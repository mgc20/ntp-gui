// Unterseiten der Hilfe (1.11) – ohne DOM, damit Tests sie in Node prüfen können.
//
// Jede Gruppe aus HELP_GROUPS ist ein Thema mit eigener Adresse: #/hilfe/<thema> (z. B. #/hilfe/gps),
// ein einzelner Eintrag darin #/hilfe/<thema>/<schlüssel> (z. B. #/hilfe/gps/pps). #/hilfe allein ist das
// Inhaltsverzeichnis. Alte Links #/hilfe?t=<schlüssel> (bis 1.10, aus den ⓘ-Erklärungen) zeigen weiter den
// Eintrag – auf der Unterseite seines Themas.
import { HELP, HELP_GROUPS } from "./help.js";

/** Abschnitte des Inhaltsverzeichnisses: Titel und Themen (ids aus HELP_GROUPS) in dieser Reihenfolge. */
export const HELP_SECTIONS = [
  { title: "Erste Schritte", topics: ["grundlagen", "uebersicht", "einstellungen"] },
  { title: "Zeit und Quellen", topics: ["systemuhr", "zeitquellen", "quellenauswahl", "ntp-details", "nts"] },
  { title: "GPS und PTP", topics: ["gps", "gps-empfang", "gps-kalibrierung", "ptp"] },
  { title: "Geräte im Netz", topics: ["clients", "client-uhren", "dns"] },
  { title: "Uhr und Hardware", topics: ["uhrqualitaet", "hardware"] },
  { title: "Betrieb und Wartung", topics: ["betrieb", "benachrichtigungen", "diagnose", "api", "sicherung", "update", "web"] },
];

const BY_ID = new Map(HELP_GROUPS.map((group) => [group.id, group]));

/** Themen in der Reihenfolge des Inhaltsverzeichnisses (für „vorheriges/nächstes Thema“). */
export const TOPICS = HELP_SECTIONS.flatMap((section) => section.topics).map((id) => BY_ID.get(id)).filter(Boolean);

/** Thema zu einer id oder null. */
export function topic(id) {
  return BY_ID.get(String(id || "").toLowerCase()) || null;
}

/** Thema, unter dem ein Hilfe-Schlüssel steht (das erste in der Reihenfolge des Inhaltsverzeichnisses). */
export function topicOfKey(key) {
  if (!Object.prototype.hasOwnProperty.call(HELP, key)) return null;
  return TOPICS.find((group) => group.keys.includes(key)) || null;
}

/** Adresse eines Themas (#/hilfe/gps) bzw. des Inhaltsverzeichnisses. */
export function topicHref(id) {
  return topic(id) ? `#/hilfe/${topic(id).id}` : "#/hilfe";
}

/** Tiefer Link auf einen Eintrag (#/hilfe/gps/pps); unbekannte Schlüssel → Inhaltsverzeichnis. */
export function helpHref(key) {
  const group = topicOfKey(key);
  return group ? `#/hilfe/${group.id}/${key}` : "#/hilfe";
}

/** Vorheriges und nächstes Thema (Reihenfolge des Inhaltsverzeichnisses), am Rand null. */
export function neighbours(id) {
  const at = TOPICS.findIndex((group) => group.id === id);
  if (at < 0) return { prev: null, next: null };
  return { prev: TOPICS[at - 1] || null, next: TOPICS[at + 1] || null };
}

/**
 * Was die Hilfe zeigt. sub: Unterpfad nach #/hilfe (ctx.subpath), query: Abfrageteil ohne „?“.
 * Ergebnis { view: "index" } (Inhaltsverzeichnis, notFound bei unbekanntem Thema) oder
 * { view: "topic", topic, focus } (focus: Schlüssel des hervorgehobenen Eintrags oder null).
 */
export function resolveHelp(sub, query = "") {
  const parts = String(sub || "").split("/").filter(Boolean);
  let legacy = null;
  try { legacy = new URLSearchParams(String(query || "")).get("t"); } catch (error) { legacy = null; }
  const known = (key) => (key && Object.prototype.hasOwnProperty.call(HELP, key) ? key : null);
  if (!parts.length) {
    // Alter Link #/hilfe?t=pps: Eintrag auf der Unterseite seines Themas.
    const key = known(legacy);
    const group = key ? topicOfKey(key) : null;
    return group ? { view: "topic", topic: group, focus: key } : { view: "index", notFound: Boolean(legacy) };
  }
  const group = topic(parts[0]);
  if (group) {
    const key = known(parts[1]) || known(legacy);
    return { view: "topic", topic: group, focus: key && group.keys.includes(key) ? key : null };
  }
  // #/hilfe/pps: ein Schlüssel statt eines Themas – der Eintrag auf seiner Unterseite.
  const key = known(parts[0]);
  const owner = key ? topicOfKey(key) : null;
  if (owner) return { view: "topic", topic: owner, focus: key };
  return { view: "index", notFound: true };
}

/**
 * Hilfe-Thema zu einer Seite des Dashboards (Verweis „Mehr in der Hilfe“ unter jeder Seite).
 * Schlüssel: Seiten-ids aus routes.js. Einstellungen, Hilfe, Einrichtung und Musterseite haben keinen Verweis.
 */
export const PAGE_TOPICS = {
  overview: "uebersicht", sources: "zeitquellen", gps: "gps", clients: "client-uhren",
  clockquality: "uhrqualitaet", hardware: "hardware", ptp: "ptp", displays: "uhrqualitaet",
  diagnose: "diagnose", notify: "benachrichtigungen",
  // settings: keiner – dort steht die Speicherleiste am Seitenende, ein Link dahinter läge unter ihr. Jedes Feld
  // der Einstellungen hat sein ⓘ mit „Mehr in der Hilfe“.
};

/** Thema zu einer Seite oder null. */
export function pageTopic(pageId) {
  return Object.prototype.hasOwnProperty.call(PAGE_TOPICS, pageId) ? topic(PAGE_TOPICS[pageId]) : null;
}

/** Suche: je Thema (Reihenfolge des Inhaltsverzeichnisses) die passenden Schlüssel, jeder nur einmal. */
export function searchHelp(needle) {
  const text = String(needle || "").trim().toLowerCase();
  if (!text) return [];
  const seen = new Set();
  const out = [];
  for (const group of TOPICS) {
    const keys = group.keys.filter((key) => HELP[key] && !seen.has(key)
      && `${HELP[key].title} ${HELP[key].text}`.toLowerCase().includes(text));
    keys.forEach((key) => seen.add(key));
    if (keys.length || group.title.toLowerCase().includes(text)) out.push({ topic: group, keys });
  }
  return out;
}
