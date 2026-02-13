"""
Tareas - API-Router fuer App-Konfiguration (Server-Adresse etc.).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from dashboard.database import get_db
from dashboard.auth import get_admin_user

app_config_router = APIRouter()


class AppConfigSave(BaseModel):
    server_address: str


@app_config_router.get("/api/admin/app/config")
async def get_app_config(user=Depends(get_admin_user)):
    """App-Config laden."""
    db = get_db()
    try:
        row = db.execute("SELECT * FROM app_config WHERE id = 1").fetchone()
        if not row:
            return {"config": None}
        return {"config": dict(row)}
    finally:
        db.close()


@app_config_router.post("/api/admin/app/config")
async def save_app_config(data: AppConfigSave, user=Depends(get_admin_user)):
    """App-Config speichern (UPSERT)."""
    address = data.server_address.strip()
    # Protokoll-Prefix entfernen falls angegeben
    for prefix in ("https://", "http://"):
        if address.lower().startswith(prefix):
            address = address[len(prefix):]
            break
    # Trailing Slash entfernen
    address = address.rstrip("/")

    db = get_db()
    try:
        db.execute(
            """INSERT INTO app_config (id, server_address)
               VALUES (1, ?)
               ON CONFLICT(id) DO UPDATE SET
                   server_address = excluded.server_address""",
            (address,),
        )
        db.commit()
        return {"message": "App-Konfiguration gespeichert"}
    finally:
        db.close()
