// GNSS-Störungen, GPS-Sperre (GPS-Seite) und echter Holdover-Test (Seite Uhrqualität) – 1.5.
// Daten: GET /api/gnss und /api/holdover; Aktionen per POST (admin). Alles als Text im DOM (el/textContent).
import { el, fmtNumber, isNum, rich, apiPost } from "../util.js";
import { card, kv, info, badge, emptyNote, toast } from "../ui.js";
import { lineChart, stepDecimals } from "../charts.js";

const STAGE = { ok: ["unauffällig", "good"], hinweis: ["Hinweis", "info"], warnung: ["Warnung", "warn"], stoerung: ["Störung", "crit"] };
const MODE = { off: "aus – es wird nicht geprüft", report: "nur melden (Standard)", lock: "automatisch sperren" };
const STAGE_TEXT = {
  ok: "Kein Befund: Signale, Zeit und Position des GPS sehen normal aus.",
  hinweis: "Ein schwaches Signal schlägt an – oft harmlos (Schnee, Flugzeug, Fahrzeug vor dem Fenster). Nur im Protokoll.",
  warnung: "Zwei schwache Signale zugleich – das GPS genau beobachten.",
  stoerung: "Starker Befund: Das GPS liefert vermutlich falsche Zeit oder Position (Spoofing). chrony sollte sich auf die Netzquellen stützen.",
};

function ms(value, digits) {
  if (!isNum(value)) return "–";
  const abs = Math.abs(value);
  return `${fmtNumber(value, digits ?? (abs >= 100 ? 0 : abs >= 1 ? 1 : 2))} ms`;
}
function when(unix) {
  if (!isNum(unix)) return "–";
  return new Date(unix * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function span(seconds) {
  if (!isNum(seconds)) return "–";
  const minutes = Math.max(0, Math.round(seconds / 60));
  if (minutes < 60) return `${Math.max(1, minutes)} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

async function post(ctx, url, body, button, done, key) {
  if (button) button.disabled = true;
  try {
    await apiPost(url, body);
    if (done) toast(done);
    ctx.invalidate(key);
    ctx.rerender();
  } catch (error) {
    toast(error.message, "crit");
    if (button) button.disabled = false;
  }
}

// --- GPS-Seite: Störungserkennung + Sperre ----------------------------------------------
function signalValue(signal, quiet) {
  if (!signal) return "–";
  if (signal.active) {
    return el("span", {}, badge(signal.strength === "strong" ? "starker Befund" : "schwacher Befund",
      signal.strength === "strong" ? "crit" : "warn"), ` ${signal.text || ""}`);
  }
  return quiet;
}

export function gnssCard(ctx) {
  const g = ctx.data("gnss", "/api/gnss", 10);
  const head = { help: "gnss_guard", sub: "Jamming und Spoofing erkennen – nur aus gpsd und chrony, auf den Empfänger wird nichts geschrieben." };
  if (!g) return card("Störungserkennung", head, emptyNote("Wird geladen …"));
  if (!g.enabled) {
    return card("Störungserkennung", { ...head, badge: badge("aus", "muted") },
      emptyNote(g.gps_enable ? "Die Störungserkennung ist ausgeschaltet (Einstellungen → GPS → Störungserkennung)."
        : "GPS ist ausgeschaltet."),
      lockBlock(ctx, g));
  }
  const [label, tone] = STAGE[g.stage] || STAGE.ok;
  const sig = Object.fromEntries((g.signals || []).map((s) => [s.key, s]));
  const t = g.time || {};
  const pos = g.position || {};
  const cn0 = g.cn0 || {};
  const refs = t.ref_kind === "nts" ? `${fmtNumber(t.references, 0)} NTS-Quellen` : t.ref_kind === "ntp" ? `${fmtNumber(t.references, 0)} Netzquellen` : null;
  const timeQuiet = !refs ? "kein Abgleich – weniger als 2 NTS- bzw. 3 Netzquellen erreichbar"
    : `${ms(t.deviation_ms)} gegen ${refs} (Schwelle ± ${ms(t.threshold_ms)}${t.baseline ? "" : ", Grundlinie wird noch gelernt"})`;
  const posQuiet = pos.learned ? `${fmtNumber(pos.deviation_m, 0)} m von der gelernten Position (Schwelle 100 m)`
    : "wird noch gelernt (einige Minuten 3D-Fix)";
  const cn0Quiet = isNum(cn0.drop_db) ? `Änderung in 60 s: ${fmtNumber(-cn0.drop_db, 1)} dB (${fmtNumber(cn0.satellites, 0)} Satelliten)`
    : "noch zu wenige starke Satelliten zum Vergleichen";
  return card("Störungserkennung", { ...head, badge: badge(label, tone) },
    el("div", { class: "verdict", "data-tone": tone },
      el("span", { class: "verdict-label" }, `Stufe: ${label}`, " ", info("gnss_stage", "Stufe")),
      el("p", { text: STAGE_TEXT[g.stage] || "" }),
      g.since && g.stage !== "ok" ? el("p", { class: "card-sub", text: `seit ${when(g.since)}` }) : null),
    kv([
      ["Signaleinbruch (C/N0)", signalValue(sig.cn0_drop, cn0Quiet), "gnss_cn0_drop"],
      ["Gleichmäßige Signale", signalValue(sig.uniform, isNum(cn0.stdev_db) ? `unauffällig (Streuung ${fmtNumber(cn0.stdev_db, 1)} dB)` : "unauffällig"), "gnss_uniform"],
      ["Urteil von chrony", signalValue(sig.falseticker, "kein Falseticker"), "gnss_falseticker"],
      ["Zeit gegen Netzquellen", signalValue(sig.time, timeQuiet), "gnss_time"],
      ["Position", signalValue(sig.position, posQuiet), "gnss_position"],
      ["Verhalten bei Störung", MODE[g.mode] || g.mode, "gnss_mode"],
    ]),
    lockBlock(ctx, g));
}

function lockBlock(ctx, g) {
  const lock = g.lock || {};
  const rows = [];
  if (lock.locked) {
    const how = lock.manual ? "von Hand" : "automatisch";
    const release = lock.manual ? "bis zur Freigabe von Hand"
      : lock.auto_release ? (isNum(lock.release_in_s) ? `Freigabe in ${span(lock.release_in_s)} ohne Befund` : "Freigabe nach 30 min ohne Befund")
        : `nach ${fmtNumber(lock.max_auto_releases, 0)} automatischen Freigaben nur noch von Hand`;
    rows.push(["GPS-Sperre", el("span", {}, badge("gesperrt", "warn"), ` ${how} seit ${when(lock.since)} (${(lock.targets || []).join(", ")}) – ${release}`), "gnss_lock"]);
    if (lock.reason) rows.push(["Grund", lock.reason, "gnss_lock_reason"]);
  } else {
    rows.push(["GPS-Sperre", el("span", {}, badge("frei", "good"), " chrony darf das GPS auswählen"), "gnss_lock"]);
  }
  const buttons = [];
  const disabled = ctx.readonly ? true : null;
  if (lock.locked) {
    const unlock = el("button", { type: "button", class: "button", text: "Sperre aufheben", disabled });
    unlock.addEventListener("click", () => {
      if (!window.confirm("GPS-Sperre aufheben? chrony darf das GPS dann wieder als Zeitquelle wählen.")) return;
      post(ctx, "/api/gnss", { action: "unlock" }, unlock, "GPS wieder freigegeben", "gnss");
    });
    buttons.push(unlock);
  } else if (g.gps_enable) {
    const lockBtn = el("button", { type: "button", class: "button", text: "GPS jetzt sperren", disabled });
    lockBtn.addEventListener("click", () => {
      // Ohne andere auswählbare Quelle liefe die Uhr frei – dann ausdrücklich bestätigen (force).
      const alone = lock.other_sources === 0;
      const question = alone
        ? "Keine andere auswählbare Zeitquelle! Ohne GPS läuft die Uhr frei (Holdover) und driftet mit der Zeit weg. Trotzdem sperren?"
        : "GPS sperren? chrony nutzt es dann nicht mehr (selectopts noselect) und hält sich an die Netzquellen – bis du es wieder freigibst.";
      if (!window.confirm(question)) return;
      post(ctx, "/api/gnss", alone ? { action: "lock", force: true } : { action: "lock" }, lockBtn, "GPS gesperrt", "gnss");
    });
    buttons.push(lockBtn);
  }
  if (g.enabled) {
    const relearn = el("button", { type: "button", class: "button", text: "Neu lernen", disabled,
      title: "Referenzposition und gewohnten Zeitabstand vergessen – nach einem Umzug des Empfängers" });
    relearn.addEventListener("click", () => {
      if (!window.confirm("Position und Zeitabstand neu lernen? Nötig, wenn du den Empfänger umgestellt hast.")) return;
      post(ctx, "/api/gnss", { action: "relearn" }, relearn, "Wird neu gelernt", "gnss");
    });
    buttons.push(relearn, info("gnss_relearn", "Neu lernen"));
  }
  buttons.push(el("a", { href: "#/einstellungen?s=gps", text: "Verhalten in den Einstellungen" }));
  return el("div", {}, kv(rows), el("div", { class: "button-row" }, buttons));
}

// --- Uhrqualität: Holdover-Test --------------------------------------------------------------
const OUTCOME = { done: ["fertig", "good"], limit: ["Grenze erreicht", "warn"], restart: ["chronyd neu gestartet", "warn"], aborted: ["abgebrochen", "muted"], invalid: ["ungültig", "warn"] };
// Nur GPS/PPS abgewählt: das Netz regelt weiter – kein Holdover-Ergebnis „die Uhr hält …“.
const outcomeLabel = (r) => (OUTCOME[r.outcome] || OUTCOME.aborted)[0] + (r.include_network === false ? " (nur ohne GPS/PPS)" : "");
const HOURS = [1, 2, 6, 12, 24];

function startForm(ctx, data) {
  const ui = ctx.uiState;
  const d = data.defaults || {};
  if (!ui.hoHours) ui.hoHours = d.hours || 2;
  if (ui.hoNetwork === undefined) ui.hoNetwork = true;
  if (!ui.hoLimit) ui.hoLimit = d.limit_ms || 10;
  const hours = el("select", { "aria-label": "Dauer des Tests" },
    HOURS.map((h) => el("option", { value: String(h), selected: h === Number(ui.hoHours) ? true : null, text: `${h} h` })));
  hours.addEventListener("change", () => { ui.hoHours = Number(hours.value); });
  const network = el("input", { type: "checkbox", role: "switch", checked: ui.hoNetwork ? true : null });
  network.addEventListener("change", () => { ui.hoNetwork = network.checked; });
  const networkSwitch = el("span", { class: "diag-switch" },
    el("label", { class: "switch" }, network, el("span", { class: "switch-track", "aria-hidden": "true" }),
      el("span", { class: "switch-text", text: "auch Netzquellen abschalten (echter Holdover)" })),
    info("holdover_network", "Netzquellen"));
  const limit = el("input", { type: "number", min: String(d.limit_min_ms || 1), max: String(d.limit_max_ms || 1000), step: "1",
    value: String(ui.hoLimit), "aria-label": "Abbruchgrenze in Millisekunden", style: "width: 6em" });
  limit.addEventListener("input", () => { ui.hoLimit = Number(limit.value); });
  const check = data.check || {};
  const start = el("button", { type: "button", class: "button primary", text: "Holdover-Test starten",
    disabled: ctx.readonly || check.ok === false ? true : null });
  start.addEventListener("click", () => {
    const what = network.checked ? "GPS/PPS und alle Netzquellen" : "GPS/PPS";
    if (!window.confirm(`${what} für ${hours.value} h abwählen? chrony stellt die Uhr in der Zeit ${network.checked ? "nicht nach" : "nur noch nach dem Netz"} – `
      + "Clients bekommen eine ungenauere Zeit. Der Test endet automatisch und bricht bei Überschreiten der Grenze ab.")) return;
    post(ctx, "/api/holdover", { action: "start", hours: Number(hours.value), include_network: network.checked, limit_ms: Number(limit.value) },
      start, "Holdover-Test läuft", "holdover");
  });
  return el("div", {},
    el("div", { class: "toolbar" },
      el("label", { class: "inline-field" }, el("span", {}, "Dauer ", info("holdover_hours", "Dauer")), hours),
      el("label", { class: "inline-field" }, el("span", {}, "Abbruch ab (ms) ", info("holdover_limit", "Abbruchgrenze")), limit)),
    networkSwitch,
    check.ok === false ? el("div", { class: "callout", "data-tone": "warn", text: check.reason }) : null,
    kv([["Messreferenzen", isNum(check.references) ? `${fmtNumber(check.references, 0)} erreichbare Netzquellen (mindestens ${fmtNumber(d.min_references || 2, 0)})` : "–", "holdover_refs"]]),
    el("p", { class: "card-sub" }, rich("**Achtung:** Während des Tests stellt chrony die Uhr nicht nach – Clients bekommen eine ungenauere Zeit. "
      + "Am besten nachts oder wenn nichts Zeitkritisches läuft.")),
    el("div", { class: "button-row" }, start));
}

function runningBlock(ctx, run) {
  const abort = el("button", { type: "button", class: "button", text: "Test abbrechen", disabled: ctx.readonly ? true : null });
  abort.addEventListener("click", () => {
    if (!window.confirm("Holdover-Test abbrechen? Alle Quellen werden sofort wieder auswählbar.")) return;
    post(ctx, "/api/holdover", { action: "abort" }, abort, "Abgebrochen – Quellen wieder auswählbar", "holdover");
  });
  const host = el("div", { class: "chart-host" });
  const points = run.points || [];
  ctx.afterRender(() => lineChart(host, { height: 170, key: "holdover-run", zeroLine: true, stats: false,
    series: [{ id: "dev", label: "ms", color: "var(--accent)", points: points.map(([t, v]) => [t, v]) }],
    format: (v) => ms(v), axisFormat: (v, step) => `${fmtNumber(v, stepDecimals(step))} ms`,
    ariaLabel: "Zeitfehler während des Holdover-Tests", emptyText: "Erster Messpunkt nach einer Minute" }));
  return el("div", {},
    el("div", { class: "verdict", "data-tone": "warn" },
      el("span", { class: "verdict-label" }, "Test läuft ", info("holdover_progress", "Fortschritt")),
      el("p", { text: `Bisher ${ms(run.deviation_ms)} in ${span(run.elapsed_s)} – noch ${span(run.remaining_s)}.` }),
      el("progress", { max: String((run.hours || 1) * 3600), value: String(run.elapsed_s || 0), "aria-label": "Fortschritt des Tests" })),
    kv([
      ["Zeitfehler bisher", `${ms(run.deviation_ms)} (größter Betrag ${ms(run.max_abs_ms)})`, "holdover_deviation"],
      ["Gangabweichung", isNum(run.drift_ppm) ? `${fmtNumber(run.drift_ppm, 3)} ppm` : "nach einigen Minuten", "holdover_drift"],
      ["Abgeschaltet", `${run.include_network ? "GPS/PPS und Netzquellen" : "nur GPS/PPS"} (${fmtNumber(run.targets, 0)} Quellen)`, "holdover_network"],
      ["Abbruch ab", `± ${ms(run.limit_ms, 0)}`, "holdover_limit"],
      ["Endet", when((run.started || 0) + (run.hours || 0) * 3600), "holdover_hours"],
    ]),
    host,
    el("div", { class: "button-row" }, abort));
}

function resultsBlock(results) {
  if (!results.length) return emptyNote("Noch kein Test gelaufen.");
  const last = results[0];
  const [label, tone] = OUTCOME[last.outcome] || OUTCOME.aborted;
  return el("div", {},
    el("div", { class: "verdict", "data-tone": tone },
      el("span", { class: "verdict-label" }, `Letzter Test (${when(last.started)}) `, badge(outcomeLabel(last) || label, tone), " ", info("holdover_result", "Ergebnis")),
      el("p", { text: last.sentence || "–" }),
      isNum(last.drift_ppm) ? el("p", { class: "card-sub", text: `Gangabweichung ${fmtNumber(last.drift_ppm, 3)} ppm, größter Betrag ${ms(last.max_abs_ms)}` }) : null),
    results.length > 1 ? el("table", { class: "mini-table" },
      el("thead", {}, el("tr", {}, el("th", { text: "Start" }), el("th", { text: "Ergebnis" }), el("th", { class: "num", text: "Dauer" }),
        el("th", { class: "num" }, "Zeitfehler ", info("holdover_deviation", "Zeitfehler")))),
      el("tbody", {}, results.map((r) => el("tr", {},
        el("td", { text: when(r.started) }),
        el("td", { text: outcomeLabel(r) }),
        el("td", { class: "num", text: span(r.duration_s) }),
        el("td", { class: "num", text: ms(r.deviation_ms) }))))) : null);
}

export function holdoverCard(ctx) {
  const running = ctx.uiState.hoRunning;
  const data = ctx.data("holdover", "/api/holdover", running ? 15 : 60);
  const head = { help: "holdover", sub: "Wie lange hält die Uhr ohne Zeitquelle? Gemessen statt geschätzt: chrony misst die Netzquellen weiter, nutzt sie aber nicht." };
  if (!data) return card("Holdover-Test", head, emptyNote("Wird geladen …"));
  ctx.uiState.hoRunning = Boolean(data.active);
  const results = data.results || [];
  // Kopfzeile: nur echte Holdover-Läufe (alle Quellen abgewählt) mit Messergebnis (fertig oder Grenze).
  const last = results.find((r) => r.include_network !== false && (r.outcome === "done" || r.outcome === "limit"));
  const headBadge = data.active ? badge("läuft", "warn") : last ? badge(`${ms(Math.abs(last.deviation_ms))} in ${span(last.duration_s)}`, "muted") : null;
  return card("Holdover-Test", { ...head, badge: headBadge },
    data.active && data.run ? runningBlock(ctx, data.run) : startForm(ctx, data),
    el("h3", { class: "mini-head" }, "Ergebnisse ", info("holdover_result", "Ergebnisse")),
    resultsBlock(results));
}
