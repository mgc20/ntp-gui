import { el, apiGet, fmtDuration, fmtNumber, fmtRate, fmtLogInterval, fmtSeconds, isNum, rich } from "../util.js";
import { card, tile, info, badge, rangeButtons, emptyNote, toast, copyButton } from "../ui.js";
import { lineChart, stepDecimals } from "../charts.js";
import { requestRate } from "./overview.js";

// Platzhalter, wenn die LAN-Adresse nicht bekannt ist – in den Beispielen gut sichtbar.
const IP_PLACEHOLDER = "<IP-des-Servers>";

// Loopback und das Standard-Docker-Bridge-Netz (172.17.0.0/16) sind von anderen
// Geräten im LAN aus nicht erreichbar – solche Adressen nie als Serveradresse zeigen.
function usableAddress(addr) {
  if (!addr) return false;
  const a = String(addr).toLowerCase().replace(/^\[|\]$/g, "");
  if (a === "localhost" || a === "::1" || a === "0.0.0.0" || a.startsWith("127.")) return false;
  if (a.startsWith("172.17.")) return false;
  return true;
}

function isIp(text) {
  const a = String(text || "").replace(/^\[|\]$/g, "");
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(a) || (/^[0-9a-f:]+$/i.test(a) && a.includes(":"));
}

// Adresse, unter der Clients diesen Server erreichen – oder null, wenn keine bekannt ist.
function serverAddress(status) {
  const host = window.location.hostname;
  if (usableAddress(host) && isIp(host)) return host.replace(/^\[|\]$/g, "");
  const addresses = (status.system || {}).addresses || [];
  const lan = addresses.find((a) => /^\d+\.\d+\.\d+\.\d+$/.test(a) && usableAddress(a));
  if (lan) return lan;
  // Ein Hostname im Browser ist besser als nichts – für DHCP-Snippets, nicht für DNS-Umschreibung.
  return usableAddress(host) ? host : null;
}

function snippet(title, code) {
  const pre = el("pre", { class: "code", text: code });
  const copy = copyButton(code, pre);
  return el("div", { class: "snippet" }, el("div", { class: "snippet-head" }, el("strong", { text: title }), copy), pre);
}

// --- Abweichung der Client-Uhren ---------------------------------------------
const STATE_TONE = { ok: "good", "falsche Uhr": "crit", verschleiert: "muted", "ohne Zeitstempel": "muted" };
const STATE_SHORT = { ok: "messbar", "falsche Uhr": "messbar", verschleiert: "verschleiert",
  "ohne Zeitstempel": "ohne Zeitstempel" };

function fmtOffset(value) {
  if (!isNum(value)) return "–";
  const abs = Math.abs(value);
  if (abs >= 86400) return `${value > 0 ? "+" : "−"}${fmtDuration(abs)}`;
  return fmtSeconds(value, 3, true);
}

function offsetTone(value) {
  if (!isNum(value)) return "muted";
  const abs = Math.abs(value);
  return abs < 0.005 ? "good" : abs < 0.5 ? "warn" : "crit";
}

function offsetData(ctx) {
  // Hat der Server die Messwerte in /api/status gemischt, die nehmen; sonst eigener Endpunkt.
  if (ctx.status.clientmon) return ctx.status.clientmon;
  return ctx.data("clientoffsets", "/api/clients/offsets", 10);
}

function offsetCells(entry) {
  if (!entry) {
    return [el("td", { class: "num muted", text: "–" }), el("td", { class: "muted", text: "–" })];
  }
  const tone = entry.measurable ? offsetTone(entry.ewma) : "muted";
  const range = entry.measurable && isNum(entry.min) && isNum(entry.max)
    ? `${fmtOffset(entry.min)} … ${fmtOffset(entry.max)} · ${fmtNumber(entry.count)} Messungen` : null;
  return [
    el("td", { class: "num" }, entry.measurable
      ? el("span", { class: "offset-value", "data-tone": tone, title: range || null, text: fmtOffset(entry.ewma) })
      : el("span", { class: "muted", text: "–" })),
    el("td", {}, badge(STATE_SHORT[entry.state] || "–", STATE_TONE[entry.state] || "muted", entry.state_text)),
  ];
}

function clientmonNote(mon) {
  if (mon === undefined) return null;
  if (!mon || !mon.available) {
    return el("p", { class: "clientmon-note" }, el("span", { text: "Messung der Uhren nicht verfügbar: " }),
      el("span", { text: (mon && mon.reason) || "Endpunkt nicht erreichbar." }), " ", info("clientmon_status"));
  }
  if (mon.reason) {
    return el("p", { class: "clientmon-note" }, el("span", { text: mon.reason }), " ", info("clientmon_status"));
  }
  return null;
}

// --- Zeitserver erzwingen ------------------------------------------------------
let checkResult = null;
let checkBusy = false;

async function runCheck(ctx, ip) {
  if (checkBusy) return;
  checkBusy = true;
  ctx.rerender();
  try {
    checkResult = await apiGet(`/api/enforce/check${ip ? `?ip=${encodeURIComponent(ip)}` : ""}`);
    if (checkResult.cached) toast(`Letzte Prüfung ist noch frisch – neu prüfen in ${Math.ceil(checkResult.retry_after || 30)} s`, "warn");
  } catch (error) {
    toast(`Prüfung fehlgeschlagen: ${error.message}`, "crit");
  }
  checkBusy = false;
  ctx.rerender();
}

const VERDICT_LABEL = {
  dns_rewrite: "umgeschrieben", answered_by_us: "antwortet wie dieser Server", dns_partial: "teilweise",
  not_redirected: "nicht umgeschrieben", no_reply: "keine Antwort", dns_error: "DNS-Fehler",
  direct: "erreicht echten Server", loop: "Schleife",
};

function checkView(result) {
  if (!result) return null;
  const row = (label, item) => el("li", { class: "enforce-row", "data-level": item.level },
    el("div", { class: "enforce-row-head" },
      el("span", { class: "mono", text: label }),
      badge(VERDICT_LABEL[item.state] || item.state || "–", item.level === "info" ? "muted" : item.level)),
    el("p", { text: item.verdict || "" }));
  return el("div", { class: "enforce-result" },
    el("div", { class: "verdict", "data-tone": result.level === "info" ? null : result.level },
      el("div", { class: "verdict-label" }, el("span", { text: "Ergebnis" }), info("enforce_verdict")),
      el("p", { text: result.summary || "" })),
    (result.loops || []).length ? el("ul", { class: "enforce-list" },
      result.loops.map((l) => row(l.host, { ...l, state: "loop" }))) : null,
    el("h3", { class: "mini-head", text: "Namen (über den DNS-Server dieses Containers)" }),
    el("ul", { class: "enforce-list" }, (result.hosts || []).map((h) => row(h.host, h))),
    el("h3", { class: "mini-head", text: "ntp-gui selbst → öffentliche Server" }),
    el("ul", { class: "enforce-list" }, (result.public || []).map((p) => row(`${p.label} (${p.ip})`, p))),
    result.ours_note ? emptyNote(result.ours_note) : null,
    emptyNote(result.resolver_note || ""));
}

function selfTest(status, ip) {
  const t = status.tracking || {};
  const stratum = isNum(t.stratum) ? String(t.stratum) : "?";
  const ref = t.ref_id || "?";
  const target = "time.google.com";
  // Feste Adresse von time.google.com: Ein Name würde die DNS-Umschreibung testen, nicht die Firewall.
  const natTarget = "216.239.35.0";
  return el("div", { class: "enforce-selftest" },
    el("h3", { class: "mini-head" }, "Selbsttest auf einem Gerät ", info("enforce_selftest")),
    el("p", { class: "card-sub" }, rich(`Frage auf einem Gerät einen **öffentlichen** Server ab. Kommt die Antwort mit `
      + `**Stratum ${stratum}** und **Referenz-ID ${ref}**, hat die Umleitung gegriffen – das sind die Werte `
      + `dieses Servers. **Per Name** prüfst du die DNS-Umschreibung, **per IP-Adresse** die Firewall-Umleitung `
      + `(NAT) – der Name wird ja schon vom DNS umgeschrieben.`)),
    el("div", { class: "snippets" },
      snippet("DNS-Umschreibung – Windows", `w32tm /stripchart /computer:${target} /samples:1 /packetinfo`),
      snippet("DNS-Umschreibung – macOS/Linux", `sntp -d ${target}`),
      snippet("Firewall-Umleitung (NAT) – Windows", `w32tm /stripchart /computer:${natTarget} /samples:3 /packetinfo`),
      snippet("Firewall-Umleitung (NAT) – macOS/Linux", `sntp -d ${natTarget}`),
      snippet("Linux mit chrony", `chronyc tracking\nchronyc ntpdata   # Stratum und Referenz-ID je Quelle`),
      snippet("Gegenprobe: direkt an ntp-gui", ip ? `sntp -d ${ip}` : `sntp -d ${IP_PLACEHOLDER}`)),
    el("p", { class: "card-sub" }, rich("**Zeitüberschreitung beim NAT-Test**, aber das Gerät erscheint oben in der "
      + "Client-Liste? Dann kommt die Anfrage bei ntp-gui an, die Antwort aber nicht zurück: das "
      + "**Hairpin-Problem** (Gerät und ntp-gui im selben Netz). Abhilfe: Masquerade-/SNAT-Regel oder ein "
      + "eigenes VLAN für ntp-gui – siehe Anleitung unten.")));
}

function enforceSection(ctx, ip) {
  const query = ip && isIp(ip) ? `&ip=${encodeURIComponent(ip)}` : "";
  const data = ctx.data("enforce", `/api/enforce/snippets?system=all${query}`, 300);
  if (data === undefined) {
    return card("Zeitserver erzwingen", { help: "enforce" }, emptyNote("Lade Anleitungen …"));
  }
  if (!data || !Array.isArray(data.snippets)) {
    return card("Zeitserver erzwingen", { help: "enforce" }, emptyNote("Anleitungen nicht verfügbar."));
  }
  const systems = data.snippets;
  const selected = systems.find((s) => s.id === ctx.uiState.enforceSystem) || systems[0];
  // Das ⓘ sitzt neben der Gruppenbeschriftung – hinter den Knöpfen rutschte es auf schmalen
  // Bildschirmen allein in eine eigene Zeile.
  const group = (kind, label, help) => el("div", { class: "enforce-tabs", role: "group", "aria-label": label },
    el("span", { class: "enforce-kind" }, label, " ", info(help, label)),
    systems.filter((s) => s.kind === kind).map((s) => el("button", {
      type: "button", class: `range${s.id === selected.id ? " is-active" : ""}`, text: s.title,
      "aria-pressed": s.id === selected.id ? "true" : "false",
      onclick: () => { ctx.uiState.enforceSystem = s.id; ctx.rerender(); },
    })));
  const names = (data.hostnames || []).map((h) => h.host);
  const checkButton = el("button", { type: "button", class: "button primary", disabled: checkBusy || null,
    text: checkBusy ? "Prüfe …" : "Prüfen", onclick: () => runCheck(ctx, data.server_ip) });

  return card("Zeitserver erzwingen", { help: "enforce", id: "erzwingen",
    sub: "Für Geräte, die den Zeitserver aus DHCP ignorieren und fest eingebaute Namen wie time.windows.com "
      + "oder pool.ntp.org fragen. Wähle dein System – die Anleitung ist mit der Adresse dieses Servers ausgefüllt"
      + (data.server_ip ? ` (**${data.server_ip}**).` : ", sobald sie bekannt ist – bis dahin steht dort **<IP-des-Servers>**."),
    actions: checkButton },
    // „Nie umschreiben: NTS-Server“ kommt mit der Begründung aus dem Server-Text (enforce.EXPLAIN).
    el("div", { class: "enforce-explain" }, (data.explain || []).map((item) => el("details", {},
      el("summary", {}, item.title, /NTS/.test(item.title || "") ? [" ", info("enforce_nts")] : null),
      el("p", {}, rich(item.text))))),
    el("div", { class: "enforce-tabbar" },
      el("div", { class: "enforce-group" }, group("dns", "DNS-Umschreibung", "enforce_dns")),
      el("div", { class: "enforce-group" }, group("nat", "Firewall-Umleitung", "enforce_nat"))),
    el("div", { class: "enforce-panel" },
      el("p", { class: "card-sub" }, rich(selected.intro || "")),
      el("div", { class: "enforce-blocks" }, (selected.blocks || []).map((b) => snippet(b.title, b.code))),
      (selected.notes || []).length ? el("ul", { class: "enforce-notes" },
        selected.notes.map((n) => el("li", {}, rich(n)))) : null,
      selected.kind === "nat" ? el("p", { class: "enforce-hint" }, "Warum Masquerade? ", info("enforce_hairpin")) : null),
    el("details", { class: "enforce-names" },
      el("summary", {}, `Umgeleitete Namen (${fmtNumber(names.length)}) `, info("enforce_hostnames")),
      el("p", { class: "mono enforce-hostlist", text: names.join("  ") }),
      (data.skipped || []).length ? el("ul", { class: "enforce-notes" }, data.skipped.map((s) =>
        el("li", {}, el("span", { class: "mono", text: s.host }), el("span", { text: ` – nicht übernommen: ${s.reason}` })))) : null),
    el("details", { class: "enforce-names" },
      el("summary", {}, "Geräte ohne NTP (Fernseher) ", info("enforce_not_ntp")),
      el("ul", { class: "enforce-notes" }, (data.not_ntp || []).map((n) =>
        el("li", {}, el("strong", { text: n.label }), el("span", { text: ` ${n.text}` }))))),
    el("div", { class: "enforce-check" },
      el("h3", { class: "mini-head" }, "Prüfung ", info("enforce_check")),
      checkResult ? checkView(checkResult)
        : emptyNote("„Prüfen“ fragt ein paar bekannte Namen über den DNS-Server dieses Containers ab und schickt je eine "
          + "NTP-Anfrage an die Antwort und an zwei öffentliche Server. Es werden keine Daten übertragen.")),
    selfTest(ctx.status, data.server_ip));
}

export function render(ctx) {
  const { status, history } = ctx;
  const clients = status.clients || [];
  const stats = status.serverstats || {};
  const rate = requestRate(history);
  const lastRate = rate.length ? rate[rate.length - 1][1] : null;
  const filter = (ctx.uiState.clientFilter || "").toLowerCase();
  const knownIp = serverAddress(status);
  const ip = knownIp || IP_PLACEHOLDER;
  const mon = offsetData(ctx);
  const offsets = (mon && mon.clients) || {};
  const measured = Object.values(offsets).filter((c) => c.measurable && isNum(c.ewma));
  const worst = measured.reduce((acc, c) => (acc === null || Math.abs(c.ewma) > Math.abs(acc) ? c.ewma : acc), null);

  // Geräte aus chronyd, ergänzt um solche, die nur die passive Messung kennt.
  const known = new Set(clients.map((c) => c.address));
  const rows = clients.concat(Object.keys(offsets).filter((a) => !known.has(a)).map((address) => ({ address })));

  const input = el("input", { type: "search", placeholder: "Filtern …", value: ctx.uiState.clientFilter || "",
    "aria-label": "Clients filtern" });
  const bodyRows = (needle) => rows.filter((c) => !needle || (c.address || "").toLowerCase().includes(needle))
    .sort((a, b) => (a.ntp_last_rx ?? 1e12) - (b.ntp_last_rx ?? 1e12))
    .map((c) => el("tr", {},
      el("td", { class: "mono", text: c.address }),
      el("td", { class: "num", text: fmtNumber(c.ntp_packets) }),
      el("td", { class: "num", text: fmtNumber(c.ntp_dropped) }),
      el("td", { class: "num", text: fmtLogInterval(c.ntp_interval) }),
      el("td", { class: "num", text: isNum(c.ntp_last_rx) ? `vor ${fmtDuration(c.ntp_last_rx)}` : "–" }),
      ...offsetCells(offsets[c.address])));
  const tbody = el("tbody", {}, bodyRows(filter));
  // Nur die Zeilen tauschen – ein Neuaufbau der Seite würde dem Feld den Fokus nehmen.
  input.addEventListener("input", () => {
    ctx.uiState.clientFilter = input.value;
    tbody.replaceChildren(...bodyRows(input.value.toLowerCase()));
  });
  const table = el("div", { class: "table-scroll" }, el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "Adresse ", info("client_address")),
      el("th", { class: "num" }, "Anfragen ", info("client_packets")),
      el("th", { class: "num" }, "Verworfen ", info("client_dropped")),
      el("th", { class: "num" }, "Intervall ", info("client_interval")),
      el("th", { class: "num" }, "Zuletzt ", info("client_last")),
      el("th", { class: "num" }, "Uhr geht falsch um ", info("client_offset")),
      el("th", {}, "messbar ", info("client_measurable")))),
    tbody));

  const chartHost = el("div", { class: "chart-host" });
  ctx.afterRender(() => lineChart(chartHost, {
    series: [{ id: "rate", label: "pro Minute", color: "var(--accent)", points: rate }],
    format: (v) => `${fmtRate(v)}/min`, axisFormat: (v, step) => fmtNumber(v, stepDecimals(step)), area: true, min: 0,
    range: ctx.range, end: ctx.status.system?.time, ariaLabel: "Beantwortete Anfragen pro Minute",
    emptyText: "Noch keine Anfragen gemessen",
  }));

  const setup = card("Clients einrichten", { help: "dhcp42",
    sub: `Adresse dieses Servers: ${knownIp ? `**${knownIp}**` : "**unbekannt** – setze die IP des Hosts ein"}. Am bequemsten per DHCP Option 42 – dann übernehmen viele Geräte den Server automatisch.` },
    el("div", { class: "snippets" },
      snippet("dnsmasq / Pi-hole", `dhcp-option=42,${ip}`),
      snippet("ISC dhcpd", `option ntp-servers ${ip};`),
      snippet("Kea DHCPv4", `"option-data": [ { "name": "ntp-servers", "data": "${ip}" } ]`),
      snippet("MikroTik RouterOS", `/ip dhcp-server network set [find] ntp-server=${ip}`),
      snippet("OPNsense / pfSense", `Dienste → DHCP-Server → Interface → NTP-Server 1: ${ip}`),
      snippet("UniFi", `Einstellungen → Netzwerke → DHCP → NTP-Server: ${ip}`)),
    el("h3", { class: "mini-head", text: "Geräte, die Option 42 ignorieren" }),
    el("div", { class: "snippets" },
      snippet("Windows (als Administrator)", `w32tm /config /manualpeerlist:"${ip},0x8" /syncfromflags:manual /update\nw32tm /resync /force\nw32tm /query /status`),
      snippet("Linux mit systemd-timesyncd", `# /etc/systemd/timesyncd.conf\n[Time]\nNTP=${ip}\n\nsudo systemctl restart systemd-timesyncd\ntimedatectl timesync-status`),
      snippet("Linux mit chrony", `# /etc/chrony/chrony.conf (bzw. /etc/chrony.conf)\nserver ${ip} iburst\n\nsudo systemctl restart chrony\nchronyc sources`),
      snippet("macOS", `sudo systemsetup -setnetworktimeserver ${ip}\nsudo sntp -sS ${ip}`)),
    emptyNote("Die FRITZ!Box verteilt Option 42 nicht frei – dort Geräte direkt einstellen oder einen anderen DHCP-Server (z. B. Pi-hole) nutzen. "
      + "Für Geräte mit fest eingebautem Server hilft **Zeitserver erzwingen** weiter unten."));

  return [
    el("div", { class: "stat-row" },
      tile({ label: "Clients", help: "client_packets", value: fmtNumber(rows.length), tone: rows.length ? "good" : "muted",
        note: "seit dem Start von chrony" }),
      tile({ label: "Anfragen", help: "served_rate", value: isNum(lastRate) ? fmtNumber(lastRate, 1) : "–", unit: "/min",
        tone: "muted", note: `${fmtNumber(stats.ntp_packets_received)} insgesamt` }),
      tile({ label: "Verworfen", help: "client_dropped", value: fmtNumber(stats.ntp_packets_dropped ?? 0),
        tone: (stats.ntp_packets_dropped || 0) > 0 ? "warn" : "muted", note: "z. B. durch Begrenzung" }),
      tile({ label: "Größte Abweichung", help: "client_offset", value: fmtOffset(worst),
        tone: offsetTone(worst), note: mon && mon.available
          ? `${fmtNumber(measured.length)} von ${fmtNumber(Object.keys(offsets).length)} Geräten messbar`
          : "Messung nicht aktiv" })),
    card("Geräte, die diesen Server fragen", { help: "client_packets", actions: input,
      sub: rows.length ? null : "Noch keine Anfragen. Sobald die Adresse verteilt ist, erscheinen die Geräte hier." },
      rows.length ? table : null, clientmonNote(mon)),
    card("Anfragen pro Minute", { help: "served_rate", actions: rangeButtons(ctx.range, ctx.setRange) }, chartHost),
    setup,
    enforceSection(ctx, knownIp && isIp(knownIp) ? knownIp : null),
  ];
}

export { rich };
