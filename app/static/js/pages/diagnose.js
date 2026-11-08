// Seite „Diagnose“: Log, Ereignisse, Diagnosepaket mit Vorschau, Aufzeichnung.
// Alles bleibt lokal: Das Paket wird nur heruntergeladen, nie hochgeladen.
import { el, apiPost, isNum, fmtNumber, fmtZoned, serverZone } from "../util.js";
import { card, info, badge, kv, emptyNote, toast } from "../ui.js";

// Nicht bei jedem Status-Refresh neu aufbauen – Filter, Vorschau und Scrollposition bleiben stehen.
export const live = false;

const LOG_REFRESH_MS = 5000;
const RECORDING_REFRESH_MS = 5000;
const LOG_LINES = 500;

const EVENT_KINDS = {
  service: "Dienst", reload: "Neuladen", settings: "Einstellungen", source: "Quelle", gps: "GPS",
  pps: "PPS", calibration: "Kalibrierung", cert: "Zertifikat", leap: "Schaltsekunde", startup: "Start",
  clients: "Clients", api: "API", notify: "Benachrichtigung", dns: "DNS", update: "Update-Hinweis", other: "Sonstiges",
};
// Filter „Stufe“: die API liefert ab der gewählten Stufe aufwärts (warn → warn + crit).
const LEVEL_FILTERS = [["", "alle Stufen"], ["warn", "ab Warnung"], ["crit", "nur Kritisch"]];
const LEVEL_LABEL = { info: "Info", warn: "Warnung", crit: "Kritisch" };
const EVENT_RANGES = [[86400, "24 h"], [7 * 86400, "7 Tage"], [30 * 86400, "30 Tage"]];

// Laufende Intervalle dieser Seite – beim nächsten Aufbau bzw. Verlassen beendet.
let timers = [];

function clearTimers() {
  for (const id of timers) clearInterval(id);
  timers = [];
}

function every(ms, node, fn) {
  const id = setInterval(() => {
    if (!node.isConnected) { clearInterval(id); timers = timers.filter((t) => t !== id); return; }
    if (!document.hidden) fn();
  }, ms);
  timers.push(id);
}

function uiState(ctx) {
  if (!ctx.uiState.diag) {
    ctx.uiState.diag = { q: "", problems: false, auto: true, eventRange: 86400, eventKind: "", eventLevel: "", clients: false,
      recording: false, minutes: 5 };
  }
  return ctx.uiState.diag;
}

// --- Helfer ------------------------------------------------------------------
async function getJson(path) {
  const response = await fetch(path, { cache: "no-store", headers: { Accept: "application/json" } });
  let data = null;
  try { data = await response.json(); } catch (error) { /* keine JSON-Antwort */ }
  if (!response.ok) {
    const failure = new Error((data && data.error) || `HTTP ${response.status}`);
    failure.status = response.status;
    failure.data = data;
    throw failure;
  }
  return data;
}

function fmtBytes(bytes) {
  if (!isNum(bytes)) return "–";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtNumber(bytes / 1024, 1)} KB`;
  return `${fmtNumber(bytes / 1024 / 1024, 1)} MB`;
}

// Zeitpunkt in der Zeitzone des Servers – wie Kopfzeile und Ereigniskarte der Übersicht (sys: system aus /api/status).
export function fmtDateTime(unix, sys = null) {
  if (!isNum(unix)) return "–";
  return fmtZoned(unix, serverZone(sys) ? sys : null, { day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function switchControl(label, checked, onChange, help, disabled = false) {
  const input = el("input", { type: "checkbox", checked, disabled, role: "switch",
    onchange: () => onChange(input.checked) });
  return el("span", { class: "diag-switch" },
    el("label", { class: "switch" }, input, el("span", { class: "switch-track", "aria-hidden": "true" }),
      el("span", { class: "switch-text", text: label })),
    info(help, label));
}

// --- Log -------------------------------------------------------------------------
function logCard(state) {
  const list = el("div", { class: "diag-log", role: "log", tabindex: "0", "aria-label": "Log" });
  const meta = el("span", { class: "toolbar-label", text: "lädt …" });
  let first = true;
  let loading = false;

  const load = async () => {
    if (loading) return;
    loading = true;
    const params = new URLSearchParams({ lines: String(LOG_LINES) });
    if (state.q) params.set("q", state.q);
    if (state.problems) params.set("level", "warn");
    try {
      const data = (await getJson(`/api/logs?${params}`)) || {};
      const lines = Array.isArray(data.lines) ? data.lines : [];
      const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
      if (!lines.length) {
        list.replaceChildren(emptyNote(data.available === false
          ? "Noch kein Log vorhanden. Es entsteht, sobald der Container mit dem Supervisor läuft (`ntp-gui.log`)."
          : "Keine passenden Zeilen."));
      } else {
        list.replaceChildren(...lines.map((line) => el("div", { class: "diag-log-line", dataset: { level: line.level || "info" } },
          el("span", { class: "diag-log-n", "aria-hidden": "true", text: String(line.n ?? "") }),
          el("span", { class: "diag-log-text", text: line.text }))));
      }
      const shown = lines.length;
      meta.textContent = data.truncated || (isNum(data.total) && data.total > shown)
        ? `${shown} von ${fmtNumber(data.total)} Zeilen` : `${shown} Zeilen`;
      if (first || atBottom) list.scrollTop = list.scrollHeight;
      first = false;
    } catch (error) {
      list.replaceChildren(emptyNote(error.status === 404
        ? "Die Log-Schnittstelle ist in diesem Build noch nicht verfügbar."
        : `Log nicht abrufbar: ${error.message}`));
      meta.textContent = "";
    } finally {
      loading = false;
    }
  };

  let debounce = null;
  const search = el("input", { type: "search", placeholder: "Filtern …", value: state.q, "aria-label": "Log filtern",
    oninput: () => {
      state.q = search.value;
      clearTimeout(debounce);
      debounce = setTimeout(() => { first = true; load(); }, 300);
    } });
  const toolbar = el("div", { class: "toolbar diag-toolbar" },
    el("span", { class: "diag-field" }, search, info("diag_log_filter", "Log filtern")),
    switchControl("nur Warnungen/Fehler", state.problems, (on) => { state.problems = on; first = true; load(); },
      "diag_log_problems"),
    switchControl("automatisch aktualisieren", state.auto, (on) => { state.auto = on; if (on) load(); }, "diag_log_auto"),
    el("button", { type: "button", class: "button", text: "Aktualisieren", onclick: () => load() }),
    meta);

  load();
  every(LOG_REFRESH_MS, list, () => { if (state.auto) load(); });

  return card("Log", { help: "diag_log",
    sub: "Ausgaben aller Dienste, neueste unten. Farbig: gelb = Warnung, rot = Fehler." },
  toolbar,
  el("div", { class: "diag-legend" },
    el("span", { class: "diag-legend-item", dataset: { level: "warn" }, text: "Warnung" }),
    el("span", { class: "diag-legend-item", dataset: { level: "crit" }, text: "Fehler" }),
    info("diag_log_level", "Einstufung der Zeilen")),
  list);
}

// --- Ereignisse ------------------------------------------------------------------
export function eventRow(event, sys = null) {
  const data = event.data && typeof event.data === "object" ? Object.entries(event.data) : [];
  return el("li", { class: "diag-event", dataset: { level: event.level || "info" } },
    el("span", { class: "diag-event-time mono", text: fmtDateTime(event.t, sys) }),
    badge(LEVEL_LABEL[event.level] || event.level || "Info", event.level === "crit" ? "crit"
      : event.level === "warn" ? "warn" : "info"),
    el("span", { class: "diag-event-kind", text: EVENT_KINDS[event.kind] || event.kind || "–" }),
    el("span", { class: "diag-event-title", text: event.display_title || event.title || "" }),
    data.length ? el("span", { class: "diag-event-data mono",
      text: data.map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ") }) : null);
}

function eventsCard(state, system = () => null) {
  const body = el("div", { class: "diag-events" }, emptyNote("lädt …"));
  const load = async () => {
    const since = Math.floor(Date.now() / 1000) - state.eventRange;
    const params = new URLSearchParams({ since: String(since), limit: "300" });
    if (state.eventKind) params.set("kinds", state.eventKind);
    if (state.eventLevel) params.set("level", state.eventLevel);
    const filtered = Boolean(state.eventKind || state.eventLevel);
    try {
      const data = await getJson(`/api/events?${params}`);
      const list = Array.isArray(data) ? data : (data && Array.isArray(data.events) ? data.events : []);
      const events = list.filter((e) => e && typeof e === "object").sort((a, b) => (b.t || 0) - (a.t || 0));
      body.replaceChildren(events.length
        ? el("ul", { class: "diag-event-list" }, events.map((e) => eventRow(e, system())))
        : emptyNote(filtered ? "Keine Ereignisse, die zum Filter passen."
          : "In diesem Zeitraum ist nichts Besonderes passiert."));
    } catch (error) {
      body.replaceChildren(emptyNote(error.status === 404
        ? "Das Ereignisprotokoll ist in diesem Build noch nicht verfügbar."
        : `Ereignisse nicht abrufbar: ${error.message}`));
    }
  };
  const buttons = EVENT_RANGES.map(([seconds, label]) => el("button", {
    type: "button", class: `range${state.eventRange === seconds ? " is-active" : ""}`, text: label,
    "aria-pressed": state.eventRange === seconds ? "true" : "false",
    onclick: (event) => {
      state.eventRange = seconds;
      for (const b of buttons) {
        const active = b === event.currentTarget;
        b.classList.toggle("is-active", active);
        b.setAttribute("aria-pressed", active ? "true" : "false");
      }
      load();
    },
  }));
  const select = (options, value, label, onPick) => {
    const node = el("select", { "aria-label": label }, options.map(([v, text]) =>
      el("option", { value: v, selected: v === value ? true : null, text })));
    node.addEventListener("change", () => { onPick(node.value); load(); });
    return node;
  };
  const kindSelect = select([["", "alle Arten"], ...Object.entries(EVENT_KINDS)], state.eventKind,
    "Art des Ereignisses", (v) => { state.eventKind = v; });
  const levelSelect = select(LEVEL_FILTERS, state.eventLevel, "Stufe", (v) => { state.eventLevel = v; });
  load();
  every(30000, body, load);
  return card("Ereignisse", { help: "diag_events",
    actions: el("div", { class: "range-group", role: "group", "aria-label": "Zeitraum" }, buttons),
    sub: "Neustarts, Quellenwechsel, GPS-Fix, Zertifikate – neueste oben." },
  el("div", { class: "toolbar diag-toolbar diag-event-filters" },
    el("label", { class: "diag-field" }, el("span", { class: "toolbar-label", text: "Art" }), kindSelect),
    info("diag_event_kind", "Art des Ereignisses"),
    el("label", { class: "diag-field" }, el("span", { class: "toolbar-label", text: "Stufe" }), levelSelect),
    info("diag_event_level", "Stufe")),
  body);
}

// --- Diagnosepaket --------------------------------------------------------------------
function sectionText(name, value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && !Array.isArray(value)
      && ["config", "chrony", "logs", "recording"].includes(name)) {
    return Object.entries(value).map(([k, v]) => `===== ${k} =====\n${typeof v === "string" ? v
      : JSON.stringify(v, null, 2)}\n`).join("\n");
  }
  return JSON.stringify(value, null, 2);
}

function sectionDetails(section, value) {
  const pre = el("pre", { class: "code diag-pre" });
  const details = el("details", { class: "diag-section" },
    el("summary", {},
      el("span", { class: "diag-section-title", text: section.title || section.name }),
      el("span", { class: "diag-section-file mono", text: section.file || "" }),
      el("span", { class: "diag-section-size", text: fmtBytes(section.size) }),
      section.truncated ? badge("gekürzt", "warn") : null),
    pre);
  // Erst beim Aufklappen füllen: ein großes Log soll die Seite nicht bremsen.
  details.addEventListener("toggle", () => {
    if (details.open && !pre.textContent) pre.textContent = sectionText(section.name, value);
  });
  return details;
}

function previewView(data) {
  if (!data || data.ok === false) {
    const leaks = (data && data.leaks) || [];
    return el("div", { class: "diag-preview", "data-state": "error" },
      el("p", { class: "diag-error", text: (data && data.error) || "Vorschau fehlgeschlagen." }),
      leaks.length ? el("ul", { class: "diag-removed" }, leaks.slice(0, 20).map((f) =>
        el("li", { text: `${f.kind}: ${f.path}` }))) : null);
  }
  const sections = data.sections || [];
  const removed = (data.removed && data.removed.removed) || {};
  const labels = (data.removed && data.removed.labels) || {};
  const total = sections.reduce((sum, s) => sum + (s.size || 0), 0);
  const entries = Object.entries(removed).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  return el("div", { class: "diag-preview" },
    kv([
      ["Abschnitte", `${sections.length} Dateien + MANIFEST.txt`, "diag_sections"],
      ["Größe (ungepackt)", fmtBytes(total), "diag_sections"],
      ["Pseudonyme", fmtNumber((data.removed || {}).pseudonyms || 0), "diag_pseudonyms"],
    ]),
    el("h3", { class: "diag-subhead" }, el("span", { text: "Entfernt oder ersetzt" }), info("diag_removed")),
    entries.length
      ? el("ul", { class: "diag-removed" }, entries.map(([key, count]) => el("li", {},
        el("strong", { text: `${fmtNumber(count)} ×` }), " ", el("span", { text: labels[key] || key }))))
      : emptyNote("Der Filter musste nichts entfernen."),
    el("h3", { class: "diag-subhead" }, el("span", { text: "So sieht das Paket aus" }), info("diag_preview")),
    el("div", { class: "diag-sections" }, sections.map((s) => sectionDetails(s, (data.content || {})[s.name]))));
}

function filenameFrom(response) {
  const header = response.headers.get("Content-Disposition") || "";
  const match = header.match(/filename="?([^";]+)"?/);
  return match ? match[1] : "ntp-gui-diagnose.tar.gz";
}

function bundleCard(state) {
  const output = el("div", { class: "diag-output" });
  const query = () => new URLSearchParams({ clients: state.clients ? "1" : "0",
    recording: state.recording ? "1" : "0" }).toString();
  const previewButton = el("button", { type: "button", class: "button", text: "Vorschau" });
  const downloadButton = el("button", { type: "button", class: "button primary", text: "Herunterladen" });

  // Die angezeigte Vorschau: ihr Merker (reuse) und die Schalter, mit denen sie entstand. Nur dann
  // liefert der Download genau dieses Paket; sonst baut der Server neu.
  let shown = null;

  const busyNote = (seconds) => emptyNote("Paket wird zusammengestellt und gefiltert … "
    + (isNum(seconds) && seconds > 0 ? `(seit ${seconds} s) ` : "")
    + (state.recording ? "Mit Aufzeichnung kann das auf einem Raspberry Pi eine bis mehrere Minuten dauern. " : "")
    + "Das Dashboard bleibt währenddessen bedienbar.");

  // Der Server baut im Hintergrund und antwortet spätestens nach etwa 10 s – fertig oder „läuft noch“
  // (202). Keine Anfrage bleibt lange offen, sonst bricht ein Reverse Proxy sie ab (oft nach 60 s).
  async function buildPreview(asked) {
    let data = await getJson(`/api/diagnostics/preview?${asked}&async=1`);
    while (data && data.pending && data.job) {
      output.replaceChildren(busyNote(data.seconds));
      await new Promise((resolve) => setTimeout(resolve, 2000));
      data = await getJson(`/api/diagnostics/preview?${new URLSearchParams({ job: String(data.job) })}`);
    }
    return data;
  }

  // Vorschau holen und anzeigen; true, wenn sie heruntergeladen werden kann.
  async function showPreview() {
    shown = null;
    output.replaceChildren(busyNote());
    const asked = query();
    try {
      const data = await buildPreview(asked);
      output.replaceChildren(previewView(data));
      if (data && data.ok !== false && data.reuse) shown = { query: asked, reuse: String(data.reuse) };
    } catch (error) {
      output.replaceChildren(previewView(error.data || { ok: false, error: error.message }));
    }
    return shown !== null;
  }

  previewButton.addEventListener("click", async () => {
    previewButton.disabled = true;
    downloadButton.disabled = true;
    try {
      await showPreview();
    } finally {
      previewButton.disabled = false;
      downloadButton.disabled = false;
    }
  });

  // Schalter geändert: Die angezeigte Vorschau zeigt nicht mehr, was heruntergeladen würde.
  const staleView = () => {
    if (shown === null && !output.firstChild) return;
    shown = null;
    if (!previewButton.disabled) output.replaceChildren();
  };

  downloadButton.addEventListener("click", async () => {
    downloadButton.disabled = true;
    previewButton.disabled = true;
    // Heruntergeladen wird immer das Paket einer Vorschau (dieselben Daten, sofort). Gibt es zu den
    // Schaltern noch keine, wird sie zuerst gebaut und angezeigt – so bleibt auch hier keine Anfrage
    // minutenlang offen.
    const asked = query();
    const hadPreview = shown !== null && shown.query === asked
      && output.querySelector(".diag-preview:not([data-state=error])") !== null;
    if (!hadPreview && !(await showPreview())) {
      downloadButton.disabled = false;
      previewButton.disabled = false;
      toast("Diagnosepaket nicht erstellt", "crit");
      return;
    }
    const reuse = `&${new URLSearchParams({ reuse: shown.reuse })}`;
    try {
      let response = await fetch(`/api/diagnostics/bundle?${shown.query}${reuse}`, { cache: "no-store" });
      // 409: Die Vorschau gilt nicht mehr (zu alt, Einstellungen geändert, anderswo ersetzt). Statt eines
      // langen Baus in dieser Anfrage eine neue Vorschau im Hintergrund – und die dann herunterladen.
      if (response.status === 409 && await showPreview()) {
        response = await fetch(`/api/diagnostics/bundle?${shown.query}&${new URLSearchParams({ reuse: shown.reuse })}`,
          { cache: "no-store" });
      }
      if (!response.ok) {
        let data = null;
        try { data = await response.json(); } catch (error) { /* kein JSON */ }
        shown = null;
        output.replaceChildren(previewView(data || { ok: false, error: `HTTP ${response.status}` }));
        toast("Diagnosepaket nicht erstellt", "crit");
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = el("a", { href: url, download: filenameFrom(response), hidden: true });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      toast("Diagnosepaket gespeichert – nichts wurde hochgeladen");
    } catch (error) {
      toast(`Herunterladen fehlgeschlagen: ${error.message}`, "crit");
    } finally {
      downloadButton.disabled = false;
      previewButton.disabled = false;
    }
  });

  return card("Diagnosepaket", { help: "diag_bundle",
    sub: "Für ein GitHub-Issue oder für jemanden, der dir hilft. Vor dem Herunterladen kannst du dir "
      + "**genau** ansehen, was drinsteht." },
  el("p", { class: "diag-privacy" },
    el("span", { text: "Datenschutzfilter: keine Koordinaten, Satellitenwinkel, Seriennummern, MAC- oder öffentlichen "
      + "IP-Adressen, eigenen Domains oder Zeitzonennamen." }), info("diag_privacy", "Datenschutzfilter")),
  el("div", { class: "diag-options" },
    switchControl("Client-Liste einschließen (pseudonymisiert)", state.clients,
      (on) => { state.clients = on; staleView(); }, "diag_include_clients"),
    switchControl("Aufzeichnung einschließen", state.recording,
      (on) => { state.recording = on; staleView(); }, "diag_include_recording")),
  el("div", { class: "button-row" },
    previewButton, info("diag_preview", "Vorschau"),
    downloadButton, info("diag_download", "Herunterladen")),
  output);
}

// --- Aufzeichnung -------------------------------------------------------------------------
function recordingCard(state, readonly, system = () => null) {
  const status = el("div", { class: "diag-recording-status" }, emptyNote("lädt …"));
  const minutes = el("input", { type: "number", min: "1", max: "60", step: "1", value: String(state.minutes),
    "aria-label": "Dauer in Minuten", class: "diag-minutes", disabled: readonly,
    onchange: () => { state.minutes = Math.min(60, Math.max(1, Math.round(Number(minutes.value) || 5))); minutes.value = String(state.minutes); } });
  const start = el("button", { type: "button", class: "button primary", text: "Aufzeichnung starten", disabled: readonly });
  const stop = el("button", { type: "button", class: "button", text: "Stoppen", hidden: true, disabled: readonly });

  const show = (raw) => {
    const data = raw && typeof raw === "object" ? raw : {};
    const active = Boolean(data.active);
    start.hidden = active;
    stop.hidden = !active;
    const state_ = active
      ? `läuft${isNum(data.ends) ? ` bis ${fmtDateTime(data.ends, system())}` : ""}`
      : data.available ? `fertig${isNum(data.started) ? ` (gestartet ${fmtDateTime(data.started, system())})` : ""}` : "keine Aufzeichnung";
    status.replaceChildren(kv([
      ["Zustand", active ? badge(state_, "info") : state_, "diag_recording_status"],
      ["Einträge", isNum(data.entries) ? fmtNumber(data.entries) : "–", "diag_recording_entries"],
      ["Größe", fmtBytes(data.size), "diag_recording_size"],
    ]));
  };
  const load = async () => {
    try {
      show(await getJson("/api/recording"));
    } catch (error) {
      start.disabled = true;
      status.replaceChildren(emptyNote(error.status === 404
        ? "Aufzeichnen ist in diesem Build noch nicht verfügbar."
        : `Zustand nicht abrufbar: ${error.message}`));
    }
  };
  start.addEventListener("click", async () => {
    start.disabled = true;
    try {
      show(await apiPost("/api/recording", { seconds: state.minutes * 60 }));
      toast(`Aufzeichnung läuft ${state.minutes} min`);
    } catch (error) {
      toast(`Aufzeichnung nicht gestartet: ${error.message}`, "crit");
    } finally {
      start.disabled = readonly;
    }
  });
  stop.addEventListener("click", async () => {
    stop.disabled = true;
    try {
      show(await apiPost("/api/recording", { stop: true }));
      toast("Aufzeichnung beendet");
    } catch (error) {
      toast(`Stoppen fehlgeschlagen: ${error.message}`, "crit");
    } finally {
      stop.disabled = readonly;
    }
  });
  load();
  every(RECORDING_REFRESH_MS, status, load);

  return card("Aufzeichnung", { help: "diag_recording",
    sub: "Schneidet mit, was ntp-gui von chronyc, gpsd, pmc und ethtool liest – damit Entwickler dein Problem "
      + "auf ihrem Rechner **genau so** abspielen können. Die Datei bleibt auf dem Gerät; ins Diagnosepaket kommt "
      + "sie nur, wenn du „Aufzeichnung einschließen“ wählst – gefiltert wie alles andere." },
  el("div", { class: "button-row" },
    el("label", { class: "diag-field" }, el("span", { class: "toolbar-label", text: "Dauer (Minuten)" }), minutes),
    info("diag_recording_duration", "Dauer"),
    start, stop),
  readonly ? emptyNote("Das Dashboard ist schreibgeschützt (`WEB_READONLY`) – Aufzeichnen ist gesperrt.") : null,
  status);
}

// --- Seite ---------------------------------------------------------------------------------
export function render(ctx) {
  clearTimers();
  const state = uiState(ctx);
  const system = () => ctx.status?.system || null;
  return [
    card("Diagnose", { help: "diag_page", class: "explain",
      sub: "Log, Ereignisse und ein Diagnosepaket für die Fehlersuche." },
    el("p", { class: "diag-privacy" },
      el("span", { text: "Nichts davon wird automatisch hochgeladen. Was das Gerät verlässt, lädst du selbst herunter – "
        + "vorher siehst du in der Vorschau genau, was drinsteht." }),
      info("diag_no_upload", "Nichts wird hochgeladen"))),
    logCard(state),
    eventsCard(state, system),
    bundleCard(state),
    recordingCard(state, ctx.readonly, system),
  ];
}
