"""Tests für scripts/review_handoff.py (kontrollierte Commit-Übergabe). Nur Wegwerf-Repos in tmp_path, erfundene Daten, keine externen Befehle
außer git (lokal, file-Pfade), nichts außerhalb von tmp_path wird geschrieben. Das Skript läuft als Unterprozess mit `python -I` (Exit-Codes!)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "review_handoff.py"
SPEC = importlib.util.spec_from_file_location("review_handoff_mod", SCRIPT)
RH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RH)  # Import ist erlaubt (Isolationsprüfung nur bei __main__)

KEY = "ab" * 32
DUMMY_SECRET = "DUMMYWERT-NICHT-AUSGEBEN-12345"


def genv(tmp: Path) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": str(tmp / "githome"), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


def g(tmp: Path, repo: Path | str, *args: str, inp: bytes | None = None) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], env=genv(tmp), input=inp, capture_output=True)
    assert r.returncode == 0, (args, r.stderr.decode())
    return r.stdout.decode().strip()


def make_repo(tmp: Path, name: str, files: dict[str, tuple[bytes, bool]]) -> tuple[Path, str]:
    repo = tmp / name
    repo.mkdir()
    g(tmp, repo, "init", "-q", "-b", "main")
    for rel, (data, ex) in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        p.chmod(0o755 if ex else 0o644)
    g(tmp, repo, "add", "-A")
    g(tmp, repo, "commit", "-q", "-m", "init")
    return repo, g(tmp, repo, "rev-parse", "HEAD")


GOOD = {"a.txt": (b"alpha\n", False), "dir/b.sh": (b"#!/bin/sh\necho hi\n", True), ".gitignore": (b"*.log\n", False)}


def raw_commit(tmp: Path, name: str, spec: dict) -> tuple[Path, str]:
    """Commit mit beliebigen Tree-Einträgen (umgeht git-Pfadprüfungen via hash-object --literally). spec: name -> (mode, bytes) | dict."""
    repo = tmp / name
    repo.mkdir()
    g(tmp, repo, "init", "-q", "-b", "main")

    def tree(d: dict) -> str:
        raw = b""
        for n, v in sorted(d.items()):
            if isinstance(v, dict):
                mode, sha = "40000", tree(v)
            elif v[0] == "160000":
                mode, sha = v[0], v[1].decode()
            else:
                mode, sha = v[0], g(tmp, repo, "hash-object", "-w", "--stdin", inp=v[1])
            raw += f"{mode} {n}".encode() + b"\0" + bytes.fromhex(sha)
        return g(tmp, repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", inp=raw)

    t = tree(spec)
    return repo, g(tmp, repo, "commit-tree", t, "-m", "raw")


def run(args: list[str], env: dict[str, str] | None = None, isolated: bool = True) -> subprocess.CompletedProcess:
    base = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-home"}
    base.update(env or {})
    cmd = [sys.executable] + (["-I"] if isolated else []) + [str(SCRIPT)] + args
    return subprocess.run(cmd, env=base, capture_output=True, text=True, cwd="/")


def keyfile(tmp: Path, name: str = "k.key") -> Path:
    p = tmp / "meta" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text(KEY + "\n")
    p.chmod(0o600)
    return p


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.src, self.sha = make_repo(tmp, "src", GOOD)
        self.key = keyfile(tmp)
        self.manifest = tmp / "meta" / "m.json"
        self.mi = tmp / "meta" / "mountinfo"
        self.mi.write_text("25 1 8:1 / / rw,relatime - ext4 /dev/vda rw\n")
        self.home = tmp / "home"
        self.home.mkdir()
        r = run(["manifest", "--repo", str(self.src), "--commit", self.sha, "--out", str(self.manifest), "--key-file", str(self.key)])
        assert r.returncode == 0, r.stderr + r.stdout
        self.co = tmp / "co"
        g(tmp, tmp, "clone", "-q", "--no-hardlinks", str(self.src), str(self.co))

    def verify(self, *extra: str, env: dict[str, str] | None = None, key: bool = True, mi: Path | None = None) -> subprocess.CompletedProcess:
        a = ["verify", "--manifest", str(self.manifest), "--checkout", str(self.co), "--mountinfo", str(mi or self.mi)]
        if key:
            a += ["--key-file", str(self.key)]
        return run(a + list(extra), env)

    def m(self) -> dict:
        return json.loads(self.manifest.read_text())

    def write_m(self, m: dict) -> None:
        self.manifest.write_text(json.dumps(m))


@pytest.fixture()
def w(tmp_path: Path) -> World:
    return World(tmp_path)


def assert_fail(r: subprocess.CompletedProcess, code: int, token: str | None = None) -> None:
    assert r.returncode == code, (r.returncode, r.stdout, r.stderr)
    if token:
        assert token in r.stdout + r.stderr, (token, r.stdout, r.stderr)


# ---------------- Aufruf ----------------
def test_requires_isolated_mode():
    r = run(["--help"], isolated=False)
    assert r.returncode == 2 and "isolierten Modus" in r.stderr


def test_unknown_subcommand_exit_2():
    assert run(["frobnicate"]).returncode == 2


# ---------------- manifest ----------------
def test_manifest_positive_content(w: World):
    m = w.m()
    assert m["commit"] == w.sha and m["tree"] == g(w.tmp, w.src, "rev-parse", w.sha + "^{tree}")
    assert m["entries"] == sorted(m["entries"], key=lambda e: e[2])
    assert {e[2]: e[0] for e in m["entries"]} == {".gitignore": "100644", "a.txt": "100644", "dir/b.sh": "100755"}
    assert m["entry_count"] == 3 and m["manifest_sha256"] == RH.manifest_hash(m) and m["mac"] == RH.manifest_mac(m, KEY)
    assert stat.S_IMODE(os.stat(w.manifest).st_mode) == 0o600


def test_manifest_without_key_has_no_mac(w: World):
    out = w.tmp / "meta" / "m2.json"
    assert run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(out)]).returncode == 0
    assert "mac" not in json.loads(out.read_text())


def test_manifest_uses_git_object_not_worktree(w: World):
    (w.src / "a.txt").write_text("lokal geändert\n")
    out = w.tmp / "meta" / "m3.json"
    assert run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(out)]).returncode == 0
    assert json.loads(out.read_text())["manifest_sha256"] == w.m()["manifest_sha256"]


def test_manifest_out_exists_exit_2(w: World):
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(w.manifest)]), 2)


def test_manifest_out_symlink_exit_2(w: World):
    ln = w.tmp / "meta" / "ln.json"
    ln.symlink_to(w.tmp / "meta" / "ziel.json")
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(ln)]), 2)
    assert not (w.tmp / "meta" / "ziel.json").exists()


def test_manifest_out_inside_repo_exit_2(w: World):
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(w.src / "m.json")]), 2)


def test_manifest_key_inside_repo_exit_2(w: World):
    k = w.src / "k.key"
    k.write_text(KEY)
    k.chmod(0o600)
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(w.tmp / "meta" / "x.json"), "--key-file", str(k)]), 2)


@pytest.mark.parametrize("mode,content", [(0o644, KEY), (0o600, "zz" * 32), (0o600, "ab" * 10)])
def test_key_file_requirements(w: World, mode: int, content: str):
    k = w.tmp / "meta" / "bad.key"
    k.write_text(content)
    k.chmod(mode)
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(w.tmp / "meta" / "x.json"), "--key-file", str(k)]), 2)


def test_key_file_symlink_exit_2(w: World):
    ln = w.tmp / "meta" / "kl.key"
    ln.symlink_to(w.key)
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(w.tmp / "meta" / "x.json"), "--key-file", str(ln)]), 2)


def test_manifest_short_sha_exit_2(w: World):
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha[:12], "--out", str(w.tmp / "meta" / "x.json")]), 2)


def test_manifest_branch_name_and_uppercase_exit_2(w: World):
    for c in ("main", "HEAD", w.sha.upper()):
        assert_fail(run(["manifest", "--repo", str(w.src), "--commit", c, "--out", str(w.tmp / "meta" / "x.json")]), 2)


def test_manifest_non_commit_exit_2(w: World):
    tree = g(w.tmp, w.src, "rev-parse", w.sha + "^{tree}")
    blob = g(w.tmp, w.src, "rev-parse", w.sha + ":a.txt")
    for obj in (tree, blob, "0" * 40):
        assert_fail(run(["manifest", "--repo", str(w.src), "--commit", obj, "--out", str(w.tmp / "meta" / "x.json")]), 2)


def test_manifest_annotated_tag_object_exit_2(w: World):
    g(w.tmp, w.src, "tag", "-a", "-m", "t", "v1")
    tag = g(w.tmp, w.src, "rev-parse", "v1")
    assert tag != w.sha
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", tag, "--out", str(w.tmp / "meta" / "x.json")]), 2)


BAD_SPECS = {
    "symlink": {"a.txt": ("100644", b"x"), "ln": ("120000", b"a.txt")},
    "gitlink": {"a.txt": ("100644", b"x"), "sub": ("160000", b"1" * 40)},
    "dotgit_dir": {".git": {"config": ("100644", b"x")}},
    "dotgit_nested": {"d": {".GIT": {"hooks": ("100644", b"x")}}},
    "dotgit_file": {".git": ("100644", b"gitdir: /x")},
    "dotgit_dots": {".git.": ("100644", b"x")},
    "git_short": {"GIT~1": {"x": ("100644", b"x")}},
    "dotdot": {"..": {"x": ("100644", b"x")}},
    "dot": {".": {"x": ("100644", b"x")}},
    "backslash": {"a\\b": ("100644", b"x")},
    "colon": {".git::$INDEX_ALLOCATION": ("100644", b"x")},
    "control": {"a\tb": ("100644", b"x")},
    "newline": {"a\nb": ("100644", b"x")},
    "case_collision": {"Readme": ("100644", b"x"), "README": ("100644", b"y")},
}


@pytest.mark.parametrize("name", sorted(BAD_SPECS))
def test_manifest_rejects_bad_tree(tmp_path: Path, name: str):
    repo, sha = raw_commit(tmp_path, "bad", BAD_SPECS[name])
    out = tmp_path / "m.json"
    r = run(["manifest", "--repo", str(repo), "--commit", sha, "--out", str(out)])
    assert_fail(r, 1, "VERSTOSS")
    assert not out.exists()


@pytest.mark.parametrize("mode", ["100664", "100600"])
def test_manifest_git_canonicalizes_odd_modes(tmp_path: Path, mode: str):
    """git normalisiert Dateimodi beim Lesen (100664 -> 100644): das Manifest enthält nie einen Sondermodus; die Modusprüfung ist Tiefenverteidigung
    (siehe test_verify_manifest_odd_mode)."""
    repo, sha = raw_commit(tmp_path, "m", {"a.txt": (mode, b"x")})
    out = tmp_path / "m.json"
    assert run(["manifest", "--repo", str(repo), "--commit", sha, "--out", str(out)]).returncode == 0
    assert json.loads(out.read_text())["entries"][0][0] == "100644"


def test_manifest_rejects_non_utf8_path(tmp_path: Path):
    repo = tmp_path / "bad"
    repo.mkdir()
    g(tmp_path, repo, "init", "-q", "-b", "main")
    blob = g(tmp_path, repo, "hash-object", "-w", "--stdin", inp=b"x")
    raw = b"100644 \xff\xfe\0" + bytes.fromhex(blob)
    t = g(tmp_path, repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", inp=raw)
    sha = g(tmp_path, repo, "commit-tree", t, "-m", "x")
    r = run(["manifest", "--repo", str(repo), "--commit", sha, "--out", str(tmp_path / "m.json")])
    assert_fail(r, 1, "VERSTOSS")


def test_manifest_allows_gitignore_and_gitattributes_names(tmp_path: Path):
    repo, sha = raw_commit(tmp_path, "ok", {".gitignore": ("100644", b"x"), ".gitattributes": ("100644", b"y"), "gitfoo": ("100644", b"z")})
    assert run(["manifest", "--repo", str(repo), "--commit", sha, "--out", str(tmp_path / "m.json")]).returncode == 0


CFG_NAMES = ["fsmonitor", "hookspath", "alias", "filter", "include", "includeif", "sshcommand", "credential", "urlinstead", "ext_url", "fd_url",
             "syntax", "nosection", "worktreeconfig", "filemode_bad", "legacy_core_sub", "inline_section", "mixed_case"]


def _cfg_variants(tmp: Path) -> dict[str, str]:
    marker = tmp / "MARKER"
    script = tmp / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(0o755)
    inc = tmp / "inc.cfg"
    inc.write_text("[core]\n\tbare = false\n")
    return {
        "fsmonitor": f"[core]\n\tfsmonitor = {script}\n",
        "hookspath": f"[core]\n\thooksPath = {tmp}\n",
        "alias": f"[alias]\n\tx = !touch {marker}\n",
        "filter": f"[filter \"f\"]\n\tclean = touch {marker}\n",
        "include": f"[include]\n\tpath = {inc}\n",
        "includeif": f"[includeIf \"gitdir:/\"]\n\tpath = {inc}\n",
        "sshcommand": f"[core]\n\tsshCommand = touch {marker}\n",
        "credential": "[credential]\n\thelper = store\n",
        "urlinstead": "[url \"https://x@example.invalid/\"]\n\tinsteadOf = a:\n",
        "ext_url": "[remote \"o\"]\n\turl = ext::sh -c touch% " + str(marker) + "\n",
        "fd_url": "[remote \"o\"]\n\turl = fd::17\n",
        "syntax": "[core\n",
        "nosection": "bare = true\n",
        "worktreeconfig": "[extensions]\n\tworktreeConfig = true\n",
        "filemode_bad": "[core]\n\tfilemode = maybe\n",
        "legacy_core_sub": "[core.x]\n\tfsmonitor = true\n",
        "inline_section": "[core] fsmonitor = true\n",
        "mixed_case": "[CoRe]\n\tFsMonitor = true\n",
    }


@pytest.mark.parametrize("name", CFG_NAMES)
def test_manifest_config_not_allowed_exit_2_nothing_executed(tmp_path: Path, name: str):
    repo, sha = make_repo(tmp_path, "r", GOOD)
    with open(repo / ".git" / "config", "a") as f:
        f.write(_cfg_variants(tmp_path)[name])
    r = run(["manifest", "--repo", str(repo), "--commit", sha, "--out", str(tmp_path / "m.json")])
    assert_fail(r, 2)
    assert not (tmp_path / "MARKER").exists()
    assert not (tmp_path / "m.json").exists()


def test_config_values_never_printed(tmp_path: Path):
    repo, sha = make_repo(tmp_path, "r", GOOD)
    with open(repo / ".git" / "config", "a") as f:
        f.write(f"[url \"https://{DUMMY_SECRET}@example.invalid/\"]\n\tinsteadOf = a:\n[core]\n\tfsmonitor = {DUMMY_SECRET}\n")
    r = run(["manifest", "--repo", str(repo), "--commit", sha, "--out", str(tmp_path / "m.json")])
    assert r.returncode == 2 and DUMMY_SECRET not in r.stdout + r.stderr


def test_manifest_refs_replace_exit_2(w: World):
    other = g(w.tmp, w.src, "rev-parse", w.sha + ":a.txt")
    d = w.src / ".git" / "refs" / "replace"
    d.mkdir(parents=True)
    (d / other).write_text(other + "\n")
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(w.tmp / "meta" / "x.json")]), 2, "git-replace")


def test_manifest_packed_replace_exit_2(w: World):
    (w.src / ".git" / "packed-refs").write_text(f"# pack-refs\n{w.sha} refs/replace/{w.sha}\n")
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(w.tmp / "meta" / "x.json")]), 2, "git-replace")


@pytest.mark.parametrize("rel", ["objects/info/alternates", "objects/info/http-alternates", "info/grafts"])
def test_manifest_alternates_grafts_exit_2(w: World, rel: str):
    p = w.src / ".git" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("/tmp/x\n")
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(w.tmp / "meta" / "x.json")]), 2, "git-alternates")


def test_manifest_dotgit_file_or_symlink_exit_2(tmp_path: Path):
    repo, sha = make_repo(tmp_path, "r", GOOD)
    real = tmp_path / "r.git"
    (repo / ".git").rename(real)
    (repo / ".git").symlink_to(real)
    assert_fail(run(["manifest", "--repo", str(repo), "--commit", sha, "--out", str(tmp_path / "m.json")]), 2)
    (repo / ".git").unlink()
    (repo / ".git").write_text(f"gitdir: {real}\n")
    assert_fail(run(["manifest", "--repo", str(repo), "--commit", sha, "--out", str(tmp_path / "m.json")]), 2)


def test_manifest_info_attributes_filter_exit_2(w: World):
    p = w.src / ".git" / "info" / "attributes"
    p.parent.mkdir(exist_ok=True)
    p.write_text("* filter=evil\n")
    assert_fail(run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(w.tmp / "meta" / "x.json")]), 2, "git-attributes")


def test_manifest_hostile_caller_env_ignored(w: World):
    marker = w.tmp / "MARKER2"
    evil = w.tmp / "evil_git"
    evil.write_text(f"#!/bin/sh\ntouch {marker}\n")
    evil.chmod(0o755)
    env = {"GIT_DIR": str(w.tmp / "nonexistent"), "GIT_EXTERNAL_DIFF": str(evil), "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
           "GIT_CONFIG_VALUE_0": str(evil), "GIT_EXEC_PATH": str(w.tmp), "PYTHONPATH": str(w.tmp)}
    out = w.tmp / "meta" / "x.json"
    r = run(["manifest", "--repo", str(w.src), "--commit", w.sha, "--out", str(out)], env)
    assert r.returncode == 0 and not marker.exists()
    assert json.loads(out.read_text())["manifest_sha256"] == w.m()["manifest_sha256"]


# ---------------- verify: Positiv ----------------
def test_verify_positive(w: World):
    r = w.verify()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: OK" in r.stdout and "FAIL" not in r.stdout
    att = json.loads(r.stdout.split("ATTESTATION ", 1)[1].splitlines()[0])
    assert att["commit"] == w.sha and att["tree"] == w.m()["tree"] and att["manifest_sha256"] == w.m()["manifest_sha256"]
    assert att["env_check"] is False and att["findings"] == 0 and att["uid"] == os.geteuid()
    assert att["hostname_hash"] == hashlib.sha256(__import__("socket").gethostname().encode()).hexdigest()
    assert "Umgebung NICHT geprüft" in r.stdout


def test_verify_positive_with_env_check_clean(w: World):
    r = w.verify("--env-check", "--home", str(w.home))
    assert r.returncode == 0, r.stdout
    assert json.loads(r.stdout.split("ATTESTATION ", 1)[1])["env_check"] is True


def test_verify_without_key_only_warns(w: World):
    r = w.verify(key=False)
    assert r.returncode == 0 and "WARN manifest-mac" in r.stdout


def test_verify_head_from_packed_refs(w: World):
    g(w.tmp, w.co, "pack-refs", "--all")
    assert not (w.co / ".git" / "refs" / "heads" / "main").exists()  # git hat die lose Ref entfernt: Auflösung nur über packed-refs
    assert w.verify().returncode == 0


def test_verify_detached_head_ok_and_wrong(w: World):
    (w.co / ".git" / "HEAD").write_text(w.sha + "\n")
    assert w.verify().returncode == 0
    (w.co / ".git" / "HEAD").write_text("1" * 40 + "\n")
    assert_fail(w.verify(), 1, "FAIL git-head")


def test_verify_empty_extra_dir_only_warns(w: World):
    (w.co / "leer").mkdir()
    r = w.verify()
    assert r.returncode == 0 and "WARN worktree-emptydir" in r.stdout


# ---------------- verify: Manifest manipuliert ----------------
def test_verify_manifest_entries_changed(w: World):
    m = w.m()
    m["entries"][0][1] = "0" * 40
    w.write_m(m)
    assert_fail(w.verify(), 1, "manifest_sha256")


def test_verify_manifest_hash_wrong(w: World):
    m = w.m()
    m["manifest_sha256"] = "0" * 64
    w.write_m(m)
    assert_fail(w.verify(), 1, "FAIL manifest")


def test_verify_manifest_mac_wrong_or_missing(w: World):
    m = w.m()
    m["mac"] = "0" * 64
    w.write_m(m)
    assert_fail(w.verify(), 1, "manifest-mac")
    del m["mac"]
    w.write_m(m)
    assert_fail(w.verify(), 1, "manifest-mac")


def test_verify_manifest_rehashed_without_key_detected_by_mac(w: World):
    m = w.m()
    m["entries"][0][1] = "0" * 40
    m["manifest_sha256"] = RH.manifest_hash(m)
    w.write_m(m)
    assert_fail(w.verify(), 1, "manifest-mac")


def test_verify_manifest_wrong_key(w: World):
    other = keyfile(w.tmp, "other.key")
    other.write_text("cd" * 32 + "\n")
    r = run(["verify", "--manifest", str(w.manifest), "--checkout", str(w.co), "--mountinfo", str(w.mi), "--key-file", str(other)])
    assert_fail(r, 1, "manifest-mac")


def test_verify_manifest_malicious_entries_rehashed(w: World):
    m = w.m()
    m["entries"].append(["120000", "1" * 40, "zz-link"])
    m["entry_count"] = len(m["entries"])
    m["manifest_sha256"] = RH.manifest_hash(m)
    m["mac"] = RH.manifest_mac(m, KEY)  # Angreifer MIT Schlüssel: Einträge werden trotzdem semantisch abgelehnt
    w.write_m(m)
    assert_fail(w.verify(), 1, "unzulässig")


@pytest.mark.parametrize("mode", ["100664", "120000", "160000", "100600"])
def test_verify_manifest_odd_mode(w: World, mode: str):
    m = w.m()
    m["entries"][0][0] = mode
    m["manifest_sha256"] = RH.manifest_hash(m)
    m["mac"] = RH.manifest_mac(m, KEY)
    w.write_m(m)
    assert_fail(w.verify(), 1, "unzulässig")


def test_verify_manifest_garbage_exit_2(w: World):
    w.manifest.write_text("{kein json")
    assert_fail(w.verify(), 2)
    w.write_m({"version": 1})
    assert_fail(w.verify(), 2)


def test_verify_manifest_symlink_exit_2(w: World):
    ln = w.tmp / "meta" / "mln.json"
    ln.symlink_to(w.manifest)
    r = run(["verify", "--manifest", str(ln), "--checkout", str(w.co), "--mountinfo", str(w.mi)])
    assert r.returncode == 2


def test_verify_checkout_missing_or_symlink_exit_2(w: World):
    ln = w.tmp / "colink"
    ln.symlink_to(w.co)
    r = run(["verify", "--manifest", str(w.manifest), "--checkout", str(ln), "--mountinfo", str(w.mi)])
    assert r.returncode == 2
    r = run(["verify", "--manifest", str(w.manifest), "--checkout", str(w.tmp / "nix"), "--mountinfo", str(w.mi)])
    assert r.returncode == 2


# ---------------- verify: .git ----------------
@pytest.mark.parametrize("name", CFG_NAMES)
def test_verify_config_not_allowed_exit_1_nothing_executed(w: World, name: str):
    with open(w.co / ".git" / "config", "a") as f:
        f.write(_cfg_variants(w.tmp)[name])
    r = w.verify()
    assert_fail(r, 1, "FAIL git-config")
    assert not (w.tmp / "MARKER").exists()


def test_verify_config_values_never_printed(w: World):
    with open(w.co / ".git" / "config", "a") as f:
        f.write(f"[url \"https://{DUMMY_SECRET}@example.invalid/\"]\n\tinsteadOf = a:\n[core]\n\tfsmonitor = {DUMMY_SECRET}\n")
    r = w.verify()
    assert r.returncode == 1 and DUMMY_SECRET not in r.stdout + r.stderr


def test_verify_config_worktree_file(w: World):
    (w.co / ".git" / "config.worktree").write_text("[core]\n\tbare = false\n")
    assert_fail(w.verify(), 1, "FAIL git-config")


def test_verify_active_hook(w: World):
    h = w.co / ".git" / "hooks" / "post-checkout"
    h.write_text("#!/bin/sh\ntouch /nonexistent-dir/x\n")
    h.chmod(0o755)
    assert_fail(w.verify(), 1, "FAIL git-hooks")


def test_verify_refs_replace(w: World):
    d = w.co / ".git" / "refs" / "replace"
    d.mkdir(parents=True, exist_ok=True)
    (d / ("2" * 40)).write_text("3" * 40 + "\n")
    assert_fail(w.verify(), 1, "FAIL git-replace")


@pytest.mark.parametrize("rel", ["objects/info/alternates", "objects/info/http-alternates", "info/grafts"])
def test_verify_alternates_grafts(w: World, rel: str):
    p = w.co / ".git" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("/tmp/x\n")
    assert_fail(w.verify(), 1, "FAIL git-alternates")


@pytest.mark.parametrize("txt", ["* filter=x\n", "*.py diff=evil\n", "*.c merge=drv\n"])
def test_verify_info_attributes(w: World, txt: str):
    p = w.co / ".git" / "info" / "attributes"
    p.parent.mkdir(exist_ok=True)
    p.write_text(txt)
    assert_fail(w.verify(), 1, "FAIL git-attributes")


def test_verify_dotgit_symlink_or_file(w: World):
    real = w.tmp / "co.git"
    (w.co / ".git").rename(real)
    (w.co / ".git").symlink_to(real)
    assert_fail(w.verify(), 1, "FAIL git-dir")
    (w.co / ".git").unlink()
    (w.co / ".git").write_text(f"gitdir: {real}\n")
    assert_fail(w.verify(), 1, "FAIL git-dir")


# ---------------- verify: Arbeitsbaum ----------------
def test_verify_changed_file(w: World):
    (w.co / "a.txt").write_text("alpha!\n")
    assert_fail(w.verify(), 1, "FAIL worktree-content")


def test_verify_same_size_changed_file(w: World):
    (w.co / "a.txt").write_bytes(b"alphb\n")
    assert_fail(w.verify(), 1, "FAIL worktree-content")


def test_verify_extra_file_even_if_ignored(w: World):
    (w.co / "extra.log").write_text("x")  # laut .gitignore ignoriert: wird trotzdem gemeldet
    assert_fail(w.verify(), 1, "FAIL worktree-extra")


def test_verify_extra_nested_file(w: World):
    (w.co / "dir" / "tief").mkdir()
    (w.co / "dir" / "tief" / "x.py").write_text("x")
    assert_fail(w.verify(), 1, "FAIL worktree-extra")


def test_verify_nested_dotgit_is_extra(w: World):
    (w.co / "dir" / ".git").mkdir()
    (w.co / "dir" / ".git" / "HEAD").write_text("x")
    assert_fail(w.verify(), 1, "FAIL worktree-extra")


def test_verify_missing_file(w: World):
    (w.co / "a.txt").unlink()
    assert_fail(w.verify(), 1, "FAIL worktree-missing")


def test_verify_symlink_instead_of_file(w: World):
    (w.co / "a.txt").unlink()
    (w.co / "a.txt").symlink_to(w.co / ".gitignore")
    assert_fail(w.verify(), 1, "FAIL worktree-symlink")


def test_verify_extra_symlink_dangling(w: World):
    (w.co / "dangling").symlink_to("/nonexistent-target")
    assert_fail(w.verify(), 1, "FAIL worktree-symlink")


def test_verify_directory_symlink(w: World):
    moved = w.tmp / "moved"
    (w.co / "dir").rename(moved)
    (w.co / "dir").symlink_to(moved)
    r = w.verify()
    assert_fail(r, 1, "FAIL worktree-symlink")
    assert "FAIL worktree-missing" in r.stdout


def test_verify_fifo(w: World):
    os.mkfifo(w.co / "pipe")
    assert_fail(w.verify(), 1, "FAIL worktree-special")


def test_verify_fifo_instead_of_file_does_not_block(w: World):
    (w.co / "a.txt").unlink()
    os.mkfifo(w.co / "a.txt")
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), "verify", "--manifest", str(w.manifest), "--checkout", str(w.co), "--mountinfo", str(w.mi),
                        "--key-file", str(w.key)], env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "worktree-special" in r.stdout


def test_verify_hardlink(w: World):
    outside = w.tmp / "outside.txt"
    outside.write_bytes(b"alpha\n")
    (w.co / "a.txt").unlink()
    os.link(outside, w.co / "a.txt")
    assert_fail(w.verify(), 1, "FAIL worktree-hardlink")


def test_verify_exec_bit_wrong(w: World):
    (w.co / "dir" / "b.sh").chmod(0o644)
    assert_fail(w.verify(), 1, "FAIL worktree-mode")
    (w.co / "dir" / "b.sh").chmod(0o755)
    (w.co / "a.txt").chmod(0o755)
    assert_fail(w.verify(), 1, "FAIL worktree-mode")


# ---------------- verify: Mounts ----------------
def _mi(w: World, *lines: str) -> Path:
    p = w.tmp / "meta" / "mi2"
    p.write_text("25 1 8:1 / / rw - ext4 /dev/vda rw\n" + "\n".join(lines) + "\n")
    return p


@pytest.mark.parametrize("fstype", ["tmpfs", "overlay", "bind-ext4", "virtiofs", "9p", "nfs4", "fuse.sshfs"])
def test_verify_mount_below_checkout(w: World, fstype: str):
    real = os.path.realpath(w.co)
    r = w.verify(mi=_mi(w, f"40 25 0:40 / {real}/dir rw,relatime - {fstype} SECRETQUELLE rw"))
    assert_fail(r, 1, "FAIL mount-below")
    assert "fstype=" + fstype in r.stdout and "SECRETQUELLE" not in r.stdout


@pytest.mark.parametrize("line,why", [
    ("40 25 0:40 / {c} rw - virtiofs share rw", "Netz-/Shared"),
    ("40 25 0:41 / {c} rw - 9p share rw", "Netz-/Shared"),
    ("40 25 0:42 / {c} rw - fuse.x x rw", "Netz-/Shared"),
    ("40 25 0:43 / {c} rw - nfs4 srv:/x rw", "Netz-/Shared"),
    ("41 25 8:1 /srv/data {c} rw - ext4 /dev/vda rw", "Bind-Mount eines Unterverzeichnisses"),
    ("41 25 8:1 / {c} rw - ext4 /dev/vda rw", "Bind-Mount (gleiches Gerät"),
])
def test_verify_mount_at_checkout(w: World, line: str, why: str):
    real = os.path.realpath(w.co)
    r = w.verify(mi=_mi(w, line.format(c=real)))
    assert_fail(r, 1, "FAIL mount-at")
    assert why in r.stdout


def test_verify_checkout_inside_shared_fs(w: World):
    real = os.path.realpath(w.tmp)
    r = w.verify(mi=_mi(w, f"40 25 0:40 / {real} rw - virtiofs share rw"))
    assert_fail(r, 1, "FAIL mount-in")


def test_verify_own_mount_warns_and_escaped_path(w: World):
    real = os.path.realpath(w.co)
    r = w.verify(mi=_mi(w, f"40 25 0:50 / {real} rw - ext4 /dev/vdb rw", "41 25 0:51 / /mnt/with\\040space rw - tmpfs t rw"))
    assert r.returncode == 0 and "WARN mount-at" in r.stdout


def test_verify_mountinfo_unreadable_fails_closed(w: World):
    assert_fail(w.verify(mi=w.tmp / "nix"), 1, "FAIL mounts")


# ---------------- verify: Umgebung ----------------
def test_env_names_fail_values_never_printed(w: World):
    env = {"GITHUB_TOKEN": DUMMY_SECRET, "MY_API_KEY": DUMMY_SECRET + "2", "AWS_REGION": "x" + DUMMY_SECRET, "GH_HOST": DUMMY_SECRET, "SSH_AUTH_SOCK": "/s/" + DUMMY_SECRET,
           "ANTHROPIC_API_URL": DUMMY_SECRET, "CLAUDE_CODE_MESSAGING_X": DUMMY_SECRET, "SESSION_INGRESS_URL": DUMMY_SECRET, "DB_PASSWORD": DUMMY_SECRET,
           "TWINE_PYPI_X": DUMMY_SECRET, "CLOUDSDK_CORE": DUMMY_SECRET, "GOOGLE_APPLICATION_CREDENTIALS": DUMMY_SECRET, "AZURE_X": DUMMY_SECRET,
           "NPM_TOKEN": DUMMY_SECRET, "MY_PASSPHRASE": DUMMY_SECRET, "THE_PRIVATE_KEY": DUMMY_SECRET, "SOME_CREDENTIAL": DUMMY_SECRET, "X_SECRET": DUMMY_SECRET}
    r = w.verify("--env-check", "--home", str(w.home), env=env)
    assert_fail(r, 1, "FAIL env-names")
    out = r.stdout + r.stderr
    assert DUMMY_SECRET not in out
    for n in ("GITHUB_TOKEN", "MY_API_KEY", "AWS_REGION", "GH_HOST", "SSH_AUTH_SOCK", "DB_PASSWORD", "NPM_TOKEN"):
        assert n in out
    att = json.loads(r.stdout.split("ATTESTATION ", 1)[1])
    assert att["findings"] >= 1 and "RESULT: BLOCKED" in r.stdout


def test_env_harmless_names_pass(w: World):
    r = w.verify("--env-check", "--home", str(w.home), env={"LANG": "C", "EDITOR": "vi", "MY_VALUE": DUMMY_SECRET})
    assert r.returncode == 0 and DUMMY_SECRET not in r.stdout


def test_env_file_variable_existing_file(w: World):
    f = w.tmp / "dummy-secret-file"
    f.write_text(DUMMY_SECRET)
    f.chmod(0o640)
    r = w.verify("--env-check", "--home", str(w.home), env={"SOME_THING_FILE": str(f)})
    assert_fail(r, 1, "FAIL env-file")
    assert str(f) in r.stdout and "0640" in r.stdout and f"size={len(DUMMY_SECRET)}" in r.stdout and DUMMY_SECRET not in r.stdout


def test_env_file_variable_missing_file_ok(w: World):
    r = w.verify("--env-check", "--home", str(w.home), env={"SOME_THING_FILE": str(w.tmp / "gibt-es-nicht")})
    assert r.returncode == 0


def test_env_proxy_only_warns(w: World):
    r = w.verify("--env-check", "--home", str(w.home), env={"HTTPS_PROXY": "http://user:" + DUMMY_SECRET + "@proxy.invalid:1"})
    assert r.returncode == 0 and "WARN env-proxy" in r.stdout and DUMMY_SECRET not in r.stdout


def test_env_home_ssh_private_key(w: World):
    (w.home / ".ssh").mkdir()
    k = w.home / ".ssh" / "id_ed25519"
    k.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n" + DUMMY_SECRET + "\n-----END OPENSSH PRIVATE KEY-----\n")
    (w.home / ".ssh" / "known_hosts").write_text("x\n")
    (w.home / ".ssh" / "id_ed25519.pub").write_text("pub\n")
    r = w.verify("--env-check", "--home", str(w.home))
    assert_fail(r, 1, "FAIL home-ssh")
    assert "id_ed25519" in r.stdout and "known_hosts" not in r.stdout and DUMMY_SECRET not in r.stdout


def test_env_home_ssh_only_public_ok(w: World):
    (w.home / ".ssh").mkdir()
    (w.home / ".ssh" / "known_hosts").write_text("x\n")
    (w.home / ".ssh" / "id_rsa.pub").write_text("pub\n")
    assert w.verify("--env-check", "--home", str(w.home)).returncode == 0


def test_env_home_ssh_oddly_named_private_key(w: World):
    (w.home / ".ssh").mkdir()
    (w.home / ".ssh" / "deploy").write_text("-----BEGIN RSA PRIVATE KEY-----\nx\n")
    assert_fail(w.verify("--env-check", "--home", str(w.home)), 1, "FAIL home-ssh")


@pytest.mark.parametrize("rel,isdir", [(".git-credentials", False), (".netrc", False), (".pypirc", False), (".config/gh", True), (".aws", True),
                                       (".config/gcloud", True)])
def test_env_home_credential_files(w: World, rel: str, isdir: bool):
    p = w.home / rel
    if isdir:
        p.mkdir(parents=True)
        (p / "hosts.yml").write_text(DUMMY_SECRET)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("machine x password " + DUMMY_SECRET)
    r = w.verify("--env-check", "--home", str(w.home))
    assert_fail(r, 1, "FAIL home-cred")
    assert rel in r.stdout and DUMMY_SECRET not in r.stdout


def test_env_home_docker_auths(w: World):
    (w.home / ".docker").mkdir()
    (w.home / ".docker" / "config.json").write_text(json.dumps({"auths": {"registry.invalid": {"auth": DUMMY_SECRET}}}))
    r = w.verify("--env-check", "--home", str(w.home))
    assert_fail(r, 1, "FAIL home-docker")
    assert "auths" in r.stdout and DUMMY_SECRET not in r.stdout and "registry.invalid" not in r.stdout


def test_env_home_docker_without_auths_ok(w: World):
    (w.home / ".docker").mkdir()
    (w.home / ".docker" / "config.json").write_text(json.dumps({"auths": {}, "psFormat": "x"}))
    assert w.verify("--env-check", "--home", str(w.home)).returncode == 0


def test_env_home_npmrc_token(w: World):
    (w.home / ".npmrc").write_text("//registry.invalid/:_authToken=" + DUMMY_SECRET + "\n")
    r = w.verify("--env-check", "--home", str(w.home))
    assert_fail(r, 1, "FAIL home-npmrc")
    assert DUMMY_SECRET not in r.stdout


def test_env_home_gitconfig_credential_and_insteadof(w: World):
    (w.home / ".gitconfig").write_text(f"[user]\n\tname = x\n[credential \"https://h.invalid\"]\n\thelper = store\n"
                                       f"[url \"https://{DUMMY_SECRET}@h.invalid/\"]\n\tinsteadOf = h:\n[http]\n\textraHeader = Authorization: {DUMMY_SECRET}\n")
    r = w.verify("--env-check", "--home", str(w.home))
    assert_fail(r, 1, "FAIL home-gitconfig")
    assert "credential.*.helper" in r.stdout and "url.*.insteadof" in r.stdout and "http.extraheader" in r.stdout
    assert DUMMY_SECRET not in r.stdout and "h.invalid" not in r.stdout


def test_env_home_gitconfig_harmless_ok(w: World):
    (w.home / ".gitconfig").write_text("[user]\n\tname = x\n[core]\n\teditor = vi\n")
    assert w.verify("--env-check", "--home", str(w.home)).returncode == 0


# ---------------- check-report ----------------
def _att_line(r: subprocess.CompletedProcess) -> dict:
    return json.loads(r.stdout.split("ATTESTATION ", 1)[1].splitlines()[0])


class Rep:
    """Erwartung/Bericht/Plattform-Auszug als Dateien; Mutationen je Test."""

    def __init__(self, w: World):
        self.w = w
        r = w.verify("--env-check", "--home", str(w.home))
        assert r.returncode == 0, r.stdout
        att = _att_line(r)
        m = w.m()
        self.expect = {"commit": m["commit"], "tree": m["tree"], "manifest_sha256": m["manifest_sha256"], "environment_id": "env_dummy1",
                       "nonce": "n" * 32, "min_ts": "2020-01-01T00:00:00Z"}
        self.report = {"commit": m["commit"], "tree": m["tree"], "manifest_sha256": m["manifest_sha256"], "session_id": "session_dummy1",
                       "environment_id": "env_dummy1", "tools": ["Read", "Grep", "Glob"], "nonce": "n" * 32, "attestation": att, "findings": []}
        self.session = {"id": "session_dummy1", "environment_id": "env_dummy1", "parent": None, "status": "idle",
                        "sources": [{"git_repository": {"url": "https://example.invalid/r.git", "revision": m["commit"]}}]}

    def run(self, *extra: str, session: bool = True) -> subprocess.CompletedProcess:
        d = self.w.tmp / "rep"
        d.mkdir(exist_ok=True)
        for n, v in (("expect", self.expect), ("report", self.report), ("session", self.session)):
            (d / f"{n}.json").write_text(json.dumps(v))
        a = ["check-report", "--expect", str(d / "expect.json"), "--report", str(d / "report.json")]
        if session:
            a += ["--session", str(d / "session.json")]
        return run(a + list(extra))


@pytest.fixture()
def rp(w: World) -> Rep:
    return Rep(w)


def test_check_report_positive(rp: Rep):
    r = rp.run()
    assert r.returncode == 0 and "RESULT: OK" in r.stdout, r.stdout + r.stderr


def test_check_report_markdown_json_block(rp: Rep):
    d = rp.w.tmp / "rep"
    rp.run()
    (d / "report.json").write_text("Bericht\n```json\n" + json.dumps(rp.report) + "\n```\nEnde\n")
    r = run(["check-report", "--expect", str(d / "expect.json"), "--report", str(d / "report.json"), "--session", str(d / "session.json")])
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_report_no_session_fails_unless_allowed(rp: Rep):
    assert_fail(rp.run(session=False), 1, "FAIL session")
    r = rp.run("--allow-no-session", session=False)
    assert r.returncode == 0 and "WARN session" in r.stdout


@pytest.mark.parametrize("field,val", [
    ("commit", "1" * 40), ("commit", "abc1234"), ("tree", "2" * 40), ("manifest_sha256", "0" * 64), ("nonce", "x" * 32), ("environment_id", "env_other"),
])
def test_check_report_report_value_wrong(rp: Rep, field: str, val: str):
    rp.report[field] = val
    assert_fail(rp.run(), 1, "FAIL")


def test_check_report_session_id_differs(rp: Rep):
    rp.session["id"] = "session_andere"
    assert_fail(rp.run(), 1, "FAIL session-id")


def test_check_report_platform_environment_differs(rp: Rep):
    rp.session["environment_id"] = "env_andere"
    r = rp.run()
    assert_fail(r, 1, "FAIL session-env")


def test_check_report_expected_environment_differs(rp: Rep):
    rp.expect["environment_id"] = "env_andere"
    assert_fail(rp.run(), 1, "FAIL environment")


def test_check_report_revision_differs_or_short(rp: Rep):
    rp.session["sources"][0]["git_repository"]["revision"] = "9" * 40
    assert_fail(rp.run(), 1, "FAIL session-revision")
    rp.session["sources"][0]["git_repository"]["revision"] = rp.expect["commit"][:12]
    assert_fail(rp.run(), 1, "FAIL session-revision")
    rp.session["sources"][0]["git_repository"]["revision"] = "main"
    assert_fail(rp.run(), 1, "FAIL session-revision")


@pytest.mark.parametrize("tools", [["Read", "Grep", "Glob", "Bash"], ["Read", "Write"], ["Read", "mcp__github__create_pull_request"],
                                   ["Read", "Edit"], ["Read", "mcp__x__y"], ["Grep", "Glob", "NotebookEdit"], []])
def test_check_report_tools_not_allowed(rp: Rep, tools: list[str]):
    rp.report["tools"] = tools
    assert_fail(rp.run(), 1, "FAIL tools")


def test_check_report_tools_subset_ok_and_custom_allowlist(rp: Rep):
    rp.report["tools"] = ["Read"]
    assert rp.run().returncode == 0
    rp.report["tools"] = ["Read", "Bash"]
    assert rp.run("--allowed-tools", "Read,Bash").returncode == 0
    rp.report["tools"] = "Read"
    assert_fail(rp.run(), 1, "FAIL tools")


def test_check_report_attestation_env_check_not_true(rp: Rep):
    for v in (False, "true", 1):
        rp.report["attestation"]["env_check"] = v
        assert_fail(rp.run(), 1, "FAIL att-env")


def test_check_report_attestation_findings(rp: Rep):
    for v in (1, "0", False):
        rp.report["attestation"]["findings"] = v
        assert_fail(rp.run(), 1, "FAIL att-findings")
    rp.report["attestation"]["findings"] = None
    assert_fail(rp.run(), 2, "findings")
    rp.report["attestation"]["findings"] = 3
    assert_fail(rp.run(), 1, "FAIL att-findings")


def test_check_report_attestation_commit_mismatch(rp: Rep):
    rp.report["attestation"]["commit"] = "4" * 40
    assert_fail(rp.run(), 1, "FAIL att-commit")
    rp.report["attestation"]["commit"] = rp.expect["commit"]
    del rp.report["attestation"]["manifest_sha256"]
    assert_fail(rp.run(), 1, "FAIL att-manifest_sha256")


def test_check_report_too_old(rp: Rep):
    rp.expect["min_ts"] = "2999-01-01T00:00:00Z"
    assert_fail(rp.run(), 1, "FAIL att-time")


def test_check_report_bad_timestamp(rp: Rep):
    rp.report["attestation"]["checked_at"] = "gestern"
    assert_fail(rp.run(), 1, "FAIL att-time")
    rp.report["attestation"]["checked_at"] = rp.w.verify("--env-check", "--home", str(rp.w.home)).stdout.split('"checked_at": "')[1][:20]
    rp.expect["min_ts"] = "nicht-zeit"
    assert_fail(rp.run(), 2)


@pytest.mark.parametrize("field", ["commit", "tree", "manifest_sha256", "session_id", "environment_id", "tools", "nonce", "attestation", "findings"])
def test_check_report_missing_report_field_exit_2(rp: Rep, field: str):
    del rp.report[field]
    assert_fail(rp.run(), 2, field)


@pytest.mark.parametrize("field", ["commit", "tree", "manifest_sha256", "environment_id", "nonce", "min_ts"])
def test_check_report_missing_expect_field_exit_2(rp: Rep, field: str):
    del rp.expect[field]
    assert_fail(rp.run(), 2, field)


@pytest.mark.parametrize("field", ["env_check", "findings", "checked_at"])
def test_check_report_missing_attestation_field_exit_2(rp: Rep, field: str):
    del rp.report["attestation"][field]
    assert_fail(rp.run(), 2, field)


def test_check_report_missing_session_fields_exit_2(rp: Rep):
    del rp.session["sources"]
    assert_fail(rp.run(), 2)
    rp.session["sources"] = [{}]
    assert_fail(rp.run(), 2)


def test_check_report_empty_values_exit_2(rp: Rep):
    rp.report["nonce"] = ""
    assert_fail(rp.run(), 2)


def test_check_report_unreadable_inputs_exit_2(rp: Rep):
    rp.run()
    r = run(["check-report", "--expect", str(rp.w.tmp / "nix"), "--report", str(rp.w.tmp / "rep" / "report.json")])
    assert r.returncode == 2
    (rp.w.tmp / "rep" / "report.json").write_text("kein json")
    r = run(["check-report", "--expect", str(rp.w.tmp / "rep" / "expect.json"), "--report", str(rp.w.tmp / "rep" / "report.json")])
    assert r.returncode == 2


def test_end_to_end_tampered_checkout_blocks_report(w: World):
    (w.co / "a.txt").write_text("manipuliert\n")
    r = w.verify("--env-check", "--home", str(w.home))
    assert r.returncode == 1
    att = _att_line(r)
    assert att["findings"] >= 1
    rp = Rep.__new__(Rep)
    rp.w = w
    m = w.m()
    rp.expect = {"commit": m["commit"], "tree": m["tree"], "manifest_sha256": m["manifest_sha256"], "environment_id": "e", "nonce": "n" * 32,
                 "min_ts": "2020-01-01T00:00:00Z"}
    rp.report = {"commit": m["commit"], "tree": m["tree"], "manifest_sha256": m["manifest_sha256"], "session_id": "s", "environment_id": "e",
                 "tools": ["Read"], "nonce": "n" * 32, "attestation": att, "findings": []}
    rp.session = {"id": "s", "environment_id": "e", "status": "idle", "sources": [{"git_repository": {"revision": m["commit"]}}]}
    assert_fail(rp.run(), 1, "FAIL att-findings")


# ---------------- remote-check ----------------
def _bare_remote(w: World) -> Path:
    bare = w.tmp / "remote.git"
    g(w.tmp, w.tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    g(w.tmp, w.src, "push", "-q", str(bare), "HEAD:refs/heads/main")
    return bare


def _rc(w: World, bare: Path, *extra: str, commit: str | None = None, ref: str = "refs/heads/main") -> subprocess.CompletedProcess:
    return run(["remote-check", "--repo", str(w.src), "--commit", commit or w.sha, "--ref", ref, "--url", f"file://{bare}", *extra])


def test_remote_check_exact(w: World):
    r = _rc(w, _bare_remote(w), "--allow-protocol", "file")
    assert r.returncode == 0 and "PASS remote-ref" in r.stdout, r.stdout + r.stderr


def test_remote_check_url_from_repo_config(w: World):
    bare = _bare_remote(w)
    g(w.tmp, w.src, "remote", "add", "origin", f"file://{bare}")
    r = run(["remote-check", "--repo", str(w.src), "--commit", w.sha, "--ref", "refs/heads/main", "--allow-protocol", "file"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_remote_check_default_protocol_https_rejects_file_url(w: World):
    assert_fail(_rc(w, _bare_remote(w)), 2)


def test_remote_check_forward_with_local_tip_warns(w: World):
    bare = _bare_remote(w)
    (w.src / "neu.txt").write_text("n")
    g(w.tmp, w.src, "add", "-A")
    g(w.tmp, w.src, "commit", "-q", "-m", "zwei")
    g(w.tmp, w.src, "push", "-q", str(bare), "HEAD:refs/heads/main")
    r = _rc(w, bare, "--allow-protocol", "file")
    assert r.returncode == 0 and "WARN remote-ref" in r.stdout and "Vorfahre" in r.stdout, r.stdout + r.stderr


def test_remote_check_tip_not_local_fails(w: World):
    bare = _bare_remote(w)
    other = w.tmp / "other"
    g(w.tmp, w.tmp, "clone", "-q", str(bare), str(other))
    (other / "x.txt").write_text("x")
    g(w.tmp, other, "add", "-A")
    g(w.tmp, other, "commit", "-q", "-m", "fremd")
    g(w.tmp, other, "push", "-q", "origin", "HEAD:refs/heads/main")
    r = _rc(w, bare, "--allow-protocol", "file")
    assert_fail(r, 1, "nicht belegbar")


def test_remote_check_commit_not_ancestor_fails(w: World):
    bare = _bare_remote(w)
    g(w.tmp, w.src, "checkout", "-q", "--orphan", "fremd")
    (w.src / "z.txt").write_text("z")
    g(w.tmp, w.src, "add", "-A")
    g(w.tmp, w.src, "commit", "-q", "-m", "orphan")
    g(w.tmp, w.src, "push", "-q", "-f", str(bare), "HEAD:refs/heads/main")
    r = _rc(w, bare, "--allow-protocol", "file")
    assert_fail(r, 1, "kein Vorfahre")


def test_remote_check_ref_missing_or_remote_unreachable(w: World):
    bare = _bare_remote(w)
    assert_fail(_rc(w, bare, "--allow-protocol", "file", ref="refs/heads/gibtsnicht"), 1, "FAIL remote-ref")
    assert_fail(run(["remote-check", "--repo", str(w.src), "--commit", w.sha, "--ref", "refs/heads/main", "--url", f"file://{w.tmp}/nix.git",
                     "--allow-protocol", "file"]), 1, "FAIL remote")


def test_remote_check_input_validation(w: World):
    bare = _bare_remote(w)
    assert_fail(_rc(w, bare, "--allow-protocol", "file", commit=w.sha[:10]), 2)
    assert_fail(_rc(w, bare, "--allow-protocol", "file", ref="main"), 2)
    assert_fail(_rc(w, bare, "--allow-protocol", "file", ref="refs/heads/../x"), 2)
    for url in ("--upload-pack=touch /tmp/x", "ext::sh -c id", "file:///x y", "-oProxyCommand=x"):
        r = run(["remote-check", "--repo", str(w.src), "--commit", w.sha, "--ref", "refs/heads/main", "--url", url, "--allow-protocol", "file"])
        assert r.returncode == 2, (url, r.stdout, r.stderr)


def test_remote_check_does_not_write_remote(w: World):
    bare = _bare_remote(w)

    def snap() -> dict:
        return {str(p.relative_to(bare)): p.stat().st_mtime_ns for p in bare.rglob("*") if p.is_file()}

    before = snap()
    assert _rc(w, bare, "--allow-protocol", "file").returncode == 0
    assert snap() == before


def test_remote_check_bad_local_config_exit_2(w: World):
    bare = _bare_remote(w)
    with open(w.src / ".git" / "config", "a") as f:
        f.write(f"[core]\n\tfsmonitor = {w.tmp}/evil\n")
    assert_fail(_rc(w, bare, "--allow-protocol", "file"), 2)
