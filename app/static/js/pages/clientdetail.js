// Detailseite eines Clients: #/clients/<adresse>
// Verlauf der Abweichung, Abstand/Poll, Zustand mit Grund, vermutete Software, Name/Notiz,
// „Aktiv nachmessen“. Alles kommt aus /api/clients/detail; geschrieben wird nur über
// /api/clients/meta und /api/clients/probe (Admin).
import { el, apiPost, fmtDuration, fmtNumber, fmtSeconds, fmtTime, isNum } from "../util.js";
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
    sub: "Nur für dich: Name und Notiz bleiben auf dieser Instanz. Im Diagnosepaket und in Benachrichtigungen "
      + "ersetzt ntp-gui den Namen durch einen Platzhalter." },
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
  list.length ? el("ul", { class: "client-guess" }, list.map((c) => el("li", {},
    el("div", { class: "client-guess-head" }, el("strong", { text: c.label }),
      badge(c.confidence, c.confidence === "wahrscheinlich" ? "good" : "muted")),
    el("ul", { class: "client-guess-reasons" }, (c.reasons || []).map((r) => el("li", { text: r }))))))
    : emptyNote("Zu wenig Hinweise für eine Vermutung."),
  (sw.basis || []).length ? el("p", { class: "field-help", text: `Grundlage: ${sw.basis.join(" · ")}` }) : null);
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
  const age = isNum(entry.last_seen) ? Math.max(0, Date.now() / 1000 - entry.last_seen) : null;
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
      detail.rdns ? el("span", { class: "mono client-sub", text: detail.rdns }) : null),
    el("div", { class: "stat-row" },
      tile({ label: "Uhr geht falsch um", help: "client_offset", value: entry.measurable ? fmtOffset(entry.ewma) : "–",
        tone: entry.measurable ? offsetTone(entry.ewma) : "muted",
        note: entry.measurable && isNum(entry.min) ? `${fmtOffset(entry.min)} … ${fmtOffset(entry.max)}` : (entry.state_text || "noch keine Anfrage") }),
      tile({ label: "Zuletzt", help: "client_seen", value: isNum(age) ? `vor ${fmtDuration(age)}` : "–",
        tone: detail.silent ? "warn" : "muted", note: detail.silent || fmtDate(entry.last_seen) }),
      tile({ label: "Typischer Abstand", help: "client_typical_interval", value: fmtInterval(entry.interval),
        tone: isNum(entry.interval) && entry.interval < 8 ? "warn" : "muted",
        note: isNum(entry.poll) ? `Poll-Feld ${entry.poll}${entry.poll === 0 ? " (nicht gesetzt)" : ""}` : "Poll-Feld unbekannt" }),
      tile({ label: "NTP-Version", help: "client_version", value: isNum(entry.version) ? String(entry.version) : "–",
        tone: "muted", note: `${fmtNumber(entry.requests || 0)} Anfragen` })),
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
          ["Zuerst gesehen", fmtDate(entry.first_seen), "client_seen"],
          ["Zuletzt gesehen", fmtDate(entry.last_seen), "client_seen"],
          ["Anfragen", fmtNumber(entry.requests || 0), "client_packets"],
          ["Messbar", stateBadge, "client_measurable"],
        ]),
        el("p", { class: "field-help", text: detail.measurable_reason || "" }),
        detail.rdns_skipped ? el("p", { class: "field-help", text: `DNS: ${detail.rdns_skipped}` }) : null),
      softwareCard(detail)),
    el("div", { class: "grid-2" }, metaCard(ctx, ip, detail), probeCard(ctx, ip, detail)),
  ];
}

