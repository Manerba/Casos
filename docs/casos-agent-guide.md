# Casos-Agent-Guide

Stand des Klons: Rebrandete technische Referenz fuer den uebernommenen MCP-Funktionsumfang. Eine Casos-Instanz ist noch nicht als Dienst installiert; die URLs zeigen die vorgesehenen Ports. Die Ticket-Spezifikationen werden separat erarbeitet.

Dieser Guide beschreibt, wie ein neues Projekt Casos als gemeinsame
Planungs- und Audit-Ebene fuer Codex/Claude-Sessions nutzt.

Der Kern ist bewusst einfach:

- Das Projekt dokumentiert die Casos-Arbeitsweise in `AGENTS.md`.
- Der echte MCP-Zugriff wird lokal im Agenten-Client konfiguriert.
- Der MCP-Token gehoert nie ins Repository.

## Kurzprompt fuer neue Projekte

Diesen Text kann der Benutzer in einem neuen Projekt an eine Agenten-Session
geben:

```text
Wir verwenden Casos zur Projektplanung. Lies den Casos-Agent-Guide:
http://10.0.12.7:8514/agent-guide.md

Richte dieses Repo danach ein: AGENTS.md ergaenzen, Casos-MCP pruefen,
Casos-Projekt anlegen oder referenzieren, Projekt-ID dokumentieren.
Token niemals ins Repo schreiben.
```

## Gemeinsame Casos-Instanz

- Web-UI: `http://10.0.12.7:8514/`
- Agent-Guide: `http://10.0.12.7:8514/agent-guide.md`
- Agent-Bootstrap-JSON: `http://10.0.12.7:8514/.well-known/casos-agent.json`
- MCP-Endpoint: `http://10.0.12.7:8514/mcp/`
- Separater MCP-Dienst: `http://10.0.12.7:8516/mcp/`
- MCP-Transport: Streamable HTTP
- MCP-Servername: `casos`
- Admin-UI fuer MCP-Tokens: `http://10.0.12.7:8515`, Tab `MCP`

`10.0.12.16:8505` ist in dieser Umgebung Kiron, nicht Casos.

Beide MCP-Zugaenge verwenden dieselben Werkzeuge, Tokens und Projektrechte.
Bestehende Konfigurationen mit Port 8514 bleiben gueltig. Fuer eine separate
Firewall-Freigabe kann Port 8516 verwendet werden: Dort stehen auch Datei-REST,
`/agent-guide.md` und `/.well-known/casos-agent.json` bereit, aber keine Web-UI.
Dateitransfers koennen damit ebenfalls vollstaendig ueber Port 8516 laufen.

Die laufende Casos-Instanz ist die kanonische Quelle fuer diesen Guide. Das
Gitea-Repo versioniert die Dokumentation nur; neue Projekte sollen den Guide
ueber die Casos-URL lesen, damit keine Gitea-Verfuegbarkeit vorausgesetzt
wird.

## Lokale MCP-Konfiguration

Die Tool-Integration ist kein Projektcode und keine Runtime-Abhaengigkeit der
Zielanwendung. Sie gehoert in die lokale Konfiguration des jeweiligen
Agenten-Clients.

Codex-Beispiel in `/root/.codex/config.toml`:

```toml
[mcp_servers.casos]
url = "http://10.0.12.7:8514/mcp/"
http_headers = { Authorization = "Bearer <token>" }
```

Claude-Beispiel:

```bash
claude mcp add --transport http casos \
  http://10.0.12.7:8514/mcp/ \
  --header "Authorization: Bearer <token>"
```

Regeln:

- `<token>` ist ein Platzhalter. Den echten Token nie in Repo-Dateien schreiben.
- Tokens werden in Casos unter Admin UI -> MCP erzeugt und nur einmal angezeigt.
- Der MCP-Bearer gilt fuer `/mcp/` und die REST-Dateioperationen unter
  `/api/tasks/{task_id}/files`. Andere REST-Endpunkte brauchen eine Web-Anmeldung.
- Wenn die lokale Konfiguration nicht beschreibbar ist, den Benutzer um Setup
  oder Token-Konfiguration bitten.

Nach Aenderung der MCP-Konfiguration muss die Agenten-Session neu gestartet
werden, damit die Tools erscheinen.

## Verifikation

Eine korrekt gestartete Session sieht Casos-Tools, z.B.:

```text
mcp__casos__whoami
mcp__casos__list_projects
mcp__casos__list_projects_page
mcp__casos__get_project
mcp__casos__get_project_status
mcp__casos__patch_description
mcp__casos__note.write
mcp__casos__note.update
mcp__casos__note.delete
mcp__casos__handoff.add
mcp__casos__handoff.list
mcp__casos__handoff.get
mcp__casos__handoff.update
mcp__casos__handoff.delete
mcp__casos__file.list
mcp__casos__file.read
mcp__casos__file.write
mcp__casos__file.append
mcp__casos__file.mkdir
mcp__casos__file.move
mcp__casos__file.delete
```

Pruefablauf:

1. `whoami` aufrufen.
2. Erwarteten `display_name` und `auth_source: "mcp"` pruefen.
3. `list_projects_page` fuer eine kompakte, paginierte Uebersicht aufrufen.
4. Arbeitsstand mit `get_project_status(project_id=...)` lesen, Beschreibungen gezielt nachladen.
5. Bei konfigurierter Dateiablage (`file_storage_type` ist `local` oder `webdav`)
   mit `file.list(task_id=...)` die Dateien und effektiven Schreibrechte pruefen.

Wenn keine Casos-MCP-Tools verfuegbar sind, keine lokale Ersatz-DB und keine
Schattenquelle in einem anderen System anlegen. Erst MCP einrichten oder den
Benutzer um die lokale Konfiguration bitten.

## Projektlisten, Status und Fehler

`list_projects_page(status=null, offset=0, limit=50, include_description=false)`
liefert `items`, `total`, `offset`, `limit` und `next_offset`. Maximal 500 Eintraege
pro Seite; fuer die naechste Seite `offset=next_offset` verwenden, bis
`next_offset=null` ist. Filter beim Blaettern beibehalten. Sortierung: Prioritaet,
Erstellungszeit und ID, jeweils absteigend. Gleichzeitige Aenderungen koennen
Offsets verschieben. Beschreibungen fehlen standardmaessig; Details mit
`get_project(project_id=...)` nachladen oder `include_description=true` setzen.
Das bisherige `list_projects` liefert fuer bestehende Clients weiterhin eine
Liste. Beide Werkzeuge beachten Sichtbarkeitsrechte und filtern den wirksamen Status.

REST und MCP akzeptieren nur `offen`, `in_arbeit`, `erledigt` und `abgebrochen`
als Status sowie ganzzahligen Teilaufgabenfortschritt von 0 bis 100.
Bei Projekten gilt wie in der Weboberflaeche:

- Keine vollstaendig erledigte Teilaufgabe: `offen`, auch bei Teilfortschritt.
- Einige, aber nicht alle Teilaufgaben zu 100 % erledigt: `in_arbeit`.
- Alle Teilaufgaben zu 100 % erledigt: `erledigt`, ohne manuellen Abschluss.
- Leeres Projekt: `offen`.
- `abgebrochen` hat Vorrang. `update_project(status="offen")` nimmt das Projekt
  wieder auf; danach gilt erneut die Ableitung aus den Teilaufgaben.

Normale Aufgaben behalten ihren manuell gesetzten Status.

Mit `create_project(parent_subtask_id=123)` oder
`update_project(project_id=456, parent_subtask_id=123)` wird ein Kind-Projekt an
Teilaufgabe 123 gehaengt. Pro Teilaufgabe ist ein Kind-Projekt erlaubt. Beide
Seiten brauchen Bearbeitungsrechte, die Verknuepfung vererbt keine Zugriffsrechte.
Selbstbezuege und Zyklen ueber mehrere Projekte werden abgewiesen.
Die PID-Spalte zeigt die Eltern-Teilaufgaben-ID, nicht die Eltern-Projekt-ID.
Projektantworten enthalten `parent_subtask_id`, `parent_project_id` und
`progress_percent`, Teilaufgaben `child_project_id` und `progress_automatic`.

Der Eltern-Subtask uebernimmt den Anteil vollstaendig erledigter Teilaufgaben des
Kind-Projekts, auf ganze Prozent abgerundet (leer = 0). Teilfortschritte und der
separate Abbruchstatus aendern die Berechnung nicht. Aenderungen werden innerhalb
derselben Transaktion ueber alle Elternebenen weitergegeben. Bei
`progress_automatic=true` darf `status_percent` auch als Admin nicht geschrieben
werden: `linked_project_progress_readonly`, Feld `status_percent`.
Andere Teilaufgabenfelder bleiben entsprechend den bisherigen Rechten editierbar.
`update_project(parent_subtask_id=0)` trennt die Verbindung. Der letzte Fortschritt
bleibt erhalten und ist wieder editierbar. Das gilt auch beim Loeschen des
Kind-Projekts. Das Loeschen eines Eltern-Subtasks/-Projekts trennt die Kinder,
ohne diese Projekte zu loeschen. Typwechsel zu einer normalen Aufgabe brauchen
vorher die Trennung aller betroffenen Projektverknuepfungen.

MCP-Werkzeugfehler liefern `isError=true`. `structuredContent` und der
JSON-Textinhalt enthalten `code`, `message` und bei feldbezogenen Fehlern
`field`/`fields`. Stabile Codes wie `invalid_status`, `invalid_progress`,
`dependency_cycle` und `storage_not_configured` fuer die Fehlerbehandlung
verwenden, statt Meldungstexte auszuwerten. Das bestehende REST-Fehlerformat bleibt erhalten.

Bei `storage_not_configured`: Aufgabe/Projekt in der Weboberflaeche aufklappen und
den Button **Dateiablage** verwenden (lokal oder WebDAV). Nach der Einrichtung
stehen die Einstellungen im Header des Dateibrowsers. Hierfuer sind
Bearbeitungsrechte am Projekt erforderlich, etwa als Ersteller, Admin oder durch
eine Bearbeitungsfreigabe. Eine blosse Zuweisung reicht nicht aus. Dateien lesen
braucht Leserechte, Dateiaenderungen brauchen Bearbeitungsrechte. Die MCP-Werkzeuge
legen keine Ablage automatisch an.

## Effizient arbeiten und gezielt nachladen

Ueblich sind `get_project(project_id=75, include_description=false)` und
`list_subtasks(project_id=75, include_description=false)`. Volltexte bei Bedarf
mit `get_project` (Standard `include_description=true`) oder `get_subtask`
nachladen. `list_projects_page` liefert standardmaessig eine kompakte Uebersicht.
`update_project` und `update_subtask` liefern bei Erfolg ausschliesslich
`{"ok": true}`, auch bei unveraenderten Werten oder Beschreibungsupdates.
Es gibt keinen `compact`-Parameter. Den aktuellen Zustand einschliesslich
Beschreibungsrevision bei Bedarf mit `get_project` oder `get_subtask` nachladen.
`patch_description` liefert weiterhin die neue Revision fuer weitere Textaenderungen.
Fehler behalten ihre strukturierten Codes und Meldungen.
`reason` ist optional, maximal 1000 Unicode-Zeichen vor dem Trimmen;
leere Begruendungen werden null. Es wird getrennt vom Felddiff im Audit mit
Akteur und Aenderungsereignis gespeichert und in der Admin-Ansicht angezeigt.

`get_project_status(project_id=75)` liest Projektmetadaten, Zaehler und alle
sichtbaren Teilaufgaben in einem konsistenten Snapshot. Bei Projekt-Leserecht
liefert `project.description_revision` die Revision fuer `update_project` oder
`patch_description`, ohne Beschreibungstexte nachzuladen. Jede Teilaufgabenzeile enthaelt
ID, Position, Titel, Bereich, Prozentwert, `readiness`, `blocker_ids` und
`latest_handoff` (null, wenn keiner existiert). Die Vorschau ist die erste
nichtleere Zeile, maximal 200 Zeichen; Neuheit folgt Erstellungszeit und ID,
beide absteigend. `handoff.get(task_id=75, handoff_id="subtask:456")` laedt Inhalt
und Revision exakt nach; es braucht keine Liste aller Handoffs.

Startbereitschaft ist rein abgeleitet, ohne Schreibzugriff:

- `completed`: 100 Prozent; wird nie als naechste Arbeit angeboten.
- `cancelled`: offene Arbeit in abgebrochenem Projekt.
- `delegated`: offene Teilaufgabe wird von einem Kindprojekt gesteuert; dort arbeiten.
- `restricted`: mindestens ein Vorgaenger ist nicht sichtbar; keine fremden IDs
  oder Statusinformationen werden offengelegt.
- `blocked`: sichtbare direkte Vorgaenger unter 100 Prozent, IDs in `blocker_ids`.
- `ready`: uebrige offene Teilaufgabe ohne unerledigte Vorgaenger.

Projektknoten `0` ist ein Startanker und wartet nicht auf den abgeleiteten
Projektstatus. Bei reinem Teilaufgaben-Zugriff enthalten Projektmetadaten nur
ID/`limited`, Zaehler beziehen sich nur auf sichtbare Zeilen. Graph-/Fortschritts-
aenderungen werden beim naechsten Abruf wirksam, bestehende Zyklusregeln bleiben.

`id` ist die stabile technische Referenz, `position_number` die veraenderliche
Anzeigereihenfolge, `name` der fachliche Titel. Beispiel: Position 3, ID 456,
Name „Port 443 pruefen“. Namen keine Positionsnummer voranstellen. Verschieben
veraendert weder ID, Titel noch Abhaengigkeiten. Bestehende nummerierte Namen
sind allenfalls manuell zu bereinigen; fachliche Zahlen niemals automatisch entfernen.

## Beschreibungen und Handoffs sicher korrigieren

Beschreibungen liefern `description_revision` (Hash aus Text und Format).
Bei Volltextupdates ueber REST/MCP diese gelesene Revision mitsenden. Sie wird
nur geprueft, wenn `description` geaendert wird; Statusupdates bleiben unabhaengig.
Ohne Revision funktionieren alte Volltextclients weiterhin bedingungslos:
Sie haben keinen Konfliktschutz. Neue Clients sollen immer die Revision senden.
Der Browser sendet sie und behaelt bei HTTP 409 den Entwurf samt alter Revision.
Die Revision schützt den Inhaltsstand; eine zwischenzeitliche Aenderung und
Rueckkehr zu identischem Text/Format gilt als derselbe Stand.

Partielle Aenderungen brauchen zwingend die gelesene Revision:

```text
patch_description(task_id=75, revision="<description_revision>",
                  operation="append", text="Weitere Anforderung")
patch_description(task_id=75, subtask_id=456, revision="<description_revision>",
                  operation="replace", old_text="Port 80", text="Port 443")
```

`append` haengt exakt an, ohne zusaetzlichen Zeilenumbruch; den gewuenschten
Umbruch im Text mitsenden. `replace` verlangt genau eine exakte, nichtleere
Fundstelle, auch ueberlappende Treffer zaehlen. Fehlende/mehrdeutige Ziele:
`description_target_not_found` / `description_target_ambiguous`, kein Schreiben.
Text/Markdown-Sonderzeichen werden nicht normalisiert, gespeichertes Format
bleibt erhalten (auch `legacy`). Volltextupdates setzen weiterhin Markdown.
Veraltete Revision: `revision_conflict`, REST HTTP 409; neu lesen und Aenderungen
abgleichen, nicht blind mit einer frischen Revision wiederholen.
REST bietet `PATCH /api/tasks/{id}/description` und
`PATCH /api/subtasks/{id}/description` mit `revision`, `operation`, `text`,
optional `old_text`. Dort gelten Session, CSRF und dieselben Rechte/Sperren.

Autoren mit aktuellen Beitragsrechten duerfen eigene Handoffs in den ersten
300 Sekunden nach Erstellung korrigieren (`0 <= Alter < 300`, Serverzeit UTC).
`handoff.get/list` liefern `revision` und `can_write`. `handoff.update` braucht
fuer normale Benutzer diese Revision; bei Ablauf gilt
`handoff_edit_window_expired`, bei Konkurrenz `revision_conflict`.
Admins koennen weiterhin ohne Zeitgrenze korrigieren; fuer alte Adminclients
ist `revision` optional, sollte fuer Konfliktschutz mitgesendet werden.
Autor, ID, Erstellungszeit und Chronologie bleiben erhalten, der wirkliche
Bearbeiter wird protokolliert. Fremde Inhalte/Rechteentzug bleiben geschuetzt.

## Dateien exakt ergaenzen

`file.append(task_id=75, path="Protokoll.txt", content="Ergebnis")` verlangt eine
vorhandene UTF-8-Textdatei (optionaler UTF-8-BOM bleibt erhalten). Kein UTF-16,
Base64 oder NUL, keine automatische Neuanlage und keine automatische neue Zeile.
Vorhandene Bytes/Zeilenenden bleiben erhalten, neue Zeilenenden stammen exakt
vom Aufrufer. Leerer Text laesst den Inhalt unveraendert. Die Gesamtdatei darf
nach Ergaenzung maximal 1 MiB enthalten; fehlende/zu grosse/ungueltige Dateien
bleiben unveraendert. Lokale Ablage und WebDAV verwenden die gemeinsame
Prozesssperre ueber Lesen, Pruefen und Schreiben, ebenso wie Upload/Office/Texteditor.
Direkte externe WebDAV-Schreiber kennen diese Casos-Sperre nicht.
Audit und Ergebnis enthalten nur Metadaten, keine Dateiinhalte.
Nach unklarem Netzwerkfehler zuerst `file.read` pruefen: erneutes Anhaengen ist
nicht idempotent und kann dieselbe Ergaenzung doppelt einfuegen.

## Suche: Begriffe, Phrasen, Filter und Fundstellen

```text
search(query="Proxy Freigabe Domain", project_id=75, types=["handoff"],
       since="2026-10-11T00:00:00+02:00", limit=10)
search(query='"Proxy Freigabe"')
search(query="fenster*")
```

Unzitierte Woerter muessen alle im selben Eintrag vorkommen (UND); eine Phrase
verlangt die Wortfolge. Satzzeichen wie Bindestrich/Komma trennen Begriffe.
`AND`, `OR`, `NOT` sind normale Suchwoerter, keine FTS-Steuerbefehle.
Ungueltige Syntax, ungeschlossene Anfuehrungszeichen oder alleinige Satzzeichen
liefern `invalid_search_query`, keine scheinbar leere Ergebnisliste. Leere
Eingabe liefert `[]`; maximal 1000 Zeichen und 32 Begriffe/Phrasen.
Unicode61 ignoriert Gross-/Kleinschreibung und Diakritika; `fenster*` findet
„Fenstern“, aber nicht „Zeitfenster“. Keine deutsche Stammwortsuche oder
beliebige Teilwortsuche; Trigram ist eine spaetere Option, hier nicht aktiviert.
Das bisherige zusammenhaengende LIKE-Muster wird durch diese Semantik ersetzt;
Clients mit Wunsch nach Wortfolge setzen Anfuehrungszeichen.

Optionale Filter sind kombinierbar: `project_id`, `types`, `since`. Typen:
`task`, `sub_task`, `task_note`, `sub_task_note`, `task_handoff`,
`sub_task_handoff`; `handoff` umfasst beide Handoff-Arten, `types=[]` keine.
`since` ist inklusive, ISO8601 mit expliziter Zeitzone. Aufgaben/Teilaufgaben/
Handoffs verwenden `created_at`, editierbare Notizen `updated_at`; SQLite-Zeiten
sind UTC und `date` wird mit `Z` geliefert. Suche ist kein Aenderungsfeed.

Alle Typen werden gemeinsam nach BM25-Relevanz sortiert, Gleichstand nach
Datum absteigend und stabiler Quell-ID. Aktuelle Rechte und Filter greifen vor
dem Limit (wie bisher auf 1–200 begrenzt). Treffer liefern eindeutige IDs,
Datum/Person soweit vorhanden und ungefaehr zwei Zeilen Fundstellenkontext.
`snippet` bleibt Klartext (maximal 322 Zeichen), `snippet_html` ergaenzt sicher
maskierten Text mit erzeugten `<mark>`-Tags. HTML aus Inhalten wird nicht aktiv.
Titel/Benutzernamen sind auf 160 Zeichen begrenzt. Handoffs mit `handoff.get`,
Aufgaben/Teilaufgaben mit Detailwerkzeugen, User-Notizen mit `note.list` nachladen.

Der Index wird beim Upgrade atomar initial befuellt und per Trigger bei REST-/
MCP-Schreibzugriffen und Kaskaden gepflegt. Wiederholte Initialisierung ist sicher;
fehlende Trigger loesen Reparatur/Backfill aus. SQLite FTS5 ist Voraussetzung,
bei fehlendem Modul bricht die Suchmigration mit klarer Diagnose ab und wird
zurueckgerollt. Wartungs-Rebuild: `rebuild_search_index(db)` aus
`dashboard.search_service` innerhalb von `db_transaction()`; Daten bleiben in
Originaltabellen. Vor produktiven Migrationen die Datenbank sichern.

## Dateiablage per REST

Fuer direkte Dateiuebertragungen, auch ueber 1 MiB, gilt derselbe MCP-Token
an den folgenden Endpunkten. Eine Web-Anmeldung ist dafuer nicht erforderlich.

| Methode | Pfad | Parameter / Body |
|---------|------|------------------|
| GET | `/api/tasks/{task_id}/files` | Optionaler Unterordner als Query `path` |
| GET | `/api/tasks/{task_id}/files/download` | Datei als Query `path`, Antwort sind Dateibytes |
| POST | `/api/tasks/{task_id}/files/upload` | Multipart-Feld `file`, optional Zielordner als Query `path`, maximal 500 MiB |
| POST | `/api/tasks/{task_id}/files/mkdir` | JSON `{"name": "Ordner"}`, optional Elternordner als Query `path` |
| PUT | `/api/tasks/{task_id}/files/move` | JSON `{"source": "alt.txt", "destination": "neu.txt"}` |
| DELETE | `/api/tasks/{task_id}/files` | Query `path`, Ordner werden rekursiv geloescht |

Bei jedem Aufruf `Authorization: Bearer <token>` senden, bei Schreibzugriffen
zusaetzlich `X-Requested-With: XMLHttpRequest`. Alle Pfade sind relativ zur
konfigurierten lokalen oder WebDAV-Ablage der Aufgabe bzw. des Projekts.
Leserechte erlauben Auflisten und Download, Bearbeitungsrechte auch Aenderungen.
Token-Widerruf und der globale MCP-Ausschalter greifen bei jedem Aufruf.
Ein expliziter Authorization-Header hat Vorrang vor einer Web-Session.
Andere REST-Endpunkte, Ablagekonfiguration und Office-Editor brauchen weiterhin
eine Web-Anmeldung.

```bash
curl --fail --get 'http://10.0.12.7:8514/api/tasks/<task_id>/files/download' \
  --header 'Authorization: Bearer <token>' \
  --data-urlencode 'path=Unterlagen/Plan.pdf' --output Plan.pdf

curl --fail 'http://10.0.12.7:8514/api/tasks/<task_id>/files/upload' \
  --header 'Authorization: Bearer <token>' \
  --header 'X-Requested-With: XMLHttpRequest' \
  --form 'file=@Plan.pdf'
```

## AGENTS.md-Snippet

Dieses Snippet in das Zielprojekt uebernehmen und die Platzhalter ersetzen:

```markdown
## Casos-Projektplanung

Projektplanung laeuft in Casos. Casos ist fuer dieses Projekt die gemeinsame
Planungsoberflaeche fuer Projekte, Sprintpakete, Abhaengigkeiten, Fortschritt
und Entscheidungen. Codex/Claude greift per MCP darauf zu.

- Web-UI: `http://10.0.12.7:8514/`
- MCP-Endpoint: `http://10.0.12.7:8514/mcp/`
- MCP-Server: `casos`
- Casos-Projekt: `<Projektname>` (ID `<project_id>`)
- Erwarteter MCP-User: `<MCP-User-Anzeigename>`
- Token niemals ins Repo schreiben; nur `<token>` als Platzhalter dokumentieren.

Arbeitsregeln:

- Vor Schreiboperationen `get_project_status` lesen; Beschreibungen gezielt nachladen.
  Projekt-Beschreibungsrevision: `project.description_revision`.
- Ueblich: `get_project/list_subtasks(include_description=false)`.
- `update_project/update_subtask` bestaetigen nur mit `{"ok": true}`, ohne
  `compact`-Parameter. Optionale Audit-Begruendung: `reason`.
- Beschreibungsrevision mitsenden; `patch_description` fuer exaktes Anhaengen
  oder eindeutiges Ersetzen. Bei Konflikt neu lesen und abgleichen.
- `id` ist stabil, `position_number` die veraenderliche Reihenfolge, `name`
  der fachliche Titel ohne Positionspraefix. Sinnvolle Zahlen nicht entfernen.
- `search` verwendet UND-Woerter, zitierte Phrasen und Wortpraefixe mit `*`;
  `project_id`, `types`, `since` filtern, `handoff.get` laedt gezielt nach.
- `file.append` ergaenzt vorhandene UTF-8-Dateien exakt bis 1 MiB gesamt,
  ohne impliziten Zeilenumbruch; nach unklarem Fehler erst Inhalt pruefen.
- `description` enthaelt Scope, Implementierungsbriefing, Akzeptanzkriterien
  und Definition of Done.
- Beschreibungen, Notizen und Handoffs als Markdown-Quelltext schreiben,
  nicht als gerendertes HTML.
- `handoff.add` dokumentiert Fortschritt, Handoffs, Entscheidungen,
  Testergebnisse, Blocker und Audit-Zusammenfassungen als neuen Verlaufseintrag.
- `handoff.list` liest diese Verlaufseintraege; `handoff.delete` loescht einen
  Handoff anhand seiner typisierten `handoff_id` (`task:123` oder
  `subtask:456`).
- Admins koennen bestehende Inhalte mit `note.update` (Autor-`user_id`) und
  `handoff.update` (typisierte `handoff_id`) korrigieren. Autor und
  Erstellungszeit bleiben erhalten; der Bearbeiter wird im Audit protokolliert.
  Autoren duerfen eigene Handoffs mit Beitragsrechten fuer 300 Sekunden mit
  Revision aus `handoff.get/list` korrigieren; Admins bleiben zeitlich unbeschraenkt.
- `note.write` aktualisiert nur die eine aktuelle Notiz des aufrufenden Users;
  wiederholte Aufrufe ueberschreiben diese Notiz.
- `note.list` liest editierbare User-Notizen; `note.delete` loescht nur die
  eine aktuelle Notiz des aufrufenden Users.
- Eine Projektzuweisung erlaubt Lesen der Notizen/Handoffs aller Teilaufgaben
  und Schreiben eigener Beitraege, ohne Einzelzuweisung. Dabei ist `task_id`
  die Projekt-ID und `subtask_id` die Teilaufgaben-ID.
- `predecessor_ids` sind echte DAG-Abhaengigkeiten zwischen Sprintpaketen.
- Nur notwendige direkte Vorgaenger im selben Projekt angeben. Wenn C von B
  und B von A abhaengt, darf C nicht zusaetzlich direkt von A abhaengen.
  Das gilt auch, wenn eine neue Verbindung eine vorhandene direkte Kante
  ueberfluessig machen wuerde. Vorgaengerlisten bei Bedarf komplett ersetzen.
- Positionsaenderungen sind nur Sortierung/Anzeige; sie aendern keine
  Abhaengigkeitsgueltigkeit.
- REST, MCP und Dateiablage pruefen dieselben Aufgabenrechte. Lesefreigaben
  erlauben nur Lesen, Schreibfreigaben auch Inhalte und eigene Beitraege.
  Projektfreigaben gelten fuer alle Teilaufgaben, Erstellen braucht ein eigenes Recht.
- Zuweisungen, Loeschen von Aufgaben/Teilaufgaben und Freigaben verwalten nur Ersteller und Admins.
  Das gilt auch fuer `assign_self`. Bei fremden Aufgaben muss der Ersteller
  oder ein Admin die Session zuweisen oder freigeben.
- `file.list`, `file.read`, `file.write`, `file.mkdir`, `file.move` und
  `file.delete` nutzen die konfigurierte lokale oder WebDAV-Projektablage.
  `task_id` ist die Projekt-ID, Pfade sind relativ zu dessen Ablage.
  Lesen braucht Leserechte, Dateiaenderungen brauchen Bearbeitungsrechte.
- `file.read` liefert UTF-8 oder Base64 (Feld `encoding`). `file.write`
  ersetzt die gesamte Datei, daher vorher lesen. Maximal 1 MiB je Datei beim
  Lesen/Schreiben, groessere Dateien ueber die REST-Datei-API oder Web-UI. `file.list` liefert
  bei weiteren Eintraegen `next_offset`. `file.delete` loescht Ordner samt Inhalt.
- Die REST-Dateiablage unter `/api/tasks/{task_id}/files` akzeptiert denselben
  MCP-Token als `Authorization: Bearer <token>`. Schreibzugriffe brauchen
  zusaetzlich `X-Requested-With: XMLHttpRequest`. Uploads laufen als Multipart
  mit Feld `file` (maximal 500 MiB), Downloads liefern die Dateibytes.
  Aufgabenrechte, Token-Widerruf und der MCP-Ausschalter gelten auch dort.
- Gitea-Issues enthalten konkrete Findings/Bugs; Casos enthaelt
  Zusammenfassung und Issue-IDs/Links.
- Keine Secrets, Tokens, Passwoerter oder privaten Schluessel in Casos-Notizen,
  AGENTS.md, docs/, .env, Logs oder Issues schreiben.
```

Eine separate Kopiervorlage liegt in `docs/casos-agents-snippet.md`.

## Zielprojekt Einrichten

1. `AGENTS.md` im Zielprojekt lesen oder anlegen.
2. Abschnitt `Casos-Projektplanung` aus dem Snippet einfuegen.
3. Lokale MCP-Verfuegbarkeit pruefen.
4. Falls MCP fehlt: lokale Client-Konfiguration einrichten, Session neu starten.
5. Casos-Projekt per MCP suchen oder anlegen.
6. Projekt-ID und erwarteten MCP-User in `AGENTS.md` dokumentieren.
7. Sprintpakete als Casos-Subtasks anlegen.
8. Abhaengigkeiten mit `predecessor_ids` bzw. Dependency-Tools modellieren.
9. Laengere Implementierungsplaene im Zielprojekt unter `docs/TODOS/` ablegen
   und dort auf Casos-Projekt-/Subtask-IDs verweisen.
10. Fortschritt, Handoffs und Entscheidungen waehrend der Arbeit per
    `handoff.add` dokumentieren.

## Fachliche Nutzung

Casos ist die Steuerungsebene:

- Projekte: Epics oder groessere Arbeitsvorhaben.
- Subtasks: operative Sprintpakete oder klar abgrenzbare Arbeitspakete.
- Dependencies: echte Reihenfolge-/Blocker-Beziehungen im DAG.
- Notes: `note.write` fuer die aktuelle eigene Notiz, `note.list` zum Lesen
  editierbarer User-Notizen, `note.delete` zum Loeschen der eigenen Notiz.
- Handoffs: `handoff.add` fuer Fortschritt, Entscheidungen, Testergebnisse,
  Uebergaben und Audit-Zusammenfassungen; `handoff.list` zum Lesen;
  `handoff.delete` zum Loeschen anhand der typisierten `handoff_id`
  (`task:123` oder `subtask:456`).
- Assignments: aktuelle Bearbeitung und Verantwortlichkeit.

Markdown-Dateien im Zielprojekt bleiben sinnvoll fuer laengere Plaene,
Spezifikationen und Sprint-TODOs. Sie ersetzen Casos nicht, sondern verlinken
auf Casos-IDs.

## Haeufige Fehler

- Token in `AGENTS.md`, docs, `.env`, Logs oder Casos-Notizen schreiben.
- `localhost:8514` in einem Remote-Projekt dokumentieren.
- Kiron (`10.0.12.16:8505`) statt Casos verwenden.
- Bei fehlendem MCP eine lokale Schatten-DB anlegen.
- Andere REST-Endpunkte als die Dateioperationen mit MCP-Bearer aufrufen.
- Positionsnummern als Dependency-Gueltigkeit interpretieren.
