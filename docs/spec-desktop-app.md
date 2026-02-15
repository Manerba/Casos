# Tareas Desktop App - Spezifikation

## Projektziel

Einzelbenutzer-Desktop-Anwendung fuer Windows, die das Tareas-Frontend in einem nativen Fenster rendert. Die App kann entweder mit einer lokalen SQLite-Datenbank (Standalone) oder als Client fuer einen Tareas-Server betrieben werden.

---

## Projektstruktur

### Einordnung im Gesamtprojekt

```
Tareas/                          <-- Git-Repo 1 (Server/Enterprise)
├── dashboard/                   <-- Haupt-Frontend + Backend
├── clients/                     <-- von Hauptrepo via .gitignore ignoriert
│   ├── desktop/                 <-- Git-Repo 2 (diese App)
│   ├── android/                 <-- Git-Repo 3 (Zukunft)
│   └── ios/                     <-- Git-Repo 4 (Zukunft)
```

- `clients/` wird in die `.gitignore` des Hauptrepos aufgenommen
- Jedes Client-Projekt ist ein eigenstaendiges Git-Repository
- Waehrend der Entwicklung importiert die Desktop-App Module direkt aus `../../dashboard/`

### Desktop-App Repository

```
clients/desktop/
├── src/
│   ├── launcher.py              <-- Haupteinstiegspunkt (pywebview + FastAPI)
│   ├── tray.py                  <-- System Tray Integration (pystray)
│   ├── notifications.py         <-- Windows-Benachrichtigungen (winotify)
│   ├── updater.py               <-- Auto-Update-Mechanismus
│   ├── welcome.py               <-- Willkommens-Dialog mit Tipps
│   └── file_browser.py          <-- Dateiablage-Feature (Verzeichnis + Dateiliste)
├── bundle/                      <-- Kopie der Dashboard-Dateien (durch Commit-Script)
│   ├── static/
│   ├── templates/
│   ├── components/
│   └── ...
├── i18n/
│   ├── de.json                  <-- Deutsche Texte
│   └── en.json                  <-- Englische Texte
├── assets/
│   └── icon.ico                 <-- App-Icon (Platzhalter, wird manuell erstellt)
├── installer/
│   └── setup.iss                <-- Inno Setup Script
├── tareas-desktop.spec          <-- PyInstaller-Konfiguration
├── git-commit.sh                <-- Commit-Script (kopiert Dashboard-Dateien + Version + Push)
├── version.txt
├── requirements.txt
├── CLAUDE.md
└── README.md
```

---

## Code-Sharing mit Hauptprojekt

### Entwicklung

- Die Desktop-App importiert Module direkt aus dem Hauptprojekt (`../../dashboard/`)
- Kein doppelter Code waehrend der Entwicklung
- Aenderungen am Frontend/Backend des Hauptprojekts sind sofort in der Desktop-App sichtbar

### Commit / Build

- Das `git-commit.sh` Script kopiert die benoetigten Dateien aus `../../dashboard/` nach `bundle/`
- Kopiert werden: `static/`, `templates/`, `components/`, relevante Backend-Module (database.py, API-Router etc.)
- NICHT kopiert werden: Admin-UI, Enterprise-Features, Server-spezifische Konfiguration
- Dadurch ist das Desktop-Repo eigenstaendig klonbar und baubar

---

## Betriebsmodi

### Standalone (Lokale Datenbank)

- Eigene SQLite-Datenbank im Benutzerprofil
- Lokaler FastAPI-Server laeuft als Thread innerhalb der App
- Dateiablage-Feature verfuegbar (lokale/SMB-Pfade)
- Keine Benutzer-Authentifizierung (Einzelbenutzer)

### Client (Verbindung zu Tareas-Server)

- Kein lokaler Server, API-Calls gehen an konfigurierten Remote-Server
- Benutzer-Authentifizierung erforderlich (Token-basiert)
- Server-URL nachtraeglich aenderbar ueber Settings-Dialog
- Dateiablage-Feature nicht verfuegbar (Server-seitige Dateien)

### Modus-Festlegung

- Der Betriebsmodus wird bei der Installation gewaehlt und ist danach nicht mehr aenderbar
- Neuinstallation erforderlich fuer Modus-Wechsel

---

## Installation

### Installer (Inno Setup)

Installationsschritte:

1. Sprachauswahl (Deutsch / Englisch)
2. Betriebsmodus-Auswahl:
   - Lokal (eigene Datenbank)
   - Client (Verbindung zu Server) + Server-URL Eingabefeld
3. Option: Bei Windows-Start automatisch starten (Hintergrund)
4. Installationsverzeichnis (Standard: `%LocalAppData%\Tareas\app\`)

### Installationspfad

Alles unter `%LocalAppData%\Tareas\`:

- Keine Admin-Rechte erforderlich (weder Installation noch Updates)
- Kein UAC-Prompt
- Konsistent mit modernen Apps (VS Code, Discord, Slack)

---

## Verzeichnisstruktur im Benutzerprofil

```
%LocalAppData%\Tareas\
├── app\                         <-- Programmdateien (Tareas.exe etc.)
├── data\
│   └── tareas.db                <-- SQLite-Datenbank (nur Standalone-Modus)
├── config\
│   └── settings.json            <-- Alle Einstellungen (dateibasiert, keine Registry)
└── logs\
    └── tareas.log               <-- Anwendungs-Log (mit Rotation)
```

---

## App-Verhalten

### Fenster

- Natives Desktop-Fenster via pywebview (System-Webview, kein Chromium-Bundling)
- Fensterposition und -groesse werden zwischen Sessions gespeichert
- Mehrere Instanzen sind erlaubt

### System Tray (pystray)

- Tray-Icon mit Tooltip "Tareas"
- Doppelklick auf Tray-Icon: Fenster oeffnen
- Rechtsklick-Menue: Oeffnen / Einstellungen / Beenden

### Schliessen-Verhalten

- Wenn "Im Hintergrund aktiv" aktiviert ist: Fenster schliessen = Minimieren in Tray, Beenden nur ueber Tray-Menue
- Wenn "Im Hintergrund aktiv" deaktiviert ist: Fenster schliessen = App beenden

### Autostart

- Optional, wird bei Installation gefragt
- Umsetzung ueber Registry-Key `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- Startet die App minimiert im Tray

---

## Features

### Dateiablage (nur Standalone-Modus)

Ersetzt die Nextcloud-Integration des Hauptprojekts. Zwei Varianten:

1. **Verzeichnis-Browse**: Ein konfigurierbarer Pfad (lokal oder Netzwerk/SMB) wird angegeben, dessen Inhalt als Dateiliste angezeigt wird
2. **Datei-Liste**: Beliebig viele einzelne Dateipfade werden angegeben und in einer Liste angezeigt

Verhalten:
- Doppelklick auf eine Datei oeffnet sie mit der in Windows hinterlegten Standard-Anwendung (`os.startfile`)
- SMB-Pfade (`\\server\freigabe\ordner`) funktionieren transparent wie lokale Pfade
- Konfiguration der Pfade ueber Settings-Dialog in der App

### Benachrichtigungen (winotify)

- Native Windows Toast-Notifications, erscheinen im Windows Action Center
- Erinnerung an faellige Aufgaben
- Vorlaufzeit konfigurierbar ueber Settings-Dialog (z.B. 1 Stunde, 1 Tag etc.)
- Pruef-Intervall: 1 Minute (fest, nicht konfigurierbar)
- Notification-Sound: Windows-Standard
- Voraussetzung: Option "Im Hintergrund aktiv" muss aktiviert sein

### Willkommens-Dialog

- Erscheint beim ersten Start nach der Installation
- Zeigt einen zufaellig ausgewaehlten Tipp aus einem Pool von 15 Tipps
- Tipps in der bei Installation gewaehlten Sprache
- Checkbox "Nicht mehr anzeigen" - Einstellung wird in `settings.json` gespeichert

### Settings-Dialog

Konfigurierbare Einstellungen:
- Im Hintergrund aktiv (ja/nein)
- Benachrichtigungs-Vorlaufzeit
- Dateiablage-Pfade (nur Standalone-Modus)
- Server-URL (nur Client-Modus)
- Auto-Update aktivieren/deaktivieren
- Willkommens-Dialog wieder aktivieren

---

## Updates

### Built-in Auto-Update

- Bei aktivierter Auto-Update-Funktion: App prueft bei Start auf neue Version
- Download und Installation erfolgen automatisch
- Abschaltbar ueber Settings-Dialog
- Eigener Update-Mechanismus (nicht ueber Winget)

### Winget-Kompatibilitaet

- Das Projekt liefert ein Winget-Manifest mit
- `winget upgrade Tareas` funktioniert unabhaengig von der Auto-Update-Funktion
- Fuer User, die ihr Patchmanagement ueber Winget abwickeln
- Beide Update-Wege existieren parallel und schliessen sich nicht gegenseitig aus

---

## Internationalisierung (i18n)

- Sprachauswahl bei Installation (Deutsch, Englisch)
- Alle UI-Texte, Willkommens-Tipps und Benachrichtigungen in der gewaehlten Sprache
- Sprachdateien als JSON (`i18n/de.json`, `i18n/en.json`)
- Sprache wird in `settings.json` gespeichert

---

## Technische Anforderungen

### Zielsystem

- Windows 10 und hoeher (kein Grund fuer Einschraenkung auf Windows 11)
- Keine zusaetzlichen Laufzeitumgebungen erforderlich (Python wird via PyInstaller eingebettet)

### Bibliotheken

| Komponente | Bibliothek |
|------------|-----------|
| Desktop-Fenster | pywebview (System-Webview) |
| System Tray | pystray |
| Benachrichtigungen | winotify |
| Bundling | PyInstaller |
| Installer | Inno Setup |

### Build-Pipeline

Das Repository enthaelt die komplette Build-Pipeline:
- `tareas-desktop.spec` - PyInstaller-Konfiguration
- `installer/setup.iss` - Inno Setup Script
- Aus dem geklonten Repo kann direkt der Installer gebaut werden

---

## Abgrenzung

Folgende Features des Hauptprojekts sind in der Desktop-App NICHT enthalten:
- Admin-UI
- Enterprise-Features
- Mehrbenutzerfaehigkeit (im Standalone-Modus)
- Nextcloud-Integration (ersetzt durch Dateiablage-Feature)
