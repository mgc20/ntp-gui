"""Simulation: GPS-Automatik ohne Zutun (1.5.2, Entscheidung E19).

Drei Tage ab einer frischen Installation mit Standard-Einstellungen (nur GPS_ENABLE=true, keine
settings.json) – mit den echten Modulen settings, autocal, gpsquality, gnssguard und history.calibrate.
Nur chrony, gpsd und die Uhr sind nachgebildet (injizierte Uhr, ein Messpunkt je Minute):

* Empfänger wie der VK-162 eines Nutzers: NMEA-Verspätung ~ +51 ms, Tagesgang ± 4 ms, Rauschen
  1,5 ms, 1 % Ausreißer bis ± 25 ms, Fix-Flattern (der Fix reißt im Mittel alle ~50 min für ein bis
  drei Minuten ab).
* Fünf genutzte NTS-Quellen (Root Distance ~ 10 ms), die Systemuhr folgt ihnen.
* chrony: GPS „x“, wenn sein Intervall (± Delay/2) das der Netzquellen nicht mehr trifft, „+“ bei
  kleiner Schranke, sonst „-“; nach jedem Neustart von chronyd zwei Minuten ohne GPS-Werte.
* Unterwegs: Neustart des Containers mitten in der ersten Messung (3 h) und ein GPS-Ausfall von 6 h
  (Empfänger ab, Tag 2).

Geprüft wird, was „ohne Zutun“ heißt: Der Offset stimmt nach etwa 12 h, chronyd startet für die
Korrektur höchstens zweimal neu, es gibt keine Warnung/Störung und keine Benachrichtigung, danach
pendelt nichts, und die Fehlerschranke schrumpft vom vorsichtigen Standard (± 100 ms) auf einen
sinnvollen Wert. Ein zweiter Lauf prüft eine PPS-Installation (behutsame 5-ms-Schritte, je 24 h).
"""

import json
import math
import os
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import autocal  # noqa: E402
import gnssguard  # noqa: E402
import gpsquality  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

H = 3600.0
DAY = 86400.0
T0 = 1_800_000_000.0
STEP = 60.0


class History:
    def __init__(self):
        self.samples = []

    def snapshot(self, since=None):
        return [s for s in self.samples if since is None or s["t"] >= since]


class Sim:
    """Ein Server mit USB-GPS, nachgebildet bis auf die echten Entscheidungsmodule."""

    LATENCY = 0.051
    SWING = 0.004
    NETS = 5                 # genutzte Netzquellen …
    NTS = True               # … mit NTS (False: pool.ntp.org oder PTB über reines NTP)

    def __init__(self, tmp, pps=False, seed=7):
        self.tmp = tmp
        self.rng = random.Random(seed)
        self.now = T0
        self.env = {"GPS_ENABLE": "true"}
        if pps:
            self.env["GPS_PPS_SHM"] = "true"
        self.cfg = settings.values(self.env)            # frische Installation: nur Standardwerte
        self.hist = History()
        self.events = []
        self.restarts = []                               # (Zeit, Auslöser)
        self.blackout_until = 0.0
        self.gps_off = None                              # (von, bis): Empfänger ab
        self.fix = True
        self.cause = "start"
        self.running = {}
        self._start_chrony()
        self.run_dir = os.path.join(tmp, "run")
        os.makedirs(self.run_dir, exist_ok=True)
        gpsquality.configure(history=self.hist, trigger_reload=lambda: self.reload("Fehlerschranke"),
                             emit=self.emit, net_distance=lambda: gpsquality.nts_distance(self.sources()))
        self._fresh_process()
        self.next_tick = self.now
        self.base_cn0 = {f"GP:{i}": 22.0 + 2.2 * i for i in range(9)}

    # --- Prozess von ntp-gui (Neustart des Containers = neue Objekte, gleiche Dateien) --------------
    def _fresh_process(self):
        gpsquality._OFFSET.update({"for": None, "value": None, "since": None})
        gpsquality._LAST_TICK["mono"] = None
        autocal._LAST_TICK["t"] = None
        self.guard = gnssguard.Guard(emit=self.emit, clock=lambda: self.now, wall=lambda: self.now)
        self.deps = {
            "get_calibration": autocal.make_calibration_getter(self.hist, lambda: self.cfg, clock=lambda: self.now),
            "get_sources": self.sources,
            "save_settings": self.save_settings,
            "trigger_reload": lambda: self.reload("Kalibrierung"),
            "emit_event": self.emit,
            "guard_hold": self.guard.calibration_hold,
            "offset_since": lambda cfg, now: gpsquality.note_offset(cfg, now),
            "adopt_bound": gpsquality.adopt_calibration,
            "measure_reset": self.guard.relearned_at,
        }

    def container_restart(self):
        self._fresh_process()
        self._start_chrony()

    # --- chrony / Supervisor ---------------------------------------------------------------------
    def _start_chrony(self):
        values = gpsquality.refclock_values(self.cfg)
        self.running = {"offset": float(self.cfg["gps_offset"]), "delay": float(values["delay"])}
        self.blackout_until = self.now + 120.0

    def reload(self, why):
        self.restarts.append((self.now, why))
        self._start_chrony()
        with open(os.path.join(self.run_dir, "reload.json"), "w", encoding="utf-8") as handle:
            json.dump({"state": "done", "time": self.now}, handle)
        return True

    def save_settings(self, changes):
        result = settings.save(changes)
        self.cfg = settings.values(self.env)
        return result

    def emit(self, kind, level, title, data=None, **_):
        self.events.append({"t": self.now, "kind": kind, "level": level, "title": title, "data": data or {}})

    def sources(self):
        return [{"name": f"nts{i}", "mode": "^", "state": "*" if i == 0 else "+", "authenticated": self.NTS,
                 "reach": 255, "ntp": {"root_delay": 0.010, "peer_delay": 0.008, "root_dispersion": 0.001,
                                       "peer_dispersion": 0.0005}} for i in range(self.NETS)]

    # --- ein Messpunkt je Minute --------------------------------------------------------------------
    def latency(self):
        swing = self.SWING * math.cos(2 * math.pi * (self.now - T0 - 3 * H) / DAY)   # Höchstwert um 3 h
        noise = self.rng.gauss(0.0, 0.0015)
        if self.rng.random() < 0.01:
            noise += self.rng.uniform(-0.025, 0.025)
        return self.LATENCY + swing + noise

    def step(self):
        self.now += STEP
        off = self.gps_off is not None and self.gps_off[0] <= self.now < self.gps_off[1]
        if self.fix and self.rng.random() < 0.02:
            self.fix = False
        elif not self.fix and self.rng.random() < 0.5:
            self.fix = True
        nets = {f"nts{i}": self.rng.gauss(0.0, 0.0005) for i in range(self.NETS)}
        net_mid = sorted(nets.values())[self.NETS // 2]
        sats = {k: v + self.rng.gauss(0.0, 1.5) for k, v in self.base_cn0.items()}
        mode = 3 if self.fix else 1
        sources = {name: {"o": o, "s": "*" if name == "nts0" else "+", "k": "^"} for name, o in nets.items()}
        obs = {"t": self.now, "refs": list(nets.values()), "ref_kind": "nts" if self.NTS else "ntp"}
        if "GPS_PPS_SHM" in self.env:
            obs["pps_state"] = "*"                       # chrony nutzt das PPS
        if off:
            sources["GPS"] = {"o": 0.0, "s": "?", "k": "#", "r": 0}
            obs.update(gps_state="?")
            gps_point = None
        else:
            gps_point = {"mode": mode, "used": 7 if self.fix else 2, "seen": 12, "cn4": 34.0}
            obs.update(mode=mode, sats=sats)
            if not self.fix or self.now < self.blackout_until:
                sources["GPS"] = {"o": 0.0, "s": "?", "k": "#", "r": 0}
                obs.update(gps_state="?")
            else:
                o = self.latency() - self.running["offset"]
                half = self.running["delay"] / 2
                if abs(o - net_mid) > half + 0.0105:
                    state = "x"
                elif half <= 3 * 0.0105:
                    state = "+"
                else:
                    state = "-"
                sources["GPS"] = {"o": o, "s": state, "k": "#", "r": 255}
                obs.update(gps_offset=o, gps_state=state)
        sample = {"t": self.now, "sources": sources}
        if gps_point:
            sample["gps"] = gps_point
        self.hist.samples.append(sample)
        self.guard.tick(self.cfg, obs=obs, select={})
        gpsquality.note_offset(self.cfg, self.now)
        if self.now >= self.next_tick:                   # stündlich, wie die Messschleife
            self.next_tick = self.now + H
            with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": self.run_dir, "WEB_READONLY": ""}):
                autocal.tick(self.cfg, self.now, deps=self.deps)
                self.cfg = settings.values(self.env)
                gpsquality.tick(self.cfg, self.now)

    def run_until(self, t):
        while self.now < t:
            self.step()

    def status(self):
        with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": self.run_dir, "WEB_READONLY": ""}):
            return autocal.api_status(self.cfg, self.now, fresh=True, deps=self.deps)


class _SimCase(unittest.TestCase):
    PPS = False
    SIM = Sim

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        saved = (settings.DATA_DIR, settings.SETTINGS_FILE)
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        settings.SETTINGS_FILE = os.path.join(settings.DATA_DIR, "settings.json")
        settings._CACHE.update(mtime=None, data=None)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("GPS_", "GNSS_", "NTP_", "NTS_", "PTP_", "WEB_"))}
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        autocal._CAL_CACHE.update(key=None, t=None, window=None, result=None)

        def cleanup():
            patch.stop()
            gpsquality._DEPS.update(history=None, trigger_reload=None, emit=None, net_distance=None)
            gpsquality._OFFSET.update({"for": None, "value": None, "since": None})
            gpsquality._LAST_TICK["mono"] = None
            autocal._LAST_TICK["t"] = None
            store.close_all()
            settings.DATA_DIR, settings.SETTINGS_FILE = saved
            settings._CACHE.update(mtime=None, data=None)
            shutil.rmtree(self.tmp, ignore_errors=True)
        self.addCleanup(cleanup)
        self.sim = self.SIM(self.tmp, pps=self.PPS)

    def changes(self):
        return [c for c in autocal.load()["changes"] if c.get("kind") == "auto"]

    def assert_quiet(self):
        loud = [e for e in self.sim.events if e["level"] in {"warn", "crit"} or e["data"].get("notify")]
        self.assertEqual(loud, [], "Warnung, Störung oder Benachrichtigung – ohne Zutun darf es die nicht geben")
        self.assertEqual(self.sim.guard.stage, "ok")


class FreshInstallWithoutPpsTest(_SimCase):
    """USB-GPS ohne PPS, fünf NTS-Quellen, nur Standard-Einstellungen – drei Tage."""

    def test_three_days_hands_free(self):
        sim = self.sim
        self.assertEqual(sim.cfg["gps_autocal"], "auto")
        self.assertEqual(sim.cfg["gps_offset"], 0.0)
        self.assertEqual(sim.running["delay"], gpsquality.DEFAULT_DELAY)
        self.assertFalse(os.path.exists(settings.SETTINGS_FILE))

        sim.run_until(T0 + 3 * H)
        status = sim.status()
        self.assertEqual(status["mode"], "auto")
        self.assertEqual(status["phase"]["key"], "measure")
        self.assertRegex(status["phase"]["label"], r"misst \(\d,\d von 6,0 h\)")
        self.assertNotIn("übernimm", status["plan"])
        self.assertNotIn("Vorschlag übernehmen", status["plan"])
        self.assertEqual(sim.restarts, [])               # die Schranke wartet auf die Korrektur

        sim.container_restart()                          # Neustart mitten in der ersten Messung
        sim.run_until(T0 + 12 * H)
        first = self.changes()
        self.assertEqual(len(first), 1, first)
        self.assertLessEqual(first[0]["t"], T0 + 7.5 * H)   # Messung lief über den Neustart weiter
        self.assertLess(abs(sim.cfg["gps_offset"] - Sim.LATENCY), 0.005)
        self.assertEqual(sim.running["offset"], sim.cfg["gps_offset"])
        self.assertLess(sim.running["delay"], 0.1)       # Schranke im selben Neustart mitgeschrieben
        self.assertEqual([why for _t, why in sim.restarts], ["Kalibrierung"])

        sim.gps_off = (T0 + 40 * H, T0 + 46 * H)         # Empfänger sechs Stunden ab
        sim.run_until(T0 + 3 * DAY)
        changes = self.changes()
        steps = [round((c["new_offset"] - c["old_offset"]) * 1000, 1) for c in changes]
        result = {
            "offset_12h_ms": round(first[0]["new_offset"] * 1000, 1),
            "offset_end_ms": round(sim.cfg["gps_offset"] * 1000, 1),
            "changes_h": [round((c["t"] - T0) / H, 1) for c in changes], "steps_ms": steps,
            "restarts": [(round((t - T0) / H, 1), why) for t, why in sim.restarts],
            "bound_ms": round(sim.running["delay"] / 2 * 1000, 1),
        }
        print(f"\n[sim ohne PPS] {result}")
        self.assertLessEqual(len(sim.restarts), 2, result)
        self.assertLessEqual(len(changes), 2, result)
        self.assertTrue(all(abs(s) <= 5.0 for s in steps[1:]), result)     # danach nur kleine Drifts
        later = [c for c in changes if c["t"] > T0 + 12 * H]
        self.assertTrue(all(c["t"] - first[0]["t"] >= autocal.AUTO_INTERVAL for c in later), result)
        self.assertLess(abs(sim.cfg["gps_offset"] - Sim.LATENCY), 0.002, result)
        self.assertTrue(0.010 <= sim.running["delay"] / 2 <= 0.030, result)   # ± 10 … 30 ms statt ± 100 ms
        self.assert_quiet()
        self.assertIsNone(sim.guard.calibration_hold(sim.now - DAY))
        status = sim.status()
        self.assertIn(status["phase"]["key"], {"calibrated", "drift_wait", "measure"}, status["phase"])
        self.assertIsNone(status["manual_change"])
        # Nach der Konvergenz kein Hin und Her: ein weiterer Tag ändert nichts.
        before = len(self.changes())
        sim.run_until(T0 + 4 * DAY)
        self.assertEqual(len(self.changes()), before)
        self.assertLessEqual(len(sim.restarts), 2)
        self.assert_quiet()


class FreshInstallWithPpsTest(_SimCase):
    """Mit PPS ist das GPS die Referenz: behutsame Schritte (höchstens 5 ms je 24 h), ohne Zutun."""

    PPS = True

    def test_three_days_small_steps(self):
        sim = self.sim
        self.assertEqual(sim.cfg["gps_autocal"], "auto")
        self.assertTrue(gpsquality.has_pps(sim.cfg))
        sim.run_until(T0 + 3 * DAY)
        changes = self.changes()
        steps = [round((c["new_offset"] - c["old_offset"]) * 1000, 1) for c in changes]
        print(f"\n[sim mit PPS] Änderungen nach h: {[round((c['t'] - T0) / H, 1) for c in changes]}, "
              f"Schritte ms: {steps}, Neustarts: {len(sim.restarts)}")
        self.assertEqual(len(changes), 3, steps)
        self.assertTrue(all(0 < s <= 5.0 for s in steps), steps)          # eine Richtung, kleine Schritte
        gaps = [b["t"] - a["t"] for a, b in zip(changes, changes[1:])]
        self.assertTrue(all(g >= autocal.AUTO_INTERVAL for g in gaps), gaps)
        self.assertEqual(len(sim.restarts), len(changes))
        self.assert_quiet()
        self.assertIn(sim.status()["phase"]["key"], {"measure", "step_wait"})


class PoolSim(Sim):
    NETS = 4
    NTS = False


class FreshInstallPoolWithoutNtsTest(_SimCase):
    """Prüfbefund 1.5.2: Standardquellen (pool.ntp.org, vier Server ohne NTS) – vorher kroch der Offset
    10–24 Tage lang mit rund zwei Neustarts von chronyd pro Tag."""

    SIM = PoolSim

    def test_one_step_after_twelve_hours(self):
        sim = self.sim
        sim.run_until(T0 + 3 * DAY)
        changes = self.changes()
        steps = [round((c["new_offset"] - c["old_offset"]) * 1000, 1) for c in changes]
        print(f"\n[sim pool ohne NTS] Änderungen nach h: {[round((c['t'] - T0) / H, 1) for c in changes]}, "
              f"Schritte ms: {steps}, Neustarts: {[(round((t - T0) / H, 1), w) for t, w in sim.restarts]}")
        self.assertTrue(changes and changes[0]["t"] <= T0 + 14 * H, steps)
        self.assertGreater(abs(steps[0]), 40.0)                            # in einem Schritt
        self.assertLess(abs(sim.cfg["gps_offset"] - Sim.LATENCY), 0.003)
        self.assertLessEqual(len(sim.restarts), 3)
        self.assert_quiet()


class PpsLateNmeaSim(Sim):
    LATENCY = 0.120


class PpsWithLateNmeaTest(_SimCase):
    """Prüfbefund 1.5.2: PPS genutzt, NMEA 120 ms spät – vorher „Störung“ mit Benachrichtigung und
    dauerhafte Sperre der Automatik (gegenseitige Blockade)."""

    PPS = True
    SIM = PpsLateNmeaSim

    def test_no_stoerung_and_no_hold(self):
        sim = self.sim
        sim.run_until(T0 + 2 * DAY)
        crit = [e for e in sim.events if e["level"] == "crit"]
        self.assertEqual(crit, [])
        self.assertTrue(self.changes())                                    # die Automatik arbeitet
        self.assertNotEqual(sim.status()["phase"]["key"], "hold")


if __name__ == "__main__":
    unittest.main()
