"""Desktop-Starter (ohne Fenster): Logdatei bei fehlender Konsole, Demo-Seiten, Pfadauflösung im gebündelten Betrieb."""
import io
import sys

from leventum import desktop, main as app_main


def test_windowed_app_without_console_logs_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    desktop._ensure_streams(tmp_path / "daten" / "logs")
    print("Test-Meldung")
    sys.stdout.flush()
    assert "Test-Meldung" in (tmp_path / "daten" / "logs" / "leventum.log").read_text(encoding="utf-8")


def test_console_streams_are_left_alone(tmp_path, monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    monkeypatch.setattr(sys, "stderr", buf)
    desktop._ensure_streams(tmp_path / "daten")
    assert sys.stdout is buf and not (tmp_path / "daten").exists()


def test_demo_credentials_page_escapes_and_links_locally():
    page = desktop._credentials_page("pw<script>", "http://127.0.0.1:1234/")
    assert "<script>" not in page and "pw&lt;script&gt;" in page and "http://127.0.0.1:1234/" in page


def test_resource_paths_in_source_tree_point_to_alembic_and_frontend():
    assert not app_main.FROZEN
    assert (app_main.RESOURCE_DIR / "alembic.ini").is_file() and (app_main.RESOURCE_DIR / "alembic" / "env.py").is_file()
    assert app_main.DEFAULT_FRONTEND_DIST == app_main.BACKEND_DIR.parent / "frontend" / "dist"


# ---- Nachbesserung nach Zweitprüfung (H-1, L-1, L-2, L-3) ---------------------------------------------------------------------------------
import http.server
import threading as _threading
from pathlib import Path

import pytest

from leventum import demo as demo_mod


@pytest.fixture
def isolated_env(monkeypatch):
    from leventum.config import get_settings
    for v in ("LEVENTUM_DATA_DIR", "LEVENTUM_DEMO_MODE", "LEVENTUM_DATABASE_URL", "LEVENTUM_DOCUMENTS_DIR", "LEVENTUM_BACKUP_DIR"):
        monkeypatch.setenv(v, "x")  # registriert die Wiederherstellung (demo.py setzt Variablen dauerhaft im Prozess)
        monkeypatch.delenv(v)
    yield monkeypatch
    get_settings.cache_clear()


def test_demo_start_without_console_seeds_and_keeps_logs_and_password_out_of_demo_dir(isolated_env, tmp_path):
    """H-1: echter Startpfad des gebündelten Fensterprogramms (stdout/stderr None): Logordner anlegen, dann Demo-Seeding mit Reset."""
    isolated_env.setattr(demo_mod, "default_demo_dir", lambda: tmp_path / "leventum-demo")
    isolated_env.setattr(sys, "stdout", None)
    isolated_env.setattr(sys, "stderr", None)
    log_dir = desktop._log_dir(True)
    assert log_dir == tmp_path / "leventum-demo-logs" and tmp_path / "leventum-demo" not in log_dir.parents
    desktop._ensure_streams(log_dir)
    pw, demo_dir = desktop._seed_demo()          # früher: SystemExit „kein Demo-Verzeichnis (Markierung fehlt)“
    assert (demo_dir / demo_mod.MARKER).read_text().startswith("leventum-demo-v1")
    assert (demo_dir / "db").is_dir() and sorted(p.name for p in demo_dir.iterdir() if p.name == "logs") == []
    pw2, _ = desktop._seed_demo()                # zweiter Start (Reset) mit bereits vorhandenem Logordner
    sys.stdout.flush()
    log = (log_dir / "leventum.log").read_text(encoding="utf-8")
    assert pw not in log and pw2 not in log and "Passwort" not in log   # L-2: Passwort nie in der Logdatei


def test_old_behaviour_would_have_broken_demo_reset(isolated_env, tmp_path):
    """Dokumentiert die Ursache von H-1: eine Logdatei im Demo-Verzeichnis vor dem Seeding macht den Reset unmöglich."""
    d = tmp_path / "leventum-demo"
    (d / "logs").mkdir(parents=True)
    (d / "logs" / "leventum.log").write_text("x")
    with pytest.raises(SystemExit):
        demo_mod.main(["--data-dir", str(d), "--reset", "--no-serve", "--password", "demo-passwort-123"])


def test_log_dir_failure_falls_back_to_devnull_instead_of_crashing(isolated_env, tmp_path):
    blocker = tmp_path / "datei"
    blocker.write_text("x")
    isolated_env.setattr(sys, "stdout", None)
    isolated_env.setattr(sys, "stderr", None)
    desktop._ensure_streams(blocker / "logs")    # Ordner unter einer Datei: OSError -> devnull
    assert sys.stdout is not None and sys.stderr is not None
    print("läuft weiter")


def test_demo_password_is_announced_only_on_a_real_console(capsys):
    desktop._announce_demo("geheim-passwort", console=True)
    assert "geheim-passwort" in capsys.readouterr().out
    desktop._announce_demo("geheim-passwort", console=False)
    assert capsys.readouterr().out == ""


def test_shutdown_handles_window_closed_before_server_exists():
    desktop._shutdown({}, None)                  # früher: AttributeError auf None
    class S:  # noqa: D401
        should_exit = False
    s = S()
    desktop._shutdown({"server": s}, None)
    assert s.should_exit is True


def test_error_page_escapes_message():
    page = desktop._error_page("Fehler <b>x</b>", "Logdatei in C:\\x")
    assert "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;" in page


def test_health_check_ignores_system_proxy(monkeypatch):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    _threading.Thread(target=srv.serve_forever, daemon=True).start()
    for v in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(v, "http://127.0.0.1:9")   # unerreichbarer Proxy
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    try:
        assert desktop._wait_healthy(f"http://127.0.0.1:{srv.server_port}/", tries=20) is True
    finally:
        srv.shutdown()


def test_demo_app_ignores_dotenv_and_real_data_settings(isolated_env, tmp_path):
    """L-1: der Demo-Server nutzt explizite Einstellungen (keine .env, Daten nur im Demo-Verzeichnis)."""
    (tmp_path / ".env").write_text(f"LEVENTUM_DATABASE_URL=sqlite:///{(tmp_path / 'echt.sqlite3').as_posix()}\n")
    isolated_env.chdir(tmp_path)
    app = desktop._demo_app(tmp_path / "demo")
    s = app.state.settings
    assert s.demo_mode is True and s.database_url is None and s.data_dir == tmp_path / "demo"
    assert not (tmp_path / "echt.sqlite3").exists()


def test_check_target_rejects_ntfs_junction(isolated_env, tmp_path):
    """L-1: Junctions (ab Python 3.12 über Path.is_junction erkennbar) werden wie Symlinks abgelehnt."""
    isolated_env.setattr(Path, "is_junction", lambda self: self.name == "junction", raising=False)
    with pytest.raises(SystemExit):
        demo_mod._check_target(tmp_path / "junction")


def test_password_with_leading_dash_is_accepted_by_demo_cli(isolated_env, tmp_path):
    """Gefunden im Gesamtlauf: secrets.token_urlsafe kann mit '-' beginnen; getrennt übergeben ('--password', '-abc…') bricht argparse mit Exit 2 ab."""
    seen = {}
    isolated_env.setattr(demo_mod, "default_demo_dir", lambda: tmp_path / "leventum-demo")
    isolated_env.setattr(demo_mod, "main", lambda argv: seen.update(argv=argv))
    isolated_env.setattr("secrets.token_urlsafe", lambda n=12: "-abcdefghijklmnop")
    desktop._seed_demo()
    assert "--password=-abcdefghijklmnop" in seen["argv"] and "--password" not in seen["argv"]
    # und die echte CLI parst diese Form (Ziel ist eine Datei -> Abbruch mit Textmeldung, NICHT Argparse-Fehler Exit 2)
    f = tmp_path / "datei"
    f.write_text("x")
    isolated_env.undo()
    with pytest.raises(SystemExit) as e:
        demo_mod.main(["--data-dir", str(f), "--no-serve", "--password=-abcdefghijklmnop"])
    assert isinstance(e.value.code, str)


def test_light_titlebar_sets_white_caption_without_title_and_icon():
    """Titelleiste hell, ohne Titeltext/Symbol – geprüft mit einer Attrappe der Windows-API (kein Windows-Test)."""
    from types import SimpleNamespace

    from leventum import desktop

    calls: list = []

    class User32:
        def SetWindowTextW(self, h, t): calls.append(("title", h, t))
        def GetWindowLongW(self, h, i): calls.append(("getlong", i)); return 0x100
        def SetWindowLongW(self, h, i, v): calls.append(("setlong", i, v))
        def SetWindowPos(self, *a): calls.append(("pos",) + a)

    class Dwm:
        def DwmSetWindowAttribute(self, h, a, ref, size): calls.append(("dwm", a, ref.value, size))

    class Val:
        def __init__(self, v): self.value = v

    api = SimpleNamespace(user32=User32(), dwm=Dwm(), c_int=Val, byref=lambda v: v)
    desktop._light_titlebar(1234, api)
    assert ("dwm", 20, 0, 4) in calls                  # kein dunkler Modus
    assert ("dwm", 35, 0x00FFFFFF, 4) in calls         # weiße Titelleiste
    assert ("title", 1234, "") in calls                # kein Titeltext
    assert ("setlong", -20, 0x101) in calls            # Fenstersymbol aus (DLGMODALFRAME)


def test_light_titlebar_never_raises():
    from types import SimpleNamespace

    from leventum import desktop

    def boom(*a, **k): raise OSError("x")
    desktop._light_titlebar(1, SimpleNamespace(user32=SimpleNamespace(), dwm=SimpleNamespace(DwmSetWindowAttribute=boom), c_int=int, byref=lambda v: v))
    desktop._light_titlebar(1)  # unter Linux ohne Wirkung
    desktop._style_window(SimpleNamespace())  # Fenster ohne native-Handle: ignoriert
