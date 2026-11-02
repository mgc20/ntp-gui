import { el, apiGet, apiPost, fmtDuration, fmtNumber, fmtRate, fmtLogInterval, isNum, rich } from "../util.js";
import { card, tile, info, badge, rangeButtons, emptyNote, toast, copyButton } from "../ui.js";
import { lineChart, stepDecimals } from "../charts.js";
import { requestRate } from "./overview.js";
import { renderDetail, fmtOffset, offsetTone, fmtInterval, clientHref, STATE_TONE, STATE_SHORT, qualityBadge, fmtDrift } from "./clientdetail.js";
import { renderPass } from "./clientpass.js";

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
// Formatierung und Zustände teilt sich die Liste mit der Detailseite (clientdetail.js).

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

// --- Netzüberblick ---------------------------------------------------------------
const BIN_TONE = { lt1ms: "good", "1-10ms": "good", "10-100ms": "warn", "0.1-1s": "warn", gt1s: "crit", wrong: "crit" };

function clientLink(item) {
  return el("a", { href: clientHref(item.address), class: "client-link" },
    item.name ? el("span", { text: item.name }) : el("span", { class: "mono", text: item.address }),
    item.name ? el("span", { class: "mono client-sub", text: ` ${item.address}` }) : null);
}

function miniList(title, help, items, total, cell, empty) {
  return el("div", { class: "net-list" },
    el("h3", { class: "mini-head" }, el("span", { text: title }), info(help, title),
      total > items.length ? el("span", { class: "muted", text: `(${fmtNumber(items.length)} von ${fmtNumber(total)})` }) : null),
    items.length ? el("ul", { class: "net-items" }, items.map((item) => el("li", {}, clientLink(item), cell(item))))
      : el("p", { class: "field-help", text: empty }));
}

function overviewCard(ctx) {
  const data = ctx.data("clientoverview", "/api/clients/overview", 15);
  if (data === undefined) return card("Netzüberblick", { help: "clients_overview" }, emptyNote("Lade Überblick …"));
  if (!data || !Array.isArray(data.histogram)) {
    return card("Netzüberblick", { help: "clients_overview" }, emptyNote("Überblick nicht verfügbar."));
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
      el("h3", { class: "mini-head" }, el("span", { text: "Wie weit gehen die Uhren falsch?" }), info("clients_histogram")),
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
    data === undefined ? "Lade Uhrgüte …" : "Noch kein Gerät bewertbar (es braucht mindestens 4 Messungen).");
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
      el("span", { class: "field-help" }, "Vorschläge aus gesehenen Netzen: ", info("clients_group_suggest")),
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

function groupsCard(ctx, names) {
  const by = ctx.uiState.groupBy || "group";
  const data = ctx.data("clientgroups", `/api/clients/groups?by=${by}`, 30);
  ctx.uiState.groupNames = names;
  const switcher = el("div", { class: "range-group", role: "group", "aria-label": "Ansicht der Gruppen" },
    GROUP_BYS.map(([key, label]) => el("button", { type: "button", class: `range${by === key ? " is-active" : ""}`,
      text: label, "aria-pressed": by === key ? "true" : "false", "data-focus-key": `groupby:${key}`,
      onclick: () => { ctx.uiState.groupBy = key; ctx.rerender(); } })),
    info("clients_group_by", "Ansicht"));
  if (data === undefined) return card("Gruppen und Netze", { help: "clients_groups", actions: switcher }, emptyNote("Lade Gruppen …"));
  if (!data || !Array.isArray(data.groups)) {
    return card("Gruppen und Netze", { help: "clients_groups", actions: switcher }, emptyNote("Gruppen nicht verfügbar."));
  }
  const table = data.groups.length ? el("div", { class: "table-scroll" }, el("table", { class: "group-table" },
    el("thead", {}, el("tr", {},
      el("th", {}, by === "vlan" ? "VLAN " : by === "software" ? "Software " : "Gruppe ", info("clients_group_by")),
      el("th", { class: "num" }, "Geräte (aktiv) ", info("clients_group_stats")),
      el("th", { class: "num" }, "Messbar ", info("client_measurable")),
      el("th", { class: "num" }, "Median ", info("clients_group_stats")),
      el("th", { class: "num" }, "Anteil gut ", info("clients_group_stats")),
      el("th", { class: "num" }, "Uhrgüte ", info("client_quality")),
      el("th", { "aria-label": "Aktion" }))),
    el("tbody", {}, data.groups.map((g) => groupRow(ctx, g, by)))))
    : emptyNote("Noch keine Geräte gesehen.");
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
      el("div", { class: "verdict-label" }, el("span", { text: "Ergebnis" }), info("enforce_verdict")),
      el("p", { text: result.summary || "" })),
    // Schleifen, die unten in der Kette der eigenen Quellen stehen, nicht doppelt zeigen.
    (result.loops || []).some((l) => !chained.has(l.host)) ? el("ul", { class: "enforce-list" },
      result.loops.filter((l) => !chained.has(l.host)).map((l) => row(l.host, { ...l, state: "loop" }))) : null,
    (result.upstream || []).length ? el("h3", { class: "mini-head" },
      el("span", { text: "Eigene Quellen: Name → Resolver → Adresse → Antwort" }), info("enforce_upstream")) : null,
    (result.upstream || []).length ? el("ul", { class: "enforce-list" }, result.upstream.map(chainRow)) : null,
    result.resolver && result.resolver.note ? emptyNote(result.resolver.note) : null,
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
  if (ctx.subpath && ctx.subpath.endsWith("/pass")) {
    const known = serverAddress(ctx.status);
    return renderPass(ctx, ctx.subpath.slice(0, -5), known && isIp(known) ? known : null);
  }
  if (ctx.subpath) return renderDetail(ctx, ctx.subpath);
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
  const scoreCell = (q) => (q && isNum(q.score) ? el("span", { class: "score-value", "data-tone": q.tone || "muted",
    title: q.grade || null, text: String(q.score) }) : el("span", { class: "muted", text: "–" }));
  const input = el("input", { type: "search", placeholder: "Filtern …", value: ctx.uiState.clientFilter || "",
    "aria-label": "Clients filtern" });
  const bodyRows = (needle) => rows.filter((c) => !needle || (c.address || "").toLowerCase().includes(needle)
    || (names[c.address] || "").toLowerCase().includes(needle))
    .sort((a, b) => (lastAge(a) ?? 1e12) - (lastAge(b) ?? 1e12))
    .map((c) => el("tr", {},
      el("td", {}, clientLink({ address: c.address, name: names[c.address] })),
      el("td", { class: "num", text: isNum(c.ntp_packets) ? fmtNumber(c.ntp_packets)
        : isNum(offsets[c.address]?.requests) ? `${fmtNumber(offsets[c.address].requests)}*` : "–",
        title: isNum(c.ntp_packets) ? "" : "* aus der eigenen Messung – chrony kennt das Gerät seit seinem letzten Neustart nicht" }),
      el("td", { class: "num", text: fmtNumber(c.ntp_dropped) }),
      el("td", { class: "num", text: fmtLogInterval(c.ntp_interval) }),
      el("td", { class: "num", text: isNum(lastAge(c)) ? `vor ${fmtDuration(lastAge(c))}${isNum(c.ntp_last_rx) ? "" : "*"}` : "–",
        title: isNum(c.ntp_last_rx) ? "" : "* aus der eigenen Messung – chrony kennt das Gerät seit seinem letzten Neustart nicht" }),
      ...offsetCells(offsets[c.address]),
      el("td", { class: "num" }, scoreCell(scores[c.address]))));
  const tbody = el("tbody", {}, bodyRows(filter));
  // Nur die Zeilen tauschen – ein Neuaufbau der Seite würde dem Feld den Fokus nehmen.
  input.addEventListener("input", () => {
    ctx.uiState.clientFilter = input.value;
    tbody.replaceChildren(...bodyRows(input.value.toLowerCase()));
  });
  const table = el("div", { class: "table-scroll" }, el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "Gerät ", info("client_address")),
      el("th", { class: "num" }, "Anfragen ", info("client_packets")),
      el("th", { class: "num" }, "Verworfen ", info("client_dropped")),
      el("th", { class: "num" }, "Intervall ", info("client_interval")),
      el("th", { class: "num" }, "Zuletzt ", info("client_last")),
      el("th", { class: "num" }, "Uhr geht falsch um ", info("client_offset")),
      el("th", {}, "messbar ", info("client_measurable")),
      el("th", { class: "num" }, "Güte ", info("client_score")))),
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
    overviewCard(ctx),
    groupsCard(ctx, names),
    card("Anfragen pro Minute", { help: "served_rate", actions: rangeButtons(ctx.range, ctx.setRange) }, chartHost),
    setup,
    enforceSection(ctx, knownIp && isIp(knownIp) ? knownIp : null),
  ];
}

export { rich };
