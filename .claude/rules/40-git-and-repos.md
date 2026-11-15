# Git und Repositories

- **Leventum** (`Wertcheck/Leventum-Verwaltungsprogramm`) ist das einzige Entwicklungsrepository. Entwicklungsbranch laut Sitzungsvorgabe (aktuell `claude/leventum-property-management-phase-a-f5kfyx`); auf keinen anderen Branch pushen.
- **Lexono** (`Wertcheck/Lexono`) ist **ausschließlich Lesereferenz**: keine Änderungen, Commits, Pushes, Branches, kein Kopieren von Secrets, Mandanten-/Personendaten oder Fachlogik. Klon nur flach und außerhalb des Leventum-Verzeichnisses. Vor Abschluss `git -C <lexono> status` prüfen (muss leer sein).
- Kein Pull Request, kein Push ohne ausdrücklichen Auftrag der Nutzerin/des Nutzers (Push auf den Entwicklungsbranch erfolgt nur im Rahmen eines erteilten Auftrags).
- Commit-Nachricht: kurze Zusammenfassung, Begründung, Trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` und `Claude-Session: <URL>`. Keine Modellkennung in Code/Kommentaren. Keine Secrets, keine echten Daten.
- Keine History-Umschreibung, keine leeren Commits, keine Tests deaktivieren, um CI zu „reparieren“.
- Vor Löschen/Überschreiben: Ziel ansehen. `git status` und `git diff --stat` vor jedem Commit.
