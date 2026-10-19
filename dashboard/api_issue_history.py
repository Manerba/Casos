"""Authenticated Issue history REST endpoint."""
from fastapi import APIRouter, Depends, Query

from dashboard.auth import get_current_user
from dashboard.issue_history_service import list_history

router = APIRouter(tags=['issues'])


@router.get('/api/issues/{issue_id}/history')
async def get_history(issue_id: int, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                      user=Depends(get_current_user)):
    return list_history(issue_id, user, offset, limit)
