// Vollbild-Uhr (/clock): große Uhrzeit, abgeglichen mit der Serveruhr statt der Browseruhr.
//
// Die Browseruhr eines Tablets kann Sekunden danebenliegen. Darum misst die Seite den Versatz
// zum Server mit vier Zeitstempeln (clocksync.js) – fünf Messungen, die mit der kleinsten
// Laufzeit gewinnt – und zeigt Serverzeit an. Alle 60 s wird neu gemessen, alle 5 s der
// Zustand abgefragt. Antwortet der Server 10 s lang nicht, wird die Ampel grau.
//
// 1.6 (T6) „Uhr-Werkstatt“: vier Designs (Bahnhofsuhr, Nixie, Klappzahlen, Wortuhr) neben der
// digitalen Anzeige, Kiosk (?kiosk=1), E-Ink (?eink=1), zweite Zeitzone (?tz=), Ton auf der Sekunde
// und „Wie falsch geht dein Gerät?“. Die reinen Rechnungen stehen in clockkit.js. Bewegung macht CSS
// (Sekundenzeiger, Klappen, Glühen); JS stellt nur einmal je Sekunde (E-Ink: je Minute) die Anzeige.
// Der gemessene Versatz der Browseruhr bleibt im Browser: nicht gespeichert, nicht gesendet.
//
// Bewusst ohne app.js/ui.js: Die Seite muss auch ohne Anmeldung (clock_public) laufen und
// lädt deshalb nur Dateien, die keine Inhalte aus Konfiguration oder Status enthalten
// (clocksync.js, clockkit.js, util.js, i18n.js und die Sprachkataloge).
import { fromResponse, best, isoWeek, hms, fmtAccuracy, sourceText } from "./clocksync.js";
import { initI18n, t, language } from "./i18n.js";
import { svgEl } from "./util.js";
import * as kit from "./clockkit.js";

const BURST = 5;
const BURST_GAP_MS = 250;
const RESYNC_MS = 60_000;
const POLL_MS = 5_000;
const STALE_MS = 10_000;
const TIMEOUT_MS = 4_000;
const IDLE_MS = 4_000;
const DESIGN_KEY = "ntp-gui-clock-design";

const $ = (id) => document.getElementById(id);
const root = document.documentElement;
const params = kit.parseParams(window.location.search, kit.supportedZones());
const reducedMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
const state = {
  sync: null,          // beste Messung der letzten Runde {offset, rtt, accuracy}
  status: null,        // letzte Antwort von /api/v1/time
  lastOk: 0,           // performance.now() der letzten erfolgreichen Antwort
  error: "",
  wake: null,
  wakeText: "",
  design: kit.DEFAULT_DESIGN,
  face: null,          // Teile des aktuellen Designs
  tone: null,          // { ctx, mode, last, exact }
  tickTimer: null,
};
if (params.ignored.length) console.info(`/clock: unbekannte Werte ignoriert (${params.ignored.join(", ")})`);

// Nur schreiben, was sich wirklich ändert: Das Band und #tone-status sind aria-live-Regionen (sonst sagt der
// Screenreader denselben Satz immer wieder an), und E-Ink aktualisiert sonst bei jeder Zuweisung.
function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}
function setAttr(node, name, value) {
  if (node.getAttribute(name) !== value) node.setAttribute(name, value);
}

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
    if (!response.ok) throw new Error(response.status === 401 ? t("clock.err_login") : `HTTP ${response.status}`);
    const payload = await response.json();
    const measured = fromResponse(wall0, payload, wall0 + (perf3 - perf0));
    state.status = payload;
    state.lastOk = performance.now();
    state.error = "";
    return measured;
  } catch (error) {
    state.error = error.name === "AbortError" ? t("clock.err_timeout") : error.message;
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
  if (winner) {
    state.sync = winner;
    // Sofort mit dem neuen Versatz zeichnen und den Takt neu ausrichten – E-Ink wartete sonst bis zur
    // nächsten (falsch berechneten) Minute. Der Sekundenzeiger setzt neu an.
    clearTimeout(state.tickTimer);
    tick();
    restartSweep();
  }
  renderBandLive();
  renderDevice();
}

async function poll() {
  await sample();
  renderBandLive();
}

/**
 * Band nach einer Messung oder Abfrage zeichnen. E-Ink: nur zum Minutenwechsel (tick) – außer das Band zeigt
 * noch „verbinde …“, dann einmal sofort, damit es nicht bis zur nächsten Minute leer bleibt.
 */
function renderBandLive() {
  if (params.eink && $("band").dataset.state !== "unknown") return;
  renderBand();
}

const offsetMs = () => (state.sync ? state.sync.offset : 0);
const serverMs = () => Date.now() + offsetMs();

// --- Anzeige ---------------------------------------------------------------------
const pad = (n) => String(n).padStart(2, "0");
const DATE_FMT = new Map();
function dateText(now) {
  const tag = language() === "en" ? "en-GB" : "de-DE";
  if (!DATE_FMT.has(tag)) DATE_FMT.set(tag, new Intl.DateTimeFormat(tag, { weekday: "long", day: "numeric", month: "long", year: "numeric" }));
  return DATE_FMT.get(tag).format(now);
}
let tzFormat = null;
function zoneTime(now) {
  if (!tzFormat) tzFormat = new Intl.DateTimeFormat("en-GB", { timeZone: params.tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return tzFormat.format(now);
}

function tick() {
  const nowMs = serverMs();
  const now = new Date(nowMs);
  render(now);
  // Ampel wird grau, sobald 10 s keine Antwort kam – auch ohne neue Antwort prüfen.
  const stale = !state.lastOk || performance.now() - state.lastOk > STALE_MS;
  document.body.classList.toggle("is-stale", stale && Boolean(state.status));
  if (state.status && (stale || $("band").dataset.state === "stale" || params.eink)) renderBand();
  if (state.tone) toneTick(nowMs);
  // Nächster Schritt genau zur vollen Sekunde der Serverzeit (E-Ink: zur vollen Minute).
  const step = params.eink ? 60_000 : 1000;
  const into = ((serverMs() % step) + step) % step;
  state.tickTimer = setTimeout(tick, step - into + 5);
}

function render(now) {
  const h = now.getHours();
  const m = now.getMinutes();
  const s = now.getSeconds();
  const short = `${pad(h)}:${pad(m)}`;
  const time = params.eink ? short : hms(now);
  setText($("local-time"), time);
  const stamp = params.eink ? new Date(Math.floor(now.getTime() / 60_000) * 60_000) : now;
  setAttr($("local-time"), "datetime", stamp.toISOString());
  setText($("utc-time"), params.eink ? hms(now, true).slice(0, 5) : hms(now, true));
  setText($("local-date"), dateText(now));
  const { week } = isoWeek(now);
  setText($("iso-week"), t("clock.week", { week }));
  if (params.tz) setText($("tz2-time"), zoneTime(now));
  renderFace(now, h, m, s);
  renderEgg(now.getTime());
}

// --- Designs -----------------------------------------------------------------------
function buildFace() {
  const face = $("face");
  face.replaceChildren();
  face.className = `clock-face face-${state.design}`;
  const digital = state.design === "digital";
  face.hidden = digital;
  $("local-time").hidden = !digital;
  state.face = { design: state.design, key: "" };
  if (digital) return;
  face.setAttribute("role", "img");
  if (state.design === "bahnhof") buildBahnhof(face);
  else if (state.design === "nixie") buildNixie(face);
  else if (state.design === "flip") buildFlip(face);
  else if (state.design === "wort") buildWort(face);
}

function digitCount() { return params.eink ? 4 : 6; }

function buildBahnhof(face) {
  // Eigenes, schlichtes Zifferblatt: Striche statt Zahlen, Balkenzeiger, Sekundenzeiger mit offenem Ring.
  const svg = svgEl("svg", { viewBox: "0 0 200 200", class: "bh", "aria-hidden": "true", focusable: "false" });
  svg.append(svgEl("circle", { cx: 100, cy: 100, r: 97, class: "bh-face" }));
  for (let i = 0; i < 60; i += 1) {
    const hour = i % 5 === 0;
    svg.append(svgEl("line", { x1: 100, y1: 9, x2: 100, y2: hour ? 27 : 15, class: hour ? "bh-tick bh-tick-hour" : "bh-tick",
      transform: `rotate(${i * 6} 100 100)` }));
  }
  const hour = svgEl("rect", { x: 95, y: 46, width: 10, height: 66, rx: 1.5, class: "bh-hour" });
  const minute = svgEl("rect", { x: 96.5, y: 15, width: 7, height: 97, rx: 1.5, class: "bh-minute" });
  const second = svgEl("g", { class: "bh-second" });
  second.append(svgEl("line", { x1: 100, y1: 130, x2: 100, y2: 40, class: "bh-second-line" }),
    svgEl("circle", { cx: 100, cy: 33, r: 7, class: "bh-second-ring" }));
  svg.append(hour, minute, second, svgEl("circle", { cx: 100, cy: 100, r: 3.5, class: "bh-cap" }));
  if (params.eink) second.hidden = true;
  face.append(svg);
  Object.assign(state.face, { svg, hour, minute, second, sweep: false });
}

function setAngle(node, angle) {
  setAttr(node, "transform", `rotate(${Math.round(angle * 100) / 100} 100 100)`);
}

function sweepWanted() {
  return state.design === "bahnhof" && !params.eink && !reducedMotion.matches;
}

/** Sekundenzeiger als CSS-Animation (60 s, Halt auf der 12) auf die Phase der Serverminute setzen. */
function restartSweep() {
  const face = state.face;
  if (!face || face.design !== "bahnhof" || !face.second) return;
  if (!face.sweep && !sweepWanted()) return;   // läuft nicht und soll nicht laufen (E-Ink, ruhig)
  const node = face.second;
  node.classList.remove("is-sweep");
  if (!sweepWanted()) { face.sweep = false; return; }
  node.removeAttribute("transform");
  const phase = (((serverMs() % 60_000) + 60_000) % 60_000) / 1000;
  void node.getBoundingClientRect();   // Animation wirklich neu starten
  node.style.animationDelay = `-${Math.round(phase * 1000) / 1000}s`;
  node.classList.add("is-sweep");
  face.sweep = true;
}

function renderBahnhof(h, m, s, ms) {
  const face = state.face;
  const angles = kit.handAngles(h, m, s, ms, { step: true });
  setAngle(face.hour, angles.hour);
  setAngle(face.minute, angles.minute);
  setAttr(face.svg, "data-hour", String(angles.hour));
  setAttr(face.svg, "data-minute", String(angles.minute));
  if (sweepWanted()) {
    // Zur vollen Minute (Zeiger steht ohnehin auf der 12) neu ansetzen – so läuft er nie weg.
    if (!face.sweep || s === 0) restartSweep();
  } else {
    if (face.sweep) restartSweep();
    if (!params.eink) setAngle(face.second, angles.second);
  }
}

function buildNixie(face) {
  const tubes = [];
  for (let i = 0; i < digitCount(); i += 1) {
    if (i && i % 2 === 0) face.append(Object.assign(document.createElement("span"), { className: "nixie-sep", textContent: "·" }));
    const tube = document.createElement("span");
    tube.className = "nixie-tube";
    tube.setAttribute("aria-hidden", "true");
    const numerals = [];
    for (let n = 0; n < 10; n += 1) {
      const numeral = document.createElement("span");
      numeral.className = "nixie-n";
      numeral.textContent = String(n);
      tube.append(numeral);
      numerals.push(numeral);
    }
    face.append(tube);
    tubes.push({ tube, numerals });
  }
  state.face.tubes = tubes;
}

function renderNixie(digits) {
  state.face.tubes.forEach(({ tube, numerals }, index) => {
    const digit = digits[index];
    if (tube.dataset.digit === digit) return;
    tube.dataset.digit = digit;
    numerals.forEach((node, n) => node.classList.toggle("on", String(n) === digit));
  });
}

function buildFlip(face) {
  const cards = [];
  for (let i = 0; i < digitCount(); i += 1) {
    if (i && i % 2 === 0) face.append(Object.assign(document.createElement("span"), { className: "flip-sep", textContent: ":" }));
    const card = document.createElement("span");
    card.className = "flip-card";
    card.setAttribute("aria-hidden", "true");
    const digit = document.createElement("span");
    digit.className = "flip-digit";
    card.append(digit);
    face.append(card);
    cards.push({ card, digit });
  }
  Object.assign(state.face, { cards, digits: "" });
}

function renderFlip(digits) {
  const face = state.face;
  kit.flipDigits(face.digits, digits).forEach(({ digit, changed }, index) => {
    const { card, digit: node } = face.cards[index];
    if (node.textContent === digit) return;
    node.textContent = digit;
    card.dataset.digit = digit;
    if (changed) {
      // Zwei gleiche Animationen im Wechsel – so startet CSS sie bei jedem Wechsel neu.
      const next = card.classList.contains("flip-a") ? "flip-b" : "flip-a";
      card.classList.remove("flip-a", "flip-b");
      card.classList.add(next);
    }
  });
  face.digits = digits;
}

function buildWort(face) {
  const text = document.createElement("p");
  text.className = "wort-text";
  const dots = document.createElement("span");
  dots.className = "wort-dots";
  dots.setAttribute("aria-hidden", "true");
  const dotNodes = [];
  for (let i = 0; i < 4; i += 1) {
    const dot = document.createElement("span");
    dot.className = "wort-dot";
    dots.append(dot);
    dotNodes.push(dot);
  }
  face.append(text, dots);
  Object.assign(state.face, { text, dots: dotNodes });
}

function renderWort(h, m) {
  const face = state.face;
  const result = kit.wordClock(h, m, language());
  face.text.replaceChildren(...result.words.map((word, i) => {
    const span = document.createElement("span");
    span.className = "wort-word";
    span.textContent = i ? ` ${word}` : word;
    return span;
  }));
  face.text.dataset.time = `${pad(h)}:${pad(m)}`;
  face.dots.forEach((dot, i) => dot.classList.toggle("on", i < result.dots));
}

function renderFace(now, h, m, s) {
  if (!state.face || state.face.design !== state.design) buildFace();
  const face = state.face;
  const minuteKey = `${pad(h)}:${pad(m)}|${language()}`;
  if (face.key !== minuteKey) {
    face.key = minuteKey;
    $("face").setAttribute("aria-label", t("clock.face_label", { time: `${pad(h)}:${pad(m)}` }));
  }
  const digits = kit.timeDigits(h, m, s, !params.eink);
  if (state.design === "bahnhof") renderBahnhof(h, m, s, now.getMilliseconds());
  else if (state.design === "nixie") renderNixie(digits);
  else if (state.design === "flip") renderFlip(digits);
  else if (state.design === "wort" && face.text.dataset.key !== minuteKey) {
    face.text.dataset.key = minuteKey;
    renderWort(h, m);
  }
  setAttr($("face"), "data-time", params.eink ? `${pad(h)}:${pad(m)}` : `${pad(h)}:${pad(m)}:${pad(s)}`);
}

function setDesign(design, remember) {
  state.design = kit.safeDesign(design);
  $("design").value = state.design;
  root.dataset.design = state.design;
  if (remember) {
    store(DESIGN_KEY, state.design);
    // Steht ?design= in der Adresse, passt sie sich an – sonst gälte beim Neuladen wieder das alte.
    const url = new URL(window.location.href);
    if (url.searchParams.has("design")) {
      url.searchParams.set("design", state.design);
      window.history.replaceState(null, "", url);
    }
  }
  buildFace();
  render(new Date(serverMs()));
  restartSweep();
}

// --- Osterei: Schaltsekunde ------------------------------------------------------------
function renderEgg(nowMs) {
  const status = state.status || {};
  const kind = state.status ? kit.leapEgg(nowMs, status.leap, status.leap_next) : null;
  const node = $("leap-egg");
  if (!kind) { node.hidden = true; return; }
  const text = t(`clock.egg_${kind}`);
  if (node.textContent !== text) node.textContent = text;
  node.hidden = false;
}

// --- Zustandsband ------------------------------------------------------------------
function renderBand() {
  const band = $("band");
  const s = state.status;
  const stale = !state.lastOk || performance.now() - state.lastOk > STALE_MS;
  let tone; let main; const detail = [];
  if (!s) {
    tone = "unknown";
    main = state.error ? t("clock.no_connection", { error: state.error }) : t("clock.connecting");
  } else if (stale) {
    tone = "stale";
    const ago = Math.round((performance.now() - state.lastOk) / 1000);
    main = t("clock.no_connection_since", { seconds: ago });
    detail.push(t("clock.stale_detail"));
  } else {
    tone = ["good", "warn", "crit"].includes(s.level) ? s.level : "warn";
    if (!s.running) main = t("clock.chrony_down");
    else if (!s.synchronised) main = s.source_kind ? t("clock.unsynced_kind", { kind: s.source_kind }) : t("clock.unsynced");
    else main = t("clock.synced", { state: t(`clock.state.${tone}`), source: sourceText(s.source_kind, s.source) });
    if (typeof s.accuracy === "number") detail.push(t("clock.server_acc", { acc: fmtAccuracy(s.accuracy * 1000) }));
    if (s.leap && s.leap !== "Normal" && s.leap !== "Not synchronised") detail.push(t("clock.leap_announced", { leap: s.leap }));
  }
  if (state.sync) detail.push(t("clock.display_acc", { acc: fmtAccuracy(state.sync.accuracy), rtt: fmtAccuracy(state.sync.rtt).replace("± ", "") }));
  setAttr(band, "data-state", tone);
  setText($("band-main"), main);
  setText($("band-detail"), detail.join(" · "));
  setText($("band-wake"), state.wakeText);
  setAttr(band, "title", t("clock.band_title"));
}

// --- ⓘ (klein, ohne ui.js – siehe Kopf) --------------------------------------------------
let openInfo = null;
function closeInfo(focus = false) {
  if (!openInfo) return;
  const { button, node } = openInfo;
  node.remove();
  button.setAttribute("aria-expanded", "false");
  openInfo = null;
  if (focus) button.focus();
}

function infoButton(titleKey, textKey) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "info";
  button.setAttribute("aria-expanded", "false");
  const glyph = document.createElement("span");
  glyph.className = "info-glyph";
  glyph.setAttribute("aria-hidden", "true");
  glyph.textContent = "i";
  button.append(glyph);
  const label = () => button.setAttribute("aria-label", t("clock.info_label", { title: t(titleKey) }));
  label();
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    if (openInfo && openInfo.button === button) { closeInfo(); return; }
    closeInfo();
    const node = document.createElement("div");
    node.className = "popover clock-popover";
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-label", t(titleKey));
    const title = document.createElement("strong");
    title.className = "popover-title";
    title.textContent = t(titleKey);
    const text = document.createElement("p");
    text.textContent = t(textKey);
    node.append(title, text);
    document.body.append(node);
    const rect = button.getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 24);
    node.style.width = `${width}px`;
    node.style.left = `${Math.min(window.innerWidth - width - 12, Math.max(12, rect.left + rect.width / 2 - width / 2)) + window.scrollX}px`;
    const below = rect.bottom + 8 + node.offsetHeight < window.innerHeight;
    node.style.top = `${(below ? rect.bottom + 8 : Math.max(8, rect.top - node.offsetHeight - 8)) + window.scrollY}px`;
    button.setAttribute("aria-expanded", "true");
    openInfo = { button, node };
  });
  button.relabel = label;
  return button;
}
document.addEventListener("click", (event) => {
  if (openInfo && !openInfo.node.contains(event.target)) closeInfo();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && openInfo) closeInfo(true);
});
window.addEventListener("resize", () => closeInfo());

// --- Panels: Ton und „Mein Gerät“ ----------------------------------------------------------
function togglePanel(buttonId, panelId, open) {
  const panel = $(panelId);
  const show = open === undefined ? panel.hidden : open;
  panel.hidden = !show;
  $(buttonId).setAttribute("aria-expanded", show ? "true" : "false");
  return show;
}

// --- Ton auf der Sekunde ---------------------------------------------------------------
function toneStatus(text) {
  setText($("tone-status"), text);   // aria-live: denselben Satz nicht jede Sekunde neu ansagen lassen
}

function toneAccuracyText() {
  if (!state.sync) return t("clock.tone_unsynced");
  // Abgleich (± halbe RTT) plus Raster der Audiozeit (mit Ausgabezeitstempel ≈ 1 ms, sonst ≈ 3 ms).
  const extra = state.tone && state.tone.exact ? 1 : 3;
  return t("clock.tone_running", { acc: fmtAccuracy(state.sync.accuracy + extra) });
}

async function startTone(mode) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) { toneStatus(t("clock.tone_unsupported")); return; }
  if (!state.tone) {
    let ctx;
    try { ctx = new Ctx({ latencyHint: "interactive" }); } catch (error) { toneStatus(t("clock.tone_unsupported")); return; }
    state.tone = { ctx, mode, last: -Infinity, exact: false };
  }
  state.tone.mode = mode;
  state.tone.last = -Infinity;
  try { await state.tone.ctx.resume(); } catch (error) { /* bleibt stumm, Anzeige läuft trotzdem */ }
  $("tone-seconds").setAttribute("aria-pressed", mode === "seconds" ? "true" : "false");
  $("tone-countdown").setAttribute("aria-pressed", mode === "countdown" ? "true" : "false");
  toneTick(serverMs());
}

function stopTone() {
  if (state.tone) {
    state.tone.ctx.close().catch(() => {});
    state.tone = null;
  }
  $("tone-seconds").setAttribute("aria-pressed", "false");
  $("tone-countdown").setAttribute("aria-pressed", "false");
  $("tone-count").hidden = true;
  toneStatus(t("clock.tone_stopped"));
}

function toneTick(nowMs) {
  const tone = state.tone;
  if (!tone) return;
  const { ctx } = tone;
  if (ctx.state === "running") {
    const clock = kit.audioClock(ctx, performance.now(), Date.now(), offsetMs());
    tone.exact = clock.exact;
    for (const planned of kit.planTones(clock, { mode: tone.mode, afterSecond: tone.last, horizonMs: 1500 })) {
      tone.last = planned.second;
      if (planned.at > ctx.currentTime + 0.005) kit.scheduleTone(ctx, planned);
    }
  }
  const count = $("tone-count");
  if (tone.mode === "countdown") {
    const value = kit.countdownValue(nowMs);
    const into = Math.floor(nowMs / 1000) % 60;
    count.textContent = value === null ? t("clock.countdown_wait", { seconds: 60 - kit.COUNTDOWN_SECONDS - into })
      : (value === 0 ? t("clock.countdown_now") : String(value));
    count.dataset.value = value === null ? "" : String(value);
    count.hidden = false;
  } else {
    count.hidden = true;
  }
  toneStatus(ctx.state === "running" ? toneAccuracyText() : t("clock.tone_blocked"));
}

// --- „Wie falsch geht dein Gerät?“ ---------------------------------------------------------
function renderDevice() {
  if ($("device-panel").hidden) return;
  const node = $("device-value");
  const drift = state.sync ? kit.deviceDrift(state.sync.offset, state.sync.accuracy) : null;
  if (!drift) {
    node.dataset.tone = "unknown";
    $("device-text").textContent = t("clock.device_measuring");
    $("device-line").textContent = t("clock.device_line_unknown");
    return;
  }
  node.dataset.tone = drift.tone;
  if (drift.dir === "uncertain") {
    $("device-text").textContent = t("clock.device_uncertain");
    $("device-line").textContent = t("clock.device_line_uncertain", { acc: fmtAccuracy(state.sync.accuracy) });
    return;
  }
  $("device-text").textContent = drift.dir === "exact" ? t("clock.device_exact")
    : t(drift.dir === "behind" ? "clock.device_behind" : "clock.device_ahead", { value: kit.fmtDrift(drift.abs) });
  $("device-line").textContent = t(`clock.device_line_${drift.tone}`, { acc: fmtAccuracy(state.sync.accuracy) });
}

// --- Bildschirm wach halten ---------------------------------------------------------
async function keepAwake() {
  if (!("wakeLock" in navigator)) {
    state.wakeText = window.isSecureContext ? "" : t("clock.wake_https");
    renderBandLive();
    return;
  }
  try {
    state.wake = await navigator.wakeLock.request("screen");
    state.wakeText = t("clock.wake_on");
    state.wake.addEventListener("release", () => { state.wakeText = ""; renderBandLive(); });
  } catch (error) {
    state.wakeText = "";
  }
  renderBandLive();
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    keepAwake();
    restartSweep();
    burst();   // nach dem Aufwachen (Tablet im Standby) sofort neu abgleichen
  }
});

// --- Darstellung: hell/dunkel, Rotlicht, E-Ink, Kiosk, Vollbild ------------------------------
function applyModes() {
  const theme = store("ntp-gui-clock-theme") || "dark";
  const red = store("ntp-gui-clock-red") === "1";
  root.dataset.theme = params.eink ? "light" : (theme === "light" ? "light" : "dark");
  if (params.eink) root.dataset.mode = "eink";
  else if (red) root.dataset.mode = "red";
  else delete root.dataset.mode;
  // Beschriftung = Aktion („Dunkel“ im hellen Modus), daher kein aria-pressed: „Dunkel, gedrückt“ wäre falsch.
  $("mode-theme").textContent = theme === "light" ? t("clock.theme_dark") : t("clock.theme_light");
  $("mode-red").setAttribute("aria-pressed", red ? "true" : "false");
  $("mode-theme").disabled = red || params.eink;
  $("mode-red").disabled = params.eink;
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
  if (event.target instanceof Element && event.target.closest("select, input, textarea")) return;
  if (event.key === "f" || event.key === "F") toggleFullscreen();
});
$("design").addEventListener("change", (event) => setDesign(event.target.value, true));
$("mode-tone").addEventListener("click", () => {
  togglePanel("mode-tone", "tone-panel");
});
$("mode-device").addEventListener("click", () => {
  if (togglePanel("mode-device", "device-panel")) renderDevice();
});
$("tone-seconds").addEventListener("click", () => startTone("seconds"));
$("tone-countdown").addEventListener("click", () => startTone("countdown"));
$("tone-off").addEventListener("click", stopTone);
reducedMotion.addEventListener?.("change", () => restartSweep());

// Leiste ausblenden, wenn sich nichts bewegt (Wandmonitor); Tippen/Bewegen holt sie zurück.
let idleTimer = null;
function mayHide() {
  // Offene Panels bleiben bedienbar: dann nicht ausblenden. Erst beim Ablauf prüfen – wake() läuft bei
  // pointerdown/keydown, also bevor der Klick das Panel öffnet. Liegt der Tastaturfokus in der Leiste, bleibt
  // sie ebenfalls sichtbar (nach einem Mausklick nicht, sonst bliebe sie am Wandmonitor für immer stehen).
  if (!$("tone-panel").hidden || !$("device-panel").hidden) return false;
  const focus = document.activeElement;
  return !(focus && focus.closest(".clock-bar") && focus.matches(":focus-visible"));
}
function wake() {
  document.body.classList.remove("is-idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { if (mayHide()) document.body.classList.add("is-idle"); }, IDLE_MS);
}
for (const type of ["pointermove", "pointerdown", "keydown", "focusin"]) document.addEventListener(type, wake, { passive: true });

function relabel() {
  applyModes();
  for (const button of document.querySelectorAll(".clock-panel button.info")) button.relabel?.();
  if (state.face) state.face.key = "";
  if (state.face && state.face.text) state.face.text.dataset.key = "";
  render(new Date(serverMs()));
  renderBand();
  renderDevice();
}

// --- Start ------------------------------------------------------------------------------
if (params.kiosk) document.body.classList.add("is-kiosk");
if (params.eink) document.body.classList.add("is-eink");
if (params.eink) $("mode-tone").hidden = true;   // E-Ink rechnet nur einmal je Minute
if (params.tz) {
  $("tz2").hidden = false;
  $("tz2-label").textContent = kit.zoneLabel(params.tz);
}
$("tone-info").append(infoButton("clock.tone_info_title", "clock.tone_info"));
$("device-info").append(infoButton("clock.device_info_title", "clock.device_info"));
applyModes();
setDesign(params.design || store(DESIGN_KEY), false);
wake();
tick();
keepAwake();
burst();
setInterval(burst, RESYNC_MS);
setInterval(poll, POLL_MS);
initI18n().then(relabel, () => {});
