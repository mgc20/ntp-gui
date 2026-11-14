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
// Zuerst der Willkommens-Assistent (setupChecks): rundgang.sh startet mit leerem Datenverzeichnis = Erststart. Bei
// 390 px öffnet die Startseite den Assistenten von selbst, alle fünf Schritte nur mit „Weiter“, dann „Später“ –
// danach darf sich nichts geändert haben (Einstellungen, setup_done). Bei 1440 px dasselbe mit Vorlage und Vorschau
// (ohne Übernehmen) und am Ende „Fertig“ – danach öffnet sich nichts mehr von selbst, und die Übersicht zeigt die
// Checkliste. Je Schritt: Überschrift hat den Fokus, genau ein Schritt mit aria-current, keine Überbreite, keine
// Tippfläche unter 24 px (ⓘ prüft infoHitCheck), keine CSP-Verstöße.
//
// Dazu die Clients (clientsChecks: Karten bei 390 px, Name direkt bearbeiten mit Enter/Esc) und die sichtbare
// Wortzahl je Seite (wordCounts, Ausgabe „words“; TOUR_WORDS_ONLY=1 misst nur sie). Dazu pagesChecks mit erfundenen
// Antworten: Clients mit Messwert (Zellen, ⓘ auf dem Handy) und Rohdaten der Ereignisse (TOUR_PAGES_ONLY=1). Dazu die
// Uhr-Werkstatt (clockChecks, TOUR_CLOCK_ONLY=1): jedes /clock-Design mit fester Serverzeit bei 390 und 1440 px, auch im
// Rotlicht-Modus, dazu Kiosk, E-Ink, zweite Zeitzone und unzulässige Parameter ohne Überbreite; E-Ink ohne Änderungen
// zwischen den Minuten, Leiste bleibt bei offenem Ton-Panel, #tone-status nicht im Sekundentakt (clockQuietChecks);
// Studiouhr A1 (clockStudioChecks): Zustände ok/free/degraded/none auf neun Flächen, Sprung der Geräteuhr, Taktlücke.
// Studiouhr A3/A4 (clockLayoutChecks, TOUR_LAYOUT_ONLY=1): alle Designs auf neun Flächen und mit Layout-Parametern –
// Zeit im safe-Rand, kein Ziffernumbruch, kein Scrollbalken, CSS-Spiegel = resolveLayout, Ziffern, CSSOM-Farben, CSP.
// Studiouhr A5 (clockCountdownChecks, TOUR_COUNTDOWN_ONLY=1): Countdown, Überzeit und Countdown als Hauptanzeige auf
// neun Flächen, Farbstufen mit Symbol und Text, Zone des Servers, Timer, Stoppuhr, Tastenkürzel, lock=1, Ansagen.
// Studiouhr A6 (clockLinkChecks, TOUR_LINK_ONLY=1): Profil (?p=) auf neun Flächen mit gemocktem Profil und /api/v1/time,
// Neuladen bei geändertem profiles_rev, Panel „Anpassen“ (Übernehmen ohne Parameter), Reiter „Anzeigen“ im Dashboard.
// Dazu timelineChecks (1.6, T7): Zustandsband und Marker bei 390/1440 px mit erfundenem Tag, Tastaturbedienung.
//
// Aufruf: node tests/ui/tour.js [Basis-URL]   (Standard http://127.0.0.1:18300, oder TOUR_BASE)
// Ausgabe: JSON mit „problems“ (leer = alles gut) und einer Zeile je Route. Rückgabecode 1 bei Problemen.
// Bildschirmfotos landen in TOUR_SHOTS, wenn gesetzt. TOUR_NAV_ONLY=1 prüft nur die Navigation.
const { chromium } = require("playwright");

const BASE = process.argv[2] || process.env.TOUR_BASE || "http://127.0.0.1:18300";
const SHOTS = process.env.TOUR_SHOTS || "";
// Kanonische Routen seit 1.6 (app/static/js/routes.js).
const routes = ["/#/", "/#/quellen", "/#/gps", "/#/clients", "/#/clients/192.0.2.10", "/#/clients/192.0.2.10/pass",
  "/#/uhr/qualitaet", "/#/uhr/hardware", "/#/uhr/ptp", "/#/uhr/anzeigen", "/#/system/diagnose", "/#/system/benachrichtigungen",
  "/#/system/einstellungen", "/#/system/einrichtung", "/#/system/einrichtung/quellen", "/#/system/einrichtung/gps",
  "/#/system/einrichtung/clients", "/#/system/einrichtung/benachrichtigung", "/#/hilfe", "/clock", "/?dev=1#/muster",
  "/#/muster"];
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
    // Reiterleiste: vier Links (mit „Anzeigen“), einer mit aria-current, Pfeiltaste wechselt den Fokus.
    const tabs = await page.evaluate(() => [...document.querySelectorAll("#tabs a.tab")].map((a) => ({
      href: a.getAttribute("href"), current: a.getAttribute("aria-current") })));
    if (tabs.length !== 4 || tabs.filter((x) => x.current === "page").length !== 1 || tabs[0].current !== "page") {
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

// Clients (1.6, T2 „Seiten entschlacken“): bei 390 px Karten statt Tabelle ohne Überbreite, bei 1440 px die
// Tabelle; Name direkt in der Liste: ✎ öffnet das Feld (Fokus darin), Esc bricht ab (Fokus zurück auf ✎, nichts
// gespeichert), Enter speichert (Name steht danach in der Liste); zum Schluss wird der Name wieder entfernt.
async function clientsChecks(browser) {
  const found = [];
  const lines = [];
  const NAME = "Rundgang-Gerät";
  for (const width of [1440, 390]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${BASE}/#/clients`, { waitUntil: "load" });
    await page.waitForTimeout(2000);
    const layout = await page.evaluate(() => ({
      cards: document.querySelectorAll("#main .client-card").length,
      table: Boolean(document.querySelector("#main table.clients-table")),
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      wide: [...document.querySelectorAll("#main .client-card")].filter((c) => c.scrollWidth > c.clientWidth + 1).length,
      edit: document.querySelectorAll("#main .name-edit").length,
    }));
    lines.push(`clients ${width}: cards=${layout.cards} table=${layout.table} edit=${layout.edit}`);
    if (width <= 640 && (!layout.cards || layout.table)) found.push(`${width} Clients: Karten statt Tabelle erwartet ${JSON.stringify(layout)}`);
    if (width > 640 && (layout.cards || !layout.table)) found.push(`${width} Clients: Tabelle erwartet ${JSON.stringify(layout)}`);
    if (layout.overflow > 0 || layout.wide) found.push(`${width} Clients: Überbreite ${JSON.stringify(layout)}`);
    if (!layout.edit) { found.push(`${width} Clients: kein ✎ zum Umbenennen`); await ctx.close(); continue; }
    const ip = await page.evaluate(() => document.querySelector("#main .name-cell .client-link")?.getAttribute("href")?.split("/").pop());
    const cellText = () => page.evaluate((h) => document.querySelector(`#main .client-link[href$="/${h}"]`)?.closest(".name-cell")?.textContent || "", ip);
    // Esc bricht ab.
    await page.click("#main .name-edit");
    await page.waitForTimeout(300);
    const opened = await page.evaluate(() => ({ input: Boolean(document.querySelector("#main .name-input")),
      focus: document.activeElement?.classList.contains("name-input") }));
    if (!opened.input || !opened.focus) found.push(`${width} Name bearbeiten: Feld nicht offen/fokussiert ${JSON.stringify(opened)}`);
    await page.keyboard.type("Abbruch");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    const cancelled = await page.evaluate(() => ({ input: Boolean(document.querySelector("#main .name-input")),
      focus: document.activeElement?.classList.contains("name-edit") }));
    if (cancelled.input || !cancelled.focus || (await cellText()).includes("Abbruch")) found.push(`${width} Esc im Namensfeld: ${JSON.stringify(cancelled)}`);
    // Enter speichert.
    await page.click("#main .name-edit");
    await page.waitForTimeout(300);
    await page.fill("#main .name-input", NAME);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(2500);
    const saved = await cellText();
    if (!saved.includes(NAME)) found.push(`${width} Enter im Namensfeld speichert nicht: „${saved}“`);
    if (await page.evaluate(() => document.querySelector("#main .inline-error")?.textContent || "")) found.push(`${width} Fehlermeldung nach dem Speichern`);
    const after = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (after > 0) found.push(`${width} Clients mit Namen: Überbreite ${after}`);
    // Aufräumen: Name wieder entfernen.
    await page.click(`#main .name-edit`);
    await page.waitForTimeout(300);
    await page.fill("#main .name-input", "");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1500);
    if ((await cellText()).includes(NAME)) found.push(`${width} Name ließ sich nicht wieder entfernen`);
    if (errors.length) found.push(`${width} Clients Seitenfehler: ${errors.join(" | ")}`);
    await ctx.close();
  }
  return { found, lines };
}

// Nachbesserung T2d, mit erfundenen Antworten (page.route), weil das erfundene chronyc weder messbare Clients
// noch Ereignisse liefert:
//   * Clients mit Messwert: keine Zelle in einer Zelle (td td, dd td), bei 390 px dieselben Spalten-ⓘ wie bei
//     1440 px in der Geräteliste, die Erklärung zum „*“ sichtbar;
//   * Diagnose, Ereignisse bei 390 px: „Rohdaten“ mit mindestens 24 px Tippfläche; aufgeklappt und mit Fokus
//     bleibt beides über das Neuladen nach 30 s erhalten.
async function pagesChecks(browser) {
  const found = [];
  const lines = [];
  const infos = {};
  const offsets = { available: true, names: {}, clients: {
    "192.0.2.10": { measurable: true, ewma: 0.0012, min: 0.001, max: 0.0014, count: 12, state: "ok", requests: 25 },
    "192.0.2.99": { measurable: false, state: "verschleiert", requests: 4, last_seen: Math.floor(Date.now() / 1000) } } };
  for (const width of [1440, 390]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await ctx.newPage();
    await page.route("**/api/clients/offsets*", (route) => route.fulfill({ json: offsets }));
    await page.route("**/api/status*", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      delete body.clientmon;
      await route.fulfill({ response, json: body });
    });
    await page.goto(`${BASE}/#/clients`, { waitUntil: "load" });
    await page.waitForTimeout(2500);
    const got = await page.evaluate(() => {
      const list = [...document.querySelectorAll("#main .card")].find((c) => /Geräte, die diesen Server fragen/.test(c.textContent));
      return { nested: document.querySelectorAll("#main td td, #main dd td, #main td dd, #main dd dd").length,
        value: Boolean(document.querySelector("#main .offset-value")),
        infos: list ? [...list.querySelectorAll("button.info")].map((b) => b.getAttribute("aria-label")).sort() : [],
        star: list ? list.innerText.includes("* aus der eigenen Messung") : false,
        cells: [...document.querySelectorAll("#main table.clients-table td.num")].filter((td) => td.querySelector(".offset-value"))
          .map((td) => { const a = td.getBoundingClientRect(); const b = td.querySelector(".offset-value").getBoundingClientRect();
            return Math.round(a.right - b.right); }) };
    });
    infos[width] = got.infos;
    lines.push(`pages clients ${width}: nested=${got.nested} infos=${got.infos.length} star=${got.star}`);
    if (!got.value) found.push(`${width} Clients: erfundener Messwert nicht sichtbar`);
    if (got.nested) found.push(`${width} Clients: ${got.nested} verschachtelte Zellen`);
    if (got.cells.some((gap) => gap > 16)) found.push(`${width} Clients: Abweichung nicht rechtsbündig ${JSON.stringify(got.cells)}`);
    if (width <= 640 && !got.star) found.push(`${width} Clients: Erklärung zum * fehlt`);
    await ctx.close();
  }
  if (JSON.stringify(infos[390]) !== JSON.stringify(infos[1440])) {
    found.push(`Clients: ⓘ bei 390 px ${JSON.stringify(infos[390])} ≠ 1440 px ${JSON.stringify(infos[1440])}`);
  }

  const ctx = await browser.newContext({ viewport: { width: 390, height: 900 } });
  const page = await ctx.newPage();
  await page.clock.install();
  const now = Math.floor(Date.now() / 1000);
  const events = [{ t: now - 60, kind: "service", level: "info", title: "Dienst gestartet", data: { pid: 4711, grund: "Rundgang" } },
    { t: now - 120, kind: "source", level: "warn", title: "Quelle gewechselt", data: { von: "a", nach: "b" } }];
  let served = 0;
  await page.route("**/api/events?*", (route) => { served += 1; return route.fulfill({ json: { events } }); });
  await page.goto(`${BASE}/#/system/diagnose`, { waitUntil: "load" });
  await page.clock.runFor(2500);
  await page.waitForTimeout(300);
  const summary = page.locator("#main details.diag-event-raw summary").first();
  if (!(await summary.count())) {
    found.push("Diagnose: keine Ereignisse mit Rohdaten");
  } else {
    const box = await summary.boundingBox();
    if (!box || box.height < 24) found.push(`Diagnose: „Rohdaten“ nur ${box && box.height.toFixed(1)} px hoch`);
    await summary.focus();
    await page.keyboard.press("Enter");
    lines.push(`pages diagnose 390: vor dem Neuladen ${JSON.stringify(await page.evaluate(() => ({ open: document.querySelector("#main details.diag-event-raw")?.open, n: document.querySelectorAll("#main details.diag-event-raw").length, key: document.querySelector("#main details.diag-event-raw")?.dataset.key, focus: document.activeElement?.tagName })))}`);
    const before = served;
    await page.evaluate(() => { document.querySelector("#main .diag-events").dataset.mark = "1"; });
    await page.clock.runFor(31000);
    await page.waitForTimeout(500);
    const after = await page.evaluate(() => {
      const first = document.querySelector("#main details.diag-event-raw");
      return { open: Boolean(first && first.open), focus: document.activeElement === first?.querySelector("summary"),
        same: document.querySelector("#main .diag-events")?.dataset.mark === "1", active: document.activeElement?.tagName };
    });
    lines.push(`pages diagnose 390: summary=${box && box.height.toFixed(1)} reloads=${served - before} open=${after.open} focus=${after.focus}`);
    if (served <= before) found.push("Diagnose: Ereignisse nach 30 s nicht neu geladen");
    if (!after.open || !after.focus) found.push(`Diagnose: Rohdaten nach dem Neuladen ${JSON.stringify(after)}`);
  }
  await ctx.close();
  return { found, lines };
}

// Uhr-Werkstatt (1.6, T6): jedes Design mit fester Serverzeit bei 390 und 1440 px, normal und im Rotlicht-Modus.
// Die Browseruhr steht 5 min daneben, /api/v1/time liefert die Serverzeit – angezeigt werden muss die Serverzeit.
// Dazu Kiosk/E-Ink/zweite Zeitzone ohne Überbreite und ein unzulässiger ?design=.
// Seit der monotonen Zeitbasis (Studiouhr A1) läuft die Anzeige mit performance.now() weiter. Damit die erwartete
// Uhrzeit fest bleibt, ist die Playwright-Uhr angehalten (Date und performance.now()) und rückt nur per runFor vor;
// der Mock antwortet mit der Serverzeit, die zur vorgerückten Browserzeit passt (wie ein echter Server).
const CLOCK_SERVER = Date.parse("2026-06-30T08:15:42.500Z");   // Europe/Berlin: 10:15:42, am 30.6. (Osterei)
const CLOCK_DEVICE_OFF = 300000;   // die Browseruhr geht 5 min nach
const CLOCK_SETTLE_MS = 1500;      // so viel Browserzeit bis zur Prüfung: fünf Messungen im Abstand von 250 ms
const CLOCK_STEP_MS = 250;

/**
 * /clock mit angehaltener Playwright-Uhr öffnen. Browserzeit beim Laden = CLOCK_SERVER − CLOCK_SETTLE_MS − 5 min,
 * nach settle() steht die Serverzeit auf CLOCK_SERVER. Der Mock (opts.reply) bekommt die passende Serverzeit (ms)
 * und liefert die Antwort (null = Server antwortet nicht).
 */
// hold: Promise, auf die jede Antwort von /api/v1/time wartet (verzögerte erste Antwort); settle=false: ohne Einschwingen
// zurück, um den Zustand vor der ersten Antwort zu prüfen. zone: Zeitzone des Browsers.
async function openPausedClock(browser, { width, height = 900, query = "", red = false, reply, hold = null, settle = true,
  zone = "Europe/Berlin", profile = null, storage = null } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, timezoneId: zone });
  await ctx.addInitScript(([isRed, extra]) => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
    try { localStorage.setItem("ntp-gui-clock-red", isRed ? "1" : "0"); localStorage.removeItem("ntp-gui-clock-design"); } catch (e) { /* egal */ }
    // Zusätzliche Einträge (Sprache, gemerkter Stand) nur beim ersten Laden: Ein Neuladen soll sie nicht zurücksetzen.
    try {
      if (extra && !sessionStorage.getItem("tour-storage")) {
        for (const [key, value] of Object.entries(extra)) localStorage.setItem(key, value);
        sessionStorage.setItem("tour-storage", "1");
      }
    } catch (e) { /* egal */ }
  }, [red, storage]);
  const page = await ctx.newPage();
  const msgs = [];
  page.on("console", (m) => { if (m.type() === "error") msgs.push(m.text()); });
  page.on("pageerror", (e) => msgs.push(`pageerror: ${e.message}`));
  const clock = { advanced: 0, hits: 0, base: CLOCK_SERVER - CLOCK_SETTLE_MS };
  const start = clock.base - CLOCK_DEVICE_OFF;
  await page.clock.install({ time: start });
  await page.clock.pauseAt(start);
  const answer = reply || ((ms) => ({ t1: ms / 1000, t2: ms / 1000, synchronised: true, running: true, level: "good",
    accuracy: 0.0004, stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS", source: null, public: true }));
  await page.route("**/api/v1/time", async (route) => {
    if (hold) await hold;
    clock.hits += 1;
    const json = answer(clock.base + clock.advanced);
    return json ? route.fulfill({ json }) : route.fulfill({ status: 503, body: "" });
  });
  // Studiouhr A6: Profil-Abruf gemockt (profile(name) → Antwort, null = 404 oder "fail" = 503).
  if (profile) {
    await page.route("**/api/v1/clock/profile*", (route) => {
      clock.profileHits = (clock.profileHits || 0) + 1;
      const json = profile(new URL(route.request().url()).searchParams.get("p"));
      if (json === "fail") return route.fulfill({ status: 503, body: "" });
      return json ? route.fulfill({ json }) : route.fulfill({ status: 404, json: { error: "Profil nicht gefunden" } });
    });
  }
  await page.goto(`${BASE}/clock${query}`, { waitUntil: "load" });
  // Browserzeit in Schritten vorrücken; dazwischen echte Zeit für die Antworten des Mocks.
  clock.run = async (ms) => {
    for (let done = 0; done < ms; done += CLOCK_STEP_MS) {
      await page.waitForTimeout(120);
      const step = Math.min(CLOCK_STEP_MS, ms - done);
      await page.clock.runFor(step);
      clock.advanced += step;
    }
    await page.waitForTimeout(120);
  };
  if (settle) await clock.run(CLOCK_SETTLE_MS);
  return { ctx, page, msgs, clock };
}
const CLOCK_EXPECT = {
  digital: { text: "10:15:42" }, nixie: { text: "101542" }, flip: { text: "101542" },
  wort: { text: "ES IST VIERTEL NACH ZEHN" }, bahnhof: { hour: 307.5, minute: 90, second: 42.5 },
};

function clockState() {
  const face = document.getElementById("face");
  const svg = face.querySelector("svg.bh");
  const second = face.querySelector(".bh-second");
  const kiosk = document.querySelector(".clock-bar");
  return {
    mode: document.documentElement.dataset.mode || "", design: document.documentElement.dataset.design,
    digital: document.getElementById("local-time").hidden ? null : document.getElementById("local-time").textContent,
    nixie: [...face.querySelectorAll(".nixie-tube")].map((tube) => tube.querySelector(".nixie-n.on")?.textContent || "?").join(""),
    flip: [...face.querySelectorAll(".flip-digit")].map((node) => node.textContent).join(""),
    wort: face.querySelector(".wort-text")?.textContent || "",
    hour: svg && svg.querySelector(".bh-hour").getAttribute("transform"),
    minute: svg && svg.querySelector(".bh-minute").getAttribute("transform"),
    sweep: second ? { cls: second.classList.contains("is-sweep"), delay: getComputedStyle(second).animationDelay,
      name: getComputedStyle(second).animationName } : null,
    egg: !document.getElementById("leap-egg").hidden,
    tz: document.getElementById("tz2").hidden ? null : document.getElementById("tz2-time").textContent,
    bar: kiosk ? getComputedStyle(kiosk).display : null,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    csp: window.__csp || [],
  };
}

async function clockChecks(browser) {
  const found = [];
  const lines = [];
  const open = async (width, query, red = false) => {
    const { ctx, page, msgs } = await openPausedClock(browser, { width, query, red });
    const got = await page.evaluate(clockState);
    await ctx.close();
    return { got, msgs };
  };
  for (const width of [390, 1440]) {
    for (const red of [false, true]) {
      for (const [design, want] of Object.entries(CLOCK_EXPECT)) {
        const { got, msgs } = await open(width, `?design=${design}`, red);
        const label = `/clock ${design} ${width}${red ? " Rotlicht" : ""}`;
        const problems = [];
        if (got.design !== design) problems.push(`Design ${got.design}`);
        if (red !== (got.mode === "red")) problems.push(`Modus „${got.mode}“`);
        if (want.text && got[design] !== want.text) problems.push(`zeigt „${got[design]}“ statt „${want.text}“`);
        if (design === "bahnhof") {
          if (got.hour !== `rotate(${want.hour} 100 100)` || got.minute !== `rotate(${want.minute} 100 100)`) {
            problems.push(`Zeiger ${got.hour} / ${got.minute}`);
          }
          const delay = -parseFloat(got.sweep?.delay || "0");
          if (!got.sweep?.cls || got.sweep.name !== "bh-sweep" || Math.abs(delay - want.second) > 1) {
            problems.push(`Sekundenzeiger ${JSON.stringify(got.sweep)}`);
          }
        }
        if (!got.egg) problems.push("Schaltsekunden-Banner am 30.6. fehlt");
        if (got.overflow > 0) problems.push(`Überbreite ${got.overflow} px`);
        if (got.csp.length || msgs.length) problems.push(`Fehler ${JSON.stringify([...got.csp, ...msgs])}`);
        lines.push(`${label}: ${problems.length ? problems.join("; ") : "ok"}`);
        if (problems.length) found.push(`${label}: ${problems.join("; ")}`);
      }
    }
    for (const [query, check] of [
      ["?kiosk=1&design=bahnhof", (g) => (g.bar === "none" ? "" : `Leiste sichtbar (${g.bar})`)],
      ["?eink=1&design=nixie&tz=America/New_York", (g) => (g.mode === "eink" && g.nixie === "1015" && g.tz === "04:15" ? ""
        : `E-Ink ${g.mode} ${g.nixie} ${g.tz}`)],
      ["?eink=1&kiosk=1&design=wort", (g) => (g.wort === "ES IST VIERTEL NACH ZEHN" && g.bar === "none" ? "" : `E-Ink-Kiosk ${g.wort}`)],
      ["?design=%3Cb%3E&tz=Mars%2FOlymp&kiosk=ja", (g) => (g.design === "digital" && g.tz === null && g.bar !== "none"
        && g.digital === "10:15:42" ? "" : `Allowlist ${g.design} ${g.tz} ${g.bar}`)],
    ]) {
      const { got, msgs } = await open(width, query);
      const problem = [check(got), got.overflow > 0 ? `Überbreite ${got.overflow} px` : "",
        got.csp.length || msgs.length ? `Fehler ${JSON.stringify([...got.csp, ...msgs])}` : ""].filter(Boolean).join("; ");
      lines.push(`/clock${query} ${width}: ${problem || "ok"}`);
      if (problem) found.push(`/clock${query} ${width}: ${problem}`);
    }
  }
  const quiet = await clockQuietChecks(browser);
  found.push(...quiet.found);
  lines.push(...quiet.lines);
  const studio = await clockStudioChecks(browser);
  found.push(...studio.found);
  lines.push(...studio.lines);
  const layout = await clockLayoutChecks(browser);
  found.push(...layout.found);
  lines.push(...layout.lines);
  const countdown = await clockCountdownChecks(browser);
  found.push(...countdown.found);
  lines.push(...countdown.lines);
  const linkResult = await clockLinkChecks(browser);
  found.push(...linkResult.found);
  lines.push(...linkResult.lines);
  return { found, lines };
}

// Studiouhr A1 (clockStudioChecks): Zeitbasis und Zustände auf allen Flächen aus docs/konzept/studiouhr.md
// (Akzeptanz A). Je Viewport die Zustände ok, free, degraded und none mit angehaltener Playwright-Uhr: data-sync
// am Root, der Zustand als Text mit Symbol (nie nur Farbe), richtige Uhrzeit, Sekunden grau, wenn die Schranke
// sie nicht trägt, keine Überbreite, kein Ziffernumbruch, keine CSP-Verstöße. Die Zustandszeile liegt ganz im
// sichtbaren Bereich, ohne senkrechten Scrollbalken, und ist mindestens 12 px bzw. 5 % der Uhrzeit hoch (auch im
// Kiosk). Das Band meldet im Zustand degraded nicht „good“. Rotlicht: Zustandstext ≥ 4,5:1, graue Stellen ≥ 3:1.
// Dazu bei 1920×1080: Die Geräteuhr springt um ±1 h (Anzeige unverändert, aber bis zum neuen Anker nicht „ok“),
// eine Taktlücke wie nach dem Standby löst eine Neumessung aus, ?lead= wird angezeigt.
const STUDIO_VIEWPORTS = [[360, 640], [390, 844], [768, 1024], [1920, 1080], [3840, 2160], [3840, 1080], [1920, 200],
  [480, 270], [1080, 1920]];

function studioState() {
  const root = document.documentElement;
  const time = document.getElementById("local-time");
  const hm = document.getElementById("local-hm");
  const sec = document.getElementById("local-sec");
  const sync = document.getElementById("clock-sync");
  const box = sync.getBoundingClientRect();
  const size = parseFloat(getComputedStyle(time).fontSize);
  const lum = (color) => {
    const [r, g, b] = color.match(/[\d.]+/g).slice(0, 3).map((v) => {
      const c = Number(v) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (a, b) => { const x = lum(a); const y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const bg = getComputedStyle(document.body).backgroundColor;
  return {
    top: box.top, bottom: box.bottom, innerHeight: window.innerHeight,
    vscroll: document.documentElement.scrollHeight - document.documentElement.clientHeight,
    syncSize: parseFloat(getComputedStyle(sync).fontSize), timeHeight: time.getBoundingClientRect().height,
    syncContrast: contrast(getComputedStyle(document.getElementById("clock-sync-text")).color, bg),
    secContrast: contrast(getComputedStyle(sec).color, bg), timeContrast: contrast(getComputedStyle(hm).color, bg),
    band: document.getElementById("band").dataset.state, bandMain: document.getElementById("band-main").textContent,
    sync: root.dataset.sync || "", seconds: root.dataset.seconds || "", lineSync: sync.dataset.sync,
    text: document.getElementById("clock-sync-text").textContent, icon: document.getElementById("clock-sync-icon").textContent,
    shown: box.width > 0 && box.height > 0 && getComputedStyle(sync).visibility !== "hidden",
    time: time.textContent, wrapped: time.getBoundingClientRect().height > size * 1.6,
    grey: getComputedStyle(sec).color !== getComputedStyle(hm).color,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    csp: window.__csp || [],
  };
}

async function clockStudioChecks(browser) {
  const found = [];
  const lines = [];
  const good = (ms) => ({ t1: ms / 1000, t2: ms / 1000, synchronised: true, running: true, level: "good", accuracy: 0.0004,
    stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS", source: null, public: true });
  const STATES = {
    ok: { reply: good, want: { sync: "ok", text: /^abgeglichen · Anzeige ± \d+ ms$/, time: "10:15:42", grey: false } },
    // Server kennt seine Uhr nur auf 0,6 s: Schranke über maxerr (unsicher) und über 0,5 s (Sekunden grau).
    degraded: { reply: (ms) => ({ ...good(ms), level: "warn", accuracy: 0.6 }),
      want: { sync: "degraded", text: /^unsicher · Anzeige ± 6\d\d ms$/, time: "10:15:42", grey: true } },
    // Server antwortet nie: Gerätezeit (5 min daneben), Sekunden grau.
    none: { reply: () => null, want: { sync: "none", text: /^Gerätezeit, nicht abgeglichen$/, time: "10:10:42", grey: true } },
    // Erst abgeglichen, dann antwortet der Server nicht mehr: nach 12 s frei laufend, die Anzeige läuft weiter.
    free: { reply: good, after: 12000, want: { sync: "free", text: /^frei laufend seit 1[23] s · ± \d+ ms$/, time: "10:15:54",
      grey: false } },
  };
  // Rotlicht (Kontrast hängt nicht von der Fläche ab) und Kiosk (Schriftgröße) auf ausgewählten Flächen.
  const EXTRA = [
    ...[[360, 640], [3840, 2160]].flatMap((vp) => ["ok", "degraded", "free", "none"].map((name) => [vp, `${name} Rotlicht`, { ...STATES[name], red: true }])),
    ...[[3840, 2160], [1920, 200], [480, 270]].flatMap((vp) => ["ok", "degraded"].map((name) => [vp, `${name} Kiosk`, { ...STATES[name], query: "?kiosk=1" }])),
  ];
  const RUNS = [...STUDIO_VIEWPORTS.flatMap((vp) => Object.entries(STATES).map(([name, spec]) => [vp, name, spec])), ...EXTRA];
  for (const [[width, height], name, spec] of RUNS) {
    {
      let failing = false;
      const reply = (ms) => (failing ? null : spec.reply(ms));
      const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, reply, query: spec.query || "",
        red: Boolean(spec.red) });
      if (spec.after) {
        failing = true;
        await clock.run(spec.after);
      }
      const got = await page.evaluate(studioState);
      await ctx.close();
      const want = spec.want;
      const problems = [];
      if (got.sync !== want.sync || got.lineSync !== want.sync) problems.push(`data-sync ${got.sync}/${got.lineSync}`);
      if (!want.text.test(got.text)) problems.push(`Text „${got.text}“`);
      if (!got.icon.trim() || !got.shown) problems.push(`Zustand nicht sichtbar (${JSON.stringify(got.icon)}, ${got.shown})`);
      if (got.time !== want.time) problems.push(`zeigt ${got.time} statt ${want.time}`);
      if (got.grey !== want.grey || (got.seconds === "unsure") !== want.grey) problems.push(`Sekunden grau=${got.grey} (${got.seconds})`);
      if (got.wrapped) problems.push("Ziffernumbruch");
      if (got.overflow > 0) problems.push(`Überbreite ${got.overflow} px`);
      if (got.top < 0 || got.bottom > got.innerHeight + 0.5) problems.push(`Zustand außerhalb des Bildes (${Math.round(got.top)}..${Math.round(got.bottom)} von ${got.innerHeight})`);
      if (got.vscroll > 0) problems.push(`senkrechter Scrollbalken (${got.vscroll} px)`);
      if (got.syncSize < Math.max(12, 0.05 * got.timeHeight) - 0.5) problems.push(`Zustand zu klein (${got.syncSize} px bei ${Math.round(got.timeHeight)} px Uhrzeit)`);
      if (want.sync === "degraded" && got.band === "good") problems.push(`Band meldet „${got.bandMain}“ (good) bei unsicherer Anzeige`);
      if (spec.red) {
        if (got.syncContrast < 4.5) problems.push(`Rotlicht: Zustandstext ${got.syncContrast.toFixed(2)}:1`);
        if (want.grey && got.secContrast < 3) problems.push(`Rotlicht: graue Sekunden ${got.secContrast.toFixed(2)}:1`);
        if (got.timeContrast < 3) problems.push(`Rotlicht: Uhrzeit ${got.timeContrast.toFixed(2)}:1`);
      }
      // Die absichtlich ausbleibenden Antworten (503) meldet Chromium als Ladefehler – nur diese sind erwartet.
      const errors = msgs.filter((m) => !(spec.reply === STATES.none.reply || spec.after) || !/status of 503/.test(m));
      if (got.csp.length || errors.length) problems.push(`Fehler ${JSON.stringify([...got.csp, ...errors])}`);
      const label = `/clock Studio ${width}×${height} ${name}`;
      lines.push(`${label}: ${problems.length ? problems.join("; ") : "ok"}`);
      if (problems.length) found.push(`${label}: ${problems.join("; ")}`);
    }
  }

  // Geräteuhr springt (setSystemTime ändert nur Date, nicht performance.now()): Die Anzeige darf nicht mitspringen.
  {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080 });
    // Ein Uhrsprung sieht aus wie ein Standby mit stehender monotoner Uhr: bis zum neuen Anker nicht „ok“.
    const before = await page.evaluate(studioState);
    const now = await page.evaluate(() => Date.now());
    const hitsJump = clock.hits;
    await page.clock.setSystemTime(now + 3600000);
    await clock.run(1000);
    const ahead = await page.evaluate(studioState);
    await clock.run(1500);
    const aheadSettled = await page.evaluate(studioState);
    const jumpHits = clock.hits - hitsJump;
    await page.clock.setSystemTime(now - 3600000);
    await clock.run(1000);
    const behind = await page.evaluate(studioState);
    await clock.run(1500);
    const behindSettled = await page.evaluate(studioState);
    // Taktlücke wie nach dem Standby: fastForward lässt jeden fälligen Zeitgeber höchstens einmal laufen.
    const hits = clock.hits;
    await page.clock.fastForward(6000);
    clock.advanced += 6000;
    await clock.run(1500);
    const after = await page.evaluate(studioState);
    const resync = clock.hits - hits;
    await ctx.close();
    const problems = [];
    const times = [before, ahead, aheadSettled, behind, behindSettled].map((x) => x.time);
    if (times.join(" ") !== "10:15:42 10:15:43 10:15:44 10:15:45 10:15:47") problems.push(`Anzeige folgt der Geräteuhr: ${times.join(" → ")}`);
    for (const [tag, got] of [["+1 h", ahead], ["−1 h", behind]]) {
      if (got.sync !== "degraded" || got.seconds !== "unsure" || !/Geräteuhr gesprungen oder Standby/.test(got.text)) {
        problems.push(`Uhrsprung ${tag}: data-sync ${got.sync}, Sekunden ${got.seconds}, „${got.text}“`);
      }
      if (got.band === "good") problems.push(`Uhrsprung ${tag}: Band meldet good`);
    }
    if (aheadSettled.sync !== "ok" || behindSettled.sync !== "ok") problems.push(`nach dem neuen Anker data-sync ${aheadSettled.sync}/${behindSettled.sync}`);
    if (jumpHits < 5) problems.push(`nach dem Uhrsprung nur ${jumpHits} Abfragen (Neumessung fehlt)`);
    if (resync < 5) problems.push(`nach der Taktlücke nur ${resync} Abfragen (Neumessung fehlt)`);
    if (after.sync !== "ok") problems.push(`nach der Taktlücke data-sync ${after.sync}`);
    if (msgs.length) problems.push(`Fehler ${JSON.stringify(msgs)}`);
    lines.push(`/clock Studio Geräteuhr ±1 h, Taktlücke: ${problems.length ? problems.join("; ") : `ok (${resync} Abfragen)`}`);
    if (problems.length) found.push(`/clock Studio Geräteuhr/Taktlücke: ${problems.join("; ")}`);
  }

  // Vorlauf ?lead=200: Zustand nennt ihn, die Anzeige läuft 0,2 s vor (42,5 s + 0,2 s bleibt in Sekunde 42);
  // unzulässige Werte lassen die Uhr ohne Vorlauf.
  for (const [query, want] of [["?lead=200", /· Vorlauf 200 ms$/], ["?lead=500&maxerr=abc", /Anzeige ± \d+ ms$/]]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 1080, query });
    const got = await page.evaluate(studioState);
    await ctx.close();
    const problem = [want.test(got.text) ? "" : `Text „${got.text}“`, got.time === "10:15:42" ? "" : `zeigt ${got.time}`,
      got.sync === "ok" ? "" : `data-sync ${got.sync}`, msgs.length ? `Fehler ${JSON.stringify(msgs)}` : ""]
      .filter(Boolean).join("; ");
    lines.push(`/clock Studio ${query}: ${problem || "ok"}`);
    if (problem) found.push(`/clock Studio ${query}: ${problem}`);
  }
  return { found, lines };
}

// Studiouhr A3/A4 (clockLayoutChecks): Layout-Engine und Designs aus docs/konzept/studiouhr.md (Akzeptanz A).
// Je Fläche (STUDIO_VIEWPORTS: Handy, Tablet, 1080p, 4K, 32:9, 1920×200, 480×270, 9:16) jedes Design samt digital mit
// 7-Segment, dazu Parameter (safe, layout, scale, shift, show, bg, look/accent, h12, colon, E-Ink). Die Browseruhr
// läuft (install), /api/v1/time antwortet passend dazu. Geprüft: Die Zeit (Text oder Zifferblatt) liegt in der Bühne
// innerhalb des safe-Rands, kein Ziffernumbruch, kein Scrollbalken, data-layout = kit.resolveLayout(Bühne) und bei
// layout=auto auch = --cq-layout aus den @container-Regeln, keine CSP-Verstöße, keine Fehler. Dazu mit angehaltener
// Uhr die Ziffern von studio und face=seg (10:15:42, Kranz bis Sekunde 42), die Akzentfarbe per CSSOM (wirksam,
// ≥ 4,5:1) und die Pixel-Shift-Klasse.
const LAYOUT_DESIGNS = ["?design=digital", "?design=digital&face=seg", "?design=studio", "?design=bahnhof", "?design=nixie",
  "?design=flip", "?design=wort"];
const LAYOUT_PARAMS = ["?layout=tile&safe=10&design=studio", "?layout=tile&design=digital", "?scale=200",
  "?scale=50&design=digital&face=seg", "?shift=2&safe=3&design=digital", "?layout=strip&design=nixie",
  "?layout=banner&design=flip", "?layout=column&design=wort", "?show=time,status&design=digital",
  "?bg=transparent&kiosk=1&design=studio", "?look=paper&accent=ffffff&design=digital&face=mono",
  "?h12=1&lz=0&colon=blink&design=digital&face=seg", "?eink=1&design=studio&date=iso", "?look=terminal&design=studio&seconds=ring&sub=date",
  "?design=studio&scale=200", "?layout=banner&scale=200&design=digital"];

function layoutState() {
  const root = document.documentElement;
  const stage = document.getElementById("clock-stage");
  const main = document.getElementById("clock-main");
  const text = !document.getElementById("local-time").hidden;
  const node = text ? document.getElementById("local-time") : document.getElementById("face");
  const parts = text ? [node] : [...node.children];
  let box = null;
  for (const part of parts) {
    const r = part.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    box = box ? { left: Math.min(box.left, r.left), right: Math.max(box.right, r.right), top: Math.min(box.top, r.top),
      bottom: Math.max(box.bottom, r.bottom) } : { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
  }
  const s = stage.getBoundingClientRect();
  const safe = parseFloat(getComputedStyle(root).getPropertyValue("--safe")) || 0;
  const fontSize = parseFloat(getComputedStyle(document.getElementById("local-time")).fontSize);
  // Banner: Datum und Zeile mit UTC/Zustand (rechte Spalte) – Breite, Schriftgröße und Lage in main.
  const m = main.getBoundingClientRect();
  const info = [...main.querySelectorAll(":scope > .clock-date, :scope > .clock-sub")].map((n) => {
    const r = n.getBoundingClientRect();
    return { cls: n.className, w: r.width, h: r.height, top: r.top, bottom: r.bottom, right: r.right,
      font: parseFloat(getComputedStyle(n).fontSize) };
  }).filter((r) => r.w || r.h);
  return {
    info, mainBox: { top: m.top, bottom: m.bottom, right: m.right },
    layout: stage.dataset.layout || "", mode: root.dataset.layoutMode || "", cq: getComputedStyle(main).getPropertyValue("--cq-layout").trim(),
    stageW: stage.clientWidth, stageH: stage.clientHeight, safe, box,
    safeBox: { left: s.left + s.width * safe / 100, right: s.right - s.width * safe / 100, top: s.top + s.height * safe / 100,
      bottom: s.bottom - s.height * safe / 100 },
    wrapped: text && node.getBoundingClientRect().height > fontSize * 1.6,
    vscroll: root.scrollHeight - root.clientHeight, hscroll: root.scrollWidth - root.clientWidth,
    shift: [...main.classList].filter((c) => c.startsWith("shift-")), transform: getComputedStyle(main).transform,
    csp: window.__csp || [],
  };
}

async function clockLayoutChecks(browser) {
  const found = [];
  const lines = [];
  const timeWidths = {};
  const note = (label, problems) => {
    lines.push(`${label}: ${problems.length ? problems.join("; ") : "ok"}`);
    if (problems.length) found.push(`${label}: ${problems.join("; ")}`);
  };
  for (const [width, height] of STUDIO_VIEWPORTS) {
    const ctx = await browser.newContext({ viewport: { width, height }, timezoneId: "Europe/Berlin" });
    await ctx.addInitScript(() => {
      window.__csp = [];
      document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
      try { localStorage.removeItem("ntp-gui-clock-design"); localStorage.setItem("ntp-gui-clock-red", "0"); } catch (e) { /* egal */ }
    });
    const page = await ctx.newPage();
    const msgs = [];
    page.on("console", (m) => { if (m.type() === "error") msgs.push(m.text()); });
    page.on("pageerror", (e) => msgs.push(`pageerror: ${e.message}`));
    const realStart = Date.now();
    await page.clock.install({ time: CLOCK_SERVER });
    await page.route("**/api/v1/time", (route) => {
      const t = (CLOCK_SERVER + Date.now() - realStart) / 1000;
      return route.fulfill({ json: { t1: t, t2: t, synchronised: true, running: true, level: "good", accuracy: 0.0004,
        stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS", source: null, public: true } });
    });
    for (const query of [...LAYOUT_DESIGNS, ...LAYOUT_PARAMS]) {
      msgs.length = 0;
      await page.goto(`${BASE}/clock${query}`, { waitUntil: "load" });
      await page.waitForTimeout(450);
      const got = await page.evaluate(layoutState);
      const want = await page.evaluate(([w, h]) => import("/static/js/clockkit.js").then((k) => k.resolveLayout(w, h)),
        [got.stageW, got.stageH]);
      const problems = [];
      if (got.mode === "auto" && got.layout !== want) problems.push(`data-layout ${got.layout} statt ${want}`);
      if (got.mode === "auto" && got.cq !== got.layout) problems.push(`CSS-Spiegel ${got.cq} ≠ data-layout ${got.layout}`);
      if (got.mode !== "auto" && got.layout !== got.mode) problems.push(`layout=${got.mode}, data-layout ${got.layout}`);
      if (!got.box) problems.push("Zeit nicht sichtbar");
      else {
        const b = got.box;
        const z = got.safeBox;
        if (b.left < z.left - 1 || b.right > z.right + 1 || b.top < z.top - 1 || b.bottom > z.bottom + 1) {
          problems.push(`Zeit außerhalb des safe-Rands ${got.safe} % (${[b.left, b.top, b.right, b.bottom].map(Math.round)} in `
            + `${[z.left, z.top, z.right, z.bottom].map(Math.round)})`);
        }
      }
      if (got.wrapped) problems.push("Ziffernumbruch");
      if (got.vscroll > 0 || got.hscroll > 0) problems.push(`Scrollbalken (${got.hscroll}/${got.vscroll} px)`);
      if (got.csp.length || msgs.length) problems.push(`Fehler ${JSON.stringify([...got.csp, ...msgs])}`);
      // Banner: Die rechte Spalte bleibt lesbar (mindestens vier Zeichen breit) und ganz in main.
      if (got.layout === "banner") {
        for (const r of got.info) {
          const mb = got.mainBox;
          if (r.w < r.font * 4) problems.push(`${r.cls} nur ${Math.round(r.w)} px breit`);
          if (r.top < mb.top - 1 || r.bottom > mb.bottom + 1 || r.right > mb.right + 1) {
            problems.push(`${r.cls} außerhalb von main (${[r.top, r.bottom, r.right].map(Math.round)} in ${[mb.top, mb.bottom, mb.right].map(Math.round)})`);
          }
        }
      }
      if (query === "?design=digital" && got.box) timeWidths[`${width}×${height}`] = got.box.right - got.box.left;
      note(`/clock Layout ${width}×${height} ${query} [${got.layout}]`, problems);
    }
    await ctx.close();
  }

  // Ziffern mit angehaltener Uhr (10:15:42): studio (Kranz bis Sekunde 42, Zeile UTC) und digital face=seg.
  for (const [query, check] of [
    ["?design=studio", (g) => [g.digits === "d-1 d-0 d-1 d-5" ? "" : `HH:MM ${g.digits}`, g.secs === "d-4 d-2" ? "" : `SS ${g.secs}`,
      g.lit === 43 ? "" : `Kranz ${g.lit} Punkte`, g.dots === 60 && g.marks === 12 ? "" : `Kranz ${g.dots}/${g.marks}`,
      g.sub === "UTC 08:15" ? "" : `Zeile „${g.sub}“`, g.shift.length === 1 ? "" : `Pixel-Shift ${g.shift}`]],
    ["?design=digital&face=seg", (g) => [g.row === "d-1 d-0 d-1 d-5 d-4 d-2" ? "" : `Ziffern ${g.row}`,
      g.textHidden ? "" : "Textzeit sichtbar"]],
    ["?look=paper&accent=ffffff", (g) => [g.contrast >= 4.5 ? "" : `Akzent ${g.accent} nur ${g.contrast.toFixed(2)}:1`,
      g.accent && g.accent !== "#ffffff" && g.computed === g.accent ? "" : `Akzent nicht wirksam (${g.accent}/${g.computed})`]],
    ["?shift=2", (g) => [g.shift.length === 1 && g.shift[0] === `shift-${g.wantShift}` ? "" : `Pixel-Shift ${g.shift} statt shift-${g.wantShift}`]],
  ]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 1080, query });
    const got = await page.evaluate(async () => {
      const k = await import("/static/js/clockkit.js");
      const cls = (list) => [...list].map((n) => n.getAttribute("class").replace("seg7 ", "").replace(" is-sec", "")).join(" ");
      const studio = document.querySelector(".face-studio .st");
      const lum = (hex) => k.luminance(hex);
      const toHex = (rgb) => `#${rgb.match(/\d+/g).slice(0, 3).map((v) => Number(v).toString(16).padStart(2, "0")).join("")}`;
      const accent = document.documentElement.style.getPropertyValue("--accent").trim();
      const bg = toHex(getComputedStyle(document.body).backgroundColor);
      const egg = document.getElementById("leap-egg");   // Rahmen in --accent (am 30.6. sichtbar)
      return {
        digits: studio ? cls(studio.querySelectorAll(":scope > use")) : "",
        secs: studio ? cls(studio.querySelectorAll(".st-secs use")) : "",
        lit: studio ? studio.querySelectorAll(".st-dot.on").length : 0,
        dots: studio ? studio.querySelectorAll(".st-dot").length : 0, marks: studio ? studio.querySelectorAll(".st-mark").length : 0,
        sub: studio ? studio.querySelector(".st-sub").textContent : "",
        row: cls(document.querySelectorAll(".face-seg .seg-row use")),
        textHidden: document.getElementById("local-time").hidden,
        accent, computed: toHex(getComputedStyle(egg).borderTopColor), contrast: accent ? k.contrastRatio(accent, bg) : 0, lumBg: lum(bg),
        shift: [...document.getElementById("clock-main").classList].filter((c) => c.startsWith("shift-")),
        wantShift: k.shiftIndex(Date.parse("2026-06-30T08:15:42.500Z")),
        csp: window.__csp || [],
      };
    });
    await ctx.close();
    const problems = check(got).filter(Boolean);
    if (got.csp.length || msgs.length) problems.push(`Fehler ${JSON.stringify([...got.csp, ...msgs])}`);
    note(`/clock Ziffern/Farbe ${query}`, problems);
  }
  // 4K bekommt die Fläche des Bildschirms, nicht die Seitenbreite aus app.css: Zeit gut doppelt so breit wie bei 1080p.
  const grow = timeWidths["3840×2160"] / timeWidths["1920×1080"];
  note(`/clock Zeitbreite 3840×2160 / 1920×1080 = ${grow.toFixed(2)}`, grow >= 1.8 ? [] : ["unter 1,8"]);
  const extra = await clockFitChecks(browser);
  found.push(...extra.found);
  lines.push(...extra.lines);
  return { found, lines };
}

// Studiouhr A5 (clockCountdownChecks): Countdown und Count-up aus docs/konzept/studiouhr.md (Akzeptanz A). Mit
// angehaltener Playwright-Uhr (Serverzeit 10:15:42,5 in Europe/Berlin, die Browseruhr 5 min daneben) und gemocktem
// /api/v1/time samt Zeitzone des Servers. Je Fläche: Countdown unter der Uhr (−04:18, gelb mit △ und „unter 5 min“),
// Countdown als Hauptanzeige in den letzten 10 s (−00:08, fett rot mit ■) und Überzeit (+00:00:42 mit „Überzeit“) –
// richtig gerechnet nach der Serverzeit, nicht nach der Browseruhr; Countdown ganz im Bild, im safe-Rand, ohne
// Umbruch, ohne Scrollbalken, ohne CSP-Verstöße. Dazu bei 1920×1080: after=stop, abweichende Zone des Servers,
// E-Ink (nur Minuten), Timer per Leertaste/R, Stoppuhr mit Zehnteln (T), Tastenkürzel D, L, U, +, ?, lock=1 und die
// Ansage beim Unterschreiten von 1 min.
function countdownState() {
  const root = document.documentElement;
  const node = document.getElementById("cd");
  const time = document.getElementById("cd-time");
  const stage = document.getElementById("clock-stage").getBoundingClientRect();
  const safe = parseFloat(getComputedStyle(root).getPropertyValue("--safe")) || 0;
  const box = time.getBoundingClientRect();
  const all = node.getBoundingClientRect();
  const size = parseFloat(getComputedStyle(time).fontSize);
  return {
    hidden: node.hidden, display: getComputedStyle(node).display, level: node.dataset.level, phase: node.dataset.phase,
    text: time.textContent, icon: document.getElementById("cd-icon").textContent,
    label: document.getElementById("cd-label").textContent, state: document.getElementById("cd-state").textContent,
    color: getComputedStyle(time).color, weight: getComputedStyle(time).fontWeight, ink: getComputedStyle(document.body).color,
    cdAttr: root.dataset.cd || "", clockShown: getComputedStyle(document.getElementById("local-time")).display !== "none"
      && !document.getElementById("local-time").hidden,
    time: document.getElementById("local-time").textContent, size, wrapped: box.height > size * 1.6,
    box: { left: all.left, right: all.right, top: all.top, bottom: all.bottom, w: box.width, h: box.height },
    safeBox: { left: stage.left + stage.width * safe / 100, right: stage.right - stage.width * safe / 100,
      top: stage.top + stage.height * safe / 100, bottom: stage.bottom - stage.height * safe / 100 },
    innerWidth: window.innerWidth, innerHeight: window.innerHeight,
    vscroll: root.scrollHeight - root.clientHeight, hscroll: root.scrollWidth - root.clientWidth,
    design: root.dataset.design, layoutMode: root.dataset.layoutMode, scale: root.style.getPropertyValue("--clock-scale"),
    keys: !document.getElementById("keys").hidden, live: document.getElementById("clock-live").textContent,
    localLabel: document.getElementById("local-label").textContent, utcLabel: document.getElementById("utc-label").textContent,
    utcTime: document.getElementById("utc-time").textContent, csp: window.__csp || [],
    layout: document.getElementById("clock-stage").dataset.layout,
    ...Object.fromEntries(["cd-label", "cd-state", "cd-now"].map((id) => {
      const el = document.getElementById(id);
      const r = el.getBoundingClientRect();
      const shown = getComputedStyle(el).display !== "none" && r.width > 0 && r.height > 0;
      return [id, { shown, size: parseFloat(getComputedStyle(el).fontSize), text: el.textContent }];
    })),
    active: document.activeElement ? (document.activeElement.id || document.activeElement.tagName) : "",
    modal: document.getElementById("keys").getAttribute("aria-modal"),
  };
}

async function clockCountdownChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    lines.push(`${label}: ${problems.length ? problems.join("; ") : "ok"}`);
    if (problems.length) found.push(`${label}: ${problems.join("; ")}`);
  };
  const reply = (zone) => (ms) => ({ t1: ms / 1000, t2: ms / 1000, synchronised: true, running: true, level: "good",
    accuracy: 0.0004, stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS", source: null, public: true, zone });
  const M = "−";
  const errors = (got, msgs) => (got.csp.length || msgs.length ? [`Fehler ${JSON.stringify([...got.csp, ...msgs])}`] : []);
  const placement = (got) => {
    const out = [];
    const b = got.box;
    const z = got.safeBox;
    if (!(b.w > 0 && b.h > 0)) out.push("Countdown nicht sichtbar");
    else if (b.left < z.left - 1 || b.right > z.right + 1 || b.top < z.top - 1 || b.bottom > z.bottom + 1) {
      out.push(`Countdown außerhalb der Bühne (${[b.left, b.top, b.right, b.bottom].map(Math.round)} in ${[z.left, z.top, z.right, z.bottom].map(Math.round)})`);
    }
    if (got.wrapped) out.push("Umbruch im Countdown");
    if (got.vscroll > 0 || got.hscroll > 0) out.push(`Scrollbalken (${got.hscroll}/${got.vscroll} px)`);
    return out;
  };
  const CASES = {
    // 10:15:42,5 → 10:20: noch 4:17,5 → aufgerundet −04:18, Stufe gelb (≤ 300 s).
    below: { query: "?until=10:20", want: { text: `${M}04:18`, level: "warn", icon: "△", state: "unter 5 min", label: "bis 10:20",
      cd: "below", clock: true } },
    // Letzte 10 s als Hauptanzeige: fett rot, Uhrzeit tritt zurück.
    main: { query: "?until=10:15:50&cd=main&design=studio", want: { text: `${M}00:08`, level: "final", icon: "■", state: "unter 10 s",
      label: "bis 10:15:50", cd: "main", clock: false } },
    // Überzeit seit 10:15 mit eigener Beschriftung.
    over: { query: "?until=10:15&label=ON%20AIR&design=digital&face=seg", want: { text: "+00:00:42", level: "over", icon: "+",
      state: "Überzeit", label: "ON AIR", cd: "below", clock: false } },
  };
  for (const [width, height] of STUDIO_VIEWPORTS) {
    for (const [name, spec] of Object.entries(CASES)) {
      const { ctx, page, msgs } = await openPausedClock(browser, { width, height, query: spec.query, reply: reply("Europe/Berlin") });
      const got = await page.evaluate(countdownState);
      await ctx.close();
      const w = spec.want;
      const problems = [];
      if (got.hidden || got.display === "none") problems.push("Countdown fehlt");
      for (const key of ["text", "level", "icon", "state", "label"]) if (got[key] !== w[key]) problems.push(`${key} „${got[key]}“ statt „${w[key]}“`);
      if (got.cdAttr !== w.cd) problems.push(`data-cd ${got.cdAttr}`);
      if (name === "main" && got.clockShown) problems.push("Uhrzeit trotz cd=main groß");
      // cd=main: Die Uhrzeit steht klein beim Countdown – auf jeder Fläche außer Streifen und Kachel (auch im Banner).
      const small = !["strip", "tile"].includes(got.layout);
      if (name === "main" && small && !(got["cd-now"].shown && /^10:15:4\d$/.test(got["cd-now"].text))) {
        problems.push(`Uhrzeit bei cd=main nicht sichtbar (${got.layout}, „${got["cd-now"].text}“)`);
      }
      // Beschriftung und Stufentext tragen die Bedeutung neben der Farbe: lesbar groß (≥ 12 px, Uhrzeit ≥ 13 px).
      if (small) {
        for (const [id, floor] of [["cd-label", 12], ["cd-state", 12], ["cd-now", 13]]) {
          if (got[id].shown && got[id].size < floor - 0.05) problems.push(`${id} nur ${got[id].size.toFixed(1)} px`);
        }
      }
      if (name === "below" && got.time !== "10:15:42") problems.push(`Uhrzeit ${got.time}`);
      if (w.level !== "none" && got.color === got.ink) problems.push(`Stufe ${w.level} ohne eigene Farbe`);
      if (w.level === "final" && Number(got.weight) < 800) problems.push(`letzte Sekunden nicht fett (${got.weight})`);
      problems.push(...placement(got), ...errors(got, msgs));
      note(`/clock Countdown ${width}×${height} ${name}`, problems);
    }
  }

  // Einzelfälle bei 1920×1080.
  const single = async (query, zone, act) => {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, query, reply: reply(zone) });
    const out = await act(page, clock);
    const got = await page.evaluate(countdownState);
    await ctx.close();
    return { got, msgs, out };
  };
  {
    const { got, msgs } = await single("?until=10:15&after=stop", "Europe/Berlin", async () => null);
    note("/clock Countdown after=stop", [got.text === "00:00" && got.level === "done" && got.state === "Zeit abgelaufen" ? ""
      : `${got.text} ${got.level} „${got.state}“`, ...errors(got, msgs)].filter(Boolean));
  }
  {
    // Server in New York (04:15:42): Ziel 06:20 dort, also −02:04:18 – die Zeitzone des Browsers (Berlin) zählt nicht.
    const { got, msgs } = await single("?until=06:20", "America/New_York", async () => null);
    note("/clock Countdown Zone des Servers", [got.text === `${M}02:04:18` ? "" : `zeigt ${got.text}`,
      /New York/.test(got.label) ? "" : `Beschriftung „${got.label}“`, got.level === "none" ? "" : `Stufe ${got.level}`,
      ...errors(got, msgs)].filter(Boolean));
  }
  {
    const { got, msgs } = await single("?until=10:20&eink=1", "Europe/Berlin", async () => null);
    note("/clock Countdown E-Ink", [got.text === `${M}00:05` ? "" : `zeigt ${got.text} (nur Minuten erwartet)`, ...errors(got, msgs)]
      .filter(Boolean));
  }
  {
    // Timer: bereit → Leertaste → 2,5 s → angehalten → R.
    const { got, msgs, out } = await single("?timer=90s&beep=5", "Europe/Berlin", async (page, clock) => {
      const steps = [await page.evaluate(countdownState)];
      await page.keyboard.press("Space");
      await clock.run(2500);
      steps.push(await page.evaluate(countdownState));
      await page.keyboard.press("Space");
      await clock.run(3000);
      steps.push(await page.evaluate(countdownState));
      await page.keyboard.press("r");
      await clock.run(250);
      return steps;
    });
    const [idle, running, paused] = out;
    note("/clock Timer", [
      idle.text === `${M}01:30` && /Leertaste/.test(idle.state) ? "" : `bereit: ${idle.text} „${idle.state}“`,
      running.text === `${M}01:28` && running.state === "unter 5 min" && running.level === "warn" ? ""
        : `läuft: ${running.text} „${running.state}“`,
      paused.text === `${M}01:28` && paused.state === "angehalten" && paused.icon === "‖" ? "" : `angehalten: ${paused.text} „${paused.state}“`,
      got.text === `${M}01:30` ? "" : `zurückgesetzt: ${got.text}`, ...errors(got, msgs)].filter(Boolean));
  }
  {
    // Stoppuhr: ohne Ziel startet die Leertaste sie, T zeigt Zehntel, R lässt sie verschwinden.
    const { got, msgs, out } = await single("", "Europe/Berlin", async (page, clock) => {
      const steps = [await page.evaluate(countdownState)];
      await page.keyboard.press("Space");
      await clock.run(3100);   // der eigene Takt der Stoppuhr wechselt 2 ms nach der vollen Sekunde
      steps.push(await page.evaluate(countdownState));
      await page.keyboard.press("t");
      await clock.run(250);
      steps.push(await page.evaluate(countdownState));
      await page.keyboard.press("r");
      await clock.run(250);
      return steps;
    });
    const [before, running, tenths] = out;
    note("/clock Stoppuhr", [before.hidden ? "" : "Stoppuhr vor dem Start sichtbar",
      running.text === "00:03" && running.label === "Stoppuhr" ? "" : `läuft: ${running.text} „${running.label}“`,
      /^00:03,[0-9]$/.test(tenths.text) ? "" : `Zehntel: ${tenths.text}`, got.hidden ? "" : "nach R noch sichtbar",
      ...errors(got, msgs)].filter(Boolean));
  }
  {
    // Tastenkürzel: D (Design), L (Layout), U (UTC groß), + (Größe), ? (Übersicht), Esc.
    const { got, msgs, out } = await single("", "Europe/Berlin", async (page, clock) => {
      const steps = {};
      await page.keyboard.press("d");
      await page.keyboard.press("l");
      await page.keyboard.press("u");
      await page.keyboard.press("+");
      await clock.run(250);
      steps.after = await page.evaluate(countdownState);
      await page.keyboard.press("?");
      steps.keys = await page.evaluate(countdownState);
      await page.keyboard.press("Escape");
      await page.keyboard.press("a");
      await clock.run(500);
      return steps;
    });
    const a = out.after;
    note("/clock Tastenkürzel", [a.design === "studio" ? "" : `D: Design ${a.design}`, a.layoutMode === "normal" ? "" : `L: ${a.layoutMode}`,
      a.localLabel === "UTC" && a.utcLabel === "Ortszeit" && /^10:15:4\d$/.test(a.utcTime) ? "" : `U: ${a.localLabel}/${a.utcLabel} ${a.utcTime}`,
      a.scale === "1.1" ? "" : `+: --clock-scale ${a.scale}`, out.keys.keys ? "" : "?: Übersicht fehlt",
      got.keys ? "Esc schließt die Übersicht nicht" : "", /^UTC 08:15$/.test(got.live) ? "" : `A: Ansage „${got.live}“`,
      ...errors(got, msgs)].filter(Boolean));
  }
  {
    // lock=1: keine Kürzel – weder Design noch Stoppuhr noch Übersicht.
    const { got, msgs } = await single("?lock=1", "Europe/Berlin", async (page, clock) => {
      for (const key of ["d", "Space", "?", "l"]) await page.keyboard.press(key);
      await clock.run(250);
    });
    note("/clock lock=1", [got.design === "digital" && got.hidden && !got.keys && got.layoutMode === "auto" ? ""
      : `Kürzel wirken: ${got.design} ${got.hidden} ${got.keys} ${got.layoutMode}`, ...errors(got, msgs)].filter(Boolean));
  }
  {
    // lock=1 mit Timer: kein Start möglich, also auch keine Bedienung versprechen.
    const { got, msgs } = await single("?timer=90s&lock=1", "Europe/Berlin", async (page, clock) => {
      await page.keyboard.press("Space");
      await clock.run(1500);
    });
    note("/clock Timer lock=1", [got.text === `${M}01:30` ? "" : `Timer läuft trotz lock=1 (${got.text})`,
      got.state === "bereit – Bedienung gesperrt (lock=1)" ? "" : `Zustand „${got.state}“`, ...errors(got, msgs)].filter(Boolean));
  }
  {
    // Kürzel-Übersicht als Dialog: Fokus hinein, Tab bleibt drin, Esc schließt und gibt den Fokus zurück.
    const { got, msgs, out } = await single("", "Europe/Berlin", async (page, clock) => {
      await page.keyboard.press("?");
      const open = await page.evaluate(countdownState);
      await page.keyboard.press("Tab");
      const tab = await page.evaluate(countdownState);
      await page.keyboard.press("Escape");
      await clock.run(250);
      return { open, tab };
    });
    note("/clock Kürzel-Übersicht Fokus", [out.open.modal === "true" ? "" : "aria-modal fehlt",
      out.open.active === "keys-close" ? "" : `Fokus beim Öffnen auf ${out.open.active}`,
      out.tab.active === "keys-close" ? "" : `Tab verlässt den Dialog (${out.tab.active})`,
      !got.keys && got.active === "clock-main" ? "" : `nach Esc Fokus auf ${got.active} (offen: ${got.keys})`,
      ...errors(got, msgs)].filter(Boolean));
  }
  {
    // Erste Antwort von /api/v1/time verzögert, Browser in UTC, Server in Berlin: Bis die Zone des Servers da ist, zeigt
    // ?until= nichts (kein Countdown in der Zone des Browsers), danach die richtige Restzeit ohne Ansage einer Schwelle.
    let release;
    const hold = new Promise((resolve) => { release = resolve; });
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, query: "?until=10:16:12",
      reply: reply("Europe/Berlin"), hold, settle: false, zone: "UTC" });
    await page.waitForTimeout(200);
    const early = await page.evaluate(countdownState);
    release();
    await clock.run(CLOCK_SETTLE_MS + 1000);
    const got = await page.evaluate(countdownState);
    await ctx.close();
    note("/clock Countdown vor der ersten Antwort", [early.text === "--:--" && early.level === "none" ? ""
      : `vor der Antwort ${early.text} (${early.level})`, /^−00:2\d$/.test(got.text) ? "" : `danach ${got.text}`,
      got.live === "" ? "" : `Ansage „${got.live}“ ohne erlebten Übergang`, ...errors(got, msgs)].filter(Boolean));
  }
  {
    // Ansage beim Unterschreiten von 1 min (Screenreader), nicht jede Sekunde.
    const { got, msgs, out } = await single("?until=10:16:44", "Europe/Berlin", async (page, clock) => {
      const first = await page.evaluate(countdownState);
      await clock.run(2000);
      return first;
    });
    note("/clock Countdown-Ansage", [out.live === "" ? "" : `schon beim Laden „${out.live}“`,
      got.live === "Noch 1 min." ? "" : `Ansage „${got.live}“ (${got.text})`, ...errors(got, msgs)].filter(Boolean));
  }
  return { found, lines };
}

// Nachbesserungen der Layout-Engine: ?bg=black mit gespeichertem hellem Thema (Schrift ≥ 4,5:1 auf Schwarz, Schema
// dunkel, Hell/Dunkel-Knopf gesperrt), Screenreader-Text bei ?h12=1 (Zifferblatt „10:15 AM“, Textzeit mit Leerzeichen
// vor AM), automatischer Streifen in sehr niedrigen Fenstern ohne Kopfzeile und Band (die Zeit bekommt die ganze Höhe).
// Studiouhr A6 (clockLinkChecks): Profile und Link-Baukasten. /clock?p=regie mit gemocktem Profil auf allen neun Flächen
// (Profilwerte wirken, Adresse schlägt Profil, Titel in der Kopfzeile, keine Überbreite, keine CSP-Verstöße); ein neues
// profiles_rev lädt die Seite mit dem geänderten Profil neu, ein unverändertes Profil nicht. Panel „Anpassen“: Formular
// aus dem Schema, Übernehmen merkt den Stand für /clock ohne Parameter, Zurücksetzen löscht ihn, lock=1 blendet es aus.
// Reiter „Anzeigen“ bei 390 und 1440 px: Link folgt dem Formular, Vorschau per window.open mit fester Größe (kein iframe),
// Profil speichern und löschen über die Einstellungen-API, Hinweis „Uhr ohne Anmeldung“.
// Nachbesserung: Profilabruf scheitert erst (Neuversuch, Standarduhr statt gemerktem Stand), Voreinstellung auf Englisch,
// Rotlicht mit offenem Panel (keine hellen Flächen, Kästchen dunkel, Fehlertitel rot, kein kiosk/lock im Panel), im
// Dashboard bleibt die geladene Vorlage in der Auswahl stehen und der Schalter „ohne Anmeldung“ hat kein aria-pressed.
async function clockLinkChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    lines.push(`${label}: ${problems.length ? problems.join("; ") : "ok"}`);
    if (problems.length) found.push(`${label}: ${problems.join("; ")}`);
  };
  const errors = (got, msgs) => (got.csp.length || msgs.length ? [`Fehler ${JSON.stringify([...got.csp, ...msgs])}`] : []);
  const rev = { value: "rev-a" };
  const profiles = {
    regie: { name: "regie", title: "Regie 1", params: { design: "studio", look: "studio", kiosk: "0", until: "10:20" }, builtin: false },
  };
  const profile = (name) => (profiles[name] ? { ...profiles[name], profiles_rev: rev.value } : null);
  const reply = (ms) => ({ t1: ms / 1000, t2: ms / 1000, synchronised: true, running: true, level: "good", accuracy: 0.0004,
    stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS", source: null, public: true, zone: "Europe/Berlin",
    profiles_rev: rev.value });
  const linkState = () => ({
    design: document.documentElement.dataset.design || "", look: document.documentElement.dataset.look || "",
    layout: document.documentElement.dataset.layoutMode || "",
    title: document.getElementById("clock-title").hidden ? null : document.getElementById("clock-title").textContent,
    titleBox: (() => { const r = document.getElementById("clock-title").getBoundingClientRect(); return { right: r.right, w: r.width }; })(),
    cd: !document.getElementById("cd").hidden, cdText: document.getElementById("cd-time").textContent,
    customShown: !document.getElementById("mode-custom").hidden && getComputedStyle(document.getElementById("mode-custom")).display !== "none",
    doc: document.title, marker: window.__marker || null,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    csp: window.__csp || [],
  });

  // Profil auf allen Flächen.
  for (const [width, height] of STUDIO_VIEWPORTS) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width, height, query: "?p=regie", reply, profile });
    const got = await page.evaluate(linkState);
    await ctx.close();
    const problems = [];
    if (got.design !== "studio" || got.look !== "studio") problems.push(`Profil nicht angewendet (${got.design}/${got.look})`);
    if (!got.cd || got.cdText !== "−04:18") problems.push(`Countdown aus dem Profil „${got.cdText}“`);
    if (!/^Regie 1 · /.test(got.doc)) problems.push(`Fenstertitel „${got.doc}“`);
    if (got.overflow > 0) problems.push(`Überbreite ${got.overflow} px`);
    if (got.titleBox.right > width + 1) problems.push(`Titel ragt hinaus (${Math.round(got.titleBox.right)} px)`);
    problems.push(...errors(got, msgs));
    note(`/clock?p=regie ${width}×${height}`, problems);
  }
  {
    // Adresse schlägt Profil; unbekanntes Profil: Hinweis statt Fehler, Standarduhr.
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1440, query: "?p=regie&design=nixie", reply, profile });
    const got = await page.evaluate(linkState);
    await ctx.close();
    note("/clock?p=regie&design=nixie", [got.design === "nixie" && got.look === "studio" ? "" : `${got.design}/${got.look}`,
      got.title === "Regie 1" ? "" : `Titel „${got.title}“`, ...errors(got, msgs)].filter(Boolean));
  }
  {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 390, query: "?p=fehlt", reply, profile });
    const got = await page.evaluate(linkState);
    await ctx.close();
    const msgs404 = msgs.filter((m) => !/404/.test(m));
    note("/clock?p=fehlt", [got.design === "digital" ? "" : `Design ${got.design}`,
      /fehlt/.test(got.title || "") ? "" : `kein Hinweis („${got.title}“)`, ...errors(got, msgs404)].filter(Boolean));
  }
  {
    // profiles_rev ändert sich: erst ohne Änderung am eigenen Profil (kein Neuladen), dann mit (Neuladen, neues Design).
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1440, query: "?p=regie", reply, profile });
    await page.evaluate(() => { window.__marker = "vorher"; });
    rev.value = "rev-b";
    await clock.run(6000);
    const same = await page.evaluate(linkState);
    profiles.regie = { ...profiles.regie, title: "Regie 2", params: { ...profiles.regie.params, design: "bahnhof" } };
    rev.value = "rev-c";
    const reloaded = page.waitForEvent("load", { timeout: 15000 }).catch(() => null);
    await clock.run(6000);
    await reloaded;
    await page.waitForTimeout(400);
    await clock.run(1500);
    const after = await page.evaluate(linkState);
    await ctx.close();
    note("/clock profiles_rev", [same.marker === "vorher" ? "" : "neu geladen, obwohl das Profil gleich blieb",
      after.marker === null ? "" : "nicht neu geladen", after.design === "bahnhof" ? "" : `Design nach Neuladen ${after.design}`,
      after.title === "Regie 2" ? "" : `Titel „${after.title}“`, ...errors(after, msgs)].filter(Boolean));
    profiles.regie = { ...profiles.regie, title: "Regie 1", params: { ...profiles.regie.params, design: "studio" } };
    rev.value = "rev-a";
  }

  // Panel „Anpassen“: Formular, Übernehmen (gilt ohne Parameter), Zurücksetzen; lock=1 blendet es aus.
  for (const width of [390, 1440]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, reply });
    const problems = [];
    await page.click("#mode-custom");
    await page.waitForTimeout(150);
    const form = await page.evaluate(() => ({
      fields: document.querySelectorAll("#custom-form .link-field").length,
      open: !document.getElementById("custom-panel").hidden,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      small: [...document.querySelectorAll("#custom-panel select, #custom-panel input, #custom-panel button")]
        .map((n) => n.getBoundingClientRect()).filter((r) => r.width && (r.height < 24 || r.width < 18)).length,
    }));
    if (!form.open || form.fields < 28) problems.push(`Formular ${form.fields} Felder, offen ${form.open}`);
    if (form.overflow > 0) problems.push(`Überbreite mit Panel ${form.overflow} px`);
    if (form.small) problems.push(`${form.small} Bedienelemente zu klein`);
    // Kachel sperrte Leiste und „Anpassen“ aus: im Panel nicht angeboten.
    const layouts = await page.evaluate(() => [...document.querySelectorAll("#custom-layout option")].map((o) => o.value));
    if (layouts.includes("tile") || !layouts.includes("banner")) problems.push(`Layout-Auswahl ${JSON.stringify(layouts)}`);
    await page.selectOption("#custom-design", "nixie");
    await page.fill("#custom-scale", "120");
    await Promise.all([page.waitForEvent("load"), page.click("#custom-apply")]);
    await page.waitForTimeout(300);
    await clock.run(1500);
    const applied = await page.evaluate(() => ({ url: location.search, design: document.documentElement.dataset.design,
      stored: localStorage.getItem("ntp-gui-clock-custom") }));
    if (applied.url !== "" || applied.design !== "nixie" || applied.stored !== "design=nixie&scale=120") {
      problems.push(`Übernehmen ${JSON.stringify(applied)}`);
    }
    // Taste D wählt ein anderes Design: Es gilt auch nach dem Neuladen (gemerkter Stand passt sich an).
    await page.keyboard.press("d");
    await clock.run(250);
    const picked = await page.evaluate(() => document.documentElement.dataset.design);
    await page.reload({ waitUntil: "load" });
    await clock.run(1500);
    const kept = await page.evaluate(() => ({ design: document.documentElement.dataset.design,
      stored: localStorage.getItem("ntp-gui-clock-custom") }));
    if (picked === "nixie" || kept.design !== picked || kept.stored !== `design=${picked}&scale=120`) {
      problems.push(`Design aus Taste D nach Neuladen ${JSON.stringify({ picked, ...kept })}`);
    }
    await page.goto(`${BASE}/clock?design=wort`, { waitUntil: "load" });
    await clock.run(1500);
    const url = await page.evaluate(() => document.documentElement.dataset.design);
    if (url !== "wort") problems.push(`Adresse schlägt den gemerkten Stand nicht (${url})`);
    // Taste D auf einer Adresse mit Parametern: Der gemerkte Stand gilt hier nicht und bleibt unberührt.
    await page.keyboard.press("d");
    await clock.run(250);
    const foreign = await page.evaluate(() => localStorage.getItem("ntp-gui-clock-custom"));
    if (foreign !== `design=${picked}&scale=120`) problems.push(`Taste D auf ?design= ändert den gemerkten Stand (${foreign})`);
    await page.goto(`${BASE}/clock`, { waitUntil: "load" });
    await clock.run(1500);
    await page.click("#mode-custom");
    await Promise.all([page.waitForEvent("load"), page.click("#custom-reset")]);
    await clock.run(1500);
    const reset = await page.evaluate(() => ({ design: document.documentElement.dataset.design,
      stored: localStorage.getItem("ntp-gui-clock-custom"), csp: window.__csp || [] }));
    if (reset.stored !== null || reset.design !== "digital") problems.push(`Zurücksetzen ${JSON.stringify(reset)}`);
    problems.push(...errors(reset, msgs));
    await ctx.close();
    note(`/clock Anpassen ${width}`, problems);
  }
  {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1440, query: "?lock=1", reply });
    const got = await page.evaluate(linkState);
    const tools = await page.evaluate(() => [...document.querySelectorAll(".clock-tools > *")]
      .filter((n) => getComputedStyle(n).display !== "none" && !n.hidden).map((n) => n.id || n.className));
    const fullTitle = await page.evaluate(() => document.getElementById("mode-full").title);
    await ctx.close();
    // Gesperrt: kein Design, Ton, Anpassen; Hell/Dunkel und Rotlicht bleiben schaltbar (kein Adressparameter).
    const want = "mode-theme,mode-red,mode-device,mode-full";
    note("/clock?lock=1 Anpassen", [got.customShown ? "Anpassen trotz lock=1 sichtbar" : "",
      tools.join(",") === want ? "" : `Bedienknöpfe mit lock=1: ${tools.join(", ")}`,
      /\bF\b/.test(fullTitle) ? `Vollbild verspricht Taste F trotz lock=1 (${fullTitle})` : "",
      ...errors(got, msgs)].filter(Boolean));
  }

  {
    // Profilabruf scheitert beim Start (503): Standarduhr statt des gemerkten Panel-Stands, Neuversuch mit Abstand,
    // nach dem ersten Erfolg lädt die Seite mit dem Profil neu – ohne dass sich profiles_rev ändert.
    const flaky = { fail: true };
    const flakyProfile = (name) => (flaky.fail ? "fail" : profile(name));
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1440, query: "?p=regie", reply,
      profile: flakyProfile, storage: { "ntp-gui-clock-custom": "design=flip&kiosk=1&lock=1" } });
    const before = await page.evaluate(linkState);
    const hitsFailed = clock.profileHits || 0;
    await clock.run(6000);
    const hitsRetry = clock.profileHits || 0;
    await page.evaluate(() => { window.__marker = "vorher"; });
    flaky.fail = false;
    const reloaded = page.waitForEvent("load", { timeout: 20000 }).catch(() => null);
    await clock.run(12000);
    await reloaded;
    await page.waitForTimeout(400);
    await clock.run(1500);
    const after = await page.evaluate(linkState);
    const kiosk = await page.evaluate(() => document.body.classList.contains("is-kiosk"));
    await ctx.close();
    const rest = msgs.filter((m) => !/503/.test(m));
    note("/clock?p=regie Abruf scheitert erst", [
      before.design === "digital" ? "" : `ohne Profil Design ${before.design} (gemerkter Stand?)`,
      /nicht geladen/.test(before.title || "") ? "" : `kein Fehlerhinweis („${before.title}“)`,
      hitsRetry > hitsFailed ? "" : "kein erneuter Abruf",
      after.marker === null ? "" : "nach erfolgreichem Abruf nicht neu geladen",
      after.design === "studio" && after.title === "Regie 1" ? "" : `nach Neuversuch ${after.design}/„${after.title}“`,
      kiosk ? "Kiosk aus dem gemerkten Stand aktiv" : "", ...errors(after, rest)].filter(Boolean));
  }
  {
    // Feste Voreinstellung auf Englisch: Titel übersetzt (Kopfzeile und Fenstertitel).
    const presets = { kitchen: { name: "kitchen", title: "Küche", params: { design: "flip", look: "warm" }, builtin: true } };
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1440, query: "?p=kitchen", reply,
      profile: (name) => (presets[name] ? { ...presets[name], profiles_rev: rev.value } : null),
      storage: { "ntp-gui-lang": "en" } });
    await page.waitForTimeout(300);
    const got = await page.evaluate(linkState);
    await page.click("#mode-custom");
    await page.waitForTimeout(150);
    const panel = await page.evaluate(() => ({
      label: document.getElementById("custom-label")?.placeholder || "",
      show: [...document.querySelectorAll("#custom-show .link-check span")].map((n) => n.textContent),
    }));
    await ctx.close();
    note("/clock?p=kitchen englisch", [got.title === "Kitchen (timer)" ? "" : `Titel „${got.title}“`,
      /^Kitchen \(timer\) · /.test(got.doc) ? "" : `Fenstertitel „${got.doc}“`,
      panel.label === "until ON AIR" ? "" : `Platzhalter „${panel.label}“`,
      panel.show[0] === "Time" ? "" : `Beschriftung show ${JSON.stringify(panel.show.slice(0, 3))}`,
      ...errors(got, msgs)].filter(Boolean));
  }
  for (const [width, height] of [[390, 844], [1920, 1080]]) {
    // Rotlicht mit offenem Panel: keine hellen Flächen (code-Kästchen, Kästchen von „Sichtbare Elemente“); Panel
    // ohne kiosk und lock; Fehlerhinweis eines Profils rot statt bernsteinfarben.
    const { ctx, page, msgs } = await openPausedClock(browser, { width, height, red: true, reply, query: "?p=fehlt", profile });
    await page.click("#mode-custom");
    await page.waitForTimeout(150);
    const got = await page.evaluate(() => {
      const light = (color) => {
        const m = color.match(/\d+(\.\d+)?/g);
        if (!m) return false;
        const [r, g, b, a = 1] = m.map(Number);
        return Number(a) > 0 && (r + g + b) / 3 > 90;
      };
      const param = document.querySelector("#custom-form .link-param");
      const box = document.querySelector("#custom-form .link-check input");
      const title = document.getElementById("clock-title");
      const lightNodes = [...document.querySelectorAll("#custom-panel *")]
        .filter((n) => n.getBoundingClientRect().width && light(getComputedStyle(n).backgroundColor)).length;
      return {
        paramBg: getComputedStyle(param).backgroundColor, lightNodes,
        boxScheme: getComputedStyle(box).colorScheme, boxAccent: getComputedStyle(box).accentColor,
        titleColor: getComputedStyle(title).color, titleError: title.classList.contains("is-error"),
        modes: ["kiosk", "lock"].filter((name) => document.getElementById(`custom-${name}`)),
        eink: Boolean(document.getElementById("custom-eink")),
        csp: window.__csp || [],
      };
    });
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/shot_${width}_clock_rotlicht_anpassen.png` });
    await ctx.close();
    const msgs404 = msgs.filter((m) => !/404/.test(m));
    note(`/clock Rotlicht Anpassen ${width}×${height}`, [
      got.lightNodes ? `${got.lightNodes} helle Flächen im Panel (code: ${got.paramBg})` : "",
      got.boxScheme === "dark" && got.boxAccent === "rgb(255, 42, 26)" ? "" : `Kästchen ${got.boxScheme}/${got.boxAccent}`,
      got.titleError && got.titleColor === "rgb(255, 42, 26)" ? "" : `Fehlertitel ${got.titleColor}`,
      got.modes.length ? `Panel bietet ${got.modes.join(", ")} an` : "", got.eink ? "" : "E-Ink fehlt im Panel",
      ...errors(got, msgs404)].filter(Boolean));
  }

  // Reiter „Anzeigen“ im Dashboard.
  for (const width of [390, 1440]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } });
    await ctx.addInitScript(() => {
      window.__csp = [];
      window.__opened = [];
      document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
      window.open = (url, target, features) => { window.__opened.push({ url, target, features }); return null; };
    });
    const page = await ctx.newPage();
    const msgs = [];
    page.on("console", (m) => { if (m.type() === "error") msgs.push(m.text()); });
    page.on("pageerror", (e) => msgs.push(`pageerror: ${e.message}`));
    await page.goto(`${BASE}/#/uhr/anzeigen`, { waitUntil: "load" });
    await page.waitForSelector("#displays-builder", { timeout: 10000 });
    const problems = [];
    // Gewählte Vorlage bleibt sichtbar; der Schalter „ohne Anmeldung“ ist ein Aktionsknopf ohne aria-pressed.
    await page.selectOption("#displays-load", "preset:tile");
    await page.waitForFunction(() => /layout=tile/.test(document.getElementById("displays-link")?.value || ""),
      null, { timeout: 5000 }).catch(() => null);
    const loaded = await page.evaluate(() => ({ value: document.getElementById("displays-load").value,
      link: document.getElementById("displays-link").value,
      pressed: document.getElementById("displays-public")?.getAttribute("aria-pressed") ?? null }));
    if (loaded.value !== "preset:tile" || !/layout=tile/.test(loaded.link)) problems.push(`Laden ${JSON.stringify(loaded)}`);
    if (loaded.pressed !== null) problems.push(`Schalter mit aria-pressed=${loaded.pressed}`);
    await page.click("#displays-builder .link-result .button-row .button:not(.primary)");
    const cleared = await page.evaluate(() => document.getElementById("displays-load").value);
    if (cleared !== "") problems.push(`nach Leeren steht noch „${cleared}“ in der Auswahl`);
    await page.selectOption("#dl-design", "studio");
    await page.fill("#dl-until", "20:15");
    await page.fill("#dl-label", "bis ON AIR");
    const linkValue = await page.inputValue("#displays-link");
    if (!linkValue.endsWith("/clock?design=studio&until=20:15&label=bis+ON+AIR")) problems.push(`Link „${linkValue}“`);
    await page.click('[data-size="banner"]');
    const opened = await page.evaluate(() => window.__opened);
    if (opened.length !== 1 || !/width=1600,height=200/.test(opened[0].features) || opened[0].target !== "_blank"
      || opened[0].url !== "/clock?design=studio&until=20:15&label=bis+ON+AIR") problems.push(`Vorschau ${JSON.stringify(opened)}`);
    await page.fill("#displays-name", `tour-${width}`);
    await page.fill("#displays-title", "Rundgang");
    await page.click("#displays-save");
    await page.waitForTimeout(1500);
    const saved = await apiJson(`/api/v1/clock/profile?p=tour-${width}`);
    if (saved.params?.until !== "20:15" || saved.title !== "Rundgang") problems.push(`Profil gespeichert ${JSON.stringify(saved)}`);
    await page.waitForSelector(".link-profile", { timeout: 5000 }).catch(() => null);
    const view = await page.evaluate(() => ({
      profiles: document.querySelectorAll(".link-profile").length,
      publicText: document.querySelector(".link-public-state")?.textContent || "",
      iframes: document.querySelectorAll("iframe").length,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      csp: window.__csp,
    }));
    if (view.profiles < 1) problems.push("Profil nicht in der Liste");
    if (!/^Aus:/.test(view.publicText)) problems.push(`Hinweis ohne Anmeldung „${view.publicText}“`);
    if (view.iframes) problems.push("iframe auf der Seite");
    if (view.overflow > 0) problems.push(`Überbreite ${view.overflow} px`);
    problems.push(...errors(view, msgs));
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/shot_${width}_anzeigen.png`, fullPage: true });
    await ctx.close();
    note(`#/uhr/anzeigen ${width}`, problems);
  }
  await apiJson("/api/settings", { changes: { clock_profiles: {} } });
  return { found, lines };
}

async function clockFitChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    lines.push(`${label}: ${problems.length ? problems.join("; ") : "ok"}`);
    if (problems.length) found.push(`${label}: ${problems.join("; ")}`);
  };
  const open = async (width, height, query, theme = null) => {
    const ctx = await browser.newContext({ viewport: { width, height }, timezoneId: "Europe/Berlin" });
    await ctx.addInitScript((th) => {
      window.__csp = [];
      document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
      try {
        localStorage.removeItem("ntp-gui-clock-design"); localStorage.setItem("ntp-gui-clock-red", "0");
        if (th) localStorage.setItem("ntp-gui-clock-theme", th);
      } catch (e) { /* egal */ }
    }, theme);
    const page = await ctx.newPage();
    const msgs = [];
    page.on("console", (m) => { if (m.type() === "error") msgs.push(m.text()); });
    page.on("pageerror", (e) => msgs.push(`pageerror: ${e.message}`));
    await page.clock.install({ time: CLOCK_SERVER });
    const realStart = Date.now();
    await page.route("**/api/v1/time", (route) => {
      const t = (CLOCK_SERVER + Date.now() - realStart) / 1000;
      return route.fulfill({ json: { t1: t, t2: t, synchronised: true, running: true, level: "good", accuracy: 0.0004,
        stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS", source: null, public: true } });
    });
    await page.goto(`${BASE}/clock${query}`, { waitUntil: "load" });
    await page.waitForTimeout(500);
    return { ctx, page, msgs };
  };
  const errors = async (page, msgs) => {
    const csp = await page.evaluate(() => window.__csp || []);
    return csp.length || msgs.length ? [`Fehler ${JSON.stringify([...csp, ...msgs])}`] : [];
  };

  for (const query of ["?bg=black", "?bg=black&design=studio", "?bg=black&design=digital&face=seg"]) {
    const { ctx, page, msgs } = await open(1440, 900, query, "light");
    const got = await page.evaluate(async () => {
      const k = await import("/static/js/clockkit.js");
      const toHex = (rgb) => `#${rgb.match(/\d+/g).slice(0, 3).map((v) => Number(v).toString(16).padStart(2, "0")).join("")}`;
      const bg = toHex(getComputedStyle(document.body).backgroundColor);
      const ink = toHex(getComputedStyle(document.body).color);
      const date = toHex(getComputedStyle(document.getElementById("local-date")).color);
      const sync = toHex(getComputedStyle(document.getElementById("clock-sync")).color);
      return { theme: document.documentElement.dataset.theme, bg, locked: document.getElementById("mode-theme").disabled,
        ratios: [ink, date, sync].map((c) => [c, Math.round(k.contrastRatio(c, bg) * 100) / 100]) };
    });
    const problems = [];
    if (got.theme !== "dark") problems.push(`data-theme ${got.theme}`);
    if (got.bg !== "#000000") problems.push(`Hintergrund ${got.bg}`);
    if (!got.locked) problems.push("Hell/Dunkel-Knopf nicht gesperrt");
    for (const [color, ratio] of got.ratios) if (!(ratio >= 4.5)) problems.push(`Schrift ${color} nur ${ratio}:1`);
    problems.push(...await errors(page, msgs));
    await ctx.close();
    note(`/clock Thema hell + ${query}`, problems);
  }

  for (const [query, want] of [["?design=studio&h12=1", { face: "10:15 AM" }], ["?design=digital&face=seg&h12=1&lz=0", { face: "10:15 AM" }],
    ["?design=digital&h12=1&lz=0", { text: /^10:15:\d\d AM$/ }], ["?design=studio", { face: "10:15 Uhr" }]]) {
    const { ctx, page, msgs } = await open(1440, 900, query);
    const got = await page.evaluate(() => ({ face: document.getElementById("face").getAttribute("aria-label"),
      text: document.getElementById("local-time").textContent }));
    const problems = [];
    if (want.face && got.face !== want.face) problems.push(`aria-label „${got.face}“ statt „${want.face}“`);
    if (want.text && !want.text.test(got.text)) problems.push(`Textzeit „${got.text}“`);
    problems.push(...await errors(page, msgs));
    await ctx.close();
    note(`/clock Screenreader ${query}`, problems);
  }

  for (const [width, height, query, layout, compact] of [[1920, 120, "", "strip", true], [1920, 160, "?design=studio", "strip", true],
    [1920, 200, "", "banner", false], [1920, 160, "?layout=strip", "strip", false]]) {
    const { ctx, page, msgs } = await open(width, height, query);
    await page.waitForTimeout(300);   // nach dem Ausblenden meldet der ResizeObserver die neue Bühne
    const got = await page.evaluate(layoutState);
    const extra = await page.evaluate(() => ({ compact: document.body.classList.contains("is-compact"),
      bar: getComputedStyle(document.querySelector(".clock-bar")).display, band: getComputedStyle(document.getElementById("band")).display }));
    const problems = [];
    if (got.layout !== layout) problems.push(`data-layout ${got.layout} statt ${layout}`);
    if (got.cq !== got.layout) problems.push(`CSS-Spiegel ${got.cq} ≠ ${got.layout}`);
    if (extra.compact !== compact) problems.push(`is-compact ${extra.compact}`);
    if (compact && (got.stageH < height - 1 || extra.bar !== "none" || extra.band !== "none")) {
      problems.push(`Bühne ${got.stageH} px von ${height}, Kopfzeile ${extra.bar}, Band ${extra.band}`);
    }
    if (!got.box) problems.push("Zeit nicht sichtbar");
    else if (got.box.top < got.safeBox.top - 1 || got.box.bottom > got.safeBox.bottom + 1) problems.push("Zeit außerhalb der Bühne");
    else if (compact && got.box.bottom - got.box.top < height * 0.5) problems.push(`Zeit nur ${Math.round(got.box.bottom - got.box.top)} px hoch`);
    if (got.vscroll > 0 || got.hscroll > 0) problems.push(`Scrollbalken (${got.hscroll}/${got.vscroll} px)`);
    problems.push(...await errors(page, msgs));
    await ctx.close();
    note(`/clock Streifen ${width}×${height} ${query || "(auto)"}`, problems);
  }
  return { found, lines };
}

// Ruhe auf der Uhrseite (T6-Nachbesserung), drei Seiten gleichzeitig, je gut 6 s echte Zeit:
// – E-Ink: zwischen zwei Minutenwechseln ändert sich nichts im DOM (auch nicht das Band beim Abfragen alle 5 s).
// – Ton-Panel per Maus bzw. Tastatur geöffnet: die Leiste blendet sich nach 4 s nicht aus.
// – #tone-status (aria-live) wird bei laufendem Ton nicht jede Sekunde neu geschrieben.
async function clockQuietChecks(browser) {
  const found = [];
  const lines = [];
  const prepare = async (query) => {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, timezoneId: "Europe/Berlin" });
    const page = await ctx.newPage();
    // Uhr läuft normal weiter: Eine stehende Date-Uhr (setFixedTime) läse die Seite als Uhrsprung und mäße
    // alle 2 s neu (kit.wallJump).
    await page.clock.install({ time: CLOCK_SERVER });
    await page.route("**/api/v1/time", (route) => route.fulfill({ json: {
      t1: CLOCK_SERVER / 1000, t2: CLOCK_SERVER / 1000, synchronised: true, running: true, level: "good",
      accuracy: 0.0004 + Math.random() * 0.0002, stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS",
      source: null, public: true } }));
    await page.goto(`${BASE}/clock${query}`, { waitUntil: "load" });
    await page.waitForTimeout(2200);
    return { ctx, page };
  };
  const observe = (page, selector) => page.evaluate((sel) => {
    window.__muts = [];
    const target = document.querySelector(sel);
    new MutationObserver((records) => {
      for (const r of records) {
        if (r.target === document.body && r.attributeName === "class") continue;   // is-idle der Leiste
        const el = r.target.nodeType === 1 ? r.target : r.target.parentElement;
        window.__muts.push(el.closest("[id]")?.id || el.tagName);
      }
    }).observe(target, { subtree: true, childList: true, characterData: true, attributes: true });
  }, selector);
  const eink = async () => {
    const { ctx, page } = await prepare("?eink=1&design=nixie");
    await observe(page, "body");
    await page.waitForTimeout(6200);
    const muts = await page.evaluate(() => window.__muts);
    await ctx.close();
    lines.push(`/clock E-Ink Ruhe: ${muts.length} Änderungen ${JSON.stringify([...new Set(muts)])}`);
    if (muts.length) found.push(`/clock E-Ink: DOM ändert sich ohne Minutenwechsel (${[...new Set(muts)].join(", ")})`);
  };
  const panel = async (how) => {
    const { ctx, page } = await prepare("?design=digital");
    if (how === "mouse") {
      await page.click("#mode-tone");
      // Ton per Skript starten: ein zweiter Klick weckte die Leiste erneut und verdeckte den Fehler.
      await page.evaluate(() => document.getElementById("tone-seconds").click());
    } else {
      await page.focus("#mode-tone");
      await page.keyboard.press("Enter");
    }
    await page.waitForTimeout(1500);
    await observe(page, "#tone-status");
    await page.waitForTimeout(4500);
    const got = await page.evaluate(() => ({ open: !document.getElementById("tone-panel").hidden,
      idle: document.body.classList.contains("is-idle"),
      opacity: getComputedStyle(document.querySelector(".clock-bar")).opacity,
      focus: document.activeElement?.id || "", status: window.__muts.length,
      text: document.getElementById("tone-status").textContent }));
    await ctx.close();
    lines.push(`/clock Ton-Panel (${how}): ${JSON.stringify(got)}`);
    if (!got.open || got.idle) found.push(`/clock Ton-Panel per ${how} offen, Leiste trotzdem ausgeblendet (${JSON.stringify(got)})`);
    if (how === "mouse" && got.status) found.push(`/clock #tone-status (aria-live) ${got.status}× neu geschrieben: „${got.text}“`);
  };
  await Promise.all([eink(), panel("mouse"), panel("keyboard")]);
  return { found, lines };
}

// „Heute“-Zeitleiste (1.6, T7) mit erfundenen Antworten (page.route): ein Tag mit Holdover 03:00–04:30 und genau drei
// bekannten Ereignissen. Bei 1440 und 390 px: genau drei Marker über dem Band an der richtigen Stelle (± 1 Fenster),
// Holdover-Abschnitt im Band, Marker auch im Diagramm, keine Überbreite, Tippflächen ≥ 24 px; Tastatur: Band fokussieren,
// Pos1 + Enter öffnet „So sah es um … aus“ (ohne Satellitenwinkel), Esc schließt und gibt den Fokus ans Band zurück,
// Tab erreicht einen Marker, Enter öffnet den Dialog zu seiner Zeit; der Filter blendet eine Art aus.
async function timelineChecks(browser) {
  const found = [];
  const lines = [];
  const now = Math.floor(Date.now() / 1000);
  const end = (Math.floor(now / 300) + 1) * 300;
  const start = end - 288 * 300;
  const at = (hours) => start + hours * 3600;
  const states = Array.from({ length: 288 }, (_, i) => (i >= 36 && i < 54 ? "h" : i >= 200 && i < 204 ? "w" : "g")).join("");
  const markers = [
    { id: 1, t: at(3) + 20, group: "source", level: "warn", title: "Keine Zeitquelle mehr ausgewählt" },
    { id: 2, t: at(10) + 70, group: "gps", level: "warn", title: "GPS-Fix verloren" },
    { id: 3, t: at(23.5), group: "restart", level: "info", title: "ntp-gui gestartet" },
  ].map((m) => ({ ...m, b: Math.floor((m.t - start) / 300) }));
  // Diagramme bekommen zusätzlich ein Ereignis „gerade eben“ ganz am rechten Rand (Tooltip darf dort nicht schrumpfen).
  const chartMarkers = [...markers, { id: 4, t: now - 5, group: "restart", level: "info",
    title: "Dienst chronyd neu gestartet, Quelle 192.0.2.1 wieder ausgewählt" }];
  const timeline = { now, start, end, bucket: 300, states, runs: [], markers,
    report: { day: "2026-11-08", samples: 8640, covered_s: 86400, synced_pct: 99.84, worst_offset: 0.0012, devices: 12,
      gps_hours: 21, pi_state: 0 } };
  for (const width of [1440, 390]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/api/timeline", (route) => route.fulfill({ json: timeline }));
    await page.route("**/api/timeline/markers*", (route) => route.fulfill({ json: { markers: chartMarkers } }));
    await page.goto(`${BASE}/#/`, { waitUntil: "load" });
    // Auf Band und Diagramm warten statt fester Zeit: Bei kaltem Browser braucht das erste Diagramm länger.
    await page.waitForSelector(".timeline-wrap .chart-event", { timeout: 15000 }).catch(() => {});
    await page.waitForSelector(".chart-wrap .chart-event", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(300);
    const band = await page.evaluate(() => {
      const track = document.querySelector(".timeline-track");
      const box = track?.getBoundingClientRect();
      const buttons = [...document.querySelectorAll(".timeline-wrap .chart-event")].map((b) => {
        const r = b.getBoundingClientRect();
        return { x: (r.left + r.width / 2 - box.left) / box.width, w: r.width, h: r.height };
      });
      const hold = [...document.querySelectorAll('.timeline-seg[data-state="holdover"]')].map((seg) => {
        const r = seg.getBoundingClientRect();
        return [(r.left - box.left) / box.width, (r.right - box.left) / box.width];
      });
      return { buttons, hold, role: track?.getAttribute("role"),
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        chart: document.querySelectorAll(".chart-wrap .chart-event").length,
        report: document.getElementById("tagesbericht")?.innerText || "" };
    });
    lines.push(`timeline ${width}: marker=${band.buttons.length} hold=${JSON.stringify(band.hold)} chart=${band.chart}`);
    if (band.buttons.length !== 3) found.push(`${width} Zeitleiste: ${band.buttons.length} statt 3 Marker`);
    band.buttons.forEach((b, i) => {
      const want = (markers[i].b + 0.5) / 288;
      if (Math.abs(b.x - want) > 1.5 / 288) found.push(`${width} Zeitleiste: Marker ${i + 1} bei ${b.x.toFixed(4)} statt ${want.toFixed(4)}`);
      if (b.w < 24 || b.h < 24) found.push(`${width} Zeitleiste: Marker ${i + 1} Tippfläche ${b.w}x${b.h}`);
    });
    if (band.hold.length !== 1 || Math.abs(band.hold[0][0] - 36 / 288) > 1 / 288 || Math.abs(band.hold[0][1] - 54 / 288) > 1 / 288) {
      found.push(`${width} Zeitleiste: Holdover-Phase falsch ${JSON.stringify(band.hold)}`);
    }
    if (band.role !== "slider") found.push(`${width} Zeitleiste: Band ohne role=slider`);
    if (band.overflow > 0) found.push(`${width} Zeitleiste: Überbreite ${band.overflow}`);
    if (!band.chart) found.push(`${width} Zeitleiste: keine Marker im Diagramm`);
    if (!/Gestern: 99,8 % synchron, schlechtester Wert ± 1,2 ms, 12 Geräte, GPS 21 h nutzbar, Pi ohne Unterspannung/.test(band.report.replace(/\s+/g, " "))) {
      found.push(`${width} Tagesbericht: „${band.report.replace(/\s+/g, " ")}“`);
    }
    // Tooltip eines Markers am rechten Rand (Band: 23:30 Uhr, Diagramm: „gerade eben“): lesbar breit, nicht
    // Zeichen für Zeichen umgebrochen, innerhalb des Fensters.
    for (const [where, selector] of [["Band", ".timeline-wrap .chart-event"], ["Diagramm", ".chart-wrap .chart-event"]]) {
      const all = await page.$$(selector);
      if (!all.length) continue;
      const last = all[all.length - 1];
      await last.scrollIntoViewIfNeeded();
      await last.hover();
      await page.waitForTimeout(150);
      const tip = await last.evaluate((button) => {
        const node = [...button.parentElement.querySelectorAll(":scope > .chart-event-tip")].find((t) => !t.hidden);
        if (!node) return null;
        const r = node.getBoundingClientRect();
        return { left: Math.round(r.left), right: Math.round(r.right), w: Math.round(r.width), h: Math.round(r.height),
          vw: document.documentElement.clientWidth };
      });
      lines.push(`timeline ${width}: Tooltip ${where} ${JSON.stringify(tip)}`);
      if (!tip) found.push(`${width} Zeitleiste: kein Tooltip am Marker (${where})`);
      else if (tip.w < 150 || tip.h > 120 || tip.left < 0 || tip.right > tip.vw) {
        found.push(`${width} Zeitleiste: Tooltip am rechten Rand (${where}) ${tip.w}×${tip.h} px, ${tip.left}–${tip.right}`);
      }
      await page.mouse.move(0, 0);
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    // Tastatur: Band → Pos1 → Enter → Dialog → Esc → Fokus zurück.
    await page.focus(".timeline-track");
    await page.keyboard.press("Home");
    await page.keyboard.press("ArrowRight");
    const text = await page.evaluate(() => document.querySelector(".timeline-track").getAttribute("aria-valuetext"));
    await page.keyboard.press("Enter");
    await page.waitForTimeout(900);
    const dialog = await page.evaluate(() => {
      const node = document.querySelector("dialog.moment-dialog[open]");
      return node ? { text: node.innerText, wide: node.scrollWidth > node.clientWidth + 1 } : null;
    });
    if (!dialog) found.push(`${width} Zeitleiste: Enter öffnet keinen Dialog`);
    else {
      if (!dialog.text.includes("So sah es um")) found.push(`${width} Dialog: Überschrift fehlt`);
      if (/Azimut|Elevation|°/.test(dialog.text)) found.push(`${width} Dialog: Satellitenwinkel sichtbar`);
      if (dialog.wide) found.push(`${width} Dialog: Überbreite`);
    }
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    const back = await page.evaluate(() => document.activeElement?.dataset?.focusKey || document.activeElement?.tagName);
    if (back !== "timeline-band") found.push(`${width} Zeitleiste: Fokus nach Esc auf ${back}`);
    // Tab vom Band erreicht den ersten Marker (Marker folgen dem Band); Enter öffnet den Dialog.
    await page.keyboard.press("Tab");
    const marker = await page.evaluate(() => document.activeElement?.classList.contains("chart-event")
      ? document.activeElement.getAttribute("aria-label") : null);
    if (!marker) found.push(`${width} Zeitleiste: Marker nicht per Tastatur erreichbar`);
    else {
      await page.keyboard.press("Enter");
      await page.waitForTimeout(900);
      if (!(await page.$("dialog.moment-dialog[open]"))) found.push(`${width} Zeitleiste: Enter auf Marker öffnet keinen Dialog`);
      await page.keyboard.press("Escape");
      await page.waitForTimeout(300);
    }
    lines.push(`timeline ${width}: „${text}“ · Marker „${marker}“`);
    // Filter nach Art: GPS ausblenden → 2 Marker, wieder einblenden → 3.
    await page.click('.marker-filter button[data-group="gps"]');
    await page.waitForTimeout(400);
    const hidden = await page.$$eval(".timeline-wrap .chart-event", (n) => n.length);
    await page.click('.marker-filter button[data-group="gps"]');
    await page.waitForTimeout(400);
    const shown = await page.$$eval(".timeline-wrap .chart-event", (n) => n.length);
    if (hidden !== 2 || shown !== 3) found.push(`${width} Filter nach Art: ${hidden}/${shown} statt 2/3`);
    if (errors.length) found.push(`${width} Zeitleiste: ${errors.slice(0, 3).join(" | ")}`);
    await ctx.close();
  }
  return { found, lines };
}

// Sichtbare Wortzahl je Seite (1.6, T2 „Seiten entschlacken“): innerText des Inhalts bei 1440 px, helles Thema.
// Geschlossene ⓘ-Popover stehen nicht im DOM, zugeklappte <details> zählt innerText nicht mit (nur die Zusammenfassung).
// Wort = Folge ohne Leerraum mit mindestens einem Buchstaben oder einer Ziffer.
// --- Statusband der Übersicht (1.6.1) --------------------------------------------------------------------
// Erfundene Hinweise (page.route auf /api/status): 2 Warnungen + 4 weitere (3 Infos, 1 Erfolg) – so viele, dass das
// alte Layout die Kennzahl-Kacheln auf die Höhe der Hinweisliste streckte. Bei 390, 1440 und 2000 px, hell und dunkel:
// Kacheln < 220 px hoch, Sparkline direkt unter der Notiz, keine leere Fläche > 150 px in einem Block der Karte, keine
// Überbreite; jeder Hinweis zeigt höchstens EINE Textzeile (Rest im ⓘ bzw. unter „Details“); die Zeile „… Informationen“
// zählt den Erfolgshinweis nicht als Information. TOUR_HERO_ONLY=1 prüft nur das; TOUR_HERO_SHOTS=<Ordner> legt
// Bildschirmfotos ab (hero_<Breite>_<Thema>.png). Nur Beispieladressen (RFC 5737).
const HERO_INSIGHTS = [
  { level: "ok", key: "synced", title: "Synchron mit GPS", text: "Stratum 1: Die Systemuhr folgt GPS, aktuelle Abweichung 1,4 µs." },
  { level: "warn", key: "unreach:192.0.2.1", action: "sources", title: "ntp1.example antwortet nicht",
    text: "Die letzten acht Anfragen an diese Quelle blieben ohne Antwort. Ursachen: Name nicht auflösbar, Port 123/udp nach außen gesperrt, Server außer Betrieb." },
  { level: "warn", key: "storage", title: "Einstellungen gehen beim Neuerstellen verloren",
    text: "/var/lib/chrony liegt nicht auf einem Volume. Im Dashboard gespeicherte Einstellungen und der Verlauf verschwinden, wenn der Container neu erstellt wird. In der Compose-Datei ein Volume für /var/lib/chrony anlegen." },
  { level: "info", key: "no_auth", action: "settings", title: "Dashboard ohne Passwort",
    text: "Jeder im LAN kann die Einstellungen ändern. Ein Passwort lässt sich unter System → Einstellungen → Dashboard & Zugang setzen." },
  { level: "info", key: "gps_distance", action: "gps", title: "GPS wird nur beobachtet, nicht genutzt",
    text: "chrony bewertet das GPS als zu unsicher: Die angenommene Unsicherheit ist viel größer als die der Netzwerkquellen. Mit Internet ist das unkritisch und ohne PPS so gewollt: Das GPS ist die Rückfallebene und springt ein, wenn das Internet ausfällt." },
  { level: "info", key: "web_proxy_untrusted", action: "settings", title: "Reverse Proxy erkannt, aber nicht eingetragen",
    text: "Ist das dein Proxy, trag ihn mit dem Knopf ein – dann erkennt ntp-gui, ob der Browser HTTPS benutzt. Anfragen mit Anmeldung tragen Proxy-Köpfe (X-Forwarded-For/-Proto), kommen aber von 127.0.0.1, die nicht in „Vertrauenswürdige Proxys“ steht.",
    fixes: [{ kind: "trust_proxy", id: "0123456789abcdef", label: "Als vertrauenswürdigen Proxy eintragen (127.0.0.1/32)", confirm: "?" }] },
  { level: "ok", key: "gps_used", title: "GPS wird genutzt", text: "Das GPS fließt in die Zeit ein (Abweichung 1,4 ms)." },
];

function heroState() {
  const hero = document.querySelector("#main .hero");
  if (!hero) return null;
  const box = (el) => el.getBoundingClientRect();
  // Größte leere Fläche in einem Block: Lücke zwischen zwei Kindern (von oben nach unten) oder unter dem letzten.
  const emptyBelow = (el) => {
    const r = box(el);
    const kids = [...el.children].filter((c) => c.getClientRects().length).map(box).sort((a, b) => a.top - b.top);
    let covered = r.top;
    let gap = 0;
    for (const k of kids) {
      gap = Math.max(gap, k.top - covered);
      covered = Math.max(covered, k.bottom);
    }
    return Math.round(Math.max(gap, r.bottom - covered));
  };
  const blocks = [".hero-verdict", ".hero-kpis .stat", ".hero-hints"].flatMap((sel) => [...hero.querySelectorAll(sel)]);
  const tiles = [...hero.querySelectorAll(".hero-kpis .stat")].map((tile) => {
    const note = tile.querySelector(".stat-note") || tile.querySelector(".stat-value");
    const spark = tile.querySelector(".stat-spark");
    return { height: Math.round(box(tile).height),
      gap: spark && note ? Math.round(box(spark).top - box(note).bottom) : 0 };
  });
  // Sichtbarer Text je Hinweis: jede Textzeile (p) eines Hinweises – höchstens eine Zeile hoch.
  const lines = [...hero.querySelectorAll(".hint-row, .insight")].map((item) => {
    const texts = [...item.querySelectorAll("p")].filter((p) => p.getClientRects().length);
    const lh = (p) => parseFloat(getComputedStyle(p).lineHeight) || parseFloat(getComputedStyle(p).fontSize) * 1.5;
    return { title: (item.querySelector("strong") || item).textContent.trim().slice(0, 40),
      rows: texts.map((p) => Math.round(box(p).height / lh(p) * 10) / 10) };
  });
  // Je Hinweiszeile: Höhe und Abstand vom Textende (Titel oder Zeile) bis zur ersten Aktion rechts.
  const rows = [...hero.querySelectorAll(".hint-row")].map((row) => {
    const texts = [...row.querySelectorAll(".hint-title strong, .hint-line-text, .hint-text")].filter((n) => n.getClientRects().length);
    const right = Math.max(...texts.map((n) => box(n).right));
    const actions = row.querySelector(".hint-actions");
    const act = actions ? [...actions.children].filter((c) => c.getClientRects().length).map(box) : [];
    const sameLine = act.filter((a) => a.top < box(row).top + 30);
    return { level: row.dataset.level, height: Math.round(box(row).height), fix: Boolean(row.querySelector(".insight-fixes")),
      jump: sameLine.length ? Math.round(Math.min(...sameLine.map((a) => a.left)) - right) : 0 };
  });
  const summary = hero.querySelector(".hint-summary-text");
  return { tiles, lines, rows, cards: hero.querySelectorAll(".insight").length, empty: blocks.map((b) => ({ cls: b.className.split(" ")[0], empty: emptyBelow(b) })),
    hero: Math.round(box(hero).height), width: Math.round(box(hero).width),
    heroOverflow: hero.scrollWidth - hero.clientWidth,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    summary: summary ? summary.textContent : "" };
}

async function heroChecks(browser) {
  const found = [];
  const lines = [];
  const shots = process.env.TOUR_HERO_SHOTS || "";
  for (const theme of ["dark", "light"]) {
    for (const width of [390, 1440, 2000, 2560]) {
      const ctx = await browser.newContext({ colorScheme: theme, viewport: { width, height: 1000 } });
      await ctx.addInitScript((t) => { try { localStorage.setItem("ntp-gui-theme", JSON.stringify(t)); } catch (e) { /* egal */ } }, theme);
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.route("**/api/status*", async (route) => {
        const response = await route.fetch();
        const body = await response.json();
        body.insights = HERO_INSIGHTS;
        await route.fulfill({ response, json: body });
      });
      await page.goto(`${BASE}/#/`, { waitUntil: "load" });
      await page.waitForSelector("#main .hero .hint-summary", { timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(1500);
      const toggle = await page.$("#main .hero .hint-summary");
      if (toggle) { await toggle.click(); await page.waitForTimeout(500); }
      const st = await page.evaluate(heroState);
      const tag = `Statusband ${width} ${theme}`;
      if (!st) { found.push(`${tag}: keine Karte`); await ctx.close(); continue; }
      lines.push(`hero ${width} ${theme}: h=${st.hero} tiles=${st.tiles.map((t) => `${t.height}/${t.gap}`).join(",")} `
        + `empty=${Math.max(...st.empty.map((e) => e.empty))} lines=${st.lines.map((l) => l.rows.join("+") || "0").join(",")}`);
      for (const tile of st.tiles) {
        if (tile.height >= 220) found.push(`${tag}: Kennzahl-Kachel ${tile.height} px hoch (≥ 220)`);
        if (tile.gap > 24) found.push(`${tag}: Sparkline ${tile.gap} px unter der Notiz (> 24)`);
      }
      for (const block of st.empty) {
        if (block.empty > 150) found.push(`${tag}: leere Fläche ${block.empty} px in ${block.cls}`);
      }
      if (st.overflow > 0 || st.heroOverflow > 0) found.push(`${tag}: Überbreite ${st.overflow}/${st.heroOverflow} px`);
      for (const item of st.lines) {
        if (item.rows.length > 1 || item.rows.some((r) => r > 1.5)) found.push(`${tag}: Hinweis „${item.title}“ zeigt ${item.rows.join("+")} Zeilen`);
      }
      // Ausgeklappte Infos sind dieselben kompakten Zeilen wie die Warnungen (keine größeren Karten), und
      // auf breiten Bildschirmen stehen die Aktionen nicht über 600 px hinter dem Textende.
      if (st.cards) found.push(`${tag}: ${st.cards} Hinweise als große Karte (.insight) statt als Zeile`);
      const warnMax = Math.max(0, ...st.rows.filter((r) => r.level === "warn").map((r) => r.height));
      // (Zeilen mit „Beheben“-Knopf ausgenommen: Der Knopf darf bei 390 px eine Zeile mehr brauchen.)
      for (const row of st.rows.filter((r) => r.level !== "warn" && r.level !== "crit" && !r.fix)) {
        if (warnMax && row.height > warnMax + 12) found.push(`${tag}: Info-Zeile ${row.height} px hoch, Warnungen ${warnMax} px`);
      }
      const jump = Math.max(0, ...st.rows.map((r) => r.jump));
      // Kurzer Text, Aktionen rechtsbündig: bei 1440 px knapp 800 px – breiter darf es nicht werden
      // (vor 1.6.1 bei 2560 px rund 1350 px, die Liste lief über die volle Kartenbreite).
      if (jump > 850) found.push(`${tag}: Aktion steht ${jump} px hinter dem Textende (> 850)`);
      lines.push(`hero ${width} ${theme}: rows=${st.rows.map((r) => `${r.level}:${r.height}`).join(",")} jump=${jump}`);
      if (!/3 Informationen/.test(st.summary) || !/1 in Ordnung/.test(st.summary)) {
        found.push(`${tag}: Zusammenfassung „${st.summary.trim().slice(0, 60)}“ statt „3 Informationen · 1 in Ordnung“`);
      }
      if (errors.length) found.push(`${tag}: ${errors.join("; ")}`);
      if (shots) {
        const hero = await page.$("#main .hero");
        await hero.screenshot({ path: `${shots}/hero_${width}_${theme}.png` });
        await page.screenshot({ path: `${shots}/seite_${width}_${theme}.png` });
      }
      await ctx.close();
    }
  }
  // Uhrqualität bei 2000 px: Vollbild-Uhr und Schaltsekunden nebeneinander – keine Karte auf die Höhe der
  // anderen gestreckt (bisher über 200 px leer unter der Vollbild-Uhr).
  for (const width of [2000]) {
    const ctx = await browser.newContext({ viewport: { width, height: 1000 } });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/#/uhr/qualitaet`, { waitUntil: "load" });
    await page.waitForSelector("#main .grid-natural .card", { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const cards = await page.$$eval("#main .grid-natural > .card", (nodes) => nodes.map((card) => {
      const r = card.getBoundingClientRect();
      const kids = [...card.children].filter((c) => c.getClientRects().length).map((c) => c.getBoundingClientRect());
      const bottom = Math.max(r.top, ...kids.map((k) => k.bottom));
      return { title: (card.querySelector("h2") || card).textContent.trim().slice(0, 30), empty: Math.round(r.bottom - bottom) };
    }));
    if (cards.length < 2) found.push(`Uhrqualität ${width}: Karten Schaltsekunden/Vollbild-Uhr nicht gefunden`);
    for (const c of cards) if (c.empty > 80) found.push(`Uhrqualität ${width}: ${c.empty} px leer unter „${c.title}“`);
    lines.push(`uhrqualitaet ${width}: ${cards.map((c) => `${c.title}=${c.empty}`).join(", ")}`);
    if (shots) await page.screenshot({ path: `${shots}/uhrqualitaet_${width}.png`, fullPage: true });
    await ctx.close();
  }
  return { found, lines };
}

const WORD_ROUTES = ["/#/", "/#/quellen", "/#/gps", "/#/clients", "/#/clients/192.0.2.10", "/#/uhr/qualitaet",
  "/#/uhr/hardware", "/#/uhr/ptp", "/#/system/diagnose", "/#/system/benachrichtigungen", "/#/system/einstellungen", "/#/hilfe"];

async function wordCounts(browser) {
  const ctx = await browser.newContext({ colorScheme: "light", viewport: { width: 1440, height: 900 } });
  const counts = {};
  for (const route of WORD_ROUTES) {
    const page = await ctx.newPage();
    await page.goto(BASE + route, { waitUntil: "load" });
    await page.waitForTimeout(2500);
    counts[route] = await page.evaluate(() => (document.getElementById("main").innerText.split(/\s+/)
      .filter((w) => /[\p{L}\p{N}]/u.test(w))).length);
    await page.close();
  }
  await ctx.close();
  return counts;
}

// --- Willkommens-Assistent (1.6, T3) ----------------------------------------------------------------------
async function apiJson(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-NTP-GUI": "1" },
    body: JSON.stringify(body) };
  const response = await fetch(BASE + path, opts);
  return response.json();
}

async function settingsValues() {
  const schema = await apiJson("/api/settings");
  return JSON.stringify((schema.fields || []).map((f) => [f.key, f.value]));
}

// Läuft im Browser: Zustand eines Schritts.
function setupStepState() {
  const small = [];
  for (const node of document.querySelectorAll("#main button:not(.info), #main .button, #main .chip, .setup-steps a, .setup-nav a, "
    + ".setup-links a, .setup-choice, .setup-checklist-items a, #main .copy, #main .field-help a")) {
    const r = node.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (r.width < 24 || r.height < 24) small.push(`${(node.textContent || node.getAttribute("aria-label") || "").trim().slice(0, 24)} ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  const title = document.getElementById("setup-step-title");
  return {
    hash: location.hash,
    title: title ? title.textContent.trim() : null,
    focused: document.activeElement === title,
    current: document.querySelectorAll('.setup-steps a[aria-current="step"]').length,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    small,
    csp: window.__csp || [],
  };
}

// Läuft im Browser: Wo steht der Tastaturfokus? (BODY = verloren)
function focusWhere() {
  const node = document.activeElement;
  if (!node || node === document.body) return "BODY";
  return `${node.tagName}.${node.className || ""}[${(node.textContent || node.getAttribute("aria-label") || "").trim().slice(0, 30)}]`;
}

async function setupChecks(browser) {
  const found = [];
  const lines = [];
  const start = await apiJson("/api/setup");
  if (start.install !== "fresh" || start.done || !start.auto_open) {
    found.push(`Assistent: kein Erststart im Testaufbau ${JSON.stringify({ install: start.install, done: start.done })}`);
  }
  const values = await settingsValues();
  for (const width of [390, 1440]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } });
    await ctx.addInitScript(() => {
      window.__csp = [];
      document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
    });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("dialog", (d) => d.accept());
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForTimeout(2500);
    let st = await page.evaluate(setupStepState);
    if (st.hash !== "#/system/einrichtung") found.push(`${width} Assistent erscheint beim Erststart nicht von selbst (${st.hash})`);
    for (let i = 0; i < 5; i += 1) {
      st = await page.evaluate(setupStepState);
      const want = `Schritt ${i + 1} von 5`;
      if (!st.title || !st.title.includes(want)) found.push(`${width} Schritt ${i + 1}: Überschrift „${st.title}“`);
      if (i > 0 && !st.focused) found.push(`${width} Schritt ${i + 1}: Fokus nicht auf der Überschrift`);
      if (st.current !== 1) found.push(`${width} Schritt ${i + 1}: ${st.current} Schritte mit aria-current`);
      if (st.overflow > 0) found.push(`${width} Schritt ${i + 1}: ${st.overflow} px Überbreite`);
      if (st.small.length) found.push(`${width} Schritt ${i + 1}: Tippfläche < 24 px: ${st.small.slice(0, 4).join(" | ")}`);
      if (st.csp.length) found.push(`${width} Schritt ${i + 1}: CSP ${st.csp.slice(0, 2).join(" | ")}`);
      if (i === 3) {
        // Loopback-Adresse aus dem Browser (der Rundgang läuft auf 127.0.0.1) nie als kopierbare Adresse anbieten.
        const loop = await page.$$eval("#main code", (n) => n.map((c) => c.textContent).filter((x) => /^(127\.|localhost$|::1$)/.test(x)));
        if (loop.length) found.push(`${width} Clients: Loopback-Adresse zum Kopieren angeboten (${loop.join(", ")})`);
      }
      if (i === 0) {
        const checks = await page.$$eval(".setup-check", (n) => n.length);
        if (!checks) found.push(`${width} Prüfen: keine Prüfpunkte`);
      }
      if (i === 1 && width === 1440) {
        // Vorlage mit einem Klick, Vorschau (Diff), dann verwerfen – ohne Übernehmen wird nichts geschrieben.
        // Per Tastatur: Der Chip ist danach gesperrt, die Übernehmen-Zeile verschwindet nach „Verwerfen“ – der
        // Fokus darf in beiden Fällen nicht auf <body> fallen.
        const chip = await page.$('.setup-presets .chip:not([disabled])');
        if (!chip) found.push("1440 Zeitquellen: keine Vorlage klickbar");
        else {
          await chip.focus();
          await page.keyboard.press("Enter");
          await page.waitForTimeout(300);
          const afterChip = await page.evaluate(focusWhere);
          if (afterChip === "BODY") found.push("1440 Zeitquellen: Fokus nach Enter auf einer Vorlage verloren");
          const added = await page.$$eval(".setup-sources .badge", (n) => n.filter((b) => b.textContent === "neu").length);
          if (!added) found.push("1440 Zeitquellen: Vorlage fügt nichts hinzu");
          await page.click('.setup-apply button:has-text("Vorschau")');
          await page.waitForTimeout(1200);
          const diff = await page.$$eval(".setup-preview .preview-file", (n) => n.length);
          if (!diff) found.push("1440 Zeitquellen: Vorschau ohne Diff");
          await page.focus('.setup-apply button:has-text("Verwerfen")');
          await page.keyboard.press("Enter");
          await page.waitForTimeout(300);
          const afterDiscard = await page.evaluate(focusWhere);
          if (afterDiscard === "BODY") found.push("1440 Zeitquellen: Fokus nach „Verwerfen“ verloren");
          lines.push(`setup focus: chip ${afterChip} · verwerfen ${afterDiscard}`);
        }
      }
      if (i < 4) {
        // „Weiter“ per Tastatur: Fokus auf den Knopf, Enter.
        await page.focus(".setup-nav a.primary");
        await page.keyboard.press("Enter");
        await page.waitForTimeout(1200);
      }
    }
    if (width === 390) {
      // „Zurück“ einmal, dann wieder vor – und „Später“: nichts geschrieben.
      await page.click('.setup-nav a:has-text("Zurück")');
      await page.waitForTimeout(800);
      st = await page.evaluate(setupStepState);
      if (!st.title?.includes("Schritt 4 von 5") || !st.focused) found.push(`390 Zurück: ${JSON.stringify({ title: st.title, focused: st.focused })}`);
      await page.goBack();
      await page.waitForTimeout(800);
      await page.click('.setup-nav a:has-text("Später")');
      await page.waitForTimeout(1500);
      const after = await apiJson("/api/setup");
      if (after.done) found.push("390 Später: setup_done gesetzt");
      if (await settingsValues() !== values) found.push("390 Überspringen hat Einstellungen geändert");
      const card = await page.$("#setup-checklist");
      if (!card) found.push("390 Übersicht: Checkliste fehlt nach „Später“");
      // Derselbe Browser öffnet die Startseite erneut: kein zweites Mal von selbst.
      await page.goto(`${BASE}/`, { waitUntil: "load" });
      await page.waitForTimeout(2000);
      const again = await page.evaluate(() => location.hash);
      if (again === "#/system/einrichtung") found.push("390 Assistent öffnet sich ein zweites Mal von selbst");
    } else {
      await page.click('.setup-nav button:has-text("Fertig")');
      await page.waitForTimeout(2000);
      const after = await apiJson("/api/setup");
      if (!after.done) found.push("1440 Fertig: setup_done fehlt");
      if (await settingsValues() !== values) found.push("1440 ohne Übernehmen wurden Einstellungen geändert");
      const hash = await page.evaluate(() => location.hash);
      if (hash !== "#/") found.push(`1440 Fertig: landet auf ${hash}`);
      const card = await page.evaluate(() => {
        const node = document.getElementById("setup-checklist");
        return node ? node.querySelector("h2")?.textContent || "" : null;
      });
      if (card === null) found.push("1440 Übersicht: Checkliste fehlt");
      else if (!/\d von 5 erledigt/.test(card)) found.push(`1440 Checkliste: „${card}“`);
      lines.push(`setup checklist: ${card}`);
      if (card !== null) {
        // Schließen per Tastatur: Karte weg, Fokus nicht auf <body>.
        await page.focus('#setup-checklist button[aria-label="Checkliste schließen"]');
        await page.keyboard.press("Enter");
        await page.waitForTimeout(1500);
        const gone = !(await page.$("#setup-checklist"));
        const where = await page.evaluate(focusWhere);
        if (!gone) found.push("1440 Checkliste: ✕ schließt die Karte nicht");
        if (where === "BODY") found.push("1440 Checkliste: Fokus nach ✕ verloren");
        lines.push(`setup checklist close: ${gone ? "weg" : "da"} · Fokus ${where}`);
      }
    }
    if (errors.length) found.push(`${width} Assistent: ${errors.slice(0, 3).join(" | ")}`);
    lines.push(`setup ${width}: ${found.length ? "Befund" : "ok"}`);
    await ctx.close();
  }
  return { found, lines };
}

(async () => {
  const browser = await chromium.launch();
  const results = [];
  let nav = { found: [], lines: [] };
  let words = {};
  try {
    // Erststart (leeres Datenverzeichnis): erst den Assistenten durchgehen und mit „Fertig“ abschließen – sonst
    // öffnete die Startseite in jedem neuen Browser-Kontext wieder den Assistenten.
    if (process.env.TOUR_LAYOUT_ONLY) {
      const result = await clockLayoutChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_COUNTDOWN_ONLY) {
      const result = await clockCountdownChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_LINK_ONLY) {
      await apiJson("/api/setup", { action: "done" });
      const result = await clockLinkChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_CLOCK_ONLY) {
      // Nur die Uhr-Werkstatt (/clock braucht keinen Assistenten).
      const result = await clockChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    const setupResult = process.env.TOUR_WORDS_ONLY || process.env.TOUR_PAGES_ONLY || process.env.TOUR_TIMELINE_ONLY
      || process.env.TOUR_HERO_ONLY
      ? (await apiJson("/api/setup", { action: "done" }), { found: [], lines: [] }) : await setupChecks(browser);
    nav.found.push(...setupResult.found);
    nav.lines.push(...setupResult.lines);
    if (process.env.TOUR_WORDS_ONLY) {
      console.log(JSON.stringify({ words: await wordCounts(browser) }, null, 1));
      return;
    }
    if (process.env.TOUR_TIMELINE_ONLY) {
      const result = await timelineChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_HERO_ONLY) {
      const result = await heroChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_PAGES_ONLY) {
      const result = await pagesChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    const navResult = await navChecks(browser);
    nav.found.push(...navResult.found);
    nav.lines.push(...navResult.lines);
    const settingsResult = await settingsChecks(browser);
    nav.found.push(...settingsResult.found);
    nav.lines.push(...settingsResult.lines);
    const clientsResult = await clientsChecks(browser);
    nav.found.push(...clientsResult.found);
    nav.lines.push(...clientsResult.lines);
    const pagesResult = await pagesChecks(browser);
    nav.found.push(...pagesResult.found);
    nav.lines.push(...pagesResult.lines);
    const clockResult = await clockChecks(browser);
    nav.found.push(...clockResult.found);
    nav.lines.push(...clockResult.lines);
    const timelineResult = await timelineChecks(browser);
    nav.found.push(...timelineResult.found);
    nav.lines.push(...timelineResult.lines);
    const heroResult = await heroChecks(browser);
    nav.found.push(...heroResult.found);
    nav.lines.push(...heroResult.lines);
    words = await wordCounts(browser);
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
  console.log(JSON.stringify({ problems, words, summary: [...nav.lines, ...results.map((x) => `${x.theme} ${x.width} ${x.route} ovf=${x.overflow} `
    + `coll=${x.collapsed} info=${x.info.hitOk}/${x.info.count} ${x.info.size || ""} overlap=${x.overlaps.length}`)] }, null, 1));
  process.exit(problems.length ? 1 : 0);
})().catch((e) => { console.error(String(e)); process.exit(2); });
