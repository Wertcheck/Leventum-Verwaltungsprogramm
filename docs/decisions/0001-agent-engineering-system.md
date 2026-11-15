# 0001 – Agent Engineering System (native Claude-Code-Struktur)
Status: akzeptiert (durch Auftrag der Eigentümerin/des Eigentümers; nicht unabhängig geprüft) · Datum: 2026-11-15

**Kontext.** Leventum soll dauerhaft mit spezialisierten Agenten weiterentwickelt werden. Lexono (read-only Referenz) nutzt Rollen-/Skill-Dateien ohne Claude-Code-Format und wachsende Freitext-Logs (siehe `docs/AGENT_ARCHITECTURE_COMPARISON.md`).
**Entscheidung.** Native Struktur `CLAUDE.md` + `.claude/{agents,skills,rules}`; Orchestrator = Hauptsitzung; Review-Matrix, Dateibesitz, Übergabeformat; Selbstprüfung per Skript; Entscheidungen als einzelne ADR-Dateien.
**Folgen.** Agenten werden erst nach Sitzungsneustart als Typen geladen; Parallelität bleibt Verfahrensregel; Pflege der Dateien erfolgt über den Orchestrator.
**Alternativen.** 1:1-Übernahme der Lexono-Struktur (verworfen: nicht delegierbar, wächst unbegrenzt); ein einzelner Riesen-Prompt (verworfen: nicht modular).
