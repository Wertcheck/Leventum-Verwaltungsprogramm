#!/usr/bin/env python3
"""Dateimengen-Kontrolle für delegierte Agentenarbeit (Verfahren aus .claude/rules/60-collaboration.md, hier maschinell prüfbar).

Claude Code kennt KEINE technische Sperre gegen parallele Schreibzugriffe auf dieselbe Datei. Dieses Skript erkennt Verstöße NACHTRÄGLICH:
  1. vor der Delegation:   python scripts/check_file_set.py snapshot --out /pfad/snap.json
  2. nach dem Agentenlauf:  python scripts/check_file_set.py check --snapshot /pfad/snap.json --allowed 'backend/leventum/services/*.py' --allowed 'backend/tests/test_x.py'
Gemeldet werden alle seit dem Snapshot neu angelegten oder inhaltlich geänderten Dateien (tracked + untracked), die auf KEINES der --allowed-Muster passen.
Bei parallelen Agenten die Muster ALLER gleichzeitig laufenden Agenten angeben (sonst meldet das Skript deren Dateien als Verstoß) und zusätzlich mit
`overlap --set A=glob,glob --set B=glob` prüfen, ob sich Dateimengen überschneiden (dann darf nicht parallel gearbeitet werden).
Exit-Code 0 = keine Verstöße, 1 = Verstoß/Überschneidung, 2 = Bedienfehler. Verändert nichts (nur Lesen von git status und Dateiinhalten)."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def dirty_files() -> dict[str, str]:
    out = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    files: dict[str, str] = {}
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        status, path = e[:2], e[3:]
        if status[0] in "RC":  # Umbenennung/Kopie: nächster Eintrag ist der alte Pfad
            i += 1
        p = ROOT / path
        files[path] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<gelöscht>"
    return files


def match(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) or path == pat.rstrip("/") or path.startswith(pat.rstrip("/") + "/") and pat.endswith("/") for pat in patterns)


def cmd_snapshot(a) -> int:
    Path(a.out).write_text(json.dumps(dirty_files(), indent=1), encoding="utf-8")
    print(f"Snapshot: {len(json.loads(Path(a.out).read_text()))} veränderte/untracked Dateien")
    return 0


def violations(snapshot: dict[str, str], now: dict[str, str], allowed: list[str]) -> list[str]:
    changed = sorted(p for p, h in now.items() if snapshot.get(p) != h)
    changed += sorted(p for p in snapshot if p not in now)  # Datei war dirty und ist jetzt sauber/zurückgesetzt
    return [p for p in changed if not match(p, allowed)]


def cmd_check(a) -> int:
    if not a.allowed:
        print("FEHLER: mindestens ein --allowed-Muster nötig", file=sys.stderr)
        return 2
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    bad = violations(snap, dirty_files(), a.allowed)
    for p in bad:
        print(f"VERSTOSS außerhalb der Dateimenge: {p}")
    print("OK – alle Änderungen liegen in der Dateimenge" if not bad else f"{len(bad)} Verstoß/Verstöße")
    return 1 if bad else 0


def overlaps(sets: dict[str, list[str]], universe: list[str]) -> list[str]:
    res = []
    names = sorted(sets)
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            both = [p for p in universe if match(p, sets[x]) and match(p, sets[y])]
            if both:
                res.append(f"{x} ∩ {y}: {', '.join(both[:5])}{' …' if len(both) > 5 else ''}")
            for gx in sets[x]:  # Muster-Gleichheit ohne vorhandene Dateien (neue Dateien) ebenfalls melden
                if gx in sets[y]:
                    res.append(f"{x} ∩ {y}: identisches Muster {gx}")
    return sorted(set(res))


def cmd_overlap(a) -> int:
    sets: dict[str, list[str]] = {}
    for s in a.set:
        name, _, globs = s.partition("=")
        if not name or not globs:
            print(f"FEHLER: --set erwartet NAME=glob,glob (war: {s})", file=sys.stderr)
            return 2
        sets[name] = [g.strip() for g in globs.split(",") if g.strip()]
    universe = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    res = overlaps(sets, [p for p in universe if p])
    for r in res:
        print("ÜBERSCHNEIDUNG:", r)
    print("OK – Dateimengen disjunkt" if not res else "Dateimengen überschneiden sich – NICHT parallel ausführen")
    return 1 if res else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("--out", required=True); s.set_defaults(fn=cmd_snapshot)
    c = sub.add_parser("check"); c.add_argument("--snapshot", required=True); c.add_argument("--allowed", action="append", default=[]); c.set_defaults(fn=cmd_check)
    o = sub.add_parser("overlap"); o.add_argument("--set", action="append", default=[], help="NAME=glob,glob"); o.set_defaults(fn=cmd_overlap)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
