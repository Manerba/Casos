"""
Tareas - Nextcloud API-Router
Admin-Konfiguration und Dateioperationen via WebDAV.
"""

import asyncio
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional

from dashboard.database import get_db
from dashboard.auth import get_admin_user, get_current_user
from dashboard import webdav


# ============================================================
# Router
# ============================================================

admin_router = APIRouter(prefix="/api/admin/nextcloud", tags=["nextcloud-admin"])
files_router = APIRouter(tags=["nextcloud-files"])


# ============================================================
# Pydantic-Modelle
# ============================================================

class NextcloudConfigRequest(BaseModel):
    server_url: str
    username: str
    password: str
    base_path: str


class MoveRequest(BaseModel):
    source: str
    destination: str


class MkdirRequest(BaseModel):
    name: str


# ============================================================
# Admin-Endpoints (nur Admins)
# ============================================================

@admin_router.get("/config")
async def get_nextcloud_config(user=Depends(get_admin_user)):
    """Aktuelle Nextcloud-Konfiguration laden (Passwort maskiert)."""
    db = get_db()
    try:
        row = db.execute("SELECT * FROM nextcloud_config WHERE id = 1").fetchone()
        if not row:
            return {"config": None}
        return {
            "config": {
                "server_url": row["server_url"],
                "username": row["username"],
                "password": "********",
                "base_path": row["base_path"],
            }
        }
    finally:
        db.close()


@admin_router.post("/config")
async def save_nextcloud_config(data: NextcloudConfigRequest, user=Depends(get_admin_user)):
    """Nextcloud-Konfiguration speichern (nach erfolgreichem Verbindungstest)."""
    if not data.server_url.strip():
        raise HTTPException(status_code=400, detail="Server-URL ist Pflichtfeld")
    if not data.username.strip():
        raise HTTPException(status_code=400, detail="Benutzername ist Pflichtfeld")
    if not data.password.strip():
        raise HTTPException(status_code=400, detail="Passwort ist Pflichtfeld")
    if not data.base_path.strip():
        raise HTTPException(status_code=400, detail="Wurzelverzeichnis ist Pflichtfeld")

    # Passwort ggf. aus DB holen wenn nicht geaendert
    actual_password = data.password
    if data.password == "********":
        db = get_db()
        try:
            existing = db.execute("SELECT password FROM nextcloud_config WHERE id = 1").fetchone()
            if existing:
                actual_password = existing["password"]
            else:
                raise HTTPException(status_code=400, detail="Kein gespeichertes Passwort vorhanden")
        finally:
            db.close()

    # Verbindungstest (in Thread-Pool)
    success, error = await asyncio.to_thread(
        webdav.test_connection,
        data.server_url.strip(),
        data.username.strip(),
        actual_password,
        data.base_path.strip(),
    )

    if not success:
        raise HTTPException(status_code=400, detail=f"Verbindungstest fehlgeschlagen: {error}")

    # Config speichern (UPSERT)
    db = get_db()
    try:
        existing = db.execute("SELECT id FROM nextcloud_config WHERE id = 1").fetchone()

        if existing:
            if data.password == "********":
                db.execute(
                    """UPDATE nextcloud_config SET server_url = ?, username = ?,
                       base_path = ? WHERE id = 1""",
                    (data.server_url.strip(), data.username.strip(), data.base_path.strip()),
                )
            else:
                db.execute(
                    """UPDATE nextcloud_config SET server_url = ?, username = ?,
                       password = ?, base_path = ? WHERE id = 1""",
                    (data.server_url.strip(), data.username.strip(),
                     data.password, data.base_path.strip()),
                )
        else:
            db.execute(
                """INSERT INTO nextcloud_config (id, server_url, username, password, base_path)
                   VALUES (1, ?, ?, ?, ?)""",
                (data.server_url.strip(), data.username.strip(),
                 actual_password, data.base_path.strip()),
            )

        db.commit()
        return {"message": "Nextcloud-Konfiguration gespeichert"}
    finally:
        db.close()


@admin_router.delete("/config")
async def delete_nextcloud_config(user=Depends(get_admin_user)):
    """Nextcloud-Konfiguration loeschen."""
    db = get_db()
    try:
        db.execute("DELETE FROM nextcloud_config WHERE id = 1")
        # nextcloud_path in allen tasks zuruecksetzen
        db.execute("UPDATE tasks SET nextcloud_path = NULL WHERE nextcloud_path IS NOT NULL")
        db.commit()
        return {"message": "Nextcloud-Konfiguration geloescht"}
    finally:
        db.close()


# ============================================================
# Verzeichniszuordnung
# ============================================================

@files_router.get("/api/nextcloud/directories")
async def get_nextcloud_directories(
    path: str = "",
    user=Depends(get_current_user),
):
    """Unterordner auflisten (optional ab Unterpfad, fuer Browse-Dialog)."""
    try:
        dirs = await asyncio.to_thread(webdav.list_subdirectories, path)
        return {
            "directories": [
                {"name": d["name"], "path": f"{path}/{d['name']}".strip("/")}
                for d in dirs
            ],
            "current_path": path,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@files_router.get("/api/nextcloud/status")
async def get_nextcloud_status(user=Depends(get_current_user)):
    """Pruefen ob Nextcloud konfiguriert ist (fuer Frontend)."""
    db = get_db()
    try:
        row = db.execute("SELECT id FROM nextcloud_config WHERE id = 1").fetchone()
        return {"configured": row is not None}
    finally:
        db.close()


# ============================================================
# Datei-Endpoints (authentifizierte Benutzer)
# ============================================================

def _get_task_nextcloud_path(task_id: int, user: dict) -> str:
    """
    Nextcloud-Pfad fuer eine Aufgabe/Projekt ermitteln und Zugriff pruefen.
    Gibt den relativen Pfad zum Verzeichnis zurueck.
    """
    db = get_db()
    try:
        task = db.execute(
            "SELECT id, task_type, nextcloud_path, created_by FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if not task:
            raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
        if not task["nextcloud_path"]:
            raise HTTPException(status_code=400, detail="Kein Nextcloud-Verzeichnis zugeordnet")

        # Zugriffspruefung: Ersteller, Legacy oder Teammitglied
        is_creator = task["created_by"] == user["id"]
        is_legacy = task["created_by"] is None
        if not is_creator and not is_legacy:
            membership = db.execute(
                "SELECT can_read FROM project_members WHERE project_id = ? AND user_id = ?",
                (task_id, user["id"]),
            ).fetchone()
            if not membership or not membership["can_read"]:
                raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Projekt")

        return task["nextcloud_path"]
    finally:
        db.close()


@files_router.get("/api/tasks/{task_id}/files")
async def list_task_files(
    task_id: int,
    path: str = "",
    user=Depends(get_current_user),
):
    """Verzeichnisinhalt eines Projekt-Verzeichnisses auflisten."""
    nc_path = _get_task_nextcloud_path(task_id, user)

    # Pfad zusammenbauen: nc_path + relativer Unterpfad
    full_path = nc_path
    if path:
        full_path = f"{nc_path}/{path.strip('/')}"

    try:
        entries = await asyncio.to_thread(webdav.list_directory, full_path)

        # Nextcloud-Config fuer Direktlinks
        config = webdav._get_config()

        items = []
        for e in entries:
            item = {
                "name": e["name"],
                "type": e["type"],
                "size": e["size"],
                "last_modified": e["last_modified"],
                "mime_type": e["mime_type"],
            }
            if config and e.get("file_id"):
                item["nextcloud_link"] = webdav.get_nextcloud_link(config, e["file_id"])
            items.append(item)

        # Sortierung: Ordner zuerst, dann alphabetisch
        items.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))

        return {"items": items, "path": path}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Verzeichnis nicht gefunden: {path}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@files_router.get("/api/tasks/{task_id}/files/download")
async def download_task_file(
    task_id: int,
    path: str = Query(..., description="Relativer Pfad zur Datei"),
    inline: bool = Query(False, description="Datei inline anzeigen statt herunterladen"),
    user=Depends(get_current_user),
):
    """Datei aus dem Projektverzeichnis herunterladen oder inline anzeigen."""
    nc_path = _get_task_nextcloud_path(task_id, user)
    full_path = f"{nc_path}/{path.strip('/')}"

    try:
        content, content_type = await asyncio.to_thread(webdav.get_file, full_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {path}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Dateiname aus Pfad extrahieren
    filename = path.rsplit("/", 1)[-1] if "/" in path else path
    disposition = "inline" if inline else "attachment"

    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
        },
    )


@files_router.post("/api/tasks/{task_id}/files/upload")
async def upload_task_file(
    task_id: int,
    file: UploadFile = File(...),
    path: str = Query("", description="Zielordner (relativ)"),
    user=Depends(get_current_user),
):
    """Datei in das Projektverzeichnis hochladen."""
    nc_path = _get_task_nextcloud_path(task_id, user)

    # Ziel-Pfad zusammenbauen
    target = nc_path
    if path:
        target = f"{nc_path}/{path.strip('/')}"
    target = f"{target}/{file.filename}"

    content = await file.read()
    content_type = file.content_type or "application/octet-stream"

    try:
        await asyncio.to_thread(webdav.upload_file, target, content, content_type)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": f"Datei '{file.filename}' hochgeladen", "filename": file.filename}


@files_router.post("/api/tasks/{task_id}/files/mkdir")
async def create_task_directory(
    task_id: int,
    body: MkdirRequest,
    path: str = Query("", description="Uebergeordneter Ordner (relativ)"),
    user=Depends(get_current_user),
):
    """Neuen Ordner im Projektverzeichnis erstellen."""
    nc_path = _get_task_nextcloud_path(task_id, user)

    target = nc_path
    if path:
        target = f"{nc_path}/{path.strip('/')}"
    target = f"{target}/{body.name}"

    try:
        await asyncio.to_thread(webdav.create_directory, target)
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Ordner existiert bereits: {body.name}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": f"Ordner '{body.name}' erstellt"}


@files_router.delete("/api/tasks/{task_id}/files")
async def delete_task_file(
    task_id: int,
    path: str = Query(..., description="Zu loeschender Pfad (relativ)"),
    user=Depends(get_current_user),
):
    """Datei oder Ordner im Projektverzeichnis loeschen."""
    nc_path = _get_task_nextcloud_path(task_id, user)
    full_path = f"{nc_path}/{path.strip('/')}"

    try:
        await asyncio.to_thread(webdav.delete_item, full_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Nicht gefunden: {path}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": "Geloescht"}


@files_router.put("/api/tasks/{task_id}/files/move")
async def move_task_file(
    task_id: int,
    body: MoveRequest,
    user=Depends(get_current_user),
):
    """Datei/Ordner im Projektverzeichnis verschieben oder umbenennen."""
    nc_path = _get_task_nextcloud_path(task_id, user)
    source = f"{nc_path}/{body.source.strip('/')}"
    dest = f"{nc_path}/{body.destination.strip('/')}"

    try:
        await asyncio.to_thread(webdav.move_item, source, dest)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Quelle nicht gefunden: {body.source}")
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Ziel existiert bereits: {body.destination}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": "Verschoben"}
