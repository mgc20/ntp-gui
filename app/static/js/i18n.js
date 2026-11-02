// Mehrsprachigkeit – bewusst winzig, ohne Bibliothek.
//
// Kataloge: /static/i18n/<sprache>.json, verschachteltes JSON im i18next-v4-Format (Weblate:
// „i18next JSON v4“). Deutsch (de) ist die Referenz und immer vollständig; Englisch darf
// hinterherhinken – fehlt ein Schlüssel, steht der deutsche Text da, nie der rohe Schlüssel.
//
//   t("nav.overview")                       → „Übersicht“
//   t("overview.facts.clients", { count })  → „1 Client“ / „5 Clients“ (Plural: _one/_other)
//   t("x.y", { name: "GPS" })               → ersetzt {name}
//
// Texte landen wie überall nur per textContent im DOM; Parameter werden nicht als HTML gelesen.
// Die Sprache gilt je Browser (localStorage), nicht für den Server: Jeder Betrachter wählt selbst.
// Die ⓘ-Erklärungen (help*.js) und Texte vom Server (Hinweise, Ereignisse) sind vorerst deutsch.

export const LANGUAGES = [
  { code: "de", label: "Deutsch" },
  { code: "en", label: "English" },
];
export const REFERENCE = "de";
const STORAGE_KEY = "ntp-gui-lang";

const catalogs = new Map();   // Sprache → Objekt
let current = REFERENCE;
const listeners = new Set();

function supported(code) {
  return LANGUAGES.some((l) => l.code === code);
}

function readStored() {
  try { return window.localStorage.getItem(STORAGE_KEY); } catch (error) { return null; }
}

function writeStored(code) {
  try { window.localStorage.setItem(STORAGE_KEY, code); } catch (error) { /* privater Modus */ }
}

/** Sprache des Browsers (navigator.languages), sonst Deutsch. */
export function browserLanguage(list = (typeof navigator !== "undefined" && (navigator.languages || [navigator.language])) || []) {
  for (const tag of list) {
    const code = String(tag || "").toLowerCase().split(/[-_]/)[0];
    if (supported(code)) return code;
  }
  return REFERENCE;
}

export function language() { return current; }

/** Wert unter einem Punkt-Pfad („nav.overview“) – nur Strings zählen. */
function lookup(catalog, key) {
  let node = catalog;
  for (const part of key.split(".")) {
    if (!node || typeof node !== "object" || !Object.prototype.hasOwnProperty.call(node, part)) return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

const pluralRules = new Map();
function pluralForm(lang, count) {
  let rules = pluralRules.get(lang);
  if (!rules) {
    try { rules = new Intl.PluralRules(lang); } catch (error) { rules = { select: (n) => (n === 1 ? "one" : "other") }; }
    pluralRules.set(lang, rules);
  }
  return rules.select(count);
}

function find(lang, key, params) {
  const catalog = catalogs.get(lang);
  if (!catalog) return undefined;
  if (params && typeof params.count === "number") {
    const form = lookup(catalog, `${key}_${pluralForm(lang, params.count)}`) ?? lookup(catalog, `${key}_other`);
    if (form !== undefined) return form;
  }
  return lookup(catalog, key);
}

/** Gibt es den Schlüssel in der Referenz (oder der aktuellen Sprache)? */
export function has(key) {
  return find(current, key, null) !== undefined || find(REFERENCE, key, null) !== undefined
    || find(REFERENCE, key, { count: 2 }) !== undefined;
}

/** Übersetzung mit {platzhalter}; Rückfall: Deutsch, dann der Schlüssel selbst. */
export function t(key, params) {
  let text = find(current, key, params);
  if (text === undefined && current !== REFERENCE) text = find(REFERENCE, key, params);
  if (text === undefined) return key;
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) =>
    (Object.prototype.hasOwnProperty.call(params, name) && params[name] !== null && params[name] !== undefined
      ? String(params[name]) : match));
}

async function load(lang) {
  if (catalogs.has(lang)) return true;
  try {
    const response = await fetch(`/static/i18n/${lang}.json`, { credentials: "same-origin", cache: "no-cache" });
    if (!response.ok) return false;
    const data = await response.json();
    if (!data || typeof data !== "object" || Array.isArray(data)) return false;
    catalogs.set(lang, data);
    return true;
  } catch (error) {
    return false;
  }
}

/** Beim Start: gespeicherte Wahl, sonst Browsersprache; Deutsch wird immer mitgeladen (Rückfall). */
export async function initI18n() {
  const stored = readStored();
  const wanted = supported(stored) ? stored : browserLanguage();
  await load(REFERENCE);
  current = wanted !== REFERENCE && await load(wanted) ? wanted : REFERENCE;
  applyDocument();
  return current;
}

export async function setLanguage(code) {
  if (!supported(code)) return current;
  if (code !== REFERENCE && !await load(code)) return current;
  current = code;
  writeStored(code);
  applyDocument();
  for (const fn of listeners) { try { fn(current); } catch (error) { console.error(error); } }
  return current;
}

export function onLanguageChange(fn) { listeners.add(fn); }

/**
 * Feste Texte in index.html: data-i18n="schlüssel" setzt textContent,
 * data-i18n-title / data-i18n-aria-label die Attribute.
 */
export function applyDocument(root = typeof document !== "undefined" ? document : null) {
  if (!root) return;
  if (root.documentElement) root.documentElement.lang = current;
  for (const node of root.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of root.querySelectorAll("[data-i18n-title]")) node.setAttribute("title", t(node.dataset.i18nTitle));
  for (const node of root.querySelectorAll("[data-i18n-aria-label]")) node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
}

/** Für Tests: Kataloge direkt setzen. */
export function _setCatalogs(map, lang = REFERENCE) {
  catalogs.clear();
  for (const [code, data] of Object.entries(map)) catalogs.set(code, data);
  current = lang;
}
