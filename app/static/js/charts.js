// SVG-Diagramme ohne Bibliothek: Linien (mehrere Serien), Himmelskarte, Balken.
import { el, svgEl, fmtTime, isNum } from "./util.js";

// Validierte Kategorienpalette (dataviz-Referenz), je Theme eigene Stufen.
const PALETTE = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};

// Farbe folgt der Quelle, nicht ihrer Position: einmal vergeben, bleibt sie.
const SLOTS = new Map();
export function colorFor(id) {
  if (!SLOTS.has(id)) SLOTS.set(id, SLOTS.size);
  const theme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  const slot = SLOTS.get(id);
  return { color: PALETTE[theme][slot % 8], dashed: slot >= 8 };
}

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// SVG-Attribute kennen kein var(--x): Variablen vorher auflösen.
function resolve(color) {
  const match = /^var\((--[\w-]+)\)$/.exec(color || "");
  return match ? css(match[1]) || color : color;
}

function seriesColor(series) {
  return series.color ? { color: resolve(series.color), dashed: false } : colorFor(series.id);
}

function niceStep(span, count = 4) {
  if (!(span > 0)) return 1;
  const raw = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalised = raw / magnitude;
  return (normalised >= 5 ? 5 : normalised >= 2 ? 2 : 1) * magnitude;
}

/**
 * Liniendiagramm.
 * opts: { series: [{id, label, color?, points: [[t, v], ...]}], format(v), axisFormat(v, step),
 *         height, zeroLine, emptyText, hidden: Set, onToggle(id) }
 */
export function lineChart(container, opts) {
  const height = opts.height || 220;
  const width = Math.max(320, container.clientWidth || 640);
  const pad = { top: 14, right: opts.series.length <= 4 && opts.series.length > 1 ? 92 : 18, bottom: 26, left: 66 };
  const hidden = opts.hidden || new Set();
  const visible = opts.series.filter((s) => !hidden.has(s.id) && s.points.some((p) => isNum(p[1])));
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img",
    "aria-label": opts.ariaLabel || "Verlaufsdiagramm", class: "chart-svg" });
  container.replaceChildren();
  const figure = el("div", { class: "chart-wrap" }, svg);
  container.append(figure);

  if (opts.series.length > 1) {
    const legend = el("div", { class: "legend" });
    for (const series of opts.series) {
      const { color, dashed } = seriesColor(series);
      legend.append(el("button", {
        type: "button", class: `legend-item${hidden.has(series.id) ? " is-off" : ""}`,
        "aria-pressed": hidden.has(series.id) ? "false" : "true",
        title: hidden.has(series.id) ? "einblenden" : "ausblenden",
        onclick: () => opts.onToggle && opts.onToggle(series.id),
      }, el("span", { class: `swatch${dashed ? " dashed" : ""}`, style: `--c:${color}` }), series.label));
    }
    container.prepend(legend);
  }

  const all = visible.flatMap((s) => s.points.filter((p) => isNum(p[1])));
  if (all.length < 2) {
    const text = svgEl("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "chart-empty" });
    text.textContent = opts.emptyText || "Noch zu wenige Messwerte";
    svg.append(text);
    return;
  }
  let t0 = Math.min(...all.map((p) => p[0]));
  let t1 = Math.max(...all.map((p) => p[0]));
  if (t0 === t1) t1 = t0 + 1;
  let lo = Math.min(...all.map((p) => p[1]));
  let hi = Math.max(...all.map((p) => p[1]));
  if (opts.zeroLine !== false) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (opts.min !== undefined) lo = Math.min(lo, opts.min);
  if (lo === hi) {
    if (opts.min !== undefined && lo <= opts.min) hi = lo + (opts.minSpan || 1);
    else { const d = Math.abs(lo) || 1e-6; lo -= d; hi += d; }
  }
  const step = niceStep(hi - lo);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;

  const pw = width - pad.left - pad.right;
  const ph = height - pad.top - pad.bottom;
  const X = (t) => pad.left + ((t - t0) / (t1 - t0)) * pw;
  const Y = (v) => pad.top + ph - ((v - lo) / (hi - lo)) * ph;

  for (let v = lo; v <= hi + step / 2; v += step) {
    const value = Math.abs(v) < step / 1e6 ? 0 : v;
    svg.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: Y(v), y2: Y(v), class: "chart-grid" }));
    const label = svgEl("text", { x: pad.left - 8, y: Y(v) + 4, "text-anchor": "end", class: "chart-label" });
    label.textContent = (opts.axisFormat || opts.format)(value, step);
    svg.append(label);
  }
  if (lo < 0 && hi > 0) {
    svg.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: Y(0), y2: Y(0), class: "chart-zero" }));
  }
  const span = t1 - t0;
  [t0, t0 + span / 2, t1].forEach((t, i) => {
    const label = svgEl("text", { x: X(t), y: height - 6, class: "chart-label",
      "text-anchor": i === 0 ? "start" : i === 2 ? "end" : "middle" });
    label.textContent = fmtTime(t, span < 7200);
    svg.append(label);
  });

  const drawn = [];
  for (const series of visible) {
    const { color, dashed } = seriesColor(series);
    // Lücken (fehlende Werte) unterbrechen die Linie, statt sie zu überbrücken.
    let d = "";
    let pen = false;
    for (const [t, v] of series.points) {
      if (!isNum(v)) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${X(t).toFixed(1)},${Y(v).toFixed(1)} `;
      pen = true;
    }
    if (opts.area && visible.length === 1) {
      // Fläche je zusammenhängendem Abschnitt – an Messlücken reißt sie ab wie die Linie.
      const base = Y(Math.max(lo, Math.min(0, hi)));
      const segments = [[]];
      for (const p of series.points) {
        if (isNum(p[1])) segments[segments.length - 1].push(p);
        else if (segments[segments.length - 1].length) segments.push([]);
      }
      const area = segments.filter((seg) => seg.length > 1).map((seg) => `M${X(seg[0][0]).toFixed(1)},${base} `
        + seg.map(([t, v]) => `L${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")
        + ` L${X(seg[seg.length - 1][0]).toFixed(1)},${base} Z`).join(" ");
      if (area) svg.append(svgEl("path", { d: area, fill: color, opacity: "0.12" }));
    }
    svg.append(svgEl("path", { d, fill: "none", stroke: color, "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": dashed ? "6 4" : null }));
    drawn.push({ series, color });
  }

  // Direkte Beschriftung am Linienende (bis 4 Serien), Kollisionen auseinanderschieben.
  if (visible.length > 1 && visible.length <= 4) {
    const ends = drawn.map(({ series, color }) => {
      const last = [...series.points].reverse().find((p) => isNum(p[1]));
      return { y: Y(last[1]), label: series.label, color };
    }).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i += 1) {
      if (ends[i].y - ends[i - 1].y < 13) ends[i].y = ends[i - 1].y + 13;
    }
    for (const end of ends) {
      svg.append(svgEl("circle", { cx: width - pad.right + 6, cy: end.y, r: 3, fill: end.color }));
      const text = svgEl("text", { x: width - pad.right + 12, y: end.y + 4, class: "chart-end-label" });
      text.textContent = end.label.length > 12 ? `${end.label.slice(0, 11)}…` : end.label;
      svg.append(text);
    }
  }

  // Fadenkreuz + Tooltip
  const tooltip = el("div", { class: "tooltip", hidden: true });
  figure.append(tooltip);
  const cursor = svgEl("line", { y1: pad.top, y2: pad.top + ph, class: "chart-cursor", visibility: "hidden" });
  const markers = svgEl("g");
  svg.append(cursor, markers);
  const times = [...new Set(all.map((p) => p[0]))].sort((a, b) => a - b);
  svg.addEventListener("pointermove", (event) => {
    const rect = svg.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    const target = t0 + Math.min(1, Math.max(0, (px - pad.left) / pw)) * (t1 - t0);
    let best = times[0];
    for (const t of times) if (Math.abs(t - target) < Math.abs(best - target)) best = t;
    cursor.setAttribute("x1", X(best)); cursor.setAttribute("x2", X(best));
    cursor.setAttribute("visibility", "visible");
    markers.replaceChildren();
    const rows = [];
    for (const { series, color } of drawn) {
      const point = series.points.find((p) => p[0] === best);
      if (!point || !isNum(point[1])) continue;
      markers.append(svgEl("circle", { cx: X(best), cy: Y(point[1]), r: 4, fill: color, class: "chart-marker" }));
      rows.push(el("div", { class: "tt-row" }, el("span", { class: "swatch", style: `--c:${color}` }),
        el("span", { class: "tt-label", text: series.label }), el("b", { text: opts.format(point[1]) })));
    }
    tooltip.replaceChildren(el("div", { class: "tt-time", text: fmtTime(best) }), ...rows);
    tooltip.hidden = rows.length === 0;
    const left = (X(best) / width) * 100;
    tooltip.style.left = `${left}%`;
    tooltip.style.transform = left > 60 ? "translate(calc(-100% - 12px), 8px)" : "translate(12px, 8px)";
  });
  svg.addEventListener("pointerleave", () => {
    cursor.setAttribute("visibility", "hidden");
    markers.replaceChildren();
    tooltip.hidden = true;
  });
}

/** Himmelskarte: Mitte = Zenit, Rand = Horizont, Norden oben. */
export function skyPlot(container, satellites) {
  const size = 300;
  const c = size / 2;
  const r = c - 26;
  const svg = svgEl("svg", { viewBox: `0 0 ${size} ${size}`, class: "sky", role: "img",
    "aria-label": "Himmelskarte der Satelliten" });
  for (const elev of [0, 30, 60]) {
    svg.append(svgEl("circle", { cx: c, cy: c, r: r * (1 - elev / 90), class: "sky-ring" }));
    if (elev) {
      const label = svgEl("text", { x: c + 3, y: c - r * (1 - elev / 90) - 3, class: "sky-label" });
      label.textContent = `${elev}°`;
      svg.append(label);
    }
  }
  svg.append(svgEl("line", { x1: c - r, x2: c + r, y1: c, y2: c, class: "sky-ring" }));
  svg.append(svgEl("line", { x1: c, x2: c, y1: c - r, y2: c + r, class: "sky-ring" }));
  for (const [label, x, y] of [["N", c, 14], ["O", size - 10, c + 4], ["S", c, size - 6], ["W", 10, c + 4]]) {
    const text = svgEl("text", { x, y, "text-anchor": "middle", class: "sky-compass" });
    text.textContent = label;
    svg.append(text);
  }
  const tooltip = el("div", { class: "tooltip", hidden: true });
  for (const sat of satellites) {
    if (!isNum(sat.elevation) || !isNum(sat.azimuth) || sat.elevation < 0) continue;
    const dist = r * (1 - sat.elevation / 90);
    const angle = (sat.azimuth * Math.PI) / 180;
    const x = c + dist * Math.sin(angle);
    const y = c - dist * Math.cos(angle);
    const group = svgEl("g", { class: `sky-sat${sat.used ? " used" : ""}`, tabindex: 0 });
    group.append(svgEl("circle", { cx: x, cy: y, r: 9, class: "sky-dot" }));
    const text = svgEl("text", { x, y: y + 3.5, "text-anchor": "middle", class: "sky-prn" });
    text.textContent = sat.prn ?? "";
    group.append(text);
    const show = () => {
      tooltip.replaceChildren(
        el("div", { class: "tt-time", text: `${sat.system} · PRN ${sat.prn}` }),
        el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Elevation / Azimut" }),
          el("b", { text: `${sat.elevation}° / ${sat.azimuth}°` })),
        el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Signal" }),
          el("b", { text: isNum(sat.snr) ? `${sat.snr} dB-Hz` : "–" })),
        el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Status" }),
          el("b", { text: sat.used ? "genutzt" : "sichtbar, nicht genutzt" })));
      tooltip.style.left = `${(x / size) * 100}%`;
      tooltip.style.top = `${(y / size) * 100}%`;
      tooltip.style.transform = "translate(12px, -50%)";
      tooltip.hidden = false;
    };
    group.addEventListener("pointerenter", show);
    group.addEventListener("focus", show);
    group.addEventListener("pointerleave", () => { tooltip.hidden = true; });
    group.addEventListener("blur", () => { tooltip.hidden = true; });
    svg.append(group);
  }
  container.replaceChildren(el("div", { class: "chart-wrap sky-wrap" }, svg, tooltip));
}

/** Säulen für die Signalstärke je Satellit, mit Schwellen 25/35 dB-Hz. */
export function snrBars(container, satellites) {
  const sats = satellites.filter((s) => isNum(s.snr) || s.used).slice(0, 32);
  const width = Math.max(320, container.clientWidth || 600);
  const height = 200;
  const pad = { top: 12, right: 8, bottom: 34, left: 36 };
  const max = 50;
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, class: "chart-svg",
    role: "img", "aria-label": "Signalstärke je Satellit" });
  const pw = width - pad.left - pad.right;
  const ph = height - pad.top - pad.bottom;
  const Y = (v) => pad.top + ph - (Math.min(v, max) / max) * ph;
  for (const v of [0, 25, 35, 50]) {
    svg.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: Y(v), y2: Y(v),
      class: v === 25 || v === 35 ? "chart-zero" : "chart-grid" }));
    const label = svgEl("text", { x: pad.left - 6, y: Y(v) + 4, "text-anchor": "end", class: "chart-label" });
    label.textContent = v;
    svg.append(label);
  }
  if (!sats.length) {
    const text = svgEl("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "chart-empty" });
    text.textContent = "Keine Satellitendaten";
    svg.append(text);
  }
  const slot = pw / Math.max(sats.length, 1);
  const barW = Math.max(4, Math.min(22, slot - 4));
  const tooltip = el("div", { class: "tooltip", hidden: true });
  sats.forEach((sat, i) => {
    const x = pad.left + i * slot + (slot - barW) / 2;
    const v = isNum(sat.snr) ? sat.snr : 0;
    const rect = svgEl("rect", { x, y: Y(v), width: barW, height: Math.max(0, Y(0) - Y(v)), rx: 3,
      class: `snr-bar${sat.used ? " used" : ""}` });
    rect.addEventListener("pointerenter", () => {
      tooltip.replaceChildren(el("div", { class: "tt-time", text: `${sat.system} · PRN ${sat.prn}` }),
        el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Signal" }),
          el("b", { text: isNum(sat.snr) ? `${sat.snr} dB-Hz` : "–" })),
        el("div", { class: "tt-row" }, el("span", { class: "tt-label", text: "Status" }),
          el("b", { text: sat.used ? "genutzt" : "nicht genutzt" })));
      tooltip.style.left = `${((x + barW / 2) / width) * 100}%`;
      tooltip.style.top = "10px";
      tooltip.style.transform = (x / width) > 0.6 ? "translate(calc(-100% - 8px), 0)" : "translate(8px, 0)";
      tooltip.hidden = false;
    });
    rect.addEventListener("pointerleave", () => { tooltip.hidden = true; });
    svg.append(rect);
    const label = svgEl("text", { x: x + barW / 2, y: height - pad.bottom + 14, "text-anchor": "middle",
      class: "chart-label" });
    label.textContent = sat.prn ?? "";
    svg.append(label);
  });
  container.replaceChildren(el("div", { class: "chart-wrap" }, svg, tooltip));
}

export { css };

// Nachkommastellen passend zur Rasterweite, damit Achsenbeschriftungen eindeutig bleiben.
export function stepDecimals(step) {
  return Math.min(6, Math.max(0, -Math.floor(Math.log10(step) + 1e-9)));
}
