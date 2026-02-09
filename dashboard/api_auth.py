"""
Tareas - Auth API-Router
Login, Logout, Me, Passwort-Aenderung.
"""

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

    if not row or not verify_password(data.password, row["password_hash"]):
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
