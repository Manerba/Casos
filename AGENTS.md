# Casos - Agenten-Kontext

Stand: 20.10.2026. Schlankes Issue-System gemäß Tareas-Projekt #77. Die verbindlichen Anforderungen und Zuständigkeiten stehen in `docs/project77-spec.json`. Die unabhängige PL-Abnahme in Subtask #401 ist für Version `0.0.1+151`, Commit `e039c3963728f0a269b1f98bb1d7f983f2ff735d`, abgeschlossen.

## Arbeitsbereich und Schutzregeln

- Änderungen ausschließlich in `/sdb1/nextcloud/data/mir/files/Dev/Casos`. `../Tareas` ist eine unabhängige lesbare Referenz; dessen Code, Runtime-Daten, Benutzer und Secrets nicht verändern oder übernehmen.
- Vor Änderungen Gitstatus und tatsächlich vorhandene Daten prüfen. Fremde Änderungen und Runtime-Daten bewahren. Unbekannte Datenbanken nicht stillschweigend migrieren, initialisieren oder löschen.
- Öffentliches Quellcode-Repository: `https://github.com/Manerba/Casos`, lokales Remote `origin`. Veröffentlichung am 20.10.2026 ausdrücklich beauftragt. Produktive Dienste sind nicht installiert/aktiviert; Paketveröffentlichungen und produktive Dienstaktionen sind kein stillschweigender Teil von Entwicklungsaufträgen. Lokale isolierte Testinstanzen sind erlaubt.
- `data/`, `venv/` und `clients/` bleiben durch `.gitignore` ausgeschlossen. Keine Tokens, Credentials, Benutzerdateien oder Datenbankkopien committen. Es gibt keine Casos-Desktop-App; mögliche künftige Clients erhalten eigene Repositories/Anweisungen.
- Parallel arbeitende Agenten nutzen getrennte Worktrees oder exklusiv vereinbarte Dateien. Zentrale Dateien und Versionscommits werden koordiniert; Erfolgsmeldungen ersetzen keine tatsächliche Gegenprüfung.
- Sprache: Deutsch bevorzugt. Betriebssystem: Ubuntu 24.04 Server, Bash. Der Entwickler verbindet sich von Windows 11 per SSH/SMB.

## Architektur

| Bereich | Aktueller Stand |
|---|---|
| Backend | Python ab 3.10, FastAPI, Uvicorn |
| Frontend | Vanilla JS, CSS Custom Properties, sieben Sprachen |
| Datenbank | SQLite, WAL, Foreign Keys, FTS5/unicode61, Schema 2 |
| Runtime | `data/casos.db`, `data/secret.key`, `data/attachments/` |
| Haupt-App | `dashboard/app.py`, Port 8514, Cookie `casos_session` |
| MCP | `dashboard/mcp_app.py`, Port 8516; derselbe MCP-Endpunkt auch auf 8514 |
| Einstellungen | Native Overlay-Dialoge in der Haupt-App; persönliche Optionen und Adminbereiche |
| Schutz | Aktuelle Session-/Tokenrechte, CSRF, CSP/Sanitizer, Revisionen, Audit, Tokenwiderruf/Kill-Switch |

Beide Apps starten als Script und setzen den Packagepfad selbst. In App-/Routercode absolute Imports `from dashboard...` verwenden. `CASOS_DATA_DIR` isoliert die Ablage; `CASOS_HOST`, `CASOS_PORT` (Haupt-App) und `CASOS_MCP_PORT` (MCP) konfigurieren Testinstanzen. Beide echten Prozesse müssen dieselbe Ablage verwenden.

## Fachmodell und Rechte

`issues` speichert Titel, Markdown-Beschreibung, Priorität, optionale Fälligkeit, Ersteller, Verantwortlichen und Status `offen`, `in_arbeit`, `erledigt`, `abgebrochen`. Wiederöffnen ist möglich. `issue_editors` speichert zusätzliche Bearbeiter. `issue_updates` enthält chronologische Markdownbeiträge; `issue_events` den fachlichen Verlauf. `attachments` enthält Originalname/Typ/Größe/Uploader und intern erzeugten Speichernamen; `attachment_gc` hält wiederholbare Bereinigungsaufträge. Weitere Tabellen betreffen Nutzer/Sessions, LDAP/SMTP/TLS/App/MCP, Audit, Mailpräferenzen/-templates und den abgeleiteten Suchindex.

Alle aktiven angemeldeten Benutzer einschließlich MCP-Identitäten dürfen alle Issues/Updates/Anhänge lesen und Issues erstellen. Ersteller, Verantwortlicher, Admin und ausdrücklich freigegebene Bearbeiter dürfen Inhalt/Status ändern, Updates hinzufügen und Dateien anhängen. Zuweisung, Bearbeitungsfreigaben und Issue-Löschung bleiben Ersteller/Admin vorbehalten. Sichtbarkeit allein gewährt keine Schreibrechte.

Autoren dürfen eigene Updates nur mit aktuellen Beitragsrechten und `0 <= Alter < 300` Sekunden korrigieren; Admins auch später. Revision ist erforderlich, Autor und Erstellzeit bleiben erhalten. Update-Löschung bleibt Admins vorbehalten. Anhänge löschen dürfen Ersteller/Admin sowie ihr Uploader mit aktuellen Beitragsrechten. Jeder Download und jeder Vorschau-/MSG-Anhangsweg prüft aktuelle Authentifizierung.

Projekt-/Subtask-/Abhängigkeits-/Netzplan-/Fortschritts-/Bereichslogik, persönliche Notizen, WebDAV/Nextcloud, Office/WOPI, Dateiänderung und die separate Admin-App sind entfernt. Gemeinsamer MarkdownEditor und UpdateDialog bleiben aktive Bestandteile.

## Dateikarte und Schnittstellen

| Dateien | Verantwortung |
|---|---|
| `database.py`, `issue_schema.sql`, `db_utils.py` | Schema, Startup-Lock, sichere Transaktionen und Identifier |
| `issue_service.py`, `issue_permissions.py`, `api_issues.py` | Gemeinsame Regeln, Rechte, Issues, Grants, Beschreibungsrevisionen |
| `update_service.py`, `api_updates.py` | Erstellung/Korrektur/Löschung; Quelle Tareas `7157218` angepasst |
| `attachment_service.py`, `api_attachments.py` | Flache unveränderliche Anhänge, Streaming, sichere Dateizugriffe, GC |
| `attachment_preview.py`, `preview_worker.py`, `api_attachment_preview.py` | Begrenzte Lesevorschau und geschützte MSG-Anhänge |
| `search_service.py`, `api_search.py` | Gemeinsamer FTS5-Korpus, sichere Snippets und Filter |
| `issue_history_service.py`, `api_issue_history.py`, `mail_service.py`, `api_mail.py` | Atomarer Verlauf, Mailversand nach Commit und Präferenzen |
| `auth.py`, `api_auth.py`, `crypto_utils.py`, `config_utils.py` | Sessions/Tokens, Login, Credentialverschlüsselung und Masking |
| `api_admin.py`, `api_app.py`, `api_ldap.py`, `api_tls.py`, `api_admin_mcp.py` | Geschützte Konfiguration in der Haupt-App |
| `mcp_server.py`, `mcp_transport.py`, `mcp_errors.py`, `agent_guide.py` | 22 aktuelle Werkzeuge, HTTP-Transport, strukturierte Fehler, Bootstrap |
| `app_core.js`, `tab_issues.js` | Theme, globale Helpers, SPA-Navigation, Issueabläufe |
| `markdown_editor.js`, `update_dialog.js`, `vendor/marked.umd.js` | Markdown mit Sanitizer, Revisionen und Entwurfserhalt |
| `issue_search.js`, `issue_history.js`, `attachment_preview.js` | Such-/Verlauf-/Vorschauansichten |
| `settings_overlay.js`, `tab_allgemein/benutzer/ldap/mail/tls/mcp.js` | Persönliche und administrative Einstellungen |

Browserrouten: `/login`, `/`, `/issues/{id}` sowie direkte Updates über `?update={id}`. Einstellungen öffnen über `/?settings=mcp` oder das globale Zahnrad. Entfernte Routen liefern 404 und fallen nicht in einen allgemeinen SPA-Catch-All.

REST beginnt mit `/api/issues`; Updates, Anhänge und Verlauf hängen am Issue. Suche: `GET /api/search`. MCP-Werkzeuge verwenden `issue.*`, `update.*`, `attachment.*`, `search`, `whoami`, `get_agent_guide` und `users.list`. Schema, konkrete Antworten und Beispiele stehen im aktuellen Agenten-Guide. Schreibregeln gehören in gemeinsame Services, damit REST/MCP dieselbe Semantik haben.

## Sicherheits- und Datenregeln

- Mutierende `/api/`-Requests benötigen `X-Requested-With: XMLHttpRequest`. MCP-REST-Anhangswege behalten diesen Schutz. Ein expliziter Bearer hat Vorrang vor Browsercookies; Port 8516 akzeptiert dort ausschließlich MCP-Bearer.
- Rechte aus der aktuellen DB prüfen, auch nach langen Uploads/Parserläufen. Bestehende MCP-Transportsessions dürfen keine überholte Rolle oder widerrufene Tokenidentität konservieren.
- MCP-Tokens nur als SHA-256-Hash speichern; Plaintext nur einmal bei Erstellung zeigen. Globaler Kill-Switch bleibt wirksam. MCP-Identitäten melden sich nicht per Passwort an.
- Beschreibungs-, Update- und Bearbeiterrevisionen verhindern verlorene konkurrierende Änderungen. Fehler lassen lokale Entwürfe und Basisrevision erhalten. Keine Entwürfe in URLs/localStorage übertragen.
- Stored HTML ausschließlich über zentralen Sanitizer; Mail-HTML bereits serverseitig eng bereinigen. Externe Vorschauressourcen nicht automatisch laden. Keine Inline-Datei-Editorfunktionen wieder einführen.
- Uploadlimit 500 MiB streamend; sichere interne Speichernamen statt Nutzerpfade. Symlinks/Hardlinks und falsche Issuezuordnung abweisen. Dateisystemcleanup über dauerhafte Queue und Locks; Locks im laufenden Betrieb nicht löschen.
- LDAP-/SMTP-Secrets mit Fernet schützen, APIs maskieren, Audit/Fehler ohne Inhalte und Secrets. `normalize_reason` vor Mutationen anwenden. Dynamische SQL-Identifier nur über Whitelists; Transaktionen und Foreign Keys erhalten.
- SMTP-/LDAP-TLS-Verify sowie HTTPS-Konfiguration und systemd-Härtung erhalten. Produktive Mails/AD-Zugriffe in Tests durch Testtransporte ersetzen.
- Vor Migration Backup; Schema 2 wird atomar initialisiert, unbekannte/ältere fremde Tabellen nicht verworfen. DB, Secret und Anhänge gemeinsam sichern. Details: `docs/operations.md`.

## Suche, Verlauf und Vorschau

Suche indexiert nur Issue-Titel/Beschreibung und Updateinhalt. Ein BM25-Korpus unterstützt UND, Phrasen und Wortpräfixe. `since` ist inklusive auf `updated_at`, verlangt eine Zone und maximal sechs Nachkommastellen. Quellen ohne Zone sind UTC; Normalisierung und Sortierung bewahren Mikrosekunden. Sichere plain/escaped Snippets, Filter vor Pagination, gemeinsame Lesesnapshotgrenzen und Quelltrigger erhalten. `rebuild_search_index(db)` ist der transaktionale Wartungseinstieg.

Verlauf und Updatezeitstempel unterstützen UTC-Mikrosekunden; gleiche Reihenfolge in REST/MCP/Browser. Mailversand erfolgt nach Commit best-effort, ohne dauerhafte Outbox oder garantierte Wiederholung. Mailfehler dürfen gespeicherte Inhalte nicht verlieren; fehlgeschlagene Mutationen erzeugen keine Benachrichtigung. Standardempfänger: aktiver Ersteller und Verantwortlicher ohne Akteur/Duplikate. Fristmails ignorieren terminale Issues und respektieren persönliche Präferenzen.

Vorschauen laufen in zeit-/speicherbegrenzten Unterprozessen. Grenzen und Lizenzen in `docs/operations.md` und `packaging/DEPENDENCIES.md` dokumentieren und bei Änderungen mit Tests abgleichen. SVG ist Download-Fallback; animierte Rasterbilder zeigen das erste Frame, verschachtelte MSGs werden nicht rekursiv angezeigt. Geschützte Downloads bleiben verfügbar.

## Frontend und Übersetzungen

DOM-Nutzertexte escapen oder `textContent` verwenden. `showNotification(message, type)` unterstützt info/success/error. Gemeinsame Dialoge dürfen keine fremden Entwürfe zerstören; native Dialogstapel, Escape/Abbrechen, Fokus-Rückgabe und beforeunload beachten. Änderungen während eines Requests bis zur vollständigen Antwortverarbeitung sperren.

Neue/veränderte UI-Keys in allen JSON-Dateien unter `dashboard/static/i18n/` pflegen: de/en/es/fr/ro/ru/uk. Dynamisch zusammengesetzte Keys bei Bereinigungen mitprüfen. Such-/Verlaufmodule verwenden Issue-Renderereignisse; bestehende Zustände und Schnittstellen vor Integration lesen. Keine alten Tab-/Komponenten-APIs voraussetzen.

## Prüfung und Betrieb

Backend: `venv/bin/python -m unittest discover -s tests -v`. Browserharnesses `tests/check_*_ui.py` verwenden Playwright/Chromium und isolierte HTTP-Apps. `tests/check_backup_restore.py` prüft einen vollständigen Offline-Restore über getrennte App-/MCP-Prozesse. `tests/test_operations.py` baut ein lokales DEB und prüft Hooks mit Stubsystembefehlen; dies ist keine echte Installation oder systemd-Aktivierung. Nicht ausgeführte Prüfungen ausdrücklich benennen.

Lokale Units in `scripts/`, Paketunits unter `packaging/services/` für `/opt/casos` und Benutzer `casos`. Haupt-/MCP-Dienste: `casos.service`, `casos-mcp.service`. Scheduler: LDAP alle 15 Minuten nach Startverzögerung, Mail täglich 00:01. Keine zusätzliche Admin-Dienstinstanz. `publish.sh --build [Zielverzeichnis]` baut ausschließlich lokal; das Artefakt bleibt erhalten. `packaging/install.sh` verlangt eine lokale DEB-Datei und aktiviert erst bei tatsächlicher Betreiberinstallation Dienste.

Historische Changelogzeilen, Screenshots und ausdrücklich markierte Altreviews dokumentieren Tareas. Aktive Dokumentation muss den tatsächlichen Casos-Stand beschreiben. Projektbelege und negative Entfernungstests dürfen historische Begriffe enthalten.

## Versionierung, Changelog und Commit

**Ausschließlich `./git-commit.sh "Kurze Beschreibung"` verwenden.** Das Script erhöht die Buildnummer in `version.txt`, staged sämtliche Änderungen mit `git add -A`, erstellt den Versionscommit und pusht nur bei konfiguriertem Remote. Ohne Remote bleibt der Commit lokal. Unteragenten lösen keine unkoordinierten Commits aus.

Vor jedem Versionscommit und damit auch vor einem Push `docs/changelog.md` ergänzen. Format: `DD.MM.YYYY HH:MM;Version;Kategorie;Beschreibung`. Kategorien konsistent halten: Feature, Aenderung, Bugfix, Security, Docs, Refactoring, Infra. Vor zentralem Commit Schreibstände aller Agenten einfrieren und Änderungen prüfen; das Script staged auch fremde uncommittete Dateien.
