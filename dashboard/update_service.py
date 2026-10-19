"""Chronological Issue updates shared by REST and MCP.

Creation and correction rules ported from Tareas 7157218 (0.0.1+144),
note_service.create_handoff; adapted to flat Issues, current permissions,
pagination and atomic audit. Personal notes and subtask branches are absent.
"""

import hashlib
import re
from datetime import datetime, timezone

from dashboard.audit_log import log_change, normalize_reason
from dashboard.db_utils import db_query, db_transaction
from dashboard.errors import ApplicationError
from dashboard.issue_permissions import require_active_user, require_issue_access

UPDATE_EDIT_SECONDS = 300
UPDATE_MAX_BYTES = 1024 * 1024


def _utc_now():
    return datetime.now(timezone.utc)


def update_revision(content, content_format="markdown"):
    return hashlib.sha256(f"{content_format}\0{content}".encode("utf-8")).hexdigest()


def _content(content):
    if not isinstance(content, str):
        raise ApplicationError(422, "updates.invalidContent", code="invalid_content", field="content")
    if not content.strip():
        raise ApplicationError(422, "updates.empty", code="empty_content", field="content")
    try:
        size = len(content.encode("utf-8"))
    except UnicodeError as exc:
        raise ApplicationError(422, "updates.invalidContent", code="invalid_content", field="content") from exc
    if size > UPDATE_MAX_BYTES:
        raise ApplicationError(422, "updates.tooLarge", code="content_too_large", field="content")
    return content


def _in_edit_window(entry):
    try:
        created = datetime.fromisoformat(entry["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (_utc_now() - created).total_seconds()
        return 0 <= age < UPDATE_EDIT_SECONDS
    except (ValueError, TypeError):
        return False


def _can_write(entry, user, rights):
    return bool(user["is_admin"] or (rights["can_contribute"] and entry["user_id"] == user["id"] and _in_edit_window(entry)))


def _serialize(row, current, rights):
    item = dict(row)
    item["user_name"] = item.pop("author_name", "").strip() or item.pop("author_username", "") or ""
    item.pop("author_username", None)
    item["can_write"] = _can_write(row, current, rights)
    item["can_delete"] = bool(current["is_admin"])
    item["revision"] = update_revision(item["content"], item["content_format"])
    return item


_SELECT = ("SELECT e.*, COALESCE(u.vorname, '') || ' ' || COALESCE(u.nachname, '') AS author_name, "
           "COALESCE(u.username, '') AS author_username FROM issue_updates e LEFT JOIN users u ON u.id = e.user_id ")


def _get(db, issue_id, update_id):
    if type(update_id) is not int or update_id < 1:
        raise ApplicationError(422, "updates.invalidId", code="invalid_update_id", field="update_id")
    row = db.execute(_SELECT + "WHERE e.issue_id = ? AND e.id = ?", (issue_id, update_id)).fetchone()
    if row is None:
        raise ApplicationError(404, "updates.notFound", code="update_not_found", field="update_id")
    return row


def list_updates(issue_id, user, offset=0, limit=50):
    if type(offset) is not int or offset < 0:
        raise ApplicationError(422, "offset muss eine nichtnegative ganze Zahl sein", code="invalid_offset", field="offset")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ApplicationError(422, "limit muss zwischen 1 und 500 liegen", code="invalid_limit", field="limit")
    with db_query() as db:
        db.execute("BEGIN")
        current = require_active_user(db, user)
        _, rights = require_issue_access(db, issue_id, current)
        total = db.execute("SELECT COUNT(*) FROM issue_updates WHERE issue_id = ?", (issue_id,)).fetchone()[0]
        rows = db.execute(_SELECT + "WHERE e.issue_id = ? ORDER BY e.created_at DESC, e.id DESC LIMIT ? OFFSET ?",
                          (issue_id, limit, offset)).fetchall()
        return {"items": [_serialize(row, current, rights) for row in rows], "offset": offset,
                "limit": limit, "total": total, "next_offset": offset + len(rows) if offset + len(rows) < total else None,
                "can_create": rights["can_contribute"]}


def get_update(issue_id, update_id, user):
    with db_query() as db:
        db.execute("BEGIN")
        current = require_active_user(db, user)
        _, rights = require_issue_access(db, issue_id, current)
        return _serialize(_get(db, issue_id, update_id), current, rights)


def create_update(issue_id, content, user, reason=None):
    content = _content(content)
    reason = normalize_reason(reason)
    with db_transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = require_active_user(db, user)
        _, rights = require_issue_access(db, issue_id, current, "contribute")
        created_at = _utc_now().strftime('%Y-%m-%d %H:%M:%S.%f')
        cursor = db.execute("INSERT INTO issue_updates(issue_id,user_id,content,content_format,created_at,updated_at) VALUES(?,?,?,'markdown',?,?)",
                            (issue_id, current["id"], content, created_at, created_at))
        update_id = cursor.lastrowid
        log_change(current, "update", update_id, "create", {"issue_id": issue_id, "owner_user_id": current["id"],
                   "content_len": len(content)}, reason=reason, db=db)
        result = _serialize(_get(db, issue_id, update_id), current, rights)
    from dashboard.mail_service import notify_issue_event
    notify_issue_event(issue_id, "new_update", current["id"], update_id=update_id)
    return result


def edit_update(issue_id, update_id, content, user, revision, reason=None):
    content = _content(content)
    reason = normalize_reason(reason)
    if revision is None:
        raise ApplicationError(422, "updates.revisionRequired", code="revision_required", field="revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
        raise ApplicationError(422, "updates.invalidRevision", code="invalid_revision", field="revision")
    with db_transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = require_active_user(db, user)
        _, rights = require_issue_access(db, issue_id, current, "contribute")
        row = _get(db, issue_id, update_id)
        if not current["is_admin"]:
            if row["user_id"] != current["id"]:
                raise ApplicationError(403, "updates.editDenied", code="permission_denied", field="update_id")
            if not _in_edit_window(row):
                raise ApplicationError(403, "updates.editWindowExpired", code="update_edit_window_expired", field="update_id")
        if revision != update_revision(row["content"], row["content_format"]):
            raise ApplicationError(409, "updates.conflict", code="revision_conflict", field="revision")
        if row["content"] != content or row["content_format"] != "markdown":
            db.execute("UPDATE issue_updates SET content=?, content_format='markdown', updated_at=? WHERE id=?",
                       (content, _utc_now().strftime('%Y-%m-%d %H:%M:%S.%f'), update_id))
            log_change(current, "update", update_id, "update", {"issue_id": issue_id, "owner_user_id": row["user_id"],
                       "content_len": len(content)}, reason=reason, db=db)
        return _serialize(_get(db, issue_id, update_id), current, rights)


def delete_update(issue_id, update_id, user, reason=None):
    reason = normalize_reason(reason)
    with db_transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = require_active_user(db, user)
        require_issue_access(db, issue_id, current)
        if not current["is_admin"]:
            raise ApplicationError(403, "updates.deleteDenied", code="permission_denied", field="update_id")
        row = _get(db, issue_id, update_id)
        db.execute("DELETE FROM issue_updates WHERE id = ?", (update_id,))
        log_change(current, "update", update_id, "delete", {"issue_id": issue_id, "owner_user_id": row["user_id"]},
                   reason=reason, db=db)
    return {"ok": True}
