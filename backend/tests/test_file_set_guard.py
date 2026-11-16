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
