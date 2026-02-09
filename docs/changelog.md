# Changelog

Zeitstempel;Version;Kategorie;Beschreibung
10.02.2026 00:55;0.0.1+12;Bugfix;Request Type-Hints in HTML-Routen (app.py, admin_app.py) - FastAPI interpretierte request ohne Hint als Query-Parameter
10.02.2026 00:45;0.0.1+11;Feature;Authentifizierung: Login/Logout mit Cookie-Sessions (bcrypt + itsdangerous), 401-Redirect
10.02.2026 00:45;0.0.1+11;Feature;Admin-App auf Port 8505: Benutzerverwaltung (CRUD) mit ExpandableTable
10.02.2026 00:45;0.0.1+11;Feature;Passwort-Aendern-Modal im Settings-Dropdown
10.02.2026 00:45;0.0.1+11;Feature;Username-Anzeige im Header, Abmelde-Button
10.02.2026 00:45;0.0.1+11;Aenderung;DB-Schema: users + sessions Tabellen, created_by-Spalte in tasks
10.02.2026 00:45;0.0.1+11;Aenderung;Alle API-Endpunkte (ausser Login) sind jetzt authentifiziert
09.02.2026 23:35;0.0.1+10;Feature;Globale msgbox()-Funktion in app_core.js (buttons: ok/cancel-yes, types: alert/confirm/warning)
09.02.2026 23:35;0.0.1+10;Aenderung;showConfirmDialog() durch msgbox() ersetzt, Bestaetigung beim Loeschen von Teilaufgaben hinzugefuegt
09.02.2026 23:21;0.0.1+9;Bugfix;Scroll-Position bleibt beim Zuklappen von Detail-Bereichen erhalten (Aufgaben + Teilaufgaben)
09.02.2026 23:21;0.0.1+9;Aenderung;WYSIWYG-Toolbar: Dropdowns auf feste Breite, einzeilig, nicht mehr von Subtask-Table-Styles ueberschrieben
09.02.2026 22:45;0.0.1+8;Aenderung;Mehr Kontrast fuer Teilaufgaben-Detailbereich (Light/Dark)
09.02.2026 22:41;0.0.1+7;Aenderung;Detail-Hintergruende: Aufgaben-Detail und Teilaufgaben-Detail mit unterschiedlichen Farben fuer besseren Kontrast
09.02.2026 22:38;0.0.1+6;Bugfix;Changelog
09.02.2026 22:36;0.0.1+5;Bugfix;Changelog
09.02.2026 22:34;0.0.1+4;Bugfix;Changelog
09.02.2026 22:30;0.0.1+3;Bugfix;Expanded-State bleibt nach Vorgaenger hinzufuegen/entfernen erhalten
09.02.2026 22:30;0.0.1+3;Aenderung;Browser-confirm() durch eigenes Overlay-Modal ersetzt (Confirm-Dialog)
09.02.2026 22:30;0.0.1+3;Aenderung;Vorgaenger-Chips als 4-Spalten-Grid inline positioniert
09.02.2026 22:30;0.0.1+3;Aenderung;Vorgaenger-Dropdown in Header-Zeile verschoben (zwischen Name und Bereich)
09.02.2026 21:24;0.0.1+2;Feature;WYSIWYG-Editor fuer Teilaufgaben-Beschreibungen (description-Spalte in sub_tasks)
09.02.2026 21:24;0.0.1+2;Feature;Aufklappbare Teilaufgaben: Text-Zeilen mit Detailbereich (gleiches Layout wie Hauptaufgaben)
09.02.2026 21:02;0.0.1+1;Aenderung;ExpandableTable: toggleAllRows(), client-seitige Select-Filter
09.02.2026 21:02;0.0.1+1;Aenderung;Tab "Dashboard" entfernt, ersetzt durch "Aufgaben" als Startseite
09.02.2026 21:02;0.0.1+1;Feature;Modal-Dialog fuer neue Aufgaben
09.02.2026 21:02;0.0.1+1;Feature;Control-Bar: Typ-/Status-Filter, Volltext-Suche, Alle auf-/zuklappen
09.02.2026 21:02;0.0.1+1;Feature;Vorgaenger-System: Abhaengigkeiten zwischen Teilaufgaben (Dropdown + Chips-UI)
09.02.2026 21:02;0.0.1+1;Feature;Positionsnummern fuer Teilaufgaben (auto-increment pro Projekt)
09.02.2026 21:02;0.0.1+1;Feature;Bereiche-Verwaltung mit +-Button (inline neue Bereiche anlegen)
09.02.2026 21:02;0.0.1+1;Feature;Typ "Projekt" mit Nested SubTask-Tabelle (inline-editierbar)
09.02.2026 21:02;0.0.1+1;Feature;WYSIWYG-Editor (contentEditable) fuer Aufgabenbeschreibungen
09.02.2026 21:02;0.0.1+1;Feature;DB-Schema (tasks, sub_tasks, areas, sub_task_dependencies), CRUD-API, Aufgaben-Tab mit ExpandableTable
