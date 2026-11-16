#!/usr/bin/env python3
"""PreToolUse-Hook für Prüf-Agenten (Bash): erlaubt AUSSCHLIESSLICH `scripts/ro_run.sh <befehl…>` als einzigen Befehl.

Zweite Schicht (Defense in Depth) vor der OS-Isolation von scripts/ro_run.sh: Jeder andere Bash-Aufruf wird mit Exit-Code 2 blockiert.
Lesart laut Claude-Code-Doku: Hooks sind ein Backstop, keine Sandbox – die eigentliche Schreibsperre liefert ro_run.sh (Read-only-Mounts, kein root,
keine Capabilities, kein Netz). Der Hook garantiert nur, dass Prüf-Agenten diesen Weg nicht verlassen.
Fail closed: unlesbare Eingabe, unbekannte Werkzeuge mit Schreibcharakter oder Parserzweifel → blockieren.
Eingabe: JSON auf stdin (tool_name, tool_input.command). Ausgabe: Exit 0 = erlaubt, Exit 2 = blockiert (Grund auf stderr)."""
from __future__ import annotations

import json
import os
import shlex
import sys

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
RUNNER = os.path.join(REPO, "scripts", "ro_run.sh")
FORBIDDEN_CHARS = ("$", "`", "\n", "\r", "\\", "\x00", "#")
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}


def deny(msg: str) -> int:
    print(f"ro_guard: blockiert – {msg}. Erlaubt ist nur: scripts/ro_run.sh <befehl…>", file=sys.stderr)
    return 2


def check_command(cmd: str, cwd: str | None = None) -> str | None:
    """Gibt None zurück, wenn erlaubt, sonst den Ablehnungsgrund."""
    if not cmd or not cmd.strip():
        return "leerer Befehl"
    if any(c in cmd for c in FORBIDDEN_CHARS):
        return "Shell-Expansion/Zeilenumbruch/Escape im Befehl nicht erlaubt"
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""  # shlex behandelt '#' standardmäßig als Kommentar und verwirft den Rest – Bash nur am Wortanfang: 'echo a#b; touch x' wäre sonst durchgerutscht (Review-Befund H1)
        tokens = list(lex)
    except ValueError as e:  # z. B. unausgewogene Anführungszeichen
        return f"Befehl nicht eindeutig parsbar ({e})"
    if not tokens:
        return "leerer Befehl"
    for t in tokens:
        if t and all(ch in ";&|<>()" for ch in t):
            return f"Shell-Operator '{t}' nicht erlaubt (keine Verkettung, Pipes, Umleitungen)"
    first = tokens[0]
    base = cwd or os.getcwd()
    path = first if os.path.isabs(first) else os.path.join(base, first)
    if os.path.realpath(path) != os.path.realpath(RUNNER):
        return "nur scripts/ro_run.sh darf aufgerufen werden"
    if len(tokens) < 2:
        return "ro_run.sh ohne Befehl"
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return deny("Hook-Eingabe nicht lesbar (fail closed)")
    if not isinstance(data, dict):
        return deny("Hook-Eingabe hat unerwartete Struktur (fail closed)")
    tool = data.get("tool_name")
    if tool in WRITE_TOOLS:
        return deny(f"Schreibwerkzeug {tool} ist für Prüf-Agenten gesperrt")
    if tool != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "")
    reason = check_command(cmd, data.get("cwd"))
    return 0 if reason is None else deny(reason)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # jeder unerwartete Fehler blockiert (Exit 1 würde NICHT blockieren)
        print(f"ro_guard: interner Fehler ({type(exc).__name__}) – blockiert (fail closed)", file=sys.stderr)
        sys.exit(2)
