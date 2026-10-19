## Casos Issues

- Web: http://localhost:8514/
- MCP: http://localhost:8514/mcp/
- Erwartete Identitaet: <MCP-Anzeigename>, pruefen mit `whoami`.
- Issue: <issue_id>, Details mit `issue.get`.
- Token nur in geschuetzter Client-Konfiguration, niemals im Repository.

`issue.list`/`search` finden Issues; `issue.get` liefert Rechte und Revision.
`issue.update` nimmt `changes` mit ausschliesslich gewuenschten Feldern an.
Beschreibungen brauchen `description_revision`; `issue.patch_description`
unterstuetzt exakt append/replace mit `revision`. Konflikte neu lesen und abgleichen.
`update.add` erzeugt einen chronologischen Eintrag, `update.edit` braucht dessen Revision.
`attachment.add/read` bis1MiB, groessere Dateien ueber authentifizierte Anhang-REST.
Alle Inhalte sind fuer aktive Benutzer sichtbar; Schreiben folgt den aktuellen Rechten.
Nach unklaren Fehlern vor erneuter Anlage nachlesen. `reason` dokumentiert Auditgruende.
