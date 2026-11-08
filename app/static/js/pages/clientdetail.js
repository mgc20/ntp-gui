// Detailseite eines Clients: #/clients/<adresse>
// Verlauf der Abweichung, Abstand/Poll, Zustand mit Grund, vermutete Software, Name/Notiz,
// „Aktiv nachmessen“. Alles kommt aus /api/clients/detail; geschrieben wird nur über
// /api/clients/meta und /api/clients/probe (Admin).
import { el, apiPost, fmtDuration, fmtNumber, fmtSeconds, fmtTime, fmtLogInterval, isNum, rich } from "../util.js";
import { card, tile, info, badge, kv, emptyNote, toast } from "../ui.js";
import { lineChart } from "../charts.js";
import { axisSeconds } from "./overview.js";

// --- Gemeinsame Helfer (auch für die Client-Liste) -----------------------------
export const STATE_TONE = { ok: "good", "falsche Uhr": "crit", verschleiert: "muted", "ohne Zeitstempel": "muted" };
export const STATE_SHORT = { ok: "messbar", "falsche Uhr": "messbar", verschleiert: "verschleiert",
  "ohne Zeitstempel": "ohne Zeitstempel" };

export function fmtOffset(value) {
  if (!isNum(value)) return "–";
  const abs = Math.abs(value);
  if (abs >= 86400) return `${value > 0 ? "+" : "−"}${fmtDuration(abs)}`;
  return fmtSeconds(value, 3, true);
}

export function offsetTone(value) {
  if (!isNum(value)) return "muted";
  const abs = Math.abs(value);
  return abs < 0.005 ? "good" : abs < 0.5 ? "warn" : "crit";
}

export function fmtInterval(seconds) {
  if (!isNum(seconds)) return "–";
  if (seconds < 10) return `${fmtNumber(seconds, 1)} s`;
  return fmtDuration(seconds);
}

export function fmtDate(unix) {
  if (!isNum(unix)) return "–";
  return new Date(unix * 1000).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

export function clientHref(address) {
  return `#/clients/${encodeURIComponent(address)}`;
}

const RANGES = [[3600, "1 h"], [21600, "6 h"], [86400, "24 h"], [604800, "7 Tage"]];

function rangeGroup(current, onChange) {
  return el("div", { class: "range-group", role: "group", "aria-label": "Zeitraum" },
    RANGES.map(([seconds, label]) => el("button", {
      type: "button", class: `range${current === seconds ? " is-active" : ""}`, text: label,
      "data-focus-key": `clientrange:${seconds}`, "aria-pressed": current === seconds ? "true" : "false",
      onclick: () => onChange(seconds),
    })));
}

// --- Name und Notiz ---------------------------------------------------------------
function metaCard(ctx, ip, detail) {
  const drafts = ctx.uiState.clientMeta || (ctx.uiState.clientMeta = {});
  const draft = drafts[ip] || (drafts[ip] = { name: detail.name || "", note: detail.note || "", dirty: false });
  if (!draft.dirty) { draft.name = detail.name || ""; draft.note = detail.note || ""; }
  const readonly = ctx.readonly;
  const name = el("input", { type: "text", maxlength: "64", value: draft.name, disabled: readonly || null,
    placeholder: "z. B. NAS im Keller", "aria-label": "Eigener Name des Geräts" });
  const note = el("textarea", { rows: "3", maxlength: "500", disabled: readonly || null,
    placeholder: "z. B. stellt die Zeit nur nach einem Neustart", "aria-label": "Notiz zum Gerät" });
  note.value = draft.note;
  name.addEventListener("input", () => { draft.name = name.value; draft.dirty = true; });
  note.addEventListener("input", () => { draft.note = note.value; draft.dirty = true; });
  const save = async () => {
    try {
      const result = await apiPost("/api/clients/meta", { ip, name: draft.name, note: draft.note });
      draft.dirty = false;
      draft.name = result.name;
      draft.note = result.note;
      toast("Gespeichert");
      ctx.invalidate(`clientdetail:${ip}`);
      ctx.invalidate("clientoffsets");
      ctx.invalidate("clientoverview");
      ctx.rerender();
    } catch (error) {
      toast(`Nicht gespeichert: ${error.message}`, "crit");
    }
  };
  return card("Eigener Name und Notiz", { help: "client_meta",
    sub: "Nur für dich: Name und Notiz bleiben auf dieser Instanz. Im Diagnosepaket ersetzt ntp-gui den Namen "
      + "durch einen Platzhalter; Benachrichtigungen über dieses Gerät nennen ihn – statt der Adresse." },
  el("div", { class: "fields" },
    el("label", { class: "field" }, el("span", { class: "field-label", text: "Name" }), name),
    el("label", { class: "field" }, el("span", { class: "field-label", text: "Notiz" }), note)),
  readonly ? emptyNote("Änderungen sind gesperrt (WEB_READONLY).")
    : el("div", { class: "button-row" }, el("button", { type: "button", class: "button primary", text: "Speichern", onclick: save })));
}

// --- Aktiv nachmessen ---------------------------------------------------------------
const probeBusy = new Set();

function probeCard(ctx, ip, detail) {
  const results = ctx.uiState.clientProbe || (ctx.uiState.clientProbe = {});
  const result = results[ip];
  const busy = probeBusy.has(ip);
  const run = async () => {
    probeBusy.add(ip);
    ctx.rerender();
    try {
      results[ip] = await apiPost("/api/clients/probe", { ip });
    } catch (error) {
      toast(error.message, "warn");
    }
    probeBusy.delete(ip);
    ctx.rerender();
  };
  const allowed = detail.probe_allowed && !ctx.readonly;
  const button = el("button", { type: "button", class: "button", disabled: busy || !allowed || null,
    text: busy ? "Messe …" : "Aktiv nachmessen", onclick: run });
  let body;
  if (!result) {
    body = emptyNote(detail.probe_allowed
      ? "Schickt **eine** NTP-Anfrage an das Gerät (Port 123, 2 s Zeitlimit). Router, NAS und manche Kameras "
        + "laufen selbst als Zeitserver und antworten – dann siehst du ihre Uhr auch, wenn sie ihre Sendezeit verschleiern."
      : detail.probe_blocked || "Nachmessen geht nur bei Geräten mit privater Adresse, die diesen Server schon gefragt haben.");
  } else if (!result.answered || !isNum(result.offset)) {
    body = el("p", { class: "card-sub" }, el("strong", { text: `${fmtTime(result.t)}: ` }), el("span", { text: result.text }));
  } else {
    body = el("div", {},
      kv([
        ["Uhr geht falsch um", el("span", { class: "offset-value", "data-tone": offsetTone(result.offset), text: fmtOffset(result.offset) }), "client_probe"],
        ["Laufzeit hin und zurück", fmtSeconds(result.rtt, 3), "client_probe"],
        ["Stratum des Geräts", String(result.stratum ?? "–"), "client_probe"],
      ]),
      el("p", { class: "card-sub" }, el("span", { text: `${fmtTime(result.t)}: ${result.text}` })));
  }
  return card("Aktiv nachmessen", { help: "client_probe", actions: button }, body);
}

// --- Vermutete Software -------------------------------------------------------------
function softwareCard(detail) {
  const sw = detail.software || {};
  const list = sw.candidates || [];
  return card("Vermutete Client-Software", { help: "client_software",
    badge: badge("Vermutung", "warn", "Aus Indizien geschätzt – kein Beweis") },
  detail.expect_mismatch ? el("p", { class: "client-mismatch", text: detail.expect_mismatch }) : null,
  list.length ? el("ul", { class: "client-guess" }, list.map((c) => el("li", {},
    el("div", { class: "client-guess-head" }, el("strong", { text: c.label }),
      badge(c.confidence, c.confidence === "wahrscheinlich" ? "good" : "muted")),
    el("ul", { class: "client-guess-reasons" }, (c.reasons || []).map((r) => el("li", { text: r }))))))
    : emptyNote("Zu wenig Hinweise für eine Vermutung."),
  (sw.basis || []).length ? el("p", { class: "field-help", text: `Grundlage: ${sw.basis.join(" · ")}` }) : null);
}

// --- Clients 3 (1.5): Uhrgüte, Regeln, NTS -------------------------------------------
export function qualityBadge(q) {
  if (!q || !isNum(q.score)) return badge(q?.grade || "–", "muted", q?.text || null);
  return badge(`${q.score} · ${q.grade}`, q.tone || "muted", q.text || null);
}

export function fmtPpm(value) {
  if (!isNum(value)) return "–";
  return `${value >= 0 ? "+" : "−"}${fmtNumber(Math.abs(value), Math.abs(value) < 10 ? 1 : 0)} ppm`;
}

// Gangabweichung aus der Uhrgüte: gemessen (drift_ppm) oder – bei gleichmäßigen Abständen – nur eine
// Obergrenze (drift_bound_ppm), weil fester Versatz und Gang dann nicht zu trennen sind.
export function fmtDrift(q) {
  if (!q) return "–";
  if (isNum(q.drift_ppm)) return fmtPpm(q.drift_ppm);
  if (isNum(q.drift_bound_ppm)) {
    const v = Math.abs(q.drift_bound_ppm);
    return `höchstens ${fmtNumber(v, v < 10 ? 1 : 0)} ppm`;
  }
  return "–";
}

function qualityCard(detail) {
  const q = detail.quality;
  if (!q) return null;
  const parts = q.components || [];
  return card("Uhrgüte", { help: "client_quality", badge: qualityBadge(q),
    sub: q.text || null },
  kv([
    ["Gangabweichung", isNum(q.drift_ppm) ? `${fmtPpm(q.drift_ppm)}${isNum(q.drift_err_ppm) ? ` (± ${fmtNumber(q.drift_err_ppm, 1)})` : ""}` : fmtDrift(q), "client_drift"],
    ["Abfrage-Intervall", fmtInterval(q.interval), "client_typical_interval"],
    ["Streuung", isNum(q.jitter) ? `± ${fmtOffset(q.jitter).replace(/^[+−]/, "")}` : "–", "client_quality_parts"],
    ["Messungen ausgewertet", fmtNumber(q.n || 0), "client_quality"],
  ]),
  parts.length ? el("ul", { class: "quality-parts", "aria-label": "Bestandteile der Uhrgüte" }, parts.map((c) =>
    el("li", {},
      el("span", { class: "quality-part-label", text: c.label }),
      el("span", { class: "quality-part-bar", "aria-hidden": "true" },
        el("span", { class: "quality-part-fill", style: `width:${(c.points / c.max) * 100}%` })),
      el("span", { class: "quality-part-points", text: `${c.points}/${c.max}` }),
      el("span", { class: "field-help", text: c.text })))) : null,
  parts.length ? el("p", { class: "field-help" }, "Wie die Punkte entstehen: ", info("client_quality_parts")) : null);
}

function numberInput(value, attrs) {
  return el("input", { type: "number", inputmode: "decimal", value: isNum(value) ? String(value) : "", ...attrs });
}

function rulesCard(ctx, ip, detail) {
  const rule = detail.rule || {};
  const drafts = ctx.uiState.clientRules || (ctx.uiState.clientRules = {});
  const fresh = { silent_h: rule.silent_h ?? null, offset_ms: rule.offset_ms ?? null, offset_min: rule.offset_min || 0,
    mute: Boolean(rule.mute), expect: rule.expect || "" };
  const draft = drafts[ip] && drafts[ip].dirty ? drafts[ip] : (drafts[ip] = { ...fresh, dirty: false });
  const readonly = ctx.readonly;
  const touch = (key, value) => { draft[key] = value; draft.dirty = true; };
  const silent = numberInput(draft.silent_h, { min: "0.25", max: "720", step: "0.25", disabled: readonly || null,
    placeholder: "aus", "aria-label": "Stunden ohne Anfrage" });
  silent.addEventListener("input", () => touch("silent_h", silent.value === "" ? null : Number(silent.value)));
  const offset = numberInput(draft.offset_ms, { min: "1", max: "86400000", step: "1", disabled: readonly || null,
    placeholder: "aus", "aria-label": "Eigene Schwelle in Millisekunden" });
  offset.addEventListener("input", () => touch("offset_ms", offset.value === "" ? null : Number(offset.value)));
  const minutes = numberInput(draft.offset_min, { min: "0", max: "1440", step: "1", disabled: readonly || null,
    "aria-label": "Minuten über der Schwelle" });
  minutes.addEventListener("input", () => touch("offset_min", minutes.value === "" ? 0 : Number(minutes.value)));
  const mute = el("input", { type: "checkbox", role: "switch", checked: draft.mute, disabled: readonly || null,
    "aria-label": "Gerät stummschalten" });
  const muteText = el("span", { class: "switch-text", text: draft.mute ? "an" : "aus" });
  mute.addEventListener("change", () => { touch("mute", mute.checked); muteText.textContent = mute.checked ? "an" : "aus"; });
  const expect = el("select", { disabled: readonly || null, "aria-label": "Erwartete Client-Software" },
    el("option", { value: "", text: "keine Angabe" }),
    (detail.expect_options || []).map((o) => el("option", { value: o.key, text: o.label })));
  expect.value = draft.expect;
  expect.addEventListener("change", () => touch("expect", expect.value));
  const save = async () => {
    try {
      await apiPost("/api/clients/rules", { ip, silent_h: draft.silent_h, offset_ms: draft.offset_ms,
        offset_min: draft.offset_min, mute: draft.mute, expect: draft.expect });
      drafts[ip] = { ...draft, dirty: false };
      toast("Regeln gespeichert");
      ctx.invalidate(`clientdetail:${ip}`);
      ctx.invalidate("clientgroups");
      ctx.rerender();
    } catch (error) {
      toast(`Nicht gespeichert: ${error.message}`, "crit");
    }
  };
  const field = (label, help, control, note) => el("div", { class: "field" },
    el("div", { class: "field-head" }, el("span", { class: "field-label" }, el("span", { text: label }), " ", info(help, label))),
    control, note ? el("p", { class: "field-help", text: note }) : null);
  const open = [rule.silent_alarm ? "„fragt nicht mehr“ ist gemeldet" : null,
    rule.offset_alarm ? "„weicht ab“ ist gemeldet" : null].filter(Boolean);
  return card("Regeln für dieses Gerät", { help: "client_rules",
    badge: open.length ? badge("Alarm offen", "warn", open.join(", ")) : null,
    sub: "Eigene Meldungen nur für dieses Gerät – entprellt wie alle Ereignisse. Benachrichtigungen nennen den "
      + "**eigenen Namen** des Geräts" + (detail.lan_addresses_in_messages ? " und seine LAN-Adresse." : ", nie seine Adresse.") },
  el("div", { class: "fields" },
    field("Melden, wenn es so lange nicht fragt (Stunden)", "client_rule_silent", silent,
      "Für Geräte, die immer fragen sollten (Kamera, SPS, NAS). Leer = aus. Gezählt wird nur, solange ntp-gui mithört."),
    field("Eigene Alarm-Schwelle (ms)", "client_rule_offset", offset,
      "Ersetzt für dieses Gerät die allgemeine Schwelle aus den Einstellungen. Leer = allgemeine Schwelle."),
    field("… für mindestens (Minuten)", "client_rule_offset", minutes,
      "0 = sobald zwei Messungen hintereinander darüber liegen."),
    field("Stumm", "client_rule_mute", el("label", { class: "switch" }, mute,
      el("span", { class: "switch-track", "aria-hidden": "true" }), muteText),
    "Ereignisse bleiben im Protokoll, gehen aber nicht als Benachrichtigung hinaus."),
    field("Erwartete Client-Software", "client_rule_expect", expect,
      "Was auf dem Gerät läuft, wenn du es weißt – zählt in der Ansicht „nach Software“ und im Gerätepass vor der Vermutung.")),
  readonly ? emptyNote("Änderungen sind gesperrt (WEB_READONLY).")
    : el("div", { class: "button-row" }, el("button", { type: "button", class: "button primary", text: "Regeln speichern", onclick: save })));
}

function ntsCard(detail) {
  const nts = detail.nts;
  if (!nts) return null;
  const tone = nts.uses ? "good" : nts.server ? "muted" : "muted";
  const can = nts.can === true ? "ja" : nts.can === false ? "nein" : "je nach Variante";
  return card("NTS für dieses Gerät", { help: "client_nts",
    badge: badge(nts.uses ? "nutzt NTS" : nts.server ? "kein NTS" : "NTS-Server aus", tone) },
  kv([
    ["NTS-Server dieser Instanz", nts.server ? "an" : "aus", "client_nts"],
    ["Nutzt NTS", nts.uses === null ? "–" : nts.uses ? `ja (${fmtNumber(nts.nts_ke || 0)} Schlüsselaustausche)` : "nein", "client_nts"],
    ["Software kann NTS", can, "client_nts"],
  ]),
  el("p", { class: "field-help", text: nts.text || "" }),
  el("p", { class: "field-help" }, rich(nts.how || "")));
}

// Zähler aus chronyd („chronyc clients“). Kennt die eigene Messung das Gerät noch nicht (aus oder gerade
// gestartet), steht hier wenigstens, was chrony weiß – statt „keine Daten“.
export function ownKnown(detail) {
  return Boolean(detail.entry && Object.keys(detail.entry).length) || (detail.samples || []).length > 0;
}

// Kennt nur chrony das Gerät, kommen „Zuletzt“ und „Anfragen“ aus chronyd – sonst widerspräche die
// Kachelreihe („0 Anfragen“) der Karte „Laut chrony“ darunter.
export function seenFacts(detail, now = Date.now() / 1000) {
  const entry = detail.entry || {};
  const c = !ownKnown(detail) && detail.chrony ? detail.chrony : null;
  if (c) {
    return { age: isNum(c.ntp_last_rx) ? Math.max(0, c.ntp_last_rx) : null, requests: isNum(c.ntp_packets) ? c.ntp_packets : 0,
      lastText: "laut chrony", source: "chrony" };
  }
  return { age: isNum(entry.last_seen) ? Math.max(0, now - entry.last_seen) : null, requests: entry.requests || 0,
    lastText: fmtDate(entry.last_seen), source: "own" };
}

export function chronyCard(detail) {
  const c = detail.chrony;
  if (!c) return null;
  const known = ownKnown(detail);
  return card("Laut chrony", { help: "client_packets" },
    kv([
      ["Anfragen", fmtNumber(c.ntp_packets), "client_packets"],
      ["Verworfen", fmtNumber(c.ntp_dropped), "client_dropped"],
      ["Intervall", fmtLogInterval(c.ntp_interval), "client_interval"],
      ["Zuletzt", isNum(c.ntp_last_rx) ? `vor ${fmtDuration(c.ntp_last_rx)}` : "–", "client_last"],
    ]),
    known ? null : el("p", { class: "field-help", text: "Die eigene Messung kennt das Gerät noch nicht (aus oder gerade "
      + "gestartet) – deshalb bleiben Abweichung, Verlauf und Software leer. Die Zähler oben kommen direkt von chronyd." }));
}

// --- Seite --------------------------------------------------------------------------
export function renderDetail(ctx, ip) {
  const range = ctx.uiState.clientRange || 86400;
  const url = `/api/clients/detail?ip=${encodeURIComponent(ip)}&range=${range}`;
  const detail = ctx.data(`clientdetail:${ip}`, url, 15);
  const back = el("p", { class: "client-back" }, el("a", { href: "#/clients", text: "← Alle Clients" }));
  const failed = detail === undefined ? ctx.dataError?.(`clientdetail:${ip}`, url) : null;
  if (failed && failed.status === 400) {
    return [back, card(ip, { help: "client_detail" },
      emptyNote("Ungültige Adresse – im Link steht keine IPv4- oder IPv6-Adresse. Wähle das Gerät in der Client-Liste aus."))];
  }
  if (failed && failed.status !== 404) {
    return [back, card(ip, { help: "client_detail" },
      emptyNote(`Die Daten des Geräts ließen sich nicht laden (${failed.message}). Ich versuche es gleich noch einmal.`))];
  }
  if (detail === undefined && !failed) return [back, emptyNote("Lade Daten des Geräts …")];
  if (!detail || !detail.address) {
    return [back, card(ip, { help: "client_detail" },
      emptyNote("Zu diesem Gerät liegen keine Daten vor – es hat diesen Server nicht gefragt, seit die Messung läuft, "
        + "oder seine Daten sind älter als 30 Tage."))];
  }
  const entry = detail.entry || {};
  const samples = detail.samples || [];
  const title = detail.name || detail.address;
  const seen = seenFacts(detail);
  const age = seen.age;
  const viaChrony = seen.source === "chrony";
  const end = ctx.status.system?.time;

  const offsetHost = el("div", { class: "chart-host" });
  const intervalHost = el("div", { class: "chart-host" });
  const offsets = samples.filter((s) => isNum(s[1])).map((s) => [s[0], s[1]]);
  const intervals = samples.filter((s) => isNum(s[4])).map((s) => [s[0], s[4]]);
  const polls = samples.filter((s) => isNum(s[2]) && s[2] > 0 && s[2] <= 17).map((s) => [s[0], 2 ** s[2]]);
  ctx.afterRender(() => {
    lineChart(offsetHost, {
      key: `client-offset:${ip}`,
      series: [{ id: "offset", label: "Abweichung", color: "var(--accent)", points: offsets }],
      format: fmtOffset, axisFormat: axisSeconds, range, end, ariaLabel: `Abweichung der Uhr von ${title} über die Zeit`,
      emptyText: entry.measurable === false ? "Nicht messbar – das Gerät schickt keine echte Uhrzeit" : "Noch zu wenige Messwerte",
    });
    lineChart(intervalHost, {
      key: `client-interval:${ip}`,
      series: [
        { id: "interval", label: "Abstand der Anfragen", points: intervals },
        { id: "poll", label: "Poll-Feld (2^poll)", points: polls },
      ],
      format: fmtInterval, range, end, scale: "log", zeroLine: false,
      hidden: ctx.uiState.clientIntervalHidden || new Set(),
      onToggle: (id) => {
        const set = ctx.uiState.clientIntervalHidden || (ctx.uiState.clientIntervalHidden = new Set());
        if (set.has(id)) set.delete(id); else set.add(id);
        ctx.rerender();
      },
      ariaLabel: `Abstand der Anfragen und Poll-Feld von ${title}`, emptyText: "Noch zu wenige Anfragen",
    });
  });

  const setRange = (seconds) => { ctx.uiState.clientRange = seconds; ctx.rerender(); };
  const mac = detail.mac;
  const macText = mac ? `${mac.mac}${mac.random ? " (zufällig gewählt)" : ""}` : "–";
  const vendorText = !mac ? "–" : mac.random ? "– (zufällige MAC verrät keinen Hersteller)"
    : mac.vendor || (mac.vendor_list ? "unbekannt" : "– (keine Herstellerliste im Image)");
  const stateBadge = badge(STATE_SHORT[entry.state] || "–", STATE_TONE[entry.state] || "muted", entry.state_text);

  return [
    back,
    el("div", { class: "client-head" },
      el("h1", { class: "client-title", text: title }),
      detail.name ? el("span", { class: "mono client-sub", text: detail.address }) : null,
      detail.rdns ? el("span", { class: "mono client-sub", text: detail.rdns }) : null,
      el("a", { class: "button client-pass-link", href: `${clientHref(detail.address)}/pass`, text: "Gerätepass" }),
      info("client_pass", "Gerätepass")),
    el("div", { class: "stat-row" },
      tile({ label: "Uhr geht falsch um", help: "client_offset", value: entry.measurable ? fmtOffset(entry.ewma) : "–",
        tone: entry.measurable ? offsetTone(entry.ewma) : "muted",
        note: entry.measurable && isNum(entry.min) ? `${fmtOffset(entry.min)} … ${fmtOffset(entry.max)}` : (entry.state_text || (viaChrony ? "eigene Messung: noch keine" : "noch keine Anfrage")) }),
      tile({ label: "Zuletzt", help: "client_seen", value: isNum(age) ? `vor ${fmtDuration(age)}` : "–",
        tone: detail.silent ? "warn" : "muted", note: detail.silent || seen.lastText }),
      tile({ label: "Typischer Abstand", help: "client_typical_interval", value: fmtInterval(entry.interval),
        tone: isNum(entry.interval) && entry.interval < 8 ? "warn" : "muted",
        note: isNum(entry.poll) ? `Poll-Feld ${entry.poll}${entry.poll === 0 ? " (nicht gesetzt)" : ""}` : "Poll-Feld unbekannt" }),
      tile({ label: "NTP-Version", help: "client_version", value: isNum(entry.version) ? String(entry.version) : "–",
        tone: "muted", note: `${fmtNumber(seen.requests)} Anfragen${viaChrony ? " (laut chrony)" : ""}` }),
      tile({ label: "Uhrgüte", help: "client_quality", value: isNum(detail.quality?.score) ? String(detail.quality.score) : "–",
        unit: isNum(detail.quality?.score) ? "/100" : null, tone: detail.quality?.tone || "muted",
        note: isNum(detail.quality?.drift_ppm) || isNum(detail.quality?.drift_bound_ppm)
          ? `${detail.quality.grade} · ${fmtDrift(detail.quality)}` : (detail.quality?.grade || "–") })),
    chronyCard(detail),
    card("Abweichung über die Zeit", { help: "client_offset_chart", actions: rangeGroup(range, setRange),
      sub: `Jede gespeicherte Anfrage ein Punkt (höchstens alle 2 min einer), ${fmtNumber(detail.retention_days || 7)} Tage lang.` },
    offsetHost),
    card("Abstand der Anfragen und Poll", { help: "client_interval_chart" }, intervalHost),
    el("div", { class: "grid-2" },
      card("Gerät", { help: "client_detail" },
        kv([
          ["Adresse", el("span", { class: "mono", text: detail.address }), "client_address"],
          ["Name aus dem DNS", detail.rdns || (detail.rdns_skipped ? "nicht abgefragt" : "kein Eintrag"), "client_rdns"],
          ["MAC-Adresse", macText, "client_mac"],
          ["Hersteller", vendorText, "client_mac"],
          ["VLAN", isNum(entry.vlan) ? String(entry.vlan) : "–", "client_vlan"],
          ["Gruppe", detail.group ? `${detail.group.name} (${detail.group.network})` : "ohne Gruppe", "client_group"],
          ["Zuerst gesehen", fmtDate(entry.first_seen), "client_seen"],
          ["Zuletzt gesehen", fmtDate(entry.last_seen), "client_seen"],
          ["Anfragen", `${fmtNumber(seen.requests)}${viaChrony ? " (laut chrony)" : ""}`, "client_packets"],
          ["Messbar", stateBadge, "client_measurable"],
        ]),
        el("p", { class: "field-help", text: detail.measurable_reason || "" }),
        detail.rdns_skipped ? el("p", { class: "field-help", text: `DNS: ${detail.rdns_skipped}` }) : null),
      softwareCard(detail)),
    el("div", { class: "grid-2" }, qualityCard(detail), ntsCard(detail)),
    el("div", { class: "grid-2" }, metaCard(ctx, ip, detail), rulesCard(ctx, ip, detail)),
    probeCard(ctx, ip, detail),
  ];
}

