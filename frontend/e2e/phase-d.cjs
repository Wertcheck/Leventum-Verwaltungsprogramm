// Manueller E2E-Lauf Phase D. Frische Datenbank, Server läuft:
//   LEVENTUM_DATA_DIR=/tmp/lev python -m leventum.desktop --browser --port 8769
//   NODE_PATH=$(npm root -g) node frontend/e2e/phase-d.cjs http://127.0.0.1:8769
const { chromium } = require("playwright");
const base = process.argv[2] || "http://127.0.0.1:8769";
const IBAN = "DE89370400440532013000";
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1536, height: 1024 } });
  const errors = []; p.on("pageerror", (e) => errors.push(e.message)); p.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  const dlg = async (t) => { await p.fill("form.dialog input, form.dialog textarea", t); await p.click("form.dialog button[type=submit]"); };
  const ok = (m) => console.log("OK  ", m);
  const api = (method, path, body) => p.evaluate(async ([method, path, body]) => {
    const r = await fetch("/api/v1" + path, { method, headers: { "X-Leventum-Client": "1", "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const j = await r.json(); if (!r.ok) throw new Error(path + " " + JSON.stringify(j)); return j;
  }, [method, path, body]);
  const pick = async (sel, text, n = 0) => { const loc = p.locator(sel).nth(n); await loc.locator("option").first().waitFor({ state: "attached" }); const v = await loc.locator("option").evaluateAll((os, t) => os.find((o) => o.textContent.includes(t))?.value, text); await loc.selectOption(v); };
  await p.goto(base);
  await p.fill("input[autocomplete=username]", "admin"); await p.fill("input[type=password]", "ein-langes-passwort-123"); await p.click("button.primary");
  await p.waitForSelector("text=Guten Tag"); ok("Einrichtung");
  // --- Stammdaten per API vorbereiten (echter Server) ---
  const own = await api("POST", "/parties", { kind: "company", company_name: "Leventum Real Estate GmbH", is_own_organization: true });
  const owner = await api("POST", "/parties", { kind: "person", first_name: "Olga", last_name: "Eigentümer", roles: ["owner"] });
  const tenant = await api("POST", "/parties", { kind: "person", first_name: "Max", last_name: "Mustermann", roles: ["tenant"], iban: IBAN });
  const prop = await api("POST", "/properties", { name: "Haus Bergmann", property_type: "mehrfamilienhaus", owner_party_id: owner.id });
  const unitA = await api("POST", `/properties/${prop.id}/units`, { unit_number: "A", living_area: "60.00" });
  await api("POST", `/properties/${prop.id}/units`, { unit_number: "B", living_area: "40.00" });
  const types = Object.fromEntries((await api("GET", "/lease-types")).items.map((t) => [t.code, t.id]));
  const rp = await api("POST", "/rentable-units", { property_id: prop.id }), ru = await api("POST", "/rentable-units", { property_id: prop.id, unit_id: unitA.id });
  const main = await api("POST", "/leases", { kind: "main", lease_type_id: types.hauptmiete, start_date: "2026-01-01", subletting_permitted: true, parties: [{ party_id: owner.id, role: "lessor" }, { party_id: own.id, role: "lessee" }], rentable_unit_ids: [rp.id] });
  await api("POST", `/leases/${main.id}/terms`, { valid_from: "2026-01-01", base_rent: "850.00" });
  await api("POST", `/leases/${main.id}/utility-agreements`, { valid_from: "2026-01-01", mode: "prepayment", monthly_amount: "180.00" });
  await api("POST", `/leases/${main.id}/activate`);
  const sub = await api("POST", "/leases", { kind: "sub", lease_type_id: types.wohnraum_unbefristet, start_date: "2026-01-01", parties: [{ party_id: own.id, role: "lessor" }, { party_id: tenant.id, role: "lessee" }], rentable_unit_ids: [ru.id] });
  await api("POST", `/leases/${sub.id}/terms`, { valid_from: "2026-01-01", base_rent: "1150.00" });
  await api("POST", `/leases/${sub.id}/utility-agreements`, { valid_from: "2026-01-01", mode: "prepayment", monthly_amount: "220.00" });
  await api("POST", `/leases/${sub.id}/activate`);
  ok("Verträge 850/180 → 1150/220 angelegt");
  // --- Sollstellungen ---
  await p.goto(base + "/finanzen"); await p.click("text=Sollstellungen erzeugen");
  await p.fill(".modal input[type=month] >> nth=0", "2026-01"); await p.fill(".modal input[type=month] >> nth=1", "2026-03"); await p.click(".modal button:has-text('Vorschau berechnen')"); await p.waitForSelector("[data-testid=charge-preview]"); await p.check(".modal input[type=checkbox]"); await p.click(".modal button.primary");
  await p.waitForSelector("text=/\\d+ erzeugt/"); console.log("Erzeugung:", await p.textContent(".alert.ok, .alert.err"));
  await p.waitForSelector("td:has-text('Kaltmiete')"); ok("Sollstellungen sichtbar");
  await p.click("text=Sollstellungen erzeugen"); await p.fill(".modal input[type=month] >> nth=0", "2026-01"); await p.fill(".modal input[type=month] >> nth=1", "2026-03"); await p.click(".modal button:has-text('Vorschau berechnen')");
  await p.waitForSelector("text=/0 würden erzeugt, 12 sind bereits vorhanden/"); await p.click(".modal button:has-text('Schließen')"); ok("Zweite Erzeugung: keine doppelten Sollstellungen (0 neu, 12 vorhanden)");
  await p.screenshot({ path: "/tmp/shots/d-finanzen.png", fullPage: true });
  // --- Mahnwesen ---
  await p.goto(base + "/mahnwesen"); await p.waitForSelector("td:has-text('Mahnung fällig')");
  await p.click("text=/als Entwurf vorbereiten/"); await p.waitForSelector("text=Entwurf/Entwürfe angelegt");
  await p.click("button:has-text('Öffnen')"); await p.waitForSelector("textarea");
  console.log("Hinweis:", (await p.textContent(".modal .alert.warn")).slice(0, 80));
  await p.click("text=Geprüft – freigeben"); await p.waitForSelector(".modal .alert.err"); console.log("Freigabe ohne Frist:", await p.textContent(".modal .alert.err")); ok("Freigabe mit offenem Platzhalter blockiert");
  const txt = (await p.inputValue("textarea")).replace("[Frist eintragen]", "30.11.2026"); await p.fill("textarea", txt);
  await p.click("text=Geprüft – freigeben"); await p.waitForSelector("text=Als versandt dokumentieren"); ok("Entwurf manuell freigegeben");
  await p.click("text=Als versandt dokumentieren"); await dlg("Brief"); await p.waitForSelector("text=/Versandt \\(manuell/"); ok("Versand manuell dokumentiert (kein Sendeknopf vorhanden)");
  console.log("Sende-Schaltflächen:", await p.locator("button:text-matches('^(Senden|Versenden)', 'i')").count());
  await p.screenshot({ path: "/tmp/shots/d-mahnung.png" });
  // --- Bankimport ---
  await p.goto(base + "/bankimport"); await p.fill("input[aria-label=Kontoname]", "Geschäftskonto"); await p.click("text=Konto anlegen");
  await p.waitForFunction(() => [...document.querySelectorAll("select option")].some((o) => o.textContent.includes("Geschäftskonto"))); await pick("select", "Geschäftskonto");
  const csv = `Buchungstag;Name Zahlungsbeteiligter;IBAN Zahlungsbeteiligter;Verwendungszweck;Betrag;Währung\n02.01.2026;Max Mustermann;${IBAN};Miete Januar;1.370,00;EUR\n05.01.2026;Unbekannt;;Spende;-5,00;EUR\n`;
  await p.setInputFiles("input[aria-label='CSV-Datei']", { name: "auszug.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await p.click("text=Prüfen (Vorschau)"); await p.waitForSelector("text=2 Zeilen: 2 neu, 0 bereits importiert"); ok("CSV-Vorschau");
  await p.click("button:has-text('Importieren')"); await p.waitForSelector("text=Es wurde noch nichts gebucht");
  await p.waitForSelector("text=/Vorschlag \\(/"); await p.waitForSelector("text=Nicht zuordenbar"); ok("Import: Vorschlag + Prüfliste (nicht zuordenbar)");
  await p.setInputFiles("input[aria-label='CSV-Datei']", { name: "auszug.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await p.click("text=Prüfen (Vorschau)"); await p.waitForSelector("text=/0 neu, 2 bereits importiert/"); ok("Erneuter Import erkennt Duplikate");
  await p.screenshot({ path: "/tmp/shots/d-bank.png", fullPage: true });
  await p.click("text=Zuordnung bestätigen"); await p.waitForTimeout(1200);
  console.log("Bank nach Bestätigung:", (await p.$$eval("tbody tr", (r) => r.map((x) => x.textContent.slice(0, 90)))).join(" || "));
  console.log("Zahlungen (API):", JSON.stringify((await api("GET", "/payments")).items.map((x) => [x.amount, x.allocated, x.source])));
  await p.goto(base + "/finanzen"); await p.waitForSelector("td:has-text('Miete Januar')"); ok("Bestätigte Bankbuchung erscheint als Zahlung");
  console.log("Status Januar-Miete:", await p.$$eval("tr:has(td:has-text('2026-01'))", (r) => r.slice(0, 4).map((x) => x.textContent.slice(-30))));
  // --- Kaution ---
  await p.goto(base + "/kautionen"); await p.click("text=Kaution vereinbaren"); await pick(".modal select", "#2 Untermiete");
  await p.fill(".modal input.field >> nth=0", "2000.00"); await p.click(".modal button.primary"); await p.waitForSelector("td:has-text('2.000,00')");
  await p.click("button:has-text('Buchung')"); await p.fill(".modal input.field >> nth=0", "2000.00"); await p.fill(".modal input[type=date]", "2026-01-03"); await p.click(".modal button.primary");
  await p.waitForSelector("text=Gezahlt"); ok("Kaution vereinbart und gebucht (außerhalb der Zahlungen)");
  // --- Rechnung mit Beleg ---
  await p.goto(base + "/rechnungen"); await p.click("text=Rechnung erfassen"); await pick(".modal select", "Haus Bergmann");
  await p.fill(".modal input.field >> nth=0", "RE-1"); await p.fill(".modal input[type=date]", "2026-01-20"); await p.fill(".modal input.field >> nth=2", "238.00");
  await p.setInputFiles("input[aria-label=Belegdatei]", { name: "beleg.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 test") });
  await p.click(".modal button.primary"); await p.waitForSelector("td:has-text('RE-1')"); ok("Rechnung mit Beleg erfasst");
  // --- Auswertungen ---
  await p.goto(base + "/auswertungen/wirtschaftlichkeit"); await p.fill("input[type=month] >> nth=0", "2026-01"); await p.fill("input[type=month] >> nth=1", "2026-01");
  await p.waitForSelector("text=Soll (laut Verträgen)"); await p.waitForFunction(() => document.body.textContent.includes("1.370,00"));
  const txt2 = await p.textContent("main"); console.log("Wirtschaftlichkeit enthält:", ["1.370,00", "1.030,00", "102,00", "kein Gewinn", "Ist (Zahlungen)", "238,00"].map((s) => `${s}:${txt2.includes(s)}`).join(" "));
  await p.screenshot({ path: "/tmp/shots/d-wirtschaft.png", fullPage: true });
  await p.goto(base + "/auswertungen/leerstand"); await p.fill("input[type=month] >> nth=0", "2026-01"); await p.fill("input[type=month] >> nth=1", "2026-01");
  await p.waitForSelector("[data-testid=phys]"); await p.waitForTimeout(500);
  console.log("Leerstand physisch:", await p.textContent("[data-testid=phys]"), "wirtschaftlich:", await p.textContent("[data-testid=econ]"));
  await p.screenshot({ path: "/tmp/shots/d-leerstand.png", fullPage: true });
  await p.goto(base + "/"); await p.waitForSelector("text=Guten Tag"); await p.waitForFunction(() => document.querySelectorAll(".kpi .value:not(.na)").length > 5);
  console.log("KPIs:", await p.$$eval(".kpi", (k) => k.map((x) => x.querySelector(".label").textContent + "=" + x.querySelector(".value").textContent)));
  await p.screenshot({ path: "/tmp/shots/d-dashboard.png", fullPage: true });
  console.log("JS-Fehler:", errors.filter((e) => !/status of (4\d\d)/.test(e)));
  await b.close();
})().catch((e) => { console.error("FEHLER", e.message.split("\n").slice(0, 3).join(" | ")); process.exit(1); });
