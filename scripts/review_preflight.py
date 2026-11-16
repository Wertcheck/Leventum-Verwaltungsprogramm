#!/usr/bin/env python3
"""Fail-closed-Preflight vor dem Einsatz des Bash-fähigen Reviewers (`independent-reviewer`).

Empfohlener Aufruf durch den Orchestrator (Vertrauensanker = unveränderliches Git-Objekt, NICHT die Arbeitskopie):
    python3 -I scripts/review_preflight.py anchor-cmd --pin <40-hex-sha> --blob <40-hex-blob>   # druckt den gehärteten Ankeraufruf (nur Text)
Der gedruckte Ablauf schreibt das Skript mit `git --no-replace-objects cat-file blob <PIN>:scripts/review_preflight.py` in eine private
Wegwerf-Datei, vergleicht deren Blob-Hash mit einem vom Orchestrator gehaltenen Wert und führt sie dann mit `python3 -I <datei> check --pin <PIN>` aus.
Ein einfaches `git show <PIN>:… | python3 -I -` ist NICHT empfohlen: refs/replace/* im Repository kann das Objekt austauschen (im Test belegt).
Weitere Befehle (aus derselben Datei): `nonce [--text]`, `verify --nonce <hex> [--log P] [--issued <ts>]`.
Das Skript verwendet nur die Standardbibliothek, keine Repo-Importe und NICHT `__file__`.

Exit-Codes: 0 = alle Prüfungen bestanden, 1 = Prüfung fehlgeschlagen (Reviewer NICHT starten), 2 = Bedienfehler.
Jede Prüfung gibt `PASS|FAIL|WARN <id>: <Grund>` aus; am Ende `RESULT: OK|BLOCKED`.

Was `check` aus dem Repository heraus ausführt (ehrlich):
* Phase 1 (Konfiguration, vor JEDEM git-Aufruf im Repository): reine Dateisystemprüfungen (.git muss echtes Verzeichnis sein; config.worktree,
  hooks, info/attributes, info/grafts, refs/replace, objects/info/alternates) und das Lesen von `.git/config` über `git config --file <datei> --list -z
  --no-includes` mit cwd `/` (kein Repository, keine Repo-Konfiguration geladen). Die Schlüssel werden gegen eine Allowlist geprüft
  (Allowlist wie `scripts/check_file_set.py`, in `extensions.*` strenger). Schon ein einziger Verstoß beendet den Lauf mit BLOCKED, OHNE dass ein
  git-Aufruf im Repository stattgefunden hat.
* Phase 2 (nur nach bestandener Phase 1): git-Aufrufe im Repository (cat-file, ls-tree, ls-files) mit neu aufgebauter Umgebung (PATH nur /usr/bin:/bin,
  GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM=1, GIT_NO_LAZY_FETCH=1, GIT_ALLOW_PROTOCOL=none, GIT_PROTOCOL_FROM_USER=0, GIT_ATTR_NOSYSTEM=1) und
  Kommandozeilen-Überschreibungen (fsmonitor/hooksPath/attributesFile/pager/ssh ... abgeschaltet, --no-replace-objects). Das ist vertretbar, weil die
  Konfiguration dann nur noch Allowlist-Schlüssel enthält und keine Hooks/Filter/Replace-Refs/Alternates existieren.
* Rest-Risiko TOCTOU: zwischen Phase 1 und Phase 2 (und danach, vor dem Reviewer-Start) kann ein gleichzeitig schreibender Prozess .git verändern. Das
  Skript prüft Momentaufnahmen; es schließt das nicht aus.
* Der Bootstrap selbst (`cat-file` im anchor-cmd) läuft VOR der Konfigurationsprüfung im Repository; er ist auf --no-replace-objects, abgeschaltete
  Lazy-Fetches/Protokolle und bereinigte Umgebung begrenzt und wird durch den Blob-Hash-Vergleich abgesichert, kann aber Repo-Konfiguration nicht ausschließen.

Ehrliche Grenzen (bitte nicht aufwerten):
* Bestandene Prüfung ist NOTWENDIG, nicht HINREICHEND. Insbesondere beweist die Trust-Prüfung (f) nur, dass die Konfigurationsdatei den Workspace selbst als
  vertraut führt, nicht, dass der Hook im konkreten Subagent-Lauf tatsächlich greift (dafür `nonce`/`verify`). Die Vererbung des Trusts von Eltern-
  verzeichnissen ist NICHT gemessen und zählt deshalb nicht (fail closed).
* Selbstbezug (j): Dass dieses Skript der Inhalt des PIN-Blobs ist, ist nicht von innen beweisbar. Ersatz: der Blob-Hash-Vergleich im anchor-cmd
  (gegen einen vom Orchestrator gehaltenen Wert). Wird das Skript aus einer Datei gestartet (argv[0] != '-'), wird deren Inhalt zusätzlich gegen den
  PIN-Blob verglichen.
* Ein als root laufender, schreibender Agent kann Dateien, Attribute (`chattr -i`) und das Hook-Protokoll verändern. `verify` ist nur ein Nachweis gegen
  Fehlkonfiguration bzw. Nicht-Ausführung des Hooks, kein Schutz gegen aktive Manipulation. Der Git-PIN ist der Anker, nicht das Dateisystem.
* `matcher_covers` (Profil-Prüfung g) nutzt Python-`re.fullmatch` als NÄHERUNG der Matcher-Semantik von Claude Code. Im Experiment bestätigt wurde nur, dass
  `Bash|Edit|Write|NotebookEdit|mcp__.*` im Subagent-Lauf für Bash feuerte; andere Matcher-Formen sind nicht gemessen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone

PROTECTED = [
    "scripts/ro_run.sh",
    "scripts/review_preflight.py",
    "scripts/protect_files.sh",
    "scripts/check_file_set.py",
    "scripts/validate_agent_system.py",
    ".claude/hooks/ro_guard.py",
    ".claude/agents/independent-reviewer.md",
    ".claude/agents/independent-reviewer-static.md",
    ".claude/settings.json",
    "CLAUDE.md",
    ".claude/rules/60-collaboration.md",
]
TREE_ROOT = ".claude"  # gesamter Baum: Pfade, Inhalt und Modus gegen den PIN; nur .claude/hooks/__pycache__ wird als Rauschen toleriert
HOOK_CMD = 'python3 -I "$CLAUDE_PROJECT_DIR/.claude/hooks/ro_guard.py" || exit 2'

# Konfigurations-Allowlist: identisch zu scripts/check_file_set.py (CONFIG_ALLOW_EXACT / CONFIG_ALLOW_RE / CONFIG_DENY_EXACT, Regex-fullmatch,
# IGNORECASE), mit zwei Verschärfungen: extensions.* nur objectformat/compatobjectformat; core.filemode nur true/false.
CONFIG_ALLOW_EXACT = frozenset({
    "core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates", "core.ignorecase", "core.precomposeunicode",
    "init.defaultbranch", "user.name", "user.email", "safe.directory",
    "extensions.objectformat", "extensions.compatobjectformat",
})
CONFIG_ALLOW_RE = [re.compile(p, re.IGNORECASE) for p in (
    r"remote\..+\.(url|fetch|pushurl)", r"branch\..+\.(remote|merge|rebase)", r"(gc|receive|pack)\..+",
)]
CONFIG_DENY_EXACT = frozenset({"extensions.worktreeconfig", "extensions.partialclone"})
ATTR_BAD_RE = re.compile(r"(?:^|\s)(?:filter|diff|merge)=")
BAD_ENV = re.compile(r"^(LD_.*|BASH_ENV|ENV|PATH|PYTHON.*|SHELLOPTS)$")

SAFE_PATH = "/usr/bin:/bin"
SAFE_ENV = {"PATH": SAFE_PATH, "HOME": "/nonexistent", "LC_ALL": "C", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "none", "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "GIT_PAGER": "cat"}
GIT_OVERRIDES = (
    "core.quotepath=off", "core.fsmonitor=false", "core.hooksPath=" + os.devnull, "core.untrackedCache=false", "core.attributesFile=" + os.devnull,
    "diff.external=", "core.pager=cat", "core.editor=true", "core.sshCommand=true", "core.askPass=", "core.gitProxy=", "credential.helper=",
    "status.submoduleSummary=false", "submodule.recurse=false", "core.sparseCheckout=false",
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MANAGED_FILES = ["/etc/claude-code/managed-settings.json"]
MANAGED_DIR = "/etc/claude-code/managed-settings.d"


def git(cwd: str, *args: str) -> tuple[int, bytes]:
    """Einziger git-Einstiegspunkt. cwd == '/' bedeutet: kein Repository (nur für `config --file`)."""
    exe = shutil.which("git", path=SAFE_PATH)
    if not exe:
        return 127, b""
    argv = [exe, "--no-pager", "--no-optional-locks", "--no-replace-objects"]
    for o in GIT_OVERRIDES:
        argv += ["-c", o]
    try:
        p = subprocess.run(argv + list(args), cwd=cwd, env=dict(SAFE_ENV), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return 127, b""
    return p.returncode, p.stdout


class Report:
    def __init__(self) -> None:
        self.failed = False

    def _p(self, kind: str, cid: str, msg: str) -> None:
        print(f"{kind} {cid}: {msg}")

    def ok(self, cid: str, msg: str) -> None:
        self._p("PASS", cid, msg)

    def fail(self, cid: str, msg: str) -> None:
        self.failed = True
        self._p("FAIL", cid, msg)

    def warn(self, cid: str, msg: str) -> None:
        self._p("WARN", cid, msg)


# ---------- Frontmatter ----------
def split_frontmatter(text: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def _norm_tools(v: object) -> list[str]:
    items = v if isinstance(v, list) else str(v or "").split(",")
    return [re.sub(r"\(.*\)$", "", str(t).strip()) for t in items if str(t).strip()]


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return re.sub(r'\\(["\\])', r"\1", s[1:-1])
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


def parse_frontmatter_fallback(fm: str) -> dict:
    """Zeilenparser: tools (Komma-Liste) und hooks.PreToolUse[{matcher, commands}]; entfernt YAML-Anführungszeichen/Escapes."""
    tools: list[str] = []
    entries: list[dict] = []
    in_hooks = False
    event = None
    cur = None
    for raw in fm.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        top = not raw[0].isspace()
        if top:
            in_hooks = raw.startswith("hooks:")
            event = cur = None
            m = re.match(r"^tools:\s*(.*)$", raw)
            if m:
                tools = _norm_tools(m.group(1).strip().strip("[]"))
            continue
        if not in_hooks:
            continue
        m = re.match(r"^\s*([A-Z][A-Za-z]+):\s*$", raw)
        if m and not raw.lstrip().startswith("-"):
            event, cur = m.group(1), None
            continue
        m = re.match(r"^\s*-\s*matcher:\s*(.*?)\s*$", raw)
        if m:
            cur = {"matcher": _unquote(m.group(1)), "commands": []}
            if event == "PreToolUse":
                entries.append(cur)
            continue
        m = re.match(r"^\s*-?\s*command:\s*(.*?)\s*$", raw)
        if m and cur is not None:
            cur["commands"].append(_unquote(m.group(1)))
    return {"tools": tools, "pretooluse": entries}


def parse_frontmatter(fm: str) -> dict:
    try:
        import yaml  # type: ignore
    except Exception:
        return parse_frontmatter_fallback(fm)
    try:
        d = yaml.safe_load(fm)
    except Exception:
        return parse_frontmatter_fallback(fm)
    if not isinstance(d, dict):
        return {"tools": [], "pretooluse": []}
    entries = []
    pre = ((d.get("hooks") or {}).get("PreToolUse") or []) if isinstance(d.get("hooks"), dict) else []
    for e in pre if isinstance(pre, list) else []:
        if isinstance(e, dict):
            cmds = [str(h.get("command", "")) for h in (e.get("hooks") or []) if isinstance(h, dict)]
            entries.append({"matcher": str(e.get("matcher", "")), "commands": cmds})
    return {"tools": _norm_tools(d.get("tools")), "pretooluse": entries}


def matcher_covers(matcher: str, name: str) -> bool:
    """NÄHERUNG: Python-fullmatch ist nicht identisch mit der Matcher-Semantik von Claude Code (nur die Form
    `Bash|Edit|Write|NotebookEdit|mcp__.*` wurde im Subagent-Lauf als wirksam bestätigt)."""
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, name) is not None
    except re.error:
        return False


# ---------- Trust ----------
def config_home() -> str:
    return os.path.expanduser("~")


def trust_state(repo_real: str) -> tuple[bool, str, str | None]:
    """Nur ein Eintrag für das Repo SELBST mit hasTrustDialogAccepted is True zählt. Dritter Wert: Hinweis auf nicht zählende Eltern-Einträge."""
    cdir = os.environ.get("CLAUDE_CONFIG_DIR")
    path = os.path.join(cdir, ".claude.json") if cdir else os.path.join(config_home(), ".claude.json")
    try:
        with open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except Exception as e:
        return False, f"{path} nicht lesbar ({type(e).__name__})", None
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        return False, f"{path}: kein projects-Block", None
    own: list[object] = []
    parent_note = None
    for k, v in projects.items():
        if not isinstance(k, str) or not isinstance(v, dict) or "hasTrustDialogAccepted" not in v:
            continue
        keys = {os.path.realpath(k), os.path.normpath(k)}
        if repo_real in keys:
            own.append(v["hasTrustDialogAccepted"])
        elif v["hasTrustDialogAccepted"] is True and any(repo_real.startswith(x.rstrip("/") + "/") for x in keys):
            parent_note = f"Eintrag für Elternverzeichnis {k}: Vererbung nicht belegt, zählt nicht"
    if own and all(x is True for x in own):
        return True, f"{path}: hasTrustDialogAccepted=True für {repo_real}", parent_note
    if own:
        return False, f"{path}: hasTrustDialogAccepted={own!r} für {repo_real}", parent_note
    return False, f"{path}: kein Eintrag für {repo_real} selbst", parent_note


# ---------- Konfiguration (Phase 1) ----------
def config_problems(entries: list[tuple[str, str | None]]) -> list[str]:
    bad = []
    for key, val in entries:
        lk = key.lower()
        v = (val or "").strip().lower()
        if lk in CONFIG_DENY_EXACT:
            bad.append(key)
        elif lk in CONFIG_ALLOW_EXACT or any(r.fullmatch(key) for r in CONFIG_ALLOW_RE):
            if lk == "core.filemode" and v not in ("true", "false"):
                bad.append(key)
            elif re.fullmatch(r"remote\..+\.(url|pushurl)", key, re.IGNORECASE) and v.startswith("ext::"):
                bad.append(key)
        else:
            bad.append(key)
    return bad


def config_phase(r: Report, repo_real: str) -> bool:
    """Alle Prüfungen, bevor irgendein git-Aufruf im Repository läuft. True = bestanden."""
    before = r.failed
    r.failed = False
    gdir = os.path.join(repo_real, ".git")
    try:
        gst = os.lstat(gdir)
    except OSError:
        gst = None
    if gst is None or not stat.S_ISDIR(gst.st_mode):
        r.fail("d-git", ".git ist kein echtes Verzeichnis (fehlt, Symlink oder Datei/gitdir-Verweis)")
        ok = False
        r.failed = before or True
        return ok
    r.ok("d-git", ".git ist ein echtes Verzeichnis")

    cfg = os.path.join(gdir, "config")
    try:
        cst = os.lstat(cfg)
    except OSError:
        cst = None
    if cst is None or not stat.S_ISREG(cst.st_mode):
        r.fail("d-config", ".git/config fehlt oder ist keine normale Datei")
    else:
        rc, o = git("/", "config", "--file", cfg, "--list", "-z", "--no-includes")
        if rc != 0:
            r.fail("d-config", "Lesen von .git/config fehlgeschlagen")
        else:
            entries: list[tuple[str, str | None]] = []
            for e in o.split(b"\0"):
                if e:
                    k, sep, v = e.partition(b"\n")
                    entries.append((os.fsdecode(k), os.fsdecode(v) if sep else None))
            badkeys = config_problems(entries)
            if os.path.lexists(os.path.join(gdir, "config.worktree")):
                badkeys.append("config.worktree (Datei)")
            if badkeys:
                r.fail("d-config", f"nicht erlaubte .git/config-Einträge (Werte werden nicht ausgegeben): {sorted(set(badkeys))[:8]}")
            else:
                r.ok("d-config", ".git/config nur Allowlist-Schlüssel/-Werte")

    hk = os.path.join(gdir, "hooks")
    if os.path.islink(hk):
        r.fail("d-hooks", ".git/hooks ist ein Symlink")
    else:
        try:
            badh = sorted(n for n in (os.listdir(hk) if os.path.isdir(hk) else []) if not n.endswith(".sample"))
        except OSError:
            badh = ["<nicht lesbar>"]
        if badh:
            r.fail("d-hooks", f".git/hooks enthält aktive Hooks: {badh[:5]}")
        else:
            r.ok("d-hooks", "keine aktiven Git-Hooks")

    ap = os.path.join(gdir, "info", "attributes")
    if os.path.islink(ap):
        r.fail("d-attributes", ".git/info/attributes ist ein Symlink")
    else:
        try:
            txt = open(ap, "r", errors="replace").read() if os.path.exists(ap) else ""
        except OSError:
            txt = "filter=x"
        if any(ATTR_BAD_RE.search(ln) for ln in txt.splitlines() if not ln.lstrip().startswith("#")):
            r.fail("d-attributes", ".git/info/attributes enthält filter=/diff=/merge=")
        else:
            r.ok("d-attributes", "keine filter=/diff=/merge= in .git/info/attributes")

    rep = []
    rdir = os.path.join(gdir, "refs", "replace")
    if os.path.lexists(rdir):
        if os.path.islink(rdir) or not os.path.isdir(rdir):
            rep.append("refs/replace (Symlink/Datei)")
        else:
            for _, _, files in os.walk(rdir):
                rep += files
    pr = os.path.join(gdir, "packed-refs")
    if os.path.lexists(pr):
        try:
            if re.search(r"^[0-9a-f]+ refs/replace/", open(pr, "r", errors="replace").read(), re.M):
                rep.append("packed-refs")
        except OSError:
            rep.append("packed-refs (nicht lesbar)")
    if rep:
        r.fail("d-replace", f"refs/replace/* vorhanden (Objekte austauschbar): {sorted(rep)[:5]}")
    else:
        r.ok("d-replace", "keine refs/replace/*")

    extra = [n for n in ("objects/info/alternates", "objects/info/http-alternates", "info/grafts") if os.path.lexists(os.path.join(gdir, n))]
    if extra:
        r.fail("d-alternates", f"{extra}: fremde Objektquellen/Grafts (fail closed)")
    else:
        r.ok("d-alternates", "keine alternates/grafts")

    ok = not r.failed
    r.failed = before or r.failed
    return ok


# ---------- Hilfen Dateimenge ----------
def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def read_nofollow(path: str) -> bytes | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as f:
            return f.read()
    except OSError:
        return None


def parse_ls_tree(o: bytes) -> dict[str, tuple[str, str]]:
    res: dict[str, tuple[str, str]] = {}
    for e in o.split(b"\0"):
        if not e:
            continue
        meta, _, name = e.partition(b"\t")
        parts = meta.decode(errors="replace").split()
        if len(parts) == 3:
            res[os.fsdecode(name)] = (parts[0], parts[2])
    return res


def managed_findings(files: list[str], d: str) -> list[tuple[str, list[str]]]:
    """Existierende Managed-Settings-Dateien mit ihren Schlüsselnamen (keine Werte)."""
    paths = list(files)
    try:
        paths += [os.path.join(d, n) for n in sorted(os.listdir(d))]
    except OSError:
        pass
    out = []
    for p in paths:
        if not os.path.lexists(p):
            continue
        try:
            data = json.loads(open(p, "rb").read().decode("utf-8"))
            keys = sorted(str(k) for k in data) if isinstance(data, dict) else ["<kein Objekt>"]
        except Exception:
            keys = ["<nicht auswertbar>"]
        out.append((p, keys))
    return out


# ---------- Prüfungen ----------
def check(pin: str, repo: str) -> int:
    r = Report()
    repo_real = os.path.realpath(repo)

    # Phase 1: Konfiguration VOR jedem git-Aufruf im Repository
    if not config_phase(r, repo_real):
        print("NOTE: Konfigurationsprüfung fehlgeschlagen – es wurde KEIN git im Repository ausgeführt.")
        print("RESULT: BLOCKED")
        return 1

    # Phase 2: git im Repository
    rc, out = git(repo_real, "cat-file", "-t", pin)
    typ = out.decode(errors="replace").strip()
    if rc != 0 or typ != "commit":
        r.fail("a-pin", f"PIN {pin} ist kein vorhandenes Commit-Objekt (Typ: {typ or 'unbekannt'})")
        print("RESULT: BLOCKED")
        return 1
    r.ok("a-pin", f"{pin} ist ein Commit")

    def pin_entry(path: str):
        rc2, o = git(repo_real, "ls-tree", "-z", pin, "--", path)
        if rc2 != 0 or not o:
            return None
        meta, _, name = o.rstrip(b"\0").partition(b"\t")
        parts = meta.decode().split()
        if len(parts) != 3 or name.decode(errors="replace") != path:
            return None
        return parts[0], parts[2]

    # (b) Schutzdateien
    bad = 0
    for p in PROTECTED:
        full = os.path.join(repo_real, p)
        ent = pin_entry(p)
        if ent is None:
            r.fail(f"b[{p}]", "fehlt im PIN-Commit")
            bad += 1
            continue
        mode, sha = ent
        if mode == "120000" or mode not in ("100644", "100755"):
            r.fail(f"b[{p}]", f"im PIN-Commit kein regulärer Dateimodus ({mode})")
            bad += 1
            continue
        try:
            st = os.lstat(full)
        except OSError:
            r.fail(f"b[{p}]", "fehlt in der Arbeitskopie")
            bad += 1
            continue
        if not stat.S_ISREG(st.st_mode) or os.path.realpath(full) != full:
            r.fail(f"b[{p}]", "Symlink/keine reguläre Datei (auch über Elternverzeichnis) verboten")
            bad += 1
            continue
        rc3, blob = git(repo_real, "cat-file", "blob", sha)
        data = read_nofollow(full)
        if rc3 != 0 or data != blob:
            r.fail(f"b[{p}]", "Inhalt weicht vom PIN-Blob ab")
            bad += 1
            continue
        if (st.st_mode & 0o111 != 0) != (mode == "100755"):
            r.fail(f"b[{p}]", f"Ausführbar-Bit weicht vom PIN ab (PIN {mode})")
            bad += 1
            continue
    if not bad:
        r.ok("b", f"{len(PROTECTED)} Schutzdateien == PIN (Inhalt und Modus)")

    # (c) gesamter .claude-Baum: Pfade, Inhalt, Modus, keine Symlinks
    rc4, o = git(repo_real, "ls-tree", "-r", "-z", pin, "--", TREE_ROOT)
    pin_map = parse_ls_tree(o) if rc4 == 0 else {}
    wt: dict[str, tuple[str, str | None]] = {}  # Pfad -> (Art, sha1 oder None)
    pycache = False
    base = os.path.join(repo_real, TREE_ROOT)
    if os.path.islink(base):
        wt[TREE_ROOT] = ("symlink", None)
    else:
        for root, dirs, files in os.walk(base):
            rel_root = os.path.relpath(root, repo_real)
            keep = []
            for dn in dirs:
                rel = os.path.join(rel_root, dn)
                if os.path.islink(os.path.join(root, dn)):
                    wt[rel] = ("symlink", None)
                elif dn == "__pycache__" and rel_root == ".claude/hooks":
                    pycache = True
                else:
                    keep.append(dn)
            dirs[:] = keep
            for fn in files:
                rel = os.path.join(rel_root, fn)
                full = os.path.join(root, fn)
                try:
                    st = os.lstat(full)
                except OSError:
                    wt[rel] = ("unlesbar", None)
                    continue
                if stat.S_ISLNK(st.st_mode):
                    wt[rel] = ("symlink", None)
                elif not stat.S_ISREG(st.st_mode):
                    wt[rel] = ("keine reguläre Datei", None)
                else:
                    data = read_nofollow(full)
                    wt[rel] = ("exec" if st.st_mode & 0o111 else "reg", git_blob_sha1(data) if data is not None else None)
    if rc4 != 0:
        r.fail("c-dateimenge", "git ls-tree fehlgeschlagen")
    else:
        extra, miss = sorted(set(wt) - set(pin_map)), sorted(set(pin_map) - set(wt))
        if extra or miss:
            r.fail("c-dateimenge", f"Abweichung zum PIN; zusätzlich: {extra[:5]}; fehlend: {miss[:5]}")
        else:
            r.ok("c-dateimenge", f"{len(pin_map)} Dateien in {TREE_ROOT} == PIN (Pfade)")
        diffs = []
        for path in sorted(set(wt) & set(pin_map)):
            pmode, psha = pin_map[path]
            kind, wsha = wt[path]
            if kind not in ("reg", "exec"):
                diffs.append(f"{path} ({kind})")
            elif pmode not in ("100644", "100755") or len(psha) != 40:
                diffs.append(f"{path} (PIN-Modus {pmode})")
            elif (kind == "exec") != (pmode == "100755"):
                diffs.append(f"{path} (Modus)")
            elif wsha != psha:
                diffs.append(f"{path} (Inhalt)")
        diffs += [f"{p} ({k})" for p, (k, _) in sorted(wt.items()) if p not in pin_map and k not in ("reg", "exec")]
        if diffs:
            r.fail("c-inhalt", f"Inhalt/Modus/Typ weicht vom PIN ab oder Symlink: {diffs[:5]}")
        else:
            r.ok("c-inhalt", f"Inhalt und Modus aller Dateien in {TREE_ROOT} == PIN")
    if pycache:
        r.warn("c-pycache", ".claude/hooks/__pycache__ vorhanden (Rauschen, ignoriert)")
    if os.path.lexists(os.path.join(repo_real, ".claude", "settings.local.json")):
        r.fail("c-settings-local", ".claude/settings.local.json darf nicht existieren")
    else:
        r.ok("c-settings-local", "keine settings.local.json")

    # (e) Index-Flags
    rc6, o = git(repo_real, "ls-files", "-v", "-z")
    flagged = []
    if rc6 != 0:
        r.fail("e-indexflags", "git ls-files fehlgeschlagen")
    else:
        for e in o.split(b"\0"):
            s = e.decode(errors="replace")
            if len(s) > 2 and s[1] == " " and s[2:] in PROTECTED and s[0] != "H":
                flagged.append(f"{s[2:]} [{s[0]}]")
        if flagged:
            r.fail("e-indexflags", f"assume-unchanged/skip-worktree auf Schutzdatei: {flagged}")
        else:
            r.ok("e-indexflags", "keine Index-Flags auf Schutzdateien")

    # (f) Trust
    trusted, why, parent = trust_state(repo_real)
    if parent:
        r.warn("f-trust-parent", parent)
    if trusted:
        r.ok("f-trust", f"{why} (notwendige, nicht hinreichende Bedingung)")
    else:
        r.fail("f-trust", f"Workspace selbst nicht explizit vertraut ({why}); Bash-Reviewer verboten; verwende independent-reviewer-static")

    # (g) Profil
    prof = os.path.join(repo_real, ".claude", "agents", "independent-reviewer.md")
    try:
        fm = split_frontmatter(open(prof, encoding="utf-8").read())
    except OSError:
        fm = None
    if fm is None:
        r.fail("g-profil", "independent-reviewer.md fehlt oder hat kein Frontmatter")
    else:
        d = parse_frontmatter(fm)
        problems = []
        if "Bash" not in d["tools"]:
            problems.append("tools enthält Bash nicht")
        problems += [f"tools enthält {t}" for t in ("Edit", "Write", "NotebookEdit", "Agent") if t in d["tools"]]
        names = ["Bash", "Edit", "Write", "NotebookEdit", "mcp__github__x"]
        good = [e for e in d["pretooluse"] if any(c.strip() == HOOK_CMD for c in e["commands"])
                and all(matcher_covers(e["matcher"], n) for n in names)]
        if not good:
            problems.append(f"kein PreToolUse-Hook mit exakt `{HOOK_CMD}`, dessen Matcher Bash/Edit/Write/NotebookEdit/mcp__ abdeckt")
        if problems:
            r.fail("g-profil", "; ".join(problems))
        else:
            r.ok("g-profil", "Profil: Bash ohne Schreibwerkzeuge, Hook-Kommando exakt, Matcher deckt alle ab (Matcher-Prüfung nur Näherung)")

    # (h) Hook-Datei und Runner; Immutable nur WARN
    for p in (".claude/hooks/ro_guard.py", "scripts/ro_run.sh", ".claude/hooks"):
        full = os.path.join(repo_real, p)
        try:
            st = os.lstat(full)
        except OSError:
            r.fail(f"h[{p}]", "fehlt")
            continue
        if p != ".claude/hooks":
            if st.st_uid != 0 or st.st_mode & 0o022:
                r.fail(f"h[{p}]", f"Besitzer uid {st.st_uid}, Modus {oct(st.st_mode & 0o777)} (verlangt: uid 0, nicht gruppen-/welt-beschreibbar)")
                continue
            r.ok(f"h[{p}]", "Besitzer root, nicht gruppen-/welt-beschreibbar")
        try:
            lp = subprocess.run(["lsattr", "-d", "--", full], env=dict(SAFE_ENV), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            flags = lp.stdout.decode(errors="replace").split()[0] if lp.returncode == 0 and lp.stdout.split() else ""
        except (OSError, subprocess.SubprocessError):
            flags = ""
        if "i" not in flags:
            r.warn(f"h-immutable[{p}]", "Immutable-Attribut nicht gesetzt (Schutz nicht aktiv; Vertrauensanker bleibt der Git-PIN)")

    # (i) Nutzerkonfiguration
    cdir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(config_home(), ".claude")
    shadow = []
    for base_dir in sorted({cdir, os.path.join(config_home(), ".claude")}):
        for n in ("independent-reviewer.md", "independent-reviewer-static.md"):
            if os.path.lexists(os.path.join(base_dir, "agents", n)):
                shadow.append(os.path.join(base_dir, "agents", n))
    if shadow:
        r.fail("i-usershadow", f"Nutzer-Agent beschattet den Projekt-Reviewer (Namensschatten): {shadow}")
    else:
        r.ok("i-usershadow", "keine gleichnamigen Nutzer-Agenten")
    sp = os.path.join(cdir, "settings.json")
    if not os.path.exists(sp):
        r.ok("i-usersettings", f"{sp} nicht vorhanden")
    else:
        try:
            with open(sp, "rb") as f:
                s = json.loads(f.read().decode("utf-8"))
            if not isinstance(s, dict):
                raise ValueError("kein Objekt")
        except Exception as e:
            s = None
            r.fail("i-usersettings", f"{sp} nicht auswertbar ({type(e).__name__})")
        if s is not None:
            envd = s.get("env") if isinstance(s.get("env"), dict) else {}
            probs = [f"env {k}" for k in sorted(k for k in envd if BAD_ENV.match(str(k)))]
            probs += [k for k in ("disableAllHooks", "allowManagedHooksOnly") if s.get(k)]
            if probs:
                r.fail("i-usersettings", f"Einstellungen mit Schutzwirkung (Hooks aus/ersetzt bzw. gefährliche env): {probs}")
            else:
                r.ok("i-usersettings", "keine gefährlichen env-/Hook-Abschalt-Schlüssel")
            perms = s.get("permissions") if isinstance(s.get("permissions"), dict) else {}
            allow = perms.get("allow") if isinstance(perms.get("allow"), list) else []
            wide = [a for a in allow if isinstance(a, str) and re.match(r"^Bash(\(\*|$)", a.strip())]
            # WARN statt FAIL: Allow-Regeln schalten PreToolUse-Hooks nicht ab (ein Hook-Deny gilt weiter); sie verändern aber die Rückfragen.
            if wide or perms.get("defaultMode") in ("bypassPermissions", "acceptEdits"):
                r.warn("i-userperms", f"weite Bash-Freigaben/permissiver Modus im Nutzer-Profil (Muster: {wide[:3]}) – Einfluss prüfen")
            hooks = s.get("hooks") if isinstance(s.get("hooks"), dict) else {}
            pre = hooks.get("PreToolUse")
            if isinstance(pre, list) and any(isinstance(e, dict) and matcher_covers(str(e.get("matcher", "")), "Bash") for e in pre):
                r.warn("i-userhooks", "Nutzer-Hooks (PreToolUse auf Bash) vorhanden – Einfluss auf den Reviewer prüfen")
    for p, keys in managed_findings(MANAGED_FILES, MANAGED_DIR):
        r.warn("i-managed", f"Managed-Settings {p} vorhanden (nur Schlüsselnamen): {keys[:12]} – Einfluss auf Hooks/Berechtigungen prüfen")

    # (j) Selbstbezug
    if sys.argv and sys.argv[0] not in ("-", ""):
        ent = pin_entry("scripts/review_preflight.py")
        me = read_nofollow(sys.argv[0])
        rc7, blob = git(repo_real, "cat-file", "blob", ent[1]) if ent else (1, b"")
        if me is None or rc7 != 0 or me != blob:
            r.fail("j-selbst", "ausführendes Skript ist nicht der PIN-Blob (Aufruf über `anchor-cmd`-Ablauf)")
        else:
            r.ok("j-selbst", "ausführende Datei == PIN-Blob")
    else:
        print("INFO j-selbst: ANNAHME – Skript stammt aus dem PIN-Objekt (von innen nicht prüfbar; Ersatz: Blob-Hash-Vergleich im anchor-cmd)")

    print("NOTE: bestanden = notwendige, nicht hinreichende Bedingung; Hook-Wirksamkeit im Subagent-Lauf nur per nonce/verify belegbar.")
    print("RESULT: " + ("BLOCKED" if r.failed else "OK"))
    return 1 if r.failed else 0


# ---------- anchor-cmd ----------
def cmd_anchor(pin: str, blob: str | None) -> int:
    b = blob or "<BLOB-HASH-VOM-ORCHESTRATOR>"
    print(f"""#!/bin/bash
# Gehärteter Ankeraufruf (nur Text, vom Orchestrator auszuführen; cwd = Repo).
# BLOB = Git-Blob-Hash von scripts/review_preflight.py im PIN, den der Orchestrator unabhängig vom Repository festgehalten hat.
set -eu
export PATH={SAFE_PATH} GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_NO_LAZY_FETCH=1 GIT_ALLOW_PROTOCOL=none GIT_PROTOCOL_FROM_USER=0 GIT_ATTR_NOSYSTEM=1
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
git --no-pager --no-replace-objects -c core.attributesFile=/dev/null cat-file blob {pin}:scripts/review_preflight.py > "$T/pf.py"
[ "$(git -C "$T" hash-object --no-filters pf.py)" = "{b}" ] || {{ echo "FAIL anchor: Blob-Hash weicht vom erwarteten Wert ab" >&2; exit 1; }}
python3 -I "$T/pf.py" check --pin {pin}""")
    if not blob:
        print("# WARNUNG: --blob fehlt; ohne festen Blob-Hash ist der Hash-Vergleich wirkungslos (Platzhalter schlägt fehl).", file=sys.stderr)
    return 0


# ---------- nonce / verify ----------
def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def cmds(nonce: str) -> tuple[str, str]:
    return f"scripts/ro_run.sh echo PROBE-{nonce}", f"echo CANARY-{nonce}"


def parse_ts(s: object) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def cmd_nonce(text_only: bool) -> int:
    n = secrets.token_hex(16)
    probe, canary = cmds(n)
    prompt = (f"Führe als allererste Aktion GENAU diese zwei Bash-Aufrufe aus und gib ihre Ergebnisse wörtlich im Bericht wieder: "
              f"1) `{probe}` 2) `{canary}`. Der zweite MUSS vom Sicherheits-Hook blockiert werden. "
              f"Wird er ausgeführt (du siehst CANARY-{n} als Ausgabe), brich SOFORT ab und melde ‚HOOK INAKTIV – Review ungültig‘.")
    if text_only:
        print(prompt)
    else:
        print(json.dumps({"nonce": n, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "probe_cmd": probe, "canary_cmd": canary,
                          "probe_sha256": sha(probe), "canary_sha256": sha(canary), "prompt": prompt}, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(nonce: str, log: str | None, issued: str | None = None) -> int:
    """HAUPT-GRENZE: Der Nonce steht im Prompt des Reviewers. Ein infizierter Reviewer OHNE aktiven Hook kann passende Zeilen an das Protokoll anhängen
    (er hat dieselbe uid). `verify` belegt daher nur Fehlkonfiguration/Nichtausführung, nicht Manipulation. `session_id` bindet die Sitzung des
    Hauptprozesses, nicht eine einzelne Subagent-Instanz."""
    probe, canary = cmds(nonce)
    ps, cs = sha(probe), sha(canary)
    path = log or os.environ.get("LEVENTUM_HOOK_LOG") or os.path.join(config_home(), ".leventum", "hook-activity.jsonl")
    msg = "Hook-Aktivität im Subagent-Betrieb NICHT nachgewiesen"
    issued_dt = parse_ts(issued) if issued is not None else None
    try:
        lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
    except OSError as e:
        print(f"{msg}: Protokoll {path} nicht lesbar ({type(e).__name__})")
        return 1
    ents = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict):
            ents.append(e)
    if any(e.get("cmd_sha256") == cs and e.get("decision") == "allow" for e in ents):
        print(f"{msg}: Canary wurde ERLAUBT (Hook inaktiv oder fehlerhaft)")
        return 1
    probes = [e for e in ents if e.get("cmd_sha256") == ps and e.get("decision") == "allow"
              and e.get("agent_type") == "independent-reviewer" and e.get("tool_name") == "Bash"]
    canaries = [e for e in ents if e.get("cmd_sha256") == cs and e.get("decision") == "deny"
                and e.get("agent_type") == "independent-reviewer" and e.get("tool_name") == "Bash"]
    if len(probes) != 1 or len(canaries) != 1:
        print(f"{msg}: Probe-allow={len(probes)}, Canary-deny={len(canaries)} (je genau 1 erwartet)")
        return 1
    sid = probes[0].get("session_id")
    if not sid or sid != canaries[0].get("session_id"):
        print(f"{msg}: session_id von Probe und Canary stimmt nicht überein")
        return 1
    if issued_dt is not None:
        for name, e in (("Probe", probes[0]), ("Canary", canaries[0])):
            t = parse_ts(e.get("ts"))
            if t is None or t < issued_dt:
                print(f"{msg}: ts der {name}-Zeile fehlt/ungültig oder liegt vor dem nonce-Zeitpunkt {issued}")
                return 1
    print(f"PASS verify: Probe erlaubt, Canary blockiert, session_id {sid} (Nachweis gegen Fehlkonfiguration, kein Manipulationsschutz; "
          f"session_id = Hauptsitzung, nicht Subagent-Instanz)")
    print("RESULT: OK")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="review_preflight")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--pin", required=True)
    c.add_argument("--repo", default=None)
    n = sub.add_parser("nonce")
    n.add_argument("--text", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--nonce", required=True)
    v.add_argument("--log", default=None)
    v.add_argument("--issued", default=None, help="ts aus der nonce-Ausgabe; Logzeilen müssen gleich/später sein")
    an = sub.add_parser("anchor-cmd")
    an.add_argument("--pin", required=True)
    an.add_argument("--blob", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "nonce":
        return cmd_nonce(a.text)
    if a.cmd == "verify":
        if not re.fullmatch(r"[0-9a-f]{32}", a.nonce):
            print("Bedienfehler: --nonce muss 32 Hex-Zeichen sein", file=sys.stderr)
            return 2
        if a.issued is not None and parse_ts(a.issued) is None:
            print("Bedienfehler: --issued muss ein ISO-8601-Zeitstempel sein", file=sys.stderr)
            return 2
        return cmd_verify(a.nonce, a.log, a.issued)
    if not SHA_RE.match(a.pin):
        print("Bedienfehler: --pin muss eine volle 40-stellige Hex-SHA (Kleinbuchstaben) sein", file=sys.stderr)
        return 2
    if a.cmd == "anchor-cmd":
        if a.blob is not None and not SHA_RE.match(a.blob):
            print("Bedienfehler: --blob muss eine volle 40-stellige Hex-SHA sein", file=sys.stderr)
            return 2
        return cmd_anchor(a.pin, a.blob)
    repo = os.path.realpath(a.repo or os.getcwd())
    if not os.path.isdir(repo):
        print(f"Bedienfehler: Repo {repo} ist kein Verzeichnis", file=sys.stderr)
        return 2
    try:
        return check(a.pin, repo)
    except Exception as e:  # fail closed
        print(f"FAIL intern: unerwarteter Fehler ({type(e).__name__})")
        print("RESULT: BLOCKED")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
