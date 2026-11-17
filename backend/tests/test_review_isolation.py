"""Isolations- und Übergabetests für scripts/review_handoff.py (nur Tests; Produktivcode wird nicht verändert).

Vier Klassen, am Testnamen-Präfix erkennbar:

* `test_limit_*`     GRENZEN-NACHWEIS. Ein root-Entwicklungsagent im SELBEN Kernel kann die Schutzmechanismen der Varianten A/B1 (uid-Trennung,
                     Dateirechte, chattr +i, setpriv/unshare-Namespace wie scripts/ro_run.sh, ro-Bind-Mounts) umgehen. Diese Tests ASSERTIEREN, dass der
                     Angriff GELINGT. Sie belegen also: innerhalb desselben Kernels gibt es KEINEN Schutz gegen root. Sie sind Regression dieser Aussage,
                     keine Sicherheitsfunktion. Nur als root, nur in einem Wegwerf-Verzeichnis unter /home/user (NICHT /tmp), restloses Aufräumen.
* `test_handoff_*`   Übergabe-Integrität Ende-zu-Ende in Wegwerf-Repos (Dev-Repo -> Manifest -> Bare-Remote -> frischer Klon = "Review-Umgebung").
* `test_secrets_*`   Secrets: Namen werden gemeldet, Werte erscheinen nie in der Ausgabe.
* `test_failclosed_*` Fail-closed bei Integritäts-/Bedienfehlern und Abbruch (nie Exit 0 / nie OK-Attestation).

Alle Daten sind erfunden/synthetisch, keine Netzzugriffe (nur file-Pfade), nichts wird außerhalb tmp_path bzw. des Wegwerf-Verzeichnisses geschrieben.
Das Skript läuft immer als Unterprozess `python -I scripts/review_handoff.py …` mit explizit gesetzter, minimaler Umgebung.
Mutationsnachweis: die Umgebungsvariable REVIEW_HANDOFF_SCRIPT_UNDER_TEST kann auf eine manipulierte KOPIE des Skripts zeigen (Standard: echter Pfad)."""
from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REAL_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "review_handoff.py"
SCRIPT = Path(os.environ.get("REVIEW_HANDOFF_SCRIPT_UNDER_TEST") or REAL_SCRIPT)
_SPEC = importlib.util.spec_from_file_location("review_handoff_under_test", SCRIPT)
RH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(RH)  # nur für den In-Process-Test der Ausnahmebehandlung; __name__ != "__main__"

KEY = "ab" * 32
OTHER_KEY = "cd" * 32
BASE_ENV = {"PATH": "/usr/bin:/bin"}


# =====================================================================================================================
# Gemeinsame Helfer
# =====================================================================================================================
def genv(tmp: Path) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": str(tmp / "githome"), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


def g(tmp: Path, repo: Path | str, *args: str, inp: bytes | None = None) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], env=genv(tmp), input=inp, capture_output=True)
    assert r.returncode == 0, (args, r.stderr.decode())
    return r.stdout.decode().strip()


def run(args: list[str], env: dict[str, str] | None = None, isolated: bool = True) -> subprocess.CompletedProcess:
    """Skript als Unterprozess; Umgebung EXAKT `env` (Standard: nur PATH), cwd `/`."""
    cmd = [sys.executable] + (["-I"] if isolated else []) + [str(SCRIPT)] + args
    return subprocess.run(cmd, env=dict(BASE_ENV if env is None else env), capture_output=True, text=True, cwd="/")


def out(r: subprocess.CompletedProcess) -> str:
    return r.stdout + r.stderr


def canon(m: dict) -> bytes:
    return json.dumps({k: m[k] for k in ("version", "commit", "tree", "entries")}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def attestation(r: subprocess.CompletedProcess) -> dict:
    return json.loads(r.stdout.split("ATTESTATION ", 1)[1].splitlines()[0])


def blocked(r: subprocess.CompletedProcess, token: str | None = None) -> None:
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "RESULT: BLOCKED" in r.stdout and "RESULT: OK" not in r.stdout, r.stdout
    if token:
        assert token in out(r), (token, r.stdout, r.stderr)


def never_ok(r: subprocess.CompletedProcess) -> None:
    assert "RESULT: OK" not in r.stdout and r.returncode != 0, (r.returncode, r.stdout, r.stderr)


def exit2(r: subprocess.CompletedProcess) -> None:
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    never_ok(r)
    assert "ATTESTATION" not in r.stdout


def leaked(text: str, value: str) -> bool:
    """True, wenn der Wert oder ein Teilstring (>= 12 Zeichen, gleitend) in text vorkommt."""
    if value in text:
        return True
    n = 12
    return any(value[i:i + n] in text for i in range(0, max(1, len(value) - n + 1), 3))


# =====================================================================================================================
# Wegwerf-Welt für Übergabe-Tests
# =====================================================================================================================
class Lab:
    """Dev-Repo (Commits B, C) + Schlüssel/Manifest außerhalb + Bare-Remote + frischer Klon (= Review-Umgebung, ausgecheckt C)."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.meta = tmp / "meta"
        self.meta.mkdir()
        self.key = self.meta / "k.key"
        self.key.write_text(KEY + "\n")
        self.key.chmod(0o600)
        self.dev = tmp / "dev"
        self.dev.mkdir()
        g(tmp, self.dev, "init", "-q", "-b", "main")
        self._w(self.dev, "a.txt", b"alpha\n", False)
        self._w(self.dev, "dir/b.sh", b"#!/bin/sh\necho hi\n", True)
        g(tmp, self.dev, "add", "-A")
        g(tmp, self.dev, "commit", "-q", "-m", "B")
        self.B = g(tmp, self.dev, "rev-parse", "HEAD")
        self._w(self.dev, "a.txt", b"alpha2\n", False)
        self._w(self.dev, "dir/c.txt", b"gamma\n", False)
        g(tmp, self.dev, "add", "-A")
        g(tmp, self.dev, "commit", "-q", "-m", "C")
        self.C = g(tmp, self.dev, "rev-parse", "HEAD")
        self.tree = g(tmp, self.dev, "rev-parse", self.C + "^{tree}")
        self.bare = tmp / "remote.git"
        g(tmp, tmp, "init", "-q", "--bare", "-b", "main", str(self.bare))
        g(tmp, self.dev, "push", "-q", str(self.bare), "main")
        self.manifest = self.meta / "manifest.json"
        r = self.make_manifest(self.C, self.manifest)
        assert r.returncode == 0, out(r)
        self.review = tmp / "review"
        self.review.mkdir()
        self.home = self.review / "home"
        self.home.mkdir()
        self.co = self.review / "co"
        g(tmp, tmp, "clone", "-q", "--no-hardlinks", str(self.bare), str(self.co))
        assert g(tmp, self.co, "rev-parse", "HEAD") == self.C

    @staticmethod
    def _w(root: Path, rel: str, data: bytes, ex: bool) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        p.chmod(0o755 if ex else 0o644)

    def make_manifest(self, commit: str, dest: Path, repo: Path | None = None, key: bool = True) -> subprocess.CompletedProcess:
        a = ["manifest", "--repo", str(repo or self.dev), "--commit", commit, "--out", str(dest)]
        if key:
            a += ["--key-file", str(self.key)]
        return run(a)

    def clean_env(self) -> dict[str, str]:
        return {"PATH": "/usr/bin:/bin", "HOME": str(self.home)}

    def verify(self, *extra: str, env: dict[str, str] | None = None, co: Path | None = None, manifest: Path | None = None, key: bool = True,
               env_check: bool = True) -> subprocess.CompletedProcess:
        a = ["verify", "--manifest", str(manifest or self.manifest), "--checkout", str(co or self.co)]
        if key:
            a += ["--key-file", str(self.key)]
        if env_check:
            a.append("--env-check")
        return run(a + list(extra), self.clean_env() if env is None else env)

    def m(self) -> dict:
        return json.loads(self.manifest.read_text())

    def forge(self, mutate, name: str = "forged.json", rehash: bool = False) -> Path:
        m = self.m()
        mutate(m)
        if rehash:
            m["manifest_sha256"] = hashlib.sha256(canon(m)).hexdigest()
            m["entry_count"] = len(m["entries"])
        p = self.meta / name
        p.write_text(json.dumps(m))
        return p

    def remote_check(self, commit: str | None = None, repo: Path | None = None, ref: str = "refs/heads/main") -> subprocess.CompletedProcess:
        return run(["remote-check", "--repo", str(repo or self.dev), "--commit", commit or self.C, "--ref", ref, "--url", f"file://{self.bare}",
                    "--allow-protocol", "file"])


@pytest.fixture()
def lab(tmp_path: Path) -> Lab:
    return Lab(tmp_path)


# =====================================================================================================================
# (2) test_handoff_*  Übergabe-Integrität Ende-zu-Ende
# =====================================================================================================================
def test_handoff_clean_clone_verifies_with_attestation(lab: Lab):
    """Positiv: frischer Klon des Bare-Remotes (ausgecheckt C), bereinigte Umgebung -> Exit 0 + Attestation zu C/tree/manifest."""
    m = lab.m()
    assert hashlib.sha256(canon(m)).hexdigest() == m["manifest_sha256"]  # eigene Nachrechnung des dokumentierten Formats
    r = lab.verify()
    assert r.returncode == 0 and "RESULT: OK" in r.stdout, out(r)
    for cid in ("manifest", "git-head", "worktree", "mounts"):
        assert f"PASS {cid}" in r.stdout, r.stdout
    assert "FAIL" not in r.stdout
    att = attestation(r)
    assert att["commit"] == lab.C and att["tree"] == lab.tree and att["manifest_sha256"] == m["manifest_sha256"]
    assert att["env_check"] is True and att["findings"] == 0
    assert m["commit"] == lab.C and m["tree"] == lab.tree and m["entry_count"] == 3  # a.txt, dir/b.sh, dir/c.txt


# ---- Arbeitsbaum-Manipulationen -------------------------------------------------------------------------------------
def test_handoff_tamper_file_content(lab: Lab):
    (lab.co / "a.txt").write_text("manipuliert\n")
    blocked(lab.verify(), "FAIL worktree-content")


def test_handoff_tamper_content_same_size(lab: Lab):
    """Gleiche Länge/Zeitstempel-unabhängig: Hash, nicht Größe, entscheidet."""
    (lab.co / "a.txt").write_bytes(b"alpha9\n")
    assert len(b"alpha9\n") == len(b"alpha2\n")
    blocked(lab.verify(), "FAIL worktree-content")


def test_handoff_tamper_extra_file(lab: Lab):
    (lab.co / "dir" / "zusatz.txt").write_text("x")
    blocked(lab.verify(), "FAIL worktree-extra")


def test_handoff_tamper_missing_file(lab: Lab):
    (lab.co / "dir" / "c.txt").unlink()
    blocked(lab.verify(), "FAIL worktree-missing")


@pytest.mark.parametrize("kind", ["file-symlink", "dir-symlink", "dangling-symlink"])
def test_handoff_tamper_symlink(lab: Lab, kind: str):
    if kind == "file-symlink":
        (lab.co / "a.txt").unlink()
        (lab.co / "a.txt").symlink_to(lab.dev / "a.txt")
    elif kind == "dir-symlink":
        shutil.move(str(lab.co / "dir"), str(lab.tmp / "dir_moved"))
        (lab.co / "dir").symlink_to(lab.tmp / "dir_moved")
    else:
        (lab.co / "dangling").symlink_to(lab.tmp / "gibtsnicht")
    blocked(lab.verify(), "FAIL worktree-symlink")


def test_handoff_tamper_fifo(lab: Lab):
    os.mkfifo(lab.co / "pipe")
    blocked(lab.verify(), "FAIL worktree-special")


def test_handoff_tamper_hardlink(lab: Lab):
    os.link(lab.co / "a.txt", lab.tmp / "hardlink_outside")
    r = lab.verify()
    blocked(r, "FAIL worktree-hardlink")
    assert "FAIL worktree-content" not in r.stdout  # Inhalt identisch: nur der Hardlink zählt


@pytest.mark.parametrize("rel,mode", [("a.txt", 0o755), ("dir/b.sh", 0o644)])
def test_handoff_tamper_exec_bit(lab: Lab, rel: str, mode: int):
    (lab.co / rel).chmod(mode)
    blocked(lab.verify(), "FAIL worktree-mode")


def test_handoff_tamper_gitlink_directory_in_checkout(lab: Lab):
    """Submodul-artiges Verzeichnis mit eigener .git-Datei im Arbeitsbaum -> Dateimenge weicht ab."""
    (lab.co / "sub").mkdir()
    (lab.co / "sub" / ".git").write_text("gitdir: ../../elsewhere\n")
    blocked(lab.verify(), "FAIL worktree-extra")


def test_handoff_gitlink_entry_rejected_at_manifest_and_verify(lab: Lab):
    """Commit mit Gitlink (160000) -> `manifest` lehnt ab (Exit 1, nichts geschrieben); ein dennoch gefälschtes Manifest mit Gitlink-Eintrag -> verify BLOCKED."""
    raw = lab.tmp / "rawrepo"
    raw.mkdir()
    g(lab.tmp, raw, "init", "-q", "-b", "main")
    blob = g(lab.tmp, raw, "hash-object", "-w", "--stdin", inp=b"x\n")
    tree_raw = b"100644 f.txt\0" + bytes.fromhex(blob) + b"160000 sub\0" + bytes.fromhex(lab.C)
    t = g(lab.tmp, raw, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", inp=tree_raw)
    c = g(lab.tmp, raw, "commit-tree", t, "-m", "gitlink")
    dest = lab.meta / "gl.json"
    r = lab.make_manifest(c, dest, repo=raw)
    assert r.returncode == 1 and "Gitlink" in r.stdout and not dest.exists(), out(r)
    forged = lab.forge(lambda m: m["entries"].append(["160000", lab.C, "sub"]), rehash=True)
    blocked(lab.verify(manifest=forged, key=False), "Gitlink")


# ---- .git des Klons -------------------------------------------------------------------------------------------------
def test_handoff_tamper_hook_in_git_hooks(lab: Lab):
    marker = lab.tmp / "HOOK_MARKER"
    hook = lab.co / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    blocked(lab.verify(), "FAIL git-hooks")
    assert not marker.exists()


def _config_cases(evil: Path, hooks_dir: Path, evil_cfg: Path) -> dict[str, str]:
    return {
        "fsmonitor": f"[core]\n\tfsmonitor = {evil}\n",
        "hooksPath": f"[core]\n\thooksPath = {hooks_dir}\n",
        "alias": f"[alias]\n\tstatus = !{evil}\n",
        "filter": f"[filter \"x\"]\n\tclean = {evil}\n\tsmudge = {evil}\n",
        "include": f"[include]\n\tpath = {evil_cfg}\n",
        "includeIf": f"[includeIf \"gitdir:/\"]\n\tpath = {evil_cfg}\n",
        "sshCommand": f"[core]\n\tsshCommand = {evil}\n",
        "pager": f"[core]\n\tpager = {evil}\n",
        "credential": f"[credential]\n\thelper = {evil}\n",
        "packObjectsHook": f"[uploadpack]\n\tpackObjectsHook = {evil}\n",
        "diff-external": f"[diff]\n\texternal = {evil}\n",
        "remote-helper-url": f"[remote \"origin\"]\n\turl = ext::{evil}\n",
        "extensions-worktreeconfig": "[extensions]\n\tworktreeConfig = true\n",
    }


@pytest.mark.parametrize("case", sorted(_config_cases(Path("/x"), Path("/y"), Path("/z"))))
def test_handoff_tamper_git_config_executes_nothing(lab: Lab, case: str):
    """Manipulierte .git/config (fsmonitor/hooksPath/alias/filter/include/…): verify, manifest und remote-check lehnen ab, eine Marker-Datei beweist: nichts lief."""
    marker = lab.tmp / "EXEC_MARKER"
    evil = lab.tmp / "evil.sh"
    evil.write_text(f"#!/bin/sh\ntouch {marker}\n")
    evil.chmod(0o755)
    hooks_dir = lab.tmp / "evilhooks"
    hooks_dir.mkdir()
    for n in ("post-checkout", "pre-commit", "reference-transaction", "post-merge", "pre-push"):
        shutil.copy(evil, hooks_dir / n)
    evil_cfg = lab.tmp / "evil.cfg"
    evil_cfg.write_text(f"[core]\n\tfsmonitor = {evil}\n")
    with open(lab.co / ".git" / "config", "a") as f:
        f.write(_config_cases(evil, hooks_dir, evil_cfg)[case])
    r = lab.verify()
    blocked(r, "FAIL git-config")
    assert str(evil) not in out(r)  # Werte der Konfiguration werden nicht ausgegeben
    exit2(lab.make_manifest(lab.C, lab.meta / f"m_{case}.json", repo=lab.co))
    exit2(lab.remote_check(repo=lab.co))
    assert not marker.exists(), "es wurde Code aus der manipulierten Konfiguration ausgeführt"


@pytest.mark.parametrize("how", ["file", "packed-refs"])
def test_handoff_tamper_refs_replace(lab: Lab, how: str):
    if how == "file":
        d = lab.co / ".git" / "refs" / "replace"
        d.mkdir(parents=True, exist_ok=True)
        (d / lab.C).write_text(lab.B + "\n")
    else:
        with open(lab.co / ".git" / "packed-refs", "a") as f:
            f.write(f"{lab.B} refs/replace/{lab.C}\n")
    blocked(lab.verify(), "FAIL git-replace")


def test_handoff_tamper_alternates(lab: Lab):
    info = lab.co / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text(str(lab.dev / ".git" / "objects") + "\n")
    blocked(lab.verify(), "FAIL git-alternates")


def test_handoff_tamper_info_attributes_filter(lab: Lab):
    (lab.co / ".git" / "info").mkdir(exist_ok=True)
    (lab.co / ".git" / "info" / "attributes").write_text("* filter=evil\n")
    blocked(lab.verify(), "FAIL git-attributes")


def test_handoff_tamper_head_points_to_other_commit_empty_commit(lab: Lab):
    """Neuer Commit D im Klon ohne Dateiänderung: Arbeitsbaum identisch, nur HEAD weicht ab -> trotzdem BLOCKED."""
    g(lab.tmp, lab.co, "commit", "-q", "--allow-empty", "-m", "D")
    r = lab.verify()
    blocked(r, "FAIL git-head")
    assert "FAIL worktree" not in r.stdout and "PASS worktree" in r.stdout


def test_handoff_tamper_head_points_to_other_commit_with_changes(lab: Lab):
    (lab.co / "a.txt").write_text("D-inhalt\n")
    g(lab.tmp, lab.co, "commit", "-q", "-am", "D")
    r = lab.verify()
    blocked(r, "FAIL git-head")
    assert "FAIL worktree-content" in r.stdout


def test_handoff_tamper_detached_head_other_sha(lab: Lab):
    (lab.co / ".git" / "HEAD").write_text(lab.B + "\n")
    blocked(lab.verify(), "FAIL git-head")


def test_handoff_tamper_git_dir_is_file_or_symlink(lab: Lab):
    shutil.move(str(lab.co / ".git"), str(lab.tmp / "realgit"))
    (lab.co / ".git").write_text(f"gitdir: {lab.tmp / 'realgit'}\n")
    blocked(lab.verify(), "FAIL git-dir")


# ---- Manifest-Manipulationen ----------------------------------------------------------------------------------------
def test_handoff_manifest_entry_replaced_hash_not_updated(lab: Lab):
    p = lab.forge(lambda m: m["entries"][0].__setitem__(1, "1" * 40))
    blocked(lab.verify(manifest=p), "FAIL manifest")


def test_handoff_manifest_entry_replaced_hash_updated_with_key_fails_mac(lab: Lab):
    """Angreifer rechnet den Hash neu, kennt aber den Schlüssel nicht -> mac ungültig."""
    p = lab.forge(lambda m: m["entries"][0].__setitem__(1, "1" * 40), rehash=True)
    blocked(lab.verify(manifest=p), "FAIL manifest-mac")


def test_handoff_manifest_entry_count_wrong(lab: Lab):
    p = lab.forge(lambda m: m.__setitem__("entry_count", 99))
    blocked(lab.verify(manifest=p), "entry_count")


def test_handoff_manifest_mac_wrong(lab: Lab):
    p = lab.forge(lambda m: m.__setitem__("mac", ("0" if m["mac"][0] != "0" else "1") + m["mac"][1:]))
    blocked(lab.verify(manifest=p), "FAIL manifest-mac")


def test_handoff_manifest_mac_removed_with_key_fails(lab: Lab):
    p = lab.forge(lambda m: m.pop("mac"))
    blocked(lab.verify(manifest=p), "FAIL manifest-mac")


def test_handoff_manifest_wrong_key(lab: Lab):
    other = lab.meta / "other.key"
    other.write_text(OTHER_KEY)
    other.chmod(0o600)
    a = ["verify", "--manifest", str(lab.manifest), "--checkout", str(lab.co), "--key-file", str(other), "--env-check"]
    blocked(run(a, lab.clean_env()), "FAIL manifest-mac")


def test_handoff_manifest_without_key_is_only_warn_documented_limit(lab: Lab):
    """DOKUMENTIERTE GRENZE: ohne --key-file wird nur die Selbstkonsistenz geprüft (WARN, Herkunft nicht belegt). Ein Angreifer, der Checkout UND Manifest
    kontrolliert, besteht ohne Schlüssel; mit Schlüssel scheitert er am mac."""
    (lab.co / "a.txt").write_text("manipuliert\n")
    forged_blob = blob_sha(b"manipuliert\n")

    def mut(m: dict) -> None:
        for e in m["entries"]:
            if e[2] == "a.txt":
                e[1] = forged_blob
        m.pop("mac", None)

    p = lab.forge(mut, rehash=True)
    r = lab.verify(manifest=p, key=False)
    assert r.returncode == 0 and "RESULT: OK" in r.stdout and "WARN manifest-mac" in r.stdout, out(r)  # Schwäche ohne Schlüssel
    blocked(lab.verify(manifest=p, key=True), "FAIL manifest-mac")  # mit Schlüssel geschlossen


def test_handoff_manifest_with_mac_but_verified_without_key_warns(lab: Lab):
    r = lab.verify(key=False)
    assert r.returncode == 0 and "WARN manifest-mac" in r.stdout and "Herkunft nicht belegt" in r.stdout, out(r)


# ---- Commit-Übergabe-Manipulation durch den Dev (Branch nach Manifest-Erzeugung verändert) ---------------------------
def test_handoff_remote_check_unchanged_branch_passes(lab: Lab):
    r = lab.remote_check()
    assert r.returncode == 0 and "PASS remote-ref" in r.stdout and "WARN" not in r.stdout, out(r)


def test_handoff_dev_forward_commit_E_on_top_is_warn_not_pass(lab: Lab):
    """Dev schiebt nach der Manifest-Erzeugung Commit E auf C: laut Spezifikation WARN (C ist Vorfahre), niemals PASS."""
    (lab.dev / "neu.txt").write_text("E\n")
    g(lab.tmp, lab.dev, "add", "-A")
    g(lab.tmp, lab.dev, "commit", "-q", "-m", "E")
    g(lab.tmp, lab.dev, "push", "-q", str(lab.bare), "main")
    r = lab.remote_check()
    assert r.returncode == 0 and "WARN remote-ref" in r.stdout and "Vorfahre" in r.stdout and "PASS remote-ref" not in r.stdout, out(r)


def test_handoff_dev_force_reset_and_new_commit_E_is_fail(lab: Lab):
    """Dev setzt den Branch auf B zurück, erzeugt E (gleicher Branchname) und force-pusht: C ist kein Vorfahre -> FAIL; Klon gegen neues Manifest -> BLOCKED."""
    g(lab.tmp, lab.dev, "reset", "-q", "--hard", lab.B)
    (lab.dev / "e.txt").write_text("E\n")
    g(lab.tmp, lab.dev, "add", "-A")
    g(lab.tmp, lab.dev, "commit", "-q", "-m", "E")
    E = g(lab.tmp, lab.dev, "rev-parse", "HEAD")
    g(lab.tmp, lab.dev, "push", "-q", "-f", str(lab.bare), "main")
    blocked_r = lab.remote_check()
    assert blocked_r.returncode == 1 and "FAIL remote-ref" in blocked_r.stdout and "kein Vorfahre" in blocked_r.stdout, out(blocked_r)
    new_manifest = lab.meta / "manifest_E.json"
    assert lab.make_manifest(E, new_manifest).returncode == 0
    blocked(lab.verify(manifest=new_manifest), "FAIL git-head")  # alter Klon (C) gegen neues Manifest (E)
    assert lab.verify().returncode == 0  # das alte Manifest bleibt an C gebunden


def test_handoff_dev_pushes_commit_not_known_locally_is_fail(lab: Lab):
    other = lab.tmp / "other"
    g(lab.tmp, lab.tmp, "clone", "-q", str(lab.bare), str(other))
    (other / "x.txt").write_text("x")
    g(lab.tmp, other, "add", "-A")
    g(lab.tmp, other, "commit", "-q", "-m", "fremd")
    g(lab.tmp, other, "push", "-q", "-f", "origin", "HEAD:refs/heads/main")
    r = lab.remote_check()
    assert r.returncode == 1 and "nicht belegbar" in r.stdout, out(r)


def test_handoff_remote_check_ref_missing_fails(lab: Lab):
    r = lab.remote_check(ref="refs/heads/gibtsnicht")
    assert r.returncode == 1 and "FAIL remote-ref" in r.stdout, out(r)


# ---- check-report (Orchestrator-Seite) ------------------------------------------------------------------------------
class Rpt:
    def __init__(self, lab: Lab):
        self.lab = lab
        r = lab.verify()
        assert r.returncode == 0, out(r)
        m = lab.m()
        self.expect = {"commit": m["commit"], "tree": m["tree"], "manifest_sha256": m["manifest_sha256"], "environment_id": "env_dummy1",
                       "nonce": "n" * 32, "min_ts": "2020-01-01T00:00:00Z"}
        self.report = {"commit": m["commit"], "tree": m["tree"], "manifest_sha256": m["manifest_sha256"], "session_id": "session_dummy1",
                       "environment_id": "env_dummy1", "tools": ["Read", "Grep", "Glob"], "nonce": "n" * 32, "attestation": attestation(r), "findings": []}
        self.session = {"id": "session_dummy1", "environment_id": "env_dummy1", "parent": None, "status": "idle",
                        "sources": [{"git_repository": {"url": "https://example.invalid/r.git", "revision": m["commit"]}}]}

    def run(self, *extra: str, session: bool = True, report_text: str | None = None) -> subprocess.CompletedProcess:
        d = self.lab.tmp / "rep"
        d.mkdir(exist_ok=True)
        (d / "expect.json").write_text(json.dumps(self.expect))
        (d / "report.md").write_text(report_text if report_text is not None else "Prüfbericht (erfunden)\n\n```json\n" + json.dumps(self.report) + "\n```\n")
        (d / "session.json").write_text(json.dumps(self.session))
        a = ["check-report", "--expect", str(d / "expect.json"), "--report", str(d / "report.md")]
        if session:
            a += ["--session", str(d / "session.json")]
        return run(a + list(extra))


@pytest.fixture()
def rp(lab: Lab) -> Rpt:
    return Rpt(lab)


def test_handoff_check_report_positive_text_with_json_block(rp: Rpt):
    r = rp.run()
    assert r.returncode == 0 and "RESULT: OK" in r.stdout and "FAIL" not in r.stdout, out(r)


_REPORT_FALSIFY = {
    "report.commit": lambda x, r, s: r.__setitem__("commit", "1" * 40),
    "report.commit-short": lambda x, r, s: r.__setitem__("commit", r["commit"][:12]),
    "report.tree": lambda x, r, s: r.__setitem__("tree", "2" * 40),
    "report.manifest_sha256": lambda x, r, s: r.__setitem__("manifest_sha256", "0" * 64),
    "report.nonce": lambda x, r, s: r.__setitem__("nonce", "x" * 32),
    "report.environment_id": lambda x, r, s: r.__setitem__("environment_id", "env_other"),
    "report.session_id": lambda x, r, s: r.__setitem__("session_id", "session_other"),
    "expect.environment_id": lambda x, r, s: x.__setitem__("environment_id", "env_expected_other"),
    "session.environment_id": lambda x, r, s: s.__setitem__("environment_id", "env_platform_other"),
    "session.revision-differs": lambda x, r, s: s["sources"][0]["git_repository"].__setitem__("revision", "3" * 40),
    "session.revision-short": lambda x, r, s: s["sources"][0]["git_repository"].__setitem__("revision", r["commit"][:12]),
    "session.revision-branchname": lambda x, r, s: s["sources"][0]["git_repository"].__setitem__("revision", "main"),
    "att.commit": lambda x, r, s: r["attestation"].__setitem__("commit", "4" * 40),
    "att.tree": lambda x, r, s: r["attestation"].__setitem__("tree", "5" * 40),
    "att.manifest_sha256": lambda x, r, s: r["attestation"].__setitem__("manifest_sha256", "6" * 64),
    "att.env_check-false": lambda x, r, s: r["attestation"].__setitem__("env_check", False),
    "att.env_check-string": lambda x, r, s: r["attestation"].__setitem__("env_check", "true"),
    "att.findings-1": lambda x, r, s: r["attestation"].__setitem__("findings", 1),
    "att.findings-bool": lambda x, r, s: r["attestation"].__setitem__("findings", True),
    "att.checked_at-too-old": lambda x, r, s: x.__setitem__("min_ts", "2999-01-01T00:00:00Z"),
    "att.checked_at-garbage": lambda x, r, s: r["attestation"].__setitem__("checked_at", "gestern"),
}


@pytest.mark.parametrize("case", sorted(_REPORT_FALSIFY))
def test_handoff_check_report_one_wrong_property_fails(rp: Rpt, case: str):
    _REPORT_FALSIFY[case](rp.expect, rp.report, rp.session)
    r = rp.run()
    assert r.returncode == 1 and "RESULT: BLOCKED" in r.stdout and "RESULT: OK" not in r.stdout and "FAIL" in r.stdout, out(r)


@pytest.mark.parametrize("tools", [["Bash"], ["Write"], ["Edit"], ["mcp__github__create_issue"], ["Read", "Grep", "Glob", "Bash"], [], "Read"])
def test_handoff_check_report_forbidden_or_missing_tools_fail(rp: Rpt, tools):
    rp.report["tools"] = tools
    r = rp.run()
    assert r.returncode == 1 and "FAIL tools" in r.stdout and "RESULT: OK" not in r.stdout, out(r)


def test_handoff_check_report_tool_subset_is_ok(rp: Rpt):
    rp.report["tools"] = ["Read"]
    assert rp.run().returncode == 0


@pytest.mark.parametrize("field", ["commit", "tree", "manifest_sha256", "session_id", "environment_id", "tools", "nonce", "attestation", "findings"])
def test_handoff_check_report_missing_report_field_exit2(rp: Rpt, field: str):
    del rp.report[field]
    exit2(rp.run())


@pytest.mark.parametrize("field", ["env_check", "findings", "checked_at"])
def test_handoff_check_report_missing_attestation_field_exit2(rp: Rpt, field: str):
    del rp.report["attestation"][field]
    exit2(rp.run())


@pytest.mark.parametrize("field", ["commit", "tree", "manifest_sha256", "environment_id", "nonce", "min_ts"])
def test_handoff_check_report_missing_expect_field_exit2(rp: Rpt, field: str):
    del rp.expect[field]
    exit2(rp.run())


def test_handoff_check_report_no_session_extract_fails_unless_explicit(rp: Rpt):
    r = rp.run(session=False)
    assert r.returncode == 1 and "FAIL session" in r.stdout and "RESULT: OK" not in r.stdout, out(r)
    w = rp.run("--allow-no-session", session=False)  # ausdrücklich nur Selbstauskunft: WARN, dokumentiert
    assert w.returncode == 0 and "WARN session" in w.stdout, out(w)


def test_handoff_check_report_without_json_block_exit2(rp: Rpt):
    exit2(rp.run(report_text="Nur Fließtext ohne JSON-Block.\n"))
    exit2(rp.run(report_text="```json\n{kaputt\n```\n"))


def test_handoff_check_report_rejects_attestation_of_tampered_checkout(lab: Lab, rp: Rpt):
    """Echte BLOCKED-Attestation eines manipulierten Klons (findings > 0) wird vom Orchestrator nicht akzeptiert."""
    (lab.co / "a.txt").write_text("manipuliert\n")
    r = lab.verify()
    blocked(r)
    rp.report["attestation"] = attestation(r)
    assert rp.report["attestation"]["findings"] > 0
    c = rp.run()
    assert c.returncode == 1 and "FAIL att-findings" in c.stdout, out(c)


def test_limit_expect_file_in_dev_vm_is_forgeable(lab: Lab):
    """GRENZEN-NACHWEIS (Klasse limit): liegt die ERWARTUNGSDATEI im Zugriff des Dev-root (gleiche VM), kann dieser sie mit eigenen Werten überschreiben
    und einen frei erfundenen Bericht samt Plattform-Auszug als OK durchbringen. Die Erwartungswerte müssen außerhalb des Dev-Zugriffs liegen."""
    rp = Rpt(lab)
    # Dev-Variante E: manipulierter Stand, eigenes Manifest
    g(lab.tmp, lab.dev, "reset", "-q", "--hard", lab.B)
    (lab.dev / "evil.sh").write_text("#!/bin/sh\necho boese\n")
    g(lab.tmp, lab.dev, "add", "-A")
    g(lab.tmp, lab.dev, "commit", "-q", "-m", "E")
    E = g(lab.tmp, lab.dev, "rev-parse", "HEAD")
    mE = lab.meta / "manifest_E.json"
    assert lab.make_manifest(E, mE).returncode == 0
    me = json.loads(mE.read_text())
    # Bericht/Auszug des Dev: komplett frei erfunden (Selbstauskunft, tools/attestation behauptet)
    rp.report.update({"commit": E, "tree": me["tree"], "manifest_sha256": me["manifest_sha256"]})
    rp.report["attestation"].update({"commit": E, "tree": me["tree"], "manifest_sha256": me["manifest_sha256"], "env_check": True, "findings": 0})
    rp.session["sources"][0]["git_repository"]["revision"] = E
    honest = rp.run()  # echte Erwartung (C) außerhalb des Dev-Zugriffs: Fälschung fliegt auf
    assert honest.returncode == 1 and "FAIL commit" in honest.stdout, out(honest)
    rp.expect.update({"commit": E, "tree": me["tree"], "manifest_sha256": me["manifest_sha256"]})  # Dev überschreibt die Erwartungsdatei
    forged = rp.run()
    assert forged.returncode == 0 and "RESULT: OK" in forged.stdout, out(forged)  # Grenze: Erwartung im Dev-Zugriff = wertlos


# =====================================================================================================================
# (3) test_secrets_*  Secrets nur als Namen, nie als Werte
# =====================================================================================================================
SECRET_VARS = {
    "GITHUB_TOKEN": "dummy-aaaaGHTOKENVALUE0001xyz",
    "AWS_SECRET_ACCESS_KEY": "dummy-bbbbAWSSECRETVALUE0002xyz",
    "CLAUDE_CODE_MESSAGING_TOKEN": "dummy-ccccMSGTOKENVALUE0003xyz",
    "SSH_AUTH_SOCK": "/dummy-ddddSSHSOCKVALUE0004xyz/agent.sock",
}
INGRESS_CONTENT = "dummy-eeeeINGRESSCONTENT0005xyz"
HOME_FILES = {
    ".ssh/id_ed25519": ("id_ed25519", "-----BEGIN OPENSSH PRIVATE KEY-----\ndummy-ffffSSHKEYBODY0006xyz\n-----END OPENSSH PRIVATE KEY-----\n"),
    ".git-credentials": (".git-credentials", "https://user:dummy-ggggCREDPASS0007xyz@example.invalid\n"),
    ".netrc": (".netrc", "machine example.invalid login u password dummy-hhhhNETRCPASS0008xyz\n"),
    ".config/gh/hosts.yml": (".config/gh", "example.invalid:\n  oauth_token: dummy-iiiiGHHOSTSTOKEN0009xyz\n"),
}


def _put_home_files(home: Path, which: list[str]) -> None:
    for rel in which:
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(HOME_FILES[rel][1])
        p.chmod(0o600)


def _secret_env(home: Path, ingress: Path, names: list[str] | None = None) -> dict[str, str]:
    ingress.write_text(INGRESS_CONTENT)
    ingress.chmod(0o600)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    env.update({k: v for k, v in SECRET_VARS.items() if names is None or k in names})
    if names is None or "CLAUDE_SESSION_INGRESS_TOKEN_FILE" in names:
        env["CLAUDE_SESSION_INGRESS_TOKEN_FILE"] = str(ingress)
    return env


ALL_SECRET_VALUES = list(SECRET_VARS.values()) + [INGRESS_CONTENT] + [c for _, c in HOME_FILES.values()]


def _assert_no_values(text: str) -> None:
    for v in ALL_SECRET_VALUES:
        for part in [v] + [ln for ln in v.splitlines() if "dummy-" in ln]:
            assert not leaked(text, part.strip()), f"Secret-Wert (Teilstring) in der Ausgabe: {part[:14]}…"


def test_secrets_all_names_reported_values_never(lab: Lab):
    _put_home_files(lab.home, list(HOME_FILES))
    env = _secret_env(lab.home, lab.tmp / "ingress_token")
    r = lab.verify(env=env)
    blocked(r)
    text = out(r)
    for name in list(SECRET_VARS) + ["CLAUDE_SESSION_INGRESS_TOKEN_FILE"]:
        assert name in text, name
    for _, label in [(k, v[0]) for k, v in HOME_FILES.items()]:
        assert label in text, label
    _assert_no_values(text)
    att = attestation(r)
    assert att["env_check"] is True and att["findings"] >= 5


@pytest.mark.parametrize("var", ["GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "CLAUDE_CODE_MESSAGING_TOKEN", "SSH_AUTH_SOCK", "CLAUDE_SESSION_INGRESS_TOKEN_FILE"])
def test_secrets_single_variable_alone_blocks(lab: Lab, var: str):
    env = _secret_env(lab.home, lab.tmp / "ingress_token", [var])
    r = lab.verify(env=env)
    blocked(r, var)
    _assert_no_values(out(r))


@pytest.mark.parametrize("rel", sorted(HOME_FILES))
def test_secrets_single_home_file_alone_blocks(lab: Lab, rel: str):
    _put_home_files(lab.home, [rel])
    r = lab.verify()
    blocked(r, HOME_FILES[rel][0])
    _assert_no_values(out(r))


def test_secrets_home_via_option_and_env_equivalent(lab: Lab):
    _put_home_files(lab.home, [".netrc"])
    r = lab.verify("--home", str(lab.home), env={"PATH": "/usr/bin:/bin", "HOME": str(lab.tmp / "ganz-anderes-home")})
    blocked(r, ".netrc")


def test_secrets_clean_environment_is_ok(lab: Lab):
    """Gleicher Lauf, bereinigte Umgebung und sauberes Home -> OK (kein Fehlalarm)."""
    r = lab.verify(env=lab.clean_env())
    assert r.returncode == 0 and "RESULT: OK" in r.stdout and "FAIL" not in r.stdout, out(r)
    _assert_no_values(out(r))


def test_secrets_without_env_check_is_flagged_in_attestation(lab: Lab):
    """Ohne --env-check keine Umgebungsprüfung: Exit 0 ist möglich, aber WARN und Attestation.env_check == false (check-report würde das ablehnen)."""
    env = _secret_env(lab.home, lab.tmp / "ingress_token")
    r = lab.verify(env=env, env_check=False)
    assert r.returncode == 0 and "WARN env" in r.stdout and attestation(r)["env_check"] is False, out(r)
    rp = Rpt(lab)
    rp.report["attestation"] = attestation(r)
    c = rp.run()
    assert c.returncode == 1 and "FAIL att-env" in c.stdout


def test_secrets_proxy_variables_warn_without_values(lab: Lab):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(lab.home), "HTTPS_PROXY": "http://dummy-proxyuser:dummy-proxypass1234567@127.0.0.1:9"}
    r = lab.verify(env=env)
    assert r.returncode == 0 and "WARN env-proxy" in r.stdout, out(r)
    assert "dummy-proxypass1234567" not in out(r) and "dummy-proxyuser" not in out(r)


# =====================================================================================================================
# (4) test_failclosed_*  Integritäts-/Bedienfehler und Abbruch -> nie Exit 0, nie OK-Attestation
# =====================================================================================================================
def test_failclosed_requires_isolated_mode(lab: Lab):
    r = run(["verify", "--manifest", str(lab.manifest), "--checkout", str(lab.co)], isolated=False)
    exit2(r)
    assert "isolierten Modus" in r.stderr


def _manifest_variants(lab: Lab) -> dict[str, Path]:
    text = lab.manifest.read_text()
    v: dict[str, Path] = {}
    v["missing"] = lab.meta / "gibtsnicht.json"
    v["directory"] = lab.meta / "ein_verzeichnis"
    v["directory"].mkdir()
    v["empty"] = lab.meta / "empty.json"
    v["empty"].write_text("")
    v["truncated"] = lab.meta / "trunc.json"
    v["truncated"].write_text(text[: len(text) // 2])
    v["not-an-object"] = lab.meta / "arr.json"
    v["not-an-object"].write_text("[1,2,3]")
    v["wrong-version"] = lab.meta / "ver.json"
    v["wrong-version"].write_text(json.dumps({**json.loads(text), "version": 2}))
    v["commit-not-hex"] = lab.meta / "chex.json"
    v["commit-not-hex"].write_text(json.dumps({**json.loads(text), "commit": "main"}))
    v["entries-malformed"] = lab.meta / "ent.json"
    v["entries-malformed"].write_text(json.dumps({**json.loads(text), "entries": [["100644", "x"]]}))
    v["symlink"] = lab.meta / "ln.json"
    v["symlink"].symlink_to(lab.manifest)
    v["binary"] = lab.meta / "bin.json"
    v["binary"].write_bytes(b"\xff\xfe\x00\x01")
    return v


@pytest.mark.parametrize("variant", ["missing", "directory", "empty", "truncated", "not-an-object", "wrong-version", "commit-not-hex", "entries-malformed",
                                     "symlink", "binary"])
def test_failclosed_unusable_manifest_exit2(lab: Lab, variant: str):
    exit2(lab.verify(manifest=_manifest_variants(lab)[variant]))


def _key_variants(lab: Lab) -> dict[str, Path]:
    v: dict[str, Path] = {}
    v["missing"] = lab.meta / "nokey"
    v["mode-0644"] = lab.meta / "k644"
    v["mode-0644"].write_text(KEY)
    v["mode-0644"].chmod(0o644)
    v["mode-0640"] = lab.meta / "k640"
    v["mode-0640"].write_text(KEY)
    v["mode-0640"].chmod(0o640)
    v["symlink"] = lab.meta / "klink"
    v["symlink"].symlink_to(lab.key)
    v["in-checkout"] = lab.co / "k.key"
    v["in-checkout"].write_text(KEY)
    v["in-checkout"].chmod(0o600)
    v["bad-format"] = lab.meta / "kbad"
    v["bad-format"].write_text("zz" * 32)
    v["bad-format"].chmod(0o600)
    v["too-short"] = lab.meta / "kshort"
    v["too-short"].write_text("ab" * 8)
    v["too-short"].chmod(0o600)
    v["directory"] = lab.meta / "kdir"
    v["directory"].mkdir()
    v["directory"].chmod(0o600)
    return v


@pytest.mark.parametrize("variant", ["missing", "mode-0644", "mode-0640", "symlink", "in-checkout", "bad-format", "too-short", "directory"])
def test_failclosed_bad_key_file_exit2(lab: Lab, variant: str):
    k = _key_variants(lab)[variant]
    r = run(["verify", "--manifest", str(lab.manifest), "--checkout", str(lab.co), "--key-file", str(k), "--env-check"], lab.clean_env())
    exit2(r)


@pytest.mark.parametrize("variant", ["mode-0644", "symlink", "bad-format"])
def test_failclosed_bad_key_file_blocks_manifest_creation(lab: Lab, variant: str):
    k = _key_variants(lab)[variant]
    dest = lab.meta / "neu.json"
    r = run(["manifest", "--repo", str(lab.dev), "--commit", lab.C, "--out", str(dest), "--key-file", str(k)])
    exit2(r)
    assert not dest.exists()


def test_failclosed_checkout_does_not_exist(lab: Lab):
    exit2(lab.verify(co=lab.tmp / "gibtsnicht"))


def test_failclosed_checkout_is_a_file(lab: Lab):
    f = lab.tmp / "ich_bin_eine_datei"
    f.write_text("x")
    exit2(lab.verify(co=f))


def test_failclosed_checkout_is_symlink(lab: Lab):
    ln = lab.tmp / "co_link"
    ln.symlink_to(lab.co)
    exit2(lab.verify(co=ln))


def test_failclosed_checkout_without_git_dir_is_blocked(lab: Lab):
    empty = lab.tmp / "leer"
    empty.mkdir()
    r = lab.verify(co=empty)
    assert r.returncode in (1, 2), out(r)
    never_ok(r)
    assert r.returncode == 2 or "FAIL git-dir" in r.stdout


@pytest.mark.parametrize("content", ["garbage\nx - y\n", "1 2 3\nx - y\n"])
def test_failclosed_unreadable_mountinfo_blocks(lab: Lab, content: str):
    mi = lab.meta / "mountinfo"
    mi.write_text(content)
    r = lab.verify("--mountinfo", str(mi))
    assert r.returncode == 1 and "FAIL mounts" in r.stdout and "RESULT: OK" not in r.stdout, out(r)


# Befund (Isolationstests): parse_mountinfo() überging Zeilen ohne " - " stillschweigend -> behoben (fail closed); Test war strict-xfail, jetzt normaler Test.
@pytest.mark.parametrize("content", ["", "kein trennzeichen in dieser zeile\n"])
def test_failclosed_mountinfo_without_any_parsable_line_blocks(lab: Lab, content: str):
    mi = lab.meta / "mountinfo_leer"
    mi.write_text(content)
    r = lab.verify("--mountinfo", str(mi))
    assert r.returncode in (1, 2) and "RESULT: OK" not in r.stdout, out(r)


def test_failclosed_missing_mountinfo_blocks(lab: Lab):
    r = lab.verify("--mountinfo", str(lab.meta / "gibtsnicht"))
    assert r.returncode == 1 and "FAIL mounts" in r.stdout and "RESULT: OK" not in r.stdout, out(r)


def test_failclosed_mount_below_checkout_blocks(lab: Lab):
    mi = lab.meta / "mountinfo"
    mi.write_text(f"25 1 8:1 / / rw - ext4 /dev/vda rw\n40 25 0:50 / {lab.co}/dir rw - tmpfs none rw\n")
    blocked(lab.verify("--mountinfo", str(mi)), "FAIL mount-below")


def test_failclosed_internal_exception_is_exit2_in_process(monkeypatch, capsys):
    """Eine unerwartete Ausnahme darf nie als OK (0) oder als Regelverstoß (1) erscheinen."""
    def boom(a):
        raise RuntimeError("simulierter interner Fehler")
    monkeypatch.setattr(RH, "cmd_verify", boom)
    rc = RH.main(["verify", "--manifest", "x", "--checkout", "/"])
    cap = capsys.readouterr()
    assert rc == 2 and "INTERNER FEHLER: RuntimeError" in cap.err and "RESULT: OK" not in cap.out


def test_failclosed_tool_error_is_exit2_in_process(monkeypatch, capsys):
    def boom(a):
        raise RH.ToolError("simuliert")
    monkeypatch.setattr(RH, "cmd_check_report", boom)
    assert RH.main(["check-report", "--expect", "x", "--report", "y"]) == 2
    assert "RESULT: OK" not in capsys.readouterr().out


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGKILL])
def test_failclosed_abort_mid_run_leaves_no_ok_attestation(lab: Lab, sig):
    """Abbruch (SIGTERM/SIGKILL, wie Timeout) mitten im Lauf: kein OK, keine Attestation auf stdout, Exit ≠ 0. Der Lauf wird durch eine große SPARSE-Datei
    (Hashing dauert Sekunden) im Checkout verlängert; Manifest dazu ohne mac (nur für diesen Test)."""
    big = lab.co / "zzz_big.bin"
    with open(big, "wb") as f:
        f.truncate(40 * 1024 ** 3)
    if os.stat(big).st_blocks * 512 > (1 << 20):
        big.unlink()
        pytest.skip("Dateisystem unterstützt keine Sparse-Dateien: Test würde echten Speicher belegen")
    p = lab.forge(lambda m: (m["entries"].append(["100644", "0" * 40, "zzz_big.bin"]), m.pop("mac", None)), rehash=True)
    cmd = [sys.executable, "-I", str(SCRIPT), "verify", "--manifest", str(p), "--checkout", str(lab.co), "--env-check"]
    proc = subprocess.Popen(cmd, env=lab.clean_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd="/")
    try:
        time.sleep(1.0)
        assert proc.poll() is None, "Testannahme verletzt: der Lauf war schon beendet, bevor abgebrochen wurde"
        proc.send_signal(sig)
        so, se = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        big.unlink()
    assert proc.returncode == -int(sig), proc.returncode
    assert "RESULT: OK" not in so and "ATTESTATION" not in so, so


# =====================================================================================================================
# (1) test_limit_*  GRENZEN-NACHWEIS: root im selben Kernel umgeht die Schutzmechanismen (Angriff GELINGT)
# =====================================================================================================================
LAB_BASE = Path("/home/user")


def _need_root(*tools: str) -> None:
    if os.geteuid() != 0:
        pytest.skip("nur als root ausführbar (Angreifer-Modell: Dev-Agent ist root)")
    for t in tools:
        if shutil.which(t) is None:
            pytest.skip(f"Werkzeug fehlt: {t}")


def _cap_eff() -> int:
    for ln in Path("/proc/self/status").read_text().splitlines():
        if ln.startswith("CapEff:"):
            return int(ln.split()[1], 16)
    return 0


CAP_SYS_ADMIN, CAP_SYS_PTRACE, CAP_CHOWN = 21, 19, 0


def _need_cap(*caps: int) -> None:
    eff = _cap_eff()
    for c in caps:
        if not eff & (1 << c):
            pytest.skip(f"Capability {c} fehlt im Testprozess (Angreifer-Modell: root mit CAP_SYS_ADMIN/PTRACE)")


class LimitLab:
    def __init__(self, d: Path):
        self.dir = d
        self.popens: list[subprocess.Popen] = []
        self.pids: list[int] = []

    def sh(self, *args: str, **kw) -> subprocess.CompletedProcess:
        return subprocess.run(list(args), env=BASE_ENV, capture_output=True, text=True, cwd="/", **kw)

    def spawn_sleeper(self, secret: str, bind_src: Path | None = None, bind_dst: Path | None = None) -> int:
        """Wie scripts/ro_run.sh (unshare --mount --pid --fork, setpriv uid 65534, bounding-set leer, no-new-privs), aber mit Dummy-`sleep` statt Runner.
        Optional ro-Bind-Mount (nur im privaten Mount-Namespace). Liefert die HOST-pid des sleep."""
        script = ('set -e; if [ -n "$1" ]; then mount --bind "$1" "$2"; mount -o remount,bind,ro "$2"; fi; '
                  'exec setpriv --reuid=65534 --regid=65534 --clear-groups --bounding-set=-all --no-new-privs sleep 300')
        args = ["unshare", "--mount", "--pid", "--fork", "--", "sh", "-c", script, "sh", str(bind_src or ""), str(bind_dst or "")]
        pr = subprocess.Popen(args, env={"PATH": "/usr/bin:/bin", "ISO_DUMMY_SECRET": secret}, cwd="/", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE)
        self.popens.append(pr)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                kids = Path(f"/proc/{pr.pid}/task/{pr.pid}/children").read_text().split()
            except OSError:
                kids = []
            for k in kids:
                try:
                    uid_line = [ln for ln in Path(f"/proc/{k}/status").read_text().splitlines() if ln.startswith("Uid:")][0].split()[1:]
                    if Path(f"/proc/{k}/comm").read_text().strip() == "sleep" and uid_line == ["65534"] * 4:
                        self.pids.append(int(k))
                        return int(k)
                except (OSError, IndexError):
                    pass
            if pr.poll() is not None:
                pytest.fail(f"unshare/setpriv beendet (rc {pr.returncode}): {pr.stderr.read()[:300]}")
            time.sleep(0.05)
        pytest.fail("Prozess wurde nicht als uid 65534 sleep sichtbar")

    def status(self, pid: int) -> dict[str, str]:
        res = {}
        for ln in Path(f"/proc/{pid}/status").read_text().splitlines():
            k, _, v = ln.partition(":")
            res[k] = v.strip()
        return res

    def cleanup(self) -> None:
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        for pr in self.popens:
            try:
                pr.kill()
            except OSError:
                pass
            try:
                pr.wait(timeout=10)
            except Exception:
                pass
        for pid in self.pids:  # Prozess wirklich weg?
            for _ in range(100):
                if not Path(f"/proc/{pid}").exists():
                    break
                time.sleep(0.05)
        try:
            for ln in Path("/proc/self/mountinfo").read_text().splitlines():
                mp = ln.split()[4]
                if mp == str(self.dir) or mp.startswith(str(self.dir) + "/"):
                    subprocess.run(["umount", "-l", mp], capture_output=True)
        except OSError:
            pass
        subprocess.run(["chattr", "-R", "-i", str(self.dir)], capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)


@pytest.fixture()
def limit_lab():
    _need_root()
    if not LAB_BASE.is_dir() or not os.access(LAB_BASE, os.W_OK):
        pytest.skip(f"{LAB_BASE} nicht beschreibbar")
    d = Path(tempfile.mkdtemp(dir=str(LAB_BASE), prefix="iso_t_"))
    assert not str(d).startswith("/tmp"), d
    lab_ = LimitLab(d)
    try:
        yield lab_
    finally:
        lab_.cleanup()
        assert not d.exists(), f"Aufräumen unvollständig: {d}"
        for pid in lab_.pids:
            assert not Path(f"/proc/{pid}").exists(), f"Prozess {pid} läuft noch"


@pytest.mark.parametrize("uid", [65000, 1000])
def test_limit_root_reads_and_writes_file_of_foreign_uid(limit_lab: LimitLab, uid: int):
    """Angriff gelingt: root liest/überschreibt eine 0400-Datei fremder uid und legt Dateien in deren 0500-Verzeichnis an."""
    _need_root("chown")
    d = limit_lab.dir / f"fremd{uid}"
    d.mkdir()
    f = d / "geheim.txt"
    f.write_text("DUMMY-INHALT-VOR\n")
    os.chown(f, uid, uid)
    f.chmod(0o400)
    os.chown(d, uid, uid)
    d.chmod(0o500)
    # Vorbedingung: Schutz wäre für die fremde uid selbst nicht schreibbar (Datei 0400, Verzeichnis 0500)
    assert (f.stat().st_uid, f.stat().st_mode & 0o777, d.stat().st_mode & 0o777) == (uid, 0o400, 0o500)
    assert f.read_text() == "DUMMY-INHALT-VOR\n"
    f.write_text("DUMMY-INHALT-NACH-ROOT\n")
    (d / "von_root.txt").write_text("root war hier\n")
    assert f.read_text() == "DUMMY-INHALT-NACH-ROOT\n" and (d / "von_root.txt").exists()


def test_limit_root_removes_immutable_flag_and_writes(limit_lab: LimitLab):
    """Angriff gelingt: `chattr +i` schützt nicht gegen root (er hebt das Flag auf und schreibt/löscht)."""
    _need_root("chattr", "lsattr")
    f = limit_lab.dir / "geschuetzt.txt"
    f.write_text("vorher\n")
    r = limit_lab.sh("chattr", "+i", str(f))
    if r.returncode != 0:
        pytest.skip(f"chattr +i auf diesem Dateisystem nicht möglich: {r.stderr.strip()[:100]}")
    assert "i" in limit_lab.sh("lsattr", str(f)).stdout.split()[0]
    with pytest.raises(PermissionError):  # Flag wirkt gegen den normalen Schreibversuch (auch als root)
        f.write_text("blockiert\n")
    with pytest.raises(PermissionError):
        f.unlink()
    assert limit_lab.sh("chattr", "-i", str(f)).returncode == 0  # root hebt auf
    f.write_text("nachher von root\n")
    assert f.read_text() == "nachher von root\n"
    f.unlink()
    assert not f.exists()


def test_limit_root_reads_environ_of_unprivileged_process(limit_lab: LimitLab):
    """Angriff gelingt: root liest /proc/<pid>/environ eines als uid 65534 laufenden, entprivilegierten Prozesses (Dummy-Secret, synthetisch)."""
    _need_root("setpriv", "unshare")
    _need_cap(CAP_SYS_PTRACE)
    secret = "dummy-JJJJISOLATION-SECRET-0010-xyz"
    pid = limit_lab.spawn_sleeper(secret)
    st = limit_lab.status(pid)
    assert st["Uid"].split() == ["65534"] * 4 and st["NoNewPrivs"] == "1" and int(st["CapBnd"], 16) == 0 and int(st["CapEff"], 16) == 0  # Schutz vorhanden
    env = Path(f"/proc/{pid}/environ").read_bytes()
    assert f"ISO_DUMMY_SECRET={secret}".encode() in env


def test_limit_root_reads_and_writes_files_via_proc_pid_root(limit_lab: LimitLab):
    """Angriff gelingt: über /proc/<pid>/root liest root eine für uid 65534 unlesbare Datei und schreibt eine neue Datei in das Dateisystem des Prozesses."""
    _need_root("setpriv", "unshare")
    _need_cap(CAP_SYS_PTRACE)
    sec = limit_lab.dir / "nur_root.txt"
    sec.write_text("DUMMY-NUR-ROOT\n")
    sec.chmod(0o400)
    # Vorbedingung: ein uid-65534-Prozess kommt nicht an die Datei (Verzeichnis 0700 root)
    pre = limit_lab.sh("setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", "cat", str(sec))
    assert pre.returncode != 0
    pid = limit_lab.spawn_sleeper("dummy-unused-0011")
    assert Path(f"/proc/{pid}/root{sec}").read_text() == "DUMMY-NUR-ROOT\n"
    Path(f"/proc/{pid}/root{limit_lab.dir}/von_root_via_proc.txt").write_text("x\n")
    assert (limit_lab.dir / "von_root_via_proc.txt").read_text() == "x\n"


def _ro_ns(limit_lab: LimitLab) -> tuple[int, Path, Path]:
    prot = limit_lab.dir / "prot"
    prot.write_text("orig\n")
    mnt = limit_lab.dir / "mnt"
    mnt.write_text("")
    pid = limit_lab.spawn_sleeper("dummy-unused-0012", prot, mnt)
    return pid, prot, mnt


def test_limit_root_nsenter_remounts_ro_bind_rw_and_writes(limit_lab: LimitLab):
    """Angriff gelingt: `nsenter -t <pid> -m` + `mount -o remount,bind,rw` hebt einen ro-Bind-Mount im privaten Namespace auf und schreibt durch."""
    _need_root("setpriv", "unshare", "nsenter", "mount")
    _need_cap(CAP_SYS_ADMIN)
    pid, prot, mnt = _ro_ns(limit_lab)
    # Vorbedingung: im Namespace ist der Pfad schreibgeschützt; der Host-Namespace sieht den Mount nicht
    pre = limit_lab.sh("nsenter", "-t", str(pid), "-m", "--", "sh", "-c", f"echo vorher > {mnt}")
    assert pre.returncode != 0 and "Read-only" in pre.stderr, pre.stderr
    assert not any(ln.split()[4] == str(mnt) for ln in Path("/proc/self/mountinfo").read_text().splitlines())
    rw = limit_lab.sh("nsenter", "-t", str(pid), "-m", "--", "mount", "-o", "remount,bind,rw", str(mnt))
    assert rw.returncode == 0, rw.stderr
    post = limit_lab.sh("nsenter", "-t", str(pid), "-m", "--", "sh", "-c", f"echo nachher_ns > {mnt}")
    assert post.returncode == 0, post.stderr
    assert prot.read_text() == "nachher_ns\n"  # durchgeschrieben auf die Host-Datei


def test_limit_root_writes_ro_namespace_path_via_proc_pid_root_after_remount(limit_lab: LimitLab):
    """Vor dem Remount verhindert der ro-Mount das Schreiben über /proc/<pid>/root (EROFS); nach nsenter-remount gelingt es root trotzdem."""
    _need_root("setpriv", "unshare", "nsenter", "mount")
    _need_cap(CAP_SYS_ADMIN, CAP_SYS_PTRACE)
    pid, prot, mnt = _ro_ns(limit_lab)
    via = Path(f"/proc/{pid}/root{mnt}")
    with pytest.raises(OSError) as ei:
        via.write_text("blockiert\n")
    assert ei.value.errno == errno.EROFS
    assert prot.read_text() == "orig\n"
    assert limit_lab.sh("nsenter", "-t", str(pid), "-m", "--", "mount", "-o", "remount,bind,rw", str(mnt)).returncode == 0
    via.write_text("via_proc_root\n")
    assert prot.read_text() == "via_proc_root\n"
