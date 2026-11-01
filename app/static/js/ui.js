// Wiederverwendbare Bausteine: Karten, Kacheln, ⓘ-Erklärungen, Badges.
import { el, rich } from "./util.js";
import { HELP } from "./help.js";

// --- ⓘ-Popover --------------------------------------------------------------
let openPopover = null;

function closePopover() {
  if (!openPopover) return;
  openPopover.button.setAttribute("aria-expanded", "false");
  openPopover.node.remove();
  openPopover = null;
}

document.addEventListener("click", (event) => {
  if (openPopover && !openPopover.node.contains(event.target) && event.target !== openPopover.button) closePopover();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && openPopover) {
    const { button } = openPopover;
    closePopover();
    button.focus();
  }
});
window.addEventListener("resize", closePopover);
window.addEventListener("scroll", closePopover, { passive: true });

export function isPopoverOpen() {
  return Boolean(openPopover && openPopover.button.isConnected);
}

export function info(key, label) {
  const entry = HELP[key];
  if (!entry) return null;
  const button = el("button", {
    type: "button", class: "info", "aria-label": `Erklärung: ${label || entry.title}`, "aria-expanded": "false",
    text: "i",
  });
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    if (openPopover && openPopover.button === button) { closePopover(); return; }
    closePopover();
    const node = el("div", { class: "popover", role: "dialog", "aria-label": entry.title },
      el("strong", { class: "popover-title", text: entry.title }),
      el("p", {}, rich(entry.text)),
      el("a", { href: `#/hilfe?t=${key}`, class: "popover-more", text: "In der Hilfe ansehen →",
        onclick: closePopover }));
    document.body.append(node);
    const rect = button.getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 24);
    node.style.width = `${width}px`;
    const left = Math.min(window.innerWidth - width - 12, Math.max(12, rect.left + rect.width / 2 - width / 2));
    node.style.left = `${left + window.scrollX}px`;
    const below = rect.bottom + 8 + node.offsetHeight < window.innerHeight;
    node.style.top = `${(below ? rect.bottom + 8 : rect.top - node.offsetHeight - 8) + window.scrollY}px`;
    button.setAttribute("aria-expanded", "true");
    openPopover = { node, button };
  });
  return button;
}

// --- Bausteine ---------------------------------------------------------------
export function card(title, options = {}, ...children) {
  const head = el("div", { class: "card-head" },
    el("div", { class: "card-title" }, el("h2", { text: title }), options.help ? info(options.help, title) : null,
      options.badge ?? null),
    options.actions ? el("div", { class: "card-actions" }, options.actions) : null);
  return el("section", { class: `card ${options.class || ""}`, id: options.id || null },
    head, options.sub ? el("p", { class: "card-sub" }, rich(options.sub)) : null, ...children);
}

export function tile({ label, value, unit, note, tone = "muted", help, long }) {
  return el("div", { class: "stat", "data-tone": tone },
    el("div", { class: "stat-label" }, el("span", { text: label }), help ? info(help, label) : null),
    el("div", { class: "stat-value", "data-long": long || String(value).length > 11 ? "true" : null },
      String(value), unit ? el("span", { class: "unit", text: unit }) : null),
    note ? el("div", { class: "stat-note", text: note }) : null);
}

export function badge(text, tone = "muted", title) {
  return el("span", { class: "badge", "data-tone": tone, title: title || null, text });
}

export function kv(rows) {
  return el("dl", { class: "kv-list" }, rows.filter(Boolean).map(([key, value, help]) =>
    el("div", { class: "kv" },
      el("dt", {}, el("span", { text: key }), help ? info(help, key) : null),
      el("dd", {}, value instanceof Node ? value : String(value ?? "–")))));
}

export function rangeButtons(current, onChange) {
  const options = [[900, "15 min"], [3600, "1 h"], [21600, "6 h"], [86400, "24 h"]];
  return el("div", { class: "range-group", role: "group", "aria-label": "Zeitraum" },
    options.map(([seconds, label]) => el("button", {
      type: "button", class: `range${current === seconds ? " is-active" : ""}`, text: label,
      "aria-pressed": current === seconds ? "true" : "false", onclick: () => onChange(seconds),
    })));
}

export function reachBar(percent, label) {
  const tone = percent >= 75 ? "good" : percent >= 25 ? "warn" : "crit";
  return el("div", { class: "reach", title: label || `${percent} %` },
    el("div", { class: "reach-track" }, el("div", { class: "reach-fill", "data-tone": tone, style: `width:${percent}%` })),
    el("span", { class: "reach-value", text: label || `${percent} %` }));
}

// Die acht letzten Abfragen als Kästchen (ältestes links).
export function reachRegister(reach) {
  const bits = [];
  for (let i = 7; i >= 0; i -= 1) bits.push((reach >> i) & 1);
  return el("div", { class: "reach-bits", title: "Letzte acht Abfragen (rechts = neueste)" },
    bits.map((b) => el("span", { class: `bit${b ? " ok" : ""}`, "aria-label": b ? "beantwortet" : "verloren" })));
}

const LEVEL_ICON = { ok: "✓", info: "i", warn: "!", crit: "✕" };

export function insightList(items, navigate) {
  if (!items || !items.length) return null;
  return el("ul", { class: "insights" }, items.map((item) => el("li", { class: "insight", "data-level": item.level },
    el("span", { class: "insight-icon", "aria-hidden": "true", text: LEVEL_ICON[item.level] || "i" }),
    el("div", { class: "insight-body" },
      el("strong", { text: item.title }),
      el("p", { text: item.text }),
      item.action ? el("a", { href: `#/${navigate[item.action] || item.action}`, class: "insight-action",
        text: ACTION_LABEL[item.action] || "Ansehen →" }) : null))));
}

const ACTION_LABEL = {
  gps: "Zur GPS-Seite →", sources: "Zu den Quellen →", settings: "Zu den Einstellungen →",
  clients: "Zu den Clients →", ptp: "Zur PTP-Seite →",
};

export function emptyNote(text) {
  return el("p", { class: "empty-note" }, rich(text));
}

export function toast(message, tone = "good") {
  const node = el("div", { class: "toast", "data-tone": tone, role: "status", text: message });
  document.body.append(node);
  setTimeout(() => node.classList.add("is-leaving"), 3200);
  setTimeout(() => node.remove(), 3800);
}
