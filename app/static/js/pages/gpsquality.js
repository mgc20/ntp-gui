// GPS ohne PPS und schwacher Empfang (1.5): Empfangsbewertung, Rolle des GPS mit ehrlicher
// Fehlerschranke und Antennen-Test. Daten: GET /api/gps/quality und /api/gps/antenna.
// Alles landet als Text im DOM (el/textContent) – auch die Namen der Messungen.
import { el, fmtNumber, fmtDate, isNum, rich, apiPost, holdoverNote } from "../util.js";
import { card, kv, infoButton, badge, emptyState, toast } from "../ui.js";

const LEVEL = {
  green: ["gut", "good"], yellow: ["mäßig", "warn"], red: ["zu schwach", "crit"], unknown: ["noch offen", "muted"],
};

function pct(share) { return isNum(share) ? `${fmtNumber(share * 100, 0)} %` : "–"; }
function ms(seconds) {
  if (!isNum(seconds)) return "–";
  const value = seconds * 1000;
  return `${fmtNumber(value, value >= 10 ? 0 : 1, { group: false })} ms`;
}
function when(unix) {
  return fmtDate(unix, { date: "day" });
}

export function qualityData(ctx) {
  return ctx.data("gpsquality", "/api/gps/quality", 30);
}

// --- Empfang (24 h) ------------------------------------------------------------
function stabilityRow(stability) {
  const state = stability?.state || "unbekannt";
  if (state === "unstet") {
    const since = isNum(stability.unstet_since) ? ` seit ${when(stability.unstet_since)}` : "";
    return el("span", {}, badge("unstet", "warn"), ` Fix kam und ging ${fmtNumber(stability.unstet_changes || 0)}-mal${since}`);
  }
  if (state === "stetig") {
    const n = isNum(stability.changes_window) ? stability.changes_window : 0;
    const minutes = isNum(stability.window_s) ? Math.max(1, Math.round(stability.window_s / 60)) : 30;
    const span = minutes === 30 ? "in der letzten halben Stunde" : `in den letzten ${fmtNumber(minutes)} min`;
    return el("span", {}, badge("stetig", "good"), n > 0 ? ` ${fmtNumber(n)} Fix-Wechsel ${span}` : ` kein Fix-Wechsel ${span}`);
  }
  return el("span", {}, badge("unbekannt", "muted"), " noch keine GPS-Werte seit dem Start");
}

export function receptionCard(ctx) {
  const q = qualityData(ctx);
  const head = { help: "gpsq_assessment", sub: "Über die letzten 24 Stunden aus dem gespeicherten Verlauf." };
  if (!q) return card("Empfang", head, emptyState("Bewertung wird geladen …"));
  if (!q.enabled || !q.assessment) return card("Empfang", head, emptyState(q.reason || "Nicht verfügbar."));
  const a = q.assessment;
  const [label, tone] = LEVEL[a.level] || LEVEL.unknown;
  const reasons = a.reasons || [];
  const cnLabel = a.cn0_source === "used_avg" ? "Signal (Ø genutzte)" : "Signal (4 stärkste)";
  return card("Empfang", { ...head, badge: badge(label, tone) },
    el("div", { class: "verdict", "data-tone": tone },
      el("span", { class: "verdict-label" }, "Empfangsbewertung ", infoButton("gpsq_assessment", "Empfangsbewertung")),
      el("p", { text: a.sentence || "–" })),
    reasons.length ? el("ul", { class: "checklist" }, reasons.map((r) => el("li", { "data-state": r.level === "red" ? "fail" : "warn" },
      el("span", { class: "check-icon", "aria-hidden": "true", text: "!" }),
      el("div", {}, el("p", { text: r.text }))))) : null,
    kv([
      ["Fix-Anteil", pct(a.fix_share) + (isNum(a.fix3d_share) ? ` (3D ${pct(a.fix3d_share)})` : ""), "gpsq_fix_share"],
      ["Fix-Wechsel je Stunde", isNum(a.changes_per_hour) ? `${fmtNumber(a.changes_per_hour, 1)} (${fmtNumber(a.changes)} in 24 h)` : "–", "gpsq_changes"],
      [cnLabel, isNum(a.cn0_top4) ? `${fmtNumber(a.cn0_top4, 0)} dB-Hz` : "–", "gpsq_cn0"],
      ["Genutzte Satelliten (Median)", isNum(a.used_median) ? fmtNumber(a.used_median, 0) : "–", "gpsq_used"],
      ["Fix gerade", stabilityRow(q.stability), "gpsq_unstet"],
      ["Datenbasis", isNum(a.covered_seconds) ? `${fmtNumber(a.covered_seconds / 3600, 1)} h Messzeit, ${fmtNumber(a.samples)} Messpunkte` : "–", "gpsq_basis"],
    ]),
    el("p", { class: "card-sub" }, "Tipps für besseren Empfang ", infoButton("gpsq_tips", "Tipps für besseren Empfang")));
}

// --- Rolle des GPS ------------------------------------------------------------------
const ROLE_TONE = { good: "good", info: "info", warn: "warn", muted: "muted" };
const SOURCE_LABEL = {
  measured: "gemessen", default: "vorsichtiger Standard (noch nicht gemessen)", manual: "von Hand", pps: "Einstellungen (mit PPS)",
};

async function resetBound(ctx, button) {
  if (!window.confirm(`Fehlerschranke auf den vorsichtigen Standard (± 100 ms) zurücksetzen? chrony startet dafür kurz neu.${holdoverNote(ctx)}`)) return;
  button.disabled = true;
  try {
    const result = await apiPost("/api/gps/bound", { action: "reset" });
    toast(result.reload_triggered ? "Zurückgesetzt – Zeitdienste starten neu" : "Zurückgesetzt");
    ctx.watchReload?.();
    ctx.invalidate("gpsquality");
    ctx.refresh();
  } catch (error) {
    toast(error.message, "crit");
    button.disabled = false;
  }
}

export function roleCard(ctx) {
  const q = qualityData(ctx);
  const head = { help: "gpsq_role" };
  if (!q || !q.role) return card("Rolle des GPS", head, emptyState(q ? (q.reason || "Nicht verfügbar.") : "Wird geladen …"));
  const role = q.role;
  const bound = q.bound || {};
  const measured = bound.measured || {};
  const tone = ROLE_TONE[role.tone] || "info";
  const rows = [
    ["Rolle", el("span", {}, badge(role.label, tone), role.active === true ? " – gerade genutzt" : role.active === false ? " – gerade nicht genutzt" : ""), "gpsq_role"],
  ];
  if (role.role !== "off" && isNum(role.delay)) {
    rows.push(["Fehlerschranke", `± ${ms(role.delay / 2)} (Delay ${fmtNumber(role.delay, 3, { group: false })} s, Auflösung ${fmtNumber(role.precision, 3, { group: false })} s)`, "gpsq_bound"]);
    rows.push(["Herkunft", SOURCE_LABEL[role.bound_source] || role.bound_source, "gpsq_bound_mode"]);
  }
  if (measured.status === "measured") {
    rows.push(["Gemessene Streuung", `± ${ms(measured.bound)} (95 % innerhalb ± ${ms(measured.p95_abs)}, ${fmtNumber(measured.samples)} Messungen über ${fmtNumber(measured.duration_seconds / 3600, 1)} h)`, "gpsq_spread"]);
  } else if (bound.managed) {
    rows.push(["Gemessene Streuung", "noch zu wenige gemeinsame Messungen mit den Netzquellen", "gpsq_spread"]);
  }
  if (bound.decision?.reason && bound.managed) rows.push(["Letzte Prüfung", `${when(bound.decision.t)} – ${bound.decision.reason}`, "gpsq_bound_check"]);
  const actions = [];
  if (bound.applied && bound.managed) {
    const button = el("button", { type: "button", class: "button", text: "Auf Standard zurücksetzen", disabled: ctx.readonly ? true : null });
    button.addEventListener("click", () => resetBound(ctx, button));
    actions.push(button);
  }
  actions.push(el("a", { href: "#/system/einstellungen?s=gps", text: "Rolle und Fehlerschranke in den Einstellungen" }));
  return card("Rolle des GPS", head,
    el("div", { class: "verdict", "data-tone": tone },
      el("span", { class: "verdict-label" }, role.label, " ", infoButton("gpsq_role", "Rolle")),
      el("p", { text: role.text || "" })),
    (role.warnings || []).map((text) => el("div", { class: "callout", "data-tone": "warn", text })),
    kv(rows),
    el("div", { class: "button-row" }, actions));
}

// --- Antennen-Test ------------------------------------------------------------------
function resultCell(result, key) {
  const value = result?.[key];
  if (!isNum(value)) return "–";
  if (key === "fix_share") return pct(value);
  if (key === "cn0_top4") return `${fmtNumber(value, 0)} dB-Hz`;
  return fmtNumber(value, 0);
}

const COMPARE_ROWS = [
  ["Signal (4 stärkste)", "cn0_top4", "gpsq_cn0"],
  ["Fix-Anteil", "fix_share", "gpsq_fix_share"],
  ["Genutzte Satelliten", "used", "gpsq_used"],
  ["Empfangene Satelliten", "tracked", "gpsq_tracked"],
  ["Davon stark (≥ 30 dB-Hz)", "strong", "gpsq_strong"],
];

function resultName(result) {
  return result ? `${result.label || "ohne Namen"} · ${when(result.started)}` : "–";
}

async function antennaAction(ctx, body, button) {
  if (button) button.disabled = true;
  try {
    await apiPost("/api/gps/antenna", body);
    ctx.invalidate("antenna");
    ctx.rerender();
  } catch (error) {
    toast(error.message, "crit");
    if (button) button.disabled = false;
  }
}

function comparisonTable(ctx, data) {
  const results = data.results || [];
  if (results.length < 2) {
    return emptyState(results.length ? "Eine Messung gespeichert – stell den Empfänger um und miss ein zweites Mal, dann erscheint hier der Vergleich."
      : "Noch keine Messung. Starte die erste, stell den Empfänger um, miss erneut – hier erscheint der Vergleich.");
  }
  const cmp = data.comparison || {};
  const byId = Object.fromEntries(results.map((r) => [r.id, r]));
  const a = byId[cmp.a] || results[1];
  const b = byId[cmp.b] || results[0];
  const pick = (which, current) => {
    const select = el("select", { "aria-label": which === "a" ? "Messung A" : "Messung B" },
      results.map((r) => el("option", { value: String(r.id), selected: r.id === current?.id ? true : null, text: resultName(r) })));
    select.addEventListener("change", () => {
      ctx.uiState.antennaPick = { ...(ctx.uiState.antennaPick || {}), [which]: select.value };
      ctx.invalidate("antenna");
      ctx.rerender();
    });
    return select;
  };
  const delta = cmp.deltas || {};
  return el("div", {},
    el("div", { class: "toolbar antenna-pick" },
      el("label", { class: "inline-field" }, el("span", { text: "Messung A" }), pick("a", a)),
      el("label", { class: "inline-field" }, el("span", { text: "Messung B" }), pick("b", b))),
    el("table", { class: "mini-table" },
      el("thead", {}, el("tr", {}, el("th", { text: "" }), el("th", { text: "A" }), el("th", { text: "B" }),
        el("th", {}, "B − A ", infoButton("gpsq_antenna_compare", "Vergleich")))),
      el("tbody", {}, COMPARE_ROWS.map(([label, key, help]) => el("tr", {},
        el("th", {}, label, " ", infoButton(help, label)),
        el("td", { text: resultCell(a, key) }), el("td", { text: resultCell(b, key) }),
        el("td", { text: isNum(delta[key]) ? (key === "fix_share" ? `${fmtNumber(delta[key] * 100, 0, { signed: true })} %-Pkt.` : fmtNumber(delta[key], 0, { signed: true })) : "–" }))))),
    cmp.verdict ? el("div", { class: "verdict", "data-tone": cmp.better ? "good" : "info" },
      el("span", { class: "verdict-label" }, "Ergebnis ", infoButton("gpsq_antenna_compare", "Ergebnis")), el("p", { text: cmp.verdict })) : null);
}

export function antennaCard(ctx) {
  const pickState = ctx.uiState.antennaPick || {};
  const query = new URLSearchParams();
  if (pickState.a) query.set("a", pickState.a);
  if (pickState.b) query.set("b", pickState.b);
  const running = ctx.uiState.antennaRunning;
  const data = ctx.data("antenna", `/api/gps/antenna${query.size ? `?${query}` : ""}`, running ? 3 : 30);
  const head = { help: "gpsq_antenna", sub: "5 Minuten messen, Empfänger umstellen, erneut messen – der Vergleich zeigt, welcher Platz besser ist. Bleibt auf diesem Gerät, ohne Satellitenwinkel." };
  if (!data) return card("Antennen-Test", head, emptyState("Wird geladen …"));
  const test = data.test || {};
  ctx.uiState.antennaRunning = Boolean(test.running);
  const body = [];
  if (test.running) {
    const live = test.live || {};
    const stop = el("button", { type: "button", class: "button", text: "Abbrechen", disabled: ctx.readonly ? true : null });
    stop.addEventListener("click", () => antennaAction(ctx, { action: "stop" }, stop));
    body.push(el("div", { class: "verdict", "data-tone": "info" },
      el("span", { class: "verdict-label" }, `Messung läuft: ${test.label || "ohne Namen"}`, " ", infoButton("gpsq_antenna", "Antennen-Test")),
      el("p", { text: `${fmtNumber(test.elapsed, 0)} von ${fmtNumber(test.seconds, 0, { group: false })} s · bisher Fix ${pct(live.fix_share)}, Signal ${isNum(live.cn0_top4) ? `${fmtNumber(live.cn0_top4, 0)} dB-Hz` : "–"}, ${isNum(live.used) ? fmtNumber(live.used, 0) : "–"} genutzte Satelliten` }),
      el("progress", { max: String(test.seconds || 300), value: String(test.elapsed || 0), "aria-label": "Fortschritt der Messung" })),
    el("div", { class: "button-row" }, stop));
  } else {
    const label = el("input", { type: "text", maxlength: "40", placeholder: "z. B. Fensterbank", "aria-label": "Name der Messung",
      value: ctx.uiState.antennaLabel || "" });
    label.addEventListener("input", () => { ctx.uiState.antennaLabel = label.value; });
    const start = el("button", { type: "button", class: "button primary", text: "5 Minuten messen",
      disabled: ctx.readonly ? true : null });
    start.addEventListener("click", () => {
      ctx.uiState.antennaRunning = true;
      antennaAction(ctx, { action: "start", label: label.value, seconds: data.default_seconds || 300 }, start);
    });
    body.push(el("div", { class: "toolbar" },
      el("label", { class: "inline-field" }, el("span", {}, "Name ", infoButton("gpsq_antenna_label", "Name der Messung")), label), start));
    if (test.error) body.push(el("div", { class: "callout", text: test.error }));
  }
  body.push(comparisonTable(ctx, data));
  const results = data.results || [];
  if (results.length) {
    body.push(el("h3", { class: "mini-head" }, "Gespeicherte Messungen ", infoButton("gpsq_antenna_list", "Gespeicherte Messungen")));
    body.push(el("table", { class: "mini-table" },
      el("thead", {}, el("tr", {}, el("th", { text: "Messung" }), el("th", { class: "num", text: "Signal" }),
        el("th", { class: "num", text: "Fix" }), el("th", { class: "num", text: "genutzt" }), el("th", { text: "" }))),
      el("tbody", {}, results.map((r) => {
        const del = el("button", { type: "button", class: "button", text: "Löschen", disabled: ctx.readonly ? true : null,
          title: "Diese Messung löschen" });
        del.addEventListener("click", () => antennaAction(ctx, { action: "delete", id: r.id }, del));
        return el("tr", {},
          el("td", { text: `${resultName(r)}${r.complete === false ? " (abgebrochen)" : ""}` }),
          el("td", { class: "num", text: resultCell(r, "cn0_top4") }),
          el("td", { class: "num", text: resultCell(r, "fix_share") }),
          el("td", { class: "num", text: resultCell(r, "used") }),
          el("td", {}, del));
      }))));
  }
  body.push(el("p", { class: "card-sub" }, rich("**Tipp:** zwischen zwei Messungen nur eine Sache ändern (Platz, Kabel, USB-Port)."), " ", infoButton("gpsq_tips", "Tipps")));
  return card("Antennen-Test", head, body);
}
