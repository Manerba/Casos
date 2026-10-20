# Casos

Casos ist ein selbst gehostetes Issue-System mit **FastAPI, SQLite und Vanilla JavaScript**. Alle aktiven angemeldeten Benutzer sehen dieselben Issues, chronologischen Updates und lokalen Anhänge. Die Oberfläche unterstützt Deutsch, Englisch, Spanisch, Französisch, Rumänisch, Russisch und Ukrainisch.

Quellcode: [GitHub – Manerba/Casos](https://github.com/Manerba/Casos) und [Gitea – mir/Casos](https://10.0.12.17:3000/mir/Casos) (im lokalen Netz). Beide Repositories sind öffentlich lesbar.

## Funktionen und Rechte

- Flache Issues mit stabiler ID, Markdown-Beschreibung, Priorität, optionaler Fälligkeit, Ersteller, Verantwortlichem und Status `offen`, `in_arbeit`, `erledigt` oder `abgebrochen`. Wiederöffnen ist möglich.
- Jeder aktive Benutzer darf Issues erstellen. Ersteller, Verantwortlicher, ausdrücklich freigegebene Bearbeiter und Admins dürfen Inhalte ändern, Updates schreiben und Dateien anhängen. Zuweisung, Bearbeitungsfreigaben und Issue-Löschung bleiben Ersteller/Admin vorbehalten. Sichtbarkeit allein gewährt keine Schreibrechte.
- Autoren dürfen eigene Updates mit aktuellen Beitragsrechten innerhalb von 300 Sekunden revisionsgesichert korrigieren. Admins dürfen auch später korrigieren und Updates löschen. Autor und Erstellzeit bleiben erhalten.
- Status- und Zuweisungsereignisse erscheinen zusammen mit Updates im Verlauf. Persönliche Mailpräferenzen steuern Zuweisungs-, Status-, Update- und Fristbenachrichtigungen. Ein neues Update informiert standardmäßig aktiven Ersteller und Verantwortlichen, ohne Akteur und Doppelzustellungen.
- Lokale, flache Anhänge bis **500 MiB pro Upload**. Gleichnamige Dateien bleiben getrennte Anhänge. Löschen dürfen Ersteller/Admin oder der Uploader mit aktuellen Beitragsrechten. Beim endgültigen Löschen eines Issues werden dessen Anhänge über eine dauerhafte Bereinigungswarteschlange entfernt.
- Lesevorschau für JPEG, PNG, GIF, WebP, BMP und Outlook-MSG. MSG zeigt Mailkopf, bereinigten Nachrichtentext und enthaltene Anhänge mit geschützten Downloads. Externe Mailbilder werden nicht automatisch geladen. Originaldateien bleiben herunterladbar.
- Volltextsuche in Issue-Titeln, Beschreibungen und Updates mit UND-Begriffen, `"genauen Phrasen"`, `wort*`, Typ-/Zeitfilter und Pagination. Anhänge werden nicht indexiert.
- Einstellungen über das globale Zahnrad: persönliche Optionen sowie für Admins Allgemein, Benutzer, LDAP, Mail, TLS und MCP einschließlich Tokens, Kill-Switch und Audit.
- Browser/REST und MCP verwenden dieselben aktuellen Rechte und Revisionsprüfungen. LDAP/AD, SMTP, optionales TLS und Hell-/Dunkeldarstellung bleiben verfügbar.

Vorschauen haben eigene Grenzen: 25 MiB Eingabe, 20 Millionen Bildpixel, maximal 10.000 Pixel je Bildseite und 4.096 Pixel Vorschaugröße. Animierte Bilder zeigen das erste Bild. SVG und andere nicht unterstützte Formate erhalten einen Download-Fallback. Die vollständigen MSG-/Worker-Limits stehen in [Betrieb und Wiederherstellung](docs/operations.md#vorschaugrenzen-und-abhängigkeiten).

## Lokaler Start

Voraussetzungen: Ubuntu 24.04 als geprüfte Entwicklungsplattform, Python ab 3.10 und SQLite mit FTS5/unicode61. Der Quellcode ist öffentlich auf GitHub verfügbar; ein öffentliches Paketrepository ist nicht eingerichtet.

```bash
cd /sdb1/nextcloud/data/mir/files/Dev/Casos
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python dashboard/app.py
```

Die Haupt-App läuft unter `http://localhost:8514/`. Eine frische Datenbank erzeugt `admin` mit Passwort `admin`; nach der ersten Anmeldung das Passwort in den persönlichen Einstellungen ändern. Für den getrennten MCP-Prozess in einem zweiten Terminal:

```bash
venv/bin/python dashboard/mcp_app.py
```

MCP ist unter `http://localhost:8516/mcp/` und weiterhin unter `http://localhost:8514/mcp/` verfügbar. Der getrennte Zugang stellt nur MCP, geschützte Anhangswege und tokenfreie Bootstrapinformationen bereit. Browseroberfläche und Einstellungen liegen auf Port 8514. Tokens werden im Einstellungsbereich MCP erstellt und nur einmal vollständig angezeigt. Einstieg: [Agenten-Guide](docs/casos-agent-guide.md), zur Laufzeit `/agent-guide.md` und `/.well-known/casos-agent.json`.

`CASOS_DATA_DIR` wählt eine isolierte Datenablage, `CASOS_HOST` die Bindadresse und `CASOS_PORT` den Port der Haupt-App und `CASOS_MCP_PORT` den getrennten MCP-Port. Beide Prozesse müssen dieselbe Datenablage verwenden. Standard ist `data/casos.db` mit Schema-Version 2, `data/secret.key` und `data/attachments/`. Vorhandene fremde oder unbekannte Datenbanken werden ohne Migration oder Löschung abgewiesen.

## Lokales Paket und Betrieb

```bash
./publish.sh --build /tmp/casos-artifacts
```

Der historische Scriptname bezeichnet jetzt ausschließlich einen lokalen Build. Das DEB bleibt im angegebenen Verzeichnis; ohne Zielangabe wird `dist/` verwendet. Es werden keine Dateien veröffentlicht und keine Dienste aktiviert. Buildwerkzeuge: `dpkg-deb` und `rsync`.

Eine spätere Installation durch den Betreiber erfolgt mit `sudo packaging/install.sh /absoluter/pfad/casos_VERSION_all.deb`. Sie installiert Python-Abhängigkeiten und startet Haupt-App, MCP sowie LDAP-/Mail-Timer. Voraussetzungen, Dienstdateien, Upgrades, Entfernung und vollständiges Backup/Restore sind in [docs/operations.md](docs/operations.md) beschrieben. Die Testläufe führen keine echte Systeminstallation aus.

## Entwicklung und Prüfung

```bash
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m playwright install chromium
venv/bin/python -m unittest discover -s tests -v
venv/bin/python tests/check_issues_ui.py
venv/bin/python tests/check_update_dialog_ui.py
venv/bin/python tests/check_settings_ui.py
venv/bin/python tests/check_search_ui.py
venv/bin/python tests/check_attachment_preview_ui.py
venv/bin/python tests/check_history_ui.py
venv/bin/python tests/check_backup_restore.py
```

Die Prüfharnesses verwenden temporäre Daten, Testidentitäten und Mail-Testtransporte. Backend-Ergebnisse, Browsernachweise und tatsächlich nicht ausgeführte Betriebsprüfungen müssen im jeweiligen Handoff angegeben werden. Entwicklungsregeln und Dateikarte stehen in [AGENTS.md](AGENTS.md).

## Herkunft und historische Unterlagen

Casos entstand als eigenständiger Tareas-Klon aus Commit `ca5d45d` (`0.0.1+143`). Die Update-Erfassung wurde gezielt aus Tareas `7157218` (`0.0.1+144`) übernommen und angepasst. Tareas bleibt eigenständig; seine Betriebsdaten wurden nicht übernommen. Es gibt keine Casos-Desktop-App.

Die früheren [Projektansichten](docs/Screenshot-Projekt.png), [Teilaufgabenansicht](docs/Screenshot-Projekt2.png) und [Netzplanansicht](docs/Screenshot-Netplan.png) sind ausschließlich **historische Tareas-Screenshots**. Frühere Changelogzeilen und ausdrücklich als historisch gekennzeichnete Review-/Desktopunterlagen dokumentieren diesen Ausgangsstand.

Casos-Quellcode steht unter [MIT](LICENSE). Bibliotheken und öffentliche Test-MSGs haben eigene Lizenzen; siehe [Abhängigkeitshinweise](packaging/DEPENDENCIES.md) und `tests/fixtures/msg/NOTICE.txt`.
