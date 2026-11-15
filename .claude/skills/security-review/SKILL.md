---
name: security-review
description: Sicherheitsprüfung von Änderungen: Authentifizierung, Autorisierung, Header, Upload, Audit, Secrets, Fehlermeldungen. Verwenden bei jeder sicherheitsrelevanten Änderung und vor Releases.
---

# Skill: security-review

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Prüfen, dass die Sicherheits-Baseline nicht verschlechtert wird, mit Beweisen statt Annahmen.

## 2. Einsatzbedingungen
- Änderungen an `security/*`, `main.py` (Middleware), Auth/Sitzung, Rechten, Upload/Download, Backup, neuen Routen.

## 3. Fachliche Grundlagen
Baseline (`30-security-privacy.md`, `docs/04-sicherheit-backup.md`): Bindung 127.0.0.1, `X-Leventum-Client`, Argon2id, Sitzungstoken-Hash, Brute-Force-Sperre, Rechtematrix, CSP/nosniff/XFO/Referrer/no-store, Dateiprüfung, Audit append-only.

## 4. Arbeitsanweisungen
1. Diff gegen Checkliste: Secrets, Logs, Auth/Recht je Route, CSRF-Äquivalent (Header), Upload/Pfad, Fehlermeldungen, Header, Debug, externe Requests. 2. Je betroffenem Punkt Test oder Befehl als Beweis suchen/verlangen. 3. Befund mit Schweregrad, Beleg, Empfehlung. 4. Veto aussprechen, wenn Baseline sinkt.

## 5. Verbindliche Regeln
- Veto bei Baseline-Verschlechterung; Aufheben nur durch den Menschen.
- Keine Secrets/echten Daten in Befunden.
- Prüfer ändert keinen Code.

## 6. Typische Fehler
Mechanismus ‚offensichtlich korrekt‘ annehmen; nur Hauptpfad prüfen; Rechte nur im Frontend; Tracebacks in Antworten.

## 7. Qualitätskriterien
Jeder Befund belegt; Baseline-Tests bleiben grün.

## 8. Erforderliche Tests
`test_auth_security.py` (alle Routen), `test_l_security_backup.py`, `test_d_deposits_documents.py`.

## 9. Übergabekriterien
Befundliste mit Schweregrad, Veto-Entscheidung, nötige Tests.

## 10. Grenzen und Eskalationsfälle
Eskalation: Kryptografie-Designänderungen, Schlüsselmanagement, Auth-Umbau, rechtliche Datenschutzfragen.
