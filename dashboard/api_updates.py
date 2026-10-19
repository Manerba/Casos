"""Update REST creation adapted from Tareas 7157218 / api_tasks.py."""

from fastapi import APIRouter, Body, Depends, Query

from dashboard.auth import get_current_user
from dashboard.errors import ApplicationError
from dashboard import update_service

router = APIRouter(prefix="/api/issues/{issue_id}/updates", tags=["updates"])


def _body(data, *, editing=False):
    allowed = {"content", "reason", "revision"} if editing else {"content", "reason"}
    if set(data) - allowed:
        raise ApplicationError(422, "Unbekannte Update-Felder", code="unknown_fields", fields=sorted(set(data) - allowed))
    return data.get("content"), data.get("reason")


@router.get("")
async def list_updates(issue_id: int, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500), user=Depends(get_current_user)):
    return update_service.list_updates(issue_id, user, offset, limit)


@router.post("", status_code=201)
async def create_update(issue_id: int, data: dict = Body(...), user=Depends(get_current_user)):
    content, reason = _body(data)
    return update_service.create_update(issue_id, content, user, reason=reason)


@router.get("/{update_id}")
async def get_update(issue_id: int, update_id: int, user=Depends(get_current_user)):
    return update_service.get_update(issue_id, update_id, user)


@router.put("/{update_id}")
async def edit_update(issue_id: int, update_id: int, data: dict = Body(...), user=Depends(get_current_user)):
    content, reason = _body(data, editing=True)
    return update_service.edit_update(issue_id, update_id, content, user, data.get("revision"), reason=reason)


@router.delete("/{update_id}")
async def delete_update(issue_id: int, update_id: int, reason: str | None = None, user=Depends(get_current_user)):
    return update_service.delete_update(issue_id, update_id, user, reason=reason)
