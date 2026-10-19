# Abhängigkeiten und Lizenzen

Casos-Quellcode verwendet die MIT-Lizenz (`LICENSE`, im DEB `copyright`). Drittbibliotheken behalten ihre eigenen Lizenzen. Die Pythonabhängigkeiten werden beim Installieren mit pip aus `requirements.txt` installiert; das lokale DEB bündelt weder virtuelle Umgebung noch Pythonpakete oder Test-MSG-Dateien.

Für die Lesevorschau werden folgende Versionen verwendet:

| Paket | Version | Lizenz | Herkunft |
|---|---|---|---|
| extract-msg | 0.56.1 | GPL-3.0-or-later | https://pypi.org/project/extract-msg/0.56.1/ |
| Pillow | 12.3.0 | MIT-CMU; eingebettete Komponenten haben eigene Hinweise | https://pypi.org/project/pillow/12.3.0/ |
| striprtf | 0.0.33 | BSD-3-Clause | https://pypi.org/project/striprtf/0.0.33/ |

Die Lizenztexte der installierten, hier genannten Distributionen liegen unter `packaging/licenses/` und werden als `licenses/` in `/usr/share/doc/casos/` mitgeliefert. Weitere transitive Python-Lizenzen verbleiben bei ihren Distributionen in der installierten virtuellen Umgebung. Der JavaScript-Markdownparser Marked wird mit seinem Lizenztext unter `dashboard/static/js/vendor/marked.LICENSE` mitgeliefert.

Öffentliche MSG-Testfixtures stammen aus TeamMsgExtractor/msg-extractor, Commit `18172ea4730fcfef6edaa0bd20e7a9c64bea20b9`. Herkunft, SHA-256 und Lizenzhinweise stehen in `tests/fixtures/msg/manifest.json` und `NOTICE.txt`; `strangeDate.msg` enthält zusätzlich ausdrücklich CC-BY-SA-3.0-attribuierten Text. Diese Testdateien werden nicht in das DEB kopiert. Die Hinweise ändern weder die Casos-Lizenz noch erklären sie pauschal die Lizenzbedingungen einer künftigen gemeinsamen Veröffentlichung. Eine Veröffentlichung ist für Casos derzeit nicht eingerichtet.

Die Auswahl und APIprüfung sind im Entwicklungsbeleg `docs/project77-preview-research.json` dokumentiert. Die tatsächlich implementierten Ressourcenlimits und Download-Fallbacks stehen in `docs/operations.md`.
