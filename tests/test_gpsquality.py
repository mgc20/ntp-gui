"""GPS ohne PPS und schwacher Empfang (1.5, Thema 3; Entscheidung E16): gpsquality.py,
das Zusammenfassen von Fix-Flattern zu „unstet“ (statewatch.py), die ehrliche
Fehlerschranke in chrony.conf (confgen.py) und der Delay-Vorschlag der Kalibrierung.

Replay „VK-162 drinnen“: tests/fixtures/gps_vk162_indoor.jsonl stammt aus vier
Aufzeichnungen eines Nutzers (Raspberry Pi 4, VK-162 ohne PPS, schwacher Empfang drinnen),
datenschutzgefiltert; die C/N0 der vier stärksten ist synthetisiert (siehe Kopfzeile).
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import apiv1  # noqa: E402
import confgen  # noqa: E402
import gps  # noqa: E402
import gpsquality  # noqa: E402
import history  # noqa: E402
import settings  # noqa: E402
import statewatch  # noqa: E402
import store  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gps_vk162_indoor.jsonl"
_PPS_DIR = tempfile.mkdtemp(prefix="gpsq-pps-")
PPS_DEV = os.path.join(_PPS_DIR, "pps0")          # vorhandenes „PPS-Gerät“ (leere Datei)
PPS_MISSING = os.path.join(_PPS_DIR, "pps-fehlt")  # eingestellt, aber nicht vorhanden


def setUpModule():
    Path(PPS_DEV).touch()


def tearDownModule():
    shutil.rmtree(_PPS_DIR, ignore_errors=True)
T0 = 1_800_000_000.0
H = 3600.0


def vk162_rows():
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if "_" not in item:
            rows.append(item)
    return rows


def vk162_samples(loops=1):
    """Messpunkte wie history.py sie speichert (GPS-Gruppe + Quellen), Zeit ab T0."""
    rows = vk162_rows()
    span = rows[-1]["t"] + 6.0
    out = []
    for loop in range(loops):
        for row in rows:
            sample = {"t": T0 + loop * span + row["t"],
                      "gps": {"mode": row["mode"], "used": row["used"], "seen": row["seen"], "cn4": row["cn4"]},
                      "sources": {}}
            if "gps_o" in row:
                sample["sources"]["GPS"] = {"o": row["gps_o"], "s": "-", "k": "#"}
                for i, offset in enumerate(row["net_o"]):
                    sample["sources"][f"net{i}"] = {"o": offset, "s": "*" if i == 0 else "+", "k": "^"}
            out.append(sample)
    return out


def outdoor_samples(hours=24.0, step=10.0):
    """Synthetisch „draußen“: 3D-Fix durchgehend, 9 Satelliten, 44 dB-Hz, GPS ± 3 ms um das Netz."""
    out = []
    n = int(hours * H / step)
    for i in range(n):
        wobble = ((i * 7919) % 13 - 6) / 2000.0  # deterministisch, ± 3 ms
        out.append({"t": T0 + i * step,
                    "gps": {"mode": 3, "used": 9, "seen": 12, "cn4": 44.0 + (i % 3)},
                    "sources": {"GPS": {"o": 0.001 + wobble, "s": "-", "k": "#"},
                                "ptb": {"o": 0.001, "s": "*", "k": "^"}}})
    return out


def cfg(**over):
    base = {"gps_enable": True, "gps_pps_device": "", "gps_pps_shm": False, "gps_delay": 0.03,
            "gps_precision": 0.1, "gps_select": "auto", "gps_refid": "GPS", "gps_bound_mode": "measured",
            "ntp_minsources": 1}
    base.update(over)
    return base


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        self.events, self.reloads = [], []
        gpsquality.configure(trigger_reload=lambda: self.reloads.append(1) or True,
                             emit=lambda *a, **k: self.events.append(a))
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        gpsquality._DEPS.update(history=None, trigger_reload=None, emit=None)
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)


# =========================================================================================
class Cn0Test(unittest.TestCase):
    def test_top4_median_ignores_untracked(self):
        sats = [{"ss": v} for v in (0, 0, 12, 41, 38, 45, 30, 20)]
        self.assertEqual(gpsquality.cn0_top4(sats), 39.5)  # 45, 41, 38, 30 → Median 39,5

    def test_fewer_than_four_and_parsed_keys(self):
        self.assertEqual(gpsquality.cn0_top4([{"snr": 25}, {"snr": 31}]), 28.0)
        self.assertIsNone(gpsquality.cn0_top4([{"ss": 0}, {"ss": None}, "kaputt"]))
        self.assertIsNone(gpsquality.cn0_top4(None))

    def test_parse_reports_carries_top4(self):
        state = gps.parse_reports({"TPV": {"mode": 3}, "SKY": {"satellites": [
            {"PRN": 1, "ss": 40, "used": True}, {"PRN": 2, "ss": 35, "used": True},
            {"PRN": 3, "ss": 30, "used": True}, {"PRN": 4, "ss": 25, "used": True}, {"PRN": 5, "ss": 0}]}})
        self.assertEqual(state["cn0_top4"], 32.5)


# =========================================================================================
class AssessTest(unittest.TestCase):
    def test_replay_vk162_indoor_is_red_with_reasons(self):
        samples = vk162_samples()
        result = gpsquality.assess(samples, now=samples[-1]["t"] + 1)
        self.assertEqual(result["level"], "red")
        keys = {r["key"]: r["level"] for r in result["reasons"]}
        self.assertEqual(keys.get("changes"), "red")   # Fix kommt und geht
        self.assertEqual(keys.get("cn0"), "red")       # ~21 dB-Hz
        self.assertIn("fix", keys)
        self.assertGreater(result["changes_per_hour"], gpsquality.CHANGES_RED)
        self.assertLess(result["fix_share"], gpsquality.FIX_YELLOW)
        self.assertRegex(result["sentence"], r"^Fix \d+ % der Zeit, [\d,]+ Wechsel/h – Empfang zu schwach")
        for reason in result["reasons"]:
            self.assertTrue(reason["text"].endswith(")") or reason["text"].endswith("."), reason)

    def test_synthetic_outdoor_is_green(self):
        samples = outdoor_samples()
        result = gpsquality.assess(samples, now=samples[-1]["t"] + 1)
        self.assertEqual(result["level"], "green", result["reasons"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["changes"], 0)
        self.assertEqual(result["fix_share"], 1.0)
        self.assertEqual(result["sentence"], "Fix 100 % der Zeit, kein Wechsel – Empfang gut")
        self.assertGreaterEqual(result["covered_seconds"], 23.9 * H)

    def test_window_is_24h(self):
        samples = outdoor_samples(hours=30)
        result = gpsquality.assess(samples, now=samples[-1]["t"] + 1)
        self.assertLessEqual(result["covered_seconds"], 24 * H)

    def test_too_little_data(self):
        samples = outdoor_samples(hours=0.2)
        result = gpsquality.assess(samples, now=samples[-1]["t"] + 1)
        self.assertEqual(result["level"], "unknown")
        self.assertIn("zu wenig Messdaten", result["sentence"])

    def test_no_gps_values_is_not_available(self):
        result = gpsquality.assess([{"t": T0, "offset": 0.001}], now=T0 + 1)
        self.assertFalse(result["available"])
        self.assertEqual(result["level"], "unknown")
        result = gpsquality.assess([{"t": T0, "gps": {"mode": None}}], now=T0 + 1)
        self.assertEqual(result["level"], "unknown")

    def test_gaps_do_not_count_as_time(self):
        samples = outdoor_samples(hours=1)
        later = [dict(s, t=s["t"] + 10 * H) for s in outdoor_samples(hours=1)]
        result = gpsquality.assess(samples + later, now=later[-1]["t"] + 1)
        self.assertLess(result["covered_seconds"], 2 * H)

    def test_single_glitch_is_no_change(self):
        samples = outdoor_samples(hours=1)
        samples[100]["gps"]["mode"] = 1  # ein einzelner leerer TPV
        result = gpsquality.assess(samples, now=samples[-1]["t"] + 1)
        self.assertEqual(result["changes"], 0)

    def test_old_samples_use_used_average(self):
        samples = outdoor_samples(hours=1)
        for s in samples:
            s["gps"].pop("cn4")
            s["gps"]["snr"] = 20.0
        result = gpsquality.assess(samples, now=samples[-1]["t"] + 1)
        self.assertEqual(result["cn0_source"], "used_avg")
        self.assertIn("der genutzten Satelliten", result["reasons"][0]["text"])

    def test_garbage_is_ignored(self):
        result = gpsquality.assess([None, "x", {"t": "jetzt", "gps": {}}, {"t": T0, "gps": "kaputt"}], now=T0)
        self.assertFalse(result["available"])


# =========================================================================================
class SpreadTest(unittest.TestCase):
    def test_bound_covers_95_percent_and_bias(self):
        diffs = [0.002] * 90 + [0.06, -0.058, 0.055, -0.05, 0.059, 0.06, -0.06, 0.057, 0.052, -0.055]
        stats = gpsquality.spread(diffs)
        within = sum(1 for d in diffs if abs(d) <= stats["bound"]) / len(diffs)
        self.assertGreaterEqual(within, 0.95)
        self.assertGreaterEqual(stats["delay"], 2 * stats["p95_abs"])
        # Der Fall aus E16: kleiner MAD, aber Ausreißer bis ± 60 ms – 6·MAD hätte ~ 0 ergeben.
        self.assertGreater(stats["delay"], 0.1)

    def test_uncalibrated_bias_counts(self):
        stats = gpsquality.spread([0.08 + (i % 5) / 1000 for i in range(100)])
        self.assertGreaterEqual(stats["bound"], 0.08)

    def test_limits_and_rounding_up(self):
        self.assertEqual(gpsquality.spread([0.0001, -0.0001] * 50)["delay"], gpsquality.DELAY_MIN)
        self.assertEqual(gpsquality.spread([0.9, -0.9] * 50)["delay"], gpsquality.DELAY_MAX)
        stats = gpsquality.spread([0.0301] * 100)
        self.assertEqual(stats["delay"], 0.061)  # 0,0602 aufgerundet, nie abgerundet
        self.assertGreaterEqual(stats["precision"], gpsquality.PRECISION_MIN)
        self.assertIsNone(gpsquality.spread([]))
        self.assertIsNone(gpsquality.spread([float("nan"), None]))

    def test_measure_from_vk162_replay(self):
        samples = vk162_samples()
        result = gpsquality.measure(samples, "GPS", now=samples[-1]["t"] + 1)
        self.assertEqual(result["status"], "measured")
        diffs, _times = history.gps_differences(samples, "GPS")
        self.assertGreaterEqual(result["delay"] / 2, gpsquality._quantile([abs(d) for d in diffs], 0.95) - 1e-9)
        self.assertGreaterEqual(result["delay"], gpsquality.DELAY_MIN)
        self.assertLess(result["delay"], gpsquality.DEFAULT_DELAY)

    @staticmethod
    def falseticker_samples(n=2000, gps_state_bad="x", net_states=("*", "+")):
        """90 % brav (± 3 ms, „-“), 10 % bei +60 ms – von chrony als Falschgeber („x“) markiert."""
        import random
        rng = random.Random(16)
        out = []
        for i in range(n):
            bad = i % 10 == 0
            offset = 0.06 if bad else rng.gauss(0.0, 0.003)
            out.append({"t": T0 + i * 10.0, "sources": {
                "GPS": {"o": offset, "s": gps_state_bad if bad else "-", "k": "#", "r": 255},
                "a": {"o": 0.0, "s": net_states[0], "k": "^"},
                "b": {"o": 0.0, "s": net_states[1], "k": "^"}}})
        return out

    def test_falseticker_excursions_raise_bound(self):
        # Befund: „x“/„~“ fielen heraus → Schranke schrumpfte auf ± 10 ms, echtes p95 ~ 60 ms.
        for bad_state in ("x", "~"):
            samples = self.falseticker_samples(gps_state_bad=bad_state)
            result = gpsquality.measure(samples, "GPS", now=samples[-1]["t"] + 1)
            self.assertEqual(result["status"], "measured")
            self.assertGreaterEqual(result["bound"], 0.06, bad_state)
            self.assertGreaterEqual(result["delay"], 0.12, bad_state)
        # Ohne Daten („?“, Reach 0) zählt weiterhin nicht.
        samples = self.falseticker_samples(gps_state_bad="?")
        self.assertLess(gpsquality.measure(samples, "GPS", now=samples[-1]["t"] + 1)["delay"], 0.05)

    def test_bound_does_not_freeze_when_gps_wins(self):
        # Befund: GPS „*“, Netzquellen „-“ → keine Vergleichswerte → Schranke eingefroren.
        samples = self.falseticker_samples(net_states=("-", "-"))
        for sample in samples:
            if sample["sources"]["GPS"]["s"] == "-":
                sample["sources"]["GPS"]["s"] = "*"
        result = gpsquality.measure(samples, "GPS", now=samples[-1]["t"] + 1)
        self.assertEqual(result["status"], "measured")
        self.assertGreaterEqual(result["delay"], 0.12)
        # Der Kalibrier-Offset bleibt bei den genutzten Netzquellen („*“/„+“).
        self.assertEqual(history.gps_differences(samples, "GPS"), ([], []))
        # Genutzte Netzquellen haben Vorrang vor „-“.
        mixed = [{"t": T0, "sources": {"GPS": {"o": 0.01, "s": "-", "k": "#"}, "a": {"o": 0.0, "s": "*", "k": "^"},
                                       "z": {"o": 0.5, "s": "-", "k": "^"}}}]
        self.assertEqual(history.gps_differences(mixed, "GPS", for_bound=True)[0], [0.01])

    def test_measure_needs_enough_data(self):
        samples = vk162_samples()[:30]
        self.assertEqual(gpsquality.measure(samples, "GPS", now=samples[-1]["t"])["status"], "insufficient")


class CalibrationDelayTest(unittest.TestCase):
    def test_suggested_delay_never_below_measured_spread(self):
        samples = vk162_samples()
        result = history.calibrate(samples, "GPS", 0.05, 0.2)
        diffs, _ = history.gps_differences(samples, "GPS")
        median = history._median(diffs)
        p95_dev = gpsquality._quantile([abs(d - median) for d in diffs], 0.95)
        self.assertGreaterEqual(result["suggested_delay"] / 2, p95_dev - 1e-9)
        self.assertGreaterEqual(result["suggested_delay"], gpsquality.DELAY_MIN)

    def test_falseticker_outliers_raise_suggested_delay(self):
        samples = SpreadTest.falseticker_samples()
        result = history.calibrate(samples, "GPS", 0.0, 0.2)
        self.assertGreaterEqual(result["suggested_delay"], 0.12)
        self.assertLess(abs(result["bias"]), 0.002)  # Offset weiter nur aus den brauchbaren Werten

    def test_outliers_raise_suggested_delay(self):
        base = [{"t": T0 + i * 10, "sources": {"GPS": {"o": 0.05 + (0.06 if i % 10 == 0 else 0.0), "s": "-", "k": "#"},
                                               "a": {"o": 0.0, "s": "*", "k": "^"}}} for i in range(400)]
        result = history.calibrate(base, "GPS", 0.0, 0.2)
        self.assertGreaterEqual(result["suggested_delay"], 0.12)  # ± 60 ms Ausreißer abgedeckt


# =========================================================================================
class RefclockValuesTest(unittest.TestCase):
    def test_default_ignores_too_small_stored_delay(self):
        # E16: ein früher gespeicherter Delay von 0,03 s bei ± 60 ms Streuung wird nicht übernommen.
        values = gpsquality.refclock_values(cfg(gps_delay=0.03), None)
        self.assertEqual(values, {"delay": 0.2, "precision": 0.1, "source": "default"})

    def test_measured(self):
        values = gpsquality.refclock_values(cfg(), {"delay": 0.12, "precision": 0.01, "t": T0})
        self.assertEqual((values["delay"], values["precision"], values["source"]), (0.12, 0.01, "measured"))

    def test_invalid_applied_is_rejected(self):
        for bad in ({"delay": 0.0001, "precision": 0.01}, {"delay": 5, "precision": 0.01},
                    {"delay": "0.1", "precision": 0.01}, {"delay": float("nan"), "precision": 0.01}, "x"):
            self.assertEqual(gpsquality.refclock_values(cfg(), bad)["source"], "default", bad)

    def test_manual_and_pps_use_settings(self):
        applied = {"delay": 0.12, "precision": 0.01}
        self.assertEqual(gpsquality.refclock_values(cfg(gps_bound_mode="manual"), applied)["delay"], 0.03)
        values = gpsquality.refclock_values(cfg(gps_pps_device=PPS_DEV), applied)
        self.assertEqual((values["delay"], values["source"]), (0.03, "pps"))
        self.assertEqual(gpsquality.refclock_values(cfg(gps_pps_shm=True), applied)["source"], "pps")
        self.assertFalse(gpsquality.managed(cfg(gps_pps_shm=True)))
        self.assertFalse(gpsquality.managed(cfg(gps_enable=False)))
        self.assertTrue(gpsquality.managed(cfg()))


class MissingPpsTest(StoreCase):
    """Befund: GPS_PPS_DEVICE eingestellt, Gerät fehlt → confgen lässt PPS weg (NMEA allein),
    gpsquality hielt das GPS trotzdem für „mit PPS“ (kleiner Delay, Rolle „Referenz“)."""

    def test_has_pps_matches_confgen(self):
        self.assertTrue(gpsquality.has_pps(cfg(gps_pps_device=PPS_DEV)))
        self.assertFalse(gpsquality.has_pps(cfg(gps_pps_device=PPS_MISSING)))
        self.assertTrue(gpsquality.has_pps(cfg(gps_pps_shm=True)))
        # confgen: Gerät eingestellt, aber fehlt → auch kein SHM-PPS (elif-Kette)
        self.assertFalse(gpsquality.has_pps(cfg(gps_pps_device=PPS_MISSING, gps_pps_shm=True)))

    def test_missing_device_gets_honest_bound_and_fallback_role(self):
        c = cfg(gps_pps_device=PPS_MISSING, gps_delay=0.03)
        self.assertTrue(gpsquality.managed(c))
        values = gpsquality.refclock_values(c, None)
        self.assertEqual((values["delay"], values["source"]), (0.2, "default"))
        role = gpsquality.role(c, None, {})
        self.assertEqual(role["role"], "fallback")
        self.assertNotEqual(role["label"], "Referenz")
        self.assertTrue(gpsquality.status_hint(c)["managed"])
        self.assertFalse(gpsquality.status_hint(c)["pps"])

    def test_confgen_and_gpsquality_agree(self):
        dev = os.path.join(self.tmp, "ttyACM0")
        Path(dev).touch()
        for pps, expect_pps in ((PPS_MISSING, False), (PPS_DEV, True)):
            full = settings.values({})
            full.update(gps_enable=True, gps_device=dev, gps_pps_device=pps, gps_delay=0.03)
            text = confgen.render_chrony(full, {}, warn=lambda *a: None)
            self.assertEqual("refclock PPS" in text, expect_pps, pps)
            self.assertEqual(gpsquality.has_pps(full), expect_pps, pps)
            line = next(l for l in text.splitlines() if l.startswith("refclock SHM"))
            self.assertIn("delay 0.03 " if expect_pps else "delay 0.2 ", line)


class DecideTest(unittest.TestCase):
    def measured(self, delay):
        return {"status": "measured", "delay": delay, "precision": 0.01, "bound": delay / 2}

    def test_first_measurement_replaces_default(self):
        self.assertTrue(gpsquality.decide(self.measured(0.12), None, T0)["apply"])

    def test_small_shrink_is_ignored(self):
        applied = {"delay": 0.12, "precision": 0.01, "t": T0}
        self.assertFalse(gpsquality.decide(self.measured(0.10), applied, T0 + 48 * H)["apply"])
        self.assertFalse(gpsquality.decide(self.measured(0.12), applied, T0 + 48 * H)["apply"])

    def test_any_grow_is_applied(self):
        # Befund: ± 29 ms gemessen, ± 19,5 ms in chrony – das darf nicht so bleiben.
        applied = {"delay": 0.039, "precision": 0.003, "t": T0}
        d = gpsquality.decide(self.measured(0.058), applied, T0 + 2 * H)
        self.assertTrue(d["apply"], d)
        self.assertGreaterEqual(d["delay"], 0.058)
        # Mit Reserve: kleines Kriechen startet chronyd nicht jede Stunde neu.
        d = gpsquality.decide(self.measured(0.122), {"delay": 0.12, "precision": 0.01, "t": T0}, T0 + 2 * H)
        self.assertTrue(d["apply"])
        self.assertEqual(d["delay"], 0.15)

    def test_grow_above_default(self):
        # Befund: ± 145 ms gemessen, der Standard ± 100 ms blieb für immer.
        d = gpsquality.decide(self.measured(0.29), None, T0)
        self.assertTrue(d["apply"], d)
        self.assertEqual(d["delay"], 0.29)
        self.assertEqual(gpsquality.decide(self.measured(1.0), {"delay": 0.9, "precision": 0.01, "t": T0},
                                           T0 + 2 * H)["delay"], gpsquality.DELAY_MAX)

    def test_clock_jumped_back(self):
        # t liegt in der Zukunft: größer erlaubt (sichere Richtung), kleiner gesperrt.
        applied = {"delay": 0.08, "precision": 0.01, "t": T0 + 100 * 24 * H}
        self.assertTrue(gpsquality.decide(self.measured(0.2), applied, T0)["apply"])
        self.assertFalse(gpsquality.decide(self.measured(0.03), applied, T0)["apply"])

    def test_no_shrink_after_reset(self):
        self.assertFalse(gpsquality.decide(self.measured(0.04), None, T0 + H, reset_at=T0)["apply"])
        self.assertTrue(gpsquality.decide(self.measured(0.3), None, T0 + H, reset_at=T0)["apply"])
        self.assertTrue(gpsquality.decide(self.measured(0.04), None, T0 + 13 * H, reset_at=T0)["apply"])

    def test_grow_after_one_hour_shrink_after_twelve(self):
        applied = {"delay": 0.08, "precision": 0.01, "t": T0}
        self.assertFalse(gpsquality.decide(self.measured(0.2), applied, T0 + 0.5 * H)["apply"])
        self.assertTrue(gpsquality.decide(self.measured(0.2), applied, T0 + 1.5 * H)["apply"])
        self.assertFalse(gpsquality.decide(self.measured(0.04), applied, T0 + 6 * H)["apply"])
        self.assertTrue(gpsquality.decide(self.measured(0.04), applied, T0 + 13 * H)["apply"])

    def test_insufficient(self):
        d = gpsquality.decide({"status": "insufficient"}, None, T0)
        self.assertFalse(d["apply"])
        self.assertTrue(d["reason"])


# =========================================================================================
class TickTest(StoreCase):
    def test_tick_applies_logs_and_confgen_uses_it(self):
        samples = vk162_samples(loops=5)  # ~6 h
        now = samples[-1]["t"] + 1
        decision = gpsquality.tick(cfg(), now, samples)
        self.assertTrue(decision["apply"], decision)
        self.assertEqual(len(self.reloads), 1)
        self.assertEqual(len(self.events), 1)
        kind, level, title, data = self.events[0]
        self.assertEqual((kind, level), ("gps", "info"))
        self.assertRegex(title, r"^GPS-Fehlerschranke angepasst: ± 100 ms → ± [\d,]+ ms$")
        self.assertEqual(data["old_delay"], 0.2)
        applied = gpsquality.read_applied()
        self.assertEqual(applied["delay"], data["new_delay"])
        # Ohne neue Erkenntnis: keine zweite Änderung, kein Neustart.
        self.assertFalse(gpsquality.tick(cfg(), now + 2 * H, samples)["apply"])
        self.assertEqual(len(self.reloads), 1)
        # confgen schreibt die gemessene Schranke in die GPS-Zeile.
        full = settings.values({})
        full.update(gps_enable=True, gps_device="/dev/null", gps_delay=0.03)
        text = confgen.render_chrony(full, {}, warn=lambda *a: None)
        line = next(l for l in text.splitlines() if l.startswith("refclock SHM"))
        self.assertIn(f"delay {confgen._num(float(applied['delay']))} ", line)
        self.assertIn("Rückfallebene", text)
        self.assertIn("(gemessen)", text)

    def test_reset(self):
        samples = vk162_samples(loops=5)
        gpsquality.tick(cfg(), samples[-1]["t"] + 1, samples)
        result = gpsquality.reset(cfg())
        self.assertTrue(result["ok"])
        self.assertIsNone(gpsquality.read_applied())
        self.assertEqual(len(self.reloads), 2)
        self.assertIn("zurückgesetzt", self.events[-1][2])
        with self.assertRaises(gpsquality.QualityError):
            gpsquality.reset(cfg())

    def test_reset_is_not_undone_by_next_tick(self):
        # Befund: reset() setzte applied=None, die nächste Prüfung setzte sofort dieselbe kleine Schranke.
        samples = vk162_samples(loops=5)
        now = samples[-1]["t"] + 1
        self.assertTrue(gpsquality.tick(cfg(), now, samples)["apply"])
        gpsquality.reset(cfg(), now=now + 60)
        reloads = len(self.reloads)
        decision = gpsquality.tick(cfg(), now + H, samples)
        self.assertFalse(decision["apply"], decision)
        self.assertIsNone(gpsquality.read_applied())
        self.assertEqual(len(self.reloads), reloads)
        later = [dict(x, t=x["t"] + 13 * H) for x in samples]  # dieselben Messwerte, 13 h später
        self.assertTrue(gpsquality.tick(cfg(), now + 13 * H, later)["apply"])

    def test_future_timestamp_is_clamped(self):
        samples = vk162_samples(loops=5)
        now = samples[-1]["t"] + 1
        gpsquality.save_state({"applied": {"delay": 0.19, "precision": 0.01, "t": now + 365 * 24 * H}})
        self.assertFalse(gpsquality.tick(cfg(), now, samples)["apply"])  # kleiner: 12 h ab jetzt gesperrt
        self.assertEqual(gpsquality.load_state()["applied"]["t"], now)
        later = [dict(x, t=x["t"] + 13 * H) for x in samples]
        self.assertTrue(gpsquality.tick(cfg(), now + 13 * H, later)["apply"])

    def test_not_managed_does_nothing(self):
        samples = vk162_samples(loops=5)
        d = gpsquality.tick(cfg(gps_pps_device=PPS_DEV), samples[-1]["t"] + 1, samples)
        self.assertFalse(d["apply"])
        self.assertEqual(self.reloads, [])
        self.assertFalse(os.path.exists(store.path()))

    def test_read_creates_nothing(self):
        self.assertIsNone(gpsquality.read_applied())
        self.assertEqual(gpsquality.load_state(), {})
        self.assertFalse(os.path.exists(store.path()))
        role = gpsquality.role(cfg())
        self.assertEqual(role["bound_source"], "default")
        self.assertFalse(os.path.exists(store.path()))

    def test_corrupt_row_falls_back(self):
        samples = vk162_samples(loops=5)
        gpsquality.tick(cfg(), samples[-1]["t"] + 1, samples)
        store.execute("UPDATE gps_bound SET json = '{kaputt' WHERE id = 1")
        self.assertIsNone(gpsquality.read_applied())
        self.assertEqual(gpsquality.refclock_values(cfg())["source"], "default")

    def test_maybe_tick_once_per_hour(self):
        calls = []
        orig = gpsquality.tick
        gpsquality.tick = lambda c, *a, **k: calls.append(c) or {}
        self.addCleanup(setattr, gpsquality, "tick", orig)
        gpsquality._LAST_TICK["mono"] = None
        self.addCleanup(gpsquality._LAST_TICK.update, mono=None)
        mono = [100.0]
        gpsquality.maybe_tick(cfg, clock=lambda: mono[0])
        mono[0] += 1800
        gpsquality.maybe_tick(cfg, clock=lambda: mono[0])
        mono[0] += 1801
        gpsquality.maybe_tick(cfg, clock=lambda: mono[0])
        self.assertEqual(len(calls), 2)


# =========================================================================================
class RoleTest(unittest.TestCase):
    STATE = {}

    def test_fallback_without_pps(self):
        role = gpsquality.role(cfg(), [], {"applied": {"delay": 0.12, "precision": 0.01}})
        self.assertEqual((role["role"], role["label"]), ("fallback", "Rückfallebene"))
        self.assertIn("± 60 ms", role["text"])
        self.assertFalse(role["active"])
        self.assertEqual(role["warnings"], [])

    def test_fallback_active_when_selected(self):
        role = gpsquality.role(cfg(), [{"name": "GPS", "mode": "#", "state": "*"}], self.STATE)
        self.assertTrue(role["active"])
        self.assertIn("Gerade nutzt chrony das GPS", role["text"])
        self.assertIn("vorsichtige Standard", role["text"])

    def test_observe_is_explicit_choice(self):
        role = gpsquality.role(cfg(gps_select="noselect"), None, self.STATE)
        self.assertEqual((role["role"], role["label"]), ("observe", "nur beobachten"))
        self.assertIn("Du hast", role["text"])
        self.assertIsNone(role["active"])

    def test_reference(self):
        self.assertEqual(gpsquality.role(cfg(gps_pps_device=PPS_DEV), None, self.STATE)["label"], "Referenz")
        role = gpsquality.role(cfg(gps_select="prefer"), None, self.STATE)
        self.assertEqual(role["role"], "reference")
        self.assertEqual(role["tone"], "warn")

    def test_warnings(self):
        state = {"measured": {"status": "measured", "delay": 0.12}}
        role = gpsquality.role(cfg(gps_bound_mode="manual", gps_delay=0.03, ntp_minsources=2), None, state)
        self.assertEqual(len(role["warnings"]), 2)
        self.assertIn("kleiner als die gemessene Streuung", role["warnings"][0])
        self.assertIn("Mindestzahl Quellen", role["warnings"][1])

    def test_measured_above_effective_is_flagged(self):
        state = {"measured": {"status": "measured", "delay": 0.29}}
        role = gpsquality.role(cfg(), None, state)
        self.assertNotIn("nach einigen Stunden", role["text"])
        self.assertEqual(len(role["warnings"]), 1)
        self.assertIn("größer als die Schranke in chrony", role["warnings"][0])
        state = {"applied": {"delay": 0.039, "precision": 0.003}, "measured": {"status": "measured", "delay": 0.058}}
        self.assertEqual(len(gpsquality.role(cfg(), None, state)["warnings"]), 1)
        # Gemessen knapp unter dem Standard: bleibt beim Standard, ehrlich gesagt.
        role = gpsquality.role(cfg(), None, {"measured": {"status": "measured", "delay": 0.15}})
        self.assertIn("bleibt darum beim Standard", role["text"])
        self.assertEqual(role["warnings"], [])

    def test_annotate_calibration(self):
        result = gpsquality.annotate_calibration({"current_delay": 0.03}, cfg(gps_delay=0.03), None)
        self.assertEqual((result["current_delay"], result["delay_managed"], result["delay_source"]), (0.2, True, "default"))
        result = gpsquality.annotate_calibration({"current_delay": 0.03}, cfg(), {"delay": 0.12, "precision": 0.01})
        self.assertEqual((result["current_delay"], result["delay_source"]), (0.12, "measured"))
        result = gpsquality.annotate_calibration({"current_delay": 0.03}, cfg(gps_bound_mode="manual"), None)
        self.assertEqual((result["current_delay"], result["delay_managed"]), (0.03, False))

    def test_off(self):
        self.assertEqual(gpsquality.role(cfg(gps_enable=False))["role"], "off")


# =========================================================================================
class FlapReplayTest(unittest.TestCase):
    """Abnahme: Replay „VK-162 drinnen“ → ein Ereignis „unstet“ statt Dutzender."""

    def run_replay(self, loops, calm_samples=0, **kw):
        events, now = [], [None]
        watch = statewatch.StateWatcher(lambda *a, **k: events.append(a), clock=lambda: now[0],
                                        wall=lambda: T0 + (now[0] or 0), **kw)
        for sample in vk162_samples(loops):
            now[0] = sample["t"] - T0
            watch.sample({"gps": sample["gps"]})
        for _ in range(calm_samples):
            now[0] += 6.0
            watch.sample({"gps": {"mode": 3, "used": 7}})
        return [e for e in events if e[0] == "gps"], watch

    def test_without_unstet_there_are_dozens(self):
        events, _ = self.run_replay(10, flap_enter=10 ** 6)
        self.assertGreaterEqual(len(events), 30)

    def test_one_unstet_event_instead_of_dozens(self):
        events, watch = self.run_replay(10)
        titles = [e[2] for e in events]
        unstet = [t for t in titles if "unstet" in t]
        self.assertEqual(len(unstet), 1, titles)
        self.assertLessEqual(len(titles), 3, titles)   # höchstens ein Paar vor dem Erkennen
        self.assertEqual(events[-1][1], "warn")
        self.assertEqual(events[-1][3]["state"], "unstet")
        self.assertGreaterEqual(events[-1][3]["changes"], statewatch.GPS_FLAP_ENTER)
        stability = watch.gps_stability()
        self.assertEqual(stability["state"], "unstet")
        self.assertGreater(stability["unstet_changes"], 50)
        self.assertIsNotNone(stability["unstet_since"])

    def test_calm_ends_with_one_summary(self):
        events, watch = self.run_replay(3, calm_samples=700)  # 70 min ruhig
        last = events[-1]
        self.assertEqual(last[1], "info")
        self.assertRegex(last[2], r"^GPS-Empfang wieder stetig – \d+ Fix-Wechsel in \d+ h")
        self.assertEqual(last[3]["state"], "stetig")
        self.assertEqual(watch.gps_stability()["state"], "stetig")
        self.assertEqual(sum(1 for e in events if "unstet" in e[2]), 1)

    def test_lost_fix_while_unstet_is_reported_early(self):
        # Befund: im Zustand „unstet“ kam „GPS-Fix verloren“ erst nach einer Stunde.
        events, now = [], [0.0]
        watch = statewatch.StateWatcher(lambda *a, **k: events.append(a + (now[0],)), clock=lambda: now[0])
        for mode in ([3, 3, 1, 1] * 6):
            watch.sample({"gps": {"mode": mode}})
            now[0] += 10
        self.assertEqual(watch.gps_stability()["state"], "unstet")
        lost_at = now[0]
        for _ in range(400):
            watch.sample({"gps": {"mode": 1}})
            now[0] += 10
        gps_events = [e for e in events if e[0] == "gps"]
        self.assertEqual(gps_events[-1][1], "warn")
        self.assertRegex(gps_events[-1][2], r"^GPS-Fix verloren – nach \d+ Fix-Wechseln .* seit 10 min ohne Fix$")
        self.assertFalse(gps_events[-1][3]["fix"])
        self.assertLessEqual(gps_events[-1][4] - lost_at, statewatch.GPS_UNSTET_LOST + 60)
        self.assertEqual(sum(1 for e in gps_events if "verloren" in e[2]), 1)  # kein zweites Ereignis
        self.assertEqual(watch.gps_stability()["state"], "stetig")
        # Fix kommt zurück → normales Ereignis (Haltezeit 60 s).
        for _ in range(10):
            watch.sample({"gps": {"mode": 3}})
            now[0] += 10
        self.assertEqual([e[2] for e in events if e[0] == "gps"][-1], "GPS-Fix wieder da")

    def test_gps_off_closes_episode_events(self):
        events, now = [], [0.0]
        watch = statewatch.StateWatcher(lambda *a, **k: events.append(a), clock=lambda: now[0])
        for mode in ([3, 3, 1, 1] * 6):
            watch.sample({"gps": {"mode": mode}})
            now[0] += 10
        self.assertEqual(watch.gps_stability()["state"], "unstet")
        watch.sample({"offset": 0.0})
        self.assertEqual(events[-1][1], "info")
        self.assertIn("GPS ausgeschaltet", events[-1][2])
        self.assertEqual(events[-1][3]["state"], "aus")
        self.assertEqual(watch.gps_stability()["state"], "unbekannt")

    def test_gps_off_resets(self):
        _, watch = self.run_replay(1)
        watch.sample({"offset": 0.0})  # GPS aus
        self.assertEqual(watch.gps_stability()["state"], "unbekannt")


# =========================================================================================
class AntennaTest(StoreCase):
    def status(self, mode=3, used=6, snrs=(40, 38, 35, 33, 20, 0)):
        return {"running": True, "mode": mode, "satellites_used": used, "satellites_seen": len(snrs),
                "satellites": [{"prn": i, "snr": s, "elevation": 45, "azimuth": 90, "used": i < used}
                               for i, s in enumerate(snrs)]}

    def test_summary_has_no_angles(self):
        points = [gpsquality._poll_point(self.status()) for _ in range(5)]
        summary = gpsquality.summarize_antenna(points)
        self.assertEqual(summary["fix_share"], 1.0)
        self.assertEqual(summary["cn0_top4"], 36.5)
        self.assertEqual(summary["strong"], 4)
        text = json.dumps(summary)
        for word in ("elevation", "azimuth", "lat", "lon"):
            self.assertNotIn(word, text)
        self.assertIsNone(gpsquality._poll_point({"running": False}))

    def test_compare(self):
        a = {"label": "Schrank", "cn0_top4": 21.0, "fix_share": 0.7, "used": 4}
        b = {"label": "Fensterbank", "cn0_top4": 33.0, "fix_share": 1.0, "used": 8}
        result = gpsquality.compare(a, b)
        self.assertEqual(result["better"], "b")
        self.assertIn("„Fensterbank“ ist besser", result["verdict"])
        self.assertIn("+12 dB-Hz", result["verdict"])
        self.assertEqual(gpsquality.compare(b, a)["better"], "a")
        same = gpsquality.compare(a, dict(a, label="nochmal"))
        self.assertIsNone(same["better"])
        self.assertIn("Kaum Unterschied", same["verdict"])

    def test_label_allowlist(self):
        self.assertEqual(gpsquality.check_label("  Fensterbank (Süd) #2 "), "Fensterbank (Süd) #2")
        self.assertEqual(gpsquality.check_label(None), "")
        for bad in ("<script>", "a" * 41, "x\ny", "a&b", "{}"):
            with self.assertRaises(gpsquality.QualityError, msg=bad):
                gpsquality.check_label(bad)

    def test_run_saves_result(self):
        polls = []

        def poll():
            polls.append(1)
            return self.status()

        # Eigene Uhr, die je Abfrage eine Sekunde weiterläuft: genau 5 Abfragen, egal wie
        # ausgelastet der Rechner ist.
        clock = [1000.0]

        def poll():
            polls.append(1)
            clock[0] += 1.0
            return self.status()

        test = gpsquality.AntennaTest(poll, gpsquality.save_antenna, mono=lambda: clock[0])
        test.start("Fensterbank", seconds=5, interval=0.01)
        test.join(timeout=60)
        self.assertFalse(test.running())
        results = gpsquality.antenna_results()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["label"], "Fensterbank")
        self.assertTrue(results[0]["complete"])
        self.assertEqual(results[0]["samples"], 5)
        self.assertEqual(len(polls), 5)
        with sqlite3.connect(store.path()) as conn:
            raw = " ".join(r[0] for r in conn.execute("SELECT json FROM antenna_tests"))
        self.assertNotIn("elevation", raw)
        self.assertNotIn("azimuth", raw)

    def test_stop_and_single_run(self):
        gate = threading.Event()

        def poll():
            gate.set()
            return self.status()

        test = gpsquality.AntennaTest(poll, gpsquality.save_antenna)
        test.start("A", seconds=600, interval=0.01)
        self.assertTrue(gate.wait(30))
        with self.assertRaises(gpsquality.QualityError):
            test.start("B")
        status = test.status()
        self.assertTrue(status["running"])
        self.assertEqual(status["label"], "A")
        deadline = time.monotonic() + 30
        while (test.status()["live"] or {}).get("samples", 0) < 3 and time.monotonic() < deadline:
            gate.clear()
            gate.wait(1)
        test.stop()
        test.join(timeout=30)
        self.assertFalse(test.running())
        results = gpsquality.antenna_results()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["complete"])

    def test_too_few_points_are_not_saved(self):
        test = gpsquality.AntennaTest(lambda: {"running": False}, gpsquality.save_antenna)
        test.start("leer", seconds=0.05, interval=0.01)
        test.join(timeout=30)
        self.assertEqual(gpsquality.antenna_results(), [])
        self.assertIn("zu wenige Werte", test.status()["error"])

    def test_keep_and_delete(self):
        for i in range(gpsquality.ANTENNA_KEEP + 3):
            gpsquality.save_antenna({"label": f"M{i}", "ended": T0 + i, "cn0_top4": 30.0, "fix_share": 1.0})
        results = gpsquality.antenna_results()
        self.assertEqual(len(results), gpsquality.ANTENNA_KEEP)
        self.assertEqual(results[0]["label"], f"M{gpsquality.ANTENNA_KEEP + 2}")
        self.assertTrue(gpsquality.delete_antenna(results[0]["id"]))
        self.assertFalse(gpsquality.delete_antenna(results[0]["id"]))
        for bad in ("1", True, -1, None):
            with self.assertRaises(gpsquality.QualityError):
                gpsquality.delete_antenna(bad)

    def test_action_validation(self):
        for data in ({"action": "explode"}, {"action": "start", "label": "<b>"},
                     {"action": "start", "label": "x", "seconds": 5}, {"action": "start", "seconds": True}):
            with self.assertRaises(gpsquality.QualityError, msg=data):
                gpsquality.antenna_action(data)


class ApiTest(StoreCase):
    def test_scopes_and_v1(self):
        self.assertEqual(apiv1.required_scope("GET", "/api/gps/quality"), "read")
        self.assertEqual(apiv1.required_scope("GET", "/api/v1/gps/quality"), "read")
        self.assertEqual(apiv1.required_scope("GET", "/api/v1/gps/antenna"), "read")
        self.assertEqual(apiv1.required_scope("POST", "/api/gps/antenna"), "admin")
        self.assertEqual(apiv1.required_scope("POST", "/api/v1/gps/bound"), "admin")

    def test_api_status(self):
        class Hist:
            def snapshot(self, since=None):
                return [s for s in outdoor_samples(hours=2) if since is None or s["t"] >= since]
        gpsquality._ASSESS_CACHE.update(mono=None, value=None, key=None)
        self.addCleanup(gpsquality._ASSESS_CACHE.update, mono=None, value=None, key=None)
        now = T0 + 2 * H
        result = gpsquality.api_status(cfg(), Hist(), [], {"state": "stetig"}, now=now)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["assessment"]["level"], "green")
        self.assertEqual(result["role"]["role"], "fallback")
        self.assertEqual(result["bound"]["effective"]["source"], "default")
        self.assertEqual(result["stability"]["state"], "stetig")
        text = json.dumps(result)
        for word in ("lat", "lon", "elevation", "azimuth"):
            self.assertNotIn(f'"{word}"', text)
        off = gpsquality.api_status(cfg(gps_enable=False), Hist(), None, None, now=now)
        self.assertFalse(off["available"])
        self.assertIn("nicht verfügbar", off["reason"])


if __name__ == "__main__":
    unittest.main()
