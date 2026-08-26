"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const CHART_HEIGHT = 260;
const PAD = { top: 16, right: 18, bottom: 26, left: 62 };

const state = {
  status: null,
  history: [],
  range: 3600,
  hover: null,
  refresh: 5,
  clientFilter: "",
};

/* ---------------- formatting ---------------- */

function formatSeconds(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(value)) return { text: "–", unit: "" };
  const abs = Math.abs(value);
  if (abs === 0) return { text: "0", unit: "s" };
  if (abs < 1e-6) return { text: (value * 1e9).toFixed(0), unit: "ns" };
  if (abs < 1e-3) return { text: (value * 1e6).toFixed(digits > 2 ? 1 : 0), unit: "µs" };
  if (abs < 1) return { text: (value * 1e3).toFixed(digits), unit: "ms" };
  return { text: value.toFixed(digits), unit: "s" };
}

function fmt(value, digits) {
  const f = formatSeconds(value, digits);
  return f.unit ? `${f.text} ${f.unit}` : f.text;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
  return `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h`;
}

function formatLogInterval(exponent) {
  if (exponent === null || exponent === undefined) return "–";
  const seconds = Math.pow(2, Number(exponent));
  return seconds < 1 ? `${seconds.toFixed(2)} s` : formatDuration(seconds);
}

function formatTime(unix) {
  return new Date(unix * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  children.flat().forEach((child) => node.append(child));
  return node;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  return node;
}

/* ---------------- stat tiles ---------------- */

function offsetTone(offset) {
  // Ohne Messwert (chronyd down) darf die Kachel nicht "gut" signalisieren.
  if (offset === null || offset === undefined || Number.isNaN(offset)) return "muted";
  const abs = Math.abs(offset);
  if (abs < 0.01) return "good";
  if (abs < 0.1) return "warn";
  return "crit";
}

function renderStats(data) {
  const tracking = data.tracking || {};
  const stats = data.serverstats || {};
  const ptp = data.ptp || {};
  const tiles = [];

  if (!data.chrony_running) {
    tiles.push({ label: "Chrony", value: "keine Antwort", tone: "crit", note: "chronyd läuft nicht oder antwortet nicht" });
  } else {
    const local = tracking.local_reference && !tracking.synchronised;
    tiles.push({
      label: "Status",
      value: tracking.synchronised ? "Synchron" : local ? "Lokale Referenz" : "Nicht synchron",
      tone: tracking.synchronised ? "good" : "warn",
      note: local
        ? `Stratum ${tracking.stratum ?? "–"} · keine Uplink-Quelle erreichbar`
        : `Stratum ${tracking.stratum ?? "–"} · Referenz ${tracking.ref_name || "–"}`,
    });
  }

  const offset = formatSeconds(tracking.system_time_offset);
  tiles.push({
    label: "Systemabweichung",
    value: offset.text, unit: offset.unit,
    tone: offsetTone(tracking.system_time_offset),
    note: `RMS ${fmt(tracking.rms_offset)}`,
    hint: "Abweichung der Systemuhr zur Referenz – negativ bedeutet: die Systemuhr geht vor.",
  });

  tiles.push({
    label: "Frequenzfehler",
    value: tracking.frequency_ppm === undefined || tracking.frequency_ppm === null ? "–" : tracking.frequency_ppm.toFixed(3),
    unit: "ppm",
    tone: "muted",
    note: `Skew ${tracking.skew_ppm !== undefined && tracking.skew_ppm !== null ? tracking.skew_ppm.toFixed(3) : "–"} ppm`,
  });

  const dispersion = formatSeconds(tracking.root_dispersion);
  tiles.push({
    label: "Root Dispersion",
    value: dispersion.text, unit: dispersion.unit,
    tone: "muted",
    note: `Root Delay ${fmt(tracking.root_delay)}`,
  });

  // chronyc activity zählt nur Netzwerkquellen – Refclocks wie GPS fehlen dort.
  const sources = data.sources || [];
  const activeSources = sources.filter((s) => s.state_label === "synced" || s.state_label === "combined").length;
  tiles.push({
    label: "NTP-Clients",
    value: String(data.client_count ?? 0),
    tone: "muted",
    note: sources.length
      ? `${activeSources} von ${sources.length} ${sources.length === 1 ? "Quelle" : "Quellen"} aktiv`
      : "keine Zeitquelle konfiguriert",
  });

  const served = stats.ntp_packets_received;
  tiles.push({
    label: "Beantwortete Pakete",
    value: served === undefined ? "–" : served.toLocaleString("de-DE"),
    tone: "muted",
    note: `${(stats.ntp_packets_dropped ?? 0).toLocaleString("de-DE")} verworfen`,
  });

  const gps = data.gps || {};
  if (gps.enabled) {
    tiles.push({
      label: "GPS-Fix",
      value: gps.running ? (gps.mode_label || "–") : "gpsd offline",
      tone: gps.has_fix ? "good" : gps.running ? "warn" : "crit",
      note: gps.running ? `${gps.satellites_used ?? 0} von ${gps.satellites_seen ?? 0} Satelliten` : "kein Kontakt zu gpsd",
    });
  }

  if (ptp.enabled) {
    const ptpOffset = typeof ptp.offset_ns === "number" ? formatSeconds(ptp.offset_ns / 1e9) : null;
    tiles.push({
      label: ptp.is_grandmaster ? "PTP-Rolle" : "PTP-Offset",
      value: ptp.is_grandmaster ? "Grandmaster" : ptpOffset ? ptpOffset.text : "–",
      unit: ptp.is_grandmaster ? "" : ptpOffset ? ptpOffset.unit : "",
      tone: ptp.running ? (ptp.synchronised ? "good" : "warn") : "crit",
      note: ptp.running ? (ptp.port_state_label || "aktiv") : "ptp4l antwortet nicht",
    });
  }

  const container = document.getElementById("stats");
  container.replaceChildren(
    ...tiles.map((tile) =>
      el("div", { class: "stat", "data-tone": tile.tone || "muted", title: tile.hint || null },
        el("div", { class: "stat-label", text: tile.label }),
        el("div", { class: "stat-value", "data-long": String(tile.value).length > 10 ? "true" : null },
          document.createTextNode(tile.value),
          tile.unit ? el("span", { class: "unit", text: tile.unit }) : ""),
        el("div", { class: "stat-note", text: tile.note || "" }))
    )
  );
}

/* ---------------- chart ---------------- */

function visibleSamples() {
  const samples = state.history.filter((s) => typeof s.offset === "number");
  if (!state.range) return samples;
  const cutoff = (samples.length ? samples[samples.length - 1].t : Date.now() / 1000) - state.range;
  return samples.filter((s) => s.t >= cutoff);
}

function formatAxisValue(value, step) {
  // Die Nachkommastellen folgen der Schrittweite, damit benachbarte
  // Gitterlinien nie dieselbe Beschriftung tragen (fmt() rundet µs auf 0).
  const abs = Math.max(Math.abs(value), step);
  let unit = "s", scale = 1;
  if (abs < 1e-6) { unit = "ns"; scale = 1e9; }
  else if (abs < 1e-3) { unit = "µs"; scale = 1e6; }
  else if (abs < 1) { unit = "ms"; scale = 1e3; }
  const scaledStep = step * scale;
  const decimals = scaledStep >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(scaledStep)));
  return `${(value * scale).toFixed(decimals)} ${unit}`;
}

function niceStep(span) {
  if (span <= 0) return 1;
  const raw = span / 4;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const normalised = raw / magnitude;
  const step = normalised >= 5 ? 5 : normalised >= 2 ? 2 : 1;
  return step * magnitude;
}

function renderChart() {
  const node = document.getElementById("chart");
  const width = Math.max(320, document.getElementById("chart-wrap").clientWidth);
  node.setAttribute("viewBox", `0 0 ${width} ${CHART_HEIGHT}`);
  node.replaceChildren();

  const samples = visibleSamples();
  if (samples.length < 2) {
    const text = svg("text", { x: width / 2, y: CHART_HEIGHT / 2, "text-anchor": "middle", class: "chart-empty" });
    text.textContent = "Sammle Messwerte …";
    node.append(text);
    document.getElementById("chart-tooltip").hidden = true;
    return;
  }

  const values = samples.map((s) => s.offset);
  let min = Math.min(0, ...values);
  let max = Math.max(0, ...values);
  if (min === max) { min -= 1e-6; max += 1e-6; }
  const step = niceStep(max - min);
  min = Math.floor(min / step) * step;
  max = Math.ceil(max / step) * step;

  const t0 = samples[0].t;
  const t1 = samples[samples.length - 1].t;
  const plotW = width - PAD.left - PAD.right;
  const plotH = CHART_HEIGHT - PAD.top - PAD.bottom;
  const x = (t) => PAD.left + (t1 === t0 ? plotW : ((t - t0) / (t1 - t0)) * plotW);
  const y = (v) => PAD.top + plotH - ((v - min) / (max - min)) * plotH;

  const defs = svg("defs");
  const gradient = svg("linearGradient", { id: "area-gradient", x1: "0", y1: "0", x2: "0", y2: "1" });
  gradient.append(svg("stop", { offset: "0%", "stop-color": "var(--accent)", "stop-opacity": "0.26" }));
  gradient.append(svg("stop", { offset: "100%", "stop-color": "var(--accent)", "stop-opacity": "0.01" }));
  defs.append(gradient);
  node.append(defs);

  for (let v = min; v <= max + step / 2; v += step) {
    const value = Math.abs(v) < step / 1e6 ? 0 : v;  // kill -0 and float residue
    const yy = y(v);
    node.append(svg("line", { class: "chart-grid", x1: PAD.left, x2: width - PAD.right, y1: yy, y2: yy }));
    const label = svg("text", { class: "chart-label", x: PAD.left - 10, y: yy + 3.5, "text-anchor": "end" });
    label.textContent = formatAxisValue(value, step);
    node.append(label);
  }

  if (min < 0 && max > 0) {
    node.append(svg("line", { class: "chart-zero", x1: PAD.left, x2: width - PAD.right, y1: y(0), y2: y(0) }));
  }

  const points = samples.map((s) => `${x(s.t).toFixed(2)},${y(s.offset).toFixed(2)}`);
  const baseline = y(Math.max(min, Math.min(0, max)));
  node.append(svg("path", {
    class: "chart-area",
    d: `M${x(t0).toFixed(2)},${baseline.toFixed(2)} L${points.join(" L")} L${x(t1).toFixed(2)},${baseline.toFixed(2)} Z`,
  }));
  node.append(svg("path", { class: "chart-line", d: `M${points.join(" L")}` }));

  [t0, (t0 + t1) / 2, t1].forEach((t, index) => {
    const label = svg("text", {
      class: "chart-label", x: x(t), y: CHART_HEIGHT - 6,
      "text-anchor": index === 0 ? "start" : index === 2 ? "end" : "middle",
    });
    label.textContent = formatTime(t);
    node.append(label);
  });

  const tooltip = document.getElementById("chart-tooltip");
  if (state.hover !== null) {
    const sample = samples[Math.min(state.hover, samples.length - 1)];
    const px = x(sample.t);
    const py = y(sample.offset);
    node.append(svg("line", { class: "chart-cursor", x1: px, x2: px, y1: PAD.top, y2: PAD.top + plotH }));
    node.append(svg("circle", { class: "chart-marker", cx: px, cy: py, r: 4.5 }));
    tooltip.replaceChildren(
      el("b", { text: fmt(sample.offset) }),
      el("span", { text: `${formatTime(sample.t)} · Stratum ${sample.stratum ?? "–"}` })
    );
    tooltip.style.left = `${(px / width) * 100}%`;
    tooltip.style.top = `${py}px`;
    tooltip.hidden = false;
  } else {
    tooltip.hidden = true;
  }

  node.onpointermove = (event) => {
    const rect = node.getBoundingClientRect();
    const scale = width / rect.width;
    const px = (event.clientX - rect.left) * scale;
    const ratio = Math.min(1, Math.max(0, (px - PAD.left) / plotW));
    const time = t0 + ratio * (t1 - t0);
    let nearest = 0;
    let best = Infinity;
    samples.forEach((s, index) => {
      const distance = Math.abs(s.t - time);
      if (distance < best) { best = distance; nearest = index; }
    });
    if (nearest !== state.hover) { state.hover = nearest; renderChart(); }
  };
  node.onpointerleave = () => { state.hover = null; renderChart(); };
}

/* ---------------- tables ---------------- */

function renderSources(sources) {
  const body = document.querySelector("#sources tbody");
  document.getElementById("source-count").textContent = sources.length;
  if (!sources.length) {
    body.replaceChildren(el("tr", {}, el("td", { colspan: "8", class: "empty-note", text: "Keine Zeitquellen konfiguriert." })));
    return;
  }
  body.replaceChildren(...sources.map((source) => {
    const reach = source.reach_percent ?? 0;
    const tone = reach >= 75 ? "good" : reach >= 25 ? "warn" : "crit";
    const bar = el("div", { class: "reach" },
      el("div", { class: "reach-track" }, el("div", { class: "reach-fill", "data-tone": tone, style: `width:${reach}%` })),
      el("span", { class: "reach-value", text: `${reach}%` }));
    return el("tr", {},
      el("td", { class: "mono", text: source.name || "–" }),
      el("td", { text: source.mode_label || "–" }),
      el("td", { class: "num", text: source.stratum ?? "–" }),
      el("td", { class: "num", title: `log2-Intervall ${source.poll ?? "–"}`, text: formatLogInterval(source.poll) }),
      el("td", {}, bar),
      el("td", { class: "num", text: fmt(source.offset) }),
      el("td", { class: "num", text: source.std_dev !== undefined && source.std_dev !== null ? fmt(source.std_dev) : "–" }),
      el("td", {}, el("span", { class: "state", "data-state": source.state_label || "", text: source.state_label || "–" })));
  }));
}

function renderClients(clients) {
  const body = document.querySelector("#clients tbody");
  const filter = state.clientFilter.trim().toLowerCase();
  const rows = clients.filter((c) => !filter || (c.address || "").toLowerCase().includes(filter));
  document.getElementById("client-count").textContent = clients.length;
  document.getElementById("clients-empty").hidden = clients.length !== 0;
  body.replaceChildren(...rows.map((client) =>
    el("tr", {},
      el("td", { class: "mono", text: client.address }),
      el("td", { class: "num", text: (client.ntp_packets ?? 0).toLocaleString("de-DE") }),
      el("td", { class: "num", text: (client.ntp_dropped ?? 0).toLocaleString("de-DE") }),
      el("td", { class: "num", text: formatLogInterval(client.ntp_interval) }),
      el("td", { class: "num", text: client.ntp_last_rx !== null && client.ntp_last_rx !== undefined ? `vor ${formatDuration(client.ntp_last_rx)}` : "–" }))));
}

function renderGps(gps) {
  const badge = document.getElementById("gps-badge");
  const body = document.getElementById("gps-body");

  if (!gps || !gps.enabled) {
    badge.textContent = "aus";
    body.replaceChildren(el("div", { class: "ptp-off" },
      document.createTextNode("Kein GPS konfiguriert. Mit einem USB-Empfänger (z. B. VK-162) genügt:"),
      el("code", { text: "--device /dev/ttyACM0\nGPS_ENABLE=true\nGPS_DEVICE=/dev/ttyACM0" })));
    return;
  }

  if (!gps.running) {
    badge.textContent = "keine Antwort";
    body.replaceChildren(el("div", { class: "ptp-off" },
      document.createTextNode(`gpsd antwortet nicht. Ist ${gps.device || "das Gerät"} in den Container durchgereicht?`),
      el("code", { text: "docker run --device /dev/ttyACM0 …" })));
    return;
  }

  badge.textContent = gps.mode_label || "aktiv";
  const used = gps.satellites_used ?? 0;
  const seen = gps.satellites_seen ?? 0;
  const ratio = seen ? Math.round((used / seen) * 100) : 0;
  const tone = used >= 4 ? "good" : used > 0 ? "warn" : "crit";
  const satBar = el("div", { class: "reach" },
    el("div", { class: "reach-track" }, el("div", { class: "reach-fill", "data-tone": tone, style: `width:${ratio}%` })),
    el("span", { class: "reach-value", text: `${used}/${seen}` }));

  const rows = [
    ["Gerät", gps.device || "–"],
    ["Fix", gps.mode_label || "–"],
    ["HDOP", gps.hdop !== undefined ? gps.hdop.toFixed(2) : "–"],
    ["Ø Signal", gps.snr_avg !== undefined ? `${gps.snr_avg} dB` : "–"],
    ["PPS", gps.pps || (gps.pps_missing ? `${gps.pps_missing} fehlt` : "nicht konfiguriert")],
    ["GPS-Zeit", gps.time || "–"],
  ];
  if (gps.lat !== undefined && gps.lon !== undefined) {
    rows.push(["Position", `${gps.lat.toFixed(5)}, ${gps.lon.toFixed(5)}`]);
  }
  if (gps.gpsd_release) rows.push(["gpsd", gps.gpsd_release]);

  const list = el("dl", {},
    el("div", { class: "kv" }, el("dt", { text: "Satelliten" }), el("dd", {}, satBar)),
    ...rows.map(([key, value]) =>
      el("div", { class: "kv" }, el("dt", { text: key }), el("dd", { text: String(value) }))));
  body.replaceChildren(list);
}

function renderPtp(ptp) {
  const badge = document.getElementById("ptp-badge");
  const body = document.getElementById("ptp-body");

  if (!ptp || !ptp.enabled) {
    badge.textContent = "aus";
    body.replaceChildren(el("div", { class: "ptp-off" },
      document.createTextNode("PTP ist deaktiviert. Aktivieren mit Host-Netzwerk und einem Interface mit Hardware-Zeitstempeln:"),
      el("code", { text: "PTP_ENABLE=true\nPTP_INTERFACE=eth0\nPTP_MODE=auto" })));
    return;
  }

  badge.textContent = ptp.running ? (ptp.portState || "aktiv") : "keine Antwort";
  const rows = [
    ["Interface", ptp.interface || "–"],
    ["Portstatus", ptp.port_state_label || "–"],
    ["Domain", ptp.domainNumber ?? ptp.domain ?? "–"],
    ["Transport", ptp.transport || "–"],
    ["Offset zum Master", ptp.is_grandmaster ? "– (eigener Grandmaster)" : typeof ptp.offset_ns === "number" ? fmt(ptp.offset_ns / 1e9) : "–"],
    ["Mean Path Delay", typeof ptp.meanPathDelay === "number" ? fmt(ptp.meanPathDelay / 1e9) : "–"],
    ["Grandmaster", ptp.grandmasterIdentity || ptp.gmIdentity || "–"],
    ["GM Clock Class", ptp["gm.ClockClass"] ?? "–"],
    ["Steps Removed", ptp.stepsRemoved ?? "–"],
    ["UTC Offset", ptp.currentUtcOffset ?? "–"],
  ];
  const list = el("dl", {}, ...rows.map(([key, value]) =>
    el("div", { class: "kv" }, el("dt", { text: key }), el("dd", { text: String(value) }))));
  const children = [list];
  if (ptp.log && ptp.log.length) {
    children.push(el("pre", { class: "log", text: ptp.log.slice(-12).join("\n") }));
  }
  body.replaceChildren(...children);
}

/* ---------------- refresh loop ---------------- */

function renderSyncPill(data) {
  const pill = document.getElementById("sync-pill");
  const label = document.getElementById("sync-label");
  if (!data.chrony_running) {
    pill.dataset.state = "crit";
    label.textContent = "chronyd offline";
  } else if (data.tracking.synchronised) {
    pill.dataset.state = "good";
    label.textContent = `Synchron · Stratum ${data.tracking.stratum}`;
  } else if (data.tracking.local_reference) {
    pill.dataset.state = "warn";
    label.textContent = `Inselbetrieb · Stratum ${data.tracking.stratum ?? "–"}`;
  } else {
    pill.dataset.state = "warn";
    label.textContent = "Synchronisiert noch …";
  }
}

async function refresh() {
  try {
    const [status, history] = await Promise.all([
      fetch("/api/status", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/history", { cache: "no-store" }).then((r) => r.json()),
    ]);
    state.status = status;
    state.history = history.samples || [];
    document.body.classList.remove("is-stale");

    document.getElementById("title").textContent = status.system.title;
    document.title = status.system.title;
    document.getElementById("hostname").textContent = status.system.hostname;
    document.getElementById("clock").textContent =
      `${new Date(status.system.time * 1000).toLocaleString("de-DE")} ${status.system.timezone || ""}`;
    document.getElementById("footer-note").textContent =
      `Aktualisierung alle ${status.system.refresh_seconds} s · Laufzeit ${formatDuration(status.system.uptime_seconds)}`;
    state.refresh = status.system.refresh_seconds || 5;

    renderSyncPill(status);
    renderStats(status);
    renderSources(status.sources || []);
    renderClients(status.clients || []);
    renderGps(status.gps);
    renderPtp(status.ptp);
    renderChart();
  } catch (error) {
    document.body.classList.add("is-stale");
    document.getElementById("sync-pill").dataset.state = "crit";
    document.getElementById("sync-label").textContent = "keine Verbindung";
  }
  window.setTimeout(refresh, Math.max(1, state.refresh) * 1000);
}

async function loadConfig() {
  try {
    const config = await fetch("/api/config", { cache: "no-store" }).then((r) => r.json());
    document.getElementById("config").textContent = config.content;
    document.querySelector("#config-details summary h2").textContent = `Aktive ${config.path.split("/").pop()}`;
  } catch (error) {
    document.getElementById("config").textContent = "Konfiguration nicht lesbar.";
  }
}

/* ---------------- boot ---------------- */

function initTheme() {
  let theme = null;
  try { theme = window.localStorage.getItem("ntp-gui-theme"); } catch (error) { /* private mode */ }
  if (!theme) {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  document.documentElement.dataset.theme = theme;
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { window.localStorage.setItem("ntp-gui-theme", next); } catch (error) { /* ignore */ }
    renderChart();
  });
}

document.querySelectorAll(".range").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".range").forEach((other) => other.classList.remove("is-active"));
    button.classList.add("is-active");
    state.range = Number(button.dataset.range);
    state.hover = null;
    renderChart();
  });
});

document.getElementById("client-filter").addEventListener("input", (event) => {
  state.clientFilter = event.target.value;
  if (state.status) renderClients(state.status.clients || []);
});

window.addEventListener("resize", () => renderChart());

initTheme();
loadConfig();
refresh();
