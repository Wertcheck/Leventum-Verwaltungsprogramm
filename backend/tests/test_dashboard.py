def test_dashboard_has_no_fake_numbers(auth_client):
    d = auth_client.get("/api/v1/dashboard").json()
    assert len(d["kpis"]) == 12
    for k in d["kpis"]:
        # solange keine Datenquelle existiert: keine Zahl, explizit als nicht verfügbar markiert
        assert k["available"] is False and k["value"] is None
