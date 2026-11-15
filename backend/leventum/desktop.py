"""Desktop-Starter: Server auf 127.0.0.1 (freier Port) + pywebview-Fenster (WebView2 unter Windows).
`--browser` startet nur den Server und gibt die URL aus (Entwicklung/Fallback).
HINWEIS: Der Fenster-Modus ist in der Linux-Entwicklungsumgebung NICHT getestet."""
from __future__ import annotations

import argparse
import socket
import threading
import time
import urllib.request

import uvicorn

from leventum.main import create_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", action="store_true", help="Nur Server starten, kein Fenster")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    port = args.port or _free_port()
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}/"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "api/v1/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    if args.browser:
        print(f"Leventum läuft auf {url} (Strg+C beendet)")
        try:
            t.join()
        except KeyboardInterrupt:
            pass
    else:
        import webview  # type: ignore  # optionale Abhängigkeit: pip install .[desktop]

        webview.create_window("Leventum Verwaltung", url, width=1536, height=1024, min_size=(1100, 700))
        webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()
