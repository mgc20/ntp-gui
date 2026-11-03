"""GNSS-Störungen erkennen (1.5, Thema 1), GPS-Sperre per selectopts (Thema 2) und echter
Holdover-Test (Thema 8): gnssguard.py, selectctl.py, holdover.py.

Replays (Abnahme): (a) C/N0-Einbruch, (b) Zeitsprung 50 ms, (c) Positionssprung, (d) langsamer
Abfall wie Schneefall → (a)–(c) in ≤ 60 s erkannt, (d) kein Alarm. Dazu „VK-162 schwacher
Empfang“ aus tests/fixtures/gps_vk162_indoor.jsonl (echte Aufzeichnung eines Nutzers,
datenschutzgefiltert: Fix-Art, Satellitenzahl, GPS- und Netz-Offsets echt) → höchstens
„Hinweis“, nie „Störung“. Die C/N0 je Satellit und die Position hat der Datenschutzfilter
entfernt; sie werden hier deterministisch synthetisiert (Startwert fest, Ort erfunden).

chronyd wird durch eine Attrappe ersetzt, die selectopts wie chrony 4.6 behandelt
(effektive Optionen, Neustart vergisst sie, konfiguriertes noselect bleibt).
"""

import json
import os
import random
import shutil
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
import chrony  # noqa: E402
import egress  # noqa: E402
import gnssguard  # noqa: E402
import gps  # noqa: E402
import holdover  # noqa: E402
import notify  # noqa: E402
import selectctl  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gps_vk162_indoor.jsonl"
HOME = (45.0, 10.0)                      # erfundener Ort, nur für die Rechnung
SKY = [44, 42, 41, 39, 38, 36, 34, 31, 28]  # draußen: 9 Satelliten, natürlich gestaffelt


def offset_pos(metres_north: float, metres_east: float = 0.0) -> tuple[float, float]:
    import math
    lat = HOME[0] + metres_north / 111_195.0
    lon = HOME[1] + metres_east / (111_195.0 * math.cos(math.radians(HOME[0])))
    return lat, lon


def outdoor(t: float, rng: random.Random, cn0_shift: float = 0.0, time_shift: float = 0.0,
            pos_shift: float = 0.0) -> dict:
    """Eine Beobachtung „draußen“: 3D-Fix, 9 Satelliten, GPS ± 2 ms um drei NTS-Quellen."""
    sats = {f"GPS:{i + 1}": max(0.0, v + rng.uniform(-1.0, 1.0) + cn0_shift) for i, v in enumerate(SKY)}
    pos = offset_pos(rng.gauss(0, 3) + pos_shift, rng.gauss(0, 3))
    return {"t": t, "mode": 3, "sats": sats, "pos": (pos[0], pos[1], 6.0),
            "gps_offset": 0.001 + rng.uniform(-0.002, 0.002) + time_shift, "gps_state": "+",
            "refs": [0.0005, 0.001, 0.0015], "ref_kind": "nts"}


def run_scenario(disturb, baseline_s=2400.0, after_s=600.0, step=10.0, seed=7):
    """Grundlinie, dann ab T Störung. Gibt (Detektor, Stufen [(t, stage)], T) zurück."""
    rng = random.Random(seed)
    det = gnssguard.Detector()
    stages = []
    t = 0.0
    while t < baseline_s + after_s:
        obs = outdoor(t, rng, **(disturb(t - baseline_s) if t >= baseline_s else {}))
        stages.append((t, det.update(obs)["stage"]))
        t += step
    return det, stages, baseline_s


def first(stages, since, wanted):
    for t, stage in stages:
        if t >= since and gnssguard.stage_rank(stage) >= gnssguard.stage_rank(wanted):
            return t - since
    return None


def vk162_observations(seed=3):
    """Echte VK-162-Aufzeichnung (drinnen) als Beobachtungen; C/N0 je Satellit und Position synthetisiert."""
    rng = random.Random(seed)
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if "_" not in r]
    out = []
    spread = [3.0, 1.5, 0.0, -1.0, -2.5, -4.0, -6.0, -8.0]   # 8 Satelliten um die vier stärksten
    for row in rows:
        mode = row.get("mode") or 0
        cn4 = row.get("cn4")
        sats = None
        if cn4 is not None:
            sats = {}
            for i, d in enumerate(spread):
                value = cn4 + d + rng.uniform(-3.0, 3.0)
                if value < 12 or rng.random() < 0.12:   # schwache Satelliten kommen und gehen
                    continue
                sats[f"GPS:{i + 1}"] = round(value)
        obs = {"t": row["t"], "mode": mode, "sats": sats}
        if mode == 3:
            eph = rng.uniform(25.0, 70.0)
            pos = offset_pos(rng.gauss(0, eph / 2), rng.gauss(0, eph / 2))
            obs["pos"] = (pos[0], pos[1], eph)
        if row.get("gps_o") is not None and row.get("net_o"):
            obs.update(gps_offset=row["gps_o"], gps_state="-", refs=row["net_o"], ref_kind="nts")
        out.append(obs)
    return out


# =========================================================================================
class ReplayTest(unittest.TestCase):
    """Abnahme Thema 1: (a)–(c) in ≤ 60 s, (d) kein Alarm, VK-162 höchstens „Hinweis“."""

    def test_quiet_outdoor_never_alarms(self):
        _det, stages, _t = run_scenario(lambda dt: {}, after_s=3600.0)
        self.assertEqual({s for _t, s in stages}, {"ok"})

    def test_a_cn0_drop_detected_within_60s(self):
        det, stages, t0 = run_scenario(lambda dt: {"cn0_shift": -12.0})
        delay = first(stages, t0, "hinweis")
        self.assertIsNotNone(delay)
        self.assertLessEqual(delay, 60.0)
        self.assertTrue(det.signals["cn0_drop"].active)
        # Reines Jamming ist ein schwaches Signal: Hinweis, keine Störung.
        self.assertEqual(max((s for _t, s in stages), key=gnssguard.stage_rank), "hinweis")
        self.assertGreaterEqual(det.signals["cn0_drop"].detail["drop_db"], 6)

    def test_b_time_jump_50ms_detected_within_60s(self):
        det, stages, t0 = run_scenario(lambda dt: {"time_shift": 0.050})
        delay = first(stages, t0, "stoerung")
        self.assertIsNotNone(delay)
        self.assertLessEqual(delay, 60.0)
        self.assertTrue(det.signals["time"].active)
        self.assertAlmostEqual(det.signals["time"].detail["deviation_ms"], 50.0, delta=4.0)
        self.assertIn("NTS-Quellen", det.signals["time"].text)

    def test_c_position_jump_detected_within_60s(self):
        det, stages, t0 = run_scenario(lambda dt: {"pos_shift": 800.0})
        delay = first(stages, t0, "stoerung")
        self.assertIsNotNone(delay)
        self.assertLessEqual(delay, 60.0)
        sig = det.signals["position"]
        self.assertTrue(sig.active)
        self.assertEqual(sig.detail["deviation_m"] % 10, 0)       # auf 10 m gerundet
        self.assertAlmostEqual(sig.detail["deviation_m"], 800, delta=30)
        self.assertNotRegex(sig.text, r"\d+\.\d{3}")               # keine Koordinaten im Text

    def test_d_slow_snow_like_decline_no_alarm(self):
        # 12 dB in 2 h auf allen Satelliten, wie Schnee auf der Antenne.
        _det, stages, t0 = run_scenario(lambda dt: {"cn0_shift": -12.0 * min(1.0, dt / 7200.0)}, after_s=9000.0)
        self.assertEqual({s for t, s in stages if t >= t0}, {"ok"})

    def test_vk162_weak_reception_at_most_hint(self):
        stages = []
        for seed in (1, 2, 3, 4, 5):
            det = gnssguard.Detector()
            for obs in vk162_observations(seed):
                stages.append(det.update(obs)["stage"])
        self.assertNotIn("stoerung", stages)
        self.assertNotIn("warnung", stages)

    def test_vk162_through_guard_emits_no_crit(self):
        emitted = []
        guard = gnssguard.Guard(emit=lambda *a: emitted.append(a), clock=lambda: 0.0, wall=lambda: 0.0)
        guard.state = dict(locked=False, since=None, manual=False, auto_release=False, reason="", targets=[],
                           repeats=0, series_t=None, auto_releases=0, suppress=False)
        for obs in vk162_observations(2):
            guard.tick({"gps_enable": True, "gnss_guard": "lock"}, obs=obs, select={})
        self.assertFalse([e for e in emitted if e[1] in {"warn", "crit"}], emitted)
        self.assertFalse(guard.state["locked"])

    def test_returns_to_ok_after_hold(self):
        _det, stages, t0 = run_scenario(lambda dt: {"time_shift": 0.050} if dt < 120 else {}, after_s=1200.0)
        self.assertIsNotNone(first(stages, t0, "stoerung"))
        self.assertEqual(stages[-1][1], "ok")


class SignalTest(unittest.TestCase):
    def test_uniform_cn0_is_hint(self):
        det = gnssguard.Detector()
        for i in range(5):
            det.update({"t": i * 10.0, "sats": {f"GPS:{k}": 45.0 + (k % 3) * 0.2 for k in range(8)}})
        self.assertTrue(det.signals["uniform"].active)
        self.assertEqual(det.stage(), "hinweis")

    def test_natural_sky_not_uniform(self):
        det = gnssguard.Detector()
        for i in range(10):
            det.update({"t": i * 10.0, "sats": {f"GPS:{k}": v for k, v in enumerate(SKY)}})
        self.assertFalse(det.signals["uniform"].active)

    def test_two_weak_signals_are_warning(self):
        det = gnssguard.Detector()
        for i in range(5):
            det.update({"t": i * 10.0, "gps_state": "x", "sats": {f"GPS:{k}": 40.0 for k in range(8)}})
        self.assertEqual(det.stage(), "warnung")

    def test_time_needs_references(self):
        det = gnssguard.Detector()
        for i in range(10):
            det.update({"t": i * 10.0, "gps_offset": 5.0, "gps_state": "-", "refs": [0.0], "ref_kind": "nts"})
        self.assertFalse(det.signals["time"].active)   # nur eine NTS-Quelle: kein Urteil
        for i in range(10, 15):
            det.update({"t": i * 10.0, "gps_offset": 5.0, "gps_state": "-", "refs": [0.0, 0.001], "ref_kind": "nts"})
        self.assertTrue(det.signals["time"].active)    # ohne Grundlinie: grober Fehler > 1 s zählt

    def test_plain_ntp_needs_three(self):
        obs = gnssguard.observation(0.0, {}, [
            {"name": "GPS", "mode": "#", "state": "-", "reach": 255, "offset": 0.01},
            {"name": "a", "mode": "^", "state": "*", "reach": 255, "offset": 0.001},
            {"name": "b", "mode": "^", "state": "+", "reach": 255, "offset": 0.002},
            {"name": "c", "mode": "^", "state": "?", "reach": 0, "offset": 0.002}],
            {"a": {"authenticated": True}}, "GPS")
        self.assertEqual(obs["ref_kind"], "ntp")
        self.assertEqual(len(obs["refs"]), 2)
        det = gnssguard.Detector()
        det.update(dict(obs, t=0.0))
        self.assertIsNone(det.last["ref_kind"])        # 2 < 3 normale Netzquellen

    def test_noselect_sources_still_count(self):
        # chrony 4.6 meldet abgewählte Quellen mit „?“ – bei reach ≠ 0 sind sie trotzdem gemessen.
        obs = gnssguard.observation(0.0, {}, [
            {"name": "GPS", "mode": "#", "state": "?", "reach": 255, "offset": 0.01},
            {"name": "a", "mode": "^", "state": "?", "reach": 255, "offset": 0.001},
            {"name": "b", "mode": "^", "state": "?", "reach": 255, "offset": 0.002},
            {"name": "c", "mode": "^", "state": "?", "reach": 0, "offset": 0.5}],
            {"a": {"authenticated": True}, "b": {"authenticated": True}}, "GPS")
        self.assertEqual(obs["gps_state"], "-")
        self.assertEqual((obs["ref_kind"], sorted(obs["refs"])), ("nts", [0.001, 0.002]))
        self.assertEqual(sorted(holdover.references([
            {"name": "a", "mode": "^", "state": "?", "reach": 255, "offset": 0.001},
            {"name": "c", "mode": "^", "state": "?", "reach": 0, "offset": 0.5}])), ["a"])

    def test_observation_from_gps_status(self):
        status = gps.parse_reports({"TPV": {"mode": 3, "lat": 1.0, "lon": 2.0}, "SKY": {"satellites": [
            {"PRN": 3, "ss": 41, "used": True, "el": 40, "az": 100}, {"PRN": 7, "ss": 0}]}})
        obs = gnssguard.observation(5.0, dict(status, running=True), [], {}, "GPS", (1.0, 2.0, 8.0))
        self.assertEqual(obs["sats"], {"GPS:3": 41.0, "GPS:7": 0.0})
        self.assertEqual(obs["pos"], (1.0, 2.0, 8.0))

    def test_relearn_forgets_position(self):
        det, _stages, _t = run_scenario(lambda dt: {"pos_shift": 800.0})
        self.assertTrue(det.signals["position"].active)
        det.reset_baselines()
        self.assertFalse(det.signals["position"].active)
        self.assertEqual(len(det._positions), 0)


# =========================================================================================
class FakeChrony:
    """selectdata/sources/selectopts wie chrony 4.6 – Neustart vergisst die Laufzeitschalter."""

    def __init__(self, gps=True, pps=False, network=3, nts=True, gps_configured_noselect=False):
        self.rows = {}
        if gps:
            self.rows["GPS"] = {"mode": "#", "auth": False, "conf": gps_configured_noselect, "offset": 0.002}
        if pps:
            self.rows["PPS"] = {"mode": "#", "auth": False, "conf": False, "offset": 0.0}
        for i in range(network):
            self.rows[f"192.0.2.{i + 1}"] = {"mode": "^", "auth": nts, "conf": False, "offset": 0.0001 * i}
        self.effective = {n for n, r in self.rows.items() if r["conf"]}
        self.calls = []
        self.down = False
        self.fail = False

    def restart(self):
        self.effective = {n for n, r in self.rows.items() if r["conf"]}

    def selectdata(self):
        if self.down:
            return []
        # Wie chrony 4.6: Nach selectopts steht die Option auch in der Spalte „konfiguriert“.
        return [{"name": n, "authenticated": r["auth"], "select_state": "noselect" if n in self.effective else "best",
                 "configured_options": ["noselect"] if n in self.effective else [],
                 "effective_options": ["noselect"] if n in self.effective else []} for n, r in self.rows.items()]

    def sources(self):
        if self.down:
            return []
        # Wie chrony 4.6: abgewählte Quellen stehen mit „?“ da, werden aber weiter gemessen (reach 377).
        return [{"name": n, "mode": r["mode"], "state": "?" if n in self.effective else "+",
                 "reach": r.get("reach", 255), "offset": r["offset"]} for n, r in self.rows.items()]

    def selectopts(self, name, sign):
        self.calls.append((name, sign))
        if self.fail or self.down or name not in self.rows or name in getattr(self, "refuse", ()):
            raise selectctl.SelectError("506 Cannot talk to daemon")
        if sign == "+":
            self.effective.add(name)
        else:
            self.effective.discard(name)

    def select(self):
        return selectctl.by_name(self.selectdata())


class StoreCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        self.chrony = FakeChrony(**getattr(self, "fake_args", {}))
        self.addCleanup(selectctl.set_port(self.chrony))
        selectctl.reset_for_tests()
        self.addCleanup(self._cleanup)
        self.events = []
        self.mono = [0.0]
        self.wall = [1_800_000_000.0]

    def _cleanup(self):
        selectctl.reset_for_tests()
        gnssguard._READY["for"] = None
        holdover._READY["for"] = None
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def guard(self):
        return gnssguard.Guard(emit=lambda *a: self.events.append(a), clock=lambda: self.mono[0],
                               wall=lambda: self.wall[0])


CFG = {"gps_enable": True, "gps_refid": "GPS", "gnss_guard": "lock", "gnss_notify": "stoerung"}


def jump_obs(t, rng, jump=True):
    return outdoor(t, rng, time_shift=0.08 if jump else 0.0)


class LockCase(StoreCase):
    """Hilfen: Beobachtungen im 10-s-Takt einspeisen (ohne eigene Tests)."""

    def feed(self, guard, seconds, jump, cfg=CFG, rng=None, step=10.0):
        rng = rng or random.Random(5)
        end = self.mono[0] + seconds
        while self.mono[0] < end:
            self.mono[0] += step
            self.wall[0] += step
            guard.tick(cfg, obs=jump_obs(self.mono[0], rng, jump), select=self.chrony.select())
        return guard

    def baseline(self, guard, cfg=CFG):
        return self.feed(guard, 2400, False, cfg)


class LockTest(LockCase):

    def test_report_mode_only_reports(self):
        guard = self.baseline(self.guard(), dict(CFG, gnss_guard="report"))
        self.feed(guard, 60, True, dict(CFG, gnss_guard="report"))
        self.assertEqual(guard.stage, "stoerung")
        self.assertEqual(self.chrony.calls, [])
        crit = [e for e in self.events if e[1] == "crit"]
        self.assertEqual(len(crit), 1)
        self.assertTrue(crit[0][2].startswith("GNSS-Störung: GPS-Zeit weicht"))
        self.assertTrue(crit[0][3]["notify"])
        self.assertEqual(crit[0][3]["subject"], "gnss")

    def test_auto_lock_and_release_after_30_min(self):
        guard = self.baseline(self.guard())
        self.feed(guard, 60, True)
        self.assertIn("GPS", self.chrony.effective)
        self.assertEqual(self.chrony.calls, [("GPS", "+")])
        self.assertTrue(any(e[2].startswith("GPS automatisch gesperrt") for e in self.events))
        # Neuer Prozess liest den Zustand aus SQLite.
        self.assertTrue(gnssguard.load("lock")["locked"])
        # Störung vorbei: Hysterese (5 min) + 30 min Ruhe → Freigabe.
        self.feed(guard, 300 + 1700, False)
        self.assertIn("GPS", self.chrony.effective)
        self.feed(guard, 400, False)
        self.assertNotIn("GPS", self.chrony.effective)
        self.assertTrue(any(e[2].startswith("GPS-Sperre aufgehoben – 30 min") for e in self.events))
        self.assertTrue(any(e[2] == "GNSS wieder unauffällig" for e in self.events))

    def test_fourth_lock_needs_manual_release(self):
        guard = self.baseline(self.guard())
        for _ in range(3):
            self.feed(guard, 60, True)
            self.assertIn("GPS", self.chrony.effective)
            self.feed(guard, 2400, False)
            self.assertNotIn("GPS", self.chrony.effective)
        self.feed(guard, 60, True)
        self.assertIn("GPS", self.chrony.effective)
        self.assertFalse(guard.lock_status()["auto_release"])
        self.feed(guard, 4000, False)
        self.assertIn("GPS", self.chrony.effective)       # bleibt bis zur Freigabe von Hand
        guard.action(CFG, {"action": "unlock"})
        self.assertNotIn("GPS", self.chrony.effective)
        self.assertEqual(guard.lock_status()["auto_releases"], 0)

    def test_pure_jamming_never_locks(self):
        guard = self.guard()
        rng = random.Random(9)
        for i in range(400):
            self.mono[0] += 10
            shift = -15.0 if i > 240 else 0.0
            guard.tick(CFG, obs=outdoor(self.mono[0], rng, cn0_shift=shift), select=self.chrony.select())
        self.assertEqual(guard.stage, "hinweis")
        self.assertEqual(self.chrony.calls, [])
        info = [e for e in self.events if e[2].startswith("GNSS-Hinweis")]
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0][1], "info")
        self.assertFalse(info[0][3]["notify"])

    def test_manual_lock_survives_chronyd_restart_and_new_process(self):
        guard = self.guard()
        status = guard.action(CFG, {"action": "lock"})
        self.assertTrue(status["lock"]["locked"])
        self.assertIn("GPS", self.chrony.effective)
        self.chrony.restart()                              # Einstellungen gespeichert → chronyd neu
        guard.tick(dict(CFG, gnss_guard="report"), obs={"t": 1.0}, select=self.chrony.select())
        self.assertIn("GPS", self.chrony.effective)
        self.assertTrue(any("nach Neustart von chronyd erneuert" in e[2] for e in self.events))
        # ntp-gui neu gestartet und chronyd auch: neue Instanz setzt die Sperre aus SQLite neu.
        selectctl.reset_for_tests()
        self.chrony.restart()
        fresh = self.guard()
        fresh.tick(dict(CFG, gnss_guard="off"), obs={"t": 1.0}, select=self.chrony.select())
        self.assertIn("GPS", self.chrony.effective)        # von Hand gesperrt: bleibt auch bei „aus“
        fresh.action(CFG, {"action": "unlock"})
        self.assertNotIn("GPS", self.chrony.effective)
        with self.assertRaises(gnssguard.GuardError):
            fresh.action(CFG, {"action": "unlock"})

    def test_pps_locked_with_gps(self):
        self.chrony = FakeChrony(pps=True)
        selectctl.set_port(self.chrony)
        guard = self.guard()
        guard.action(CFG, {"action": "lock"})
        self.assertEqual(self.chrony.effective, {"GPS", "PPS"})

    def test_lock_errors(self):
        guard = self.guard()
        with self.assertRaises(gnssguard.GuardError):
            guard.action(dict(CFG, gps_enable=False), {"action": "lock"})
        with self.assertRaises(gnssguard.GuardError):
            guard.action(dict(CFG, gps_refid="NMEA"), {"action": "lock"})
        self.chrony.fail = True
        with self.assertRaises(gnssguard.GuardError):
            guard.action(CFG, {"action": "lock"})
        self.assertFalse(guard.lock_status()["locked"])
        with self.assertRaises(gnssguard.GuardError):
            guard.action(CFG, {"action": "kaputt"})

    def test_auto_lock_released_when_switched_to_report(self):
        guard = self.baseline(self.guard())
        self.feed(guard, 60, True)
        self.assertIn("GPS", self.chrony.effective)
        self.feed(guard, 10, True, dict(CFG, gnss_guard="report"))
        self.assertNotIn("GPS", self.chrony.effective)

    def test_manual_unlock_suppresses_relock_during_episode(self):
        guard = self.baseline(self.guard())
        self.feed(guard, 60, True)
        guard.action(CFG, {"action": "unlock"})
        self.feed(guard, 120, True)
        self.assertNotIn("GPS", self.chrony.effective)


class ConfiguredNoselectTest(StoreCase):
    fake_args = {"gps_configured_noselect": True}

    def test_never_unselects_configured_noselect(self):
        selectctl.hold("gps-lock", ["GPS"], self.chrony.select())
        self.assertEqual(self.chrony.calls, [])            # war schon noselect
        released, failed = selectctl.release("gps-lock", self.chrony.select())
        self.assertEqual((released, failed), ([], []))
        self.assertIn("GPS", self.chrony.effective)
        self.assertEqual(self.chrony.calls, [])

    def test_observe_only_set_during_lock_is_kept(self):
        # Gesperrt, dann Einstellung „nur beobachten“ (chrony.conf: refclock … refid GPS … noselect).
        self.chrony = FakeChrony()
        selectctl.set_port(self.chrony)
        selectctl.hold("gps-lock", ["GPS"], self.chrony.select())
        self.assertEqual(selectctl.added("gps-lock"), {"GPS"})
        conf = os.path.join(self.tmp, "chrony.conf")
        with open(conf, "w", encoding="utf-8") as handle:
            handle.write("server 192.0.2.1 iburst\nrefclock SHM 0 refid GPS offset 0 delay 0.2 noselect\n")
        saved = os.environ.get("CHRONY_CONF")
        os.environ["CHRONY_CONF"] = conf
        try:
            self.assertEqual(selectctl.conf_noselect_refids(), {"GPS"})
            selectctl.release("gps-lock", self.chrony.select())
        finally:
            if saved is None:
                os.environ.pop("CHRONY_CONF", None)
            else:
                os.environ["CHRONY_CONF"] = saved
        self.assertIn("GPS", self.chrony.effective)
        self.assertEqual(self.chrony.calls, [("GPS", "+")])

    def test_restart_forgets_what_conf_now_selects(self):
        # PPS war schon vor der Sperre noselect (Konfiguration), GPS hat ntp-gui abgewählt.
        self.chrony = FakeChrony(pps=True)
        self.chrony.rows["PPS"]["conf"] = True
        self.chrony.restart()
        selectctl.set_port(self.chrony)
        selectctl.hold("gps-lock", ["GPS", "PPS"], self.chrony.select())
        self.assertEqual(selectctl.added("gps-lock"), {"GPS"})
        self.chrony.restart()
        self.assertEqual(selectctl.reapply("gps-lock", self.chrony.select()), ["GPS"])
        selectctl.release("gps-lock", self.chrony.select())
        self.assertEqual(self.chrony.effective, {"PPS"})

    def test_invalid_names_rejected(self):
        with self.assertRaises(selectctl.SelectError):
            selectctl.hold("x", ["GPS; reboot"], {"GPS; reboot": {}})


# =========================================================================================
class HoldoverTest(StoreCase):
    fake_args = {"pps": True}

    def make(self):
        return holdover.HoldoverTest(emit=lambda *a: self.events.append(a), wall=lambda: self.wall[0])

    def run_for(self, test, seconds, drift_ppm=0.0, step=10.0):
        end = self.wall[0] + seconds
        while self.wall[0] < end:
            self.wall[0] += step
            for name, row in self.chrony.rows.items():
                if row["mode"] == "^":
                    row["offset"] += drift_ppm * 1e-6 * step
            result = test.tick({}, self.chrony.select())
            if result:
                return result
        return None

    def test_full_run_restores_and_reports(self):
        test = self.make()
        status = test.start({"action": "start", "hours": 1, "include_network": True, "limit_ms": 50})
        self.assertTrue(status["active"])
        self.assertEqual(self.chrony.effective, set(self.chrony.rows))   # alle abgewählt
        self.assertTrue(self.events[-1][3]["notify"] is False)
        self.run_for(test, 30, drift_ppm=1.0)
        self.assertEqual(test.status()["run"]["measured"], 3)       # abgewählt („?“), aber gemessen
        result = self.run_for(test, 3700, drift_ppm=1.0)
        self.assertEqual(result["outcome"], "done")
        self.assertEqual(self.chrony.effective, set())                    # alle wieder auswählbar
        self.assertRegex(result["sentence"], r"^Die Uhr hält 3,6 ms in 1 h$")
        self.assertAlmostEqual(result["drift_ppm"], 1.0, delta=0.05)
        stored = test.results()
        self.assertEqual(stored[0]["outcome"], "done")
        self.assertIn("Die Uhr hält", self.events[-1][2])

    def test_gps_only_keeps_network(self):
        test = self.make()
        test.start({"hours": 2, "include_network": False})
        self.assertEqual(self.chrony.effective, {"GPS", "PPS"})
        test.abort(self.chrony.select())
        self.assertEqual(self.chrony.effective, set())
        self.assertEqual(test.results()[0]["outcome"], "aborted")

    def test_limit_aborts(self):
        test = self.make()
        test.start({"hours": 24, "limit_ms": 10})
        result = self.run_for(test, 24 * 3600, drift_ppm=20.0)
        self.assertEqual(result["outcome"], "limit")
        self.assertLess(result["duration_s"], 900)
        self.assertEqual(self.chrony.effective, set())
        self.assertEqual(self.events[-1][1], "warn")

    def test_chronyd_restart_aborts_cleanly(self):
        test = self.make()
        test.start({"hours": 2})
        self.run_for(test, 120)
        self.chrony.restart()
        result = test.tick({}, self.chrony.select())
        self.assertEqual(result["outcome"], "restart")
        self.assertFalse(test.state()["active"])
        self.assertEqual(self.chrony.effective, set())
        self.assertIn("chronyd neu gestartet", self.events[-1][2])

    def test_deadline_persists_across_web_restart(self):
        test = self.make()
        test.start({"hours": 1})
        selectctl.reset_for_tests()
        self.wall[0] += 2 * 3600
        fresh = self.make()                                  # neuer Prozess: Zustand aus SQLite
        result = fresh.tick({}, self.chrony.select())
        self.assertEqual(result["outcome"], "done")
        self.assertEqual(self.chrony.effective, set())

    def test_needs_two_references(self):
        self.chrony = FakeChrony(network=1)
        selectctl.set_port(self.chrony)
        with self.assertRaises(holdover.HoldoverError) as ctx:
            self.make().start({"hours": 1})
        self.assertIn("mindestens 2", str(ctx.exception))
        self.assertEqual(self.chrony.calls, [])

    def test_validation(self):
        test = self.make()
        for bad in ({"hours": 0.5}, {"hours": 25}, {"hours": "x"}, {"limit_ms": 0}, {"include_network": "ja"},
                    {"hours": float("nan")}):
            with self.subTest(bad=bad), self.assertRaises(holdover.HoldoverError):
                test.start(bad)
        self.assertEqual(self.chrony.calls, [])
        test.start({"hours": 1})
        with self.assertRaises(holdover.HoldoverError):
            test.start({"hours": 1})

    def test_lock_survives_holdover(self):
        guard = self.guard()
        guard.action(CFG, {"action": "lock"})
        test = self.make()
        test.start({"hours": 1})
        self.assertEqual(self.chrony.effective, set(self.chrony.rows))
        test.abort(self.chrony.select())
        self.assertEqual(self.chrony.effective, {"GPS", "PPS"})     # Sperre bleibt
        guard.action(CFG, {"action": "unlock"})
        self.assertEqual(self.chrony.effective, set())

    def test_unlock_during_holdover_keeps_gps_off(self):
        test = self.make()
        test.start({"hours": 1})
        guard = self.guard()
        # Alle Netzquellen sind im Test abgewählt: Sperren nur mit ausdrücklicher Bestätigung.
        with self.assertRaises(gnssguard.GuardError) as ctx:
            guard.action(CFG, {"action": "lock"})
        self.assertIn("Trotzdem sperren", str(ctx.exception))
        guard.action(CFG, {"action": "lock", "force": True})
        guard.action(CFG, {"action": "unlock"})
        self.assertIn("GPS", self.chrony.effective)                  # Holdover hält es noch
        test.abort(self.chrony.select())
        self.assertEqual(self.chrony.effective, set())

    def test_release_retried_when_selectopts_fails(self):
        test = self.make()
        test.start({"hours": 1})
        self.assertIsNone(test.tick({}, {}))               # chronyd antwortet nicht: nichts tun
        self.chrony.fail = True
        self.wall[0] += 3700
        result = test.tick({}, self.chrony.select())
        self.assertEqual(result["outcome"], "done")
        self.assertTrue(test.state().get("release_pending"))
        self.assertIn("erneut versucht", self.events[-1][2])
        self.chrony.fail = False
        test.tick({}, self.chrony.select())
        self.assertEqual(self.chrony.effective, set())
        self.assertFalse(test.state().get("release_pending"))


# =========================================================================================
class PrivacyAndWiringTest(unittest.TestCase):
    def test_position_never_in_status(self):
        old = gps._setting
        gps._setting = lambda key: {"gps_enable": True, "gps_show_position": False, "gps_device": "/dev/x",
                                    "gps_pps_device": "", "gps_pps_shm": False}[key]
        saved_poll = gps.poll_gpsd
        gps.poll_gpsd = lambda timeout=4.0: {"TPV": {"mode": 3, "lat": 45.12345, "lon": 10.54321, "eph": 7.0},
                                             "SKY": {"satellites": [{"PRN": 1, "ss": 40, "used": True}]}}
        gps._CACHE.clear()
        try:
            state = gps.status()
        finally:
            gps._setting, gps.poll_gpsd = old, saved_poll
            gps._CACHE.clear()
        self.assertNotIn("lat", state)
        self.assertNotIn("45.12345", json.dumps(state))
        self.assertEqual(gps.private_position(), (45.12345, 10.54321, 7.0))

    def test_notification_without_coordinates(self):
        det, _stages, _t = run_scenario(lambda dt: {"pos_shift": 800.0})
        title = "GNSS-Störung: " + det.signals["position"].text
        out = egress.notify_message({"title": title, "level": "crit", "kind": "gps", "time": 1.8e9})
        self.assertIn("800 m", out["title"])
        self.assertEqual(egress.check_no_leaks(out), [])

    def test_router_respects_notify_false(self):
        router = notify.ChannelRouter({"min_level": "info", "kinds": [], "debounce_min": 0, "resolved": True},
                                      clock=lambda: 1.0, wall=lambda: 1.0)
        self.assertEqual(router.offer({"kind": "gps", "level": "warn", "title": "GNSS-Warnung: x",
                                       "data": {"subject": "gnss", "notify": False}}), [])
        sent = router.offer({"kind": "gps", "level": "crit", "title": "GNSS-Störung: x",
                             "data": {"subject": "gnss", "notify": True}})
        self.assertEqual(len(sent), 1)
        done = router.offer({"kind": "gps", "level": "info", "title": "GNSS wieder unauffällig",
                             "data": {"subject": "gnss", "resolves": True}})
        self.assertTrue(done and done[0]["resolved"])

    def test_notify_threshold_setting(self):
        emitted = []
        guard = gnssguard.Guard(emit=lambda *a: emitted.append(a), clock=lambda: 0.0, wall=lambda: 0.0)
        for i in range(5):
            guard.detector.update({"t": i * 10.0, "gps_state": "x", "sats": {f"GPS:{k}": 40.0 for k in range(8)}})
        guard._stage_event("warnung", {"gnss_notify": "warnung"})
        guard._stage_event("warnung", {"gnss_notify": "stoerung"})
        self.assertEqual([e[3]["notify"] for e in emitted], [True, False])
        self.assertEqual(emitted[0][1], "warn")

    def test_api_scopes(self):
        self.assertEqual(apiv1.required_scope("GET", "/api/v1/gnss"), "read")
        self.assertEqual(apiv1.required_scope("POST", "/api/gnss"), "admin")
        self.assertEqual(apiv1.required_scope("GET", "/api/v1/holdover"), "read")
        self.assertEqual(apiv1.required_scope("POST", "/api/v1/holdover"), "admin")

    def test_settings_fields(self):
        fields = {f["key"]: f for f in settings.SCHEMA}
        for key, default in (("gnss_guard", "report"), ("gnss_notify", "stoerung")):
            self.assertEqual(fields[key]["default"], default)
            self.assertTrue(fields[key]["env"])
            self.assertTrue(fields[key]["help"])
        with self.assertRaises(Exception):
            fields["gnss_guard"]["convert"]("immer")

    def test_selectopts_command_line(self):
        calls = []
        saved = chrony.run
        chrony.run = lambda *a, **k: calls.append(a) or "200 OK"
        try:
            selectctl.ChronyPort().selectopts("GPS", "+")
        finally:
            chrony.run = saved
        self.assertEqual(calls, [("selectopts", "GPS", "+noselect")])

    def test_insights(self):
        items = gnssguard.insights({"stage": "stoerung", "signals": [{"active": True, "text": "GPS-Zeit weicht 50 ms ab"}],
                                    "lock": {"locked": True, "manual": False, "auto_release": True}})
        self.assertEqual([i["key"] for i in items], ["gnss_stage", "gnss_lock"])
        self.assertEqual(items[0]["level"], "crit")
        run = {"active": True, "run": {"remaining_s": 3600, "deviation_ms": 1.5}}
        self.assertEqual(holdover.insights(run)[0]["key"], "holdover_running")
        self.assertEqual(holdover.insights({"active": False}), [])


# =========================================================================================
# Prüfbefunde (Review 1.5): feste Anker, eingefrorene Grundlinien, Daten fehlen, Übergaben
# =========================================================================================
def ramp(rate_ms_per_min):
    return lambda dt: {"time_shift": rate_ms_per_min / 1000.0 * dt / 60.0}


class AnchorReplayTest(unittest.TestCase):
    def test_constant_spoof_stays_stoerung_for_3h(self):
        det, stages, t0 = run_scenario(lambda dt: {"time_shift": 0.080}, after_s=3 * 3600.0)
        after = [s for t, s in stages if t >= t0 + 60.0]
        self.assertEqual(set(after), {"stoerung"})       # wird nie zur neuen Normalität
        self.assertAlmostEqual(det.signals["time"].detail["deviation_ms"], 80.0, delta=5.0)

    def test_slow_ramps_detected(self):
        # Langsames Wegziehen (carry-off): früher nie erkannt, jetzt gegen den Anker.
        for rate in (0.5, 1.0, 2.0):
            with self.subTest(rate=rate):
                _det, stages, t0 = run_scenario(ramp(rate), after_s=3 * 3600.0)
                delay = first(stages, t0, "stoerung")
                self.assertIsNotNone(delay, f"{rate} ms/min nicht erkannt")
                self.assertLess(delay, 3 * 3600.0)
                # erkannt, bevor die Zeit 150 ms weggezogen ist
                self.assertLess(rate * delay / 60.0, 150.0)

    def test_vk162_still_quiet_with_anchor(self):
        det = gnssguard.Detector()
        for obs in vk162_observations(4):
            det.update(obs)
        self.assertFalse(det.signals["time"].active)
        self.assertIsNotNone(det.time_anchor)

    def test_position_jump_stays_frozen(self):
        det, stages, t0 = run_scenario(lambda dt: {"pos_shift": 500.0}, after_s=2 * 3600.0)
        after = [s for t, s in stages if t >= t0 + 60.0]
        self.assertEqual(set(after), {"stoerung"})        # Referenz lernt den falschen Ort nicht
        self.assertTrue(det.signals["position"].active)

    def test_slow_position_drift_detected(self):
        _det, stages, t0 = run_scenario(lambda dt: {"pos_shift": 300.0 * dt / 3600.0}, after_s=3 * 3600.0)
        self.assertIsNotNone(first(stages, t0, "stoerung"))

    def test_persistent_falseticker_with_nts_is_strong(self):
        # 1.5.1: stark nur, wenn der Zeitabgleich gegen die Grundlinie eine neue Abweichung sieht –
        # hier 15 ms: unter der Zeitschwelle (20 ms), aber über der halben.
        def run(seconds, ref_kind="nts", shift=0.015, seed=4):
            rng = random.Random(seed)
            det = gnssguard.Detector()
            t = 0.0
            while t < 2400.0:
                det.update(outdoor(t, rng))
                t += 10.0
            end = t + seconds
            while t < end:
                det.update(dict(outdoor(t, rng, time_shift=shift), gps_state="x", ref_kind=ref_kind))
                t += 10.0
            return det
        det = run(600.0)
        self.assertFalse(det.signals["time"].active)
        self.assertEqual(det.stage(), "stoerung")
        self.assertEqual(det.signals["falseticker"].strength, "strong")
        self.assertIn("NTS-Quellen", det.signals["falseticker"].text)
        # Ohne NTS bleibt es ein schwaches Signal (Hinweis).
        self.assertEqual(run(600.0, ref_kind="ntp").stage(), "hinweis")
        # Kurzzeitig (unter 5 min) auch mit NTS nur Hinweis.
        self.assertEqual(run(200.0).stage(), "hinweis")
        # Ohne neue Abweichung (gleicher Abstand wie gelernt) nur Hinweis, nie stark.
        det = run(1800.0, shift=0.0)
        self.assertEqual(det.stage(), "hinweis")
        self.assertEqual(det.signals["falseticker"].strength, "weak")

    def test_falseticker_gross_error_is_strong_without_baseline(self):
        rng = random.Random(9)
        det = gnssguard.Detector()
        for i in range(60):
            det.update(dict(outdoor(i * 10.0, rng, time_shift=1.5), gps_state="x"))
        self.assertEqual(det.stage(), "stoerung")
        self.assertEqual(det.signals["falseticker"].strength, "strong")

    def test_active_signal_expires_without_data(self):
        det, _stages, _t0 = run_scenario(lambda dt: {"pos_shift": 500.0}, after_s=60.0)
        self.assertEqual(det.stage(), "stoerung")
        t = 2400.0 + 60.0
        changes = {}
        while t < 2400.0 + 6 * 3600.0:
            t += 10.0
            result = det.update({"t": t, "mode": 2, "sats": None, "gps_state": "?"})
            changes.update(result["changes"])
        self.assertEqual(det.stage(), "ok")
        self.assertEqual(changes.get("position"), "off")
        self.assertTrue(det.signals["position"].stale)


class _SlowSources(FakeChrony):
    """sources() blockiert, bis der Test es freigibt – wie ein chronyd im Neustart."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.entered = threading.Event()
        self.go = threading.Event()

    def sources(self):
        self.entered.set()
        self.go.wait(30.0)
        return super().sources()


class ReviewGuardTest(LockCase):
    def test_constant_spoof_keeps_lock_for_3h(self):
        guard = self.baseline(self.guard())
        self.feed(guard, 3 * 3600, True)
        self.assertEqual(guard.stage, "stoerung")
        self.assertIn("GPS", self.chrony.effective)
        self.assertFalse([e for e in self.events if "GPS-Sperre aufgehoben" in e[2]])
        self.assertFalse([e for e in self.events if e[2] == "GNSS wieder unauffällig"])

    def test_spoof_present_after_ntp_gui_restart(self):
        guard = self.baseline(self.guard(), dict(CFG, gnss_guard="report"))
        self.assertIsNotNone(gnssguard.load("time_anchor").get("value"))
        # Neustart von ntp-gui – der Spoofer ist schon da, bevor die neue Grundlinie entsteht.
        fresh = self.guard()
        self.feed(fresh, 900, True, dict(CFG, gnss_guard="report"))
        self.assertEqual(fresh.stage, "stoerung")
        self.assertTrue(fresh.detector.signals["time"].active)

    def test_gps_settings_change_relearns_time(self):
        guard = self.baseline(self.guard())
        self.assertIsNotNone(guard.detector.time_anchor)
        self.feed(guard, 10, False, dict(CFG, gps_offset=0.05))
        self.assertTrue(any("GPS-Einstellungen geändert" in e[2] for e in self.events))
        self.assertIsNone(guard.detector.time_anchor)
        self.assertIsNone(gnssguard.load("time_anchor").get("value"))
        self.feed(guard, 900, False, dict(CFG, gps_offset=0.05))
        self.assertEqual(guard.stage, "ok")
        self.assertIsNotNone(guard.detector.time_anchor)

    def test_relearn_forgets_stored_anchor(self):
        guard = self.baseline(self.guard())
        guard.action(CFG, {"action": "relearn"})
        self.assertIsNone(gnssguard.load("time_anchor").get("value"))
        self.assertIsNone(guard.detector.time_anchor)

    def test_stale_episode_ends_and_lock_releases(self):
        guard = self.baseline(self.guard())
        self.feed(guard, 60, True)
        self.assertIn("GPS", self.chrony.effective)
        end = self.mono[0] + 3 * 3600
        while self.mono[0] < end:                     # danach: kein Fix, GPS unerreichbar
            self.mono[0] += 10
            self.wall[0] += 10
            guard.tick(CFG, obs={"t": self.mono[0], "mode": 2, "gps_state": "?"}, select=self.chrony.select())
        self.assertEqual(guard.stage, "ok")
        ends = [e for e in self.events if e[2] == "GNSS wieder unauffällig"]
        self.assertEqual(len(ends), 1)
        self.assertIn("keine Messwerte mehr", ends[0][3]["why"])
        self.assertNotIn("GPS", self.chrony.effective)    # 30 min Ruhe → automatische Freigabe

    def test_status_not_blocked_by_slow_chronyd(self):
        slow = _SlowSources()
        selectctl.set_port(slow)
        guard = self.guard()
        saved = gnssguard.live_observation
        gnssguard.live_observation = lambda cfg, now, select, sources=None: {"t": now}
        self.addCleanup(setattr, gnssguard, "live_observation", saved)
        worker = threading.Thread(target=guard.tick, args=(CFG,), kwargs={"select": slow.select()}, daemon=True)
        worker.start()
        self.assertTrue(slow.entered.wait(10.0))
        result = {}
        reader = threading.Thread(target=lambda: result.update(status=guard.status(CFG)), daemon=True)
        reader.start()
        reader.join(10.0)
        try:
            self.assertFalse(reader.is_alive(), "status() wartet auf chronyc")
            self.assertIn("stage", result["status"])
        finally:
            slow.go.set()
            worker.join(10.0)
        self.assertFalse(worker.is_alive())


class NoOtherSourceTest(LockCase):
    fake_args = {"network": 0}

    def test_auto_lock_skipped_without_other_sources(self):
        guard = self.baseline(self.guard())
        self.feed(guard, 600, True)
        self.assertEqual(guard.stage, "stoerung")
        self.assertNotIn("GPS", self.chrony.effective)
        self.assertEqual(self.chrony.calls, [])
        skipped = [e for e in self.events if e[2].startswith("GPS-Sperre ausgelassen")]
        self.assertEqual(len(skipped), 1)                  # einmal je Episode, nicht jede 10 s
        self.assertEqual(skipped[0][1], "warn")
        self.assertEqual(guard.lock_status()["other_sources"], 0)

    def test_manual_lock_needs_force(self):
        guard = self.guard()
        with self.assertRaises(gnssguard.GuardError) as ctx:
            guard.action(CFG, {"action": "lock"})
        self.assertTrue(ctx.exception.conflict)
        self.assertNotIn("GPS", self.chrony.effective)
        status = guard.action(CFG, {"action": "lock", "force": True})
        self.assertTrue(status["lock"]["locked"])
        self.assertIn("GPS", self.chrony.effective)
        items = gnssguard.insights(status)
        self.assertIn("läuft frei", [i for i in items if i["key"] == "gnss_lock"][0]["text"])


class SelectPersistenceTest(StoreCase):
    fake_args = {"pps": True}

    def make(self):
        return holdover.HoldoverTest(emit=lambda *a: self.events.append(a), wall=lambda: self.wall[0])

    def test_handover_lock_to_holdover_survives_restart(self):
        guard = self.guard()
        guard.action(CFG, {"action": "lock"})
        test = self.make()
        test.start({"hours": 1})
        guard.action(CFG, {"action": "unlock"})            # GPS/PPS gehen an den Holdover-Test über
        self.assertEqual(self.chrony.effective, set(self.chrony.rows))
        selectctl.reset_for_tests()                          # Neustart von ntp-gui
        fresh_test, fresh_guard = self.make(), self.guard()
        fresh_guard.status(CFG)
        fresh_test.abort(self.chrony.select())
        self.assertEqual(self.chrony.effective, set())

    def test_handover_holdover_to_lock_survives_restart(self):
        test = self.make()
        test.start({"hours": 1})
        guard = self.guard()
        guard.action(CFG, {"action": "lock", "force": True})   # GPS war schon abgewählt: added = []
        test.abort(self.chrony.select())                         # GPS/PPS gehen an die Sperre über
        self.assertEqual(self.chrony.effective, {"GPS", "PPS"})
        selectctl.reset_for_tests()
        fresh = self.guard()
        status = fresh.action(CFG, {"action": "unlock"})
        self.assertFalse(status["lock"]["locked"])
        self.assertEqual(self.chrony.effective, set())

    def test_runtime_file_lists_locked_sources_only(self):
        path = os.path.join(settings.DATA_DIR, "noselect.list")
        guard = self.guard()
        guard.action(CFG, {"action": "lock"})
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "GPS\nPPS\n")
        test = self.make()
        test.start({"hours": 1})
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "GPS\nPPS\n")      # Holdover-Quellen nicht (Test bricht ab)
        guard.action(CFG, {"action": "unlock"})
        self.assertFalse(os.path.exists(path))
        test.abort(self.chrony.select())

    def test_orphan_from_runtime_file_released(self):
        os.makedirs(settings.DATA_DIR, exist_ok=True)
        with open(os.path.join(settings.DATA_DIR, "noselect.list"), "w", encoding="utf-8") as handle:
            handle.write("GPS\n")
        # Supervisor hat GPS nach dem chronyd-Start abgewählt; jemand anders hat 192.0.2.1 abgewählt.
        self.chrony.effective = {"GPS", "192.0.2.1"}
        selectctl.reset_for_tests()
        guard = self.guard()
        guard.tick(dict(CFG, gnss_guard="report"), obs={"t": 1.0}, select=self.chrony.select())
        self.assertEqual(self.chrony.effective, {"192.0.2.1"})
        self.assertTrue(any("Übrig gebliebene Abwahl" in e[2] for e in self.events))

    def test_stale_hold_without_lock_released(self):
        selectctl.hold("gps-lock", ["GPS"], self.chrony.select())
        guard = self.guard()                                  # gespeicherter Zustand: nicht gesperrt
        guard.tick(dict(CFG, gnss_guard="report"), obs={"t": 1.0}, select=self.chrony.select())
        self.assertNotIn("GPS", self.chrony.effective)

    def test_reapply_keeps_added_when_only_some_missing(self):
        selectctl.hold("gps-lock", ["GPS", "PPS"], self.chrony.select())
        self.chrony.effective.discard("PPS")                 # jemand hat nur PPS wieder freigegeben
        self.assertEqual(selectctl.reapply("gps-lock", self.chrony.select()), ["PPS"])
        self.assertEqual(selectctl.added("gps-lock"), {"GPS", "PPS"})
        selectctl.release("gps-lock", self.chrony.select())
        self.assertEqual(self.chrony.effective, set())


class HoldoverReviewTest(StoreCase):
    fake_args = {"pps": True}

    def make(self):
        return holdover.HoldoverTest(emit=lambda *a: self.events.append(a), wall=lambda: self.wall[0])

    def run_for(self, test, seconds, step=10.0):
        end = self.wall[0] + seconds
        while self.wall[0] < end:
            self.wall[0] += step
            result = test.tick({}, self.chrony.select())
            if result:
                return result
        return None

    def spread_refs(self):
        for name, offset in zip(sorted(n for n in self.chrony.rows if n.startswith("192.")), (0.0, 0.006, 0.014)):
            self.chrony.rows[name]["offset"] = offset

    def test_reference_drop_causes_no_jump(self):
        self.spread_refs()
        test = self.make()
        test.start({"hours": 1, "limit_ms": 1})
        self.assertIsNone(self.run_for(test, 600))
        self.chrony.rows["192.0.2.3"]["reach"] = 0           # der Ausreißer (14 ms) fällt aus
        self.assertIsNone(self.run_for(test, 600))
        self.assertAlmostEqual(test.status()["run"]["deviation_ms"], 0.0, delta=0.001)
        self.chrony.rows["192.0.2.3"]["reach"] = 255          # und kommt zurück
        result = self.run_for(test, 3000)
        self.assertEqual(result["outcome"], "done")
        self.assertAlmostEqual(result["deviation_ms"], 0.0, delta=0.001)

    def test_too_few_common_references_skip_points(self):
        self.spread_refs()
        test = self.make()
        test.start({"hours": 1, "limit_ms": 1})
        self.chrony.rows["192.0.2.2"]["reach"] = 0
        self.chrony.rows["192.0.2.3"]["reach"] = 0
        self.chrony.rows["192.0.2.1"]["offset"] = 0.5        # nur noch eine Referenz: zählt nicht
        self.assertIsNone(self.run_for(test, 600))
        self.assertEqual(test.status()["run"]["measured"], 1)
        self.assertTrue(test.state()["active"])

    def test_new_source_during_test_is_deselected(self):
        test = self.make()
        test.start({"hours": 1})
        self.chrony.rows["192.0.2.9"] = {"mode": "^", "auth": False, "conf": False, "offset": 0.0}
        self.assertIsNone(self.run_for(test, 30))
        self.assertIn("192.0.2.9", self.chrony.effective)
        self.assertTrue(any("neue Quelle 192.0.2.9" in e[2] for e in self.events))
        selectctl.reset_for_tests()                          # auch nach Neustart von ntp-gui bekannt
        result = self.run_for(self.make(), 3700)
        self.assertEqual(result["outcome"], "done")
        self.assertEqual(self.chrony.effective, set())

    def test_new_source_not_deselectable_invalidates(self):
        test = self.make()
        test.start({"hours": 1})
        self.chrony.rows["192.0.2.9"] = {"mode": "^", "auth": False, "conf": False, "offset": 0.0}
        self.chrony.refuse = {"192.0.2.9"}
        result = self.run_for(test, 30)
        self.assertEqual(result["outcome"], "invalid")
        self.assertIn("ungültig", result["sentence"])
        self.assertEqual(self.chrony.effective, set())

    def test_gps_only_run_is_not_a_holdover_result(self):
        test = self.make()
        test.start({"hours": 1, "include_network": False})
        result = self.run_for(test, 3700)
        self.assertEqual(result["outcome"], "done")
        self.assertTrue(result["sentence"].startswith("Ohne GPS/PPS: Abweichung"), result["sentence"])
        self.assertNotIn("Die Uhr hält", result["sentence"])
        self.assertNotIn("Die Uhr hält", self.events[-1][2])


class NotifyHintTest(unittest.TestCase):
    def test_hint_reaches_channel_with_warn_minimum(self):
        router = notify.ChannelRouter({"min_level": "warn", "kinds": [], "debounce_min": 0, "resolved": True},
                                      clock=lambda: 1.0, wall=lambda: 1.0)
        # ohne Freigabe (notify fehlt/false) bleibt ein info-Ereignis unter der Mindeststufe
        self.assertEqual(router.offer({"kind": "gps", "level": "info", "title": "GNSS-Hinweis: x",
                                       "data": {"subject": "gnss", "notify": False}}), [])
        self.assertEqual(router.offer({"kind": "gps", "level": "info", "title": "irgendwas",
                                       "data": {"subject": "anders"}}), [])
        emitted = []
        guard = gnssguard.Guard(emit=lambda *a: emitted.append(a), clock=lambda: 0.0, wall=lambda: 0.0)
        for i in range(5):
            guard.detector.update({"t": i * 10.0, "sats": {f"GPS:{k}": 45.0 + (k % 3) * 0.2 for k in range(8)}})
        guard._stage_event("hinweis", {"gnss_notify": "hinweis"})
        kind, level, title, data = emitted[0]
        self.assertEqual(level, "info")
        sent = router.offer({"kind": kind, "level": level, "title": title, "data": data})
        self.assertEqual(len(sent), 1)
        done = router.offer({"kind": "gps", "level": "info", "title": "GNSS wieder unauffällig",
                             "data": {"subject": "gnss", "resolves": True}})
        self.assertTrue(done and done[0]["resolved"])
        # Die Art-Auswahl des Kanals gilt weiter.
        only_ptp = notify.ChannelRouter({"min_level": "warn", "kinds": ["ptp"], "debounce_min": 0},
                                        clock=lambda: 1.0, wall=lambda: 1.0)
        self.assertEqual(only_ptp.offer({"kind": kind, "level": level, "title": title, "data": data}), [])


if __name__ == "__main__":
    unittest.main()


# =========================================================================================
# 1.5.1: Kein Fehlalarm nach „Offset zurücksetzen“ (Diagnosepaket eines Nutzers, Pi 4 + VK-162)
# =========================================================================================
class OffsetResetReplayTest(LockCase):
    """Nachgestellter Verlauf: GPS kalibriert (Offset 0,0526), dann setzt der Nutzer den Offset
    auf 0 zurück. Ab da liegt das GPS dauerhaft rund +51 ms neben 5 NTS-Quellen, chrony markiert
    es als Falseticker („x“). Früher: nach 5 min „GNSS-Störung“ (crit, Benachrichtigung), mit
    gnss_guard=lock sogar die Sperre. Jetzt: höchstens „Hinweis“ mit dem Rat zu kalibrieren."""

    def obs(self, t, rng, bias, state):
        # NMEA ohne PPS: einige ms Rauschen, gelegentlich Ausreißer um ± 30 ms.
        noise = rng.gauss(0, 0.004) + (rng.choice((-0.03, 0.03)) if rng.random() < 0.02 else 0.0)
        refs = [0.0002 * i + rng.gauss(0, 0.0005) for i in range(5)]
        return {"t": t, "mode": 3, "sats": None, "gps_offset": bias + noise, "gps_state": state,
                "refs": refs, "ref_kind": "nts"}

    def run_timeline(self, cfg_mode):
        guard = self.guard()
        rng = random.Random(11)
        before = dict(CFG, gnss_guard=cfg_mode, gnss_notify="stoerung", gps_offset=0.0526)
        after = dict(before, gps_offset=0.0)
        for cfg, bias, state, seconds in ((before, 0.0, "+", 3 * 3600), (after, 0.051, "x", 8 * 3600)):
            end = self.mono[0] + seconds
            while self.mono[0] < end:
                self.mono[0] += 10.0
                self.wall[0] += 10.0
                guard.tick(cfg, obs=self.obs(self.mono[0], rng, bias, state), select=self.chrony.select())
        return guard

    def test_constant_bias_after_offset_reset_is_no_alarm(self):
        guard = self.run_timeline("report")
        self.assertTrue(any("neu gelernt" in e[2] for e in self.events))
        self.assertFalse([e for e in self.events if e[1] == "crit"], self.events)
        self.assertFalse([e for e in self.events if (e[3] or {}).get("notify")])
        self.assertNotEqual(guard.stage, "stoerung")
        ft = guard.detector.signals["falseticker"]
        self.assertTrue(ft.active)
        self.assertEqual(ft.strength, "weak")
        self.assertIn("Kalibrierfehler", ft.text)
        self.assertRegex(ft.text, r"rund \+5[01] ms")
        hints = [e for e in self.events if e[2].startswith("GNSS-Hinweis")]
        self.assertTrue(hints and all(e[1] == "info" for e in hints))

    def test_constant_bias_never_locks(self):
        guard = self.run_timeline("lock")
        self.assertNotIn("GPS", self.chrony.effective)
        self.assertFalse([c for c in self.chrony.calls if c[1] == "+"])
        self.assertFalse(guard.lock_status()["locked"])

    def test_real_jump_after_relearn_still_detected(self):
        guard = self.run_timeline("report")
        rng = random.Random(12)
        cfg = dict(CFG, gnss_guard="report", gps_offset=0.0)
        end = self.mono[0] + 600
        while self.mono[0] < end:   # Spoofer zieht die Zeit um weitere 80 ms weg
            self.mono[0] += 10.0
            self.wall[0] += 10.0
            guard.tick(cfg, obs=self.obs(self.mono[0], rng, 0.131, "x"), select=self.chrony.select())
        self.assertEqual(guard.stage, "stoerung")
        self.assertTrue([e for e in self.events if e[1] == "crit"])
