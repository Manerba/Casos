# Sprint: Nextcloud-Dateiablage

## Ziel

Integration einer Dateiablage in Tareas ueber die WebDAV-Schnittstelle von Nextcloud. Pro Projekt kann ein Verzeichnis aus Nextcloud verknuepft werden. Die Dateien werden im Detail-Bereich des Projekts neben dem WYSIWYG-Editor in einer umschaltbaren Ansicht (Baumansicht / Icon-Grid) angezeigt. Voller Dateizugriff: Browsen, Oeffnen, Hochladen, Loeschen, Ordner erstellen.

## Kontext

- Nextcloud-Instanz vorhanden (z.B. `https://cloud.firma.de`)
- Ein Nextcloud-Benutzer besitzt ein Projekt-Wurzelverzeichnis mit mehreren Projektordnern
- Diese Ordner sind ggf. per Freigabe fuer andere Nextcloud-Benutzer zugaenglich
- Gleichzeitiger Zugriff ueber SMB moeglich (External Storage oder direkter Share)
- Tareas verbindet sich als dieser Nextcloud-Benutzer via WebDAV und proxied alle Requests

## Entscheidungen

| Frage | Antwort |
|-------|---------|
| Nextcloud-Zugang | Ein Service-Benutzer, Credentials in Admin-UI konfigurierbar |
| Protokoll | WebDAV (`/remote.php/dav/files/{user}/`) |
| Backend-Architektur | Tareas-Backend als Proxy (kein direkter Browser-zu-Nextcloud-Zugriff) |
| Dateizugriff | Lesen + Schreiben (browsen, oeffnen, hochladen, loeschen, Ordner erstellen) |
| Verzeichniszuordnung | Projekt-Ersteller waehlt Unterverzeichnis aus dem Wurzelverzeichnis |
| Ansicht | Umschaltbar: Baumansicht (Explorer-Stil) und Icon-Grid (Desktop-Stil) |
| Position im UI | Zwei-Spalten-Layout im Projekt-Detail: links Editor, rechts Dateien |

## Anforderungen

### 1. Datenbank

- Neue Tabelle `nextcloud_config`:
  - id INTEGER PRIMARY KEY
  - server_url TEXT NOT NULL (z.B. `https://cloud.firma.de`)
  - username TEXT NOT NULL (Nextcloud-Benutzername)
  - password TEXT NOT NULL (App-Passwort oder regulaeres Passwort)
  - base_path TEXT NOT NULL (Wurzelverzeichnis, z.B. `/Projekte`)
  - created_at TEXT DEFAULT (datetime('now'))
  - Maximal ein Eintrag (eine Nextcloud-Konfiguration)

- `tasks`-Tabelle erweitern:
  - `nextcloud_path` TEXT (relativer Pfad zum Projektverzeichnis innerhalb des Wurzelverzeichnisses, z.B. `Redesign-Website`)
  - Nur fuer task_type='projekt' relevant
  - NULL wenn kein Verzeichnis zugeordnet

### 2. WebDAV-Modul (`dashboard/webdav.py`)

Neues Modul fuer die Kommunikation mit Nextcloud via WebDAV (Python `requests` oder `httpx`).

**Funktionen:**

- **test_connection(server_url, username, password, base_path)** - Verbindungstest: PROPFIND auf das Wurzelverzeichnis. Liefert True/False + Fehlermeldung
- **list_directory(path)** - Verzeichnisinhalt auflisten (PROPFIND Depth 1). Liefert Liste von Eintraegen mit: Name, Typ (Datei/Ordner), Groesse, Letzte Aenderung, MIME-Type
- **list_subdirectories(base_path)** - Nur Unterordner des Wurzelverzeichnisses auflisten (fuer Projekt-Zuordnungs-Dropdown)
- **get_file(path)** - Datei herunterladen (GET). Liefert Dateiinhalt + MIME-Type
- **upload_file(path, content, content_type)** - Datei hochladen (PUT)
- **create_directory(path)** - Ordner erstellen (MKCOL)
- **delete_item(path)** - Datei oder Ordner loeschen (DELETE)
- **move_item(source_path, dest_path)** - Datei/Ordner verschieben/umbenennen (MOVE)

Alle Funktionen laden die Nextcloud-Config intern aus der DB. Pfade werden relativ zum konfigurierten Wurzelverzeichnis aufgeloest. Vollstaendiger WebDAV-Pfad wird intern zusammengebaut: `{server_url}/remote.php/dav/files/{username}/{base_path}/{relativer_pfad}`

### 3. API-Endpoints

**Admin-Endpoints (nur Admins):**
- `GET /api/admin/nextcloud/config` - Aktuelle Nextcloud-Konfiguration laden (Passwort maskiert)
- `POST /api/admin/nextcloud/config` - Konfiguration speichern (nach Verbindungstest)
- `DELETE /api/admin/nextcloud/config` - Konfiguration loeschen

**Datei-Endpoints (authentifizierte Benutzer):**
- `GET /api/tasks/{id}/files?path=` - Verzeichnisinhalt auflisten (Default: Wurzel des Projektverzeichnisses)
  - Antwort: Liste von {name, type (file/directory), size, last_modified, mime_type}
  - Prueft ob der aktuelle Benutzer Zugriff auf das Projekt hat
- `GET /api/tasks/{id}/files/download?path=` - Datei herunterladen (Stream-Response mit korrektem MIME-Type und Content-Disposition)
- `POST /api/tasks/{id}/files/upload?path=` - Datei hochladen (Multipart-Upload, Zielordner als Query-Parameter)
- `POST /api/tasks/{id}/files/mkdir?path=` - Ordner erstellen
- `DELETE /api/tasks/{id}/files?path=` - Datei oder Ordner loeschen
- `PUT /api/tasks/{id}/files/move` - Datei/Ordner umbenennen/verschieben (Body: source, destination)

**Verzeichniszuordnung:**
- `GET /api/nextcloud/directories` - Alle Unterordner des Wurzelverzeichnisses auflisten (fuer Zuordnungs-Dropdown)
- `PUT /api/tasks/{id}` - Bestehender Endpoint, erweitert um `nextcloud_path`-Feld

### 4. Admin-UI: Tab "Nextcloud"

Neuer Tab in der Admin-UI (wie LDAP-Tab).

**Formularfelder:**
- Nextcloud-URL (Text-Input, Platzhalter: `https://cloud.firma.de`)
- Benutzername (Text-Input)
- Passwort / App-Passwort (Password-Input)
- Wurzelverzeichnis (Text-Input, Platzhalter: `/Projekte`)
- Button: "Verbindung testen & Speichern"
- Status-Anzeige bei gespeicherter Config (Server-URL, Benutzer, Pfad, Verbindungsstatus)
- Button: "Loeschen" (wenn Config vorhanden)

### 5. Frontend: Verzeichniszuordnung im Projekt-Detail

- Im Detail-Bereich eines Projekts (Header-Felder): Neues Dropdown-Feld "Dateiablage"
  - Optionen: Alle Unterordner des Wurzelverzeichnisses (geladen via `GET /api/nextcloud/directories`)
  - Erste Option: "-- Keine --" (kein Verzeichnis zugeordnet)
  - Bei Auswahl: `nextcloud_path` via `PUT /api/tasks/{id}` speichern
- Nur sichtbar wenn Nextcloud konfiguriert ist und task_type='projekt'
- Nur der Projekt-Ersteller kann die Zuordnung aendern

### 6. Frontend: Dateiablage im Projekt-Detail

**Layout:**
- Zwei-Spalten-Layout im Detail-Bereich des Projekts:
  - Linke Spalte: WYSIWYG-Editor + Teilaufgaben (wie bisher)
  - Rechte Spalte: Dateiablage (nur sichtbar wenn Verzeichnis zugeordnet)
- Responsive: Bei schmalen Bildschirmen untereinander statt nebeneinander

**Header der Dateiablage-Spalte:**
- Breadcrumb-Navigation (klickbare Pfad-Segmente, z.B. `Projekte / Redesign / Entwuerfe`)
- Toggle-Button fuer Ansichtswechsel: Baum-Icon / Grid-Icon
- Button: "Hochladen" (oeffnet Datei-Dialog)
- Button: "Neuer Ordner" (Inline-Eingabe oder Prompt)

**Baumansicht (Explorer-Stil):**
- Aufklappbare Ordner mit Einrueckung
- Ordner-Icon + Name (klickbar zum Oeffnen/Aufklappen)
- Datei-Icon (basierend auf MIME-Type/Endung) + Name + Groesse + Datum
- Rechtsklick oder Aktions-Button pro Eintrag: Oeffnen, Herunterladen, Umbenennen, Loeschen
- Ordner lazy laden (Inhalt erst bei Aufklappen abrufen)

**Icon-Grid-Ansicht (Desktop-Stil):**
- Grosse Icons/Thumbnails in einem Grid
- Ordner als Ordner-Icon mit Name darunter
- Dateien als Typ-Icon mit Name darunter (z.B. PDF-Icon, Word-Icon, Bild-Icon, generisches Datei-Icon)
- Doppelklick auf Ordner: Navigiert hinein (Breadcrumb aktualisiert sich)
- Doppelklick auf Datei: Oeffnet die Datei (Download oder in Nextcloud oeffnen)
- Rechtsklick oder Aktions-Button: Herunterladen, Umbenennen, Loeschen

**Datei-Icons nach Typ:**
- Ordner: Ordner-Icon
- Bilder (.jpg, .png, .gif, .svg): Bild-Icon (optional: Thumbnail wenn Nextcloud Vorschau liefert)
- PDF: PDF-Icon
- Office-Dokumente (.docx, .xlsx, .pptx): Entsprechende Icons
- Text/Code (.txt, .md, .py, .js): Text-Icon
- Archive (.zip, .tar.gz): Archiv-Icon
- Sonstige: Generisches Datei-Icon
- Icons als SVG oder Unicode-Zeichen (kein Icon-Font noetig, konsistent mit bestehendem Design)

**Upload:**
- Button "Hochladen" oeffnet nativen Datei-Dialog (input type=file, multiple erlaubt)
- Drag-and-Drop auf den Dateibereich (Drop-Zone mit visuellem Feedback)
- Fortschrittsanzeige bei Upload
- Nach erfolgreichem Upload: Ansicht aktualisieren

**Loeschen:**
- Bestaetigung ueber msgbox() (bestehende Confirm-Dialog-Funktion)
- Bei Ordnern: Warnung dass Inhalt mitgeloescht wird

### 7. Dateien oeffnen

- Klick auf Datei: Zwei Optionen je nach Kontext
  - Standard: Download ueber Tareas-API (`GET /api/tasks/{id}/files/download?path=...`)
  - Alternative: In Nextcloud oeffnen (Link zu `{nextcloud_url}/f/{file_id}` oder `{nextcloud_url}/apps/files/?dir={path}`)
- Fuer den Nextcloud-Direktlink: WebDAV-PROPFIND liefert die Nextcloud-interne File-ID, daraus kann ein Direktlink gebaut werden
- Empfehlung: Download als Standard, "In Nextcloud oeffnen" als zusaetzliche Option im Kontextmenue

### 8. CSS-Ergaenzungen

- Zwei-Spalten-Layout fuer Projekt-Detail (CSS Grid oder Flexbox)
- Dateiablage-Container mit Header, Breadcrumb, Inhaltsbereich
- Baumansicht: Einrueckung, Aufklapp-Icons, Hover-Effekte
- Icon-Grid: Grid-Layout, Icon-Groessen, Hover-Effekte, Auswahlzustand
- Drop-Zone: Gestrichelter Rand, Highlight bei Drag-Over
- Upload-Fortschritt: Balken oder Prozentanzeige
- Responsive Breakpoints: Ab bestimmter Breite einspaltiges Layout
- Theme-kompatibel (Light/Dark)

### 9. Infrastruktur

- `requirements.txt`: `httpx` hinzufuegen (fuer async WebDAV-Requests) oder `requests` verwenden (bereits oft implizit vorhanden)
- Keine zusaetzlichen Services oder Cron-Jobs noetig

## Reihenfolge

1. DB-Schema (nextcloud_config-Tabelle, nextcloud_path in tasks)
2. WebDAV-Modul (`webdav.py`)
3. Admin-UI: Tab "Nextcloud" (Config-Formular mit Verbindungstest)
4. API-Endpoints fuer Dateioperationen
5. Frontend: Verzeichniszuordnung im Projekt-Detail (Dropdown)
6. Frontend: Dateiablage-Container mit Baumansicht
7. Frontend: Icon-Grid-Ansicht + Toggle
8. Frontend: Upload (Button + Drag-and-Drop)
9. Frontend: Loeschen, Umbenennen, Neuer Ordner
10. CSS: Zwei-Spalten-Layout, Responsive, Theme
11. Testen mit echten Dateien und verschiedenen Dateitypen

## Verifikation

- Admin-UI: Nextcloud-Verbindung testen und speichern
- Projekt erstellen, Verzeichnis aus Dropdown zuordnen
- Dateiablage erscheint rechts neben dem Editor
- Baumansicht: Ordner aufklappen, Dateien sehen
- Icon-Grid: Ordner navigieren, Dateien als Icons
- Ansicht umschalten (Baum <-> Grid)
- Breadcrumb-Navigation funktioniert
- Datei hochladen (Button und Drag-and-Drop)
- Datei herunterladen/oeffnen
- Ordner erstellen
- Datei/Ordner loeschen (mit Bestaetigung)
- Datei/Ordner umbenennen
- Grosse Dateien: Upload-Fortschritt sichtbar
- Verschiedene Dateitypen: Korrekte Icons
- Gleichzeitig ueber SMB eine Datei hinzufuegen -> in Tareas nach Refresh sichtbar
- Dark Mode: Alle Elemente korrekt dargestellt
- Kein Verzeichnis zugeordnet: Dateiablage-Spalte nicht sichtbar
- Nextcloud nicht konfiguriert: Dropdown und Dateiablage komplett ausgeblendet

## Nicht-Ziele

- Keine Datei-Vorschau/Thumbnails (nur Typ-Icons, Thumbnails koennen spaeter ergaenzt werden)
- Keine Datei-Versionierung (Nextcloud verwaltet Versionen intern)
- Keine Volltextsuche in Dateien
- Keine Dateien an Teilaufgaben (nur auf Projekt-Ebene)
- Kein Offline-Cache
- Keine Synchronisation (Echtzeit-Ansicht, bei jedem Navigieren wird WebDAV abgefragt)
- Kein Multi-Select (Mehrfachauswahl fuer Batch-Operationen kann spaeter kommen)
