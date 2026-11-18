// Timecode-Anzeige der Studiouhr (Design tc, Etappe B1): reine Funktionen, kein DOM, keine Zeitgeber.
//
// Das Design zeigt die Tageszeit als HH:MM:SS:FF aus der abgeglichenen Serverzeit. Es ist eine Anzeige, kein
// Referenzsignal: nicht genlocked, ohne Hausreferenzsignal, mit der Bildwiederholrate des Monitors als Raster. Darum
// ist die Feinstelle (Zehntel oder Frames) eigens abgesichert:
//   – Standard sind Zehntel, Frames gibt es nur auf ausdrücklichen Wunsch (?sub=frames, Taste T).
//   – Die Feinstelle wird grau, wenn die Fehlerschranke sie nicht trägt (Frames: über ½ Frame, Zehntel: über 50 ms),
//     und verschwindet über ?maxerr= (kit.fineDigits).
//   – Rundet der Browser seine Zeitgeber grob (performance.now() in Stufen von 16,7 oder 100 ms), wird sie ebenfalls
//     grau (timerGrain, fineLevel).
//   – E-Ink zeigt keine Feinstelle, bei „weniger Bewegung“ (prefers-reduced-motion) gibt es höchstens Zehntel.
//   – Ist die Feinstelle ausgeblendet, kommen auch die Sekunden aus der Wanduhr, nicht aus der Framenummer (paintMode).
// Drop-Frame (29,97 und 59,94 fps) rechnet framesToTc nach der SMPTE-Zählweise: Zu Beginn jeder Minute fallen die
// Nummern 00 und 01 (bei 59,94: 00 bis 03) weg, außer in jeder zehnten Minute; Trennzeichen vor den Frames ist „;“.
import { fineDigits, TENTHS_UNSURE_MS } from "./clockkit.js";

export const DAY_MS = 86_400_000;

/**
 * Bildraten (?fps=). nominal: Frames je Timecode-Sekunde; drop: Nummern, die je Minute wegfallen (Drop-Frame);
 * den: Nenner der echten Bildrate (nominal × 1000 / den Bilder je Sekunde, also 30000/1001 bei 29,97).
 */
export const TC_RATES = Object.freeze({
  24: Object.freeze({ fps: "24", nominal: 24, drop: 0, den: 1000 }),
  25: Object.freeze({ fps: "25", nominal: 25, drop: 0, den: 1000 }),
  30: Object.freeze({ fps: "30", nominal: 30, drop: 0, den: 1000 }),
  50: Object.freeze({ fps: "50", nominal: 50, drop: 0, den: 1000 }),
  60: Object.freeze({ fps: "60", nominal: 60, drop: 0, den: 1000 }),
  29.97: Object.freeze({ fps: "29.97", nominal: 30, drop: 2, den: 1001 }),
  59.94: Object.freeze({ fps: "59.94", nominal: 60, drop: 4, den: 1001 }),
});
export const DEFAULT_FPS = "25";

/** Bildrate zu einem Wert von ?fps=; unbekannt: 25 fps. */
export function tcRate(fps) {
  const key = String(fps ?? "");
  return Object.prototype.hasOwnProperty.call(TC_RATES, key) ? TC_RATES[key] : TC_RATES[DEFAULT_FPS];
}

/** Dauer eines Frames in ms (29,97 fps: 33,37 ms). */
export function frameMs(rate) {
  return rate.den / rate.nominal;
}

/** Frames je Timecode-Minute mit weggelassenen Nummern (29,97: 1798) und je zehn Minuten (17 982). */
function perMinute(rate) {
  return rate.nominal * 60 - rate.drop;
}
function perTenMinutes(rate) {
  return rate.nominal * 600 - rate.drop * 9;
}

/** Frames eines Timecode-Tages: 24 h × Bildrate, bei Drop-Frame abzüglich der weggelassenen Nummern (29,97: 2 589 408). */
export function dayFrames(rate) {
  return rate.drop ? perTenMinutes(rate) * 144 : rate.nominal * 86400;
}

/**
 * Laufende Framenummer seit 00:00:00:00 → Timecode { h, m, s, f }. Läuft über den Tag hinaus um (nach 23:59:59 und dem
 * letzten Frame folgt 00:00:00:00), negative Nummern zählen vom Tagesende. Keine gültige Zahl: null.
 */
export function framesToTc(frame, rate) {
  if (!Number.isFinite(frame) || !rate) return null;
  const day = dayFrames(rate);
  let n = ((Math.floor(frame) % day) + day) % day;
  if (rate.drop) {
    // Weggelassene Nummern wieder einrechnen: 9 × drop je vollen zehn Minuten, dazu drop je begonnener Minute danach
    // (die erste Minute eines Zehnerblocks lässt nichts weg).
    const tens = Math.floor(n / perTenMinutes(rate));
    const rest = n % perTenMinutes(rate);
    n += rate.drop * 9 * tens;
    if (rest >= rate.nominal * 60) n += rate.drop * (1 + Math.floor((rest - rate.nominal * 60) / perMinute(rate)));
  }
  const seconds = Math.floor(n / rate.nominal);
  return { h: Math.floor(seconds / 3600) % 24, m: Math.floor(seconds / 60) % 60, s: seconds % 60, f: n % rate.nominal };
}

/** Timecode → laufende Framenummer; NaN für Werte außerhalb des Tages und für Nummern, die Drop-Frame weglässt. */
export function tcToFrames(tc, rate) {
  if (!tc || !rate || ![tc.h, tc.m, tc.s, tc.f].every(Number.isInteger)) return NaN;
  const { h, m, s, f } = tc;
  if (h < 0 || h > 23 || m < 0 || m > 59 || s < 0 || s > 59 || f < 0 || f >= rate.nominal) return NaN;
  if (rate.drop && s === 0 && f < rate.drop && m % 10 !== 0) return NaN;
  const minutes = h * 60 + m;
  return ((minutes * 60 + s) * rate.nominal + f) - rate.drop * (minutes - Math.floor(minutes / 10));
}

/**
 * Tageszeit (ms seit Mitternacht) → laufende Framenummer bei echter Bildrate. Ein Drop-Frame-Tag ist 86,4 ms kürzer
 * als ein Kalendertag: In den letzten Millisekunden vor Mitternacht bleibt die Nummer auf dem letzten Frame stehen
 * (23:59:59;29), statt vorzeitig auf 00:00:00;00 umzulaufen.
 */
export function frameAt(todMs, rate) {
  if (!Number.isFinite(todMs) || !rate) return NaN;
  const frame = Math.floor((Math.max(0, todMs) * rate.nominal) / rate.den + 1e-9);
  return Math.min(frame, dayFrames(rate) - 1);
}

/** Zeitpunkt (ms) plus Abstand der Zone zu UTC (ms) → Tageszeit in ms seit Mitternacht (0 … 86 399 999,9). */
export function dayMs(ms, offsetMs = 0) {
  if (!Number.isFinite(ms) || !Number.isFinite(offsetMs)) return NaN;
  return (((ms + offsetMs) % DAY_MS) + DAY_MS) % DAY_MS;
}

/**
 * Welche Feinstelle zeigt das Design? sub: Wert von ?sub= bzw. die Wahl per Taste T. "frames" nur auf ausdrücklichen
 * Wunsch und nie bei „weniger Bewegung“ (dann Zehntel); "off" schaltet sie ab; alles andere sind Zehntel. E-Ink und
 * eine Anzeige ohne Sekunden (?show= ohne seconds) haben keine Feinstelle. Ergebnis: "frames" | "tenths" | "off".
 */
export function fineMode(sub, { eink = false, reduced = false, seconds = true } = {}) {
  if (eink || !seconds || sub === "off") return "off";
  if (sub === "frames") return reduced ? "tenths" : "frames";
  return "tenths";
}

/** Wert von ?sub= für das Design studio: Die Werte der Timecode-Feinstelle bedeuten dort die Standardzeile (UTC). */
export function studioSub(sub) {
  return sub === "tenths" || sub === "frames" ? "utc" : sub;
}

/**
 * Feinstelle, mit der gezeichnet wird. Ist sie ausgeblendet (level "off"), kommen HH:MM:SS aus der Wanduhr: Die
 * Bildschleife steht dann, gezeichnet wird nur zur vollen Wanduhr-Sekunde – ein Drop-Frame-Timecode, der der Wanduhr
 * um einige Millisekunden nachläuft, zeigte zu diesem Zeitpunkt sonst dauerhaft die vorige Sekunde.
 */
export function paintMode(mode, level) {
  return level === "off" ? "off" : mode;
}

/**
 * Taste T: nächste Feinstelle. Üblich ist der Wechsel Zehntel ↔ Frames. Ist die Anzeige mit ?sub=off eingerichtet
 * (base), führt die Taste im Dreierwechsel auch wieder zurück: aus → Zehntel → Frames → aus.
 */
export function nextFine(current, base) {
  if (current === "frames") return base === "off" ? "off" : "tenths";
  return current === "off" ? "tenths" : "frames";
}

/**
 * Kalendertag der Wanduhr in einer Zone: Zeitpunkt (ms) plus Abstand der Zone zu UTC (ms) → { y, mo, d } (mo 1–12).
 * Damit stehen Datum und Woche unter dem Timecode in derselben Zone wie die Zeit. Ohne gültige Werte null.
 */
export function zoneDay(ms, offsetMs = 0) {
  if (!Number.isFinite(ms) || !Number.isFinite(offsetMs)) return null;
  const wall = new Date(ms + offsetMs);
  return { y: wall.getUTCFullYear(), mo: wall.getUTCMonth() + 1, d: wall.getUTCDate() };
}

const pad = (n) => String(n).padStart(2, "0");

/**
 * Anzeige aus der Tageszeit: { hh, mm, ss, sep, fine, text }.
 *   frames: Timecode bei der gewählten Bildrate, sep „:“ bzw. „;“ bei Drop-Frame, fine = FF.
 *   tenths: Uhrzeit mit Zehntelsekunde (abgerundet), sep „.“ (die Seite setzt das Dezimalzeichen der Sprache).
 *   off:    nur HH:MM:SS.
 * Ohne gültige Tageszeit Striche.
 */
export function tcView(todMs, fps, mode = "tenths") {
  if (!Number.isFinite(todMs)) {
    const fine = mode === "frames" ? "--" : (mode === "tenths" ? "-" : "");
    return { hh: "--", mm: "--", ss: "--", sep: mode === "frames" ? ":" : (mode === "tenths" ? "." : ""), fine,
      text: `--:--:--${fine ? (mode === "frames" ? ":" : ".") + fine : ""}` };
  }
  const rate = tcRate(fps);
  const tod = dayMs(todMs);
  if (mode === "frames") {
    const tc = framesToTc(frameAt(tod, rate), rate);
    const sep = rate.drop ? ";" : ":";
    return { hh: pad(tc.h), mm: pad(tc.m), ss: pad(tc.s), sep, fine: pad(tc.f),
      text: `${pad(tc.h)}:${pad(tc.m)}:${pad(tc.s)}${sep}${pad(tc.f)}` };
  }
  const total = Math.floor(tod / 1000);
  const hh = pad(Math.floor(total / 3600));
  const mm = pad(Math.floor(total / 60) % 60);
  const ss = pad(total % 60);
  if (mode !== "tenths") return { hh, mm, ss, sep: "", fine: "", text: `${hh}:${mm}:${ss}` };
  const fine = String(Math.floor((tod % 1000) / 100));
  return { hh, mm, ss, sep: ".", fine, text: `${hh}:${mm}:${ss}.${fine}` };
}

// --- Rundung der Zeitgeber des Browsers ----------------------------------------------------------------------
/** So viele Messwerte von performance.now() sammelt die Seite mindestens bzw. höchstens (je einer pro Zeitgeber-Takt). */
export const GRAIN_MIN_SAMPLES = 12;
export const GRAIN_MAX_SAMPLES = 250;

/** Reichen die Messwerte? Ab GRAIN_MIN_SAMPLES mit drei verschiedenen Werten, spätestens nach GRAIN_MAX_SAMPLES. */
export function grainDone(samples) {
  const list = Array.isArray(samples) ? samples : [];
  if (list.length >= GRAIN_MAX_SAMPLES) return true;
  return list.length >= GRAIN_MIN_SAMPLES && new Set(list).size >= 3;
}

/**
 * Raster von performance.now() aus Messwerten, die im Abstand weniger Millisekunden genommen wurden: der kleinste
 * Schritt zwischen zwei verschiedenen Werten (ms, obere Schranke für das Raster). Üblich sind 0,005 bis 1 ms; mit
 * Schutz gegen Wiedererkennung runden Browser auf 16,7 oder 100 ms. Bewegt sich der Wert über alle Messungen nicht,
 * ist das Raster gröber als die ganze Messung: Infinity. Zu wenige Messwerte: null (unbekannt).
 */
export function timerGrain(samples) {
  const list = (Array.isArray(samples) ? samples : []).filter(Number.isFinite).sort((a, b) => a - b);
  if (list.length < GRAIN_MIN_SAMPLES) return null;
  let grain = Infinity;
  for (let i = 1; i < list.length; i += 1) {
    const step = list[i] - list[i - 1];
    if (step > 0 && step < grain) grain = step;
  }
  return Number.isFinite(grain) ? Math.round(grain * 1000) / 1000 : Infinity;
}

/** Grenze, bis zu der Schranke und Zeitgeber-Raster die Feinstelle tragen (ms): ½ Frame bzw. 50 ms bei Zehnteln. */
export function fineLimit(mode, rate) {
  if (mode === "frames") return frameMs(rate || TC_RATES[DEFAULT_FPS]) / 2;
  return mode === "tenths" ? TENTHS_UNSURE_MS : NaN;
}

/**
 * Zustand der Feinstelle: { level, reason, limit }.
 *   level:  "sure" (normal), "unsure" (grau) oder "off" (ausgeblendet),
 *   reason: "" | "bound" (Fehlerschranke über der Grenze bzw. über maxerrMs oder unbekannt) | "grain" (grobe Zeitgeber),
 *   limit:  die Grenze in ms.
 * Die Schranke geht vor: Über maxerrMs oder ohne Schranke ist die Feinstelle weg, gleich wie fein die Zeitgeber sind.
 */
export function fineLevel({ mode = "tenths", boundMs = null, grainMs = null, fps = DEFAULT_FPS, maxerrMs = 100 } = {}) {
  const rate = tcRate(fps);
  const limit = fineLimit(mode, rate);
  if (mode !== "frames" && mode !== "tenths") return { level: "off", reason: "", limit };
  const digits = fineDigits(boundMs, { fps: 1000 / frameMs(rate), maxerrMs });
  const byBound = mode === "frames" ? digits.frames : digits.tenths;
  if (byBound === "off") return { level: "off", reason: "bound", limit };
  if (byBound === "unsure") return { level: "unsure", reason: "bound", limit };
  if (typeof grainMs === "number" && !Number.isNaN(grainMs) && grainMs > limit) return { level: "unsure", reason: "grain", limit };
  return { level: "sure", reason: "", limit };
}
