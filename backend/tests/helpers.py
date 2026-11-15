"""Testwelt: Eigentümer, Objekt mit 2 Wohneinheiten (WE1: 2 Zimmer, Zimmer 1 mit 2 Betten), Hauptmietvertrag."""
from datetime import date
from decimal import Decimal as D

from sqlalchemy import select

from leventum.models import AppUser, LeaseType, Role
from leventum.services import leases as L, master as M


class World:
    def __init__(self, app):
        self.db = app.state.session_factory()
        db = self.db
        self.own = M.create_party(db, None, {"kind": "company", "company_name": "Leventum Real Estate", "is_own_organization": True}, [])
        self.owner = M.create_party(db, None, {"kind": "person", "first_name": "Olga", "last_name": "Eigentümer"}, ["owner", "landlord"])
        self.prop = M.create_property(db, None, {"name": "Haus Bergmann", "property_type": "mehrfamilienhaus",
                                                 "street": "Bergmannstraße 12", "city": "Berlin", "owner_party_id": self.owner.id})
        self.we1 = M.create_unit(db, None, self.prop.id, {"unit_number": "WE 1", "living_area": D("60.00")})
        self.we2 = M.create_unit(db, None, self.prop.id, {"unit_number": "WE 2", "living_area": D("40.00")})
        self.room1 = M.create_room(db, None, self.we1.id, {"name": "Zimmer 1", "area": D("20.00")})
        self.room2 = M.create_room(db, None, self.we1.id, {"name": "Zimmer 2", "area": D("15.00")})
        self.bed1 = M.create_bed(db, None, self.room1.id, {"label": "Bett A"})
        self.bed2 = M.create_bed(db, None, self.room1.id, {"label": "Bett B"})
        self.user = AppUser(username='tester', display_name='Tester', password_hash='x', role_id=db.scalar(select(Role.id).where(Role.code == 'admin')))
        db.add(self.user)
        db.flush()
        self.t = {c.code: c.id for c in db.scalars(select(LeaseType))}

    def ru_prop(self): return M.ensure_rentable_unit(self.db, None, property_id=self.prop.id)
    def ru_unit(self, u): return M.ensure_rentable_unit(self.db, None, property_id=self.prop.id, unit_id=u.id)
    def ru_room(self, r): return M.ensure_rentable_unit(self.db, None, property_id=self.prop.id, room_id=r.id)
    def ru_bed(self, b): return M.ensure_rentable_unit(self.db, None, property_id=self.prop.id, bed_id=b.id)

    def tenant(self, name):
        first, _, last = name.partition(" ")
        return M.create_party(self.db, None, {"kind": "person", "first_name": first, "last_name": last}, ["tenant"])

    def main(self, rus=None, start=date(2025, 1, 1), end=None, permitted=True, rent=D("850.00"), nk=D("180.00"), nk_mode="prepayment"):
        rus = rus or [self.ru_prop()]
        lease = L.create_lease(self.db, None, kind="main", lease_type_id=self.t["hauptmiete"], start_date=start, end_date=end,
                               parties=[{"party_id": self.owner.id, "role": "lessor"}, {"party_id": self.own.id, "role": "lessee"}],
                               rentable_unit_ids=[r.id for r in rus], subletting_permitted=permitted)
        L.add_term(self.db, None, lease.id, valid_from=start, valid_to=None, base_rent=rent)
        L.add_utility_agreement(self.db, None, lease.id, valid_from=start, valid_to=None, mode=nk_mode,
                                monthly_amount=nk if nk_mode in ("prepayment", "flat_rate") else None)
        return lease

    def activate_main(self, **kw):
        lease = self.main(**kw)
        L.activate_lease(self.db, None, lease.id)
        return lease

    def sub(self, rus, tenants, start, end, type_code="wohnraum_unbefristet", rent=D("1150.00"), nk=D("220.00"),
            nk_mode="prepayment", activate=True, **fields):
        lease = L.create_lease(self.db, None, kind="sub", lease_type_id=self.t[type_code], start_date=start, end_date=end,
                               parties=[{"party_id": self.own.id, "role": "lessor"}] + [{"party_id": t.id, "role": "lessee"} for t in tenants],
                               rentable_unit_ids=[r.id for r in rus], **fields)
        L.add_term(self.db, None, lease.id, valid_from=start, valid_to=None, base_rent=rent)
        if nk_mode:
            L.add_utility_agreement(self.db, None, lease.id, valid_from=start, valid_to=None, mode=nk_mode,
                                    monthly_amount=nk if nk_mode in ("prepayment", "flat_rate") else None,
                                    description="individuell vereinbart" if nk_mode == "individual" else None)
        if activate:
            L.activate_lease(self.db, None, lease.id)
        return lease
