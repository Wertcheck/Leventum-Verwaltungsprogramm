#!/usr/bin/env python3
"""Kontrollierte Commit-Übergabe an eine getrennte Prüfumgebung (Komponente; KEIN Sicherheitsversprechen darüber hinaus).

Kontext: Isolation innerhalb desselben Kernels (uid/Mounts/chattr/Container) schützt nicht gegen einen Entwicklungs-Agenten als root. Eine echte
Trennung braucht einen anderen Kernel (separate Cloud-Sitzung/microVM, `create_session` mit festem `source_revision` = volle 40-hex-Commit-SHA; die
Plattform akzeptiert keine Kurz-SHA). Dieses Skript ist die plattformunabhängige, testbare Komponente dieser Übergabe. Nur Python-Standardbibliothek.

AUFRUF (Pflicht `-I`, wie scripts/check_file_set.py; ohne -I bricht das Skript VOR allen Importen mit Exit 2 ab):
    python3 -I scripts/review_handoff.py manifest      --repo R --commit <40hex> --out FILE [--key-file KF]            (Orchestrator, Dev-VM)
    python3 -I scripts/review_handoff.py verify        --manifest FILE --checkout DIR [--key-file KF] [--env-check] [--home H] [--mountinfo F]
                                                                                                                       (Review-Umgebung)
    python3 -I scripts/review_handoff.py check-report  --expect FILE --report FILE [--session FILE] [--allowed-tools Read,Grep,Glob]
                                                       [--allow-no-session]                                            (Orchestrator)
    python3 -I scripts/review_handoff.py remote-check  --repo R --commit <40hex> --ref refs/heads/x [--url U] [--allow-protocol https|file]
                                                                                                                       (Orchestrator; Netz!)
Exit-Codes: 0 = OK, 1 = Verstoß/Abweichung (verify: mindestens ein FAIL), 2 = Bedien-/Konfigurationsfehler oder interner Fehler (Ausnahmen werden
NIE zu 0). Ausgaben `PASS|FAIL|WARN <id>: …`, `RESULT: OK|BLOCKED`. Es werden nie Secret-WERTE ausgegeben (nur Namen von Variablen/Konfigurations-
schlüsseln; bei `_FILE`-Variablen Pfad/Modus/Größe, nie Inhalt). Netzzugriff gibt es ausschließlich im Unterbefehl `remote-check`.

UNTERBEFEHLE
* manifest: liest aus dem Git-OBJEKT (nicht aus dem Arbeitsbaum) `tree` und `git ls-tree -r -z --full-tree`; Eintrag = [mode, blob_sha, path], sortiert.
  Abgelehnt (Exit 1, nichts geschrieben): Symlinks (120000), Gitlinks (160000), Modus ≠ 100644/100755, Pfade mit leerer/`.`/`..`-Komponente, absolut,
  Backslash, Doppelpunkt, Steuerzeichen, Nicht-UTF-8, Komponente `.git` (case-insensitiv, auch mit angehängten Punkten/Leerzeichen, `git~N`,
  HFS-ignorierbare Unicode-Zeichen), Pfadkollisionen bei Groß-/Kleinschreibung. Git-Umgebung kontrolliert (wie check_file_set.py: PATH nur
  /usr/bin:/bin, GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM, `--no-replace-objects`, `-c core.fsmonitor=false …`); VOR dem ersten git-Aufruf im
  Repository wird `.git/config` mit EIGENEM Parser (ohne git, ohne Includes) gegen eine Allowlist geprüft; `.git` muss echtes Verzeichnis sein;
  refs/replace, alternates, http-alternates, grafts, config.worktree, filter=/diff=/merge= in info/attributes -> Exit 2. Aktive Hooks bleiben beim
  `manifest` unbeachtet (core.hooksPath=/dev/null; sie werden nie ausgeführt), werden aber von `verify` verlangt-leer. JSON:
  {version, commit, tree, entries, entry_count, manifest_sha256 [, mac]}; `manifest_sha256` = SHA-256 über die kanonische Darstellung von
  version/commit/tree/entries; `mac` (nur mit --key-file) = HMAC-SHA256 über dieselbe Darstellung. Schlüsseldatei: außerhalb des Repos, 0600, kein
  Symlink, 64 Hex. Ausgabedatei: außerhalb des Repos, 0600, O_EXCL|O_NOFOLLOW (existiert sie schon -> Exit 2).
* verify (läuft IN der Review-Umgebung): (a) Manifest-Konsistenz (Hash nachrechnen, mac falls Schlüssel), Einträge erneut validiert; (b) `.git` des
  Checkouts OHNE git-Aufruf (HEAD aus .git/HEAD bzw. losen Refs/packed-refs == manifest.commit, Config-Allowlist, keine Hooks/replace/alternates/
  grafts/Attribut-Filter); (c) Arbeitsbaum: Dateimenge (ohne `.git`) == Manifest EXAKT, keine Symlinks/Sonderdateien, Hardlinks (nlink>1) = FAIL,
  je Datei Git-Blob-SHA-1 und Ausführbit == Manifest; (d) `/proc/self/mountinfo` (oder --mountinfo): kein Mount unterhalb des Checkouts, Checkout
  selbst kein Bind-/9p-/virtiofs-/Netz-/fuse-Mount, Einbettung in solch ein Dateisystem = FAIL; (e) mit --env-check: Namen von Umgebungsvariablen
  (Muster TOKEN, SECRET, PASSWORD, …, GITHUB, GH_, AWS_, ANTHROPIC_API, SESSION_INGRESS, …), `*_FILE`-Variablen auf existierende Dateien,
  Anmeldedateien im Home (~/.ssh-Privatschlüssel, ~/.git-credentials, ~/.netrc, ~/.config/gh, ~/.aws, ~/.config/gcloud, ~/.docker/config.json mit
  auths/credsStore, ~/.npmrc mit _authToken, ~/.pypirc, ~/.gitconfig mit credential.*/url.*.insteadOf/http.*extraheader); Proxy-Variablen nur WARN.
  Schluss: `RESULT: OK|BLOCKED` und `ATTESTATION {commit, tree, manifest_sha256, checked_at, env_check, findings, hostname_hash, uid}`.
* check-report (Orchestrator, fail-closed): vergleicht die vom Orchestrator gehaltenen Erwartungswerte {commit, tree, manifest_sha256,
  environment_id, nonce, min_ts} mit dem Bericht des Reviewers {commit, tree, manifest_sha256, session_id, environment_id, tools, nonce,
  attestation, findings} UND mit einem Plattform-Auszug (`--session`: id, environment_id, parent, sources[0].git_repository.revision, status).
  Ohne --session ist der Bericht reine Selbstauskunft: das ist FAIL, außer mit ausdrücklichem --allow-no-session (dann WARN). Fehlende Felder ->
  Exit 2. tools müssen nicht leer und ⊆ --allowed-tools sein (Standard exakt Read,Grep,Glob). Attestation: env_check == true, findings == 0,
  checked_at ≥ min_ts, commit/tree/manifest_sha256 wie erwartet.
* remote-check (Orchestrator): `git ls-remote` (kontrollierte Umgebung, GIT_ALLOW_PROTOCOL nur https bzw. file mit --allow-protocol file; URL aus
  --url oder aus remote.origin.url der Allowlist-geprüften Repo-Konfiguration; nur lesend, cwd `/`). Remote-Tip von --ref == commit: PASS. Anderer
  Tip: WARN, falls der Tip lokal vorhanden und der Commit Vorfahre ist (`merge-base --is-ancestor`); sonst FAIL „nicht belegbar“. Ref fehlt: FAIL.
  Nur dieser Befehl reicht Proxy-/CA-Variablen (HTTPS_PROXY, NO_PROXY, SSL_CERT_FILE, …) an git durch (Werte werden nie ausgegeben).

WAS DIE KOMPONENTE BEWEIST (wenn sie korrekt und unmanipuliert läuft): der Inhalt des Checkouts (Dateimenge, Inhalte als Git-Blob-SHA-1, Ausführbit)
entspricht dem Manifest, das aus dem Commit-Objekt gebildet wurde; die Umgebung zeigt keine der bekannten Secret-Spuren (Muster oben); der Bericht
eines Reviewers passt zu Erwartung und Plattform-Auszug.
WAS SIE NICHT BEWEIST (ehrlich, nicht aufwerten):
* `verify` läuft in der zu prüfenden Umgebung selbst: ein kompromittierter Prüfer/Checkout/Interpreter kann das Skript täuschen oder ersetzen.
  Deshalb die Orchestrator-seitige Gegenprüfung `check-report`; auch sie vertraut dem Bericht nur so weit, wie er mit dem Plattform-Auszug übereinstimmt.
* Der Orchestrator selbst läuft in der Dev-VM (gleicher Kernel wie der Dev-Agent): `manifest`/`check-report` sind nicht gegen einen root-Agenten dort
  geschützt (Schlüsseldatei, Erwartungsdatei sind für ihn lesbar/änderbar).
* Plattform-Tokens des Reviewers (Sitzungs-/Proxy-Zugang) können nicht entfernt werden; Umgebungsprüfung erkennt nur bekannte Namen/Dateien.
* Keine kryptografische Signatur der Plattform: der Plattform-Auszug ist ein vom Orchestrator beschaffter Text.
* Blob-Identität beruht auf Git-SHA-1 (kollisionsanfällig in der Theorie); Objektdatenbank (.git/objects), Index und Pack-Inhalte werden nicht geprüft
  (HEAD-Angabe ist nur eine Datei-Behauptung); TOCTOU zwischen Prüfung und späterer Nutzung; Windows nicht getestet (Pfad-/Mount-Logik Linux).
* Root-Dateisystem der Prüfumgebung: ob es schreibbar ist, wird nicht bewertet (bei frischem Klon in eigener microVM erwartbar).
* Mountinfo-Prüfung: ein Bind-Mount eines ganzen Dateisystems wird nur über die gleiche Gerätenummer an mehreren Pfaden erkannt.
"""
from __future__ import annotations

import sys  # eingebaut: darf vor der Isolationsprüfung importiert werden

if __name__ == "__main__" and not sys.flags.isolated:  # VOR allen weiteren Importen
    sys.stderr.write("FEHLER: bitte im isolierten Modus starten: python3 -I scripts/review_handoff.py <manifest|verify|check-report|remote-check> …\n")
    raise SystemExit(2)

import argparse  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402  (nur gethostname, kein Netzzugriff)
import stat  # noqa: E402
import subprocess  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

MANIFEST_VERSION = 1
SAFE_PATH = "/usr/bin:/bin"
SHA_RE = re.compile(r"[0-9a-f]{40}")
KEY_RE = re.compile(r"[0-9a-f]{64}")
OK_MODES = ("100644", "100755")
DEFAULT_TOOLS = "Read,Grep,Glob"

GIT_OVERRIDES = (
    "core.quotepath=off", "core.fsmonitor=false", "core.hooksPath=" + os.devnull, "core.untrackedCache=false", "core.attributesFile=" + os.devnull,
    "diff.external=", "core.pager=cat", "core.editor=true", "core.sshCommand=true", "core.askPass=", "core.gitProxy=", "credential.helper=",
    "status.submoduleSummary=false", "submodule.recurse=false", "core.sparseCheckout=false",
)

# Konfigurations-Allowlist (wie scripts/check_file_set.py; extensions.* wie review_preflight.py strenger)
CONFIG_ALLOW_EXACT = frozenset({
    "core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates", "core.ignorecase", "core.precomposeunicode",
    "init.defaultbranch", "user.name", "user.email", "safe.directory", "extensions.objectformat", "extensions.compatobjectformat",
})
CONFIG_ALLOW_RE = [re.compile(p, re.IGNORECASE) for p in (
    r"remote\..+\.(url|fetch|pushurl)", r"branch\..+\.(remote|merge|rebase)", r"(gc|receive|pack)\..+",
)]
ATTR_BAD_RE = re.compile(r"(?:^|\s)(?:filter|diff|merge)=")
HELPER_URL_RE = re.compile(r"^[A-Za-z0-9+.-]+::")  # Remote-Helfer (ext::, fd::, …) führen Befehle aus

ENV_NAME_RE = re.compile(r"TOKEN|SECRET|PASSWORD|PASSPHRASE|API_KEY|PRIVATE_KEY|CREDENTIAL|GITHUB|^GH_|^AWS_|CLOUDSDK|GOOGLE_APPLICATION|^AZURE_|"
                         r"ANTHROPIC_API|CLAUDE_CODE_MESSAGING|SESSION_INGRESS|SSH_AUTH_SOCK|NPM_TOKEN|PYPI", re.IGNORECASE)
PROXY_NAMES = frozenset({"HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY"})
PASS_THROUGH_ENV = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy",
                    "SSL_CERT_FILE", "SSL_CERT_DIR", "GIT_SSL_CAINFO", "CURL_CA_BUNDLE")  # nur für remote-check; Werte nie ausgegeben
BAD_FSTYPES = frozenset({"9p", "virtiofs", "nfs", "nfs4", "cifs", "smb3", "smbfs", "vboxsf", "ceph", "glusterfs", "afs", "lustre"})
HFS_IGNORABLE = dict.fromkeys(list(range(0x200C, 0x2010)) + list(range(0x202A, 0x202F)) + list(range(0x206A, 0x2070)) + [0xFEFF])


class ToolError(Exception):
    """Bedienfehler oder interner Fehler -> Exit-Code 2."""


def show(s: str) -> str:
    return os.fsencode(s).decode("utf-8", "backslashreplace")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: object) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class Report:
    def __init__(self) -> None:
        self.fails = 0

    def ok(self, cid: str, msg: str) -> None:
        print(f"PASS {cid}: {msg}")

    def fail(self, cid: str, msg: str) -> None:
        self.fails += 1
        print(f"FAIL {cid}: {msg}")

    def warn(self, cid: str, msg: str) -> None:
        print(f"WARN {cid}: {msg}")


def lst(items: list[str], n: int = 8) -> str:
    items = [show(i) for i in items]
    return ", ".join(items[:n]) + (f" … (+{len(items) - n})" if len(items) > n else "")


# --- git (einziger Einstiegspunkt) ----------------------------------------------------------------------------------
def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {"PATH": SAFE_PATH, "HOME": "/nonexistent", "LC_ALL": "C", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "GIT_PAGER": "cat", "GIT_NO_LAZY_FETCH": "1",
           "GIT_ALLOW_PROTOCOL": "none", "GIT_PROTOCOL_FROM_USER": "0", "GIT_ATTR_NOSYSTEM": "1"}
    env.update(extra or {})
    return env


def git_argv(*args: str) -> list[str]:
    exe = shutil.which("git", path=SAFE_PATH)
    if not exe:
        raise ToolError(f"git nicht gefunden in {SAFE_PATH}")
    base = [exe, "--no-pager", "--no-optional-locks", "--no-replace-objects"]
    for o in GIT_OVERRIDES:
        base += ["-c", o]
    return base + list(args)


def git(cwd: str, *args: str, ok: tuple[int, ...] = (0,), extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(git_argv(*args), cwd=cwd, env=git_env(extra_env), capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise ToolError(f"git nicht ausführbar: {type(e).__name__}") from e
    if r.returncode not in ok:
        raise ToolError(f"git {args[0]} fehlgeschlagen (Exit {r.returncode}): {r.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return r


# --- Konfigurationsparser (ohne git) --------------------------------------------------------------------------------
def _value(raw: str) -> str:
    """Wert einer Konfigurationszeile: Kommentar außerhalb von Anführungszeichen abschneiden, Anführungszeichen/Escapes entfernen."""
    out, q, i = [], False, 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            out.append({"n": "\n", "t": "\t", "b": "\b"}.get(raw[i + 1], raw[i + 1]))
            i += 2
            continue
        if c == '"':
            q = not q
        elif not q and c in "#;":
            break
        else:
            out.append(c)
        i += 1
    if q:
        raise ValueError("offenes Anführungszeichen")
    return "".join(out).strip()


def parse_config(text: str) -> list[tuple[str, str | None]]:
    """Konservativer Parser für Git-Konfigurationssyntax. Unklare Syntax -> ValueError (Aufrufer: fail closed). Führt nichts aus, folgt keinen Includes."""
    entries: list[tuple[str, str | None]] = []
    section = sub = None
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        i += 1
        while ln.endswith("\\") and not ln.endswith("\\\\") and i < len(lines):  # Fortsetzungszeile
            ln = ln[:-1] + lines[i].strip()
            i += 1
        if not ln or ln[0] in "#;":
            continue
        rest = ln
        if ln[0] == "[":
            m = re.match(r'\[\s*([A-Za-z0-9.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\](.*)$', ln)
            if not m:
                raise ValueError("Abschnittskopf nicht lesbar")
            section, sub, rest = m.group(1).lower(), m.group(2), m.group(3).strip()
            if sub is not None:
                sub = re.sub(r"\\(.)", r"\1", sub)
            elif "." in section:  # veraltete Schreibweise [section.sub]
                section, sub = section.split(".", 1)
            if not rest or rest[0] in "#;":
                continue
        if section is None:
            raise ValueError("Eintrag vor Abschnittskopf")
        m = re.match(r"([A-Za-z][A-Za-z0-9-]*)\s*(?:(=)\s*(.*))?$", rest)
        if not m:
            raise ValueError("Eintrag nicht lesbar")
        key = f"{section}.{sub}.{m.group(1).lower()}" if sub is not None else f"{section}.{m.group(1).lower()}"
        entries.append((key, _value(m.group(3)) if m.group(2) else None))
    return entries


def config_problems(entries: list[tuple[str, str | None]]) -> list[str]:
    bad = []
    for key, val in entries:
        lk = key.lower()
        if lk == "extensions.worktreeconfig" or lk == "extensions.partialclone":
            bad.append(key)
        elif lk == "core.filemode":
            if (val or "").strip().lower() not in ("true", "false"):
                bad.append(key)
        elif lk in CONFIG_ALLOW_EXACT or any(r.fullmatch(key) for r in CONFIG_ALLOW_RE):
            if re.fullmatch(r"remote\..+\.(url|pushurl)", key, re.IGNORECASE) and HELPER_URL_RE.match(val or ""):
                bad.append(key)
        else:
            bad.append(key)
    return bad


def redact_key(key: str) -> str:
    """Schlüsselname ohne Unterabschnitt (der URLs/Zugangsdaten enthalten kann)."""
    parts = key.split(".")
    return key if len(parts) <= 2 else f"{parts[0]}.*.{parts[-1]}"


def read_nofollow(path: str, limit: int = 1 << 20) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("keine normale Datei")
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read(limit)
    finally:
        os.close(fd)


# --- .git ohne git-Aufruf prüfen ------------------------------------------------------------------------------------
def git_dir_findings(top: str, hooks: bool) -> list[tuple[str, bool, str]]:
    """[(id, ok, Text)] für die .git-Struktur von top. Kein git-Aufruf. hooks=False: aktive Hooks nicht bewerten."""
    res: list[tuple[str, bool, str]] = []
    gd = os.path.join(top, ".git")
    try:
        st = os.lstat(gd)
    except OSError:
        st = None
    if st is None or not stat.S_ISDIR(st.st_mode):
        return [("git-dir", False, ".git fehlt oder ist kein echtes Verzeichnis (Symlink/Datei/gitdir-Verweis abgelehnt)")]
    res.append(("git-dir", True, ".git ist ein echtes Verzeichnis"))
    cfg = os.path.join(gd, "config")
    try:
        entries = parse_config(read_nofollow(cfg).decode("utf-8"))
        bad = config_problems(entries)
        if os.path.lexists(os.path.join(gd, "config.worktree")):
            bad.append("config.worktree (Datei)")
    except (OSError, ValueError, UnicodeDecodeError) as e:
        res.append(("git-config", False, f".git/config nicht sicher lesbar ({type(e).__name__}); abgelehnt"))
    else:
        if bad:
            names = sorted({redact_key(b) for b in bad})
            res.append(("git-config", False, f"unzulässige Schlüssel in .git/config (Werte werden nicht ausgegeben): {', '.join(names[:8])}"))
        else:
            res.append(("git-config", True, ".git/config nur Allowlist-Schlüssel"))
    if hooks:
        hk = os.path.join(gd, "hooks")
        if os.path.islink(hk):
            res.append(("git-hooks", False, ".git/hooks ist ein Symlink"))
        else:
            try:
                act = sorted(n for n in (os.listdir(hk) if os.path.isdir(hk) else []) if not n.endswith(".sample"))
            except OSError:
                act = ["<nicht lesbar>"]
            res.append(("git-hooks", not act, "keine aktiven Hooks" if not act else f"aktive Hooks: {act[:5]}"))
    ap = os.path.join(gd, "info", "attributes")
    try:
        txt = read_nofollow(ap).decode("utf-8", "replace") if os.path.lexists(ap) else ""
    except OSError:
        txt = "filter=x"
    badattr = any(ATTR_BAD_RE.search(ln) for ln in txt.splitlines() if not ln.lstrip().startswith("#"))
    res.append(("git-attributes", not badattr, "keine filter=/diff=/merge= in info/attributes" if not badattr else ".git/info/attributes enthält filter=/diff=/merge="))
    rep: list[str] = []
    rdir = os.path.join(gd, "refs", "replace")
    if os.path.lexists(rdir):
        if os.path.islink(rdir) or not os.path.isdir(rdir):
            rep.append("refs/replace (Symlink/Datei)")
        else:
            for _, dirs, files in os.walk(rdir):
                rep += files + dirs
    pr = os.path.join(gd, "packed-refs")
    if os.path.lexists(pr):
        try:
            if re.search(r"^[0-9a-f]+ refs/replace/", read_nofollow(pr, 1 << 24).decode("utf-8", "replace"), re.M):
                rep.append("packed-refs")
        except OSError:
            rep.append("packed-refs (nicht lesbar)")
    res.append(("git-replace", not rep, "keine refs/replace/*" if not rep else f"refs/replace/* vorhanden: {sorted(rep)[:5]}"))
    extra = [n for n in ("objects/info/alternates", "objects/info/http-alternates", "info/grafts", "shallow-grafts") if os.path.lexists(os.path.join(gd, n))]
    res.append(("git-alternates", not extra, "keine alternates/grafts" if not extra else f"fremde Objektquellen/Grafts: {extra}"))
    return res


def resolve_head(top: str) -> str:
    """HEAD-Commit aus Dateien (ohne git). ValueError, wenn nicht auflösbar."""
    gd = os.path.join(top, ".git")
    head = read_nofollow(os.path.join(gd, "HEAD"), 4096).decode("utf-8", "replace").strip()
    if SHA_RE.fullmatch(head):
        return head
    m = re.fullmatch(r"ref:\s*(refs/[A-Za-z0-9._/@+-]+)", head)
    if not m or any(c in ("", ".", "..") for c in m.group(1).split("/")):
        raise ValueError("HEAD nicht lesbar/ungültig")
    ref = m.group(1)
    try:
        oid = read_nofollow(os.path.join(gd, *ref.split("/")), 4096).decode("ascii", "replace").strip()
        if SHA_RE.fullmatch(oid):
            return oid
    except OSError:
        pass
    try:
        packed = read_nofollow(os.path.join(gd, "packed-refs"), 1 << 24).decode("utf-8", "replace")
    except OSError:
        packed = ""
    for ln in packed.splitlines():
        if ln.endswith(" " + ref) and not ln.startswith(("#", "^")) and SHA_RE.fullmatch(ln.split()[0]):
            return ln.split()[0]
    raise ValueError("HEAD-Ref nicht auflösbar")


# --- Pfad-/Eintragsprüfung ------------------------------------------------------------------------------------------
def path_problem(path: str) -> str | None:
    if not path or path.startswith("/"):
        return "leer/absolut"
    if "\\" in path or ":" in path:
        return "Backslash/Doppelpunkt"
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
        return "Steuerzeichen"
    for comp in path.split("/"):
        if comp in ("", ".", ".."):
            return "leere/.-/..-Komponente"
        low = comp.lower().translate(HFS_IGNORABLE)
        if low.rstrip(". ") == ".git" or re.fullmatch(r"git~\d+[. ]*", low):
            return "Komponente .git (oder Windows-Kurzname)"
    return None


def entry_problems(entries: list[list[str]]) -> list[str]:
    probs: list[str] = []
    seen: dict[str, str] = {}
    for mode, sha, path in entries:
        why = None
        if mode == "120000":
            why = "Symlink"
        elif mode == "160000":
            why = "Gitlink/Submodul"
        elif mode not in OK_MODES:
            why = f"Modus {mode}"
        elif not SHA_RE.fullmatch(sha):
            why = "Blob-SHA ungültig"
        else:
            why = path_problem(path)
        if why:
            probs.append(f"{path}: {why}")
        key = path.lower()
        if key in seen and seen[key] != path:
            probs.append(f"{path}: Groß-/Kleinschreibungs-Kollision mit {seen[key]}")
        seen.setdefault(key, path)
    return probs


# --- Manifest -------------------------------------------------------------------------------------------------------
def canonical(m: dict) -> bytes:
    core = {k: m[k] for k in ("version", "commit", "tree", "entries")}
    return json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def manifest_hash(m: dict) -> str:
    return hashlib.sha256(canonical(m)).hexdigest()


def manifest_mac(m: dict, key: str) -> str:
    return hmac.new(key.encode("utf-8"), canonical(m), hashlib.sha256).hexdigest()


def ensure_outside(top: str, path: str) -> None:
    ro, rt = os.path.realpath(path), os.path.realpath(top)
    if ro == rt or ro.startswith(rt + os.sep):
        raise ToolError(f"Pfad liegt innerhalb von {rt}; muss außerhalb liegen")


def read_key_file(path: str, forbidden_root: str) -> str:
    try:
        st = os.lstat(path)
    except OSError as e:
        raise ToolError(f"Schlüsseldatei nicht lesbar: {path}: {type(e).__name__}") from e
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ToolError(f"Schlüsseldatei ist keine normale Datei (Symlink?): {path}")
    if st.st_mode & 0o077:
        raise ToolError(f"Schlüsseldatei hat zu weite Rechte (erwartet 0600): {path}")
    if st.st_uid != os.geteuid():
        raise ToolError(f"Schlüsseldatei gehört einem anderen Benutzer: {path}")
    ensure_outside(forbidden_root, path)
    try:
        key = read_nofollow(path, 256).decode("ascii", "replace").strip()
    except OSError as e:
        raise ToolError(f"Schlüsseldatei nicht lesbar: {path}: {type(e).__name__}") from e
    if not KEY_RE.fullmatch(key):
        raise ToolError(f"Schlüsseldatei hat ungültiges Format (erwartet 64 Hex-Zeichen): {path}")
    return key


def find_top(repo: str) -> str:
    if not os.path.isdir(repo):
        raise ToolError(f"Repository-Pfad existiert nicht: {repo}")
    cur = os.path.realpath(repo)
    while True:
        gp = os.path.join(cur, ".git")
        if os.path.lexists(gp):
            st = os.lstat(gp)
            if stat.S_ISLNK(st.st_mode):
                raise ToolError(f".git ist ein Symlink ({cur}); abgelehnt")
            if stat.S_ISDIR(st.st_mode):
                return cur
            raise ToolError(f".git ist eine Datei (Worktree/gitdir-Verweis) in {cur}; abgelehnt")
        parent = os.path.dirname(cur)
        if parent == cur:
            raise ToolError(f"kein git-Repository: {repo}")
        cur = parent


def prepare(repo: str, hooks: bool = False) -> str:
    """Repository-Toplevel (ohne git gefunden) und .git/Konfiguration fail-closed prüfen, BEVOR irgendein git im Repository läuft."""
    top = find_top(repo)
    bad = [f"{cid}: {msg}" for cid, ok, msg in git_dir_findings(top, hooks) if not ok]
    if bad:
        raise ToolError("Repository nicht zulässig (nichts wurde ausgeführt): " + "; ".join(bad))
    r = git(top, "rev-parse", "--show-toplevel").stdout.strip()
    if os.path.realpath(os.fsdecode(r)) != top:
        raise ToolError("git meldet ein anderes Toplevel als die .git-Suche; abgelehnt")
    return top


def require_full_sha(value: str, what: str = "--commit") -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ToolError(f"{what} muss eine volle 40-stellige Hex-SHA (Kleinbuchstaben) sein (keine Kurzform, kein Name)")
    return value


def write_new_private(path: str, text: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        raise ToolError(f"Ausgabedatei nicht anlegbar (existiert sie schon?): {path}: {type(e).__name__}") from e
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(text)


def cmd_manifest(a) -> int:
    commit = require_full_sha(a.commit)
    top = find_top(a.repo)
    ensure_outside(top, a.out)
    key = read_key_file(a.key_file, top) if a.key_file else None
    if key and os.path.realpath(a.key_file) == os.path.realpath(a.out):
        raise ToolError("--key-file und --out dürfen nicht dieselbe Datei sein")
    top = prepare(a.repo)
    if git(top, "cat-file", "-t", commit, ok=(0, 128)).stdout.decode().strip() != "commit":
        raise ToolError("--commit ist kein Commit-Objekt dieses Repositorys")
    tree = git(top, "rev-parse", "--verify", commit + "^{tree}").stdout.decode().strip()
    raw = git(top, "ls-tree", "-r", "-z", "--full-tree", commit).stdout
    entries: list[list[str]] = []
    problems: list[str] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        meta, _, pb = item.partition(b"\t")
        try:
            mode, typ, sha = meta.decode("ascii").split(" ")
            path = pb.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            problems.append(f"{pb.decode('utf-8', 'backslashreplace')}: Nicht-UTF-8-Pfad oder unlesbarer Eintrag")
            continue
        entries.append([mode, sha, path])
    entries.sort(key=lambda e: e[2])
    problems += entry_problems(entries)
    if problems:
        for p in problems[:50]:
            print(f"VERSTOSS {show(p)}")
        print(f"{len(problems)} Verstoß/Verstöße – kein Manifest geschrieben")
        return 1
    m: dict = {"version": MANIFEST_VERSION, "commit": commit, "tree": tree, "entries": entries}
    m["entry_count"] = len(entries)
    m["manifest_sha256"] = manifest_hash(m)
    if key:
        m["mac"] = manifest_mac(m, key)
    write_new_private(a.out, json.dumps(m, indent=1, sort_keys=True))
    print(f"Manifest: commit {commit} tree {tree} {len(entries)} Dateien sha256 {m['manifest_sha256']}{' mac: ja' if key else ' mac: nein'}")
    return 0


def load_manifest(path: str) -> dict:
    try:
        m = json.loads(read_nofollow(path, 1 << 28).decode("utf-8"))
    except (OSError, ValueError) as e:
        raise ToolError(f"Manifest nicht lesbar: {path}: {type(e).__name__}") from e
    ok = (isinstance(m, dict) and m.get("version") == MANIFEST_VERSION and isinstance(m.get("commit"), str) and isinstance(m.get("tree"), str)
          and isinstance(m.get("manifest_sha256"), str) and isinstance(m.get("entries"), list) and isinstance(m.get("entry_count"), int)
          and all(isinstance(e, list) and len(e) == 3 and all(isinstance(x, str) for x in e) for e in m["entries"]))
    if not ok or not SHA_RE.fullmatch(m["commit"]) or not SHA_RE.fullmatch(m["tree"]) or ("mac" in m and not isinstance(m["mac"], str)):
        raise ToolError("Manifest hat ungültiges Format")
    return m


# --- verify ---------------------------------------------------------------------------------------------------------
def unescape_mount(s: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda mm: chr(int(mm.group(1), 8)), s)


def parse_mountinfo(text: str) -> list[dict]:
    mounts = []
    for ln in text.splitlines():
        if " - " not in ln:
            continue
        left, right = ln.split(" - ", 1)
        lf, rf = left.split(), right.split()
        if len(lf) < 6 or len(rf) < 1:
            raise ValueError("mountinfo-Zeile nicht lesbar")
        mounts.append({"dev": lf[2], "root": unescape_mount(lf[3]), "mp": unescape_mount(lf[4]), "opts": lf[5], "fstype": rf[0]})
    if not mounts:  # leere/separatorlose Datei darf nie ‚kein Mount gefunden = OK‘ bedeuten (Review-Befund: fail closed)
        raise ValueError("mountinfo enthält keine parsbare Zeile")
    return mounts


def bad_fstype(t: str) -> bool:
    return t in BAD_FSTYPES or t.startswith("fuse")


def check_mounts(rep: Report, checkout: str, mountinfo: str) -> None:
    try:
        mounts = parse_mountinfo(read_nofollow(mountinfo, 1 << 24).decode("utf-8", "replace"))
    except (OSError, ValueError) as e:
        rep.fail("mounts", f"mountinfo nicht lesbar/ungültig ({type(e).__name__}); fail closed")
        return
    before = rep.fails
    c = checkout.rstrip("/") or "/"
    below = [m for m in mounts if m["mp"].startswith(c + "/")]
    for m in below:
        rep.fail("mount-below", f"Mount unterhalb des Checkouts: ./{m['mp'][len(c) + 1:]} fstype={m['fstype']} opts={m['opts']}")
    at = [m for m in mounts if m["mp"] == c]
    for m in at:
        same_dev = [o for o in mounts if o["dev"] == m["dev"] and o["mp"] != c]
        if bad_fstype(m["fstype"]) or m["root"] != "/" or same_dev:
            why = "Netz-/Shared-Dateisystem" if bad_fstype(m["fstype"]) else ("Bind-Mount eines Unterverzeichnisses" if m["root"] != "/" else "Bind-Mount (gleiches Gerät an weiterem Pfad)")
            rep.fail("mount-at", f"Checkout-Pfad ist ein Mountpunkt: {why}; fstype={m['fstype']} opts={m['opts']}")
        else:
            rep.warn("mount-at", f"Checkout-Pfad ist eigener Mountpunkt: fstype={m['fstype']} opts={m['opts']}")
    if not at:
        cont = [m for m in mounts if c == m["mp"] or c.startswith(m["mp"].rstrip("/") + "/")]
        if cont:
            m = max(cont, key=lambda x: len(x["mp"]))
            if bad_fstype(m["fstype"]):
                rep.fail("mount-in", f"Checkout liegt in einem Netz-/Shared-/fuse-Dateisystem: fstype={m['fstype']} opts={m['opts']}")
            elif m["fstype"] == "overlay":
                rep.warn("mount-in", "Checkout liegt auf einem overlay-Dateisystem (Container, kein eigener Kernel belegt)")
    if rep.fails == before:
        rep.ok("mounts", "kein Mount unterhalb des Checkouts, kein Bind-/Netz-Mount am Checkout")


def walk_tree(root: str) -> tuple[dict[str, os.stat_result], list[str], list[str], list[str]]:
    """(Dateien rel->lstat, Symlinks, Sonderdateien, leere Verzeichnisse); `.git` oben wird übersprungen; folgt nie Symlinks."""
    files: dict[str, os.stat_result] = {}
    links: list[str] = []
    others: list[str] = []
    empty: list[str] = []
    stack = [""]
    while stack:
        rel = stack.pop()
        d = os.path.join(root, rel) if rel else root
        names = sorted(os.listdir(d))
        if not names and rel:
            empty.append(rel)
        for n in names:
            r = f"{rel}/{n}" if rel else n
            if r == ".git":
                continue
            st = os.lstat(os.path.join(root, r))
            if stat.S_ISLNK(st.st_mode):
                links.append(r)
            elif stat.S_ISDIR(st.st_mode):
                stack.append(r)
            elif stat.S_ISREG(st.st_mode):
                files[r] = st
            else:
                others.append(r)
    return files, links, others, empty


def blob_sha1(path: str, st: os.stat_result) -> str | None:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            return None
        h = hashlib.sha1(b"blob %d\0" % fst.st_size)  # Git-Objekt-ID, kein Sicherheitsmerkmal dieses Skripts
        n = 0
        with os.fdopen(fd, "rb", closefd=False) as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                n += len(chunk)
        return h.hexdigest() if n == fst.st_size else None
    finally:
        os.close(fd)


def check_worktree(rep: Report, checkout: str, entries: list[list[str]]) -> None:
    exp = {p: (mode, sha) for mode, sha, p in entries}
    try:
        files, links, others, empty = walk_tree(checkout)
    except OSError as e:
        rep.fail("worktree", f"Arbeitsbaum nicht lesbar ({type(e).__name__})")
        return
    before = rep.fails
    if links:
        rep.fail("worktree-symlink", f"Symlinks im Checkout (auch Verzeichnis-Symlinks): {lst(links)}")
    if others:
        rep.fail("worktree-special", f"Sonderdateien (FIFO/Socket/Gerät) im Checkout: {lst(others)}")
    extra = sorted(set(files) - set(exp))
    missing = sorted(set(exp) - set(files))
    if extra:
        rep.fail("worktree-extra", f"Dateien nicht im Manifest ({len(extra)}): {lst(extra)}")
    if missing:
        rep.fail("worktree-missing", f"Dateien fehlen ({len(missing)}): {lst(missing)}")
    if empty:
        rep.warn("worktree-emptydir", f"leere Verzeichnisse (nicht im Git-Baum): {lst(empty)}")
    changed, badmode, links_n = [], [], []
    for p in sorted(set(files) & set(exp)):
        st = files[p]
        mode, sha = exp[p]
        if st.st_nlink > 1:
            links_n.append(p)
        try:
            h = blob_sha1(os.path.join(checkout, p), st)
        except OSError:
            h = None
        if h != sha:
            changed.append(p)
        if bool(st.st_mode & 0o111) != (mode == "100755"):
            badmode.append(p)
    if links_n:
        rep.fail("worktree-hardlink", f"Hardlinks (nlink>1): {lst(links_n)}")
    if changed:
        rep.fail("worktree-content", f"Inhalt weicht vom Manifest ab ({len(changed)}): {lst(changed)}")
    if badmode:
        rep.fail("worktree-mode", f"Ausführbit weicht vom Manifest ab: {lst(badmode)}")
    if rep.fails == before:
        rep.ok("worktree", f"{len(exp)} Dateien == Manifest (Dateimenge, Git-Blob-SHA-1, Ausführbit)")


def check_env(rep: Report, env: dict[str, str], home: str) -> None:
    names = sorted(n for n in env if ENV_NAME_RE.search(n))
    if names:
        rep.fail("env-names", f"Umgebungsvariablen mit Secret-Namensmuster (Werte nicht ausgegeben): {', '.join(names[:20])}")
    fvars = [n for n in sorted(env) if n.upper().endswith("_FILE") and env[n]]
    hit = False
    for n in fvars:
        p = env[n]
        if os.path.lexists(p):
            hit = True
            try:
                st = os.lstat(p)
                rep.fail("env-file", f"{n} verweist auf existierende Datei: {p} mode={stat.S_IMODE(st.st_mode):04o} size={st.st_size} (Inhalt nicht gelesen)")
            except OSError:
                rep.fail("env-file", f"{n} verweist auf existierenden Pfad: {p}")
    if not names and not hit:
        rep.ok("env-names", "keine Variablen mit Secret-Namensmuster, keine *_FILE-Variable auf existierende Datei")
    prox = sorted(n for n in env if n.upper() in PROXY_NAMES)
    if prox:
        rep.warn("env-proxy", f"Proxy-Variablen gesetzt (Netzpfad; Werte nicht ausgegeben): {', '.join(prox)}")
    before = rep.fails

    def present(rel: str) -> bool:
        return os.path.lexists(os.path.join(home, rel))

    ssh = os.path.join(home, ".ssh")
    if os.path.isdir(ssh) and not os.path.islink(ssh):
        priv = []
        for n in sorted(os.listdir(ssh)):
            fp = os.path.join(ssh, n)
            if n.endswith(".pub") or n.startswith(("known_hosts", "authorized_keys")) or n == "config":
                continue
            looks = re.fullmatch(r"id_(rsa|dsa|ecdsa|ed25519)(_sk)?|.*\.(pem|key)", n) is not None
            if not looks and os.path.isfile(fp) and not os.path.islink(fp):
                try:
                    looks = b"PRIVATE KEY" in read_nofollow(fp, 4096)
                except OSError:
                    looks = False
            if looks or os.path.islink(fp):
                priv.append(n)
        if priv:
            rep.fail("home-ssh", f"~/.ssh enthält Privatschlüssel-Dateien (Inhalt nicht gelesen): {', '.join(priv[:8])}")
    elif os.path.islink(ssh):
        rep.fail("home-ssh", "~/.ssh ist ein Symlink")
    for rel in (".git-credentials", ".netrc", ".pypirc", ".config/git/credentials"):
        if present(rel):
            rep.fail("home-cred", f"~/{rel} vorhanden (Inhalt nicht gelesen)")
    for rel in (".config/gh", ".aws", ".config/gcloud"):
        p = os.path.join(home, rel)
        if os.path.lexists(p) and (not os.path.isdir(p) or os.path.islink(p) or os.listdir(p)):
            rep.fail("home-cred", f"~/{rel} vorhanden (Inhalt nicht gelesen)")
    dc = os.path.join(home, ".docker", "config.json")
    if os.path.lexists(dc):
        try:
            data = json.loads(read_nofollow(dc, 1 << 20).decode("utf-8"))
            keys = [k for k in ("auths", "credsStore", "credHelpers", "identitytoken") if data.get(k)]
        except (OSError, ValueError, AttributeError):
            keys = ["<nicht lesbar>"]
        if keys:
            rep.fail("home-docker", f"~/.docker/config.json enthält Schlüssel: {', '.join(keys)}")
    npmrc = os.path.join(home, ".npmrc")
    if os.path.lexists(npmrc):
        try:
            if re.search(rb"_authToken|_auth\b|_password", read_nofollow(npmrc, 1 << 20)):
                rep.fail("home-npmrc", "~/.npmrc enthält Zugangsdaten-Schlüssel (_authToken/_auth/_password)")
        except OSError:
            rep.fail("home-npmrc", "~/.npmrc nicht lesbar")
    for rel in (".gitconfig", ".config/git/config"):
        p = os.path.join(home, rel)
        if not os.path.lexists(p):
            continue
        try:
            ents = parse_config(read_nofollow(p, 1 << 22).decode("utf-8", "replace"))
        except (OSError, ValueError):
            rep.fail("home-gitconfig", f"~/{rel} nicht lesbar/ungültig (fail closed)")
            continue
        bad = sorted({redact_key(k) for k, _ in ents if re.match(r"credential\.|url\..*\.(push)?insteadof$|http\..*extraheader$|http\.extraheader$", k, re.I)})
        if bad:
            rep.fail("home-gitconfig", f"~/{rel} enthält Schlüssel: {', '.join(bad)} (Werte nicht ausgegeben)")
    if rep.fails == before:
        rep.ok("home", "keine bekannten Zugangsdaten-Dateien im Home")


def cmd_verify(a) -> int:
    checkout = os.path.realpath(a.checkout)
    if os.path.islink(a.checkout) or not os.path.isdir(checkout):
        raise ToolError("--checkout muss ein echtes Verzeichnis (kein Symlink) sein")
    m = load_manifest(a.manifest)
    key = read_key_file(a.key_file, checkout) if a.key_file else None
    rep = Report()
    if not hmac.compare_digest(manifest_hash(m).encode(), m["manifest_sha256"].encode("utf-8", "replace")):
        rep.fail("manifest", "manifest_sha256 stimmt nicht mit dem Inhalt überein (manipuliert?)")
    elif m["entry_count"] != len(m["entries"]):
        rep.fail("manifest", "entry_count stimmt nicht")
    elif key is not None and not (isinstance(m.get("mac"), str) and hmac.compare_digest(manifest_mac(m, key).encode(), m["mac"].encode("utf-8", "replace"))):
        rep.fail("manifest-mac", "mac fehlt oder ist ungültig (falscher Schlüssel oder manipuliert)")
    else:
        probs = entry_problems(m["entries"])
        if probs or [e[2] for e in m["entries"]] != sorted(e[2] for e in m["entries"]):
            rep.fail("manifest", f"Manifest-Einträge unzulässig/unsortiert: {lst(probs)}")
        else:
            rep.ok("manifest", f"Hash stimmt{', mac gültig' if key else ''}; {len(m['entries'])} Einträge zulässig")
            if key is None:
                rep.warn("manifest-mac", "kein --key-file: nur Selbstkonsistenz des Manifests geprüft (Herkunft nicht belegt)" if "mac" in m else
                         "Manifest ohne mac: nur Selbstkonsistenz, Herkunft nicht belegt")
    if rep.fails:
        print("RESULT: BLOCKED")
        return 1
    for cid, ok, msg in git_dir_findings(checkout, hooks=True):
        (rep.ok if ok else rep.fail)(cid, msg)
    try:
        head = resolve_head(checkout)
        if head == m["commit"]:
            rep.ok("git-head", "HEAD == Manifest-Commit")
        else:
            rep.fail("git-head", f"HEAD ({head}) != Manifest-Commit ({m['commit']})")
    except (OSError, ValueError) as e:
        rep.fail("git-head", f"HEAD nicht prüfbar/auflösbar ({type(e).__name__})")
    check_worktree(rep, checkout, m["entries"])
    check_mounts(rep, checkout, a.mountinfo)
    if a.env_check:
        check_env(rep, dict(os.environ), os.path.realpath(a.home) if a.home else os.path.expanduser("~"))
    else:
        rep.warn("env", "--env-check nicht angefordert: Umgebung NICHT geprüft")
    print(f"RESULT: {'OK' if not rep.fails else 'BLOCKED'}")
    att = {"commit": m["commit"], "tree": m["tree"], "manifest_sha256": m["manifest_sha256"], "checked_at": utcnow(), "env_check": bool(a.env_check),
           "findings": rep.fails, "hostname_hash": hashlib.sha256(socket.gethostname().encode("utf-8", "replace")).hexdigest(), "uid": os.geteuid()}
    print("ATTESTATION " + json.dumps(att, sort_keys=True))
    return 1 if rep.fails else 0


# --- check-report ---------------------------------------------------------------------------------------------------
def load_json_doc(path: str, what: str) -> dict:
    try:
        text = read_nofollow(path, 1 << 24).decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ToolError(f"{what} nicht lesbar: {path}: {type(e).__name__}") from e
    try:
        doc = json.loads(text)
    except ValueError:
        blocks = re.findall(r"```(?:json)?\s*\n(.*?)\n```", text, re.S)  # Bericht als Textdatei mit JSON-Block: letzter Block gilt
        if not blocks:
            raise ToolError(f"{what} ist kein JSON und enthält keinen JSON-Block") from None
        try:
            doc = json.loads(blocks[-1])
        except ValueError as e:
            raise ToolError(f"{what}: JSON-Block nicht lesbar") from e
    if not isinstance(doc, dict):
        raise ToolError(f"{what}: JSON-Objekt erwartet")
    return doc


def need(doc: dict, keys: tuple[str, ...], what: str) -> None:
    missing = [k for k in keys if k not in doc or doc[k] is None or doc[k] == ""]
    if missing:
        raise ToolError(f"{what}: Pflichtfelder fehlen: {', '.join(missing)}")


def cmd_check_report(a) -> int:
    exp = load_json_doc(a.expect, "expect")
    rpt = load_json_doc(a.report, "report")
    need(exp, ("commit", "tree", "manifest_sha256", "environment_id", "nonce", "min_ts"), "expect")
    need(rpt, ("commit", "tree", "manifest_sha256", "session_id", "environment_id", "tools", "nonce", "attestation", "findings"), "report")
    for k in ("commit", "tree"):
        require_full_sha(exp[k], f"expect.{k}")
    if not all(isinstance(exp[k], str) for k in ("manifest_sha256", "environment_id", "nonce")):
        raise ToolError("expect: manifest_sha256/environment_id/nonce müssen Zeichenketten sein")
    min_ts = parse_ts(exp["min_ts"])
    if min_ts is None:
        raise ToolError("expect.min_ts ist kein ISO-8601-Zeitstempel")
    att = rpt["attestation"]
    if not isinstance(att, dict):
        raise ToolError("report.attestation muss ein Objekt sein")
    need(att, ("env_check", "findings", "checked_at"), "report.attestation")
    sess = None
    if a.session:
        sess = load_json_doc(a.session, "session")
        need(sess, ("id", "environment_id", "sources", "status"), "session")
        try:
            revision = sess["sources"][0]["git_repository"]["revision"]
        except (KeyError, IndexError, TypeError) as e:
            raise ToolError("session: sources[0].git_repository.revision fehlt") from e
        if not isinstance(revision, str) or not revision:
            raise ToolError("session: revision fehlt")
    allowed = {t.strip() for t in a.allowed_tools.split(",") if t.strip()}
    if not allowed:
        raise ToolError("--allowed-tools ist leer")
    rep = Report()

    def eq(cid: str, x: object, y: object, label: str) -> None:
        if isinstance(x, str) and isinstance(y, str) and hmac.compare_digest(x.encode("utf-8", "replace"), y.encode("utf-8", "replace")):
            rep.ok(cid, f"{label} stimmt")
        else:
            rep.fail(cid, f"{label} weicht ab")

    eq("commit", rpt["commit"], exp["commit"], "commit (volle SHA)")
    eq("tree", rpt["tree"], exp["tree"], "tree")
    eq("manifest", rpt["manifest_sha256"], exp["manifest_sha256"], "manifest_sha256")
    eq("nonce", rpt["nonce"], exp["nonce"], "nonce")
    eq("environment", rpt["environment_id"], exp["environment_id"], "environment_id (Bericht vs. erwartet)")
    if sess is None:
        (rep.warn if a.allow_no_session else rep.fail)("session", "kein Plattform-Auszug (--session): Bericht ist nur Selbstauskunft")
    else:
        eq("session-env", sess["environment_id"], exp["environment_id"], "environment_id (Plattform vs. erwartet)")
        eq("session-env-report", sess["environment_id"], rpt["environment_id"], "environment_id (Plattform vs. Bericht)")
        eq("session-id", sess["id"], rpt["session_id"], "session_id (Plattform vs. Bericht)")
        eq("session-revision", revision, exp["commit"], "Plattform-revision == erwarteter Commit (volle SHA)")
        if not SHA_RE.fullmatch(revision):
            rep.fail("session-revision-form", "Plattform-revision ist keine volle 40-hex-SHA")
        rep.ok("session-info", f"status={sess['status']} parent={sess.get('parent')}")
    tools = rpt["tools"]
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) for t in tools):
        rep.fail("tools", "tools fehlt/leer/ungültig (Werkzeugliste nicht belegt)")
    else:
        extra = sorted(set(tools) - allowed)
        if extra:
            rep.fail("tools", f"unzulässige Werkzeuge: {', '.join(extra[:10])} (erlaubt: {', '.join(sorted(allowed))})")
        else:
            rep.ok("tools", f"Werkzeuge ⊆ erlaubt ({', '.join(sorted(set(tools)))})")
    if att["env_check"] is True:
        rep.ok("att-env", "Attestation.env_check == true")
    else:
        rep.fail("att-env", "Attestation.env_check ist nicht true")
    if isinstance(att["findings"], int) and not isinstance(att["findings"], bool) and att["findings"] == 0:
        rep.ok("att-findings", "Attestation.findings == 0")
    else:
        rep.fail("att-findings", "Attestation.findings ist nicht 0")
    for k in ("commit", "tree", "manifest_sha256"):
        if k in att:
            eq(f"att-{k}", att[k], exp[k], f"Attestation.{k}")
        else:
            rep.fail(f"att-{k}", f"Attestation.{k} fehlt")
    ts = parse_ts(att["checked_at"])
    if ts is None:
        rep.fail("att-time", "Attestation.checked_at ist kein Zeitstempel")
    elif ts < min_ts:
        rep.fail("att-time", "Attestation.checked_at liegt vor min_ts (zu alt)")
    else:
        rep.ok("att-time", "Attestation.checked_at >= min_ts")
    print(f"RESULT: {'OK' if not rep.fails else 'BLOCKED'}")
    return 1 if rep.fails else 0


# --- remote-check ---------------------------------------------------------------------------------------------------
def cmd_remote_check(a) -> int:
    commit = require_full_sha(a.commit)
    if not re.fullmatch(r"refs/[A-Za-z0-9._/@+-]+", a.ref) or any(c in ("", ".", "..") for c in a.ref.split("/")) or a.ref.endswith("/"):
        raise ToolError("--ref muss ein voller Ref-Name sein (z. B. refs/heads/main)")
    top = prepare(a.repo)
    url = a.url
    if url is None:
        ents = parse_config(read_nofollow(os.path.join(top, ".git", "config")).decode("utf-8"))
        urls = [v for k, v in ents if re.fullmatch(r"remote\..+\.url", k, re.I) and v]
        url = next((v for k, v in ents if k == "remote.origin.url" and v), urls[0] if len(urls) == 1 else None)
        if not url:
            raise ToolError("keine eindeutige Remote-URL in der Repo-Konfiguration (--url angeben)")
    proto = a.allow_protocol
    if url.startswith("-") or any(ord(c) < 0x21 or ord(c) == 0x7F for c in url) or HELPER_URL_RE.match(url):
        raise ToolError("URL unzulässig (Option/Steuerzeichen/Remote-Helfer)")
    if not url.startswith(proto + "://"):
        raise ToolError(f"URL muss mit {proto}:// beginnen (--allow-protocol {proto})")
    if git(top, "cat-file", "-t", commit, ok=(0, 128)).stdout.decode().strip() != "commit":
        raise ToolError("--commit ist kein Commit-Objekt des lokalen Repositorys")
    extra = {"GIT_ALLOW_PROTOCOL": proto}
    extra.update({k: os.environ[k] for k in PASS_THROUGH_ENV if k in os.environ})
    r = git("/", "ls-remote", "--", url, a.ref, extra_env=extra, ok=(0, 128, 1))
    rep = Report()
    if r.returncode != 0:
        rep.fail("remote", "git ls-remote fehlgeschlagen (Remote nicht erreichbar/URL ungültig); Übergabe nicht belegt")
        print("RESULT: BLOCKED")
        return 1
    tips = [ln.split("\t", 1)[0] for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.endswith("\t" + a.ref)]
    if len(tips) != 1 or not SHA_RE.fullmatch(tips[0]):
        rep.fail("remote-ref", f"Ref {a.ref} nicht (eindeutig) auf dem Remote gefunden")
    elif tips[0] == commit:
        rep.ok("remote-ref", f"Remote-Tip von {a.ref} == Commit")
    else:
        tip = tips[0]
        have = git(top, "cat-file", "-t", tip, ok=(0, 128)).stdout.decode().strip() == "commit"
        if not have:
            rep.fail("remote-ref", f"Remote-Tip {tip} ≠ Commit und lokal nicht vorhanden: Erreichbarkeit des Commits nicht belegbar")
        elif git(top, "merge-base", "--is-ancestor", commit, tip, ok=(0, 1)).returncode == 0:
            rep.warn("remote-ref", f"Remote-Tip {tip} ≠ Commit, Commit ist Vorfahre des Tips (Remote ist vorwärts gelaufen)")
        else:
            rep.fail("remote-ref", f"Remote-Tip {tip} ≠ Commit und Commit ist kein Vorfahre des Tips")
    print(f"RESULT: {'OK' if not rep.fails else 'BLOCKED'}")
    return 1 if rep.fails else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--repo", required=True)
    m.add_argument("--commit", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--key-file", default=None)
    m.set_defaults(fn=cmd_manifest)
    v = sub.add_parser("verify")
    v.add_argument("--manifest", required=True)
    v.add_argument("--checkout", required=True)
    v.add_argument("--key-file", default=None)
    v.add_argument("--env-check", action="store_true")
    v.add_argument("--home", default=None)
    v.add_argument("--mountinfo", default="/proc/self/mountinfo")
    v.set_defaults(fn=cmd_verify)
    c = sub.add_parser("check-report")
    c.add_argument("--expect", required=True)
    c.add_argument("--report", required=True)
    c.add_argument("--session", default=None)
    c.add_argument("--allowed-tools", default=DEFAULT_TOOLS)
    c.add_argument("--allow-no-session", action="store_true", help="fehlenden Plattform-Auszug nur als WARN werten (Bericht = reine Selbstauskunft)")
    c.set_defaults(fn=cmd_check_report)
    r = sub.add_parser("remote-check")
    r.add_argument("--repo", required=True)
    r.add_argument("--commit", required=True)
    r.add_argument("--ref", required=True)
    r.add_argument("--url", default=None)
    r.add_argument("--allow-protocol", choices=("https", "file"), default="https")
    r.set_defaults(fn=cmd_remote_check)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)  # argparse-Fehler -> SystemExit(2)
    try:
        return a.fn(a)
    except ToolError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # interner Fehler darf nie als OK oder Regelverstoß erscheinen
        print(f"INTERNER FEHLER: {type(e).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
