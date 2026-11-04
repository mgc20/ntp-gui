"""1.5.3: Ein Holdover-Test wird von Automatiken nicht mehr unterbrochen.

Rückmeldung (Diagnosepaket 1.5.1, Pi 4, VK-162 ohne PPS, 5 NTS-Quellen): 6-h-Test mit Netzquellen um
01:06 gestartet; um 05:41 vergrößerte gpsquality die GPS-Fehlerschranke (± 16 → ± 22 ms), startete
dafür chronyd neu – „Holdover-Test abgebrochen (chronyd neu gestartet) … nach 4 h 35 min“. Dazu
stand beim Start „Keine Zeitquelle mehr ausgewählt“ als Warnung im Protokoll, obwohl der Test die
Quellen absichtlich abgewählt hatte.

Hier mit eingespielten Uhren nachgestellt: Schranke will nach 4,5 h wachsen → zurückgestellt (ein
Ereignis, kein Neustart), Test läuft die 6 h zu Ende, danach wird die Schranke sofort übernommen.
Und: keine Warnung beim Start des Tests.
"""

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
import events  # noqa: E402
import gpsquality  # noqa: E402
import holdover  # noqa: E402
import notify  # noqa: E402
import selectctl  # noqa: E402
import settings  # noqa: E402
import statewatch  # noqa: E402
import store  # noqa: E402
from test_gnssguard import FakeChrony  # noqa: E402
from test_gpsquality import cfg as gq_cfg, vk162_samples  # noqa: E402

H = 3600.0


class Case(unittest.TestCase):
    """Eigene Datenbank, chronyd-Attrappe mit GPS + 5 NTS-Quellen, holdover.TEST mit eigener Uhr."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        self.chrony = FakeChrony(gps=True, pps=False, network=5)
        self.addCleanup(selectctl.set_port(self.chrony))
        selectctl.reset_for_tests()
        self.events, self.reloads, self.holds = [], [], []
        self.wall = [1_800_000_000.0]
        self.test = holdover.HoldoverTest(emit=lambda *a: self.events.append(a), wall=lambda: self.wall[0],
                                          hold=self.holds.append)
        patcher = mock.patch.object(holdover, "TEST", self.test)
        patcher.start()
        self.addCleanup(patcher.stop)
        gpsquality.configure(trigger_reload=lambda: self.reloads.append(self.wall[0]) or True,
                             emit=lambda *a, **k: self.events.append(a))
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        gpsquality._DEPS.update(history=None, trigger_reload=None, emit=None, net_distance=None)
        selectctl.reset_for_tests()
        holdover._READY["for"] = None
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, hours=6, limit_ms=80):
        return self.test.start({"action": "start", "hours": hours, "include_network": True, "limit_ms": limit_ms})

    def run_until(self, wall_end, step=60.0):
        while self.wall[0] < wall_end:
            self.wall[0] = min(wall_end, self.wall[0] + step)
            result = self.test.tick({}, self.chrony.select())
            if result:
                return result
        return None

    def titles(self):
        return [e[2] for e in self.events]


class BoundWaitsForHoldoverTest(Case):
    def test_timeline_bound_deferred_then_applied_after_six_hours(self):
        samples = vk162_samples(loops=5)          # ~6 h VK-162 drinnen: Schranke will vom Standard weg
        gq_now = samples[-1]["t"] + 1
        self.wall[0] = gq_now - 4.5 * H           # Test beginnt 4,5 h vor dem Wunsch der Schranke
        self.start(hours=6, limit_ms=80)
        self.assertTrue(self.holds and self.holds[-1] is not None)   # Supervisor-Sperre gesetzt
        self.assertIsNone(self.run_until(self.wall[0] + 4.5 * H))

        # 4,5 h: gpsquality will die Schranke ändern → zurückgestellt, kein Neustart, nichts übernommen.
        decision = gpsquality.tick(gq_cfg(), gq_now, samples)
        self.assertFalse(decision["apply"], decision)
        self.assertEqual(decision["deferred"], "holdover")
        self.assertIn("Zurückgestellt bis zum Ende des Holdover-Tests", decision["reason"])
        self.assertEqual(self.reloads, [])
        self.assertIsNone(gpsquality.read_applied())
        deferred = [t for t in self.titles() if "zurückgestellt bis zum Ende des Holdover-Tests" in t]
        self.assertEqual(len(deferred), 1)
        self.assertTrue(deferred[0].startswith("GPS-Fehlerschranke ± 100 ms → ± "), deferred[0])
        # Eine Stunde später derselbe Wunsch: wieder zurückgestellt, aber kein zweites Ereignis.
        self.assertIsNone(self.run_until(self.wall[0] + 1 * H))
        self.assertFalse(gpsquality.tick(gq_cfg(), gq_now + H, samples)["apply"])
        self.assertEqual(len([t for t in self.titles() if "zurückgestellt" in t]), 1)
        self.assertTrue(self.test.status()["run"]["deferred"])
        self.assertTrue(self.test.status()["active"])

        # Test läuft die vollen 6 h – nicht abgebrochen.
        result = self.run_until(self.wall[0] + 1 * H)
        self.assertIsNotNone(result)
        self.assertEqual(result["outcome"], "done")
        self.assertEqual(result["duration_s"], 6 * 3600)
        self.assertIsNone(self.holds[-1])                              # Supervisor-Sperre aufgehoben
        self.assertEqual(self.chrony.effective, set())
        self.assertIn("Zurückgestellt, wird jetzt erneut geprüft: GPS-Fehlerschranke", self.events_of("source")[-1][2])

        # Nächster Durchgang der Messschleife: gpsquality prüft sofort (nicht erst nach einer Stunde).
        calls = []
        with mock.patch.object(gpsquality, "tick", lambda c, *a, **k: calls.append(c) or {"apply": True}), \
                mock.patch.dict(gpsquality._LAST_TICK, {"mono": 100.0}):
            gpsquality.maybe_tick(gq_cfg, clock=lambda: 160.0)     # 1 min nach dem letzten Durchgang
            gpsquality.maybe_tick(gq_cfg, clock=lambda: 220.0)     # nur einmal vorgezogen
        self.assertEqual(len(calls), 1)
        decision = gpsquality.tick(gq_cfg(), gq_now + 1.5 * H, samples)
        self.assertTrue(decision["apply"], decision)
        self.assertEqual(len(self.reloads), 1)
        self.assertIsNotNone(gpsquality.read_applied())

    def events_of(self, kind):
        return [e for e in self.events if e[0] == kind]

    def test_without_holdover_bound_applies_immediately(self):
        samples = vk162_samples(loops=5)
        self.assertTrue(gpsquality.tick(gq_cfg(), samples[-1]["t"] + 1, samples)["apply"])
        self.assertEqual(len(self.reloads), 1)

    def test_user_abort_also_resumes(self):
        self.start(hours=2)
        self.assertTrue(holdover.defer("gps_bound", "GPS-Fehlerschranke ± 16 ms → ± 22 ms"))
        self.assertFalse(holdover.resume("gps_bound"))           # läuft noch
        self.test.abort(self.chrony.select())
        self.assertTrue(holdover.resume("gps_bound"))
        self.assertFalse(holdover.resume("gps_bound"))           # genau einmal
        self.assertFalse(holdover.defer("gps_bound", "x"))       # kein Test → nicht zurückstellen

    def test_deferral_survives_dashboard_restart(self):
        self.start(hours=2)
        holdover.defer("autocal", "GPS-Offset 0.005 s → 0.0542 s")
        fresh = holdover.HoldoverTest(emit=lambda *a: self.events.append(a), wall=lambda: self.wall[0],
                                      hold=self.holds.append)
        with mock.patch.object(holdover, "TEST", fresh):
            self.assertTrue(holdover.defer("autocal", "GPS-Offset 0.005 s → 0.0542 s"))
            self.assertEqual(len([t for t in self.titles() if "zurückgestellt" in t]), 1)
            self.wall[0] += 2 * H + 60
            fresh.tick({}, self.chrony.select())
            self.assertTrue(holdover.resume("autocal"))


class ReviewFindingsTest(Case):
    """Prüfbefunde zu 1.5.3: Teststart-Wettlauf, Frist bei hängendem chronyd, Tests direkt hintereinander."""

    def test_start_refused_while_reload_requested_or_running(self):
        self.test.busy = lambda: "Ein Neustart der Zeitdienste ist angefordert"
        with self.assertRaises(holdover.HoldoverError) as ctx:
            self.start(hours=2)
        self.assertTrue(ctx.exception.conflict)
        self.assertIn("in ein paar Sekunden", str(ctx.exception))
        self.assertFalse(self.test.running())
        self.assertIsNone(self.holds[-1])              # Sperre wieder weg
        self.assertEqual(self.chrony.effective, set())   # nichts abgewählt
        self.test.busy = lambda: ""
        self.start(hours=2)
        self.assertTrue(self.test.running())

    def test_reload_busy_reads_request_and_status(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": tmp}):
            self.assertEqual(holdover.reload_busy(1000.0), "")
            open(os.path.join(tmp, "reload.request"), "w").close()
            self.assertIn("angefordert", holdover.reload_busy(1000.0))
            os.remove(os.path.join(tmp, "reload.request"))
            with open(os.path.join(tmp, "reload.json"), "w", encoding="utf-8") as handle:
                handle.write('{"state": "running", "message": "x", "time": 990}')
            self.assertIn("starten gerade neu", holdover.reload_busy(1000.0))
            self.assertEqual(holdover.reload_busy(990.0 + holdover.RELOAD_RUNNING_MAX + 1), "")   # veraltet
            with open(os.path.join(tmp, "reload.json"), "w", encoding="utf-8") as handle:
                handle.write('{"state": "done", "message": "x", "time": 990}')
            self.assertEqual(holdover.reload_busy(1000.0), "")

    def test_automatic_reload_right_after_start_waits_for_end(self):
        """Wettlauf: gpsquality fragt defer() (noch kein Test), der Test startet, dann käme der Neustart –
        er wird unter der Sperre noch einmal geprüft und folgt erst nach dem Ende."""
        fired = []
        holdover.configure(trigger_reload=lambda: fired.append(self.wall[0]) or True)
        self.addCleanup(holdover.configure, None)
        samples = vk162_samples(loops=5)

        def defer_then_start(what):
            self.start(hours=2)          # genau zwischen Prüfung und Neustart
            return False

        with mock.patch.object(gpsquality, "_holdover_defers", defer_then_start):
            decision = gpsquality.tick(gq_cfg(), samples[-1]["t"] + 1, samples)
        self.assertTrue(decision["apply"])
        self.assertTrue(decision["reload_triggered"])          # vorgemerkt
        self.assertEqual(self.reloads, [])                     # aber jetzt kein Neustart
        self.assertTrue(self.test.running())
        self.assertEqual(len([t for t in self.titles() if t.startswith("Neustart der Zeitdienste – zurückgestellt")]), 1)
        result = self.run_until(self.wall[0] + 2 * H + 60)
        self.assertEqual(result["outcome"], "done")
        self.assertEqual(len(fired), 1)                        # nach dem Ende genau einmal
        self.assertIn("Ein zurückgestellter Neustart der Zeitdienste folgt jetzt", self.events_of("source")[-1][2])

    def events_of(self, kind):
        return [e for e in self.events if e[0] == kind]

    def test_deadline_applies_while_chronyd_hangs(self):
        self.start(hours=1)
        self.wall[0] += 3 * H
        result = self.test.tick({}, {})                         # chronyd antwortet nicht
        self.assertIsNotNone(result)
        self.assertEqual(result["outcome"], "done")
        self.assertFalse(self.test.running())
        self.assertIsNone(self.holds[-1])
        self.assertTrue(self.test.state().get("release_pending"))
        self.test.tick({}, self.chrony.select())                # chronyd wieder da → freigegeben
        self.assertEqual(self.chrony.effective, set())

    def test_hold_never_much_longer_than_deadline(self):
        import time as _time
        self.start(hours=1)
        self.wall[0] += 1 * H - 10                              # 10 s vor der Frist
        self.test.tick({}, None)
        self.assertLessEqual(self.holds[-1], _time.time() + 10 + holdover.HOLD_TTL + 1)
        self.wall[0] += 3 * H                                   # weit danach (chronyd hängt, noch ein Durchgang)
        self.test._refresh_hold()
        self.assertLessEqual(self.holds[-1], _time.time() + holdover.HOLD_TTL + 1)

    def test_back_to_back_tests_keep_deferred_changes(self):
        self.start(hours=1)
        holdover.defer("gps_bound", "GPS-Fehlerschranke ± 16 ms → ± 22 ms")
        self.test.abort(self.chrony.select())
        with self.assertRaises(holdover.HoldoverError):          # sofort danach: Pause
            self.start(hours=1)
        self.wall[0] += holdover.RESTART_PAUSE + 1
        with self.assertRaises(holdover.HoldoverError) as ctx:   # Zurückgestelltes noch nicht geprüft
            self.start(hours=1)
        self.assertIn("nachgeholt", str(ctx.exception))
        self.wall[0] += holdover.RESUME_WAIT
        self.start(hours=1)                                      # Automatik aus? Dann übernehmen
        self.assertFalse(holdover.resume("gps_bound"))           # nicht während des Tests
        self.test.abort(self.chrony.select())
        self.assertTrue(holdover.resume("gps_bound"))            # nach dem zweiten Test

    def test_unconfirmed_state_after_container_restart_defers_quietly(self):
        self.start(hours=2)
        self.chrony.restart()                                    # Container neu: chronyd vergaß die Abwahl
        fresh = holdover.HoldoverTest(emit=lambda *a: self.events.append(a), wall=lambda: self.wall[0],
                                      hold=self.holds.append)
        with mock.patch.object(holdover, "TEST", fresh):
            self.assertTrue(holdover.defer("gps_bound", "GPS-Fehlerschranke ± 16 ms → ± 22 ms"))
            self.assertEqual([t for t in self.titles() if "zurückgestellt" in t], [])
            self.assertEqual(fresh.tick({}, self.chrony.select())["outcome"], "restart")
            self.assertTrue(holdover.resume("gps_bound"))
            self.assertIn("wird jetzt erneut geprüft", self.events_of("source")[-1][2])


class AutocalWaitsForHoldoverTest(unittest.TestCase):
    def setUp(self):
        import test_autocal
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.file = os.path.join(self.tmp, "autocal.json")
        self.h = test_autocal.Harness()
        self.running = True
        self.deferred = []
        env = mock.patch.dict(os.environ, {"WEB_READONLY": ""})
        env.start()
        self.addCleanup(env.stop)

    def tick(self, now):
        deps = self.h.deps()
        deps["holdover_defer"] = lambda what: self.running and (self.deferred.append(what) or True)
        return autocal.tick(self.h.cfg, now, deps=deps, file=self.file)

    def test_offset_change_waits_until_test_ends(self):
        now = 1_800_000_000.0
        self.tick(now)
        d = self.tick(now + 7 * H)
        self.assertEqual(d["action"], "none")
        self.assertEqual(d["deferred"], "holdover")
        self.assertEqual(self.h.saved, [])
        self.assertEqual(self.h.reloads, 0)
        self.assertEqual(self.deferred, ["GPS-Offset 0.05 s → 0.055 s"])
        self.running = False
        d = self.tick(now + 8 * H)
        self.assertEqual(d["action"], "apply")
        self.assertEqual(self.h.saved, [{"gps_offset": 0.055}])
        self.assertEqual(self.h.reloads, 1)

    def test_maybe_tick_runs_right_after_test(self):
        now = 1_800_000_000.0
        calls = []
        resumed = iter([True, False])
        with mock.patch.object(autocal, "tick", lambda c, n: calls.append(n) or {}), \
                mock.patch.dict(autocal._LAST_TICK, {"t": now}), \
                mock.patch.dict(autocal._DEPS, {"holdover_resume": lambda: next(resumed)}):
            autocal.maybe_tick({}, now + 60)
            autocal.maybe_tick({}, now + 120)
        self.assertEqual(calls, [now + 60])


class NoWarningFromOwnTestTest(Case):
    def setUp(self):
        super().setUp()
        events.add_filter(holdover.event_filter)
        self.addCleanup(events.remove_filter, holdover.event_filter)
        self.watch = statewatch.StateWatcher(events.emit)

    def sample(self, selected):
        rows = {"GPS": {"s": "-", "k": "#"}}
        for i in range(5):
            name = f"192.0.2.{i + 1}"
            rows[name] = {"s": "*" if name == selected else ("?" if selected is None else "+"), "k": "^"}
        self.watch.sample({"t": self.wall[0], "offset": 0.0, "sources": rows})

    def stored(self):
        return list(reversed(events.query(limit=50)))

    def test_no_warn_or_notification_at_start_and_end(self):
        for _ in range(3):
            self.sample("192.0.2.1")
        self.start(hours=6)
        for _ in range(3):                         # chrony hat alles abgewählt
            self.sample(None)
        no_source = [e for e in self.stored() if e["title"].startswith("Keine Zeitquelle")]
        self.assertEqual(len(no_source), 1)
        self.assertEqual(no_source[0]["level"], "info")
        self.assertTrue(no_source[0]["title"].endswith("(Holdover-Test)"))
        self.assertIs(no_source[0]["data"]["notify"], False)
        self.assertEqual(no_source[0]["data"]["original_level"], "warn")
        self.assertEqual([e for e in self.stored() if e["level"] != "info"], [])
        # Auch ein Kanal, der alles ab „info“ meldet, bekommt nichts.
        router = notify.ChannelRouter({"min_level": "info", "debounce_min": 0}, clock=lambda: 1000.0,
                                      wall=lambda: self.wall[0])
        self.assertEqual(router.offer(no_source[0]), [])
        self.assertTrue(router.offer(dict(no_source[0], data={}, level="warn")))   # Gegenprobe ohne Vermerk
        # Test zu Ende, chrony wählt kurz danach wieder aus: ebenfalls still.
        self.assertEqual(self.run_until(self.wall[0] + 6 * H + 60, step=300.0)["outcome"], "done")
        self.wall[0] += 120
        for _ in range(3):
            self.sample("192.0.2.2")
        back = [e for e in self.stored() if e["title"].startswith("Zeitquelle ausgewählt")]
        self.assertEqual(len(back), 1)
        self.assertIs(back[0]["data"]["notify"], False)
        # Lange nach dem Test ist „keine Quelle“ wieder eine echte Warnung.
        self.wall[0] += holdover.EVENT_GRACE + 60
        for _ in range(3):
            self.sample(None)
        later = [e for e in self.stored() if e["title"] == "Keine Zeitquelle mehr ausgewählt"]
        self.assertEqual(len(later), 1)
        self.assertEqual(later[0]["level"], "warn")

    def test_filter_leaves_real_problems_alone(self):
        self.start(hours=6)
        f = holdover.event_filter
        self.assertEqual(f("source", "crit", "Schleife: pool.ntp.org", {"state": "loop"})[0], "crit")
        self.assertEqual(f("gps", "warn", "GPS-Fix verloren", {})[0], "warn")
        self.assertEqual(f("service", "warn", "chronyd nicht erreichbar", {})[0], "warn")
        level, title, data = f("gps", "warn", "GPS-Sperre ausgelassen: keine andere Zeitquelle",
                               {"subject": "gps-sperre-ausgelassen"})
        self.assertEqual((level, data["notify"], data["holdover_test"]), ("info", False, True))
        level, title, data = f("source", "info", "Schleife bei x beendet – die Quelle antwortet derzeit nicht",
                               {"state": "resolved"})
        self.assertEqual((level, data["notify"]), ("info", False))
        own = {"subject": "holdover", "notify": False}
        self.assertEqual(f("source", "warn", "Holdover-Test abgebrochen (Grenze)", own),
                         ("warn", "Holdover-Test abgebrochen (Grenze)", own))

    def test_gps_only_test_keeps_real_network_loss(self):
        """Prüfbefund: Test nur ohne GPS – die Netzquellen stellen weiter die Uhr. Fallen sie aus, ist
        „keine Zeitquelle“ ein echter Ausfall und bleibt eine Warnung mit Meldung."""
        self.test.start({"action": "start", "hours": 2, "include_network": False, "limit_ms": 80})
        f = holdover.event_filter
        self.assertEqual(f("source", "warn", "Keine Zeitquelle mehr ausgewählt", {"from": "192.0.2.1"})[0], "warn")
        self.assertEqual(f("source", "warn", "Keine Zeitquelle mehr ausgewählt", {"from": "GPS"})[0], "warn")
        level, _t, data = f("source", "info", "Zeitquelle gewechselt: GPS → 192.0.2.1", {"from": "GPS", "to": "192.0.2.1"})
        self.assertEqual((level, data["notify"]), ("info", False))
        level, _t, data = f("source", "info", "Zeitquelle gewechselt: 192.0.2.1 → 192.0.2.2",
                            {"from": "192.0.2.1", "to": "192.0.2.2"})
        self.assertNotIn("holdover_test", data)
        self.assertEqual(f("source", "info", "Schleife bei x beendet – die Quelle antwortet derzeit nicht",
                           {"state": "resolved", "address": "192.0.2.9"})[2].get("notify"), None)
        # Nach dem Test (Nachlauf) gilt dasselbe.
        self.test.abort(self.chrony.select())
        self.assertEqual(f("source", "warn", "Keine Zeitquelle mehr ausgewählt", {"from": "192.0.2.1"})[0], "warn")
        self.assertEqual(f("source", "info", "Zeitquelle ausgewählt: GPS", {"to": "GPS"})[2]["notify"], False)

    def test_skip_note_only_while_test_runs(self):
        f = holdover.event_filter
        skip = ("gps", "warn", "GPS-Sperre ausgelassen: keine andere Zeitquelle", {"subject": "gps-sperre-ausgelassen"})
        self.start(hours=1)
        self.assertEqual(f(*skip)[0], "info")
        self.test.abort(self.chrony.select())
        self.assertEqual(f(*skip)[0], "warn")                   # kein 15-min-Nachlauf

    def test_without_test_nothing_changes(self):
        self.assertEqual(holdover.event_filter("source", "warn", "Keine Zeitquelle mehr ausgewählt", {}),
                         ("warn", "Keine Zeitquelle mehr ausgewählt", {}))


class WiringTest(unittest.TestCase):
    def test_server_registers_filter_and_status_flag(self):
        text = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(encoding="utf-8")
        self.assertIn("events.add_filter(holdover.event_filter)", text)
        self.assertIn("holdover.configure(trigger_reload=trigger_reload)", text)
        pages = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "pages"
        for name in ("gps.js", "gpsquality.js"):
            self.assertIn("holdoverNote(ctx)", (pages / name).read_text(encoding="utf-8"), name)
        self.assertIn('status["holdover_active"]', text)
        js = (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "pages" / "settings.js").read_text(
            encoding="utf-8")
        self.assertIn("holdover_active", js)
        self.assertIn("bricht den Test ab", js)


class HoldFileTest(unittest.TestCase):
    def test_write_and_remove(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": tmp}):
            holdover._write_hold(1_900_000_000.7)
            with open(os.path.join(tmp, "reload.hold"), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "1900000000\n")
            holdover._write_hold(None)
            self.assertFalse(os.path.exists(os.path.join(tmp, "reload.hold")))
            holdover._write_hold(None)                      # fehlt schon: kein Fehler


if __name__ == "__main__":
    unittest.main()
