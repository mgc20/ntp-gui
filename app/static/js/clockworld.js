// Weltzeit der Studiouhr (B2): reine Funktionen, kein DOM, keine Zeitgeber (Node-Tests in tests/test_uhr_weltzeit.py).
//
// ?tz= nennt bis zu sechs Zeitzonen, ?tzl= dazu Kurznamen in derselben Reihenfolge. Je Zone rechnet die Uhr aus der
// abgeglichenen Serverzeit: Uhrzeit, Abweichung zur groß gezeigten Zeit („+6 h“, „+5:30 h“), Tageswechsel („+1 Tag“) und
// Tag oder Nacht. Der Abstand einer Zone zu UTC wird für genau diesen Zeitpunkt bestimmt (zoneOffset aus clockcount.js,
// Intl-Objekte dort je Zone einmal angelegt) – darum stimmt die Abweichung auch an Umstellungstagen, wenn nur eine der
// beiden Seiten schon umgestellt hat. Tag und Nacht richten sich allein nach der Uhrzeit der Zone (6 bis 18 Uhr), nicht
// nach dem Sonnenstand: Einen Standort kennt die Uhr nicht.
import { MAX_ZONES, LAYOUT_LIMITS, zoneLabel, hourText } from "./clockkit.js";
import { zoneOffset, MINUS } from "./clockcount.js";

export const DAY_MS = 86_400_000;
/** „Tag“ von 6:00 bis 17:59 Uhr der Zone, sonst „Nacht“. */
export const DAY_FROM = 6;
export const DAY_UNTIL = 18;
/** Symbole für Tag und Nacht (mit U+FE0E: als Textzeichen, nicht als buntes Emoji). Die Bedeutung steht im aria-label. */
export const SUN = "☀︎";
export const MOON = "☾︎";
/** Ab dieser Bühnenhöhe (px) darf die Leiste eine Zeile mehr haben (normal zwei, Banner drei). */
export const TWO_LINES_FROM = 420;
/** Schmaler als so viele px passen nur zwei Zonen in eine Zeile: Die Leiste darf dann drei Zeilen haben. */
export const NARROW_BELOW = 720;

const pad = (n) => String(n).padStart(2, "0");
const mod = (a, n) => ((a % n) + n) % n;

/**
 * Zonen mit Beschriftung: [{ zone, label }]. label = Kurzname aus ?tzl= an derselben Stelle, sonst der Ortsteil des
 * Zonennamens („America/New_York“ → „New York“). Ohne Zonen leer; mit fallback (Layout world ohne ?tz=) nur UTC.
 */
export function worldEntries(zones, labels, { fallback = false } = {}) {
  const list = Array.isArray(zones) ? zones.filter((z) => typeof z === "string" && z).slice(0, MAX_ZONES) : [];
  if (!list.length) return fallback ? [{ zone: "UTC", label: "UTC" }] : [];
  const names = Array.isArray(labels) ? labels : [];
  return list.map((zone, index) => ({ zone, label: (typeof names[index] === "string" && names[index]) || zoneLabel(zone) }));
}

/** Lässt ?show= die Weltzeit zu? Ohne ?show= ja, sonst nur mit „tz“ in der Liste. */
export function worldAllowed(show) {
  return !Array.isArray(show) || show.includes("tz");
}

/**
 * Wie die Zonen gezeigt werden: "grid" (Layout world: Raster als Hauptinhalt), "bar" (ab zwei Zonen: Leiste unter der
 * Uhr), "single" (genau eine Zone: wie bisher als zweite Zeitzone in der Zeile unter der Uhr) oder "none" (keine
 * Zonen, oder ?show= nennt „tz“ nicht: allowed = false).
 */
export function worldMode(count, layout, allowed = true) {
  if (!allowed) return "none";
  if (layout === "world") return "grid";
  if (!(count > 0)) return "none";
  return count === 1 ? "single" : "bar";
}

/** Abweichung als Text: „+6 h“, „−5 h“, „+5:30 h“, „+5:45 h“, „±0 h“ (auf ganze Minuten gerundet). */
export function fmtDelta(deltaMs) {
  if (!Number.isFinite(deltaMs)) return "";
  const minutes = Math.round(deltaMs / 60_000);
  if (minutes === 0) return "±0 h";
  const abs = Math.abs(minutes);
  const rest = abs % 60;
  return `${minutes < 0 ? MINUS : "+"}${Math.floor(abs / 60)}${rest ? `:${pad(rest)}` : ""} h`;
}

/**
 * Tageswechsel gegenüber der Bezugszeit: Kalendertag der Zone minus Kalendertag der Bezugszeit (−2 … +2; ±2 gibt es nur
 * zwischen den Rändern der Datumsgrenze, z. B. Baker Island und Kiritimati).
 */
export function dayShift(ms, refOffsetMs, offsetMs) {
  if (![ms, refOffsetMs, offsetMs].every(Number.isFinite)) return 0;
  return Math.floor((ms + offsetMs) / DAY_MS) - Math.floor((ms + refOffsetMs) / DAY_MS);
}

/** Tageswechsel als Text: „+1 Tag“, „−1 Tag“, „+2 Tage“; 0: leer. words: { day, days } in der Sprache der Anzeige. */
export function dayShiftText(shift, { day = "Tag", days = "Tage" } = {}) {
  if (!Number.isInteger(shift) || shift === 0) return "";
  const abs = Math.abs(shift);
  return `${shift < 0 ? MINUS : "+"}${abs} ${abs === 1 ? day : days}`;
}

/** Nacht nach der Uhrzeit der Zone: vor DAY_FROM oder ab DAY_UNTIL. */
export function isNight(hour) {
  return !(hour >= DAY_FROM && hour < DAY_UNTIL);
}

/**
 * Eine Zone zum Zeitpunkt ms. refOffsetMs: Abstand der groß gezeigten Zeit zu UTC (Ortszeit des Geräts, im Design tc
 * die Zone des Servers, nach Taste U 0). offsetOf(ms, zone): Abstand der Zone zu UTC in ms (Standard: Intl).
 * { zone, label, time: "HH:MM", ampm, hour, minute, offsetMs, deltaMs, delta, day, night }. Mit h12 (?h12=1) steht time
 * wie die große Zeit zwölfstündig („01:00“, ampm „PM“), sonst ist ampm leer; hour bleibt die Stunde 0 … 23.
 */
export function worldRow(ms, entry, refOffsetMs = 0, offsetOf = zoneOffset, { h12 = false } = {}) {
  const offsetMs = offsetOf(ms, entry.zone);
  const tod = mod(ms + offsetMs, DAY_MS);
  const hour = Math.floor(tod / 3_600_000);
  const minute = Math.floor((tod % 3_600_000) / 60_000);
  const deltaMs = offsetMs - refOffsetMs;
  const shown = hourText(hour, { h12, lz: true });
  return { zone: entry.zone, label: entry.label, time: `${shown.text}:${pad(minute)}`, ampm: shown.ampm, hour, minute, offsetMs, deltaMs,
    delta: fmtDelta(deltaMs), day: dayShift(ms, refOffsetMs, offsetMs), night: isNight(hour) };
}

/** Alle Zonen zum Zeitpunkt ms (siehe worldRow). */
export function worldView(ms, entries, refOffsetMs = 0, offsetOf = zoneOffset, opts = {}) {
  if (!Number.isFinite(ms) || !Array.isArray(entries)) return [];
  return entries.map((entry) => worldRow(ms, entry, refOffsetMs, offsetOf, opts));
}

/**
 * Raster des Layouts world aus Anzahl und Größe der Bühne: { cols, rows, flow }.
 *   Hochformat (≤ 1:1,6, Stele, Handy): eine Spalte, je Zone eine Zeile (flow "list");
 *   sehr breit (≥ 3:1, Banner): alle Zonen in einer Zeile neben der Uhr (flow "row");
 *   sonst (16:9, 4:3): bis drei Zonen nebeneinander, ab vier in zwei Zeilen – sechs Zonen als 3×2 (flow "grid");
 *   ist die Fläche dabei höher als breit (Handy mit Kopfzeile), höchstens zwei nebeneinander.
 * Mit list: true wie im Hochformat eine Spalte (Stufe von worldSteps, wenn zwei Zellen nicht nebeneinander passen).
 */
export function worldGrid(count, width, height, { list = false } = {}) {
  const n = Math.max(1, Math.min(MAX_ZONES, Math.floor(Number(count)) || 1));
  const w = Number(width);
  const h = Number(height);
  const ratio = w > 0 && h > 0 ? w / h : 16 / 9;
  if (list || ratio <= LAYOUT_LIMITS.columnRatio) return { cols: 1, rows: n, flow: "list" };
  if (ratio >= LAYOUT_LIMITS.bannerRatio) return { cols: n, rows: 1, flow: "row" };
  const cols = ratio < 1 ? Math.min(n, 2) : (n <= 3 ? n : Math.ceil(n / 2));
  return { cols, rows: Math.ceil(n / cols), flow: "grid" };
}

/**
 * Höchstzahl der Zeilen, die die Leiste unter der Uhr belegen darf (was nicht passt, blendet clock.js aus):
 * Streifen und Kachel 0 (keine Leiste), Spalte je Zone eine Zeile, Banner zwei (ab TWO_LINES_FROM px Bühnenhöhe
 * drei – die Leiste steht dort in der schmalen rechten Spalte), normal eine (ab TWO_LINES_FROM px zwei, auf schmalen
 * Flächen unter NARROW_BELOW px Breite drei).
 */
export function worldLines(layout, height, count, width = Infinity) {
  const n = Math.max(0, Math.min(MAX_ZONES, Math.floor(Number(count)) || 0));
  if (!n || layout === "strip" || layout === "tile") return 0;
  if (layout === "column") return n;
  const tall = Number(height) >= TWO_LINES_FROM;
  if (layout === "banner") return Math.min(n, tall ? 3 : 2);
  return Math.min(n, tall ? (Number(width) < NARROW_BELOW ? 3 : 2) : 1);
}

/**
 * Stufen, in denen das Raster eingepasst wird: [{ shown, dense, list }]. Erst alle Zonen – mehrzeilige Zellen, dann
 * einzeilige (dense); ist die Fläche höher als breit, aber noch kein Hochformat (Handy mit Kopfzeile), jeweils danach
 * als eine Spalte (list). Erst wenn nichts davon passt, fallen Zonen vom Ende her weg (einzeilig).
 */
export function worldSteps(total, width, height) {
  const n = Math.max(1, Math.min(MAX_ZONES, Math.floor(Number(total)) || 1));
  const ratio = Number(width) > 0 && Number(height) > 0 ? Number(width) / Number(height) : 16 / 9;
  const column = ratio < 1 && ratio > LAYOUT_LIMITS.columnRatio;
  const steps = [];
  const add = (shown, dense) => {
    steps.push({ shown, dense, list: false });
    if (column) steps.push({ shown, dense, list: true });
  };
  add(n, false);
  for (let shown = n; shown > 0; shown -= 1) add(shown, true);
  return steps;
}

/**
 * Zeilen, die Boxen [{ top, bottom }] belegen: Eine neue Zeile beginnt erst, wenn eine Box unter der Mitte der
 * laufenden Zeile anfängt. Der Hinweis „+2“ (kleinere Schrift, an der Grundlinie ausgerichtet) steht ein paar Pixel
 * tiefer als die Zellen daneben und zählt so nicht als eigene Zeile.
 */
export function lineCount(boxes) {
  const list = (Array.isArray(boxes) ? boxes : []).filter((b) => b && Number.isFinite(b.top) && Number.isFinite(b.bottom))
    .sort((a, b) => a.top - b.top);
  let lines = 0;
  let line = null;
  for (const box of list) {
    if (!line || box.top >= (line.top + line.bottom) / 2) {
      lines += 1;
      line = box;
    }
  }
  return lines;
}

/**
 * Faktoren, mit denen die Leiste freie Höhe nutzen darf (größter zuerst, clock.js nimmt den ersten, der passt): bis
 * ihre Schrift ein Fünftel der Zeithöhe erreicht, höchstens BAR_GROW_MAX. Leer, wenn sie schon so groß ist.
 */
export const BAR_GROW_MAX = 1.8;
export const BAR_GROW_SHARE = 0.2;
export function barGrowSteps(timeHeight, fontPx) {
  if (!(timeHeight > 0) || !(fontPx > 0)) return [];
  const limit = Math.min(BAR_GROW_MAX, (timeHeight * BAR_GROW_SHARE) / fontPx);
  if (!(limit >= 1.08)) return [];
  return [1, 2 / 3, 1 / 3].map((part) => Math.round((1 + (limit - 1) * part) * 1000) / 1000);
}
