"""1.6, T4: Pi-Zustand – Unterspannung, Drosselung, Takt, Lüfter (pistate.py).

Läuft mit nachgebautem sysfs (NTPGUI_SYS_ROOT bzw. root=…), ohne echten Pi. Akzeptanzkriterien:
  * Bitfeld 0x50005 → „Unterspannung jetzt und seit Start“, genau ein Ereignis, kein weiteres bei
    gleichem Wert.
  * x86 ohne die Dateien → keine Karte, keine Warnung, kein Fehler im Log.
"""

import contextlib
import io
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
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import events  # noqa: E402
import hardware  # noqa: E402
import history  # noqa: E402
import notify  # noqa: E402
import pistate  # noqa: E402

JS = ROOT / "app" / "static" / "js"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeSys:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    @property
    def path(self) -> str:
        return str(self.root)

    def throttled(self, value: str, *parts: str) -> None:
        parts = parts or ("devices", "platform", "soc", "soc:firmware")
        write(self.root.joinpath(*parts, "get_throttled"), value + "\n")

    def hwmon(self, n: int, name: str, **files: str) -> None:
        base = self.root / "class" / "hwmon" / f"hwmon{n}"
        write(base / "name", name + "\n")
        for key, value in files.items():
            write(base / key, value + "\n")

    def cpufreq(self, cur_khz: int, max_khz: int) -> None:
        base = self.root / "devices" / "system" / "cpu" / "cpu0" / "cpufreq"
        write(base / "scaling_cur_freq", f"{cur_khz}\n")
        write(base / "scaling_max_freq", f"{max_khz}\n")

    def cleanup(self):
        self.tmp.cleanup()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ParseTest(unittest.TestCase):
    def test_parse_throttled(self):
        self.assertEqual(pistate.parse_throttled("50005"), 0x50005)
        self.assertEqual(pistate.parse_throttled("0x50005\n"), 0x50005)
        self.assertEqual(pistate.parse_throttled("throttled=0x0"), 0)
        for bad in (None, "", "zz", "-1", "0x123456789"):
            self.assertIsNone(pistate.parse_throttled(bad), bad)

    def test_decode_0x50005(self):
        flags = pistate.decode(0x50005)
        self.assertEqual(flags["undervoltage"], {"now": True, "since_boot": True})
        self.assertEqual(flags["throttled"], {"now": True, "since_boot": True})
        self.assertEqual(flags["capped"], {"now": False, "since_boot": False})
        self.assertEqual(flags["soft_temp_limit"], {"now": False, "since_boot": False})

    def test_flag_text(self):
        self.assertEqual(pistate.flag_text({"now": True, "since_boot": True}), "jetzt und seit Start")
        self.assertEqual(pistate.flag_text({"now": True, "since_boot": None}), "jetzt")
        self.assertEqual(pistate.flag_text({"now": False, "since_boot": True}), "seit Start (jetzt nicht)")
        self.assertEqual(pistate.flag_text({"now": False, "since_boot": False}), "nein")
        self.assertIsNone(pistate.flag_text({"now": None, "since_boot": None}))


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.sys = FakeSys()

    def tearDown(self):
        self.sys.cleanup()

    def test_pi_with_bitfield_fan_and_cpufreq(self):
        self.sys.throttled("50005")
        self.sys.hwmon(0, "cpu_thermal", temp1_input="48000")
        self.sys.hwmon(1, "pwmfan", fan1_input="3120")
        self.sys.cpufreq(1_500_000, 2_400_000)
        state = pistate.read(self.sys.path)
        self.assertTrue(state["available"])
        self.assertEqual(state["sources"], ["get_throttled"])
        self.assertEqual(state["bits"], 0x50005)
        self.assertEqual(state["undervoltage"], {"now": True, "since_boot": True})
        self.assertEqual(state["fan_rpm"], 3120)
        self.assertEqual((state["freq_mhz"], state["freq_max_mhz"]), (1500, 2400))
        self.assertEqual(pistate.summary(state),
                         "Unterspannung jetzt und seit Start; Gedrosselt jetzt und seit Start")
        self.assertEqual(pistate.severity(state), 2)

    def test_root_override_from_environment(self):
        self.sys.throttled("0")
        with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": self.sys.path}):
            state = pistate.read()
        self.assertTrue(state["available"])
        self.assertEqual(pistate.summary(state), "Keine Unterspannung, keine Drosselung")
        self.assertEqual(pistate.severity(state), 0)

    def test_other_firmware_path_is_found(self):
        # Pi 5: Firmware-Knoten womöglich an anderer Stelle im Baum.
        self.sys.throttled("4", "devices", "platform", "soc@107c000000", "soc@107c000000:firmware")
        state = pistate.read(self.sys.path)
        self.assertTrue(state["available"])
        self.assertEqual(state["throttled"], {"now": True, "since_boot": False})
        self.assertEqual(pistate.severity(state), 1)

    def test_hwmon_rpi_volt_only(self):
        self.sys.hwmon(2, "rpi_volt", in0_lcrit_alarm="1")
        state = pistate.read(self.sys.path)
        self.assertTrue(state["available"])
        self.assertEqual(state["sources"], ["rpi_volt"])
        self.assertEqual(state["undervoltage"]["now"], True)
        self.assertIsNone(state["throttled"]["now"])  # ohne Bitfeld: keine Zeile, kein „nein“
        self.assertEqual(pistate.summary(state), "Unterspannung jetzt")

    def test_garbage_is_not_a_source(self):
        self.sys.throttled("kaputt")
        self.assertFalse(pistate.read(self.sys.path)["available"])

    def test_x86_without_pi_files_is_not_available(self):
        # PC: Lüfter und cpufreq gibt es, aber keine Pi-Quelle → keine Karte.
        self.sys.hwmon(0, "nct6775", fan1_input="900")
        self.sys.cpufreq(3_400_000, 4_200_000)
        state = pistate.read(self.sys.path)
        self.assertFalse(state["available"])
        self.assertIsNone(pistate.summary(state))
        self.assertIsNone(pistate.severity(state))

    def test_missing_root_is_quiet(self):
        state = pistate.read(os.path.join(self.sys.path, "gibt-es-nicht"))
        self.assertFalse(state["available"])


class EventTest(unittest.TestCase):
    def setUp(self):
        self.sys = FakeSys()
        self.clock = Clock()
        self.monitor = pistate.Monitor(clock=self.clock)
        self.events = []

    def tearDown(self):
        self.sys.cleanup()

    def emit(self, kind, level, title, data=None):
        self.events.append((kind, level, title, data))

    def step(self, value: str, seconds: float = 10.0):
        self.sys.throttled(value)
        self.clock.now += seconds
        return self.monitor.sample(self.emit, self.sys.path)

    def titles(self):
        return [e[2] for e in self.events]

    def test_0x50005_exactly_one_event_and_none_for_same_value(self):
        state = self.step("50005")
        self.assertEqual(pistate.flag_text(state["undervoltage"]), "jetzt und seit Start")
        self.assertEqual(self.titles().count("Unterspannung erkannt"), 1)
        self.assertEqual(self.titles().count("Takt gedrosselt"), 1)
        uv = next(e for e in self.events if e[2] == "Unterspannung erkannt")
        self.assertEqual((uv[0], uv[1]), ("pi", "warn"))
        self.assertIn("offizielle Netzteil", uv[3]["hint"])
        before = len(self.events)
        for _ in range(20):
            self.step("50005")
        self.assertEqual(len(self.events), before)

    def test_flicker_is_debounced_and_episode_ends_after_quiet(self):
        self.step("50005")
        self.events.clear()
        # Spannung flackert: kurz gut, wieder schlecht – kein zweites „erkannt“.
        self.step("50000", 30)
        self.step("50005", 30)
        self.step("50000", 30)
        self.assertEqual(self.events, [])
        # Erst nach QUIET_SECONDS ohne Unterspannung endet die Episode – genau einmal.
        self.step("50000", pistate.QUIET_SECONDS)
        self.assertEqual(sorted(self.titles()), ["Takt wieder frei", "Unterspannung vorbei"])
        self.assertTrue(all(e[1] == "info" for e in self.events))
        self.step("50000", pistate.QUIET_SECONDS)
        self.assertEqual(len(self.events), 2)
        # Neues Auftreten danach zählt wieder.
        self.step("50001")
        self.assertEqual(self.titles()[-1], "Unterspannung erkannt")

    def test_short_dip_between_samples_counts_via_since_bit(self):
        self.step("0")
        self.assertEqual(self.events, [])
        self.step("10000")
        self.assertEqual(self.titles(), ["Unterspannung erkannt"])
        self.assertFalse(self.events[0][3]["now"])

    def test_since_bit_at_start_alone_is_no_event(self):
        # Das war vor dem Start des Dashboards – die Karte zeigt es, das Protokoll nicht.
        state = self.step("50000")
        self.assertEqual(self.events, [])
        self.assertEqual(pistate.flag_text(state["undervoltage"]), "seit Start (jetzt nicht)")

    def test_rpi_volt_only_events_and_since(self):
        self.sys.hwmon(0, "rpi_volt", in0_lcrit_alarm="1")
        state = self.monitor.sample(self.emit, self.sys.path)
        self.assertEqual(self.titles(), ["Unterspannung erkannt"])
        self.sys.hwmon(0, "rpi_volt", in0_lcrit_alarm="0")
        self.clock.now += 10
        state = self.monitor.sample(self.emit, self.sys.path)
        self.assertEqual(pistate.flag_text(state["undervoltage"]), "seit Start (jetzt nicht)")
        self.assertEqual(len(self.events), 1)

    def test_x86_no_events_no_log(self):
        self.sys.hwmon(0, "k10temp", temp1_input="45000")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            for _ in range(3):
                state = self.monitor.sample(self.emit, self.sys.path)
            current = self.monitor.current(self.sys.path)
        self.assertFalse(state["available"])
        self.assertFalse(current["available"])
        self.assertEqual(self.events, [])
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.assertIsNone(self.monitor.metrics_state())

    def test_emit_failure_does_not_break_sampling(self):
        def broken(*args):
            raise RuntimeError("Datenbank weg")
        self.sys.throttled("50005")
        state = self.monitor.sample(broken, self.sys.path)
        self.assertTrue(state["available"])

    def test_metrics_state_only_when_fresh(self):
        self.step("50005")
        self.assertIsNotNone(self.monitor.metrics_state())
        self.monitor.last["t"] = time.time() - pistate.METRIC_MAX_AGE - 1
        self.assertIsNone(self.monitor.metrics_state())


class WiringTest(unittest.TestCase):
    def test_event_kind_and_notify(self):
        self.assertIn("pi", events.KINDS)
        self.assertEqual(notify.KIND_LABELS["pi"], "Pi-Zustand")
        self.assertEqual(notify.KIND_PAGES["pi"], "uhr/hardware")
        self.assertIn("pi", notify.RESOLVING_KINDS)  # „… vorbei“ schließt die Meldung
        diagnose = (JS / "pages" / "diagnose.js").read_text(encoding="utf-8")
        self.assertIn('pi: "Pi-Zustand"', diagnose)

    def test_history_column_is_backward_compatible(self):
        self.assertIn("pi_state", history._NUMERIC_TOP)
        merged = history.downsample([{"t": 1, "pi_state": 2}, {"t": 2, "pi_state": 0}, {"t": 3}], 1)
        self.assertEqual(merged[0]["pi_state"], 1.0)
        # Alte Punkte ohne das Feld bleiben gültig.
        merged = history.downsample([{"t": 1, "offset": 0.001}, {"t": 2, "offset": 0.003}], 1)
        self.assertNotIn("pi_state", merged[0])

    def test_history_sqlite_rollup_keeps_field(self):
        tmp = tempfile.mkdtemp()
        try:
            import store
            hist = history.History(None, path=os.path.join(tmp, "history.json.gz"),
                                   db_path=os.path.join(tmp, "test.db"))
            now = int(time.time())
            hist.add({"t": now - 20, "offset": 0.0, "pi_state": 2})
            hist.add({"t": now - 10, "offset": 0.0})
            hist.save(force=True)
            rows = hist.query(3600, 10)
            self.assertIn(2, [r.get("pi_state") for r in rows])
        finally:
            store.close_all()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_diagnostics_summary_includes_pi_state(self):
        import diagnostics
        out = diagnostics.summarize_history([{"t": 1, "pi_state": 0}, {"t": 2, "pi_state": 2}])
        self.assertEqual(out["metrics"]["pi_state"]["max"], 2)

    def test_collect_sample_writes_field_only_on_pi(self):
        import chrony
        import gps
        import ptp
        import server
        fake = FakeSys()
        try:
            fake.throttled("50005")
            patches = [mock.patch.object(chrony, "tracking", return_value={}),
                       mock.patch.object(chrony, "serverstats", return_value={}),
                       mock.patch.object(chrony, "clients", return_value=[]),
                       mock.patch.object(chrony, "merged_sources", return_value=[]),
                       mock.patch.object(gps, "enabled", return_value=False),
                       mock.patch.object(ptp, "enabled", return_value=False),
                       mock.patch.object(server.pistate, "MONITOR", pistate.Monitor()),
                       mock.patch.object(events, "emit")]
            for p in patches:
                p.start()
            try:
                with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": fake.path}):
                    sample = server.collect_sample()
                    self.assertEqual(sample["pi_state"], 2)
                    metrics = server.build_metrics()
                self.assertIn("ntpgui_pi_undervoltage 1", metrics)
                self.assertIn("ntpgui_pi_throttled 1", metrics)
                titles = [c.args[2] for c in events.emit.call_args_list if c.args and c.args[0] == "pi"]
                self.assertEqual(titles.count("Unterspannung erkannt"), 1)
                empty = os.path.join(fake.path, "leer")
                os.makedirs(empty)
                server.pistate.MONITOR.reset()
                with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": empty}):
                    sample = server.collect_sample()
                    metrics = server.build_metrics()
                self.assertNotIn("pi_state", sample)
                self.assertNotIn("ntpgui_pi_", metrics)
            finally:
                for p in reversed(patches):
                    p.stop()
        finally:
            fake.cleanup()


class HardwareCheckTest(unittest.TestCase):
    def state(self, bits):
        state = {"available": True, "sources": ["get_throttled"], "bits": bits, **pistate.decode(bits)}
        state["summary"] = pistate.summary(state)
        return state

    def test_row_with_undervoltage_names_power_supply(self):
        row = hardware._pi_power_row(self.state(0x50005))
        self.assertEqual((row["key"], row["status"]), ("pi_power", "limited"))
        self.assertIn("Unterspannung jetzt und seit Start", row["text"])
        self.assertIn("offizielle Netzteil", row["text"])

    def test_row_ok_and_throttled(self):
        self.assertEqual(hardware._pi_power_row(self.state(0))["status"], "ok")
        row = hardware._pi_power_row(self.state(0x40000))
        self.assertEqual(row["status"], "limited")
        self.assertIn("Hitze", row["text"])

    def test_insight_only_for_undervoltage(self):
        for bits, expected in ((0x50005, True), (0x40000, False), (0, False)):
            rep = {"pistate": self.state(bits), "matrix": [hardware._pi_power_row(self.state(bits))]}
            with mock.patch.object(hardware, "_REPORT", rep):
                keys = [i["key"] for i in hardware.cached_insights({})]
            self.assertEqual("hw_pi_power" in keys, expected, hex(bits))

    def test_report_on_x86_has_no_row(self):
        fake = FakeSys()
        try:
            fake.hwmon(0, "coretemp", temp1_input="40000")
            with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": fake.path}):
                state = hardware._pistate()
            self.assertFalse(state["available"])
        finally:
            fake.cleanup()

    def test_report_includes_pistate(self):
        fake = FakeSys()
        try:
            fake.throttled("50005")
            with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": fake.path}):
                rep = hardware.build_report({}, {})
            self.assertTrue(rep["pistate"]["available"])
            self.assertIn("pi_power", [r["key"] for r in rep["matrix"]])
            json.dumps(rep)  # geht so ins Diagnosepaket
        finally:
            fake.cleanup()

    def test_report_without_pi_has_no_row(self):
        fake = FakeSys()
        try:
            with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": fake.path}):
                rep = hardware.build_report({}, {})
            self.assertFalse(rep["pistate"]["available"])
            self.assertNotIn("pi_power", [r["key"] for r in rep["matrix"]])
        finally:
            fake.cleanup()


def mod(path: str) -> str:
    return json.dumps((JS / path).resolve().as_uri())


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class CardTest(unittest.TestCase):
    def run_js(self, body: str):
        import test_frontend_states as fs
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dom.mjs").write_text(fs.DOM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            script.write_text('import { text, withAttr, ctx } from "./dom.mjs";\n' + body, encoding="utf-8")
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_card_shows_undervoltage_now_and_since_start(self):
        state = {"available": True, "sources": ["get_throttled"], "bits": 0x50005, **pistate.decode(0x50005),
                 "freq_mhz": 1500, "freq_max_mhz": 2400, "fan_rpm": 3120}
        out = self.run_js(f"""
const hw = await import({mod("pages/hardware.js")});
const state = {json.dumps(state)};
const card = hw.pistateCard({{ pistate: state }});
const rows = [];
const walk = (n) => {{ if (!n) return; if (n.tagName === "DIV" && n.attrs.class === "kv") {{
  rows.push([n.childNodes[0].childNodes[0].textContent, n.childNodes[1].textContent]); }}
  for (const c of n.childNodes || []) walk(c); }};
walk(card);
const none = hw.pistateCard({{ pistate: {{ available: false, sources: [] }} }});
const missing = hw.pistateCard({{}});
const page = text(hw.render(ctx({{ data: (k) => k === "hardware" ? {{ generated: 1, matrix: [], warnings: [] }} : undefined }})));
console.log(JSON.stringify({{ rows, all: text(card), none, missing, page,
  styles: (() => {{ let k = 0; const w = (n) => {{ if (!n) return; if (n.attrs && "style" in n.attrs) k++;
    for (const c of n.childNodes || []) w(c); }}; w(card); return k; }})() }}));
""")
        rows = dict(out["rows"])
        self.assertEqual(rows["Unterspannung"], "jetzt und seit Start")
        self.assertEqual(rows["Gedrosselt"], "jetzt und seit Start")
        self.assertEqual(rows["Takt"], "1.500 MHz (höchstens 2.400 MHz)")
        self.assertEqual(rows["Lüfter"], "3.120 U/min")
        self.assertNotIn("Takt gedeckelt", rows)  # nie aufgetreten → keine Zeile
        self.assertIn("Pi-Zustand", out["all"])
        self.assertIn("offizielle Netzteil", out["all"])
        self.assertEqual(out["styles"], 0)
        self.assertIsNone(out["none"])
        self.assertIsNone(out["missing"])
        self.assertNotIn("Pi-Zustand", out["page"])

    def test_rpi_volt_only_shows_no_throttle_row(self):
        state = {"available": True, "sources": ["rpi_volt"], "bits": None,
                 "undervoltage": {"now": False, "since_boot": None}, "throttled": {"now": None, "since_boot": None},
                 "capped": {"now": None, "since_boot": None}, "soft_temp_limit": {"now": None, "since_boot": None}}
        out = self.run_js(f"""
const hw = await import({mod("pages/hardware.js")});
console.log(JSON.stringify({{ all: text(hw.pistateCard({{ pistate: {json.dumps(state)} }})) }}));
""")
        self.assertIn("Unterspannung", out["all"])
        self.assertNotIn("Gedrosselt", out["all"])
        self.assertNotIn("unbekannt", out["all"])


if __name__ == "__main__":
    unittest.main()


class T4ReviewTest(unittest.TestCase):
    """Befunde der unabhängigen Prüfung: Neustart ohne Doppelmeldung, Temperaturgrenze im Hardware-Check."""

    def test_restart_during_episode_emits_nothing(self):
        sample = {"bits": 0x50005, **pistate.decode(0x50005)}
        first = pistate.Monitor(clock=lambda: 100.0)
        with mock.patch("events.query", return_value=[]):
            out = first._update(dict(sample), 100.0)
        self.assertEqual([t for _, _, t, _ in out], ["Unterspannung erkannt", "Takt gedrosselt"])
        # gespeichertes Protokoll (neueste zuerst) nach dem ersten Lauf
        logged = [{"kind": "pi", "title": t, "data": d} for _, _, t, d in reversed(out)]
        restarted = pistate.Monitor(clock=lambda: 200.0)  # Dashboard neu gestartet, Episode läuft weiter
        with mock.patch("events.query", return_value=logged):
            self.assertEqual(restarted._update(dict(sample), 200.0), [])
            self.assertEqual(restarted._update(dict(sample), 260.0), [])

    def test_restart_after_episode_ended_meanwhile_closes_it(self):
        # Befund: Ist die Spannung während des Neustarts wieder gut, blieb „erkannt“ ohne „vorbei“ stehen.
        sample = {"bits": 0x50005, **pistate.decode(0x50005)}
        first = pistate.Monitor(clock=lambda: 100.0)
        with mock.patch("events.query", return_value=[]):
            out = first._update(dict(sample), 100.0)
        logged = [{"kind": "pi", "title": t, "data": d} for _, _, t, d in reversed(out)]
        good = {"bits": 0x50000, **pistate.decode(0x50000)}
        restarted = pistate.Monitor(clock=lambda: 200.0)
        with mock.patch("events.query", return_value=logged):
            self.assertEqual(restarted._update(dict(good), 200.0), [])
            self.assertEqual(restarted._update(dict(good), 200.0 + pistate.QUIET_SECONDS - 1), [])
            out = restarted._update(dict(good), 200.0 + pistate.QUIET_SECONDS)
        self.assertEqual([t for _, _, t, _ in out], ["Unterspannung vorbei", "Takt wieder frei"])
        # Ohne offene Episode im Protokoll: nichts zu schließen.
        fresh = pistate.Monitor(clock=lambda: 0.0)
        with mock.patch("events.query", return_value=[]):
            fresh._update(dict(good), 0.0)
            self.assertEqual(fresh._update(dict(good), 2 * pistate.QUIET_SECONDS), [])

    def test_restart_after_closed_episode_reports_again(self):
        sample = {"bits": 0x50005, **pistate.decode(0x50005)}
        logged = [{"kind": "pi", "title": "Unterspannung vorbei", "data": {"subject": "undervoltage"}},
                  {"kind": "pi", "title": "Unterspannung erkannt", "data": {"subject": "undervoltage"}}]
        mon = pistate.Monitor(clock=lambda: 0.0)
        with mock.patch("events.query", return_value=logged):
            out = mon._update(dict(sample), 0.0)
        self.assertIn("Unterspannung erkannt", [t for _, _, t, _ in out])

    def test_new_episode_after_start_still_reported(self):
        mon = pistate.Monitor(clock=lambda: 0.0)
        mon._update({"bits": 0, **pistate.decode(0)}, 0.0)
        out = mon._update({"bits": 0x50005, **pistate.decode(0x50005)}, 60.0)
        self.assertEqual([t for _, _, t, _ in out], ["Unterspannung erkannt", "Takt gedrosselt"])

    def test_soft_temp_limit_is_not_ok(self):
        import hardware
        row = hardware._pi_power_row({**pistate.decode(0x80008), "summary": None})
        self.assertEqual(row["status"], "limited")
