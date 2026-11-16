#!/usr/bin/env python3
"""Dateimengen-Kontrolle für delegierte Agentenarbeit (Verfahren aus .claude/rules/60-collaboration.md, hier maschinell prüfbar).

Claude Code kennt KEINE technische Sperre gegen parallele Schreibzugriffe auf dieselbe Datei. Dieses Skript erkennt Verstöße NACHTRÄGLICH:
  1. vor der Delegation:   python scripts/check_file_set.py snapshot --out /pfad/snap.json
  2. nach dem Agentenlauf:  python scripts/check_file_set.py check --snapshot /pfad/snap.json --allowed 'backend/leventum/services/*.py' --allowed 'backend/tests/test_x.py'
Gemeldet werden alle seit dem Snapshot neu angelegten, geänderten, gelöschten, umbenannten oder committeten Dateien, die auf KEINES der
--allowed-Muster passen. Bei Umbenennung/Kopie werden alter UND neuer Pfad geprüft. Bei parallelen Agenten die Muster ALLER gleichzeitig
laufenden Agenten angeben (sonst meldet das Skript deren Dateien als Verstoß) und zusätzlich mit
`overlap --set A=glob,glob --set B=glob` prüfen, ob sich Dateimengen überschneiden (dann darf nicht parallel gearbeitet werden).
Optional für alle Unterbefehle: `--repo PFAD` (Standard: das Repository dieses Skripts).

Was erfasst wird (Fingerabdruck je Pfad): Inhalt (SHA-256), Typ (Datei / Symlink mit Ziel via readlink, ohne dem Link zu folgen / Verzeichnis / Sonstiges),
Ausführbit (Datei), Gelöscht-Zustand. Quellen: `git status` (tracked, staged, untracked), ignorierte Dateien (`git ls-files --others --ignored
--exclude-standard`) und committete Änderungen seit dem Snapshot (`git diff --name-status -M <Snapshot-HEAD>..HEAD`; Snapshot speichert den HEAD).
Rauschen bei ignorierten Dateien wird ausgeschlossen (NOISE_DIRS, NOISE_SUFFIXES: .venv, node_modules, __pycache__, .pytest_cache, dist, build,
*.pyc, Caches u. ä.); relevante ignorierte Dateien (z. B. lokale Datenbank, .env) werden dagegen verglichen. Nicht ignorierte Dateien werden nie als Rauschen behandelt.

Glob-Syntax (eigener Matcher): `*` und `?` matchen NICHT über `/`; `**` matcht beliebig viele Verzeichnisebenen (`a/**/b` trifft auch `a/b`);
`[abc]` Zeichenklasse; ein Muster mit `/` am Ende ist ein Verzeichnispräfix; ein Muster ohne Wildcard trifft genau diesen Pfad.

Exit-Codes: 0 = OK, 1 = Regelverstoß bzw. Überschneidung, 2 = Bedienfehler oder interner Fehler (Meldung auf stderr; z. B. fehlendes --allowed,
fehlerhafter/unlesbarer Snapshot, Snapshot-HEAD nicht mehr vorhanden oder nicht mehr Vorfahre von HEAD (zurückgesetzt/gewechselt), git-Fehler,
unlesbare Datei). Das Skript verändert nichts im Repository (nur Lesen von git-Ausgaben und Dateien; geschrieben wird nur die --out-Datei).

Grenzen (NICHT erkannt): Änderungen außerhalb des Repositories; Änderungen, die vor dem Check wieder rückgängig gemacht wurden (Netto-Null);
reine Moduswechsel, wenn git `core.fileMode=false` gesetzt hat (git meldet sie dann nicht); Inhalte in ignorierten Rauschverzeichnissen;
mehrfach hin- und her-committete Änderungen ohne Netto-Differenz; wer die Dateien zwischen Snapshot und Check selbst verändert, ist nicht zuordenbar
(das Skript kennt keine Agenten, nur Pfade). Weitere Grenzen: geschachtelte Repos/Submodule werden nur als Verzeichnis erfasst; Muster wie `docs/*/` (Wildcard + Verzeichnis-Schrägstrich) matchen nicht (Fehlalarm-Richtung); `overlap` erkennt Überschneidungen nur für vorhandene Dateien und wortgleiche Muster; eine `--out`-Datei innerhalb des Repos meldet der Check selbst als Änderung. Rückgängig gemachter Snapshot-Zustand (Datei war dirty, ist jetzt sauber mit anderem Inhalt) wird gemeldet."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GONE = "<gelöscht>"
SNAPSHOT_VERSION = 2

# Rauschen: gilt NUR für ignorierte Dateien (siehe ignored_files). Verzeichnisnamen (beliebige Ebene) und Dateiendungen.
NOISE_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".cache", ".vite",
    ".parcel-cache", "dist", "build", "coverage", "htmlcov", "test-results", "playwright-report",
})
NOISE_SUFFIXES = (".pyc", ".pyo", ".egg-info")
NOISE_FILES = frozenset({".coverage"})


class ToolError(Exception):
    """Bedienfehler oder interner Fehler -> Exit-Code 2."""


def show(path: str) -> str:
    """Pfad ausgebbar machen (auch nicht-UTF-8-Bytes)."""
    return os.fsencode(path).decode("utf-8", "backslashreplace")


# --- git ------------------------------------------------------------------------------------------------
def git(top: Path, *args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=top, capture_output=True)
    except OSError as e:
        raise ToolError(f"git nicht ausführbar: {e}") from e
    if r.returncode not in ok:
        raise ToolError(f"git {' '.join(args)} fehlgeschlagen (Exit {r.returncode}): {r.stderr.decode('utf-8', 'replace').strip()}")
    return r


def toplevel(repo: Path) -> Path:
    if not repo.is_dir():
        raise ToolError(f"Repository-Pfad existiert nicht: {repo}")
    return Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel").stdout.strip()))


def split_z(data: bytes) -> list[str]:
    return [os.fsdecode(x) for x in data.split(b"\0") if x]


def head_commit(top: Path) -> str:
    r = git(top, "rev-parse", "--verify", "-q", "HEAD^{commit}", ok=(0, 1))
    return r.stdout.decode().strip() if r.returncode == 0 else ""  # "" = noch kein Commit


def status_paths(top: Path) -> list[str]:
    parts = git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout.split(b"\0")
    paths: list[str] = []
    i = 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        paths.append(os.fsdecode(e[3:]))
        if e[:1] in b"RC" or e[1:2] in b"RC":  # Umbenennung/Kopie: nächster Eintrag ist der Ursprungspfad -> ebenfalls erfassen
            if i < len(parts) and parts[i]:
                paths.append(os.fsdecode(parts[i]))
            i += 1
    return paths


def is_noise(path: str) -> bool:
    parts = path.split("/")
    return (any(p in NOISE_DIRS for p in parts[:-1]) or parts[-1] in NOISE_FILES or parts[-1] in NOISE_DIRS
            or any(p.endswith(NOISE_SUFFIXES) for p in parts))


def ignored_files(top: Path) -> list[str]:
    out = split_z(git(top, "ls-files", "-z", "--others", "--ignored", "--exclude-standard").stdout)
    return [p for p in out if not is_noise(p)]


def committed_paths(top: Path, base: str) -> list[str]:
    """Pfade (bei R/C beide) der committeten Änderungen base..HEAD."""
    if not head_commit(top):
        return []
    if base == "":
        base = git(top, "hash-object", "-t", "tree", "/dev/null").stdout.decode().strip()  # leerer Baum
    toks = git(top, "diff", "--name-status", "-M", "-z", base, "HEAD").stdout.split(b"\0")
    paths: list[str] = []
    i = 0
    while i < len(toks):
        st = toks[i]
        i += 1
        if not st:
            continue
        n = 2 if st[:1] in b"RC" else 1
        paths += [os.fsdecode(x) for x in toks[i:i + n]]
        i += n
    return paths


# --- Fingerabdruck -------------------------------------------------------------------------------------
def fingerprint(top: Path, rel: str) -> str:
    p = top / rel
    try:
        st = os.lstat(p)
    except (FileNotFoundError, NotADirectoryError):
        return GONE
    except OSError as e:
        raise ToolError(f"Datei nicht lesbar: {show(rel)}: {e}") from e
    if stat.S_ISLNK(st.st_mode):
        try:
            return "symlink:" + os.fsdecode(os.readlink(p))  # Ziel, dem Link wird nicht gefolgt (auch kaputte/Verzeichnis-Links)
        except OSError as e:
            raise ToolError(f"Symlink nicht lesbar: {show(rel)}: {e}") from e
    if stat.S_ISDIR(st.st_mode):
        return "dir"  # z. B. Submodul; Inhalt wird von git einzeln gemeldet
    if stat.S_ISREG(st.st_mode):
        try:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        except OSError as e:
            raise ToolError(f"Datei nicht lesbar: {show(rel)}: {e}") from e
        return f"file:{'x' if st.st_mode & stat.S_IXUSR else '-'}:{h.hexdigest()}"
    return "other"


def collect(top: Path, extra: list[str] = ()) -> dict[str, str]:
    cand = set(status_paths(top)) | set(ignored_files(top)) | set(extra)
    return {p: fingerprint(top, p) for p in sorted(cand)}


def dirty_files(repo: Path = ROOT) -> dict[str, str]:
    return collect(toplevel(repo))


# --- Glob ----------------------------------------------------------------------------------------------
def glob_to_regex(pat: str) -> re.Pattern:
    out, i, n = [], 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat.startswith("**", i):
                j = i + 2
                if pat.startswith("/", j):
                    out.append("(?:.*/)?")
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < n and pat[j] in "!^":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
            else:
                body = pat[i + 1:j]
                if body[:1] in ("!", "^"):
                    body = "^" + body[1:]
                out.append("(?!/)[" + body.replace("\\", "\\\\") + "]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def match(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        base = pat.rstrip("/")
        if path == base:
            return True
        if pat.endswith("/"):
            if path.startswith(base + "/"):
                return True
            continue
        if glob_to_regex(pat).fullmatch(path):
            return True
    return False


# --- Kommandos -----------------------------------------------------------------------------------------
def cmd_snapshot(a) -> int:
    top = toplevel(a.repo)
    files = collect(top)
    data = {"version": SNAPSHOT_VERSION, "head": head_commit(top), "files": files}
    try:
        Path(a.out).write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError as e:
        raise ToolError(f"Snapshot nicht schreibbar: {e}") from e
    print(f"Snapshot: HEAD {data['head'][:12] or '(kein Commit)'}, {len(files)} veränderte/untracked/ignorierte Dateien")
    return 0


def violations(snapshot: dict[str, str], now: dict[str, str], allowed: list[str]) -> list[str]:
    changed = sorted(p for p, h in now.items() if snapshot.get(p) != h)
    changed += sorted(p for p in snapshot if p not in now)  # Datei war dirty und ist jetzt sauber/zurückgesetzt
    return [p for p in changed if not match(p, allowed)]


def load_snapshot(path: str) -> tuple[str, dict[str, str]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ToolError(f"Snapshot nicht lesbar: {path}: {e}") from e
    if (not isinstance(data, dict) or data.get("version") != SNAPSHOT_VERSION or not isinstance(data.get("head"), str)
            or not isinstance(data.get("files"), dict) or not all(isinstance(v, str) for v in data["files"].values())):
        raise ToolError(f"Snapshot hat ungültiges Format (erwartet Version {SNAPSHOT_VERSION}; neu erzeugen): {path}")
    return data["head"], data["files"]


def check_head(top: Path, snap_head: str) -> None:
    cur = head_commit(top)
    if snap_head == "":
        return
    if not cur:
        raise ToolError("Snapshot-HEAD ist vorhanden, das Repository hat aber keinen Commit mehr (zurückgesetzt/neu angelegt?)")
    if git(top, "cat-file", "-e", snap_head + "^{commit}", ok=(0, 1, 128)).returncode != 0:
        raise ToolError(f"Snapshot-HEAD {snap_head[:12]} existiert nicht mehr (anderes Repository oder History umgeschrieben); Check nicht möglich")
    if git(top, "merge-base", "--is-ancestor", snap_head, "HEAD", ok=(0, 1)).returncode != 0:
        raise ToolError(f"Snapshot-HEAD {snap_head[:12]} ist kein Vorfahre des aktuellen HEAD (zurückgesetzt oder Branch gewechselt); Check nicht möglich")


def cmd_check(a) -> int:
    if not a.allowed:
        raise ToolError("mindestens ein --allowed-Muster nötig")
    top = toplevel(a.repo)
    snap_head, snap = load_snapshot(a.snapshot)
    check_head(top, snap_head)
    now = collect(top, extra=list(snap) + committed_paths(top, snap_head))
    bad = violations(snap, now, a.allowed)
    for p in bad:
        print(f"VERSTOSS außerhalb der Dateimenge: {show(p)}")
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
            raise ToolError(f"--set erwartet NAME=glob,glob (war: {s})")
        sets[name] = [g.strip() for g in globs.split(",") if g.strip()]
    top = toplevel(a.repo)
    universe = split_z(git(top, "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout)
    res = overlaps(sets, universe)
    for r in res:
        print("ÜBERSCHNEIDUNG:", show(r))
    print("OK – Dateimengen disjunkt" if not res else "Dateimengen überschneiden sich – NICHT parallel ausführen")
    return 1 if res else 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", type=Path, default=ROOT, help="Repository (Standard: Repository dieses Skripts)")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", parents=[common]); s.add_argument("--out", required=True); s.set_defaults(fn=cmd_snapshot)
    c = sub.add_parser("check", parents=[common]); c.add_argument("--snapshot", required=True); c.add_argument("--allowed", action="append", default=[]); c.set_defaults(fn=cmd_check)
    o = sub.add_parser("overlap", parents=[common]); o.add_argument("--set", action="append", default=[], help="NAME=glob,glob"); o.set_defaults(fn=cmd_overlap)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)  # argparse-Fehler -> SystemExit(2)
    try:
        return a.fn(a)
    except ToolError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # interner Fehler darf nie als Regelverstoß (1) erscheinen
        print(f"INTERNER FEHLER: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
