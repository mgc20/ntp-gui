"""Zustand der Benachrichtigungen, des Client-Alarms und des Zeitwächter-Pings über einen Neustart.

Der Neustart wird simuliert: notify wird neu geladen (importlib.reload) bzw. neue Objekte lesen dieselbe
Datenbank. Grenzfälle: Uhr vor/nach dem Neustart, sehr alter Zustand, kaputte Werte, fehlende Tabelle,
Wiederherstellung einer Sicherung.
"""

import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import backup  # noqa: E402
import events  # noqa: E402
import heartbeat  # noqa: E402
import notify  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import statewatch  # noqa: E402
import store  # noqa: E402
from test_backup import BackupTestBase  # noqa: E402

DAY = 86400.0


class _Data(unittest.TestCase):
    """Eigenes Datenverzeichnis je Test; Namensliste für den Leck-Filter fest."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="neustart-")
        store.close_all()
        self.patches = [mock.patch.object(settings, "DATA_DIR", self.tmp),
                        mock.patch.object(settings, "SETTINGS_FILE", os.path.join(self.tmp, "settings.json"))]
        for patch in self.patches:
            patch.start()
        settings._CACHE.update(mtime=None, data=None, error=None)
        notify._reset_for_tests()
        events._STATE["ready_for"] = None
        events._LISTENERS.clear()
        self.clock = dict(events._CLOCK)
        events._CLOCK.update(plausible=None, at=None, noted=False, held=False)

    def tearDown(self):
        notify._reset_for_tests()
        events._LISTENERS.clear()
        events._CLOCK.clear()
        events._CLOCK.update(self.clock)
        store.close_all()
        for patch in reversed(self.patches):
            patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class StampTest(unittest.TestCase):
    def test_fresh_state_is_taken(self):
        raw = notify.stamp({"a": 1}, now=1000.0)
        self.assertEqual(notify.unstamp(raw, now=1000.0 + 3600), ({"a": 1}, "ok"))

    def test_too_old_state_is_dropped(self):
        raw = notify.stamp({"a": 1}, now=1000.0)
        self.assertEqual(notify.unstamp(raw, now=1000.0 + notify.STATE_MAX_AGE + 1), (None, "abgelaufen"))

    def test_clock_ahead_after_restart_drops_state(self):
        """Steht die Uhr nach dem Neustart weit vor, wirkt der Zustand alt: lieber eine Meldung zu viel."""
        raw = notify.stamp({"a": 1}, now=1_800_000_000.0)
        self.assertIsNone(notify.unstamp(raw, now=1_800_000_000.0 + 30 * DAY)[0])

    def test_clock_behind_after_restart_keeps_state(self):
        """Pi ohne RTC: Nach dem Start steht die Uhr hinter der Speicherzeit – Alter unbekannt, Zustand gilt."""
        raw = notify.stamp({"a": 1}, now=1_800_000_000.0)
        self.assertEqual(notify.unstamp(raw, now=1_800_000_000.0 - 3 * DAY)[0], {"a": 1})
        self.assertEqual(notify.unstamp(raw, now=0.0)[0], {"a": 1})

    def test_legacy_format_without_stamp_is_taken(self):
        self.assertEqual(notify.unstamp('{"gps:fix":{"notified":"warn"}}'),
                         ({"gps:fix": {"notified": "warn"}}, "alt"))
        self.assertEqual(notify.unstamp('["192.0.2.1"]'), (["192.0.2.1"], "alt"))

    def test_legacy_format_is_aged_by_its_newest_time(self):
        """Älteres Format: Die jüngste enthaltene Uhrzeit schätzt das Alter – sehr alter Zustand verfällt."""
        now = 1_800_000_000.0
        old = {"gps:fix": {"open_since": now - 90 * DAY, "notified": "warn", "last_sent": now - 90 * DAY},
               "ntp:quelle": {"open_since": None, "notified": None, "last_sent": now - 30 * DAY}}
        self.assertEqual(notify.unstamp(json.dumps(old), now=now), (None, "abgelaufen"))
        recent = dict(old, **{"pps:pps": {"open_since": now - 3600, "notified": "warn", "last_sent": None}})
        self.assertEqual(notify.unstamp(json.dumps(recent), now=now), (recent, "alt"))
        held = dict(old, **{"x:y": {"pending": {"t": now - 60, "kind": "x"}}})
        self.assertEqual(notify.unstamp(json.dumps(held), now=now)[1], "alt")
        # Uhr steht nach dem Start zurück (Pi ohne RTC): Alter unbekannt, Zustand gilt.
        self.assertEqual(notify.unstamp(json.dumps(old), now=now - 120 * DAY)[1], "alt")
        # ohne Zeitangaben (Liste der Client-Alarme, Einträge ohne Zeit): übernommen
        self.assertEqual(notify.unstamp('{"a:b":{"open_since":null,"last_sent":true}}', now=now)[1], "alt")

    def test_channel_state_expires_before_source_state(self):
        """Kanäle verfallen früher als die Quellen (die erst nach dem nächsten Ping neu stempeln)."""
        self.assertLessEqual(notify.ROUTER_STATE_MAX_AGE + notify.STATE_REFRESH + heartbeat.MAX_INTERVAL,
                             notify.STATE_MAX_AGE)
        self.assertGreater(notify.ROUTER_STATE_MAX_AGE, 12 * 3600)

    def test_broken_values(self):
        for raw in ("nicht json", '{"v":2,"saved":"gestern","state":{}}', '{"v":2,"saved":NaN,"state":{}}',
                    '{"v":3,"saved":1,"state":{}}', "[" * 5000):
            with self.subTest(raw=raw[:30]):
                self.assertEqual(notify.unstamp(raw)[0], None)
        self.assertEqual(notify.unstamp(None), (None, "leer"))


class SavedStateTest(_Data):
    def test_writes_only_on_change_or_refresh(self):
        clock = [100.0]
        saved = notify.SavedState("probe", clock=lambda: clock[0], wall=lambda: 5000.0)
        self.assertTrue(saved.save({"x": 1}))
        self.assertFalse(saved.save({"x": 1}))                       # unverändert: nichts schreiben
        self.assertTrue(saved.save({"x": 2}))
        clock[0] += notify.STATE_REFRESH
        self.assertTrue(saved.save({"x": 2}))                        # neu stempeln
        self.assertTrue(saved.save({"x": 2}, restamp=True))          # Herunterfahren
        self.assertEqual(json.loads(notify.meta_get("probe"))["saved"], 5000.0)

    def test_expired_and_broken_entries_are_removed(self):
        notify.meta_set("alt", notify.stamp({"x": 1}, now=time.time() - notify.STATE_MAX_AGE - 60))
        notify.meta_set("kaputt", "{nicht json")
        for key in ("alt", "kaputt"):
            saved = notify.SavedState(key)
            self.assertIsNone(saved.load())
            self.assertIsNone(notify.meta_get(key))

    def test_missing_table_is_recreated(self):
        notify.meta_set("probe", "1")
        store.execute("DROP TABLE notify_meta")
        self.assertIsNone(notify.meta_get("probe"))
        self.assertTrue(notify.meta_set("probe", "2"))
        self.assertEqual(notify.meta_get("probe"), "2")
        self.assertEqual(notify.meta_keys("pro"), ["probe"])


class RouterImportTest(unittest.TestCase):
    CHANNEL = {"id": "kanal0001", "kinds": [], "min_level": "warn", "debounce_min": 15, "resolved": True}

    def test_pending_is_sanitised(self):
        router = notify.ChannelRouter(self.CHANNEL, clock=lambda: 10.0, wall=lambda: 2000.0)
        router.import_state({
            "gps:fix": {"open_since": 1000.0, "notified": None, "last_sent": None, "suppressed": 1,
                        "pending": {"id": "x", "t": "gestern", "kind": "GPS los!", "level": "kaputt",
                                    "title": "GPS-Fix verloren", "data": [1]}},
            "gps:leer": {"open_since": 1000.0, "pending": {"title": ""}},
        })
        pending = router.state["gps:fix"]["pending"]
        self.assertEqual(pending, {"id": None, "t": None, "kind": "other", "level": "warn",
                                   "title": "GPS-Fix verloren", "data": {}})
        self.assertIsNone(router.state["gps:leer"]["pending"])
        out = router.tick()                                           # wird nachgeholt, ohne Fehler
        self.assertEqual(len(out), 1)
        self.assertIn("besteht seit", out[0]["title"])

    def test_open_since_in_future_gives_no_negative_duration(self):
        router = notify.ChannelRouter(self.CHANNEL, clock=lambda: 10.0, wall=lambda: 1000.0)
        router.import_state({"gps:fix": {"open_since": 5000.0,
                                         "pending": {"title": "GPS-Fix verloren", "level": "warn"}}})
        out = router.tick()
        self.assertIn("besteht seit 0 s", out[0]["title"])


def ev_wait(notifier, count, captured, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        notifier.process()
        if len(captured) >= count:
            return True
        time.sleep(0.02)
    return len(captured) >= count


class NotifierRestartTest(_Data):
    """Simulierter Neustart: Modul neu laden, dieselbe Datenbank."""

    def setUp(self):
        super().setUp()
        self.known = mock.patch.object(notify, "_known", return_value=([], {}))
        self.known.start()
        notify.save_channel({"name": "Haus", "type": "webhook", "url": "http://192.168.1.5/hook"})
        self.cid = notify._load_all()[0]["id"]
        self.captured = []

    def tearDown(self):
        self.known.stop()
        super().tearDown()

    def boot(self):
        """„Container startet“: Verteiler mit abgefangener Zustellung, Position wie nach dem Start."""
        notifier = notify.NOTIFIER
        notifier.deliver_fn = lambda channel, clean, version="": self.captured.append(clean)
        notifier._load_position()
        return notifier

    def restart(self, while_down=None):
        self.known.stop()
        notify._reset_for_tests()                     # SIGTERM: stop() → flush()
        if while_down:
            while_down()                              # was zwischen Herunterfahren und Start passiert
        importlib.reload(notify)
        self.known = mock.patch.object(notify, "_known", return_value=([], {}))
        self.known.start()
        return self.boot()

    def problem(self):
        events.emit("gps", "warn", "GPS-Fix verloren", {"subject": "fix"})

    def fixed(self):
        events.emit("gps", "info", "GPS-Fix wieder da", {"subject": "fix"})

    def test_no_duplicate_and_resolved_after_restart(self):
        first = self.boot()
        self.problem()
        self.assertTrue(ev_wait(first, 1, self.captured))
        second = self.restart()
        self.problem()                                # Quelle meldet nach dem Start erneut
        second.process()
        time.sleep(0.3)
        self.assertEqual(len(self.captured), 1)       # kein doppelter Alarm
        self.fixed()
        self.assertTrue(ev_wait(second, 2, self.captured))
        self.assertIn("Dauer", self.captured[1]["title"])

    def test_very_old_state_is_dropped(self):
        first = self.boot()
        self.problem()
        self.assertTrue(ev_wait(first, 1, self.captured))
        key = notify.ROUTER_STATE_PREFIX + self.cid

        def a_day_later():
            stored = json.loads(notify.meta_get(key))
            stored["saved"] = time.time() - notify.STATE_MAX_AGE - 600   # Container einen Tag aus
            notify.meta_set(key, json.dumps(stored))

        second = self.restart(a_day_later)
        self.problem()
        self.assertTrue(ev_wait(second, 2, self.captured))           # neu gemeldet statt verschluckt

    def test_legacy_state_from_older_version(self):
        router = notify.ChannelRouter(notify._load_all()[0])
        router.offer({"id": 1, "t": time.time() - 60, "kind": "gps", "level": "warn",
                      "title": "GPS-Fix verloren", "data": {"subject": "fix"}})
        notify.meta_set(notify.ROUTER_STATE_PREFIX + self.cid, json.dumps(router.export_state()))
        second = self.restart()
        self.problem()
        second.process()
        time.sleep(0.3)
        self.assertEqual(self.captured, [])
        self.fixed()
        self.assertTrue(ev_wait(second, 1, self.captured))
        self.assertIn("Dauer", self.captured[0]["title"])
        stored = json.loads(notify.meta_get(notify.ROUTER_STATE_PREFIX + self.cid))
        self.assertEqual(stored["v"], notify.STATE_FORMAT)              # neues Format geschrieben

    def test_very_old_legacy_state_is_dropped(self):
        """Update nach langer Pause: Zustand im älteren Format mit 30 Tage alter Meldung verschluckt nichts."""
        router = notify.ChannelRouter(notify._load_all()[0])
        router.offer({"id": 1, "t": time.time(), "kind": "gps", "level": "warn",
                      "title": "GPS-Fix verloren", "data": {"subject": "fix"}})
        legacy = router.export_state()
        for item in legacy.values():
            item["open_since"] = item["last_sent"] = time.time() - 30 * DAY
        notify.meta_set(notify.ROUTER_STATE_PREFIX + self.cid, json.dumps(legacy))
        second = self.restart()
        self.problem()
        self.assertTrue(ev_wait(second, 1, self.captured))            # neu gemeldet
        self.assertEqual(self.captured[0]["title"], "GPS-Fix verloren")

    def test_channel_state_does_not_outlive_heartbeat_state(self):
        """Stromausfall knapp einen Tag: Der Ping-Zustand (vor 24,5 h gestempelt) ist verfallen. Der Kanal
        (vor 23,5 h gestempelt) darf den Betreff dann nicht offen halten – sonst wäre jeder spätere Ausfall
        „schon gemeldet“."""
        first = self.boot()
        events.emit("heartbeat", "warn", "Zeitwächter nicht erreichbar", {"subject": "heartbeat", "resolves": False})
        self.assertTrue(ev_wait(first, 1, self.captured))
        key = notify.ROUTER_STATE_PREFIX + self.cid
        notify.meta_set(heartbeat.STATE_KEY, notify.stamp({"failures": 3, "alarmed": True, "target": "0" * 16},
                                                          now=time.time() - 24.5 * 3600))

        def power_cut():
            stored = json.loads(notify.meta_get(key))
            stored["saved"] = time.time() - 23.5 * 3600
            notify.meta_set(key, json.dumps(stored))

        second = self.restart(power_cut)
        self.assertIsNone(notify.SavedState(heartbeat.STATE_KEY).load())   # Quelle: verfallen
        events.emit("heartbeat", "warn", "Zeitwächter nicht erreichbar", {"subject": "heartbeat", "resolves": False})
        self.assertTrue(ev_wait(second, 2, self.captured))           # neuer Ausfall wird gemeldet

    def test_garbage_state_starts_clean(self):
        notify.meta_set(notify.ROUTER_STATE_PREFIX + self.cid, '{"v":2,"saved":1e300,"state":{"x":')
        second = self.restart()
        self.problem()
        self.assertTrue(ev_wait(second, 1, self.captured))

    def test_state_of_removed_channel_is_forgotten(self):
        notify.meta_set(notify.ROUTER_STATE_PREFIX + "weg0000001", notify.stamp({}))
        notifier = self.boot()
        notifier.process()
        self.assertIsNone(notify.meta_get(notify.ROUTER_STATE_PREFIX + "weg0000001"))
        self.assertIsNotNone(notify.meta_get(notify.ROUTER_STATE_PREFIX + self.cid))

    def test_disabled_channel_keeps_state_until_expiry(self):
        notifier = self.boot()
        self.problem()
        self.assertTrue(ev_wait(notifier, 1, self.captured))
        store.execute("UPDATE notify_channels SET enabled=0 WHERE id=?", (self.cid,))
        notifier.reload()
        notifier.process()
        stored = notify.unstamp(notify.meta_get(notify.ROUTER_STATE_PREFIX + self.cid))[0]
        self.assertEqual(stored["subjects"]["gps:fix"]["notified"], "warn")

    def open_problem(self):
        notifier = self.boot()
        self.problem()
        self.assertTrue(ev_wait(notifier, 1, self.captured))
        return notifier

    def test_saved_channel_state_carries_keyed_target(self):
        self.open_problem()
        notify.NOTIFIER._save_states(force=True)
        raw = notify.meta_get(notify.ROUTER_STATE_PREFIX + self.cid)
        self.assertNotIn("192.168.1.5", raw)
        stored = notify.unstamp(raw)[0]
        self.assertEqual(stored["target"], notify.target_id("kanal", "webhook", "http://192.168.1.5/hook", ""))

    def test_target_change_while_enabled_drops_open_subjects(self):
        """Ziel ändern: Probleme beim neuen Ziel gelten nicht als „schon gemeldet“, kein „behoben“ ohne Alarm."""
        notifier = self.open_problem()
        notify.save_channel({"id": self.cid, "name": "Haus", "type": "webhook", "url": "http://192.168.1.6/hook"})
        notifier.process()
        self.problem()
        self.assertTrue(ev_wait(notifier, 2, self.captured))          # neu gemeldet
        self.assertEqual(self.captured[1]["title"], "GPS-Fix verloren")

    def test_target_change_after_restart_drops_saved_state(self):
        """Kanal ändert das Ziel, während der Container aus ist (z. B. Sicherung zurückgespielt): nach dem
        Neustart kein offener Betreff des alten Ziels."""
        self.open_problem()

        def other_target():
            store.execute("UPDATE notify_channels SET url=? WHERE id=?", ("http://192.168.1.6/hook", self.cid))

        second = self.restart(other_target)
        self.fixed()
        second.process()
        time.sleep(0.3)
        self.assertEqual(len(self.captured), 1)                       # kein „behoben“ ohne vorherigen Alarm
        self.problem()
        self.assertTrue(ev_wait(second, 2, self.captured))
        self.assertEqual(self.captured[1]["title"], "GPS-Fix verloren")

    def test_target_change_while_disabled_drops_state_on_enable(self):
        notifier = self.open_problem()
        store.execute("UPDATE notify_channels SET enabled=0 WHERE id=?", (self.cid,))
        notifier.reload()
        notifier.process()
        self.assertIsNotNone(notify.meta_get(notify.ROUTER_STATE_PREFIX + self.cid))
        store.execute("UPDATE notify_channels SET enabled=1, topic=? WHERE id=?", ("anders", self.cid))
        notifier.reload()
        notifier.process()
        self.problem()
        self.assertTrue(ev_wait(notifier, 2, self.captured))

    def test_same_target_new_secret_keeps_state(self):
        notifier = self.open_problem()
        notify.save_channel({"id": self.cid, "name": "Neu", "type": "webhook", "url": "http://192.168.1.5/hook",
                             "secret": "neues-token"})
        notifier.process()
        self.problem()
        notifier.process()
        time.sleep(0.3)
        self.assertEqual(len(self.captured), 1)                       # bleibt „schon gemeldet“


class TargetIdTest(_Data):
    def test_keyed_and_not_derivable_from_address(self):
        import hashlib
        url = "https://hc.example.org/ping/abc"
        first = notify.target_id("ping", "auto", url)
        self.assertRegex(first, r"^[0-9a-f]{32}$")
        self.assertEqual(notify.target_id("ping", "auto", url), first)              # stabil
        self.assertNotEqual(notify.target_id("ping", "get", url), first)
        plain = hashlib.sha256(f"auto\n{url}".encode()).hexdigest()
        self.assertFalse(plain.startswith(first[:16]))
        self.assertNotIn(first, hashlib.sha256(f"ping\nauto\n{url}".encode()).hexdigest())
        key = notify.meta_get(notify.TARGET_KEY)
        self.assertRegex(key, r"^[0-9a-f]{64}$")
        notify.meta_set(notify.TARGET_KEY, None)                                     # anderer Schlüssel
        self.assertNotEqual(notify.target_id("ping", "auto", url), first)

    def test_without_database_no_id(self):
        with mock.patch.object(notify, "meta_get", return_value=None), \
                mock.patch.object(notify, "_meta_retry", side_effect=OSError):
            self.assertIsNone(notify.target_id("ping", "auto", "https://hc.example.org/x"))


class ClientAlarmRestartTest(_Data):
    def setUp(self):
        super().setUp()
        self.sent = []
        self.patch_state()

    def patch_state(self):
        self.watch = statewatch.StateWatcher(lambda *a, **k: self.sent.append(a))
        for patch in getattr(self, "state_patches", []):
            patch.stop()
        self.state_patches = [mock.patch.object(server, "STATE_WATCH", self.watch),
                              mock.patch.dict(server._CLIENT_ALARMS, {"loaded": False, "saved": None})]
        for patch in self.state_patches:
            patch.start()
            self.addCleanup(patch.stop)

    def open_alarm(self, ip):
        self.watch.restore_client_alarms([ip])

    def test_alarm_survives_restart(self):
        server._client_alarms_persist()                   # Start: nichts gespeichert
        self.open_alarm("192.168.1.20")
        server._client_alarms_persist()
        self.patch_state()                                # „Neustart“
        server._client_alarms_persist()
        self.assertEqual(self.watch.client_alarm_ips(), ["192.168.1.20"])

    def test_old_alarm_list_is_dropped(self):
        notify.meta_set(server.CLIENT_ALARMS_KEY, notify.stamp(["192.168.1.20"],
                                                               now=time.time() - notify.STATE_MAX_AGE - 1))
        server._client_alarms_persist()
        self.assertEqual(self.watch.client_alarm_ips(), [])

    def test_legacy_list_and_garbage(self):
        notify.meta_set(server.CLIENT_ALARMS_KEY, json.dumps(["192.168.1.21", "kein Gerät\nX", 5, "::1"]))
        server._client_alarms_persist()
        self.assertEqual(self.watch.client_alarm_ips(), ["192.168.1.21", "::1"])
        self.patch_state()
        notify.meta_set(server.CLIENT_ALARMS_KEY, '{"v":2,"saved":1,"state":{"a":1}}')
        server._client_alarms_persist()
        self.assertEqual(self.watch.client_alarm_ips(), [])

    def test_unchanged_list_is_restamped_on_shutdown(self):
        server._client_alarms_persist()
        self.open_alarm("192.168.1.22")
        server._client_alarms_persist()
        stored = json.loads(notify.meta_get(server.CLIENT_ALARMS_KEY))
        stored["saved"] -= 3600
        notify.meta_set(server.CLIENT_ALARMS_KEY, json.dumps(stored))
        server._client_alarms_persist(restamp=True)
        self.assertGreater(json.loads(notify.meta_get(server.CLIENT_ALARMS_KEY))["saved"], time.time() - 60)


class HeartbeatRestartTest(_Data):
    URL = "https://hc.example.org/ping/abc"

    def make(self, url=URL, ok=False):
        self.url = [url]
        self.ok = [ok]
        self.emitted = []

        def sender(url, state, mode):
            if not self.ok[0]:
                raise heartbeat.PingError("Zeitüberschreitung")
            return "up"

        return heartbeat.Pinger(config=lambda: {"url": self.url[0], "interval": 60, "mode": "auto"},
                                sender=sender, emit=lambda *a: self.emitted.append(a),
                                saved=notify.SavedState(heartbeat.STATE_KEY))

    def fail_until_alarm(self, ping):
        for _ in range(heartbeat.FAIL_EVENT_AFTER):
            ping.tick(force=True)
        self.assertEqual(self.emitted[-1][1], "warn")

    def test_recovery_after_restart_is_reported(self):
        self.fail_until_alarm(self.make())
        ping = self.make(ok=True)                         # Neustart, Wächter wieder da
        ping.tick()
        self.assertEqual([(e[1], e[2]) for e in self.emitted], [("info", "Zeitwächter wieder erreichbar")])

    def test_counter_continues_without_second_alarm(self):
        self.fail_until_alarm(self.make())
        ping = self.make()
        ping.tick()
        self.assertEqual(ping.status()["failures"], heartbeat.FAIL_EVENT_AFTER + 1)
        self.assertEqual(self.emitted, [])                # schon gemeldet: kein zweiter Alarm

    def test_saved_state_holds_no_address(self):
        self.fail_until_alarm(self.make())
        raw = notify.meta_get(heartbeat.STATE_KEY)
        self.assertNotIn("hc.example.org", raw)
        self.assertNotIn("abc", raw.replace('"alarmed"', ""))

    def test_unknown_key_counts_as_other_target(self):
        """Fehlt der lokale Schlüssel (oder ist er ein anderer), gilt das Ziel als „anders“: still schließen."""
        self.fail_until_alarm(self.make())
        notify.meta_set(notify.TARGET_KEY, None)
        ping = self.make(ok=True)
        ping.tick()
        self.assertEqual([e[3].get("notify") for e in self.emitted], [False])

    def test_listener_reading_status_does_not_block(self):
        """Das stille Schließen nach dem Start feuert sein Ereignis außerhalb der Sperre des Pingers."""
        import threading
        self.fail_until_alarm(self.make())
        ping = self.make(url="")
        seen = []
        ping.emit = lambda *a: seen.append(ping.status())
        worker = threading.Thread(target=ping.tick, daemon=True)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive(), "tick() hängt an der eigenen Sperre")
        self.assertEqual(len(seen), 1)

    def test_switched_off_after_restart_closes_quietly(self):
        self.fail_until_alarm(self.make())
        ping = self.make(url="")
        ping.tick()
        self.assertEqual(len(self.emitted), 1)
        kind, level, title, data, _source = self.emitted[0]
        self.assertEqual((kind, level), ("heartbeat", "info"))
        self.assertEqual(data, {"subject": "heartbeat", "resolves": True, "notify": False})
        self.assertIsNone(notify.meta_get(heartbeat.STATE_KEY))

    def test_other_target_after_restart_starts_fresh(self):
        self.fail_until_alarm(self.make())
        ping = self.make(url="https://hc.example.org/ping/neu", ok=True)
        ping.tick()
        self.assertEqual([e[3].get("notify") for e in self.emitted], [False])
        self.assertEqual(ping.status()["failures"], 0)

    def test_switch_off_while_running_closes_quietly(self):
        ping = self.make()
        self.fail_until_alarm(ping)
        self.url[0] = ""
        ping.tick()
        self.assertEqual(self.emitted[-1][3], {"subject": "heartbeat", "resolves": True, "notify": False})

    def test_old_state_is_not_taken(self):
        self.fail_until_alarm(self.make())
        stored = json.loads(notify.meta_get(heartbeat.STATE_KEY))
        stored["saved"] -= notify.STATE_MAX_AGE + 60
        notify.meta_set(heartbeat.STATE_KEY, json.dumps(stored))
        ping = self.make(ok=True)
        ping.tick()
        self.assertEqual(self.emitted, [])
        self.assertEqual(ping.status()["failures"], 0)

    def test_quiet_close_ends_open_problem_in_router(self):
        """Das stille Schließen beendet den offenen Betreff: Ein späterer Ausfall wird wieder gemeldet."""
        router = notify.ChannelRouter({"id": "k", "kinds": [], "min_level": "warn", "debounce_min": 0})
        warn = {"id": 1, "t": time.time(), "kind": "heartbeat", "level": "warn", "title": "nicht erreichbar",
                "data": {"subject": "heartbeat", "resolves": False}}
        self.assertEqual(len(router.offer(warn)), 1)
        quiet = {"id": 2, "t": time.time(), "kind": "heartbeat", "level": "info", "title": "beendet",
                 "data": {"subject": "heartbeat", "resolves": True, "notify": False}}
        self.assertEqual(router.offer(quiet), [])
        self.assertEqual(len(router.offer(dict(warn, id=3))), 1)


class BackupRestoreTest(BackupTestBase):
    """Die Sicherung trägt keinen Benachrichtigungszustand; eine Wiederherstellung lässt ihn stehen
    (die Kanäle bleiben dieselben) und räumt den Zustand nicht mehr vorhandener Kanäle auf."""

    def test_state_not_in_backup_and_kept_on_restore(self):
        notify._reset_for_tests()
        cid = notify._load_all()[0]["id"]
        key = notify.ROUTER_STATE_PREFIX + cid
        notify.meta_set(key, notify.stamp({"gps:fix": {"open_since": time.time(), "notified": "warn"}}))
        notify.meta_set(server.CLIENT_ALARMS_KEY, notify.stamp(["192.168.1.77"]))
        notify.meta_set(notify.ROUTER_STATE_PREFIX + "weg0000001", notify.stamp({}))
        data = self.make_backup()
        for name, content in self.unpacked(data).items():
            self.assertNotIn(b"192.168.1.77", content, name)
            self.assertNotIn(b"router:", content, name)
        staged = backup.stage_upload(io.BytesIO(data), len(data))
        with mock.patch.object(notify.NOTIFIER, "_save_position"):
            backup.apply(staged["token"])
        self.assertIsNotNone(notify.meta_get(key))
        self.assertIsNotNone(notify.meta_get(server.CLIENT_ALARMS_KEY))
        notify.NOTIFIER._sync_channels()
        self.assertIsNone(notify.meta_get(notify.ROUTER_STATE_PREFIX + "weg0000001"))
        self.assertIsNotNone(notify.meta_get(key))
        notify._reset_for_tests()


if __name__ == "__main__":
    unittest.main()
