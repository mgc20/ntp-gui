"""Zustände des Dashboards im echten JS-Interpreter (1.6, T1 „Frontend-Zustand und Sprache“).

Die Seiten werden mit einem winzigen DOM-Ersatz gerendert (createElement/append/textContent) – ohne
Browser, ohne Bibliothek. Geprüft wird, was der Betrachter liest:

  F1  Kopfzeile, Fußzeile und Ereignisse zeigen die Uhrzeit des Servers, nicht die des Browsers.
  F2  Verbindungsverlust: „veraltet seit hh:mm:ss“, sofort neu abfragen bei online/visibilitychange.
  F3  Nach einem Fehler steht nicht endlos „Lade …“ da, sondern dass es nicht ging.
  K4  Gruppen-Karte widerspricht nicht der Client-Liste („Noch keine Geräte gesehen“).
  U6  „Anfragen/min“ springt nicht zwischen 6 und 0, sondern ist das Mittel der letzten Minute.
  U8  Zeitraum-Knöpfe der Uhrqualität sitzen in der Temperaturkarte und nur mit Sensor.

Nachbesserung: Zeiten mit IANA-Zeitzone (sommerzeitrichtig, auch im Ereignisprotokoll der Diagnose),
Kacheln der Detailseite bei Geräten, die nur chrony kennt, ehrliche Notiz zum Mittelungsfenster.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

DOM = r"""
class Node { constructor() { this.childNodes = []; }
  append(...c) { for (const x of c) this.childNodes.push(typeof x === "string" ? new Text(x) : x); }
  appendChild(x) { this.append(x); return x; }
  get textContent() { return this._text ?? this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this._text = String(v); this.childNodes = []; }
  replaceChildren(...c) { this.childNodes = []; this._text = undefined; this.append(...c); } }
class Text extends Node { constructor(t) { super(); this._text = t; } }
class Element extends Node { constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.attrs = {}; this.dataset = {};
  this.style = { setProperty() {}, removeProperty() {} };
  this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } }; }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener() {} querySelector() { return null; } querySelectorAll() { return []; } closest() { return null; } }
globalThis.Node = Node; globalThis.Element = Element; globalThis.HTMLElement = Element;
globalThis.document = { createElement: (t) => new Element(t), createElementNS: (n, t) => new Element(t),
  createTextNode: (t) => new Text(String(t)), getElementById: () => null, addEventListener() {}, querySelector: () => null,
  body: new Element("body"), documentElement: new Element("html") };
globalThis.window = { location: { hash: "" }, addEventListener() {}, matchMedia: () => ({ matches: false }), innerWidth: 1200,
  localStorage: { getItem: () => null, setItem() {} } };
globalThis.localStorage = window.localStorage; globalThis.requestAnimationFrame = () => 0;
export function text(nodes) { return [].concat(nodes).filter(Boolean).map((n) => n.textContent).join(" | "); }
// Alle Elemente (auch verschachtelt), deren Attribut name mit prefix beginnt.
export function withAttr(nodes, name, prefix) {
  const out = [];
  const walk = (n) => { if (!n) return; if (n.attrs && String(n.attrs[name] ?? "").startsWith(prefix)) out.push(n);
    for (const c of n.childNodes || []) walk(c); };
  [].concat(nodes).forEach(walk);
  return out;
}
export function ctx(extra = {}) {
  return { status: { system: { time: 1783000000 }, tracking: {}, clients: [], serverstats: {} }, history: [], range: 3600,
    uiState: {}, subpath: "", readonly: false, data: () => undefined, dataError: () => null, invalidate() {},
    afterRender() {}, rerender() {}, refresh() {}, setRange() {}, ...extra };
}
"""


def mod(path: str) -> str:
    return json.dumps((JS / path).resolve().as_uri())


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class NodeTest(unittest.TestCase):
    def run_js(self, body: str, tz: str = "UTC"):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dom.mjs").write_text(DOM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            script.write_text('import { text, withAttr, ctx } from "./dom.mjs";\n' + body, encoding="utf-8")
            env = {**os.environ, "TZ": tz}
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    # --- F1 ---------------------------------------------------------------------------------
    def test_header_shows_server_time_not_browser_time(self):
        out = self.run_js(f"""
const util = await import({mod("util.js")});
const ov = await import({mod("pages/overview.js")});
console.log(JSON.stringify({{
  header: util.fmtServerDateTime({{ time: 1783000000, utc_offset: 7200, timezone: "CEST" }}),
  footer: util.fmtTime(1783000000, true, 7200),
  event: ov.eventTime(1783000000, {{ time: 1783000100, utc_offset: 7200 }}),
  older: ov.eventTime(1783000000 - 86400, {{ time: 1783000100, utc_offset: 7200 }}),
}}));
""", tz="America/New_York")
        self.assertEqual(out["header"], "2.7.2026, 15:46:40")   # Browser in New York: früher 09:46:40
        self.assertEqual(out["footer"], "15:46:40")
        self.assertEqual(out["event"], "15:46")
        self.assertEqual(out["older"], "01.07. 15:46")

    # --- F2 ---------------------------------------------------------------------------------
    def test_stale_text_names_the_time(self):
        out = self.run_js(f"""
const util = await import({mod("util.js")});
console.log(JSON.stringify({{ a: util.staleText(Date.UTC(2026, 10, 8, 12, 0, 5)), b: util.staleText(null) }}));
""")
        self.assertIn("veraltet seit", out["a"])
        self.assertIn("12:00:05", out["a"])
        self.assertIn("veraltet", out["b"])

    # --- F3 ---------------------------------------------------------------------------------
    def test_error_replaces_endless_loading(self):
        out = self.run_js(f"""
const pages = {{ clients: await import({mod("pages/clients.js")}), clockquality: await import({mod("pages/clockquality.js")}),
  overview: await import({mod("pages/overview.js")}) }};
const err = {{ status: 500, message: "HTTP 500" }};
const res = {{}};
for (const [name, page] of Object.entries(pages)) {{
  res[name] = {{ failed: text(page.render(ctx({{ dataError: () => err }}))), loading: text(page.render(ctx())) }};
}}
console.log(JSON.stringify(res));
""")
        for name, texts in out.items():
            with self.subTest(page=name):
                self.assertNotRegex(texts["failed"], r"Lade [^|]*…|lädt …")
                self.assertIn("nicht laden", texts["failed"])
                self.assertIn("HTTP 500", texts["failed"])
                self.assertIn("Lade ", texts["loading"])  # ohne Fehler: weiter der Ladezustand

    # --- K4 ---------------------------------------------------------------------------------
    def test_groups_card_does_not_contradict_client_list(self):
        out = self.run_js(f"""
const clients = await import({mod("pages/clients.js")});
const D = {{ clientgroups: {{ by: "group", groups: [], total: 0, defined: [], suggestions: [] }},
  clientoverview: {{ histogram: [], total: 0 }}, clientquality: {{ scores: {{}}, worst: [], rated: 0 }}, clientoffsets: {{ clients: {{}} }} }};
const status = {{ system: {{ time: 1783000000 }}, serverstats: {{}},
  clients: [{{ address: "192.0.2.10", ntp_packets: 50, ntp_last_rx: 3 }}, {{ address: "192.0.2.11", ntp_packets: 9, ntp_last_rx: 8 }}] }};
const withChrony = text(clients.render(ctx({{ status, data: (k) => D[k] }})));
const empty = text(clients.render(ctx({{ data: (k) => D[k] }})));
console.log(JSON.stringify({{ withChrony, empty }}));
""")
        self.assertIn("192.0.2.10", out["withChrony"])
        self.assertNotIn("Noch keine Geräte gesehen", out["withChrony"])
        self.assertIn("chrony kennt 2 Geräte", out["withChrony"])
        self.assertIn("Noch keine Geräte gesehen", out["empty"])

    # --- U6 ---------------------------------------------------------------------------------
    def test_request_rate_is_mean_of_last_minute(self):
        out = self.run_js(f"""
const ov = await import({mod("pages/overview.js")});
// 10-s-Messintervall, ein Gerät fragt alle 20 s (wahr: 3/min) -> served steigt abwechselnd um 1 und 0.
const s = []; let served = 1000;
for (let i = 0; i < 12; i++) {{ s.push({{ t: 1000 + i * 10, served }}); if (i % 2 === 0) served += 1; }}
const later = s.concat({{ t: 1120, served }});
// Zählerrücksprung (chronyd neu gestartet): nur die Zeit danach zählt.
const reset = s.concat({{ t: 1120, served: 0 }}, {{ t: 1130, served: 1 }}, {{ t: 1140, served: 1 }});
// Langer Zeitraum: Punkte 144 s auseinander -> letztes Intervall.
const sparse = [{{ t: 0, served: 0 }}, {{ t: 144, served: 12 }}, {{ t: 288, served: 24 }}];
console.log(JSON.stringify({{ a: ov.recentRate(s), b: ov.recentRate(later), reset: ov.recentRate(reset),
  sparse: ov.recentRate(sparse), none: ov.recentRate([{{ t: 1, served: 1 }}]),
  old: [ov.requestRate(s).at(-1)[1], ov.requestRate(later).at(-1)[1]] }}));
""")
        for key in ("a", "b"):
            self.assertGreaterEqual(out[key], 2.5, key)
            self.assertLessEqual(out[key], 3.5, key)
        self.assertEqual(out["old"], [6, 0])     # so sprang der alte Wert
        self.assertAlmostEqual(out["reset"], 3.0)  # 1 Anfrage in 20 s nach dem Rücksprung
        self.assertAlmostEqual(out["sparse"], 5.0)
        self.assertIsNone(out["none"])

    def test_both_pages_use_recent_rate(self):
        clients = (JS / "pages" / "clients.js").read_text(encoding="utf-8")
        overview = (JS / "pages" / "overview.js").read_text(encoding="utf-8")
        self.assertIn("recentRateInfo(history)", clients)
        self.assertNotIn("rate[rate.length - 1]", clients)
        self.assertIn("recentRate(history)", overview)

    # --- 1.6.1: ausgeklappte Infos wie Warnungen ------------------------------------------------
    def test_expanded_infos_use_compact_hint_rows(self):
        # Infos (ausgeklappt) sind dieselben kompakten Zeilen wie die Warnungen – keine größeren Karten
        # (.insight) mit Link und Knopf je in eigener Zeile. Der „Beheben“-Knopf steht bei den Aktionen rechts.
        out = self.run_js(f"""
const ov = await import({mod("pages/overview.js")});
const items = [
  {{ level: "warn", key: "storage", title: "Volume fehlt", text: "Kein Volume." }},
  {{ level: "info", key: "no_auth", action: "settings", title: "Dashboard ohne Passwort", text: "Jeder im LAN kann ändern." }},
  {{ level: "info", key: "web_proxy_untrusted", action: "settings", title: "Proxy nicht eingetragen", text: "Trag ihn ein.",
    fixes: [{{ kind: "trust_proxy", id: "0123456789abcdef", label: "Als vertrauenswürdigen Proxy eintragen (192.0.2.10/32)" }}] }},
  {{ level: "ok", key: "gps_used", title: "GPS wird genutzt", text: "Das GPS fließt ein." }},
];
const c = ctx({{ uiState: {{ overviewHintsOpen: true }} }});
const block = ov.hintsBlock(c, items);
const rows = withAttr(block, "class", "hint-row");
const actions = withAttr(block, "class", "hint-actions");
const proxyRow = rows.find((r) => text(r).includes("Proxy nicht eingetragen"));
console.log(JSON.stringify({{
  rows: rows.map((r) => r.attrs["data-level"]),
  cards: withAttr(block, "class", "insight").filter((n) => /^insight( |$)/.test(n.attrs.class)).length,
  lists: withAttr(block, "class", "hint-list").length,
  fixInActions: withAttr(withAttr(proxyRow, "class", "hint-actions"), "class", "insight-fixes").length,
  fixInMain: withAttr(withAttr(proxyRow, "class", "hint-main"), "class", "insight-fixes").length,
  linkInActions: actions.map((a) => withAttr(a, "class", "insight-action").length),
}}));
""")
        self.assertEqual(out["rows"], ["warn", "info", "info", "ok"])
        self.assertEqual(out["cards"], 0)
        self.assertEqual(out["lists"], 2)
        self.assertEqual((out["fixInActions"], out["fixInMain"]), (1, 0))
        self.assertEqual(out["linkInActions"], [0, 1, 1, 0])

    # --- F1 Nachbesserung: IANA-Zeitzone -------------------------------------------------------
    def test_event_times_follow_dst_of_their_day(self):
        # Ereignis am 24.10.2026 12:00 UTC (noch Sommerzeit in Berlin), angezeigt am 08.11.2026 (Winterzeit).
        out = self.run_js(f"""
const util = await import({mod("util.js")});
const ov = await import({mod("pages/overview.js")});
const sys = {{ time: 1794139200, utc_offset: 3600, tz_name: "Europe/Berlin", timezone: "CET" }};
console.log(JSON.stringify({{
  event: ov.eventTime(1792843200, sys),
  offsetOnly: ov.eventTime(1792843200, {{ time: 1794139200, utc_offset: 3600 }}),
  unknownZone: ov.eventTime(1792843200, {{ ...sys, tz_name: "Nirgendwo/Gibtsnicht" }}),
  header: util.fmtServerDateTime(sys),
  footer: util.fmtTime(1792843200, true, sys),
  stale: util.staleText(1792843200 * 1000, sys),
}}));
""", tz="America/New_York")
        self.assertEqual(out["event"], "24.10. 14:00")        # CEST, nicht 13:00 mit dem heutigen Offset
        self.assertEqual(out["offsetOnly"], "24.10. 13:00")   # Rückfall ohne tz_name: nur utc_offset
        self.assertEqual(out["unknownZone"], "24.10. 13:00")  # Name, den Intl nicht kennt: Rückfall
        self.assertEqual(out["header"], "8.11.2026, 13:00:00")
        self.assertEqual(out["footer"], "14:00:00")
        self.assertIn("14:00:00", out["stale"])

    def test_diagnose_event_log_uses_server_zone(self):
        out = self.run_js(f"""
const diag = await import({mod("pages/diagnose.js")});
const sys = {{ time: 1783000100, utc_offset: 7200, tz_name: "Europe/Berlin" }};
console.log(JSON.stringify({{
  dt: diag.fmtDateTime(1783000000, sys),
  offsetOnly: diag.fmtDateTime(1783000000, {{ utc_offset: 7200 }}),
  row: diag.eventRow({{ t: 1783000000, level: "info", kind: "service", title: "x" }}, sys).textContent,
}}));
""", tz="America/New_York")
        self.assertEqual(out["dt"], "02.07., 15:46:40")      # Browser in New York zeigte 09:46:40
        self.assertEqual(out["offsetOnly"], "02.07., 15:46:40")
        self.assertIn("15:46:40", out["row"])

    # --- U4 Nachbesserung: Kacheln der Detailseite ----------------------------------------------
    def test_detail_tiles_use_chrony_when_own_measurement_is_empty(self):
        out = self.run_js(f"""
const cd = await import({mod("pages/clientdetail.js")});
const detail = {{ address: "192.0.2.77", entry: {{}}, samples: [], measurable_reason: "",
  chrony: {{ ntp_packets: 50, ntp_dropped: 0, ntp_interval: 6, ntp_last_rx: 3 }} }};
const own = {{ address: "192.0.2.78", entry: {{ requests: 7, last_seen: Date.now() / 1000 - 5, state_text: "messbar" }}, samples: [],
  chrony: {{ ntp_packets: 50, ntp_last_rx: 3 }} }};
const render = (d) => text(cd.renderDetail(ctx({{ data: () => d }}), d.address));
console.log(JSON.stringify({{ only: render(detail), own: render(own) }}));
""")
        self.assertNotRegex(out["only"], r"(?<![\d.])0 Anfragen")
        self.assertNotIn("noch keine Anfrage", out["only"])
        self.assertNotRegex(out["only"], r"Anfrageni0(?!\d)")
        self.assertIn("50 Anfragen (laut chrony)", out["only"])
        self.assertIn("vor 3 s", out["only"].split("Laut chrony")[0])  # Kachel „Zuletzt“, nicht erst die Karte
        self.assertIn("7 Anfragen", out["own"])                         # eigene Messung hat Vorrang
        self.assertNotIn("(laut chrony)", out["own"])

    def test_pass_page_shows_chrony_counters(self):
        out = self.run_js(f"""
const cp = await import({mod("pages/clientpass.js")});
const data = {{ address: "192.0.2.77", name: "", generated: 1783000000, entry: {{}}, week: {{}}, month: {{}}, daily: [], series: [],
  software: {{ key: null, label: "unbekannt", origin: "unbekannt" }}, quality: {{}}, nts: {{}}, recommendations: [],
  chrony: {{ ntp_packets: 50, ntp_last_rx: 3 }} }};
console.log(JSON.stringify({{ t: text(cp.renderPass(ctx({{ data: () => data }}), "192.0.2.77")) }}));
""")
        self.assertIn("vor 3 s (laut chrony)", out["t"])   # T2: ohne Nullen am Ende
        self.assertIn("Anfragen (laut chrony)", out["t"])

    # --- U6 Nachbesserung: Notiz nennt das echte Fenster ---------------------------------------
    def test_clients_rate_note_names_real_window(self):
        out = self.run_js(f"""
const clients = await import({mod("pages/clients.js")});
const ov = await import({mod("pages/overview.js")});
const sparse = [{{ t: 0, served: 0 }}, {{ t: 144, served: 0 }}, {{ t: 288, served: 10 }}];
const dense = []; for (let i = 0; i < 12; i++) dense.push({{ t: 1000 + i * 10, served: i }});
const render = (history) => text(clients.render(ctx({{ history }})));
console.log(JSON.stringify({{ sparse: render(sparse), dense: render(dense), none: ov.rateWindowText(null),
  min: ov.rateWindowText(120), h: ov.rateWindowText(7200) }}));
""")
        self.assertNotIn("letzten Minute", out["sparse"])
        self.assertIn("Mittel der letzten 2,4 min", out["sparse"])
        self.assertIn("Mittel der letzten 60 s", out["dense"])
        self.assertEqual(out["min"], "Mittel der letzten 2 min")
        self.assertEqual(out["h"], "Mittel der letzten 2 h")   # T2: ohne Nullen am Ende
        self.assertIn("zu wenige", out["none"])

    # --- U8 ---------------------------------------------------------------------------------
    def test_range_buttons_only_in_temperature_card(self):
        out = self.run_js(f"""
const cq = await import({mod("pages/clockquality.js")});
const temp = (available, range) => ({{ available, reason: available ? null : "none", candidates: [], setting: "auto", range,
  sensor: {{ name: "cpu" }}, celsius: 40, pairs: [], summary: {{ count: 100, days: 1, need_days: 3, span_k: 6, need_span_k: 4 }} }});
const render = (available, range) => cq.render(ctx({{ uiState: {{ uqRange: range }},
  data: (k) => (k === "temperature" ? temp(available, range) : undefined) }}));
const where = (nodes) => withAttr(nodes, "data-focus-key", "uqrange:").length;
const none = render(false, 86400);
const withSensor = render(true, 86400);
// Knöpfe stecken in der Karte „Temperatur und Frequenz“, nicht in der Kopfzeile der Seite.
const head = withSensor[0];
const tempCard = withSensor.find((n) => n && n.textContent.startsWith("Temperatur und Frequenz"));
console.log(JSON.stringify({{ none: where(none), withSensor: where(withSensor), head: where([head]),
  inCard: where([tempCard]), shortText: text(withSensor), longText: text(render(true, 7 * 86400)) }}));
""")
        self.assertEqual(out["none"], 0)
        self.assertEqual(out["withSensor"], 4)
        self.assertEqual(out["head"], 0)
        self.assertEqual(out["inCard"], 4)
        self.assertIn("mindestens 3 Tagen", out["shortText"])
        self.assertNotIn("Es wird weiter gesammelt", out["shortText"])
        self.assertIn("Es wird weiter gesammelt", out["longText"])


class StaticTest(unittest.TestCase):
    # --- F2 ---------------------------------------------------------------------------------
    def test_reconnect_handlers_and_banner(self):
        app = (JS / "app.js").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('addEventListener("online"', app)
        self.assertIn('addEventListener("visibilitychange"', app)
        self.assertIn('Math.min(30000', app)  # Backoff höchstens 30 s
        self.assertIn('id="stale-banner"', html)

    # --- F1 ---------------------------------------------------------------------------------
    def test_system_info_has_utc_offset(self):
        import server
        saved = os.environ.get("TZ")
        try:
            with mock.patch.dict(os.environ, {"TZ": "Europe/Berlin"}):
                time.tzset()
                info = server.system_info({"web_title": "x", "web_refresh_seconds": 5, "ntp_port": 123})
        finally:
            if saved is None:
                os.environ.pop("TZ", None)
            time.tzset()
        self.assertIn(info["utc_offset"], (3600, 7200))
        self.assertIn(info["timezone"], ("CET", "CEST"))
        self.assertEqual(info["tz_name"], "Europe/Berlin")

    def test_iana_timezone_sources(self):
        import server
        with tempfile.TemporaryDirectory() as tmp:
            zoneinfo = Path(tmp) / "usr" / "share" / "zoneinfo" / "Europe"
            zoneinfo.mkdir(parents=True)
            (zoneinfo / "Vienna").write_bytes(b"TZif")
            link = Path(tmp) / "localtime"
            link.symlink_to(zoneinfo / "Vienna")
            missing = str(Path(tmp) / "timezone")
            tzfile = Path(tmp) / "tzfile"
            tzfile.write_text("Europe/Zurich\n", encoding="utf-8")
            self.assertEqual(server.iana_timezone({"TZ": "Europe/Berlin"}, str(link), missing), "Europe/Berlin")
            self.assertEqual(server.iana_timezone({"TZ": ":Europe/Berlin"}, str(link), missing), "Europe/Berlin")
            self.assertEqual(server.iana_timezone({"TZ": "UTC"}, str(link), missing), "UTC")
            self.assertIsNone(server.iana_timezone({"TZ": "CET-1CEST,M3.5.0,M10.5.0/3"}, str(link), missing))
            self.assertEqual(server.iana_timezone({}, str(link), str(tzfile)), "Europe/Zurich")
            self.assertEqual(server.iana_timezone({}, str(link), missing), "Europe/Vienna")
            self.assertIsNone(server.iana_timezone({}, str(Path(tmp) / "fehlt"), missing))


if __name__ == "__main__":
    unittest.main()
