// Uhr-Werkstatt (/clock, 1.6 T6): reine Funktionen für Designs, Adressparameter, Ton und Geräteversatz.
//
// Kein DOM, keine Zeitgeber – so lässt sich alles mit Node prüfen (tests/test_uhr_werkstatt.py). Die Seite
// (clock.js) baut daraus die Anzeige; Bewegung (Sekundenzeiger, Klappen, Glühen) macht CSS, nicht eine
// JS-Schleife.
import { fmtNumber } from "./util.js";

/** Designs in der Reihenfolge der Auswahl. Schlüssel = Wert von ?design= und im Browser gemerkt. */
export const DESIGNS = ["digital", "studio", "bahnhof", "nixie", "flip", "wort"];
export const DEFAULT_DESIGN = "digital";

// --- Adressparameter (Schema-Tabelle) -------------------------------------------------
// Nur Namen aus PARAM_SCHEMA mit gültigem Wert wirken; Unbekanntes wird stillschweigend ignoriert. Die Werte
// landen nie als HTML im DOM (nur textContent, Klassen, CSSOM aus festen Listen), trotzdem prüft das Schema
// jeden Wert streng: Typ, Bereich, Länge und Zeichensatz. Werte über MAX_LEN Zeichen werden verworfen.
const FLAG = { 1: true, 0: false, true: true, false: false };
export const MAX_LEN = 64;
const ZONE_CHARS = /^[A-Za-z0-9_+\-/]+$/;
const INT_CHARS = /^[0-9]{1,6}$/;
const HEX6 = /^[0-9a-fA-F]{6}$/;
// Kurzzeilen (Typ label): Buchstaben, Ziffern, Leerzeichen und wenige Satzzeichen – keine spitzen Klammern,
// Anführungszeichen, Semikolons, geschweiften Klammern, Backslashes, Steuer- oder Formatzeichen.
export const LABEL_CHARS = /^[\p{L}\p{N} .,:!?+\-/()#&']+$/u;
const DAILY_TIME = /^([01][0-9]|2[0-3]):([0-5][0-9])(?::([0-5][0-9]))?$/;
// Dauer für ?timer=: „90s“, „25m“, „1h30m“, „2m30s“ (Einheiten absteigend, jede höchstens einmal).
const DURATION = /^(?:([0-9]{1,2})h)?(?:([0-9]{1,4})m)?(?:([0-9]{1,5})s)?$/;
export const MAX_TIMER_MS = 24 * 3600_000;
const ISO_TIME = /^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):([0-5][0-9])(?::([0-5][0-9]))?$/;

// --- Darstellung: Layouts, Elemente, Farben (Studiouhr A3/A4) ---------------------------------
/** Layouts: auto wählt per resolveLayout() aus der Größe der Bühne, die anderen setzen es fest. */
export const LAYOUTS = ["auto", "normal", "banner", "column", "strip", "tile"];
/** Elemente, die sich mit ?show= einzeln zeigen lassen (Allowlist; was fehlt, wird ausgeblendet). */
export const SHOW_ITEMS = ["time", "seconds", "date", "weekday", "week", "utc", "tz", "status", "countdown"];
/** Themen (data-look in clock.css, höchstens sechs). bg: Hintergrund für die Kontrastprüfung der Akzentfarbe. */
export const LOOKS = Object.freeze({
  studio: { bg: "#000000", scheme: "dark" },
  contrast: { bg: "#000000", scheme: "dark" },
  warm: { bg: "#1b130c", scheme: "dark" },
  terminal: { bg: "#020a04", scheme: "dark" },
  paper: { bg: "#f6f1e7", scheme: "light" },
  pastel: { bg: "#24213a", scheme: "dark" },
});
/** Hintergrund von Hell/Dunkel aus app.css (ohne Thema). */
export const THEME_BG = Object.freeze({ dark: "#0d1117", light: "#f4f6f9" });
/** Feste Farbpalette (Namen für ?accent= und ?color=). Jede Farbe hat auf Schwarz mindestens 4,5:1. */
export const PALETTE = Object.freeze({
  amber: "#ffb000", red: "#ff4d40", green: "#3ddc68", cyan: "#2ee6f0", white: "#f2f2f2", ice: "#a8d8ff",
  yellow: "#ffe14d", orange: "#ff8a1f", blue: "#6aa8ff", violet: "#c39bff", pink: "#ff7ab8", lime: "#b8f040",
});
/** Farben des Designs studio (?color=). */
export const STUDIO_COLORS = ["amber", "red", "green", "cyan", "white", "ice"];
export const MIN_CONTRAST = 4.5;

/**
 * Parameter der Uhr. Typen: enum (values), flag (1/0/true/false), int (min, max; nur Ziffern), zone (siehe
 * checkZone), label (len, charset), time („20:15[:00]“ oder „2026-12-31T23:59[:59]“), list (kommagetrennt, nur
 * Einträge aus values; Unbekanntes fällt weg), color (Name aus PALETTE oder sechs Hexziffern ohne #), duration
 * („90s“, „25m“, „1h30m“; in ms), intlist (kommagetrennte ganze Zahlen in min … max, höchstens maxItems). default gilt,
 * wenn der Parameter fehlt oder ungültig ist. Standortangaben (lat/lon) kennt das Schema bewusst nicht.
 */
export const PARAM_SCHEMA = Object.freeze([
  { name: "design", type: "enum", values: DESIGNS, default: null },
  { name: "kiosk", type: "flag", default: false },
  { name: "eink", type: "flag", default: false },
  { name: "tz", type: "zone", default: null },
  // Vorlauf der Anzeige in ms: gleicht die Verzögerung von Bildprozessoren im Fernseher aus.
  { name: "lead", type: "int", min: 0, max: 200, default: 0 },
  // Ab dieser Fehlerschranke (ms) gilt die Anzeige als unsicher (data-sync="degraded").
  { name: "maxerr", type: "int", min: 10, max: 1000, default: 100 },
  // Layout-Engine (A3): Aufteilung der Bühne, Sicherheitsrand in % (null: 0, bei layout=tile 5), Hintergrund,
  // Größe in %, sichtbare Elemente, Schriftstärke, Pixel-Shift gegen Einbrennen (null: 0, im Design studio 1).
  { name: "layout", type: "enum", values: LAYOUTS, default: "auto" },
  { name: "safe", type: "int", min: 0, max: 10, default: null },
  { name: "bg", type: "enum", values: ["black", "transparent"], default: null },
  { name: "scale", type: "int", min: 50, max: 200, default: 100 },
  { name: "show", type: "list", values: SHOW_ITEMS, default: null },
  { name: "weight", type: "enum", values: ["thin", "regular", "bold"], default: null },
  { name: "shift", type: "int", min: 0, max: 2, default: null },
  // Design studio (A4): Farbe von Kranz und Ziffern, Zeile unter der Zeit, Sekunden als Kranz/Ziffern, 12 h.
  { name: "color", type: "enum", values: STUDIO_COLORS, default: "amber" },
  { name: "sub", type: "enum", values: ["utc", "tz2", "date", "off"], default: "utc" },
  { name: "seconds", type: "enum", values: ["ring", "digits", "both"], default: "both" },
  { name: "h12", type: "flag", default: false },
  // Design digital (A4): Ziffernsatz, Doppelpunkt, führende Null der Stunde, Datumszeile.
  { name: "face", type: "enum", values: ["sans", "mono", "seg"], default: "sans" },
  { name: "colon", type: "enum", values: ["steady", "blink"], default: "steady" },
  { name: "lz", type: "flag", default: true },
  { name: "date", type: "enum", values: ["long", "short", "iso", "off"], default: "long" },
  // Thema und Akzentfarbe (A4): gesetzt per CSSOM, nach Kontrastprüfung gegen den Hintergrund.
  { name: "look", type: "enum", values: Object.keys(LOOKS), default: null },
  { name: "accent", type: "color", default: null },
  // Countdown und Count-up (A5): Ziel als Uhrzeit (heute in der Server-Zeitzone, sonst morgen) oder ISO-Zeitpunkt,
  // alternativ eine lokale Dauer (Start mit der Leertaste). Danach hochzählen (up) oder auf 00:00 stehen (stop).
  // Farbstufen in Sekunden (absteigend: gelb, rot, fett rot), Piepen in den letzten n Sekunden, Kurzzeile, Platz.
  { name: "until", type: "time", default: null },
  { name: "timer", type: "duration", default: null },
  { name: "after", type: "enum", values: ["up", "stop"], default: "up" },
  { name: "warn", type: "intlist", min: 1, max: 3600, maxItems: 3, default: Object.freeze([300, 60, 10]) },
  { name: "beep", type: "int", min: 0, max: 60, default: 0 },
  { name: "label", type: "label", len: 24, default: null },
  { name: "cd", type: "enum", values: ["below", "main"], default: "below" },
  // Lokale Bedienung sperren: keine Tastenkürzel, keine Timer-Knöpfe (Kiosk, Regie-Monitor).
  { name: "lock", type: "flag", default: false },
].map((entry) => Object.freeze(entry)));

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

/** „20:15“ → { kind: "daily", h, m, s }; „2026-12-31T23:59:59“ → { kind: "iso", y, mo, d, h, m, s }; sonst null. */
export function parseTimeValue(value) {
  if (typeof value !== "string") return null;
  const daily = DAILY_TIME.exec(value);
  if (daily) return { kind: "daily", h: Number(daily[1]), m: Number(daily[2]), s: Number(daily[3] || 0) };
  const iso = ISO_TIME.exec(value);
  if (!iso) return null;
  const [y, mo, d, h, m] = iso.slice(1, 6).map(Number);
  const probe = new Date(Date.UTC(y, mo - 1, d));
  if (probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== d) return null;   // 31.02. gibt es nicht
  return { kind: "iso", y, mo, d, h, m, s: Number(iso[6] || 0) };
}

/** „90s“ → 90 000, „25m“ → 1 500 000, „1h30m“ → 5 400 000 (ms); 0, über 24 h oder unlesbar: null. */
export function parseDuration(value) {
  if (typeof value !== "string" || !value) return null;
  const m = DURATION.exec(value);
  if (!m || !(m[1] || m[2] || m[3])) return null;
  const ms = ((Number(m[1] || 0) * 60 + Number(m[2] || 0)) * 60 + Number(m[3] || 0)) * 1000;
  return ms > 0 && ms <= MAX_TIMER_MS ? ms : null;
}

/** Einen Rohwert gegen einen Schema-Eintrag prüfen. Liefert { ok: true, value } oder { ok: false }. */
export function checkParam(entry, raw, zones = [], intl = globalThis.Intl) {
  const fail = { ok: false };
  if (!entry || typeof raw !== "string" || raw.length > MAX_LEN) return fail;
  switch (entry.type) {
    case "enum":
      return entry.values.includes(raw) ? { ok: true, value: raw } : fail;
    case "flag":
      return Object.prototype.hasOwnProperty.call(FLAG, raw) ? { ok: true, value: FLAG[raw] } : fail;
    case "int": {
      if (!INT_CHARS.test(raw)) return fail;
      const value = Number(raw);
      return value >= entry.min && value <= entry.max ? { ok: true, value } : fail;
    }
    case "zone": {
      const zone = checkZone(raw, zones, intl);
      return zone ? { ok: true, value: zone } : fail;
    }
    case "label": {
      const text = raw.normalize("NFC");
      const len = Math.min(entry.len || 24, MAX_LEN);
      const charset = entry.charset || LABEL_CHARS;
      const ok = text.length > 0 && [...text].length <= len && text.trim() === text && charset.test(text);
      return ok ? { ok: true, value: text } : fail;
    }
    case "time": {
      const value = parseTimeValue(raw);
      return value ? { ok: true, value } : fail;
    }
    case "duration": {
      const value = parseDuration(raw);
      return value ? { ok: true, value } : fail;
    }
    case "intlist": {
      // Kommagetrennte ganze Zahlen im Bereich, ohne Doppelte, höchstens maxItems; absteigend sortiert. Ein
      // unzulässiger Eintrag verwirft den ganzen Wert (lieber die Standardstufen als halbe Stufen).
      const items = raw.split(",");
      if (items.length > (entry.maxItems || 3)) return fail;
      const values = [];
      for (const item of items) {
        if (!INT_CHARS.test(item)) return fail;
        const value = Number(item);
        if (value < entry.min || value > entry.max || values.includes(value)) return fail;
        values.push(value);
      }
      return { ok: true, value: Object.freeze(values.sort((a, b) => b - a)) };
    }
    case "list": {
      const items = [];
      for (const item of raw.split(",")) {
        if (entry.values.includes(item) && !items.includes(item)) items.push(item);
      }
      return items.length ? { ok: true, value: items } : fail;
    }
    case "color": {
      if (Object.prototype.hasOwnProperty.call(PALETTE, raw)) return { ok: true, value: raw };
      return HEX6.test(raw) ? { ok: true, value: raw.toLowerCase() } : fail;
    }
    default:
      return fail;
  }
}

/** Standardwerte aller Schema-Einträge: { design: null, kiosk: false, … }. */
export function paramDefaults(schema = PARAM_SCHEMA) {
  const out = {};
  for (const entry of schema) out[entry.name] = entry.default;
  return out;
}

/**
 * ?design=…&kiosk=1&eink=1&tz=Europe/London&lead=40 → { design, kiosk, eink, tz, lead, maxerr, ignored }.
 * Jeder Name aus dem Schema bekommt seinen geprüften Wert oder den Standard. ignored: Namen bekannter
 * Parameter mit unzulässigem Wert (für eine Konsolenzeile, nie für das DOM). Doppelte Namen: Der erste gilt.
 */
export function parseParams(search, zones = [], intl = globalThis.Intl, schema = PARAM_SCHEMA) {
  const params = new URLSearchParams(typeof search === "string" ? search : "");
  const out = { ...paramDefaults(schema), ignored: [] };
  for (const entry of schema) {
    if (!params.has(entry.name)) continue;
    const result = checkParam(entry, String(params.get(entry.name) ?? ""), zones, intl);
    if (result.ok) out[entry.name] = result.value;
    else out.ignored.push(entry.name);
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

// --- Layout-Engine (Studiouhr A3) ---------------------------------------------------------
// Die Bühne (.clock-stage, container-type: size) bekommt ihr Layout aus ihrer eigenen Größe, nicht aus dem
// Fenster oder der Ausrichtung des Geräts. clock.css spiegelt dieselben Grenzen in @container-Regeln (Prüfwert
// --cq-layout); clock.js setzt data-layout bei jeder Größenänderung (ResizeObserver).
export const LAYOUT_LIMITS = Object.freeze({ stripHeight: 120, bannerRatio: 3, columnRatio: 0.625, tileWidth: 480,
  tileHeight: 270, stackRatio: 1 / 3 });

/**
 * Layout aus der Größe der Bühne (CSS-Pixel). Reihenfolge wie in der Tabelle des Konzepts:
 *   Höhe < 120 → strip; Seitenverhältnis ≥ 3:1 → banner; ≤ 1:1,6 → column; kleiner als 480×270 (schmaler als 480 und
 *   niedriger als 270, z. B. eine Multiviewer-Kachel) → tile; sonst normal.
 */
export function resolveLayout(width, height) {
  const w = Number(width);
  const h = Number(height);
  if (!(w > 0 && h > 0) || !Number.isFinite(w) || !Number.isFinite(h)) return "normal";
  const L = LAYOUT_LIMITS;
  if (h < L.stripHeight) return "strip";
  const ratio = w / h;
  if (ratio >= L.bannerRatio) return "banner";
  if (ratio <= L.columnRatio) return "column";
  if (w < L.tileWidth && h < L.tileHeight) return "tile";
  return "normal";
}

/** Layout nach ?layout=: auto (oder unbekannt) rechnet resolveLayout, sonst gilt der Parameter. */
export function effectiveLayout(param, width, height) {
  return LAYOUTS.includes(param) && param !== "auto" ? param : resolveLayout(width, height);
}

/**
 * Layout mit ausgeblendeter Kopfzeile und Band: Wählt die Automatik den Streifen (wenig Höhe), braucht die Zeit jede
 * Zeile – dann fallen Kopfzeile und Band weg („compact“), die Bühne wächst um deren Höhe (hiddenChrome). Damit das
 * Layout danach nicht zurückspringt, wird mit der Höhe entschieden, die die Bühne mit Kopfzeile und Band hätte.
 * Nur bei ?layout=auto; ein ausdrücklich gewähltes Layout behält Kopfzeile und Band. { layout, compact }.
 */
export function chromeLayout(param, width, stageHeight, hiddenChrome = 0) {
  const auto = !(LAYOUTS.includes(param) && param !== "auto");
  const chrome = auto && Number.isFinite(hiddenChrome) && hiddenChrome > 0 ? hiddenChrome : 0;
  const layout = effectiveLayout(param, width, stageHeight - chrome);
  return { layout, compact: auto && layout === "strip" };
}

/** Sehr schmale Spalte (≤ 1:3): Stunden über Minuten statt nebeneinander. */
export function stackedTime(layout, width, height) {
  return layout === "column" && width > 0 && height > 0 && width / height <= LAYOUT_LIMITS.stackRatio;
}

/** Sicherheitsrand in Prozent: ?safe=, sonst 5 bei ?layout=tile (Multiviewer) und 0 sonst. */
export function safeMargin(params = {}) {
  if (Number.isInteger(params.safe)) return params.safe;
  return params.layout === "tile" ? 5 : 0;
}

/** Pixel-Shift-Stufe: ?shift=, sonst 1 im Design studio und 0 sonst. */
export function shiftLevel(params = {}, design = DEFAULT_DESIGN) {
  if (Number.isInteger(params.shift)) return params.shift;
  return design === "studio" ? 1 : 0;
}

export const SHIFT_PERIOD_MS = 120_000;
export const SHIFT_STEPS = 8;
/** Deterministischer Zyklus: alle 2 min eine von acht Positionen (Klassen shift-0 … shift-7). */
export function shiftIndex(serverMs) {
  if (!Number.isFinite(serverMs)) return 0;
  const step = Math.floor(serverMs / SHIFT_PERIOD_MS);
  return ((step % SHIFT_STEPS) + SHIFT_STEPS) % SHIFT_STEPS;
}

/**
 * Verkleinerung, damit die Zeit ohne Umbruch in die verfügbare Fläche passt: min(1, verfügbar / nötig) je Achse,
 * auf drei Stellen abgerundet. Ohne Maße 1.
 */
export function fitFactor(needed, available) {
  const ok = (v) => Number.isFinite(v) && v > 0;
  let factor = 1;
  if (ok(needed?.width) && ok(available?.width)) factor = Math.min(factor, available.width / needed.width);
  if (ok(needed?.height) && ok(available?.height)) factor = Math.min(factor, available.height / needed.height);
  return Math.max(0.1, Math.floor(factor * 1000) / 1000);
}

/**
 * Auto-Anpassung bis zur Ruhe: measure(factor) setzt --fit = factor und liefert { needed, available } (oder null).
 * Ein Durchgang reicht nicht immer – max-width: 100 % kappt die erste Messung, und Grid-Spalten ordnen sich nach dem
 * Verkleinern neu. Darum so lange nachregeln, bis die Zeit passt (höchstens `rounds` Messungen). Ergebnis: factor.
 */
export function fitConverge(measure, { rounds = 4, tolerance = 0.002 } = {}) {
  let factor = 1;
  for (let round = 0; round < rounds; round += 1) {
    const got = typeof measure === "function" ? measure(factor) : null;
    if (!got) return factor;
    const step = fitFactor(got.needed, got.available);
    if (step >= 1 - tolerance) return factor;
    factor = Math.max(0.1, Math.floor(factor * step * 1000) / 1000);
  }
  return factor;
}

// --- Farben: Palette, Kontrast (WCAG 2.x) ----------------------------------------------------
/** „#ff8800“ → [255, 136, 0]; sonst null. */
export function hexRgb(hex) {
  const m = /^#([0-9a-f]{6})$/i.exec(String(hex || ""));
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbHex(rgb) {
  return `#${rgb.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("")}`;
}

/** Relative Leuchtdichte nach WCAG 2.x. */
export function luminance(hex) {
  const rgb = hexRgb(hex);
  if (!rgb) return NaN;
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Kontrastverhältnis zweier Farben (1 … 21). */
export function contrastRatio(a, b) {
  const x = luminance(a);
  const y = luminance(b);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return NaN;
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/** Wert aus ?accent=/?color= als #rrggbb: Name aus PALETTE oder sechs Hexziffern; sonst null. */
export function colorValue(value) {
  if (Object.prototype.hasOwnProperty.call(PALETTE, value)) return PALETTE[value];
  return HEX6.test(String(value || "")) ? `#${String(value).toLowerCase()}` : null;
}

/**
 * Farbe mit mindestens `min`:1 Kontrast zu `bg`. Reicht er nicht, wird die Farbe in Stufen von 10 % zu Weiß
 * (dunkler Hintergrund) bzw. Schwarz (heller Hintergrund) gemischt, bis er reicht – die nächste Stufe, die trägt.
 * { hex, ratio, adjusted }; ungültige Eingaben: null.
 */
export function ensureContrast(hex, bg, min = MIN_CONTRAST) {
  const rgb = hexRgb(hex);
  const back = hexRgb(bg);
  if (!rgb || !back) return null;
  const target = luminance(bg) < 0.18 ? [255, 255, 255] : [0, 0, 0];
  for (let step = 0; step <= 10; step += 1) {
    const mixed = rgbHex(rgb.map((v, i) => v + (target[i] - v) * (step / 10)));
    const ratio = contrastRatio(mixed, bg);
    if (ratio >= min || step === 10) return { hex: mixed, ratio, adjusted: step > 0 };
  }
  return null;
}

/**
 * Hell oder dunkel: E-Ink hell, ein Thema (?look=) bringt sein Schema mit, ?bg=black ist immer dunkel (sonst stünde
 * die dunkle Schrift des hellen Themas auf Schwarz), sonst die gespeicherte Wahl. { scheme, locked } – locked:
 * der Hell/Dunkel-Knopf hat keine Wirkung.
 */
export function colorScheme({ eink = false, look = null, bg = null, stored = null } = {}) {
  if (eink) return { scheme: "light", locked: true };
  if (look && Object.prototype.hasOwnProperty.call(LOOKS, look)) return { scheme: LOOKS[look].scheme, locked: true };
  if (bg === "black") return { scheme: "dark", locked: true };
  return { scheme: stored === "light" ? "light" : "dark", locked: false };
}

/** Hintergrund, gegen den Akzent- und Ziffernfarbe geprüft werden: Thema, ?bg=black oder Hell/Dunkel. */
export function colorBackground({ look = null, bg = null, theme = "dark" } = {}) {
  if (look && Object.prototype.hasOwnProperty.call(LOOKS, look)) return LOOKS[look].bg;
  if (bg === "black") return "#000000";
  return THEME_BG[theme] || THEME_BG.dark;
}

// --- 7-Segment-Ziffern (studio, digital mit face=seg) -----------------------------------------
/** Leuchtende Segmente je Ziffer (a oben, im Uhrzeigersinn b … f, g Mitte). " " = aus. */
export const SEGMENTS = Object.freeze({
  0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg", 6: "acdefg", 7: "abc", 8: "abcdefg",
  9: "abcdfg", " ": "",
});

/** Klasse eines Ziffernsymbols: „seg7 d-4“; unbekannte Zeichen als leere Stelle („d-blank“). */
export function segClass(ch, extra = "") {
  const name = /^[0-9]$/.test(ch) ? `d-${ch}` : "d-blank";
  return extra ? `seg7 ${name} ${extra}` : `seg7 ${name}`;
}

/**
 * Stunde für die Anzeige: 24 h oder 12 h (12, 1 … 11), mit oder ohne führende Null (dann führendes Leerzeichen,
 * damit die Stellen fest bleiben). { text: "09"|" 9", ampm: ""|"AM"|"PM" }.
 */
export function hourText(h, { h12 = false, lz = true } = {}) {
  const hour = h12 ? (h % 12 || 12) : h;
  const text = lz ? String(hour).padStart(2, "0") : String(hour).padStart(2, " ");
  return { text, ampm: h12 ? (h < 12 ? "AM" : "PM") : "" };
}

/** Kranz des Designs studio: Punkt i (0 = oben) leuchtet, solange i ≤ Sekunde; zur vollen Minute nur Punkt 0. */
export function ringLit(index, second) {
  return Number.isInteger(index) && Number.isInteger(second) && index >= 0 && index <= second;
}

// --- Zeitbasis: Anker, Fehlerschranke, Zustand --------------------------------------------
// Die Anzeige rechnet nicht mit Date.now() + Versatz, sondern mit einem Anker aus der besten Messung:
//   serverMs = anchor.server + (performance.now() − anchor.perf)
// performance.now() ist monoton: Stellt jemand die Geräteuhr um (von Hand, per NTP des Geräts), springt die
// Anzeige nicht mit. Nur eine neue Messung setzt einen neuen Anker.
// Grenze: Auf manchen Plattformen steht performance.now() im Systemschlaf still (Linux CLOCK_MONOTONIC, macOS
// mach_absolute_time; die HR-Time-Spezifikation erlaubt das). Dann fehlt nach dem Standby die Schlafdauer im
// Anker. Darum vergleicht wallJump() bei jedem Takt die Wanduhr mit der monotonen Uhr seit dem Anker: Weichen
// beide um mehr als WALL_JUMP_MS ab (Standby oder verstellte Geräteuhr), gilt die Anzeige bis zum nächsten
// Anker als unsicher (degraded, Schranke unbekannt) und es wird sofort neu gemessen.
export const DRIFT_PPM = 50;          // angenommene Gangabweichung des Quarzes im Anzeigegerät
export const FRAME_MS = 17;           // eine Bildauffrischung bei 60 Hz, solange nichts gemessen ist
export const STALE_MS = 10_000;       // so lange ohne Antwort, dann läuft die Uhr frei
export const TICK_GAP_MS = 2_000;     // Takt so viel später als geplant: Standby, gedrosselter Tab → neu messen
export const WALL_JUMP_MS = 2_000;    // Wanduhr und monotone Uhr laufen seit dem Anker so weit auseinander → unsicher
export const SECONDS_UNSURE_MS = 500; // ab dieser Schranke ist schon die Sekundenstelle unsicher
export const TENTHS_UNSURE_MS = 50;   // ab dieser Schranke wird die Zehntelstelle grau

/**
 * Messung (clocksync.measure plus perf = performance.now() im Moment von t3) → Anker { server, perf, wall }.
 * server = t3 + Versatz, also die Serverzeit in dem Moment, in dem die Antwort ankam; wall = t3 auf der
 * Geräteuhr (nur für wallJump, nie für die Anzeige). Sonst null.
 */
export function anchorFrom(sample) {
  if (!sample || ![sample.at, sample.offset, sample.perf].every(Number.isFinite)) return null;
  return { server: sample.at + sample.offset, perf: sample.perf, wall: sample.at };
}

/**
 * Laufen Geräteuhr (Date.now()) und monotone Uhr seit dem Anker um mehr als WALL_JUMP_MS auseinander? Das heißt:
 * Standby mit stehender monotoner Uhr oder eine verstellte Geräteuhr – welches von beiden, lässt sich nicht
 * unterscheiden. Ohne Anker oder ohne Wanduhr im Anker: false.
 */
export function wallJump(anchor, perfNow, wallNow) {
  if (!anchor || ![anchor.perf, anchor.wall, perfNow, wallNow].every(Number.isFinite)) return false;
  return Math.abs((wallNow - anchor.wall) - (perfNow - anchor.perf)) > WALL_JUMP_MS;
}

/** Serverzeit (ms) aus Anker und monotoner Uhr; ohne Anker gilt `fallback` (Gerätezeit, Zustand „none“). */
export function anchoredNow(anchor, perfNow, fallback = NaN) {
  if (!anchor || !Number.isFinite(perfNow)) return fallback;
  return anchor.server + (perfNow - anchor.perf);
}

/**
 * Fehlerschranke der Anzeige in ms: Genauigkeit der Serveruhr (accuracy aus /api/v1/time) + RTT/2 der besten
 * Messung + DRIFT_PPM × Alter der Messung + eine Bildauffrischung. null, wenn ein Wert fehlt (z. B. der
 * Server kennt seine eigene Genauigkeit nicht) – dann lässt sich keine Schranke belegen.
 */
export function errorBound({ serverAccMs, rttMs, ageMs, frameMs = FRAME_MS } = {}) {
  if (![serverAccMs, rttMs, ageMs].every(Number.isFinite)) return null;
  const frame = Number.isFinite(frameMs) && frameMs > 0 ? frameMs : FRAME_MS;
  return Math.abs(serverAccMs) + Math.max(0, rttMs) / 2 + DRIFT_PPM * 1e-6 * Math.max(0, ageMs) + frame;
}

/**
 * Zustand für data-sync am Root:
 *   none     – nie abgeglichen (Anzeige = Gerätezeit),
 *   free     – letzte Antwort älter als STALE_MS, die Uhr läuft mit dem Anker frei weiter,
 *   degraded – Schranke unbekannt oder über maxerrMs, der Server selbst ist nicht synchron, oder seit dem Anker
 *              ist die Geräteuhr gegen die monotone Uhr gesprungen (jumped: Standby, verstellte Uhr) –
 *              das gilt bis zum nächsten Anker, auch ohne Antwort des Servers,
 *   ok       – abgeglichen.
 */
export function syncState({ anchored = false, sinceOkMs = Infinity, boundMs = null, maxerrMs = 100, serverSynced = true,
  jumped = false } = {}) {
  if (!anchored) return "none";
  if (jumped) return "degraded";
  if (!(sinceOkMs <= STALE_MS)) return "free";
  if (!Number.isFinite(boundMs) || boundMs > maxerrMs || serverSynced === false) return "degraded";
  return "ok";
}

/**
 * Was trägt die Schranke? Je Stelle "sure" (normal), "unsure" (grau) oder "off" (ausgeblendet).
 * Sekunden grau ab SECONDS_UNSURE_MS; Zehntel grau ab TENTHS_UNSURE_MS, weg über maxerrMs; Frames grau ab
 * einem halben Frame, weg über maxerrMs. Unbekannte Schranke: alles grau, Zehntel und Frames weg.
 */
export function fineDigits(boundMs, { fps = 25, maxerrMs = 100 } = {}) {
  if (!Number.isFinite(boundMs)) return { seconds: "unsure", tenths: "off", frames: "off" };
  const halfFrame = 500 / (Number.isFinite(fps) && fps > 0 ? fps : 25);
  const level = (unsureFrom) => {
    if (boundMs > maxerrMs) return "off";
    return boundMs > unsureFrom ? "unsure" : "sure";
  };
  return {
    seconds: boundMs > SECONDS_UNSURE_MS ? "unsure" : "sure",
    tenths: level(TENTHS_UNSURE_MS),
    frames: level(halfFrame),
  };
}

/** Kam der Takt mehr als TICK_GAP_MS später als geplant (Standby, gedrosselter Hintergrund-Tab)? */
export function tickGap(lastPerf, nowPerf, stepMs) {
  if (![lastPerf, nowPerf, stepMs].every(Number.isFinite)) return false;
  return nowPerf - lastPerf > stepMs + TICK_GAP_MS;
}

/** Dauer einer Bildauffrischung aus requestAnimationFrame-Zeitstempeln (Median der Abstände), sonst FRAME_MS. */
export function frameFromStamps(stamps) {
  const list = Array.isArray(stamps) ? stamps.filter(Number.isFinite) : [];
  const deltas = list.slice(1).map((v, i) => v - list[i]).filter((d) => d > 0).sort((a, b) => a - b);
  if (!deltas.length) return FRAME_MS;
  const median = deltas[Math.floor(deltas.length / 2)];
  return median >= 4 && median <= 50 ? median : FRAME_MS;
}

/** Dauer grob: „25 s“, „3 min“, „2 h“ (für „frei laufend seit …“). */
export function fmtAge(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "–";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${fmtNumber(seconds, 0, { group: false })} s`;
  if (seconds < 3600) return `${fmtNumber(Math.floor(seconds / 60), 0, { group: false })} min`;
  return `${fmtNumber(Math.floor(seconds / 3600), 0, { group: false })} h`;
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

/** Geplante Töne (Oszillatoren aus scheduleTone) sofort verstummen lassen – auch die, die noch gar nicht klingen. */
export function stopTones(oscs) {
  for (const osc of oscs || []) {
    try { osc.stop(0); } catch (error) { /* schon beendet */ }
    try { osc.disconnect(); } catch (error) { /* schon getrennt */ }
  }
  return [];
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
