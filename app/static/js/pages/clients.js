import { el, fmtDuration, fmtNumber, fmtLogInterval, isNum, rich } from "../util.js";
import { card, tile, info, rangeButtons, emptyNote, toast } from "../ui.js";
import { lineChart, stepDecimals } from "../charts.js";
import { requestRate } from "./overview.js";

function serverAddress(status) {
  const host = window.location.hostname;
  if (host && host !== "localhost" && !host.startsWith("127.")) return host;
  const addresses = (status.system || {}).addresses || [];
  return addresses.find((a) => /^\d+\.\d+\.\d+\.\d+$/.test(a) && !a.startsWith("127.")) || "192.168.1.10";
}

function snippet(title, code) {
  const pre = el("pre", { class: "code", text: code });
  const copy = el("button", { type: "button", class: "copy", text: "Kopieren", onclick: async () => {
    try { await navigator.clipboard.writeText(code); toast("Kopiert"); } catch (error) { toast("Kopieren nicht möglich – bitte markieren", "warn"); }
  } });
  return el("div", { class: "snippet" }, el("div", { class: "snippet-head" }, el("strong", { text: title }), copy), pre);
}

export function render(ctx) {
  const { status, history } = ctx;
  const clients = status.clients || [];
  const stats = status.serverstats || {};
  const rate = requestRate(history);
  const lastRate = rate.length ? rate[rate.length - 1][1] : null;
  const filter = (ctx.uiState.clientFilter || "").toLowerCase();
  const ip = serverAddress(status);

  const input = el("input", { type: "search", placeholder: "Filtern …", value: ctx.uiState.clientFilter || "",
    "aria-label": "Clients filtern" });
  const bodyRows = (needle) => clients.filter((c) => !needle || (c.address || "").toLowerCase().includes(needle))
    .sort((a, b) => (a.ntp_last_rx ?? 1e12) - (b.ntp_last_rx ?? 1e12))
    .map((c) => el("tr", {},
      el("td", { class: "mono", text: c.address }),
      el("td", { class: "num", text: fmtNumber(c.ntp_packets) }),
      el("td", { class: "num", text: fmtNumber(c.ntp_dropped) }),
      el("td", { class: "num", text: fmtLogInterval(c.ntp_interval) }),
      el("td", { class: "num", text: isNum(c.ntp_last_rx) ? `vor ${fmtDuration(c.ntp_last_rx)}` : "–" })));
  const tbody = el("tbody", {}, bodyRows(filter));
  // Nur die Zeilen tauschen – ein Neuaufbau der Seite würde dem Feld den Fokus nehmen.
  input.addEventListener("input", () => {
    ctx.uiState.clientFilter = input.value;
    tbody.replaceChildren(...bodyRows(input.value.toLowerCase()));
  });
  const table = el("div", { class: "table-scroll" }, el("table", {},
    el("thead", {}, el("tr", {},
      el("th", { text: "Adresse" }),
      el("th", { class: "num" }, "Anfragen ", info("client_packets")),
      el("th", { class: "num" }, "Verworfen ", info("client_dropped")),
      el("th", { class: "num" }, "Intervall ", info("client_interval")),
      el("th", { class: "num" }, "Zuletzt ", info("client_last")))),
    tbody));

  const chartHost = el("div", { class: "chart-host" });
  ctx.afterRender(() => lineChart(chartHost, {
    series: [{ id: "rate", label: "pro Minute", color: "var(--accent)", points: rate }],
    format: (v) => `${fmtNumber(v, 1)}/min`, axisFormat: (v, step) => fmtNumber(v, stepDecimals(step)), area: true, min: 0,
    emptyText: "Noch keine Anfragen gemessen",
  }));

  const setup = card("Clients einrichten", { help: "dhcp42",
    sub: `Adresse dieses Servers: **${ip}**. Am bequemsten per DHCP Option 42 – dann übernehmen viele Geräte den Server automatisch.` },
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
    emptyNote("Die FRITZ!Box verteilt Option 42 nicht frei – dort Geräte direkt einstellen oder einen anderen DHCP-Server (z. B. Pi-hole) nutzen."));

  return [
    el("div", { class: "stat-row" },
      tile({ label: "Clients", help: "client_packets", value: fmtNumber(clients.length), tone: clients.length ? "good" : "muted",
        note: "seit dem Start von chrony" }),
      tile({ label: "Anfragen", help: "served_rate", value: isNum(lastRate) ? fmtNumber(lastRate, 1) : "–", unit: "/min",
        tone: "muted", note: `${fmtNumber(stats.ntp_packets_received)} insgesamt` }),
      tile({ label: "Verworfen", help: "client_dropped", value: fmtNumber(stats.ntp_packets_dropped ?? 0),
        tone: (stats.ntp_packets_dropped || 0) > 0 ? "warn" : "muted", note: "z. B. durch Begrenzung" })),
    card("Geräte, die diesen Server fragen", { help: "client_packets", actions: input,
      sub: clients.length ? null : "Noch keine Anfragen. Sobald die Adresse verteilt ist, erscheinen die Geräte hier." },
      clients.length ? table : null),
    card("Anfragen pro Minute", { help: "served_rate", actions: rangeButtons(ctx.range, ctx.setRange) }, chartHost),
    setup,
  ];
}

export { rich };
