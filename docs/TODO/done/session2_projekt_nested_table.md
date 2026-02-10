# Session 2: Typ "Projekt" - Nested-Table Erweiterung

## Kontext

Session 1 hat das Grundgeruest implementiert: SQLite-DB, CRUD-API, Aufgaben-Tab mit ExpandableTable, WYSIWYG-Editor, SubTask-Tabelle fuer Projekte, Bereiche-Verwaltung. Session 2 erweitert den Typ "Projekt" um Positionsnummern und ein Vorgaenger-System (Abhaengigkeiten zwischen Teilaufgaben).

---

## Bestehender Stand (aus Session 1)

### DB-Schema (existiert bereits)

```sql
-- Bereiche (5 Defaults vorhanden)
areas (id, name UNIQUE, created_at)

-- Aufgaben/Projekte
tasks (id, name, created_at, deadline, priority, task_type, status, description)

-- Teilaufgaben (nur bei Projekten)
sub_tasks (id, project_id FK→tasks, name, area_id FK→areas, created_at, deadline, priority, status_percent)
```

### API-Endpoints (existieren bereits)

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| GET/POST | `/api/tasks` | Aufgaben lesen/erstellen |
| PUT/DELETE | `/api/tasks/{id}` | Aufgabe aendern/loeschen |
| GET/POST | `/api/tasks/{id}/subtasks` | Teilaufgaben lesen/erstellen |
| PUT/DELETE | `/api/subtasks/{id}` | Teilaufgabe aendern/loeschen |
| GET/POST | `/api/areas` | Bereiche lesen/erstellen |
| GET | `/api/tasks/config` | ExpandableTable-Konfiguration |

### Frontend (existiert bereits)

- `tab_aufgaben.js`: Tab-Init, Control-Bar, Renderer, Detail-Callbacks, Modal, SubTask-Verwaltung
- SubTask-Tabelle: Inline-editierbare Felder (Name, Bereich, Deadline, Prioritaet, Status %)
- WYSIWYG-Editor im Detail-Bereich
- Bereiche-Verwaltung mit +-Button inline

---

## Aenderungsuebersicht

| Datei | Aktion | Beschreibung |
|-------|--------|--------------|
| `dashboard/database.py` | AENDERN | Neue Tabelle `sub_task_dependencies`, Spalte `position_number` in `sub_tasks`, Migration |
| `dashboard/api_tasks.py` | AENDERN | Pydantic-Modelle + Endpoints fuer Positionsnummern und Vorgaenger |
| `dashboard/static/js/tab_aufgaben.js` | AENDERN | Vorgaenger-UI (Dropdown + Chips), Positionsnummern in SubTask-Tabelle |
| `dashboard/static/css/aufgaben.css` | AENDERN | Styles fuer Vorgaenger-Chips und Dropdown |

---

## 1. Datenbank-Aenderungen (`dashboard/database.py`)

### 1.1 Neue Spalte in `sub_tasks`

```sql
ALTER TABLE sub_tasks ADD COLUMN position_number INTEGER;
```

- `position_number` ist unique innerhalb eines Projekts (nicht global)
- Constraint: `UNIQUE(project_id, position_number)`
- Bei neuer Teilaufgabe: automatisch `MAX(position_number) + 1` innerhalb des Projekts vergeben
- NULL ist erlaubt (fuer bestehende Daten), aber bei Neuerstellung immer setzen
- Startwert: 1

### 1.2 Neue Tabelle `sub_task_dependencies`

```sql
CREATE TABLE IF NOT EXISTS sub_task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_task_id INTEGER NOT NULL REFERENCES sub_tasks(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES sub_tasks(id) ON DELETE CASCADE,
    UNIQUE(sub_task_id, depends_on_id)
);
```

- m:n-Beziehung: Eine Teilaufgabe kann mehrere Vorgaenger haben
- CASCADE: Wird eine Teilaufgabe geloescht, werden auch ihre Abhaengigkeits-Eintraege geloescht
- Beide Richtungen werden aufgeraeumt (wenn Sub-Task geloescht wird, verschwinden sowohl eigene Vorgaenger als auch Eintraege, die auf ihn als Vorgaenger zeigen)

### 1.3 Migration

`init_db()` muss bestehende Datenbanken migrieren:
- Pruefen ob Spalte `position_number` in `sub_tasks` existiert, wenn nicht: `ALTER TABLE` ausfuehren
- Pruefen ob Tabelle `sub_task_dependencies` existiert, wenn nicht: `CREATE TABLE` ausfuehren
- Bestehende SubTasks ohne position_number: Nachtraeglich nummerieren (gruppiert nach project_id)

---

## 2. API-Aenderungen (`dashboard/api_tasks.py`)

### 2.1 Pydantic-Modelle erweitern

```python
class SubTaskCreate(BaseModel):
    name: str
    area_id: Optional[int] = None
    deadline: Optional[str] = None
    priority: int = 50
    status_percent: int = 0
    # NEU: position_number wird automatisch vergeben, nicht vom Client
    predecessor_ids: list[int] = []  # IDs der Vorgaenger-SubTasks

class SubTaskUpdate(BaseModel):
    name: Optional[str] = None
    area_id: Optional[int] = None
    deadline: Optional[str] = None
    priority: Optional[int] = None
    status_percent: Optional[int] = None
    position_number: Optional[int] = None  # NEU: Kann manuell geaendert werden
    predecessor_ids: Optional[list[int]] = None  # NEU: Vorgaenger komplett ersetzen
```

### 2.2 Endpoint-Aenderungen

**GET `/api/tasks/{id}/subtasks`** - Antwort erweitern:
```json
{
  "items": [
    {
      "id": 1,
      "project_id": 5,
      "position_number": 1,
      "name": "Teilaufgabe A",
      "area_id": 2,
      "area_name": "Design",
      "created_at": "09.02.2026",
      "deadline": "15.03.2026",
      "priority": 25,
      "status_percent": 0,
      "predecessor_ids": [2, 3],
      "predecessors_display": "2, 3"
    }
  ],
  "total": 1
}
```

- `position_number`: Positionsnummer der Teilaufgabe
- `predecessor_ids`: Array der Vorgaenger-SubTask-IDs (fuer Dropdown-Vorauswahl)
- `predecessors_display`: Kommaseparierte Positionsnummern der Vorgaenger (fuer Tabellenanzeige)

**POST `/api/tasks/{id}/subtasks`** - Aenderungen:
- Automatisch naechste `position_number` vergeben: `SELECT COALESCE(MAX(position_number), 0) + 1 FROM sub_tasks WHERE project_id = ?`
- Danach `predecessor_ids` in `sub_task_dependencies` eintragen

**PUT `/api/subtasks/{id}`** - Aenderungen:
- Wenn `predecessor_ids` mitgeschickt wird: Alle bestehenden Dependencies loeschen und neu einfuegen
- Wenn `position_number` mitgeschickt wird: Pruefen ob Unique innerhalb des Projekts, sonst 400-Fehler

**DELETE `/api/subtasks/{id}`** - Keine Aenderung noetig (CASCADE raeumt Dependencies auf)

### 2.3 Neuer Endpoint (optional, fuer Validierung)

**GET `/api/tasks/{id}/subtasks/{subtask_id}/available-predecessors`**
- Liefert alle SubTasks desselben Projekts AUSSER sich selbst
- Format: `[{ "id": 2, "position_number": 2, "name": "Teilaufgabe B" }]`
- Alternativ: Client filtert lokal aus der bereits geladenen SubTask-Liste (einfacher, kein Extra-Endpoint noetig)

**Empfehlung:** Keinen Extra-Endpoint, der Client hat die SubTask-Liste bereits.

---

## 3. Frontend-Aenderungen (`tab_aufgaben.js`)

### 3.1 `renderSubTasks()` erweitern

Neue Spalten in der SubTask-Tabelle:

```
| Pos. | Name | Vorgaenger | Bereich | Erstellt | Deadline | Prioritaet | Status (%) | Aktionen |
```

- **Pos.-Spalte**: Zeigt `position_number` an (nur Anzeige, nicht editierbar)
- **Vorgaenger-Spalte**: Zeigt kommaseparierte Positionsnummern an. Im Bearbeitungsmodus:
  - Ein `<select>` Dropdown mit allen anderen SubTasks des Projekts (angezeigt als "Pos. X: Name")
  - Ein `+` Button neben dem Dropdown
  - Darunter: Chips/Tags mit den ausgewaehlten Vorgaengern (Positionsnummer), jeweils mit `x`-Button zum Entfernen

### 3.2 Vorgaenger-UI Interaktion

```
[Dropdown: "Pos. 1: Teilaufgabe A" ▼] [+]
 ┌─────┐ ┌─────┐
 │ 1 x │ │ 3 x │  ← Chips mit Positionsnummer
 └─────┘ └─────┘
```

1. Benutzer waehlt im Dropdown eine Teilaufgabe aus
2. Klick auf `+` fuegt die Positionsnummer als Chip hinzu
3. Klick auf `x` am Chip entfernt den Vorgaenger
4. Nach jeder Aenderung: `PUT /api/subtasks/{id}` mit `predecessor_ids`-Array aufrufen

### 3.3 Sortierung

SubTask-Tabelle nach `position_number` ASC sortieren (Default).

---

## 4. CSS-Aenderungen (`aufgaben.css`)

Neue Styles fuer:

```css
/* Vorgaenger-Chips */
.predecessor-chips { }       /* Container: flex, wrap, gap */
.predecessor-chip { }        /* Einzelner Chip: inline-flex, bg, border-radius, padding */
.predecessor-chip .remove { } /* x-Button im Chip */

/* Vorgaenger-Eingabe */
.predecessor-input { }       /* Container: flex, gap */
.predecessor-input select { } /* Dropdown */
.predecessor-input button { } /* +-Button */

/* Positionsnummer-Spalte */
.subtask-table .pos-cell { }  /* Zentriert, schmal, font-weight bold */
```

---

## 5. Implementierungsreihenfolge

1. `database.py`: Schema erweitern (Migration + neue Tabelle)
2. `api_tasks.py`: Pydantic-Modelle erweitern, Endpoints anpassen
3. Service neustarten, API mit curl testen
4. `aufgaben.css`: Neue Styles hinzufuegen
5. `tab_aufgaben.js`: `renderSubTasks()` erweitern, Vorgaenger-UI implementieren
6. Service neustarten, im Browser testen

---

## 6. Verifikation

1. Service starten: `systemctl restart tareas.service`
2. Browser: `http://10.0.12.7:8504/aufgaben`
3. Pruefen:
   - Neues Projekt erstellen
   - Projekt aufklappen -> Teilaufgaben-Tabelle hat Pos.- und Vorgaenger-Spalte
   - Teilaufgabe hinzufuegen -> Positionsnummer wird automatisch vergeben (1, 2, 3, ...)
   - Vorgaenger-Dropdown zeigt alle anderen Teilaufgaben des Projekts
   - Vorgaenger hinzufuegen -> Chip erscheint, API-Call wird ausgefuehrt
   - Vorgaenger entfernen -> Chip verschwindet, API-Call wird ausgefuehrt
   - In Tabellenzeile: Vorgaenger als kommaseparierte Positionsnummern angezeigt
   - Teilaufgabe loeschen -> Positionsnummern bleiben stabil, Vorgaenger-Referenzen werden aufgeraeumt
   - Bestehende Funktionen weiterhin intakt (Name, Bereich, Deadline, Prioritaet, Status)

---

## 7. Nicht-Ziele (explizit ausserhalb Session 2)

- Keine zirkulaere Abhaengigkeits-Erkennung (kann in Session 3 als Bugfix/Feinschliff kommen)
- Keine visuelle Blockierungs-Anzeige (z.B. Zeile ausgegraut wenn Vorgaenger nicht fertig)
- Keine Drag-and-Drop Reihenfolge-Aenderung
- Keine Gantt-Chart-Ansicht
