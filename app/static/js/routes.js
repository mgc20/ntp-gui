// Routentabelle des Dashboards (1.6, T2 „Navigation“) – ohne DOM, damit Tests sie in Node prüfen können.
//
// Sieben Einträge in der Navigation: Übersicht · Zeitquellen · GPS · Clients · Uhr & Hardware · System · Hilfe.
// „Uhr & Hardware“ und „System“ sind Gruppen mit Reitern (erster Reiter = Standard). Die Hash-Routen
// sind deutsch und kurz (#/uhr/ptp, #/system/einstellungen). Alte Routen (#/ptp, #/einstellungen?s=gps,
// #/hardware/…) leiten per location.replace auf die neuen weiter – ohne Verlaufseintrag; die Tabelle
// LEGACY ist die einzige Stelle, an der die alten Namen noch stehen dürfen (tests/test_navigation.py).

/** Navigation: id, Hash-Pfad des Ziels, Katalogschlüssel, Tastenkürzel (g + Taste), untere Leiste. */
export const NAV = [
  { id: "overview", href: "#/", titleKey: "nav.overview", shortKey: "nav.short.overview", key: "o", bottom: true },
  { id: "sources", href: "#/quellen", titleKey: "nav.sources", shortKey: "nav.short.sources", key: "s", bottom: true },
  { id: "gps", href: "#/gps", titleKey: "nav.gps", shortKey: "nav.gps", key: "g", bottom: true },
  { id: "clients", href: "#/clients", titleKey: "nav.clients", shortKey: "nav.clients", key: "c", bottom: true },
  { id: "uhr", href: "#/uhr/qualitaet", titleKey: "nav.uhr", key: "u", group: true },
  { id: "system", href: "#/system/diagnose", titleKey: "nav.system", key: "y", group: true },
  { id: "help", href: "#/hilfe", titleKey: "nav.help", key: null },
];

/**
 * Seiten: id (= Modulname in app.js), Pfad ohne „#/“, Navigationseintrag, Titel, history (Verlauf mitladen).
 * Seiten mit gleichem nav-Eintrag und tab: true bilden die Reiterleiste dieser Gruppe – in dieser Reihenfolge.
 */
export const PAGES = [
  { id: "overview", path: "", nav: "overview", titleKey: "nav.overview", history: true },
  { id: "sources", path: "quellen", nav: "sources", titleKey: "nav.sources", history: true },
  { id: "gps", path: "gps", nav: "gps", titleKey: "nav.gps", history: true },
  { id: "clients", path: "clients", nav: "clients", titleKey: "nav.clients", history: true },
  { id: "clockquality", path: "uhr/qualitaet", nav: "uhr", tab: true, titleKey: "nav.clockquality", history: false },
  { id: "hardware", path: "uhr/hardware", nav: "uhr", tab: true, titleKey: "nav.hardware", history: false },
  { id: "ptp", path: "uhr/ptp", nav: "uhr", tab: true, titleKey: "nav.ptp", history: true },
  { id: "diagnose", path: "system/diagnose", nav: "system", tab: true, titleKey: "nav.diagnose", history: false },
  { id: "notify", path: "system/benachrichtigungen", nav: "system", tab: true, titleKey: "nav.notify", history: false },
  { id: "settings", path: "system/einstellungen", nav: "system", tab: true, titleKey: "nav.settings" },
  // 1.6 (T3): Willkommens-Assistent – Reiter „Einrichtung“ unter System, kein eigener Navigationseintrag.
  // Die Schritte sind Unterpfade (#/system/einrichtung/quellen), damit „Zurück“ im Browser einen Schritt zurückgeht.
  { id: "setup", path: "system/einrichtung", nav: "system", tab: true, titleKey: "nav.setup", history: false },
  { id: "help", path: "hilfe", nav: "help", titleKey: "nav.help" },
  // Nur für Entwicklung: Musterseite mit allen Bausteinen, erreichbar mit ?dev=1 (nicht in der Navigation).
  { id: "muster", path: "muster", nav: null, title: "Musterseite", dev: true, history: false },
];

/**
 * Schritte des Willkommens-Assistenten (pages/setup.js) als Unterpfade von #/system/einrichtung; key = Kennung
 * des Punkts in der Checkliste (GET /api/setup), die auf der Übersicht auf den Schritt verlinkt.
 */
export const SETUP_STEPS = [
  { id: "pruefen", key: "check" },
  { id: "quellen", key: "sources" },
  { id: "gps", key: "gps" },
  { id: "clients", key: "clients" },
  { id: "benachrichtigung", key: "notify" },
];

/** Link auf einen Schritt des Assistenten (Index oder Kennung der Checkliste). */
export function setupHref(step) {
  const index = typeof step === "number" ? step : SETUP_STEPS.findIndex((s) => s.key === step);
  const at = Math.max(0, Math.min(SETUP_STEPS.length - 1, index));
  return route("setup", at > 0 ? SETUP_STEPS[at].id : "");
}

/** Gruppenpfade ohne Reiter → erster Reiter. */
export const GROUPS = { uhr: "uhr/qualitaet", system: "system/diagnose" };

/**
 * Alte Routen (bis 1.5) → neue. Unterpfade und Abfrageteil bleiben erhalten:
 * #/einstellungen?s=gps → #/system/einstellungen?s=gps. gnss/gpsquality waren nie eigene Seiten,
 * gehören aber zur GPS-Seite – falls jemand sie von Hand aufruft.
 */
export const LEGACY = {
  ptp: "uhr/ptp",
  uhrqualitaet: "uhr/qualitaet",
  hardware: "uhr/hardware",
  diagnose: "system/diagnose",
  benachrichtigungen: "system/benachrichtigungen",
  einstellungen: "system/einstellungen",
  gnss: "gps",
  gpsquality: "gps",
};

/** Kanonischer Hash einer Seite (mit optionalem Unterpfad/Abfrage), z. B. route("settings", "", "s=gps"). */
export function route(id, sub = "", query = "") {
  const page = PAGES.find((p) => p.id === id);
  if (!page) throw new Error(`unbekannte Seite ${id}`);
  const path = [page.path, sub].filter(Boolean).join("/");
  return `#/${path}${query ? `?${query}` : ""}`;
}

function splitHash(hash) {
  const raw = String(hash || "").replace(/^#\/?/, "");
  const q = raw.indexOf("?");
  const path = (q < 0 ? raw : raw.slice(0, q)).replace(/\/+$/, "");
  const query = q < 0 ? "" : raw.slice(q + 1);
  return { path, query };
}

/**
 * Hash auflösen. Ergebnis entweder { redirect: "#/neu…" } (alte Route oder Gruppe ohne Reiter) oder
 * { page, sub, query }. Unbekannte Pfade landen auf der Übersicht (nie eine leere Seite).
 * dev: Entwicklerseiten freigeschaltet (?dev=1).
 */
export function resolve(hash, dev = false) {
  const text = String(hash || "");
  // Sprungmarken ohne „#/“ (z. B. #main vom „Zum Inhalt springen“-Link) sind keine Routen.
  if (text && !text.startsWith("#/") && text !== "#") return { page: PAGES[0], sub: "", query: "", anchor: true };
  const { path, query } = splitHash(text);
  const parts = path.split("/");
  const head = (parts[0] || "").toLowerCase();
  const suffix = (q) => (q ? `?${q}` : "");
  if (Object.prototype.hasOwnProperty.call(LEGACY, head)) {
    const target = [LEGACY[head], ...parts.slice(1)].filter(Boolean).join("/");
    return { redirect: `#/${target}${suffix(query)}` };
  }
  if (Object.prototype.hasOwnProperty.call(GROUPS, head)) {
    const second = (parts[1] || "").toLowerCase();
    const page = PAGES.find((p) => p.path === `${head}/${second}`);
    if (!page) return { redirect: `#/${GROUPS[head]}${suffix(query)}` };
    return { page, sub: decode(parts.slice(2).join("/")), query };
  }
  const page = PAGES.find((p) => p.path === head && p.path !== "" && (!p.dev || dev));
  if (!page) return { page: PAGES[0], sub: "", query };
  return { page, sub: decode(parts.slice(1).join("/")), query };
}

function decode(sub) {
  try { return decodeURIComponent(sub); } catch (error) { return ""; }
}

/** Reiter einer Gruppe (Seiten in Tabellenreihenfolge). */
export function tabsOf(navId) {
  return PAGES.filter((p) => p.nav === navId && p.tab);
}

/** Navigationseintrag einer Seite. */
export function navOf(page) {
  return NAV.find((n) => n.id === page?.nav) || null;
}

/**
 * Ziel eines Hinweises (insight.action vom Server) → Seite. Die Schlüssel sind Kennungen, keine Routen;
 * Der Server schickt für die Uhrqualität „uhrqualitaet“ (Feld action der API, bleibt stabil);
 * „clockquality“ ist die Kennung der Seite und wird ebenfalls angenommen.
 */
export const ACTION_PAGES = {
  gps: "gps", sources: "sources", clients: "clients", settings: "settings", ptp: "ptp", hardware: "hardware",
  clockquality: "clockquality", diagnose: "diagnose", notify: "notify", uhrqualitaet: "clockquality",
  setup: "setup",
};

/** Link eines Hinweises oder null, wenn die Aktion unbekannt ist. */
export function actionHref(action) {
  const id = Object.prototype.hasOwnProperty.call(ACTION_PAGES, action) ? ACTION_PAGES[action] : null;
  return id ? route(id) : null;
}

// --- Verlauf: „Abbrechen“ beim Verlassen mit ungespeicherten Änderungen -------------------------------------
// Jeder gezeigte Verlaufseintrag trägt eine laufende Nummer (history.state.nav). Bricht der Nutzer einen
// Wechsel ab, springt app.js mit history.go() auf den gezeigten Eintrag zurück, statt einen Eintrag zu
// überschreiben: Nach „Zurück“ fehlte sonst die vorige Seite im Verlauf, nach einem Link stünde die Seite
// doppelt darin.

/** Nummer eines Verlaufseintrags oder null bei einem neuen Eintrag (Link, Kürzel, Adresszeile). */
export function entryIndex(state) {
  return Number.isInteger(state?.nav) ? state.nav : null;
}

/** state für history.replaceState: die Nummer dazu, sonstige Angaben bleiben. */
export function stampState(state, index) {
  return { ...(state && typeof state === "object" ? state : {}), nav: index };
}

/** Schritte für history.go(), um vom aktuellen Eintrag (state) zum gezeigten (Nummer shown) zurückzukehren. */
export function returnStep(shown, state) {
  const entry = entryIndex(state);
  return entry === null ? -1 : shown - entry;
}

/**
 * Gezeigten Eintrag nummerieren: ein neuer Eintrag (Link, Kürzel, Adresszeile, Seitenstart) bekommt per
 * hist.replaceState die Nummer nach shown, ein bekannter (Zurück/Vor) behält seine. Ergebnis: seine Nummer.
 */
export function stampEntry(hist, shown) {
  const index = entryIndex(hist.state);
  if (index !== null) return index;
  hist.replaceState(stampState(hist.state, shown + 1), "");
  return shown + 1;
}

/**
 * Rumpf des hashchange-Handlers aus app.js, ohne DOM: hist ist window.history, shown die Nummer des
 * gezeigten Eintrags, leaveAllowed() fragt bei ungespeicherten Änderungen nach, redirect() stellt alte
 * Routen um (true = umgestellt, der nächste hashchange zeichnet). Ergebnis: { shown, show } – show heißt,
 * die Seite des aktuellen Eintrags ist neu zu zeichnen.
 */
export function hashChange(hist, shown, { leaveAllowed, redirect }) {
  // Zurück auf dem gezeigten Eintrag (nach „Abbrechen“): nichts zu tun.
  if (entryIndex(hist.state) === shown) return { shown, show: false };
  if (!leaveAllowed()) {
    hist.go(returnStep(shown, hist.state));
    return { shown, show: false };
  }
  if (redirect()) return { shown, show: false };
  return { shown: stampEntry(hist, shown), show: true };
}
