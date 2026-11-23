// Uhr-Werkstatt (/clock, 1.6 T6): reine Funktionen für Designs, Adressparameter, Ton und Geräteversatz.
//
// Kein DOM, keine Zeitgeber – so lässt sich alles mit Node prüfen (tests/test_uhr_werkstatt.py). Die Seite
// (clock.js) baut daraus die Anzeige; Bewegung (Sekundenzeiger, Klappen, Glühen) macht CSS, nicht eine
// JS-Schleife.
import { fmtNumber } from "./util.js";

/** Designs in der Reihenfolge der Auswahl. Schlüssel = Wert von ?design= und im Browser gemerkt. */
// Höchstens acht Designs (docs/konzept/studiouhr.md, Abschnitt 7) – mit binary (Etappe C) ist die Grenze erreicht.
export const DESIGNS = ["digital", "studio", "bahnhof", "nixie", "flip", "wort", "tc", "binary"];
export const MAX_DESIGNS = 8;
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
// Kurznamen der Weltzeit (?tzl=): nur Buchstaben, Ziffern, Leerzeichen, Punkt und Bindestrich – strenger als LABEL_CHARS,
// das Komma trennt die Einträge.
export const ZONE_LABEL_CHARS = /^[\p{L}\p{N} .\-]+$/u;
/** Weltzeit: höchstens so viele Zonen (?tz=) und Kurznamen (?tzl=), ein Kurzname höchstens so viele Zeichen. */
export const MAX_ZONES = 6;
export const ZONE_LABEL_LEN = 16;
// Stundenbereich für den Nachtmodus (?dim=22-6): von – bis in vollen Stunden, über Mitternacht erlaubt, nie gleich.
const HOURS_RANGE = /^([01]?[0-9]|2[0-3])-([01]?[0-9]|2[0-3])$/;
/** Eingebaute Countdowns (?goal=, Etappe C): Neujahr und nächste Zeitumstellung in der Zone des Servers, dazu zwei feste
 *  Zeitpunkte – Unixzeit 2 000 000 000 und das Ende der NTP-Ära 0 (Rechnung in clockextras.js). */
export const GOALS = ["newyear", "dst", "unix", "ntp"];
const ISO_TIME = /^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):([0-5][0-9])(?::([0-5][0-9]))?$/;

// --- Darstellung: Layouts, Elemente, Farben (Studiouhr A3/A4) ---------------------------------
/** Layouts: auto wählt per resolveLayout() aus der Größe der Bühne, die anderen setzen es fest. */
export const LAYOUTS = ["auto", "normal", "banner", "column", "strip", "tile", "world"];
/** Elemente, die sich mit ?show= einzeln zeigen lassen (Allowlist; was fehlt, wird ausgeblendet). Die letzten drei sind
 *  Zusätze der Etappe C (Mondphase, Nerd-Zeile, Fortschrittsbalken): Standard aus, nur wenn ?show= sie nennt. */
export const SHOW_ITEMS = ["time", "seconds", "date", "weekday", "week", "utc", "tz", "status", "countdown", "moon", "nerd",
  "progress"];
/** Binäruhr (?bin=): bcd je Dezimalziffer eine Spalte, plain Stunde/Minute/Sekunde als Dualzahl (clockextras.js). */
export const BIN_MODES = ["bcd", "plain"];
/** Fortschrittsbalken (?bars=): Tag, Woche, Monat, Jahr (Ortszeit des Geräts) und die laufende Eieruhr bzw. Pomodoro-Phase. */
export const BARS = ["day", "week", "month", "year", "timer"];
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
/** Bildraten der Timecode-Anzeige (?fps=, Design tc); 29.97 und 59.94 zählen Drop-Frame (clocktc.js). */
export const TC_FPS = ["24", "25", "30", "50", "60", "29.97", "59.94"];

/**
 * Parameter der Uhr. Typen: enum (values), flag (1/0/true/false), int (min, max; nur Ziffern), zone (siehe
 * checkZone), label (len, charset), time („20:15[:00]“ oder „2026-12-31T23:59[:59]“), list (kommagetrennt, nur
 * Einträge aus values; Unbekanntes fällt weg), color (Name aus PALETTE oder sechs Hexziffern ohne #), duration
 * („90s“, „25m“, „1h30m“; in ms), intlist (kommagetrennte ganze Zahlen in min … max, höchstens maxItems), zonelist
 * (kommagetrennte Zeitzonen, höchstens maxItems, ohne Doppelte; der Parameter darf auch mehrfach in der Adresse stehen),
 * labellist (kommagetrennte Kurznamen zu den Zonen, je höchstens len Zeichen; leere Einträge erlaubt). default gilt,
 * wenn der Parameter fehlt oder ungültig ist. hours („22-6“: von – bis in vollen Stunden, Nachtmodus). Standortangaben
 * (lat/lon) kennt das Schema bewusst nicht.
 */
export const PARAM_SCHEMA = Object.freeze([
  { name: "design", type: "enum", values: DESIGNS, default: null },
  { name: "kiosk", type: "flag", default: false },
  { name: "eink", type: "flag", default: false },
  // Weltzeit (B2): bis zu sechs Zeitzonen (eine: zweite Zeitzone in der Zeile unter der Uhr, mehrere: Leiste bzw.
  // Raster mit ?layout=world), dazu Kurznamen in derselben Reihenfolge.
  { name: "tz", type: "zonelist", maxItems: MAX_ZONES, default: null },
  { name: "tzl", type: "labellist", len: ZONE_LABEL_LEN, maxItems: MAX_ZONES, default: null },
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
  // sub gilt auch im Design tc (B1) für die Feinstelle: frames, off, sonst Zehntel (tenths ist dort der Standard).
  { name: "color", type: "enum", values: STUDIO_COLORS, default: "amber" },
  { name: "sub", type: "enum", values: ["utc", "tz2", "date", "off", "tenths", "frames"], default: "utc" },
  { name: "seconds", type: "enum", values: ["ring", "digits", "both"], default: "both" },
  { name: "h12", type: "flag", default: false },
  // Design digital (A4): Ziffernsatz, Doppelpunkt, führende Null der Stunde, Datumszeile.
  { name: "face", type: "enum", values: ["sans", "mono", "seg"], default: "sans" },
  { name: "colon", type: "enum", values: ["steady", "blink"], default: "steady" },
  { name: "lz", type: "flag", default: true },
  { name: "date", type: "enum", values: ["long", "short", "iso", "off"], default: "long" },
  // Design tc (B1): Bildrate der Timecode-Anzeige. Die Feinstelle (Zehntel, Frames, aus) wählt ?sub=.
  { name: "fps", type: "enum", values: TC_FPS, default: "25" },
  // Design binary (C2): BCD-Spalten oder Dualzahl je Stunde, Minute, Sekunde.
  { name: "bin", type: "enum", values: BIN_MODES, default: "bcd" },
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
  // On-Air/REC-Signal (B4): Dieser Bildschirm zeigt das zentrale Signal aus /api/v1/time als Rahmen mit Text und fragt
  // dafür im Sekundentakt ab (sonst alle 5 s). Die Taste O schaltet unabhängig davon ein lokales „On Air“.
  { name: "signal", type: "flag", default: false },
  // Spielereien (Etappe C): fun=0 blendet Eieruhr, Pomodoro, eigene Countdowns und den Nachtmodus-Knopf aus – in den
  // Voreinstellungen studio, tile und banner gesetzt. Kiosk, lock=1, die Kachel und OBS-Browserquellen zeigen sie ohnehin nie.
  { name: "fun", type: "flag", default: true },
  // Ostereier (C3): 13:37, 12:34:56, Neujahr mit Konfetti, Schaltsekunde, Zeitumstellung, Konami-Code. eggs=0 schaltet sie
  // ab; ohne Spielereien (fun=0, Kiosk, lock=1, Kachel, OBS, E-Ink) gibt es sie ohnehin nie (clockextras.eggsAllowed).
  { name: "eggs", type: "flag", default: true },
  // Eingebauter Countdown (Neujahr, nächste Zeitumstellung, Unixzeit 2 000 000 000, NTP-Ära 2036); ?until= geht vor.
  { name: "goal", type: "enum", values: GOALS, default: null },
  // Pomodoro: Dauer der Arbeitsphase (startet den Pomodoro-Timer statt ?timer=) und der Pause (ohne Angabe 5 min).
  { name: "pomo", type: "duration", default: null },
  { name: "pause", type: "duration", default: null },
  // Nachtmodus: von – bis (volle Stunden der Ortszeit dieses Geräts), Helligkeit in %, Rotlicht statt Grau.
  { name: "dim", type: "hours", default: null },
  { name: "dimlevel", type: "int", min: 20, max: 80, default: 40 },
  { name: "dimred", type: "flag", default: false },
  // Fortschrittsbalken (C2, mit ?show=progress): welche Zeiträume; ohne Angabe Tag und Jahr bzw. Timer und Tag.
  { name: "bars", type: "list", values: BARS, default: null },
  // Prüfbild (B5): test=sync lässt eine Fläche zur vollen Sekunde wechseln und klickt dazu (Einmessen von ?lead=).
  // Wirkt nur aus der Adresse (ADDRESS_ONLY, testMode) – nie aus einem Profil oder dem gemerkten Stand.
  { name: "test", type: "enum", values: ["sync"], default: null },
].map((entry) => Object.freeze(entry)));

/** Parameter, die nur aus der Adresse wirken: Profile und der gemerkte Stand tragen sie nie (clocklink.js, clockprofiles.py). */
export const ADDRESS_ONLY = Object.freeze(["test"]);

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

/** „22-6“ → { from: 22, to: 6 }; gleiche Stunden, Minuten oder anderes: null. */
export function parseHours(value) {
  if (typeof value !== "string") return null;
  const m = HOURS_RANGE.exec(value);
  if (!m) return null;
  const from = Number(m[1]);
  const to = Number(m[2]);
  return from === to ? null : { from, to };
}

/** „90s“ → 90 000, „25m“ → 1 500 000, „1h30m“ → 5 400 000 (ms); 0, über 24 h oder unlesbar: null. */
export function parseDuration(value) {
  if (typeof value !== "string" || !value) return null;
  const m = DURATION.exec(value);
  if (!m || !(m[1] || m[2] || m[3])) return null;
  const ms = ((Number(m[1] || 0) * 60 + Number(m[2] || 0)) * 60 + Number(m[3] || 0)) * 1000;
  return ms > 0 && ms <= MAX_TIMER_MS ? ms : null;
}

/** Mehrere Werte in einem Parameter (kommagetrennt, in der Adresse auch als wiederholter Name)? */
export function multiParam(entry) {
  return Boolean(entry) && (entry.type === "zonelist" || entry.type === "labellist");
}

/**
 * Größte Länge eines Rohwerts: MAX_LEN, bei Listen aus Zonen bzw. Kurznamen je Eintrag (plus Kommas). Bei Listen
 * zählen Zeichen (Codepunkte) der bereinigten Schreibweise (listRaw), wie in clockprofiles.py.
 */
export function rawLimit(entry) {
  if (!multiParam(entry)) return MAX_LEN;
  const items = entry.maxItems || MAX_ZONES;
  const each = entry.type === "labellist" ? Math.min(entry.len || ZONE_LABEL_LEN, MAX_LEN) : MAX_LEN;
  return items * each + (items - 1);
}

/** So viel länger als rawLimit darf der Rohwert einer Liste vor dem Bereinigen sein (Leerzeichen, zerlegte Zeichen). */
export const LIST_SLACK = 4;

/**
 * Schreibweise einer Liste (tz, tzl), wie sie in die Adresse gehört: ohne Leerzeichen um die Kommas und am Rand
 * („Europe/London, Asia/Tokyo“ → „Europe/London,Asia/Tokyo“), Kurznamen in NFC. Leerzeichen in einem Kurznamen
 * („New York“) bleiben. Andere Parameter unverändert.
 */
export function listRaw(entry, raw) {
  if (!multiParam(entry) || typeof raw !== "string") return raw;
  const text = entry.type === "labellist" ? raw.normalize("NFC") : raw;
  return text.replace(/ *, */g, ",").replace(/^ +| +$/g, "");
}

/** Rohwert eines Parameters aus der Adresse: der erste, bei Listen aus Zonen/Kurznamen alle Vorkommen mit Komma verbunden. */
export function rawFromSearch(params, entry) {
  if (!params.has(entry.name)) return null;
  return multiParam(entry) ? params.getAll(entry.name).join(",") : String(params.get(entry.name) ?? "");
}

/** Einen Rohwert gegen einen Schema-Eintrag prüfen. Liefert { ok: true, value } oder { ok: false }. */
export function checkParam(entry, raw, zones = [], intl = globalThis.Intl) {
  const fail = { ok: false };
  if (!entry || typeof raw !== "string") return fail;
  if (multiParam(entry)) {
    // Listen: erst bereinigen (Leerzeichen um die Kommas, NFC), dann in Zeichen messen – nicht in UTF-16-Einheiten.
    if (raw.length > rawLimit(entry) * LIST_SLACK) return fail;
    raw = listRaw(entry, raw);
    if ([...raw].length > rawLimit(entry)) return fail;
  } else if (raw.length > rawLimit(entry)) return fail;
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
    case "zonelist": {
      // Jede Zone einzeln geprüft; ein unzulässiger oder doppelter Eintrag verwirft den ganzen Wert – sonst passten die
      // Kurznamen (?tzl=, gleiche Reihenfolge) nicht mehr zu ihren Zonen.
      const items = raw.split(",");
      if (items.length > (entry.maxItems || MAX_ZONES)) return fail;
      const values = [];
      for (const item of items) {
        const zone = checkZone(item, zones, intl);
        if (!zone || values.some((v) => v.toLowerCase() === zone.toLowerCase())) return fail;
        values.push(zone);
      }
      return { ok: true, value: Object.freeze(values) };
    }
    case "labellist": {
      const items = raw.split(",");
      const len = Math.min(entry.len || ZONE_LABEL_LEN, MAX_LEN);
      const charset = entry.charset || ZONE_LABEL_CHARS;
      if (items.length > (entry.maxItems || MAX_ZONES) || !items.some(Boolean)) return fail;
      for (const item of items) {
        if (item && !([...item].length <= len && item.trim() === item && charset.test(item))) return fail;
      }
      return { ok: true, value: Object.freeze(items) };
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
    case "hours": {
      const value = parseHours(raw);
      return value ? { ok: true, value: Object.freeze(value) } : fail;
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
 * Parameter mit unzulässigem Wert (für eine Konsolenzeile, nie für das DOM). Doppelte Namen: Der erste gilt – außer bei
 * tz und tzl, dort zählen alle (?tz=Europe/London&tz=Asia/Tokyo wie ?tz=Europe/London,Asia/Tokyo).
 */
export function parseParams(search, zones = [], intl = globalThis.Intl, schema = PARAM_SCHEMA) {
  const params = new URLSearchParams(typeof search === "string" ? search : "");
  const out = { ...paramDefaults(schema), ignored: [] };
  for (const entry of schema) {
    if (!params.has(entry.name)) continue;
    const result = checkParam(entry, rawFromSearch(params, entry), zones, intl);
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
  click: { freq: 2000, dur: 0.02 },   // Prüfbild test=sync: kurzer Klick auf jeder vollen Sekunde
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
 * mode "click": ein kurzer Klick auf jeder vollen Sekunde, auch zur Minute (Prüfbild test=sync).
 * Ergebnis: [{ second (Unix-Sekunde des Servers), at (Audiozeit s), kind, freq, dur }].
 */
export function planTones(clock, { mode = "seconds", afterSecond = -Infinity, horizonMs = 1500 } = {}) {
  const out = [];
  const first = Math.max(Math.floor(clock.server / 1000) + 1, afterSecond + 1);
  const last = Math.floor((clock.server + horizonMs) / 1000);
  for (let second = first; second <= last; second += 1) {
    const inMinute = ((second % 60) + 60) % 60;
    let kind = null;
    if (mode === "click") kind = "click";
    else if (inMinute === 0) kind = "long";
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

// --- Prüfbild test=sync (Studiouhr B5) ---------------------------------------------------
/** Schrittweite und Grenzen beim Einmessen von ?lead= im Prüfbild (wie im Schema: 0 … 200 ms). */
export const LEAD_STEP_MS = 10;
export const LEAD_MAX_MS = 200;
/** So viel früher darf der Zeitgeber feuern und zählt trotzdem schon zur nächsten Sekunde. */
export const FLASH_EARLY_MS = 20;

/**
 * Soll das Prüfbild laufen? Nur mit test=sync ausdrücklich in der Adresse (erster Wert, wie parseParams):
 * "off" ohne den Parameter, "reduced", wenn das System weniger Bewegung wünscht (dann nur ein Hinweis, kein Blitz),
 * "eink" auf E-Ink (dort gibt es keinen Sekundentakt), sonst "run".
 */
export function testMode(search, { reduced = false, eink = false } = {}) {
  let value = null;
  try { value = new URLSearchParams(typeof search === "string" ? search : "").get("test"); } catch (error) { value = null; }
  if (value !== "sync") return "off";
  if (reduced) return "reduced";
  return eink ? "eink" : "run";
}

/**
 * Stand des Sekundenblitzes zur angezeigten Serverzeit: Die Fläche wechselt genau zur vollen Sekunde – hell in
 * geraden, dunkel in ungeraden Sekunden, also ein Wechsel je Sekunde (höchstens 1 Hz, ein Hell-Dunkel-Paar dauert 2 s).
 * Liefert { second (Unix-Sekunde), on, delay (ms bis zum nächsten Wechsel, mindestens 1) } oder null.
 */
export function flashStep(serverMs) {
  if (!Number.isFinite(serverMs)) return null;
  const second = Math.floor((serverMs + FLASH_EARLY_MS) / 1000);
  return { second, on: second % 2 === 0, delay: Math.max(1, Math.ceil((second + 1) * 1000 - serverMs)) };
}

/** Vorlauf im Prüfbild um einen Schritt ändern (dir: +1 oder −1), begrenzt auf 0 … LEAD_MAX_MS. */
export function leadStep(lead, dir) {
  const base = Number.isFinite(lead) ? lead : 0;
  return Math.min(LEAD_MAX_MS, Math.max(0, Math.round(base) + (dir > 0 ? LEAD_STEP_MS : -LEAD_STEP_MS)));
}

/**
 * Adresse ohne das Prüfbild: Abfrageteil mit „?“ oder leer. lead: der im Prüfbild eingemessene Vorlauf; null: Der
 * Vorlauf wurde nicht geändert, ein lead= der Adresse bleibt, wie es ist. Ein eingemessener Wert 0 steht mit einem
 * Profil (?p=) ausdrücklich als lead=0 da – sonst gälte nach dem Neuladen wieder der Vorlauf des Profils; ohne Profil
 * ist 0 der Standard und lead= entfällt, außer mit keepZero (clocklink.testDoneSearch: Ohne lead=0 gälte der gemerkte
 * Stand). Unzulässige Werte: ohne lead.
 */
export function testDoneSearch(search, lead = null, { keepZero = false } = {}) {
  const params = new URLSearchParams(typeof search === "string" ? search : "");
  params.delete("test");
  if (lead === null || lead === undefined) { /* unverändert */ }
  else if (Number.isInteger(lead) && lead >= 0 && lead <= LEAD_MAX_MS && (lead > 0 || params.has("p") || keepZero)) params.set("lead", String(lead));
  else params.delete("lead");
  const text = params.toString().replace(/%2C/g, ",").replace(/%3A/g, ":").replace(/%2F/g, "/");
  return text ? `?${text}` : "";
}

// --- Statuszeile: PTP und Holdover (Studiouhr B3) -----------------------------------------
/** Zustände von PTP aus /api/v1/time (wie PTP_STATES in server.py). */
export const PTP_STATES = Object.freeze(["off", "down", "master", "locked", "acquiring", "passive", "fault", "unknown"]);
/** Symbol und Stufe je Zustand; off und unknown zeigen nichts. Bedeutung trägt immer auch der Text. */
export const PTP_SHOWN = Object.freeze({
  master: { icon: "◈", level: "good" }, locked: { icon: "◆", level: "good" }, acquiring: { icon: "◇", level: "warn" },
  passive: { icon: "◇", level: "info" }, fault: { icon: "✕", level: "crit" }, down: { icon: "✕", level: "crit" },
});
/** Holdover: ein „H“ im gestrichelten Kreis (clock.css) – ein Buchstabe, den jede Schrift hat, auch am Smart-TV. */
export const HOLDOVER_ICON = "H";

/** Dauer eines Holdovers grob: „< 1 min“, „12 min“, „2 h 5 min“, „3 d 4 h“; ohne brauchbare Angabe "". */
export function holdSpan(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 1) return "< 1 min";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

/**
 * Was die Statuszeile über PTP und Holdover zeigt – nur aus festen Werten: { ptp: null | { state, icon, level },
 * holdover: null | { icon, span } }. Unbekannte oder fremde Werte aus der Antwort zeigen nichts (nie als Text ins DOM).
 */
export function statusChips(status) {
  const s = status && typeof status === "object" ? status : {};
  const state = typeof s.ptp_state === "string" && PTP_STATES.includes(s.ptp_state) ? s.ptp_state : "unknown";
  const shown = Object.prototype.hasOwnProperty.call(PTP_SHOWN, state) ? PTP_SHOWN[state] : null;
  return {
    ptp: shown ? { state, icon: shown.icon, level: shown.level } : null,
    holdover: s.holdover === true ? { icon: HOLDOVER_ICON, span: holdSpan(s.holdover_seconds) } : null,
  };
}

// --- On-Air/REC-Signal (Studiouhr B4) --------------------------------------------------------------------
/** Feste Zustände des Signals (wie clocksignal.STATES auf dem Server). */
export const SIGNAL_STATES = Object.freeze(["off", "on_air", "rec"]);
/** Abstand der Zustandsabfrage: mit ?signal=1 jede Sekunde, sonst alle 5 s. */
export const POLL_MS = 5_000;
export const SIGNAL_POLL_MS = 1_000;

/** Wert aus /api/v1/time prüfen: nur ein fester Zustand, alles andere ist „off“. */
export function signalState(value) {
  return typeof value === "string" && SIGNAL_STATES.includes(value) ? value : "off";
}

/** Abstand der Zustandsabfrage in ms für diese Parameter. */
export function pollInterval(params = {}) {
  return params && params.signal === true ? SIGNAL_POLL_MS : POLL_MS;
}

/**
 * Was der Bildschirm zeigt: { state, local, stale }. Das zentrale Signal zählt nur mit ?signal=1 (enabled) und geht vor;
 * ist es aus, gilt das lokale „On Air“ der Taste O (local: nur dieses Gerät). stale: Der Server antwortet seit
 * staleMs nicht mehr – der zuletzt gemeldete Zustand bleibt stehen, ist aber als ungewiss markiert.
 */
export function signalView({ enabled = false, central = "off", local = false, sinceOkMs = 0, staleMs = STALE_MS } = {}) {
  const state = enabled ? signalState(central) : "off";
  if (state !== "off") return { state, local: false, stale: !(sinceOkMs <= staleMs) };
  if (local === true) return { state: "on_air", local: true, stale: false };
  return { state: "off", local: false, stale: false };
}

/**
 * Taste O: { local, blocked }. Solange der Bildschirm das zentrale Signal zeigt, schaltet die Taste nichts (blocked) –
 * sonst stünde nach dem zentralen „Aus“ unbemerkt ein lokales „On Air“ da. Ohne zentrales Signal wechselt local.
 */
export function signalToggle({ enabled = false, central = "off", local = false } = {}) {
  if (enabled && signalState(central) !== "off") return { local: false, blocked: true };
  return { local: local !== true, blocked: false };
}

/**
 * Wann das Signal von selbst ausgeht (ms seit 1970) oder null. until ist { rev, at } aus der Antwort auf das eigene
 * Setzen; es gilt nur, solange der Server noch denselben Stand (signal_rev) meldet und die Zeit nicht um ist.
 */
export function signalExpiry({ state = "off", rev = "", until = null, now = 0 } = {}) {
  if (signalState(state) === "off" || !until || typeof rev !== "string" || !rev) return null;
  return until.rev === rev && Number.isFinite(until.at) && until.at > now ? until.at : null;
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
