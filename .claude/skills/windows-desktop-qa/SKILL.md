---
name: windows-desktop-qa
description: Windows-Desktop-Prüfung (pywebview/WebView2, Dateisystem, Downloads, DPI). Verwenden bei Änderungen an `desktop.py`, Datenpfaden, Downloads, und für jeden Windows-Statusbericht.
---

# Skill: windows-desktop-qa

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Windows-Verhalten nur nach echtem Windows-Lauf bewerten; ansonsten ehrlich ‚nicht getestet‘.

## 2. Einsatzbedingungen
- Desktop-/Installer-Änderungen; Release-Vorbereitung; Windows-Fragen.

## 3. Fachliche Grundlagen
`backend/leventum/desktop.py` (Server auf 127.0.0.1 + `webview`, `ALLOW_DOWNLOADS` in try/except), `docs/WINDOWS_TESTPLAN.md` (W1–W9, alle offen). Chromium-E2E ersetzt **keinen** Windows-Test.

## 4. Arbeitsanweisungen
1. Ist ein Windows-Rechner mit WebView2 verfügbar? Nein → nichts als getestet berichten, Testplan pflegen. 2. Ja: W1–W9 abarbeiten (Start, Neustart/Daten, Dialoge, Downloads, Backup/Restore, CSV mit ANSI/UTF-8, Fenstergrößen/DPI 125–150 %, belegter Port, BitLocker-Hinweis). 3. Ergebnisse mit Datum/Tester/Version eintragen. 4. Fehler als Befund an Besitzer.

## 5. Verbindliche Regeln
- Status ‚Unter Windows getestet‘ nur nach realem Lauf.
- Keine Vermutungen über WebView2-Verhalten als Fakt.

## 6. Typische Fehler
Linux-Chromium-Ergebnis als Windows-Ergebnis ausgeben; Pfad-/Dateisperren ignorieren.

## 7. Qualitätskriterien
Jeder Testfall mit Ergebnis, Umgebung, Version.

## 8. Erforderliche Tests
Windows-Testplan (manuell/skriptbar); keine automatisierte Windows-Suite vorhanden.

## 9. Übergabekriterien
Ausgefüllter Testplan; offene Fehler; Empfehlung.

## 10. Grenzen und Eskalationsfälle
Eskalation: Installer/Signatur/Updates (nicht vorhanden), Datenverlustrisiko beim Update.
