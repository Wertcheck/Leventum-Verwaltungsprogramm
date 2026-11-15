import pytest
from fastapi.testclient import TestClient

from leventum.config import Settings
from leventum.main import create_app

PW = "ein-langes-passwort-123"


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", frontend_dist=tmp_path / "nodist")


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app, headers={"X-Leventum-Client": "1"}) as c:
        yield c


@pytest.fixture
def auth_client(client):
    r = client.post("/api/v1/auth/setup", json={"username": "admin", "password": PW, "display_name": "Admin"})
    assert r.status_code == 200, r.text
    return client
