import { el, rich, apiPost, apiGet, apiUpload, fmtNumber, fmtDate as fmtDateTime, fmtZoned, serverZone, isNum } from "../util.js";
import { card, infoButton, badge, kv, emptyState, toast, copyButton, isPopoverOpen } from "../ui.js";
import { t, has, language, setLanguage, LANGUAGES } from "../i18n.js";
import { HELP } from "../help.js";
import { route } from "../routes.js";

export const live = false; // nicht bei jedem Refresh neu aufbauen – Eingaben bleiben stehen

// Vorlagen für Zeitquellen – feste Liste im Code (auch im Willkommens-Assistenten, pages/setup.js).
export const PRESETS = [
  ["PTB (NTS)", [["server", "ptbtime1.ptb.de", true], ["server", "ptbtime2.ptb.de", true], ["server", "ptbtime3.ptb.de", true]]],
  ["Cloudflare (NTS)", [["server", "time.cloudflare.com", true]]],
  ["Netnod (NTS)", [["server", "nts.netnod.se", true]]],
  ["de.pool.ntp.org", [["pool", "de.pool.ntp.org", false]]],
  ["pool.ntp.org", [["pool", "pool.ntp.org", false]]],
];

/** Quellenliste plus Vorlage: vorhandene Einträge bleiben, nur fehlende Server kommen hinten dazu. */
export function withPreset(items, entries) {
  const next = JSON.parse(JSON.stringify(items || []));
  for (const [type, host, nts] of entries) {
    if (!next.some((r) => r.host === host)) next.push({ type, host, nts, prefer: false, noselect: false, options: "" });
  }
  return next;
}

// ⓘ neben einzelnen Feldern: verweist auf die ausführliche Erklärung in der Hilfe.
// Die sichtbare Zeile unter jedem Feld („hint“) und der Rest im ⓘ („more“) kommen vom Server (Schema).
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
  temp_sensor: "temp_sensor", clock_public: "clock_public", update_check: "update_check", backup_nightly: "backup_nightly",
  trusted_proxies: "trusted_proxies", web_allowed_hosts: "allowed_hosts",
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
        infoButton("ui_language", t("settings.language.label"),
          { title: t("settings.language.label"), text: t("settings.language.note_more") }))),
    select,
    el("p", { class: "field-help", text: t("settings.language.note") })));
}

// Datum und Uhrzeit, ohne Wert „nie“.
function dateOrNever(unix) {
  return fmtDateTime(unix, { empty: "nie" });
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
  if (keys === undefined) return [emptyState("Schlüssel werden geladen …")];
  if (!keys || !keys.keys || !keys.keys.length) return [emptyState("Noch keine Schlüssel angelegt.")];
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
    kv([["Angelegt", dateOrNever(key.created), "api_keys"], ["Zuletzt benutzt", dateOrNever(key.last_used), "api_key_used"]]),
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
    body.push(emptyState("Noch ist **kein Passwort** gesetzt – das Dashboard und die API sind im LAN offen. "
      + "Schlüssel wirken trotzdem schon mit ihrem Recht; wirklich nötig werden sie, sobald du oben ein Passwort setzt."));
  }
  if (ui.newKey) {
    const token = ui.newKey.token;
    body.push(el("div", { class: "apikey-new", role: "status" },
      el("div", { class: "apikey-new-head" }, el("strong", { text: `Neuer Schlüssel „${ui.newKey.name}“` }), infoButton("api_key_token", "Neuer Schlüssel")),
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
    el("label", {}, el("span", {}, "Recht ", infoButton("api_key_scope", "Recht")), scope),
    el("button", { type: "button", class: "button primary", text: "Schlüssel anlegen", disabled, onclick: create })));
  const keyBox = el("div", { class: "apikey-box" }, keyListNodes(ctx, keys, disabled));
  body.push(keyBox);
  ctx.afterRender(() => watchKeys(ctx, keyBox, disabled));
  body.push(el("p", { class: "field-help" }, rich("Beschreibung aller Endpunkte samt nötigem Recht: `GET /api/v1`. "
    + "Beispiel: `curl -H \"Authorization: Bearer ntpg_…\" http://<server>:8080/api/v1/status`"), " ", infoButton("api_v1", "Versionierte API")));

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
      ["Seit", inst ? dateOrNever(inst.since) : "–", "instance_id"]]),
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
  return age < 90 ? `vor ${Math.round(age)} s` : age < 5400 ? `vor ${Math.round(age / 60)} min` : dateOrNever(unix);
}

// Update-Hinweis: nur Zustand anzeigen; ein-/ausschalten über das Feld „update_check“ darunter.
const RELEASE_LINK = /^https:\/\/github\.com\/mgc20\/ntp-gui\/releases(\/tag\/v[0-9A-Za-z.-]+)?$/;

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
    ["Nächste Prüfung", typeof upd.next_check === "number" ? dateOrNever(upd.next_check) : "–", "update_next"],
  ];
  return el("div", { class: "update-status" },
    el("h3", { class: "mini-head" }, "Update-Hinweis ", infoButton("update_check", "Update-Hinweis")),
    kv(rows),
    upd.error ? el("p", { class: "field-error", role: "alert", text: `Letzte Prüfung gescheitert: ${upd.error}` }) : null);
}

function dnsStatus(dns) {
  if (dns === undefined) return emptyState("Zustand wird geladen …");
  if (!dns) return emptyState("Zustand nicht verfügbar.");
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
    dns.nts_note ? el("p", { class: "card-sub" }, el("span", { text: dns.nts_note }), infoButton("dns_nts", "NTS und DNS")) : null,
    ups.length ? el("div", {},
      el("h3", { class: "mini-head" }, "Eigene Server ", infoButton("dns_upstreams", "Eigene Server")),
      el("ul", { class: "svc-list" }, ups.map((u) => {
        const down = typeof u.down_until === "number" && u.down_until * 1000 > Date.now();
        const tone = down ? "warn" : u.ok ? "good" : u.fail ? "warn" : "muted";
        return el("li", { class: "svc", "data-tone": tone },
          el("span", { class: "svc-dot", "aria-hidden": "true" }),
          el("span", { class: "svc-name mono", text: u.label }),
          badge(down ? "übersprungen" : u.ok ? "antwortet" : u.fail ? "Fehler" : "noch nicht gefragt", tone),
          el("span", { class: "svc-message", text: `${u.ok} ok · ${u.fail} Fehler · zuletzt ok ${fmtAgo(u.last_ok)}`
            + (typeof u.rtt_ms === "number" ? ` · ${fmtNumber(u.rtt_ms, 1, { group: false })} ms` : "")
            + (u.last_error ? ` · letzter Fehler (${fmtAgo(u.last_error_t)}): ${u.last_error}` : "") }));
      }))) : null);
}

// --- Sichern und wiederherstellen (1.6, T5) ---------------------------------------------------------
// Herunterladen ist ein Link (GET /api/backup); Wiederherstellen in zwei Schritten: Datei hochladen →
// Vorschau vom Server (prüft alles, ändert nichts) → „Übernehmen“ mit Rückfrage.
function backupDate(ctx, unix) {
  if (!isNum(unix)) return "–";
  const sys = ctx.status?.system || null;
  return fmtZoned(unix, serverZone(sys) ? sys : null, { day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit" });
}

function plural(n, one, other) {
  return `${fmtNumber(n)} ${n === 1 ? one : other}`;
}

function fmtSize(bytes) {
  if (!isNum(bytes)) return "–";
  return bytes >= 1024 * 1024 ? `${fmtNumber(bytes / (1024 * 1024), 1)} MiB` : `${fmtNumber(Math.max(1, Math.round(bytes / 1024)))} KiB`;
}

function backupPreview(ctx, preview) {
  const history = preview.history || {};
  const cal = preview.calibration || {};
  const channels = preview.channels || {};
  const setts = preview.settings || {};
  const reenter = [
    ...(setts.reenter || []).map((item) => `Einstellung „${item.label}“`),
    ...(channels.reenter || []).map((item) => `Kanal „${item.name}“ (${item.type}): ${item.what}`),
  ];
  const days = isNum(history.days) ? history.days : 0;
  const items = channels.items || [];
  const removed = channels.removed || [];
  const replaced = channels.replaced || [];
  const security = setts.security || [];
  const dropped = cal.dropped || [];
  const channelText = (item) => {
    if (item.dropped) return `${item.type} → ${item.host}: wird nicht übernommen (${item.dropped})`;
    const parts = [`${item.type} → ${item.host}`, item.known ? "vorhanden" : "neu"];
    parts.push(item.enabled ? "bleibt eingeschaltet" : "wird ausgeschaltet übernommen");
    if (item.reenter) parts.push(`neu einzugeben: ${item.reenter}`);
    return parts.join(" · ");
  };
  return el("div", { class: "backup-preview" },
    kv([
      ["Sicherung vom", `${backupDate(ctx, preview.created)}${preview.version ? ` · ntp-gui ${preview.version}` : ""}`
        + (preview.schema?.migrated ? " · ältere Version, wird umgewandelt" : ""), "backup_created"],
      ["Verlauf", `${fmtNumber(days, days < 10 ? 1 : 0)} Tage · ${plural(history.samples || 0, "Messpunkt", "Messpunkte")}`
        + (history.skipped ? ` · ${plural(history.skipped, "Messpunkt liegt", "Messpunkte liegen")} nach dem Zeitpunkt der Sicherung oder in der Zukunft und ${history.skipped === 1 ? "wird" : "werden"} nicht übernommen` : ""), "backup_history"],
      ["Geräte", `${plural(preview.devices || 0, "Gerät", "Geräte")}, ${fmtNumber(preview.names || 0)} mit eigenem Namen`, "backup_devices"],
      ["Gruppen und Regeln", `${plural(preview.groups || 0, "Gruppe", "Gruppen")}, ${plural(preview.rules || 0, "Regel", "Regeln")}`, "backup_groups"],
      ["Ereignisse", fmtNumber(preview.events || 0), "backup_events"],
      ["Kalibrierung", (isNum(cal.last_change) ? `letzte Änderung ${backupDate(ctx, cal.last_change)}` : "kein Protokoll")
        + (isNum(cal.gps_offset) ? ` · GPS-Offset ${fmtNumber(cal.gps_offset, 4, { group: false })} s` : "")
        + (dropped.length ? ` · ${plural(dropped.length, "ungültiger Teil", "ungültige Teile")} verworfen` : ""), "backup_calibration"],
      ["Benachrichtigungen", `${plural(channels.count || 0, "Kanal", "Kanäle")}`
        + (items.some((item) => !item.dropped && !item.enabled) ? `, ${fmtNumber(items.filter((item) => !item.dropped && !item.enabled).length)} ausgeschaltet` : "")
        + ((channels.reenter || []).length ? `, ${fmtNumber(channels.reenter.length)} ohne Token bzw. Adresse – bitte neu eingeben` : "")
        + (removed.length ? `, ${plural(removed.length, "Kanal", "Kanäle")} von hier ${removed.length === 1 ? "fällt" : "fallen"} weg` : "")
        + (replaced.length ? `, ${plural(replaced.length, "Kanal", "Kanäle")} von hier ${replaced.length === 1 ? "wird" : "werden"} durch die Fassung aus der Sicherung ersetzt` : ""), "backup_channels"],
      ["Einstellungen", `${plural(setts.count || 0, "gespeicherter Wert", "gespeicherte Werte")}`
        + (setts.restart ? " · Zeitdienste starten danach neu" : " · ohne Neustart der Zeitdienste"), "backup_settings"],
    ]),
    items.length ? el("div", { class: "backup-reenter" },
      el("p", { class: "field-help" }, el("strong", { text: "Benachrichtigungskanäle: " }), infoButton("backup_channels", "Benachrichtigungskanäle")),
      el("ul", {}, items.map((item) => el("li", {}, el("strong", { text: `${item.name}: ` }), el("span", { text: channelText(item) }))))) : null,
    removed.length ? el("div", { class: "backup-reenter" },
      el("p", { class: "field-help" }, el("strong", { text: "Diese Kanäle gibt es nur hier – sie werden gelöscht: " }), infoButton("backup_channels", "Benachrichtigungskanäle")),
      el("ul", {}, removed.map((item) => el("li", {}, el("strong", { text: `${item.name}: ` }),
        el("span", { text: `${item.type} → ${item.host}${item.secret ? " · Token bzw. Adresse geht verloren, auch die automatische Sicherung davor enthält sie nicht" : ""}` }))))) : null,
    replaced.length ? el("div", { class: "backup-reenter" },
      el("p", { class: "field-help" }, el("strong", { text: "Diese Kanäle stehen in der Sicherung mit anderer Art oder anderem Server – sie werden ersetzt: " }), infoButton("backup_channels", "Benachrichtigungskanäle")),
      el("ul", {}, replaced.map((item) => el("li", {}, el("strong", { text: `${item.name}: ` }),
        el("span", { text: `jetzt ${item.type} → ${item.host}, danach ${item.new_type} → ${item.new_host}${item.secret ? " · jetziger Token bzw. Adresse geht verloren, auch die automatische Sicherung davor enthält sie nicht" : ""}` }))))) : null,
    security.length ? el("div", { class: "backup-reenter" },
      el("p", { class: "field-help" }, el("strong", { text: "Diese sicherheitsrelevanten Einstellungen ändern sich: " }), infoButton("backup_security", "Sicherheitsrelevante Einstellungen")),
      el("ul", {}, security.map((item) => el("li", { text: `${item.label}: ${item.before} → ${item.after}` })))) : null,
    dropped.length ? el("div", { class: "backup-reenter" },
      el("p", { class: "field-help" }, el("strong", { text: "Kalibrierung – verworfen, weil ungültig: " }), infoButton("backup_calibration", "Kalibrierung")),
      el("ul", {}, dropped.map((text) => el("li", { text })))) : null,
    reenter.length ? el("div", { class: "backup-reenter" },
      el("p", { class: "field-help" }, el("strong", { text: "Bitte nach dem Übernehmen neu eingeben: " }), infoButton("backup_reenter", "Bitte neu eingeben")),
      el("ul", {}, reenter.map((text) => el("li", { text })))) : null,
    (setts.skipped || []).length ? el("div", { class: "backup-reenter" },
      el("p", { class: "field-help" }, el("strong", { text: "Übersprungen (ungültig oder unbekannt): " }), infoButton("backup_settings", "Einstellungen")),
      el("ul", {}, setts.skipped.map((item) => el("li", { text: `${item.label}: ${item.why}` })))) : null,
    (setts.notes || []).length ? el("ul", { class: "backup-notes" }, setts.notes.map((text) => el("li", { text }))) : null);
}

// rows: Feldzeilen aus dem Schema, die hier stehen (Schalter „Nächtliche Sicherung“).
function backupCard(ctx, readonly, rows = []) {
  const ui = ctx.uiState;
  ui.backup = ui.backup || {};
  const state = ui.backup;
  const stored = ctx.data("backups", "/api/backup/list", 60);
  const fileInput = el("input", { type: "file", accept: ".gz,.tgz,application/gzip", hidden: true });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    state.busy = "Prüfe die Sicherung …"; state.preview = null; state.result = null; state.error = null;
    ctx.rerender();
    try {
      const answer = await apiUpload("/api/restore/preview", file);
      state.preview = answer.preview; state.token = answer.token;
    } catch (error) {
      state.error = error.message;
    }
    state.busy = null;
    ctx.rerender();
  });
  const discard = async () => {
    const token = state.token;
    state.preview = null; state.token = null; state.error = null;
    ctx.rerender();
    if (token) { try { await apiPost("/api/restore/cancel", { token }); } catch (error) { /* verfällt ohnehin */ } }
  };
  const take = async () => {
    const restart = state.preview?.settings?.restart;
    const holdover = ctx.status?.holdover_active && restart ? " Gerade läuft ein Holdover-Test – der Neustart der Zeitdienste bricht ihn ab." : "";
    const removed = state.preview?.channels?.removed || [];
    const replaced = state.preview?.channels?.replaced || [];
    if (!window.confirm("Die Sicherung ersetzt Einstellungen, Verlauf, Ereignisse, Geräte, Namen, Gruppen, Regeln, "
      + "Kalibrierung und Benachrichtigungskanäle. Der jetzige Stand wird vorher im Datenverzeichnis gesichert (ohne "
      + "Tokens). Kanäle mit gleicher Kennung, gleicher Art und gleichem Server behalten ihre Tokens; alle anderen "
      + "kommen ausgeschaltet"
      + (removed.length ? `; ${plural(removed.length, "Kanal", "Kanäle")}, die es nur hier gibt, ${removed.length === 1 ? "wird" : "werden"} samt Token gelöscht` : "")
      + (replaced.length ? `; ${plural(replaced.length, "Kanal", "Kanäle")} mit anderer Art oder anderem Server in der Sicherung ${replaced.length === 1 ? "wird" : "werden"} ersetzt, ${replaced.length === 1 ? "sein" : "ihr"} jetziger Token geht verloren` : "")
      + ". Das Dashboard ist dabei einige "
      + `Sekunden beschäftigt.${restart ? " Die Zeitdienste starten danach neu." : ""}${holdover} Übernehmen?`)) return;
    state.busy = "Übernehme die Sicherung … Das Dashboard ist dabei einige Sekunden beschäftigt.";
    ctx.rerender();
    try {
      const result = await apiPost("/api/restore/apply", { token: state.token });
      state.result = result; state.preview = null; state.token = null;
      toast(result.reload_triggered ? "Wiederhergestellt – Zeitdienste starten neu" : "Wiederhergestellt");
      if (result.reload_triggered) ctx.watchReload();
      ctx.invalidate("settings"); ctx.invalidate("backups");
    } catch (error) {
      state.error = error.message; state.preview = null; state.token = null;
      toast(`Wiederherstellen fehlgeschlagen: ${error.message}`, "crit");
    }
    state.busy = null;
    ctx.rerender();
  };

  const body = [
    el("p", { class: "field-help export-note backup-warning" }, el("span", {}, rich("Die Sicherung **enthält Daten über Geräte "
      + "in deinem Netz** (Adressen, Namen, Verlauf) – nicht öffentlich teilen. Für Fehlerberichte das gefilterte "
      + "**Diagnosepaket** nehmen.")), infoButton("backup_privacy", "Wer die Datei sehen darf")),
    kv([
      ["Enthalten", "Einstellungen, Verlauf, Ereignisse, Geräte mit Namen, Gruppen, Regeln, Kalibrierung, Benachrichtigungskanäle", "backup_contents"],
      ["Nie enthalten", "GPS-Position, Satellitenwinkel, Passwort, API-Schlüssel, Tokens, NTS-Schlüssel", "backup_excluded"],
    ]),
    el("div", { class: "button-row" },
      el("a", { class: "button primary", href: "/api/backup", download: "", text: "Sicherung herunterladen" }),
      el("button", { type: "button", class: "button", text: "Wiederherstellen …", disabled: readonly || state.busy ? true : null,
        onclick: () => fileInput.click() }),
      infoButton("backup_restore", "Wiederherstellen"),
      fileInput),
  ];
  if (state.busy) body.push(emptyState(state.busy));
  if (state.error) body.push(el("p", { class: "field-error", role: "alert", text: state.error }));
  if (state.preview) {
    body.push(el("h3", { class: "mini-head", text: "Vorschau – noch ist nichts geändert" }));
    body.push(backupPreview(ctx, state.preview));
    body.push(el("p", { class: "field-help" }, el("span", { text: "Das Dashboard ist während der Übernahme einige Sekunden beschäftigt." }),
      infoButton("backup_busy", "Während der Übernahme")));
    body.push(el("div", { class: "button-row" },
      el("button", { type: "button", class: "button primary", text: "Übernehmen", disabled: readonly || state.busy ? true : null, onclick: take }),
      el("button", { type: "button", class: "button", text: "Verwerfen", onclick: discard })));
  }
  if (state.result) {
    const result = state.result;
    body.push(el("div", { class: "backup-result", role: "status" },
      el("p", {}, el("strong", { text: `Wiederhergestellt aus der Sicherung vom ${backupDate(ctx, result.created)}. ` }),
        el("span", { text: `Der vorherige Stand liegt als „${result.before}“ im Ordner „sicherungen“.` })),
      (result.reenter || []).length ? el("div", { class: "backup-reenter" },
        el("p", { class: "field-help" }, el("strong", { text: "Jetzt bitte neu eingeben: " }), infoButton("backup_reenter", "Bitte neu eingeben")),
        el("ul", {}, result.reenter.map((text) => el("li", { text })))) : null));
  }
  const list = stored?.backups || [];
  if (rows.length) body.push(el("div", { class: "fields" }, rows));
  body.push(el("h3", { class: "mini-head" }, "Gespeicherte Sicherungen ", infoButton("backup_stored", "Gespeicherte Sicherungen")));
  body.push(list.length
    ? el("ul", { class: "backup-list" }, list.map((item) => el("li", {},
      el("a", { href: `/api/backup?name=${encodeURIComponent(item.name)}`, download: "", text: item.name }),
      el("span", { class: "muted", text: ` · ${item.kind === "nightly" ? "nächtlich" : "vor einer Wiederherstellung"} · ${backupDate(ctx, item.t)} · ${fmtSize(item.size)}` }))))
    : emptyState(stored?.nightly ? "Noch keine – die erste nächtliche Sicherung entsteht gegen 3 Uhr."
      : "Keine. Die nächtliche Sicherung schaltest du oben mit dem Schalter **Nächtliche Sicherung** ein."));
  return card("Sichern", { id: "s-backup", help: "backup",
    sub: "Alles außer Position und Geheimnissen in einer Datei – für eine neue SD-Karte oder einen neuen Container." }, body);
}


function clone(value) { return JSON.parse(JSON.stringify(value)); }
function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

// --- Einstellungen 2.0 (1.6, T2) ---------------------------------------------------------------------
// Reiter im Abfrageteil (#/system/einstellungen?s=gps); frühere Sprungziele ?s=<abschnitt> (ntp, nts, dns,
// web, auth, api, backup …) landen im passenden Reiter. Suche über alle Reiter, Schalter „nur Geänderte“,
// Abzeichen nur bei geänderten Werten, klebende Speicherleiste mit Vorschau (Diff der chrony.conf/ptp4l.conf
// vom Server: POST /api/settings/preview prüft wie Speichern und schreibt nichts).
export const TABS = [
  { id: "quellen", titleKey: "settings.tab.quellen", sections: ["ntp", "nts", "dns"] },
  { id: "lan", titleKey: "settings.tab.lan", sections: ["lan"] },
  { id: "gps", titleKey: "settings.tab.gps", sections: ["gps"] },
  { id: "ptp", titleKey: "settings.tab.ptp", sections: ["ptp"] },
  { id: "zugang", titleKey: "settings.tab.zugang", sections: ["web"] },
  { id: "sichern", titleKey: "settings.tab.sichern", sections: [] },
];
const DEFAULT_TAB = TABS[0].id;
// Karten außerhalb des Schemas und ihr Reiter.
const EXTRA_TAB = { auth: "zugang", api: "zugang", env: "zugang", backup: "sichern", export: "sichern" };
// Einzelne Felder, die nicht im Reiter ihres Abschnitts stehen (Schalter beim zugehörigen Bereich).
const FIELD_TAB = { backup_nightly: "sichern" };
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

/** Reiter eines Abschnitts (Schema) oder einer Zusatzkarte; Unbekanntes landet im ersten Reiter. */
export function tabOf(section) {
  const tab = TABS.find((entry) => entry.sections.includes(section));
  if (tab) return tab.id;
  return own(EXTRA_TAB, section) ? EXTRA_TAB[section] : DEFAULT_TAB;
}

/** Reiter eines Felds: eigener Eintrag in FIELD_TAB, sonst der Reiter seines Abschnitts. */
export function fieldTab(field) {
  return own(FIELD_TAB, field?.key) ? FIELD_TAB[field.key] : tabOf(field?.section);
}

/** Reiter aus dem Abfrageteil („s=gps“, auch alte Sprungziele wie „s=web“). */
export function tabFromQuery(query) {
  const target = new URLSearchParams(query || "").get("s") || "";
  if (TABS.some((tab) => tab.id === target)) return target;
  return tabOf(target);
}

function hashQuery() {
  const hash = window.location.hash || "";
  const index = hash.indexOf("?");
  return index < 0 ? "" : hash.slice(index + 1);
}

// Suche: Name, Schlüssel, sichtbare Zeile, ⓘ-Text (Rest des Hilfetexts und die Erklärung aus der Hilfe),
// Umgebungsvariable und Auswahlwerte. Groß/klein und Akzente egal; jedes Wort muss vorkommen.
function normalize(text) {
  return String(text ?? "").replace(/[*`]/g, "").toLocaleLowerCase("de").replace(/ß/g, "ss").normalize("NFKD")
    .replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();
}

const EXTRA_ENTRIES = [
  { id: "ui_language", tab: "zugang", target: "row-ui-language", labelKey: "settings.language.label",
    words: "Sprache Language Deutsch English Beta" },
  { id: "auth", tab: "zugang", target: "s-auth", label: "Zugang zum Dashboard", words: "Passwort Benutzer Anmeldung Schutz" },
  { id: "api", tab: "zugang", target: "s-api", label: "API-Schlüssel und Instanz",
    words: "API Schlüssel Token Bearer Instanz-Kennung Skripte" },
  { id: "env", tab: "zugang", target: "s-env", label: "Nur per Umgebungsvariable", words: "Compose Umgebungsvariable" },
  { id: "backup", tab: "sichern", target: "s-backup", label: "Sichern",
    words: "Sicherung herunterladen wiederherstellen nächtliche Sicherung Backup" },
  { id: "export", tab: "sichern", target: "s-export", label: "Nur Einstellungen übertragen",
    words: "Exportieren Importieren JSON Datei" },
];

/** Suchindex über alle Felder (Schema vom Server) und die Karten außerhalb des Schemas. */
export function searchIndex(fields, help = {}) {
  const out = (Array.isArray(fields) ? fields : []).map((field) => {
    const info = help[FIELD_HELP[field.key]];
    const options = (field.options || []).map((option) => `${option.label} ${option.value}`).join(" ");
    return {
      id: field.key, tab: fieldTab(field), section: field.section, label: field.label,
      advanced: Boolean(field.advanced), target: `row-${field.key}`,
      name: normalize(field.label), key: normalize(field.key),
      text: normalize([field.label, field.key, field.env, field.hint, field.more, field.help, options,
        info?.title, info?.text].filter(Boolean).join(" ")),
    };
  });
  for (const entry of EXTRA_ENTRIES) {
    const label = entry.labelKey ? t(entry.labelKey) : entry.label;
    out.push({ id: entry.id, tab: entry.tab, section: null, label, advanced: false, target: entry.target,
      name: normalize(label), key: normalize(entry.id), text: normalize(`${label} ${entry.id} ${entry.words}`) });
  }
  return out;
}

/** Treffer für eine Eingabe: erst Namen, dann Schlüssel, dann der Rest – sonst in Schema-Reihenfolge. */
export function search(index, query) {
  const words = normalize(query).split(" ").filter(Boolean);
  if (!words.length) return [];
  const rank = (entry) => (words.every((w) => entry.name.includes(w)) ? 0 : words.every((w) => entry.key.includes(w)) ? 1 : 2);
  return index.map((entry, order) => ({ entry, order }))
    .filter(({ entry }) => words.every((w) => entry.text.includes(w)))
    .map((hit) => ({ ...hit, rank: rank(hit.entry) }))
    .sort((a, b) => a.rank - b.rank || a.order - b.order)
    .map((hit) => hit.entry);
}

// Verlassen der Seite (app.js: Hash-Wechsel und beforeunload) mit ungespeicherten Änderungen.
export function leaveMessage(uiState) {
  return uiState?.settings?.pending ? t("settings.leave") : null;
}

export function leave(uiState) {
  if (uiState?.settings) Object.assign(uiState.settings, { draft: {}, defaults: {}, fieldErrors: {}, pending: 0 });
}

// Diff-Zeile → CSS-Klasse; „−“ statt „-“ für entfernte Zeilen (lesbarer), sonst unverändert.
function diffLine(line) {
  if (line.startsWith("+++") || line.startsWith("---")) return el("span", { class: "diff-line diff-file", text: line });
  if (line.startsWith("@@")) return el("span", { class: "diff-line diff-hunk", text: line });
  if (line.startsWith("+")) return el("span", { class: "diff-line diff-add", text: line });
  if (line.startsWith("-")) return el("span", { class: "diff-line diff-del", text: `−${line.slice(1)}` });
  return el("span", { class: "diff-line diff-ctx", text: line });
}

const PREVIEW_STATUS = {
  changed: "settings.preview.changed", same: "settings.preview.same", new: "settings.preview.new",
  unused: "settings.preview.unused", custom: "settings.preview.custom",
};

export function previewFile(file) {
  const lines = Array.isArray(file.diff) ? file.diff : [];
  const added = lines.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length;
  const removed = lines.filter((l) => l.startsWith("-") && !l.startsWith("---")).length;
  const status = t(PREVIEW_STATUS[file.status] || "settings.preview.changed");
  return el("section", { class: "preview-file" },
    el("h3", { class: "preview-name" }, el("code", { text: file.name }), " ",
      badge(status, file.status === "changed" || file.status === "new" ? "info" : "muted"),
      lines.length ? el("span", { class: "muted preview-count", text: ` ${t("settings.preview.lines", { added, removed })}` }) : null),
    lines.length ? el("pre", { class: "diff", tabindex: "0", "aria-label": file.name }, lines.map(diffLine)) : null,
    file.truncated ? el("p", { class: "field-help", text: t("settings.preview.truncated") }) : null);
}

export function render(ctx) {
  const schema = ctx.data("settings", "/api/settings", 0);
  const devices = ctx.data("devices", "/api/devices", 60);
  const dns = ctx.data("dns", "/api/dns", 0);
  const update = ctx.data("update", "/api/update", 60);
  if (!schema) return [card("Einstellungen", {}, emptyState("Wird geladen …"))];
  const ui = ctx.uiState;
  const st = ui.settings = ui.settings || {};
  st.draft = st.draft || {};
  st.defaults = st.defaults || {};
  st.showAdvanced = st.showAdvanced || {};
  st.fieldErrors = st.fieldErrors || {};
  const readonly = schema.readonly;
  const fields = Array.isArray(schema.fields) ? schema.fields : [];
  const byKey = Object.fromEntries(fields.map((f) => [f.key, f]));
  const query = hashQuery();
  const tab = tabFromQuery(query);
  const current = (key) => (key in st.draft ? st.draft[key] : byKey[key]?.value);
  // Entwürfe für Felder, die der Server nicht (mehr) kennt, zählen nicht.
  const draftDiffers = (key) => key in st.draft && key in byKey && !same(st.draft[key], byKey[key].value);
  const changedKeys = () => Object.keys(st.draft).filter(draftDiffers);
  const differsFromDefault = (field) => !same(current(field.key), field.default);
  const isChanged = (field) => differsFromDefault(field) || draftDiffers(field.key);

  // 1.5.3: Läuft ein Holdover-Test, bricht jeder Neustart von chronyd ihn ab – vorher nachfragen.
  const holdoverActive = () => Boolean(ctx.status?.holdover_active);
  const confirmHoldover = () => !holdoverActive() || window.confirm(
    "Gerade läuft ein Holdover-Test. Speichern startet chronyd neu und bricht den Test ab " +
    "(das Ergebnis bis jetzt bleibt erhalten). Trotzdem speichern?");

  const metaBoxes = {};
  const tabCounts = {};
  const saveSummary = el("span", { class: "save-summary" });
  const saveBar = el("div", { class: "save-bar", role: "region", "aria-label": t("settings.savebar.label"), hidden: true },
    saveSummary,
    el("div", { class: "save-actions" },
      el("button", { type: "button", class: "button", text: t("settings.savebar.preview"), onclick: openPreview }),
      el("button", { type: "button", class: "button", text: t("settings.savebar.discard"), onclick: discard }),
      el("button", { type: "button", class: "button primary", text: t("settings.savebar.save"), disabled: readonly ? true : null,
        onclick: save })));
  let previewDialog = null;

  const updateTabCounts = (changed) => {
    for (const entry of TABS) {
      const count = changed.filter((key) => fieldTab(byKey[key]) === entry.id).length;
      const node = tabCounts[entry.id];
      if (!node) continue;
      node.hidden = count === 0;
      node.textContent = count ? String(count) : "";
    }
  };
  const updateBar = () => {
    const changed = changedKeys();
    st.pending = changed.length;
    saveBar.hidden = changed.length === 0;
    const restart = changed.some((k) => byKey[k].restart === "services");
    const parts = [t("settings.savebar.changes", { count: changed.length })];
    if (restart) parts.push(t("settings.savebar.restart"));
    if (restart && holdoverActive()) parts.push(t("settings.savebar.holdover"));
    // Nur den Text tauschen, die Knöpfe bleiben: Verliert ein Feld beim Drücken auf „Speichern“ den Fokus und
    // ändert dabei den Entwurf, müssen Drücken und Loslassen denselben Knopf treffen – sonst kommt kein Klick an.
    saveSummary.textContent = parts.join(" · ");
    updateTabCounts(changed);
  };
  const refreshMeta = (key) => { if (metaBoxes[key] && byKey[key]) metaBoxes[key].replaceChildren(...metaNodes(byKey[key])); };
  const setDraft = (key, value) => {
    st.draft[key] = value;
    delete st.defaults[key];
    delete st.fieldErrors[key];
    updateBar();
    refreshMeta(key);
  };
  function discard() {
    leave(ui);
    closePreview();
    st.refocus = { tab: true };
    ctx.rerender();
  }

  // Was die Speicherleiste schickt: geänderte Werte und Schlüssel, die auf ihren Standard zurückgehen.
  function payload() {
    const changed = changedKeys();
    return {
      changes: Object.fromEntries(changed.filter((k) => !st.defaults[k]).map((k) => [k, st.draft[k]])),
      defaults: changed.filter((k) => st.defaults[k]),
      restart: changed.some((k) => byKey[k]?.restart === "services"),
    };
  }

  async function save() {
    const { changes, defaults, restart } = payload();
    if (!Object.keys(changes).length && !defaults.length) return;
    if (restart && !confirmHoldover()) return;
    try {
      const result = await apiPost("/api/settings", { changes, defaults });
      leave(ui);
      closePreview();
      toast(result.restart ? (result.reload_triggered ? "Gespeichert – Zeitdienste starten neu" : result.reload_note) : "Gespeichert");
      for (const note of result.warnings || []) toast(note, "warn");
      if (result.reload_triggered) ctx.watchReload();
      ctx.invalidate("settings");
      ctx.refresh();
      ctx.rerender();
    } catch (error) {
      st.fieldErrors = error.fields || {};
      toast(error.message, "crit");
      closePreview();
      ctx.rerender();
    }
  }

  function closePreview() {
    if (previewDialog?.open) previewDialog.close();
  }

  async function openPreview() {
    const { changes, defaults, restart } = payload();
    if (!Object.keys(changes).length && !defaults.length) return;
    const content = el("div", { class: "preview-body", "aria-live": "polite" }, emptyState(t("settings.preview.loading")));
    previewDialog?.remove();
    const dialog = el("dialog", { class: "preview-dialog", "aria-labelledby": "preview-title" },
      el("div", { class: "preview-head" },
        el("h2", { id: "preview-title", text: t("settings.preview.title") }),
        el("button", { type: "button", class: "icon-button", "aria-label": t("settings.preview.close"), text: "✕",
          onclick: () => dialog.close() })),
      content,
      el("div", { class: "preview-actions" },
        el("button", { type: "button", class: "button", text: t("settings.preview.close"), onclick: () => dialog.close() }),
        el("button", { type: "button", class: "button primary", text: t("settings.savebar.save"), disabled: readonly ? true : null,
          onclick: save })));
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener("close", () => { dialog.remove(); if (previewDialog === dialog) previewDialog = null; });
    previewDialog = dialog;
    document.body.append(dialog);
    dialog.showModal();
    try {
      const result = await apiPost("/api/settings/preview", { changes, defaults });
      const files = Array.isArray(result.files) ? result.files : [];
      const touched = files.some((file) => file.status === "changed" || file.status === "new");
      // Natives replaceChildren macht aus null den Text „null“ – leere Teile vorher weglassen.
      content.replaceChildren(...[
        // Beide Dateien gleich: Werte wie GPS-Gerät, Baudrate, DNS-Modus oder phc2sys-Optionen wirken trotzdem –
        // über den Neustart der Zeitdienste. „Nur im Dashboard“ stimmt nur ohne solche Änderungen.
        touched ? null : el("p", { class: "preview-none", text: t(restart ? "settings.preview.none_restart" : "settings.preview.none") }),
        ...files.map(previewFile),
        (result.notes || []).length ? el("div", { class: "preview-notes" },
          el("h3", { class: "mini-head", text: t("settings.preview.notes") }),
          el("ul", {}, result.notes.map((note) => el("li", { text: note })))) : null,
      ].filter(Boolean));
    } catch (error) {
      st.fieldErrors = error.fields || {};
      content.replaceChildren(el("p", { class: "field-error", role: "alert", text: t("settings.preview.error", { message: error.message }) }));
      for (const key of Object.keys(st.fieldErrors)) {
        const row = document.getElementById(`row-${key}`);
        if (row && !row.querySelector(".field-error")) {
          row.classList.add("has-error");
          row.append(el("p", { class: "field-error", role: "alert", text: st.fieldErrors[key] }));
        }
      }
    }
  }

  // „zurücksetzen“: auf den Standard – wirkt erst mit dem Speichern.
  function resetToDefault(field) {
    if (same(field.value, field.default)) {
      delete st.draft[field.key];
      delete st.defaults[field.key];
    } else {
      st.draft[field.key] = clone(field.default);
      st.defaults[field.key] = true;
    }
    delete st.fieldErrors[field.key];
    st.refocus = { key: field.key };
    ctx.rerender();
  }
  function undoReset(field) {
    delete st.draft[field.key];
    delete st.defaults[field.key];
    st.refocus = { key: field.key };
    ctx.rerender();
  }

  // Abzeichen nur bei geänderten Werten: „geändert · zurücksetzen“ (bzw. „ungespeichert“ für Entwürfe).
  function metaNodes(field) {
    const key = field.key;
    const nodes = [];
    if (st.defaults[key] && draftDiffers(key)) {
      nodes.push(badge(t("settings.badge.to_default"), "info"));
      nodes.push(el("button", { type: "button", class: "link", text: t("settings.badge.undo"), onclick: () => undoReset(field) }));
      return nodes;
    }
    if (differsFromDefault(field)) {
      const env = field.source === "env" && field.env && !draftDiffers(key);
      nodes.push(badge(t("settings.badge.changed"), "info", env ? t("settings.badge.env", { name: field.env }) : null));
      if (env) nodes.push(el("span", { class: "field-source muted", text: t("settings.badge.env", { name: field.env }) }));
      if (!readonly) {
        nodes.push(el("span", { class: "muted", "aria-hidden": "true", text: "·" }));
        nodes.push(el("button", { type: "button", class: "link", text: t("settings.badge.reset"),
          title: t("settings.badge.reset_title"), "aria-label": `${field.label}: ${t("settings.badge.reset_title")}`,
          onclick: () => resetToDefault(field) }));
      }
    }
    if (draftDiffers(key)) nodes.push(badge(t("settings.badge.unsaved"), "warn"));
    return nodes;
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
        const area = el("textarea", { id, rows: Math.max(2, (value || []).length + 1), disabled,
          placeholder: field.placeholder || "ein Name pro Zeile", value: (value || []).join("\n") });
        area.addEventListener("input", () => setDraft(field.key, area.value.split(/[\n,\s]+/).map((s) => s.trim()).filter(Boolean)));
        return area;
      }
      case "networks": {
        const area = el("textarea", { id, rows: Math.max(2, (value || []).length + 1), disabled,
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
    let items = [];
    // Neu gezeichnet wird nur, wenn Zeilen dazukommen oder wegfallen. Änderungen in einer Zelle (Name beim Tippen,
    // Typ, Kästchen) lassen den Editor stehen: Das Element behält den Fokus, Tab geht zur nächsten Zelle.
    const commit = (next, redraw = true) => { items = next; setDraft(field.key, next); if (redraw) draw(); };
    function draw() {
      list.replaceChildren(
        el("div", { class: "src-editor-head" }, ["Typ", "Server oder Pool", "NTS", "bevorzugen", "nur beobachten", ""].map((h) => el("span", { text: h }))),
        ...items.map((row, index) => {
          const update = (patch) => { const next = clone(items); next[index] = { ...next[index], ...patch }; commit(next, false); };
          const type = el("select", { disabled, "aria-label": "Typ" }, ["server", "pool", "peer"].map((t) =>
            el("option", { value: t, selected: row.type === t ? true : null, text: t })));
          type.addEventListener("change", () => update({ type: type.value }));
          const host = el("input", { type: "text", value: row.host, disabled, "aria-label": "Server oder Pool", placeholder: "z. B. ptbtime1.ptb.de" });
          const remove = el("button", { type: "button", class: "icon-button", disabled, "aria-label": `${row.host} entfernen`, text: "✕",
            onclick: () => commit(items.filter((_, i) => i !== index)) });
          host.addEventListener("input", () => {
            update({ host: host.value.trim() });
            remove.setAttribute("aria-label", `${host.value.trim()} entfernen`);
          });
          const box = (key, label) => {
            const input = el("input", { type: "checkbox", checked: row[key], disabled, "aria-label": label });
            input.addEventListener("change", () => update({ [key]: input.checked }));
            return el("label", { class: "cell-check" }, input, el("span", { class: "cell-check-text", text: label }));
          };
          return el("div", { class: "src-editor-row" }, type, host, box("nts", "NTS"), box("prefer", "bevorzugen"),
            box("noselect", "nur beobachten"), remove);
        }),
        el("div", { class: "src-editor-tools" },
          el("button", { type: "button", class: "button", disabled, text: "+ Quelle",
            onclick: () => commit([...items, { type: "server", host: "", nts: false, prefer: false, noselect: false, options: "" }]) }),
          el("span", { class: "muted", text: "Vorlagen:" }),
          PRESETS.map(([label, entries]) => el("button", { type: "button", class: "chip", disabled, text: label, onclick: () => {
            commit(withPreset(items, entries));
          } }))));
    }
    items = rows.map((r) => ({ options: "", ...r }));
    draw();
    return list;
  }

  // Zusätzliche Werte aus der Umgebung, die neben dem Dashboard-Wert gelten (nur lesend, z. B. WEB_ALLOWED_HOSTS).
  function envExtra(field) {
    const extra = field.env_extra;
    const values = Array.isArray(extra?.values) ? extra.values : [];
    if (!values.length) return null;
    const parts = [];
    values.forEach((v, i) => { if (i) parts.push(", "); parts.push(el("code", { text: String(v) })); });
    return el("p", { class: "field-help", id: `env-${field.key}` },
      el("strong", { text: `Zusätzlich aus ${extra.name} (nur in der Compose-Datei änderbar): ` }), ...parts,
      values.includes("*") ? el("span", { text: " – „*“ schaltet die Namensprüfung ganz ab." }) : null);
  }

  // Pro Feld höchstens eine sichtbare Zeile (Schema: „hint“ ≤ 140 Zeichen); der Rest („more“) steht im ⓘ.
  function fieldRow(field) {
    const error = st.fieldErrors[field.key] || field.error;
    const hint = field.hint ?? field.help;
    const more = field.more ? { title: field.label, text: field.more } : null;
    const meta = el("span", { class: "field-meta" }, metaNodes(field));
    metaBoxes[field.key] = meta;
    return el("div", { class: `field${error ? " has-error" : ""}`, id: `row-${field.key}` },
      el("div", { class: "field-head" },
        el("span", { class: "field-label" }, el("label", { for: `f-${field.key}`, text: field.label }), " ",
          infoButton(FIELD_HELP[field.key] || "", field.label, more)),
        meta),
      control(field),
      envExtra(field),
      hint ? el("p", { class: "field-help" }, rich(hint)) : null,
      error ? el("p", { class: "field-error", role: "alert", text: error }) : null);
  }

  function sectionCard(section) {
    const sectionFields = fields.filter((f) => f.section === section.key && fieldTab(f) === tabOf(section.key));
    if (!sectionFields.length) return null;
    let basic;
    let advanced = [];
    if (st.onlyChanged) {
      basic = sectionFields.filter(isChanged);
      if (!basic.length) return null;
    } else {
      // Eingeklappt bleiben nur erweiterte Felder auf ihrem Standard (Geändertes und Fehler stehen immer da).
      basic = sectionFields.filter((f) => !f.advanced || isChanged(f) || st.fieldErrors[f.key] || f.error
        || (f.env_extra?.values || []).length > 0);
      advanced = sectionFields.filter((f) => !basic.includes(f));
    }
    const showAdv = Boolean(st.showAdvanced[section.key]) && advanced.length > 0;
    const toggle = advanced.length ? el("button", { type: "button", class: "link advanced-toggle",
      text: showAdv ? t("settings.advanced.hide") : t("settings.advanced.show", { count: advanced.length }),
      "aria-expanded": showAdv ? "true" : "false",
      onclick: () => { st.showAdvanced[section.key] = !showAdv; ctx.rerender(); } }) : null;
    const helpKey = { ntp: "minsources", lan: "island", nts: "nts", dns: "dns", gps: "gps_value", ptp: "ptp_requirements", web: "settings_source" }[section.key];
    // Titel und Beschreibung aus dem Sprachkatalog; unbekannte Abschnitte behalten den Servertext.
    const titleKey = `settings.section.${section.key}.title`;
    const descKey = `settings.section.${section.key}.description`;
    return card(has(titleKey) ? t(titleKey) : section.label, { id: `s-${section.key}`, help: helpKey,
      sub: has(descKey) ? t(descKey) : section.description, actions: toggle },
    !st.onlyChanged && section.key === "dns" ? dnsStatus(dns) : null,
    !st.onlyChanged && section.key === "web" ? updateStatus(update) : null,
    !st.onlyChanged && section.key === "web" ? languageRow() : null,
    el("div", { class: "fields" }, basic.map(fieldRow)),
    showAdv ? el("div", { class: "fields fields-advanced" }, advanced.map(fieldRow)) : null);
  }

  // --- Kopf: Reiter, Suche, „nur Geänderte“ ---------------------------------------------------------
  const index = searchIndex(fields, HELP);
  const tabTitle = (id) => t(TABS.find((entry) => entry.id === id)?.titleKey || "settings.tab.quellen");
  const tabsNav = el("nav", { class: "settings-tabs", "aria-label": t("settings.tabs_label") },
    TABS.map((entry) => {
      const count = el("span", { class: "nav-badge tab-count", hidden: true });
      tabCounts[entry.id] = count;
      return el("a", { href: route("settings", "", `s=${entry.id}`), class: `subtab${entry.id === tab ? " is-active" : ""}`,
        "aria-current": entry.id === tab ? "true" : null, dataset: { tab: entry.id } },
      el("span", { text: t(entry.titleKey) }), count);
    }));
  const searchInput = el("input", { type: "search", id: "settings-search", class: "settings-search", autocomplete: "off",
    placeholder: t("settings.search.placeholder"), "aria-label": t("settings.search.label"), "aria-controls": "settings-hits",
    value: st.query || "" });
  const hitsBox = el("div", { class: "search-hits", id: "settings-hits", "aria-live": "polite", hidden: true });
  let hits = [];
  const jump = (entry) => {
    st.query = "";
    st.focus = entry.target;
    if (entry.advanced && entry.section) st.showAdvanced[entry.section] = true;
    if (st.onlyChanged && byKey[entry.id] && !isChanged(byKey[entry.id])) st.onlyChanged = false;
    if (st.onlyChanged && !byKey[entry.id]) st.onlyChanged = false;
    if (entry.tab !== tab) window.location.hash = route("settings", "", `s=${entry.tab}`);
    else ctx.rerender();
  };
  const drawHits = () => {
    hits = search(index, st.query || "");
    hitsBox.hidden = !(st.query || "").trim();
    if (hitsBox.hidden) { hitsBox.replaceChildren(); return; }
    hitsBox.replaceChildren(
      el("p", { class: "search-count muted", text: hits.length ? t("settings.search.hits", { count: hits.length })
        : t("settings.search.none", { query: st.query.trim() }) }),
      hits.length ? el("ul", { class: "search-list" }, hits.slice(0, 12).map((entry) => el("li", {},
        el("button", { type: "button", class: "search-hit", onclick: () => jump(entry) },
          el("span", { class: "search-hit-label", text: entry.label }),
          el("span", { class: "search-hit-where muted", text: entry.advanced
            ? `${tabTitle(entry.tab)} · ${t("settings.search.advanced")}` : tabTitle(entry.tab) }))))) : null);
  };
  searchInput.addEventListener("input", () => { st.query = searchInput.value; drawHits(); });
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && hits.length) { event.preventDefault(); jump(hits[0]); }
    if (event.key === "Escape" && searchInput.value) {
      event.preventDefault(); event.stopPropagation();
      searchInput.value = ""; st.query = ""; drawHits();
    }
  });
  drawHits();
  const onlyChanged = el("button", { type: "button", class: "chip only-changed", "aria-pressed": st.onlyChanged ? "true" : "false",
    text: t("settings.only_changed"), onclick: () => { st.onlyChanged = !st.onlyChanged; ctx.rerender(); } });
  const head = el("div", { class: "settings-head" }, tabsNav,
    el("div", { class: "settings-tools" }, searchInput, onlyChanged,
      el("span", { class: "settings-intro muted" }, rich("Dashboard-Werte haben **Vorrang** vor der Compose-Datei."), " ",
        infoButton("settings_source", "Wie Einstellungen wirken", { title: "Wie Einstellungen wirken", text:
          "Werte aus diesem Dashboard haben **Vorrang** vor Umgebungsvariablen aus der Compose-Datei; die gelten als Startwerte. "
          + "Nach dem Speichern starten die Zeitdienste neu – das dauert wenige Sekunden, chrony behält seine Messhistorie. "
          + "Eine eigene `/config/chrony.conf` ersetzt die erzeugte Konfiguration komplett." }))),
    hitsBox);

  // --- Seite ---------------------------------------------------------------------------------------
  const out = [];
  out.push(notesCard(ctx, schema.notes, readonly));
  if (!fields.length) {
    out.push(card("Einstellungen nicht lesbar", { class: "card-alert" },
      emptyState("Der Server hat keine Felder geliefert – Seite neu laden oder das Container-Log ansehen.")));
  }
  if (readonly) out.push(card("Einstellungen gesperrt", { class: "card-alert" }, emptyState("`WEB_READONLY=true` ist gesetzt – hier lässt sich nur ansehen, nicht ändern.")));
  if (!((schema.storage || {}).persistent ?? true)) {
    out.push(card("Achtung: Einstellungen sind nicht dauerhaft", { class: "card-alert" }, el("p", {}, rich(
      "`/var/lib/chrony` liegt auf keinem Volume. Gespeichertes geht verloren, wenn der Container **neu erstellt** wird (ein Neustart reicht nicht). "
      + "In der Compose-Datei: `volumes: [chrony-data:/var/lib/chrony]`."))));
  }
  out.push(head);

  const tabEntry = TABS.find((entry) => entry.id === tab);
  const panel = [];
  const sections = Array.isArray(schema.sections) ? schema.sections : [];
  for (const section of sections) {
    if (tabOf(section.key) !== tab) continue;
    panel.push(sectionCard(section));
  }

  if (!st.onlyChanged && tab === "zugang") panel.push(...accessCards(ctx, schema, readonly));
  // Felder aus FIELD_TAB, die in diesem Reiter stehen (z. B. „Nächtliche Sicherung“ in „Sichern“).
  const movedHere = fields.filter((f) => fieldTab(f) === tab && tabOf(f.section) !== tab);
  if (tab === "sichern") {
    if (!st.onlyChanged) panel.push(...backupCards(ctx, readonly, confirmHoldover, movedHere.map(fieldRow)));
    else if (movedHere.some(isChanged)) {
      panel.push(card(t(tabEntry.titleKey), {}, el("div", { class: "fields" }, movedHere.filter(isChanged).map(fieldRow))));
    }
  }
  if (!panel.filter(Boolean).length) {
    panel.push(card(t(tabEntry.titleKey), {}, emptyState(st.onlyChanged ? t("settings.only_changed_none") : "Hier gibt es nichts einzustellen.")));
  }
  out.push(el("div", { class: "settings-panel", id: `panel-${tab}` }, panel));

  out.push(saveBar);
  updateBar();
  ctx.afterRender(() => {
    // Der gedrückte Knopf ist nach dem Neuzeichnen weg (bzw. die Speicherleiste versteckt): Fokus bewusst setzen –
    // nach „zurücksetzen“/„rückgängig“ auf den Gegenknopf im Abzeichen oder das Feld, nach „Verwerfen“ auf den Reiter.
    const refocus = st.refocus;
    st.refocus = null;
    if (refocus) {
      const node = refocus.key
        ? document.querySelector(`#row-${refocus.key} .field-meta button.link`) || document.getElementById(`f-${refocus.key}`)
        : document.querySelector(".settings-tabs a[aria-current]");
      node?.focus({ preventScroll: true });
    }
    // Sprungziel: Suchtreffer oder früheres ?s=<abschnitt> (z. B. ?s=nts im Reiter „Quellen“). Erst nach
    // dem Zeichnen – app.js stellt danach noch die Scrollposition wieder her.
    const s = new URLSearchParams(query).get("s") || "";
    let target = st.focus || null;
    const focusField = Boolean(st.focus);
    st.focus = null;
    // ui.scrolled setzt app.js bei jedem Hash-Wechsel zurück – so scrollt auch der zweite Sprung in der
    // Sitzung, das regelmäßige Neuzeichnen aber nicht.
    if (!target && s && s !== tab && !ui.scrolled && document.getElementById(`s-${s}`)) target = `s-${s}`;
    if (!target) return;
    ui.scrolled = true;
    setTimeout(() => {
      const node = document.getElementById(target);
      if (!node) return;
      node.scrollIntoView({ block: focusField ? "center" : "start" });
      if (!focusField) return;
      node.classList.add("is-hit");
      node.querySelector("input:not([type=hidden]), select, textarea, button:not(.info)")?.focus({ preventScroll: true });
      setTimeout(() => node.classList.remove("is-hit"), 2400);
    }, 0);
  });
  return out;
}

// Dashboard & Zugang: Passwort, API-Schlüssel, Werte nur per Umgebungsvariable.
function accessCards(ctx, schema, readonly) {
  const out = [];
  const auth = schema.auth || {};
  const authBody = [];
  if (auth.source === "env") {
    authBody.push(emptyState(`Geschützt per Umgebungsvariable (Benutzer **${auth.user}**). Ändern nur in der Compose-Datei.`));
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
    authBody.push(emptyState("Gilt für das Dashboard und die API. `/healthz` bleibt für den Docker-Healthcheck offen. Kein TLS – für Zugriff von außen einen Reverse Proxy davorsetzen."));
  }
  out.push(card("Zugang zum Dashboard", { id: "s-auth" }, authBody));
  if (auth.enabled || !readonly) out.push(apiCard(ctx, readonly, auth));
  out.push(card("Nur per Umgebungsvariable", { id: "s-env", sub: "Diese Werte steuern den Start selbst und lassen sich deshalb nur in der Compose-Datei setzen." },
    el("table", { class: "mini-table" }, el("tbody", {}, (schema.env_only || []).map((e) => el("tr", {},
      el("td", { class: "mono", text: e.name }), el("td", { text: e.label }),
      el("td", { class: "mono", text: e.set ? (e.value || "(gesetzt)") : "–" })))))));
  return out;
}

// Sichern: Sicherung (T5, unverändert) und „Nur Einstellungen übertragen“.
function backupCards(ctx, readonly, confirmHoldover, rows = []) {
  const fileInput = el("input", { type: "file", accept: "application/json,.json", hidden: true });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    if (!confirmHoldover()) { fileInput.value = ""; return; }
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
  return [backupCard(ctx, readonly, rows),
    card("Nur Einstellungen übertragen", { id: "s-export" },
      el("p", { text: "Die im Dashboard gespeicherten Werte als Datei sichern oder auf einen anderen Server übertragen (ohne Passwort)." }),
      el("div", { class: "button-row" },
        el("a", { class: "button", href: "/api/settings/export", download: "ntp-gui-einstellungen.json", text: "Exportieren" }),
        el("button", { type: "button", class: "button", text: "Importieren …", disabled: readonly ? true : null, onclick: () => fileInput.click() }),
        fileInput),
      el("p", { class: "field-help export-note" }, el("span", {}, rich("Die Sicherung ist **ungefiltert**: Sie enthält "
        + "Hostnamen, Server und Netze genau so, wie sie hier eingetragen sind. Nicht öffentlich teilen – für "
        + "Fehlerberichte das gefilterte **Diagnosepaket** nehmen.")), infoButton("settings_export", "Sicherung")))];
}

export { apiGet };
