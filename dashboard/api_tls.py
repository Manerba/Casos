"""
Tareas - TLS Admin API-Router
TLS-Konfiguration: Zertifikate verwalten, aktivieren/deaktivieren.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from dashboard.database import get_db
from dashboard.auth import get_admin_user
from dashboard.tls_utils import validate_cert_files

router = APIRouter(prefix="/api/admin/tls", tags=["tls"])


# ============================================================
# Pydantic-Modelle
# ============================================================

class TlsConfigRequest(BaseModel):
    cert_path: str
    key_path: str
    enabled: int = 0


class TlsValidateRequest(BaseModel):
    cert_path: str
    key_path: str


# ============================================================
# Endpoints
# ============================================================

@router.get("/config")
async def get_tls_config(user=Depends(get_admin_user)):
    """Aktuelle TLS-Konfiguration laden."""
    db = get_db()
    try:
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
    finally:
        db.close()


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

    db = get_db()
    try:
        existing = db.execute("SELECT id FROM tls_config WHERE id = 1").fetchone()
        if existing:
            db.execute(
                "UPDATE tls_config SET cert_path = ?, key_path = ?, enabled = ? WHERE id = 1",
                (cert_path, key_path, req.enabled),
            )
        else:
            db.execute(
                "INSERT INTO tls_config (id, cert_path, key_path, enabled) VALUES (1, ?, ?, ?)",
                (cert_path, key_path, req.enabled),
            )
        db.commit()
        return {"status": "ok", "message": "TLS-Konfiguration gespeichert"}
    finally:
        db.close()


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
    db = get_db()
    try:
        db.execute("DELETE FROM tls_config WHERE id = 1")
        db.commit()
        return {"status": "ok", "message": "TLS-Konfiguration geloescht"}
    finally:
        db.close()
