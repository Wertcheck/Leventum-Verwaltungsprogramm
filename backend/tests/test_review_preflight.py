"""Tests für scripts/review_preflight.py und scripts/protect_files.sh (nur Wegwerf-Repos unter tmp_path, erfundene Dummy-Inhalte).

Das Skript wird – wie vom Orchestrator vorgesehen – per Stdin ausgeführt (`python -I -`), nicht als Datei.
Ehrliche Grenze: Tests belegen die Prüflogik, nicht die Wirksamkeit des Hooks in einem echten Claude-Code-Subagenten-Lauf."""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "review_preflight.py"
PROTECT = ROOT / "scripts" / "protect_files.sh"
SCRIPT_BYTES = SCRIPT.read_bytes()

pytestmark = pytest.mark.skipif(os.getuid() != 0, reason="Preflight verlangt Besitzer uid 0 – Tests nur als root sinnvoll")

PROFILE_OK = '''---
name: independent-reviewer
description: "dummy"
tools: Read, Grep, Glob, Bash
disallowedTools: Edit, Write, NotebookEdit, Agent
hooks:
  PreToolUse:
    - matcher: "Bash|Edit|Write|NotebookEdit|mcp__.*"
      hooks:
        - type: command
          command: "python3 -I \\"$CLAUDE_PROJECT_DIR/.claude/hooks/ro_guard.py\\" || exit 2"
---

# Dummy
'''
PROFILE_NO_HOOK = PROFILE_OK.split("hooks:")[0] + "---\n\n# Dummy\n"
PROFILE_NO_MCP = PROFILE_OK.replace("|mcp__.*", "")
PROFILE_WRITE = PROFILE_OK.replace("tools: Read, Grep, Glob, Bash", "tools: Read, Grep, Glob, Bash, Write")
PROFILE_NO_BASH = PROFILE_OK.replace("tools: Read, Grep, Glob, Bash", "tools: Read, Grep, Glob")
PROFILE_OTHER_SCRIPT = PROFILE_OK.replace("ro_guard.py", "other.py")
PROFILE_NO_I = PROFILE_OK.replace("python3 -I ", "python3 ")
PROFILE_POST = PROFILE_OK.replace("PreToolUse", "PostToolUse")

GIT_ENV = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}


def git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", str(repo), *args], env=GIT_ENV, capture_output=True, text=True)
    if check:
        assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def sha256(s):
    return hashlib.sha256(s.encode()).hexdigest()


PROTECTED = None


def _protected():
    global PROTECTED
    if PROTECTED is None:
        spec = importlib.util.spec_from_file_location("review_preflight_mod", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        PROTECTED = mod.PROTECTED
    return PROTECTED


def make_repo(tmp_path, profile=PROFILE_OK, trust=True):
    repo = tmp_path / "repo"
    repo.mkdir()
    for p in _protected():
        f = repo / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"dummy {p}\n")
    (repo / "scripts/review_preflight.py").write_bytes(SCRIPT_BYTES)
    (repo / ".claude/agents/independent-reviewer.md").write_text(profile)
    for p in ("scripts/ro_run.sh", "scripts/protect_files.sh"):
        os.chmod(repo / p, 0o755)
    for p in (".claude/skills/s/SKILL.md", ".claude/agents/other.md", ".claude/rules/other.md"):
        (repo / p).parent.mkdir(parents=True, exist_ok=True)
        (repo / p).write_text("x\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init")
    pin = git(repo, "rev-parse", "HEAD")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    if trust:
        write_trust(cfg, {str(repo): {"hasTrustDialogAccepted": True}})
    return repo, pin, cfg


def write_trust(cfg, projects):
    (cfg / ".claude.json").write_text(json.dumps({"projects": projects}))


def run(args, cfg, repo=None, script=None, stdin=None):
    env = {"PATH": os.environ["PATH"], "HOME": str(cfg), "CLAUDE_CONFIG_DIR": str(cfg), "GIT_CONFIG_GLOBAL": "/dev/null"}
    cmd = [sys.executable, "-I", "-" if script is None else str(script), *args]
    if repo is not None and args and args[0] == "check":
        cmd += ["--repo", str(repo)]
    p = subprocess.run(cmd, input=SCRIPT_BYTES if script is None else None, env=env, capture_output=True)
    return p.returncode, p.stdout.decode(), p.stderr.decode()


def check(repo, pin, cfg, **kw):
    return run(["check", "--pin", pin], cfg, repo=repo, **kw)


def expect_fail(repo, pin, cfg, cid):
    rc, out, _ = check(repo, pin, cfg)
    assert rc == 1, out
    assert re.search(rf"^FAIL {re.escape(cid)}", out, re.M), out
    assert "RESULT: BLOCKED" in out
    return out


# ---------- Positivfall ----------
def test_positive_all_ok(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    rc, out, err = check(repo, pin, cfg)
    assert rc == 0, out + err
    assert "RESULT: OK" in out and "FAIL" not in out
    assert "notwendige, nicht hinreichende" in out
    assert "WARN h-immutable[scripts/ro_run.sh]" in out or "h[scripts/ro_run.sh]" in out  # Immutable fehlt: WARN, nie FAIL
    assert "h-immutable[.claude/hooks]" in out  # Verzeichnis wird (nur als WARN) geprüft


def test_pycache_in_hooks_is_warn_only(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / ".claude/hooks/__pycache__").mkdir()
    (repo / ".claude/hooks/__pycache__/x.pyc").write_bytes(b"x")
    rc, out, _ = check(repo, pin, cfg)
    assert rc == 0 and "WARN c-pycache" in out, out


def test_stdin_execution_from_git_object(tmp_path):
    """Beweis: `git show PIN:scripts/review_preflight.py | python3 -I - check …` läuft ohne __file__."""
    repo, pin, cfg = make_repo(tmp_path)
    shown = subprocess.run(["git", "-C", str(repo), "show", f"{pin}:scripts/review_preflight.py"], env=GIT_ENV, capture_output=True, check=True).stdout
    env = {"PATH": os.environ["PATH"], "HOME": str(cfg), "CLAUDE_CONFIG_DIR": str(cfg)}
    p = subprocess.run([sys.executable, "-I", "-", "check", "--pin", pin, "--repo", str(repo)], input=shown, env=env, capture_output=True)
    assert p.returncode == 0, p.stdout.decode() + p.stderr.decode()
    assert "INFO j-selbst" in p.stdout.decode()


def test_default_repo_is_cwd(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    env = {"PATH": os.environ["PATH"], "HOME": str(cfg), "CLAUDE_CONFIG_DIR": str(cfg)}
    p = subprocess.run([sys.executable, "-I", "-", "check", "--pin", pin], input=SCRIPT_BYTES, env=env, cwd=repo, capture_output=True)
    assert p.returncode == 0, p.stdout.decode()


# ---------- (a) PIN ----------
@pytest.mark.parametrize("pin", ["abc1234", "HEAD", "A" * 40, "g" * 40, ""])
def test_pin_format_is_operating_error(tmp_path, pin):
    repo, _, cfg = make_repo(tmp_path)
    rc, out, err = check(repo, pin, cfg)
    assert rc == 2 and "RESULT" not in out


def test_pin_missing_object_blocks(tmp_path):
    repo, _, cfg = make_repo(tmp_path)
    expect_fail(repo, "0" * 40, cfg, "a-pin")


def test_pin_not_a_commit_blocks(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    tree = git(repo, "rev-parse", f"{pin}^{{tree}}")
    expect_fail(repo, tree, cfg, "a-pin")


# ---------- (b) Schutzdateien ----------
@pytest.mark.parametrize("path", ["scripts/ro_run.sh", "CLAUDE.md", ".claude/hooks/ro_guard.py", ".claude/settings.json", "scripts/review_preflight.py"])
def test_protected_content_changed(tmp_path, path):
    repo, pin, cfg = make_repo(tmp_path)
    with open(repo / path, "a") as f:
        f.write("# manipuliert\n")
    expect_fail(repo, pin, cfg, f"b[{path}]")


def test_protected_mode_exec_added_and_removed(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    os.chmod(repo / "CLAUDE.md", 0o755)
    expect_fail(repo, pin, cfg, "b[CLAUDE.md]")
    os.chmod(repo / "CLAUDE.md", 0o644)
    os.chmod(repo / "scripts/ro_run.sh", 0o644)
    out = expect_fail(repo, pin, cfg, "b[scripts/ro_run.sh]")
    assert "b[CLAUDE.md]" not in out.replace("PASS", "")


def test_protected_symlink_forbidden(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / "CLAUDE.md").rename(repo / "elsewhere.md")
    os.symlink("elsewhere.md", repo / "CLAUDE.md")
    expect_fail(repo, pin, cfg, "b[CLAUDE.md]")


def test_protected_parent_dir_symlink_forbidden(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    shutil.move(str(repo / ".claude/rules"), str(repo / "rules_real"))
    os.symlink("../rules_real", repo / ".claude/rules")
    expect_fail(repo, pin, cfg, "b[.claude/rules/60-collaboration.md]")


def test_protected_missing_in_worktree(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / "scripts/check_file_set.py").unlink()
    expect_fail(repo, pin, cfg, "b[scripts/check_file_set.py]")


def test_protected_missing_in_pin(tmp_path):
    """Pin ohne independent-reviewer-static.md (noch nicht committet) → FAIL."""
    repo, _, cfg = make_repo(tmp_path)
    git(repo, "rm", "-q", ".claude/agents/independent-reviewer-static.md")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "rm")
    pin = git(repo, "rev-parse", "HEAD")
    out = expect_fail(repo, pin, cfg, "b[.claude/agents/independent-reviewer-static.md]")
    assert "fehlt im PIN-Commit" in out


# ---------- (c) Dateimengen ----------
@pytest.mark.parametrize("extra", [".claude/hooks/evil.py", ".claude/skills/s/extra.md", ".claude/agents/new.md", ".claude/rules/new.md"])
def test_extra_file_in_claude_dirs(tmp_path, extra):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / extra).write_text("x")
    expect_fail(repo, pin, cfg, "c-dateimenge")


def test_missing_file_in_claude_dirs(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / ".claude/rules/other.md").unlink()
    expect_fail(repo, pin, cfg, "c-dateimenge")


def test_pycache_elsewhere_is_not_ignored(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / ".claude/agents/__pycache__").mkdir()
    (repo / ".claude/agents/__pycache__/x.pyc").write_bytes(b"x")
    expect_fail(repo, pin, cfg, "c-dateimenge")


def test_settings_local_forbidden(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / ".claude/settings.local.json").write_text("{}")
    expect_fail(repo, pin, cfg, "c-settings-local")


# ---------- (d) .git ----------
def test_git_config_fsmonitor_not_executed(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    marker = tmp_path / "MARKER-fsmonitor"
    git(repo, "config", "core.fsmonitor", f"touch {marker}; true")
    git(repo, "config", "core.hooksPath", str(tmp_path / "h"))
    expect_fail(repo, pin, cfg, "d-config")
    assert not marker.exists()


@pytest.mark.parametrize("key,value", [
    ("core.fsmonitor", "true"), ("core.hooksPath", "/x"), ("core.pager", "cat"), ("core.sshCommand", "ssh"),
    ("alias.st", "!echo"), ("filter.x.clean", "cat"), ("diff.x.textconv", "cat"), ("include.path", "/etc/x"),
    ("url.a.insteadOf", "b"), ("credential.helper", "store"),
])
def test_git_config_forbidden_keys(tmp_path, key, value):
    repo, pin, cfg = make_repo(tmp_path)
    git(repo, "config", key, value)
    out = expect_fail(repo, pin, cfg, "d-config")
    assert key.split(".")[0] in out.lower()


def test_git_config_allowlist_ok(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    git(repo, "config", "remote.origin.url", "https://example.invalid/r.git")
    git(repo, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    git(repo, "config", "branch.main.remote", "origin")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "gc.auto", "0")
    rc, out, _ = check(repo, pin, cfg)
    assert rc == 0, out


def test_git_hook_present(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    marker = tmp_path / "MARKER-hook"
    hk = repo / ".git/hooks/pre-commit"
    hk.write_text(f"#!/bin/sh\ntouch {marker}\n")
    os.chmod(hk, 0o755)
    expect_fail(repo, pin, cfg, "d-hooks")
    assert not marker.exists()


def test_git_info_attributes(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / ".git/info").mkdir(exist_ok=True)
    (repo / ".git/info/attributes").write_text("*.txt text\n")
    rc, out, _ = check(repo, pin, cfg)
    assert rc == 0, out
    (repo / ".git/info/attributes").write_text("* filter=evil\n")
    expect_fail(repo, pin, cfg, "d-attributes")
    (repo / ".git/info/attributes").write_text("*.md diff=evil\n")
    expect_fail(repo, pin, cfg, "d-attributes")


# ---------- (e) Index-Flags ----------
@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_index_flags_on_protected_file(tmp_path, flag):
    repo, pin, cfg = make_repo(tmp_path)
    git(repo, "update-index", flag, "CLAUDE.md")
    expect_fail(repo, pin, cfg, "e-indexflags")


def test_index_flag_on_unprotected_file_is_ignored(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    git(repo, "update-index", "--assume-unchanged", ".claude/rules/other.md")
    rc, out, _ = check(repo, pin, cfg)
    assert rc == 0, out


# ---------- (f) Trust ----------
def test_trust_missing_file(tmp_path):
    repo, pin, cfg = make_repo(tmp_path, trust=False)
    out = expect_fail(repo, pin, cfg, "f-trust")
    assert "independent-reviewer-static" in out


def test_trust_false(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    write_trust(cfg, {str(repo): {"hasTrustDialogAccepted": False}})
    expect_fail(repo, pin, cfg, "f-trust")


@pytest.mark.parametrize("projects", [
    lambda repo: {"/some/other/project": {"hasTrustDialogAccepted": True}},
    lambda repo: {str(repo): {"allowedTools": []}},
    lambda repo: {str(repo): {"hasTrustDialogAccepted": "true"}},
    lambda repo: {str(repo / "sub"): {"hasTrustDialogAccepted": True}},  # Unterverzeichnis zählt nicht
])
def test_trust_other_project(tmp_path, projects):
    repo, pin, cfg = make_repo(tmp_path)
    write_trust(cfg, projects(repo))
    expect_fail(repo, pin, cfg, "f-trust")


def test_trust_invalid_json(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (cfg / ".claude.json").write_text("{kaputt")
    expect_fail(repo, pin, cfg, "f-trust")


def test_trust_parent_directory_does_not_count(tmp_path):
    """Vererbung vom Elternverzeichnis ist nicht gemessen -> nur WARN + FAIL (fail closed)."""
    repo, pin, cfg = make_repo(tmp_path, trust=False)
    write_trust(cfg, {str(repo.parent): {"hasTrustDialogAccepted": True}})
    out = expect_fail(repo, pin, cfg, "f-trust")
    assert "WARN f-trust-parent" in out and "Vererbung nicht belegt" in out


def test_trust_explicit_false_beats_parent_true(tmp_path):
    repo, pin, cfg = make_repo(tmp_path, trust=False)
    write_trust(cfg, {str(repo.parent): {"hasTrustDialogAccepted": True}, str(repo): {"hasTrustDialogAccepted": False}})
    expect_fail(repo, pin, cfg, "f-trust")


# ---------- (g) Profil ----------
@pytest.mark.parametrize("profile", [PROFILE_NO_HOOK, PROFILE_NO_MCP, PROFILE_WRITE, PROFILE_NO_BASH, PROFILE_OTHER_SCRIPT, PROFILE_POST, PROFILE_NO_I])
def test_profile_inconsistent(tmp_path, profile):
    repo, pin, cfg = make_repo(tmp_path, profile=profile)
    out = expect_fail(repo, pin, cfg, "g-profil")
    assert "FAIL b[" not in out  # nur das Profil ist das Problem (Inhalt == PIN)


def test_profile_without_frontmatter(tmp_path):
    repo, pin, cfg = make_repo(tmp_path, profile="# kein Frontmatter\n")
    expect_fail(repo, pin, cfg, "g-profil")


def test_frontmatter_parser_variants():
    spec = importlib.util.spec_from_file_location("review_preflight_mod2", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    d = mod.parse_frontmatter_fallback(mod.split_frontmatter(PROFILE_OK))
    assert d["tools"] == ["Read", "Grep", "Glob", "Bash"]
    assert d["pretooluse"][0]["matcher"] == "Bash|Edit|Write|NotebookEdit|mcp__.*"
    assert d["pretooluse"][0]["commands"][0] == 'python3 -I "$CLAUDE_PROJECT_DIR/.claude/hooks/ro_guard.py" || exit 2'
    assert mod.parse_frontmatter_fallback(mod.split_frontmatter(PROFILE_POST))["pretooluse"] == []
    # echtes Profil des Repos wird ebenfalls konsistent erkannt, wenn es dem erwarteten Muster entspricht
    real = (ROOT / ".claude/agents/independent-reviewer.md").read_text(encoding="utf-8")
    rd = mod.parse_frontmatter(mod.split_frontmatter(real))
    assert "Bash" in rd["tools"]


# ---------- (h) Hook-Datei/Runner ----------
def test_hook_file_world_writable(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    os.chmod(repo / ".claude/hooks/ro_guard.py", 0o666)
    expect_fail(repo, pin, cfg, "h[.claude/hooks/ro_guard.py]")


def test_runner_group_writable(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    os.chmod(repo / "scripts/ro_run.sh", 0o775)
    expect_fail(repo, pin, cfg, "h[scripts/ro_run.sh]")


def test_hook_file_foreign_owner(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    os.chown(repo / ".claude/hooks/ro_guard.py", 12345, 0)
    expect_fail(repo, pin, cfg, "h[.claude/hooks/ro_guard.py]")


# ---------- (i) Nutzerkonfiguration ----------
@pytest.mark.parametrize("key", ["LD_PRELOAD", "BASH_ENV", "ENV", "PATH", "PYTHONPATH", "PYTHONSTARTUP", "SHELLOPTS", "LD_LIBRARY_PATH"])
def test_user_settings_dangerous_env(tmp_path, key):
    repo, pin, cfg = make_repo(tmp_path)
    (cfg / "settings.json").write_text(json.dumps({"env": {key: "x"}}))
    expect_fail(repo, pin, cfg, "i-usersettings")


def test_user_settings_harmless_and_hooks_warn(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (cfg / "settings.json").write_text(json.dumps({"env": {"FOO": "1"}, "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}))
    rc, out, _ = check(repo, pin, cfg)
    assert rc == 0 and "WARN i-userhooks" in out, out


def test_user_settings_invalid_json(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (cfg / "settings.json").write_text("{kaputt")
    expect_fail(repo, pin, cfg, "i-usersettings")


# ---------- (j) Selbstbezug ----------
def test_self_check_when_run_from_file(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    same = tmp_path / "same.py"
    same.write_bytes(SCRIPT_BYTES)
    rc, out, _ = check(repo, pin, cfg, script=same)
    assert rc == 0 and "PASS j-selbst" in out, out
    other = tmp_path / "other.py"
    other.write_bytes(SCRIPT_BYTES + b"\n# anders\n")
    rc, out, _ = check(repo, pin, cfg, script=other)
    assert rc == 1 and "FAIL j-selbst" in out


# ---------- nonce / verify ----------
def test_nonce_format(tmp_path):
    rc, out, _ = run(["nonce"], tmp_path)
    assert rc == 0
    d = json.loads(out)
    n = d["nonce"]
    assert re.fullmatch(r"[0-9a-f]{32}", n)
    assert d["probe_cmd"] == f"scripts/ro_run.sh echo PROBE-{n}"
    assert d["canary_cmd"] == f"echo CANARY-{n}"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", d["ts"])
    assert d["probe_sha256"] == sha256(d["probe_cmd"]) and d["canary_sha256"] == sha256(d["canary_cmd"])
    assert "HOOK INAKTIV – Review ungültig" in d["prompt"] and f"CANARY-{n}" in d["prompt"] and "allererste Aktion" in d["prompt"]
    assert run(["nonce"], tmp_path)[1] != out
    rc, txt, _ = run(["nonce", "--text"], tmp_path)
    assert rc == 0 and txt.startswith("Führe als allererste Aktion")


NONCE = "ab" * 16


def entry(cmd, decision, sid="s1", agent="independent-reviewer", tool="Bash"):
    return {"ts": "2026-01-01T00:00:00Z", "tool_name": tool, "agent_type": agent, "session_id": sid, "decision": decision,
            "reason": "r", "cmd_sha256": sha256(cmd), "cwd": "/x"}


PROBE = f"scripts/ro_run.sh echo PROBE-{NONCE}"
CANARY = f"echo CANARY-{NONCE}"


def verify(tmp_path, entries, raw_extra=""):
    log = tmp_path / "log.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in entries) + raw_extra)
    return run(["verify", "--nonce", NONCE, "--log", str(log)], tmp_path)


def test_verify_complete(tmp_path):
    rc, out, _ = verify(tmp_path, [entry("other", "allow"), entry(PROBE, "allow"), entry(CANARY, "deny")], raw_extra="kein json\n")
    assert rc == 0 and "RESULT: OK" in out


@pytest.mark.parametrize("entries", [
    [entry(PROBE, "allow")],  # Canary-Deny fehlt
    [entry(CANARY, "deny")],  # Probe fehlt
    [],
    [entry(PROBE, "allow"), entry(CANARY, "deny"), entry(CANARY, "allow")],  # Canary ausgeführt
    [entry(PROBE, "allow"), entry(CANARY, "allow")],
    [entry(PROBE, "allow"), entry(CANARY, "deny", sid="s2")],  # andere Session
    [entry(PROBE, "allow", agent="general-purpose"), entry(CANARY, "deny")],  # falscher Agent
    [entry(PROBE, "allow", tool="Read"), entry(CANARY, "deny")],
    [entry(PROBE, "deny"), entry(CANARY, "deny")],  # Probe nicht erlaubt
    [entry(PROBE, "allow"), entry(PROBE, "allow"), entry(CANARY, "deny")],  # doppelt
])
def test_verify_failures(tmp_path, entries):
    rc, out, _ = verify(tmp_path, entries)
    assert rc == 1 and "NICHT nachgewiesen" in out and "RESULT: OK" not in out


def test_verify_missing_log_and_bad_nonce(tmp_path):
    rc, out, _ = run(["verify", "--nonce", NONCE, "--log", str(tmp_path / "nope.jsonl")], tmp_path)
    assert rc == 1 and "NICHT nachgewiesen" in out
    rc, _, _ = run(["verify", "--nonce", "xyz", "--log", str(tmp_path / "nope.jsonl")], tmp_path)
    assert rc == 2


# ---------- Phase 1: Konfiguration vor jedem Repo-git; Marker-Beweise ----------
def _mod():
    spec = importlib.util.spec_from_file_location("review_preflight_mod3", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hostile(repo, tmp_path, kind, marker):
    cmd = f"touch {marker}"
    if kind == "fsmonitor":
        git(repo, "config", "core.fsmonitor", cmd)
    elif kind == "hooksPath":
        hd = tmp_path / "hp"
        hd.mkdir()
        for h in ("reference-transaction", "post-checkout", "pre-commit"):
            (hd / h).write_text(f"#!/bin/sh\n{cmd}\n")
            os.chmod(hd / h, 0o755)
        git(repo, "config", "core.hooksPath", str(hd))
    elif kind == "alias":
        git(repo, "config", "alias.cat-file", f"!{cmd}")
    elif kind == "filter":
        git(repo, "config", "filter.x.clean", cmd)
        git(repo, "config", "filter.x.process", cmd)
        (repo / ".gitattributes").write_text("* filter=x\n")
    elif kind == "include":
        inc = tmp_path / "inc.cfg"
        inc.write_text(f"[core]\n\tfsmonitor = {cmd}\n")
        git(repo, "config", "include.path", str(inc))
    elif kind == "partialclone":
        git(repo, "config", "extensions.partialclone", "origin")
        git(repo, "config", "remote.origin.url", f"ext::{cmd}")
        git(repo, "config", "remote.origin.promisor", "true")
    elif kind == "ext-url":
        git(repo, "config", "remote.origin.url", f"ext::{cmd}")
    elif kind == "pushurl-ext":
        git(repo, "config", "remote.origin.pushurl", f"ext::{cmd}")


@pytest.mark.parametrize("kind", ["fsmonitor", "hooksPath", "alias", "filter", "include", "partialclone", "ext-url", "pushurl-ext"])
def test_hostile_config_marker_not_created(tmp_path, kind):
    repo, pin, cfg = make_repo(tmp_path)
    marker = tmp_path / f"MARKER-{kind}"
    _hostile(repo, tmp_path, kind, marker)
    out = expect_fail(repo, pin, cfg, "d-config")
    assert not marker.exists()
    assert "KEIN git im Repository" in out


def test_config_check_runs_before_any_repo_git_even_with_missing_pin(tmp_path):
    """Reihenfolge: fsmonitor-Marker + fehlendes PIN-Objekt -> FAIL d-config (nicht a-pin), kein Marker."""
    repo, _, cfg = make_repo(tmp_path)
    marker = tmp_path / "MARKER-order"
    git(repo, "config", "core.fsmonitor", f"touch {marker}")
    out = expect_fail(repo, "0" * 40, cfg, "d-config")
    assert "a-pin" not in out and not marker.exists()


def test_no_repo_git_call_before_config_check(tmp_path, monkeypatch):
    repo, pin, cfg = make_repo(tmp_path)
    mod = _mod()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("HOME", str(cfg))
    monkeypatch.setattr(sys, "argv", ["-"])  # wie bei Ausführung aus dem Objekt: kein Selbstvergleich
    calls = []
    real = mod.git
    monkeypatch.setattr(mod, "git", lambda cwd, *a: (calls.append((cwd, a[0])), real(cwd, *a))[1])
    git(repo, "config", "core.fsmonitor", "true")
    assert mod.check(pin, str(repo)) == 1
    assert [c for c in calls if c[0] == str(repo)] == []
    assert calls and calls[0][0] == "/" and calls[0][1] == "config"
    calls.clear()
    git(repo, "config", "--unset", "core.fsmonitor")
    assert mod.check(pin, str(repo)) == 0
    assert calls[0] == ("/", "config") and calls[1][0] == str(repo)


@pytest.mark.parametrize("key,value", [
    ("extensions.partialclone", "origin"), ("extensions.worktreeConfig", "true"), ("extensions.relativeWorktrees", "true"),
    ("remote.origin.promisor", "true"), ("remote.origin.partialclonefilter", "blob:none"), ("core.filemode", "maybe"),
    ("includeIf.gitdir:/x.path", "/y"), ("uploadpack.packObjectsHook", "x"),
])
def test_config_stricter_keys_and_values(tmp_path, key, value):
    repo, pin, cfg = make_repo(tmp_path)
    git(repo, "config", key, value)
    expect_fail(repo, pin, cfg, "d-config")


@pytest.mark.parametrize("key,value", [
    ("core.filemode", "false"), ("extensions.objectformat", "sha1"), ("pack.threads", "1"), ("receive.denyDeletes", "true"),
    ("remote.origin.pushurl", "https://example.invalid/r.git"), ("branch.main.rebase", "true"),
])
def test_config_allowed_keys(tmp_path, key, value):
    repo, pin, cfg = make_repo(tmp_path)
    if key.startswith("extensions."):
        git(repo, "config", "core.repositoryformatversion", "1")  # extensions.* setzt Format 1 voraus
    git(repo, "config", key, value)
    rc, out, _ = check(repo, pin, cfg)
    assert rc == 0, out


def test_config_worktree_file_and_dotgit_structure(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / ".git/config.worktree").write_text("[core]\n")
    expect_fail(repo, pin, cfg, "d-config")
    (repo / ".git/config.worktree").unlink()
    (repo / ".git").rename(tmp_path / "realgit")
    (repo / ".git").write_text(f"gitdir: {tmp_path / 'realgit'}\n")  # gitdir-Verweis (Datei)
    out = expect_fail(repo, pin, cfg, "d-git")
    assert "KEIN git im Repository" in out
    (repo / ".git").unlink()
    os.symlink(tmp_path / "realgit", repo / ".git")
    expect_fail(repo, pin, cfg, "d-git")


def test_attributes_merge_and_replace_and_alternates(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / ".git/info").mkdir(exist_ok=True)
    (repo / ".git/info/attributes").write_text("* merge=evil\n")
    expect_fail(repo, pin, cfg, "d-attributes")
    (repo / ".git/info/attributes").unlink()
    (repo / ".git/objects/info").mkdir(exist_ok=True)
    (repo / ".git/objects/info/alternates").write_text(str(tmp_path / "other-objects") + "\n")
    expect_fail(repo, pin, cfg, "d-alternates")


def _replace_setup(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    orig = git(repo, "rev-parse", f"{pin}:scripts/review_preflight.py")
    fake = b'print("HACKED-OK")\nprint("RESULT: OK")\n'
    fake_sha = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=fake, env=GIT_ENV, capture_output=True,
                              check=True).stdout.decode().strip()
    git(repo, "replace", orig, fake_sha)
    return repo, pin, cfg, orig, fake


def test_replace_ref_check_blocks(tmp_path):
    repo, pin, cfg, _, _ = _replace_setup(tmp_path)
    expect_fail(repo, pin, cfg, "d-replace")


def test_replace_ref_gap_and_anchor_flow(tmp_path):
    """Beweis der Lücke: einfaches `git show PIN:...` liefert das ERSETZTE Objekt; der anchor-cmd-Ablauf (--no-replace-objects + Blob-Hash) den echten."""
    repo, pin, cfg, orig, fake = _replace_setup(tmp_path)
    shown = subprocess.run(["git", "-C", str(repo), "show", f"{pin}:scripts/review_preflight.py"], env=GIT_ENV, capture_output=True, check=True).stdout
    assert shown == fake  # Lücke: Ersatzobjekt
    real = subprocess.run(["git", "-C", str(repo), "--no-replace-objects", "cat-file", "blob", f"{pin}:scripts/review_preflight.py"], env=GIT_ENV,
                          capture_output=True, check=True).stdout
    assert real == SCRIPT_BYTES
    rc, script, _ = run(["anchor-cmd", "--pin", pin, "--blob", orig], tmp_path)
    assert rc == 0
    env = {"HOME": str(cfg), "CLAUDE_CONFIG_DIR": str(cfg), "PATH": os.environ["PATH"]}
    p = subprocess.run(["bash", "-c", script], cwd=repo, env=env, capture_output=True, text=True)
    assert "HACKED" not in p.stdout
    assert p.returncode == 1 and "FAIL d-replace" in p.stdout  # echtes Skript lief und blockiert wegen refs/replace


def test_anchor_flow_ok_and_blob_mismatch(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    blob = git(repo, "rev-parse", f"{pin}:scripts/review_preflight.py")
    env = {"HOME": str(cfg), "CLAUDE_CONFIG_DIR": str(cfg), "PATH": os.environ["PATH"]}
    rc, script, _ = run(["anchor-cmd", "--pin", pin, "--blob", blob], tmp_path)
    assert rc == 0 and "--no-replace-objects" in script and "hash-object --no-filters" in script and "python3 -I" in script
    assert "GIT_NO_LAZY_FETCH=1" in script and "GIT_CONFIG_GLOBAL=/dev/null" in script and "mktemp -d" in script
    p = subprocess.run(["bash", "-c", script], cwd=repo, env=env, capture_output=True, text=True)
    assert p.returncode == 0 and "RESULT: OK" in p.stdout and "PASS j-selbst" in p.stdout, p.stdout + p.stderr
    rc, bad, _ = run(["anchor-cmd", "--pin", pin, "--blob", "0" * 40], tmp_path)
    p = subprocess.run(["bash", "-c", bad], cwd=repo, env=env, capture_output=True, text=True)
    assert p.returncode == 1 and "RESULT" not in p.stdout and "Blob-Hash" in p.stderr


def test_anchor_cmd_argument_validation(tmp_path):
    assert run(["anchor-cmd", "--pin", "abc"], tmp_path)[0] == 2
    assert run(["anchor-cmd", "--pin", "a" * 40, "--blob", "XYZ"], tmp_path)[0] == 2
    rc, out, _ = run(["anchor-cmd", "--pin", "a" * 40], tmp_path)
    assert rc == 0 and "<BLOB-HASH-VOM-ORCHESTRATOR>" in out


def test_config_allowlist_matches_check_file_set():
    """Drift-Wächter: gemeinsame Teile der Allowlist == scripts/check_file_set.py; Preflight darf nur strenger sein."""
    cfs_path = ROOT / "scripts" / "check_file_set.py"
    spec = importlib.util.spec_from_file_location("cfs_mod", cfs_path)
    cfs = importlib.util.module_from_spec(spec)
    sys.modules["cfs_mod"] = cfs
    try:
        spec.loader.exec_module(cfs)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"check_file_set nicht ladbar: {type(e).__name__}")
    if not hasattr(cfs, "CONFIG_ALLOW_EXACT") or not hasattr(cfs, "CONFIG_ALLOW_RE"):
        pytest.skip("check_file_set hat die erwarteten Allowlist-Namen nicht (Drift prüfen!)")
    mod = _mod()
    assert set(mod.CONFIG_ALLOW_EXACT) - {"extensions.objectformat", "extensions.compatobjectformat"} == set(cfs.CONFIG_ALLOW_EXACT)
    pats = {r.pattern for r in mod.CONFIG_ALLOW_RE}
    assert pats == {r.pattern for r in cfs.CONFIG_ALLOW_RE} - {r"extensions\..+"}
    assert mod.ATTR_BAD_RE.pattern == cfs.ATTR_BAD_RE.pattern


# ---------- (c) Inhalt/Modus des gesamten .claude-Baums ----------
@pytest.mark.parametrize("path", [".claude/rules/other.md", ".claude/agents/other.md", ".claude/skills/s/SKILL.md"])
def test_unprotected_claude_file_content_changed(tmp_path, path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / path).write_text("manipuliert\n")
    out = expect_fail(repo, pin, cfg, "c-inhalt")
    assert path in out and "FAIL c-dateimenge" not in out


def test_unprotected_claude_file_mode_changed(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    os.chmod(repo / ".claude/rules/other.md", 0o755)
    out = expect_fail(repo, pin, cfg, "c-inhalt")
    assert "Modus" in out


def test_claude_file_symlink_to_file_fails(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    f = repo / ".claude/rules/other.md"
    f.unlink()
    (tmp_path / "t.md").write_text("x\n")  # gleicher Inhalt wie im PIN
    os.symlink(tmp_path / "t.md", f)
    out = expect_fail(repo, pin, cfg, "c-inhalt")
    assert "symlink" in out


def test_claude_toplevel_extra_file_fails(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (repo / ".claude/extra.json").write_text("{}")
    expect_fail(repo, pin, cfg, "c-dateimenge")


def test_claude_unchanged_ok(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    rc, out, _ = check(repo, pin, cfg)
    assert "PASS c-inhalt" in out and "PASS c-dateimenge" in out


# ---------- (i) Nutzer-Agent-Schatten, Settings, Managed ----------
@pytest.mark.parametrize("name", ["independent-reviewer.md", "independent-reviewer-static.md"])
def test_user_agent_shadow_fails(tmp_path, name):
    repo, pin, cfg = make_repo(tmp_path)
    (cfg / "agents").mkdir()
    (cfg / "agents" / name).write_text("---\nname: independent-reviewer\ntools: Bash\n---\n")
    expect_fail(repo, pin, cfg, "i-usershadow")


def test_user_agent_other_name_is_fine(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (cfg / "agents").mkdir()
    (cfg / "agents" / "something-else.md").write_text("x\n")
    rc, out, _ = check(repo, pin, cfg)
    assert rc == 0, out


@pytest.mark.parametrize("settings", [{"disableAllHooks": True}, {"allowManagedHooksOnly": True}])
def test_user_settings_hooks_disabled_fails(tmp_path, settings):
    repo, pin, cfg = make_repo(tmp_path)
    (cfg / "settings.json").write_text(json.dumps(settings))
    expect_fail(repo, pin, cfg, "i-usersettings")


def test_user_settings_wide_bash_allow_warns(tmp_path):
    repo, pin, cfg = make_repo(tmp_path)
    (cfg / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(*)", "Read"]}}))
    rc, out, _ = check(repo, pin, cfg)
    assert rc == 0 and "WARN i-userperms" in out, out


def test_managed_settings_warn_only_key_names(tmp_path):
    mod = _mod()
    f = tmp_path / "managed-settings.json"
    f.write_text(json.dumps({"permissions": {"allow": ["GEHEIMER-WERT"]}, "hooks": {}}))
    d = tmp_path / "m.d"
    d.mkdir()
    (d / "10.json").write_text("{kaputt")
    found = mod.managed_findings([str(f), str(tmp_path / "fehlt.json")], str(d))
    assert [(p, k) for p, k in found] == [(str(f), ["hooks", "permissions"]), (str(d / "10.json"), ["<nicht auswertbar>"])]
    assert "GEHEIMER-WERT" not in repr(found)
    assert mod.managed_findings([str(tmp_path / "nix")], str(tmp_path / "nix.d")) == []


# ---------- (g) Fallback-Parser entfernt Escapes ----------
def test_fallback_parser_unescapes_double_quotes():
    mod = _mod()
    d = mod.parse_frontmatter_fallback(mod.split_frontmatter(PROFILE_OK))
    assert d["pretooluse"][0]["commands"] == [mod.HOOK_CMD]


def test_matcher_covers_documented_as_approximation():
    mod = _mod()
    assert "NÄHERUNG" in mod.matcher_covers.__doc__
    assert mod.matcher_covers("Bash|Edit|Write|NotebookEdit|mcp__.*", "mcp__github__x")
    assert not mod.matcher_covers("Bash", "Edit")


# ---------- verify --issued ----------
def test_verify_issued_timestamps(tmp_path):
    def with_ts(e, ts):
        e = dict(e)
        e["ts"] = ts
        return e
    ok = [with_ts(entry(PROBE, "allow"), "2026-01-01T00:00:05Z"), with_ts(entry(CANARY, "deny"), "2026-01-01T00:00:06Z")]
    log = tmp_path / "l.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in ok))

    def v(issued):
        return run(["verify", "--nonce", NONCE, "--log", str(log), "--issued", issued], tmp_path)
    assert v("2026-01-01T00:00:05Z")[0] == 0
    rc, out, _ = v("2026-01-01T00:00:06Z")  # Probe liegt vor dem Ausgabezeitpunkt
    assert rc == 1 and "vor dem nonce-Zeitpunkt" in out
    assert v("2027-01-01T00:00:00Z")[0] == 1
    assert v("kein-datum")[0] == 2
    log.write_text("".join(json.dumps(with_ts(e, "murks")) + "\n" for e in ok))
    assert v("2026-01-01T00:00:00Z")[0] == 1  # ungültiges ts + --issued -> fail
    assert run(["verify", "--nonce", NONCE, "--log", str(log)], tmp_path)[0] == 0  # ohne --issued unverändert


def test_verify_documents_main_limit():
    mod = _mod()
    doc = mod.cmd_verify.__doc__
    assert "Nonce steht im Prompt" in doc and "session_id" in doc and "Hauptprozesses" in doc


# ---------- protect_files.sh ----------
def _chattr_works(tmp_path):
    if not shutil.which("chattr") or not shutil.which("lsattr"):
        return False
    probe = tmp_path / "probe"
    probe.write_text("x")
    try:
        if subprocess.run(["chattr", "+i", str(probe)], capture_output=True).returncode != 0:
            return False
        ok = "i" in subprocess.run(["lsattr", "-d", str(probe)], capture_output=True, text=True).stdout.split()[0]
        return ok
    finally:
        subprocess.run(["chattr", "-i", str(probe)], capture_output=True)


def test_protect_bash_syntax():
    assert subprocess.run(["bash", "-n", str(PROTECT)], capture_output=True).returncode == 0


def test_protect_usage_error(tmp_path):
    p = subprocess.run(["bash", str(PROTECT), "--root", str(tmp_path), "bogus"], capture_output=True)
    assert p.returncode == 2


def test_protect_not_root_exits_3(tmp_path):
    if not shutil.which("setpriv"):
        pytest.skip("setpriv nicht vorhanden")
    p = subprocess.run(["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", "bash", "-s", "--", "--root", "/nonexistent", "protect"],
                       input=PROTECT.read_bytes(), capture_output=True)
    assert p.returncode == 3, p.stderr


def test_protect_cycle_on_throwaway_files(tmp_path):
    if not _chattr_works(tmp_path):
        pytest.skip("chattr +i auf tmp_path nicht unterstützt/wirksam")
    root = tmp_path / "root"
    for p in _protected():
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_text("x")
    script = ["bash", str(PROTECT), "--root", str(root)]
    try:
        assert subprocess.run([*script, "status"], capture_output=True).returncode == 1
        r = subprocess.run([*script, "protect"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert subprocess.run([*script, "status"], capture_output=True).returncode == 0
        with pytest.raises(PermissionError):
            (root / "CLAUDE.md").write_text("änderung")
        with pytest.raises(PermissionError):
            (root / ".claude/hooks/neu.py").write_text("x")
        assert (root / "CLAUDE.md").read_text() == "x"
    finally:
        subprocess.run([*script, "unprotect"], capture_output=True)
    assert subprocess.run([*script, "status"], capture_output=True).returncode == 1
    (root / "CLAUDE.md").write_text("wieder schreibbar")


def test_protect_missing_file_exits_1_and_changes_nothing(tmp_path):
    if not _chattr_works(tmp_path):
        pytest.skip("chattr +i auf tmp_path nicht unterstützt/wirksam")
    root = tmp_path / "root"
    for p in _protected():
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_text("x")
    (root / ".claude/agents/independent-reviewer-static.md").unlink()
    script = ["bash", str(PROTECT), "--root", str(root)]
    try:
        assert subprocess.run([*script, "protect"], capture_output=True).returncode == 1
        (root / "CLAUDE.md").write_text("noch schreibbar")  # nichts wurde geschützt
    finally:
        subprocess.run([*script, "unprotect"], capture_output=True)
