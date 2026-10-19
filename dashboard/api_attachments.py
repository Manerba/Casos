"""Authenticated, immutable Issue attachments; no directory/editor operations."""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from python_multipart.exceptions import MultipartParseError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect

from dashboard import attachment_service as service
from dashboard.auth import get_file_user
from dashboard.db_utils import db_query
from dashboard.errors import ApplicationError
from dashboard.issue_permissions import require_issue_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/issues/{issue_id}/attachments", tags=["attachments"])


class _UploadTooLarge(MultiPartException):
    pass


class _LimitedUploadParser(MultiPartParser):
    def __init__(self, headers, stream):
        super().__init__(headers, stream, max_files=1, max_fields=0)
        self.file_bytes = 0
        self.header_bytes = 0
        self.completed_parts = 0
        self.multipart_complete = False

    def on_part_end(self):
        self.completed_parts += 1
        super().on_part_end()

    def on_end(self):
        self.multipart_complete = True
        super().on_end()

    def on_part_data(self, data, start, end):
        if self._current_part.file is not None:
            self.file_bytes += end - start
            if self.file_bytes > service.MAX_UPLOAD_SIZE:
                raise _UploadTooLarge("Anhang zu gross (max. 500 MiB)")
        super().on_part_data(data, start, end)

    def on_header_field(self, data, start, end):
        self._check_headers(end - start)
        super().on_header_field(data, start, end)

    def on_header_value(self, data, start, end):
        self._check_headers(end - start)
        super().on_header_value(data, start, end)

    def _check_headers(self, size):
        self.header_bytes += size
        if self.header_bytes > 16 * 1024:
            raise MultiPartException("Multipart-Header zu gross")

    def close(self):
        for file in self._files_to_close_on_error:
            file.close()


@router.get("")
def list_attachments(issue_id: int, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500), user=Depends(get_file_user)):
    return service.list_attachments(issue_id, user, offset, limit)


@router.post("", status_code=201, openapi_extra={"requestBody": {"required": True, "content": {
    "multipart/form-data": {"schema": {"type": "object", "required": ["file"],
                                       "properties": {"file": {"type": "string", "format": "binary"}}}},
}}})
async def upload_attachment(issue_id: int, request: Request, user=Depends(get_file_user)):
    # No body/File dependency: identity and contribution rights are resolved
    # before consuming even the first byte of an unauthorised upload.
    with db_query() as db:
        require_issue_access(db, issue_id, user, "contribute")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "multipart/form-data":
        raise ApplicationError(400, "Multipart-Dateiupload erforderlich", code="invalid_upload")
    parser = _LimitedUploadParser(request.headers, request.stream())
    try:
        try:
            form = await parser.parse()
        except _UploadTooLarge as exc:
            raise ApplicationError(413, "Anhang zu gross (max. 500 MiB)", code="attachment_too_large", field="file") from exc
        except (MultiPartException, MultipartParseError, ClientDisconnect, UnicodeError, KeyError) as exc:
            raise ApplicationError(400, "Ungueltiger oder abgebrochener Dateiupload", code="invalid_upload") from exc
        if not parser.multipart_complete or parser.completed_parts != 1:
            raise ApplicationError(400, "Unvollstaendiger Dateiupload", code="invalid_upload")
        file = form.get("file")
        if len(form.multi_items()) != 1 or not isinstance(file, UploadFile):
            raise ApplicationError(422, "Genau ein Dateifeld 'file' ist erforderlich", code="invalid_upload", field="file")
        # Session expiration/logout and token revocation during reception apply.
        current = await get_file_user(request)
        return await run_in_threadpool(service.add_attachment, issue_id, current,
                                       original_name=file.filename or "", media_type=file.content_type,
                                       content=file.file)
    finally:
        parser.close()


@router.get("/{attachment_id}")
def get_attachment(issue_id: int, attachment_id: int, user=Depends(get_file_user)):
    return service.get_attachment(issue_id, attachment_id, user)


def _download_chunks(stream):
    try:
        while chunk := stream.read(service.COPY_CHUNK_SIZE):
            yield chunk
    finally:
        stream.close()


@router.get("/{attachment_id}/download")
def download_attachment(issue_id: int, attachment_id: int, user=Depends(get_file_user)):
    metadata, stream = service.open_attachment(issue_id, attachment_id, user)
    return StreamingResponse(_download_chunks(stream), media_type=metadata["media_type"], headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(metadata["original_name"], safe=""),
        "Content-Length": str(metadata["size"]), "Content-Security-Policy": "sandbox",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    }, background=BackgroundTask(stream.close))


@router.delete("/{attachment_id}")
def delete_attachment(issue_id: int, attachment_id: int, user=Depends(get_file_user)):
    return service.delete_attachment(issue_id, attachment_id, user)
