#!/usr/bin/env python3
"""Selbstprüfung des Leventum-Agentensystems (.claude/agents, .claude/skills, .claude/rules, CLAUDE.md).

Prüft Struktur, Pflichtabschnitte, Skill-Verweise, Werkzeugzuordnung und Pfadverweise. Ändert nichts.
Aufruf: python scripts/validate_agent_system.py   (Exit-Code 0 = keine Fehler)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # ohne PyYAML kann das Frontmatter (Listen/Hooks) nicht geprüft werden – lieber abbrechen als still weniger prüfen
    sys.exit("FEHLER: PyYAML fehlt (pip install pyyaml) – Validierung nicht möglich")

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_AGENTS = ["independent-reviewer", "lead-architect", "backend-engineer", "frontend-ui-engineer", "domain-finance-engineer", "security-privacy-engineer",
                   "qa-test-engineer", "database-architect", "windows-release-engineer", "documentation-engineer"]
REQUIRED_SKILLS = ["architecture-review", "backend-development", "frontend-development", "ui-ux-review", "financial-calculations", "rental-contract-domain",
                   "operating-cost-accounting", "database-migrations", "data-integrity-review", "security-review", "privacy-review", "backup-restore",
                   "dependency-audit", "api-testing", "e2e-testing", "regression-testing", "windows-desktop-qa", "release-management", "technical-documentation"]
SKILL_SECTIONS = ["Zweck", "Einsatzbedingungen", "Fachliche Grundlagen", "Arbeitsanweisungen", "Verbindliche Regeln", "Typische Fehler", "Qualitätskriterien",
                  "Erforderliche Tests", "Übergabekriterien", "Grenzen und Eskalationsfälle"]
AGENT_SECTIONS = ["Verantwortung", "Skills", "Verbindliche Regeln", "Review-Pflichten", "Übergabe", "Grenzen und Eskalation"]
RULES = ["00-domain-rent-to-rent.md", "10-finance-invariants.md", "20-data-and-migrations.md", "30-security-privacy.md", "40-git-and-repos.md",
         "50-evidence-and-status.md", "60-collaboration.md"]
VALID_TOOLS = {"Read", "Grep", "Glob", "Bash", "Edit", "Write", "Agent", "WebFetch", "WebSearch", "NotebookEdit"}
ERRORS: list[str] = []
WARN: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        err(f"{path.relative_to(ROOT)}: Frontmatter fehlt")
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        err(f"{path.relative_to(ROOT)}: Frontmatter ist kein gültiges YAML ({e})")
        return {}, m.group(2)
    return fm, m.group(2)


def check_agents() -> dict[str, dict]:
    found = {}
    d = ROOT / ".claude" / "agents"
    files = sorted(d.glob("*.md"))
    names = [f.stem for f in files]
    for need in REQUIRED_AGENTS:
        if need not in names:
            err(f"Agent fehlt: {need}")
    for f in files:
        fm, body = frontmatter(f)
        rel = f.relative_to(ROOT)
        if fm.get("name") != f.stem:
            err(f"{rel}: name '{fm.get('name')}' ≠ Dateiname")
        if len(fm.get("description", "")) < 80:
            err(f"{rel}: description fehlt/zu kurz (Delegationsentscheidung hängt daran)")
        tools = {t.strip() for t in str(fm.get("tools", "")).split(",") if t.strip()}
        denied = {t.strip() for t in str(fm.get("disallowedTools", "")).split(",") if t.strip()}
        if not tools:
            err(f"{rel}: tools fehlen")
        for t in (tools | denied) - VALID_TOOLS:
            err(f"{rel}: unbekanntes Werkzeug {t}")
        if f.stem == "lead-architect":
            if "Agent" not in tools:
                err(f"{rel}: Orchestrator braucht das Agent-Werkzeug")
        else:
            if "Agent" in tools:
                err(f"{rel}: nur der Orchestrator darf Agent in tools haben")
            if "Agent" not in denied:
                err(f"{rel}: disallowedTools muss Agent enthalten (Delegation nur durch den Orchestrator, Verschachtelung ausgeschlossen)")
        if f.stem == "security-privacy-engineer":
            if tools != {"Read", "Grep", "Glob"}:
                err(f"{rel}: Sicherheitsprüfer darf NUR Read, Grep, Glob haben (kein Bash/Edit/Write), ist: {sorted(tools)}")
            if not {"Bash", "Edit", "Write", "NotebookEdit"} <= denied:
                err(f"{rel}: disallowedTools muss Bash, Edit, Write, NotebookEdit enthalten")
        if f.stem == "independent-reviewer-static":
            if tools != {"Read", "Grep", "Glob"}:
                err(f"{rel}: statischer Reviewer darf NUR Read, Grep, Glob haben (kein Bash/Edit/Write), ist: {sorted(tools)}")
            if not {"Bash", "Edit", "Write", "NotebookEdit", "Agent"} <= denied:
                err(f"{rel}: disallowedTools muss Bash, Edit, Write, NotebookEdit, Agent enthalten")
        if f.stem == "independent-reviewer":
            if tools & {"Edit", "Write", "NotebookEdit"} or not {"Edit", "Write", "NotebookEdit", "Agent"} <= denied:
                err(f"{rel}: Reviewer darf keine Schreibwerkzeuge haben (tools/disallowedTools prüfen)")
            hooks = json.dumps(fm.get("hooks", {}))
            if "Bash" in tools and "ro_guard.py" not in hooks:
                err(f"{rel}: Bash nur zusammen mit dem ro_guard-Hook erlaubt")
            if "ro_guard.py" in hooks and "mcp__" not in hooks:
                err(f"{rel}: Hook-Matcher muss mcp__.* abdecken (MCP-Werkzeuge sperren)")
            if "ro_guard.py" in hooks and "python3 -I" not in hooks:
                err(f"{rel}: Hook-Kommando muss `python3 -I` nutzen (isolierter Modus: keine Modul-Schatten aus .claude/hooks, keine PYTHON*-Variablen)")
            if "Bash" in tools and "|| exit 2" not in hooks:
                err(f"{rel}: Hook-Befehl muss mit '|| exit 2' enden – sonst blockiert ein fehlendes python3 (Exit 127) NICHT (Review-Befund H1)")
        if "Bash" in tools and f.stem == "documentation-engineer":
            err(f"{rel}: documentation-engineer braucht kein Bash")
        for sec in AGENT_SECTIONS:
            if not re.search(rf"^## {re.escape(sec)}", body, re.M):
                err(f"{rel}: Abschnitt fehlt: {sec}")
        skills = re.findall(r"`\.claude/skills/([a-z0-9-]+)/SKILL\.md`", body)
        if not skills:
            err(f"{rel}: keine Skills referenziert")
        for s in skills:
            if not (ROOT / ".claude" / "skills" / s / "SKILL.md").exists():
                err(f"{rel}: Skill existiert nicht: {s}")
        fm_skills = fm.get("skills") or []
        if sorted(fm_skills) != sorted(skills):
            err(f"{rel}: Frontmatter-skills {sorted(fm_skills)} ≠ im Text referenzierte Skills {sorted(skills)} (Skills werden nur vorgeladen, wenn sie im Frontmatter stehen)")
        found[f.stem] = {"tools": tools, "skills": set(skills)}
    return found


def check_skills(agents: dict[str, dict]) -> None:
    d = ROOT / ".claude" / "skills"
    names = sorted(p.name for p in d.iterdir() if p.is_dir())
    for need in REQUIRED_SKILLS:
        if need not in names:
            err(f"Skill fehlt: {need}")
    used = set().union(*(a["skills"] for a in agents.values())) if agents else set()
    for n in names:
        f = d / n / "SKILL.md"
        if not f.exists():
            err(f"{n}: SKILL.md fehlt")
            continue
        fm, body = frontmatter(f)
        rel = f.relative_to(ROOT)
        if fm.get("name") != n:
            err(f"{rel}: name ≠ Verzeichnis")
        if len(fm.get("description", "")) < 60:
            err(f"{rel}: description zu kurz")
        heads = re.findall(r"^## (\d+)\. (.+)$", body, re.M)
        if [h[1] for h in heads] != SKILL_SECTIONS or [int(h[0]) for h in heads] != list(range(1, 11)):
            err(f"{rel}: Pflichtabschnitte 1–10 fehlen/abweichend: {[h[1] for h in heads]}")
        for sec, nxt in zip(SKILL_SECTIONS, SKILL_SECTIONS[1:] + [None]):
            m = re.search(rf"^## \d+\. {re.escape(sec)}\n(.*?)(?=^## \d+\.|\Z)", body, re.S | re.M)
            if m and len(m.group(1).strip()) < 25:
                err(f"{rel}: Abschnitt '{sec}' praktisch leer")
        if n not in used:
            err(f"{n}: wird von keinem Agenten verwendet")
    shared = [n for n in names if sum(n in a["skills"] for a in agents.values()) > 1]
    print(f"Skills mit Mehrfachnutzung durch Agenten: {len(shared)} von {len(names)}")


PATH_RE = re.compile(r"`([A-Za-z0-9_./\-]+\.(?:md|py|cjs|ts|tsx|json|ini|toml|tsx))`")
IGNORE = ("NNNN", "/tmp/", "tests/test_", "docs/decisions/NNNN")


def check_paths() -> None:
    targets = [ROOT / "CLAUDE.md", *sorted((ROOT / ".claude").rglob("*.md")), *sorted((ROOT / "docs").glob("AGENT_*.md"))]
    n = 0
    for f in targets:
        if not f.exists():
            err(f"{f.relative_to(ROOT)} fehlt")
            continue
        for tok in PATH_RE.findall(f.read_text(encoding="utf-8")):
            if "/" not in tok or any(i in tok for i in IGNORE) or tok.startswith("."):
                if not tok.startswith(".claude/"):
                    continue
            n += 1
            cands = [ROOT / tok, ROOT / "backend" / tok, ROOT / "backend" / "leventum" / tok, ROOT / "backend" / "leventum" / "services" / tok,
                     ROOT / "backend" / "tests" / tok, ROOT / "frontend" / tok, ROOT / "frontend" / "src" / tok, ROOT / "docs" / tok]
            if not any(c.exists() for c in cands):
                err(f"{f.relative_to(ROOT)}: Verweis ins Leere: {tok}")
    print(f"Pfadverweise geprüft: {n}")


def check_rules_and_misc() -> None:
    for r in RULES:
        if not (ROOT / ".claude" / "rules" / r).exists():
            err(f"Regeldatei fehlt: {r}")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8") if (ROOT / "CLAUDE.md").exists() else ""
    for must in ("Lexono", "read-only", "Windows", "Statusstufen", "Orchestr"):
        if must.lower() not in claude.lower():
            err(f"CLAUDE.md erwähnt nicht: {must}")
    for dup in (ROOT / ".claude" / "CLAUDE.md", ROOT / "AGENTS.md"):
        if dup.exists():
            err(f"Doppelte/widersprüchliche Konfiguration: {dup.relative_to(ROOT)}")
    secret = re.compile(r"(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ANTHROPIC_API_KEY\s*=)")
    for f in [ROOT / "CLAUDE.md", *(ROOT / ".claude").rglob("*"), *(ROOT / "docs").glob("AGENT_*.md")]:
        if f.is_file() and secret.search(f.read_text(encoding="utf-8", errors="ignore")):
            err(f"{f.relative_to(ROOT)}: mögliches Secret")


def check_isolation() -> None:
    """Lexono-Schutz, Read-only-Runner und Hook müssen vorhanden und konsistent sein."""
    sp = ROOT / ".claude" / "settings.json"
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
    except Exception as e:
        err(f".claude/settings.json nicht lesbar ({e})")
        return
    deny = st.get("permissions", {}).get("deny", [])
    if not any(d.startswith("Edit(") and "lexono" in d for d in deny):
        err("settings.json: Edit-Deny-Regel für Lexono fehlt")
    for d in deny:  # Claude Code wertet nur Edit(...) für Dateipfade aus; Write(...)/NotebookEdit(...) werden gemeldet und ignoriert
        if d.startswith(("Write(", "NotebookEdit(")):
            err(f"settings.json: Deny-Regel '{d}' wird von Claude Code nicht ausgewertet – Edit(...) verwenden")
    if not any("lexono" in x for x in st.get("claudeMdExcludes", [])):
        err("settings.json: claudeMdExcludes für Lexono fehlt (fremde Projektregeln dürfen nicht in den Kontext)")
    for rel, need_exec in ((".claude/hooks/ro_guard.py", False), ("scripts/ro_run.sh", True)):
        fp = ROOT / rel
        if not fp.exists():
            err(f"{rel} fehlt")
        elif need_exec and not os.access(fp, os.X_OK):
            err(f"{rel} ist nicht ausführbar")


def main() -> int:
    agents = check_agents()
    check_skills(agents)
    check_rules_and_misc()
    check_isolation()
    check_paths()
    print(f"Agenten: {len(agents)} · Skills: {len(list((ROOT / '.claude' / 'skills').iterdir()))} · Regeln: {len(list((ROOT / '.claude' / 'rules').glob('*.md')))}")
    for w in WARN:
        print("WARNUNG:", w)
    for e in ERRORS:
        print("FEHLER:", e)
    print("OK – keine Fehler" if not ERRORS else f"{len(ERRORS)} Fehler")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())
