# Sprint: Netzplan (Projekt-Aufgabengraph)

## Ziel

Interaktiver Netzplan als Overlay im Detail-Bereich eines Projekts. Teilaufgaben werden als Knoten dargestellt, Vorgaenger-Beziehungen als geschwungene Pfeile. Automatisches hierarchisches Layout, Zoom, Pan und farbliche Statusanzeige.

## Kontext

- Teilaufgaben haben `position_number` und `predecessor_ids` (Vorgaenger-System aus Sprint Session 2)
- API-Endpoint `GET /api/tasks/{id}/subtasks` liefert alle Daten (inkl. Abhaengigkeiten)
- Frontend: Vanilla JS, kein Framework, Overlay-Pattern bereits vorhanden (Team-Dialog, Modal-Dialoge)
- vis-network als Bibliothek (einzelne JS-Datei, keine Build-Pipeline noetig)

## Entscheidungen

| Frage | Antwort |
|-------|---------|
| Bibliothek | vis-network (standalone JS+CSS) |
| Einbindung | Statische Dateien unter `/static/js/vis-network.min.js` und `/static/css/vis-network.min.css` |
| Darstellung | Fullscreen-Overlay ueber Button im Projekt-Detail-Bereich |
| Layout | Hierarchisch (links-nach-rechts oder oben-nach-unten), automatisch berechnet |
| Interaktivitaet | Zoom, Pan, Knoten anklickbar |

## Anforderungen

### 1. vis-network einbinden

- `vis-network.min.js` und `vis-network.min.css` herunterladen (Standalone-Distribution von vis.js, nur das network-Modul)
- Ablegen unter `dashboard/static/js/` und `dashboard/static/css/`
- In `index.html` einbinden (vor `tab_aufgaben.js`)
- Keine npm/Build-Pipeline - nur statische Dateien

### 2. Netzplan-Button

- Im Detail-Bereich eines Projekts (`onTaskRowExpanded` in `tab_aufgaben.js`): Neuer Button "Netzplan" in der Header-Zeile der editierbaren Felder
- Button nur sichtbar wenn `task_type === 'projekt'`
- Klick oeffnet das Netzplan-Overlay
- Button-Style: `control-btn` (konsistent mit bestehendem Design)

### 3. Netzplan-Overlay

- Fullscreen-Overlay (gleicher Pattern wie Modal: `modal-overlay` mit z-index, Hintergrund abgedunkelt)
- Header-Leiste mit:
  - Titel: Projektname
  - Legende: Farbpunkte fuer Status (Offen=grau, In Arbeit=blau, Erledigt=gruen)
  - Schliessen-Button (X) rechts
  - ESC schliesst Overlay
- Hauptbereich: vis-network Container (fuellt den gesamten verfuegbaren Platz)

### 4. Graph-Daten aufbereiten

Datenquelle: Die bereits geladenen SubTasks des Projekts (aus `loadSubTasks()`), kein zusaetzlicher API-Call noetig.

**Knoten (nodes):**
- Jede Teilaufgabe = ein Knoten
- ID: SubTask-ID
- Label: Positionsnummer + Name (z.B. "1: Design erstellen")
- Farbe basierend auf Status:
  - status_percent == 0: Grau (offen)
  - status_percent > 0 und < 100: Blau (in Arbeit, Akzentfarbe)
  - status_percent == 100: Gruen (erledigt)
- Form: Box (abgerundete Ecken)
- Schrift: Aus CSS-Variablen (Theme-kompatibel)

**Kanten (edges):**
- Fuer jede Vorgaenger-Beziehung: Kante von Vorgaenger-Knoten -> abhaengiger Knoten
- Pfeilspitze am Zielknoten (gerichtete Kante)
- Geschwungene Linien (vis-network Option: `smooth.type: 'curvedCW'` oder `'dynamic'`)
- Farbe: Dezent (border-color aus Theme)

### 5. Layout-Konfiguration

- Hierarchisches Layout: `layout.hierarchical`
  - Richtung: Links nach Rechts (`direction: 'LR'`)
  - Sortierung: Nach Level (Knoten ohne Vorgaenger = Level 0, Knoten mit Vorgaengern = Level des spaetesten Vorgaengers + 1)
  - Knotenabstand und Levelabstand konfigurierbar fuer gute Lesbarkeit
- Physik deaktiviert (bei hierarchischem Layout nicht noetig, verhindert Wackeln)
- Falls Teilaufgaben keine Vorgaenger-Beziehungen haben (isolierte Knoten): Nebeneinander auf Level 0 anzeigen

### 6. Interaktion

- **Zoom**: Mausrad oder Pinch-Geste
- **Pan**: Klicken und Ziehen auf leerem Bereich
- **Knoten-Klick**: Knoten wird hervorgehoben, Tooltip zeigt Details (Name, Status-%, Deadline, Bereich)
- **Doppelklick auf Knoten**: Overlay schliessen und die entsprechende Teilaufgabe in der Tabelle aufklappen/anscollen (optional, nice-to-have)
- **Fit-Button**: Button um den gesamten Graph in den sichtbaren Bereich einzupassen (`network.fit()`)

### 7. Theme-Kompatibilitaet

- Knoten-Farben und Schriftfarben muessen sowohl im Light- als auch im Dark-Theme funktionieren
- Hintergrund des Graph-Containers: `var(--bg-primary)`
- Kanten-Farbe: `var(--border-color)`
- Beim Theme-Wechsel (Event `themeChanged`): Farben der Knoten/Kanten aktualisieren oder Graph neu rendern

### 8. Neue Dateien

- `dashboard/static/js/vis-network.min.js` - vis-network Bibliothek (Download)
- `dashboard/static/css/vis-network.min.css` - vis-network Styles (Download)
- Netzplan-Logik direkt in `tab_aufgaben.js` als neue Funktionen (kein separates Modul noetig, da ueberschaubar)

### 9. CSS-Ergaenzungen (`aufgaben.css`)

- Netzplan-Overlay: Fullscreen-Container mit Header-Leiste und Graph-Bereich
- Legende: Inline-Flex mit farbigen Punkten und Labels
- Fit-Button: Positioniert im Overlay (z.B. unten-rechts oder in der Header-Leiste)
- Graph-Container: `width: 100%; height: calc(100vh - Header-Hoehe)`

## Reihenfolge

1. vis-network Dateien herunterladen und einbinden
2. Netzplan-Button im Projekt-Detail-Bereich
3. Overlay-Struktur (HTML-Generierung in JS)
4. Graph-Daten aufbereiten (SubTasks -> Nodes + Edges)
5. vis-network initialisieren mit hierarchischem Layout
6. Styling und Theme-Kompatibilitaet
7. Interaktion (Tooltip, Fit-Button)
8. Testen mit verschiedenen Projektgroessen und -strukturen

## Verifikation

- Button "Netzplan" nur bei Projekten sichtbar (nicht bei Typ "Aufgabe")
- Overlay oeffnet sich, Graph wird angezeigt
- Knoten zeigen Positionsnummer + Name
- Pfeile verbinden Vorgaenger korrekt (Richtung stimmt)
- Pfeile sind geschwungen (nicht gerade Linien)
- Farbcodierung nach Status funktioniert
- Zoom und Pan funktionieren
- ESC und X-Button schliessen Overlay
- Dark Mode: Farben passen sich an
- Projekt ohne Vorgaenger-Beziehungen: Alle Knoten nebeneinander
- Projekt mit linearer Kette (1->2->3): Knoten in Reihe
- Projekt mit Verzweigung (1->3, 2->3): Korrektes hierarchisches Layout
- Grosses Projekt (20+ Teilaufgaben): Performant und lesbar
- Fit-Button passt den sichtbaren Bereich an

## Nicht-Ziele

- Kein Bearbeiten von Aufgaben/Vorgaengern im Netzplan (nur Anzeige)
- Kein Drag-and-Drop zum Umordnen von Knoten
- Kein Kritischer-Pfad-Algorithmus (kann spaeter ergaenzt werden)
- Kein Export als Bild/PDF
- Keine Gantt-Chart-Ansicht (anderes Feature)
