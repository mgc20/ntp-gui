// Hardware-Check: Was kann dieses Gerät von dem, was ntp-gui kann?
// Alle Werte aus /api/hardware landen nur als Text im DOM (el/textContent).
import { el, apiGet, fmtNumber, fmtTime, isNum, rich } from "../util.js";
import { card, kv, info, badge, emptyNote, toast, copyButton } from "../ui.js";

// Kein Neuaufbau alle paar Sekunden: Kopierbare Ausschnitte bleiben markierbar,
// aufgeklappte Details bleiben offen. Neu geladen wird per Knopf oder Seitenwechsel.
export const live = false;

// --- Gemeinsame Bausteine (auch für GPS- und PTP-Seite) ------------------------

export const STATUS = {
  ok: { label: "geht", tone: "good", state: "ok", icon: "✓" },
  limited: { label: "eingeschränkt", tone: "warn", state: "warn", icon: "!" },
  change: { label: "geht mit Änderung", tone: "info", state: "change", icon: "→" },
  no: { label: "geht nicht", tone: "crit", state: "fail", icon: "✕" },
  unknown: { label: "unklar", tone: "muted", state: "note", icon: "?" },
};

export const PPS_PATH = {
  none: { label: "kein PPS möglich", text: "Über USB-CDC (Modem-Gerät) kommt kein Sekundenimpuls beim Rechner an – die Leitung trägt nur NMEA-/UBX-Daten." },
  dcd_usb: { label: "PPS über DCD (USB-Seriell)", text: "Nur wenn das Board den Impuls auf die DCD-Leitung legt. Begrenzt durch den USB-Takt: etwa ±1 ms." },
  dcd_uart: { label: "PPS über DCD (UART)", text: "Echte serielle Schnittstelle mit Impuls auf DCD: wenige Mikrosekunden." },
  gpio: { label: "PPS über GPIO", text: "Der Impuls kommt über einen GPIO-Pin (pps-gpio) direkt in den Kernel: etwa 1 µs." },
  possible_gpio: { label: "PPS über GPIO möglich", text: "Empfänger am Pi-UART, aber keine PPS-Quelle aktiv. Hat dein HAT einen PPS-Pin (meist GPIO18 oder GPIO4), schaltet `dtoverlay=pps-gpio,gpiopin=18` in `/boot/firmware/config.txt` ihn frei." },
  unknown: { label: "unklar", text: "Die Schnittstelle ließ sich nicht eindeutig zuordnen." },
};

const PPS_STATE = {
  live: { label: "live", tone: "good", text: "Impulse kommen regelmäßig an." },
  stale: { label: "keine Impulse", tone: "warn", text: "Gerät da, aber gerade keine Impulse – noch kein GPS-Fix? Antenne, Kabel oder Pin prüfen." },
  never: { label: "noch nie", tone: "crit", text: "Seit dem Systemstart kam kein einziger Impuls – Overlay-Pin (gpiopin=) und Verkabelung prüfen." },
  unknown: { label: "unbekannt", tone: "muted", text: "Der Impulszähler ließ sich nicht lesen." },
};

const LADDER = [
  { id: "nmea", label: "NMEA", value: "~10 ms" },
  { id: "dcd_usb", label: "USB-DCD", value: "~1 ms" },
  { id: "dcd_uart", label: "UART-DCD", value: "~5 µs" },
  { id: "gpio", label: "GPIO", value: "~1 µs" },
  { id: "ptp_hw", label: "PTP-HW", value: "< 1 µs" },
];

export function hardwareData(ctx) {
  const cached = ctx.data("hardware", "/api/hardware", 30);
  if (fresh && (!cached || (fresh.generated || 0) >= (cached.generated || 0))) return fresh;
  return cached;
}

let fresh = null;
let busy = false;

function snippet(code, title) {
  const pre = el("pre", { class: "code", text: code });
  return el("div", { class: "snippet" },
    el("div", { class: "snippet-head" }, el("strong", { text: title || "Änderung" }), copyButton(code, pre)),
    pre);
}

// Eine Zeile der Fähigkeitsmatrix im Stil der PTP-Prüfliste.
export function matrixList(rows) {
  if (!rows || !rows.length) return emptyNote("Der Server hat keine Ergebnisse geliefert – „Neu prüfen“ versuchen oder das Container-Log ansehen.");
  return el("ul", { class: "checklist hw-matrix" }, rows.map((row) => {
    const s = STATUS[row.status] || STATUS.unknown;
    return el("li", { "data-state": s.state, "data-active": row.active ? "true" : null },
      el("span", { class: "check-icon", "aria-hidden": "true", text: s.icon }),
      el("div", { class: "hw-row-body" },
        el("div", { class: "hw-row-head" },
          el("strong", { text: row.title || row.key }),
          info(`hw_${row.key}`, row.title),
          badge(s.label, s.tone),
          row.active ? badge("aktiv", "info", "In den Einstellungen eingeschaltet") : null),
        el("p", { text: row.text || "" }),
        row.accuracy ? el("p", { class: "hw-accuracy" }, el("span", { class: "muted", text: "Genauigkeit: " }),
          el("span", { class: "mono", text: row.accuracy }), " ", info("hw_accuracy", "Genauigkeit")) : null,
        row.fix ? snippet(row.fix, row.status === "change" ? "So geht es" : row.status === "no" ? "Nur mit anderer Hardware" : "Hinweis") : null));
  }));
}

// Waagerechte Treppe der Genauigkeitsstufen; Farbe ist nie die einzige Kennzeichnung.
export function accuracyLadder(receiver, report) {
  const { current, possible } = ladderLevels(receiver, report);
  const steps = LADDER.map((step) => {
    const mark = step.id === current ? "current" : step.id === possible ? "possible" : null;
    return el("li", { class: "ladder-step", "data-mark": mark, "aria-current": mark === "current" ? "true" : null },
      el("span", { class: "ladder-bar", "aria-hidden": "true" }),
      el("span", { class: "ladder-label", text: step.label }),
      el("span", { class: "ladder-value", text: step.value }),
      el("span", { class: "ladder-mark", text: mark === "current" ? "▲ jetzt" : mark === "possible" ? "◇ möglich" : "" }));
  });
  const currentStep = LADDER.find((s) => s.id === current);
  const possibleStep = LADDER.find((s) => s.id === possible);
  const summary = `Jetzt: ${currentStep ? `${currentStep.label} (${currentStep.value})` : "unbekannt"}`
    + (possibleStep ? `, möglich: ${possibleStep.label} (${possibleStep.value})` : "");
  return el("div", { class: "ladder" },
    el("div", { class: "ladder-head" }, el("span", { text: "Genauigkeitsstufen" }), info("hw_ladder", "Genauigkeitsstufen"),
      el("span", { class: "ladder-axis", text: "ungenau → genau" })),
    el("ol", { class: "ladder-steps", "aria-label": `Genauigkeitsstufen. ${summary}` }, steps),
    el("p", { class: "ladder-legend", text: summary }));
}

function ladderLevels(receiver, report) {
  const pps = report?.pps || [];
  const liveKind = (kind) => pps.some((p) => p.kind === kind && p.state === "live");
  const path = receiver?.pps_path || "unknown";
  if (path === "gpio") return liveKind("gpio") ? { current: "gpio" } : { current: "nmea", possible: "gpio" };
  if (path === "dcd_uart") return liveKind("ldisc") ? { current: "dcd_uart" } : { current: "nmea", possible: "dcd_uart" };
  if (path === "dcd_usb") return report?.gps?.gpsd_pps?.seen ? { current: "dcd_usb" } : { current: "nmea", possible: "dcd_usb" };
  if (path === "possible_gpio") return { current: "nmea", possible: "gpio" };
  return { current: receiver ? "nmea" : null };
}

export function pickReceiver(report) {
  const receivers = report?.gps?.receivers || [];
  return receivers.find((r) => r.configured) || receivers[0] || null;
}

const yesNo = (value, yes = "ja", no = "nein") => (value === true ? yes : value === false ? no : "unbekannt");

// Fehlt ein Abschnitt im Bericht ganz, wissen wir nichts – dann nicht „nein“/„keine“ behaupten.
const NO_DATA = "Keine Daten – der Server hat für diesen Teil keine Ergebnisse geliefert. „Neu prüfen“ versuchen oder das Container-Log ansehen.";
function missing(section) { return section === null || section === undefined; }

function flag(value, good = true) {
  if (value === null || value === undefined) return badge("unbekannt", "muted");
  const ok = good ? value : !value;
  return badge(value ? "ja" : "nein", ok ? "good" : "warn");
}

function presence(item) {
  const parts = [];
  parts.push(badge(item.host_present ? "am Host" : "nicht am Host", item.host_present ? "good" : "muted"));
  parts.push(badge(item.in_container ? "im Container" : "nicht im Container", item.in_container ? "good" : "warn"));
  if (item.in_container) {
    parts.push(item.usable === true ? badge("nutzbar", "good")
      : item.usable === false ? badge("nicht nutzbar", "crit") : badge("nutzbar?", "muted"));
  }
  return el("span", { class: "badge-row" }, parts);
}

// --- Karten ------------------------------------------------------------------------

function receiverBlock(r, report) {
  const usb = r.usb;
  const gpsd = r.gpsd;
  const path = PPS_PATH[r.pps_path] || PPS_PATH.unknown;
  const gpsdText = gpsd ? [gpsd.driver, gpsd.generation, gpsd.module, gpsd.subtype && !gpsd.generation ? gpsd.subtype : null]
    .filter(Boolean).join(" · ") || "–" : "nicht von gpsd erkannt";
  return el("article", { class: "hw-item" },
    el("div", { class: "hw-item-head" },
      el("h3", { text: r.product || r.tty || "Empfänger" }),
      r.configured ? badge("eingetragen", "info", "Steht in den Einstellungen als GPS-Gerät") : null,
      gpsd?.timing ? badge("Timing-Modul", "good") : null),
    el("div", { class: "verdict", "data-tone": r.tone || "info" },
      el("span", { class: "verdict-label" }, "Urteil ", info("hw_verdict", "Urteil")),
      el("p", { text: r.verdict || "–" })),
    el("div", { class: "hw-item-grid" },
      kv([
        ["Schnittstelle", `${r.interface || "–"}${r.tty_driver ? ` · ${r.tty_driver}` : ""}`, "hw_interface"],
        ["Gerät", r.dev || "–", "hw_device_path"],
        r.stable_path ? ["Stabiler Pfad", el("span", { class: "mono wrap", text: r.stable_path }), "hw_stable_path"] : null,
        ["Verfügbarkeit", presence(r), "hw_presence"],
        usb ? ["USB-Kennung", `${usb.vid}:${usb.pid}${isNum(usb.speed_mbit) ? ` · ${usb.speed_mbit} Mbit/s` : ""}`, "hw_usb_id"] : null,
        usb && (usb.manufacturer || usb.product) ? ["USB-Name", [usb.manufacturer, usb.product].filter(Boolean).join(" – "), "hw_usb_id"] : null,
      ]),
      kv([
        ["gpsd erkennt", gpsdText, "hw_gpsd_driver"],
        gpsd ? ["Von gpsd geöffnet", flag(gpsd.activated), "hw_gpsd_activated"] : null,
        gpsd ? ["Baudrate", isNum(gpsd.bps) ? `${fmtNumber(gpsd.bps)} Bd` : "automatisch", "gps_baud"] : null,
        ["PPS-Weg", path.label, "hw_pps_path"],
        ["Genauigkeit", r.accuracy || "–", "hw_accuracy"],
      ])),
    el("p", { class: "hw-note" }, rich(path.text)),
    accuracyLadder(r, report));
}

function gpsCard(report) {
  if (missing(report.gps)) return card("GPS-Empfänger", { help: "hw_receiver" }, emptyNote(NO_DATA));
  const receivers = report.gps.receivers || [];
  const gpsdPps = report.gps.gpsd_pps || {};
  const body = receivers.length ? receivers.map((r) => receiverBlock(r, report))
    : [emptyNote("Kein serieller GPS-Empfänger gefunden – weder am Host noch im Container. USB-Sticks erscheinen als `/dev/ttyACM0` oder `/dev/ttyUSB0`, GPS-HATs am Pi als `/dev/ttyAMA0` bzw. `/dev/serial0`."),
      accuracyLadder(null, report)];
  if (receivers.length) {
    body.push(kv([
      ["gpsd sieht PPS", gpsdPps.seen === false && (report.pps || []).some((p) => p.kind === "gpio" && p.state === "live")
        ? "nein – normal, chrony liest /dev/pps direkt" : yesNo(gpsdPps.seen), "hw_gpsd_pps"],
      ["NMEA-Verspätung (gpsd)", isNum(gpsdPps.toff_latency_ms) ? `${fmtNumber(gpsdPps.toff_latency_ms, 1)} ms` : "–", "hw_toff"],
    ]));
  }
  return card("GPS-Empfänger", { help: "hw_receiver" }, body);
}

function ppsCard(report) {
  if (!Array.isArray(report.pps)) return card("PPS-Quellen", { help: "hw_pps_sources" }, emptyNote(NO_DATA));
  const pps = report.pps;
  if (!pps.length) {
    return card("PPS-Quellen", { help: "hw_pps_sources" },
      emptyNote("Keine PPS-Quelle im Kernel. Für PPS über GPIO am Raspberry Pi: `dtoverlay=pps-gpio,gpiopin=18` in `/boot/firmware/config.txt`, neu starten – dann erscheint `/dev/pps0`."));
  }
  const kindLabel = { gpio: "GPIO", ldisc: "seriell (DCD)", phc: "Netzwerkkarte", unknown: "unbekannt" };
  const head = (text, help) => el("th", {}, text, " ", info(help, text));
  return card("PPS-Quellen", { help: "hw_pps_sources" },
    el("div", { class: "table-scroll" }, el("table", { class: "hw-table" },
      el("thead", {}, el("tr", {}, head("Gerät", "hw_device_path"), head("Art", "hw_pps_kind"), head("Impulse", "hw_pps_state"),
        el("th", { class: "num" }, "Rate ", info("hw_pps_rate", "Rate")), el("th", { class: "num" }, "Phase ", info("hw_pps_phase", "Phase")),
        head("Verfügbarkeit", "hw_presence"), head("Eingetragen", "hw_pps_configured"))),
      el("tbody", {}, pps.map((p) => {
        const s = PPS_STATE[p.state] || PPS_STATE.unknown;
        return el("tr", {},
          el("td", {}, el("div", { class: "mono", text: p.dev }), el("div", { class: "sub", text: [p.name, p.path].filter(Boolean).join(" · ") })),
          el("td", { text: kindLabel[p.kind] || p.kind || "–" }),
          el("td", { class: "wrap-cell" }, badge(s.label, s.tone), el("div", { class: "sub", text: p.error || s.text })),
          el("td", { class: "num", text: isNum(p.rate_hz) ? `${fmtNumber(p.rate_hz, 2)} Hz` : "–" }),
          el("td", { class: "num", text: isNum(p.phase_us) ? `${fmtNumber(p.phase_us, 1)} µs` : "–" }),
          el("td", {}, presence(p)),
          el("td", { text: p.configured ? "ja" : "nein" }));
      })))));
}

const NIC_CLASS = {
  good: ["gut", "good"], limited: ["eingeschränkt", "warn"], none: ["keine", "muted"],
  virtual: ["virtuell", "warn"], unknown: ["unklar", "muted"],
};

function ptpCard(report) {
  if (missing(report.ptp)) return card("PTP-Uhren und Netzwerkkarten", { help: "hw_ptp_clocks" }, emptyNote(NO_DATA));
  const clocks = report.ptp?.clocks || [];
  const nics = report.ptp?.interfaces || [];
  const head = (text, help, cls) => el("th", { class: cls || null }, text, " ", info(help, text));
  const kindLabel = { nic: "Netzwerkkarte", vm: "VM-Uhr", unknown: "unbekannt" };
  const clockTable = clocks.length ? el("div", { class: "table-scroll" }, el("table", { class: "hw-table" },
    el("thead", {}, el("tr", {}, head("Uhr", "phc"), head("Name", "hw_clock_name"), head("Art", "hw_ptp_kind"),
      head("Karte", "ptp_interface"), head("Pins / ext. Zeitst.", "hw_ptp_pins"), head("PPS", "hw_pps_available"),
      head("Verfügbarkeit", "hw_presence"))),
    el("tbody", {}, clocks.map((c) => el("tr", {},
      el("td", { class: "mono", text: c.dev }),
      el("td", { class: "mono", text: c.clock_name || "–" }),
      el("td", { text: kindLabel[c.kind] || c.kind || "–" }),
      el("td", { class: "mono", text: c.interface || "–" }),
      el("td", { class: "num", text: `${c.n_pins ?? "–"} / ${c.n_external_timestamps ?? "–"}` }),
      el("td", { text: yesNo(c.pps_available === 1 ? true : c.pps_available === 0 ? false : c.pps_available) }),
      el("td", { class: "wrap-cell" }, presence({ host_present: true, ...c }), c.error ? el("div", { class: "sub", text: c.error }) : null))))))
    : emptyNote("Keine PTP-Hardwareuhr (`/dev/ptp*`) im System – Hardware-PTP geht mit dieser Hardware nicht.");
  const nicTable = nics.length ? el("div", { class: "table-scroll" }, el("table", { class: "hw-table" },
    el("thead", {}, el("tr", {}, head("Interface", "ptp_interface"), head("Treiber", "nic_driver"), head("Zustand", "nic_state"),
      head("HW-Zeitstempel", "nic_hw_timestamps"), head("PTP-Uhr", "phc"), head("Eignung", "hw_nic_class"))),
    el("tbody", {}, nics.map((n) => {
      const [label, tone] = NIC_CLASS[n.nic_class] || NIC_CLASS.unknown;
      return el("tr", {},
        el("td", { class: "mono", text: n.name }),
        el("td", { text: n.driver || (n.physical ? "?" : "virtuell") }),
        el("td", { text: n.operstate || "–" }),
        el("td", { text: n.hardware_tx === undefined ? "–" : `${n.hardware_tx ? "ja" : "nein"} / ${n.hardware_rx ? "ja" : "nein"}` }),
        el("td", { class: "mono", text: n.phc || "keine" }),
        el("td", { class: "wrap-cell" }, el("span", { class: "badge-row" }, badge(label, tone),
          n.passthrough ? badge("Passthrough", "good", "PCI-Passthrough erkannt") : null),
          n.nic_note ? el("div", { class: "sub", text: n.nic_note }) : null));
    })))) : emptyNote("Keine Netzwerkkarten sichtbar.");
  const bridge = report.permissions?.network === "bridge";
  return card("PTP-Uhren und Netzwerkkarten", { help: "hw_ptp_clocks" },
    el("h3", { class: "mini-head" }, "PTP-Hardwareuhren ", info("hw_ptp_clocks", "PTP-Hardwareuhren")), clockTable,
    el("h3", { class: "mini-head hw-gap" }, "Netzwerkkarten ", info("hw_nic_class", "Netzwerkkarten")), nicTable,
    bridge ? el("p", { class: "hw-note" }, rich("Der Container läuft im **Bridge-Netz** und sieht nur seine virtuelle Karte. Die echten Karten des Hosts erscheinen erst mit `network_mode: host`.")) : null);
}

function permissionsCard(report) {
  const p = report.permissions || {};
  const plat = report.platform || {};
  const majors = report.majors || {};
  const modules = Object.entries(p.modules || {});
  const network = { host: "Host-Netz", bridge: "Bridge (Docker-Netz)", unknown: "unbekannt" }[p.network] || p.network || "–";
  const container = missing(report.platform) ? "unbekannt" : plat.container ? `${plat.container === "podman" ? "Podman" : "Docker"}${plat.docker_desktop ? " Desktop" : ""}${plat.wsl ? " (WSL2)" : ""}` : "kein Container erkannt";
  const body = [kv([
    ["Container", container, "hw_container"],
    ["Privilegiert", flag(p.privileged, false), "hw_privileged"],
    ["SYS_TIME (Uhr stellen)", flag(p.sys_time), "hw_sys_time"],
    ["NET_ADMIN (PTP-Zeitstempel)", flag(p.net_admin), "hw_net_admin"],
    ["NET_RAW (PTP über L2)", flag(p.net_raw), "hw_net_raw"],
    ["SYS_NICE", p.sys_nice === true ? "ja" : p.sys_nice === false ? "nein (wird nicht gebraucht)" : "unbekannt", "hw_sys_nice"],
    ["CapEff", el("span", { class: "mono", text: p.cap_eff || "–" }), "hw_caps"],
    ["Netzwerk", network, "hw_network"],
    ["/dev vom Host eingehängt", yesNo(p.dev_mounted), "hw_dev_mounted"],
    ["Kernel-Module", modules.length ? el("span", { class: "badge-row" }, modules.map(([name, loaded]) =>
      badge(`${name}${loaded ? "" : " –"}`, loaded ? "good" : "muted", loaded ? "geladen" : "nicht nachweisbar"))) : "–", "hw_modules"],
    ["Major-Nummer PPS / PTP", `${majors.pps ?? "–"} / ${majors.ptp ?? "–"}`, "hw_majors"],
  ])];
  if (isNum(majors.pps) || isNum(majors.ptp)) {
    const env = [isNum(majors.pps) ? `PPS_MAJOR=${majors.pps}` : null, isNum(majors.ptp) ? `PTP_MAJOR=${majors.ptp}` : null].filter(Boolean).join("\n");
    const rules = ["device_cgroup_rules:",
      isNum(majors.pps) ? `  - "c ${majors.pps}:* rwm"   # /dev/ppsN – PPS` : null,
      isNum(majors.ptp) ? `  - "c ${majors.ptp}:* rwm"   # /dev/ptpN – PTP-Hardwareuhr` : null].filter(Boolean).join("\n");
    body.push(el("p", { class: "hw-note" }, rich(p.dev_mounted
      ? "`/dev` ist eingehängt – damit der Container PPS- und PTP-Geräte auch **öffnen** darf, braucht er Regeln mit diesen Nummern. Für die All-in-one-Compose in die `.env` schreiben:"
      : "Wenn du `/dev` einhängst (All-in-one-Compose), braucht der Container Regeln mit diesen Nummern. Für die `.env`:")),
    el("div", { class: "snippets" }, snippet(env, ".env"), snippet(rules, "oder direkt in der Compose-Datei")));
  }
  return card("Rechte & Geräte im Container", { help: "hw_caps" }, body);
}

function rtcCard(report, ctx) {
  const rtc = report.rtc || {};
  const unknown = missing(report.rtc);
  const nocert = ctx.status?.config?.nts_nocerttimecheck;
  let note;
  if (unknown) {
    note = NO_DATA;
  } else if (!rtc.present) {
    note = "Keine Echtzeituhr: Nach einem Stromausfall startet das Gerät mit einer Zeit in der Vergangenheit. Für NTP egal, aber **NTS** scheitert dann an der Zertifikatsprüfung – „Zertifikatszeit beim Start nicht prüfen“ (`NTS_NOCERTTIMECHECK=true`) muss deshalb an bleiben.";
  } else if (isNum(rtc.drift_seconds) && Math.abs(rtc.drift_seconds) > 120) {
    note = "Die RTC weicht stark ab – wahrscheinlich fehlt die Batterie (Pi 5: Akku an **J5**). Bis dahin „Zertifikatszeit beim Start nicht prüfen“ für NTS eingeschaltet lassen.";
  } else {
    note = "Die Echtzeituhr hält die Zeit auch ohne Strom. NTS kann damit schon beim Start Zertifikate prüfen.";
  }
  return card("Echtzeituhr (RTC)", { help: "hw_rtc" },
    kv([
      ["Vorhanden", unknown ? "unbekannt" : rtc.present ? `ja${rtc.name ? ` (${rtc.name})` : ""}` : "nein", "hw_rtc"],
      rtc.present ? ["Abweichung zur Systemuhr", isNum(rtc.drift_seconds) ? `${fmtNumber(rtc.drift_seconds, 1)} s` : "–", "hw_rtc_drift"] : null,
      rtc.present ? ["Beim Start übernommen", yesNo(rtc.hctosys), "hw_hctosys"] : null,
      nocert !== undefined ? ["Zertifikatszeit beim Start prüfen", nocert ? "nein (sicher ohne RTC)" : "ja", "nocerttimecheck"] : null,
    ]),
    el("p", { class: "hw-note" }, rich(note)));
}

const TEMP_KIND = { thermal: "Thermalzone", hwmon: "Sensorchip (hwmon)", w1: "1-Wire (DS18B20)" };

function temperatureCard(report) {
  const temp = report.temperature;
  if (missing(temp)) return card("Temperatursensoren", { help: "temp_candidates" }, emptyNote(NO_DATA));
  const rows = temp.candidates || [];
  const chosen = temp.sensor?.id;
  const note = !rows.length
    ? "Keine Temperatursensoren sichtbar – typisch für VMs und Docker Desktop. Die Seite **Uhrqualität** zeigt dann „nicht verfügbar“."
    : temp.available
      ? `Aufgezeichnet wird **${temp.sensor.label || temp.sensor.id}** (Einstellung „${temp.setting}“). Die Kennung eines anderen Sensors kannst du in den Einstellungen unter „Temperatursensor“ eintragen.`
      : "Der eingestellte Sensor liefert keinen Wert – in den Einstellungen „auto“ wählen oder eine Kennung aus der Tabelle eintragen.";
  const head = (text, help) => el("th", {}, text, " ", info(help, text));
  return card("Temperatursensoren", { help: "temp_candidates" },
    rows.length ? el("div", { class: "table-scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, head("Kennung", "temp_candidates"), el("th", { text: "Art" }),
        el("th", { text: "Name" }), head("Wert", "temp_now"), head("Aufgezeichnet", "temp_sensor"))),
      el("tbody", {}, rows.map((s) => el("tr", {},
        el("td", { class: "mono", text: s.id }),
        el("td", { text: TEMP_KIND[s.kind] || s.kind || "–" }),
        el("td", { text: s.label || s.name || "–" }),
        el("td", { text: isNum(s.celsius) ? `${fmtNumber(s.celsius, 1)} °C` : "kein Wert" }),
        el("td", {}, s.id === chosen ? badge("ja", "good") : "")))))) : null,
    el("p", { class: "hw-note" }, rich(note)));
}

function headCard(report, ctx) {
  const plat = report.platform || {};
  const board = plat.board || {};
  const dmi = plat.dmi || {};
  const model = board.model || [dmi.sys_vendor, dmi.product_name].filter(Boolean).join(" ") || "–";
  const button = el("button", { type: "button", class: "button", text: busy ? "Prüfe …" : "Neu prüfen", disabled: busy ? true : null,
    onclick: () => recheck(ctx) });
  return card("Dieses System", { help: "hw_check", actions: el("span", { class: "button-row" },
    el("span", { class: "muted hw-stamp", text: isNum(report.generated) ? `Stand ${fmtTime(report.generated)}` : "" }),
    button, info("hw_refresh", "Neu prüfen")) },
    el("p", { class: "hw-summary", text: plat.summary || (model !== "–" ? model : missing(report.platform) ? "Keine Daten zur Plattform" : "Plattform nicht erkannt") }),
    kv([
      ["Board / Modell", model, "hw_board"],
      ["Architektur", plat.arch || "–", "hw_arch"],
      ["Virtualisierung", plat.hypervisor || (plat.docker_desktop ? "Docker Desktop (VM)" : plat.wsl ? "WSL2 (VM)" : missing(report.platform) ? "unbekannt" : "keine erkannt"), "hw_hypervisor"],
    ]),
    (report.warnings || []).length ? el("div", { class: "hw-warnings" },
      el("h3", { class: "mini-head" }, "Auffälligkeiten ", info("hw_warnings", "Auffälligkeiten")),
      el("ul", { class: "insights" }, report.warnings.map((w) => el("li", { class: "insight", "data-level": "warn" },
        el("span", { class: "insight-icon", "aria-hidden": "true", text: "!" }),
        el("div", { class: "insight-body" }, el("p", { text: w })))))) : null);
}

async function recheck(ctx) {
  if (busy) return;
  busy = true;
  ctx.rerender();
  try {
    fresh = await apiGet("/api/hardware?refresh=1");
    ctx.invalidate("hardware");
    toast("Hardware neu geprüft");
  } catch (error) {
    toast(`Prüfung fehlgeschlagen: ${error.message}`, "crit");
  }
  busy = false;
  ctx.rerender();
}

export function render(ctx) {
  const report = hardwareData(ctx);
  if (!report) {
    return [card("Hardware-Check", { help: "hw_check" },
      emptyNote("Hardware wird geprüft … (beim ersten Mal gut eine Sekunde, um PPS-Impulse zu zählen)"))];
  }
  const matrix = report.matrix || [];
  const fixes = matrix.filter((m) => m.status === "change" && m.fix);
  return [
    headCard(report, ctx),
    card("Was diese Hardware kann", { help: "hw_matrix",
      sub: "Für jede Funktion von ntp-gui: geht, geht mit Änderung, eingeschränkt oder geht nicht – jeweils mit Begründung." },
    matrixList(matrix),
    fixes.length > 1 ? el("details", { class: "more" }, el("summary", { text: `Alle ${fixes.length} Änderungen auf einen Blick` }),
      snippet(fixes.map((m) => `# ${m.title}\n${m.fix}`).join("\n\n"), "Alle Änderungen")) : null),
    gpsCard(report),
    el("div", { class: "grid-2" }, ppsCard(report), rtcCard(report, ctx)),
    temperatureCard(report),
    ptpCard(report),
    permissionsCard(report),
  ];
}
