// Einstieg: Navigation, Aktualisierung, Datencache, Neustart-Anzeige.
import { el, apiGet, storageGet, storageSet, fmtTime } from "./util.js";
import { toast, isPopoverOpen } from "./ui.js";
import * as overview from "./pages/overview.js";
import * as sources from "./pages/sources.js";
import * as gps from "./pages/gps.js";
import * as ptp from "./pages/ptp.js";
import * as hardware from "./pages/hardware.js";
import * as clients from "./pages/clients.js";
import * as settings from "./pages/settings.js";
import * as help from "./pages/help.js";

const PAGES = [
  { id: "", title: "Übersicht", module: overview, history: true },
  { id: "quellen", title: "Zeitquellen", module: sources, history: true },
  { id: "gps", title: "GPS", module: gps, history: true },
  { id: "ptp", title: "PTP", module: ptp, history: true },
  { id: "hardware", title: "Hardware", module: hardware, history: false },
  { id: "clients", title: "Clients", module: clients, history: true },
  { id: "einstellungen", title: "Einstellungen", module: settings },
  { id: "hilfe", title: "Hilfe", module: help },
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

function currentPage() {
  const id = (window.location.hash.replace(/^#\/?/, "").split("?")[0] || "").toLowerCase();
  return PAGES.find((p) => p.id === id) || PAGES[0];
}

// --- Datencache für seitenbezogene Abfragen ---------------------------------
function data(key, url, ttlSeconds) {
  const entry = state.cache.get(key);
  const now = Date.now();
  const fresh = entry && entry.url === url && entry.data !== undefined
    && (ttlSeconds === 0 || now - entry.time < ttlSeconds * 1000);
  if (!fresh && !(entry && entry.pending && entry.url === url)) {
    const record = { url, pending: true, time: entry?.time || 0, data: entry?.url === url ? entry.data : undefined };
    state.cache.set(key, record);
    apiGet(url).then((result) => {
      Object.assign(record, { data: result, time: Date.now(), pending: false });
      render();
    }).catch(() => { record.pending = false; record.time = Date.now(); });
  }
  const current = state.cache.get(key);
  return current && current.url === url ? current.data : undefined;
}

function invalidate(key) { state.cache.delete(key); }

// --- Rendern -----------------------------------------------------------------
let pendingAfter = [];

function render() {
  const page = currentPage();
  document.title = `${page.title} · ${state.status?.system?.title || "ntp-gui"}`;
  for (const link of nav.querySelectorAll("a")) {
    const active = link.dataset.page === page.id;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  if (!state.status && page.module !== help && page.module !== settings) {
    main.replaceChildren(el("p", { class: "empty-note", text: "Verbinde mit dem Server …" }));
    return;
  }
  const scroll = window.scrollY;
  pendingAfter = [];
  const ctx = {
    status: state.status || {},
    history: state.history,
    range: state.range,
    uiState: state.uiState,
    readonly: Boolean(state.status?.ui?.readonly),
    setRange: (seconds) => { state.range = seconds; storageSet("ntp-gui-range", seconds); refresh(); },
    rerender: () => render(),
    afterRender: (fn) => pendingAfter.push(fn),
    data, invalidate,
    watchReload,
    refresh: () => refresh(),
  };
  let nodes;
  try {
    nodes = page.module.render(ctx);
  } catch (error) {
    console.error(error);
    nodes = [el("p", { class: "empty-note", text: `Darstellungsfehler: ${error.message}` })];
  }
  main.replaceChildren(...nodes.filter(Boolean));
  for (const fn of pendingAfter) { try { fn(); } catch (error) { console.error(error); } }
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
  document.getElementById("clock").textContent = `${new Date(sys.time * 1000).toLocaleString("de-DE")} ${sys.timezone || ""}`;
  const t = status.tracking || {};
  let tone = "warn"; let text = "Synchronisiert …";
  if (!status.chrony_running) { tone = "crit"; text = "chronyd offline"; }
  else if (t.synchronised) { tone = "good"; text = `Synchron · Stratum ${t.stratum}`; }
  else if (t.local_reference) { text = `Inselbetrieb · Stratum ${t.stratum ?? "–"}`; }
  pill.dataset.state = tone;
  label.textContent = text;
  const serious = (status.insights || []).filter((i) => i.level === "warn" || i.level === "crit");
  // Übersicht zählt alle Probleme, „Hardware“ nur die aus dem Hardware-Check.
  setBadge("", serious.length);
  setBadge("hardware", serious.filter((i) => i.action === "hardware").length);
  document.getElementById("footer-note").textContent =
    `ntp-gui ${sys.version || ""} · aktualisiert ${fmtTime(sys.time)} · alle ${sys.refresh_seconds} s`;
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
    document.getElementById("sync-label").textContent = "keine Verbindung";
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
    el("span", { text: page.title }),
    page.id === "" || page.id === "hardware" ? el("span", { class: "nav-badge", hidden: true }) : null)));
}

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
  window.scrollTo(0, 0);
  const page = currentPage();
  if (page.history) refresh(); else render();
});

buildNav();
initTheme();
render();
refresh();
