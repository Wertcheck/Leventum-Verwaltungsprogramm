#!/usr/bin/env bash
# Read-only-Ausführung für Prüf-Agenten (Linux, benötigt root/CAP_SYS_ADMIN zum Einrichten; schlägt sonst GESCHLOSSEN fehl).
# Zweck: Tests/Skripte lesend ausführen, ohne dass sie das Repository, Lexono oder andere Dateien verändern können.
# Mechanismus (OS-Ebene, unabhängig vom Befehlstext): eigener Mount-Namespace → alle Dateisysteme read-only →
# frisches tmpfs nur auf /tmp → Prozess läuft als unprivilegierter Benutzer ohne Capabilities, no_new_privs, ohne Netzwerk.
# Aufruf: scripts/ro_run.sh <befehl> [args…]      Beispiel: scripts/ro_run.sh ./.venv/bin/python -m pytest backend/tests/test_k2_dashboard_kpis.py -q -p no:cacheprovider
# Umgebung (Nachreview): Der Prüf-Prozess erhält NUR eine Allowlist (env -i): PATH (fest), HOME=/tmp, LANG, TERM, PYTHONDONTWRITEBYTECODE, PYTEST_ADDOPTS (fest), GIT_*-Sicherheitsvariablen.
# Keine Tokens/Secrets, kein PYTHONPATH/LD_PRELOAD/BASH_ENV usw. aus der Aufrufumgebung. RO_RUN_UID wird validiert (numerisch 1..65534, nie 0).
# Rest-Grenze: Das Skript selbst (bash/env/unshare im root-Teil) startet mit der Umgebung des AUFRUFERS; ein dort gesetztes LD_PRELOAD würde in diesen root-Prozessen geladen,
# bevor die Allowlist greift. Verhinderung liegt beim Aufrufer (Hook verbietet VAR=…-Präfixe und export); im Skript selbst nicht behebbar.
# Grenzen: Linux-only; Windows nicht unterstützt; ein Prozess mit Kernel-Exploit ist nicht abgedeckt; /dev/shm ist read-only.
set -euo pipefail
if [ "$#" -lt 1 ]; then echo "Aufruf: $0 <befehl> [args…]" >&2; exit 2; fi
if [ "$(id -u)" != "0" ]; then echo "ro_run.sh: benötigt root zum Einrichten der Isolation – Abbruch (fail closed)." >&2; exit 3; fi
case "$1" in -*) echo "ro_run.sh: das erste Argument muss ein Befehl sein, keine Option (verhindert Einschleusen von setpriv-Optionen) – Abbruch." >&2; exit 2 ;; esac
# Geerbte Dateideskriptoren > 2 schließen (kein Schreiben über vom Aufrufer geerbte offene Handles).
for fdp in /proc/$$/fd/*; do fd="${fdp##*/}"; case "$fd" in 0|1|2) ;; *[!0-9]*) ;; *) eval "exec $fd>&-" 2>/dev/null || true ;; esac; done
for t in unshare setpriv mount; do command -v "$t" >/dev/null || { echo "ro_run.sh: '$t' fehlt – Abbruch (fail closed)." >&2; exit 3; }; done
RO_UID="${RO_RUN_UID:-65534}"
case "$RO_UID" in ''|*[!0-9]*) echo "ro_run.sh: RO_RUN_UID muss eine Dezimalzahl sein – Abbruch (fail closed)." >&2; exit 3 ;; esac
if [ "${#RO_UID}" -gt 5 ] || [ "$((10#$RO_UID))" -lt 1 ] || [ "$((10#$RO_UID))" -gt 65534 ]; then echo "ro_run.sh: RO_RUN_UID außerhalb 1..65534 (0/root nicht erlaubt) – Abbruch (fail closed)." >&2; exit 3; fi
RO_UID="$((10#$RO_UID))"
SAFE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Nur die Allowlist wird in den Namespace gereicht; alles andere (Tokens, PYTHONPATH, LD_PRELOAD, BASH_ENV …) wird verworfen.
exec env -i PATH="$SAFE_PATH" RO_CWD="$PWD" RO_UID="$RO_UID" LANG="C.UTF-8" TERM="${TERM:-dumb}" \
  unshare --mount --net --pid --fork --mount-proc --ipc --uts --propagation private -- bash -c '
  set -e
  # Alle echten Dateisysteme read-only (Root-Dateisystem und separate rw-Mounts wie /dev/shm); danach privates tmpfs für /tmp.
  mount -o remount,ro,bind /
  # Review M4: ALLE als rw eingehängten Mounts (aus /proc/self/mounts) read-only, nicht nur eine feste Liste; /proc, /sys und /dev/pts bleiben unberührt (Prozess-/Terminalbetrieb).
  while read -r _ mp _ opts _; do
    case ",$opts," in *,rw,*) ;; *) continue ;; esac
    case "$mp" in /|/proc|/proc/*|/sys|/sys/*|/dev/pts|/dev/mqueue) continue ;; esac
    mp=$(printf "%b" "$mp"); mount -o remount,ro,bind "$mp" 2>/dev/null || true
  done < /proc/self/mounts
  mount -t tmpfs -o mode=1777,size=1g,nosuid,nodev tmpfs /tmp
  # Pfad-Unix-Sockets sind durch --net NICHT isoliert (Nachreview: /run/sandbox-telemetry/ingest.sock world-writable) -> /run durch leeres tmpfs verdecken.
  mount -t tmpfs -o mode=0755,size=1m,nosuid,nodev,noexec tmpfs /run
  # Verifikation statt Hoffnung: bleibt der OBERSTE (per Pfad erreichbare) Mount eines Mountpunkts rw – außer Ausnahmeliste und /tmp –, bricht der Runner geschlossen ab.
  # Verdeckte, gestapelte Mounts darunter (z. B. zweites /dev/shm) sind per Pfad nicht erreichbar und zählen nicht.
  declare -A top
  while read -r _ mp _ opts _; do top["$mp"]="$opts"; done < /proc/self/mounts
  for mp in "${!top[@]}"; do
    case ",${top[$mp]}," in *,rw,*) ;; *) continue ;; esac
    case "$mp" in /tmp|/run|/proc|/proc/*|/sys|/sys/*|/dev/pts|/dev/mqueue) continue ;; esac
    echo "ro_run.sh: Mount $mp ist weiterhin schreibbar – Abbruch (fail closed)." >&2; exit 3
  done
  cd "$RO_CWD"
  # Zweite, endgültige Allowlist für den unprivilegierten Prozess (RO_CWD/RO_UID verschwinden hier).
  exec env -i PATH="$PATH" HOME=/tmp LANG=C.UTF-8 TERM="$TERM" PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS="-p no:cacheprovider" \
    GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="*" GIT_OPTIONAL_LOCKS=0 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 \
    setpriv --reuid="$RO_UID" --regid="$RO_UID" --clear-groups --bounding-set=-all --inh-caps=-all --no-new-privs -- "$@"
' ro_run "$@"
