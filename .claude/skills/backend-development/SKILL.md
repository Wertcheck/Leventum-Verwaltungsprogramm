---
name: backend-development
description: "Backend-Entwicklung in Leventum (FastAPI, SQLAlchemy 2, Pydantic, Services). Verwenden für neue/geänderte Endpunkte, Services, Validierung und Fehlerbehandlung."
---

# Skill: backend-development

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Backend-Änderungen konsistent mit bestehenden Mustern, sicher und testbar umsetzen.

## 2. Einsatzbedingungen
- Neue oder geänderte Endpunkte, Services, Schemas.
- Fehler in Geschäftslogik oder API-Verhalten.

## 3. Fachliche Grundlagen
- Router `backend/leventum/api/*` (Rechte pro Route über `require(...)`, `db.commit()` in der API), Services `backend/leventum/services/*` (werfen `ServiceError`/`NotFound` mit Code), Schemas `api/schemas.py` (Pydantic, `extra=forbid`), Serialisierung `ser/js`. Geld: Decimal/`Money`.
- Audit: `audit.record`, Änderungen mit `audit.diff` (Vorher/Nachher, sensible Felder maskiert).

## 4. Arbeitsanweisungen
1. Verwandte Services/Tests lesen. 2. Logik im Service, Route dünn. 3. Eingaben in Schema validieren (Grenzen, Literale). 4. Fehler als `ServiceError(code, text, status)`; keine rohen Exceptions nach außen. 5. Audit-Eintrag für schreibende Fachaktionen. 6. Test schreiben (`api-testing`), Doku `docs/03-api-module.md` ergänzen. 7. Volle Backend-Suite im Hintergrund.

## 5. Verbindliche Regeln
- Finanzinvarianten (`10-finance-invariants.md`) bleiben unberührt; Änderungen daran nur mit Freigabe.
- Jede Route hinter Auth + Recht; neue Rechte in `security/permissions.py` und Rechtematrix-Test.
- Keine `float`-Rechnung mit Geld; keine Commits im Service.
- Zentrale Definitionen wiederverwenden.

## 6. Typische Fehler
- Logik in der Route statt im Service.
- Float/String-Mischformen bei Geld.
- Rechte vergessen; ungeprüfte Dateinamen/Pfade.
- Sitzungscache nach Raw-SQL (`expire_all`).
- Erwartungswerte in Tests hartcodiert statt fachlich berechnet.

## 7. Qualitätskriterien
Route ≤ ~15 Zeilen Logik; Fehlercodes stabil; Test beweist Verhalten inkl. Fehlerfall und Recht; keine neue N+1-Abfrage.

## 8. Erforderliche Tests
`cd backend && python -m pytest -q` (voll); betroffene Testdatei isoliert für schnelles Feedback; neue Tests für Erfolg, Validierungsfehler, fehlendes Recht.

## 9. Übergabekriterien
Übergabeformat; Dateiliste; Endpunkt-Änderungen mit Beispielanfrage/-antwort; Hinweise auf Pflichtreviews (Finanzen → Domain & Finance + QA).

## 10. Grenzen und Eskalationsfälle
Eskalation bei: Änderung an Modellen/Finanzservices/Sicherheit, Breaking-API-Änderung, fachlicher Unklarheit.
