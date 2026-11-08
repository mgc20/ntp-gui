// Tastenkürzel (1.6, T2): g o / g s / g g / g c / g u / g y springen zu den Bereichen, „/“ setzt den Fokus
// in die Suche der Seite (falls es eine gibt), „?“ zeigt die Übersicht der Kürzel.
//
// Nie aktiv in Eingabefeldern (input, textarea, select, contenteditable) und nie mit Strg/Alt/Meta –
// sonst schnappte das Dashboard Browser- und Systemkürzel weg. Ohne DOM-Zugriff geschrieben, damit
// tests/test_navigation.py die Logik in Node prüfen kann; app.js hängt den Handler an document.
import { NAV } from "./routes.js";

/** Zweite Taste nach „g“ → Navigationseintrag. */
export const GO_KEYS = Object.fromEntries(NAV.filter((n) => n.key).map((n) => [n.key, n.id]));

/** Wie lange nach „g“ die zweite Taste zählt (ms). */
export const SEQUENCE_MS = 1500;

/** Tippt der Nutzer gerade in ein Feld? Dann gehört jede Taste dem Feld. */
export function isTypingTarget(target) {
  if (!target || typeof target !== "object") return false;
  if (target.isContentEditable) return true;
  const tag = String(target.tagName || "").toUpperCase();
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    // Knöpfe, Kästchen und Regler nehmen keine Buchstaben auf; jeder andere (auch unbekannte) Typ
    // gilt vorsichtshalber als Textfeld.
    const type = String(target.type || target.getAttribute?.("type") || "text").toLowerCase();
    return !["button", "submit", "reset", "checkbox", "radio", "range", "color", "file", "image"].includes(type);
  }
  return false;
}

/**
 * Handler bauen. actions: { go(navId), search() → true wenn eine Suche fokussiert wurde, help() }.
 * now: Zeitquelle (Tests). Gibt eine Funktion (event) → Name der ausgelösten Aktion oder null zurück.
 */
export function createShortcuts(actions, now = () => Date.now()) {
  let pendingG = 0;
  return function onKey(event) {
    if (!event || event.defaultPrevented || event.isComposing) return null;
    if (event.ctrlKey || event.altKey || event.metaKey) { pendingG = 0; return null; }
    if (isTypingTarget(event.target)) { pendingG = 0; return null; }
    const key = String(event.key || "");
    if (pendingG && now() - pendingG <= SEQUENCE_MS) {
      pendingG = 0;
      const target = GO_KEYS[key.toLowerCase()];
      if (target) {
        event.preventDefault?.();
        actions.go?.(target);
        return `go:${target}`;
      }
      // Unbekannte zweite Taste: Folge verwerfen, die Taste selbst normal weiter auswerten.
    }
    pendingG = 0;
    if (key === "g" || key === "G") {
      pendingG = now();
      return "pending";
    }
    if (key === "/") {
      if (actions.search?.()) {
        event.preventDefault?.();
        return "search";
      }
      return null;
    }
    if (key === "?") {
      event.preventDefault?.();
      actions.help?.();
      return "help";
    }
    return null;
  };
}

/** Liste für die Übersicht („?“): [Tasten, Katalogschlüssel der Beschreibung]. */
export function shortcutList() {
  return [
    ...NAV.filter((n) => n.key).map((n) => [["g", n.key], n.titleKey]),
    [["/"], "app.shortcuts.search"],
    [["?"], "app.shortcuts.help"],
  ];
}
