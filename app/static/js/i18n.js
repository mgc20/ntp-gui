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
  { code: "en", label: "English (Beta)" },  // nur Navigation, Kopfzeile, Teile der Übersicht übersetzt
];
export const REFERENCE = "de";
const STORAGE_KEY = "ntp-gui-lang";

// Notfallkatalog: Lädt de.json nicht (Netzfehler, Proxy sperrt .json, 401 beim Anmelden), stehen
// wenigstens Navigation, Kopfzeile und Übersicht auf Deutsch da statt roher Schlüssel.
// Muss mit de.json übereinstimmen (tests/test_i18n.py prüft das).
export const CORE_DE = {
  "app": {
    "skip_link": "Zum Inhalt springen",
    "connecting": "verbinde …",
    "connecting_server": "Verbinde mit dem Server …",
    "no_connection": "keine Verbindung",
    "render_error": "Darstellungsfehler: {message}",
    "footer": "ntp-gui {version} · aktualisiert {time} · alle {seconds} s",
    "clock_link_title": "Vollbild-Uhr (Wandmonitor, Tablet)",
    "clock_link_label": "Vollbild-Uhr öffnen",
    "theme_title": "Hell / Dunkel",
    "theme_label": "Hell oder dunkel umschalten",
    "language_title": "Sprache: Deutsch / English (Beta)",
    "language_label": "Sprache wechseln (Language)",
    "title_short": "NTP-GUI",
    "bottom_label": "Hauptbereiche",
    "more": "Mehr",
    "more_label": "Weitere Bereiche",
    "ptp_off": "Nicht genutzt – in {link} einschalten.",
    "ptp_off_link": "System → Einstellungen → PTP",
    "shortcuts": {
      "hint": "Tastenkürzel (?)",
      "title": "Tastenkürzel",
      "search": "Suche der Seite (falls vorhanden)",
      "help": "Diese Übersicht",
      "then": "dann",
      "close": "Schließen",
      "note": "Die Kürzel wirken nicht, solange du in einem Eingabefeld tippst."
    }
  },
  "nav": {
    "label": "Bereiche",
    "overview": "Übersicht",
    "sources": "Zeitquellen",
    "gps": "GPS",
    "ptp": "PTP",
    "clockquality": "Uhrqualität",
    "hardware": "Hardware",
    "clients": "Clients",
    "diagnose": "Diagnose",
    "notify": "Benachrichtigungen",
    "settings": "Einstellungen",
    "setup": "Einrichtung",
    "help": "Hilfe",
    "uhr": "Uhr & Hardware",
    "system": "System",
    "short": {
      "overview": "Übersicht",
      "sources": "Quellen"
    }
  },
  "overview": {
    "band_label": "Gesamtzustand",
    "verdict": {
      "check_count_one": "{count} Punkt unten prüfen",
      "check_count_other": "{count} Punkte unten prüfen",
      "no_issues": "keine offenen Hinweise",
      "stratum": "Stratum {n}",
      "warn_count_one": "{count} Hinweis",
      "warn_count_other": "{count} Hinweise",
      "down_title": "Zeitdienst antwortet nicht",
      "down_text": "chronyd läuft nicht – Geräte im LAN bekommen gerade keine Zeit.",
      "down_pill": "chronyd offline",
      "down_pill_short": "offline",
      "crit_title_one": "{count} Störung",
      "crit_title_other": "{count} Störungen",
      "crit_pill": "Störung",
      "island_title": "Inselbetrieb",
      "island_text": "Keine Zeitquelle erreichbar – die Uhr läuft frei weiter",
      "island_pill_short": "Insel",
      "syncing_title": "Synchronisiert …",
      "syncing_text": "chrony sucht noch eine verlässliche Quelle",
      "syncing_pill_short": "sync …",
      "warn_title": "Synchron – mit Hinweisen",
      "synced": "Synchron",
      "good_title": "Alles in Ordnung",
      "good_text": "Die Uhr ist synchron, alle Teile laufen."
    },
    "facts": {
      "via": "über {source}",
      "local_clock": "lokale Uhr",
      "sources_used": "{used} von {total} Quellen genutzt",
      "clients_one": "{n} Client",
      "clients_other": "{n} Clients"
    },
    "kpi": {
      "offset": "Abweichung",
      "max_error": "Max. Fehler",
      "max_error_note": "Fehlerschranke zu UTC",
      "frequency": "Frequenz",
      "requests": "Anfragen",
      "requests_note_one": "{n} Client im LAN",
      "requests_note_other": "{n} Clients im LAN",
      "tone_warn": "erhöht",
      "tone_crit": "kritisch"
    },
    "area": {
      "clock": "Systemuhr",
      "sources": "Zeitquellen",
      "gps": "GPS",
      "ptp": "PTP",
      "clients": "Clients",
      "services": "Dienste"
    },
    "hints": {
      "serious_label": "Warnungen und Störungen",
      "rest_label": "Informationen und Erfolgsmeldungen",
      "info_count_one": "{count} Information",
      "info_count_other": "{count} Informationen",
      "ok_count_one": "{count} in Ordnung",
      "ok_count_other": "{count} in Ordnung",
      "show": "anzeigen",
      "hide": "ausblenden",
      "details": "Details",
      "less": "weniger",
      "details_show": "Details anzeigen: {title}",
      "details_hide": "Details ausblenden: {title}",
      "label": "Hinweise"
    }
  },
  // Seiten (T2 „Seiten entschlacken“): kurze Texte, die auch ohne Katalog lesbar sein müssen.
  "pages": {
    "clients": {
      "name_add": "Namen geben",
      "name_change": "Namen ändern",
      "name_input": "Eigener Name für {address} (Enter speichert, Esc bricht ab)",
      "name_placeholder": "z. B. NAS im Keller",
      "name_saved": "Name gespeichert",
      "name_removed": "Name entfernt",
      "name_failed": "Nicht gespeichert: {message}",
      "cards_label": "Geräte",
      "ignore_42": "Geräte, die Option 42 ignorieren (Windows, Linux, macOS)",
      "notes": "Hinweise zu {system} ({count})",
      "check_line": "„Prüfen“ testet die Umleitung von hier aus."
    },
    "sources": {
      "steps": "Die vier Schritte im Einzelnen",
      "steps_line": "Messen → Mehrheit finden → beste wählen → kombinieren."
    },
    "diagnose": {
      "intro": "Log, Ereignisse und Diagnosepaket für die Fehlersuche – nichts davon wird automatisch hochgeladen.",
      "privacy": "Mit Datenschutzfilter."
    },
    "more": "Mehr dazu"
  },
  "clock": {
    "back": "← Dashboard",
    "tools_label": "Darstellung",
    "design_label": "Design",
    "design_title": "Design der Uhr",
    "design": {
      "digital": "Digital",
      "bahnhof": "Bahnhofsuhr",
      "nixie": "Nixie",
      "flip": "Klappzahlen",
      "wort": "Wortuhr"
    },
    "theme_title": "Hell oder dunkel",
    "theme_light": "Hell",
    "theme_dark": "Dunkel",
    "red": "Rotlicht",
    "red_title": "Rotlicht: schont die Dunkeladaption der Augen (Sternwarte, Schlafzimmer, Serverraum bei Nacht)",
    "tone": "Ton",
    "device": "Mein Gerät",
    "full": "Vollbild",
    "full_title": "Vollbild ein oder aus (Taste F)",
    "local": "Ortszeit",
    "week": "KW {week}",
    "face_label": "{time} Uhr",
    "tone_title": "Ton auf der Sekunde",
    "tone_line": "Zum Stellen von Uhren ohne Funk oder Netz: Piep auf jeder vollen Sekunde, langer Ton zur Minute.",
    "tone_seconds": "Sekundenpiep",
    "tone_countdown": "Uhr stellen",
    "tone_off": "Aus",
    "tone_running": "Läuft · erwartete Genauigkeit {acc} (Ziel ± 5 ms), ohne Laufzeit im Lautsprecher.",
    "tone_unsynced": "Läuft · noch kein Abgleich mit dem Server – die Töne folgen vorerst der Uhr dieses Geräts.",
    "tone_blocked": "Der Browser hält den Ton noch an – tippe noch einmal auf „Sekundenpiep“ oder „Uhr stellen“.",
    "tone_unsupported": "Dein Browser kann hier keinen Ton erzeugen.",
    "tone_stopped": "Ton aus.",
    "countdown_wait": "Drücke bei 0 · Countdown in {seconds} s",
    "countdown_now": "0",
    "tone_info_title": "Ton auf der Sekunde",
    "tone_info": "Der Ton startet erst nach deinem Klick (Browser spielen sonst nichts ab). „Sekundenpiep“: kurzer Piep auf jeder vollen Sekunde der Serverzeit, ein langer Ton zur vollen Minute. „Uhr stellen“: Countdown der letzten 10 Sekunden vor der vollen Minute, der lange Ton ist die 0 – dann drückst du am Backofen, im Auto oder an der Armbanduhr. Geplant wird mit der Audiouhr des Browsers und dem gemessenen Versatz zum Server; die erwartete Genauigkeit ist der Abgleich (± halbe Laufzeit) plus das Raster der Audiouhr, Ziel ± 5 ms. Nicht enthalten ist die Laufzeit im Lautsprecher: Bluetooth-Kopfhörer und -Boxen hängen 100 bis 300 ms hinterher, eingebaute Lautsprecher kaum.",
    "device_title": "Wie falsch geht dein Gerät?",
    "device_measuring": "misst …",
    "device_behind": "Dein Gerät geht {value} nach",
    "device_ahead": "Dein Gerät geht {value} vor",
    "device_exact": "Dein Gerät geht richtig",
    "device_line_unknown": "Gleich fertig: Die Seite vergleicht die Uhr dieses Geräts mit dem Zeitserver.",
    "device_line_good": "Passt – weniger als 0,1 s daneben, gemessen auf {acc} genau.",
    "device_line_warn": "Merkbar daneben, im Alltag egal: Handys holen die Zeit meist vom Mobilfunknetz, PCs aus dem Internet.",
    "device_line_crit": "Deutlich daneben: Schalte in den Einstellungen deines Geräts „Uhrzeit automatisch einstellen“ ein.",
    "device_uncertain": "Messung zu ungenau",
    "device_line_uncertain": "Gemessen auf nur {acc} genau – das reicht nicht, um sicher zu sagen, ob dein Gerät weniger als 0,1 s daneben liegt. Probier es in einem schnelleren Netz.",
    "device_info_title": "Wie falsch geht dein Gerät?",
    "device_info": "Die Seite misst wie NTP mit vier Zeitstempeln, wie weit die Uhr dieses Geräts von der Serveruhr abweicht (± halbe Laufzeit). Das Ergebnis bleibt in diesem Browser: Es wird weder gespeichert noch an den Server oder sonst wohin gesendet. Ampel: grün unter 0,1 s (samt Messgenauigkeit), gelb unter 1 s, rot ab 1 s; grau, wenn die Messung zu ungenau für ein Urteil ist. Handys stellen ihre Uhr meist über das Mobilfunknetz oder NTP, Computer über einen Zeitserver im Internet – je nach Gerät und letztem Abgleich liegen sie Millisekunden bis Sekunden daneben. Manche Browser runden ihre Uhr absichtlich (Schutz vor Fingerprinting, z. B. auf 1 ms oder 100 ms); kleine Werte sind dann ungenauer.",
    "info_label": "Erklärung: {title}",
    "egg_possible": "23:59:60 wäre heute möglich: Am 30. Juni und 31. Dezember darf die letzte Minute (UTC) eine Schaltsekunde bekommen – diesmal ist keine angekündigt.",
    "egg_insert": "Heute Nacht gibt es eine Schaltsekunde: Auf 23:59:59 UTC folgt 23:59:60.",
    "egg_delete": "Heute fällt eine Sekunde aus: Auf 23:59:58 UTC folgt gleich der neue Tag (negative Schaltsekunde).",
    "state": {
      "good": "synchron",
      "warn": "eingeschränkt",
      "crit": "nicht synchron"
    },
    "connecting": "verbinde …",
    "no_connection": "keine Verbindung ({error})",
    "no_connection_since": "keine Verbindung seit {seconds} s",
    "stale_detail": "die Uhr läuft mit dem letzten Abgleich weiter",
    "chrony_down": "chronyd antwortet nicht",
    "unsynced": "nicht synchron",
    "unsynced_kind": "nicht synchron · {kind}",
    "synced": "{state} · {source}",
    "source_unknown": "Quelle",
    "server_acc": "Server {acc}",
    "leap_announced": "Schaltsekunde angekündigt ({leap})",
    "display_acc": "Anzeige {acc} (RTT {rtt})",
    "band_title": "Server: Genauigkeit der Serveruhr laut chrony. Anzeige: Abgleich dieser Seite mit dem Server (± halbe Laufzeit der besten von fünf Messungen).",
    "wake_on": "Bildschirm bleibt an",
    "wake_https": "Bildschirm-Sperre: nur über HTTPS abschaltbar",
    "err_login": "Anmeldung nötig",
    "err_timeout": "Zeitüberschreitung"
  }
};

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

function findCore(key, params) {
  if (params && typeof params.count === "number") {
    const form = lookup(CORE_DE, `${key}_${pluralForm(REFERENCE, params.count)}`) ?? lookup(CORE_DE, `${key}_other`);
    if (form !== undefined) return form;
  }
  return lookup(CORE_DE, key);
}

function resolveText(key, params) {
  let text = find(current, key, params);
  if (text === undefined && current !== REFERENCE) text = find(REFERENCE, key, params);
  if (text === undefined) text = findCore(key, params);
  return text;
}

/** Übersetzung mit {platzhalter}; Rückfall: Deutsch, Notfallkatalog, dann der Schlüssel selbst. */
export function t(key, params) {
  const text = resolveText(key, params);
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

/**
 * Beim Start: gespeicherte Wahl, sonst Deutsch; Deutsch wird immer mitgeladen (Rückfall).
 * Bewusst KEINE automatische Wahl nach Browsersprache: Englisch ist noch Beta (große Teile der Seiten
 * sind fest deutsch) und gilt nur, wenn es jemand ausdrücklich gewählt hat. browserLanguage() bleibt
 * für später exportiert.
 */
export async function initI18n() {
  const stored = readStored();
  const wanted = supported(stored) ? stored : REFERENCE;
  // Deutsch ist der Rückfall für alles – bei einem kurzen Netzfehler lieber nochmal versuchen.
  for (let attempt = 0; attempt < 3 && !await load(REFERENCE); attempt += 1) {
    await new Promise((done) => setTimeout(done, 300 * (attempt + 1)));
  }
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
  // Unbekannter Schlüssel: den deutschen Text aus index.html stehen lassen, nie den Schlüssel zeigen.
  for (const node of root.querySelectorAll("[data-i18n]")) {
    const text = resolveText(node.dataset.i18n);
    if (text !== undefined) node.textContent = text;
  }
  for (const node of root.querySelectorAll("[data-i18n-title]")) {
    const text = resolveText(node.dataset.i18nTitle);
    if (text !== undefined) node.setAttribute("title", text);
  }
  for (const node of root.querySelectorAll("[data-i18n-aria-label]")) {
    const text = resolveText(node.dataset.i18nAriaLabel);
    if (text !== undefined) node.setAttribute("aria-label", text);
  }
}

/** Für Tests: Kataloge direkt setzen. */
export function _setCatalogs(map, lang = REFERENCE) {
  catalogs.clear();
  for (const [code, data] of Object.entries(map)) catalogs.set(code, data);
  current = lang;
}
