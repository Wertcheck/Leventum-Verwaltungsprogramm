---
name: release-management
description: Release-Vorbereitung und -Bericht: Versionsstand, Migrationen, Backup vor Update, Testnachweise, Einschränkungen. Verwenden vor jedem Release/Abschlussbericht.
---

# Skill: release-management

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Releases nachvollziehbar, mit Nachweisen und ehrlichen Einschränkungen vorbereiten.

## 2. Einsatzbedingungen
- Release-Kandidat; Abschluss einer Phase.

## 3. Fachliche Grundlagen
Version in `backend/pyproject.toml`; Migrationen `backend/alembic/versions`; Berichte `docs/ABSCHLUSSBERICHT_*.md`; Statusstufen aus `50-evidence-and-status.md`. Ein Installer/Build-Skript für Windows existiert **nicht**.

## 4. Arbeitsanweisungen
1. Git-Status sauber, Branch korrekt. 2. Volle Tests + E2E + Responsive. 3. Migration auf Altdaten getestet, Backup vor Update. 4. Dependency-Audit. 5. Windows-Status ehrlich. 6. Release-Bericht mit getrennten Statusstufen, Einschränkungen und Risiken. 7. Commit/Push nur auf Auftrag.

## 5. Verbindliche Regeln
- Nicht ‚produktionsreif‘ nennen, nur weil Tests grün sind.
- Kein Release ohne Backup-/Restore-Nachweis.

## 6. Typische Fehler
Release-Bericht ohne Testausgabe; Einschränkungen verschwiegen; Version nicht erhöht.

## 7. Qualitätskriterien
Jede Zeile im Bericht mit Beleg; Statusstufen getrennt.

## 8. Erforderliche Tests
Alle Suiten laut `regression-testing`; Restore-Drill.

## 9. Übergabekriterien
Release-Checkliste ausgefüllt, Bericht erstellt.

## 10. Grenzen und Eskalationsfälle
Eskalation: Freigabe/Go-Live-Entscheidung ist menschlich.
