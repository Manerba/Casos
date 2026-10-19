# Casos - Projektkontext

## Projektziel

Casos soll ein Ticketsystem auf Basis von **FastAPI + Vanilla JS** werden. Ausgangspunkt ist der rebrandete Klon von Tareas, Commit `ca5d45d` (Version `0.0.1+143`). Der aktuelle Funktionsumfang ist noch Aufgaben- und Projektplanung. Die Spezifikationen fuer den Ticket-Umbau werden erst in einer eigenen Session hier erarbeitet.

Den aktuellen technischen Kontext und den Stand des Klons beschreibt `AGENTS.md`. Casos verwendet eigene Ports 8514/8515/8516, `data/casos.db`, Cookie `casos_session` und Dienste `casos*`. Keine produktiven Daten oder Secrets wurden uebernommen, kein Remote eingerichtet und keine Dienste installiert. Aenderungen ausschliesslich unter `/sdb1/nextcloud/data/mir/files/Dev/Casos` vornehmen.

## Entscheidungen

| Aspekt | Entscheidung |
|--------|--------------|
| Backend | FastAPI (Python) |
| Frontend | Vanilla JS (kein Framework) |
| Styling | CSS Custom Properties (Light/Dark Theme) |
| Port | 8514 |
| Routing | SPA mit History API + Catch-All im Backend |

## Infrastruktur

| Komponente | Details |
|------------|---------|
| OS | Ubuntu 24.04 |
| Dashboard | Port 8514 |
| Admin | Port 8515 |
| Service | `casos.service` |

---

## Verfuegbare Komponenten

### ExpandableTable
Sortierbare, filterbare Tabelle mit aufklappbaren Detail-Rows.
- Python: `dashboard/components/expandable_table.py` (Column, DetailField, Filter, ExpandableTable, PaginationConfig)
- JS: `dashboard/static/js/expandable_table.js`
- CSS: `dashboard/static/css/expandable_table.css`

### KPI-Cards / Widget-Dashboard
Dashboard-Widgets mit KPI-Karten und Tabellen.
- Python: `dashboard/components/kpi_card.py` (KPICard, KPISection, Widget, WidgetDashboardConfig)
- JS: `dashboard/static/js/kpi_grid.js` (WidgetDashboard-Klasse)
- CSS: `dashboard/static/css/kpi_grid.css`

### Theme-System
Light/Dark mit CSS Custom Properties in `style.css`.

### Notification-System
`showNotification(message, type)` - Toast-Benachrichtigungen (info, success, error).

### DOM-Caching
Tab-Inhalte werden beim Wechsel als DocumentFragment gespeichert (Scroll, Filter, Zustand bleibt erhalten).

### URL-Routing
SPA-Routing mit `history.pushState()`. Backend hat Catch-All-Route fuer direkten URL-Zugriff.

---

## Neuen Tab hinzufuegen

1. JS-Datei erstellen: `dashboard/static/js/tab_example.js`
2. Init-Funktion definieren: `async function initExampleTab() { ... }`
3. In `app_core.js`: Tab in `switchTab()` registrieren + in `tabMap`/`buildPath` eintragen
4. In `index.html`: Tab-Link in `<nav class="tabs">` + `<script>`-Include
5. Optional: API-Endpunkt in `app.py` hinzufuegen
6. Optional: Tabellen-Config mit ExpandableTable definieren

---

## Projektstruktur

```
Casos/
├── dashboard/
│   ├── app.py                  # FastAPI Backend (Port 8514)
│   ├── components/
│   │   ├── __init__.py
│   │   ├── expandable_table.py # Generische Tabellen-Komponente
│   │   └── kpi_card.py         # KPI-Card/Widget Dataclasses
│   ├── static/
│   │   ├── css/
│   │   │   ├── style.css              # Haupt-CSS (Theme, Layout)
│   │   │   ├── expandable_table.css   # Tabellen-Styles
│   │   │   └── kpi_grid.css           # Widget-Styles
│   │   └── js/
│   │       ├── app_core.js            # Core: Theme, Routing, Tabs
│   │       ├── expandable_table.js    # Tabellen-JS
│   │       └── kpi_grid.js            # Widget-Dashboard-JS
│   └── templates/
│       └── index.html          # SPA-Einstiegspunkt
├── scripts/
│   └── casos.service          # Systemd-Service
├── git-commit.sh               # Auto-Version + Commit + Push
├── version.txt                 # Version (MAJOR.MINOR.PATCH+BUILD)
├── requirements.txt            # Python-Dependencies
├── .gitignore
└── CLAUDE.md                   # Diese Datei
```

---

## Versionierung & Commit-Workflow

**Immer `git-commit.sh` verwenden:**

```bash
./git-commit.sh "Kurze Beschreibung"
```

Das Script:
1. Inkrementiert Build-Nummer in `version.txt`
2. Staged alle Aenderungen (`git add -A`)
3. Commit mit Version-Prefix (z.B. `0.0.1+1: Beschreibung`)
4. Push zum konfigurierten Remote; ohne Remote bleibt der Commit lokal

---

## API-Endpunkte

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| GET | `/api/dashboard/info` | App-Infos und Entwickler-Hilfe |
| POST | `/api/dashboard/restart` | Service neu starten |

---

## Entwicklungsumgebung

Dieses Repo ist das Hauptprojekt fuer Bash auf Ubuntu 24.04 Server. Eine Casos-Desktop-App existiert derzeit nicht. `clients/` ist per `.gitignore` ausgeschlossen; kuenftige Clients sind eigenstaendige Repos mit eigenen Anweisungen.

---

## Benutzer-Praeferenzen

- Sprache: Deutsch bevorzugt
