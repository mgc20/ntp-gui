import { el, rich, apiPost, apiGet } from "../util.js";
import { card, info, badge, kv, emptyNote, toast, copyButton, isPopoverOpen } from "../ui.js";
import { t, has, language, setLanguage, LANGUAGES } from "../i18n.js";

export const live = false; // nicht bei jedem Refresh neu aufbauen – Eingaben bleiben stehen

const SOURCE_LABEL = { default: "Standard", env: "Umgebung", gui: "Dashboard" };
const PRESETS = [
  ["PTB (NTS)", [["server", "ptbtime1.ptb.de", true], ["server", "ptbtime2.ptb.de", true], ["server", "ptbtime3.ptb.de", true]]],
  ["Cloudflare (NTS)", [["server", "time.cloudflare.com", true]]],
  ["Netnod (NTS)", [["server", "nts.netnod.se", true]]],
  ["de.pool.ntp.org", [["pool", "de.pool.ntp.org", false]]],
  ["pool.ntp.org", [["pool", "pool.ntp.org", false]]],
];

// ⓘ neben einzelnen Feldern: verweist auf die ausführliche Erklärung in der Hilfe.
// Der kurze Hilfetext unter jedem Feld kommt vom Server (Schema).
export const FIELD_HELP = {
  ntp_sources: "source_type", ntp_minsources: "minsources", leapsectz: "leap_source", leapseclist: "leap_source",
  serve_unsynced: "island", local_stratum: "island", local_orphan: "local_orphan",
  ntp_hw_timestamp: "timestamping",
  nts_nocerttimecheck: "nocerttimecheck", nts_server_enable: "nts_server",
  nts_server_cert: "nts_server_files", nts_server_key: "nts_server_files",
  nts_server_name: "nts_server_name", nts_server_port: "nts_server_name",
  gps_enable: "gps", gps_offset: "gps_recalibrate", gps_delay: "gps_delay", gps_select: "gps_role",
  gps_pps_device: "pps",
  ptp_enable: "ptp_vs_ntp", ptp_interface: "ptp_requirements", ptp_mode: "grandmaster", ptp_domain: "ptp_domain",
  ptp_transport: "ptp_transport", ptp_profile: "ptp_profile", ptp_time_stamping: "timestamping",
  ptp_clock_class: "clock_class", phc2sys_enable: "phc2sys", phc_refclock: "phc",
  gps_autocal: "autocal_mode", gps_autocal_max_step_ms: "autocal_step", gps_autocal_min_hours: "autocal_window",
  clientmon_enable: "clientmon", clients_alarm_ms: "clients_alarm", clients_rdns: "client_rdns",
  clients_new_device_alarm: "clients_new_device", notify_lan_addresses: "notify_lan_addresses",
  web_title: "web_title", web_refresh_seconds: "web_refresh", history_interval: "history_interval",
  notify_dashboard_url: "notify_link",
  temp_sensor: "temp_sensor", clock_public: "clock_public", update_check: "update_check",
  trusted_proxies: "trusted_proxies",
  dns_mode: "dns_modes", dns_servers: "dns_upstreams", dns_dot: "dns_modes", dns_doh: "dns_modes",
  dns_pin: "dns_pin", dns_fallback: "dns_fallback",
  gps_device: "hw_device_path", allow_networks: "allow_networks", gps_show_position: "gps_show_position",
};

// Sprache des Dashboards: keine Server-Einstellung, sondern je Browser (i18n.js, localStorage).
function languageRow() {
  const select = el("select", { id: "f-ui-language" }, LANGUAGES.map((l) =>
    el("option", { value: l.code, selected: l.code === language() ? true : null, text: l.label })));
  select.addEventListener("change", () => { setLanguage(select.value); });
  return el("div", { class: "fields" }, el("div", { class: "field", id: "row-ui-language" },
    el("div", { class: "field-head" },
      el("span", { class: "field-label" }, el("label", { for: "f-ui-language", text: t("settings.language.label") }), " ",
        info("ui_language", t("settings.language.label"))),
      el("span", { class: "field-meta" }, badge("Browser", "muted"))),
    select,
    el("p", { class: "field-help", text: t("settings.language.note") })));
}

function fmtDate(unix) {
  return typeof unix === "number" && Number.isFinite(unix)
    ? new Date(unix * 1000).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "nie";
}

// Update-Hinweise: was die Migration der Einstellungen geändert hat und warum.
function notesCard(ctx, notes, readonly) {
  if (!notes || !notes.length) return null;
  const ack = async () => {
    try {
      await apiPost("/api/settings/notes/ack", {});
      ctx.invalidate("settings");
      ctx.rerender();
    } catch (error) { toast(error.message, "crit"); }
  };
  return card("Was sich beim Update geändert hat", { help: "settings_notes", class: "card-alert",
    actions: readonly ? null : el("button", { type: "button", class: "button", text: "Gelesen", onclick: ack }) },
  el("ul", { class: "update-notes" }, notes.map((note) => el("li", {},
    el("strong", { text: note.title }), el("p", {}, rich(note.text))))));
}

// Liste der Schlüssel. „Zuletzt benutzt“ ändert sich, während die Seite offen ist –
// deshalb tauscht ein Zeitgeber nur diese Liste aus (die Seite selbst baut sich
// nicht neu auf, damit Eingaben stehen bleiben).
const KEYS_REFRESH_SECONDS = 30;
let keysTimer = null;

function keyListNodes(ctx, keys, disabled) {
  if (keys === undefined) return [emptyNote("Schlüssel werden geladen …")];
  if (!keys || !keys.keys || !keys.keys.length) return [emptyNote("Noch keine Schlüssel angelegt.")];
  const revoke = async (key) => {
    if (!window.confirm(`Schlüssel „${key.name}“ widerrufen? Programme, die ihn nutzen, bekommen danach keinen Zugriff mehr.`)) return;
    try {
      await apiPost("/api/apikeys/revoke", { id: key.id });
      toast("Widerrufen");
      ctx.invalidate("apikeys");
      ctx.rerender();
    } catch (error) { toast(error.message, "crit"); }
  };
  return [el("ul", { class: "apikey-list" }, keys.keys.map((key) => el("li", { class: "apikey" },
    el("div", { class: "apikey-main" },
      el("strong", { text: key.name }), " ", badge(key.scope_label || key.scope, key.scope === "admin" ? "warn" : "info"),
      el("span", { class: "mono muted", text: ` ntpg_${key.id}…` })),
    kv([["Angelegt", fmtDate(key.created), "api_keys"], ["Zuletzt benutzt", fmtDate(key.last_used), "api_key_used"]]),
    el("button", { type: "button", class: "button", text: "Widerrufen", disabled, onclick: () => revoke(key) }))))];
}

function watchKeys(ctx, box, disabled) {
  clearInterval(keysTimer);
  keysTimer = setInterval(async () => {
    if (!box.isConnected) { clearInterval(keysTimer); keysTimer = null; return; }
    if (document.hidden || isPopoverOpen() || box.contains(document.activeElement)) return;
    try {
      const fresh = await apiGet("/api/apikeys");
      if (box.isConnected) box.replaceChildren(...keyListNodes(ctx, fresh, disabled));
    } catch (error) { /* nächster Versuch beim nächsten Takt */ }
  }, KEYS_REFRESH_SECONDS * 1000);
}

// API-Schlüssel anlegen, auflisten, widerrufen + Instanz-Kennung.
function apiCard(ctx, readonly, auth) {
  const ui = ctx.uiState;
  const keys = ctx.data("apikeys", "/api/apikeys", KEYS_REFRESH_SECONDS);
  const inst = ctx.data("instance", "/api/v1/instance", 0);
  const disabled = readonly ? true : null;
  const body = [];
  if (!auth.enabled) {
    body.push(emptyNote("Noch ist **kein Passwort** gesetzt – das Dashboard und die API sind im LAN offen. "
      + "Schlüssel wirken trotzdem schon mit ihrem Recht; wirklich nötig werden sie, sobald du oben ein Passwort setzt."));
  }
  if (ui.newKey) {
    const token = ui.newKey.token;
    body.push(el("div", { class: "apikey-new", role: "status" },
      el("div", { class: "apikey-new-head" }, el("strong", { text: `Neuer Schlüssel „${ui.newKey.name}“` }), info("api_key_token", "Neuer Schlüssel")),
      el("p", { class: "muted", text: "Jetzt kopieren – er wird nur dieses eine Mal angezeigt." }),
      el("div", { class: "apikey-token" },
        el("code", { class: "mono", text: token }),
        copyButton(token)),
      el("button", { type: "button", class: "button", text: "Ich habe ihn gespeichert",
        onclick: () => { ui.newKey = null; ctx.rerender(); } })));
  }
  const name = el("input", { type: "text", maxlength: 64, placeholder: "z. B. Home Assistant", "aria-label": "Name des Schlüssels", disabled });
  const scope = el("select", { "aria-label": "Recht", disabled },
    el("option", { value: "read", text: "nur lesen" }), el("option", { value: "admin", text: "lesen und verwalten" }));
  const create = async () => {
    try {
      const result = await apiPost("/api/apikeys", { name: name.value, scope: scope.value });
      ui.newKey = { token: result.token, name: result.name };
      ctx.invalidate("apikeys");
      ctx.rerender();
    } catch (error) { toast(error.message, "crit"); }
  };
  body.push(el("div", { class: "auth-form" },
    el("label", {}, el("span", { text: "Name" }), name),
    el("label", {}, el("span", {}, "Recht ", info("api_key_scope", "Recht")), scope),
    el("button", { type: "button", class: "button primary", text: "Schlüssel anlegen", disabled, onclick: create })));
  const keyBox = el("div", { class: "apikey-box" }, keyListNodes(ctx, keys, disabled));
  body.push(keyBox);
  ctx.afterRender(() => watchKeys(ctx, keyBox, disabled));
  body.push(el("p", { class: "field-help" }, rich("Beschreibung aller Endpunkte samt nötigem Recht: `GET /api/v1`. "
    + "Beispiel: `curl -H \"Authorization: Bearer ntpg_…\" http://<server>:8080/api/v1/status`"), " ", info("api_v1", "Versionierte API")));

  const rotate = async () => {
    if (!window.confirm("Neue Instanz-Kennung erzeugen? Die alte wird verworfen.")) return;
    try {
      await apiPost("/api/instance/rotate", {});
      toast("Neue Kennung erzeugt");
      ctx.invalidate("instance");
      ctx.rerender();
    } catch (error) { toast(error.message, "crit"); }
  };
  const instanceRow = el("div", { class: "instance-row" },
    kv([["Instanz-Kennung", inst ? el("code", { class: "mono", text: inst.instance_id }) : "–", "instance_id"],
      ["Seit", inst ? fmtDate(inst.since) : "–", "instance_id"]]),
    el("button", { type: "button", class: "button", text: "Neu erzeugen", disabled, onclick: rotate }));
  return card("API-Schlüssel und Instanz", { id: "s-api", help: "api_keys",
    sub: "Für Skripte und Programme: eigene Schlüssel statt des Passworts, einzeln widerrufbar." },
  body, el("h3", { class: "subhead", text: "Instanz" }), instanceRow);
}

// DNS für ntp-gui: Zustand des Weiterleiters (Stand beim Laden der Seite).
const DNS_STATE = {
  system: ["System-DNS – kein eigener Weiterleiter", "muted"],
  starting: ["läuft – wartet auf erste Anfrage", "info"],
  ok: ["läuft – eigene Server antworten", "good"],
  fallback: ["Rückfall auf System-DNS", "warn"],
  failing: ["keine Auflösung", "crit"],
  down: ["nicht gestartet", "crit"],
};
const RESOLV_STATE = {
  local: ["zeigt auf 127.0.0.1", "good"],
  system: ["System-DNS", "muted"],
  readonly: ["schreibgeschützt", "warn"],
  error: ["Fehler", "crit"],
};

function fmtAgo(unix) {
  if (typeof unix !== "number" || !Number.isFinite(unix)) return "nie";
  const age = Math.max(0, Date.now() / 1000 - unix);
  return age < 90 ? `vor ${Math.round(age)} s` : age < 5400 ? `vor ${Math.round(age / 60)} min` : fmtDate(unix);
}

// Update-Hinweis: nur Zustand anzeigen; ein-/ausschalten über das Feld „update_check“ darunter.
const RELEASE_LINK = /^https:\/\/github\.com\/ConGp20\/ntp-gui\/releases(\/tag\/v[0-9A-Za-z.-]+)?$/;

function updateStatus(upd) {
  if (!upd || !upd.enabled) return null;
  const latest = upd.latest || null;
  const link = latest && RELEASE_LINK.test(latest.url || "") ? latest.url : null;
  const latestValue = !latest ? "noch nicht geprüft"
    : el("span", {},
      `${latest.version}${latest.title ? ` – ${latest.title}` : ""} `,
      upd.available ? badge(upd.attention ? "neuer · Achtung beim Update" : "neuer", upd.attention ? "warn" : "info")
        : badge("aktuell", "good"),
      link ? el("a", { href: link, target: "_blank", rel: "noopener noreferrer", class: "update-link", text: " Release-Notizen →" }) : null);
  const rows = [
    ["Installiert", upd.current_valid ? upd.current : `${upd.current || "unbekannt"} (keine Versionsnummer)`, "update_current"],
    ["Neueste auf GitHub", latestValue, "update_latest"],
    ["Letzte Prüfung", upd.last_attempt ? `${fmtAgo(upd.last_attempt)}${upd.error ? "" : " · ok"}` : "noch keine", "update_last"],
    ["Nächste Prüfung", typeof upd.next_check === "number" ? fmtDate(upd.next_check) : "–", "update_next"],
  ];
  return el("div", { class: "update-status" },
    el("h3", { class: "mini-head" }, "Update-Hinweis ", info("update_check", "Update-Hinweis")),
    kv(rows),
    upd.error ? el("p", { class: "field-error", role: "alert", text: `Letzte Prüfung gescheitert: ${upd.error}` }) : null);
}

function dnsStatus(dns) {
  if (dns === undefined) return emptyNote("Zustand wird geladen …");
  if (!dns) return emptyNote("Zustand nicht verfügbar.");
  const [stateText, stateTone] = DNS_STATE[dns.state] || ["unklar", "warn"];
  const resolv = dns.resolv || {};
  const [resolvText, resolvTone] = RESOLV_STATE[resolv.state] || [dns.effective_mode === "system" ? "System-DNS" : "unbekannt", "muted"];
  const stats = dns.stats || {};
  const ups = Array.isArray(dns.upstreams) ? dns.upstreams : [];
  const rows = [
    ["Aktiver Modus", dns.effective_label || dns.effective_mode || "–", "dns_modes"],
    ["Zustand", badge(stateText, stateTone), "dns_state"],
    dns.effective_mode !== "system" ? ["resolv.conf", el("span", {}, badge(resolvText, resolvTone),
      resolv.message ? el("span", { class: "muted", text: ` ${resolv.message}` }) : null), "dns_resolv"] : null,
    dns.effective_mode !== "system" ? ["Rückfall auf System-DNS", !dns.fallback_enabled ? "aus"
      : (dns.fallback_servers || []).length ? `an (${dns.fallback_servers.join(", ")})` : "an – kein System-DNS bekannt", "dns_fallback"] : null,
    dns.running ? ["Anfragen", `${stats.queries ?? 0} · Cache ${stats.cache_hits ?? 0} · Rückfall ${stats.fallback ?? 0}`
      + ` · ohne Antwort ${stats.servfail ?? 0}`, "dns_counts"] : null,
    dns.effective_mode !== "system" && dns.running ? ["Letzte erfolgreiche Auflösung",
      typeof dns.last_success === "number" ? fmtAgo(dns.last_success) : "noch keine", "dns_last_ok"] : null,
    dns.effective_mode !== "system" && dns.running ? ["Erreichbar", `${dns.reachable ?? 0} von ${ups.length} Servern`
      + (typeof stats.health_last === "number" ? ` · zuletzt geprüft ${fmtAgo(stats.health_last)}` : ""), "dns_reachable"] : null,
  ];
  return el("div", { class: "dns-status" },
    kv(rows),
    dns.error ? el("p", { class: "field-error", role: "alert", text: dns.error }) : null,
    (dns.warnings || []).map((w) => el("p", { class: "field-error", text: w })),
    dns.nts_note ? el("p", { class: "card-sub" }, el("span", { text: dns.nts_note }), info("dns_nts", "NTS und DNS")) : null,
    ups.length ? el("div", {},
      el("h3", { class: "mini-head" }, "Eigene Server ", info("dns_upstreams", "Eigene Server")),
      el("ul", { class: "svc-list" }, ups.map((u) => {
        const down = typeof u.down_until === "number" && u.down_until * 1000 > Date.now();
        const tone = down ? "warn" : u.ok ? "good" : u.fail ? "warn" : "muted";
        return el("li", { class: "svc", "data-tone": tone },
          el("span", { class: "svc-dot", "aria-hidden": "true" }),
          el("span", { class: "svc-name mono", text: u.label }),
          badge(down ? "übersprungen" : u.ok ? "antwortet" : u.fail ? "Fehler" : "noch nicht gefragt", tone),
          el("span", { class: "svc-message", text: `${u.ok} ok · ${u.fail} Fehler · zuletzt ok ${fmtAgo(u.last_ok)}`
            + (typeof u.rtt_ms === "number" ? ` · ${u.rtt_ms} ms` : "")
            + (u.last_error ? ` · letzter Fehler (${fmtAgo(u.last_error_t)}): ${u.last_error}` : "") }));
      }))) : null);
}

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

export function render(ctx) {
  const schema = ctx.data("settings", "/api/settings", 0);
  const devices = ctx.data("devices", "/api/devices", 60);
  const dns = ctx.data("dns", "/api/dns", 0);
  const update = ctx.data("update", "/api/update", 60);
  if (!schema) return [card("Einstellungen", {}, emptyNote("Wird geladen …"))];
  const ui = ctx.uiState;
  ui.draft = ui.draft || {};
  ui.showAdvanced = ui.showAdvanced || {};
  ui.fieldErrors = ui.fieldErrors || {};
  const readonly = schema.readonly;
  const fields = Array.isArray(schema.fields) ? schema.fields : [];
  const byKey = Object.fromEntries(fields.map((f) => [f.key, f]));
  const current = (key) => (key in ui.draft ? ui.draft[key] : byKey[key]?.value);
  // Entwürfe für Felder, die der Server nicht (mehr) kennt, zählen nicht.
  const changedKeys = () => Object.keys(ui.draft).filter((k) => k in byKey && !same(ui.draft[k], byKey[k].value));

  const saveBar = el("div", { class: "save-bar", hidden: true });
  const updateBar = () => {
    const changed = changedKeys();
    saveBar.hidden = changed.length === 0;
    const restart = changed.some((k) => byKey[k].restart === "services");
    saveBar.replaceChildren(
      el("span", { text: `${changed.length} ${changed.length === 1 ? "Änderung" : "Änderungen"}${restart ? " · Zeitdienste starten danach neu (wenige Sekunden)" : ""}` }),
      el("div", { class: "save-actions" },
        el("button", { type: "button", class: "button", text: "Verwerfen", onclick: () => { ui.draft = {}; ui.fieldErrors = {}; ctx.rerender(); } }),
        el("button", { type: "button", class: "button primary", text: "Speichern", onclick: save })));
  };
  const setDraft = (key, value) => {
    ui.draft[key] = value;
    delete ui.fieldErrors[key];
    updateBar();
  };

  async function save() {
    const changes = Object.fromEntries(changedKeys().map((k) => [k, ui.draft[k]]));
    try {
      const result = await apiPost("/api/settings", { changes });
      ui.draft = {}; ui.fieldErrors = {};
      toast(result.restart ? (result.reload_triggered ? "Gespeichert – Zeitdienste starten neu" : result.reload_note) : "Gespeichert");
      if (result.reload_triggered) ctx.watchReload();
      ctx.invalidate("settings");
      ctx.refresh();
      ctx.rerender();
    } catch (error) {
      ui.fieldErrors = error.fields || {};
      toast(error.message, "crit");
      ctx.rerender();
    }
  }

  async function reset(key) {
    try {
      const result = await apiPost("/api/settings/reset", { keys: [key] });
      delete ui.draft[key];
      toast(result.reload_triggered ? "Zurückgesetzt – Zeitdienste starten neu" : "Zurückgesetzt");
      if (result.reload_triggered) ctx.watchReload();
      ctx.invalidate("settings");
      ctx.rerender();
    } catch (error) { toast(error.message, "crit"); }
  }

  function control(field) {
    const id = `f-${field.key}`;
    const value = current(field.key);
    const disabled = readonly ? true : null;
    switch (field.type) {
      case "bool": {
        const input = el("input", { type: "checkbox", id, checked: value, disabled, role: "switch" });
        const text = el("span", { class: "switch-text", text: value ? "an" : "aus" });
        input.addEventListener("change", () => { text.textContent = input.checked ? "an" : "aus"; setDraft(field.key, input.checked); });
        return el("label", { class: "switch" }, input, el("span", { class: "switch-track", "aria-hidden": "true" }), text);
      }
      case "select": {
        const select = el("select", { id, disabled }, (field.options || []).map((o) =>
          el("option", { value: o.value, selected: o.value === value ? true : null, text: o.label })));
        select.addEventListener("change", () => setDraft(field.key, select.value));
        return select;
      }
      case "hostlist": {
        const area = el("textarea", { id, rows: Math.max(3, (value || []).length + 1), disabled,
          placeholder: field.placeholder || "ein Name pro Zeile", value: (value || []).join("\n") });
        area.addEventListener("input", () => setDraft(field.key, area.value.split(/[\n,\s]+/).map((s) => s.trim()).filter(Boolean)));
        return area;
      }
      case "networks": {
        const area = el("textarea", { id, rows: Math.max(3, (value || []).length + 1), disabled,
          placeholder: "ein Netz pro Zeile, z. B. 192.168.0.0/16", value: (value || []).join("\n") });
        area.addEventListener("input", () => setDraft(field.key, area.value.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean)));
        return area;
      }
      case "sources": return sourcesEditor(field, value || [], disabled);
      default: {
        const listId = field.type === "device" || field.type === "interface" ? `${id}-list` : null;
        const input = el("input", {
          id, type: field.type === "int" || field.type === "float" ? "number" : "text",
          step: field.type === "float" ? "any" : field.type === "int" ? "1" : null,
          value: value ?? "", placeholder: field.placeholder || null, disabled, list: listId,
          inputmode: field.type === "float" ? "decimal" : null, autocomplete: "off",
        });
        input.addEventListener("input", () => {
          const raw = input.value;
          setDraft(field.key, field.type === "int" ? (raw === "" ? raw : Number.parseInt(raw, 10))
            : field.type === "float" ? (raw === "" ? raw : Number.parseFloat(raw)) : raw);
        });
        const wrap = [input];
        if (listId && devices) {
          const options = field.type === "interface"
            ? (devices.interfaces || []).map((n) => [n.name, n.ptp_hardware ? "PTP-tauglich" : n.virtual_nic ? "virtuell" : "nur Software"])
            : [...(devices.serial || []).map((d) => [d.path, d.description]), ...(devices.serial || []).filter((d) => d.stable_path).map((d) => [d.stable_path, "fester Name"]),
              ...(devices.pps || []).map((d) => [d.path, d.description]), ...(devices.ptp_clocks || []).map((d) => [d.path, d.description])];
          wrap.push(el("datalist", { id: listId }, options.map(([v, l]) => el("option", { value: v, label: l }))));
        }
        if (field.unit) wrap.push(el("span", { class: "unit-suffix", text: field.unit }));
        return el("div", { class: "input-wrap" }, wrap);
      }
    }
  }

  function sourcesEditor(field, rows, disabled) {
    const list = el("div", { class: "src-editor" });
    const commit = (next) => { setDraft(field.key, next); draw(next); };
    function draw(items) {
      list.replaceChildren(
        el("div", { class: "src-editor-head" }, ["Typ", "Server oder Pool", "NTS", "bevorzugen", "nur beobachten", ""].map((h) => el("span", { text: h }))),
        ...items.map((row, index) => {
          const update = (patch) => { const next = clone(items); next[index] = { ...next[index], ...patch }; commit(next); };
          const type = el("select", { disabled, "aria-label": "Typ" }, ["server", "pool", "peer"].map((t) =>
            el("option", { value: t, selected: row.type === t ? true : null, text: t })));
          type.addEventListener("change", () => update({ type: type.value }));
          const host = el("input", { type: "text", value: row.host, disabled, "aria-label": "Server oder Pool", placeholder: "z. B. ptbtime1.ptb.de" });
          host.addEventListener("change", () => update({ host: host.value.trim() }));
          const box = (key, label) => {
            const input = el("input", { type: "checkbox", checked: row[key], disabled, "aria-label": label });
            input.addEventListener("change", () => update({ [key]: input.checked }));
            return el("label", { class: "cell-check" }, input);
          };
          return el("div", { class: "src-editor-row" }, type, host, box("nts", "NTS"), box("prefer", "bevorzugen"),
            box("noselect", "nur beobachten"),
            el("button", { type: "button", class: "icon-button", disabled, "aria-label": `${row.host} entfernen`, text: "✕",
              onclick: () => commit(items.filter((_, i) => i !== index)) }));
        }),
        el("div", { class: "src-editor-tools" },
          el("button", { type: "button", class: "button", disabled, text: "+ Quelle",
            onclick: () => commit([...items, { type: "server", host: "", nts: false, prefer: false, noselect: false, options: "" }]) }),
          el("span", { class: "muted", text: "Vorlagen:" }),
          PRESETS.map(([label, entries]) => el("button", { type: "button", class: "chip", disabled, text: label, onclick: () => {
            const next = clone(items);
            for (const [t, h, nts] of entries) {
              if (!next.some((r) => r.host === h)) next.push({ type: t, host: h, nts, prefer: false, noselect: false, options: "" });
            }
            commit(next);
          } }))));
    }
    draw(rows.map((r) => ({ options: "", ...r })));
    return list;
  }

  function fieldRow(field) {
    const error = ui.fieldErrors[field.key] || field.error;
    const sourceText = field.source === "env" && field.env ? `Umgebung (${field.env})` : SOURCE_LABEL[field.source];
    return el("div", { class: `field${error ? " has-error" : ""}`, id: `row-${field.key}` },
      el("div", { class: "field-head" },
        el("span", { class: "field-label" }, el("label", { for: `f-${field.key}`, text: field.label }), " ",
          FIELD_HELP[field.key] ? info(FIELD_HELP[field.key], field.label) : null),
        el("span", { class: "field-meta" },
          badge(sourceText, field.source === "gui" ? "info" : "muted"),
          field.restart === "none" ? badge("wirkt sofort", "muted") : null,
          field.source === "gui" && !readonly ? el("button", { type: "button", class: "link", text: "zurücksetzen",
            title: "Dashboard-Wert entfernen – dann gilt wieder Umgebung bzw. Standard", onclick: () => reset(field.key) }) : null)),
      control(field),
      el("p", { class: "field-help" }, rich(field.help)),
      error ? el("p", { class: "field-error", role: "alert", text: error }) : null);
  }

  const out = [];
  out.push(notesCard(ctx, schema.notes, readonly));
  if (!fields.length) {
    out.push(card("Einstellungen nicht lesbar", { class: "card-alert" },
      emptyNote("Der Server hat keine Felder geliefert – Seite neu laden oder das Container-Log ansehen.")));
  }
  if (readonly) out.push(card("Einstellungen gesperrt", { class: "card-alert" }, emptyNote("`WEB_READONLY=true` ist gesetzt – hier lässt sich nur ansehen, nicht ändern.")));
  if (!((schema.storage || {}).persistent ?? true)) {
    out.push(card("Achtung: Einstellungen sind nicht dauerhaft", { class: "card-alert" }, el("p", {}, rich(
      "`/var/lib/chrony` liegt auf keinem Volume. Gespeichertes geht verloren, wenn der Container **neu erstellt** wird (ein Neustart reicht nicht). "
      + "In der Compose-Datei: `volumes: [chrony-data:/var/lib/chrony]`."))));
  }
  out.push(card("Wie Einstellungen wirken", { help: "settings_source", class: "explain" }, el("p", {}, rich(
    "Werte aus diesem Dashboard haben **Vorrang** vor Umgebungsvariablen aus der Compose-Datei; die gelten als Startwerte. "
    + "Nach dem Speichern starten die Zeitdienste neu – das dauert wenige Sekunden, chrony behält seine Messhistorie. "
    + "Eine eigene `/config/chrony.conf` ersetzt die erzeugte Konfiguration komplett."))));

  for (const section of Array.isArray(schema.sections) ? schema.sections : []) {
    const sectionFields = fields.filter((f) => f.section === section.key);
    if (!sectionFields.length) continue;
    const advancedCount = sectionFields.filter((f) => f.advanced).length;
    const showAdv = ui.showAdvanced[section.key];
    const visible = sectionFields.filter((f) => !f.advanced || showAdv || f.source === "gui" || f.source === "env");
    const toggle = advancedCount ? el("button", { type: "button", class: "link", text: showAdv ? "Weniger anzeigen" : `Erweitert (${advancedCount})`,
      "aria-expanded": showAdv ? "true" : "false", onclick: () => { ui.showAdvanced[section.key] = !showAdv; ctx.rerender(); } }) : null;
    const helpKey = { ntp: "minsources", lan: "island", nts: "nts", dns: "dns", gps: "gps_value", ptp: "ptp_requirements", web: "settings_source" }[section.key];
    // Titel und Beschreibung aus dem Sprachkatalog; unbekannte Abschnitte behalten den Servertext.
    const titleKey = `settings.section.${section.key}.title`;
    const descKey = `settings.section.${section.key}.description`;
    out.push(card(has(titleKey) ? t(titleKey) : section.label, { id: `s-${section.key}`, help: helpKey,
      sub: has(descKey) ? t(descKey) : section.description, actions: toggle },
      section.key === "dns" ? dnsStatus(dns) : null,
      section.key === "web" ? updateStatus(update) : null,
      section.key === "web" ? languageRow() : null,
      el("div", { class: "fields" }, visible.map(fieldRow))));
  }

  // Zugang zum Dashboard
  const auth = schema.auth || {};
  const authBody = [];
  if (auth.source === "env") {
    authBody.push(emptyNote(`Geschützt per Umgebungsvariable (Benutzer **${auth.user}**). Ändern nur in der Compose-Datei.`));
  } else {
    const user = el("input", { type: "text", autocomplete: "username", value: auth.user || "admin", "aria-label": "Benutzername", disabled: readonly ? true : null });
    const pass = el("input", { type: "password", autocomplete: "new-password", placeholder: "mindestens 8 Zeichen", "aria-label": "Passwort", disabled: readonly ? true : null });
    const pass2 = el("input", { type: "password", autocomplete: "new-password", placeholder: "wiederholen", "aria-label": "Passwort wiederholen", disabled: readonly ? true : null });
    const setPw = async () => {
      if (pass.value !== pass2.value) { toast("Die Passwörter stimmen nicht überein", "crit"); return; }
      try {
        await apiPost("/api/auth", { user: user.value, password: pass.value });
        toast("Passwort gesetzt – der Browser fragt gleich danach");
        setTimeout(() => window.location.reload(), 900);
      } catch (error) { toast(error.message, "crit"); }
    };
    authBody.push(el("p", {}, rich(auth.enabled ? `Geschützt – Benutzer **${auth.user}**.` : "**Ohne Passwort** kann jeder im LAN die Einstellungen ändern.")));
    authBody.push(el("div", { class: "auth-form" },
      el("label", {}, el("span", { text: "Benutzer" }), user),
      el("label", {}, el("span", { text: auth.enabled ? "Neues Passwort" : "Passwort" }), pass),
      el("label", {}, el("span", { text: "Wiederholen" }), pass2),
      el("button", { type: "button", class: "button primary", text: auth.enabled ? "Passwort ändern" : "Passwort setzen", disabled: readonly ? true : null, onclick: setPw }),
      auth.enabled ? el("button", { type: "button", class: "button", text: "Schutz entfernen", disabled: readonly ? true : null, onclick: async () => {
        try { await apiPost("/api/auth", { clear: true }); toast("Schutz entfernt"); ctx.invalidate("settings"); ctx.rerender(); } catch (error) { toast(error.message, "crit"); }
      } }) : null));
    authBody.push(emptyNote("Gilt für das Dashboard und die API. `/healthz` bleibt für den Docker-Healthcheck offen. Kein TLS – für Zugriff von außen einen Reverse Proxy davorsetzen."));
  }
  out.push(card("Zugang zum Dashboard", { id: "s-auth" }, authBody));
  if (auth.enabled || !readonly) out.push(apiCard(ctx, readonly, auth));

  // Sichern & Wiederherstellen
  const fileInput = el("input", { type: "file", accept: "application/json,.json", hidden: true });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const result = await apiPost("/api/settings/import", data.values ? { values: data.values, schema: data.schema ?? 1 } : { values: data });
      toast(result.reload_triggered ? "Importiert – Zeitdienste starten neu" : "Importiert");
      for (const note of result.notes || []) toast(note, "warn");
      if (result.reload_triggered) ctx.watchReload();
      ctx.invalidate("settings"); ctx.rerender();
    } catch (error) { toast(`Import fehlgeschlagen: ${error.message}`, "crit"); }
    fileInput.value = "";
  });
  out.push(card("Sichern und übertragen", {},
    el("p", { text: "Die im Dashboard gespeicherten Werte als Datei sichern oder auf einen anderen Server übertragen (ohne Passwort)." }),
    el("div", { class: "button-row" },
      el("a", { class: "button", href: "/api/settings/export", download: "ntp-gui-einstellungen.json", text: "Exportieren" }),
      el("button", { type: "button", class: "button", text: "Importieren …", disabled: readonly ? true : null, onclick: () => fileInput.click() }),
      fileInput),
    el("p", { class: "field-help export-note" }, el("span", {}, rich("Die Sicherung ist **ungefiltert**: Sie enthält "
      + "Hostnamen, Server und Netze genau so, wie sie hier eingetragen sind. Nicht öffentlich teilen – für "
      + "Fehlerberichte das gefilterte **Diagnosepaket** nehmen.")), info("settings_export", "Sicherung"))));

  out.push(card("Nur per Umgebungsvariable", { sub: "Diese Werte steuern den Start selbst und lassen sich deshalb nur in der Compose-Datei setzen." },
    el("table", { class: "mini-table" }, el("tbody", {}, (schema.env_only || []).map((e) => el("tr", {},
      el("td", { class: "mono", text: e.name }), el("td", { text: e.label }),
      el("td", { class: "mono", text: e.set ? (e.value || "(gesetzt)") : "–" })))))));

  out.push(saveBar);
  updateBar();
  ctx.afterRender(() => {
    const target = new URLSearchParams(window.location.hash.split("?")[1] || "").get("s");
    if (target && !ui.scrolled) {
      ui.scrolled = true;
      document.getElementById(`s-${target}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  return out;
}

export { info, apiGet };
