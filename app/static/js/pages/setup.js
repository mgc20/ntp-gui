// Willkommens-Assistent „In 3 Minuten fertig“ (1.6, T3) – Reiter „Einrichtung“ unter System.
//
// Fünf Schritte als Unterpfade (#/system/einrichtung/<schritt>): Prüfen · Zeitquellen · GPS · Clients ·
// Benachrichtigung. Jeder Schritt ist freiwillig: „Weiter“ und „Zurück“ schreiben nichts. Geschrieben wird nur
// mit „Übernehmen“ – und zwar über denselben Weg wie die Einstellungen (Vorschau POST /api/settings/preview,
// Speichern POST /api/settings mit derselben Prüfung) bzw. die Benachrichtigungen (Kanal anlegen, Testnachricht).
// „Fertig“ merkt sich der Server (POST /api/setup, setup_done), „Nicht mehr zeigen“ schließt zusätzlich die
// Checkliste der Übersicht (action „never“); „Später“ schreibt nichts.
// Keine Verbindung nach außen: Die Vorlagen sind die feste Liste PRESETS aus den Einstellungen.
import { el, rich, apiGet, apiPost } from "../util.js";
import { card, badge, kv, emptyState, errorState, toast, copyButton } from "../ui.js";
import { t } from "../i18n.js";
import { route, SETUP_STEPS, setupHref } from "../routes.js";
import { PRESETS, withPreset, previewFile } from "./settings.js";
import { serverAddress, usableAddress, usableHostname, clientSnippets, snippet, IP_PLACEHOLDER } from "./clients.js";
import { blankDraft, channelCard, editorCard } from "./notify.js";

export const live = false; // Entwürfe und offene Vorschau bleiben stehen; neu gezeichnet wird gezielt

/** Schritte in ihrer Reihenfolge (Unterpfad, Katalogschlüssel) – die Tabelle steht in routes.js. */
export const STEPS = SETUP_STEPS;

/** Index des Schritts zu einem Unterpfad – unbekannt oder leer: erster Schritt. */
export function stepIndex(sub) {
  const index = STEPS.findIndex((s) => s.id === String(sub || "").toLowerCase());
  return index < 0 ? 0 : index;
}

export const stepHref = setupHref;

/** Vorlagen des Assistenten: nur die öffentlichen NTS-Server (PTB, Cloudflare, Netnod …). */
export function ntsPresets(presets = PRESETS) {
  return presets.filter(([, entries]) => entries.length && entries.every(([, , nts]) => nts));
}

/** Stimmen zwei Quellenlisten überein (Typ, Name, NTS, bevorzugen, nur beobachten, Optionen)? */
export function sameSources(a, b) {
  const norm = (list) => JSON.stringify((list || []).map((s) => [s.type, s.host, Boolean(s.nts), Boolean(s.prefer),
    Boolean(s.noselect), s.options || ""]));
  return norm(a) === norm(b);
}

const STATUS_TONE = { ok: "good", problem: "crit", info: "info" };

function setupState(ctx) {
  const st = ctx.uiState.setup = ctx.uiState.setup || {};
  st.preview = st.preview || {};
  return st;
}

// Verlassen mit ungespeichertem Entwurf (Zeitquellen oder GPS): wie bei den Einstellungen nachfragen.
export function leaveMessage(uiState) {
  const st = uiState?.setup;
  return st && (st.sources || st.gps !== undefined) ? t("setup.leave") : null;
}

export function leave(uiState) {
  if (uiState?.setup) Object.assign(uiState.setup, { sources: null, gps: undefined, preview: {} });
}

// --- Speichern über den Weg der Einstellungen -----------------------------------------------------------
async function preview(ctx, which, changes) {
  const st = setupState(ctx);
  st.preview[which] = { loading: true };
  ctx.rerender();
  try {
    st.preview[which] = { result: await apiPost("/api/settings/preview", { changes }) };
  } catch (error) {
    st.preview[which] = { error: error.message };
  }
  ctx.rerender();
}

async function apply(ctx, which, changes) {
  const st = setupState(ctx);
  if (ctx.status?.holdover_active && !window.confirm(t("setup.holdover_confirm"))) return;
  try {
    const result = await apiPost("/api/settings", { changes });
    toast(result.restart ? (result.reload_triggered ? t("setup.saved_restart") : result.reload_note) : t("setup.saved"));
    for (const note of result.warnings || []) toast(note, "warn");
    if (result.reload_triggered) ctx.watchReload();
    if (which === "sources") st.sources = null;
    else st.gps = undefined;
    delete st.preview[which];
    ctx.invalidate("settings");
    ctx.invalidate("setup");
    ctx.rerender();
  } catch (error) {
    st.preview[which] = { error: error.message };
    toast(error.message, "crit");
    ctx.rerender();
  }
}

function previewBox(ctx, which) {
  const shown = setupState(ctx).preview[which];
  if (!shown) return null;
  if (shown.loading) return emptyState(t("setup.preview_loading"));
  if (shown.error) return el("p", { class: "field-error", role: "alert", text: t("setup.preview_error", { message: shown.error }) });
  const files = Array.isArray(shown.result?.files) ? shown.result.files : [];
  const touched = files.some((file) => file.status === "changed" || file.status === "new");
  return el("div", { class: "setup-preview", "aria-live": "polite" },
    el("h3", { class: "mini-head", text: t("setup.preview_title") }),
    touched ? null : el("p", { class: "preview-none", text: t("setup.preview_none") }),
    files.map(previewFile));
}

function applyRow(ctx, which, changes, canWrite) {
  const disabled = canWrite ? null : true;
  return el("div", { class: "button-row setup-apply" },
    el("button", { type: "button", class: "button", text: t("setup.preview"), onclick: () => preview(ctx, which, changes) }),
    el("button", { type: "button", class: "button primary", text: t("setup.apply"), disabled, onclick: () => apply(ctx, which, changes) }),
    el("button", { type: "button", class: "button", text: t("setup.discard"), onclick: () => {
      leave(ctx.uiState);
      setupState(ctx).refocus = which; // die Zeile verschwindet – Fokus zurück zur Auswahl
      ctx.rerender();
    } }));
}

// --- (a) Prüfen ------------------------------------------------------------------------------------------
function checkItem(check) {
  const tone = STATUS_TONE[check.status] || "muted";
  return el("li", { class: "setup-check", "data-tone": tone },
    el("div", { class: "setup-check-head" },
      badge(t(`setup.status.${check.status}`), tone), " ", el("strong", { text: check.title })),
    check.text ? el("p", { class: "setup-check-text", text: check.text }) : null,
    check.status === "problem" && check.remedy ? el("p", { class: "setup-remedy" },
      el("strong", { text: `${t("setup.check.remedy")} ` }), check.remedy) : null,
    check.status === "problem" && check.fix ? snippet(t("setup.check.compose"), check.fix) : null);
}

function stepCheck(ctx, data) {
  const checks = Array.isArray(data.checks) ? data.checks : [];
  const problems = checks.filter((c) => c.status === "problem").length;
  const recheck = async () => {
    setupState(ctx).rechecking = true;
    ctx.rerender();
    try { await apiGet("/api/hardware?refresh=1"); } catch (error) { toast(error.message, "crit"); }
    setupState(ctx).rechecking = false;
    ctx.invalidate("setup");
    ctx.rerender();
  };
  return [
    card(t("setup.check.card"), { help: "hw_check",
      sub: problems ? t("setup.check.problems", { count: problems, n: problems }) : t("setup.check.all_ok"),
      actions: el("button", { type: "button", class: "button", text: setupState(ctx).rechecking ? t("setup.check.running") : t("setup.check.again"),
        disabled: setupState(ctx).rechecking ? true : null, onclick: recheck }) },
    el("ul", { class: "setup-checks" }, checks.map(checkItem)),
    el("p", { class: "field-help setup-more" }, el("a", { href: route("hardware"), text: t("setup.check.full") }))),
  ];
}

// --- (b) Zeitquellen -----------------------------------------------------------------------------------
function sourceList(list, before) {
  if (!list.length) return emptyState(t("setup.sources.none"));
  const known = new Set((before || []).map((s) => s.host));
  return el("ul", { class: "setup-sources" }, list.map((s) => el("li", {},
    el("span", { class: "mono", text: s.host }), " ",
    badge(s.type, "muted"), s.nts ? badge("NTS", "good") : null,
    before && !known.has(s.host) ? badge(t("setup.sources.new"), "info") : null)));
}

function stepSources(ctx, data, schema, canWrite) {
  const st = setupState(ctx);
  const field = (schema?.fields || []).find((f) => f.key === "ntp_sources");
  if (!field) return [card(t("setup.sources.card"), {}, schema === undefined ? emptyState(t("setup.loading")) : errorState(null, t("setup.sources.what")))];
  const current = Array.isArray(field.value) ? field.value : [];
  const draft = st.sources || null;
  const shown = draft || current;
  const presets = ntsPresets();
  const chips = el("div", { class: "setup-presets", role: "group", "aria-label": t("setup.sources.templates"), tabindex: "-1" },
    presets.map(([label, entries]) => {
      const present = entries.every(([, host]) => shown.some((s) => s.host === host));
      return el("button", { type: "button", class: "chip", "aria-pressed": present ? "true" : "false", text: label,
        disabled: present ? true : null, "data-focus-key": `preset:${label}`,
        onclick: () => {
          st.sources = withPreset(shown, entries);
          delete st.preview.sources;
          st.refocus = "sources"; // der Chip ist danach gesperrt – Fokus auf den nächsten freien
          ctx.rerender();
        } });
    }));
  const changed = draft && !sameSources(draft, current);
  return [
    card(t("setup.sources.card"), { help: "nts", sub: t("setup.sources.sub") },
      el("h3", { id: "setup-sources-head", class: "mini-head", tabindex: "-1", text: t(changed ? "setup.sources.after" : "setup.sources.now") }),
      sourceList(shown, changed ? current : null),
      field.source === "env" ? el("p", { class: "field-help", text: t("setup.sources.env") }) : null,
      el("h3", { class: "mini-head", text: t("setup.sources.templates") }),
      chips,
      el("p", { class: "field-help", text: t("setup.sources.keep") }),
      changed ? applyRow(ctx, "sources", { ntp_sources: draft }, canWrite) : null,
      changed ? previewBox(ctx, "sources") : null,
      el("p", { class: "field-help setup-more" }, el("a", { href: route("settings", "", "s=quellen"), text: t("setup.sources.more") }))),
  ];
}

// --- (c) GPS ----------------------------------------------------------------------------------------------
function stepGps(ctx, data, canWrite) {
  const st = setupState(ctx);
  const gps = data.gps || {};
  const enabled = Boolean(gps.enabled);
  const wanted = st.gps === undefined ? enabled : st.gps;
  const receiver = gps.receiver || null;
  const choose = (value) => { st.gps = value === enabled ? undefined : value; delete st.preview.gps; ctx.rerender(); };
  const option = (value, label) => el("label", { class: "setup-choice" },
    el("input", { type: "radio", name: "setup-gps", value: value ? "ja" : "nein", checked: wanted === value,
      onchange: () => choose(value) }),
    el("span", { text: label }));
  const changes = { gps_enable: wanted };
  if (wanted && receiver?.device && receiver.device !== gps.device) changes.gps_device = receiver.device;
  return [
    card(t("setup.gps.card"), { help: "gps_role" },
      el("p", { class: "setup-found" }, receiver
        ? [badge(t("setup.gps.found"), "good"), " ", el("span", { text: receiver.label })]
        : [badge(t("setup.gps.not_found"), "muted"), " ", el("span", { text: t("setup.gps.optional") })]),
      el("p", {}, rich(t("setup.gps.honest"))),
      gps.pps ? el("p", { class: "field-help", text: t("setup.gps.with_pps") }) : null,
      el("fieldset", { class: "setup-choices" },
        el("legend", { text: t("setup.gps.question") }),
        option(true, t("setup.gps.yes")), option(false, t("setup.gps.no"))),
      wanted && !receiver ? el("p", { class: "field-help", text: t("setup.gps.no_receiver") }) : null,
      st.gps !== undefined ? applyRow(ctx, "gps", changes, canWrite) : null,
      st.gps !== undefined ? previewBox(ctx, "gps") : null,
      el("p", { class: "field-help setup-more" },
        el("a", { href: "#/hilfe?t=pps", text: t("setup.gps.pps_link") }), " · ",
        el("a", { href: route("gps"), text: t("setup.gps.page_link") }))),
  ];
}

// Fokus nach „Verwerfen“ oder einem Vorlagen-Chip: Das fokussierte Element ist danach weg oder gesperrt.
function refocus(which) {
  if (which === "gps") {
    document.querySelector('.setup-choices input:checked')?.focus();
    return;
  }
  const free = document.querySelector(".setup-presets .chip:not([disabled])");
  (free || document.querySelector(".setup-presets") || document.getElementById("setup-sources-head"))?.focus();
}

// --- (d) Clients ---------------------------------------------------------------------------------------
function copyRow(label, value) {
  const code = el("code", { class: "mono", text: value });
  return [label, el("span", { class: "setup-copy" }, code, copyButton(value, code))];
}

function stepClients(ctx) {
  const status = ctx.status || {};
  const ip = serverAddress(status);
  const host = usableHostname(status.system?.hostname) ? String(status.system.hostname) : "";
  const browserHost = window.location.hostname;
  const rows = [
    ip ? copyRow(t("setup.clients.address"), ip) : [t("setup.clients.address"), t("setup.clients.unknown")],
    host ? copyRow(t("setup.clients.hostname"), host) : null,
    usableAddress(browserHost) && browserHost !== ip && browserHost !== host ? copyRow(t("setup.clients.browser"), browserHost) : null,
  ];
  return [
    card(t("setup.clients.card"), { help: "dhcp42", sub: t("setup.clients.sub") },
      kv(rows),
      el("h3", { class: "mini-head", text: t("setup.clients.devices") }),
      el("div", { class: "snippets" }, clientSnippets(ip || IP_PLACEHOLDER)),
      el("h3", { class: "mini-head", text: t("setup.clients.guides") }),
      el("ul", { class: "setup-links" },
        el("li", {}, el("a", { href: route("clients"), text: t("setup.clients.router") })),
        el("li", {}, el("a", { href: "#/hilfe?t=dhcp42", text: t("setup.clients.option42") })),
        el("li", {}, el("a", { href: "#/hilfe?t=enforce", text: t("setup.clients.enforce") })),
        el("li", {}, rich(t("setup.clients.smarthome"))))),
  ];
}

// --- (e) Benachrichtigung --------------------------------------------------------------------------------
function stepNotify(ctx, canWrite) {
  const cfg = ctx.data("notify", "/api/notify", 0);
  const failed = cfg === undefined ? ctx.dataError?.("notify", "/api/notify") : null;
  const ui = ctx.uiState;
  const disabled = canWrite ? null : true;
  const intro = card(t("setup.notify.card"), { help: "notify", sub: t("setup.notify.sub") },
    failed ? emptyState(failed.status === 401 || failed.status === 403 ? t("setup.notify.no_right") : t("setup.notify.failed"))
      : cfg === undefined ? emptyState(t("setup.loading"))
        : (cfg.channels || []).length
          ? el("ul", { class: "notify-list" }, cfg.channels.map((c) => channelCard(ctx, cfg, c, disabled)))
          : emptyState(t("setup.notify.none")),
    cfg && !ui.notifyDraft ? el("div", { class: "button-row" },
      el("button", { type: "button", class: "button", text: t("setup.notify.add"), disabled,
        onclick: () => { ui.notifyDraft = blankDraft(cfg); ui.notifyErrors = null; ctx.rerender(); } })) : null);
  return [intro, cfg && ui.notifyDraft ? editorCard(ctx, cfg, disabled) : null];
}

// --- Rahmen: Schrittanzeige, Überschrift, Weiter/Zurück ------------------------------------------------
async function finish(ctx, data, action = "done") {
  if (data.can_write && !data.done) {
    try {
      await apiPost("/api/setup", { action });
      toast(t(action === "never" ? "setup.hidden" : "setup.finished"));
    } catch (error) {
      toast(error.message, "crit");
      return;
    }
  }
  ctx.invalidate("setup");
  window.location.hash = "#/";
}

function stepNav(ctx, data, index) {
  const last = index === STEPS.length - 1;
  return el("nav", { class: "setup-nav", "aria-label": t("setup.nav_label") },
    index > 0 ? el("a", { class: "button", href: stepHref(index - 1), text: t("setup.back") }) : el("span"),
    el("span", { class: "setup-nav-end" },
      last ? el("a", { class: "button", href: "#/", text: t("setup.later") }) : null,
      last ? el("button", { type: "button", class: "button primary", text: t("setup.finish"), onclick: () => finish(ctx, data) })
        : el("a", { class: "button primary", href: stepHref(index + 1), text: t("setup.next") })));
}

export function render(ctx) {
  const data = ctx.data("setup", "/api/setup", 30);
  const schema = ctx.data("settings", "/api/settings", 0);
  const st = setupState(ctx);
  const index = stepIndex(ctx.subpath);
  const step = STEPS[index];
  if (!data) {
    const failed = ctx.dataError?.("setup", "/api/setup");
    return [card(t("setup.title"), {}, failed ? errorState(failed, t("setup.what")) : emptyState(t("setup.loading")))];
  }
  const canWrite = Boolean(data.can_write) && !ctx.readonly;
  // Fokus auf die Überschrift, sobald sich der Schritt ändert (Tastatur und Screenreader landen beim neuen Inhalt).
  if (st.shownStep !== step.id) {
    st.shownStep = step.id;
    if (st.rendered) ctx.afterRender(() => document.getElementById("setup-step-title")?.focus());
  }
  st.rendered = true;
  if (st.refocus) {
    const which = st.refocus;
    st.refocus = null;
    ctx.afterRender(() => refocus(which));
  }
  const steps = el("ol", { class: "setup-steps", "aria-label": t("setup.steps_label") }, STEPS.map((s, i) => el("li", {},
    el("a", { href: stepHref(i), class: i === index ? "is-current" : null, "aria-current": i === index ? "step" : null },
      el("span", { class: "setup-step-no", "aria-hidden": "true", text: String(i + 1) }),
      el("span", { class: "setup-step-name", text: t(`setup.steps.${s.key}`) })))));
  const later = el("a", { class: "button", href: "#/", text: t("setup.later") });
  const never = canWrite && !data.done
    ? el("button", { type: "button", class: "button", text: t("setup.never"), onclick: () => finish(ctx, data, "never") }) : null;
  const head = el("section", { class: "card setup-head", "aria-labelledby": "setup-step-title" },
    el("div", { class: "setup-head-top" },
      el("p", { class: "setup-intro", text: data.done ? t("setup.intro_done") : t("setup.intro") }),
      el("div", { class: "card-actions" }, later, never)),
    steps,
    el("h2", { id: "setup-step-title", class: "setup-title", tabindex: "-1" },
      el("span", { class: "setup-count", text: `${t("setup.count", { n: index + 1, total: STEPS.length })} · ` }),
      t(`setup.steps.${step.key}`)),
    el("p", { class: "card-sub", text: t(`setup.lead.${step.key}`) }),
    canWrite ? null : el("p", { class: "empty-note", role: "note", text: t("setup.readonly") }));
  let body;
  if (step.key === "check") body = stepCheck(ctx, data);
  else if (step.key === "sources") body = stepSources(ctx, data, schema, canWrite);
  else if (step.key === "gps") body = stepGps(ctx, data, canWrite);
  else if (step.key === "clients") body = stepClients(ctx);
  else body = stepNotify(ctx, canWrite);
  return [head, ...body, stepNav(ctx, data, index)];
}
