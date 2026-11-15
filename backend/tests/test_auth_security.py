from datetime import timedelta

from sqlalchemy import select
from fastapi.testclient import TestClient

from leventum.db.base import utcnow
from leventum.models import AppUser, AuditEvent, UserSession
from tests.conftest import PW

PUBLIC = {("GET", "/api/v1/health"), ("GET", "/api/v1/auth/status"), ("POST", "/api/v1/auth/setup"),
          ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/logout")}


def test_every_route_except_whitelist_requires_auth(app):
    # app.routes ist in neueren FastAPI-Versionen lazy; das OpenAPI-Schema listet alle registrierten Operationen.
    routes = [(m.upper(), path) for path, ops in app.openapi()["paths"].items() for m in ops]
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    checked = 0
    for method, path in routes:
        if (method, path) in PUBLIC or not path.startswith("/api/"):
            continue
        url = path.replace("{backup_id}", "x")
        resp = c.request(method, url, json={})
        assert resp.status_code == 401, f"{method} {path} ist nicht geschützt ({resp.status_code})"
        checked += 1
    assert checked >= 4


def test_setup_creates_admin_once_and_hashes_password(auth_client, app):
    with app.state.session_factory() as db:
        u = db.scalar(select(AppUser))
        assert u.password_hash.startswith("$argon2id$") and PW not in u.password_hash
    r = auth_client.post("/api/v1/auth/setup", json={"username": "x", "password": PW})
    assert r.status_code == 409


def test_setup_rejects_weak_password(client):
    r = client.post("/api/v1/auth/setup", json={"username": "admin", "password": "kurz"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "weak_password"
    assert client.get("/api/v1/auth/status").json()["setup_required"] is True


def test_login_logout_cookie_flags_and_revocation(auth_client):
    c = auth_client
    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": PW})
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc
    assert c.get("/api/v1/auth/me").json()["username"] == "admin"
    c.post("/api/v1/auth/logout")
    assert c.get("/api/v1/auth/me").status_code == 401


def test_token_not_stored_in_plaintext(auth_client, app):
    token = auth_client.cookies.get("leventum_session")
    with app.state.session_factory() as db:
        for s in db.scalars(select(UserSession)):
            assert s.token_hash != token and len(s.token_hash) == 64


def test_lockout_after_failed_attempts_and_audit(auth_client, app):
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    for _ in range(5):
        assert c.post("/api/v1/auth/login", json={"username": "admin", "password": "falsch"}).status_code == 401
    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": PW})
    assert r.status_code == 429
    with app.state.session_factory() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.login_failed")) is not None
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.login_blocked")) is not None


def test_unknown_user_gets_same_error_as_wrong_password(auth_client, app):
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    a = c.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    b = c.post("/api/v1/auth/login", json={"username": "admin", "password": "x"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_expired_and_idle_sessions_rejected(auth_client, app):
    with app.state.session_factory() as db:
        s = db.scalar(select(UserSession))
        s.last_seen_at = utcnow() - timedelta(days=2)
        db.commit()
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_csrf_header_required_for_writes(app):
    c = TestClient(app)  # ohne Header
    assert c.post("/api/v1/auth/login", json={"username": "a", "password": "b"}).status_code == 403


def test_untrusted_host_rejected(app):
    c = TestClient(app, base_url="http://evil.example.com")
    assert c.get("/api/v1/health").status_code == 400


def test_openapi_docs_disabled(client):
    assert client.get("/openapi.json").status_code in (404,)
