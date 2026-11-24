"""Handybreite im echten Browser (F5, F18): kein Element ragt über den Rand, der Titel bleibt lesbar.

Startet den HTTP-Handler der App lokal (127.0.0.1, freier Port, Testpfade aus _isolation) und
öffnet die Einstellungsseite mit Playwright bei 320 und 390 px, hell und dunkel. Ohne Node,
Playwright oder Browser wird der Test übersprungen.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, skip_tool, skip_unless_tool, stop_http_server  # noqa: E402

CHECK = r"""
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const out = {};
  try {
    for (const width of [320, 390]) {
      for (const theme of ["dark", "light"]) {
        const page = await browser.newPage({ viewport: { width, height: 800 } });
        await page.goto(`${process.argv[2]}/#/einstellungen`, { waitUntil: "networkidle" });
        await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
        await page.waitForSelector(".src-editor-row", { timeout: 15000 });
        out[`${width}/${theme}`] = await page.evaluate((vw) => {
          const over = [];
          for (const e of document.querySelectorAll("body *")) {
            const r = e.getBoundingClientRect();
            if (!r.width || e.closest(".nav") || e.classList.contains("skip-link")) continue;
            if (r.right > vw + 0.5 || r.left < -0.5) over.push(`${e.tagName}.${e.className}`);
          }
          for (const e of document.querySelectorAll(".src-editor-row .cell-check, .src-editor-row .cell-check-text")) {
            if (e.scrollWidth > e.clientWidth + 1) over.push(`scroll ${e.className}: ${e.textContent}`);
          }
          const h1 = document.querySelector(".topbar h1");
          const lh = parseFloat(getComputedStyle(h1).lineHeight);
          return { over, docWidth: document.documentElement.scrollWidth, h1Width: h1.clientWidth,
            h1Cut: h1.scrollHeight > h1.clientHeight + 1 || h1.scrollWidth > h1.clientWidth + 1,
            h1Lines: Math.round(h1.getBoundingClientRect().height / lh) };
        }, width);
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(String(e)); process.exit(2); });
"""

# GPS-Seite: Zeile „Delay in chrony“ mit gespeicherter, noch nicht aktiver Fehlerschranke. Der Testserver hat kein GPS,
# deshalb baut die Prüfung die Zeile mit den echten Modulen so auf wie gps.js (Karte in .grid-2).
GPS_BOUND_CHECK = r"""
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const out = {};
  try {
    for (const [width, height] of [[390, 844], [1440, 900]]) {
      const page = await browser.newPage({ viewport: { width, height } });
      await page.goto(`${process.argv[2]}/#/`, { waitUntil: "networkidle" });
      out[width] = await page.evaluate(async (vw) => {
        const ui = await import("/static/js/ui.js");
        const gps = await import("/static/js/pages/gps.js");
        const { el } = await import("/static/js/util.js");
        const res = {};
        for (const state of ["limit", "holdover", "retry", "collecting"]) {
          const cell = gps.delayCell({ gps_bound: { managed: true, delay: 0.04, source: "measured", saved: 0.06,
            restart: { state, next_try: Math.floor(Date.now() / 1000) + 3600 } } }, {});
          const own = ui.card("GPS in chrony", {}, ui.kv([["Delay in chrony", cell]]));
          const main = document.getElementById("main");
          main.replaceChildren(el("div", { class: "grid-2" }, own, ui.card("Daneben", {}, ui.kv([["A", "B"]]))));
          const box = own.getBoundingClientRect();
          const over = [];
          for (const e of own.querySelectorAll("*")) {
            const r = e.getBoundingClientRect();
            if (r.width && (r.right > box.right + 0.5 || r.left < box.left - 0.5)) over.push(`${e.tagName}.${e.className}`);
          }
          const badge = own.querySelector(".badge");
          const note = own.querySelector(".kv-note");
          res[state] = { over, docWidth: document.documentElement.scrollWidth,
            badge: badge ? badge.textContent : null, note: note ? note.textContent : null,
            badgeWidth: badge ? badge.getBoundingClientRect().width : null };
        }
        return res;
      }, width);
      await page.close();
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(String(e)); process.exit(2); });
"""


def _playwright_ready() -> bool:
    if not shutil.which("node"):
        return False
    probe = subprocess.run(["node", "-e", "require.resolve('playwright')"], capture_output=True, timeout=30)
    return probe.returncode == 0


@skip_unless_tool(_playwright_ready(), "Node mit Playwright nicht vorhanden")
class HandyBreiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server  # noqa: PLC0415 – erst hier, damit der Skip ohne App-Import auskommt

        os.makedirs(os.environ["NTPGUI_DATA_DIR"], exist_ok=True)
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        import store  # noqa: PLC0415

        store.close_all()

    def test_einstellungen_bei_320_und_390_px(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "check.cjs"
            script.write_text(CHECK, encoding="utf-8")
            url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
            result = subprocess.run(["node", str(script), url], capture_output=True, text=True, timeout=180)
        if result.returncode == 2 and "Executable doesn't exist" in result.stderr:
            skip_tool(self, "Playwright-Browser nicht installiert")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        for key, res in out.items():
            width = int(key.split("/")[0])
            with self.subTest(ansicht=key):
                self.assertEqual(res["over"], [], "Elemente ragen über den Rand oder laufen über")
                self.assertLessEqual(res["docWidth"], width)
                self.assertFalse(res["h1Cut"], f"Titel abgeschnitten (Breite {res['h1Width']} px)")
                self.assertLessEqual(res["h1Lines"], 2)

    def _run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "check.cjs"
            script.write_text(source, encoding="utf-8")
            url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
            result = subprocess.run(["node", str(script), url], capture_output=True, text=True, timeout=180)
        if result.returncode == 2 and "Executable doesn't exist" in result.stderr:
            skip_tool(self, "Playwright-Browser nicht installiert")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_gps_wartende_fehlerschranke_ohne_ueberbreite(self):
        """Der Wartehinweis der Fehlerschranke bricht um und bleibt in der Karte (390 und 1440 px)."""
        out = self._run(GPS_BOUND_CHECK)
        for width, states in out.items():
            for state, res in states.items():
                with self.subTest(breite=width, zustand=state):
                    self.assertEqual(res["over"], [], "Elemente ragen aus der Karte")
                    self.assertLessEqual(res["docWidth"], int(width))
                    self.assertEqual(res["badge"], "wartet auf Neustart")
                    self.assertLess(res["badgeWidth"], 200)
                    self.assertIn("gespeichert: 0.06 s", res["note"])


if __name__ == "__main__":
    unittest.main()
