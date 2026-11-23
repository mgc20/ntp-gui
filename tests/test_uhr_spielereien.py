"""Studiouhr Etappe C1: Eieruhr, Pomodoro, eigene und eingebaute Countdowns, Nachtmodus, Bedienung.

Die reinen Rechnungen stehen in app/static/js/clockextras.js und laufen hier mit Node, immer zu festen Zeitpunkten:
Eingabe der Eieruhr, „+1 min“, Ende, Pomodoro-Phasen (auch nach langer Zeit im Hintergrund), eingebaute Countdowns
gegen Referenzwerte aus Python (zoneinfo für die Zeitumstellungen, Unix- und NTP-Zeitpunkte aus datetime), Nachtmodus
nach Uhrzeit und von Hand, eigene Countdowns aus dem localStorage (auch feindliche Einträge) und die Regel, wann
Bedienelemente erscheinen (nie in Studio-, Kachel- und Kiosk-Voreinstellungen, mit lock=1 und in OBS). Dazu Schema und
Server-Allowlist der neuen Parameter und Regeln für clock.js/clock.css/clock.html.
"""

import datetime
import json
import re
import shutil
import subprocess
import sys
import unittest
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
MIN = 60_000


def run_fx(code: str, tz: str | None = None):
    mods = {name: json.dumps((JS / f"{name}.js").as_uri()) for name in ("clockextras", "clockkit", "clockcount")}
    script = (f"import * as x from {mods['clockextras']};\nimport * as k from {mods['clockkit']};\n"
              f"import * as c from {mods['clockcount']};\n{code}")
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


def transitions(zone: str, start: datetime.datetime, count: int) -> list[int]:
    """Referenz: die nächsten Umstellungen der Zone, sekundengenau aus zoneinfo (unabhängig von Intl)."""
    import zoneinfo
    tz = zoneinfo.ZoneInfo(zone)
    out = []
    t = start
    step = datetime.timedelta(hours=1)
    prev = t.astimezone(tz).utcoffset()
    end = start + datetime.timedelta(days=800)
    while len(out) < count and t < end:
        nxt = t + step
        off = nxt.astimezone(tz).utcoffset()
        if off != prev:
            lo, hi = t, nxt
            while (hi - lo) > datetime.timedelta(seconds=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(tz).utcoffset() == prev:
                    lo = mid
                else:
                    hi = mid
            out.append(ms(hi.replace(microsecond=0)))
            prev = off
        t = nxt
    return out


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class EieruhrTest(unittest.TestCase):
    def test_eingabe_der_dauer(self):
        cases = ["7", "07", "7:30", "0:45", "1:05:00", "90s", "25m", "1h30m", " 12 ", "0", "0:00", "24:00:00",
                 "24:00:01", "1441", "7:60", "x", "", "7,5", "-3", "<b>", "9" * 20, "1e2", "７"]
        out = run_fx(f"console.log(JSON.stringify({json.dumps(cases)}.map((v) => x.parseEggInput(v))));")
        want = [7 * MIN, 7 * MIN, 7 * MIN + 30_000, 45_000, 65 * MIN, 90_000, 25 * MIN, 90 * MIN, 12 * MIN, None, None,
                24 * 60 * MIN, None, None, None, None, None, None, None, None, None, None, None]
        self.assertEqual(dict(zip(cases, out)), dict(zip(cases, want)))

    def test_plus_eine_minute_und_ende(self):
        out = run_fx("""
          const egg = c.timerToggle(c.timerNew(3 * 60000), 0);
          const before = x.timerAdd(egg, x.EGG_PLUS_MS, 60000);          // nach 1 min: 2 min übrig + 1
          const after = x.timerAdd(egg, x.EGG_PLUS_MS, 190000);          // 10 s Überzeit: 1 min ab jetzt
          const paused = x.timerAdd(c.timerToggle(egg, 30000), x.EGG_PLUS_MS, 99999);
          const watch = c.timerToggle(c.timerNew(null), 0);
          const capped = x.timerAdd(c.timerToggle(c.timerNew(k.MAX_TIMER_MS), 0), x.EGG_PLUS_MS, 0);
          console.log(JSON.stringify({
            before: c.timerRead(before, 60000).remaining, after: c.timerRead(after, 190000).remaining,
            paused: [paused.state, c.timerRead(paused, 99999).remaining], same: x.timerAdd(watch, 60000, 5000) === watch,
            capped: c.timerRead(capped, 0).remaining,
            ended: [x.timerEnded(c.timerRead(egg, 179999)), x.timerEnded(c.timerRead(egg, 180000)),
              x.timerEnded(c.timerRead(egg, 200000)), x.timerEnded(c.timerRead(watch, 9e9))],
            presets: x.EGG_PRESETS, beeps: x.END_BEEPS,
          }));
        """)
        self.assertEqual(out["before"], 3 * MIN)
        self.assertEqual(out["after"], MIN, "nach dem Ende: eine Minute ab jetzt, nicht 50 s")
        self.assertEqual(out["paused"], ["paused", 3 * MIN + 30_000])
        self.assertTrue(out["same"], "Stoppuhr ohne Dauer bleibt")
        self.assertEqual(out["capped"], 24 * 60 * MIN)
        self.assertEqual(out["ended"], [False, True, True, False])
        self.assertEqual(out["presets"], [1, 3, 5, 10, 15, 30])
        self.assertEqual(out["beeps"], 3)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class PomodoroTest(unittest.TestCase):
    def test_phasen_und_zaehler(self):
        out = run_fx("""
          let p = x.pomoNew();
          const seq = [];
          for (let i = 0; i < 10; i += 1) { seq.push([p.phase, p.round, p.done, x.pomoPhaseMs(p)]); p = x.pomoNext(p); }
          console.log(JSON.stringify({ seq, custom: x.pomoNew(50 * 60000, 10 * 60000), longCap: x.pomoNew(null, 20 * 60000).long,
            bad: x.pomoNew(-1, NaN), reset: x.pomoReset(p) }));
        """)
        W, B, L = 25 * MIN, 5 * MIN, 15 * MIN
        self.assertEqual(out["seq"], [
            ["work", 1, 0, W], ["break", 1, 1, B], ["work", 2, 1, W], ["break", 2, 2, B], ["work", 3, 2, W],
            ["break", 3, 3, B], ["work", 4, 3, W], ["long", 4, 4, L], ["work", 5, 4, W], ["break", 5, 5, B]])
        self.assertEqual((out["custom"]["work"], out["custom"]["brk"], out["custom"]["long"]), (50 * MIN, 10 * MIN, 30 * MIN))
        self.assertEqual(out["longCap"], 30 * MIN, "lange Pause höchstens 30 min")
        self.assertEqual((out["bad"]["work"], out["bad"]["brk"]), (W, B))
        self.assertEqual((out["reset"]["phase"], out["reset"]["round"], out["reset"]["done"]), ("work", 1, 0))

    def test_lange_pause_nie_kuerzer_als_die_kurze(self):
        out = run_fx("console.log(JSON.stringify([5, 10, 12, 30, 40, 90].map((m) => x.pomoNew(null, m * 60000).long / 60000)));")
        self.assertEqual(out, [15, 30, 30, 30, 40, 90], "dreimal so lang, höchstens 30 min, aber nie kürzer als die Pause")
        for lang in ("de", "en"):
            text = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]["timer_info"]
            with self.subTest(lang=lang):
                self.assertRegex(text, r"nie kürzer als die normale Pause|never shorter than the normal break")
        self.assertIn("nie kürzer als die normale Pause", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_naechste_phase_genau_am_ende(self):
        out = run_fx("""
          const p0 = x.pomoNew(25 * 60000, 5 * 60000);
          const t0 = c.timerToggle(c.timerNew(x.pomoPhaseMs(p0)), 1000);   // Start bei performance.now() = 1 s
          const at = (now) => { const r = x.pomoAdvance(p0, t0, now); return [r.pomo.phase, r.pomo.round, r.pomo.done, r.steps,
            c.timerRead(r.timer, now).remaining, r.timer.state]; };
          const paused = c.timerToggle(t0, 5000);
          console.log(JSON.stringify({
            before: at(1000 + 25 * 60000 - 1), end: at(1000 + 25 * 60000), later: at(1000 + 27 * 60000),
            // Tab lange im Hintergrund: 25 + 5 + 25 + 5 + 25 + 5 + 25 min → lange Pause, 2 min darin
            hidden: at(1000 + 117 * 60000),
            paused: x.pomoAdvance(p0, paused, 9e9).steps,
          }));
        """)
        self.assertEqual(out["before"], ["work", 1, 0, 0, 1, "running"])
        self.assertEqual(out["end"], ["break", 1, 1, 1, 5 * MIN, "running"], "Pause beginnt genau am Ende der Arbeit")
        self.assertEqual(out["later"], ["break", 1, 1, 1, 3 * MIN, "running"])
        self.assertEqual(out["hidden"], ["long", 4, 4, 7, 13 * MIN, "running"])
        self.assertEqual(out["paused"], 0, "angehalten: keine Phase vergeht")


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class EingebauteCountdownsTest(unittest.TestCase):
    """Referenzwerte: Unix- und NTP-Zeitpunkte aus datetime, Zeitumstellungen aus zoneinfo (nicht aus Intl)."""

    def test_feste_zeitpunkte(self):
        out = run_fx("""
          const now = Date.UTC(2026, 10, 23, 12);
          console.log(JSON.stringify({ unix: x.goalTarget("unix", now), ntp: x.goalTarget("ntp", now),
            y2038: x.goalTarget("y2038", now), consts: [x.UNIX_2E9_MS, x.NTP_ERA_MS, x.Y2038_MS], bad: [x.goalTarget("nope", now), x.goalTarget("unix", NaN)], goals: k.GOALS }));
        """)
        unix = ms(datetime.datetime.fromtimestamp(2_000_000_000, UTC))
        ntp = ms(datetime.datetime(1900, 1, 1, tzinfo=UTC) + datetime.timedelta(seconds=2 ** 32))
        y2038 = ms(datetime.datetime.fromtimestamp(2 ** 31, UTC))
        self.assertEqual((out["unix"], out["ntp"], out["y2038"]), (unix, ntp, y2038))
        self.assertEqual(out["consts"], [unix, ntp, y2038])
        self.assertEqual(y2038, ms(datetime.datetime(2038, 1, 19, 3, 14, 8, tzinfo=UTC)), "Jahr-2038-Problem")
        self.assertEqual(ntp, ms(datetime.datetime(2036, 2, 7, 6, 28, 16, tzinfo=UTC)))
        self.assertEqual(out["bad"], [None, None], "NaN wird in JSON zu null")
        self.assertEqual(out["goals"], ["newyear", "dst", "unix", "ntp", "y2038"])

    def test_neujahr_in_der_zone_des_servers(self):
        import zoneinfo
        berlin = zoneinfo.ZoneInfo("Europe/Berlin")
        tokyo = zoneinfo.ZoneInfo("Asia/Tokyo")
        cases = {
            "nov": (ms(datetime.datetime(2026, 11, 23, 12, tzinfo=UTC)), "Europe/Berlin"),
            "silvester": (ms(datetime.datetime(2026, 12, 31, 22, 59, 59, tzinfo=UTC)), "Europe/Berlin"),
            "halb1": (ms(datetime.datetime(2027, 1, 1, 0, 30, tzinfo=berlin)), "Europe/Berlin"),
            "nach1h": (ms(datetime.datetime(2027, 1, 1, 1, 0, tzinfo=berlin)), "Europe/Berlin"),
            "tokyo": (ms(datetime.datetime(2026, 12, 31, 15, 30, tzinfo=UTC)), "Asia/Tokyo"),
        }
        out = run_fx(f"""
          const cases = {json.dumps(cases)};
          const res = {{}};
          for (const [name, [now, zone]] of Object.entries(cases)) res[name] = x.goalTarget("newyear", now, zone);
          console.log(JSON.stringify(res));
        """)
        ny27 = ms(datetime.datetime(2027, 1, 1, tzinfo=berlin))
        self.assertEqual(out["nov"], ny27)
        self.assertEqual(out["silvester"], ny27)
        self.assertEqual(out["halb1"], ny27, "eine Stunde lang bleibt Neujahr stehen (Überzeit)")
        self.assertEqual(out["nach1h"], ms(datetime.datetime(2028, 1, 1, tzinfo=berlin)))
        self.assertEqual(out["tokyo"], ms(datetime.datetime(2027, 1, 1, tzinfo=tokyo)), "Tokio ist seit 30 min im neuen Jahr")

    def test_naechste_zeitumstellung_gegen_zoneinfo(self):
        start = datetime.datetime(2026, 1, 10, tzinfo=UTC)
        zones = ("Europe/Berlin", "America/New_York", "Australia/Sydney", "America/Santiago")
        ref = {zone: transitions(zone, start, 4) for zone in zones}
        probes = {zone: [ms(start)] + [t + 1000 for t in ref[zone][:3]] + [t - 1000 for t in ref[zone][:3]]
                  for zone in zones}
        out = run_fx(f"""
          const probes = {json.dumps(probes)};
          const res = {{}};
          // ohne Haltezeit: immer die nächste Umstellung
          for (const [zone, list] of Object.entries(probes)) res[zone] = list.map((now) => x.goalTarget("dst", now, zone, 0));
          const t0 = {ref["Europe/Berlin"][0]};
          console.log(JSON.stringify({{ res,
            hold: [x.goalTarget("dst", t0 + 30 * 60000, "Europe/Berlin"), x.goalTarget("dst", t0 + 61 * 60000, "Europe/Berlin")],
            none: [x.goalTarget("dst", {ms(start)}, "Asia/Tokyo"), x.goalTarget("dst", {ms(start)}, "UTC")],
            recent: x.recentOffsetChange(t0 + 5000, "Europe/Berlin", 60000),
          }}));
        """)
        for zone in zones:
            with self.subTest(zone=zone):
                r = ref[zone]
                self.assertEqual(out["res"][zone], [r[0], r[1], r[2], r[3], r[0], r[1], r[2]])
        berlin = ref["Europe/Berlin"]
        self.assertEqual(berlin[0], ms(datetime.datetime(2026, 3, 29, 1, tzinfo=UTC)))
        self.assertEqual(berlin[1], ms(datetime.datetime(2026, 10, 25, 1, tzinfo=UTC)))
        self.assertEqual(out["hold"], [berlin[0], berlin[1]], "eine Stunde Überzeit, danach die nächste")
        self.assertEqual(out["none"], [None, None], "ohne Sommerzeit keine Umstellung")
        self.assertEqual(out["recent"], berlin[0])

    def test_rechnet_wie_until_mit_ueberzeit(self):
        out = run_fx("""
          const v = (now) => c.countdownView(x.goalTarget("unix", now) - now, { warn: [300, 60, 10] });
          console.log(JSON.stringify([v(x.UNIX_2E9_MS - 9500), v(x.UNIX_2E9_MS + 42000)].map((r) => [r.phase, r.level, r.text])));
        """)
        self.assertEqual(out, [["before", "final", "−00:10"], ["over", "over", "+00:00:42"]])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class EigeneCountdownsTest(unittest.TestCase):
    def test_liste_aus_dem_speicher(self):
        good = [{"until": "20:15", "label": "Tagesschau"}, {"until": "2026-12-31T23:59", "label": "Silvester"}]
        hostile = [
            {"until": "20:15", "label": "<script>alert(1)</script>"}, {"until": "javascript:x", "label": "A"},
            {"until": "25:00", "label": "B"}, {"until": "2026-02-31T10:00", "label": "C"}, {"until": "20:15", "label": ""},
            {"until": "20:15", "label": "x" * 25}, {"until": "20:15", "label": "a‮b"}, {"until": 2015, "label": "D"},
            "20:15", None, {"until": "20:15", "label": "Tagesschau"}, {"until": "20:15", "label": "E", "style": "red"},
        ]
        many = [{"until": f"1{i}:00", "label": f"T{i}"} for i in range(9)]
        out = run_fx(f"""
          const good = {json.dumps(good)}, hostile = {json.dumps(hostile)}, many = {json.dumps(many)};
          const listed = x.ownList(JSON.stringify([...good, ...hostile]));
          let list = [];
          for (const item of many) list = x.ownAdd(list, item).list;
          const again = x.ownAdd(list, many[6]);
          console.log(JSON.stringify({{
            listed, many: list.map((i) => i.label), again: again.list.map((i) => i.label),
            bad: x.ownAdd(list, {{ until: "x", label: "y" }}), trimmed: x.ownAdd([], {{ until: " 20:15 ", label: " Hallo " }}).list,
            text: x.ownText(good), empty: x.ownText([]), removed: x.ownRemove(good, 0),
            junk: ["", "{{", "null", "{{}}", "[1,2]", JSON.stringify(good).padEnd(2001, " ")].map((t) => x.ownList(t)),
            key: x.OWN_KEY, max: x.OWN_MAX,
          }}));
        """)
        self.assertEqual(out["listed"][:2], good)
        self.assertEqual(out["listed"][2:], [{"until": "20:15", "label": "E"}], "fremde Felder fallen weg, der Rest gilt")
        self.assertEqual(out["many"], ["T8", "T7", "T6", "T5", "T4"], "höchstens fünf, die neuesten zuerst")
        self.assertEqual(out["again"], ["T6", "T8", "T7", "T5", "T4"], "gleicher Countdown rückt nach vorn")
        self.assertFalse(out["bad"]["ok"])
        self.assertEqual(out["trimmed"], [{"until": "20:15", "label": "Hallo"}])
        self.assertEqual(json.loads(out["text"]), good)
        self.assertIsNone(out["empty"])
        self.assertEqual(out["removed"], good[1:])
        self.assertEqual(out["junk"], [[], [], [], [], [], []])
        self.assertEqual((out["key"], out["max"]), ("ntp-gui-clock-countdowns", 5))


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class NachtmodusTest(unittest.TestCase):
    def test_zeitplan_und_hand(self):
        out = run_fx("""
          const night = { from: 22, to: 6 }, day = { from: 8, to: 17 };
          console.log(JSON.stringify({
            night: [21, 22, 23, 0, 5, 6, 12].map((h) => x.nightScheduled(night, h)),
            day: [7, 8, 16, 17].map((h) => x.nightScheduled(day, h)),
            none: x.nightScheduled(null, 3),
            keep: x.nightOverride({ scheduled: true, prev: true, override: false }),
            flip: x.nightOverride({ scheduled: false, prev: true, override: false }),
            manual: x.nightOverride({ scheduled: null, prev: null, override: true }),
            views: [
              x.nightView({ scheduled: true }), x.nightView({ scheduled: true, override: false }),
              x.nightView({ scheduled: false, override: true, red: true, level: 60 }), x.nightView({ scheduled: true, eink: true }),
              x.nightView({ scheduled: null, override: null }), x.nightView({ scheduled: true, level: 5 }),
              x.nightView({ scheduled: true, level: 99 }),
            ],
          }));
        """)
        self.assertEqual(out["night"], [False, True, True, True, True, False, False])
        self.assertEqual(out["day"], [False, True, True, False])
        self.assertIsNone(out["none"])
        self.assertFalse(out["keep"], "von Hand aus bleibt aus, solange der Zeitplan nicht wechselt")
        self.assertIsNone(out["flip"], "Wechsel des Zeitplans hebt die Hand-Einstellung auf")
        self.assertTrue(out["manual"], "ohne Zeitplan bleibt die Hand-Einstellung")
        self.assertEqual(out["views"], [
            {"on": True, "mode": "night", "level": 0.4}, {"on": False, "mode": None, "level": 0.4},
            {"on": True, "mode": "red", "level": 0.6}, {"on": False, "mode": None, "level": 0.4},
            {"on": False, "mode": None, "level": 0.4}, {"on": True, "mode": "night", "level": 0.2},
            {"on": True, "mode": "night", "level": 0.8}])

    def test_stunde_in_der_ortszeit_des_geraets(self):
        # 2026-07-01 20:30 UTC: in Berlin 22 Uhr (Sommerzeit), in New York 16 Uhr, in UTC 20 Uhr – unabhängig davon,
        # welche Zone groß angezeigt wird (UTC groß, Design tc in der Zone des Servers).
        at = ms(datetime.datetime(2026, 7, 1, 20, 30, tzinfo=UTC))
        want = {"Europe/Berlin": [22, True], "America/New_York": [16, False], "UTC": [20, False]}
        for zone, expected in want.items():
            with self.subTest(zone=zone):
                out = run_fx(f"const h = x.nightHour({at}); console.log(JSON.stringify([h, x.nightScheduled({{ from: 22, to: 6 }}, h)]));",
                             tz=zone)
                self.assertEqual(out, expected)
        self.assertEqual(run_fx("console.log(JSON.stringify([x.nightHour(NaN), x.nightHour(null)]));"), [None, None])
        js = (JS / "clock.js").read_text(encoding="utf-8")
        self.assertIn("fx.nightScheduled(params.dim, fx.nightHour(serverMs()))", js)
        self.assertIn("volle Stunden der Ortszeit dieses Geräts", (JS / "clockkit.js").read_text(encoding="utf-8"))
        self.assertNotIn("angezeigten Zeit", (JS / "clockkit.js").read_text(encoding="utf-8"))

    def test_parameter_dim(self):
        values = ["22-6", "6-22", "0-23", "7-7", "24-1", "22:30-6", "22-6 ", "-1-2", "22-", "22", "22-6-1", "022-6",
                  "٢٢-٦", "1-2"]
        out = run_fx(f"""
          console.log(JSON.stringify({json.dumps(values)}.map((v) => {{
            const p = k.parseParams("?" + new URLSearchParams([["dim", v]]).toString());
            return p.dim ? [p.dim.from, p.dim.to] : null; }})));
        """)
        want = [[22, 6], [6, 22], [0, 23], None, None, None, None, None, None, None, None, None, None, [1, 2]]
        self.assertEqual(dict(zip(values, out)), dict(zip(values, want)))
        for value, expected in zip(values, want):
            with self.subTest(value=value):
                if expected:
                    self.assertEqual(clockprofiles.check_value("dim", value), value)
                else:
                    with self.assertRaises(clockprofiles.ProfileError):
                        clockprofiles.check_value("dim", value)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class BedienungTest(unittest.TestCase):
    """Bedienelemente nie in Studio-, Kachel- und Kiosk-Voreinstellungen, mit lock=1 und in einer OBS-Browserquelle."""

    def test_regel_und_voreinstellungen(self):
        presets = {name: preset["params"] for name, preset in clockprofiles.PRESETS.items()}
        out = run_fx(f"""
          const presets = {json.dumps(presets)};
          const ctl = (q, obs = false) => {{ const p = k.parseParams(q);
            return x.funControls({{ fun: p.fun, kiosk: p.kiosk, lock: p.lock, layout: p.layout, obs, eink: p.eink }}); }};
          const res = {{}};
          for (const [name, params] of Object.entries(presets)) res[name] = ctl(new URLSearchParams(params).toString());
          console.log(JSON.stringify({{ presets: res, plain: ctl(""), obs: ctl("", true), fun0: ctl("?fun=0"), lock: ctl("?lock=1"),
            kiosk: ctl("?kiosk=1"), tile: ctl("?layout=tile"), eink: ctl("?eink=1"), bad: ctl("?fun=nein") }}));
        """)
        for name in ("studio", "tile", "banner"):
            with self.subTest(preset=name):
                self.assertFalse(out["presets"][name]["fun"])
                self.assertEqual(presets[name].get("fun"), "0")
        self.assertFalse(out["presets"]["tile"]["actions"])
        for name in ("kitchen", "workshop", "night", "nerd"):
            self.assertTrue(out["presets"][name]["fun"], name)
        self.assertEqual(out["plain"], {"actions": True, "fun": True})
        self.assertEqual(out["obs"], {"actions": False, "fun": False})
        self.assertEqual(out["fun0"], {"actions": True, "fun": False})
        self.assertEqual(out["lock"], {"actions": False, "fun": False})
        self.assertEqual(out["kiosk"], {"actions": True, "fun": False})
        self.assertEqual(out["tile"], {"actions": False, "fun": False})
        self.assertEqual(out["eink"], {"actions": True, "fun": False})
        self.assertEqual(out["bad"], {"actions": True, "fun": True}, "unzulässiger Wert: Standard")


class SchemaUndServerTest(unittest.TestCase):
    def test_server_allowlist_neue_parameter(self):
        self.assertEqual(clockprofiles.PARAMS["fun"], ("flag", {}))
        self.assertEqual(clockprofiles.PARAMS["goal"], ("enum", {"values": ("newyear", "dst", "unix", "ntp", "y2038")}))
        self.assertEqual(clockprofiles.PARAMS["dimlevel"], ("int", {"min": 20, "max": 80}))
        self.assertEqual(list(clockprofiles.PARAMS)[-1], "test")
        clean = clockprofiles.clean_profile({"title": "Küche", "params": {
            "fun": "1", "goal": "newyear", "pomo": "50m", "pause": "10m", "dim": "22-6", "dimlevel": "30", "dimred": "1"}})
        self.assertEqual(clean["params"], {"fun": "1", "goal": "newyear", "pomo": "50m", "pause": "10m", "dim": "22-6",
                                           "dimlevel": "30", "dimred": "1"})
        for name, bad in (("goal", "<script>"), ("goal", "Newyear"), ("pomo", "0m"), ("pomo", "25h"), ("pause", "5"),
                          ("dimlevel", "19"), ("dimlevel", "81"), ("dimred", "ja"), ("fun", "2")):
            with self.subTest(name=name, bad=bad):
                with self.assertRaises(clockprofiles.ProfileError):
                    clockprofiles.check_value(name, bad)
        stored = {"kueche": {"title": "Küche", "params": {"goal": "dst", "dim": "23-5", "secret": "x", "dimlevel": "999"}}}
        self.assertEqual(clockprofiles.public_profile("kueche", stored)["params"], {"goal": "dst", "dim": "23-5"},
                         "nur Allowlist-Werte im öffentlichen Lesepfad")

    def test_oeffentlich_nur_code(self):
        self.assertIn("/static/js/clockextras.js", server.CLOCK_PUBLIC_PATHS)
        text = (JS / "clockextras.js").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'^import .* from "\./([\w]+\.js)";', text, re.M), ["clockkit.js", "clockcount.js", "util.js"])
        self.assertNotRegex(text, r"fetch\(|XMLHttpRequest|sendBeacon|WebSocket|localStorage\.|document\.|window\.")
        self.assertNotRegex(text, r"setTimeout|setInterval|requestAnimationFrame")


class SeitenregelnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")

    def body(self, name):
        start = self.js.index(name)
        return self.js[start:self.js.index("\n}\n", start)]

    def test_bedienung_nach_dem_profil_und_nie_in_obs(self):
        self.assertIn('import * as fx from "./clockextras.js";', self.js)
        self.assertIn('typeof window.obsstudio === "object"', self.js)
        start = self.body("async function start()")
        self.assertLess(start.index("await loadProfile()"), start.index("CONTROLS = fx.funControls("))
        self.assertIn('$("mode-timer").hidden = !CONTROLS.fun;', start)
        self.assertIn('$("mode-night").hidden = !CONTROLS.fun;', start)
        self.assertIn('setHidden($("cd-actions"), Boolean(params.lock) || !CONTROLS.actions);', self.body("function renderCountdown("))
        self.assertIn("if (!CONTROLS.fun) return;", self.body("function toggleNight()"))
        self.assertRegex(self.html, r'id="mode-timer"[^>]* hidden')
        self.assertRegex(self.html, r'id="mode-night"[^>]* hidden')
        self.assertIn("body.is-obs :is(.clock-bar, .clock-panel, .clock-cd-actions) { display: none; }", self.css)

    def test_ton_nur_nach_klick(self):
        self.assertIn("endTone: false,", self.js)
        self.assertEqual(self.js.count("state.endTone = "), 1, "nur der Klick auf „Ton am Ende“ schaltet ihn ein")
        self.assertIn('state.endTone = $("timer-tone").checked;', self.body("function toggleEndTone()"))
        self.assertIn("countdownAudio(true)", self.body("function toggleEndTone()"))
        self.assertNotIn("endTone", self.body("function store("))

    def test_ton_im_hintergrund_vorausgeplant(self):
        out = run_fx("""
          const clock = { audio: 10, server: 1_000_000 }, target = 1_000_000 + 25 * 60000;
          const plan = (hidden) => c.planCountdownTones(clock, target, 3, { horizonMs: c.toneHorizonMs(hidden) })
            .map((t) => [t.k, Math.round(t.at * 1000) / 1000, t.kind]);
          console.log(JSON.stringify({ visible: plan(false), hidden: plan(true), h: [c.toneHorizonMs(false), c.toneHorizonMs(true)],
            again: c.planCountdownTones(clock, target, 3, { horizonMs: Infinity, lastK: 0 }) }));
        """)
        self.assertEqual(out["visible"], [], "sichtbar: nur 1,5 s voraus")
        self.assertEqual(out["hidden"], [[3, 1507.0, "count"], [2, 1508.0, "count"], [1, 1509.0, "count"], [0, 1510.0, "long"]],
                         "im Hintergrund alle Töne bis zum Ziel, in Audiozeit")
        self.assertEqual(out["h"][0], 1500)
        self.assertIsNone(out["h"][1], "Infinity (JSON null)")
        self.assertEqual(out["again"], [], "schon geplante Töne nicht doppelt")
        self.assertIn("cd.toneHorizonMs(document.hidden)", self.body("function countdownTones("))
        vis = self.js[self.js.index('document.addEventListener("visibilitychange"'):]
        self.assertIn("if (document.hidden && state.cdTone) renderCountdown();", vis[:vis.index("\n});")])

    def test_speicher_gesperrt_ehrliche_meldung(self):
        body = self.body("function store(")
        self.assertIn("return window.localStorage.getItem(key) === value;", body)
        self.assertIn("return value === undefined ? null : false;", body)
        self.assertIn("return saved;", self.body("function saveOwn("))
        self.assertIn('timerStatus(t(saveOwn(result.list) ? "clock.own_saved" : "clock.own_unsaved"));', self.body("function addOwn("))
        for lang in ("de", "en"):
            data = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
            self.assertTrue(data["own_unsaved"], lang)

    def test_kuerzel_n_nur_mit_spielereien(self):
        self.assertRegex(self.html, r'<dt id="keys-n-key"><kbd>N</kbd></dt><dd id="keys-n" ')
        start = self.body("async function start()")
        self.assertIn('$("keys-n-key").hidden = !CONTROLS.fun;', start)
        self.assertIn('$("keys-n").hidden = !CONTROLS.fun;', start)

    def test_ende_in_streifen_und_kachel_und_knoepfe_im_querformat(self):
        self.assertIn(':root[data-cd-end] .clock-stage:is([data-layout="strip"], [data-layout="tile"]) .clock-cd-state { display: inline;',
                      self.css)
        self.assertIn("@media (max-height: 320px) and (max-width: 600px) { #mode-timer, #mode-night { display: none; } }", self.css)
        self.assertNotIn("@media (max-height: 320px) { #mode-timer", self.css, "Handys im Querformat behalten Timer und Nacht")
        self.assertIn(".clock-timer-field #own-until { width: 19em; }", self.css)

    def test_ende_deutlich_ohne_blinken(self):
        block = self.css[self.css.index("/* --- Studiouhr C1"):]
        self.assertNotRegex(block, r"animation|transition|@keyframes|blink|filter:|url\(")
        self.assertIn(":root[data-cd-end] .clock-cd { outline:", block)
        self.assertIn('if (ended) status = t("clock.cd_end");', self.body("function renderCountdown("))
        self.assertIn(":root[data-night] :is(.clock-stage, .clock-band, .clock-signal, .clock-egg) { opacity: var(--night, 0.4); }",
                      block)
        self.assertNotRegex(block, r":root\[data-night\][^{]*\.clock-bar", "die Leiste blendet sich im Leerlauf über opacity aus")

    def test_nachtmodus_kontrast_und_vorrang(self):
        block = re.search(r':root\[data-mode="night"\] \{([^}]*)\}', self.css).group(1)
        var = dict(re.findall(r"--([\w-]+): (#[0-9a-f]{6})", block))
        script = json.dumps([[var["ink"], var["bg"]], [var["ink-2"], var["bg"]], [var["ink-unsure"], var["bg"]]])
        mods = json.dumps((JS / "clockkit.js").as_uri())
        if shutil.which("node"):
            res = subprocess.run(["node", "--input-type=module", "-e",
                                  f"import * as k from {mods}; console.log(JSON.stringify({script}.map(([a, b]) => k.contrastRatio(a, b))));"],
                                 capture_output=True, text=True, timeout=60)
            ink, ink2, unsure = json.loads(res.stdout)
            self.assertGreaterEqual(ink, 4.5)
            self.assertGreaterEqual(ink2, 4.5)
            self.assertGreaterEqual(unsure, 3.0)
        self.assertIn("@media (prefers-contrast: more) {\n  :root[data-night] :is(.clock-stage, .clock-band, .clock-signal, "
                      ".clock-egg) { opacity: max(var(--night, 0.4), 0.6); }", self.css)
        if shutil.which("node"):
            # Tatsächlicher Kontrast gedimmt (Deckkraft über Schwarz): bewusst dokumentiert, nicht verschleiert.
            def dim(color, level):
                return "#" + "".join(f"{round(int(color[i:i + 2], 16) * level):02x}" for i in (1, 3, 5))
            pairs = [[dim(var["ink"], lv), "#000000"] for lv in (0.4, 0.2, 0.6)] + [[dim(var["ink-2"], 0.4), "#000000"]]
            res = subprocess.run(["node", "--input-type=module", "-e",
                                  f"import * as k from {mods}; console.log(JSON.stringify({json.dumps(pairs)}.map(([a, b]) => k.contrastRatio(a, b))));"],
                                 capture_output=True, text=True, timeout=60)
            at40, at20, at60, ink2_40 = json.loads(res.stdout)
            self.assertAlmostEqual(at40, 2.6, delta=0.1)
            self.assertAlmostEqual(at20, 1.4, delta=0.1)
            self.assertAlmostEqual(ink2_40, 2.1, delta=0.15)
            self.assertGreaterEqual(at60, 4.5, "prefers-contrast: more – mindestens 60 % reichen für 4,5:1")
            self.assertIn("etwa 2,6:1", self.css)
            self.assertIn("etwa 2,6:1", (ROOT / "README.md").read_text(encoding="utf-8"))
        body = self.body("function applyModes()")
        self.assertLess(body.index('if (params.eink) root.dataset.mode = "eink";'), body.index("else if (night.on)"))
        self.assertLess(body.index("else if (night.on)"), body.index('else if (red) root.dataset.mode = "red";'))
        self.assertIn('root.style.setProperty("--night", String(night.level));', body)
        self.assertIn("renderNight();", self.body("function tick()"))

    def test_panel_nur_text_und_eigene_countdowns_lokal(self):
        for name in ("function renderTimerPanel()", "function renderOwn()"):
            body = self.body(name)
            self.assertNotRegex(body, r"innerHTML|insertAdjacentHTML|outerHTML")
            self.assertIn("textContent", body)
        self.assertIn("link.clockHref(link.buildQuery({ until: own.until, label: own.label }, ZONES))", self.body("function renderOwn()"))
        self.assertIn("store(fx.OWN_KEY, text)", self.body("function saveOwn("))
        self.assertIn("state.own = fx.ownList(store(fx.OWN_KEY)", self.js)

    def test_kuerzel_n_und_texte(self):
        self.assertIn("n: toggleNight", self.body("function onKey(event)"))
        self.assertIn("<kbd>N</kbd>", self.html)
        for lang in ("de", "en"):
            data = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
            with self.subTest(lang=lang):
                for key in ("goal_name", "goal_label"):
                    self.assertEqual(sorted(data[key]), ["dst", "newyear", "ntp", "unix", "y2038"])
                for name in ("fun", "goal", "pomo", "pause", "dim", "dimlevel", "dimred"):
                    self.assertTrue(data["link"]["f"][name])
                self.assertTrue(data["link"]["group"]["night"])
                self.assertRegex(data["timer_info"], r"(offen|open)")

    def test_doku(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        help_text = (JS / "help-uhr.js").read_text(encoding="utf-8")
        for name, text in (("README", readme), ("help-uhr.js", help_text)):
            with self.subTest(name=name):
                for needle in ("Eieruhr", "Pomodoro", "?pomo=", "?goal=", "?dim=22-6", "dimlevel", "dimred", "fun=0", "OBS"):
                    self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
