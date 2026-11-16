"""Tests für scripts/check_file_set.py (Dateimengen-Kontrolle). Reine Funktionstests ohne Repo-Schreibzugriff (nur Funktionen/Arbeitskopie im tmp)."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("check_file_set", Path(__file__).resolve().parents[2] / "scripts" / "check_file_set.py")
cfs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cfs)


def test_match_globs_and_directory_prefix():
    assert cfs.match("backend/leventum/services/x.py", ["backend/leventum/services/*.py"])
    assert not cfs.match("backend/leventum/api/x.py", ["backend/leventum/services/*.py"])
    assert cfs.match("docs/a/b.md", ["docs/"])
    assert not cfs.match("docsx/a.md", ["docs/"])
    assert cfs.match("scripts/x.py", ["scripts/x.py"])


def test_violations_detect_new_changed_and_reverted_files():
    before = {"a.py": "h1", "b.py": "h2"}
    now = {"a.py": "h1", "b.py": "CHANGED", "c.py": "new"}
    assert cfs.violations(before, now, ["b.py"]) == ["c.py"]                  # b erlaubt, c neu & nicht erlaubt, a unverändert
    assert cfs.violations(before, now, ["*.py"]) == []
    assert cfs.violations({"a.py": "h1"}, {}, ["x"]) == ["a.py"]               # vorher dirty, jetzt zurückgesetzt = Änderung außerhalb → melden


def test_overlaps_between_agent_file_sets():
    sets = {"backend": ["backend/leventum/api/*.py", "docs/03.md"], "frontend": ["frontend/src/*"], "docs": ["docs/03.md"]}
    universe = ["backend/leventum/api/a.py", "frontend/src/x.tsx", "docs/03.md"]
    res = cfs.overlaps(sets, universe)
    assert any("backend ∩ docs" in r for r in res) and not any("frontend" in r for r in res)
    assert cfs.overlaps({"a": ["x/*.py"], "b": ["y/*.py"]}, ["x/1.py", "y/1.py"]) == []
    assert cfs.overlaps({"a": ["neu.py"], "b": ["neu.py"]}, []) == ["a ∩ b: identisches Muster neu.py"]  # noch nicht existierende Datei, gleiches Muster


# --- Glob-Matcher -------------------------------------------------------------------------------------------
import contextlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize("path,pat,expected", [
    ("a/b/c.py", "a/*.py", False),             # * matcht nicht über /
    ("a/c.py", "a/*.py", True),
    ("a/b/c.py", "a/**/*.py", True),           # ** über mehrere Ebenen
    ("a/c.py", "a/**/*.py", True),             # ** auch null Ebenen
    ("a/b/c/d.py", "a/**", True),
    ("a/b/c.py", "a/?/c.py", True),
    ("a/bb/c.py", "a/?/c.py", False),
    ("a//c.py", "a/?/c.py", False),            # ? matcht nicht /
    ("a/b/c.py", "a?b/c.py", False),
    ("a/x1.py", "a/x[0-9].py", True),
    ("a/xa.py", "a/x[!0-9].py", True),
    ("a/x/.py", "a/x[/]*.py", False),
    ("docs/a/b.md", "docs/", True),
    ("docsx/a.md", "docs/", False),
    ("a.b", "a.b", True),
    ("axb", "a.b", False),                     # Punkt ist wörtlich
])
def test_glob_boundaries(path, pat, expected):
    assert cfs.match(path, [pat]) is expected


def test_overlap_star_does_not_cross_slash():
    universe = ["src/a/x.py", "src/x.py"]
    assert cfs.overlaps({"a": ["src/*.py"], "b": ["src/a/*.py"]}, universe) == []
    assert cfs.overlaps({"a": ["src/**/*.py"], "b": ["src/a/*.py"]}, universe) != []


# --- Temporäres git-Repo ------------------------------------------------------------------------------------
@pytest.fixture()
def repo(tmp_path, monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                 "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(k, v)
    r = tmp_path / "repo"
    r.mkdir()
    g(r, "init", "-q")
    (r / ".gitignore").write_text("secret.env\n*.pyc\nnode_modules/\n.venv/\n__pycache__/\ndist/\n")
    (r / "a.txt").write_text("a\n")
    (r / "old.txt").write_text("a long enough file to be detected as rename\n" * 5)
    (r / "tool.sh").write_text("#!/bin/sh\n")
    os.symlink("a.txt", r / "link")
    g(r, "add", "-A")
    g(r, "commit", "-q", "-m", "init")
    return r


def g(r, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=r, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _clean_key(monkeypatch):
    monkeypatch.delenv("CFS_SNAPSHOT_KEY", raising=False)
    yield
    os.environ.pop("CFS_SNAPSHOT_KEY", None)


def snap(r, tmp_path, name="snap.json"):
    """Snapshot AUSSERHALB des Repos (tmp_path/<name>); Schlüssel (stdout KEY=...) landet in CFS_SNAPSHOT_KEY."""
    out = tmp_path / name
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cfs.main(["snapshot", "--repo", str(r), "--out", str(out)])
    assert rc == 0
    m = re.search(r"^KEY=([0-9a-f]{64})$", buf.getvalue(), re.M)
    assert m, buf.getvalue()
    os.environ["CFS_SNAPSHOT_KEY"] = m.group(1)
    return out


def chk(r, snapfile, *allowed):
    args = ["check", "--repo", str(r), "--snapshot", str(snapfile)]
    for a in allowed:
        args += ["--allowed", a]
    return cfs.main(args)


def test_exit_codes_ok_and_violation(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    assert chk(repo, s, "ok/") == 0                              # nichts geändert
    (repo / "ok").mkdir()
    (repo / "ok" / "n.txt").write_text("x")
    assert chk(repo, s, "ok/") == 0                              # erlaubt
    (repo / "bad.txt").write_text("x")
    capsys.readouterr()
    assert chk(repo, s, "ok/") == 1
    assert "bad.txt" in capsys.readouterr().out


def test_committed_change_after_snapshot_is_detected(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    (repo / "a.txt").write_text("changed\n")
    g(repo, "commit", "-qam", "c")                               # Arbeitsbaum jetzt sauber, Änderung nur im Commit
    assert g(repo, "status", "--porcelain") == ""
    assert chk(repo, s, "other.txt") == 1
    assert "a.txt" in capsys.readouterr().out
    assert chk(repo, s, "a.txt") == 0


def test_committed_deletion_is_detected(repo, tmp_path):
    s = snap(repo, tmp_path)
    g(repo, "rm", "-q", "a.txt")
    g(repo, "commit", "-qm", "rm")
    assert chk(repo, s, "zzz") == 1
    assert chk(repo, s, "a.txt") == 0


def test_dirty_file_committed_unchanged_is_not_a_violation(repo, tmp_path):
    (repo / "a.txt").write_text("dirty at snapshot\n")
    s = snap(repo, tmp_path)
    g(repo, "commit", "-qam", "same content")
    assert chk(repo, s, "nothing") == 0


def test_rename_reports_old_and_new_path(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    g(repo, "mv", "old.txt", "new.txt")                          # staged Umbenennung (status R)
    capsys.readouterr()
    assert chk(repo, s, "new.txt") == 1                          # alter Pfad nicht erlaubt
    assert "old.txt" in capsys.readouterr().out
    assert chk(repo, s, "old.txt") == 1                          # neuer Pfad nicht erlaubt
    assert "new.txt" in capsys.readouterr().out
    assert chk(repo, s, "old.txt", "new.txt") == 0


def test_committed_rename_reports_both_paths(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    g(repo, "mv", "old.txt", "new.txt")
    g(repo, "commit", "-qm", "mv")
    capsys.readouterr()
    assert chk(repo, s, "new.txt") == 1 and "old.txt" in capsys.readouterr().out
    assert chk(repo, s, "old.txt") == 1 and "new.txt" in capsys.readouterr().out
    assert chk(repo, s, "old.txt", "new.txt") == 0


def test_symlink_target_change_and_broken_link(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    (repo / "link").unlink()
    os.symlink("does-not-exist", repo / "link")                  # kaputter Link, anderes Ziel
    capsys.readouterr()
    assert chk(repo, s, "x") == 1 and "link" in capsys.readouterr().out
    assert chk(repo, s, "link") == 0
    assert cfs.fingerprint(repo, "link") == "symlink:does-not-exist"   # nicht „gelöscht“
    (repo / "adir").mkdir()
    os.symlink("adir", repo / "dirlink")
    assert cfs.fingerprint(repo, "dirlink") == "symlink:adir"
    assert cfs.fingerprint(repo, "nichts") == cfs.GONE


def test_symlink_replaced_by_file_with_same_content_is_change(repo, tmp_path):
    s = snap(repo, tmp_path)
    (repo / "link").unlink()
    (repo / "link").write_text("a\n")
    assert chk(repo, s, "x") == 1


def test_exec_bit_change_is_detected(repo, tmp_path):
    s = snap(repo, tmp_path)
    os.chmod(repo / "tool.sh", 0o755)
    assert g(repo, "status", "--porcelain").startswith("M")
    assert chk(repo, s, "other") == 1
    assert chk(repo, s, "tool.sh") == 0
    assert cfs.fingerprint(repo, "tool.sh").startswith("file:x:")


def test_ignored_file_is_tracked_but_noise_is_excluded(repo, tmp_path, capsys):
    (repo / "secret.env").write_text("v1")
    s = snap(repo, tmp_path)
    assert "secret.env" in json.loads(s.read_text())["files"]
    assert chk(repo, s, "none") == 0
    (repo / "secret.env").write_text("v2")
    capsys.readouterr()
    assert chk(repo, s, "none") == 1 and "secret.env" in capsys.readouterr().out
    (repo / "secret.env").write_text("v1")
    # Rauschen (nicht skriptartig): darf weder Verstoß erzeugen noch im Snapshot stehen
    for rel in ("node_modules/x/y.json", ".venv/lib/z.txt", "pkg/__pycache__/m.dat", "dist/bundle.map"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("noise")
    assert chk(repo, s, "none") == 0
    assert set(cfs.dirty_files(repo)) == {"secret.env"}


def test_is_script_list():
    for p in ("a/x.py", ".venv/lib/x.pth", "x/__pycache__/m.pyc", "node_modules/a.js", "x.sh", "lib/x.so", "A.PY"):
        assert cfs.is_script(p), p
    for p in ("a.txt", "x.json", "x.pyx.map"):
        assert not cfs.is_script(p), p


def test_is_noise_list():
    for p in ("node_modules/a.js", "frontend/node_modules/.vite/x", ".venv/bin/python", "a/__pycache__/m.cpython-312.pyc", "x.pyc", ".pytest_cache/v/x",
              "frontend/dist/index.html", "build/lib/x.py", "pkg.egg-info/PKG-INFO", ".coverage"):
        assert cfs.is_noise(p), p
    for p in ("backend/data/leventum.db", "secret.env", "docs/dist.md", "src/build.py"):
        assert not cfs.is_noise(p), p


def test_operating_errors_exit_2(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    assert cfs.main(["check", "--repo", str(repo), "--snapshot", str(s)]) == 2                      # --allowed fehlt
    assert "--allowed" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{kaputt")
    assert chk(repo, bad, "x") == 2                                                                  # Snapshot kein JSON
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"a.py": "h"}))
    assert chk(repo, old, "x") == 2                                                                  # altes/ungültiges Format
    assert chk(repo, tmp_path / "fehlt.json", "x") == 2                                              # Datei fehlt
    unknown = tmp_path / "unk.json"
    data = {"version": cfs.SNAPSHOT_VERSION, "head": "0123456789abcdef0123456789abcdef01234567", "files": {}, "flags": {}, "gitmeta": {}}
    data["mac"] = cfs.sign(data, os.environ["CFS_SNAPSHOT_KEY"])                                     # gültiger MAC, aber unbekannter HEAD
    unknown.write_text(json.dumps(data))
    capsys.readouterr()
    assert chk(repo, unknown, "x") == 2
    assert "existiert nicht mehr" in capsys.readouterr().err
    assert cfs.main(["overlap", "--repo", str(repo), "--set", "kaputt"]) == 2
    assert cfs.main(["snapshot", "--repo", str(tmp_path / "nirgends"), "--out", str(tmp_path / "o.json")]) == 2
    plain = tmp_path / "plain"
    plain.mkdir()
    assert cfs.main(["snapshot", "--repo", str(plain), "--out", str(tmp_path / "o.json")]) == 2    # kein git-Repo


def test_head_reset_or_switch_is_error_not_violation(repo, tmp_path, capsys):
    base = g(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("2\n")
    g(repo, "commit", "-qam", "second")
    s = snap(repo, tmp_path)                                                                          # Snapshot auf „second“
    g(repo, "reset", "-q", "--hard", base)                                                            # HEAD zurückgesetzt
    capsys.readouterr()
    assert chk(repo, s, "a.txt") == 2
    assert "Vorfahre" in capsys.readouterr().err


def test_non_utf8_path_and_unreadable_file(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    raw = os.fsencode(str(repo)) + b"/bad-\xff.txt"
    with open(raw, "wb") as f:
        f.write(b"x")
    assert chk(repo, s, "ok") == 1                                                                    # Verstoß, kein Absturz
    assert "bad-" in capsys.readouterr().out
    assert chk(repo, s, "bad-*.txt") == 0
    if os.geteuid() != 0:                                                                             # unlesbar nur ohne root prüfbar
        (repo / "locked.txt").write_text("x")
        os.chmod(repo / "locked.txt", 0)
        assert chk(repo, s, "locked.txt") == 2


def test_overlap_cli(repo, tmp_path):
    (repo / "sub").mkdir()
    (repo / "sub" / "b.txt").write_text("x")
    assert cfs.main(["overlap", "--repo", str(repo), "--set", "A=*.txt", "--set", "B=sub/b.txt"]) == 0    # * matcht nicht über /
    assert cfs.main(["overlap", "--repo", str(repo), "--set", "A=**/*.txt", "--set", "B=sub/b.txt"]) == 1  # ** schon
    assert cfs.main(["overlap", "--repo", str(repo), "--set", "A=*.txt", "--set", "B=a.txt"]) == 1


# === Härtung (Security-Audit): kontrollierter git-Aufruf, Konfigurationsprüfung, .git-Integrität, Index-Flags, MAC, Muster ==============
def evil(tmp_path):
    """Harmlose Attrappe: legt nur eine Marker-Datei in tmp_path an. Existiert der Marker, wurde etwas ausgeführt."""
    marker = tmp_path / "MARKER"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\ncat\n")
    os.chmod(script, 0o755)
    return script, marker


def cfg(r, *args):
    g(r, "config", *args)


def run(r, tmp_path, *allowed, name="snap.json"):
    return cfs.main(["snapshot", "--repo", str(r), "--out", str(tmp_path / name)])


EVIL_CONFIGS = [
    ("core.fsmonitor", "{s}"), ("core.hooksPath", "{d}"), ("core.pager", "{s}"), ("core.sshCommand", "{s}"), ("core.editor", "{s}"),
    ("core.gitProxy", "{s}"), ("alias.st", "!{s}"), ("diff.external", "{s}"), ("filter.x.clean", "{s}"), ("filter.x.smudge", "{s}"),
    ("merge.m.driver", "{s} %A"), ("credential.helper", "!{s}"), ("url.file:///x.insteadOf", "y"), ("protocol.ext.allow", "always"),
    ("uploadpack.packObjectsHook", "{s}"), ("http.proxy", "http://u:geheim@x.invalid"), ("gpg.program", "{s}"),
    ("submodule.sm.update", "!{s}"), ("trace2.eventTarget", "{d}/t"), ("include.path", "{d}/extra.cfg"),
    ("includeIf.gitdir:/x/.path", "{d}/extra.cfg"), ("core.worktree", "{d}"), ("diff.x.textconv", "{s}"), ("core.sparsecheckout", "true"),
]


@pytest.mark.parametrize("key,val", EVIL_CONFIGS)
def test_unsafe_config_is_rejected_without_executing_anything(repo, tmp_path, capsys, key, val):
    script, marker = evil(tmp_path)
    s = snap(repo, tmp_path)                                                                          # Snapshot VOR der bösen Konfiguration
    cfg(repo, key, val.format(s=script, d=tmp_path))
    (repo / ".gitattributes").write_text("*.txt filter=x\n")
    (repo / "a.txt").write_text("changed\n")
    capsys.readouterr()
    assert chk(repo, s, "a.txt", ".gitattributes") == 2
    err = capsys.readouterr().err
    assert key.split(".")[0].lower() in err.lower() and "geheim" not in err and str(script) not in err      # Schlüsselname, nie Werte
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(tmp_path / "s2.json")]) == 2
    assert cfs.main(["overlap", "--repo", str(repo), "--set", "A=a.txt", "--set", "B=b.txt"]) == 2
    assert not marker.exists()                                                                        # Beweis: nichts wurde ausgeführt
    assert not (tmp_path / "s2.json").exists()


def test_ext_remote_url_and_worktree_config_and_git_file_rejected(repo, tmp_path):
    script, marker = evil(tmp_path)
    cfg(repo, "remote.o.url", f"ext::{script}")
    assert run(repo, tmp_path) == 2
    cfg(repo, "--unset", "remote.o.url")
    (repo / ".git" / "config.worktree").write_text("[core]\n\tfsmonitor = " + str(script) + "\n")
    assert run(repo, tmp_path) == 2
    (repo / ".git" / "config.worktree").unlink()
    cfg(repo, "extensions.worktreeConfig", "true")
    assert run(repo, tmp_path) == 2
    assert not marker.exists()
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {repo}/.git\n")                                                # .git als Datei (Worktree) -> ablehnen
    assert cfs.main(["snapshot", "--repo", str(wt), "--out", str(tmp_path / "w.json")]) == 2
    sl = tmp_path / "sl"
    sl.mkdir()
    os.symlink(repo / ".git", sl / ".git")                                                            # .git als Symlink -> ablehnen
    assert cfs.main(["snapshot", "--repo", str(sl), "--out", str(tmp_path / "w.json")]) == 2


def test_harmless_config_is_accepted(repo, tmp_path):
    cfg(repo, "remote.origin.url", "https://example.invalid/x.git")
    cfg(repo, "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    cfg(repo, "branch.main.remote", "origin")
    cfg(repo, "branch.main.merge", "refs/heads/main")
    cfg(repo, "user.name", "Erfunden")
    cfg(repo, "gc.auto", "0")
    cfg(repo, "pack.threads", "1")
    cfg(repo, "init.defaultBranch", "main")
    s = snap(repo, tmp_path)
    assert chk(repo, s, "none") == 0


def test_gitattributes_filter_in_worktree_is_harmless_without_filter_config(repo, tmp_path):
    (repo / ".gitattributes").write_text("*.txt filter=x\n")
    s = snap(repo, tmp_path)
    (repo / "a.txt").write_text("neu\n")
    assert chk(repo, s, "a.txt", ".gitattributes") == 0


def test_info_attributes_filter_rejected_and_harmless_accepted(repo, tmp_path):
    script, marker = evil(tmp_path)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    attr = repo / ".git" / "info" / "attributes"
    for line in ("*.txt filter=x\n", "*.txt diff=x\n", "*.txt merge=x\n"):
        attr.write_text(line)
        assert run(repo, tmp_path) == 2
    attr.write_text("# filter=x im Kommentar\n*.txt text\n")
    assert run(repo, tmp_path) == 0
    assert not marker.exists()


def test_caller_git_environment_is_ignored(repo, tmp_path, monkeypatch):
    script, marker = evil(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    g(other, "init", "-q")
    (other / "fremd.txt").write_text("x")
    (repo / "mine.txt").write_text("x")
    for k, v in {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other), "GIT_INDEX_FILE": str(other / "idx"),
                 "GIT_EXTERNAL_DIFF": str(script), "GIT_PAGER": str(script), "GIT_EDITOR": str(script), "GIT_SSH_COMMAND": str(script),
                 "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": str(script),
                 "GIT_CONFIG_GLOBAL": str(tmp_path / "gc"), "PATH": "/nonexistent"}.items():
        monkeypatch.setenv(k, v)
    (tmp_path / "gc").write_text(f"[core]\n\tfsmonitor = {script}\n")
    s = snap(repo, tmp_path)
    files = json.loads(s.read_text())["files"]
    assert "mine.txt" in files and "fremd.txt" not in files
    (repo / "a.txt").write_text("changed\n")
    assert chk(repo, s, "other") == 1
    assert not marker.exists()
    env = cfs.git_env()
    assert set(env) == {"PATH", "HOME", "LC_ALL", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT", "GIT_ASKPASS", "GIT_PAGER",
                       "GIT_NO_LAZY_FETCH", "GIT_ALLOW_PROTOCOL", "GIT_PROTOCOL_FROM_USER", "GIT_ATTR_NOSYSTEM"}
    assert env["PATH"] == "/usr/bin:/bin" and "/usr/local" not in env["PATH"] and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_NO_LAZY_FETCH"] == "1" and env["GIT_ALLOW_PROTOCOL"] == "none" and env["GIT_PROTOCOL_FROM_USER"] == "0" and env["GIT_ATTR_NOSYSTEM"] == "1"
    argv = cfs.git_argv("status")
    assert argv[1:4] == ["--no-pager", "--no-optional-locks", "--no-replace-objects"]
    assert "core.fsmonitor=false" in argv and "core.hooksPath=" + os.devnull in argv and argv[-1] == "status"


def test_all_git_calls_go_through_helper():
    src = (Path(cfs.__file__)).read_text(encoding="utf-8")
    assert src.count("subprocess.run(") == 1                                                          # genau ein Einstiegspunkt


# --- .git-Integrität ---------------------------------------------------------------------------------------
def test_new_hook_is_integrity_violation(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    (repo / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
    capsys.readouterr()
    assert chk(repo, s, "none") == 1
    assert ".git-Integrität verletzt: .git/hooks/pre-commit" in capsys.readouterr().out
    assert chk(repo, s, ".git/**", ".git/hooks/pre-commit") == 1                                       # --allowed ändert nichts


def test_modified_sample_hook_and_deleted_hook_detected(repo, tmp_path):
    samples = sorted((repo / ".git" / "hooks").glob("*.sample"))
    if not samples:
        (repo / ".git" / "hooks").mkdir(exist_ok=True)
        samples = [repo / ".git" / "hooks" / "x.sample"]
        samples[0].write_text("a")
    s = snap(repo, tmp_path)
    samples[0].write_text("geändert")
    assert chk(repo, s, "none") == 1
    s = snap(repo, tmp_path)
    samples[0].unlink()
    assert chk(repo, s, "none") == 1


def test_info_exclude_and_attributes_change_detected(repo, tmp_path, capsys):
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "exclude").write_text("# a\n")
    s = snap(repo, tmp_path)
    assert chk(repo, s, "none") == 0
    (repo / ".git" / "info" / "exclude").write_text("# a\nsecret.txt\n")
    capsys.readouterr()
    assert chk(repo, s, "none") == 1 and ".git/info/exclude" in capsys.readouterr().out
    s = snap(repo, tmp_path)
    (repo / ".git" / "info" / "attributes").write_text("*.txt text\n")
    assert chk(repo, s, "none") == 1


def test_harmless_config_change_after_snapshot_is_violation(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    cfg(repo, "user.name", "Spaeter")
    capsys.readouterr()
    assert chk(repo, s, ".git/config") == 1
    assert ".git-Integrität verletzt: .git/config" in capsys.readouterr().out


def test_refs_replace_after_snapshot_is_violation(repo, tmp_path, capsys):
    (repo / "a.txt").write_text("zwei\n")
    g(repo, "commit", "-qam", "zwei")
    s = snap(repo, tmp_path)
    assert chk(repo, s, "none") == 0
    g(repo, "replace", "HEAD", "HEAD~1")
    capsys.readouterr()
    assert chk(repo, s, "none") == 1
    assert "refs/replace/" in capsys.readouterr().out


# --- Index-Flags --------------------------------------------------------------------------------------------
def test_assume_unchanged_and_skip_worktree_set_after_snapshot_is_violation(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    g(repo, "update-index", "--assume-unchanged", "a.txt")
    capsys.readouterr()
    assert chk(repo, s, "a.txt") == 1
    assert "Index-Flag gesetzt: a.txt" in capsys.readouterr().out
    g(repo, "update-index", "--no-assume-unchanged", "a.txt")
    assert chk(repo, s, "none") == 0
    g(repo, "update-index", "--skip-worktree", "tool.sh")
    assert chk(repo, s, "tool.sh") == 1
    assert "Index-Flag gesetzt: tool.sh" in capsys.readouterr().out


def test_flag_recorded_and_hidden_change_of_flagged_file_detected(repo, tmp_path, capsys):
    (repo / "a.txt").write_text("schon geändert\n")
    g(repo, "update-index", "--assume-unchanged", "a.txt")
    g(repo, "update-index", "--skip-worktree", "tool.sh")
    s = snap(repo, tmp_path)
    d = json.loads(s.read_text())
    assert d["flags"] == {"a.txt": "h", "tool.sh": "S"} and "a.txt" in d["files"]                      # Flag erfasst und Datei trotz leerem git status gehasht
    assert g(repo, "status", "--porcelain") == ""
    assert chk(repo, s, "none") == 0                                                                   # unverändert -> kein Verstoß
    (repo / "a.txt").write_text("noch weiter geändert\n")                                              # git status schweigt weiterhin
    assert g(repo, "status", "--porcelain") == ""
    capsys.readouterr()
    assert chk(repo, s, "none") == 1 and "a.txt" in capsys.readouterr().out
    assert chk(repo, s, "a.txt") == 0
    (repo / "tool.sh").write_text("#!/bin/sh\necho x\n")
    assert chk(repo, s, "a.txt") == 1


# --- Snapshot-Schutz (MAC) ----------------------------------------------------------------------------------
def test_snapshot_must_be_outside_repo(repo, tmp_path, capsys):
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(repo / "snap.json")]) == 2
    assert "außerhalb" in capsys.readouterr().err and not (repo / "snap.json").exists()
    link = tmp_path / "lnk"
    os.symlink(repo, link)                                                                             # Symlink ins Repo
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(link / "s.json")]) == 2
    assert not (repo / "s.json").exists()
    (repo / "sub").mkdir()
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(repo / "sub" / "s.json")]) == 2
    os.symlink(repo / "x.json", tmp_path / "ls.json")                                                  # Ziel-Symlink zeigt ins Repo
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(tmp_path / "ls.json")]) == 2


def test_snapshot_key_not_in_file_mode_0600_and_key_required(repo, tmp_path, monkeypatch, capsys):
    s = snap(repo, tmp_path)
    key = os.environ["CFS_SNAPSHOT_KEY"]
    text = s.read_text()
    assert key not in text and "mac" in json.loads(text)
    assert stat.S_IMODE(os.stat(s).st_mode) == 0o600
    assert chk(repo, s, "none") == 0
    monkeypatch.delenv("CFS_SNAPSHOT_KEY")
    capsys.readouterr()
    assert chk(repo, s, "none") == 2 and "CFS_SNAPSHOT_KEY" in capsys.readouterr().err                # Schlüssel fehlt
    monkeypatch.setenv("CFS_SNAPSHOT_KEY", "0" * 64)
    capsys.readouterr()
    assert chk(repo, s, "none") == 2 and "MAC" in capsys.readouterr().err                             # falscher Schlüssel
    monkeypatch.setenv("CFS_SNAPSHOT_KEY", key)
    assert chk(repo, s, "none") == 0
    s2 = snap(repo, tmp_path, "snap2.json")
    assert os.environ["CFS_SNAPSHOT_KEY"] != key                                                       # zufällig je Snapshot


def test_tampered_or_unsigned_snapshot_rejected(repo, tmp_path):
    (repo / "x.txt").write_text("x")
    s = snap(repo, tmp_path)
    good = json.loads(s.read_text())
    assert "x.txt" in good["files"]
    t = dict(good); t["files"] = {k: v for k, v in good["files"].items() if k != "x.txt"}              # Eintrag entfernt
    s.write_text(json.dumps(t))
    assert chk(repo, s, "none") == 2
    t = dict(good); t["head"] = "0" * 40
    s.write_text(json.dumps(t))
    assert chk(repo, s, "none") == 2
    t = dict(good); t["gitmeta"] = {}
    s.write_text(json.dumps(t))
    assert chk(repo, s, "none") == 2
    t = dict(good); del t["mac"]
    s.write_text(json.dumps(t))
    assert chk(repo, s, "none") == 2
    t = dict(good); t["mac"] = "00" * 32
    s.write_text(json.dumps(t))
    assert chk(repo, s, "none") == 2
    s.write_text(json.dumps(good))
    assert chk(repo, s, "x.txt") == 0                                                                  # Original weiterhin gültig


# --- allumfassende Muster ---------------------------------------------------------------------------------
@pytest.mark.parametrize("pat", ["**", "**/*", "**/**", "/**", "/", "", "/**/*"])
def test_all_embracing_patterns_rejected(repo, tmp_path, pat):
    s = snap(repo, tmp_path)
    assert chk(repo, s, pat) == 2
    assert cfs.main(["check", "--repo", str(repo), "--snapshot", str(s), "--allowed", "ok.txt", "--allowed", pat]) == 2
    if pat:
        assert cfs.main(["overlap", "--repo", str(repo), "--set", f"A={pat}", "--set", "B=a.txt"]) == 2


def test_top_level_directory_pattern_warns_but_is_accepted(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    (repo / "backend").mkdir()
    (repo / "backend" / "x.py").write_text("x")
    capsys.readouterr()
    assert chk(repo, s, "backend/**") == 0
    assert "WARNUNG" in capsys.readouterr().err
    assert chk(repo, s, "backend/") == 0 and chk(repo, s, "backend/**/*") == 0
    capsys.readouterr()
    assert chk(repo, s, "backend/x.py") == 0
    assert "WARNUNG" not in capsys.readouterr().err


# --- Rauschen: skriptartige Dateien ------------------------------------------------------------------------
@pytest.mark.parametrize("rel", [".venv/lib/site-packages/evil.pth", ".venv/lib/x.py", "node_modules/p/i.js", "pkg/__pycache__/m.cpython-312.pyc",
                                 "dist/run.sh", "build/lib/x.so"])
def test_new_script_in_noise_dir_is_violation(repo, tmp_path, capsys, rel):
    s = snap(repo, tmp_path)
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text("x")
    capsys.readouterr()
    assert chk(repo, s, "none") == 1 and rel in capsys.readouterr().out
    assert chk(repo, s, rel) == 0


def test_changed_and_deleted_script_in_noise_dir_is_violation(repo, tmp_path):
    p = repo / "node_modules" / "p" / "i.js"
    p.parent.mkdir(parents=True)
    p.write_text("v1")
    s = snap(repo, tmp_path)
    assert chk(repo, s, "none") == 0                                                                   # unverändert: kein Verstoß
    p.write_text("v2")
    assert chk(repo, s, "none") == 1
    s = snap(repo, tmp_path)
    p.unlink()
    assert chk(repo, s, "none") == 1


def test_performance_20000_noise_files(repo, tmp_path):
    nm = repo / "node_modules"
    for d in range(200):
        sub = nm / f"p{d}"
        sub.mkdir(parents=True)
        for i in range(100):
            (sub / f"f{i}.{'js' if i % 2 else 'txt'}").write_text("x")
    (nm / ".bin").mkdir()
    for i in range(5):                                                                                 # ausführbar ohne Endung: ELF/Shebang werden gehasht
        (nm / ".bin" / f"tool{i}").write_bytes(b"#!/bin/sh\n" if i % 2 else b"\x7fELF\0\0")
        os.chmod(nm / ".bin" / f"tool{i}", 0o755)
    for i in range(50):                                                                                # Ausführbit, aber Daten: Rauschen
        (nm / ".bin" / f"data{i}").write_text("daten")
        os.chmod(nm / ".bin" / f"data{i}", 0o755)
    t0 = time.monotonic()
    s = snap(repo, tmp_path)
    t1 = time.monotonic()
    assert chk(repo, s, "none") == 0
    t2 = time.monotonic()
    files = json.loads(s.read_text())["files"]
    assert len(files) == 10_005                                                                        # *.js + 5 ELF/Shebang-Dateien gehasht, *.txt/Datendateien nicht
    print(f"20000 Rauschdateien: snapshot {t1 - t0:.1f}s, check {t2 - t1:.1f}s")
    assert (t1 - t0) < 120 and (t2 - t1) < 120
    (nm / "p3" / "f1.js").write_text("geändert")
    assert chk(repo, s, "none") == 1


def test_repo_subdirectory_resolves_toplevel(repo, tmp_path):
    (repo / "sub").mkdir()
    s = snap(repo / "sub", tmp_path)
    assert chk(repo / "sub", s, "none") == 0


# === Nachhärtung (Review): PATH, filemode, Rauschen mit Ausführbit, Sondierungsmuster, -I, --key-file, geschachtelte Repos ================
def test_git_binary_resolved_only_from_safe_path(monkeypatch):
    assert cfs.SAFE_PATH == "/usr/bin:/bin"
    exe = cfs.git_argv("status")[0]
    assert os.path.dirname(exe) in ("/usr/bin", "/bin")


@pytest.mark.parametrize("val,ok", [("true", True), ("false", True), ("TRUE", True), ("maybe", False), ("", False), ("$(touch x)", False)])
def test_core_filemode_value_checked(repo, tmp_path, val, ok):
    cfg(repo, "core.filemode", val)
    assert run(repo, tmp_path) == (0 if ok else 2)


def test_filemode_change_after_snapshot_is_integrity_violation(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    cfg(repo, "core.filemode", "false")
    capsys.readouterr()
    assert chk(repo, s, ".git/config") == 1
    assert ".git-Integrität verletzt: .git/config" in capsys.readouterr().out


def test_executable_without_extension_in_noise_dir_is_hashed(repo, tmp_path, capsys):
    s = snap(repo, tmp_path)
    done: list[str] = []
    for rel, content in ((".venv/bin/tool", b"#!/usr/bin/python3\n"), ("node_modules/.bin/elfy", b"\x7fELF\2\1")):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(content)
        os.chmod(repo / rel, 0o755)
        capsys.readouterr()
        assert chk(repo, s, "none") == 1 and rel in capsys.readouterr().out
        done.append(rel)
        assert chk(repo, s, *done) == 0
    # Ausführbit ohne Magic oder Magic ohne Ausführbit: Rauschen
    (repo / ".venv/bin/data").write_text("nur daten")
    os.chmod(repo / ".venv/bin/data", 0o755)
    (repo / ".venv/bin/plain").write_bytes(b"\x7fELF\2\1")
    assert chk(repo, s, ".venv/bin/tool", "node_modules/.bin/elfy") == 0


def test_changed_executable_in_noise_dir_is_violation(repo, tmp_path):
    p = repo / ".venv" / "bin" / "py"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"#!/bin/sh\necho 1\n")
    os.chmod(p, 0o755)
    s = snap(repo, tmp_path)
    assert chk(repo, s, "none") == 0
    p.write_bytes(b"#!/bin/sh\necho 2\n")
    assert chk(repo, s, "none") == 1


@pytest.mark.parametrize("pat", ["[!a]**", "**/*.*", "**/?*", "?**", "[!/]**", "**/[!/]*", "**/*[!/]"])
def test_near_all_embracing_patterns_rejected(repo, tmp_path, pat):
    s = snap(repo, tmp_path)
    assert chk(repo, s, pat) == 2
    assert cfs.main(["overlap", "--repo", str(repo), "--set", f"A={pat}", "--set", "B=a.txt"]) == 2


@pytest.mark.parametrize("pat", ["backend/leventum/services/*.py", "**/*.py", "**/*.md", "docs/**", "src/*", "[ab]*", "a*"])
def test_ordinary_patterns_not_rejected_by_probes(pat):
    cfs.validate_patterns([pat])


def test_probe_set_contains_requested_paths():
    for x in ("a", "A", ".x", "x.y.z", "1/2", "x/y/z/w.txt", ".hidden/a", "_", "-x", "a.txt"):
        assert x in cfs.PROBE_PATHS


def script_cmd(*args):
    root = Path(cfs.__file__).resolve()
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return env, [sys.executable, str(root), *args]


def test_script_requires_isolated_mode(repo, tmp_path):
    env, cmd = script_cmd("overlap", "--repo", str(repo), "--set", "A=a.txt", "--set", "B=b.txt")
    plain = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=tmp_path)
    assert plain.returncode == 2 and "-I" in plain.stderr and "python3 -I scripts/check_file_set.py" in plain.stderr
    assert "OK" not in plain.stdout
    iso = subprocess.run([cmd[0], "-I", *cmd[1:]], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert iso.returncode == 0 and "disjunkt" in iso.stdout, iso.stderr


def test_planted_stdlib_module_in_script_dir_does_not_run(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    marker = tmp_path / "PLANTED"
    (d / "hmac.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    shutil.copy(cfs.__file__, d / "check_file_set.py")
    env = {"PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(d / "check_file_set.py"), "--help"], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 2 and not marker.exists()
    r = subprocess.run([sys.executable, "-I", str(d / "check_file_set.py"), "--help"], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0 and not marker.exists()


# --- --key-file ---------------------------------------------------------------------------------------------
def test_key_file_roundtrip_without_printing_key(repo, tmp_path, capsys, monkeypatch):
    kf, out = tmp_path / "k.key", tmp_path / "s.json"
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(out), "--key-file", str(kf)]) == 0
    printed = capsys.readouterr().out
    key = kf.read_text().strip()
    assert re.fullmatch(r"[0-9a-f]{64}", key) and key not in printed and "KEY=" not in printed
    assert stat.S_IMODE(os.stat(kf).st_mode) == 0o600
    assert cfs.main(["check", "--repo", str(repo), "--snapshot", str(out), "--key-file", str(kf), "--allowed", "x"]) == 0
    (repo / "neu.txt").write_text("x")
    assert cfs.main(["check", "--repo", str(repo), "--snapshot", str(out), "--key-file", str(kf), "--allowed", "x"]) == 1
    monkeypatch.setenv("CFS_SNAPSHOT_KEY", "0" * 64)                                                   # Datei hat Vorrang vor Umgebung
    assert cfs.main(["check", "--repo", str(repo), "--snapshot", str(out), "--key-file", str(kf), "--allowed", "neu.txt"]) == 0


def test_key_file_rejections(repo, tmp_path, capsys):
    out = tmp_path / "s.json"
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(out), "--key-file", str(repo / "k.key")]) == 2   # im Repo
    assert not (repo / "k.key").exists() and not out.exists()
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(out), "--key-file", str(out)]) == 2             # identisch mit --out
    target = tmp_path / "target"
    os.symlink(target, tmp_path / "lnk.key")
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(out), "--key-file", str(tmp_path / "lnk.key")]) == 2   # Symlink beim Schreiben
    assert not target.exists()
    kf = tmp_path / "k.key"
    assert cfs.main(["snapshot", "--repo", str(repo), "--out", str(out), "--key-file", str(kf)]) == 0
    chkargs = ["check", "--repo", str(repo), "--snapshot", str(out), "--allowed", "x", "--key-file"]
    os.chmod(kf, 0o644)
    capsys.readouterr()
    assert cfs.main([*chkargs, str(kf)]) == 2 and "Rechte" in capsys.readouterr().err                   # zu weite Rechte
    os.chmod(kf, 0o600)
    key = kf.read_text().strip()
    os.symlink(kf, tmp_path / "ln2.key")
    assert cfs.main([*chkargs, str(tmp_path / "ln2.key")]) == 2                                          # Symlink beim Lesen
    kf.write_text("kein hex\n")
    assert cfs.main([*chkargs, str(kf)]) == 2
    kf.write_text("0" * 64 + "\n")
    capsys.readouterr()
    assert cfs.main([*chkargs, str(kf)]) == 2 and "MAC" in capsys.readouterr().err                       # falscher Schlüssel
    assert cfs.main([*chkargs, str(tmp_path / "fehlt.key")]) == 2
    in_repo = repo / "k2.key"
    in_repo.write_text(key + "\n")
    os.chmod(in_repo, 0o600)
    assert cfs.main([*chkargs, str(in_repo)]) == 2                                                       # Schlüsseldatei im Repo
    assert key not in capsys.readouterr().err


# --- geschachtelte Repos / Gitlinks -------------------------------------------------------------------------
def nested(repo, name="nest"):
    n = repo / name
    n.mkdir()
    g(n, "init", "-q")
    (n / "f.txt").write_text("1")
    g(n, "add", "-A")
    g(n, "commit", "-qm", "n1")
    return n


def test_nested_repo_head_change_is_violation(repo, tmp_path, capsys):
    n = nested(repo)
    s = snap(repo, tmp_path)
    assert chk(repo, s, "none") == 0
    (n / "f.txt").write_text("2")
    g(n, "commit", "-qam", "n2")                                                                         # HEAD zeigt auf Branch: aufgelöste Ref ändert sich
    capsys.readouterr()
    assert chk(repo, s, "none") == 1 and "nest" in capsys.readouterr().out
    assert chk(repo, s, "nest/") == 0


def test_nested_repo_detached_head_and_packed_refs(repo, tmp_path):
    n = nested(repo)
    first = g(n, "rev-parse", "HEAD")
    (n / "f.txt").write_text("2")
    g(n, "commit", "-qam", "n2")
    g(n, "pack-refs", "--all")                                                                           # lose Ref weg, nur packed-refs
    s = snap(repo, tmp_path)
    assert chk(repo, s, "none") == 0
    g(n, "checkout", "-q", "--detach", first)                                                            # HEAD-Datei enthält jetzt direkt eine SHA
    assert chk(repo, s, "none") == 1


def test_new_nested_repo_after_snapshot_is_violation(repo, tmp_path):
    s = snap(repo, tmp_path)
    nested(repo)
    assert chk(repo, s, "none") == 1


def test_gitlink_head_recorded(repo, tmp_path):
    n = nested(repo, "sm")
    sha = g(n, "rev-parse", "HEAD")
    g(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},sm")
    s = snap(repo, tmp_path)
    val = json.loads(s.read_text())["files"]["sm"]
    assert val.startswith(f"gitlink:{sha}:nested:") and sha in val.split(":nested:")[1]
    assert chk(repo, s, "none") == 0
    (n / "f.txt").write_text("3")
    g(n, "commit", "-qam", "n3")                                                                         # Gitlink im Index unverändert, HEAD im Submodul neu
    assert chk(repo, s, "none") == 1


@pytest.mark.parametrize("pat", ["*/**", "*/*", "?/**", "*/**/*", "[!.]*/**"])
def test_wildcard_first_segment_without_restriction_is_rejected(pat):
    """Review: `*/**` trifft nur ~77 % der Sondierungspfade, gibt aber .claude/** und scripts/** pauschal frei -> abgelehnt (ToolError, Exit 2)."""
    with pytest.raises(cfs.ToolError):
        cfs.validate_patterns([pat])


@pytest.mark.parametrize("pat", ["*/*.py", "backend/**", "scripts/*.py", "docs/", "*/README.md"])
def test_restricted_patterns_with_wildcard_segments_are_still_allowed(pat):
    cfs.validate_patterns([pat])
