import { el, fmtNs, fmtNumber, isNum, rich } from "../util.js";
import { card, tile, kv, info, badge, emptyNote } from "../ui.js";
import { lineChart } from "../charts.js";

const ACCURACY = { "0x20": "25 ns", "0x21": "100 ns", "0x22": "250 ns", "0x23": "1 µs", "0x24": "2,5 µs",
  "0x25": "10 µs", "0x26": "25 µs", "0x27": "100 µs", "0x28": "250 µs", "0x29": "1 ms", "0x2a": "2,5 ms",
  "0x2b": "10 ms", "0x2c": "25 ms", "0x2d": "100 ms", "0x2e": "250 ms", "0x2f": "1 s", "0x30": "10 s",
  "0x31": "> 10 s", "0xfe": "unbekannt" };

function checklist(checks) {
  return el("ul", { class: "checklist" }, (checks || []).map((c) => {
    const state = c.ok === true ? "ok" : c.ok === false ? (c.warn ? "warn" : "fail") : "note";
    const icon = { ok: "✓", fail: "✕", warn: "!", note: "i" }[state];
    return el("li", { "data-state": state }, el("span", { class: "check-icon", "aria-hidden": "true", text: icon }),
      el("div", {}, el("strong", { text: c.title }), el("p", { text: c.detail })));
  }));
}

function nicTable(nics) {
  if (!nics || !nics.length) return emptyNote("Keine Netzwerkkarten gefunden.");
  const yes = (v) => (v ? "ja" : "nein");
  return el("div", { class: "table-scroll" }, el("table", {},
    el("thead", {}, el("tr", {}, ["Interface", "Treiber", "Zustand", "HW-Zeitstempel", "PTP-Uhr", "Eignung"].map((h) => el("th", { text: h })))),
    el("tbody", {}, nics.map((n) => el("tr", {},
      el("td", { class: "mono", text: n.name }),
      el("td", { text: n.driver || (n.physical ? "?" : "virtuell") }),
      el("td", { text: n.operstate || "–" }),
      el("td", { text: isNum(n.hardware_tx) || n.hardware_tx !== undefined ? `${yes(n.hardware_tx)} / ${yes(n.hardware_rx)}` : "–" }),
      el("td", { class: "mono", text: n.phc || "keine" }),
      el("td", {}, n.ptp_hardware ? badge("PTP-tauglich", "good")
        : n.virtual_nic ? badge("virtuell – nur Software", "warn") : badge("nur Software", "muted")))))));
}

const COMPOSE = `services:
  ntp-gui:
    image: ghcr.io/congp20/ntp-gui:latest
    network_mode: host            # PTP braucht die echte Netzwerkkarte
    cap_add: [SYS_TIME, NET_ADMIN, NET_RAW]
    devices:
      - /dev/ptp0:/dev/ptp0       # PTP-Uhr der Karte (siehe Tabelle)
      - /dev/ttyACM0:/dev/ttyACM0 # GPS – ideal mit PPS
    volumes:
      - chrony-data:/var/lib/chrony
volumes:
  chrony-data:`;

export function render(ctx) {
  const { status, history } = ctx;
  const ptp = status.ptp || {};
  const devices = ctx.data("devices", "/api/devices", 30);
  const out = [];

  out.push(card("Was ist PTP – und brauche ich das?", { help: "ptp", class: "explain" },
    el("p", {}, rich("**PTP** (IEEE 1588) verteilt Zeit im LAN auf **Nanosekunden** genau. Der Trick: Die Netzwerkkarte stempelt jedes Paket selbst, Verzögerungen in Betriebssystem und Treibern fallen weg.")),
    el("div", { class: "compare" },
      el("div", { class: "compare-col" }, el("h3", { text: "Lohnt sich für" }), el("ul", {},
        el("li", {}, rich("Audio/Video über IP (**AES67, Dante, Ravenna**), Broadcast")),
        el("li", {}, rich("Messaufbauten, Datenerfassung, Kameras mit Zeitstempeln")),
        el("li", {}, rich("Lernen und Experimentieren im Homelab")))),
      el("div", { class: "compare-col" }, el("h3", { text: "Nicht nötig für" }), el("ul", {},
        el("li", {}, rich("PCs, Server, Smart-Home, Logs, Zertifikate – dafür reicht **NTP** völlig")),
        el("li", {}, rich("Geräte ohne PTP-Unterstützung (Windows nur eingeschränkt, macOS gar nicht)"))))),
    emptyNote("Dieser Server macht beides gleichzeitig: PTP für Geräte, die es können, NTP für alle anderen."),
    el("details", { class: "more" }, el("summary", { text: "Alle Voraussetzungen im Detail" }), el("p", {}, rich(
      "1. **Netzwerkkarte mit Hardware-Zeitstempeln** und eigener PTP-Uhr – geprüft unten. Gut: Intel i210/i211/i225/i226/X550, Raspberry Pi CM4/CM5. Virtuelle Karten in VMs können es nicht.  "
      + "2. **Host-Netzwerk** und Rechte `NET_ADMIN`/`NET_RAW`, das Gerät `/dev/ptpN` im Container.  "
      + "3. **Eine gute Referenz**: Als Grandmaster ist PTP nur mit GPS **plus PPS** sinnvoll – sonst verteilt man Nanosekunden-genau eine Zeit, die auf Millisekunden falsch ist. Als Slave übernimmt der Server die Zeit eines vorhandenen Grandmasters.  "
      + "4. **PTP-fähige Clients** (Linux mit linuxptp, viele Audio- und Netzwerkgeräte).  "
      + "5. **Switches**: einfache gehen, kosten aber Genauigkeit (Mikrosekunden). Für Nanosekunden: Switches mit Transparent- oder Boundary-Clock oder Direktverbindung.")))));

  out.push(card("Voraussetzungen auf diesem System", { help: "ptp_requirements",
    sub: "Live geprüft. Graue Punkte lassen sich nicht automatisch prüfen." },
    devices ? checklist(devices.ptp_checks) : emptyNote("Wird geprüft …")));
  out.push(card("Netzwerkkarten", { help: "phc", sub: "Fähigkeiten laut `ethtool -T`." },
    devices ? nicTable(devices.interfaces) : emptyNote("Wird geprüft …")));

  if (ptp.enabled && ptp.running) {
    const metrics = ptp.log_metrics || {};
    out.unshift(el("div", { class: "stat-row" },
      tile({ label: "Rolle", help: "port_state", value: ptp.is_grandmaster ? "Grandmaster" : (ptp.portState || "–"),
        tone: ptp.synchronised ? "good" : "warn", note: ptp.port_state_label || "" }),
      tile({ label: "Offset zum Master", help: "offset_from_master", value: ptp.is_grandmaster ? "–" : fmtNs(ptp.offset_ns),
        tone: "muted", note: ptp.is_grandmaster ? "dieser Server ist die Referenz" : `RMS ${isNum(metrics.rms_ns) ? fmtNs(metrics.rms_ns) : "–"}` }),
      tile({ label: "Laufzeit", help: "mean_path_delay", value: fmtNs(ptp.meanPathDelay ?? metrics.path_delay_ns), tone: "muted",
        note: "eine Richtung" }),
      tile({ label: "Zeitstempel", help: "timestamping", value: ptp.time_stamping === "hardware" ? "Hardware" : "Software",
        tone: ptp.time_stamping === "hardware" ? "good" : "warn", note: ptp.interface || "" })));

    out.push(card("PTP im Detail", { help: "grandmaster" }, el("div", { class: "grid-2" },
      kv([
        ["Interface", ptp.interface],
        ["Domain", ptp.domainNumber ?? ptp.domain, "ptp_domain"],
        ["Transport", ptp.transport, "ptp_transport"],
        ["Portzustand", ptp.port_state_label || ptp.portState, "port_state"],
        ["Servo", metrics.servo_state || "–", "ptp_servo"],
        ["Frequenzkorrektur", isNum(metrics.freq_ppb) ? `${metrics.freq_ppb} ppb` : "–", "ptp_freq"],
        ["RMS / Max", isNum(metrics.rms_ns) ? `${fmtNs(metrics.rms_ns)} / ${fmtNs(metrics.max_ns)}` : "–", "ptp_rms"],
        ["phc2sys", ptp.phc2sys ? "an – stellt die Systemuhr" : "aus", "phc2sys"],
      ]),
      kv([
        ["Grandmaster", ptp.grandmasterIdentity || ptp.gmIdentity || "–", "grandmaster"],
        ["Eigene Kennung", ptp.clockIdentity || "–"],
        ["Steps Removed", ptp.stepsRemoved ?? "–", "steps_removed"],
        ["Clock Class (GM)", ptp["gm.ClockClass"] ?? "–", "clock_class"],
        ["Genauigkeit (GM)", ACCURACY[String(ptp["gm.ClockAccuracy"] || "").toLowerCase()] || ptp["gm.ClockAccuracy"] || "–", "clock_accuracy"],
        ["Priority 1 / 2 (GM)", `${ptp.grandmasterPriority1 ?? "–"} / ${ptp.grandmasterPriority2 ?? "–"}`, "grandmaster"],
        ["UTC-Offset", isNum(ptp.currentUtcOffset) ? `${ptp.currentUtcOffset} s` : "–", "utc_offset"],
        ["Zeit rückverfolgbar", ptp.timeTraceable === "1" || ptp.timeTraceable === true ? "ja" : "nein"],
      ]))));

    const offsetHost = el("div", { class: "chart-host" });
    const delayHost = el("div", { class: "chart-host" });
    ctx.afterRender(() => {
      lineChart(offsetHost, { series: [{ id: "ptp-off", label: "Offset", color: "var(--accent)",
        points: history.map((s) => [s.t, s.ptp?.offset_ns ?? null]) }], format: (v) => fmtNs(v),
        axisFormat: (v) => `${fmtNumber(v, 0)} ns`, emptyText: ptp.is_grandmaster ? "Als Grandmaster gibt es keinen Offset zu einem Master" : undefined });
      lineChart(delayHost, { series: [{ id: "ptp-delay", label: "Laufzeit", color: "var(--accent)",
        points: history.map((s) => [s.t, s.ptp?.delay_ns ?? null]) }], format: (v) => fmtNs(v),
        axisFormat: (v) => `${fmtNumber(v, 0)} ns`, zeroLine: false });
    });
    out.push(el("div", { class: "grid-2" },
      card("Offset zum Master", { help: "offset_from_master" }, offsetHost),
      card("Laufzeit zum Master", { help: "mean_path_delay" }, delayHost)));
    if ((metrics.transitions || []).length) {
      out.push(card("Letzte Zustandswechsel", { help: "port_state" }, el("ol", { class: "transitions" },
        metrics.transitions.map((t) => el("li", {}, el("span", { class: "mono", text: `${t.from} → ${t.to}` }),
          el("span", { class: "muted", text: ` (${t.event})` }))))));
    }
  } else if (ptp.enabled) {
    out.unshift(card("PTP ist eingeschaltet, läuft aber nicht", { class: "card-alert" },
      el("p", {}, rich("ptp4l antwortet nicht. Die häufigsten Gründe stehen in der Prüfliste unten. Im Log steht der konkrete Fehler – z. B. `ioctl SIOCSHWTSTAMP failed` (fehlende Rechte oder keine Hardware-Zeitstempel).")),
    ));
  } else {
    out.push(card("PTP einschalten", { help: "ptp_requirements" },
      el("p", {}, rich("PTP ist aus. Zum Einschalten in den Einstellungen das Interface wählen und PTP aktivieren. Der Container muss dafür im Host-Netzwerk laufen – so sieht die Compose-Datei dann aus:")),
      el("pre", { class: "code", text: COMPOSE }),
      el("p", {}, el("a", { href: "#/einstellungen?s=ptp", class: "button", text: "Zu den PTP-Einstellungen" }))));
  }
  if (ptp.enabled && (ptp.log || []).length) {
    out.push(card("ptp4l-Log", {}, el("pre", { class: "log", text: ptp.log.join("\n") })));
  }
  return out;
}
