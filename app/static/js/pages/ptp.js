import { el, fmtNs, fmtNumber, isNum, rich } from "../util.js";
import { card, tile, kv, info, badge, emptyNote, copyButton } from "../ui.js";
import { lineChart } from "../charts.js";
import { hardwareData, matrixList } from "./hardware.js";

const ACCURACY = { "0x20": "25 ns", "0x21": "100 ns", "0x22": "250 ns", "0x23": "1 µs", "0x24": "2,5 µs",
  "0x25": "10 µs", "0x26": "25 µs", "0x27": "100 µs", "0x28": "250 µs", "0x29": "1 ms", "0x2a": "2,5 ms",
  "0x2b": "10 ms", "0x2c": "25 ms", "0x2d": "100 ms", "0x2e": "250 ms", "0x2f": "1 s", "0x30": "10 s",
  "0x31": "> 10 s", "0xfe": "unbekannt" };

// Erklärung je Prüfpunkt (Schlüssel aus devices.ptp_readiness).
const CHECK_HELP = {
  host_network: "hw_network", interface: "ptp_interface", hardware_timestamps: "nic_hw_timestamps",
  phc_device: "phc", candidates: "hw_nic_class", capability: "hw_net_admin", network: "ptp_chk_network",
  clients: "ptp_chk_clients",
};

function checklist(checks, report) {
  const perms = report?.permissions;
  return el("ul", { class: "checklist" }, (checks || []).map((raw) => {
    let c = raw;
    // Die Rechte lassen sich über den Hardware-Check echt prüfen statt nur grau zu erklären.
    if (c.key === "capability" && perms && typeof perms.net_admin === "boolean") {
      const ok = perms.net_admin && perms.net_raw !== false;
      const missing = [perms.net_admin ? null : "NET_ADMIN", perms.net_raw === false ? "NET_RAW" : null].filter(Boolean);
      c = { ...c, ok, title: "Rechte: NET_ADMIN / NET_RAW", detail: ok
        ? "Der Container darf Hardware-Zeitstempel einschalten und PTP-Pakete senden."
        : `Es fehlt ${missing.join(" und ")}. In der Compose-Datei „cap_add: [${missing.join(", ")}]“ ergänzen und den Container neu erzeugen (docker compose up -d) – sonst meldet ptp4l „ioctl SIOCSHWTSTAMP failed“.` };
    }
    const state = c.ok === true ? "ok" : c.ok === false ? (c.warn ? "warn" : "fail") : "note";
    const icon = { ok: "✓", fail: "✕", warn: "!", note: "i" }[state];
    return el("li", { "data-state": state }, el("span", { class: "check-icon", "aria-hidden": "true", text: icon }),
      el("div", {}, el("div", { class: "hw-row-head" }, el("strong", { text: c.title }), CHECK_HELP[c.key] ? info(CHECK_HELP[c.key], c.title) : null),
        el("p", { text: c.detail })));
  }));
}

const NIC_CLASS = { good: ["PTP-tauglich", "good"], limited: ["eingeschränkt", "warn"], none: ["nur Software", "muted"],
  virtual: ["virtuell – nur Software", "warn"] };

function nicTable(nics, report) {
  if (!nics || !nics.length) return emptyNote("Keine Netzwerkkarten gefunden.");
  const yes = (v) => (v ? "ja" : "nein");
  const hw = new Map((report?.ptp?.interfaces || []).map((n) => [n.name, n]));
  const head = (text, help) => el("th", {}, text, " ", info(help, text));
  return el("div", { class: "table-scroll" }, el("table", {},
    el("thead", {}, el("tr", {}, head("Interface", "ptp_interface"), head("Treiber", "nic_driver"), head("Zustand", "nic_state"),
      head("HW-Zeitstempel", "nic_hw_timestamps"), head("PTP-Uhr", "phc"), head("Eignung", "nic_suitability"))),
    el("tbody", {}, nics.map((n) => {
      const extra = hw.get(n.name);
      const cls = extra && NIC_CLASS[extra.nic_class];
      const verdict = cls ? badge(cls[0], cls[1], extra.nic_note || null)
        : n.ptp_hardware ? badge("PTP-tauglich", "good")
          : n.virtual_nic ? badge("virtuell – nur Software", "warn") : badge("nur Software", "muted");
      return el("tr", {},
        el("td", { class: "mono", text: n.name }),
        el("td", { text: n.driver || (n.physical ? "?" : "virtuell") }),
        el("td", { text: n.operstate || "–" }),
        el("td", { text: isNum(n.hardware_tx) || n.hardware_tx !== undefined ? `${yes(n.hardware_tx)} / ${yes(n.hardware_rx)}` : "–" }),
        el("td", { class: "mono", text: n.phc || "keine" }),
        el("td", { class: "wrap-cell" }, verdict, extra?.passthrough ? badge("Passthrough", "good", "PCI-Passthrough erkannt") : null,
          extra?.nic_note ? el("div", { class: "sub", text: extra.nic_note }) : null));
    }))));
}

const COMPOSE = `services:
  ntp-gui:
    image: ghcr.io/congp20/ntp-gui:latest
    network_mode: host            # PTP braucht die echte Netzwerkkarte
    cap_add: [SYS_TIME, NET_ADMIN, NET_RAW]
    devices:
      - /dev/ptp0:/dev/ptp0       # PTP-Uhr der Karte (siehe Tabelle)
      - /dev/ttyAMA0:/dev/ttyAMA0 # GPS am UART (USB-Stick: /dev/ttyACM0)
      - /dev/pps0:/dev/pps0       # PPS – ohne ihn ist ein Grandmaster kaum sinnvoll
    environment:
      PTP_ENABLE: "true"
      PTP_INTERFACE: eth0
      PTP_MODE: master            # chrony stellt die Systemuhr nach GPS/PPS,
                                  # phc2sys kopiert sie in die PTP-Uhr der Karte,
                                  # ptp4l verteilt diese Uhr im Netz
      PHC2SYS_ENABLE: "true"      # Pflicht: koppelt Systemuhr → PTP-Uhr der Karte
                                  # (ohne phc2sys läuft die Kartenuhr frei)
      GPS_ENABLE: "true"
      GPS_DEVICE: /dev/ttyAMA0
      GPS_PPS_DEVICE: /dev/pps0
    volumes:
      - chrony-data:/var/lib/chrony
volumes:
  chrony-data:`;

// Die Seite wird alle paar Sekunden neu aufgebaut – aufgeklappte Details sollen offen bleiben.
function keepOpen(ctx, id) {
  return { class: "more", open: ctx.uiState[id] ? true : null,
    ontoggle: (event) => { ctx.uiState[id] = event.currentTarget.open; } };
}

export function render(ctx) {
  const { status, history } = ctx;
  const ptp = status.ptp || {};
  const devices = ctx.data("devices", "/api/devices", 30);
  const report = hardwareData(ctx);
  const matrixRows = (report?.matrix || []).filter((m) => ["ptp_hw", "ptp_sw", "ptp_to_ntp", "gps_to_ptp"].includes(m.key));
  const masterMode = ptp.is_grandmaster || (status.config || {}).ptp_mode === "master";
  const out = [];

  out.push(card("Was ist PTP – und brauche ich das?", { help: "ptp", class: "explain" },
    el("p", {}, rich("**PTP** (IEEE 1588) verteilt Zeit im LAN auf **Nanosekunden** genau. Der Trick: Die Netzwerkkarte stempelt jedes Paket selbst, Verzögerungen in Betriebssystem und Treibern fallen weg.")),
    el("div", { class: "compare" },
      el("div", { class: "compare-col" }, el("h3", { text: "Lohnt sich für" }), el("ul", {},
        el("li", {}, rich("Audio/Video über IP (**AES67** – Dante nur im AES67-Modus –, **Ravenna**), Broadcast")),
        el("li", {}, rich("Messaufbauten, Datenerfassung, Kameras mit Zeitstempeln")),
        el("li", {}, rich("Lernen und Experimentieren im Homelab")))),
      el("div", { class: "compare-col" }, el("h3", { text: "Nicht nötig für" }), el("ul", {},
        el("li", {}, rich("PCs, Server, Smart-Home, Logs, Zertifikate – dafür reicht **NTP** völlig")),
        el("li", {}, rich("Geräte ohne PTP-Unterstützung (Windows nur eingeschränkt, macOS gar nicht)"))))),
    emptyNote("Dieser Server macht beides gleichzeitig: PTP für Geräte, die es können, NTP für alle anderen. Natives Dante nutzt PTPv1 – das kann linuxptp nicht; Dante-Geräte daher in den AES67-Modus schalten."),
    el("details", keepOpen(ctx, "ptpReq"), el("summary", { text: "Alle Voraussetzungen im Detail" }), el("p", {}, rich(
      "1. **Netzwerkkarte mit Hardware-Zeitstempeln** und eigener PTP-Uhr – geprüft unten. Gut: Intel i210/i211/i225/i226/X550, Raspberry Pi CM4/CM5. Virtuelle Karten in VMs können es nicht.  "
      + "2. **Host-Netzwerk** und Rechte `NET_ADMIN`/`NET_RAW`, das Gerät `/dev/ptpN` im Container.  "
      + "3. **Eine gute Referenz**: Als Grandmaster ist PTP nur mit GPS **plus PPS** sinnvoll – sonst verteilt man Nanosekunden-genau eine Zeit, die auf Millisekunden falsch ist. Als Slave übernimmt der Server die Zeit eines vorhandenen Grandmasters.  "
      + "4. **PTP-fähige Clients** (Linux mit linuxptp, viele Audio- und Netzwerkgeräte).  "
      + "5. **Switches**: einfache gehen, kosten aber Genauigkeit (Mikrosekunden). Für Nanosekunden: Switches mit Transparent- oder Boundary-Clock oder Direktverbindung."))),
    el("details", keepOpen(ctx, "ptpGm"), el("summary", {}, "So wird dieser Server zum GPS-Grandmaster ", info("ptp_grandmaster_flow", "Grandmaster")),
      el("ol", { class: "steps gm-flow" },
        el("li", {}, rich("**chrony** stellt die Systemuhr nach GPS – mit **PPS** auf Mikrosekunden genau.")),
        el("li", {}, rich("**phc2sys** kopiert die Systemuhr laufend in die PTP-Uhr der Netzwerkkarte (`/dev/ptp0`) und rechnet dabei die 37 s zwischen UTC und der PTP-Zeitskala TAI ein. Dafür muss „Systemuhr und PTP-Uhr koppeln (phc2sys)“ an sein (`PHC2SYS_ENABLE=true`); die Richtung wählt ntp-gui im Modus „Master“ automatisch. chrony stellt dabei weiter die Systemuhr.")),
        el("li", {}, rich("**ptp4l** verteilt die Uhr der Karte als Grandmaster an alle PTP-Clients im LAN."))),
      el("p", {}, rich("Im Modus **Slave** läuft es umgekehrt: ptp4l übernimmt die Zeit eines anderen Grandmasters in die Karte, chrony liest sie über `PHC_REFCLOCK` (oder phc2sys stellt die Systemuhr, dann läuft chrony mit `-x`) und verteilt sie per NTP weiter.")))));

  out.push(card("Voraussetzungen auf diesem System", { help: "ptp_requirements",
    sub: "Live geprüft. Graue Punkte lassen sich nicht automatisch prüfen." },
    matrixRows.length ? [el("h3", { class: "mini-head" }, "Was mit dieser Hardware geht ", info("hw_matrix", "Was mit dieser Hardware geht")),
      matrixList(matrixRows),
      el("p", { class: "hw-more" }, el("a", { href: "#/hardware", text: "Alle Fähigkeiten im Hardware-Check →" })),
      el("h3", { class: "mini-head hw-gap" }, "Einzelprüfungen ", info("ptp_requirements", "Einzelprüfungen"))] : null,
    devices ? checklist(devices.ptp_checks, report) : emptyNote("Wird geprüft …")));
  out.push(card("Netzwerkkarten", { help: "phc", sub: "Fähigkeiten laut `ethtool -T`." },
    devices ? nicTable(devices.interfaces, report) : emptyNote("Wird geprüft …")));

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
        ["Interface", ptp.interface, "ptp_interface"],
        ["Domain", ptp.domainNumber ?? ptp.domain, "ptp_domain"],
        ["Transport", ptp.transport, "ptp_transport"],
        ["Portzustand", ptp.port_state_label || ptp.portState, "port_state"],
        ["Servo", metrics.servo_state || "–", "ptp_servo"],
        ["Frequenzkorrektur", isNum(metrics.freq_ppb) ? `${metrics.freq_ppb} ppb` : "–", "ptp_freq"],
        ["RMS / Max", isNum(metrics.rms_ns) ? `${fmtNs(metrics.rms_ns)} / ${fmtNs(metrics.max_ns)}` : "–", "ptp_rms"],
        ["phc2sys", ptp.phc2sys ? (masterMode ? "an – überträgt die Systemuhr in die Karte" : "an – stellt die Systemuhr") : "aus", "phc2sys"],
      ]),
      kv([
        ["Grandmaster", ptp.grandmasterIdentity || ptp.gmIdentity || "–", "grandmaster"],
        ["Eigene Kennung", ptp.clockIdentity || "–", "ptp_clock_identity"],
        ["Steps Removed", ptp.stepsRemoved ?? "–", "steps_removed"],
        ["Clock Class (GM)", ptp["gm.ClockClass"] ?? "–", "clock_class"],
        ["Genauigkeit (GM)", ACCURACY[String(ptp["gm.ClockAccuracy"] || "").toLowerCase()] || ptp["gm.ClockAccuracy"] || "–", "clock_accuracy"],
        ["Priority 1 / 2 (GM)", `${ptp.grandmasterPriority1 ?? "–"} / ${ptp.grandmasterPriority2 ?? "–"}`, "grandmaster"],
        ["UTC-Offset", isNum(ptp.currentUtcOffset) ? `${ptp.currentUtcOffset} s` : "–", "utc_offset"],
        ["Zeit rückverfolgbar", ptp.timeTraceable === "1" || ptp.timeTraceable === true ? "ja" : "nein", "ptp_time_traceable"],
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
      el("div", { class: "snippet" }, el("div", { class: "snippet-head" }, el("strong", { text: "docker-compose.yml – GPS-Grandmaster" }), copyButton(COMPOSE)),
        el("pre", { class: "code", text: COMPOSE })),
      el("p", { class: "hw-note" }, rich("Ohne PPS die Zeilen für `/dev/pps0` und `GPS_PPS_DEVICE` weglassen – dann aber besser **Slave** statt Master. Welche Geräte es bei dir gibt, zeigt der **Hardware-Check**.")),
      el("p", {}, el("a", { href: "#/einstellungen?s=ptp", class: "button", text: "Zu den PTP-Einstellungen" }))));
  }
  if (ptp.enabled && (ptp.log || []).length) {
    out.push(card("ptp4l-Log", {}, el("pre", { class: "log", text: ptp.log.join("\n") })));
  }
  return out;
}
