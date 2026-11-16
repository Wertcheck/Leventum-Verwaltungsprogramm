// Automatisierte Browser-E2E-Suite (Chromium/Playwright, Linux oder Windows-Browser – NICHT pywebview/WebView2).
// Startet einen eigenen Server mit frischer Datenbank, führt die Abläufe nacheinander aus und endet mit Exit-Code 0/1.
//   npm run build && NODE_PATH=$(npm root -g) node e2e/suite.cjs        (Python-Interpreter: LEVENTUM_PYTHON, sonst ../.venv/bin/python bzw. python)
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const PORT = Number(process.env.E2E_PORT || 8791), base = `http://127.0.0.1:${PORT}`, PW = "ein-langes-passwort-123", IBAN = "DE89370400440532013000";
const root = path.resolve(__dirname, "..", "..");
const py = process.env.LEVENTUM_PYTHON || (fs.existsSync(path.join(root, ".venv/bin/python")) ? path.join(root, ".venv/bin/python") : "python");
const data = fs.mkdtempSync(path.join(os.tmpdir(), "lev-e2e-"));
const results = []; const errors = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const srv = spawn(py, ["-m", "leventum.desktop", "--browser", "--port", String(PORT)], { cwd: path.join(root, "backend"), env: { ...process.env, LEVENTUM_DATA_DIR: data, PYTHONPATH: "" }, stdio: "ignore" });
  for (let i = 0; i < 60; i++) { try { if ((await fetch(base + "/api/v1/health")).ok) break; } catch {} await sleep(500); }
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 1536, height: 1024 }, acceptDownloads: true }); const p = await ctx.newPage();
  p.on("pageerror", (e) => errors.push(e.message)); p.on("console", (m) => m.type() === "error" && !/favicon|Failed to load resource/.test(m.text()) && errors.push(m.text()));
  const dlg = async (t) => { await p.fill("form.dialog input, form.dialog textarea", t); await p.click("form.dialog button[type=submit]"); };
  const api = (method, url, body) => p.evaluate(async ([method, url, body]) => {
    const r = await fetch("/api/v1" + url, { method, headers: { "X-Leventum-Client": "1", "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(url + " " + JSON.stringify(j)); return j;
  }, [method, url, body]);
  const ctxState = {};
  async function test(name, fn) {
    try { await fn(); results.push([true, name]); console.log("OK     ", name); }
    catch (e) { results.push([false, name, String(e.message).split("\n")[0]]); console.log("FEHLER ", name, "|", String(e.message).split("\n")[0]); await p.screenshot({ path: path.join(os.tmpdir(), `e2e-fail-${results.length}.png`) }).catch(() => {}); }
  }
  const expect = (c, m) => { if (!c) throw new Error(m); };

  await test("01 Einrichtung und Anmeldung", async () => {
    await p.goto(base); await p.waitForSelector("input[autocomplete=username]");
    await p.fill("input[autocomplete=username]", "admin"); await p.fill("input:not([autocomplete])", "Admin"); await p.fill("input[type=password]", PW); await p.click("button.primary");
    await p.waitForSelector("text=Guten Tag");
  });
  await test("02 Stammdaten, Objektstruktur über Dialoge (WE → Zimmer → Bett)", async () => {
    const S = ctxState;
    S.own = await api("POST", "/parties", { kind: "company", company_name: "Leventum Real Estate GmbH", is_own_organization: true });
    S.owner = await api("POST", "/parties", { kind: "person", first_name: "Olga", last_name: "Eigentümer", roles: ["owner"] });
    S.prop = await api("POST", "/properties", { name: "Haus Bergmann", property_type: "mehrfamilienhaus", owner_party_id: S.owner.id });
    await p.goto(base + `/objekte/${S.prop.id}`); await p.waitForSelector("h1:has-text('Haus Bergmann')");
    await p.click("text=+ Wohneinheit"); await dlg("WE 1"); await p.waitForSelector("text=WE 1 >> nth=0");
    await p.click("text=+ Zimmer"); await dlg("Zimmer 1"); await p.waitForSelector("text=Zimmer 1 >> nth=0");
    await p.click("text=+ Bett"); await dlg("Bett A"); await p.waitForSelector("li:has-text('Bett A')");
  });
  await test("03 Dialog: Abbrechen legt nichts an, leere Eingabe wird abgewiesen", async () => {
    const before = (await api("GET", `/properties/${ctxState.prop.id}`)).units.length;
    await p.click("text=+ Wohneinheit"); await p.click("form.dialog button[type=submit]"); await p.waitForSelector("form.dialog .alert.err");
    await p.click("form.dialog button:has-text('Abbrechen')");
    expect((await api("GET", `/properties/${ctxState.prop.id}`)).units.length === before, "Wohneinheit angelegt");
    expect((await p.locator("form.dialog").count()) === 0, "Dialog noch offen");
  });
  await test("04 Verträge (Haupt-/Untermiete) aktivieren, Überschneidung blockiert", async () => {
    const S = ctxState; const types = Object.fromEntries((await api("GET", "/lease-types")).items.map((t) => [t.code, t.id]));
    S.tenant = await api("POST", "/parties", { kind: "person", first_name: "Max", last_name: "Mustermann", roles: ["tenant"], iban: IBAN });
    const prop = await api("GET", `/properties/${S.prop.id}`); const unit = prop.units[0];
    const rp = await api("POST", "/rentable-units", { property_id: S.prop.id }), ru = await api("POST", "/rentable-units", { property_id: S.prop.id, unit_id: unit.id });
    const main = await api("POST", "/leases", { kind: "main", lease_type_id: types.hauptmiete, start_date: "2026-01-01", subletting_permitted: true, parties: [{ party_id: S.owner.id, role: "lessor" }, { party_id: S.own.id, role: "lessee" }], rentable_unit_ids: [rp.id] });
    await api("POST", `/leases/${main.id}/terms`, { valid_from: "2026-01-01", base_rent: "850.00" });
    await api("POST", `/leases/${main.id}/utility-agreements`, { valid_from: "2026-01-01", mode: "prepayment", monthly_amount: "180.00" });
    await api("POST", `/leases/${main.id}/activate`);
    const sub = await api("POST", "/leases", { kind: "sub", lease_type_id: types.wohnraum_unbefristet, start_date: "2026-01-01", parties: [{ party_id: S.own.id, role: "lessor" }, { party_id: S.tenant.id, role: "lessee" }], rentable_unit_ids: [ru.id] });
    await api("POST", `/leases/${sub.id}/terms`, { valid_from: "2026-01-01", base_rent: "1150.00" });
    await api("POST", `/leases/${sub.id}/utility-agreements`, { valid_from: "2026-01-01", mode: "prepayment", monthly_amount: "220.00" });
    await api("POST", `/leases/${sub.id}/activate`); S.main = main; S.sub = sub; S.main_ru = rp; S.sub_ru = ru;
    let blocked = false;
    try { const dup = await api("POST", "/leases", { kind: "sub", lease_type_id: types.wohnraum_unbefristet, start_date: "2026-03-01", parties: [{ party_id: S.own.id, role: "lessor" }, { party_id: S.tenant.id, role: "lessee" }], rentable_unit_ids: [ru.id] }); await api("POST", `/leases/${dup.id}/terms`, { valid_from: "2026-03-01", base_rent: "100.00" }); await api("POST", `/leases/${dup.id}/activate`); } catch { blocked = true; }
    expect(blocked, "Überlappender Untermietvertrag wurde nicht blockiert");
  });
  await test("05 Sollstellungen: Vorschau, Rückwirkung nur nach Bestätigung, keine Doppelbuchung", async () => {
    await p.goto(base + "/finanzen"); await p.click("text=Sollstellungen erzeugen");
    await p.fill(".modal input[type=month] >> nth=0", "2026-01"); await p.fill(".modal input[type=month] >> nth=1", "2026-03");
    await p.click(".modal button:has-text('Vorschau berechnen')"); await p.waitForSelector("[data-testid=charge-preview]");
    expect(await p.locator(".modal button.primary").isDisabled(), "Erzeugen trotz fehlender Rückwirkungs-Bestätigung aktiv");
    await p.check(".modal input[type=checkbox]"); await p.click(".modal button.primary"); await p.waitForSelector("text=/12 erzeugt/");
    await p.click("text=Sollstellungen erzeugen"); await p.fill(".modal input[type=month] >> nth=0", "2026-01"); await p.fill(".modal input[type=month] >> nth=1", "2026-03");
    await p.click(".modal button:has-text('Vorschau berechnen')"); await p.waitForSelector("text=/0 würden erzeugt, 12 sind bereits vorhanden/"); await p.click(".modal button:has-text('Schließen')");
  });
  await test("06 Zahlung, Stornierung per Gegenbuchung mit Begründung", async () => {
    const S = ctxState; const pay = await api("POST", "/payments", { direction: "in", booking_date: "2026-01-02", amount: "100.00", reference: "Test", counterparty_party_id: S.tenant.id });
    await p.goto(base + "/finanzen"); await p.waitForSelector("text=Test");
    await p.click("tr:has-text('Test') >> button:has-text('Stornieren')"); await dlg("Fehlbuchung"); await p.waitForSelector("text=/Zahlung storniert/");
    expect((await api("GET", "/payments")).items.some((x) => x.is_reversal), "Keine Gegenbuchung");
  });
  await test("07 Mahnwesen: konsistente Zähler, Entwurf, Platzhalter blockiert, Versand dokumentiert, keine Sendefunktion", async () => {
    await p.goto(base + "/mahnwesen"); await p.waitForSelector("[aria-label='Überblick Mahnwesen']");
    await p.waitForSelector("td:has-text('Mahnung fällig')"); await p.click("text=/als Entwurf vorbereiten/"); await p.waitForSelector("text=Entwurf/Entwürfe angelegt");
    await p.click("button:has-text('Öffnen')"); await p.waitForSelector("textarea");
    await p.click("text=Geprüft – freigeben"); await p.waitForSelector(".modal .alert.err");
    const txt = (await p.inputValue("textarea")).replace("[Frist eintragen]", "30.11.2026"); await p.fill("textarea", txt);
    await p.click("text=Geprüft – freigeben"); await p.click("text=Als versandt dokumentieren"); await dlg("Brief"); await p.waitForSelector("text=/Versandt \\(manuell/");
    expect((await p.locator("button:text-matches('^(Senden|Versenden)', 'i')").count()) === 0, "Sendefunktion vorhanden");
  });
  await test("08 Mieterliste: Detailpanel öffnen/schließen, Vertrag im Panel", async () => {
    await p.goto(base + "/mieter"); await p.click("td:has-text('Max Mustermann')"); await p.waitForSelector("[data-testid=tenant-panel] >> text=Offene Posten");
    expect((await p.textContent("[data-testid=tenant-panel]")).includes("Untermietvertrag"), "Vertrag fehlt im Panel");
    await p.click("[aria-label='Detailpanel schließen']"); expect((await p.locator("[data-testid=tenant-panel]").count()) === 0, "Panel offen");
  });
  await test("09 Betriebskosten (Ebene A) über die Oberfläche: erfassen, Position, Vorauszahlung, Prüfung sperrt", async () => {
    const S = ctxState; const ct = (await api("GET", "/cost-types")).items[0];
    await p.goto(base + "/betriebskosten"); await p.click("button:has-text('Abrechnung erfassen')");
    await p.locator(".modal select").nth(0).selectOption({ label: "Haus Bergmann" });
    await p.locator(".modal select").nth(1).selectOption({ index: 1 });
    await p.fill(".modal input[type=date] >> nth=0", "2026-01-01"); await p.fill(".modal input[type=date] >> nth=1", "2026-12-31");
    await p.check(".modal input[type=checkbox] >> nth=0"); await p.click(".modal button.primary:has-text('Anlegen')");
    await p.waitForSelector("text=Positionen");
    await p.locator(".modal select").first().selectOption(String(ct.id)); await p.fill(".modal input[placeholder='480.00']", "480.00");
    await p.click("button:has-text('Position hinzufügen')"); await p.waitForSelector("td:has-text('480,00')");
    await p.click("button:has-text('Manuell eingeben')"); await dlg("2160.00"); await p.waitForSelector("text=Vorauszahlungen gespeichert");
    await p.click("button:has-text('Als erfasst markieren')"); await p.waitForSelector("button:has-text('Als geprüft markieren')");
    await p.click("button:has-text('Als geprüft markieren')"); await p.click("form.dialog button[type=submit]"); await p.waitForSelector("text=/eingefroren/");
    expect((await p.locator("button:has-text('Position hinzufügen')").count()) === 0, "Gesperrte Abrechnung noch bearbeitbar");
  });
  await test("10 Wirtschaftlichkeit: Datenstand-Banner und Soll-Anzeige", async () => {
    await p.goto(base + "/auswertungen/wirtschaftlichkeit"); await p.waitForSelector("[data-testid=datenstand]");
    expect((await p.textContent("body")).includes("Soll"), "Soll fehlt");
  });
  await test("11 Dokument hochladen und mit Begründung löschen", async () => {
    await p.goto(base + `/vertraege/${ctxState.sub.id}`); await p.waitForSelector("input[type=file]");
    await p.setInputFiles("input[type=file]", { name: "vertrag.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 test") });
    await p.waitForSelector("a:has-text('vertrag.pdf')"); await p.click("button:has-text('Löschen') >> nth=0"); await dlg("Test"); await p.waitForFunction(() => !document.body.textContent.includes("vertrag.pdf"));
  });
  await test("12 Backup erstellen und prüfen (unverschlüsselt)", async () => {
    await p.goto(base + "/einstellungen"); await p.click("button:has-text('Backup jetzt erstellen')"); await p.waitForSelector("text=Backup erstellt und Integrität geprüft");
  });
  await test("13 Verschlüsseltes Backup: Passphrase, Kennzeichnung, Prüfung", async () => {
    await p.click("button:has-text('Verschlüsseltes Backup erstellen')"); await dlg("geheim-1234-xyz"); await p.waitForSelector("text=Backup erstellt und Integrität geprüft");
    await p.waitForSelector("text=verschlüsselt");
    await p.click(".list-row:has-text('verschlüsselt') >> button:has-text('Prüfen')"); await dlg("geheim-1234-xyz"); await p.waitForSelector("text=intakt");
    await p.click(".list-row:has-text('verschlüsselt') >> button:has-text('Prüfen')"); await dlg("falsch-falsch-1234"); await p.waitForSelector(".alert.err");
  });
  await test("14 Datenprüfung meldet keine Auffälligkeiten", async () => {
    await p.click("button:has-text('Datenbestand prüfen')"); await p.waitForSelector("text=Keine Auffälligkeiten");
  });
  await test("15 Wiederherstellung: Änderung nach Backup wird zurückgenommen", async () => {
    const before = (await api("GET", "/parties?role=tenant")).items.length;
    await p.goto(base + "/einstellungen"); await p.click("button:has-text('Backup jetzt erstellen')"); await p.waitForSelector("text=Backup erstellt und Integrität geprüft");
    await api("POST", "/parties", { kind: "person", first_name: "Nach", last_name: "Backup", roles: ["tenant"] });
    expect((await api("GET", "/parties?role=tenant")).items.length === before + 1, "Testpartei fehlt");
    await p.reload(); await p.waitForSelector(".list-row");
    await p.click(".list-row:not(:has-text('verschlüsselt')) >> nth=0 >> button:has-text('Wiederherstellen')"); await p.click("form.dialog button[type=submit]"); await p.waitForSelector("text=/Wiederhergestellt/");
    await p.goto(base); await p.waitForSelector("text=Guten Tag, input[autocomplete=username]".split(",")[0]).catch(() => {});
    if (await p.locator("input[autocomplete=username]").count()) { await p.fill("input[autocomplete=username]", "admin"); await p.fill("input[type=password]", PW); await p.click("button.primary"); await p.waitForSelector("text=Guten Tag"); }
    expect((await api("GET", "/parties?role=tenant")).items.length === before, "Daten nicht zurückgesetzt");
  });
  await test("16 Responsive: kein Seitenüberlauf, keine abgeschnittenen KPI-Werte (4 Viewports × 6 Seiten + Dashboard mit Stichtag)", async () => {
    const bad = [];
    for (const [w, h] of [[1536, 1024], [1366, 768], [1280, 800], [1024, 768]]) {
      await p.setViewportSize({ width: w, height: h });
      for (const pg of ["/", "/mieter", "/finanzen", "/mahnwesen", "/betriebskosten", "/auswertungen/wirtschaftlichkeit"]) {
        await p.goto(base + pg); await p.waitForLoadState("networkidle");
        const r = await p.evaluate(() => ({ x: document.documentElement.scrollWidth - document.documentElement.clientWidth, c: [...document.querySelectorAll(".kpi .value")].filter((e) => e.scrollWidth > e.clientWidth + 1).length }));
        if (r.x > 1 || r.c) bad.push(`${w}x${h} ${pg} x=${r.x} clipped=${r.c}`);
      }
    }
    const d = new Date(Date.now() - 30 * 864e5), past = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    for (const [w, h] of [[1536, 1024], [1366, 768], [1280, 800], [1024, 768]]) {  // Dashboard mit Stichtag-Auswahl, Banner und Badges
      await p.setViewportSize({ width: w, height: h }); await p.goto(base + "/"); await p.waitForSelector("#stichtag-input");
      await p.fill("#stichtag-input", past); await p.waitForSelector("[data-testid=stichtag-banner]"); await p.waitForLoadState("networkidle");
      const r = await p.evaluate(() => ({ x: document.documentElement.scrollWidth - document.documentElement.clientWidth, c: [...document.querySelectorAll(".kpi .value, .kpi .kpi-badge")].filter((e) => e.scrollWidth > e.clientWidth + 1).length }));
      if (r.x > 1 || r.c) bad.push(`${w}x${h} / (Stichtag) x=${r.x} clipped=${r.c}`);
      await p.screenshot({ path: path.join(os.tmpdir(), `e2e-stichtag-${w}.png`) });
    }
    await p.setViewportSize({ width: 1536, height: 1024 }); expect(bad.length === 0, bad.join("; "));
  });
  await test("17 Dashboard: KPI-Definitionen (Info-Symbole) vorhanden", async () => {
    await p.goto(base + "/"); await p.waitForSelector(".kpi-info"); expect((await p.locator(".kpi-info").count()) > 5, "Keine KPI-Definitionen");
  });
  await test("18 Stammdaten bearbeiten: Partei und Zimmer, Änderung wird gespeichert", async () => {
    const S = ctxState;
    await p.goto(base + `/parteien/${S.tenant.id}`); await p.click("button:has-text('Stammdaten bearbeiten')");
    const city = p.locator(".modal label:has-text('Ort') input"); await city.fill("Hamburg"); await p.click(".modal button.primary"); await p.waitForFunction(() => !document.querySelector(".modal"));
    expect((await api("GET", `/parties/${S.tenant.id}`)).city === "Hamburg", "Ort nicht gespeichert");
    await p.goto(base + `/objekte/${S.prop.id}`); await p.waitForSelector("[data-testid=summary]");
    await p.click(".node:has-text('Zimmer 1') >> button:has-text('Bearbeiten')"); await p.locator(".modal label:has-text('Name') input").fill("Zimmer Süd"); await p.click(".modal button.primary");
    await p.waitForSelector("text=Zimmer Süd");
  });
  await test("19 Mietkonditionen als neue Version: Historie bleibt, Soll ändert sich nicht rückwirkend", async () => {
    const S = ctxState; const before = (await api("GET", "/charges?lease_id=" + S.sub.id)).items.length;
    await p.goto(base + `/vertraege/${S.sub.id}`); await p.click("button:has-text('Neue Konditionen (Version)')");
    await p.locator(".modal label:has-text('Gültig ab') input").fill("2027-01-01"); await p.locator(".modal label:has-text('Kaltmiete') input").fill("1200.00");
    await p.click(".modal button.primary"); await p.waitForFunction(() => !document.querySelector(".modal"));
    const d = await api("GET", `/leases/${S.sub.id}`); expect(d.terms.length >= 2, "Keine zweite Version");
    expect((await api("GET", "/charges?lease_id=" + S.sub.id)).items.length === before, "Sollstellungen wurden still verändert");
  });
  await test("20 Vertragsende ändern: Hinweis auf unveränderte Sollstellungen außerhalb der Laufzeit", async () => {
    const S = ctxState; await p.goto(base + `/vertraege/${S.sub.id}`); await p.click("button:has-text('Vertrag bearbeiten')");
    await p.locator(".modal label:has-text('Ende') input").fill("2026-01-31"); await p.click(".modal button.primary");
    await p.waitForSelector("text=/NICHT verändert|nicht verändert/");
  });
  await test("21 Dashboard-Stichtag: Auswahl, Banner, 'Heute' setzt zurück, Zukunftsdatum nicht wählbar", async () => {
    const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const today = iso(new Date()), past = iso(new Date(Date.now() - 30 * 864e5)), [py, pm, pd] = past.split("-");
    await p.goto(base + "/"); await p.waitForSelector("[data-testid=stichtag-picker]");
    expect((await p.getAttribute("#stichtag-input", "max")) === today, "max ist nicht heute");
    expect((await p.locator("[data-testid=stichtag-banner]").count()) === 0, "Banner ohne Stichtag");
    await p.fill("#stichtag-input", past); await p.waitForSelector("[data-testid=stichtag-banner]");
    const banner = await p.textContent("[data-testid=stichtag-banner]");
    expect(banner.includes(`Historische Auswertung zum ${pd}.${pm}.${py}`) && banner.includes("nicht alle Kennzahlen sind historisch verfügbar"), "Bannertext: " + banner.slice(0, 120));
    expect((await p.locator(".kpi .kpi-badge:has-text('aktueller Stand')").count()) > 0, "Keine Kennzeichnung 'aktueller Stand' für nicht-historische Kennzahlen");
    await p.fill("#stichtag-input", "2999-01-01"); await p.waitForSelector("[data-testid=stichtag-msg]");
    expect((await p.inputValue("#stichtag-input")) === past, "Zukunftsdatum wurde übernommen");
    expect((await p.textContent("[data-testid=stichtag-banner]")).includes(`${pd}.${pm}.${py}`), "Stichtag nach Zukunftsdatum verändert");
    await p.click("button:has-text('Heute')"); await p.waitForFunction(() => !document.querySelector("[data-testid=stichtag-banner]"));
    expect((await p.inputValue("#stichtag-input")) === today, "Feld nicht auf heute zurückgesetzt");
    expect((await p.locator(".kpi .kpi-badge").count()) === 0, "Badge nach Zurücksetzen noch sichtbar");
    ctxState.pastDay = past;
  });
  await test("22 Keine JavaScript-Fehler während des gesamten Laufs", async () => { expect(errors.length === 0, errors.slice(0, 3).join(" | ")); });

  await b.close(); srv.kill(); fs.rmSync(data, { recursive: true, force: true });
  const failed = results.filter((r) => !r[0]);
  console.log(`\n${results.length - failed.length}/${results.length} Abläufe bestanden`); process.exit(failed.length ? 1 : 0);
})();
