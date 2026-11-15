# Windows-/WebView2-Testplan (NICHT DURCHGEFÜHRT)

**Status: nicht getestet.** Alle bisherigen Tests liefen unter Linux (Chromium über Playwright, `--browser`-Modus). Der pywebview-/WebView2-Start
und der Windows-Installer wurden in dieser Umgebung **nie ausgeführt**. Die Anwendung darf daher nicht als „unter Windows geprüft“ bezeichnet werden.

## Voraussetzungen
Windows 10/11, Python 3.11+, Microsoft Edge WebView2 Runtime, `pip install .[desktop]` im Ordner `backend`, `npm ci && npm run build` im Ordner `frontend`.

## Testfälle (bitte abhaken, Ergebnis + Datum + Tester eintragen)
| # | Prüfung | Erwartung | Ergebnis |
|---|---|---|---|
| W1 | `python -m leventum.desktop` | Fenster „Leventum Verwaltung“ öffnet, Einrichtung/Login sichtbar | offen |
| W2 | Neustart | Daten bleiben erhalten (Datenordner unter `%LOCALAPPDATA%`/konfiguriert) | offen |
| W3 | Eigene Dialoge (Löschen mit Begründung, Kündigung) | Dialoge erscheinen im Fenster (keine nativen Browser-Dialoge) | offen |
| W4 | Dokument hochladen, herunterladen | Datei wird gespeichert (ALLOW_DOWNLOADS) und Prüfsumme stimmt | offen |
| W5 | Backup erstellen (mit Passphrase), Download, Wiederherstellen | Restore erfolgreich, Daten identisch | offen |
| W6 | CSV-Bankimport mit Windows-Datei (ANSI/UTF-8, `;`) | Vorschau korrekt, Umlaute lesbar | offen |
| W7 | Fenstergrößen 1536×1024 … 1024×768, 125 %/150 % Skalierung | kein Überlauf, Panel als Drawer | offen |
| W8 | Port belegt / zweite Instanz | verständliche Meldung, keine Datenbeschädigung | offen |
| W9 | BitLocker aktiv? | Dokumentation: DB und Dokumente sind unverschlüsselt, Schutz nur über BitLocker | offen |

## Build-Hinweis
Ein Installer (z. B. PyInstaller) ist nicht Teil dieses Stands und wurde nicht erprobt.
