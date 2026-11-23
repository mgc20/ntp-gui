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
