import { language } from "./i18n.js";

// Kleine Helfer: DOM-Bau, Formatierung, API-Zugriff.
// Daten aus der API landen ausschließlich als Text im DOM (textContent),
// nie als HTML – Hostnamen, Logzeilen oder Gerätenamen können so nichts
// einschleusen.

export function el(tag, attrs = {}, ...children) {
  const node = tag === "svg" || attrs.svg ? document.createElementNS("http://www.w3.org/2000/svg", tag)
    : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false || key === "svg") continue;
    if (key === "class") node.setAttribute("class", value);
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    // CSSOM statt style-Attribut: Die Content-Security-Policy (style-src 'self') sperrt style-Attribute.
    else if (key === "style") node.style.cssText = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "value" && "value" in node) node.value = value;
    else if (key === "checked") node.checked = Boolean(value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function svgEl(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  return node;
}

// Vertrauenswürdige, im Code geschriebene Texte mit **fett** und `code`.
export function rich(text) {
  const span = document.createElement("span");
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  for (const part of parts) {
    if (part.startsWith("**") && part.endsWith("**")) span.append(el("strong", { text: part.slice(2, -2) }));
    else if (part.startsWith("`") && part.endsWith("`")) span.append(el("code", { text: part.slice(1, -1) }));
    else if (part) span.append(document.createTextNode(part));
  }
  return span;
}

export function isNum(value) {
  return typeof value === "number" && Number.isFinite(value);
}

// --- Zahlen und Zeiten (T2) ---------------------------------------------------
// Alle Zahlen im Dashboard laufen über fmtNumber und seine Verwandten: Intl.NumberFormat in der
// gewählten Sprache (Deutsch: Komma als Dezimalzeichen, Punkt als Tausendertrenner) und **ohne
// Nullen am Ende** („± 1 ms“ statt „± 1,000 ms“ – das läse sich im Deutschen wie tausend).
// Feste Nachkommastellen nur noch für Achsenbeschriftungen (fmtFixed), wo benachbarte Striche
// gleich breit sein sollen. `toFixed` ist in den Seiten verboten (tests/test_gui_bausteine.py).
const LOCALES = { de: "de-DE", en: "en-GB" };
/** Minuszeichen aller formatierten Zahlen (fmtNumber, fmtSeconds, fmtPpm, Achsen): U+2212. */
export const MINUS = "\u2212";

/** BCP-47-Tag der gewählten Sprache für Intl (Deutsch, wenn unbekannt). */
export function locale() {
  return LOCALES[language()] || LOCALES.de;
}

const NUMBER_FORMATS = new Map();
function numberFormat(options) {
  const key = `${locale()}|${JSON.stringify(options)}`;
  let format = NUMBER_FORMATS.get(key);
  if (!format) {
    format = new Intl.NumberFormat(locale(), options);
    NUMBER_FORMATS.set(key, format);
  }
  return format;
}

/**
 * Zahl in der gewählten Sprache. digits = höchstens so viele Nachkommastellen (Nullen am Ende
 * fallen weg). opts: { fixed: true – genau digits Stellen (nur für Achsen), sig: n – höchstens n
 * signifikante Stellen statt digits, signed: true – „+“ vor positiven Werten (nie „+0“),
 * group: false – ohne Tausenderpunkt (für Sekunden: „1000 s“ statt „1.000 s“, das läse sich als 1 s) }.
 * „-0“ nach dem Runden wird zu „0“. Negative Werte stehen immer mit „−“ (MINUS) da, nie mit „-“.
 */
export function fmtNumber(value, digits = 0, opts = {}) {
  if (!isNum(value)) return "–";
  const options = opts.sig
    ? { maximumSignificantDigits: opts.sig }
    : { minimumFractionDigits: opts.fixed ? digits : 0, maximumFractionDigits: digits };
  if (opts.group === false) options.useGrouping = false;
  let text = numberFormat(options).format(value);
  if (/^-0([.,]0*)?$/.test(text)) text = text.slice(1);
  // Ein Minuszeichen in der ganzen App: das typografische „−“ (U+2212), mit und ohne signed.
  if (text.startsWith("-")) return `${MINUS}${text.slice(1)}`;
  if (!opts.signed) return text;
  return /^0([.,]0*)?$/.test(text) ? text : `+${text}`;
}

// Feste Nachkommastellen (mit Nullen am Ende) – nur für Achsenbeschriftungen.
export function fmtFixed(value, digits = 0) {
  return fmtNumber(value, digits, { fixed: true });
}

// Messwert in Sekunden mit passender Einheit (ns/µs/ms/s), ohne Nullen am Ende.
// digits: höchstens so viele Nachkommastellen in ms bzw. s; signed: „+“ vor positiven Werten.
// Vorzeichen und Minuszeichen kommen aus fmtNumber: kein „+0 ns“, immer „−“. Ohne Tausenderpunkt.
export function fmtSeconds(value, digits = 3, signed = false) {
  if (!isNum(value)) return "–";
  const abs = Math.abs(value);
  if (abs === 0) return "0 s";
  // [Einheit, Faktor, Nachkommastellen]. Höchstens vier bis fünf signifikante Stellen.
  const units = [
    ["ns", 1e9, abs < 1e-8 ? 1 : 0],
    ["µs", 1e6, abs < 1e-5 ? 2 : 1],
    ["ms", 1e3, Math.min(digits, abs >= 0.1 ? 1 : abs >= 0.01 ? 2 : 3)],
    ["s", 1, digits],
  ];
  let index = abs < 1e-6 ? 0 : abs < 1e-3 ? 1 : abs < 1 ? 2 : 3;
  // Rundet der Wert auf 1000 der Einheit (999,96 µs → „1.000 µs“), gilt die nächstgrößere: „1 ms“.
  while (index < 3) {
    const [, factor, places] = units[index];
    if (Math.abs(Number((abs * factor).toFixed(places))) < 1000) break;
    index += 1;
  }
  const [unit, factor, places] = units[index];
  return `${fmtNumber(value * factor, places, { group: false, signed })} ${unit}`;
}

export function fmtNs(value) {
  return isNum(value) ? fmtSeconds(value / 1e9, 2, true) : "–";
}

/**
 * Zeitspanne: unter einer Sekunde mit passender Einheit (ns/µs/ms), sonst s, min, h, d – ohne
 * Nullteile am Ende („1 h“ statt „1 h 0 min“). Negative Spannen gelten als 0.
 */
export function fmtDuration(seconds) {
  if (!isNum(seconds)) return "–";
  if (seconds > 0 && seconds < 0.5) return fmtSeconds(seconds);
  const s = Math.max(0, Math.round(seconds));
  const pair = (big, bigUnit, small, smallUnit) => (small ? `${big} ${bigUnit} ${small} ${smallUnit}` : `${big} ${bigUnit}`);
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return pair(Math.floor(s / 3600), "h", Math.floor((s % 3600) / 60), "min");
  return pair(Math.floor(s / 86400), "d", Math.floor((s % 86400) / 3600), "h");
}

export function fmtLogInterval(exponent) {
  if (!isNum(exponent)) return "–";
  const seconds = 2 ** exponent;
  return seconds < 1 ? `${fmtNumber(seconds, 3)} s` : fmtDuration(seconds);
}

/**
 * Frequenzabweichung in ppm. Ohne digits richtet sich die Genauigkeit nach der Größe
 * (12,3 ppm · 1,23 ppm · 0,123 ppm), Nullen am Ende fallen weg. signed: „+“ davor. Ohne
 * Tausenderpunkt („1235 ppm“ – „1.235 ppm“ läse sich wie gut 1 ppm).
 */
export function fmtPpm(value, { digits, signed = false } = {}) {
  if (!isNum(value)) return "–";
  const abs = Math.abs(value);
  const places = isNum(digits) ? digits : abs >= 100 ? 0 : abs >= 10 ? 1 : abs >= 1 ? 2 : 3;
  return `${fmtNumber(value, places, { signed, group: false })} ppm`;
}

// Anfragen pro Minute: ganze Zahl, nur unter 10/min mit (höchstens) einer Nachkommastelle.
export function fmtRate(value) {
  return isNum(value) ? fmtNumber(value, Math.abs(value) < 10 ? 1 : 0) : "–";
}

// Zeitzone des Servers für Intl. Bevorzugt der IANA-Name (system.tz_name, z. B. „Europe/Berlin“): Damit
// steht jedes Ereignis mit der Sommer-/Winterzeit seines eigenen Tages da. Kennt der Browser den Namen
// nicht (oder der Server liefert keinen), gilt system.utc_offset – der stimmt nur für die aktuelle Zeit.
// Ohne beides (älterer Server): Zeitzone des Browsers. „zone“ darf auch eine Zahl sein (nur Offset).
const ZONES = new Map();
export function knownZone(name) {
  if (typeof name !== "string" || !name || name.length > 64) return false;
  if (!ZONES.has(name)) {
    let ok = false;
    try { new Intl.DateTimeFormat("de-DE", { timeZone: name }); ok = true; } catch (error) { ok = false; }
    ZONES.set(name, ok);
  }
  return ZONES.get(name);
}

export function serverZone(zone) {
  if (isNum(zone)) return { timeZone: "UTC", shift: zone };
  if (!zone || typeof zone !== "object") return null;
  // system.timezone ist meist nur die Abkürzung („CEST“) – als IANA-Name nur mit „/“ brauchbar.
  for (const name of [zone.tz_name, typeof zone.timezone === "string" && zone.timezone.includes("/") ? zone.timezone : null]) {
    if (knownZone(name)) return { timeZone: name, shift: 0 };
  }
  if (isNum(zone.utc_offset)) return { timeZone: "UTC", shift: zone.utc_offset };
  return null;
}

// Zeitpunkt (Unix-Sekunden) mit Intl-Optionen in der Zeitzone des Servers formatieren.
// method: "toLocaleString", "toLocaleDateString" oder "toLocaleTimeString". Ohne lang: gewählte Sprache.
export function fmtZoned(unix, zone, options = {}, lang = null, method = "toLocaleString") {
  const tag = lang || locale();
  const z = serverZone(zone);
  if (!z) return new Date(unix * 1000)[method](tag, options);
  return new Date((unix + z.shift) * 1000)[method](tag, { ...options, timeZone: z.timeZone });
}

// zone: system-Objekt des Servers (tz_name/utc_offset) oder ein Offset in Sekunden.
export function fmtTime(unix, seconds = true, zone = null) {
  const options = seconds ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : { hour: "2-digit", minute: "2-digit" };
  return fmtZoned(unix, zone, options, null, "toLocaleTimeString");
}

const DATE_PARTS = {
  short: { dateStyle: "short" }, medium: { dateStyle: "medium" }, long: { dateStyle: "long" },
  numeric: { day: "2-digit", month: "2-digit", year: "numeric" }, day: { day: "2-digit", month: "2-digit" },
};

/**
 * Zeitpunkt als Datum (und Uhrzeit) in der gewählten Sprache. value: Unix-Sekunden, Date oder
 * ISO-Text („2026-11-08T12:34:56Z“, auch nur „2026-11-08“ – dann ohne Uhrzeit, als Kalendertag).
 * opts: { date: "short" | "medium" | "long" | "numeric" | "day" | false, time: "short" | "medium" | false,
 *         zone – Zeitzone des Servers (system-Objekt oder Offset), utc: true – in UTC,
 *         empty – Text für fehlende Werte (Standard „–“) }.
 */
export function fmtDate(value, opts = {}) {
  const empty = opts.empty ?? "–";
  let unix = null;
  let dayOnly = false;
  if (isNum(value)) unix = value;
  else if (value instanceof Date) unix = value.getTime() / 1000;
  else if (typeof value === "string" && value) {
    dayOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
    const ms = Date.parse(dayOnly ? `${value}T00:00:00Z` : value);
    unix = Number.isNaN(ms) ? null : ms / 1000;
  }
  if (!isNum(unix)) return empty;
  const date = opts.date === undefined ? "short" : opts.date;
  const time = dayOnly ? false : opts.time === undefined ? "short" : opts.time;
  const datePart = date ? DATE_PARTS[date] || DATE_PARTS.short : {};
  let options;
  if (datePart.dateStyle || !date) {
    options = { ...datePart, ...(time ? { timeStyle: time } : {}) };
  } else {
    options = { ...datePart, ...(time ? { hour: "2-digit", minute: "2-digit", ...(time === "medium" ? { second: "2-digit" } : {}) } : {}) };
  }
  const method = date && time ? "toLocaleString" : date ? "toLocaleDateString" : "toLocaleTimeString";
  const zone = opts.utc || dayOnly ? 0 : opts.zone ?? null;
  return fmtZoned(unix, zone, options, null, method);
}

// Datum und Uhrzeit des Servers für die Kopfzeile. Ohne tz_name und utc_offset (älterer Server) gilt UTC.
export function fmtServerDateTime(sys, lang = null) {
  return fmtZoned(sys?.time || 0, serverZone(sys) ? sys : 0, {}, lang);
}

// Hinweis bei Verbindungsverlust: seit wann die angezeigten Werte nicht mehr frisch sind.
export function staleText(lastOkMs, zone = null) {
  if (!isNum(lastOkMs)) return "Keine Verbindung zum Server – die angezeigten Werte sind veraltet.";
  return `Keine Verbindung zum Server – Werte veraltet seit ${fmtTime(lastOkMs / 1000, true, zone)}. Neuer Versuch läuft.`;
}

// Serveruhr im Browser fortschreiben: Die Uhr des Betrachter-PCs kann vor- oder nachgehen, Zeitstempel des
// Servers (z. B. reload.json) dürfen nur mit der Serverzeit verglichen werden. serverClock() merkt sich
// beim Abruf des Status Serverzeit (s) und Browserzeit (ms), serverNow() rechnet daraus die Serverzeit jetzt.
export function serverClock(serverTime, browserMs = Date.now()) {
  return isNum(serverTime) && isNum(browserMs) ? { server: serverTime, browser: browserMs } : null;
}

export function serverNow(clock, browserMs = Date.now()) {
  return clock ? clock.server + (browserMs - clock.browser) / 1000 : browserMs / 1000;
}

// Neustart der Zeitdienste abgeschlossen? Nur ein Ergebnis, das nach dem Auslösen (Serverzeit) geschrieben wurde.
export function reloadSettled(status, started) {
  return Boolean(status) && isNum(status.time) && status.time >= started && (status.state === "done" || status.state === "error");
}

// ISO-Zeit (z. B. gpsd „2026-11-08T12:34:56.000Z“) als „08.11.26, 12:34:56 UTC“.
export function fmtIsoUtc(iso) {
  const text = fmtDate(iso, { date: "short", time: "medium", utc: true, empty: "" });
  return text ? `${text} UTC` : "–";
}

export function sourceLabel(source) {
  if (!source) return "–";
  return source.hostname || source.name || "–";
}

// --- API -------------------------------------------------------------------

export async function apiGet(path) {
  const response = await fetch(path, { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = "";
    try { message = (await response.json()).error || ""; } catch (error) { /* keine JSON-Antwort */ }
    const failure = new Error(message || `${path}: HTTP ${response.status}`);
    failure.status = response.status;
    throw failure;
  }
  return response.json();
}

export async function apiPost(path, body) {
  const response = await fetch(path, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-NTP-GUI": "1" },
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await response.json(); } catch (error) { /* leere Antwort */ }
  if (!response.ok) {
    const failure = new Error(data.error || `HTTP ${response.status}`);
    failure.fields = data.fields || {};
    throw failure;
  }
  return data;
}

// Datei als Body hochladen (Sicherung wiederherstellen). Gleicher Schutz wie apiPost: Pflicht-Kopf X-NTP-GUI.
export async function apiUpload(path, file, type = "application/gzip") {
  const response = await fetch(path, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": type, "X-NTP-GUI": "1" },
    body: file,
  });
  let data = {};
  try { data = await response.json(); } catch (error) { /* leere Antwort */ }
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

// 1.5.3: Läuft ein Holdover-Test, bricht jeder Neustart von chronyd ihn ab – Zusatz für Rückfragen.
export function holdoverNote(ctx) {
  return ctx?.status?.holdover_active
    ? " Achtung: Gerade läuft ein Holdover-Test – der Neustart bricht ihn ab (das Ergebnis bis jetzt bleibt erhalten)."
    : "";
}

export function storageGet(key, fallback) {
  try { return JSON.parse(window.localStorage.getItem(key)) ?? fallback; } catch (error) { return fallback; }
}

export function storageSet(key, value) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (error) { /* privat */ }
}

// --- Zwischenablage ----------------------------------------------------------
// navigator.clipboard gibt es nur in einem „sicheren Kontext“ (https oder
// localhost). Im LAN wird das Dashboard aber meist per http://<IP>:8080
// geöffnet – dann bleibt nur der alte Weg über ein verstecktes Textfeld und
// document.execCommand("copy"). Liefert true, wenn kopiert wurde; wirft nie.
export async function copyText(text) {
  const value = String(text ?? "");
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(value); return true; } catch (error) { /* weiter mit dem Fallback */ }
  }
  const area = document.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.setAttribute("aria-hidden", "true");
  area.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:0;opacity:0;";
  const active = document.activeElement;
  document.body.append(area);
  let ok = false;
  try {
    area.focus({ preventScroll: true });
    area.select();
    area.setSelectionRange(0, value.length);
    ok = document.execCommand("copy");
  } catch (error) {
    ok = false;
  } finally {
    area.remove();
    if (active && typeof active.focus === "function") active.focus({ preventScroll: true });
  }
  return ok;
}

// Markiert den Inhalt eines Elements, damit nur noch Strg+C fehlt.
export function selectContents(node) {
  if (!node) return false;
  try {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(node);
    selection.removeAllRanges();
    selection.addRange(range);
    return true;
  } catch (error) {
    return false;
  }
}
