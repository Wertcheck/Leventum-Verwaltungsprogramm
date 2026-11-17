# Messprotokoll – Root-Angriffe im selben Kernel (Experiment, bereinigte Kopie)
Quelle: Infrastruktur-Experimente der Phase „Isolierung der Vertrauensgrenze“ (Linux-Firecracker-microVM, Kernel 6.18, root, CapEff 000001fffeffffff). Enthält nur Befehle, Exit-Codes und Metadaten; **keine Secret-Werte**; Sitzungs-ID, Scratchpad-/Token-Pfade und die Dateigröße der Token-Datei sind durch Platzhalter ersetzt (Wegwerf-Pfade wie `/home/user/iso_lab`, Benutzername `ubuntu`, Zeitstempel und Namen von Plattform-Variablen stehen im Klartext). Dies ist ein **Auszug** (nicht vollständig: einzelne Skriptdateien und Zwischenschritte fehlen; Aussagen wie „aufgeräumt, nichts übrig“ sind Selbstauskunft des Messagenten); die Muster-Prüfung war eine Stichprobe. Einordnung und Schlussfolgerungen: `PHASE_I_ISOLATION_ARCHITECTURE.md` §3. Status: Experiment, nicht unabhängig geprüft; reproduzierbar sind im Repo nur die `test_limit_*`-Tests (`backend/tests/test_review_isolation.py`).

## A1

$ stat -c '%u %a %n' a1/f a1/d
1000 400 a1/f
65000 500 a1/d
[exit 0]

$ cat a1/f
geheim
[exit 0]

$ echo neu > a1/f && cat a1/f
neu
[exit 0]

$ echo x > a1/d/neu && ls a1/d
neu
[exit 0]

$ rm a1/d/neu; chattr +i a1/f; lsattr a1/f
----i---------e------- a1/f
[exit 0]

$ echo x2 > a1/f
bash: line 1: a1/f: Operation not permitted
[exit 1]

$ rm -f a1/f
rm: cannot remove 'a1/f': Operation not permitted
[exit 1]

$ chattr -i a1/f && echo ok-- && echo x3 > a1/f && cat a1/f
ok--
x3
[exit 0]
## A3
pid=384

$ grep -E 'Uid|CapEff|NoNewPrivs' /proc/384/status
Uid:	1000	1000	1000	1000
CapEff:	0000000000000000
NoNewPrivs:	1
[exit 0]

$ tr '\0' '\n' < /proc/384/environ | cut -d= -f1 | head -3
SHELL
IS_SANDBOX
COREPACK_ENABLE_AUTO_PIN
[exit 0]

$ ls -l /proc/384/cwd /proc/384/root
lrwxrwxrwx 1 ubuntu ubuntu 0 Nov 16 23:46 /proc/384/cwd -> /home/user/iso_lab
lrwxrwxrwx 1 ubuntu ubuntu 0 Nov 16 23:46 /proc/384/root -> /
[exit 0]

$ head -c 100 /proc/384/mem | wc -c
head: error reading '/proc/384/mem': Input/output error
0
[exit 0]

$ python3 -c "import ctypes;l=ctypes.CDLL(None,use_errno=True);print('ptrace_attach',l.ptrace(16,384,0,0),ctypes.get_errno())"
ptrace_attach 0 0
[exit 0]

$ grep -E 'TracerPid' /proc/384/status
TracerPid:	0
[exit 0]

$ touch /proc/384/root/tmp/rootwrote && ls -l /tmp/rootwrote; rm -f /tmp/rootwrote
-rw-r--r-- 1 root root 0 Nov 16 23:46 /tmp/rootwrote
[exit 0]

$ kill -9 384; sleep 0.3; kill -0 384
bash: line 1: kill: (384) - No such process
<scratchpad>/iso/infra/a.sh: line 2:   384 Killed                  setpriv --reuid=1000 --regid=1000 --clear-groups --inh-caps=-all --bounding-set=-all --no-new-privs env SECRETVAR=abc123 sleep 300
[exit 1]
## A3b mem-Lesen an gueltiger Adresse

$ A=$(head -1 /proc/448/maps | cut -d- -f1); python3 -c "f=open('/proc/448/mem','rb');f.seek(int('$A',16));print(len(f.read(16)),'bytes gelesen')"
16 bytes gelesen
[exit 0]

$ A=$(grep -m1 ' rw-p' /proc/448/maps | cut -d- -f1); python3 -c "f=open('/proc/448/mem','r+b');f.seek(int('$A',16));f.write(b'XX');print('geschrieben')"
geschrieben
[exit 0]
## A2
<scratchpad>/iso/infra/a2.sh: line 10:   448 Killed                  setpriv --reuid=1000 --regid=1000 --clear-groups --inh-caps=-all --bounding-set=-all --no-new-privs sleep 300
nspid=467

$ echo inside-write > a2/mnt; echo 'init-ns sieht mount?'; grep -c iso_lab/a2/mnt /proc/self/mountinfo
init-ns sieht mount?
0
[exit 1]

$ echo CHANGED > a2/prot; cat a2/prot
CHANGED
[exit 0]

$ nsenter -t 467 -m -- cat /home/user/iso_lab/a2/mnt
CHANGED
[exit 0]

$ nsenter -t 467 -m -- sh -c 'echo viaNS > /home/user/iso_lab/a2/mnt'
sh: 1: cannot create /home/user/iso_lab/a2/mnt: Read-only file system
[exit 2]

$ nsenter -t 467 -m -- mount -o remount,bind,rw /home/user/iso_lab/a2/mnt && nsenter -t 467 -m -- sh -c 'echo viaRW > /home/user/iso_lab/a2/mnt' && cat a2/prot
viaRW
[exit 0]

$ cat /proc/467/root/home/user/iso_lab/a2/mnt
viaRW
[exit 0]
## A2b loop-FS nur im privaten Mount-NS

$ truncate -s 16M a2/img && mkfs.ext4 -q -F a2/img && echo mkfs ok
mkfs ok
[exit 0]

$ ls a2/mp | wc -l; echo '(init-ns: Inhalt von a2/mp, 0 = nicht sichtbar)'
0
(init-ns: Inhalt von a2/mp, 0 = nicht sichtbar)
[exit 0]

$ losetup -a
/dev/loop0: [65024]:583754 (/home/user/iso_lab/a2/img)
[exit 0]

$ strings a2/img | grep -c SECRETFILE
0
[exit 1]

$ nsenter -t 506 -m -- cat /home/user/iso_lab/a2/mp/s
SECRETFILE
[exit 0]

$ cat /proc/506/root/home/user/iso_lab/a2/mp/s
SECRETFILE
[exit 0]

$ mkdir a2/mp2; mount -o loop,ro a2/img a2/mp2 2>&1; ls a2/mp2; umount a2/mp2
mount: /home/user/iso_lab/a2/mp2: /dev/loop0 already mounted or mount point busy.
       dmesg(1) may have more information after failed mount system call.
umount: a2/mp2: not mounted.
[exit 32]
## B1.1 runc

$ runc --version | head -2
runc version 1.5.2
commit: v1.5.2-0-g29dd3dc2
[exit 0]

$ runc spec && ls
config.json
rootfs
[exit 0]
lrwxrwxrwx 1 root root 7 Apr 22  2024 /bin -> usr/bin
lrwxrwxrwx 1 root root 7 Apr 22  2024 /lib -> usr/lib
lrwxrwxrwx 1 root root 9 Apr 22  2024 /lib64 -> usr/lib64

$ runc --root /home/user/iso_lab/b1/state run -d --pid-file /home/user/iso_lab/b1/pid c1 </dev/null
time="2026-11-16T23:46:37Z" level=error msg="runc run failed: unable to start container process: error during container init: error mounting \"proc\" to rootfs at \"/proc\": mkdirat /home/user/iso_lab/b1/bundle/rootfs/proc: permission denied"
[exit 1]

$ runc --root /home/user/iso_lab/b1/state list
ID          PID         STATUS      BUNDLE      CREATED     OWNER
[exit 0]
## B1.1 (2. Versuch: rootfs chown 100000, bin/lib als Symlinks)

$ runc --root /home/user/iso_lab/b1/state run -d --pid-file /home/user/iso_lab/b1/pid c1 </dev/null >/home/user/iso_lab/b1/out 2>&1

[exit 1]

$ runc --root /home/user/iso_lab/b1/state list
ID          PID         STATUS      BUNDLE      CREATED     OWNER
[exit 0]

$ cat /home/user/iso_lab/b1/out
time="2026-11-16T23:46:48Z" level=error msg="runc run failed: unable to start container process: error during container init: error mounting \"sysfs\" to rootfs at \"/sys\": mount src=sysfs, dst=/sys, dstFd=/proc/thread-self/fd/13, flags=MS_RDONLY|MS_NOSUID|MS_NODEV|MS_NOEXEC: operation not permitted"
[exit 0]
## B1.1 (3. Versuch: ohne sysfs/cgroup-Mount)
## B1.1 Angriffe (Container c1 laeuft, readonly rootfs, userns 0->100000, noNewPrivs, Caps leer) pid=748

$ grep -E 'NoNewPrivs|CapEff|^Uid' /proc/748/status; ls -l /proc/748/ns/ | awk '{print $9,$11}' | head -9; readlink /proc/self/ns/user
Uid:	100000	100000	100000	100000
CapEff:	0000000000000000
NoNewPrivs:	1
 
cgroup cgroup:[4026531835]
ipc ipc:[4026532267]
mnt mnt:[4026532265]
net net:[4026531833]
[exit 0]

$ touch rootfs/hostwrite 2>&1; ls rootfs
bin
dev
hostwrite
lib
lib64
proc
sys
usr
[exit 0]

$ runc --root /home/user/iso_lab/b1/state exec c1 /bin/sh -c 'id -u; echo exec-ok'
0
exec-ok
[exit 0]

$ nsenter -t 748 -a -- /bin/sh -c 'id -u; echo nsenter-a-ok; touch /x 2>&1'
0
nsenter-a-ok
touch: cannot touch '/x': Read-only file system
[exit 1]

$ touch /proc/748/root/hostwrote-via-proc && ls /proc/748/root | head -20
touch: cannot touch '/proc/748/root/hostwrote-via-proc': Read-only file system
[exit 1]

$ ls /proc/748/root/etc 2>&1 | head -2; echo hack > /proc/748/root/tmp/y; ls /proc/748/root/tmp
ls: cannot access '/proc/748/root/etc': No such file or directory
bash: line 1: /proc/748/root/tmp/y: No such file or directory
ls: cannot access '/proc/748/root/tmp': No such file or directory
[exit 2]

$ grep -c . /proc/748/mountinfo; nsenter -t 748 -m -- mount -o remount,rw / ; nsenter -t 748 -m -- sh -c 'touch /rwtest && echo rw-write-ok'
20
rw-write-ok
[exit 0]

$ nsenter -t 748 -m -- mount -t tmpfs none /usr && nsenter -t 748 -m -- ls /usr | wc -l
nsenter: failed to execute ls: No such file or directory
0
[exit 0]

$ runc --root /home/user/iso_lab/b1/state kill c1 KILL; sleep 1; runc --root /home/user/iso_lab/b1/state list; kill -0 748
ID          PID         STATUS      BUNDLE                         CREATED                          OWNER
c1          0           stopped     /home/user/iso_lab/b1/bundle   2026-11-16T23:46:53.436276271Z   root
[exit 0]

$ runc --root /home/user/iso_lab/b1/state delete -f c1; runc --root /home/user/iso_lab/b1/state list
ID          PID         STATUS      BUNDLE      CREATED     OWNER
[exit 0]
## B1.2 Docker

$ ls -l /var/run/docker.sock; docker images 2>&1 | head -2; docker info 2>&1 | head -3
ls: cannot access '/var/run/docker.sock': No such file or directory
failed to connect to the docker API at unix:///var/run/docker.sock; check if the path is correct and if the daemon is running: dial unix /var/run/docker.sock: connect: no such file or directory
Client: Docker Engine - Community
 Version:    29.9.2
 Context:    default
[exit 0]

$ ls /var/lib/docker /etc/docker 2>&1 | head; dockerd --version
ls: cannot access '/var/lib/docker': No such file or directory
/etc/docker:
Docker version 29.9.2, build 0367cbe
[exit 0]

$ timeout 25 dockerd --data-root /home/user/iso_lab/dk/data --exec-root /home/user/iso_lab/dk/exec --pidfile /home/user/iso_lab/dk/pid --host unix:///home/user/iso_lab/dk/d.sock --bridge=none --iptables=false --ip-forward=false --ip-masq=false --containerd-namespace x 2>&1 | tail -6
time="2026-11-16T23:47:20.517376672Z" level=info msg="API listen on /home/user/iso_lab/dk/d.sock"
time="2026-11-16T23:47:45.048306224Z" level=info msg="Processing signal 'terminated'"
time="2026-11-16T23:47:45.050085085Z" level=info msg="stopping event stream following graceful shutdown" error="grpc: the client connection is closing: context canceled" module=libcontainerd namespace=x
time="2026-11-16T23:47:45.052498441Z" level=info msg="stopping containerd healthcheck following graceful shutdown" binary=/usr/bin/containerd module=supervisor pid=998
time="2026-11-16T23:47:45.052554881Z" level=info msg="stopping event stream following graceful shutdown" error="context canceled" module=libcontainerd namespace=plugins.moby
time="2026-11-16T23:47:46.053707326Z" level=info msg="Daemon shutdown complete"
[exit 0]
## C1 Secrets (nur Namen/Metadaten)

$ tr '\0' '\n' < /proc/1/environ | cut -d= -f1 | sort | tr '\n' ' '
bash: line 1: /proc/1/environ: Permission denied
[exit 0]
<scratchpad>/iso/infra/c.sh: line 11: /proc/1/environ: Permission denied
CLAUDE_SESSION_INGRESS_TOKEN_FILE path=

$ ls -la /root/.ssh 2>&1 | head -5; ls -la /root/.config/gh 2>&1 | head -5; ls -la /root/.ccr 2>&1 | head -10
total 8
drwx------  2 root root 4096 Oct 27 19:42 .
drwx------ 17 root root 4096 Nov 16 23:43 ..
ls: cannot access '/root/.config/gh': No such file or directory
total 216
drwxr-xr-x  2 root root   4096 Nov 16 23:43 .
drwx------ 17 root root   4096 Nov 16 23:43 ..
-rw-r--r--  1 root root   5562 Nov 16 23:43 README.md
-rw-r--r--  1 root root   2000 Nov 16 23:43 agent-proxy-ca.crt
-rw-r--r--  1 root root 186636 Nov 16 23:43 ca-bundle.crt
-rw-r--r--  1 root root     64 Nov 15 09:10 nssdb-4b83bad972d4a339.checked-v2
-rw-r--r--  1 root root     64 Nov 15 09:10 nssdb-6d01b74740a725a6.checked-v2
[exit 0]

$ stat -c '%a %U %s %n' /root/.ccr/* 2>&1 | head
644 root 5562 /root/.ccr/README.md
644 root 2000 /root/.ccr/agent-proxy-ca.crt
644 root 186636 /root/.ccr/ca-bundle.crt
644 root 64 /root/.ccr/nssdb-4b83bad972d4a339.checked-v2
644 root 64 /root/.ccr/nssdb-6d01b74740a725a6.checked-v2
644 root 2000 /root/.ccr/system-trust.ca.pem
[exit 0]

$ tr '\0' '\n' < /proc/self/environ | cut -d= -f1 | grep -ciE 'TOKEN|SECRET|KEY'
0
[exit 1]
-- Namespace mit env -i und leerem Mount: Host-Secrets weiter lesbar?

$ unshare -m --pid --fork --mount-proc env -i /bin/bash -c 'mkdir -p /tmp/e; mount -t tmpfs none /root; ls /root | wc -l; env | wc -l; ls /proc/1/environ; tr "\0" "\n" < /proc/1/environ | cut -d= -f1 | head -3; echo ---pid-ns-init-is-bash'
0
8
/proc/1/environ
---pid-ns-init-is-bash
[exit 0]

$ unshare -m env -i /bin/bash -c 'mount -t tmpfs none /root; echo root-leer:; ls -A /root | wc -l; echo hostproc-env-names:; tr "\0" "\n" < /proc/1/environ | cut -d= -f1 | grep -c TOKEN'
root-leer:
0
hostproc-env-names:
/bin/bash: line 1: /proc/1/environ: Permission denied
0
[exit 1]

$ unshare -m --fork env -i /bin/bash -c 'mount -t tmpfs none /root; HP=$(nsenter -t 1 -m -- sh -c "ls /root/.ccr | wc -l"); echo nsenter-t1-m ls .ccr count=$HP'
nsenter: cannot open /proc/1/ns/mnt: Permission denied
nsenter-t1-m ls .ccr count=
[exit 0]

$ unshare -m --pid --fork --mount-proc env -i /bin/bash -c 'nsenter -t 1 -m -- sh -c "echo nsenter-1-failed-or-ok"' 
nsenter-1-failed-or-ok
[exit 0]
## C2 Netz

$ unshare -n sh -c 'ip -br addr; ip route; (echo > /dev/tcp/127.0.0.1/80) 2>&1 | head -1'
sh: 1: ip: not found
sh: 1: ip: not found
sh: 1: cannot create /dev/tcp/127.0.0.1/80: Directory nonexistent
[exit 0]

$ ip -br addr | head -5
bash: line 1: ip: command not found
[exit 0]
## C1b Detail: warum /proc/1/environ verweigert? Elternkette lesen

$ grep -E 'Name|Uid|CapEff' /proc/1/status; cat /proc/sys/kernel/yama/ptrace_scope 2>&1; ls -ld /proc/1 | cut -c1-30; ls /sys/kernel/security 2>&1 | head -3; cat /proc/1/cmdline | tr '\0' ' ' | cut -c1-60
Name:	process_api
Uid:	0	0	0	0
CapEff:	000001ffffffffff
cat: /proc/sys/kernel/yama/ptrace_scope: No such file or directory
dr-xr-xr-x 9 root root 0 Nov 1
/process_api --firecracker-init --addr <adresse> --max-ws
[exit 0]

$ P=$$; while [ $P -gt 1 ]; do echo $P $(cut -d' ' -f2 /proc/$P/stat) env_readable=$(head -c1 /proc/$P/environ >/dev/null 2>&1 && echo yes || echo no); P=$(awk '{print $4}' /proc/$P/stat); done
1281 (bash) env_readable=yes
1280 (bash) env_readable=yes
1265 (bash) env_readable=yes
1263 (bash) env_readable=yes
101 (claude) env_readable=yes
93 (environment-man) env_readable=yes
90 (sh) env_readable=yes
[exit 0]
-- Namen der Variablen (nur Namen) fuer lesbare Vorfahren:

$ P=$$; while [ $P -gt 1 ]; do if head -c1 /proc/$P/environ >/dev/null 2>&1; then echo pid $P:; tr '\0' '\n' </proc/$P/environ | cut -d= -f1 | grep -E 'TOKEN|SECRET|KEY|PROXY|URL|FILE|PASS' | sort -u | tr '\n' ' '; echo; break; fi; P=$(awk '{print $4}' /proc/$P/stat); done
pid 1313:
ANTHROPIC_BASE_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY BUN_TLS_EXTRA_DISTRUSTED_KEYS CCR_AGENT_PROXY_CA_WATCH_ENABLED CCR_AGENT_PROXY_ENABLED CCR_AUTO_MODE_USER_ENV_KEYS_FACT CCR_SESSION_PROFILE CCR_UPSTREAM_PROXY_ENABLED CLAUDE_CODE_ARTIFACT_MULTI_FILE CLAUDE_CODE_DIAGNOSTICS_FILE CLAUDE_CODE_MESSAGING_TOKEN CLAUDE_CODE_PROXY_RESOLVES_HOSTS CLAUDE_CODE_REMOTE_SDK_URL CLAUDE_SESSION_INGRESS_TOKEN_FILE CLOUDSDK_AUTH_ACCESS_TOKEN CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE CLOUDSDK_PROXY_ADDRESS CLOUDSDK_PROXY_PORT CLOUDSDK_PROXY_TYPE CURL_CA_BUNDLE DOCKER_HTTPS_PROXY ELECTRON_GET_USE_PROXY GH_TOKEN GITHUB_TOKEN GIT_ASKPASS GIT_CONFIG_KEY_0 GIT_CONFIG_KEY_1 GIT_CONFIG_KEY_2 GLOBAL_AGENT_HTTPS_PROXY GLOBAL_AGENT_NO_PROXY GRPC_DEFAULT_SSL_ROOTS_FILE_PATH HTTPS_PROXY MAX_THINKING_TOKENS NIX_PROFILES NIX_SSL_CERT_FILE NO_PROXY PIP_CONFIG_FILE SESSION_INGRESS_URL SSL_CERT_FILE YARN_HTTPS_PROXY __ETC_PROFILE_NIX_SOURCED 
[exit 0]
-- Token-Datei (nur Metadaten)

$ P=$$; while [ $P -gt 1 ]; do f=$(tr '\0' '\n' </proc/$P/environ 2>/dev/null | grep '^CLAUDE_SESSION_INGRESS_TOKEN_FILE=' | cut -d= -f2-); [ -n "$f" ] && { echo path=$f; stat -c 'mode=%a owner=%U size=%s' "$f"; break; }; P=$(awk '{print $4}' /proc/$P/stat); done
path=<home>/.claude/remote/<token-datei>
mode=600 owner=root size=<n>
[exit 0]
-- Alle Prozesse: environ lesbar fuer root? (Zaehlung)

$ n=0;y=0; for d in /proc/[0-9]*; do n=$((n+1)); head -c1 $d/environ >/dev/null 2>&1 && y=$((y+1)); done; echo total=$n readable=$y
total=83 readable=9
[exit 0]

$ for d in /proc/[0-9]*; do head -c1 $d/environ >/dev/null 2>&1 || echo $(basename $d) $(cut -d' ' -f2 $d/stat) NOT-readable; done | head -8
1 (process_api) NOT-readable
10 (kworker/0:0H-events_highpri) NOT-readable
11 (kworker/0:1-virtio_vsock) NOT-readable
12 (kworker/u16:0-flush-254:0) NOT-readable
13 (kworker/R-mm_percpu_wq) NOT-readable
14 (ksoftirqd/0) NOT-readable
15 (rcu_preempt) NOT-readable
16 (rcu_exp_par_gp_kthread_worker/0) NOT-readable
[exit 0]
-- Host-pid-Sicht aus Namespace mit env -i + leerem /root (kein --pid): Secrets noch lesbar?

$ unshare -m env -i /bin/bash -c 'mount -t tmpfs none /root; P=$PPID; echo hostpid-ancestor=$P; for p in $(seq 1 3); do :; done; PP=$(awk "{print \$4}" /proc/$$/stat); while [ $PP -gt 1 ]; do if head -c1 /proc/$PP/environ >/dev/null 2>&1; then echo readable-ancestor=$PP names:; tr "\0" "\n" </proc/$PP/environ | cut -d= -f1 | grep -cE "TOKEN|SECRET"; break; fi; PP=$(awk "{print \$4}" /proc/$PP/stat); done'
hostpid-ancestor=1459
readable-ancestor=1459 names:
7
[exit 0]
## C1c: Lesen der Token-Datei NICHT getestet (Aktion vom Berechtigungssystem abgelehnt); nur Metadaten (Modus 600, Besitzer root) -> fuer root per Dateirechte lesbar [aus Modus/uid abgeleitet, nicht gemessen]
bash: <scratchpad>/iso/infra/c4.sh: No such file or directory
## C2 Netz (kein iproute2/veth-Werkzeug; Messung mit python+ioctl, nur 127.0.0.1)

$ python3 netns.py list; unshare -n python3 netns.py list
['lo', 'ifb0', 'ifb1', 'eth0']
['lo']
[exit 0]

$ unshare -n python3 netns.py conn
connect failed: [Errno 101] Network is unreachable
[exit 0]

$ nsenter -t 1511 -n python3 netns.py list
['lo']
[exit 0]

$ python3 netns.py conn
connect failed: [Errno 111] Connection refused
[exit 0]

$ nsenter -t 1511 -n python3 netns.py conn; sleep 0.5; cat ns_out
connected
listening
got: b'hello'
[exit 0]

$ readlink /proc/1511/ns/net /proc/self/ns/net
net:[4026532265]
net:[4026531833]
[exit 0]
## Aufraeumen: /home/user/iso_lab geloescht, keine Mounts/Loops/Container/Daemons uebrig
