# Tareas - Agenten-Kontext

Stand: 11.10.2026, um Projekt #75 ergaenzt und gegen Repo-Dateien geprueft.

## Projektziel

Tareas ist ein selbst gehostetes Aufgaben- und Projektplanungs-Tool auf Basis von **FastAPI + Vanilla JS**. Es bietet Aufgaben, Projekte mit Teilaufgaben, Abhaengigkeiten, Netzplan, Teamrechte, Notizen, Dateiablage, Office-Bearbeitung, Benachrichtigungen und Admin-Konfiguration.

## Grundentscheidungen

| Aspekt | Stand |
|--------|-------|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Frontend | Vanilla JS, keine Frameworks |
| Styling | CSS Custom Properties, Light/Dark Theme |
| Datenbank | SQLite unter `data/tareas.db`, WAL mode, Foreign Keys |
| Auth | bcrypt + itsdangerous, Cookie-Session `tareas_session` |
| Credentials at rest | Fernet-Verschluesselung via `dashboard/crypto_utils.py` |
| Haupt-App | `dashboard/app.py`, Port 8504 |
| Admin-App | `dashboard/admin_app.py`, Port 8505 |
| MCP-App | `dashboard/mcp_app.py`, Port 8506, bestehendes `/mcp/` auf 8504 bleibt |
| Routing | SPA mit History API + Backend-Catch-All |
| OS | Ubuntu 24.04 LTS |

## Infrastruktur

| Komponente | Details |
|------------|---------|
| Haupt-Service | `tareas.service`, startet `dashboard/app.py` |
| Admin-Service | `tareas-admin.service`, startet `dashboard/admin_app.py` |
| MCP-Service | `tareas-mcp.service`, startet `dashboard/mcp_app.py`, Betriebslogs im Journal |
| Mail-Scheduler | `tareas-mail-scheduler.timer`, taeglich 00:01 |
| LDAP-Sync | `tareas-ldap-sync.timer`, 5 Min. nach Boot, danach alle 15 Min. |
| Lokale Services | `scripts/*.service`, Pfad `/sdb1/nextcloud/data/mir/files/Dev/Tareas` |
| Paket-Services | `packaging/services/*.service`, Pfad `/opt/tareas`, User `tareas` |
| Logging | Haupt-App schreibt nach `/var/log/tareas.log`, Fallback stderr |
| Runtime-Daten | `data/` mit SQLite-DB und `secret.key`, per `.gitignore` ausgeschlossen |

## Wichtige Features

- Aufgaben und Projekte mit Teilaufgaben, Positionen, Prioritaet, Deadline und Status.
- Kind-Projekte haengen ueber `tasks.parent_subtask_id` an genau einer Eltern-Teilaufgabe, hoechstens ein Kind-Projekt je Subtask (Unique-Index). Die PID-Spalte zeigt die Eltern-Teilaufgaben-ID und navigiert dorthin. `project_links.py` prueft fuer REST/MCP gemeinsam Bearbeitungsrechte beider Seiten, Projekttypen und Zyklen. Der Eltern-Fortschritt entspricht dem abgerundeten Anteil vollstaendig erledigter Kind-Teilaufgaben (leer = 0), Weitergabe ueber alle Ebenen unter derselben DB-Schreibsperre. Manuelles `status_percent` ist dabei auch fuer Admins gesperrt (`linked_project_progress_readonly`). REST/MCP liefern `parent_subtask_id`, `parent_project_id`, `progress_percent` bzw. `child_project_id`, `progress_automatic`. MCP `create_project`/`update_project` akzeptieren die PID, `0` trennt (REST auch explizites `null`). Trennen/Loeschen des Kindes behaelt den letzten Eltern-Fortschritt, Loeschen des Eltern-Subtasks/-Projekts trennt Kinder ohne deren Projekte zu loeschen. Keine Rechtevererbung, Typwechsel erst nach Trennung der Verknuepfungen. UI im aufgeklappten Subtask: bestehendes Projekt verknuepfen, neues Kind-Projekt erstellen oder Verbindung trennen.
- Beim Aufklappen eines Projekts werden die anderen Listenzeilen, der Tabellenkopf und die Filterleiste ausgeblendet. Zuklappen stellt die gefilterte/sortierte Liste samt Filterleiste wieder her, der Teilaufgaben-Tabellenkopf bleibt sichtbar.
- Beim Zuklappen eines Projekts beruecksichtigt die Scrollkorrektur die aktuell gemessenen Hoehen von App-Header, Filterleiste und Tabellenkopf. Die Projektzeile bleibt mit 4px Abstand darunter sichtbar, soweit die natuerlichen Scrollgrenzen dies erlauben.
- Beim Zuklappen einer Teilaufgabe bleibt deren Tabellenzeile an derselben Bildschirmposition. `--project-scroll-min-height` reserviert bei Bedarf Leerraum ausserhalb des Projektrahmens, der beim Zurueckscrollen abgebaut wird und nur in der Projektansicht gilt.
- Teilaufgaben oeffnen/schliessen mit einer 240-ms-Animation fuer Hoehe und Deckkraft. CSS Grid beruecksichtigt wechselnde Inhaltshoehen, schnelle Klicks kehren die laufende Animation um. Beim Wiederherstellen nach einem Daten-Reload und bei `prefers-reduced-motion` erfolgt der Wechsel ohne Animation.
- Abhaengigkeiten zwischen Teilaufgaben und optional vom Projektknoten.
- `dashboard/dependency_service.py` prueft Vorgaenger-Aenderungen aus REST und MCP gemeinsam: gleiches Projekt, keine Selbstbezuege/Zyklen und keine neuen transitiv redundanten Kanten, auch nicht an anderen Teilaufgaben. Pruefung und Schreiben laufen unter einer DB-Schreibsperre. Bestehende Alt-Redundanzen koennen schrittweise entfernt werden. Projektknoten `0` ist nur als alleiniger Vorgaenger erlaubt. UI-Auswahl und Netzplan verwenden dieselben Regeln.
- Interaktiver Netzplan mit `vis-network`.
- Freigaben fuer Aufgaben und Projekte in Einstellungen -> Berechtigungen (Zahnrad in der Zeile). Ersteller und Admins verwalten Benutzer, Lesen/Bearbeiten und bei Projekten zusaetzlich Teilaufgaben erstellen. Dialogaenderungen sind lokale Entwuerfe bis Speichern, atomarer PUT auf `/api/tasks/{id}/members` mit Revisionspruefung verhindert verlorene parallele Aenderungen.
- `dashboard/permissions.py` berechnet effektive Rechte fuer REST, MCP, Dateiablage und UI-Metadaten. Bestehende Tabelle `project_members` speichert Freigaben auch fuer normale Aufgaben. Bearbeiten schliesst Lesen ein, Projektfreigaben gelten fuer Teilaufgaben. Zuweisungen, Loeschen und Rechteverwaltung bleiben Ersteller/Admin vorbehalten. Reine Lesefreigaben erlauben keine eigenen Notizen/Handoffs, bestehende Zuweisungsrechte fuer eigene Beitraege bleiben bestehen. MCP `assign_self` braucht ebenfalls Verwaltungsrechte.
- Aufgaben-/Teilaufgaben-Zuweisung und Notizen fuer Zugewiesene.
- Projektzuweisungen vererben Leserechte auf alle Teilaufgaben samt Notizen/Handoffs in REST, MCP und MCP-Suche. Eigene Notizen und Handoffs sind damit ebenfalls erlaubt, ohne zusaetzliche Teilaufgaben-Zuweisung. Fremde Inhalte bleiben vor Aenderungen durch normale Nutzer geschuetzt. Die REST-Teilaufgabenliste gewaehrt durch die Projektzuweisung allein keine Bearbeitungs-/Erstellungsrechte.
- Markdown-Beschreibungen mit formatierter Leseansicht und Bearbeiten/Speichern/Abbrechen. WYSIWYG-Code bleibt erhalten, die Funktionen sind ausgeblendet. HTML-Ausgabe laeuft durch den zentralen Sanitizer in `app_core.js`. Beschreibungen behalten beim Moduswechsel ihre Abmessungen. Beim Zeilen-Neuaufbau waehrend eines Speicherns uebernimmt der neue `MarkdownEditor` den laufenden Vorgang samt Eingabesperre. Erfolg aktualisiert Inhalt und Revision der aktuellen Instanz sowie ihres Zeilenmodells, Fehler erhalten Entwurf und Basisrevision.
- Teilaufgaben-Handoffs stehen als responsives Widget-Grid rechts neben der Beschreibung, mit ID, Autor, Zeitpunkt und Textvorschau. Gemeinsame Hoehe und Spaltenbreiten lassen sich wie bei Projektbeschreibung/Dateiablage verstellen. Einfachklick oeffnet den nativen Dialog, Doppelklick direkt ein Fenster unter `/handoff`. Ausklappen uebernimmt offene Entwuerfe. GET `/api/tasks/{id}/subtasks/{subtask_id}/note-entries/{entry_id}` prueft aktuelle Leserechte, Admin-PUT kann eine Revision gegen parallele Aenderungen mitsenden. Speichern aktualisiert die Widgets, Autor und Zeitpunkt bleiben erhalten.
- Projekt-/Aufgaben-Handoffs nutzen dieselben Widgets und Dialoge in einem Grid mit natuerlicher Hoehe ohne Resize-Rahmen. Alle Widgets zeigen eine einzeilige Textvorschau und passen ihre Hoehe an den Inhalt an. Einzelzugriff per GET/PUT `/api/tasks/{id}/note-entries/{entry_id}`; `/handoff` ohne `subtaskId` adressiert Projekt-Handoffs. Fenster-Rueckmeldungen unterscheiden Projekt und Teilaufgabe auch bei identischen Handoff-IDs.
- Nextcloud/WebDAV-Dateiablage ueber `dashboard/webdav.py` und `api_nextcloud.py`.
- WebDAV-Transportfehler in der Datei-REST-API liefern JSON mit `files.webdavConnectionError` (503) bzw. `files.webdavTimeout` (504). Dateibrowser und nativer Texteditor uebersetzen die Meldungen, technische Ursachen bleiben im Serverlog. Fehlgeschlagene Unterordner-Aufrufe im Dateibaum zeigen einen Fehler und lassen sich erneut aufklappen.
- Native Textdateien pruefen beim Speichern die Revision vom Oeffnen. `TaskStorage.update_file` haelt eine prozessuebergreifende `flock`-Sperre ueber Lesen, Pruefen und Schreiben; `upload_file` nutzt dieselbe Sperre auch fuer MCP-, REST- und Office-Schreibzugriffe. Gemeinsame Lockdateien unter `data/.file-locks/` identifizieren den Ablagepfad, einschliesslich geteilter WebDAV-Pfade. HTTP 409 laesst den Editor mit Entwurf im Bearbeitungsmodus. Keine Bearbeitungsreservierungen oder zusaetzlichen Agenten-Aufrufe; die Sperre gilt nur waehrend des Speichervorgangs. Lockdateien im laufenden Betrieb nicht entfernen.
- Alternativ lokale Dateiablage pro Aufgabe/Projekt unter `data/files/task-<ID>/`, gemeinsame Dateischnittstelle in `dashboard/file_storage.py`. Auswahl ueber `file_storage_type` (`local`, `webdav`, `none` in der API), bestehende `nextcloud_path`-Zuordnungen bleiben kompatibel. Lokale Dateien bei Backups einschliessen.
- Die Dateiablage wird im Header des Dateibrowsers konfiguriert. Beim expliziten Entfernen einer lokalen Ablage wird nach Bestaetigung auch `data/files/task-<ID>/` samt Inhalt geloescht. Beim Entfernen einer WebDAV-Zuordnung bleibt das Remote-Verzeichnis erhalten. Ein Wechsel der Ablageart und das Loeschen einer Aufgabe behalten lokale Dateien zur manuellen Wiederherstellung/Bereinigung bei. Datei-Schreibzugriffe brauchen Bearbeitungsrechte, ONLYOFFICE unterstuetzt beide Ablagearten.
- ONLYOFFICE/WOPI-Integration ueber `api_onlyoffice.py` und `/editor`.
- Die Office-Editor-Seite laedt ihren Startcode extern aus `editor_page.js`, damit auch die strikte CSP ohne ONLYOFFICE-Konfiguration greift und API-Fehler sichtbar werden. Dateilisten liefern `onlyoffice_configured`, Office-Aktionen brauchen eine Konfiguration. ONLYOFFICE-Origin direkt aus der DB lesen, damit Aenderungen aus dem separaten Admin-Prozess sofort in neuen CSP-Antworten/Dateilisten ankommen.
- Markdown-, Text- und Scriptdateien haben Vorrang vor ONLYOFFICE und oeffnen im nativen Dialog (`text_file_editor.js`) bzw. via Ausklappen unter `/text-editor`. `MarkdownEditor` liefert die formatierte Markdown-Vorschau oder mit `plainText` eine woertliche Codeansicht, standardmaessig lesen, dann Bearbeiten/Speichern/Abbrechen. Entwuerfe per origin-/fenstergeprueftem postMessage uebertragen, Dialog erst nach erfolgreicher Uebernahme schliessen. Kein Entwurf in URLs/localStorage. Dateilisten liefern `text_format` aus `text_files.py`, GET/PUT `/api/tasks/{id}/files/text` nutzt die aktuellen Dateirechte, Revision und Audit. Max. 2 MiB, UTF-8 oder UTF-16 mit BOM, Encoding/BOM/Zeilenenden erhalten. Bilder weiter inline, uebrige Dateien als Download.
- LDAP/Active Directory Login und Sync ueber `api_ldap.py`, `ldap_utils.py`, `ldap_sync.py`.
- Mail-Benachrichtigungen mit SMTP-Konfig, Templates und User-Prefs.
- Optionales TLS inkl. Zertifikatspfaden und Verify-Flags pro Integration.
- MCP-Server unter `/mcp/` mit FastMCP, Bearer-Token-Auth und Audit-Log.
- Admin-UI fuer Allgemein, Benutzer, LDAP, Nextcloud, ONLYOFFICE, Mail, TLS, MCP.
- i18n mit JSON-Dateien unter `dashboard/static/i18n/` fuer de/en/es/fr/ro/ru/uk.

## Import- und App-Pattern

- Services starten `dashboard/app.py`, `dashboard/admin_app.py` und `dashboard/mcp_app.py` als Script, nicht als Modul.
- Alle drei Apps setzen `sys.path.insert(0, str(Path(__file__).parent.parent))`, damit `dashboard` als Package importierbar ist.
- In App-/Router-Code absolute Imports verwenden, z.B. `from dashboard.database import ...`.
- Keine relativen Imports wie `from .database` in App-/Router-Dateien verwenden.
- `dashboard/__init__.py` macht `dashboard` zum Package.
- `dashboard/components/__init__.py` nutzt relative Imports intern, das ist dort korrekt.

## Datenbank

- DB-Pfad: `dashboard/database.py` setzt `DB_PATH = data/tareas.db`.
- `get_db()` aktiviert `PRAGMA foreign_keys = ON` und setzt `sqlite3.Row`.
- `init_db()` aktiviert `PRAGMA journal_mode=WAL`, erstellt Tabellen und fuehrt Migrationen aus.
- Wichtige Tabellen: `areas`, `tasks`, `sub_tasks`, `sub_task_dependencies`, `users`, `sessions`, `task_notes`, `sub_task_notes`, `project_members`, Integrations-Configs, `mcp_tokens`, `audit_log`, `mcp_config`.
- `subtask_permissions` wird bewusst gedroppt; Projektrechte laufen ueber `project_members`.
- Wenn keine User existieren, legt `init_db()` derzeit einen Default-Admin `admin` mit Passwort `admin` an.
- Fuer neue DB-Zugriffe bevorzugt `dashboard/db_utils.py`: `db_query()`, `db_transaction()`, `upsert_singleton_config()`, `build_update_query()`.
- Bei dynamischen SQL-Identifiern Whitelists in `db_utils.py` erweitern statt freie Tabellen-/Spaltennamen einzubauen.

## API-Struktur

### Haupt-App `dashboard/app.py`

- Bindet Router fuer Auth, Tasks, Teams, Nextcloud-Dateien, ONLYOFFICE WOPI/Editor und Mail-User ein.
- `/api/dashboard/info` liefert Entwickler- und Komponenteninfos.
- `/mcp/` ist als FastMCP-ASGI-App gemountet.
- HTML-Routen: `/login`, `/`, `/editor`, `/text-editor`, `/handoff`, Catch-All `/{path:path}`.
- Mutierende `/api/`-Requests brauchen `X-Requested-With: XMLHttpRequest`, ausgenommen WOPI/ONLYOFFICE Callback.

### Admin-App `dashboard/admin_app.py`

- Bindet Admin-Router fuer Benutzer, LDAP, Nextcloud, ONLYOFFICE, Mail, App-Config, TLS und MCP ein.
- `/api/dashboard/restart` startet `tareas.service`, `tareas-admin.service` und `tareas-mcp.service` neu und ist nur fuer Admins.
- HTML-Routen: `/login`, `/`, Catch-All.

### Router-Dateien

| Datei | Zweck |
|-------|------|
| `api_auth.py` | Login, Logout, aktueller User, Passwortaenderung |
| `api_tasks.py` | Tasks, Subtasks, Dependencies, Notes, Areas, User-Liste, Tabellenconfig |
| `api_teams.py` | Projektmitglieder und Teamrechte |
| `api_admin.py` | Benutzerverwaltung |
| `api_admin_mcp.py` | MCP-Konfig, Token-Verwaltung, Audit-Log |
| `api_app.py` | Allgemeine App-Konfig, u.a. Server-Adresse |
| `api_ldap.py` | LDAP-Konfig, Gruppen, Sync |
| `api_nextcloud.py` | Nextcloud Admin-Konfig und Datei-API |
| `api_onlyoffice.py` | ONLYOFFICE Admin-Konfig, WOPI, Editor-Start |
| `api_mail.py` | Mail-Admin-Konfig/Templates/Test/Invite und User-Prefs |
| `api_tls.py` | TLS-Konfig und Verify-Flags |

## MCP

- Port 8506 stellt denselben MCP-Endpunkt `/mcp/` wie Port 8504 bereit. Werkzeuge bleiben ausschliesslich in `mcp_server.py`, HTTP-Mount, Lifespan und Bearer-Auth liegen gemeinsam in `mcp_transport.py`. Beide Dienste greifen direkt auf dieselbe DB zu, brauchen keine Weiterleitung ueber 8504 und nutzen dieselbe TLS-Konfiguration. Bestehende Clients auf 8504 bleiben kompatibel.
- `mcp_app.py` bietet nur MCP, Datei-REST und tokenfreie Bootstrap-Endpunkte. `file_operations_router` in `api_nextcloud.py` wird mit der Haupt-App geteilt. Auf 8506 prueft `MCPAuthMiddleware` den Datei-REST-Bearer vor dem Einlesen des Request-Bodys, die Dependency `get_mcp_user` prueft danach erneut. Browser-Cookies reichen dort nicht aus. Datei-Uploads auf beiden Ports akzeptieren genau ein Multipart-Dateifeld bis 500 MiB, begrenzen die Dateibytes waehrend des Empfangs ohne Content-Length-Vorabpruefung und schliessen temporaere Dateien auch bei Abbruch/HTTP 413. Allgemeine REST-/Login-/Office-/Admin-/Static-Routen sind auf 8506 nicht eingebunden. Datei-Schreibzugriffe brauchen auf beiden Ports den bestehenden CSRF-Header.
- Admin-MCP-Konfig behaelt `server_url` fuer 8504 und liefert zusaetzlich `dedicated_server_url` fuer 8506. Neue Kopiervorlagen nutzen 8506. Bootstrap und MCP-Guide verwenden auf dem dedizierten Zugang dessen Adresse auch fuer Datei-REST, ohne Web-/Admin-URLs umzubiegen. Laufende Transport-Sessions gelten jeweils nur fuer ihren Dienst.
- `dashboard/mcp_server.py` definiert FastMCP mit Tools fuer Projekte, Subtasks, Dependencies, Notes, Suche, Users, Areas, Selbstzuweisung und `whoami`.
- `dashboard/task_validation.py` definiert gemeinsame REST-/MCP-Regeln: Status nur `offen`, `in_arbeit`, `erledigt`, `abgebrochen`, Teilaufgabenfortschritt strikt ganzzahlig von 0 bis 100. `task_status.py` leitet den Projektstatus fuer REST und MCP gemeinsam aus vollstaendig erledigten Teilaufgaben ab. Leere Projekte und Projekte ohne erledigte Teilaufgabe bleiben `offen`, einige erledigte Teilaufgaben ergeben `in_arbeit`, alle ergeben `erledigt`. `abgebrochen` hat Vorrang, normale Aufgaben behalten manuelle Statuswerte. Die Ableitung veraendert keine gespeicherten Daten.
- `list_projects_page` bietet kompakte Projektlisten mit `offset`, `limit` (Standard 50, maximal 500), optional `include_description` und `next_offset`. Sichtbarkeit und effektiver Status werden vor der Pagination gefiltert, Sortierung nach Prioritaet, Erstellzeit und ID absteigend. `list_projects` behaelt seine bisherige Listenantwort, `get_project` liefert Details.
- `dashboard/errors.py` ergaenzt Fachfehler um stabile Codes/Felder bei unveraendertem REST-`detail`. `mcp_errors.py` liefert Werkzeugfehler mit `isError=true`, `code`, `message` und gegebenenfalls `field`/`fields` in `structuredContent` sowie JSON-Text. Schemafehler werden ebenfalls strukturiert gemeldet. Bei fehlender Ablage nennt MCP den initialen Button `Dateiablage` und die benoetigten Browser-Bearbeitungsrechte; REST/UI-Texte bleiben kompatibel.
- Auth laeuft per Bearer-Token ueber die gemeinsame `MCPAuthMiddleware` in `dashboard/mcp_transport.py`.
- MCP-Werkzeuge lesen die aktuelle Identitaet aus `get_http_request().state.mcp_user`, damit Token- und Adminrechte-Wechsel auch in laufenden Transport-Sessions gelten. `current_mcp_user` bleibt nur fuer direkte Aufrufe ohne HTTP erhalten.
- Die REST-Dateioperationen unter `/api/tasks/{task_id}/files` (Auflisten, Download, Upload, mkdir, move, delete sowie GET/PUT text) akzeptieren denselben MCP-Bearer ueber `get_file_user`. Ein expliziter Authorization-Header hat Vorrang vor einer Cookie-Session. Aufgabenrechte, Token-Widerruf und MCP-Kill-Switch gelten auch dort, Schreibzugriffe brauchen weiterhin `X-Requested-With: XMLHttpRequest`. Andere REST-Endpunkte und der Office-Editor bleiben Session-basiert.
- MCP-Tokens werden nur als SHA-256-Hash in `mcp_tokens` gespeichert; Plain-Token ist nur beim Erstellen sichtbar.
- Jeder MCP-Token gehoert zu einem eigenen User mit `auth_source='mcp'`.
- Schreiboperationen sollen `audit_log.log_change(...)` verwenden.
- `file.list/read/write/mkdir/move/delete` nutzen `dashboard/file_storage.py` fuer lokale und WebDAV-Projektablagen mit aktuellen Projektrechten. `task_id` ist die Projekt-ID, Pfade sind relativ zur Ablage. Lesen/Schreiben maximal 1 MiB je Datei, UTF-8 oder Base64, Listen mit `offset`/`limit` (max. 500) und `next_offset`. `file.write` ersetzt die ganze Datei, `file.delete` loescht Ordner rekursiv, die Ablagewurzel ist geschuetzt. Audit ohne Dateiinhalte. `get_project`/`list_projects` liefern `file_storage_type`.
- Der globale MCP-Kill-Switch liegt in `mcp_config.enabled`.

- Projekt #75: `get_project`/`list_subtasks` unterstuetzen `include_description=false`, `update_project`/`update_subtask` `compact=true` (bestehende Vollantworten bleiben Standard). Kompakte Updates liefern tatsaechliche `changed_fields`, kurze wirksame Werte und bei Textaenderung Laenge/Revision. `project_views.py` liefert `get_project_status` mit konsistentem Snapshot, sichtbaren Zaehlern, maximal 200 Zeichen letzter Handoff-Vorschau und `readiness`/`blocker_ids`. 100%=completed, Abbruch=cancelled, Kindprojekt=delegated, unsichtbarer Vorgaenger=restricted, sonst blocked/ready. Startanker 0 blockiert nicht. `handoff.get` laedt einzelne Handoffs nach. ID bleibt technische Referenz, Position Anzeigereihenfolge, Name fachlicher Titel ohne Positionspraefix.
- `description_service.py` teilt Beschreibungsrevisionen und atomare Aenderungen zwischen REST/MCP. Reads liefern `description_revision`, Volltext-PUT/Update pruefen sie optional (Legacy ohne Revision bleibt bedingungslos). `patch_description` und REST PATCH auf `/api/tasks/{id}/description` bzw. `/api/subtasks/{id}/description` verlangen `revision`, `operation` append/replace, `text`, bei replace eindeutigen `old_text`. Exaktes Anhaengen ohne Newline, fehlende/mehrdeutige Ziele abweisen, Format erhalten. Konflikt 409/`revision_conflict`; Browser behaelt Entwurf und urspruengliche Revision auch beim Zeilen-Neuaufbau.
- Handoff-Autoren duerfen mit aktuellen Beitragsrechten innerhalb `0 <= Alter < 300` Sekunden Serverzeit UTC korrigieren. `note_service.py` prueft Rechte/Zeit/Revision gemeinsam unter BEGIN IMMEDIATE. Neue Autorroute braucht Revision, Adminroute bleibt optional kompatibel. Autor/ID/Erstellungszeit bleiben erhalten. REST/MCP-Reads liefern `can_write` und Revision, reale Bearbeiter stehen im Audit.
- `file.append` ergaenzt vorhandene UTF-8-Dateien exakt, optionalen BOM erhalten, keine automatische Newline/Neuanlage, keine NUL/UTF-16, Gesamtlimit 1 MiB. `TaskStorage.append_text` nutzt dieselbe prozessuebergreifende Sperre wie Upload/Texteditor/Office. Audit nur Metadaten. Nach unklaren Netzwerkfehlern lesen vor Wiederholung (nicht idempotent).
- MCP-Updates akzeptieren `reason` (maximal 1000 Unicode-Zeichen vor Trimmen, leer=null), getrennt vom fachlichen Diff in `audit_log.reason`, Admin-UI zeigt die Begruendung. Vor fachlichen Mutationen validieren, fuer kuenftige Tools `audit_log.normalize_reason` verwenden.
- `search_service.py` verwendet FTS5/unicode61 mit gemeinsamem BM25-Ranking, UND-Begriffen, Phrasen und Wortpraefixen. `search` filtert mit `project_id`, `types` (auch handoff-Alias), `since` (ISO8601 mit Zone, inklusiv). Notes nutzen updated_at, andere created_at UTC. Rechte vor Limit, begrenzte plain/HTML-escaped Fundstellen. Keine beliebige Teilwortsuche. Atomarer Backfill und Quelltrigger inkl. Kaskaden, FTS5 muss vorhanden sein; `rebuild_search_index(db)` im `db_transaction()` fuer Wartung. Migrationen vor Dienstneustarts sichern.

## Frontend-Konventionen

- Haupt-App zeigt die Aufgabenliste ohne Tab-Leiste in `dashboard/templates/index.html`. Der kompakte Header ist 44px hoch, der Titel `Tareas` verlinkt zur Aufgabenliste. Standardsortierung: angezeigte ID absteigend, inklusive positiver Teilaufgaben-IDs bei Pseudozeilen.
- Der Haupttabellenkopf bleibt beim Scrollen unter Header und Filterleiste angeheftet. In der Listenansicht entfaellt der obere Innenabstand des Inhaltscontainers, damit der Kopf schon ab dem ersten Scrollschritt seine Position haelt. `app_core.js` misst die Hoehen der Leisten per `ResizeObserver` und setzt `--task-table-header-top`, damit auch umgebrochene oder ausgeblendete Filterleisten beruecksichtigt werden.
- Admin-App hat Tabs `allgemein`, `benutzer`, `ldap`, `nextcloud`, `onlyoffice`, `mail`, `tls`, `mcp`.
- `dashboard/static/js/app_core.js` enthaelt Theme, Settings, 401-Interceptor, CSRF-Header, Routing, DOM-Caching, Notifications, Modal- und Sanitizer-Helfer.
- `showNotification(message, type)` unterstuetzt `info`, `success`, `error`.
- DOM-Caching speichert Tab-Inhalte als `DocumentFragment` inklusive Filterbar und Scrollposition.
- Frontend-Renderers werden lokal z.B. per `table.renderers['name'] = function` gesetzt.
- `onRowExpanded` kann Detailinhalt dynamisch ersetzen.
- i18n laeuft ueber `t()` und JSON-Dateien in `dashboard/static/i18n/`.
- Bei UI-Texten neue Keys in allen Sprachdateien ergaenzen.

## Wiederverwendbare Komponenten

### ExpandableTable

- Python: `dashboard/components/expandable_table.py`
- JS: `dashboard/static/js/expandable_table.js`
- CSS: `dashboard/static/css/expandable_table.css`
- Dataclasses: `Column`, `DetailField`, `Filter`, `PaginationConfig`, `ExpandableTable`.
- Unterstuetzt Sortierung, Filter, Pagination, Sticky Header, expandable Detail-Rows, i18n-Header via `i18n_key`.

### KPI-Cards / Widget-Dashboard

- Python: `dashboard/components/kpi_card.py`
- JS: `dashboard/static/js/kpi_grid.js`
- CSS: `dashboard/static/css/kpi_grid.css`
- Dataclasses: `KPICard`, `KPISection`, `KPITableRow`, `KPITableSection`, `WidgetColumn`, `Widget`, `WidgetDashboardConfig`.

### Weitere Frontend-Bausteine

- WYSIWYG: `dashboard/static/js/wysiwyg_editor.js`
- Dateiablage: `file_browser.js` / `file_browser.css`
- Nativer Datei-/Handoff-Dialog: `text_file_editor.js` / `text_file_editor.css`, Datei-Backend `text_files.py`, geteilter `MarkdownEditor`
- ONLYOFFICE: `onlyoffice_editor.js` / `onlyoffice.css`
- Netzplan: lokale `vis-network.min.js` / `vis-network.min.css`

## Neuen Haupt-App-Tab hinzufuegen

1. JS-Datei erstellen, z.B. `dashboard/static/js/tab_example.js`.
2. Init-Funktion definieren: `async function initExampleTab() { ... }`.
3. In `app_core.js` `parseRoute()`, `buildPath()` und `switchTab()` erweitern.
4. In `dashboard/templates/index.html` Navigation und Script-Include hinzufuegen. Aktuell gibt es keine Tab-Leiste, der Header-Titel verlinkt zur Aufgabenliste.
5. Optional neuen API-Router `dashboard/api_example.py` erstellen und in `dashboard/app.py` einbinden.
6. Optional Tabellen-Config mit `ExpandableTable` definieren.

## Neuen Admin-Tab hinzufuegen

1. JS-Datei `dashboard/static/js/tab_example.js` erstellen.
2. In `dashboard/templates/admin.html` Tab-Link, Script-Include, URL-Auswertung und `switchAdminTab()` erweitern.
3. Falls API noetig: Router-Datei erstellen und in `dashboard/admin_app.py` einbinden.
4. Admin-Endpunkte mit `get_admin_user` schuetzen.

## Sicherheit

- CSRF-Schutz: Mutierende API-Requests brauchen `X-Requested-With`.
- Security-Header/CSP werden in `app.py` und `admin_app.py` gesetzt.
- Login und Passwortaenderung haben Rate-Limiting in `api_auth.py`.
- Stored HTML nur ueber den Sanitizer erlauben; keine unsanitisierte HTML-Ausgabe.
- Dateioperationen muessen Pfadvalidierung gegen Path Traversal respektieren.
- Secrets/Credentials nicht im Klartext aus APIs zurueckgeben; Masking/Resolver in `config_utils.py` nutzen.
- TLS-Verify-Flags fuer Nextcloud, ONLYOFFICE, SMTP und LDAP beachten.
- Systemd-Hardening in Service-Dateien beibehalten.
- Audit-Log fuer MCP- und relevante Schreiboperationen nutzen.

## Projektstruktur

```text
Tareas/
|-- dashboard/
|   |-- app.py                  # Haupt-App, Port 8504
|   |-- admin_app.py            # Admin-App, Port 8505
|   |-- api_*.py                # API-Router
|   |-- database.py             # SQLite Schema/Migrationen
|   |-- db_utils.py             # DB-Context-Manager und SQL-Helper
|   |-- mcp_server.py           # FastMCP Tools
|   |-- components/             # Python-Komponenten
|   |-- static/
|   |   |-- css/                # Styles
|   |   |-- i18n/               # Sprachdateien
|   |   `-- js/                 # Frontend-JS
|   `-- templates/              # HTML-Templates
|-- docs/
|   `-- changelog.md            # CSV-Changelog
|-- packaging/                  # Debian/APT-Paket
|-- scripts/                    # Lokale systemd Services/Timer/Scheduler
|-- git-commit.sh               # Version + Commit + Push
|-- publish.sh                  # Packaging/Publish-Workflow
|-- requirements.txt
|-- version.txt
|-- README.md
|-- CLAUDE.md
`-- AGENTS.md
```

## Versionierung, Changelog und Commit

**Immer `./git-commit.sh` verwenden:**

```bash
./git-commit.sh "Kurze Beschreibung"
```

Das Script:
1. Inkrementiert die Build-Nummer in `version.txt`.
2. Staged alle Aenderungen mit `git add -A`.
3. Erstellt einen Commit mit Version-Prefix, z.B. `0.0.1+98: Beschreibung`.
4. Pusht zum Remote.

Regeln:
- Vor jedem Push immer `docs/changelog.md` aktualisieren.
- Changelog-Format: `Zeitstempel;Version;Kategorie;Beschreibung`.
- Zeitstempel immer mit Uhrzeit: `DD.MM.YYYY HH:MM`, nicht nur Datum.
- Kategorien konsistent halten, z.B. `Feature`, `Aenderung`, `Bugfix`, `Security`, `Docs`, `Refactoring`, `Infra`.

## Zwei-Umgebungen-Konvention

| | Hauptprojekt | Desktop-App |
|---|---|---|
| Umgebung | Bash auf Ubuntu 24.04 Server | PowerShell auf Windows 11 |
| Repo | `mir/Tareas` | `mir/Tareas-Desktop` |
| Pfad | `Tareas/` | `Tareas/clients/desktop/` |
| Commit | `./git-commit.sh "msg"` | `clients/desktop/git-commit.sh` |
| Changelog | `docs/changelog.md` | `clients/desktop/docs/changelog.md` |

Regeln:
- Bash/Linux bedeutet Hauptprojekt. Nur Hauptprojekt-Dateien aendern.
- PowerShell/Windows bedeutet ausschliesslich Desktop-App. Dann `clients/desktop/CLAUDE.md` lesen und nur unter `clients/desktop/` arbeiten.
- `clients/` ist per `.gitignore` ausgeschlossen und als eigenes Repo zu behandeln.
- Entwickler-PC ist Windows 11 und verbindet sich per SSH; Projektverzeichnis ist per SMB erreichbar.
- EXE-Builds/PyInstaller fuer Desktop koennen direkt auf dem Windows-PC laufen.

## Benutzer-Praeferenzen

- Sprache: Deutsch bevorzugt.
