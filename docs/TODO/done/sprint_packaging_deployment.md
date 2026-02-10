# Sprint: APT-Packaging + Deployment

## Ziel

Tareas als `.deb`-Paket ueber ein APT-Repository auf 188.245.43.207 verteilen. Installation auf einem frischen Ubuntu 24.04-Server mit einem Einzeiler. Updates ueber `apt upgrade tareas`.

## Kontext Repo-Server (188.245.43.207)

- Ubuntu-Server, Apache2 mit Let's Encrypt (cloud2.hirschgasse5.de, klapp.hirschgasse5.de)
- Bestehendes KLAPP-Repo unter `/var/www/apt-repo/` (Struktur mit `dists/noble/`, `pool/main/`, GPG-signiert)
- Repo-Tool: `dpkg-scanpackages` (kein reprepro/aptly)
- GPG-Key vorhanden: RSA 4096, `C818D9020A2F43CEBCE2E7E0BA3D049F6600D868` (KLAPP Update Server)
- Das KLAPP-Repo hat aktuell keinen Apache-VHost/Alias konfiguriert - es ist nicht von aussen erreichbar
- SSH-Zugang: root@188.245.43.207 (SSH-Key hinterlegt, kein Passwort noetig)

## Entscheidungen

| Frage | Antwort |
|-------|---------|
| Installationspfad Zielserver | `/opt/tareas` |
| Service-User | Eigener System-User `tareas` |
| Repo-URL | `http://188.245.43.207/tareas/repo` |
| Repo-Tool | `dpkg-scanpackages` (wie KLAPP) |
| GPG-Signierung | Bestehenden KLAPP-GPG-Key mitnutzen (bereits auf Server vorhanden) |
| Paketarchitektur | `all` (Python, kein kompilierter Code) |
| Einzeiler | Bootstrap-Script: `curl -s http://188.245.43.207/tareas/install.sh \| bash` |

## Anforderungen

### 1. Paket-Struktur (`packaging/`)

Neues Verzeichnis `packaging/` im Projektroot mit allem, was zum Bauen des .deb-Pakets noetig ist.

**DEBIAN/control** - Paket-Metadaten:
- Package: tareas
- Version: Aus `version.txt` lesen
- Architecture: all
- Depends: python3 (>= 3.10), python3-venv, python3-pip
- Maintainer, Description

**DEBIAN/postinst** - Nach-Installations-Script (laeuft als root):
- System-User `tareas` erstellen (falls nicht vorhanden, nologin, home=/opt/tareas)
- Python-venv erstellen unter `/opt/tareas/venv` (falls nicht vorhanden)
- `pip install -r /opt/tareas/requirements.txt` im venv ausfuehren
- Verzeichnis `/opt/tareas/data` erstellen, Besitzer tareas:tareas
- Systemd-Services kopieren/aktivieren: `tareas.service` und `tareas-admin.service`
- Wenn LDAP-Sync-Timer vorhanden: ebenfalls aktivieren
- Services (neu)starten
- Dateiberechtigungen setzen: `/opt/tareas` gehoert tareas:tareas

**DEBIAN/prerm** - Vor-Deinstallations-Script:
- Services stoppen und deaktivieren

**DEBIAN/postrm** - Nach-Deinstallations-Script:
- Bei `purge`: Datenverzeichnis `/opt/tareas/data` loeschen, User `tareas` entfernen

**DEBIAN/conffiles** - Konfigurationsdateien die bei Update nicht ueberschrieben werden:
- `/opt/tareas/data/secret.key`
- `/opt/tareas/data/tareas.db`

### 2. Paket-Inhalt

Das .deb-Paket installiert alle Projektdateien nach `/opt/tareas/`:
- `dashboard/` (Python-Backend, Templates, Static, Komponenten)
- `scripts/` (Service-Dateien, Sync-Scripte)
- `requirements.txt`
- `version.txt`
- NICHT enthalten: `data/`, `.git/`, `venv/`, `packaging/`, `docs/`, `.claude/`, `__pycache__/`

### 3. Service-Dateien anpassen

Die bestehenden Service-Dateien (`tareas.service`, `tareas-admin.service`) muessen fuer das Paket angepasste Versionen bekommen:
- WorkingDirectory: `/opt/tareas`
- ExecStart: `/opt/tareas/venv/bin/python dashboard/app.py` (bzw. admin_app.py)
- User: tareas
- Group: tareas
- Diese angepassten Versionen liegen im Paket und werden vom postinst nach `/etc/systemd/system/` kopiert

### 4. Build-Script (`publish.sh`)

Script im Projektroot. Ablauf:

1. Version aus `version.txt` lesen
2. Temporaeres Build-Verzeichnis erstellen
3. DEBIAN/-Verzeichnis mit control, postinst, prerm, postrm, conffiles aufbauen (Version dynamisch einsetzen)
4. Projektdateien in die Paketstruktur kopieren (nach `opt/tareas/`)
5. `dpkg-deb --build` ausfuehren -> erzeugt `tareas_{version}_all.deb`
6. Passwortabfrage fuer Remote-Server (oder SSH-Key wie aktuell konfiguriert)
7. .deb-Paket per SCP auf den Repo-Server hochladen nach `/var/www/tareas/repo/pool/main/t/tareas/`
8. Per SSH auf dem Repo-Server:
   - `dpkg-scanpackages` ausfuehren
   - `Packages.gz` generieren
   - `Release`-Datei generieren
   - `Release.gpg` und `InRelease` mit GPG-Key signieren
9. Aufraeum-Meldung mit Erfolgsstatus

### 5. Apache-Konfiguration auf Repo-Server

Neuer Apache-Alias oder VHost-Eintrag damit das Repo unter `http://188.245.43.207/tareas/` erreichbar ist.

- Apache-Config-Datei: `/etc/apache2/conf-available/tareas-repo.conf`
- Alias `/tareas/repo` -> `/var/www/tareas/repo`
- Directory-Optionen: Indexes erlauben (damit APT browsen kann), FollowSymLinks
- Zusaetzlich: `/tareas/install.sh` -> Bootstrap-Script (statische Datei)
- Config aktivieren: `a2enconf tareas-repo && systemctl reload apache2`
- `publish.sh` erstellt diese Config beim ersten Aufruf automatisch (oder mit `--setup` Flag)

### 6. Repo-Verzeichnisstruktur auf dem Server

```
/var/www/tareas/
├── install.sh                          # Bootstrap-Script (Einzeiler-Ziel)
└── repo/
    ├── dists/
    │   └── noble/
    │       ├── main/
    │       │   └── binary-all/
    │       │       ├── Packages
    │       │       └── Packages.gz
    │       ├── Release
    │       ├── Release.gpg
    │       └── InRelease
    ├── pool/
    │   └── main/
    │       └── t/
    │           └── tareas/
    │               └── tareas_{version}_all.deb
    └── tareas-repo.gpg                 # Oeffentlicher GPG-Key zum Download
```

### 7. Bootstrap-Script (`install.sh`)

Wird auf dem Repo-Server unter `/var/www/tareas/install.sh` abgelegt. Inhalt:

- Pruefen ob als root ausgefuehrt
- Pruefen ob Ubuntu 24.04
- GPG-Key herunterladen und in `/etc/apt/keyrings/tareas-repo.gpg` ablegen
- APT-Quelle hinzufuegen: `/etc/apt/sources.list.d/tareas.list` mit Inhalt `deb [signed-by=/etc/apt/keyrings/tareas-repo.gpg] http://188.245.43.207/tareas/repo noble main`
- `apt update`
- `apt install -y tareas`
- Erfolgsmeldung mit URL-Hinweis (Port 8504 fuer App, Port 8505 fuer Admin)

Dieses Script wird von `publish.sh` beim Setup auf den Server hochgeladen und bei jeder Veroeffentlichung aktualisiert.

### 8. Update-Verhalten

Wenn `apt upgrade tareas` ausgefuehrt wird:
- APT ersetzt die Dateien unter `/opt/tareas/` (ausser conffiles)
- `postinst` laeuft erneut:
  - User existiert bereits -> wird uebersprungen
  - venv existiert bereits -> nur `pip install -r requirements.txt` (aktualisiert Dependencies)
  - DB existiert bereits -> `init_db()` fuehrt nur Migrationen aus (CREATE IF NOT EXISTS, ALTER TABLE)
  - Services werden neugestartet
- Datenbank und Secret-Key bleiben erhalten (conffiles/data-Verzeichnis)

## Reihenfolge

1. `packaging/`-Verzeichnis mit DEBIAN-Dateien erstellen
2. `publish.sh` erstellen (Build + Upload + Repo-Update)
3. `install.sh` (Bootstrap-Script) erstellen
4. Erstmaliges Setup auf Repo-Server: Apache-Config, Verzeichnisstruktur, GPG-Key
5. Erstes Paket bauen und veroeffentlichen
6. Auf einem frischen Ubuntu 24.04 testen: Einzeiler ausfuehren
7. Update testen: Version erhoehen, erneut publizieren, `apt upgrade` auf Zielserver

## Verifikation

- `publish.sh` baut .deb-Paket ohne Fehler
- `publish.sh` laedt Paket auf Repo-Server und aktualisiert Index
- `http://188.245.43.207/tareas/repo/dists/noble/Release` ist im Browser erreichbar
- `http://188.245.43.207/tareas/install.sh` ist im Browser erreichbar
- Auf frischem Ubuntu 24.04: `curl -s http://188.245.43.207/tareas/install.sh | bash` installiert Tareas
- Nach Installation: `systemctl status tareas.service` laeuft als User `tareas`
- App erreichbar unter `http://<zielserver>:8504/`
- Admin erreichbar unter `http://<zielserver>:8505/`
- Login mit admin/admin funktioniert
- Version erhoehen, erneut publizieren: `apt update && apt upgrade tareas` aktualisiert die Installation
- DB und Benutzer bleiben nach Update erhalten
- `apt remove tareas` stoppt Services
- `apt purge tareas` entfernt Daten

## Nicht-Ziele

- Kein HTTPS fuer das Repo (laeuft ueber IP, kein Zertifikat)
- Kein automatisches Update auf Zielsystemen (kein unattended-upgrades)
- Keine Multi-Architektur (nur `all`)
- Kein Changelog im .deb-Paket (kann spaeter hinzugefuegt werden)
- Kein separater GPG-Key fuer Tareas (nutzt den bestehenden KLAPP-Key)
