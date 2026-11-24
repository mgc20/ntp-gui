"""Neustart-Koordinator (1.12): automatische Neustarts von chronyd sammeln, je Tag begrenzen, melden.

Geprüft wird das Modul allein (eigene Uhr, eigener Zustand), das Zusammenspiel mit gpsquality, autocal
und dem Holdover-Test, die Verdrahtung im Server (/api/status, /metrics) und eine Simulation über drei
Tage mit den echten Automatiken – dieselbe wie in test_gps_autopilot, nur über den Koordinator.
"""

import json
import os
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
import gpsquality  # noqa: E402
import holdover  # noqa: E402
import restartctl  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

H = 3600.0
DAY = 86400.0
T0 = 1_800_000_000.0


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.now = [T0]
        self.events, self.fired, self.gated = [], [], []
        self.started = [None]
        self.ok = [True]
        self.file = os.path.join(self.tmp, "data", "neustarts.json")
        self.coord = self.make()

    def make(self):
        def gate(trigger):
            self.gated.append(self.now[0])
            return trigger()
        coord = restartctl.Coordinator(path=lambda: self.file, wall=lambda: self.now[0],
                                       emit=lambda *a: self.events.append(a), gate=gate,
                                       started=lambda: self.started[0])
        coord.configure(chronyd=lambda: self.fire("chronyd"), full=lambda: self.fire("all"))
        return coord

    def fire(self, scope):
        if self.ok[0]:
            self.fired.append((self.now[0], scope))
        return self.ok[0]

    def advance(self, seconds, step=10.0):
        """Messschleife: alle 10 s ein tick."""
        end = self.now[0] + seconds
        results = []
        while self.now[0] < end:
            self.now[0] = min(end, self.now[0] + step)
            result = self.coord.tick()
            if result and result["decision"] not in ("collect", "wait"):
                results.append(result)
        return results

    def titles(self, level=None):
        return [e[2] for e in self.events if level is None or e[1] == level]


class CollectTest(Harness):
    def test_unknown_names_and_scopes_are_refused(self):
        self.assertFalse(self.coord.request("irgendwas"))
        self.assertFalse(self.coord.request("autocal", scope="alles"))
        self.assertFalse(os.path.exists(self.file))
        self.assertIsNone(self.coord.tick())

    def test_requests_within_window_share_one_restart(self):
        self.assertTrue(self.coord.request("autocal"))
        self.advance(60)
        self.assertEqual(self.fired, [])                       # noch im Sammelfenster
        self.assertEqual(self.coord.status()["state"], "collecting")
        self.assertTrue(self.coord.trigger_for("gps_bound")())
        self.advance(restartctl.COLLECT_SECONDS)
        self.assertEqual(len(self.fired), 1)
        self.assertEqual(self.fired[0][1], "chronyd")
        self.assertLess(self.fired[0][0] - T0, restartctl.COLLECT_SECONDS + 11)
        self.assertEqual(len(self.events), 1)
        kind, level, title, data = self.events[0]
        self.assertEqual((kind, level), ("reload", "info"))
        self.assertIn("GPS-Kalibrierung (Offset), GPS-Fehlerschranke", title)
        self.assertIn("1 von 4 in 24 h", title)
        self.assertEqual(data["who"], ["autocal", "gps_bound"])
        self.assertEqual(data["decision"], "applied")
        status = self.coord.status()
        self.assertEqual((status["auto_24h"], status["state"], status["pending"]), (1, "idle", []))

    def test_full_scope_wins(self):
        self.coord.request("autocal")
        self.coord.request("gps_bound", scope="all")
        self.coord.request("gps_bound")                          # bleibt „all“
        self.advance(restartctl.COLLECT_SECONDS + 10)
        self.assertEqual([s for _t, s in self.fired], ["all"])

    def test_goes_through_holdover_gate(self):
        """Gesammelt angewandt wird über holdover.reload_or_defer: Läuft ein Test, folgt der Neustart danach."""
        deferred = []

        class FakeTest:
            def reload_or_defer(self, trigger):
                deferred.append(trigger)
                return True                                       # „fest vorgemerkt“

        coord = restartctl.Coordinator(path=lambda: self.file, wall=lambda: self.now[0],
                                       emit=lambda *a: self.events.append(a), started=lambda: None)
        coord.configure(chronyd=lambda: self.fire("chronyd"))
        with mock.patch.object(holdover, "TEST", FakeTest()):
            coord.request("gps_bound")
            self.now[0] += restartctl.COLLECT_SECONDS + 1
            self.assertEqual(coord.tick()["decision"], "applied")
        self.assertEqual(len(deferred), 1)
        self.assertEqual(self.fired, [])                          # der Test entscheidet, wann
        self.assertEqual(coord.status()["auto_24h"], 1)


class LimitTest(Harness):
    def run_requests(self, count, gap=H):
        for _ in range(count):
            self.coord.request("gps_bound")
            self.advance(gap)

    def test_daily_limit_holds_back_and_catches_up(self):
        self.run_requests(restartctl.MAX_PER_DAY)
        self.assertEqual(len(self.fired), restartctl.MAX_PER_DAY)
        self.coord.request("gps_bound")
        self.coord.request("autocal")
        self.advance(10 * H, step=60.0)
        self.assertEqual(len(self.fired), restartctl.MAX_PER_DAY)  # gesperrt
        warn = self.titles("warn")
        self.assertEqual(len(warn), 1)                             # ein Ereignis je Wartezeit
        self.assertIn("Tagesgrenze automatischer Neustarts erreicht (4 in 24 h)", warn[0])
        status = self.coord.status()
        self.assertEqual(status["state"], "limit")
        self.assertEqual(status["next_try"], self.fired[0][0] + DAY)   # wenn der älteste aus dem Fenster fällt
        self.assertEqual(status["pending"], ["GPS-Kalibrierung (Offset)", "GPS-Fehlerschranke"])
        self.advance(DAY, step=60.0)
        self.assertEqual(len(self.fired), restartctl.MAX_PER_DAY + 1)
        self.assertGreaterEqual(self.fired[-1][0], self.fired[0][0] + DAY)
        self.assertIn("nach Tagesgrenze nachgeholt", self.titles("info")[-1])
        self.assertEqual(self.coord.status()["state"], "idle")

    def test_never_more_than_limit_in_any_day(self):
        """Zwei Automatiken wollen zwei Tage lang stündlich neu starten: nie mehr als die Grenze in 24 h,
        und am Ende ist alles übernommen."""
        for hour in range(48):
            self.coord.request("gps_bound" if hour % 2 else "autocal")
            self.advance(H, step=60.0)
        self.advance(DAY, step=60.0)
        times = [t for t, _s in self.fired]
        for i, start in enumerate(times):
            self.assertLessEqual(len([t for t in times[i:] if t < start + DAY]), restartctl.MAX_PER_DAY)
        self.assertEqual(self.coord.status()["pending"], [])
        self.assertLessEqual(len(times), 3 * restartctl.MAX_PER_DAY)

    def test_user_restarts_are_not_counted(self):
        """Was ein Mensch auslöst, geht nicht über den Koordinator – nimmt aber Wartendes mit."""
        self.run_requests(restartctl.MAX_PER_DAY)
        self.coord.request("gps_bound")
        self.advance(H)
        self.assertEqual(self.coord.status()["state"], "limit")
        self.started[0] = self.now[0]                              # du speicherst: chronyd startet neu
        result = self.advance(10)
        self.assertEqual(result[0]["decision"], "taken_along")
        self.assertEqual(len(self.fired), restartctl.MAX_PER_DAY)
        self.assertEqual(self.coord.status()["auto_24h"], restartctl.MAX_PER_DAY)
        self.assertIn("mit dem letzten Neustart von chronyd übernommen", self.titles()[-1])


class TakeAlongTest(Harness):
    def test_restart_for_other_reason_takes_change_along(self):
        self.coord.request("autocal")
        self.now[0] += restartctl.TAKE_ALONG_MARGIN + 5
        self.started[0] = self.now[0]                              # Zertifikat/Hotplug/du
        self.assertEqual(self.coord.tick()["decision"], "taken_along")
        self.assertEqual(self.fired, [])
        self.assertEqual(self.coord.status()["auto_24h"], 0)
        self.assertEqual(self.events[-1][3]["decision"], "taken_along")

    def test_restart_right_after_request_does_not_count(self):
        """Ein Neustart, der kurz nach der Anforderung endete, hat die Konfiguration womöglich vorher erzeugt."""
        self.coord.request("autocal")
        self.started[0] = self.now[0] + 5
        self.advance(restartctl.COLLECT_SECONDS + 10)
        self.assertEqual(len(self.fired), 1)

    def test_old_restart_is_ignored(self):
        self.started[0] = T0 - 100
        self.coord.request("autocal")
        self.advance(restartctl.COLLECT_SECONDS + 10)
        self.assertEqual(len(self.fired), 1)


class FailureAndStateTest(Harness):
    def test_failed_request_retries_with_one_event(self):
        self.ok[0] = False
        self.coord.request("gps_bound")
        self.advance(restartctl.COLLECT_SECONDS + 10)
        self.advance(restartctl.RETRY_SECONDS - 60)
        self.assertEqual(len(self.gated), 1)
        self.assertEqual(len(self.titles("warn")), 1)
        self.assertIn("ließ sich nicht anfordern", self.titles("warn")[0])
        self.assertEqual(self.coord.status()["state"], "retry")
        self.ok[0] = True
        self.advance(120)
        self.assertEqual(len(self.fired), 1)
        self.assertEqual(self.coord.status()["auto_24h"], 1)

    def test_state_survives_restart_of_ntp_gui(self):
        self.coord.request("gps_bound")
        self.advance(restartctl.COLLECT_SECONDS + 10)
        self.coord.request("autocal")
        again = self.make()                                        # neuer Prozess, gleiche Datei
        status = again.status()
        self.assertEqual(status["auto_24h"], 1)
        self.assertEqual(status["pending"], ["GPS-Kalibrierung (Offset)"])
        self.now[0] += restartctl.COLLECT_SECONDS + 1
        self.assertEqual(again.tick()["decision"], "applied")
        with open(self.file, encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn("Kalibrierung", raw)                      # nur feste Namen und Zeiten
        self.assertEqual(oct(os.stat(self.file).st_mode & 0o777), "0o600")

    def test_broken_or_foreign_state_is_ignored(self):
        os.makedirs(os.path.dirname(self.file), exist_ok=True)
        for content in ("{kaputt", "[]", '{"v": 99, "auto": [1]}',
                        json.dumps({"v": 1, "auto": ["x", None, True, T0], "pending": {"since": "x"}}),
                        json.dumps({"v": 1, "auto": [], "pending": {"since": T0, "who": {"fremd": "all"}}})):
            with open(self.file, "w", encoding="utf-8") as handle:
                handle.write(content)
            status = self.coord.status()
            self.assertEqual(status["pending"], [], content)
            self.assertLessEqual(status["auto_24h"], 1, content)
            self.assertIsNone(self.coord.tick(), content)

    def test_clock_set_back_does_not_block_forever(self):
        self.coord.request("autocal")
        self.now[0] -= 30 * DAY                                     # Pi ohne RTC: Uhr weit zurück
        self.advance(restartctl.COLLECT_SECONDS + 20)
        self.assertEqual(len(self.fired), 1)

    def test_clock_set_back_keeps_recent_restarts_counted(self):
        for _ in range(restartctl.MAX_PER_DAY):
            self.coord.request("gps_bound")
            self.advance(H)
        self.now[0] -= 2 * H                                       # leicht zurückgestellt: zählen weiter
        self.assertEqual(self.coord.status()["auto_24h"], restartctl.MAX_PER_DAY)

    def test_module_helpers_never_raise(self):
        with mock.patch.object(restartctl.COORD, "_load", side_effect=RuntimeError("kaputt")):
            self.assertIsNone(restartctl.tick())
            self.assertEqual(restartctl.status()["state"], "unknown")


class AutomaticsWiringTest(unittest.TestCase):
    """gpsquality und autocal: die Automatik geht über auto_reload, was ein Mensch auslöst, nicht."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        self.direct, self.queued = [], []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        gpsquality._DEPS.update(history=None, trigger_reload=None, emit=None, net_distance=None, auto_reload=None)
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gps_bound_automatic_goes_to_coordinator_reset_stays_direct(self):
        from test_gpsquality import cfg as gq_cfg, vk162_samples
        gpsquality.configure(trigger_reload=lambda: self.direct.append(1) or True,
                             auto_reload=lambda: self.queued.append(1) or True,
                             emit=lambda *a, **k: None)
        samples = vk162_samples(loops=5)
        decision = gpsquality.tick(gq_cfg(), samples[-1]["t"] + 1, samples)
        self.assertTrue(decision["apply"])
        self.assertTrue(decision["reload_triggered"])
        self.assertEqual((len(self.queued), len(self.direct)), (1, 0))
        gpsquality.reset(gq_cfg(), samples[-1]["t"] + 2)            # „Auf Standard zurücksetzen“
        self.assertEqual((len(self.queued), len(self.direct)), (1, 1))

    def test_without_auto_reload_old_behaviour(self):
        from test_gpsquality import cfg as gq_cfg, vk162_samples
        gpsquality.configure(trigger_reload=lambda: self.direct.append(1) or True, emit=lambda *a, **k: None)
        samples = vk162_samples(loops=5)
        self.assertTrue(gpsquality.tick(gq_cfg(), samples[-1]["t"] + 1, samples)["apply"])
        self.assertEqual(len(self.direct), 1)

    def test_autocal_dependency_is_known(self):
        self.assertIn("auto_reload", autocal._DEPS)
        autocal.configure(auto_reload=None)                          # bekannt: kein TypeError


class ServerTest(unittest.TestCase):
    def test_status_and_metrics(self):
        import server
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        coord = restartctl.Coordinator(path=lambda: os.path.join(tmp, "n.json"), wall=lambda: T0,
                                       emit=lambda *a: None, gate=lambda trig: trig(), started=lambda: None)
        coord.configure(chronyd=lambda: True)
        coord.request("gps_bound")
        with mock.patch.object(restartctl, "COORD", coord):
            text = server.build_metrics()
            self.assertEqual(restartctl.status()["state"], "collecting")
        for line in ("ntpgui_auto_restarts_24h 0", "ntpgui_auto_restart_limit 4", "ntpgui_auto_restart_pending 1",
                     "ntpgui_auto_restart_limited 0"):
            self.assertRegex(text, rf"(?m)^{line}$")
        self.assertIn("# TYPE ntpgui_auto_restarts_24h gauge", text)
        self.assertNotRegex(text, r"ntpgui_auto_restart\w*\{")       # keine Labels


import test_frontend_states as fs  # noqa: E402

mod = fs.mod


class OverviewRowTest(unittest.TestCase):
    """Übersicht, Karte Dienste: Zeile „Automatische Neustarts“ (Zahl, Grenze, was wartet)."""

    run_js = fs.NodeTest.run_js

    @unittest.skipUnless(shutil.which("node"), "node fehlt")
    def test_row_texts(self):
        out = self.run_js(f"""
const ov = await import({mod("pages/overview.js")});
const t = (v) => typeof v === "string" ? v : text(v);
const sys = {{ time: 1783000000, utc_offset: 7200 }};
console.log(JSON.stringify({{
  idle: t(ov.restartsValue({{ auto_24h: 1, limit: 4, pending: [], state: "idle" }}, sys)),
  collecting: t(ov.restartsValue({{ auto_24h: 0, limit: 4, pending: ["GPS-Fehlerschranke"], state: "collecting",
    next_try: 1783000120 }}, sys)),
  limit: t(ov.restartsValue({{ auto_24h: 4, limit: 4, pending: ["GPS-Fehlerschranke"], state: "limit",
    next_try: 1783003600 }}, sys)),
  title: ov.restartsValue({{ auto_24h: 4, limit: 4, pending: ["A", "B"], state: "limit", next_try: 1783003600 }}, sys)
    .getAttribute("title"),
  none: ov.restartsValue(null), unknown: ov.restartsValue({{ auto_24h: null, limit: 4, state: "unknown" }}),
}}));
""", tz="America/New_York")
        self.assertEqual(out["idle"], "1 von 4 in 24 h")
        self.assertEqual(out["collecting"], "0 von 4 in 24 h wird gesammelt")
        self.assertEqual(out["limit"], "4 von 4 in 24 h wartet bis 16:46")      # Zeit des Servers (UTC+2), nicht New York
        self.assertEqual(out["title"], "Wartet: A, B")
        self.assertIsNone(out["none"])
        self.assertIsNone(out["unknown"])


try:
    from test_gps_autopilot import Sim, _SimCase, T0 as SIM_T0
except Exception:  # pragma: no cover – Simulation fehlt: Rest der Tests läuft weiter
    Sim = None


if Sim is not None:
    class CoordinatedSim(Sim):
        """Wie test_gps_autopilot, aber beide Automatiken über einen Koordinator; er tickt jede Minute."""

        def __init__(self, tmp, pps=False, seed=7):
            self.coord_events = []
            super().__init__(tmp, pps=pps, seed=seed)

        def _fresh_process(self):
            super()._fresh_process()
            self.coord = restartctl.Coordinator(
                path=lambda: os.path.join(self.tmp, "neustarts.json"), wall=lambda: self.now,
                emit=lambda *a: self.coord_events.append(a) or self.emit(*a), gate=lambda trig: trig(),
                started=self._started)
            self.coord.configure(chronyd=lambda: self.reload("Koordinator"))
            self.deps["auto_reload"] = self.coord.trigger_for("autocal")
            gpsquality.configure(auto_reload=self.coord.trigger_for("gps_bound"))

        def _started(self):
            try:
                with open(os.path.join(self.run_dir, "reload.json"), encoding="utf-8") as handle:
                    return json.load(handle).get("time")
            except (OSError, ValueError):
                return None

        def step(self):
            super().step()
            self.coord.tick()

    class CoordinatedSimTest(_SimCase):
        SIM = CoordinatedSim

        def setUp(self):
            super().setUp()
            self.addCleanup(gpsquality._DEPS.update, auto_reload=None)

        def test_three_days_hands_free_through_coordinator(self):
            sim = self.sim
            sim.run_until(SIM_T0 + 3 * H)
            sim.container_restart()
            sim.run_until(SIM_T0 + 3 * DAY)
            changes = self.changes()
            result = {"restarts": [(round((t - SIM_T0) / H, 2), why) for t, why in sim.restarts],
                      "changes_h": [round((c["t"] - SIM_T0) / H, 1) for c in changes],
                      "offset_ms": round(sim.cfg["gps_offset"] * 1000, 1)}
            self.assertTrue(sim.restarts, result)
            self.assertTrue(all(why == "Koordinator" for _t, why in sim.restarts), result)
            self.assertLessEqual(len(sim.restarts), 2, result)
            self.assertLess(abs(sim.cfg["gps_offset"] - Sim.LATENCY), 0.002, result)
            self.assertEqual(sim.running["offset"], sim.cfg["gps_offset"])   # übernommen
            self.assertTrue(0.010 <= sim.running["delay"] / 2 <= 0.030, result)
            for change in changes:                                   # gesammelt, aber zeitnah
                after = [t for t, _w in sim.restarts if t >= change["t"]]
                self.assertTrue(after and after[0] - change["t"] <= restartctl.COLLECT_SECONDS + 60, result)
            self.assertTrue(all(e[3]["decision"] == "applied" for e in sim.coord_events), sim.coord_events)
            self.assert_quiet()


if __name__ == "__main__":
    unittest.main()
