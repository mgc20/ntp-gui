import { t as tr } from "../i18n.js";
import { el, fmtSeconds, fmtDuration, fmtLogInterval, fmtNumber, fmtDate, isNum, rich } from "../util.js";
import { card, kv, badge, infoButton, reachRegister, rangeButtons, emptyState, chartCard } from "../ui.js";
import { lineChart } from "../charts.js";
import { SELECT_STATE_HELP, SELECT_STATE_SHORT } from "../help.js";
import { axisSeconds } from "./overview.js";

export const STATE = {
  "*": ["ausgewählt", "good", "state_best"],
  "+": ["kombiniert", "good", "state_combined"],
  "-": ["nicht kombiniert", "info", "state_not_combined"],
  x: ["Falseticker", "crit", "state_falseticker"],
  "~": ["zu unruhig", "warn", "state_jittery"],
  "?": ["nicht erreichbar", "crit", "state_unreachable"],
};
const TYPE = { "^": "server", "=": "peer", "#": "refclock" };

export function stateBadge(source) {
  const [label, tone, help] = STATE[source.state] || [source.state_label || "–", "muted", null];
  return el("span", { class: "state-cell" }, badge(label, tone), help ? infoButton(help, label) : null);
}

// „Grund“ nur, wenn er mehr sagt als „Zustand“ (bei * und + wäre es dasselbe Wort).
function sameAsState(source) {
  const key = source.select_state;
  return Boolean(key) && (SELECT_STATE_SHORT[key] || key) === (STATE[source.state] || [])[0];
}

/** Sagt „Grund“ etwas anderes als „Zustand“? Nur dann steht er da (Tabelle, Details, GPS-Seite). */
export function reasonDiffers(source) {
  return Boolean(source && source.select_state) && !sameAsState(source);
}

export function reasonCell(source) {
  const key = source.select_state;
  if (!key || sameAsState(source)) return el("span", { class: "muted", text: "–" });
  const text = SELECT_STATE_SHORT[key] || key;
  return el("span", { class: "reason" }, el("span", { text }), infoButton(SELECT_STATE_HELP[key], text));
}

function lastRx(source) {
  return isNum(source.last_rx) ? `vor ${fmtDuration(source.last_rx)}` : "noch nie";
}

function uncertainty(source) {
  if (isNum(source.interval_low) && isNum(source.interval_high)) {
    return `± ${fmtSeconds((source.interval_high - source.interval_low) / 2)}`;
  }
  return isNum(source.error) ? `± ${fmtSeconds(source.error)}` : "–";
}

function details(source) {
  const ntp = source.ntp || {};
  const auth = source.auth || {};
  const blocks = [];
  blocks.push(el("div", { class: "detail-block" }, el("h3", { text: "Auswahl durch chrony" }), kv([
    ["Zustand", stateBadge(source)],
    reasonDiffers(source) ? ["Grund", reasonCell(source), "select_reason"] : null,
    ["Vertrauensbereich", isNum(source.interval_low) ? `${fmtSeconds(source.interval_low, 3, true)} … ${fmtSeconds(source.interval_high, 3, true)}` : "–", "interval"],
    ["Bewertung", isNum(source.score) ? fmtNumber(source.score, 2) : "–", "score"],
    ["Optionen", (source.effective_options || []).join(", ") || "keine", "select_options"],
    ["Messwerte", isNum(source.samples) ? `${source.samples} über ${fmtDuration(source.span)}` : "–", "samples"],
    ["Letzte 8 Abfragen", reachRegister(source.reach || 0), "reach"],
    ["Letzter Empfang", lastRx(source), "last_rx"],
  ])));
  if (source.ntp) {
    blocks.push(el("div", { class: "detail-block" }, el("h3", { text: "NTP-Details" }), kv([
      ["Adresse", `${ntp.remote || source.name}${ntp.remote_port ? ` : ${ntp.remote_port}` : ""}`, "hostname_vs_ip"],
      ["Referenz des Servers", ntp.reference_name ? `${ntp.reference_id} (${ntp.reference_name})` : ntp.reference_id, "server_reference"],
      ["Paketlaufzeit", fmtSeconds(ntp.peer_delay), "peer_delay"],
      ["Antwortzeit des Servers", fmtSeconds(ntp.response_time), "response_time"],
      ["Peer Dispersion", fmtSeconds(ntp.peer_dispersion), "peer_dispersion"],
      ["Root Delay / Dispersion", `${fmtSeconds(ntp.root_delay)} / ${fmtSeconds(ntp.root_dispersion)}`, "root_delay"],
      ["Präzision", isNum(ntp.precision_seconds) ? fmtSeconds(ntp.precision_seconds) : "–", "precision"],
      ["Asymmetrie", isNum(ntp.jitter_asymmetry) ? fmtNumber(ntp.jitter_asymmetry, 2) : "–", "jitter_asymmetry"],
      ["NTP-Prüfungen", isNum(ntp.ntp_tests_passed) ? `${ntp.ntp_tests_passed}/${ntp.ntp_tests_total} bestanden` : "–", "ntp_tests"],
      ["Zeitstempel", `Senden: ${ntp.tx_timestamping || "–"} · Empfang: ${ntp.rx_timestamping || "–"}`, "timestamping"],
      ["Interleaved", ntp.interleaved || "–", "interleaved"],
      ["Pakete", `${fmtNumber(ntp.total_tx)} gesendet · ${fmtNumber(ntp.total_rx)} empfangen · ${fmtNumber(ntp.total_valid_rx)} gültig`, "packets"],
    ])));
  }
  if (source.auth) {
    const nts = auth.mode === "NTS";
    blocks.push(el("div", { class: "detail-block" }, el("h3", {}, "NTS ", infoButton("nts", "NTS")), nts ? kv([
      ["Authentifiziert", source.authenticated ? "ja – Antworten sind signiert" : "nein", "nts_authenticated"],
      ["Letzter Schlüsselaustausch", auth.last_ke_ago === null ? "noch keiner" : `vor ${fmtDuration(auth.last_ke_ago)}`, "nts_ke"],
      ["Versuche / NAK", `${auth.ke_attempts ?? 0} / ${auth.nak ?? 0}`, "nts_ke"],
      ["Cookies", `${auth.cookies ?? 0} von 8`, "nts_cookies"],
    ]) : el("p", { class: "muted" }, rich("Diese Quelle nutzt kein NTS. In den Einstellungen lässt es sich je Quelle einschalten, wenn der Server es anbietet (z. B. `ptbtime1.ptb.de`)."))));
  }
  return el("div", { class: "detail-grid" }, blocks);
}

function fileState(exists, readable) {
  if (!exists) return badge("fehlt", "crit");
  return readable === false ? badge("nicht lesbar", "crit") : badge("vorhanden", "good");
}

function expiry(nts) {
  if (!nts.cert_readable) return "–";
  if (!isNum(nts.not_after)) {
    return nts.openssl === false ? "unbekannt – openssl fehlt im Image" : `unbekannt${nts.cert_error ? ` (${nts.cert_error})` : ""}`;
  }
  const days = nts.days_left;
  const tone = days < 0 ? "crit" : days < 14 ? "warn" : "good";
  const label = days < 0 ? `seit ${Math.ceil(-days)} Tagen abgelaufen` : `noch ${Math.floor(days)} Tage`;
  return el("span", {}, `${fmtDate(nts.not_after, { date: "medium", time: false })} `, badge(label, tone));
}

// Name, unter dem Clients den Server eintragen – passt er nicht zum Zertifikat,
// scheitert bei ihnen die TLS-Prüfung.
function serverName(nts) {
  const port = isNum(nts.port) && nts.port !== 4460 ? ` (NTS-KE-Port ${nts.port})` : "";
  const match = nts.name_matches_cert === true ? badge("passt zum Zertifikat", "good")
    : nts.name_matches_cert === false ? badge("steht nicht im Zertifikat", "crit") : null;
  return el("span", {}, el("span", { class: "mono", text: `${nts.name}${port} ` }), match);
}

// Eigener NTS-Server: nur sichtbar, wenn er eingeschaltet ist.
export function ntsServerCard(nts) {
  if (!nts || !nts.enabled) return null;
  return card("Eigener NTS-Server", { help: "nts_server",
    sub: "Bietet den Clients im LAN abgesicherte Zeit an: Schlüsselaustausch über TCP-Port 4460, danach signierte NTP-Pakete. Normales NTP läuft parallel weiter." },
  el("div", { class: "grid-2" },
    kv([
      ["Zertifikat", el("span", {}, el("span", { class: "mono", text: `${nts.cert || "–"} ` }), fileState(nts.cert_exists, nts.cert_readable)), "nts_server_files"],
      ["Privater Schlüssel", el("span", {}, el("span", { class: "mono", text: `${nts.key || "–"} ` }), fileState(nts.key_exists, nts.key_readable)), "nts_server_files"],
      ["Gültig bis", expiry(nts), "nts_cert_expiry"],
      ["Name im Zertifikat", (nts.names || []).join(", ") || nts.subject || "–", "nts_cert_subject"],
      nts.name ? ["Servername für Clients", serverName(nts), "nts_server_name"] : null,
      nts.cert_issuer ? ["Aussteller", String(nts.cert_issuer), "nts_cert_issuer"] : null,
    ]),
    kv([
      ["Schlüsselaustausch angenommen", fmtNumber(nts.ke_accepted), "nts_ke_server"],
      ["Schlüsselaustausch abgelehnt", fmtNumber(nts.ke_dropped), "nts_ke_server"],
      ["Authentifizierte Anfragen", fmtNumber(nts.authenticated_packets), "nts_auth_packets"],
    ])));
}

export function render(ctx) {
  const { status, history } = ctx;
  const sources = status.sources || [];
  const expanded = ctx.uiState.expandedSources || (ctx.uiState.expandedSources = new Set());

  const rows = [];
  // Spalte „Grund“ nur, wenn er bei mindestens einer Quelle mehr sagt als „Zustand“.
  const showReason = sources.some(reasonDiffers);
  const columns = showReason ? 10 : 9;
  for (const source of sources) {
    const open = expanded.has(source.name);
    const label = source.hostname || source.name;
    const toggle = () => { if (open) expanded.delete(source.name); else expanded.add(source.name); ctx.rerender(); };
    const nts = source.auth && source.auth.mode === "NTS";
    rows.push(el("tr", { class: `src-row${open ? " is-open" : ""}`, tabindex: 0, "aria-expanded": open ? "true" : "false",
      onclick: (e) => { if (!e.target.closest("button.info")) toggle(); },
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } } },
      el("td", {}, el("div", { class: "src-name" }, el("span", { class: "chev", "aria-hidden": "true", text: open ? "▾" : "▸" }),
        el("div", {}, el("div", { class: "mono", text: label }),
          source.hostname ? el("div", { class: "sub mono", text: source.name }) : null)),
        nts ? badge(source.authenticated ? "NTS ✓" : "NTS", source.authenticated ? "good" : "warn") : null),
      el("td", { text: TYPE[source.mode] || source.mode_label || "–" }),
      el("td", { class: "num", text: source.stratum ?? "–" }),
      el("td", { class: "num", text: fmtLogInterval(source.poll) }),
      el("td", {}, reachRegister(source.reach || 0)),
      el("td", { class: "num", text: fmtSeconds(source.offset, 3, true) }),
      el("td", { class: "num", text: isNum(source.std_dev) ? fmtSeconds(source.std_dev) : "–" }),
      el("td", { class: "num", text: uncertainty(source) }),
      el("td", {}, stateBadge(source)),
      showReason ? el("td", {}, reasonCell(source)) : null));
    if (open) rows.push(el("tr", { class: "src-detail" }, el("td", { colspan: columns }, details(source))));
  }

  const head = [
    ["Quelle", "hostname_vs_ip"], ["Typ", "source_type"], ["Stratum", "stratum", "num"], ["Intervall", "poll", "num"],
    ["Letzte 8", "reach"], ["Offset", "source_offset", "num"], ["Jitter", "jitter", "num"],
    ["Unsicherheit", "interval", "num"], ["Zustand", "state_combined"], showReason ? ["Grund", "select_reason"] : null,
  ].filter(Boolean);
  const table = el("div", { class: "table-scroll" }, el("table", { class: "sources-table" },
    el("thead", {}, el("tr", {}, head.map(([label, help, cls]) => el("th", { class: cls || null },
      el("span", { text: label }), infoButton(help, label))))),
    el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: columns, class: "empty-note", text: "Keine Zeitquellen konfiguriert." })))));

  // Offset je Quelle
  const names = [...new Set(history.flatMap((s) => Object.keys(s.sources || {})))];
  const hostOf = (name) => (sources.find((s) => s.name === name) || {}).hostname || name;
  // Mitglieder eines Pools melden alle den Pool-Namen: dann die Adresse dazu (Legende) bzw. nur sie (Linienende),
  // sonst wären beide mehrdeutig.
  const shared = (name) => names.some((other) => other !== name && hostOf(other) === hostOf(name));
  const labelOf = (name) => (shared(name) ? `${hostOf(name)} (${name})` : hostOf(name));
  const hidden = ctx.uiState.hiddenSeries || (ctx.uiState.hiddenSeries = new Set());
  // Farbe fest je Quelle (charts.colorFor), Referenzuhren (GPS/PPS) in der Signalfarbe.
  const isRefclock = (name) => (sources.find((s) => s.name === name) || {}).mode === "#";
  const offsetSeries = names.map((name) => ({ id: name, label: labelOf(name), short: shared(name) ? name : null, signal: isRefclock(name),
    points: history.map((s) => [s.t, (s.sources || {})[name]?.o ?? null]) }));
  // Noch kein Verlauf → eine Zeile „sammelt seit …“ statt einer leeren Fläche. Nie „flach“:
  // Offsets mehrerer Quellen sind auch bei kleiner Spannweite aussagekräftig.
  const offsetCard = chartCard(ctx, {
    title: "Offset je Quelle", help: "source_offset", key: "sources-offset", series: offsetSeries, flat: false,
    sub: "Wie weit jede Quelle von der Systemuhr entfernt ist. Liegen alle Netzwerkquellen beieinander und eine weicht konstant ab, ist das ein Kalibrierfall (typisch: USB-GPS). Klick auf die Legende blendet Quellen aus.",
    actions: rangeButtons(ctx.range, ctx.setRange), since: history.length ? history[0].t : null,
    zone: ctx.status.system?.tz_name || isNum(ctx.status.system?.utc_offset) ? ctx.status.system : null,
    draw: (host) => lineChart(host, {
      series: offsetSeries,
      format: (v) => fmtSeconds(v, 3, true), axisFormat: axisSeconds, height: 260, hidden, range: ctx.range, end: ctx.status.system?.time,
      ariaLabel: "Offset je Quelle",
      onToggle: (id) => { if (hidden.has(id)) hidden.delete(id); else hidden.add(id); ctx.rerender(); },
      emptyText: "Noch zu wenige Messwerte – der Verlauf füllt sich alle paar Sekunden",
    }),
  });

  return [
    card("Zeitquellen", { help: "source_type", sub: "Klick auf eine Zeile zeigt alles, was chrony über die Quelle weiß." }, table),
    ntsServerCard(status.nts_server),
    offsetCard,
    card("So wählt chrony seine Quellen", { class: "explain", help: "select_reason",
      sub: tr("pages.sources.steps_line") },
      el("details", { class: "explain-more" }, el("summary", { text: tr("pages.sources.steps") }),
      el("ol", { class: "steps" },
        el("li", {}, rich("**Messen**: Jede Quelle wird regelmäßig gefragt. Aus Offset, Laufzeit und Streuung entsteht ein **Vertrauensbereich**, in dem die echte Zeit laut dieser Quelle liegt.")),
        el("li", {}, rich("**Mehrheit finden**: chrony sucht den Bereich, in dem sich die meisten Vertrauensbereiche überschneiden. Wer nicht dazugehört, ist **Falseticker (x)** und wird ignoriert.")),
        el("li", {}, rich("**Beste wählen**: Unter den übrigen wird die beste Quelle **ausgewählt** (Zeichen `*`) – kleinste Unsicherheit, stabil, ohne Hin-und-her-Springen.")),
        el("li", {}, rich("**Kombinieren**: Quellen, die fast so gut sind, werden **kombiniert (+)** und mitgemittelt. Deutlich schlechtere bleiben **nicht kombiniert (−)** – sie stehen als Reserve bereit."))),
      emptyState("Bevorzugte Quellen („prefer“) gewinnen, solange sie plausibel sind. „Nur beobachten“ („noselect“) misst ohne zu nutzen."))),
  ].filter(Boolean);
}
