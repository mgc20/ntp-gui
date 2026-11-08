// Musterseite #/muster – nur mit ?dev=1 erreichbar, nicht in der Navigation (app.js).
// Zeigt alle Bausteine aus ui.js und die Zahlenformate aus util.js mit festen Beispielwerten,
// damit neue Seiten und Änderungen an den Bausteinen an einer Stelle geprüft werden können.
import { el, fmtSeconds, fmtDuration, fmtNumber, fmtPpm, fmtDate, fmtRate } from "../util.js";
import { card, statCard, kv, kvRow, badge, infoButton, rangePicker, emptyState, errorState, chartCard } from "../ui.js";
import { lineChart } from "../charts.js";
import { axisSeconds } from "./overview.js";

// Feste Zeitachse: 60 Punkte im Minutenabstand bis zum Zeitpunkt `end`.
function series(end, fn) {
  const out = [];
  for (let i = 59; i >= 0; i -= 1) out.push([end - i * 60, fn(i)]);
  return out;
}

const EXAMPLES = [
  ["fmtSeconds(0.001)", () => fmtSeconds(0.001)],
  ["`± ${fmtSeconds(0.001)}`", () => `± ${fmtSeconds(0.001)}`],
  ["fmtSeconds(0.014)", () => fmtSeconds(0.014)],
  ["fmtSeconds(-0.000420, 3, true)", () => fmtSeconds(-0.00042, 3, true)],
  ["fmtSeconds(0.0000004)", () => fmtSeconds(0.0000004)],
  ["fmtDuration(0.0005)", () => fmtDuration(0.0005)],
  ["fmtDuration(3600)", () => fmtDuration(3600)],
  ["fmtDuration(93784)", () => fmtDuration(93784)],
  ["fmtPpm(-12.345)", () => fmtPpm(-12.345)],
  ["fmtPpm(0.5, { signed: true })", () => fmtPpm(0.5, { signed: true })],
  ["fmtNumber(1234.5, 2)", () => fmtNumber(1234.5, 2)],
  ["fmtRate(6)", () => fmtRate(6)],
  ["fmtDate(1783000000)", () => fmtDate(1783000000)],
  ["fmtDate(\"2026-11-08\", { date: \"long\" })", () => fmtDate("2026-11-08", { date: "long" })],
  ["fmtDate(\"2026-11-08T12:34:56Z\", { time: \"medium\", utc: true })", () => fmtDate("2026-11-08T12:34:56Z", { time: "medium", utc: true })],
];

export function render(ctx) {
  const end = ctx.status?.system?.time || Math.floor(Date.now() / 1000);
  const ui = ctx.uiState;
  if (!ui.musterRange) ui.musterRange = 3600;
  const wavy = series(end, (i) => 0.0004 * Math.sin(i / 6) + 0.00002 * Math.cos(i));
  const flat = series(end, () => 0.00042);

  const numbers = el("div", { class: "table-scroll" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", { text: "Aufruf" }), el("th", {}, "Ergebnis ", infoButton("number_format", "Ergebnis")))),
    el("tbody", {}, EXAMPLES.map(([call, fn]) => el("tr", {}, el("td", {}, el("code", { text: call })), el("td", { text: fn() }))))));

  const offsetChart = (points) => (host) => lineChart(host, {
    series: [{ id: "muster", label: "Abweichung", color: "var(--accent)", points }], height: 180, key: "muster",
    format: (v) => fmtSeconds(v, 3, true), axisFormat: axisSeconds, ariaLabel: "Beispielverlauf",
  });

  return [
    card("Musterseite", { sub: "Alle Bausteine aus `ui.js` mit Beispielwerten – nur mit `?dev=1` erreichbar." },
      emptyState("Neue Seiten bauen aus diesen Teilen. Zahlen und Zeiten laufen immer über `fmt*` aus `util.js`.")),
    el("div", { class: "stat-row" },
      statCard({ label: "Abweichung", help: "system_offset", value: fmtSeconds(0.000012, 3, true), tone: "good", note: "statCard mit Ton „good“" }),
      statCard({ label: "Maximaler Fehler", help: "uncertainty", value: `± ${fmtSeconds(0.00042)}`, note: "ohne Ton" }),
      statCard({ label: "Frequenzfehler", help: "frequency", value: fmtNumber(-12.345, 3, { group: false }), unit: "ppm", tone: "warn" }),
      statCard({ label: "Anfragen", help: "served_rate", value: fmtRate(42), unit: "/min", tone: "crit", note: badge("Beispiel", "crit") })),
    el("div", { class: "grid-2" },
      card("kv und kvRow", { help: "reference" },
        kv([
          ["Referenz", "GPS (PPS)", "reference"],
          ["Root Delay", fmtSeconds(0.0001234), "root_delay"],
          ["Aktualisierungsintervall", fmtDuration(64), "update_interval"],
        ]),
        el("dl", { class: "kv-list" }, kvRow("Einzelne Zeile", fmtPpm(0.123), "skew"))),
      card("Zeitraum, Leer- und Fehlerzustand", { help: "chart_stats" },
        rangePicker({ value: ui.musterRange, onChange: (seconds) => { ui.musterRange = seconds; ctx.rerender(); },
          options: [900, 3600, 21600, 86400, 7 * 86400, 30 * 86400], focusKey: "muster-range" }),
        emptyState(`Gewählt: ${fmtDuration(ui.musterRange)}`),
        errorState({ status: 503, message: "HTTP 503" }, "die Beispieldaten"),
        el("p", { class: "card-sub" }, "infoButton: ", infoButton("number_format", "Zahlen und Einheiten")))),
    el("div", { class: "charts-grid" },
      chartCard(ctx, { title: "Verlauf mit Bewegung", help: "system_offset", key: "muster-wavy", series: [{ points: wavy }],
        format: (v) => fmtSeconds(v, 3, true), flatAbs: 1e-6, draw: offsetChart(wavy) }),
      chartCard(ctx, { title: "Maximaler Fehler", help: "uncertainty", key: "muster-flat", series: [{ points: flat }],
        format: (v) => `± ${fmtSeconds(v)}`, draw: offsetChart(flat) }),
      chartCard(ctx, { title: "Satelliten im Verlauf", help: "satellites", key: "muster-empty", series: [{ points: [] }],
        since: end - 300, draw: offsetChart([]) })),
    card("Zahlenformate", { help: "number_format", sub: "Ergebnis in der gewählten Sprache – ohne Nullen am Ende." }, numbers),
  ];
}
