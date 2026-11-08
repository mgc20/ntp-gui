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
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

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


def _playwright_ready() -> bool:
    if not shutil.which("node"):
        return False
    probe = subprocess.run(["node", "-e", "require.resolve('playwright')"], capture_output=True, timeout=30)
    return probe.returncode == 0


@unittest.skipUnless(_playwright_ready(), "Node mit Playwright nicht vorhanden")
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
            self.skipTest("Playwright-Browser nicht installiert")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        for key, res in out.items():
            width = int(key.split("/")[0])
            with self.subTest(ansicht=key):
                self.assertEqual(res["over"], [], "Elemente ragen über den Rand oder laufen über")
                self.assertLessEqual(res["docWidth"], width)
                self.assertFalse(res["h1Cut"], f"Titel abgeschnitten (Breite {res['h1Width']} px)")
                self.assertLessEqual(res["h1Lines"], 2)


if __name__ == "__main__":
    unittest.main()
