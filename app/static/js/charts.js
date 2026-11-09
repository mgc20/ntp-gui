// SVG-Diagramme ohne Bibliothek: Linien (mehrere Serien), Himmelskarte, Balken.
import { el, svgEl, isNum, fmtNumber, storageGet, storageSet } from "./util.js";
import { infoButton } from "./ui.js";
import { t as tr } from "./i18n.js";

// Quellenfarben (T2 „Seiten entschlacken“): fest je Quelle, gleich in allen Diagrammen. Die Farbe hängt
// allein am Namen der Quelle (FNV-1a-Hash → Platz in der Palette), nicht an ihrer Reihenfolge und nicht an
// den anderen Quellen im Diagramm – nach einem Neuladen, auf einer anderen Seite, bei einem anderen
// Zeitraum oder in einem anderen Browser hat dieselbe Quelle dieselbe Farbe. Teilen sich zwei Quellen eines
// Diagramms eine Farbe, unterscheidet sie die Strichelung (nur die bleibt von der Menge abhängig).
// Je Thema eigene Stufen, alle mit mindestens 3:1 Kontrast zum Diagrammhintergrund (--surface,
// tests/test_seiten.py prüft das). Rot und Gelb fehlen bewusst: Sie bedeuten „kritisch“ und „Warnung“.
export const SERIES_PALETTE = {
  light: ["#2a78d6", "#c4511f", "#13865c", "#a36b00", "#c2457a", "#0f7c8c", "#8a5a2b", "#57606a"],
  dark: ["#3987e5", "#e0753f", "#2bb383", "#d19a1c", "#e0699a", "#2fb3c4", "#c08a55", "#8b949e"],
};
// GPS, PPS und andere Referenzuhren (chrony-refclock) haben immer dieselbe Signalfarbe, die keine
// Netzquelle bekommt.
export const SIGNAL_COLOR = { light: "#8250df", dark: "#b392f0" };
// Hintergrund der Diagramme (Karte, --surface in app.css) – Bezug für den Kontrasttest.
export const CHART_BACKGROUND = { light: "#ffffff", dark: "#151b23" };

const SIGNAL_NAME = /^(gps|pps|nmea|gnss|shm|phc|sock)\d*$/i;

/** Referenzuhr (GPS, PPS, NMEA, SHM, PHC …)? Erkannt am Namen bzw. an series.signal. */
export function isSignalSource(name) {
  return SIGNAL_NAME.test(String(name ?? "").trim());
}

/** FNV-1a (32 bit) über den Namen – stabil, schnell, ohne Zufall. */
export function hashName(name) {
  let hash = 0x811c9dc5;
  for (const char of String(name ?? "").toLowerCase()) {
    hash ^= char.codePointAt(0);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

// Strichmuster für Quellen, die sich im selben Diagramm eine Farbe teilen (Stufe 1, 2, 3 …).
const DASHES = [null, "6 4", "2 3", "8 3 2 3"];

/**
 * Stufen der Strichelung für eine Menge von Quellen (Map Name → Stufe, 0 = durchgezogen). Die Farbe
 * bleibt der Hash-Platz; nur wenn mehrere Quellen dieser Menge denselben Platz haben, bekommen alle außer
 * der ersten (nach Name) eine Strichelung. Das Ergebnis hängt nur von der Menge ab, nicht von ihrer
 * Reihenfolge.
 */
export function assignSlots(ids) {
  const size = SERIES_PALETTE.light.length;
  const unique = [...new Set(ids.map(String))].filter((id) => !isSignalSource(id)).sort();
  const slots = new Map();
  const seen = new Map();
  for (const id of unique) {
    const slot = hashName(id) % size;
    const level = seen.get(slot) || 0;
    seen.set(slot, level + 1);
    slots.set(id, level);
  }
  return slots;
}

function themeName() {
  return document.documentElement?.dataset?.theme === "light" ? "light" : "dark";
}

/**
 * Farbe einer Quelle: immer der Hash-Platz ihres Namens. slots: Ergebnis von assignSlots für alle Quellen
 * eines Diagramms – bestimmt nur die Strichelung bei gleicher Farbe (ohne: durchgezogen).
 * theme: "light" | "dark" (Standard: aktuelles Thema).
 */
export function colorFor(id, slots = null, theme = themeName()) {
  // PPS neben GPS im selben Diagramm: gleiche Signalfarbe, aber gestrichelt.
  if (isSignalSource(id)) {
    const pps = /^pps/i.test(String(id));
    return { color: SIGNAL_COLOR[theme], dashed: pps, dash: pps ? DASHES[1] : null, signal: true };
  }
  const size = SERIES_PALETTE.light.length;
  const level = (slots && slots.get(String(id))) || 0;
  const dash = level ? DASHES[((level - 1) % (DASHES.length - 1)) + 1] : null;
  return { color: SERIES_PALETTE[theme][hashName(id) % size], dashed: Boolean(dash), dash, signal: false };
}

// --- Kurznamen für Linien-Endbeschriftungen ----------------------------------------
const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;
const HOSTNAME = /^(?=.*[a-z])[a-z0-9_-]+(\.[a-z0-9_-]+)+\.?$/i;
// Allerweltsnamen vorn („time.cloudflare.com“, „ntp1.example.net“): dann zählt der nächste Teil.
const GENERIC_LABEL = /^(time\d*|ntp\d*|clock\d*|tick|tock|pool|zeit|sntp|nts\d*|\d+)$/i;
export const SHORT_MAX = 14;

export function isIpAddress(text) {
  const value = String(text ?? "").replace(/^\[|\]$/g, "");
  return IPV4.test(value) || (value.includes(":") && /^[0-9a-f:.]+$/i.test(value));
}

function clip(text, max = SHORT_MAX) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/**
 * Kurzname für eine Linien-Endbeschriftung: IP-Adressen bleiben unverändert, Hostnamen ohne Domain
 * („ptbtime1.ptb.de“ → „ptbtime1“; „time.cloudflare.com“ → „cloudflare“), sonst gekürzt auf SHORT_MAX.
 */
export function shortName(name) {
  const value = String(name ?? "").trim();
  if (!value || isIpAddress(value)) return value;
  if (!HOSTNAME.test(value)) return clip(value);
  const labels = value.replace(/\.$/, "").split(".");
  const parts = labels.length > 1 ? labels.slice(0, -1) : labels;   // ohne Top-Level-Domain
  const pick = parts.find((part) => !GENERIC_LABEL.test(part)) || parts[0];
  return clip(pick);
}

// Gemeinsames Ende mehrerer Namen, nur an einer Grenze (Punkt oder Bindestrich), damit der
// unterscheidende Teil ganz bleibt („x1.a.org“/„y1.a.org“ → „.a.org“, nicht „1.a.org“).
function commonTail(names) {
  let n = 0;
  const min = Math.min(...names.map((x) => x.length));
  while (n < min && names.every((x) => x[x.length - 1 - n] === names[0][names[0].length - 1 - n])) n += 1;
  const tail = names[0].slice(names[0].length - n);
  const cut = tail.search(/[.-]/);
  return cut < 0 ? 0 : tail.length - cut;
}

// Kürzen in der Mitte: Anfang und Ende bleiben sichtbar („abcdefgh…qrstuvwxyz-1“).
function clipMiddle(text, max) {
  if (text.length <= max) return text;
  const head = Math.ceil((max - 1) * 0.4);
  return `${text.slice(0, head)}…${text.slice(text.length - (max - 1 - head))}`;
}

/**
 * Kurznamen für alle Linien eines Diagramms (Map Name → Kurzname), immer eindeutig. Ergäben zwei
 * Hostnamen denselben Kurznamen, behalten beide mehr vom Namen (ohne Top-Level-Domain). Bleibt es gleich,
 * fällt das gemeinsame Ende weg und gekürzt wird in der Mitte, damit der unterscheidende Teil sichtbar
 * bleibt; als Letztes hilft eine laufende Nummer.
 */
export function shortNames(names) {
  const LONG = 22;
  const list = [...new Set(names.map(String))];
  const groups = (map) => {
    const by = new Map();
    for (const [name, short] of map) by.set(short, [...(by.get(short) || []), name]);
    return [...by.values()].filter((g) => g.length > 1);
  };
  const out = new Map(list.map((n) => [n, shortName(n)]));
  for (const group of groups(out)) {
    for (const name of group) {
      if (!HOSTNAME.test(name) || isIpAddress(name)) continue;
      const labels = name.replace(/\.$/, "").split(".");
      out.set(name, clip(labels.slice(0, Math.max(1, labels.length - 1)).join("."), LONG));
    }
  }
  for (const group of groups(out)) {
    const cut = commonTail(group);
    for (const name of group) {
      if (isIpAddress(name)) continue;
      const rest = cut && cut < name.length ? name.slice(0, name.length - cut) : name;
      out.set(name, clipMiddle(rest, LONG));
    }
  }
  for (const group of groups(out)) {
    group.slice(1).forEach((name, i) => out.set(name, `${clip(out.get(name), LONG - 3)} ${i + 2}`));
  }
  return out;
}

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// SVG-Attribute kennen kein var(--x): Variablen vorher auflösen.
function resolve(color) {
  const match = /^var\((--[\w-]+)\)$/.exec(color || "");
  return match ? css(match[1]) || color : color;
}

function seriesColor(series, slots = null) {
  if (series.color) return { color: resolve(series.color), dashed: false, dash: null };
  return series.signal && !isSignalSource(series.id) ? colorFor("GPS", null) : colorFor(series.id, slots);
}

function niceStep(span, count = 5) {
  if (!(span > 0)) return 1;
  const raw = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalised = raw / magnitude;
  // Aufrunden: höchstens `count` Abschnitte, sonst wird die Achse zu dicht beschriftet.
  return (normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10) * magnitude;
}

// --- Hilfen für Zeitachse, Skalierung und Statistik ---------------------------

let uid = 0;
// Diagramme, die ihren Auftritt schon hatten: Die Seite baut alle paar Sekunden
// neu auf – die Einblendung soll nur beim ersten Mal laufen, nicht bei jeder Aktualisierung.
const REVEALED = new Set();
// Fadenkreuz über das Neuzeichnen hinweg halten (Schlüssel → Zeitpunkt).
const HOVER = new Map();

/** Beim Seitenwechsel aufrufen: gemerktes Fadenkreuz gehört zur alten Seite. */
export function resetChartState() {
  HOVER.clear();
}

const pad2 = (n) => String(n).padStart(2, "0");

function tzOffset(t) {
  return -new Date(t * 1000).getTimezoneOffset() * 60;
}

function fmtClock(t, withSeconds = false) {
  const d = new Date(t * 1000);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}${withSeconds ? `:${pad2(d.getSeconds())}` : ""}`;
}

function fmtDay(t) {
  const d = new Date(t * 1000);
  return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.`;
}

/** Zeitpunkt für Tooltips: Uhrzeit, bei anderem Tag oder langem Zeitraum mit Datum. */
export function fmtStamp(t, span = 0) {
  const sameDay = new Date(t * 1000).toDateString() === new Date().toDateString();
  return `${sameDay && span <= 86400 ? "" : `${fmtDay(t)} `}${fmtClock(t, span < 3600)}`;
}

const TIME_STEPS = [60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 14400, 21600, 28800, 43200, 86400, 172800, 604800];

// Ticks auf „runden“ Ortszeiten (volle 5 min, volle Stunde, Mitternacht …).
// Ab Stundenschritten wird jeder Tick in Ortszeit gezählt – so bleiben die
// Ticks auch über eine Sommer-/Winterzeit-Umstellung auf vollen Stunden.
function timeTicks(t0, t1, maxTicks) {
  const span = t1 - t0;
  const step = TIME_STEPS.find((s) => span / s <= maxTicks) || TIME_STEPS[TIME_STEPS.length - 1];
  const ticks = [];
  if (step < 3600) {
    const tz = tzOffset(t0);
    for (let t = Math.ceil((t0 + tz) / step) * step - tz; t <= t1; t += step) ticks.push(t);
    return { ticks, step };
  }
  const d = new Date(t0 * 1000);
  d.setMinutes(0, 0, 0);
  if (step >= 86400) {
    const days = step / 86400;
    d.setHours(0);
    while (d.getTime() / 1000 < t0) d.setDate(d.getDate() + 1);
    for (let n = 0; d.getTime() / 1000 <= t1 && n < 200; n += 1) { ticks.push(d.getTime() / 1000); d.setDate(d.getDate() + days); }
    return { ticks, step };
  }
  const hours = step / 3600;
  d.setHours(Math.ceil(d.getHours() / hours) * hours);
  while (d.getTime() / 1000 < t0) d.setHours(d.getHours() + hours);
  for (let n = 0; d.getTime() / 1000 <= t1 && n < 400; n += 1) {
    ticks.push(d.getTime() / 1000);
    const before = d.getTime();
    d.setHours(d.getHours() + hours);
    // Umstellung: auf das nächste Vielfache der Schrittweite zurückrücken
    const off = d.getHours() % hours;
    if (off) d.setHours(d.getHours() - off);
    if (d.getTime() <= before) d.setTime(before + step * 1000);
  }
  return { ticks, step };
}

function timeLabel(t, step, span) {
  const d = new Date(t * 1000);
  const midnight = d.getHours() === 0 && d.getMinutes() === 0;
  if (span > 86400 && (midnight || step >= 86400)) return fmtDay(t);
  return fmtClock(t, step < 60);
}

function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.min(sorted.length - 1, lo + 1);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function extent(values) {
  let min = Infinity; let max = -Infinity;
  for (const v of values) { if (v < min) min = v; if (v > max) max = v; }
  return [min, max];
}

/**
 * Robuster Wertebereich: Einzelne Ausreißer (etwa die Startspitze von chrony)
 * sollen den Rest nicht plattdrücken. Der Zaun liegt sechs robuste
 * Standardabweichungen (aus MAD bzw. 10.–90.-Perzentil) um den Median.
 * Abgeschnitten wird nur, wenn
 *  - es höchstens 8 % der Punkte sind,
 *  - die jüngsten Werte (`keep`) liegen immer im Bereich – ein echter, neuer
 *    Pegelsprung bleibt also sichtbar,
 *  - der Kern überhaupt eine Streuung hat (sonst wären bei „fast immer 0“ alle
 *    echten Werte Ausreißer),
 *  - und der Rest dadurch spürbar mehr Platz bekommt.
 */
export function robustRange(values, enabled = true, keep = []) {
  const sorted = values.filter(isNum).sort((a, b) => a - b);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const out = { min, max, lo: min, hi: max, clippedHi: false, clippedLo: false };
  if (!enabled || sorted.length < 12) return out;
  const median = quantile(sorted, 0.5);
  const deviations = sorted.map((v) => Math.abs(v - median)).sort((a, b) => a - b);
  const spread = Math.max(1.4826 * quantile(deviations, 0.5), (quantile(sorted, 0.9) - quantile(sorted, 0.1)) / 2.56);
  if (!(spread > 0)) return out;
  const fenceLo = median - 6 * spread;
  const fenceHi = median + 6 * spread;
  let first = -1; let last = -1;
  for (let i = 0; i < sorted.length; i += 1) {
    if (sorted[i] >= fenceLo && sorted[i] <= fenceHi) { if (first < 0) first = i; last = i; }
  }
  if (first < 0 || last - first < 1) return out;
  if (sorted.length - (last - first + 1) > sorted.length * 0.08) return out;
  // Die jüngsten Werte bleiben immer im Bild – ein echter neuer Sprung wird so nie versteckt
  // (dann lohnt sich das Abschneiden unten meist nicht mehr).
  let lo = sorted[first];
  let hi = sorted[last];
  for (const v of keep) if (isNum(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  if ((max - min) < 1.8 * (hi - lo || spread)) return out;
  return { min, max, lo, hi, clippedHi: max > hi, clippedLo: min < lo };
}

/** Kennzahlen über die sichtbaren (nicht abgeschnittenen) Werte. */
function statsOf(points, range) {
  let sum = 0; let n = 0; let min = Infinity; let max = -Infinity; let now = null;
  for (const [, v] of points) {
    if (!isNum(v)) continue;
    now = v;
    if (range && (v < range.lo || v > range.hi)) continue;
    sum += v; n += 1;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (n < 2) return null;
  return { now, min, max, mean: sum / n, count: n };
}

// Lücken: fehlen Messpunkte deutlich länger als üblich, reißt die Linie ab.
function gapLimit(times) {
  const deltas = [];
  for (let i = 1; i < times.length; i += 1) deltas.push(times[i] - times[i - 1]);
  return Math.max(quantile(deltas.sort((a, b) => a - b), 0.5) * 3.5, 30);
}

function findGaps(times) {
  if (times.length < 3) return [];
  const limit = gapLimit(times);
  const gaps = [];
  for (let i = 1; i < times.length; i += 1) {
    if (times[i] - times[i - 1] > limit) gaps.push([times[i - 1], times[i]]);
  }
  return gaps;
}

function inGap(gaps, a, b) {
  return gaps.some(([g0, g1]) => a <= g0 && b >= g1);
}

function emptyState(svg, width, height, text, loading) {
  for (let i = 1; i <= 3; i += 1) {
    svg.append(svgEl("line", { x1: 16, x2: width - 16, y1: (height / 4) * i, y2: (height / 4) * i, class: "chart-grid" }));
  }
  const group = svgEl("g", { class: loading ? "chart-empty is-loading" : "chart-empty" });
  const pill = Math.min(width - 32, Math.max(220, text.length * 7.2 + 40));
  group.append(svgEl("rect", { x: width / 2 - pill / 2, y: height / 2 - 18, width: pill, height: 36, rx: 18, class: "chart-empty-pill" }));
  const label = svgEl("text", { x: width / 2, y: height / 2 + 4.5, "text-anchor": "middle", class: "chart-empty-text" });
  label.textContent = text;
  group.append(label);
  svg.append(group);
}

const defaultFormat = (v) => fmtNumber(v, 0, { sig: 4 });

/** Zeile über dem Diagramm: aktueller Wert groß, daneben Min · Max · Mittel. */
export function statsHeader(stats, format, clip, opts) {
  const item = (label, value, title) => el("span", { class: "chart-stat", title: title || null },
    el("span", { class: "chart-stat-label", text: label }), el("b", { text: value }));
  const current = isNum(opts.current) ? opts.current : stats.now;
  return el("div", { class: "chart-stats" },
    el("span", { class: "chart-now" }, el("span", { class: "chart-stat-label", text: opts.nowLabel || (isNum(opts.current) ? "jetzt" : "letzter Wert") }),
      el("b", { text: isNum(current) ? format(current) : "–" })),
    el("span", { class: "chart-stat-group" },
      item("min", format(stats.min)), item("max", format(stats.max)), item("Ø", format(stats.mean), "Mittelwert im Zeitraum")),
    liveOutside(opts.current, stats, format)
      ? el("span", { class: "chart-scale-note", title: "Der Verlauf speichert Mittelwerte je Zeitabschnitt, „jetzt“ ist der Rohwert.",
        text: "min/max aus Mittelwerten" }) : null,
    clip ? clipChip(clip) : null,
    opts.scale === "log" ? el("span", { class: "chart-scale-note", text: "log. Skala" }) : null,
    infoButton("chart_stats", "Werte über dem Diagramm"));
}

// Nur ein übergebener Live-Wert („jetzt“) kann außerhalb der gemittelten Verlaufswerte liegen – der
// Rückfall auf den letzten Punkt nicht (liegt der außerhalb, ist er als Spitze abgeschnitten). Was
// gleich angezeigt wird, gilt nicht als außerhalb.
function liveOutside(current, stats, format) {
  if (!isNum(current)) return false;
  if (current > stats.max) return format(current) !== format(stats.max);
  if (current < stats.min) return format(current) !== format(stats.min);
  return false;
}

function clipChip(clip) {
  return el("span", { class: "chart-clip-note",
    title: "Spitzen sind abgeschnitten, damit der normale Verlauf lesbar bleibt. Min, Max und Ø zählen sie nicht mit – der Tooltip zeigt den echten Wert." },
  el("span", { "aria-hidden": "true", text: `${clip.up ? "⤒" : "⤓"} ` }), clip.text);
}

// Gemeinsame Einheit der Achsenbeschriftung („0,5 µs“, „1,0 µs“ → „µs“ einmal oben).
function splitUnit(labels) {
  let unit = null;
  const numbers = [];
  for (const label of labels) {
    const match = /^(.*[\d])\s+([^\d\s]+)$/.exec(label);
    if (!match || (unit !== null && match[2] !== unit)) return { unit: null, labels };
    unit = match[2];
    numbers.push(match[1]);
  }
  return unit ? { unit, labels: numbers } : { unit: null, labels };
}

// --- Ereignismarker (1.6, T7) -----------------------------------------------------------------------
// Jedes Zeitdiagramm (lineChart) zeigt Ereignisse aus dem Protokoll als dünne senkrechte Linie mit einem
// Symbol darüber: Quellenwechsel, GPS-Ausfall, Neustart, Pi-Spannung, übrige Warnungen. Die Marker liefert
// /api/timeline/markers (app.js setzt sie mit setChartMarkers für die ganze Seite). Liegen Ereignisse enger als
// eine Tippfläche beieinander, werden sie zu einem Marker mit Anzahl zusammengefasst – bei vielen Ereignissen
// bleibt das Diagramm ruhig. Die Symbole sind echte Knöpfe (Tab erreicht sie, Enter/Fokus zeigt den Text);
// welche Arten erscheinen, merkt sich der Browser (markerFilterControl).
export const MARKER_GROUPS = [
  { id: "source", glyph: "⇄" },
  { id: "gps", glyph: "◎" },
  { id: "restart", glyph: "↻" },
  { id: "pi", glyph: "π" },
  { id: "warn", glyph: "!" },
];
const MARKER_FILTER_KEY = "ntp-gui-marker-filter";
export const MARKER_GAP = 26;   // px – enger beieinander → ein Marker mit Anzahl (Tippfläche 24 px)
const MARKER_TIP_MAX = 6;       // so viele Titel im Tooltip, der Rest als „und n weitere“
const LEVEL_ORDER = { info: 0, warn: 1, crit: 2 };
let CHART_MARKERS = [];

/** Marker für alle Diagramme der Seite setzen (Liste aus /api/timeline/markers). */
export function setChartMarkers(list) {
  CHART_MARKERS = Array.isArray(list) ? list.filter((m) => m && isNum(m.t)) : [];
}

/** Ausgeblendete Arten (Set der ids) – je Browser gemerkt. */
export function hiddenMarkerGroups() {
  const stored = storageGet(MARKER_FILTER_KEY, []);
  return new Set(Array.isArray(stored) ? stored.filter((id) => MARKER_GROUPS.some((g) => g.id === id)) : []);
}

export function markerGlyph(group) {
  return (MARKER_GROUPS.find((g) => g.id === group) || MARKER_GROUPS[MARKER_GROUPS.length - 1]).glyph;
}

export function markerGroupLabel(group) {
  return tr(`pages.timeline.group.${MARKER_GROUPS.some((g) => g.id === group) ? group : "warn"}`);
}

/** Marker im Zeitraum [t0, t1] ohne ausgeblendete Arten, zeitlich sortiert. */
export function visibleMarkers(list, t0, t1, hidden = hiddenMarkerGroups()) {
  return (list || []).filter((m) => m && isNum(m.t) && m.t >= t0 && m.t <= t1 && !hidden.has(m.group))
    .sort((a, b) => a.t - b.t);
}

/**
 * Marker zu Gruppen zusammenfassen: Liegt ein Marker näher als gap Pixel am vorigen Haufen, gehört er dazu.
 * X: Zeit → Pixel. Ergebnis: [{ x (Mitte), t (erster), items, group (Art des schwersten), level (schwerste Stufe) }].
 * Reine Funktion (in Node getestet).
 */
export function clusterMarkers(list, X, gap = MARKER_GAP) {
  const clusters = [];
  for (const m of [...list].sort((a, b) => a.t - b.t)) {
    const x = X(m.t);
    const last = clusters[clusters.length - 1];
    if (last && x - last.x1 < gap) {
      last.items.push(m); last.x1 = x;
    } else {
      clusters.push({ x0: x, x1: x, items: [m] });
    }
  }
  return clusters.map((c) => {
    let worst = c.items[0];
    for (const m of c.items) if ((LEVEL_ORDER[m.level] || 0) > (LEVEL_ORDER[worst.level] || 0)) worst = m;
    return { x: (c.x0 + c.x1) / 2, t: c.items[0].t, items: c.items, group: worst.group, level: worst.level || "info" };
  });
}

function markerText(cluster, stamp) {
  const titles = cluster.items.slice(0, MARKER_TIP_MAX).map((m) => `${stamp(m.t)} ${m.title}`);
  const more = cluster.items.length - MARKER_TIP_MAX;
  if (more > 0) titles.push(tr("pages.timeline.marker_more", { count: more }));
  return titles;
}

/**
 * Marker-Knöpfe über einer Fläche (Diagramm oder Zustandsband) – Linien zeichnet der Aufrufer selbst.
 * host: Element mit position: relative. opts: { clusters, width (Bezugsbreite der x-Werte), top (y-Mitte der
 * Knöpfe in Prozent der Höhe von host), stamp(t) → Uhrzeit, key (Fokus-Schlüssel), onActivate(cluster) –
 * Enter/Klick (Standard: Text zeigen), tipTop – y des Tooltips in Prozent }.
 */
export function markerButtons(host, opts) {
  const tip = el("div", { class: "tooltip chart-event-tip", hidden: true, "aria-hidden": "true" });
  let shown = null;
  const hide = () => { tip.hidden = true; shown = null; };
  const show = (cluster, x) => {
    shown = cluster;
    tip.replaceChildren(...markerText(cluster, opts.stamp).map((line) => el("div", { class: "tt-row chart-event-row", text: line })));
    const left = (x / opts.width) * 100;
    // An der Seite mit mehr Platz verankern: rechts vom Marker mit „left“, links davon mit „right“. So bemisst der
    // Browser die Breite nach dem Platz auf dieser Seite (mindestens die halbe Fläche) – mit „left“ + translate
    // schrumpfte der Tooltip am rechten Rand auf wenige Pixel und brach Zeichen für Zeichen um.
    const leftSide = left > 50;
    tip.style.left = leftSide ? "auto" : `${left}%`;
    tip.style.right = leftSide ? `${100 - left}%` : "auto";
    tip.style.top = `${opts.tipTop ?? 0}%`;
    tip.style.transform = leftSide ? "translate(-14px, 0)" : "translate(14px, 0)";
    tip.hidden = false;
  };
  for (const cluster of opts.clusters) {
    const lines = markerText(cluster, opts.stamp);
    const count = cluster.items.length;
    const label = `${markerGroupLabel(cluster.group)}${count > 1 ? ` (${tr("pages.timeline.events_count", { count })})` : ""}: ${lines.join("; ")}`;
    const button = el("button", { type: "button", class: "chart-event", "data-group": cluster.group, "data-level": cluster.level,
      "aria-label": label, "data-focus-key": `marker:${opts.key}:${cluster.t}` },
    el("span", { class: "chart-event-glyph", "aria-hidden": "true", text: count > 1 ? String(Math.min(count, 99)) : markerGlyph(cluster.group) }));
    button.style.left = `${(cluster.x / opts.width) * 100}%`;
    button.style.top = `${opts.top}%`;
    button.addEventListener("pointerenter", () => show(cluster, cluster.x));
    button.addEventListener("pointerleave", (event) => { if (event.pointerType === "mouse" && document.activeElement !== button) hide(); });
    button.addEventListener("focus", () => show(cluster, cluster.x));
    button.addEventListener("blur", () => hide());
    button.addEventListener("keydown", (event) => { if (event.key === "Escape" && shown) { event.stopPropagation(); hide(); } });
    button.addEventListener("click", () => {
      if (opts.onActivate) opts.onActivate(cluster, button);
      else if (shown === cluster) hide(); else show(cluster, cluster.x);
    });
    host.append(button);
  }
  host.append(tip);
}

/**
 * Filter nach Art: eine Reihe Umschaltknöpfe (aria-pressed) mit Symbol und Namen. Gilt für alle Diagramme und
 * das Zustandsband; onChange() zeichnet neu.
 */
export function markerFilterControl(onChange) {
  const hidden = hiddenMarkerGroups();
  return el("div", { class: "marker-filter", role: "group", "aria-label": tr("pages.timeline.filter_label") },
    MARKER_GROUPS.map((group) => {
      const on = !hidden.has(group.id);
      return el("button", { type: "button", class: `range marker-toggle${on ? " is-active" : ""}`, "data-group": group.id,
        "aria-pressed": on ? "true" : "false", "data-focus-key": `marker-filter:${group.id}`,
        onclick: () => {
          const now = hiddenMarkerGroups();
          if (now.has(group.id)) now.delete(group.id); else now.add(group.id);
          storageSet(MARKER_FILTER_KEY, [...now]);
          if (onChange) onChange();
        } },
      el("span", { class: "chart-event-glyph", "data-group": group.id, "aria-hidden": "true", text: group.glyph }),
      markerGroupLabel(group.id));
    }), infoButton("chart_markers", tr("pages.timeline.filter_label")));
}

/**
 * Liniendiagramm (eine y-Achse, Zeit auf x).
 * opts: { series: [{id, label, color?, points: [[t, v], ...]}], format(v), axisFormat(v, step, extent),
 *         height, zeroLine, min, minSpan, emptyText, loading, hidden: Set, onToggle(id), ariaLabel,
 *         area (Standard: an bei einer Serie), stats (Standard: an bei einer Serie),
 *         current – Live-Wert für „jetzt“ (sonst „letzter Wert“ aus dem Verlauf), nowLabel,
 *         range, end – x-Achse = gewählter Zeitraum bis jetzt (sonst: so weit die Daten reichen),
 *         robust (Standard: an) – Ausreißer abschneiden, scale: "linear" | "log",
 *         bands: [{from, to, tone: "warn"|"crit"|"good", label}] – Schwellen, nur wenn im Bild,
 *         events – eigene Marker (Standard: die der Seite, setChartMarkers), false = keine }
 */
export function lineChart(container, opts) {
  const height = opts.height || 220;
  const width = Math.max(300, container.clientWidth || 640);
  const hidden = opts.hidden || new Set();
  const log = opts.scale === "log";
  const usable = (v) => isNum(v) && (!log || v > 0);
  const visible = opts.series.filter((s) => !hidden.has(s.id) && s.points.some((p) => usable(p[1])));
  const single = opts.series.length === 1;
  const key = `${window.location.hash}|${opts.key || opts.series.map((s) => s.id).join("|")}`;
  const format = opts.format || defaultFormat;
  const axisFormat = opts.axisFormat || format;
  const title = opts.ariaLabel || "Verlaufsdiagramm";
  // Farben je Quelle fest (Hash des Namens); teilen sich zwei Quellen hier eine Farbe, unterscheidet sie die Strichelung.
  const slots = assignSlots(opts.series.filter((s) => !s.color && !s.signal).map((s) => s.id));
  container.replaceChildren();
  container.classList.add("chart-host");

  // Kopfzeile mit Kennzahlen (eine Serie) bzw. Legende (mehrere Serien)
  const all = [];
  const keep = [];
  for (const s of visible) {
    let tail = 0;
    for (const p of s.points) if (usable(p[1])) all.push(p);
    for (let i = s.points.length - 1; i >= 0 && tail < 3; i -= 1) if (usable(s.points[i][1])) { keep.push(s.points[i][1]); tail += 1; }
  }
  const range = log ? null : robustRange(all.map((p) => p[1]), opts.robust !== false, keep);
  if (opts.series.length > 1) {
    const legend = el("div", { class: "legend", role: "group", "aria-label": "Serien ein- und ausblenden" });
    for (const series of opts.series) {
      const { color, dashed } = seriesColor(series, slots);
      const off = hidden.has(series.id);
      legend.append(el("button", {
        type: "button", class: `legend-item${off ? " is-off" : ""}`, "data-focus-key": `legend:${key}:${series.id}`,
        "aria-pressed": off ? "false" : "true", title: off ? "einblenden" : "ausblenden",
        onclick: () => opts.onToggle && opts.onToggle(series.id),
      }, el("span", { class: `swatch${dashed ? " dashed" : ""}`, style: `--c:${color}` }), series.label));
    }
    container.append(legend);
  }
  const clipped = range && (range.clippedHi || range.clippedLo);
  const stats = all.length >= 2 && visible.length === 1 && opts.stats !== false && (single || opts.stats)
    ? statsOf(visible[0].points.filter((p) => usable(p[1])), clipped ? range : null) : null;
  let clip = null;
  if (clipped) {
    const up = range.clippedHi && (!range.clippedLo || Math.abs(range.max) >= Math.abs(range.min));
    clip = { up, text: `Spitze ${format(up ? range.max : range.min)} ausgeblendet` };
  }
  if (stats) container.append(statsHeader(stats, format, clip, opts));
  else if (clip) container.append(el("div", { class: "chart-stats" }, clipChip(clip), infoButton("chart_stats", "Werte über dem Diagramm")));

  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img",
    "aria-label": title, "aria-roledescription": "Diagramm", class: "chart-svg" });
  const figure = el("div", { class: "chart-wrap" }, svg);
  container.append(figure);

  if (all.length < 2) {
    emptyState(svg, width, height, opts.loading ? "lädt …" : (opts.emptyText || "Noch zu wenige Messwerte"), opts.loading);
    return;
  }

  // --- Bereiche --------------------------------------------------------------
  const [d0, d1] = extent(all.map((p) => p[0]));
  let t0 = d0; let t1 = d1;
  if (isNum(opts.range) && opts.range > 0) {
    t1 = Math.max(isNum(opts.end) ? opts.end : Date.now() / 1000, d1);
    t0 = Math.min(t1 - opts.range, d0);
  }
  if (t0 === t1) t1 = t0 + 1;
  const span = t1 - t0;

  let lo; let hi; const ticks = []; let Y;
  const pad = { top: 10, right: 14, bottom: 26, left: 0 };
  const labelled = visible.length > 1 && visible.length <= 8;
  // Endbeschriftungen nur mit Kurznamen (Hostname ohne Domain, IP unverändert); Platz rechts nach dem
  // längsten Kurznamen, damit nichts abgeschnitten wird.
  // Teilen sich Linien eine Beschriftung (Mitglieder eines Pools heißen alle „pool.ntp.org“), steht am Ende
  // ihre Kennung (die IP) – sonst wären die Enden trotz verschiedener Linien gleich.
  const nameOf = (series) => String(series.short || series.label);
  const shared = new Set(visible.map(nameOf).filter((name, i, all) => all.indexOf(name) !== i));
  const endName = (series) => (shared.has(nameOf(series)) ? String(series.id) : nameOf(series));
  const ends = labelled ? shortNames(visible.map(endName)) : new Map();
  const endText = (series) => ends.get(endName(series)) || series.label;
  if (labelled) {
    const longest = Math.max(4, ...visible.map((s) => endText(s).length));
    pad.right = Math.round(Math.min(Math.max(60, longest * 6.8 + 22), Math.max(96, width * 0.3)));
  }
  if (log) {
    const [vMin, vMax] = extent(all.map((p) => p[1]));
    const e0 = Math.floor(Math.log10(vMin));
    let e1 = Math.ceil(Math.log10(vMax));
    if (e1 <= e0) e1 = e0 + 1;
    lo = 10 ** e0; hi = 10 ** e1;
    const decades = e1 - e0;
    const room = Math.max(2, Math.floor((height - 36) / 22));
    const every = Math.max(1, Math.ceil((decades + 1) / room));
    for (let e = e0; e <= e1; e += every) {
      ticks.push(10 ** e);
      if (decades <= 2 && e < e1) ticks.push(2 * 10 ** e, 5 * 10 ** e);
    }
    ticks.sort((a, b) => a - b);
  } else {
    lo = range.lo; hi = range.hi;
    if (opts.zeroLine !== false) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (opts.min !== undefined) lo = Math.min(lo, opts.min);
    if (lo === hi) {
      if (opts.min !== undefined && lo <= opts.min) hi = lo + (opts.minSpan || 1);
      else { const d = Math.abs(lo) || 1e-6; lo -= d; hi += d; }
    }
    const step = niceStep(hi - lo);
    lo = Math.floor(lo / step - 1e-9) * step;
    hi = Math.ceil(hi / step + 1e-9) * step;
    if (opts.min !== undefined && lo < opts.min) lo = opts.min;
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.abs(v) < step / 1e6 ? 0 : v);
    ticks.step = step;
  }
  // Ereignismarker im Zeitraum: Platz für die Symbolreihe über der Fläche.
  const marks = opts.events === false ? [] : visibleMarkers(Array.isArray(opts.events) ? opts.events : CHART_MARKERS, t0, t1);
  const axisExtent = Math.max(Math.abs(lo), Math.abs(hi));
  const split = splitUnit(ticks.map((v) => (log ? axisFormat(v, v) : axisFormat(v, ticks.step, axisExtent))));
  const tickLabels = split.labels;
  if (split.unit) pad.top = 20;
  if (marks.length) pad.top += 20;
  const ph = height - pad.top - pad.bottom;
  Y = log
    ? (v) => pad.top + ph - ((Math.log10(Math.min(hi, Math.max(v, lo))) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * ph
    : (v) => pad.top + ph - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * ph;
  let widest = 0;
  for (const label of tickLabels) widest = Math.max(widest, label.length);
  pad.left = Math.max(split.unit ? 30 : 40, Math.round(Math.max(widest, split.unit ? split.unit.length : 0) * 6.6 + 14));
  const pw = width - pad.left - pad.right;
  const X = (t) => pad.left + ((t - t0) / span) * pw;

  const id = `c${uid += 1}`;
  const defs = svgEl("defs");
  svg.append(defs);
  const clipPath = svgEl("clipPath", { id: `${id}-clip` });
  clipPath.append(svgEl("rect", { x: pad.left, y: pad.top - 3, width: pw, height: ph + 6 }));
  defs.append(clipPath);

  // --- Raster, Schwellen, Achsen --------------------------------------------
  const grid = svgEl("g", { class: "chart-grid", "aria-hidden": "true" });
  ticks.forEach((v, i) => {
    grid.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: Y(v), y2: Y(v) }));
    const label = svgEl("text", { x: pad.left - 8, y: Y(v) + 3.5, "text-anchor": "end", class: "chart-label" });
    label.textContent = tickLabels[i];
    svg.append(label);
  });
  if (split.unit) {
    const unit = svgEl("text", { x: pad.left - 8, y: 10, "text-anchor": "end", class: "chart-unit" });
    unit.textContent = split.unit;
    svg.append(unit);
  }
  svg.append(grid);
  for (const band of opts.bands || []) {
    if (log) break;
    const from = Math.max(lo, band.from ?? -Infinity);
    const to = Math.min(hi, band.to ?? Infinity);
    if (!(to > from)) continue;
    svg.append(svgEl("rect", { x: pad.left, width: pw, y: Y(to), height: Math.max(0, Y(from) - Y(to)),
      class: "chart-band", "data-tone": band.tone || "warn" }));
    const edge = band.from > lo && band.from < hi ? band.from : band.to < hi && band.to > lo ? band.to : null;
    if (edge !== null && band.label) {
      const text = svgEl("text", { x: width - pad.right - 4, y: Y(edge) - 4, "text-anchor": "end", class: "chart-band-label" });
      text.textContent = band.label;
      svg.append(text);
    }
  }
  if (!log && lo < 0 && hi > 0) {
    svg.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: Y(0), y2: Y(0), class: "chart-zero" }));
  }
  const { ticks: tTicks, step: tStep } = timeTicks(t0, t1, Math.max(3, Math.floor(pw / 72)));
  for (const t of tTicks) {
    svg.append(svgEl("line", { x1: X(t), x2: X(t), y1: pad.top + ph, y2: pad.top + ph + 4, class: "chart-tick" }));
    const label = svgEl("text", { x: X(t), y: height - 7, "text-anchor": "middle", class: "chart-label" });
    label.textContent = timeLabel(t, tStep, span);
    // Randbeschriftungen nicht über den Rand schieben
    if (X(t) - pad.left < 16) label.setAttribute("text-anchor", "start");
    if (width - pad.right - X(t) < 16) label.setAttribute("text-anchor", "end");
    svg.append(label);
  }
  svg.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: pad.top + ph, y2: pad.top + ph, class: "chart-axis" }));

  // --- Lücken (auch: Zeitraum vor dem ersten Messpunkt) -----------------------
  const times = [...new Set(all.map((p) => p[0]))].sort((a, b) => a - b);
  const gaps = findGaps(times);
  const limit = times.length > 2 ? gapLimit(times) : 30;
  const shaded = gaps.map(([g0, g1]) => [g0, g1, "keine Daten"]);
  if (d0 - t0 > Math.max(limit, span * 0.02)) shaded.unshift([t0, d0, `Verlauf ab ${span > 86400 ? fmtStamp(d0, span) : fmtClock(d0)}`]);
  if (t1 - d1 > Math.max(limit, span * 0.02)) shaded.push([d1, t1, "keine Daten"]);
  for (const [g0, g1, text] of shaded) {
    const x0 = X(g0); const x1 = X(g1);
    svg.append(svgEl("rect", { x: x0, y: pad.top, width: Math.max(1, x1 - x0), height: ph, class: "chart-gap" }));
    if (x1 - x0 > text.length * 6 + 12) {
      const label = svgEl("text", { x: (x0 + x1) / 2, y: pad.top + 14, "text-anchor": "middle", class: "chart-gap-label" });
      label.textContent = text;
      svg.append(label);
    }
  }

  // --- Serien ---------------------------------------------------------------
  const plot = svgEl("g", { "clip-path": `url(#${id}-clip)`, class: "chart-plot" });
  if (!REVEALED.has(key)) { plot.classList.add("is-entering"); REVEALED.add(key); }
  svg.append(plot);
  const drawn = [];
  const segmentsOf = (points) => {
    const segments = [[]];
    let prev = null;
    for (const p of points) {
      // Abgeschnittene Werte nicht als flaches Stück am Rand zeichnen: Linie unterbrechen, ▲/▼ markiert sie.
      const out = clipped && (p[1] > hi || p[1] < lo);
      if (!usable(p[1]) || out) { if (segments[segments.length - 1].length) segments.push([]); prev = null; continue; }
      if (prev && inGap(gaps, prev[0], p[0])) segments.push([]);
      segments[segments.length - 1].push(p);
      prev = p;
    }
    return segments.filter((seg) => seg.length);
  };
  const withArea = visible.length === 1 && (opts.area ?? single) !== false;
  for (const series of visible) {
    const { color, dash } = seriesColor(series, slots);
    const segments = segmentsOf(series.points);
    if (withArea) {
      const baseValue = log ? lo : Math.max(lo, Math.min(0, hi));
      const base = Y(baseValue);
      const grad = svgEl("linearGradient", { id: `${id}-fill`, gradientUnits: "userSpaceOnUse", x1: 0, x2: 0,
        y1: pad.top, y2: pad.top + ph });
      const b = Math.min(1, Math.max(0, (base - pad.top) / ph));
      const stops = b >= 0.999 ? [[0, 0.26], [1, 0.02]] : b <= 0.001 ? [[0, 0.02], [1, 0.26]] : [[0, 0.24], [b, 0.02], [1, 0.24]];
      for (const [offset, alpha] of stops) grad.append(svgEl("stop", { offset, "stop-color": color, "stop-opacity": alpha }));
      defs.append(grad);
      const area = segments.filter((seg) => seg.length > 1).map((seg) => `M${X(seg[0][0]).toFixed(1)},${base.toFixed(1)} `
        + seg.map(([t, v]) => `L${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")
        + ` L${X(seg[seg.length - 1][0]).toFixed(1)},${base.toFixed(1)} Z`).join(" ");
      if (area) plot.append(svgEl("path", { d: area, fill: `url(#${id}-fill)`, class: "chart-area" }));
    }
    const d = segments.map((seg) => seg.map(([t, v], i) => `${i ? "L" : "M"}${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")).join(" ");
    plot.append(svgEl("path", { d, fill: "none", stroke: color, "stroke-width": 2, class: "chart-line",
      "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": dash || null }));
    // Einzelpunkte (zwischen zwei Lücken) als Punkt, sonst wären sie unsichtbar.
    for (const seg of segments) {
      if (seg.length === 1) plot.append(svgEl("circle", { cx: X(seg[0][0]), cy: Y(seg[0][1]), r: 2.5, fill: color }));
    }
    drawn.push({ series, color });
  }

  // Abgeschnittene Spitzen: Pfeil am Rand, je zusammenhängendem Abschnitt einer.
  if (!log && clipped) {
    for (const { series } of drawn) {
      let run = null;
      const flush = () => {
        if (!run) return;
        const x = X(run.t);
        const edge = run.v > hi ? pad.top + 1 : pad.top + ph - 1;
        const base = run.v > hi ? edge + 7 : edge - 7;
        svg.append(svgEl("path", { d: `M${x - 5},${base} L${x + 5},${base} L${x},${edge} Z`, class: "chart-clip-mark" }));
        run = null;
      };
      for (const [t, v] of series.points) {
        if (isNum(v) && (v > hi || v < lo)) {
          if (!run || Math.abs(v) > Math.abs(run.v)) run = { t, v };
        } else flush();
      }
      flush();
    }
  }

  const lastOf = (series) => {
    for (let i = series.points.length - 1; i >= 0; i -= 1) if (usable(series.points[i][1])) return series.points[i];
    return null;
  };
  // Direkte Beschriftung am Linienende (bis 8 Serien), Kollisionen auseinanderschieben.
  if (labelled) {
    const marks = drawn.map(({ series, color }) => ({ y: Y(lastOf(series)[1]), label: endText(series), color }))
      .sort((a, b) => a.y - b.y);
    const gap = 14;
    for (let i = 1; i < marks.length; i += 1) if (marks[i].y - marks[i - 1].y < gap) marks[i].y = marks[i - 1].y + gap;
    const bottom = pad.top + ph;
    if (marks.length && marks[marks.length - 1].y > bottom) {
      marks[marks.length - 1].y = bottom;
      for (let i = marks.length - 2; i >= 0; i -= 1) if (marks[i + 1].y - marks[i].y < gap) marks[i].y = marks[i + 1].y - gap;
    }
    for (const end of marks) {
      svg.append(svgEl("circle", { cx: width - pad.right + 7, cy: end.y, r: 3, fill: end.color }));
      const text = svgEl("text", { x: width - pad.right + 13, y: end.y + 4, class: "chart-end-label" });
      text.textContent = end.label;
      svg.append(text);
    }
  } else if (visible.length === 1) {
    // Letzter Wert als Punkt mit Ring – „hier stehen wir jetzt“.
    const { series, color } = drawn[0];
    const last = lastOf(series);
    if (last) svg.append(svgEl("circle", { cx: X(last[0]), cy: Y(last[1]), r: 3.5, fill: color, class: "chart-last" }));
  }

  // --- Ereignismarker ------------------------------------------------------------
  const clusters = marks.length ? clusterMarkers(marks, X) : [];
  if (clusters.length) {
    const lines = svgEl("g", { class: "chart-events", "aria-hidden": "true" });
    for (const cluster of clusters) {
      lines.append(svgEl("line", { x1: cluster.x, x2: cluster.x, y1: pad.top - 8, y2: pad.top + ph, class: "chart-event-line",
        "data-level": cluster.level }));
    }
    svg.append(lines);
    markerButtons(figure, { clusters, width, top: ((pad.top - 15) / height) * 100, tipTop: ((pad.top + 4) / height) * 100,
      stamp: (t) => fmtStamp(t, span), key });
  }

  // --- Beschreibung für Screenreader ------------------------------------------
  const summary = drawn.map(({ series }) => {
    const last = lastOf(series);
    return `${drawn.length > 1 ? `${series.label} ` : ""}${last ? format(last[1]) : "–"}`;
  }).join(", ");
  const statText = stats ? `, min ${format(stats.min)}, max ${format(stats.max)}` : "";
  const eventText = marks.length ? `; ${tr("pages.timeline.events_marked", { count: marks.length })}` : "";
  svg.setAttribute("aria-label", `${title}: zuletzt ${summary}${statText}; ${all.length} Messwerte von ${fmtStamp(d0, span)} bis ${fmtStamp(d1, span)}${eventText}`);
  const hintId = `${id}-hint`;
  svg.setAttribute("aria-describedby", hintId);
  const live = el("div", { class: "sr-only", "aria-live": "polite" });
  figure.append(el("span", { class: "sr-only", id: hintId, text: "Pfeiltasten: Messpunkte durchgehen, Bild auf/ab: größere Sprünge, Pos1/Ende: Anfang/Ende, Esc: schließen." }), live);

  // --- Fadenkreuz + Tooltip (Maus, Touch, Tastatur) --------------------------
  const tooltip = el("div", { class: "tooltip", hidden: true, "aria-hidden": "true" });
  figure.append(tooltip);
  const cursor = svgEl("line", { y1: pad.top, y2: pad.top + ph, class: "chart-cursor", visibility: "hidden" });
  const markers = svgEl("g");
  svg.append(cursor, markers);
  const hoverTimes = [...new Set(drawn.flatMap(({ series }) => series.points.filter((p) => usable(p[1])).map((p) => p[0])))]
    .sort((a, b) => a - b);
  const lookup = drawn.map(({ series }) => new Map(series.points.map((p) => [p[0], p[1]])));
  let index = -1;
  const show = (i, announce = false) => {
    index = Math.max(0, Math.min(hoverTimes.length - 1, i));
    const best = hoverTimes[index];
    HOVER.set(key, best);
    cursor.setAttribute("x1", X(best)); cursor.setAttribute("x2", X(best));
    cursor.setAttribute("visibility", "visible");
    markers.replaceChildren();
    const rows = [];
    const spoken = [];
    drawn.forEach(({ series, color }, n) => {
      const v = lookup[n].get(best);
      if (!usable(v)) return;
      markers.append(svgEl("circle", { cx: X(best), cy: Y(v), r: 4.5, fill: color, class: "chart-marker" }));
      rows.push(drawn.length > 1
        ? el("div", { class: "tt-row" }, el("span", { class: "swatch", style: `--c:${color}` }),
          el("span", { class: "tt-label", text: series.label }), el("b", { text: format(v) }))
        : el("div", { class: "tt-row tt-single" }, el("b", { text: format(v) })));
      spoken.push(`${drawn.length > 1 ? `${series.label} ` : ""}${format(v)}`);
    });
    tooltip.replaceChildren(el("div", { class: "tt-time", text: fmtStamp(best, span) }), ...rows);
    tooltip.hidden = rows.length === 0;
    const left = (X(best) / width) * 100;
    tooltip.style.left = `${left}%`;
    tooltip.style.transform = left > 60 ? "translate(calc(-100% - 12px), 0)" : "translate(12px, 0)";
    if (announce) live.textContent = `${fmtStamp(best, span)}: ${spoken.join(", ") || "kein Wert"}`;
  };
  const hide = () => {
    index = -1;
    HOVER.delete(key);
    cursor.setAttribute("visibility", "hidden");
    markers.replaceChildren();
    tooltip.hidden = true;
  };
  const nearest = (target) => {
    let lo2 = 0; let hi2 = hoverTimes.length - 1;
    while (hi2 - lo2 > 1) {
      const mid = (lo2 + hi2) >> 1;
      if (hoverTimes[mid] < target) lo2 = mid; else hi2 = mid;
    }
    return Math.abs(hoverTimes[lo2] - target) <= Math.abs(hoverTimes[hi2] - target) ? lo2 : hi2;
  };
  const fromEvent = (event) => {
    const rect = svg.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    return nearest(t0 + Math.min(1, Math.max(0, (px - pad.left) / pw)) * span);
  };
  svg.addEventListener("pointermove", (event) => show(fromEvent(event)));
  svg.addEventListener("pointerdown", (event) => show(fromEvent(event)));
  svg.addEventListener("pointerleave", (event) => { if (event.pointerType === "mouse") hide(); });
  svg.setAttribute("tabindex", "0");
  // app.js stellt den Fokus nach jedem Neuaufbau über diesen Schlüssel wieder her.
  svg.dataset.focusKey = `chart:${key}`;
  svg.addEventListener("focus", () => { if (index < 0) show(hoverTimes.length - 1); });
  // Beim Neuaufbau feuert blur, während das alte Diagramm noch im DOM hängt –
  // dann das Fadenkreuz behalten; nur echtes Weiterwandern blendet es aus.
  svg.addEventListener("blur", () => setTimeout(() => {
    if (svg.isConnected && document.activeElement !== svg) hide();
  }, 0));
  svg.addEventListener("keydown", (event) => {
    const jump = Math.max(1, Math.round(hoverTimes.length / 20));
    const moves = { ArrowLeft: index - 1, ArrowRight: index + 1, PageUp: index - jump, PageDown: index + jump,
      Home: 0, End: hoverTimes.length - 1 };
    if (event.key in moves) { event.preventDefault(); show(moves[event.key], true); } else if (event.key === "Escape") hide();
  });
  if (HOVER.has(key)) show(nearest(HOVER.get(key)));
}

/**
 * Kleiner Verlauf ohne Achsen für Kennzahl-Kacheln. Schneidet Ausreißer ab wie
 * lineChart, damit die Startspitze den Trend nicht verschluckt.
 */
export function sparkline(points, opts = {}) {
  const log = opts.scale === "log";
  const usable = (v) => isNum(v) && (!log || v > 0);
  const data = points.filter((p) => usable(p[1]));
  const W = 120; const H = 32;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", class: "spark", "aria-hidden": "true",
    focusable: "false" });
  if (data.length < 2) return svg;
  const t1 = isNum(opts.end) && opts.range ? Math.max(opts.end, data[data.length - 1][0]) : data[data.length - 1][0];
  const t0 = isNum(opts.end) && opts.range ? Math.min(t1 - opts.range, data[0][0]) : data[0][0];
  const tr = log ? (v) => Math.log10(v) : (v) => v;
  const r = robustRange(data.map((p) => tr(p[1])), true, data.slice(-3).map((p) => tr(p[1])));
  let lo = r.lo; let hi = r.hi;
  if (opts.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (opts.min !== undefined) lo = Math.min(lo, opts.min);
  if (hi === lo) { hi += 1; lo -= 1; }
  const X = (t) => ((t - t0) / Math.max(1, t1 - t0)) * W;
  const Y = (v) => 2 + (H - 4) * (1 - (Math.min(hi, Math.max(lo, tr(v))) - lo) / (hi - lo));
  const gaps = findGaps(points.map((p) => p[0]));
  const segments = [[]];
  let prev = null;
  for (const p of points) {
    if (!usable(p[1])) { if (segments[segments.length - 1].length) segments.push([]); prev = null; continue; }
    if (prev && inGap(gaps, prev[0], p[0])) segments.push([]);
    segments[segments.length - 1].push([X(p[0]).toFixed(1), Y(p[1]).toFixed(1)]);
    prev = p;
  }
  const parts = segments.filter((seg) => seg.length);
  const d = parts.map((seg) => seg.map(([x, y], i) => `${i ? "L" : "M"}${x},${y}`).join(" ")).join(" ");
  const area = parts.filter((seg) => seg.length > 1).map((seg) => `M${seg[0][0]},${H} `
    + seg.map(([x, y]) => `L${x},${y}`).join(" ") + ` L${seg[seg.length - 1][0]},${H} Z`).join(" ");
  const color = resolve(opts.color || "var(--accent)");
  const gid = `s${uid += 1}`;
  const grad = svgEl("linearGradient", { id: gid, x1: 0, x2: 0, y1: 0, y2: 1 });
  grad.append(svgEl("stop", { offset: 0, "stop-color": color, "stop-opacity": 0.28 }),
    svgEl("stop", { offset: 1, "stop-color": color, "stop-opacity": 0 }));
  const defs = svgEl("defs");
  defs.append(grad);
  svg.append(defs);
  svg.append(svgEl("path", { d: area, fill: `url(#${gid})` }));
  svg.append(svgEl("path", { d, fill: "none", stroke: color, "stroke-width": 1.6, "vector-effect": "non-scaling-stroke",
    "stroke-linejoin": "round", "stroke-linecap": "round" }));
  return svg;
}

/** Himmelskarte: Mitte = Zenit, Rand = Horizont, Norden oben. */
export function skyPlot(container, satellites) {
  const size = 300;
  const c = size / 2;
  const r = c - 26;
  // role=group statt img: die Satelliten darin sind einzeln per Tab erreichbar und
  // brauchen eine eigene Beschreibung.
  const svg = svgEl("svg", { viewBox: `0 0 ${size} ${size}`, class: "sky", role: "group",
    "aria-label": `Himmelskarte der Satelliten: ${satellites.filter((s) => s.used).length} genutzt von ${satellites.length} sichtbar` });
  for (const elev of [0, 30, 60]) {
    svg.append(svgEl("circle", { cx: c, cy: c, r: r * (1 - elev / 90), class: "sky-ring" }));
    if (elev) {
      const label = svgEl("text", { x: c + 3, y: c - r * (1 - elev / 90) - 3, class: "sky-label" });
      label.textContent = `${elev}°`;
      svg.append(label);
    }
  }
  svg.append(svgEl("line", { x1: c - r, x2: c + r, y1: c, y2: c, class: "sky-ring" }));
  svg.append(svgEl("line", { x1: c, x2: c, y1: c - r, y2: c + r, class: "sky-ring" }));
  for (const [label, x, y] of [["N", c, 14], ["O", size - 10, c + 4], ["S", c, size - 6], ["W", 10, c + 4]]) {
    const text = svgEl("text", { x, y, "text-anchor": "middle", class: "sky-compass" });
    text.textContent = label;
    svg.append(text);
  }
  const tooltip = el("div", { class: "tooltip", hidden: true });
  for (const sat of satellites) {
    if (!isNum(sat.elevation) || !isNum(sat.azimuth) || sat.elevation < 0) continue;
    const dist = r * (1 - sat.elevation / 90);
    const angle = (sat.azimuth * Math.PI) / 180;
    const x = c + dist * Math.sin(angle);
    const y = c - dist * Math.cos(angle);
    const group = svgEl("g", { class: `sky-sat${sat.used ? " used" : ""}`, tabindex: 0, role: "img",
      "aria-label": `${sat.system || "GNSS"} PRN ${sat.prn}, Elevation ${sat.elevation}°, Azimut ${sat.azimuth}°, `
        + `Signal ${isNum(sat.snr) ? `${sat.snr} dB-Hz` : "unbekannt"}, ${sat.used ? "genutzt" : "nicht genutzt"}` });
    group.append(svgEl("circle", { cx: x, cy: y, r: 9, class: "sky-dot" }));
    const text = svgEl("text", { x, y: y + 3.5, "text-anchor": "middle", class: "sky-prn" });
    text.textContent = sat.prn ?? "";
    group.append(text);
    const show = () => {
      tooltip.replaceChildren(
        el("div", { class: "tt-time", text: `${sat.system} · PRN ${sat.prn}` }),
        el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Elevation / Azimut" }),
          el("b", { text: `${sat.elevation}° / ${sat.azimuth}°` })),
        el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Signal" }),
          el("b", { text: isNum(sat.snr) ? `${sat.snr} dB-Hz` : "–" })),
        el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Status" }),
          el("b", { text: sat.used ? "genutzt" : "sichtbar, nicht genutzt" })));
      tooltip.style.left = `${(x / size) * 100}%`;
      tooltip.style.top = `${(y / size) * 100}%`;
      tooltip.style.transform = "translate(12px, -50%)";
      tooltip.hidden = false;
    };
    group.addEventListener("pointerenter", show);
    group.addEventListener("focus", show);
    group.addEventListener("pointerleave", () => { tooltip.hidden = true; });
    group.addEventListener("blur", () => { tooltip.hidden = true; });
    svg.append(group);
  }
  container.replaceChildren(el("div", { class: "chart-wrap sky-wrap" }, svg, tooltip));
}

/** Säulen für die Signalstärke je Satellit, mit Schwellen 25/35 dB-Hz. Maus, Touch und Pfeiltasten. */
export function snrBars(container, satellites) {
  const sats = satellites.filter((s) => isNum(s.snr) || s.used).slice(0, 32);
  const width = Math.max(320, container.clientWidth || 600);
  const height = 200;
  const pad = { top: 12, right: 8, bottom: 34, left: 36 };
  const max = 50;
  const used = sats.filter((s) => s.used).length;
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, class: "chart-svg",
    role: "img", "aria-roledescription": "Diagramm",
    "aria-label": `Signalstärke je Satellit: ${sats.length} Satelliten, ${used} genutzt` });
  if (!sats.length) {
    emptyState(svg, width, height, "Keine Satellitendaten");
    container.replaceChildren(el("div", { class: "chart-wrap" }, svg));
    return;
  }
  const pw = width - pad.left - pad.right;
  const ph = height - pad.top - pad.bottom;
  const Y = (v) => pad.top + ph - (Math.min(v, max) / max) * ph;
  for (const v of [0, 25, 35, 50]) {
    svg.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: Y(v), y2: Y(v),
      class: v === 25 || v === 35 ? "chart-zero" : "chart-grid" }));
    const label = svgEl("text", { x: pad.left - 6, y: Y(v) + 4, "text-anchor": "end", class: "chart-label" });
    label.textContent = v;
    svg.append(label);
  }
  const slot = pw / Math.max(sats.length, 1);
  const barW = Math.max(4, Math.min(22, slot - 4));
  const tooltip = el("div", { class: "tooltip", hidden: true, "aria-hidden": "true" });
  const live = el("div", { class: "sr-only", "aria-live": "polite" });
  const rects = [];
  let index = -1;
  const describe = (sat) => `${sat.system} PRN ${sat.prn}: Signal ${isNum(sat.snr) ? `${sat.snr} dB-Hz` : "unbekannt"}, ${sat.used ? "genutzt" : "nicht genutzt"}`;
  const show = (i, announce = false) => {
    index = Math.max(0, Math.min(sats.length - 1, i));
    const sat = sats[index];
    const x = pad.left + index * slot + (slot - barW) / 2;
    rects.forEach((r, n) => r.classList.toggle("is-active", n === index));
    tooltip.replaceChildren(el("div", { class: "tt-time", text: `${sat.system} · PRN ${sat.prn}` }),
      el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Signal" }),
        el("b", { text: isNum(sat.snr) ? `${sat.snr} dB-Hz` : "–" })),
      el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Status" }),
        el("b", { text: sat.used ? "genutzt" : "nicht genutzt" })));
    tooltip.style.left = `${((x + barW / 2) / width) * 100}%`;
    tooltip.style.top = "10px";
    tooltip.style.transform = (x / width) > 0.6 ? "translate(calc(-100% - 8px), 0)" : "translate(8px, 0)";
    tooltip.hidden = false;
    if (announce) live.textContent = describe(sat);
  };
  const hide = () => { index = -1; tooltip.hidden = true; rects.forEach((r) => r.classList.remove("is-active")); };
  sats.forEach((sat, i) => {
    const x = pad.left + i * slot + (slot - barW) / 2;
    const v = isNum(sat.snr) ? sat.snr : 0;
    const rect = svgEl("rect", { x, y: Y(v), width: barW, height: Math.max(0, Y(0) - Y(v)), rx: 3,
      class: `snr-bar${sat.used ? " used" : ""}` });
    rect.addEventListener("pointerenter", () => show(i));
    rect.addEventListener("pointerdown", () => show(i));
    rect.addEventListener("pointerleave", (event) => { if (event.pointerType === "mouse") hide(); });
    rects.push(rect);
    svg.append(rect);
    const label = svgEl("text", { x: x + barW / 2, y: height - pad.bottom + 14, "text-anchor": "middle",
      class: "chart-label" });
    label.textContent = sat.prn ?? "";
    svg.append(label);
  });
  svg.setAttribute("tabindex", "0");
  svg.dataset.focusKey = "chart:snr";
  svg.addEventListener("focus", () => { if (index < 0) show(0, true); });
  svg.addEventListener("blur", () => setTimeout(() => { if (svg.isConnected && document.activeElement !== svg) hide(); }, 0));
  svg.addEventListener("keydown", (event) => {
    const moves = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: sats.length - 1 };
    if (event.key in moves) { event.preventDefault(); show(moves[event.key], true); } else if (event.key === "Escape") hide();
  });
  const hint = `snr-hint-${uid += 1}`;
  svg.setAttribute("aria-describedby", hint);
  container.replaceChildren(el("div", { class: "chart-wrap" }, svg, tooltip, live,
    el("span", { class: "sr-only", id: hint, text: "Pfeiltasten: Satelliten durchgehen." })));
}

export { css };

// Nachkommastellen passend zur Rasterweite, damit Achsenbeschriftungen eindeutig bleiben.
export function stepDecimals(step) {
  return Math.min(6, Math.max(0, -Math.floor(Math.log10(step) + 1e-9)));
}

/**
 * Streudiagramm (1.4: Temperatur ↔ Frequenz). Jeder Punkt ein Messpunkt; die Farbe wird
 * mit dem Alter blasser, damit Tag-/Nacht-Schleifen und Verschiebungen sichtbar bleiben.
 * opts: { points: [{x, y, t}], xFormat(v), yFormat(v), xAxis(v, step), yAxis(v, step), xUnit, yUnit,
 *         height, emptyText, ariaLabel, key, robust (Standard: an – Ausreißer in y abschneiden) }
 */
export function scatterChart(container, opts) {
  const height = opts.height || 260;
  const width = Math.max(280, container.clientWidth || 640);
  const xFormat = opts.xFormat || defaultFormat;
  const yFormat = opts.yFormat || defaultFormat;
  const xAxis = opts.xAxis || xFormat;
  const yAxis = opts.yAxis || yFormat;
  const pts = (opts.points || []).filter((p) => isNum(p.x) && isNum(p.y));
  container.replaceChildren();
  container.classList.add("chart-host");
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img",
    "aria-label": opts.ariaLabel || "Streudiagramm", "aria-roledescription": "Diagramm", class: "chart-svg" });
  const figure = el("div", { class: "chart-wrap" }, svg);
  container.append(figure);
  if (pts.length < 2) {
    emptyState(svg, width, height, opts.emptyText || "Noch zu wenige Messwerte", false);
    return;
  }
  const yr = robustRange(pts.map((p) => p.y), opts.robust !== false);
  const [xMin, xMax] = extent(pts.map((p) => p.x));
  const axis = (lo, hi) => {
    if (lo === hi) { const d = Math.abs(lo) * 0.01 || 0.5; lo -= d; hi += d; }
    const step = niceStep(hi - lo, 5);
    lo = Math.floor(lo / step - 1e-9) * step;
    hi = Math.ceil(hi / step + 1e-9) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.abs(v) < step / 1e6 ? 0 : v);
    return { lo, hi, step, ticks };
  };
  const ax = axis(xMin, xMax);
  const ay = axis(yr.lo, yr.hi);
  const yLabels = ay.ticks.map((v) => yAxis(v, ay.step));
  const pad = { top: opts.yUnit ? 22 : 12, right: 16, bottom: 40, left: 0 };
  pad.left = Math.max(40, Math.round(Math.max(...yLabels.map((l) => l.length)) * 6.6 + 14));
  const pw = width - pad.left - pad.right;
  const ph = height - pad.top - pad.bottom;
  const X = (v) => pad.left + ((v - ax.lo) / (ax.hi - ax.lo)) * pw;
  const Y = (v) => pad.top + ph - ((Math.min(ay.hi, Math.max(ay.lo, v)) - ay.lo) / (ay.hi - ay.lo)) * ph;

  const grid = svgEl("g", { class: "chart-grid", "aria-hidden": "true" });
  ay.ticks.forEach((v, i) => {
    grid.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: Y(v), y2: Y(v) }));
    const label = svgEl("text", { x: pad.left - 8, y: Y(v) + 3.5, "text-anchor": "end", class: "chart-label" });
    label.textContent = yLabels[i];
    svg.append(label);
  });
  const every = Math.max(1, Math.ceil(ax.ticks.length / Math.max(2, Math.floor(pw / 64))));
  ax.ticks.forEach((v, i) => {
    grid.append(svgEl("line", { x1: X(v), x2: X(v), y1: pad.top, y2: pad.top + ph }));
    if (i % every) return;
    const label = svgEl("text", { x: X(v), y: pad.top + ph + 16, "text-anchor": "middle", class: "chart-label" });
    label.textContent = xAxis(v, ax.step);
    svg.append(label);
  });
  svg.append(grid);
  svg.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: pad.top + ph, y2: pad.top + ph, class: "chart-axis" }));
  if (opts.yUnit) {
    const unit = svgEl("text", { x: pad.left - 8, y: 12, "text-anchor": "end", class: "chart-unit" });
    unit.textContent = opts.yUnit;
    svg.append(unit);
  }
  if (opts.xUnit) {
    const unit = svgEl("text", { x: width - pad.right, y: height - 4, "text-anchor": "end", class: "chart-unit" });
    unit.textContent = opts.xUnit;
    svg.append(unit);
  }

  // Punkte: ältere blasser. Sortiert nach Zeit, damit die neuesten oben liegen.
  const color = resolve("var(--accent)");
  const times = pts.map((p) => (isNum(p.t) ? p.t : 0));
  const [tMin, tMax] = extent(times);
  const sorted = [...pts].sort((a, b) => (a.t || 0) - (b.t || 0));
  const plot = svgEl("g", { class: "chart-plot" });
  for (const p of sorted) {
    const age = tMax > tMin ? (p.t - tMin) / (tMax - tMin) : 1;
    const out = p.y > ay.hi || p.y < ay.lo;
    plot.append(svgEl("circle", { cx: X(p.x).toFixed(1), cy: Y(p.y).toFixed(1), r: out ? 3 : 2.4, fill: color,
      "fill-opacity": (0.12 + 0.78 * age).toFixed(2), class: out ? "chart-clip-mark" : null }));
  }
  svg.append(plot);
  const latest = sorted[sorted.length - 1];
  svg.append(svgEl("circle", { cx: X(latest.x), cy: Y(latest.y), r: 4.5, fill: color, class: "chart-last" }));
  svg.setAttribute("aria-label", `${opts.ariaLabel || "Streudiagramm"}: ${pts.length} Punkte, x von ${xFormat(xMin)} bis ${xFormat(xMax)}, `
    + `y von ${yFormat(yr.min)} bis ${yFormat(yr.max)}; zuletzt ${xFormat(latest.x)} / ${yFormat(latest.y)}`);

  // Tooltip: nächster Punkt zur Maus (Bildschirmabstand).
  const tooltip = el("div", { class: "tooltip", hidden: true, "aria-hidden": "true" });
  const marker = svgEl("circle", { r: 5.5, fill: color, class: "chart-marker", visibility: "hidden" });
  svg.append(marker);
  figure.append(tooltip);
  const show = (p) => {
    marker.setAttribute("cx", X(p.x)); marker.setAttribute("cy", Y(p.y));
    marker.setAttribute("visibility", "visible");
    tooltip.replaceChildren(
      el("div", { class: "tt-time", text: isNum(p.t) ? fmtStamp(p.t, 2 * 86400) : "" }),
      el("div", { class: "tt-row tt-single" }, el("b", { text: `${xFormat(p.x)} · ${yFormat(p.y)}` })));
    tooltip.hidden = false;
    const left = (X(p.x) / width) * 100;
    tooltip.style.left = `${left}%`;
    tooltip.style.transform = left > 60 ? "translate(calc(-100% - 12px), 0)" : "translate(12px, 0)";
  };
  const hide = () => { marker.setAttribute("visibility", "hidden"); tooltip.hidden = true; };
  const pick = (event) => {
    const rect = svg.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    const py = ((event.clientY - rect.top) / rect.height) * height;
    let winner = null; let dist = Infinity;
    for (const p of pts) {
      const d = (X(p.x) - px) ** 2 + (Y(p.y) - py) ** 2;
      if (d < dist) { dist = d; winner = p; }
    }
    if (winner && dist < 40 * 40) show(winner); else hide();
  };
  svg.addEventListener("pointermove", pick);
  svg.addEventListener("pointerdown", pick);
  svg.addEventListener("pointerleave", (event) => { if (event.pointerType === "mouse") hide(); });
}

/**
 * Log-log-Diagramm (1.5.4: Allan-Abweichung). Eine y-Achse, x und y logarithmisch, Punkte mit
 * Linie und senkrechtem Vertrauensbereich; blasse Punkte (muted) sind weniger aussagekräftig.
 * opts: { points: [{x, y, lo, hi, muted}], xTicks: [Werte], xAxis(v), yAxis(v), tooltip(p) → [Zeilen],
 *         xUnit, yUnit, height, emptyText, ariaLabel, describe(p) für die Kurzbeschreibung }
 */
export function logLogChart(container, opts) {
  const height = opts.height || 260;
  const width = Math.max(280, container.clientWidth || 640);
  const pts = (opts.points || []).filter((p) => isNum(p.x) && isNum(p.y) && p.x > 0 && p.y > 0);
  container.replaceChildren();
  container.classList.add("chart-host");
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img",
    "aria-label": opts.ariaLabel || "Diagramm", "aria-roledescription": "Diagramm", class: "chart-svg" });
  const figure = el("div", { class: "chart-wrap" }, svg);
  container.append(figure);
  if (pts.length < 2) {
    emptyState(svg, width, height, opts.emptyText || "Noch zu wenige Messwerte", false);
    return;
  }
  const xAxis = opts.xAxis || defaultFormat;
  const yAxis = opts.yAxis || defaultFormat;
  const ys = pts.flatMap((p) => [p.y, isNum(p.lo) && p.lo > 0 ? p.lo : p.y, isNum(p.hi) ? p.hi : p.y]);
  const decades = (lo, hi) => {
    const e0 = Math.floor(Math.log10(lo) + 1e-9);
    let e1 = Math.ceil(Math.log10(hi) - 1e-9);
    if (e1 <= e0) e1 = e0 + 1;
    return [e0, e1];
  };
  const [xMin, xMax] = extent(pts.map((p) => p.x));
  const [ye0, ye1] = decades(...extent(ys));
  const yTicks = [];
  for (let e = ye0; e <= ye1; e += 1) {
    yTicks.push(10 ** e);
    if (ye1 - ye0 <= 2 && e < ye1) yTicks.push(2 * 10 ** e, 5 * 10 ** e);
  }
  yTicks.sort((a, b) => a - b);
  const lx0 = Math.log10(xMin) - 0.04; const lx1 = Math.log10(xMax) + 0.04;
  const ly0 = ye0; const ly1 = ye1;
  const yLabels = yTicks.map((v) => yAxis(v));
  const pad = { top: opts.yUnit ? 22 : 12, right: 16, bottom: 40, left: 0 };
  pad.left = Math.max(40, Math.round(Math.max(...yLabels.map((l) => l.length)) * 6.6 + 14));
  const pw = width - pad.left - pad.right;
  const ph = height - pad.top - pad.bottom;
  const X = (v) => pad.left + ((Math.log10(v) - lx0) / (lx1 - lx0)) * pw;
  const Y = (v) => pad.top + ph - ((Math.log10(Math.max(v, 10 ** ly0)) - ly0) / (ly1 - ly0)) * ph;

  const grid = svgEl("g", { class: "chart-grid", "aria-hidden": "true" });
  yTicks.forEach((v, i) => {
    grid.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: Y(v), y2: Y(v) }));
    const label = svgEl("text", { x: pad.left - 8, y: Y(v) + 3.5, "text-anchor": "end", class: "chart-label" });
    label.textContent = yLabels[i];
    svg.append(label);
  });
  let xTicks = (opts.xTicks || []).filter((v) => v >= 10 ** lx0 && v <= 10 ** lx1);
  if (!xTicks.length) {
    xTicks = [];
    for (let e = Math.ceil(lx0); e <= Math.floor(lx1); e += 1) xTicks.push(10 ** e);
  }
  let lastX = -Infinity;
  for (const v of xTicks) {
    const x = X(v);
    grid.append(svgEl("line", { x1: x, x2: x, y1: pad.top, y2: pad.top + ph }));
    if (x - lastX < 48) continue;  // Beschriftungen nicht übereinander
    lastX = x;
    const label = svgEl("text", { x, y: pad.top + ph + 16, "text-anchor": "middle", class: "chart-label" });
    label.textContent = xAxis(v);
    svg.append(label);
  }
  svg.append(grid);
  svg.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: pad.top + ph, y2: pad.top + ph, class: "chart-axis" }));
  if (opts.yUnit) {
    const unit = svgEl("text", { x: pad.left - 8, y: 12, "text-anchor": "end", class: "chart-unit" });
    unit.textContent = opts.yUnit;
    svg.append(unit);
  }
  if (opts.xUnit) {
    const unit = svgEl("text", { x: width - pad.right, y: height - 4, "text-anchor": "end", class: "chart-unit" });
    unit.textContent = opts.xUnit;
    svg.append(unit);
  }

  const color = resolve("var(--accent)");
  const plot = svgEl("g", { class: "chart-plot" });
  for (const p of pts) {
    if (isNum(p.lo) && isNum(p.hi) && p.hi > p.lo) {
      plot.append(svgEl("line", { x1: X(p.x), x2: X(p.x), y1: Y(p.hi), y2: Y(Math.max(p.lo, 10 ** ly0)), stroke: color,
        "stroke-width": 1.5, "stroke-opacity": p.muted ? 0.25 : 0.45, "stroke-linecap": "round" }));
    }
  }
  const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(" ");
  plot.append(svgEl("path", { d, fill: "none", stroke: color, "stroke-width": 2, class: "chart-line",
    "stroke-linejoin": "round", "stroke-linecap": "round" }));
  for (const p of pts) {
    plot.append(svgEl("circle", { cx: X(p.x).toFixed(1), cy: Y(p.y).toFixed(1), r: 3.2, fill: color,
      "fill-opacity": p.muted ? 0.4 : 1 }));
  }
  svg.append(plot);
  if (opts.describe) svg.setAttribute("aria-label", `${opts.ariaLabel || "Diagramm"}: ${opts.describe(pts)}`);

  const tooltip = el("div", { class: "tooltip", hidden: true, "aria-hidden": "true" });
  const marker = svgEl("circle", { r: 5.5, fill: color, class: "chart-marker", visibility: "hidden" });
  svg.append(marker);
  figure.append(tooltip);
  const show = (p) => {
    marker.setAttribute("cx", X(p.x)); marker.setAttribute("cy", Y(p.y));
    marker.setAttribute("visibility", "visible");
    const rows = opts.tooltip ? opts.tooltip(p) : [`${xAxis(p.x)} · ${yAxis(p.y)}`];
    tooltip.replaceChildren(el("div", { class: "tt-time", text: rows[0] }),
      ...rows.slice(1).map((row, i) => el("div", { class: `tt-row${i ? "" : " tt-single"}` }, i ? el("span", { text: row }) : el("b", { text: row }))));
    tooltip.hidden = false;
    const left = (X(p.x) / width) * 100;
    tooltip.style.left = `${left}%`;
    tooltip.style.transform = left > 60 ? "translate(calc(-100% - 12px), 0)" : "translate(12px, 0)";
  };
  const hide = () => { marker.setAttribute("visibility", "hidden"); tooltip.hidden = true; };
  const pick = (event) => {
    const rect = svg.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    let winner = null; let dist = Infinity;
    for (const p of pts) {
      const dx = Math.abs(X(p.x) - px);
      if (dx < dist) { dist = dx; winner = p; }
    }
    if (winner && dist < 40) show(winner); else hide();
  };
  svg.addEventListener("pointermove", pick);
  svg.addEventListener("pointerdown", pick);
  svg.addEventListener("pointerleave", (event) => { if (event.pointerType === "mouse") hide(); });
}
