// UI-Rundgang: alle Routen bei 1440 und 390 px, helles und dunkles Thema, im echten Browser (Playwright).
// Kein Unit-Test – läuft nur von Hand (siehe README.md) und braucht einen laufenden Server mit dem
// erfundenen chronyc (fake_chronyc.py).
//
// Prüft je Route:
//   * Konsolenfehler und Seitenfehler,
//   * Verstöße gegen die Content-Security-Policy,
//   * verbotene Zahlmuster („1,000 “, Punkt als Dezimalzeichen vor s/ms, Werte mit Einheit mit Tausenderpunkt),
//   * waagerechte Überbreite,
//   * ⓘ-Tippfläche: 10 px neben der Mitte trifft elementFromPoint noch das ⓘ (24 px Tippfläche),
//   * ⓘ überdeckt keine Nachbarn: elementFromPoint an den Innenrändern jedes Bedienelements trifft
//     dieses selbst und nicht ein ⓘ daneben.
//
// Aufruf: node tests/ui/tour.js [Basis-URL]   (Standard http://127.0.0.1:18095, oder TOUR_BASE)
// Ausgabe: JSON mit „problems“ (leer = alles gut) und einer Zeile je Route. Rückgabecode 1 bei Problemen.
// Bildschirmfotos landen in TOUR_SHOTS, wenn gesetzt.
const { chromium } = require("playwright");

const BASE = process.argv[2] || process.env.TOUR_BASE || "http://127.0.0.1:18095";
const SHOTS = process.env.TOUR_SHOTS || "";
const routes = ["/#/", "/#/quellen", "/#/gps", "/#/ptp", "/#/uhrqualitaet", "/#/hardware", "/#/clients",
  "/#/clients/192.0.2.10", "/#/clients/192.0.2.10/pass", "/#/diagnose", "/#/benachrichtigungen",
  "/#/einstellungen", "/#/hilfe", "/clock", "/?dev=1#/muster", "/#/muster"];
const FORBIDDEN = /\d,000(\s|$)|\d\.\d+ (s|ms)\b|\d{1,3}\.\d{3}(,\d+)? (ppm|ppb|ns|µs|ms|s)\b/;

// Läuft im Browser: Bedienelemente, deren Rand ein ⓘ (oder dessen Tippfläche) verdeckt.
function overlapCheck() {
  const found = [];
  const controls = document.querySelectorAll("button:not(.info), a[href], input, select, textarea, summary");
  for (const node of controls) {
    const r = node.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    const xs = [r.left + 1, r.left + r.width / 2, r.right - 1];
    const ys = [r.top + 1, r.top + r.height / 2, r.bottom - 1];
    for (const x of xs) {
      for (const y of ys) {
        if (x !== xs[1] && y !== ys[1]) continue; // nur Kantenmitten und Ränder, keine Ecken (border-radius)
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
        const hit = document.elementFromPoint(x, y);
        const info = hit && hit.closest(".info");
        if (info && !node.contains(info)) {
          found.push(`${node.tagName.toLowerCase()} „${(node.textContent || node.getAttribute("aria-label") || node.placeholder || "").trim().slice(0, 30)}“ bei (${Math.round(x)},${Math.round(y)}) → ⓘ „${info.getAttribute("aria-label") || ""}“`);
        }
      }
    }
  }
  return found;
}

function infoHitCheck() {
  const out = { count: 0, hitOk: 0, size: null };
  for (const b of [...document.querySelectorAll("button.info")].slice(0, 40)) {
    const r = b.getBoundingClientRect();
    // Nur ganz sichtbare ⓘ (nicht in waagerecht gescrollten Tabellen außerhalb des Fensters).
    if (!r.width || r.top < 12 || r.bottom > innerHeight - 12 || r.left < 12 || r.right > innerWidth - 12) continue;
    const box = b.closest(".table-scroll")?.getBoundingClientRect();
    if (box && (r.left < box.left + 12 || r.right > box.right - 12)) continue;
    out.count += 1; out.size = `${r.width}x${r.height}`;
    const hit = document.elementFromPoint(r.left + r.width / 2 + 10, r.top + r.height / 2);
    if (hit && (hit === b || b.contains(hit))) out.hitOk += 1;
  }
  return out;
}

async function scrolledOverlaps(page) {
  // Ganze Seite abfahren: elementFromPoint sieht nur den sichtbaren Ausschnitt.
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  const view = page.viewportSize().height;
  const all = new Set();
  for (let y = 0; y < height; y += Math.max(200, view - 100)) {
    await page.evaluate((top) => window.scrollTo(0, top), y);
    await page.waitForTimeout(30);
    for (const line of await page.evaluate(overlapCheck)) all.add(line);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  return [...all];
}

(async () => {
  const browser = await chromium.launch();
  const results = [];
  try {
    for (const theme of ["light", "dark"]) {
      for (const width of [1440, 390]) {
        const ctx = await browser.newContext({ colorScheme: theme, viewport: { width, height: 900 } });
        await ctx.addInitScript((t) => {
          window.__csp = [];
          try { localStorage.setItem("ntp-gui-theme", JSON.stringify(t)); } catch (e) { /* egal */ }
          document.addEventListener("securitypolicyviolation", (e) =>
            window.__csp.push(`${e.violatedDirective} ${e.blockedURI} ${e.sourceFile}:${e.lineNumber} ${e.sample}`));
        }, theme);
        for (const route of routes) {
          const page = await ctx.newPage();
          const msgs = [];
          page.on("console", (m) => { if (m.type() === "error" || /Content Security Policy|Refused/i.test(m.text())) msgs.push(`${m.type()}: ${m.text()}`); });
          page.on("pageerror", (e) => msgs.push(`pageerror: ${e.message}`));
          await page.goto(BASE + route, { waitUntil: "load" });
          await page.waitForTimeout(2500);
          const overlaps = await scrolledOverlaps(page);
          const info = await page.evaluate(infoHitCheck);
          // „Diagramm zeigen“ einmal aufklappen, wenn vorhanden, und einige ⓘ öffnen und schließen.
          const toggle = await page.$(".chart-line-toggle");
          if (toggle) { await toggle.click(); await page.waitForTimeout(400); }
          for (const b of (await page.$$("button.info")).slice(0, 8)) {
            try { await b.click({ timeout: 500 }); await page.waitForTimeout(60); await page.keyboard.press("Escape"); } catch (e) { /* verdeckt */ }
          }
          const data = await page.evaluate(() => ({
            csp: window.__csp, text: document.body.innerText,
            overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            collapsed: document.querySelectorAll(".chart-card.is-collapsed").length,
          }));
          const forbidden = data.text.split("\n").filter((l) => FORBIDDEN.test(l)).slice(0, 5);
          results.push({ theme, width, route, console: msgs, csp: data.csp, forbidden, overflow: data.overflow,
            overlaps, collapsed: data.collapsed, info });
          if (SHOTS && theme === "light") {
            const name = route.replace(/[^a-z]+/g, "_") || "root";
            await page.screenshot({ path: `${SHOTS}/shot_${width}${name}.png`, fullPage: true });
          }
          await page.close();
        }
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
  }
  const problems = results.filter((x) => x.console.length || x.csp.length || x.forbidden.length || x.overflow > 0
    || x.overlaps.length || x.info.hitOk < x.info.count);
  console.log(JSON.stringify({ problems, summary: results.map((x) => `${x.theme} ${x.width} ${x.route} ovf=${x.overflow} `
    + `coll=${x.collapsed} info=${x.info.hitOk}/${x.info.count} ${x.info.size || ""} overlap=${x.overlaps.length}`) }, null, 1));
  process.exit(problems.length ? 1 : 0);
})().catch((e) => { console.error(String(e)); process.exit(2); });
