"""
Tokenfreier Bootstrap-Guide fuer Agenten-Integration.

Die Daten werden zur Laufzeit aus der Casos-Konfiguration abgeleitet, damit
Clients die aktuellen Issue-Endpunkte und Rechte verwenden.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request

from dashboard.db_utils import db_query


DEFAULT_ADDRESS = "localhost:8514"
MCP_SERVER_NAME = "casos"
MCP_TRANSPORT = "streamable_http"
current_agent_base_url: ContextVar[str | None] = ContextVar("current_agent_base_url", default=None)


def _strip_protocol(address: str) -> str:
    value = (address or "").strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if value.lower().startswith(prefix):
            return value[len(prefix):]
    return value


def _get_configured_address() -> str | None:
    try:
        with db_query() as db:
            row = db.execute("SELECT server_address FROM app_config WHERE id = 1").fetchone()
        if row and row["server_address"]:
            return _strip_protocol(row["server_address"])
    except Exception:
        return None
    return None


def _tls_enabled() -> bool:
    try:
        with db_query() as db:
            row = db.execute("SELECT enabled FROM tls_config WHERE id = 1").fetchone()
        return bool(row and row["enabled"])
    except Exception:
        return False


def _request_base_url(request: Request | None) -> str | None:
    if not request:
        return None
    return str(request.base_url).rstrip("/")


def public_base_url(request: Request | None = None) -> str:
    """Liefert die oeffentliche Basis-URL der Haupt-App."""
    configured = _get_configured_address()
    if configured:
        protocol = "https" if _tls_enabled() else "http"
        return f"{protocol}://{configured}"

    requested = _request_base_url(request)
    if requested:
        return requested

    protocol = "https" if _tls_enabled() else "http"
    return f"{protocol}://{DEFAULT_ADDRESS}"


def _with_port(base_url: str, port: int) -> str:
    parts = urlsplit(base_url)
    hostname = parts.hostname or parts.netloc.split(":")[0]
    if not hostname:
        return base_url
    netloc = f"[{hostname}]:{port}" if ":" in hostname else f"{hostname}:{port}"
    return urlunsplit((parts.scheme or "http", netloc, "", "", "")).rstrip("/")


def build_agent_metadata(request: Request | None = None, *, mcp_base_url: str | None = None) -> dict[str, Any]:
    base_url = public_base_url(request)
    agent_base = mcp_base_url or current_agent_base_url.get()
    if agent_base and not _get_configured_address():
        base_url = _with_port(agent_base, 8514)
    dedicated_endpoint = f"{agent_base or _with_port(base_url, 8516)}/mcp/"
    agent_base = agent_base or base_url
    endpoint = f"{agent_base}/mcp/"
    return {
        'name': 'Casos', 'description': 'Flache Issues, chronologische Updates und lokale Anhaenge.',
        'web_ui': base_url + '/', 'attachment_api_base_url': agent_base,
        'agent_guide_url': agent_base + '/agent-guide.md',
        'well_known_url': agent_base + '/.well-known/casos-agent.json',
        'mcp': {'server_name': MCP_SERVER_NAME, 'endpoint': endpoint,
                'legacy_endpoint': base_url + '/mcp/', 'dedicated_endpoint': dedicated_endpoint,
                'transport': MCP_TRANSPORT, 'authorization_header': 'Authorization: Bearer <token>',
                'token_placeholder': '<token>', 'token_admin_url': base_url + '/?settings=mcp'},
        'client_examples': {
            'codex_config_toml': '[mcp_servers.casos]\nurl = "' + dedicated_endpoint + '"\nhttp_headers = { Authorization = "Bearer <token>" }',
            'claude_command': 'claude mcp add --transport http casos ' + dedicated_endpoint + ' --header "Authorization: Bearer <token>"',
        },
        'agents_md_snippet': build_agents_snippet(base_url + '/', endpoint),
        'limits': {'attachment_mcp_bytes': 1048576, 'attachment_upload_bytes': 524288000,
                   'description_utf8_bytes': 1048576, 'update_utf8_bytes': 1048576,
                   'update_author_edit_seconds': 300, 'list_limit': 500, 'search_limit': 200},
        'rules': [
            'Alle aktiven Benutzer lesen alle Issues, Updates und Anhaenge. Kein anonymer Zugriff.',
            'Ersteller, Verantwortliche, explizite Bearbeiter und Admins bearbeiten und verfassen Beitraege.',
            'Zuweisungen, Bearbeitungsfreigaben und Issue-Loeschung bleiben Ersteller/Admin vorbehalten.',
            'Autoren korrigieren eigene Updates mit aktuellen Beitragsrechten innerhalb 300 Sekunden; Admins auch spaeter. Revision erforderlich. Update-Loeschung nur Admin.',
            'Anhang-Loeschung: Ersteller/Admin oder Uploader mit aktuellen Beitragsrechten.',
            'Beschreibung und Updates als Markdown-Quelle senden. Bei revision_conflict neu lesen und Entwurf abgleichen.',
            'Listen sind paginiert; next_offset bis null folgen. Mutationen liefern kompakte Bestaetigungen.',
            'reason ist optionale Audit-Begruendung, maximal1000 Zeichen, getrennt vom Inhalt.',
            'Tokens nur in geschuetzter Client-Konfiguration speichern, nie in Repository, Logs oder Issues.',
            'Nach unklaren Netzwerkfehlern erst nachlesen: Anlage, Update-Anlage und Anhang-Upload sind nicht idempotent.',
        ],
    }


def build_agents_snippet(web_ui: str, mcp_endpoint: str) -> str:
    return f'''## Casos Issues

- Web: {web_ui}
- MCP: {mcp_endpoint}
- Erwartete Identitaet: <MCP-Anzeigename>, pruefen mit `whoami`.
- Issue: <issue_id>, Details mit `issue.get`.
- Token nur in geschuetzter Client-Konfiguration, niemals im Repository.

`issue.list`/`search` finden Issues; `issue.get` liefert Rechte und Revision.
`issue.update` nimmt `changes` mit ausschliesslich gewuenschten Feldern an.
Beschreibungen brauchen `description_revision`; `issue.patch_description`
unterstuetzt exakt append/replace mit `revision`. Konflikte neu lesen und abgleichen.
`update.add` erzeugt einen chronologischen Eintrag, `update.edit` braucht dessen Revision.
`attachment.add/read` bis1MiB, groessere Dateien ueber authentifizierte Anhang-REST.
Alle Inhalte sind fuer aktive Benutzer sichtbar; Schreiben folgt den aktuellen Rechten.
Nach unklaren Fehlern vor erneuter Anlage nachlesen. `reason` dokumentiert Auditgruende.
'''


def build_agent_guide_markdown(metadata: dict[str, Any]) -> str:
    m = metadata['mcp']
    base = metadata['attachment_api_base_url']
    rules = '\n'.join('- ' + value for value in metadata['rules'])
    return f'''# Casos: Agenten-Guide

Casos verwaltet flache Issues mit Markdown-Beschreibung, chronologischen Updates
und lokalen Anhaengen. Issue-Status: `offen`, `in_arbeit`, `erledigt`, `abgebrochen`.
Wiederoeffnen ist ein Statuswechsel; Prioritaet0..100, Frist optional YYYY-MM-DD.

## Zugang

Web: {metadata['web_ui']}
MCP hier: {m['endpoint']}
Dedizierter MCP-Zugang: {m['dedicated_endpoint']}
Bootstrap: {metadata['well_known_url']}
Guide: {metadata['agent_guide_url']}
Token erstellen: globales Zahnrad → Einstellungen → MCP ({m['token_admin_url']}).
Alle MCP-Anfragen brauchen `Authorization: Bearer <token>`.
Der dedizierte Dienst auf8516 und der Hauptdienst auf8514 bieten dieselben Werkzeuge.
Transport-Sessions gelten nur fuer ihren jeweiligen Dienst. Tokenwiderruf,
Deaktivierung, aktuelle Rollen und MCP-Kill-Switch gelten auch in bestehenden Sessions.

```toml
{metadata['client_examples']['codex_config_toml']}
```

## Rechte und sichere Arbeitsweise

{rules}

## Werkzeuge

| Werkzeug | Eingabe / Verhalten |
|---|---|
| whoami, get_agent_guide | Aktuelle Identitaet bzw. dieser dynamische Guide |
| issue.list | offset0, limit50 (max500), status, assigned_to oder unassigned, include_description=false, sort_by=id/title/priority/deadline/created_at, sort_direction=desc/asc |
| issue.get | issue_id, include_description=true; aktuelle permissions und description_revision |
| issue.create | title, description, priority50, deadline=null, assigned_to=null, status=offen; Antwort ok/issue_id |
| issue.update | issue_id, changes-Objekt; fehlende Felder bleiben, null leert deadline/assigned_to; Beschreibung nur mit description_revision; Antwort ok |
| issue.patch_description | issue_id, revision, operation=append/replace, text; replace braucht eindeutiges old_text. Keine automatische Newline. Antwort neue description_revision |
| issue.delete | issue_id; endgueltig samt Updates und Anhaengen; cleanup_pending nennt verbleibende wiederholbare Dateibereinigung |
| issue.editors.get/set | issue_id; get liefert user_ids/revision, set ersetzt alle user_ids mit revision; nur Ersteller/Admin |
| issue.history | issue_id, offset/limit; Status-/Zuweisungsereignisse mit Akteur und Vorher-/Nachher-Werten sowie menschliche Updates, neueste zuerst |
| update.list/get | issue_id, optional update_id; Listen offset/limit, neueste zuerst; Inhalte, revision, can_write/can_delete |
| update.add | issue_id, content; neuer Eintrag, Antwort ok/update_id/revision |
| update.edit | issue_id, update_id, content, revision; Antwort ok/revision |
| update.delete | issue_id, update_id; Admin, endgueltig |
| attachment.list | issue_id, offset/limit; Metadaten, attachment_id, download_url, can_delete |
| attachment.add | issue_id, original_name, content, encoding=base64 (oder utf-8), optional media_type; Antwort ok/attachment_id |
| attachment.read | issue_id, attachment_id, encoding=base64 (oder utf-8); Metadaten + content |
| attachment.delete | issue_id, attachment_id; endgueltig |
| users.list | offset/limit; aktive Benutzer mit user_id fuer Zuweisung/Freigabe |
| search | query, issue_id, types=[issue,update], since, offset, limit20 (max200) |

Alle Listen liefern `items`, `offset`, `limit`, `total`, `next_offset`.
Zwischen Seiten koennen parallele Aenderungen die Reihenfolge verschieben.
Schreibwerkzeuge akzeptieren optional `reason` (max1000 Unicode-Zeichen vor Trimmen).
Werkzeugfehler: `isError=true` und `structuredContent` mit `code`, `message`,
gegebenenfalls `field`/`fields`. Beispielsweise `revision_conflict`, `permission_denied`,
`issue_not_found`, `update_edit_window_expired`, `attachment_too_large`.
Keine Fehlertexte parsen; ungueltige Eingaben schreiben keine Teilmutationen.

Suche: mehrere Begriffe per UND, exakte `"Phrasen"`, `wort*` als Wortpraefix,
keine beliebige Teilwortsuche. `since` ist inklusive auf `updated_at` in UTC,
Eingabe ISO8601 mit expliziter Zeitzone. Ranking ueber Issues/Updates gemeinsam.
Treffer enthalten sichere Fundstellen und direkte Issue-/Update-URLs.
Binaere Anhanginhalte werden nicht indiziert.

## Beispielablauf

1. `whoami` pruefen, `issue.list` oder `search(query="Drucker")` verwenden.
2. `issue.create(title="Drucker pruefen", description="## Ziel\\nTestseite", priority=60)`;
   neue `issue_id` merken. Anlage bei unklarem Ergebnis nicht blind wiederholen.
3. `issue.get(issue_id=42)` lesen. Beschreibung mit `issue.patch_description`
   und aktueller `revision` aendern, oder `issue.update(issue_id=42,
   changes={{"status":"in_arbeit"}})`.
4. `update.add(issue_id=42, content="Testseite erfolgreich.")`; Rueckgabe enthaelt
   `update_id` und `revision`. Korrektur mit `update.edit` innerhalb des Autorenfensters.
5. `attachment.add(issue_id=42, original_name="test.txt", content="Ergebnis",
   encoding="utf-8")`; neue ID mit `attachment.read` wieder lesen.
6. `issue.update(issue_id=42, changes={{"status":"erledigt"}}, reason="Pruefung bestanden")`.

## Anhang-REST fuer groessere Dateien

MCP-Anhanginhalte sind auf1MiB dekodiert begrenzt (Base64 entsprechend groesser).
Multipart-REST akzeptiert genau ein `file`-Feld bis500MiB Dateibytes, streamend begrenzt.
Gleichnamige Uploads bleiben getrennte IDs. Keine Ordner, kein Ueberschreiben/Datei-Editieren.
REST liefert Metadaten mit `id`; MCP nennt diese Referenz `attachment_id`.

Basis dieser Verbindung: `{base}`
- GET/POST `/api/issues/{{issue_id}}/attachments` (Liste / Upload)
- GET `/api/issues/{{issue_id}}/attachments/{{attachment_id}}` (Metadaten)
- GET `/api/issues/{{issue_id}}/attachments/{{attachment_id}}/download` (Original)
- DELETE `/api/issues/{{issue_id}}/attachments/{{attachment_id}}`

Derselbe Bearer-Token gilt auf beiden Diensten. Schreibrequests brauchen zusaetzlich
`X-Requested-With: XMLHttpRequest`. Andere REST-Fachendpunkte sind Browser-Sessions
vorbehalten; Agenten verwenden dafuer MCP. Beispiel mit Platzhalter:

```sh
curl --fail -H 'Authorization: Bearer <token>' -H 'X-Requested-With: XMLHttpRequest' \\
  -F 'file=@./beleg.pdf' '{base}/api/issues/42/attachments'
curl --fail -H 'Authorization: Bearer <token>' \\
  '{base}/api/issues/42/attachments/7/download' -o beleg.pdf
```

Nie echte Tokens in gespeicherte Beispiele oder Shell-Historien uebernehmen.
Download-/Vorschauzugriffe pruefen aktuelle Authentifizierung; externe Mailbilder
werden nicht automatisch geladen. Vorschaugrenzen sind unabhaengig vom Uploadlimit.

## AGENTS.md-Snippet

```markdown
{metadata['agents_md_snippet']}```
'''
