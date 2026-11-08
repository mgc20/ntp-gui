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

// Alle Zahlen im Dashboard laufen über diesen deutschen Formatierer: Komma als
// Dezimalzeichen, Punkt als Tausendertrenner. „-0,000“ nach dem Runden wird zu „0,000“.
const FIXED = new Map();
export function fmtFixed(value, digits = 0) {
  if (!isNum(value)) return "–";
  let format = FIXED.get(digits);
  if (!format) {
    format = new Intl.NumberFormat("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    FIXED.set(digits, format);
  }
  const text = format.format(value);
  return /^-0(,0*)?$/.test(text) ? text.slice(1) : text;
}

// Sekunden in eine lesbare Größe (ns/µs/ms/s).
export function fmtSeconds(value, digits = 3, signed = false) {
  if (!isNum(value)) return "–";
  const abs = Math.abs(value);
  const sign = signed && value > 0 ? "+" : "";
  if (abs === 0) return "0 s";
  if (abs < 1e-6) return `${sign}${fmtFixed(value * 1e9, 0)} ns`;
  if (abs < 1e-3) return `${sign}${fmtFixed(value * 1e6, abs < 1e-5 ? 2 : 1)} µs`;
  // Höchstens fünf signifikante Stellen – „100.000 ms“ läse sich im Deutschen wie hunderttausend.
  if (abs < 1) return `${sign}${fmtFixed(value * 1e3, Math.min(digits, abs >= 0.1 ? 1 : 3))} ms`;
  return `${sign}${fmtFixed(value, digits)} s`;
}

export function fmtNs(value) {
  return isNum(value) ? fmtSeconds(value / 1e9, 2, true) : "–";
}

export function fmtDuration(seconds) {
  if (!isNum(seconds)) return "–";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
  return `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h`;
}

export function fmtLogInterval(exponent) {
  if (!isNum(exponent)) return "–";
  const seconds = 2 ** exponent;
  return seconds < 1 ? `${fmtFixed(seconds, 3).replace(/0+$/, "")} s` : fmtDuration(seconds);
}

export function fmtNumber(value, digits = 0) {
  return fmtFixed(value, digits);
}

// Anfragen pro Minute: ganze Zahl, nur unter 10/min mit einer Nachkommastelle.
export function fmtRate(value) {
  return isNum(value) ? fmtFixed(value, Math.abs(value) < 10 && value !== 0 ? 1 : 0) : "–";
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
// method: "toLocaleString", "toLocaleDateString" oder "toLocaleTimeString".
export function fmtZoned(unix, zone, options = {}, locale = "de-DE", method = "toLocaleString") {
  const z = serverZone(zone);
  if (!z) return new Date(unix * 1000)[method](locale, options);
  return new Date((unix + z.shift) * 1000)[method](locale, { ...options, timeZone: z.timeZone });
}

// zone: system-Objekt des Servers (tz_name/utc_offset) oder ein Offset in Sekunden.
export function fmtTime(unix, seconds = true, zone = null) {
  const options = seconds ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : { hour: "2-digit", minute: "2-digit" };
  return fmtZoned(unix, zone, options, "de-DE", "toLocaleTimeString");
}

// Datum und Uhrzeit des Servers für die Kopfzeile. Ohne tz_name und utc_offset (älterer Server) gilt UTC.
export function fmtServerDateTime(sys, locale = "de-DE") {
  return fmtZoned(sys?.time || 0, serverZone(sys) ? sys : 0, {}, locale);
}

// Hinweis bei Verbindungsverlust: seit wann die angezeigten Werte nicht mehr frisch sind.
export function staleText(lastOkMs, zone = null) {
  if (!isNum(lastOkMs)) return "Keine Verbindung zum Server – die angezeigten Werte sind veraltet.";
  return `Keine Verbindung zum Server – Werte veraltet seit ${fmtTime(lastOkMs / 1000, true, zone)}. Neuer Versuch läuft.`;
}

// ISO-Zeit (z. B. gpsd „2026-11-08T12:34:56.000Z“) als „08.11.26, 12:34:56 UTC“.
export function fmtIsoUtc(iso) {
  const date = new Date(iso);
  if (!iso || Number.isNaN(date.getTime())) return "–";
  return `${date.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium", timeZone: "UTC" })} UTC`;
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
