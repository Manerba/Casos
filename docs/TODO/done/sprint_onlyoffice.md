# Sprint: ONLYOFFICE-Integration

## Ziel

Office-Dokumente (docx, xlsx, pptx und Textdateien) direkt in Casos im Browser bearbeiten. ONLYOFFICE Document Server laeuft als Docker-Container auf dem Casos-Zielserver. Casos implementiert einen WOPI-Host, sodass Dokumente aus der Nextcloud-Dateiablage in einem Fullscreen-Overlay-Editor geoeffnet werden koennen.

## Kontext

- Nextcloud-Dateiablage ist bereits implementiert (WebDAV-Proxy, Baumansicht, Icon-Grid)
- Dateien liegen auf Nextcloud, Casos greift via WebDAV darauf zu
- ONLYOFFICE Document Server muss als Docker-Container aufgesetzt werden
- WOPI (Web Application Open Platform Interface) ist das Protokoll zwischen Editor und Host

## Entscheidungen

| Frage | Antwort |
|-------|---------|
| Office-Suite | ONLYOFFICE Docs Community Edition (AGPL v3) |
| Deployment | Docker-Container auf dem Casos-Zielserver |
| Editor-UI | Fullscreen-Overlay (wie Netzplan) |
| Protokoll | WOPI zwischen Casos (Host) und ONLYOFFICE (Client) |
| Unterstuetzte Formate | docx, xlsx, pptx, odt, ods, odp, txt, csv, md |

## WOPI-Protokoll Grundlagen

ONLYOFFICE laedt Dokumente ueber WOPI-Endpoints vom Host (Casos). Der Ablauf:

1. Benutzer klickt auf eine Datei in der Dateiablage
2. Casos generiert einen WOPI-File-Identifier und ein zeitlich begrenztes Access-Token
3. Casos oeffnet ein Fullscreen-Overlay mit einem iframe
4. Die iframe-URL zeigt auf ONLYOFFICE Document Server mit WOPI-Source-URL als Parameter
5. ONLYOFFICE ruft die WOPI-Endpoints von Casos auf, um die Datei zu laden
6. Benutzer bearbeitet das Dokument
7. Beim Speichern ruft ONLYOFFICE den PutFile-Endpoint auf
8. Casos schreibt die Datei via WebDAV zurueck nach Nextcloud

## Anforderungen

### 1. ONLYOFFICE Document Server Setup

- Docker-Image: `onlyoffice/documentserver` (Community Edition)
- Container-Konfiguration:
  - Port: 8090 (oder anderer freier Port, intern 80)
  - Persistentes Volume fuer Logs und Caches
  - JWT-Secret konfigurieren (Authentifizierung zwischen Casos und ONLYOFFICE)
  - WOPI aktivieren (`WOPI_ENABLED=true`)
- Systemd-Service oder Docker-Compose fuer automatischen Start
- Im `.deb`-Paket: Docker als Dependency deklarieren, postinst startet den Container
- ONLYOFFICE muss vom Browser des Benutzers erreichbar sein (nicht nur lokal)

### 2. Datenbank

- `nextcloud_config`-Tabelle erweitern (oder neue Tabelle `onlyoffice_config`):
  - onlyoffice_url TEXT (URL des Document Servers, z.B. `http://localhost:8090`)
  - onlyoffice_secret TEXT (JWT-Secret fuer Token-Signierung, Shared Secret mit dem Container)
- Neue Tabelle `wopi_tokens`:
  - id INTEGER PRIMARY KEY
  - token TEXT NOT NULL UNIQUE
  - user_id INTEGER NOT NULL (FK users)
  - task_id INTEGER NOT NULL (FK tasks)
  - file_path TEXT NOT NULL (relativer Pfad zur Datei im Projektverzeichnis)
  - permissions TEXT DEFAULT 'edit' (edit oder view)
  - created_at TEXT DEFAULT (datetime('now'))
  - expires_at TEXT NOT NULL
  - Token-Ablauf: 8 Stunden (Dokument muss vorher gespeichert werden)

### 3. WOPI-Host Endpoints

Casos muss folgende WOPI-Endpoints implementieren, die vom ONLYOFFICE Document Server aufgerufen werden:

**CheckFileInfo** - `GET /api/wopi/files/{file_id}`
- Liefert Metadaten ueber die Datei
- Pflichtfelder in der Antwort: BaseFileName, Size, UserId, UserFriendlyName, UserCanWrite, SHA256
- `file_id` ist ein Base64-kodierter String aus task_id + file_path
- Access-Token als Query-Parameter `access_token`

**GetFile** - `GET /api/wopi/files/{file_id}/contents`
- Liefert den Dateiinhalt als Binary-Stream
- Casos laedt die Datei via WebDAV von Nextcloud und streamt sie an ONLYOFFICE
- Access-Token Validierung

**PutFile** - `POST /api/wopi/files/{file_id}/contents`
- Empfaengt den geaenderten Dateiinhalt von ONLYOFFICE
- Casos schreibt die Datei via WebDAV zurueck nach Nextcloud
- Access-Token Validierung

**Lock/Unlock/RefreshLock** (optional, aber empfohlen):
- `POST /api/wopi/files/{file_id}` mit X-WOPI-Override Header
- Verhindert gleichzeitige Bearbeitung
- Lock-Info in DB speichern (neue Tabelle oder Spalte in wopi_tokens)
- Timeout: 30 Minuten, wird bei Aktivitaet verlaengert

Alle WOPI-Endpoints muessen:
- Das Access-Token aus dem Query-Parameter `access_token` validieren
- Bei ungueltigem/abgelaufenem Token: 401 zurueckgeben
- Den JWT-Header von ONLYOFFICE verifizieren (mit dem Shared Secret)

### 4. Token-Management

- Beim Oeffnen einer Datei: Casos generiert ein kurzlebiges WOPI-Token
  - Token enthaelt: user_id, task_id, file_path, permissions, expiry
  - Token wird in der DB gespeichert (wopi_tokens-Tabelle)
  - Token wird signiert (HMAC mit dem ONLYOFFICE JWT-Secret oder eigenem Secret)
- ONLYOFFICE sendet dieses Token bei jedem WOPI-Request als Query-Parameter
- Abgelaufene Tokens: Cronjob oder Cleanup bei jedem Request (alte Tokens loeschen)

### 5. API-Endpoint: Editor oeffnen

- `GET /api/tasks/{id}/files/edit?path=` - Gibt die Daten zurueck, die das Frontend braucht um den Editor zu oeffnen:
  - `editor_url`: URL des ONLYOFFICE Document Servers
  - `file_id`: Base64-kodierter WOPI-File-Identifier
  - `access_token`: Generiertes WOPI-Token
  - `access_token_ttl`: Token-Ablaufzeit als Timestamp
  - `document_type`: "word", "cell" oder "slide" (basierend auf Dateiendung)
  - `file_name`: Dateiname
  - `file_type`: Dateiendung (docx, xlsx, etc.)
  - `can_edit`: Boolean (basierend auf Benutzerrechten)

### 6. Frontend: Editor-Overlay

- Klick auf eine unterstuetzte Datei in der Dateiablage (oder Kontextmenue "Bearbeiten") oeffnet Fullscreen-Overlay
- Overlay-Struktur:
  - Header-Leiste: Dateiname, Schliessen-Button (X)
  - Hauptbereich: iframe mit ONLYOFFICE-Editor (fuellt gesamten Platz)
- ONLYOFFICE wird ueber die Document Server API initialisiert:
  - JS-API des Document Servers einbinden (`/web-apps/apps/api/documents/api.js`)
  - `new DocsAPI.DocEditor(containerId, config)` mit:
    - `document.url`: WOPI-Source-URL (`{casos_url}/api/wopi/files/{file_id}/contents?access_token={token}`)
    - `document.fileType`: Dateiendung
    - `document.title`: Dateiname
    - `editorConfig.callbackUrl`: URL die ONLYOFFICE nach dem Speichern aufruft
    - `editorConfig.user`: Aktueller Benutzer (id, name)
    - `token`: JWT-signierter Config-Block (mit dem Shared Secret)
- Beim Schliessen des Overlays: Editor-Instanz zerstoeren, ggf. Auto-Save ausloesen

### 7. Unterstuetzte Dateiformate

Mapping Dateiendung -> Editor-Typ:
- **Text/Word**: docx, doc, odt, txt, rtf, md, html -> documentType: "word"
- **Tabelle**: xlsx, xls, ods, csv -> documentType: "cell"
- **Praesentation**: pptx, ppt, odp -> documentType: "slide"
- Nicht unterstuetzte Dateien: "Bearbeiten"-Option nicht anzeigen, nur Download

In der Dateiablage-UI: Unterstuetzte Dateien bekommen ein zusaetzliches Edit-Icon oder der Doppelklick oeffnet den Editor statt den Download.

### 8. Admin-UI: ONLYOFFICE-Konfiguration

Erweiterung des Nextcloud-Tabs oder eigener Tab "ONLYOFFICE" in der Admin-UI:
- ONLYOFFICE Document Server URL (Text-Input, z.B. `http://localhost:8090`)
- JWT-Secret (Password-Input, muss mit dem Docker-Container uebereinstimmen)
- Button: "Verbindung testen" (ruft ONLYOFFICE Healthcheck-Endpoint auf)
- Status-Anzeige (verbunden/nicht verbunden, Version des Document Servers)

### 9. Deployment / Packaging

- ONLYOFFICE Docker-Container muss im `.deb`-Paket beruecksichtigt werden:
  - `docker.io` oder `docker-ce` als empfohlene Dependency (Recommends, nicht Depends - damit Installation ohne Docker moeglich bleibt)
  - `postinst`: Wenn Docker vorhanden, Container starten (oder Hinweis ausgeben)
  - Docker-Compose-Datei oder Script unter `/opt/casos/scripts/onlyoffice-setup.sh`
- Alternativ: ONLYOFFICE-Setup als separater optionaler Schritt dokumentieren (nicht automatisch im postinst)
- JWT-Secret: Bei Erstinstallation automatisch generieren und in Config speichern

### 10. Sicherheit

- WOPI-Tokens sind kurzlebig (8 Stunden) und an Benutzer + Datei gebunden
- JWT-Signierung zwischen Casos und ONLYOFFICE (Shared Secret)
- WOPI-Endpoints pruefen sowohl Token als auch JWT-Header
- Datei-Zugriff ueber WOPI respektiert die Casos-Berechtigungen (Projekt-Mitgliedschaft)
- Benutzer ohne Schreibrecht auf das Projekt: `UserCanWrite=false` in CheckFileInfo -> Read-Only-Modus

## Reihenfolge

1. ONLYOFFICE Docker-Container aufsetzen und testen (manuell)
2. DB-Schema (onlyoffice_config, wopi_tokens)
3. Admin-UI: ONLYOFFICE-Konfiguration (URL, Secret, Verbindungstest)
4. WOPI-Host Endpoints implementieren (CheckFileInfo, GetFile, PutFile)
5. Token-Management (Generierung, Validierung, Cleanup)
6. API-Endpoint: Editor oeffnen (gibt Config fuer Frontend zurueck)
7. Frontend: Fullscreen-Overlay mit ONLYOFFICE-iframe
8. Frontend: Dateiablage anpassen (Edit-Icon fuer unterstuetzte Formate, Doppelklick-Logik)
9. Lock-Mechanismus (optional)
10. Packaging anpassen (Docker-Setup Script)
11. End-to-End testen

## Verifikation

- ONLYOFFICE Document Server laeuft und ist erreichbar (Healthcheck)
- Admin-UI: URL und Secret konfigurierbar, Verbindungstest erfolgreich
- Klick auf .docx in Dateiablage: Fullscreen-Overlay mit Word-Editor oeffnet sich
- Dokument bearbeiten und speichern: Aenderungen landen ueber WebDAV in Nextcloud
- Datei ueber SMB/Nextcloud aendern, in Casos oeffnen: Aktuelle Version wird geladen
- .xlsx oeffnen: Tabellen-Editor
- .pptx oeffnen: Praesentation-Editor
- .txt/.md oeffnen: Text-Editor
- Nicht unterstuetzte Datei (.zip, .pdf): Kein "Bearbeiten"-Option, nur Download
- Benutzer ohne Schreibrecht: Editor oeffnet im Read-Only-Modus
- Token abgelaufen: Editor zeigt Fehlermeldung, kein Datenzugriff
- Overlay schliessen: Editor wird sauber beendet
- Gleichzeitiges Oeffnen derselben Datei von zwei Benutzern: Lock-Mechanismus greift (oder zweiter Benutzer erhaelt Read-Only)

## Nicht-Ziele

- Kein gleichzeitiges Bearbeiten (Co-Editing) in dieser Version (ONLYOFFICE unterstuetzt es, aber WOPI-Locking-Logik ist komplex)
- Keine Versionierung/History im Editor (Nextcloud verwaltet Versionen separat)
- Keine Konvertierung zwischen Formaten (z.B. docx -> pdf)
- Kein Offline-Editing
- Kein automatisches Speichern in konfigurierbarem Intervall (nur manuelles Speichern oder Save-on-Close)
- Kein eigener ONLYOFFICE fuer die Admin-UI (nur in der Haupt-App)
