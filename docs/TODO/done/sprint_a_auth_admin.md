# Sprint A: Authentifizierung + Admin-UI (Benutzerverwaltung)

## Ziel

Login-System mit Session-Cookies und eine Admin-Oberflaeche auf Port 8515 zur Benutzerverwaltung. Nach diesem Sprint kann sich kein Benutzer mehr ohne Anmeldung Aufgaben ansehen.

## Kontext

- Bestehende App: FastAPI auf Port 8514, SQLite (`data/casos.db`), Vanilla JS SPA
- Import-Pattern: `sys.path.insert(0, ...)` in app.py, absolute Imports (`from dashboard.xxx import ...`)
- Komponenten: ExpandableTable, KPI-Widgets, Theme-System, Notification, DOM-Caching, WYSIWYG-Editor, MsgBox
- Service: `casos.service` (`venv/bin/python dashboard/app.py`)

## Entscheidungen (vom Benutzer bestaetigt)

| Frage | Antwort |
|-------|---------|
| Session-Handling | Signed Cookie (Secret Key, kein JWT) |
| Session-Ablauf | 365 Tage |
| Passwort-Hashing | bcrypt (oder argon2 falls verfuegbar) |
| Initiale Passwoerter | Admin setzt Passwort beim Erstellen eines Benutzers |
| Passwort aendern | Ja, im Settings-Dropdown der Haupt-App (Modal-Dialog) |
| Admin-UI Architektur | Geteilte DB + gleicher Static-Ordner, eigener Port 8515 |
| Admin-Login | Eigener Login-Screen mit Titel "Casos Admin", initial admin/admin (hartcodiert oder DB-Eintrag) |

## Anforderungen

### 1. Datenbank

- Neue Tabelle `users`: id, username (unique), password_hash, vorname, nachname, email, is_admin (boolean), created_at
- Neue Tabelle `sessions`: id, user_id (FK users), token (unique), created_at, expires_at
- Bei `init_db()`: Default-Admin-Benutzer anlegen falls users-Tabelle leer (username: admin, passwort: admin, is_admin: true)
- Bestehende `tasks`-Tabelle: Neue Spalte `created_by` (FK users, nullable fuer Migration bestehender Daten)

### 2. Auth-System (Backend)

- Passwort-Hashing mit bcrypt (Paket `bcrypt` in requirements.txt)
- Login-Endpoint: `POST /api/auth/login` (username, password) -> setzt Signed Cookie
- Logout-Endpoint: `POST /api/auth/logout` -> loescht Cookie + Session
- Session-Info: `GET /api/auth/me` -> gibt aktuellen Benutzer zurueck (oder 401)
- Auth-Middleware: Alle `/api/`-Routen (ausser `/api/auth/login`) erfordern gueltigen Session-Cookie
- Passwort-Aendern: `PUT /api/auth/password` (old_password, new_password)
- Cookie: HttpOnly, SameSite=Lax, signiert mit Secret Key (aus Env-Variable oder Config-Datei)

### 3. Login-Seite (Frontend, Haupt-App)

- Eigenes HTML-Template oder Abschnitt in index.html
- Felder: Benutzername, Passwort, Login-Button
- Bei fehlender/abgelaufener Session: Automatisch zur Login-Seite umleiten
- Nach erfolgreichem Login: Weiterleitung zum Aufgaben-Tab
- Fehlermeldung bei falschem Login

### 4. Admin-UI (Port 8515)

- Eigene FastAPI-App: `dashboard/admin_app.py`
- Eigener systemd-Service: `casos-admin.service`
- Teilt DB und Static-Ordner mit der Haupt-App
- Eigenes HTML-Template: `dashboard/templates/admin.html`
- Eigener Login-Bildschirm mit Titel "Casos Admin" (gleicher Login-Mechanismus, aber nur is_admin=true darf rein)
- Ein Tab: "Benutzerverwaltung"

### 5. Benutzerverwaltung (Admin-UI Frontend)

- ExpandableTable fuer Benutzerliste
- Spalten: Nachname, Vorname, E-Mail, (Admin-Badge)
- Am Ende jeder Zeile: Bearbeiten/Loeschen-Buttons
- Bearbeiten: Inline oder Detail-Bereich (Nachname, Vorname, E-Mail, Passwort zuruecksetzen)
- Control-Bar: "+ Neuer Benutzer"-Button -> Modal mit Feldern: Benutzername, Vorname, Nachname, E-Mail, Passwort, Admin-Checkbox
- Admin-API-Endpoints (nur fuer is_admin):
  - `GET /api/admin/users`
  - `POST /api/admin/users`
  - `PUT /api/admin/users/{id}`
  - `DELETE /api/admin/users/{id}`

### 6. Haupt-App Anpassungen

- Settings-Dropdown: Neuer Eintrag "Passwort aendern" (Modal-Dialog: Altes Passwort, Neues Passwort, Bestaetigung)
- Settings-Dropdown: Neuer Eintrag "Abmelden" (ruft Logout-Endpoint auf)
- Header: Benutzername des eingeloggten Benutzers anzeigen
- Alle neu erstellten Aufgaben bekommen `created_by` = aktuelle user_id
- Bestehende Aufgaben ohne `created_by`: Allen Benutzern sichtbar (Migration-Kompatibilitaet)

### 7. Infrastruktur

- `requirements.txt`: bcrypt hinzufuegen
- `scripts/casos-admin.service`: Neuer systemd-Service fuer Admin-UI auf Port 8515
- Secret Key: In `data/secret.key` gespeichert (beim ersten Start automatisch generiert, in .gitignore)

## Reihenfolge

1. requirements.txt + bcrypt installieren
2. DB-Schema erweitern (users, sessions, migration)
3. Auth-Backend (Login, Logout, Session-Middleware, Passwort-Aendern)
4. Login-Seite Frontend
5. Admin-App Backend (admin_app.py, API-Endpoints)
6. Admin-HTML + Benutzerverwaltungs-Tab
7. Haupt-App: Settings-Dropdown erweitern, created_by, Header-Anzeige
8. Services konfigurieren und testen

## Verifikation

- Login mit admin/admin funktioniert (Haupt-App + Admin-UI)
- Ohne Login: Weiterleitung zur Login-Seite
- Neuen Benutzer anlegen (Admin-UI)
- Mit neuem Benutzer in Haupt-App einloggen
- Passwort aendern (Settings-Dropdown)
- Abmelden funktioniert
- Neue Aufgabe hat created_by gesetzt
- Admin-UI nur fuer Admins zugaenglich
- Nicht-Admin wird bei Admin-Login abgewiesen

## Nicht-Ziele (spaetere Sprints)

- Keine Aufgabenzuweisung an andere Benutzer (Sprint B)
- Kein Team-/Berechtigungskonzept (Sprint C)
- Keine LDAP-Anbindung (spaeter)
- Kein "Passwort vergessen" Flow
