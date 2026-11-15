---
name: backup-restore
description: Backup/Restore inkl. Verschlüsselung und Restore-Drill. Verwenden bei Änderungen an `services/backup*.py`, Datenpfaden, Dokumentenspeicher, Migrationen und vor Releases.
---

# Skill: backup-restore

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Wiederherstellbarkeit nachweisen statt behaupten.

## 2. Einsatzbedingungen
- Änderung am Backup, Speicherformat, Schema oder Dokumentenspeicher; Release-Vorbereitung.

## 3. Fachliche Grundlagen
Backup = ZIP (`manifest.json` mit SHA-256, `database.sqlite3` per SQLite-Backup-API, `documents/`); optional `.zip.enc` (AES-256-GCM, scrypt, Passphrase ≥ 12, nicht gespeichert). Restore: vorher Sicherheits-Backup, Wiederherstellung in Temp, Prüfung, Austausch, Neustart nötig.

## 4. Arbeitsanweisungen
1. Backup erstellen (+ verschlüsselt), `verify` ausführen. 2. Daten ändern. 3. Restore, dann Daten und Dokumente vergleichen (Hashes). 4. Falsche Passphrase/Manipulation → Fehler erwartet. 5. Schema-Revision im Manifest bei Migration beachten. 6. Windows-Verhalten (Dateisperren) separat — nicht aus Linux ableiten.

## 5. Verbindliche Regeln
- Verschlüsselungsstatus ehrlich: nur Backups.
- Restore nie ohne Sicherheits-Backup.
- Passphrase nie loggen/speichern.

## 6. Typische Fehler
Backup nur ‚erstellt‘, nie wiederhergestellt; Dokumente fehlen im Restore; alter Sitzungs-/DB-Handle nach Restore.

## 7. Qualitätskriterien
Restore-Drill besteht inkl. Dokumente; Integritätsprüfung nach Restore sauber.

## 8. Erforderliche Tests
`test_backup_migrations.py`, `test_l_security_backup.py`, E2E 12–15.

## 9. Übergabekriterien
Drill-Protokoll mit Befehlen/Ergebnissen; Status unter Windows ‚nicht getestet‘.

## 10. Grenzen und Eskalationsfälle
Eskalation: Formatänderung des Backups, Schlüsselableitung, Aufbewahrungskonzept.
