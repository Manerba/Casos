"""Zentrale DB-Hilfsfunktionen zur Vermeidung von Code-Duplikaten."""
from contextlib import contextmanager
from dashboard.database import get_db


@contextmanager
def db_query():
    """Context Manager fuer Read-Only DB-Queries. Schliesst Connection automatisch."""
    db = get_db()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_transaction():
    """Context Manager fuer DB-Transaktionen mit Auto-Commit/Rollback."""
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def upsert_singleton_config(db, table: str, fields: dict):
    """UPSERT fuer Singleton-Konfigurationen (id=1).

    Args:
        db: DB-Connection
        table: Tabellenname
        fields: Dict mit Spaltenname -> Wert
    """
    existing = db.execute(f"SELECT id FROM {table} WHERE id = 1").fetchone()

    if existing:
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        db.execute(f"UPDATE {table} SET {set_clause} WHERE id = 1", list(fields.values()))
    else:
        cols = ", ".join(["id"] + list(fields.keys()))
        placeholders = ", ".join(["1"] + ["?"] * len(fields))
        db.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(fields.values()))


def build_update_query(table: str, fields: dict, where_clause: str, where_values: list):
    """Baut dynamische UPDATE-Query aus nicht-None Feldern.

    Args:
        table: Tabellenname
        fields: Dict mit Spaltenname -> Wert (None-Werte werden ignoriert)
        where_clause: WHERE-Bedingung (z.B. "id = ?")
        where_values: Werte fuer WHERE-Bedingung

    Returns:
        Tuple (query, values) oder None wenn keine Felder zu aktualisieren
    """
    updates = []
    values = []

    for key, value in fields.items():
        if value is not None:
            updates.append(f"{key} = ?")
            values.append(value)

    if not updates:
        return None

    query = f"UPDATE {table} SET {', '.join(updates)} WHERE {where_clause}"
    return query, values + where_values
