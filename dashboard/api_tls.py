"""
Casos - TLS Admin API-Router
TLS-Konfiguration: Zertifikate verwalten, aktivieren/deaktivieren.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict, Field

from dashboard.db_utils import db_query, db_transaction, upsert_singleton_config
from dashboard.auth import get_admin_user
from dashboard.audit_log import log_change
from dashboard.tls_utils import validate_cert_files, get_tls_verify_config
from dashboard.logging_config import get_security_logger

security_log = get_security_logger()

router = APIRouter(prefix="/api/admin/tls", tags=["tls"])


# ============================================================
# Pydantic-Modelle
# ============================================================

class TlsConfigRequest(BaseModel):
    cert_path: str
    key_path: str
    enabled: int = Field(default=0, ge=0, le=1)


class TlsValidateRequest(BaseModel):
    cert_path: str
    key_path: str


class TlsVerifyConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verify_smtp: int = Field(default=0, ge=0, le=1)
    verify_ldap: int = Field(default=0, ge=0, le=1)


# ============================================================
# Endpoints
# ============================================================

@router.get("/config")
async def get_tls_config(user=Depends(get_admin_user)):
    """Aktuelle TLS-Konfiguration laden."""
    with db_query() as db:
        row = db.execute("SELECT * FROM tls_config WHERE id = 1").fetchone()
        if not row:
            return {"config": None}
        return {
            "config": {
                "enabled": row["enabled"],
                "cert_path": row["cert_path"],
                "key_path": row["key_path"],
                "created_at": row["created_at"],
            }
        }


@router.post("/config")
async def save_tls_config(req: TlsConfigRequest, user=Depends(get_admin_user)):
    """TLS-Konfiguration speichern (validiert Zertifikate)."""
    cert_path = req.cert_path.strip()
    key_path = req.key_path.strip()

    if not cert_path or not key_path:
        raise HTTPException(status_code=400, detail="Zertifikat- und Key-Pfad sind erforderlich")

    # Dateien validieren
    error = validate_cert_files(cert_path, key_path)
    if error:
        raise HTTPException(status_code=400, detail=error)

    with db_transaction() as db:
        upsert_singleton_config(db, "tls_config", {
            "cert_path": cert_path,
            "key_path": key_path,
            "enabled": req.enabled,
        })
        log_change(user, "tls_config", 1, "update", {"cert_path": cert_path, "key_path": key_path, "enabled": req.enabled}, db=db)
        security_log.info("CONFIG_CHANGED section=tls by=%s", user["username"])
        return {"status": "ok", "message": "TLS-Konfiguration gespeichert"}


@router.post("/validate")
async def validate_tls_files(req: TlsValidateRequest, user=Depends(get_admin_user)):
    """Zertifikat-Dateien pruefen ohne zu speichern."""
    cert_path = req.cert_path.strip()
    key_path = req.key_path.strip()

    if not cert_path or not key_path:
        raise HTTPException(status_code=400, detail="Beide Pfade sind erforderlich")

    error = validate_cert_files(cert_path, key_path)
    if error:
        return {"valid": False, "error": error}
    return {"valid": True, "message": "Zertifikat und Key sind gueltig"}


@router.delete("/config")
async def delete_tls_config(user=Depends(get_admin_user)):
    """TLS-Konfiguration loeschen (zurueck zu HTTP)."""
    with db_transaction() as db:
        db.execute("DELETE FROM tls_config WHERE id = 1")
        log_change(user, "tls_config", 1, "delete", db=db)
        security_log.info("CONFIG_CHANGED section=tls_deleted by=%s", user["username"])
        return {"status": "ok", "message": "TLS-Konfiguration geloescht"}


@router.get("/verify")
async def get_verify_config(user=Depends(get_admin_user)):
    """Zertifikatsvalidierungs-Konfiguration laden."""
    return {"config": get_tls_verify_config()}


@router.post("/verify")
async def save_verify_config(req: TlsVerifyConfigRequest, user=Depends(get_admin_user)):
    """Zertifikatsvalidierungs-Konfiguration speichern."""
    with db_transaction() as db:
        upsert_singleton_config(db, "tls_verify_config", {
            "verify_smtp": req.verify_smtp,
            "verify_ldap": req.verify_ldap,
        })
        log_change(user, "tls_config", 1, "update", {"verify_smtp": req.verify_smtp, "verify_ldap": req.verify_ldap}, db=db)
        security_log.info("CONFIG_CHANGED section=tls_verify by=%s", user["username"])
        return {"status": "ok", "message": "Zertifikatsvalidierung gespeichert"}
