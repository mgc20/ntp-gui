import { el, fmtSeconds, fmtNs, fmtNumber, fmtFixed, fmtRate, fmtDuration, isNum, sourceLabel } from "../util.js";
import { card, tile, kv, badge, insightList, insightLink, rangeButtons, info, emptyNote, ACTION_LABEL } from "../ui.js";
import { lineChart, sparkline, stepDecimals } from "../charts.js";

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
  return isNum(value) ? `${fmtFixed(value, 3)} ppm` : "–";
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
const SERVICE_ORDER = ["chronyd", "gpsd", "ptp4l", "phc2sys", "dnsfwd", "web"];
const SERVICE_INFO = { chronyd: "chronyd", ptp4l: "ptp_requirements", phc2sys: "phc2sys", dnsfwd: "dns" };

function serviceSince(svc) {
  if (!isNum(svc.since)) return "–";
  const age = Math.max(0, Date.now() / 1000 - svc.since);
  return `seit ${fmtDuration(age)}`;
}

// --- Übersicht: alles auf einen Blick ----------------------------------------
// Aufbau: Statusband (Gesamturteil + Kennzahlen mit Mini-Verlauf + wichtige
// Hinweise), darunter je Teilsystem eine Kachel mit Link zur Detailseite,
// dann die Verläufe und ganz unten die Details der Systemuhr.

const VERDICT_ICON = { good: "✓", warn: "!", crit: "✕", muted: "…" };
const LEVEL_RANK = { crit: 0, warn: 1, info: 2, ok: 3 };
const TONE_RANK = { muted: 0, good: 1, info: 1, warn: 2, crit: 3 };
const LEVEL_ICON = { ok: "✓", info: "i", warn: "!", crit: "✕" };

/**
 * Gesamturteil – auch die Kopfzeile (app.js) nutzt es, damit Statusband und
 * Statuspunkt oben rechts nie Verschiedenes sagen.
 */
export function verdict(status, insights) {
  const t = status.tracking || {};
  const crit = insights.filter((i) => i.level === "crit");
  const warn = insights.filter((i) => i.level === "warn");
  const issues = crit.length + warn.length;
  const more = issues ? `${issues} ${issues === 1 ? "Punkt" : "Punkte"} unten prüfen` : "keine offenen Hinweise";
  const stratum = isNum(t.stratum) && t.stratum > 0 && t.stratum < 16 ? `Stratum ${t.stratum}` : null;
  const count = (n) => `${n} ${n === 1 ? "Hinweis" : "Hinweise"}`;
  if (!status.chrony_running) {
    return { tone: "crit", title: "Zeitdienst antwortet nicht", text: "chronyd läuft nicht – Geräte im LAN bekommen gerade keine Zeit.",
      pill: "chronyd offline", pillShort: "offline" };
  }
  if (crit.length) {
    return { tone: "crit", title: crit.length === 1 ? crit[0].title : `${crit.length} Störungen`, text: more,
      pill: `Störung${stratum ? ` · ${stratum}` : ""}`, pillShort: "Störung" };
  }
  if (!t.synchronised) {
    return t.local_reference
      ? { tone: "warn", title: "Inselbetrieb", text: `Keine Zeitquelle erreichbar – die Uhr läuft frei weiter · ${more}`,
        pill: `Inselbetrieb${stratum ? ` · ${stratum}` : ""}`, pillShort: "Insel" }
      : { tone: "warn", title: "Synchronisiert …", text: `chrony sucht noch eine verlässliche Quelle · ${more}`,
        pill: "Synchronisiert …", pillShort: "sync …" };
  }
  if (warn.length) {
    return { tone: "warn", title: "Synchron – mit Hinweisen", text: more,
      pill: `Synchron · ${count(warn.length)}`, pillShort: stratum || "Synchron" };
  }
  return { tone: "good", title: "Alles in Ordnung", text: "Die Uhr ist synchron, alle Teile laufen.",
    pill: `Synchron${stratum ? ` · ${stratum}` : ""}`, pillShort: stratum || "Synchron" };
}

// Zu welcher Kachel gehört ein Hinweis? So färbt sich die betroffene Kachel mit,
// und die Hinweiszeile nennt den Bereich.
const PANEL_NAME = { clock: "Systemuhr", sources: "Zeitquellen", gps: "GPS", ptp: "PTP", clients: "Clients", services: "Dienste" };
const CLOCK_KEYS = new Set(["chrony_down", "no_clock_control", "island", "syncing", "synced"]);

export function panelOf(item) {
  const key = String(item.key || "");
  if (CLOCK_KEYS.has(key)) return "clock";
  if (key === "dns_loop" || key === "dns_loop_risk") return "sources";
  if (key.startsWith("service_") || key === "storage" || key.startsWith("dns_")) return "services";
  if (key.startsWith("hw_gps") || key.startsWith("gps") || item.action === "gps") return "gps";
  if (key.startsWith("hw_ptp") || key.startsWith("ptp") || item.action === "ptp") return "ptp";
  if (key.startsWith("nts_server") || key === "hw_nts" || item.action === "clients") return "clients";
  if (item.action === "sources" || key === "minsources" || key.startsWith("unreach:") || key.startsWith("nts:")) return "sources";
  return null;
}

// Kurzer Zustand für das Badge der Kachel, wenn ein Hinweis sie einfärbt.
const ISSUE_BADGE = {
  no_clock_control: "nicht geregelt", island: "Inselbetrieb", syncing: "synchronisiert …", chrony_down: "keine Antwort",
  gpsd_down: "gpsd offline", gps_nofix: "kein Fix", gps_falseticker: "Falseticker", hw_gps_usb: "Empfänger fehlt",
  hw_gps_pps: "PPS fehlt", ptp_down: "ptp4l aus", minsources: "zu wenige", storage: "kein Volume",
  nts_server_files: "NTS-Zertifikat",
};

function issuesFor(insights, id) {
  return insights.filter((i) => (i.level === "warn" || i.level === "crit") && panelOf(i) === id)
    .sort((a, b) => LEVEL_RANK[a.level] - LEVEL_RANK[b.level]);
}

function hintRow(ctx, item) {
  const key = String(item.key || item.title);
  const crit = item.level === "crit";
  const openSet = ctx.uiState.overviewHintOpen || (ctx.uiState.overviewHintOpen = new Set());
  const open = crit || openSet.has(key);
  const area = panelOf(item);
  const textId = `hint-text-${key.replace(/[^\w-]/g, "_")}`;
  return el("li", { class: `hint-row${open ? " is-open" : ""}`, "data-level": item.level },
    el("span", { class: "insight-icon", "aria-hidden": "true", text: LEVEL_ICON[item.level] || "i" }),
    el("div", { class: "hint-main" },
      el("div", { class: "hint-title" },
        el("strong", { text: item.title }),
        area ? el("span", { class: "hint-area", text: PANEL_NAME[area] }) : null),
      open ? el("p", { class: "hint-text", id: textId, text: item.text }) : null),
    el("div", { class: "hint-actions" },
      crit ? null : el("button", {
        type: "button", class: "link hint-toggle", "aria-expanded": open ? "true" : "false",
        "aria-controls": open ? textId : null, "data-focus-key": `hint:${key}`,
        "aria-label": `${open ? "Details ausblenden" : "Details anzeigen"}: ${item.title}`,
        onclick: () => { if (open) openSet.delete(key); else openSet.add(key); ctx.rerender(); },
      }, open ? "weniger" : "Details"),
      insightLink(item),
      item.action ? el("a", { href: `#/${ROUTES[item.action] || item.action}`, class: "insight-action",
        text: ACTION_LABEL[item.action] || "Ansehen →" }) : null));
}

function hintsBlock(ctx, insights) {
  // „Synchron mit …“ sagt das Statusband schon – keine eigene Zeile.
  const shown = insights.filter((i) => i.key !== "synced");
  const sorted = [...shown].sort((a, b) => (LEVEL_RANK[a.level] ?? 2) - (LEVEL_RANK[b.level] ?? 2));
  const serious = sorted.filter((i) => i.level === "crit" || i.level === "warn");
  const rest = sorted.filter((i) => i.level !== "crit" && i.level !== "warn");
  const open = Boolean(ctx.uiState.overviewHintsOpen);
  const parts = [];
  if (serious.length) parts.push(el("ul", { class: "hint-list", "aria-label": "Warnungen und Störungen" }, serious.map((i) => hintRow(ctx, i))));
  if (rest.length) {
    const toggle = el("button", {
      type: "button", class: "hint-summary", "aria-expanded": open ? "true" : "false", "aria-controls": "hints-rest",
      "data-focus-key": "hints-toggle",
      onclick: () => { ctx.uiState.overviewHintsOpen = !open; ctx.rerender(); },
    },
    el("span", { class: "hint-summary-icons", "aria-hidden": "true" }, rest.slice(0, 4).map((i) =>
      el("span", { class: "insight-icon", "data-level": i.level, text: LEVEL_ICON[i.level] || "i" }))),
    el("span", { class: "hint-summary-text" },
      el("strong", { text: `${rest.length} ${rest.length === 1 ? "Information" : "Informationen"}` }),
      el("span", { class: "muted", text: ` · ${rest.map((i) => i.title).join(" · ")}` })),
    el("span", { class: "hint-summary-action", text: open ? "ausblenden" : "anzeigen" }));
    parts.push(el("div", { class: "hint-more" }, toggle, info("overview_hints", "Hinweise")));
    if (open) parts.push(el("div", { class: "insights-rest", id: "hints-rest" }, insightList(rest, ROUTES)));
  } else if (serious.length) {
    parts.push(el("div", { class: "hint-more hint-more-quiet" }, info("overview_hints", "Hinweise")));
  }
  return parts.length ? el("div", { class: "hero-hints" }, parts) : null;
}

/** Kachel eines Teilsystems: Zustand, Hauptwert, ein paar Zeilen, Link zur Detailseite. */
function panel({ title, help, tone = "muted", state, value, valueNote, href, linkLabel, body, extra, id, issues = [] }) {
  // Hinweise zu diesem Bereich heben die Farbe auf ihre Stufe und stehen in der Kachel.
  const worst = issues[0];
  if (worst && TONE_RANK[worst.level] > (TONE_RANK[tone] ?? 0)) {
    tone = worst.level;
    state = issues.length === 1 ? (ISSUE_BADGE[worst.key] || "1 Hinweis") : `${issues.length} Hinweise`;
  }
  return el("section", { class: "card panel", "data-tone": tone, id: id || null },
    el("div", { class: "panel-head" },
      el("div", { class: "card-title" }, el("h2", { text: title }), help ? info(help, title) : null),
      state ? badge(state, tone) : null),
    value !== undefined ? el("div", { class: "panel-value" },
      el("span", { class: "panel-number", text: String(value) }),
      valueNote ? el("span", { class: "panel-note", text: valueNote }) : null) : null,
    issues.length ? el("ul", { class: "panel-issues", "aria-label": "Hinweise zu diesem Bereich" }, issues.map((i) =>
      el("li", { class: "panel-issue", "data-level": i.level },
        el("span", { class: "insight-icon", "aria-hidden": "true", text: LEVEL_ICON[i.level] }),
        el("span", { text: i.title })))) : null,
    el("div", { class: "panel-body" }, body),
    extra || null,
    href ? el("a", { class: "panel-link", href, text: `${linkLabel || "Details"} →` }) : null);
}

function meter(used, total, label) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  return el("span", { class: "meter-cell" },
    el("span", { class: "meter", role: "img", "aria-label": label },
      el("span", { class: "meter-fill", style: `width:${Math.round(pct)}%` })),
    el("span", { text: `${used} / ${total}` }));
}

// Schaltsekunden-Liste in einer Zeile: Tage bis zum Ablauf, nur wenn chrony die Datei liest.
function leapText(leap) {
  if (!leap || leap.source === "tz") return leap && leap.source === "tz" ? "über Zeitzone (leapsectz)" : "–";
  if (leap.reason === "disabled") return badge("abgeschaltet", "warn");
  if (!leap.available) return badge("fehlt", "warn");
  if (leap.reason === "hash") return badge("Prüfsumme falsch", "warn");
  if (leap.expired || (isNum(leap.days_left) && leap.days_left < 0)) return badge("abgelaufen", "warn");
  const tone = leap.level === "warn" ? "warn" : "good";
  return badge(`noch ${leap.days_left} Tage`, tone, leap.expires_date ? `gilt bis ${leap.expires_date}` : null);
}

function syncPanel(status, ref, rootDistance, issues, temp) {
  const t = status.tracking || {};
  if (!status.chrony_running) {
    return panel({ title: "Systemuhr", help: "chronyd", tone: "crit", state: "keine Antwort", value: "–",
      valueNote: "chronyd läuft nicht", body: emptyNote("Ohne chronyd verteilt der Server keine Zeit. Das Log auf der Diagnose-Seite nennt meist den Grund."),
      href: "#/diagnose", linkLabel: "Zur Diagnose" });
  }
  const local = t.local_reference && !t.synchronised;
  const tone = t.synchronised ? offsetTone(t.system_time_offset) : "warn";
  return panel({
    title: "Systemuhr", help: "system_offset", tone, issues,
    state: t.synchronised ? "synchron" : local ? "Inselbetrieb" : "synchronisiert …",
    value: fmtSeconds(t.system_time_offset, 3, true), valueNote: "Abweichung jetzt",
    body: kv([
      ["Max. Fehler", rootDistance === null ? "–" : `± ${fmtSeconds(rootDistance)}`, "uncertainty"],
      ["Stratum", t.stratum ?? "–", "stratum"],
      ["Referenz", t.local_reference ? "LOCAL" : (sourceLabel(ref) !== "–" ? sourceLabel(ref) : t.ref_name || "–"), "reference"],
      ["Uhrensteuerung", status.system?.clock_control === false ? "aus (-x)" : status.system?.clock_control ? "aktiv" : "–", "clock_control"],
      isNum(temp) ? ["Temperatur", `${fmtFixed(temp, 1)} °C`, "temp_now"] : null,
      ["Schaltsekunden-Liste", leapText(status.leap), "leap_expiry"],
    ].filter(Boolean)),
    href: "#/quellen", linkLabel: "Zu den Quellen",
  });
}

function sourcesPanel(status, issues) {
  const sources = status.sources || [];
  const used = sources.filter((s) => s.state === "*" || s.state === "+");
  const best = sources.find((s) => s.state === "*");
  const reachable = sources.filter((s) => (s.reach_percent ?? 0) > 0);
  const nts = sources.filter((s) => s.authenticated).length;
  const avgReach = sources.length ? sources.reduce((sum, s) => sum + (s.reach_percent || 0), 0) / sources.length : null;
  const tone = !sources.length ? "warn" : used.length ? (used.length < sources.length && reachable.length < sources.length ? "warn" : "good") : "crit";
  return panel({
    title: "Zeitquellen", help: "state_combined", tone, issues,
    state: !sources.length ? "keine" : used.length ? `${used.length} genutzt` : "keine nutzbar",
    value: `${used.length} / ${sources.length}`, valueNote: "genutzt / eingetragen",
    body: kv([
      ["Ausgewählt", best ? `${sourceLabel(best)} (${fmtSeconds(best.offset, 1, true)})` : "–", "overview_best_source"],
      ["Erreichbar", sources.length ? `${reachable.length} von ${sources.length} · Ø ${fmtNumber(avgReach, 0)} %` : "–", "reach"],
      ["NTS-gesichert", sources.length ? `${nts} von ${sources.length}` : "–", "nts_authenticated"],
    ]),
    href: "#/quellen", linkLabel: "Zeitquellen",
  });
}

function gpsPanel(status, issues) {
  const gps = status.gps || {};
  const tone = gps.has_fix ? "good" : gps.running ? "warn" : "crit";
  const pps = gps.pps_missing ? `fehlt (${gps.pps_missing})` : gps.pps ? gps.pps : "nicht eingerichtet";
  return panel({
    title: "GPS", help: gps.running && !gps.has_fix ? "cold_start" : "fix", tone, issues,
    state: gps.running ? (gps.mode_label || "–") : "gpsd offline",
    value: gps.running ? `${gps.satellites_used ?? 0}` : "–", valueNote: gps.running ? "Satelliten im Fix" : "keine Verbindung zu gpsd",
    body: kv([
      ["Satelliten", meter(gps.satellites_used ?? 0, gps.satellites_seen ?? 0, "genutzt von sichtbar"), "satellites"],
      ["Signal", isNum(gps.snr_avg) ? `${fmtNumber(gps.snr_avg, 1)} dB-Hz` : "–", "snr"],
      ["HDOP", isNum(gps.hdop) ? fmtFixed(gps.hdop, 2) : "–", "dop"],
      ["PPS", pps, "pps"],
    ]),
    href: "#/gps", linkLabel: "Zur GPS-Seite",
  });
}

function ptpPanel(status, issues) {
  const ptp = status.ptp || {};
  const tone = ptp.running ? (ptp.synchronised || ptp.is_grandmaster ? "good" : "warn") : "crit";
  const short = { SLAVE: "Slave", MASTER: "Master", GRAND_MASTER: "Grandmaster", LISTENING: "hört zu",
    UNCALIBRATED: "kalibriert", PASSIVE: "passiv", FAULTY: "Fehler", INITIALIZING: "startet" };
  const role = !ptp.running ? "läuft nicht" : ptp.is_grandmaster ? "Grandmaster"
    : (short[String(ptp.portState || "").toUpperCase()] || ptp.portState || "–");
  return panel({
    title: "PTP", help: "port_state", tone, state: role, issues,
    value: ptp.running && !ptp.is_grandmaster ? fmtNs(ptp.offset_ns) : ptp.running ? "GM" : "–",
    valueNote: ptp.running ? (ptp.is_grandmaster ? "gibt die Zeit vor" : "Offset zum Master") : "ptp4l antwortet nicht",
    body: kv([
      ["Port-Zustand", ptp.port_state_label || ptp.portState || "–", "port_state"],
      ["Offset", fmtNs(ptp.offset_ns), "offset_from_master"],
      ["Laufzeit", fmtNs(ptp.meanPathDelay), "mean_path_delay"],
      ["Interface", ptp.interface || ptp.ptp_interface || "–", "ptp_interface"],
    ]),
    href: "#/ptp", linkLabel: "Zur PTP-Seite",
  });
}

/** Nicht genutzte Module (GPS, PTP aus): eine schmale Zeile statt leerer Kacheln. */
function unusedStrip(status) {
  const off = [];
  if (!(status.gps || {}).enabled) off.push({ name: "GPS", help: "gps", href: "#/gps", pitch: "macht den Server zur Stratum-1-Quelle, unabhängig vom Internet" });
  if (!(status.ptp || {}).enabled) off.push({ name: "PTP", help: "ptp", href: "#/ptp", pitch: "verteilt die Zeit im LAN auf Mikrosekunden genau" });
  if (!off.length) return null;
  return el("div", { class: "unused-strip", role: "note" },
    el("span", { class: "unused-label", text: "Nicht genutzt" }),
    off.map((m) => el("span", { class: "unused-item" },
      badge("aus", "muted"), el("strong", { text: m.name }), info(m.help, m.name),
      el("span", { class: "muted unused-pitch", text: ` – ${m.pitch}` }),
      el("a", { href: m.href, text: "mehr →", "aria-label": `${m.name}: mehr erfahren und einrichten` }))));
}

function clientsPanel(ctx, lastRate, rate, issues, spanOpts) {
  const { status } = ctx;
  const count = status.client_count ?? 0;
  const mon = ctx.data("clientoffsets", "/api/clients/offsets", 15);
  let worst = null;
  for (const [ip, entry] of Object.entries((mon && mon.clients) || {})) {
    if (entry && entry.measurable && isNum(entry.ewma) && (!worst || Math.abs(entry.ewma) > Math.abs(worst.ewma))) {
      worst = { ip: entry.name || entry.hostname || ip, ewma: entry.ewma };
    }
  }
  const served = (status.serverstats || {}).ntp_packets_received;
  return panel({
    title: "Clients", help: "served_rate", tone: count ? "good" : "muted", state: count ? "aktiv" : "noch keine", issues,
    value: fmtNumber(count), valueNote: count === 1 ? "Gerät fragt nach der Zeit" : "Geräte fragen nach der Zeit",
    body: kv([
      ["Anfragen/min", fmtRate(lastRate), "served_rate"],
      ["Anfragen gesamt", fmtNumber(served), "client_packets"],
      ["Größte Client-Abweichung", worst ? `${fmtSeconds(worst.ewma, 1, true)} · ${worst.ip}` : "–", "client_offset"],
    ]),
    extra: rate.some((p) => isNum(p[1])) ? el("div", { class: "panel-spark" },
      el("span", { class: "panel-spark-label", text: "Anfragen/min im gewählten Zeitraum" }), sparkline(rate, { min: 0, ...spanOpts })) : null,
    href: "#/clients", linkLabel: "Zu den Clients",
  });
}

// DNS-Modus und Benachrichtigungen: zwei Zeilen unter der Dienstliste.
function opsRows(status) {
  const dns = status.dns || {};
  const dnsState = { ok: ["ok", "good"], fallback: ["Rückfall", "warn"], failing: ["gestört", "crit"], down: ["läuft nicht", "crit"] };
  const ds = dnsState[dns.state];
  const dnsValue = !dns.mode || dns.mode === "system" ? "System-DNS"
    : el("span", {}, `${dns.mode_label || dns.mode} `, ds ? badge(ds[0], ds[1]) : null);
  const n = status.notify || {};
  const notifyValue = !n.channels ? "kein Kanal"
    : !n.enabled ? badge("alle Kanäle aus", "muted")
      : n.failing ? el("span", {}, `${n.enabled} aktiv `, badge(`${n.failing} mit Fehler`, "warn"))
        : el("span", {}, `${n.enabled} aktiv `, badge("zugestellt", "good"));
  return kv([
    ["DNS für ntp-gui", dnsValue, "dns_modes"],
    ["Benachrichtigungen", el("a", { href: "#/benachrichtigungen" }, notifyValue), "notify"],
  ]);
}

function servicesPanel(services, issues, status = {}) {
  const names = Object.keys(services || {});
  names.sort((a, b) => {
    const ia = SERVICE_ORDER.indexOf(a); const ib = SERVICE_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  // Ohne Supervisor gibt es keine Dienstliste – dann keine leere Kachel.
  if (!names.length) return null;
  const count = (state) => names.filter((n) => services[n].state === state).length;
  const running = count("running");
  const failed = count("failed");
  const restarting = count("restarting");
  const off = count("stopped");
  const unclear = names.length - running - failed - restarting - off;
  const tone = failed ? "crit" : restarting || unclear ? "warn" : "good";
  const list = el("ul", { class: "svc-list" }, names.map((name) => {
    const svc = services[name] || {};
    const [label, stTone] = SERVICE_STATE[svc.state] || ["unklar", "warn"];
    const restarts = svc.restarts ?? 0;
    const full = svc.label || name;
    return el("li", { class: "svc", "data-tone": stTone, title: svc.state === "stopped" ? full : `${full} · ${serviceSince(svc)}` },
      el("span", { class: "svc-dot", "aria-hidden": "true" }),
      el("span", { class: "svc-name" }, el("span", { text: SERVICE_SHORT[name] || full }),
        SERVICE_INFO[name] ? info(SERVICE_INFO[name], svc.label || name) : null),
      restarts ? el("span", { class: "svc-restarts", text: `${restarts}× neu` }) : null,
      badge(label, stTone),
      svc.message && svc.state !== "running" ? el("span", { class: "svc-message", text: svc.message }) : null);
  }));
  return panel({
    title: "Dienste", help: "services", tone, issues,
    state: failed ? `${failed} ausgefallen` : restarting ? "Neustart läuft" : unclear ? `${unclear} unklar` : "alle laufen",
    value: `${running} / ${names.length - off}`, valueNote: off ? `laufen · ${off} aus` : "laufen",
    body: el("div", {}, list, opsRows(status), el("p", { class: "panel-foot" }, "Neustarts zählt der Supervisor ", info("overview_restarts", "Neustarts"))),
  });
}

// Kurze Namen für die Dienste-Kachel; der volle Name steht im Tooltip.
const SERVICE_SHORT = { chronyd: "chronyd", gpsd: "gpsd", ptp4l: "ptp4l", phc2sys: "phc2sys", dnsfwd: "DNS", web: "Dashboard" };

const EVENT_LABEL = { info: "Info", warn: "Warnung", crit: "Kritisch" };

function eventsPanel(ctx) {
  const data = ctx.data("overview-events", "/api/events?limit=5", 20);
  const events = data && Array.isArray(data.events) ? data.events.slice(0, 5) : null;
  const today = new Date().toDateString();
  const body = events === null ? emptyNote("lädt …")
    : !events.length ? emptyNote("Noch keine Ereignisse – hier erscheinen Quellenwechsel, GPS-Ausfälle, Neustarts und Änderungen.")
      : el("ol", { class: "event-list" }, events.map((event) => {
        const d = new Date((event.t || 0) * 1000);
        const time = d.toDateString() === today
          ? d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })
          : `${d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })} ${d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}`;
        const level = event.level === "crit" || event.level === "warn" ? event.level : "info";
        return el("li", { class: "event", "data-level": level },
          el("time", { class: "event-time", datetime: d.toISOString(), title: `vor ${fmtDuration(Date.now() / 1000 - (event.t || 0))}`, text: time }),
          el("span", { class: "event-level", text: EVENT_LABEL[level] }),
          el("span", { class: "event-title", text: event.display_title || event.title || "" }));
      }));
  return panel({ title: "Letzte Ereignisse", help: "overview_events", tone: "muted", body,
    href: "#/diagnose", linkLabel: "Alle Ereignisse" });
}

const OFFSET_BANDS = [
  { from: 0.005, to: 0.05, tone: "warn", label: "> 5 ms" }, { from: -0.05, to: -0.005, tone: "warn", label: "< −5 ms" },
  { from: 0.05, tone: "crit", label: "> 50 ms" }, { to: -0.05, tone: "crit", label: "< −50 ms" },
];

const TONE_WORD = { warn: "erhöht", crit: "kritisch" };

export function render(ctx) {
  const { status, history } = ctx;
  const t = status.tracking || {};
  const sources = status.sources || [];
  const insights = status.insights || [];
  const rootDistance = isNum(t.root_delay) && isNum(t.root_dispersion) ? t.root_delay / 2 + t.root_dispersion : null;
  const rate = requestRate(history);
  // Letzter gültiger Wert: nach einem Zählerreset ist der jüngste Punkt leer.
  let lastRate = null;
  for (let i = rate.length - 1; i >= 0; i -= 1) if (isNum(rate[i][1])) { lastRate = rate[i][1]; break; }
  const ref = sources.find((s) => s.state === "*");
  // Temperatur: letzter Messpunkt des Verlaufs (nur wenn ein Sensor aufzeichnet, höchstens 5 min alt).
  const lastSample = history.length ? history[history.length - 1] : null;
  const lastTemp = lastSample && isNum(lastSample.temp) && Date.now() / 1000 - lastSample.t < 300 ? lastSample.temp : null;
  // x-Achse aller Verläufe: gewählter Zeitraum bis jetzt (Serverzeit).
  const span = { range: ctx.range, end: isNum(status.system?.time) ? status.system.time : Date.now() / 1000 };

  const series = (key) => history.map((s) => [s.t, isNum(s[key]) ? s[key] : null]);
  const distance = history.map((s) => [s.t, isNum(s.root_delay) && isNum(s.root_dispersion) && s.stratum > 0 && s.stratum < 16
    ? s.root_delay / 2 + s.root_dispersion : null]);
  const offsets = series("offset");
  const freq = series("freq");

  // --- Statusband -------------------------------------------------------------
  const v = verdict(status, insights);
  const facts = status.chrony_running ? [
    t.stratum ? `Stratum ${t.stratum}` : null,
    ref ? `über ${sourceLabel(ref)}` : t.local_reference ? "lokale Uhr" : null,
    `${sources.filter((s) => s.state === "*" || s.state === "+").length} von ${sources.length} Quellen genutzt`,
    `${fmtNumber(status.client_count ?? 0)} Clients`,
  ].filter(Boolean) : null;
  const offTone = offsetTone(t.system_time_offset);
  const kpis = el("div", { class: "hero-kpis" },
    tile({ label: "Abweichung", help: "system_offset", value: fmtSeconds(t.system_time_offset, 3, true), tone: offTone,
      note: TONE_WORD[offTone] ? el("span", {}, badge(TONE_WORD[offTone], offTone), ` RMS ${fmtSeconds(t.rms_offset)}`) : `RMS ${fmtSeconds(t.rms_offset)}`,
      spark: sparkline(offsets, { zero: true, ...span }) }),
    tile({ label: "Max. Fehler", help: "uncertainty", value: rootDistance === null ? "–" : `± ${fmtSeconds(rootDistance)}`,
      tone: "muted", note: "Fehlerschranke zu UTC", spark: sparkline(distance, { min: 0, ...span }) }),
    tile({ label: "Frequenz", help: "frequency", value: isNum(t.frequency_ppm) ? fmtFixed(t.frequency_ppm, 3) : "–", unit: "ppm",
      tone: "muted", note: `Skew ${isNum(t.skew_ppm) ? fmtFixed(t.skew_ppm, 3) : "–"} ppm`, spark: sparkline(freq, span) }),
    tile({ label: "Anfragen", help: "served_rate", value: fmtRate(lastRate), unit: "/min",
      tone: "muted", note: `${fmtNumber(status.client_count ?? 0)} Clients im LAN`, spark: sparkline(rate, { min: 0, ...span }) }));
  const hero = el("section", { class: "card hero", "data-tone": v.tone, "aria-label": "Gesamtzustand" },
    el("div", { class: "hero-top" },
      el("div", { class: "hero-verdict" },
        el("span", { class: "verdict-icon", "aria-hidden": "true", text: VERDICT_ICON[v.tone] }),
        el("div", { class: "verdict-text" },
          el("div", { class: "verdict-title" }, el("h2", { text: v.title }), info("overview_verdict", "Gesamtzustand")),
          el("p", { class: "verdict-sub", text: v.text }),
          facts ? el("p", { class: "verdict-facts" }, facts.map((f, i) => el("span", { class: "fact", text: i ? `· ${f}` : f }))) : null)),
      kpis),
    hintsBlock(ctx, insights));

  // --- Teilsysteme ------------------------------------------------------------
  const own = (id) => issuesFor(insights, id);
  const list = [
    syncPanel(status, ref, rootDistance, own("clock"), lastTemp), sourcesPanel(status, own("sources")),
    (status.gps || {}).enabled ? gpsPanel(status, own("gps")) : null,
    (status.ptp || {}).enabled ? ptpPanel(status, own("ptp")) : null,
    clientsPanel(ctx, lastRate, rate, own("clients"), span), servicesPanel(status.services, own("services"), status),
  ].filter(Boolean);
  // Die Ereignisse füllen die Zeile auf (4 bzw. 2 Spalten), damit keine Lücke bleibt.
  const events = eventsPanel(ctx);
  const n = list.length;
  events.style.setProperty("--span4", String(4 - (n % 4)));
  events.style.setProperty("--span2", String(2 - (n % 2)));
  events.classList.add("panel-fill");
  const panels = el("div", { class: "panels" }, list, events);

  // --- Verläufe -----------------------------------------------------------------
  const charts = el("div", { class: "charts-grid" });
  const chartCards = [
    ["Abweichung der Systemuhr", "system_offset", "Negativ: die Systemuhr geht vor.",
      { series: [{ id: "offset", label: "Abweichung", color: "var(--accent)", points: offsets }], current: t.system_time_offset,
        format: (x) => fmtSeconds(x, 3, true), axisFormat: axisSeconds, bands: OFFSET_BANDS,
        ariaLabel: "Verlauf der Abweichung der Systemuhr" }],
    ["Maximaler Fehler zu UTC", "uncertainty", "Halbe Root Delay + Root Dispersion – so weit kann die Uhr höchstens von UTC weg sein.",
      { series: [{ id: "dist", label: "± max.", color: "var(--accent)", points: distance }], current: rootDistance,
        format: (x) => `± ${fmtSeconds(x)}`, axisFormat: axisSeconds, min: 0, zeroLine: false,
        ariaLabel: "Verlauf des maximalen Fehlers zu UTC" }],
    ["Frequenzfehler", "frequency", "Wie schnell der Quarz ungeregelt laufen würde.",
      { series: [{ id: "freq", label: "ppm", color: "var(--accent)", points: freq }], current: t.frequency_ppm,
        format: (x) => `${fmtFixed(x, 3)} ppm`, axisFormat: (x, step) => `${fmtFixed(x, stepDecimals(step))} ppm`, zeroLine: false,
        ariaLabel: "Verlauf des Frequenzfehlers" }],
    ["Beantwortete Anfragen", "served_rate", "NTP-Anfragen aus dem LAN pro Minute.",
      { series: [{ id: "rate", label: "pro Minute", color: "var(--accent)", points: rate }], current: lastRate ?? undefined,
        nowLabel: "zuletzt", format: (x) => `${fmtRate(x)}/min`, axisFormat: (x, step) => fmtNumber(x, stepDecimals(step)), min: 0,
        emptyText: "Noch keine Anfragen gemessen", ariaLabel: "Verlauf der beantworteten Anfragen pro Minute" }],
  ];
  for (const [title, help, sub, opts] of chartCards) {
    const target = el("div", { class: "chart-host" });
    charts.append(card(title, { help, sub, class: "chart-card" }, target));
    ctx.afterRender(() => lineChart(target, { height: 200, key: `overview-${opts.series[0].id}`, ...span, ...opts }));
  }

  return [
    hero,
    panels,
    unusedStrip(status),
    el("div", { class: "toolbar section-head" },
      el("h2", { class: "section-title", text: "Verlauf" }),
      el("span", { class: "toolbar-label", text: "Zeitraum" }), rangeButtons(ctx.range, ctx.setRange)),
    charts,
    status.chrony_running ? card("Details zur Systemuhr", { help: "reference", id: "systemuhr",
      sub: "Alles, was chrony über die eigene Uhr meldet (`chronyc tracking`). Das ⓘ erklärt jeden Wert." },
    trackingDetails(status, ref)) : null,
  ].filter(Boolean);
}

// Achsenbeschriftung: Einheit aus dem ganzen Achsenbereich (`extent`), damit eine
// Achse nicht mitten drin von ns auf µs springt; Nachkommastellen aus der
// Schrittweite, damit sich benachbarte Gitterlinien nie gleich beschriften.
export function axisSeconds(value, step, extent) {
  const abs = Math.max(isNum(extent) ? extent : Math.abs(value), step);
  let unit = "s"; let scale = 1;
  if (abs < 1e-6) { unit = "ns"; scale = 1e9; } else if (abs < 1e-3) { unit = "µs"; scale = 1e6; } else if (abs < 1) { unit = "ms"; scale = 1e3; }
  const scaled = step * scale;
  const decimals = scaled >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(scaled) - 1e-9));
  return `${value === 0 ? "0" : fmtFixed(value * scale, decimals)} ${unit}`;
}

export { info };
