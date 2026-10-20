# Betrieb, Paketierung und Wiederherstellung

Diese Anleitung beschreibt den aktuellen Casos-Issue-Stand mit Schema-Version 2. Casos und das benachbarte Tareas sind getrennte Anwendungen. Die hier gezeigten Installations-, Dienst- und Restorebefehle sind bewusst auszuführende Betreiberaktionen; die Entwicklungsprüfungen aktivieren keine produktiven Dienste.

## Prozesse und Ablage

| Zweck | Dienst/Datei | Standard |
|---|---|---|
| Web, REST, Einstellungen und MCP | `casos.service`, `dashboard/app.py` | Port 8514 |
| Getrennter Agentenzugang | `casos-mcp.service`, `dashboard/mcp_app.py` | Port 8516 |
| LDAP-Abgleich | `casos-ldap-sync.timer` / `.service` | 5 Minuten nach Boot, danach alle 15 Minuten |
| Fristbenachrichtigungen | `casos-mail-scheduler.timer` / `.service` | täglich 00:01 lokale Systemzeit |
| Datenbank | `data/casos.db` | SQLite WAL, Foreign Keys, FTS5 |
| Schlüssel | `data/secret.key` | Cookie-Signatur und Fernet-Credentials, Modus 0600 |
| Anhangsdateien | `data/attachments/` | flach, interne Namen, keine Nutzerpfade |

Metadaten, Bearbeitungsfreigaben, Updates, Verlauf, Suchindex, Audit und Mailkonfiguration liegen in der Datenbank. `attachment_gc` enthält wiederholbare Lösch-/Abbruchbereinigungen. Haupt-App und MCP bearbeiten die Queue beim Start und periodisch; fehlgeschlagene Bereinigung wird erneut versucht. Eine Anhangsdatei ohne passenden Datensatz darf nicht durch Umbenennen als neuer Anhang eingebunden werden.

`CASOS_DATA_DIR` kann die komplette Datenablage verlegen. `CASOS_HOST` gilt für beide Prozesse; `CASOS_PORT` legt den Haupt-App-Port fest, `CASOS_MCP_PORT` den getrennten MCP-Port. Haupt-App, MCP und beide Scheduler müssen dieselbe Ablage verwenden. Bei einer systemd-Abweichung auch `ReadWritePaths` sowie Besitzer und Zugriffsrechte anpassen; eine Umgebungsvariable allein erweitert die Service-Schreibrechte nicht. Keine Tareas-Datenablage als Ziel verwenden.

Frische Initialisierung erzeugt `admin` / `admin`. Das Passwort nach der ersten Anmeldung ändern. Ein vorhandenes fremdes Schema wird abgewiesen und bleibt erhalten. Bei unterstützten Casos-Upgrades vor dem Start alle Daten gemeinsam sichern; der Schemawechsel ist kein Ersatz für ein Backup.

## Lokales Paket

Auf dem Buildrechner müssen `bash`, `dpkg-deb` und `rsync` verfügbar sein:

```bash
./publish.sh --build /tmp/casos-artifacts
```

Das Artefakt `casos_VERSION_all.deb` bleibt im Zielverzeichnis. Ohne Verzeichnisargument ist das Ziel `dist/`. Der Builder verwendet eine eigene temporäre Stagingablage, setzt Archivbesitzer auf root und normalisiert Verzeichnisse auf 0755 sowie Dateien auf 0644. Nur Debian-Hooks sind ausführbar. Das verhindert übernommene 0777-Modi aus dem gemeinsamen Entwicklungsdateisystem.

Enthalten sind aktive Dashboarddateien, die beiden Scheduler, die sechs Paketunits, Requirements, Version sowie README.Debian/Betriebs-/Agenten-/Lizenzhinweise. Nicht enthalten sind Runtime, Secrets, virtuelle Umgebung, Pythoncache, Testfixtures, Entwicklungspläne oder ein Admin-/Office-Dienst. Marked und sein Lizenztext bleiben Bestandteil des Frontends. Preview-Abhängigkeiten werden über pip installiert und behalten ihre eigenen Lizenzen.

`publish.sh` unterstützt ausschließlich `--build` und `--help`. Es richtet kein Remote oder APT-Repository ein und besitzt keinen automatischen Uploadpfad. Der Quellcode liegt öffentlich auf [GitHub](https://github.com/Manerba/Casos); DEB-Builds werden dadurch nicht automatisch veröffentlicht.

## Installation und Dienste

Die folgenden Befehle sind für einen Betreiber vorgesehen, der die Maschine tatsächlich installieren möchte:

```bash
sudo packaging/install.sh /absoluter/pfad/casos_VERSION_all.deb
```

Der Installer akzeptiert nur eine lokale DEB-Datei mit Paketname `casos` und ruft APT auf. APT kann Systemabhängigkeiten beziehen. `postinst` legt den Systembenutzer `casos`, die virtuelle Umgebung und eine private Datenablage unter `/opt/casos` an. Pythonabhängigkeiten werden anhand `requirements.txt` mit pip installiert; dafür muss eine passende Paketquelle oder ein vorbereiteter pip-Cache erreichbar sein. Das DEB ist kein vollständig offline gebündeltes Pythonpaket.

Anwendungsquellen und virtuelle Umgebung bleiben durch root verwaltet; nur die Runtimeablage gehört dem Dienstbenutzer. Die Installation aktiviert und startet Haupt-App, MCP sowie beide Timer. Änderungsmails werden nach Commit best-effort versendet; es gibt keine dauerhafte Outbox oder garantierte Wiederholung fehlgeschlagener Zustellungen. LDAP-/SMTP-Konfiguration erfolgt anschließend in der Haupt-App über das globale Zahnrad. In einer frischen Konfiguration kontaktieren die Scheduler keine eingerichteten LDAP-/SMTP-Ziele.

Für eine manuelle Installation zuerst eine virtuelle Umgebung samt Requirements erstellen. `scripts/` enthält Units für den Entwicklungscheckout; `packaging/services/` enthält Units für `/opt/casos` und Benutzer/Gruppe `casos`. Vor manuellem Kopieren Pfade und Dienstkonto an den Zielrechner anpassen. Die sechs Units vollständig installieren und die Timer statt ihrer One-Shot-Jobs aktivieren.

Die Units behalten `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, die Adressfamilienbegrenzung sowie Kernel-/ControlGroup-Schutz. Vorschautempdateien liegen im privaten Tempbereich und werden nach jedem Workeraufruf entfernt. Betriebsdiagnose erfolgt mit `journalctl -u casos -u casos-mcp`; vorhandenes Dateilogging kann je nach Verzeichnisrechten auf stderr/Journal zurückfallen. Der Neustartknopf prüft den systemctl-Aufruf ohne Passwortdialog und meldet bei fehlender Berechtigung HTTP 503/restart_failed mit übersetztem Hinweis; gespeicherte Einstellungen bleiben erhalten. Das Dienstkonto erhält dafür keine pauschalen sudo-/Polkitrechte. Ein Betreiber kann die Dienste direkt per systemctl neu starten.

Bei Paket-Upgrades stoppt `prerm upgrade` Timer und Schreibprozesse, behält Aktivierung, Daten und Unitdateien, und `postinst configure` installiert/aktiviert/startet den aktuellen Stand. `postrm upgrade` entfernt keine Dateien. Ein Upgrade benötigt eine funktionierende Installation der Pythonabhängigkeiten; nach einem fehlgeschlagenen Configure bleibt die Wiederaufnahme Betreiberaufgabe (`dpkg --configure -a` nach Behebung).

`apt remove casos` stoppt/deaktiviert die Units und entfernt deren installierte Dateien; `data/` einschließlich Secret und Anhängen bleibt erhalten. **`apt purge casos` löscht die Standardablage `/opt/casos/data`, die virtuelle Umgebung und das Dienstkonto.** Vor Purge sichern. Eine ausdrücklich extern konfigurierte Datenablage wird durch diesen Hook nicht automatisch gesucht oder gelöscht.

## Offline-Backup

Eine laufende Kopie nur der Datei `casos.db` reicht bei SQLite-WAL nicht aus. Außerdem müssen Datenbankmetadaten und Anhangsdateien denselben Zustand haben. Die einfache, nachvollziehbare Vorgehensweise ist eine gemeinsame Kopie bei gestoppten Schreibern.

Als Betreiber mit den erforderlichen Dateirechten zunächst beide Timer stoppen, danach Apps und eventuell laufende Schedulerjobs:

```bash
sudo systemctl stop casos-ldap-sync.timer casos-mail-scheduler.timer
sudo systemctl stop casos.service casos-mcp.service casos-ldap-sync.service casos-mail-scheduler.service
```

Auch manuell gestartete App-/Scheduler-/Wartungsprozesse müssen beendet sein. Prüfen, dass keine dieser Instanzen noch schreibt. Lockdateien im laufenden Betrieb nicht entfernen.

Im folgenden Beispiel gelten die Paketstandardpfade; die Befehle laufen in einer root-Shell:

```bash
umask 077
casos_app=/opt/casos
casos_backup=$(mktemp -d /var/backups/casos-XXXXXXXX)
cp -a -- "$casos_app/data" "$casos_backup/data"
cp -- "$casos_app/version.txt" "$casos_app/requirements.txt" "$casos_backup/"
sqlite3 "$casos_backup/data/casos.db" 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

Erwartet werden `ok` und keine Foreign-Key-Fehlerzeilen. Die **gesamte** Datenablage wird kopiert, einschließlich vorhandener `casos.db-wal`, `casos.db-shm`, `secret.key`, interner Anhangsnamen und Queuezustände. Eine eventuell nach Kopie durch SQLite bereinigte WAL-Datei im Backup ist unproblematisch, solange die Datenintegrität geprüft bleibt. Das Original wird nicht bearbeitet.

Zusätzlich den passenden Code-/DEB-Stand, betriebsspezifische Unit-/Umgebungskonfiguration und TLS-Zertifikat/-Schlüssel außerhalb von `data/` sichern. Backups enthalten private Inhalte, Passwort-/Tokenhashes und den Credentialschlüssel; Zugriff und Aufbewahrung entsprechend begrenzen. Ohne `secret.key` lassen sich gespeicherte Credentials nicht zuverlässig wiederverwenden.

Nach erfolgreicher Sicherung die vorher betriebenen Instanzen wieder starten:

```bash
sudo systemctl start casos.service casos-mcp.service
sudo systemctl start casos-ldap-sync.timer casos-mail-scheduler.timer
```

## Restore und Prüfung

1. Den zur Sicherung passenden Casos-Code-/Paketstand bereitstellen und die Zielprozesse stoppen. Ein älterer Code darf ein neueres Schema nicht überschreiben.
2. In eine **neue leere** Zielablage kopieren; nie eine vorhandene Runtime stillschweigend überschreiben. Beispielsweise `casos_restore=$(mktemp -d /opt/casos-restore-XXXXXXXX)` und `cp -a -- "$casos_backup/data" "$casos_restore/data"` in der Betreiber-Shell.
3. DB-Integrität und Foreign Keys wie oben prüfen. Besitzer an das Zielkonto anpassen, Datenverzeichnis auf 0700 und `secret.key` auf 0600 halten. Der gesicherte Schlüssel muss vor dem ersten Start vorliegen. TLS-Dateien und Pfade separat wiederherstellen.
4. Zunächst isoliert mit `CASOS_DATA_DIR` auf die neue Ablage, `CASOS_HOST=127.0.0.1` und zwei freien Testports starten. Mail-/LDAP-Testtransporte oder isolierte Konfiguration verwenden, damit ein Wiederherstellungstest keine realen Nachrichten/Abgleiche auslöst. Beide Apps müssen denselben Schlüssel und dieselbe Datenbank sehen.
5. Anmelden, Issue/Update/Verlauf und Suchtreffer prüfen; gleichnamige Anhänge über ihre unterschiedlichen IDs bytegenau herunterladen. Credentialentschlüsselung, bestehende Tokenrechte/Widerruf, Revisionen sowie neue Schreibvorgänge kontrollieren. Anhänge nicht anhand ihres sichtbaren Originalnamens zuordnen.
6. Erst nach erfolgreicher Prüfung den Betreiberstand übernehmen. Die bisherige Runtime unter einem neuen Sicherungsnamen aufbewahren oder die Units ausdrücklich auf die neue Datenablage umstellen. Bei abweichendem Pfad `ReadWritePaths` und alle vier Prozesse/Scheduler konsistent konfigurieren. Danach Haupt-App, MCP und die gewünschten Timer starten.

Ein transaktionales SQLite-Backup ist ebenfalls möglich; ohne gemeinsame Schreibpause löst es jedoch nicht die Konsistenz zwischen Datenbank und getrennten Anhangsdateien. Eine automatisierte Online-Sicherung wird hier nicht behauptet.

## Vorschaugrenzen und Abhängigkeiten

Das Uploadlimit bleibt unabhängig von der Vorschau **500 MiB**. Originaldownloads funktionieren auch bei abgewiesener Vorschau. Alle Bild-/MSG-/enthaltenen Downloadwege prüfen die aktuelle Identität und Originalzuordnung; temporäre Extraktionen werden nicht als neue Issue-Anhänge gespeichert.

| Grenze | Wert |
|---|---|
| Vorschaueingabe | 25 MiB |
| Rasterbild | JPEG, PNG, GIF, WebP, BMP; maximal 20.000.000 Pixel und 10.000 Pixel je Seite |
| Neucodierte Bildvorschau | höchstens 4.096 Pixel je Seite und 16 MiB |
| Animation | nur erstes Frame, sichtbarer Hinweis |
| MSG-Anhänge | höchstens 100, pro enthaltenem Download höchstens 20 MiB |
| MSG-Streams/Extraktionssumme | höchstens 50 MiB |
| Nachrichtentext | höchstens 1 MiB |
| Einzelnes Kopffeld | höchstens 8.192 Zeichen |
| OLE-Struktur | höchstens 4.096 Einträge und 16 Pfadebenen |
| Rekursive MSG-Vorschau | keine; unterstützter begrenzter MSG-Export als Download |
| Worker | 10 Sekunden Wandzeit, 5 Sekunden CPU, 512 MiB Adressraum, 32 offene Dateien, 32 MiB Ausgabedatei, keine Coredumps |
| Parallele Worker | 2 je App-Prozess, bei Haupt-App plus MCP zusammen höchstens 4 |

SVG, TIFF und unbekannte Formate werden nicht aktiv als Vorschau eingebettet. Beschädigte/zu große/unsupported Nachrichten liefern einen erklärten Zustand mit Originaldownload. HTML wird serverseitig bereinigt; aktive Inhalte und externe Ressourcen werden entfernt. Eindeutig zuordenbare CID-Rasterbilder nutzen geschützte Anhangswege. Die Ressourcenbegrenzung ist keine vollständige Betriebssystem-Sandbox.

Versionen/Lizenzen: extract-msg 0.56.1 (GPL-3.0-or-later), Pillow 12.3.0 (MIT-CMU mit eigenen Komponentenhinweisen) und striprtf 0.0.33 (BSD-3-Clause). Einzelheiten, Herkunft und Lizenztexte stehen in [packaging/DEPENDENCIES.md](../packaging/DEPENDENCIES.md). Im installierten Paket liegen sie zusammen mit dieser Anleitung unter `/usr/share/doc/casos/`.

## Aussagekraft der Prüfungen

`tests/test_operations.py` prüft Shellsyntax, echten lokalen DEB-Build, Archivinhalt/-modi, vollständige Units sowie Configure-/Upgrade-/Remove-/Purgeabläufe in einer temporären Zielwurzel. `CASOS_PACKAGE_ROOT` ist ausschließlich dafür vorgesehen; fehlt einer der lokalen Stubs unter `.casos-hook-stubs`, bricht der Hook vor Systemaktionen ab. In diesem Modus werden Account-, systemd-, Venv- und pip-Kommandos ausschließlich an diese Stubs übergeben. Die Prüfung führt keine echte Rootinstallation, Paketquelleninstallation, Benutzeranlage oder Dienstaktivierung aus.

`tests/check_backup_restore.py` verwendet dagegen echte getrennte lokale App-/MCP-Prozesse und temporäre Testdaten für Sicherung/Wiederherstellung einschließlich Secret, Anhängen, Suche, Revisionen und Testcredentials. Browserprüfungen, Backendtests und dieser Restorecheck ergänzen die Paketprüfung. Erfolgreiche Stub-Hooks sind kein Nachweis einer ausgeführten Installation auf einem frischen Ubuntu-Rechner; nicht ausgeführte Systemprüfungen bleiben in der Übergabe ausdrücklich benannt.
