"""
Casos - API-Router fuer App-Konfiguration (Server-Adresse etc.).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.db_utils import db_query, db_transaction
from dashboard.auth import get_admin_user
from dashboard.audit_log import log_change
from dashboard.logging_config import get_security_logger

security_log = get_security_logger()

app_config_router = APIRouter()


class AppConfigSave(BaseModel):
    server_address: str


@app_config_router.get("/api/admin/app/config")
async def get_app_config(user=Depends(get_admin_user)):
    """App-Config laden."""
    with db_query() as db:
        row = db.execute("SELECT * FROM app_config WHERE id = 1").fetchone()
        if not row:
            return {"config": None}
        return {"config": dict(row)}


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
    if not address or any(char.isspace() for char in address) or any(char in address for char in "<>\\?#@"):
        raise HTTPException(status_code=400, detail="Gueltige Server-Adresse ist erforderlich")

    with db_transaction() as db:
        db.execute(
            """INSERT INTO app_config (id, server_address)
               VALUES (1, ?)
               ON CONFLICT(id) DO UPDATE SET
                   server_address = excluded.server_address""",
            (address,),
        )
        log_change(user, "app_config", 1, "update", {"server_address": address}, db=db)
        security_log.info("CONFIG_CHANGED section=app by=%s", user["username"])
        return {"message": "App-Konfiguration gespeichert"}
