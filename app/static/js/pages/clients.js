import { t as tr } from "../i18n.js";
import { el, apiGet, apiPost, fmtDuration, fmtNumber, fmtRate, fmtLogInterval, isNum, rich } from "../util.js";
import { card, statCard, infoButton, badge, rangeButtons, emptyState, toast, copyButton, loadingOr, loadingText, explainLine } from "../ui.js";
import { lineChart, stepDecimals } from "../charts.js";
import { requestRate, recentRateInfo, rateWindowText } from "./overview.js";
import { renderDetail, fmtOffset, offsetTone, fmtInterval, clientHref, STATE_TONE, STATE_SHORT, qualityBadge, fmtDrift } from "./clientdetail.js";
import { renderPass } from "./clientpass.js";

// Platzhalter, wenn die LAN-Adresse nicht bekannt ist – in den Beispielen gut sichtbar.
export const IP_PLACEHOLDER = "<IP-des-Servers>";

// Loopback und das Standard-Docker-Bridge-Netz (172.17.0.0/16) sind von anderen
// Geräten im LAN aus nicht erreichbar – solche Adressen nie als Serveradresse zeigen.
// Auch im Willkommens-Assistenten (pages/setup.js): Loopback und Docker-Brücke helfen keinem Gerät im Netz.
export function usableAddress(addr) {
  if (!addr) return false;
  const a = String(addr).toLowerCase().replace(/^\[|\]$/g, "");
  if (a === "localhost" || a === "::1" || a === "0.0.0.0" || a.startsWith("127.")) return false;
  if (a.startsWith("172.17.")) return false;
  return true;
}

// Rechnername des Servers, den Geräte im LAN auflösen können – nicht die Container-ID, die Docker im Bridge-Netz
// ohne „hostname:“ vergibt (12 oder 64 Hex-Zeichen, nach jedem Neuerstellen anders), und nicht localhost.
export function usableHostname(name) {
  const host = String(name || "").trim().toLowerCase();
  if (!host || host === "localhost" || host.startsWith("localhost.")) return false;
  return !/^(?:[0-9a-f]{12}|[0-9a-f]{64})$/.test(host);
}

function isIp(text) {
  const a = String(text || "").replace(/^\[|\]$/g, "");
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(a) || (/^[0-9a-f:]+$/i.test(a) && a.includes(":"));
}

// Adresse, unter der Clients diesen Server erreichen – oder null, wenn keine bekannt ist.
export function serverAddress(status) {
  const host = window.location.hostname;
  if (usableAddress(host) && isIp(host)) return host.replace(/^\[|\]$/g, "");
  const addresses = (status.system || {}).addresses || [];
  const lan = addresses.find((a) => /^\d+\.\d+\.\d+\.\d+$/.test(a) && usableAddress(a));
  if (lan) return lan;
  // Ein Hostname im Browser ist besser als nichts – für DHCP-Snippets, nicht für DNS-Umschreibung.
  return usableAddress(host) ? host : null;
}

// Schnipsel für Geräte, die Option 42 ignorieren – auch im Willkommens-Assistenten (pages/setup.js).
export function clientSnippets(ip) {
  return [
    snippet("Windows (als Administrator)", `w32tm /config /manualpeerlist:"${ip},0x8" /syncfromflags:manual /update\nw32tm /resync /force\nw32tm /query /status`),
    snippet("Linux mit systemd-timesyncd", `# /etc/systemd/timesyncd.conf\n[Time]\nNTP=${ip}\n\nsudo systemctl restart systemd-timesyncd\ntimedatectl timesync-status`),
    snippet("Linux mit chrony", `# /etc/chrony/chrony.conf (bzw. /etc/chrony.conf)\nserver ${ip} iburst\n\nsudo systemctl restart chrony\nchronyc sources`),
    snippet("macOS", `sudo systemsetup -setnetworktimeserver ${ip}\nsudo sntp -sS ${ip}`),
  ];
}

export function snippet(title, code) {
  const pre = el("pre", { class: "code", text: code });
  const copy = copyButton(code, pre);
  return el("div", { class: "snippet" }, el("div", { class: "snippet-head" }, el("strong", { text: title }), copy), pre);
}

// --- Abweichung der Client-Uhren ---------------------------------------------
// Formatierung und Zustände teilt sich die Liste mit der Detailseite (clientdetail.js).

function offsetData(ctx) {
  // Hat der Server die Messwerte in /api/status gemischt, die nehmen; sonst eigener Endpunkt.
  if (ctx.status.clientmon) return ctx.status.clientmon;
  return ctx.data("clientoffsets", "/api/clients/offsets", 10);
}

// Inhalt der Spalten „Uhr geht falsch um“ und „messbar“ – die Zelle (<td> bzw. <dd>) baut render().
function offsetValue(entry) {
  if (!entry || !entry.measurable) return el("span", { class: "muted", text: "–" });
  const range = isNum(entry.min) && isNum(entry.max)
    ? `${fmtOffset(entry.min)} … ${fmtOffset(entry.max)} · ${fmtNumber(entry.count)} Messungen` : null;
  return el("span", { class: "offset-value", "data-tone": offsetTone(entry.ewma), title: range, text: fmtOffset(entry.ewma) });
}

function offsetState(entry) {
  if (!entry) return el("span", { class: "muted", text: "–" });
  return badge(STATE_SHORT[entry.state] || "–", STATE_TONE[entry.state] || "muted", entry.state_text);
}

function clientmonNote(mon) {
  if (mon === undefined) return null;
  if (!mon || !mon.available) {
    return el("p", { class: "clientmon-note" }, el("span", { text: "Messung der Uhren nicht verfügbar: " }),
      el("span", { text: (mon && mon.reason) || "Endpunkt nicht erreichbar." }), " ", infoButton("clientmon_status"));
  }
  if (mon.reason) {
    return el("p", { class: "clientmon-note" }, el("span", { text: mon.reason }), " ", infoButton("clientmon_status"));
  }
  return null;
}

// --- Netzüberblick ---------------------------------------------------------------
const BIN_TONE = { lt1ms: "good", "1-10ms": "good", "10-100ms": "warn", "0.1-1s": "warn", gt1s: "crit", wrong: "crit" };

function clientLink(item) {
  return el("a", { href: clientHref(item.address), class: "client-link" },
    item.name ? el("span", { text: item.name }) : el("span", { class: "mono", text: item.address }),
    item.name ? el("span", { class: "mono client-sub", text: ` ${item.address}` }) : null);
}

function miniList(title, help, items, total, cell, empty) {
  return el("div", { class: "net-list" },
    el("h3", { class: "mini-head" }, el("span", { text: title }), infoButton(help, title),
      total > items.length ? el("span", { class: "muted", text: `(${fmtNumber(items.length)} von ${fmtNumber(total)})` }) : null),
    items.length ? el("ul", { class: "net-items" }, items.map((item) => el("li", {}, clientLink(item), cell(item))))
      : el("p", { class: "field-help", text: empty }));
}

function overviewCard(ctx) {
  const data = ctx.data("clientoverview", "/api/clients/overview", 15);
  if (data === undefined) return card("Netzüberblick", { help: "clients_overview" }, loadingOr(ctx, "clientoverview", "/api/clients/overview", "Überblick"));
  if (!data || !Array.isArray(data.histogram)) {
    return card("Netzüberblick", { help: "clients_overview" }, emptyState("Überblick nicht verfügbar."));
  }
  if (!data.total) return null;
  const max = Math.max(1, ...data.histogram.map((b) => b.count));
  const hist = el("div", { class: "net-hist", role: "list", "aria-label": "Verteilung der Abweichungen" },
    data.histogram.map((b) => el("div", { class: "net-bin", role: "listitem", "data-tone": BIN_TONE[b.key] || "muted",
      "aria-label": `${b.label}: ${b.count} Geräte` },
    el("span", { class: "net-bin-label", text: b.label }),
    el("span", { class: "net-bin-track" }, el("span", { class: "net-bin-fill", style: `width:${(b.count / max) * 100}%` })),
    el("span", { class: "net-bin-count", text: fmtNumber(b.count) }))));
  return card("Netzüberblick", { help: "clients_overview",
    sub: `${fmtNumber(data.measured)} von ${fmtNumber(data.total)} Geräten messbar`
      + (data.unmeasurable ? ` – ${fmtNumber(data.unmeasurable)} verschleiern ihre Zeit oder senden keine.` : ".") },
  el("div", { class: "net-grid" },
    el("div", {},
      el("h3", { class: "mini-head" }, el("span", { text: "Wie weit gehen die Uhren falsch?" }), infoButton("clients_histogram")),
      hist),
    miniList("Größte Abweichung", "clients_worst", data.worst || [], (data.worst || []).length,
      (item) => el("span", { class: "offset-value", "data-tone": offsetTone(item.offset), text: fmtOffset(item.offset) }),
      "Noch kein Gerät messbar."),
    miniList("Verstummt", "clients_silent", data.silent || [], data.silent_total || 0,
      (item) => el("span", { class: "field-help", text: item.reason }),
      "Alle bekannten Geräte fragen weiter."),
    miniList("Fragt auffällig oft", "clients_chatty", data.chatty || [], data.chatty_total || 0,
      (item) => el("span", { class: "field-help", text: `alle ${fmtInterval(item.interval)} (${fmtNumber(item.rate_per_min, 0)}/min)` }),
      "Kein Gerät fragt öfter als alle 8 s."),
    worstClocks(ctx)));
}

// --- Clients 3 (1.5): Uhrgüte, Gruppen ----------------------------------------------
function qualityData(ctx) {
  return ctx.data("clientquality", "/api/clients/quality", 30);
}

function worstClocks(ctx) {
  const data = qualityData(ctx);
  const items = (data && data.worst) || [];
  return miniList("Schlechteste Uhren im Haus", "clients_worst_clocks", items, data?.rated || 0,
    (item) => el("span", { class: "worst-clock" }, qualityBadge(item),
      isNum(item.drift_ppm) || isNum(item.drift_bound_ppm)
        ? el("span", { class: "field-help", text: ` ${fmtDrift(item)}` }) : null),
    data === undefined ? loadingText(ctx, "clientquality", "/api/clients/quality", "Uhrgüte") : "Noch kein Gerät bewertbar (es braucht mindestens 4 Messungen).");
}

const GROUP_BYS = [["group", "Gruppe"], ["vlan", "VLAN"], ["software", "Software"]];
const MEMBERS_SHOWN = 100;

function pct(value) {
  return isNum(value) ? `${fmtNumber(value * 100, 0)} %` : "–";
}

function groupForm(ctx, data) {
  const draft = ctx.uiState.groupDraft || (ctx.uiState.groupDraft = { name: "", network: "" });
  const name = el("input", { type: "text", maxlength: "40", value: draft.name, placeholder: "z. B. IoT",
    "aria-label": "Name der Gruppe" });
  const network = el("input", { type: "text", maxlength: "64", value: draft.network, placeholder: "z. B. 10.0.30.0/24",
    "aria-label": "Netz der Gruppe", class: "mono" });
  name.addEventListener("input", () => { draft.name = name.value; });
  network.addEventListener("input", () => { draft.network = network.value; });
  const add = async () => {
    try {
      await apiPost("/api/clients/groups", { name: draft.name, network: draft.network });
      ctx.uiState.groupDraft = { name: "", network: "" };
      toast("Gruppe angelegt");
      ctx.invalidate("clientgroups");
      ctx.rerender();
    } catch (error) {
      toast(`Nicht angelegt: ${error.message}`, "crit");
    }
  };
  const suggestions = data.suggestions || [];
  return el("div", { class: "group-form" },
    el("div", { class: "group-form-row" },
      el("label", { class: "inline-field" }, el("span", { text: "Name" }), name),
      el("label", { class: "inline-field" }, el("span", { text: "Netz" }), network),
      el("button", { type: "button", class: "button primary", text: "Gruppe anlegen", onclick: add })),
    suggestions.length ? el("div", { class: "group-suggest" },
      el("span", { class: "field-help" }, "Vorschläge aus gesehenen Netzen: ", infoButton("clients_group_suggest")),
      suggestions.map((sug) => el("button", { type: "button", class: "chip mono",
        text: `${sug.network} (${fmtNumber(sug.count)})`,
        onclick: () => { draft.network = sug.network; ctx.rerender(); } }))) : null);
}

function groupRow(ctx, group, by) {
  const del = by === "group" && group.group_id && !ctx.readonly ? el("button", { type: "button", class: "button",
    text: "Löschen", "aria-label": `Gruppe ${group.label} löschen`,
    onclick: async () => {
      try {
        await apiPost("/api/clients/groups/delete", { id: group.group_id });
        ctx.invalidate("clientgroups");
        ctx.rerender();
      } catch (error) { toast(error.message, "crit"); }
    } }) : null;
  const names = ctx.uiState.groupNames || {};
  const members = group.members || [];
  const list = members.length ? el("details", { class: "group-members" },
    el("summary", { text: `${fmtNumber(members.length)} Geräte zeigen` }),
    el("ul", { class: "group-member-list" }, members.slice(0, MEMBERS_SHOWN).map((address) =>
      el("li", {}, clientLink({ address, name: names[address] })))),
    members.length > MEMBERS_SHOWN ? el("p", { class: "field-help", text: `… und ${fmtNumber(members.length - MEMBERS_SHOWN)} weitere` }) : null)
    : null;
  return [
    el("tr", {},
      el("td", {}, el("strong", { text: group.label }),
        group.network ? el("span", { class: "mono client-sub", text: ` ${group.network}` }) : null),
      el("td", { class: "num", text: `${fmtNumber(group.total)} (${fmtNumber(group.active)})` }),
      el("td", { class: "num", text: fmtNumber(group.measured) }),
      el("td", { class: "num" }, isNum(group.median_offset)
        ? el("span", { class: "offset-value", "data-tone": offsetTone(group.median_offset), text: fmtOffset(group.median_offset).replace(/^\+/, "") })
        : "–"),
      el("td", { class: "num", text: pct(group.good_share) }),
      el("td", { class: "num", text: isNum(group.score_median) ? fmtNumber(group.score_median, 0) : "–" }),
      el("td", {}, del)),
    group.hint || list ? el("tr", { class: "group-extra" }, el("td", { colspan: "7" },
      group.hint ? el("p", { class: "group-hint" }, el("span", { text: group.hint }), " ",
        el("a", { href: "#/clients", onclick: (event) => { event.preventDefault(); document.getElementById("erzwingen")?.scrollIntoView({ behavior: "smooth" }); },
          text: "Zu „Zeitserver erzwingen“" })) : null,
      list)) : null,
  ];
}

// Gruppen zählen nur Geräte aus der eigenen (passiven) Messung, die Liste oben kommt von chronyd.
// Kennt chrony schon Geräte, darf hier nicht „noch keine Geräte“ stehen.
function emptyGroupsNote(ctx) {
  const known = (ctx.status.clients || []).length;
  if (!known) return emptyState("Noch keine Geräte gesehen.");
  return explainLine(`Noch leer – chrony kennt ${fmtNumber(known)} ${known === 1 ? "Gerät" : "Geräte"} (Liste oben), die eigene Messung `
    + "noch keins. Gruppen zählen nur Geräte aus der eigenen Messung; die ist aus oder gerade gestartet.",
  { class: "empty-note", title: "Gruppen und Netze" });
}

function groupsCard(ctx, names) {
  const by = ctx.uiState.groupBy || "group";
  const groupsUrl = `/api/clients/groups?by=${by}`;
  const data = ctx.data("clientgroups", groupsUrl, 30);
  ctx.uiState.groupNames = names;
  const switcher = el("div", { class: "range-group", role: "group", "aria-label": "Ansicht der Gruppen" },
    GROUP_BYS.map(([key, label]) => el("button", { type: "button", class: `range${by === key ? " is-active" : ""}`,
      text: label, "aria-pressed": by === key ? "true" : "false", "data-focus-key": `groupby:${key}`,
      onclick: () => { ctx.uiState.groupBy = key; ctx.rerender(); } })),
    infoButton("clients_group_by", "Ansicht"));
  if (data === undefined) return card("Gruppen und Netze", { help: "clients_groups", actions: switcher }, loadingOr(ctx, "clientgroups", groupsUrl, "Gruppen"));
  if (!data || !Array.isArray(data.groups)) {
    return card("Gruppen und Netze", { help: "clients_groups", actions: switcher }, emptyState("Gruppen nicht verfügbar."));
  }
  const table = data.groups.length ? el("div", { class: "table-scroll" }, el("table", { class: "group-table" },
    el("thead", {}, el("tr", {},
      el("th", {}, by === "vlan" ? "VLAN " : by === "software" ? "Software " : "Gruppe ", infoButton("clients_group_by")),
      el("th", { class: "num" }, "Geräte (aktiv) ", infoButton("clients_group_stats")),
      el("th", { class: "num" }, "Messbar ", infoButton("client_measurable")),
      el("th", { class: "num" }, "Median ", infoButton("clients_group_stats")),
      el("th", { class: "num" }, "Anteil gut ", infoButton("clients_group_stats")),
      el("th", { class: "num" }, "Uhrgüte ", infoButton("client_quality")),
      el("th", { "aria-label": "Aktion" }))),
    el("tbody", {}, data.groups.map((g) => groupRow(ctx, g, by)))))
    : emptyGroupsNote(ctx);
  return card("Gruppen und Netze", { help: "clients_groups", actions: switcher,
    sub: by === "group" ? "Benenne Netze („IoT = 10.0.30.0/24“) – das spezifischste Netz gewinnt. Die Zahlen "
      + "zeigen je Gruppe, wie gut die Uhren gehen." : by === "vlan"
      ? "Nur, wo die VLAN-Kennung im Paket sichtbar ist (Trunk am Host) – sonst alle unter „ohne VLAN-Kennung“."
      : "Nach erwarteter Software (Regel am Gerät), sonst nach der Vermutung aus den Anfragen." },
  table,
  by === "group" && !ctx.readonly ? groupForm(ctx, data) : null);
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
  foreign: "fremder Server", self_reply: "Schleife", self_address: "Schleife",
};

// Kette „Name → Resolver → Adresse → Antwort“ für eine eigene Quelle (1.5).
function chainRow(item) {
  const reply = item.reply;
  const answer = reply ? `Stratum ${reply.stratum ?? "?"} · ${reply.ref_label || reply.ref_id || "?"}` : "keine Antwort";
  const steps = [
    item.by === "name" ? item.host : `${item.host} (feste IP)`,
    item.by === "name" ? (item.resolver || "System-DNS") : null,
    item.address || (item.by === "name" ? "keine Adresse" : null),
    answer,
  ].filter(Boolean);
  const chain = el("ol", { class: "enforce-chain", "aria-label": "Name, Resolver, Adresse, Antwort" },
    steps.map((step) => el("li", { class: "mono", text: step })));
  return el("li", { class: "enforce-row", "data-level": item.level },
    el("div", { class: "enforce-row-head" },
      el("span", { class: "mono", text: item.host + (item.nts ? " · NTS" : "") }),
      badge(VERDICT_LABEL[item.state] || item.state || "–", item.level === "info" ? "muted" : item.level)),
    chain,
    el("p", { text: item.verdict || "" }));
}

function checkView(result) {
  if (!result) return null;
  const row = (label, item) => el("li", { class: "enforce-row", "data-level": item.level },
    el("div", { class: "enforce-row-head" },
      el("span", { class: "mono", text: label }),
      badge(VERDICT_LABEL[item.state] || item.state || "–", item.level === "info" ? "muted" : item.level)),
    el("p", { text: item.verdict || "" }));
  // Nur Schleifen ausblenden, die die Kette selbst schon als Schleife zeigt – sonst bliebe eine
  // Schleife unsichtbar, deren Kettenzeile (z. B. nur IPv4 geprüft) „fremder Server“ sagt.
  const chained = new Set((result.upstream || [])
    .filter((u) => u.state === "self_address" || u.state === "self_reply").map((u) => u.host));
  return el("div", { class: "enforce-result" },
    el("div", { class: "verdict", "data-tone": result.level === "info" ? null : result.level },
      el("div", { class: "verdict-label" }, el("span", { text: "Ergebnis" }), infoButton("enforce_verdict")),
      el("p", { text: result.summary || "" })),
    // Schleifen, die unten in der Kette der eigenen Quellen stehen, nicht doppelt zeigen.
    (result.loops || []).some((l) => !chained.has(l.host)) ? el("ul", { class: "enforce-list" },
      result.loops.filter((l) => !chained.has(l.host)).map((l) => row(l.host, { ...l, state: "loop" }))) : null,
    (result.upstream || []).length ? el("h3", { class: "mini-head" },
      el("span", { text: "Eigene Quellen: Name → Resolver → Adresse → Antwort" }), infoButton("enforce_upstream")) : null,
    (result.upstream || []).length ? el("ul", { class: "enforce-list" }, result.upstream.map(chainRow)) : null,
    result.resolver && result.resolver.note ? emptyState(result.resolver.note) : null,
    el("h3", { class: "mini-head", text: "Namen (über den DNS-Server dieses Containers)" }),
    el("ul", { class: "enforce-list" }, (result.hosts || []).map((h) => row(h.host, h))),
    el("h3", { class: "mini-head", text: "ntp-gui selbst → öffentliche Server" }),
    el("ul", { class: "enforce-list" }, (result.public || []).map((p) => row(`${p.label} (${p.ip})`, p))),
    result.ours_note ? emptyState(result.ours_note) : null,
    emptyState(result.resolver_note || ""));
}

function selfTest(status, ip) {
  const t = status.tracking || {};
  const stratum = isNum(t.stratum) ? String(t.stratum) : "?";
  const ref = t.ref_id || "?";
  const target = "time.google.com";
  // Feste Adresse von time.google.com: Ein Name würde die DNS-Umschreibung testen, nicht die Firewall.
  const natTarget = "216.239.35.0";
  return el("details", { class: "enforce-selftest explain-more" },
    el("summary", {}, "Selbsttest auf einem Gerät ", infoButton("enforce_selftest")),
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
  const enforceUrl = `/api/enforce/snippets?system=all${query}`;
  const data = ctx.data("enforce", enforceUrl, 300);
  if (data === undefined) {
    return card("Zeitserver erzwingen", { help: "enforce" }, loadingOr(ctx, "enforce", enforceUrl, "Anleitungen"));
  }
  if (!data || !Array.isArray(data.snippets)) {
    return card("Zeitserver erzwingen", { help: "enforce" }, emptyState("Anleitungen nicht verfügbar."));
  }
  const systems = data.snippets;
  const selected = systems.find((s) => s.id === ctx.uiState.enforceSystem) || systems[0];
  // Das ⓘ sitzt neben der Gruppenbeschriftung – hinter den Knöpfen rutschte es auf schmalen
  // Bildschirmen allein in eine eigene Zeile.
  const group = (kind, label, help) => el("div", { class: "enforce-tabs", role: "group", "aria-label": label },
    el("span", { class: "enforce-kind" }, label, " ", infoButton(help, label)),
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
      el("summary", {}, item.title, /NTS/.test(item.title || "") ? [" ", infoButton("enforce_nts")] : null),
      el("p", {}, rich(item.text))))),
    el("div", { class: "enforce-tabbar" },
      el("div", { class: "enforce-group" }, group("dns", "DNS-Umschreibung", "enforce_dns")),
      el("div", { class: "enforce-group" }, group("nat", "Firewall-Umleitung", "enforce_nat"))),
    el("div", { class: "enforce-panel" },
      explainLine(selected.intro || "", { title: selected.title }),
      el("div", { class: "enforce-blocks" }, (selected.blocks || []).map((b) => snippet(b.title, b.code))),
      (selected.notes || []).length ? el("details", { class: "explain-more" },
        el("summary", { text: tr("pages.clients.notes", { system: selected.title, count: fmtNumber(selected.notes.length) }) }),
        el("ul", { class: "enforce-notes" }, selected.notes.map((n) => el("li", {}, rich(n))))) : null,
      selected.kind === "nat" ? el("p", { class: "enforce-hint" }, "Warum Masquerade? ", infoButton("enforce_hairpin")) : null),
    el("details", { class: "enforce-names" },
      el("summary", {}, `Umgeleitete Namen (${fmtNumber(names.length)}) `, infoButton("enforce_hostnames")),
      el("p", { class: "mono enforce-hostlist", text: names.join("  ") }),
      (data.skipped || []).length ? el("ul", { class: "enforce-notes" }, data.skipped.map((s) =>
        el("li", {}, el("span", { class: "mono", text: s.host }), el("span", { text: ` – nicht übernommen: ${s.reason}` })))) : null),
    el("details", { class: "enforce-names" },
      el("summary", {}, "Geräte ohne NTP (Fernseher) ", infoButton("enforce_not_ntp")),
      el("ul", { class: "enforce-notes" }, (data.not_ntp || []).map((n) =>
        el("li", {}, el("strong", { text: n.label }), el("span", { text: ` ${n.text}` }))))),
    el("div", { class: "enforce-check" },
      el("h3", { class: "mini-head" }, "Prüfung ", infoButton("enforce_check")),
      checkResult ? checkView(checkResult)
        : el("p", { class: "empty-note" }, `${tr("pages.clients.check_line")} `, infoButton(null, "Was „Prüfen“ macht", {
          title: "Prüfung", text: "„Prüfen“ fragt ein paar bekannte Namen über den DNS-Server dieses Containers ab und schickt je eine "
          + "NTP-Anfrage an die Antwort und an zwei öffentliche Server. Es werden keine Daten übertragen." }))),
    selfTest(ctx.status, data.server_ip));
}

// --- Geräteliste: Spalten, Karten, Name direkt bearbeiten (T2 „Seiten entschlacken“) ------------
const MOBILE_QUERY = "(max-width: 640px)";

export function isMobile() {
  try { return Boolean(window.matchMedia && window.matchMedia(MOBILE_QUERY).matches); } catch (error) { return false; }
}

const STAR_TITLE = "* aus der eigenen Messung – chrony kennt das Gerät seit seinem letzten Neustart nicht";

/**
 * Spalten der Geräteliste (ohne „Gerät“). has(c): hat diese Zeile einen Messwert? cell(c): Inhalt.
 * lastAge(c): Sekunden seit der letzten Anfrage (chrony oder eigene Messung) oder null.
 */
export function clientColumns({ offsets = {}, scores = {}, lastAge = () => null } = {}) {
  const off = (c) => offsets[c.address];
  const measurable = (c) => Boolean(off(c) && off(c).measurable && isNum(off(c).ewma));
  return [
    { key: "packets", label: "Anfragen", help: "client_packets", num: true,
      has: (c) => isNum(c.ntp_packets) || isNum(off(c)?.requests),
      cell: (c) => (isNum(c.ntp_packets) ? fmtNumber(c.ntp_packets)
        : isNum(off(c)?.requests) ? `${fmtNumber(off(c).requests)}*` : "–"),
      title: (c) => (isNum(c.ntp_packets) ? null : STAR_TITLE) },
    { key: "dropped", label: "Verworfen", help: "client_dropped", num: true,
      has: (c) => isNum(c.ntp_dropped), cell: (c) => fmtNumber(c.ntp_dropped) },
    { key: "interval", label: "Intervall", help: "client_interval", num: true,
      has: (c) => isNum(c.ntp_interval), cell: (c) => fmtLogInterval(c.ntp_interval) },
    { key: "last", label: "Zuletzt", help: "client_last", num: true,
      has: (c) => isNum(lastAge(c)),
      cell: (c) => (isNum(lastAge(c)) ? `vor ${fmtDuration(lastAge(c))}${isNum(c.ntp_last_rx) ? "" : "*"}` : "–"),
      title: (c) => (isNum(c.ntp_last_rx) ? null : STAR_TITLE) },
    { key: "offset", label: "Uhr geht falsch um", help: "client_offset", num: true,
      has: measurable, cell: (c) => offsetValue(off(c)) },
    { key: "state", label: "messbar", help: "client_measurable",
      has: (c) => Boolean(off(c) && off(c).state), cell: (c) => offsetState(off(c)) },
    { key: "score", label: "Güte", help: "client_score", num: true,
      has: (c) => isNum(scores[c.address]?.score), cell: (c) => scoreCell(scores[c.address]) },
  ];
}

/** Nur Spalten, in denen mindestens eine Zeile einen Messwert hat. */
export function visibleColumns(columns, rows) {
  return columns.filter((col) => rows.some((row) => col.has(row)));
}

function scoreCell(q) {
  return q && isNum(q.score) ? el("span", { class: "score-value", "data-tone": q.tone || "muted",
    title: q.grade || null, text: String(q.score) }) : el("span", { class: "muted", text: "–" });
}

// Name direkt in der Liste: ✎ öffnet ein Feld, Enter speichert (POST /api/clients/meta, nur der Name –
// die Notiz bleibt), Esc bricht ab. Der Zustand liegt in uiState, damit das Neuzeichnen alle paar
// Sekunden weder Eingabe noch Cursor verliert. Schreibgeschützt (WEB_READONLY): kein ✎.
function nameEditor(ctx, { address, name, where, names }) {
  const link = clientLink({ address, name });
  const edit = ctx.uiState.nameEdit;
  const key = `${where}:${address}`;
  if (ctx.readonly) return link;
  if (!edit || edit.address !== address) {
    const open = el("button", { type: "button", class: "name-edit", "data-focus-key": `name-edit:${key}`,
      "aria-label": `${tr(name ? "pages.clients.name_change" : "pages.clients.name_add")}: ${name || address}`,
      title: tr(name ? "pages.clients.name_change" : "pages.clients.name_add"),
      onclick: () => {
        ctx.uiState.nameEdit = { address, value: name || "", error: "", busy: false, focus: true, where };
        ctx.rerender();
      } }, el("span", { "aria-hidden": "true", text: "✎" }));
    return el("span", { class: "name-cell" }, link, open);
  }
  const field = el("input", { type: "text", class: "name-input", maxlength: "64", value: edit.value,
    placeholder: tr("pages.clients.name_placeholder"), "data-focus-key": `name-input:${key}`, disabled: edit.busy || null,
    "aria-label": tr("pages.clients.name_input", { address }),
    "aria-invalid": edit.error ? "true" : null, "aria-describedby": edit.error ? `name-error-${where}` : null });
  const remember = () => { edit.value = field.value; edit.selection = [field.selectionStart, field.selectionEnd]; };
  field.addEventListener("input", () => { remember(); if (edit.error) { edit.error = ""; } });
  field.addEventListener("keyup", remember);
  field.addEventListener("click", remember);
  field.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      ctx.uiState.nameEdit = null;
      ctx.uiState.nameFocus = `name-edit:${key}`;
      ctx.rerender();
    } else if (event.key === "Enter") {
      event.preventDefault();
      saveName(ctx, edit, key, names);
    }
  });
  if (edit.where === where) {
    ctx.afterRender(() => {
      if (!field.isConnected || edit.busy) return;
      if (edit.focus || document.activeElement === document.body || document.activeElement === field) {
        field.focus({ preventScroll: true });
        const [a, b] = edit.selection || [field.value.length, field.value.length];
        try { field.setSelectionRange(a, b); } catch (error) { /* Feldtyp ohne Auswahl */ }
        edit.focus = false;
      }
    });
  }
  return el("span", { class: "name-cell is-editing" },
    el("span", { class: "name-edit-box" }, field,
      el("span", { class: "mono client-sub", text: address })),
    edit.error ? el("span", { class: "inline-error", id: `name-error-${where}`, role: "alert", text: edit.error }) : null);
}

async function saveName(ctx, edit, key, names) {
  if (edit.busy) return;
  edit.busy = true;
  ctx.rerender();
  try {
    const result = await apiPost("/api/clients/meta", { ip: edit.address, name: edit.value });
    if (names) names[edit.address] = result.name || undefined;
    ctx.uiState.nameEdit = null;
    ctx.uiState.nameFocus = `name-edit:${key}`;
    toast(tr(result.name ? "pages.clients.name_saved" : "pages.clients.name_removed"));
    ctx.invalidate("clientoffsets");
    ctx.invalidate("clientoverview");
    ctx.invalidate("clientgroups");
    ctx.invalidate(`clientdetail:${edit.address}`);
    ctx.rerender();
    ctx.refresh();
  } catch (error) {
    edit.busy = false;
    edit.focus = true;
    edit.error = tr("pages.clients.name_failed", { message: error.message });
    ctx.rerender();
  }
}

export function render(ctx) {
  if (ctx.subpath && ctx.subpath.endsWith("/pass")) {
    const known = serverAddress(ctx.status);
    return renderPass(ctx, ctx.subpath.slice(0, -5), known && isIp(known) ? known : null);
  }
  if (ctx.subpath) return renderDetail(ctx, ctx.subpath);
  const { status, history } = ctx;
  const clients = status.clients || [];
  const stats = status.serverstats || {};
  const rate = requestRate(history);
  const recent = recentRateInfo(history);
  const lastRate = recent.rate;
  const filter = (ctx.uiState.clientFilter || "").toLowerCase();
  // Nach Esc oder Speichern im Namensfeld: Fokus zurück auf das ✎ der Zeile.
  if (ctx.uiState.nameFocus) {
    const want = ctx.uiState.nameFocus;
    ctx.uiState.nameFocus = null;
    ctx.afterRender(() => document.querySelector(`[data-focus-key="${CSS.escape(want)}"]`)?.focus({ preventScroll: true }));
  }
  const knownIp = serverAddress(status);
  const ip = knownIp || IP_PLACEHOLDER;
  const mon = offsetData(ctx);
  const offsets = (mon && mon.clients) || {};
  const names = (mon && mon.names) || {};
  const measured = Object.values(offsets).filter((c) => c.measurable && isNum(c.ewma));
  const worst = measured.reduce((acc, c) => (acc === null || Math.abs(c.ewma) > Math.abs(acc) ? c.ewma : acc), null);

  // chrony leert seine Client-Liste bei jedem Neustart (z. B. nach dem Speichern von Einstellungen);
  // die eigene Messung kennt die Geräte weiter. Fehlt chronys Wert, gilt ihrer (mit * markiert).
  const lastAge = (c) => {
    if (isNum(c.ntp_last_rx)) return c.ntp_last_rx;
    const seen = offsets[c.address]?.last_seen;
    return isNum(seen) ? Math.max(0, Date.now() / 1000 - seen) : null;
  };
  // Geräte aus chronyd, ergänzt um solche, die nur die passive Messung kennt.
  const known = new Set(clients.map((c) => c.address));
  const rows = clients.concat(Object.keys(offsets).filter((a) => !known.has(a)).map((address) => ({ address })));

  const quality = qualityData(ctx);
  const scores = (quality && quality.scores) || {};
  const input = el("input", { type: "search", placeholder: "Filtern …", value: ctx.uiState.clientFilter || "",
    "aria-label": "Clients filtern" });
  // Spalten ohne einen einzigen Messwert fallen weg (z. B. „Güte“, solange keine Uhr bewertbar ist).
  const columns = clientColumns({ offsets, scores, lastAge });
  const shown = visibleColumns(columns, rows);
  const mobile = isMobile();
  const sorted = (needle) => rows.filter((c) => !needle || (c.address || "").toLowerCase().includes(needle)
    || (names[c.address] || "").toLowerCase().includes(needle))
    .sort((a, b) => (lastAge(a) ?? 1e12) - (lastAge(b) ?? 1e12));
  const nameCell = (c, where) => nameEditor(ctx, { address: c.address, name: names[c.address], where, names });
  const bodyRows = (needle) => sorted(needle).map((c) => (mobile
    ? el("li", { class: "client-card" },
      el("div", { class: "client-card-head" }, nameCell(c, "card")),
      el("dl", { class: "client-card-facts" }, shown.map((col) => el("div", { class: "client-card-fact" },
        el("dt", { text: col.label }),
        el("dd", { class: col.num ? "num" : null, title: col.title ? col.title(c) : null }, col.cell(c))))))
    : el("tr", {},
      el("td", {}, nameCell(c, "table")),
      ...shown.map((col) => el("td", { class: col.num ? "num" : null, title: col.title ? col.title(c) : null }, col.cell(c))))));
  const tbody = mobile ? el("ul", { class: "client-cards", "aria-label": tr("pages.clients.cards_label") }, bodyRows(filter))
    : el("tbody", {}, bodyRows(filter));
  // Nur die Zeilen tauschen – ein Neuaufbau der Seite würde dem Feld den Fokus nehmen.
  input.addEventListener("input", () => {
    ctx.uiState.clientFilter = input.value;
    tbody.replaceChildren(...bodyRows(input.value.toLowerCase()));
  });
  // Handy (≤ 640 px): Karten statt einer Tabelle, die man seitlich schieben müsste. Die Erklärungen der
  // Spalten (ⓘ im Tabellenkopf) stehen einmal über den Karten, die zum Sternchen sichtbar darunter.
  const starred = shown.some((col) => col.title && rows.some((c) => col.title(c)));
  const table = mobile ? el("div", { class: "client-cards-wrap" },
    el("p", { class: "client-card-legend" },
      el("span", {}, "Gerät ", infoButton("client_address")),
      shown.map((col) => el("span", {}, `${col.label} `, infoButton(col.help)))),
    tbody,
    starred ? el("p", { class: "field-help", text: STAR_TITLE }) : null) : el("div", { class: "table-scroll" }, el("table", { class: "clients-table" },
    el("thead", {}, el("tr", {},
      el("th", {}, "Gerät ", infoButton("client_address")),
      shown.map((col) => el("th", { class: col.num ? "num" : null }, `${col.label} `, infoButton(col.help))))),
    tbody));

  const chartHost = el("div", { class: "chart-host" });
  ctx.afterRender(() => lineChart(chartHost, {
    series: [{ id: "rate", label: "pro Minute", color: "var(--accent)", points: rate }],
    format: (v) => `${fmtRate(v)}/min`, axisFormat: (v, step) => fmtNumber(v, stepDecimals(step)), area: true, min: 0,
    range: ctx.range, end: ctx.status.system?.time, ariaLabel: "Beantwortete Anfragen pro Minute",
    emptyText: "Noch keine Anfragen gemessen",
  }));

  // Eine Zeile sichtbar (Adresse), Erklärung und FRITZ!Box-Hinweis im ⓘ; die Anleitungen für Geräte, die
  // Option 42 ignorieren, eingeklappt.
  const setup = card("Clients einrichten", { help: "dhcp42",
    sub: `Adresse dieses Servers: ${knownIp ? `**${knownIp}**` : "**unbekannt** – setze die IP des Hosts ein"}. Am bequemsten per DHCP Option 42 – dann übernehmen viele Geräte den Server automatisch. `
      + "Die FRITZ!Box verteilt Option 42 nicht frei – dort Geräte direkt einstellen oder einen anderen DHCP-Server (z. B. Pi-hole) nutzen. "
      + "Für Geräte mit fest eingebautem Server hilft **Zeitserver erzwingen** weiter unten." },
    el("div", { class: "snippets" },
      snippet("dnsmasq / Pi-hole", `dhcp-option=42,${ip}`),
      snippet("ISC dhcpd", `option ntp-servers ${ip};`),
      snippet("Kea DHCPv4", `"option-data": [ { "name": "ntp-servers", "data": "${ip}" } ]`),
      snippet("MikroTik RouterOS", `/ip dhcp-server network set [find] ntp-server=${ip}`),
      snippet("OPNsense / pfSense", `Dienste → DHCP-Server → Interface → NTP-Server 1: ${ip}`),
      snippet("UniFi", `Einstellungen → Netzwerke → DHCP → NTP-Server: ${ip}`)),
    el("details", { class: "explain-more" }, el("summary", { text: tr("pages.clients.ignore_42") }),
    el("div", { class: "snippets" }, clientSnippets(ip))));

  return [
    el("div", { class: "stat-row" },
      statCard({ label: "Clients", help: "client_packets", value: fmtNumber(rows.length), tone: rows.length ? "good" : "muted",
        note: "seit dem Start von chrony" }),
      statCard({ label: "Anfragen", help: "served_rate", value: fmtRate(lastRate), unit: "/min",
        tone: "muted", note: `${rateWindowText(recent.seconds)} · ${fmtNumber(stats.ntp_packets_received)} insgesamt` }),
      statCard({ label: "Verworfen", help: "client_dropped", value: fmtNumber(stats.ntp_packets_dropped ?? 0),
        tone: (stats.ntp_packets_dropped || 0) > 0 ? "warn" : "muted", note: "z. B. durch Begrenzung" }),
      statCard({ label: "Größte Abweichung", help: "client_offset", value: fmtOffset(worst),
        tone: offsetTone(worst), note: mon && mon.available
          ? `${fmtNumber(measured.length)} von ${fmtNumber(Object.keys(offsets).length)} Geräten messbar`
          : "Messung nicht aktiv" })),
    card("Geräte, die diesen Server fragen", { help: "client_packets", actions: input,
      sub: rows.length ? null : "Noch keine Anfragen. Sobald die Adresse verteilt ist, erscheinen die Geräte hier." },
      rows.length ? table : null, clientmonNote(mon)),
    overviewCard(ctx),
    groupsCard(ctx, names),
    card("Anfragen pro Minute", { help: "served_rate", actions: rangeButtons(ctx.range, ctx.setRange) }, chartHost),
    setup,
    enforceSection(ctx, knownIp && isIp(knownIp) ? knownIp : null),
  ];
}

export { rich };
