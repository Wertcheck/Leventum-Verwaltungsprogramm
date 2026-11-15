// Responsive-Prüfung: je Viewport und Seite (a) kein horizontaler Seitenüberlauf, (b) kein abgeschnittener KPI-Wert, (c) Screenshot.
// Voraussetzung: Instanz mit Demodaten (seed-and-shoot.cjs), Benutzer admin / ein-langes-passwort-123.
//   NODE_PATH=$(npm root -g) node frontend/e2e/responsive.cjs http://127.0.0.1:8780 /tmp/shots
const { chromium } = require("playwright");
const base = process.argv[2] || "http://127.0.0.1:8780", out = process.argv[3] || "/tmp/shots";
const VIEWPORTS = [[1536, 1024], [1366, 768], [1280, 800], [1024, 768]];
const PAGES = ["/", "/mieter", "/objekte", "/vertraege", "/finanzen", "/mahnwesen", "/bankimport", "/kautionen", "/betriebskosten", "/aufgaben", "/reparaturen", "/dokumente", "/auswertungen/wirtschaftlichkeit", "/auswertungen/leerstand", "/einstellungen"];
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 1536, height: 1024 } }); const p = await ctx.newPage();
  const errors = []; p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(base); await p.waitForSelector("input[autocomplete=username]");
  await p.fill("input[autocomplete=username]", "admin"); await p.fill("input[type=password]", "ein-langes-passwort-123"); await p.click("button.primary");
  await p.waitForSelector("text=Guten Tag");
  let bad = 0;
  for (const [w, h] of VIEWPORTS) {
    await p.setViewportSize({ width: w, height: h });
    for (const path of PAGES) {
      await p.goto(base + path); await p.waitForLoadState("networkidle"); await p.waitForTimeout(250);
      const r = await p.evaluate(() => {
        const de = document.documentElement;
        const clipped = [...document.querySelectorAll(".kpi .value, .kpi .label")].filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent.slice(0, 40));
        return { overflowX: de.scrollWidth - de.clientWidth, clipped };
      });
      const name = `${w}x${h}${path === "/" ? "-dashboard" : path.replace(/\//g, "-")}`;
      const flag = r.overflowX > 1 || r.clipped.length ? "FEHLER" : "OK  ";
      if (flag === "FEHLER") bad++;
      console.log(`${flag} ${w}x${h} ${path}  überlauf=${r.overflowX}px${r.clipped.length ? " abgeschnitten=" + JSON.stringify(r.clipped) : ""}`);
      if (path === "/" || path === "/mieter" || path === "/mahnwesen") await p.screenshot({ path: `${out}/${name}.png`, fullPage: true });
    }
  }
  console.log(bad ? `${bad} Befund(e)` : "Keine Überläufe", "| JS-Fehler:", JSON.stringify(errors));
  await b.close(); process.exit(bad ? 1 : 0);
})();
