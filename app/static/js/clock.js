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
// Studiouhr (Etappe A1): Die Anzeige rechnet mit einem Anker aus der besten Messung und der monotonen
// Uhr performance.now() (kit.anchoredNow), nicht mit Date.now() + Versatz. Verstellt das Gerät seine Uhr,
// springt die Anzeige nicht mit. Neu gemessen wird beim Zurückkommen (visibilitychange), wenn ein Takt
// mehr als 2 s zu spät kommt, und wenn Geräteuhr und performance.now() seit dem Anker um mehr als 2 s
// auseinanderlaufen (kit.wallJump: Standby auf Plattformen, deren monotone Uhr im Schlaf steht, oder verstellte
// Geräteuhr). Bis zum neuen Anker gilt die Anzeige dann als unsicher, ohne Schranke. Die Fehlerschranke (kit.errorBound) bestimmt data-sync am Root
// (ok|free|degraded|none, sichtbar als Text mit Symbol) und graut Stellen aus, die sie nicht trägt.
// ?lead=0..200 lässt die Anzeige so viele ms vorlaufen (Bildprozessor im Fernseher); der Ton bleibt exakt.
//
// Studiouhr A3/A4: Die Bühne (.clock-stage um main, container-type: size) wählt ihr Layout aus ihrer eigenen Größe
// (kit.resolveLayout, gesetzt als data-layout per ResizeObserver; ?layout= übersteuert). Sicherheitsrand (?safe=),
// Größe (?scale=), Schriftstärke (?weight=), Hintergrund (?bg=), sichtbare Elemente (?show=) und Pixel-Shift (?shift=,
// acht Klassen im 2-min-Takt) kommen nur über data-Attribute, Klassen und CSSOM-Variablen – nie über style-Attribute.
// Design studio und digital mit face=seg zeichnen 7-Segment-Ziffern als SVG (clockfaces.js). Themen (?look=) stehen
// in clock.css, Akzent- und Ziffernfarbe (?accent=, ?color=) setzt clock.js nach Kontrastprüfung (≥ 4,5:1) per
// documentElement.style.setProperty. Bewegung gibt es nur als Klassenwechsel je Sekunde.
//
// Studiouhr A5: Countdown und Count-up (clockcount.js). ?until= rechnet auf der korrigierten Serverzeit in der
// Zeitzone des Servers (zone aus /api/v1/time) – alle Bildschirme zeigen dasselbe, ohne Steuerkanal. ?timer= und die
// Stoppuhr (Leertaste ohne Ziel) laufen lokal als Zustandsautomat auf performance.now(). Farbstufen (?warn=) immer mit
// Symbol und Text, ?beep= über denselben Tonweg wie „Ton auf der Sekunde“ (kit.audioClock, kit.scheduleTone).
// Tastenkürzel F, D, L, U, T, Leertaste/R, +/−, A und ? (Übersicht); ?lock=1 schaltet sie ab.
//
// Studiouhr A6: Panel „Anpassen“ (Formular aus dem Schema, clocklink.js). Übernommen wird in den localStorage; der
// Stand gilt, wenn /clock ohne Parameter aufgerufen wird. ?p=name lädt ein Profil vom Server (GET
// /api/v1/clock/profile, Rangfolge Profil < Adresse). /api/v1/time meldet profiles_rev: Ändert sich der Wert, holt
// die Seite ihr Profil beim nächsten Abgleich neu und lädt sich neu, wenn sich daran etwas geändert hat. Scheitert
// der Abruf (Netz, 5xx, 401), versucht sie es mit wachsendem Abstand (5 s bis 60 s) erneut und lädt sich nach dem
// ersten Erfolg neu; bis dahin läuft die Standarduhr, nicht der im Panel gemerkte Stand.
//
// Bewusst ohne app.js/ui.js: Die Seite muss auch ohne Anmeldung (clock_public) laufen und
// lädt deshalb nur Dateien, die keine Inhalte aus Konfiguration oder Status enthalten
// (clocksync.js, clockkit.js, util.js, i18n.js und die Sprachkataloge).
import { fromResponse, best, isoWeek, hms, fmtAccuracy, sourceText } from "./clocksync.js";
import { initI18n, t, language } from "./i18n.js";
import { svgEl } from "./util.js";
import * as kit from "./clockkit.js";
import * as faces from "./clockfaces.js";
import * as cd from "./clockcount.js";
import * as link from "./clocklink.js";
import { copyText } from "./util.js";

const BURST = 5;
const BURST_GAP_MS = 250;
const RESYNC_MS = 60_000;
const POLL_MS = 5_000;
const STALE_MS = kit.STALE_MS;
const FRAME_SAMPLES = 6;
const TIMEOUT_MS = 4_000;
const IDLE_MS = 4_000;
const DESIGN_KEY = "ntp-gui-clock-design";
const HINT_MS = 2_000;
// Art des Countdowns: absolutes Ziel (?until=, synchron auf allen Bildschirmen), lokaler Timer (?timer=) oder
// Stoppuhr (ohne beides, Start mit der Leertaste).

const $ = (id) => document.getElementById(id);
const root = document.documentElement;
const ZONES = kit.supportedZones();
const PROFILE = link.profileFromSearch(window.location.search);
// Startwerte aus der Adresse bzw. dem gemerkten Stand; ein Profil (?p=) kommt in start() dazu (Object.assign).
const params = kit.parseParams(link.effectiveQuery({ search: window.location.search, stored: store(link.STORE_KEY) || "",
  zones: ZONES }), ZONES);
const reducedMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
const state = {
  sync: null,          // beste Messung der letzten Runde {offset, rtt, accuracy, at, perf}
  anchor: null,        // { server, perf } aus dieser Messung – Grundlage der Anzeige
  frameMs: kit.FRAME_MS,
  planned: null,       // { perf, delay } des nächsten Takts (Lücke erkennen)
  bursting: false,
  jumped: false,       // Geräteuhr und monotone Uhr seit dem Anker auseinander: unsicher bis zum nächsten Anker
  syncKey: "",
  bandSync: "",        // Zustand der Zeitbasis beim letzten Zeichnen des Bands
  status: null,        // letzte Antwort von /api/v1/time
  lastOk: 0,           // performance.now() der letzten erfolgreichen Antwort
  error: "",
  wake: null,
  wakeText: "",
  design: kit.DEFAULT_DESIGN,
  face: null,          // Teile des aktuellen Designs
  tone: null,          // { ctx, mode, last, exact }
  tickTimer: null,
  layout: "",          // aufgelöstes Layout der Bühne (data-layout)
  stage: { width: 0, height: 0 },
  shift: -1,           // aktuelle Pixel-Shift-Klasse
  minuteKey: "",       // für die Auto-Anpassung der Zeitbreite einmal je Minute
  chrome: 0,           // Höhe von Kopfzeile und Band, solange sie im Streifen ausgeblendet sind (is-compact)
  timer: null,         // lokaler Timer bzw. Stoppuhr (cd.timerNew …), null: keiner
  timerTimer: null,
  tenths: false,       // Taste T: Zehntel bei Stoppuhr und Timer
  utcBig: false,       // Taste U: UTC als große Zeit
  cdPrev: NaN,         // Restsekunden der letzten Anzeige (Ansagen an Schwellen)
  cdZone: undefined,   // Zeitzone, in der ?until= zuletzt gerechnet wurde (undefined: noch keine)
  cdShape: "",         // Breite und Art der Countdown-Anzeige (bei Änderung neu einpassen)
  cdTone: null,        // { ctx, lastK, target, oscs } für ?beep= (oscs: geplante, noch nicht verklungene Töne)
  hintTimer: null,
  keysReturn: null,    // Element mit dem Fokus vor dem Öffnen der Kürzel-Übersicht
  profile: null,       // geladenes Profil (?p=) { name, title, params, profiles_rev }
  profileKey: "",      // Inhalt des Profils beim Laden (Vergleich nach einer Änderung von profiles_rev)
  profileRev: null,    // zuletzt gesehenes profiles_rev
  profileBusy: false,
  profileError: "",
  profileTries: 0,     // gescheiterte Abrufe in Folge (Abstand des nächsten Versuchs)
  profileRetryAt: 0,   // performance.now(), ab dem der nächste Versuch kommt
  customRaw: null,     // Rohwerte im Panel „Anpassen“
  ready: false,        // Start abgeschlossen (Profil geladen): erst dann wirken Tastenkürzel
};
let COUNT_MODE = "watch";
function initCountMode() {
  COUNT_MODE = params.until ? "until" : (params.timer ? "timer" : "watch");
  state.timer = COUNT_MODE === "timer" ? cd.timerNew(params.timer) : null;
  if (params.until && params.timer) console.info("/clock: until und timer zugleich – es gilt until");
  if (params.ignored.length) console.info(`/clock: unzulässige Werte ignoriert (${params.ignored.join(", ")})`);
}

// Nur schreiben, was sich wirklich ändert: Das Band und #tone-status sind aria-live-Regionen (sonst sagt der
// Screenreader denselben Satz immer wieder an), und E-Ink aktualisiert sonst bei jeder Zuweisung.
function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}
function setAttr(node, name, value) {
  if (node.getAttribute(name) !== value) node.setAttribute(name, value);
}
function setHidden(node, hidden) {
  if (node.hidden !== hidden) node.hidden = hidden;
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
    if (measured) measured.perf = perf3;   // für den Anker: t3 auf der monotonen Uhr
    state.status = payload;
    checkProfileRev(payload.profiles_rev);
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
  if (state.bursting) return;
  state.bursting = true;
  const results = [];
  try {
    for (let i = 0; i < BURST; i += 1) {
      const m = await sample();
      if (m) results.push(m);
      if (i < BURST - 1) await wait(BURST_GAP_MS);
    }
  } finally {
    state.bursting = false;
  }
  const winner = best(results);
  const anchor = kit.anchorFrom(winner);
  if (winner && anchor) {
    state.sync = winner;
    state.anchor = anchor;
    state.jumped = false;
    // Neuer Anker: die Restzeit kann springen (erster Anker nach der Gerätezeit) – das ist kein erlebter Übergang.
    state.cdPrev = NaN;
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

// --- Profil (?p=name) ---------------------------------------------------------------------------
/** Profil vom Server holen: { name, title, params, profiles_rev } oder null (Fehlertext in state.profileError). */
async function fetchProfile() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(`/api/v1/clock/profile?p=${encodeURIComponent(PROFILE)}`, {
      cache: "no-store", credentials: "same-origin", signal: controller.signal, headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      state.profileError = response.status === 404 ? "missing" : (response.status === 401 ? "login" : "error");
      return null;
    }
    const data = await response.json();
    state.profileError = "";
    return data && typeof data === "object" && data.params && typeof data.params === "object" ? data : null;
  } catch (error) {
    state.profileError = "error";
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** Vergleichswert eines Profils: nur das, was die Anzeige bestimmt. */
function profileKey(profile) {
  if (!profile) return "";
  return JSON.stringify({ title: profile.title || "", query: link.layerQuery(link.rawParams(profile.params, ZONES)) });
}

/**
 * profiles_rev aus /api/v1/time: Ändert er sich, das Profil neu holen und die Seite neu laden, wenn sich das eigene
 * Profil geändert hat (ein anderes Profil zu speichern lässt diesen Bildschirm in Ruhe).
 */
function checkProfileRev(rev) {
  const step = link.profileStep({ name: PROFILE, loaded: Boolean(state.profile), error: state.profileError,
    seenRev: state.profileRev, rev, busy: state.profileBusy, now: performance.now(), retryAt: state.profileRetryAt });
  if (step === "adopt") { state.profileRev = rev; return; }
  if (step === "retry") { retryProfile(); return; }
  if (step !== "refetch") return;
  state.profileBusy = true;
  fetchProfile().then((profile) => {
    state.profileBusy = false;
    if (!profile && state.profileError !== "missing") return;   // Netzfehler: beim nächsten Abgleich noch einmal
    state.profileRev = rev;
    if (profileKey(profile) !== state.profileKey) window.location.reload();
  });
}

/** Abruf nach einem Fehlschlag wiederholen; gelingt er, mit dem Profil neu laden (alle Startwerte hängen daran). */
function retryProfile() {
  state.profileBusy = true;
  fetchProfile().then((profile) => {
    state.profileBusy = false;
    if (profile) { window.location.reload(); return; }
    noteProfileFailure();
    renderProfileTitle();
  });
}

function noteProfileFailure() {
  state.profileRetryAt = performance.now() + link.profileRetryDelay(state.profileTries);
  state.profileTries += 1;
}

/** Titel des Profils (oder ein Hinweis, warum es fehlt) in der Kopfzeile und im Fenstertitel. */
function renderProfileTitle() {
  const node = $("clock-title");
  if (!PROFILE) return;
  const key = link.presetTitleKey(state.profile);
  const preset = key ? t(key) : "";
  const title = state.profile ? ((preset && preset !== key ? preset : "") || state.profile.title || "") : "";
  const error = state.profileError ? t(`clock.profile_${state.profileError}`, { name: PROFILE }) : "";
  setText(node, error || title);
  node.classList.toggle("is-error", Boolean(error));
  node.hidden = !(error || title);
  document.title = title ? `${title} · ${t("clock.page_title")}` : t("clock.page_title");
}

/**
 * Band nach einer Messung oder Abfrage zeichnen. E-Ink: nur zum Minutenwechsel (tick) – außer das Band zeigt
 * noch „verbinde …“, dann einmal sofort, damit es nicht bis zur nächsten Minute leer bleibt.
 */
function renderBandLive() {
  if (params.eink && $("band").dataset.state !== "unknown") return;
  renderBand();
}

// Serverzeit aus Anker + performance.now(); vor dem ersten Abgleich die Gerätezeit (Zustand „none“).
const trueMs = (perf = performance.now()) => kit.anchoredNow(state.anchor, perf, Date.now());
// Angezeigte Zeit: mit Vorlauf (?lead=) für die Verzögerung des Bildschirms. Ton und Abgleich ohne Vorlauf.
const serverMs = () => trueMs() + params.lead;

/** Fehlerschranke und Zustand jetzt: { state, bound, sinceOk }. */
function syncInfo() {
  const perf = performance.now();
  const s = state.status || {};
  const sinceOk = state.lastOk ? perf - state.lastOk : Infinity;
  const bound = state.anchor && !state.jumped ? kit.errorBound({
    serverAccMs: typeof s.accuracy === "number" ? s.accuracy * 1000 : NaN,
    rttMs: state.sync.rtt, ageMs: perf - state.anchor.perf, frameMs: state.frameMs,
  }) : null;
  const serverSynced = !state.status || (s.running !== false && s.synchronised !== false);
  return { state: kit.syncState({ anchored: Boolean(state.anchor), sinceOkMs: sinceOk, boundMs: bound,
    maxerrMs: params.maxerr, serverSynced, jumped: state.jumped }), bound, sinceOk };
}

/** data-sync, ausgegraute Stellen und die Zeile unter der Uhr (Text + Symbol, nie nur Farbe). Liefert syncInfo(). */
function renderSync() {
  const info = syncInfo();
  // E-Ink: nur zum Minutenwechsel oder bei neuem Zustand neu zeichnen (jede Änderung lässt das Display blinken).
  if (params.eink) {
    const key = `${info.state}|${Math.floor(serverMs() / 60_000)}`;
    if (key === state.syncKey) return info;
    state.syncKey = key;
  }
  const fine = kit.fineDigits(info.bound, { maxerrMs: params.maxerr });
  setAttr(root, "data-sync", info.state);
  setAttr(root, "data-seconds", info.state === "none" ? "unsure" : fine.seconds);
  const acc = info.bound === null ? "" : fmtAccuracy(info.bound);
  let text;
  if (info.state === "none") text = t("clock.sync_none");
  else if (info.state === "free") text = t("clock.sync_free", { since: kit.fmtAge(info.sinceOk), acc: acc || "?" });
  else if (info.state === "degraded" && state.jumped) text = t("clock.sync_jump");
  else if (info.state === "degraded") text = acc ? t("clock.sync_degraded", { acc }) : t("clock.sync_degraded_unknown");
  else text = t("clock.sync_ok", { acc });
  if (params.lead) text += ` · ${t("clock.sync_lead", { ms: params.lead })}`;
  const node = $("clock-sync");
  setAttr(node, "data-sync", info.state);
  setText($("clock-sync-icon"), { ok: "✓", free: "○", degraded: "!", none: "–" }[info.state]);
  setText($("clock-sync-text"), text);
  return info;
}

/** Dauer einer Bildauffrischung einmal messen (sechs Bilder, Median); sonst gilt kit.FRAME_MS. */
function measureFrame() {
  if (params.eink || document.visibilityState !== "visible" || typeof window.requestAnimationFrame !== "function") return;
  const stamps = [];
  const step = (stamp) => {
    stamps.push(stamp);
    if (stamps.length < FRAME_SAMPLES) window.requestAnimationFrame(step);
    else state.frameMs = kit.frameFromStamps(stamps);
  };
  window.requestAnimationFrame(step);
}

// --- Anzeige ---------------------------------------------------------------------
const pad = (n) => String(n).padStart(2, "0");
const DATE_FMT = new Map();
// Datumszeile nach ?date= (long, short, iso) und ?show= (ohne „weekday“ kein Wochentag, nur „weekday“: nur er).
const DATE_STYLES = {
  long: { weekday: "long", day: "numeric", month: "long", year: "numeric" },
  plain: { day: "numeric", month: "long", year: "numeric" },
  weekday: { weekday: "long" },
  short: { day: "2-digit", month: "2-digit", year: "numeric" },
};
function dateText(now, style = dateStyle()) {
  if (style === "iso") return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  if (style === "off") return "";
  const tag = language() === "en" ? "en-GB" : "de-DE";
  const key = `${tag}|${style}`;
  if (!DATE_FMT.has(key)) DATE_FMT.set(key, new Intl.DateTimeFormat(tag, DATE_STYLES[style] || DATE_STYLES.long));
  return DATE_FMT.get(key).format(now);
}
function dateStyle() {
  if (params.date !== "long") return params.date;
  if (!params.show) return "long";
  const date = params.show.includes("date");
  const weekday = params.show.includes("weekday");
  if (date && weekday) return "long";
  if (weekday) return "weekday";
  return date ? "plain" : "off";
}
let tzFormat = null;
function zoneTime(now) {
  if (!tzFormat) tzFormat = new Intl.DateTimeFormat("en-GB", { timeZone: params.tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return tzFormat.format(now);
}

function tick() {
  // Kam dieser Takt mehr als 2 s zu spät (Standby, gedrosselter Tab), gleich neu abgleichen.
  const perf = performance.now();
  if (state.planned && kit.tickGap(state.planned.perf, perf, state.planned.delay)) burst();
  // Geräteuhr gegen die monotone Uhr seit dem Anker: Standby (monotone Uhr stand) oder verstellte Uhr. Die Anzeige
  // bleibt am Anker (springt nicht mit), gilt aber bis zum neuen Anker als unsicher; sofort neu messen.
  if (!state.jumped && kit.wallJump(state.anchor, perf, Date.now())) {
    state.jumped = true;
    burst();
  }
  const nowMs = serverMs();
  const now = new Date(nowMs);
  render(now);
  const remaining = renderCountdown(nowMs);
  const info = renderSync();
  // Zustandswechsel der Zeitbasis auch im Band (aria-live) ansagen – nicht nur in der Zeile unter der Uhr.
  if (info.state !== state.bandSync) renderBandLive();
  // Ampel wird grau, sobald 10 s keine Antwort kam – auch ohne neue Antwort prüfen.
  const stale = !state.lastOk || performance.now() - state.lastOk > STALE_MS;
  document.body.classList.toggle("is-stale", stale && Boolean(state.status));
  if (state.status && (stale || $("band").dataset.state === "stale" || params.eink)) renderBand();
  if (state.tone) toneTick(trueMs());
  // Nächster Schritt genau zur vollen Sekunde der angezeigten Zeit (E-Ink: zur vollen Minute, bei laufendem Countdown
  // oder Timer auch zu dessen Minutensprüngen und genau auf dem Ziel).
  const later = serverMs();
  const delay = params.eink ? cd.einkDelay(later, remaining - (later - nowMs)) : 1000 - (((later % 1000) + 1000) % 1000) + 5;
  state.planned = { perf: performance.now(), delay };
  state.tickTimer = setTimeout(tick, delay);
}

function render(now) {
  // Taste U: UTC als große Zeit, die Ortszeit steht dann in der Zeile darunter.
  const utc = state.utcBig;
  const h = utc ? now.getUTCHours() : now.getHours();
  const m = utc ? now.getUTCMinutes() : now.getMinutes();
  const s = utc ? now.getUTCSeconds() : now.getSeconds();
  // Stunden, Minuten und Sekunden getrennt: Die Sekunden können allein grau werden (data-seconds), der Doppelpunkt
  // allein blinken (?colon=blink: ein Attributwechsel je Sekunde).
  const hour = kit.hourText(h, { h12: params.h12, lz: params.lz });
  setText($("local-h"), hour.text.trimStart());
  setText($("local-m"), pad(m));
  setText($("local-s"), params.eink ? "" : pad(s));
  setHidden($("local-sec"), params.eink);
  // Mit führendem Leerzeichen: Der Screenreader liest „6:02:08 PM“ statt „6:02:08PM“ (der Abstand kommt aus dem Leerzeichen).
  setText($("local-ampm"), hour.ampm ? ` ${hour.ampm}` : "");
  setHidden($("local-ampm"), !hour.ampm);
  if (params.colon === "blink" && !params.eink) setAttr(root, "data-colon", s % 2 ? "off" : "on");
  const stamp = params.eink ? new Date(Math.floor(now.getTime() / 60_000) * 60_000) : now;
  setAttr($("local-time"), "datetime", stamp.toISOString());
  setText($("local-label"), utc ? "UTC" : t("clock.local"));
  setText($("utc-label"), utc ? t("clock.local") : "UTC");
  setText($("utc-time"), params.eink ? hms(now, !utc).slice(0, 5) : hms(now, !utc));
  setText($("local-date"), dateText(now));
  const { week } = isoWeek(now);
  setText($("iso-week"), t("clock.week", { week }));
  if (params.tz) setText($("tz2-time"), zoneTime(now));
  renderFace(now, h, m, s);
  renderShift(now.getTime());
  renderEgg(now.getTime());
  const minuteKey = `${h}:${m}|${language()}`;
  if (minuteKey !== state.minuteKey) {
    state.minuteKey = minuteKey;
    fitTime();
  }
}

// --- Designs -----------------------------------------------------------------------
function textTime() {
  return state.design === "digital" && params.face !== "seg";
}

function buildFace() {
  const face = $("face");
  face.replaceChildren();
  const seg = state.design === "digital" && params.face === "seg";
  face.className = `clock-face face-${seg ? "seg" : state.design}`;
  const text = textTime();
  face.hidden = text;
  $("local-time").hidden = !text;
  state.face = { design: state.design, key: "" };
  if (text) return;
  face.setAttribute("role", "img");
  if (seg) Object.assign(state.face, faces.buildSegRow(face, { count: digitCount(), h12: params.h12 }), { seg: true });
  else if (state.design === "studio") {
    Object.assign(state.face, faces.buildStudio(face, { seconds: params.seconds, sub: params.sub, h12: params.h12 }));
    // E-Ink rechnet nur einmal je Minute: weder Kranz noch Sekundenziffern.
    if (params.eink) for (const part of [state.face.ring, state.face.secGroup]) part.classList.add("is-off");
  } else if (state.design === "bahnhof") buildBahnhof(face);
  else if (state.design === "nixie") buildNixie(face);
  else if (state.design === "flip") buildFlip(face);
  else if (state.design === "wort") buildWort(face);
}

// Ohne Sekunden (E-Ink, ?show= ohne „seconds“) nur HH:MM.
function digitCount() { return params.eink || (params.show && !params.show.includes("seconds")) ? 4 : 6; }

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
    tube.className = i >= 4 ? "nixie-tube is-sec" : "nixie-tube";
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
    card.className = i >= 4 ? "flip-card is-sec" : "flip-card";
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
    $("face").setAttribute("aria-label", faceLabel(h, m));
  }
  const digits = kit.timeDigits(h, m, s, !params.eink);
  if (face.seg) renderSeg(h, m, s);
  else if (state.design === "studio") renderStudio(now, h, m, s);
  else if (state.design === "bahnhof") renderBahnhof(h, m, s, now.getMilliseconds());
  else if (state.design === "nixie") renderNixie(digits);
  else if (state.design === "flip") renderFlip(digits);
  else if (state.design === "wort" && face.text.dataset.key !== minuteKey) {
    face.text.dataset.key = minuteKey;
    renderWort(h, m);
  }
  setAttr($("face"), "data-time", params.eink ? `${pad(h)}:${pad(m)}` : `${pad(h)}:${pad(m)}:${pad(s)}`);
}

/** Zeit des Zifferblatts für den Screenreader: wie angezeigt, mit ?h12=1 also „6:02 PM“ statt „18:02 Uhr“. */
function faceLabel(h, m) {
  if (!params.h12) return t("clock.face_label", { time: `${pad(h)}:${pad(m)}` });
  const hour = kit.hourText(h, { h12: true, lz: params.lz });
  return `${hour.text.trimStart()}:${pad(m)} ${hour.ampm}`;
}

/** 7-Segment-Zeile (digital, face=seg): nur geänderte Stellen bekommen eine neue Klasse. */
function renderSeg(h, m, s) {
  const face = state.face;
  const hour = kit.hourText(h, { h12: params.h12, lz: params.lz });
  const chars = `${hour.text}${pad(m)}${pad(s)}`;
  face.digits.forEach((node, index) => faces.setDigit(node, chars[index]));
  if (face.ampm) setText(face.ampm, hour.ampm);
}

/** Design studio: HH:MM, Sekunden als Ziffern und/oder Kranz, Zeile darunter nach ?sub=. */
function renderStudio(now, h, m, s) {
  const face = state.face;
  const hour = kit.hourText(h, { h12: params.h12, lz: params.lz });
  const chars = `${hour.text}${pad(m)}`;
  face.digits.forEach((node, index) => faces.setDigit(node, chars[index]));
  if (!params.eink) {
    face.secDigits.forEach((node, index) => faces.setDigit(node, pad(s)[index]));
    faces.setRing(face.dots, s);
  }
  if (face.ampm) setText(face.ampm, hour.ampm);
  let sub = "";
  if (state.utcBig && (params.sub === "utc" || (params.sub === "tz2" && !params.tz))) sub = `${t("clock.local")} ${hms(now).slice(0, 5)}`;
  else if (params.sub === "utc" || (params.sub === "tz2" && !params.tz)) sub = `UTC ${hms(now, true).slice(0, 5)}`;
  else if (params.sub === "tz2") sub = `${kit.zoneLabel(params.tz)} ${zoneTime(now)}`;
  else if (params.sub === "date") sub = dateText(now, "short");
  setText(face.sub, sub);
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
    // Ebenso der im Panel „Anpassen“ gemerkte Stand: Er gilt beim Start vor DESIGN_KEY – aber nur, wenn diese Adresse
    // ihn überhaupt anwendet (/clock ohne Parameter). Ein Profil- oder Link-Bildschirm lässt ihn unberührt.
    const stored = link.storedApplies(window.location.search) ? store(link.STORE_KEY) : null;
    if (stored) {
      const next = link.storedWith(stored, "design", state.design, ZONES);
      if (next) store(link.STORE_KEY, next);
      else removeStored(link.STORE_KEY);
    }
  }
  buildFace();
  render(new Date(serverMs()));
  restartSweep();
  fitTime();
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
  const display = syncInfo().state;
  state.bandSync = display;
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
    // Server synchron, Anzeige aber unsicher (Schranke über maxerr, Uhrsprung): nicht als grünes „synchron“ melden.
    if (display === "degraded") {
      if (tone === "good") tone = "warn";
      main = t("clock.band_unsure", { server: main });
    }
    if (typeof s.accuracy === "number") detail.push(t("clock.server_acc", { acc: fmtAccuracy(s.accuracy * 1000) }));
    if (s.leap && s.leap !== "Normal" && s.leap !== "Not synchronised") detail.push(t("clock.leap_announced", { leap: s.leap }));
  }
  if (state.sync) detail.push(t("clock.match_acc", { acc: fmtAccuracy(state.sync.accuracy), rtt: fmtAccuracy(state.sync.rtt).replace("± ", "") }));
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
  // Mit offenem Panel bekommt die Bühne eine Mindesthöhe (sonst drückte das Panel sie auf null zusammen).
  document.body.classList.toggle("has-panel", !$("tone-panel").hidden || !$("device-panel").hidden || !$("custom-panel").hidden);
  return show;
}

// --- Panel „Anpassen“ (Link-Baukasten auf der Uhr) --------------------------------------------
/** Rohwerte, mit denen die Seite läuft (Adresse, Profil oder gemerkter Stand) – Ausgangspunkt des Formulars. */
function currentRaw() {
  const search = window.location.search;
  if (state.profile) return link.rawParams(link.effectiveQuery({ search, profile: state.profile.params, zones: ZONES }), ZONES);
  return link.rawParams(link.effectiveQuery({ search, stored: store(link.STORE_KEY) || "", zones: ZONES }), ZONES);
}

function customStatus(text) {
  setText($("custom-status"), text);
}

function openCustom() {
  if (!togglePanel("mode-custom", "custom-panel")) return;
  state.customRaw = currentRaw();
  const form = link.buildForm({ values: state.customRaw, prefix: "custom", zones: ZONES, exclude: link.STORE_SKIP,
    excludeValues: link.STORE_SKIP_VALUES, onChange: () => customStatus("") });
  $("custom-form").replaceChildren(form);
  setHidden($("custom-url-note"), !(PROFILE || link.hasSchemaParams(window.location.search)));
  customStatus("");
}

function applyCustom() {
  const query = link.storedQuery(link.buildQuery(state.customRaw || {}, ZONES), ZONES);   // ohne kiosk/lock/layout=tile
  if (query) store(link.STORE_KEY, query);
  else removeStored(link.STORE_KEY);
  window.location.assign("/clock");
}

function resetCustom() {
  removeStored(link.STORE_KEY);
  window.location.assign("/clock");
}

async function copyCustom() {
  const href = `${window.location.origin}${link.clockHref(link.buildQuery(state.customRaw || {}, ZONES))}`;
  customStatus(await copyText(href) ? t("clock.custom_copied") : t("clock.custom_copy_failed", { link: href }));
}

function removeStored(key) {
  try { window.localStorage.removeItem(key); } catch (error) { /* privates Fenster */ }
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
  toneTick(trueMs());
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
    // Serverzeit zum selben performance.now() übergeben (Versatz 0): Der Ton folgt dem Anker, nicht Date.now().
    const perf = performance.now();
    const clock = kit.audioClock(ctx, perf, trueMs(perf), 0);
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

// --- Countdown, Count-up, Timer (Studiouhr A5) -------------------------------------------------
const CD_ICONS = { none: "▷", warn: "△", alert: "▲", final: "■", over: "+", done: "■", watch: "◷", paused: "‖" };

/** Gibt es gerade etwas zu zählen? ?until= und ?timer= immer, die Stoppuhr erst nach dem ersten Start. */
function countdownActive() {
  return COUNT_MODE !== "watch" || state.timer !== null;
}
function countdownMain() {
  return params.cd === "main" && countdownActive();
}

/** Zeitzone für ?until=: die des Servers (zone aus /api/v1/time); fehlt sie, die des Browsers; undefined: noch offen. */
function countZone() {
  return cd.untilZone(state.status, { failed: Boolean(state.error), waitedMs: performance.now(), anchored: Boolean(state.anchor) });
}
function browserZone() {
  try { return new Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (error) { return null; }
}

/** Beschriftung ohne ?label=: „bis 20:15“ (ISO: „bis 2026-12-31 23:59“), mit Zone, wenn sie von der des Browsers abweicht. */
function untilLabel(zone) {
  const u = params.until;
  const clock = `${pad(u.h)}:${pad(u.m)}${u.s ? `:${pad(u.s)}` : ""}`;
  const time = u.kind === "iso" ? `${u.y}-${pad(u.mo)}-${pad(u.d)} ${clock}` : clock;
  if (zone && zone !== browserZone()) return t("clock.cd_until_zone", { time, zone: kit.zoneLabel(zone) });
  return t("clock.cd_until", { time });
}

/** Zehntel anhängen (Taste T, nur lokale Timer): „−00:04,3“ bzw. „+00:00:01,2“ – abgerundet auf der echten Restzeit. */
function withTenths(view, remainingMs) {
  const decimal = language() === "en" ? "." : ",";
  const ms = Math.abs(remainingMs);
  if (view.phase === "before") {
    return `${cd.MINUS}${cd.fmtSpan(Math.floor(ms / 1000), { dayUnit: t("clock.cd_day") })}${decimal}${Math.floor((ms % 1000) / 100)}`;
  }
  if (view.phase === "over") {
    return `+${cd.fmtSpan(Math.floor(ms / 1000), { hours: true, dayUnit: t("clock.cd_day") })}${decimal}${Math.floor((ms % 1000) / 100)}`;
  }
  return view.text;
}

function levelText(view) {
  if (["warn", "alert", "final"].includes(view.level)) return t("clock.cd_below", { limit: cd.fmtLimit(view.limit) });
  if (view.level === "over") return t("clock.cd_over");
  if (view.level === "done") return t("clock.cd_done");
  return "";
}

/**
 * Countdown-Zeile zeichnen (aus tick je Sekunde, bei laufendem lokalen Timer zusätzlich zu dessen eigenen Wechseln).
 * nowMs: angezeigte Serverzeit (mit ?lead=). Alles nur per textContent, Klassen und data-Attributen.
 * Liefert die Restzeit (ms) bis zum Ziel, solange es näher rückt (?until=, laufender Timer), sonst NaN – für den
 * E-Ink-Takt.
 */
function renderCountdown(nowMs = serverMs()) {
  const node = $("cd");
  const active = countdownActive();
  setHidden(node, !active);
  if (active) setAttr(root, "data-cd", params.cd);
  else root.removeAttribute("data-cd");
  if (!active) return NaN;
  const opts = { after: params.after, warn: params.warn, dayUnit: t("clock.cd_day"), coarse: params.eink };
  const tenths = state.tenths && !params.eink;
  let view;
  let label;
  let status = "";
  let toneTarget = NaN;
  let remaining = NaN;
  if (COUNT_MODE === "until") {
    const zone = countZone();
    // Andere Zone als bisher (erste Antwort des Servers): Restzeit springt – das ist kein erlebter Übergang, also
    // weder eine Schwelle ansagen noch Töne aus der alten Planung behalten.
    if (zone !== state.cdZone) {
      state.cdZone = zone;
      state.cdPrev = NaN;
      stopCountdownTones();
    }
    if (zone === undefined) {
      view = cd.countdownView(NaN, opts);   // „--:--“ ohne Stufe, bis die Zone des Servers bekannt ist
      label = params.label || untilLabel(null);
    } else {
      const target = cd.untilTarget(params.until, nowMs, zone);
      remaining = target - nowMs;
      view = cd.countdownView(remaining, opts);
      label = params.label || untilLabel(zone);
      toneTarget = target;   // absolute Serverzeit: der Ton fällt auf das Ziel, die Anzeige läuft um ?lead= vor
    }
  } else {
    const perf = performance.now();
    const read = cd.timerRead(state.timer, perf);
    if (read.remaining === null) {
      view = { phase: "watch", level: "none", seconds: NaN,
        text: cd.stopwatchText(read.elapsed, { tenths, decimal: language() === "en" ? "." : ",", dayUnit: opts.dayUnit }) };
      label = params.label || t("clock.cd_stopwatch");
    } else {
      view = cd.countdownView(read.remaining, opts);
      if (tenths) view = { ...view, text: withTenths(view, read.remaining) };
      label = params.label || t("clock.cd_timer", { time: cd.fmtSpan(params.timer / 1000) });
      if (read.state === "running") {
        toneTarget = trueMs(perf) + read.remaining;
        remaining = read.remaining;
      }
    }
    // Mit ?lock=1 fehlen Kürzel und Start-Knopf: dann nicht „Leertaste oder Start“ versprechen.
    if (read.state === "idle") status = t(params.lock ? "clock.cd_locked" : "clock.cd_idle");
    else if (read.state === "paused") status = t("clock.cd_paused");
    const button = read.state === "running" ? "clock.cd_stop" : (read.state === "paused" ? "clock.cd_resume" : "clock.cd_start");
    setText($("cd-toggle"), t(button));
    setHidden($("cd-actions"), Boolean(params.lock));
  }
  const paused = state.timer && state.timer.state === "paused";
  setAttr(node, "data-level", view.level);
  setAttr(node, "data-phase", view.phase);
  setText($("cd-icon"), CD_ICONS[paused ? "paused" : (view.phase === "watch" ? "watch" : view.level)] || "");
  setText($("cd-label"), label);
  setText($("cd-time"), view.text);
  setText($("cd-state"), status || levelText(view));
  setText($("cd-now"), params.eink ? hms(new Date(nowMs)).slice(0, 5) : hms(new Date(nowMs)));
  // Screenreader: nur an Schwellen (1 min, 10 s, Ziel), nie jede Sekunde.
  const step = cd.announceStep(state.cdPrev, view.seconds);
  state.cdPrev = view.seconds;
  if (step !== null) say(step === 0 ? t("clock.say_target") : t("clock.say_left", { limit: cd.fmtLimit(step) }));
  if (Number.isFinite(toneTarget)) countdownTones(toneTarget);
  // Neue Breite (−MM:SS → −HH:MM:SS) oder Art: Zeit neu einpassen, damit nichts umbricht.
  const shape = `${params.cd}|${view.phase}|${view.text.length}|${label}|${state.layout}`;
  if (shape !== state.cdShape) {
    state.cdShape = shape;
    fitTime();
  }
  return remaining;
}

/** Audiouhr für ?beep= anlegen bzw. fortsetzen (gesture: bei einer Bedienung). Liefert den Zustand oder null. */
function countdownAudio(gesture) {
  if (!(params.beep > 0) || params.eink) return null;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  if (!state.cdTone) {
    try { state.cdTone = { ctx: new Ctx({ latencyHint: "interactive" }), lastK: Infinity, target: NaN, oscs: [] }; } catch (error) { return null; }
  }
  if (gesture && state.cdTone.ctx.state !== "running") state.cdTone.ctx.resume().catch(() => {});
  return state.cdTone;
}

/** Piep in den letzten ?beep= Sekunden vor dem Ziel (Serverzeit), langer Ton auf dem Ziel. */
function countdownTones(target) {
  const tone = countdownAudio(false);
  if (!tone || tone.ctx.state !== "running") return;
  if (!Number.isFinite(tone.target) || Math.abs(tone.target - target) > 1500) stopCountdownTones();   // neues Ziel
  tone.target = target;
  const perf = performance.now();
  const clock = kit.audioClock(tone.ctx, perf, trueMs(perf), 0);
  for (const planned of cd.planCountdownTones(clock, target, params.beep, { lastK: tone.lastK })) {
    tone.lastK = planned.k;
    if (planned.at > tone.ctx.currentTime + 0.005) {
      const osc = kit.scheduleTone(tone.ctx, planned);
      tone.oscs.push(osc);
      osc.addEventListener("ended", () => { tone.oscs = tone.oscs.filter((item) => item !== osc); });
    }
  }
}

/** Geplante Countdown-Töne verwerfen (Anhalten, Zurücksetzen, neues Ziel): Was schon im Voraus geplant ist, verstummt. */
function stopCountdownTones() {
  if (!state.cdTone) return;
  state.cdTone.oscs = kit.stopTones(state.cdTone.oscs);
  state.cdTone.lastK = Infinity;
  state.cdTone.target = NaN;
}

/** Eigener Takt eines laufenden lokalen Timers: genau zum nächsten Wechsel der Anzeige (Zehntel: alle 100 ms). */
function scheduleTimer() {
  clearTimeout(state.timerTimer);
  if (!state.timer || state.timer.state !== "running" || params.eink) return;
  const read = cd.timerRead(state.timer, performance.now());
  state.timerTimer = setTimeout(() => { renderCountdown(); scheduleTimer(); }, cd.timerDelay(read, state.tenths ? 100 : 1000));
}

/** Leertaste/Start: lokalen Timer starten oder anhalten; ohne Ziel startet die Stoppuhr. ?until= lässt sich nicht anhalten. */
function toggleTimer() {
  if (COUNT_MODE === "until") { hint(t("clock.hint_no_timer")); return; }
  if (!state.timer) state.timer = cd.timerNew(null);
  state.timer = cd.timerToggle(state.timer, performance.now());
  stopCountdownTones();
  state.cdPrev = NaN;
  renderCountdown();
  scheduleTimer();
  einkRetick();
}

/** R: zurücksetzen; die Stoppuhr verschwindet dann wieder. */
function resetTimer() {
  if (COUNT_MODE === "until") { hint(t("clock.hint_no_timer")); return; }
  state.timer = COUNT_MODE === "timer" ? cd.timerReset(state.timer) : null;
  state.cdPrev = NaN;
  stopCountdownTones();
  clearTimeout(state.timerTimer);
  renderCountdown();
  fitTime();
  einkRetick();
}

/** E-Ink hat keinen eigenen Timer-Takt: nach Start/Anhalten/Zurücksetzen den Minutentakt neu auf den Timer ausrichten. */
function einkRetick() {
  if (!params.eink) return;
  clearTimeout(state.tickTimer);
  tick();
}

// --- Tastenkürzel, Hinweis, Ansage ------------------------------------------------------------
/** Kurzer sichtbarer Hinweis nach einem Kürzel (2 s, role=status). */
function hint(text) {
  const node = $("clock-hint");
  setText(node, text);
  node.hidden = false;
  clearTimeout(state.hintTimer);
  state.hintTimer = setTimeout(() => { node.hidden = true; }, HINT_MS);
}

/** Text einmal über die Live-Region ansagen (Screenreader; keine Sprachausgabe des Browsers). */
function say(text) {
  const node = $("clock-live");
  node.textContent = "";
  setTimeout(() => { node.textContent = text; }, 60);
}

/** Übersicht der Kürzel öffnen/schließen. Beim Schließen kehrt der Fokus dorthin zurück, wo er vorher war. */
function showKeys(open) {
  const node = $("keys");
  const show = open === undefined ? node.hidden : open;
  if (show === !node.hidden) { wake(); return; }
  if (show) {
    const before = document.activeElement;
    state.keysReturn = before instanceof HTMLElement && before !== document.body && !node.contains(before) ? before : null;
  }
  node.hidden = !show;
  if (show) $("keys-close").focus();
  else {
    const back = state.keysReturn && state.keysReturn.isConnected ? state.keysReturn : $("clock-main");
    state.keysReturn = null;
    back.focus({ preventScroll: true });
  }
  wake();
}

/** Tab bleibt in der offenen Übersicht (aria-modal): vom letzten zum ersten Element und umgekehrt. */
function trapKeys(event) {
  if (event.key !== "Tab") return;
  const node = $("keys");
  const items = [...node.querySelectorAll("button, [href], [tabindex]:not([tabindex='-1'])")].filter((el) => !el.disabled);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (event.shiftKey ? (active === first || !node.contains(active)) : (active === last || !node.contains(active))) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  }
}

function nextDesign() {
  const list = kit.DESIGNS;
  setDesign(list[(list.indexOf(state.design) + 1) % list.length], true);
  hint(t("clock.hint_design", { name: t(`clock.design.${state.design}`) }));
}

function nextLayout() {
  const list = kit.LAYOUTS;
  params.layout = list[(list.indexOf(params.layout) + 1) % list.length];
  root.dataset.layoutMode = params.layout;
  document.body.classList.toggle("is-tile", params.layout === "tile");
  root.style.setProperty("--safe", String(kit.safeMargin(params)));
  const stage = $("clock-stage");
  applyLayout(stage.clientWidth, stage.clientHeight);
  hint(t("clock.hint_layout", { name: t(`clock.layout_name.${params.layout}`) }));
}

function changeScale(delta) {
  params.scale = Math.max(50, Math.min(200, params.scale + delta));
  root.style.setProperty("--clock-scale", String(params.scale / 100));
  fitTime();
  hint(t("clock.hint_scale", { value: params.scale }));
}

function toggleUtc() {
  state.utcBig = !state.utcBig;
  state.minuteKey = "";
  if (state.face) state.face.key = "";
  if (state.face && state.face.text) state.face.text.dataset.key = "";
  render(new Date(serverMs()));
  hint(t(state.utcBig ? "clock.hint_utc" : "clock.hint_local"));
}

function toggleTenths() {
  state.tenths = !state.tenths;
  renderCountdown();
  scheduleTimer();
  hint(t(state.tenths ? "clock.hint_tenths_on" : "clock.hint_tenths_off"));
}

function announceTime() {
  const now = new Date(serverMs());
  const h = state.utcBig ? now.getUTCHours() : now.getHours();
  const m = state.utcBig ? now.getUTCMinutes() : now.getMinutes();
  say(state.utcBig ? `UTC ${pad(h)}:${pad(m)}` : t("clock.say_time", { time: `${pad(h)}:${pad(m)}` }));
}

/** Tastenkürzel ohne Strg/Alt/Cmd; nicht in Eingabefeldern, mit ?lock=1 gar nicht. */
function onKey(event) {
  if (!state.ready || params.lock || event.ctrlKey || event.altKey || event.metaKey || event.repeat) return;
  const target = event.target instanceof Element ? event.target : null;
  if (target && target.closest("select, input, textarea")) return;
  const key = event.key;
  if (key === "Escape") {
    if (!$("keys").hidden) showKeys(false);
    return;
  }
  if (key === " " || key === "Spacebar") {
    if (target && target.closest("button, a")) return;   // dort löst die Leertaste den Knopf aus
    event.preventDefault();
    toggleTimer();
    return;
  }
  const actions = {
    f: toggleFullscreen, d: nextDesign, l: nextLayout, u: toggleUtc, t: toggleTenths, r: resetTimer, a: announceTime,
    "+": () => changeScale(10), "-": () => changeScale(-10), "−": () => changeScale(-10), "?": () => showKeys(),
  };
  const action = actions[key.length === 1 ? key.toLowerCase() : key];
  if (action) {
    event.preventDefault();
    action();
  }
}

// --- Darstellung: hell/dunkel, Rotlicht, E-Ink, Kiosk, Vollbild ------------------------------
function applyModes() {
  const red = store("ntp-gui-clock-red") === "1";
  // Ein Thema (?look=) bringt sein eigenes Hell/Dunkel mit, ?bg=black ist immer dunkel; Rotlicht und E-Ink übersteuern.
  const scheme = kit.colorScheme({ eink: params.eink, look: params.look, bg: params.bg, stored: store("ntp-gui-clock-theme") });
  root.dataset.theme = scheme.scheme;
  if (params.eink) root.dataset.mode = "eink";
  else if (red) root.dataset.mode = "red";
  else delete root.dataset.mode;
  // Beschriftung = Aktion („Dunkel“ im hellen Modus), daher kein aria-pressed: „Dunkel, gedrückt“ wäre falsch.
  $("mode-theme").textContent = scheme.scheme === "light" ? t("clock.theme_dark") : t("clock.theme_light");
  $("mode-red").setAttribute("aria-pressed", red ? "true" : "false");
  $("mode-theme").disabled = red || scheme.locked;
  $("mode-red").disabled = params.eink;
  applyColors();
}

/**
 * Akzent- (?accent=) und Ziffernfarbe (?color=, Design studio) per CSSOM – kein style-Attribut im Markup, daher
 * unter der strengen CSP erlaubt. Reicht der Kontrast zum Hintergrund nicht (≥ 4,5:1), gilt die nächste Stufe, die
 * trägt (kit.ensureContrast). Rotlicht und E-Ink haben feste Farben: dann nichts setzen.
 */
function applyColors() {
  const style = root.style;
  if (root.dataset.mode) {
    style.removeProperty("--accent");
    style.removeProperty("--studio-ink");
    return;
  }
  const bg = kit.colorBackground({ look: params.look, bg: params.bg, theme: root.dataset.theme });
  const accent = params.accent ? kit.ensureContrast(kit.colorValue(params.accent), bg) : null;
  if (accent) style.setProperty("--accent", accent.hex);
  else style.removeProperty("--accent");
  const ink = kit.ensureContrast(kit.PALETTE[params.color] || kit.PALETTE.amber, bg);
  if (ink) style.setProperty("--studio-ink", ink.hex);
}

// --- Layout-Engine: Bühne, Sicherheitsrand, Größe, Pixel-Shift ---------------------------------------
/** Feste Einstellungen aus der Adresse: data-Attribute am Root und CSSOM-Variablen (nur Zahlen aus dem Schema). */
function applyDisplayParams() {
  const style = root.style;
  style.setProperty("--safe", String(kit.safeMargin(params)));
  style.setProperty("--clock-scale", String(params.scale / 100));
  style.setProperty("--fit", "1");
  if (params.show) root.dataset.show = params.show.join(" ");
  if (params.weight) root.dataset.weight = params.weight;
  if (params.bg) root.dataset.bg = params.bg;
  if (params.look) root.dataset.look = params.look;
  if (params.face !== "sans") root.dataset.face = params.face;
  if (params.date === "off") root.dataset.date = "off";
  if (params.colon === "blink" && !params.eink) root.dataset.colon = "on";
  root.dataset.layoutMode = params.layout;
  // Multiviewer-Kachel ausdrücklich gewählt: ohne Kopfzeile, Band und Mauszeiger (bei automatischer Kachel bleiben
  // sie, sonst wüchse die Bühne und das Layout spränge zurück).
  document.body.classList.toggle("is-tile", params.layout === "tile");
}

/**
 * data-layout der Bühne aus ihrer Größe (oder ?layout=), danach die Zeitbreite anpassen. Wählt die Automatik den
 * Streifen, fallen Kopfzeile und Band weg (body.is-compact, kit.chromeLayout); entschieden wird dann mit der Höhe,
 * die die Bühne mit beiden hätte, damit das Layout nicht hin- und herspringt.
 */
function applyLayout(width, height) {
  state.stage = { width, height };
  const stage = $("clock-stage");
  const body = document.body;
  const compact = body.classList.contains("is-compact");
  const pick = kit.chromeLayout(params.layout, width, height, compact ? state.chrome : 0);
  const wantCompact = pick.compact && !body.classList.contains("has-panel");
  if (wantCompact !== compact) {
    if (wantCompact) state.chrome = Math.max(0, document.documentElement.clientHeight - height);
    body.classList.toggle("is-compact", wantCompact);   // der ResizeObserver meldet danach die neue Bühnengröße
  }
  const layout = pick.layout;
  state.layout = layout;
  setAttr(stage, "data-layout", layout);
  if (kit.stackedTime(layout, width, height)) setAttr(stage, "data-stack", "1");
  else stage.removeAttribute("data-stack");
  fitTime();
}

function observeStage() {
  const stage = $("clock-stage");
  const measure = () => applyLayout(stage.clientWidth, stage.clientHeight);
  if (typeof window.ResizeObserver === "function") {
    new window.ResizeObserver((entries) => {
      const box = entries[entries.length - 1].contentRect;
      applyLayout(box.width, box.height);
    }).observe(stage);
  } else {
    window.addEventListener("resize", measure);
  }
  measure();
}

/** Was eingepasst wird: der Countdown als Hauptanzeige (?cd=main), sonst die Textzeit oder das Zifferblatt. */
function fitNode() {
  if (countdownMain()) return $("cd");
  return textTime() ? $("local-time") : $("face");
}

/** Größe der sichtbaren Zeit (Text oder Zifferblatt) ohne Rand: Vereinigung der Kinder-Rechtecke. */
function timeBox() {
  const node = fitNode();
  if (!node || node.hidden) return null;
  const parts = node.id === "local-time" ? [node] : [...node.children];
  let left = Infinity; let right = -Infinity; let top = Infinity; let bottom = -Infinity;
  for (const part of parts) {
    const box = part.getBoundingClientRect();
    if (!box.width && !box.height) continue;
    left = Math.min(left, box.left); right = Math.max(right, box.right);
    top = Math.min(top, box.top); bottom = Math.max(bottom, box.bottom);
  }
  return Number.isFinite(left) ? { width: right - left, height: bottom - top } : null;
}

/**
 * Auto-Anpassung: Die Zeit muss ohne Umbruch in den sicheren Bereich passen. --fit = 1 setzen, messen, dann so weit
 * verkleinern, dass Breite und Höhe mit 4 % Luft (Pixel-Shift) in main passen – mehrmals, bis es passt
 * (kit.fitConverge). Bei Größen-, Layout- und Designwechsel und einmal je Minute (Stundenbreite ohne führende Null).
 * Im Banner bekommt die Spalte mit Datum, UTC und Zustand vorher ihre natürliche Breite (höchstens 45 %, CSS), die
 * Zeit nur den Rest – sonst drückte eine große Zeit (?scale=200) die Spalte auf wenige Pixel zusammen.
 */
function fitTime() {
  const main = $("clock-main");
  if (!main || !state.face) return;
  if (state.layout === "banner") root.style.setProperty("--info-w", `${infoWidth()}px`);
  const factor = kit.fitConverge((fit) => {
    root.style.setProperty("--fit", String(fit));
    const box = timeBox();
    return box ? { needed: box, available: { width: timeWidth(main) * 0.96, height: main.clientHeight * 0.96 - restHeight(main) } }
      : null;
  });
  root.style.setProperty("--fit", String(factor));
}

/** Natürliche Breite der Infospalte im Banner: mit kleinster Zeit messen, dann hat die Spalte Platz für ihren Inhalt. */
function infoWidth() {
  root.style.setProperty("--fit", "0.1");
  let width = 0;
  for (const node of document.querySelectorAll("#clock-main > .clock-date, #clock-main > .clock-sub, :root[data-cd=below] #clock-main > .clock-cd")) {
    width = Math.max(width, node.getBoundingClientRect().width);
  }
  return Math.ceil(width);
}

/**
 * Höhe der übrigen Zeilen in main (Beschriftung, Datum, Zeile mit UTC und Zustand), wenn sie untereinander stehen
 * (normal, column): Die Zeit bekommt nur den Rest, sonst schöbe ein großes Zifferblatt (?scale=200) sie aus dem Bild.
 */
function restHeight(main) {
  const box = window.getComputedStyle(main);
  if (box.display !== "flex" || box.flexDirection !== "column") return 0;
  const time = fitNode();
  let rest = 0;
  let items = 0;
  for (const node of main.children) {
    if (node.hidden) continue;
    const style = window.getComputedStyle(node);
    if (style.display === "none" || style.position === "absolute") continue;
    items += 1;
    if (node === time) continue;
    rest += node.getBoundingClientRect().height + (parseFloat(style.marginTop) || 0) + (parseFloat(style.marginBottom) || 0);
  }
  return rest + Math.max(0, items - 1) * (parseFloat(box.rowGap) || 0);   // Abstand zwischen den Zeilen (gap aus app.css)
}

/**
 * Breite für die Zeit: main, im Banner ohne die Infospalte und den Spaltenabstand (aufgelöste Grid-Spalten), im Streifen
 * ohne die übrigen Teile der Zeile (Countdown, Zustandssymbol) samt Abständen.
 */
function timeWidth(main) {
  if (state.layout === "strip") {
    const time = fitNode();
    const style = window.getComputedStyle(main);
    let rest = 0;
    let items = 0;
    for (const node of main.children) {
      const box = node.getBoundingClientRect();
      if (node.hidden || (!box.width && !box.height) || window.getComputedStyle(node).position === "absolute") continue;
      items += 1;
      if (node !== time) rest += box.width;
    }
    return Math.max(0, main.clientWidth - rest - Math.max(0, items - 1) * (parseFloat(style.columnGap) || 0));
  }
  if (state.layout !== "banner") return main.clientWidth;
  const style = window.getComputedStyle(main);
  const columns = style.gridTemplateColumns.split(" ").map(parseFloat);
  const info = columns.length > 1 && Number.isFinite(columns[1]) ? columns[1] : 0;
  const gap = parseFloat(style.columnGap) || 0;
  return Math.max(0, main.clientWidth - info - (info ? gap : 0));
}

/** Pixel-Shift gegen Einbrennen: alle 2 min eine der Klassen shift-0 … shift-7 an main (Stufe über data-shift). */
function renderShift(nowMs) {
  const level = kit.shiftLevel(params, state.design);
  setAttr(root, "data-shift", String(level));
  const index = level ? kit.shiftIndex(nowMs) : -1;
  if (index === state.shift) return;
  const main = $("clock-main");
  if (state.shift >= 0) main.classList.remove(`shift-${state.shift}`);
  if (index >= 0) main.classList.add(`shift-${index}`);
  state.shift = index;
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
document.addEventListener("keydown", onKey);
$("design").addEventListener("change", (event) => setDesign(event.target.value, true));
$("mode-tone").addEventListener("click", () => {
  togglePanel("mode-tone", "tone-panel");
});
$("mode-device").addEventListener("click", () => {
  if (togglePanel("mode-device", "device-panel")) renderDevice();
});
$("mode-custom").addEventListener("click", openCustom);
$("custom-apply").addEventListener("click", applyCustom);
$("custom-copy").addEventListener("click", copyCustom);
$("custom-reset").addEventListener("click", resetCustom);
$("tone-seconds").addEventListener("click", () => startTone("seconds"));
$("tone-countdown").addEventListener("click", () => startTone("countdown"));
$("tone-off").addEventListener("click", stopTone);
$("cd-toggle").addEventListener("click", () => toggleTimer());
$("cd-reset").addEventListener("click", () => resetTimer());
$("keys-close").addEventListener("click", () => showKeys(false));
$("keys").addEventListener("keydown", trapKeys);
reducedMotion.addEventListener?.("change", () => restartSweep());

// Leiste ausblenden, wenn sich nichts bewegt (Wandmonitor); Tippen/Bewegen holt sie zurück.
let idleTimer = null;
function mayHide() {
  // Offene Panels bleiben bedienbar: dann nicht ausblenden. Erst beim Ablauf prüfen – wake() läuft bei
  // pointerdown/keydown, also bevor der Klick das Panel öffnet. Liegt der Tastaturfokus in der Leiste, bleibt
  // sie ebenfalls sichtbar (nach einem Mausklick nicht, sonst bliebe sie am Wandmonitor für immer stehen).
  if (!$("tone-panel").hidden || !$("device-panel").hidden || !$("custom-panel").hidden || !$("keys").hidden) return false;
  const focus = document.activeElement;
  return !(focus && focus.closest(".clock-bar") && focus.matches(":focus-visible"));
}
function wake() {
  document.body.classList.remove("is-idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { if (mayHide()) document.body.classList.add("is-idle"); }, IDLE_MS);
}
for (const type of ["pointermove", "pointerdown", "keydown", "focusin"]) document.addEventListener(type, wake, { passive: true });
// ?beep=: Browser spielen Töne erst nach einer Bedienung – bei der ersten Berührung oder Taste die Audiouhr starten.
for (const type of ["pointerdown", "keydown"]) document.addEventListener(type, () => countdownAudio(true), { passive: true });

function relabel() {
  applyModes();
  if (params.lock) $("mode-full").title = t("clock.full_title_locked");
  for (const button of document.querySelectorAll(".clock-panel button.info")) button.relabel?.();
  if (state.face) state.face.key = "";
  if (state.face && state.face.text) state.face.text.dataset.key = "";
  state.minuteKey = "";
  render(new Date(serverMs()));
  state.syncKey = "";
  renderSync();
  renderBand();
  renderDevice();
  state.cdShape = "";
  renderCountdown();
  renderProfileTitle();
}

// --- Start ------------------------------------------------------------------------------
/** Profil (?p=) laden und über die Startwerte legen: Profil < Adresse. Ohne Profil sofort. */
async function loadProfile() {
  if (!PROFILE) return;
  const profile = await fetchProfile();
  if (!profile) { if (state.profileError !== "missing") noteProfileFailure(); return; }
  state.profile = profile;
  state.profileKey = profileKey(profile);
  state.profileRev = typeof profile.profiles_rev === "string" ? profile.profiles_rev : null;
  Object.assign(params, kit.parseParams(link.effectiveQuery({ search: window.location.search, profile: profile.params,
    zones: ZONES }), ZONES));
}

async function start() {
  const i18nReady = initI18n();
  await loadProfile();
  initCountMode();
  if (params.kiosk) document.body.classList.add("is-kiosk");
  if (params.eink) document.body.classList.add("is-eink");
  if (params.eink) $("mode-tone").hidden = true;   // E-Ink rechnet nur einmal je Minute
  if (params.lock) document.body.classList.add("is-locked");
  $("mode-custom").hidden = Boolean(params.lock);   // lock=1: keine lokale Bedienung, auch kein Anpassen
  // lock=1 schaltet die Tasten ab: Der Vollbild-Knopf verspricht dann keine Taste F (Titel auch in relabel()).
  if (params.lock) $("mode-full").dataset.i18nTitle = "clock.full_title_locked";
  if (params.tz) {
    $("tz2").hidden = false;
    $("tz2-label").textContent = kit.zoneLabel(params.tz);
  }
  $("tone-info").append(infoButton("clock.tone_info_title", "clock.tone_info"));
  $("device-info").append(infoButton("clock.device_info_title", "clock.device_info"));
  applyDisplayParams();
  applyModes();
  setDesign(params.design || store(DESIGN_KEY), false);
  observeStage();
  wake();
  countdownAudio(false);
  tick();
  measureFrame();
  keepAwake();
  burst();
  setInterval(burst, RESYNC_MS);
  setInterval(poll, POLL_MS);
  state.ready = true;
  i18nReady.then(relabel, () => {});
}
start();
