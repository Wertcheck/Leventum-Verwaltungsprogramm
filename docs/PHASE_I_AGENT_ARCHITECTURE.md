# Phase I – Agentenarchitektur, Agentensicherheit, Lexono-Isolation

Stand 2026-11-16. Statusstufen: Geplant · Implementiert · Automatisiert getestet · Manuell getestet · Unabhängig geprüft · Unter Windows getestet · Freigegeben. **Unter Windows getestet: nichts. Freigegeben: nichts.** „Real getestet“ unten heißt: mit einem **frischen headless Claude-Code-Prozess** (`claude -p`, Version 2.1.325) bzw. mit dem Betriebssystem ausgeführt; die Aussagen der Agenten in diesen Tests sind Selbstauskünfte, die ich nur dort durch Beobachtung ergänzt habe, wo es ausdrücklich steht.

## 1. Ausgangszustand (aus `PHASE_AGENT_VALIDATION.md`)
Security-Agent hatte Bash und konnte damit eine Datei anlegen; Skills wurden nicht vorgeladen; die Lexono-`CLAUDE.md` stand im Agentenkontext; Delegation nur durch die Hauptsitzung (unbelegt als Konfiguration); Dateimengen nur als Verfahren.

## 2. Was Claude Code tatsächlich kann (Dokumentation `code.claude.com`, durch einen Dokumentations-Agenten recherchiert; teilweise per Test bestätigt)
| Frage | Aussage (Quelle: offizielle Doku, Stand 2026-11-16) | Eigener Test |
|---|---|---|
| `tools` im Subagent-Frontmatter | **Allowlist**; ein nicht aufgeführtes Werkzeug fehlt dem Subagenten wirklich | bestätigt (siehe 4.1) |
| `disallowedTools` | wird vor `tools` angewendet; `Bash(…)`-Muster dort entfernen das **ganze** Werkzeug | Agent-Werkzeug entfernt: bestätigt (4.3) |
| Bash-Deny-/Allow-Regeln | **keine Sicherheitsgrenze** (`sh -c`, andere Pfade, `python -c` umgehen Textmuster); Doku empfiehlt Sandbox oder Hooks | – |
| `permissionMode` | wird bei `bypassPermissions`/`acceptEdits`/`auto`/`plan` der Hauptsitzung ignoriert; Plan-Modus ist **keine** garantierte Read-only-Sperre für Bash | nicht getestet |
| Hooks (PreToolUse) | Exit-Code 2 blockiert; in Subagent-Frontmatter nur während der Subagent läuft; Hooks sind laut Doku „Backstop, keine Sandbox“; Projekt-Hooks/`allow`-Regeln wirken **erst nach Workspace-Trust** | Hook wirksam bei Konfiguration über `--settings`: bestätigt (4.2); Wirkung des **Frontmatter**-Hooks im vertrauten Workspace: **nicht getestet** |
| Bash-Sandbox | OS-erzwungen, aber nicht auf **nativem Windows**; `failIfUnavailable` nötig, sonst fail-open; wirkt nicht auf Edit/Write | nicht genutzt (eigener Runner, siehe 3) |
| Skills in Subagenten | nicht vorgeladen, außer per `skills:` im Frontmatter | bestätigt (4.4) |
| CLAUDE.md-Laden | Verzeichnisbaum aufwärts; Unterverzeichnisse bei Bedarf; `--add-dir` nur mit Umgebungsvariable; `claudeMdExcludes` schließt Dateien aus | bestätigt (4.5) |
| Verschachtelte Subagenten | Standard bis 3 Ebenen (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`); mit `--agent <name>` kann der Hauptthread delegieren | bestätigt (4.3) |
| `isolation: worktree` | isolierte Git-Worktrees je Subagent; kein Rechteschutz; nicht ohne Git | nicht genutzt (nicht nötig, Dateimengen-Regel + Prüfskript) |

## 3. Umgesetzte Maßnahmen (Implementiert; Tests unter 4 und in `backend/tests/test_agent_guard.py`, `test_file_set_guard.py`)
1. **Security-Agent ohne Bash:** `tools: Read, Grep, Glob`, `disallowedTools: Bash, Edit, Write, NotebookEdit, Agent`. Das ist die einzige **harte, werkzeugseitige** Schreibsperre. Folge: Er kann nichts ausführen; Testausgaben/Diffs liefert der Orchestrator als Nachweisdateien.
2. **Neuer Agent `independent-reviewer`** (unabhängige QA-/Fach-/DB-Prüfung): `tools: Read, Grep, Glob, Bash`, `disallowedTools: Edit, Write, NotebookEdit, Agent`, Bash nur über `scripts/ro_run.sh`, erzwungen durch den Hook `.claude/hooks/ro_guard.py` (frontmatter-`hooks`).
3. **`scripts/ro_run.sh`** (OS-Ebene, Linux, benötigt root zum Einrichten, sonst Abbruch = fail closed): eigener Mount-Namespace, `/` und weitere Mounts **read-only**, privates tmpfs nur auf `/tmp`, Prozess als unprivilegierter Benutzer (65534) ohne Capabilities (`--bounding-set=-all`), `no_new_privs`, **kein Netzwerk**, `PYTHONDONTWRITEBYTECODE`, pytest ohne Cache. **Warum Capabilities entzogen werden:** Ein erster Prototyp ließ sich mit `CAP_SYS_ADMIN` per `mount -o remount,rw` aushebeln (im Wegwerfverzeichnis nachgewiesen) – deshalb dürfen die Prozesse nicht root bleiben.
4. **Hook `ro_guard.py`:** erlaubt nur `scripts/ro_run.sh <befehl…>` als einzigen Befehl (keine Verkettung, Pipes, Umleitungen, Expansion; `shlex`-Prüfung auf Operatoren; `$`, Backtick, Zeilenumbruch, Backslash verboten; Schreibwerkzeuge gesperrt; jede Ausnahme/kaputte Eingabe → Exit 2). Bei der Entwicklung fiel ein Fehler auf (Eingabe `[]` → Exit 1 = **nicht** blockierend); behoben und getestet.
5. **`disallowedTools: Agent`** in allen Nicht-Orchestratoren; **`skills:`-Frontmatter** in allen Profilen (Skills werden vorgeladen).
6. **`.claude/settings.json`:** `Edit(//home/user/lexono/**)` als Deny; `claudeMdExcludes` für Lexono; die früheren Regeln `Write(…)`/`NotebookEdit(…)` entfernt (der frische Prozess meldete, dass Claude Code sie **nicht auswertet** – nur `Edit(…)` deckt alle Editier-Werkzeuge ab). `allow: Bash(scripts/ro_run.sh *)` (wirkt erst im vertrauten Workspace).
7. **Beschreibungen quoten:** `description:` enthielt `: ` und war als strenges YAML ungültig (Claude Code lud sie tolerant); alle 30 Zeilen in Anführungszeichen gesetzt (Validator hat es aufgedeckt).
8. **`scripts/check_file_set.py`** (snapshot/check/overlap): erkennt nachträglich Änderungen außerhalb der zugewiesenen Dateimenge und überschneidende Dateimengen. **Keine Sperre**, nur Detektion.
9. **Validator** (`scripts/validate_agent_system.py`) prüft jetzt YAML-Frontmatter, `disallowedTools`, Security-Allowlist, Reviewer-Hook, `skills:`-Konsistenz, Settings-Regeln, `claudeMdExcludes`, vorhandene Hook-/Runner-Dateien.

## 4. Reale Tests (frischer Prozess `claude -p`; keine Windows-Umgebung)
**4.1 Security-Agent:** Subagent `security-privacy-engineer` meldete als Werkzeuge nur `Read, Grep, Glob`, kein Bash/Edit/Write, 0 Tool-Aufrufe; Skills `security-review, privacy-review, backup-restore, dependency-audit` vorgeladen (zitierte den Titel „# Skill: security-review“). Im Praxiseinsatz (Review der Finanzrechte) arbeitete er allein mit Read/Grep/Glob und fand reale Lecks (B1–B6).
**4.2 Reviewer, Hook + Runner:** Der Hook wurde in diesem Test per `--settings` und die `allow`-Regel per `--allowedTools` konfiguriert (nicht über Workspace-Trust, den ich nicht verändert habe). Ergebnis des Subagenten `independent-reviewer`: `touch …` direkt → **Hook blockiert**; `scripts/ro_run.sh touch …` → `Read-only file system`; `scripts/ro_run.sh ls README.md` und `git diff --stat` → laufen; `scripts/ro_run.sh git commit --allow-empty` → `Unable to create '.git/index.lock': Read-only file system`; `python3 -c "open(…,'w')"` → Hook blockiert; `ro_run.sh ls ; touch …` → Hook blockiert (Operator). **Meine eigene Kontrolle danach:** keine Canary-Dateien, HEAD unverändert, Lexono `git status` leer. Ohne Konfiguration (untrusted, Standardmodus) wurden **alle** Bash-Aufrufe abgelehnt („requires approval“), auch harmlose – fail closed.
**4.3 Delegation:** `claude -p … --agent lead-architect`: Hauptthread hat `Agent` und startete erfolgreich `documentation-engineer` (antwortete PING, Werkzeuge Read/Edit/Write/Grep/Glob, **kein Bash, kein Agent**). Subagent `backend-engineer` meldete: kein Agent-/Task-Werkzeug.
**4.4 Skills:** `backend-engineer` zitierte ohne Tool-Aufruf den 4. Spiegelstrich aus „6. Typische Fehler“ des Skills `backend-development` korrekt („Sitzungscache nach Raw-SQL (`expire_all`)“) – **nicht aus dem Skillnamen ableitbar**. Alle 10 Agententypen werden geladen (Liste des Agent-Werkzeugs).
**4.5 Lexono-Isolation:** Frisch gestartet aus dem Leventum-Verzeichnis: nur die Leventum-`CLAUDE.md` + 7 Regeln im Kontext; aus `/home/user`: keine `CLAUDE.md` geladen. Aus dem Lexono-Verzeichnis **ohne** Exclude: Lexono-`CLAUDE.md` geladen; **mit** `claudeMdExcludes` (`--settings`): nicht geladen. Lexono blieb unverändert (`git status` leer, HEAD `5735e5b`).
**4.6 OS-Tests (Linux, root):** `backend/tests/test_agent_guard.py` – 53 Tests (Hook: 6 erlaubte, 29 blockierte Befehle, Schreibwerkzeuge, kaputte Eingaben; Runner: Lesen als `nobody`, Schreiben überall außer privatem `/tmp` verweigert, Remount/Netzwerk verweigert, Git read-only, Ablehnung ohne Argumente). Tests, die root/unshare/setpriv brauchen, werden sonst übersprungen und **nicht** als bestanden gewertet. `test_file_set_guard.py` – 3 Tests.

## 5. Ursache der sichtbaren Lexono-`CLAUDE.md` (Ergebnis der Untersuchung)
In frischen Prozessen **nicht** reproduzierbar (4.5). In der Cloud-Sitzung wurde Lexono über `add_repo` angebunden; die Harness lädt dessen Projektanweisungen in den Sitzungskontext, den Subagenten erben. Die Doku nennt zusätzlich als Wege: Sitzung startet im Elternverzeichnis (Unterverzeichnis-Laden bei Bedarf), `--add-dir` mit Umgebungsvariable. **Maßnahmen:** `claudeMdExcludes` (wirksam, 4.5); Lexono nur bei Bedarf anbinden und danach die Sitzung beenden; Sitzungen im Leventum-Verzeichnis starten. **Nicht verifiziert:** ob `claudeMdExcludes` auch das Laden über die Cloud-Anbindung (`add_repo`) verhindert – nur der Pfad „cwd = Lexono“ wurde getestet.

## 6. Delegations- und Parallelitätsmodell (belegt)
| Frage | Antwort |
|---|---|
| Werden echte Agententypen geladen? | Ja (10/10, Sitzungsneustart nötig; Agentenliste und `claude -p`) |
| Werden Skills bereitgestellt? | Ja per `skills:`-Frontmatter (4.4); ohne Frontmatter nicht |
| Kann der Orchestrator delegieren? | Ja: Hauptsitzung oder `claude --agent lead-architect` (4.3). Der **Subagent**-Typ `lead-architect` hat `Agent` in der Datei, aber in dieser Cloud-Sitzung keines zur Laufzeit (Sonde Phase Agentenvalidierung) |
| Können Subagenten delegieren? | In diesem Setup nein (gemessen); die Doku erlaubt standardmäßig Verschachtelung – deshalb zusätzlich `disallowedTools: Agent` |
| Welche Aufgaben parallel? | Nur mit **disjunkten Dateimengen** und ohne Schnittstellenabhängigkeit. In Phase I lief z. B. Performance (`economics.py`, `charges.py`) parallel zu Rechten (API/Dashboard) und Windows-Vorbereitung (Docs/Skript); schreibende Pakete mit gemeinsamen Dateien (Stichtag ↔ Lecks) liefen **sequenziell** |
| Dateikonflikte? | Keine technische Sperre. Verfahren: Dateimenge je Briefing; `check_file_set.py overlap` vorab, `check` danach; zentrale Dateien eine Instanz zur Zeit |
| Wer darf Dateien verändern? | Backend, Frontend, DB, Domain, QA (nur Tests), Windows, Doku: ja (Dateimenge). **Security (kein Bash/Edit/Write) und independent-reviewer: nein** (technisch) |
| Unabhängiges Review | Prüfer ≠ Autor; Security-Agent ohne Bash; `independent-reviewer` mit Hook+Runner; Orchestrator führt Befunde zusammen |

## 7. Grenzen und offene Risiken (ehrlich)
- Die Schreibsperre des `independent-reviewer` hängt an Hook **und** Runner: Der Hook wirkt nur im vertrauten Workspace und ist laut Doku ein Backstop; der Runner schützt nur Befehle, die **durch ihn** laufen. Wer den Hook umgeht (z. B. fremder Workspace ohne Trust), hat uneingeschränktes Bash des Reviewers. Das Frontmatter-Hook-Zusammenspiel im vertrauten Workspace wurde **nicht** getestet (nur per `--settings`).
- `permissionMode`-Frontmatter wird bei einigen Hauptsitzungs-Modi ignoriert; `dontAsk` wurde **nicht** eingesetzt/geprüft.
- `ro_run.sh` ist Linux-only, braucht root; **auf Windows nicht anwendbar** – dort bleibt für Prüf-Agenten nur das Profil ohne Bash (`security-privacy-engineer`). Eine Claude-Code-Sandbox gibt es auf nativem Windows nicht (Doku).
- Der Runner schützt vor Dateischreiben/Netz, **nicht** vor Kernel-Exploits oder vor dem Auslesen lesbarer Dateien im Repo.
- Dateimengen-Regel bleibt Verfahren + Detektion; kein Schutz gegen gleichzeitige Schreibzugriffe.
- `claudeMdExcludes` gegen `add_repo`-Anbindung: nicht verifiziert (5).
- Alle Agentenaussagen in den Tests sind Selbstauskünfte; belegt durch Beobachtung des Hauptprozesses sind: Werkzeugablehnungen (Hook-/EROFS-Meldungen), fehlende Canary-Dateien, Git-/Lexono-Status.

## 8. Nachtrag: Befunde des unabhängigen Reviews (Stand 052b758)
- **H1 (hoch) – behoben, Automatisiert getestet:** `.claude/hooks/ro_guard.py` ließ `scripts/ro_run.sh echo a#b; touch /x` passieren, weil `shlex` ein `#` mitten im Wort als Kommentar verwirft, Bash aber nicht. Fix: `lex.commenters = ""` und `#` in `FORBIDDEN_CHARS`; 6 neue Tests in `backend/tests/test_agent_guard.py` (jetzt 61 bestanden). Der Hook bleibt ein **Backstop**, keine Sicherheitsgrenze; die Grenze ist `ro_run.sh`.
- **M4 – behoben:** `scripts/ro_run.sh` remountet alle als `rw` eingehängten Mounts aus `/proc/self/mounts` read-only (außer `/proc`, `/sys`, `/dev/pts`, `/dev/mqueue`). Geprüft in dieser Linux-Umgebung: Repo, `/dev/shm`, `/run`, `/var/tmp` → „Read-only file system“, `/tmp` = privates tmpfs, uid 65534. `/sys/fs/cgroup` bleibt rw, ist ohne Capabilities für den Prozess nicht beschreibbar (nicht gesondert geprüft).
- **N1/N2** (`check_file_set.py` erkennt committete Änderungen nicht, `*` matcht über `/`; Validator): **offen**, dokumentiert in Abschnitt 7.
