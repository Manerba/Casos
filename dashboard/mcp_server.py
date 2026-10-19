"""Casos Issue tools; both HTTP transports use the same current-rights services."""
import base64
import binascii
from contextvars import ContextVar
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from pydantic import BaseModel, ConfigDict, Field

from dashboard import attachment_service, issue_service, update_service
from dashboard.agent_guide import build_agent_guide_markdown, build_agent_metadata
from dashboard.db_utils import db_query
from dashboard.errors import ApplicationError
from dashboard.issue_permissions import require_active_user
from dashboard.mcp_errors import MCPToolError, StructuredToolErrors

current_mcp_user: ContextVar[dict | None] = ContextVar('current_mcp_user', default=None)
Id = Annotated[int, Field(strict=True, ge=1)]
Offset = Annotated[int, Field(strict=True, ge=0)]
Limit = Annotated[int, Field(strict=True, ge=1, le=500)]
Text = Annotated[str, Field(strict=True)]
Status = Literal['offen', 'in_arbeit', 'erledigt', 'abgebrochen']
Priority = Annotated[int, Field(strict=True, ge=0, le=100)]
MCP_ATTACHMENT_MAX_BYTES = 1024 * 1024


class IssueChanges(BaseModel):
    """Only supplied fields change; explicit null clears assignee or deadline."""
    model_config = ConfigDict(extra='forbid', strict=True)
    title: str | None = None
    description: str | None = None
    description_revision: str | None = None
    priority: Priority | None = None
    deadline: str | None = None
    assigned_to: Id | None = None
    status: Status | None = None


def _user():
    try:
        request = get_http_request()
    except RuntimeError:
        user = current_mcp_user.get()
    else:
        # Transport sessions outlive requests: never authorize from their copied ContextVars.
        user = getattr(request.state, 'mcp_user', None)
    if not user:
        raise MCPToolError('authentication_required', 'MCP-Identitaet fehlt')
    with db_query() as db:
        return require_active_user(db, user)


def _item(value, kind):
    value = dict(value)
    value[kind + '_id'] = value.pop('id')
    return value


def _page(value, kind):
    return {**value, 'items': [_item(item, kind) for item in value['items']]}


mcp = FastMCP(
    name='Casos', middleware=[StructuredToolErrors()], mask_error_details=True,
    strict_input_validation=False,
    instructions=(
        'Casos verwaltet flache Issues, chronologische Markdown-Updates und lokale Anhaenge. '
        'Alle aktiven Benutzer lesen alle Inhalte. Schreiben erfordert aktuelle Issue-Rechte; '
        'Zuweisungen, Bearbeitungsfreigaben und Loeschen verwalten Ersteller/Admins. '
        'Nutze gezielte paginierte Reads, Revisionen fuer Beschreibungen/Updates und optional reason '
        'fuer Audit. get_agent_guide erklaert die Werkzeuge und authentifizierte Anhang-REST.'
    ),
)


@mcp.tool(annotations={'readOnlyHint': True})
def whoami() -> dict:
    """Aktuelle Identitaet (auch nach Rollenwechsel oder Tokenwiderruf)."""
    user = _user()
    return {key: user[key] for key in ('id', 'username', 'auth_source', 'is_admin')} | {
        'display_name': user.get('mcp_display_name') or ' '.join(filter(None, [user.get('vorname'), user.get('nachname')])) or user['username']}


@mcp.tool(annotations={'readOnlyHint': True})
def get_agent_guide() -> dict:
    """Aktuelle URLs, MCP-Vertrag, REST-Beispiele und AGENTS.md-Snippet ohne Secrets."""
    _user()
    try:
        request = get_http_request()
    except RuntimeError:
        request = None
    metadata = build_agent_metadata(request)
    return {'metadata': metadata, 'markdown': build_agent_guide_markdown(metadata)}


@mcp.tool(name='issue.list', annotations={'readOnlyHint': True})
def issue_list(offset: Offset = 0, limit: Limit = 50, status: Status | None = None,
               assigned_to: Id | None = None, unassigned: bool = False, include_description: bool = False,
               sort_by: Literal['id','title','priority','deadline','created_at'] = 'id',
               sort_direction: Literal['asc','desc'] = 'desc') -> dict:
    """Issues seitenweise, standardmaessig ID absteigend, ohne Beschreibung; next_offset bis null folgen."""
    return _page(issue_service.list_issues(_user(), offset, limit, status, assigned_to,
                                          include_description, sort_by, sort_direction, unassigned), 'issue')


@mcp.tool(name='issue.get', annotations={'readOnlyHint': True})
def issue_get(issue_id: Id, include_description: bool = True) -> dict:
    """Issue, aktuelle Faehigkeiten und Beschreibungsrevision gezielt laden."""
    result = _item(issue_service.get_issue(issue_id, _user()), 'issue')
    if not include_description:
        result.pop('description', None)
        result.pop('description_format', None)
    return result


@mcp.tool(name='issue.create')
def issue_create(title: Text, description: Text = '', priority: Priority = 50,
                 deadline: Text | None = None, assigned_to: Id | None = None,
                 status: Status = 'offen', reason: Text | None = None) -> dict:
    """Issue anlegen; liefert ok und issue_id. Beschreibung als Markdown, Frist YYYY-MM-DD."""
    result = issue_service.create_issue(dict(title=title, description=description, priority=priority,
                                             deadline=deadline, assigned_to=assigned_to, status=status), _user(), reason)
    return {'ok': True, 'issue_id': result['id']}


@mcp.tool(name='issue.update')
def issue_update(issue_id: Id, changes: IssueChanges, reason: Text | None = None) -> dict:
    """Nur Felder in changes aendern. null loescht deadline/assigned_to. Beschreibung braucht description_revision."""
    issue_service.update_issue(issue_id, changes.model_dump(exclude_unset=True), _user(), reason)
    return {'ok': True}


@mcp.tool(name='issue.delete', annotations={'destructiveHint': True})
def issue_delete(issue_id: Id, reason: Text | None = None) -> dict:
    """Issue samt Updates/Anhaengen endgueltig loeschen (Ersteller/Admin). Restbereinigung wird wiederholt."""
    return issue_service.delete_issue(issue_id, _user(), reason)


@mcp.tool(name='issue.patch_description')
def issue_patch_description(issue_id: Id, revision: Text, operation: Literal['append','replace'],
                            text: Text, old_text: Text | None = None, reason: Text | None = None) -> dict:
    """Exakt anhaengen ohne Newline oder eindeutiges old_text ersetzen; neue Revision als Antwort."""
    return issue_service.patch_issue_description(issue_id, _user(), revision=revision, operation=operation,
                                                 text=text, old_text=old_text, reason=reason)


@mcp.tool(name='issue.editors.get', annotations={'readOnlyHint': True})
def issue_editors_get(issue_id: Id) -> dict:
    """Bearbeitungsfreigaben samt Revision lesen; globale Sichtbarkeit ist davon unabhaengig."""
    return issue_service.get_editors(issue_id, _user())


@mcp.tool(name='issue.editors.set')
def issue_editors_set(issue_id: Id, user_ids: list[Id], revision: Text, reason: Text | None = None) -> dict:
    """Gesamte Bearbeiterliste revisionsgesichert ersetzen (Ersteller/Admin); leere Liste entfernt Freigaben."""
    result = issue_service.set_editors(issue_id, user_ids, _user(), revision=revision, reason=reason)
    return {'ok': True, 'revision': result['revision']}


@mcp.tool(name='update.list', annotations={'readOnlyHint': True})
def update_list(issue_id: Id, offset: Offset = 0, limit: Limit = 50) -> dict:
    """Chronologische Updates, neueste zuerst, inklusive Revision und aktuellen can_write/can_delete."""
    return _page(update_service.list_updates(issue_id, _user(), offset, limit), 'update')


@mcp.tool(name='update.get', annotations={'readOnlyHint': True})
def update_get(issue_id: Id, update_id: Id) -> dict:
    """Ein Update mit Markdown-Quelle und Revision laden."""
    return _item(update_service.get_update(issue_id, update_id, _user()), 'update')


@mcp.tool(name='update.add')
def update_add(issue_id: Id, content: Text, reason: Text | None = None) -> dict:
    """Neuen chronologischen Eintrag anlegen; kein Ueberschreiben vorheriger Updates."""
    result = update_service.create_update(issue_id, content, _user(), reason)
    return {'ok': True, 'update_id': result['id'], 'revision': result['revision']}


@mcp.tool(name='update.edit')
def update_edit(issue_id: Id, update_id: Id, content: Text, revision: Text, reason: Text | None = None) -> dict:
    """Autor mit aktuellen Beitragsrechten innerhalb 300s, Admin auch spaeter; Revision immer erforderlich."""
    result = update_service.edit_update(issue_id, update_id, content, _user(), revision, reason)
    return {'ok': True, 'revision': result['revision']}


@mcp.tool(name='update.delete', annotations={'destructiveHint': True})
def update_delete(issue_id: Id, update_id: Id, reason: Text | None = None) -> dict:
    """Update endgueltig loeschen; nur Admins, mit Audit."""
    return update_service.delete_update(issue_id, update_id, _user(), reason)


@mcp.tool(name='attachment.list', annotations={'readOnlyHint': True})
def attachment_list(issue_id: Id, offset: Offset = 0, limit: Limit = 50) -> dict:
    """Flache Anhangmetadaten mit IDs, Downloadpfad und aktuellen Rechten; keine Dateiinhalte."""
    return _page(attachment_service.list_attachments(issue_id, _user(), offset, limit), 'attachment')


@mcp.tool(name='attachment.add')
def attachment_add(issue_id: Id, original_name: Text, content: Text,
                   encoding: Literal['utf-8','base64'] = 'base64', media_type: Text | None = None,
                   reason: Text | None = None) -> dict:
    """Neuen Anhang bis1MiB dekodiert anlegen. Gleiche Namen bleiben getrennt. Groesser: Multipart-REST bis500MiB."""
    user = _user()
    max_encoded = 4 * ((MCP_ATTACHMENT_MAX_BYTES + 2) // 3)
    if len(content) > (max_encoded if encoding == 'base64' else MCP_ATTACHMENT_MAX_BYTES):
        raise ApplicationError(413, 'MCP-Anhang maximal1MiB; authentifizierte Anhang-REST nutzen', code='attachment_too_large', field='content')
    try:
        data = base64.b64decode(content, validate=True) if encoding == 'base64' else content.encode('utf-8')
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ApplicationError(422, 'Ungueltige Anhangkodierung', code='invalid_encoding', field='content') from exc
    if len(data) > MCP_ATTACHMENT_MAX_BYTES:
        raise ApplicationError(413, 'MCP-Anhang maximal1MiB; authentifizierte Anhang-REST nutzen', code='attachment_too_large', field='content')
    result = attachment_service.add_attachment(issue_id, user, original_name=original_name,
                                                content=data, media_type=media_type, reason=reason)
    return {'ok': True, 'attachment_id': result['id']}


@mcp.tool(name='attachment.read', annotations={'readOnlyHint': True})
def attachment_read(issue_id: Id, attachment_id: Id, encoding: Literal['utf-8','base64'] = 'base64') -> dict:
    """Anhang maximal1MiB lesen, standardmaessig Base64. Groessere Originale ueber geschuetzte Download-REST."""
    metadata, stream = attachment_service.open_attachment(issue_id, attachment_id, _user())
    with stream:
        if metadata['size'] > MCP_ATTACHMENT_MAX_BYTES:
            raise ApplicationError(413, 'MCP-Anhang maximal1MiB; authentifizierte Download-REST nutzen', code='attachment_too_large', field='attachment_id')
        data = stream.read(MCP_ATTACHMENT_MAX_BYTES + 1)
    if len(data) > MCP_ATTACHMENT_MAX_BYTES:
        raise ApplicationError(413, 'Anhang zu gross', code='attachment_too_large', field='attachment_id')
    try:
        content = base64.b64encode(data).decode('ascii') if encoding == 'base64' else data.decode('utf-8')
    except UnicodeError as exc:
        raise ApplicationError(422, 'Kein UTF-8-Text; encoding=base64 verwenden', code='invalid_encoding', field='encoding') from exc
    return {**_item(metadata, 'attachment'), 'encoding': encoding, 'content': content}


@mcp.tool(name='attachment.delete', annotations={'destructiveHint': True})
def attachment_delete(issue_id: Id, attachment_id: Id, reason: Text | None = None) -> dict:
    """Anhang loeschen: Ersteller/Admin oder Uploader mit aktuellen Beitragsrechten."""
    return attachment_service.delete_attachment(issue_id, attachment_id, _user(), reason)


@mcp.tool(name='users.list', annotations={'readOnlyHint': True})
def users_list(offset: Offset = 0, limit: Limit = 50) -> dict:
    """Aktive Benutzer fuer Zuweisungen und Bearbeitungsfreigaben seitenweise laden."""
    user = _user()
    with db_query() as db:
        db.execute('BEGIN')
        require_active_user(db, user)
        total = db.execute('SELECT count(*) FROM users WHERE is_active=1').fetchone()[0]
        rows = db.execute('SELECT id AS user_id,username,vorname,nachname FROM users WHERE is_active=1 ORDER BY username,id LIMIT ? OFFSET ?', (limit, offset)).fetchall()
    return {'items': [dict(row) for row in rows], 'offset': offset, 'limit': limit, 'total': total,
            'next_offset': offset + len(rows) if offset + len(rows) < total else None}


@mcp.tool(annotations={'readOnlyHint': True})
def search(query: Text, issue_id: Id | None = None, types: list[Literal['issue','update']] | None = None,
           since: Text | None = None, offset: Offset = 0, limit: Annotated[int, Field(strict=True, ge=1, le=200)] = 20) -> dict:
    """UND-Woerter, \"Phrasen\", Wortpraefix*. since: inklusive updated_at, ISO8601 mit Zeitzone. Keine Anhanginhalte."""
    from dashboard.search_service import search_content
    user = _user()
    with db_query() as db:
        return search_content(db, user, query, limit, offset=offset, issue_id=issue_id, types=types, since=since)
