# Sprint: LDAP-Integration

## Ziel

Active-Directory-Anbindung ueber LDAP. Benutzer einer konfigurierbaren AD-Gruppe werden automatisch als Tareas-Benutzer synchronisiert und koennen sich mit ihren AD-Zugangsdaten anmelden. Lokale Benutzer (Admin) bleiben als Fallback erhalten.

## Kontext

- Admin-UI laeuft auf Port 8505 (`dashboard/admin_app.py`, Service `tareas-admin.service`)
- Admin-UI hat einen Tab "Benutzerverwaltung" (`tab_benutzer.js`)
- Auth-System: bcrypt-Passwoerter, Signed Session Cookies (365 Tage), `users`-Tabelle
- Login-Endpoint: `POST /api/auth/login` in `api_auth.py`, prueft aktuell nur lokale DB
- Auth-Hilfsfunktionen in `auth.py` (hash_password, verify_password, create_session, etc.)
- Dependencies: fastapi, uvicorn, bcrypt, itsdangerous

## Entscheidungen

| Frage | Antwort |
|-------|---------|
| Python-Library | `ldap3` (pure Python, kein C-Dependency) |
| SSL | Checkbox in Config. Bei Aktivierung wird Port-Vorschlag auf 636 gesetzt |
| Sync-Strategie | Periodisch (konfigurierbares Intervall in Minuten) via Cron-Job + Button "Jetzt synchronisieren" |
| Benutzer-Entfernung | Bei Sync: Deaktivieren (`is_active=false`). Manuelles Loeschen ueber Button in Admin-UI |
| Koexistenz | Lokale Benutzer + LDAP-Benutzer parallel. Lokaler Admin als Fallback wenn LDAP nicht erreichbar |
| Gruppen | Genau eine AD-Gruppe auswaehlen |
| Auth-Flow | AD-Benutzer: Login immer per LDAP-Bind. Lokale Benutzer: Login gegen lokale DB |
| AD-Attribute | sAMAccountName -> username, sn -> nachname, givenName -> vorname, mail -> email |

## Anforderungen

### 1. Datenbank

- `users`-Tabelle erweitern:
  - `auth_source` TEXT DEFAULT 'local' - Werte: 'local' oder 'ldap'
  - `ldap_dn` TEXT - Distinguished Name des AD-Objekts (fuer LDAP-Benutzer)
  - `is_active` INTEGER DEFAULT 1 - Aktiv/Deaktiviert (0 = deaktiviert, Login gesperrt)
  - Migration: Bestehende Benutzer bekommen auth_source='local', is_active=1
  - LDAP-Benutzer bekommen password_hash='' (leer, da Auth ueber LDAP laeuft)

- Neue Tabelle `ldap_config`:
  - id INTEGER PRIMARY KEY
  - server TEXT NOT NULL (IP oder Hostname)
  - port INTEGER DEFAULT 389
  - use_ssl INTEGER DEFAULT 0
  - bind_dn TEXT NOT NULL (DN des Lese-Benutzers, z.B. CN=ldapreader,OU=Service,DC=firma,DC=local)
  - bind_password TEXT NOT NULL
  - search_base TEXT NOT NULL (OU-Pfad, z.B. OU=Benutzer,DC=firma,DC=local)
  - group_dn TEXT (DN der ausgewaehlten Gruppe, leer wenn noch keine gewaehlt)
  - group_name TEXT (Anzeigename der Gruppe)
  - sync_interval_minutes INTEGER DEFAULT 60
  - last_sync_at TEXT
  - created_at TEXT DEFAULT (datetime('now'))
  - Es soll maximal ein Eintrag existieren (eine LDAP-Konfiguration)

### 2. LDAP-Modul (`dashboard/ldap_utils.py`)

Neues Modul mit Hilfsfunktionen (verwendet `ldap3`):

- **test_connection(server, port, use_ssl, bind_dn, bind_password, search_base)** - Verbindungstest. Liefert True/False + Fehlermeldung
- **list_groups(config)** - Alle Gruppen im search_base auflisten. Liefert Liste von {dn, name}
- **get_group_members(config)** - Alle Benutzer der konfigurierten Gruppe. Liefert Liste von {dn, sAMAccountName, sn, givenName, mail}
- **authenticate_user(config, username, password)** - LDAP-Bind mit Benutzer-DN. Liefert True/False
  - Zuerst DN des Benutzers anhand sAMAccountName im search_base finden (mit Service-Account)
  - Dann Bind-Versuch mit gefundenem DN + eingegebenem Passwort

### 3. Sync-Logik (`dashboard/ldap_sync.py`)

Neues Modul fuer die Synchronisierung:

- **sync_ldap_users()** - Hauptfunktion:
  1. LDAP-Config aus DB laden
  2. Gruppenmitglieder ueber `get_group_members()` abrufen
  3. Fuer jeden AD-Benutzer:
     - Existiert in users mit auth_source='ldap'? -> Attribute aktualisieren (vorname, nachname, email), is_active=1 setzen
     - Existiert nicht? -> Neuen User anlegen (auth_source='ldap', password_hash='', is_active=1)
  4. LDAP-Benutzer in DB, die NICHT mehr in der AD-Gruppe sind: is_active=0 setzen
  5. `last_sync_at` in ldap_config aktualisieren
  - Lokale Benutzer (auth_source='local') werden NICHT angefasst

### 4. Cron-Job fuer periodische Synchronisierung

- Eigenstaendiges Script: `scripts/ldap_sync_cron.py`
  - Importiert `ldap_sync.sync_ldap_users()`
  - Fuehrt Sync aus und loggt Ergebnis
  - Wird per systemd-Timer oder Crontab aufgerufen
- Systemd-Timer: `scripts/tareas-ldap-sync.timer` + `scripts/tareas-ldap-sync.service`
  - Timer liest Intervall NICHT aus DB (zu komplex), stattdessen festes Intervall (z.B. alle 15 Minuten)
  - Das Script selbst prueft ob genuegend Zeit seit last_sync_at vergangen ist (basierend auf sync_interval_minutes aus DB)
  - Alternativ: Einfacher Crontab-Eintrag statt systemd-Timer (pragmatischer)

### 5. API-Endpoints (Admin)

- `GET /api/admin/ldap/config` - Aktuelle LDAP-Konfiguration laden (bind_password maskiert)
- `POST /api/admin/ldap/config` - LDAP-Konfiguration speichern (nach erfolgreichem Verbindungstest)
  - Felder: server, port, use_ssl, bind_dn, bind_password, search_base, sync_interval_minutes
  - Fuehrt automatisch Verbindungstest durch
  - Bei Erfolg: Config speichern, Antwort mit Erfolg
  - Bei Fehler: Config NICHT speichern, Fehlermeldung zurueckgeben
- `DELETE /api/admin/ldap/config` - LDAP-Konfiguration loeschen (alle LDAP-Benutzer deaktivieren)
- `GET /api/admin/ldap/groups` - Verfuegbare AD-Gruppen im search_base auflisten (nur wenn Config vorhanden)
- `POST /api/admin/ldap/group` - Gruppe auswaehlen (group_dn + group_name speichern, sofort Sync ausfuehren)
- `DELETE /api/admin/ldap/group` - Gruppenauswahl aufheben (alle LDAP-Benutzer deaktivieren)
- `POST /api/admin/ldap/sync` - Manueller Sync ("Jetzt synchronisieren")
- Alle Endpoints nur fuer Admins (get_admin_user Dependency)

### 6. Auth-Flow anpassen (`api_auth.py`)

Login-Endpoint `POST /api/auth/login` erweitern:

1. Benutzer in DB suchen (username)
2. Wenn auth_source='local': Wie bisher gegen password_hash pruefen
3. Wenn auth_source='ldap':
   - Pruefen ob is_active=1 (sonst Fehler "Benutzer deaktiviert")
   - LDAP-Config aus DB laden
   - `authenticate_user(config, username, password)` aufrufen
   - Bei Erfolg: Session erstellen wie gehabt
   - Bei Fehler: "Falsches Passwort" zurueckgeben
4. Wenn Benutzer nicht in DB: Fehler "Benutzer nicht gefunden"
   - KEIN On-the-fly LDAP-Lookup (Benutzer muss vorher synchronisiert sein)

Fallback-Logik: Wenn LDAP-Server nicht erreichbar und auth_source='ldap':
- Login fehlschlagen lassen mit Hinweis "LDAP-Server nicht erreichbar"
- Lokale Benutzer (auth_source='local') koennen sich weiterhin anmelden

### 7. Admin-UI: Neuer Tab "LDAP"

Neuer Tab in `admin.html`: "LDAP" (href="/ldap", data-tab="ldap")
Neues JS: `dashboard/static/js/tab_ldap.js`

**Layout des Tabs (zwei Sektionen):**

**Sektion 1: LDAP-Server Konfiguration**
- Formularfelder:
  - Server (Text-Input: IP oder Hostname)
  - Port (Number-Input, Default 389)
  - SSL (Checkbox - bei Aktivierung Port-Vorschlag auf 636 setzen)
  - Bind-DN (Text-Input, Platzhalter: "CN=ldapreader,OU=Service,DC=firma,DC=local")
  - Bind-Passwort (Password-Input)
  - Suchpfad (Text-Input, Platzhalter: "OU=Benutzer,DC=firma,DC=local")
  - Sync-Intervall (Number-Input, Minuten, Default 60)
- Buttons: "Verbindung testen & Speichern", "Loeschen" (wenn Config vorhanden)
- Unter dem Formular: Status-Anzeige (gespeicherte Config als kompakte Info-Zeile: Server, Port, SSL, Suchpfad, letzter Sync)

**Sektion 2: AD-Gruppe (nur sichtbar wenn Config gespeichert)**
- Tabelle mit verfuegbaren AD-Gruppen (Name, DN)
- Jede Zeile hat einen "+"-Button zum Auswaehlen
- Wenn eine Gruppe ausgewaehlt ist:
  - Anzeige der gewaehlten Gruppe (Name + DN) mit "Auswahl aufheben"-Button
  - Darunter: Button "Jetzt synchronisieren" mit Anzeige des letzten Sync-Zeitpunkts
  - Darunter: Hinweis "LDAP-Benutzer werden in der Benutzerverwaltung angezeigt"

### 8. Admin-UI: Benutzerverwaltung anpassen (`tab_benutzer.js`)

- Neue Spalte in der Benutzer-Tabelle: "Quelle" (Badge: "Lokal" oder "LDAP")
- Neue Spalte: "Status" (Badge: "Aktiv" oder "Deaktiviert")
- LDAP-Benutzer:
  - Felder Nachname, Vorname, E-Mail, Benutzername sind NICHT bearbeitbar (Quelle = LDAP)
  - Kein Passwort-Feld (Auth ueber LDAP)
  - Loeschen-Button nur fuer deaktivierte LDAP-Benutzer sichtbar (manuelles Bereinigen)
  - is_admin kann vom Admin geaendert werden (auch fuer LDAP-Benutzer)
- Lokale Benutzer: Wie bisher voll editierbar

### 9. Infrastruktur

- `requirements.txt`: `ldap3` hinzufuegen
- Neues Script: `scripts/ldap_sync_cron.py`
- Neuer Service/Timer oder Crontab-Eintrag fuer periodischen Sync

## Reihenfolge

1. `requirements.txt` + ldap3 installieren
2. DB-Schema erweitern (users-Migration, ldap_config-Tabelle)
3. `ldap_utils.py` erstellen (Verbindung, Gruppen, Mitglieder, Auth)
4. `ldap_sync.py` erstellen (Sync-Logik)
5. API-Endpoints fuer LDAP-Config und Sync
6. `api_auth.py`: Login-Flow um LDAP-Auth erweitern
7. Admin-UI: Tab "LDAP" (tab_ldap.js)
8. Admin-UI: Benutzerverwaltung anpassen (Quelle, Status, Readonly fuer LDAP)
9. Cron-Script + Service/Timer fuer periodischen Sync
10. Services neustarten und testen

## Verifikation

- LDAP-Config Formular: Verbindung testen mit gueltigem und ungueltigem Server
- SSL-Checkbox: Port-Vorschlag wechselt auf 636
- Gruppen werden aufgelistet nach erfolgreicher Verbindung
- Gruppe auswaehlen: LDAP-Benutzer erscheinen in der Benutzerverwaltung
- LDAP-Benutzer hat Badges "LDAP" und "Aktiv"
- LDAP-Benutzer: Felder nicht bearbeitbar (ausser is_admin)
- Login mit AD-Zugangsdaten funktioniert
- Login mit lokalem Admin funktioniert weiterhin (auch wenn LDAP down)
- Benutzer aus AD-Gruppe entfernen -> nach Sync: Status "Deaktiviert", Login gesperrt
- Deaktivierten Benutzer manuell loeschen
- "Jetzt synchronisieren" funktioniert
- Periodischer Sync ueber Cron/Timer

## Nicht-Ziele

- Keine mehrfachen LDAP-Server (nur eine Konfiguration)
- Keine mehrfachen Gruppen (nur eine Gruppe)
- Keine verschachtelten Gruppen (nur direkte Mitgliedschaft)
- Keine automatische Admin-Zuweisung per AD-Gruppe
- Kein LDAP-Schreibzugriff (nur Lesen)
- Kein Passwort-Caching fuer Offline-LDAP-Login
