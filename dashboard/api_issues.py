"""Session-authenticated REST transport for the shared Issue services."""

from fastapi import APIRouter, Body, Depends, Query

from dashboard.auth import get_current_user
from dashboard.db_utils import db_query
from dashboard.errors import ApplicationError
from dashboard.issue_permissions import require_active_user
from dashboard import issue_service

router = APIRouter(tags=["issues"])


def _body(data, allowed=None):
    data = dict(data)
    reason = data.pop("reason", None)
    if allowed is not None and set(data) - allowed:
        raise ApplicationError(422, "Unbekannte Felder", code="unknown_fields", fields=sorted(set(data) - allowed))
    return data, reason


@router.get("/api/users/list")
async def list_users(user=Depends(get_current_user)):
    with db_query() as db:
        db.execute("BEGIN")
        require_active_user(db, user)
        rows = db.execute("SELECT id, username, vorname, nachname FROM users WHERE is_active = 1 ORDER BY username, id").fetchall()
        return {"items": [dict(row) for row in rows]}


@router.get("/api/issues")
async def list_issues(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                      status: str | None = None, assigned_to: int | None = None,
                      include_description: bool = False, user=Depends(get_current_user)):
    return issue_service.list_issues(user, offset, limit, status, assigned_to, include_description)


@router.post("/api/issues", status_code=201)
async def create_issue(data: dict = Body(...), user=Depends(get_current_user)):
    data, reason = _body(data)
    return issue_service.create_issue(data, user, reason=reason)


@router.get("/api/issues/{issue_id}")
async def get_issue(issue_id: int, user=Depends(get_current_user)):
    return issue_service.get_issue(issue_id, user)


@router.put("/api/issues/{issue_id}")
async def update_issue(issue_id: int, data: dict = Body(...), user=Depends(get_current_user)):
    data, reason = _body(data)
    return issue_service.update_issue(issue_id, data, user, reason=reason)


@router.delete("/api/issues/{issue_id}")
async def delete_issue(issue_id: int, reason: str | None = None, user=Depends(get_current_user)):
    return issue_service.delete_issue(issue_id, user, reason=reason)


@router.patch("/api/issues/{issue_id}/description")
async def patch_description(issue_id: int, data: dict = Body(...), user=Depends(get_current_user)):
    data, reason = _body(data, {"revision", "operation", "text", "old_text"})
    missing = {"revision", "operation", "text"} - set(data)
    if missing:
        raise ApplicationError(422, "Pflichtfelder fehlen", code="missing_fields", fields=sorted(missing))
    return issue_service.patch_issue_description(issue_id, user, **data, reason=reason)


@router.get("/api/issues/{issue_id}/editors")
async def get_editors(issue_id: int, user=Depends(get_current_user)):
    return issue_service.get_editors(issue_id, user)


@router.put("/api/issues/{issue_id}/editors")
async def set_editors(issue_id: int, data: dict = Body(...), user=Depends(get_current_user)):
    data, reason = _body(data, {"revision", "user_ids"})
    return issue_service.set_editors(issue_id, data.get("user_ids"), user, revision=data.get("revision"), reason=reason)
