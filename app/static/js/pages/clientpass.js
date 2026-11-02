// Gerätepass (1.5, Clients 3): #/clients/<adresse>/pass
// Eine druckbare Seite je Gerät – Browser-Druck, kein Export-Endpunkt. Alle Werte landen per
// el()/textContent im DOM. „Gefilterte Kopie“ holt eine Textfassung, die der Datenschutzfilter
// (egress) bereinigt hat – zum Weitergeben im Forum oder Ticket.
import { el, apiGet, fmtNumber, isNum } from "../util.js";
import { card, info, badge, kv, emptyNote, toast, copyButton } from "../ui.js";
import { lineChart } from "../charts.js";
import { axisSeconds } from "./overview.js";
import { fmtOffset, fmtInterval, fmtDate, clientHref, qualityBadge, fmtPpm } from "./clientdetail.js";

const ORIGIN = { erwartet: "erwartet (deine Angabe)", vermutet: "vermutlich", unbekannt: "unbekannt" };

let shareBusy = false;

async function loadShare(ctx, ip) {
  if (shareBusy) return;
  shareBusy = true;
  ctx.rerender();
  const shares = ctx.uiState.passShare || (ctx.uiState.passShare = {});
  try {
    shares[ip] = await apiGet(`/api/clients/pass?ip=${encodeURIComponent(ip)}&share=1`);
  } catch (error) {
    toast(`Keine Kopie: ${error.message}`, "crit");
  }
  shareBusy = false;
  ctx.rerender();
}

function recommendation(rec, placeholder, serverIp) {
  const code = serverIp ? String(rec.code).split(placeholder).join(serverIp) : String(rec.code);
  const pre = el("pre", { class: "code", text: code });
  return el("div", { class: "snippet" },
    el("div", { class: "snippet-head" }, el("strong", { text: rec.title }), copyButton(code, pre)), pre);
}

export function renderPass(ctx, ip, serverIp) {
  const url = `/api/clients/pass?ip=${encodeURIComponent(ip)}`;
  const data = ctx.data(`clientpass:${ip}`, url, 60);
  const back = el("p", { class: "client-back no-print" }, el("a", { href: clientHref(ip), text: "← Zurück zum Gerät" }));
  const failed = data === undefined ? ctx.dataError?.(`clientpass:${ip}`, url) : null;
  if (failed) {
    return [back, card("Gerätepass", { help: "client_pass" },
      emptyNote(failed.status === 404 ? "Zu diesem Gerät liegen keine Daten vor."
        : failed.status === 400 ? "Ungültige Adresse im Link." : `Nicht geladen: ${failed.message}`))];
  }
  if (data === undefined) return [back, emptyNote("Lade Gerätepass …")];
  const entry = data.entry || {};
  const q = data.quality || {};
  const nts = data.nts || {};
  const week = data.week || {};
  const month = data.month || {};
  const title = data.name || data.address;
  const now = Date.now() / 1000;
  const share = (ctx.uiState.passShare || {})[ip];

  const chartHost = el("div", { class: "chart-host" });
  const points = (data.series || []).filter((p) => isNum(p[1]));
  ctx.afterRender(() => lineChart(chartHost, {
    key: `client-pass:${ip}`,
    series: [{ id: "offset", label: "Abweichung", color: "var(--accent)", points }],
    format: fmtOffset, axisFormat: axisSeconds, range: 604800, end: data.generated,
    ariaLabel: `Abweichung der Uhr von ${title} über 7 Tage`,
    emptyText: entry.measurable === false ? "Nicht messbar – das Gerät schickt keine echte Uhrzeit" : "Noch keine Messwerte",
  }));

  const actions = el("div", { class: "button-row no-print" },
    el("button", { type: "button", class: "button primary", text: "Drucken", onclick: () => window.print() }),
    el("button", { type: "button", class: "button", disabled: shareBusy || null,
      text: shareBusy ? "Filtere …" : "Gefilterte Kopie", onclick: () => loadShare(ctx, ip) }),
    info("client_pass_share", "Gefilterte Kopie"));
  const softwareText = `${data.software?.label || "unbekannt"} · ${ORIGIN[data.software?.origin] || "unbekannt"}`;
  const ntsText = !nts.server ? "NTS-Server dieser Instanz aus"
    : nts.uses ? "nutzt NTS" : nts.can === true ? "nein – könnte es" : "nein";

  return [
    back,
    el("article", { class: "client-pass" },
      el("header", { class: "client-pass-head" },
        el("div", {},
          el("p", { class: "client-pass-kind", text: "Gerätepass" }),
          el("h1", { class: "client-title", text: title }),
          data.name ? el("span", { class: "mono client-sub", text: data.address }) : null),
        el("div", { class: "client-pass-meta" },
          qualityBadge(q),
          el("span", { class: "field-help", text: `Stand ${fmtDate(data.generated)}` })),
        actions),
      share ? card("Gefilterte Kopie", { help: "client_pass_share", class: "no-print",
        sub: "So darf der Pass die Instanz verlassen – Adressen und eigene Namen sind ersetzt, Notiz und MAC fehlen." },
      el("pre", { class: "code", text: share.text }),
      el("div", { class: "button-row" }, copyButton(share.text))) : null,
      el("div", { class: "grid-2" },
        card("Gerät", { help: "client_detail" }, kv([
          ["Name", data.name || "–", "client_meta"],
          ["Adresse", el("span", { class: "mono", text: data.address }), "client_address"],
          ["Gruppe", data.group ? `${data.group.name} (${data.group.network})` : "ohne Gruppe", "client_group"],
          ["Software", softwareText, "client_rule_expect"],
          ["NTP-Version", isNum(entry.version) ? String(entry.version) : "–", "client_version"],
          ["Typischer Abstand", fmtInterval(entry.interval), "client_typical_interval"],
          ["Zuerst gesehen", fmtDate(entry.first_seen), "client_seen"],
          ["Letzte Anfrage", isNum(entry.last_seen) ? `${fmtDate(entry.last_seen)} (vor ${fmtInterval(Math.max(0, now - entry.last_seen))})` : "–", "client_seen"],
          ["Messbar", entry.state_text || "–", "client_measurable"],
          ["NTS", ntsText, "client_nts"],
        ]),
        data.note ? el("p", { class: "client-pass-note" }, el("strong", { text: "Notiz: " }), el("span", { text: data.note })) : null),
        card("Uhr", { help: "client_pass_values" }, kv([
          ["Abweichung jetzt", entry.measurable ? fmtOffset(entry.ewma) : "–", "client_offset"],
          ["Median (7 Tage)", fmtOffset(week.median), "client_pass_values"],
          ["P95 |Abweichung| (7 Tage)", isNum(week.p95) ? fmtOffset(week.p95).replace(/^\+/, "") : "–", "client_pass_values"],
          ["Median (30 Tage)", fmtOffset(month.median), "client_pass_values"],
          ["Gangabweichung", fmtPpm(q.drift_ppm), "client_drift"],
          ["Uhrgüte", isNum(q.score) ? `${q.score}/100 – ${q.grade}` : (q.grade || "–"), "client_quality"],
          ["Messungen (7 Tage)", fmtNumber(week.n || 0), "client_pass_values"],
        ]), q.text ? el("p", { class: "field-help", text: q.text }) : null)),
      card("Abweichung – 7 Tage", { help: "client_offset_chart" }, chartHost),
      card("Empfehlung", { help: "client_pass",
        sub: serverIp ? null : "Die Adresse dieses Servers ist nicht bekannt – setze sie für **<IP-des-Servers>** ein." },
      (data.recommendations || []).length
        ? el("div", { class: "snippets" }, data.recommendations.map((r) => recommendation(r, data.server_placeholder, serverIp)))
        : emptyNote("Keine Empfehlung – das Gerät hält seine Uhr gut.")),
      el("p", { class: "field-help client-pass-foot" },
        badge("lokal", "muted"), " Dieser Pass bleibt auf dieser Instanz. Drucken oder „Als PDF speichern“ macht der Browser.")),
  ];
}
