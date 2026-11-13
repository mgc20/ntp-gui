// Link-Baukasten der Vollbild-Uhr (Studiouhr A6): Formular aus dem Parameter-Schema, Link bauen, Profile schichten.
//
// Genutzt vom Reiter „Anzeigen“ im Dashboard (pages/displays.js) und vom Panel „Anpassen“ auf /clock. Darum ist die
// Datei öffentlich (CLOCK_PUBLIC_PATHS) und lädt nur andere öffentliche Dateien. Die reinen Funktionen oben kommen
// ohne DOM aus (Node-Tests in tests/test_uhr_profile.py); buildForm() baut das Formular, Werte nur als value bzw.
// textContent. Rangfolge der Werte: Profil < Adresse; ohne Parameter in der Adresse gilt der im Panel gemerkte Stand.
import * as kit from "./clockkit.js";
import { t } from "./i18n.js";

/** Name eines Profils: /clock?p=regie (wie clockprofiles.NAME_RE). */
export const PROFILE_NAME = /^[a-z0-9-]{1,32}$/;
export const MAX_PROFILES = 20;
export const TITLE_MAX = 40;
/** Feste Voreinstellungen des Servers (clockprofiles.PRESETS) in der Reihenfolge der Auswahl. */
export const PRESETS = ["studio", "tile", "banner", "kitchen", "workshop", "night", "nerd"];
/** localStorage: zuletzt im Panel „Anpassen“ übernommener Stand (Abfrageteil ohne „?“). */
export const STORE_KEY = "ntp-gui-clock-custom";
const STORE_MAX = 2000;
/**
 * Nicht im gemerkten Stand: kiosk und lock blenden Leiste bzw. Knopf „Anpassen“ aus. Gemerkt gälten sie für jeden
 * Aufruf von /clock ohne Parameter, und in der Oberfläche führte kein Weg zurück. Darum bietet das Panel sie nicht an
 * und storedQuery() streicht sie; im Link (Dashboard, Adresse) bleiben sie erlaubt.
 */
export const STORE_SKIP = Object.freeze(["kiosk", "lock"]);
/** Ebenso einzelne Werte: layout=tile (Multiviewer-Kachel) blendet Leiste, Knopf „Anpassen“ und Mauszeiger aus. */
export const STORE_SKIP_VALUES = Object.freeze({ layout: Object.freeze(["tile"]) });
/** Neuer Versuch, wenn ein Profil (?p=) nicht geladen werden konnte: 5 s, dann verdoppelt bis 60 s. */
export const PROFILE_RETRY_MS = 5_000;
export const PROFILE_RETRY_MAX_MS = 60_000;

/** Gruppen des Formulars; jeder Schema-Parameter steht in genau einer. */
export const FORM_GROUPS = Object.freeze([
  { key: "look", names: ["design", "layout", "look", "accent", "scale", "weight", "show", "bg", "safe", "shift"] },
  { key: "digits", names: ["color", "sub", "seconds", "h12", "face", "colon", "lz", "date"] },
  { key: "zone", names: ["tz", "lead", "maxerr"] },
  { key: "countdown", names: ["until", "timer", "after", "warn", "beep", "label", "cd"] },
  { key: "mode", names: ["kiosk", "eink", "lock"] },
]);

/** Feste Fenstergrößen der Vorschau (window.open im neuen Tab, kein iframe: frame-ancestors bleibt 'none'). */
export const PREVIEW_SIZES = Object.freeze({
  phone: { width: 390, height: 844 },
  monitor: { width: 1280, height: 720 },
  banner: { width: 1600, height: 200 },
  tile: { width: 480, height: 270 },
  stele: { width: 540, height: 960 },
});

/** Fenster-Merkmale für window.open: feste Größe, ohne Rückverweis auf das Dashboard. */
export function previewFeatures(size) {
  const box = PREVIEW_SIZES[size] || PREVIEW_SIZES.monitor;
  return `popup=yes,width=${box.width},height=${box.height},noopener=yes,noreferrer=yes`;
}

const entryOf = (name, schema = kit.PARAM_SCHEMA) => schema.find((entry) => entry.name === name) || null;
const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** Gültiger Profilname oder null. */
export function profileName(value) {
  return typeof value === "string" && PROFILE_NAME.test(value) ? value : null;
}

/** Wartezeit vor dem n-ten erneuten Profilabruf (n ab 0). */
export function profileRetryDelay(attempt) {
  const n = Number.isInteger(attempt) && attempt > 0 ? Math.min(attempt, 10) : 0;
  return Math.min(PROFILE_RETRY_MS * 2 ** n, PROFILE_RETRY_MAX_MS);
}

/**
 * Was die Uhr nach einem Abgleich mit profiles_rev tut:
 *  - "retry": Profil konnte nicht geladen werden (Netz, 5xx, 401) und die Wartezeit ist um – erneut abrufen.
 *  - "adopt": erster gültiger rev bei geladenem (oder sicher fehlendem) Profil – merken.
 *  - "refetch": rev hat sich geändert – Profil neu holen und vergleichen.
 *  - "none": nichts zu tun.
 * Ein nicht geladenes Profil übernimmt keinen rev: Sonst käme der nächste Abruf erst mit der nächsten Änderung.
 */
export function profileStep({ name = null, loaded = false, error = "", seenRev = null, rev = null, busy = false,
  now = 0, retryAt = 0 } = {}) {
  if (!profileName(name) || busy) return "none";
  if (!loaded && error !== "missing") return now >= retryAt ? "retry" : "none";
  if (typeof rev !== "string" || !rev) return "none";
  if (seenRev === null) return "adopt";
  return rev === seenRev ? "none" : "refetch";
}

/** i18n-Schlüssel für den Titel einer festen Voreinstellung (sonst null: eigener Titel des Profils gilt). */
export function presetTitleKey(profile) {
  if (!profile || profile.builtin !== true || !PRESETS.includes(profile.name)) return null;
  return `pages.displays.preset.${profile.name}`;
}

/** Profilname aus der Adresse (?p=), sonst null. */
export function profileFromSearch(search) {
  return profileName(new URLSearchParams(typeof search === "string" ? search : "").get("p"));
}

/** Rohwert prüfen: true, wenn leer (= Standard) oder für das Schema gültig. */
export function rawValid(name, raw, zones = [], intl = globalThis.Intl) {
  if (raw === undefined || raw === null || raw === "") return true;
  const entry = entryOf(name);
  return Boolean(entry) && kit.checkParam(entry, String(raw), zones, intl).ok;
}

/**
 * Rohwerte (Zeichenketten wie in der Adresse) aus einem Abfrageteil oder Objekt: nur Schema-Namen mit gültigem Wert.
 * Doppelte Namen: Der erste gilt (wie parseParams).
 */
export function rawParams(source, zones = [], intl = globalThis.Intl, schema = kit.PARAM_SCHEMA) {
  const out = {};
  const get = source && typeof source === "object" && !(source instanceof URLSearchParams)
    ? (name) => (Object.prototype.hasOwnProperty.call(source, name) ? source[name] : null)
    : ((params) => (name) => (params.has(name) ? params.get(name) : null))(new URLSearchParams(source || ""));
  for (const entry of schema) {
    const raw = get(entry.name);
    if (raw === null || raw === undefined || raw === "") continue;
    const text = String(raw);
    if (kit.checkParam(entry, text, zones, intl).ok) out[entry.name] = text;
  }
  return out;
}

/** Nennt der Abfrageteil einen Schema-Parameter (auch mit ungültigem Wert)? Dann gilt die Adresse, nicht der Speicher. */
export function hasSchemaParams(search, schema = kit.PARAM_SCHEMA) {
  const params = new URLSearchParams(typeof search === "string" ? search : "");
  return schema.some((entry) => params.has(entry.name));
}

/**
 * Link-Abfrageteil aus Rohwerten: Schema-Reihenfolge, nur gültige Werte, ohne Werte, die dem Standard entsprechen.
 * Ergebnis ohne „?“, leer, wenn alles auf Standard steht.
 */
export function buildQuery(raw, zones = [], intl = globalThis.Intl, schema = kit.PARAM_SCHEMA) {
  const out = new URLSearchParams();
  for (const entry of schema) {
    const value = raw ? raw[entry.name] : undefined;
    if (value === undefined || value === null || value === "") continue;
    const result = kit.checkParam(entry, String(value), zones, intl);
    if (!result.ok || same(result.value, entry.default)) continue;
    out.set(entry.name, String(value));
  }
  return out.toString().replace(/%2C/g, ",").replace(/%3A/g, ":");
}

/** Schichten zusammenführen (spätere gewinnen), ohne Standardwerte zu streichen: ein Override darf zurück auf Standard. */
export function layerQuery(...layers) {
  const merged = Object.assign({}, ...layers.filter(Boolean));
  const out = new URLSearchParams();
  for (const entry of kit.PARAM_SCHEMA) {
    if (merged[entry.name] !== undefined && merged[entry.name] !== "") out.set(entry.name, String(merged[entry.name]));
  }
  return out.toString();
}

/**
 * Abfrageteil, mit dem die Uhr startet: mit Profil Profil < Adresse; ohne Profil die Adresse, wenn sie einen
 * Schema-Parameter oder ein Profil (?p=) nennt; sonst der im Panel gemerkte Stand (stored). Ein Profil-Bildschirm,
 * dessen Profil (noch) nicht geladen ist, zeigt also die Standarduhr, nicht die Panel-Einstellungen dieses Browsers.
 */
export function effectiveQuery({ search = "", stored = "", profile = null, zones = [], intl = globalThis.Intl } = {}) {
  const url = rawParams(search, zones, intl);
  if (profile) return layerQuery(rawParams(profile, zones, intl), url);
  if (!storedApplies(search)) return layerQuery(url);
  return layerQuery(rawParams(storedQuery(stored), zones, intl));
}

/** Gilt der im Panel gemerkte Stand für diese Adresse? Nur ohne Schema-Parameter und ohne Profil (?p=). */
export function storedApplies(search = "") {
  return !hasSchemaParams(search) && !profileFromSearch(search);
}

/** Gemerkten Stand säubern: nur gültige Schema-Werte ohne STORE_SKIP und STORE_SKIP_VALUES, höchstens STORE_MAX Zeichen. */
export function storedQuery(text, zones = [], intl = globalThis.Intl) {
  if (typeof text !== "string" || !text || text.length > STORE_MAX) return "";
  const raw = rawParams(text, zones, intl);
  for (const name of STORE_SKIP) delete raw[name];
  for (const [name, values] of Object.entries(STORE_SKIP_VALUES)) if (values.includes(raw[name])) delete raw[name];
  return buildQuery(raw, zones, intl);
}

/**
 * Gemerkten Stand an einen Wert anpassen, der außerhalb des Panels gewählt wurde (Design in der Leiste, Taste D): Nennt
 * er name, gilt danach value; sonst bleibt er, wie er ist. Ergebnis wie storedQuery().
 */
export function storedWith(text, name, value, zones = [], intl = globalThis.Intl) {
  const clean = storedQuery(text, zones, intl);
  const raw = rawParams(clean, zones, intl);
  if (!Object.prototype.hasOwnProperty.call(raw, name)) return clean;
  raw[name] = value;
  return storedQuery(buildQuery(raw, zones, intl), zones, intl);
}

/** Pfad der Uhr: /clock, /clock?<query>, /clock?p=name[&<query>]. */
export function clockHref(query = "", name = null) {
  const parts = [];
  if (profileName(name)) parts.push(`p=${name}`);
  if (query) parts.push(query);
  return parts.length ? `/clock?${parts.join("&")}` : "/clock";
}

// --- Formular ---------------------------------------------------------------------------------------------------
function node(tag, attrs = {}, ...children) {
  const item = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "text") item.textContent = value;
    else if (key === "class") item.className = value;
    else if (key === "value") item.value = value;
    else item.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children) if (child) item.append(child);
  return item;
}

const EXAMPLES = { until: "20:15", timer: "25m", warn: "300,60,10", tz: "Europe/London", accent: "amber, ff8800" };

function example(name) {
  if (name === "label") return t("clock.link.example_label");
  return EXAMPLES[name] || "";
}

function optionText(name, value) {
  if (name === "design") return t(`clock.design.${value}`);
  if (name === "layout") return t(`clock.layout_name.${value}`);
  return value;
}

/**
 * Formular aus dem Schema. values: Rohwerte (werden beim Bearbeiten geändert), onChange(name, raw) nach jeder Eingabe.
 * prefix: Präfix der ids (Dashboard und Panel getrennt), disabled: nur lesen, exclude: Namen, die das Formular nicht
 * anbietet (Panel auf /clock: STORE_SKIP), excludeValues: { name: [Werte] }, die eine Auswahl nicht anbietet (Panel:
 * STORE_SKIP_VALUES). Liefert das Wurzelelement.
 */
export function buildForm({ values = {}, onChange = () => {}, prefix = "cl", disabled = false, zones = [],
  exclude = [], excludeValues = {} } = {}) {
  const root = node("div", { class: "link-form" });
  const set = (name, raw, control) => {
    if (raw === "") delete values[name];
    else values[name] = raw;
    if (control) control.setAttribute("aria-invalid", rawValid(name, raw, zones) ? "false" : "true");
    onChange(name, raw);
  };
  for (const group of FORM_GROUPS) {
    const box = node("fieldset", { class: "link-group" }, node("legend", { text: t(`clock.link.group.${group.key}`) }));
    const names = group.names.filter((name) => !exclude.includes(name));
    if (!names.length) continue;
    for (const name of names) {
      const entry = entryOf(name);
      if (!entry) continue;
      const id = `${prefix}-${name}`;
      const label = node("label", { for: id, class: "link-label" }, node("span", { text: t(`clock.link.f.${name}`) }),
        node("code", { class: "link-param", text: name }));
      const current = values[name] ?? "";
      let control;
      if (entry.type === "enum" || entry.type === "flag") {
        const options = entry.type === "flag" ? [["1", t("clock.link.on")], ["0", t("clock.link.off")]]
          : entry.values.filter((v) => !(excludeValues[name] || []).includes(v)).map((v) => [v, optionText(name, v)]);
        control = node("select", { id, disabled }, node("option", { value: "", text: t("clock.link.default") }),
          ...options.map(([v, text]) => node("option", { value: v, text })));
        control.value = current;
        control.addEventListener("change", () => set(name, control.value, control));
      } else if (entry.type === "list") {
        control = node("div", { id, class: "link-checks", role: "group", "aria-label": t(`clock.link.f.${name}`) });
        const chosen = new Set(String(current).split(",").filter(Boolean));
        for (const value of entry.values) {
          const box2 = node("input", { type: "checkbox", value, disabled, id: `${id}-${value}` });
          box2.checked = chosen.has(value);
          box2.addEventListener("change", () => {
            const picked = [...control.querySelectorAll("input:checked")].map((input) => input.value);
            set(name, picked.join(","), null);
          });
          control.append(node("label", { class: "link-check", for: `${id}-${value}` }, box2,
            node("span", { text: t(`clock.link.show_item.${value}`) }), node("code", { class: "link-param", text: value })));
        }
        label.removeAttribute("for");
      } else {
        const number = entry.type === "int";
        control = node("input", {
          id, type: number ? "number" : "text", disabled, autocomplete: "off", spellcheck: "false",
          min: number ? entry.min : null, max: number ? entry.max : null, step: number ? 1 : null,
          inputmode: number ? "numeric" : null, maxlength: number ? null : (entry.type === "label" ? entry.len : kit.MAX_LEN),
          placeholder: number ? (entry.default ?? "") : example(name),
          list: name === "accent" ? `${prefix}-palette` : (name === "tz" && zones.length ? `${prefix}-zones` : null),
        });
        control.value = current;
        control.setAttribute("aria-invalid", rawValid(name, current, zones) ? "false" : "true");
        control.addEventListener("input", () => set(name, control.value.trim(), control));
      }
      box.append(node("div", { class: "link-field" }, label, control));
    }
    root.append(box);
  }
  const palette = node("datalist", { id: `${prefix}-palette` });
  for (const name of Object.keys(kit.PALETTE)) palette.append(node("option", { value: name }));
  root.append(palette);
  if (zones.length) {
    const list = node("datalist", { id: `${prefix}-zones` });
    for (const zone of zones) list.append(node("option", { value: zone }));
    root.append(list);
  }
  return root;
}
