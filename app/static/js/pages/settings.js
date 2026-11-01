import { el, rich, apiPost, apiGet } from "../util.js";
import { card, info, badge, emptyNote, toast } from "../ui.js";

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
  ntp_sources: "source_type", ntp_minsources: "minsources", leapsectz: "leap",
  serve_unsynced: "island", local_stratum: "island",
  ntp_hw_timestamp: "timestamping",
  nts_nocerttimecheck: "nocerttimecheck", nts_server_enable: "nts_server",
  nts_server_cert: "nts_server_files", nts_server_key: "nts_server_files",
  gps_enable: "gps", gps_offset: "gps_recalibrate", gps_delay: "gps_delay", gps_select: "gps_role",
  gps_pps_device: "pps",
  ptp_enable: "ptp_vs_ntp", ptp_interface: "ptp_requirements", ptp_mode: "grandmaster", ptp_domain: "ptp_domain",
  ptp_transport: "ptp_transport", ptp_clock_class: "clock_class", phc2sys_enable: "phc2sys", phc_refclock: "phc",
};

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

export function render(ctx) {
  const schema = ctx.data("settings", "/api/settings", 0);
  const devices = ctx.data("devices", "/api/devices", 60);
  if (!schema) return [card("Einstellungen", {}, emptyNote("Wird geladen …"))];
  const ui = ctx.uiState;
  ui.draft = ui.draft || {};
  ui.showAdvanced = ui.showAdvanced || {};
  ui.fieldErrors = ui.fieldErrors || {};
  const readonly = schema.readonly;
  const fields = schema.fields;
  const byKey = Object.fromEntries(fields.map((f) => [f.key, f]));
  const current = (key) => (key in ui.draft ? ui.draft[key] : byKey[key].value);
  const changedKeys = () => Object.keys(ui.draft).filter((k) => !same(ui.draft[k], byKey[k].value));

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
        const select = el("select", { id, disabled }, field.options.map((o) =>
          el("option", { value: o.value, selected: o.value === value ? true : null, text: o.label })));
        select.addEventListener("change", () => setDraft(field.key, select.value));
        return select;
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
            ? devices.interfaces.map((n) => [n.name, n.ptp_hardware ? "PTP-tauglich" : n.virtual_nic ? "virtuell" : "nur Software"])
            : [...devices.serial.map((d) => [d.path, d.description]), ...devices.serial.filter((d) => d.stable_path).map((d) => [d.stable_path, "fester Name"]),
              ...devices.pps.map((d) => [d.path, d.description]), ...devices.ptp_clocks.map((d) => [d.path, d.description])];
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
  if (readonly) out.push(card("Einstellungen gesperrt", { class: "card-alert" }, emptyNote("`WEB_READONLY=true` ist gesetzt – hier lässt sich nur ansehen, nicht ändern.")));
  if (!schema.storage.persistent) {
    out.push(card("Achtung: Einstellungen sind nicht dauerhaft", { class: "card-alert" }, el("p", {}, rich(
      "`/var/lib/chrony` liegt auf keinem Volume. Gespeichertes geht verloren, wenn der Container **neu erstellt** wird (ein Neustart reicht nicht). "
      + "In der Compose-Datei: `volumes: [chrony-data:/var/lib/chrony]`."))));
  }
  out.push(card("Wie Einstellungen wirken", { help: "settings_source", class: "explain" }, el("p", {}, rich(
    "Werte aus diesem Dashboard haben **Vorrang** vor Umgebungsvariablen aus der Compose-Datei; die gelten als Startwerte. "
    + "Nach dem Speichern starten die Zeitdienste neu – das dauert wenige Sekunden, chrony behält seine Messhistorie. "
    + "Eine eigene `/config/chrony.conf` ersetzt die erzeugte Konfiguration komplett."))));

  for (const section of schema.sections) {
    const sectionFields = fields.filter((f) => f.section === section.key);
    if (!sectionFields.length) continue;
    const advancedCount = sectionFields.filter((f) => f.advanced).length;
    const showAdv = ui.showAdvanced[section.key];
    const visible = sectionFields.filter((f) => !f.advanced || showAdv || f.source === "gui" || f.source === "env");
    const toggle = advancedCount ? el("button", { type: "button", class: "link", text: showAdv ? "Weniger anzeigen" : `Erweitert (${advancedCount})`,
      "aria-expanded": showAdv ? "true" : "false", onclick: () => { ui.showAdvanced[section.key] = !showAdv; ctx.rerender(); } }) : null;
    const helpKey = { ntp: "minsources", lan: "island", nts: "nts", gps: "gps_value", ptp: "ptp_requirements", web: "settings_source" }[section.key];
    out.push(card(section.label, { id: `s-${section.key}`, help: helpKey, sub: section.description, actions: toggle },
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

  // Sichern & Wiederherstellen
  const fileInput = el("input", { type: "file", accept: "application/json,.json", hidden: true });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const result = await apiPost("/api/settings/import", { values: data.values || data });
      toast(result.reload_triggered ? "Importiert – Zeitdienste starten neu" : "Importiert");
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
      fileInput)));

  out.push(card("Nur per Umgebungsvariable", { sub: "Diese Werte steuern den Start selbst und lassen sich deshalb nur in der Compose-Datei setzen." },
    el("table", { class: "mini-table" }, el("tbody", {}, schema.env_only.map((e) => el("tr", {},
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
