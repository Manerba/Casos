# Sprint: Microsoft Teams Integration

## Ziel

Tareas als Tab-App in Microsoft Teams einbetten und optionale Webhook-Benachrichtigungen an Teams-Kanaele senden. Benutzer koennen Tareas direkt in ihrer Teams-Umgebung nutzen, ohne die Anwendung separat im Browser oeffnen zu muessen.

## Kontext

- Tareas laeuft aktuell auf HTTP (Port 8504/8505)
- Teams Tab-Apps erfordern zwingend HTTPS
- Admin-UI auf Port 8505 mit Benutzerverwaltung und LDAP-Tab
- Auth-System: Session-Cookies (Signed, HttpOnly, SameSite=Lax)
- Aufgabenzuweisung existiert (assigned_to, created_by)

## Voraussetzungen

- Ein Microsoft 365 Tenant mit Admin-Zugriff (zum Registrieren der App)
- Eine oeffentlich erreichbare Domain mit HTTPS-Zertifikat fuer Tareas (oder Reverse-Proxy)
- Optional: Azure AD App-Registrierung (fuer SSO)

## Teil 1: HTTPS + Reverse Proxy

### 1.1 Problemstellung

Teams laedt Tab-Apps als iframe. Dafuer gelten:
- Nur HTTPS erlaubt
- `X-Frame-Options` darf den iframe nicht blockieren
- `Content-Security-Policy` muss `frame-ancestors` fuer Teams-Domains erlauben
- Cookies brauchen `SameSite=None; Secure` (da Cross-Origin iframe)

### 1.2 Reverse Proxy Optionen

| Option | Beschreibung |
|--------|-------------|
| Apache auf Repo-Server | Neuer VHost mit Let's Encrypt, ProxyPass auf den Tareas-Server |
| Nginx auf Tareas-Server | Lokaler Reverse-Proxy, Let's Encrypt direkt |
| Caddy auf Tareas-Server | Automatisches HTTPS, minimale Konfiguration |

Die Wahl des Reverse-Proxy haengt von der Infrastruktur ab - muss mit dem Benutzer geklaert werden.

### 1.3 Anpassungen am Tareas-Backend

- Response-Header `X-Frame-Options` entfernen oder auf `ALLOW-FROM` setzen (veraltet) -> besser: `Content-Security-Policy: frame-ancestors https://teams.microsoft.com https://*.teams.microsoft.com`
- Session-Cookie anpassen: `SameSite=None` und `Secure=True` wenn hinter HTTPS-Proxy
- Konfigurierbar machen: Env-Variable oder Config-Eintrag ob Tareas im iframe-Modus laeuft

### 1.4 Domain/DNS

- Subdomain fuer Tareas einrichten (z.B. `tareas.firmenname.de`)
- DNS-Eintrag (A oder CNAME) auf den Server zeigen lassen
- Let's Encrypt Zertifikat beantragen

## Teil 2: Teams Tab-App

### 2.1 Teams App Manifest

Ein Teams-App-Paket ist eine ZIP-Datei mit:
- `manifest.json` - App-Definition (Name, ID, Beschreibung, Tab-URL, Berechtigungen)
- `color.png` - App-Icon 192x192 (Farbversion)
- `outline.png` - App-Icon 32x32 (Outline-Version)

**manifest.json Kernfelder:**
- `$schema`: Teams Manifest Schema (v1.16 oder neuer)
- `manifestVersion`: "1.16"
- `id`: Eindeutige GUID (einmalig generieren)
- `version`: Tareas-Version
- `name.short`: "Tareas"
- `name.full`: "Tareas - Aufgabenplanung"
- `description.short`: "Aufgabenplanung und Projektmanagement"
- `description.full`: Ausfuehrliche Beschreibung
- `developer`: Name, Website-URL, Privacy-URL, Terms-URL
- `staticTabs`: Persoenlicher Tab (zeigt Aufgaben des eingeloggten Benutzers)
- `configurableTabs`: Kanal-Tab (konfigurierbar welches Projekt angezeigt wird)
- `validDomains`: Die HTTPS-Domain von Tareas
- `webApplicationInfo`: Azure AD App-ID und Resource-URL (fuer SSO, optional)

### 2.2 Statischer Tab (Persoenlich)

- Erscheint in der linken Seitenleiste des Benutzers
- URL: `https://tareas.domain.de/aufgaben`
- Zeigt die persoenlichen Aufgaben des Benutzers (wie die normale Aufgaben-Ansicht)
- Kein Konfigurationsdialog noetig

### 2.3 Konfigurierbarer Tab (Kanal)

- Kann zu einem Teams-Kanal hinzugefuegt werden
- Konfigurationsseite: Auswahl welches Projekt im Tab angezeigt werden soll
  - Neue HTML-Seite: `dashboard/templates/teams_config.html`
  - Zeigt Dropdown mit allen Projekten des Benutzers
  - Nach Auswahl: Tab-URL wird auf `https://tareas.domain.de/aufgaben?project={id}` gesetzt
- Tareas-Frontend muss den `project`-URL-Parameter erkennen und das Projekt direkt aufklappen/filtern

### 2.4 Konfigurationsseite fuer Teams-Tab

- Neue Route: `GET /teams/config` -> Liefert `teams_config.html`
- Die Seite nutzt das Microsoft Teams JavaScript SDK (`@microsoft/teams-js`)
- SDK-Funktionen:
  - `microsoftTeams.initialize()` - SDK initialisieren
  - `microsoftTeams.settings.registerOnSaveHandler()` - Speichern-Callback
  - `microsoftTeams.settings.setSettings()` - Tab-URL und Display-Name setzen
  - `microsoftTeams.settings.setValidityState()` - Speichern-Button aktivieren
- Teams SDK als statische JS-Datei einbinden (CDN oder lokal)

### 2.5 App-Icons

- `color.png`: 192x192, Tareas-Logo auf farbigem Hintergrund
- `outline.png`: 32x32, Tareas-Logo als weisse Outline auf transparentem Hintergrund
- Ablegen unter `packaging/teams/` oder `dashboard/static/img/`

### 2.6 App-Paket bauen

- Script oder Anweisung zum Erstellen der ZIP-Datei (manifest.json + Icons)
- Upload in Teams Admin Center oder direkt im Teams-Client (Sideloading)
- Fuer organisationsweite Verteilung: Ueber Teams Admin Center veroeffentlichen

## Teil 3: Webhook-Benachrichtigungen

### 3.1 Konzept

Optionale ausgehende Benachrichtigungen an einen Teams-Kanal ueber Incoming Webhooks. Kein Bot noetig - nur HTTP-POST-Requests an eine Webhook-URL.

### 3.2 Konfiguration

- Neuer Tab in der Admin-UI: "Integrationen" (oder Erweiterung des bestehenden Settings)
- Konfigurationsfelder:
  - Teams Webhook-URL (Text-Input, vom Benutzer aus Teams kopiert)
  - Benachrichtigungen aktivieren (Checkbox)
  - Welche Events benachrichtigen (Checkboxen):
    - Aufgabe zugewiesen
    - Aufgabe erledigt (Status 100%)
    - Neue Aufgabe/Projekt erstellt
    - Deadline ueberschritten (taegliche Pruefung)
- Config in DB speichern (neue Tabelle `integrations_config` oder Key-Value in bestehender Config)

### 3.3 Webhook-Format

Teams Incoming Webhooks erwarten Adaptive Cards (JSON):
- Titel: Event-Beschreibung (z.B. "Neue Aufgabe zugewiesen")
- Body: Aufgabenname, Zuweisender, Zugewiesener, Deadline
- Action-Button: Link zu Tareas (oeffnet die Aufgabe im Browser)
- Farbe: Akzentfarbe passend zum Event-Typ

### 3.4 Webhook-Versand

- Neues Modul: `dashboard/notifications.py`
- Funktion `send_teams_notification(event_type, task_data)`:
  - Webhook-URL und Einstellungen aus DB laden
  - Pruefen ob Event-Typ aktiviert
  - Adaptive Card JSON aufbauen
  - HTTP-POST an Webhook-URL (async, nicht-blockierend, Fehler nur loggen)
- Aufrufe einbauen in:
  - `api_tasks.py`: Bei Zuweisung (PUT mit assigned_to), bei Status-Aenderung
  - Optional: Cron-Job fuer Deadline-Ueberschreitungen

### 3.5 DB-Schema

- Neue Tabelle `webhook_config`:
  - id INTEGER PRIMARY KEY
  - webhook_url TEXT
  - enabled INTEGER DEFAULT 0
  - notify_assigned INTEGER DEFAULT 1
  - notify_completed INTEGER DEFAULT 1
  - notify_created INTEGER DEFAULT 0
  - notify_overdue INTEGER DEFAULT 0
  - created_at TEXT

## Reihenfolge

1. HTTPS/Reverse-Proxy einrichten (Infrastruktur, ausserhalb des Codes)
2. Backend: iframe-Header und Cookie-Anpassungen
3. Teams App Manifest + Icons erstellen
4. Konfigurationsseite fuer konfigurierbaren Tab
5. Frontend: URL-Parameter `project` unterstuetzen (Projekt direkt anzeigen)
6. App-Paket bauen und in Teams sideloaden/testen
7. Webhook-Config in Admin-UI
8. Webhook-Versand-Modul
9. Webhook-Aufrufe in API-Endpoints einbauen
10. End-to-End testen (Tab + Webhooks)

## Verifikation

### Tab-App
- Tareas ueber HTTPS erreichbar
- App-Paket laesst sich in Teams hochladen (Sideloading)
- Persoenlicher Tab zeigt Aufgaben des eingeloggten Benutzers
- Kanal-Tab: Konfigurationsseite zeigt Projekt-Auswahl
- Kanal-Tab: Nach Konfiguration wird das gewaehlte Projekt angezeigt
- Login funktioniert im iframe (Cookies korrekt)
- Dark Mode in Teams: Tareas erkennt Teams-Theme (optional)

### Webhooks
- Webhook-URL in Admin-UI konfigurierbar
- Aufgabe zuweisen -> Benachrichtigung im Teams-Kanal mit Adaptive Card
- Aufgabe erledigen -> Benachrichtigung
- Link in der Adaptive Card oeffnet Tareas im Browser
- Webhook-Fehler (falsche URL) werden geloggt aber blockieren nicht die API

## Nicht-Ziele

- Kein Teams Bot (kein Befehls-Interface im Chat)
- Kein SSO mit Azure AD (Login bleibt ueber Tareas-eigene Anmeldung, SSO kann spaeter ergaenzt werden)
- Keine bidirektionale Sync mit MS Planner
- Keine Teams-Notifications (Push-Benachrichtigungen) - nur Kanal-Webhooks
- Kein automatisches Theme-Matching mit Teams (kann spaeter ueber Teams SDK `getContext` ergaenzt werden)

## Offene Punkte (vor Sprint mit Benutzer klaeren)

- Welche Domain/Subdomain soll fuer HTTPS genutzt werden?
- Welcher Reverse-Proxy (Apache, Nginx, Caddy)?
- Steht ein Microsoft 365 Tenant mit Admin-Zugriff zur Verfuegung?
- Soll die App organisationsweit oder nur per Sideloading bereitgestellt werden?
- Soll Azure AD SSO implementiert werden (Login ohne erneute Anmeldung in Teams)?
