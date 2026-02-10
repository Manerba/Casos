# Sprint B: Aufgabenzuweisung

## Ziel

Benutzer koennen einander Aufgaben und Teilaufgaben zuweisen. Zugewiesene Aufgaben erscheinen im Aufgaben-Tab des Empfaengers. Zuweisender und Zugewiesener haben unterschiedliche Bearbeitungsrechte. Notizen-System fuer Kommunikation zwischen Zuweiser und Zugewiesenem.

## Voraussetzungen

- Sprint A abgeschlossen: Login-System, users-Tabelle, Session-Cookies, created_by in tasks

## Anforderungen

### 1. Datenbank

- `tasks`-Tabelle erweitern: `assigned_to` (FK users, nullable) - der Benutzer, dem die Aufgabe zugewiesen wurde
- `sub_tasks`-Tabelle erweitern: `assigned_to` (FK users, nullable), `created_by` (FK users, nullable)
- Neue Tabelle `task_notes`: id, task_id (FK tasks), user_id (FK users), content (HTML), created_at, updated_at
  - Speichert Notizen des Zugewiesenen zur Aufgabe
  - Ein Eintrag pro Benutzer pro Aufgabe (UNIQUE task_id + user_id)
- Gleiche Struktur fuer `sub_task_notes`: id, sub_task_id (FK sub_tasks), user_id (FK users), content (HTML), created_at, updated_at

### 2. API-Aenderungen

- `GET /api/tasks`: Zusaetzliche Felder `created_by_name`, `assigned_to_name` (JOINs auf users)
- `PUT /api/tasks/{id}`: Neues Feld `assigned_to` (user_id oder null)
- `GET /api/tasks/{id}/subtasks`: Zusaetzliche Felder `created_by_name`, `assigned_to_name`
- `PUT /api/subtasks/{id}`: Neues Feld `assigned_to`
- Neuer Endpoint `GET /api/users/list` - Gibt alle Benutzer zurueck (id, vorname, nachname) fuer Zuweisungs-Dropdowns (nur fuer eingeloggte Benutzer)
- Notizen-Endpoints:
  - `GET /api/tasks/{id}/notes` - Alle Notizen zu einer Aufgabe
  - `PUT /api/tasks/{id}/notes` - Eigene Notiz speichern/aktualisieren
  - Analog fuer sub_tasks

### 3. Sichtbarkeitsregeln

Welche Aufgaben sieht ein Benutzer in seinem Aufgaben-Tab:
- Alle Aufgaben, die er selbst erstellt hat (`created_by` = eigene user_id)
- Alle Aufgaben, die ihm zugewiesen wurden (`assigned_to` = eigene user_id)
- Alle Aufgaben ohne `created_by` (Altdaten vor Sprint A)
- API muss nach aktuellem Benutzer filtern

### 4. Bearbeitbarkeitsregeln

**Zuweisender (created_by):**
- Kann Name, Deadline, Prioritaet, Beschreibung bearbeiten SOLANGE Aufgabe nicht zugewiesen ist
- Nach Zuweisung: Aufgabe nur noch lesen (alle Felder disabled/readonly)
- Sieht die Notizen des Zugewiesenen als readonly Kasten unterhalb der eigenen Beschreibung
- Kann Zuweisung aufheben (Aufgabe zuruecknehmen)

**Zugewiesener (assigned_to):**
- Kann Name, Deadline, Prioritaet NICHT bearbeiten (readonly)
- Sieht Beschreibung des Zuweisenden als readonly Kasten
- Hat eigenen WYSIWYG-Editor fuer Notizen (unterhalb des readonly-Kastens)
- Kann Status aendern (offen/in_arbeit/erledigt)

**Eigene Aufgaben (created_by = assigned_to = null oder created_by = eigene ID, nicht zugewiesen):**
- Volle Bearbeitungsrechte wie bisher

### 5. Frontend: Aufgaben-Tabelle

- Neue Spalten in der Haupttabelle: "Von" (created_by_name), "Zugewiesen an" (assigned_to_name)
- Spaltenreihenfolge anpassen: Name, Typ, Status, Prioritaet, Von, Zugewiesen an, Erstellt, Deadline
- ExpandableTable-Config vom Backend anpassen

### 6. Frontend: Detail-Bereich

- Neues Dropdown-Feld im Detail-Header: "Zuweisen an" (Liste aller Benutzer)
- Bearbeitbarkeits-Logik:
  - Pruefen ob aktueller Benutzer = created_by oder = assigned_to
  - Felder je nach Rolle readonly setzen oder bearbeitbar lassen
- Notizen-Anzeige:
  - Zuweisender sieht: [Beschreibung readonly] + [Notizen des Zugewiesenen readonly]
  - Zugewiesener sieht: [Beschreibung readonly] + [Eigener WYSIWYG-Editor fuer Notizen]
  - Eigene Aufgabe: [WYSIWYG-Editor wie bisher]
- Aktuellen Benutzer bei Seitenstart via `GET /api/auth/me` laden und global verfuegbar machen

### 7. Frontend: Teilaufgaben-Tabelle (Nested)

- Neue Spalten: "Von", "Zugewiesen an"
- Zuweisungs-Dropdown in jeder Zeile
- Gleiche Bearbeitbarkeitsregeln wie bei Hauptaufgaben

## Reihenfolge

1. DB-Schema erweitern (assigned_to, notes-Tabellen, Migration)
2. API anpassen (Sichtbarkeit, Zuweisung, Notizen)
3. Frontend: Aktuellen Benutzer global laden
4. Frontend: Tabellen-Spalten erweitern
5. Frontend: Detail-Bereich mit Bearbeitbarkeitslogik
6. Frontend: Notizen-System
7. Testen mit zwei Benutzern

## Verifikation

- Benutzer A erstellt Aufgabe -> nur bei A sichtbar
- A weist Aufgabe an B zu -> bei B sichtbar mit "Von: A"
- B kann Status aendern, aber nicht Name/Deadline/Prioritaet
- B schreibt Notiz -> A sieht die Notiz als readonly
- A kann Zuweisung aufheben -> Aufgabe wieder voll bearbeitbar
- Altdaten ohne created_by: fuer alle sichtbar
- Teilaufgaben: gleiche Zuweisungslogik

## Nicht-Ziele

- Kein Team-Konzept (Sprint C)
- Keine projektweiten Berechtigungen (Sprint C)
- Keine Benachrichtigungen bei Zuweisung (spaeter)
- Keine Aufgaben-Historie/Audit-Log
