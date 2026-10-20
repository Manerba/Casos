# Casos - Projektkontext

Casos ist ein selbst gehostetes, flaches Issue-System mit FastAPI, SQLite und Vanilla JS. Verbindliche Entwicklungs-, Sicherheits- und Commitregeln sowie die aktuelle Dateikarte stehen in [AGENTS.md](AGENTS.md); Bedienung und Betrieb in [README.md](README.md) und [docs/operations.md](docs/operations.md).

Arbeitsverzeichnis: `/sdb1/nextcloud/data/mir/files/Dev/Casos`. Das benachbarte Tareas bleibt eigenständig und unverändert. Vorhandene Änderungen und Daten bewahren. Keine produktiven Dienstaktionen, Veröffentlichung oder Remoteeinrichtung als stillschweigender Teil eines Entwicklungsauftrags. Tests verwenden isolierte Daten und Mail-Testtransporte.

Haupt-App und Einstellungen laufen auf Port 8514, der getrennte MCP-Zugang auf 8516. Beide Prozesse teilen `data/casos.db` (Schema 2), `data/secret.key` und `data/attachments/`; `CASOS_DATA_DIR` ermöglicht isolierte Testablagen. Alle aktiven Benutzer lesen alle Issues, Updates und Anhänge; gemeinsame Services prüfen die differenzierten Schreibrechte und aktuellen Token-/Sessionrechte.

Aktiv bleiben Markdownbeschreibungen, chronologische Updates, fachlicher Verlauf, lokale Anhänge mit Bild-/MSG-Lesevorschau, FTS-Suche, LDAP/SMTP/TLS, MCP und Einstellungen im globalen Overlay. Es gibt keine Projektplanung, Dateibearbeitung, separate Admin-App oder Casos-Desktop-App.

Backendprüfung: `venv/bin/python -m unittest discover -s tests -v`. Weitere Browser-, Paket- und Wiederherstellungsprüfungen sind in AGENTS/README dokumentiert. Ergebnisse und nicht ausgeführte Prüfungen wahrheitsgemäß festhalten. Die unabhängige PL-Abnahme in Subtask #401 ist für `0.0.1+151` / `e039c3963728f0a269b1f98bb1d7f983f2ff735d` abgeschlossen.

Commits ausschließlich mit `./git-commit.sh "Kurze Beschreibung"`. Vorher `docs/changelog.md` im Format `DD.MM.YYYY HH:MM;Version;Kategorie;Beschreibung` pflegen. Das Script staged alle Änderungen; parallele Agenten dürfen nicht unkoordiniert committen. Öffentliches Remote `origin`: `https://github.com/Manerba/Casos`.

Sprache: Deutsch bevorzugt. Entwicklung auf Ubuntu 24.04/Bash, Zugriff vom Windows-PC per SSH/SMB. `clients/` bleibt ausgeschlossen; künftige Clients benötigen eigene Repositories und Anweisungen.
