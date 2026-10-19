"""Read-only previews, always authorized against the original Issue attachment."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from dashboard import attachment_preview
from dashboard.auth import get_file_user

router = APIRouter(prefix='/api/issues/{issue_id}/attachments/{attachment_id}', tags=['attachment previews'])
HEADERS = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}


async def _run(request, issue_id, attachment_id, user, mode='metadata', index=-1):
    result = await run_in_threadpool(attachment_preview.preview, issue_id, attachment_id, user, mode, index)
    # Revalidate the actual cookie too (logout/session expiration during parsing).
    await get_file_user(request)
    return result


@router.get('/preview')
async def get_preview(issue_id: int, attachment_id: int, request: Request, user=Depends(get_file_user)):
    result, _ = await _run(request, issue_id, attachment_id, user)
    return JSONResponse(result, headers=HEADERS)


@router.get('/preview/image')
async def get_image(issue_id: int, attachment_id: int, request: Request, user=Depends(get_file_user)):
    _, data = await _run(request, issue_id, attachment_id, user, 'image')
    return Response(data, media_type='image/png', headers=HEADERS)


@router.get('/embedded/{index}/download')
async def get_embedded(issue_id: int, attachment_id: int, index: int, request: Request, user=Depends(get_file_user)):
    result, data = await _run(request, issue_id, attachment_id, user, 'embedded', index)
    return Response(data, media_type='application/octet-stream', headers={**HEADERS,
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(result['name'], safe=''),
        'Content-Security-Policy': 'sandbox'})


@router.get('/embedded/{index}/preview/image')
async def get_embedded_image(issue_id: int, attachment_id: int, index: int, request: Request, user=Depends(get_file_user)):
    _, data = await _run(request, issue_id, attachment_id, user, 'embedded-image', index)
    return Response(data, media_type='image/png', headers=HEADERS)
