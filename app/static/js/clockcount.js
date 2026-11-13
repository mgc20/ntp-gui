// Countdown, Count-up und Timer der Studiouhr (A5): reine Funktionen, kein DOM, keine Zeitgeber.
//
// Zwei Arten von Zielen:
//   – absolut (?until=20:15 oder ?until=2026-12-31T23:59:59): gerechnet auf der korrigierten Serverzeit in der
//     Zeitzone des Servers. Jeder Bildschirm rechnet für sich dasselbe Ziel aus und zeigt deshalb dasselbe – ganz
//     ohne Steuerkanal.
//   – lokal (?timer=25m, ohne Parameter die Stoppuhr): ein Zustandsautomat auf performance.now(), der nur aus
//     Differenzen rechnet. Verstellt sich die Geräteuhr, läuft der Timer unbeirrt weiter.
// clock.js zeichnet daraus einmal je Sekunde (Zehntel: alle 100 ms, nur solange ein lokaler Timer läuft).
import { BEEP } from "./clockkit.js";

const pad = (n) => String(n).padStart(2, "0");
export const MINUS = "−";   // echtes Minuszeichen, so breit wie das Plus

// --- Zeitzone: Wanduhrzeit ↔ Zeitpunkt ---------------------------------------------------------
const PARTS_FMT = new Map();

function partsFormat(zone) {
  // Ohne Zone gilt die des Browsers – die kann sich ändern (Reise, Umstellung im System), ein Intl-Objekt friert sie aber
  // beim Erzeugen ein. Deshalb steht die aktuelle Zone des Browsers im Schlüssel.
  const key = zone || `browser:${new Intl.DateTimeFormat().resolvedOptions().timeZone}`;
  if (!PARTS_FMT.has(key)) {
    PARTS_FMT.set(key, new Intl.DateTimeFormat("en-US", { timeZone: zone || undefined, hourCycle: "h23", year: "numeric",
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }));
  }
  return PARTS_FMT.get(key);
}

/** Gültiger IANA-Name für Intl, sonst null (dann gilt die Zeitzone des Browsers). */
export function usableZone(zone) {
  if (typeof zone !== "string" || !zone || zone.length > 64) return null;
  try {
    partsFormat(zone);
    return zone;
  } catch (error) {
    PARTS_FMT.delete(zone);
    return null;
  }
}

/** So lange wartet ?until= höchstens auf die Zeitzone des Servers, bevor die des Browsers gilt. */
export const ZONE_WAIT_MS = 5000;

/**
 * Zeitzone für ?until=: die des Servers aus der ersten Antwort von /api/v1/time (unbrauchbar: null, also Browser).
 * Ohne Antwort undefined – dann zeigt der Countdown noch nichts (keine Stufe, keine Ansage, kein Ton), statt erst in
 * der Zone des Browsers zu rechnen und dann um die Zonendifferenz zu springen. Schlug die Messung fehl (z. B. 401)
 * oder ist ZONE_WAIT_MS vergangen, gilt die Zone des Browsers (null). anchored=false (Antwort da, aber noch kein Anker
 * aus dem ersten Messbündel): ebenfalls undefined, bis der Anker steht oder ZONE_WAIT_MS vergangen ist.
 */
export function untilZone(status, { failed = false, waitedMs = 0, anchored = true } = {}) {
  // Ohne Anker liefe die Rechnung auf der Gerätezeit und spränge mit dem ersten Anker: so lange auch noch nichts.
  if (status) return anchored || waitedMs >= ZONE_WAIT_MS ? usableZone(status.zone) : undefined;
  return failed || waitedMs >= ZONE_WAIT_MS ? null : undefined;
}

/** Wanduhrzeit in `zone` (null: Browser) zum Zeitpunkt ms: { y, mo, d, h, m, s }. */
export function zoneParts(ms, zone = null) {
  const out = {};
  for (const part of partsFormat(zone).formatToParts(new Date(ms))) {
    if (part.type !== "literal") out[part.type] = Number(part.value);
  }
  return { y: out.year, mo: out.month, d: out.day, h: out.hour % 24, m: out.minute, s: out.second };
}

/** Abstand der Wanduhr in `zone` zu UTC (ms) zum Zeitpunkt ms. */
export function zoneOffset(ms, zone = null) {
  const whole = Math.floor(ms / 1000) * 1000;
  const p = zoneParts(whole, zone);
  return Date.UTC(p.y, p.mo - 1, p.d, p.h, p.m, p.s) - whole;
}

/**
 * Wanduhrzeit in `zone` → Zeitpunkt (ms). An Umstellungstagen eindeutig:
 *   – doppelt vorhandene Zeit (Herbst, 02:30 gibt es zweimal): die erste, also noch Sommerzeit;
 *   – fehlende Zeit (Frühjahr, 02:30 gibt es nicht): um die Lücke verschoben (02:30 → 03:30 Sommerzeit).
 * Monat und Tag dürfen überlaufen (Tag 32 = 1. des Folgemonats), wie bei Date.UTC.
 */
export function zonedTime({ y, mo, d, h = 0, m = 0, s = 0 }, zone = null) {
  const local = Date.UTC(y, mo - 1, d, h, m, s);
  const before = zoneOffset(local - 14 * 3600_000, zone);
  const after = zoneOffset(local + 14 * 3600_000, zone);
  const hits = [];
  for (const offset of new Set([before, after, zoneOffset(local, zone)])) {
    const at = local - offset;
    if (zoneOffset(at, zone) === offset) hits.push(at);   // dort zeigt die Wanduhr wirklich diese Zeit
  }
  if (hits.length) return Math.min(...hits);
  return local - before;   // Lücke: mit dem Abstand vor der Umstellung gelesen, landet die Zeit dahinter
}

// --- Absolute Ziele (?until=) -----------------------------------------------------------------
/** So lange nach einem täglichen Ziel bleibt es stehen (Überzeit bzw. 00:00), danach gilt der nächste Tag. */
export const DAILY_HOLD_MS = 3600_000;

/**
 * Zeitpunkt (ms) des Ziels aus ?until= (parseTimeValue) zur Serverzeit nowMs in `zone`.
 *   daily: heute in der Zone; ist es schon vorbei, morgen – außer es liegt weniger als holdMs zurück (dann bleibt
 *          es stehen, damit „Überzeit“ bzw. „seit Sendebeginn“ eine Stunde lang hochzählt). Auch das Ziel von gestern
 *          zählt dafür: until=23:30 zeigt um 00:10 noch +00:40:00.
 *   iso:   der Zeitpunkt in der Zone.
 * Ungültig: NaN.
 */
export function untilTarget(spec, nowMs, zone = null, holdMs = DAILY_HOLD_MS) {
  if (!spec || !Number.isFinite(nowMs)) return NaN;
  if (spec.kind === "iso") return zonedTime(spec, zone);
  if (spec.kind !== "daily") return NaN;
  const today = zoneParts(nowMs, zone);
  const at = (days) => zonedTime({ y: today.y, mo: today.mo, d: today.d + days, h: spec.h, m: spec.m, s: spec.s }, zone);
  const recent = [at(0), at(-1)].filter((t) => t <= nowMs && nowMs - t < holdMs);
  if (recent.length) return Math.max(...recent);
  const next = at(0);
  return next > nowMs ? next : at(1);
}

// --- Anzeige: Text, Farbstufe, Ansagen --------------------------------------------------------
/** Ganze Sekunden → { d, h, m, s }. */
export function splitSeconds(total) {
  const t = Math.max(0, Math.floor(total));
  return { d: Math.floor(t / 86400), h: Math.floor((t % 86400) / 3600), m: Math.floor((t % 3600) / 60), s: t % 60 };
}

/**
 * Dauer als Text: unter 1 h „MM:SS“, sonst „HH:MM:SS“, ab einem Tag „3 T 04:05:06“ (dayUnit). hours=true erzwingt
 * HH:MM:SS. coarse=true (E-Ink, Anzeige nur je Minute): „HH:MM“.
 */
export function fmtSpan(totalSeconds, { hours = false, dayUnit = "T", coarse = false } = {}) {
  const { d, h, m, s } = splitSeconds(totalSeconds);
  const hh = d ? `${d} ${dayUnit} ${pad(h)}` : pad(h);
  if (coarse) return `${hh}:${pad(m)}`;
  if (d || h || hours) return `${hh}:${pad(m)}:${pad(s)}`;
  return `${pad(m)}:${pad(s)}`;
}

/** Namen der Farbstufen in der Reihenfolge von ?warn= (größter Wert zuerst). */
export const LEVELS = ["warn", "alert", "final"];

/**
 * Ansicht eines Countdowns aus der Restzeit (ms; negativ = Ziel vorbei):
 *   before: „−MM:SS“ (aufgerundet: −00:01 ist die letzte Sekunde), Stufe nach warn (absteigende Sekunden):
 *           ≤ warn[0] „warn“ (gelb), ≤ warn[1] „alert“ (rot), ≤ warn[2] „final“ (fett rot), sonst „none“;
 *   over:   after=up, „+HH:MM:SS“ seit dem Ziel (abgerundet), Stufe „over“;
 *   done:   after=stop, Stillstand auf „00:00“, Stufe „done“.
 * { phase, level, text, seconds (Restsekunden, aufgerundet; nach dem Ziel 0), limit (Schwelle der Stufe in s) }.
 */
export function countdownView(remainingMs, { after = "up", warn = [300, 60, 10], dayUnit = "T", coarse = false } = {}) {
  if (!Number.isFinite(remainingMs)) return { phase: "none", level: "none", text: "--:--", seconds: NaN, limit: null };
  if (remainingMs > 0) {
    const seconds = coarse ? Math.ceil(remainingMs / 60_000) * 60 : Math.ceil(remainingMs / 1000);
    let level = "none";
    let limit = null;
    (Array.isArray(warn) ? warn : []).slice(0, LEVELS.length).forEach((value, index) => {
      if (Number.isFinite(value) && seconds <= value) { level = LEVELS[index]; limit = value; }
    });
    return { phase: "before", level, text: `${MINUS}${fmtSpan(seconds, { dayUnit, coarse })}`, seconds, limit };
  }
  if (after === "stop") return { phase: "done", level: "done", text: "00:00", seconds: 0, limit: null };
  const elapsed = coarse ? Math.floor(-remainingMs / 60_000) * 60 : Math.floor(-remainingMs / 1000);
  return { phase: "over", level: "over", text: `+${fmtSpan(elapsed, { hours: true, dayUnit, coarse })}`, seconds: 0,
    limit: null, elapsed };
}

/** Stoppuhr: „MM:SS“ bzw. „HH:MM:SS“, mit Zehnteln „MM:SS,t“ (decimal = Dezimalzeichen der Sprache). */
export function stopwatchText(elapsedMs, { tenths = false, decimal = ",", dayUnit = "T" } = {}) {
  const ms = Math.max(0, Number.isFinite(elapsedMs) ? elapsedMs : 0);
  const text = fmtSpan(Math.floor(ms / 1000), { dayUnit });
  return tenths ? `${text}${decimal}${Math.floor((ms % 1000) / 100)}` : text;
}

/** Schwellen, an denen der Screenreader den Countdown ansagt (1 min, 10 s, Ziel). */
export const ANNOUNCE_AT = [60, 10, 0];

/**
 * Wurde zwischen zwei Anzeigen eine Ansage-Schwelle erreicht? prev/next: Restsekunden (aufgerundet, nach dem Ziel 0).
 * Liefert die Schwelle (60, 10, 0) oder null. Ohne vorherige Anzeige (Seite neu geladen) nie: Angesagt wird nur ein
 * Übergang, den man gerade erlebt. Wurden mehrere übersprungen (Tab im Hintergrund), gilt die kleinste.
 */
export function announceStep(prev, next) {
  if (!Number.isFinite(prev) || !Number.isFinite(next) || next >= prev) return null;
  let hit = null;
  for (const at of ANNOUNCE_AT) if (prev > at && next <= at) hit = at;   // mehrere übersprungen: die jüngste
  return hit;
}

/** Schwelle lesbar: 300 → „5 min“, 90 → „1 min 30 s“, 10 → „10 s“. */
export function fmtLimit(seconds) {
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return `${seconds} s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m} min ${s} s` : `${m} min`;
}

// --- Timer-Engine (Eieruhr, Stoppuhr) ----------------------------------------------------------
// Zustände: idle (bereit, nichts gelaufen) → running ⇄ paused; reset führt zurück nach idle. Gerechnet wird nur mit
// Differenzen von performance.now(): acc = bisher gelaufene Zeit, start = Moment des letzten Starts.

/** Neuer Timer: duration (ms) für die Eieruhr, null für die Stoppuhr. */
export function timerNew(duration = null) {
  return Object.freeze({ duration: Number.isFinite(duration) && duration > 0 ? duration : null, state: "idle", start: null, acc: 0 });
}

/** Gelaufene Zeit (ms) zum Zeitpunkt now (performance.now()). */
export function timerElapsed(timer, now) {
  if (!timer) return 0;
  if (timer.state !== "running" || !Number.isFinite(now)) return timer.acc;
  return timer.acc + Math.max(0, now - timer.start);
}

/** Leertaste: idle/paused → running, running → paused. */
export function timerToggle(timer, now) {
  if (!timer || !Number.isFinite(now)) return timer;
  if (timer.state === "running") return Object.freeze({ ...timer, state: "paused", start: null, acc: timerElapsed(timer, now) });
  return Object.freeze({ ...timer, state: "running", start: now });
}

/** R: zurück auf Anfang (idle), die Dauer bleibt. */
export function timerReset(timer) {
  return timerNew(timer ? timer.duration : null);
}

/**
 * Stand des Timers: { state, elapsed, remaining } – remaining nur für die Eieruhr (Dauer − gelaufen, darf negativ
 * werden: Überzeit), sonst null.
 */
export function timerRead(timer, now) {
  const elapsed = timerElapsed(timer, now);
  return { state: timer ? timer.state : "idle", elapsed,
    remaining: timer && timer.duration !== null ? timer.duration - elapsed : null };
}

/**
 * Wartezeit (ms) bis zum nächsten Wechsel der Anzeige eines laufenden lokalen Timers: Restzeit wechselt beim
 * Aufrunden auf volle Schritte, die Stoppuhr beim Abrunden. step: 1000 oder 100 (Zehntel). Mindestens 10 ms.
 */
export function timerDelay(read, step = 1000) {
  const value = read.remaining !== null && read.remaining > 0 ? read.remaining : Math.abs(read.remaining ?? read.elapsed);
  const counting = read.remaining !== null && read.remaining > 0;
  const into = ((value % step) + step) % step;
  const wait = counting ? (into || step) : step - into;
  return Math.max(10, Math.round(wait) + 2);
}

/**
 * E-Ink: Wartezeit (ms) bis zum nächsten Bild. Die Anzeige wechselt zur vollen Minute der Serverzeit (nowMs) und – bei
 * laufendem Countdown/Timer mit remainingMs bis zum Ziel – an dessen Minutensprüngen und genau am Ziel. Ohne Ziel
 * (remainingMs nicht endlich) nur zur vollen Minute. Jeweils 5 ms später, damit der Wechsel sicher schon gilt.
 */
export function einkDelay(nowMs, remainingMs = NaN) {
  const minute = 60_000 - (((nowMs % 60_000) + 60_000) % 60_000) + 5;
  if (!Number.isFinite(remainingMs)) return minute;
  return Math.min(minute, timerDelay({ remaining: remainingMs, elapsed: 0 }, 60_000) + 3);
}

// --- Piepen in den letzten Sekunden (?beep=n) über den Tonweg der Uhr ---------------------------
/**
 * Töne für ein Ziel (Serverzeit targetMs): kurze „count“-Töne n … 1 s vorher, ein langer Ton auf dem Ziel. Nur die,
 * die zwischen jetzt (clock.server, höchstens 1 s zurück) und horizonMs voraus liegen und deren Index k (Sekunden vor
 * dem Ziel) kleiner ist als lastK – so plant jeder Takt nur Neues. clock: kit.audioClock(). Ergebnis wie
 * kit.planTones: [{ k, at (Audiozeit s), kind, freq, dur }], k absteigend.
 */
export function planCountdownTones(clock, targetMs, beep, { lastK = Infinity, horizonMs = 1500 } = {}) {
  const out = [];
  if (!clock || !Number.isFinite(targetMs) || !Number.isFinite(clock.server) || !(beep > 0)) return out;
  for (let k = Math.min(beep, 60); k >= 0; k -= 1) {
    if (k >= lastK) continue;
    const at = targetMs - k * 1000;
    if (at < clock.server) continue;   // schon vorbei: nicht nachholen
    if (at > clock.server + horizonMs) break;
    const kind = k === 0 ? "long" : "count";
    out.push({ k, at: clock.audio + (at - clock.server) / 1000, kind, ...BEEP[kind] });
  }
  return out;
}
