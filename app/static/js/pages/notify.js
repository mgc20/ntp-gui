// Benachrichtigungen: Kanäle (Webhook, ntfy, Gotify, Apprise-API) mit Filtern, Test-Knopf und Zustellstand.
// Tokens kommen vom Server nie zurück – nur „gesetzt“ (secret_set).
import { el, rich, apiPost, fmtTime } from "../util.js";
import { card, info, badge, kv, emptyNote, toast, isPopoverOpen } from "../ui.js";

export const live = false; // Eingaben im Editor bleiben stehen; der Zustand wird gezielt nachgeladen

const STATE_BADGE = {
  ok: ["zugestellt", "good"], error: ["Fehler", "crit"], never: ["noch nichts gesendet", "muted"], off: ["aus", "muted"],
};
const LEVEL_TEXT = { info: "alles ab Info", warn: "ab Warnung", crit: "nur Kritisch" };
// Was die Felder „Thema“ und „Token“ je Kanalart bedeuten.
const TYPE_FIELDS = {
  webhook: { url: "z. B. http://homeassistant.lan:8123/api/webhook/ntp", topic: null,
    secret: "Signatur-Schlüssel (optional)", secretHelp: "Wenn gesetzt, trägt jede Anfrage den Header `X-NTPGUI-Signature: sha256=<HMAC>` – so prüft dein Empfänger, dass die Meldung wirklich von hier kommt." },
  ntfy: { url: "z. B. https://ntfy.sh oder http://ntfy.lan", topic: "Thema", topicHint: "z. B. zeitserver-8f3k",
    secret: "Zugangs-Token (optional)", secretHelp: "Nur nötig, wenn dein ntfy-Server das Thema schützt (`tk_…`). Auf ntfy.sh ohne Token gilt: Wer das Thema kennt, liest mit – nimm einen schwer zu ratenden Namen." },
  gotify: { url: "z. B. http://gotify.lan", topic: null, secret: "App-Token",
    secretHelp: "In Gotify unter **Apps** eine App anlegen und deren Token hier eintragen." },
  apprise: { url: "z. B. http://apprise:8000", topic: "Konfigurations-Schlüssel", topicHint: "z. B. ntp",
    secret: "Apprise-URLs (statt Schlüssel)", secretHelp: "Entweder einen in der Apprise-API gespeicherten **Schlüssel** angeben (empfohlen) oder hier direkt Apprise-URLs wie `mailto://…` oder `tgram://…` – die enthalten Zugangsdaten und werden deshalb wie ein Token behandelt." },
};

const REFRESH_SECONDS = 15;
let refreshTimer = null;

function fmtWhen(unix) {
  return typeof unix === "number" && Number.isFinite(unix)
    ? new Date(unix * 1000).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium" }) : "nie";
}

function blankDraft(cfg) {
  const d = cfg.defaults || {};
  return { id: null, name: "", type: "ntfy", url: "", topic: "", secret: "", clearSecret: false, secretSet: false,
    min_level: d.min_level || "warn", kinds: [], debounce_min: d.debounce_min ?? 15,
    rate_per_hour: d.rate_per_hour ?? 30, resolved: true, enabled: true };
}

function draftFrom(channel) {
  return { id: channel.id, name: channel.name, type: channel.type, url: channel.url, topic: channel.topic || "",
    secret: "", clearSecret: false, secretSet: channel.secret_set, min_level: channel.min_level,
    kinds: [...channel.kinds], debounce_min: channel.debounce_min, rate_per_hour: channel.rate_per_hour,
    resolved: channel.resolved, enabled: channel.enabled };
}

function switchControl(checked, label, onChange, disabled) {
  const input = el("input", { type: "checkbox", checked, disabled, role: "switch", "aria-label": label });
  const text = el("span", { class: "switch-text", text: checked ? "an" : "aus" });
  input.addEventListener("change", () => { text.textContent = input.checked ? "an" : "aus"; onChange(input.checked); });
  return el("label", { class: "switch" }, input, el("span", { class: "switch-track", "aria-hidden": "true" }), text);
}

function fieldBlock(label, help, control, note) {
  return el("div", { class: "field" },
    el("div", { class: "field-head" }, el("span", { class: "field-label" }, el("span", { text: label }), " ", info(help, label))),
    control,
    note ? el("p", { class: "field-help" }, rich(note)) : null);
}

function kindsText(channel, cfg) {
  if (!channel.kinds.length) return "alle Arten";
  const labels = Object.fromEntries((cfg.kinds || []).map((k) => [k.value, k.label]));
  return channel.kinds.map((k) => labels[k] || k).join(", ");
}

// --- Liste der Kanäle --------------------------------------------------------------
function channelCard(ctx, cfg, channel, disabled) {
  const ui = ctx.uiState;
  const st = channel.status || {};
  const [stateText, tone] = STATE_BADGE[st.state] || STATE_BADGE.never;
  const busy = ui.notifyBusy === channel.id;
  const test = async () => {
    ui.notifyBusy = channel.id;
    ctx.rerender();
    try {
      const result = await apiPost("/api/notify/test", { id: channel.id });
      if (result.ok) toast("Testnachricht zugestellt");
      else toast(`Testnachricht nicht zugestellt: ${result.error}`, "crit");
    } catch (error) { toast(error.message, "crit"); }
    ui.notifyBusy = null;
    ctx.invalidate("notify");
    ctx.rerender();
  };
  const remove = async () => {
    if (!window.confirm(`Kanal „${channel.name}“ löschen? Über ihn kommen dann keine Meldungen mehr.`)) return;
    try {
      await apiPost("/api/notify/channels/delete", { id: channel.id });
      toast("Gelöscht");
      if (ui.notifyDraft && ui.notifyDraft.id === channel.id) ui.notifyDraft = null;
      ctx.invalidate("notify");
      ctx.rerender();
    } catch (error) { toast(error.message, "crit"); }
  };
  const target = channel.type === "ntfy" || (channel.type === "apprise" && channel.topic)
    ? `${channel.url} · ${channel.topic}` : channel.url;
  return el("li", { class: "notify-channel" },
    el("div", { class: "notify-channel-head" },
      el("strong", { text: channel.name }), " ", badge(channel.type_label || channel.type, "info"), " ",
      el("span", { class: "mono muted", text: channel.id, title: "Kennung – so steht der Kanal im Ereignisprotokoll" }), " ",
      badge(stateText, tone), info("notify_status", "Zustellstand")),
    kv([
      ["Ziel", el("span", { class: "mono", text: target }), "notify_target"],
      ["Token", channel.secret_set ? "gesetzt (wird nie angezeigt)" : "keins", "notify_secret"],
      ["Filter", `${LEVEL_TEXT[channel.min_level] || channel.min_level} · ${kindsText(channel, cfg)}`, "notify_filter"],
      ["Entprellen", channel.debounce_min ? `gleiche Meldung höchstens alle ${channel.debounce_min} min` : "aus", "notify_debounce"],
      ["Höchstens", `${channel.rate_per_hour} je Stunde`, "notify_rate"],
      ["„Behoben“ melden", channel.resolved ? "ja, mit Dauer" : "nein", "notify_resolved"],
      ["Zuletzt zugestellt", fmtWhen(st.last_ok), "notify_status"],
      st.last_error ? ["Letzter Fehler", `${st.last_error} (${fmtWhen(st.last_error_t)})`, "notify_error"] : null,
      ["Gesendet / fehlgeschlagen / verworfen", `${st.sent || 0} / ${st.failed || 0} / ${st.dropped || 0}`, "notify_counts"],
      st.queued ? ["Wartet auf Versand", String(st.queued), "notify_retry"] : null,
    ]),
    el("div", { class: "button-row" },
      el("button", { type: "button", class: "button", text: busy ? "Sende …" : "Testnachricht senden", disabled: disabled || busy ? true : null, onclick: test }),
      el("button", { type: "button", class: "button", text: "Bearbeiten", disabled,
        onclick: () => { ui.notifyDraft = draftFrom(channel); ui.notifyErrors = null; ctx.rerender();
          ctx.afterRender(() => document.getElementById("notify-editor")?.scrollIntoView({ behavior: "smooth", block: "start" })); } }),
      el("button", { type: "button", class: "button", text: "Löschen", disabled, onclick: remove })));
}

// --- Editor --------------------------------------------------------------------------
function editorCard(ctx, cfg, disabled) {
  const ui = ctx.uiState;
  const d = ui.notifyDraft;
  const fields = TYPE_FIELDS[d.type] || TYPE_FIELDS.webhook;
  const set = (patch) => Object.assign(d, patch);

  const name = el("input", { type: "text", maxlength: 64, value: d.name, disabled, "aria-label": "Name", placeholder: "z. B. Handy (ntfy)" });
  name.addEventListener("input", () => set({ name: name.value }));
  const type = el("select", { disabled, "aria-label": "Art" }, (cfg.types || []).map((t) =>
    el("option", { value: t.value, selected: t.value === d.type ? true : null, text: t.label })));
  type.addEventListener("change", () => { set({ type: type.value }); ctx.rerender(); });
  const url = el("input", { type: "text", inputmode: "url", autocomplete: "off", value: d.url, disabled, "aria-label": "Adresse", placeholder: fields.url });
  url.addEventListener("input", () => set({ url: url.value.trim() }));
  const topic = fields.topic ? el("input", { type: "text", maxlength: 64, value: d.topic, disabled, "aria-label": fields.topic, placeholder: fields.topicHint }) : null;
  topic?.addEventListener("input", () => set({ topic: topic.value.trim() }));
  const secret = el("input", { type: "password", autocomplete: "new-password", value: d.secret, disabled, "aria-label": fields.secret,
    placeholder: d.secretSet ? "gesetzt – leer lassen, um es zu behalten" : "" });
  secret.addEventListener("input", () => set({ secret: secret.value }));
  const clear = d.secretSet ? el("label", { class: "notify-inline" },
    el("input", { type: "checkbox", checked: d.clearSecret, disabled, onchange: (e) => set({ clearSecret: e.target.checked }) }),
    el("span", { text: "gespeichertes Token entfernen" })) : null;
  const level = el("select", { disabled, "aria-label": "Mindeststufe" }, (cfg.levels || []).map((lv) =>
    el("option", { value: lv.value, selected: lv.value === d.min_level ? true : null, text: LEVEL_TEXT[lv.value] || lv.label })));
  level.addEventListener("change", () => set({ min_level: level.value }));
  const kinds = el("div", { class: "notify-kinds", role: "group", "aria-label": "Arten" },
    (cfg.kinds || []).map((k) => {
      const on = d.kinds.includes(k.value);
      return el("button", { type: "button", class: "chip", "aria-pressed": on ? "true" : "false", text: k.label, disabled,
        "data-focus-key": `kind:${k.value}`,
        onclick: (e) => {
          d.kinds = on ? d.kinds.filter((x) => x !== k.value) : [...d.kinds, k.value];
          e.currentTarget.setAttribute("aria-pressed", on ? "false" : "true");
          ctx.rerender();
        } });
    }));
  const number = (key, min, max, label, unit) => {
    const input = el("input", { type: "number", min, max, step: 1, value: d[key], disabled, "aria-label": label, inputmode: "numeric" });
    input.addEventListener("input", () => set({ [key]: input.value === "" ? "" : Number.parseInt(input.value, 10) }));
    return el("div", { class: "input-wrap" }, input, el("span", { class: "unit-suffix", text: unit }));
  };
  const errors = ui.notifyErrors;

  const save = async () => {
    const body = { name: d.name, type: d.type, url: d.url, topic: d.topic, min_level: d.min_level, kinds: d.kinds,
      debounce_min: d.debounce_min, rate_per_hour: d.rate_per_hour, resolved: d.resolved, enabled: d.enabled };
    if (d.id) body.id = d.id;
    if (d.clearSecret) body.secret = "";
    else if (d.secret) body.secret = d.secret;
    try {
      await apiPost("/api/notify/channels", body);
      toast(d.id ? "Gespeichert" : "Kanal angelegt – schick am besten gleich eine Testnachricht");
      ui.notifyDraft = null;
      ui.notifyErrors = null;
      ctx.invalidate("notify");
      ctx.rerender();
    } catch (error) {
      ui.notifyErrors = error.message;
      toast(error.message, "crit");
      ctx.rerender();
    }
  };

  return card(d.id ? `Kanal „${d.name}“ bearbeiten` : "Neuer Kanal", { id: "notify-editor", help: "notify_channel" },
    el("div", { class: "fields" },
      fieldBlock("Name", "notify_channel", name, "Nur für dich – steht in der Liste und in lokalen Ereignissen, nie in der Nachricht."),
      fieldBlock("Art", d.type === "webhook" ? "notify_webhook" : d.type === "apprise" ? "notify_apprise" : "notify_types", type, d.type === "apprise"
        ? "Apprise-API läuft als eigener Container neben ntp-gui und leitet an E-Mail, Telegram, Matrix, Signal und über 100 weitere Dienste weiter (Compose-Beispiel in der Hilfe)."
        : null),
      fieldBlock("Adresse", "notify_target", url, "Nur `http://` oder `https://`. Weiterleitungen werden nicht befolgt – trag die endgültige Adresse ein."),
      topic ? fieldBlock(fields.topic, "notify_target", topic, null) : null,
      fieldBlock(fields.secret, "notify_secret", el("div", { class: "notify-secret" }, secret, clear), fields.secretHelp),
      fieldBlock("Ab Stufe", "notify_filter", level, null),
      fieldBlock("Arten", "notify_filter", kinds, d.kinds.length ? "Nur die markierten Arten." : "Keine markiert = **alle** Arten (auch künftige)."),
      fieldBlock("Entprellen", "notify_debounce", number("debounce_min", 0, 1440, "Entprellen in Minuten", "min"),
        "Gleiche Meldung (gleiche Art, gleiches Gerät/gleicher Dienst) höchstens so oft. 0 = aus."),
      fieldBlock("Höchstens je Stunde", "notify_rate", number("rate_per_hour", 1, 600, "Höchstens je Stunde", "Nachrichten"), null),
      fieldBlock("„Behoben“ melden", "notify_resolved", switchControl(d.resolved, "Behoben melden", (v) => set({ resolved: v }), disabled), null),
      fieldBlock("Aktiv", "notify_enabled", switchControl(d.enabled, "Kanal aktiv", (v) => set({ enabled: v }), disabled), null)),
    errors ? el("p", { class: "field-error", role: "alert", text: errors }) : null,
    el("div", { class: "button-row" },
      el("button", { type: "button", class: "button primary", text: d.id ? "Speichern" : "Kanal anlegen", disabled, onclick: save }),
      el("button", { type: "button", class: "button", text: "Abbrechen", onclick: () => { ui.notifyDraft = null; ui.notifyErrors = null; ctx.rerender(); } })));
}

// Zustand alle 15 s nachladen – aber nicht, solange jemand im Editor tippt oder eine Erklärung offen ist.
function watch(ctx, box) {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    if (!box.isConnected) { clearInterval(refreshTimer); refreshTimer = null; return; }
    if (document.hidden || isPopoverOpen() || ctx.uiState.notifyDraft || ctx.uiState.notifyBusy) return;
    ctx.invalidate("notify");
    ctx.data("notify", "/api/notify", 0);
  }, REFRESH_SECONDS * 1000);
}

export function render(ctx) {
  const cfg = ctx.data("notify", "/api/notify", 0);
  const ui = ctx.uiState;
  const disabled = ctx.readonly ? true : null;
  const out = [];
  out.push(card("Benachrichtigungen", { help: "notify", class: "explain",
    sub: "Meldet Probleme dorthin, wo du sie siehst: aufs Handy (ntfy, Gotify), in Home Assistant (Webhook) oder über Apprise per E-Mail, Telegram, Matrix …" },
  el("p", {}, rich("Jede Nachricht läuft durch denselben **Datenschutzfilter** wie das Diagnosepaket: keine Koordinaten, keine öffentlichen IP-Adressen, keine eigenen Hostnamen. "
    + "Gleiche Meldungen werden **entprellt**, und wenn ein Problem vorbei ist, kommt „behoben“ mit der Dauer. Ohne Kanal verlässt nichts den Server."))));
  if (cfg === undefined) {
    out.push(card("Kanäle", {}, emptyNote("Wird geladen …")));
    return out;
  }
  if (!cfg) {
    out.push(card("Kanäle", { class: "card-alert" }, emptyNote("Konnte die Kanäle nicht laden – dafür braucht es das Verwaltungsrecht.")));
    return out;
  }
  if (ctx.readonly) out.push(card("Gesperrt", { class: "card-alert" }, emptyNote("`WEB_READONLY=true` ist gesetzt – Kanäle lassen sich nur ansehen.")));
  const channels = cfg.channels || [];
  const list = channels.length
    ? el("ul", { class: "notify-list" }, channels.map((c) => channelCard(ctx, cfg, c, disabled)))
    : emptyNote("Noch kein Kanal angelegt. Am schnellsten geht **ntfy**: App aufs Handy, ein Thema ausdenken, hier eintragen, Testnachricht senden.");
  const full = channels.length >= ((cfg.limits || {}).channels || 10);
  out.push(card("Kanäle", { help: "notify_channel",
    actions: ui.notifyDraft ? null : el("button", { type: "button", class: "button primary", text: "+ Kanal", disabled: disabled || full ? true : null,
      onclick: () => { ui.notifyDraft = blankDraft(cfg); ui.notifyErrors = null; ctx.rerender(); } }) }, list));
  ctx.afterRender(() => watch(ctx, list));
  if (ui.notifyDraft) out.push(editorCard(ctx, cfg, disabled));
  out.push(card("Link zum Dashboard", { help: "notify_link" },
    kv([["Adresse", cfg.dashboard_url ? el("span", { class: "mono", text: cfg.dashboard_url }) : "nicht gesetzt – Nachrichten ohne Link", "notify_link"]]),
    el("p", { class: "field-help" }, rich("Einstellen unter **Einstellungen → Dashboard → Erweitert** (`NOTIFY_DASHBOARD_URL`). "),
      el("a", { href: "#/einstellungen?s=web", text: "Zu den Einstellungen →" }))));
  out.push(el("p", { class: "field-help notify-foot" }, `Stand ${fmtTime(Date.now() / 1000)} · Wiederholung nach 30 s, 2 min und 10 min, danach verworfen (steht dann im Ereignisprotokoll).`));
  return out;
}
