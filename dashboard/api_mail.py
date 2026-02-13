"""
Tareas - API-Router fuer Mail-Konfiguration, Templates und Preferences.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from dashboard.database import get_db
from dashboard.auth import get_admin_user, get_current_user
from dashboard.mail_service import (
    test_smtp_connection,
    send_mail,
    render_template,
    build_html_mail,
    ensure_default_prefs,
    get_app_url,
)

mail_admin_router = APIRouter()
mail_user_router = APIRouter()


# ============================================================
# Pydantic-Modelle
# ============================================================

class MailConfigSave(BaseModel):
    smtp_server: str
    smtp_port: int = 587
    encryption: str = "starttls"
    auth_enabled: bool = True
    username: str = ""
    password: str = ""
    from_address: str
    from_name: str = "Tareas"


class TemplateUpdate(BaseModel):
    subject: str
    body_text: str


class TestMailRequest(BaseModel):
    to_email: str


class MailPreferenceItem(BaseModel):
    event_type: str
    enabled: bool
    days_before: int = 2


class MailPreferencesSave(BaseModel):
    preferences: list[MailPreferenceItem]


# ============================================================
# Admin-Endpunkte
# ============================================================

@mail_admin_router.get("/api/admin/mail/config")
async def get_mail_config(user=Depends(get_admin_user)):
    """Mail-Config laden (Passwort maskiert)."""
    db = get_db()
    try:
        row = db.execute("SELECT * FROM mail_config WHERE id = 1").fetchone()
        if not row:
            return {"config": None}
        config = dict(row)
        # Passwort maskieren
        if config.get("password"):
            config["password"] = "********"
        return {"config": config}
    finally:
        db.close()


@mail_admin_router.post("/api/admin/mail/config")
async def save_mail_config(data: MailConfigSave, user=Depends(get_admin_user)):
    """Mail-Config speichern (UPSERT, Verbindungstest vorher)."""
    db = get_db()
    try:
        # Bestehendes Passwort beibehalten wenn maskiert
        password = data.password
        if password == "********":
            existing = db.execute("SELECT password FROM mail_config WHERE id = 1").fetchone()
            if existing:
                password = existing["password"]
            else:
                raise HTTPException(status_code=400, detail="Passwort muss angegeben werden")

        config = {
            "smtp_server": data.smtp_server,
            "smtp_port": data.smtp_port,
            "encryption": data.encryption,
            "auth_enabled": 1 if data.auth_enabled else 0,
            "username": data.username,
            "password": password,
            "from_address": data.from_address,
            "from_name": data.from_name,
        }

        # Verbindungstest
        error = test_smtp_connection(config)
        if error:
            raise HTTPException(status_code=400, detail=f"SMTP-Verbindung fehlgeschlagen: {error}")

        # UPSERT
        db.execute(
            """INSERT INTO mail_config (id, smtp_server, smtp_port, encryption, auth_enabled,
                                        username, password, from_address, from_name)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   smtp_server = excluded.smtp_server,
                   smtp_port = excluded.smtp_port,
                   encryption = excluded.encryption,
                   auth_enabled = excluded.auth_enabled,
                   username = excluded.username,
                   password = excluded.password,
                   from_address = excluded.from_address,
                   from_name = excluded.from_name""",
            (data.smtp_server, data.smtp_port, data.encryption,
             1 if data.auth_enabled else 0, data.username, password,
             data.from_address, data.from_name),
        )
        db.commit()
        return {"message": "Mail-Konfiguration gespeichert (Verbindung OK)"}
    finally:
        db.close()


@mail_admin_router.delete("/api/admin/mail/config")
async def delete_mail_config(user=Depends(get_admin_user)):
    """Mail-Config loeschen."""
    db = get_db()
    try:
        db.execute("DELETE FROM mail_config WHERE id = 1")
        db.commit()
        return {"message": "Mail-Konfiguration geloescht"}
    finally:
        db.close()


@mail_admin_router.get("/api/admin/mail/templates")
async def get_mail_templates(user=Depends(get_admin_user)):
    """Alle Mail-Templates laden."""
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM mail_templates ORDER BY event_type").fetchall()
        return {"templates": [dict(r) for r in rows]}
    finally:
        db.close()


@mail_admin_router.put("/api/admin/mail/templates/{event_type}")
async def update_mail_template(event_type: str, data: TemplateUpdate, user=Depends(get_admin_user)):
    """Mail-Template aktualisieren."""
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id FROM mail_templates WHERE event_type = ?", (event_type,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Template nicht gefunden")

        db.execute(
            "UPDATE mail_templates SET subject = ?, body_text = ? WHERE event_type = ?",
            (data.subject, data.body_text, event_type),
        )
        db.commit()
        return {"message": "Template aktualisiert"}
    finally:
        db.close()


@mail_admin_router.post("/api/admin/mail/test")
async def send_test_mail(data: TestMailRequest, user=Depends(get_admin_user)):
    """Testmail senden."""
    result = render_template("test", {})
    if not result:
        raise HTTPException(status_code=400, detail="Test-Template nicht gefunden")

    subject, body_text = result
    html_body = build_html_mail(body_text)

    error = send_mail(data.to_email, subject, html_body, body_text)
    if error:
        raise HTTPException(status_code=400, detail=f"Versand fehlgeschlagen: {error}")

    return {"message": f"Testmail an {data.to_email} gesendet"}


@mail_admin_router.post("/api/admin/mail/invite/{user_id}")
async def send_invite_mail(user_id: int, user=Depends(get_admin_user)):
    """Einladungsmail an Benutzer senden."""
    db = get_db()
    try:
        target = db.execute(
            "SELECT id, username, vorname, nachname, email FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
        if not target["email"]:
            raise HTTPException(status_code=400, detail="Benutzer hat keine E-Mail-Adresse")
    finally:
        db.close()

    recipient_name = f"{target['vorname']} {target['nachname']}".strip() or target["username"]
    placeholders = {
        "recipient_name": recipient_name,
        "username": target["username"],
        "app_url": get_app_url(),
    }

    result = render_template("invite", placeholders)
    if not result:
        raise HTTPException(status_code=400, detail="Einladungs-Template nicht gefunden")

    subject, body_text = result
    html_body = build_html_mail(body_text)

    error = send_mail(target["email"], subject, html_body, body_text)
    if error:
        raise HTTPException(status_code=400, detail=f"Versand fehlgeschlagen: {error}")

    return {"message": f"Einladungsmail an {target['email']} gesendet"}


# ============================================================
# User-Endpunkte
# ============================================================

@mail_user_router.get("/api/user/mail/preferences")
async def get_mail_preferences(user=Depends(get_current_user)):
    """Eigene Mail-Prefs laden."""
    # Defaults anlegen falls noetig
    ensure_default_prefs(user["id"])

    db = get_db()
    try:
        rows = db.execute(
            "SELECT event_type, enabled, days_before FROM user_mail_preferences WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
        return {"preferences": [dict(r) for r in rows]}
    finally:
        db.close()


@mail_user_router.put("/api/user/mail/preferences")
async def save_mail_preferences(data: MailPreferencesSave, user=Depends(get_current_user)):
    """Eigene Mail-Prefs speichern."""
    db = get_db()
    try:
        for pref in data.preferences:
            db.execute(
                """INSERT INTO user_mail_preferences (user_id, event_type, enabled, days_before)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, event_type) DO UPDATE SET
                       enabled = excluded.enabled,
                       days_before = excluded.days_before""",
                (user["id"], pref.event_type, 1 if pref.enabled else 0, pref.days_before),
            )
        db.commit()
        return {"message": "Mail-Einstellungen gespeichert"}
    finally:
        db.close()
