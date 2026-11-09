"""Uhr-Werkstatt (1.6, T6): Designs, Adressparameter, Ton auf der Sekunde, Geräteversatz, Osterei.

Die reinen Rechnungen stehen in app/static/js/clockkit.js und laufen hier mit Node: Zeigerwinkel der
Bahnhofsuhr, Wortuhr für alle Fünf-Minuten-Schritte (deutsch und englisch), Klappzahlen, Allowlist der
Parameter, Ton-Planung mit gemockter AudioContext (Start innerhalb ±2 ms der vollen Serversekunde).
Dazu der Server-Teil (leap_next in /api/v1/time, öffentliche Dateien) und Regeln für clock.js/clock.css
(CSS statt JS-Schleife, ruhig mit prefers-reduced-motion, Versatz bleibt im Browser).
"""

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import leap  # noqa: E402
import server  # noqa: E402

LEAP_REAL = Path(__file__).resolve().parent / "fixtures" / "leap-seconds.list"


def run_kit(code: str):
    module = json.dumps((JS / "clockkit.js").as_uri())
    script = f"import * as k from {module};\n{code}"
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class ClockKitTest(unittest.TestCase):
    def test_zeigerwinkel(self):
        out = run_kit("""
          console.log(JSON.stringify({
            a: k.handAngles(10, 15, 42, 500), b: k.handAngles(0, 0, 0, 0), c: k.handAngles(23, 59, 58, 600),
            d: k.handAngles(12, 30, 29, 250), e: k.handAngles(3, 0, 59, 999), step: k.handAngles(10, 15, 42, 500, { step: true }),
            half: k.handAngles(6, 0, 29, 250),
          }));
        """)
        self.assertEqual((out["a"]["hour"], out["a"]["minute"]), (307.5, 90))
        self.assertAlmostEqual(out["a"]["second"], 42.5 / 58.5 * 360, places=6)
        self.assertEqual(out["b"], {"hour": 0, "minute": 0, "second": 0})
        self.assertEqual((out["c"]["hour"], out["c"]["minute"]), (359.5, 354))
        self.assertEqual(out["c"]["second"], 0, "nach 58,5 s wartet der Zeiger auf der 12")
        self.assertEqual(out["e"]["second"], 0)
        self.assertEqual((out["d"]["hour"], out["d"]["minute"]), (15, 180))
        self.assertAlmostEqual(out["half"]["second"], 180, places=6, msg="29,25 s = halbe Runde von 58,5 s")
        self.assertEqual(out["step"]["second"], 252, "ruhig: sekundenweise springen")

    def test_wortuhr_alle_fuenf_minuten(self):
        out = run_kit("""
          const de = [], en = [];
          for (let m = 0; m < 60; m += 5) { de.push(k.wordClock(10, m, "de").text); en.push(k.wordClock(10, m, "en").text); }
          console.log(JSON.stringify({ de, en, dots: [0, 1, 2, 3, 4, 7, 59].map((m) => k.wordClock(10, m).dots),
            one: k.wordClock(13, 0).text, halfOne: k.wordClock(0, 30).text, midnight: k.wordClock(0, 0).text,
            noon: k.wordClock(11, 55).text, enOne: k.wordClock(1, 0, "en").text, enTwelve: k.wordClock(23, 40, "en").text,
            round: k.wordClock(10, 19).text }));
        """)
        self.assertEqual(out["de"], [
            "ES IST ZEHN UHR", "ES IST FÜNF NACH ZEHN", "ES IST ZEHN NACH ZEHN", "ES IST VIERTEL NACH ZEHN",
            "ES IST ZWANZIG NACH ZEHN", "ES IST FÜNF VOR HALB ELF", "ES IST HALB ELF", "ES IST FÜNF NACH HALB ELF",
            "ES IST ZWANZIG VOR ELF", "ES IST VIERTEL VOR ELF", "ES IST ZEHN VOR ELF", "ES IST FÜNF VOR ELF"])
        self.assertEqual(out["en"], [
            "IT IS TEN O'CLOCK", "IT IS FIVE PAST TEN", "IT IS TEN PAST TEN", "IT IS QUARTER PAST TEN",
            "IT IS TWENTY PAST TEN", "IT IS TWENTY-FIVE PAST TEN", "IT IS HALF PAST TEN", "IT IS TWENTY-FIVE TO ELEVEN",
            "IT IS TWENTY TO ELEVEN", "IT IS QUARTER TO ELEVEN", "IT IS TEN TO ELEVEN", "IT IS FIVE TO ELEVEN"])
        self.assertEqual(out["dots"], [0, 1, 2, 3, 4, 2, 4])
        self.assertEqual(out["one"], "ES IST EIN UHR")
        self.assertEqual(out["halfOne"], "ES IST HALB EINS")
        self.assertEqual(out["midnight"], "ES IST ZWÖLF UHR")
        self.assertEqual(out["noon"], "ES IST FÜNF VOR ZWÖLF")
        self.assertEqual(out["enOne"], "IT IS ONE O'CLOCK")
        self.assertEqual(out["enTwelve"], "IT IS TWENTY TO TWELVE")
        self.assertEqual(out["round"], "ES IST VIERTEL NACH ZEHN", "abgerundet auf fünf Minuten")

    def test_klappzahlen(self):
        out = run_kit("""
          console.log(JSON.stringify({
            digits: k.timeDigits(9, 5, 7), short: k.timeDigits(9, 5, 7, false),
            first: k.flipDigits("", "101542"), next: k.flipDigits("101542", "101543"),
            hour: k.flipDigits("095959", "100000"), length: k.flipDigits("1015", "101500"),
          }));
        """)
        self.assertEqual(out["digits"], "090507")
        self.assertEqual(out["short"], "0905")
        self.assertFalse(any(d["changed"] for d in out["first"]), "erster Aufbau klappt nicht")
        self.assertEqual("".join(d["digit"] for d in out["first"]), "101542")
        self.assertEqual([d["changed"] for d in out["next"]], [False] * 5 + [True])
        self.assertEqual([d["changed"] for d in out["hour"]], [True, True, True, True, True, True])
        self.assertFalse(any(d["changed"] for d in out["length"]))

    def test_parameter_allowlist(self):
        out = run_kit("""
          const zones = ["Europe/Berlin", "America/New_York"];
          const p = (q) => k.parseParams(q, zones);
          console.log(JSON.stringify({
            ok: p("?design=wort&kiosk=1&eink=0&tz=America/New_York"),
            bad: p("?design=<script>&kiosk=yes&eink=2&tz=Mars/Olympus&x=1"),
            long: p("?tz=" + "A".repeat(200)),
            empty: p(""), none: k.parseParams("?tz=Europe/Berlin"),
            safe: [k.safeDesign("nixie"), k.safeDesign("../x"), k.safeDesign(null)],
            label: k.zoneLabel("America/New_York"), designs: k.DESIGNS,
            zones: k.supportedZones().includes("Europe/Berlin"),
            noIntl: k.supportedZones({}),
          }));
        """)
        self.assertEqual(out["ok"], {"design": "wort", "kiosk": True, "eink": False, "tz": "America/New_York", "ignored": []})
        self.assertEqual(out["bad"], {"design": None, "kiosk": False, "eink": False, "tz": None,
                                      "ignored": ["design", "kiosk", "eink", "tz"]})
        self.assertIsNone(out["long"]["tz"])
        self.assertEqual(out["empty"]["ignored"], [])
        self.assertIsNone(out["none"]["tz"], "ohne Allowlist keine Zeitzone")
        self.assertEqual(out["safe"], ["nixie", "digital", "digital"])
        self.assertEqual(out["label"], "New York")
        self.assertEqual(out["designs"], ["digital", "bahnhof", "nixie", "flip", "wort"])
        self.assertTrue(out["zones"], "Node kennt Intl.supportedValuesOf")
        self.assertEqual(out["noIntl"], [])

    def test_ton_auf_der_vollen_sekunde(self):
        """Gemockte AudioContext: Jeder Ton startet innerhalb ±2 ms der vollen Serversekunde (nach Versatz)."""
        out = run_kit("""
          const started = [];
          const param = () => ({ setValueAtTime() {}, linearRampToValueAtTime() {} });
          function fakeCtx({ currentTime, stamp, outputLatency = 0 }) {
            return {
              currentTime, outputLatency, destination: {},
              getOutputTimestamp: stamp ? () => stamp : undefined,
              createOscillator: () => ({ type: "", frequency: { value: 0 }, connect() {}, start(at) { started.push(at); }, stop() {} }),
              createGain: () => ({ gain: param(), connect() {} }),
            };
          }
          const results = [];
          // Browseruhr geht 3,2006 s nach; Ausgabezeitstempel 20 ms alt; zwei krumme Ausgangslagen.
          for (const [wall, perf, offset, stamp, latency] of [
            [1782807342123.4, 5020.25, 3200.6, { contextTime: 12.3, performanceTime: 5000.25 }, 0],
            [1782807420987.9, 812345.5, -1234.25, { contextTime: 801.004, performanceTime: 812330.0 }, 0],
            [1782807342777.7, 4000, 15.5, null, 0.0213],
          ]) {
            started.length = 0;
            const ctx = fakeCtx({ currentTime: stamp ? stamp.contextTime + 0.02 : 50.5, stamp, outputLatency: latency });
            const clock = k.audioClock(ctx, perf, wall, offset);
            const plan = k.planTones(clock, { mode: "seconds", horizonMs: 3000 });
            for (const tone of plan) k.scheduleTone(ctx, tone);
            // Unabhängig nachrechnen: Wann (Browseruhr) kommt der Ton aus dem Gerät, welche Serverzeit ist das?
            const errors = started.map((at) => {
              const heardWall = stamp ? wall - (perf - stamp.performanceTime) + (at - stamp.contextTime) * 1000
                : wall + (at - (ctx.currentTime - latency)) * 1000;
              const server = heardWall + offset;
              return server - Math.round(server / 1000) * 1000;
            });
            results.push({ errors, seconds: plan.map((t) => t.second), kinds: plan.map((t) => t.kind),
              exact: clock.exact, ahead: plan.map((t) => t.at - ctx.currentTime) });
          }
          const cd = k.planTones({ audio: 0, server: 1782807340000.5 }, { mode: "countdown", horizonMs: 25000 });
          const after = k.planTones({ audio: 0, server: 1782807340000.5 }, { afterSecond: 1782807341, horizonMs: 3000 });
          console.log(JSON.stringify({ results, countdown: cd.map((t) => [t.second % 60, t.kind]),
            after: after.map((t) => t.second), values: [k.countdownValue(1782807349999), k.countdownValue(1782807350000),
              k.countdownValue(1782807359500), k.countdownValue(1782807360200)] }));
        """)
        for result in out["results"]:
            self.assertGreaterEqual(len(result["errors"]), 2)
            for error in result["errors"]:
                self.assertLessEqual(abs(error), 2.0, f"Ton {error} ms neben der vollen Sekunde")
            self.assertEqual(result["seconds"], sorted(result["seconds"]))
            self.assertTrue(all(b - a == 1 for a, b in zip(result["seconds"], result["seconds"][1:])))
            self.assertTrue(all(a > -0.03 for a in result["ahead"]))
        self.assertTrue(out["results"][0]["exact"])
        self.assertFalse(out["results"][2]["exact"], "ohne getOutputTimestamp: currentTime minus Latenz")
        # Sekunde …420 ist eine volle Minute (1782807420 % 60 == 0): langer Ton.
        kinds = dict(zip(out["results"][1]["seconds"], out["results"][1]["kinds"]))
        self.assertEqual(kinds.get(1782807420), "long")
        self.assertEqual(kinds.get(1782807421), "short")
        self.assertEqual(out["countdown"], [[50, "count"], [51, "count"], [52, "count"], [53, "count"], [54, "count"],
                                            [55, "count"], [56, "count"], [57, "count"], [58, "count"], [59, "count"],
                                            [0, "long"]])
        self.assertEqual(out["after"], [1782807342, 1782807343])
        self.assertEqual(out["values"], [None, 10, 1, 0])

    def test_geraeteversatz(self):
        out = run_kit("""
          console.log(JSON.stringify({
            exact: k.deviceDrift(1.2, 2), good: k.deviceDrift(-80, 2), warn: k.deviceDrift(420, 3),
            crit: k.deviceDrift(-3200, 3), none: k.deviceDrift(NaN),
            fmt: [k.fmtDrift(42.4), k.fmtDrift(3200), k.fmtDrift(12345), k.fmtDrift(125000), k.fmtDrift(-999.6)],
          }));
        """)
        self.assertEqual(out["exact"], {"tone": "good", "dir": "exact", "abs": 1.2})
        self.assertEqual(out["good"]["dir"], "ahead", "negativer Versatz: Gerät geht vor")
        self.assertEqual(out["good"]["tone"], "good")
        self.assertEqual((out["warn"]["tone"], out["warn"]["dir"]), ("warn", "behind"))
        self.assertEqual((out["crit"]["tone"], out["crit"]["dir"]), ("crit", "ahead"))
        self.assertIsNone(out["none"])
        self.assertEqual(out["fmt"], ["42 ms", "3,2 s", "12 s", "2 min 5 s", "1000 ms"])

    def test_fmt_drift_rundet_vor_dem_aufteilen(self):
        # Erst auf ganze Sekunden runden, dann Minuten und Sekunden ableiten: nie „60 s“ oder „1 min 60 s“.
        out = run_kit("console.log(JSON.stringify([59600, 59999, 60000, 119600, 3599700, 9960, 9940, 999.4, -119600]"
                      ".map((v) => k.fmtDrift(v))));")
        self.assertEqual(out, ["1 min 0 s", "1 min 0 s", "1 min 0 s", "2 min 0 s", "60 min 0 s", "10 s", "9,9 s",
                               "999 ms", "2 min 0 s"])

    def test_osterei_schaltsekunde(self):
        out = run_kit("""
          const at = (s) => Date.parse(s);
          console.log(JSON.stringify([
            k.leapEgg(at("2026-06-30T08:15:42Z"), "Normal", null),
            k.leapEgg(at("2026-12-31T23:59:59Z"), "Normal", "2027-01-01"),
            k.leapEgg(at("2026-06-30T12:00:00Z"), "Insert second", null),
            k.leapEgg(at("2026-06-30T12:00:00Z"), "Delete second", null),
            k.leapEgg(at("2026-07-01T00:00:00Z"), "Insert second", "2026-07-01"),
            k.leapEgg(at("2026-06-29T23:59:59Z"), "Normal", null),
            k.leapEgg(at("2026-12-31T12:00:00Z"), "Normal", "2027-07-01"),
          ]));
        """)
        self.assertEqual(out, ["possible", "insert", "insert", "delete", None, None, "possible"])


class ServerTeilTest(unittest.TestCase):
    def test_leap_next_aus_leap_py(self):
        with mock.patch.object(server.leap, "status", return_value={"available": True, "next_leap_date": "2027-01-01"}):
            self.assertEqual(server._clock_leap_next({}), "2027-01-01")
        with mock.patch.object(server.leap, "status", return_value={"available": False, "next_leap_date": "2027-01-01"}):
            self.assertIsNone(server._clock_leap_next({}))
        with mock.patch.object(server.leap, "status", side_effect=RuntimeError("kaputt")):
            self.assertIsNone(server._clock_leap_next({}))
        with mock.patch.object(server.leap, "status", return_value={"available": True, "next_leap_date": "/etc/x"}):
            self.assertIsNone(server._clock_leap_next({}), "nur ein Datum, nie ein Pfad")
        # Echte Liste (keine angekündigte Schaltsekunde): None, aber kein Fehler.
        with mock.patch.object(leap, "chrony_source", return_value=("list", str(LEAP_REAL))):
            self.assertIsNone(server._clock_leap_next({}))

    def test_time_payload_hat_leap_next_ohne_pfad(self):
        tracking = {"synchronised": True, "stratum": 2, "ref_name": "192.0.2.1", "root_delay": 0.001,
                    "root_dispersion": 0.0001, "system_time_offset": 0.0, "leap_status": "Normal"}
        with mock.patch.object(server, "_clock_tracking", return_value=tracking), \
                mock.patch.object(server.leap, "status", return_value={"available": True, "next_leap_date": "2027-01-01",
                                                                        "path": "/geheim/leap.list"}):
            payload = server.time_payload(1.0, public=True)
        self.assertEqual(payload["leap_next"], "2027-01-01")
        self.assertNotIn("geheim", json.dumps(payload))
        self.assertIsNone(payload["source"])

    def test_oeffentliche_dateien_ohne_konfiguration(self):
        public = server.CLOCK_PUBLIC_PATHS
        for path in ("/static/js/clockkit.js", "/static/js/util.js", "/static/js/i18n.js", "/static/i18n/de.json",
                     "/static/i18n/en.json"):
            self.assertIn(path, public)
        for path in ("/static/js/app.js", "/static/js/ui.js", "/static/index.html", "/api/status", "/api/leap"):
            self.assertNotIn(path, public)
        # Jede öffentliche JS-Datei importiert nur andere öffentliche Dateien.
        for path in sorted(p for p in public if p.endswith(".js")):
            text = (STATIC / path[len("/static/"):]).read_text(encoding="utf-8")
            for target in re.findall(r"""^import .* from ["']\./([\w-]+\.js)["']""", text, re.M):
                self.assertIn(f"/static/js/{target}", public, f"{path} lädt {target}")
            self.assertNotRegex(text, r"fetch\(\s*[\"'`]/api/(?!v1/time)", f"{path}: nur /api/v1/time")


class SeitenregelnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")

    def test_bewegung_per_css_nicht_per_js_schleife(self):
        self.assertNotIn("requestAnimationFrame", self.js)
        for match in re.finditer(r"setInterval\([^,]+,\s*([A-Z_0-9]+)\)", self.js):
            self.assertIn(match.group(1), {"RESYNC_MS", "POLL_MS"})
        self.assertIn("@keyframes bh-sweep", self.css)
        self.assertRegex(self.css, r"97\.5% \{ transform: rotate\(360deg\)")
        self.assertIn("animation: bh-sweep 60s linear infinite", self.css)

    def test_ruhig_mit_reduced_motion(self):
        block = self.css[self.css.rindex("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn(".bh-second.is-sweep", block)
        self.assertIn(".flip-card .flip-digit", block)
        self.assertIn("prefers-reduced-motion: reduce", self.js, "Sekundenzeiger springt dann sekundenweise")

    def test_versatz_bleibt_im_browser(self):
        # Nur feste Schlüssel im localStorage; der gemessene Versatz wird nie gespeichert oder gesendet.
        keys = re.findall(r"store\(\s*([^,)]+)", self.js)
        self.assertTrue(keys)
        for key in keys:
            self.assertRegex(key.strip(), r'^(DESIGN_KEY|"ntp-gui-clock-(theme|red)"|key)$')
        self.assertEqual(re.findall(r"fetch\(\s*\"([^\"]+)", self.js), ["/api/v1/time"])
        self.assertNotRegex(self.js, r"method:\s*\"POST\"|sendBeacon|WebSocket")
        self.assertNotIn("localStorage.setItem", self.js.replace("window.localStorage.setItem(key, value)", ""))

    def test_html_texte_gleich_katalog(self):
        de = json.loads((STATIC / "i18n" / "de.json").read_text(encoding="utf-8"))

        def get(key):
            node = de
            for part in key.split("."):
                node = node[part]
            return node
        for key, text in re.findall(r'data-i18n="([^"]+)"[^>]*>([^<]+)<', self.html):
            self.assertEqual(get(key), text.strip(), key)
        for match in re.finditer(r'title="([^"]+)" data-i18n-title="([^"]+)"', self.html):
            self.assertEqual(get(match.group(2)), match.group(1))

    def test_bahnhofsuhr_eigenes_design(self):
        # Generisches Zifferblatt: offener Ring statt gefüllter Kelle, keine Herstellernamen.
        self.assertIn("bh-second-ring", self.js)
        self.assertRegex(self.css, r"\.bh-second-ring \{ fill: none;")
        for name in ("SBB", "Mondaine", "Swiss"):
            self.assertNotIn(name, self.js + self.css + self.html)


if __name__ == "__main__":
    unittest.main()
