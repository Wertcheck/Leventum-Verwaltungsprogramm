#!/usr/bin/env python3
"""Dateimengen-Kontrolle für delegierte Agentenarbeit (Verfahren aus .claude/rules/60-collaboration.md, hier maschinell prüfbar).

Claude Code kennt KEINE technische Sperre gegen parallele Schreibzugriffe auf dieselbe Datei. Dieses Skript erkennt Verstöße NACHTRÄGLICH:
  1. vor der Delegation (Orchestrator, Snapshot AUSSERHALB des Repos):
         python3 -I scripts/check_file_set.py snapshot --out /pfad/ausserhalb/snap.json [--key-file /pfad/ausserhalb/snap.key]
     -> gibt EINMALIG `KEY=<64 Hex>` auf stdout aus (ohne --key-file) bzw. schreibt den Schlüssel in die Datei (mit --key-file; 0600, außerhalb des Repos,
        kein Symlink; dann KEINE Ausgabe des Schlüssels). Der Orchestrator hält den Schlüssel (nicht im Repo, nicht an Agenten).
  2. nach dem Agentenlauf (Schlüssel per Umgebungsvariable ODER --key-file, NIE per argv):
         CFS_SNAPSHOT_KEY=<hex> python3 -I scripts/check_file_set.py check --snapshot /pfad/snap.json --allowed 'backend/leventum/services/*.py' --allowed 'backend/tests/test_x.py'
         python3 -I scripts/check_file_set.py check --snapshot /pfad/snap.json --key-file /pfad/snap.key --allowed '…'
AUFRUF-HYGIENE: Das Skript MUSS mit `python3 -I` (isolierter Modus: kein sys.path[0] = scripts/, keine PYTHON*-Umgebung, kein User-site) gestartet werden. Ohne -I
(sys.flags.isolated nicht gesetzt) bricht es VOR allen Importen mit Exit 2 ab (sonst könnte eine in scripts/ abgelegte hmac.py/hashlib.py laufen). Die
Prüfung greift nur beim direkten Start (`__main__`), nicht beim Import als Modul (Tests).
SCHLÜSSEL-EXPOSITION (ehrlich): ohne --key-file erscheint der Schlüssel in Tool-Ausgaben/Transkripten des Orchestrators und danach in der Umgebung des
`check`-Prozesses; ein Agent mit Lesezugriff auf Transkripte oder /proc/*/environ derselben uid kann ihn gewinnen und den Snapshot neu signieren. Mit
--key-file entfällt die Ausgabe, die Datei ist aber für dieselbe uid (root-Agent erst recht) lesbar: das mindert nur Transkript-Lecks, ist kein Schutz gegen
einen Agenten gleicher uid.
Gemeldet werden alle seit dem Snapshot neu angelegten, geänderten, gelöschten, umbenannten oder committeten Dateien, die auf KEINES der
--allowed-Muster passen. Bei Umbenennung/Kopie werden alter UND neuer Pfad geprüft. Bei parallelen Agenten die Muster ALLER gleichzeitig
laufenden Agenten angeben (sonst meldet das Skript deren Dateien als Verstoß) und zusätzlich mit
`overlap --set A=glob,glob --set B=glob` prüfen, ob sich Dateimengen überschneiden (dann darf nicht parallel gearbeitet werden).
Optional für alle Unterbefehle: `--repo PFAD` (Standard: das Repository dieses Skripts).

Was erfasst wird (Fingerabdruck je Pfad): Inhalt (SHA-256), Typ (Datei / Symlink mit Ziel via readlink, ohne dem Link zu folgen / Verzeichnis / Sonstiges),
Ausführbit (Datei), Gelöscht-Zustand, Gitlink (Submodul: nur Pfad und im Index eingetragener Commit). Quellen: `git status` (tracked, staged,
untracked; Submodule ausgeblendet), ignorierte Dateien (`git ls-files --others --ignored --exclude-standard`), Dateien mit Index-Flag (siehe unten) und
committete Änderungen seit dem Snapshot (`git diff --name-status -M <Snapshot-HEAD>..HEAD`; Snapshot speichert den HEAD).
Rauschen bei ignorierten Dateien (NOISE_DIRS, NOISE_SUFFIXES: .venv, node_modules, __pycache__, .pytest_cache, dist, build, *.pyc, Caches u. ä.)
wird ausgeblendet, AUSSER ausführbaren/skriptartigen Dateien (SCRIPT_SUFFIXES: *.py *.pth *.pyc *.js *.sh *.so u. a., ohne Ausnahme) und Dateien MIT
gesetztem Ausführbit (st_mode & 0o111, reguläre Datei, kein Symlink), deren erste 4 Bytes ELF (`\\x7fELF`) oder Shebang (`#!`) sind (z. B. .venv/bin/*; die
4 Bytes werden NUR für Dateien mit Ausführbit gelesen). Ausführbit ohne ELF/Shebang oder ELF ohne Ausführbit und ohne skriptartige Endung bleibt Rauschen
(Grenze, z. B. Dateisysteme mit 755 für alles). Diese Dateien werden auch im Rauschen gehasht; neu oder geändert (oder gelöscht) = Verstoß. Folge: Testläufe, die `__pycache__/*.pyc` neu erzeugen, melden Verstöße
(Abhilfe: PYTHONDONTWRITEBYTECODE=1 oder bewusst `--allowed '**/__pycache__/**'`). Messung: Snapshot + Check mit 20 000 Rauschdateien
(10 000 davon *.js, gehasht, dazu einige ausführbare ELF-/Shebang-Dateien ohne Endung) in einem Wegwerf-Repo: siehe Test test_performance_20000_noise_files (Dauer wird dort ausgegeben; Messwert im
Übergabebericht). Nicht ignorierte Dateien werden nie als Rauschen behandelt.

.git-Integrität (Fingerabdruck `gitmeta`, IMMER Verstoß bei Änderung, unabhängig von --allowed; damit auch jede Änderung von core.filemode nach dem Snapshot): `.git/config`, `.git/info/*`, `.git/hooks/*` (alle
Dateien inkl. *.sample), `.git/shallow`, `.git/objects/info/alternates` sowie alle `refs/replace/*` (git for-each-ref). Meldung „.git-Integrität verletzt: …“.
Index-Flags (`git ls-files -v`): assume-unchanged (Tag h) und skip-worktree (Tag S; s = beides) verbergen Änderungen vor `git status`. Solche
Dateien werden im Snapshot als Flag erfasst und trotzdem per Inhalt gehasht. Ein nach dem Snapshot gesetztes/entferntes/geändertes Flag ist selbst
ein Verstoß („Index-Flag gesetzt: <pfad>“, Exit 1). Ein sparse-checkout-Wechsel wird NICHT gesondert erkannt (nur dokumentiert; `core.sparsecheckout`
steht nicht in der Config-Allowlist, `.git/info/sparse-checkout` liegt unter `.git/info/*` und ist damit im Fingerabdruck).

Kontrollierter git-Aufruf: ALLE git-Aufrufe laufen über die eine Funktion `git()`: Umgebung von Grund auf neu (nur PATH=/usr/bin:/bin (bewusst OHNE
/usr/local/bin, wo ein Agent ein `git` ablegen könnte), HOME=/nonexistent, LC_ALL=C, GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM=1, GIT_OPTIONAL_LOCKS=0,
GIT_TERMINAL_PROMPT=0, GIT_ASKPASS leer, GIT_PAGER=cat, GIT_NO_LAZY_FETCH=1, GIT_ALLOW_PROTOCOL=none, GIT_PROTOCOL_FROM_USER=0, GIT_ATTR_NOSYSTEM=1; GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE/GIT_EXTERNAL_DIFF u. a. aus der Umgebung des Aufrufers werden NICHT übernommen) und Argumente
`--no-pager --no-optional-locks --no-replace-objects -c core.fsmonitor=false -c core.hooksPath=/dev/null -c core.untrackedCache=false
-c core.attributesFile=/dev/null -c diff.external= -c core.pager=cat -c core.editor=true -c core.sshCommand=true -c core.askPass= …` (vollständige Liste:
GIT_OVERRIDES; alle mit git 2.43 geprüft). `git status` läuft zusätzlich mit `--ignore-submodules=all` (sonst startet git Kind-Prozesse in Submodulen mit
deren ungeprüfter Konfiguration).
Fail-closed-Konfigurationsprüfung VOR dem ersten Status-/Diff-Aufruf (auch bei overlap): `.git/config` wird nur über `git config --file … --list -z
--no-includes` gelesen (führt nichts aus) und gegen eine ALLOWLIST harmloser Schlüssel geprüft (core.repositoryformatversion/filemode (nur Wert true|false)/bare/
logallrefupdates/ignorecase/precomposeunicode, remote.*.url|fetch|pushurl (url nicht `ext::`), branch.*.remote|merge|rebase, user.name/email, gc.*,
receive.*, pack.*, init.defaultbranch, safe.directory, extensions.* außer worktreeConfig). Alles andere (core.fsmonitor, core.hooksPath, alias.*, filter.*,
diff.*, include.*, credential.*, url.*, …) -> Exit 2, Meldung nennt nur den Schlüsselnamen (gekürzt), nie Werte. `.git/info/attributes` mit
`filter=`/`diff=`/`merge=` -> Exit 2; `.git/config.worktree` vorhanden -> Exit 2. `.git` als Datei (Worktree/Submodul/gitdir-Verweis) oder Symlink -> Exit 2.
Das Repo-Toplevel wird ohne git durch Aufwärtssuche nach `.git` bestimmt (vor der Prüfung läuft kein git im Ziel-Repo).
`.gitattributes` im Arbeitsbaum mit `filter=` ist harmlos, solange keine filter.*-Konfiguration existiert (durch die Allowlist ausgeschlossen).
NICHT neutralisierbar / Restrisiken (ehrlich): (a) git liest die Repo-Konfiguration immer; Schutz ist die Allowlist, nicht `-c` (z. B. filter.<x>.clean,
merge-Treiber oder unbekannte künftige Schlüssel lassen sich nicht pauschal per -c überschreiben); (b) TOCTOU: ändert jemand `.git/config` zwischen
Prüfung und git-Aufruf, ist der Lauf nicht abgesichert (Folgecheck würde die Änderung als .git-Integrität melden); (c) `include.path` lässt sich per -c
nicht abschalten (nur über Allowlist/--no-includes beim Lesen); (d) das aufgerufene `git`-Binary und /usr/bin, /bin sowie das
Dateisystem werden als vertrauenswürdig angenommen (ein root-Agent könnte sie ersetzen); (e) Hooks werden vom Skript nie ausgeführt (core.hooksPath=/dev/null), ihre Inhalte aber nicht
bewertet, nur gehasht; (f) Objekt-Datenbank (alternates sind erfasst, Pack-Inhalte nicht).

Snapshot-Manipulationsschutz: `snapshot --out` MUSS außerhalb des Repos liegen (realpath inkl. Symlinks; sonst Exit 2). Die Datei (Modus 0600, nicht
über Symlinks) enthält `mac` = HMAC-SHA256 über die kanonische JSON-Darstellung von {version, head, files, flags, gitmeta}; der zufällige 32-Byte-Schlüssel
(secrets.token_hex) steht NICHT in der Datei. `check` liest ihn aus --key-file (hat Vorrang) oder CFS_SNAPSHOT_KEY und prüft mit hmac.compare_digest; fehlender Schlüssel, fehlender
oder falscher MAC -> Exit 2. EHRLICH: das schützt nur gegen Manipulation der Snapshot-Datei OHNE Kenntnis des Schlüssels; nicht gegen einen Angreifer
(z. B. root-Agent), der Prozessspeicher oder Umgebung des Orchestrators lesen oder den Check selbst austauschen kann.

Glob-Syntax (eigener Matcher): `*` und `?` matchen NICHT über `/`; `**` matcht beliebig viele Verzeichnisebenen (`a/**/b` trifft auch `a/b`);
`[abc]` Zeichenklasse; ein Muster mit `/` am Ende ist ein Verzeichnispräfix; ein Muster ohne Wildcard trifft genau diesen Pfad.
ALLUMFASSENDE Muster werden von `check` und `overlap` mit Exit 2 abgelehnt. Definition (PROBEBASIERT, daher nur eine Näherung): das Muster passt auf alle drei
Pfade `a.txt`, `x/y/z/w.txt`, `.hidden/a` (z. B. `**`, `**/*`, `**/**`) ODER auf >= 90 % der Sondierungspfade PROBE_PATHS (66 Pfade: `a`, `A`, `.x`, `x.y.z`,
`1/2`, `_`, `-x`, `.hidden/a`, überwiegend Pfade mit Punkt in verschiedenen Tiefen); damit fallen auch `[!a]**`, `**/*.*`, `**/?*` heraus; ebenso leere oder
mit `/` beginnende Muster. Muster, die ein ganzes Top-Level-
Verzeichnis freigeben (`backend/**`, `backend/**/*`, `backend/`), werden nur mit Warnung auf stderr akzeptiert. Nicht erfasst (Grenze der Probe): Muster, die
< 90 % der Sondierungspfade treffen, aber real fast alles (z. B. Muster, die nur wenige Sondierungspfade auslassen, aber reale Pfade fast vollständig treffen, wie `[!q][!r]*/**` nicht unbedingt).

Exit-Codes: 0 = OK, 1 = Regelverstoß, .git-Integritätsverletzung, Index-Flag-Änderung bzw. Überschneidung, 2 = Bedienfehler oder interner Fehler (Meldung auf
stderr; z. B. fehlendes --allowed, allumfassendes Muster, fehlender Schlüssel/MAC, Snapshot im Repo, unzulässige Git-Konfiguration, fehlerhafter/unlesbarer
Snapshot, Snapshot-HEAD nicht mehr vorhanden oder nicht mehr Vorfahre von HEAD, git-Fehler, unlesbare Datei). Das Skript verändert nichts im Repository
(nur Lesen von git-Ausgaben und Dateien; geschrieben wird nur die --out-Datei).

Grenzen (NICHT erkannt): Änderungen außerhalb des Repositories; Änderungen, die vor dem Check wieder rückgängig gemacht wurden (Netto-Null);
reine Moduswechsel, wenn git `core.fileMode=false` gesetzt hat (core.filemode wird mit Wert true ODER false akzeptiert, weil Windows-Init false setzt;
bei false sieht `git status` keine Moduswechsel, das Skript hasht aber Kandidatendateien samt Ausführbit; eine Änderung des Wertes nach dem Snapshot ist über gitmeta ein Verstoß);
Inhalte in ignorierten Rauschdateien, die nicht skriptartig sind (SCRIPT_SUFFIXES); mehrfach hin- und her-committete Änderungen ohne Netto-Differenz;
wer die Dateien zwischen Snapshot und Check selbst verändert, ist nicht zuordenbar (das Skript kennt keine Agenten, nur Pfade). Weitere Grenzen:
Submodule/geschachtelte Repos: erfasst werden Pfad, Gitlink-Commit (Index) und, OHNE git-Aufruf im geschachtelten Repo, der aufgelöste HEAD von `<pfad>/.git`
(Datei .git/HEAD; bei `ref:` die lose Ref-Datei bzw. packed-refs; `.git` als Datei: Hash). Ein geänderter HEAD gilt wie jede Änderung dieses Pfades
(Verstoß, wenn nicht erlaubt). Nicht erfasst: Inhalt/Objekte/Konfiguration des geschachtelten Repos, geschachtelte Repos in ignorierten Rauschverzeichnissen; Windows-Groß-/Kleinschreibung (Pfade werden
case-sensitiv verglichen, auf Windows nicht getestet); Muster wie `docs/*/` (Wildcard + Verzeichnis-Schrägstrich) matchen nicht (Fehlalarm-Richtung);
`overlap` erkennt Überschneidungen nur für vorhandene Dateien und wortgleiche Muster. Rückgängig gemachter Snapshot-Zustand (Datei war dirty, ist jetzt
sauber mit anderem Inhalt) wird gemeldet."""
from __future__ import annotations

import sys  # eingebaut: darf vor der Isolationsprüfung importiert werden

if __name__ == "__main__" and not sys.flags.isolated:  # VOR allen weiteren Importen (sys.path[0] = scripts/ wäre sonst ein Einfallstor)
    sys.stderr.write("FEHLER: bitte im isolierten Modus starten: python3 -I scripts/check_file_set.py <snapshot|check|overlap> …\n"
                     "(ohne -I könnte eine in scripts/ abgelegte hmac.py/hashlib.py statt der Standardbibliothek laufen)\n")
    raise SystemExit(2)

import argparse  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GONE = "<gelöscht>"
SNAPSHOT_VERSION = 3
KEY_ENV = "CFS_SNAPSHOT_KEY"
SAFE_PATH = "/usr/bin:/bin"  # bewusst ohne /usr/local/bin

# Rauschen: gilt NUR für ignorierte Dateien (siehe ignored_files). Verzeichnisnamen (beliebige Ebene) und Dateiendungen.
NOISE_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".cache", ".vite",
    ".parcel-cache", "dist", "build", "coverage", "htmlcov", "test-results", "playwright-report",
})
NOISE_SUFFIXES = (".pyc", ".pyo", ".egg-info")
NOISE_FILES = frozenset({".coverage"})
# Ausführbare/skriptartige Dateien werden auch im Rauschen gehasht (ohne Ausnahme).
SCRIPT_SUFFIXES = (".py", ".pth", ".pyc", ".pyo", ".pyd", ".js", ".cjs", ".mjs", ".sh", ".so", ".dll", ".dylib", ".node", ".ps1", ".bat", ".cmd")

# Schlüssel der Repo-Konfiguration, die als harmlos gelten (alles andere -> Exit 2). Schlüssel kommen von git klein geschrieben (Sektion/Name).
CONFIG_ALLOW_EXACT = frozenset({
    "core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates", "core.ignorecase", "core.precomposeunicode",
    "init.defaultbranch", "user.name", "user.email", "safe.directory",
})
CONFIG_ALLOW_RE = [re.compile(p, re.IGNORECASE) for p in (
    r"remote\..+\.(url|fetch|pushurl)", r"branch\..+\.(remote|merge|rebase)", r"(gc|receive|pack)\..+", r"extensions\..+",
)]
CONFIG_DENY_EXACT = frozenset({"extensions.worktreeconfig"})  # würde .git/config.worktree einbinden
ATTR_BAD_RE = re.compile(r"(?:^|\s)(?:filter|diff|merge)=")  # filter=/diff=/merge=<name> in info/attributes
CORE_PROBES = ("a.txt", "x/y/z/w.txt", ".hidden/a")
_PD = ("", "src/", "docs/", "backend/leventum/", "frontend/src/", ".github/workflows/", "tests/")
_PN = ("main.py", "README.md", "index.ts", "x.json", "Z.TXT", "m.c", "b.h", "notes.v2.txt")
PROBE_PATHS = CORE_PROBES + ("a", "A", ".x", "x.y.z", "1/2", "_", "-x") + tuple(d + n for d in _PD for n in _PN)
PROBE_THRESHOLD = 0.9

# Alle git-Aufrufe: diese -c-Überschreibungen (Kommandozeile hat Vorrang vor der Repo-Konfiguration).
GIT_OVERRIDES = (
    "core.quotepath=off", "core.fsmonitor=false", "core.hooksPath=" + os.devnull, "core.untrackedCache=false", "core.attributesFile=" + os.devnull,
    "diff.external=", "core.pager=cat", "core.editor=true", "core.sshCommand=true", "core.askPass=", "core.gitProxy=", "credential.helper=",
    "status.submoduleSummary=false", "submodule.recurse=false", "core.sparseCheckout=false",
)


class ToolError(Exception):
    """Bedienfehler oder interner Fehler -> Exit-Code 2."""


def show(path: str) -> str:
    """Pfad ausgebbar machen (auch nicht-UTF-8-Bytes)."""
    return os.fsencode(path).decode("utf-8", "backslashreplace")


# --- git (einziger Einstiegspunkt) ----------------------------------------------------------------------
def git_env() -> dict[str, str]:
    """Neu aufgebaute, bereinigte Umgebung; nichts aus der Umgebung des Aufrufers wird übernommen."""
    return {
        "PATH": SAFE_PATH, "HOME": "/nonexistent", "LC_ALL": "C", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "GIT_PAGER": "cat", "GIT_NO_LAZY_FETCH": "1",
        "GIT_ALLOW_PROTOCOL": "none", "GIT_PROTOCOL_FROM_USER": "0", "GIT_ATTR_NOSYSTEM": "1",
    }


def git_argv(*args: str) -> list[str]:
    exe = shutil.which("git", path=SAFE_PATH)
    if not exe:
        raise ToolError(f"git nicht gefunden in {SAFE_PATH}")
    base = [exe, "--no-pager", "--no-optional-locks", "--no-replace-objects"]
    for o in GIT_OVERRIDES:
        base += ["-c", o]
    return base + list(args)


def git(top: Path | str, *args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(git_argv(*args), cwd=top, env=git_env(), capture_output=True, stdin=subprocess.DEVNULL)
    except OSError as e:
        raise ToolError(f"git nicht ausführbar: {e}") from e
    if r.returncode not in ok:
        raise ToolError(f"git {' '.join(args)} fehlgeschlagen (Exit {r.returncode}): {r.stderr.decode('utf-8', 'replace').strip()}")
    return r


# --- Repository finden und Konfiguration prüfen (ohne git im Ziel-Repo) ----------------------------------
def find_top(repo: Path) -> Path:
    if not repo.is_dir():
        raise ToolError(f"Repository-Pfad existiert nicht: {repo}")
    cur = Path(os.path.realpath(repo))
    for d in (cur, *cur.parents):
        gp = d / ".git"
        if os.path.lexists(gp):
            st = os.lstat(gp)
            if stat.S_ISLNK(st.st_mode):
                raise ToolError(f".git ist ein Symlink ({d}); abgelehnt")
            if stat.S_ISDIR(st.st_mode):
                return d
            raise ToolError(f".git ist eine Datei (Worktree/Submodul/gitdir-Verweis) in {d}; nicht unterstützt, abgelehnt")
    raise ToolError(f"kein git-Repository: {repo}")


def short(s: str, n: int = 60) -> str:
    s = show(s)
    return s if len(s) <= n else s[:n] + "…"


def config_problems(entries: list[tuple[str, str | None]]) -> list[str]:
    bad = []
    for key, val in entries:
        lk = key.lower()
        if lk in CONFIG_DENY_EXACT:
            bad.append(key)
        elif lk == "core.filemode":
            if (val or "").strip().lower() not in ("true", "false"):
                bad.append(key)
        elif lk in CONFIG_ALLOW_EXACT or any(r.fullmatch(key) for r in CONFIG_ALLOW_RE):
            if re.fullmatch(r"remote\..+\.(url|pushurl)", key, re.IGNORECASE) and (val or "").lower().startswith("ext::"):
                bad.append(key)  # ext:: führt Befehle aus (nur bei fetch/push, trotzdem abgelehnt)
        else:
            bad.append(key)
    return bad


def check_git_config(top: Path) -> None:
    gd = top / ".git"
    if os.path.lexists(gd / "config.worktree"):
        raise ToolError(".git/config.worktree vorhanden (zusätzliche Konfigurationsquelle); abgelehnt, nichts wurde ausgeführt")
    cfg = gd / "config"
    if not os.path.lexists(cfg) or stat.S_ISLNK(os.lstat(cfg).st_mode) or not stat.S_ISREG(os.lstat(cfg).st_mode):
        raise ToolError(".git/config fehlt oder ist keine normale Datei; abgelehnt")
    raw = git("/", "config", "--file", str(cfg), "--list", "-z", "--no-includes").stdout
    entries: list[tuple[str, str | None]] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        k, sep, v = item.partition(b"\n")
        entries.append((os.fsdecode(k), os.fsdecode(v) if sep else None))
    bad = config_problems(entries)
    if bad:
        names = ", ".join(sorted({short(b) for b in bad})[:8])
        raise ToolError(f"unzulässige Git-Konfiguration in .git/config (nur Allowlist harmloser Schlüssel erlaubt): {names}"
                        f"{' …' if len(set(bad)) > 8 else ''}. Nichts wurde ausgeführt; Konfiguration bereinigen (Werte werden nicht ausgegeben).")
    attr = gd / "info" / "attributes"
    if os.path.lexists(attr):
        if stat.S_ISLNK(os.lstat(attr).st_mode):
            raise ToolError(".git/info/attributes ist ein Symlink; abgelehnt")
        try:
            lines = attr.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            raise ToolError(f".git/info/attributes nicht lesbar: {e}") from e
        if any(ATTR_BAD_RE.search(ln) for ln in lines if not ln.lstrip().startswith("#")):
            raise ToolError(".git/info/attributes enthält filter=/diff=/merge=-Einträge; abgelehnt, nichts wurde ausgeführt")


def prepare(repo: Path) -> Path:
    """Toplevel finden und Konfiguration fail-closed prüfen, BEVOR irgendein status/diff läuft."""
    top = find_top(repo)
    check_git_config(top)
    r = git(top, "rev-parse", "--show-toplevel").stdout.strip()
    if os.path.realpath(os.fsdecode(r)) != str(top):
        raise ToolError(f"git meldet ein anderes Toplevel ({os.fsdecode(r)}) als die .git-Suche ({top}); abgelehnt")
    return top


# --- git-Abfragen --------------------------------------------------------------------------------------
def split_z(data: bytes) -> list[str]:
    return [os.fsdecode(x) for x in data.split(b"\0") if x]


def head_commit(top: Path) -> str:
    r = git(top, "rev-parse", "--verify", "-q", "HEAD^{commit}", ok=(0, 1))
    return r.stdout.decode().strip() if r.returncode == 0 else ""  # "" = noch kein Commit


def status_paths(top: Path) -> list[str]:
    parts = git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all").stdout.split(b"\0")
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


def is_script(path: str) -> bool:
    return path.lower().endswith(SCRIPT_SUFFIXES)


def is_native_executable(top: Path, path: str) -> bool:
    """Reguläre Datei mit Ausführbit UND ELF-/Shebang-Magic (erste 4 Bytes werden nur bei gesetztem Ausführbit gelesen)."""
    p = top / path
    try:
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode) or not st.st_mode & 0o111:
            return False
        with open(p, "rb") as f:
            head = f.read(4)
    except OSError:
        return False
    return head == b"\x7fELF" or head[:2] == b"#!"


def ignored_files(top: Path) -> list[str]:
    out = split_z(git(top, "ls-files", "-z", "--others", "--ignored", "--exclude-standard").stdout)
    return [p for p in out if not is_noise(p) or is_script(p) or is_native_executable(top, p)]


def index_flags(top: Path) -> dict[str, str]:
    """Pfad -> Tag für Dateien mit assume-unchanged (h) oder skip-worktree (S, s = beides). Normale Tags (H, M, R, C, K, ?) zählen nicht."""
    flags: dict[str, str] = {}
    for e in git(top, "ls-files", "-v", "-z").stdout.split(b"\0"):
        if len(e) < 3:
            continue
        tag = e[:1].decode("ascii", "replace")
        if tag == "S" or tag.islower():
            flags[os.fsdecode(e[2:])] = tag
    return flags


def gitlinks(top: Path) -> dict[str, str]:
    res: dict[str, str] = {}
    for e in git(top, "ls-files", "-s", "-z").stdout.split(b"\0"):
        head, _, path = e.partition(b"\t")
        f = head.split()
        if len(f) >= 2 and f[0] == b"160000":
            res[os.fsdecode(path)] = f[1].decode()
    return res


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
def _read_small(p: Path) -> str | None:
    try:
        if not stat.S_ISREG(os.lstat(p).st_mode):
            return None
        with open(p, "rb") as f:
            return f.read(4096).decode("utf-8", "replace").strip()
    except OSError:
        return None


def nested_state(d: Path) -> str:
    """HEAD eines geschachtelten Repos (<d>/.git) ohne git-Aufruf: Dateien lesen. Leer = kein geschachteltes Repo."""
    g = d / ".git"
    try:
        gst = os.lstat(g)
    except OSError:
        return ""
    if stat.S_ISLNK(gst.st_mode):
        return "nested:symlink:" + os.fsdecode(os.readlink(g))
    if not stat.S_ISDIR(gst.st_mode):
        c = _read_small(g)
        return "nested:gitfile:" + hashlib.sha256((c or "").encode()).hexdigest()
    head = _read_small(g / "HEAD")
    if head is None:
        return "nested:head:unreadable"
    if head.startswith("ref:"):
        ref = head[4:].strip()
        if ref.startswith("/") or ".." in ref.split("/"):
            return "nested:head:" + head
        oid = _read_small(g / ref)
        if oid is None:
            packed = _read_small(g / "packed-refs") or ""
            oid = next((ln.split()[0] for ln in packed.splitlines() if ln.endswith(" " + ref) and not ln.startswith(("#", "^"))), "unborn")
        return f"nested:{ref}:{oid}"
    return "nested:detached:" + head


def fingerprint_abs(p: Path, label: str) -> str:
    try:
        st = os.lstat(p)
    except (FileNotFoundError, NotADirectoryError):
        return GONE
    except OSError as e:
        raise ToolError(f"Datei nicht lesbar: {show(label)}: {e}") from e
    if stat.S_ISLNK(st.st_mode):
        try:
            return "symlink:" + os.fsdecode(os.readlink(p))  # Ziel, dem Link wird nicht gefolgt (auch kaputte/Verzeichnis-Links)
        except OSError as e:
            raise ToolError(f"Symlink nicht lesbar: {show(label)}: {e}") from e
    if stat.S_ISDIR(st.st_mode):
        ns = nested_state(p)
        return "dir" + (":" + ns if ns else "")  # z. B. geschachteltes Repo/Submodul; Inhalt wird von git einzeln gemeldet
    if stat.S_ISREG(st.st_mode):
        try:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        except OSError as e:
            raise ToolError(f"Datei nicht lesbar: {show(label)}: {e}") from e
        return f"file:{'x' if st.st_mode & stat.S_IXUSR else '-'}:{h.hexdigest()}"
    return "other"


def fingerprint(top: Path, rel: str) -> str:
    return fingerprint_abs(top / rel, rel)


def walk_files(base: Path, label: str, out: dict[str, str]) -> None:
    """Alle Dateien/Symlinks unterhalb base (rekursiv, ohne Symlinks zu folgen) fingerprinten."""
    try:
        entries = sorted(os.scandir(base), key=lambda e: e.name)
    except FileNotFoundError:
        return
    except OSError as e:
        raise ToolError(f"Verzeichnis nicht lesbar: {label}: {e}") from e
    for e in entries:
        lab = f"{label}/{e.name}"
        if e.is_dir(follow_symlinks=False):
            walk_files(Path(e.path), lab, out)
        else:
            out[lab] = fingerprint_abs(Path(e.path), lab)


def gitmeta(top: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    gd = top / ".git"
    for rel in ("config", "shallow", "objects/info/alternates"):
        p = gd / rel
        if os.path.lexists(p):
            meta[f".git/{rel}"] = fingerprint_abs(p, f".git/{rel}")
    walk_files(gd / "info", ".git/info", meta)
    walk_files(gd / "hooks", ".git/hooks", meta)
    for line in git(top, "for-each-ref", "--format=%(refname) %(objectname)", "refs/replace").stdout.decode("utf-8", "replace").splitlines():
        name, _, oid = line.partition(" ")
        meta[name] = oid
    return meta


def scan(top: Path, extra: list[str] = ()) -> dict:
    """Vollständiger Zustand: files, flags, gitmeta."""
    flags = index_flags(top)
    links = gitlinks(top)
    cand = set(status_paths(top)) | set(ignored_files(top)) | set(extra) | set(flags) | set(links)
    files = {}
    for p in sorted(cand):
        if p in links:
            ns = nested_state(top / p)
            files[p] = "gitlink:" + links[p] + (":" + ns if ns else "")
        else:
            files[p] = fingerprint(top, p)
    return {"files": files, "flags": flags, "gitmeta": gitmeta(top)}


def collect(top: Path, extra: list[str] = ()) -> dict[str, str]:
    return scan(top, extra)["files"]


def dirty_files(repo: Path = ROOT) -> dict[str, str]:
    return collect(prepare(repo))


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


def validate_patterns(patterns: list[str]) -> None:
    """Allumfassende/ungültige Muster -> ToolError (Exit 2); Top-Level-Verzeichnisfreigaben -> Warnung."""
    for p in patterns:
        if not p.strip():
            raise ToolError("leeres Muster abgelehnt")
        if p.startswith("/"):
            raise ToolError(f"Muster beginnt mit '/': {p} (Pfade sind relativ zum Repository; `/**` o. ä. gilt als allumfassend) – abgelehnt")
        hits = sum(1 for x in PROBE_PATHS if match(x, [p]))
        if all(match(x, [p]) for x in CORE_PROBES) or hits >= PROBE_THRESHOLD * len(PROBE_PATHS):
            raise ToolError(f"allumfassendes Muster abgelehnt: {p} (passt auf {hits} von {len(PROBE_PATHS)} Sondierungspfaden – hebelt die Dateimengen-Kontrolle aus)")
        if re.fullmatch(r"[*?\[\]!.^-]*[*?\[][*?\[\]!.^-]*/[*?/]*", p):  # Wildcard im ersten Segment und nur Wildcards dahinter (`*/**`, `*/*`, `?/**`): gibt .claude/** und scripts/** pauschal frei (Review, Nachweisgrad: Handrechnung 77 % < 90 %)
            raise ToolError(f"Muster mit Wildcard im ersten Segment ohne einschränkenden Rest abgelehnt: {p}")
        if re.fullmatch(r"[^*?\[/]+/(?:\*\*(?:/\*{1,2})?)?", p):
            print(f"WARNUNG: Muster {p} gibt ein ganzes Top-Level-Verzeichnis frei", file=sys.stderr)


# --- Snapshot, MAC --------------------------------------------------------------------------------------
def canonical(data: dict) -> bytes:
    core = {k: data[k] for k in ("version", "head", "files", "flags", "gitmeta")}
    return json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sign(data: dict, key: str) -> str:
    return hmac.new(key.encode("utf-8"), canonical(data), hashlib.sha256).hexdigest()


def write_private(path: str, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(text)


def ensure_outside(top: Path, out: str) -> None:
    ro, rt = os.path.realpath(out), os.path.realpath(top)
    if ro == rt or ro.startswith(rt + os.sep):
        raise ToolError(f"--out liegt innerhalb des Repositories ({ro}); der Snapshot muss außerhalb liegen (Manipulationsschutz)")


KEY_RE = re.compile(r"[0-9a-f]{64}")


def read_key_file(top: Path, path: str) -> str:
    try:
        st = os.lstat(path)
    except OSError as e:
        raise ToolError(f"Schlüsseldatei nicht lesbar: {path}: {e}") from e
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ToolError(f"Schlüsseldatei ist keine normale Datei (Symlink?): {path}")
    if st.st_mode & 0o077:
        raise ToolError(f"Schlüsseldatei hat zu weite Rechte (erwartet 0600): {path}")
    if st.st_uid != os.geteuid():
        raise ToolError(f"Schlüsseldatei gehört einem anderen Benutzer: {path}")
    ensure_outside(top, path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            key = f.read(256).decode("ascii", "replace").strip()
    except OSError as e:
        raise ToolError(f"Schlüsseldatei nicht lesbar: {path}: {e}") from e
    if not KEY_RE.fullmatch(key):
        raise ToolError(f"Schlüsseldatei hat ungültiges Format (erwartet 64 Hex-Zeichen): {path}")
    return key


def load_snapshot(path: str, key: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ToolError(f"Snapshot nicht lesbar: {path}: {e}") from e
    need = ("version", "head", "files", "flags", "gitmeta", "mac")
    if not isinstance(data, dict) or data.get("version") != SNAPSHOT_VERSION or any(k not in data for k in need):
        raise ToolError(f"Snapshot hat ungültiges Format (erwartet Version {SNAPSHOT_VERSION}; neu erzeugen): {path}")
    if not isinstance(data["mac"], str) or not isinstance(data["head"], str) or not all(isinstance(data[k], dict) for k in ("files", "flags", "gitmeta")):
        raise ToolError(f"Snapshot hat ungültiges Format: {path}")
    if not all(isinstance(v, str) for k in ("files", "flags", "gitmeta") for v in data[k].values()):
        raise ToolError(f"Snapshot hat ungültiges Format: {path}")
    if not hmac.compare_digest(sign(data, key).encode(), data["mac"].encode("utf-8", "replace")):
        raise ToolError("Snapshot-MAC ungültig (Datei manipuliert oder falscher Schlüssel); Check nicht möglich")
    return data


# --- Kommandos -----------------------------------------------------------------------------------------
def cmd_snapshot(a) -> int:
    top = find_top(a.repo)
    ensure_outside(top, a.out)
    if a.key_file:
        ensure_outside(top, a.key_file)
        if os.path.realpath(a.key_file) == os.path.realpath(a.out):
            raise ToolError("--key-file und --out dürfen nicht dieselbe Datei sein")
    top = prepare(a.repo)
    st = scan(top)
    data = {"version": SNAPSHOT_VERSION, "head": head_commit(top), **st}
    key = secrets.token_hex(32)
    data["mac"] = sign(data, key)
    try:
        if a.key_file:
            write_private(a.key_file, key + "\n")
        write_private(a.out, json.dumps(data, indent=1))
    except OSError as e:
        raise ToolError(f"Snapshot nicht schreibbar: {e}") from e
    print(f"Snapshot: HEAD {data['head'][:12] or '(kein Commit)'}, {len(st['files'])} veränderte/untracked/ignorierte Dateien, "
          f"{len(st['flags'])} Index-Flags, {len(st['gitmeta'])} .git-Metadaten")
    if a.key_file:
        print(f"Schlüssel in Datei geschrieben (0600): {a.key_file}")
    else:
        print(f"KEY={key}")  # einmalig; nicht in der Datei. Als CFS_SNAPSHOT_KEY an `check` übergeben.
    return 0


def violations(snapshot: dict[str, str], now: dict[str, str], allowed: list[str]) -> list[str]:
    changed = sorted(p for p, h in now.items() if snapshot.get(p) != h)
    changed += sorted(p for p in snapshot if p not in now)  # Datei war dirty und ist jetzt sauber/zurückgesetzt
    return [p for p in changed if not match(p, allowed)]


def integrity_violations(snap: dict[str, str], now: dict[str, str]) -> list[str]:
    res = []
    for k in sorted(set(snap) | set(now)):
        if k not in snap:
            res.append(f".git-Integrität verletzt: {show(k)} (neu)")
        elif k not in now:
            res.append(f".git-Integrität verletzt: {show(k)} (gelöscht)")
        elif snap[k] != now[k]:
            res.append(f".git-Integrität verletzt: {show(k)} (geändert)")
    return res


def flag_violations(snap: dict[str, str], now: dict[str, str]) -> list[str]:
    res = []
    for p in sorted(now):
        if p not in snap:
            res.append(f"Index-Flag gesetzt: {show(p)} ({now[p]})")
        elif snap[p] != now[p]:
            res.append(f"Index-Flag geändert: {show(p)} ({snap[p]} -> {now[p]})")
    res += [f"Index-Flag entfernt: {show(p)}" for p in sorted(snap) if p not in now]
    return res


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
    validate_patterns(a.allowed)
    if a.key_file:
        key = read_key_file(find_top(a.repo), a.key_file)
    else:
        key = os.environ.get(KEY_ENV, "")
    if not key:
        raise ToolError(f"Umgebungsvariable {KEY_ENV} fehlt (Schlüssel aus `snapshot`, nicht per argv; oder --key-file)")
    top = prepare(a.repo)
    snap = load_snapshot(a.snapshot, key)
    check_head(top, snap["head"])
    now = scan(top, extra=list(snap["files"]) + committed_paths(top, snap["head"]))
    meta_bad = integrity_violations(snap["gitmeta"], now["gitmeta"])
    flag_bad = flag_violations(snap["flags"], now["flags"])
    bad = violations(snap["files"], now["files"], a.allowed)
    for m in meta_bad + flag_bad:
        print(f"VERSTOSS {m}")
    for p in bad:
        print(f"VERSTOSS außerhalb der Dateimenge: {show(p)}")
    n = len(meta_bad) + len(flag_bad) + len(bad)
    print("OK – alle Änderungen liegen in der Dateimenge" if not n else f"{n} Verstoß/Verstöße")
    return 1 if n else 0


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
    for pats in sets.values():
        validate_patterns(pats)
    top = prepare(a.repo)
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
    s = sub.add_parser("snapshot", parents=[common]); s.add_argument("--out", required=True); s.add_argument("--key-file", default=None, help="Schlüssel in diese Datei (0600, außerhalb des Repos) statt auf stdout"); s.set_defaults(fn=cmd_snapshot)
    c = sub.add_parser("check", parents=[common]); c.add_argument("--snapshot", required=True); c.add_argument("--key-file", default=None, help="Schlüsseldatei (0600) statt CFS_SNAPSHOT_KEY"); c.add_argument("--allowed", action="append", default=[]); c.set_defaults(fn=cmd_check)
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
