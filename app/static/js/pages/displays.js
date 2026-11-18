// Reiter „Anzeigen“ (Uhr & Hardware): Link-Baukasten für die Vollbild-Uhr, benannte Profile, der Schalter
// „Vollbild-Uhr ohne Anmeldung“ und das On-Air/REC-Signal (POST /api/v1/clock/signal, Zustand aus /api/v1/time).
//
// Das Formular kommt aus dem Parameter-Schema der Uhr (clocklink.js, dieselbe Datei wie das Panel „Anpassen“ auf
// /clock). Die Vorschau öffnet sich mit fester Fenstergröße in einem neuen Tab – kein iframe, die Uhr bleibt
// mit frame-ancestors 'none' nicht einbettbar. Profile und clock_public werden über POST /api/settings gespeichert
// (Anmeldung, Pflicht-Kopf X-NTP-GUI); was gespeichert wird, prüft der Server (clockprofiles.py).
import { el, rich, apiGet, apiPost, copyText, fmtDate } from "../util.js";
import { card, infoButton, toast, emptyState, errorState } from "../ui.js";
import { t } from "../i18n.js";
import * as link from "../clocklink.js";
import * as kit from "../clockkit.js";

const ZONES = kit.supportedZones();

function settingValue(schema, key) {
  return (schema?.fields || []).find((field) => field.key === key)?.value;
}

/** Gespeicherte Profile (Objekt name → { title, params }) aus dem Einstellungs-Schema. */
export function storedProfiles(schema) {
  const value = settingValue(schema, "clock_profiles");
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

async function saveSetting(ctx, changes, done) {
  try {
    await apiPost("/api/settings", { changes });
    ctx.invalidate("settings");
    toast(done);
  } catch (error) {
    toast(t("pages.displays.save_failed", { message: error.message }), "warn");
  }
  ctx.refresh();
}

function builderCard(ctx, st, profiles, readonly) {
  const output = el("input", { type: "text", class: "mono link-output", readonly: true, id: "displays-link",
    "aria-label": t("pages.displays.link_label") });
  const href = () => link.clockHref(link.buildQuery(st.raw, ZONES));
  const update = () => { output.value = `${window.location.origin}${href()}`; };
  const form = link.buildForm({ values: st.raw, prefix: "dl", zones: ZONES, onChange: update });
  update();

  const choose = el("select", { id: "displays-load", "aria-label": t("pages.displays.load_label") },
    el("option", { value: "", text: t("pages.displays.load_placeholder") }),
    el("optgroup", { label: t("pages.displays.presets") },
      link.PRESETS.map((name) => el("option", { value: `preset:${name}`, text: t(`pages.displays.preset.${name}`) }))),
    Object.keys(profiles).length ? el("optgroup", { label: t("pages.displays.profiles") },
      Object.entries(profiles).map(([name, entry]) => el("option", { value: `profile:${name}`,
        text: entry.title ? `${name} – ${entry.title}` : name }))) : null);
  // Gewählte Vorlage bleibt nach dem Neuzeichnen sichtbar (sonst stünde wieder der Platzhalter da).
  choose.value = st.loaded || "";   // gelöschtes Profil: keine passende Option, dann der Platzhalter
  choose.addEventListener("change", async () => {
    const picked = choose.value;
    const [kind, name] = picked.split(":");
    if (!name) { st.loaded = ""; return; }
    try {
      const data = kind === "profile" ? { ...profiles[name], name }
        : await apiGet(`/api/v1/clock/profile?p=${encodeURIComponent(name)}`);
      st.raw = link.rawParams(data.params || {}, ZONES);
      if (kind === "profile") { st.name = name; st.title = data.title || ""; }
      st.loaded = picked;
      ctx.rerender();
    } catch (error) {
      toast(t("pages.displays.load_failed", { message: error.message }), "warn");
    }
  });

  const copy = el("button", { type: "button", class: "button primary", text: t("pages.displays.copy") });
  copy.addEventListener("click", async () => {
    if (await copyText(output.value)) toast(t("pages.displays.copied"));
    else { output.select(); toast(t("pages.displays.copy_failed"), "warn"); }
  });
  const clear = el("button", { type: "button", class: "button", text: t("pages.displays.clear") });
  clear.addEventListener("click", () => { st.raw = {}; st.loaded = ""; ctx.rerender(); });
  const previews = Object.keys(link.PREVIEW_SIZES).map((size) => {
    const box = link.PREVIEW_SIZES[size];
    const button = el("button", { type: "button", class: "button", dataset: { size },
      text: `${t(`pages.displays.size.${size}`)} ${box.width}×${box.height}` });
    button.addEventListener("click", () => window.open(href(), "_blank", link.previewFeatures(size)));
    return button;
  });

  return card(t("pages.displays.builder_title"), { help: "clock_page", sub: t("pages.displays.builder_sub"),
    id: "displays-builder" },
  el("div", { class: "toolbar link-load" }, el("label", { for: "displays-load", class: "toolbar-label",
    text: t("pages.displays.load") }), choose),
  form,
  el("div", { class: "link-result" }, output, el("div", { class: "button-row" }, copy, clear)),
  el("p", { class: "field-help", text: t("pages.displays.preview_note") }),
  el("div", { class: "button-row link-previews", role: "group", "aria-label": t("pages.displays.preview") }, previews),
  readonly ? null : saveRow(ctx, st, profiles));
}

function saveRow(ctx, st, profiles) {
  const name = el("input", { type: "text", id: "displays-name", class: "mono", maxlength: 32, autocomplete: "off",
    spellcheck: "false", pattern: "[a-z0-9-]{1,32}", placeholder: "regie", value: st.name || "" });
  const title = el("input", { type: "text", id: "displays-title", maxlength: link.TITLE_MAX, autocomplete: "off",
    placeholder: t("pages.displays.title_placeholder"), value: st.title || "" });
  name.addEventListener("input", () => { st.name = name.value.trim(); });
  title.addEventListener("input", () => { st.title = title.value; });
  const save = el("button", { type: "button", class: "button", id: "displays-save", text: t("pages.displays.save") });
  save.addEventListener("click", () => {
    const key = link.profileName(st.name || "");
    if (!key) { toast(t("pages.displays.name_invalid"), "warn"); name.focus(); return; }
    if (link.PRESETS.includes(key)) { toast(t("pages.displays.name_reserved", { name: key }), "warn"); name.focus(); return; }
    if (!(key in profiles) && Object.keys(profiles).length >= link.MAX_PROFILES) {
      toast(t("pages.displays.limit", { max: link.MAX_PROFILES }), "warn");
      return;
    }
    // Ohne das Prüfbild (test=sync): Es wirkt nur aus der Adresse, nie aus einem Profil.
    const params = link.profileParams(link.rawParams(link.buildQuery(st.raw, ZONES), ZONES));
    const next = { ...profiles, [key]: { title: (st.title || "").trim(), params } };
    saveSetting(ctx, { clock_profiles: next }, t("pages.displays.saved", { name: key }));
  });
  return el("div", { class: "link-save" },
    el("h3", { class: "link-save-title", text: t("pages.displays.save_title") }),
    el("div", { class: "link-save-row" },
      el("label", { for: "displays-name", class: "link-label" }, el("span", { text: t("pages.displays.name") })), name,
      el("label", { for: "displays-title", class: "link-label" }, el("span", { text: t("pages.displays.title") })), title,
      save),
    el("p", { class: "field-help", text: t("pages.displays.save_note") }));
}

function profilesCard(ctx, st, profiles, readonly) {
  const names = Object.keys(profiles);
  const rows = names.map((name) => {
    const entry = profiles[name] || {};
    const href = link.clockHref("", name);
    const load = el("button", { type: "button", class: "button", text: t("pages.displays.edit"),
      "aria-label": t("pages.displays.edit_label", { name }) });
    load.addEventListener("click", () => {
      st.raw = link.rawParams(entry.params || {}, ZONES);
      st.name = name;
      st.title = entry.title || "";
      st.loaded = `profile:${name}`;
      ctx.rerender();
      document.getElementById("displays-builder")?.scrollIntoView({ block: "start" });
    });
    const remove = readonly ? null : el("button", { type: "button", class: "button", text: t("pages.displays.delete"),
      "aria-label": t("pages.displays.delete_label", { name }) });
    remove?.addEventListener("click", () => {
      if (!window.confirm(t("pages.displays.delete_confirm", { name }))) return;
      const next = { ...profiles };
      delete next[name];
      saveSetting(ctx, { clock_profiles: next }, t("pages.displays.deleted", { name }));
    });
    return el("li", { class: "link-profile" },
      el("div", { class: "link-profile-head" }, el("strong", { class: "mono", text: name }),
        entry.title ? el("span", { text: entry.title }) : null),
      el("a", { href, target: "_blank", rel: "noopener", class: "mono", text: href }),
      el("div", { class: "button-row" }, load, remove));
  });
  return card(t("pages.displays.profiles_title"), { sub: t("pages.displays.profiles_sub", { count: names.length,
    max: link.MAX_PROFILES }) },
  rows.length ? el("ul", { class: "link-profiles" }, rows) : emptyState(t("pages.displays.profiles_empty")));
}

function publicCard(ctx, schema, readonly) {
  const on = Boolean(settingValue(schema, "clock_public"));
  // Aktionsknopf mit wechselnder Beschriftung (Erlauben/Abschalten), darum kein Umschalter-Zustand: Er steht im
  // Absatz darüber; beides zusammen läse ein Screenreader widersprüchlich.
  const button = el("button", { type: "button", class: on ? "button" : "button primary", disabled: readonly || null,
    id: "displays-public", "aria-describedby": "displays-public-state",
    text: on ? t("pages.displays.public_off") : t("pages.displays.public_on") });
  button.addEventListener("click", () => saveSetting(ctx, { clock_public: !on },
    on ? t("pages.displays.public_done_off") : t("pages.displays.public_done_on")));
  return card(t("pages.displays.public_title"), { help: "clock_public", id: "displays-public-card" },
    el("p", { class: "link-public-state", id: "displays-public-state", dataset: { state: on ? "on" : "off" },
      text: on ? t("pages.displays.public_state_on") : t("pages.displays.public_state_off") }),
    el("p", { class: "field-help", text: t("pages.displays.public_what") }),
    el("p", { class: "field-help", text: t("pages.displays.public_not") }),
    el("div", { class: "button-row" }, button));
}

/** Ablaufzeiten des Signals zur Auswahl in Sekunden (0: bleibt, bis du es ausschaltest). */
const SIGNAL_TTLS = [0, 300, 900, 1800, 3600, 7200, 14400];
const SIGNAL_REFRESH_MS = 5000;
let signalTimer = null;
/** Die gerade gezeichnete Karte: { st, node, paint }. Die Seite wird alle paar Sekunden neu gezeichnet – der Zeitgeber
 *  läuft dabei durch und schreibt in die jeweils aktuelle Karte. */
let signalLive = null;

function ttlText(seconds) {
  if (!seconds) return t("pages.displays.signal_ttl_none");
  return seconds < 3600 ? t("pages.displays.signal_ttl_min", { count: seconds / 60 })
    : t("pages.displays.signal_ttl_h", { count: seconds / 3600 });
}

/**
 * Zustand lesen und in st merken (signal: null heißt unbekannt); danach die aktuelle Karte neu beschriften. Wurde
 * inzwischen geschaltet (st.signalSeq zählt jeden Schaltbefehl beim Absenden und bei der Antwort), ist diese Antwort
 * womöglich älter als der Befehl und wird verworfen – sonst überschriebe sie den gerade gesetzten Zustand.
 */
async function signalLoad(st) {
  st.signalAt = Date.now();
  const seq = st.signalSeq || 0;
  const fresh = () => (st.signalSeq || 0) === seq;
  try {
    const data = await apiGet("/api/v1/time");
    if (!fresh()) return;
    st.signal = kit.signalState(data.signal);
    st.signalRev = typeof data.signal_rev === "string" ? data.signal_rev : "";
  } catch (error) {
    if (!fresh()) return;
    st.signal = null;
  }
  if (signalLive && signalLive.st === st) signalLive.paint();
}

/**
 * On-Air/REC-Signal: drei Knöpfe und eine Ablaufzeit. Der Zustand steht als Text im Absatz darüber (Knöpfe ohne
 * Umschalter-Zustand, wie bei „ohne Anmeldung“). Er kommt aus /api/v1/time, wird in st gemerkt und alle 5 s
 * nachgelesen. Beim Neuzeichnen der Seite steht sofort der gemerkte Zustand da; der Text wird nur gesetzt, wenn er
 * sich ändert (role=status: sonst läse ein Screenreader alle 5 s dieselbe Meldung). Wann das Signal von selbst
 * ausgeht, weiß die Seite nur aus der Antwort auf das eigene Setzen.
 */
function signalCard(ctx, st, readonly) {
  const now = el("p", { class: "link-public-state", id: "displays-signal-state", role: "status" });
  const name = (state) => t(`pages.displays.signal_name.${state}`);
  const paint = () => {
    const state = st.signal == null ? null : kit.signalState(st.signal);
    const until = state ? kit.signalExpiry({ state, rev: st.signalRev, until: st.signalUntil, now: Date.now() }) : null;
    const text = !state ? t("pages.displays.signal_unknown")
      : until ? t("pages.displays.signal_now_until", { state: name(state),
        time: fmtDate(until / 1000, { date: false, time: "short" }) })
        : t("pages.displays.signal_now", { state: name(state) });
    const shown = state && state !== "off" ? "on" : "off";
    if (now.dataset.state !== shown) now.dataset.state = shown;
    if (now.dataset.signal !== (state || "")) now.dataset.signal = state || "";
    if (now.textContent !== text) now.textContent = text;
  };
  paint();
  const ttl = el("select", { id: "displays-signal-ttl", disabled: readonly || null },
    SIGNAL_TTLS.map((seconds) => el("option", { value: String(seconds), text: ttlText(seconds) })));
  ttl.value = String(st.signalTtl || 0);
  ttl.addEventListener("change", () => { st.signalTtl = Number(ttl.value) || 0; });
  const send = async (state) => {
    const body = { state };
    if (state !== "off" && st.signalTtl) body.ttl = st.signalTtl;
    st.signalSeq = (st.signalSeq || 0) + 1;   // eine schon laufende Abfrage gilt ab jetzt als veraltet (signalLoad)
    try {
      const result = await apiPost("/api/v1/clock/signal", body);
      st.signalSeq += 1;
      st.signal = kit.signalState(result.signal);
      st.signalRev = typeof result.signal_rev === "string" ? result.signal_rev : "";
      st.signalUntil = result.expires_in ? { rev: st.signalRev, at: Date.now() + result.expires_in * 1000 } : null;
      st.signalAt = Date.now();
      paint();
      toast(result.expires_in ? t("pages.displays.signal_done_ttl", { state: name(st.signal), span: ttlText(result.expires_in) })
        : t("pages.displays.signal_done", { state: name(st.signal) }));
    } catch (error) {
      toast(t("pages.displays.signal_failed", { message: error.message }), "warn");
      signalLoad(st);   // ob der Befehl ankam, ist offen: den Zustand gleich neu lesen
    }
  };
  const buttons = kit.SIGNAL_STATES.filter((state) => state !== "off").concat("off").map((state) => {
    const button = el("button", { type: "button", class: state === "off" ? "button" : "button primary",
      disabled: readonly || null, dataset: { signal: state }, "aria-describedby": "displays-signal-state",
      text: state === "off" ? t("pages.displays.signal_off") : t(`pages.displays.signal_name.${state}`) });
    button.addEventListener("click", () => send(state));
    return button;
  });
  signalLive = { st, node: now, paint };
  // Nicht bei jedem Neuzeichnen neu lesen: nur beim ersten Mal und wenn der letzte Abruf 5 s oder länger her ist.
  if (!signalTimer || !st.signalAt || Date.now() - st.signalAt >= SIGNAL_REFRESH_MS) signalLoad(st);
  if (!signalTimer) {
    signalTimer = setInterval(() => {
      if (!signalLive || !signalLive.node.isConnected) { clearInterval(signalTimer); signalTimer = null; return; }
      if (!document.hidden) signalLoad(signalLive.st);
    }, SIGNAL_REFRESH_MS);
  }
  return card(t("pages.displays.signal_title"), { help: "clock_signal", sub: t("pages.displays.signal_sub"),
    id: "displays-signal-card" },
  now,
  el("div", { class: "toolbar link-signal" },
    el("label", { for: "displays-signal-ttl", class: "toolbar-label", text: t("pages.displays.signal_ttl") }), ttl),
  el("div", { class: "button-row", role: "group", "aria-label": t("pages.displays.signal_state") }, buttons),
  el("p", { class: "field-help", text: t("pages.displays.signal_note") }),
  el("p", { class: "field-help" }, rich(t("pages.displays.signal_api"))));
}

export function render(ctx) {
  const schema = ctx.data("settings", "/api/settings", 0);
  const head = el("div", { class: "toolbar section-head" },
    el("h2", { class: "section-title" }, `${t("nav.displays")} `, infoButton("clock_page", t("nav.displays"))),
    el("a", { class: "button", href: "/clock", target: "_blank", rel: "noopener", text: t("pages.displays.open") }));
  if (schema === undefined) {
    const failed = ctx.dataError("settings", "/api/settings");
    return [head, failed ? errorState(failed, t("nav.displays")) : card(t("nav.displays"), {}, emptyState(t("pages.displays.loading")))];
  }
  const ui = ctx.uiState;
  const st = ui.displays = ui.displays || { raw: {}, name: "", title: "", loaded: "", signalTtl: 0, signal: null, signalRev: "",
    signalUntil: null, signalAt: 0, signalSeq: 0 };
  const readonly = Boolean(schema.readonly || ctx.readonly);
  const profiles = storedProfiles(schema);
  return [
    head,
    builderCard(ctx, st, profiles, readonly),
    el("div", { class: "grid-2 grid-natural" }, profilesCard(ctx, st, profiles, readonly), publicCard(ctx, schema, readonly)),
    signalCard(ctx, st, readonly),
  ];
}
