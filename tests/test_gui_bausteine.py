"""T2 GUI-Erneuerung, erster Teil: Bausteine in ui.js und Zahlen in util.js (docs/konzept/version-1.6.md).

  * Zahlenformate (fmtNumber, fmtSeconds, fmtDuration, fmtPpm, fmtDate) im echten JS-Interpreter:
    passende Einheit, keine Nullen am Ende („± 1 ms“ statt „± 1,000 ms“), Komma im Deutschen,
    Punkt im Englischen, ISO-Zeiten formatiert.
  * Akzeptanzkriterium „kein Text \\d,000 und kein \\d.\\d+ (s|ms) in deutscher Sprache“: über viele
    Größenordnungen und an gerenderten Seiten mit Testdaten.
  * Bausteine: statCard, kvRow, rangePicker, emptyState/errorState, chartCard, infoButton.
  * Lint-Regeln per grep: kein toFixed und keine eigenen toLocale*-Aufrufe in den Seiten, feste
    Nachkommastellen (fmtFixed) nur in Achsenbeschriftungen.
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
CSS = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_frontend_states import DOM  # noqa: E402 – dieselbe DOM-Attrappe wie die T1-Tests

# Im Deutschen verboten: „1,000 ms“ (liest sich als tausend) und Punkt als Dezimalzeichen vor s/ms.
FORBIDDEN_DE = re.compile(r"\d,000(?:\s|$)|\d\.\d+ (?:s|ms)\b")
# Strenger für Werte mit Einheit: keine Null am Ende der Nachkommastellen (deutsches Komma).
TRAILING_ZERO = re.compile(r"\d,\d*0 ?(?:ns|µs|ms|s|ppm|ppb|min|h|°C|K)\b")


def mod(path: str) -> str:
    return json.dumps((JS / path).resolve().as_uri())


def code_lines(path: Path):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        if not stripped.startswith("//") and not stripped.startswith("*"):
            yield number, line


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class NodeTest(unittest.TestCase):
    def run_js(self, body: str, tz: str = "Europe/Berlin"):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dom.mjs").write_text(DOM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            script.write_text('import { text, withAttr, ctx } from "./dom.mjs";\n' + body, encoding="utf-8")
            env = {**os.environ, "TZ": tz}
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])


class ZahlenTest(NodeTest):
    def fmt(self, calls: dict, lang: str = "de"):
        body = f"""
const util = await import({mod("util.js")});
const i18n = await import({mod("i18n.js")});
i18n._setCatalogs({{ de: {{}}, en: {{}} }}, {json.dumps(lang)});
const {{ fmtNumber, fmtFixed, fmtSeconds, fmtDuration, fmtPpm, fmtDate, fmtIsoUtc, fmtRate, fmtNs, fmtLogInterval }} = util;
const calls = {json.dumps(calls)};
const out = {{}};
for (const expr of Object.keys(calls)) out[expr] = eval(expr);
console.log(JSON.stringify(out));
"""
        return self.run_js(body)

    def test_fmt_seconds_einheit_und_keine_nullen(self):
        cases = {
            "fmtSeconds(0.001)": "1 ms",
            "fmtSeconds(0.014)": "14 ms",
            "`± ${fmtSeconds(0.001)}`": "± 1 ms",
            "fmtSeconds(0.00042)": "420 µs",
            "fmtSeconds(0.0000004)": "400 ns",
            "fmtSeconds(0.000005)": "5 µs",
            "fmtSeconds(0.0008)": "800 µs",
            "fmtSeconds(0.0012345)": "1,235 ms",
            "fmtSeconds(0.1234)": "123,4 ms",
            "fmtSeconds(1.5)": "1,5 s",
            "fmtSeconds(2)": "2 s",
            "fmtSeconds(0)": "0 s",
            "fmtSeconds(0.0042, 3, true)": "+4,2 ms",
            "fmtSeconds(-0.0042, 3, true)": "−4,2 ms",
            "fmtSeconds(null)": "–",
            "fmtNs(1500)": "+1,5 µs",
        }
        out = self.fmt(cases)
        for expr, expected in cases.items():
            with self.subTest(expr=expr):
                self.assertEqual(out[expr], expected)

    def test_fmt_duration(self):
        cases = {
            "fmtDuration(0.0005)": "500 µs",
            "fmtDuration(0.02)": "20 ms",
            "fmtDuration(42)": "42 s",
            "fmtDuration(600)": "10 min",
            "fmtDuration(3600)": "1 h",
            "fmtDuration(5400)": "1 h 30 min",
            "fmtDuration(86400)": "1 d",
            "fmtDuration(93784)": "1 d 2 h",
            "fmtDuration(-5)": "0 s",
            "fmtDuration(undefined)": "–",
            "fmtLogInterval(-2)": "0,25 s",
            "fmtLogInterval(6)": "1 min",
        }
        out = self.fmt(cases)
        for expr, expected in cases.items():
            with self.subTest(expr=expr):
                self.assertEqual(out[expr], expected)

    def test_fmt_ppm_und_number(self):
        cases = {
            "fmtPpm(-12.345)": "−12,3 ppm",
            "fmtPpm(1.5)": "1,5 ppm",
            "fmtPpm(0.1234)": "0,123 ppm",
            "fmtPpm(150.4)": "150 ppm",
            "fmtPpm(2, { digits: 3 })": "2 ppm",
            "fmtPpm(0.5, { signed: true })": "+0,5 ppm",
            "fmtPpm(-3.25, { signed: true, digits: 1 })": "−3,3 ppm",
            "fmtPpm(NaN)": "–",
            "fmtNumber(1234.5, 2)": "1.234,5",
            "fmtNumber(6, 1)": "6",
            "fmtNumber(-0.0001, 2)": "0",
            "fmtNumber(12.3456, 0, { sig: 2 })": "12",
            "fmtNumber(5, 0, { signed: true })": "+5",
            "fmtFixed(1, 3)": "1,000",
            "fmtRate(6)": "6",
            "fmtRate(4.25)": "4,3",
        }
        out = self.fmt(cases)
        for expr, expected in cases.items():
            with self.subTest(expr=expr):
                self.assertEqual(out[expr], expected)

    def test_fmt_date_iso_und_unix(self):
        cases = {
            "fmtDate(1783000000)": "02.07.26, 15:46",
            "fmtDate(1783000000, { time: 'medium' })": "02.07.26, 15:46:40",
            "fmtDate(1783000000, { date: 'numeric' })": "02.07.2026, 15:46",
            "fmtDate(1783000000, { date: 'day' })": "02.07., 15:46",
            "fmtDate(1783000000, { time: false })": "02.07.26",
            "fmtDate(1783000000, { utc: true })": "02.07.26, 13:46",
            "fmtDate(1783000000, { zone: 3600 })": "02.07.26, 14:46",
            "fmtDate('2026-11-08', { date: 'long' })": "8. November 2026",
            "fmtDate('2026-11-08T12:34:56Z', { time: 'medium', utc: true })": "08.11.26, 12:34:56",
            "fmtDate(new Date(1783000000000))": "02.07.26, 15:46",
            "fmtDate('kaputt')": "–",
            "fmtDate(null, { empty: 'nie' })": "nie",
            "fmtIsoUtc('2026-11-08T12:34:56.000Z')": "08.11.26, 12:34:56 UTC",
        }
        out = self.fmt(cases)
        for expr, expected in cases.items():
            with self.subTest(expr=expr):
                self.assertEqual(out[expr], expected)

    def test_englisch_mit_punkt(self):
        cases = {
            "fmtSeconds(0.0015)": "1.5 ms",
            "fmtNumber(1234.5, 1)": "1,234.5",
            "fmtPpm(-0.25)": "−0.25 ppm",
            "fmtDate('2026-11-08', { date: 'long' })": "8 November 2026",
        }
        out = self.fmt(cases, lang="en")
        for expr, expected in cases.items():
            with self.subTest(expr=expr):
                self.assertEqual(out[expr], expected)

    def test_kein_tausend_ms_ueber_alle_groessenordnungen(self):
        """Akzeptanzkriterium: kein „\\d,000 “ und kein „\\d.\\d+ (s|ms)“ im Deutschen – für jede Größe."""
        out = self.run_js(f"""
const util = await import({mod("util.js")});
const values = [];
for (let e = -10; e <= 6; e += 1) for (const m of [1, 1.0004, 1.5, 2, 2.5, 3.33333, 5, 9.9996, 10, 12.5]) {{
  values.push(m * 10 ** e, -m * 10 ** e);
}}
const out = [];
for (const v of values) {{
  out.push(util.fmtSeconds(v), util.fmtSeconds(v, 3, true), `± ${{util.fmtSeconds(Math.abs(v))}}`, util.fmtDuration(Math.abs(v)),
    util.fmtPpm(v), util.fmtPpm(v, {{ digits: 3 }}), util.fmtRate(Math.abs(v)), util.fmtNs(v * 1e9));
}}
console.log(JSON.stringify(out));
""")
        bad = [text for text in out if FORBIDDEN_DE.search(text) or TRAILING_ZERO.search(text)]
        self.assertEqual(bad, [])


# Testdaten für gerenderte Seiten: Werte, die früher „1,000 ms“, „14,000 ms“ oder „6,0“ ergaben.
STATUS = """{
  system: { time: 1783000000, tz_name: "Europe/Berlin", utc_offset: 7200, refresh_seconds: 5 },
  chrony_running: true,
  tracking: { system_time_offset: 0.001, rms_offset: 0.014, root_delay: 0.002, root_dispersion: 0.0005,
    frequency_ppm: -12.5, skew_ppm: 0.05, residual_freq_ppm: 0.001, update_interval: 64, ref_time: 1782999990,
    leap_status: "Normal", stratum: 2, ref_name: "ptbtime1.ptb.de", ref_id: "C0A80001" },
  sources: [
    { name: "192.0.2.1", hostname: "ptbtime1.ptb.de", state: "*", select_state: "best", mode: "server", stratum: 1, poll: 6,
      reach: 255, last_rx: 12, offset: 0.001, error: 0.014, jitter: 0.0005, interval: 0.002 },
    { name: "GPS", hostname: "GPS", state: "+", select_state: "combined", mode: "refclock", stratum: 0, poll: 4,
      reach: 255, last_rx: 3, offset: -0.00042, error: 0.001, jitter: 0.0001, interval: 0.001 },
  ],
  serverstats: { ntp_packets_received: 1200 }, clients: [], insights: [], services: {},
  gps: { enabled: false }, ptp: { enabled: false },
}"""

HISTORY = """(() => {
  const out = [];
  for (let i = 0; i < 60; i += 1) out.push({ t: 1783000000 - (59 - i) * 60, offset: 0.001 * Math.sin(i / 5),
    root_delay: 0.00064, root_dispersion: 0.0001, stratum: 2,
    freq: -12.5, served: 1000 + i * 6, sources: { "192.0.2.1": { o: 0.001 }, GPS: { o: -0.00042 } } });
  return out;
})()"""


class SeitenTest(NodeTest):
    def test_gerenderte_seiten_ohne_tausend_ms(self):
        out = self.run_js(f"""
globalThis.getComputedStyle = () => ({{ getPropertyValue: () => "" }});
const status = {STATUS};
const history = {HISTORY};
const pages = {{ overview: await import({mod("pages/overview.js")}), sources: await import({mod("pages/sources.js")}),
  muster: await import({mod("pages/muster.js")}) }};
const res = {{}};
for (const [name, page] of Object.entries(pages)) res[name] = text(page.render(ctx({{ status, history }})));
console.log(JSON.stringify(res));
""")
        for name, page_text in out.items():
            with self.subTest(page=name):
                self.assertTrue(page_text)
                self.assertIsNone(FORBIDDEN_DE.search(page_text), FORBIDDEN_DE.search(page_text))
                self.assertIsNone(TRAILING_ZERO.search(page_text), TRAILING_ZERO.search(page_text))
        self.assertIn("± 1 ms", out["muster"].replace("± ", "± "))
        self.assertIn("1 ms", out["overview"])          # Abweichung 0,001 s
        self.assertIn("14 ms", out["overview"])         # RMS
        # Konstanter maximaler Fehler: eine Zeile statt eines leeren Diagramms.
        self.assertIn("stabil um ± 420 µs", out["overview"])


class BausteinTest(NodeTest):
    def test_stat_card_kv_row_info(self):
        out = self.run_js(f"""
const ui = await import({mod("ui.js")});
const card = ui.statCard({{ label: "Abweichung", value: "1 ms", help: "system_offset", tone: "good" }});
const row = ui.kvRow("Root Delay", "2 ms", "root_delay");
const button = ui.infoButton("system_offset", "Abweichung");
console.log(JSON.stringify({{
  card: text(card), tone: card.getAttribute("data-tone"), cardInfo: withAttr(card, "class", "info").filter((n) => n.attrs.class === "info").length,
  row: text(row), rowInfo: withAttr(row, "class", "info").filter((n) => n.attrs.class === "info").length,
  glyph: withAttr(button, "class", "info-glyph").length, label: button.getAttribute("aria-label"),
  unknown: ui.infoButton("gibt_es_nicht"), alias: ui.info === ui.infoButton && ui.tile === ui.statCard && ui.emptyNote === ui.emptyState,
}}));
""")
        self.assertIn("Abweichung", out["card"])
        self.assertIn("1 ms", out["card"])
        self.assertEqual(out["tone"], "good")
        self.assertEqual(out["cardInfo"], 1)
        self.assertEqual(out["rowInfo"], 1)
        self.assertIn("2 ms", out["row"])
        self.assertEqual(out["glyph"], 1)
        self.assertEqual(out["label"], "Erklärung: Abweichung")
        self.assertIsNone(out["unknown"])
        self.assertTrue(out["alias"])

    def test_range_picker_minuten_bis_tage(self):
        out = self.run_js(f"""
const ui = await import({mod("ui.js")});
const picker = ui.rangePicker({{ value: 3600, onChange() {{}}, options: [900, 3600, 86400, 7 * 86400, 30 * 86400, [86400 * 2, "2 T."]] }});
const buttons = picker.childNodes;
console.log(JSON.stringify({{ labels: buttons.map((b) => b.textContent), pressed: buttons.map((b) => b.getAttribute("aria-pressed")),
  role: picker.getAttribute("role"), live: ui.rangeButtons(900, () => {{}}).childNodes.map((b) => b.textContent) }}));
""")
        self.assertEqual(out["labels"], ["15 min", "1 h", "24 h", "7 Tage", "30 Tage", "2 T."])
        self.assertEqual(out["pressed"], ["false", "true", "false", "false", "false", "false"])
        self.assertEqual(out["role"], "group")
        self.assertEqual(out["live"], ["15 min", "1 h", "6 h", "24 h"])

    def test_empty_und_error_state(self):
        out = self.run_js(f"""
const ui = await import({mod("ui.js")});
const failing = {{ dataError: () => ({{ status: 500, message: "HTTP 500" }}) }};
console.log(JSON.stringify({{
  empty: text(ui.emptyState("Noch **nichts** da")),
  error: text(ui.errorState({{ status: 404 }}, "die Daten")),
  errorClass: ui.errorState({{ message: "weg" }}, "x").getAttribute("class"),
  loading: text(ui.loadingOr({{}}, "k", "/u", "die Liste")),
  failed: text(ui.loadingOr(failing, "k", "/u", "die Liste")),
}}));
""")
        self.assertEqual(out["empty"], "Noch nichts da")
        self.assertEqual(out["error"], "Konnte die Daten nicht laden (HTTP 404) – neuer Versuch läuft.")
        self.assertIn("is-error", out["errorClass"])
        self.assertEqual(out["loading"], "Lade die Liste …")
        self.assertEqual(out["failed"], "Konnte die Liste nicht laden (HTTP 500) – neuer Versuch läuft.")

    def test_chart_card_klappt_flach_und_leer_zusammen(self):
        out = self.run_js(f"""
const ui = await import({mod("ui.js")});
const util = await import({mod("util.js")});
const drawn = [];
const c = ctx();
c.afterRender = (fn) => fn();
const pts = (fn) => Array.from({{ length: 30 }}, (_, i) => [1783000000 + i * 60, fn(i)]);
const make = (title, points, extra = {{}}) => ui.chartCard(c, {{ title, help: "uncertainty", key: title, series: [{{ points }}],
  format: (v) => `± ${{util.fmtSeconds(v)}}`, zone: 7200, draw: () => drawn.push(title), ...extra }});
const flat = make("Maximaler Fehler", pts((i) => 0.00042 + (i % 2) * 4e-8));
const empty = make("Satelliten im Verlauf", [], {{ since: 1783000000 - 1800 }});
const none = make("Leer ohne Beginn", []);
const moving = make("Bewegt", pts((i) => 0.0004 * Math.sin(i)));
const never = make("Nie flach", pts(() => 1), {{ flat: false }});
// Aufklappen: Knopf merkt sich den Schlüssel, danach steht das Diagramm da.
c.uiState.chartOpen.add("Maximaler Fehler");
const opened = make("Maximaler Fehler", pts(() => 0.00042));
console.log(JSON.stringify({{ flat: text(flat), flatShape: flat.getAttribute("data-shape"), empty: text(empty), none: text(none),
  moving: moving.getAttribute("data-shape"), drawn, opened: text(opened), never: never.getAttribute("data-shape"),
  flatClass: flat.getAttribute("class"), help: withAttr(flat, "class", "info").filter((n) => n.attrs.class === "info").length }}));
""")
        self.assertIn("Maximaler Fehler", out["flat"])
        self.assertIn("stabil um ± 420 µs", out["flat"])
        self.assertIn("Diagramm zeigen", out["flat"])
        self.assertEqual(out["flatShape"], "flat")
        self.assertIn("is-collapsed", out["flatClass"])
        self.assertEqual(out["help"], 1)
        self.assertIn("Satelliten im Verlauf", out["empty"])
        self.assertIn("sammelt seit 15:16", out["empty"])   # 30 min vor 15:46 (UTC+2)
        self.assertIn("noch keine Messwerte", out["none"])
        self.assertIsNone(out["moving"])          # normale Karte, kein data-shape
        self.assertIsNone(out["never"])
        self.assertEqual(out["drawn"], ["Bewegt", "Nie flach", "Maximaler Fehler"])
        self.assertIn("Einklappen", out["opened"])


class NachbesserungTest(NodeTest):
    """Prüfbefunde zu T2a: Pendeln um 0, Lücken, Leerzustand mit Datum, Vorzeichen, Gruppierung."""

    def card_text(self, body: str):
        return self.run_js(f"""
const ui = await import({mod("ui.js")});
const util = await import({mod("util.js")});
const c = ctx();
c.afterRender = () => {{}};
const T0 = 1783000000;
const card = (opts) => ui.chartCard(c, {{ title: "Karte", key: opts.title || "Karte", draw: () => {{}}, ...opts }});
const out = {{}};
{body}
console.log(JSON.stringify(out));
""")

    def test_pendeln_um_null_zeigt_betrag_statt_mittel(self):
        out = self.card_text("""
const pts = Array.from({ length: 30 }, (_, i) => [T0 - 1740 + i * 60, i % 2 ? -3.9e-7 : 4e-7]);
const node = card({ title: "Abweichung", series: [{ points: pts }], flatAbs: 1e-6, format: (x) => util.fmtSeconds(x, 3, true) });
out.text = text(node);
out.shape = node.getAttribute("data-shape");
// Kleiner Mittelwert gegenüber der Spannweite (ohne Vorzeichenwechsel) gilt ebenso als Pendeln.
const pos = Array.from({ length: 30 }, (_, i) => [T0 - 1740 + i * 60, i % 2 ? 1e-9 : 6e-7]);
out.pos = text(card({ title: "Positiv", series: [{ points: pos }], flatAbs: 1e-6, format: (x) => `± ${util.fmtSeconds(x)}` }));
""")
        self.assertEqual(out["shape"], "flat")
        self.assertIn("stabil innerhalb ± 400 ns", out["text"])
        self.assertNotIn("stabil um", out["text"])
        self.assertIn("stabil innerhalb ± 600 ns", out["pos"])

    def test_flach_nur_ohne_luecken(self):
        out = self.card_text("""
const gap = [[T0 - 86400, 0.00042], ...Array.from({ length: 500 }, (_, i) => [T0 - 86000 + i * 170, null]), [T0, 0.00042]];
out.gap = ui.seriesShape([{ points: gap }]).kind;
out.gapText = text(card({ title: "Lücke", series: [{ points: gap }], format: (v) => `± ${util.fmtSeconds(v)}` }));
// Lücke mitten in sonst dichten Daten (2 h von 24 h, Abstand 60 s).
const mid = Array.from({ length: 1441 }, (_, i) => [T0 - 86400 + i * 60, i > 600 && i < 720 ? null : 0.00042]);
out.mid = ui.seriesShape([{ points: mid }]).kind;
// Zu wenige gültige Punkte: nicht flach.
out.few = ui.seriesShape([{ points: [[T0 - 120, 1], [T0 - 60, 1], [T0, 1]] }]).kind;
// Dicht und gleichmäßig: flach.
const dense = Array.from({ length: 30 }, (_, i) => [T0 - 1740 + i * 60, 0.00042]);
out.dense = ui.seriesShape([{ points: dense }]).kind;
""")
        self.assertNotEqual(out["gap"], "flat")
        self.assertNotIn("stabil", out["gapText"])
        self.assertNotEqual(out["mid"], "flat")
        self.assertNotEqual(out["few"], "flat")
        self.assertEqual(out["dense"], "flat")

    def test_leerzustand_mit_datum_und_keine_messwerte(self):
        out = self.card_text("""
const nulls = Array.from({ length: 300 }, (_, i) => [T0 - 82800 + i * 276, null]);
out.old = text(card({ title: "Satelliten", series: [{ points: nulls }], since: T0 - 82800, zone: 7200 }));
out.oldNoData = text(card({ title: "Alt", series: [{ points: [] }], since: T0 - 82800, zone: 7200 }));
out.recent = text(card({ title: "Neu", series: [{ points: [] }], since: T0 - 1800, zone: 7200 }));
out.recentNulls = text(card({ title: "Neu leer", series: [{ points: [[T0 - 1800, null], [T0, null]] }], zone: 7200 }));
// Anderer Kalendertag, aber unter 12 h: auch mit Datum (T0 = 02.07. 15:46 in UTC+2, jetzt 03.07. 01:46).
out.yesterday = text(card({ title: "Gestern", series: [{ points: [] }], since: T0, now: T0 + 36000, zone: 7200 }));
""")
        self.assertIn("keine Messwerte seit 01.07.", out["old"])
        self.assertNotIn("sammelt", out["old"])
        self.assertIn("sammelt seit 01.07.", out["oldNoData"])
        self.assertRegex(out["recent"], r"sammelt seit \d\d:\d\d$")
        self.assertRegex(out["recentNulls"], r"keine Messwerte seit \d\d:\d\d$")
        self.assertIn("sammelt seit 02.07.", out["yesterday"])

    def test_vorzeichen_einheitlich(self):
        out = self.run_js(f"""
const util = await import({mod("util.js")});
const i18n = await import({mod("i18n.js")});
i18n._setCatalogs({{ de: {{}}, en: {{}} }}, "de");
const {{ fmtSeconds, fmtNs, fmtPpm, fmtNumber }} = util;
console.log(JSON.stringify({{
  tiny: fmtSeconds(4e-12, 3, true), ns: fmtNs(0.004), neg: fmtSeconds(-0.0042, 3, true), negPlain: fmtSeconds(-0.0042),
  pos: fmtSeconds(0.0042, 3, true), ppm: fmtPpm(-12.345), ppmSigned: fmtPpm(-0.5, {{ signed: true }}), num: fmtNumber(-5),
  fixed: util.fmtFixed(-1.5, 2) }}));
""")
        self.assertEqual(out["tiny"], "0 ns")
        self.assertEqual(out["ns"], "0 ns")
        self.assertEqual(out["neg"], "−4,2 ms")
        self.assertEqual(out["negPlain"], "−4,2 ms")
        self.assertEqual(out["pos"], "+4,2 ms")
        self.assertEqual(out["ppm"], "−12,3 ppm")
        self.assertEqual(out["ppmSigned"], "−0,5 ppm")
        self.assertEqual(out["num"], "−5")
        self.assertEqual(out["fixed"], "−1,50")
        # Kein ASCII-Minus mehr in Werten: einheitlich U+2212.
        self.assertFalse(any(v.startswith("-") for v in out.values()))

    def test_werte_mit_einheit_ohne_tausendergruppe(self):
        out = self.run_js(f"""
const util = await import({mod("util.js")});
const i18n = await import({mod("i18n.js")});
i18n._setCatalogs({{ de: {{}}, en: {{}} }}, "de");
console.log(JSON.stringify({{ ppm: util.fmtPpm(1234.5), ppmEn: (i18n._setCatalogs({{ de: {{}}, en: {{}} }}, "en"), util.fmtPpm(-1234.5)),
  plain: (i18n._setCatalogs({{ de: {{}}, en: {{}} }}, "de"), util.fmtNumber(12345)) }}));
""")
        self.assertEqual(out["ppm"], "1235 ppm")
        self.assertEqual(out["ppmEn"], "−1235 ppm")
        self.assertEqual(out["plain"], "12.345")   # ohne Einheit bleibt die Gruppierung


class LintTest(unittest.TestCase):
    def test_kein_tofixed_in_seiten(self):
        found = [f"{p.name}:{n}" for p in PAGES for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if "toFixed" in line]
        self.assertEqual(found, [], "Zahlen auf Seiten über fmt* aus util.js – toFixed ist verboten")

    def test_keine_eigenen_locale_formate_in_seiten(self):
        """Datum und Zahl laufen über fmtDate/fmtNumber (gewählte Sprache) statt toLocale*("de-DE")."""
        pattern = re.compile(r"\.toLocale(?:Date|Time)?String\(|\"de-DE\"|new Intl\.")
        found = [f"{p.name}:{n}" for p in PAGES for n, line in code_lines(p) if pattern.search(line)]
        self.assertEqual(found, [])

    def test_feste_nachkommastellen_nur_an_achsen(self):
        """fmtFixed (mit Nullen am Ende) nur in Achsenbeschriftungen, sonst fmtNumber/fmtSeconds/fmtPpm."""
        found = []
        for path in PAGES:
            function = None
            for number, line in code_lines(path):
                match = re.match(r"(?:export\s+)?function\s+(\w+)", line)
                if match:
                    function = match.group(1)
                if "fmtFixed(" in line and not re.search(r"axis", line, re.I) and not re.search(r"axis", function or "", re.I):
                    found.append(f"{path.name}:{number}")
        self.assertEqual(found, [])

    def test_keine_lokalen_doppel_der_fmt_helfer(self):
        """fmtPpm und fmtDate gibt es nur in util.js – Seiten bauen keine eigenen daneben."""
        found = [f"{p.name}:{n}" for p in PAGES for n, line in code_lines(p)
                 if re.search(r"(?:function|const)\s+(?:fmtPpm|fmtDate|fmtDuration|fmtNumber|fmtSeconds)\b", line)]
        self.assertEqual(found, [])

    def test_info_button_tippflaeche_und_blass(self):
        rules = dict((sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS))
        info = rules[".info"]
        self.assertRegex(info, r"width:\s*14px")
        self.assertRegex(info, r"height:\s*14px")
        self.assertRegex(info, r"background:\s*transparent")
        after = rules[".info::after"]
        inset = int(re.search(r"inset:\s*-(\d+)px", after).group(1))
        self.assertGreaterEqual(14 + 2 * inset, 24, "Tippfläche des ⓘ mindestens 24 px (WCAG 2.2, 2.5.8)")
        self.assertLessEqual(14 + 2 * inset, 24, "größer als 24 px überdeckt Nachbarn (Klick auf deren Rand öffnet das ⓘ)")
        hover = next(body for sel, body in rules.items() if ".info:hover" in sel)
        self.assertIn(".info:focus-visible", next(sel for sel in rules if ".info:hover" in sel))
        self.assertIn("background", hover)

    def test_einheiten_ohne_tausendergruppe_in_seiten(self):
        """„12.345 ppb“ läse sich wie 12 ppb: Zahlen direkt vor ppm/ppb/ns/µs/ms/s mit group: false."""
        pattern = re.compile(r"fmtNumber\((?:[^()]|\([^()]*\))*\)\}\s?(?:ppm|ppb|ns|µs|ms|s)\b")
        found = []
        for path in PAGES:
            for number, line in code_lines(path):
                for match in pattern.finditer(line):
                    if "group: false" not in match.group(0):
                        found.append(f"{path.name}:{number}")
        self.assertEqual(found, [])

    def test_musterseite_nur_mit_dev(self):
        app = (JS / "app.js").read_text(encoding="utf-8")
        self.assertRegex(app, r'id: "muster".*dev: true')
        self.assertIn('get("dev") === "1"', app)
        self.assertIn("PAGES.filter((page) => !page.dev)", app)
        self.assertIn("(!p.dev || devMode())", app)

    def test_keine_inline_styles(self):
        """Strenge CSP (style-src 'self'): keine style-Attribute im HTML und kein setAttribute("style")."""
        for path in [*PAGES, JS / "ui.js", JS / "util.js"]:
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotRegex(text, r"setAttribute\(\s*[\"']style[\"']")
                self.assertNotIn("innerHTML", text)


if __name__ == "__main__":
    unittest.main()
