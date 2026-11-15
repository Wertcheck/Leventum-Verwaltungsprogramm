// Manueller E2E-Lauf (nicht Teil von `npm test`): Server muss laufen, z. B.
//   LEVENTUM_DATA_DIR=/tmp/lev python -m leventum.desktop --browser --port 8767   (frische Datenbank!)
//   NODE_PATH=$(npm root -g) node frontend/e2e/phase-c.cjs http://127.0.0.1:8767
const { chromium } = require("playwright");
const base = process.argv[2] || "http://127.0.0.1:8767";
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1536, height: 1024 } });
  const errors = []; p.on("pageerror", (e) => errors.push(e.message));
  p.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  const answers = []; p.on("dialog", (d) => d.accept(answers.shift() ?? ""));
  const ok = (m) => console.log("OK  ", m);
  await p.goto(base);
  await p.fill("input[autocomplete=username]", "admin"); await p.fill("input[type=password]", "ein-langes-passwort-123"); await p.click("button.primary");
  await p.waitForSelector("text=Guten Tag"); ok("Einrichtung + Dashboard");
  await p.click("text=Einstellungen"); await p.click("text=Anlegen"); await p.waitForSelector("text=Angelegt: Leventum Real Estate"); ok("Eigene Organisation");
  await p.click("text=Stammdaten"); await p.click("a:has-text('Eigentümer & Vermieter')"); await p.click("text=Eigentümer anlegen");
  await p.selectOption(".modal select", "company"); await p.fill(".modal input.field >> nth=0", "Eigentümer Immobilien GmbH"); await p.click(".modal button.primary");
  await p.waitForSelector("td:has-text('Eigentümer Immobilien GmbH')"); ok("Eigentümer angelegt");
  await p.click("a:has-text('Objekte')"); await p.click("text=Objekt anlegen");
  await p.fill(".modal input.field >> nth=0", "Haus Bergmann"); await p.fill(".modal input.field >> nth=1", "Bergmannstraße 12");
  await p.selectOption(".modal select >> nth=1", { label: "Eigentümer Immobilien GmbH" }); await p.click(".modal button.primary");
  await p.click("td:has-text('Haus Bergmann')"); await p.waitForSelector("h1:has-text('Haus Bergmann')"); ok("Objekt angelegt");
  answers.push("WE 1"); await p.click("text=+ Wohneinheit"); await p.waitForSelector("text=WE WE 1");
  answers.push("Zimmer 1"); await p.click("text=+ Zimmer"); await p.waitForSelector("text=Zimmer Zimmer 1");
  answers.push("Bett A"); await p.click("text=+ Bett"); await p.waitForSelector("li:has-text('Bett Bett A')"); ok("Wohneinheit → Zimmer → Bett");
  for (let i = 0; i < 4; i++) { const btn = p.locator("button:has-text('anlegen')").first(); await btn.click(); await p.waitForTimeout(400); }
  await p.waitForFunction(() => document.querySelectorAll(".badge.ok").length >= 4); ok("4 Vermietungseinheiten (Objekt, WE, Zimmer, Bett)");
  await p.screenshot({ path: "/tmp/shots/c-objekt.png" });
  // Hauptmietvertrag
  await p.click("a:has-text('Verträge')"); await p.click("text=Vertrag anlegen");
  await p.selectOption(".modal select >> nth=0", "main");
  await p.selectOption(".modal select >> nth=1", { label: "Hauptmietvertrag (Leventum als Mieter)" });
  await p.selectOption(".modal select >> nth=2", { label: "Eigentümer Immobilien GmbH" });
  await p.selectOption(".modal select[multiple]", { label: "Haus Bergmann" });
  await p.fill(".modal input[type=date] >> nth=0", "2026-01-01");
  await p.selectOption(".modal select >> nth=5", "1");
  await p.fill("input[placeholder='850.00']", "850.00"); await p.fill("input[placeholder='180.00']", "180.00");
  await p.click(".modal button.primary"); await p.waitForSelector("h1:has-text('Hauptmietvertrag')");
  await p.click("text=Prüfen & aktivieren"); await p.waitForSelector(".badge:has-text('Aktiv')"); ok("Hauptmietvertrag aktiviert");
  // Mieter + Untermietvertrag (Bett)
  await p.click("text=Stammdaten").catch(() => {}); await p.click("a:has-text('Mieter')").catch(() => {});
  await p.goto(base + "/mieter"); await p.click("text=Mieter anlegen"); await p.fill(".modal input.field >> nth=0", "Max"); await p.fill(".modal input.field >> nth=1", "Mustermann"); await p.click(".modal button.primary");
  await p.waitForSelector("td:has-text('Max Mustermann')"); ok("Mieter angelegt");
  await p.goto(base + "/vertraege"); await p.click("text=Vertrag anlegen");
  await p.selectOption(".modal select >> nth=0", "sub"); await p.selectOption(".modal select >> nth=1", { label: "Bettenvermietung" });
  await p.selectOption(".modal select >> nth=2", { label: "Max Mustermann" }); await p.selectOption(".modal select[multiple]", { label: "Haus Bergmann · WE WE 1 · Zimmer Zimmer 1 · Bett Bett A" });
  await p.fill(".modal input[type=date] >> nth=0", "2026-02-01"); await p.fill(".modal input[type=date] >> nth=1", "2026-07-31");
  await p.selectOption(".modal select >> nth=4", "1");
  await p.fill("input[placeholder='850.00']", "300.00"); await p.selectOption(".modal select >> nth=5", "flat_rate"); await p.fill("input[placeholder='180.00']", "40.00");
  await p.click(".modal button.primary"); await p.waitForSelector("h1:has-text('Untermietvertrag')");
  await p.click("text=Prüfen & aktivieren"); await p.waitForSelector(".badge:has-text('Aktiv')"); ok("Untermietvertrag (Bett) aktiviert");
  console.log("Gesamt:", await p.textContent("dl.kv >> nth=1"));
  console.log("Hinweise:", await p.$$eval(".alert.ok li", (l) => l.map((x) => x.textContent)));
  await p.screenshot({ path: "/tmp/shots/c-vertrag.png", fullPage: true });
  // Konflikt: zweiter Vertrag auf dasselbe Bett
  await p.goto(base + "/vertraege"); await p.click("text=Vertrag anlegen");
  await p.selectOption(".modal select >> nth=0", "sub"); await p.selectOption(".modal select >> nth=1", { label: "Zimmervermietung" });
  await p.selectOption(".modal select >> nth=2", { label: "Max Mustermann" }); await p.selectOption(".modal select[multiple]", { label: "Haus Bergmann · WE WE 1 · Zimmer Zimmer 1" });
  await p.fill(".modal input[type=date] >> nth=0", "2026-03-01"); await p.click(".modal button.primary"); await p.waitForSelector("h1:has-text('Untermietvertrag')");
  await p.click("text=Prüfen & aktivieren"); await p.waitForSelector("text=Aktivierung nicht möglich");
  console.log("Konflikt:", await p.$$eval(".alert.err li", (l) => l.map((x) => x.textContent))); ok("Überschneidung Zimmer vs. belegtes Bett blockiert");
  await p.fill(".search input", "mustermann"); await p.waitForSelector(".search-results a"); ok("Globale Suche liefert Treffer");
  await p.goto(base + "/wohneinheiten"); await p.waitForSelector("td .badge"); console.log("WE-Status:", await p.$$eval("td .badge", (l) => l.map((x) => x.textContent)));
  console.log("JS-Fehler:", errors.filter((e) => !/status of (4\d\d)/.test(e)));
  await b.close();
})().catch((e) => { console.error("FEHLER", e.message.split("\n")[0]); process.exit(1); });
