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

export function fmtTime(unix, seconds = true) {
  return new Date(unix * 1000).toLocaleTimeString("de-DE", seconds
    ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : { hour: "2-digit", minute: "2-digit" });
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
