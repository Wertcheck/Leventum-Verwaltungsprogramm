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

Nicht implementiert (offen): Verschlüsselung der Backups, Aufbewahrungsrotation, externes Ziel. Der Wiederherstellungs-Austausch der laufenden DB erfordert in Phase B einen Neustart der Anwendung.

## 4. Export/Migration (Serverumzug)
Geplant Phase F: Logischer Export (JSON/CSV je Tabelle + Dokumentenarchiv mit Manifest) und Import über ORM in PostgreSQL. Alembic-Schema-Revision im Manifest verhindert Import in falsche Schemastände.
