// Befüllt eine frische Instanz mit realistischen Demodaten (nur für Screenshots/Abnahme!) und erzeugt Screenshots aller Bereiche.
//   LEVENTUM_DATA_DIR=/tmp/lev python -m leventum.desktop --browser --port 8780
//   NODE_PATH=$(npm root -g) node frontend/e2e/seed-and-shoot.cjs http://127.0.0.1:8780 docs/screenshots
const { chromium } = require("playwright");
const base = process.argv[2] || "http://127.0.0.1:8780", out = process.argv[3] || "docs/screenshots";
const PW = "ein-langes-passwort-123";
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1536, height: 1024 } });
  const errors = []; p.on("pageerror", (e) => errors.push(e.message)); p.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  p.on("dialog", (d) => d.dismiss());
  await p.goto(base); await p.waitForSelector("input[autocomplete=username]");
  await p.screenshot({ path: `${out}/00-einrichtung.png` });
  await p.fill("input[autocomplete=username]", "admin"); await p.fill("input:not([autocomplete])", "Admin"); await p.fill("input[type=password]", PW); await p.click("button.primary");
  await p.waitForSelector("text=Guten Tag");
  const seed = await p.evaluate(async () => {
    const A = async (m, path, body) => { const r = await fetch("/api/v1" + path, { method: m, headers: { "X-Leventum-Client": "1", "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined }); const j = await r.json(); if (!r.ok) throw new Error(m + " " + path + " " + JSON.stringify(j)); return j; };
    const party = (kind, o, roles = [], extra = {}) => A("POST", "/parties", { kind, ...o, roles, ...extra });
    const own = await party("company", { company_name: "Leventum Real Estate GmbH" }, [], { is_own_organization: true });
    const o1 = await party("person", { first_name: "Helga", last_name: "Brandt" }, ["owner"], { iban: "DE02120300000000202051", city: "Berlin" });
    const o2 = await party("company", { company_name: "Lindenallee Immobilien GmbH" }, ["owner"], { city: "Potsdam" });
    const names = [["Max", "Mustermann", "DE89370400440532013000"], ["Sandra", "Klein"], ["Bernd", "Hoffmann"], ["Lisa", "Schneider"], ["Thomas", "Keller"], ["Anna", "Weber"], ["Jonas", "Becker"], ["Maria", "Kovač"]];
    const T = {}; for (const [f, l, iban] of names) T[l] = await party("person", { first_name: f, last_name: l }, ["tenant"], { email: `${f.toLowerCase()}.${l.toLowerCase().replace("č", "c")}@example.org`, iban });
    const supplier = await party("company", { company_name: "Sanitär Schmidt GmbH" }, ["service_provider"]);
    const types = Object.fromEntries((await A("GET", "/lease-types")).items.map((t) => [t.code, t.id]));
    const pA = await A("POST", "/properties", { name: "Haus Bergmann", property_type: "mehrfamilienhaus", street: "Bergmannstraße 12", postal_code: "10961", city: "Berlin", owner_party_id: o1.id, year_built: 1965, heating_type: "Gas-Zentralheizung" });
    const pB = await A("POST", "/properties", { name: "Lindenallee 5", property_type: "mehrfamilienhaus", street: "Lindenallee 5", postal_code: "14469", city: "Potsdam", owner_party_id: o2.id, year_built: 1998 });
    const unit = (p, n, area, extra = {}) => A("POST", `/properties/${p.id}/units`, { unit_number: n, living_area: area, ...extra });
    const a1 = await unit(pA, "WE 01", "78.50", { floor: "2", rooms_count: 3 }), a2 = await unit(pA, "WE 02", "55.00", { floor: "1", rooms_count: 2 }), a3 = await unit(pA, "WE 03", "92.00", { floor: "3", rooms_count: 4 });
    const b1 = await unit(pB, "1", "62.00", { floor: "EG" }), b2 = await unit(pB, "2", "48.00", { floor: "1" });
    const rooms = {}; for (const [n, area] of [["Zimmer 1", "18.00"], ["Zimmer 2", "14.00"], ["Zimmer 3", "16.00"]]) rooms[n] = await A("POST", `/units/${a3.id}/rooms`, { name: n, area });
    const beds = {}; for (const lbl of ["Bett A", "Bett B"]) beds[lbl] = await A("POST", `/rooms/${rooms["Zimmer 1"].id}/beds`, { label: lbl });
    const RU = (o) => A("POST", "/rentable-units", o);
    const ruAp = await RU({ property_id: pA.id }), ruBp = await RU({ property_id: pB.id });
    const ru = { a1: await RU({ property_id: pA.id, unit_id: a1.id }), a2: await RU({ property_id: pA.id, unit_id: a2.id }), b1: await RU({ property_id: pB.id, unit_id: b1.id }),
      r1a: await RU({ property_id: pA.id, bed_id: beds["Bett A"].id }), r1b: await RU({ property_id: pA.id, bed_id: beds["Bett B"].id }), r2: await RU({ property_id: pA.id, room_id: rooms["Zimmer 2"].id }) };
    const lease = async (kind, type, start, rus, parties, rent, nkMode, nk, extra = {}) => {
      const l = await A("POST", "/leases", { kind, lease_type_id: types[type], start_date: start, parties, rentable_unit_ids: rus, ...extra });
      await A("POST", `/leases/${l.id}/terms`, { valid_from: start, base_rent: rent });
      await A("POST", `/leases/${l.id}/utility-agreements`, { valid_from: start, mode: nkMode, monthly_amount: nk || null });
      await A("POST", `/leases/${l.id}/activate`); return l;
    };
    const m1 = await lease("main", "hauptmiete", "2025-06-01", [ruAp.id], [{ party_id: o1.id, role: "lessor" }, { party_id: own.id, role: "lessee" }], "3100.00", "prepayment", "780.00", { subletting_permitted: true, notice_period_months: 3 });
    const m2 = await lease("main", "hauptmiete", "2025-06-01", [ruBp.id], [{ party_id: o2.id, role: "lessor" }, { party_id: own.id, role: "lessee" }], "1450.00", "prepayment", "340.00", { subletting_permitted: true });
    const sub = (type, start, rus, tenant, rent, mode, nk, extra = {}) => lease("sub", type, start, rus, [{ party_id: own.id, role: "lessor" }, { party_id: T[tenant].id, role: "lessee" }], rent, mode, nk, extra);
    const s = {};
    s.mm = await sub("wohnraum_unbefristet", "2026-01-01", [ru.a1.id], "Mustermann", "1120.00", "prepayment", "280.00", { contract_number: "M-2026-01" });
    s.kl = await sub("wohnraum_unbefristet", "2026-01-01", [ru.a2.id], "Klein", "890.00", "prepayment", "210.00");
    s.wa = await sub("bett", "2026-02-01", [ru.r1a.id], "Weber", "420.00", "flat_rate", "60.00");
    s.be = await sub("bett", "2026-02-01", [ru.r1b.id], "Becker", "420.00", "flat_rate", "60.00");
    s.ko = await sub("zimmer", "2026-03-01", [ru.r2.id], "Kovač", "560.00", "flat_rate", "70.00");
    s.ho = await sub("wohnraum_unbefristet", "2026-01-01", [ru.b1.id], "Hoffmann", "1060.00", "prepayment", "250.00");
    s.ke = await sub("wohnraum_befristet", "2026-01-01", [], "Keller", "900.00", "prepayment", "200.00").catch(() => null);
    const ruB2 = await RU({ property_id: pB.id, unit_id: b2.id });
    s.ke = await sub("wohnraum_befristet", "2026-01-01", [ruB2.id], "Keller", "900.00", "prepayment", "200.00", { end_date: "2026-12-31", is_fixed_term: true, fixed_term_reason: "Beispiel: Eigenbedarf des Eigentümers ab 2027", notice_period_months: 2 });
    await A("POST", `/leases/${s.ke.id}/terminate`, { terminated_on: "2026-10-20", effective_on: "2026-12-31" });
    await A("POST", "/charges/generate", { from_month: "2026-01-01", through_month: "2026-11-01" });
    const charges = (await A("GET", "/charges")).items.filter((c) => !c.voided_at);
    const byLease = (id) => charges.filter((c) => c.lease_id === id);
    for (const c of charges.sort((a, b) => a.due_date.localeCompare(b.due_date))) {
      const skip = (c.lease_id === s.kl.id && c.due_date >= "2026-10-01") || (c.lease_id === s.ho.id && c.due_date >= "2026-11-01") || (c.lease_id === s.ke.id && c.due_date >= "2026-11-01");
      if (skip) continue;
      const out = c.direction === "payable";
      const amount = c.lease_id === s.ho.id && c.due_date === "2026-10-01" && c.charge_type === "base_rent" ? "800.00" : c.amount;   // eine Teilzahlung
      await A("POST", "/payments", { direction: out ? "out" : "in", booking_date: c.due_date, amount, reference: `${out ? "Miete" : "Zahlung"} ${c.period_start.slice(0, 7)} ${c.charge_type}`, accept_possible_duplicate: true, allocations: [{ charge_id: c.id, amount }] });
    }
    for (const [lid, amt] of [[s.mm.id, "2800.00"], [s.kl.id, "1780.00"], [s.ho.id, "2120.00"]]) { const d = await A("POST", "/deposits", { lease_id: lid, agreed_amount: amt, due_date: "2026-01-01" }); await A("POST", `/deposits/${d.id}/transactions`, { kind: "paid", amount: lid === s.ho.id ? "1000.00" : amt, transaction_date: "2026-01-03" }); }
    const dm = await A("POST", "/deposits", { lease_id: m1.id, agreed_amount: "9300.00", due_date: "2025-06-01" }); await A("POST", `/deposits/${dm.id}/transactions`, { kind: "paid", amount: "9300.00", transaction_date: "2025-06-02" });
    const inv = await A("POST", "/invoices", { property_id: pA.id, unit_id: a1.id, supplier_party_id: supplier.id, invoice_number: "SAN-2026-114", amount: "476.00", invoice_date: "2026-10-12", description: "Heizungswartung WE 01" });
    const rep = await A("POST", "/repairs", { property_id: pA.id, unit_id: a1.id, lease_id: s.mm.id, title: "Heizung in WE 01 bleibt kalt", category: "heizung", priority: "urgent", reported_on: "2026-10-10", cost_estimate: "400.00", scheduled_for: "2026-11-18", contractor_party_id: supplier.id });
    await A("POST", `/repairs/${rep.id}/invoices`, { invoice_id: inv.id }); await A("POST", `/repairs/${rep.id}/status`, { status: "scheduled" }); await A("POST", `/repairs/${rep.id}/notes`, { text: "Termin mit Sanitär Schmidt für den 18.11. vereinbart." });
    await A("POST", "/repairs", { property_id: pB.id, title: "Wasserhahn tropft (Küche)", category: "sanitaer", priority: "normal", reported_on: "2026-11-03" });
    for (const [t, pr, d, extra] of [["Kündigung Keller: Nachmieter suchen", "high", "2026-11-30", { lease_id: s.ke.id }], ["Rauchmelder in Haus Bergmann prüfen lassen", "normal", "2026-12-15", { property_id: pA.id }], ["Mahnung Klein vorbereiten", "high", "2026-11-10", { lease_id: s.kl.id }], ["Versicherungsnachweis anfordern", "low", null, { property_id: pB.id }]]) await A("POST", "/tasks", { title: t, priority: pr, due_date: d, ...extra });
    await A("POST", "/communications", { channel: "email", direction: "in", subject: "Heizung ist seit Tagen kalt", body: "Herr Mustermann meldet, dass die Heizung im Wohnzimmer nicht warm wird.", party_id: T.Mustermann.id, lease_id: s.mm.id, repair_id: rep.id, follow_up: { title: "Mustermann Termin bestätigen", due_date: "2026-11-17" } });
    await A("POST", "/communications", { channel: "phone", direction: "out", subject: "Rückruf wegen Mietrückstand", party_id: T.Klein.id, lease_id: s.kl.id });
    await A("POST", "/communications", { channel: "letter", direction: "in", subject: "Kündigungsschreiben", party_id: T.Keller.id, lease_id: s.ke.id });
    await A("POST", "/handover-protocols", { lease_id: s.mm.id, kind: "move_in", protocol_date: "2026-01-01", keys_handed: 3, condition_notes: "Wände weiß, Parkett ohne Mängel.", signed: true });
    const acc = await A("POST", "/bank/accounts", { name: "Geschäftskonto Leventum", iban: "DE12 5001 0517 5407 3249 31" });
    const csv = ["Buchungstag;Valuta;Name Zahlungsbeteiligter;IBAN Zahlungsbeteiligter;Verwendungszweck;Betrag;Währung",
      "02.11.2026;02.11.2026;Max Mustermann;DE89 3704 0044 0532 0130 00;Miete November M-2026-01;1.400,00;EUR", "03.11.2026;03.11.2026;Sandra Klein;;Miete Oktober;900,00;EUR",
      "05.11.2026;05.11.2026;Stadtwerke Potsdam;;Abschlag Allgemeinstrom;-84,00;EUR", "09.11.2026;09.11.2026;Sanitär Schmidt;;Rechnung SAN-2026-114;-476,00;EUR", "10.11.2026;10.11.2026;Unbekannt;DE44500105175407324931;Spende Sommerfest;25,00;EUR"].join("\n");
    const fd = new FormData(); fd.set("account_id", acc.id); fd.set("file", new File([csv], "Kontoauszug-2026-11.csv", { type: "text/csv" }));
    await fetch("/api/v1/bank/imports", { method: "POST", headers: { "X-Leventum-Client": "1" }, body: fd });
    const up = async (name, mime, bytes, et, eid, dt) => { const f = new FormData(); f.set("file", new File([bytes], name, { type: mime })); f.set("entity_type", et); f.set("entity_id", eid); f.set("doc_type", dt); await fetch("/api/v1/documents", { method: "POST", headers: { "X-Leventum-Client": "1" }, body: f }); };
    await up("Mietvertrag Mustermann.pdf", "application/pdf", "%PDF-1.4 Beispiel", "lease", s.mm.id, "mietvertrag"); await up("Mietvertrag Klein.pdf", "application/pdf", "%PDF-1.4 Beispiel", "lease", s.kl.id, "mietvertrag");
    await up("Hauptmietvertrag Haus Bergmann.pdf", "application/pdf", "%PDF-1.4 Beispiel", "lease", m1.id, "mietvertrag"); await up("Rechnung SAN-2026-114.pdf", "application/pdf", "%PDF-1.4 Beispiel", "invoice", inv.id, "rechnung");
    await up("Kaution Mustermann Beleg.pdf", "application/pdf", "%PDF-1.4 Beispiel", "party", T.Mustermann.id, "kaution");
    await A("POST", "/dunning/prepare", {});
    return { ids: { mm: s.mm.id, kl: s.kl.id, rep: rep.id, tenantMM: T.Mustermann.id, pA: pA.id, ke: s.ke.id, a3: a3.id } };
  });
  console.log("Seed ok", JSON.stringify(seed.ids));
  const shots = [["01-dashboard", "/", "text=Untermiete (Soll)"], ["02-mieter", "/mieter", "td strong"], ["03-eigentuemer", "/eigentuemer", "td strong"], ["04-objekte", "/objekte", "td strong"], ["05-objekt-detail", `/objekte/${seed.ids.pA}`, ".tree"],
    ["06-wohneinheiten", "/wohneinheiten", "td .badge"], ["07-vertraege", "/vertraege", "td .badge"], ["08-vertrag-detail", `/vertraege/${seed.ids.mm}`, "text=Konditionen"], ["09-sollstellungen-zahlungen", "/finanzen", "td:has-text('Kaltmiete')"],
    ["10-kautionen", "/kautionen", "td:has-text('2.800')"], ["11-mahnwesen", "/mahnwesen", "td:has-text('Entwurf vorhanden')"], ["12-bankimport", "/bankimport", "text=Kontoauszug importieren"], ["13-rechnungen", "/rechnungen", "td:has-text('SAN-2026-114')"],
    ["14-wirtschaftlichkeit", "/auswertungen/wirtschaftlichkeit", "text=Soll (laut Verträgen)"], ["15-leerstand", "/auswertungen/leerstand", "[data-testid=phys]"], ["16-aufgaben", "/aufgaben", "td strong"], ["17-reparaturen", "/reparaturen", "td strong"],
    ["18-reparatur-detail", `/reparaturen/${seed.ids.rep}`, "text=Verlauf"], ["19-kommunikation", "/kommunikation", "td strong"], ["20-dokumente", "/dokumente", "text=Dokumente"], ["21-einstellungen", "/einstellungen", "text=Eigene Organisation"], ["22-mieterakte", `/parteien/${seed.ids.tenantMM}`, "text=Historie"]];
  for (const [name, path, sel] of shots) {
    await p.goto(base + path); await p.waitForSelector(sel, { timeout: 8000 }).catch(() => console.log("WARN Selektor fehlt:", name)); await p.waitForTimeout(700);
    await p.screenshot({ path: `${out}/${name}.png`, fullPage: false }); console.log("shot", name);
  }
  console.log("JS-Fehler:", errors.filter((e) => !/status of (4\d\d)/.test(e)));
  await b.close();
})().catch((e) => { console.error("FEHLER", e.message.split("\n").slice(0, 3).join(" | ")); process.exit(1); });
