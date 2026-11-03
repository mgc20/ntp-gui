import { el, fmtSeconds, fmtDuration, fmtNumber, isNum, rich, apiPost } from "../util.js";
import { card, tile, kv, info, badge, emptyNote, toast } from "../ui.js";
import { lineChart, skyPlot, snrBars } from "../charts.js";
import { stateBadge, reasonCell } from "./sources.js";
import { axisSeconds } from "./overview.js";
import { hardwareData, pickReceiver, accuracyLadder, PPS_PATH } from "./hardware.js";
import { receptionCard, roleCard, antennaCard } from "./gpsquality.js";
import { gnssCard } from "./gnss.js";

const WINDOWS = [[0, "gesamter Verlauf"], [3600, "letzte Stunde"], [21600, "letzte 6 h"], [86400, "letzte 24 h"]];

// Karte „Dein Empfänger“ aus dem Hardware-Check – auch bei ausgeschaltetem GPS.
function receiverCard(ctx, report) {
  const link = el("a", { href: "#/hardware", class: "insight-action", text: "Details → Hardware-Check" });
  if (!report) return card("Dein Empfänger", { help: "gps_receiver_card" }, emptyNote("Hardware wird geprüft …"));
  const receiver = pickReceiver(report);
  if (!receiver) {
    return card("Dein Empfänger", { help: "gps_receiver_card" },
      el("div", { class: "verdict", "data-tone": "info" }, el("p", { text: "Kein GPS-Empfänger gefunden – weder am Host noch im Container." })),
      emptyNote("USB-Sticks erscheinen als `/dev/ttyACM0` oder `/dev/ttyUSB0`, GPS-HATs am Raspberry Pi als `/dev/ttyAMA0` bzw. `/dev/serial0`."),
      link);
  }
  const path = PPS_PATH[receiver.pps_path] || PPS_PATH.unknown;
  return card("Dein Empfänger", { help: "gps_receiver_card", badge: receiver.configured ? null : badge("nicht eingetragen", "muted", "Erster gefundener Empfänger – in den Einstellungen ist ein anderes Gerät eingetragen") },
    el("div", { class: "verdict", "data-tone": receiver.tone || "info" },
      el("span", { class: "verdict-label" }, receiver.product || receiver.dev || "Empfänger", " ", info("hw_verdict", "Urteil")),
      el("p", { text: receiver.verdict || "–" })),
    el("div", { class: "hw-item-grid" },
      kv([
        ["Schnittstelle", `${receiver.interface || "–"}${receiver.dev ? ` · ${receiver.dev}` : ""}`, "hw_interface"],
        ["PPS-Weg", path.label, "hw_pps_path"],
        ["Genauigkeit", receiver.accuracy || "–", "hw_accuracy"],
      ]),
      accuracyLadder(receiver, report)),
    link);
}

// PPS-Kachel: Einstellung + tatsächliche Impulse aus dem Hardware-Check.
function ppsTile(gps, cfg, report) {
  const sources = report?.pps || [];
  const wanted = cfg.gps_pps_device || gps.pps_missing || gps.pps;
  const source = sources.find((p) => p.configured) || sources.find((p) => wanted && p.dev === wanted) || null;
  const receiver = pickReceiver(report);
  if (source) {
    if (source.state === "live") {
      return tile({ label: "PPS", help: "hw_pps_state", value: "live", unit: isNum(source.rate_hz) ? `${fmtNumber(source.rate_hz, 1)} Hz` : "",
        tone: source.configured ? "good" : "warn", note: source.configured ? source.dev : `${source.dev} – nicht eingetragen` });
    }
    return tile({ label: "PPS", help: "hw_pps_state", value: "keine Impulse", tone: source.configured ? "crit" : "warn",
      note: `${source.dev} · ${source.state === "never" ? "noch nie ein Impuls" : "kein Fix? Kabel/Pin?"}` });
  }
  if (gps.pps_missing) return tile({ label: "PPS", help: "pps", value: "fehlt", tone: "crit", note: `${gps.pps_missing} fehlt im Container` });
  if (gps.pps) {
    const seen = report?.gps?.gpsd_pps?.seen;
    return tile({ label: "PPS", help: "hw_gpsd_pps", value: seen === false ? "keine Impulse" : seen ? "live" : "aktiv",
      tone: seen === false ? "warn" : "good", note: gps.pps });
  }
  return tile({ label: "PPS", help: "pps", value: "kein PPS", tone: "muted",
    note: receiver ? (PPS_PATH[receiver.pps_path] || PPS_PATH.unknown).label : "USB-Empfänger: ms-Genauigkeit" });
}

function disabledView(ctx) {
  return [
    receiverCard(ctx, hardwareData(ctx)),
    card("GPS ist nicht eingeschaltet", { help: "gps" },
      el("p", {}, rich("Ein GPS-Empfänger macht diesen Server zum **Stratum-1-Server** mit eigener Referenz – unabhängig vom Internet.")),
      el("div", { class: "compare" },
        el("div", { class: "compare-col" }, el("h3", { text: "USB-GPS ohne PPS (z. B. VK-162)" }),
          el("ul", {},
            el("li", {}, rich("Genauigkeit nach Kalibrierung **1–10 ms** – nicht genauer als die PTB über eine gute Festnetzleitung.")),
            el("li", {}, rich("**Lohnt sich bei**: Mobilfunk/LTE, Starlink, Satellit (dort hat NTP 10–50 ms Fehler), häufigen Internetausfällen, isolierten Netzen ohne Internet.")),
            el("li", {}, rich("**Und**: als unabhängige Kontrolle gegen falsche Internetzeit.")))),
        el("div", { class: "compare-col" }, el("h3", { text: "GPS mit PPS (HAT, GPIO, seriell)" }),
          el("ul", {},
            el("li", {}, rich("Genauigkeit **unter 1 µs** – tausendfach besser.")),
            el("li", {}, rich("Voraussetzung für einen sinnvollen **PTP-Grandmaster**.")),
            el("li", {}, rich("Am Raspberry Pi über GPIO (`dtoverlay=pps-gpio`), Beispiel: Jeff Geerlings time-pi."))))),
      el("p", {}, el("a", { href: "#/einstellungen?s=gps", class: "button", text: "GPS in den Einstellungen einschalten" }))),
  ];
}

// --- Automatische Kalibrierung (GET /api/gps/autocal, POST /api/gps/autocal/rollback) ---
const AUTOCAL_TONE = { off: "muted", suggest: "info", auto: "good" };
const AUTOCAL_ACTION = { none: ["keine Änderung", "muted"], suggest: ["Vorschlag", "warn"], apply: ["wird geändert", "good"] };

function fmtWhen(unix) {
  if (!isNum(unix)) return "–";
  return new Date(unix * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

// Nach einer Offset-Änderung wartet die Messung erst die Einschwingzeit ab – der
// Zeitpunkt liegt dann noch in der Zukunft. Maßgeblich ist die Uhr des Servers.
function measuringLabel(ctx, since) {
  const now = isNum(ctx.status?.system?.time) ? ctx.status.system.time : Date.now() / 1000;
  return isNum(since) && since > now ? "Messung zählt ab" : "Messung zählt seit";
}

function fmtMs(value, signed = false) {
  return isNum(value) ? `${signed && value > 0 ? "+" : ""}${fmtNumber(value, 1)} ms` : "–";
}

function autocalReference(decision) {
  const ref = decision?.reference;
  if (!ref || !isNum(ref.current_network)) return "–";
  const inWindow = isNum(ref.window_median) ? ` · im Messzeitraum im Mittel ${fmtNumber(ref.window_median, 1)}` : "";
  return `${fmtNumber(ref.current_network)} genutzt, davon ${fmtNumber(ref.current_nts || 0)} mit NTS${inWindow}`;
}

async function rollbackAutocal(ctx, button, change) {
  const text = `Offset von ${change.new_offset} s auf ${change.old_offset} s zurücksetzen? chrony startet dafür kurz neu.`;
  if (!window.confirm(text)) return;
  button.disabled = true;
  try {
    const result = await apiPost("/api/gps/autocal/rollback", { steps: 1 });
    toast(result.reload_triggered ? `Zurückgenommen – Offset ${result.restored_offset} s, Zeitdienste starten neu`
      : `Zurückgenommen – Offset ${result.restored_offset} s`);
    ctx.watchReload();
    ctx.invalidate("autocal");
    ctx.invalidate("calibration");
    ctx.refresh();
  } catch (error) {
    toast(error.message, "crit");
    button.disabled = false;
  }
}

function autocalChanges(ctx, auto) {
  const changes = auto.changes || [];
  if (!changes.length) return emptyNote("Bisher keine automatischen Änderungen.");
  const rollback = auto.rollback || {};
  return el("table", { class: "mini-table" },
    el("thead", {}, el("tr", {},
      el("th", { text: "Zeit" }),
      el("th", { text: "Art" }),
      el("th", {}, "Offset ", info("gps_offset", "Offset")),
      el("th", {}, "Grund ", info("autocal_changes", "Änderungen")),
      el("th", {}, info("autocal_rollback", "Rückgängig")))),
    el("tbody", {}, changes.map((change) => {
      let action = null;
      if (change.kind === "auto" && change.rolled_back) {
        action = badge("zurückgenommen", "muted", `am ${fmtWhen(change.rolled_back)}`);
      } else if (change.kind === "auto" && rollback.possible && rollback.change_id === change.id) {
        const button = el("button", { type: "button", class: "button", text: "Rückgängig",
          disabled: ctx.readonly || auto.readonly ? true : null,
          title: `Offset wieder auf ${change.old_offset} s setzen` });
        button.addEventListener("click", () => rollbackAutocal(ctx, button, change));
        action = button;
      } else if (change.kind === "auto" && rollback.change_id === change.id && rollback.reason) {
        action = badge("nicht möglich", "warn", rollback.reason);
      }
      return el("tr", {},
        el("td", { text: fmtWhen(change.t) }),
        el("td", { text: change.kind === "rollback" ? "Rücknahme" : "automatisch" }),
        el("td", { text: `${change.old_offset} s → ${change.new_offset} s` }),
        el("td", { text: change.reason || "–" }),
        el("td", {}, action));
    })));
}

// Offset von Hand geändert (z. B. „zurücksetzen“), während die automatische Kalibrierung läuft:
// sagen, was sie als Nächstes tut, und den Kalibrier-Vorschlag mit einem Klick anbieten.
function autocalPlan(auto, applyOffer) {
  if (!auto.plan) return null;
  const manual = auto.manual_change;
  // Bei einer Störungssperre nicht zum Übernehmen einladen – erst Antenne und Umgebung prüfen.
  if (!manual || auto.decision?.guard_hold) return el("p", { text: auto.plan });
  const parts = [el("p", { text: auto.plan })];
  if (applyOffer) parts.push(el("div", { class: "cal-apply" }, applyOffer()));
  return el("div", { class: "callout" }, parts);
}

function autocalSection(ctx, applyOffer = null) {
  const auto = ctx.data("autocal", "/api/gps/autocal", 60);
  const head = el("h3", { class: "mini-head" }, "Automatische Kalibrierung ", info("autocal_mode", "Automatische Kalibrierung"));
  if (!auto) return el("div", { class: "autocal" }, head, emptyNote("Wird geladen …"));
  const decision = auto.decision || {};
  const [actionLabel, actionTone] = AUTOCAL_ACTION[decision.action] || AUTOCAL_ACTION.none;
  const settingsLink = el("a", { href: "#/einstellungen?s=gps", text: "Modus in den Einstellungen ändern" });
  const parts = [
    head,
    el("div", { class: "cal-status", "data-tone": AUTOCAL_TONE[auto.mode] || "muted" },
      badge(`Modus: ${auto.mode_label || auto.mode}`, AUTOCAL_TONE[auto.mode] || "muted"),
      el("span", { text: auto.mode_text || "" })),
    el("p", {}, settingsLink),
  ];
  if (auto.mode !== "off") {
    const phase = auto.phase || null;
    const held = Boolean(decision.guard_hold);
    parts.push(kv([
      phase ? ["Phase", el("span", {}, badge(phase.label, phase.tone || "muted"), " ", phase.text || ""), "autocal_phase"] : null,
      ["Entscheidung", el("span", {}, badge(actionLabel, actionTone), " ", decision.reason || "–"), "autocal_decision"],
      isNum(decision.bias_ms) ? ["Gemessene Abweichung", `${fmtMs(decision.bias_ms, true)} (Streuung ± ${fmtMs(decision.spread_ms)})`, "autocal_bias"] : null,
      isNum(decision.threshold_ms) ? ["Schwelle", fmtMs(decision.threshold_ms), "autocal_threshold"] : null,
      decision.reference ? ["Vergleichsquellen", autocalReference(decision), "autocal_reference"] : null,
      [measuringLabel(ctx, decision.measuring_since), fmtWhen(decision.measuring_since), "autocal_window"],
      auto.mode === "auto" && isNum(auto.next_change_at) ? ["Nächster Schritt", fmtWhen(auto.next_change_at), "autocal_next"] : null,
      auto.mode === "auto" ? ["Größter Schritt", fmtMs(auto.max_step_ms), "autocal_step"] : null,
    ]));
    const plan = autocalPlan(auto, applyOffer);
    if (plan) parts.push(plan);
    if (held) {
      parts.push(el("div", { class: "callout", "data-tone": "crit" },
        el("p", { text: "Gesperrt wegen GNSS-Störung – erst Antenne und Umgebung prüfen (Karte „GNSS-Störungen“). Den gemessenen Versatz bitte nicht von Hand übernehmen: Während einer Störung könnte er von einem Spoofer stammen." })));
    } else if (decision.action === "suggest" && isNum(decision.new_offset)) {
      const delay = isNum(decision.new_delay) ? `, Delay ${decision.new_delay} s` : "";
      parts.push(emptyNote(`Vorschlag: Offset ${decision.new_offset} s${delay} – übernimm ihn oben mit „Vorschlag übernehmen“, wenn der Messzeitraum passt.`));
    }
  }
  parts.push(el("h3", { class: "mini-head" }, "Letzte automatische Änderungen ", info("autocal_changes", "Änderungen")));
  parts.push(autocalChanges(ctx, auto));
  return el("div", { class: "autocal" }, parts);
}

function calibrationCard(ctx, gpsSource) {
  const cfg = ctx.status.config || {};
  const windowSeconds = ctx.uiState.calWindow ?? 0;
  const cal = ctx.data("calibration", `/api/gps/calibration?window=${windowSeconds}`, 15);
  // Für die Rückfrage beim Übernehmen: Meldet die Störungserkennung gerade etwas?
  const gnssNow = ctx.data("gnss", "/api/gnss", 10);
  const autoNow = ctx.data("autocal", "/api/gps/autocal", 60);
  const body = [];
  let applyOffer = null;   // „Vorschlag übernehmen“ auch im Hinweis der automatischen Kalibrierung

  body.push(el("p", {}, rich("Ein USB-Empfänger meldet die Zeit mit einer festen **Verspätung** (NMEA-Zeile + serielle Übertragung + USB-Puffer, typisch 20–150 ms). Der Assistent vergleicht das GPS laufend mit den genutzten Netzwerkquellen und schlägt den passenden Korrekturwert vor."), " ", info("gps_offset", "Warum ein Offset?")));
  body.push(el("div", { class: "toolbar" }, el("span", { class: "toolbar-label", text: "Messzeitraum" }),
    el("div", { class: "range-group" }, WINDOWS.map(([seconds, label]) => el("button", {
      type: "button", class: `range${windowSeconds === seconds ? " is-active" : ""}`, text: label,
      onclick: () => { ctx.uiState.calWindow = seconds; ctx.invalidate("calibration"); ctx.rerender(); },
    })))));

  if (!cal) {
    body.push(emptyNote("Messung wird geladen …"));
    body.push(autocalSection(ctx));
    return card("GPS kalibrieren", { help: "gps_offset", id: "kalibrierung" }, body);
  }
  const tone = { ready: "good", calibrated: "good", preliminary: "warn", insufficient: "muted" }[cal.status] || "muted";
  body.push(el("div", { class: "cal-status", "data-tone": tone },
    badge({ ready: "Vorschlag bereit", calibrated: "bereits kalibriert", preliminary: "vorläufig", insufficient: "zu wenig Daten" }[cal.status] || cal.status, tone),
    el("span", { text: cal.message })));
  if (isNum(cal.since_offset_change)) {
    body.push(emptyNote(`Gemessen wird nur seit der letzten Offset-Änderung (ab ${fmtWhen(cal.since_offset_change)}) – ältere Werte passen nicht mehr zum eingestellten Offset.`));
  }

  if (isNum(cal.bias)) {
    // Modus „gemessen“ (ohne PPS): chrony nutzt die gemessene Schranke bzw. den Standard, nicht
    // gps_delay – dann zeigt „aktuell“ diesen Wert und „Übernehmen“ setzt nur den Offset.
    const delayManaged = cal.delay_managed === true;
    const delayChanged = !delayManaged && Math.abs(cal.suggested_delay - cal.current_delay) > 1e-9;
    const delaySourceLabel = cal.delay_source === "measured" ? "gemessen" : "Standard";
    const offsetChanged = Math.abs(cal.suggested_offset - cal.current_offset) > 0.0005;
    body.push(el("div", { class: "cal-grid" },
      kv([
        ["Gemessene Verspätung", fmtSeconds(cal.bias, 3, true), "gps_offset"],
        ["Streuung", `± ${fmtSeconds(cal.spread)}`, "jitter"],
        ["Datenbasis", `${fmtNumber(cal.samples)} Messungen über ${fmtDuration(cal.duration_seconds)}`, "gps_samples"],
      ]),
      el("table", { class: "cal-table" },
        el("thead", {}, el("tr", {}, el("th", { text: "" }), el("th", { text: "aktuell" }), el("th", { text: "Vorschlag" }))),
        el("tbody", {},
          el("tr", {}, el("th", {}, "Offset ", info("gps_offset", "Offset")), el("td", { text: `${cal.current_offset} s` }),
            el("td", { class: offsetChanged ? "changed" : "", text: `${cal.suggested_offset} s` })),
          el("tr", {}, el("th", {}, "Delay ", info("gps_delay", "Delay")),
            el("td", { text: delayManaged ? `${cal.current_delay} s (${delaySourceLabel})` : `${cal.current_delay} s` }),
            el("td", { class: delayChanged ? "changed" : "", text: delayManaged ? "automatisch gemessen" : `${cal.suggested_delay} s` }))))));

    const role = el("select", { id: "cal-role", "aria-label": "Rolle des GPS" },
      [["auto", "automatisch – chrony entscheidet"], ["prefer", "bevorzugen – GPS ist erste Wahl"]].map(([value, label]) =>
        el("option", { value, selected: (cfg.gps_select || "auto") === value ? true : null, text: label })));
    const applyButton = (label) => {
      const button = el("button", { type: "button", class: "button primary", text: label,
        disabled: ctx.readonly || cal.status === "insufficient" ? true : null,
        title: `Offset ${cal.suggested_offset} s übernehmen` });
      button.addEventListener("click", async () => {
        const hold = autoNow?.decision?.guard_hold;
        const disturbed = gnssNow && (["warnung", "stoerung"].includes(gnssNow.stage) || gnssNow.lock?.locked);
        if ((hold || disturbed) && !window.confirm("Die GNSS-Störungserkennung meldet gerade eine Warnung oder Störung"
          + (hold ? " (die automatische Kalibrierung ist deshalb gesperrt)" : "") + ". Ein Versatz während einer möglichen "
          + "Störung kann von einem Spoofer stammen. Prüfe zuerst Antenne und Umgebung. Trotzdem übernehmen?")) return;
        button.disabled = true;
        try {
          const changes = { gps_offset: cal.suggested_offset, gps_select: role.value };
          if (!delayManaged) changes.gps_delay = cal.suggested_delay;
          const result = await apiPost("/api/settings", { changes });
          toast(result.reload_triggered ? "Übernommen – Zeitdienste starten neu" : (result.reload_note || "Gespeichert"));
          ctx.watchReload();
          ctx.invalidate("calibration");
          ctx.invalidate("autocal");
        } catch (error) {
          toast(error.message, "crit");
          button.disabled = false;
        }
      });
      return button;
    };
    const apply = applyButton("Vorschlag übernehmen");
    if (cal.status === "ready" && offsetChanged) {
      applyOffer = () => applyButton(`Vorschlag übernehmen (Offset ${cal.suggested_offset} s)`);
    }
    body.push(el("div", { class: "cal-apply" },
      el("label", { class: "inline-field" }, el("span", {}, "Rolle ", info("gps_role", "Rolle")), role), apply));
    if (delayManaged) {
      body.push(emptyNote("Den Delay (die Fehlerschranke) misst ntp-gui im Modus „gemessen“ selbst – „Übernehmen“ setzt nur Offset und Rolle. Delay von Hand: Einstellungen → GPS → „Fehlerschranke ohne PPS: von Hand“."));
    }
    body.push(emptyNote("Nach dem Übernehmen startet chrony neu (die Messhistorie bleibt erhalten). Die Abweichung im Diagramm sollte danach um 0 schwanken. Neu kalibrieren nach einem Wechsel von Empfänger, USB-Port oder Firmware."));

    const host = el("div", { class: "chart-host" });
    body.push(host);
    ctx.afterRender(() => lineChart(host, {
      series: [
        { id: "diff", label: "GPS − Netzwerk", color: "var(--accent)", points: (cal.series || []).map((p) => [p.t, p.d]) },
        { id: "median", label: "Median", color: "var(--ink-muted)", points: (cal.series || []).map((p) => [p.t, cal.bias]) },
      ],
      format: (v) => fmtSeconds(v, 3, true), axisFormat: axisSeconds, height: 200, zeroLine: true,
    }));
  }
  // Dieselbe PPS-Prüfung wie im Server (gpsquality.has_pps): Gerät vorhanden oder „PPS über gpsd“.
  const bound = cfg.gps_bound || {};
  const fallback = !bound.pps && (cfg.gps_bound_mode || "measured") === "measured" && cfg.gps_select !== "prefer";
  const delayNow = isNum(bound.delay) ? bound.delay : cfg.gps_delay;
  if (gpsSource && gpsSource.select_state === "large_distance" && fallback) {
    body.push(el("div", { class: "callout" }, rich("**Darum steht das GPS auf „Unsicherheit zu groß“:** Das ist so gewollt. "
      + "Ohne PPS ist das GPS die **Rückfallebene** mit ehrlicher Fehlerschranke (siehe „Rolle des GPS“): Solange die "
      + "Netzwerkquellen genauer sind, nimmt chrony sie; wird das Internet schlecht oder fällt aus, übernimmt das GPS von selbst."),
      " ", info("gpsq_role", "Rolle des GPS")));
  } else if (gpsSource && gpsSource.select_state === "large_distance") {
    body.push(el("div", { class: "callout" }, rich("**Darum steht das GPS auf „Unsicherheit zu groß“:** Mit Delay "
      + `${delayNow} s nimmt chrony an, die GPS-Zeit könne bis zu ${fmtSeconds(delayNow / 2)} daneben liegen – die Netzwerkquellen sind viel genauer. `
      + "Der vorgeschlagene kleinere Delay macht das GPS konkurrenzfähig.")));
  }
  body.push(autocalSection(ctx, applyOffer));
  return card("GPS kalibrieren", { help: "gps_offset", id: "kalibrierung" }, body);
}

// Delay, den chrony wirklich nutzt: im Modus „gemessen“ die gemessene Schranke bzw. der
// vorsichtige Standard (nicht die Einstellung gps_delay), sonst die Einstellung.
function delayCell(cfg) {
  const bound = cfg.gps_bound || {};
  if (bound.managed && isNum(bound.delay)) {
    return `${bound.delay} s (${bound.source === "measured" ? "gemessen" : "vorsichtiger Standard"}, ± ${fmtSeconds(bound.delay / 2)})`;
  }
  return `${cfg.gps_delay} s (eingestellt)`;
}

export function render(ctx) {
  const { status, history } = ctx;
  const gps = status.gps || {};
  if (!gps.enabled) return disabledView(ctx);
  const cfg = status.config || {};
  const gpsSource = (status.sources || []).find((s) => s.mode === "#" && s.name === cfg.gps_refid);
  const report = hardwareData(ctx);

  const tiles = el("div", { class: "stat-row" },
    tile({ label: "Fix", help: "fix", value: gps.running ? (gps.mode_label || "–") : "gpsd offline",
      tone: gps.has_fix ? "good" : gps.running ? "warn" : "crit", note: gps.device || "" }),
    tile({ label: "Satelliten", help: "satellites", value: `${gps.satellites_used ?? 0} / ${gps.satellites_seen ?? 0}`,
      tone: (gps.satellites_used || 0) >= 4 ? "good" : "warn", note: "genutzt / sichtbar" }),
    tile({ label: "HDOP", help: "dop", value: isNum(gps.hdop) ? gps.hdop.toFixed(2) : "–",
      tone: isNum(gps.hdop) ? (gps.hdop < 2 ? "good" : gps.hdop < 5 ? "warn" : "crit") : "muted",
      note: `PDOP ${isNum(gps.pdop) ? gps.pdop.toFixed(2) : "–"} · VDOP ${isNum(gps.vdop) ? gps.vdop.toFixed(2) : "–"}` }),
    tile({ label: "Signal", help: "snr", value: isNum(gps.snr_avg) ? `${gps.snr_avg}` : "–", unit: "dB-Hz",
      tone: isNum(gps.snr_avg) ? (gps.snr_avg >= 35 ? "good" : gps.snr_avg >= 25 ? "warn" : "crit") : "muted",
      note: `Ø der genutzten · max. ${gps.snr_max ?? "–"}` }),
    ppsTile(gps, cfg, report),
    tile({ label: "In chrony", help: "gps_role", value: gpsSource ? ({ "*": "ausgewählt", "+": "kombiniert", "-": "beobachtet", x: "Falseticker", "?": "keine Daten" }[gpsSource.state] || gpsSource.state) : "–",
      tone: gpsSource ? ({ "*": "good", "+": "good", "-": "muted", x: "crit", "?": "crit" }[gpsSource.state] || "muted") : "muted",
      note: gpsSource ? `Offset ${fmtSeconds(gpsSource.offset, 3, true)}` : "Refclock nicht aktiv" }));

  const chronyCard = card("GPS in chrony", { help: "gps_value", sub: "Wie chrony das GPS gerade bewertet." },
    gpsSource ? kv([
      ["Zustand", stateBadge(gpsSource), "gps_source_state"],
      ["Grund", reasonCell(gpsSource), "gps_select_reason"],
      ["Offset der letzten Messung", fmtSeconds(gpsSource.offset, 3, true), "source_offset"],
      ["Jitter", isNum(gpsSource.std_dev) ? fmtSeconds(gpsSource.std_dev) : "–", "jitter"],
      ["Eingestellter Offset", `${cfg.gps_offset} s`, "gps_offset"],
      ["Delay in chrony", delayCell(cfg), "gps_delay"],
      ["Rolle", { auto: "automatisch", prefer: "bevorzugt", noselect: "nur beobachten" }[cfg.gps_select] || cfg.gps_select, "gps_role"],
    ]) : emptyNote("Die GPS-Zeile fehlt in chrony – meist weil das Gerät beim Start nicht vorhanden war. Der Hinweis oben auf der Übersicht nennt den Grund."));

  const sky = el("div", { class: "chart-host" });
  const bars = el("div", { class: "chart-host" });
  const sats = gps.satellites || [];
  ctx.afterRender(() => { skyPlot(sky, sats); snrBars(bars, sats); });

  const systems = Object.entries(gps.systems || {});
  const satCard = card("Satelliten", { help: "skyplot", sub: "Ausgefüllt = für den Fix genutzt. Fehlen ganze Himmelsrichtungen, verdeckt dort etwas die Sicht." },
    el("div", { class: "sky-layout" }, sky,
      el("div", {}, el("h3", { class: "mini-head" }, "Signalstärke je Satellit ", info("snr", "Signalstärke")), bars,
        systems.length ? el("table", { class: "mini-table" },
          el("thead", {}, el("tr", {}, el("th", {}, "System ", info("gnss", "Systeme")), el("th", { class: "num", text: "sichtbar" }), el("th", { class: "num", text: "genutzt" }))),
          el("tbody", {}, systems.map(([name, v]) => el("tr", {}, el("td", { text: name }), el("td", { class: "num", text: v.seen }), el("td", { class: "num", text: v.used }))))) : null)));

  const satHost = el("div", { class: "chart-host" });
  ctx.afterRender(() => lineChart(satHost, {
    series: [
      { id: "gps-used", label: "genutzt", points: history.map((s) => [s.t, s.gps?.used ?? null]) },
      { id: "gps-seen", label: "sichtbar", points: history.map((s) => [s.t, s.gps?.seen ?? null]) },
    ], format: (v) => fmtNumber(v, 0), axisFormat: (v, step) => fmtNumber(v, step < 1 ? 1 : 0), height: 180, min: 0, minSpan: 12,
    range: ctx.range, end: ctx.status.system?.time, ariaLabel: "Satelliten genutzt und sichtbar",
  }));

  const facts = card("Empfänger", { help: "gps" }, kv([
    ["Gerät", `${gps.device || "–"}${gps.driver ? ` (${gps.driver})` : ""}`, "gps_device"],
    ["Baudrate", gps.baud ?? "automatisch", "gps_baud"],
    ["gpsd", gps.gpsd_release || "–", "gpsd_version"],
    ["GPS-Zeit", gps.time || "–", "gps_time"],
    ["Zeitfehler laut Empfänger", isNum(gps.time_error) ? fmtSeconds(gps.time_error) : "–", "time_error"],
    ["Schaltsekunden (GPS−UTC)", gps.leapseconds ?? "–", "gps_leapseconds"],
    isNum(gps.lat) ? ["Position", `${gps.lat.toFixed(5)}, ${gps.lon.toFixed(5)}${isNum(gps.alt) ? ` · ${gps.alt.toFixed(0)} m` : ""}`, "gps_position"] : null,
  ]));

  return [
    receiverCard(ctx, report),
    tiles,
    el("div", { class: "grid-2" }, receptionCard(ctx), roleCard(ctx)),
    gnssCard(ctx),
    el("div", { class: "grid-2" }, chronyCard, facts),
    calibrationCard(ctx, gpsSource),
    satCard,
    antennaCard(ctx),
    card("Satelliten im Verlauf", { help: "satellites", sub: "Bricht die Zahl regelmäßig ein, verdeckt zu bestimmten Zeiten etwas die Sicht." }, satHost),
    card("Was bringt GPS hier?", { class: "explain", help: "gps_value" }, el("p", {}, rich(
      "Ohne PPS bleibt die Genauigkeit im Millisekundenbereich – so gut wie die PTB über eine gute Festnetzleitung. "
      + "Der Wert liegt in der **Unabhängigkeit**: Die Zeit stimmt auch ohne Internet, sie ist gegen falsche Internetzeit abgesichert, "
      + "und bei **Mobilfunk/Starlink** ist sie deutlich besser als NTP über diese Leitung. Mehr Genauigkeit bringt erst ein **PPS-Signal**.")),
    ),
  ];
}
