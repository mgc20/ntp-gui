// UI-Rundgang: alle Routen bei 1440 und 390 px, helles und dunkles Thema, im echten Browser (Playwright).
// Kein Unit-Test – läuft nur von Hand (siehe README.md) und braucht einen laufenden Server mit dem
// erfundenen chronyc (fake_chronyc.py).
//
// Prüft je Route (kanonische Routen seit 1.6):
//   * Konsolenfehler und Seitenfehler,
//   * Verstöße gegen die Content-Security-Policy,
//   * verbotene Zahlmuster („1,000 “, Punkt als Dezimalzeichen vor s/ms, Werte mit Einheit mit Tausenderpunkt),
//   * waagerechte Überbreite,
//   * ⓘ-Tippfläche: 10 px neben der Mitte trifft elementFromPoint noch das ⓘ (24 px Tippfläche),
//   * ⓘ überdeckt keine Nachbarn: elementFromPoint an den Innenrändern jedes Bedienelements trifft
//     dieses selbst und nicht ein ⓘ daneben.
// Dazu einmal je Breite die Navigation: jede alte Route landet per Weiterleitung (ohne Verlaufseintrag)
// auf der neuen, Reiterleiste, PTP aus als eine Zeile, untere Leiste nur ≤ 640 px ohne Überdeckung des
// letzten Inhalts, „Mehr“ per Tastatur (Enter/Esc/Tab hinaus, Fokus zurück bzw. auf den Inhalt), Reiterwechsel
// per Enter ohne Fokusverlust, Speicherleiste der Einstellungen über der unteren Leiste, /clock ohne deren
// Abstand, Tastenkürzel nicht im Suchfeld. Dazu die Einstellungen (settingsChecks): Reiter, Höhe < 2500 px
// bei 1440 px, Suche, „nur Geänderte“, Speicherleiste, Vorschau-Dialog, Nachfrage beim Verlassen.
//
// Aufruf: node tests/ui/tour.js [Basis-URL]   (Standard http://127.0.0.1:18300, oder TOUR_BASE)
// Ausgabe: JSON mit „problems“ (leer = alles gut) und einer Zeile je Route. Rückgabecode 1 bei Problemen.
// Bildschirmfotos landen in TOUR_SHOTS, wenn gesetzt. TOUR_NAV_ONLY=1 prüft nur die Navigation.
const { chromium } = require("playwright");

const BASE = process.argv[2] || process.env.TOUR_BASE || "http://127.0.0.1:18300";
const SHOTS = process.env.TOUR_SHOTS || "";
// Kanonische Routen seit 1.6 (app/static/js/routes.js).
const routes = ["/#/", "/#/quellen", "/#/gps", "/#/clients", "/#/clients/192.0.2.10", "/#/clients/192.0.2.10/pass",
  "/#/uhr/qualitaet", "/#/uhr/hardware", "/#/uhr/ptp", "/#/system/diagnose", "/#/system/benachrichtigungen",
  "/#/system/einstellungen", "/#/hilfe", "/clock", "/?dev=1#/muster", "/#/muster"];
// Alte Routen (bis 1.5) und Gruppen ohne Reiter → erwartete Adresse nach der Weiterleitung (location.replace,
// kein Verlaufseintrag). Alte Lesezeichen dürfen nie auf einer leeren Seite landen.
const redirects = {
  "/#/ptp": "#/uhr/ptp", "/#/uhrqualitaet": "#/uhr/qualitaet", "/#/hardware": "#/uhr/hardware",
  "/#/diagnose": "#/system/diagnose", "/#/benachrichtigungen": "#/system/benachrichtigungen",
  "/#/einstellungen": "#/system/einstellungen", "/#/einstellungen?s=gps": "#/system/einstellungen?s=gps",
  "/#/gnss": "#/gps", "/#/gpsquality": "#/gps", "/#/uhr": "#/uhr/qualitaet", "/#/system": "#/system/diagnose",
  "/#/quellen": "#/quellen", "/#/gps": "#/gps", "/#/clients": "#/clients", "/#/hilfe": "#/hilfe", "/#/": "#/",
  "/#/clients/192.0.2.10/pass": "#/clients/192.0.2.10/pass", "/#/hardware/x?y=1": "#/uhr/hardware/x?y=1",
};
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
  // Handy: Die untere Leiste (fest am Rand) deckt die letzten 56 px des Fensters ab – dort ist nichts zu treffen.
  const bar = document.getElementById("bottombar");
  const bottom = bar && bar.getBoundingClientRect().height ? bar.getBoundingClientRect().top : innerHeight;
  for (const b of [...document.querySelectorAll("button.info")].slice(0, 40)) {
    const r = b.getBoundingClientRect();
    // Nur ganz sichtbare ⓘ (nicht in waagerecht gescrollten Tabellen außerhalb des Fensters).
    if (!r.width || r.top < 12 || r.bottom > bottom - 12 || r.left < 12 || r.right > innerWidth - 12) continue;
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

// Navigation (1.6, T2): Weiterleitungen, untere Leiste, „Mehr“ per Tastatur, Reiter, Tastenkürzel, PTP aus.
async function navChecks(browser) {
  const found = [];
  const lines = [];
  for (const width of [1440, 390]) {
    const ctx = await browser.newContext({ viewport: { width, height: 800 } });
    // Weiterleitungen: richtige Adresse, Seite mit Inhalt, kein zusätzlicher Verlaufseintrag.
    // Vergleichswert: Verlaufslänge nach dem Öffnen einer Route ohne Weiterleitung (about:blank zählt mit).
    const plain = await ctx.newPage();
    await plain.goto(`${BASE}/#/quellen`, { waitUntil: "load" });
    await plain.waitForTimeout(500);
    const baseline = await plain.evaluate(() => history.length);
    await plain.close();
    for (const [from, want] of Object.entries(redirects)) {
      const page = await ctx.newPage();
      await page.goto(BASE + from, { waitUntil: "load" });
      await page.waitForTimeout(900);
      const got = await page.evaluate(() => ({ hash: location.hash, history: history.length,
        content: document.getElementById("main").innerText.trim().length,
        current: document.querySelector('#nav a[aria-current="page"]')?.dataset.nav || null }));
      if (got.hash !== want) found.push(`${width} ${from}: landet auf ${got.hash}, erwartet ${want}`);
      if (got.history !== baseline) found.push(`${width} ${from}: ${got.history} statt ${baseline} Verlaufseinträge (Weiterleitung muss ersetzen)`);
      if (got.content < 20) found.push(`${width} ${from}: leere Seite`);
      if (!got.current) found.push(`${width} ${from}: kein Navigationseintrag aktiv`);
      await page.close();
    }
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${BASE}/#/uhr/qualitaet`, { waitUntil: "load" });
    await page.waitForTimeout(1500);
    // Reiterleiste: drei Links, einer mit aria-current, Pfeiltaste wechselt den Fokus.
    const tabs = await page.evaluate(() => [...document.querySelectorAll("#tabs a.tab")].map((a) => ({
      href: a.getAttribute("href"), current: a.getAttribute("aria-current") })));
    if (tabs.length !== 3 || tabs.filter((x) => x.current === "page").length !== 1 || tabs[0].current !== "page") {
      found.push(`${width} Reiter Uhr & Hardware: ${JSON.stringify(tabs)}`);
    }
    await page.focus("#tabs a.tab");
    await page.keyboard.press("ArrowRight");
    const focusedTab = await page.evaluate(() => document.activeElement?.getAttribute("href"));
    if (focusedTab !== "#/uhr/hardware") found.push(`${width} Pfeiltaste in der Reiterleiste: Fokus auf ${focusedTab}`);
    // Enter auf dem Reiter wechselt die Seite, der Fokus bleibt auf dem (jetzt aktiven) Reiter, und die
    // Pfeiltasten wirken danach weiter.
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1200);
    const afterEnter = await page.evaluate(() => ({ hash: location.hash, focus: document.activeElement?.getAttribute("href") || document.activeElement?.tagName,
      current: document.activeElement?.getAttribute("aria-current") }));
    if (afterEnter.hash !== "#/uhr/hardware" || afterEnter.focus !== "#/uhr/hardware" || afterEnter.current !== "page") {
      found.push(`${width} Enter auf Reiter: Fokus verloren ${JSON.stringify(afterEnter)}`);
    }
    await page.keyboard.press("ArrowRight");
    const afterArrow = await page.evaluate(() => document.activeElement?.getAttribute("href") || document.activeElement?.tagName);
    if (afterArrow !== "#/uhr/ptp") found.push(`${width} Pfeiltaste nach Reiterwechsel: Fokus auf ${afterArrow}`);
    // PTP aus (erfundenes chronyc, keine PTP-Hardware): genau eine Zeile statt leerer Karten.
    await page.evaluate(() => { location.hash = "#/uhr/ptp"; });
    await page.waitForTimeout(1200);
    const ptp = await page.evaluate(() => ({ off: Boolean(document.querySelector("#main .ptp-off")),
      children: document.getElementById("main").children.length, cards: document.querySelectorAll("#main .card").length }));
    if (!ptp.off || ptp.children !== 1 || ptp.cards) found.push(`${width} PTP aus: ${JSON.stringify(ptp)}`);
    const bar = await page.evaluate(() => {
      const node = document.getElementById("bottombar");
      const style = node && getComputedStyle(node);
      return { shown: Boolean(node && style.display !== "none" && node.getBoundingClientRect().height > 0),
        overflow: node ? node.scrollWidth - node.clientWidth : 0,
        cut: [...document.querySelectorAll("#bottombar > a .nav-label, #bottombar > button .nav-label")]
          .filter((n) => n.scrollWidth > n.clientWidth).map((n) => n.textContent),
        topNav: getComputedStyle(document.getElementById("nav")).display,
        title: (() => { const h = document.getElementById("title-wrap"); return h ? h.scrollWidth - h.clientWidth : 0; })(),
        topbar: (() => { const t = document.querySelector(".topbar-inner"); return t ? t.scrollWidth - t.clientWidth : 0; })() };
    });
    lines.push(`nav ${width}: bottombar=${bar.shown} topnav=${bar.topNav} tabs=${tabs.length}`);
    if (width <= 640) {
      if (!bar.shown) found.push(`${width}: untere Leiste fehlt`);
      if (bar.topNav !== "none") found.push(`${width}: obere Navigation zusätzlich sichtbar`);
      if (bar.overflow > 0 || bar.title > 0 || bar.topbar > 0 || bar.cut.length) found.push(`${width}: abgeschnitten/Überbreite ${JSON.stringify(bar)}`);
      // Letzter Inhalt nicht verdeckt: ganz nach unten, dann liegen Seite und Fußzeile über der Leiste.
      for (const route of ["#/hilfe", "#/system/einstellungen", "#/"]) {
        await page.evaluate((h) => { location.hash = h; }, route);
        await page.waitForTimeout(1200);
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        await page.waitForTimeout(300);
        const cover = await page.evaluate(() => {
          const barTop = document.getElementById("bottombar").getBoundingClientRect().top;
          const last = document.getElementById("main").lastElementChild?.getBoundingClientRect();
          const footer = document.querySelector(".footer").getBoundingClientRect();
          return { barTop, last: last ? last.bottom : 0, footer: footer.bottom };
        });
        if (cover.last > cover.barTop + 0.5 || cover.footer > cover.barTop + 0.5) {
          found.push(`${width} ${route}: Inhalt unter der unteren Leiste ${JSON.stringify(cover)}`);
        }
      }
      // „Mehr“ per Tastatur: Enter öffnet, Fokus im Menü, Esc schließt, Fokus zurück auf „Mehr“.
      await page.focus("#bottombar .bottom-more");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(150);
      const opened = await page.evaluate(() => ({ visible: !document.getElementById("more-menu").hidden,
        expanded: document.querySelector(".bottom-more").getAttribute("aria-expanded"),
        focus: Boolean(document.activeElement?.closest("#more-menu")),
        items: [...document.querySelectorAll("#more-menu a")].map((a) => a.getAttribute("href")) }));
      if (!opened.visible || opened.expanded !== "true" || !opened.focus || opened.items.length !== 3) {
        found.push(`${width} Mehr öffnen per Tastatur: ${JSON.stringify(opened)}`);
      }
      await page.keyboard.press("Escape");
      await page.waitForTimeout(100);
      const closed = await page.evaluate(() => ({ hidden: document.getElementById("more-menu").hidden,
        focus: document.activeElement?.classList.contains("bottom-more") }));
      if (!closed.hidden || !closed.focus) found.push(`${width} Mehr schließen mit Esc: ${JSON.stringify(closed)}`);
      // Klick daneben schließt ebenfalls.
      await page.click("#bottombar .bottom-more");
      await page.mouse.click(200, 300);
      await page.waitForTimeout(100);
      if (!await page.evaluate(() => document.getElementById("more-menu").hidden)) found.push(`${width} Mehr: Klick daneben schließt nicht`);
      // Eintrag im Menü wählen: Seite wechselt, Menü zu, „Mehr“ markiert.
      await page.click("#bottombar .bottom-more");
      await page.click('#more-menu a[data-nav="system"]');
      await page.waitForTimeout(800);
      const chosen = await page.evaluate(() => ({ hash: location.hash, hidden: document.getElementById("more-menu").hidden,
        active: document.querySelector(".bottom-more").classList.contains("is-active") }));
      if (chosen.hash !== "#/system/diagnose" || !chosen.hidden || !chosen.active) found.push(`${width} Mehr → System: ${JSON.stringify(chosen)}`);
      // Eintrag per Tastatur wählen (auch die schon aktive Seite): Fokus landet nicht auf <body>.
      for (const round of [1, 2]) {
        await page.focus("#bottombar .bottom-more");
        await page.keyboard.press("Enter");
        await page.waitForTimeout(150);
        await page.focus('#more-menu a[data-nav="system"]');
        await page.keyboard.press("Enter");
        await page.waitForTimeout(800);
        const kb = await page.evaluate(() => ({ hash: location.hash, active: document.activeElement?.tagName,
          hidden: document.getElementById("more-menu").hidden }));
        if (kb.hash !== "#/system/diagnose" || kb.active === "BODY" || !kb.hidden) found.push(`${width} Mehr → System per Enter (${round}): ${JSON.stringify(kb)}`);
      }
      // Mit Tab hinter den letzten Eintrag: Menü schließt sich, aria-expanded zurück auf false.
      await page.focus("#bottombar .bottom-more");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(150);
      const count = await page.evaluate(() => document.querySelectorAll("#more-menu a").length);
      for (let i = 0; i < count + 2; i += 1) await page.keyboard.press("Tab");
      await page.waitForTimeout(150);
      const tabbed = await page.evaluate(() => ({ hidden: document.getElementById("more-menu").hidden,
        expanded: document.querySelector(".bottom-more").getAttribute("aria-expanded") }));
      if (!tabbed.hidden || tabbed.expanded !== "false") found.push(`${width} Mehr: Tab aus dem Menü schließt nicht ${JSON.stringify(tabbed)}`);
      // Einstellungen: geändertes Feld → Speicherleiste liegt über der unteren Leiste, Knöpfe treffbar.
      const edit = await ctx.newPage();
      edit.on("pageerror", (e) => errors.push(e.message));
      // Reiter „Dashboard & Zugang“: Textfelder mit input-Ereignis (Titel). Quellen hat nur das Quellen-Raster.
      await edit.goto(`${BASE}/#/system/einstellungen?s=zugang`, { waitUntil: "load" });
      await edit.waitForTimeout(1500);
      // Erstes Textfeld, dessen Änderung die Speicherleiste zeigt (andere Textfelder gehören z. B. zu API-Schlüsseln).
      let dirty = false;
      for (const field of (await edit.$$('#main input[type="text"]:not([disabled]):not([readonly])')).slice(0, 12)) {
        const before = await field.inputValue();
        await field.fill(`${before}x`);
        await edit.waitForTimeout(100);
        if (await edit.evaluate(() => document.querySelector(".save-bar")?.hidden === false)) { dirty = true; break; }
        await field.fill(before);
      }
      if (!dirty) found.push(`${width} Einstellungen: kein Feld zeigt nach einer Änderung die Speicherleiste`);
      else {
        for (const y of [0, 1500, 4000]) {
          await edit.evaluate((top) => window.scrollTo(0, top), y);
          await edit.waitForTimeout(200);
          const save = await edit.evaluate(() => {
            const bar = document.querySelector(".save-bar");
            if (!bar || bar.hidden) return { shown: false };
            const r = bar.getBoundingClientRect();
            const barTop = document.getElementById("bottombar").getBoundingClientRect().top;
            const buttons = [...bar.querySelectorAll("button")].map((b) => {
              const q = b.getBoundingClientRect();
              const hit = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2);
              return { text: b.textContent.trim(), ok: Boolean(hit && (hit === b || b.contains(hit))) };
            });
            return { shown: true, bottom: r.bottom, barTop, buttons };
          });
          if (!save.shown || save.bottom > save.barTop + 0.5 || !save.buttons.length || save.buttons.some((b) => !b.ok)) {
            found.push(`${width} Speicherleiste bei scrollY ${y}: ${JSON.stringify(save)}`);
          }
        }
      }
      await edit.close();
      // Uhrseite /clock: keine untere Leiste, also auch kein Abstand für sie.
      const clock = await ctx.newPage();
      await clock.goto(`${BASE}/clock`, { waitUntil: "load" });
      await clock.waitForTimeout(800);
      const pad = await clock.evaluate(() => getComputedStyle(document.body).paddingBottom);
      if (pad !== "0px") found.push(`${width} /clock: padding-bottom ${pad} (untere Leiste gibt es dort nicht)`);
      await clock.close();
    } else {
      if (bar.shown) found.push(`${width}: untere Leiste auf dem Desktop sichtbar`);
      // Tastenkürzel: g u → Uhr & Hardware, g o → Übersicht, ? → Übersicht der Kürzel, nicht im Suchfeld.
      await page.evaluate(() => { location.hash = "#/hilfe"; });
      await page.waitForTimeout(800);
      await page.keyboard.press("g"); await page.keyboard.press("u");
      await page.waitForTimeout(600);
      const afterGu = await page.evaluate(() => location.hash);
      if (afterGu !== "#/uhr/qualitaet") found.push(`g u: ${afterGu}`);
      await page.keyboard.press("g"); await page.keyboard.press("y");
      await page.waitForTimeout(600);
      const afterGy = await page.evaluate(() => location.hash);
      if (afterGy !== "#/system/diagnose") found.push(`g y: ${afterGy}`);
      await page.keyboard.press("?");
      await page.waitForTimeout(200);
      if (!await page.evaluate(() => Boolean(document.querySelector("dialog.shortcuts-dialog[open]")))) found.push("? öffnet keine Übersicht");
      await page.keyboard.press("Escape");
      await page.evaluate(() => { location.hash = "#/hilfe"; });
      await page.waitForTimeout(800);
      await page.keyboard.press("/");
      const inSearch = await page.evaluate(() => document.activeElement?.type === "search");
      if (!inSearch) found.push("/ fokussiert die Suche der Hilfe nicht");
      await page.keyboard.type("g o");
      await page.waitForTimeout(500);
      const stay = await page.evaluate(() => location.hash);
      if (stay !== "#/hilfe") found.push(`Kürzel im Suchfeld ausgelöst: ${stay}`);
    }
    if (errors.length) found.push(`${width} Seitenfehler: ${errors.join(" | ")}`);
    await page.close();
    await ctx.close();
  }
  return { found, lines };
}

// Einstellungen 2.0 (1.6, T2): Reiter, Höhe < 2500 px bei 1440 px (ohne aufgeklappte Erweitert-Bereiche),
// Suche („/“ fokussiert sie, Treffer springen in den Reiter), „nur Geänderte“, Speicherleiste mit Vorschau-Dialog,
// Nachfrage beim Verlassen mit ungespeicherten Änderungen, Speicherleiste bei 390 px über der unteren Leiste.
const SETTINGS_TABS = ["quellen", "lan", "gps", "ptp", "zugang", "sichern"];
const SETTINGS_MAX_HEIGHT = 2500;

async function settingsChecks(browser) {
  const found = [];
  const lines = [];
  for (const width of [1440, 390]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    let answer = false;
    const dialogs = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("dialog", async (d) => { dialogs.push(d.type()); if (answer) await d.accept(); else await d.dismiss(); });
    const base = `${BASE}/#/system/einstellungen`;
    // Reiter: sechs Links, genau einer aktiv, jeder Reiter adressierbar (?s=…) und mit eigenem Inhalt.
    const heights = {};
    for (const tab of SETTINGS_TABS) {
      await page.goto(`${base}?s=${tab}`, { waitUntil: "load" });
      await page.waitForTimeout(900);
      const got = await page.evaluate(() => ({
        tabs: [...document.querySelectorAll(".settings-tabs a.subtab")].map((a) => ({ tab: a.dataset.tab, current: a.getAttribute("aria-current") })),
        panel: document.querySelector(".settings-panel")?.id || null,
        cards: document.querySelectorAll(".settings-panel .card").length,
        advanced: document.querySelectorAll(".fields-advanced").length,
        height: document.documentElement.scrollHeight,
      }));
      heights[tab] = got.height;
      if (got.tabs.map((x) => x.tab).join() !== SETTINGS_TABS.join() || got.tabs.filter((x) => x.current === "true").length !== 1
        || got.tabs.find((x) => x.current === "true")?.tab !== tab) found.push(`${width} Einstellungen Reiter ${tab}: ${JSON.stringify(got.tabs)}`);
      if (got.panel !== `panel-${tab}` || !got.cards) found.push(`${width} Einstellungen ${tab}: Inhalt fehlt ${JSON.stringify(got)}`);
      if (got.advanced) found.push(`${width} Einstellungen ${tab}: Erweitert ist aufgeklappt`);
      if (width === 1440 && got.height >= SETTINGS_MAX_HEIGHT) found.push(`1440 Einstellungen ${tab}: ${got.height} px hoch (Ziel < ${SETTINGS_MAX_HEIGHT})`);
    }
    lines.push(`settings ${width}: ${SETTINGS_TABS.map((tab) => `${tab}=${heights[tab]}`).join(" ")}`);
    // Altes Sprungziel landet im richtigen Reiter.
    await page.goto(`${BASE}/#/einstellungen?s=web`, { waitUntil: "load" });
    await page.waitForTimeout(1200);
    const legacy = await page.evaluate(() => ({ hash: location.hash, tab: document.querySelector(".settings-tabs a[aria-current]")?.dataset.tab }));
    if (legacy.hash !== "#/system/einstellungen?s=web" || legacy.tab !== "zugang") found.push(`${width} ?s=web: ${JSON.stringify(legacy)}`);
    // Reiterwechsel per Klick.
    await page.click('.settings-tabs a[data-tab="gps"]');
    await page.waitForTimeout(800);
    const clicked = await page.evaluate(() => ({ hash: location.hash, panel: document.querySelector(".settings-panel")?.id }));
    if (clicked.hash !== "#/system/einstellungen?s=gps" || clicked.panel !== "panel-gps") found.push(`${width} Reiterklick: ${JSON.stringify(clicked)}`);
    // Suche: „/“ fokussiert das Suchfeld; ein Treffer aus einem anderen Reiter (erweitertes Feld) springt dorthin.
    await page.evaluate(() => document.activeElement?.blur());
    await page.keyboard.press("/");
    const focused = await page.evaluate(() => document.activeElement?.id);
    if (focused !== "settings-search") found.push(`${width} „/“ fokussiert die Suche nicht (${focused})`);
    await page.fill("#settings-search", "orphan");
    await page.waitForTimeout(200);
    const hitList = await page.evaluate(() => [...document.querySelectorAll(".search-hit")].map((b) => b.textContent));
    if (!hitList.length) found.push(`${width} Suche „orphan“: keine Treffer`);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1000);
    const jumped = await page.evaluate(() => {
      const row = document.getElementById("row-local_orphan");
      const r = row?.getBoundingClientRect();
      return { hash: location.hash, row: Boolean(row), visible: Boolean(r && r.bottom > 0 && r.top < innerHeight),
        focus: Boolean(row && row.contains(document.activeElement)) };
    });
    if (jumped.hash !== "#/system/einstellungen?s=lan" || !jumped.row || !jumped.visible || !jumped.focus) found.push(`${width} Suchtreffer springt nicht: ${JSON.stringify(jumped)}`);
    await page.fill("#settings-search", "ntp_minsources");
    await page.waitForTimeout(200);
    if (!await page.evaluate(() => [...document.querySelectorAll(".search-hit")].some((b) => b.textContent.includes("Mindestens")))) {
      found.push(`${width} Suche nach Schlüssel ntp_minsources findet das Feld nicht`);
    }
    await page.fill("#settings-search", "");
    // „nur Geänderte“: mit Standardwerten weniger Felder, aria-pressed; danach wieder alles.
    await page.goto(`${base}?s=quellen`, { waitUntil: "load" });
    await page.waitForTimeout(900);
    await page.click(".only-changed");
    await page.waitForTimeout(300);
    const only = await page.evaluate(() => ({ pressed: document.querySelector(".only-changed").getAttribute("aria-pressed"),
      fields: document.querySelectorAll(".settings-panel .field").length }));
    await page.click(".only-changed");
    await page.waitForTimeout(300);
    const all = await page.evaluate(() => document.querySelectorAll(".settings-panel .field").length);
    if (only.pressed !== "true" || only.fields >= all || !all) found.push(`${width} nur Geänderte: ${JSON.stringify(only)} gegen ${all}`);
    // Änderung → Speicherleiste mit Zähler und Neustart-Hinweis, Abzeichen am Feld, Vorschau als Diff.
    await page.fill("#f-ntp_minsources", "2");
    await page.waitForTimeout(200);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(200);
    const bar = await page.evaluate(() => {
      const node = document.querySelector(".save-bar");
      const meta = document.querySelector("#row-ntp_minsources .field-meta")?.textContent || "";
      const bottombar = document.getElementById("bottombar");
      const barTop = bottombar && bottombar.getBoundingClientRect().height ? bottombar.getBoundingClientRect().top : innerHeight;
      const r = node.getBoundingClientRect();
      const buttons = [...node.querySelectorAll("button")].map((b) => { const q = b.getBoundingClientRect();
        const hit = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2); return Boolean(hit && (hit === b || b.contains(hit))); });
      return { hidden: node.hidden, text: node.textContent, meta, bottom: r.bottom, barTop, buttons };
    });
    if (bar.hidden || !/1 Änderung/.test(bar.text) || !/Neustart der Zeitdienste/.test(bar.text) || !/Vorschau/.test(bar.text)) found.push(`${width} Speicherleiste: ${JSON.stringify(bar)}`);
    if (!/geändert/.test(bar.meta) || !/zurücksetzen/.test(bar.meta)) found.push(`${width} Abzeichen am geänderten Feld fehlt: ${bar.meta}`);
    if (bar.bottom > bar.barTop + 0.5 || bar.buttons.some((ok) => !ok)) found.push(`${width} Speicherleiste verdeckt: ${JSON.stringify(bar)}`);
    await page.click(".save-bar >> text=Vorschau");
    await page.waitForTimeout(1200);
    const preview = await page.evaluate(() => {
      const dialog = document.querySelector("dialog.preview-dialog");
      const r = dialog?.getBoundingClientRect();
      return { open: Boolean(dialog?.open), add: [...(dialog?.querySelectorAll(".diff-add") || [])].map((n) => n.textContent),
        del: [...(dialog?.querySelectorAll(".diff-del") || [])].map((n) => n.textContent),
        names: [...(dialog?.querySelectorAll(".preview-name code") || [])].map((n) => n.textContent),
        inline: dialog ? [...dialog.querySelectorAll("[style]")].length : -1, fits: Boolean(r && r.right <= innerWidth && r.left >= 0) };
    });
    // Ohne Supervisor (Rundgang) gibt es noch keine chrony.conf – dann ist alles „+“ (Datei wird neu angelegt).
    if (!preview.open || !preview.add.includes("+minsources 2") || (preview.del.length && !preview.del.includes("−minsources 1"))
      || preview.names.join() !== "chrony.conf,ptp4l.conf" || preview.inline || !preview.fits) found.push(`${width} Vorschau-Dialog: ${JSON.stringify(preview)}`);
    // Kein loser Text (etwa „null“) im Dialog; der Diff rollt in seinem eigenen Kasten, nicht der ganze Dialog.
    const previewBox = await page.evaluate(() => {
      const dialog = document.querySelector("dialog.preview-dialog");
      const body = dialog?.querySelector(".preview-body");
      const loose = body ? [...body.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent) : ["?"];
      const box = dialog?.getBoundingClientRect();
      const out = [...(dialog?.querySelectorAll("pre.diff") || [])].some((pre) => pre.getBoundingClientRect().right > box.right + 0.5);
      return { loose, client: dialog?.clientWidth, scroll: dialog?.scrollWidth, out };
    });
    if (previewBox.loose.length) found.push(`${width} Vorschau: loser Text ${JSON.stringify(previewBox.loose)}`);
    if (!(previewBox.scroll <= previewBox.client + 1) || previewBox.out) found.push(`${width} Vorschau läuft waagerecht über: ${JSON.stringify(previewBox)}`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
    if (await page.evaluate(() => Boolean(document.querySelector("dialog.preview-dialog[open]")))) found.push(`${width} Vorschau schließt nicht mit Esc`);
    // Verlassen mit ungespeicherten Änderungen: erst „Abbrechen“ (bleibt), dann „OK“ (verwirft).
    answer = false;
    await page.evaluate(() => { location.hash = "#/hilfe"; });
    await page.waitForTimeout(600);
    const stayed = await page.evaluate(() => ({ hash: location.hash, bar: document.querySelector(".save-bar")?.hidden === false }));
    if (stayed.hash !== "#/system/einstellungen?s=quellen" || !stayed.bar || !dialogs.includes("confirm")) found.push(`${width} Nachfrage beim Verlassen: ${JSON.stringify(stayed)} ${dialogs}`);
    answer = true;
    await page.evaluate(() => { location.hash = "#/hilfe"; });
    await page.waitForTimeout(800);
    await page.evaluate(() => { location.hash = "#/system/einstellungen?s=quellen"; });
    await page.waitForTimeout(800);
    const back = await page.evaluate(() => ({ bar: document.querySelector(".save-bar")?.hidden, value: document.getElementById("f-ntp_minsources")?.value }));
    if (!back.bar || back.value !== "1") found.push(`${width} Verwerfen beim Verlassen: ${JSON.stringify(back)}`);
    // Tastaturfokus bleibt nach „Verwerfen“ (Speicherleiste) und „zurücksetzen“ (Feld) auf der Seite.
    const focusAt = () => page.evaluate(() => {
      const node = document.activeElement;
      const main = document.getElementById("main");
      return node && node !== main && main?.contains(node) ? node.id || node.tagName : null;
    });
    await page.fill("#f-ntp_minsources", "2");
    await page.waitForTimeout(200);
    await page.focus(".save-bar >> text=Verwerfen");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);
    const afterDiscard = await focusAt();
    if (!afterDiscard) found.push(`${width} Fokus nach „Verwerfen“ verloren`);
    await page.fill("#f-ntp_minsources", "2");
    await page.waitForTimeout(200);
    await page.focus("#row-ntp_minsources .field-meta button.link");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);
    const afterReset = await focusAt();
    if (!afterReset) found.push(`${width} Fokus nach „zurücksetzen“ verloren`);
    if (await page.evaluate(() => document.querySelector(".save-bar")?.hidden === false)) {
      await page.click(".save-bar >> text=Verwerfen");
      await page.waitForTimeout(300);
    }
    // Alte Sprungziele scrollen auch beim zweiten und dritten Sprung in derselben Sitzung zur Karte.
    for (const [jumpTo, card] of [["dns", "s-dns"], ["api", "s-api"], ["dns", "s-dns"]]) {
      await page.evaluate(() => { location.hash = "#/hilfe"; });
      await page.waitForTimeout(500);
      await page.evaluate((s) => { location.hash = `#/system/einstellungen?s=${s}`; }, jumpTo);
      await page.waitForTimeout(900);
      const pos = await page.evaluate((id) => ({ y: Math.round(scrollY), top: Math.round(document.getElementById(id)?.getBoundingClientRect().top ?? -1) }), card);
      if (pos.top < 0 || pos.top > 300) found.push(`${width} Sprung ?s=${jumpTo} scrollt nicht zur Karte: ${JSON.stringify(pos)}`);
    }
    // Nächtliche Sicherung: Schalter im Reiter „Sichern“, nicht unter „Dashboard & Zugang“.
    await page.evaluate(() => { location.hash = "#/system/einstellungen?s=sichern"; });
    await page.waitForTimeout(900);
    const nightly = await page.evaluate(() => ({ here: Boolean(document.querySelector("#panel-sichern #f-backup_nightly")),
      oldText: document.getElementById("main").textContent.includes("Dashboard → Nächtliche") }));
    await page.evaluate(() => { location.hash = "#/system/einstellungen?s=zugang"; });
    await page.waitForTimeout(900);
    nightly.zugang = await page.evaluate(() => Boolean(document.getElementById("f-backup_nightly")));
    if (!nightly.here || nightly.oldText || nightly.zugang) found.push(`${width} Nächtliche Sicherung: ${JSON.stringify(nightly)}`);
    if (errors.length) found.push(`${width} Einstellungen Seitenfehler: ${errors.join(" | ")}`);
    await ctx.close();
  }
  return { found, lines };
}

(async () => {
  const browser = await chromium.launch();
  const results = [];
  let nav = { found: [], lines: [] };
  try {
    nav = await navChecks(browser);
    const settingsResult = await settingsChecks(browser);
    nav.found.push(...settingsResult.found);
    nav.lines.push(...settingsResult.lines);
    // TOUR_NAV_ONLY=1: nur die Navigationsprüfungen (schneller Durchlauf beim Arbeiten an der Navigation).
    for (const theme of process.env.TOUR_NAV_ONLY ? [] : ["light", "dark"]) {
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
  if (nav.found.length) problems.push({ check: "navigation", found: nav.found });
  console.log(JSON.stringify({ problems, summary: [...nav.lines, ...results.map((x) => `${x.theme} ${x.width} ${x.route} ovf=${x.overflow} `
    + `coll=${x.collapsed} info=${x.info.hitOk}/${x.info.count} ${x.info.size || ""} overlap=${x.overlaps.length}`)] }, null, 1));
  process.exit(problems.length ? 1 : 0);
})().catch((e) => { console.error(String(e)); process.exit(2); });
