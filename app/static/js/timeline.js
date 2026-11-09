// „Heute“-Zeitleiste (1.6, T7) für die Übersicht: Zustandsband der letzten 24 h mit Ereignismarkern, Dialog
// „so sah es um 03:12 aus“ und Tagesbericht für gestern. Daten: /api/timeline (vorverdichtet, timeline.py) und
// /api/timeline/at (nächstgelegener Messpunkt). Alles bleibt lokal; Satelliten nur als Anzahl.
//
// Bedienung des Bands: Klick/Tipp auf eine Stelle öffnet den Dialog. Mit der Tastatur ist das Band ein
// Schieberegler (role="slider"): Pfeiltasten 5 Minuten, Bild auf/ab eine Stunde, Pos1/Ende, Enter öffnet den
// Dialog. Die Marker darüber sind eigene Knöpfe (Tab), Enter öffnet den Dialog zu ihrer Zeit.
import { el, apiGet, fmtSeconds, fmtNumber, fmtZoned, serverZone, isNum } from "./util.js";
import { card, kv, badge, emptyState, errorState, loadingOr } from "./ui.js";
import { clusterMarkers, markerButtons, markerFilterControl, visibleMarkers, markerGlyph } from "./charts.js";
import { t as tr } from "./i18n.js";

const STATE_NAMES = { g: "good", w: "warn", c: "crit", h: "holdover", n: "none" };
const STATE_TONE = { good: "good", warn: "warn", crit: "crit", holdover: "info", none: "muted" };
const LEGEND = ["good", "warn", "crit", "holdover", "none"];
const URL = "/api/timeline";

function zoneOf(ctx) {
  return serverZone(ctx.status?.system) ? ctx.status.system : null;
}

function clock(unix, zone) {
  return fmtZoned(unix, zone, { hour: "2-digit", minute: "2-digit" }, null, "toLocaleTimeString");
}

function stateLabel(state) {
  return tr(`pages.timeline.state.${STATE_NAMES[state] ? STATE_NAMES[state] : state}`);
}

// --- Dialog „so sah es um … aus“ ------------------------------------------------------------------------
let momentDialog = null;

function closeMoment() {
  if (momentDialog?.open) momentDialog.close();
}

function momentBody(result, zone) {
  const sample = result?.sample;
  const rows = [];
  if (!sample) rows.push(emptyState(tr("pages.timeline.moment.none")));
  else {
    const sats = sample.satellites;
    rows.push(kv([
      [tr("pages.timeline.moment.state"), badge(stateLabel(sample.state), STATE_TONE[sample.state] || "muted"), "timeline"],
      [tr("pages.timeline.moment.source"), sample.source || tr("pages.timeline.moment.no_source"), "overview_best_source"],
      [tr("pages.timeline.moment.offset"), fmtSeconds(sample.offset, 3, true), "system_offset"],
      [tr("pages.timeline.moment.bound"), isNum(sample.bound) ? `± ${fmtSeconds(sample.bound)}` : "–", "uncertainty"],
      sats ? [tr("pages.timeline.moment.satellites"), tr("pages.timeline.moment.satellites_value",
        { used: fmtNumber(sats.used), seen: fmtNumber(sats.seen) }), "satellites"] : null,
      [tr("pages.timeline.moment.point"), fmtZoned(sample.t, zone, { hour: "2-digit", minute: "2-digit", second: "2-digit" }, null,
        "toLocaleTimeString"), "timeline"],
    ]));
  }
  const list = Array.isArray(result?.events) ? result.events : [];
  if (list.length) {
    rows.push(el("h3", { class: "mini-head", text: tr("pages.timeline.moment.events") }),
      el("ul", { class: "moment-events" }, list.map((event) => el("li", { "data-level": event.level },
        el("span", { class: "chart-event-glyph", "data-group": event.group, "aria-hidden": "true", text: markerGlyph(event.group) }),
        el("time", { class: "muted", text: clock(event.t, zone) }), " ", el("span", { text: event.title })))));
  }
  return rows;
}

/** Dialog öffnen und den nächstgelegenen Messpunkt laden. focusKey: Element, das danach den Fokus zurückbekommt. */
export async function openMoment(at, zone, focusKey) {
  momentDialog?.remove();
  const content = el("div", { class: "moment-body", "aria-live": "polite" }, emptyState(tr("pages.timeline.moment.loading")));
  const title = tr("pages.timeline.moment.title", { time: clock(at, zone) });
  const dialog = el("dialog", { class: "preview-dialog moment-dialog", "aria-labelledby": "moment-title" },
    el("div", { class: "preview-head" },
      el("h2", { id: "moment-title", text: title }),
      el("button", { type: "button", class: "icon-button", "aria-label": tr("pages.timeline.moment.close"), text: "✕",
        onclick: () => dialog.close() })),
    content,
    el("div", { class: "preview-actions" },
      el("button", { type: "button", class: "button", text: tr("pages.timeline.moment.close"), onclick: () => dialog.close() })));
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => {
    dialog.remove();
    if (momentDialog === dialog) momentDialog = null;
    // Die Seite baut alle paar Sekunden neu: das auslösende Element über seinen Schlüssel wiederfinden.
    const back = focusKey ? document.querySelector(`[data-focus-key="${CSS.escape(focusKey)}"]`) : null;
    if (back) back.focus({ preventScroll: true });
  });
  momentDialog = dialog;
  document.body.append(dialog);
  dialog.showModal();
  try {
    const result = await apiGet(`/api/timeline/at?t=${Math.round(at)}`);
    content.replaceChildren(...momentBody(result, zone));
  } catch (error) {
    content.replaceChildren(errorState(error, tr("pages.timeline.moment.what"), false));
  }
}

// --- Zustandsband -------------------------------------------------------------------------------------
function bandRuns(states) {
  const out = [];
  for (let i = 0; i < states.length; i += 1) {
    const last = out[out.length - 1];
    if (last && last.code === states[i]) last.to = i + 1;
    else out.push({ code: states[i], from: i, to: i + 1 });
  }
  return out;
}

function band(ctx, data) {
  const zone = zoneOf(ctx);
  const states = String(data.states || "");
  const count = states.length;
  const bucket = data.bucket || 300;
  const start = data.start;
  const ui = ctx.uiState;
  const timeAt = (i) => start + i * bucket;
  const describe = (i) => `${clock(timeAt(i), zone)}–${clock(timeAt(i + 1), zone)}: ${stateLabel(states[i] || "n")}`;
  if (!isNum(ui.timelineIndex) || ui.timelineIndex >= count) ui.timelineIndex = count - 1;

  const track = el("div", { class: "timeline-track", role: "slider", tabindex: "0", "data-focus-key": "timeline-band",
    "aria-label": tr("pages.timeline.band_label"), "aria-describedby": "timeline-hint",
    "aria-valuemin": "0", "aria-valuemax": String(count - 1) });
  for (const run of bandRuns(states)) {
    const seg = el("span", { class: "timeline-seg", "data-state": STATE_NAMES[run.code] || "none" });
    seg.style.left = `${(run.from / count) * 100}%`;
    seg.style.width = `${((run.to - run.from) / count) * 100}%`;
    track.append(seg);
  }
  const cursor = el("span", { class: "timeline-cursor", "aria-hidden": "true" });
  const hover = el("div", { class: "tooltip timeline-tip", hidden: true, "aria-hidden": "true" });
  track.append(cursor);
  const setIndex = (i) => {
    const index = Math.max(0, Math.min(count - 1, i));
    ui.timelineIndex = index;
    track.setAttribute("aria-valuenow", String(index));
    track.setAttribute("aria-valuetext", describe(index));
    cursor.style.left = `${((index + 0.5) / count) * 100}%`;
    return index;
  };
  setIndex(ui.timelineIndex);
  const open = (i) => openMoment(timeAt(i) + bucket / 2, zone, "timeline-band");
  const indexFrom = (event) => {
    const rect = track.getBoundingClientRect();
    return Math.floor(Math.min(0.9999, Math.max(0, (event.clientX - rect.left) / rect.width)) * count);
  };
  track.addEventListener("pointermove", (event) => {
    const i = indexFrom(event);
    hover.textContent = describe(i);
    const left = ((i + 0.5) / count) * 100;
    hover.style.left = `${left}%`;
    hover.style.transform = left > 60 ? "translate(calc(-100% - 10px), 0)" : "translate(10px, 0)";
    hover.hidden = false;
  });
  track.addEventListener("pointerleave", () => { hover.hidden = true; });
  track.addEventListener("click", (event) => { const i = setIndex(indexFrom(event)); open(i); });
  track.addEventListener("keydown", (event) => {
    const i = ui.timelineIndex;
    const moves = { ArrowLeft: i - 1, ArrowDown: i - 1, ArrowRight: i + 1, ArrowUp: i + 1, PageUp: i + 12, PageDown: i - 12,
      Home: 0, End: count - 1 };
    if (event.key in moves) { event.preventDefault(); setIndex(moves[event.key]); } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault(); open(i);
    }
  });

  // Marker über dem Band: eigene Knöpfe; Enter/Klick öffnet den Dialog zu ihrer Zeit.
  const marks = visibleMarkers(data.markers, start, start + count * bucket);
  const width = 1000;
  const X = (t) => ((t - start) / (count * bucket)) * width;
  const host = el("div", { class: "timeline-wrap" });
  const lines = el("div", { class: "timeline-lines", "aria-hidden": "true" });
  host.append(lines, track, hover);
  // Pixelabstand erst nach dem Einhängen bekannt: die Knöpfe nach dem Zeichnen setzen.
  ctx.afterRender(() => {
    const scale = (host.clientWidth || width) / width;
    const placed = clusterMarkers(marks, (t) => X(t) * scale).map((c) => ({ ...c, x: c.x / scale }));
    for (const cluster of placed) {
      const line = el("span", { class: "timeline-line", "data-level": cluster.level });
      line.style.left = `${(cluster.x / width) * 100}%`;
      lines.append(line);
    }
    markerButtons(host, { clusters: placed, width, top: 0, tipTop: 100, key: "timeline",
      stamp: (t) => clock(t, zone),
      onActivate: (cluster) => openMoment(cluster.t, zone, `marker:timeline:${cluster.t}`) });
  });
  const hours = [0, 6, 12, 18, 24].map((h) => {
    const label = el("span", { class: "timeline-hour", text: h === 24 ? tr("pages.timeline.now") : clock(start + h * 3600, zone) });
    label.style.left = `${(h / 24) * 100}%`;
    return label;
  });
  return el("div", { class: "timeline" }, host, el("div", { class: "timeline-axis", "aria-hidden": "true" }, hours),
    el("span", { class: "sr-only", id: "timeline-hint", text: tr("pages.timeline.band_hint") }));
}

function legend() {
  return el("ul", { class: "timeline-legend", "aria-label": tr("pages.timeline.legend_label") },
    LEGEND.map((state) => el("li", {}, el("span", { class: "timeline-swatch", "data-state": state, "aria-hidden": "true" }),
      tr(`pages.timeline.state.${state}`))));
}

/** Karte „Heute – letzte 24 Stunden“ (Zustandsband, Marker, Filter nach Art). */
export function timelineCard(ctx) {
  const data = ctx.data("timeline", URL, 60);
  const body = data && typeof data.states === "string" && data.states.length
    ? [band(ctx, data), legend(), markerFilterControl(() => ctx.rerender())]
    : [loadingOr(ctx, "timeline", URL, tr("pages.timeline.what"))];
  return card(tr("pages.timeline.title"), { help: "timeline", id: "zeitleiste", class: "timeline-card",
    sub: tr("pages.timeline.sub") }, ...body);
}

// --- Tagesbericht ---------------------------------------------------------------------------------------
function pctText(pct) {
  // Abrunden: 99,96 % ist nicht „100 %“ – sonst sähe ein Tag mit kurzem Ausfall wie ein perfekter aus.
  const floored = pct >= 100 ? 100 : Math.floor(pct * 10) / 10;
  return fmtNumber(floored, 1);
}

/** Teile des Satzes „Gestern: 99,8 % synchron, schlechtester Wert ± 1,2 ms, 12 Geräte, …“. */
export function reportParts(report) {
  if (!report || !report.samples) return [];
  const parts = [];
  if (isNum(report.synced_pct)) parts.push(tr("pages.timeline.report.synced", { pct: pctText(report.synced_pct) }));
  if (isNum(report.worst_offset)) parts.push(tr("pages.timeline.report.worst", { value: fmtSeconds(report.worst_offset) }));
  if (isNum(report.devices)) parts.push(tr("pages.timeline.report.devices", { count: report.devices, n: fmtNumber(report.devices) }));
  if (isNum(report.gps_hours)) {
    parts.push(tr("pages.timeline.report.gps", { hours: fmtNumber(report.gps_hours, report.gps_hours < 10 ? 1 : 0) }));
  }
  if (isNum(report.pi_state)) parts.push(tr(`pages.timeline.report.pi_${Math.max(0, Math.min(2, report.pi_state))}`));
  return parts;
}

/** Karte „Tagesbericht“ für gestern (aus derselben Antwort wie das Band). */
export function dailyReportCard(ctx) {
  const data = ctx.data("timeline", URL, 60);
  if (!data) return null;
  const report = data.report;
  const parts = reportParts(report);
  let body;
  if (!parts.length) body = emptyState(tr(report?.pending ? "pages.timeline.report.pending" : "pages.timeline.report.empty"));
  else {
    const covered = isNum(report.covered_s) ? report.covered_s / 3600 : 24;
    body = el("p", { class: "daily-line" },
      el("strong", { text: `${tr("pages.timeline.report.yesterday")}: ` }),
      // Trennzeichen außerhalb der Teile: Nur zwischen den Teilen darf die Zeile umbrechen.
      parts.map((part, i) => [el("span", { class: "daily-part", text: i < parts.length - 1 ? `${part},` : part }),
        i < parts.length - 1 ? " " : null]),
      covered < 23 ? el("span", { class: "muted", text: ` (${tr("pages.timeline.report.partial", { hours: fmtNumber(covered, 1) })})` }) : null);
  }
  return card(tr("pages.timeline.report.title"), { help: "daily_report", id: "tagesbericht", class: "daily-card" }, body);
}
