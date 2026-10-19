"""
Casos - TLS Hilfsfunktionen
Config-Lesen und Zertifikats-Validierung.
"""

import sqlite3
import ssl
from contextlib import closing
from pathlib import Path

from dashboard import database


def get_tls_config() -> dict | None:
    """Liest TLS-Config aus DB. Gibt None zurueck wenn nicht konfiguriert oder DB fehlt."""
    if not database.DB_PATH.exists():
        return None
    with closing(sqlite3.connect(str(database.DB_PATH))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tls_config WHERE id = 1").fetchone()
        return dict(row) if row else None


def validate_cert_files(cert_path: str, key_path: str) -> str | None:
    """Prueft Existenz, Lesbarkeit und PEM-Format. Gibt Fehlermeldung oder None zurueck."""
    cert = Path(cert_path)
    key = Path(key_path)

    if not cert.exists():
        return f"Zertifikat nicht gefunden: {cert_path}"
    if not key.exists():
        return f"Key-Datei nicht gefunden: {key_path}"

    if not cert.is_file():
        return f"Zertifikat ist keine Datei: {cert_path}"
    if not key.is_file():
        return f"Key ist keine Datei: {key_path}"

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
    except (OSError, ValueError, ssl.SSLError) as exc:
        return f"Zertifikat/Key ungueltig oder nicht lesbar: {exc}"
    return None


def get_tls_verify_config() -> dict:
    """Current certificate validation settings for retained SMTP/LDAP integrations."""
    defaults = {"verify_smtp": False, "verify_ldap": False}
    if not database.DB_PATH.exists():
        return defaults
    with closing(sqlite3.connect(str(database.DB_PATH))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tls_verify_config WHERE id = 1").fetchone()
        return {key: bool(row[key]) for key in defaults} if row else defaults
