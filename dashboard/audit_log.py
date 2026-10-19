"""
Casos - Audit-Log fuer Aenderungen an Aufgaben/Teilaufgaben/Notes/Dependencies.

Persistiert WHO did WHAT, WHEN, WHERE und (optional) ein JSON-Diff der Aenderungen.
Wird aus REST-Endpunkten und MCP-Tools aufgerufen. Reads werden NICHT geloggt
(zu viel Rauschen) - nur Schreib-Operationen.
"""

import json
import logging
from typing import Any

from dashboard.database import get_db
from dashboard.errors import ApplicationError

logger = logging.getLogger(__name__)

REASON_MAX_LENGTH = 1000


def normalize_reason(reason: str | None) -> str | None:
    """Separate Audit-Metadaten; vor jeder fachlichen Aenderung validieren."""
    if reason is None:
        return None
    if not isinstance(reason, str) or len(reason) > REASON_MAX_LENGTH:
        raise ApplicationError(400, "reason darf hoechstens 1000 Zeichen enthalten",
                               code="invalid_reason", field="reason")
    try:
        reason.encode("utf-8")
    except UnicodeError as exc:
        raise ApplicationError(400, "reason muss gueltiger Unicode-Text sein",
                               code="invalid_reason", field="reason") from exc
    return reason.strip() or None


def log_change(
    actor: dict | None,
    entity_type: str,
    entity_id: int | None,
    action: str,
    changes: dict[str, Any] | None = None,
    *,
    reason: str | None = None,
    db=None,
) -> None:
    """Schreibt einen Eintrag ins Audit-Log.

    Args:
        actor: User-Dict (mit 'id' und 'auth_source'). None = System-Action.
        entity_type: 'issue' | 'update' | 'attachment' | 'mcp_token' | ...
        entity_id: ID der betroffenen Entitaet (None bei z.B. globalen Config-Aenderungen)
        action: 'create' | 'update' | 'delete' | 'status_change' | 'revoke' | ...
        changes: Optional dict mit Feld -> neuer Wert (oder {'old': ..., 'new': ...})
        reason: Optionale Begruendung (max. 1000 Zeichen), getrennt vom Feld-Diff.

    Mit db gehoert Audit zur bestehenden Transaktion und Fehler werden weitergegeben.
    Ohne db bleibt der bisherige Best-effort-Aufruf fuer Konfigurationsaktionen erhalten.
    """
    if db is not None:
        # Issue services may couple the audit record to their business mutation.
        # A write error then rolls back both records through the outer transaction.
        source = (actor.get("auth_source") if actor else None) or "local"
        actor_type = "mcp" if source == "mcp" else ("system" if actor is None else "user")
        db.execute(
            "INSERT INTO audit_log (actor_user_id, actor_type, entity_type, entity_id, action, changes_json, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (actor["id"] if actor else None, actor_type, entity_type, entity_id, action,
             json.dumps(changes, ensure_ascii=False, default=str) if changes else None, normalize_reason(reason)),
        )
        return
    try:
        actor_user_id = actor["id"] if actor else None
        actor_source = (actor.get("auth_source") if actor else None) or "local"
        actor_type = "mcp" if actor_source == "mcp" else ("system" if actor is None else "user")

        changes_json = json.dumps(changes, ensure_ascii=False, default=str) if changes else None

        db = get_db()
        try:
            db.execute(
                """INSERT INTO audit_log
                   (actor_user_id, actor_type, entity_type, entity_id, action, changes_json, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (actor_user_id, actor_type, entity_type, entity_id, action, changes_json, normalize_reason(reason)),
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("audit_log write failed: %s", exc)


def diff_fields(before: dict, after: dict, fields: list[str]) -> dict[str, dict]:
    """Hilfsfunktion: berechnet Diff fuer eine Liste von Feldern.

    Returns dict {field: {'old': ..., 'new': ...}} - nur fuer geaenderte Felder.
    """
    result = {}
    for f in fields:
        b = before.get(f)
        a = after.get(f)
        if b != a:
            result[f] = {"old": b, "new": a}
    return result
