"""Sicherheit und Datensicherung (Master-Review Phase F): Header, Verschlüsselung der Backups, Rechtematrix, Restore-Drill mit Neustart."""
import io
import os
import sqlite3
import zipfile
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from leventum.config import Settings
from leventum.main import create_app
from leventum.models import AppUser, Document, Role
from leventum.security.passwords import hash_password
from leventum.security.permissions import ROLE_PERMISSIONS, has_permission
from leventum.services import backup as B, backup_crypto as BC, integrity
from tests.conftest import PW

V = "/api/v1"
H = {"X-Leventum-Client": "1"}


# ---- Sicherheitsheader ---------------------------------------------------------------------------------------------------------------------------
def test_security_headers_on_api_and_spa(tmp_path):
    dist = tmp_path / "dist"; (dist / "assets").mkdir(parents=True); (dist / "index.html").write_text("<html></html>")
    app = create_app(Settings(data_dir=tmp_path / "d", frontend_dist=dist))
    c = TestClient(app, headers=H)
    for resp in (c.get(V + "/health"), c.get("/"), c.post(V + "/auth/login", json={"username": "x", "password": "y"}), TestClient(app).post(V + "/auth/login", json={})):
        h = resp.headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
        assert "unsafe-eval" not in csp and "http://" not in csp and "https://" not in csp and "script-src 'self'" in csp  # keine externen Quellen, kein eval
    assert c.get(V + "/health").headers["cache-control"] == "no-store"


# ---- Verschlüsselung ---------------------------------------------------------------------------------------------------------------------------------
PASS = "korrekte-pferd-batterie"


def test_encryption_roundtrip_multi_chunk_and_no_plaintext(tmp_path):
    plain = tmp_path / "p.bin"; plain.write_bytes(b"GEHEIM-Mustermann-IBAN-DE89" + os.urandom(2_500_000))
    enc, dec = tmp_path / "p.enc", tmp_path / "p.dec"
    BC.encrypt_file(plain, enc, PASS)
    assert BC.is_encrypted(enc) and not BC.is_encrypted(plain)
    raw = enc.read_bytes()
    assert b"GEHEIM" not in raw and b"Mustermann" not in raw and raw.startswith(BC.MAGIC)
    BC.decrypt_file(enc, dec, PASS)
    assert dec.read_bytes() == plain.read_bytes()
    enc2 = tmp_path / "p2.enc"; BC.encrypt_file(plain, enc2, PASS)
    assert enc2.read_bytes() != raw  # zufälliges Salz/Nonce: gleiche Eingabe ergibt andere Datei


def test_encryption_detects_wrong_passphrase_tampering_truncation_and_appending(tmp_path):
    plain = tmp_path / "p.bin"; plain.write_bytes(os.urandom(2_200_000))
    enc = tmp_path / "p.enc"; BC.encrypt_file(plain, enc, PASS)
    raw = enc.read_bytes()
    cases = {"falsche Passphrase": (raw, "anders-aber-lang-genug"), "ein Bit verändert": (raw[:5000] + bytes([raw[5000] ^ 1]) + raw[5001:], PASS),
             "abgeschnitten (letzter Block fehlt)": (raw[: len(raw) - 1_000], PASS), "am Ende angehängt": (raw + b"\x00\x00\x00\x05abcde", PASS),
             "nur Kopf": (raw[:30], PASS), "kein Leventum-Format": (b"PK\x03\x04 zip", PASS)}
    for name, (data, pw) in cases.items():
        f = tmp_path / "x.enc"; f.write_bytes(data)
        out = tmp_path / "x.out"
        with pytest.raises(BC.CryptoError):
            BC.decrypt_file(f, out, pw)
        assert not out.exists(), name  # keine halb entschlüsselten Reste
    with pytest.raises(BC.CryptoError) as e:
        BC.encrypt_file(plain, tmp_path / "w.enc", "kurz")
    assert e.value.code == "weak_passphrase"


# ---- Backup/Restore praktisch (API) --------------------------------------------------------------------------------------------------------------
def test_encrypted_backup_via_api_verify_restore_and_wrong_passphrase(auth_client, settings, app):
    c = auth_client
    doc = c.post(V + "/documents", data={"entity_type": "party", "entity_id": c.post(V + "/parties", json={"kind": "person", "last_name": "Vor Backup"}).json()["id"], "doc_type": "sonstige"},
                 files={"file": ("a.pdf", b"%PDF-1.4 vor dem Backup", "application/pdf")}).json()
    r = c.post(V + "/system/backups", json={"passphrase": PASS}).json()
    assert r["encrypted"] is True and r["verified"] is True and r["id"].endswith(".zip.enc")
    listing = c.get(V + "/system/backups").json()["items"]
    assert listing[0]["encrypted"] is True
    raw = (settings.backups_path / r["id"]).read_bytes()
    assert b"Vor Backup" not in raw and b"PK\x03\x04" not in raw[:64]
    assert c.post(V + f"/system/backups/{r['id']}/verify", json={}).json()["ok"] is False  # ohne Passphrase
    assert c.post(V + f"/system/backups/{r['id']}/verify", json={"passphrase": "falsche-passphrase-xx"}).json()["ok"] is False
    assert c.post(V + f"/system/backups/{r['id']}/verify", json={"passphrase": PASS}).json()["ok"] is True
    c.post(V + "/parties", json={"kind": "person", "last_name": "Nach Backup"})
    bad = c.post(V + f"/system/backups/{r['id']}/restore", json={"confirm": True, "passphrase": "falsche-passphrase-xx"})
    assert bad.status_code == 400
    with app.state.session_factory() as db:
        from leventum.models import Party
        assert {p.display_name for p in db.scalars(select(Party))} >= {"Vor Backup", "Nach Backup"}  # fehlgeschlagene Wiederherstellung lässt den Bestand unverändert
    ok = c.post(V + f"/system/backups/{r['id']}/restore", json={"confirm": True, "passphrase": PASS})
    assert ok.status_code == 200
    with app.state.session_factory() as db:
        names = {p.display_name for p in db.scalars(select(Party))}
        assert "Vor Backup" in names and "Nach Backup" not in names
    assert c.post(V + "/system/backups", json={"passphrase": "kurz"}).status_code == 400  # zu schwache Passphrase


# ---- Restore-Drill: Daten + Dokumente + Neustart + Integrität ----------------------------------------------------------------------------------
def sha_tree(root: Path) -> dict:
    import hashlib
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("passphrase", [None, PASS])
def test_restore_drill_database_documents_restart_and_integrity(tmp_path, passphrase):
    s = Settings(data_dir=tmp_path / "data", frontend_dist=tmp_path / "x")
    app = create_app(s)
    c = TestClient(app, headers=H)
    assert c.post(V + "/auth/setup", json={"username": "admin", "password": PW}).status_code == 200
    own = c.post(V + "/parties", json={"kind": "company", "company_name": "Leventum", "is_own_organization": True}).json()
    owner = c.post(V + "/parties", json={"kind": "person", "last_name": "Eigentümer", "roles": ["owner"]}).json()
    ten = c.post(V + "/parties", json={"kind": "person", "last_name": "Mieter", "roles": ["tenant"]}).json()
    prop = c.post(V + "/properties", json={"name": "H", "property_type": "wohnung", "owner_party_id": owner["id"]}).json()
    unit = c.post(V + f"/properties/{prop['id']}/units", json={"unit_number": "1", "living_area": "50.00"}).json()
    types = {t["code"]: t["id"] for t in c.get(V + "/lease-types").json()["items"]}
    rp, ru = (c.post(V + "/rentable-units", json={"property_id": prop["id"], **extra}).json() for extra in ({}, {"unit_id": unit["id"]}))
    main = c.post(V + "/leases", json={"kind": "main", "lease_type_id": types["hauptmiete"], "start_date": "2026-01-01", "subletting_permitted": True,
                                       "parties": [{"party_id": owner["id"], "role": "lessor"}, {"party_id": own["id"], "role": "lessee"}], "rentable_unit_ids": [rp["id"]]}).json()
    c.post(V + f"/leases/{main['id']}/terms", json={"valid_from": "2026-01-01", "base_rent": "800.00"}); c.post(V + f"/leases/{main['id']}/activate")
    sub = c.post(V + "/leases", json={"kind": "sub", "lease_type_id": types["wohnraum_unbefristet"], "start_date": "2026-01-01",
                                      "parties": [{"party_id": own["id"], "role": "lessor"}, {"party_id": ten["id"], "role": "lessee"}], "rentable_unit_ids": [ru["id"]]}).json()
    c.post(V + f"/leases/{sub['id']}/terms", json={"valid_from": "2026-01-01", "base_rent": "1000.00"}); c.post(V + f"/leases/{sub['id']}/activate")
    c.post(V + "/charges/generate", json={"allow_backdated": True, "from_month": "2026-01-01", "through_month": "2026-02-01"})
    rent = c.get(V + f"/charges?lease_id={sub['id']}").json()["items"][-1]
    c.post(V + "/payments", json={"direction": "in", "booking_date": "2026-01-05", "amount": "400.00", "allocations": [{"charge_id": rent["id"], "amount": "400.00"}]})
    for i in range(3):
        c.post(V + "/documents", data={"entity_type": "lease", "entity_id": sub["id"], "doc_type": "mietvertrag"}, files={"file": (f"d{i}.pdf", b"%PDF-1.4 " + os.urandom(5000), "application/pdf")})
    snap_docs, snap_db = sha_tree(s.documents_path), c.get(V + "/economics?start=2026-01-01&end=2026-02-28").json()["soll"]
    backup = c.post(V + "/system/backups", json={"passphrase": passphrase} if passphrase else {}).json()
    assert backup["verified"] is True
    # Schaden nach dem Backup: Daten ändern, Datei löschen, Datei verändern
    c.post(V + "/parties", json={"kind": "person", "last_name": "Nach Backup"})
    victims = sorted(s.documents_path.rglob("*.pdf"))
    victims[0].unlink(); victims[1].write_bytes(b"%PDF-1.4 beschaedigt")
    (s.documents_path / "zusatz.pdf").write_bytes(b"%PDF neu")
    assert c.post(V + f"/system/backups/{backup['id']}/restore", json={"confirm": True, **({"passphrase": passphrase} if passphrase else {})}).status_code == 200
    # NEUSTART: neue Anwendungsinstanz auf demselben Datenverzeichnis
    app2 = create_app(s)
    c2 = TestClient(app2, headers=H)
    assert c2.post(V + "/auth/login", json={"username": "admin", "password": PW}).status_code == 200  # Benutzer/Passwort überleben die Wiederherstellung
    assert sha_tree(s.documents_path) == snap_docs  # Dokumente byte-genau wie zum Backup-Zeitpunkt (Schaden und Zusatzdatei sind weg)
    assert c2.get(V + "/economics?start=2026-01-01&end=2026-02-28").json()["soll"] == snap_db
    assert [p["display_name"] for p in c2.get(V + "/parties?q=nach").json()["items"]] == []
    integ = c2.get(V + "/system/integrity").json()
    assert integ["ok"] is True and integ["documents"]["ok"] is True  # keine Daten- oder Dateischäden
    assert c2.get(V + "/documents/verify-all").json()["ok"] is True
    con = sqlite3.connect(s.data_dir / "db" / "leventum.sqlite3")
    assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005" and con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert any("pre-restore" in p.name for p in s.backups_path.iterdir())  # Sicherheitskopie des Zustands vor der Wiederherstellung


def test_restore_rejects_corrupt_backup_and_keeps_state(auth_client, settings, app):
    c = auth_client
    r = c.post(V + "/system/backups", json={}).json()
    path = settings.backups_path / r["id"]
    with zipfile.ZipFile(path) as z, zipfile.ZipFile(settings.backups_path / "leventum-backup-defekt.zip", "w") as out:
        for n in z.namelist():
            out.writestr(n, b"kaputt" if n == "database.sqlite3" else z.read(n))  # Inhalt passt nicht zur Prüfsumme
    c.post(V + "/parties", json={"kind": "person", "last_name": "Bleibt"})
    bad = c.post(V + "/system/backups/leventum-backup-defekt.zip/restore", json={"confirm": True})
    assert bad.status_code == 400
    assert any(p["display_name"] == "Bleibt" for p in c.get(V + "/parties").json()["items"])


# ---- Rechtematrix --------------------------------------------------------------------------------------------------------------------------------------
# (Methode, Pfad, benötigtes Recht): jede Route muss genau für Rollen mit diesem Recht erreichbar sein
MATRIX = [("GET", "/parties", "master:read"), ("POST", "/parties", "master:write"), ("PATCH", "/parties/1", "master:write"), ("POST", "/properties", "master:write"),
          ("PATCH", "/rooms/1", "master:write"), ("POST", "/leases", "master:write"), ("POST", "/leases/1/activate", "master:write"),
          ("GET", "/charges", "finance:read"), ("POST", "/charges/generate", "finance:write"), ("POST", "/charges/preview", "finance:read"), ("POST", "/payments", "finance:write"),
          ("POST", "/payments/1/reverse", "finance:write"), ("GET", "/deposits", "finance:read"), ("POST", "/deposits", "finance:write"), ("POST", "/dunning/prepare", "finance:write"),
          ("POST", "/dunning/notices/1/approve", "finance:write"), ("POST", "/bank/transactions/1/confirm", "finance:write"), ("POST", "/bank/accounts", "finance:write"),
          ("GET", "/economics?start=2026-01-01&end=2026-01-31", "finance:read"), ("GET", "/utility-statements", "finance:read"), ("POST", "/utility-statements", "finance:write"),
          ("GET", "/tasks", "task:read"), ("POST", "/tasks", "task:write"), ("POST", "/communications", "task:write"), ("GET", "/repairs", "repair:read"), ("POST", "/repairs", "repair:write"),
          ("GET", "/documents/search", "document:read"), ("POST", "/documents/1/delete", "document:write"), ("POST", "/documents/1/purge", "document:purge"),
          ("GET", "/system/backups", "system:backup"), ("POST", "/system/backups", "system:backup"), ("GET", "/system/integrity", "system:backup"),
          ("GET", "/dashboard", "dashboard:read"), ("GET", "/reminders", "dashboard:read"), ("GET", "/tenants", "master:read"), ("GET", "/history?entity_type=party&entity_id=1", "master:read")]


def make_client(app, role):
    name = f"u_{role}"
    with app.state.session_factory() as db:
        if not db.scalar(select(AppUser).where(AppUser.username == name)):
            db.add(AppUser(username=name, display_name=name, password_hash=hash_password(PW), role_id=db.scalar(select(Role.id).where(Role.code == role))))
            db.commit()
    c = TestClient(app, headers=H)
    assert c.post(V + "/auth/login", json={"username": name, "password": PW}).status_code == 200
    return c


@pytest.mark.parametrize("role", sorted(ROLE_PERMISSIONS))
def test_permission_matrix_every_route_is_wired_to_the_documented_permission(auth_client, app, role):
    c = make_client(app, role)
    wrong = []
    for method, path, perm in MATRIX:
        r = c.request(method, V + path, json={} if method in ("POST", "PATCH", "PUT") else None)
        allowed = has_permission(role, perm)
        if allowed and r.status_code == 403:
            wrong.append(f"{role} {method} {path}: sollte erlaubt sein, war 403")
        if not allowed and r.status_code != 403:
            wrong.append(f"{role} {method} {path}: sollte 403 sein, war {r.status_code}")
    assert wrong == []
    assert c.get(V + "/auth/me").json()["role"] == role
