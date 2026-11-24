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
import { fmtNumber } from "./util.js";

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

/**
 * fun für funControls/eggsAllowed, solange ein Profil (?p=) angefordert, aber (noch) nicht geladen ist: vorsichtshalber
 * aus. fun=0 und kiosk=1 der Voreinstellungen studio, tile und banner stehen nur in der Antwort des Servers – fällt der
 * Abruf aus (503, 401, Netz), zeigte ein Studio-Bildschirm sonst Ostereier, Konfetti und die Knöpfe Timer, Spiel und
 * Nacht. Lädt das Profil später, lädt die Seite neu (retryProfile) und rechnet mit dessen Werten.
 */
export function funWanted({ fun = true, profile = "", loaded = false } = {}) {
  return fun === true && (!profile || loaded === true);
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
/** Jahr-2038-Problem: 2^31 s Unixzeit (Überlauf vorzeichenbehafteter 32-Bit-Zähler), 19.01.2038 03:14:08 UTC. */
export const Y2038_MS = 2 ** 31 * 1000;
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
 *   unix:    Unixzeit 2 000 000 000; ntp: Ende der NTP-Ära 0; y2038: Unixzeit 2^31 (Jahr-2038-Problem) – feste
 *            Zeitpunkte, danach Überzeit wie bei ?until=.
 */
export function goalTarget(goal, nowMs, zone = null, holdMs = cd.DAILY_HOLD_MS) {
  if (!Number.isFinite(nowMs)) return NaN;
  if (goal === "unix") return UNIX_2E9_MS;
  if (goal === "ntp") return NTP_ERA_MS;
  if (goal === "y2038") return Y2038_MS;
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
 * Zusätze („show=moon“), bleiben die Grundelemente, wie sie sonst wären (base: null) – so schaltet man einen Zusatz dazu,
 * ohne alle anderen aufzuzählen. show null: { base: null, extras: [] }.
 */
export function splitShow(show) {
  if (!Array.isArray(show)) return { base: null, extras: [] };
  const extras = show.filter((item) => EXTRA_ITEMS.includes(item));
  const base = show.filter((item) => !EXTRA_ITEMS.includes(item));
  return { base: base.length ? base : null, extras };
}

/**
 * ?show= nach Profil und Adresse (Rangfolge Profil < Adresse): show ist der zusammengeführte Wert, profileShow der des
 * Profils allein. Nennt show nur Zusätze, gilt für die Grundelemente die Auswahl des Profils (etwa night: nur die Zeit) –
 * die Adresse ändert nur, was sie nennt. Ergebnis wie splitShow.
 */
export function mergeShow(show, profileShow = null) {
  const split = splitShow(show);
  if (split.base === null && split.extras.length) return { base: splitShow(profileShow).base, extras: split.extras };
  return split;
}

/** Unter dieser Bühnenhöhe (px) fehlen die Zusätze außer im Banner (dort stehen sie neben der Zeit): kein Platz. */
export const EXTRAS_MIN_HEIGHT = 360;

/**
 * Welche Zusätze erscheinen? Nur die mit ?show= gewählten – nie mit fun=0 (Voreinstellungen studio, tile, banner), nie im
 * Kiosk (wie die Knöpfe der Spielereien, funControls), nie in der Multiviewer-Kachel und im Streifen (layout tile/strip)
 * und auf Bühnen unter EXTRAS_MIN_HEIGHT außer im Banner (dort stehen sie neben der Zeit); im Banner aber nicht, wenn dort
 * schon der Countdown oder die Leiste der Weltzeit steht (crowded) und die Bühne niedriger ist – dann ist kein Platz.
 * Auf E-Ink ohne die Nerd-Zeile (sie zählt Sekunden, E-Ink zeichnet nur einmal je Minute).
 * height: Höhe der Bühne in px (null: unbekannt, zählt nicht).
 */
export function extrasShown({ extras = [], fun = true, kiosk = false, layout = "normal", eink = false, height = null,
  crowded = false } = {}) {
  if (fun !== true || kiosk === true || layout === "tile" || layout === "strip" || !Array.isArray(extras)) return [];
  const low = Number.isFinite(height) && height > 0 && height < EXTRAS_MIN_HEIGHT;
  if (low && (layout !== "banner" || crowded === true)) return [];
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
 * Werte der Nerd-Zeile zum Zeitpunkt ms (UTC-Millisekunden der angezeigten Zeit): Unixzeit (s, ganzzahlig, dazu
 * hexadezimal), MJD,
 * und mit TAI−UTC (tai, Sekunden) auch TAI als Uhrzeit sowie GPS-Woche und -Sekunde der Woche. Ohne gültiges tai sind
 * taiMs und gps null. Kein Wert hängt von der Zeitzone ab.
 */
export function nerdValues(ms, tai = null) {
  if (!Number.isFinite(ms)) return null;
  const unix = Math.floor(ms / 1000);
  const offset = taiUtc(tai);
  const out = { unix, hex: unixHex(unix), mjd: ms / 86_400_000 + MJD_UNIX, taiMs: null, gps: null, gpsUtc: null };
  if (offset === null) return out;
  out.taiMs = ms + offset * 1000;
  out.gpsUtc = offset - TAI_GPS_S;
  const gpsS = Math.floor((ms - GPS_EPOCH_MS) / 1000) + out.gpsUtc;
  if (gpsS >= 0) out.gps = { week: Math.floor(gpsS / WEEK_S), sow: gpsS % WEEK_S };
  return out;
}

/** Unixzeit (s) hexadezimal, Großbuchstaben mit „0x“; negativ oder ungültig: null. */
export function unixHex(unix) {
  return Number.isSafeInteger(unix) && unix >= 0 ? `0x${unix.toString(16).toUpperCase()}` : null;
}

const ROMAN = [[1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"], [90, "XC"], [50, "L"], [40, "XL"], [10, "X"],
  [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];

/** Ganze Zahl 0 … 3999 als römische Zahl; die Null als „N“ (nulla, wie in mittelalterlichen Tafeln). Sonst null. */
export function roman(n) {
  if (!Number.isInteger(n) || n < 0 || n > 3999) return null;
  if (n === 0) return "N";
  let rest = n;
  let out = "";
  for (const [value, sign] of ROMAN) {
    while (rest >= value) { out += sign; rest -= value; }
  }
  return out;
}

/** Stunde und Minute der angezeigten Uhrzeit römisch („XVIII:XLIV“, Mitternacht „N:N“). Ungültig: null. */
export function romanTime(h, m) {
  if (!Number.isInteger(h) || h < 0 || h > 23 || !Number.isInteger(m) || m < 0 || m > 59) return null;
  return `${roman(h)}:${roman(m)}`;
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
/** Balken (?bars=): Tag, Woche (ab Montag), Monat, Jahr im angezeigten Datum (sonst Ortszeit dieses Geräts), timer:
 *  Eieruhr bzw. Pomodoro-Phase. */
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
 * Anteil des laufenden Zeitraums kind ("day", "week", "month", "year") zum Zeitpunkt ms: { start, end, fraction (0 … 1) }.
 * Ohne offset in der Ortszeit dieses Geräts (Grenzen über Date – Tage mit Zeitumstellung sind 23 bzw. 25 h lang); mit
 * offset (ms, fester Abstand einer Zone zu UTC – Design tc mit der Zone des Servers) in dieser Zone, damit die Balken zum
 * angezeigten Datum passen.
 */
export function periodProgress(kind, ms, offset = null) {
  if (!Number.isFinite(ms)) return null;
  const fixed = Number.isFinite(offset);
  const local = fixed ? new Date(ms + offset) : new Date(ms);
  const y = fixed ? local.getUTCFullYear() : local.getFullYear();
  const mo = fixed ? local.getUTCMonth() : local.getMonth();
  const d = fixed ? local.getUTCDate() : local.getDate();
  const wd = fixed ? local.getUTCDay() : local.getDay();
  const at = fixed ? (yy, mm, dd) => Date.UTC(yy, mm, dd) - offset : (yy, mm, dd) => new Date(yy, mm, dd).getTime();
  let start;
  let end;
  if (kind === "day") { start = at(y, mo, d); end = at(y, mo, d + 1); }
  else if (kind === "week") {
    const back = (wd + 6) % 7;   // Montag = 0
    start = at(y, mo, d - back); end = at(y, mo, d - back + 7);
  } else if (kind === "month") { start = at(y, mo, 1); end = at(y, mo + 1, 1); }
  else if (kind === "year") { start = at(y, 0, 1); end = at(y + 1, 0, 1); }
  else return null;
  return { start, end, fraction: Math.min(1, Math.max(0, (ms - start) / (end - start))) };
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

// --- C3: Spiel „Tippe auf :00“, Zeitzeichen, Ostereier -------------------------------------------------------------
// Alles nur im Browser: Der Bestwert des Spiels steht im localStorage (clock.js schreibt mit try/catch), Ostereier und
// Konfetti entstehen aus der angezeigten Zeit bzw. einer Tastenfolge, Zeitzeichen sind WebAudio-Töne nach einem Klick.

/**
 * Gibt es Ostereier (und Konfetti)? Nur wo auch die Spielereien erscheinen (funControls: nicht mit fun=0 – Voreinstellungen
 * studio, tile, banner –, lock=1, im Kiosk, in der Kachel, in OBS und auf E-Ink) und nicht mit eggs=0.
 */
export function eggsAllowed({ eggs = true, fun = true, kiosk = false, lock = false, layout = "auto", obs = false,
  eink = false } = {}) {
  return eggs === true && funControls({ fun, kiosk, lock, layout, obs, eink }).fun;
}

/**
 * Osterei (und Konfetti) in diesem Layout zeigen? Nur mit Erlaubnis (eggsAllowed) und nie in Kachel und Streifen – dort
 * steht nur die Zeit, auch wenn das Layout erst zur Laufzeit (Taste L, flaches Fenster) dazu wird. Auch nie über dem
 * Prüfbild (test: ?test=sync läuft), sonst lägen Zeile und Schnipsel über der Blitzfläche.
 */
export function eggShown({ allowed = false, layout = "normal", test = false } = {}) {
  return allowed === true && !test && layout !== "tile" && layout !== "strip";
}

/** Ziel des Spiels: die volle Sekunde oder die volle Minute (Schrittweite in ms). */
export const TAP_UNITS = Object.freeze({ second: 1000, minute: 60_000 });
/** localStorage: Bestwerte des Spiels je Ziel ({"second": 12.3, "minute": 410}), nur dieser Browser. */
export const TAP_BEST_KEY = "ntp-gui-clock-tap";
/** Stufen der Wertung (Betrag der Abweichung in ms, aufsteigend); darüber „daneben“. */
export const TAP_LEVELS = Object.freeze([["perfect", 10], ["great", 30], ["good", 100], ["ok", 300]]);

/**
 * Zählt ein click am Spielknopf als eigener Tipp? Nur ohne Zeiger dahinter (MouseEvent.detail 0: Screenreader oder
 * Tastatur). Zu Maus und Finger gehört immer ein pointerdown, der schon gewertet hat – auch bei langem Druck.
 */
export function tapFromClick(detail) {
  return detail === 0;
}

/**
 * Abweichung eines Tipps zur nächsten vollen Sekunde bzw. Minute (ms, Serverzeit): negativ zu früh, positiv zu spät.
 * Bereich [−½, +½) Schritt. Unbekanntes Ziel oder keine Zeit: null.
 */
export function tapDeviation(serverMs, unit = "second") {
  const step = TAP_UNITS[unit];
  if (!step || !Number.isFinite(serverMs)) return null;
  const rest = ((serverMs % step) + step) % step;
  return rest < step / 2 ? rest : rest - step;
}

/** Wertung einer Abweichung: perfect | great | good | ok | off. */
export function tapLevel(deviation) {
  if (!Number.isFinite(deviation)) return null;
  const abs = Math.abs(deviation);
  for (const [level, limit] of TAP_LEVELS) if (abs <= limit) return level;
  return "off";
}

/**
 * Wie genau kann das Spiel überhaupt messen? device: halbe Laufzeit der besten Messung (RTT/2), server: Genauigkeit
 * der Serveruhr (accuracy), frame: eine Bildauffrischung (so spät erscheint die neue Ziffer frühestens). Alles in ms,
 * unbekannt: null. total: Summe der bekannten Teile.
 */
export function tapUncertainty({ rttMs = NaN, serverAccMs = NaN, frameMs = NaN } = {}) {
  const part = (v) => (Number.isFinite(v) && v >= 0 ? v : null);
  const device = part(rttMs / 2);
  const server = part(serverAccMs);
  const frame = part(frameMs);
  const total = (device || 0) + (server || 0) + (frame || 0);
  return { device, server, frame, total };
}

/** Betrag einer Abweichung lesbar: unter 10 ms mit einer Nachkommastelle („3,4 ms“), sonst wie kit.fmtDrift. */
export function tapText(absMs) {
  if (!Number.isFinite(absMs)) return "–";
  const v = Math.abs(absMs);
  return v < 9.95 ? `${fmtNumber(v, 1, { group: false })} ms` : kit.fmtDrift(v);
}

/** Bestwerte aus dem localStorage lesen – nur endliche Zahlen in [0, ½ Schritt] je bekanntem Ziel, sonst leer. */
export function tapBestRead(text) {
  const out = {};
  if (typeof text !== "string" || !text || text.length > 200) return out;
  let raw;
  try { raw = JSON.parse(text); } catch (error) { return out; }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [unit, step] of Object.entries(TAP_UNITS)) {
    const value = raw[unit];
    if (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= step / 2) out[unit] = value;
  }
  return out;
}

/** Neuer Tipp: { best (neue Bestwerte), record (neuer Bestwert?) }. Gemerkt wird der Betrag auf 0,1 ms. */
export function tapBestUpdate(best, unit, deviation) {
  const now = { ...(best || {}) };
  if (!TAP_UNITS[unit] || !Number.isFinite(deviation)) return { best: now, record: false };
  const abs = Math.round(Math.abs(deviation) * 10) / 10;
  const record = !(unit in now) || abs < now[unit];
  if (record) now[unit] = abs;
  return { best: now, record };
}

/** Bestwerte als Text für den localStorage (leer: nichts zu merken). */
export function tapBestText(best) {
  const out = tapBestRead(JSON.stringify(best || {}));
  return Object.keys(out).length ? JSON.stringify(out) : "";
}

// Zeitzeichen wie im Rundfunk: fünf kurze Töne auf den Sekunden 55 … 59, ein langer auf der vollen Minute bzw. Stunde.
export const PIPS = Object.freeze({
  short: Object.freeze({ freq: 1000, dur: 0.1 }),
  long: Object.freeze({ freq: 1000, dur: 0.5 }),
  shorts: 5,
});
export const PIP_SCOPES = Object.freeze(["hour", "minute"]);

/**
 * Töne des Zeitzeichens für die vollen Serversekunden nach afterSecond bis horizonMs voraus – gleiche Form wie
 * kit.planTones ({ second, at, kind, freq, dur }). scope "hour": nur vor der vollen Stunde, "minute": vor jeder Minute.
 * offsetMs: Abstand der angezeigten Zeitzone zu UTC (volle Stunde in Indien liegt auf :30 UTC).
 */
export function planPips(clock, { scope = "hour", afterSecond = -Infinity, horizonMs = 1500, offsetMs = 0 } = {}) {
  const out = [];
  if (!clock || !Number.isFinite(clock.server) || !Number.isFinite(clock.audio) || !PIP_SCOPES.includes(scope)) return out;
  const off = Number.isFinite(offsetMs) ? Math.round(offsetMs / 1000) : 0;
  const first = Math.max(Math.floor(clock.server / 1000) + 1, afterSecond + 1);
  const last = Math.floor((clock.server + horizonMs) / 1000);
  for (let second = first; second <= last; second += 1) {
    const local = second + off;
    const inMinute = ((local % 60) + 60) % 60;
    const minuteOfHour = ((Math.floor(local / 60) % 60) + 60) % 60;
    let kind = null;
    if (inMinute >= 60 - PIPS.shorts && (scope === "minute" || minuteOfHour === 59)) kind = "short";
    else if (inMinute === 0 && (scope === "minute" || minuteOfHour === 0)) kind = "long";
    if (!kind) continue;
    out.push({ second, at: clock.audio + (second * 1000 - clock.server) / 1000, kind, ...PIPS[kind] });
  }
  return out;
}

/**
 * Wie weit das Zeitzeichen vorausplanen (ms)? Sichtbar reicht horizonMs (der Sekundentakt plant laufend nach). Im
 * versteckten Tab drosselt der Browser die Zeitgeber bis auf etwa einen Weckruf je Minute: dann bis einschließlich zum
 * langen Ton der nächsten vollen Stunde bzw. Minute (offsetMs: Abstand der Zone zu UTC) – höchstens sechs Töne je Ziel.
 */
export function pipsHorizonMs(serverMs, { scope = "hour", hidden = false, horizonMs = 1500, offsetMs = 0 } = {}) {
  if (!hidden || !Number.isFinite(serverMs) || !PIP_SCOPES.includes(scope)) return horizonMs;
  const step = scope === "hour" ? 3_600_000 : 60_000;
  const off = Number.isFinite(offsetMs) ? Math.round(offsetMs / 1000) * 1000 : 0;
  const local = serverMs + off;
  const next = (Math.floor(local / step) + 1) * step - off;   // nächste volle Stunde bzw. Minute (UTC-ms)
  return Math.max(horizonMs, next - serverMs + 500);
}

/**
 * Zeitumstellung am Tag von ms in `zone` (null: Zone dieses Geräts): Minuten, um die die Uhr an diesem Tag vor- (positiv)
 * oder zurückgestellt (negativ) wird, sonst 0.
 */
export function dstShiftOfDay(ms, zone = null) {
  if (!Number.isFinite(ms)) return 0;
  const p = cd.zoneParts(ms, zone);
  const start = cd.zonedTime({ y: p.y, mo: p.mo, d: p.d }, zone);
  const end = cd.zonedTime({ y: p.y, mo: p.mo, d: p.d + 1 }, zone);
  return Math.round((cd.zoneOffset(end, zone) - cd.zoneOffset(start, zone)) / MIN);
}

/**
 * Ostereier als Tabelle, in dieser Reihenfolge geprüft (das erste passende gewinnt). when bekommt die angezeigte Zeit
 * { h, m, s, mo, d } (24 h, Monat 1–12) und die Lage { leap: kit.leapEgg(…), dst: dstShiftOfDay(…) }. confetti: dazu
 * Konfetti (nur CSS; bei „weniger Bewegung“ nur der Text). Der Konami-Code steht nicht hier: Er hängt an Tasten, nicht
 * an der Zeit (konamiStep).
 */
export const EGGS = Object.freeze([
  Object.freeze({ kind: "newyear", confetti: true, when: (t) => t.mo === 1 && t.d === 1 && t.h === 0 && t.m < 10 }),
  Object.freeze({ kind: "straight", confetti: false, when: (t) => t.h === 12 && t.m === 34 && t.s >= 56 }),
  Object.freeze({ kind: "leet", confetti: false, when: (t) => t.h === 13 && t.m === 37 }),
  Object.freeze({ kind: "leap", confetti: false, when: (t, at) => Boolean(at.leap) }),
  Object.freeze({ kind: "dst", confetti: false, when: (t, at) => at.dst !== 0 }),
]);

/**
 * Welches Osterei gilt jetzt? { kind, text (Schlüssel unter clock.egg_…), confetti } oder null. Ohne Erlaubnis
 * (eggsAllowed) nie eins.
 */
export function eggFor(time, { leap = null, dst = 0, allowed = true } = {}) {
  if (!allowed || !time) return null;
  for (const egg of EGGS) {
    if (!egg.when(time, { leap, dst: Number.isFinite(dst) ? dst : 0 })) continue;
    let text = egg.kind;
    if (egg.kind === "leap") text = leap;
    else if (egg.kind === "dst") text = dst > 0 ? "dst_forward" : "dst_back";
    return { kind: egg.kind, text, confetti: egg.confetti };
  }
  return null;
}

/** Konfetti zeigen? "css" (fallende Schnipsel nur per CSS), "text" (bei „weniger Bewegung“: nur der Text), "none". */
export function confettiMode({ allowed = true, wanted = false, reduced = false } = {}) {
  if (!allowed || !wanted) return "none";
  return reduced ? "text" : "css";
}

/** Konami-Code: ↑ ↑ ↓ ↓ ← → ← → B A (KeyboardEvent.key, Buchstaben ohne Groß/Klein). */
export const KONAMI = Object.freeze(["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight",
  "ArrowLeft", "ArrowRight", "b", "a"]);

/**
 * Nächster Schritt im Konami-Code: { pos, done }. pos: so viele Tasten passen schon; done: gerade vollständig (pos
 * beginnt dann wieder bei 0). Eine falsche Taste setzt zurück – ein weiteres ↑ zählt dabei als Anfang.
 */
export function konamiStep(pos, key) {
  const at = Number.isInteger(pos) && pos >= 0 && pos < KONAMI.length ? pos : 0;
  const k = typeof key === "string" && key.length === 1 ? key.toLowerCase() : key;
  if (k === KONAMI[at]) return at + 1 === KONAMI.length ? { pos: 0, done: true } : { pos: at + 1, done: false };
  if (k === KONAMI[0]) return { pos: at === 2 ? 2 : 1, done: false };
  return { pos: 0, done: false };
}
