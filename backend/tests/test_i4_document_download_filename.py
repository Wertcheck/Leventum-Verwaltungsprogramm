"""Befund R4 (Windows-Vorbereitung): Download mit Dateinamen außerhalb von Latin-1 darf keinen Serverfehler auslösen (RFC 6266/5987)."""
import pytest
from urllib.parse import unquote

from leventum.api.finance import _content_disposition

V = "/api/v1"


@pytest.mark.parametrize("name,ascii_part,utf8_part", [
    ("Vertrag_Müller.pdf", "Vertrag_Muller.pdf", "Vertrag_Müller.pdf"),
    ("Vertrag_€_2026.pdf", "Vertrag__2026.pdf", "Vertrag_€_2026.pdf"),
    ("Dokument – final.pdf", "Dokument  final.pdf", "Dokument – final.pdf"),
    ("договор.pdf", ".pdf", "договор.pdf"),
    ('evil"; x=y.pdf', "evil; x=y.pdf", "evil; x=y.pdf"),
])
def test_content_disposition_is_ascii_and_carries_utf8_name(name, ascii_part, utf8_part):
    h = _content_disposition(name)
    h.encode("latin-1")                                   # Header-Werte müssen Latin-1-kodierbar sein
    assert h.isascii()
    assert h.startswith("attachment; filename=\"") and "filename*=UTF-8''" in h
    assert unquote(h.split("filename*=UTF-8''")[1]) == utf8_part
    assert '"' not in h.split("filename=\"", 1)[1].rsplit('"; filename*', 1)[0]  # kein Anführungszeichen im ASCII-Fallback


def test_content_disposition_strips_control_chars_and_path_separators():
    h = _content_disposition("a\r\nSet-Cookie: x=1/../b.pdf")
    assert "\r" not in h and "\n" not in h and "/" not in h.split("filename*=UTF-8''")[1].replace("%2F", "")
    assert _content_disposition("").startswith('attachment; filename="dokument"')


@pytest.mark.parametrize("name", ["Vertrag_€_2026.pdf", "Dokument – final.pdf", "договор.pdf"])
def test_download_with_non_latin1_filename_works_over_http(auth_client, name):
    c = auth_client
    party = c.post(V + "/parties", json={"kind": "person", "first_name": "A", "last_name": "B", "roles": ["tenant"]}).json()
    r = c.post(V + "/documents", data={"entity_type": "party", "entity_id": str(party["id"]), "doc_type": "sonstige"},
               files={"file": (name, b"%PDF-1.4 test", "application/pdf")})
    assert r.status_code == 201, r.text
    d = c.get(V + f"/documents/{r.json()['id']}/download")
    assert d.status_code == 200 and d.content == b"%PDF-1.4 test"
    assert "filename*=UTF-8''" in d.headers["content-disposition"]
