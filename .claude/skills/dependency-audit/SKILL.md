---
name: dependency-audit
description: Abhängigkeitsprüfung (npm, Python) mit ehrlicher Berichterstattung. Verwenden vor Releases, bei neuen/aktualisierten Paketen.
---

# Skill: dependency-audit

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Bekannte Schwachstellen erkennen, bewerten und berichten, ohne ungetestete Major-Upgrades.

## 2. Einsatzbedingungen
- Neue Abhängigkeit; Release; regelmäßig.

## 3. Fachliche Grundlagen
Frontend: `cd frontend && npm audit` (und `--omit=dev`). Python: Abhängigkeiten in `backend/pyproject.toml`; ein Python-Audit-Werkzeug (z. B. `pip-audit`) ist **in der Umgebung bisher nicht installiert** (nicht geprüft).

## 4. Arbeitsanweisungen
1. `npm audit` voll und `--omit=dev` ausführen, Produktiv- von Dev-Funden trennen. 2. Python-Werkzeug verfügbar? Wenn nein: ‚nicht geprüft‘ berichten. 3. Fixes nur mit Tests; kein `--force` ohne Freigabe. 4. Neue Abhängigkeit: Lizenz, Pflege, Netzwerkverhalten (keine Telemetrie), Notwendigkeit.

## 5. Verbindliche Regeln
- Kein `npm audit fix --force` ohne Test und Freigabe.
- Keine Abhängigkeit mit ausgehender Verbindung/Telemetrie.

## 6. Typische Fehler
Dev-Funde als Produktivrisiko darstellen (oder umgekehrt); Audit nicht ausgeführt, aber ‚sauber‘ berichtet.

## 7. Qualitätskriterien
Befundzahlen mit Datum; getrennt Produktiv/Dev.

## 8. Erforderliche Tests
Nach Updates: volle Backend-/Frontend-Suite + E2E.

## 9. Übergabekriterien
Auditergebnis, Entscheidung (Upgrade/Zurückstellung mit Begründung).

## 10. Grenzen und Eskalationsfälle
Eskalation: Major-Upgrade (z. B. react-router), kritische Schwachstelle ohne Fix.
