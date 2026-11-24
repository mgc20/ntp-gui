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
        self.busy = [False]                    # Holdover-Test läuft?
        self.arrived = {}                      # who -> True/False/None: steht die Änderung in chrony.conf?
        self.want = {}                         # who -> Wert, den die Einstellungen gerade vorgeben (None = unbekannt)
        self.file = os.path.join(self.tmp, "data", "neustarts.json")
        self.coord = self.make()

    def make(self):
        def gate(trigger):
            self.gated.append(self.now[0])
            return trigger()
        coord = restartctl.Coordinator(path=lambda: self.file, wall=lambda: self.now[0],
                                       emit=lambda *a: self.events.append(a), gate=gate,
                                       started=lambda: self.started[0], busy=lambda: self.busy[0],
                                       verify=lambda who: self.arrived.get(who),
                                       wanted=lambda who: self.want.get(who))
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
        """Gesammelt angewandt wird über holdover.reload_or_defer (Standard-gate)."""
        gated = []

        class FakeTest:
            def running(self):
                return False

            def reload_or_defer(self, trigger):
                gated.append(trigger)
                return trigger()

        coord = restartctl.Coordinator(path=lambda: self.file, wall=lambda: self.now[0],
                                       emit=lambda *a: self.events.append(a), started=lambda: None,
                                       verify=lambda who: None)
        coord.configure(chronyd=lambda: self.fire("chronyd"))
        with mock.patch.object(holdover, "TEST", FakeTest()):
            coord.request("gps_bound")
            self.now[0] += restartctl.COLLECT_SECONDS + 1
            self.assertEqual(coord.tick()["decision"], "applied")
        self.assertEqual(len(gated), 1)
        self.assertEqual(len(self.fired), 1)
        self.assertEqual(coord.status()["auto_24h"], 1)


class HoldoverTest(Harness):
    """Läuft ein Holdover-Test, wird nichts neu gestartet, nichts gezählt und nichts als „neu gestartet“ gemeldet."""

    def test_running_test_holds_change_without_counting(self):
        self.coord.request("gps_bound")
        self.busy[0] = True
        results = self.advance(restartctl.COLLECT_SECONDS + 600)
        self.assertEqual([r["decision"] for r in results], ["deferred"] * len(results))
        self.assertEqual(self.fired, [])
        self.assertEqual(self.gated, [])
        status = self.coord.status()
        self.assertEqual((status["auto_24h"], status["state"]), (0, "holdover"))
        self.assertEqual(self.coord.waiting("gps_bound")["state"], "holdover")
        self.assertEqual(len(self.events), 1)                       # ein Ereignis je Wartezeit
        self.assertIn("zurückgestellt: Holdover-Test läuft", self.titles()[0])
        self.assertEqual(self.events[0][3]["decision"], "deferred")
        self.assertFalse(any("neu gestartet" in t for t in self.titles()))
        # Test vorbei: kurz warten (ein Neustart nach dem Test nähme die Änderung mit), dann eigener Neustart.
        self.busy[0] = False
        self.advance(restartctl.COLLECT_SECONDS - 20)
        self.assertEqual(self.fired, [])
        self.advance(40)
        self.assertEqual(len(self.fired), 1)
        self.assertEqual(self.coord.status()["auto_24h"], 1)
        self.assertIn("neu gestartet", self.titles()[-1])

    def test_restart_after_test_takes_change_along(self):
        self.coord.request("autocal")
        self.busy[0] = True
        self.advance(restartctl.COLLECT_SECONDS + 600)
        self.busy[0] = False
        self.started[0] = self.now[0] + 20                          # holdover startet nach dem Test neu
        self.advance(restartctl.COLLECT_SECONDS + 30)
        self.assertEqual(self.fired, [])
        self.assertEqual(self.events[-1][3]["decision"], "taken_along")
        self.assertEqual(self.coord.status()["auto_24h"], 0)

    def test_gate_that_only_defers_is_not_a_restart(self):
        """Beginnt der Test genau beim Anwenden, merkt reload_or_defer nur vor (True ohne Auslöser)."""
        def gate(trigger):
            self.busy[0] = True                                     # Test hat gerade begonnen
            return True
        coord = restartctl.Coordinator(path=lambda: self.file, wall=lambda: self.now[0],
                                       emit=lambda *a: self.events.append(a), gate=gate,
                                       started=lambda: None, busy=lambda: self.busy[0], verify=lambda who: None)
        coord.configure(chronyd=lambda: self.fire("chronyd"))
        coord.request("gps_bound")
        self.now[0] += restartctl.COLLECT_SECONDS + 1
        result = coord.tick()
        self.assertEqual(result, {"decision": "deferred", "who": ["gps_bound"]})
        self.assertEqual(self.fired, [])
        self.assertEqual(coord.status()["auto_24h"], 0)
        self.assertEqual(len(self.events), 1)
        self.assertIn("zurückgestellt", self.events[0][2])
        self.assertNotIn("neu gestartet", self.events[0][2])


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

    def test_later_request_is_not_taken_along_by_earlier_restart(self):
        """Verglichen wird mit der LETZTEN Anforderung: Eine zweite Automatik, die erst nach der
        Konfigurationserzeugung eines fremden Neustarts dazukam, ist nicht mitgenommen."""
        self.coord.request("autocal")
        self.now[0] += 90
        self.coord.request("gps_bound")
        self.started[0] = self.now[0] + 5                            # fremder Neustart endet 5 s später
        self.now[0] += 10
        self.assertEqual(self.coord.tick()["decision"], "collect")
        results = self.advance(restartctl.COLLECT_SECONDS)
        self.assertEqual([r["decision"] for r in results], ["applied"])
        self.assertEqual(results[0]["who"], ["autocal", "gps_bound"])
        self.assertEqual(len(self.fired), 1)

    def test_take_along_checks_running_config(self):
        """Hat der fremde Neustart seine Konfiguration vor der Änderung erzeugt (langes Beenden der Dienste),
        steht sie nicht in chrony.conf: Die Anforderung bleibt, es folgt ein eigener Neustart."""
        self.coord.request("autocal")
        self.coord.request("gps_bound")
        self.arrived.update(autocal=False, gps_bound=True)
        self.now[0] += restartctl.TAKE_ALONG_MARGIN + 5
        self.started[0] = self.now[0]
        self.coord.tick()
        decisions = [e[3]["decision"] for e in self.events]
        self.assertEqual(decisions, ["taken_along", "not_taken_along"])
        self.assertEqual(self.events[0][3]["who"], ["gps_bound"])
        self.assertEqual(self.events[1][3]["who"], ["autocal"])
        self.assertEqual(self.coord.status()["pending_ids"], ["autocal"])
        results = self.advance(restartctl.COLLECT_SECONDS)
        self.assertEqual([(r["decision"], r["who"]) for r in results], [("applied", ["autocal"])])
        self.assertEqual(len(self.events), 3)                       # „nicht übernommen“ nur einmal
        self.assertEqual(self.coord.status()["auto_24h"], 1)

    def test_unknown_config_counts_as_taken_along(self):
        self.arrived["autocal"] = None                                # nicht prüfbar (ohne GPS, kein chrony.conf)
        self.coord.request("autocal")
        self.now[0] += restartctl.TAKE_ALONG_MARGIN + 5
        self.started[0] = self.now[0]
        self.assertEqual(self.coord.tick()["decision"], "taken_along")

    def test_rollback_with_restart_is_not_reported_as_taken_along(self):
        """„Rückgängig“ (bzw. Sicherung zurückspielen) startet chronyd sofort neu. Danach stimmt die laufende
        chrony.conf mit den Einstellungen überein – die Automatik-Änderung ist aber gerade nicht aktiv."""
        self.want["autocal"] = 0.120
        self.coord.request("autocal")
        self.want["autocal"] = 0.100                                # zurückgenommen
        self.arrived["autocal"] = True                              # Einstellungen == chrony.conf
        self.now[0] += restartctl.TAKE_ALONG_MARGIN + 5
        self.started[0] = self.now[0]                               # sofortiger Neustart der Rücknahme
        self.assertEqual(self.coord.tick()["decision"], "superseded")
        self.assertEqual([e[3]["decision"] for e in self.events], ["superseded"])
        self.assertNotIn("übernommen", " ".join(self.titles()))
        self.assertIn("verworfen", self.titles()[0])
        self.assertEqual(self.fired, [])
        self.assertEqual(self.coord.status()["pending_ids"], [])
        self.assertIsNone(self.coord.waiting("autocal"))

    def test_superseded_part_dropped_rest_taken_along(self):
        self.want.update(autocal=0.12, gps_bound=0.05)
        self.coord.request("autocal")
        self.coord.request("gps_bound", grow=True)
        self.want["gps_bound"] = 0.2                                # Sicherung brachte eine andere Schranke
        self.now[0] += restartctl.TAKE_ALONG_MARGIN + 5
        self.started[0] = self.now[0]
        self.assertEqual(self.coord.tick(), {"decision": "taken_along", "who": ["autocal"]})
        self.assertEqual([(e[3]["decision"], e[3]["who"]) for e in self.events],
                         [("superseded", ["gps_bound"]), ("taken_along", ["autocal"])])

    def test_superseded_without_restart_needs_no_own_restart(self):
        self.want["gps_bound"] = 0.05
        self.coord.request("gps_bound")
        self.want["gps_bound"] = 0.04
        self.advance(restartctl.COLLECT_SECONDS + 30)
        self.assertEqual(self.fired, [])
        self.assertEqual([e[3]["decision"] for e in self.events], ["superseded"])

    def test_same_value_and_new_request_still_apply(self):
        self.want["autocal"] = 0.12
        self.coord.request("autocal")
        self.want["autocal"] = 0.13
        self.coord.request("autocal")                               # neue Anforderung: neuer Wert gilt
        self.advance(restartctl.COLLECT_SECONDS + 30)
        self.assertEqual(len(self.fired), 1)
        with open(self.file, encoding="utf-8") as handle:
            self.assertIsNone(json.load(handle)["pending"])

    def test_requested_value_survives_reload(self):
        self.want["autocal"] = 0.12
        self.coord.request("autocal")
        with open(self.file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["pending"]["want"], {"autocal": 0.12})
        self.coord = self.make()
        self.want["autocal"] = 0.0
        self.advance(restartctl.COLLECT_SECONDS + 30)
        self.assertEqual(self.fired, [])

    def test_unknown_value_keeps_old_behaviour(self):
        self.coord.request("autocal")                               # Wert nicht bestimmbar (z. B. GPS aus)
        self.want["autocal"] = 0.5
        self.advance(restartctl.COLLECT_SECONDS + 30)
        self.assertEqual(len(self.fired), 1)

    def test_old_restart_is_ignored(self):
        self.started[0] = T0 - 100
        self.coord.request("autocal")
        self.advance(restartctl.COLLECT_SECONDS + 10)
        self.assertEqual(len(self.fired), 1)


class GrowTest(Harness):
    """Eine größere GPS-Fehlerschranke (vorsichtigere Richtung) hat Vorrang vor der Tagesgrenze."""

    def fill(self):
        for _ in range(restartctl.MAX_PER_DAY):
            self.coord.request("autocal")
            self.advance(H)
        self.assertEqual(len(self.fired), restartctl.MAX_PER_DAY)

    def test_growing_bound_passes_limit_shrinking_waits(self):
        self.fill()
        self.coord.request("gps_bound")                              # kleiner: wartet
        results = self.advance(restartctl.COLLECT_SECONDS + 10)
        self.assertEqual([r["decision"] for r in results], ["limit"])
        self.coord.request("gps_bound", grow=True)                   # größer: sofort neu bewertet
        results = self.advance(10)
        self.assertEqual([r["decision"] for r in results], ["applied"])
        self.assertEqual(len(self.fired), restartctl.MAX_PER_DAY + 1)
        self.assertIn("Vorrang vor der Tagesgrenze", self.titles()[-1])
        self.assertTrue(self.events[-1][3]["grow"])

    def test_reserve_is_bounded(self):
        self.fill()
        for _ in range(restartctl.GROW_RESERVE):
            self.coord.trigger_for("gps_bound", grow=True)()
            self.advance(H)
        self.assertEqual(len(self.fired), restartctl.MAX_PER_DAY + restartctl.GROW_RESERVE)
        self.coord.request("gps_bound", grow=True)
        results = self.advance(restartctl.COLLECT_SECONDS + 10)
        self.assertEqual([r["decision"] for r in results], ["limit"])
        free_at = results[0]["free_at"]
        self.assertEqual(free_at, self.fired[0][0] + DAY)            # der älteste fällt heraus
        for start in range(int(T0), int(T0 + 3 * DAY), 600):        # in keinem 24-h-Fenster mehr als erlaubt
            inside = [t for t, _s in self.fired if start <= t < start + DAY]
            self.assertLessEqual(len(inside), restartctl.MAX_PER_DAY + restartctl.GROW_RESERVE)

    def test_normal_request_counts_extra_restarts(self):
        """Nach Plätzen aus der Reserve wartet eine normale Änderung, bis wieder weniger als die Grenze in 24 h liegen."""
        self.fill()
        self.coord.request("gps_bound", grow=True)
        self.advance(H)
        self.coord.request("autocal")
        results = self.advance(restartctl.COLLECT_SECONDS + 10)
        self.assertEqual(results[0]["decision"], "limit")
        self.assertEqual(results[0]["free_at"], self.fired[1][0] + DAY)   # 5 in 24 h: erst wenn zwei herausfallen


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
        gpsquality._DEPS.update(history=None, trigger_reload=None, emit=None, net_distance=None, auto_reload=None,
                                auto_reload_grow=None, restart_wait=None)
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

    def test_default_wanted_reads_settings(self):
        """Der gemerkte Wert ist der gespeicherte Offset bzw. die Fehlerschranke, die chrony.conf bekäme."""
        self.assertIsNone(restartctl._default_wanted("autocal"))      # ohne GPS: nicht prüfbar
        with mock.patch.object(settings, "values", return_value={"gps_enable": True, "gps_offset": 0.125}):
            self.assertEqual(restartctl._default_wanted("autocal"), 0.125)
            with mock.patch.object(gpsquality, "refclock_values", return_value={"delay": 0.04}):
                self.assertEqual(restartctl._default_wanted("gps_bound"), 0.04)
            with mock.patch.object(gpsquality, "refclock_values", side_effect=ValueError):
                self.assertIsNone(restartctl._default_wanted("gps_bound"))
            self.assertIsNone(restartctl._default_wanted("irgendwas"))

    def test_without_auto_reload_old_behaviour(self):
        from test_gpsquality import cfg as gq_cfg, vk162_samples
        gpsquality.configure(trigger_reload=lambda: self.direct.append(1) or True, emit=lambda *a, **k: None)
        samples = vk162_samples(loops=5)
        self.assertTrue(gpsquality.tick(gq_cfg(), samples[-1]["t"] + 1, samples)["apply"])
        self.assertEqual(len(self.direct), 1)

    def test_growing_bound_asks_with_priority(self):
        from test_gpsquality import cfg as gq_cfg, vk162_samples
        grown = []
        gpsquality.configure(trigger_reload=lambda: self.direct.append(1) or True,
                             auto_reload=lambda: self.queued.append(1) or True,
                             auto_reload_grow=lambda: grown.append(1) or True, emit=lambda *a, **k: None)
        samples = vk162_samples(loops=5)
        bigger = gpsquality.unmeasured_delay(gq_cfg()) * 2
        with mock.patch.object(gpsquality, "decide", return_value={"apply": True, "delay": bigger, "reason": "r"}):
            self.assertTrue(gpsquality.tick(gq_cfg(), samples[-1]["t"] + 1, samples)["apply"])
        self.assertEqual((len(grown), len(self.queued), len(self.direct)), (1, 0, 0))
        with mock.patch.object(gpsquality, "decide", return_value={"apply": True, "delay": bigger / 4, "reason": "r"}):
            self.assertTrue(gpsquality.tick(gq_cfg(), samples[-1]["t"] + 2, samples)["apply"])
        self.assertEqual((len(grown), len(self.queued), len(self.direct)), (1, 1, 0))

    def test_bound_waiting_for_restart_is_shown_as_saved(self):
        """GPS-Seite: Solange der Koordinator den Neustart hält, gilt in chronyd die bisherige Schranke."""
        from test_gpsquality import cfg as gq_cfg, vk162_samples
        wait = [None]
        gpsquality.configure(auto_reload=lambda: True, emit=lambda *a, **k: None,
                             restart_wait=lambda who: wait[0] if who == "gps_bound" else None)
        samples = vk162_samples(loops=5)
        cfg = gq_cfg()
        old = gpsquality.unmeasured_delay(cfg)
        conf = os.path.join(self.tmp, "chrony.conf")
        with open(conf, "w", encoding="utf-8") as handle:
            handle.write(f"refclock SHM 0 refid GPS offset 0.05 delay {old} precision 0.1\n")
        self.assertTrue(gpsquality.tick(cfg, samples[-1]["t"] + 1, samples)["apply"])
        new = gpsquality.refclock_values(cfg)["delay"]
        self.assertNotAlmostEqual(new, old)
        with mock.patch.dict(os.environ, {"CHRONY_CONF": conf}):
            self.assertIs(gpsquality.bound_running(cfg), False)
            self.assertEqual(gpsquality.status_hint(cfg)["delay"], new)    # ohne Koordinator wie bisher
            wait[0] = {"state": "limit", "next_try": T0 + 20 * H}
            hint = gpsquality.status_hint(cfg)
            self.assertEqual(hint["delay"], old)
            self.assertEqual(hint["saved"], new)
            self.assertEqual(hint["restart"], {"state": "limit", "next_try": T0 + 20 * H})
            with open(conf, "w", encoding="utf-8") as handle:
                handle.write(f"refclock SHM 0 refid GPS offset 0.05 delay {new} precision 0.1\n")
            self.assertIs(gpsquality.bound_running(cfg), True)
            self.assertNotIn("saved", gpsquality.status_hint(cfg))

    def test_autocal_offset_running(self):
        conf = os.path.join(self.tmp, "chrony.conf")
        with open(conf, "w", encoding="utf-8") as handle:
            handle.write("refclock SHM 0 refid GPS offset 0.05 delay 0.2\n")
        with mock.patch.dict(os.environ, {"CHRONY_CONF": conf}):
            self.assertIs(autocal.offset_running({"gps_offset": 0.05, "gps_refid": "GPS"}), True)
            self.assertIs(autocal.offset_running({"gps_offset": 0.065, "gps_refid": "GPS"}), False)
            self.assertIsNone(autocal.offset_running({"gps_offset": 0.05, "gps_refid": "PPS"}))
            self.assertEqual(autocal.running_conf_value("GPS", "delay"), 0.2)
        with mock.patch.dict(os.environ, {"CHRONY_CONF": os.path.join(self.tmp, "fehlt.conf")}):
            self.assertIsNone(autocal.offset_running({"gps_offset": 0.05}))

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

    @unittest.skipUnless(shutil.which("node"), "node fehlt")
    def test_names_follow_language(self):
        """Die wartenden Automatiken kommen als feste Kennungen (pending_ids) und werden übersetzt."""
        static = json.dumps(str(Path(__file__).resolve().parents[1] / "app" / "static"))
        out = self.run_js(f"""
import {{ readFileSync }} from "node:fs";
globalThis.fetch = async (u) => ({{ ok: true, json: async () => JSON.parse(readFileSync({static} + u.replace("/static", ""), "utf8")) }});
const i18n = await import({mod("i18n.js")});
const ov = await import({mod("pages/overview.js")});
const r = {{ auto_24h: 4, limit: 4, pending: ["GPS-Kalibrierung (Offset)", "GPS-Fehlerschranke"],
  pending_ids: ["autocal", "gps_bound"], state: "limit", next_try: 1783003600 }};
const de = ov.restartsValue(r).getAttribute("title");
const old = ov.restartsValue({{ ...r, pending_ids: undefined }}).getAttribute("title");
const held = text(ov.restartsValue({{ ...r, state: "holdover", next_try: null }}));
if (typeof document.querySelectorAll !== "function") document.querySelectorAll = () => [];
await i18n.setLanguage("en");
console.log(JSON.stringify({{ de, old, held, en: ov.restartsValue(r).getAttribute("title"),
  enHeld: text(ov.restartsValue({{ ...r, state: "holdover", next_try: null }})) }}));
""")
        self.assertEqual(out["de"], "Wartet: GPS-Kalibrierung (Offset), GPS-Fehlerschranke")
        self.assertEqual(out["old"], out["de"])                                  # älterer Server ohne Kennungen
        self.assertEqual(out["en"], "Waiting: GPS calibration (offset), GPS error bound")
        self.assertEqual(out["held"], "4 von 4 in 24 h wartet auf Holdover-Test")
        self.assertEqual(out["enHeld"], "4 of 4 in 24 h waits for holdover test")

    @unittest.skipUnless(shutil.which("node"), "node fehlt")
    def test_gps_delay_cell_shows_saved_bound(self):
        out = self.run_js(f"""
const gps = await import({mod("pages/gps.js")});
const sys = {{ time: 1783000000, utc_offset: 7200 }};
const t = (v) => typeof v === "string" ? v : text(v);
const base = {{ managed: true, source: "measured", delay: 0.04, pps: false }};
console.log(JSON.stringify({{
  plain: t(gps.delayCell({{ gps_bound: base }}, sys)),
  limit: t(gps.delayCell({{ gps_bound: {{ ...base, saved: 0.06, restart: {{ state: "limit", next_try: 1783003600 }} }} }}, sys)),
  soon: t(gps.delayCell({{ gps_bound: {{ ...base, saved: 0.03, restart: {{ state: "collecting", next_try: 1783000120 }} }} }}, sys)),
}}));
""", tz="America/New_York")
        self.assertEqual(out["plain"], "0.04 s (gemessen, ± 20 ms)")
        self.assertIn("0.04 s (bisher", out["limit"])
        self.assertIn("gespeichert: 0.06 s", out["limit"])
        self.assertIn("wird mit dem nächsten Neustart von chronyd aktiv (Tagesgrenze automatischer Neustarts, frei ab 16:46)",
                      out["limit"])
        self.assertIn("(in Kürze)", out["soon"])
        self.assertIn("wartet auf Neustart", out["limit"])            # kurzes Badge, der Satz steht darunter


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
