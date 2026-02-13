"""
Tareas - Auth API-Router
Login, Logout, Me, Passwort-Aenderung.
"""

import asyncio
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dashboard.database import get_db
from dashboard.auth import (
    verify_password,
    hash_password,
    create_session,
    delete_session,
    set_session_cookie,
    delete_session_cookie,
    get_current_user,
    COOKIE_NAME,
    unsign_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ============================================================
# Pydantic-Modelle
# ============================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


# ============================================================
# Endpoints
# ============================================================

@router.post("/login")
async def login(data: LoginRequest):
    """Benutzer anmelden, Session erstellen, Cookie setzen."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM users WHERE username = ?", (data.username,)
        ).fetchone()
    finally:
        db.close()

    if not row:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")

    auth_source = row["auth_source"] if "auth_source" in row.keys() else "local"
    is_active = row["is_active"] if "is_active" in row.keys() else 1

    if auth_source == "ldap":
        # LDAP-Benutzer: Pruefen ob aktiv
        if not is_active:
            raise HTTPException(status_code=401, detail="Benutzer deaktiviert")

        # LDAP-Config laden und Authentifizierung
        config_db = get_db()
        try:
            config_row = config_db.execute("SELECT * FROM ldap_config WHERE id = 1").fetchone()
        finally:
            config_db.close()

        if not config_row:
            raise HTTPException(status_code=503, detail="LDAP-Server nicht konfiguriert")

        from dashboard.tls_utils import get_tls_verify_config
        verify_cfg = get_tls_verify_config()
        config = {
            "server": config_row["server"],
            "port": config_row["port"],
            "use_ssl": config_row["use_ssl"],
            "bind_dn": config_row["bind_dn"],
            "bind_password": config_row["bind_password"],
            "search_base": config_row["search_base"],
            "verify_cert": verify_cfg["verify_ldap"],
        }

        try:
            from dashboard.ldap_utils import authenticate_user
            success, error = await asyncio.to_thread(
                authenticate_user, config, data.username, data.password
            )
        except Exception:
            raise HTTPException(status_code=503, detail="LDAP-Server nicht erreichbar")

        if not success:
            raise HTTPException(status_code=401, detail=f"LDAP-Login fehlgeschlagen: {error}")
    else:
        # Lokaler Benutzer: Passwort-Hash pruefen
        if not verify_password(data.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Ungueltige Anmeldedaten")

    token = create_session(row["id"])

    user_data = {
        "id": row["id"],
        "username": row["username"],
        "vorname": row["vorname"],
        "nachname": row["nachname"],
        "is_admin": row["is_admin"],
    }

    response = JSONResponse(content={"message": "Angemeldet", "user": user_data})
    set_session_cookie(response, token)
    return response


@router.post("/logout")
async def logout(request: Request, user=Depends(get_current_user)):
    """Abmelden: Session und Cookie loeschen."""
    signed = request.cookies.get(COOKIE_NAME)
    if signed:
        token = unsign_token(signed)
        if token:
            delete_session(token)

    response = JSONResponse(content={"message": "Abgemeldet"})
    delete_session_cookie(response)
    return response


@router.get("/me")
async def me(user=Depends(get_current_user)):
    """Aktuellen Benutzer zurueckgeben."""
    return {"user": user}


@router.put("/password")
async def change_password(data: PasswordChangeRequest, user=Depends(get_current_user)):
    """Passwort aendern."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user["id"],)
        ).fetchone()

        if not row or not verify_password(data.old_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="Altes Passwort ist falsch")

        new_hash = hash_password(data.new_password)
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_hash, user["id"]),
        )
        db.commit()
    finally:
        db.close()

    return {"message": "Passwort geaendert"}
