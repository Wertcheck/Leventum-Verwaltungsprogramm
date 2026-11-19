"""Desktop-Starter: Server auf 127.0.0.1 (freier Port) + pywebview-Fenster (WebView2 unter Windows).
`--browser` startet nur den Server und gibt die URL aus (Entwicklung/Fallback).
`--demo` legt eine frische, getrennte Demo-Datenbank mit ERFUNDENEN Daten an (zufälliges Passwort).
Das Demo-Passwort wird nur im Fenster bzw. auf einer echten Konsole angezeigt – nie in eine Logdatei geschrieben.
HINWEIS: Der Fenster-Modus ist in der Linux-Entwicklungsumgebung NICHT getestet, unter Windows bisher ebenfalls nicht."""
from __future__ import annotations

import argparse
import html
import os
import secrets
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

import uvicorn

from leventum.main import create_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _log_dir(demo: bool) -> Path:
    """Logordner. Im Demo-Betrieb NIE im Demo-Datenverzeichnis (sonst ist es vor dem Seeding nicht leer/unmarkiert) und nie im echten Datenordner:
    Geschwisterordner `leventum-demo-logs`. Sonst `<Datenordner>/logs`."""
    if demo:
        from leventum import demo as demo_mod
        d = demo_mod.default_demo_dir()
        return d.parent / (d.name + "-logs")
    from leventum.config import get_settings
    return get_settings().data_dir / "logs"


def _ensure_streams(log_dir: Path) -> None:
    """Fenster-Anwendung ohne Konsole (PyInstaller --windowed): stdout/stderr sind None -> in eine Logdatei umleiten, damit Logging/Fehler nicht abstürzen.
    Kann der Logordner nicht angelegt werden, wird nach os.devnull umgeleitet (Start darf daran nicht scheitern). Es werden keine Passwörter geschrieben."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        f = open(log_dir / "leventum.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 – lebt so lange wie der Prozess
    except OSError:
        f = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    sys.stdout = sys.stdout or f
    sys.stderr = sys.stderr or f


def _wait_healthy(url: str, tries: int = 300) -> bool:
    """Health-Check bewusst OHNE Systemproxy (Loopback darf nie über einen Proxy laufen)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(tries):
        try:
            opener.open(url + "api/v1/health", timeout=1)
            return True
        except OSError:
            time.sleep(0.1)
    return False


def _start_server(app, port: int):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}/"
    if not _wait_healthy(url):
        server.should_exit = True
        raise RuntimeError("Der lokale Server ist nicht innerhalb von 30 Sekunden gestartet (Port belegt oder Start fehlgeschlagen).")
    return server, t, url


def _shutdown(holder: dict, server) -> None:
    """Beendet den Server, falls einer läuft (Fenster kann schon während des Seedings geschlossen worden sein)."""
    srv = holder.get("server") or server
    if srv is not None:
        srv.should_exit = True


def _seed_demo() -> tuple[str, Path]:
    """Frische Demo-Daten (Reset nur in markierten Demo-Verzeichnissen, siehe leventum.demo). Gibt (Passwort, Verzeichnis) zurück."""
    from leventum import demo
    d = demo.default_demo_dir()
    pw = secrets.token_urlsafe(12)
    # "--password=<pw>" (nicht getrennt): token_urlsafe liefert in ca. 1 von 64 Fällen ein Passwort mit führendem "-", das argparse sonst als Option liest
    demo.main(["--data-dir", str(d), "--reset", "--no-serve", f"--password={pw}"])
    return pw, d


def _demo_app(demo_dir: Path):
    """App für die Demo: explizite Einstellungen, `.env` wird ignoriert, demo_mode gesetzt, Daten ausschließlich im Demo-Verzeichnis."""
    from leventum.config import Settings
    return create_app(Settings(_env_file=None, data_dir=demo_dir, demo_mode=True))


def _announce_demo(pw: str, console: bool) -> None:
    """Passwort nur auf einer echten Konsole ausgeben; ohne Konsole (stdout -> Logdatei) NICHT."""
    if console:
        print(f"Demo-Zugang: Benutzer demo, Passwort {pw}", flush=True)


_SPLASH = "<html><body style='font-family:Segoe UI,Arial,sans-serif;display:grid;place-items:center;height:100vh;margin:0;color:#14284b'><div><h2>Leventum</h2><p>Demo-Daten werden vorbereitet …</p></div></body></html>"


def _credentials_page(pw: str, url: str) -> str:
    return ("<html><body style='font-family:Segoe UI,Arial,sans-serif;display:grid;place-items:center;height:100vh;margin:0;color:#14284b'><div style='max-width:520px'>"
            "<h2>Leventum – Demo</h2><p>Alle Daten sind erfunden. Zugang nur für diese Demo-Sitzung:</p>"
            f"<p>Benutzer: <b>demo</b><br>Passwort: <b>{html.escape(pw)}</b></p>"
            f"<p><a href='{html.escape(url)}' style='background:#14284b;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none'>Zur Anmeldung</a></p>"
            "</div></body></html>")


def _error_page(message: str, log_hint: str) -> str:
    return ("<html><body style='font-family:Segoe UI,Arial,sans-serif;display:grid;place-items:center;height:100vh;margin:0;color:#14284b'><div style='max-width:560px'>"
            "<h2>Leventum – Demo konnte nicht gestartet werden</h2>"
            f"<p>{html.escape(message)}</p><p style='color:#555'>Details: {html.escape(log_hint)}</p></div></body></html>")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", action="store_true", help="Nur Server starten, kein Fenster")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--demo", action="store_true", help="Frische Demo-Daten (erfunden) in getrenntem Datenverzeichnis; echte Daten bleiben unberührt")
    args = ap.parse_args(argv)
    port = args.port or _free_port()
    console = sys.stdout is not None  # vor _ensure_streams feststellen: nur dann darf ein Passwort ausgegeben werden
    log_dir = _log_dir(args.demo)
    _ensure_streams(log_dir)

    window_mode = not args.browser
    if not window_mode or not args.demo:
        # Server zuerst (normaler Start, oder Browser-Modus mit/ohne Demo)
        if args.demo:
            pw, demo_dir = _seed_demo()
            app = _demo_app(demo_dir)
        else:
            pw, app = None, create_app()
        server, t, url = _start_server(app, port)
        if args.browser:
            print(f"Leventum läuft auf {url} (Strg+C beendet)", flush=True)
            if pw:
                _announce_demo(pw, console)
            try:
                t.join()
            except KeyboardInterrupt:
                pass
            server.should_exit = True
            return
        window_url, work = url, False
    else:
        server, window_url, work = None, None, True

    try:
        import webview  # type: ignore  # optionale Abhängigkeit: pip install .[desktop]
    except ImportError:
        print("pywebview ist nicht installiert – bitte den Browser-Modus verwenden (--browser).", file=sys.stderr)
        sys.exit(3)
    try:  # Downloads (Backup, Dokumente) im eingebetteten WebView2 zulassen – Verhalten unter Windows ungetestet
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:  # ältere pywebview-Version ohne diese Einstellung
        pass
    holder: dict = {}
    if work:
        window = webview.create_window("Leventum Verwaltung (Demo)", html=_SPLASH, width=1536, height=1024, min_size=(1100, 700))

        def _prepare() -> None:  # Hintergrund-Thread: Meldung steht schon im Fenster; Fehler werden angezeigt und geloggt (kein stilles Hängen)
            try:
                pw, demo_dir = _seed_demo()
                holder["server"], _t, url = _start_server(_demo_app(demo_dir), port)
                window.load_html(_credentials_page(pw, url))
            except BaseException as exc:  # inkl. SystemExit aus demo.main
                traceback.print_exc()
                try:
                    window.load_html(_error_page(str(exc) or exc.__class__.__name__, f"Logdatei in {log_dir}"))
                except Exception:  # Fenster evtl. schon geschlossen
                    pass

        # Daemon-Thread: ein Schließen des Fensters während des Seedings hält den Prozess nicht fest
        webview.start(lambda: threading.Thread(target=_prepare, daemon=True).start())
    else:
        webview.create_window("Leventum Verwaltung", window_url, width=1536, height=1024, min_size=(1100, 700))
        webview.start()
    _shutdown(holder, server)


if __name__ == "__main__":
    main()
