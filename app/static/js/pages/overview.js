import { el, fmtSeconds, fmtNumber, fmtDuration, isNum, sourceLabel } from "../util.js";
import { card, tile, kv, badge, insightList, rangeButtons, info } from "../ui.js";
import { lineChart, stepDecimals } from "../charts.js";

export const ROUTES = { gps: "gps", sources: "quellen", settings: "einstellungen", clients: "clients", ptp: "ptp", hardware: "hardware" };

function offsetTone(offset) {
  if (!isNum(offset)) return "muted";
  const abs = Math.abs(offset);
  return abs < 0.005 ? "good" : abs < 0.05 ? "warn" : "crit";
}

export function requestRate(samples) {
  const out = [];
  for (let i = 1; i < samples.length; i += 1) {
    const a = samples[i - 1];
    const b = samples[i];
    if (!isNum(a.served) || !isNum(b.served) || b.t <= a.t) continue;
    const delta = b.served - a.served;
    out.push([b.t, delta >= 0 ? (delta / (b.t - a.t)) * 60 : null]);
  }
  return out;
}

const LEAP = {
  normal: ["Normal", "good"], "insert second": ["Schaltsekunde wird eingefügt", "info"],
  "delete second": ["Schaltsekunde wird entfernt", "info"], "not synchronised": ["Nicht synchron", "warn"],
};

function ppm(value) {
  return isNum(value) ? `${value.toFixed(3)} ppm` : "–";
}

// Alles, was „chronyc tracking“ über die Systemuhr weiß – jede Zeile mit ⓘ.
export function trackingDetails(status, ref) {
  const t = status.tracking || {};
  const system = status.system || {};
  const refName = ref ? sourceLabel(ref) : (t.ref_name || "");
  const refText = t.local_reference ? "keine – Inselbetrieb (LOCAL)"
    : [refName, t.ref_id && t.ref_id !== refName ? `ID ${t.ref_id}` : ""].filter(Boolean).join(" · ") || "–";
  const leap = LEAP[(t.leap_status || "").toLowerCase()];
  const refAge = isNum(t.ref_time) && t.ref_time > 0 ? Date.now() / 1000 - t.ref_time : null;
  const control = system.clock_control;
  return el("div", { class: "grid-2" }, kv([
    ["Referenz", refText, "reference"],
    ["Stratum", t.stratum ?? "–", "stratum"],
    ["Abweichung jetzt", fmtSeconds(t.system_time_offset, 3, true), "system_offset"],
    ["RMS-Mittel", fmtSeconds(t.rms_offset), "rms_offset"],
    ["Frequenzfehler", ppm(t.frequency_ppm), "frequency"],
    ["Skew (Unsicherheit der Frequenz)", ppm(t.skew_ppm), "skew"],
  ]), kv([
    ["Root Delay", fmtSeconds(t.root_delay), "root_delay"],
    ["Root Dispersion", fmtSeconds(t.root_dispersion), "root_dispersion"],
    ["Schaltsekunden-Status", leap ? badge(leap[0], leap[1]) : (t.leap_status || "–"), "leap"],
    ["Aktualisierungsintervall", isNum(t.update_interval) ? fmtDuration(t.update_interval) : "–", "update_interval"],
    ["Referenzzeit", refAge === null ? "–"
      : `${new Date(t.ref_time * 1000).toLocaleString("de-DE")} (vor ${fmtDuration(refAge)})`, "ref_time"],
    ["Uhrensteuerung", control === true ? badge("aktiv – chrony stellt die Uhr", "good")
      : control === false ? badge("aus (-x) – nur messen und verteilen", "warn") : "unbekannt", "clock_control"],
  ]));
}

// Dienste unter dem Supervisor (aus RUN_DIR/services.json).
const SERVICE_STATE = {
  running: ["läuft", "good"],
  restarting: ["Neustart geplant", "warn"],
  failed: ["ausgefallen", "crit"],
  stopped: ["aus", "muted"],
};
const SERVICE_ORDER = ["chronyd", "gpsd", "ptp4l", "phc2sys", "web"];
const SERVICE_INFO = { chronyd: "chronyd", ptp4l: "ptp_requirements", phc2sys: "phc2sys" };

function serviceSince(svc) {
  if (!isNum(svc.since)) return "–";
  const age = Math.max(0, Date.now() / 1000 - svc.since);
  return `seit ${fmtDuration(age)}`;
}

export function servicesCard(services) {
  const names = Object.keys(services || {});
  if (!names.length) return null;
  names.sort((a, b) => {
    const ia = SERVICE_ORDER.indexOf(a); const ib = SERVICE_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  const rows = names.map((name) => {
    const svc = services[name] || {};
    const [label, tone] = SERVICE_STATE[svc.state] || [svc.state || "unbekannt", "muted"];
    const retry = svc.state === "restarting" && isNum(svc.next_retry)
      ? ` · nächster Versuch in ${fmtDuration(Math.max(0, svc.next_retry - Date.now() / 1000))}` : "";
    return el("tr", {},
      el("td", {}, el("span", { class: "state-cell" }, el("span", { text: svc.label || name }),
        SERVICE_INFO[name] ? info(SERVICE_INFO[name], svc.label || name) : null),
        svc.optional ? null : el("div", { class: "sub", text: "Pflichtdienst" })),
      el("td", {}, badge(label, tone), svc.message ? el("div", { class: "sub", text: svc.message }) : null),
      el("td", { class: "num", text: fmtNumber(svc.restarts ?? 0) }),
      el("td", { text: svc.state === "stopped" ? "–" : `${serviceSince(svc)}${retry}` }));
  });
  return card("Dienste", {
    help: "services",
    sub: "Was der Supervisor im Container gestartet hat. Fällt ein optionaler Dienst (gpsd, ptp4l, phc2sys) aus, "
      + "startet er ihn mit wachsender Pause (5 s, 15 s, 1 min, 5 min) neu – NTP läuft dabei weiter. "
      + "„aus“ heißt: in den Einstellungen nicht eingeschaltet. Fällt chronyd oder das Dashboard aus, startet der ganze Container neu.",
  }, el("div", { class: "table-scroll" }, el("table", { class: "services-table" },
    el("thead", {}, el("tr", {}, ["Dienst", "Zustand", "Neustarts", "Seit"].map((label) =>
      el("th", { class: label === "Neustarts" ? "num" : null, text: label })))),
    el("tbody", {}, rows))));
}

export function render(ctx) {
  const { status, history } = ctx;
  const t = status.tracking || {};
  const sources = status.sources || [];
  const active = sources.filter((s) => s.state === "*" || s.state === "+").length;
  const rootDistance = isNum(t.root_delay) && isNum(t.root_dispersion) ? t.root_delay / 2 + t.root_dispersion : null;
  const rate = requestRate(history);
  const lastRate = rate.length ? rate[rate.length - 1][1] : null;
  const ref = sources.find((s) => s.state === "*");

  const tiles = [];
  if (!status.chrony_running) {
    tiles.push(tile({ label: "Zeitdienst", help: "chronyd", value: "keine Antwort", tone: "crit", note: "chronyd läuft nicht" }));
  } else {
    const local = t.local_reference && !t.synchronised;
    tiles.push(tile({
      label: "Status", help: "stratum",
      value: t.synchronised ? "Synchron" : local ? "Inselbetrieb" : "Synchronisiert …",
      tone: t.synchronised ? "good" : "warn",
      note: t.synchronised ? `Stratum ${t.stratum} · ${sourceLabel(ref) || t.ref_name}` : `Stratum ${t.stratum ?? "–"}`,
    }));
  }
  tiles.push(tile({ label: "Abweichung", help: "system_offset", value: fmtSeconds(t.system_time_offset, 3, true),
    tone: offsetTone(t.system_time_offset), note: `Mittel (RMS) ${fmtSeconds(t.rms_offset)}` }));
  tiles.push(tile({ label: "Max. Abweichung zu UTC", help: "uncertainty", value: rootDistance === null ? "–" : `± ${fmtSeconds(rootDistance)}`,
    tone: "muted", note: `Delay ${fmtSeconds(t.root_delay)} · Dispersion ${fmtSeconds(t.root_dispersion)}` }));
  tiles.push(tile({ label: "Frequenzfehler", help: "frequency", value: isNum(t.frequency_ppm) ? t.frequency_ppm.toFixed(3) : "–",
    unit: "ppm", tone: "muted", note: `Skew ${isNum(t.skew_ppm) ? t.skew_ppm.toFixed(3) : "–"} ppm` }));
  tiles.push(tile({ label: "Zeitquellen", help: "state_combined", value: `${active} / ${sources.length}`,
    tone: active ? "good" : "warn", note: active === 1 ? "1 Quelle wird genutzt" : `${active} Quellen werden genutzt` }));
  tiles.push(tile({ label: "Clients im LAN", help: "served_rate", value: fmtNumber(status.client_count ?? 0),
    tone: "muted", note: isNum(lastRate) ? `${fmtNumber(lastRate, 1)} Anfragen/min` : "noch keine Messung" }));
  const gps = status.gps || {};
  if (gps.enabled) {
    tiles.push(tile({ label: "GPS", help: gps.running && !gps.has_fix ? "cold_start" : "fix", value: gps.running ? (gps.mode_label || "–") : "gpsd offline",
      tone: gps.has_fix ? "good" : gps.running ? "warn" : "crit",
      note: gps.running ? `${gps.satellites_used ?? 0} von ${gps.satellites_seen ?? 0} Satelliten` : "keine Verbindung zu gpsd" }));
  }
  const ptp = status.ptp || {};
  if (ptp.enabled) {
    tiles.push(tile({ label: "PTP", help: "port_state", value: ptp.running ? (ptp.is_grandmaster ? "Grandmaster" : (ptp.portState || "–")) : "läuft nicht",
      tone: ptp.running ? (ptp.synchronised ? "good" : "warn") : "crit",
      note: ptp.running ? (ptp.port_state_label || "") : "ptp4l antwortet nicht" }));
  }

  const charts = el("div", { class: "charts-grid" });
  const series = (key, transform = (v) => v) => history.map((s) => [s.t, isNum(s[key]) ? transform(s[key]) : null]);
  const distance = history.map((s) => [s.t, isNum(s.root_delay) && isNum(s.root_dispersion) && s.stratum > 0 && s.stratum < 16 ? s.root_delay / 2 + s.root_dispersion : null]);
  const chartCards = [
    ["Abweichung der Systemuhr", "system_offset", "Negativ: die Systemuhr geht vor.",
      { series: [{ id: "offset", label: "Abweichung", color: "var(--accent)", points: series("offset") }],
        format: (v) => fmtSeconds(v, 3, true), axisFormat: axisSeconds, area: true }],
    ["Maximale Abweichung zu UTC", "uncertainty", "Halbe Root Delay + Root Dispersion – die Fehlerschranke.",
      { series: [{ id: "dist", label: "± max.", color: "var(--accent)", points: distance }],
        format: (v) => `± ${fmtSeconds(v)}`, axisFormat: axisSeconds, zeroLine: true, area: true }],
    ["Frequenzfehler", "frequency", "Wie schnell der Quarz ungeregelt laufen würde.",
      { series: [{ id: "freq", label: "ppm", color: "var(--accent)", points: series("freq") }],
        format: (v) => `${v.toFixed(3)} ppm`, axisFormat: (v, step) => v.toFixed(stepDecimals(step)), zeroLine: false }],
    ["Beantwortete Anfragen", "served_rate", "NTP-Anfragen aus dem LAN pro Minute.",
      { series: [{ id: "rate", label: "pro Minute", color: "var(--accent)", points: rate }],
        format: (v) => `${fmtNumber(v, 1)}/min`, axisFormat: (v, step) => fmtNumber(v, stepDecimals(step)), area: true, min: 0,
        emptyText: "Noch keine Anfragen gemessen" }],
  ];
  for (const [title, help, sub, opts] of chartCards) {
    const target = el("div", { class: "chart-host" });
    charts.append(card(title, { help, sub }, target));
    ctx.afterRender(() => lineChart(target, opts));
  }

  return [
    card("Was gerade los ist", { class: "card-insights" }, insightList(status.insights, ROUTES)),
    el("div", { class: "stat-row" }, tiles),
    el("div", { class: "toolbar" }, el("span", { class: "toolbar-label", text: "Zeitraum der Diagramme" }),
      rangeButtons(ctx.range, ctx.setRange)),
    charts,
    servicesCard(status.services),
    status.chrony_running ? card("Details zur Systemuhr", { help: "reference",
      sub: "Alles, was chrony über die eigene Uhr meldet (`chronyc tracking`). Das ⓘ erklärt jeden Wert." },
    trackingDetails(status, ref)) : null,
  ].filter(Boolean);
}

// Achsenbeschriftung: Nachkommastellen aus der Schrittweite, damit sich
// benachbarte Gitterlinien nie gleich beschriften.
export function axisSeconds(value, step) {
  const abs = Math.max(Math.abs(value), step);
  let unit = "s"; let scale = 1;
  if (abs < 1e-6) { unit = "ns"; scale = 1e9; } else if (abs < 1e-3) { unit = "µs"; scale = 1e6; } else if (abs < 1) { unit = "ms"; scale = 1e3; }
  const scaled = step * scale;
  const decimals = scaled >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(scaled)));
  return `${(value * scale).toFixed(decimals)} ${unit}`;
}

export { info };
