"""
Casos - Authentifizierung
Hashing, Sessions, Cookie-Signing, FastAPI-Dependencies.
"""

import hashlib
import fcntl
import os
import secrets
import stat
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, Request, Response
from itsdangerous import URLSafeSerializer, BadSignature

from dashboard.database import DB_DIR, get_db

COOKIE_NAME = "casos_session"
SESSION_MAX_AGE = 365 * 86400  # 1 Jahr in Sekunden
SECRET_KEY_PATH = DB_DIR / "secret.key"


# ============================================================
# Secret Key
# ============================================================

def get_secret_key() -> str:
    """Read or atomically create the shared cookie/Fernet key under a flock.

    Existing bytes are never replaced, including an empty/corrupt key. A new
    key is fsynced before publication with link(), which cannot overwrite an
    existing destination. All operations use the opened private directory.
    A process killed before publication can leave a private staging file;
    it is never treated as the active key or reused on the next attempt.
    """
    path = SECRET_KEY_PATH
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    lock = None
    temporary = None
    try:
        os.fchmod(directory, 0o700)
        lock = os.open(f'.{path.name}.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                       0o600, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(lock).st_mode):
            raise RuntimeError('Secret key lock must be a regular file')
        os.fchmod(lock, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)

        def read_existing():
            try:
                fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=directory)
            except FileNotFoundError:
                return None
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise RuntimeError('Secret key must be a regular file')
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, 'r', encoding='utf-8') as stream:
                    fd = None
                    key = stream.read().strip()
                if not key:
                    raise RuntimeError('Existing secret key is empty; restore the original key from backup')
                return key
            finally:
                if fd is not None:
                    os.close(fd)

        existing = read_existing()
        if existing is not None:
            return existing
        key = secrets.token_hex(32)
        candidate = f'.{path.name}.{secrets.token_hex(16)}.tmp'
        fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory)
        temporary = candidate
        try:
            os.fchmod(fd, 0o600)
            content = key.encode('utf-8')
            while content:
                written = os.write(fd, content)
                if written <= 0:
                    raise OSError('Could not write complete secret key')
                content = content[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            # Also protect against another writer which does not use our lock.
            existing = read_existing()
            if existing is None:
                raise RuntimeError('Secret key changed during publication')
            return existing
        os.unlink(temporary, dir_fd=directory)
        temporary = None
        os.fsync(directory)
        return key
    finally:
        try:
            if temporary is not None:
                os.unlink(temporary, dir_fd=directory)
        finally:
            if lock is not None:
                os.close(lock)
            os.close(directory)


def _get_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_secret_key(), salt="casos-session")


# ============================================================
# Passwort-Hashing
# ============================================================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        # MCP identities have no password hash and cannot log in by cookie.
        return False


# ============================================================
# Session-Verwaltung
# ============================================================

def create_session(user_id: int) -> str:
    """Erstellt eine neue Session in der DB, gibt den Token zurueck."""
    token = secrets.token_hex(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM users WHERE id = ? AND is_active = 1 AND auth_source != 'mcp'", (user_id,)).fetchone():
            raise HTTPException(status_code=401, detail="Anmeldung fehlgeschlagen")
        db.execute(
            "INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)",
            (user_id, token, expires_at),
        )
        db.commit()
    finally:
        db.close()
    return token


def validate_session(token: str) -> dict | None:
    """Validiert einen Session-Token. Gibt User-Dict oder None zurueck."""
    db = get_db()
    try:
        row = db.execute(
            """SELECT s.*, u.id as uid, u.username, u.vorname, u.nachname,
                      u.email, u.is_admin, u.auth_source
               FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.token = ? AND s.expires_at > datetime('now') AND u.is_active = 1 AND u.auth_source != 'mcp'""",
            (token,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["uid"],
            "username": row["username"],
            "vorname": row["vorname"],
            "nachname": row["nachname"],
            "email": row["email"],
            "is_admin": row["is_admin"],
            "auth_source": row["auth_source"] or "local",
        }
    finally:
        db.close()


def delete_session(token: str):
    """Loescht eine Session aus der DB."""
    db = get_db()
    try:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        db.commit()
    finally:
        db.close()


# ============================================================
# Cookie-Signing
# ============================================================

def sign_token(token: str) -> str:
    return _get_serializer().dumps(token)


def unsign_token(signed: str) -> str | None:
    try:
        return _get_serializer().loads(signed)
    except BadSignature:
        return None


# ============================================================
# Cookie-Helpers
# ============================================================

def set_session_cookie(response: Response, token: str):
    from dashboard.tls_utils import get_tls_config
    tls = get_tls_config()
    use_secure = bool(tls and tls["enabled"])

    signed = sign_token(token)
    response.set_cookie(
        key=COOKIE_NAME,
        value=signed,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=use_secure,
        samesite="lax",
        path="/",
    )


def delete_session_cookie(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")


# ============================================================
# FastAPI Dependencies
# ============================================================

def _extract_user_from_request(request: Request) -> dict | None:
    """Liest Cookie, validiert Session, gibt User-Dict oder None zurueck."""
    signed = request.cookies.get(COOKIE_NAME)
    if not signed:
        return None
    token = unsign_token(signed)
    if not token:
        return None
    return validate_session(token)


async def get_current_user(request: Request) -> dict:
    """FastAPI Dependency: Gibt aktuellen User zurueck oder 401."""
    user = _extract_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    return user


async def get_admin_user(request: Request) -> dict:
    """FastAPI Dependency: Gibt Admin-User zurueck oder 401/403."""
    user = _extract_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Kein Admin-Zugriff")
    return user


# ============================================================
# MCP-Token-Auth (Bearer-Token fuer MCP und die REST-Dateiablage)
# ============================================================

def _hash_token(plain_token: str) -> str:
    """SHA-256-Hash eines Plain-Tokens (Hex). Nur Hash wird gespeichert."""
    return hashlib.sha256(plain_token.encode()).hexdigest()


def _mcp_globally_enabled() -> bool:
    """Prueft den Kill-Switch (mcp_config.enabled)."""
    db = get_db()
    try:
        row = db.execute("SELECT enabled FROM mcp_config WHERE id = 1").fetchone()
        return bool(row and row["enabled"])
    finally:
        db.close()


def validate_mcp_bearer(token: str) -> dict | None:
    """Validiert einen MCP-Bearer-Token. Gibt User-Dict (auth_source='mcp')
    oder None zurueck. Aktualisiert last_used_at."""
    if not token:
        return None
    if not _mcp_globally_enabled():
        return None
    token_hash = _hash_token(token)
    db = get_db()
    try:
        row = db.execute(
            """SELECT t.id AS token_id, t.display_name,
                      u.id AS uid, u.username, u.vorname, u.nachname,
                      u.email, u.is_admin, u.auth_source
               FROM mcp_tokens t
               JOIN users u ON t.user_id = u.id
               WHERE t.token_hash = ? AND t.revoked_at IS NULL AND u.is_active = 1
                 AND EXISTS (SELECT 1 FROM mcp_config WHERE id = 1 AND enabled = 1)""",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE mcp_tokens SET last_used_at = datetime('now') WHERE id = ?",
            (row["token_id"],),
        )
        db.commit()
        return {
            "id": row["uid"],
            "username": row["username"],
            "vorname": row["vorname"],
            "nachname": row["nachname"],
            "email": row["email"],
            "is_admin": row["is_admin"],
            "auth_source": row["auth_source"] or "mcp",
            "mcp_token_id": row["token_id"],
            "mcp_display_name": row["display_name"],
        }
    finally:
        db.close()


def _extract_bearer_token(request: Request) -> str | None:
    """Liest 'Authorization: Bearer <token>' aus dem Request, oder None."""
    parts = request.headers.get("Authorization", "").split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


async def get_mcp_user(request: Request) -> dict:
    """FastAPI Dependency: Validiert Bearer-Token, gibt MCP-User zurueck oder 401/403."""
    if not _mcp_globally_enabled():
        raise HTTPException(status_code=403, detail="MCP ist deaktiviert")
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Bearer-Token fehlt")
    user = validate_mcp_bearer(token)
    if not user:
        raise HTTPException(status_code=401, detail="Ungueltiges oder widerrufenes Token")
    return user


async def get_file_user(request: Request) -> dict:
    """Datei-API: MCP-Bearer oder Web-Session mit denselben Aufgabenrechten."""
    # Ein expliziter Authorization-Header bestimmt die Identitaet. Ungueltige
    # Tokens duerfen nicht auf eine eventuell privilegiertere Session fallen.
    if "Authorization" in request.headers:
        return await get_mcp_user(request)
    return await get_current_user(request)


def create_mcp_token(display_name: str, created_by_user_id: int) -> tuple[str, int]:
    """Legt einen neuen MCP-User samt Token an.

    Returns:
        (plain_token, token_id) - Plain-Token wird nur HIER und im Admin-UI angezeigt.

    Der zugehoerige User hat auth_source='mcp' und einen automatischen Username
    'mcp_<token_id>'. password_hash bleibt leer (Login per Cookie nicht moeglich).
    """
    plain_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(plain_token)
    db = get_db()
    try:
        # 1. User anlegen (Platzhalter-Username, wird gleich aktualisiert)
        placeholder_username = f"mcp_{secrets.token_hex(4)}"
        cursor = db.execute(
            """INSERT INTO users
               (username, password_hash, vorname, nachname, is_admin, auth_source, is_active)
               VALUES (?, '', ?, '', 0, 'mcp', 1)""",
            (placeholder_username, display_name),
        )
        user_id = cursor.lastrowid

        # 2. Token-Eintrag erstellen
        cursor = db.execute(
            """INSERT INTO mcp_tokens
               (user_id, token_hash, display_name, created_by)
               VALUES (?, ?, ?, ?)""",
            (user_id, token_hash, display_name, created_by_user_id),
        )
        token_id = cursor.lastrowid

        # 3. Username auf finales Format aktualisieren ('mcp_<token_id>')
        db.execute(
            "UPDATE users SET username = ? WHERE id = ?",
            (f"mcp_{token_id}", user_id),
        )

        db.commit()
        return plain_token, token_id
    finally:
        db.close()


def revoke_mcp_token(token_id: int) -> bool:
    """Setzt revoked_at auf jetzt. Behaelt Audit-Spur (User wird nicht geloescht).

    Returns True wenn das Token aktiv war und revoked wurde, sonst False.
    """
    db = get_db()
    try:
        cursor = db.execute(
            """UPDATE mcp_tokens
               SET revoked_at = datetime('now')
               WHERE id = ? AND revoked_at IS NULL""",
            (token_id,),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        db.close()


def list_mcp_tokens() -> list[dict]:
    """Liste aller MCP-Tokens (ohne Hash) fuer Admin-UI."""
    db = get_db()
    try:
        rows = db.execute(
            """SELECT t.id, t.display_name, t.created_at, t.last_used_at,
                      t.revoked_at, t.user_id,
                      cb.username AS created_by_username
               FROM mcp_tokens t
               LEFT JOIN users cb ON t.created_by = cb.id
               ORDER BY t.id DESC"""
        ).fetchall()
        return [
            {
                "id": r["id"],
                "display_name": r["display_name"],
                "created_at": r["created_at"],
                "last_used_at": r["last_used_at"],
                "revoked_at": r["revoked_at"],
                "user_id": r["user_id"],
                "created_by_username": r["created_by_username"],
                "active": r["revoked_at"] is None,
            }
            for r in rows
        ]
    finally:
        db.close()


def get_mcp_config() -> dict:
    """Liefert die MCP-Config (Kill-Switch + Metadaten)."""
    db = get_db()
    try:
        row = db.execute("SELECT enabled FROM mcp_config WHERE id = 1").fetchone()
        return {"enabled": bool(row["enabled"]) if row else True}
    finally:
        db.close()


def set_mcp_enabled(enabled: bool) -> None:
    """Schaltet MCP global ein/aus (Kill-Switch)."""
    db = get_db()
    try:
        db.execute(
            "INSERT OR REPLACE INTO mcp_config (id, enabled) VALUES (1, ?)",
            (1 if enabled else 0,),
        )
        db.commit()
    finally:
        db.close()
