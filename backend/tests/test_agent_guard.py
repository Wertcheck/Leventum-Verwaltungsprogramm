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


@pytest.fixture(autouse=True)
def _isolated_hook_log(tmp_path, monkeypatch):
    """Der Hook schreibt ein Aktivitätsprotokoll; Tests dürfen NIE ins echte ~/.leventum/hook-activity.jsonl schreiben (Subprozesse erben diese Variable)."""
    monkeypatch.setenv("LEVENTUM_HOOK_LOG", str(tmp_path / "hook-activity.jsonl"))


def run_hook_full(payload, cwd=ROOT, env=None):
    return subprocess.run([sys.executable, str(HOOK)], input=payload if isinstance(payload, str) else json.dumps(payload), capture_output=True, text=True, cwd=cwd, env=env)


def run_hook(payload, cwd=ROOT):
    p = run_hook_full(payload, cwd)
    return p.returncode, p.stderr


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(ROOT)}


ALLOWED = [
    "scripts/ro_run.sh ls",
    "./scripts/ro_run.sh git diff --stat HEAD~1 HEAD",
    "scripts/ro_run.sh ./.venv/bin/python -m pytest backend/tests/test_dashboard.py -q",
    f"{RUNNER} grep -rn receivable_position backend",
    "scripts/ro_run.sh bash -c 'echo a; echo b'",   # Operatoren NUR in Anführungszeichen (laufen innerhalb der Read-only-Umgebung)
    "scripts/ro_run.sh  id -u",                      # doppeltes Leerzeichen NACH dem Runner: Bash trennt Wörter, Runner läuft (siehe Eigenschaftstest)
    f"{RUNNER} id -u",
]
BLOCKED = [
    # Audit F1: bis HEAD erlaubt (realpath-Auflösung), jetzt zeichengenau verboten. Begründung: Bash löst diese Formen NICHT immer zum Runner auf
    # (`A=x/../scripts/ro_run.sh cmd` ist eine Zuweisung -> `cmd` läuft direkt als root); ausführlich in den Bypass-Tabellen weiter unten.
    "scripts/../scripts/ro_run.sh ls",
    "'scripts/ro_run.sh' ls",
    "../scripts/ro_run.sh ls",
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


# ======================================================================================================================
# Audit-Befund F1 (kritisch): Neuer Hook mit zeichengenauen Runner-Präfixen. Die Tests prüfen die TATSÄCHLICHE Bash-Auswertung, nicht nur check_command.
# Alle ausgeführten Nutzlasten sind harmlos (`id -u`, `echo`); schreibende Befehle werden nirgends ausgeführt.
# ======================================================================================================================
import hashlib
import random
import re
import stat
import itertools


def _load_hook(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NEW = _load_hook(HOOK, "ro_guard_new_under_test")
OLD_REV = "af67304"   # letzter Commit mit dem ALTEN (realpath-basierten) Hook


@pytest.fixture(scope="module")
def old_hook(tmp_path_factory):
    """Kopie des alten Hooks aus der Git-Historie (Mutationsnachweis). RUNNER wird auf den echten Runner gesetzt, weil die Kopie unter tmp_path liegt."""
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_REV}:.claude/hooks/ro_guard.py"], capture_output=True, text=True)
    if r.returncode != 0 or "nur scripts/ro_run.sh darf aufgerufen werden" not in r.stdout:
        pytest.skip(f"alter Hook ({OLD_REV}) nicht aus Git lesbar: {r.stderr.strip()[:100]}")
    d = tmp_path_factory.mktemp("old_hook")
    f = d / "ro_guard_old.py"
    f.write_text(r.stdout, encoding="utf-8")
    mod = _load_hook(f, "ro_guard_old_copy")
    mod.RUNNER = str(RUNNER)
    return mod


def hook_allows(cmd, cwd=ROOT, mod=NEW):
    return mod.check_command(cmd, str(cwd)) is None


def _clean_env():
    env = dict(os.environ)
    for k in ("LD_PRELOAD", "BASH_ENV", "ENV", "RO_RUN_UID"):
        env.pop(k, None)
    return env


def bash_exec(cmd, cwd=ROOT):
    """Führt `bash -c cmd` wirklich aus (Stand-in für die Bash-Auswertung des Claude-Code-Bash-Werkzeugs; dessen Shell wurde hier nicht separat geprüft)."""
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=60, env=_clean_env())


# ---- (a) Tabelle bekannter Bypass-Varianten: ALLE müssen blockiert sein -----------------------------------------------------------------------
P = "scripts/ro_run.sh"
BYPASS = [
    # Variablenzuweisungen als erstes Wort (Kern von F1): Bash startet `id -u` direkt
    "A=x/../scripts/ro_run.sh id -u", 'A="x"/../scripts/ro_run.sh id -u', "A='x'/../scripts/ro_run.sh id -u", "A+=x/../scripts/ro_run.sh id -u",
    "A[0]=x/../scripts/ro_run.sh id -u", "A=x/../scripts/ro_run.sh LD_PRELOAD=/x id -u", "A=x B=y/../scripts/ro_run.sh id -u",
    "A=x B=y C=z/../scripts/ro_run.sh id -u", "A=/../scripts/ro_run.sh id -u", "A=*/../scripts/ro_run.sh id -u", "A=./../scripts/ro_run.sh id -u",
    "A=x/../scripts/ro_run.sh echo hi", "_=x/../scripts/ro_run.sh id -u", "PATH=x/../scripts/ro_run.sh id -u",
    "A=x scripts/ro_run.sh id -u", "A=x ./scripts/ro_run.sh id -u", f"A=x {RUNNER} id -u", "A= scripts/ro_run.sh id -u", "A=x B=y scripts/ro_run.sh id -u",
    f"A={ROOT}/../{ROOT.name}/scripts/ro_run.sh id -u", f"A=x/..{RUNNER} id -u",
    # Pfadformen mit ..-, ~-, Glob-, Brace-Segmenten und Quoting (Hook darf nicht per realpath "gleich" entscheiden)
    "scripts/../scripts/ro_run.sh id -u", "./x/../scripts/ro_run.sh id -u", "~/../scripts/ro_run.sh id -u", "../scripts/ro_run.sh id -u",
    "scripts/./ro_run.sh id -u", "scripts//ro_run.sh id -u", "./scripts/../scripts/ro_run.sh id -u", f"{ROOT}/scripts/../scripts/ro_run.sh id -u",
    f"{ROOT}/./scripts/ro_run.sh id -u", f"{ROOT}//scripts/ro_run.sh id -u", "'scripts/ro_run.sh' id -u", '"scripts/ro_run.sh" id -u',
    "scripts/ro_run.s''h id -u", 'scripts/ro_r"un".sh id -u', f"'{RUNNER}' id -u", f'"{RUNNER}" id -u', "'scripts'/ro_run.sh id -u",
    "s*/ro_run.sh id -u", "scripts/ro_r?n.sh id -u", "scripts/ro_run.s[h] id -u", "{scripts,scripts}/ro_run.sh id -u", "scripts/ro_run.sh{,} id -u",
    "~/scripts/ro_run.sh id -u", "~root/scripts/ro_run.sh id -u", "$PWD/scripts/ro_run.sh id -u", "`pwd`/scripts/ro_run.sh id -u", "$(pwd)/scripts/ro_run.sh id -u",
    "scripts/ro_run.sh' id -u'", 'scripts/ro_run.sh" id -u"', "/scripts/ro_run.sh id -u", "x/scripts/ro_run.sh id -u", "./scripts/ro_run.shx id -u",
    # Whitespace-/Sonderzeichen vor dem Befehl bzw. zwischen Runner und Befehl (Bash/shlex könnten verschieden trennen)
    " scripts/ro_run.sh id -u", "  scripts/ro_run.sh id -u", "\tscripts/ro_run.sh id -u", "\x0bscripts/ro_run.sh id -u", "\x0cscripts/ro_run.sh id -u",
    "\u00a0scripts/ro_run.sh id -u", "\u2028scripts/ro_run.sh id -u", "\u0085scripts/ro_run.sh id -u", "\x00scripts/ro_run.sh id -u",
    "scripts/ro_run.sh\tid -u", "scripts/ro_run.sh\x0bid -u", "scripts/ro_run.sh\x0cid -u", "scripts/ro_run.sh\u00a0id -u", "scripts/ro_run.sh\u2028id -u",
    "scripts/ro_run.sh\u0085id -u", "scripts/ro_run.sh\x00id -u", "scripts/ro_run.sh id\u00a0-u", "scripts/ro_run.sh id -u\x00",
    # Präfix-Wörter und Kompoundformen
    "env scripts/ro_run.sh id -u", "time scripts/ro_run.sh id -u", "exec scripts/ro_run.sh id -u", "command scripts/ro_run.sh id -u",
    "builtin scripts/ro_run.sh id -u", "nohup scripts/ro_run.sh id -u", "! scripts/ro_run.sh id -u", "{ scripts/ro_run.sh id -u; }", "{scripts/ro_run.sh id -u;}",
    "(scripts/ro_run.sh id -u)", "coproc scripts/ro_run.sh id -u", "if scripts/ro_run.sh id -u; then :; fi", "for i in 1; do scripts/ro_run.sh id -u; done",
    "while scripts/ro_run.sh id -u; do :; done", "env A=x scripts/ro_run.sh id -u", "sudo scripts/ro_run.sh id -u", "bash scripts/ro_run.sh id -u", "sh -c 'scripts/ro_run.sh id -u'",
    # Umleitungen vor dem Befehl
    "2>/dev/null scripts/ro_run.sh id -u", ">x scripts/ro_run.sh id -u", "</dev/null scripts/ro_run.sh id -u", "> x scripts/ro_run.sh id -u", "2>&1 scripts/ro_run.sh id -u",
    # Verkettung / Operatoren / Substitutionen
    "cd backend && scripts/ro_run.sh id -u", "cd .. && scripts/ro_run.sh id -u", "true; scripts/ro_run.sh id -u", "true && scripts/ro_run.sh id -u",
    "false || scripts/ro_run.sh id -u", "true | scripts/ro_run.sh id -u", "true & scripts/ro_run.sh id -u",
    "scripts/ro_run.sh id -u; id", "scripts/ro_run.sh id -u && id", "scripts/ro_run.sh id -u || id", "scripts/ro_run.sh id -u | cat", "scripts/ro_run.sh id -u & id",
    "scripts/ro_run.sh id -u;id", "scripts/ro_run.sh id -u&&id", "scripts/ro_run.sh id -u||id", "scripts/ro_run.sh id -u|cat", "scripts/ro_run.sh id -u&", "scripts/ro_run.sh id -u |& cat",
    "scripts/ro_run.sh $(id -u)", "scripts/ro_run.sh `id -u`", "scripts/ro_run.sh <(id -u)", "scripts/ro_run.sh cat >(cat)", "scripts/ro_run.sh id -u >/dev/null",
    "scripts/ro_run.sh id -u 2>/dev/null", "scripts/ro_run.sh id -u >x", "scripts/ro_run.sh cat <x", "scripts/ro_run.sh id -u <<< x", "scripts/ro_run.sh id -u ; ",
    "scripts/ro_run.sh id -u\nid", "scripts/ro_run.sh id -u\rid", "scripts/ro_run.sh id -u\\\nid", "scripts/ro_run.sh id -u # c", "scripts/ro_run.sh echo a#b;id",
    "scripts/ro_run.sh echo \"a\";id", "scripts/ro_run.sh echo 'a';id", "scripts/ro_run.sh echo a'b';id", "scripts/ro_run.sh echo a\"b\"&id",
    "scripts/ro_run.sh echo $HOME", "scripts/ro_run.sh echo ${HOME}", "scripts/ro_run.sh echo \"$(id -u)\"", "scripts/ro_run.sh echo 'a' `id`",
    # erstes Argument mit '-', nur der Runner
    "scripts/ro_run.sh -x", "scripts/ro_run.sh --reuid=0 id -u", "scripts/ro_run.sh -- id -u", "scripts/ro_run.sh '-x'", 'scripts/ro_run.sh "--reuid=0" id',
    "scripts/ro_run.sh -", "scripts/ro_run.sh", "scripts/ro_run.sh ", "scripts/ro_run.sh     ", "./scripts/ro_run.sh", "./scripts/ro_run.sh ", f"{RUNNER}", f"{RUNNER} ",
    "", " ", "\t",
]


@pytest.mark.parametrize("cmd", BYPASS, ids=[repr(c)[:70] for c in BYPASS])
def test_bypass_table_blocked_in_function_and_subprocess(cmd):
    assert NEW.check_command(cmd, str(ROOT)) is not None, cmd
    rc, err = run_hook(bash(cmd))
    assert rc == 2 and "ro_guard" in err


def test_bypass_table_has_no_allowed_entries_and_no_duplicates():
    assert len(set(BYPASS)) == len(BYPASS)
    assert [c for c in BYPASS if hook_allows(c)] == []


@needs_runner
def test_audit_f1_exploit_is_real_in_bash_and_blocked_by_hook():
    """Kernbeweis F1: Bash startet bei `A=x/../scripts/ro_run.sh id -u` KEINEN Runner (uid 0 = root, ungeschützt) -> der Hook muss das ablehnen."""
    cmd = "A=x/../scripts/ro_run.sh id -u"
    assert bash_exec(cmd).stdout.strip() == "0"          # Exploit real: id -u lief direkt als root
    assert bash_exec("scripts/ro_run.sh id -u").stdout.strip() == "65534"   # Kontrolle: so sieht ein Runner-Lauf aus
    assert not hook_allows(cmd)
    # F1-Variante mit Umgebungsmanipulation: LD_PRELOAD wirkt auf einen direkt (nicht über den Runner) gestarteten root-Prozess
    cmd2 = "A=x/../scripts/ro_run.sh LD_PRELOAD=/x id -u"
    assert bash_exec(cmd2).stdout.strip() == "0" and not hook_allows(cmd2)


# ---- relatives Präfix mit cwd != Repo: ein FREMDES scripts/ro_run.sh würde laufen -----------------------------------------------------------
@pytest.fixture
def fake_repo(tmp_path):
    d = tmp_path / "fakerepo"
    (d / "scripts").mkdir(parents=True)
    f = d / "scripts" / "ro_run.sh"
    f.write_text("#!/bin/sh\necho FAKE\n")
    f.chmod(0o755)
    return d


@pytest.mark.parametrize("cmd", ["scripts/ro_run.sh id -u", "./scripts/ro_run.sh id -u"])
def test_relative_runner_blocked_when_cwd_is_not_repo_but_bash_would_run_fake(fake_repo, cmd):
    r = bash_exec(cmd, cwd=fake_repo)
    assert r.stdout.strip() == "FAKE"                    # Beweis: wäre es erlaubt, liefe das fremde Skript statt des Runners
    assert not hook_allows(cmd, cwd=fake_repo)
    assert run_hook({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(fake_repo)}, cwd=fake_repo)[0] == 2
    # Hook-Prozess im Repo, aber JSON-cwd = Wegwerfverzeichnis: es zählt das cwd des Tool-Aufrufs
    assert run_hook({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(fake_repo)}, cwd=ROOT)[0] == 2


def test_absolute_runner_allowed_from_foreign_cwd_and_real_runner_used(fake_repo):
    cmd = f"{RUNNER} id -u"
    assert hook_allows(cmd, cwd=fake_repo)
    assert run_hook({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(fake_repo)}, cwd=fake_repo)[0] == 0
    if _OK:
        # (Wegwerfverzeichnis liegt unter /tmp, das der Runner mit leerem tmpfs überdeckt -> dort kein cd möglich; deshalb fremdes, aber im Runner sichtbares cwd /usr)
        assert bash_exec(cmd, cwd="/usr").stdout.strip() == "65534"      # absoluter Pfad ist cwd-unabhängig -> echter Runner


def test_relative_runner_blocked_in_repo_subdirectory():
    sub = ROOT / "backend"
    assert not hook_allows("scripts/ro_run.sh id -u", cwd=sub)
    assert not hook_allows("./scripts/ro_run.sh id -u", cwd=sub)
    assert not hook_allows("scripts/ro_run.sh id -u", cwd="/")


def test_relative_runner_allowed_via_symlinked_repo_cwd(tmp_path):
    link = tmp_path / "repo_link"
    link.symlink_to(ROOT)
    assert hook_allows("scripts/ro_run.sh id -u", cwd=link)
    if _OK:
        assert bash_exec("scripts/ro_run.sh id -u", cwd=link).stdout.strip() == "65534"


# ---- (b) Eigenschaftstest: Hook erlaubt => Bash startet den Runner -------------------------------------------------------------------------------
_PATHS = [P, "./scripts/ro_run.sh", str(RUNNER), "scripts/../scripts/ro_run.sh", "./x/../scripts/ro_run.sh", "~/../scripts/ro_run.sh", "'scripts/ro_run.sh'",
          '"scripts/ro_run.sh"', "scripts/./ro_run.sh", "scripts//ro_run.sh", "../scripts/ro_run.sh", f"{ROOT}/./scripts/ro_run.sh", "x/../scripts/ro_run.sh"]
_ASSIGN = ["{p}", "A=x/../{p}", 'A="x"/../{p}', "A+=x/../{p}", "A[0]=x/../{p}", "A=x B=y/../{p}", "A=/../{p}", "A=*/../{p}", "A=x {p}", "A= {p}", "A=x/../{p} LD_PRELOAD=/x"]
_SEPS = [" ", "  ", "\t", "\x0b", "\x0c", "\u00a0", "\u2028", "\u0085", "\x00"]
_LEADS = ["", " ", "  ", "\t", "\x0b", "\x0c", "\u00a0", "\u2028", "\u0085", "\x00"]
_TEMPLATES = ["{c}", "time {c}", "exec {c}", "command {c}", "builtin {c}", "nohup {c}", "env {c}", "! {c}", "{{ {c}; }}", "({c})", "coproc {c}",
              "if {c}; then :; fi", "for i in 1; do {c}; done", "2>/dev/null {c}", ">/dev/null {c}", "cd backend && {c}", "true; {c}", "true && {c}", "false || {c}",
              "true | {c}", "true & {c}", "{c}; echo INJECT", "{c} && echo INJECT", "{c} | cat", "{c} &", "{c} >/dev/null"]
PAYLOAD = "id -u"


def generate_variants():
    out = []
    for p, a, sep, tpl in itertools.product(_PATHS, _ASSIGN, _SEPS, _TEMPLATES):
        out.append(tpl.format(c=a.format(p=p) + sep + PAYLOAD))
    for lead, p, tpl in itertools.product(_LEADS, _PATHS, _TEMPLATES):
        out.append(lead + tpl.format(c=p + " " + PAYLOAD))
    # zusätzlich: Verdopplung/Trailing-Whitespace nach dem Runner (legitim) und Brace/Tilde/Glob im ersten Wort
    for p in (P, "./scripts/ro_run.sh", str(RUNNER)):
        out += [f"{p}  {PAYLOAD}", f"{p}   {PAYLOAD} ", f"{p} {PAYLOAD}  "]
    out += ["{scripts,scripts}/ro_run.sh id -u", "s*/ro_run.sh id -u", "~/scripts/ro_run.sh id -u", "scripts/ro_run.sh{,} id -u", "scripts/ro_r?n.sh id -u"]
    seen, uniq = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


VARIANTS = generate_variants()


def find_violations(mod, sample_blocked=300, seed=20240601):
    """Gibt (Verletzungen, Statistik) zurück. Verletzung = Hook erlaubt, aber Bash gibt nicht die Runner-uid 65534 aus.
    ALLE vom Hook erlaubten Varianten werden ausgeführt; von den blockierten nur eine feste Stichprobe (nur zur Information)."""
    allowed = [v for v in VARIANTS if hook_allows(v, mod=mod)]
    blocked = [v for v in VARIANTS if v not in set(allowed)]
    violations = []
    for v in allowed:
        if "\x00" in v:
            violations.append((v, "NUL im Befehl, nicht ausführbar"))
            continue
        r = bash_exec(v)
        if r.stdout.strip() != "65534":
            violations.append((v, r.stdout.strip()[:40]))
    sample = [v for v in random.Random(seed).sample(blocked, min(sample_blocked, len(blocked))) if "\x00" not in v]
    used_runner = sum(1 for v in sample if bash_exec(v).stdout.strip().splitlines()[-1:] == ["65534"])
    return violations, {"variants": len(VARIANTS), "allowed": len(allowed), "blocked_sampled": len(sample), "blocked_sample_that_used_runner": used_runner}


@needs_runner
def test_property_hook_allows_implies_bash_starts_runner(record_property):
    violations, stats = find_violations(NEW)
    for k, v in stats.items():
        record_property(k, v)
    print("\nEIGENSCHAFTSTEST-STATISTIK (neuer Hook):", stats)   # Information: blockierte Varianten, die Bash trotzdem über den Runner startet, sind KEIN Fehler
    assert stats["variants"] > 5000 and stats["allowed"] >= 3     # Raum ist groß genug und enthält die legitimen Formen
    assert violations == [], violations[:10]


@needs_runner
def test_mutation_property_test_is_red_against_old_hook(old_hook):
    """Mutationsnachweis: derselbe Eigenschaftstest gegen den ALTEN Hook (HEAD af67304) findet Verletzungen, u. a. die F1-Zuweisungsform."""
    violations, stats = find_violations(old_hook, sample_blocked=0)
    print("\nEIGENSCHAFTSTEST-STATISTIK (ALTER Hook):", stats, "Verletzungen:", len(violations))
    assert len(violations) > 0
    cmds = {v for v, _ in violations}
    assert "A=x/../scripts/ro_run.sh id -u" in cmds
    assert any(c.startswith(("A=", "A+=", "A[0]=")) and "/../scripts/ro_run.sh" in c for c in cmds)
    assert any(out == "0" for _, out in violations)       # mindestens eine Variante lief direkt als root


_TAILS = ["", "; echo INJECT", " && echo INJECT", " || echo INJECT", " | echo INJECT", " & echo INJECT", " 2>&1; echo INJECT", "; echo INJECT #", " a#b; echo INJECT",
          " 'x'; echo INJECT", ' "x"; echo INJECT', " x'y'; echo INJECT", " x\"y\"&echo INJECT", " ';' echo INJECT", ' ";" echo INJECT', " '&&' echo INJECT",
          " 'a; echo INJECT'", " \"a && echo INJECT\"", " a\\; echo INJECT", " $(echo INJECT)", " `echo INJECT`", " <(echo INJECT)", " >(echo INJECT)",
          " {a,b}", " ~", " *", " a{b,c}; echo INJECT", " 'a' ; echo INJECT", " x ;echo INJECT", " x;echo INJECT", " x&&echo INJECT", " x||echo INJECT", " x|echo INJECT"]


@needs_runner
@pytest.mark.parametrize("p", [P, "./scripts/ro_run.sh", str(RUNNER)])
def test_property_allowed_argument_tails_never_run_a_second_command(p):
    """Für jede vom Hook erlaubte Variante `<runner> echo hello<tail>` darf Bash genau eine Zeile ausgeben, die mit `hello` beginnt
    (ein außerhalb des Runners laufendes `echo INJECT` erzeugte eine eigene Zeile). Blockierte Tails werden hier nicht bewertet."""
    allowed = 0
    for tail in _TAILS:
        cmd = f"{p} echo hello{tail}"
        if not hook_allows(cmd):
            continue
        allowed += 1
        r = bash_exec(cmd)
        lines = r.stdout.splitlines()
        assert len(lines) == 1 and lines[0].startswith("hello") and "INJECT" not in [x.strip() for x in lines], (cmd, r.stdout, r.stderr)
    assert allowed >= 3     # (mind.: leer, ' x'-Tails in Anführungszeichen, Brace/Tilde/Glob-Argumente) – sonst wäre der Test unbeweisend


def test_mutation_bypass_table_old_hook_allows_what_new_blocks(old_hook):
    """Mutationsnachweis: gegen den alten Hook wären die F1-Bypass-Tests ROT (er lässt diese Befehle durch, der neue nicht)."""
    old_allowed = [c for c in BYPASS if hook_allows(c, mod=old_hook)]
    new_allowed = [c for c in BYPASS if hook_allows(c, mod=NEW)]
    assert new_allowed == []
    for must in ("A=x/../scripts/ro_run.sh id -u", 'A="x"/../scripts/ro_run.sh id -u', "A+=x/../scripts/ro_run.sh id -u", "A[0]=x/../scripts/ro_run.sh id -u",
                 "A=x/../scripts/ro_run.sh LD_PRELOAD=/x id -u", "A=/../scripts/ro_run.sh id -u", "A=*/../scripts/ro_run.sh id -u",
                 "scripts/../scripts/ro_run.sh id -u", "./x/../scripts/ro_run.sh id -u", "~/../scripts/ro_run.sh id -u", "'scripts/ro_run.sh' id -u"):
        assert must in old_allowed, f"alter Hook blockierte {must!r} bereits -> Test beweist den Fix nicht"
    print("\nMUTATION: alter Hook lässt", len(old_allowed), "von", len(BYPASS), "Bypass-Einträgen durch; neuer Hook 0")


# ---- (c) Hook als Subprozess: Werkzeugnamen und Eingabeformen ----------------------------------------------------------------------------------
@pytest.mark.parametrize("tool", ["MultiEdit", "WebFetch", "WebSearch", "Monitor", "SendMessage", "Skill", "Task", "Agent", "TodoWrite", "KillShell", "bash", "BASH", "Bash ", " Bash",
                                  "", None, 5, [], {}, True, "mcp", "Write ", "read"])
def test_hook_unknown_tools_fail_closed(tool):
    rc, err = run_hook({"tool_name": tool, "tool_input": {"command": "scripts/ro_run.sh ls", "file_path": "x"}})
    assert rc == 2 and "ro_guard" in err


def test_hook_missing_tool_name_fails_closed():
    assert run_hook({"tool_input": {"command": "scripts/ro_run.sh ls"}})[0] == 2
    assert run_hook({})[0] == 2


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob"])
def test_hook_read_tools_exit_zero(tool):
    assert run_hook({"tool_name": tool, "tool_input": {"file_path": "x", "pattern": "y"}})[0] == 0
    assert run_hook({"tool_name": tool})[0] == 0


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit", "mcp__github__push_files", "mcp__x"])
def test_hook_write_and_mcp_tools_exit_two(tool):
    assert run_hook({"tool_name": tool, "tool_input": {"file_path": "x"}})[0] == 2


@pytest.mark.parametrize("tool_input", [None, [], "scripts/ro_run.sh ls", 5, ["scripts/ro_run.sh ls"], {}, {"command": None}, {"command": 5}, {"command": ["scripts/ro_run.sh", "ls"]},
                                        {"command": {"a": 1}}, {"command": True}, {"cmd": "scripts/ro_run.sh ls"}, {"command": ""}])
def test_hook_bash_with_malformed_tool_input_exits_two(tool_input):
    rc, err = run_hook({"tool_name": "Bash", "tool_input": tool_input, "cwd": str(ROOT)})
    assert rc == 2 and "ro_guard" in err


def test_hook_missing_tool_input_key_exits_two():
    assert run_hook({"tool_name": "Bash", "cwd": str(ROOT)})[0] == 2


# ---- (d) Aktivitätsprotokoll ---------------------------------------------------------------------------------------------------------------------
LOG_FIELDS = {"ts", "tool_name", "agent_type", "session_id", "decision", "reason", "cmd_sha256", "cwd"}


def _env_with_log(path):
    env = dict(os.environ)
    env["LEVENTUM_HOOK_LOG"] = str(path)
    return env


def _read_log(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def test_activity_log_records_allow_and_deny_without_plaintext(tmp_path):
    log = tmp_path / "sub" / "log.jsonl"
    allowed_cmd = "scripts/ro_run.sh echo UNIQUEMARKER_allow_7f3a"
    denied_cmd = "touch UNIQUEMARKER_deny_b81c"
    base = {"agent_type": "independent-reviewer", "session_id": "sess-123", "cwd": str(ROOT)}
    a = run_hook_full({"tool_name": "Bash", "tool_input": {"command": allowed_cmd}, **base}, env=_env_with_log(log))
    d = run_hook_full({"tool_name": "Bash", "tool_input": {"command": denied_cmd}, **base}, env=_env_with_log(log))
    assert a.returncode == 0 and d.returncode == 2
    recs = _read_log(log)
    assert len(recs) == 2 and all(set(r) == LOG_FIELDS for r in recs)
    ra, rd = recs
    assert (ra["decision"], rd["decision"]) == ("allow", "deny")
    assert ra["reason"] == "ok" and rd["reason"] and rd["reason"] != "ok"
    assert ra["cmd_sha256"] == hashlib.sha256(allowed_cmd.encode()).hexdigest()
    assert rd["cmd_sha256"] == hashlib.sha256(denied_cmd.encode()).hexdigest()
    for r in recs:
        assert r["tool_name"] == "Bash" and r["agent_type"] == "independent-reviewer" and r["session_id"] == "sess-123" and r["cwd"] == str(ROOT)
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}", r["ts"]), r["ts"]
    raw = log.read_text(encoding="utf-8")
    assert "UNIQUEMARKER" not in raw and allowed_cmd not in raw and denied_cmd not in raw and "touch" not in raw      # Klartext des Befehls steht nirgends im Protokoll
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert stat.S_IMODE(log.parent.stat().st_mode) == 0o700


def test_activity_log_appends_and_logs_non_bash_and_odd_inputs(tmp_path):
    log = tmp_path / "log.jsonl"
    run_hook_full({"tool_name": "Read", "tool_input": {"file_path": "x"}}, env=_env_with_log(log))
    run_hook_full({"tool_name": "WebFetch", "tool_input": {}}, env=_env_with_log(log))
    run_hook_full({"tool_name": 5, "tool_input": {"command": 7}, "cwd": 3, "agent_type": 1, "session_id": []}, env=_env_with_log(log))
    recs = _read_log(log)
    assert [r["decision"] for r in recs] == ["allow", "deny", "deny"]
    assert recs[0]["cmd_sha256"] is None and recs[0]["tool_name"] == "Read"
    assert recs[2]["tool_name"] is None and recs[2]["agent_type"] is None and recs[2]["session_id"] is None and recs[2]["cwd"] is None and recs[2]["cmd_sha256"] is None


def test_activity_log_hash_covers_non_ascii_command_exactly(tmp_path):
    log = tmp_path / "log.jsonl"
    cmd = "scripts/ro_run.sh\u00a0echo \u00e4\u2028"
    assert run_hook_full(bash(cmd), env=_env_with_log(log)).returncode == 2
    assert _read_log(log)[0]["cmd_sha256"] == hashlib.sha256(cmd.encode("utf-8")).hexdigest()


def test_activity_log_default_path_under_home(tmp_path):
    env = dict(os.environ)
    env.pop("LEVENTUM_HOOK_LOG", None)
    env["HOME"] = str(tmp_path)
    assert run_hook_full(bash("scripts/ro_run.sh echo hi"), env=env).returncode == 0
    f = tmp_path / ".leventum" / "hook-activity.jsonl"
    assert f.is_file() and stat.S_IMODE(f.stat().st_mode) == 0o600 and stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert _read_log(f)[0]["decision"] == "allow"


@pytest.mark.parametrize("kind", ["parent_is_file", "path_is_directory", "empty_env_falls_back_but_unwritable_home"])
def test_unwritable_activity_log_never_changes_decision_or_exit_code(tmp_path, kind):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    env = dict(os.environ)
    if kind == "parent_is_file":
        env["LEVENTUM_HOOK_LOG"] = str(blocker / "log.jsonl")          # Verzeichnisanlage scheitert (NotADirectoryError)
    elif kind == "path_is_directory":
        d = tmp_path / "isdir"
        d.mkdir()
        env["LEVENTUM_HOOK_LOG"] = str(d)                              # open() scheitert (EISDIR)
    else:
        env["LEVENTUM_HOOK_LOG"] = ""
        env["HOME"] = str(blocker)                                     # ~/.leventum nicht anlegbar
    allow = run_hook_full(bash("scripts/ro_run.sh echo hi"), env=env)
    deny = run_hook_full(bash("touch x"), env=env)
    assert allow.returncode == 0 and allow.stderr == ""
    assert deny.returncode == 2 and "ro_guard" in deny.stderr
    assert "Traceback" not in allow.stderr + deny.stderr
    assert run_hook_full({"tool_name": "WebFetch"}, env=env).returncode == 2
    assert run_hook_full("kein json", env=env).returncode == 2


def test_log_function_swallows_all_errors_in_process(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("kaputt")
    monkeypatch.setattr(NEW.os, "open", boom)
    monkeypatch.setenv("LEVENTUM_HOOK_LOG", str(tmp_path / "x.jsonl"))
    NEW.log_activity({"tool_name": "Bash"}, "allow", "ok")        # darf nicht werfen


def test_blocked_decision_is_logged_before_exit_even_for_garbage_cwd(tmp_path):
    log = tmp_path / "l.jsonl"
    assert run_hook_full({"tool_name": "Bash", "tool_input": {"command": "scripts/ro_run.sh ls"}, "cwd": {"x": 1}}, env=_env_with_log(log)).returncode == 2
    assert _read_log(log)[0]["decision"] == "deny" and _read_log(log)[0]["cwd"] is None


# ---- (e) cwd-Handling ------------------------------------------------------------------------------------------------------------------------
def test_cwd_missing_in_json_falls_back_to_hook_process_cwd(fake_repo):
    payload = {"tool_name": "Bash", "tool_input": {"command": "scripts/ro_run.sh echo hi"}}       # KEIN cwd-Feld
    assert run_hook(payload, cwd=ROOT)[0] == 0              # Hook-Prozess im Repo -> relative Form erlaubt
    assert run_hook(payload, cwd=fake_repo)[0] == 2         # Hook-Prozess woanders -> blockiert
    assert run_hook(payload, cwd=ROOT / "backend")[0] == 2


@pytest.mark.parametrize("cwd_value", [None, ""])
def test_cwd_null_or_empty_uses_process_cwd(cwd_value, fake_repo):
    payload = {"tool_name": "Bash", "tool_input": {"command": "./scripts/ro_run.sh echo hi"}, "cwd": cwd_value}
    assert run_hook(payload, cwd=ROOT)[0] == 0
    assert run_hook(payload, cwd=fake_repo)[0] == 2


@pytest.mark.parametrize("cwd_value", [5, ["x"], {"a": 1}, True, "/nonexistent/dir", "/", "relative/dir", "backend"])
def test_cwd_invalid_or_foreign_blocks_relative_runner(cwd_value):
    rc, _ = run_hook({"tool_name": "Bash", "tool_input": {"command": "scripts/ro_run.sh echo hi"}, "cwd": cwd_value}, cwd=ROOT)
    assert rc == 2


def test_cwd_equivalent_spellings_of_repo_are_accepted():
    for spelling in (str(ROOT), str(ROOT) + "/", str(ROOT / "backend" / "..")):
        assert hook_allows("scripts/ro_run.sh echo hi", cwd=spelling), spelling


def test_absolute_runner_does_not_depend_on_cwd():
    for cwd in (None, 5, "/nonexistent", "/"):
        assert run_hook({"tool_name": "Bash", "tool_input": {"command": f"{RUNNER} echo hi"}, "cwd": cwd}, cwd="/")[0] == 0


# ======================================================================================================================
# Nachreview-Lücken (Review G/I/J): FIFO-/Symlink-/Gerätepfad im Protokoll, relatives cwd, Pfadguard ABS_PREFIX, Frontmatter-Kommando + Modul-Schatten,
# Argumentteil-Fuzz gegen echte Bash. Alle ausgeführten Befehle sind harmlos (Attrappen unter tmp_path); keine realen Schreibbefehle.
# ======================================================================================================================
def _hook_subprocess(payload, env, cwd=ROOT, timeout=10):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, cwd=cwd, env=env, timeout=timeout)


# ---- 1. Aktivitätsprotokoll G: Sonderdateien ------------------------------------------------------------------------------------------------------
def test_activity_log_fifo_does_not_hang_and_keeps_decision(tmp_path):
    fifo = tmp_path / "fifo.log"
    os.mkfifo(fifo)                                                    # kein Leser: ein blockierendes open() würde ewig hängen
    env = _env_with_log(fifo)
    allow = _hook_subprocess(bash("scripts/ro_run.sh echo hi"), env)   # subprocess.TimeoutExpired = Hänger = Testfehler
    deny = _hook_subprocess(bash("touch x"), env)
    assert allow.returncode == 0 and allow.stderr == ""
    assert deny.returncode == 2 and "ro_guard" in deny.stderr
    fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        assert os.read(fd, 65536) == b""                               # es wurden keine Daten ins FIFO geschrieben
    finally:
        os.close(fd)


def test_activity_log_fifo_with_active_reader_receives_nothing(tmp_path):
    fifo = tmp_path / "fifo2.log"
    os.mkfifo(fifo)
    rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)                   # Leser vorhanden: open(O_WRONLY|O_NONBLOCK) gelingt, die S_ISREG-Prüfung muss trotzdem greifen
    try:
        r = _hook_subprocess(bash("scripts/ro_run.sh echo hi"), _env_with_log(fifo))
        assert r.returncode == 0
        assert os.read(rfd, 65536) == b""
    finally:
        os.close(rfd)


def test_activity_log_symlink_is_not_followed(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("")
    link = tmp_path / "link.log"
    link.symlink_to(target)
    env = _env_with_log(link)
    assert _hook_subprocess(bash("scripts/ro_run.sh echo hi"), env).returncode == 0
    assert _hook_subprocess(bash("touch x"), env).returncode == 2
    assert target.read_text() == ""                                    # nicht durch den Link geschrieben
    assert link.is_symlink()


def test_activity_log_dangling_symlink_does_not_create_target(tmp_path):
    target = tmp_path / "not_there.txt"
    link = tmp_path / "dangling.log"
    link.symlink_to(target)
    assert _hook_subprocess(bash("scripts/ro_run.sh echo hi"), _env_with_log(link)).returncode == 0
    assert not target.exists()


def test_activity_log_device_path_changes_nothing(tmp_path):
    env = _env_with_log("/dev/null")
    assert _hook_subprocess(bash("scripts/ro_run.sh echo hi"), env).returncode == 0
    assert _hook_subprocess(bash("touch x"), env).returncode == 2
    assert stat.S_ISCHR(os.stat("/dev/null").st_mode)                  # weiterhin Gerät, nicht ersetzt/umbenannt


def test_activity_log_regular_path_still_writes_one_line_per_decision(tmp_path):
    log = tmp_path / "regular.jsonl"
    _hook_subprocess(bash("scripts/ro_run.sh echo hi"), _env_with_log(log))
    _hook_subprocess(bash("touch x"), _env_with_log(log))
    recs = _read_log(log)
    assert [r["decision"] for r in recs] == ["allow", "deny"]


# ---- 2. relatives cwd (Review I) --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("cwd_value", [".", "backend", "./", "..", "x/y"])
@pytest.mark.parametrize("cmd", ["scripts/ro_run.sh echo hi", "./scripts/ro_run.sh echo hi"])
def test_relative_cwd_blocks_relative_runner_with_reason(cwd_value, cmd):
    reason = NEW.check_command(cmd, cwd_value)
    assert reason is not None and "nicht absolut" in reason
    p = run_hook_full({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd_value}, cwd=ROOT)      # auch wenn der Hook-Prozess im Repo läuft
    assert p.returncode == 2 and "nicht absolut" in p.stderr


@pytest.mark.parametrize("cwd_value", [".", "backend", "relative/dir"])
def test_relative_cwd_keeps_absolute_runner_allowed(cwd_value):
    assert NEW.check_command(f"{RUNNER} echo hi", cwd_value) is None
    assert run_hook_full({"tool_name": "Bash", "tool_input": {"command": f"{RUNNER} echo hi"}, "cwd": cwd_value}, cwd="/").returncode == 0


@pytest.mark.parametrize("cwd_value", ["MISSING", None, ""])
def test_missing_null_empty_cwd_behaves_like_process_cwd(cwd_value, monkeypatch, tmp_path):
    cmd = "scripts/ro_run.sh echo hi"
    monkeypatch.chdir(ROOT)
    assert NEW.check_command(cmd) is None if cwd_value == "MISSING" else NEW.check_command(cmd, cwd_value) is None
    monkeypatch.chdir(tmp_path)
    r = NEW.check_command(cmd) if cwd_value == "MISSING" else NEW.check_command(cmd, cwd_value)
    assert r is not None and "Repo-Wurzel" in r and "nicht absolut" not in r


# ---- Wegwerf-Repo mit Hook-Kopie und Runner-Attrappe -------------------------------------------------------------------------------------------------
ATTRAPPE = "#!/bin/sh\nprintf 'ARGS:'\nfor a in \"$@\"; do printf '[%s]' \"$a\"; done\nprintf '\\n'\n"


def _make_repo(base, name):
    repo = Path(base) / name
    (repo / ".claude" / "hooks").mkdir(parents=True)
    (repo / "scripts").mkdir()
    shutil.copy(HOOK, repo / ".claude" / "hooks" / "ro_guard.py")
    runner = repo / "scripts" / "ro_run.sh"
    runner.write_text(ATTRAPPE)
    runner.chmod(0o755)
    return repo


# ---- 3. ABS_PREFIX-Pfadguard --------------------------------------------------------------------------------------------------------------------------
def test_abs_prefix_none_for_path_with_space_ampersand_paren_and_relative_form_only_in_that_repo(tmp_path):
    repo = _make_repo(tmp_path, "a b&c(d)")
    mod = _load_hook(repo / ".claude" / "hooks" / "ro_guard.py", "ro_guard_weird_path")
    assert mod.ABS_PREFIX is None
    assert mod.REPO == os.path.realpath(repo)
    abs_cmd = f"{repo}/scripts/ro_run.sh echo hi"
    r = mod.check_command(abs_cmd, str(repo))
    assert r is not None and "nur scripts/ro_run.sh" in r                      # absolute Form abgelehnt (Grund), selbst im Repo selbst
    assert mod.check_command(abs_cmd, "/") is not None
    assert mod.check_command("scripts/ro_run.sh echo hi", str(repo)) is None   # relative Form nur im Wegwerf-Repo ...
    assert mod.check_command("./scripts/ro_run.sh echo hi", str(repo)) is None
    assert mod.check_command("scripts/ro_run.sh echo hi", str(ROOT)) is not None   # ... nicht im echten Repo
    assert mod.check_command("scripts/ro_run.sh echo hi", str(tmp_path)) is not None
    # Subprozess-Ebene mit der Kopie
    hook_copy = repo / ".claude" / "hooks" / "ro_guard.py"
    run = lambda cmd, cwd: subprocess.run([sys.executable, str(hook_copy)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}),
                                          capture_output=True, text=True, cwd=cwd, env=_env_with_log(tmp_path / "w.log"))
    assert run(abs_cmd, repo).returncode == 2
    assert run("scripts/ro_run.sh echo hi", repo).returncode == 0
    assert run("scripts/ro_run.sh echo hi", tmp_path).returncode == 2
    # Beweis, warum der Guard nötig ist: Bash zerlegt den ungequoteten absoluten Pfad und startet NICHT die Attrappe
    r = bash_exec(abs_cmd, cwd=tmp_path)
    assert not r.stdout.startswith("ARGS:")


def test_abs_prefix_set_and_absolute_form_allowed_for_harmless_path(tmp_path):
    repo = _make_repo(tmp_path, "harmless-repo_1.0")
    mod = _load_hook(repo / ".claude" / "hooks" / "ro_guard.py", "ro_guard_harmless_path")
    assert mod.ABS_PREFIX == os.path.join(mod.REPO, "scripts", "ro_run.sh") + " "
    assert mod.check_command(f"{mod.REPO}/scripts/ro_run.sh echo hi", "/") is None
    r = bash_exec(f"{mod.REPO}/scripts/ro_run.sh echo hi", cwd="/")
    assert r.stdout.strip() == "ARGS:[echo][hi]"


# ---- 4. Frontmatter-Kommando und Modul-Schatten ------------------------------------------------------------------------------------------------------
def test_frontmatter_hook_command_text_and_execution(tmp_path):
    text = (ROOT / ".claude" / "agents" / "independent-reviewer.md").read_text(encoding="utf-8")
    m = re.search(r'command: "(.*)"\n', text)
    assert m
    cmd = m.group(1).replace('\\"', '"')
    assert "python3 -I" in cmd and cmd.rstrip().endswith("|| exit 2") and "$CLAUDE_PROJECT_DIR" in cmd      # Variable bleibt unexpandiert im Kommando (Shell löst auf)
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    env["LEVENTUM_HOOK_LOG"] = str(tmp_path / "fm.log")
    run = lambda c: subprocess.run(["/bin/sh", "-c", cmd], input=json.dumps(bash(c)), capture_output=True, text=True, cwd=tmp_path, env=env, timeout=30)
    ok, bad = run("scripts/ro_run.sh echo hi"), run("touch x")
    assert ok.returncode == 0, ok.stderr
    assert bad.returncode == 2 and "ro_guard" in bad.stderr
    assert [r["decision"] for r in _read_log(tmp_path / "fm.log")] == ["allow", "deny"]
    # absolute Form funktioniert unabhängig vom cwd (cwd=tmp_path ist hier absichtlich NICHT das Repo; die JSON-cwd bleibt ROOT)
    assert run(f"{RUNNER} echo hi").returncode == 0


@pytest.mark.parametrize("shadow", ["shlex", "json"])
def test_isolated_mode_ignores_shadow_modules_next_to_hook(tmp_path, shadow):
    hooks = tmp_path / "hooks_copy"
    hooks.mkdir()
    shutil.copy(HOOK, hooks / "ro_guard.py")
    marker = tmp_path / f"{shadow}.marker"
    (hooks / f"{shadow}.py").write_text(f"open({str(marker)!r}, 'w').write('imported')\n")
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "x"}})
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["LEVENTUM_HOOK_LOG"] = str(tmp_path / "s.log")
    iso = subprocess.run(["python3", "-I", str(hooks / "ro_guard.py")], input=payload, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=30)
    assert iso.returncode == 0, iso.stderr
    assert not marker.exists()                                         # mit -I wird das Schattenmodul NICHT importiert
    subprocess.run(["python3", str(hooks / "ro_guard.py")], input=payload, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=30)
    assert marker.exists()                                             # Kontrolle: ohne -I wird es importiert (Schatten wirkt wirklich)


# ---- 5. Argumentteil-Fuzz gegen echte Bash ---------------------------------------------------------------------------------------------------------
FUZZ_SPECIALS = "!={}~*?[]'\";&|<>()%^:,@-_./"
FUZZ_PLAIN = "abcxyzABC019 "
MIN_ALLOWED = 2000


def _tree(path):
    return sorted((str(Path(d, n).relative_to(path)) for d, ds, fs in os.walk(path) for n in ds + fs))


def test_fuzz_allowed_argument_tails_start_runner_exactly_once_and_nothing_else(tmp_path):
    repo = _make_repo(tmp_path, "fuzzrepo")
    mod = _load_hook(repo / ".claude" / "hooks" / "ro_guard.py", "ro_guard_fuzz_copy")
    assert mod.ABS_PREFIX is not None                                  # normaler Pfad: alle drei Präfixformen testbar
    prefixes = ["scripts/ro_run.sh ", "./scripts/ro_run.sh ", mod.ABS_PREFIX]
    sentdir, markers, home = tmp_path / "sentbin", tmp_path / "markers", tmp_path / "home"
    for d in (sentdir, markers, home):
        d.mkdir()
    s = sentdir / "sentinel"
    s.write_text(f"#!/bin/sh\ntouch {markers}/sentinel_ran\n")
    s.chmod(0o755)
    env = {"PATH": f"{sentdir}:/usr/bin:/bin", "HOME": str(home), "LC_ALL": "C"}
    rng = random.Random(20240611)
    allowed, attempts, blocked = [], 0, 0
    while len(allowed) < MIN_ALLOWED and attempts < 400000:
        attempts += 1
        n = rng.randint(1, 14)
        body = "".join(rng.choice(FUZZ_SPECIALS if rng.random() < 0.45 else FUZZ_PLAIN) for _ in range(n))
        form = rng.random()
        if form < 0.25:
            body = "'" + body.replace("'", "") + "'"
        elif form < 0.4:
            body = '"' + body.replace('"', "") + '"'
        rest = rng.choice(["echo ", "ls ", "id ", "sentinel_arg "]) + body
        cmd = rng.choice(prefixes) + rest
        if mod.check_command(cmd, str(repo)) is None:
            allowed.append(cmd)
        else:
            blocked += 1
    assert len(allowed) >= MIN_ALLOWED, f"Generator liefert zu wenige erlaubte Fälle ({len(allowed)} von {attempts})"
    assert blocked > 0                                                 # der Generator erzeugt auch Verbotenes (sonst wäre der Filter ungeprüft)
    before = _tree(tmp_path)
    for cmd in allowed:
        r = subprocess.run(["bash", "-c", cmd], cwd=repo, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, env=env, timeout=30)
        lines = r.stdout.splitlines()
        assert r.returncode == 0 and len(lines) == 1 and lines[0].startswith("ARGS:"), (cmd, r.returncode, r.stdout, r.stderr)   # Attrappe genau einmal, sonst nichts
        assert not (markers / "sentinel_ran").exists(), cmd
    assert _tree(tmp_path) == before                                   # keine neue Datei (Umleitung, Glob-Nebenwirkung, Sentinel-Marker …)
