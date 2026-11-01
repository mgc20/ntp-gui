import { el, rich } from "../util.js";
import { card } from "../ui.js";
import { HELP, HELP_GROUPS } from "../help.js";

export const live = false;

const SETUPS = [
  ["Nur Internet (NTP)", "1–50 ms", "keine", "Standard. Reicht für PCs, Server, Smart-Home, Logs und Zertifikate – wenn die Internetleitung stabil ist (Festnetz/Glasfaser)."],
  ["+ NTS", "wie oben", "keine", "Gleiche Genauigkeit, aber gegen gefälschte Zeit abgesichert. Empfehlenswert: PTB, Cloudflare oder Netnod mit NTS eintragen."],
  ["+ USB-GPS ohne PPS", "1–10 ms", "~15 € (z. B. VK-162)", "Nicht genauer als gutes Festnetz-NTP. Lohnt bei Mobilfunk/Starlink/Satellit, häufigen Ausfällen, Netzen ohne Internet oder als unabhängige Kontrolle. Einmal kalibrieren."],
  ["+ GPS mit PPS", "< 1 µs", "~30–60 € (GPS-HAT oder Modul + GPIO)", "Tausendfach genauer. Für Messaufbauten, Audio/Video über IP und als Basis für PTP. Am Raspberry Pi über GPIO."],
  ["+ PTP", "< 1 µs im LAN", "NIC mit Hardware-Zeitstempeln (z. B. Intel i210, gebraucht ab ~30 €)", "Nur sinnvoll mit GPS+PPS als Referenz und Clients, die PTP können. Für Audio-over-IP (AES67/Dante), Labore, zum Lernen."],
];

export function render(ctx) {
  const query = (ctx.uiState.helpQuery || "").toLowerCase();
  const focus = new URLSearchParams(window.location.hash.split("?")[1] || "").get("t");
  const search = el("input", { type: "search", placeholder: "Begriff suchen, z. B. Stratum, Falseticker, PPS …",
    value: ctx.uiState.helpQuery || "", "aria-label": "Hilfe durchsuchen", class: "help-search" });
  const list = el("div", { class: "help-groups" });

  const draw = (needle) => {
    list.replaceChildren(...HELP_GROUPS.map((group) => {
      const entries = group.keys.filter((key) => HELP[key] && (!needle
        || `${HELP[key].title} ${HELP[key].text}`.toLowerCase().includes(needle)));
      if (!entries.length) return null;
      return card(group.title, { class: "help-group" }, el("dl", { class: "glossary" }, entries.map((key) =>
        el("div", { class: `gloss${key === focus ? " is-focus" : ""}`, id: `h-${key}` },
          el("dt", { text: HELP[key].title }), el("dd", {}, rich(HELP[key].text))))));
    }).filter(Boolean));
    if (!list.children.length) list.append(el("p", { class: "empty-note", text: "Nichts gefunden." }));
  };
  search.addEventListener("input", () => { ctx.uiState.helpQuery = search.value; draw(search.value.toLowerCase()); });
  draw(query);
  if (focus) ctx.afterRender(() => document.getElementById(`h-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));

  return [
    card("Welcher Aufbau passt zu mir?", { class: "explain", sub: "Jede Stufe baut auf der vorigen auf. Für die meisten Heimnetze reicht die zweite Zeile." },
      el("div", { class: "table-scroll" }, el("table", { class: "setup-table" },
        el("thead", {}, el("tr", {}, ["Aufbau", "Genauigkeit", "Hardware", "Wann sinnvoll"].map((h) => el("th", { text: h })))),
        el("tbody", {}, SETUPS.map(([name, accuracy, hardware, when]) => el("tr", {},
          el("th", { text: name }), el("td", { class: "mono", text: accuracy }), el("td", { text: hardware }), el("td", { text: when }))))))),
    el("div", { class: "toolbar" }, search),
    list,
  ];
}
