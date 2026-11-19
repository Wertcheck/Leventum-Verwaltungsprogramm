"""Statische Prüfungen der Windows-Paketierungsdateien (KEIN Ausführen von PowerShell/Inno/PyInstaller – das ist unter Linux nicht möglich).
Sie fangen bekannte Fehlerklassen ab (Scope-Fehler, Quoting, BOM, Workflow-Grenzen), ersetzen aber keinen Windows-Lauf."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PK = ROOT / "packaging"


def test_inno_script_has_utf8_bom_and_never_deletes_user_data():
    raw = (PK / "leventum.iss").read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"          # sonst liest Inno Umlaute als ANSI
    text = raw.decode("utf-8-sig")
    assert not re.search(r"^\[UninstallDelete\]", text, re.M)  # Benutzerdaten bleiben bei der Deinstallation
    assert "PrivilegesRequired=lowest" in text and "{localappdata}\\Programs\\Leventum" in text
    assert re.search(r"AppId=\{\{[0-9A-F-]{36}\}", text)


def test_powershell_scripts_are_ascii_only():
    for f in ("build_windows.ps1", "installer_smoke.ps1"):
        (PK / f).read_text(encoding="ascii")    # wirft bei Nicht-ASCII (Windows PowerShell 5.1 liest BOM-lose Dateien als ANSI)


def test_smoke_script_shares_session_variables_across_check_blocks():
    s = (PK / "installer_smoke.ps1").read_text(encoding="ascii")
    assert "$script:s2 = $s2" in s              # M-1: Prüfung 07 liest $s2 aus Prüfung 06
    assert '"/DIR=`"$app`""' in s               # L-5: Pfad mit Leerzeichen
    for var in re.findall(r"-SessionVariable (\w+)", s):
        assert f"$script:{'sess' if var == 's' else var} = ${var}" in s, var


def test_workflow_is_manual_read_only_and_never_releases():
    w = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")
    assert re.search(r"^on: workflow_dispatch\s*$", w, re.M) and "push:" not in w and "pull_request" not in w and "schedule" not in w
    assert "contents: read" in w and "secrets." not in w and "${{" not in w
    assert not re.search(r"release|deploy|gh-release|publish", w, re.I)


def test_spec_bundles_alembic_frontend_and_two_programs():
    s = (PK / "leventum.spec").read_text(encoding="utf-8")
    assert '"alembic.ini"' in s.replace("BACKEND / ", "") or "alembic.ini" in s
    for needle in ('"alembic"', '"frontend_dist"', 'name="Leventum"', 'name="LeventumServer"', "console=False", "console=True"):
        assert needle in s, needle
