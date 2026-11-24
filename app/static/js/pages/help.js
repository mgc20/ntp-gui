import { el, rich } from "../util.js";
import { card, infoButton } from "../ui.js";
import { HELP } from "../help.js";
import { HELP_SECTIONS, topic, topicHref, helpHref, neighbours, resolveHelp, searchHelp } from "../helpnav.js";
import { t, language, REFERENCE } from "../i18n.js";

export const live = false;

const SETUPS = [
  ["Nur Internet (NTP)", "ntp", "1–50 ms", "keine", "Standard. Reicht für PCs, Server, Smart-Home, Logs und Zertifikate – wenn die Internetleitung stabil ist (Festnetz/Glasfaser)."],
  ["+ NTS", "nts", "wie oben", "keine", "Gleiche Genauigkeit, aber gegen gefälschte Zeit abgesichert. Empfehlenswert: PTB, Cloudflare oder Netnod mit NTS eintragen."],
  ["+ USB-GPS ohne PPS", "gps_value", "1–10 ms", "~15 € (z. B. VK-162)", "Nicht genauer als gutes Festnetz-NTP. Lohnt bei Mobilfunk/Starlink/Satellit, häufigen Ausfällen, Netzen ohne Internet oder als unabhängige Kontrolle. Einmal kalibrieren."],
  ["+ GPS mit PPS", "pps", "< 1 µs", "~30–60 € (GPS-HAT oder Modul + GPIO)", "Tausendfach genauer. Für Messaufbauten, Audio/Video über IP und als Basis für PTP. Am Raspberry Pi über GPIO."],
  ["+ PTP", "ptp_vs_ntp", "< 1 µs im LAN", "NIC mit Hardware-Zeitstempeln (z. B. Intel i210, gebraucht ab ~30 €)", "Nur sinnvoll mit GPS+PPS als Referenz und Clients, die PTP können. Für Audio-over-IP – AES67 (Dante nur im AES67-Modus), Ravenna –, Labore, zum Lernen."],
];

// Hilfe mit Inhaltsverzeichnis und Unterseiten (1.11): #/hilfe ist das Inhaltsverzeichnis, #/hilfe/<thema>
// eine Unterseite, #/hilfe/<thema>/<schlüssel> ein hervorgehobener Eintrag (Adressen: helpnav.js). Alte Links
// #/hilfe?t=<schlüssel> zeigen den Eintrag auf seiner Unterseite. Die Suche durchsucht immer alle Themen.

// Früher in der Fußzeile (bis 1.5): die Adressen für Monitoring und Skripte.
const API_LINKS = [["/metrics", "help.api.metrics"], ["/api/status", "help.api.status"], ["/healthz", "help.api.healthz"],
  ["/readyz", "help.api.readyz"]];

function apiCard() {
  return card(t("help.api.title"), { id: "api", help: "api_keys", sub: t("help.api.intro") },
    el("dl", { class: "api-links" }, API_LINKS.map(([href, key]) => el("div", { class: "api-link" },
      el("dt", {}, el("a", { href, class: "mono", text: href })), el("dd", { text: t(key) })))));
}

function setupCard() {
  return card("Welcher Aufbau passt zu mir?", { class: "explain", sub: "Jede Stufe baut auf der vorigen auf. Für die meisten Heimnetze reicht die zweite Zeile." },
    el("div", { class: "table-scroll" }, el("table", { class: "setup-table" },
      el("thead", {}, el("tr", {}, [["Aufbau", null], ["Genauigkeit", "setup_accuracy"], ["Hardware", "hw_check"],
        ["Wann sinnvoll", null]].map(([h, help]) => el("th", {}, el("span", { text: h }), help ? infoButton(help, h) : null)))),
      el("tbody", {}, SETUPS.map(([name, help, accuracy, hardware, when]) => el("tr", {},
        el("th", {}, el("span", { text: name }), infoButton(help, name)), el("td", { class: "mono", text: accuracy }),
        el("td", { text: hardware }), el("td", { text: when })))))));
}

// Ein Eintrag: Titel mit Link auf sich selbst (zum Kopieren und Teilen), darunter der Text.
function entry(key, focus, onLink) {
  const item = HELP[key];
  return el("div", { class: `gloss${key === focus ? " is-focus" : ""}`, id: `h-${key}` },
    el("dt", {}, el("span", { text: item.title }), " ",
      el("a", { href: helpHref(key), class: "gloss-link", "aria-label": t("help.entry_link", { title: item.title }),
        text: "#", onclick: onLink })),
    el("dd", {}, rich(item.text)));
}

function tocCard() {
  return card(t("help.toc_title"), { class: "help-toc-card" },
    el("nav", { class: "help-toc", "aria-label": t("help.toc_label") }, HELP_SECTIONS.map((section) =>
      el("div", { class: "help-toc-section" },
        el("h3", { class: "mini-head", text: section.title }),
        el("ul", {}, section.topics.map(topic).filter(Boolean).map((group) => el("li", {},
          el("a", { href: topicHref(group.id), text: group.title }), " ",
          el("span", { class: "help-toc-count", text: t("help.entries", { count: group.keys.length }) }))))))));
}

function topicView(group, focus, onLink) {
  const { prev, next } = neighbours(group.id);
  const see = (group.see || []).filter((key) => HELP[key]);
  return [
    el("nav", { class: "help-crumbs", "aria-label": t("help.crumb_label") },
      el("a", { href: "#/hilfe", text: t("help.all_topics") }), el("span", { "aria-hidden": "true", text: " / " }),
      el("span", { "aria-current": "page", text: group.title })),
    card(group.title, { class: "help-group help-topic", id: `t-${group.id}` },
      el("dl", { class: "glossary" }, group.keys.filter((key) => HELP[key]).map((key) => entry(key, focus, onLink))),
      see.length ? el("p", { class: "help-see" }, el("span", { text: t("help.see_also") }), " ",
        ...see.flatMap((key, i) => [i ? ", " : null, el("a", { href: helpHref(key), text: HELP[key].title })].filter(Boolean)))
        : null),
    group.id === "api" ? apiCard() : null,
    el("nav", { class: "help-pager", "aria-label": t("help.pager_label") },
      prev ? el("a", { href: topicHref(prev.id), rel: "prev", text: t("help.prev", { topic: prev.title }) }) : el("span"),
      next ? el("a", { href: topicHref(next.id), rel: "next", text: t("help.next", { topic: next.title }) }) : el("span")),
  ];
}

function resultsView(needle, onLink) {
  const found = searchHelp(needle);
  if (!found.length) return [el("p", { class: "empty-note", text: t("help.nothing_found") })];
  return found.map(({ topic: group, keys }) => card(group.title, { class: "help-group",
    actions: el("a", { href: topicHref(group.id), class: "help-open", text: t("help.result_topic"), onclick: onLink }) },
  keys.length ? el("dl", { class: "glossary" }, keys.map((key) => entry(key, null, onLink))) : null));
}

export function render(ctx) {
  const hash = window.location.hash;
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  // Kaputte Prozent-Kodierung: routes.js liefert dann einen leeren Unterpfad – Hinweis statt stillem Inhaltsverzeichnis.
  const broken = !ctx.subpath && /^#\/hilfe\/[^?]/.test(hash);
  const view = broken ? { view: "index", notFound: true } : resolveHelp(ctx.subpath, query);
  const focus = view.view === "topic" ? view.focus : null;
  // Ein tiefer Link (ⓘ „Mehr in der Hilfe“) zeigt den Eintrag – eine alte Suche stünde sonst davor.
  if (focus) ctx.uiState.helpQuery = "";
  // Ein Treffer der Suche führt auf seine Unterseite; die Suche ist danach leer.
  const clearSearch = () => { ctx.uiState.helpQuery = ""; };
  const search = el("input", { type: "search", placeholder: t("help.search_placeholder"),
    value: ctx.uiState.helpQuery || "", "aria-label": t("help.search_label"), class: "help-search" });
  const content = el("div", { class: "help-content" }, view.view === "topic"
    ? [view.missing ? el("p", { class: "empty-note", text: t("help.entry_not_found") }) : null, topicView(view.topic, focus, clearSearch)]
    : [view.notFound ? el("p", { class: "empty-note", text: t("help.not_found") }) : null, tocCard(), setupCard(), apiCard()]);
  const results = el("div", { class: "help-groups", hidden: true });

  const draw = (needle) => {
    const active = Boolean(needle.trim());
    results.hidden = !active;
    content.hidden = active;
    results.replaceChildren(...(active ? resultsView(needle, clearSearch) : []));
  };
  search.addEventListener("input", () => { ctx.uiState.helpQuery = search.value; draw(search.value); });
  draw(ctx.uiState.helpQuery || "");
  // Zum Eintrag rollen – einmal je Aufruf der Adresse: uiState.scrolled setzt app.js bei jedem Hash-Wechsel zurück
  // (auch bei Zurück/Vor und erneutem Aufruf derselben Adresse); ein Neuzeichnen im Hintergrund reißt den Leser
  // nicht zurück. Erst nach dem Zeichnen: app.js stellt danach die Rollposition wieder her, das bräche ein sanftes
  // Rollen ab.
  if (focus && !ctx.uiState.scrolled) {
    ctx.uiState.scrolled = true;
    ctx.afterRender(() => setTimeout(() => document.getElementById(`h-${focus}`)?.scrollIntoView({
      behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" }), 0));
  }

  return [
    // Die Erklärungen sind vorerst nur deutsch (i18n-Gerüst 1.5.0) – das sagen wir offen.
    language() !== REFERENCE ? el("p", { class: "empty-note", lang: language(), text: t("help.german_only") }) : null,
    el("div", { class: "toolbar" }, search),
    results,
    content,
  ];
}
