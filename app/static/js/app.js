// Einstieg: Navigation, Aktualisierung, Datencache, Neustart-Anzeige.
import { el, apiGet, storageGet, storageSet, fmtTime } from "./util.js";
import { toast, isPopoverOpen, info, badge } from "./ui.js";
import { resetChartState } from "./charts.js";
import * as overview from "./pages/overview.js";
import * as sources from "./pages/sources.js";
import * as gps from "./pages/gps.js";
import * as ptp from "./pages/ptp.js";
import * as clockquality from "./pages/clockquality.js";
import * as hardware from "./pages/hardware.js";
import * as clients from "./pages/clients.js";
import * as diagnose from "./pages/diagnose.js";
import * as notify from "./pages/notify.js";
import * as settings from "./pages/settings.js";
import * as help from "./pages/help.js";
import { t, initI18n, setLanguage, language, LANGUAGES, onLanguageChange } from "./i18n.js";

// Titel als Katalogschlüssel (i18n.js) – die Route (id) bleibt deutsch, damit Lesezeichen gelten.
const PAGES = [
  { id: "", titleKey: "nav.overview", module: overview, history: true },
  { id: "quellen", titleKey: "nav.sources", module: sources, history: true },
  { id: "gps", titleKey: "nav.gps", module: gps, history: true },
  { id: "ptp", titleKey: "nav.ptp", module: ptp, history: true },
  { id: "uhrqualitaet", titleKey: "nav.clockquality", module: clockquality, history: false },
  { id: "hardware", titleKey: "nav.hardware", module: hardware, history: false },
  { id: "clients", titleKey: "nav.clients", module: clients, history: true },
  { id: "diagnose", titleKey: "nav.diagnose", module: diagnose, history: false },
  { id: "benachrichtigungen", titleKey: "nav.notify", module: notify, history: false },
  { id: "einstellungen", titleKey: "nav.settings", module: settings },
  { id: "hilfe", titleKey: "nav.help", module: help },
];

const state = {
  status: null,
  history: [],
  range: storageGet("ntp-gui-range", 3600),
  uiState: {},
  cache: new Map(),
  timer: null,
  failed: 0,
  reload: null,
};

const main = document.getElementById("main");
const nav = document.getElementById("nav");

// #/<seite>/<unterpfad> – der Unterpfad (z. B. die Adresse auf #/clients/192.168.1.5) geht als
// ctx.subpath an die Seite.
function routeParts() {
  const raw = window.location.hash.replace(/^#\/?/, "").split("?")[0] || "";
  const slash = raw.indexOf("/");
  const id = (slash < 0 ? raw : raw.slice(0, slash)).toLowerCase();
  let sub = slash < 0 ? "" : raw.slice(slash + 1);
  try { sub = decodeURIComponent(sub); } catch (error) { sub = ""; }
  return { id, sub };
}

function currentPage() {
  const { id } = routeParts();
  return PAGES.find((p) => p.id === id) || PAGES[0];
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
      render();
    }).catch((error) => {
      const known = record.error;
      Object.assign(record, { pending: false, time: Date.now(), error: { status: error.status || 0, message: error.message } });
      // Nur neu zeichnen, wenn der Fehler neu ist – sonst hinge die Seite in einer Schleife.
      if (!known || known.status !== record.error.status) render();
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

// Tastaturfokus über das Neuzeichnen retten: Die Seite wird alle paar Sekunden
// komplett neu gebaut. Vorher merken, welches Element (Schlüssel + Position unter
// gleichartigen) den Fokus hatte, danach das passende neue Element fokussieren.
const FOCUSABLE = "a[href], button, input, select, textarea, summary, [tabindex]";

function focusKeyOf(node) {
  if (!node || node === main || !main.contains(node)) return null;
  if (node.dataset && node.dataset.focusKey) return node.dataset.focusKey;
  const parts = [node.tagName, node.getAttribute("href") || "", node.getAttribute("aria-label") || "", node.id || ""];
  if (!parts[1] && !parts[2] && !parts[3]) parts.push((node.textContent || "").trim().slice(0, 60));
  return parts.join("|");
}

function captureFocus() {
  const node = document.activeElement;
  const key = focusKeyOf(node);
  if (!key) return null;
  const same = [...main.querySelectorAll(FOCUSABLE)].filter((n) => focusKeyOf(n) === key);
  return { key, index: Math.max(0, same.indexOf(node)) };
}

function restoreFocus(saved) {
  if (!saved) return;
  const active = document.activeElement;
  if (active && active !== document.body && active !== main && active.isConnected) return;
  const same = [...main.querySelectorAll(FOCUSABLE)].filter((n) => focusKeyOf(n) === saved.key);
  const target = same[Math.min(saved.index, same.length - 1)];
  if (target) target.focus({ preventScroll: true });
}

function render() {
  const page = currentPage();
  document.title = `${t(page.titleKey)} · ${state.status?.system?.title || "ntp-gui"}`;
  for (const link of nav.querySelectorAll("a")) {
    const active = link.dataset.page === page.id;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  if (!state.status && page.module !== help && page.module !== settings) {
    main.replaceChildren(el("p", { class: "empty-note", text: t("app.connecting_server") }));
    return;
  }
  const scroll = window.scrollY;
  pendingAfter = [];
  const ctx = {
    status: state.status || {},
    history: state.history,
    range: state.range,
    uiState: state.uiState,
    subpath: page.id ? routeParts().sub : "",
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
  const focus = captureFocus();
  main.replaceChildren(...nodes.filter(Boolean));
  for (const fn of pendingAfter) { try { fn(); } catch (error) { console.error(error); } }
  restoreFocus(focus);
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
  document.getElementById("clock").textContent = `${new Date(sys.time * 1000).toLocaleString(language() === "en" ? "en-GB" : "de-DE")} ${sys.timezone || ""}`;
  // Dieselbe Bewertung wie das Statusband der Übersicht – Kopfzeile und Übersicht
  // dürfen sich nie widersprechen. Schmal: nur Punkt + Kurztext.
  const v = overview.verdict(status, status.insights || []);
  pill.dataset.state = v.tone;
  label.replaceChildren(el("span", { class: "pill-long", text: v.pill }), el("span", { class: "pill-short", text: v.pillShort }));
  pill.title = v.title;
  const serious = (status.insights || []).filter((i) => i.level === "warn" || i.level === "crit");
  // Übersicht zählt alle Probleme, „Hardware“ nur die aus dem Hardware-Check.
  setBadge("", serious.length);
  setBadge("hardware", serious.filter((i) => i.action === "hardware").length);
  renderUpdateBanner(status.update);
  document.getElementById("footer-note").textContent =
    t("app.footer", { version: sys.version || "", time: fmtTime(sys.time), seconds: sys.refresh_seconds });
}

// --- Update-Hinweis (opt-in) ---------------------------------------------------
// Nur ein Link nach github.com/ConGp20/ntp-gui – der Server baut ihn aus der geprüften Versionsnummer.
const RELEASE_LINK = /^https:\/\/github\.com\/ConGp20\/ntp-gui\/releases(\/tag\/v[0-9A-Za-z.-]+)?$/;

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
      info("update_attention", "Achtung beim Update")) : null,
    link ? el("a", { href: link, target: "_blank", rel: "noopener noreferrer", text: "Release-Notizen →" }) : null,
    info("update_banner", "Neue Version verfügbar"),
    el("button", { type: "button", class: "icon-button update-close", "aria-label": `Hinweis auf Version ${latest.version} ausblenden`,
      text: "✕", onclick: () => { storageSet("ntp-gui-update-dismissed", latest.version); renderUpdateBanner(update); } }));
  banner.hidden = false;
}

function setBadge(pageId, count) {
  const badgeNode = nav.querySelector(`a[data-page="${pageId}"] .nav-badge`);
  if (!badgeNode) return;
  badgeNode.textContent = count ? String(count) : "";
  badgeNode.hidden = !count;
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
    if (history) state.history = history.samples || [];
    state.failed = 0;
    document.body.classList.remove("is-stale");
    renderHeader();
    // Offene Erklärung nicht wegreißen: dann nur die Kopfzeile aktualisieren.
    if (page.module.live !== false && !isPopoverOpen()) render();
    else if (!main.childElementCount || main.querySelector(".empty-note:only-child")) render();
  } catch (error) {
    state.failed += 1;
    document.body.classList.add("is-stale");
    document.getElementById("sync-pill").dataset.state = "crit";
    document.getElementById("sync-label").textContent = t("app.no_connection");
  }
  const every = Math.max(1, state.status?.system?.refresh_seconds || 5) * 1000;
  state.timer = setTimeout(refresh, state.failed ? Math.min(30000, every * (state.failed + 1)) : every);
}

// --- Neustart der Zeitdienste verfolgen ------------------------------------------
function watchReload() {
  const banner = document.getElementById("reload-banner");
  const started = Date.now() / 1000 - 2;
  let tries = 0;
  banner.hidden = false;
  banner.dataset.state = "running";
  banner.textContent = "Zeitdienste starten mit den neuen Einstellungen neu …";
  const poll = async () => {
    tries += 1;
    try {
      const status = await apiGet("/api/reload");
      if (status.time >= started && (status.state === "done" || status.state === "error")) {
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

// --- Start -------------------------------------------------------------------------
function buildNav() {
  nav.replaceChildren(...PAGES.map((page) => el("a", { href: `#/${page.id}`, dataset: { page: page.id } },
    el("span", { text: t(page.titleKey) }),
    page.id === "" || page.id === "hardware" ? el("span", { class: "nav-badge", hidden: true }) : null)));
}

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
  resizeTimer = setTimeout(() => { if (currentPage().module.live !== false) render(); }, 200);
});
window.addEventListener("hashchange", () => {
  state.uiState.scrolled = false;
  resetChartState();
  window.scrollTo(0, 0);
  const page = currentPage();
  if (page.history) refresh(); else render();
  revealActiveNav(true);
});

// Sprache: je Browser (localStorage), Standard = Browsersprache. Der Knopf schaltet reihum.
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
    const counts = [...nav.querySelectorAll(".nav-badge")].map((n) => [n.closest("a")?.dataset.page, n.textContent]);
    buildNav();
    for (const [page, text] of counts) setBadge(page, Number(text) || 0);
    renderHeader();
    render();
    revealActiveNav(false);
  });
}

await initI18n();
buildNav();
initTheme();
initLanguage();
render();
revealActiveNav(false);
refresh();
