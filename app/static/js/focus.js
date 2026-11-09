// Tastaturfokus und Eingaben über das Neuzeichnen retten (ohne DOM-Globals, in Node getestet).
//
// Live-Seiten werden alle paar Sekunden komplett neu gebaut. Vorher merken, welches Element
// (Schlüssel + Position unter gleichartigen) den Fokus hatte und wo Cursor und Markierung standen,
// danach das passende neue Element fokussieren und die Auswahl wieder setzen.
export const FOCUSABLE = "a[href], button, input, select, textarea, summary, [tabindex]";

export function focusKeyOf(root, node) {
  if (!node || node === root || !root.contains(node)) return null;
  if (node.dataset && node.dataset.focusKey) return node.dataset.focusKey;
  const parts = [node.tagName, node.getAttribute("href") || "", node.getAttribute("aria-label") || "", node.id || ""];
  if (!parts[1] && !parts[2] && !parts[3]) parts.push((node.textContent || "").trim().slice(0, 60));
  return parts.join("|");
}

// Cursor/Markierung eines Text- oder Notizfelds; null bei Feldern ohne Auswahl (Zahl, Kontrollkästchen …).
function selectionOf(node) {
  try {
    if (typeof node.selectionStart !== "number") return null;
    return { start: node.selectionStart, end: node.selectionEnd, direction: node.selectionDirection || "none", value: node.value };
  } catch (error) {
    return null;
  }
}

export function captureFocus(root, active) {
  const key = focusKeyOf(root, active);
  if (!key) return null;
  const same = [...root.querySelectorAll(FOCUSABLE)].filter((n) => focusKeyOf(root, n) === key);
  return { key, index: Math.max(0, same.indexOf(active)), selection: selectionOf(active) };
}

// active: das Element, das nach dem Neuzeichnen den Fokus hat (null/body, wenn er verloren ging).
export function restoreFocus(root, saved, active, body = null) {
  if (!saved) return;
  if (active && active !== body && active !== root && active.isConnected) return;
  const same = [...root.querySelectorAll(FOCUSABLE)].filter((n) => focusKeyOf(root, n) === saved.key);
  const target = same[Math.min(saved.index, same.length - 1)];
  if (!target) return;
  target.focus({ preventScroll: true });
  const sel = saved.selection;
  // Nur bei unverändertem Text – sonst gehörte die Auswahl zu einem anderen Inhalt.
  if (sel && target.value === sel.value) {
    try { target.setSelectionRange(sel.start, sel.end, sel.direction); } catch (error) { /* Feldtyp ohne Auswahl */ }
  }
}

// Steht der Cursor in einem Zahlenfeld? Dessen getippten Text („0,“) gibt der Browser nicht heraus –
// value ist dann „0“ oder leer. Ein Neubau im Hintergrund machte daraus „0“, und aus „0,5“ würde 5.
// Ebenso eine Auswahlliste: Neu gebaut schlösse sich ihre geöffnete Liste mitten in der Wahl.
// Solange so ein Feld den Fokus hat, wird nur auf ausdrücklichen Wunsch neu gezeichnet.
export function holdsTyping(root, active) {
  if (!active || active === root || !root.contains(active)) return false;
  return (active.tagName === "INPUT" && active.type === "number") || active.tagName === "SELECT";
}

// Wann darf ein Neuzeichnen im Hintergrund laufen? Nicht, solange in einem Feld getippt wird
// (holdsTyping), und nicht, solange ein Zeiger in der Seite gedrückt ist: Ein Klick besteht aus
// Drücken und Loslassen auf demselben Element – baut ein Neuzeichnen dazwischen die Seite neu, geht
// er verloren. Zurückgehaltenes holt schedule() nach: beim Loslassen des Zeigers oder wenn der Fokus
// das Feld verlässt, aber nie mitten in einer Zeigeraktion (deren Drücken löst das Verlassen ja aus).
export function renderGate(schedule) {
  let deferred = false;
  let pressed = false;
  return {
    // true: dieses Neuzeichnen jetzt auslassen (und später nachholen).
    blocks(background, root, active) {
      deferred = Boolean(background) && (pressed || holdsTyping(root, active));
      return deferred;
    },
    get deferred() { return deferred; },
    pointerDown() { pressed = true; },
    pointerUp() {
      if (!pressed) return;
      pressed = false;
      if (deferred) schedule();
    },
    focusOut() { if (deferred && !pressed) schedule(); },
  };
}
