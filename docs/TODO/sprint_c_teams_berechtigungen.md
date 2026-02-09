# Sprint C: Teams + Berechtigungen

## Ziel

Projekte koennen Teams haben. Teammitglieder erhalten Zugriff auf das Projekt und dessen Teilaufgaben mit konfigurierbaren Berechtigungen. Granulare Berechtigungen auf Teilaufgaben-Ebene koennen die projektweiten Standardberechtigungen ueberschreiben.

## Voraussetzungen

- Sprint A abgeschlossen: users-Tabelle, Auth-System
- Sprint B abgeschlossen: Aufgabenzuweisung, Sichtbarkeitsregeln, created_by/assigned_to

## Anforderungen

### 1. Datenbank

- Neue Tabelle `project_members`: id, project_id (FK tasks), user_id (FK users), can_read (bool, default true), can_edit (bool, default false), can_create (bool, default false), added_at
  - UNIQUE(project_id, user_id)
  - Speichert projektweite Standardberechtigungen pro Teammitglied
  - Der Projekt-Ersteller (tasks.created_by) hat implizit Vollberechtigung und taucht NICHT in dieser Tabelle auf (seine Rechte koennen nicht eingeschraenkt werden)

- Neue Tabelle `subtask_permissions`: id, sub_task_id (FK sub_tasks), user_id (FK users), can_read (bool), can_edit (bool)
  - UNIQUE(sub_task_id, user_id)
  - Ueberschreibt die projektweiten Standardberechtigungen fuer eine spezifische Teilaufgabe
  - Wenn kein Eintrag vorhanden: Fallback auf project_members-Berechtigungen

### 2. Berechtigungslogik

**Sichtbarkeit eines Projekts:**
- Ersteller sieht es immer (created_by)
- Zugewiesener sieht es (assigned_to aus Sprint B)
- Teammitglieder mit can_read=true sehen es
- Alle drei Quellen muessen im API-Filter beruecksichtigt werden

**Bearbeitbarkeit innerhalb eines Projekts:**
- Ersteller: Vollberechtigung (kann nicht eingeschraenkt werden)
- Teammitglied: Berechtigungen laut project_members (Standard) bzw. subtask_permissions (Ueberschreibung)
  - can_read: Darf Teilaufgabe sehen
  - can_edit: Darf bestehende Teilaufgaben bearbeiten
  - can_create: Darf neue Teilaufgaben anlegen

**Aufloesungsreihenfolge fuer eine Teilaufgabe:**
1. Ist der Benutzer Projekt-Ersteller? -> Vollzugriff
2. Gibt es einen subtask_permissions-Eintrag? -> Dessen Werte nutzen
3. Gibt es einen project_members-Eintrag? -> Dessen Standardwerte nutzen
4. Sonst: Kein Zugriff

### 3. API-Aenderungen

- Team-Management:
  - `GET /api/tasks/{id}/members` - Alle Teammitglieder eines Projekts mit Berechtigungen
  - `POST /api/tasks/{id}/members` - Teammitglied hinzufuegen (user_id, can_read, can_edit, can_create)
  - `PUT /api/tasks/{id}/members/{user_id}` - Berechtigungen eines Mitglieds aendern
  - `DELETE /api/tasks/{id}/members/{user_id}` - Teammitglied entfernen
  - Nur der Projekt-Ersteller darf Team verwalten

- Teilaufgaben-Berechtigungen:
  - `GET /api/subtasks/{id}/permissions` - Individuelle Berechtigungen einer Teilaufgabe
  - `PUT /api/subtasks/{id}/permissions/{user_id}` - Berechtigungen ueberschreiben
  - `DELETE /api/subtasks/{id}/permissions/{user_id}` - Ueberschreibung entfernen (Fallback auf Standard)

- Bestehende Endpoints anpassen:
  - `GET /api/tasks`: Sichtbarkeit um Teammitgliedschaft erweitern
  - `GET /api/tasks/{id}/subtasks`: Nur Teilaufgaben zurueckgeben, die der aktuelle Benutzer lesen darf
  - `PUT /api/subtasks/{id}`: Pruefung ob aktueller Benutzer can_edit hat
  - `POST /api/tasks/{id}/subtasks`: Pruefung ob aktueller Benutzer can_create hat

### 4. Frontend: Team-Verwaltung (Overlay-Dialog)

- Im Detail-Bereich eines Projekts: Neue Schaltflaeche "Team" nach dem Status-Feld
- Klick oeffnet Overlay-Dialog:
  - Titel: "Teammitglieder"
  - Button "+ Mitglied hinzufuegen" (Benutzer-Dropdown + Hinzufuegen-Button)
  - Tabelle mit Teammitgliedern:
    - Spalten: Nachname, Vorname, E-Mail, Lesen (Checkbox), Bearbeiten (Checkbox), Erstellen (Checkbox), Entfernen-Button
    - Checkboxen direkt editierbar (onChange -> API-Call)
    - Der Projekt-Ersteller wird NICHT in der Liste angezeigt (implizit Vollzugriff, Info-Text stattdessen)
  - Nur sichtbar wenn aktueller Benutzer = Projekt-Ersteller

### 5. Frontend: Granulare Teilaufgaben-Berechtigungen

- In der Teilaufgaben-Tabelle: Zusaetzliches Icon/Button pro Zeile fuer Berechtigungen (nur fuer Projekt-Ersteller sichtbar)
- Klick oeffnet kleinen Dialog: Liste der Teammitglieder mit Checkboxen fuer Lesen/Bearbeiten
- Wenn ueberschrieben: Visueller Indikator an der Zeile (z.B. kleines Schloss-Icon)
- Option "Auf Standard zuruecksetzen" (loescht subtask_permissions-Eintrag)

### 6. Frontend: Bearbeitbarkeit erzwingen

- Beim Aufklappen einer Teilaufgabe: API-Response enthaelt effektive Berechtigungen des aktuellen Benutzers
- Felder entsprechend readonly setzen:
  - can_read=true, can_edit=false: Alle Felder readonly
  - can_read=true, can_edit=true: Felder bearbeitbar
  - can_create=false: "+ Teilaufgabe"-Button ausblenden
- Teilaufgaben ohne can_read: Gar nicht in der Liste anzeigen (Backend filtert bereits)

## Reihenfolge

1. DB-Schema (project_members, subtask_permissions, Migration)
2. API: Team-Management Endpoints
3. API: Sichtbarkeits- und Berechtigungspruefungen in bestehende Endpoints einbauen
4. API: Teilaufgaben-Berechtigungs-Endpoints
5. Frontend: Team-Verwaltungs-Dialog
6. Frontend: Bearbeitbarkeit basierend auf Berechtigungen
7. Frontend: Granulare Teilaufgaben-Berechtigungen
8. End-to-End-Tests mit mehreren Benutzern

## Verifikation

- Projekt-Ersteller hat immer Vollzugriff
- Teammitglied mit can_read sieht Projekt in seiner Aufgabenliste
- Teammitglied ohne can_edit: Alle Felder einer Teilaufgabe readonly
- Teammitglied mit can_create: "+ Teilaufgabe"-Button sichtbar
- Granulare Ueberschreibung: Mitglied hat Standard can_edit=false, aber fuer eine bestimmte Teilaufgabe can_edit=true
- "Auf Standard zuruecksetzen" entfernt Ueberschreibung
- Benutzer ohne Teammitgliedschaft sieht Projekt nicht
- Team-Verwaltung nur fuer Projekt-Ersteller sichtbar

## Nicht-Ziele

- Keine LDAP-Anbindung (spaeterer Sprint)
- Keine Rollen-Templates (z.B. "Viewer", "Editor" als vordefinierte Berechtigungssets)
- Keine Vererbung ueber Projekt-Hierarchien (Projekte sind flach)
- Keine Audit-Logs fuer Berechtigungsaenderungen
