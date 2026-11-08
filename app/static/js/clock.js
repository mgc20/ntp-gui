// Vollbild-Uhr (/clock): große Uhrzeit, abgeglichen mit der Serveruhr statt der Browseruhr.
//
// Die Browseruhr eines Tablets kann Sekunden danebenliegen. Darum misst die Seite den Versatz
// zum Server mit vier Zeitstempeln (clocksync.js) – fünf Messungen, die mit der kleinsten
// Laufzeit gewinnt – und zeigt Serverzeit an. Alle 60 s wird neu gemessen, alle 5 s der
// Zustand abgefragt. Antwortet der Server 10 s lang nicht, wird die Ampel grau.
//
// Bewusst ohne app.js/ui.js: Die Seite muss auch ohne Anmeldung (clock_public) laufen und
// lädt deshalb nur Dateien, die keine Inhalte aus Konfiguration oder Status enthalten.
import { fromResponse, best, isoWeek, hms, fmtAccuracy, sourceText } from "./clocksync.js";

const BURST = 5;
const BURST_GAP_MS = 250;
const RESYNC_MS = 60_000;
const POLL_MS = 5_000;
const STALE_MS = 10_000;
const TIMEOUT_MS = 4_000;
const IDLE_MS = 4_000;

const $ = (id) => document.getElementById(id);
const root = document.documentElement;
const state = {
  sync: null,          // beste Messung der letzten Runde {offset, rtt, accuracy}
  status: null,        // letzte Antwort von /api/v1/time
  lastOk: 0,           // performance.now() der letzten erfolgreichen Antwort
  error: "",
  wake: null,
  wakeText: "",
};

function store(key, value) {
  try {
    if (value === undefined) return window.localStorage.getItem(key);
    window.localStorage.setItem(key, value);
  } catch (error) { /* privates Fenster – dann eben ohne Merken */ }
  return null;
}

// --- Messung -------------------------------------------------------------------
async function sample() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  // Datumsbasis aus Date.now(), Dauer aus performance.now() (feiner als 1 ms).
  const wall0 = Date.now();
  const perf0 = performance.now();
  try {
    const response = await fetch("/api/v1/time", {
      cache: "no-store", credentials: "same-origin", signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    const perf3 = performance.now();
    if (!response.ok) throw new Error(response.status === 401 ? "Anmeldung nötig" : `HTTP ${response.status}`);
    const payload = await response.json();
    const measured = fromResponse(wall0, payload, wall0 + (perf3 - perf0));
    state.status = payload;
    state.lastOk = performance.now();
    state.error = "";
    return measured;
  } catch (error) {
    state.error = error.name === "AbortError" ? "Zeitüberschreitung" : error.message;
    return null;
  } finally {
    clearTimeout(timer);
  }
}

const wait = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

async function burst() {
  const results = [];
  for (let i = 0; i < BURST; i += 1) {
    const m = await sample();
    if (m) results.push(m);
    if (i < BURST - 1) await wait(BURST_GAP_MS);
  }
  const winner = best(results);
  if (winner) state.sync = winner;
  renderBand();
}

async function poll() {
  await sample();
  renderBand();
}

function serverNow() {
  return new Date(Date.now() + (state.sync ? state.sync.offset : 0));
}

// --- Anzeige ---------------------------------------------------------------------
const DATE_FMT = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

function tick() {
  const now = serverNow();
  $("local-time").textContent = hms(now);
  $("local-time").setAttribute("datetime", now.toISOString());
  $("utc-time").textContent = hms(now, true);
  $("local-date").textContent = DATE_FMT.format(now);
  const { week } = isoWeek(now);
  $("iso-week").textContent = `KW ${week}`;
  // Ampel wird grau, sobald 10 s keine Antwort kam – auch ohne neue Antwort prüfen.
  const stale = !state.lastOk || performance.now() - state.lastOk > STALE_MS;
  document.body.classList.toggle("is-stale", stale && Boolean(state.status));
  if (state.status && (stale || $("band").dataset.state === "stale")) renderBand();
  // Nächster Schritt genau zur vollen Sekunde der Serverzeit.
  const ms = (Date.now() + (state.sync ? state.sync.offset : 0)) % 1000;
  setTimeout(tick, 1000 - ms + 5);
}

const STATE_TEXT = { good: "synchron", warn: "eingeschränkt", crit: "nicht synchron" };

function renderBand() {
  const band = $("band");
  const s = state.status;
  const stale = !state.lastOk || performance.now() - state.lastOk > STALE_MS;
  let tone; let main; const detail = [];
  if (!s) {
    tone = "unknown";
    main = state.error ? `keine Verbindung (${state.error})` : "verbinde …";
  } else if (stale) {
    tone = "stale";
    const ago = Math.round((performance.now() - state.lastOk) / 1000);
    main = `keine Verbindung seit ${ago} s`;
    detail.push("die Uhr läuft mit dem letzten Abgleich weiter");
  } else {
    tone = s.level in STATE_TEXT ? s.level : "warn";
    if (!s.running) main = "chronyd antwortet nicht";
    else if (!s.synchronised) main = s.source_kind ? `nicht synchron · ${s.source_kind}` : "nicht synchron";
    else main = `${STATE_TEXT[tone] || "synchron"} · ${sourceText(s.source_kind, s.source)}`;
    if (typeof s.accuracy === "number") detail.push(`Server ${fmtAccuracy(s.accuracy * 1000)}`);
    if (s.leap && s.leap !== "Normal" && s.leap !== "Not synchronised") detail.push(`Schaltsekunde angekündigt (${s.leap})`);
  }
  if (state.sync) detail.push(`Anzeige ${fmtAccuracy(state.sync.accuracy)} (RTT ${fmtAccuracy(state.sync.rtt).replace("± ", "")})`);
  band.dataset.state = tone;
  $("band-main").textContent = main;
  $("band-detail").textContent = detail.join(" · ");
  $("band-wake").textContent = state.wakeText;
  band.title = "Server: Genauigkeit der Serveruhr laut chrony. Anzeige: Abgleich dieser Seite mit dem Server "
    + "(± halbe Laufzeit der besten von fünf Messungen).";
}

// --- Bildschirm wach halten ---------------------------------------------------------
async function keepAwake() {
  if (!("wakeLock" in navigator)) {
    state.wakeText = window.isSecureContext ? "" : "Bildschirm-Sperre: nur über HTTPS abschaltbar";
    renderBand();
    return;
  }
  try {
    state.wake = await navigator.wakeLock.request("screen");
    state.wakeText = "Bildschirm bleibt an";
    state.wake.addEventListener("release", () => { state.wakeText = ""; renderBand(); });
  } catch (error) {
    state.wakeText = "";
  }
  renderBand();
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    keepAwake();
    burst();   // nach dem Aufwachen (Tablet im Standby) sofort neu abgleichen
  }
});

// --- Darstellung: hell/dunkel, Rotlicht, Vollbild ---------------------------------------
function applyModes() {
  const theme = store("ntp-gui-clock-theme") || "dark";
  const red = store("ntp-gui-clock-red") === "1";
  root.dataset.theme = theme;
  if (red) root.dataset.mode = "red"; else delete root.dataset.mode;
  $("mode-theme").textContent = theme === "dark" ? "Hell" : "Dunkel";
  $("mode-theme").setAttribute("aria-pressed", theme === "light" ? "true" : "false");
  $("mode-red").setAttribute("aria-pressed", red ? "true" : "false");
  $("mode-theme").disabled = red;
}

$("mode-theme").addEventListener("click", () => {
  store("ntp-gui-clock-theme", root.dataset.theme === "dark" ? "light" : "dark");
  applyModes();
});
$("mode-red").addEventListener("click", () => {
  store("ntp-gui-clock-red", root.dataset.mode === "red" ? "0" : "1");
  applyModes();
});
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.().catch(() => {});
}
$("mode-full").addEventListener("click", toggleFullscreen);
if (!document.documentElement.requestFullscreen) $("mode-full").hidden = true;
document.addEventListener("keydown", (event) => {
  if (event.key === "f" || event.key === "F") toggleFullscreen();
});

// Leiste ausblenden, wenn sich nichts bewegt (Wandmonitor); Tippen/Bewegen holt sie zurück.
let idleTimer = null;
function wake() {
  document.body.classList.remove("is-idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => document.body.classList.add("is-idle"), IDLE_MS);
}
for (const type of ["pointermove", "pointerdown", "keydown", "focusin"]) document.addEventListener(type, wake, { passive: true });

// --- Start ------------------------------------------------------------------------------
applyModes();
wake();
tick();
keepAwake();
burst();
setInterval(burst, RESYNC_MS);
setInterval(poll, POLL_MS);
