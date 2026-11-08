// Seite „Uhrqualität“ (1.4): Temperatur ↔ Frequenz, Schaltsekunden, Vollbild-Uhr; ab 1.5 echter Holdover-Test,
// ab 1.5.4 Allan-Abweichung (wie stabil ist der Quarz über 10 s … 1 Tag).
import { el, isNum, fmtFixed, fmtNumber, fmtSeconds, fmtPpm, fmtDate, rich } from "../util.js";
import { card, statCard, kv, badge, emptyState, infoButton, loadingOr, rangePicker } from "../ui.js";
import { lineChart, logLogChart, scatterChart, stepDecimals } from "../charts.js";
import { holdoverCard } from "./gnss.js";

const RANGES = [[86400, "1 Tag"], [3 * 86400, "3 Tage"], [7 * 86400, "7 Tage"], [30 * 86400, "30 Tage"]];
// Ab so vielen Tagen im gewählten Zeitraum lässt sich der Zusammenhang Temperatur ↔ Frequenz bewerten
// (wie thermal.summarize: need_days).
const READY_DAYS = 3;

const NO_SENSOR = {
  none: "Dieses System stellt keinen Temperatursensor bereit – typisch für virtuelle Maschinen und Docker Desktop. "
    + "Ohne Messwert gibt es hier nichts aufzuzeichnen; die Uhr funktioniert trotzdem.",
  off: "Die Aufzeichnung ist abgeschaltet (Einstellungen → Dashboard → Temperatursensor = „off“).",
  missing: "Der eingestellte Sensor ist nicht (mehr) da – abgesteckt oder umbenannt? Der Hardware-Check zeigt, "
    + "welche Sensoren es gibt; „auto“ wählt selbst einen.",
  no_value: "Es gibt Sensoren, aber keiner liefert gerade einen plausiblen Wert (−40 bis 125 °C). Der Hardware-Check "
    + "zeigt die Kandidaten.",
  error: "Die Sensoren ließen sich nicht lesen. Details stehen im Container-Log.",
};

const fmtC = (v) => (isNum(v) ? `${fmtNumber(v, 1)} °C` : "–");
const fmtFreq = (v) => fmtPpm(v, { digits: 3 });

function rangeGroup(current, onChange) {
  return rangePicker({ value: current, onChange, options: RANGES, label: "Zeitraum der Temperaturauswertung", focusKey: "uqrange" });
}

function fmtDays(days) {
  if (!isNum(days) || days <= 0) return "–";
  if (days < 1) return `${fmtNumber(days * 24, 1)} h`;
  return `${fmtNumber(days, 1)} Tage`;
}

function readiness(summary) {
  if (!summary || !summary.count) return "Noch keine gemeinsamen Messpunkte von Temperatur und Frequenz.";
  const missing = [];
  if (summary.days < summary.need_days) missing.push(`${fmtDays(summary.days)} von ${fmtNumber(summary.need_days, 0)} Tagen`);
  if (summary.span_k < summary.need_span_k) missing.push(`${fmtNumber(summary.span_k, 1)} K von ${fmtNumber(summary.need_span_k, 0)} K Spanne`);
  if (!missing.length) {
    return "Genug Daten für eine Auswertung: mindestens 3 Tage und 4 K Spanne. Das Streudiagramm zeigt, "
      + "wie stark die Frequenz mit der Temperatur wandert.";
  }
  return `Es wird weiter gesammelt (bisher ${missing.join(", ")}). Für eine Aussage braucht es **1–3 Tage mit Tag-/Nacht-Wechsel**.`;
}

// Der Zeitraum gilt nur für die Temperaturauswertung – deshalb sitzen die Knöpfe in dieser Karte und
// nur, wenn es einen Sensor gibt (ohne Sensor änderten sie nichts).
function rangeActions(ctx) {
  const ui = ctx.uiState;
  return el("div", { class: "toolbar" },
    el("span", { class: "toolbar-label", text: "Zeitraum" }),
    rangeGroup(ui.uqRange, (seconds) => { ui.uqRange = seconds; ctx.rerender(); }));
}

function temperatureSection(ctx, data, loading) {
  const out = [];
  const ui = ctx.uiState;
  if (data) ui.uqTempAvailable = Boolean(data.available);
  if (!data) {
    // Beim Umschalten des Zeitraums Knöpfe stehen lassen, solange der Sensor zuletzt da war.
    out.push(card("Temperatur und Frequenz", { help: "temp_freq", actions: ui.uqTempAvailable ? rangeActions(ctx) : null }, loading));
    return out;
  }
  if (!data.available) {
    const candidates = (data.candidates || []).length;
    out.push(card("Temperatur und Frequenz", { help: "temp_freq", badge: badge("nicht verfügbar", "muted") },
      emptyState(NO_SENSOR[data.reason] || NO_SENSOR.none),
      kv([["Temperatursensor", data.setting === "off" ? "aus" : "nicht verfügbar", "temp_sensor"],
        ["Gefundene Sensoren", String(candidates), "temp_candidates"]]),
      el("p", { class: "card-sub" }, el("a", { href: "#/hardware", text: "Zum Hardware-Check →" }))));
    return out;
  }
  const summary = data.summary || {};
  const pairs = data.pairs || [];
  const sensor = data.sensor || {};
  const r = summary.correlation;
  const tone = summary.ready ? "good" : "muted";
  const enoughRange = (ui.uqRange || 0) >= READY_DAYS * 86400;
  out.push(card("Temperatur und Frequenz", { help: "temp_freq", actions: rangeActions(ctx),
    sub: "Zu jedem Messpunkt speichert ntp-gui die Temperatur. So zeigt sich, wie stark der Quarz mit ihr wandert – "
      + "die Grundlage für einen Temperaturausgleich. Hier wird nur gemessen, nichts verstellt." },
  el("div", { class: "stat-row" },
    statCard({ label: "Sensor", help: "temp_sensor", value: sensor.name || "–", note: data.setting === "auto" ? "automatisch gewählt" : "eingestellt", tone: "muted" }),
    statCard({ label: "Temperatur jetzt", help: "temp_now", value: fmtNumber(data.celsius, 1), unit: "°C",
      note: data.reason === "no_value" ? "kein Wert – wird nicht aufgezeichnet" : null, tone: data.reason === "no_value" ? "warn" : "muted" }),
    statCard({ label: "Spanne", help: "temp_span", value: fmtNumber(summary.span_k, 1), unit: "K",
      note: isNum(summary.temp_min) ? `${fmtC(summary.temp_min)} … ${fmtC(summary.temp_max)}` : null, tone }),
    statCard({ label: "Messdauer", help: "temp_duration", value: fmtDays(summary.days), note: `${fmtNumber(summary.count || 0, 0)} Punkte`, tone }),
    statCard({ label: "Zusammenhang r", help: "temp_correlation", value: fmtNumber(r, 2),
      note: !isNum(r) ? "zu wenige Punkte" : Math.abs(r) >= 0.5 ? "deutlich" : Math.abs(r) >= 0.2 ? "schwach" : "kaum", tone: "muted" })),
  data.reason === "no_value"
    ? el("p", { class: "hw-note" }, rich("Der gewählte Sensor liefert gerade **keinen plausiblen Wert** (−40 bis 125 °C) – "
      + "neue Messpunkte bekommen keine Temperatur. Der **Hardware-Check** zeigt alle Sensoren und ihre Werte."))
    : null,
  el("p", { class: "hw-note" }, rich(enoughRange ? readiness(summary)
    : `Für die Bewertung braucht es einen Zeitraum von mindestens ${READY_DAYS} Tagen – wähle oben in dieser Karte `
      + "**3 Tage** oder mehr. Der kürzere Zeitraum zeigt nur den Verlauf."))));

  const scatter = el("div", { class: "chart-host" });
  const tempChart = el("div", { class: "chart-host" });
  const freqChart = el("div", { class: "chart-host" });
  out.push(el("div", { class: "grid-2" },
    card("Temperatur ↔ Frequenz", { help: "temp_scatter", class: "chart-card",
      sub: "x: Temperatur, y: Frequenzfehler von chrony. Blasse Punkte sind älter." }, scatter),
    card("Temperaturverlauf", { help: "temp_history", class: "chart-card", sub: "Darunter der Frequenzfehler im selben Zeitraum." },
      tempChart, el("div", { class: "uq-subchart" }, el("h3", { class: "mini-head" }, "Frequenzfehler ", infoButton("frequency", "Frequenzfehler")), freqChart))));
  const range = data.range;
  ctx.afterRender(() => {
    scatterChart(scatter, { points: pairs.map(([t, x, y]) => ({ t, x, y })), height: 300, key: "uq-scatter",
      xFormat: fmtC, yFormat: fmtFreq, xAxis: (v, step) => fmtFixed(v, stepDecimals(step)), yAxis: (v, step) => fmtFixed(v, stepDecimals(step)),
      xUnit: "°C", yUnit: "ppm", ariaLabel: "Streudiagramm Temperatur gegen Frequenzfehler",
      emptyText: "Noch zu wenige Messpunkte mit Temperatur" });
    lineChart(tempChart, { height: 170, key: "uq-temp", range, zeroLine: false,
      series: [{ id: "temp", label: "°C", color: "var(--accent)", points: pairs.map(([t, x]) => [t, x]) }],
      current: data.celsius, format: fmtC, axisFormat: (v, step) => `${fmtFixed(v, stepDecimals(step))} °C`,
      ariaLabel: "Verlauf der Temperatur", emptyText: "Noch zu wenige Messpunkte mit Temperatur" });
    lineChart(freqChart, { height: 150, key: "uq-freq", range, zeroLine: false, stats: false,
      series: [{ id: "freq", label: "ppm", color: "var(--accent)", points: pairs.map(([t, , y]) => [t, y]) }],
      format: fmtFreq, axisFormat: (v, step) => `${fmtFixed(v, stepDecimals(step))} ppm`,
      ariaLabel: "Verlauf des Frequenzfehlers", emptyText: "Noch zu wenige Messpunkte" });
  });
  return out;
}

// --- Allan-Abweichung (1.5.4) --------------------------------------------------------------
const sig2 = (v) => fmtNumber(v, 0, { sig: 2 });

export function fmtTau(seconds) {
  if (!isNum(seconds)) return "–";
  if (seconds < 60) return `${fmtNumber(seconds, 0, { group: false })} s`;
  if (seconds < 3600) return `${sig2(seconds / 60)} min`;
  if (seconds < 86400) return `${sig2(seconds / 3600)} h`;
  const days = seconds / 86400;
  return `${sig2(days)} ${days < 1.05 ? "Tag" : "Tage"}`;
}

// Bruchteil → ppb (1 ppb = 0,001 ppm = 1e-9).
export function fmtPpb(fraction) {
  return isNum(fraction) ? `${sig2(fraction * 1e9)} ppb` : "–";
}

const ADEV_TICKS = [1, 10, 60, 600, 3600, 6 * 3600, 86400, 7 * 86400, 30 * 86400];
const ADEV_LEVEL = { very_quiet: "good", quiet: "good", typical: "muted", restless: "warn" };
const ADEV_REASON = {
  no_history: "Noch kein Verlauf mit Frequenzwerten von chrony.",
  few: "Noch zu kurz: Die Kurve braucht mindestens 2 Stunden Verlauf (ohne die ersten 45 min nach jedem Start "
    + "von chronyd – da läuft die Frequenz erst ein), für eine Aussage über einen Tag "
    + "mindestens 4 Tage (τ reicht bis zu einem Viertel der Messdauer).",
  error: "Der Verlauf ließ sich gerade nicht auswerten – Details im Container-Log.",
};

const driftOf = (p) => (p ? fmtSeconds(p.adev * p.tau, 1) : "–");

function adevLine(data) {
  const s = data.summary || {};
  if (!s.text || !s.ref) return null;
  let line = `Um ${fmtTau(s.ref.tau)} etwa **${fmtPpb(s.ref.adev)}** – ${s.text}.`;
  if (isNum(s.rising_after)) {
    line += ` Ab etwa ${fmtTau(s.rising_after)} steigt die Kurve wieder: Dort wirken Temperatur (Tag/Nacht) und Last.`;
  }
  return line;
}

function allanSection(data, loading) {
  const title = "Allan-Abweichung";
  if (!data) return card(title, { help: "adev" }, loading);
  if (!data.available) {
    return card(title, { help: "adev", badge: badge("sammelt", "muted") },
      emptyState(ADEV_REASON[data.reason] || ADEV_REASON.few),
      kv([["Datenbasis", data.span ? `${fmtTau(data.span)} Verlauf, ${fmtNumber(data.samples || 0, 0)} Punkte` : "–", "adev_basis"]]));
  }
  const s = data.summary || {};
  const points = data.points || [];
  const host = el("div", { class: "chart-host" });
  const table = el("details", { class: "adev-table" },
    el("summary", { text: "Als Tabelle" }),
    el("div", { class: "table-scroll" }, el("table", { class: "mini-table" },
      el("thead", {}, el("tr", {}, ["Mittelungszeit", "Allan-Abweichung", "Bereich (68 %)", "≈ Zeitfehler frei laufend", "Paare"]
        .map((h) => el("th", { text: h })))),
      el("tbody", {}, points.map((p) => el("tr", { class: p.short ? "is-muted" : null },
        el("td", { text: fmtTau(p.tau) }), el("td", { text: fmtPpb(p.adev) }),
        el("td", { text: `${fmtPpb(p.lo)} … ${fmtPpb(p.hi)}` }), el("td", { text: driftOf(p) }),
        el("td", { text: fmtNumber(p.n, 0) })))))));
  const node = card(title, { help: "adev", class: "chart-card", badge: s.level ? badge(
    { very_quiet: "sehr ruhig", quiet: "ruhig", typical: "üblich", restless: "unruhig" }[s.level], ADEV_LEVEL[s.level]) : null,
  sub: "Wie stabil ist der Quarz über 10 s … 1 Tag? Je kleiner, desto ruhiger. Grob übersetzt: Liefe die Uhr frei, "
    + "sammelte sie in der Zeit τ etwa **Wert × τ** Zeitfehler (1 ppb über 1 h ≈ 3,6 µs)." },
  el("div", { class: "stat-row" },
    statCard({ label: "Bestwert", help: "adev_best", value: fmtPpb(s.best?.adev), note: s.best ? `bei τ ≈ ${fmtTau(s.best.tau)}` : null, tone: "muted" }),
    statCard({ label: "Über 1 Stunde", help: "adev_hour", value: fmtPpb(s.hour?.adev),
      note: s.hour ? `≈ ${driftOf(s.hour)} in ${fmtTau(s.hour.tau)}` : "noch zu kurz", tone: s.level ? ADEV_LEVEL[s.level] : "muted" }),
    statCard({ label: "Über 1 Tag", help: "adev_day", value: fmtPpb(s.day?.adev),
      note: s.day ? `≈ ${driftOf(s.day)} in ${fmtTau(s.day.tau)}` : "braucht 4 Tage Verlauf", tone: "muted" }),
    statCard({ label: "Datenbasis", help: "adev_basis", value: fmtTau(data.span),
      note: `Raster ${fmtTau(data.tau0)}, ${fmtNumber((data.coverage || 0) * 100, 0)} % belegt`
        + ((data.segments || 0) > 1 ? `, ${fmtNumber(data.segments - 1, 0)}× Einschwingen nach Neustart/Sprung weggelassen` : ""),
      tone: "muted" })),
  adevLine(data) ? el("p", { class: "hw-note" }, rich(adevLine(data))) : null,
  host,
  el("p", { class: "card-sub" }, rich(`Blasse Punkte (τ unter ${fmtTau(data.short_tau)}) zeigen vor allem, wie chrony die Frequenz `
    + "nachführt, nicht den Quarz. Senkrechte Striche: Bereich, in dem der wahre Wert mit 68 % liegt.")),
  table);
  return { node, draw: () => logLogChart(host, {
    height: 260, ariaLabel: "Allan-Abweichung über τ", emptyText: "Noch zu wenige Punkte",
    points: points.map((p) => ({ x: p.tau, y: p.adev, lo: p.lo, hi: p.hi, muted: p.short, p })),
    xTicks: ADEV_TICKS, xAxis: fmtTau, yAxis: (v) => `${sig2(v * 1e9)}`, xUnit: "τ", yUnit: "ppb",
    tooltip: ({ p }) => [`τ = ${fmtTau(p.tau)}`, fmtPpb(p.adev), `Bereich ${fmtPpb(p.lo)} … ${fmtPpb(p.hi)}`,
      `≈ ${driftOf(p)} Zeitfehler in ${fmtTau(p.tau)}`, `n = ${fmtNumber(p.n, 0)}${p.short ? " · von chrony geglättet" : ""}`],
    describe: (pts) => `${pts.length} Punkte von τ = ${fmtTau(pts[0].x)} bis ${fmtTau(pts[pts.length - 1].x)}, `
      + `Bestwert ${fmtPpb(s.best?.adev)} bei ${fmtTau(s.best?.tau)}`,
  }) };
}

const CHRONY_LEAP = { Normal: "normal", "Insert second": "Schaltsekunde wird eingefügt", "Delete second": "Schaltsekunde wird entfernt",
  "Not synchronised": "nicht synchron" };

function leapSection(info_, status, loading) {
  if (!info_) return card("Schaltsekunden", { help: "leap_overview" }, loading);
  const chrony = info_.chrony_leap || status?.tracking?.leap_status;
  const chronyRow = ["Leap-Status von chrony", CHRONY_LEAP[chrony] || chrony || "–", "leap"];
  if (info_.reason === "disabled") {
    return card("Schaltsekunden", { help: "leap_overview", badge: badge("abgeschaltet", "warn") },
      emptyState("chrony kennt keine Schaltsekunden – die Einstellung „Schaltsekunden-Liste“ ist leer. Der Server kündigt "
        + "dann keine Schaltsekunde an und fügt sie nicht ein; er und seine Clients lägen danach eine Sekunde daneben, "
        + "bis sie nachregeln. Standard ist /usr/share/zoneinfo/leap-seconds.list (Einstellungen → Zeitquellen, erweitert)."),
      kv([chronyRow, ["Datei", "keine", "leap_source"]]));
  }
  const tz = info_.reason === "tz" ? info_.leapsectz : null;
  if (!info_.available) {
    if (tz) {
      return card("Schaltsekunden", { help: "leap_overview", badge: badge(`Zeitzone ${tz}`, "muted") },
        emptyState(`chrony liest Schaltsekunden aus der Zeitzone ${tz}. Die Liste ${info_.path} wäre nur zur Information da `
          + `und ist nicht lesbar: ${info_.error || "unbekannter Fehler"}.`),
        kv([chronyRow, ["Datei", `Zeitzone ${tz}`, "leap_source"]]));
    }
    return card("Schaltsekunden", { help: "leap_overview", badge: badge("Liste fehlt", "warn") },
      emptyState(`Die Schaltsekunden-Liste ${info_.path} ist nicht lesbar: ${info_.error || "unbekannter Fehler"}.`),
      kv([chronyRow, ["Datei", info_.path, "leap_source"]]));
  }
  const days = info_.days_left;
  const listReason = tz ? info_.list_reason : info_.reason;
  const expiryTone = tz ? "muted" : info_.expired ? "crit" : listReason === "expiring" ? "warn" : "good";
  const expiryText = info_.expired ? `abgelaufen seit ${-days} Tagen` : `noch ${days} Tage`;
  const hash = info_.hash_ok === true ? badge("stimmt", "good") : info_.hash_ok === false ? badge("stimmt nicht", "crit") : badge("keine Prüfsumme in der Datei", "muted");
  const last = info_.last_leap_date
    ? `${fmtDate(info_.last_leap_date, { date: "long" })} (${info_.last_leap_delta > 0 ? "+" : "−"}1 s)` : "–";
  const headBadge = tz ? badge(`Zeitzone ${tz}`, "muted")
    : info_.level === "warn" ? badge(info_.reason === "hash" ? "Prüfsumme falsch" : "Image zu alt", "warn") : badge("aktuell", "good");
  const sub = tz
    ? `chrony liest Schaltsekunden aus der Zeitzone ${tz} – die Liste unten ist nur zur Information; ihr Ablaufdatum spielt für chrony keine Rolle.`
    : "Aus der leap-seconds.list im Image (Paket tzdata) – ntp-gui lädt sie nicht selbst nach.";
  return card("Schaltsekunden", { help: "leap_overview", badge: headBadge, sub },
  kv([
    ["TAI − UTC", isNum(info_.tai_utc) ? `${info_.tai_utc} s` : "–", "leap_tai_utc"],
    ["Letzte Schaltsekunde", last, "leap_last"],
    ["Angekündigt", info_.next_leap_date ? `${fmtDate(info_.next_leap_date, { date: "long" })} (${info_.next_leap_delta > 0 ? "+" : "−"}1 s)` : "keine", "leap_next"],
    ["Liste gültig bis", el("span", {}, `${fmtDate(info_.expires_date, { date: "long" })} `, badge(expiryText, expiryTone)), "leap_expiry"],
    ["Prüfsumme (SHA-1)", hash, "leap_hash"],
    chronyRow,
    ["Datei", tz ? `${info_.path} (chrony nutzt die Zeitzone ${tz})` : info_.path, "leap_source"],
    ["Zukunft der Schaltsekunde", "spätestens 2035 abgeschafft (CGPM 2022)", "leap_future"],
  ]));
}

function clockSection(ctx) {
  const schema = ctx.data("uq-settings", "/api/settings", 120);
  const field = (schema?.fields || []).find((f) => f.key === "clock_public");
  const publicText = !field ? "–" : field.value ? "ja – Uhr und /api/v1/time ohne Passwort" : "nein – wie das Dashboard geschützt";
  return card("Vollbild-Uhr", { help: "clock_page",
    actions: el("a", { class: "button primary", href: "/clock", text: "Uhr öffnen" }) },
  el("p", { class: "card-sub" }, rich("Große Uhrzeit (Ortszeit und UTC), Datum und Kalenderwoche für Wandmonitor oder Tablet – "
    + "abgeglichen mit der Serveruhr statt mit der Uhr des Geräts. Taste **F** für Vollbild.")),
  kv([
    ["Ohne Anmeldung erreichbar", publicText, "clock_public"],
    ["Genauigkeit der Anzeige", "± halbe Laufzeit (RTT), wird auf der Uhr angezeigt", "clock_sync"],
  ]));
}

export function render(ctx) {
  const ui = ctx.uiState;
  if (!ui.uqRange) ui.uqRange = 7 * 86400;
  const tempUrl = `/api/temperature?range=${ui.uqRange}&points=1500`;
  const temp = ctx.data("temperature", tempUrl, 60);
  const leapInfo = ctx.data("leap", "/api/leap", 300);
  const allanData = ctx.data("allan", "/api/clockquality/allan", 600);
  const adev = allanSection(allanData, loadingOr(ctx, "allan", "/api/clockquality/allan", "Allan-Abweichung"));
  if (adev.draw) ctx.afterRender(adev.draw);
  return [
    el("div", { class: "toolbar section-head" },
      el("h2", { class: "section-title" }, "Uhrqualität ", infoButton("uq_page", "Uhrqualität"))),
    holdoverCard(ctx),
    ...temperatureSection(ctx, temp, loadingOr(ctx, "temperature", tempUrl, "Temperaturdaten")),
    adev.node || adev,
    el("div", { class: "grid-2" }, leapSection(leapInfo, ctx.status, loadingOr(ctx, "leap", "/api/leap", "Schaltsekunden-Daten")),
      clockSection(ctx)),
  ];
}
