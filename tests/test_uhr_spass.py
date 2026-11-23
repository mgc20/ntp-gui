"""Studiouhr Etappe C3: Spiel „Tippe auf :00“, Zeitzeichen und Ostereier (mit Konami-Code und CSS-Konfetti).

Die reinen Rechnungen stehen in app/static/js/clockextras.js und laufen hier mit Node gegen Referenzwerte aus Python:
Abweichung zur vollen Sekunde bzw. Minute, Wertung, Messgenauigkeit, Bestwert aus dem localStorage (auch feindliche
Einträge), Töne des Zeitzeichens (Sekunden und Zeitpunkte, auch in Zonen mit halben Stunden), Zeitumstellung am Tag
(zoneinfo), Tabelle der Ostereier, Konami-Code und die Regel, wann es überhaupt Ostereier gibt: nie mit eggs=0 oder
fun=0, nie in den Voreinstellungen studio, tile, banner, nie im Kiosk (auch nicht aus einem Profil), mit lock=1, in
OBS und auf E-Ink. Dazu Schema, Server-Allowlist, Seitenregeln (Konfetti nur per CSS, bei „weniger Bewegung“ nur Text,
Ton nur nach Klick) und Doku.
"""

import datetime
import json
import re
import shutil
import subprocess
import sys
import unittest
import zoneinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import clockprofiles  # noqa: E402
import server  # noqa: E402

UTC = datetime.timezone.utc


def run_fx(code: str, tz: str | None = None):
    mods = {name: json.dumps((JS / f"{name}.js").as_uri()) for name in ("clockextras", "clockkit", "clockcount", "clocklink")}
    script = (f"import * as x from {mods['clockextras']};\nimport * as k from {mods['clockkit']};\n"
              f"import * as l from {mods['clocklink']};\n{code}")
    env = None
    if tz:
        import os
        env = {**os.environ, "TZ": tz}
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def ms(dt: datetime.datetime) -> int:
    return int(dt.timestamp() * 1000)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class SpielTest(unittest.TestCase):
    def test_abweichung_zur_vollen_sekunde_und_minute(self):
        base = ms(datetime.datetime(2026, 11, 23, 10, 15, 0, tzinfo=UTC))
        cases = [(base + 12, "second", 12), (base - 12, "second", -12), (base + 499, "second", 499),
                 (base + 500, "second", -500), (base + 999.25, "second", -0.75), (base, "second", 0),
                 (base - 300, "minute", -300), (base + 29_999, "minute", 29_999), (base + 30_000, "minute", -30_000),
                 (base + 1_250, "minute", 1_250)]
        out = run_fx(f"""
          const cases = {json.dumps(cases)};
          console.log(JSON.stringify({{
            got: cases.map(([t, u]) => x.tapDeviation(t, u)),
            bad: [x.tapDeviation(NaN), x.tapDeviation(1000, "hour"), x.tapDeviation(1000, "__proto__")],
            units: x.TAP_UNITS,
          }}));
        """)
        for (_, unit, want), got in zip(cases, out["got"]):
            with self.subTest(unit=unit, want=want):
                self.assertAlmostEqual(got, want, places=6)
        self.assertEqual(out["bad"], [None, None, None])
        self.assertEqual(out["units"], {"second": 1000, "minute": 60000})

    def test_wertung_und_messgenauigkeit(self):
        out = run_fx("""
          console.log(JSON.stringify({
            levels: [0, -10, 10.4, 30, -31, 100, 101, -300, 301, 29999, NaN].map(x.tapLevel),
            unc: x.tapUncertainty({ rttMs: 3, serverAccMs: 0.4, frameMs: 17 }),
            missing: x.tapUncertainty({ rttMs: NaN, frameMs: 16.7 }),
            neg: x.tapUncertainty({ rttMs: -2, serverAccMs: -1, frameMs: 17 }),
            text: [0.04, 3.44, 9.94, 9.96, 42.4, 1500].map(x.tapText),
          }));
        """)
        self.assertEqual(out["levels"], ["perfect", "perfect", "great", "great", "good", "good", "ok", "ok", "off", "off", None])
        self.assertEqual(out["unc"], {"device": 1.5, "server": 0.4, "frame": 17, "total": 18.9})
        self.assertEqual(out["missing"], {"device": None, "server": None, "frame": 16.7, "total": 16.7})
        self.assertEqual(out["neg"]["device"], None)
        self.assertEqual(out["neg"]["server"], None)
        self.assertEqual(out["text"], ["0 ms", "3,4 ms", "9,9 ms", "10 ms", "42 ms", "1,5 s"])

    def test_click_zaehlt_nur_ohne_zeiger(self):
        """Langer Druck mit Maus oder Finger: Der click nach dem Loslassen wertet nicht noch einmal (detail ≥ 1)."""
        out = run_fx("console.log(JSON.stringify([0, 1, 2, 3, undefined, null, -1, NaN, '0'].map((d) => x.tapFromClick(d))));")
        self.assertEqual(out, [True, False, False, False, False, False, False, False, False])

    def test_bestwert_aus_dem_speicher_auch_feindlich(self):
        out = run_fx("""
          const bad = ['', 'null', '[]', '[1,2]', '"x"', '{', '{"second":-1}', '{"second":"5"}', '{"second":501}',
            '{"minute":30001}', '{"second":1e999}', '{"__proto__":{"second":1}}', 'x'.repeat(201),
            '{"second":12.5,"minute":400,"evil":"<script>"}', '{"second":0,"minute":30000}'];
          let best = {};
          const steps = [["second", 40], ["second", -12.34], ["second", 20], ["minute", -1500], ["hour", 3], ["second", NaN]]
            .map(([u, d]) => { const r = x.tapBestUpdate(best, u, d); best = r.best; return r.record; });
          console.log(JSON.stringify({
            read: bad.map(x.tapBestRead), steps, best, text: x.tapBestText(best), empty: x.tapBestText({}),
            dirty: x.tapBestText({ second: 3, minute: -5, x: 1 }), key: x.TAP_BEST_KEY,
          }));
        """)
        want = [{}] * 13 + [{"second": 12.5, "minute": 400}, {"second": 0, "minute": 30000}]
        self.assertEqual(out["read"], want)
        self.assertEqual(out["steps"], [True, True, False, True, False, False])
        self.assertEqual(out["best"], {"second": 12.3, "minute": 1500})
        self.assertEqual(json.loads(out["text"]), {"second": 12.3, "minute": 1500})
        self.assertEqual(out["empty"], "")
        self.assertEqual(json.loads(out["dirty"]), {"second": 3})
        self.assertRegex(out["key"], r"^ntp-gui-clock-[a-z-]+$")


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class ZeitzeichenTest(unittest.TestCase):
    @staticmethod
    def expected(server_ms: int, scope: str, offset_s: int, horizon_ms: int = 1500, after: int | None = None):
        """Referenz in Python: Sekunden 55–59 kurz, :00 lang – zur Stunde nur in der letzten bzw. ersten Minute."""
        out = []
        first = server_ms // 1000 + 1
        if after is not None:
            first = max(first, after + 1)
        for second in range(first, (server_ms + horizon_ms) // 1000 + 1):
            local = second + offset_s
            in_minute, minute = local % 60, (local // 60) % 60
            if in_minute >= 55 and (scope == "minute" or minute == 59):
                out.append((second, "short", 0.1))
            elif in_minute == 0 and (scope == "minute" or minute == 0):
                out.append((second, "long", 0.5))
        return out

    def plan(self, cases):
        return run_fx(f"""
          const cases = {json.dumps(cases)};
          console.log(JSON.stringify(cases.map(([server, scope, offset, horizon, after]) => x.planPips(
            {{ audio: 100, server, exact: true }},
            {{ scope, offsetMs: offset * 1000, horizonMs: horizon, afterSecond: after === null ? -Infinity : after }}))));
        """)

    def test_fuenf_kurze_und_ein_langer_vor_der_vollen_stunde(self):
        hour = ms(datetime.datetime(2026, 11, 23, 11, 0, 0, tzinfo=UTC))
        cases = [[hour - 5_800, "hour", 0, 7000, None],      # 10:59:54,2 → 55 … 59 und 11:00:00
                 [hour - 65_800, "hour", 0, 7000, None],     # 10:58:54,2: keine volle Stunde in Sicht
                 [hour - 65_800, "minute", 0, 7000, None],   # jede Minute: 10:58:55 … 10:59:00
                 [hour - 1_800_000 - 5_800, "hour", 19_800, 7000, None],   # Indien (+5:30): volle Stunde auf :30 UTC
                 [hour - 5_800, "hour", 19_800, 7000, None],
                 [hour - 5_800, "hour", 0, 1500, None],      # Horizont 1,5 s: nur 55
                 [hour - 5_800, "hour", 0, 7000, (hour - 3000) // 1000]]   # schon geplant bis 57
        got = self.plan(cases)
        for case, tones in zip(cases, got):
            server_ms, scope, offset, horizon, after = case
            with self.subTest(case=case):
                want = self.expected(server_ms, scope, offset, horizon, after)
                self.assertEqual([(t["second"], t["kind"], t["dur"]) for t in tones], want)
                for tone in tones:
                    self.assertAlmostEqual(tone["at"], 100 + (tone["second"] * 1000 - server_ms) / 1000, places=9)
                    self.assertEqual(tone["freq"], 1000)
        self.assertEqual([t["kind"] for t in got[0]], ["short"] * 5 + ["long"])
        self.assertEqual(got[0][-1]["second"] * 1000, hour)
        self.assertEqual(got[1], [])
        self.assertEqual(len(got[2]), 6)
        self.assertEqual(got[3][-1]["second"] * 1000, hour - 1_800_000, "Indien: volle Stunde um 10:30 UTC")
        self.assertEqual(got[4], [])
        self.assertEqual([t["kind"] for t in got[6]], ["short", "short", "long"])

    def test_versteckter_tab_plant_bis_zum_naechsten_ziel(self):
        """Sichtbar 1,5 s; versteckt bis einschließlich zum langen Ton der nächsten vollen Stunde bzw. Minute."""
        hour = ms(datetime.datetime(2026, 11, 23, 11, 0, 0, tzinfo=UTC))
        out = run_fx(f"""
          const hour = {hour};
          const plan = (server, scope, offsetMs = 0) => {{
            const horizonMs = x.pipsHorizonMs(server, {{ scope, hidden: true, horizonMs: 1500, offsetMs }});
            return {{ horizonMs, tones: x.planPips({{ audio: 0, server, exact: true }}, {{ scope, horizonMs, offsetMs }})
              .map((t) => [t.second * 1000 - hour, t.kind]) }};
          }};
          console.log(JSON.stringify({{
            visible: x.pipsHorizonMs(hour - 3_540_000, {{ scope: "hour", hidden: false }}),
            hourFar: plan(hour - 3_540_000, "hour"),          // 10:01:00 – versteckt: bis 11:00:00
            hourNear: plan(hour - 3_000, "hour"),             // 10:59:57
            minute: plan(hour - 45_000, "minute"),            // 10:59:15
            india: plan(hour - 3_540_000, "hour", 19_800_000),   // +5:30: volle Stunde auf :30 UTC
            bad: [x.pipsHorizonMs(NaN, {{ hidden: true }}), x.pipsHorizonMs(hour, {{ scope: "day", hidden: true }})],
          }}));
        """)
        self.assertEqual(out["visible"], 1500)
        want = [[-5000, "short"], [-4000, "short"], [-3000, "short"], [-2000, "short"], [-1000, "short"], [0, "long"]]
        self.assertEqual(out["hourFar"]["tones"], want)
        self.assertEqual(out["hourFar"]["horizonMs"], 3_540_000 + 500)
        self.assertEqual(out["hourNear"]["tones"], want[3:])
        self.assertEqual(out["minute"]["tones"], want, "jede Minute: bis 11:00:00")
        self.assertEqual(out["india"]["tones"], [[t - 1_800_000, k] for t, k in want], "Indien: 10:30 UTC")
        self.assertEqual(out["bad"], [1500, 1500])

    def test_ungueltiges_ergibt_keine_toene(self):
        out = run_fx("""
          const c = { audio: 1, server: Date.UTC(2026, 10, 23, 10, 59, 54) };
          console.log(JSON.stringify([x.planPips(null), x.planPips({ audio: 1, server: NaN }), x.planPips(c, { scope: "day" }),
            x.planPips(c, { scope: "hour", horizonMs: 7000 }).length, x.PIPS.shorts, x.PIP_SCOPES]));
        """)
        self.assertEqual(out, [[], [], [], 6, 5, ["hour", "minute"]])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class OstereierTest(unittest.TestCase):
    @staticmethod
    def shift(zone: str, day: datetime.date) -> int:
        """Referenz: Abstand zu UTC zu Beginn des Folgetags minus zu Beginn des Tags (Minuten), aus zoneinfo."""
        tz = zoneinfo.ZoneInfo(zone)

        def start(d):
            # erster Moment des Tags (Mitternacht kann in manchen Zonen fehlen – dann eine Stunde später suchen)
            for minutes in range(0, 180):
                local = datetime.datetime(d.year, d.month, d.day, tzinfo=tz) + datetime.timedelta(minutes=minutes)
                back = local.astimezone(UTC).astimezone(tz)
                if back.replace(tzinfo=None) == local.replace(tzinfo=None):
                    return local.astimezone(UTC)
            raise AssertionError("kein Tagesbeginn")

        a = start(day).astimezone(tz).utcoffset()
        b = start(day + datetime.timedelta(days=1)).astimezone(tz).utcoffset()
        return int((b - a).total_seconds() // 60)

    def test_zeitumstellung_am_tag_gegen_zoneinfo(self):
        cases = [("Europe/Berlin", datetime.date(2026, 3, 29)), ("Europe/Berlin", datetime.date(2026, 10, 25)),
                 ("Europe/Berlin", datetime.date(2026, 6, 30)), ("America/New_York", datetime.date(2026, 3, 8)),
                 ("America/New_York", datetime.date(2026, 11, 1)), ("Australia/Lord_Howe", datetime.date(2026, 10, 4)),
                 ("Australia/Lord_Howe", datetime.date(2026, 4, 5)), ("Asia/Kolkata", datetime.date(2026, 3, 29)),
                 ("Etc/UTC", datetime.date(2026, 10, 25))]
        probes = [[zone, ms(datetime.datetime(d.year, d.month, d.day, 12, tzinfo=zoneinfo.ZoneInfo(zone)))] for zone, d in cases]
        got = run_fx(f"console.log(JSON.stringify({json.dumps(probes)}.map(([z, t]) => x.dstShiftOfDay(t, z))));")
        for (zone, day), value in zip(cases, got):
            with self.subTest(zone=zone, day=day):
                self.assertEqual(value, self.shift(zone, day))
        self.assertEqual(got[:5], [60, -60, 0, 60, -60])
        self.assertEqual(got[5:7], [30, -30])
        # Zone dieses Geräts (TZ), wie clock.js sie ohne Angabe nutzt
        local = run_fx(f"console.log(JSON.stringify([x.dstShiftOfDay({probes[0][1]}), x.dstShiftOfDay({probes[1][1]}),"
                       f" x.dstShiftOfDay(NaN)]));", tz="Europe/Berlin")
        self.assertEqual(local, [60, -60, 0])

    def test_tabelle_der_ostereier(self):
        out = run_fx("""
          const T = (h, m, s, mo = 6, d = 15) => ({ h, m, s, mo, d });
          const cases = [
            [T(13, 37, 0), {}], [T(13, 37, 59), {}], [T(13, 38, 0), {}], [T(1, 37, 0), {}],
            [T(12, 34, 55), {}], [T(12, 34, 56), {}], [T(12, 34, 59), {}], [T(12, 35, 0), {}],
            [T(0, 0, 0, 1, 1), {}], [T(0, 9, 59, 1, 1), {}], [T(0, 10, 0, 1, 1), {}], [T(0, 0, 0, 1, 2), {}],
            [T(23, 59, 59, 12, 31), {}],
            [T(10, 0, 0, 6, 30), { leap: "possible" }], [T(10, 0, 0, 12, 31), { leap: "insert" }],
            [T(10, 0, 0, 6, 30), { leap: "delete" }], [T(13, 37, 0, 6, 30), { leap: "insert" }],
            [T(10, 0, 0, 3, 29), { dst: 60 }], [T(10, 0, 0, 10, 25), { dst: -60 }], [T(10, 0, 0, 10, 4), { dst: 30 }],
            [T(10, 0, 0, 3, 29), { dst: NaN }],
            [T(13, 37, 0), { allowed: false }], [T(0, 0, 0, 1, 1), { allowed: false }], [T(10, 0, 0, 6, 30), { leap: "insert", allowed: false }],
            [null, {}],
          ];
          console.log(JSON.stringify({ got: cases.map(([t, o]) => x.eggFor(t, o)), kinds: x.EGGS.map((e) => e.kind),
            frozen: Object.isFrozen(x.EGGS) && x.EGGS.every((e) => Object.isFrozen(e)) }));
        """)
        egg = lambda kind, text=None, confetti=False: {"kind": kind, "text": text or kind, "confetti": confetti}  # noqa: E731
        want = [egg("leet"), egg("leet"), None, None,
                None, egg("straight"), egg("straight"), None,
                egg("newyear", confetti=True), egg("newyear", confetti=True), None, None,
                None,
                egg("leap", "possible"), egg("leap", "insert"), egg("leap", "delete"), egg("leet"),
                egg("dst", "dst_forward"), egg("dst", "dst_back"), egg("dst", "dst_forward"),
                None,
                None, None, None,
                None]
        self.assertEqual(out["got"], want)
        self.assertEqual(out["kinds"], ["newyear", "straight", "leet", "leap", "dst"])
        self.assertTrue(out["frozen"])

    def test_konami_code(self):
        out = run_fx("""
          const run = (keys) => { let pos = 0; const done = []; for (const key of keys) { const r = x.konamiStep(pos, key); pos = r.pos; done.push(r.done); } return { pos, done: done.lastIndexOf(true) }; };
          const K = [...x.KONAMI];
          console.log(JSON.stringify({
            plain: run(K), upper: run([...K.slice(0, 8), "B", "A"]), triple: run(["ArrowUp", ...K]),
            wrong: run([...K.slice(0, 9), "x"]), late: run(["x", "ArrowUp", "ArrowDown", ...K]),
            twice: run([...K, ...K]), junk: [x.konamiStep(-1, "ArrowUp"), x.konamiStep(99, "a"), x.konamiStep(3.5, null)],
            frozen: Object.isFrozen(x.KONAMI), len: K.length,
          }));
        """)
        self.assertEqual(out["plain"], {"pos": 0, "done": 9})
        self.assertEqual(out["upper"], {"pos": 0, "done": 9})
        self.assertEqual(out["triple"], {"pos": 0, "done": 10}, "↑ ↑ ↑ ↓ … zählt trotzdem")
        self.assertEqual(out["wrong"], {"pos": 0, "done": -1})
        self.assertEqual(out["late"]["done"], 12)
        self.assertEqual(out["twice"]["done"], 19)
        self.assertEqual(out["junk"], [{"pos": 1, "done": False}, {"pos": 0, "done": False}, {"pos": 0, "done": False}])
        self.assertTrue(out["frozen"])
        self.assertEqual(out["len"], 10)

    def test_konfetti_nur_css_bei_weniger_bewegung_text(self):
        out = run_fx("""
          console.log(JSON.stringify([
            x.confettiMode({ allowed: true, wanted: true, reduced: false }),
            x.confettiMode({ allowed: true, wanted: true, reduced: true }),
            x.confettiMode({ allowed: false, wanted: true, reduced: false }),
            x.confettiMode({ allowed: true, wanted: false }),
          ]));
        """)
        self.assertEqual(out, ["css", "text", "none", "none"])

    def test_nie_mit_eggs0_fun0_studio_tile_kiosk(self):
        """Akzeptanz C: eggs=0, fun=0 sowie Studio-, Tile- und Kiosk-Profile zeigen nie ein Ei oder Konfetti."""
        presets = {name: entry["params"] for name, entry in clockprofiles.PRESETS.items()}
        out = run_fx(f"""
          const presets = {json.dumps(presets)};
          const on = (q, extra = {{}}) => {{
            const p = k.parseParams(q);
            const allowed = x.eggsAllowed({{ eggs: p.eggs, fun: p.fun, kiosk: p.kiosk, lock: p.lock, layout: p.layout, eink: p.eink, ...extra }});
            return {{ allowed, egg: x.eggFor({{ h: 0, m: 0, s: 0, mo: 1, d: 1 }}, {{ leap: "insert", dst: 60, allowed }}),
              confetti: x.confettiMode({{ allowed, wanted: true, reduced: false }}) }};
          }};
          const fromPreset = (name, add = "") => on(l.effectiveQuery({{ search: add, profile: presets[name] }}));
          console.log(JSON.stringify({{
            presets: Object.fromEntries(Object.keys(presets).map((n) => [n, fromPreset(n)])),
            presetsWithEggs: Object.fromEntries(["studio", "tile", "banner"].map((n) => [n, fromPreset(n, "?eggs=1&fun=1")])),
            kioskProfile: fromPreset("nerd", "?kiosk=1"),
            plain: on(""), eggs0: on("?eggs=0"), fun0: on("?fun=0"), kiosk: on("?kiosk=1"), lock: on("?lock=1"),
            tile: on("?layout=tile"), eink: on("?eink=1"), obs: on("", {{ obs: true }}), eggsTrue: on("?eggs=1"),
          }}));
        """)
        for name in ("studio", "tile", "banner"):
            with self.subTest(preset=name):
                self.assertEqual(out["presets"][name], {"allowed": False, "egg": None, "confetti": "none"})
                self.assertFalse(out["presetsWithEggs"][name]["allowed"], "studio/banner bleiben Kiosk, tile gesperrt")
        for name in ("kitchen", "workshop", "night", "nerd"):
            with self.subTest(preset=name):
                self.assertTrue(out["presets"][name]["allowed"])
        for name in ("eggs0", "fun0", "kiosk", "lock", "tile", "eink", "obs", "kioskProfile"):
            with self.subTest(case=name):
                self.assertEqual(out[name], {"allowed": False, "egg": None, "confetti": "none"})
        for name in ("plain", "eggsTrue"):
            self.assertEqual(out[name]["confetti"], "css")
            self.assertEqual(out[name]["egg"]["kind"], "newyear")


    def test_nie_in_kachel_und_streifen(self):
        """Ostereier und Konfetti auch zur Laufzeit (Taste L, flaches Fenster) nie in Kachel und Streifen."""
        out = run_fx("""
          const layouts = ["normal", "banner", "column", "world", "strip", "tile"];
          console.log(JSON.stringify([layouts.map((layout) => x.eggShown({ allowed: true, layout })),
            layouts.map((layout) => x.eggShown({ allowed: false, layout })), x.eggShown(), x.eggShown({ allowed: 1 })]));
        """)
        self.assertEqual(out, [[True, True, True, True, False, False], [False] * 6, False, False])


class SchemaUndServerTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node fehlt")
    def test_schema_und_link_baukasten(self):
        out = run_fx("""
          const entry = k.PARAM_SCHEMA.find((e) => e.name === "eggs");
          const names = k.PARAM_SCHEMA.map((e) => e.name);
          console.log(JSON.stringify({ entry, after: names[names.indexOf("eggs") - 1], last: names[names.length - 1],
            ok: [k.parseParams("?eggs=0").eggs, k.parseParams("?eggs=1").eggs, k.parseParams("").eggs],
            bad: ["2", "ja", "<script>", "0;1"].map((v) => k.parseParams("?eggs=" + encodeURIComponent(v))).map((p) => [p.eggs, p.ignored]),
            group: l.FORM_GROUPS.find((g) => g.names.includes("eggs")).key,
            query: l.buildQuery({ eggs: "0", fun: "1" }),
          }));
        """)
        self.assertEqual(out["entry"], {"name": "eggs", "type": "flag", "default": True})
        self.assertEqual(out["after"], "fun")
        self.assertEqual(out["last"], "test")
        self.assertEqual(out["ok"], [False, True, True])
        for value, ignored in out["bad"]:
            self.assertEqual((value, ignored), (True, ["eggs"]))
        self.assertEqual(out["group"], "mode")
        self.assertIn("eggs=0", out["query"])

    def test_server_allowlist(self):
        self.assertEqual(clockprofiles.PARAMS["eggs"], ("flag", {}))
        clean = clockprofiles.clean_profile({"title": "Wohnzimmer", "params": {"eggs": "0", "fun": "1"}})
        self.assertEqual(clean["params"], {"eggs": "0", "fun": "1"})
        for bad in ("2", "ja", "<b>", "0 ", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(clockprofiles.ProfileError):
                    clockprofiles.check_value("eggs", bad)
        stored = {"wohnzimmer": {"title": "Wohnzimmer", "params": {"eggs": "0", "secret": "x"}}}
        self.assertEqual(clockprofiles.public_profile("wohnzimmer", stored)["params"], {"eggs": "0"})
        for name in ("studio", "tile", "banner"):
            self.assertEqual(clockprofiles.PRESETS[name]["params"]["fun"], "0", "Studio, Kachel, Banner ohne Spielereien")

    def test_keine_neue_datei_kein_neuer_weg(self):
        # C3 bringt keine neue statische Datei und keinen neuen Endpunkt: Die Liste der öffentlichen Pfade bleibt.
        public = sorted(server.CLOCK_PUBLIC_PATHS)
        self.assertFalse([p for p in public if "spiel" in p or "game" in p or "egg" in p], public)
        text = (JS / "clockextras.js").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"fetch\(|XMLHttpRequest|sendBeacon|WebSocket|localStorage\.|document\.|window\.")
        self.assertNotRegex(text, r"setTimeout|setInterval|requestAnimationFrame|speechSynthesis|Notification")


class SeitenregelnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")

    def body(self, name):
        start = self.js.index(name)
        return self.js[start:self.js.index("\n}\n", start)]

    def test_ostereier_nur_mit_erlaubnis(self):
        start = self.body("async function start()")
        self.assertLess(start.index("await loadProfile()"), start.index("EGGS_ON = fx.eggsAllowed("))
        self.assertIn("eggs: params.eggs, fun: params.fun, kiosk: params.kiosk, lock: params.lock", start)
        self.assertIn("obs: OBS, eink: params.eink", start)
        egg = self.body("function renderEgg(")
        self.assertLess(egg.index("if (fx.eggShown({ allowed: EGGS_ON,"), egg.index("kit.leapEgg("),
                        "auch die Schaltsekunde nur mit Erlaubnis")
        self.assertIn("setText(node, t(", egg)
        self.assertNotIn("innerHTML", egg)
        self.assertIn("fx.eggShown({ allowed: EGGS_ON, layout: state.layout })", egg, "nie in Kachel und Streifen")
        self.assertIn("fx.eggShown({ allowed: true, layout: state.layout })", self.body("function startConfetti()"))
        # Die Eier richten sich nach der großen Zeit: tc mit Zone des Servers deren Zeit, Tag und Zeitumstellung.
        render = self.body("function render(now)")
        self.assertIn("mo: shown.getUTCMonth() + 1, d: shown.getUTCDate() }, tcZone());", render)
        dst = self.body("function dstToday(")
        self.assertLess(dst.index("if (state.utcBig) return 0;"), dst.index("fx.dstShiftOfDay(ms, zone)"), "UTC groß: keine Umstellung")
        self.assertIn("${zone || \"\"}|", dst)
        key = self.body("function onKey(event)")
        self.assertIn("if (EGGS_ON) {", key)
        self.assertLess(key.index("fx.konamiStep("), key.index("const actions = {"), "das letzte A sagt nicht die Zeit an")
        self.assertLess(key.index("params.lock"), key.index("fx.konamiStep("), "lock=1: keine Tasten, auch kein Konami")
        self.assertIn('setDesign("binary", false)', self.body("function konami()"), "Binäruhr nur bis zum Neuladen")

    def test_konfetti_nur_css_und_nicht_bei_weniger_bewegung(self):
        confetti = self.body("function startConfetti()")
        self.assertIn("fx.confettiMode({ allowed: EGGS_ON, wanted: true, reduced: reducedMotion.matches }) !== \"css\") return;", confetti)
        self.assertIn('box.classList.add("is-on")', confetti)
        self.assertNotRegex(confetti, r"\.style\b|requestAnimationFrame|setInterval|animate\(")
        self.assertIn("setTimeout(stopConfetti, CONFETTI_MS)", confetti)
        self.assertIn("box.replaceChildren()", self.body("function stopConfetti()"))
        self.assertIn("@media (prefers-reduced-motion: reduce) { .clock-confetti { display: none; } }", self.css)
        self.assertIn("body:is(.is-kiosk, .is-tile, .is-compact, .is-eink, .is-obs) .clock-confetti { display: none; }", self.css)
        self.assertRegex(self.html, r'<div class="clock-confetti" id="confetti" aria-hidden="true" hidden></div>')
        # Bewegt wird nur über transform und opacity (Compositor), endlich oft.
        for frames in re.findall(r"@keyframes clock-confetti[\w-]*\s*\{(.*?)\n\}", self.css, re.S):
            props = set(re.findall(r"([a-z-]+):", frames))
            self.assertLessEqual(props, {"opacity", "transform"}, frames)
        self.assertRegex(self.css, r"\.clock-confetti\.is-on i \{ animation: clock-confetti-fall [0-9.]+s [^;]* 2 both; \}")
        self.assertNotRegex(self.css, r"clock-confetti[^}]*infinite")

    def test_spiel_bestwert_nur_lokal(self):
        tap = self.body("function gameTap(")
        self.assertIn("if (!CONTROLS.fun) return;", tap)
        self.assertIn("fx.tapDeviation(trueMs(perf), unit)", tap)
        self.assertIn("store(fx.TAP_BEST_KEY, fx.tapBestText(update.best))", tap)
        self.assertIn('state.game.best = fx.tapBestRead(store(fx.TAP_BEST_KEY) || "");', self.js)
        self.assertIn("removeStored(fx.TAP_BEST_KEY);", self.body("function gameReset()"))
        store = self.body("function store(key, value)")
        self.assertIn("try {", store)
        self.assertIn("} catch (error)", store)
        self.assertEqual(re.findall(r"fetch\(\s*[\"`]([^\"`?]+)", self.js), ["/api/v1/time", "/api/v1/clock/profile"])
        self.assertIn('$("game-tap").addEventListener("pointerdown"', self.js)
        # Langer Druck zählt einmal: der click nur ohne Zeiger dahinter, kein Zeitfenster mehr.
        self.assertIn("if (fx.tapFromClick(event.detail)) gameTap(event.timeStamp);", self.js)
        self.assertNotIn("GAME_CLICK_GAP_MS", self.js)
        self.assertRegex(self.html, r'id="mode-game"[^>]* hidden')
        self.assertIn('$("mode-game").hidden = !CONTROLS.fun;', self.body("async function start()"))
        self.assertIn("@media (max-height: 320px) { #mode-game { display: none; } }", self.css, "flache Fenster: Leiste bricht nicht um")

    def test_zeitzeichen_nur_nach_klick(self):
        self.assertIn('$("tone-pips-hour").addEventListener("click", () => startTone("pips-hour"));', self.js)
        self.assertIn('$("tone-pips-minute").addEventListener("click", () => startTone("pips-minute"));', self.js)
        self.assertEqual(len(re.findall(r'startTone\("pips-', self.js)), 2, "nur aus den Klicks")
        planned = self.body("function plannedTones(")
        self.assertIn("fx.planPips(clock,", planned)
        self.assertIn("fx.pipsHorizonMs(clock.server, { scope, hidden: document.hidden, horizonMs: 1500, offsetMs })", planned)
        self.assertIn('if (document.hidden && state.tone && state.tone.mode.startsWith("pips-")) toneTick(trueMs());', self.js)
        for id_ in ("tone-pips-hour", "tone-pips-minute", "tone-pips-line"):
            self.assertRegex(self.html, rf'id="{id_}"[^>]* hidden')
        self.assertIn('for (const id of ["tone-pips-hour", "tone-pips-minute", "tone-pips-line"]) $(id).hidden = !CONTROLS.fun;',
                      self.body("async function start()"))
        self.assertNotIn("speechSynthesis", self.js)

    def test_texte(self):
        for lang in ("de", "en"):
            data = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
            with self.subTest(lang=lang):
                for key in ("egg_newyear", "egg_straight", "egg_leet", "egg_dst_forward", "egg_dst_back", "egg_konami",
                            "egg_possible", "egg_insert", "egg_delete", "game_title", "game_info", "tone_pips_line"):
                    self.assertTrue(data[key], key)
                self.assertEqual(sorted(data["game_level"]), ["good", "great", "off", "ok", "perfect"])
                self.assertEqual(sorted(data["tone_pips_scope"]), ["hour", "minute"])
                self.assertTrue(data["link"]["f"]["eggs"])
                self.assertIn("{min}", data["egg_dst_forward"])
        de = json.loads((STATIC / "i18n" / "de.json").read_text(encoding="utf-8"))["clock"]
        self.assertIn("keine Referenz", de["tone_pips_line"])
        self.assertIn("nur in diesem Browser", de["game_note"])

    def test_doku(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        help_text = (JS / "help-uhr.js").read_text(encoding="utf-8")
        doc = (ROOT / "docs" / "integrationen" / "studiouhr.md").read_text(encoding="utf-8")
        for name, text in (("README", readme), ("help-uhr.js", help_text)):
            with self.subTest(name=name):
                for needle in ("Tippe auf :00", "Zeitzeichen", "Konami", "eggs=0", "Konfetti", "keine Referenz"):
                    self.assertIn(needle, text)
        self.assertIn("eggs=0", doc)
        self.assertIn("Schaltsekunden-Zeile", doc)
        self.assertNotIn("body.is-kiosk .clock-egg", self.css, "Kiosk hat keine Ostereier")
        for name, text in (("README", readme), ("help-uhr.js", help_text)):
            with self.subTest(name=name):
                self.assertIn("goal=y2038", text)
                self.assertIn("Hintergrund-Tab", text)
                self.assertRegex(text, r"Streifen")


if __name__ == "__main__":
    unittest.main()
