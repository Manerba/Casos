# Tareas - Agenten-Kontext

Stand: 04.06.2026, gegen Repo-Dateien und Claude-Memory geprueft.

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
| Routing | SPA mit History API + Backend-Catch-All |
| OS | Ubuntu 24.04 LTS |

## Infrastruktur

| Komponente | Details |
|------------|---------|
| Haupt-Service | `tareas.service`, startet `dashboard/app.py` |
| Admin-Service | `tareas-admin.service`, startet `dashboard/admin_app.py` |
| Mail-Scheduler | `tareas-mail-scheduler.timer`, taeglich 00:01 |
| LDAP-Sync | `tareas-ldap-sync.timer`, 5 Min. nach Boot, danach alle 15 Min. |
| Lokale Services | `scripts/*.service`, Pfad `/sdb1/nextcloud/data/mir/files/Dev/Tareas` |
| Paket-Services | `packaging/services/*.service`, Pfad `/opt/tareas`, User `tareas` |
| Logging | Haupt-App schreibt nach `/var/log/tareas.log`, Fallback stderr |
| Runtime-Daten | `data/` mit SQLite-DB und `secret.key`, per `.gitignore` ausgeschlossen |

## Wichtige Features

- Aufgaben und Projekte mit Teilaufgaben, Positionen, Prioritaet, Deadline und Status.
- Beim Aufklappen eines Projekts werden die anderen Listenzeilen, der Tabellenkopf und die Filterleiste ausgeblendet. Zuklappen stellt die gefilterte/sortierte Liste samt Filterleiste wieder her, der Teilaufgaben-Tabellenkopf bleibt sichtbar.
- Beim Zuklappen eines Projekts beruecksichtigt die Scrollkorrektur die aktuell gemessenen Hoehen von App-Header, Filterleiste und Tabellenkopf. Die Projektzeile bleibt mit 4px Abstand darunter sichtbar, soweit die natuerlichen Scrollgrenzen dies erlauben.
- Beim Zuklappen einer Teilaufgabe bleibt deren Tabellenzeile an derselben Bildschirmposition. `--project-scroll-min-height` reserviert bei Bedarf Leerraum ausserhalb des Projektrahmens, der beim Zurueckscrollen abgebaut wird und nur in der Projektansicht gilt.
- Teilaufgaben oeffnen/schliessen mit einer 240-ms-Animation fuer Hoehe und Deckkraft. CSS Grid beruecksichtigt wechselnde Inhaltshoehen, schnelle Klicks kehren die laufende Animation um. Beim Wiederherstellen nach einem Daten-Reload und bei `prefers-reduced-motion` erfolgt der Wechsel ohne Animation.
- Abhaengigkeiten zwischen Teilaufgaben und optional vom Projektknoten.
- `dashboard/dependency_service.py` prueft Vorgaenger-Aenderungen aus REST und MCP gemeinsam: gleiches Projekt, keine Selbstbezuege/Zyklen und keine neuen transitiv redundanten Kanten, auch nicht an anderen Teilaufgaben. Pruefung und Schreiben laufen unter einer DB-Schreibsperre. Bestehende Alt-Redundanzen koennen schrittweise entfernt werden. Projektknoten `0` ist nur als alleiniger Vorgaenger erlaubt. UI-Auswahl und Netzplan verwenden dieselben Regeln.
- Interaktiver Netzplan mit `vis-network`.
- Teammitglieder pro Projekt mit `can_read`, `can_edit`, `can_create`.
- Aufgaben-/Teilaufgaben-Zuweisung und Notizen fuer Zugewiesene.
- Projektzuweisungen vererben Leserechte auf alle Teilaufgaben samt Notizen/Handoffs in REST, MCP und MCP-Suche. Eigene Notizen und Handoffs sind damit ebenfalls erlaubt, ohne zusaetzliche Teilaufgaben-Zuweisung. Fremde Inhalte bleiben vor Aenderungen durch normale Nutzer geschuetzt. Die REST-Teilaufgabenliste gewaehrt durch die Projektzuweisung allein keine Bearbeitungs-/Erstellungsrechte.
- WYSIWYG-Beschreibungen mit zentralem HTML-Sanitizer in `app_core.js`.
- Nextcloud/WebDAV-Dateiablage ueber `dashboard/webdav.py` und `api_nextcloud.py`.
- Alternativ lokale Dateiablage pro Aufgabe/Projekt unter `data/files/task-<ID>/`, gemeinsame Dateischnittstelle in `dashboard/file_storage.py`. Auswahl ueber `file_storage_type` (`local`, `webdav`, `none` in der API), bestehende `nextcloud_path`-Zuordnungen bleiben kompatibel. Lokale Dateien bei Backups einschliessen.
- Die Dateiablage wird im Header des Dateibrowsers konfiguriert. Beim expliziten Entfernen einer lokalen Ablage wird nach Bestaetigung auch `data/files/task-<ID>/` samt Inhalt geloescht. Beim Entfernen einer WebDAV-Zuordnung bleibt das Remote-Verzeichnis erhalten. Ein Wechsel der Ablageart und das Loeschen einer Aufgabe behalten lokale Dateien zur manuellen Wiederherstellung/Bereinigung bei. Datei-Schreibzugriffe brauchen Bearbeitungsrechte, ONLYOFFICE unterstuetzt beide Ablagearten.
- ONLYOFFICE/WOPI-Integration ueber `api_onlyoffice.py` und `/editor`.
- LDAP/Active Directory Login und Sync ueber `api_ldap.py`, `ldap_utils.py`, `ldap_sync.py`.
- Mail-Benachrichtigungen mit SMTP-Konfig, Templates und User-Prefs.
- Optionales TLS inkl. Zertifikatspfaden und Verify-Flags pro Integration.
- MCP-Server unter `/mcp/` mit FastMCP, Bearer-Token-Auth und Audit-Log.
- Admin-UI fuer Allgemein, Benutzer, LDAP, Nextcloud, ONLYOFFICE, Mail, TLS, MCP.
- i18n mit JSON-Dateien unter `dashboard/static/i18n/` fuer de/en/es/fr/ro/ru/uk.

## Import- und App-Pattern

- Services starten `dashboard/app.py` und `dashboard/admin_app.py` als Script, nicht als Modul.
- Beide Apps setzen `sys.path.insert(0, str(Path(__file__).parent.parent))`, damit `dashboard` als Package importierbar ist.
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
- HTML-Routen: `/login`, `/`, `/editor`, Catch-All `/{path:path}`.
- Mutierende `/api/`-Requests brauchen `X-Requested-With: XMLHttpRequest`, ausgenommen WOPI/ONLYOFFICE Callback.

### Admin-App `dashboard/admin_app.py`

- Bindet Admin-Router fuer Benutzer, LDAP, Nextcloud, ONLYOFFICE, Mail, App-Config, TLS und MCP ein.
- `/api/dashboard/restart` startet `tareas.service` und `tareas-admin.service` neu und ist nur fuer Admins.
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

- `dashboard/mcp_server.py` definiert FastMCP mit Tools fuer Projekte, Subtasks, Dependencies, Notes, Suche, Users, Areas, Selbstzuweisung und `whoami`.
- Auth laeuft per Bearer-Token ueber die Middleware `mcp_auth` in `dashboard/app.py`.
- MCP-Tokens werden nur als SHA-256-Hash in `mcp_tokens` gespeichert; Plain-Token ist nur beim Erstellen sichtbar.
- Jeder MCP-Token gehoert zu einem eigenen User mit `auth_source='mcp'`.
- Schreiboperationen sollen `audit_log.log_change(...)` verwenden.
- Der globale MCP-Kill-Switch liegt in `mcp_config.enabled`.

## Frontend-Konventionen

- Haupt-App zeigt die Aufgabenliste ohne Tab-Leiste in `dashboard/templates/index.html`. Der kompakte Header ist 44px hoch, der Titel `Tareas` verlinkt zur Aufgabenliste. Standardsortierung: angezeigte ID absteigend, inklusive positiver Teilaufgaben-IDs bei Pseudozeilen.
- Der Haupttabellenkopf bleibt beim Scrollen unter Header und Filterleiste angeheftet. `app_core.js` misst deren Hoehe per `ResizeObserver` und setzt `--task-table-header-top`, damit auch umgebrochene oder ausgeblendete Filterleisten beruecksichtigt werden.
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
