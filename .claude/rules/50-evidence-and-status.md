# Evidenz und Statusstufen

Jede Aussage über Fortschritt trägt genau eine dieser Stufen (strikt trennen, nie aufwerten):
**Geplant · Implementiert · Automatisiert getestet · Manuell getestet · Unter Windows getestet · Unabhängig geprüft · Freigegeben.**
- „Automatisiert getestet“ nur mit tatsächlich ausgeführtem Befehl und Ergebnis (Anzahl bestanden/fehlgeschlagen, Datum/Stand). Nicht ausgeführt → „nicht getestet“.
- „Unabhängig geprüft“ nur, wenn Prüfer ≠ Autor (anderer Agent mit eigenem Kontext **oder** Mensch) und die Prüfung dokumentiert ist. Ein Agent erklärt seine eigene Arbeit nie als unabhängig geprüft.
- „Unter Windows getestet“ nur nach echtem Windows-Lauf (`docs/WINDOWS_TESTPLAN.md`); bisher **nicht** erfolgt.
- Grüne Tests ≠ produktionsreif. Datensicherheit, Wiederherstellbarkeit, Finanzkorrektheit und Windows-Kompatibilität werden **separat** belegt.
- Keine erfundenen Implementierungsstände, Testergebnisse, Dateien, Endpunkte. Erst lesen/ausführen, dann behaupten. Sichtbare Bedienelemente ohne echte Funktion gelten nicht als erledigt.
- Lange Backend-Suite (~2 min) im Hintergrund starten; Ausgabedatei vor dem Warten löschen (sonst alte Ergebnisse).
