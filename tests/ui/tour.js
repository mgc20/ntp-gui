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
// Studiouhr C1 (clockTimerChecks, TOUR_TIMER_ONLY=1): Eieruhr, Pomodoro, eigene Countdowns, Nachtmodus, Bedienung.
// Studiouhr C2 (clockExtrasChecks, TOUR_EXTRAS_ONLY=1): Design binary, Mondphase, Nerd-Zeile, Fortschrittsbalken.
// Studiouhr C3 (clockFunChecks, TOUR_FUN_ONLY=1): Spiel „Tippe auf :00“, Zeitzeichen, Ostereier mit Konfetti und Konami-Code.
// Studiouhr A6 (clockLinkChecks, TOUR_LINK_ONLY=1): Profil (?p=) auf neun Flächen mit gemocktem Profil und /api/v1/time,
// Neuladen bei geändertem profiles_rev, Panel „Anpassen“ (Übernehmen ohne Parameter), Reiter „Anzeigen“ im Dashboard.
// Studiouhr B1 (clockTimecodeChecks, TOUR_TC_ONLY=1): Design tc auf neun Flächen – Kopfzeile „nicht genlocked“, Zehntel als
// Standard, Frames und Drop-Frame, Feinstelle grau über ½ Frame bzw. 50 ms und bei groben Zeitgebern, E-Ink, Taste T.
// Kleine Flächen (Kachel 240×135, Streifen), Grund der grauen Feinstelle in der Kopfzeile, Datum in der Zone des Servers.
// Studiouhr B2 (clockWorldChecks, TOUR_WORLD_ONLY=1): Weltzeit mit sechs Zonen als Leiste und als Layout world auf neun
// Flächen – alles in der Bühne, kein Scrollbalken, Schrift ab 12 px; Abweichung und Tageswechsel über die Umstellungen
// am 29.3., 25.10. und 8.3. (USA), halbe Stunden, Datumsgrenze, Kurznamen nur als Text, eine Zone wie bisher.
// Studiouhr B3/B5 (clockStatusChecks, TOUR_STATUS_ONLY=1): Statuszeile mit PTP und Holdover (Symbol und Text, fremde
// Werte zeigen nichts, ?show= ohne status), Kachel mit Titel, Zustandssymbol und Countdown, Prüfbild ?test=sync –
// Wechsel genau zur vollen Sekunde und höchstens einer je Sekunde, Vorlauf, Esc (auch mit lock=1), nie aus Profil oder
// gemerktem Stand, bei „weniger Bewegung“ nur der Hinweis.
// Studiouhr B4 (clockSignalChecks, TOUR_SIGNAL_ONLY=1): On-Air/REC-Signal auf neun Flächen, auch mit Timecode und Weltzeit –
// Rahmen und Balken mit Symbol und Text, ohne Bewegung, Zeit in der Bühne unter dem Balken, kein Scrollbalken; nur mit
// signal=1 (dann Abfrage im Sekundentakt), Taste O lokal, fremde Werte zeigen nichts, ohne Antwort „Stand ungewiss“,
// Schalter im Reiter „Anzeigen“.
// Dazu helpChecks (1.11, TOUR_HELP_ONLY=1): Hilfe mit Inhaltsverzeichnis, Unterseiten, tiefen und alten Links, Suche,
// „Zurück“ im Browser und „Mehr in der Hilfe“ aus dem ⓘ bei 390 und 1440 px.
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
  "/#/system/einrichtung/clients", "/#/system/einrichtung/benachrichtigung", "/#/hilfe", "/#/hilfe/betrieb",
  "/#/hilfe/gps/pps", "/clock", "/?dev=1#/muster",
  "/#/muster"];
// Alte Routen (bis 1.5) und Gruppen ohne Reiter → erwartete Adresse nach der Weiterleitung (location.replace,
// kein Verlaufseintrag). Alte Lesezeichen dürfen nie auf einer leeren Seite landen.
const redirects = {
  "/#/ptp": "#/uhr/ptp", "/#/uhrqualitaet": "#/uhr/qualitaet", "/#/hardware": "#/uhr/hardware",
  "/#/diagnose": "#/system/diagnose", "/#/benachrichtigungen": "#/system/benachrichtigungen",
  "/#/einstellungen": "#/system/einstellungen", "/#/einstellungen?s=gps": "#/system/einstellungen?s=gps",
  "/#/gnss": "#/gps", "/#/gpsquality": "#/gps", "/#/uhr": "#/uhr/qualitaet", "/#/system": "#/system/diagnose",
  "/#/quellen": "#/quellen", "/#/gps": "#/gps", "/#/clients": "#/clients", "/#/hilfe": "#/hilfe", "/#/": "#/",
  "/#/hilfe/ptp": "#/hilfe/ptp", "/#/hilfe?t=pps": "#/hilfe?t=pps",
  "/#/clients/192.0.2.10/pass": "#/clients/192.0.2.10/pass", "/#/hardware/x?y=1": "#/uhr/hardware/x?y=1",
};
const FORBIDDEN = /\d,000(\s|$)|\d\.\d+ (s|ms)\b|\d{1,3}\.\d{3}(,\d+)? (ppm|ppb|ns|µs|ms|s)\b/;

// Läuft im Browser: Bedienelemente, deren Rand ein ⓘ (oder dessen Tippfläche) verdeckt.
function overlapCheck() {
  const found = [];
  // Liegt der Punkt außerhalb eines Scrollbereichs, in dem das Element steckt (lange Ereignisliste), ist
  // es dort abgeschnitten und nicht zu treffen – was an der Stelle liegt, überlappt es nicht.
  const clipped = (node, x, y) => {
    for (let box = node.parentElement; box && box !== document.documentElement; box = box.parentElement) {
      const style = getComputedStyle(box);
      if (!/(auto|scroll|hidden|clip)/.test(style.overflowX + style.overflowY)) continue;
      const b = box.getBoundingClientRect();
      if (x < b.left || x > b.right || y < b.top || y > b.bottom) return true;
    }
    return false;
  };
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
        if (clipped(node, x, y)) continue;
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
      // Der Verweis „Mehr in der Hilfe“ unter jeder Seite (1.11) zählt nicht als Zeile.
      children: document.querySelectorAll("#main > :not(.page-help)").length, cards: document.querySelectorAll("#main .card").length }));
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
// zurück, um den Zustand vor der ersten Antwort zu prüfen. zone: Zeitzone des Browsers. at: Serverzeit nach dem
// Einschwingen (ms), Standard CLOCK_SERVER. reduced: Das System wünscht weniger Bewegung (prefers-reduced-motion).
async function openPausedClock(browser, { width, height = 900, query = "", red = false, reply, hold = null, settle = true,
  zone = "Europe/Berlin", profile = null, storage = null, at = CLOCK_SERVER, reduced = false, init = null, touch = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, timezoneId: zone,
    ...(reduced ? { reducedMotion: "reduce" } : {}), ...(touch ? { isMobile: true, hasTouch: true } : {}) });
  if (init) await ctx.addInitScript(init);   // z. B. window.obsstudio wie in einer OBS-Browserquelle
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
  const clock = { advanced: 0, hits: 0, base: at - CLOCK_SETTLE_MS };
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
  const tcResult = await clockTimecodeChecks(browser);
  found.push(...tcResult.found);
  lines.push(...tcResult.lines);
  const worldResult = await clockWorldChecks(browser);
  found.push(...worldResult.found);
  lines.push(...worldResult.lines);
  const statusResult = await clockStatusChecks(browser);
  found.push(...statusResult.found);
  lines.push(...statusResult.lines);
  const signalResult = await clockSignalChecks(browser);
  found.push(...signalResult.found);
  lines.push(...signalResult.lines);
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
  "?design=flip", "?design=wort", "?design=tc", "?design=binary", "?design=binary&bin=plain&h12=1",
  "?design=binary&show=moon,nerd,progress"];
const LAYOUT_PARAMS = ["?layout=tile&safe=10&design=studio", "?layout=tile&design=digital", "?scale=200",
  "?scale=50&design=digital&face=seg", "?shift=2&safe=3&design=digital", "?layout=strip&design=nixie",
  "?layout=banner&design=flip", "?layout=column&design=wort", "?show=time,status&design=digital",
  "?bg=transparent&kiosk=1&design=studio", "?look=paper&accent=ffffff&design=digital&face=mono",
  "?h12=1&lz=0&colon=blink&design=digital&face=seg", "?eink=1&design=studio&date=iso", "?look=terminal&design=studio&seconds=ring&sub=date",
  "?design=studio&scale=200", "?layout=banner&scale=200&design=digital", "?design=tc&sub=frames&fps=59.94&scale=200",
  "?design=tc&layout=tile&sub=frames", "?design=tc&layout=strip", "?design=tc&eink=1&layout=column"];

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

// Studiouhr C1 (clockTimerChecks, TOUR_TIMER_ONLY=1): Eieruhr, Pomodoro, eigene Countdowns, Nachtmodus und die Regel
// für Bedienelemente. Auf allen neun Flächen und fest als Streifen (1920×100) bzw. Kachel (480×270): Eieruhr (?timer=3s,
// Leertaste) läuft ab – „Zeit ist um!“ als Text mit Rahmen, Überzeit, im Bild, ohne Umbruch und Scrollbalken. Gesperrter
// Speicher: Merken meldet „nur bis zum Neuladen“. Handy quer (Touch 740×300, 667×320): Timer und Nacht in der Leiste. Bei 390 und 1440 px das Panel „Timer“: sechs Schnellwahlen, 3 min ohne gelbe
// Stufe, „+1 min“, eigene Dauer, Pomodoro-Start, eigener Countdown merken und wieder entfernen (nur localStorage), Tippflächen
// ≥ 24 px, keine Überbreite. Pomodoro (?pomo=1m&pause=1m) wechselt nach einer Minute in die Pause und zählt. Nachtmodus
// nach Uhrzeit (grau bzw. rot, Deckkraft aus dimlevel), Taste N schaltet von Hand. Keine Knöpfe in den Voreinstellungen
// studio, tile, banner, mit kiosk=1, lock=1, fun=0 und in OBS (window.obsstudio); Taste N wirkt dort nicht und fehlt in
// der Kürzel-Übersicht. Dazu ein Lauf
// in Echtzeit: keine Long Tasks (> 50 ms) und keine Bildschleife bei laufendem Pomodoro. Fotos mit TOUR_SHOTS.
function timerState() {
  const root = document.documentElement;
  const cd = document.getElementById("cd");
  const time = document.getElementById("cd-time");
  const stage = document.getElementById("clock-stage").getBoundingClientRect();
  const safe = parseFloat(getComputedStyle(root).getPropertyValue("--safe")) || 0;
  const box = cd.getBoundingClientRect();
  const size = parseFloat(getComputedStyle(time).fontSize);
  const visible = (id) => { const el = document.getElementById(id); const r = el.getBoundingClientRect();
    return !el.hidden && getComputedStyle(el).display !== "none" && r.width > 0 && r.height > 0; };
  return {
    text: time.textContent, label: document.getElementById("cd-label").textContent, state: document.getElementById("cd-state").textContent,
    level: cd.dataset.level, phase: cd.dataset.phase, end: root.dataset.cdEnd || "", outline: getComputedStyle(cd).outlineStyle,
    wrapped: time.getBoundingClientRect().height > size * 1.6, layout: document.getElementById("clock-stage").dataset.layout,
    box: { left: box.left, right: box.right, top: box.top, bottom: box.bottom, w: box.width, h: box.height },
    safeBox: { left: stage.left + stage.width * safe / 100, right: stage.right - stage.width * safe / 100,
      top: stage.top + stage.height * safe / 100, bottom: stage.bottom - stage.height * safe / 100 },
    vscroll: root.scrollHeight - root.clientHeight, hscroll: root.scrollWidth - root.clientWidth,
    mode: root.dataset.mode || "", night: root.dataset.night || "",
    opacity: getComputedStyle(document.getElementById("clock-stage")).opacity,
    timerBtn: visible("mode-timer"), nightBtn: visible("mode-night"), actions: visible("cd-actions"), plus: visible("cd-plus"),
    bar: visible("clock-back"), barH: document.querySelector(".clock-bar").getBoundingClientRect().height,
    timeFont: parseFloat(getComputedStyle(document.getElementById("local-time")).fontSize), nightPressed: document.getElementById("mode-night").getAttribute("aria-pressed"),
    stateShown: visible("cd-state"), keysN: !document.getElementById("keys-n").hidden && !document.getElementById("keys-n-key").hidden,
    csp: window.__csp || [],
  };
}

function timerPanelState() {
  const panel = document.getElementById("timer-panel");
  // ⓘ hat seine eigene 24-px-Prüfung (infoHitCheck); beim Kästchen zählt das Label drumherum.
  const small = [...panel.querySelectorAll("button:not(.info), input:not([type=checkbox]), a, label.clock-timer-check")].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && (r.width < 24 || r.height < 24);
  }).map((el) => el.id || el.textContent.trim().slice(0, 20));
  return {
    open: !panel.hidden, presets: [...document.querySelectorAll("#egg-presets button")].map((b) => b.textContent),
    goals: [...document.querySelectorAll("#goal-list a")].map((a) => a.getAttribute("href")),
    own: [...document.querySelectorAll("#own-list a")].map((a) => [a.textContent, a.getAttribute("href")]),
    stored: localStorage.getItem("ntp-gui-clock-countdowns"), status: document.getElementById("timer-status").textContent,
    small, hscroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    pomo: document.getElementById("pomo-line").textContent,
    untilFits: (() => {   // Platzhalter des Ziel-Felds ganz zu sehen (Breite des Texts in der Schrift des Felds)
      const input = document.getElementById("own-until");
      const style = getComputedStyle(input);
      const ctx = document.createElement("canvas").getContext("2d");
      ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      return ctx.measureText(input.placeholder).width <= input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    })(),
  };
}

async function clockTimerChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    lines.push(`${label}: ${problems.length ? problems.join("; ") : "ok"}`);
    if (problems.length) found.push(`${label}: ${problems.join("; ")}`);
  };
  const M = "−";
  const errors = (got, msgs) => (got.csp.length || msgs.length ? [`Fehler ${JSON.stringify([...got.csp, ...msgs])}`] : []);
  const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/clock-c1-${name}.png` }); };
  // 1) Eieruhr läuft ab, auf allen neun Flächen und fest im Streifen bzw. in der Kachel (dort steht „Zeit ist um!“ klein).
  for (const [width, height, layout] of [...STUDIO_VIEWPORTS, [1920, 100, "strip"], [480, 270, "tile"]]) {
    const query = layout ? `?layout=${layout}&timer=3s` : "?timer=3s";
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, query });
    await page.keyboard.press("Space");
    await clock.run(4500);   // die Anzeige wechselt 2 ms nach der vollen Sekunde
    const got = await page.evaluate(timerState);
    await shot(page, `ende-${width}x${height}${layout ? `-${layout}` : ""}`);
    await ctx.close();
    const problems = [];
    if (got.end !== "1") problems.push("kein data-cd-end");
    if (got.text !== "+00:00:01") problems.push(`zeigt ${got.text}`);
    if (got.state !== "Zeit ist um!" || !got.stateShown) problems.push(`Text „${got.state}“ ${got.stateShown ? "" : "(ausgeblendet)"}`);
    if (layout && got.layout !== layout) problems.push(`Layout ${got.layout}`);
    if (got.outline !== "solid") problems.push(`kein Rahmen (${got.outline})`);
    const b = got.box;
    const z = got.safeBox;
    if (!(b.w > 0 && b.h > 0)) problems.push("Countdown nicht sichtbar");
    else if (b.left < z.left - 6 || b.right > z.right + 6 || b.top < z.top - 6 || b.bottom > z.bottom + 6) {
      problems.push(`außerhalb der Bühne (${[b.left, b.top, b.right, b.bottom].map(Math.round)} in ${[z.left, z.top, z.right, z.bottom].map(Math.round)})`);
    }
    if (got.wrapped) problems.push("Umbruch");
    if (got.vscroll > 0 || got.hscroll > 0) problems.push(`Scrollbalken (${got.hscroll}/${got.vscroll} px)`);
    problems.push(...errors(got, msgs));
    note(`/clock Eieruhr-Ende ${width}×${height}${layout ? ` ${layout}` : ""}`, problems);
  }
  // 2) Panel „Timer“ bei 390 und 1440 px.
  for (const width of [390, 1440]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height: 900, query: "" });
    await page.click("#mode-timer");
    await clock.run(250);
    const panel = await page.evaluate(timerPanelState);
    await shot(page, `panel-${width}`);
    await page.click("#egg-presets button:nth-child(2)");   // 3 min
    await clock.run(1500);
    const egg = await page.evaluate(timerState);
    await page.click("#cd-plus");
    await clock.run(250);
    const plus = await page.evaluate(timerState);
    await page.fill("#egg-input", "7:30");
    await page.click("#egg-start");
    await clock.run(250);   // gerade gestartet: noch die volle Dauer
    const own = await page.evaluate(timerState);
    await page.fill("#egg-input", "abc");
    await page.click("#egg-start");
    const bad = await page.evaluate(() => [document.getElementById("egg-input").getAttribute("aria-invalid"),
      document.getElementById("timer-status").textContent]);
    await page.fill("#own-label", "Tagesschau");
    await page.fill("#own-until", "20:15");
    await page.click("#own-save");
    const saved = await page.evaluate(timerPanelState);
    await shot(page, `panel-gemerkt-${width}`);
    await page.click("#own-list button");
    const removed = await page.evaluate(timerPanelState);
    await page.click("#pomo-start");
    await clock.run(1500);
    const pomo = await page.evaluate(timerState);
    await ctx.close();
    const problems = [];
    if (!panel.open) problems.push("Panel zu");
    if (panel.presets.join("|") !== "1 min|3 min|5 min|10 min|15 min|30 min") problems.push(`Schnellwahl ${panel.presets}`);
    if (panel.goals.join(" ") !== "/clock?goal=newyear /clock?goal=dst /clock?goal=unix /clock?goal=ntp /clock?goal=y2038") problems.push(`Ziele ${panel.goals}`);
    if (panel.small.length) problems.push(`Tippflächen < 24 px: ${panel.small.join(", ")}`);
    if (panel.hscroll > 0) problems.push(`Überbreite ${panel.hscroll} px`);
    if (!panel.untilFits) problems.push("Platzhalter im Feld „Ziel“ abgeschnitten");
    if (egg.text !== `${M}02:59` || egg.level !== "none" || egg.label !== "Timer 03:00") problems.push(`3 min: ${egg.text} ${egg.level} „${egg.label}“`);
    if (!egg.plus) problems.push("+1 min fehlt");
    if (plus.text !== `${M}03:59`) problems.push(`+1 min: ${plus.text}`);
    if (own.text !== `${M}07:30` || own.label !== "Timer 07:30") problems.push(`eigene Dauer: ${own.text} „${own.label}“`);
    if (bad[0] !== "true" || !/verstehe/.test(bad[1])) problems.push(`falsche Dauer: ${bad}`);
    if (JSON.stringify(saved.own) !== JSON.stringify([["Tagesschau (20:15)", "/clock?until=20:15&label=Tagesschau"]])) problems.push(`gemerkt ${JSON.stringify(saved.own)}`);
    if (saved.stored !== JSON.stringify([{ until: "20:15", label: "Tagesschau" }])) problems.push(`localStorage ${saved.stored}`);
    if (removed.own.length || removed.stored !== null) problems.push("Entfernen wirkt nicht");
    if (pomo.label !== "Pomodoro 1 · Arbeit" || pomo.text !== `${M}24:59` || pomo.plus) problems.push(`Pomodoro: ${pomo.text} „${pomo.label}“`);
    problems.push(...errors(pomo, msgs));
    note(`/clock Panel Timer ${width}`, problems);
  }
  // 2b) Gesperrter Speicher (privates Fenster): Merken sagt ehrlich, dass nur bis zum Neuladen gemerkt ist.
  {
    const blocked = () => { Object.defineProperty(window, "localStorage", { get() { throw new DOMException("gesperrt", "SecurityError"); } }); };
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1440, height: 900, init: blocked });
    await page.click("#mode-timer");
    await page.fill("#own-label", "Test");
    await page.fill("#own-until", "20:15");
    await page.click("#own-save");
    await clock.run(250);
    const got = await page.evaluate(() => ({ status: document.getElementById("timer-status").textContent,
      own: [...document.querySelectorAll("#own-list a")].map((a) => a.textContent), csp: window.__csp || [] }));
    await ctx.close();
    note("/clock eigener Countdown, Speicher gesperrt", [/Neuladen/.test(got.status) ? "" : `Meldung „${got.status}“`,
      got.own.join() === "Test (20:15)" ? "" : `Liste ${got.own}`, ...errors(got, msgs)].filter(Boolean));
  }
  // 2c) Handy im Querformat (Touch, ohne Tastatur): Timer und Nacht bleiben in der Leiste; nur sehr kleine flache Fenster
  // verzichten darauf.
  // Die Leiste bleibt dabei einzeilig wie in 1.9 (Knopfgruppe rollt seitlich, höchstens 48 px hoch). Die Ziffern
  // mindestens 20 % der Fensterhöhe: Mit der umbrochenen Leiste (zwei bis drei Zeilen) lagen sie darunter.
  for (const [width, height, want, minFont] of [[740, 300, true, 0], [667, 320, true, 0], [568, 300, false, 0],
    [640, 360, true, 72], [740, 360, true, 72], [844, 390, true, 78]]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, touch: true });
    await clock.run(250);
    const got = await page.evaluate(timerState);
    await shot(page, `quer-${width}x${height}`);
    await ctx.close();
    note(`/clock Querformat ${width}×${height} Touch`, [got.timerBtn === want && got.nightBtn === want ? ""
      : `Timer/Nacht ${got.timerBtn}/${got.nightBtn}, erwartet ${want}`, got.hscroll > 0 ? `Überbreite ${got.hscroll} px` : "",
      got.barH <= 48 ? "" : `Leiste ${Math.round(got.barH)} px hoch (umbrochen)`,
      got.timeFont >= minFont ? "" : `Ziffern nur ${got.timeFont.toFixed(1)} px statt ≥ ${minFont} px`,
      ...errors(got, msgs)].filter(Boolean));
  }
  // 3) Pomodoro wechselt nach der Arbeitsphase in die Pause und zählt.
  {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, query: "?pomo=1m&pause=1m" });
    await page.keyboard.press("Space");
    await clock.run(500);
    clock.advanced += 60000;
    await page.clock.runFor(60000);
    await clock.run(1500);
    const got = await page.evaluate(timerState);
    const live = await page.evaluate(() => document.getElementById("clock-live").textContent);
    await shot(page, "pomodoro-pause");
    await ctx.close();
    note("/clock Pomodoro Phasenwechsel", [got.label === "Pomodoro 1 · Pause" ? "" : `„${got.label}“`,
      got.state === "1 Pomodoro geschafft" ? "" : `„${got.state}“`, /^−00:5\d$/.test(got.text) ? "" : `zeigt ${got.text}`,
      got.end ? "Eieruhr-Ende beim Pomodoro" : "", /Pause/.test(live) ? "" : `Ansage „${live}“`, ...errors(got, msgs)].filter(Boolean));
  }
  // 4) Nachtmodus nach Uhrzeit (10:15 liegt in 8-17) und Taste N.
  for (const [query, mode, opacity] of [["?dim=8-17", "night", "0.4"], ["?dim=8-17&dimred=1&dimlevel=60", "red", "0.6"]]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1440, height: 900, query });
    const on = await page.evaluate(timerState);
    await shot(page, `nacht-${mode}`);
    await page.keyboard.press("n");
    await clock.run(250);
    const off = await page.evaluate(timerState);
    await ctx.close();
    note(`/clock Nachtmodus ${query}`, [on.mode === mode && on.night === "1" ? "" : `an: ${on.mode}/${on.night}`,
      on.opacity === opacity ? "" : `Deckkraft ${on.opacity}`, on.nightPressed === "true" ? "" : "Knopf nicht gedrückt",
      !off.night && off.mode === "" && off.opacity === "1" ? "" : `nach N: ${off.mode}/${off.night}/${off.opacity}`,
      ...errors(off, msgs)].filter(Boolean));
  }
  {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1440, height: 900, query: "?dim=20-6" });
    const before = await page.evaluate(timerState);
    await page.click("#mode-night");
    await clock.run(250);
    const after = await page.evaluate(timerState);
    await ctx.close();
    note("/clock Nachtmodus von Hand", [before.night ? "außerhalb des Zeitplans an" : "", after.mode === "night" ? "" : `nach Klick ${after.mode}`,
      before.keysN ? "" : "Kürzel-Übersicht ohne N",
      ...errors(after, msgs)].filter(Boolean));
  }
  // 5) Keine Bedienung in Studio-, Kachel- und Kiosk-Voreinstellungen, mit lock=1, fun=0 und in OBS.
  const obs = () => { window.obsstudio = { pluginVersion: "30.0.0" }; };
  for (const [name, query, init, actions] of [["studio", "?p=studio&timer=5m", null, false], ["tile", "?p=tile&timer=5m", null, false],
    ["banner", "?p=banner&timer=5m", null, false], ["kiosk", "?kiosk=1&timer=5m", null, false], ["lock", "?lock=1&timer=5m", null, false],
    ["fun0", "?fun=0&timer=5m", null, true], ["obs", "?timer=5m", obs, false]]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, query, init });
    await clock.run(1500);   // Profil geladen
    await page.keyboard.press("n");
    await clock.run(250);
    const got = await page.evaluate(timerState);
    if (name === "obs") await shot(page, "obs");
    await ctx.close();
    note(`/clock Bedienung ${name}`, [got.timerBtn || got.nightBtn ? "Knöpfe Timer/Nacht sichtbar" : "",
      got.actions !== actions ? `Knöpfe am Countdown ${got.actions ? "sichtbar" : "fehlen"}` : "",
      got.night ? "Taste N wirkt" : "", got.keysN ? "Kürzel-Übersicht nennt N" : "", name === "obs" && got.bar ? "Leiste in OBS sichtbar" : "",
      name === "obs" && /Start/.test(got.state) ? `verspricht Start-Knopf „${got.state}“` : "", ...errors(got, msgs)].filter(Boolean));
  }
  // 6) Echtzeit: laufender Pomodoro ohne Long Tasks und ohne Bildschleife.
  {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    await ctx.addInitScript(() => {
      window.__long = [];
      window.__raf = 0;
      const raf = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (cb) => { window.__raf += 1; return raf(cb); };
      try { new PerformanceObserver((list) => window.__long.push(...list.getEntries().map((e) => e.duration))).observe({ type: "longtask", buffered: true }); } catch (e) { /* egal */ }
    });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/clock?pomo=25m&dim=0-23`, { waitUntil: "load" });
    await page.waitForTimeout(1500);
    await page.keyboard.press("Space");
    const rafStart = await page.evaluate(() => window.__raf);
    await page.waitForTimeout(6000);
    const got = await page.evaluate(() => ({ long: window.__long, raf: window.__raf }));
    await ctx.close();
    note("/clock C1 Leistung", [got.long.length ? `Long Tasks ${got.long.map(Math.round)}` : "",
      got.raf - rafStart > 2 ? `Bildschleife (${got.raf - rafStart} Bilder)` : ""].filter(Boolean));
  }
  return { found, lines };
}

// Studiouhr C2 (clockExtrasChecks, TOUR_EXTRAS_ONLY=1): Design binary und die Zusätze Mondphase, Nerd-Zeile und
// Fortschrittsbalken (?show=moon,nerd,progress). Auf den neun Flächen: Zusätze im Bild (in Kachel und Streifen nie),
// keine Scrollbalken, Zeit ohne Umbruch, Nerd-Zeile mit TAI und GPS aus tai_utc des (gemockten) Servers, ohne tai_utc „–“.
// Binäruhr (bcd und plain) zeigt die gemockte Serverzeit 10:15:42 als Lämpchen. Nie Zusätze in den Voreinstellungen
// studio, tile, banner und mit fun=0; Standard ohne ?show= ohne Zusätze. Klick auf den Mond spiegelt ihn (Südhalbkugel,
// nur localStorage). Echtzeit: keine Long Tasks, keine Bildschleife. Fotos mit TOUR_SHOTS.
function extrasState() {
  const root = document.documentElement;
  const stage = document.getElementById("clock-stage").getBoundingClientRect();
  const visible = (id) => { const el = document.getElementById(id); const r = el.getBoundingClientRect();
    return !el.hidden && getComputedStyle(el).display !== "none" && r.width > 0 && r.height > 0; };
  const extras = document.getElementById("extras").getBoundingClientRect();
  const time = document.getElementById(document.getElementById("local-time").hidden ? "face" : "local-time");
  const tb = time.getBoundingClientRect();
  const size = parseFloat(getComputedStyle(time).fontSize);
  const lamps = [...document.querySelectorAll("#face .bin-lamp")].map((l) => (l.classList.contains("on") ? "1" : "0")).join("");
  return {
    layout: document.getElementById("clock-stage").dataset.layout, stageH: stage.height, extras: visible("extras"), moon: visible("moon-box"),
    nerd: visible("nerd"), bars: visible("bars"), inside: extras.bottom <= stage.bottom + 1 && extras.top >= stage.top - 1
      && extras.right <= stage.right + 1 && extras.left >= stage.left - 1,
    timeInside: tb.bottom <= stage.bottom + 1 && tb.top >= stage.top - 1,
    wrapped: !document.getElementById("local-time").hidden && tb.height > size * 1.6,
    nerdText: [...document.querySelectorAll(".clock-nerd-item")].map((n) => n.textContent),
    moonText: document.getElementById("moon-text").textContent, moonPath: document.getElementById("moon-lit").getAttribute("d"),
    moonPressed: document.getElementById("moon").getAttribute("aria-pressed"),
    barTexts: [...document.querySelectorAll(".clock-prog-item")].map((n) => n.textContent),
    barNow: [...document.querySelectorAll(".clock-prog-item")].map((n) => n.getAttribute("aria-valuenow")),
    lamps, values: [...document.querySelectorAll("#face .bin-value")].map((n) => n.textContent),
    vscroll: root.scrollHeight - root.clientHeight, hscroll: root.scrollWidth - root.clientWidth, csp: window.__csp || [],
  };
}

async function clockExtrasChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    lines.push(`${label}: ${problems.length ? problems.join("; ") : "ok"}`);
    if (problems.length) found.push(`${label}: ${problems.join("; ")}`);
  };
  const errors = (got, msgs) => (got.csp.length || msgs.length ? [`Fehler ${JSON.stringify([...got.csp, ...msgs])}`] : []);
  const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/clock-c2-${name}.png` }); };
  const withTai = (tai) => (ms) => ({ t1: ms / 1000, t2: ms / 1000, synchronised: true, running: true, level: "good",
    accuracy: 0.0004, stratum: 1, leap: "Normal", leap_next: null, tai_utc: tai, source_kind: "GPS", source: null, public: true });
  // Serverzeit CLOCK_SERVER = 2026-06-30 08:15:42,5 UTC (10:15:42 in Berlin): Unix 1782807342, TAI 08:16:19,
  // GPS 1782807342 − 315964800 + 18 = 1466842560 s → Woche 2425, Sekunde 216960 (Dienstag 12:16:00 GPS-Zeit).
  const unix = Math.floor(CLOCK_SERVER / 1000);
  const gps = unix - 315964800 + 18;
  const wantNerd = [`Unix ${unix}`, `Hex 0x${unix.toString(16).toUpperCase()}`, "TAI 08:16:19 (+37 s)", `GPS Woche ${Math.floor(gps / 604800)} · ${gps % 604800} s`,
    `MJD ${(CLOCK_SERVER / 86400000 + 40587).toFixed(3).replace(".", ",")}`, "Tag 181", "ISO 2026-W27-2", "Römisch X:XV"];
  // 1) Alle Zusätze auf den neun Flächen.
  for (const [width, height] of STUDIO_VIEWPORTS) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, query: "?show=moon,nerd,progress", reply: withTai(37) });
    const got = await page.evaluate(extrasState);
    await shot(page, `zusaetze-${width}x${height}`);
    await ctx.close();
    const small = ["tile", "strip"].includes(got.layout) || (got.layout !== "banner" && got.stageH < 360);
    const problems = [];
    if (small && got.extras) problems.push(`Zusätze im Layout ${got.layout}`);
    if (!small) {
      if (!(got.extras && got.moon && got.nerd && got.bars)) problems.push(`nicht alle Zusätze sichtbar ${JSON.stringify([got.moon, got.nerd, got.bars])}`);
      if (!got.inside) problems.push("Zusätze außerhalb der Bühne");
      if (JSON.stringify(got.nerdText) !== JSON.stringify(wantNerd)) problems.push(`Nerd-Zeile ${JSON.stringify(got.nerdText)}`);
      if (got.barTexts.join("|") !== "Tag42 %|Jahr49 %") problems.push(`Balken ${got.barTexts.join("|")}`);
      if (!/^Vollmond · (9\d|100) %$/.test(got.moonText)) problems.push(`Mond „${got.moonText}“`);
    }
    if (!got.timeInside) problems.push("Zeit außerhalb der Bühne");
    if (got.wrapped) problems.push("Umbruch");
    if (got.vscroll > 0 || got.hscroll > 0) problems.push(`Scrollbalken (${got.hscroll}/${got.vscroll} px)`);
    problems.push(...errors(got, msgs));
    note(`/clock Zusätze ${width}×${height} (${got.layout})`, problems);
  }
  // 2) Binäruhr: 10:15:42 als BCD (1|0|1|5|4|2) und als Dualzahl (01010|001111|101010).
  const bcd = "01" + "0000" + "001" + "0101" + "100" + "0010";
  for (const [query, lamps, values] of [["?design=binary", bcd, "1,0,1,5,4,2"],
    ["?design=binary&bin=plain", "01010" + "001111" + "101010", "10,15,42"]]) {
    for (const [width, height] of STUDIO_VIEWPORTS) {
      const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, query });
      const got = await page.evaluate(extrasState);
      if ([390, 1920, 3840].includes(width) && height !== 200) await shot(page, `${query.includes("plain") ? "dual" : "bcd"}-${width}x${height}`);
      await ctx.close();
      note(`/clock ${query} ${width}×${height}`, [got.lamps === lamps ? "" : `Lämpchen ${got.lamps}`,
        got.values.join(",") === values ? "" : `Werte ${got.values}`, got.timeInside ? "" : "außerhalb der Bühne",
        got.vscroll > 0 || got.hscroll > 0 ? `Scrollbalken (${got.hscroll}/${got.vscroll} px)` : "", ...errors(got, msgs)].filter(Boolean));
    }
  }
  // 3) Ohne tai_utc: TAI und GPS „–“, nichts geraten. Zunehmende Sichel (16.8.2026) und Klick: Südhalbkugel.
  {
    const at = Date.parse("2026-08-16T10:00:00.500Z");
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1440, height: 900, query: "?show=moon,nerd", at });
    const before = await page.evaluate(extrasState);
    await shot(page, "sichel-nord");
    await page.click("#moon");
    await clock.run(250);
    const after = await page.evaluate(extrasState);
    const stored = await page.evaluate(() => localStorage.getItem("ntp-gui-clock-south"));
    await shot(page, "sichel-sued");
    await ctx.close();
    note("/clock Mond und Nerd ohne tai_utc", [before.nerdText[2] === "TAI –" && before.nerdText[3] === "GPS –" ? "" : `ohne TAI: ${before.nerdText}`,
      /^Zunehmende Sichel/.test(before.moonText) ? "" : `Mond „${before.moonText}“`,
      / 0 1 50 /.test(before.moonPath) ? "" : `Nord nicht rechts: ${before.moonPath}`,
      after.moonPressed === "true" && / 0 0 50 /.test(after.moonPath) ? "" : `Süd: ${after.moonPressed} ${after.moonPath}`,
      stored === "1" ? "" : `localStorage ${stored}`, ...errors(after, msgs)].filter(Boolean));
  }
  // 4) Nie Zusätze in Studio-, Kachel- und Banner-Voreinstellung, mit fun=0, im Streifen; Standard ohne show keine.
  for (const [name, query] of [["studio", "?p=studio&show=moon,nerd,progress"], ["tile", "?p=tile&show=moon,nerd,progress"],
    ["banner", "?p=banner&show=moon,nerd,progress"], ["fun0", "?fun=0&show=moon,nerd,progress"],
    ["strip", "?layout=strip&show=moon,nerd,progress"], ["kiosk", "?kiosk=1&show=moon,nerd,progress"],
    ["kiosk-profil", "?p=nerd&kiosk=1"], ["standard", ""]]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, query, reply: withTai(37) });
    await clock.run(1500);
    const got = await page.evaluate(extrasState);
    await ctx.close();
    note(`/clock keine Zusätze ${name}`, [got.extras ? "Zusätze sichtbar" : "", ...errors(got, msgs)].filter(Boolean));
  }
  // 4b) Profil mit eigener Auswahl (night: nur die Zeit) und show=moon: Die Auswahl des Profils bleibt, der Mond kommt dazu.
  {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 1080, query: "?p=night&show=moon" });
    const got = await page.evaluate(() => ({ show: document.documentElement.dataset.show || null,
      date: getComputedStyle(document.getElementById("local-date")).display, csp: window.__csp || [] }));
    const ex = await page.evaluate(extrasState);
    await ctx.close();
    note("/clock Profil night mit show=moon", [got.show === "time" ? "" : `data-show ${got.show}`,
      got.date === "none" ? "" : "Datum sichtbar", ex.moon ? "" : "Mond fehlt", ...errors(ex, msgs)].filter(Boolean));
  }
  // 4c) Quadratische Zifferblätter: TAI kommt erst mit der zweiten Antwort (die Nerd-Zeile bricht dann um) – die Zeit
  // wird sofort neu eingepasst, die Zusätze bleiben über dem Band (nicht erst zur nächsten Minute).
  for (const design of ["binary", "studio", "bahnhof"]) {
    for (const [width, height] of [[1920, 1080], [1280, 720]]) {
      let answers = 0;
      const late = (ms) => withTai(answers++ ? 37 : null)(ms);
      const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, reply: late,
        query: `?design=${design}&show=moon,nerd,progress` });
      await clock.run(6000);
      const got = await page.evaluate(extrasState);
      if (width === 1920) await shot(page, `${design}-zusaetze-${width}x${height}`);
      await ctx.close();
      note(`/clock ${design} mit Zusätzen ${width}×${height}`, [got.extras ? "" : "Zusätze fehlen",
        got.inside ? "" : "Zusätze unter dem Band", got.timeInside ? "" : "Zeit außerhalb der Bühne",
        /\(\+37 s\)/.test(got.nerdText.join(" ")) ? "" : `ohne TAI ${got.nerdText}`, ...errors(got, msgs)].filter(Boolean));
    }
  }
  // 4d) Banner mit Countdown unter der Uhr und Leiste der Weltzeit: niedrig (1920×200) ohne Zusätze, höher (2560×720)
  // mit Zusätzen in der rechten Spalte – kein Rasterfeld ohne Namen, alles in der Bühne. Mit Countdown und Weltzeit
  // zusammen reicht die Höhe dort nicht: Dann fallen die Zusätze weg (checkExtrasRoom), statt unter das Band zu ragen.
  for (const query of ["&until=2026-12-31T23:00", "&tz=Asia/Tokyo,America/New_York", "&until=2026-12-31T23:00&tz=Asia/Tokyo"]) {
    for (const [width, height] of [[1920, 200], [2560, 720]]) {
      const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, reply: withTai(37),
        query: `?layout=banner&show=moon,nerd,progress${query}` });
      await clock.run(1500);
      const got = await page.evaluate(extrasState);
      const cols = await page.evaluate(() => getComputedStyle(document.getElementById("clock-main")).gridTemplateColumns.split(" ").length);
      if (width === 2560) await shot(page, `banner${query.replace(/[^a-z]+/g, "-")}${width}x${height}`);
      await ctx.close();
      note(`/clock Banner Zusätze${query} ${width}×${height}`, [height < 360 && got.extras ? "Zusätze trotz Platzmangel" : "",
        height >= 360 && !got.extras && !(query.includes("until=") && query.includes("tz=")) ? "Zusätze fehlen" : "", got.extras && !got.inside ? "Zusätze außerhalb der Bühne" : "",
        got.timeInside ? "" : "Zeit außerhalb der Bühne", cols === 2 ? "" : `${cols} Rasterspalten`, ...errors(got, msgs)].filter(Boolean));
    }
  }
  // 4f) Banner 32:9 (3840×1080) mit allen Zusätzen: Zeit und Zusätze behalten ihren Abstand zum Rand wie ohne Zusätze
  // (die lange Nerd-Zeile bricht in ihrer Spalte um, statt das Raster über den Rand zu schieben).
  for (const design of ["wort", "digital", "nixie", "binary"]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 3840, height: 1080, reply: withTai(37),
      query: `?design=${design}&show=moon,nerd,progress&timer=5m` });
    await clock.run(1500);
    const got = await page.evaluate(() => {
      const stage = document.getElementById("clock-stage").getBoundingClientRect();
      const box = (el) => (el && !el.hidden && el.offsetWidth ? el.getBoundingClientRect() : null);
      const time = box(document.getElementById("face")) || box(document.getElementById("local-time"));
      const parts = [...document.querySelectorAll("#extras *")].filter((el) => el.offsetWidth > 0).map((el) => el.getBoundingClientRect());
      return { layout: document.getElementById("clock-stage").dataset.layout, extras: parts.length > 0,
        left: time ? time.left - stage.left : -1, right: parts.length ? stage.right - Math.max(...parts.map((r) => r.right)) : -1,
        hscroll: document.documentElement.scrollWidth - document.documentElement.clientWidth, csp: window.__csp || [] };
    });
    if (design === "wort") await shot(page, `banner-zusaetze-${design}-3840x1080`);
    await ctx.close();
    note(`/clock Banner 3840×1080 ${design} mit Zusätzen: Rand`, [got.layout === "banner" ? "" : `Layout ${got.layout}`,
      got.extras ? "" : "Zusätze fehlen", got.left >= 24 ? "" : `Zeit ${Math.round(got.left)} px vom linken Rand`,
      got.right >= 24 ? "" : `Zusätze ${Math.round(got.right)} px vom rechten Rand`, got.hscroll > 0 ? `Überbreite ${got.hscroll} px` : "",
      ...errors(got, msgs)].filter(Boolean));
  }
  // 4e) Design tc mit Zone des Servers (UTC) auf einem Gerät in Kiritimati (UTC+14): Am 23.11. um 12:30 UTC ist dort schon
  // der 24.11. – Tag im Jahr, ISO-Datum und Tagesbalken folgen dem angezeigten Datum (Montag, 23.11.).
  {
    const at = Date.parse("2026-11-23T12:30:00.500Z");
    const reply = (ms) => ({ ...withTai(37)(ms), zone: "Etc/UTC" });
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 1080, zone: "Pacific/Kiritimati", at, reply,
      query: "?design=tc&show=nerd,progress&bars=day" });
    const got = await page.evaluate(extrasState);
    const date = await page.evaluate(() => document.getElementById("local-date").textContent);
    await ctx.close();
    note("/clock tc Zusätze in der Zone der Anzeige", [/23\. November/.test(date) ? "" : `Datum ${date}`,
      got.nerdText.includes("Tag 327") ? "" : `Tag ${got.nerdText}`, got.nerdText.includes("ISO 2026-W48-1") ? "" : `ISO ${got.nerdText}`,
      got.barTexts.join("|") === "Tag52 %" ? "" : `Balken ${got.barTexts}`, ...errors(got, msgs)].filter(Boolean));
  }
  // 5) Eieruhr-Balken: 10 min, nach 2,5 min 25 %.
  {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1440, height: 900, query: "?timer=10m&show=progress" });
    await page.keyboard.press("Space");
    await clock.run(151000);
    const got = await page.evaluate(extrasState);
    await shot(page, "timer-balken");
    await ctx.close();
    note("/clock Balken der Eieruhr", [got.barTexts.join("|") === "Tag42 %|Timer25 %" ? "" : `Balken ${got.barTexts.join("|")}`,
      ...errors(got, msgs)].filter(Boolean));
  }
  // 6) Echtzeit: Binäruhr mit allen Zusätzen ohne Long Tasks und ohne Bildschleife.
  {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    await ctx.addInitScript(() => {
      window.__long = [];
      window.__raf = 0;
      const raf = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (cb) => { window.__raf += 1; return raf(cb); };
      try { new PerformanceObserver((list) => window.__long.push(...list.getEntries().map((e) => e.duration))).observe({ type: "longtask", buffered: true }); } catch (e) { /* egal */ }
    });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/clock?design=binary&show=moon,nerd,progress`, { waitUntil: "load" });
    await page.waitForTimeout(1500);
    // Ruhebetrieb (Konzept, Akzeptanz A): gezählt wird nach dem Start, nicht das erste Laden der Seite.
    const rafStart = await page.evaluate(() => { window.__long = []; return window.__raf; });
    await page.waitForTimeout(6000);
    const got = await page.evaluate(() => ({ long: window.__long, raf: window.__raf }));
    await ctx.close();
    note("/clock C2 Leistung", [got.long.length ? `Long Tasks ${got.long.map(Math.round)}` : "",
      got.raf - rafStart > 2 ? `Bildschleife (${got.raf - rafStart} Bilder)` : ""].filter(Boolean));
  }
  return { found, lines };
}

// Studiouhr C3 (clockFunChecks, TOUR_FUN_ONLY=1): Spiel „Tippe auf :00“, Zeitzeichen und Ostereier. Mit angehaltener
// Playwright-Uhr: Osterei 13:37 auf den neun Flächen (im Bild, in Kachel und Streifen nie, keine Scrollbalken; Streifen
// auch fest per ?layout=strip und per Taste L bei 1920×1080), Design tc mit Zone des Servers (Ei zu deren 13:37), Neujahr
// mit CSS-Konfetti (bei „weniger Bewegung“ nur Text), Konami-Code (Konfetti, Binäruhr bis zum Neuladen, nicht gemerkt).
// Nie ein Ei oder Konfetti mit eggs=0, fun=0, in studio, tile, banner, im Kiosk (auch aus einem Profil), mit lock=1 und
// in OBS. Panel „Spiel“ bei 390 und 1920 px (Tipp mit Maus und Taste, Ergebnis, Bestwert im localStorage, auch bei
// gesperrtem Speicher ehrlich; langer Druck mit Maus und Finger ergibt genau eine Wertung), Zeitzeichen-Knöpfe nur mit
// Spielereien. Echtzeit: keine Long Tasks, keine Bildschleife.
function funState() {
  const root = document.documentElement;
  const visible = (id) => { const el = document.getElementById(id); if (!el) return false; const r = el.getBoundingClientRect();
    return !el.hidden && getComputedStyle(el).display !== "none" && r.width > 0 && r.height > 0; };
  const egg = document.getElementById("leap-egg");
  const er = egg.getBoundingClientRect();
  const confetti = document.getElementById("confetti");
  const piece = confetti.querySelector("i");
  return {
    egg: visible("leap-egg"), eggText: egg.textContent, eggKind: egg.dataset.egg || "",
    eggInside: er.left >= -1 && er.right <= innerWidth + 1 && er.top >= -1 && er.bottom <= innerHeight + 1,
    confetti: visible("confetti"), pieces: confetti.childElementCount, anim: piece ? getComputedStyle(piece).animationName : "",
    design: root.dataset.design, layout: document.getElementById("clock-stage").dataset.layout,
    compact: document.body.classList.contains("is-compact"),
    game: !document.getElementById("mode-game").hidden, pips: !document.getElementById("tone-pips-hour").hidden,
    result: document.getElementById("game-result").textContent, detail: document.getElementById("game-detail").textContent,
    best: document.getElementById("game-best").textContent,
    vscroll: root.scrollHeight - root.clientHeight, hscroll: root.scrollWidth - root.clientWidth, csp: window.__csp || [],
  };
}

async function clockFunChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    lines.push(`${label}: ${problems.length ? problems.join("; ") : "ok"}`);
    if (problems.length) found.push(`${label}: ${problems.join("; ")}`);
  };
  const errors = (got, msgs) => (got.csp.length || msgs.length ? [`Fehler ${JSON.stringify([...got.csp, ...msgs])}`] : []);
  const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/clock-c3-${name}.png` }); };
  const LEET = Date.parse("2026-11-23T12:37:10.500Z");      // 13:37:10 in Berlin
  const NEWYEAR = Date.parse("2026-12-31T23:00:03.500Z");   // 1.1.2027 00:00:03 in Berlin
  const KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a"];
  // 1) 13:37 auf den neun Flächen.
  for (const [width, height] of STUDIO_VIEWPORTS) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width, height, at: LEET });
    const got = await page.evaluate(funState);
    if ([390, 1920, 3840].includes(width)) await shot(page, `leet-${width}x${height}`);
    await ctx.close();
    // Kachel, Streifen, Bühnen ohne Kopfzeile (is-compact) und Fenster bis 320 px Höhe (clock.css): nur die Zeit, kein Ei.
    const small = ["tile", "strip"].includes(got.layout) || got.compact || height <= 320;
    note(`/clock 13:37 ${width}×${height} (${got.layout})`, [
      small && got.egg ? "Ei in Kachel/Streifen" : "", !small && !got.egg ? "Ei fehlt" : "",
      !small && got.eggText !== "13:37 – leet." ? `Text „${got.eggText}“` : "", got.egg && !got.eggInside ? "Ei außerhalb" : "",
      got.confetti ? "Konfetti ohne Anlass" : "", got.vscroll > 0 || got.hscroll > 0 ? `Scrollbalken (${got.hscroll}/${got.vscroll} px)` : "",
      ...errors(got, msgs)].filter(Boolean));
  }
  // 1b) Streifen bei 1920×1080: fest (?layout=strip, auch nach dem Konami-Code) und per Taste L – nie ein Ei.
  {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 1080, query: "?layout=strip", at: LEET });
    const fixed = await page.evaluate(funState);
    for (const key of KONAMI) await page.keyboard.press(key);
    await page.waitForTimeout(400);
    const after = await page.evaluate(funState);
    await shot(page, "strip-1920x1080");
    await ctx.close();
    note("/clock 13:37 ?layout=strip 1920×1080", [fixed.layout === "strip" ? "" : `Layout ${fixed.layout}`,
      fixed.egg ? `Ei „${fixed.eggText}“` : "", after.egg ? `Ei nach Konami „${after.eggText}“` : "",
      after.confetti || after.pieces ? "Konfetti" : "", ...errors(after, msgs)].filter(Boolean));
  }
  {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, at: LEET });
    const seen = [];
    for (let i = 0; i < 6; i += 1) {
      const got = await page.evaluate(funState);
      seen.push([got.layout, got.egg]);
      await page.keyboard.press("l");
      await clock.run(200);
    }
    const last = await page.evaluate(funState);
    await ctx.close();
    const wrong = seen.filter(([layout, egg]) => egg === ["tile", "strip"].includes(layout));
    note("/clock 13:37 Taste L", [seen.some(([layout]) => layout === "strip") ? "" : `kein Streifen ${JSON.stringify(seen)}`,
      wrong.length ? `Ei falsch ${JSON.stringify(seen)}` : "", ...errors(last, msgs)].filter(Boolean));
  }
  // 1c) Design tc, Gerät in UTC, Server in Berlin: Das Ei kommt zu 13:37 der Anzeige (Berlin), nicht eine Stunde später.
  {
    const reply = (ms) => ({ t1: ms / 1000, t2: ms / 1000, synchronised: true, running: true, level: "good", accuracy: 0.0004,
      stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS", source: null, public: true, zone: "Europe/Berlin" });
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 1080, query: "?design=tc", at: LEET,
      zone: "UTC", reply });
    const got = await page.evaluate(funState);
    await ctx.close();
    note("/clock 13:37 tc mit Zone des Servers", [got.design === "tc" ? "" : `Design ${got.design}`,
      got.egg && got.eggText === "13:37 – leet." ? "" : `Ei „${got.egg ? got.eggText : ""}“`, ...errors(got, msgs)].filter(Boolean));
  }
  // 2) Neujahr: Konfetti per CSS, bei „weniger Bewegung“ nur Text.
  for (const [width, height, reduced] of [[1920, 1080, false], [390, 844, false], [1920, 1080, true]]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width, height, at: NEWYEAR, reduced });
    await page.waitForTimeout(900);
    const got = await page.evaluate(funState);
    await shot(page, `neujahr-${width}x${height}${reduced ? "-reduced" : ""}`);
    await ctx.close();
    note(`/clock Neujahr ${width}×${height}${reduced ? " weniger Bewegung" : ""}`, [
      got.eggText === "Frohes neues Jahr!" ? "" : `Text „${got.eggText}“`,
      reduced ? (got.confetti || got.pieces ? "Konfetti trotz weniger Bewegung" : "")
        : (got.confetti && got.pieces === 24 && /clock-confetti-fall/.test(got.anim) ? "" : `Konfetti ${JSON.stringify([got.confetti, got.pieces, got.anim])}`),
      got.vscroll > 0 || got.hscroll > 0 ? `Scrollbalken (${got.hscroll}/${got.vscroll} px)` : "", ...errors(got, msgs)].filter(Boolean));
  }
  // 3) Konami-Code: Konfetti und Binäruhr, nicht gemerkt; danach (10 s) wieder ohne Ei.
  {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080 });
    for (const key of KONAMI) await page.keyboard.press(key);
    await page.waitForTimeout(400);
    const got = await page.evaluate(funState);
    const said = await page.evaluate(() => document.getElementById("clock-live").textContent);
    const stored = await page.evaluate(() => localStorage.getItem("ntp-gui-clock-design"));
    await shot(page, "konami");
    await clock.run(11000);
    const later = await page.evaluate(funState);
    await ctx.close();
    note("/clock Konami-Code", [got.eggKind === "konami" ? "" : `Ei ${got.eggKind} „${got.eggText}“`,
      got.design === "binary" ? "" : `Design ${got.design}`, got.confetti ? "" : "kein Konfetti",
      said ? `A hat angesagt: ${said}` : "", stored ? `Design gemerkt: ${stored}` : "",
      later.egg && later.eggKind === "konami" ? "Konami-Ei bleibt stehen" : "", ...errors(got, msgs)].filter(Boolean));
  }
  // 4) Nie ein Ei oder Konfetti: eggs=0, fun=0, Voreinstellungen, Kiosk (auch aus dem Profil), lock=1, OBS.
  for (const [name, query, init] of [["eggs0", "?eggs=0"], ["fun0", "?fun=0"], ["studio", "?p=studio"], ["tile", "?p=tile"],
    ["banner", "?p=banner"], ["kiosk", "?kiosk=1"], ["kiosk-profil", "?p=nerd&kiosk=1"], ["lock", "?lock=1"],
    ["obs", "", () => { window.obsstudio = { pluginVersion: "30.0.0" }; }], ["studio-eggs1", "?p=studio&eggs=1&fun=1"]]) {
    for (const at of [LEET, NEWYEAR]) {
      const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 1080, query, at, init });
      for (const key of KONAMI) await page.keyboard.press(key);
      await page.waitForTimeout(400);
      const got = await page.evaluate(funState);
      await ctx.close();
      note(`/clock kein Ei ${name} ${at === LEET ? "13:37" : "Neujahr"}`, [got.egg ? `Ei „${got.eggText}“` : "",
        got.confetti || got.pieces ? "Konfetti" : "", got.design === "binary" && !query.includes("binary") ? "Konami wirkt" : "",
        // eggs=0 schaltet nur die Ostereier ab – Spiel und Zeitzeichen bleiben dort.
        got.game && name !== "eggs0" ? "Knopf Spiel" : "", got.pips && name !== "eggs0" ? "Zeitzeichen-Knöpfe" : "",
        name === "eggs0" && !(got.game && got.pips) ? "eggs=0 nimmt Spiel oder Zeitzeichen weg" : "", ...errors(got, msgs)].filter(Boolean));
    }
  }
  // 4g) Profil-Abruf fällt aus (503): ?p=studio zeigt vorsichtshalber weder Ei noch Konfetti noch Timer, Spiel und Nacht.
  for (const name of ["studio", "tile", "banner", "eigenes"]) {
    for (const at of [LEET, NEWYEAR]) {
      const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 1080, query: `?p=${name}`, at,
        profile: () => "fail" });
      await page.waitForTimeout(400);
      const got = await page.evaluate(funState);
      const btns = await page.evaluate(() => ["mode-timer", "mode-night", "mode-game"].filter((id) => !document.getElementById(id).hidden));
      await ctx.close();
      const rest = msgs.filter((m) => !/status of 503/.test(m));
      note(`/clock Profil ${name} nicht geladen ${at === LEET ? "13:37" : "Neujahr"}`, [got.egg ? `Ei „${got.eggText}“` : "",
        got.confetti || got.pieces ? "Konfetti" : "", btns.length ? `Knöpfe ${btns}` : "", ...errors(got, rest)].filter(Boolean));
    }
  }
  // 4h) Prüfbild ?test=sync zu Neujahr und um 13:37: kein Ei und kein Konfetti über der Blitzfläche.
  for (const at of [LEET, NEWYEAR]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, query: "?test=sync", at });
    await clock.run(1500);
    const got = await page.evaluate(funState);
    const test = await page.evaluate(() => !document.getElementById("sync-test").hidden);
    await ctx.close();
    note(`/clock Prüfbild ${at === LEET ? "13:37" : "Neujahr"}`, [test ? "" : "Prüfbild fehlt", got.egg ? `Ei „${got.eggText}“` : "",
      got.confetti || got.pieces ? "Konfetti" : "", ...errors(got, msgs)].filter(Boolean));
  }
  // 5) Panel „Spiel“: Tipp mit Maus und Taste, Bestwert im localStorage; Zeitzeichen-Knöpfe im Panel Ton.
  for (const [width, height] of [[390, 844], [1920, 1080], [768, 1024]]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height });
    const before = await page.evaluate(funState);
    await page.click("#mode-game");
    await clock.run(500);
    await page.click("#game-tap");
    await clock.run(300);
    const first = await page.evaluate(funState);
    await page.click("#game-minute");
    await page.focus("#game-tap");
    await page.keyboard.press("Enter");
    await clock.run(300);
    const second = await page.evaluate(funState);
    const stored = await page.evaluate(() => localStorage.getItem("ntp-gui-clock-tap"));
    const sizes = await page.evaluate(() => [...document.querySelectorAll("#game-panel button:not(.info)")].filter((b) => b.offsetParent)
      .map((b) => { const r = b.getBoundingClientRect(); return Math.min(r.width, r.height); }));
    await shot(page, `spiel-${width}x${height}`);
    await page.click("#mode-game");
    await page.click("#mode-tone");
    await clock.run(300);
    await shot(page, `ton-${width}x${height}`);
    const tone = await page.evaluate(() => ({ pips: !document.getElementById("tone-pips-hour").hidden,
      line: document.getElementById("tone-pips-line").textContent }));
    await ctx.close();
    const want = /^(genau drauf|[0-9.,]+ (ms|s|min [0-9]+ s) zu (früh|spät))\. /;
    note(`/clock Spiel ${width}×${height}`, [before.game ? "" : "Knopf Spiel fehlt", want.test(first.result) ? "" : `Ergebnis „${first.result}“`,
      /Messgenauigkeit: Abgleich ± .* · Server ± .* · Bild ± /.test(first.detail) ? "" : `Genauigkeit „${first.detail}“`,
      want.test(second.result) ? "" : `Taste: „${second.result}“`, /^Bestwert \(volle Minute\): /.test(second.best) ? "" : `Bestwert „${second.best}“`,
      stored && JSON.parse(stored).second >= 0 && JSON.parse(stored).minute >= 0 ? "" : `localStorage ${stored}`,
      sizes.every((v) => v >= 24) ? "" : `Tippfläche ${Math.min(...sizes)} px`, tone.pips ? "" : "Zeitzeichen fehlen",
      /keine Referenz/.test(tone.line) ? "" : "Hinweis Referenz fehlt",
      second.hscroll > 0 ? `Überbreite ${second.hscroll} px` : "", ...errors(second, msgs)].filter(Boolean));
  }
  // 5a) Langer Druck (700 ms) mit Maus und Finger: genau eine Wertung – der click beim Loslassen zählt nicht noch einmal.
  for (const how of ["mouse", "touch"]) {
    const touch = how === "touch";
    const { ctx, page, msgs, clock } = await openPausedClock(browser, touch ? { width: 390, height: 844, touch: true }
      : { width: 1920, height: 1080 });
    await page.click("#mode-game");
    await clock.run(500);
    await page.evaluate(() => {
      window.__results = [];
      new MutationObserver(() => window.__results.push(document.getElementById("game-result").textContent))
        .observe(document.getElementById("game-result"), { childList: true, characterData: true, subtree: true });
    });
    await page.locator("#game-tap").scrollIntoViewIfNeeded();
    const box = await page.locator("#game-tap").boundingBox();
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    let cdp = null;
    if (touch) {
      cdp = await ctx.newCDPSession(page);
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
    } else {
      await page.mouse.move(x, y);
      await page.mouse.down();
    }
    await clock.run(700);
    if (touch) await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    else await page.mouse.up();
    await clock.run(300);
    const results = await page.evaluate(() => window.__results.filter(Boolean));
    // Ein click ohne Zeiger (Screenreader: element.click(), detail 0) zählt selbst – genau einmal.
    await clock.run(1000);
    await page.evaluate(() => document.getElementById("game-tap").click());
    await clock.run(300);
    const reader = await page.evaluate(() => window.__results.filter(Boolean).length);
    const got = await page.evaluate(funState);
    await ctx.close();
    note(`/clock Spiel langer Druck ${how === "touch" ? "Finger" : "Maus"}`, [results.length === 1 ? "" : `${results.length} Wertungen ${JSON.stringify(results)}`,
      reader === results.length + 1 ? "" : `Screenreader-Klick: ${reader - results.length} Wertungen`, ...errors(got, msgs)].filter(Boolean));
  }
  // 5b) Gesperrter Speicher: Bestwert gilt bis zum Neuladen, ehrlich gesagt; kein Fehler.
  {
    const init = () => { const deny = () => { throw new DOMException("gesperrt", "SecurityError"); };
      Object.defineProperty(window, "localStorage", { get: deny, configurable: true }); };
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1440, height: 900, init });
    await page.click("#mode-game");
    await page.click("#game-tap");
    await clock.run(300);
    const got = await page.evaluate(funState);
    await ctx.close();
    note("/clock Spiel ohne Speicher", [/nur bis zum Neuladen/.test(got.result) ? "" : `Ergebnis „${got.result}“`,
      ...errors(got, msgs)].filter(Boolean));
  }
  // 6) Echtzeit: Konami (Konfetti) und offenes Spiel ohne Long Tasks und ohne Bildschleife.
  {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    await ctx.addInitScript(() => {
      window.__long = [];
      window.__raf = 0;
      const raf = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (cb) => { window.__raf += 1; return raf(cb); };
      try { new PerformanceObserver((list) => window.__long.push(...list.getEntries().map((e) => e.duration))).observe({ type: "longtask", buffered: true }); } catch (e) { /* egal */ }
    });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/clock`, { waitUntil: "load" });
    await page.waitForTimeout(1500);
    const rafStart = await page.evaluate(() => { window.__long = []; return window.__raf; });
    for (const key of KONAMI) await page.keyboard.press(key);
    await page.click("#mode-game");
    await page.waitForTimeout(6000);
    const got = await page.evaluate(() => ({ long: window.__long, raf: window.__raf,
      confetti: document.getElementById("confetti").childElementCount }));
    await page.waitForTimeout(3500);
    const gone = await page.evaluate(() => document.getElementById("confetti").hidden && !document.getElementById("confetti").childElementCount);
    await ctx.close();
    note("/clock C3 Leistung", [got.long.length ? `Long Tasks ${got.long.map(Math.round)}` : "",
      got.raf - rafStart > 3 ? `Bildschleife (${got.raf - rafStart} Bilder)` : "", got.confetti ? "" : "Konfetti fehlte",
      gone ? "" : "Konfetti bleibt liegen"].filter(Boolean));
  }
  return { found, lines };
}

// Nachbesserungen der Layout-Engine: ?bg=black mit gespeichertem hellem Thema (Schrift ≥ 4,5:1 auf Schwarz, Schema
// dunkel, Hell/Dunkel-Knopf gesperrt), Screenreader-Text bei ?h12=1 (Zifferblatt „10:15 AM“, Textzeit mit Leerzeichen
// vor AM), automatischer Streifen in sehr niedrigen Fenstern ohne Kopfzeile und Band (die Zeit bekommt die ganze Höhe).
// Studiouhr B1 (clockTimecodeChecks, TOUR_TC_ONLY=1): Design tc aus docs/konzept/studiouhr.md (Akzeptanz B). Mit
// angehaltener Playwright-Uhr (page.clock) und gemocktem /api/v1/time steht die Serverzeit auf 10:15:42,5. Auf allen neun
// Flächen: Kopfzeile „Anzeige-Timecode – nicht genlocked“ sichtbar und lesbar, Zehntel als Standard, Zeile in der Bühne,
// kein Umbruch, kein Scrollbalken, keine CSP-Verstöße. Dazu bei 1920×1080: Frames nur mit sub=frames (laufen mit der
// Bildschleife weiter), Drop-Frame mit „;“, die FF-Stelle grau bei Schranke über ½ Frame (mit Text), Zehntel grau über
// 50 ms, Feinstelle weg über maxerr, Taste T, weniger Bewegung (höchstens Zehntel), E-Ink ohne Feinstelle und Sekunden,
// grob gerundete Zeitgeber (performance.now() in 100-ms-Stufen) grau mit Hinweis, Zeitzone des Servers, ⓘ, Rotlicht.
// Die Feinstelle wird je Bild gezeichnet, das letzte Bild liegt bis zu 16 ms vor dem Prüfzeitpunkt: Wo der Prüfzeitpunkt
// genau auf einem Wechsel liegt (Zehntel bei ,5), gilt auch der Wert davor.
// Dazu kleine Flächen (Kachel 240×135, Streifen 1920×100 und 1920×60, schmales Fenster): Kopfzeile bleibt im Bild
// (bricht um bzw. steht im Streifen neben der Zeit), die Ziffern sind größer als die Kopfzeile; wo die Zeile unter der
// Zeit keinen Platz hat, steht der Grund für eine graue Feinstelle kurz in der Kopfzeile; ausgeblendete Feinstelle:
// Sekunden aus der Wanduhr (Drop-Frame früh am Tag) und die Zeit rückt nach 3 s zur Mitte; Taste T mit ?cd=main, ohne
// Sekunden und mit ?sub=off; Datum und Nebenzeile (Taste U) in der Zone des Servers.
function tcState() {
  const root = document.documentElement;
  const face = document.getElementById("face");
  const q = (sel) => face.querySelector(sel);
  const row = q(".tc-row");
  if (!row) return { missing: true, design: root.dataset.design, csp: window.__csp || [] };
  const vis = (n) => {
    if (!n) return false;
    const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };
  const lum = (color) => {
    const [r, g, b] = color.match(/[\d.]+/g).slice(0, 3).map((v) => {
      const c = Number(v) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (a, b) => { const x = lum(a); const y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const bg = getComputedStyle(document.body).backgroundColor;
  const fine = q(".tc-fine");
  const label = q(".tc-label");
  const note = q(".tc-note");
  const stage = document.getElementById("clock-stage").getBoundingClientRect();
  const inStage = (n) => { const r = n.getBoundingClientRect();
    return r.left >= stage.left - 1 && r.right <= stage.right + 1 && r.top >= stage.top - 1 && r.bottom <= stage.bottom + 1; };
  const hint = document.getElementById("clock-hint");
  const popover = document.querySelector(".clock-popover");
  const head = q(".tc-head");
  const why = q(".tc-why");
  const headBox = head.getBoundingClientRect();
  const shown = [...row.querySelectorAll(".tc-d, .tc-sep")].filter(vis).map((n) => n.getBoundingClientRect());
  const shownCx = shown.length ? (Math.min(...shown.map((r) => r.left)) + Math.max(...shown.map((r) => r.right))) / 2 : NaN;
  return {
    headIn: inStage(head) && headBox.left >= 0 && headBox.right <= root.clientWidth + 0.5, headHeight: headBox.height,
    rowSize: parseFloat(getComputedStyle(row).fontSize), rowHeight: row.getBoundingClientRect().height,
    why: why.textContent, whyShown: vis(why),
    offCentre: Math.abs(shownCx - (headBox.left + headBox.right) / 2),
    date: document.getElementById("local-date").textContent, utcLabel: document.getElementById("utc-label").textContent,
    utcTime: document.getElementById("utc-time").textContent, dataTime: face.dataset.time || "",
    cdTime: document.getElementById("cd-time").textContent,
    design: root.dataset.design, role: face.getAttribute("role"), aria: face.getAttribute("aria-label") || "",
    text: [...row.querySelectorAll(".tc-d, .tc-sep")].filter(vis).map((n) => n.textContent).join(""),
    label: label.textContent, labelShown: vis(label) && inStage(label), labelSize: parseFloat(getComputedStyle(label).fontSize),
    level: fine.dataset.level || "", mode: fine.dataset.mode || "", fineShown: vis(fine),
    grey: getComputedStyle(fine).color !== getComputedStyle(q(".tc-d")).color,
    fineContrast: contrast(getComputedStyle(fine).color, bg),
    note: note.textContent, noteShown: vis(note), noteSize: parseFloat(getComputedStyle(note).fontSize),
    rowIn: inStage(row), wrapped: row.getBoundingClientRect().height > parseFloat(getComputedStyle(row).fontSize) * 1.6,
    info: vis(q(".tc-head .info")), hint: hint.hidden ? "" : hint.textContent,
    popover: popover ? popover.textContent : "", mainLabel: getComputedStyle(document.getElementById("local-label")).display,
    sync: root.dataset.sync || "", layout: document.getElementById("clock-stage").dataset.layout || "",
    overflow: root.scrollWidth - root.clientWidth, vscroll: root.scrollHeight - root.clientHeight, csp: window.__csp || [],
  };
}

async function clockTimecodeChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    const list = problems.filter(Boolean);
    lines.push(`${label}: ${list.length ? list.join("; ") : "ok"}`);
    if (list.length) found.push(`${label}: ${list.join("; ")}`);
  };
  const reply = (extra = {}) => (ms) => ({ t1: ms / 1000, t2: ms / 1000, synchronised: true, running: true, level: "good",
    accuracy: 0.0004, stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS", source: null, public: true,
    zone: "Europe/Berlin", ...extra });
  const errors = (got, msgs) => (got.csp.length || msgs.length ? `Fehler ${JSON.stringify([...got.csp, ...msgs])}` : "");
  const LABEL = "Anzeige-Timecode – nicht genlocked";

  // Alle Flächen: Standard (Zehntel) und Frames bei 25 fps.
  for (const [width, height] of STUDIO_VIEWPORTS) {
    for (const [query, text, mode] of [["?design=tc", /^10:15:42,[45]$/, "tenths"], ["?design=tc&sub=frames", /^10:15:42:12$/, "frames"]]) {
      const { ctx, page, msgs } = await openPausedClock(browser, { width, height, query, reply: reply() });
      const got = await page.evaluate(tcState);
      await ctx.close();
      // Streifen, Kachel und sehr niedrige Flächen zeigen nur Kopfzeile und Zeit.
      const small = ["strip", "tile"].includes(got.layout) || height <= 320;
      note(`/clock Timecode ${width}×${height} ${query} [${got.layout || "?"}]`, got.missing ? [`Design ${got.design} ohne Timecode-Zeile`] : [
        got.design === "tc" && got.role === "group" ? "" : `Design ${got.design}, role ${got.role}`,
        text.test(got.text) ? "" : `zeigt „${got.text}“ statt ${text}`,
        got.mode === mode && got.level === "sure" && got.fineShown && !got.grey ? "" : `Feinstelle ${got.mode}/${got.level}, sichtbar ${got.fineShown}, grau ${got.grey}`,
        got.label === LABEL && got.labelShown && got.headIn ? "" : `Kopfzeile „${got.label}“ sichtbar ${got.labelShown}, im Bild ${got.headIn}`,
        got.labelSize >= 11.5 ? "" : `Kopfzeile nur ${got.labelSize.toFixed(1)} px`,
        got.rowSize >= 2 * got.labelSize ? "" : `Ziffern nur ${got.rowSize.toFixed(1)} px bei Kopfzeile ${got.labelSize.toFixed(1)} px`,
        got.why === "" ? "" : `Grund „${got.why}“ ohne graue Feinstelle`,
        small || (got.noteShown && got.noteSize >= 11.5 && /^25 fps · (Zehntel|Frames)$/.test(got.note)) ? "" : `Zeile darunter „${got.note}“ (${got.noteSize} px, sichtbar ${got.noteShown})`,
        got.aria === `${LABEL}: 10:15 Uhr` ? "" : `aria-label „${got.aria}“`,
        got.mainLabel === "none" ? "" : "„Ortszeit“ über dem Timecode",
        got.rowIn ? "" : "Zeile außerhalb der Bühne", got.wrapped ? "Umbruch" : "",
        got.overflow > 0 || got.vscroll > 0 ? `Scrollbalken (${got.overflow}/${got.vscroll} px)` : "",
        got.sync === "ok" ? "" : `data-sync ${got.sync}`, errors(got, msgs)]);
    }
  }

  const single = async (query, opts, act) => {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, query, reply: reply(), ...opts });
    const out = act ? await act(page, clock) : null;
    const got = await page.evaluate(tcState);
    await ctx.close();
    return { got, msgs, out };
  };
  // Die Bildschleife zählt weiter: nach 250 ms Frame 18 (10:15:42,75), die Zehntel stehen auf 7.
  for (const [query, want] of [["?design=tc&sub=frames", /^10:15:42:18$/], ["?design=tc", /^10:15:42,7$/], ["?design=tc&fps=50&sub=frames", /^10:15:42:3[67]$/]]) {
    const { got, msgs } = await single(query, {}, async (page, clock) => { await clock.run(250); });
    note(`/clock Timecode läuft ${query}`, [want.test(got.text) ? "" : `zeigt „${got.text}“ statt ${want}`, errors(got, msgs)]);
  }
  // Drop-Frame: Trennzeichen „;“, der Wert stimmt mit der reinen Funktion überein (Tageszeit 10:15:42,5).
  for (const fps of ["29.97", "59.94"]) {
    const { got, msgs, out } = await single(`?design=tc&sub=frames&fps=${fps}`, {}, async (page) => page.evaluate(async (rate) => {
      const tc = await import("/static/js/clocktc.js");
      const tod = ((10 * 60 + 15) * 60 + 42) * 1000 + 500;
      return [tod, tod - 16].map((ms) => tc.tcView(ms, rate, "frames").text);
    }, fps));
    note(`/clock Timecode Drop-Frame ${fps}`, [out.includes(got.text) && /^10:15:4[12];\d\d$/.test(got.text) ? "" : `zeigt „${got.text}“ statt „${out[0]}“`,
      got.note.startsWith(`${fps.replace(".", ",")} fps Drop-Frame · Frames`) ? "" : `Zeile „${got.note}“`, errors(got, msgs)]);
  }
  // Fehlerschranke: FF grau über ½ Frame, Zehntel grau über 50 ms, Feinstelle weg über maxerr – immer mit Text.
  for (const [name, query, accuracy, want] of [
    ["Frames, Schranke ≈ 46 ms", "?design=tc&sub=frames", 0.03, { level: "unsure", grey: true, shown: true, note: /Frames unsicher: Anzeige ± 4\d ms, ein halbes Frame sind 20 ms$/, text: /^10:15:42:\d\d$/ }],
    ["Frames 50 fps, Schranke ≈ 16 ms", "?design=tc&sub=frames&fps=50", 0.0004, { level: "unsure", grey: true, shown: true, note: /Frames unsicher: Anzeige ± 1\d ms, ein halbes Frame sind 10 ms$/, text: /^10:15:42:\d\d$/ }],
    ["Zehntel, Schranke ≈ 46 ms", "?design=tc", 0.03, { level: "sure", grey: false, shown: true, note: /^25 fps · Zehntel$/, text: /^10:15:42,[45]$/ }],
    ["Zehntel, Schranke ≈ 76 ms", "?design=tc", 0.06, { level: "unsure", grey: true, shown: true, note: /Zehntel unsicher: Anzeige ± 7\d ms, tragfähig bis 50 ms$/, text: /^10:15:42,[45]$/ }],
    ["Schranke über maxerr", "?design=tc&sub=frames", 0.6, { level: "off", shown: false, note: /Feinstelle aus: Anzeige unsicher$/, text: /^10:15:42$/ }],
    ["maxerr=20", "?design=tc&maxerr=20", 0.01, { level: "off", shown: false, note: /Feinstelle aus: Anzeige unsicher$/, text: /^10:15:42$/ }],
  ]) {
    const { got, msgs } = await single(query, { reply: reply({ accuracy }) });
    note(`/clock Timecode ${name}`, [got.level === want.level ? "" : `Feinstelle ${got.level} statt ${want.level}`,
      got.fineShown === want.shown ? "" : `Feinstelle sichtbar ${got.fineShown}`,
      want.grey === undefined || got.grey === want.grey ? "" : `grau ${got.grey}`,
      want.grey && got.fineContrast < 3 ? `graue Feinstelle nur ${got.fineContrast.toFixed(2)}:1` : "",
      want.note.test(got.note) ? "" : `Zeile „${got.note}“`, want.text.test(got.text) ? "" : `zeigt „${got.text}“`,
      got.label === LABEL && got.labelShown ? "" : "Kopfzeile fehlt", errors(got, msgs)]);
  }
  // Rotlicht: graue Feinstelle bleibt lesbar (≥ 3:1).
  {
    const { got, msgs } = await single("?design=tc&sub=frames", { reply: reply({ accuracy: 0.03 }), red: true });
    note("/clock Timecode Rotlicht grau", [got.level === "unsure" && got.grey ? "" : `Feinstelle ${got.level}, grau ${got.grey}`,
      got.fineContrast >= 3 ? "" : `nur ${got.fineContrast.toFixed(2)}:1`, errors(got, msgs)]);
  }
  // Taste T: Zehntel → Frames → Zehntel, jeweils mit Hinweis.
  {
    const { got, msgs, out } = await single("?design=tc", {}, async (page, clock) => {
      await page.keyboard.press("t");
      await clock.run(250);
      const frames = await page.evaluate(tcState);
      await page.keyboard.press("t");
      await clock.run(250);
      return frames;
    });
    note("/clock Timecode Taste T", [out.mode === "frames" && /^10:15:42:\d\d$/.test(out.text) ? "" : `nach T ${out.mode} „${out.text}“`,
      out.hint === "Timecode: Frames (nicht genlocked)" ? "" : `Hinweis „${out.hint}“`,
      got.mode === "tenths" && /^10:15:4\d,\d$/.test(got.text) ? "" : `nach zweitem T ${got.mode} „${got.text}“`,
      got.hint === "Timecode: Zehntel" ? "" : `Hinweis „${got.hint}“`, errors(got, msgs)]);
  }
  // Weniger Bewegung: aus Frames werden Zehntel, mit Begründung.
  {
    const { got, msgs, out } = await single("?design=tc&sub=frames", {}, async (page, clock) => {
      const before = await page.evaluate(tcState);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await clock.run(250);
      return before;
    });
    note("/clock Timecode weniger Bewegung", [out.mode === "frames" ? "" : `vorher ${out.mode}`,
      got.mode === "tenths" && /^10:15:42,\d$/.test(got.text) ? "" : `zeigt ${got.mode} „${got.text}“`,
      /Frames aus, weil dein System weniger Bewegung wünscht$/.test(got.note) ? "" : `Zeile „${got.note}“`, errors(got, msgs)]);
  }
  // E-Ink: weder Feinstelle noch Sekunden, auch mit sub=frames; Taste T ändert daran nichts.
  {
    const { got, msgs } = await single("?design=tc&eink=1&sub=frames", {}, async (page, clock) => {
      await page.keyboard.press("t");
      await clock.run(250);
    });
    note("/clock Timecode E-Ink", [got.text === "10:15" && !got.fineShown && got.mode === "off" ? "" : `zeigt „${got.text}“ (${got.mode}, Feinstelle ${got.fineShown})`,
      got.hint === "E-Ink zeigt keine Feinstelle." ? "" : `Hinweis „${got.hint}“`,
      got.label === LABEL && got.labelShown ? "" : "Kopfzeile fehlt", errors(got, msgs)]);
  }
  // sub=off und show ohne seconds.
  for (const [query, text] of [["?design=tc&sub=off", "10:15:42"], ["?design=tc&show=time,status", "10:15"]]) {
    const { got, msgs } = await single(query, {});
    note(`/clock Timecode ${query}`, [got.text === text && !got.fineShown ? "" : `zeigt „${got.text}“ (Feinstelle ${got.fineShown})`, errors(got, msgs)]);
  }
  // Grob gerundete Zeitgeber: performance.now() in 100-ms-Stufen, dann das Design wählen (die Messung läuft danach).
  {
    const { got, msgs } = await single("?design=digital", {}, async (page, clock) => {
      await page.evaluate(() => {
        const real = performance.now.bind(performance);
        performance.now = () => Math.floor(real() / 100) * 100;
      });
      await page.selectOption("#design", "tc");
      await clock.run(1500);
    });
    note("/clock Timecode grobe Zeitgeber", [got.level === "unsure" && got.grey && got.fineShown ? "" : `Feinstelle ${got.level}, grau ${got.grey}`,
      /Feinstelle unsicher: Dein Browser rundet seine Zeitgeber auf 100 ms$/.test(got.note) ? "" : `Zeile „${got.note}“`, errors(got, msgs)]);
  }
  // Zeitzone des Servers (Browser: Europe/Berlin): Timecode in New York, die Zone steht darunter.
  {
    const { got, msgs } = await single("?design=tc", { reply: reply({ zone: "America/New_York" }) });
    note("/clock Timecode Zone des Servers", [/^04:15:42,[45]$/.test(got.text) ? "" : `zeigt „${got.text}“`,
      got.note === "25 fps · Zehntel · New York" ? "" : `Zeile „${got.note}“`, errors(got, msgs)]);
  }
  // ⓘ erklärt die Grenze; Esc schließt.
  {
    const { got, msgs, out } = await single("?design=tc", {}, async (page) => {
      await page.click(".tc-head .info");
      const open = await page.evaluate(tcState);
      await page.keyboard.press("Escape");
      return open;
    });
    note("/clock Timecode ⓘ", [got.info ? "" : "ⓘ fehlt", /Hausreferenzsignal/.test(out.popover) && /LTC- oder VITC-Generatoren/.test(out.popover)
      ? "" : `Erklärung „${out.popover.slice(0, 60)}“`, got.popover === "" ? "" : "Esc schließt nicht", errors(got, msgs)]);
  }
  // Kleine Flächen: Kopfzeile im Bild (umbrochen, im flachen Streifen neben der Zeit), Ziffern deutlich größer als die
  // Kopfzeile. Mit Kopfzeile und Band bleiben der Bühne bei 1920×100 nur 26 px, bei 1920×60 (kiosk) 12 px Höhe: Dort
  // füllen die Ziffern die Höhe aus (mindestens so groß wie im Design digital), größer als die Kopfzeile geht nicht.
  for (const [width, height, query, minSize] of [[240, 135, "?design=tc&layout=tile", 30], [256, 144, "?design=tc&layout=tile&sub=frames", 26],
    [240, 135, "?design=tc&kiosk=1", 30], [280, 500, "?design=tc", 30], [1920, 100, "?design=tc&layout=strip", 20],
    [1920, 60, "?design=tc&layout=strip&kiosk=1", 10], [640, 100, "?design=tc&layout=strip", 24]]) {
    const { got, msgs } = await single(query, { width, height });
    note(`/clock Timecode klein ${width}×${height} ${query} [${got.layout}]`, [
      got.label === LABEL && (got.labelShown || minSize < 18) && got.headIn ? "" : `Kopfzeile sichtbar ${got.labelShown}, im Bild ${got.headIn}`,
      got.labelSize >= 11.5 ? "" : `Kopfzeile nur ${got.labelSize.toFixed(1)} px`,
      got.rowSize >= minSize && (minSize < 18 || got.rowSize >= 1.5 * got.labelSize) ? "" : `Ziffern nur ${got.rowSize.toFixed(1)} px (Kopfzeile ${got.labelSize.toFixed(1)} px)`,
      got.rowIn && !got.wrapped ? "" : "Zeile außerhalb der Bühne oder umbrochen",
      got.overflow > 0 || got.vscroll > 0 ? `Scrollbalken (${got.overflow}/${got.vscroll} px)` : "", errors(got, msgs)]);
  }
  // Graue Feinstelle ohne Platz für die Zeile darunter: Der Grund steht kurz in der Kopfzeile – nie nur Farbe.
  for (const [width, height, query] of [[1920, 200, "?design=tc&sub=frames&fps=29.97"], [480, 270, "?design=tc&sub=frames&fps=29.97"],
    [480, 270, "?design=tc&sub=frames&layout=tile"], [1920, 200, "?design=tc&sub=frames&layout=strip"], [640, 100, "?design=tc&sub=frames&layout=strip"], [240, 135, "?design=tc&sub=frames"],
    [1920, 1080, "?design=tc&sub=frames"]]) {
    const { got, msgs } = await single(query, { width, height, reply: reply({ accuracy: 0.03 }) });
    const text = got.noteShown ? /Frames unsicher: Anzeige/.test(got.note) && !got.whyShown : got.whyShown && got.why === " · Frames unsicher";
    note(`/clock Timecode Grund sichtbar ${width}×${height} ${query} [${got.layout}]`, [
      got.level === "unsure" && got.grey ? "" : `Feinstelle ${got.level}, grau ${got.grey}`,
      text ? "" : `Grund nicht zu lesen (Zeile darunter sichtbar ${got.noteShown}, Kopfzeile „${got.why}“ sichtbar ${got.whyShown})`,
      got.headIn && got.rowIn ? "" : "Kopfzeile oder Zeit außerhalb der Bühne",
      got.overflow > 0 || got.vscroll > 0 ? `Scrollbalken (${got.overflow}/${got.vscroll} px)` : "", errors(got, msgs)]);
  }
  {
    const { got, msgs } = await single("?design=tc&maxerr=20", { width: 480, height: 270, reply: reply({ accuracy: 0.01 }) });
    note("/clock Timecode Grund sichtbar: Feinstelle aus", [got.whyShown && got.why === " · Feinstelle aus" ? "" : `Kopfzeile „${got.why}“ sichtbar ${got.whyShown}`,
      errors(got, msgs)]);
  }
  // Ausgeblendete Feinstelle bei Drop-Frame: Früh am Tag (Server in Los Angeles, 01:15) läuft der Timecode der Wanduhr
  // nach. Kurz nach der vollen Sekunde gezeichnet, zeigen die Sekunden trotzdem die Wanduhr (01:15:43), nicht den
  // Timecode (01:15:42;29).
  for (const fps of ["29.97", "59.94"]) {
    const { got, msgs } = await single(`?design=tc&sub=frames&fps=${fps}`, { reply: reply({ accuracy: 0.6, zone: "America/Los_Angeles" }) },
      async (page, clock) => { await clock.run(750); });
    note(`/clock Timecode Drop-Frame ${fps} ohne Feinstelle`, [got.level === "off" && !got.fineShown ? "" : `Feinstelle ${got.level}`,
      got.text === "01:15:43" && got.dataTime === "01:15:43" ? "" : `zeigt „${got.text}“ (data-time ${got.dataTime}) statt 01:15:43`, errors(got, msgs)]);
  }
  // Bleibt die Feinstelle aus, rückt die Zeit nach 3 s zur Mitte (vorher bleibt der Platz frei).
  {
    const { got, msgs, out } = await single("?design=tc&maxerr=20", { reply: reply({ accuracy: 0.01 }) }, async (page, clock) => {
      const before = await page.evaluate(tcState);
      await clock.run(4500);
      return before;
    });
    note("/clock Timecode Feinstelle aus: Zeit mittig", [out.offCentre > 20 ? "" : `Platz anfangs nicht frei (${out.offCentre.toFixed(1)} px)`,
      got.offCentre <= 2 ? "" : `Zeit ${got.offCentre.toFixed(1)} px neben der Mitte`, got.level === "off" && !got.fineShown ? "" : `Feinstelle ${got.level}`,
      got.rowIn && got.overflow <= 0 ? "" : "Zeile außerhalb der Bühne", errors(got, msgs)]);
  }
  // Taste T mit ?cd=main: Der Countdown ist die Hauptanzeige, T schaltet seine Zehntel (nicht die Feinstelle des Timecodes).
  {
    const { got, msgs, out } = await single("?design=tc&timer=90s&cd=main", {}, async (page) => {
      const before = await page.evaluate(tcState);
      await page.keyboard.press("t");
      return before;
    });
    note("/clock Timecode Taste T mit cd=main", [/Zehntel (an|aus)/.test(got.hint) ? "" : `Hinweis „${got.hint}“`,
      got.cdTime !== out.cdTime ? "" : `Countdown unverändert „${got.cdTime}“`, got.mode === out.mode ? "" : `Feinstelle ${got.mode}`, errors(got, msgs)]);
  }
  // Taste T ohne Sekunden: kein Wechsel, der Hinweis sagt warum.
  {
    const { got, msgs } = await single("?design=tc&show=time,status", {}, async (page) => { await page.keyboard.press("t"); });
    note("/clock Timecode Taste T ohne Sekunden", [got.hint === "Ohne Sekunden gibt es keine Feinstelle." ? "" : `Hinweis „${got.hint}“`,
      got.mode === "off" && got.text === "10:15" ? "" : `zeigt ${got.mode} „${got.text}“`, errors(got, msgs)]);
  }
  // ?sub=off: T führt im Dreierwechsel zurück zu „aus“ (aus → Zehntel → Frames → aus).
  {
    const { got, msgs, out } = await single("?design=tc&sub=off", {}, async (page, clock) => {
      const seen = [];
      for (let i = 0; i < 2; i += 1) {
        await page.keyboard.press("t");
        await clock.run(250);
        const now = await page.evaluate(tcState);
        seen.push(`${now.mode}|${now.hint}`);
      }
      await page.keyboard.press("t");
      await clock.run(250);
      return seen;
    });
    note("/clock Timecode Taste T mit sub=off", [
      out.join(" ") === "tenths|Timecode: Zehntel frames|Timecode: Frames (nicht genlocked)" ? "" : `Folge „${out.join(" ")}“`,
      got.mode === "off" && !got.fineShown && /^10:15:4\d$/.test(got.text) ? "" : `nach drittem T ${got.mode} „${got.text}“`,
      got.hint === "Timecode: Feinstelle aus" ? "" : `Hinweis „${got.hint}“`, errors(got, msgs)]);
  }
  // Zone des Servers weicht ab (Honolulu, dort noch Montag, der 29.): Datum unter dem Timecode gehört zu dieser Zone;
  // nach Taste U steht in der Nebenzeile die Zeit des Servers mit Zonenname, nicht die des Browsers.
  {
    const { got, msgs, out } = await single("?design=tc", { reply: reply({ zone: "Pacific/Honolulu" }) }, async (page) => {
      const before = await page.evaluate(tcState);
      await page.keyboard.press("u");
      return before;
    });
    note("/clock Timecode Datum in der Zone des Servers", [/^22:15:42,[45]$/.test(out.text) ? "" : `zeigt „${out.text}“`,
      out.date === "Montag, 29. Juni 2026" ? "" : `Datum „${out.date}“`, out.utcLabel === "UTC" && out.utcTime === "08:15:42" ? "" : `Nebenzeile „${out.utcLabel} ${out.utcTime}“`,
      /^08:15:42,[45]$/.test(got.text) ? "" : `nach U „${got.text}“`,
      got.utcLabel === "Honolulu" && got.utcTime === "22:15:42" ? "" : `Nebenzeile nach U „${got.utcLabel} ${got.utcTime}“`,
      got.date === "Montag, 29. Juni 2026" ? "" : `Datum nach U „${got.date}“`, errors(got, msgs)]);
  }
  {
    const { got, msgs } = await single("?design=tc", {}, async (page) => { await page.keyboard.press("u"); });
    note("/clock Timecode Datum in eigener Zone", [got.date === "Dienstag, 30. Juni 2026" ? "" : `Datum „${got.date}“`,
      got.utcLabel === "Ortszeit" && got.utcTime === "10:15:42" ? "" : `Nebenzeile nach U „${got.utcLabel} ${got.utcTime}“`, errors(got, msgs)]);
  }
  // Wechsel zurück zu einem anderen Design: keine Timecode-Zeile mehr, keine Fehler.
  {
    const { got, msgs } = await single("?design=tc&sub=frames", {}, async (page, clock) => {
      await page.selectOption("#design", "digital");
      await clock.run(500);
    });
    note("/clock Timecode → digital", [got.missing && got.design === "digital" ? "" : `Design ${got.design}`, errors(got, msgs)]);
  }
  return { found, lines };
}

// Studiouhr B2 (clockWorldChecks, TOUR_WORLD_ONLY=1): Weltzeit aus docs/konzept/studiouhr.md (Abschnitt 2.5,
// Akzeptanz B). Mit angehaltener Playwright-Uhr (page.clock) und gemocktem /api/v1/time steht die Serverzeit fest.
// Sechs Zonen als Leiste (Layout automatisch) und als Raster (?layout=world) auf allen neun Flächen: jede sichtbare Zone
// mit richtiger Uhrzeit und Abweichung ganz in der Bühne, Schrift ab 12 px, Tag/Nacht-Symbol mit aria-label, kein
// Scrollbalken, keine CSP-Verstöße; im Streifen und in der Kachel keine Leiste; fehlende Zonen nennt „+n“. Dazu bei
// 1920×1080 mit festen Zeitpunkten: Europa stellt um (29.3., 25.10.), die USA stellen um (8.3.), Zonen mit 30 und 45
// Minuten, Datumsgrenze mit „+1 Tag“/„−1 Tag“, Taste U (Bezug UTC), Kurznamen nur als Text, eine Zone wie bisher.
// Einpassen: ?show= ohne tz (Layout world → Automatik, Banner ohne leere Zeile), Raster ohne Platz für eine Zone (Uhr im
// automatischen Layout), breite Zelle im festen Banner, „+n“ zählt nicht als Zeile (800×480 mit vier und sechs Zonen,
// „+2“ in der zweiten Zeile), Raster einspaltig bei 360×640, Leerzeichen nach dem Komma, ?h12=1 in den Zonen, Leiste
// wächst bei 768×1024, Vorschlagsliste und Schreibweise im Panel „Anpassen“.
function worldState() {
  const root = document.documentElement;
  const stage = document.getElementById("clock-stage");
  const sb = stage.getBoundingClientRect();
  const node = document.getElementById("world");
  const vis = (n) => {
    if (!n) return false;
    const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };
  const inStage = (n) => { const r = n.getBoundingClientRect();
    return r.left >= sb.left - 1 && r.right <= sb.right + 1 && r.top >= sb.top - 1 && r.bottom <= sb.bottom + 1; };
  const cells = [...node.querySelectorAll(".wz")].filter(vis);
  const more = node.querySelector(".wz-more");
  const text = (n, sel) => n.querySelector(sel).textContent;
  const sizes = cells.flatMap((c) => [".wz-label", ".wz-time", ".wz-delta"].map((sel) => parseFloat(getComputedStyle(c.querySelector(sel)).fontSize)));
  const time = [document.getElementById("local-time"), document.getElementById("face")].find(vis);
  const tz2 = document.getElementById("tz2");
  return {
    layout: stage.dataset.layout || "", world: stage.dataset.world || "", flow: stage.dataset.worldFlow || "",
    shown: vis(node), role: node.getAttribute("role"), aria: node.getAttribute("aria-label") || "",
    total: node.querySelectorAll(".wz").length,
    rows: cells.map((c) => `${text(c, ".wz-label")} ${text(c, ".wz-time")} ${text(c, ".wz-delta")} ${text(c, ".wz-day")}`.trim()),
    night: cells.map((c) => c.dataset.night).join(""),
    sunLabels: cells.map((c) => c.querySelector(".wz-sun").getAttribute("aria-label") || ""),
    sunShown: cells.every((c) => vis(c.querySelector(".wz-sun")) && c.querySelector(".wz-sun").getAttribute("role") === "img"),
    inside: cells.every(inStage) && (!vis(more) || inStage(more)), more: vis(more) ? more.textContent : "",
    moreLabel: vis(more) ? more.getAttribute("aria-label") || "" : "",
    smallest: sizes.length ? Math.min(...sizes) : null,
    timeIn: time ? inStage(time) : false, timeHeight: time ? time.getBoundingClientRect().height : 0,
    dateTop: Math.round(document.getElementById("local-date").getBoundingClientRect().top),
    zoneFont: cells.length ? parseFloat(getComputedStyle(cells[0].querySelector(".wz-time")).fontSize) : 0,
    dense: stage.dataset.worldDense || "",
    lines: new Set(cells.map((c) => Math.round(c.getBoundingClientRect().top))).size,
    tz2: vis(tz2) ? tz2.textContent.replace(/\s+/g, " ").trim() : "", html: node.querySelectorAll("img, b, script").length,
    local: document.getElementById("local-time").textContent,
    overflow: root.scrollWidth - root.clientWidth, vscroll: root.scrollHeight - root.clientHeight, csp: window.__csp || [],
  };
}

async function clockWorldChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    const list = problems.filter(Boolean);
    lines.push(`${label}: ${list.length ? list.join("; ") : "ok"}`);
    if (list.length) found.push(`${label}: ${list.join("; ")}`);
  };
  const errors = (got, msgs) => (got.csp.length || msgs.length ? `Fehler ${JSON.stringify([...got.csp, ...msgs])}` : "");
  const M = "−";
  const ZONES = "tz=Europe/London,America/New_York,Asia/Tokyo,Asia/Kolkata,Australia/Sydney,Pacific/Kiritimati&tzl=LON,NYC,TYO,,SYD,";
  // Serverzeit 30.6. 10:15:42 in Berlin (MESZ).
  const ROWS = [`LON 09:15 ${M}1 h`, `NYC 04:15 ${M}6 h`, "TYO 17:15 +7 h", "Kolkata 13:45 +3:30 h", "SYD 18:15 +8 h", "Kiritimati 22:15 +12 h"];
  const NIGHT = "010011";
  const ALL = new Set(["1920x1080", "390x844", "3840x1080", "1080x1920", "3840x2160"]);   // dort passen alle sechs

  for (const [width, height] of STUDIO_VIEWPORTS) {
    for (const [name, query] of [["Leiste", `?${ZONES}`], ["Raster", `?layout=world&${ZONES}`]]) {
      const { ctx, page, msgs } = await openPausedClock(browser, { width, height, query });
      const got = await page.evaluate(worldState);
      await ctx.close();
      const n = got.rows.length;
      const off = name === "Leiste" && ["strip", "tile"].includes(got.layout);
      note(`/clock Weltzeit ${name} ${width}×${height} [${got.layout || "?"}${got.flow ? ` ${got.flow}` : ""}, ${n} von 6]`, [
        got.total === 6 ? "" : `${got.total} Zellen statt 6`,
        name === "Raster" ? (got.layout === "world" ? "" : `Layout ${got.layout}`) : (got.layout !== "world" ? "" : "Layout world ohne Parameter"),
        off ? (n === 0 && !got.shown ? "" : `Leiste im Layout ${got.layout} sichtbar`) : "",
        JSON.stringify(got.rows) === JSON.stringify(ROWS.slice(0, n)) ? "" : `zeigt ${JSON.stringify(got.rows)}`,
        got.night === NIGHT.slice(0, n) ? "" : `Tag/Nacht ${got.night}`,
        got.sunShown && got.sunLabels.every((label, i) => label === (NIGHT[i] === "1" ? "Nacht" : "Tag")) ? "" : `Symbol ohne Text-Alternative ${JSON.stringify(got.sunLabels)}`,
        got.inside ? "" : "Zone außerhalb der Bühne", got.timeIn ? "" : "Uhrzeit außerhalb der Bühne",
        n === 0 || got.smallest >= 11.5 ? "" : `Schrift nur ${got.smallest.toFixed(1)} px`,
        n > 0 && n < 6 ? (got.more === `+${6 - n}` && (6 - n === 1 ? got.moreLabel === "1 weitere Zeitzone passt hier nicht" : /^\d weitere Zeitzonen passen/.test(got.moreLabel)) ? "" : `fehlende Zonen nicht genannt („${got.more}“)`) : (got.more ? `„${got.more}“ ohne fehlende Zone` : ""),
        ALL.has(`${width}x${height}`) && n !== 6 ? `nur ${n} von 6 Zonen` : "",
        n === 0 || (got.role === "list" && got.aria === "Weltzeit") ? "" : `role ${got.role}, aria-label „${got.aria}“`,
        got.local.startsWith("10:15:42") ? "" : `Uhr zeigt ${got.local}`,
        got.overflow > 0 || got.vscroll > 0 ? `Scrollbalken (${got.overflow}/${got.vscroll} px)` : "", errors(got, msgs)]);
    }
  }

  const single = async (query, opts = {}, act = null) => {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, query, ...opts });
    const before = await page.evaluate(worldState);
    const out = act ? await act(page, clock) : null;
    const got = await page.evaluate(worldState);
    await ctx.close();
    return { before, got, msgs, out };
  };
  const want = (got, rows) => (JSON.stringify(got.rows) === JSON.stringify(rows) ? "" : `zeigt ${JSON.stringify(got.rows)} statt ${JSON.stringify(rows)}`);
  const cross = async (label, at, query, first, second) => {
    // 10 s vor der Umstellung öffnen, dann 15 s weiter: Die Abweichung wechselt mit dem Minutensprung.
    const { before, got, msgs } = await single(query, { at: Date.parse(at) - 10000 }, async (page, clock) => { await clock.run(15000); });
    note(`/clock Weltzeit ${label}`, [want(before, first), want(got, second), got.inside ? "" : "Zone außerhalb der Bühne", errors(got, msgs)]);
  };
  const THREE = "?tz=Europe/London,America/New_York,Asia/Tokyo";
  await cross("Europa stellt vor (29.3.)", "2026-03-29T01:00:00Z", THREE,
    [`London 00:59 ${M}1 h`, `New York 20:59 ${M}5 h ${M}1 Tag`, "Tokyo 09:59 +8 h"],
    [`London 02:00 ${M}1 h`, `New York 21:00 ${M}6 h ${M}1 Tag`, "Tokyo 10:00 +7 h"]);
  await cross("Europa stellt zurück (25.10.)", "2026-10-25T01:00:00Z", THREE,
    [`London 01:59 ${M}1 h`, `New York 20:59 ${M}6 h ${M}1 Tag`, "Tokyo 09:59 +7 h"],
    [`London 01:00 ${M}1 h`, `New York 21:00 ${M}5 h ${M}1 Tag`, "Tokyo 10:00 +8 h"]);
  await cross("USA stellen vor (8.3.)", "2026-03-08T07:00:00Z", "?layout=world&tz=America/New_York,America/Phoenix",
    [`New York 01:59 ${M}6 h`, `Phoenix 23:59 ${M}8 h ${M}1 Tag`], [`New York 03:00 ${M}5 h`, `Phoenix 00:00 ${M}8 h`]);

  {
    const query = "?layout=world&tz=Asia/Kolkata,Asia/Kathmandu,Pacific/Kiritimati,Etc/GMT%2B12,Pacific/Chatham,Australia/Lord_Howe&tzl=,,,Baker%20Island";
    const { got, msgs } = await single(query, { at: Date.parse("2026-01-15T12:00:30Z") });
    note("/clock Weltzeit halbe Stunden und Datumsgrenze", [want(got, ["Kolkata 17:30 +4:30 h", "Kathmandu 17:45 +4:45 h",
      "Kiritimati 02:00 +13 h +1 Tag", `Baker Island 00:00 ${M}13 h`, "Chatham 01:45 +12:45 h +1 Tag", "Lord Howe 23:00 +10 h"]),
    got.night === "001111" ? "" : `Tag/Nacht ${got.night}`, got.inside ? "" : "Zone außerhalb der Bühne", errors(got, msgs)]);
  }
  {
    // Taste U: Die große Zeit ist UTC, die Abweichungen beziehen sich darauf.
    const { before, got, msgs } = await single(THREE, {}, async (page, clock) => { await page.keyboard.press("u"); await clock.run(250); });
    note("/clock Weltzeit Taste U", [want(before, [`London 09:15 ${M}1 h`, `New York 04:15 ${M}6 h`, "Tokyo 17:15 +7 h"]),
      want(got, ["London 09:15 +1 h", `New York 04:15 ${M}4 h`, "Tokyo 17:15 +9 h"]), errors(got, msgs)]);
  }
  {
    // Kurzname mit Sonderzeichen: die ganze Liste gilt nicht, es bleibt der Ortsname – und nichts davon wird Markup.
    const { got, msgs } = await single("?tz=Europe/London,Asia/Tokyo&tzl=LON,%3Cimg%20src%3Dx%3E");
    note("/clock Weltzeit Kurzname mit Sonderzeichen", [want(got, [`London 09:15 ${M}1 h`, "Tokyo 17:15 +7 h"]),
      got.html === 0 ? "" : "Markup aus dem Kurznamen im DOM", errors(got, msgs)]);
  }
  {
    const { got, msgs } = await single("?tz=Europe/London&tz=Asia/Tokyo&tzl=Studio%202&tzl=T%C5%8Dky%C5%8D");
    note("/clock Weltzeit mehrfach genannt", [want(got, [`Studio 2 09:15 ${M}1 h`, "Tōkyō 17:15 +7 h"]), got.tz2 === "" ? "" : `zweite Zeitzone zusätzlich („${got.tz2}“)`,
      errors(got, msgs)]);
  }
  {
    // Eine Zone: wie bisher als zweite Zeitzone in der Zeile unter der Uhr, ohne Leiste.
    const { got, msgs } = await single("?tz=America/New_York&tzl=NYC");
    note("/clock Weltzeit eine Zone", [got.tz2 === "NYC 04:15" ? "" : `zweite Zeitzone „${got.tz2}“`, got.shown || got.total ? "Leiste trotz einer Zone" : "",
      errors(got, msgs)]);
  }
  {
    // Profil mit Zonen und Kurznamen, die Adresse nennt eine andere Zone ohne Kurznamen: New York steht nicht unter „LON“.
    const profile = (name) => (name === "regie" ? { name, title: "Regie 1", builtin: false, profiles_rev: "aaaa00000001",
      params: { tz: "Europe/London,Asia/Tokyo", tzl: "LON,TYO" } } : null);
    const { got, msgs } = await single("?p=regie&tz=America/New_York", { profile });
    note("/clock Weltzeit Zone der Adresse ohne Kurznamen des Profils", [got.tz2 === "New York 04:15" ? "" : `zweite Zeitzone „${got.tz2}“`,
      got.shown || got.total ? "Leiste trotz einer Zone" : "", errors(got, msgs)]);
    const same = await single("?p=regie", { profile });
    note("/clock Weltzeit Kurznamen des Profils", [want(same.got, ["LON 09:15 −1 h", "TYO 17:15 +7 h"].map((row) => row.replace("−", M))),
      errors(same.got, same.msgs)]);
  }
  {
    // Zu viele oder doppelte Zonen: nichts davon gilt, die Uhr läuft ohne Weltzeit.
    const { got, msgs } = await single("?tz=UTC,Europe/London,America/New_York,Asia/Tokyo,Asia/Kolkata,Australia/Sydney,Europe/Paris");
    note("/clock Weltzeit sieben Zonen", [!got.shown && got.total === 0 && got.tz2 === "" ? "" : `zeigt ${JSON.stringify(got.rows)}`,
      got.local.startsWith("10:15:42") ? "" : `Uhr zeigt ${got.local}`, errors(got, msgs)]);
  }
  {
    // Layout world ohne Zonen: UTC als einzige Zelle. Rotlicht und E-Ink: lesbar, nichts außerhalb.
    const { got, msgs } = await single("?layout=world");
    note("/clock Weltzeit Layout world ohne tz", [want(got, [`UTC 08:15 ${M}2 h`]), got.inside ? "" : "außerhalb der Bühne", errors(got, msgs)]);
    for (const [label, opts, query] of [["Rotlicht", { red: true }, `?layout=world&${ZONES}`], ["E-Ink", {}, `?eink=1&${ZONES}`],
      ["Design studio", {}, `?design=studio&${ZONES}`], ["Kiosk 480×270", { width: 480, height: 270 }, `?layout=world&kiosk=1&${ZONES}`]]) {
      const r = await single(query, opts);
      const n = r.got.rows.length;
      note(`/clock Weltzeit ${label}`, [n > 0 && JSON.stringify(r.got.rows) === JSON.stringify(ROWS.slice(0, n)) ? "" : `zeigt ${JSON.stringify(r.got.rows)}`,
        r.got.inside && r.got.timeIn ? "" : "außerhalb der Bühne", r.got.smallest >= 11.5 ? "" : `Schrift nur ${r.got.smallest} px`,
        r.got.overflow > 0 || r.got.vscroll > 0 ? `Scrollbalken (${r.got.overflow}/${r.got.vscroll} px)` : "", errors(r.got, r.msgs)]);
    }
  }

  // --- Einpassen ---
  const Z6 = "tz=Europe/London,America/New_York,Asia/Tokyo,Asia/Kolkata,Australia/Sydney,Pacific/Kiritimati";
  const LONG = `${Z6}&tzl=${["P", "Q", "R", "S", "T", "U"].map((c) => `ABCDEFGHIJKLMNO${c}`).join(",")}`;
  const JAN = Date.parse("2026-01-15T12:00:30Z");   // Berlin 13:00:30 (MEZ)
  const sized = (width, height, query, opts = {}) => single(query, { width, height, ...opts });
  const base = (r) => [r.got.timeIn ? "" : "Uhrzeit außerhalb der Bühne", r.got.inside ? "" : "Zone außerhalb der Bühne",
    r.got.overflow > 0 || r.got.vscroll > 0 ? `Scrollbalken (${r.got.overflow}/${r.got.vscroll} px)` : "", errors(r.got, r.msgs)];
  {
    // ?show= ohne tz: keine Weltzeit. Im Layout world gilt dann die Automatik – die Uhr so groß wie ohne layout=world.
    const off = await sized(1920, 1080, `?layout=world&show=time,seconds,date&${Z6}`);
    const plain = await sized(1920, 1080, "?show=time,seconds,date");
    note("/clock Weltzeit show ohne tz im Layout world", [off.got.layout === "normal" && off.got.world === "" ? "" : `Layout ${off.got.layout}, data-world „${off.got.world}“`,
      off.got.rows.length || off.got.total ? "Zonen trotz show ohne tz" : "",
      Math.abs(off.got.timeHeight - plain.got.timeHeight) <= 1 ? "" : `Zeit ${Math.round(off.got.timeHeight)} px statt ${Math.round(plain.got.timeHeight)} px`, ...base(off)]);
    // Banner im Kiosk: ohne dritte Zeile der Spalte, Datum auf derselben Höhe wie ohne Zonen.
    const bar = await sized(1920, 200, `?kiosk=1&show=time,seconds,date,status&${Z6}`);
    const none = await sized(1920, 200, "?kiosk=1&show=time,seconds,date,status");
    note("/clock Weltzeit show ohne tz im Banner", [bar.got.layout === "banner" && bar.got.world === "" ? "" : `Layout ${bar.got.layout}, data-world „${bar.got.world}“`,
      bar.got.dateTop === none.got.dateTop ? "" : `Datum bei ${bar.got.dateTop} px statt ${none.got.dateTop} px`, ...base(bar)]);
    const shown = await sized(1920, 1080, `?show=time,seconds,date,tz&${Z6}`);
    note("/clock Weltzeit show mit tz", [shown.got.rows.length === 6 && shown.got.world === "bar" ? "" : `${shown.got.rows.length} von 6, data-world „${shown.got.world}“`, ...base(shown)]);
  }
  for (const [width, height, query] of [[320, 180, `?kiosk=1&layout=world&${Z6}`], [320, 180, "?kiosk=1&layout=world"], [200, 400, `?kiosk=1&layout=world&${Z6}`]]) {
    // Layout world ohne Platz für eine einzige Zone: Uhr im automatischen Layout, so groß wie ohne layout=world.
    const r = await sized(width, height, query);
    const auto = await sized(width, height, "?kiosk=1");
    note(`/clock Weltzeit Raster ohne Platz ${width}×${height}${query.includes("tz=") ? "" : " ohne tz"}`, [
      r.got.rows.length === 0 && r.got.world === "off" ? "" : `zeigt ${r.got.rows.length} Zonen (data-world „${r.got.world}“)`,
      r.got.layout === auto.got.layout ? "" : `Layout ${r.got.layout} statt ${auto.got.layout}`,
      r.got.timeHeight >= auto.got.timeHeight - 1 ? "" : `Zeit ${Math.round(r.got.timeHeight)} px statt ${Math.round(auto.got.timeHeight)} px`, ...base(r)]);
  }
  for (const [width, height, zones] of [[320, 240, "America/Argentina/ComodRivadavia,Asia/Tokyo"], [200, 400, "Europe/London,Asia/Tokyo"]]) {
    // Festes Banner auf schmaler Fläche: Eine Zelle, die breiter ist als die Spalte, ragt nicht aus der Bühne.
    const r = await sized(width, height, `?kiosk=1&layout=banner&tz=${zones}`);
    note(`/clock Weltzeit breite Zelle im Banner ${width}×${height}`, [r.got.layout === "banner" ? "" : `Layout ${r.got.layout}`, ...base(r)]);
  }
  for (const [width, height, query, n, more, rows] of [
    [800, 480, "?tz=Europe/London,America/New_York,Asia/Tokyo,Asia/Kolkata", 3, "+1", 1],
    [800, 480, `?${Z6}`, 3, "+3", 1], [800, 400, `?kiosk=1&${Z6}`, 3, "+3", 1],
    [1280, 400, `?kiosk=1&${Z6}`, 5, "+1", 2]]) {
    // Der Hinweis „+n“ steht in der Zeile der letzten Zone und zählt nicht als eigene Zeile.
    const r = await sized(width, height, query, { at: JAN });
    const label = more === "+1" ? "1 weitere Zeitzone passt hier nicht" : `${more.slice(1)} weitere Zeitzonen passen hier nicht`;
    note(`/clock Weltzeit „${more}“ in der Zeile ${width}×${height}${query.includes("kiosk") ? " Kiosk" : ""}`, [
      r.got.rows.length === n && r.got.more === more ? "" : `${r.got.rows.length} Zonen und „${r.got.more}“ statt ${n} und „${more}“`,
      r.got.moreLabel === label ? "" : `Text-Alternative „${r.got.moreLabel}“`, r.got.lines === rows ? "" : `${r.got.lines} Zeilen statt ${rows}`, ...base(r)]);
  }
  {
    const r = await sized(1920, 1080, `?${LONG}`);
    note("/clock Weltzeit „+2“ in der zweiten Zeile", [r.got.rows.length === 4 && r.got.more === "+2" && r.got.lines === 2 ? ""
      : `${r.got.rows.length} Zonen, „${r.got.more}“, ${r.got.lines} Zeilen`, ...base(r)]);
  }
  for (const [label, width, height, query, at] of [
    ["Timecode 360×640", 360, 640, "?layout=world&design=tc&tz=America/Argentina/Buenos_Aires,America/Los_Angeles,Asia/Ho_Chi_Minh,Europe/London,Asia/Tokyo,Australia/Sydney", JAN],
    ["Countdown 360×640", 360, 640, "?layout=world&until=20:15&label=Sendung&tz=America/Argentina/Buenos_Aires,America/Los_Angeles,Asia/Ho_Chi_Minh,Europe/London,Asia/Tokyo,Australia/Sydney", JAN],
    ["320×568", 320, 568, "?layout=world&tz=America/Argentina/Buenos_Aires,America/Los_Angeles,Asia/Ho_Chi_Minh,Europe/London,Asia/Tokyo,Australia/Sydney", JAN],
    ["lange Kurznamen 390×844 mit Rand", 390, 844, `?layout=world&safe=10&${LONG}`, CLOCK_SERVER]]) {
    // Fast hochformatige Fläche: Passen zwei Zellen nicht nebeneinander, steht das Raster als eine Spalte mit allen Zonen.
    const r = await sized(width, height, query, { at });
    note(`/clock Weltzeit Raster einspaltig ${label}`, [r.got.rows.length === 6 && !r.got.more ? "" : `${r.got.rows.length} von 6 („${r.got.more}“)`,
      r.got.flow === "list" && r.got.lines === 6 ? "" : `Anordnung ${r.got.flow}, ${r.got.lines} Zeilen`,
      r.got.smallest >= 11.5 ? "" : `Schrift nur ${r.got.smallest} px`, ...base(r)]);
  }
  {
    // Leerzeichen nach dem Komma (auch als „+“): Die Liste gilt.
    const r = await single("?tz=Europe/London,%20Asia/Tokyo&tzl=LON,+TYO");
    note("/clock Weltzeit Leerzeichen nach dem Komma", [want(r.got, [`LON 09:15 ${M}1 h`, "TYO 17:15 +7 h"]), ...base(r)]);
  }
  {
    // ?h12=1: Zonen wie die große Zeit zwölfstündig mit AM/PM – in Raster, Leiste und als zweite Zeitzone.
    const grid = await single(`?layout=world&h12=1&${Z6}`, { at: JAN });
    note("/clock Weltzeit h12 im Raster", [want(grid.got, [`London 12:00 PM ${M}1 h`, `New York 07:00 AM ${M}6 h`, "Tokyo 09:00 PM +8 h",
      "Kolkata 05:30 PM +4:30 h", "Sydney 11:00 PM +10 h", "Kiritimati 02:00 AM +13 h +1 Tag"]),
    grid.got.local.endsWith("PM") ? "" : `Uhr zeigt ${grid.got.local}`, grid.got.smallest >= 11.5 ? "" : `Schrift nur ${grid.got.smallest} px`, ...base(grid)]);
    const bar = await single("?h12=1&tz=Europe/London,Asia/Tokyo", { at: JAN });
    note("/clock Weltzeit h12 in der Leiste", [want(bar.got, [`London 12:00 PM ${M}1 h`, "Tokyo 09:00 PM +8 h"]), ...base(bar)]);
    const one = await single("?h12=1&tz=Asia/Tokyo&tzl=TYO", { at: JAN });
    note("/clock Weltzeit h12 mit einer Zone", [one.got.tz2 === "TYO 09:00 PM" ? "" : `zweite Zeitzone „${one.got.tz2}“`, ...base(one)]);
    const h24 = await single(`?layout=world&${Z6}`, { at: JAN });
    note("/clock Weltzeit ohne h12", [h24.got.rows[2] === "Tokyo 21:00 +8 h" ? "" : `zeigt ${h24.got.rows[2]}`, ...base(h24)]);
  }
  {
    // Leiste nutzt freie Höhe: bei 768×1024 alle sechs Zonen, die Zonenzeit deutlich über der Grundgröße, die Zeit so
    // groß wie ohne Zonen. Wo nichts frei ist (1920×200), bleibt alles in der Bühne.
    const r = await sized(768, 1024, `?${Z6}`);
    const plain = await sized(768, 1024, "");
    note("/clock Weltzeit Leiste wächst 768×1024", [r.got.rows.length === 6 ? "" : `${r.got.rows.length} von 6`,
      r.got.zoneFont >= 24 ? "" : `Zonenzeit nur ${r.got.zoneFont.toFixed(1)} px`,
      r.got.zoneFont <= r.got.timeHeight * 0.2 + 0.5 ? "" : `Zonenzeit ${r.got.zoneFont.toFixed(1)} px bei ${Math.round(r.got.timeHeight)} px Zeit`,
      r.got.timeHeight >= plain.got.timeHeight - 1 ? "" : `Zeit ${Math.round(r.got.timeHeight)} px statt ${Math.round(plain.got.timeHeight)} px`, ...base(r)]);
  }
  {
    // Panel „Anpassen“: „A, B“ gilt, das Feld hat eine Vorschlagsliste – auch für die Zone nach dem Komma.
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1280, height: 900, query: "" });
    await page.click("#mode-custom");
    await page.fill("#custom-tz", "Europe/London, Asia/Tokyo");
    const typed = await page.evaluate(() => {
      const input = document.getElementById("custom-tz");
      const list = document.getElementById(input.getAttribute("list") || "");
      return { invalid: input.getAttribute("aria-invalid"), list: input.getAttribute("list"), options: list ? [...list.options].map((o) => o.value) : [] };
    });
    await page.fill("#custom-tz", "Europe/London, Mars/Olympus");
    const wrong = await page.getAttribute("#custom-tz", "aria-invalid");
    await page.fill("#custom-tz", "");
    const empty = await page.evaluate(() => [...document.getElementById("custom-zones").options].map((o) => o.value));
    const got = await page.evaluate(worldState);
    await ctx.close();
    note("/clock Weltzeit Panel: Zonen mit Leerzeichen und Vorschlagsliste", [typed.invalid === "false" ? "" : "„A, B“ als ungültig markiert",
      wrong === "true" ? "" : "unbekannte Zone nicht markiert", typed.list === "custom-zones" ? "" : `list „${typed.list}“`,
      typed.options.includes("Europe/London, Asia/Tokyo") && typed.options.includes("Europe/London, America/New_York")
        && !typed.options.includes("Europe/London, Europe/London") ? "" : `Vorschläge nach dem Komma: ${JSON.stringify(typed.options.slice(0, 3))}`,
      empty.includes("Europe/London") && empty.length > 100 ? "" : `Vorschläge ohne Eingabe: ${empty.length}`, errors(got, msgs)]);
  }
  return { found, lines };
}

// Studiouhr B4 (clockSignalChecks, TOUR_SIGNAL_ONLY=1): On-Air/REC-Signal aus docs/konzept/studiouhr.md (Abschnitt 2.8,
// Akzeptanz B: Screenshot-Matrix um On-Air erweitert). Mit angehaltener Playwright-Uhr (page.clock) und gemocktem
// /api/v1/time steht die Serverzeit fest (10:15:42); die Antwort trägt signal und signal_rev.
// Matrix: neun Flächen × ON AIR (digital), REC (Studio), ON AIR (Timecode), REC (Weltzeit als Raster), dazu Kachel, Kiosk
// und E-Ink. Jede Fläche startet ohne Signal und schaltet dann um: Das Layout der Bühne springt dabei nicht. Geprüft: Balken sichtbar mit Text und Symbol (Symbol für Screenreader verborgen), Rahmen am body
// (durchgezogen bzw. doppelt), nichts bewegt sich, Schrift ab 12 px, Text nicht abgeschnitten, Zeit in der Bühne und
// unter dem Balken, kein Scrollbalken, keine CSP-Verstöße.
// Verhalten: ohne signal=1 zeigt der Bildschirm das zentrale Signal nicht und fragt weiter alle 5 s ab, mit signal=1
// jede Sekunde; ein Wechsel erscheint nach höchstens gut einer Sekunde und wird einmal angesagt; Taste O schaltet lokal
// („nur dieses Gerät“), mit lock=1 nicht; das zentrale Signal geht vor; fremde Werte zeigen nichts; ohne Antwort des
// Servers bleibt der Zustand stehen, gestrichelt und mit „Stand ungewiss“; signal=1 wirkt auch aus einem Profil.
// Dashboard: Karte „On-Air-Signal“ im Reiter „Anzeigen“ setzt den Zustand am echten Server und stellt ihn zurück.
// Dazu: „Stand ungewiss“ auf 240×135 und 320 px Breite (Symbol und Zustand bleiben im Balken, der Hinweis steht als
// Kurzfassung da), Größe des Balkens auf 3840×2160 und 1920×200, Taste O neben dem zentralen Signal (wirkt nicht, der
// Kurzhinweis sagt es und verdeckt den Balken nicht, nach dem zentralen „Aus“ bleibt nichts stehen), und im Dashboard
// bleibt die Statuszeile über mehrere Neuzeichnungen ruhig und nennt die Ablaufzeit.
function signalShown() {
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const body = document.body;
  const stage = $("clock-stage");
  const sb = stage.getBoundingClientRect();
  const vis = (n) => {
    if (!n) return false;
    const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };
  const bar = $("signal");
  const icon = bar.querySelector(".clock-signal-icon");
  const br = bar.getBoundingClientRect();
  const cs = getComputedStyle(bar);
  const bs = getComputedStyle(body);
  const time = [$("local-time"), $("face")].find(vis) || null;
  const tr = time ? time.getBoundingClientRect() : null;
  const inBar = (n) => { const r = n.getBoundingClientRect(); return r.left >= br.left - 1 && r.right <= br.right + 1; };
  const noteNode = [$("signal-note"), $("signal-note-short")].find(vis) || null;
  const hintNode = $("clock-hint");
  const hr = hintNode.getBoundingClientRect();
  return {
    iconIn: inBar(icon), textIn: inBar($("signal-text")), noteShown: noteNode ? noteNode.textContent : "",
    noteCut: Boolean(noteNode) && (noteNode.scrollWidth > noteNode.clientWidth + 1 || !inBar(noteNode)),
    barH: br.height, winH: window.innerHeight,
    hintOver: !hintNode.hidden && vis(bar) && hr.top < br.bottom && hr.bottom > br.top && hr.left < br.right && hr.right > br.left,
    shown: vis(bar), state: bar.dataset.signal || "", bodyState: body.dataset.signal || "", hasSignal: body.classList.contains("has-signal"),
    stale: body.hasAttribute("data-signal-stale"), text: $("signal-text").textContent, note: $("signal-note").textContent,
    icon: vis(icon), iconHidden: icon.getAttribute("aria-hidden"), iconStyle: `${getComputedStyle(icon).borderTopWidth}|${getComputedStyle(icon).backgroundImage.slice(0, 6)}`,
    html: bar.querySelectorAll("b, img, script").length, size: parseFloat(cs.fontSize), clipped: bar.scrollWidth > bar.clientWidth + 1,
    inPage: br.left >= -1 && br.right <= window.innerWidth + 1 && br.top >= -1 && br.bottom <= window.innerHeight + 1,
    border: bs.borderTopStyle, borderW: parseFloat(bs.borderTopWidth) || 0, sameColor: bs.borderTopColor === cs.backgroundColor,
    motion: [cs.animationName, cs.transitionDuration, bs.animationName, bs.transitionDuration, getComputedStyle(icon).animationName].join("|"),
    layout: stage.dataset.layout || "", design: root.dataset.design || "",
    timeIn: !tr || (tr.left >= sb.left - 1 && tr.right <= sb.right + 1 && tr.top >= sb.top - 1 && tr.bottom <= sb.bottom + 1),
    timeBelow: !tr || !vis(bar) || tr.top >= br.bottom - 1, stageBelow: !vis(bar) || sb.top >= br.bottom - 1,
    local: $("local-time").textContent, hint: $("clock-hint").hidden ? "" : $("clock-hint").textContent, live: $("clock-live").textContent,
    keyO: [...document.querySelectorAll("#keys kbd")].some((k) => k.textContent === "O"),
    overflow: root.scrollWidth - root.clientWidth, vscroll: root.scrollHeight - root.clientHeight, csp: window.__csp || [],
  };
}

async function clockSignalChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    const list = problems.filter(Boolean);
    lines.push(`${label}: ${list.length ? list.join("; ") : "ok"}`);
    if (list.length) found.push(`${label}: ${list.join("; ")}`);
  };
  const errors = (got, msgs) => (got.csp.length || msgs.length ? `Fehler ${JSON.stringify([...got.csp, ...msgs])}` : "");
  const scroll = (got) => (got.overflow > 0 || got.vscroll > 0 ? `Scrollbalken (${got.overflow}/${got.vscroll} px)` : "");
  const answer = (extra = {}) => (ms) => ({ t1: ms / 1000, t2: ms / 1000, synchronised: true, running: true, level: "good",
    accuracy: 0.0004, stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS + PPS", source: null, public: true,
    zone: "Europe/Berlin", ptp_state: "off", holdover: false, holdover_seconds: null, signal: "off", signal_rev: "aaaa00000001",
    ...(typeof extra === "function" ? extra() : extra) });
  const TEXT = { on_air: "ON AIR", rec: "REC" };
  const BORDER = { on_air: "solid", rec: "double" };
  const look = (got, state) => [
    got.shown && got.hasSignal ? "" : "Balken nicht sichtbar",
    got.state === state && got.bodyState === state ? "" : `Zustand ${got.state}/${got.bodyState} statt ${state}`,
    got.text === TEXT[state] ? "" : `Text „${got.text}“ statt „${TEXT[state]}“`,
    got.icon && got.iconHidden === "true" ? "" : "Symbol fehlt oder nicht verborgen",
    got.border === BORDER[state] && got.borderW >= 4 && got.sameColor ? "" : `Rahmen ${got.borderW}px ${got.border}`,
    /^none\|0s\|none\|0s\|none$/.test(got.motion) ? "" : `Bewegung ${got.motion}`,
    got.size >= 12 ? "" : `Schrift ${got.size} px`, got.clipped ? "Text abgeschnitten" : "", got.inPage ? "" : "Balken außerhalb der Seite",
    got.timeIn ? "" : "Zeit außerhalb der Bühne", got.timeBelow && got.stageBelow ? "" : "Balken überdeckt die Bühne",
    got.html ? "HTML im Balken" : ""];

  // --- Matrix: neun Flächen × Zustand und Design ---------------------------------------------------------------
  const WORLD = "layout=world&tz=Europe/London,America/New_York,Asia/Tokyo&tzl=LON,NYC,TYO";
  const VARIANTS = [["onair", "?signal=1", "on_air"], ["rec-studio", "?signal=1&design=studio", "rec"],
    ["onair-tc", "?signal=1&design=tc", "on_air"], ["rec-world", `?signal=1&${WORLD}`, "rec"]];
  const icons = {};
  for (const [width, height] of STUDIO_VIEWPORTS) {
    for (const [name, query, state] of VARIANTS) {
      // Erst ohne Signal, dann schaltet der Server um: Das Layout der Bühne bleibt dasselbe.
      let now = "off";
      const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, query, reply: answer(() => ({ signal: now })) });
      const before = await page.evaluate(signalShown);
      now = state;
      await clock.run(1250);
      const got = await page.evaluate(signalShown);
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/signal_${width}x${height}_${name}.png` });
      await ctx.close();
      icons[state] = got.iconStyle;
      note(`/clock Signal ${name} ${width}×${height} [${got.layout || "?"}]`, [...look(got, state),
        before.shown || before.hasSignal ? "ohne Signal schon sichtbar" : "", scroll(before),
        before.layout === got.layout ? "" : `Layout springt beim Schalten von ${before.layout} auf ${got.layout}`,
        scroll(got), errors(got, msgs)]);
    }
  }
  note("/clock Signal Symbole", [icons.on_air && icons.rec && icons.on_air !== icons.rec ? "" : `ON AIR und REC mit gleichem Symbol (${icons.on_air})`]);
  for (const [width, height, query, state] of [[480, 270, "?signal=1&layout=tile", "on_air"], [240, 135, "?signal=1&layout=tile&design=tc", "rec"],
    [1920, 100, "?signal=1&layout=strip", "on_air"], [1280, 720, "?signal=1&kiosk=1&design=bahnhof", "rec"],
    [1280, 720, "?signal=1&eink=1", "on_air"], [1280, 720, "?signal=1&bg=transparent&layout=tile", "rec"],
    [1280, 720, "?signal=1&until=10:20&cd=main", "on_air"]]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width, height, query, reply: answer({ signal: state }) });
    const got = await page.evaluate(signalShown);
    await ctx.close();
    note(`/clock Signal ${query} ${width}×${height}`, [...look(got, state), scroll(got), errors(got, msgs)]);
  }
  {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1280, height: 720, query: "?signal=1", red: true, reply: answer({ signal: "on_air" }) });
    const got = await page.evaluate(signalShown);
    await ctx.close();
    note("/clock Signal Rotlicht", [...look(got, "on_air"), errors(got, msgs)]);
  }
  // Nachtmodus (Zeitplan dim um 10:15, auch im Profil studio mit fun=0; dimred=1 rot): On Air und REC bleiben rot und
  // voll deckend – gesendet wird gerade nachts.
  for (const [query, state] of [["?signal=1&dim=10-11", "on_air"], ["?signal=1&dim=10-11", "rec"], ["?p=studio&signal=1&dim=10-11", "on_air"],
    ["?signal=1&dim=10-11&dimred=1", "on_air"]]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 1080, query, reply: answer({ signal: state }) });
    const got = await page.evaluate(signalShown);
    const look2 = await page.evaluate(() => { const bar = getComputedStyle(document.getElementById("signal"));
      return { bg: bar.backgroundColor, opacity: bar.opacity, night: document.documentElement.dataset.night || "",
        border: getComputedStyle(document.body).borderTopColor }; });
    await ctx.close();
    const red = (c) => { const m = c.match(/\d+/g) || []; return Number(m[0]) >= 180 && Number(m[1]) < 80 && Number(m[2]) < 80; };
    note(`/clock Signal ${state} im Nachtmodus ${query}`, [look2.night === "1" ? "" : "Nachtmodus nicht an",
      red(look2.bg) ? "" : `Band ${look2.bg}`, red(look2.border) ? "" : `Rahmen ${look2.border}`,
      look2.opacity === "1" ? "" : `Deckkraft ${look2.opacity}`, got.shown ? "" : "Band fehlt", errors(got, msgs)]);
  }

  // Höhen um die Grenze zum automatischen Streifen (Kopfzeile und Band fallen weg): Das Layout ist mit und ohne Signal
  // dasselbe und pendelt nicht zwischen Streifen und Banner.
  for (const height of [170, 180, 186, 190, 194, 200, 230, 244]) {
    let now = "off";
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height, query: "?signal=1", reply: answer(() => ({ signal: now })) });
    const before = await page.evaluate(signalShown);
    now = "rec";
    await clock.run(1250);
    const seen = [];
    for (let i = 0; i < 6; i += 1) {
      seen.push((await page.evaluate(signalShown)).layout);
      await page.waitForTimeout(60);
    }
    const got = await page.evaluate(signalShown);
    now = "off";
    await clock.run(1250);
    const after = await page.evaluate(signalShown);
    await ctx.close();
    note(`/clock Signal 1920×${height} [${before.layout} → ${got.layout} → ${after.layout}]`, [...look(got, "rec"),
      new Set([before.layout, ...seen, got.layout, after.layout]).size === 1 ? "" : `Layout wechselt: ${before.layout}, ${seen.join(", ")}, ${after.layout}`,
      scroll(before), scroll(got), scroll(after), errors(got, msgs)]);
  }

  // --- Nur mit signal=1, Abfragetakt ---------------------------------------------------------------------------
  for (const [query, shown, min, max] of [["?signal=1", true, 9, 12], ["", false, 1, 3], ["?signal=0", false, 1, 3]]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query, reply: answer({ signal: "rec" }) });
    const before = clock.hits;
    await clock.run(10000);
    const polls = clock.hits - before;
    const got = await page.evaluate(signalShown);
    await ctx.close();
    note(`/clock Signal Abfragetakt ${query || "ohne Parameter"}`, [
      got.shown === shown && got.hasSignal === shown ? "" : `Balken sichtbar=${got.shown}, erwartet ${shown}`,
      shown || (got.borderW === 0 && got.bodyState === "off") ? "" : `Rahmen ohne signal=1 (${got.borderW}px)`,
      polls >= min && polls <= max ? "" : `${polls} Abfragen in 10 s (erwartet ${min} bis ${max})`, scroll(got), errors(got, msgs)]);
  }
  {
    // Wechsel am Server: nach höchstens gut einer Sekunde auf dem Bildschirm, einmal angesagt.
    let now = "off";
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?signal=1",
      reply: answer(() => ({ signal: now, signal_rev: `rev-${now}` })) });
    const off = await page.evaluate(signalShown);
    now = "on_air";
    await clock.run(1250);
    const on = await page.evaluate(signalShown);
    now = "rec";
    await clock.run(1250);
    const rec = await page.evaluate(signalShown);
    now = "off";
    await clock.run(1250);
    const gone = await page.evaluate(signalShown);
    await ctx.close();
    note("/clock Signal Wechsel", [off.shown || off.hasSignal || off.live ? `am Anfang sichtbar oder angesagt („${off.live}“)` : "",
      ...look(on, "on_air"), on.live === "On Air" ? "" : `Ansage „${on.live}“`,
      ...look(rec, "rec"), rec.live === "Aufnahme läuft" ? "" : `Ansage „${rec.live}“`,
      gone.shown || gone.hasSignal || gone.borderW ? "nach „off“ noch sichtbar" : "", gone.live === "Signal aus" ? "" : `Ansage „${gone.live}“`,
      on.local.startsWith("10:15:4") ? "" : `Uhr zeigt ${on.local}`, scroll(on), scroll(gone), errors(gone, msgs)]);
  }

  // --- Taste O: lokal, nur dieses Gerät ------------------------------------------------------------------------
  {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, reply: answer({ signal: "off" }) });
    const before = await page.evaluate(signalShown);
    const hits = clock.hits;
    await page.keyboard.press("o");
    await page.waitForTimeout(150);
    const on = await page.evaluate(signalShown);
    await page.keyboard.press("O");
    await page.waitForTimeout(150);
    const off = await page.evaluate(signalShown);
    await ctx.close();
    note("/clock Signal Taste O", [before.shown ? "vor der Taste sichtbar" : "", before.keyO ? "" : "O fehlt in der Übersicht der Kürzel",
      ...look(on, "on_air"), on.note === "nur dieses Gerät" ? "" : `Hinweis „${on.note}“`,
      /nur auf diesem Gerät/.test(on.hint) ? "" : `Kurzhinweis „${on.hint}“`,
      off.shown || off.hasSignal ? "zweite Taste schaltet nicht aus" : "", clock.hits === hits ? "" : "Taste löst eine Abfrage aus",
      scroll(on), errors(off, msgs)]);
  }
  for (const [name, query, central, want, local] of [["mit lock=1", "?lock=1", "off", null, false],
    ["zentrales Signal geht vor", "?signal=1", "rec", "rec", false], ["ohne signal=1 neben zentralem REC", "", "rec", "on_air", true]]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1280, height: 720, query, reply: answer({ signal: central }) });
    await page.keyboard.press("o");
    await page.waitForTimeout(150);
    const got = await page.evaluate(signalShown);
    await ctx.close();
    note(`/clock Signal Taste O ${name}`, [...(want ? look(got, want) : [got.shown || got.hasSignal ? "Balken trotz lock=1" : ""]),
      want && (got.note === "nur dieses Gerät") !== local ? `Hinweis „${got.note}“` : "", errors(got, msgs)]);
  }

  // --- Fremde Werte, fehlende Antwort, Profil ------------------------------------------------------------------
  for (const value of ["ON_AIR", "<b>rec</b>", "standby", 7, null, ["rec"], true]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1280, height: 720, query: "?signal=1", reply: answer({ signal: value }) });
    const got = await page.evaluate(signalShown);
    await ctx.close();
    note(`/clock Signal signal=${JSON.stringify(value)}`, [got.shown || got.hasSignal || got.text ? `zeigt „${got.text}“` : "",
      got.html ? "HTML im Balken" : "", scroll(got), errors(got, msgs)]);
  }
  {
    let failing = false;
    const good = answer({ signal: "on_air" });
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?signal=1",
      reply: (ms) => (failing ? null : good(ms)) });
    const before = await page.evaluate(signalShown);
    failing = true;
    await clock.run(12000);
    const after = await page.evaluate(signalShown);
    failing = false;
    await clock.run(1500);
    const back = await page.evaluate(signalShown);
    await ctx.close();
    note("/clock Signal ohne Antwort", [...look(before, "on_air"), before.stale || before.note ? "vorher schon ungewiss" : "",
      after.shown && after.text === "ON AIR" ? "" : "Zustand verschwindet ohne Antwort",
      after.stale && after.border === "dashed" && /Stand ungewiss/.test(after.note) ? "" : `nicht als ungewiss markiert (${after.border}, „${after.note}“)`,
      after.clipped ? "Text abgeschnitten" : "", scroll(after),
      !back.stale && back.border === "solid" && back.note === "" ? "" : "nach neuer Antwort noch ungewiss",
      msgs.filter((m) => !/503|Failed to load resource/.test(m)).length ? `Fehler ${JSON.stringify(msgs)}` : ""]);
  }
  // „Stand ungewiss“ auf schmalen Flächen: Symbol und Zustand bleiben ganz im Balken, der Hinweis ist nicht abgeschnitten.
  for (const [width, height, query, state, want] of [[240, 135, "?signal=1&layout=tile", "on_air", "ungewiss"],
    [320, 568, "?signal=1", "rec", "ungewiss"], [390, 844, "?signal=1", "on_air", "ungewiss"],
    [480, 270, "?signal=1", "rec", "Stand ungewiss – Server antwortet nicht"]]) {
    let failing = false;
    const good = answer({ signal: state });
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, query, reply: (ms) => (failing ? null : good(ms)) });
    failing = true;
    await clock.run(12000);
    const got = await page.evaluate(signalShown);
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/signal_stale_${width}x${height}.png` });
    await ctx.close();
    note(`/clock Signal ohne Antwort ${width}×${height}`, [got.shown && got.text === TEXT[state] ? "" : `Zustand fehlt („${got.text}“)`,
      got.stale && got.border === "dashed" ? "" : `nicht als ungewiss markiert (${got.border})`,
      got.icon && got.iconIn ? "" : "Symbol außerhalb des Balkens", got.textIn ? "" : "Zustand außerhalb des Balkens",
      got.noteShown === want ? "" : `Hinweis „${got.noteShown}“ statt „${want}“`, got.noteCut ? "Hinweis abgeschnitten" : "",
      got.clipped ? "Balken abgeschnitten" : "", got.inPage ? "" : "Balken außerhalb der Seite", scroll(got),
      msgs.filter((m) => !/503|Failed to load resource/.test(m)).length ? `Fehler ${JSON.stringify(msgs)}` : ""]);
  }
  // Größe: auf 3840×2160 derselbe Anteil der Höhe wie auf 1920×1080; auf einem flachen Streifen größer als die Untergrenze.
  {
    const sizes = {};
    for (const [width, height] of [[1920, 1080], [3840, 2160], [1920, 200]]) {
      const { ctx, page, msgs } = await openPausedClock(browser, { width, height, query: "?signal=1&kiosk=1", reply: answer({ signal: "rec" }) });
      const got = await page.evaluate(signalShown);
      await ctx.close();
      sizes[`${width}x${height}`] = got;
      note(`/clock Signal Größe ${width}×${height}`, [...look(got, "rec"), scroll(got), errors(got, msgs)]);
    }
    const hd = sizes["1920x1080"], uhd = sizes["3840x2160"], flat = sizes["1920x200"];
    note("/clock Signal Größe im Verhältnis", [
      Math.abs(uhd.size / uhd.winH - hd.size / hd.winH) < 0.001 ? "" : `Schrift auf 4K ${uhd.size} px, auf Full HD ${hd.size} px`,
      Math.abs(uhd.borderW / uhd.winH - hd.borderW / hd.winH) < 0.001 ? "" : `Rahmen auf 4K ${uhd.borderW} px, auf Full HD ${hd.borderW} px`,
      flat.size >= 20 ? "" : `Schrift auf 1920×200 nur ${flat.size} px`, flat.borderW >= 8 ? "" : `Rahmen auf 1920×200 nur ${flat.borderW} px`,
      flat.barH <= 0.2 * flat.winH ? "" : `Balken auf 1920×200 ${flat.barH} px hoch`]);
  }
  // Taste O neben dem zentralen Signal: wirkt nicht, der Kurzhinweis sagt es und liegt nicht über dem Balken; nach dem
  // zentralen „Aus“ steht kein lokales „On Air“ da – auch nicht, wenn es vorher lokal an war.
  for (const first of [false, true]) {
    let now = first ? "off" : "rec";
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 480, height: 270, query: "?signal=1&kiosk=1",
      reply: answer(() => ({ signal: now, signal_rev: `rev-${now}` })) });
    let local = null;
    if (first) {
      await page.keyboard.press("o");
      await page.waitForTimeout(150);
      local = await page.evaluate(signalShown);
      now = "rec";
      await clock.run(1200);
    }
    await page.keyboard.press("o");
    await page.waitForTimeout(150);
    const got = await page.evaluate(signalShown);
    now = "off";
    await clock.run(1200);
    const gone = await page.evaluate(signalShown);
    await page.keyboard.press("o");
    await page.waitForTimeout(150);
    const again = await page.evaluate(signalShown);
    await ctx.close();
    note(`/clock Signal Taste O bei zentralem REC${first ? " (vorher lokal an)" : ""}`, [
      !first || (local.text === "ON AIR" && local.note === "nur dieses Gerät") ? "" : "lokales On Air fehlt am Anfang",
      !first || !local.hintOver ? "" : "Kurzhinweis liegt über dem lokalen Balken",
      ...look(got, "rec"), got.note === "" ? "" : `Hinweis im Balken „${got.note}“`,
      /Zentrales Signal ist an/.test(got.hint) ? "" : `Kurzhinweis „${got.hint}“`, got.hintOver ? "Kurzhinweis liegt über dem Balken" : "",
      gone.shown || gone.hasSignal ? `nach zentralem Aus steht „${gone.text} ${gone.note}“` : "",
      again.text === "ON AIR" && again.note === "nur dieses Gerät" ? "" : "nach zentralem Aus schaltet die Taste nicht lokal",
      scroll(got), errors(again, msgs)]);
  }
  {
    const profile = (name) => (name === "regie" ? { name, title: "Regie 1", builtin: false, params: { signal: "1", design: "studio" },
      profiles_rev: "aaaa00000001" } : null);
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1280, height: 720, query: "?p=regie", profile,
      reply: answer({ signal: "rec", profiles_rev: "aaaa00000001" }) });
    const got = await page.evaluate(signalShown);
    await ctx.close();
    note("/clock Signal aus dem Profil", [...look(got, "rec"), got.design === "studio" ? "" : `Design ${got.design}`, scroll(got), errors(got, msgs)]);
  }

  // --- Dashboard: Karte im Reiter „Anzeigen“ am echten Server ---------------------------------------------------
  for (const width of [390, 1440]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await ctx.newPage();
    const msgs = [];
    page.on("console", (m) => { if (m.type() === "error") msgs.push(m.text()); });
    page.on("pageerror", (e) => msgs.push(`pageerror: ${e.message}`));
    const problems = [];
    try {
      await page.goto(`${BASE}/#/uhr/anzeigen`, { waitUntil: "load" });
      await page.waitForSelector("#displays-signal-card", { timeout: 10000 });
      const stateText = () => page.evaluate(() => document.getElementById("displays-signal-state").textContent);
      const server = async () => (await apiJson("/api/v1/time")).signal;
      await page.waitForFunction(() => /^Jetzt: /.test(document.getElementById("displays-signal-state").textContent), null, { timeout: 5000 });
      if (await stateText() !== "Jetzt: aus") problems.push(`Anfang „${await stateText()}“`);
      for (const [state, text] of [["on_air", "Jetzt: ON AIR"], ["rec", "Jetzt: REC – geht um etwa "], ["off", "Jetzt: aus"]]) {
        if (state === "rec") await page.selectOption("#displays-signal-ttl", "300");
        await page.click(`#displays-signal-card button[data-signal="${state}"]`);
        await page.waitForFunction((want) => { const now = document.getElementById("displays-signal-state").textContent;
          return want.endsWith(" ") ? now.startsWith(want) : now === want; }, text, { timeout: 5000 })
          .catch(() => problems.push(`nach „${state}“ steht „…“ statt „${text}“`));
        const now = await server();
        if (now !== state) problems.push(`Server meldet ${now} statt ${state}`);
        if (state !== "rec") continue;
        // Mit Ablaufzeit: Statuszeile und Meldung nennen sie. Über mehrere Neuzeichnungen der Seite (alle 5 s) bleibt
        // der Text stehen – kein „Zustand unbekannt“ dazwischen – und /api/v1/time wird nicht öfter als alle 5 s gelesen.
        const shown = await stateText();
        if (!/^Jetzt: REC – geht um etwa \d{1,2}[:.]\d{2}( [AP]M)? von selbst aus$/.test(shown)) problems.push(`Ablaufzeit fehlt: „${shown}“`);
        const toastText = await page.evaluate(() => document.body.textContent);
        if (!/Signal: REC – aus in 5 min/.test(toastText)) problems.push("Meldung nennt die Ablaufzeit nicht");
        let reads = 0;
        const count = (req) => { if (/\/api\/v1\/time(\?|$)/.test(req.url())) reads += 1; };
        page.on("request", count);
        await page.evaluate(() => {
          window.__signalTexts = [];
          const seen = () => { const node = document.getElementById("displays-signal-state");
            const now = node ? node.textContent : "(fehlt)";
            if (window.__signalTexts[window.__signalTexts.length - 1] !== now) window.__signalTexts.push(now); };
          seen();
          new MutationObserver(seen).observe(document.body, { childList: true, subtree: true, characterData: true });
        });
        await page.waitForTimeout(11500);
        page.off("request", count);
        const texts = await page.evaluate(() => window.__signalTexts);
        if (texts.length !== 1 || texts[0] !== shown) problems.push(`Statuszeile wechselt ohne Anlass: ${JSON.stringify(texts)}`);
        if (reads < 1 || reads > 3) problems.push(`${reads} Abrufe von /api/v1/time in 11,5 s`);
        const label = await page.evaluate(() => document.querySelector('label[for="displays-signal-ttl"]').textContent);
        if (label !== "Beim Setzen: automatisch aus nach") problems.push(`Etikett „${label}“`);
      }
      // Eine schon laufende Zustandsabfrage (alle 5 s) antwortet erst nach dem Schaltbefehl mit dem alten Zustand:
      // Die Karte bleibt beim gerade gesetzten Zustand und nennt die Ablaufzeit weiter.
      {
        let release = () => {};
        const gate = new Promise((resolve) => { release = resolve; });
        let held = 0;
        const slow = async (route) => {
          const response = await route.fetch();   // der Zustand vor dem Schalten
          held += 1;
          await gate;
          await route.fulfill({ response });
        };
        await page.route("**/api/v1/time", slow);
        const until = Date.now() + 8000;
        while (!held && Date.now() < until) await page.waitForTimeout(100);
        if (!held) problems.push("keine Zustandsabfrage in 8 s");
        await page.click('#displays-signal-card button[data-signal="on_air"]');
        await page.waitForFunction(() => /^Jetzt: ON AIR – geht um etwa /.test(document.getElementById("displays-signal-state").textContent),
          null, { timeout: 5000 }).catch(() => problems.push("nach dem Schalten steht nicht „ON AIR“ mit Ablaufzeit"));
        const set = await stateText();
        release();
        await page.waitForTimeout(1200);
        await page.unroute("**/api/v1/time", slow);
        const after = await stateText();
        if (after !== set) problems.push(`ältere Abfrage überschreibt den Schaltbefehl: „${after}“ statt „${set}“`);
        await page.waitForTimeout(5500);   // die nächste Abfrage bestätigt den Zustand
        if (await stateText() !== set) problems.push(`nach der nächsten Abfrage „${await stateText()}“ statt „${set}“`);
        await page.click('#displays-signal-card button[data-signal="off"]');
        await page.waitForFunction(() => document.getElementById("displays-signal-state").textContent === "Jetzt: aus", null, { timeout: 5000 })
          .catch(() => problems.push("„Aus“ nach der verzögerten Abfrage wirkt nicht"));
      }
      const card = await page.evaluate(() => {
        const node = document.getElementById("displays-signal-card");
        const buttons = [...node.querySelectorAll("button[data-signal]")];
        return { buttons: buttons.map((b) => b.textContent), pressed: buttons.some((b) => b.hasAttribute("aria-pressed")),
          described: buttons.every((b) => b.getAttribute("aria-describedby") === "displays-signal-state"),
          small: buttons.some((b) => b.getBoundingClientRect().height < 24), info: Boolean(node.querySelector("button.info, .info")),
          text: node.textContent, overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
      });
      if (JSON.stringify(card.buttons) !== JSON.stringify(["ON AIR", "REC", "Aus"])) problems.push(`Knöpfe ${JSON.stringify(card.buttons)}`);
      if (card.pressed || !card.described) problems.push("Knöpfe mit Umschalter-Zustand oder ohne Bezug zum Zustandstext");
      if (card.small) problems.push("Knopf niedriger als 24 px");
      if (!/kein Tally/.test(card.text)) problems.push("Hinweis „kein Tally“ fehlt");
      if (card.overflow > 0) problems.push(`Überbreite ${card.overflow} px`);
      if (SHOTS) await page.locator("#displays-signal-card").screenshot({ path: `${SHOTS}/signal_anzeigen_${width}.png` });
    } catch (error) {
      problems.push(`Abbruch: ${error.message.split("\n")[0]}`);
    }
    await apiJson("/api/v1/clock/signal", { state: "off" });
    if (msgs.length) problems.push(`Fehler ${JSON.stringify(msgs)}`);
    await ctx.close();
    note(`#/uhr/anzeigen On-Air-Signal ${width}`, problems);
  }
  return { found, lines };
}

// Studiouhr B3 und B5 (clockStatusChecks, TOUR_STATUS_ONLY=1): Statuszeile, Kachel und Prüfbild aus
// docs/konzept/studiouhr.md (Abschnitte 2.6, 2.7, Akzeptanz B). Mit angehaltener Playwright-Uhr (page.clock) und
// gemocktem /api/v1/time steht die Serverzeit fest (10:15:42).
// Statuszeile: ptp_state und holdover als Marken im Band – Symbol und Text, in der Seite, ohne Überbreite; ausgeschaltetes
// PTP, unbekannte und fremde Werte (Kennung, HTML) zeigen nichts; ?show= ohne status blendet Marken und Zustandszeile
// aus; ohne Antwort des Servers verschwinden sie.
// Kachel (?layout=tile): Titel des Profils oben links, Zustandssymbol (bei Holdover zusätzlich „H“) oben rechts, Countdown
// mit Symbol – alles in der Bühne, nichts überdeckt die Zeit oder einander, kein Scrollbalken.
// Prüfbild (?test=sync): Warnhinweis sichtbar; die Fläche wechselt nur an der Sekundengrenze der angezeigten Zeit, über
// sechs Sekunden genau sechsmal; Pfeiltaste ändert den Vorlauf; Esc beendet und schreibt lead= in die Adresse – auch mit
// lock=1; aus Profil und gemerktem Stand startet es nicht; bei „weniger Bewegung“ und auf E-Ink nur der Hinweistext
// (auch bei wenig Höhe). /clock?test=sync nimmt den gemerkten Stand als Grundlage und merkt den Vorlauf dort; mit Profil
// steht ein eingemessener Wert 0 als lead=0 in der Adresse; hinter dem Prüfbild ruhen die Kürzel der Uhr; mit lock=1
// nennt der Text keine Pfeiltasten; Knöpfe und Texte wachsen mit der Fläche. Die Dauer des Holdovers im Band steht in
// einem Element mit aria-live="off".
function statusState() {
  const root = document.documentElement;
  const stage = document.getElementById("clock-stage");
  const sb = stage.getBoundingClientRect();
  const vis = (n) => {
    if (!n) return false;
    const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };
  const rect = (n) => { const r = n.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, w: r.width, h: r.height }; };
  const inStage = (n) => { const r = n.getBoundingClientRect();
    return r.left >= sb.left - 1 && r.right <= sb.right + 1 && r.top >= sb.top - 1 && r.bottom <= sb.bottom + 1; };
  const inPage = (n) => { const r = n.getBoundingClientRect(); return r.left >= -1 && r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1; };
  const apart = (a, b) => { const x = a.getBoundingClientRect(); const y = b.getBoundingClientRect();
    return x.right <= y.left + 1 || y.right <= x.left + 1 || x.bottom <= y.top + 1 || y.bottom <= x.top + 1; };
  const $ = (id) => document.getElementById(id);
  const chip = (id) => (vis($(id)) ? { text: $(id).textContent.replace(/\s+/g, " ").trim(), icon: $(id).querySelector(".clock-chip-icon").textContent.trim(),
    hidden: $(id).querySelector(".clock-chip-icon").getAttribute("aria-hidden"), level: $(id).dataset.level || "", state: $(id).dataset.state || "",
    inPage: inPage($(id)), size: parseFloat(getComputedStyle($(id)).fontSize), title: $(id).getAttribute("title") || "" } : null);
  const time = [$("local-time"), $("face")].find(vis) || null;
  const title = $("tile-title");
  const sync = $("clock-sync-icon");
  const hold = $("clock-hold");
  const cd = $("cd");
  const test = $("sync-test");
  const flash = $("sync-test-flash");
  return {
    layout: stage.dataset.layout || "", band: vis($("band")), bandStatus: vis($("band-status")),
    ptp: chip("chip-ptp"), hold: chip("chip-hold"), html: document.querySelectorAll("#band b, #band img, #band script").length,
    syncLine: vis($("clock-sync")), syncText: $("clock-sync-text").textContent,
    title: vis(title) ? { text: title.textContent, box: rect(title), inStage: inStage(title), size: parseFloat(getComputedStyle(title).fontSize),
      clipped: title.scrollWidth > title.clientWidth + 1 } : null,
    titleText: title.textContent, barTitle: vis($("clock-title")) ? $("clock-title").textContent : "",
    barTitleClipped: vis($("clock-title")) && $("clock-title").scrollWidth > $("clock-title").clientWidth + 1,
    syncIcon: vis(sync) ? { text: sync.textContent.trim(), inStage: inStage(sync), box: rect(sync) } : null,
    holdIcon: vis(hold) ? { text: hold.querySelector(".clock-hold-icon").textContent, label: $("clock-hold-text").textContent,
      inStage: inStage(hold), box: rect(hold) } : null,
    time: time ? { text: time.id === "local-time" ? time.textContent : "", inStage: inStage(time), box: rect(time) } : null,
    cd: vis(cd) ? { icon: $("cd-icon").textContent.trim(), iconShown: vis($("cd-icon")), text: $("cd-time").textContent, inStage: inStage(cd),
      level: cd.dataset.level, oneLine: (() => { const i = $("cd-icon").getBoundingClientRect(); const t = $("cd-time").getBoundingClientRect();
        const mid = (i.top + i.bottom) / 2; return mid > t.top && mid < t.bottom && i.right <= t.left + 1; })() } : null,
    apart: {
      titleTime: !(vis(title) && time) || apart(title, time), titleSync: !(vis(title) && vis(sync)) || apart(title, sync),
      titleHold: !(vis(title) && vis(hold)) || apart(title, hold), syncTime: !(vis(sync) && time) || apart(sync, time),
      holdSync: !(vis(hold) && vis(sync)) || apart(hold, sync), cdTime: !(vis(cd) && time) || apart(cd, time),
      titleCd: !(vis(title) && vis(cd)) || apart(title, cd),
    },
    test: { shown: vis(test), mode: test.dataset.mode || "", inStage: vis(test) ? inStage(test) : true,
      warn: vis($("sync-test-warn")) ? $("sync-test-warn").textContent.replace(/\s+/g, " ").trim() : "",
      warnSize: vis($("sync-test-warn")) ? parseFloat(getComputedStyle($("sync-test-warn")).fontSize) : 0,
      warnIn: !vis($("sync-test-warn")) || inStage($("sync-test-warn")),
      flash: vis(flash), on: flash.dataset.on, sec: $("sync-test-sec").textContent, bg: getComputedStyle(flash).backgroundColor,
      area: vis(flash) ? Math.round(flash.getBoundingClientRect().width * flash.getBoundingClientRect().height) : 0,
      motion: `${getComputedStyle(flash).transitionDuration}|${getComputedStyle(flash).animationName}`,
      note: vis($("sync-test-note")) ? $("sync-test-note").textContent : "", noteText: $("sync-test-note").textContent,
      lead: $("sync-test-lead").textContent, stop: vis($("sync-test-stop")) && inStage($("sync-test-stop")), tone: vis($("sync-test-tone")),
      steps: vis($("sync-test-less")) || vis($("sync-test-more")), pressed: $("sync-test-tone").getAttribute("aria-pressed"),
      noteIn: vis($("sync-test-note")) && inStage($("sync-test-note")), noteSize: parseFloat(getComputedStyle($("sync-test-note")).fontSize),
      stopSize: parseFloat(getComputedStyle($("sync-test-stop")).fontSize), stopH: $("sync-test-stop").getBoundingClientRect().height },
    design: root.dataset.design || "", inert: $("clock-main").inert === true, cdShown: vis(cd),
    holdSince: { live: $("chip-hold-since").getAttribute("aria-live"), text: $("chip-hold-since").textContent, main: $("chip-hold-text").textContent },
    stored: (() => { try { return localStorage.getItem("ntp-gui-clock-custom"); } catch (e) { return null; } })(),
    local: $("local-time").textContent, search: window.location.search, hint: $("clock-hint").hidden ? "" : $("clock-hint").textContent,
    overflow: root.scrollWidth - root.clientWidth, vscroll: root.scrollHeight - root.clientHeight, csp: window.__csp || [],
  };
}

async function clockStatusChecks(browser) {
  const found = [];
  const lines = [];
  const note = (label, problems) => {
    const list = problems.filter(Boolean);
    lines.push(`${label}: ${list.length ? list.join("; ") : "ok"}`);
    if (list.length) found.push(`${label}: ${list.join("; ")}`);
  };
  const errors = (got, msgs) => (got.csp.length || msgs.length ? `Fehler ${JSON.stringify([...got.csp, ...msgs])}` : "");
  const scroll = (got) => (got.overflow > 0 || got.vscroll > 0 ? `Scrollbalken (${got.overflow}/${got.vscroll} px)` : "");
  const answer = (extra = {}) => (ms) => ({ t1: ms / 1000, t2: ms / 1000, synchronised: true, running: true, level: "good",
    accuracy: 0.0004, stratum: 1, leap: "Normal", leap_next: null, source_kind: "GPS + PPS", source: null, public: true,
    zone: "Europe/Berlin", ptp_state: "off", holdover: false, holdover_seconds: null, ...extra });
  const profileOf = (params = {}, title = "Regie 1") => (name) => (name === "regie"
    ? { name, title, builtin: false, params, profiles_rev: "aaaa00000001" } : null);
  const M = "−";

  // --- Statuszeile ---------------------------------------------------------------------------------------------
  for (const [width, height] of [[1920, 1080], [390, 844], [768, 1024]]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width, height,
      reply: answer({ ptp_state: "locked", holdover: true, holdover_seconds: 185 }) });
    const got = await page.evaluate(statusState);
    await ctx.close();
    note(`/clock Statuszeile ${width}×${height}`, [
      got.band && got.bandStatus ? "" : "Marken im Band nicht sichtbar",
      got.ptp && got.ptp.text === "◆ PTP eingerastet" ? "" : `PTP „${got.ptp && got.ptp.text}“`,
      got.ptp && got.ptp.icon && got.ptp.hidden === "true" && got.ptp.level === "good" && got.ptp.state === "locked" ? "" : `PTP-Symbol ${JSON.stringify(got.ptp)}`,
      got.hold && got.hold.text === "H Holdover seit 3 min" ? "" : `Holdover „${got.hold && got.hold.text}“`,
      got.hold && got.hold.icon === "H" && got.hold.hidden === "true" && got.hold.title ? "" : "Holdover ohne Symbol oder Erklärung",
      // Die Dauer wechselt jede Minute: Im Band (Live-Region) steht sie in einem Element, das nicht angesagt wird.
      got.holdSince.live === "off" && got.holdSince.text === "seit 3 min" && got.holdSince.main === "Holdover" ? "" : `Dauer des Holdovers ${JSON.stringify(got.holdSince)}`,
      got.ptp && got.hold && got.ptp.inPage && got.hold.inPage ? "" : "Marke außerhalb der Seite",
      got.ptp && got.ptp.size >= 12 ? "" : `Schrift ${got.ptp && got.ptp.size} px`,
      got.holdIcon ? "Holdover-Symbol der Kachel trotz Band" : "",
      got.local.startsWith("10:15:42") ? "" : `Uhr zeigt ${got.local}`, scroll(got), errors(got, msgs)]);
  }
  const TEXTS = { master: "◈ PTP Grandmaster", locked: "◆ PTP eingerastet", acquiring: "◇ PTP sucht", passive: "◇ PTP passiv",
    fault: "✕ PTP gestört", down: "✕ PTP antwortet nicht" };
  for (const [state, want] of [...Object.entries(TEXTS), ["off", null], ["unknown", null], ["LOCKED", null],
    ["<b>locked</b>", null], ["001b21.fffe.8a4c7e", null], [null, null], [7, null]]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1280, height: 720, reply: answer({ ptp_state: state }) });
    const got = await page.evaluate(statusState);
    await ctx.close();
    note(`/clock Statuszeile ptp_state=${JSON.stringify(state)}`, [
      want ? (got.ptp && got.ptp.text === want ? "" : `zeigt „${got.ptp && got.ptp.text}“ statt „${want}“`)
        : (got.ptp || got.bandStatus ? `zeigt „${got.ptp && got.ptp.text}“` : ""),
      got.hold ? "Holdover ohne Holdover" : "", got.html ? "HTML im Band" : "", scroll(got), errors(got, msgs)]);
  }
  for (const [name, extra, want] of [["ohne Dauer", { holdover: true, holdover_seconds: null }, "H Holdover"],
    ["unter einer Minute", { holdover: true, holdover_seconds: 12 }, "H Holdover seit < 1 min"],
    ["Stunden", { holdover: true, holdover_seconds: 7500 }, "H Holdover seit 2 h 5 min"],
    ["Text statt Dauer", { holdover: true, holdover_seconds: "<img src=x>" }, "H Holdover"],
    ["unbekannt", { holdover: null }, null], ["Text statt Wahrheitswert", { holdover: "true" }, null]]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1280, height: 720, reply: answer(extra) });
    const got = await page.evaluate(statusState);
    await ctx.close();
    note(`/clock Statuszeile Holdover ${name}`, [
      want ? (got.hold && got.hold.text === want ? "" : `zeigt „${got.hold && got.hold.text}“ statt „${want}“`) : (got.hold ? `zeigt „${got.hold.text}“` : ""),
      got.html ? "HTML im Band" : "", errors(got, msgs)]);
  }
  for (const [query, shown] of [["?show=time,seconds,date", false], ["?show=time,status", true], ["", true]]) {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1280, height: 720, query,
      reply: answer({ ptp_state: "master", holdover: true, holdover_seconds: 60 }) });
    const got = await page.evaluate(statusState);
    await ctx.close();
    note(`/clock Statuszeile ${query || "ohne show"}`, [
      Boolean(got.ptp) === shown && Boolean(got.hold) === shown ? "" : `Marken sichtbar=${Boolean(got.ptp)}/${Boolean(got.hold)}, erwartet ${shown}`,
      got.syncLine === shown ? "" : `Zustandszeile sichtbar=${got.syncLine}`, got.band ? "" : "Band fehlt", errors(got, msgs)]);
  }
  {
    // Der Server antwortet nicht mehr: Der Zustand ist unbekannt, die Marken verschwinden.
    let failing = false;
    const good = answer({ ptp_state: "locked", holdover: true, holdover_seconds: 185 });
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, reply: (ms) => (failing ? null : good(ms)) });
    const before = await page.evaluate(statusState);
    failing = true;
    await clock.run(12000);
    const after = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Statuszeile ohne Antwort", [before.ptp && before.hold ? "" : "Marken fehlen vorher",
      after.ptp || after.hold || after.bandStatus ? "Marken trotz fehlender Antwort" : "",
      msgs.filter((m) => !/503|Failed to load resource/.test(m)).length ? `Fehler ${JSON.stringify(msgs)}` : ""]);
  }

  // --- Kachel --------------------------------------------------------------------------------------------------
  // Serverzeit 10:15:42, Ziel 10:20 → −04:18 (unter 5 min: Stufe warn, Symbol △).
  for (const [width, height] of [[480, 270], [240, 135], [1280, 720], [1920, 1080], [3840, 2160], [640, 200]]) {
    for (const [name, extra, design] of [["Titel, Holdover, Countdown", "&until=10:20", ""], ["Countdown groß", "&until=10:20&cd=main", ""],
      ["Studio", "&until=10:20", "&design=studio"], ["Timecode", "", "&design=tc"]]) {
      const { ctx, page, msgs } = await openPausedClock(browser, { width, height, query: `?p=regie&layout=tile${extra}${design}`,
        profile: profileOf(), reply: answer({ ptp_state: "master", holdover: true, holdover_seconds: 185 }) });
      const got = await page.evaluate(statusState);
      await ctx.close();
      const a = got.apart;
      const main = name === "Countdown groß";
      note(`/clock Kachel ${width}×${height} ${name}`, [
        got.layout === "tile" ? "" : `Layout ${got.layout}`, got.band ? "Band sichtbar" : "", got.barTitle ? "Kopfzeile sichtbar" : "",
        got.title && got.title.text === "Regie 1" ? "" : `Titel „${got.title && got.title.text}“`,
        got.title && got.title.inStage && got.title.size >= 12 ? "" : `Titel außerhalb oder zu klein (${got.title && got.title.size} px)`,
        got.title && got.title.box.left < width / 2 && got.title.box.top < height / 2 ? "" : "Titel nicht oben links",
        got.syncIcon && got.syncIcon.text === "✓" && got.syncIcon.inStage ? "" : `Zustandssymbol ${JSON.stringify(got.syncIcon)}`,
        got.syncIcon && got.syncIcon.box.left > width / 2 && got.syncIcon.box.top < height / 2 ? "" : "Zustandssymbol nicht oben rechts",
        got.holdIcon && got.holdIcon.text === "H" && got.holdIcon.inStage && got.holdIcon.label === "Holdover seit 3 min" ? "" : `Holdover-Symbol ${JSON.stringify(got.holdIcon)}`,
        main ? (got.time ? "Uhrzeit trotz cd=main groß" : "") : (got.time && got.time.inStage ? "" : "Zeit außerhalb der Bühne"),
        main || design || (got.time && got.time.text.startsWith("10:15:42")) ? "" : `Uhr zeigt ${got.time && got.time.text}`,
        // Titel und Countdown dürfen die Zeit nicht erdrücken: Sie bleibt der Hauptinhalt der Kachel.
        main || !got.time || got.time.box.h >= (design === "&design=studio" ? 0.3 : 0.2) * height ? "" : `Zeit nur ${Math.round(got.time.box.h)} px hoch`,
        extra ? (got.cd && got.cd.text === `${M}04:18` && got.cd.icon === "△" && got.cd.iconShown && got.cd.inStage && got.cd.level === "warn" ? "" : `Countdown ${JSON.stringify(got.cd)}`) : "",
        extra && got.cd && !got.cd.oneLine ? "Symbol und Restzeit nicht in einer Zeile" : "",
        Object.entries(a).filter(([, ok]) => !ok).map(([key]) => key).join(", ") ? `überdeckt: ${Object.entries(a).filter(([, ok]) => !ok).map(([key]) => key).join(", ")}` : "",
        scroll(got), errors(got, msgs)]);
    }
  }
  {
    // Langer Titel: eine Zeile mit Auslassung, nie unter den Symbolen. Ohne Profil: kein Titel, keine leere Zeile.
    const long = await openPausedClock(browser, { width: 240, height: 135, query: "?p=regie&layout=tile",
      profile: profileOf({}, "Regie 1 – Hauptabendprogramm Studio Nord"), reply: answer({ holdover: true, holdover_seconds: 60 }) });
    const gotLong = await long.page.evaluate(statusState);
    await long.ctx.close();
    const plain = await openPausedClock(browser, { width: 480, height: 270, query: "?layout=tile", reply: answer() });
    const gotPlain = await plain.page.evaluate(statusState);
    await plain.ctx.close();
    // 470×340: Seit 1.10 bleibt die Leiste bei wenig Höhe einzeilig – bei 470×400 bliebe der Bühne genug Höhe für das
    // normale Layout (wie in 1.9 ohne Titel), die Kachel greift erst darunter.
    const auto = await openPausedClock(browser, { width: 470, height: 340, query: "?p=regie", profile: profileOf(), reply: answer({ holdover: true }) });
    const gotAuto = await auto.page.evaluate(statusState);
    await auto.ctx.close();
    note("/clock Kachel langer Titel", [gotLong.title && gotLong.title.clipped && gotLong.title.box.h < 2.2 * gotLong.title.size ? "" : `Titel ${JSON.stringify(gotLong.title)}`,
      gotLong.apart.titleSync && gotLong.apart.titleHold && gotLong.apart.titleTime ? "" : "Titel überdeckt etwas", scroll(gotLong), errors(gotLong, long.msgs)]);
    note("/clock Kachel ohne Profil", [gotPlain.title ? `Titel „${gotPlain.title.text}“` : "", gotPlain.holdIcon ? "Holdover-Symbol ohne Holdover" : "",
      gotPlain.syncIcon && gotPlain.syncIcon.text === "✓" ? "" : "Zustandssymbol fehlt", gotPlain.time && gotPlain.time.inStage ? "" : "Zeit außerhalb",
      scroll(gotPlain), errors(gotPlain, plain.msgs)]);
    // Automatische Kachel (kleines Fenster ohne ?layout=tile): Kopfzeile und Band bleiben, der Titel steht in der Kopfzeile.
    note(`/clock Kachel automatisch [${gotAuto.layout}]`, [gotAuto.layout === "tile" ? "" : "kein Layout tile", gotAuto.title ? "Titel doppelt (Bühne und Kopfzeile)" : "", gotAuto.barTitle === "Regie 1" ? "" : `Kopfzeile „${gotAuto.barTitle}“`,
      gotAuto.barTitleClipped ? "Titel in der einzeiligen Kopfzeile abgeschnitten" : "",
      gotAuto.hold && !gotAuto.holdIcon ? "" : "Holdover nicht im Band", errors(gotAuto, auto.msgs)]);
  }
  {
    // Automatischer Streifen (ohne Band): Holdover als Symbol in der Zeile, die Zeit bleibt in der Bühne.
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1920, height: 100, query: "?until=10:20",
      reply: answer({ holdover: true, holdover_seconds: 185 }) });
    const got = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Streifen 1920×100 Holdover", [got.layout === "strip" ? "" : `Layout ${got.layout}`,
      got.holdIcon && got.holdIcon.inStage && got.syncIcon && got.syncIcon.inStage ? "" : "Symbole fehlen oder ragen heraus",
      got.apart.holdSync && got.apart.syncTime && got.apart.cdTime ? "" : "Überdeckung", got.time && got.time.inStage ? "" : "Zeit außerhalb",
      scroll(got), errors(got, msgs)]);
  }

  // --- Prüfbild ------------------------------------------------------------------------------------------------
  const stepFlash = async (page, clock, ms, each = 100) => {
    const seen = [];
    // Erst eine halbe Schrittweite: Die Proben fallen dann nie genau auf eine Sekundengrenze.
    await page.clock.runFor(each / 2);
    clock.advanced += each / 2;
    for (let done = 0; done < ms; done += each) {
      await page.clock.runFor(each);
      clock.advanced += each;
      await page.waitForTimeout(25);
      seen.push(await page.evaluate(() => ({ on: document.getElementById("sync-test-flash").dataset.on,
        sec: document.getElementById("sync-test-sec").textContent, local: document.getElementById("local-s").textContent })));
    }
    return seen;
  };
  for (const [width, height, query] of [[1920, 1080, "?test=sync&lead=40"], [390, 844, "?test=sync"], [480, 270, "?test=sync&layout=tile"],
    [1920, 200, "?test=sync"], [1280, 720, "?test=sync&design=studio&kiosk=1"], [3840, 2160, "?test=sync&bg=transparent"]]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width, height, query, reply: answer() });
    const got = await page.evaluate(statusState);
    const seen = await stepFlash(page, clock, 6000);
    await ctx.close();
    const changes = seen.filter((item, i) => i > 0 && item.on !== seen[i - 1].on).length;
    const offBeat = seen.filter((item, i) => i > 0 && (item.on !== seen[i - 1].on) !== (item.sec !== seen[i - 1].sec)).length;
    const parity = seen.filter((item) => (item.on === "1") !== (Number(item.sec) % 2 === 0)).length;
    const behind = seen.filter((item) => item.sec !== item.local).length;
    let run = 0; let shortest = Infinity;
    for (let i = 1; i < seen.length; i += 1) {
      run += 1;
      if (seen[i].on !== seen[i - 1].on) { if (i > run) shortest = Math.min(shortest, run); run = 0; }
    }
    note(`/clock Prüfbild ${width}×${height} ${query}`, [
      got.test.shown && got.test.mode === "run" && got.test.flash ? "" : `nicht aktiv (${JSON.stringify([got.test.shown, got.test.mode, got.test.flash])})`,
      /^⚠ Achtung: .*Esc beendet\.$/.test(got.test.warn) && got.test.warnIn && got.test.warnSize >= 12 ? "" : `Warnhinweis „${got.test.warn}“ (${got.test.warnSize} px, in Bühne ${got.test.warnIn})`,
      got.test.inStage && got.test.stop ? "" : "Prüfbild oder Knopf „Beenden“ außerhalb der Bühne",
      got.test.stopSize >= 12 ? "" : `Knöpfe nur ${got.test.stopSize} px`,
      // 4K ohne Skalierung: Knöpfe, Warnhinweis und Erklärtext wachsen mit der Fläche.
      width < 3840 || (got.test.stopSize >= 24 && got.test.stopH >= 48 && got.test.warnSize >= 36 && got.test.noteSize >= 30) ? ""
        : `auf 4K zu klein (Knopf ${got.test.stopSize} px, ${Math.round(got.test.stopH)} px hoch, Warnhinweis ${got.test.warnSize} px, Text ${got.test.noteSize} px)`,
      got.inert ? "" : "Uhr hinter dem Prüfbild nicht inert",
      got.test.area >= 3000 ? "" : `Fläche nur ${got.test.area} px²`,
      got.test.motion === "0s|none" ? "" : `Übergang oder Animation (${got.test.motion})`,
      changes === 6 ? "" : `${changes} Wechsel in 6 s statt 6`,
      offBeat ? `${offBeat} Wechsel nicht an der Sekundengrenze` : "", parity ? `${parity}× falsche Seite (gerade Sekunde = hell)` : "",
      behind ? `${behind}× Sekunde der Fläche ≠ Sekunde der Uhr` : "",
      shortest >= 9 ? "" : `Wechsel nach nur ${shortest * 100} ms (schneller als 1 Hz)`,
      scroll(got), errors(got, msgs)]);
  }
  {
    // Vorlauf mit den Pfeiltasten, Esc beendet und schreibt lead= in die Adresse.
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1920, height: 1080, query: "?design=studio&test=sync&lead=40", reply: answer() });
    const before = await page.evaluate(statusState);
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("ArrowLeft");
    await clock.run(250);
    const stepped = await page.evaluate(statusState);
    for (let i = 0; i < 30; i += 1) await page.keyboard.press("ArrowDown");
    await clock.run(250);
    const floor = await page.evaluate(statusState);
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Escape");
    await clock.run(500);
    const ended = await page.evaluate(statusState);
    const quiet = await stepFlash(page, clock, 2500);
    await ctx.close();
    note("/clock Prüfbild Vorlauf und Esc", [
      before.test.lead === "Vorlauf 40 ms · im Link: lead=40" ? "" : `Vorlauf „${before.test.lead}“`,
      stepped.test.lead === "Vorlauf 50 ms · im Link: lead=50" && /Vorlauf 50 ms/.test(stepped.syncText) ? "" : `nach den Pfeiltasten „${stepped.test.lead}“ / „${stepped.syncText}“`,
      floor.test.lead === "Vorlauf 0 ms · im Link: lead=0" ? "" : `Untergrenze „${floor.test.lead}“`,
      ended.test.shown ? "Esc beendet nicht" : "", ended.search === "?design=studio&lead=30" ? "" : `Adresse „${ended.search}“`,
      ended.hint === "Prüfbild beendet" ? "" : `Hinweis „${ended.hint}“`,
      new Set(quiet.map((item) => item.on)).size === 1 ? "" : "Fläche wechselt nach dem Beenden weiter",
      ended.inert ? "Uhr nach dem Beenden noch inert" : "", ended.stored === null ? "" : `gemerkter Stand „${ended.stored}“ ohne Panel`,
      ended.time && ended.time.inStage ? "" : "Uhr nach dem Beenden nicht sichtbar", errors(ended, msgs)]);
  }
  {
    // lock=1: keine Knöpfe und keine Pfeiltasten für den Vorlauf, aber Esc beendet.
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?test=sync&lock=1&lead=20", reply: answer() });
    const before = await page.evaluate(statusState);
    await page.keyboard.press("ArrowRight");
    await clock.run(250);
    const stepped = await page.evaluate(statusState);
    await page.keyboard.press("Escape");
    await clock.run(250);
    const ended = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Prüfbild lock=1", [before.test.shown && before.test.mode === "run" ? "" : "nicht aktiv", before.test.steps ? "Knöpfe für den Vorlauf trotz lock=1" : "",
      stepped.test.lead === "Vorlauf 20 ms · im Link: lead=20" ? "" : `Pfeiltaste wirkt trotz lock=1 („${stepped.test.lead}“)`,
      /Pfeiltasten/.test(before.test.note) || !/gesperrt \(lock=1\).*lead= im Link/.test(before.test.note) ? `Text fordert zu gesperrter Bedienung auf: „${before.test.note}“` : "",
      ended.test.shown ? "Esc beendet nicht" : "", ended.search === "?lock=1&lead=20" ? "" : `Adresse „${ended.search}“`, errors(ended, msgs)]);
  }
  {
    // Knopf „Beenden“ und der Klick (in der Prüfung ohne Tonausgabe: nur der Zustand des Knopfs).
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?test=sync", reply: answer() });
    await page.click("#sync-test-tone");
    await clock.run(1250);
    const toned = await page.evaluate(statusState);
    await page.click("#sync-test-more");
    await page.click("#sync-test-stop");
    await clock.run(250);
    const ended = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Prüfbild Knöpfe", [toned.test.pressed === "true" ? "" : "Ton-Klick nicht eingeschaltet", ended.test.shown ? "Knopf beendet nicht" : "",
      ended.search === "?lead=10" ? "" : `Adresse „${ended.search}“`, errors(ended, msgs)]);
  }
  {
    // Gemerkter Stand (Panel „Anpassen“): /clock?test=sync misst genau diese Anzeige ein. Design und Vorlauf kommen aus
    // dem Stand, der eingemessene Wert wird dort gemerkt, die Adresse bleibt /clock – auch nach dem Neuladen.
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?test=sync",
      storage: { "ntp-gui-clock-custom": "design=studio&lead=80" }, reply: answer() });
    const before = await page.evaluate(statusState);
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Escape");
    await clock.run(500);
    const ended = await page.evaluate(statusState);
    await page.reload({ waitUntil: "load" });
    await clock.run(1500);
    const again = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Prüfbild mit gemerktem Stand", [before.test.shown && before.test.mode === "run" ? "" : "nicht aktiv",
      before.design === "studio" ? "" : `Design ${before.design} statt des gemerkten`,
      before.test.lead === "Vorlauf 80 ms · im Link: lead=80" ? "" : `Vorlauf „${before.test.lead}“`,
      ended.test.shown ? "Esc beendet nicht" : "", ended.search === "" ? "" : `Adresse „${ended.search}“`,
      ended.stored === "design=studio&lead=90" ? "" : `gemerkter Stand „${ended.stored}“`,
      ended.hint === "Prüfbild beendet · Vorlauf 90 ms gemerkt" ? "" : `Hinweis „${ended.hint}“`,
      ended.design === "studio" && /Vorlauf 90 ms/.test(ended.syncText) ? "" : `nach dem Beenden ${ended.design} / „${ended.syncText}“`,
      again.design === "studio" && /Vorlauf 90 ms/.test(again.syncText) && !again.test.shown ? "" : `nach dem Neuladen ${again.design} / „${again.syncText}“`,
      errors(again, msgs)]);
  }
  {
    // Profil mit eigenem Vorlauf: Auf 0 eingemessen steht lead=0 in der Adresse – nach dem Neuladen gilt nicht wieder das Profil.
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?p=regie&test=sync",
      profile: profileOf({ lead: "40" }), reply: answer() });
    for (let i = 0; i < 4; i += 1) await page.keyboard.press("ArrowLeft");
    await clock.run(250);
    const floor = await page.evaluate(statusState);
    await page.keyboard.press("Escape");
    await clock.run(250);
    const ended = await page.evaluate(statusState);
    await page.reload({ waitUntil: "load" });
    await clock.run(1500);
    const again = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Prüfbild Profil auf 0 eingemessen", [floor.test.lead === "Vorlauf 0 ms · im Link: lead=0" ? "" : `Vorlauf „${floor.test.lead}“`,
      ended.search === "?p=regie&lead=0" ? "" : `Adresse „${ended.search}“`,
      /Vorlauf/.test(again.syncText) ? `nach dem Neuladen „${again.syncText}“` : "", again.test.shown ? "Prüfbild startet wieder" : "", errors(again, msgs)]);
  }
  {
    // Hinter dem Prüfbild ruhen die Kürzel der Uhr: keine Stoppuhr, kein anderes Design oder Layout, keine andere Größe.
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?test=sync", reply: answer() });
    const before = await page.evaluate(statusState);
    const scale = () => page.evaluate(() => document.documentElement.style.getPropertyValue("--clock-scale"));
    const scaleBefore = await scale();
    for (const key of ["Space", "d", "l", "u", "t", "+", "r"]) await page.keyboard.press(key);
    await clock.run(2500);
    const during = await page.evaluate(statusState);
    await page.keyboard.press("?");
    await clock.run(250);
    const help = await page.evaluate(() => !document.getElementById("keys").hidden);
    await page.keyboard.press("Escape");
    await clock.run(250);
    const helpClosed = await page.evaluate(statusState);
    await page.keyboard.press("Escape");
    await clock.run(250);
    const ended = await page.evaluate(statusState);
    const scaleAfter = await scale();
    // Danach wirken die Kürzel wieder.
    await page.keyboard.press("d");
    await clock.run(250);
    const after = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Prüfbild Tastenkürzel", [before.inert ? "" : "Uhr nicht inert",
      during.test.shown && during.design === before.design && during.layout === before.layout && !during.hint ? "" : `Kürzel wirken hinter dem Prüfbild (${during.design}, ${during.layout}, „${during.hint}“)`,
      help ? "" : "Hilfe (?) öffnet nicht", helpClosed.test.shown ? "" : "Esc schließt mit der Hilfe auch das Prüfbild",
      ended.test.shown ? "Esc beendet nicht" : "", ended.cdShown ? `Stoppuhr läuft nach dem Beenden (${JSON.stringify(ended.cd)})` : "",
      ended.design === before.design && ended.layout === before.layout && scaleAfter === scaleBefore ? "" : `Anzeige verändert (${ended.design}, ${ended.layout}, ${scaleAfter})`,
      ended.search === "" ? "" : `Adresse „${ended.search}“`, ended.inert ? "Uhr noch inert" : "",
      after.design !== before.design ? "" : "Kürzel D wirkt nach dem Beenden nicht", errors(after, msgs)]);
  }
  {
    // Nur lead= in der Adresse, im Panel ein anderer Stand gemerkt: Auf 0 eingemessen bleibt lead=0 stehen – nach dem
    // Neuladen gilt nicht der gemerkte Stand mit seinem Vorlauf.
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?lead=20&test=sync",
      storage: { "ntp-gui-clock-custom": "design=studio&lead=80" }, reply: answer() });
    const before = await page.evaluate(statusState);
    for (let i = 0; i < 2; i += 1) await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("Escape");
    await clock.run(500);
    const ended = await page.evaluate(statusState);
    await page.reload({ waitUntil: "load" });
    await clock.run(1500);
    const again = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Prüfbild nur lead= auf 0 eingemessen", [before.design !== "studio" && before.test.lead === "Vorlauf 20 ms · im Link: lead=20" ? "" : `Anfang ${before.design} / „${before.test.lead}“`,
      ended.search === "?lead=0" ? "" : `Adresse „${ended.search}“`, ended.stored === "design=studio&lead=80" ? "" : `gemerkter Stand „${ended.stored}“`,
      again.design === before.design && !/Vorlauf/.test(again.syncText) && !again.test.shown ? "" : `nach dem Neuladen ${again.design} / „${again.syncText}“`,
      errors(again, msgs)]);
  }
  {
    // „Weniger Bewegung“ wechselt mitten im Einmessen hin und zurück: Das Prüfbild hält an und läuft wieder; der schon
    // eingemessene Vorlauf steht nach Esc trotzdem als lead= in der Adresse.
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?design=tc&test=sync", reply: answer() });
    for (let i = 0; i < 3; i += 1) await page.keyboard.press("ArrowRight");
    await clock.run(250);
    const mode = () => page.evaluate(() => document.getElementById("sync-test").dataset.mode || "");
    const media = async (value, want) => {
      for (let round = 0; round < 3 && await mode() !== want; round += 1) {
        await page.emulateMedia({ reducedMotion: value });
        for (let i = 0; i < 10 && await mode() !== want; i += 1) await clock.run(100);
        if (await mode() !== want) await page.emulateMedia({ reducedMotion: value === "reduce" ? "no-preference" : "reduce" });
      }
      return mode();
    };
    const less = await media("reduce", "reduced");
    const lessState = await page.evaluate(statusState);
    const back = await media("no-preference", "run");
    const backState = await page.evaluate(statusState);
    await page.keyboard.press("Escape");
    await clock.run(500);
    const ended = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Prüfbild weniger Bewegung mitten im Einmessen", [less === "reduced" ? "" : `Modus ${less} nach dem Wechsel auf „weniger Bewegung“`,
      lessState.test.flash ? "Fläche sichtbar trotz „weniger Bewegung“" : "", back === "run" ? "" : `Modus ${back} nach dem Zurückschalten`,
      backState.test.lead === "Vorlauf 30 ms · im Link: lead=30" ? "" : `Vorlauf „${backState.test.lead}“`,
      ended.test.shown ? "Esc beendet nicht" : "", ended.search === "?design=tc&lead=30" ? "" : `Adresse „${ended.search}“`, errors(ended, msgs)]);
  }
  {
    // Panel „Anpassen“ bei laufendem Prüfbild: „Link kopieren“ nimmt test=sync nicht mit (das Formular hat kein Feld dafür).
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, query: "?test=sync",
      storage: { "ntp-gui-clock-custom": "design=studio&lead=30" }, reply: answer() });
    await ctx.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
    await page.click("#mode-custom");
    await clock.run(250);
    const field = await page.evaluate(() => Boolean(document.getElementById("custom-test")));
    await page.click("#custom-copy");
    await clock.run(500);
    const copied = await page.evaluate(async () => {
      const status = document.getElementById("custom-status").textContent;
      let text = "";
      try { text = await navigator.clipboard.readText(); } catch (error) { /* ohne Zwischenablage steht der Link in der Meldung */ }
      return { status, text };
    });
    const got = await page.evaluate(statusState);
    await ctx.close();
    const linkText = /\/clock/.test(copied.text) ? copied.text : copied.status;
    note("/clock Prüfbild Link kopieren ohne test=", [field ? "Formular hat ein Feld für test" : "",
      /\/clock\?design=studio&lead=30(\s|$|[^&\w])/.test(`${linkText} `) ? "" : `kopierter Link „${linkText}“`,
      /test=/.test(linkText) ? "Link enthält test=" : "", got.test.shown ? "" : "Prüfbild endet durch das Kopieren", errors(got, msgs)]);
  }
  // Nie ohne ausdrücklichen Parameter: nicht aus dem Profil, nicht aus dem gemerkten Stand, nicht ohne test=.
  for (const [name, opts] of [["aus dem Profil", { query: "?p=regie", profile: profileOf({ design: "studio", test: "sync" }) }],
    ["aus dem gemerkten Stand", { query: "", storage: { "ntp-gui-clock-custom": "design=flip&test=sync" } }],
    ["ohne Parameter", { query: "?design=studio" }], ["falscher Wert", { query: "?test=1" }], ["Großschreibung", { query: "?test=SYNC" }]]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, reply: answer(), ...opts });
    const got = await page.evaluate(statusState);
    const seen = await stepFlash(page, clock, 2500);
    await ctx.close();
    note(`/clock Prüfbild ${name}`, [got.test.shown ? "Prüfbild gestartet" : "", new Set(seen.map((item) => item.on)).size === 1 ? "" : "Fläche wechselt",
      got.time && got.time.inStage ? "" : "Uhr nicht sichtbar", errors(got, msgs)]);
  }
  // Profil mit ausdrücklichem Parameter in der Adresse: Dann gilt er.
  {
    const { ctx, page, msgs } = await openPausedClock(browser, { width: 1280, height: 720, query: "?p=regie&test=sync",
      profile: profileOf({ design: "studio", lead: "30" }), reply: answer() });
    const got = await page.evaluate(statusState);
    await ctx.close();
    note("/clock Prüfbild Profil und Adresse", [got.test.shown && got.test.mode === "run" ? "" : "nicht aktiv",
      got.test.lead === "Vorlauf 30 ms · im Link: lead=30" ? "" : `Vorlauf „${got.test.lead}“`, errors(got, msgs)]);
  }
  // „Weniger Bewegung“ und E-Ink: kein Blitz, nur der Hinweistext; Esc schließt ihn.
  for (const [name, opts, text] of [["weniger Bewegung", { query: "?test=sync", reduced: true }, /^Das Prüfbild startet nicht: Dein System wünscht weniger Bewegung/],
    ["weniger Bewegung in der Kachel", { query: "?test=sync&layout=tile", reduced: true, width: 480, height: 270 }, /weniger Bewegung/],
    ["weniger Bewegung 480×270", { query: "?test=sync", reduced: true, width: 480, height: 270 }, /weniger Bewegung/],
    ["weniger Bewegung 1920×200", { query: "?test=sync", reduced: true, width: 1920, height: 200 }, /weniger Bewegung/],
    ["E-Ink 480×270", { query: "?test=sync&eink=1", width: 480, height: 270 }, /^Das Prüfbild gibt es auf E-Ink nicht/],
    ["E-Ink 1920×200", { query: "?test=sync&eink=1", width: 1920, height: 200 }, /^Das Prüfbild gibt es auf E-Ink nicht/],
    ["E-Ink", { query: "?test=sync&eink=1" }, /^Das Prüfbild gibt es auf E-Ink nicht/]]) {
    const { ctx, page, msgs, clock } = await openPausedClock(browser, { width: 1280, height: 720, reply: answer(), ...opts });
    const got = await page.evaluate(statusState);
    const seen = await stepFlash(page, clock, 3000);
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Escape");
    await clock.run(250);
    const ended = await page.evaluate(statusState);
    await ctx.close();
    note(`/clock Prüfbild ${name}`, [got.test.shown ? "" : "Hinweis fehlt", got.test.mode !== "run" ? "" : "Modus run",
      got.test.flash ? "Fläche sichtbar" : "", got.test.warn ? "Warnhinweis ohne Blitz" : "", got.test.tone || got.test.steps ? "Knöpfe für Ton oder Vorlauf sichtbar" : "",
      // Der Hinweistext ist hier der ganze Inhalt: sichtbar, in der Bühne und lesbar – auch bei wenig Höhe.
      text.test(got.test.note) ? "" : `Hinweistext nicht sichtbar („${got.test.note}“)`,
      got.test.noteIn && got.test.noteSize >= 12 ? "" : `Hinweistext außerhalb der Bühne oder zu klein (${got.test.noteSize} px)`,
      got.test.stop ? "" : "Knopf „Beenden“ fehlt",
      new Set(seen.map((item) => item.on)).size === 1 && seen[0].on === "0" ? "" : "Fläche wechselt trotzdem",
      ended.test.shown ? "Esc schließt den Hinweis nicht" : "", /lead=/.test(ended.search) ? `Adresse „${ended.search}“` : "", scroll(got), errors(got, msgs)]);
  }
  return { found, lines };
}

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

// 1.9 Korrekturen: (a) bei 390 px brechen lange Rechnernamen und Pfade in Statusband und Hinweisen um, statt am
// Kartenrand abgeschnitten zu werden; (b) bei 390 px liegt ein per Tab erreichtes Element nie hinter der unteren
// Leiste bzw. der Speicherleiste der Einstellungen; (c) bei 2000 und 2560 px liegt der Wert einer kv-Zeile nicht
// über den halben Bildschirm neben seiner Bezeichnung (TOUR_FIXES_ONLY=1 prüft nur das).
const LONG_NAME = "zeitquelle-im-rechenzentrum-mit-sehr-langem-namen.standort.beispiel.example.org";
async function layoutFixChecks(browser) {
  const found = [];
  const lines = [];
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await ctx.newPage();
    await page.route("**/api/status*", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.insights = [
        { level: "crit", key: "unreach:long", action: "sources", title: `${LONG_NAME} antwortet nicht`,
          text: `Die Quelle ${LONG_NAME} antwortet nicht; Datei /var/lib/chrony/${LONG_NAME}/zertifikat.pem fehlt.` },
        ...HERO_INSIGHTS.slice(1, 3)];
      await route.fulfill({ response, json: body });
    });
    await page.goto(`${BASE}/#/`, { waitUntil: "load" });
    await page.waitForSelector("#main .hero", { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const toggle = await page.$("#main .hero .hint-summary");
    if (toggle) { await toggle.click(); await page.waitForTimeout(500); }
    const cut = await page.evaluate(() => [...document.querySelectorAll("#main .verdict-title h2, #main .hint-title, #main .hint-text")]
      .filter((n) => n.getClientRects().length)
      .map((n) => ({ cls: n.className || n.tagName, over: n.scrollWidth - n.clientWidth,
        right: Math.round(n.getBoundingClientRect().right - (n.closest(".card, .hero")?.getBoundingClientRect().right ?? innerWidth)) }))
      .filter((x) => x.over > 1 || x.right > 1));
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    lines.push(`lange Namen 390: abgeschnitten=${cut.length} ovf=${overflow}`);
    if (cut.length || overflow > 0) found.push(`390 lange Namen abgeschnitten ${JSON.stringify(cut.slice(0, 3))} ovf=${overflow}`);
    await ctx.close();
  }
  for (const [route, dirty] of [["#/system/einstellungen", false], ["#/system/einstellungen", true], ["#/system/diagnose", false]]) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 700 } });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/${route}`, { waitUntil: "load" });
    await page.waitForTimeout(2500);
    if (dirty) {
      // Speicherleiste einblenden: ein Textfeld ändern (wird nicht gespeichert).
      const input = await page.$("#main input[type=text]:not([readonly]):not([disabled])");
      if (input) { await input.focus(); await page.keyboard.type("x"); await page.waitForTimeout(400); }
    }
    let hidden = 0;
    let checked = 0;
    const samples = [];
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    for (let i = 0; i < 60; i += 1) {
      await page.keyboard.press("Tab");
      await page.waitForTimeout(40);
      const got = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body || !el.closest("#main")) return null;
        const r = el.getBoundingClientRect();
        if (!r.height) return null;
        const covers = [...document.querySelectorAll(".bottombar, .save-bar:not([hidden])")]
          .filter((c) => getComputedStyle(c).display !== "none" && !c.contains(el))
          .map((c) => c.getBoundingClientRect().top);
        const limit = Math.min(innerHeight, ...covers);
        return { top: Math.round(r.top), bottom: Math.round(r.bottom), limit: Math.round(limit), what: el.tagName + (el.className ? `.${String(el.className).split(" ")[0]}` : "") };
      });
      if (!got) continue;
      checked += 1;
      if (got.bottom > got.limit + 1) { hidden += 1; if (samples.length < 3) samples.push(got); }
    }
    lines.push(`Fokus 390 ${route}${dirty ? " (Speicherleiste)" : ""}: geprüft=${checked} verdeckt=${hidden}`);
    if (hidden) found.push(`390 ${route}${dirty ? " mit Speicherleiste" : ""}: Fokus hinter der unteren Leiste ${JSON.stringify(samples)}`);
    await ctx.close();
  }
  for (const width of [2000, 2560]) {
    const ctx = await browser.newContext({ viewport: { width, height: 1200 } });
    for (const route of ["#/system/diagnose", "#/uhr/hardware", "#/system/einstellungen", "#/quellen"]) {
      const page = await ctx.newPage();
      await page.goto(`${BASE}/${route}`, { waitUntil: "load" });
      await page.waitForTimeout(2000);
      const rows = await page.evaluate(() => [...document.querySelectorAll("#main .kv")]
        .filter((row) => row.getClientRects().length && row.querySelector("dt") && row.querySelector("dd"))
        .map((row) => {
          const dt = row.querySelector("dt").getBoundingClientRect();
          const dd = row.querySelector("dd").getBoundingClientRect();
          return Math.round(dd.right - dt.left);
        }));
      const widest = rows.length ? Math.max(...rows) : 0;
      lines.push(`kv ${width} ${route}: Zeilen=${rows.length} breiteste=${widest}`);
      if (widest > 900) found.push(`${width} ${route}: kv-Zeile ${widest} px breit (Bezeichnung und Wert zu weit auseinander)`);
      await page.close();
    }
    await ctx.close();
  }
  return { found, lines };
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

// Hilfe mit Unterseiten (1.11, helpChecks, einzeln mit TOUR_HELP_ONLY=1) bei 390 und 1440 px: Inhaltsverzeichnis
// mit allen Themen, Unterseite per Klick, vorheriges/nächstes Thema, „Zurück“ im Browser (Adresse und Ansicht),
// tiefer Link #/hilfe/gps/pps (Eintrag hervorgehoben und im Bild), alter Link #/hilfe?t=pps, unbekanntes Thema,
// Suche über alle Themen mit Sprung auf den Treffer, „Mehr in der Hilfe“ aus einem ⓘ, Verweis unter einer Seite,
// keine Überbreite, Tippflächen der neuen Links ≥ 24 px. Fotos mit TOUR_SHOTS.
async function helpChecks(browser) {
  const found = [];
  const lines = [];
  for (const width of [390, 1440]) {
    const height = width === 390 ? 844 : 900;
    const ctx = await browser.newContext({ viewport: { width, height } });
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(e.message));
    const shot = async (name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/hilfe-${name}-${width}.png`, fullPage: false }); };
    const go = async (hash) => { await page.evaluate((h) => { location.hash = h; }, hash); await page.waitForTimeout(700); };
    const state = () => page.evaluate(() => {
      const visible = (n) => Boolean(n && n.offsetParent !== null);
      const focus = document.querySelector(".gloss.is-focus");
      const r = focus?.getBoundingClientRect();
      return { hash: location.hash, toc: document.querySelectorAll(".help-toc a").length,
        topic: visible(document.querySelector(".help-topic")) ? document.querySelector(".help-topic h2")?.textContent : null,
        focus: focus ? focus.id : null, focusInView: Boolean(r && r.top >= 0 && r.top < innerHeight),
        notFound: [...document.querySelectorAll("#main .empty-note")].some((n) => visible(n) && /gibt es nicht/.test(n.textContent)),
        results: visible(document.querySelector(".help-groups")) ? document.querySelectorAll(".help-groups .gloss").length : 0,
        overflow: document.documentElement.scrollWidth - innerWidth };
    });
    const small = () => page.evaluate(() => [...document.querySelectorAll(".help-toc a, .help-crumbs a, .gloss-link, .help-pager a, .help-see a, .page-help a")]
      .filter((n) => n.offsetParent !== null).map((n) => ({ t: n.textContent.trim().slice(0, 30), r: n.getBoundingClientRect() }))
      .filter(({ r }) => r.height < 24 || r.width < 24).map(({ t, r }) => `${t} ${Math.round(r.width)}×${Math.round(r.height)}`));
    await page.goto(`${BASE}/#/hilfe`, { waitUntil: "load" });
    await page.waitForTimeout(1200);
    const topics = await page.evaluate(async () => (await import("/static/js/helpnav.js")).TOPICS.map((t) => t.id));
    let s = await state();
    if (s.toc !== topics.length) found.push(`${width} Inhaltsverzeichnis: ${s.toc} Links statt ${topics.length}`);
    if (s.overflow > 0) found.push(`${width} #/hilfe: Überbreite ${s.overflow} px`);
    found.push(...(await small()).map((x) => `${width} #/hilfe: Tippfläche zu klein: ${x}`));
    await shot("inhalt");
    // Unterseite per Klick, dann nächstes Thema, dann zweimal „Zurück“.
    await page.click('.help-toc a[href="#/hilfe/betrieb"]');
    await page.waitForTimeout(700);
    s = await state();
    if (s.hash !== "#/hilfe/betrieb" || s.topic !== "Betrieb und Überwachung") found.push(`${width} Klick auf Thema: ${JSON.stringify(s)}`);
    if (s.overflow > 0) found.push(`${width} #/hilfe/betrieb: Überbreite ${s.overflow} px`);
    found.push(...(await small()).map((x) => `${width} #/hilfe/betrieb: Tippfläche zu klein: ${x}`));
    await shot("betrieb");
    const next = topics[topics.indexOf("betrieb") + 1];
    await page.click('.help-pager a[rel="next"]');
    await page.waitForTimeout(700);
    s = await state();
    if (s.hash !== `#/hilfe/${next}`) found.push(`${width} nächstes Thema: ${s.hash} statt #/hilfe/${next}`);
    await page.goBack();
    await page.waitForTimeout(700);
    s = await state();
    if (s.hash !== "#/hilfe/betrieb" || s.topic !== "Betrieb und Überwachung") found.push(`${width} Zurück auf das Thema: ${JSON.stringify(s)}`);
    await page.goBack();
    await page.waitForTimeout(700);
    s = await state();
    if (s.hash !== "#/hilfe" || s.toc !== topics.length || s.topic) found.push(`${width} Zurück ins Inhaltsverzeichnis: ${JSON.stringify(s)}`);
    await page.goForward();
    await page.waitForTimeout(700);
    s = await state();
    if (s.hash !== "#/hilfe/betrieb") found.push(`${width} Vor: ${s.hash}`);
    // Tiefer Link und alter Link.
    await go("#/hilfe/gps/pps");
    await page.waitForTimeout(600);
    s = await state();
    if (s.topic !== "GPS" || s.focus !== "h-pps" || !s.focusInView) found.push(`${width} tiefer Link #/hilfe/gps/pps: ${JSON.stringify(s)}`);
    await shot("gps-pps");
    await go("#/hilfe?t=dhcp42");
    await page.waitForTimeout(600);
    s = await state();
    if (s.hash !== "#/hilfe?t=dhcp42" || s.focus !== "h-dhcp42" || !s.focusInView) found.push(`${width} alter Link #/hilfe?t=dhcp42: ${JSON.stringify(s)}`);
    await go("#/hilfe/gibtsnicht");
    s = await state();
    if (!s.notFound || s.toc !== topics.length) found.push(`${width} unbekanntes Thema: ${JSON.stringify(s)}`);
    // Suche über alle Themen; ein Treffer springt auf seine Unterseite, die Suche ist danach leer.
    await go("#/hilfe/betrieb");
    await page.fill(".help-search", "Falseticker");
    await page.waitForTimeout(300);
    s = await state();
    if (!s.results || s.topic) found.push(`${width} Suche: ${JSON.stringify(s)}`);
    await shot("suche");
    const target = await page.getAttribute('.help-groups .gloss-link[href$="/state_falseticker"]', "href");
    await page.click('.help-groups .gloss-link[href$="/state_falseticker"]');
    await page.waitForTimeout(900);
    s = await state();
    const query = await page.inputValue(".help-search");
    if (s.hash !== target || s.focus !== "h-state_falseticker" || s.results || query) found.push(`${width} Treffer der Suche: ${JSON.stringify({ ...s, query, target })}`);
    // „Mehr in der Hilfe“ aus einem ⓘ und der Verweis unter einer Seite.
    await go("#/quellen");
    await page.waitForTimeout(800);
    const more = await page.evaluate(() => {
      for (const button of document.querySelectorAll("#main button.info")) {
        button.click();
        const link = document.querySelector(".popover .popover-more");
        if (link) return { href: link.getAttribute("href"), text: link.textContent };
        button.click();
      }
      return null;
    });
    if (!more || !/^#\/hilfe\/[a-z0-9-]+\/[a-z0-9_]+$/.test(more.href) || !/Mehr in der Hilfe/.test(more.text)) {
      found.push(`${width} ⓘ ohne tiefen Hilfe-Link: ${JSON.stringify(more)}`);
    } else {
      if (width === 390) await shot("popover");
      await page.click(".popover .popover-more");
      await page.waitForTimeout(900);
      s = await state();
      if (s.hash !== more.href || s.focus !== `h-${more.href.split("/").pop()}` || !s.focusInView) found.push(`${width} ⓘ-Link: ${JSON.stringify({ ...s, href: more.href })}`);
    }
    await go("#/uhr/ptp");
    await page.waitForTimeout(500);
    const pageLink = await page.evaluate(() => document.querySelector("#main .page-help a")?.getAttribute("href") || null);
    if (pageLink !== "#/hilfe/ptp") found.push(`${width} Verweis unter #/uhr/ptp: ${pageLink}`);
    if (errors.length) found.push(`${width} Hilfe Seitenfehler: ${errors.join(" | ")}`);
    lines.push(`hilfe ${width}: ${found.length ? "Befund" : "ok"}`);
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
    if (process.env.TOUR_TIMER_ONLY) {
      const result = await clockTimerChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_EXTRAS_ONLY) {
      const result = await clockExtrasChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_FUN_ONLY) {
      const result = await clockFunChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_TC_ONLY) {
      const result = await clockTimecodeChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_STATUS_ONLY) {
      const result = await clockStatusChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_SIGNAL_ONLY) {
      await apiJson("/api/setup", { action: "done" });
      const result = await clockSignalChecks(browser);
      console.log(JSON.stringify(result, null, 1));
      process.exitCode = result.found.length ? 1 : 0;
      return;
    }
    if (process.env.TOUR_WORLD_ONLY) {
      const result = await clockWorldChecks(browser);
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
    // Hilfe: ohne Assistent – #/hilfe öffnet ihn nie von selbst.
    if (process.env.TOUR_HELP_ONLY) {
      const result = await helpChecks(browser);
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
    if (process.env.TOUR_FIXES_ONLY) {
      const result = await layoutFixChecks(browser);
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
    const helpResult = await helpChecks(browser);
    nav.found.push(...helpResult.found);
    nav.lines.push(...helpResult.lines);
    const layoutResult = await layoutFixChecks(browser);
    nav.found.push(...layoutResult.found);
    nav.lines.push(...layoutResult.lines);
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
