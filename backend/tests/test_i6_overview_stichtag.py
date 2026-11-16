"""Review-Befund F-1 (Domain-Zweitreview Phase I): Die Mieterakte (/tenants/{id}/overview, Block finance) muss Zahlungen wie Dashboard, Forderungsliste und
Mahnwesen erst ab ihrem Buchungsdatum berücksichtigen (Entscheidung 2.3). Handrechnung relativ zu heute:
  Forderung A 1000 (fällig -40), Zahlungen 300 (Buchung -30) und 100 (Buchung +5, Zukunft); Forderung B 500 (fällig +10).
  Heute offen: A 1000-300 = 700 (die Zukunftszahlung mindert noch nicht), B 500 -> open_total 1200, überfällig nur A: 700."""
from decimal import Decimal as D

from tests.test_i2_storno import Fin, d, world  # noqa: F401  (Fixture 'world' und Helfer wiederverwendet)

V = "/api/v1"


def test_overview_finance_ignores_future_dated_payments_like_dashboard(world, auth_client):
    f = Fin(world)
    a = f.charge("1000.00", d(-40))
    b = f.charge("500.00", d(10))
    f.pay("300.00", d(-30), (a, "300.00"))
    f.pay("100.00", d(5), (a, "100.00"))
    f.commit()
    ov = auth_client.get(V + f"/tenants/{f.tenant.id}/overview").json()["finance"]
    assert D(ov["open_total"]) == D("1200.00") and D(ov["overdue_total"]) == D("700.00")
    items = {i["charge_id"]: i for i in ov["open_items"]}
    assert D(items[a.id]["open_amount"]) == D("700.00") and items[a.id]["overdue"] is True
    assert D(items[b.id]["open_amount"]) == D("500.00") and items[b.id]["overdue"] is False
    kpi = {k["key"]: k["value"] for k in auth_client.get(V + "/dashboard").json()["kpis"]}
    assert D(kpi["open_receivables"]) == D(ov["open_total"]) and D(kpi["overdue_receivables"]) == D(ov["overdue_total"])  # alle Ansichten gleich
    lease = auth_client.get(V + f"/tenants/{f.tenant.id}/overview").json()["leases"][0]
    assert lease["payment_status"] == "arrears" and D(lease["overdue_amount"]) == D("700.00")
