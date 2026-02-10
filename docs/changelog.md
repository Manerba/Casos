# Changelog

Zeitstempel;Version;Kategorie;Beschreibung
10.02.2026 20:30;0.0.1+23;Bugfix;LDAP: Falsches Bind-Passwort wurde nicht erkannt (raise_exceptions=True fuer ldap3 Connection)
10.02.2026 20:30;0.0.1+23;Bugfix;APT-Repo: GPG-Key im binaeren Format exportieren (statt ASCII-Armor)
10.02.2026 20:00;0.0.1+21;Feature;APT-Packaging: .deb-Paket-Bau mit packaging/DEBIAN (control, postinst, prerm, postrm)
10.02.2026 20:00;0.0.1+21;Feature;publish.sh: Build + Upload + Repo-Index-Aktualisierung + GPG-Signierung auf Repo-Server
10.02.2026 20:00;0.0.1+21;Feature;install.sh: Bootstrap-Script fuer Einzeiler-Installation (curl | bash)
10.02.2026 20:00;0.0.1+21;Feature;APT-Repository auf 188.245.43.207 eingerichtet (Apache-Alias, Verzeichnisstruktur, GPG-Key)
10.02.2026 20:00;0.0.1+21;Aenderung;Angepasste Service-Dateien fuer Paket (User tareas, /opt/tareas Pfade, venv)
10.02.2026 17:15;0.0.1+20;Bugfix;LDAP: StartTLS auf Port 389 wenn SSL nicht aktiviert (behebt strongerAuthRequired bei Samba-DCs)
10.02.2026 17:15;0.0.1+20;Bugfix;LDAP: TLS-Zertifikatsvalidierung deaktiviert (CERT_NONE) fuer selbst-signierte/abgelaufene Zertifikate
10.02.2026 17:00;0.0.1+19;Feature;LDAP-Integration: Active-Directory-Anbindung, AD-Benutzer automatisch synchronisieren
10.02.2026 17:00;0.0.1+19;Feature;LDAP-Login: AD-Benutzer melden sich mit AD-Zugangsdaten an (LDAP-Bind), lokale Benutzer als Fallback
10.02.2026 17:00;0.0.1+19;Feature;Admin-UI: Neuer Tab "LDAP" mit Server-Konfiguration, Verbindungstest, Gruppenauswahl
10.02.2026 17:00;0.0.1+19;Feature;Admin-UI: Benutzerverwaltung zeigt Quelle (Lokal/LDAP) und Status (Aktiv/Deaktiviert)
10.02.2026 17:00;0.0.1+19;Feature;LDAP-Sync: Manuell via Button + periodisch via systemd-Timer (15 Min.)
10.02.2026 17:00;0.0.1+19;Aenderung;DB-Schema: auth_source, ldap_dn, is_active in users; neue Tabelle ldap_config
10.02.2026 17:00;0.0.1+19;Aenderung;LDAP-Benutzer in Benutzerverwaltung: Felder readonly (ausser Admin-Checkbox), Loeschen nur wenn deaktiviert
10.02.2026 17:00;0.0.1+19;Aenderung;requirements.txt: ldap3 hinzugefuegt
10.02.2026 16:15;0.0.1+18;Bugfix;Subtask-View Save: Negative ID als strukturelles Signal (robust gegen Browser-Cache mit altem JS)
10.02.2026 15:00;0.0.1+17;Bugfix;Zugewiesene Teilaufgaben erscheinen jetzt in der Aufgabenliste des Zugewiesenen (als Pseudo-Aufgabe mit Projekt-Info)
10.02.2026 15:00;0.0.1+17;Bugfix;Readonly-Logik korrigiert: Deadline+Prioritaet bleiben fuer Ersteller nach Zuweisung editierbar
10.02.2026 15:00;0.0.1+17;Bugfix;Name+Beschreibung werden nach Zuweisung fuer den Ersteller readonly
10.02.2026 15:00;0.0.1+17;Aenderung;Subtask-Detail im Projekt: Creator sieht bei zugewiesener Subtask Beschreibung readonly + Zugewiesenen-Notizen
10.02.2026 15:00;0.0.1+17;Aenderung;saveSubTask() sendet nur editierbare Felder (respektiert readonly-Status)
10.02.2026 12:00;0.0.1+16;Feature;Teams: Projekte koennen Teammitglieder mit konfigurierbaren Berechtigungen (Lesen/Bearbeiten/Erstellen) haben
10.02.2026 12:00;0.0.1+16;Feature;Granulare Subtask-Berechtigungen: Ueberschreibungen pro Teilaufgabe fuer einzelne Teammitglieder
10.02.2026 12:00;0.0.1+16;Feature;Team-Dialog: Overlay zum Verwalten von Teammitgliedern (hinzufuegen, Berechtigungen aendern, entfernen)
10.02.2026 12:00;0.0.1+16;Feature;Subtask-Berechtigungs-Dialog: Schloss-Icon pro Teilaufgabe, Override setzen/entfernen
10.02.2026 12:00;0.0.1+16;Feature;Sichtbarkeit: Teammitglieder sehen Projekte in der Aufgabenliste, nicht-lesbare Teilaufgaben werden gefiltert
10.02.2026 12:00;0.0.1+16;Aenderung;DB-Schema: project_members + subtask_permissions Tabellen
10.02.2026 12:00;0.0.1+16;Aenderung;API: Neuer Router api_teams.py (Team-CRUD + Subtask-Permissions), Berechtigungschecks in bestehenden Subtask-Endpoints
10.02.2026 12:00;0.0.1+16;Aenderung;Frontend: Readonly-Erzwingung basierend auf Backend-Permissions, Team-Button nur fuer Ersteller
10.02.2026 09:00;0.0.1+15;Feature;Aufgabenzuweisung: Aufgaben/Teilaufgaben an andere Benutzer zuweisen
10.02.2026 09:00;0.0.1+15;Feature;Sichtbarkeitsfilter: Benutzer sehen nur eigene/zugewiesene Aufgaben (+ Altdaten ohne Ersteller)
10.02.2026 09:00;0.0.1+15;Feature;Notizen-System: Zugewiesene koennen Notizen hinterlassen, Ersteller sehen diese readonly
10.02.2026 09:00;0.0.1+15;Feature;Bearbeitbarkeitsregeln: Ersteller vs. Zugewiesener (readonly-Felder je nach Rolle)
10.02.2026 09:00;0.0.1+15;Aenderung;DB-Schema: assigned_to fuer tasks/sub_tasks, task_notes/sub_task_notes Tabellen
10.02.2026 09:00;0.0.1+15;Aenderung;Tabelle: Neue Spalten "Von" und "Zugewiesen an" in Aufgaben- und Teilaufgabenliste
10.02.2026 09:00;0.0.1+15;Aenderung;API: /api/users/list, /api/tasks/{id}/notes (GET/PUT), Sichtbarkeitsfilter in GET /api/tasks
10.02.2026 01:05;0.0.1+14;Bugfix;Admin-Benutzertabelle: Config-Feldnamen an ExpandableTable-Konvention angepasst (apiEndpoint, defaultSort, wildcardFields)
10.02.2026 01:00;0.0.1+13;Bugfix;Login-Redirect: 302 zu /login statt inline login.html (Browser-Cache-Problem behoben)
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
