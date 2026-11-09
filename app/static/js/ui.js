// Wiederverwendbare Bausteine: Karten, Kacheln, ⓘ-Erklärungen, Badges.
//
// T2 (1.6): Jede Seite baut aus denselben Teilen – infoButton (ⓘ), statCard (Kachel), kvRow/kv
// (Zeile Beschriftung → Wert), rangePicker (Zeitraum), emptyState/errorState (leer bzw. Fehler)
// und chartCard (Diagramm, das sich bei flachem oder leerem Verlauf auf eine Zeile zusammenklappt).
// Alle Bausteine zeigt die Musterseite #/muster?dev=1 (pages/muster.js).
import { t as tr } from "./i18n.js";
import { el, rich, copyText, selectContents, apiPost, isNum, fmtTime, fmtDate } from "./util.js";
import { HELP } from "./help.js";
import { actionHref } from "./routes.js";

// --- ⓘ-Popover --------------------------------------------------------------
let openPopover = null;

function closePopover() {
  if (!openPopover) return;
  openPopover.button.setAttribute("aria-expanded", "false");
  openPopover.node.remove();
  openPopover = null;
}

document.addEventListener("click", (event) => {
  if (openPopover && !openPopover.node.contains(event.target) && event.target !== openPopover.button) closePopover();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && openPopover) {
    const { button } = openPopover;
    closePopover();
    button.focus();
  }
});
window.addEventListener("resize", closePopover);
// Erst ab 40 px Scrollweg schließen – Touch-Ruckeln und die einklappende Adressleiste lassen es offen.
window.addEventListener("scroll", () => {
  if (openPopover && Math.hypot(window.scrollX - openPopover.x, window.scrollY - openPopover.y) > 40) closePopover();
}, { passive: true });

export function isPopoverOpen() {
  return Boolean(openPopover && openPopover.button.isConnected);
}

/**
 * ⓘ-Knopf mit Erklärung aus HELP[key]. Das Symbol ist 14 px groß, die Tippfläche 32 px (unsichtbarer
 * Rand per CSS, verschiebt nichts im Layout); blass, bis die Maus darüber steht oder er den Fokus hat.
 * Unbekannter Schlüssel: null (dann steht einfach kein Knopf da).
 * more = { title, text }: eigener Text im Popover (z. B. der Rest eines Feld-Hilfetexts, der unter dem
 * Feld keinen Platz hat); der Link „In der Hilfe ansehen“ führt dann weiter zu HELP[key], falls es ihn gibt.
 * more.withHelp: unter dem eigenen Text steht zusätzlich die Erklärung aus HELP[key] (Karten, deren
 * Untertitel ins ⓘ gewandert ist – so bleibt beides an einem Knopf).
 */
export function infoButton(key, label, more) {
  const found = HELP[key];
  const extra = more && more.text ? more : null;
  if (!found && !extra) return null;
  const entry = extra ? { title: extra.title || found?.title || label, text: extra.text,
    also: extra.withHelp && found ? found.text : null } : found;
  const button = el("button", {
    type: "button", class: "info", "aria-label": `Erklärung: ${label || entry.title}`, "aria-expanded": "false",
  }, el("span", { class: "info-glyph", "aria-hidden": "true", text: "i" }));
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    if (openPopover && openPopover.button === button) { closePopover(); return; }
    closePopover();
    const node = el("div", { class: "popover", role: "dialog", "aria-label": entry.title },
      el("strong", { class: "popover-title", text: entry.title }),
      el("p", {}, rich(entry.text)),
      entry.also ? el("p", { class: "popover-also" }, rich(entry.also)) : null,
      found ? el("a", { href: `#/hilfe?t=${key}`, class: "popover-more", text: "In der Hilfe ansehen →",
        onclick: closePopover }) : null);
    document.body.append(node);
    const rect = button.getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 24);
    node.style.width = `${width}px`;
    const left = Math.min(window.innerWidth - width - 12, Math.max(12, rect.left + rect.width / 2 - width / 2));
    node.style.left = `${left + window.scrollX}px`;
    const below = rect.bottom + 8 + node.offsetHeight < window.innerHeight;
    node.style.top = `${(below ? rect.bottom + 8 : rect.top - node.offsetHeight - 8) + window.scrollY}px`;
    button.setAttribute("aria-expanded", "true");
    openPopover = { node, button, x: window.scrollX, y: window.scrollY };
  });
  return button;
}

// Früherer Name – derselbe Baustein.
export const info = infoButton;

// --- Eine Erklärzeile (T2 „Seiten entschlacken“) -------------------------------
// Je Karte und Feld steht höchstens eine Erklärzeile sichtbar da; der Rest wandert ins ⓘ (nichts wird
// gelöscht). Länger als LINE_MAX Zeichen → sichtbar bleibt der erste Satz (bzw. der Teil vor einem
// Gedankenstrich), der Rest steht im Popover.
export const LINE_MAX = 140;

// Hervorhebungen (**…**, `…`) dürfen nicht mitten durchgeschnitten werden.
function balanced(text) {
  return (text.split("**").length - 1) % 2 === 0 && (text.split("`").length - 1) % 2 === 0;
}

/**
 * Text in { first, rest } teilen: first passt in eine Zeile (≤ max Zeichen), rest geht ins ⓘ.
 * Geteilt wird am letzten Satzende vor max, sonst an einem Gedankenstrich („ – “); ohne passende
 * Stelle bleibt der Text ganz (rest leer).
 */
export function splitExplain(text, max = LINE_MAX) {
  const value = String(text ?? "").trim();
  if (value.length <= max) return { first: value, rest: "" };
  const cuts = [];
  const dashes = [];
  const sentence = /[.!?…](?=\s+[„"(A-ZÄÖÜ0-9*`])/g;
  for (let m = sentence.exec(value); m; m = sentence.exec(value)) {
    // Abkürzungen („z. B.“, „d. h.“, „ca.“) sind kein Satzende.
    if (!/(^|[\s(])[\p{L}\d]{1,2}\.$/u.test(value.slice(0, m.index + 1))) cuts.push([m.index + 1, m.index + 1]);
  }
  const dash = / – /g;
  for (let m = dash.exec(value); m; m = dash.exec(value)) dashes.push([m.index, m.index + 3]);
  const usable = (list) => list.filter(([end]) => end <= max && end >= 20 && balanced(value.slice(0, end)))
    .sort((a, b) => b[0] - a[0]);
  // Lieber ein ganzer Satz; nur ohne passendes Satzende am Gedankenstrich teilen.
  const fits = usable(cuts).length ? usable(cuts) : usable(dashes);
  if (!fits.length) return { first: value, rest: "" };
  const [end, next] = fits[0];
  let first = value.slice(0, end).trim();
  let rest = value.slice(next).trim();
  if (value.slice(end, next) === " – " && !/[.!?…]$/.test(first)) first = `${first} …`;
  if (rest) rest = rest.charAt(0).toUpperCase() + rest.slice(1);
  return { first, rest };
}

/**
 * Erklärzeile: Absatz mit höchstens einer Zeile Text; der Rest (und HELP[help]) im ⓘ dahinter.
 * opts: { help, title, class (Standard „card-sub“), tag }.
 */
export function explainLine(text, opts = {}) {
  if (!text) return null;
  const { first, rest } = splitExplain(text, opts.max);
  const more = rest ? infoButton(opts.help, opts.title || tr("pages.more"), { title: opts.title, text: rest, withHelp: true })
    : opts.help ? infoButton(opts.help, opts.title) : null;
  return el(opts.tag || "p", { class: opts.class || "card-sub" }, rich(first), more ? " " : null, more);
}

// --- Bausteine ---------------------------------------------------------------
// options.sub: Untertitel – eine Zeile sichtbar, ein längerer Rest steht im ⓘ der Karte (zusammen mit
// der Erklärung aus options.help).
export function card(title, options = {}, ...children) {
  const sub = typeof options.sub === "string" ? splitExplain(options.sub) : null;
  const button = sub && sub.rest
    ? infoButton(options.help, title, { title, text: sub.rest, withHelp: true })
    : options.help ? infoButton(options.help, title) : null;
  const subNode = sub ? (sub.first ? el("p", { class: "card-sub" }, rich(sub.first)) : null)
    : options.sub ? el("p", { class: "card-sub" }, options.sub) : null;
  const head = el("div", { class: "card-head" },
    el("div", { class: "card-title" }, el("h2", { text: title }), button, options.badge ?? null),
    options.actions ? el("div", { class: "card-actions" }, options.actions) : null);
  return el("section", { class: `card ${options.class || ""}`, id: options.id || null },
    head, subNode, ...children);
}

/**
 * Kachel mit einer Kennzahl. value: fertiger Text (über fmt* formatiert) oder Knoten.
 * spark: optionaler Mini-Verlauf (charts.sparkline) unter dem Wert.
 */
export function statCard({ label, value, unit, note, tone = "muted", help, long, spark }) {
  const shown = value instanceof Node ? value : String(value ?? "–");
  return el("div", { class: `stat${spark ? " has-spark" : ""}`, "data-tone": tone },
    el("div", { class: "stat-label" }, el("span", { text: label }), help ? infoButton(help, label) : null),
    el("div", { class: "stat-value", "data-long": long || (typeof shown === "string" && shown.length > 11) ? "true" : null },
      shown, unit ? el("span", { class: "unit", text: unit }) : null),
    note ? el("div", { class: "stat-note" }, note) : null,
    spark ? el("div", { class: "stat-spark" }, spark) : null);
}

// Früherer Name.
export const tile = statCard;

export function badge(text, tone = "muted", title) {
  return el("span", { class: "badge", "data-tone": tone, title: title || null, text });
}

/** Eine Zeile „Beschriftung ⓘ → Wert“ (für kv-Listen). */
export function kvRow(key, value, help) {
  return el("div", { class: "kv" },
    el("dt", {}, el("span", { text: key }), help ? infoButton(help, key) : null),
    el("dd", {}, value instanceof Node ? value : String(value ?? "–")));
}

/** Liste von Zeilen [Beschriftung, Wert, Hilfe-Schlüssel]; null-Einträge fallen weg. */
export function kv(rows) {
  return el("dl", { class: "kv-list" }, rows.filter(Boolean).map(([key, value, help]) => kvRow(key, value, help)));
}

/** Beschriftung eines Zeitraums: „15 min“, „6 h“, „24 h“, „7 Tage“. */
export function rangeLabel(seconds) {
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds <= 2 * 86400) return `${Math.round(seconds / 3600)} h`;
  const days = Math.round(seconds / 86400);
  return `${days} ${days === 1 ? "Tag" : "Tage"}`;
}

// Zeiträume der Verläufe (Übersicht, Quellen, Clients): 15 min bis 24 h.
export const RANGES_LIVE = [900, 3600, 21600, 86400];

/**
 * Zeitraum-Auswahl von Minuten bis Tagen – eine Komponente für alle Seiten.
 * options: Sekunden oder [Sekunden, Beschriftung]; value: gewählte Sekunden; onChange(sekunden).
 * Der gedrückte Knopf wird sofort markiert (auch wenn die Seite danach nicht neu zeichnet).
 */
export function rangePicker({ value, onChange, options = RANGES_LIVE, label = "Zeitraum", focusKey = "range" }) {
  const buttons = options.map((option) => {
    const [seconds, text] = Array.isArray(option) ? option : [option, rangeLabel(option)];
    const active = value === seconds;
    return el("button", {
      type: "button", class: `range${active ? " is-active" : ""}`, text, "data-focus-key": `${focusKey}:${seconds}`,
      "aria-pressed": active ? "true" : "false",
      onclick: (event) => {
        for (const button of buttons) {
          const on = button === event.currentTarget;
          button.classList.toggle("is-active", on);
          button.setAttribute("aria-pressed", on ? "true" : "false");
        }
        onChange(seconds);
      },
    });
  });
  return el("div", { class: "range-group", role: "group", "aria-label": label }, buttons);
}

export function rangeButtons(current, onChange) {
  return rangePicker({ value: current, onChange });
}

export function reachBar(percent, label) {
  const tone = percent >= 75 ? "good" : percent >= 25 ? "warn" : "crit";
  return el("div", { class: "reach", title: label || `${percent} %` },
    el("div", { class: "reach-track" }, el("div", { class: "reach-fill", "data-tone": tone, style: `width:${percent}%` })),
    el("span", { class: "reach-value", text: label || `${percent} %` }));
}

// Die acht letzten Abfragen als Kästchen (ältestes links).
export function reachRegister(reach) {
  const bits = [];
  for (let i = 7; i >= 0; i -= 1) bits.push((reach >> i) & 1);
  const answered = bits.filter(Boolean).length;
  return el("div", { class: "reach-bits", title: "Letzte acht Abfragen (rechts = neueste)",
    role: "img", "aria-label": `Letzte acht Abfragen: ${answered} von 8 beantwortet` },
    bits.map((b) => el("span", { class: `bit${b ? " ok" : ""}`, "aria-hidden": "true" })));
}

const LEVEL_ICON = { ok: "✓", info: "i", warn: "!", crit: "✕" };

export function insightList(items, ctx) {
  if (!items || !items.length) return null;
  return el("ul", { class: "insights" }, items.map((item) => el("li", { class: "insight", "data-level": item.level },
    el("span", { class: "insight-icon", "aria-hidden": "true", text: LEVEL_ICON[item.level] || "i" }),
    el("div", { class: "insight-body" },
      el("strong", { text: item.title }),
      // Eine Zeile sichtbar, der Rest des Hinweises im ⓘ (T2 „Seiten entschlacken“).
      hintLine(item),
      insightFixes(item, ctx),
      insightLink(item),
      insightAction(item)))));
}

function hintLine(item) {
  return oneLine(item.text, item.title || "Hinweis");
}

// 1.6.1: Zeile eines Hinweises – genau EINE sichtbare Zeile (erster Satz, zu lang wird per CSS mit „…“
// gekürzt). Der ganze Text steht dann im ⓘ dahinter (nichts wird gelöscht). Kurze Ein-Satz-Texte ohne ⓘ.
export const HINT_LINE_MAX = LINE_MAX;
const HINT_LINE_SAFE = 60; // so kurz passt der Satz auch bei 390 px in eine Zeile

export function hintFirst(text) {
  return splitExplain(text || "", HINT_LINE_MAX).first;
}

export function oneLine(text, title, opts = {}) {
  const value = String(text ?? "").trim();
  if (!value) return null;
  const first = hintFirst(value);
  const more = opts.info !== false && (first !== value || first.length > HINT_LINE_SAFE)
    ? infoButton(null, title, { title, text: value }) : null;
  return el("p", { class: "hint-line", id: opts.id || null }, el("span", { class: "hint-line-text", text: first }), more);
}

// Link „Zur … →“ eines Hinweises: Ziel aus der Routentabelle (routes.js), unbekannte Aktion ohne Link.
export function insightAction(item) {
  const href = item?.action ? actionHref(item.action) : null;
  return href ? el("a", { href, class: "insight-action", text: ACTION_LABEL[item.action] || "Ansehen →" }) : null;
}

// 1.5.4: „Per Klick beheben“ eines Hinweises (bisher nur: beobachteten Proxy eintragen). Der Knopf
// schickt nur die Kennung; welche Adresse eingetragen wird, entscheidet der Server aus seiner Liste.
const FIX_PATHS = { trust_proxy: "/api/web/proxies/trust" };

export function insightFixes(item, ctx) {
  const fixes = Array.isArray(item?.fixes) ? item.fixes.filter((f) => f && FIX_PATHS[f.kind] && f.id) : [];
  if (!fixes.length || ctx?.readonly) return null;
  return el("div", { class: "insight-fixes" }, fixes.map((fix) => el("button", {
    type: "button", class: "button", text: fix.label || "Beheben",
    onclick: async (event) => {
      if (!window.confirm(fix.confirm || `${fix.label}?`)) return;
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const result = await apiPost(FIX_PATHS[fix.kind], { id: fix.id });
        toast(result.already ? `${result.network} war schon eingetragen` : `${result.network} eingetragen`);
        for (const note of result.warnings || []) toast(note, "warn");
        ctx?.invalidate?.("settings");
        ctx?.refresh?.();
      } catch (error) {
        toast(error.message, "crit");
        button.disabled = false;
      }
    },
  })));
}

// Externer Link eines Hinweises (bisher nur Update-Hinweis): nur auf die Release-Seiten des Projekts.
const INSIGHT_LINK = /^https:\/\/github\.com\/mgc20\/ntp-gui\/releases(\/tag\/v[0-9A-Za-z.-]+)?$/;

export function insightLink(item) {
  if (!item || typeof item.link !== "string" || !INSIGHT_LINK.test(item.link)) return null;
  return el("a", { href: item.link, class: "insight-action", target: "_blank", rel: "noopener noreferrer",
    text: "Release-Notizen →" });
}

export const ACTION_LABEL = {
  gps: "Zur GPS-Seite →", sources: "Zu den Quellen →", settings: "Zu den Einstellungen →",
  clients: "Zu den Clients →", ptp: "Zur PTP-Seite →", hardware: "Zur Hardware-Seite →",
  clockquality: "Zur Uhrqualität →", uhrqualitaet: "Zur Uhrqualität →",
  diagnose: "Zur Diagnose →", notify: "Zu den Benachrichtigungen →",
};

/**
 * Leerzustand: ein ruhiger Satz statt einer leeren Fläche. text darf **fett** und `code` enthalten.
 * Längere Texte: eine Zeile sichtbar, der Rest im ⓘ dahinter (opts: { help, title }).
 */
export function emptyState(text, opts = {}) {
  const { first, rest } = splitExplain(text);
  if (!rest) return el("p", { class: "empty-note" }, rich(first));
  return el("p", { class: "empty-note" }, rich(first), " ",
    infoButton(opts.help, opts.title || tr("pages.more"), { title: opts.title || tr("pages.more"), text: rest, withHelp: true }));
}

// Früherer Name.
export const emptyNote = emptyState;

/**
 * Fehlerzustand: was nicht geladen werden konnte und warum. error: {status, message} (wie
 * ctx.dataError) oder Error. retry: true, wenn der Datencache von selbst neu fragt.
 */
export function errorText(error, what, retry = true) {
  const reason = error?.message || (error?.status ? `HTTP ${error.status}` : "unbekannter Fehler");
  return `Konnte ${what} nicht laden (${reason})${retry ? " – neuer Versuch läuft." : "."}`;
}

export function errorState(error, what, retry = true) {
  return el("p", { class: "empty-note is-error", role: "status", text: errorText(error, what, retry) });
}

// Gemeinsamer Lade-/Fehlerzustand: Solange nichts da ist „Lade … “, nach einem Fehler aber nicht
// endlos weiter „Lade …“, sondern was schiefging (der Datencache fragt von selbst erneut).
export function loadingText(ctx, key, url, what) {
  const failed = ctx?.dataError ? ctx.dataError(key, url) : null;
  return failed ? errorText(failed, what) : `Lade ${what} …`;
}

export function loadingOr(ctx, key, url, what) {
  const failed = ctx?.dataError ? ctx.dataError(key, url) : null;
  return failed ? errorState(failed, what) : emptyState(`Lade ${what} …`);
}

// --- chartCard ------------------------------------------------------------------
// „Flach“ nur bei ausreichender Abdeckung: genug gültige Punkte, und keine Lücke (auch am Anfang
// oder Ende des Zeitraums) größer als 10 % des Zeitraums oder 3 × der typische Abstand der Punkte.
const FLAT_MIN_POINTS = 10;
const FLAT_MAX_GAP_SHARE = 0.1;
const FLAT_MAX_GAP_STEPS = 3;

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

/**
 * Form eines Verlaufs: "empty" (weniger als zwei Messwerte), "flat" (Spannweite höchstens
 * max(flatAbs, |Mittel| · flatRel), mindestens FLAT_MIN_POINTS Messwerte und ohne Lücken; nie bei
 * flat: false) oder "chart". series: [{ points: [[t, v], …] }, …]. Außerdem: points (alle Punkte,
 * auch null), maxGap (größte Lücke in s), aroundZero (pendelt um 0: Vorzeichenwechsel oder |Mittel|
 * kleiner als die Spannweite) und bound = max(|min|, |max|).
 */
export function seriesShape(series, { flatRel = 0.02, flatAbs = 0, flat: canBeFlat = true } = {}) {
  let count = 0; let points = 0; let sum = 0; let min = Infinity; let max = -Infinity; let first = null;
  let tMin = Infinity; let tMax = -Infinity;
  const valid = [];
  const steps = [];
  for (const s of series || []) {
    const times = [];
    const good = [];
    for (const point of s.points || []) {
      const [t, v] = point;
      points += 1;
      if (isNum(t)) {
        times.push(t);
        if (t < tMin) tMin = t;
        if (t > tMax) tMax = t;
      }
      if (!isNum(v)) continue;
      count += 1; sum += v;
      if (v < min) min = v;
      if (v > max) max = v;
      if (isNum(t)) {
        good.push(t);
        if (first === null || t < first) first = t;
      }
    }
    times.sort((a, b) => a - b);
    for (let i = 1; i < times.length; i += 1) if (times[i] > times[i - 1]) steps.push(times[i] - times[i - 1]);
    valid.push(good.sort((a, b) => a - b));
  }
  if (count < 2) return { kind: "empty", count, points, first };
  const mean = sum / count;
  // Größte Lücke je Reihe zwischen gültigen Punkten, auch zum Anfang und Ende des Zeitraums.
  let maxGap = 0;
  for (const good of valid) {
    if (!good.length) continue;
    const edges = [tMin, ...good, tMax];
    for (let i = 1; i < edges.length; i += 1) maxGap = Math.max(maxGap, edges[i] - edges[i - 1]);
  }
  const period = tMax - tMin;
  const step = median(steps);
  const covered = count >= FLAT_MIN_POINTS && period > 0 && isNum(step)
    && maxGap <= FLAT_MAX_GAP_SHARE * period && maxGap <= FLAT_MAX_GAP_STEPS * step;
  const spread = max - min;
  const flat = canBeFlat && covered && spread <= Math.max(flatAbs, Math.abs(mean) * flatRel);
  const aroundZero = (min < 0 && max > 0) || Math.abs(mean) < spread;
  const bound = Math.max(Math.abs(min), Math.abs(max));
  return { kind: flat ? "flat" : "chart", count, points, first, min, max, mean, maxGap, aroundZero, bound };
}

// Beginn der Sammlung: nur Uhrzeit, wenn er heute (in der Zeitzone des Servers) und höchstens 12 h
// zurück liegt; sonst mit Datum – „seit 19:35“ sähe am Abend davor wie ein Zeitpunkt in der Zukunft aus.
function sinceText(since, now, zone) {
  const sameDay = isNum(now) && fmtDate(since, { date: "numeric", time: false, zone }) === fmtDate(now, { date: "numeric", time: false, zone });
  const recent = isNum(now) && now - since <= 12 * 3600;
  return sameDay && recent ? fmtTime(since, false, zone) : fmtDate(since, { date: "day", time: "short", zone });
}

/**
 * Karte mit Verlaufsdiagramm, die sich zusammenklappt, wenn das Diagramm nichts zu sagen hat:
 *   leer  → „Satelliten im Verlauf: sammelt seit 23:30“ (bzw. „noch keine Messwerte“; liegen Punkte
 *           vor, aber alle ohne Wert: „keine Messwerte seit …“; Beginn vor über 12 h oder an einem
 *           anderen Tag mit Datum)
 *   flach → „Maximaler Fehler: stabil um ± 420 µs – Diagramm zeigen“ (Knopf klappt auf); pendelt die
 *           Reihe um 0: „stabil innerhalb ± 400 ns“ (größter Betrag statt Mittelwert)
 * opts: { title, help, sub, actions, id, class, series (für die Form), format(v) für den Mittelwert,
 *         draw(host) – zeichnet das Diagramm nach dem Einhängen, key – Merkname fürs Aufklappen,
 *         since – Beginn der Sammlung (Unix-s), now – jetzt (Standard: Uhr des Servers aus ctx.status),
 *         zone – Zeitzone des Servers, flatRel, flatAbs, flat: false, emptyText – eigener Text für „leer“,
 *         collapse: false – nie zusammenklappen (z. B. während Daten noch laden) }.
 * ctx: Seitenkontext (afterRender, uiState, rerender).
 */
export function chartCard(ctx, opts) {
  const shape = seriesShape(opts.series, opts);
  const ui = ctx.uiState || {};
  const open = ui.chartOpen || (ui.chartOpen = new Set());
  const key = opts.key || opts.title;
  const format = opts.format || ((v) => String(v));
  const classes = `chart-card ${opts.class || ""}`.trim();
  const rerender = () => (ctx.rerender ? ctx.rerender() : null);
  if (opts.collapse !== false && (shape.kind === "empty" || (shape.kind === "flat" && !open.has(key)))) {
    let text;
    let toggle = null;
    if (shape.kind === "empty") {
      const firstPoint = (opts.series || []).flatMap((s) => s.points || []).map((p) => p[0]).filter(isNum);
      const since = isNum(opts.since) ? opts.since : shape.first ?? (firstPoint.length ? Math.min(...firstPoint) : null);
      const now = isNum(opts.now) ? opts.now : isNum(ctx.status?.system?.time) ? ctx.status.system.time : Date.now() / 1000;
      const when = isNum(since) ? sinceText(since, now, opts.zone ?? null) : null;
      // Punkte da, aber ohne einen Wert (GPS ohne Fix, Quelle aus): nicht „sammelt“, sondern „keine Messwerte“.
      const silent = shape.count === 0 && shape.points > 0;
      text = opts.emptyText || (when ? `${silent ? "keine Messwerte" : "sammelt"} seit ${when}` : "noch keine Messwerte");
    } else {
      // Um 0 pendelnde Reihen (Abweichung der Uhr): der Mittelwert läge nahe 0 und verschwiege die
      // Schwankung – dann der größte Betrag. format liefert ggf. schon „±“ oder „+“, das fällt weg.
      text = shape.aroundZero
        ? `stabil innerhalb ± ${format(shape.bound).replace(/^[±+]\s*/, "")} –`
        : `stabil um ${format(shape.mean)} –`;
      toggle = el("button", { type: "button", class: "chart-line-toggle", text: "Diagramm zeigen",
        "data-focus-key": `chart-open:${key}`, "aria-label": `${opts.title}: Diagramm zeigen`,
        onclick: () => { open.add(key); rerender(); } });
    }
    return el("section", { class: `card ${classes} is-collapsed`, id: opts.id || null, "data-shape": shape.kind },
      el("div", { class: "chart-line" },
        el("div", { class: "card-title" }, el("h2", { text: opts.title }), opts.help ? infoButton(opts.help, opts.title) : null),
        el("span", { class: "chart-line-text", text }), toggle,
        opts.actions ? el("div", { class: "card-actions" }, opts.actions) : null));
  }
  const host = el("div", { class: "chart-host" });
  const fold = shape.kind === "flat" && open.has(key)
    ? el("button", { type: "button", class: "chart-line-toggle", text: "Einklappen", "data-focus-key": `chart-close:${key}`,
      "aria-label": `${opts.title}: Diagramm einklappen`, onclick: () => { open.delete(key); rerender(); } }) : null;
  const actions = opts.actions || fold ? [opts.actions || null, fold] : null;
  if (ctx.afterRender) ctx.afterRender(() => opts.draw(host));
  return card(opts.title, { help: opts.help, sub: opts.sub, class: classes, id: opts.id, actions }, host);
}

export function toast(message, tone = "good") {
  const node = el("div", { class: "toast", "data-tone": tone, role: "status", text: message });
  document.body.append(node);
  setTimeout(() => node.classList.add("is-leaving"), 3200);
  setTimeout(() => node.remove(), 3800);
}

// „Kopieren“-Knopf für Code-Schnipsel und Schlüssel. `target` ist das Element mit
// dem Text (pre/code); klappt das Kopieren nicht, wird es markiert.
export function copyButton(text, target) {
  const button = el("button", { type: "button", class: "copy", text: "Kopieren" });
  button.addEventListener("click", async () => {
    const value = typeof text === "function" ? text() : text;
    if (await copyText(value)) { toast("Kopiert"); return; }
    const node = target || button.closest(".snippet, .apikey-token")?.querySelector("pre, code");
    const marked = selectContents(node);
    toast(marked ? "Kopieren nicht möglich – Text ist markiert, bitte Strg+C drücken" : "Kopieren nicht möglich – bitte markieren", "warn");
  });
  return button;
}
