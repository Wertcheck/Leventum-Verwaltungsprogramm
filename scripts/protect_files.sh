#!/usr/bin/env bash
# Setzt/entfernt/zeigt das Immutable-Attribut (chattr +i) der Schutzdateien des Prüf-Systems.
# Aufruf: scripts/protect_files.sh [--root DIR] protect|unprotect|status
# EHRLICH: Das schützt nur gegen VERSEHENTLICHE Schreibzugriffe (Edit/Write, Shell-Umleitungen normaler Agenten). Es schützt NICHT gegen einen
# root-Agenten, der `chattr -i` ausführt. Der Vertrauensanker ist der Git-PIN (scripts/review_preflight.py), nicht das Attribut.
# Exit-Codes: 0 ok · 1 Zustand/Datei nicht in Ordnung (status: nicht immutable; protect: Datei fehlt) · 2 Bedienfehler · 3 nicht root / chattr/lsattr fehlt oder nicht unterstützt.
# `unprotect` ist ein ausdrücklicher Orchestrator-Schritt (z. B. vor einer bewussten Änderung der Schutzdateien).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || true)"
if [ "${1:-}" = "--root" ]; then ROOT="${2:?--root braucht ein Verzeichnis}"; shift 2; fi
CMD="${1:-}"
case "$CMD" in protect|unprotect|status) ;; *) echo "Aufruf: $0 [--root DIR] protect|unprotect|status" >&2; exit 2 ;; esac
FILES=(
  scripts/ro_run.sh scripts/review_preflight.py scripts/protect_files.sh scripts/check_file_set.py scripts/validate_agent_system.py
  .claude/hooks/ro_guard.py .claude/agents/independent-reviewer.md .claude/agents/independent-reviewer-static.md
  .claude/settings.json CLAUDE.md .claude/rules/60-collaboration.md
  .claude/hooks   # Verzeichnis, nicht rekursiv
)
if [ "$(id -u)" != "0" ]; then echo "protect_files.sh: benötigt root – nichts getan." >&2; exit 3; fi
for t in chattr lsattr; do command -v "$t" >/dev/null || { echo "protect_files.sh: '$t' fehlt – Abbruch." >&2; exit 3; }; done
missing=0
for f in "${FILES[@]}"; do
  if [ ! -e "$ROOT/$f" ] || [ -L "$ROOT/$f" ]; then echo "FEHLT/SYMLINK: $f" >&2; missing=1; fi
done
if [ "$missing" = 1 ] && [ "$CMD" != "status" ]; then echo "protect_files.sh: Dateien fehlen – nichts getan." >&2; exit 1; fi
rc=0
for f in "${FILES[@]}"; do
  p="$ROOT/$f"
  case "$CMD" in
    protect)   chattr +i -- "$p" 2>/dev/null || { echo "protect_files.sh: chattr +i auf $f fehlgeschlagen (nicht unterstützt?)" >&2; exit 3; }; echo "immutable: $f" ;;
    unprotect) chattr -i -- "$p" 2>/dev/null || { echo "protect_files.sh: chattr -i auf $f fehlgeschlagen" >&2; exit 3; }; echo "mutable:   $f" ;;
    status)
      if [ ! -e "$p" ]; then echo "FEHLT:         $f"; rc=1; continue; fi
      flags="$(lsattr -d -- "$p" 2>/dev/null | awk '{print $1}')" || flags=""
      [ -n "$flags" ] || { echo "protect_files.sh: lsattr auf $f nicht möglich (nicht unterstützt?)" >&2; exit 3; }
      case "$flags" in *i*) echo "immutable:     $f" ;; *) echo "NICHT immutable: $f"; rc=1 ;; esac ;;
  esac
done
exit "$rc"
