"""Projektgebundene Dateiablage auf dem Server oder ueber WebDAV."""

import mimetypes
import os
import posixpath
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException

from dashboard import database, webdav
from dashboard.db_utils import db_query


def safe_rel_path(value: str, *, allow_empty: bool = True) -> str:
    """Pfadsegmente pruefen, auch bei mehrfach URL-kodierten Eingaben.

    Die Rueckgabe behaelt literale Prozentzeichen in Dateinamen bei.
    """
    decoded = value
    while True:
        if (decoded.startswith("/") or "\\" in decoded
                or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
                or ".." in decoded.split("/")):
            raise HTTPException(status_code=400, detail="Ungueltiger Pfad")
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    result = posixpath.normpath(value)
    if result == ".":
        result = ""
    if not result and not allow_empty:
        raise HTTPException(status_code=400, detail="Ein Datei- oder Ordnerpfad ist erforderlich")
    return result


def safe_filename(value: str) -> str:
    if not value or value in (".", "..") or "/" in value:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")
    decoded = value
    while True:
        safe_rel_path(decoded, allow_empty=False)
        if "/" in decoded:
            raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")
        next_value = unquote(decoded)
        if next_value == decoded:
            return value
        decoded = next_value


def storage_type(task) -> str:
    """Alte WebDAV-Zuordnungen bleiben ohne Umstellung lesbar."""
    if task["file_storage_type"] == "local":
        return "local"
    return "webdav" if task["nextcloud_path"] else "none"


def local_path(task_id: int, path: str = "") -> Path:
    """Keine frei waehlbaren Serverpfade oder symbolischen Links zulassen."""
    path = safe_rel_path(path)
    base = database.DB_DIR.resolve()
    target = base / "files" / f"task-{int(task_id)}"
    if path:
        target = target / path
    current = base
    for part in target.relative_to(base).parts:
        current = current / part
        if current.is_symlink():
            raise HTTPException(status_code=400, detail="Symbolische Links sind in der Dateiablage nicht erlaubt")
    return target


def ensure_local_directory(task_id: int):
    root = local_path(task_id)
    root.parent.mkdir(mode=0o700, exist_ok=True)
    root.mkdir(mode=0o700, exist_ok=True)


def get_task_storage(task_id: int, user: dict, *, write: bool = False):
    """Ablage mit den aktuellen Rechten des Session- oder WOPI-Benutzers laden."""
    with db_query() as db:
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
        owner = bool(user.get("is_admin")) or task["created_by"] in (None, user["id"])
        membership = db.execute(
            "SELECT can_read, can_edit FROM project_members WHERE project_id = ? AND user_id = ?",
            (task_id, user["id"]),
        ).fetchone()
        can_read = owner or task["assigned_to"] == user["id"] or bool(membership and membership["can_read"])
        can_write = owner or bool(membership and membership["can_read"] and membership["can_edit"])
        if not can_read or (write and not can_write):
            raise HTTPException(status_code=403, detail="Keine Berechtigung fuer diese Dateiablage")
        kind = storage_type(task)
        if kind == "none":
            raise HTTPException(status_code=400, detail="Keine Dateiablage zugeordnet")
        base_path = safe_rel_path(task["nextcloud_path"], allow_empty=False) if kind == "webdav" else ""
        return TaskStorage(task_id, kind, base_path, can_write)


class TaskStorage:
    def __init__(self, task_id: int, kind: str, base_path: str, can_write: bool):
        self.task_id = task_id
        self.kind = kind
        self.base_path = base_path
        self.can_write = can_write

    def _path(self, path: str, *, allow_empty: bool = False):
        path = safe_rel_path(path, allow_empty=allow_empty)
        if self.kind == "local":
            return local_path(self.task_id, path)
        return f"{self.base_path}/{path}" if path else self.base_path

    def list_directory(self, path: str = "") -> list[dict]:
        target = self._path(path, allow_empty=True)
        if self.kind == "webdav":
            entries = webdav.list_directory(target)
            config = webdav._get_config()
            if config:
                for item in entries:
                    if item.get("file_id"):
                        item["nextcloud_link"] = webdav.get_nextcloud_link(config, item["file_id"])
        else:
            entries = []
            for entry in target.iterdir():
                info = entry.lstat()
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    continue
                is_dir = stat.S_ISDIR(info.st_mode)
                entries.append({
                    "name": entry.name, "type": "directory" if is_dir else "file",
                    "size": 0 if is_dir else info.st_size,
                    "last_modified": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                    "mime_type": "" if is_dir else self._mime_type(entry),
                })
        entries.sort(key=lambda item: (item["type"] != "directory", item["name"].lower()))
        return entries

    @staticmethod
    def _mime_type(path: Path) -> str:
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    def get_file(self, path: str) -> tuple[bytes, str]:
        target = self._path(path)
        if self.kind == "webdav":
            return webdav.get_file(target)
        if not target.is_file():
            raise FileNotFoundError(path)
        return target.read_bytes(), self._mime_type(target)

    def upload_file(self, path: str, content: bytes, content_type: str = "application/octet-stream"):
        target = self._path(path)
        if self.kind == "webdav":
            return webdav.upload_file(target, content, content_type)
        if target.exists() and not target.is_file():
            raise FileExistsError(path)
        # Ersetzen erst nach vollstaendigem Schreiben, damit Fehler keine Datei zerstoeren.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".upload-", delete=False) as tmp:
                temp_path = Path(tmp.name)
                tmp.write(content)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def create_directory(self, path: str):
        target = self._path(path)
        if self.kind == "webdav":
            return webdav.create_directory(target)
        target.mkdir(mode=0o700)

    def delete_item(self, path: str):
        target = self._path(path)
        if self.kind == "webdav":
            return webdav.delete_item(target)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def move_item(self, source: str, destination: str):
        source_path = self._path(source)
        dest_path = self._path(destination)
        if self.kind == "webdav":
            return webdav.move_item(source_path, dest_path)
        if not source_path.exists():
            raise FileNotFoundError(source)
        if dest_path.exists():
            raise FileExistsError(destination)
        if source_path in dest_path.parents:
            raise HTTPException(status_code=400, detail="Ordner kann nicht in sich selbst verschoben werden")
        source_path.rename(dest_path)
