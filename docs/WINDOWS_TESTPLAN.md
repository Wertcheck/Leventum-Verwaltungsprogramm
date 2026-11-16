# Windows-/WebView2-Testplan (NICHT DURCHGEFÜHRT)

**Status: nicht getestet.** Alle bisherigen Tests liefen unter Linux (Chromium über Playwright, `--browser`-Modus). Der pywebview-/WebView2-Start
und der Windows-Installer wurden in dieser Umgebung **nie ausgeführt**. Die Anwendung darf daher nicht als „unter Windows geprüft“ bezeichnet werden.

## Voraussetzungen
Windows 10/11, Python 3.11+, Microsoft Edge WebView2 Runtime, `pip install .[desktop]` im Ordner `backend`, `npm ci && npm run build` im Ordner `frontend`.

> **Hinweis zur Installationsart (aus Quellcode-Lektüre, nicht ausgeführt):** `backend/leventum/main.py` sucht `alembic.ini` und `alembic/` relativ zu
> `Path(__file__).parent.parent` und `backend/pyproject.toml` packt nur `leventum*`. Eine **normale** (nicht editierbare) Installation per
> `pip install .[desktop]` ist daher vermutlich **nicht** lauffähig (Migrationen nicht auffindbar). Für die Testphase `pip install -e ".[desktop]"` im Ordner
> `backend` verwenden und das Ergebnis von WIN-ST-01 mit der verwendeten Installationsart festhalten. Zu prüfen; Konsequenzen siehe `docs/WINDOWS_BUILD_PLAN.md`.

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

## Skript-Unterstützung (UNGETESTET)
`scripts/windows_smoke_test.ps1` deckt einen Teil der **Server-/API-Ebene** ab (Prüfungen S01–S23, `--browser`-Modus, kein Fenster). Das Skript wurde
**nie ausgeführt und seine Syntax nicht geprüft** (Erstellung in einer Linux-Umgebung ohne PowerShell). Es kann beim ersten Windows-Lauf selbst fehlerhaft sein; ein
„fail“ muss zuerst daraufhin geprüft werden, ob Skript oder Anwendung die Ursache ist. „not-run“ ist **nicht** bestanden. Ein Skriptlauf ersetzt keinen
manuellen Fall mit Fenster/WebView2.

Zuordnung (Skript → Matrix): S01–S04 → WIN-ST-01; S05 → WIN-ST-06; S06/S19 → WIN-ST-03, WIN-PE-02; S07 → WIN-SEC-01; S08 → WIN-SEC-05;
S12–S14 → WIN-BR-01…04; S15–S16, S21 → WIN-UD-01, WIN-UD-03; S17–S20 → WIN-PE-02, WIN-PE-03. S22/S23 sind bewusst manuell.

## Konventionen der Matrix
- **Ergebnis:** `offen` · `bestanden` · `fehlgeschlagen` · `nicht anwendbar` – erst nach echtem Windows-Lauf ändern (mit Datum/Tester im Protokoll unten).
- **Nachweis:** S = Screenshot, L = Log/Konsolenausgabe, H = Hash (SHA-256 als Text), F = Ergebnisdatei (JSON des Skripts), N = Notiz. Dateien unter einer Protokoll-ID ablegen; keine echten Personendaten im Nachweis (erfundene Testdaten verwenden).
- Spalte „Erwartet“ enthält teils **Annahmen** (mit „Annahme“ markiert) – dort ist das tatsächliche Verhalten erst durch den Test belegt.
- Testdaten: ausschließlich erfundene Daten; eigener Datenordner pro Lauf (`LEVENTUM_DATA_DIR`), damit der echte Datenordner nicht berührt wird.

## Matrix A – Starter (`python -m leventum.desktop`)
| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-ST-01 | Python ≥ 3.11, Frontend gebaut, Installation (Art notieren: editierbar/normal) | `pip install -e ".[desktop]"` (und zusätzlich einmal `pip install ".[desktop]"` zur Prüfung der Annahme „normale Installation findet alembic nicht“); `python -c "import leventum.desktop"` | Installation ohne Fehler; Import ok. Annahme: normale Installation scheitert beim Start an Migrationen/`alembic.ini` | L | offen |
| WIN-ST-02 | wie ST-01, WebView2 vorhanden | `python -m leventum.desktop` | Fenster „Leventum Verwaltung“ (Startgröße 1536×1024, Mindestgröße 1100×700 laut Code) öffnet, Einrichtung/Login sichtbar | S | offen |
| WIN-ST-03 | wie ST-01 | `python -m leventum.desktop --browser --port 8799` | Konsole zeigt URL; `http://127.0.0.1:8799/api/v1/health` liefert `{"status":"ok"}`; Strg+C beendet den Prozess (Annahme: sauberes Ende) | L, S | offen |
| WIN-ST-04 | pywebview **nicht** installiert (frische venv ohne Extra `[desktop]`) | `python -m leventum.desktop` (ohne `--browser`) | Erwartung zu klären: laut Code `import webview` ohne Fangblock → Traceback `ModuleNotFoundError`; prüfen, ob/wie der Server-Thread endet und ob der Prozess hängen bleibt. Ergebnis als Befund festhalten (verständliche Meldung fehlt vermutlich) | L, N | offen |
| WIN-ST-05 | pywebview installiert, WebView2-Runtime **nicht** vorhanden (VM ohne Runtime bzw. Runtime deinstalliert – nur in Testumgebung) | `python -m leventum.desktop` | Verhalten unbekannt (pywebview könnte auf anderes Backend/Fehler ausweichen). Beobachten: Fehlermeldung, Prozessende, Konsole; Befund dokumentieren | S, L, N | offen |
| WIN-ST-06 | Port 8799 durch anderes Programm belegt (z. B. `python -m http.server 8799 --bind 127.0.0.1`) | `python -m leventum.desktop --browser --port 8799` | Verständliche Meldung, kein Schreiben in fremde Daten. **Risiko aus Code-Lektüre (ungetestet):** Bind-Fehler im Server-Thread und Health-Wartelogik (`desktop.py`) könnten gegen den fremden Prozess „erfolgreich“ wirken; genau beobachten | L, N | offen |
| WIN-ST-07 | ohne `--port` | Start dreimal nacheinander (parallel) mit **gleichem** Datenordner | Zweite/dritte Instanz: Verhalten dokumentieren (Code enthält keine Einzelinstanz-Sperre; beide würden dieselbe SQLite-Datei öffnen). Keine Datenbeschädigung erwartet/zu prüfen; Befund an Besitzer | L, N | offen |
| WIN-ST-08 | Datenordner nicht beschreibbar (z. B. Schreibschutz-ACL auf Testordner) | Start mit `LEVENTUM_DATA_DIR` auf diesen Ordner | Verständlicher Fehler, kein Teilzustand; Verhalten dokumentieren | L | offen |
| WIN-ST-09 | `--browser`, Standard-Browser (Edge/Chrome) | URL im Browser öffnen, Einrichtung durchlaufen | Oberfläche identisch nutzbar; Cookie-Sitzung funktioniert | S | offen |

## Matrix B – pywebview / WebView2
| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-WV-01 | Fenstermodus läuft | Titelleiste ansehen | Titel „Leventum Verwaltung“ | S | offen |
| WIN-WV-02 | wie oben | Fenstergröße beim Start und Minimalgröße messen; Fenster verkleinern | Startgröße ≈ 1536×1024 (sofern Bildschirm groß genug); Mindestgröße 1100×700 wird nicht unterschritten (Annahme) | S | offen |
| WIN-WV-03 | Anzeige auf 100 % | Alle Hauptseiten öffnen (Dashboard, Objekte, Verträge, Zahlungen, Einstellungen) | Kein Überlauf, keine abgeschnittenen Inhalte | S | offen |
| WIN-WV-04 | Anzeige auf 125 % | wie WV-03; Fenster neu starten | Kein Überlauf, Seitenpanel als Drawer bei geringer Breite | S | offen |
| WIN-WV-05 | Anzeige auf 150 % | wie WV-03; Fenster neu starten | wie WV-04; Text unscharf? (Notiz) | S | offen |
| WIN-WV-06 | Zwei Monitore mit unterschiedlicher Skalierung (z. B. 100 %/150 %), falls vorhanden | Fenster zwischen Monitoren ziehen | Darstellung bleibt nutzbar; Verhalten notieren (Unschärfe/Größensprünge) | S, N | offen |
| WIN-WV-07 | Fenstermodus | Eigene Dialoge öffnen (Löschen mit Begründung, Kündigung) | Dialoge erscheinen im Fenster, modal, bedienbar (siehe W3). Prüfen, ob irgendwo native `alert/confirm` genutzt werden und im WebView2 unbemerkt unterdrückt würden | S | offen |
| WIN-WV-08 | Fenstermodus | Tab-Reihenfolge, Enter/Esc in Dialogen, Strg+C/V in Formularfeldern, Strg+F, Strg+P, F5 | Tastaturbedienung funktioniert; F5/Strg+R lädt die Seite neu – prüfen, ob Sitzung erhalten bleibt (Cookie); Verhalten bei F5 dokumentieren | N | offen |
| WIN-WV-09 | Fenstermodus | Fenster in den Hintergrund und zurück; Dialog offen lassen; Fokus in Eingabefeld | Fokus wird korrekt zurückgegeben, Eingaben gehen nicht verloren | N | offen |
| WIN-WV-10 | Fenstermodus; `ALLOW_DOWNLOADS = True` (try/except in `desktop.py`) | Dokument-Download und Backup-Download (falls in der Oberfläche vorhanden) auslösen | Speichern-Dialog oder Ablage im Downloads-Ordner (Annahme); Datei vollständig; SHA-256 stimmt mit Original überein. **Dokumentieren, ob die Einstellung in der installierten pywebview-Version existiert** (sonst stilles `except`) | S, H | offen |
| WIN-WV-11 | wie WV-10 | Download mit Dateiname, der Zeichen außerhalb von Latin-1 enthält (z. B. „Ł“, „ő“, Emoji), und Umlaute | Erwartung: Download funktioniert. **Vermutung aus Code-Lektüre (ungetestet):** `Content-Disposition: filename="…"` wird ohne RFC-5987-Kodierung gesetzt; Nicht-Latin-1-Zeichen könnten einen Serverfehler (HTTP 500) auslösen – Befund bei Bestätigung an Besitzer | S, L | offen |
| WIN-WV-12 | Fenstermodus | Externe Links (falls vorhanden, z. B. `mailto:`, `http(s)://`) anklicken | Es darf **keine** ausgehende Verbindung durch die App entstehen; Verhalten dokumentieren (öffnet WebView/Standardbrowser/nichts). Keine externen Ressourcen beim Laden (Netzwerkmonitor) | S, N | offen |
| WIN-WV-13 | Fenstermodus | Rechtsklick/Kontextmenü, DevTools (F12), Drag&Drop einer Datei ins Fenster | Verhalten dokumentieren (Sicherheit: DevTools in Produktion ggf. unerwünscht; Drag&Drop darf Navigation weg von der App nicht auslösen) | S, N | offen |
| WIN-WV-14 | Fenstermodus | Fenster schließen (X) | Prozess endet vollständig (kein verwaister `python.exe` im Task-Manager); Port wieder frei | L, N | offen |

## Matrix C – Dateizugriffe und Datenordner
| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-FS-01 | `LEVENTUM_DATA_DIR` **nicht** gesetzt, keine `.env` im Arbeitsordner | Erststart, danach Explorer: `%LOCALAPPDATA%\Leventum` | Unterordner `db`, `documents`, `backups`, Datei `db\leventum.sqlite3` vorhanden (laut `config.py`; Annahme für Windows) | S | offen |
| WIN-FS-02 | Datenordner in Pfad mit Leerzeichen | `LEVENTUM_DATA_DIR="C:\Test Daten\Leventum Test"`; Start, Einrichtung, Upload, Backup | Alles funktioniert | L | offen |
| WIN-FS-03 | Pfad mit Umlauten/Sonderzeichen (z. B. `C:\Tëst Ärger\Dätén`) | wie FS-02 | Alles funktioniert; SQLite-URL (`sqlite:///…`) und Alembic kommen mit dem Pfad zurecht (Annahme) | L | offen |
| WIN-FS-04 | Datenordner tief verschachtelt, Gesamtpfad > 260 Zeichen (Dokumentpfad ≈ Datenordner + `\documents\xxxx\<32 Hex>.ext`), mit und ohne aktivierten Long-Path-Support | Start, Upload, Backup, Restore | Verhalten dokumentieren (MAX_PATH-Fehler?) – Befund, falls Fehlermeldung unverständlich oder Teilzustand entsteht | L, N | offen |
| WIN-FS-05 | Datenordner auf anderem Laufwerk/USB-Stick/Netzlaufwerk (UNC) – nur Beobachtung | Start auf Wechseldatenträger, dann Datenträger ziehen (nur Testdaten!) | SQLite auf Netzlaufwerk ist **nicht** vorgesehen; Verhalten/Empfehlung dokumentieren, keine Freigabeaussage | N | offen |
| WIN-FS-06 | Normales Benutzerkonto | Rechte des Ordners `%LOCALAPPDATA%\Leventum` prüfen (`icacls`) | Nur eigenes Konto/SYSTEM/Administratoren (Standard-ACL des Profils, Annahme) – Abweichungen dokumentieren | L | offen |
| WIN-FS-07 | Zweites Windows-Konto | Als anderes Benutzerkonto auf `%LOCALAPPDATA%\Leventum` des ersten zugreifen | Zugriff verweigert (Annahme); sonst Befund | N | offen |
| WIN-FS-08 | Windows Defender aktiv (Echtzeitschutz) | Upload mehrerer Dateien, Backup erzeugen, Restore ausführen; Defender-Protokoll prüfen | Keine Fehler/Verzögerungen > Toleranz; Defender-Funde/Quarantäne dokumentieren; keine Ausnahmen setzen, ohne es zu vermerken | S, L | offen |
| WIN-FS-09 | Dritter Virenscanner/EDR falls vorhanden | wie FS-08 | Befund dokumentieren (Dateisperren auf `*.sqlite3`/`*.zip` möglich) | N | offen |
| WIN-FS-10 | Server läuft | Während Betrieb im Datenordner: `db\leventum.sqlite3` im Explorer kopieren/öffnen; `-wal`/`-shm`-Dateien beobachten | SQLite-Dateien sind gesperrt oder lesbar (dokumentieren); App bleibt funktionsfähig. **Keine Kopie der Live-Datei als Backup verwenden** | N | offen |
| WIN-FS-11 | Server läuft, Last: gleichzeitig Browser-Tab und Fenster | Viele Schreibvorgänge (Skript oder Handklicks) bei gleichzeitigem Backup | Keine „database is locked“-Fehler; falls doch: Meldung/Häufigkeit dokumentieren | L | offen |
| WIN-FS-12 | Zugriff auf `db` durch Backup-Software/OneDrive-Ordnerumleitung (falls Profil umgeleitet) | Prüfen, ob `%LOCALAPPDATA%` nicht in Cloud-Sync liegt | Dokumentieren; Cloud-Sync von Datenordner ist nicht vorgesehen | N | offen |

## Matrix D – Upload und Download (Dokumente)
Erlaubte Typen laut `storage/local.py`: `.pdf .png .jpg .jpeg .docx .xlsx .txt .csv` (Magic-Bytes-Prüfung bei PDF/PNG/JPG/DOCX/XLSX); Standardlimit 25 MB; Speicherschlüssel zufällig.

| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-UD-01 | Angemeldet, Objekt vorhanden | Je eine Testdatei pro erlaubtem Typ hochladen (erfundener Inhalt) | Upload ok; Liste zeigt Name/Größe; Download liefert byte-identische Datei (SHA-256 Original = Download) | S, H | offen |
| WIN-UD-02 | wie oben | Nicht erlaubte Typen (`.exe`, `.bat`, `.ps1`, `.html`), umbenannte Datei (z. B. `.exe` als `.pdf`), leere Datei, Datei > 25 MB | Jeweils verständliche Ablehnung (HTTP 422), nichts gespeichert | S | offen |
| WIN-UD-03 | wie oben | Dateiname mit Umlauten, Leerzeichen, Sonderzeichen (`Prüfung Müller (1).pdf`), langer Name (> 150 Zeichen), Name mit Punkten | Name bleibt in der Oberfläche korrekt; Download-Dateiname korrekt (siehe auch WIN-WV-10/11) | S, H | offen |
| WIN-UD-04 | wie oben | Datei aus Windows-Pfad hochladen, deren Name Backslashes im Client-Dateinamen simuliert (nur per Skript/curl: `filename="C:\\x\\a.pdf"`) | Nur Basisname gespeichert (Code ersetzt `\` durch `/`) | L | offen |
| WIN-UD-05 | wie oben | Größe 1 KB, 1 MB, 10 MB, nahe 25 MB hochladen/herunterladen | Erfolgreich; Dauer notieren; SHA-256 identisch | H | offen |
| WIN-UD-06 | wie oben | Gespeicherte Datei im Dateisystem manuell verändern (Testdatenordner!), dann Download | Server meldet Integritätsfehler (HTTP 409 `file_corrupt`), Download wird nicht ausgeliefert | S, L | offen |
| WIN-UD-07 | wie oben | Gespeicherte Datei im Dateisystem löschen, dann Download | HTTP 404 `file_missing` mit verständlicher Meldung | S | offen |
| WIN-UD-08 | Defender aktiv | Upload einer EICAR-Testzeichenfolge **nur auf isolierter Testumgebung und nur wenn Sicherheitsbeauftragte zustimmt** (optional) | Verhalten dokumentieren (Defender entfernt Datei im Datenordner → Dokument „missing“?) | N | offen |

## Matrix E – Datenpersistenz
| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-PE-01 | Testdaten (Objekt, Vertrag, Sollstellung, Zahlung, Dokument) angelegt | Fenster schließen, App neu starten, Anmeldung | Alle Daten vorhanden, Beträge unverändert | S | offen |
| WIN-PE-02 | wie PE-01 | `--browser`-Server per Task-Manager/`taskkill /F` beenden (Absturz-Simulation), neu starten | Daten bis zum letzten abgeschlossenen Request vorhanden; keine Datenbankbeschädigung; `PRAGMA integrity_check` (z. B. über Backup-Verify) ok | L | offen |
| WIN-PE-03 | wie PE-01 | Während eines laufenden Uploads/Backups Prozess beenden | Keine halbfertige Backup-Datei als gültig gelistet (`.part` bleibt evtl. liegen – dokumentieren); Dokumentliste konsistent | L, N | offen |
| WIN-PE-04 | wie PE-01 | Windows-Abmeldung/Neustart bei laufender App (kein Stromausfall-Test am echten System) | Beim nächsten Start Daten vorhanden | N | offen |
| WIN-PE-05 | **Nur Hinweis, nicht automatisiert:** Stromausfall-Simulation (z. B. VM hart ausschalten, nur auf Wegwerf-VM mit Testdaten) | Während Schreibvorgang VM hart ausschalten, neu starten | Erwartung: SQLite mit Journal/WAL übersteht dies; **Annahme**, nicht belegt. Nur wenn VM-Test vorgesehen; Ergebnis nur als Hinweis dokumentieren | N | offen |
| WIN-PE-06 | Datenordner mit Testdaten | App-Version aktualisieren (Quellcode neu), Start | Migrationen laufen beim Start automatisch (`run_migrations`); **vorher Backup** (siehe WIN-UPD-01); Daten vorhanden | L | offen |

## Matrix F – Neustart (Restore erfordert Neustart)
Laut `docs/04-sicherheit-backup.md` erfordert der Austausch der laufenden DB einen Neustart; die API antwortet mit „Bitte erneut anmelden.“. Das tatsächliche Verhalten unter Windows ist ungeprüft.

| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-RS-01 | Backup mit Daten-Stand A vorhanden, danach Stand B erzeugt | Restore über Oberfläche (Bestätigung), Ergebnis lesen | Erfolgsmeldung mit Name des Sicherheits-Backups (`…-pre-restore.zip`). Bei Fehler: verständliche Meldung | S | offen |
| WIN-RS-02 | nach RS-01 | Ohne Neustart weiterarbeiten: Seiten öffnen, speichern | Dokumentieren, ob Anwendung konsistenten Stand zeigt oder Fehler wirft; ist ein Neustart zwingend? (Oberfläche sollte Neustart anfordern – Befund, falls nicht) | S, N | offen |
| WIN-RS-03 | nach RS-01 | Fenster schließen, Prozess wirklich beendet (Task-Manager), App neu starten, anmelden | Stand A sichtbar (inkl. Dokumente); Sitzung muss neu angemeldet werden | S | offen |
| WIN-RS-04 | wie RS-01 | Zweiter Neustart-Zyklus | Stabil, Daten identisch zu RS-03 | S | offen |
| WIN-RS-05 | Wiederherstellungspfad bei Fehlern | Restore mit fehlerhaftem Backup (Byte in ZIP verändern) | Ablehnung vor dem Austausch (`restore_failed`), aktueller Stand unverändert | S, L | offen |

## Matrix G – Backup und Restore
Code-Fakten (gelesen): Backup = ZIP (DB-Snapshot über SQLite-Backup-API, `documents/…`, `manifest.json` mit SHA-256); optional `.zip.enc` (AES-256-GCM, scrypt, Magic `LEVBKP01`, Passphrase ≥ 12 Zeichen); Restore erstellt vorher ein Sicherheits-Backup, entpackt in ein Temp-Verzeichnis **im Datenordner**, löscht `-wal`/`-shm`, kopiert die DB über die Live-Datei und benennt den Dokumentenordner um (`documents` → `documents.old`). Unter Windows mögliche Dateisperren sind **ungeprüft**.

| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-BR-01 | Testdaten + 2 Dokumente | Backup ohne Passphrase erstellen, „prüfen“ | Datei `leventum-backup-*.zip` in `backups`; Verify ok; ZIP in Explorer/7-Zip lesbar, enthält `manifest.json`, `database.sqlite3`, `documents/…` | S, H | offen |
| WIN-BR-02 | wie oben | Backup mit Passphrase (≥ 12 Zeichen) erstellen, prüfen | Datei `*.zip.enc`; unverschlüsselte Zwischendatei verschwindet; Verify ok; Datei nicht mit ZIP-Programm lesbar | S, H | offen |
| WIN-BR-03 | wie BR-02 | Verify/Restore mit falscher Passphrase, mit leerer Passphrase | Ablehnung („Falsche Passphrase …“/„Passphrase erforderlich“), aktueller Stand unverändert | S | offen |
| WIN-BR-04 | wie BR-02 | Passphrase mit Umlauten/Sonderzeichen (`Küchen-Pässwörd-2026!`), anderes Tastaturlayout beim Anlegen/Prüfen | Funktioniert reproduzierbar (UTF-8-Kodierung, Annahme) | S | offen |
| WIN-BR-05 | Backup existiert | Backup-Datei auf anderes Laufwerk/USB kopieren, im Datenordner `backups` ersetzen/platzieren, prüfen | Verify ok nach Kopie; bei Abweichung Hash vergleichen (`Get-FileHash`) | H | offen |
| WIN-BR-06 | Backup-Verzeichnis auf anderem Laufwerk konfiguriert (`LEVENTUM_BACKUP_DIR=D:\…`) | Backup erstellen | Datei liegt dort; Verify ok; Restore aus diesem Ordner möglich | S, L | offen |
| WIN-BR-07 | App läuft, Stand B; Backup Stand A | **Restore bei geöffneter Datenbank** (normaler Betrieb, Fenster offen, mehrere Seiten geöffnet) | Kernfall: Restore gelingt **oder** scheitert mit verständlicher Meldung ohne Halbzustand. Beobachten: `PermissionError`/`WinError 32` beim Überschreiben der DB-Datei oder beim Umbenennen von `documents`; HTTP-Status/Meldung (nicht-`BackupError`-Fehler werden vermutlich als HTTP 500 sichtbar – Annahme); Zustand danach: DB alt/neu? Dokumente alt/neu? | S, L, N | offen |
| WIN-BR-08 | wie BR-07, zusätzlich Dokumentordner im Explorer geöffnet / Datei im PDF-Reader geöffnet | Restore | Verhalten bei gesperrter Datei im Ordner `documents` dokumentieren (Umbenennen von `documents` schlägt unter Windows bei offenen Handles häufig fehl – Annahme); Halbzustand ausschließen: Sicherheits-Backup vorhanden und wiederherstellbar | S, L | offen |
| WIN-BR-09 | Defender/Indexierung aktiv | Restore mit großem Backup (> 500 MB Testdaten) | Verhalten/Dauer dokumentieren; keine Teilzustände | L | offen |
| WIN-BR-10 | Nach Restore (BR-07) | Sicherheits-Backup (`*-pre-restore.zip`) auflisten, prüfen, daraus Stand B wiederherstellen | Verify ok; Rückweg funktioniert | S | offen |
| WIN-BR-11 | nach Restore (unverschlüsselt und verschlüsselt je einmal) | Dokumente vergleichen: Anzahl, SHA-256 aller Dokumentdateien vor Backup vs. nach Restore (`Get-FileHash -Recurse`-Vergleich), „Datenprüfung“ in den Einstellungen und `verify-all` ausführen | Dokumente byte-identisch; Datenprüfung ohne neue Befunde; Beträge/Zahlen identisch | H, S | offen |
| WIN-BR-12 | Restore einer verschlüsselten Sicherung | Restore `.zip.enc` mit richtiger Passphrase | Entpackt in Temp-Ordner im Datenordner; Klartext-Kopie wird danach gelöscht (prüfen, dass keine `restore.zip`/Temp-Reste im Datenordner bleiben – Datenschutz) | L, N | offen |
| WIN-BR-13 | Backup während laufender Schreibvorgänge | Backup + gleichzeitig Zahlungen erfassen | Backup konsistent (Verify ok), keine Sperrfehler | L | offen |
| WIN-BR-14 | Wenig Speicherplatz (kleine VHD/Quota, nur Testumgebung) | Backup erstellen | Verständlicher Fehler; kein „gültiges“ unvollständiges Backup gelistet (`.part`) | L | offen |

## Matrix H – CSV-Bankimport
Code-Fakten (gelesen): `bank_parsers.py` probiert Kodierungen `utf-8-sig`, danach `cp1252`; Trennzeichen automatisch aus `; , Tab |` (häufigstes in Kopfzeile) oder explizit; Upload ≤ 5 MB. Vorschau schreibt nichts; Buchung nur mit `confirm: true`.

| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-CSV-01 | Testkonto, erfundene Buchungen | CSV UTF-8 **ohne** BOM mit `;` und Umlauten im Verwendungszweck | Vorschau korrekt, Umlaute lesbar | S | offen |
| WIN-CSV-02 | wie oben | UTF-8 **mit** BOM (z. B. Excel „CSV UTF-8“) | Erste Spaltenüberschrift ohne BOM-Zeichen erkannt, Vorschau korrekt | S | offen |
| WIN-CSV-03 | wie oben | ANSI/Windows-1252 (Notepad „ANSI“, Excel „CSV (Trennzeichen-getrennt)“) mit Umlauten und `€`/`ß` | Umlaute korrekt (Fallback cp1252), keine Mojibake | S | offen |
| WIN-CSV-04 | wie oben | Trennzeichen `,` / Tab / `|`; Dezimalkomma vs. Dezimalpunkt; Zeilenenden CRLF vs. LF | Vorschau korrekt oder verständliche Ablehnung; keine stille Fehlinterpretation von Beträgen | S | offen |
| WIN-CSV-05 | wie oben | Datei über den Windows-Dateidialog des Fensters (WebView2) wählen; Dateiname mit Umlauten/Leerzeichen | Dateiauswahl funktioniert im Fenster (W6) | S | offen |
| WIN-CSV-06 | wie oben | Fehlerhafte Datei (> 5 MB, > 20.000 Zeilen, Steuerzeichen, ungültiges Datum/IBAN) | Gesamte Datei wird abgelehnt, verständliche Meldung | S | offen |
| WIN-CSV-07 | wie oben | Dieselbe Datei zweimal importieren | Duplikaterkennung greift; keine doppelten Zahlungen; Buchung nur nach Bestätigung | S | offen |

## Matrix I – Sicherheit (Windows-spezifisch)
| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-SEC-01 | Server läuft | `netstat -ano -p TCP` (Port des Servers) | Listener ausschließlich `127.0.0.1:<Port>`, nie `0.0.0.0`/`[::]` | L | offen |
| WIN-SEC-02 | Server läuft, zweiter Rechner im selben Netz (oder zweite VM) | Von dort `http://<IP-des-Testrechners>:<Port>/api/v1/health` aufrufen | Keine Verbindung (Bindung nur lokal; zusätzlich Host-Header-Prüfung) | L | offen |
| WIN-SEC-03 | Erster Start der Python-Anwendung auf frischem Windows | Beobachten, ob **Windows-Firewall-Dialog** („Zugriff zulassen“) erscheint | Erwartung (Annahme): bei reiner Loopback-Bindung kein Dialog. Falls Dialog erscheint: Befund; **nicht** „Zulassen“ als Standardlösung dokumentieren, sondern Ursache klären | S | offen |
| WIN-SEC-04 | Firewall-Protokoll/Ressourcenmonitor | Während Betrieb ausgehende Verbindungen des Prozesses beobachten (Resource Monitor → Netzwerk, ggf. Wireshark nur auf Testsystem) | Keine ausgehenden Verbindungen durch die Anwendung (außer lokale Loopback) | S, N | offen |
| WIN-SEC-05 | Server läuft | `POST /api/v1/auth/login` ohne Header `X-Leventum-Client: 1` | HTTP 403 (CSRF-Schutz) | L | offen |
| WIN-SEC-06 | Server läuft | Request mit fremdem Host-Header (`Host: example.test`) an 127.0.0.1 | Abgelehnt (TrustedHost) | L | offen |
| WIN-SEC-07 | Zweites Windows-Konto, gleicher PC | Als anderer Nutzer `http://127.0.0.1:<Port>/` aufrufen (feste `--port`) | Erreichbar, aber nur nach Anmeldung nutzbar (Loopback ist PC-weit erreichbar – Restrisiko dokumentieren: Mehrbenutzer-PC/Terminalserver) | N | offen |
| WIN-SEC-08 | BitLocker-Status (`manage-bde -status` oder Einstellungen) | Status des Laufwerks mit dem Datenordner notieren | Dokumentation (W9): DB und Dokumente **unverschlüsselt**, Schutz nur über BitLocker/Windows-Konto; ohne BitLocker Hinweis an Anwender | S, N | offen |
| WIN-SEC-09 | Datenordner | Prüfen, ob Passwörter/Passphrasen/Tokens in Logdateien (`server-*.log`, Konsole) auftauchen | Keine Klartext-Secrets | L | offen |

## Matrix J – Installer (existiert nicht)
Ein Installer oder Build-Skript **existiert nicht** (siehe `docs/WINDOWS_BUILD_PLAN.md`, reiner Plan). Die folgenden Fälle sind Platzhalter für die Zeit nach einer Umsetzung; bis dahin **nicht anwendbar**, nicht „bestanden“.

| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-INS-01 | Installer-Artefakt liegt vor (nicht vorhanden) | Installation auf sauberer Windows-VM ohne Python/Node | Programm startet ohne vorinstalliertes Python; Datenordner `%LOCALAPPDATA%\Leventum` (nicht im Programmordner) | S | offen |
| WIN-INS-02 | wie oben, ohne WebView2-Runtime | Installation/Erststart | WebView2-Prüfung/-Installation wie im Plan; verständliche Meldung | S | offen |
| WIN-INS-03 | wie oben | Installation ohne Administratorrechte (falls Pro-Benutzer-Installation vorgesehen) | wie im Plan festgelegt | S | offen |
| WIN-INS-04 | wie oben | SmartScreen/Signaturprüfung | Verhalten mit/ohne Signatur dokumentieren | S | offen |
| WIN-INS-05 | wie oben | Frontend-Auslieferung und Migrationen aus dem Installationspaket (`frontend_dist`, `alembic`) | Oberfläche lädt; Migrationen laufen; keine Pfadfehler | L | offen |

## Matrix K – Deinstallation und Update (Daten bleiben)
Nur anwendbar, sobald ein Installer existiert. Bis dahin kann das Update-Verhalten teilweise mit Quellcode-Updates geprüft werden (WIN-PE-06).

| ID | Vorbedingung | Schritte | Erwartetes Ergebnis | Nachweis | Ergebnis |
|---|---|---|---|---|---|
| WIN-UPD-01 | Version N mit Testdaten, Datenordner-Hash notiert | Vor dem Update Backup (verschlüsselt und unverschlüsselt) erstellen und prüfen | Backup prüfbar; vor Migration vorhanden | H | offen |
| WIN-UPD-02 | wie oben | Update auf Version N+1 | Daten vollständig vorhanden; Schema-Revision erhöht; Dokumente unverändert (Hashes) | H, L | offen |
| WIN-UPD-03 | wie oben | Update mit fehlschlagender Migration (Testfall: künstlich) | Kein Datenverlust; Rückweg über Backup dokumentiert | L | offen |
| WIN-UPD-04 | Version N+1 | Deinstallation | Programmdateien entfernt; Datenordner `%LOCALAPPDATA%\Leventum` **bleibt** (Daten nie automatisch löschen) | S, N | offen |
| WIN-UPD-05 | nach Deinstallation | Neuinstallation | App findet vorhandenen Datenordner und Daten | S | offen |
| WIN-UPD-06 | Update während laufender Anwendung | Update/Installation ausführen, während App läuft | Installer erkennt laufende Instanz und bricht ab/fordert Schließen; keine Dateisperrfehler mit Halbzustand | S, N | offen |

## Abnahmetabelle „Freigabeblocker“
Diese Tests müssen **vor jeder Windows-Freigabe** den Status „bestanden“ (mit Nachweis im Ergebnisprotokoll) haben. Ein offener oder fehlgeschlagener Blocker verhindert die Aussage „unter Windows getestet/freigegeben“. Die Freigabe selbst ist eine menschliche Entscheidung.

| Blocker | Testfälle | Grund | Status |
|---|---|---|---|
| B1 Start im Fenster | WIN-ST-02, WIN-WV-01, WIN-WV-14, W1 | Ohne lauffähiges Fenster keine Desktop-Aussage | offen |
| B2 Datenerhalt | WIN-PE-01, WIN-PE-02, W2 | Datenverlust ist nicht akzeptabel | offen |
| B3 Datenordner/Pfade | WIN-FS-01, WIN-FS-02, WIN-FS-03 | Standardpfad und übliche Pfade müssen funktionieren | offen |
| B4 Upload/Download inkl. Integrität | WIN-UD-01, WIN-UD-03, WIN-UD-06, WIN-WV-10, WIN-WV-11, W4 | Dokumentverlust/-korruption; Download im WebView2 | offen |
| B5 Backup/Restore | WIN-BR-01, -02, -03, -07, -08, -10, -11, W5 | Kein Release ohne Backup-/Restore-Nachweis; Dateisperren-Risiko | offen |
| B6 Restore-Neustart | WIN-RS-01 … WIN-RS-03 | Ablauf unter Windows ungeprüft | offen |
| B7 Netzwerk/Sicherheit | WIN-SEC-01, WIN-SEC-02, WIN-SEC-04, WIN-SEC-05, WIN-SEC-09 | Lokale Bindung, keine ausgehenden Verbindungen, keine Secrets in Logs | offen |
| B8 BitLocker-Hinweis | WIN-SEC-08, W9 | Ehrliche Aussage zur Verschlüsselung | offen |
| B9 CSV-Import | WIN-CSV-01, -02, -03, -05, W6 | Umlaute/Kodierung bei Windows-Dateien | offen |
| B10 Bedienbarkeit/DPI | WIN-WV-03 … -05, WIN-WV-07, W3, W7 | Dialoge/Layout bei 100/125/150 % | offen |
| B11 Port/Mehrfachstart | WIN-ST-06, WIN-ST-07, W8 | Keine Datenbeschädigung bei zweiter Instanz | offen |
| B12 Installer/Update (nur wenn Installer ausgeliefert wird) | WIN-INS-01, WIN-INS-02, WIN-UPD-01 … WIN-UPD-05 | Daten nie überschreiben, Backup vor Migration | offen (Installer existiert nicht) |

Nicht-Blocker (zu dokumentieren, aber nicht freigabeentscheidend): WIN-WV-06 (Mehrmonitor), WIN-FS-05/-09/-12, WIN-PE-05, WIN-WV-13, WIN-FS-04 (nur wenn Gesamtpfad im Zielbetrieb kurz bleibt).

## Ergebnisprotokoll-Formular (je Testlauf eine Kopie ausfüllen)
```
Protokoll-ID:              WIN-RUN-JJJJMMTT-NN
Tester (Name/Rolle):       
Datum/Uhrzeit Start/Ende:  
Rechner (physisch/VM):     
Windows-Version/Build:     (winver)
Benutzerkontotyp:          (Standard/Administrator)
Anzeige (Skalierung, Monitore):  
WebView2-Runtime-Version:  (Edge-/WebView2-Version, wie ermittelt:            )
Python-Version:            
pywebview-Version:         (pip show pywebview)
Installationsart:          (pip install -e / pip install . / Installer, Version)
App-Version / Git-Commit:  (leventum.__version__ / git rev-parse --short HEAD)
Frontend-Build (Datum/Commit): 
Datenordner:               (Pfad; Testdaten ausschließlich erfunden: ja/nein)
Virenschutz/Defender:      (aktiv/Ausnahmen)
BitLocker:                 (ja/nein/Laufwerk)
Skriptlauf windows_smoke_test.ps1: (ja/nein; Ergebnisdatei: ; Exit-Code: )

Ergebnisse (je Testfall-ID):
| ID | Ergebnis (bestanden/fehlgeschlagen/nicht anwendbar/offen) | Nachweis (Dateiname/Hash) | Bemerkung |
|----|-----------------------------------------------------------|---------------------------|-----------|

Abweichungen / Befunde (ID, Beschreibung, Schwere, Reproduktion, an wen gemeldet):

Blocker-Status (B1–B12):   

Unterschrift/Freigabe durch Mensch (nur Entscheidung, kein Agent): 
```

## Build-Hinweis
Ein Installer (z. B. PyInstaller) ist nicht Teil dieses Stands und wurde nicht erprobt. Siehe `docs/WINDOWS_BUILD_PLAN.md` (Plan, nicht umgesetzt).

## Statushinweis dieser Ergänzung
Matrix, Freigabeblocker und Protokollformular sind **geplant/erstellt**, nicht ausgeführt; kein Eintrag ist „unter Windows getestet“. Erwartungen mit „Annahme“/„Vermutung“ stammen aus Quellcode-Lektüre unter Linux und sind **nicht belegt**. Das Review dieser Ergänzung durch eine unabhängige Person/Instanz steht aus.
