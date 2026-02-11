# Sprint: Mail-Integration

## Uebersicht

Benachrichtigungsmails an Benutzer versenden ueber ein zentral konfiguriertes SMTP-Postfach.
Unterstuetzte Mailserver: Exchange Server (On-Premise), Exchange Online, beliebige SMTP-Provider.

---

## 1. Admin-UI: Tab "Mail"

### 1.1 SMTP-Server-Konfiguration

Neuer Tab "Mail" in der Admin-UI mit folgenden Eingabefeldern:

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| SMTP-Server | Text | Hostname des Mailservers |
| Port | Zahl | SMTP-Port (z.B. 25, 465, 587) |
| Verschluesselung | Auswahl | None / STARTTLS / SSL/TLS |
| Authentifizierung | Toggle | Ja / Nein |
| Benutzername | Text | Nur sichtbar wenn Authentifizierung aktiv |
| Passwort | Passwort | Nur sichtbar wenn Authentifizierung aktiv |
| Absender-Adresse | Text | From-Adresse fuer alle ausgehenden Mails |
| Absender-Name | Text | Anzeigename des Absenders |

- Es gibt genau ein globales Postfach fuer alle ausgehenden Mails.
- Konfiguration wird persistent gespeichert.

### 1.2 Testmail-Versand

- Button "Testmail senden" im Mail-Tab.
- Oeffnet ein Eingabefeld fuer die Empfaenger-Adresse.
- Versendet eine Testmail mit dem aktuell konfigurierten SMTP-Setup.
- Erfolgsmeldung oder Fehlermeldung wird angezeigt.

### 1.3 Mail-Templates (Texte bearbeiten)

- Im Mail-Tab gibt es einen Bereich "Mail-Vorlagen".
- Pro Event-Typ je ein editierbares Feld fuer:
  - **Betreff** (einzeilig)
  - **Text** (mehrzeilig, nur der Inhaltstext — nicht der HTML-Body/Rahmen)
- Platzhalter koennen im Text verwendet werden (z.B. `{aufgabe}`, `{benutzer}`, `{faelligkeit}`, `{link}`).
- Die verfuegbaren Platzhalter werden pro Event-Typ angezeigt.

Event-Typen mit anpassbaren Vorlagen:

| Event-Typ | Beschreibung | Platzhalter |
|-----------|-------------|-------------|
| Aufgabe zugewiesen | Benutzer wurde eine Aufgabe zugewiesen | {aufgabe}, {zuweiser}, {faelligkeit}, {link} |
| Faelligkeit Vorwarnung | X Tage vor Ablauf der Deadline | {aufgabe}, {faelligkeit}, {tage_verbleibend}, {link} |
| Faelligkeit erreicht | Deadline ist heute | {aufgabe}, {faelligkeit}, {link} |
| Statusaenderung | Status einer Aufgabe hat sich geaendert | {aufgabe}, {alter_status}, {neuer_status}, {geaendert_von}, {link} |
| Kommentar | Neuer Kommentar zu einer Aufgabe | {aufgabe}, {kommentar_von}, {kommentar_text}, {link} |
| Einladung | Benutzer wird eingeladen, Tareas zu nutzen | {benutzer}, {login_link} |

---

## 2. Benutzerverwaltung: Einladungsmail

- In der Benutzerverwaltung (Admin-UI) erhaelt jede Benutzerzeile einen Button "Einladungsmail senden".
- Vor dem Versand erscheint ein Bestaetigungsdialog ("Sind Sie sicher?") zum Schutz vor versehentlichem Versand.
- Die Einladungsmail enthaelt einen kurzen, freundlichen Satz, dass der Benutzer eingeladen wurde, Tareas zu nutzen, sowie einen Link zum Login.
- Versand erfolgt einzeln pro Benutzer (kein Sammelversand).

---

## 3. Benutzer-Einstellungen: Mail-Benachrichtigungen

### 3.1 Zugang

- Im Einstellungen-Menue (Zahnrad-Symbol rechts oben) neuer Punkt "Mail-Benachrichtigungen".
- Oeffnet ein Overlay/Modal mit Toggles.

### 3.2 Toggles pro Event-Typ

Jeder Benutzer kann individuell steuern, welche Benachrichtigungen er erhaelt:

| Toggle | Beschreibung | Standard |
|--------|-------------|----------|
| Aufgabe zugewiesen | Mail bei Zuweisung einer Aufgabe | Aktiv |
| Faelligkeit Vorwarnung | Mail X Tage vor Ablauf | Aktiv |
| Faelligkeit erreicht | Mail am Tag der Deadline | Aktiv |
| Statusaenderung | Mail bei Statusaenderung eigener Aufgaben | Aktiv |
| Kommentar | Mail bei neuem Kommentar zu eigenen Aufgaben | Aktiv |

- Default bei neuem Benutzer: **Alle Benachrichtigungen aktiv**.

### 3.3 Faelligkeits-Vorwarnung: Konfigurierbare Vorlaufzeit

- Zusaetzlich zum Toggle "Faelligkeit Vorwarnung" gibt es ein Eingabefeld fuer die Anzahl Tage.
- Standardwert: **2 Tage** vor Faelligkeit.
- Der Benutzer kann diesen Wert selbst aendern.

### 3.4 Faelligkeit erreicht: Versandzeitpunkt

- Die Mail "Faelligkeit erreicht" wird automatisch um **00:01 Uhr** am Tag der Deadline versendet.
- Dieser Zeitpunkt ist nicht konfigurierbar (nur der Toggle zum Aktivieren/Deaktivieren).

---

## 4. Mail-Versand (Backend)

### 4.1 Protokoll

- Ausschliesslich SMTP fuer den Versand.
- Unterstuetzung fuer STARTTLS und SSL/TLS.
- Kompatibel mit Exchange Server, Exchange Online (SMTP AUTH) und generischen SMTP-Providern.

### 4.2 HTML-Mail-Template

- Alle Mails werden als HTML versendet.
- Einfaches, sauberes Layout im Stil des Tareas-Dashboards (Farben, Schriftarten).
- Der HTML-Rahmen (Header, Footer, Styling) ist fest definiert.
- Nur Betreff und Inhaltstext sind pro Event-Typ ueber die Admin-UI anpassbar.
- Zusaetzlich wird eine Plain-Text-Alternative mitgesendet (Multipart).

### 4.3 Event-getriggerter Versand

Mails werden bei folgenden Ereignissen ausgeloest:

| Trigger | Zeitpunkt | Empfaenger |
|---------|-----------|------------|
| Aufgabe zugewiesen | Sofort bei Zuweisung | Zugewiesener Benutzer |
| Faelligkeit Vorwarnung | Taeglich (Cronjob/Scheduler), X Tage vor Deadline | Aufgaben-Verantwortlicher |
| Faelligkeit erreicht | Taeglich um 00:01 Uhr | Aufgaben-Verantwortlicher |
| Statusaenderung | Sofort bei Aenderung | Aufgaben-Verantwortlicher |
| Kommentar | Sofort bei neuem Kommentar | Aufgaben-Verantwortlicher |
| Testmail | Manuell (Admin-UI) | Eingegebene Adresse |
| Einladungsmail | Manuell (Benutzerverwaltung) | Ausgewaehlter Benutzer |

- Vor dem Versand wird geprueft, ob der Empfaenger den jeweiligen Benachrichtigungstyp aktiviert hat.
- Sofort-Trigger: Versand direkt nach dem ausloesenden Ereignis.
- Zeitgesteuerte Trigger (Faelligkeit): Hintergrund-Scheduler prueft taeglich ausstehende Deadlines.

---

## 5. Datenmodell (konzeptionell)

### 5.1 SMTP-Konfiguration

- Globale Einstellungstabelle mit den SMTP-Feldern (Server, Port, Verschluesselung, Auth, Credentials, Absender).
- Passwort wird verschluesselt gespeichert.

### 5.2 Mail-Vorlagen

- Tabelle mit Vorlagen pro Event-Typ.
- Felder: Event-Typ, Betreff, Text.
- Beim ersten Start werden Default-Vorlagen angelegt.

### 5.3 Benutzer-Benachrichtigungseinstellungen

- Pro Benutzer eine Konfiguration mit Toggles je Event-Typ.
- Zusaetzlich: Vorlaufzeit (Tage) fuer Faelligkeits-Vorwarnung.
- Default-Werte werden bei Benutzer-Erstellung gesetzt (alles aktiv, 2 Tage Vorlauf).

---

## 6. Abgrenzung (nicht im Scope)

- Kein Mail-Empfang (IMAP/EWS/Graph API).
- Kein Sammelversand fuer Einladungsmails.
- Kein Mail-Log oder Versandhistorie in der Admin-UI.
- Keine Microsoft Graph API Anbindung.
- Keine individuellen Absender-Adressen pro Benutzer.
