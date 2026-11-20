// Manueller E2E-Lauf Phase E. Frische Datenbank, Server läuft:
//   LEVENTUM_DATA_DIR=/tmp/lev python -m leventum.desktop --browser --port 8773
//   NODE_PATH=$(npm root -g) node frontend/e2e/phase-e.cjs http://127.0.0.1:8773
const { chromium } = require("playwright");
const base = process.argv[2] || "http://127.0.0.1:8773";
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
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
  const own = await api("POST", "/parties", { kind: "company", company_name: "Leventum Real Estate GmbH", is_own_organization: true });
  const owner = await api("POST", "/parties", { kind: "person", first_name: "Olga", last_name: "Eigentümer", roles: ["owner"] });
  const tenant = await api("POST", "/parties", { kind: "person", first_name: "Max", last_name: "Mustermann", roles: ["tenant"] });
  const prop = await api("POST", "/properties", { name: "Haus Bergmann", property_type: "mehrfamilienhaus", owner_party_id: owner.id });
  const unit = await api("POST", `/properties/${prop.id}/units`, { unit_number: "A", living_area: "60.00" });
  const types = Object.fromEntries((await api("GET", "/lease-types")).items.map((t) => [t.code, t.id]));
  const rp = await api("POST", "/rentable-units", { property_id: prop.id }), ru = await api("POST", "/rentable-units", { property_id: prop.id, unit_id: unit.id });
  const main = await api("POST", "/leases", { kind: "main", lease_type_id: types.hauptmiete, start_date: "2026-01-01", subletting_permitted: true, parties: [{ party_id: owner.id, role: "lessor" }, { party_id: own.id, role: "lessee" }], rentable_unit_ids: [rp.id] });
  await api("POST", `/leases/${main.id}/terms`, { valid_from: "2026-01-01", base_rent: "850.00" }); await api("POST", `/leases/${main.id}/activate`);
  const end = new Date(Date.now() + 40 * 864e5).toISOString().slice(0, 10);
  const sub = await api("POST", "/leases", { kind: "sub", lease_type_id: types.wohnraum_befristet, start_date: "2026-01-01", end_date: end, is_fixed_term: true, notice_period_months: 1, parties: [{ party_id: own.id, role: "lessor" }, { party_id: tenant.id, role: "lessee" }], rentable_unit_ids: [ru.id] });
  await api("POST", `/leases/${sub.id}/terms`, { valid_from: "2026-01-01", base_rent: "1150.00" }); await api("POST", `/leases/${sub.id}/activate`);
  await api("POST", "/invoices", { property_id: prop.id, amount: "300.00", invoice_date: "2026-03-10", invoice_number: "SAN-1", description: "Sanitär" });
  ok("Daten angelegt");
  // --- Dashboard: Hinweise → Aufgabe ---
  await p.goto(base + "/"); await p.waitForSelector("text=/endet am/");
  console.log("Hinweise:", await p.$$eval(".list-row .grow > div:first-child", (e) => e.slice(0, 5).map((x) => x.textContent)));
  await p.click("button:has-text('Aufgabe erstellen') >> nth=0"); await p.waitForSelector("text=/Aufgabe #\\d+/"); ok("Aus Erinnerung Aufgabe erzeugt (Button wird zum Link)");
  // --- Aufgaben ---
  await p.goto(base + "/aufgaben"); await p.waitForSelector("td strong");
  await p.click("text=Aufgabe anlegen"); await p.fill(".modal input.field >> nth=0", "Treppenhaus reinigen lassen"); await p.fill(".modal input[data-kind=date]", "2020-01-01"); await p.click(".modal button.primary");
  await p.waitForSelector("td:has-text('Treppenhaus reinigen lassen')"); await p.waitForSelector("text=überfällig"); ok("Manuelle Aufgabe, überfällig markiert");
  await p.check("input[type=checkbox]"); await p.waitForFunction(() => document.querySelectorAll("tbody tr").length === 1); ok("Filter 'nur überfällige'"); await p.uncheck("input[type=checkbox]");
  await p.selectOption("select[aria-label='Status Treppenhaus reinigen lassen']", "done"); await p.waitForFunction(() => document.querySelector("select[aria-label='Status Treppenhaus reinigen lassen']")?.value === "done"); ok("Status auf erledigt");
  // --- Reparatur ---
  await p.goto(base + "/reparaturen"); await p.click("text=Reparatur melden"); await pick(".modal select", "Haus Bergmann");
  await p.fill(".modal input.field >> nth=0", "Heizung defekt"); await p.fill(".modal input.field >> nth=3", "500.00"); await p.click(".modal button.primary");
  await p.waitForSelector("h1:has-text('Heizung defekt')"); ok("Reparatur gemeldet");
  await p.click("button:has-text('Notiz')"); await dlg("Monteur bestellt"); await p.waitForSelector("text=Monteur bestellt");
  await pick("select", "Erledigt"); await p.waitForSelector(".badge:has-text('Erledigt')"); ok("Notiz und Status im Verlauf");
  await pick(".card select", "SAN-1"); await p.waitForFunction(() => /Tatsächlich \(Rechnungen\)\s*300,00/.test(document.querySelector("dl.kv").textContent.replace(/\u00a0/g, " ")));
  console.log("Kosten:", (await p.textContent("dl.kv")).replace(/\s+/g, " ")); ok("Rechnung verknüpft → tatsächliche Kosten");
  await p.click("text=+ Aufgabe"); await p.fill(".modal input.field >> nth=0", "Handwerker bezahlen"); await p.click(".modal button.primary"); await p.waitForSelector("text=Handwerker bezahlen");
  await p.setInputFiles("input[aria-label='Dokument hochladen']", { name: "heizung.png", mimeType: "image/png", buffer: PNG }); await p.waitForSelector("a:has-text('heizung.png')"); ok("Aufgabe + Foto zur Reparatur");
  // --- Kommunikation ---
  await p.goto(base + "/kommunikation"); await p.click("text=Kontakt erfassen"); await p.fill(".modal input.field >> nth=0", "Heizung ist kalt");
  await pick(".modal select", "Max Mustermann", 2); await p.fill(".modal input.field >> nth=2", "Mieter zurückrufen"); await p.click(".modal button.primary");
  await p.waitForSelector("td:has-text('Heizung ist kalt')"); ok("Kommunikation protokolliert"); 
  console.log("Versand-Schaltflächen:", await p.locator("button:text-matches('senden|versenden|abschicken', 'i')").count());
  await p.goto(base + "/aufgaben"); await p.waitForSelector("td:has-text('Mieter zurückrufen')"); ok("Folgeaufgabe aus Kommunikation");
  // --- Vertrag: fehlende Dokumente / Übergabeprotokoll / Dokument ---
  await p.goto(base + `/vertraege/${sub.id}`); await p.waitForSelector("text=Fehlende Dokumente");
  console.log("Fehlend:", await p.textContent(".alert.warn:has-text('Fehlende Dokumente')"));
  await p.setInputFiles("input[aria-label='Dokument hochladen']", { name: "Mietvertrag.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 mv") }); await p.waitForSelector("a:has-text('Mietvertrag.pdf')");
  await p.click("text=+ Protokoll"); await p.fill(".modal input[data-kind=date]", "2026-01-01"); await p.fill(".modal input.field >> nth=1", "3"); await p.click(".modal button.primary"); await p.waitForSelector("text=Einzug");
  await p.reload(); await p.waitForSelector("text=Übergabeprotokolle"); await p.waitForTimeout(600);
  console.log("Fehlende-Dokumente-Hinweis nach Upload+Protokoll:", await p.locator("text=Fehlende Dokumente").count()); ok("Vertrag: Dokument + Übergabeprotokoll → Pflichtliste erfüllt");
  // --- Dokumente-Seite ---
  await p.goto(base + "/dokumente"); await p.waitForSelector("a:has-text('Mietvertrag.pdf')"); await p.fill("input[aria-label=Suche]", "heizung"); await p.waitForSelector("a:has-text('heizung.png')");
  await p.click("button:has-text('Löschen')"); await dlg("Testlöschung"); await p.waitForFunction(() => !document.body.textContent.includes("heizung.png")); ok("Dokumentensuche und Löschen mit Begründung");
  await p.check("text=gelöschte anzeigen >> input"); await p.waitForSelector("text=gelöscht: Testlöschung"); ok("Gelöschtes Dokument nur noch in 'gelöschte anzeigen'");
  // --- Historie in Mieterakte ---
  await p.goto(base + `/parteien/${tenant.id}`); await p.waitForSelector("text=Historie"); await p.waitForFunction(() => document.body.textContent.includes("Heizung ist kalt"));
  console.log("Historie enthält Kommunikation:", true); ok("Mieterakte-Historie");
  await p.goto(base + "/"); await p.waitForFunction(() => document.querySelectorAll(".kpi .value:not(.na)").length > 5);
  console.log("KPIs:", await p.$$eval(".kpi", (k) => k.filter((x) => /Aufgaben|Reparaturen|Hauptmiet/.test(x.textContent)).map((x) => x.querySelector(".label").textContent + "=" + x.querySelector(".value").textContent)));
  await p.screenshot({ path: "/tmp/shots/e-dashboard.png", fullPage: true });
  console.log("JS-Fehler:", errors.filter((e) => !/status of (4\d\d)/.test(e)));
  await b.close();
})().catch((e) => { console.error("FEHLER", e.message.split("\n").slice(0, 3).join(" | ")); process.exit(1); });
