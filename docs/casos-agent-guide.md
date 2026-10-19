# Casos: Agenten-Guide

Casos verwaltet flache Issues mit Markdown-Beschreibung, chronologischen Updates
und lokalen Anhaengen. Issue-Status: `offen`, `in_arbeit`, `erledigt`, `abgebrochen`.
Wiederoeffnen ist ein Statuswechsel; Prioritaet0..100, Frist optional YYYY-MM-DD.

## Zugang

Web: http://localhost:8514/
MCP hier: http://localhost:8514/mcp/
Dedizierter MCP-Zugang: http://localhost:8516/mcp/
Bootstrap: http://localhost:8514/.well-known/casos-agent.json
Guide: http://localhost:8514/agent-guide.md
Token erstellen: globales Zahnrad → Einstellungen → MCP (http://localhost:8514/?settings=mcp).
Alle MCP-Anfragen brauchen `Authorization: Bearer <token>`.
Der dedizierte Dienst auf8516 und der Hauptdienst auf8514 bieten dieselben Werkzeuge.
Transport-Sessions gelten nur fuer ihren jeweiligen Dienst. Tokenwiderruf,
Deaktivierung, aktuelle Rollen und MCP-Kill-Switch gelten auch in bestehenden Sessions.

```toml
[mcp_servers.casos]
url = "http://localhost:8516/mcp/"
http_headers = { Authorization = "Bearer <token>" }
```

## Rechte und sichere Arbeitsweise

- Alle aktiven Benutzer lesen alle Issues, Updates und Anhaenge. Kein anonymer Zugriff.
- Ersteller, Verantwortliche, explizite Bearbeiter und Admins bearbeiten und verfassen Beitraege.
- Zuweisungen, Bearbeitungsfreigaben und Issue-Loeschung bleiben Ersteller/Admin vorbehalten.
- Autoren korrigieren eigene Updates mit aktuellen Beitragsrechten innerhalb 300 Sekunden; Admins auch spaeter. Revision erforderlich. Update-Loeschung nur Admin.
- Anhang-Loeschung: Ersteller/Admin oder Uploader mit aktuellen Beitragsrechten.
- Beschreibung und Updates als Markdown-Quelle senden. Bei revision_conflict neu lesen und Entwurf abgleichen.
- Listen sind paginiert; next_offset bis null folgen. Mutationen liefern kompakte Bestaetigungen.
- reason ist optionale Audit-Begruendung, maximal1000 Zeichen, getrennt vom Inhalt.
- Tokens nur in geschuetzter Client-Konfiguration speichern, nie in Repository, Logs oder Issues.
- Nach unklaren Netzwerkfehlern erst nachlesen: Anlage, Update-Anlage und Anhang-Upload sind nicht idempotent.

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
2. `issue.create(title="Drucker pruefen", description="## Ziel\nTestseite", priority=60)`;
   neue `issue_id` merken. Anlage bei unklarem Ergebnis nicht blind wiederholen.
3. `issue.get(issue_id=42)` lesen. Beschreibung mit `issue.patch_description`
   und aktueller `revision` aendern, oder `issue.update(issue_id=42,
   changes={"status":"in_arbeit"})`.
4. `update.add(issue_id=42, content="Testseite erfolgreich.")`; Rueckgabe enthaelt
   `update_id` und `revision`. Korrektur mit `update.edit` innerhalb des Autorenfensters.
5. `attachment.add(issue_id=42, original_name="test.txt", content="Ergebnis",
   encoding="utf-8")`; neue ID mit `attachment.read` wieder lesen.
6. `issue.update(issue_id=42, changes={"status":"erledigt"}, reason="Pruefung bestanden")`.

## Anhang-REST fuer groessere Dateien

MCP-Anhanginhalte sind auf1MiB dekodiert begrenzt (Base64 entsprechend groesser).
Multipart-REST akzeptiert genau ein `file`-Feld bis500MiB Dateibytes, streamend begrenzt.
Gleichnamige Uploads bleiben getrennte IDs. Keine Ordner, kein Ueberschreiben/Datei-Editieren.
REST liefert Metadaten mit `id`; MCP nennt diese Referenz `attachment_id`.

Basis dieser Verbindung: `http://localhost:8514`
- GET/POST `/api/issues/{issue_id}/attachments` (Liste / Upload)
- GET `/api/issues/{issue_id}/attachments/{attachment_id}` (Metadaten)
- GET `/api/issues/{issue_id}/attachments/{attachment_id}/download` (Original)
- DELETE `/api/issues/{issue_id}/attachments/{attachment_id}`

Derselbe Bearer-Token gilt auf beiden Diensten. Schreibrequests brauchen zusaetzlich
`X-Requested-With: XMLHttpRequest`. Andere REST-Fachendpunkte sind Browser-Sessions
vorbehalten; Agenten verwenden dafuer MCP. Beispiel mit Platzhalter:

```sh
curl --fail -H 'Authorization: Bearer <token>' -H 'X-Requested-With: XMLHttpRequest' \
  -F 'file=@./beleg.pdf' 'http://localhost:8514/api/issues/42/attachments'
curl --fail -H 'Authorization: Bearer <token>' \
  'http://localhost:8514/api/issues/42/attachments/7/download' -o beleg.pdf
```

Nie echte Tokens in gespeicherte Beispiele oder Shell-Historien uebernehmen.
Download-/Vorschauzugriffe pruefen aktuelle Authentifizierung; externe Mailbilder
werden nicht automatisch geladen. Vorschaugrenzen sind unabhaengig vom Uploadlimit.

## AGENTS.md-Snippet

```markdown
## Casos Issues

- Web: http://localhost:8514/
- MCP: http://localhost:8514/mcp/
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
```
