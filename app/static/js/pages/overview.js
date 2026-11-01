import { el, fmtSeconds, fmtNumber, isNum, sourceLabel } from "../util.js";
import { card, tile, insightList, rangeButtons, info } from "../ui.js";
import { lineChart, stepDecimals } from "../charts.js";

export const ROUTES = { gps: "gps", sources: "quellen", settings: "einstellungen", clients: "clients", ptp: "ptp" };

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
    tiles.push(tile({ label: "Zeitdienst", value: "keine Antwort", tone: "crit", note: "chronyd läuft nicht" }));
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
    tiles.push(tile({ label: "GPS", help: "fix", value: gps.running ? (gps.mode_label || "–") : "gpsd offline",
      tone: gps.has_fix ? "good" : gps.running ? "warn" : "crit",
      note: gps.running ? `${gps.satellites_used ?? 0} von ${gps.satellites_seen ?? 0} Satelliten` : "keine Verbindung zu gpsd" }));
  }
  const ptp = status.ptp || {};
  if (ptp.enabled) {
    tiles.push(tile({ label: "PTP", help: "port_state", value: ptp.running ? (ptp.is_grandmaster ? "Grandmaster" : (ptp.portState || "–")) : "aus",
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
  ];
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
