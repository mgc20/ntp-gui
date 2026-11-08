// Wiederverwendbare Bausteine: Karten, Kacheln, ⓘ-Erklärungen, Badges.
import { el, rich, copyText, selectContents, apiPost } from "./util.js";
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

// spark: optionaler Mini-Verlauf (charts.sparkline) unter dem Wert.
export function tile({ label, value, unit, note, tone = "muted", help, long, spark }) {
  return el("div", { class: `stat${spark ? " has-spark" : ""}`, "data-tone": tone },
    el("div", { class: "stat-label" }, el("span", { text: label }), help ? info(help, label) : null),
    el("div", { class: "stat-value", "data-long": long || String(value).length > 11 ? "true" : null },
      String(value), unit ? el("span", { class: "unit", text: unit }) : null),
    note ? el("div", { class: "stat-note" }, note) : null,
    spark ? el("div", { class: "stat-spark" }, spark) : null);
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
      type: "button", class: `range${current === seconds ? " is-active" : ""}`, text: label, "data-focus-key": `range:${seconds}`,
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

export function insightList(items, navigate, ctx) {
  if (!items || !items.length) return null;
  return el("ul", { class: "insights" }, items.map((item) => el("li", { class: "insight", "data-level": item.level },
    el("span", { class: "insight-icon", "aria-hidden": "true", text: LEVEL_ICON[item.level] || "i" }),
    el("div", { class: "insight-body" },
      el("strong", { text: item.title }),
      el("p", { text: item.text }),
      insightFixes(item, ctx),
      insightLink(item),
      item.action ? el("a", { href: `#/${navigate[item.action] || item.action}`, class: "insight-action",
        text: ACTION_LABEL[item.action] || "Ansehen →" }) : null))));
}

// 1.5.4: „Per Klick beheben“ eines Hinweises (bisher nur: beobachteten Proxy eintragen). Der Knopf
// schickt nur die Kennung; welche Adresse eingetragen wird, entscheidet der Server aus seiner Liste.
const FIX_PATHS = { trust_proxy: "/api/web/proxies/trust" };

export function insightFixes(item, ctx) {
  const fixes = Array.isArray(item?.fixes) ? item.fixes.filter((f) => f && FIX_PATHS[f.kind] && f.id) : [];
  if (!fixes.length || ctx?.readonly) return null;
  return el("div", { class: "insight-fixes" }, fixes.map((fix) => el("button", {
    type: "button", class: "button", text: fix.label || "Beheben",
    onclick: async (event) => {
      if (!window.confirm(fix.confirm || `${fix.label}?`)) return;
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const result = await apiPost(FIX_PATHS[fix.kind], { id: fix.id });
        toast(result.already ? `${result.network} war schon eingetragen` : `${result.network} eingetragen`);
        for (const note of result.warnings || []) toast(note, "warn");
        ctx?.invalidate?.("settings");
        ctx?.refresh?.();
      } catch (error) {
        toast(error.message, "crit");
        button.disabled = false;
      }
    },
  })));
}

// Externer Link eines Hinweises (bisher nur Update-Hinweis): nur auf die Release-Seiten des Projekts.
const INSIGHT_LINK = /^https:\/\/github\.com\/mgc20\/ntp-gui\/releases(\/tag\/v[0-9A-Za-z.-]+)?$/;

export function insightLink(item) {
  if (!item || typeof item.link !== "string" || !INSIGHT_LINK.test(item.link)) return null;
  return el("a", { href: item.link, class: "insight-action", target: "_blank", rel: "noopener noreferrer",
    text: "Release-Notizen →" });
}

export const ACTION_LABEL = {
  gps: "Zur GPS-Seite →", sources: "Zu den Quellen →", settings: "Zu den Einstellungen →",
  clients: "Zu den Clients →", ptp: "Zur PTP-Seite →", hardware: "Zur Hardware-Seite →",
  uhrqualitaet: "Zur Uhrqualität →",
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

// „Kopieren“-Knopf für Code-Schnipsel und Schlüssel. `target` ist das Element mit
// dem Text (pre/code); klappt das Kopieren nicht, wird es markiert.
export function copyButton(text, target) {
  const button = el("button", { type: "button", class: "copy", text: "Kopieren" });
  button.addEventListener("click", async () => {
    const value = typeof text === "function" ? text() : text;
    if (await copyText(value)) { toast("Kopiert"); return; }
    const node = target || button.closest(".snippet, .apikey-token")?.querySelector("pre, code");
    const marked = selectContents(node);
    toast(marked ? "Kopieren nicht möglich – Text ist markiert, bitte Strg+C drücken" : "Kopieren nicht möglich – bitte markieren", "warn");
  });
  return button;
}
