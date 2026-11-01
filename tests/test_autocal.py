"""Tests für die automatische GPS-Kalibrierung (autocal.py)."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import autocal  # noqa: E402
import history  # noqa: E402

H = 3600.0
NOW = 1_800_000_000.0


def cfg(**over):
    base = {"gps_enable": True, "gps_autocal": "auto", "gps_autocal_max_step_ms": 5.0,
            "gps_autocal_min_hours": 6.0, "gps_offset": 0.05, "gps_delay": 0.2, "gps_refid": "GPS"}
    base.update(over)
    return base


def cal(**over):
    base = {"status": "ready", "bias": 0.02, "spread": 0.002, "samples": 2000,
            "duration_seconds": 8 * H, "current_offset": 0.05, "current_delay": 0.2,
            "suggested_offset": 0.07, "suggested_delay": 0.012,
            "reference": {"window_median": 3, "current_network": 3, "current_nts": 0}}
    base.update(over)
    return base


def ref(**over):
    base = {"window_median": 3, "current_network": 3, "current_nts": 0}
    base.update(over)
    return base


class DecideTest(unittest.TestCase):
    def test_off(self):
        d = autocal.decide(cfg(gps_autocal="off"), cal(), None, NOW)
        self.assertEqual(d["action"], "none")
        self.assertIn("ausgeschaltet", d["reason"])

    def test_gps_disabled(self):
        self.assertEqual(autocal.decide(cfg(gps_enable=False), cal(), None, NOW)["action"], "none")

    def test_status_gates(self):
        for status in ("insufficient", "preliminary", "calibrated", None, "weird"):
            d = autocal.decide(cfg(), cal(status=status), None, NOW)
            self.assertEqual(d["action"], "none", status)
            self.assertTrue(d["reason"])

    def test_min_hours(self):
        d = autocal.decide(cfg(), cal(duration_seconds=5 * H), None, NOW)
        self.assertEqual(d["action"], "none")
        self.assertIn("Mindest", d["reason"])
        d = autocal.decide(cfg(gps_autocal_min_hours=4), cal(duration_seconds=5 * H), None, NOW)
        self.assertEqual(d["action"], "apply")

    def test_gps_only_source(self):
        d = autocal.decide(cfg(), cal(reference=ref(current_network=0)), None, NOW)
        self.assertEqual(d["action"], "none")
        self.assertIn("einzige", d["reason"])
        d = autocal.decide(cfg(gps_autocal="suggest"), cal(reference=ref(current_network=0)), None, NOW)
        self.assertEqual(d["action"], "none")

    def test_missing_reference_is_refused(self):
        d = autocal.decide(cfg(), cal(reference=None), None, NOW)
        self.assertEqual(d["action"], "none")

    def test_single_source_needs_nts(self):
        one = ref(window_median=1, current_network=1)
        self.assertEqual(autocal.decide(cfg(), cal(reference=one), None, NOW)["action"], "none")
        one_nts = ref(window_median=1, current_network=1, current_nts=1)
        self.assertEqual(autocal.decide(cfg(), cal(reference=one_nts), None, NOW)["action"], "apply")
        # Ohne Fenster-Angabe zählen die aktuellen Quellen.
        cur = {"current_network": 2, "current_nts": 0}
        self.assertEqual(autocal.decide(cfg(), cal(reference=cur), None, NOW)["action"], "apply")

    def test_apply_step_limited(self):
        d = autocal.decide(cfg(), cal(), None, NOW)
        self.assertEqual(d["action"], "apply")
        self.assertAlmostEqual(d["new_offset"], 0.055)
        self.assertAlmostEqual(d["step_ms"], 5.0)
        self.assertAlmostEqual(d["target_offset"], 0.07)
        self.assertFalse(d["final_step"])
        # Kein letzter Schritt: Delay wird nicht verkleinert.
        self.assertEqual(d["new_delay"], 0.2)
        self.assertEqual(d["next_change_at"], NOW + autocal.AUTO_INTERVAL)

    def test_negative_bias(self):
        d = autocal.decide(cfg(), cal(bias=-0.012), None, NOW)
        self.assertEqual(d["action"], "apply")
        self.assertAlmostEqual(d["new_offset"], 0.045)
        self.assertAlmostEqual(d["step_ms"], -5.0)

    def test_final_step_takes_delay(self):
        d = autocal.decide(cfg(), cal(bias=0.003), None, NOW)
        self.assertEqual(d["action"], "apply")
        self.assertAlmostEqual(d["new_offset"], 0.053)
        self.assertTrue(d["final_step"])
        self.assertEqual(d["new_delay"], 0.012)

    def test_delay_never_shrinks_early_but_may_grow(self):
        d = autocal.decide(cfg(gps_delay=0.005), cal(current_delay=0.005, suggested_delay=0.02), None, NOW)
        self.assertEqual(d["new_delay"], 0.02)

    def test_threshold_minimum_1ms(self):
        d = autocal.decide(cfg(), cal(bias=0.0009, spread=0.0001), None, NOW)
        self.assertEqual(d["action"], "none")
        self.assertIn("Schwelle", d["reason"])

    def test_threshold_uses_effective_samples(self):
        # 8 h → 48 unabhängige Messungen; 3·20 ms/√48 ≈ 8,7 ms
        thr = autocal.threshold(0.02, 5000, 8 * H)
        self.assertAlmostEqual(thr, 3 * 0.02 / (48 ** 0.5))
        d = autocal.decide(cfg(), cal(bias=0.006, spread=0.02), None, NOW)
        self.assertEqual(d["action"], "none")
        d = autocal.decide(cfg(), cal(bias=0.010, spread=0.02), None, NOW)
        self.assertEqual(d["action"], "apply")
        # Wenige Messungen: samples begrenzt n_eff.
        self.assertAlmostEqual(autocal.threshold(0.01, 4, 10 * H), 3 * 0.01 / 2)

    def test_once_per_day(self):
        last = {"t": NOW - 23 * H, "kind": "auto", "old_offset": 0.045, "new_offset": 0.05}
        d = autocal.decide(cfg(), cal(), last, NOW)
        self.assertEqual(d["action"], "none")
        self.assertEqual(d["next_change_at"], NOW + H)
        last["t"] = NOW - 25 * H
        self.assertEqual(autocal.decide(cfg(), cal(), last, NOW)["action"], "apply")
        # Auch eine Rücknahme sperrt 24 h.
        back = {"t": NOW - 2 * H, "kind": "rollback", "old_offset": 0.055, "new_offset": 0.05}
        self.assertEqual(autocal.decide(cfg(), cal(), back, NOW)["action"], "none")

    def test_reversal_hysteresis(self):
        last = {"t": NOW - 2 * autocal.DAY, "kind": "auto", "old_offset": 0.045, "new_offset": 0.05}
        # Gegenrichtung: 1,5 ms < 2 × 1 ms
        d = autocal.decide(cfg(), cal(bias=-0.0015, spread=0.0005), last, NOW)
        self.assertEqual(d["action"], "none")
        self.assertIn("doppelte", d["reason"])
        # Gleiche Richtung: 1,5 ms ≥ 1 ms
        self.assertEqual(autocal.decide(cfg(), cal(bias=0.0015, spread=0.0005), last, NOW)["action"], "apply")
        # Nach 7 Tagen keine Hysterese mehr.
        last["t"] = NOW - 8 * autocal.DAY
        self.assertEqual(autocal.decide(cfg(), cal(bias=-0.0015, spread=0.0005), last, NOW)["action"], "apply")

    def test_suggest_mode_gives_full_target(self):
        d = autocal.decide(cfg(gps_autocal="suggest"), cal(), None, NOW)
        self.assertEqual(d["action"], "suggest")
        self.assertAlmostEqual(d["new_offset"], 0.07)
        self.assertEqual(d["new_delay"], 0.012)
        self.assertAlmostEqual(d["step_ms"], 20.0)
        # Die 24-h-Sperre gilt nur fürs automatische Ändern.
        last = {"t": NOW - H, "kind": "auto", "old_offset": 0.045, "new_offset": 0.05}
        self.assertEqual(autocal.decide(cfg(gps_autocal="suggest"), cal(), last, NOW)["action"], "suggest")

    def test_auto_downgrades_on_noise_or_huge_bias(self):
        d = autocal.decide(cfg(), cal(spread=0.03, samples=100000, duration_seconds=1000 * H, bias=0.05), None, NOW)
        self.assertEqual(d["action"], "suggest")
        self.assertIn("streuen", d["reason"])
        d = autocal.decide(cfg(gps_offset=0.0), cal(bias=0.8, current_offset=0.0), None, NOW)
        self.assertEqual(d["action"], "suggest")

    def test_offset_limits(self):
        d = autocal.decide(cfg(), cal(current_offset=1.9, bias=0.2), None, NOW)
        self.assertEqual(d["action"], "none")

    def test_bad_numbers(self):
        for bad in (float("nan"), float("inf"), None, "x", True):
            d = autocal.decide(cfg(), cal(bias=bad), None, NOW)
            self.assertEqual(d["action"], "none")


class ReferenceTest(unittest.TestCase):
    def test_reference_stats(self):
        samples = [
            {"t": 1, "sources": {"GPS": {"o": 0.1, "k": "#"}, "a": {"o": 0.0, "s": "*", "k": "^"},
                                 "b": {"o": 0.0, "s": "+", "k": "^"}, "c": {"o": 0.0, "s": "-", "k": "^"},
                                 "PPS": {"o": 0.0, "s": "+", "k": "#"}}},
            {"t": 2, "sources": {"GPS": {"o": 0.1}, "a": {"o": 0.0, "s": "*", "k": "^"}}},
            {"t": 3, "sources": {"GPS": {"o": 0.1}}},
            {"t": 4, "sources": {"a": {"o": 0.0, "s": "*", "k": "^"}}},
        ]
        stats = autocal.reference_stats(samples, "GPS")
        self.assertEqual(stats["window_samples"], 2)
        self.assertEqual(stats["window_median"], 1.5)
        self.assertEqual(stats["window_min"], 1)
        self.assertEqual(autocal.reference_stats([], "GPS")["window_median"], 0)

    def test_summarize_sources(self):
        sources = [
            {"name": "GPS", "mode": "#", "state": "*"},
            {"name": "1.2.3.4", "mode": "^", "state": "+", "authenticated": True},
            {"name": "5.6.7.8", "mode": "^", "state": "+", "auth": {"mode": "NTS"}},
            {"name": "9.9.9.9", "mode": "^", "state": "x", "authenticated": True},
            {"name": "10.0.0.1", "mode": "^", "state": "-"},
        ]
        s = autocal.summarize_sources(sources, "GPS")
        self.assertEqual(s, {"current_network": 2, "current_nts": 2, "gps_used": True})
        self.assertEqual(autocal.summarize_sources(None, "GPS")["current_network"], 0)

    def test_calibration_getter(self):
        t0 = NOW - 10 * H
        samples = [{"t": int(t0 + i * 60), "sources": {
            "GPS": {"o": 0.03, "s": "-", "k": "#"}, "a": {"o": 0.0, "s": "*", "k": "^"},
            "b": {"o": 0.0, "s": "+", "k": "^"}}} for i in range(600)]
        hist = mock.Mock()
        hist.snapshot.return_value = samples
        get = autocal.make_calibration_getter(hist, lambda: cfg(gps_offset=0.05))
        result = get(12 * H)
        self.assertEqual(result["status"], "ready")
        self.assertAlmostEqual(result["bias"], 0.03)
        self.assertNotIn("series", result)
        self.assertEqual(result["reference"]["window_median"], 2)


class Harness:
    """Abhängigkeiten für tick()/rollback() mit Aufzeichnung."""

    def __init__(self, calibration=None, sources=None, restart=True):
        self.calibration = calibration or cal()
        self.sources = sources if sources is not None else [
            {"name": "GPS", "mode": "#", "state": "-"},
            {"name": "a", "mode": "^", "state": "*"}, {"name": "b", "mode": "^", "state": "+"}]
        self.saved, self.events, self.reloads, self.windows = [], [], 0, []
        self.restart = restart
        self.target = None
        self.cfg = cfg()

    def deps(self):
        def get_calibration(window):
            self.windows.append(window)
            result = dict(self.calibration)
            result["current_offset"] = self.cfg["gps_offset"]
            result["current_delay"] = self.cfg["gps_delay"]
            if self.target is not None:  # echte Verspätung fest, Abweichung folgt dem Offset
                result["bias"] = round(self.target - self.cfg["gps_offset"], 6)
            result["reference"] = {"window_median": 2}
            return result

        def save_settings(changes):
            self.saved.append(dict(changes))
            self.cfg.update(changes)
            return {"changed": list(changes), "restart": self.restart}

        def reload():
            self.reloads += 1
            return True

        return {"get_calibration": get_calibration, "get_sources": lambda: self.sources,
                "save_settings": save_settings, "trigger_reload": reload,
                "emit_event": lambda *a: self.events.append(a)}


class TickTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "data", "autocal.json")
        self.h = Harness()
        env = mock.patch.dict(os.environ, {"WEB_READONLY": ""})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tick(self, now):
        return autocal.tick(self.h.cfg, now, deps=self.h.deps(), file=self.file)

    def state(self):
        with open(self.file, encoding="utf-8") as handle:
            return json.load(handle)

    def test_first_tick_only_observes(self):
        d = self.tick(NOW)
        self.assertEqual(d["action"], "none")
        self.assertIn("begonnen", d["reason"])
        self.assertEqual(self.h.saved, [])
        st = self.state()
        self.assertEqual(st["observed"]["offset"], 0.05)
        self.assertEqual(st["last_tick"], NOW)
        self.assertEqual(oct(os.stat(self.file).st_mode & 0o777), "0o600")

    def test_window_starts_after_settle(self):
        self.tick(NOW)
        self.tick(NOW + 7 * H)
        self.assertAlmostEqual(self.h.windows[-1], 7 * H - autocal.SETTLE_SECONDS)
        # Obergrenze: max(24 h, 2 × Mindestdauer)
        self.tick(NOW + 100 * H)
        self.assertAlmostEqual(self.h.windows[-1], autocal.DAY)

    def test_apply_then_wait_then_step_again(self):
        self.tick(NOW)
        d = self.tick(NOW + 7 * H)
        self.assertEqual(d["action"], "apply")
        self.assertEqual(self.h.saved, [{"gps_offset": 0.055}])
        self.assertEqual(self.h.reloads, 1)
        self.assertTrue(d["reload_triggered"])
        st = self.state()
        self.assertEqual(len(st["changes"]), 1)
        change = st["changes"][0]
        self.assertEqual((change["old_offset"], change["new_offset"], change["kind"]), (0.05, 0.055, "auto"))
        self.assertEqual(st["observed"], {"offset": 0.055, "since": NOW + 7 * H})
        self.assertEqual(self.h.events[-1][0], "calibration")
        self.assertEqual(self.h.events[-1][1], "info")
        # Sofort danach: Messung neu – keine weitere Änderung.
        d = self.tick(NOW + 8 * H)
        self.assertEqual(d["action"], "none")
        # Nach 6 h Messdauer, aber < 24 h seit der Änderung: noch gesperrt.
        d = self.tick(NOW + 7 * H + 20 * H)
        self.assertEqual(d["action"], "none")
        self.assertIn("24 h", d["reason"])
        d = self.tick(NOW + 7 * H + 25 * H)
        self.assertEqual(d["action"], "apply")
        self.assertEqual(self.h.cfg["gps_offset"], 0.06)

    def test_manual_change_restarts_measurement(self):
        self.tick(NOW)
        self.h.cfg["gps_offset"] = 0.06
        d = self.tick(NOW + 7 * H)
        self.assertEqual(d["action"], "none")
        self.assertIn("gerade geändert", d["reason"])
        self.assertEqual(self.h.saved, [])

    def test_internet_down_does_nothing(self):
        self.h.sources = [{"name": "GPS", "mode": "#", "state": "*"},
                          {"name": "a", "mode": "^", "state": "?"}]
        self.tick(NOW)
        d = self.tick(NOW + 7 * H)
        self.assertEqual(d["action"], "none")
        self.assertIn("einzige", d["reason"])
        self.assertEqual(self.h.saved, [])

    def test_sources_failure_refuses(self):
        deps = self.h.deps()
        deps["get_sources"] = mock.Mock(side_effect=RuntimeError("chronyc weg"))
        autocal.tick(self.h.cfg, NOW, deps=deps, file=self.file)
        d = autocal.tick(self.h.cfg, NOW + 7 * H, deps=deps, file=self.file)
        self.assertEqual(d["action"], "none")

    def test_suggest_emits_once(self):
        self.h.cfg["gps_autocal"] = "suggest"
        self.tick(NOW)
        for i in range(3):
            d = self.tick(NOW + (7 + i) * H)
            self.assertEqual(d["action"], "suggest")
        self.assertEqual(len(self.h.events), 1)
        self.assertEqual(self.h.saved, [])

    def test_readonly_downgrades(self):
        self.tick(NOW)
        with mock.patch.dict(os.environ, {"WEB_READONLY": "1"}):
            d = self.tick(NOW + 7 * H)
        self.assertEqual(d["action"], "suggest")
        self.assertIn("WEB_READONLY", d["reason"])
        self.assertEqual(self.h.saved, [])

    def test_save_failure_is_reported(self):
        deps = self.h.deps()
        deps["save_settings"] = mock.Mock(side_effect=ValueError("kaputt"))
        autocal.tick(self.h.cfg, NOW, deps=deps, file=self.file)
        d = autocal.tick(self.h.cfg, NOW + 7 * H, deps=deps, file=self.file)
        self.assertEqual(d["action"], "none")
        self.assertIn("kaputt", d["reason"])
        self.assertEqual(self.state()["changes"], [])

    def test_no_reload_when_not_needed(self):
        self.h.restart = False
        self.tick(NOW)
        self.tick(NOW + 7 * H)
        self.assertEqual(self.h.reloads, 0)

    def test_delay_on_final_step(self):
        self.h.calibration = cal(bias=0.003)
        self.tick(NOW)
        self.tick(NOW + 7 * H)
        self.assertEqual(self.h.saved, [{"gps_offset": 0.053, "gps_delay": 0.012}])

    def test_corrupt_state_file(self):
        os.makedirs(os.path.dirname(self.file))
        Path(self.file).write_text("{kaputt")
        self.assertEqual(self.tick(NOW)["action"], "none")
        self.assertIn("observed", self.state())


class RollbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "autocal.json")
        self.h = Harness()
        env = mock.patch.dict(os.environ, {"WEB_READONLY": ""})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_changes(self, n):
        t = NOW
        autocal.tick(self.h.cfg, t, deps=self.h.deps(), file=self.file)
        for _ in range(n):
            t += 25 * H
            d = autocal.tick(self.h.cfg, t, deps=self.h.deps(), file=self.file)
            self.assertEqual(d["action"], "apply")
        return t

    def rollback(self, steps=1, now=None):
        return autocal.rollback(steps, cfg=self.h.cfg, now=now or NOW + 1000 * H,
                                deps=self.h.deps(), file=self.file)

    def test_nothing_to_undo(self):
        with self.assertRaises(autocal.AutocalError):
            self.rollback()

    def test_undo_one_then_another(self):
        self.h.calibration = cal(bias=0.02)
        self.run_changes(2)
        self.assertEqual(self.h.cfg["gps_offset"], 0.06)
        result = self.rollback(1)
        self.assertEqual(result["restored_offset"], 0.055)
        self.assertEqual(self.h.cfg["gps_offset"], 0.055)
        self.assertTrue(result["reload_triggered"])
        result = self.rollback(1)
        self.assertEqual(result["restored_offset"], 0.05)
        with self.assertRaises(autocal.AutocalError):
            self.rollback(1)
        st = autocal.load(self.file)
        kinds = [c["kind"] for c in st["changes"]]
        self.assertEqual(kinds, ["auto", "auto", "rollback", "rollback"])
        self.assertTrue(all(c["rolled_back"] for c in st["changes"][:2]))
        self.assertEqual(self.h.events[-1][1], "warn")

    def test_undo_several_restores_delay(self):
        self.h.target = 0.058
        self.run_changes(2)  # 0.05 → 0.055 (Delay bleibt) → 0.058 (letzter Schritt: Delay 0.012)
        self.assertEqual(self.h.cfg["gps_delay"], 0.012)
        result = self.rollback(2)
        self.assertEqual(result["restored_offset"], 0.05)
        self.assertEqual(self.h.cfg["gps_delay"], 0.2)
        with self.assertRaises(autocal.AutocalError):
            self.rollback(5)

    def test_refuses_after_manual_change(self):
        self.run_changes(1)
        self.h.cfg["gps_offset"] = 0.1
        with self.assertRaises(autocal.AutocalError) as ctx:
            self.rollback()
        self.assertIn("von Hand", str(ctx.exception))
        status = autocal.api_status(self.h.cfg, NOW + 1000 * H, fresh=False, file=self.file)
        self.assertFalse(status["rollback"]["possible"])

    def test_bad_steps(self):
        self.run_changes(1)
        for bad in (0, -1, "x", None):
            with self.assertRaises(autocal.AutocalError):
                self.rollback(bad)

    def test_rollback_blocks_next_auto_change(self):
        t = self.run_changes(1)
        self.rollback(1, now=t + H)
        d = autocal.tick(self.h.cfg, t + 10 * H, deps=self.h.deps(), file=self.file)
        self.assertEqual(d["action"], "none")


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "autocal.json")
        self.h = Harness()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_status_shape(self):
        autocal.tick(self.h.cfg, NOW, deps=self.h.deps(), file=self.file)
        autocal.tick(self.h.cfg, NOW + 7 * H, deps=self.h.deps(), file=self.file)
        s = autocal.api_status(self.h.cfg, NOW + 8 * H, deps=self.h.deps(), file=self.file)
        for key in ("mode", "mode_label", "mode_text", "decision", "next_change_at", "changes",
                    "rollback", "last_tick", "next_tick_at", "max_step_ms", "min_hours"):
            self.assertIn(key, s)
        self.assertEqual(s["mode_label"], "automatisch")
        self.assertEqual(len(s["changes"]), 1)
        self.assertTrue(s["rollback"]["possible"])
        self.assertEqual(s["rollback"]["restores_offset"], 0.05)
        self.assertEqual(s["next_change_at"], NOW + 7 * H + autocal.DAY)
        self.assertEqual(s["next_tick_at"], NOW + 8 * H)
        json.dumps(s)  # JSON-tauglich
        # Vorschau ändert nichts.
        self.assertEqual(len(self.h.saved), 1)

    def test_status_without_state(self):
        s = autocal.api_status(cfg(gps_autocal="suggest"), NOW, fresh=False, file=self.file)
        self.assertEqual(s["mode"], "suggest")
        self.assertIsNone(s["next_change_at"])
        self.assertFalse(s["rollback"]["possible"])
        self.assertFalse(os.path.exists(self.file))

    def test_unknown_mode_is_off(self):
        s = autocal.api_status(cfg(gps_autocal="bogus"), NOW, fresh=False, file=self.file)
        self.assertEqual(s["mode"], "off")


class MaybeTickTest(unittest.TestCase):
    def test_hourly(self):
        calls = []
        with mock.patch.object(autocal, "tick", lambda c, n: calls.append(n) or {}), \
                mock.patch.object(autocal, "load", lambda *a: autocal._empty()), \
                mock.patch.dict(autocal._LAST_TICK, {"t": None}):
            autocal.maybe_tick(cfg(), NOW)
            autocal.maybe_tick(cfg(), NOW + 10)
            autocal.maybe_tick(cfg(), NOW + H + 1)
            autocal.maybe_tick(cfg(), NOW - 5 * H)  # Uhr zurückgesprungen
        self.assertEqual(calls, [NOW, NOW + H + 1, NOW - 5 * H])

    def test_never_raises(self):
        with mock.patch.object(autocal, "tick", mock.Mock(side_effect=RuntimeError("x"))), \
                mock.patch.dict(autocal._LAST_TICK, {"t": NOW - 2 * H}), \
                mock.patch("builtins.print"):
            self.assertIsNone(autocal.maybe_tick(cfg(), NOW))


class PrivacyTest(unittest.TestCase):
    def test_log_has_no_source_names(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        file = os.path.join(tmp, "autocal.json")
        h = Harness(sources=[{"name": "GPS", "mode": "#", "state": "-"},
                             {"name": "203.0.113.7", "mode": "^", "state": "*", "hostname": "ntp.example.org"},
                             {"name": "198.51.100.9", "mode": "^", "state": "+"}])
        with mock.patch.dict(os.environ, {"WEB_READONLY": ""}):
            autocal.tick(h.cfg, NOW, deps=h.deps(), file=file)
            autocal.tick(h.cfg, NOW + 7 * H, deps=h.deps(), file=file)
        text = Path(file).read_text() + json.dumps(h.events)
        for leak in ("203.0.113.7", "198.51.100.9", "example.org"):
            self.assertNotIn(leak, text)


class HelpKeysTest(unittest.TestCase):
    """Alle autocal_*-Schlüssel aus gps.js stehen in help-autocal.js und in dessen Gruppe."""

    def test_help_autocal(self):
        js = Path(__file__).resolve().parents[1] / "app" / "static" / "js"
        page = (js / "pages" / "gps.js").read_text(encoding="utf-8")
        helpfile = (js / "help-autocal.js").read_text(encoding="utf-8")
        import re
        used = set(re.findall(r"\"(autocal_[a-z_]+)\"", page))
        self.assertGreater(len(used), 5)
        body = helpfile.split("export const HELP_GROUP_AUTOCAL")[0]
        defined = set(re.findall(r"^\s{2}(autocal_[a-z_]+):\s*\{", body, re.M))
        group = helpfile.split("export const HELP_GROUP_AUTOCAL")[1]
        grouped = set(re.findall(r"\"(autocal_[a-z_]+)\"", group))
        self.assertEqual(used - defined, set())
        self.assertEqual(defined, grouped)


if __name__ == "__main__":
    unittest.main()
