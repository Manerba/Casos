"""Current identities and shared permissions for every Issue transport."""

from dashboard.errors import ApplicationError


def require_active_user(db, user: dict | None) -> dict:
    """Never authorize from cached role or activity flags supplied by a caller."""
    user_id = user.get("id") if isinstance(user, dict) else None
    if type(user_id) is not int or user_id < 1:
        raise ApplicationError(401, "Nicht angemeldet", code="authentication_required")
    row = db.execute(
        "SELECT id, username, vorname, nachname, email, is_admin, is_active, auth_source "
        "FROM users WHERE id = ? AND is_active = 1", (user_id,),
    ).fetchone()
    if row is None:
        raise ApplicationError(401, "Benutzer ist nicht aktiv", code="inactive_user")
    current = dict(row)
    if user.get("mcp_token_id") is not None:
        token = db.execute(
            "SELECT t.id, t.display_name FROM mcp_tokens t JOIN mcp_config c ON c.id = 1 "
            "WHERE t.id = ? AND t.user_id = ? AND t.revoked_at IS NULL AND c.enabled = 1",
            (user["mcp_token_id"], user_id),
        ).fetchone()
        if token is None:
            raise ApplicationError(401, "MCP-Zugriff ist nicht mehr aktiv", code="invalid_token")
        current.update(mcp_token_id=token["id"], mcp_display_name=token["display_name"])
    return current


def issue_permissions(db, issue, user: dict) -> dict:
    """Compute capabilities; user must already be refreshed in this transaction."""
    can_manage = bool(user["is_admin"] or issue["created_by"] == user["id"])
    can_edit = bool(can_manage or issue["assigned_to"] == user["id"] or db.execute(
        "SELECT 1 FROM issue_editors WHERE issue_id = ? AND user_id = ?",
        (issue["id"], user["id"]),
    ).fetchone())
    return {"can_read": True, "can_edit": can_edit, "can_contribute": can_edit,
            "can_manage": can_manage}


def require_issue_access(db, issue_id: int, user: dict, action: str = "read"):
    current = require_active_user(db, user)
    if type(issue_id) is not int or issue_id < 1:
        raise ApplicationError(422, "Ungueltige Issue-ID", code="invalid_issue_id", field="issue_id")
    row = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        raise ApplicationError(404, "Issue nicht gefunden", code="issue_not_found", field="issue_id")
    rights = issue_permissions(db, row, current)
    if action not in {"read", "edit", "contribute", "manage"}:
        raise ValueError("Unknown Issue permission action")
    if not rights[f"can_{action}"]:
        raise ApplicationError(403, "Keine Berechtigung fuer diese Issue-Aktion", code="permission_denied")
    return row, rights
