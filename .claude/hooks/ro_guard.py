#!/usr/bin/env python3
"""PreToolUse-Hook für Prüf-Agenten (Bash): erlaubt AUSSCHLIESSLICH `scripts/ro_run.sh <befehl…>` als einzigen Befehl.

Zweite Schicht (Defense in Depth) vor der OS-Isolation von scripts/ro_run.sh: Jeder andere Bash-Aufruf wird mit Exit-Code 2 blockiert.
Lesart laut Claude-Code-Doku: Hooks sind ein Backstop, keine Sandbox – die eigentliche Schreibsperre liefert ro_run.sh (Read-only-Mounts, kein root,
keine Capabilities, kein Netz). Der Hook garantiert nur, dass Prüf-Agenten diesen Weg nicht verlassen – UND NUR, WENN ER LÄUFT: Frontmatter-Hooks
sind in nicht vertrauten Workspaces aus (Audit, gemessen). Deshalb gibt es zusätzlich scripts/review_preflight.py (Trust-/Integritäts-/Aktivitätsnachweis).

Prüfung (Audit-Befund F1): Der Befehl muss mit EINEM der drei zulässigen Runner-Präfixe beginnen – zeichengenau, ohne führende Leerzeichen:
    `scripts/ro_run.sh `   `./scripts/ro_run.sh `   `<absoluter Pfad dieses Repos>/scripts/ro_run.sh `
Es wird NICHT mehr geprüft, wohin das erste Wort per realpath auflöst: Bash behandelt `A=x/../scripts/ro_run.sh cmd` als Variablenzuweisung und startet
`cmd` DIREKT (ohne Runner). Alles, was nicht exakt mit einem Präfix beginnt (Variablenzuweisungen, `..`, `~`, Anführungszeichen, `env`, `time`, `{`, `!` …), wird
abgelehnt. Relative Präfixe gelten nur, wenn das Arbeitsverzeichnis des Aufrufs genau das Repo ist (sonst würde ein fremdes `scripts/ro_run.sh` laufen).
Der Rest (Argumente) darf weder `$`, Backtick, Backslash, `#`, Steuerzeichen/Nicht-ASCII noch Shell-Operatoren/Umleitungen enthalten.
Fail closed: unlesbare Eingabe, unbekannte Werkzeuge, Parserzweifel → blockieren.
Aktivitätsprotokoll: Jede Entscheidung wird (ohne Befehlstext, nur SHA-256) an ${LEVENTUM_HOOK_LOG} bzw. ~/.leventum/hook-activity.jsonl angehängt;
Protokollfehler ändern die Entscheidung nie. Das Protokoll beweist nur, DASS der Hook lief (Gegenprobe scripts/review_preflight.py verify), nicht dass ein root-Agent
es nicht fälschen könnte.
Eingabe: JSON auf stdin (tool_name, tool_input.command, cwd, agent_type, session_id). Ausgabe: Exit 0 = erlaubt, Exit 2 = blockiert (Grund auf stderr)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import sys
import time

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
RUNNER = os.path.join(REPO, "scripts", "ro_run.sh")
REL_PREFIXES = ("scripts/ro_run.sh ", "./scripts/ro_run.sh ")
# Der absolute Präfix wird nur akzeptiert, wenn der Repo-Pfad keine Zeichen enthält, die Bash anders zerlegt (Leerzeichen, &, ;, ( … ) – sonst nur die relativen Formen
ABS_PREFIX = RUNNER + " " if re.fullmatch(r"[A-Za-z0-9_./-]+", RUNNER) else None
FORBIDDEN_CHARS = ("$", "`", "\n", "\r", "\\", "\x00", "#")
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}


def deny(msg: str) -> int:
    print(f"ro_guard: blockiert – {msg}. Erlaubt ist nur: scripts/ro_run.sh <befehl…>", file=sys.stderr)
    return 2


def _same_dir(a: str, b: str) -> bool:
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except Exception:
        return False


def check_command(cmd: str, cwd: str | None = None) -> str | None:
    """Gibt None zurück, wenn erlaubt, sonst den Ablehnungsgrund."""
    if not isinstance(cmd, str) or not cmd or not cmd.strip():
        return "leerer Befehl"
    if any(c in cmd for c in FORBIDDEN_CHARS):
        return "Shell-Expansion/Zeilenumbruch/Escape im Befehl nicht erlaubt"
    if any(ord(c) < 32 or ord(c) >= 127 for c in cmd):  # Steuerzeichen (Tab, VT, FF …) und Nicht-ASCII (NBSP, U+2028 …): Bash/shlex könnten sie verschieden trennen
        return "Steuer- oder Nicht-ASCII-Zeichen im Befehl nicht erlaubt"
    if ABS_PREFIX and cmd.startswith(ABS_PREFIX):
        rest = cmd[len(ABS_PREFIX):]
    elif cmd.startswith(REL_PREFIXES):
        # relative Form: Bash löst sie gegen das tatsächliche Arbeitsverzeichnis des Tool-Aufrufs auf
        if cwd is not None and not (isinstance(cwd, str) and cwd == "") and not (isinstance(cwd, str) and os.path.isabs(cwd)):
            return "cwd ist nicht absolut – relative Runner-Form abgelehnt"
        if not _same_dir(cwd or os.getcwd(), REPO):
            return "relative Runner-Form nur im Repo-Wurzelverzeichnis erlaubt (sonst absoluter Pfad)"
        rest = cmd[cmd.index(" ") + 1:]
    else:
        return "nur scripts/ro_run.sh, ./scripts/ro_run.sh oder der absolute Runner-Pfad (zeichengenau, ohne Zuweisung/Präfix) darf aufgerufen werden"
    if not rest.strip():
        return "ro_run.sh ohne Befehl"
    try:
        lex = shlex.shlex(rest, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""  # shlex behandelt '#' standardmäßig als Kommentar (Review H1); '#' ist zusätzlich verboten
        tokens = list(lex)
    except ValueError as e:  # z. B. unausgewogene Anführungszeichen
        return f"Befehl nicht eindeutig parsbar ({e})"
    if not tokens:
        return "ro_run.sh ohne Befehl"
    for t in tokens:
        if t and all(ch in ";&|<>()" for ch in t):
            return f"Shell-Operator '{t}' nicht erlaubt (keine Verkettung, Pipes, Umleitungen)"
    if tokens[0].startswith("-"):
        return "das erste Argument muss ein Befehl sein, keine Option"
    return None


def log_activity(data: dict, decision: str, reason: str) -> None:
    """Hängt eine Zeile an das Aktivitätsprotokoll an (nur Hash des Befehls). Jeder Fehler wird ignoriert – die Entscheidung bleibt unberührt."""
    try:
        path = os.environ.get("LEVENTUM_HOOK_LOG") or os.path.join(os.path.expanduser("~"), ".leventum", "hook-activity.jsonl")
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        cmd = ti.get("command")
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "tool_name": data.get("tool_name") if isinstance(data.get("tool_name"), str) else None,
            "agent_type": data.get("agent_type") if isinstance(data.get("agent_type"), str) else None,
            "session_id": data.get("session_id") if isinstance(data.get("session_id"), str) else None,
            "decision": decision,
            "reason": reason[:200],
            "cmd_sha256": hashlib.sha256(cmd.encode("utf-8", "replace")).hexdigest() if isinstance(cmd, str) else None,
            "cwd": data.get("cwd") if isinstance(data.get("cwd"), str) else None,
        }
        # kein Folgen von Symlinks, kein Blockieren an FIFOs/Geräten (Review: ein dort abgelegtes FIFO ließe den Hook hängen); nur reguläre Dateien
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return
            os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        pass


def decide(data: dict) -> tuple[int, str]:
    """(exit_code, grund) – 0 erlaubt, 2 blockiert."""
    tool = data.get("tool_name")
    if not isinstance(tool, str) or not tool:  # unhashbare/fehlende Namen nicht erst im Fangnetz scheitern lassen
        return 2, "Werkzeugname fehlt oder ist kein Text (fail closed)"
    if tool in WRITE_TOOLS:
        return 2, f"Schreibwerkzeug {tool} ist für Prüf-Agenten gesperrt"
    if isinstance(tool, str) and tool.startswith("mcp__"):  # MCP-Werkzeuge (z. B. GitHub-Schreibzugriffe) sind für Prüf-Agenten nie zulässig
        return 2, f"MCP-Werkzeug {tool} ist für Prüf-Agenten gesperrt"
    if tool == "Bash":
        ti = data.get("tool_input")
        cmd = ti.get("command", "") if isinstance(ti, dict) else ""
        reason = check_command(cmd, data.get("cwd"))
        return (0, "ok") if reason is None else (2, reason)
    if tool in READ_TOOLS:
        return 0, "ok"
    return 2, f"unbekanntes oder nicht freigegebenes Werkzeug {tool!r} (fail closed)"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return deny("Hook-Eingabe nicht lesbar (fail closed)")
    if not isinstance(data, dict):
        return deny("Hook-Eingabe hat unerwartete Struktur (fail closed)")
    code, reason = decide(data)
    log_activity(data, "allow" if code == 0 else "deny", reason)
    return 0 if code == 0 else deny(reason)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # jeder unerwartete Fehler blockiert (Exit 1 würde NICHT blockieren)
        print(f"ro_guard: interner Fehler ({type(exc).__name__}) – blockiert (fail closed)", file=sys.stderr)
        sys.exit(2)
