"""Tests für die Agenten-Schreibsperre: Hook .claude/hooks/ro_guard.py (Befehlsfilter) und scripts/ro_run.sh (OS-Ebene, nur Linux mit root).
Keine destruktiven Tests: Schreibversuche zielen auf ein Wegwerfverzeichnis unter tmp_path bzw. auf /tmp-Pfade, nie auf Repo oder Lexono."""
import importlib.util
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
    # Review-Befund H1: '#' mitten im Wort ist für shlex ein Kommentar, für Bash nicht – der Rest nach ';', '&&', '|' lief an der Isolation vorbei
    "scripts/ro_run.sh echo a#b; touch /x",
    "scripts/ro_run.sh echo a #b; touch /x",
    "scripts/ro_run.sh echo a#b && touch /x",
    "scripts/ro_run.sh echo a#b | tee /x",
    "scripts/ro_run.sh ls # kommentar",
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


def test_shlex_comment_semantics_cannot_hide_operators():
    """Der Hook darf nie wegen shlex-Kommentarregeln Tokens verlieren: direkte Prüfung der Funktion (ohne Subprozess)."""
    spec = importlib.util.spec_from_file_location("ro_guard", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for cmd in ("scripts/ro_run.sh echo a#b; touch /x", "scripts/ro_run.sh echo a#b && touch /x", "scripts/ro_run.sh echo a #b | tee /x"):
        assert mod.check_command(cmd, str(ROOT)) is not None, cmd
    assert mod.check_command("scripts/ro_run.sh bash -c 'echo hallo'", str(ROOT)) is None


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


# ======================================================================================================================
# Nachreview-Härtung von scripts/ro_run.sh und ro_guard.py. Alle Tests mit erfundenen Dummy-Werten; gefährliche Fälle NUR über den Runner.
# ======================================================================================================================
def _runner_usable():
    """Runner im aktuellen (ggf. geschachtelten) Kontext lauffähig? Nur Namespace-/Mount-Einrichtungsfehler führen zum Skip, nie ein Fehlverhalten des Ziel-Befehls."""
    if not (sys.platform.startswith("linux") and os.geteuid() == 0 and shutil.which("unshare") and shutil.which("setpriv") and shutil.which("mount")):
        return False, "Runner benötigt Linux, root, unshare, setpriv, mount"
    r = subprocess.run([str(RUNNER), "id", "-u"], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0 and any(s in r.stderr for s in ("unshare:", "mount:", "Operation not permitted", "Permission denied")):
        return False, f"Runner im geschachtelten Kontext nicht lauffähig: {r.stderr.strip()[:120]}"
    return True, ""


_OK, _WHY = _runner_usable()
needs_runner = pytest.mark.skipif(not _OK, reason=_WHY or "Runner nicht lauffähig")


def ro_env(*args, extra=None, remove=(), pass_fds=(), cwd=ROOT):
    env = dict(os.environ)
    for k in remove:
        env.pop(k, None)
    env.update(extra or {})
    return subprocess.run([str(RUNNER), *args], capture_output=True, text=True, cwd=cwd, env=env, pass_fds=pass_fds)


def _parse_env(out):
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


ALLOWLIST = {"PATH", "HOME", "LANG", "TERM", "PYTHONDONTWRITEBYTECODE", "PYTEST_ADDOPTS", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0",
             "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT"}
# Ausdrücklich tolerierte, NICHT vom Skript gesetzte Zusatzvariablen (könnten Shell/Profil/Nix setzen; im Ist-Zustand erscheint keine davon).
TOLERATED_EXTRA = {"PWD", "SHLVL", "_", "XDG_DATA_DIRS", "__ETC_PROFILE_NIX_SOURCED"}
POISON = {"GITHUB_TOKEN": "dummy-secret-123", "GH_TOKEN": "dummy-secret-124", "CLAUDE_CODE_MESSAGING_TOKEN": "dummy-secret-125",
          "CLOUDSDK_AUTH_ACCESS_TOKEN": "dummy-secret-126", "SESSION_INGRESS_URL": "http://dummy-ingress.invalid/x",
          "PYTHONPATH": "/x", "PYTHONSTARTUP": "/x", "BASH_ENV": "/x", "ENV": "/x", "PYTEST_ADDOPTS": "-pX",
          "LEVENTUM_DATA_DIR": "/x", "NODE_OPTIONS": "x"}   # bewusst OHNE LD_PRELOAD (würde die root-Prozesse des Runners selbst treffen)


@needs_runner
def test_runner_environment_is_allowlist_only():
    r = ro_env("env", extra=POISON)
    assert r.returncode == 0, r.stderr
    env = _parse_env(r.stdout)
    for name, value in POISON.items():
        if name == "PYTEST_ADDOPTS":
            continue
        assert name not in env, name
        assert f"{name}={value}" not in r.stdout.splitlines(), name
        if value.startswith("dummy-") or "dummy" in value:
            assert value not in r.stdout, name        # eindeutige Dummy-Werte: nirgends in der Ausgabe
    assert "-pX" not in r.stdout and env["PYTEST_ADDOPTS"] == "-p no:cacheprovider"
    extras = set(env) - ALLOWLIST
    assert extras <= TOLERATED_EXTRA or all(k.startswith("NIX_") for k in extras - TOLERATED_EXTRA), sorted(extras)
    assert not [k for k in extras if any(w in k.upper() for w in ("TOKEN", "SECRET", "KEY", "PASSWORD"))]
    assert env["HOME"] == "/tmp" and env["PYTHONDONTWRITEBYTECODE"] == "1"


UID_REJECTED = ["0", "abc", "-1", "70000", "65534;id", "0 --x", "65535", "1e3", " ", "1 000", "0x10", "99999", "00000", "0000", "065534", "\t", "１０００"]


@needs_runner
@pytest.mark.parametrize("value", UID_REJECTED)
def test_runner_rejects_invalid_uid_and_runs_nothing(value):
    r = ro_env("id", "-u", extra={"RO_RUN_UID": value})
    assert r.returncode == 3, (value, r.returncode, r.stderr)
    assert r.stdout == ""                              # Ziel-Befehl wurde nicht ausgeführt
    assert "fail closed" in r.stderr


@needs_runner
def test_runner_uid_default_for_empty_and_unset_and_valid_custom():
    assert ro_env("id", "-u", extra={"RO_RUN_UID": ""}).stdout.strip() == "65534"
    r = ro_env("id", "-u", remove=("RO_RUN_UID",))
    assert r.returncode == 0 and r.stdout.strip() == "65534"
    r = ro_env("id", "-u", extra={"RO_RUN_UID": "1000"})
    assert r.returncode == 0 and r.stdout.strip() == "1000"


@needs_runner
@pytest.mark.parametrize("template", ["65534; touch {f}", "65534\ntouch {f}", "$(touch {f})", "`touch {f}`", "65534 && touch {f}"])
def test_runner_uid_injection_does_not_execute(tmp_path, template):
    marker = tmp_path / "injected"
    r = ro_env("id", "-u", extra={"RO_RUN_UID": template.format(f=marker)})
    assert r.returncode == 3 and r.stdout == ""
    assert not marker.exists()


@needs_runner
@pytest.mark.parametrize("args", [("--reuid=0", "id"), ("-x",), ("--",), ("-x", "id", "-u"), ("--reuid=0", "--", "id", "-u")])
def test_runner_rejects_option_as_first_argument(args):
    r = ro_env(*args)
    assert r.returncode == 2, (args, r.returncode, r.stderr)
    assert r.stdout == ""                              # 'id' wurde nicht ausgeführt (sonst uid=… in stdout)


@needs_runner
def test_runner_process_has_no_privileges_no_network_own_pid_namespace():
    status = dict(line.split(":\t", 1) for line in ro("cat", "/proc/self/status").stdout.splitlines() if ":\t" in line)
    for cap in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        assert int(status[cap].strip(), 16) == 0, cap
    assert status["NoNewPrivs"].strip() == "1"
    assert ro("id", "-u").stdout.strip() == "65534" and ro("id", "-g").stdout.strip() == "65534"
    assert ro("id", "-G").stdout.strip() == "65534"    # --clear-groups: keine Zusatzgruppen
    dev = ro("cat", "/proc/net/dev").stdout.splitlines()[2:]
    assert [ln.split(":")[0].strip() for ln in dev if ln.strip()] == ["lo"]
    pids = ro("python3", "-c", "import os;print(' '.join(sorted(d for d in os.listdir('/proc') if d.isdigit())))").stdout.split()
    assert 1 <= len(pids) <= 10, pids
    host_pid = os.getpid()
    assert str(host_pid) not in pids
    assert ro("test", "-e", f"/proc/{host_pid}").returncode != 0   # Host-Prozess im Namespace nicht sichtbar
    assert Path(f"/proc/{host_pid}").exists()                      # (Kontrolle: im Host existiert er)


@needs_runner
@pytest.mark.parametrize("target", [str(ROOT / "__ro_probe__"), "/dev/shm/__ro_probe__", "/run/__ro_probe__", "/var/tmp/__ro_probe__"])
def test_runner_write_denied_on_repo_and_other_writable_paths(target):
    if not Path(target).parent.is_dir():
        pytest.skip(f"{Path(target).parent} existiert in dieser Umgebung nicht (sonst wäre der Fehler 'No such file' und kein Beweis)")
    assert not Path(target).exists()
    r = ro("bash", "-c", f"echo x > {target}; echo rc=$?")
    # /run ist im Runner ein leeres root-eigenes tmpfs (Sockets verdeckt) -> dort "Permission denied" statt "Read-only"; beides = nicht beschreibbar
    assert ("Read-only file system" in r.stderr) or (target.startswith("/run/") and "Permission denied" in r.stderr), r.stderr
    assert "rc=0" not in r.stdout
    assert not Path(target).exists()                   # Befund, falls doch entstanden: Datei entfernen und melden
    if Path(target).exists():
        Path(target).unlink()


@needs_runner
def test_runner_tmp_is_private_tmpfs_with_nosuid_nodev():
    name = f"ro_probe_{os.getpid()}"
    r = ro("bash", "-c", f"echo x > /tmp/{name}; echo rc=$?; test -f /tmp/{name}; echo seen=$?; grep -E '^[^ ]+ /tmp ' /proc/self/mounts")
    assert "rc=0" in r.stdout and "seen=0" in r.stdout
    assert not Path("/tmp", name).exists()
    mount = [ln for ln in r.stdout.splitlines() if " /tmp " in ln]
    assert mount, r.stdout
    fstype, opts = mount[-1].split()[2], mount[-1].split()[3].split(",")
    assert fstype == "tmpfs" and "nosuid" in opts and "nodev" in opts


@needs_runner
def test_runner_closes_inherited_file_descriptors(tmp_path):
    f = tmp_path / "leak.txt"
    with open(f, "w") as fh:
        fd = fh.fileno()
        assert fd > 2
        # Kontrolle: OHNE Runner ist der vererbte Deskriptor beschreibbar (sonst wäre der Test unbeweisend)
        ctl = subprocess.run(["bash", "-c", f"echo ctl >&{fd}"], pass_fds=(fd,), capture_output=True, text=True)
        assert ctl.returncode == 0
        fh.flush()
        assert f.read_text() == "ctl\n"
        r = ro_env("python3", "-c",
                   f"import os\ntry:\n os.write({fd}, b'LEAK')\n print('written')\nexcept OSError as e:\n print('errno', e.errno)\n"
                   "print('open', sorted(int(d) for d in os.listdir('/proc/self/fd')))", pass_fds=(fd,))
    assert r.returncode == 0, r.stderr
    assert "written" not in r.stdout and "errno 9" in r.stdout, r.stdout   # EBADF: Deskriptor im Ziel-Prozess nicht mehr vorhanden
    assert "LEAK" not in f.read_text()
    open_fds = json.loads(r.stdout.split("open ")[1].replace("'", '"'))
    assert fd not in open_fds


@needs_runner
@pytest.mark.skipif(shutil.which("gh") is None, reason="gh nicht installiert")
def test_runner_gh_has_no_login_and_no_network():
    assert ro("gh", "auth", "status").returncode != 0
    r = ro_env("gh", "api", "user", extra={"GH_TOKEN": "dummy-secret-123", "GITHUB_TOKEN": "dummy-secret-123"}, remove=("GH_HOST",))
    assert r.returncode != 0
    assert '"login"' not in r.stdout


@pytest.mark.parametrize("tool", ["mcp__github__create_issue", "mcp__anything", "mcp__"])
def test_hook_blocks_mcp_tools(tool):
    rc, err = run_hook({"tool_name": tool, "tool_input": {}})
    assert rc == 2 and "MCP" in err


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob"])
def test_hook_still_allows_read_tools(tool):
    assert run_hook({"tool_name": tool, "tool_input": {"pattern": "x"}})[0] == 0


@needs_runner
def test_runner_hides_host_run_directory_and_unix_sockets():
    """Nachreview: Pfad-Unix-Sockets (z. B. unter /run) sind durch --net nicht isoliert; /run im Runner ist ein leeres tmpfs."""
    r = ro_env("bash", "-c", "ls -A /run | wc -l; find / -xdev -type s 2>/dev/null | wc -l; grep -c ' /run ' /proc/self/mounts")
    assert r.returncode == 0, r.stderr
    n_entries, n_sockets, n_mount = (int(x) for x in r.stdout.split())
    assert n_entries == 0 and n_sockets == 0 and n_mount >= 1, r.stdout
