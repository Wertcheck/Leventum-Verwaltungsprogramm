"""Tests für die Agenten-Schreibsperre: Hook .claude/hooks/ro_guard.py (Befehlsfilter) und scripts/ro_run.sh (OS-Ebene, nur Linux mit root).
Keine destruktiven Tests: Schreibversuche zielen auf ein Wegwerfverzeichnis unter tmp_path bzw. auf /tmp-Pfade, nie auf Repo oder Lexono."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "ro_guard.py"
RUNNER = ROOT / "scripts" / "ro_run.sh"


def run_hook(payload, cwd=ROOT):
    p = subprocess.run([sys.executable, str(HOOK)], input=payload if isinstance(payload, str) else json.dumps(payload), capture_output=True, text=True, cwd=cwd)
    return p.returncode, p.stderr


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(ROOT)}


ALLOWED = [
    "scripts/ro_run.sh ls",
    "./scripts/ro_run.sh git diff --stat HEAD~1 HEAD",
    "scripts/ro_run.sh ./.venv/bin/python -m pytest backend/tests/test_dashboard.py -q",
    f"{RUNNER} grep -rn receivable_position backend",
    "scripts/ro_run.sh bash -c 'echo a; echo b'",   # Operatoren NUR in Anführungszeichen (laufen innerhalb der Read-only-Umgebung)
    "scripts/../scripts/ro_run.sh ls",
]
BLOCKED = [
    "touch .canary",
    "echo x > file.txt",
    "scripts/ro_run.sh ls; touch x",
    "scripts/ro_run.sh ls && touch x",
    "scripts/ro_run.sh ls || touch x",
    "scripts/ro_run.sh ls | tee x",
    "scripts/ro_run.sh ls > out.txt",
    "scripts/ro_run.sh ls >> out.txt",
    "scripts/ro_run.sh cat < /etc/passwd",
    'scripts/ro_run.sh "$(touch x)"',
    "scripts/ro_run.sh `touch x`",
    "scripts/ro_run.sh $HOME",
    "scripts/ro_run.sh ls\ntouch x",
    "scripts/ro_run.sh ls &",
    "cd backend && scripts/ro_run.sh ls",
    "FOO=1 scripts/ro_run.sh ls",
    "python3 -c \"open('x','w')\"",
    "bash -c 'touch x'",
    "sh -c 'scripts/ro_run.sh ls'",
    "git commit -m x",
    "git -C /home/user/lexono commit -m x",
    "/tmp/evil/scripts/ro_run.sh ls",
    "scripts/ro_run.sh",
    "scripts/ro_run.sh 'unbalanced",
    "",
    "   ",
    "scripts/ro_run.sh ls \\\n touch x",
    "(scripts/ro_run.sh ls)",
    "scripts/ro_run.sh ls 2>&1",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_hook_allows_only_ro_run(cmd):
    rc, err = run_hook(bash(cmd))
    assert rc == 0, err


@pytest.mark.parametrize("cmd", BLOCKED)
def test_hook_blocks_everything_else(cmd):
    rc, err = run_hook(bash(cmd))
    assert rc == 2 and "ro_guard" in err


@pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit"])
def test_hook_blocks_write_tools(tool):
    assert run_hook({"tool_name": tool, "tool_input": {"file_path": "x"}})[0] == 2


@pytest.mark.parametrize("payload", ["", "kein json", "[]", "{", "null", "42", '"Bash"', '{"tool_name": "Bash", "tool_input": null}', '{"tool_name": "Bash", "tool_input": {"command": 5}}'])
def test_hook_fails_closed_on_bad_input(payload):
    rc, _ = run_hook(payload)
    assert rc == 2   # Exit 1 würde NICHT blockieren – jede kaputte Eingabe muss mit 2 enden


def test_hook_ignores_read_tools():
    assert run_hook({"tool_name": "Read", "tool_input": {"file_path": "x"}})[0] == 0


# ----------------------------------------------------------------------------------------------------------------------
# OS-Ebene: nur Linux, root, unshare/setpriv vorhanden
needs_os_isolation = pytest.mark.skipif(
    not (sys.platform.startswith("linux") and os.geteuid() == 0 and shutil.which("unshare") and shutil.which("setpriv")),
    reason="Read-only-Runner benötigt Linux, root, unshare und setpriv (auf Windows nicht verfügbar → dort NICHT getestet)",
)


def ro(*args, cwd=ROOT):
    return subprocess.run([str(RUNNER), *args], capture_output=True, text=True, cwd=cwd)


@needs_os_isolation
def test_runner_reads_and_runs_as_unprivileged_user():
    r = ro("id", "-u")
    assert r.returncode == 0 and r.stdout.strip() == "65534"
    assert "README.md" in ro("ls").stdout


@needs_os_isolation
def test_runner_blocks_writes_everywhere_but_private_tmp(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "f.txt").write_text("orig")
    script = (f"echo x > {victim}/new.txt; echo a=$?; echo y >> {victim}/f.txt; echo b=$?; "
              "echo z > /tmp/private_ok; echo c=$?; python3 -c \"open('/home/pyw.txt','w')\" 2>/dev/null; echo d=$?")
    r = ro("bash", "-c", script)
    vals = dict(line.split("=") for line in r.stdout.split() if "=" in line)
    assert vals["a"] != "0" and vals["b"] != "0" and vals["d"] != "0"
    assert vals["c"] == "0"                          # privates tmpfs bleibt beschreibbar (Testdaten)
    assert (victim / "f.txt").read_text() == "orig" and not (victim / "new.txt").exists()
    assert not Path("/tmp/private_ok").exists()      # privat: nicht in der echten /tmp sichtbar


@needs_os_isolation
def test_runner_cannot_remount_or_write_block_device_or_use_network(tmp_path):
    r = ro("bash", "-c", "mount -o remount,rw / 2>&1; echo m=$?; python3 -c \"import socket;s=socket.socket();s.settimeout(2);print('n=%s' % s.connect_ex(('1.1.1.1',53)))\"")
    assert "m=0" not in r.stdout
    assert "n=0" not in r.stdout                      # kein Netzwerk


@needs_os_isolation
def test_runner_git_is_read_only():
    r = ro("bash", "-c", "git log --oneline | head -1 >/dev/null; echo r=$?; git commit --allow-empty -m x >/dev/null 2>&1; echo c=$?; git branch zz_should_not_exist >/dev/null 2>&1; echo b=$?")
    vals = dict(line.split("=") for line in r.stdout.split() if "=" in line)
    assert vals["r"] == "0" and vals["c"] != "0" and vals["b"] != "0"
    branches = subprocess.run(["git", "branch", "--list", "zz_should_not_exist"], capture_output=True, text=True, cwd=ROOT).stdout
    assert branches.strip() == ""


def test_runner_refuses_without_privileges_or_args():
    assert subprocess.run([str(RUNNER)], capture_output=True, cwd=ROOT).returncode == 2


# ---- Review-Befund H1: fehlendes python3 darf den Hook nicht fail-open machen (nur Exit-Code 2 blockiert) -----------------------------------
def _reviewer_hook_command():
    import re
    text = (ROOT / ".claude" / "agents" / "independent-reviewer.md").read_text(encoding="utf-8")
    m = re.search(r'command: "(.*)"\n', text)
    assert m, "Hook-Befehl im Frontmatter nicht gefunden"
    return m.group(1).replace('\\"', '"').replace("$CLAUDE_PROJECT_DIR", str(ROOT))


def test_reviewer_hook_command_blocks_when_python_is_missing():
    cmd = _reviewer_hook_command()
    assert cmd.rstrip().endswith("|| exit 2")
    r = subprocess.run(["/bin/sh", "-c", cmd], input="{}", capture_output=True, text=True, env={"PATH": "/nonexistent"})
    assert r.returncode == 2          # ohne '|| exit 2' wäre es 127 (= nicht blockierend)


def test_reviewer_hook_command_allows_ro_run_and_blocks_other_commands():
    cmd = _reviewer_hook_command()
    run = lambda c: subprocess.run(["/bin/sh", "-c", cmd], input=json.dumps(bash(c)), capture_output=True, text=True, cwd=ROOT).returncode
    assert run("scripts/ro_run.sh ls") == 0 and run("touch x") == 2
