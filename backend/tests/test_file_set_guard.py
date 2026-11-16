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
import json
import os
import subprocess

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


def snap(r, tmp_path):
    out = tmp_path / "snap.json"
    assert cfs.main(["snapshot", "--repo", str(r), "--out", str(out)]) == 0
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
    # Rauschen: nichts davon darf Verstoß erzeugen oder im Snapshot stehen
    for rel in ("node_modules/x/y.js", ".venv/lib/z.py", "pkg/__pycache__/m.pyc", "dist/bundle.js", "t.pyc"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("noise")
    assert chk(repo, s, "none") == 0
    assert set(cfs.dirty_files(repo)) == {"secret.env"}


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
    unknown.write_text(json.dumps({"version": 2, "head": "0123456789abcdef0123456789abcdef01234567", "files": {}}))
    capsys.readouterr()
    assert chk(repo, unknown, "x") == 2                                                              # unbekannter HEAD
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
