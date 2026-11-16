#!/usr/bin/env bash
# Read-only-Ausführung für Prüf-Agenten (Linux, benötigt root/CAP_SYS_ADMIN zum Einrichten; schlägt sonst GESCHLOSSEN fehl).
# Zweck: Tests/Skripte lesend ausführen, ohne dass sie das Repository, Lexono oder andere Dateien verändern können.
# Mechanismus (OS-Ebene, unabhängig vom Befehlstext): eigener Mount-Namespace → alle Dateisysteme read-only →
# frisches tmpfs nur auf /tmp → Prozess läuft als unprivilegierter Benutzer ohne Capabilities, no_new_privs, ohne Netzwerk.
# Aufruf: scripts/ro_run.sh <befehl> [args…]      Beispiel: scripts/ro_run.sh ./.venv/bin/python -m pytest backend/tests/test_k2_dashboard_kpis.py -q -p no:cacheprovider
# Grenzen: Linux-only; Windows nicht unterstützt; ein Prozess mit Kernel-Exploit ist nicht abgedeckt; /dev/shm ist read-only.
set -euo pipefail
if [ "$#" -lt 1 ]; then echo "Aufruf: $0 <befehl> [args…]" >&2; exit 2; fi
if [ "$(id -u)" != "0" ]; then echo "ro_run.sh: benötigt root zum Einrichten der Isolation – Abbruch (fail closed)." >&2; exit 3; fi
for t in unshare setpriv mount; do command -v "$t" >/dev/null || { echo "ro_run.sh: '$t' fehlt – Abbruch (fail closed)." >&2; exit 3; }; done
RO_UID="${RO_RUN_UID:-65534}"
export RO_CWD="$PWD"
exec unshare --mount --net --propagation private -- bash -c '
  set -e
  # Alle echten Dateisysteme read-only (Root-Dateisystem und separate rw-Mounts wie /dev/shm); danach privates tmpfs für /tmp.
  mount -o remount,ro,bind /
  for m in /dev/shm /run; do mountpoint -q "$m" 2>/dev/null && mount -o remount,ro,bind "$m" 2>/dev/null || true; done
  mount -t tmpfs -o mode=1777,size=1g tmpfs /tmp
  cd "$RO_CWD"
  export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="*" GIT_OPTIONAL_LOCKS=0
  export HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS="-p no:cacheprovider ${PYTEST_ADDOPTS:-}"
  exec setpriv --reuid='"$RO_UID"' --regid='"$RO_UID"' --clear-groups --bounding-set=-all --inh-caps=-all --no-new-privs "$@"
' ro_run "$@"
