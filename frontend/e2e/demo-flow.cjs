// Demo-Durchlauf (10 Schritte) gegen einen bereits laufenden Demo-Server (python -m leventum.demo).
//   DEMO_URL=http://127.0.0.1:8765 DEMO_PASSWORD=… NODE_PATH=$(npm root -g) node e2e/demo-flow.cjs
// Fuehrt die Schritte ueber die Oberflaeche aus und prueft die Ergebnisse gegen die API. Schreibt Screenshots nach $DEMO_SHOTS.
const { chromium } = require("playwright");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const base = process.env.DEMO_URL || "http://127.0.0.1:8765", PW = process.env.DEMO_PASSWORD || "";
const shots = process.env.DEMO_SHOTS || fs.mkdtempSync(path.join(os.tmpdir(), "demo-shots-"));
const today = new Date().toISOString().slice(0, 10);
const results = [], errors = [];
(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1536, height: 1024 } })).newPage();
  p.on("pageerror", (e) => errors.push(e.message)); p.on("console", (m) => m.type() === "error" && !/favicon|Failed to load resource/.test(m.text()) && errors.push(m.text()));
  const api = (url) => p.evaluate(async (url) => (await fetch("/api/v1" + url, { headers: { "X-Leventum-Client": "1" } })).json(), url);
  const shot = (n) => p.screenshot({ path: path.join(shots, n + ".png") });
  const kpis = async () => { await p.goto(base + "/"); await p.waitForSelector(".kpi"); await p.waitForTimeout(600);
    return p.$$eval("[data-testid^=kpi-]", (els) => Object.fromEntries(els.map((e) => [e.getAttribute("data-testid").slice(4), e.querySelector(".kpi-value, .value, strong, b")?.textContent?.trim() ?? e.textContent.replace(/\s+/g, " ").trim()]))); };
  const step = async (name, fn) => { try { const r = await fn(); results.push([true, name, r]); console.log("OK     ", name, r ?? ""); } catch (e) { results.push([false, name]); console.log("FEHLER ", name, "|", String(e.message).split("\n")[0]); await shot("fehler-" + results.length).catch(() => {}); } };
  const S = {}; const fillDlg = async (map) => { for (const [lbl, v] of Object.entries(map)) { const f = p.locator(`.modal label:has-text("${lbl}")`).first(); const sel = await f.locator("select").count(); if (sel) await f.locator("select").selectOption(v); else await f.locator("input").fill(v); } };

  await step("01 Anwendung starten / Anmelden", async () => {
    const h = await (await fetch(base + "/api/v1/health")).json(); if (!h.demo) throw new Error("kein Demo-Modus"); 
    await p.goto(base); await p.waitForSelector("input[type=password]");
    await p.fill("input[autocomplete=username]", "demo"); await p.fill("input[type=password]", PW); await p.click("button.primary"); await p.waitForSelector("text=Guten Tag");
    await p.waitForSelector("[data-testid=demo-banner]", { timeout: 5000 }).catch(() => { throw new Error("Demo-Banner fehlt"); }); return "Health ok, Demo-Banner sichtbar";
  });
  await step("02 Dashboard öffnen (Ausgangswerte)", async () => { S.k0 = await kpis(); await shot("02-dashboard-vorher"); S.dash0 = await api("/dashboard"); return JSON.stringify({ Immobilien: S.k0["Immobilien"], Wohneinheiten: S.k0["Wohneinheiten"], Auslastung: S.k0["Auslastungsquote"], "Offene Aufgaben": S.k0["Offene Aufgaben"] }); });
  const monthStart = today.slice(0, 8) + "01", ym = today.slice(0, 7);
  const lastDay = new Date(Number(today.slice(0, 4)), Number(today.slice(5, 7)), 0).toISOString().slice(0, 10).slice(0, 8) + String(new Date(Number(today.slice(0, 4)), Number(today.slice(5, 7)), 0).getDate()).padStart(2, "0");
  const eq = (got, want, what) => { if (String(got) !== String(want)) throw new Error(`${what}: erwartet ${want}, erhalten ${got}`); };
  const createLease = async (kind, fields) => {
    await p.goto(base + "/vertraege"); await p.click("button:has-text('Vertrag anlegen')");
    await p.locator(".modal label:has-text('Vertragsart') select").selectOption(kind);
    await p.locator(".modal label:has-text('Vertragstyp') select").selectOption({ index: 1 });
    if (kind === "main") await p.locator(".modal label:has-text('Vermieter') select").selectOption({ label: "Helga Brandt" });
    else await p.locator(".modal label:has-text('Mieter') select").first().selectOption({ label: "Lisa Schneider" });
    const m = p.locator(".modal label:has-text('Mietgegenstand') select");
    await p.waitForFunction(() => [...document.querySelectorAll(".modal select[multiple] option")].some((o) => o.text.includes("Demo-Neubau")), null, { timeout: 8000 });
    await m.selectOption({ label: (await m.locator("option").allTextContents()).find((o) => o.includes("Demo-Neubau")) });
    await p.locator(".modal label:has-text('Vertragsbeginn') input").fill(monthStart);
    await p.locator(".modal input[placeholder='850.00']").fill(fields.rent); await p.locator(".modal input[placeholder='180.00']").fill(fields.nk);
    if (kind === "main") await p.locator(".modal label:has-text('Untervermietung erlaubt') select").selectOption({ label: "Ja" });
    await p.click(".modal button:has-text('Entwurf anlegen')"); await p.waitForTimeout(1200);
    const l = (await api("/leases")).items.filter((x) => JSON.stringify(x).includes("Demo-Neubau")).find((x) => x.kind === kind); if (!l) throw new Error("Vertrag nicht in der API");
    await p.goto(base + `/vertraege/${l.id}`); await p.click("button:has-text('Prüfen & aktivieren')");
    await p.waitForFunction(async (id) => (await (await fetch(`/api/v1/leases/${id}`, { headers: { "X-Leventum-Client": "1" } })).json()).status === "active", l.id, { timeout: 8000 });
    return l;
  };

  await step("03 Immobilie anlegen (mit Eigentümer)", async () => {
    await p.goto(base + "/objekte"); await p.click("button:has-text('Objekt anlegen')");
    await fillDlg({ "Bezeichnung": "Demo-Neubau Hamburg", "Straße": "Hafenstraße 12", "PLZ": "20359", "Ort": "Hamburg", "Eigentümer": "Helga Brandt" });
    await p.click(".modal button:has-text('Anlegen')"); await p.waitForSelector("text=Demo-Neubau Hamburg"); await shot("03-immobilie");
    S.prop = (await api("/properties")).items.find((x) => x.name === "Demo-Neubau Hamburg"); if (!S.prop) throw new Error("API kennt Objekt nicht"); return "Objekt #" + S.prop.id;
  });
  await step("04 Wohneinheit anlegen und als Vermietungseinheit freigeben", async () => {
    await p.goto(base + `/objekte/${S.prop.id}`); await p.waitForSelector("h1:has-text('Demo-Neubau')");
    await p.click("text=+ Wohneinheit"); await p.fill("form.dialog input", "WE 1 – 2. OG links"); await p.click("form.dialog button[type=submit]"); await p.waitForSelector("text=WE 1 – 2. OG links");
    await p.locator(".list-row:has-text('WE 1 – 2. OG links') >> button:has-text('anlegen')").click(); await p.waitForSelector(".list-row:has-text('WE 1 – 2. OG links') >> text=angelegt");
    await shot("04-wohneinheit"); const d = await api(`/properties/${S.prop.id}`); if (d.units.length !== 1 || d.rentable_units.length !== 1) throw new Error("Einheit/Vermietungseinheit nicht gespeichert"); return "Einheit #" + d.units[0].id;
  });
  await step("05 Hauptmietvertrag (Eigentümer → Leventum) anlegen und aktivieren", async () => {
    S.main = await createLease("main", { rent: "600.00", nk: "100.00" }); await shot("05-hauptmietvertrag"); return "Hauptmietvertrag #" + S.main.id + " aktiv (600,00 € + 100,00 € NK)";
  });
  await step("06 Untermietvertrag (Leventum → Untermieter) anlegen und aktivieren", async () => {
    S.sub = await createLease("sub", { rent: "900.00", nk: "150.00" }); await shot("06-untermietvertrag"); return "Untermietvertrag #" + S.sub.id + " aktiv (900,00 € + 150,00 € NK)";
  });
  await step("07 Sollstellungen erzeugen (Vorschau, dann Erzeugen) und rechnerisch prüfen", async () => {
    await p.goto(base + "/finanzen"); await p.click("button:has-text('Sollstellungen erzeugen')");
    await p.locator(".modal label:has-text('Von') input").fill(ym); await p.locator(".modal label:has-text('Bis') input").fill(ym);
    await p.click(".modal button:has-text('Vorschau berechnen')"); await p.waitForSelector("[data-testid=charge-preview]");
    const cb = p.locator(".modal label.check input"); if (await cb.count()) await cb.check();
    await p.click(".modal button:has-text('Sollstellung(en) erzeugen')"); await p.waitForSelector(".alert.ok"); await shot("07-sollstellungen");
    const ch = async (id) => (await api(`/charges?lease_id=${id}&month=${ym}`)).items.filter((c) => c.status !== "voided");
    S.subCh = await ch(S.sub.id); S.mainCh = await ch(S.main.id);
    const sum = (a, k) => a.reduce((t, c) => t + Math.round(parseFloat(c[k]) * 100), 0) / 100;
    eq(sum(S.subCh, "amount").toFixed(2), "1050.00", "Soll Untermiete"); eq(sum(S.mainCh, "amount").toFixed(2), "700.00", "Soll Hauptmiete");
    eq(S.subCh.every((c) => c.direction === "receivable") && S.mainCh.every((c) => c.direction === "payable"), true, "Richtungen");
    return `Untermiete-Forderungen ${S.subCh.length}× = 1050,00 €; Hauptmiete-Verbindlichkeiten ${S.mainCh.length}× = 700,00 €`;
  });
  await step("08 Teilzahlung erfassen und der Kaltmiete-Forderung zuordnen", async () => {
    const rent = S.subCh.find((c) => c.charge_type === "base_rent");
    await p.goto(base + "/finanzen"); await p.click("button:has-text('Zahlung erfassen')");
    await p.locator(".modal label:has-text('Buchungsdatum') input").fill(today); await p.locator(".modal input[placeholder='1370.00']").fill("500.00");
    await p.locator(".modal label:has-text('Verwendungszweck') input").fill("Demo Teilzahlung Schneider");
    const sel = p.locator(".modal label:has-text('Sollstellung zuordnen') select"); await p.waitForFunction(() => [...document.querySelectorAll(".modal option")].some((o) => o.text.includes("Lisa Schneider")), null, { timeout: 8000 }).catch(() => {}); const lab = (await sel.locator("option").allTextContents()).find((o) => o.includes("Kaltmiete") && o.includes("Demo-Neubau")); if (!lab) throw new Error("Forderung im Zuordnungs-Dialog nicht wählbar");
    await sel.selectOption({ label: lab }); await p.click(".modal button:has-text('Speichern')"); await p.waitForSelector("text=Zahlung erfasst"); await shot("08-teilzahlung");
    const after = (await api(`/charges?lease_id=${S.sub.id}&month=${ym}`)).items; const r2 = after.find((c) => c.id === rent.id);
    eq(parseFloat(r2.allocated).toFixed(2), "500.00", "zugeordnet"); eq(parseFloat(r2.open_amount).toFixed(2), "400.00", "offen Kaltmiete"); eq(r2.status, "partial", "Status");
    const openAll = after.filter((c) => c.status !== "voided").reduce((t, c) => t + Math.round(parseFloat(c.open_amount ?? "0") * 100), 0) / 100; eq(openAll.toFixed(2), "550.00", "offen gesamt Untermieter");
    return "500,00 € zugeordnet → Kaltmiete offen 400,00 € (Teilzahlung), Vertrag gesamt offen 550,00 €";
  });
  await step("09 Wirtschaftlichkeit/Überschuss: Oberfläche und API rechnerisch geprüft", async () => {
    const e = await api(`/economics?start=${monthStart}&end=${lastDay}&scope=property&id=${S.prop.id}`);
    eq(e.soll.sub_total, "1050.00", "Soll Untermiete"); eq(e.soll.main_total, "700.00", "Soll Hauptmiete"); eq(e.contribution.soll_basis, "350.00", "Deckungsbeitrag Soll");
    eq(e.ist.in_total, "500.00", "Ist Eingang"); eq(e.ist.out_total, "0.00", "Ist Ausgang"); eq(e.contribution.ist_basis, "500.00", "Zahlungsfluss Ist");
    await p.goto(base + "/auswertungen/wirtschaftlichkeit"); await p.waitForTimeout(1500);
    const t = (await p.locator("main").innerText()).replace(/\s+/g, " "); if (!/Deckungsbeitrag/i.test(t)) throw new Error("Deckungsbeitrag nicht sichtbar"); await shot("09-wirtschaftlichkeit");
    return "Objekt Demo-Neubau (Monat): Soll 1050,00 − 700,00 = Deckungsbeitrag 350,00 € (Soll); Ist-Eingang 500,00 € (getrennt, nicht addiert)";
  });
  await step("10 Aufgabe erstellen", async () => {
    await p.goto(base + "/aufgaben"); await p.click("button:has-text('Aufgabe anlegen')");
    await p.locator(".modal label:has-text('Titel') input").fill("Demo: Restzahlung Schneider nachhalten"); await p.locator(".modal label:has-text('Fällig am') input").fill(today);
    await p.click(".modal button:has-text('Aufgabe anlegen')"); await p.waitForSelector("text=Demo: Restzahlung Schneider nachhalten"); await shot("10-aufgabe"); return "Aufgabe sichtbar";
  });
  await step("11 Dokument dem Untermietvertrag zuordnen", async () => {
    await p.goto(base + "/dokumente"); await p.click("button:has-text('Dokument hochladen')");
    await p.locator(".modal label:has-text('Zuordnung zu') select").selectOption({ label: "Vertrag" });
    const tgt = p.locator(".modal label:has-text('Ziel') select"); const o = (await tgt.locator("option").allTextContents()).find((x) => x.includes("Demo-Neubau") && x.includes("Untermiete")) || (await tgt.locator("option").allTextContents()).find((x) => x.startsWith("#" + S.sub.id)); if (!o) throw new Error("Zielvertrag fehlt");
    await tgt.selectOption({ label: o });
    fs.writeFileSync(path.join(shots, "demo-untermietvertrag.pdf"), "%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n");
    await p.setInputFiles(".modal input[type=file]", path.join(shots, "demo-untermietvertrag.pdf")); await p.click(".modal button:has-text('Hochladen')");
    await p.waitForSelector("a:has-text('demo-untermietvertrag.pdf')"); await shot("11-dokument");
    await p.goto(base + `/vertraege/${S.sub.id}`); await p.waitForSelector("a:has-text('demo-untermietvertrag.pdf')"); return "Dokument am Vertrag #" + S.sub.id + " sichtbar";
  });
  await step("12 Dashboard-Kennzahlen erneut kontrollieren (Vorher/Nachher, rechnerisch)", async () => {
    const k1 = await kpis(); await shot("12-dashboard-nachher");
    const num = (t) => parseFloat(t.replace(/[^\d,-]/g, "").replace(".", "").replace(",", "."));
    const money = (t) => parseFloat(t.replace(/\./g, "").replace(/[^\d,-]/g, "").replace(",", "."));
    eq(Number(k1["Immobilien"]) - Number(S.k0["Immobilien"]), 1, "Immobilien Δ"); eq(Number(k1["Wohneinheiten"]) - Number(S.k0["Wohneinheiten"]), 1, "Wohneinheiten Δ");
    eq(Number(k1["Aktive Hauptmietverträge"]) - Number(S.k0["Aktive Hauptmietverträge"]), 1, "Hauptmietverträge Δ"); eq(Number(k1["Aktive Untermietverträge"]) - Number(S.k0["Aktive Untermietverträge"]), 1, "Untermietverträge Δ");
    eq(Number(k1["Offene Aufgaben"]) - Number(S.k0["Offene Aufgaben"]), 1, "Aufgaben Δ");
    eq((money(k1["Monatliche Untermietforderungen"]) - money(S.k0["Monatliche Untermietforderungen"])).toFixed(2), "1050.00", "Untermietforderungen Δ");
    eq((money(k1["Monatliche Hauptmietverpflichtungen"]) - money(S.k0["Monatliche Hauptmietverpflichtungen"])).toFixed(2), "700.00", "Hauptmietverpflichtungen Δ");
    eq((money(k1["Offene Mietforderungen"]) - money(S.k0["Offene Mietforderungen"])).toFixed(2), "550.00", "Offene Mietforderungen Δ");
    return `Auslastung ${S.k0["Auslastungsquote"]} → ${k1["Auslastungsquote"]} (neue WE vermietet: 8 von 9); Untermietforderungen +1050,00 €; Hauptmietverpflichtungen +700,00 €; offene Forderungen +550,00 €`;
  });
  console.log("\nKonsolenfehler:", errors.length ? errors : "keine"); console.log("Screenshots:", shots);
  console.log(`\n${results.filter((r) => r[0]).length}/${results.length} Schritte bestanden`);
  await b.close(); process.exit(results.every((r) => r[0]) && !errors.length ? 0 : 1);
})();
