# 04 – Sicherheits- und Backupkonzept

## 1. Bedrohungsmodell (Einzelplatz, lokal)

| Risiko | Maßnahme | Status |
|---|---|---|
| Andere Prozesse/Websites greifen auf den lokalen Server zu | Bindung nur an `127.0.0.1`; `TrustedHost`-Prüfung (DNS-Rebinding); kein CORS; Pflicht-Header `X-Leventum-Client` bei schreibenden Requests (CSRF); Cookie `HttpOnly`, `SameSite=Strict` | implementiert/getestet |
| Ungeschützte Endpunkte | Alle Fach-Endpunkte hinter Auth-Dependency; Test, der **jede** registrierte Route auf Auth prüft | implementiert/getestet |
| Passwortdiebstahl | Argon2id, keine Klartextspeicherung, Mindestlänge 12, kein Standardpasswort (Erst-Einrichtung beim ersten Start) | implementiert/getestet |
| Brute Force | Sperre nach 5 Fehlversuchen für 5 Minuten, Audit-Eintrag | implementiert/getestet |
| Sitzungsdiebstahl | Zufälliges 256-Bit-Token, in DB nur als SHA-256-Hash, Ablauf (Standard 8 h inaktiv/absolut 24 h), Logout widerruft | implementiert/getestet |
| SQL-Injection | Ausschließlich parametrisierte SQLAlchemy-Abfragen | implementiert (Konvention) |
| Dateiupload (Phase E) | Allowlist Endungen + Magic-Byte-Prüfung, Größenlimit, zufällige Speicherschlüssel, Originalname nur als Metadatum, Pfad-Traversal-Schutz | Speicherschicht implementiert/getestet; Upload-Endpunkt Phase E |
| Zugriff auf Dokumente per URL | Keine statischen Datei-URLs; Download nur über authentifizierten Endpunkt (Phase E) | geplant |
| Nachträgliche Manipulation | Append-only-Audit auf Anwendungsebene; Finanzdaten per Storno | Audit implementiert; Finanzdaten Phase D |
| Geheimnisse im Code | Keine Secrets im Repo; Sessiontokens zufällig zur Laufzeit; `.env` in `.gitignore` | umgesetzt |
| Externe Verbindungen | Anwendung baut keine ausgehenden Verbindungen auf. Frontend lädt keine CDN-Ressourcen/Fonts (System-Schrift). | umgesetzt |

**Nicht durch die Anwendung lösbar** (Betriebsumgebung): Festplattenverschlüsselung → **BitLocker** aktivieren; Windows-Benutzerkonto mit Passwort; Datenverzeichnis (`%LOCALAPPDATA%\Leventum`) nur für das eigene Konto (Standard-ACL des Benutzerprofils). Die Datenbank selbst ist **nicht** verschlüsselt (SQLite ohne SQLCipher) – bewusst, siehe Offene Entscheidungen.

Bekannte Restrisiken: Wer Zugriff auf das entsperrte Windows-Konto hat, hat Zugriff auf Datenbankdatei und Dokumente. Malware im Benutzerkonto ist nicht abgewehrt. Argon2-Parameter sind Standardwerte der Bibliothek.

DSGVO: Datensparsamkeit (Geburtsdatum optional), Löschkonzept und Aufbewahrungsfristen sind **fachlich noch zu klären** (Offene Entscheidungen); es erfolgt keine rechtliche Bewertung durch die Software.

## 2. Berechtigungen
Rollen: admin, verwaltung, buchhaltung, objektbetreuung, lesend. Rechte sind Strings (`tenant:read`, `finance:write`, …), Zuordnung in `security/permissions.py`. Jede Route deklariert ihr Recht. In der ersten Version existiert nur `admin`.

## 3. Backup und Wiederherstellung

Ein Backup ist **ein ZIP-Archiv** mit:
- `manifest.json` (Format-Version, Zeitpunkt, Schema-Revision, Dateiliste mit SHA-256 und Größe)
- `database.sqlite3` (konsistenter Snapshot über die SQLite-Backup-API, nicht Datei-Kopie einer laufenden DB)
- `documents/…` (alle Dokumente des Dateispeichers)

Ablauf:
1. **Erstellen:** Snapshot der DB + Kopie der Dokumente → ZIP in Backup-Verzeichnis (konfigurierbar, Standard: `<data>/backups`; empfohlen zusätzlich externes Laufwerk).
2. **Prüfen (`verify`):** ZIP lesbar, Manifest vorhanden, alle SHA-256 stimmen, `PRAGMA integrity_check` der enthaltenen DB = ok.
3. **Wiederherstellen:** Backup wird zuerst geprüft; vor dem Überschreiben entsteht automatisch ein Sicherheits-Backup des Ist-Zustands; Wiederherstellung in ein temporäres Verzeichnis, Prüfung, dann Austausch. Bei Fehler bleibt der alte Stand erhalten.
4. **Automatik:** Zeitplan (täglich) – im Desktop-Betrieb beim App-Start geprüft („letztes Backup älter als N Stunden → Backup“), kein Hintergrunddienst nötig. Der geplante Dienst ist in Phase F zu bewerten; „zuverlässig umsetzbar“ ist auf einem Desktop nur beim laufenden Programm gewährleistet.
5. **Statusanzeige:** Zeitpunkt des letzten erfolgreichen Backups, Ergebnis der Prüfung, Warnung bei Alter > Schwelle.

Nicht implementiert (offen): Aufbewahrungsrotation, externes Ziel. Der Wiederherstellungs-Austausch der laufenden DB erfordert in Phase B einen Neustart der Anwendung.

## 4. Export/Migration (Serverumzug)
Geplant Phase F: Logischer Export (JSON/CSV je Tabelle + Dokumentenarchiv mit Manifest) und Import über ORM in PostgreSQL. Alembic-Schema-Revision im Manifest verhindert Import in falsche Schemastände.


## Ergänzung Phase D
* **Bankimport:** Es werden ausschließlich lokale Dateien verarbeitet; keine Zugangsdaten, keine Netzwerkzugriffe. Upload ≤ 5 MB, ≤ 20.000 Zeilen, Steuerzeichen werden entfernt, Beträge/IBAN/Datum streng validiert; fehlerhafte Dateien werden vollständig abgelehnt. Bankkonten speichern nur Name/IBAN als Kennung.
* **Bestätigungspflicht:** Eine Bankbuchung wird nur durch `POST …/confirm` mit `confirm: true` zur Zahlung (Test: ohne Flag HTTP 422, keine Zahlung).
* **Dokumente:** Download nur authentifiziert (`Content-Disposition: attachment`, `nosniff`); Typ/Größe/Magic-Bytes-Prüfung; zufällige Speicherschlüssel. Dokumente sind im Backup enthalten (bestehender Backup-Mechanismus).
* **Unveränderlichkeit:** Zahlungen, Zuordnungen, Kautionsbuchungen sind append-only/Storno; Audit für jeden Schritt. Schutz auf Anwendungsebene, nicht auf Datenbankebene.
* Mahnwesen: Es existiert kein Versandcode (E-Mail/Post).


## Ergänzung Master-Review (Stand dieses Berichts)
**Was verschlüsselt ist – und was nicht (ehrlich):**
| Objekt | Verschlüsselt? |
|---|---|
| Backup-Archiv, wenn mit Passphrase erstellt (`.zip.enc`) | **Ja** – AES-256-GCM, Schlüssel per scrypt aus der Passphrase; Passphrase (mind. 12 Zeichen) wird nicht gespeichert; falsche Passphrase/Manipulation → Entschlüsselung scheitert |
| Backup-Archiv ohne Passphrase | Nein |
| Laufende SQLite-Datenbank | **Nein** |
| Dokumente im Datenordner | **Nein** |
Schutz der laufenden Daten ist **nur** über BitLocker/Geräteverschlüsselung und das Windows-Benutzerkonto möglich. Die Anwendung darf daher nicht als „verschlüsselte Datenhaltung“ beschrieben werden.

**HTTP-Sicherheitsheader** (Test `test_l_security_backup.py`): `Content-Security-Policy` (nur eigene Ressourcen), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` für API-Antworten.
**Dokumentintegrität:** SHA-256 beim Speichern; Download und `POST /documents/{id}/verify` prüfen die Datei (409 `file_corrupt` / 404 `file_missing`, Audit-Eintrag). Endgültige Entfernung (`purge`) nur Administrator und erst nach Ablauf der Aufbewahrungsfrist (Einstellung `document_retention_days`, Standard 3650 Tage – **Annahme, nicht rechtlich geprüft**).
**Datenprüfung:** `GET /system/integrity` (Oberfläche: Einstellungen → Datenprüfung) meldet verwaiste Verknüpfungen, doppelte Vermietungseinheiten, überlappende Untermietverträge, Überbelegung und beschädigte Dokumente. Es verändert nichts.
**Restore-Drill:** automatisierter Test (Backup → Änderung → Wiederherstellung inkl. Dokumente → Neustart) sowie E2E-Ablauf 15 über die Oberfläche.
**Abhängigkeitsprüfung:** `npm audit` (Stand dieses Berichts): Produktivabhängigkeiten 2 Meldungen mittlerer Schwere (react-router); weitere 6 betreffen nur Entwicklungswerkzeuge (vitest/esbuild/tinypool). Es wurde bewusst **kein** `npm audit fix --force` ausgeführt (Major-Upgrades ungetestet). Für Python wurde kein Audit-Werkzeug ausgeführt (`pip-audit` nicht installiert) – **nicht geprüft**.
