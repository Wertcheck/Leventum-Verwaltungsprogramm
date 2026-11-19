"""Demo-Starter: Seeding über die REST-API, berechnete Kennzahlen, Demo-Kennzeichnung (alle Daten erfunden)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from leventum import demo


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LEVENTUM_DATA_DIR", "x")  # stellt die Umgebung nach dem Test wieder her (build_demo setzt sie selbst)
    mp.setenv("LEVENTUM_DEMO_MODE", "1")
    from leventum.config import get_settings
    app, summary = demo.build_demo(tmp_path_factory.mktemp("demo"), "demo-passwort-123", today=date.today())
    mp.undo()  # Umgebung sofort zurücksetzen: die App läuft mit explizit übergebenen Settings (app.state.settings)
    get_settings.cache_clear()
    yield app, summary


def _login(app):
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    r = c.post("/api/v1/auth/login", json={"username": "demo", "password": "demo-passwort-123"})
    assert r.status_code == 200, r.text
    return c


def test_demo_summary_counts(built):
    _, s = built
    assert s["properties"] == 2 and s["units"] == 5 and s["active_subleases"] == 7
    assert s["payments"] > 100 and s["occupancy_rate"] == "87.5"


def test_demo_health_flag_and_dashboard_kpis_match_data(built):
    app, _ = built
    c = _login(app)
    assert c.get("/api/v1/health").json() == {"status": "ok", "demo": True}
    k = {x["key"]: x for x in c.get("/api/v1/dashboard").json()["kpis"]}
    assert k["properties"]["value"] == 2 and k["units"]["value"] == 5
    assert k["occupancy_rate"]["format"] == "percent" and k["occupancy_rate"]["value"] == "87.5"
    assert k["overdue_tasks"]["value"] == 1 and k["open_tasks"]["value"] == 4
    assert k["physical_vacancy"]["value"] == 1
    assert k["open_receivables"]["value"] == "4870.00"


@pytest.fixture
def isolated_env(monkeypatch):
    """demo.main/build_demo setzen os.environ dauerhaft; hier wird alles danach zurückgesetzt."""
    from leventum.config import get_settings
    for v in ("LEVENTUM_DATA_DIR", "LEVENTUM_DEMO_MODE", "LEVENTUM_DATABASE_URL", "LEVENTUM_DOCUMENTS_DIR", "LEVENTUM_BACKUP_DIR"):
        monkeypatch.setenv(v, "x")  # setenv+delenv: registriert die Wiederherstellung (auch für später von demo.py gesetzte Variablen)
        monkeypatch.delenv(v)
    yield monkeypatch
    get_settings.cache_clear()


@pytest.mark.parametrize("var", ["LEVENTUM_DATABASE_URL", "LEVENTUM_DOCUMENTS_DIR", "LEVENTUM_BACKUP_DIR"])
def test_demo_refuses_when_env_points_to_real_data(isolated_env, tmp_path, var):
    isolated_env.setenv(var, str(tmp_path / "echt"))
    target = tmp_path / "demo"
    with pytest.raises(SystemExit):
        demo.main(["--data-dir", str(target), "--no-serve"])
    assert not target.exists()
    with pytest.raises(SystemExit):
        demo.build_demo(tmp_path / "demo2", "demo-passwort-123")


def test_demo_refuses_real_data_dir_home_and_parents(isolated_env, tmp_path):
    from pathlib import Path

    from leventum.config import default_data_dir
    for bad in (default_data_dir(), default_data_dir().parent, Path.home(), Path("/"), Path.cwd()):
        with pytest.raises(SystemExit):
            demo.main(["--data-dir", str(bad), "--no-serve"])


def test_demo_refuses_file_symlink_short_password_and_bad_marker(isolated_env, tmp_path):
    f = tmp_path / "datei"
    f.write_text("x")
    with pytest.raises(SystemExit):
        demo.main(["--data-dir", str(f), "--no-serve"])
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    with pytest.raises(SystemExit):
        demo.main(["--data-dir", str(link), "--no-serve"])
    with pytest.raises(SystemExit):
        demo.main(["--data-dir", str(tmp_path / "neu"), "--password", "kurz", "--no-serve"])
    assert not (tmp_path / "neu").exists()
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / demo.MARKER).write_text("")  # Markierung ohne die Kennung
    (fake / "daten.txt").write_text("nicht löschen")
    with pytest.raises(SystemExit):
        demo.main(["--data-dir", str(fake), "--reset", "--no-serve"])
    assert (fake / "daten.txt").exists()


def test_demo_is_repeatable_with_reset_and_cleans_up_failed_build(isolated_env, tmp_path, monkeypatch):
    target = tmp_path / "demo"
    demo.main(["--data-dir", str(target), "--password", "demo-passwort-123", "--no-serve"])
    assert (target / demo.MARKER).read_text().startswith("leventum-demo-v1")
    with pytest.raises(SystemExit):  # ohne --reset kein Überschreiben
        demo.main(["--data-dir", str(target), "--password", "demo-passwort-123", "--no-serve"])
    demo.main(["--data-dir", str(target), "--reset", "--password", "demo-passwort-123", "--no-serve"])
    assert (target / demo.MARKER).exists()
    bad = tmp_path / "scheitert"
    monkeypatch.setattr(demo, "build_demo", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Seed-Fehler")))
    with pytest.raises(RuntimeError):
        demo.main(["--data-dir", str(bad), "--no-serve"])
    assert not bad.exists()  # kein halbfertiger, markierter Bestand


def test_health_demo_flag_comes_from_app_settings_not_environment(client, monkeypatch):
    monkeypatch.setenv("LEVENTUM_DEMO_MODE", "1")
    assert client.get("/api/v1/health").json() == {"status": "ok", "demo": False}


def test_demo_marker_protects_foreign_directories(tmp_path):
    foreign = tmp_path / "wichtig"
    foreign.mkdir()
    (foreign / "daten.txt").write_text("nicht löschen")
    with pytest.raises(SystemExit):
        demo.main(["--data-dir", str(foreign), "--reset", "--no-serve"])
    assert (foreign / "daten.txt").exists()
