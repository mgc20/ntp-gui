// Geführte Fehlersuche „Mein Gerät bekommt keine Zeit“ (1.11): Adresse eingeben, der Server geht eine feste
// Prüfliste durch (GET /api/clients/troubleshoot, rein lesend) und nennt genau einen Befund mit dem nächsten
// Schritt. Nachmessen nur über das vorhandene „Aktiv nachmessen“ auf der Geräteseite.
import { t as tr } from "../i18n.js";
import { el, apiGet, rich } from "../util.js";
import { card, badge, infoButton } from "../ui.js";
import { clientHref } from "./clientdetail.js";

const LEVEL = { ok: "good", warn: "warn", fail: "crit" };
const ACTION_HREF = { settings: "#/system/einstellungen", diagnose: "#/system/diagnose", sources: "#/quellen" };

// checked: die Adresse, zu der result gehört – in der Schreibweise des Servers (Kurzform, ohne ::ffff:).
let state = { input: "", checked: "", busy: false, result: null, error: null, open: true };

// Grobe Vorprüfung im Browser – die strenge Prüfung macht der Server.
export function looksLikeIp(text) {
  const a = String(text || "").trim().replace(/^\[|\]$/g, "");
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(a)) return a.split(".").every((n) => Number(n) <= 255);
  return a.includes(":") && /^[0-9a-f:.]+$/i.test(a) && a.length <= 45;
}

export async function run(ctx, value) {
  const ip = String(value || "").trim();
  state.input = ip;
  if (!looksLikeIp(ip)) {
    state = { ...state, result: null, error: tr("pages.clients.ts.invalid") };
    ctx.rerender();
    return;
  }
  state = { ...state, busy: true, error: null };
  ctx.rerender();
  try {
    state.result = await apiGet(`/api/clients/troubleshoot?ip=${encodeURIComponent(ip)}`);
    state.open = (state.result.verdict || {}).level !== "ok";
    // Der Server schreibt die Adresse um („FD00:0::1“ → „fd00::1“, „::ffff:192.168.1.10“ → „192.168.1.10“).
    // Das Feld zeigt danach die geprüfte Schreibweise – solange in der Zwischenzeit nichts Neues getippt wurde.
    state.checked = String(state.result.address || ip);
    if (state.input === ip) state.input = state.checked;
  } catch (error) {
    state.result = null;
    state.checked = "";
    state.error = error.message;
  }
  state.busy = false;
  ctx.rerender();
}

function statusBadge(status) {
  const key = { ok: "ok", warn: "warn", fail: "fail", info: "info", skip: "skip" }[status] || "info";
  return badge(tr(`pages.clients.ts.status.${key}`), LEVEL[status] || "muted");
}

function checkRow(check) {
  return el("li", { class: "enforce-row", "data-level": LEVEL[check.status] || null, "data-key": check.key },
    el("div", { class: "enforce-row-head" }, el("strong", { text: check.title }), statusBadge(check.status)),
    el("p", { text: check.text || "" }));
}

function resultView(ctx, result, snippets) {
  const v = result.verdict || {};
  const tone = v.level === "ok" ? "good" : v.level;
  const action = ACTION_HREF[v.action];
  const showDetail = result.known;
  return el("div", { class: "ts-result" },
    el("div", { class: "verdict", "data-tone": tone, role: "status" },
      el("div", { class: "verdict-label" }, el("span", { text: tr("pages.clients.ts.verdict") }),
        infoButton("troubleshoot_verdict")),
      el("p", {}, el("strong", { text: `${v.title}: ` }), v.text || ""),
      v.next ? el("p", {}, el("strong", { text: `${tr("pages.clients.ts.next")}: ` }), rich(v.next)) : null,
      action || showDetail ? el("p", { class: "ts-links" },
        action ? el("a", { href: action, text: tr(`pages.clients.ts.action.${v.action}`) }) : null,
        action && showDetail ? " · " : null,
        showDetail ? el("a", { href: clientHref(result.address),
          text: tr(result.probe_allowed ? "pages.clients.ts.detail_probe" : "pages.clients.ts.detail") }) : null) : null),
    v.snippets ? el("div", { class: "snippets" }, snippets) : null,
    el("details", { class: "explain-more", open: state.open,
      ontoggle: (event) => { state.open = event.target.open; } },
      el("summary", { text: tr("pages.clients.ts.checks", { address: result.address }) }),
      el("ol", { class: "enforce-list ts-checks" }, (result.checks || []).map(checkRow))));
}

// Sprungziel #/clients?s=fehlersuche (Hinweis auf der Diagnose-Seite): einmal je Hash-Wechsel zur Karte
// scrollen und das Feld fokussieren – erst nach dem Zeichnen, app.js stellt danach die Scrollposition wieder her.
function jumpHere(ctx) {
  const query = String(window.location?.hash || "").split("?")[1] || "";
  if (new URLSearchParams(query).get("s") !== "fehlersuche" || ctx.uiState.scrolled) return;
  ctx.uiState.scrolled = true;
  ctx.afterRender(() => setTimeout(() => {
    const node = document.getElementById("fehlersuche");
    if (!node) return;
    node.scrollIntoView({ block: "start" });
    node.querySelector("input")?.focus({ preventScroll: true });
  }, 0));
}

export function troubleshootCard(ctx, snippets) {
  jumpHere(ctx);
  const input = el("input", { type: "text", inputmode: "text", maxlength: "45", autocomplete: "off", spellcheck: "false",
    class: "mono", value: state.input, placeholder: tr("pages.clients.ts.placeholder"),
    "aria-label": tr("pages.clients.ts.input_label"), "data-focus-key": "troubleshoot-ip",
    // Getipptes merken: Die Seite wird im Hintergrund neu gebaut, das Feld bekommt den Wert zurück.
    oninput: (event) => { state.input = event.target.value; } });
  const button = el("button", { type: "submit", class: "button primary", disabled: state.busy || null,
    text: state.busy ? tr("pages.clients.ts.busy") : tr("pages.clients.ts.run") });
  const form = el("form", { class: "ts-form", onsubmit: (event) => { event.preventDefault(); run(ctx, input.value); } },
    input, button);
  // Ergebnis nur zur Adresse im Feld zeigen – wer eine andere tippt, sieht kein fremdes Ergebnis.
  const matches = state.result && state.checked && state.input.trim() === state.checked;
  return card(tr("pages.clients.ts.title"), { help: "troubleshoot", id: "fehlersuche",
    sub: tr("pages.clients.ts.sub") },
    form,
    state.error ? el("p", { class: "field-error", role: "alert", text: state.error }) : null,
    state.result && (matches || !state.input) ? resultView(ctx, state.result, snippets) : null);
}

// Für Tests: Zustand zurücksetzen.
export function _reset() { state = { input: "", checked: "", busy: false, result: null, error: null, open: true }; }
