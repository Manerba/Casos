# Changelog

## 0.0.1+3 - Session 3

### Geaendert
- **Teilaufgaben-Detail**: Vorgaenger-Dropdown in Header-Zeile verschoben (zwischen Name und Bereich)
- **Vorgaenger-Chips**: Als 4-Spalten-Grid zwischen Dropdown und Bereich positioniert
- **Confirm-Dialog**: Browser-`confirm()` durch eigenes Overlay-Modal ersetzt (Aufgabe loeschen, Vorgaenger entfernen)
- **Expanded-State**: Aufgeklappte Teilaufgaben bleiben nach Aktionen (Vorgaenger hinzufuegen/entfernen) geoeffnet

## 0.0.1+2 - Session 2

### Hinzugefuegt
- **Aufklappbare Teilaufgaben**: SubTask-Zeilen als reiner Text, Klick oeffnet Detailbereich
- **WYSIWYG-Editor fuer Teilaufgaben**: Beschreibungsfeld mit Rich-Text-Editor
- **DB-Migration**: `description`-Spalte in `sub_tasks`-Tabelle
- **API**: `description`-Feld in SubTask-Endpoints (GET, POST, PUT)

## 0.0.1+1 - Session 1

### Hinzugefuegt
- SQLite-Datenbank mit Tasks, SubTasks, Areas, Dependencies
- CRUD-API fuer Aufgaben, Teilaufgaben und Bereiche
- Aufgaben-Tab mit ExpandableTable, Filtern und Suche
- Projekte mit Teilaufgaben und Vorgaenger-System (Positionsnummern, Chips)
- WYSIWYG-Editor fuer Aufgaben-Beschreibungen
- Modal fuer neue Aufgaben
