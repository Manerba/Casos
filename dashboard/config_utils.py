"""Zentrale Hilfsfunktionen fuer Config-Operationen."""
from fastapi import HTTPException
from dashboard.db_utils import db_query


def get_masked_config(table: str, mask_fields: list[str] | None = None) -> dict | None:
    """Laedt Singleton-Config (id=1) und maskiert sensitive Felder.

    Args:
        table: Tabellenname
        mask_fields: Liste von Feldnamen deren Werte maskiert werden (z.B. ["password"])

    Returns:
        Config-Dict mit maskierten Feldern oder None
    """
    with db_query() as db:
        row = db.execute(f"SELECT * FROM {table} WHERE id = 1").fetchone()
        if not row:
            return None
        config = dict(row)
        if mask_fields:
            for field in mask_fields:
                if config.get(field):
                    config[field] = "********"
        return config


def resolve_masked_password(db, table: str, field: str, new_value: str) -> str:
    """Loest maskiertes Passwort auf: gibt echtes PW zurueck wenn '********', sonst new_value.

    Args:
        db: Offene DB-Connection (innerhalb eines Context Managers)
        table: Tabellenname
        field: Spaltenname des Passwort-Feldes
        new_value: Der vom Client gesendete Wert

    Returns:
        Das tatsaechliche Passwort

    Raises:
        HTTPException(400) wenn maskiert aber kein gespeichertes PW existiert
    """
    if new_value != "********":
        return new_value

    row = db.execute(f"SELECT {field} FROM {table} WHERE id = 1").fetchone()
    if row and row[field]:
        return row[field]
    raise HTTPException(status_code=400, detail="Kein gespeichertes Passwort vorhanden")
