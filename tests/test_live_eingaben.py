"""Eingaben und Rückmeldungen überstehen den Live-Refresh (Befunde aus der Fehlersuche zur 1.6).

  * GPS-Kalibrierung: Die gewählte Rolle („bevorzugen“) bleibt nach dem Neuzeichnen stehen und wird
    nicht still durch den gespeicherten Wert ersetzt.
  * Eingabefelder: Cursor und Markierung bleiben nach dem Neuzeichnen erhalten; ein halb getipptes
    Zahlenfeld („0,“) wird im Hintergrund nicht neu gebaut (sonst wird aus 0,5 eine 5).
  * Neustart-Anzeige: verglichen wird mit der Serveruhr, nicht mit der Uhr des Browsers.
  * Zurückgehaltenes Neuzeichnen wird nicht mitten in einem Klick nachgeholt (Drücken verlässt das
    Zahlenfeld, Loslassen muss noch denselben Knopf treffen); Auswahllisten werden wie Zahlenfelder
    nicht unter dem Fokus neu gebaut.

Alles im echten JS-Interpreter mit der DOM-Attrappe aus test_frontend_states.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_frontend_states import DOM  # noqa: E402 – dieselbe DOM-Attrappe
from test_darstellung_browser import _playwright_ready  # noqa: E402


def mod(path: str) -> str:
    return json.dumps((JS / path).resolve().as_uri())


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class NodeTest(unittest.TestCase):
    def run_js(self, body: str):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dom.mjs").write_text(DOM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            script.write_text('import { text, withAttr, ctx } from "./dom.mjs";\n'
                              'Element.prototype.addEventListener = function (type, fn) { (this._on ||= {})[type] = fn; };\n'
                              + body, encoding="utf-8")
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60,
                                    env={**os.environ, "TZ": "UTC"})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])


class GpsRolleTest(NodeTest):
    SETUP = f"""
const gps = await import({mod("pages/gps.js")});
const cal = {{ status: "ready", bias: 0.08, spread: 0.001, samples: 500, duration_seconds: 3600, suggested_offset: 0.08,
  current_offset: 0, suggested_delay: 0.01, current_delay: 0.2, series: [] }};
const status = {{ system: {{ time: 1783000000 }}, gps: {{ enabled: true, running: true }}, config: {{ gps_select: "auto" }},
  sources: [], tracking: {{}}, clients: [] }};
const c = ctx({{ status, data: (key) => key === "calibration" ? cal : undefined }});
const select = () => withAttr(gps.render(c), "id", "cal-role")[0];
const chosen = (s) => s.childNodes.filter((o) => o.getAttribute("selected") !== null).map((o) => o.getAttribute("value"));
"""

    def test_gewaehlte_rolle_uebersteht_neuzeichnen(self):
        out = self.run_js(self.SETUP + """
const first = select();
first.value = "prefer";
first._on.change();
const afterRefresh = chosen(select());
status.config = { gps_select: "prefer" };   // anderswo gespeichert: dann gilt wieder die Konfiguration
const pickedBefore = select(); pickedBefore.value = "auto"; pickedBefore._on.change();
status.config = { gps_select: "auto" };
const afterConfigChange = chosen(select());
console.log(JSON.stringify({ afterRefresh, afterConfigChange }));
""")
        self.assertEqual(out["afterRefresh"], ["prefer"])
        self.assertEqual(out["afterConfigChange"], ["auto"])


class FokusTest(NodeTest):
    # Kleine Attrappe: ein Wurzelknoten mit Eingabefeldern, die Auswahl und Fokus kennen.
    SETUP = f"""
const focus = await import({mod("focus.js")});
let active = null;
function field(type, value, label) {{
  return {{ tagName: "INPUT", type, value, dataset: {{}}, isConnected: true, selectionStart: value.length,
    selectionEnd: value.length, selectionDirection: "none", textContent: "",
    getAttribute(k) {{ return k === "aria-label" ? label : null; }},
    focus() {{ active = this; }},
    setSelectionRange(a, b, d) {{ if (this.type === "number") throw new Error("InvalidStateError");
      this.selectionStart = a; this.selectionEnd = b; this.selectionDirection = d; }} }};
}}
function root(nodes) {{ return {{ contains: (n) => nodes.includes(n), querySelectorAll: () => nodes }}; }}
"""

    def test_markierung_bleibt_nach_neuzeichnen(self):
        out = self.run_js(self.SETUP + """
const old = field("text", "Zeile eins und zwei", "Notiz zum Gerät");
old.selectionStart = 0; old.selectionEnd = 19; old.selectionDirection = "forward";
const saved = focus.captureFocus(root([old]), old);
const fresh = field("text", "Zeile eins und zwei", "Notiz zum Gerät");
focus.restoreFocus(root([fresh]), saved, null);
const changed = field("text", "anderer Text", "Notiz zum Gerät");
focus.restoreFocus(root([changed]), saved, null);
console.log(JSON.stringify({ focused: active === changed, sel: [fresh.selectionStart, fresh.selectionEnd, fresh.selectionDirection],
  changedSel: [changed.selectionStart, changed.selectionEnd] }));
""")
        self.assertTrue(out["focused"])
        self.assertEqual(out["sel"], [0, 19, "forward"])
        self.assertEqual(out["changedSel"], [12, 12])  # anderer Text: Auswahl passt nicht, Cursor bleibt am Ende

    def test_zahlenfeld_wird_im_hintergrund_nicht_neu_gebaut(self):
        out = self.run_js(self.SETUP + """
const num = field("number", "0", "Stunden ohne Anfrage");
const txt = field("text", "abc", "Name der Gruppe");
const box = root([num, txt]);
const saved = focus.captureFocus(box, num);   // Zahlenfeld kennt keine Auswahl: darf nicht werfen
console.log(JSON.stringify({ number: focus.holdsTyping(box, num), text: focus.holdsTyping(box, txt),
  outside: focus.holdsTyping(root([]), num), none: focus.holdsTyping(box, null), saved: Boolean(saved) }));
""")
        self.assertEqual(out, {"number": True, "text": False, "outside": False, "none": False, "saved": True})

    def test_auswahlliste_wird_im_hintergrund_nicht_neu_gebaut(self):
        out = self.run_js(self.SETUP + """
const sel = field("text", "auto", "Rolle des GPS"); sel.tagName = "SELECT"; sel.type = "select-one";
const box = root([sel]);
console.log(JSON.stringify({ select: focus.holdsTyping(box, sel), outside: focus.holdsTyping(root([]), sel) }));
""")
        self.assertEqual(out, {"select": True, "outside": False})


class RenderGateTest(NodeTest):
    SETUP = f"""
const {{ renderGate }} = await import({mod("focus.js")});
let runs = 0;
const gate = renderGate(() => {{ runs += 1; }});
let active = null;
const num = {{ tagName: "INPUT", type: "number" }};
const btn = {{ tagName: "BUTTON", type: "submit" }};
const box = {{ contains: (n) => n === num || n === btn }};
const bg = () => gate.blocks(true, box, active);
"""

    def test_klick_nach_zahlenfeld_wird_nicht_unterbrochen(self):
        # Refresh während des Tippens wird zurückgehalten; das Drücken auf einen Knopf verlässt das Feld
        # (focusout), aber nachgeholt wird erst nach dem Loslassen.
        out = self.run_js(self.SETUP + """
active = num;
const heldTyping = bg();
gate.pointerDown(); active = btn; gate.focusOut();
const afterFocusOut = runs;
const heldWhilePressed = bg();          // regulärer Refresh zwischen Drücken und Loslassen
gate.pointerUp();
const afterUp = runs;
const free = bg();
gate.pointerUp();                        // Loslassen ohne vorheriges Drücken: nichts nachzuholen
console.log(JSON.stringify({ heldTyping, afterFocusOut, heldWhilePressed, afterUp, free, deferred: gate.deferred, end: runs }));
""")
        self.assertEqual(out, {"heldTyping": True, "afterFocusOut": 0, "heldWhilePressed": True, "afterUp": 1,
                               "free": False, "deferred": False, "end": 1})

    def test_tastatur_holt_beim_verlassen_nach(self):
        out = self.run_js(self.SETUP + """
active = num;
const held = bg();
active = btn; gate.focusOut();           // Tab: kein Zeiger gedrückt, gleich nachholen
const afterTab = runs;
active = num; bg();
const explicit = gate.blocks(false, box, active);   // ausdrückliches Neuzeichnen läuft immer
gate.focusOut();
console.log(JSON.stringify({ held, afterTab, explicit, end: runs }));
""")
        self.assertEqual(out, {"held": True, "afterTab": 1, "explicit": False, "end": 1})

    def test_app_nutzt_gate(self):
        app = (JS / "app.js").read_text(encoding="utf-8")
        self.assertIn("gate.blocks(background, main, document.activeElement)", app)
        self.assertIn('main.addEventListener("pointerdown"', app)


CLICK = r"""
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const out = {};
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await page.goto(`${process.argv[2]}/#/`, { waitUntil: "networkidle" });
    // Eigene Testelemente in #main: Jedes Neuzeichnen im Hintergrund entfernt sie.
    await page.evaluate(() => {
      const main = document.getElementById("main");
      const num = Object.assign(document.createElement("input"), { type: "number", id: "t-num" });
      const btn = Object.assign(document.createElement("button"), { type: "button", id: "t-btn", textContent: "Test" });
      btn.addEventListener("click", () => { window.tClicks = (window.tClicks || 0) + 1; });
      main.prepend(num, btn);
    });
    await page.click("#t-num");
    await page.keyboard.type("2");
    await page.waitForTimeout(7000);    // länger als ein Refresh-Intervall (5 s)
    out.numHeld = await page.evaluate(() => document.getElementById("t-num")?.isConnected === true);
    const box = await page.locator("#t-btn").boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(150);
    out.btnDuringPress = await page.evaluate(() => document.getElementById("t-btn")?.isConnected === true);
    await page.mouse.up();
    await page.waitForTimeout(500);
    out.clicks = await page.evaluate(() => window.tClicks || 0);
    out.renderedAfter = await page.evaluate(() => !document.getElementById("t-btn"));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(String(e)); process.exit(2); });
"""


@unittest.skipUnless(_playwright_ready(), "Node mit Playwright nicht vorhanden")
class KlickNachZahlenfeldBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "app"))
        import _isolation  # noqa: PLC0415,F401 – vor jedem App-Import: Host-Pfade umlenken
        import server  # noqa: PLC0415
        from _support import JoiningHTTPServer  # noqa: PLC0415

        import onboarding  # noqa: PLC0415

        os.makedirs(os.environ["NTPGUI_DATA_DIR"], exist_ok=True)
        # Einrichtung als erledigt markieren: Sonst öffnet die Startseite beim Erststart den Assistenten,
        # und der Test liefe auf der falschen Seite.
        onboarding.action("never")
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        from _support import stop_http_server  # noqa: PLC0415
        import store  # noqa: PLC0415

        stop_http_server(cls.httpd)
        store.close_all()

    def test_getrenntes_druecken_und_loslassen(self):
        # Getrennt gedrückt und losgelassen (wie eine Hand) – Playwrights click() verdeckte den Fehler.
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "click.cjs"
            script.write_text(CLICK, encoding="utf-8")
            url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
            result = subprocess.run(["node", str(script), url], capture_output=True, text=True, timeout=180)
        if result.returncode == 2 and "Executable doesn't exist" in result.stderr:
            self.skipTest("Playwright-Browser nicht installiert")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertTrue(out["numHeld"], "Zahlenfeld wurde trotz Fokus im Hintergrund neu gebaut")
        self.assertTrue(out["btnDuringPress"], "Neuzeichnen zwischen Drücken und Loslassen")
        self.assertEqual(out["clicks"], 1, "Klick ging verloren")
        self.assertTrue(out["renderedAfter"], "Zurückgehaltenes Neuzeichnen wurde nicht nachgeholt")


class NeustartTest(NodeTest):
    def test_bezugszeit_ist_serverzeit(self):
        out = self.run_js(f"""
const util = await import({mod("util.js")});
// Browseruhr geht 5 s vor: Server 1000, Browser 1005 beim Abruf des Status; 3 s später wird gespeichert.
const clock = util.serverClock(1000, 1005000);
const started = util.serverNow(clock, 1008000) - 2;
const done = {{ state: "done", time: 1004 }};
const old = {{ state: "done", time: 990 }};
console.log(JSON.stringify({{ started, done: util.reloadSettled(done, started), old: util.reloadSettled(old, started),
  running: util.reloadSettled({{ state: "running", time: 1004 }}, started), noClock: util.serverNow(null, 1008000) }}));
""")
        self.assertEqual(out["started"], 1001)
        self.assertTrue(out["done"])
        self.assertFalse(out["old"])
        self.assertFalse(out["running"])
        self.assertEqual(out["noClock"], 1008)  # ohne Serverstatus: Browseruhr wie bisher

    def test_temperatur_alter_nach_serverzeit(self):
        # Die Browseruhr (echtes Date.now()) liegt Monate neben der Serverzeit der Attrappe.
        out = self.run_js(f"""
const ov = await import({mod("pages/overview.js")});
const now = 1783000000;
const c = ctx({{ history: [{{ t: now - 10, temp: 21.5 }}],
  status: {{ system: {{ time: now }}, chrony_running: true, tracking: {{ synchronised: true }}, clients: [], serverstats: {{}} }} }});
console.log(JSON.stringify({{ text: text(ov.render(c)) }}));
""")
        self.assertIn("21,5 °C", out["text"])

    def test_app_nutzt_serveruhr(self):
        app = (JS / "app.js").read_text(encoding="utf-8")
        self.assertFalse("Date.now() / 1000 - 2" in app, "Browseruhr als Bezugszeit")
        self.assertIn("serverNow(", app)
        self.assertIn("reloadSettled(", app)


if __name__ == "__main__":
    unittest.main()
