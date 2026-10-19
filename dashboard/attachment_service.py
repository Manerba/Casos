"""Flat, immutable Issue attachments and durable filesystem cleanup.

Only generated 32-character hexadecimal names ever address the filesystem.
The cleanup queue also records unfinished uploads. A file lock protects each
live upload; the short directory lock coordinates reservation, publication and
cleanup across both app processes. No SQLite lock is held during file copying.
"""

import errno
import fcntl
import io
import logging
import mimetypes
import os
import re
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote

from dashboard import database
from dashboard.audit_log import log_change, normalize_reason
from dashboard.db_utils import db_query, db_transaction
from dashboard.errors import ApplicationError
from dashboard.issue_permissions import require_active_user, require_issue_access

logger = logging.getLogger(__name__)
MAX_UPLOAD_SIZE = 500 * 1024 * 1024
COPY_CHUNK_SIZE = 64 * 1024
_STORAGE_NAME = re.compile(r"[a-f0-9]{32}\Z")
_MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z")
_SELECT = """SELECT a.*, COALESCE(NULLIF(trim(u.vorname || ' ' || u.nachname), ''), u.username, '')
    AS uploader_name FROM attachments a LEFT JOIN users u ON u.id = a.uploader_id"""


def validate_filename(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ApplicationError(400, "Ungueltiger Dateiname", code="invalid_filename", field="original_name")
    try:
        if len(value.encode("utf-8")) > 1024:
            raise UnicodeError()
    except UnicodeError as exc:
        raise ApplicationError(400, "Ungueltiger Dateiname", code="invalid_filename", field="original_name") from exc
    decoded = value
    while True:
        if decoded in {".", ".."} or any(c in decoded for c in "/\\") or any(ord(c) < 32 or ord(c) == 127 for c in decoded):
            raise ApplicationError(400, "Ungueltiger Dateiname", code="invalid_filename", field="original_name")
        next_value = unquote(decoded)
        if next_value == decoded:
            return value
        decoded = next_value


def _media_type(value, filename):
    value = value or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if not isinstance(value, str) or len(value) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ApplicationError(400, "Ungueltiger Medientyp", code="invalid_media_type", field="media_type")
    # Preserve the MIME essence, not sender-controlled header parameters.
    value = value.split(";", 1)[0].strip()
    if not _MEDIA_TYPE.fullmatch(value):
        raise ApplicationError(400, "Ungueltiger Medientyp", code="invalid_media_type", field="media_type")
    return value.lower()


def _validate_storage_name(value):
    if not isinstance(value, str) or not _STORAGE_NAME.fullmatch(value):
        raise ApplicationError(500, "Ungueltiger interner Anhangname", code="invalid_storage_name")
    return value


def _require_regular(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ApplicationError(503, "Anhangablage ist nicht sicher erreichbar", code="attachment_storage_unavailable")
    return info


@contextmanager
def _directory(*, create=False):
    """Directory descriptors prevent attachment-root symlink replacement races."""
    base = root = None
    try:
        base = os.open(database.DB_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if create:
            try:
                os.mkdir("attachments", mode=0o700, dir_fd=base)
            except FileExistsError:
                pass
        root = os.open("attachments", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
        yield root
    finally:
        if root is not None:
            os.close(root)
        if base is not None:
            os.close(base)


@contextmanager
def _directory_lock(root):
    fd = os.open(".gc.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=root)
    try:
        _require_regular(fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _checked(db, issue_id, attachment_id, user):
    _, rights = require_issue_access(db, issue_id, user)
    if type(attachment_id) is not int or attachment_id < 1:
        raise ApplicationError(422, "Ungueltige Anhang-ID", code="invalid_attachment_id", field="attachment_id")
    row = db.execute(_SELECT + " WHERE a.id = ? AND a.issue_id = ?", (attachment_id, issue_id)).fetchone()
    if row is None:
        raise ApplicationError(404, "Anhang nicht gefunden", code="attachment_not_found", field="attachment_id")
    return row, rights


def _metadata(row, rights, user):
    result = {key: row[key] for key in (
        "id", "issue_id", "original_name", "media_type", "size", "uploader_id", "uploader_name", "created_at",
    )}
    result["can_delete"] = bool(rights["can_manage"] or (row["uploader_id"] == user["id"] and rights["can_contribute"]))
    result["download_url"] = f'/api/issues/{row["issue_id"]}/attachments/{row["id"]}/download'
    return result


def list_attachments(issue_id, user, offset=0, limit=50):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
        raise ApplicationError(422, "Ungueltige Seitenauswahl", code="invalid_pagination", fields=["offset", "limit"])
    with db_query() as db:
        db.execute("BEGIN")
        _, rights = require_issue_access(db, issue_id, user)
        total = db.execute("SELECT count(*) FROM attachments WHERE issue_id = ?", (issue_id,)).fetchone()[0]
        rows = db.execute(_SELECT + " WHERE a.issue_id = ? ORDER BY a.created_at DESC, a.id DESC LIMIT ? OFFSET ?",
                          (issue_id, limit, offset)).fetchall()
        return {"items": [_metadata(row, rights, user) for row in rows], "offset": offset, "limit": limit,
                "total": total, "next_offset": offset + len(rows) if offset + len(rows) < total else None,
                "can_upload": rights["can_contribute"]}


def get_attachment(issue_id, attachment_id, user):
    with db_query() as db:
        db.execute("BEGIN")
        row, rights = _checked(db, issue_id, attachment_id, user)
        return _metadata(row, rights, user)


def open_attachment(issue_id, attachment_id, user):
    """Return (public metadata, open binary stream); the caller must close it.

    Prefer this over reopening attachment_path: O_NOFOLLOW and directory-relative
    opens keep downloads/previews safe against replacement of a stored path.
    """
    with db_query() as db:
        db.execute("BEGIN")
        row, rights = _checked(db, issue_id, attachment_id, user)
        name = _validate_storage_name(row["storage_name"])
        try:
            with _directory() as root:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
                try:
                    info = _require_regular(fd)
                    if info.st_size != row["size"]:
                        raise ApplicationError(503, "Gespeicherter Anhang ist unvollstaendig", code="attachment_storage_unavailable")
                    stream = os.fdopen(fd, "rb")
                except BaseException:
                    os.close(fd)
                    raise
            return _metadata(row, rights, user), stream
        except FileNotFoundError as exc:
            raise ApplicationError(404, "Anhangdatei nicht gefunden", code="attachment_file_missing") from exc
        except OSError as exc:
            raise ApplicationError(503, "Anhangablage ist nicht erreichbar", code="attachment_storage_unavailable") from exc


def attachment_path(issue_id, attachment_id, user) -> Path:
    """Authenticated internal path. Actual consumers should use open_attachment."""
    with db_query() as db:
        row, _ = _checked(db, issue_id, attachment_id, user)
        name = _validate_storage_name(row["storage_name"])
    _, stream = open_attachment(issue_id, attachment_id, user)
    stream.close()
    return database.DB_DIR / "attachments" / name


def _reserve_upload(root, issue_id, user):
    fd = None
    with _directory_lock(root):
        name = secrets.token_hex(16)
        # Never replace an existing file, even if a generated name collides.
        for candidate in (name, name + ".part"):
            try:
                os.stat(candidate, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ApplicationError(503, "Interner Anhangname bereits belegt", code="attachment_storage_unavailable")
        try:
            with db_transaction() as db:
                db.execute("BEGIN IMMEDIATE")
                require_issue_access(db, issue_id, user, "contribute")
                db.execute("INSERT INTO attachment_gc(storage_name) VALUES(?)", (name,))
            # Commit the reservation before creating a file. A process dying
            # immediately after open() must leave a durable cleanup job. GC
            # cannot consume the reservation while this directory lock is held.
            fd = os.open(name + ".part", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
            fcntl.flock(fd, fcntl.LOCK_EX)
            return name, fd
        except BaseException:
            if fd is not None:
                os.close(fd)
                os.unlink(name + ".part", dir_fd=root)
            raise


def add_attachment(issue_id, user, *, original_name, content, media_type=None, reason=None):
    """Store immutable bytes or a binary read(size) stream without full buffering.

    Returns public metadata. The caller owns and closes a supplied stream.
    Current contribution rights/token status are checked before and after copying.
    """
    reason = normalize_reason(reason)
    original_name = validate_filename(original_name)
    media_type = _media_type(media_type, original_name)
    source = io.BytesIO(content) if isinstance(content, bytes) else content
    if not callable(getattr(source, "read", None)):
        raise ApplicationError(422, "Binaerer Dateiinhalt erforderlich", code="invalid_attachment_content", field="content")
    with db_query() as db:
        require_issue_access(db, issue_id, user, "contribute")
    name = None
    try:
        with _directory(create=True) as root:
            name, fd = _reserve_upload(root, issue_id, user)
            with os.fdopen(fd, "wb") as target:
                size = 0
                while True:
                    chunk = source.read(min(COPY_CHUNK_SIZE, MAX_UPLOAD_SIZE - size + 1))
                    if not isinstance(chunk, bytes):
                        raise ApplicationError(422, "Binaerer Dateiinhalt erforderlich", code="invalid_attachment_content", field="content")
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_SIZE:
                        raise ApplicationError(413, "Anhang zu gross (max. 500 MiB)", code="attachment_too_large", field="content")
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
                with _directory_lock(root), db_transaction() as db:
                    db.execute("BEGIN IMMEDIATE")
                    current = require_active_user(db, user)
                    _, rights = require_issue_access(db, issue_id, current, "contribute")
                    os.replace(name + ".part", name, src_dir_fd=root, dst_dir_fd=root)
                    os.fsync(root)
                    attachment_id = db.execute(
                        "INSERT INTO attachments(issue_id,storage_name,original_name,media_type,size,uploader_id) VALUES(?,?,?,?,?,?)",
                        (issue_id, name, original_name, media_type, size, current["id"]),
                    ).lastrowid
                    log_change(current, "attachment", attachment_id, "create",
                               {"issue_id": issue_id, "original_name": original_name, "media_type": media_type, "size": size},
                               reason=reason, db=db)
                    db.execute("DELETE FROM attachment_gc WHERE storage_name = ?", (name,))
                    row = db.execute(_SELECT + " WHERE a.id = ?", (attachment_id,)).fetchone()
                    result = _metadata(row, rights, current)
            return result
    except OSError as exc:
        logger.warning("Attachment storage failed (%s)", type(exc).__name__)
        raise ApplicationError(503, "Anhang konnte nicht gespeichert werden", code="attachment_storage_unavailable") from exc
    finally:
        if name is not None:
            # A publication/audit/commit failure leaves the durable reservation.
            # Cleanup failure must not hide the original error or successful save.
            _process_gc_name(name)


def delete_attachment(issue_id, attachment_id, user, reason=None):
    reason = normalize_reason(reason)
    with db_transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = require_active_user(db, user)
        row, rights = _checked(db, issue_id, attachment_id, current)
        if not _metadata(row, rights, current)["can_delete"]:
            raise ApplicationError(403, "Keine Berechtigung zum Loeschen dieses Anhangs", code="permission_denied")
        db.execute("INSERT OR IGNORE INTO attachment_gc(storage_name) VALUES(?)", (row["storage_name"],))
        db.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        log_change(current, "attachment", attachment_id, "delete",
                   {"issue_id": issue_id, "original_name": row["original_name"], "size": row["size"]}, reason=reason, db=db)
    _process_gc_name(row["storage_name"])
    return {"ok": True}


def _process_gc_name(name):
    """Return removed/skipped/failed. Never follow names from a corrupt queue."""
    opened = []
    try:
        with db_query() as db:
            if not db.execute("SELECT 1 FROM attachment_gc WHERE storage_name = ?", (name,)).fetchone():
                return "skipped"
        _validate_storage_name(name)
        with _directory(create=True) as root, _directory_lock(root), db_transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM attachment_gc WHERE storage_name = ?", (name,)).fetchone():
                return "skipped"
            if db.execute("SELECT 1 FROM attachments WHERE storage_name = ?", (name,)).fetchone():
                # A stale/corrupt job must never delete a published attachment.
                db.execute("DELETE FROM attachment_gc WHERE storage_name = ?", (name,))
                return "removed"
            for candidate in (name + ".part", name):
                try:
                    fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
                except FileNotFoundError:
                    continue
                opened.append((candidate, fd))
                _require_regular(fd)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return "skipped"
            for candidate, fd in opened:
                now, original = os.stat(candidate, dir_fd=root, follow_symlinks=False), os.fstat(fd)
                if (now.st_dev, now.st_ino) != (original.st_dev, original.st_ino):
                    raise OSError(errno.EBUSY, "Attachment changed during cleanup")
                os.unlink(candidate, dir_fd=root)
            os.fsync(root)
            db.execute("DELETE FROM attachment_gc WHERE storage_name = ?", (name,))
        return "removed"
    except Exception as exc:
        # Bound and redact persisted errors; do not expose server paths/contents.
        error = getattr(exc, "code", None) or type(exc).__name__
        logger.warning("Attachment cleanup deferred (%s)", error)
        try:
            with db_transaction() as db:
                db.execute("UPDATE attachment_gc SET last_error = ? WHERE storage_name = ?", (str(error)[:200], name))
        except Exception:
            logger.exception("Unable to record attachment cleanup failure")
        return "failed"
    finally:
        for _, fd in opened:
            os.close(fd)


def process_attachment_gc(limit=100):
    """Retry queued Issue/attachment deletions and interrupted uploads safely."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    with db_query() as db:
        names = [row[0] for row in db.execute("SELECT storage_name FROM attachment_gc ORDER BY queued_at, storage_name LIMIT ?", (limit,))]
    outcomes = [_process_gc_name(name) for name in names]
    with db_query() as db:
        pending = db.execute("SELECT count(*) FROM attachment_gc").fetchone()[0]
    return {"removed": outcomes.count("removed"), "pending": pending, "failed": outcomes.count("failed")}
