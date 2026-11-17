# ADR 0003 – Vertrauensgrenze zwischen Entwicklungsagents und Review-Ebene

Status: **Teilweise umgesetzt, Hauptziel NICHT erreicht (Blocker, Entscheidung beim Menschen offen).** Stand: HEAD f90c137 + ungecommittete Arbeit dieser Phase.

## Kontext
Alle Entwicklungsagents laufen als root im selben Firecracker-microVM-Kernel wie der Orchestrator (CapEff 000001fffeffffff, NoNewPrivs 0, Seccomp 0). Ziel: Entwicklungsagents dürfen die Sicherheitsebene (Runner, Hook, Reviewer-Profile, Hash-Anker, Schlüssel, Trust-Konfiguration, Review-Protokolle, Git-Metadaten der Review-Umgebung) nicht verändern können, auch nicht als root; der Reviewer prüft ausschließlich einen festgelegten Commit, ohne Entwicklungs-Secrets und ohne GitHub-Schreibwerkzeuge.

## Entscheidung
1. **Varianten A (separater Benutzer/Mounts) und B1 (Container im selben Kernel) werden als Sicherheitsgrenze gegen root verworfen** – A gemessen; B1: **runc gemessen, Docker nur Daemon-Start gemessen (Container-Angriffe per Analogie, nicht gemessen)** (`PHASE_I_ISOLATION_ARCHITECTURE.md` §3).
2. **Einzige Variante, die den Dev-root kernelseitig trennt: B2 (getrennte Cloud-Sitzung/microVM mit festem `source_revision`, volle 40-hex-SHA)** – plus Remote-Anker (C3) und menschliche Gegenzeichnung (C2). B2 ist **nicht als vollwertige Isolation zulässig**, weil die Plattform dem Reviewer-Sitzungs-VM Entwicklungs-Credentials gleicher Art mitgibt (GITHUB_TOKEN/GH_TOKEN, AWS-/gcloud-Variablen, Session-Ingress-/Messaging-Token) und `api.github.com` auch in einer Umgebung ohne erlaubte Hosts erreichbar bleibt (gemessen, Probe 4). Dies lässt sich über die verfügbaren Plattform-Schnittstellen (`create_session`, `create_environment`, `permission_mode`, `extra_allowed_tools`; getestete Parameter) nicht abschalten; `permission_mode` darf den der Eltern-Sitzung nicht überschreiten.
3. **`independent-reviewer-static` bleibt das einzige Standard-Reviewer-Profil**, ausdrücklich ohne Behauptung vollständiger Isolation.
4. **Umgesetzt wurde nur, was real und testbar ist:** `scripts/review_handoff.py` (Manifest aus dem Git-Objekt, Prüfung eines Review-Checkouts/der Umgebung, Bindung eines Review-Berichts an Commit und Prüfumgebung, Remote-Anker-Prüfung) mit Tests. Es ist ein Integritätswerkzeug, kein Isolationsmechanismus.
5. **Keine scheinbare Sicherheitslösung** (kein Container im selben Kernel, keine zusätzlichen chattr-/uid-Schichten als „Isolation“).

## Zusätzliche Vorbehalte (aus dem unabhängigen Lesereview)
- **Remote-Anker:** Ein Dev-root besitzt die GitHub-Credentials der Sitzung und kann den Remote-Branch selbst verschieben/neue Commits pushen; `remote-check` (vorher/nachher) erkennt das nur, wenn der Orchestrator den erwarteten Commit außerhalb des Dev-Zugriffs hält – das ist derzeit nicht gegeben.
- **`check-report`:** `tools`, `attestation.env_check` und `findings` sind Selbstauskunft des Reviewers (der Plattform-Auszug enthält kein Werkzeugfeld); gebunden werden nur Commit, Tree, Manifest-Hash, Nonce, Umgebungs- und Sitzungs-ID gegen die vom Orchestrator gehaltenen Werte/den Plattform-Auszug. `PASS tools` heißt „der Bericht behauptet nur erlaubte Werkzeuge“.
- **`verify --env-check` auf B2:** liefert wegen der plattformseitig vorhandenen Tokens (GH_TOKEN, AWS_*, …) zwangsläufig BLOCKED; ein OK-Bericht ist auf dieser Plattform nicht erreichbar – das ist das erwartete, ehrliche Ergebnis, kein Defekt. Der Env-Check erfasst bekannte Namensmuster des eigenen Prozesses (nicht GIT_CONFIG_*/GIT_ASKPASS).

## Folgen
- Die Aussage „Entwicklungsagents können die Schutzebene technisch nicht verändern“ bleibt **unzulässig**.
- Reviewer-Sitzungen auf B2 sind „zweite Meinung in getrenntem Kernel“; ihr Ergebnis ist Daten, mit Pflicht-Gegenprüfung (`check-report`, Remote-Tip vorher/nachher) und menschlicher Bestätigung.
- Voraussetzungen für eine echte Lösung: siehe `PHASE_I_ISOLATION_ARCHITECTURE.md` §6 (Infrastrukturplan).

## Alternativen
A, B1, C-Host (kein eigener Host belegt), reine Dokumentation (verworfen).
