// Einstieg: Navigation, Aktualisierung, Datencache, Neustart-Anzeige.
import { el, apiGet, storageGet, storageSet, fmtTime, fmtServerDateTime, serverZone, staleText, isNum, serverClock, serverNow, reloadSettled } from "./util.js";
import { toast, isPopoverOpen, infoButton, badge } from "./ui.js";
import { resetChartState, setChartMarkers } from "./charts.js";
import * as overview from "./pages/overview.js";
import * as sources from "./pages/sources.js";
import * as gps from "./pages/gps.js";
import * as ptp from "./pages/ptp.js";
import * as clockquality from "./pages/clockquality.js";
import * as hardware from "./pages/hardware.js";
import * as displays from "./pages/displays.js";
import * as clients from "./pages/clients.js";
import * as diagnose from "./pages/diagnose.js";
import * as notify from "./pages/notify.js";
import * as settings from "./pages/settings.js";
import * as setup from "./pages/setup.js";
import * as help from "./pages/help.js";
import * as muster from "./pages/muster.js";
import { t, initI18n, setLanguage, language, LANGUAGES, onLanguageChange } from "./i18n.js";
import { NAV, resolve, route, tabsOf, navOf, stampEntry, hashChange } from "./routes.js";
import { createShortcuts, shortcutList } from "./shortcuts.js";
import { captureFocus, restoreFocus, renderGate } from "./focus.js";

// Routentabelle, alte Routen und Reiter stehen in routes.js (ohne DOM, in Node getestet).
const MODULES = { overview, sources, gps, clients, clockquality, hardware, ptp, displays, diagnose, notify, settings, setup, help, muster };

// ?dev=1 in der Adresse (vor oder nach dem #) schaltet die Entwicklerseiten frei.
function devMode() {
  const hashQuery = window.location.hash.split("?")[1] || "";
  return new URLSearchParams(window.location.search).get("dev") === "1" || new URLSearchParams(hashQuery).get("dev") === "1";
}

function pageTitle(page) {
  return page.title || t(page.titleKey);
}

const state = {
  status: null,
  history: [],
  range: storageGet("ntp-gui-range", 3600),
  uiState: {},
  cache: new Map(),
  timer: null,
  failed: 0,
  reload: null,
  lastOk: null,   // Serverzeit (ms) der letzten erfolgreichen Abfrage – für „veraltet seit …“
  clock: null,    // Serverzeit und Browserzeit beim letzten Status – die Browseruhr kann falsch gehen
};

const main = document.getElementById("main");
const nav = document.getElementById("nav");

// #/<seite>/<unterpfad> – der Unterpfad (z. B. die Adresse auf #/clients/192.0.2.5) geht als
// ctx.subpath an die Seite. Alte Routen löst resolve() zu ihrem Ziel auf; die Adresszeile stellt
// redirectLegacy() um.
function currentRoute() {
  let found = resolve(window.location.hash, devMode());
  if (found.redirect) found = resolve(found.redirect, devMode());
  return found.redirect ? resolve("#/") : found;
}

function currentPage() {
  const page = currentRoute().page;
  return { ...page, module: MODULES[page.id] };
}

// Alte Lesezeichen (#/ptp, #/einstellungen?s=gps, #/hardware/…): Adresse ersetzen, ohne Verlaufseintrag.
// Der folgende hashchange zeichnet die neue Seite.
function redirectLegacy() {
  const found = resolve(window.location.hash, devMode());
  if (!found.redirect) return false;
  window.location.replace(found.redirect);
  return true;
}

// --- Datencache für seitenbezogene Abfragen ---------------------------------
function data(key, url, ttlSeconds) {
  const entry = state.cache.get(key);
  const now = Date.now();
  // Ein Fehler gilt ttlSeconds lang (bei 0: 5 s) – sonst fragte die Seite nach einem 404 bei jedem
  // Neuzeichnen neu.
  const fresh = entry && entry.url === url && (entry.data !== undefined
    ? ttlSeconds === 0 || now - entry.time < ttlSeconds * 1000
    : Boolean(entry.error) && now - entry.time < (ttlSeconds || 5) * 1000);
  if (!fresh && !(entry && entry.pending && entry.url === url)) {
    const same = entry?.url === url;
    const record = { url, pending: true, time: entry?.time || 0, data: same ? entry.data : undefined,
      error: same ? entry.error || null : null };
    state.cache.set(key, record);
    apiGet(url).then((result) => {
      Object.assign(record, { data: result, time: Date.now(), pending: false, error: null });
      render({ background: true });
    }).catch((error) => {
      const known = record.error;
      Object.assign(record, { pending: false, time: Date.now(), error: { status: error.status || 0, message: error.message } });
      // Nur neu zeichnen, wenn der Fehler neu ist – sonst hinge die Seite in einer Schleife.
      if (!known || known.status !== record.error.status) render({ background: true });
    });
  }
  const current = state.cache.get(key);
  return current && current.url === url ? current.data : undefined;
}

// Letzter Fehler einer Abfrage ({status, message}) – z. B. 404, damit eine Seite „keine Daten“
// statt endlos „Lade …“ zeigen kann. null, solange die letzte Abfrage geklappt hat.
function dataError(key, url) {
  const entry = state.cache.get(key);
  return entry && entry.url === url && entry.data === undefined ? entry.error || null : null;
}

function invalidate(key) { state.cache.delete(key); }

// --- Rendern -----------------------------------------------------------------
let pendingAfter = [];

// Tastaturfokus, Cursor und Markierung über das Neuzeichnen retten: focus.js.
// Neuzeichnen im Hintergrund (Refresh, nachgeladene Daten, Fenstergröße) wartet, solange jemand in einem
// Zahlenfeld oder einer Auswahlliste ist oder einen Zeiger in #main gedrückt hält (renderGate in focus.js).
// Nachgeholt wird erst nach dem Fokuswechsel bzw. nach dem Klick (setTimeout 0 nach pointerup läuft nach
// dem click-Ereignis): Dann kennt captureFocus() das neue Feld, und der Klick traf noch sein Element.
const gate = renderGate(() => setTimeout(() => { if (gate.deferred) render({ background: true }); }, 0));
main.addEventListener("pointerdown", () => gate.pointerDown(), true);
for (const type of ["pointerup", "pointercancel"]) window.addEventListener(type, () => gate.pointerUp(), true);
window.addEventListener("blur", () => gate.pointerUp());
main.addEventListener("focusout", () => gate.focusOut());

// Seiten mit Zeitdiagrammen – nur dort werden Ereignismarker geladen.
const CHART_PAGES = new Set(["overview", "sources", "gps", "ptp", "clients", "clockquality", "muster"]);
const MARKER_RANGE = 31 * 86400;

function render({ background = false } = {}) {
  if (gate.blocks(background, main, document.activeElement)) return;
  const route = currentRoute();
  const page = currentPage();
  state.shown = page;
  document.title = `${pageTitle(page)} · ${state.status?.system?.title || "ntp-gui"}`;
  markActive(page);
  renderTabs(page);
  if (!state.status && !["help", "settings", "muster"].includes(page.id)) {
    main.replaceChildren(el("p", { class: "empty-note", text: t("app.connecting_server") }));
    return;
  }
  const scroll = window.scrollY;
  pendingAfter = [];
  // 1.6 (T7): Ereignismarker für alle Zeitdiagramme der Seite (höchstens 31 Tage, einmal je Minute).
  setChartMarkers(CHART_PAGES.has(page.id) ? data("chart-markers", `/api/timeline/markers?range=${MARKER_RANGE}`, 60)?.markers : []);
  const ctx = {
    status: state.status || {},
    history: state.history,
    range: state.range,
    uiState: state.uiState,
    subpath: route.sub,
    readonly: Boolean(state.status?.ui?.readonly),
    setRange: (seconds) => { state.range = seconds; storageSet("ntp-gui-range", seconds); refresh(); },
    rerender: () => render(),
    afterRender: (fn) => pendingAfter.push(fn),
    data, dataError, invalidate,
    watchReload,
    refresh: () => refresh(),
  };
  let nodes;
  try {
    nodes = page.module.render(ctx);
  } catch (error) {
    console.error(error);
    nodes = [el("p", { class: "empty-note", text: t("app.render_error", { message: error.message }) })];
  }
  const focus = captureFocus(main, document.activeElement);
  main.replaceChildren(...nodes.filter(Boolean));
  for (const fn of pendingAfter) { try { fn(); } catch (error) { console.error(error); } }
  restoreFocus(main, focus, document.activeElement, document.body);
  window.scrollTo(0, scroll);
}

function renderHeader() {
  const status = state.status;
  const pill = document.getElementById("sync-pill");
  const label = document.getElementById("sync-label");
  if (!status) return;
  const sys = status.system || {};
  document.getElementById("title").textContent = sys.title || "ntp-gui";
  document.getElementById("hostname").textContent = sys.hostname || "";
  // Handy: sichtbar nur „NTP-GUI“ – voller Titel und Rechnername im Titelattribut und im „Mehr“-Menü.
  document.getElementById("title-wrap")?.setAttribute("title", [sys.title, sys.hostname].filter(Boolean).join(" · "));
  renderMoreHost();
  // Uhrzeit des Servers, nicht die des Browsers (sys.timezone ist nur die Abkürzung, z. B. „CEST“).
  const zone = serverZone(sys) ? sys.timezone || "" : "UTC";
  document.getElementById("clock").textContent = `${fmtServerDateTime(sys, language() === "en" ? "en-GB" : "de-DE")} ${zone}`;
  // Dieselbe Bewertung wie das Statusband der Übersicht – Kopfzeile und Übersicht
  // dürfen sich nie widersprechen. Schmal: nur Punkt + Kurztext.
  const v = overview.verdict(status, status.insights || []);
  pill.dataset.state = v.tone;
  label.replaceChildren(el("span", { class: "pill-long", text: v.pill }), el("span", { class: "pill-short", text: v.pillShort }));
  pill.title = v.title;
  const serious = (status.insights || []).filter((i) => i.level === "warn" || i.level === "crit");
  // Übersicht zählt alle Probleme, „Hardware“ nur die aus dem Hardware-Check.
  setBadge("overview", serious.length);
  setBadge("uhr", serious.filter((i) => i.action === "hardware").length);
  renderUpdateBanner(status.update);
  document.getElementById("footer-note").textContent =
    t("app.footer", { version: sys.version || "", time: fmtTime(sys.time, true, serverZone(sys) ? sys : 0),
      seconds: sys.refresh_seconds });
}

// --- Update-Hinweis (opt-in) ---------------------------------------------------
// Nur ein Link nach github.com/mgc20/ntp-gui – der Server baut ihn aus der geprüften Versionsnummer.
const RELEASE_LINK = /^https:\/\/github\.com\/mgc20\/ntp-gui\/releases(\/tag\/v[0-9A-Za-z.-]+)?$/;

function renderUpdateBanner(update) {
  const banner = document.getElementById("update-banner");
  if (!banner) return;
  const latest = update?.latest;
  const dismissed = storageGet("ntp-gui-update-dismissed", "");
  if (!update?.available || !latest?.version || dismissed === latest.version) {
    banner.hidden = true;
    banner.replaceChildren();
    return;
  }
  if (banner.dataset.version === `${latest.version}:${update.attention}` && !banner.hidden) return; // offenes ⓘ nicht wegreißen
  banner.dataset.version = `${latest.version}:${update.attention}`;
  banner.dataset.state = update.attention ? "warn" : "info";
  const link = RELEASE_LINK.test(latest.url || "") ? latest.url : null;
  banner.replaceChildren(
    el("span", { class: "update-text" },
      el("strong", { text: `Neue Version ${latest.version} verfügbar` }),
      latest.title ? el("span", { class: "update-title", text: ` – ${latest.title}` }) : null),
    update.attention ? el("span", { class: "update-attention" }, badge("Achtung beim Update", "warn"),
      infoButton("update_attention", "Achtung beim Update")) : null,
    link ? el("a", { href: link, target: "_blank", rel: "noopener noreferrer", text: "Release-Notizen →" }) : null,
    infoButton("update_banner", "Neue Version verfügbar"),
    el("button", { type: "button", class: "icon-button update-close", "aria-label": `Hinweis auf Version ${latest.version} ausblenden`,
      text: "✕", onclick: () => { storageSet("ntp-gui-update-dismissed", latest.version); renderUpdateBanner(update); } }));
  banner.hidden = false;
}

// Zähler an einem Navigationseintrag – oben, in der unteren Leiste, im „Mehr“-Menü und am Reiter
// „Hardware“. „Mehr“ zählt zusammen, was sich darunter verbirgt.
const badges = {};

function setBadge(navId, count) {
  badges[navId] = count || 0;
  paintBadges();
}

function paintBadges() {
  const counts = { ...badges, more: MORE.reduce((sum, id) => sum + (badges[id] || 0), 0), "tab-hardware": badges.uhr || 0 };
  for (const node of document.querySelectorAll("[data-badge]")) {
    const count = counts[node.dataset.badge] || 0;
    node.textContent = count ? String(count) : "";
    node.hidden = !count;
  }
}

// --- Aktualisierung ------------------------------------------------------------
async function refresh() {
  clearTimeout(state.timer);
  const page = currentPage();
  try {
    const [status, history] = await Promise.all([
      apiGet("/api/status"),
      page.history ? apiGet(`/api/history?range=${state.range}&points=600`) : Promise.resolve(null),
    ]);
    state.status = status;
    openSetupOnce(status);
    if (history) state.history = history.samples || [];
    state.failed = 0;
    state.lastOk = (isNum(status?.system?.time) ? status.system.time : Date.now() / 1000) * 1000;
    state.clock = serverClock(status?.system?.time) || state.clock;
    document.body.classList.remove("is-stale");
    showStale(false);
    renderHeader();
    // Offene Erklärung nicht wegreißen: dann nur die Kopfzeile aktualisieren. Seiten mit live = false nur dann
    // neu aufbauen, wenn #main selbst bloß den Platzhalter zeigt – nicht wegen eines leeren Hinweises in einer
    // Karte (sonst klappte z. B. die Diagnose alle paar Sekunden alles zu und verlöre den Fokus).
    if (page.module.live !== false && !isPopoverOpen()) render({ background: true });
    else if (!main.childElementCount || main.querySelector(":scope > .empty-note:only-child")) render({ background: true });
  } catch (error) {
    state.failed += 1;
    document.body.classList.add("is-stale");
    document.getElementById("sync-pill").dataset.state = "crit";
    document.getElementById("sync-label").textContent = t("app.no_connection");
    showStale(true);
  }
  // Verborgener Tab: nicht weiter abfragen – visibilitychange holt beim Zurückkehren sofort neu.
  if (document.hidden) return;
  const every = Math.max(1, state.status?.system?.refresh_seconds || 5) * 1000;
  clearTimeout(state.timer); // zwei überlappende Abfragen (online + Timer) dürfen keine zweite Kette starten
  state.timer = setTimeout(refresh, state.failed ? Math.min(30000, every * (state.failed + 1)) : every);
}

// 1.6 (T3): Erststart (frische Installation, Einrichtung nicht abgeschlossen) – der Willkommens-Assistent
// erscheint von selbst, aber nur beim Öffnen der Startseite und nur einmal je Browser (localStorage): Wer
// „Später“ wählt und zur Übersicht geht, findet dort die Checkliste und landet nicht immer wieder im Assistenten.
// Ohne Schreibrecht (WEB_READONLY) meldet der Server auto_open = false.
let setupChecked = false;
function openSetupOnce(status) {
  if (setupChecked) return false;
  setupChecked = true;
  const hash = window.location.hash;
  if (!status?.ui?.setup?.auto_open || (hash && hash !== "#/" && hash !== "#")) return false;
  if (storageGet("ntp-gui-setup-opened", false)) return false;
  storageSet("ntp-gui-setup-opened", true);
  window.location.replace(route("setup")); // hashchange zeichnet den Assistenten
  return true;
}

// Verbindungsverlust sichtbar machen: Inhalt bleibt stehen, darüber steht, seit wann er veraltet ist.
function showStale(stale) {
  const banner = document.getElementById("stale-banner");
  if (!banner) return;
  if (!stale) { banner.hidden = true; banner.textContent = ""; return; }
  const sys = state.status?.system;
  banner.textContent = staleText(state.lastOk, serverZone(sys) ? sys : 0);
  banner.hidden = false;
}

// Netz wieder da oder Tab wieder sichtbar: sofort abfragen statt bis zu 30 s Backoff abzuwarten.
window.addEventListener("online", () => { state.failed = 0; refresh(); });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(state.timer);
  else refresh();
});

// --- Neustart der Zeitdienste verfolgen ------------------------------------------
function watchReload() {
  const banner = document.getElementById("reload-banner");
  // Serverzeit, nicht die Uhr des Browsers: reload.json trägt den Zeitstempel des Servers.
  const started = serverNow(state.clock) - 2;
  let tries = 0;
  banner.hidden = false;
  banner.dataset.state = "running";
  banner.textContent = "Zeitdienste starten mit den neuen Einstellungen neu …";
  const poll = async () => {
    tries += 1;
    try {
      const status = await apiGet("/api/reload");
      if (reloadSettled(status, started)) {
        banner.dataset.state = status.state === "done" ? "done" : "error";
        banner.textContent = status.message || (status.state === "done" ? "Neue Einstellungen aktiv" : "Fehler beim Neustart");
        if (status.state === "error") toast(status.message, "crit");
        state.cache.clear();
        setTimeout(() => { banner.hidden = true; }, status.state === "done" ? 4000 : 12000);
        refresh();
        return;
      }
    } catch (error) { /* Server startet evtl. gerade */ }
    if (tries < 60) setTimeout(poll, 1000);
    else { banner.dataset.state = "error"; banner.textContent = "Neustart dauert ungewöhnlich lange – Container-Log prüfen."; }
  };
  setTimeout(poll, 800);
}

// --- Navigation ----------------------------------------------------------------------
// Oben (Desktop) alle sieben Einträge, auf dem Handy (≤ 640 px, app.css) stattdessen die untere Leiste
// mit vier Einträgen und „Mehr“. Gruppen („Uhr & Hardware“, „System“) zeigen über dem Inhalt Reiter.
const MORE = NAV.filter((n) => !n.bottom).map((n) => n.id);
const bottombar = document.getElementById("bottombar");
const tabsNav = document.getElementById("tabs");
let moreButton = null;
let moreMenu = null;

function navLink(entry, label, extra = {}) {
  return el("a", { href: entry.href, dataset: { nav: entry.id }, ...extra },
    el("span", { class: "nav-label", text: label }),
    el("span", { class: "nav-badge", hidden: true, dataset: { badge: entry.id } }));
}

function buildNav() {
  nav.replaceChildren(...NAV.map((entry) => navLink(entry, t(entry.titleKey))));
  buildBottomBar();
  paintBadges();
}

function buildBottomBar() {
  if (!bottombar) return;
  closeMore(false);
  moreButton = el("button", { type: "button", class: "bottom-more", "aria-expanded": "false", "aria-controls": "more-menu",
    onclick: () => (moreMenu.hidden ? openMore() : closeMore(true)) },
  el("span", { class: "nav-label", text: t("app.more") }),
  el("span", { class: "nav-badge", hidden: true, dataset: { badge: "more" } }));
  moreMenu = el("div", { id: "more-menu", class: "more-menu", hidden: true },
    el("p", { class: "more-host", id: "more-host" }),
    el("ul", { "aria-label": t("app.more_label") }, NAV.filter((n) => MORE.includes(n.id)).map((entry) =>
      el("li", {}, navLink(entry, t(entry.titleKey), { onclick: chooseMore })))));
  bottombar.replaceChildren(
    ...NAV.filter((n) => n.bottom).map((entry) => navLink(entry, t(entry.shortKey || entry.titleKey))),
    moreButton, moreMenu);
  renderMoreHost();
  markActive(currentPage());
}

// Rechnername im „Mehr“-Menü (auf dem Handy steht in der Kopfzeile nur „NTP-GUI“).
function renderMoreHost() {
  const node = document.getElementById("more-host");
  if (!node) return;
  const sys = state.status?.system || {};
  const parts = [sys.title, sys.hostname].filter(Boolean);
  node.textContent = parts.length ? parts.join(" · ") : "";
  node.hidden = !parts.length;
}

function openMore() {
  if (!moreMenu) return;
  moreMenu.hidden = false;
  moreButton.setAttribute("aria-expanded", "true");
  moreMenu.querySelector("a")?.focus();
}

// focusButton: Fokus zurück auf „Mehr“ (Esc, zweiter Klick) – nicht, wenn ein Eintrag gewählt wurde.
function closeMore(focusButton) {
  if (!moreMenu || moreMenu.hidden) return;
  moreMenu.hidden = true;
  moreButton.setAttribute("aria-expanded", "false");
  if (focusButton) moreButton.focus();
}

// Eintrag im Menü gewählt: Menü zu, Fokus auf den Inhalt (nicht auf <body>) – auch wenn der Eintrag
// zur schon aktiven Seite führt und kein hashchange folgt.
function chooseMore() {
  closeMore(false);
  main.focus({ preventScroll: true });
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && moreMenu && !moreMenu.hidden) {
    event.preventDefault();
    closeMore(true);
  }
});
// Klick daneben schließt; der Fokus kehrt auf „Mehr“ zurück, wenn er im Menü stand.
document.addEventListener("pointerdown", (event) => {
  if (!moreMenu || moreMenu.hidden || moreMenu.contains(event.target) || moreButton.contains(event.target)) return;
  closeMore(moreMenu.contains(document.activeElement));
});
// Fokus verlässt das Menü (Tab hinaus): zuklappen, damit es nicht offen über dem Inhalt stehen bleibt.
// relatedTarget ist null, wenn der Fokus das Dokument verlässt (Tab hinter den letzten Eintrag) – das
// zählt ebenfalls als Verlassen – nicht aber während eines Klicks oder Tippens: Safari fokussiert Knöpfe
// beim Klick nicht (relatedTarget null), sonst ginge das Menü beim zweiten Klick auf „Mehr“ zu und gleich
// wieder auf. Klicks daneben behandelt der pointerdown-Handler.
let pointerDown = false;
document.addEventListener("pointerdown", () => { pointerDown = true; }, true);
for (const type of ["pointerup", "pointercancel"]) document.addEventListener(type, () => { pointerDown = false; }, true);
bottombar?.addEventListener("focusout", (event) => {
  if (!moreMenu || moreMenu.hidden) return;
  if (event.relatedTarget ? !bottombar.contains(event.relatedTarget) : !pointerDown) closeMore(false);
});

function markActive(page) {
  for (const link of document.querySelectorAll("#nav a[data-nav], #bottombar a[data-nav]")) {
    const active = link.dataset.nav === page.nav;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  moreButton?.classList.toggle("is-active", MORE.includes(page.nav));
}

// Reiterleiste einer Gruppe: echte Links (Mittelklick, Lesezeichen), aria-current am aktiven Reiter,
// Pfeiltasten wechseln den Fokus zwischen den Reitern. Nur neu bauen, wenn sich Gruppe oder Sprache
// ändern – sonst verlöre ein fokussierter Reiter den Fokus (bei jeder Aktualisierung und beim Wechsel
// per Enter innerhalb der Gruppe). Innerhalb der Gruppe nur den aktiven Reiter umschalten.
function renderTabs(page) {
  if (!tabsNav) return;
  const tabs = page.tab ? tabsOf(page.nav) : [];
  const key = tabs.length ? `${language()}|${page.nav}` : "";
  if (tabsNav.dataset.key === key) {
    for (const link of tabsNav.querySelectorAll("a.tab")) {
      const active = link.getAttribute("href") === route(page.id);
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    }
    return;
  }
  tabsNav.dataset.key = key;
  if (!tabs.length) { tabsNav.hidden = true; tabsNav.replaceChildren(); return; }
  const group = navOf(page);
  tabsNav.setAttribute("aria-label", t(group.titleKey));
  tabsNav.replaceChildren(el("h2", { class: "tabs-title", text: t(group.titleKey) }),
    el("div", { class: "tabs-row" }, tabs.map((tab) => el("a", {
      href: route(tab.id), class: `tab${tab.id === page.id ? " is-active" : ""}`,
      "aria-current": tab.id === page.id ? "page" : null },
    el("span", { text: t(tab.titleKey) }),
    tab.id === "hardware" ? el("span", { class: "nav-badge", hidden: true, dataset: { badge: "tab-hardware" } }) : null))));
  tabsNav.hidden = false;
  paintBadges();
}

tabsNav?.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || event.altKey || event.ctrlKey || event.metaKey) return;
  const links = [...tabsNav.querySelectorAll("a.tab")];
  const index = links.indexOf(document.activeElement);
  if (index < 0) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? links.length - 1
    : (index + (event.key === "ArrowRight" ? 1 : -1) + links.length) % links.length;
  links[next].focus();
});

// Auf schmalen Bildschirmen scrollt die Navigation seitwärts. Ein weicher Rand
// zeigt, dass es links bzw. rechts weitergeht; der aktive Eintrag wird sichtbar
// gehalten, auch wenn er weit rechts steht (z. B. „Einstellungen“).
function updateNavFade() {
  const max = nav.scrollWidth - nav.clientWidth;
  nav.classList.toggle("fade-start", nav.scrollLeft > 2);
  nav.classList.toggle("fade-end", max > 2 && nav.scrollLeft < max - 2);
}

function revealActiveNav(smooth) {
  const active = nav.querySelector("a.is-active");
  if (!active || nav.scrollWidth <= nav.clientWidth) { updateNavFade(); return; }
  const left = active.offsetLeft; // .nav ist position: relative (app.css)
  const right = left + active.offsetWidth;
  const pad = 32;
  let target = null;
  if (left - pad < nav.scrollLeft) target = Math.max(0, left - pad);
  else if (right + pad > nav.scrollLeft + nav.clientWidth) target = right + pad - nav.clientWidth;
  if (target !== null) nav.scrollTo({ left: target, behavior: smooth ? "smooth" : "auto" });
  updateNavFade();
}

nav.addEventListener("scroll", updateNavFade, { passive: true });
window.addEventListener("resize", updateNavFade);

function initTheme() {
  let theme = storageGet("ntp-gui-theme", null);
  if (!theme) theme = window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    storageSet("ntp-gui-theme", next);
    render();
  });
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (currentPage().module.live !== false) render({ background: true }); }, 200);
});
// Ungespeicherte Änderungen (Einstellungen): Seite mit leaveMessage(uiState) fragt vor dem Verlassen nach –
// beim Wechsel auf eine andere Seite (Hash) und beim Schließen/Neuladen (beforeunload). „Abbrechen“ springt
// im Verlauf auf den gezeigten Eintrag zurück, ohne neu zu zeichnen; „OK“ verwirft die Änderungen (leave).
// Dafür trägt jeder gezeigte Eintrag eine laufende Nummer (navIndex). Die Entscheidung trifft
// routes.js: hashChange (ohne DOM getestet), hier bleibt nur das Zeichnen.
let navIndex = 0;
// Seitenwechsel: Dialoge der alten Seite (Vorschau der Einstellungen, „So sah es um … aus“) gehören nicht
// über die neue – sie hängen an <body> und überlebten sonst das Neuzeichnen.
function closeDialogs() {
  for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
}
function leaveAllowed() {
  const shown = state.shown;
  const next = currentPage();
  if (!shown || shown.id === next.id) return true;
  const message = shown.module?.leaveMessage?.(state.uiState);
  if (!message) return true;
  if (!window.confirm(message)) return false;
  shown.module.leave?.(state.uiState);
  return true;
}
window.addEventListener("beforeunload", (event) => {
  if (!state.shown?.module?.leaveMessage?.(state.uiState)) return;
  event.preventDefault();
  event.returnValue = "";
});
window.addEventListener("hashchange", () => {
  const step = hashChange(history, navIndex, { leaveAllowed, redirect: redirectLegacy });
  navIndex = step.shown;
  if (!step.show) return;
  if (state.shown && state.shown.id !== currentPage().id) closeDialogs();
  closeMore(false);
  state.uiState.scrolled = false;
  resetChartState();
  window.scrollTo(0, 0);
  const page = currentPage();
  if (page.history) refresh(); else render();
  revealActiveNav(true);
});

// Sprache: je Browser (localStorage), Standard = Deutsch – Englisch (Beta) nur auf ausdrücklichen Wunsch.
// Der Knopf schaltet reihum.
function initLanguage() {
  const button = document.getElementById("lang-toggle");
  const code = document.getElementById("lang-code");
  const show = () => { if (code) code.textContent = language().toUpperCase(); };
  show();
  button?.addEventListener("click", () => {
    const index = LANGUAGES.findIndex((l) => l.code === language());
    setLanguage(LANGUAGES[(index + 1) % LANGUAGES.length].code);
  });
  onLanguageChange(() => {
    show();
    buildNav();
    renderHeader();
    render();
    revealActiveNav(false);
  });
}

// --- Tastenkürzel ------------------------------------------------------------------------
let shortcutDialog = null;

function showShortcuts() {
  if (!shortcutDialog || shortcutDialog.dataset.lang !== language()) {
    shortcutDialog?.remove();
    shortcutDialog = el("dialog", { class: "shortcuts-dialog", "aria-labelledby": "shortcuts-title", dataset: { lang: language() } },
      el("div", { class: "shortcuts-head" },
        el("h2", { id: "shortcuts-title", text: t("app.shortcuts.title") }),
        el("button", { type: "button", class: "icon-button", "aria-label": t("app.shortcuts.close"), text: "✕",
          onclick: () => shortcutDialog.close() })),
      el("dl", { class: "shortcuts-list" }, shortcutList().map(([keys, label]) => el("div", { class: "shortcut" },
        el("dt", {}, keys.map((k, i) => [i ? el("span", { class: "muted", text: ` ${t("app.shortcuts.then")} ` }) : null,
          el("kbd", { text: k })])),
        el("dd", { text: t(label) })))),
      el("p", { class: "muted shortcuts-note", text: t("app.shortcuts.note") }));
    // Klick auf den abgedunkelten Rand schließt.
    shortcutDialog.addEventListener("click", (event) => { if (event.target === shortcutDialog) shortcutDialog.close(); });
    document.body.append(shortcutDialog);
  }
  if (!shortcutDialog.open) shortcutDialog.showModal();
}

const onShortcut = createShortcuts({
  go: (navId) => {
    const entry = NAV.find((n) => n.id === navId);
    if (entry) window.location.hash = entry.href.slice(1);
  },
  // „/“: Suchfeld der Seite (Hilfe, Clients, Log der Diagnose …), sonst nichts.
  search: () => {
    const field = main.querySelector('input[type="search"]');
    if (!field) return false;
    field.focus();
    field.select?.();
    return true;
  },
  help: showShortcuts,
});
// Kürzel ruhen auch bei jedem anderen offenen modalen Dialog (Vorschau, „So sah es um … aus“): Die Seite darunter bleibt.
document.addEventListener("keydown", (event) => {
  if (shortcutDialog?.open || document.querySelector("dialog[open]") || isPopoverOpen() || (moreMenu && !moreMenu.hidden)) return;
  onShortcut(event);
});
document.getElementById("shortcuts-button")?.addEventListener("click", showShortcuts);

// „Zum Inhalt springen“: Fokus auf den Inhalt, ohne den Hash (die Route) zu ändern.
document.querySelector(".skip-link")?.addEventListener("click", (event) => {
  event.preventDefault();
  main.focus();
});

await initI18n();
redirectLegacy();
navIndex = stampEntry(history, navIndex);
buildNav();
initTheme();
initLanguage();
render();
revealActiveNav(false);
refresh();
