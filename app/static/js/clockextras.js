// Spielereien der Studiouhr (Etappe C): reine Funktionen, kein DOM, keine Zeitgeber – geprüft mit Node
// (tests/test_uhr_spielereien.py). clock.js baut daraus die Bedienung.
//
// C1: Eieruhr (Dauer wählen, „+1 min“), Pomodoro (Arbeit und Pause im Wechsel, Zähler), eingebaute Countdowns
// (?goal=), eigene Countdowns (bis zu fünf im localStorage dieses Browsers), Nachtmodus (?dim=22-6, manuell per Knopf
// oder Taste N) und die Regel, wann Bedienelemente überhaupt erscheinen (funControls).
//
// Alles läuft im Browser: Timer-Stände, eigene Countdowns und der manuelle Nachtmodus werden nicht gesendet. Gerechnet
// wird wie beim Countdown (clockcount.js) – lokale Timer auf performance.now(), Ziele auf der korrigierten Serverzeit.
import * as kit from "./clockkit.js";
import * as cd from "./clockcount.js";

const MIN = 60_000;

// --- Bedienelemente: wann es sie gibt --------------------------------------------------------------------------------
/**
 * Welche Bedienung zeigt die Uhr? actions: Start/Anhalten/Zurücksetzen/+1 min am Countdown, fun: Knöpfe „Timer“ und
 * „Nacht“ samt Panel und Taste N. Nie mit lock=1, in der Multiviewer-Kachel (layout=tile) und in einer OBS-Browserquelle
 * (obs); die Spielereien zusätzlich nicht mit fun=0 (Voreinstellungen studio, tile, banner), im Kiosk und auf E-Ink.
 */
export function funControls({ fun = true, kiosk = false, lock = false, layout = "auto", obs = false, eink = false } = {}) {
  const actions = !lock && !obs && layout !== "tile";
  return { actions, fun: actions && fun === true && !kiosk && !eink };
}

// --- Eieruhr ---------------------------------------------------------------------------------------------------------
/** Schnellwahl der Eieruhr in Minuten. */
export const EGG_PRESETS = Object.freeze([1, 3, 5, 10, 15, 30]);
/** „+1 min“ */
export const EGG_PLUS_MS = MIN;
/** So viele kurze Töne vor dem Ende, wenn „Ton am Ende“ an ist (dazu ein langer auf dem Ende). */
export const END_BEEPS = 3;
const EGG_CLOCK = /^([0-9]{1,2}):([0-5][0-9])(?::([0-5][0-9]))?$/;
const EGG_MINUTES = /^[0-9]{1,4}$/;

/**
 * Eingabe „Eigene Dauer“ → ms: „7“ (Minuten), „7:30“ (Minuten:Sekunden), „1:05:00“ (Stunden:Minuten:Sekunden) oder wie
 * ?timer= („90s“, „25m“, „1h30m“). Leerzeichen am Rand zählen nicht. 0, über 24 h oder unlesbar: null.
 */
export function parseEggInput(text) {
  if (typeof text !== "string" || text.length > 16) return null;
  const value = text.trim();
  let ms = null;
  if (EGG_MINUTES.test(value)) ms = Number(value) * MIN;
  else {
    const clock = EGG_CLOCK.exec(value);
    if (clock) {
      ms = clock[3] === undefined ? (Number(clock[1]) * 60 + Number(clock[2])) * 1000
        : ((Number(clock[1]) * 60 + Number(clock[2])) * 60 + Number(clock[3])) * 1000;
    } else return kit.parseDuration(value);
  }
  return ms > 0 && ms <= kit.MAX_TIMER_MS ? ms : null;
}

/**
 * „+1 min“ für eine laufende oder angehaltene Eieruhr: Vor dem Ende kommt die Zeit dazu, nach dem Ende (Überzeit) läuft
 * sie von jetzt an noch add ms. Höchstens bis kit.MAX_TIMER_MS Restzeit. Stoppuhr (ohne Dauer): unverändert.
 */
export function timerAdd(timer, add, now) {
  if (!timer || timer.duration === null || !Number.isFinite(now) || !(add > 0)) return timer;
  const read = cd.timerRead(timer, now);
  const rest = Math.min(Math.max(read.remaining, 0) + add, kit.MAX_TIMER_MS);
  return Object.freeze({ ...timer, duration: read.elapsed + rest });
}

/** Ist die Eieruhr abgelaufen (Restzeit ≤ 0)? Die Stoppuhr nie. */
export function timerEnded(read) {
  return Boolean(read) && read.remaining !== null && read.remaining <= 0;
}

// --- Pomodoro --------------------------------------------------------------------------------------------------------
export const POMO_WORK_MS = 25 * MIN;
export const POMO_BREAK_MS = 5 * MIN;
/** Jede vierte Pause ist lang: dreimal so lang wie die kurze, höchstens 30 min – aber nie kürzer als die kurze Pause. */
export const POMO_LONG_EVERY = 4;
export const POMO_LONG_MAX_MS = 30 * MIN;

/** Neuer Pomodoro: Arbeitsphase work, Pause brk (ms; ohne Angabe 25 bzw. 5 min). Beginnt mit Arbeit, Runde 1. */
export function pomoNew(work = null, brk = null) {
  const w = Number.isFinite(work) && work > 0 ? Math.min(work, kit.MAX_TIMER_MS) : POMO_WORK_MS;
  const b = Number.isFinite(brk) && brk > 0 ? Math.min(brk, kit.MAX_TIMER_MS) : POMO_BREAK_MS;
  return Object.freeze({ work: w, brk: b, long: Math.max(b, Math.min(3 * b, POMO_LONG_MAX_MS)), phase: "work", round: 1,
    done: 0 });
}

/** Dauer der aktuellen Phase (ms). */
export function pomoPhaseMs(pomo) {
  if (!pomo) return null;
  return pomo.phase === "work" ? pomo.work : (pomo.phase === "long" ? pomo.long : pomo.brk);
}

/** Nächste Phase: nach der Arbeit eine Pause (jede vierte lang), nach der Pause die nächste Runde Arbeit. */
export function pomoNext(pomo) {
  if (pomo.phase === "work") {
    const done = pomo.done + 1;
    return Object.freeze({ ...pomo, done, phase: done % POMO_LONG_EVERY === 0 ? "long" : "break" });
  }
  return Object.freeze({ ...pomo, phase: "work", round: pomo.round + 1 });
}

/**
 * Laufenden Pomodoro fortschreiben: Ist die Phase um, beginnt die nächste genau an deren Ende (nicht erst jetzt) und
 * läuft weiter – auch über mehrere Phasen, wenn der Tab lange im Hintergrund war. Angehalten oder vor dem Ende:
 * unverändert. { pomo, timer, steps } (steps: so viele Phasen sind gerade zu Ende gegangen).
 */
export function pomoAdvance(pomo, timer, now) {
  let p = pomo;
  let t = timer;
  let steps = 0;
  while (p && t && t.state === "running" && Number.isFinite(now) && cd.timerRead(t, now).remaining <= 0 && steps < 10_000) {
    const end = t.start + (t.duration - t.acc);
    p = pomoNext(p);
    t = Object.freeze({ duration: pomoPhaseMs(p), state: "running", start: end, acc: 0 });
    steps += 1;
  }
  return { pomo: p, timer: t, steps };
}

/** Pomodoro neu beginnen (Taste R): Runde 1, Arbeit, Zähler 0 – mit denselben Dauern. */
export function pomoReset(pomo) {
  return pomo ? pomoNew(pomo.work, pomo.brk) : null;
}

// --- Eingebaute Countdowns (?goal=) ---------------------------------------------------------------------------------
/** Unixzeit 2 000 000 000 s: 18.05.2033 03:33:20 UTC. */
export const UNIX_2E9_MS = 2_000_000_000_000;
/** Ende der NTP-Ära 0 (2^32 s nach dem 1.1.1900): 07.02.2036 06:28:16 UTC. */
export const NTP_ERA_MS = Date.UTC(2036, 1, 7, 6, 28, 16);
const DAY_MS = 86_400_000;
const DST_HORIZON_DAYS = 400;
const dstCache = new Map();   // Zone → { from, at }: nächste Umstellung ab from (at = NaN: keine in Sicht)

/** Erste volle Sekunde in (lo, hi], an der der Abstand der Zone zu UTC nicht mehr der von lo ist (Halbierung). */
function offsetChange(lo, hi, zone) {
  const before = cd.zoneOffset(lo, zone);
  let a = Math.floor(lo / 1000);
  let b = Math.ceil(hi / 1000);
  while (b - a > 1) {
    const mid = Math.floor((a + b) / 2);
    if (cd.zoneOffset(mid * 1000, zone) === before) a = mid;
    else b = mid;
  }
  return b * 1000;
}

/**
 * Nächste Zeitumstellung der Zone nach nowMs (ms, auf die Sekunde), NaN, wenn es in gut einem Jahr keine gibt (Zone ohne
 * Sommerzeit). Gesucht wird in Tagesschritten, dann halbiert; das Ergebnis wird je Zone gemerkt, bis es erreicht ist.
 */
export function nextOffsetChange(nowMs, zone = null) {
  if (!Number.isFinite(nowMs)) return NaN;
  const key = zone || "";
  const hit = dstCache.get(key);
  if (hit && nowMs >= hit.from && (Number.isNaN(hit.at) ? nowMs - hit.from < DAY_MS : nowMs < hit.at)) return hit.at;
  const base = cd.zoneOffset(nowMs, zone);
  let at = NaN;
  for (let day = 1; day <= DST_HORIZON_DAYS; day += 1) {
    const probe = nowMs + day * DAY_MS;
    if (cd.zoneOffset(probe, zone) !== base) { at = offsetChange(probe - DAY_MS, probe, zone); break; }
  }
  if (dstCache.size > 16) dstCache.clear();
  dstCache.set(key, { from: nowMs, at });
  return at;
}

/** Letzte Zeitumstellung der Zone in [nowMs − spanMs, nowMs], sonst NaN. */
export function recentOffsetChange(nowMs, zone = null, spanMs = cd.DAILY_HOLD_MS) {
  if (!Number.isFinite(nowMs)) return NaN;
  const from = nowMs - spanMs;
  return cd.zoneOffset(from, zone) === cd.zoneOffset(nowMs, zone) ? NaN : offsetChange(from, nowMs, zone);
}

/**
 * Zielzeitpunkt (ms) eines eingebauten Countdowns zur Serverzeit nowMs in `zone` (Zone des Servers):
 *   newyear: 1. Januar 00:00 in der Zone – eine Stunde lang (holdMs) bleibt das gerade erreichte Neujahr stehen
 *            (Überzeit „+00:12:00“), danach zählt es auf das nächste;
 *   dst:     nächste Zeitumstellung in der Zone (eine Stunde lang die gerade erfolgte); keine in Sicht: NaN;
 *   unix:    Unixzeit 2 000 000 000; ntp: Ende der NTP-Ära 0 – feste Zeitpunkte, danach Überzeit wie bei ?until=.
 */
export function goalTarget(goal, nowMs, zone = null, holdMs = cd.DAILY_HOLD_MS) {
  if (!Number.isFinite(nowMs)) return NaN;
  if (goal === "unix") return UNIX_2E9_MS;
  if (goal === "ntp") return NTP_ERA_MS;
  if (goal === "newyear") {
    const year = cd.zoneParts(nowMs, zone).y;
    const reached = cd.zonedTime({ y: year, mo: 1, d: 1 }, zone);
    if (nowMs >= reached && nowMs - reached < holdMs) return reached;
    return reached > nowMs ? reached : cd.zonedTime({ y: year + 1, mo: 1, d: 1 }, zone);
  }
  if (goal === "dst") {
    const recent = recentOffsetChange(nowMs, zone, holdMs);
    return Number.isFinite(recent) ? recent : nextOffsetChange(nowMs, zone);
  }
  return NaN;
}

// --- Eigene Countdowns (localStorage, nur dieser Browser) -----------------------------------------------------------
export const OWN_KEY = "ntp-gui-clock-countdowns";
export const OWN_MAX = 5;
const OWN_TEXT_MAX = 2000;
const entry = (name) => kit.PARAM_SCHEMA.find((item) => item.name === name);

/** Einen eigenen Countdown prüfen: Ziel wie ?until=, Beschriftung wie ?label= (Pflicht). Liefert { until, label } oder null. */
export function ownItem(raw) {
  if (!raw || typeof raw !== "object") return null;
  const until = typeof raw.until === "string" ? raw.until.trim() : "";
  const label = typeof raw.label === "string" ? raw.label.trim().normalize("NFC") : "";
  if (!kit.checkParam(entry("until"), until).ok || !kit.checkParam(entry("label"), label).ok) return null;
  return Object.freeze({ until, label });
}

/** Gemerkte Liste lesen (JSON aus dem localStorage): nur gültige Einträge, ohne Doppelte, höchstens OWN_MAX. */
export function ownList(text) {
  if (typeof text !== "string" || !text || text.length > OWN_TEXT_MAX) return [];
  let data;
  try { data = JSON.parse(text); } catch (error) { return []; }
  if (!Array.isArray(data)) return [];
  const out = [];
  for (const raw of data) {
    const item = ownItem(raw);
    if (item && !out.some((x) => x.until === item.until && x.label === item.label)) out.push(item);
    if (out.length >= OWN_MAX) break;
  }
  return out;
}

/** Neuen Countdown vorn einreihen (gleicher schon da: nach vorn). Ungültig: { ok: false, list } unverändert. */
export function ownAdd(list, raw) {
  const item = ownItem(raw);
  const base = Array.isArray(list) ? list : [];
  if (!item) return { ok: false, list: base };
  const rest = base.filter((x) => !(x.until === item.until && x.label === item.label));
  return { ok: true, list: [item, ...rest].slice(0, OWN_MAX) };
}

/** Eintrag index entfernen. */
export function ownRemove(list, index) {
  return (Array.isArray(list) ? list : []).filter((_, i) => i !== index);
}

/** Liste für den localStorage (leer: null – dann wird der Eintrag gelöscht). */
export function ownText(list) {
  return Array.isArray(list) && list.length ? JSON.stringify(list.map(({ until, label }) => ({ until, label }))) : null;
}

// --- Nachtmodus -----------------------------------------------------------------------------------------------------
/**
 * Stunde für den Zeitplan (?dim=): volle Stunde in der Ortszeit dieses Geräts zum Zeitpunkt ms (Serverzeit). Nicht die
 * groß angezeigte Zone – auch mit „UTC groß“ oder im Design tc (Zone des Servers) dimmt die Uhr nach der Uhrzeit des
 * Raums, in dem sie steht. null bei ungültigem ms.
 */
export function nightHour(ms) {
  return Number.isFinite(ms) ? new Date(ms).getHours() : null;
}

/** Liegt die volle Stunde hour im Bereich range ({ from, to } aus ?dim=, über Mitternacht erlaubt)? Ohne Bereich: null. */
export function nightScheduled(range, hour) {
  if (!range || !Number.isInteger(hour)) return null;
  const { from, to } = range;
  return from < to ? hour >= from && hour < to : hour >= from || hour < to;
}

/**
 * Manuelles Umschalten gilt nur bis zum nächsten Wechsel des Zeitplans: Ändert sich scheduled gegenüber prev, fällt
 * override weg (null). Ohne Zeitplan bleibt es.
 */
export function nightOverride({ scheduled = null, prev = null, override = null } = {}) {
  if (scheduled === null || prev === null || scheduled === prev) return override;
  return null;
}

/**
 * Zustand des Nachtmodus: { on, mode ("night" grau gedimmt | "red" Rotlicht gedimmt | null), level (Deckkraft 0,2–0,8) }.
 * override (manuell) geht vor dem Zeitplan; E-Ink kennt keinen Nachtmodus.
 */
export function nightView({ scheduled = null, override = null, red = false, level = 40, eink = false } = {}) {
  const on = !eink && (override === null ? scheduled === true : override === true);
  const pct = Number.isFinite(level) ? Math.min(80, Math.max(20, Math.round(level))) : 40;
  return { on, mode: on ? (red ? "red" : "night") : null, level: pct / 100 };
}

// --- C2: Design binary, Nerd-Zeile, Mondphase, Fortschrittsbalken ----------------------------------------------------
// Alles reine Rechnung im Browser: kein Standort (die Mondphase ist überall auf der Erde gleich, nur ihr Bild steht auf
// der Südhalbkugel gespiegelt – das wählt man von Hand, gemerkt nur in diesem Browser), kein Abruf, keine Tabelle aus dem
// Netz. TAI−UTC kommt vom Server (tai_utc in /api/v1/time, aus leap.py und der leap-seconds.list des Images); ohne den
// Wert zeigt die Nerd-Zeile TAI und GPS nicht an, statt eine Zahl zu raten.

/** Zusätze unter der Uhr, die sich mit ?show= einschalten lassen (Standard aus). */
export const EXTRA_ITEMS = Object.freeze(kit.SHOW_ITEMS.slice(kit.SHOW_ITEMS.indexOf("moon")));

/**
 * ?show= aufteilen: die Grundelemente (Zeit, Datum, …) und die Zusätze (Mond, Nerd-Zeile, Balken). Nennt die Liste nur
 * Zusätze („show=moon“), bleiben die Grundelemente auf Standard (base: null) – so schaltet man einen Zusatz dazu, ohne
 * alle anderen aufzuzählen. show null: { base: null, extras: [] }.
 */
export function splitShow(show) {
  if (!Array.isArray(show)) return { base: null, extras: [] };
  const extras = show.filter((item) => EXTRA_ITEMS.includes(item));
  const base = show.filter((item) => !EXTRA_ITEMS.includes(item));
  return { base: base.length ? base : null, extras };
}

/** Unter dieser Bühnenhöhe (px) fehlen die Zusätze außer im Banner (dort stehen sie neben der Zeit): kein Platz. */
export const EXTRAS_MIN_HEIGHT = 360;

/**
 * Welche Zusätze erscheinen? Nur die mit ?show= gewählten – nie mit fun=0 (Voreinstellungen studio, tile, banner), nie in
 * der Multiviewer-Kachel und im Streifen (layout tile/strip) und auf Bühnen unter EXTRAS_MIN_HEIGHT außer im Banner (dort
 * ist kein Platz), auf E-Ink ohne die Nerd-Zeile (sie zählt Sekunden, E-Ink zeichnet nur einmal je Minute).
 * height: Höhe der Bühne in px (null: unbekannt, zählt nicht).
 */
export function extrasShown({ extras = [], fun = true, layout = "normal", eink = false, height = null } = {}) {
  if (fun !== true || layout === "tile" || layout === "strip" || !Array.isArray(extras)) return [];
  if (layout !== "banner" && Number.isFinite(height) && height > 0 && height < EXTRAS_MIN_HEIGHT) return [];
  return EXTRA_ITEMS.filter((item) => extras.includes(item) && !(eink && item === "nerd"));
}

// --- Design binary ---------------------------------------------------------------------------------------------------
/** Darstellungen der Binäruhr (?bin=): bcd = je Ziffer eine Spalte (8-4-2-1), plain = Stunde, Minute, Sekunde als Dualzahl. */
export const BIN_MODES = Object.freeze([...kit.BIN_MODES]);
const BCD_BITS = [2, 4, 3, 4, 3, 4];   // Zehner der Stunde 0–2, Einer 0–9, Zehner der Minute/Sekunde 0–5, Einer 0–9
const PLAIN_BITS = [5, 6, 6];          // Stunde 0–23, Minute und Sekunde 0–59

function bitsOf(value, count) {
  const out = [];
  for (let i = count - 1; i >= 0; i -= 1) out.push({ weight: 2 ** i, on: Boolean((value >> i) & 1) });
  return out;
}

/**
 * Lämpchen der Binäruhr für h:m:s. Ergebnis: { mode, groups: [{ value, bits: [{ weight, on }] }] } – bcd: sechs (bzw. ohne
 * Sekunden vier) Spalten je Dezimalziffer, Gewichte von oben 8, 4, 2, 1; plain: drei (zwei) Zeilen, Gewichte von links
 * 32 … 1. Ungültige Eingaben: null.
 */
export function binaryLamps(h, m, s, { mode = "bcd", seconds = true } = {}) {
  const ok = (v, max) => Number.isInteger(v) && v >= 0 && v <= max;
  if (!ok(h, 23) || !ok(m, 59) || !ok(s, 59) || !BIN_MODES.includes(mode)) return null;
  const values = seconds ? [h, m, s] : [h, m];
  if (mode === "plain") {
    return { mode, groups: values.map((value, i) => ({ value, bits: bitsOf(value, PLAIN_BITS[i]) })) };
  }
  const digits = values.flatMap((value) => [Math.floor(value / 10), value % 10]);
  return { mode, groups: digits.map((value, i) => ({ value, bits: bitsOf(value, BCD_BITS[i]) })) };
}

// --- Nerd-Zeile ------------------------------------------------------------------------------------------------------
/** GPS-Zeit startet am 6.1.1980 00:00 UTC; damals war TAI−UTC 19 s, seitdem gilt GPS = TAI − 19 s. */
export const GPS_EPOCH_MS = Date.UTC(1980, 0, 6);
export const TAI_GPS_S = 19;
export const WEEK_S = 604_800;
/** Modifiziertes Julianisches Datum des 1.1.1970 00:00 UTC. */
export const MJD_UNIX = 40_587;

/** TAI−UTC aus /api/v1/time prüfen: ganze Sekunden 10 … 100, sonst null (dann keine TAI- und GPS-Angaben). */
export function taiUtc(value) {
  return Number.isInteger(value) && value >= 10 && value <= 100 ? value : null;
}

/** Tag im Jahr (1 … 366) für ein Kalenderdatum. */
export function dayOfYear(y, mo, d) {
  return Math.round((Date.UTC(y, mo - 1, d) - Date.UTC(y, 0, 1)) / 86_400_000) + 1;
}

/**
 * Werte der Nerd-Zeile zum Zeitpunkt ms (UTC-Millisekunden der angezeigten Zeit): Unixzeit (s, ganzzahlig), MJD,
 * und mit TAI−UTC (tai, Sekunden) auch TAI als Uhrzeit sowie GPS-Woche und -Sekunde der Woche. Ohne gültiges tai sind
 * taiMs und gps null. Kein Wert hängt von der Zeitzone ab.
 */
export function nerdValues(ms, tai = null) {
  if (!Number.isFinite(ms)) return null;
  const unix = Math.floor(ms / 1000);
  const offset = taiUtc(tai);
  const out = { unix, mjd: ms / 86_400_000 + MJD_UNIX, taiMs: null, gps: null, gpsUtc: null };
  if (offset === null) return out;
  out.taiMs = ms + offset * 1000;
  out.gpsUtc = offset - TAI_GPS_S;
  const gpsS = Math.floor((ms - GPS_EPOCH_MS) / 1000) + out.gpsUtc;
  if (gpsS >= 0) out.gps = { week: Math.floor(gpsS / WEEK_S), sow: gpsS % WEEK_S };
  return out;
}

/** Uhrzeit HH:MM:SS (UTC-Zählung) eines Zeitpunkts – für TAI. */
export function hmsOf(ms) {
  const sec = ((Math.floor(ms / 1000) % 86_400) + 86_400) % 86_400;
  const two = (n) => String(n).padStart(2, "0");
  return `${two(Math.floor(sec / 3600))}:${two(Math.floor(sec / 60) % 60)}:${two(sec % 60)}`;
}

// --- Mondphase -------------------------------------------------------------------------------------------------------
/** Mittlerer synodischer Monat in Tagen (Neumond bis Neumond). */
export const SYNODIC_DAYS = 29.530589;
const J2000_MS = Date.UTC(2000, 0, 1, 12);
const RAD = Math.PI / 180;
const norm360 = (deg) => ((deg % 360) + 360) % 360;

/**
 * Elongation des Mondes von der Sonne in Grad (0 = Neumond, 90 = erstes Viertel, 180 = Vollmond, 270 = letztes Viertel)
 * – mittlere Bahnen mit den größten Störungsgliedern (Evektion, Variation, jährliche Gleichung …). Genauigkeit etwa
 * 0,3°, also Neu- und Vollmond auf rund eine halbe Stunde; die Anzeige verspricht weniger (±1 Tag im ⓘ).
 */
export function moonElongation(ms) {
  const d = (ms - J2000_MS) / 86_400_000;
  const s = (deg) => Math.sin(deg * RAD);
  const g = 357.528 + 0.9856003 * d;
  const sun = 280.46 + 0.9856474 * d + 1.915 * s(g) + 0.02 * s(2 * g);
  const L = 218.316 + 13.176396 * d;
  const Mm = 134.963 + 13.064993 * d;
  const F = 93.272 + 13.22935 * d;
  const D = 297.85 + 12.190749 * d;
  const Ms = 357.529 + 0.98560028 * d;
  const moon = L + 6.289 * s(Mm) - 1.274 * s(Mm - 2 * D) + 0.658 * s(2 * D) - 0.186 * s(Ms) - 0.059 * s(2 * Mm - 2 * D)
    - 0.057 * s(Mm - 2 * D + Ms) + 0.053 * s(Mm + 2 * D) + 0.046 * s(2 * D - Ms) + 0.041 * s(Mm - Ms) - 0.035 * s(D)
    - 0.031 * s(Mm + Ms) - 0.015 * s(2 * F - 2 * D) + 0.011 * s(Mm - 4 * D);
  return norm360(moon - sun);
}

/** Namen der acht Phasen (i18n clock.moon.<key>), je 45° um 0, 45, 90 … 315°. */
export const MOON_PHASES = Object.freeze(["new", "waxing_crescent", "first_quarter", "waxing_gibbous", "full",
  "waning_gibbous", "last_quarter", "waning_crescent"]);

/**
 * Mondphase zum Zeitpunkt ms: { angle (Elongation, Grad), illum (beleuchteter Anteil 0 … 1), age (Tage seit Neumond,
 * mittlerer Monat), waxing, key (eine der MOON_PHASES) }. Ungültig: null.
 */
export function moonPhase(ms) {
  if (!Number.isFinite(ms)) return null;
  const angle = moonElongation(ms);
  const illum = (1 - Math.cos(angle * RAD)) / 2;
  return { angle, illum, age: (angle / 360) * SYNODIC_DAYS, waxing: angle < 180,
    key: MOON_PHASES[Math.floor(norm360(angle + 22.5) / 45) % 8] };
}

/**
 * Nächster Zeitpunkt (ms) nach ms, an dem die Elongation target Grad erreicht (0 Neumond, 180 Vollmond) – Schritte
 * entlang der mittleren Geschwindigkeit, bis die Abweichung unter einer Minute liegt.
 */
export function nextMoonPhase(ms, target = 180) {
  if (!Number.isFinite(ms)) return NaN;
  const rate = 360 / SYNODIC_DAYS / 86_400_000;   // Grad je ms
  let t = ms + (norm360(target - moonElongation(ms)) || 360) / rate;
  for (let i = 0; i < 8; i += 1) {
    const diff = ((moonElongation(t) - target + 540) % 360) - 180;
    t -= diff / rate;
    if (Math.abs(diff / rate) < 60_000) break;
  }
  return t <= ms ? nextMoonPhase(ms + 86_400_000, target) : t;
}

const r2 = (v) => Math.round(v * 100) / 100;

/**
 * SVG-Pfad der beleuchteten Fläche einer Mondscheibe (Mitte cx/cy, Radius r): rechte bzw. linke Hälfte als Bogen, die
 * Lichtgrenze als Halbellipse mit der Breite r·|cos(angle)|. Auf der Nordhalbkugel nimmt der Mond rechts zu, auf der
 * Südhalbkugel (south) links. Neumond: leerer Pfad. Nur Zahlen, nie Text aus einer Eingabe.
 */
export function moonPath(angle, { cx = 50, cy = 50, r = 50, south = false } = {}) {
  if (!Number.isFinite(angle)) return "";
  const a = norm360(angle);
  const illum = (1 - Math.cos(a * RAD)) / 2;
  if (illum < 0.005) return "";
  const top = `${r2(cx)} ${r2(cy - r)}`;
  const bottom = `${r2(cx)} ${r2(cy + r)}`;
  if (illum > 0.995) return `M ${top} A ${r2(r)} ${r2(r)} 0 1 1 ${bottom} A ${r2(r)} ${r2(r)} 0 1 1 ${top} Z`;
  const right = (a < 180) !== south;   // beleuchtete Seite
  const gibbous = a > 90 && a < 270;
  const rx = r2(r * Math.abs(Math.cos(a * RAD)));
  // Rand: von oben nach unten über die beleuchtete Seite (rechts: Uhrzeigersinn, sweep 1). Lichtgrenze zurück nach oben:
  // beim zunehmenden Sichel nach außen zur hellen Seite gewölbt, beim Dreiviertel zur dunklen.
  const limb = right ? 1 : 0;
  const term = right ? (gibbous ? 1 : 0) : (gibbous ? 0 : 1);
  return `M ${top} A ${r2(r)} ${r2(r)} 0 0 ${limb} ${bottom} A ${rx} ${r2(r)} 0 0 ${term} ${top} Z`;
}

// --- Fortschrittsbalken ----------------------------------------------------------------------------------------------
/** Balken (?bars=): Tag, Woche (ab Montag), Monat, Jahr in der Ortszeit dieses Geräts, timer: Eieruhr bzw. Pomodoro-Phase. */
export const BARS = Object.freeze([...kit.BARS]);

/**
 * Welche Balken? bars aus ?bars= (Liste) oder ohne Angabe: mit laufender Eieruhr bzw. Pomodoro (hasTimer) dessen Balken
 * und der Tag, sonst Tag und Jahr. „timer“ ohne Eieruhr fällt weg.
 */
export function barsFor(bars, hasTimer = false) {
  const list = Array.isArray(bars) && bars.length ? bars : (hasTimer ? ["timer", "day"] : ["day", "year"]);
  return BARS.filter((bar) => list.includes(bar) && (bar !== "timer" || hasTimer));
}

/**
 * Anteil des laufenden Zeitraums kind ("day", "week", "month", "year") zum Zeitpunkt ms in der Ortszeit dieses Geräts:
 * { start, end, fraction (0 … 1) }. Grenzen über Date in Ortszeit – Tage mit Zeitumstellung sind 23 bzw. 25 h lang.
 */
export function periodProgress(kind, ms) {
  if (!Number.isFinite(ms)) return null;
  const now = new Date(ms);
  const y = now.getFullYear();
  const mo = now.getMonth();
  const d = now.getDate();
  let start;
  let end;
  if (kind === "day") { start = new Date(y, mo, d); end = new Date(y, mo, d + 1); }
  else if (kind === "week") {
    const back = (now.getDay() + 6) % 7;   // Montag = 0
    start = new Date(y, mo, d - back); end = new Date(y, mo, d - back + 7);
  } else if (kind === "month") { start = new Date(y, mo, 1); end = new Date(y, mo + 1, 1); }
  else if (kind === "year") { start = new Date(y, 0, 1); end = new Date(y + 1, 0, 1); }
  else return null;
  const span = end.getTime() - start.getTime();
  return { start: start.getTime(), end: end.getTime(), fraction: Math.min(1, Math.max(0, (ms - start.getTime()) / span)) };
}

/** Anteil einer Eieruhr bzw. Pomodoro-Phase zum Zeitpunkt now (performance.now()): verstrichen / Dauer, 0 … 1; Stoppuhr
 *  (ohne Dauer) oder kein Timer: null. */
export function timerProgress(timer, now) {
  if (!timer || !Number.isFinite(timer.duration) || timer.duration <= 0) return null;
  const read = cd.timerRead(timer, now);
  return Math.min(1, Math.max(0, read.elapsed / timer.duration));
}

/** Prozent für die Anzeige: abgerundet (erst bei wirklich vollem Zeitraum 100 %). */
export function percentOf(fraction) {
  return Number.isFinite(fraction) ? Math.min(100, Math.max(0, Math.floor(fraction * 100))) : null;
}
