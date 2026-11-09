// Uhr-Werkstatt (/clock, 1.6 T6): reine Funktionen für Designs, Adressparameter, Ton und Geräteversatz.
//
// Kein DOM, keine Zeitgeber – so lässt sich alles mit Node prüfen (tests/test_uhr_werkstatt.py). Die Seite
// (clock.js) baut daraus die Anzeige; Bewegung (Sekundenzeiger, Klappen, Glühen) macht CSS, nicht eine
// JS-Schleife.
import { fmtNumber } from "./util.js";

/** Designs in der Reihenfolge der Auswahl. Schlüssel = Wert von ?design= und im Browser gemerkt. */
export const DESIGNS = ["digital", "bahnhof", "nixie", "flip", "wort"];
export const DEFAULT_DESIGN = "digital";

// --- Adressparameter (Allowlist) ---------------------------------------------------
// Nur bekannte Namen mit bekannten Werten wirken; alles andere wird stillschweigend ignoriert. Die Werte
// landen nie als HTML im DOM, trotzdem prüfen wir sie hier gegen feste Listen.
const FLAG = { 1: true, 0: false, true: true, false: false };
const MAX_LEN = 64;
const ZONE_CHARS = /^[A-Za-z0-9_+\-/]+$/;

/** Zeitzonenliste des Browsers (Intl.supportedValuesOf), leer, wenn der Browser sie nicht kennt. */
export function supportedZones(intl = globalThis.Intl) {
  try {
    return typeof intl?.supportedValuesOf === "function" ? intl.supportedValuesOf("timeZone") : [];
  } catch (error) {
    return [];
  }
}

/**
 * Zeitzone prüfen: nur [A-Za-z0-9_+-/], höchstens MAX_LEN Zeichen, und dann entweder in `zones` oder von
 * Intl.DateTimeFormat angenommen. Die Liste allein reicht nicht: V8 führt dort nur CLDR-Altnamen
 * (Asia/Calcutta statt Asia/Kolkata) und gar kein UTC. Liefert den Namen (Schreibweise des Browsers,
 * wenn er sich nur in Groß/klein unterscheidet) oder null.
 */
export function checkZone(value, zones = [], intl = globalThis.Intl) {
  if (typeof value !== "string" || !value || value.length > MAX_LEN || !ZONE_CHARS.test(value)) return null;
  if (zones.includes(value)) return value;
  try {
    const resolved = new intl.DateTimeFormat(undefined, { timeZone: value }).resolvedOptions().timeZone;
    return typeof resolved === "string" && resolved.toLowerCase() === value.toLowerCase() ? resolved : value;
  } catch (error) {
    return null;
  }
}

/**
 * ?design=…&kiosk=1&eink=1&tz=Europe/London → { design, kiosk, eink, tz, ignored }.
 * design: einer aus DESIGNS, sonst null; kiosk/eink: 1/0/true/false; tz: siehe checkZone.
 * ignored: Namen bekannter Parameter mit unzulässigem Wert (für eine Konsolenzeile, nie für das DOM).
 */
export function parseParams(search, zones = [], intl = globalThis.Intl) {
  const params = new URLSearchParams(typeof search === "string" ? search : "");
  const out = { design: null, kiosk: false, eink: false, tz: null, ignored: [] };
  for (const name of ["design", "kiosk", "eink", "tz"]) {
    if (!params.has(name)) continue;
    const raw = String(params.get(name) || "");
    const value = raw.length <= MAX_LEN ? raw : "";
    const zone = name === "tz" ? checkZone(value, zones, intl) : null;
    if (name === "design" && DESIGNS.includes(value)) out.design = value;
    else if ((name === "kiosk" || name === "eink") && Object.prototype.hasOwnProperty.call(FLAG, value)) out[name] = FLAG[value];
    else if (zone) out.tz = zone;
    else out.ignored.push(name);
  }
  return out;
}

/** Gemerkte Auswahl prüfen: nur bekannte Designs, sonst Standard. */
export function safeDesign(value) {
  return DESIGNS.includes(value) ? value : DEFAULT_DESIGN;
}

/** Anzeigename einer Zeitzone: „America/New_York“ → „New York“. */
export function zoneLabel(zone) {
  const last = String(zone || "").split("/").pop() || "";
  return last.replace(/_/g, " ");
}

// --- Ziffern (Nixie, Klappzahlen, Digital) -----------------------------------------------
const pad = (n) => String(n).padStart(2, "0");

/** Stunden, Minuten, Sekunden → Ziffernfolge „101542“ (mit Sekunden) bzw. „1015“. */
export function timeDigits(h, m, s, seconds = true) {
  return `${pad(h)}${pad(m)}${seconds ? pad(s) : ""}`;
}

/**
 * Klappzahlen: Welche Ziffern ändern sich von prev nach next? Nur diese klappen.
 * [{ digit: "4", changed: true }, …]; ohne prev (erster Aufbau) klappt nichts.
 */
export function flipDigits(prev, next) {
  const before = String(prev || "");
  return [...String(next)].map((digit, index) => ({
    digit, changed: before.length === String(next).length && before[index] !== digit,
  }));
}

// --- Bahnhofsuhr (eigenes, schlichtes Zifferblatt) ----------------------------------------
/** Der Sekundenzeiger läuft in 58,5 s einmal herum und wartet dann auf der 12 auf die volle Minute. */
export const SWEEP_SECONDS = 58.5;

/**
 * Zeigerwinkel in Grad (0 = 12 Uhr, im Uhrzeigersinn). Minutenzeiger springt jede Minute,
 * Stundenzeiger rückt mit jeder Minute ein halbes Grad weiter. Sekundenzeiger: gleichmäßig in
 * 58,5 s herum, dann Halt auf 0 bis zur vollen Minute; mit step=true springt er sekundenweise (ruhig).
 */
export function handAngles(h, m, s, ms = 0, { step = false } = {}) {
  const hour = ((h % 12) * 30 + m * 0.5) % 360;
  const minute = (m * 6) % 360;
  let second;
  if (step) {
    second = (s * 6) % 360;
  } else {
    const t = s + ms / 1000;
    second = t < SWEEP_SECONDS ? (t / SWEEP_SECONDS) * 360 : 0;
  }
  return { hour, minute, second };
}

// --- Wortuhr ----------------------------------------------------------------------
const HOURS_DE = ["ZWÖLF", "EINS", "ZWEI", "DREI", "VIER", "FÜNF", "SECHS", "SIEBEN", "ACHT", "NEUN", "ZEHN", "ELF"];
const HOURS_EN = ["TWELVE", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN"];
// Je Fünf-Minuten-Schritt: Wörter vor der Stunde und ob die nächste Stunde gemeint ist.
const STEPS_DE = [
  [[], 0], [["FÜNF", "NACH"], 0], [["ZEHN", "NACH"], 0], [["VIERTEL", "NACH"], 0], [["ZWANZIG", "NACH"], 0],
  [["FÜNF", "VOR", "HALB"], 1], [["HALB"], 1], [["FÜNF", "NACH", "HALB"], 1], [["ZWANZIG", "VOR"], 1],
  [["VIERTEL", "VOR"], 1], [["ZEHN", "VOR"], 1], [["FÜNF", "VOR"], 1],
];
const STEPS_EN = [
  [[], 0], [["FIVE", "PAST"], 0], [["TEN", "PAST"], 0], [["QUARTER", "PAST"], 0], [["TWENTY", "PAST"], 0],
  [["TWENTY-FIVE", "PAST"], 0], [["HALF", "PAST"], 0], [["TWENTY-FIVE", "TO"], 1], [["TWENTY", "TO"], 1],
  [["QUARTER", "TO"], 1], [["TEN", "TO"], 1], [["FIVE", "TO"], 1],
];

/**
 * Uhrzeit in Worten, auf fünf Minuten abgerundet wie bei einer Wortuhr; dots = die Minuten
 * dazwischen (0–4, als Punkte angezeigt). Deutsch: „ES IST VIERTEL NACH ZEHN“, zur vollen Stunde
 * „ES IST ZEHN UHR“ („EIN UHR“). Englisch (Beta): „IT IS QUARTER PAST TEN“, „IT IS TEN O'CLOCK“.
 */
export function wordClock(h, m, lang = "de") {
  const en = lang === "en";
  const step = Math.floor((((m % 60) + 60) % 60) / 5);
  const [words, next] = (en ? STEPS_EN : STEPS_DE)[step];
  const hour = ((h % 12) + next) % 12;
  const names = en ? HOURS_EN : HOURS_DE;
  const out = en ? ["IT", "IS", ...words] : ["ES", "IST", ...words];
  if (step === 0) out.push(en ? names[hour] : (hour === 1 ? "EIN" : names[hour]), en ? "O'CLOCK" : "UHR");
  else out.push(names[hour]);
  return { words: out, text: out.join(" "), dots: m % 5 };
}

// --- Ton auf der Sekunde --------------------------------------------------------------
export const BEEP = {
  short: { freq: 1000, dur: 0.06 },
  long: { freq: 1000, dur: 0.5 },
  count: { freq: 1500, dur: 0.06 },
};
/** „Uhr stellen“: so viele Sekunden vor der vollen Minute beginnt der Countdown. */
export const COUNTDOWN_SECONDS = 10;

/**
 * Bezug zwischen AudioContext-Zeit und Serverzeit für „jetzt“.
 * audio: die Audiozeit (s), die gerade aus dem Gerät kommt; server: Serverzeit (ms) in diesem Moment.
 * Mit getOutputTimestamp() (Chrome, Firefox) samt Ausgabelatenz des Browsers; sonst currentTime minus
 * outputLatency/baseLatency. Die Laufzeit im Lautsprecher selbst (z. B. Bluetooth) kennt niemand.
 *   perfNow = performance.now(), wallNow = Date.now() (gleicher Moment), offsetMs = Versatz aus clocksync.js.
 */
export function audioClock(ctx, perfNow, wallNow, offsetMs = 0) {
  const off = Number.isFinite(offsetMs) ? offsetMs : 0;
  let stamp = null;
  try { stamp = typeof ctx.getOutputTimestamp === "function" ? ctx.getOutputTimestamp() : null; } catch (error) { stamp = null; }
  if (stamp && Number.isFinite(stamp.contextTime) && Number.isFinite(stamp.performanceTime) && stamp.performanceTime > 0
      && stamp.contextTime > 0) {
    return { audio: stamp.contextTime, server: wallNow - (perfNow - stamp.performanceTime) + off, exact: true };
  }
  const latency = Number(ctx.outputLatency) || Number(ctx.baseLatency) || 0;
  return { audio: ctx.currentTime - latency, server: wallNow + off, exact: false };
}

/**
 * Töne für alle vollen Serversekunden nach `afterSecond` bis `horizonMs` voraus.
 * mode "seconds": kurzer Piep jede Sekunde, langer zur vollen Minute.
 * mode "countdown": nur die letzten COUNTDOWN_SECONDS vor der vollen Minute (höher) und der lange Ton bei 0.
 * Ergebnis: [{ second (Unix-Sekunde des Servers), at (Audiozeit s), kind, freq, dur }].
 */
export function planTones(clock, { mode = "seconds", afterSecond = -Infinity, horizonMs = 1500 } = {}) {
  const out = [];
  const first = Math.max(Math.floor(clock.server / 1000) + 1, afterSecond + 1);
  const last = Math.floor((clock.server + horizonMs) / 1000);
  for (let second = first; second <= last; second += 1) {
    const inMinute = ((second % 60) + 60) % 60;
    let kind = null;
    if (inMinute === 0) kind = "long";
    else if (mode === "seconds") kind = "short";
    else if (mode === "countdown" && inMinute >= 60 - COUNTDOWN_SECONDS) kind = "count";
    if (!kind) continue;
    const at = clock.audio + (second * 1000 - clock.server) / 1000;
    out.push({ second, at, kind, ...BEEP[kind] });
  }
  return out;
}

/** Einen geplanten Ton anlegen (Sinus mit kurzer Rampe gegen Knacksen). Liefert den Oszillator. */
export function scheduleTone(ctx, tone, volume = 0.25) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "sine";
  osc.frequency.value = tone.freq;
  const g = gain.gain;
  g.setValueAtTime(0, tone.at);
  g.linearRampToValueAtTime(volume, tone.at + 0.004);
  g.setValueAtTime(volume, tone.at + Math.max(0.005, tone.dur - 0.01));
  g.linearRampToValueAtTime(0, tone.at + tone.dur);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start(tone.at);
  osc.stop(tone.at + tone.dur + 0.01);
  return osc;
}

/** Countdown bis zur vollen Minute („Drücke bei 0“): 10 … 1, 0 genau auf der Minute, sonst null. */
export function countdownValue(serverMs) {
  const inMinute = Math.floor(serverMs / 1000) % 60;
  if (inMinute === 0) return 0;
  const left = 60 - inMinute;
  return left <= COUNTDOWN_SECONDS ? left : null;
}

// --- „Wie falsch geht dein Gerät?“ -------------------------------------------------------
// Versatz aus clocksync.js: positiv = die Browseruhr geht nach. Bleibt im Browser (nie gespeichert/gesendet).
export const DEVICE_GOOD_MS = 100;
export const DEVICE_WARN_MS = 1000;

/**
 * { tone: good|warn|crit|unknown, dir: behind|ahead|exact|uncertain, abs (ms) } – exact, wenn innerhalb der
 * Messgenauigkeit. Grün nur, wenn auch der ungünstigste Wert (|Versatz| + Genauigkeit) unter DEVICE_GOOD_MS
 * liegt. Kann der echte Versatz auf beiden Seiten von DEVICE_GOOD_MS liegen (|Versatz| < DEVICE_GOOD_MS, oder
 * |Versatz| ≤ Genauigkeit), lässt sich kein Urteil belegen: uncertain/unknown (grau). Liegt |Versatz| sicher
 * außerhalb der Genauigkeit und ab DEVICE_GOOD_MS, gilt die Ampel nach dem gemessenen Wert.
 */
export function deviceDrift(offsetMs, accuracyMs = 0) {
  if (!Number.isFinite(offsetMs)) return null;
  const abs = Math.abs(offsetMs);
  const acc = Number.isFinite(accuracyMs) ? Math.abs(accuracyMs) : 0;
  const dir = abs <= acc ? "exact" : (offsetMs > 0 ? "behind" : "ahead");
  if (abs + acc < DEVICE_GOOD_MS) return { tone: "good", dir, abs };
  if (abs < DEVICE_GOOD_MS || dir === "exact") return { tone: "unknown", dir: "uncertain", abs };
  const tone = abs < DEVICE_WARN_MS ? "warn" : "crit";
  return { tone, dir, abs };
}

/** Betrag lesbar ohne Vorzeichen: „42 ms“, „3,2 s“, „2 min 5 s“ (gewählte Sprache über fmtNumber). */
export function fmtDrift(absMs) {
  if (!Number.isFinite(absMs)) return "–";
  const v = Math.abs(absMs);
  if (v < 1000) return `${fmtNumber(v, 0, { group: false })} ms`;
  // Unter 10 s mit einer Nachkommastelle (9 950 ms ergäben „10,0 s“, daher die Grenze davor).
  if (v < 9_950) return `${fmtNumber(v / 1000, 1, { group: false })} s`;
  // Erst auf ganze Sekunden runden, dann aufteilen: sonst „60 s“ oder „1 min 60 s“ an den Grenzen.
  const total = Math.round(v / 1000);
  if (total < 60) return `${fmtNumber(total, 0, { group: false })} s`;
  const minutes = Math.floor(total / 60);
  return `${fmtNumber(minutes, 0, { group: false })} min ${fmtNumber(total % 60, 0, { group: false })} s`;
}

// --- Osterei: Schaltsekunde --------------------------------------------------------------
/**
 * Am 30. Juni und 31. Dezember (UTC) dürfte die letzte Minute des Tages 61 Sekunden haben.
 * leapStatus: chronys Leap-Status aus /api/v1/time („Insert second“, „Delete second“, „Normal“),
 * leapNext: Datum der nächsten angekündigten Schaltsekunde aus leap.py („2017-01-01“ = Beginn danach).
 * Ergebnis: null (kein Tag dafür) oder "insert" | "delete" | "possible".
 */
export function leapEgg(serverMs, leapStatus, leapNext) {
  if (!Number.isFinite(serverMs)) return null;
  const day = new Date(serverMs);
  const month = day.getUTCMonth() + 1;
  const date = day.getUTCDate();
  if (!((month === 6 && date === 30) || (month === 12 && date === 31))) return null;
  if (leapStatus === "Delete second") return "delete";
  if (leapStatus === "Insert second") return "insert";
  const tomorrow = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), date + 1)).toISOString().slice(0, 10);
  return leapNext === tomorrow ? "insert" : "possible";
}
