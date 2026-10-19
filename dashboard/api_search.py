"""Cookie-authenticated HTTP search using the same service as MCP."""
from fastapi import APIRouter, Depends, Query

from dashboard.auth import get_current_user
from dashboard.db_utils import db_query
from dashboard.search_service import search_content

router = APIRouter(tags=['search'])


@router.get('/api/search')
async def search(query: str = '', limit: int = 20, offset: int = 0,
                 issue_id: int | None = None, types: list[str] | None = Query(None),
                 since: str | None = None, user=Depends(get_current_user)):
    with db_query() as db:
        return search_content(db, user, query, limit, offset=offset,
                              issue_id=issue_id, types=types, since=since)
