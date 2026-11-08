"""T1 Grundreinigung, Thema Darstellung (docs/konzept/version-1.6.md, Anhang „Befunde“).

Je Befund ein Test, der vor der Korrektur rot war:
  * Kontraste (F9, F10 hell und dunkel): WCAG-2.x-Verhältnisse direkt aus app.css gerechnet.
  * CSS-Regeln (F5, F12, F18) als Text geprüft.
  * Verhalten im JS (F8, F11, F15, K3, U10, U14, U16) mit Node und einer kleinen DOM-Attrappe.
  * Texte und Zahlenformate (F14, F15, F17, K1) als statische Prüfung.
  * Kurze Auswahltexte in den Einstellungen (U12).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"
PAGES = sorted((JS / "pages").glob("*.js"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401

import settings  # noqa: E402

CSS = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
THEMES = ("dark", "light")
MIN_RATIO = 4.5


# --------------------------------------------------------------------------- CSS-Helfer
def theme_tokens(theme: str) -> dict:
    match = re.search(r':root\[data-theme="%s"\]\s*\{(.*?)\n\}' % theme, CSS, re.S)
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", match.group(1)))


def media_block(query: str) -> str:
    """Inhalt aller @media-Blöcke mit genau dieser Bedingung (Klammern gezählt)."""
    out = []
    for match in re.finditer(r"@media\s*\(%s\)\s*\{" % re.escape(query), CSS):
        depth, i = 1, match.end()
        while depth and i < len(CSS):
            depth += {"{": 1, "}": -1}.get(CSS[i], 0)
            i += 1
        out.append(CSS[match.end():i - 1])
    return "\n".join(out)


def rules(text: str = CSS):
    """(Selektor, Deklarationen) der innersten Blöcke."""
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        yield selector.strip(), body


def decl(body: str, prop: str):
    match = re.search(r"(?<![-\w])%s:\s*([^;]+)" % re.escape(prop), body)
    return match.group(1).strip() if match else None


def rgba(value: str):
    value = value.strip().lstrip("#")
    if len(value) in (3, 4):
        value = "".join(c * 2 for c in value)
    channels = [int(value[i:i + 2], 16) / 255 for i in range(0, len(value), 2)]
    return channels + ([1.0] if len(channels) == 3 else [])


def resolve(value: str, tokens: dict):
    """var(--x, fallback) und Hex-Farben → [r, g, b, a]; None, wenn nicht auflösbar."""
    value = value.strip()
    match = re.fullmatch(r"var\((--[\w-]+)(?:,\s*(.+))?\)", value)
    if match:
        if match.group(1) in tokens:
            return resolve(tokens[match.group(1)], tokens)
        return resolve(match.group(2), tokens) if match.group(2) else None
    if value in ("#fff", "#ffffff", "white"):
        return [1.0, 1.0, 1.0, 1.0]
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", value):
        return rgba(value)
    return None


def over(color, base):
    alpha = color[3]
    return [color[i] * alpha + base[i] * (1 - alpha) for i in range(3)] + [1.0]


def luminance(color) -> float:
    def channel(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def ratio(fg, bg) -> float:
    if fg[3] < 1:
        fg = over(fg, bg)
    high, low = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def theme_rules(theme: str) -> dict:
    """Selektor → zusammengeführte Deklarationen für ein Theme (Theme-Regeln überschreiben)."""
    merged: dict[str, dict] = {}
    other = [t for t in THEMES if t != theme][0]
    for selector, body in rules():
        if selector.startswith("@") or f'data-theme="{other}"' in selector:
            continue
        selector = re.sub(r':root\[data-theme="%s"\]\s*' % theme, "", selector).strip()
        props = merged.setdefault(selector, {})
        for prop in ("background", "background-color", "color"):
            value = decl(body, prop)
            if value:
                props["background" if prop == "background-color" else prop] = value
    return merged


class KontrastTest(unittest.TestCase):
    # Flächen, auf denen Text steht. --surface-3 trägt Text nur als `code` (erbt die Schriftfarbe
    # aus dem Fließtext, auch aus gedämpftem Text) – deshalb gilt sie für die Schrift-Tokens mit.
    SURFACES = ("--bg", "--surface", "--surface-2")
    TEXT_TOKENS = ("--ink", "--ink-2", "--ink-muted", "--good-ink", "--warn-ink", "--crit-ink", "--info-ink")
    # Der Akzent erscheint auch direkt als Schrift (Links).
    COLOR_AS_TEXT = ("--accent",)

    def check(self, fg_value, bg_value, theme, label, bases=SURFACES):
        tokens = theme_tokens(theme)
        fg, bg = resolve(fg_value, tokens), resolve(bg_value, tokens)
        self.assertIsNotNone(fg, f"{label}: {fg_value} nicht auflösbar")
        self.assertIsNotNone(bg, f"{label}: {bg_value} nicht auflösbar")
        # Halbtransparente Flächen (…-soft) liegen auf einer der Grundflächen.
        grounds = [over(bg, resolve(f"var({b})", tokens)) for b in bases] if bg[3] < 1 else [bg]
        worst = min(ratio(fg, ground) for ground in grounds)
        self.assertGreaterEqual(worst, MIN_RATIO, f"{theme}: {label} nur {worst:.2f}:1")

    def test_f9_primaerknopf_beide_themes(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                props = theme_rules(theme)[".button.primary"]
                self.check(props["color"], props["background"], theme, ".button.primary")

    def test_f10_ink_muted_auf_flaechen(self):
        for theme in THEMES:
            for surface in (*self.SURFACES, "--surface-3"):
                with self.subTest(theme=theme, surface=surface):
                    self.check("var(--ink-muted)", f"var({surface})", theme, f"--ink-muted auf {surface}")

    def test_schrift_tokens_auf_allen_flaechen(self):
        for theme in THEMES:
            for token in self.TEXT_TOKENS:
                for surface in (*self.SURFACES, "--surface-3"):
                    with self.subTest(theme=theme, token=token, surface=surface):
                        self.check(f"var({token})", f"var({surface})", theme, f"{token} auf {surface}")
            for token in self.COLOR_AS_TEXT:
                for surface in self.SURFACES:
                    with self.subTest(theme=theme, token=token, surface=surface):
                        self.check(f"var({token})", f"var({surface})", theme, f"{token} auf {surface}")

    def test_statusschrift_auf_getoenter_flaeche(self):
        for theme in THEMES:
            for tone in ("good", "warn", "crit", "info"):
                with self.subTest(theme=theme, tone=tone):
                    self.check(f"var(--{tone}-ink)", f"var(--{tone}-soft)", theme, f"--{tone}-ink auf --{tone}-soft")
            for fill in ("--good", "--warn", "--crit", "--info", "--accent", "--ink-muted"):
                with self.subTest(theme=theme, fill=fill):
                    self.check("var(--on-status)", f"var({fill})", theme, f"--on-status auf {fill}")

    def test_statusfarbe_als_schrift_nur_ueber_ink_token(self):
        """--warn hell hat auf --bg nur 4,496:1 – Schrift in Statusfarbe läuft deshalb über …-ink."""
        found = re.findall(r"(?<![-\w])color:\s*var\(--(?:good|warn|crit|info)\)", CSS)
        self.assertEqual(found, [])

    def test_regeln_mit_schrift_und_hintergrund(self):
        """Jede Regel, die Schrift- und Hintergrundfarbe setzt (z. B. Hinweisband „neu geladen“)."""
        checked = 0
        for theme in THEMES:
            for selector, props in theme_rules(theme).items():
                if "color" not in props or "background" not in props or selector == "body":
                    continue
                tokens = theme_tokens(theme)
                if resolve(props["color"], tokens) is None or resolve(props["background"], tokens) is None:
                    continue
                checked += 1
                with self.subTest(theme=theme, selector=selector):
                    self.check(props["color"], props["background"], theme, selector)
        self.assertGreater(checked, 30)


class CssTest(unittest.TestCase):
    def test_f5_checkbox_beschriftung_unter_720(self):
        settings_js = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
        self.assertIn('el("span", { class: "cell-check-text", text: label })', settings_js)
        self.assertRegex(CSS, r"(?m)^\.cell-check-text \{ display: none; \}")
        self.assertRegex(media_block("max-width: 720px"), r"\.cell-check-text \{[^}]*display: inline")

    def test_f5_kaestchen_in_eigener_zeile_unter_720(self):
        """Die drei Kästchen liegen in Zeile 2, nicht in der 36-px-Spalte des ✕-Knopfs."""
        block = dict(rules(media_block("max-width: 720px")))
        self.assertEqual(decl(block[".src-editor-row .cell-check"], "grid-row"), "2")
        self.assertEqual(decl(block[".src-editor-row > .icon-button"], "grid-row"), "1")
        narrow = dict(rules(media_block("max-width: 400px")))
        self.assertEqual(decl(narrow[".src-editor-row .cell-check"], "flex-direction"), "column")

    def test_f12_ip_in_client_link_bricht_nicht_um(self):
        body = dict(rules()).get(".client-link .mono")
        self.assertIsNotNone(body, "Regel .client-link .mono fehlt")
        self.assertEqual(decl(body, "white-space"), "nowrap")

    def test_f18_titel_auf_dem_handy_nicht_einzeilig_abgeschnitten(self):
        body = dict(rules(media_block("max-width: 640px"))).get(".topbar h1")
        self.assertIsNotNone(body, ".topbar h1 fehlt in der 640-px-Media-Query")
        self.assertEqual(decl(body, "white-space"), "normal")
        self.assertEqual(decl(body, "-webkit-line-clamp"), "2")


    def test_f18_titel_bei_320_lesbar(self):
        body = dict(rules(media_block("max-width: 640px")))[".topbar h1"]
        self.assertTrue(decl(body, "font-size").startswith("clamp("))
        tiny = dict(rules(media_block("max-width: 360px")))
        self.assertIn("#sync-label", tiny, "Zustandstext bei 320 px nicht nur für Screenreader")
        self.assertEqual(decl(tiny["#sync-label"], "position"), "absolute")

# --------------------------------------------------------------------------- Node
DOM_SHIM = r"""
class Node {
  constructor() { this.childNodes = []; this.parentNode = null; }
  append(...items) { for (const item of items) { const n = typeof item === "string" ? new Text(item) : item;
    if (n.parentNode) n.remove(); n.parentNode = this; this.childNodes.push(n); } }
  appendChild(n) { this.append(n); return n; }
  remove() { if (this.parentNode) { const list = this.parentNode.childNodes; list.splice(list.indexOf(this), 1); this.parentNode = null; } }
  contains(n) { for (let c = n; c; c = c.parentNode) if (c === this) return true; return false; }
  get isConnected() { for (let c = this; c; c = c.parentNode) if (c === globalThis.document.body) return true; return false; }
  get textContent() { return this._text ?? this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this._text = String(v); this.childNodes = []; }
  replaceChildren(...items) { this.childNodes = []; this._text = undefined; this.append(...items); }
}
class Text extends Node { constructor(t) { super(); this._text = String(t); } }
class Element extends Node {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.attrs = {}; this.dataset = {}; this.style = {};
    this.listeners = {}; this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } }; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  getBoundingClientRect() { return { left: 10, top: 10, bottom: 30, width: 20, height: 20 }; }
  get offsetHeight() { return 100; }
  focus() {}
  get children() { return this.childNodes.filter((c) => c instanceof Element); }
  findAll(pred) { const out = []; const walk = (n) => { for (const c of n.children) { if (pred(c)) out.push(c); walk(c); } }; walk(this); return out; }
}
const listeners = {};
globalThis.Node = Node; globalThis.Element = Element; globalThis.HTMLElement = Element;
globalThis.document = { createElement: (t) => new Element(t), createElementNS: (n, t) => new Element(t),
  createTextNode: (t) => new Text(t), addEventListener() {}, getElementById: () => null, querySelector: () => null,
  body: new Element("body"), documentElement: new Element("html") };
globalThis.window = { location: { hash: "" }, scrollX: 0, scrollY: 0, innerWidth: 1200, innerHeight: 800,
  addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }, matchMedia: () => ({ matches: false }),
  localStorage: { getItem: () => null, setItem() {} } };
globalThis.localStorage = window.localStorage;
globalThis.requestAnimationFrame = () => 0;
globalThis.__fire = (type) => { for (const fn of listeners[type] || []) fn({}); };
"""


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class NodeTest(unittest.TestCase):
    def run_js(self, code: str):
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / "dom.mjs"
            shim.write_text(DOM_SHIM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            root = json.dumps(JS.resolve().as_uri())
            script.write_text(f'import "./dom.mjs";\nconst JS = {root};\n{code}', encoding="utf-8")
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_f8_popover_bleibt_bei_kleinem_scrollweg_offen(self):
        out = self.run_js("""
const ui = await import(JS + "/ui.js");
const button = ui.info("chart_stats", "x");
document.body.append(button);
button.listeners.click[0]({ stopPropagation() {} });
const offen = ui.isPopoverOpen();
window.scrollY = 12; __fire("scroll");
const nachKlein = ui.isPopoverOpen();
window.scrollY = 80; __fire("scroll");
console.log(JSON.stringify({ offen, nachKlein, nachGross: ui.isPopoverOpen() }));
""")
        self.assertEqual(out, {"offen": True, "nachKlein": True, "nachGross": False})

    def test_f11_jetzt_ausserhalb_min_max_wird_erklaert(self):
        out = self.run_js("""
const charts = await import(JS + "/charts.js");
const stats = { now: 11, min: 10, max: 12, mean: 11, count: 20 };
const text = (current) => charts.statsHeader(stats, String, null, { current }).textContent;
console.log(JSON.stringify({ aussen: text(30), innen: text(11) }));
""")
        self.assertIn("Mittelwerte", out["aussen"])
        self.assertNotIn("Mittelwerte", out["innen"])

    def test_f11_hinweis_nur_bei_live_wert_und_sichtbarem_unterschied(self):
        out = self.run_js("""
const charts = await import(JS + "/charts.js");
const stats = { now: 50, min: 10, max: 12, mean: 11, count: 20 };
const ohneLive = charts.statsHeader(stats, String, { up: true, text: "1 Spitze" }, {}).textContent;
const fmt = (v) => v.toFixed(1);
const gerundet = charts.statsHeader(stats, fmt, null, { current: 12.0004 }).textContent;
const drunter = charts.statsHeader(stats, fmt, null, { current: 9.99 }).textContent;
console.log(JSON.stringify({ ohneLive, gerundet, drunter }));
""")
        self.assertNotIn("Mittelwerte", out["ohneLive"])
        self.assertNotIn("Mittelwerte", out["gerundet"])
        self.assertNotIn("Mittelwerte", out["drunter"])

    def test_f15_iso_zeit_deutsch_in_utc(self):
        out = self.run_js("""
const util = await import(JS + "/util.js");
console.log(JSON.stringify([util.fmtIsoUtc("2026-11-08T12:34:56.000Z"), util.fmtIsoUtc(null), util.fmtIsoUtc("kaputt")]));
""")
        self.assertEqual(out, ["08.11.26, 12:34:56 UTC", "–", "–"])

    def test_k3_reach_register_hat_rolle_und_beschriftung(self):
        out = self.run_js("""
const ui = await import(JS + "/ui.js");
const node = ui.reachRegister(0b11111101);
console.log(JSON.stringify({ role: node.getAttribute("role"), label: node.getAttribute("aria-label"),
  bits: node.children.map((c) => [c.getAttribute("aria-hidden"), c.getAttribute("aria-label")]) }));
""")
        self.assertEqual(out["role"], "img")
        self.assertEqual(out["label"], "Letzte acht Abfragen: 7 von 8 beantwortet")
        self.assertEqual(out["bits"], [["true", None]] * 8)

    def test_u10_grund_nur_wenn_anders_als_zustand(self):
        out = self.run_js("""
const src = await import(JS + "/pages/sources.js");
console.log(JSON.stringify({
  best: src.reasonCell({ state: "*", select_state: "best" }).textContent,
  combined: src.reasonCell({ state: "+", select_state: "combined" }).textContent,
  large: src.reasonCell({ state: "-", select_state: "large_distance" }).textContent,
}));
""")
        self.assertEqual(out["best"], "–")
        self.assertEqual(out["combined"], "–")
        self.assertTrue(out["large"].startswith("Unsicherheit zu groß"), out["large"])

    def test_u14_quelle_ohne_doppelten_namen(self):
        out = self.run_js("""
const c = await import(JS + "/clocksync.js");
console.log(JSON.stringify([c.sourceText("GPS", "GPS"), c.sourceText("GPS + PPS", "PPS"),
  c.sourceText("NTP", "192.168.1.1"), c.sourceText("GPS", "NMEA"), c.sourceText("", "")]));
""")
        self.assertEqual(out, ["GPS", "GPS + PPS", "NTP (192.168.1.1)", "GPS (NMEA)", "Quelle"])

    def test_u16_rohdaten_der_ereignisse_eingeklappt(self):
        out = self.run_js("""
const diag = await import(JS + "/pages/diagnose.js");
const li = diag.eventRow({ t: 1793527200, level: "info", kind: "gps", title: "x", data: { a: 1 } });
const raw = li.findAll((n) => (n.getAttribute("class") || "").includes("diag-event-data"));
const details = li.children.filter((n) => n.tagName === "DETAILS");
console.log(JSON.stringify({ raw: raw.length, inDetails: details.some((d) => raw.every((r) => d.contains(r))),
  text: raw.map((r) => r.textContent) }));
""")
        self.assertEqual(out["raw"], 1)
        self.assertTrue(out["inDetails"])
        self.assertEqual(out["text"], ["a=1"])


# --------------------------------------------------------------------------- Texte
def code_lines(path: Path):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.lstrip().startswith("//"):
            yield number, line


class TextTest(unittest.TestCase):
    def test_f14_kein_tofixed_in_seiten(self):
        found = [f"{p.name}:{n}" for p in PAGES for n, line in code_lines(p) if ".toFixed(" in line]
        self.assertEqual(found, [], "Zahlen auf Seiten über fmt* aus util.js (Komma statt Punkt)")

    def test_f14_snr_nicht_roh(self):
        self.assertNotIn("`${gps.snr_avg}`", (JS / "pages" / "gps.js").read_text(encoding="utf-8"))

    def test_f15_gps_zeit_formatiert(self):
        self.assertNotIn('["GPS-Zeit", gps.time ||', (JS / "pages" / "gps.js").read_text(encoding="utf-8"))

    def test_f17_keine_versionsgeschichte_im_bedientext(self):
        pattern = re.compile(r"\b(?:ab|seit|vor|in|bis)\s+(?:Version\s+)?1\.\d|\*\*1\.\d+\*\*", re.I)
        files = [*sorted(JS.glob("help*.js")), *PAGES]
        found = [f"{p.name}:{n}" for p in files for n, line in code_lines(p) if pattern.search(line)]
        self.assertEqual(found, [])
        for key, field in settings.FIELDS.items():
            with self.subTest(field=key):
                self.assertIsNone(pattern.search(field.get("help") or ""))

    def test_k1_keine_ungenutzten_konstanten_in_seiten(self):
        unused = []
        for path in PAGES:
            text = path.read_text(encoding="utf-8")
            for name in re.findall(r"(?m)^const ([A-Za-z_$][\w$]*) =", text):
                if len(re.findall(r"(?<![\w$])%s(?![\w$])" % re.escape(name), text)) < 2:
                    unused.append(f"{path.name}:{name}")
        self.assertEqual(unused, [])


class SettingsTest(unittest.TestCase):
    def test_u12_auswahltexte_passen_in_die_liste(self):
        """Lange Auswahltexte schneidet der native select ab („(empfohle“) – Erklärung gehört ins ⓘ."""
        for key, field in settings.FIELDS.items():
            for option in field.get("options") or []:
                label = option[1] if isinstance(option, (list, tuple)) else option
                with self.subTest(field=key, option=label):
                    self.assertLessEqual(len(str(label)), 40)


if __name__ == "__main__":
    unittest.main()
