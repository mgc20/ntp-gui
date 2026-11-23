"""Fehlerkorrekturen 1.9: Zeitlimits und Antwortprüfung im Dashboard, Zahlen in Einstellungen, nicht lesbare
settings.json (fail-closed), Verlauf und Update-Prüfung bei einer Uhr in der Zukunft, Größe der Sicherung,
Zustand der Benachrichtigungen und des Client-Alarms über einen Neustart, Ladezustände und Layout.

Jeder Test prüft das sichere bzw. richtige Verhalten und schlägt ohne die jeweilige Korrektur fehl."""

import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import backup  # noqa: E402
import confgen  # noqa: E402
import events  # noqa: E402
import history  # noqa: E402
import notify  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import statewatch  # noqa: E402
import store  # noqa: E402
import updatecheck  # noqa: E402
from test_anmeldung import _ServerBase  # noqa: E402
from test_eingaben_ziele import FAKE_CHRONYD  # noqa: E402
from test_frontend_states import DOM, mod  # noqa: E402

DAY = 86400


class _TempData(unittest.TestCase):
    """Eigenes Datenverzeichnis (settings.json, Datenbank) je Test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="korrekturen-")
        store.close_all()
        self.patches = [mock.patch.object(settings, "DATA_DIR", self.tmp),
                        mock.patch.object(settings, "SETTINGS_FILE", os.path.join(self.tmp, "settings.json"))]
        for patch in self.patches:
            patch.start()
        settings._CACHE.update(mtime=None, data=None, error=None)
        notify._READY["db"] = None
        self.clock = dict(events._CLOCK)
        events._CLOCK.update(plausible=None, at=None, noted=False, held=False)

    def tearDown(self):
        events._CLOCK.clear()
        events._CLOCK.update(self.clock)
        store.close_all()
        for patch in reversed(self.patches):
            patch.stop()
        settings._CACHE.update(mtime=None, data=None, error=None)
        notify._READY["db"] = None
        shutil.rmtree(self.tmp, ignore_errors=True)


# --- Einstellungen: Zahlen ------------------------------------------------------------------------------

class NumberFieldTest(unittest.TestCase):
    def assert_invalid(self, key, value):
        with self.assertRaises(settings.ValidationError, msg=f"{key}={value!r}"):
            settings.validate({key: value})

    def test_infinite_and_huge_numbers_are_validation_errors(self):
        self.assert_invalid("ntp_port", float("inf"))        # 1e999 aus JSON
        self.assert_invalid("ntp_port", float("-inf"))
        self.assert_invalid("ntp_port", float("nan"))
        self.assert_invalid("gps_offset", 10 ** 400)          # float(10**400) läuft über
        self.assert_invalid("gps_offset", "1e999")

    def test_integer_fields_reject_fractions_and_odd_spellings(self):
        self.assert_invalid("ntp_port", 1.5)
        self.assert_invalid("ntp_port", "1_23")
        self.assert_invalid("ntp_port", "١٢٣")   # andere Ziffernsysteme
        self.assertEqual(settings.validate({"ntp_port": 123.0})["ntp_port"], 123)
        self.assertEqual(settings.validate({"ntp_port": " 124 "})["ntp_port"], 124)
        self.assertEqual(settings.validate({"gps_offset": "0.25"})["gps_offset"], 0.25)


class NumberFieldHttpTest(_ServerBase):
    def test_infinite_number_is_422_with_field(self):
        status, payload, _ = self.request("POST", "/api/settings", {"changes": {"ntp_port": float("inf")}})
        self.assertEqual(status, 422, payload)
        self.assertIn("ntp_port", json.dumps(payload))
        self.assertNotIn("cannot convert", json.dumps(payload))


# --- Einstellungen: nicht lesbare settings.json ------------------------------------------------------------

class UnreadableSettingsTest(_TempData):
    def write_raw(self, text):
        with open(settings.SETTINGS_FILE, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_broken_file_locks_instead_of_dropping_password(self):
        settings.set_credentials("admin", "lang-und-eigen-42")
        good = Path(settings.SETTINGS_FILE).read_text(encoding="utf-8")
        broken = good[: len(good) // 2]   # abgeschnitten
        self.write_raw(broken)
        self.assertIsNotNone(settings.load_error())
        info = server.auth_info()
        self.assertTrue(info["locked"])
        self.assertEqual(info["code"], "settings_unreadable")
        with self.assertRaises(settings.SettingsUnreadable):
            settings.save({"web_title": "Neu"})
        with self.assertRaises(settings.ValidationError):
            settings.set_credentials("admin", None)
        self.assertEqual(Path(settings.SETTINGS_FILE).read_text(encoding="utf-8"), broken)  # nicht überschrieben
        self.assertIn("GESPERRT", "\n".join(server.startup_auth_warnings("0.0.0.0")))
        self.assertTrue(settings.storage_info()["error"])

    def test_repaired_file_unlocks_and_missing_file_is_fine(self):
        self.write_raw("[1, 2]")   # kein JSON-Objekt
        self.assertIsNotNone(settings.load_error())
        self.write_raw(json.dumps({"schema": settings.SCHEMA_VERSION, "values": {}}))
        os.utime(settings.SETTINGS_FILE, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
        self.assertIsNone(settings.load_error())
        os.unlink(settings.SETTINGS_FILE)
        self.assertIsNone(settings.load_error())
        self.assertFalse(server.auth_info()["locked"])


    def test_repaired_file_with_older_schema_unlocks_and_is_migrated(self):
        for repaired in ({"schema": 1, "ntp_port": 123}, {"values": {"web_title": "Zeit"}}, {"schema": 3}):
            with self.subTest(repaired=repaired):
                self.write_raw("{")
                self.assertIsNotNone(settings.load_error())
                self.write_raw(json.dumps(repaired))
                os.utime(settings.SETTINGS_FILE, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
                self.assertIsNone(settings.load_error())
                self.assertIsInstance(settings.values(), dict)
                self.assertFalse(server.auth_info().get("locked"))
                stored = json.loads(Path(settings.SETTINGS_FILE).read_text(encoding="utf-8"))
                self.assertEqual(stored["schema"], settings.SCHEMA_VERSION)

    def test_messages_go_to_stderr_not_stdout(self):
        self.write_raw('{"auth": ')
        settings._UNREADABLE_NOTED["error"] = None   # einmal je Grund ins Log
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertIsNotNone(settings.load_error())
        self.assertEqual(out.getvalue(), "")
        self.assertIn("nicht lesbar", err.getvalue())

    def test_message_warns_that_removing_the_file_drops_the_password(self):
        self.write_raw("{")
        error = settings.load_error()
        self.assertIn("Passwort", error.split("Entfernst du sie")[1])
        self.assertIn("WEB_REQUIRE_AUTH=true", error)


class UnreadableSettingsConfgenTest(_TempData):
    """confgen bei nicht lesbarer settings.json: stdout nur Zuweisungen, Zeitserver im Notbetrieb."""

    def setUp(self):
        super().setUp()
        fake = os.path.join(self.tmp, "chronyd")
        Path(fake).write_text(FAKE_CHRONYD, encoding="utf-8")
        os.chmod(fake, 0o700)
        run_dir = os.path.join(self.tmp, "run")
        os.makedirs(run_dir)
        patches = [
            mock.patch.object(confgen, "CHRONYD_BIN", fake),
            mock.patch.object(confgen, "CHRONY_CONF", os.path.join(self.tmp, "etc", "chrony.conf")),
            mock.patch.object(confgen, "PTP4L_CONF", os.path.join(self.tmp, "etc", "ptp4l.conf")),
            mock.patch.object(confgen, "CUSTOM_CHRONY", os.path.join(self.tmp, "config", "chrony.conf")),
            mock.patch.object(confgen, "CUSTOM_PTP4L", os.path.join(self.tmp, "config", "ptp4l.conf")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.env = {"GPS_WAIT_SECONDS": "0", "NTPGUI_RUN_DIR": run_dir}

    def save_then_break(self):
        settings.save({"deny_networks": ["198.51.100.0/24"], "ntp_ratelimit": "streng"})
        Path(settings.SETTINGS_FILE).write_text('{"schema": 4, "values": {"deny_', encoding="utf-8")
        settings._CACHE.update(mtime=None, data=None, error=None)

    def conf(self):
        return Path(confgen.CHRONY_CONF).read_text(encoding="utf-8")

    def test_stdout_holds_only_assignments(self):
        self.save_then_break()
        with mock.patch.dict(os.environ, dict(self.env, GPS_ENABLE="true", DNS_MODE="off"), clear=True), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(confgen.main(["confgen.py", "apply", "--start"]), 0)
        lines = [line for line in out.getvalue().splitlines() if line]
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(line, r"^[A-Z_][A-Z0-9_]*=", line)
        self.assertIn("NTPGUI_GPS_ENABLE=1", lines)

    def test_time_server_runs_restricted_without_readable_settings(self):
        self.save_then_break()
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            confgen.apply(self.env, fallback=True)
        conf = self.conf()
        self.assertNotRegex(conf, r"(?m)^allow ")
        self.assertIn(confgen.RATELIMIT_LINES["streng"][0], conf)
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            confgen.apply(dict(self.env, ALLOW_NETWORKS="10.0.0.0/8", NTP_RATELIMIT="aus"), fallback=True)
        conf = self.conf()
        self.assertEqual(re.findall(r"(?m)^allow (.*)$", conf), ["10.0.0.0/8"])
        self.assertIn(confgen.RATELIMIT_LINES["streng"][0], conf)

    def test_readable_settings_are_not_restricted(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            confgen.apply(self.env, fallback=True)
        self.assertRegex(self.conf(), r"(?m)^allow 192\.168\.0\.0/16$")


class UnreadableSettingsHttpTest(_ServerBase):
    def test_dashboard_answers_with_protective_message(self):
        with open(settings.SETTINGS_FILE, "w", encoding="utf-8") as handle:
            handle.write('{"auth": {"user": "admin", "hash": ')
        settings._CACHE.update(mtime=None, data=None, error=None)
        try:
            status, payload, _ = self.request("GET", "/api/status", headers={"Accept": "application/json"})
            self.assertEqual(status, 503)
            self.assertEqual(payload["reason"], "settings_unreadable")
            status, body, _ = self.request("GET", "/", headers={"Accept": "text/html"})
            self.assertEqual(status, 503)
            self.assertIn("Einstellungen nicht lesbar", body.decode())
            self.assertEqual(self.request("GET", "/healthz")[0], 200)
            self.assertEqual(self.request("POST", "/api/settings", {"changes": {"web_title": "x"}})[0], 503)
        finally:
            settings._CACHE.update(mtime=None, data=None, error=None)


# --- Verlauf: Uhr in der Zukunft ------------------------------------------------------------------------

def sample(t):
    return {"t": t, "offset": 1e-6, "stratum": 2}


class HistoryClockAheadTest(_TempData):
    def test_clock_ahead_keeps_history_and_charts_stay_filled(self):
        h = history.History(8640, os.path.join(self.tmp, "history.json.gz"), days=30)
        now = int(time.time())
        for i in range(60):
            h.add(sample(now - 3600 + i * 60))
        for i in range(20):
            h.add(sample(now - 10 * DAY + i * 60))
        h.save(force=True)
        real = store.query("SELECT count(*) FROM samples")[0][0]
        self.assertEqual(real, 80)
        ahead = now + 40 * DAY
        with mock.patch("time.time", return_value=ahead):
            h.add(sample(ahead))
            h.save(force=True)
        self.assertEqual(store.query("SELECT count(*) FROM samples")[0][0], real + 1)  # nichts gelöscht
        # Uhr wieder richtig: die letzte Stunde zeigt die echten Punkte, nicht ein leeres Fenster.
        self.assertGreaterEqual(len(h.query(3600, 600)), 50)
        # chrony meldet die Uhr als plausibel: Der Zukunftspunkt verschwindet beim nächsten Schreiben.
        events._CLOCK.update(plausible=True, at=time.monotonic())
        h.add(sample(now))
        h.save(force=True)
        self.assertEqual(store.query("SELECT count(*) FROM samples WHERE t > ?", (now + DAY,))[0][0], 0)
        self.assertEqual(store.query("SELECT count(*) FROM samples")[0][0], real + 1)

    def test_clock_ahead_while_chrony_reports_synchronised_keeps_history(self):
        # Die Quelle selbst stellt die Uhr vor: chrony meldet „synchron“ mit kleinem Offset.
        h = history.History(8640, os.path.join(self.tmp, "history.json.gz"), days=30)
        now = int(time.time())
        for i in range(100):
            h.add(sample(now - 25 * DAY + i * (25 * DAY // 100)))
        h.save(force=True)
        events.note_tracking({"leap_status": "Normal", "system_time_offset": 0.0})
        self.assertTrue(events.clock_state())
        ahead = now + 40 * DAY
        with mock.patch("time.time", return_value=ahead):
            h.add(sample(ahead))
            h.save(force=True)
        self.assertEqual(store.query("SELECT count(*) FROM samples")[0][0], 101)
        h.add(sample(now + 60))   # Uhr wieder richtig
        h.save(force=True)
        self.assertEqual(store.query("SELECT count(*) FROM samples WHERE t <= ?", (now,))[0][0], 100)
        self.assertEqual(store.query("SELECT count(*) FROM samples WHERE t > ?", (now + DAY,))[0][0], 0)

    def test_old_points_still_expire_without_a_jump(self):
        events.note_tracking({"leap_status": "Normal", "system_time_offset": 0.0})
        h = history.History(8640, os.path.join(self.tmp, "history.json.gz"), days=30)
        now = int(time.time())
        for i in range(40):
            h.add(sample(now - 39 * DAY + i * DAY))
        h.save(force=True)
        self.assertEqual(store.query("SELECT count(*) FROM samples WHERE t < ?", (now - 30 * DAY,))[0][0], 0)


# --- Update-Prüfung: Uhr in der Zukunft -----------------------------------------------------------------

class _MemoryState:
    def __init__(self, data):
        self.data = data

    def load(self):
        return self.data

    def save(self, data):
        self.data = data


class UpdateFutureAttemptTest(unittest.TestCase):
    def test_attempt_in_future_does_not_block_checks(self):
        now = 1_800_000_000.0
        checker = updatecheck.Checker("1.9.0", lambda: True, state=_MemoryState({"last_attempt": now + 40 * DAY}))
        today = updatecheck._day(now)
        at = today * updatecheck.DAY + checker.slot(today) + 1
        self.assertTrue(checker.due(at))
        self.assertLessEqual(checker.next_check(at), at + updatecheck.DAY)

    def test_attempt_today_still_counts(self):
        now = 1_800_000_000.0
        checker = updatecheck.Checker("1.9.0", lambda: True, state=_MemoryState({"last_attempt": now}))
        self.assertFalse(checker.due(now + 60))


# --- Sicherung: nie größer als die eigene Wiederherstellung ---------------------------------------------

class BackupSizeTest(_TempData):
    def test_backup_with_dense_history_stays_restorable(self):
        store.migrate("history", history._SCHEMA)
        now = int(time.time())
        filler = "x" * 400   # Messpunkte wie bei kleinem Messintervall: viele und nicht klein
        rows = [(now - 20000 + i * 2, json.dumps({"t": now - 20000 + i * 2, "offset": 1e-6, "pad": filler}))
                for i in range(10000)]
        with store.transaction() as conn:
            conn.executemany("INSERT INTO samples(t, json) VALUES(?, ?)", rows)
            conn.executemany("INSERT INTO samples_5m(b, t, json) VALUES(?, ?, ?)",
                             [(b, b * 300, json.dumps({"t": b * 300})) for b in
                              range((now - 20000) // 300, now // 300 + 1)])
        rollups = store.query("SELECT count(*) FROM samples_5m")[0][0]
        limit = 256 * 1024
        dest = os.path.join(self.tmp, "sicherung.tar.gz")
        with mock.patch.dict(backup.PART_LIMITS, {backup.DB_PART: limit}), \
                mock.patch.object(backup, "_flush", lambda: None):
            manifest = backup.create(dest, "1.9.0")
            sizes = {p["name"]: p["size"] for p in manifest["parts"]}
            self.assertLessEqual(sizes[backup.DB_PART], limit)
            self.assertIn("history_thinned_s", manifest)
            work = os.path.join(self.tmp, "entpackt")
            os.makedirs(work)
            backup.unpack(dest, work)   # die eigene Wiederherstellung nimmt die Sicherung an
        conn = sqlite3.connect(os.path.join(work, backup.DB_PART))
        try:
            kept, first = conn.execute("SELECT count(*), min(t) FROM samples").fetchone()
            self.assertEqual(conn.execute("SELECT count(*) FROM samples_5m").fetchone()[0], rollups)
        finally:
            conn.close()
        self.assertGreater(kept, 0)
        self.assertEqual(first, now - 20000)   # ältester Punkt bleibt: die Verdichtung wird nicht gekürzt

    def test_small_backup_is_unchanged(self):
        store.migrate("history", history._SCHEMA)
        with store.transaction() as conn:
            conn.executemany("INSERT INTO samples(t, json) VALUES(?, ?)",
                             [(1000 + i, json.dumps({"t": 1000 + i})) for i in range(50)])
        dest = os.path.join(self.tmp, "klein.tar.gz")
        with mock.patch.object(backup, "_flush", lambda: None):
            manifest = backup.create(dest, "1.9.0")
        self.assertNotIn("history_thinned_s", manifest)
        self.assertEqual(manifest["rows"]["samples"], 50)
        with tarfile.open(dest) as tar:
            self.assertEqual(tar.getnames()[0], backup.MANIFEST)


# --- Benachrichtigungen und Client-Alarm über einen Neustart ---------------------------------------------

CHANNEL = {"id": "kanal0001", "name": "Test", "type": "webhook", "kinds": [], "min_level": "warn",
           "debounce_min": 15, "resolved": True, "enabled": True}


def ev(eid, level, title, t, kind="gps"):
    return {"id": eid, "t": t, "kind": kind, "level": level, "title": title, "data": {"subject": "fix"}}


class RouterRestartTest(_TempData):
    def test_open_problem_survives_restart(self):
        clock = [100.0]
        wall = [1_800_000_000.0]
        first = notify.ChannelRouter(CHANNEL, clock=lambda: clock[0], wall=lambda: wall[0])
        self.assertEqual(len(first.offer(ev(1, "warn", "GPS-Fix verloren", wall[0]))), 1)
        saved = json.loads(json.dumps(first.export_state()))
        # Neustart: monotone Uhr beginnt neu, Uhrzeit läuft weiter.
        clock[0] = 5.0
        wall[0] += 120
        second = notify.ChannelRouter(CHANNEL, clock=lambda: clock[0], wall=lambda: wall[0])
        second.import_state(saved)
        self.assertEqual(second.offer(ev(2, "warn", "GPS-Fix verloren", wall[0])), [])   # kein doppelter Alarm
        resolved = second.offer(ev(3, "info", "GPS-Fix wieder da", wall[0], kind="gps"))
        self.assertEqual(len(resolved), 1)
        self.assertTrue(resolved[0]["resolved"])
        self.assertIn("Dauer 2 min", resolved[0]["title"])

    def test_notifier_stores_and_loads_state(self):
        notifier = notify.Notifier()
        router = notify.ChannelRouter(CHANNEL)
        router.offer(ev(1, "warn", "GPS-Fix verloren", time.time()))
        notifier.routers[CHANNEL["id"]] = router
        notifier._save_states(force=True)
        again = notify.Notifier()
        fresh = notify.ChannelRouter(CHANNEL)
        again._load_state(CHANNEL["id"], fresh)
        self.assertEqual(fresh.state["fix"]["notified"] if "fix" in fresh.state else
                         next(iter(fresh.state.values()))["notified"], "warn")

    def test_garbage_state_is_ignored(self):
        router = notify.ChannelRouter(CHANNEL)
        self.assertEqual(router.import_state({"a": "kaputt", "b": {"last_sent": "nein", "notified": "x"}}), 1)
        self.assertIsNone(router.state["b"]["notified"])
        self.assertEqual(router.import_state(["keine", "map"]), 0)


class ClientAlarmRestartTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.now = [1000.0]
        self.watch = statewatch.StateWatcher(lambda *a, **k: self.sent.append(a), clock=lambda: self.now[0])

    def measure(self, ip, offset, count):
        self.watch.clients({ip: {"measurable": True, "offset": offset, "count": count}}, 100)

    def test_restored_alarm_is_not_repeated_and_resolves(self):
        ip = "192.0.2.5"
        self.assertEqual(self.watch.restore_client_alarms([ip]), 1)
        self.watch.clients({}, 100)                   # Client-Liste nach dem Start noch leer
        self.assertEqual(self.sent, [])
        self.measure(ip, 0.5, 1)
        self.measure(ip, 0.5, 2)
        self.assertEqual(self.sent, [])               # weicht noch ab: kein zweiter Alarm
        self.measure(ip, 0.001, 3)
        self.measure(ip, 0.001, 4)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("wieder im Rahmen", self.sent[0][2])
        self.assertEqual(self.watch.client_alarm_ips(), [])

    def test_restored_alarm_closes_after_grace(self):
        self.watch.restore_client_alarms(["192.0.2.6"])
        self.now[0] += statewatch.CLIENT_RESTORE_GRACE + 1
        self.watch.clients({}, 100)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("beendet", self.sent[0][2])


# --- Dashboard (JS) -------------------------------------------------------------------------------------

@unittest.skipUnless(shutil.which("node"), "node fehlt")
class FrontendTest(unittest.TestCase):
    def run_js(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dom.mjs").write_text(DOM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            script.write_text('import { text, withAttr, ctx } from "./dom.mjs";\n' + body, encoding="utf-8")
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60,
                                    env={**os.environ, "TZ": "UTC"})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_hanging_request_ends_with_timeout(self):
        out = self.run_js(f"""
const keepAlive = setInterval(() => {{}}, 1000);  // Node: Zeitgeber von AbortSignal.timeout halten den Prozess nicht
globalThis.fetch = (url, opts) => new Promise((resolve, reject) => {{
  opts?.signal?.addEventListener("abort", () => reject(opts.signal.reason || new DOMException("x", "AbortError")));
}});
const util = await import({mod("util.js")});
const res = {{ limit: util.API_TIMEOUT_MS }};
const started = Date.now();
try {{ await util.apiGet("/api/status", {{ timeout: 80 }}); res.get = "ok"; }} catch (e) {{ res.get = e.message; res.status = e.status; }}
try {{ await util.apiPost("/api/settings", {{}}, {{ timeout: 80 }}); res.post = "ok"; }} catch (e) {{ res.post = e.message; }}
res.ms = Date.now() - started;
clearInterval(keepAlive);
console.log(JSON.stringify(res));
""")
        self.assertIn("Zeitüberschreitung", out["get"])
        self.assertIn("Zeitüberschreitung", out["post"])
        self.assertEqual(out["status"], 0)
        self.assertLess(out["ms"], 5000)
        self.assertLessEqual(out["limit"], 30000)

    def test_unreadable_success_is_not_saved(self):
        out = self.run_js(f"""
let reply = "";
globalThis.fetch = async () => new Response(reply, {{ status: 200, headers: {{ "Content-Type": "text/html" }} }});
const util = await import({mod("util.js")});
const res = {{}};
for (const [name, body] of [["empty", ""], ["html", "<!doctype html><title>Portal</title>"], ["json", '{{"ok": true}}']]) {{
  reply = body;
  try {{ res["post_" + name] = JSON.stringify(await util.apiPost("/api/settings", {{}})); }} catch (e) {{ res["post_" + name] = "Fehler: " + e.message; }}
  try {{ res["get_" + name] = JSON.stringify(await util.apiGet("/api/status")); }} catch (e) {{ res["get_" + name] = "Fehler: " + e.message; }}
}}
console.log(JSON.stringify(res));
""")
        for name in ("empty", "html"):
            self.assertTrue(out[f"post_{name}"].startswith("Fehler: Unerwartete Antwort des Servers"), out)
            self.assertTrue(out[f"get_{name}"].startswith("Fehler: Unerwartete Antwort des Servers"), out)
        self.assertEqual(json.loads(out["post_json"]), {"ok": True})
        self.assertEqual(json.loads(out["get_json"]), {"ok": True})

    def test_large_offsets_are_structured(self):
        out = self.run_js(f"""
const util = await import({mod("util.js")});
console.log(JSON.stringify({{ years: util.fmtSeconds(-1790000000), min: util.fmtSeconds(150, 3, true),
  hours: util.fmtSeconds(7322), small: util.fmtSeconds(1.5), edge: util.fmtSeconds(119.5) }}));
""")
        self.assertEqual(out["years"], "−20.717 d 14 h")
        self.assertEqual(out["min"], "+2 min 30 s")
        self.assertEqual(out["hours"], "2 h 2 min")
        self.assertEqual(out["small"], "1,5 s")
        self.assertEqual(out["edge"], "119,5 s")

    def test_pages_show_error_instead_of_endless_loading(self):
        out = self.run_js(f"""
const err = {{ status: 500, message: "HTTP 500" }};
const failing = ctx({{ dataError: () => err, status: {{ system: {{ time: 1783000000 }}, tracking: {{}}, clients: [],
  serverstats: {{}}, gps: {{ enabled: true }}, config: {{}}, sources: [], ui: {{}} }} }});
const settings = await import({mod("pages/settings.js")});
const hardware = await import({mod("pages/hardware.js")});
const gnss = await import({mod("pages/gnss.js")});
const gpsq = await import({mod("pages/gpsquality.js")});
const gps = await import({mod("pages/gps.js")});
const res = {{
  settings: text(settings.render(failing)), hardware: text(hardware.render(failing)),
  holdover: text(gnss.holdoverCard(failing)), gnss: text(gnss.gnssCard(failing)),
  antenna: text(gpsq.antennaCard(failing)), role: text(gpsq.roleCard(failing)), gps: text(gps.render(failing)),
  reception: text(gpsq.receptionCard(failing)),
  loading: text(settings.render(ctx())),
}};
// Einstellungen geladen, nur der DNS-Zustand scheitert: Abschnitt DNS zeigt den Fehler.
const schema = {json.dumps(settings.public_schema())};
const dnsFailing = ctx({{ data: (key) => key === "settings" ? schema : undefined,
  dataError: (key) => key === "dns" ? err : null, uiState: {{ settings: {{ tab: "quellen" }} }}, subpath: "s=quellen" }});
res.dns = text(settings.render(dnsFailing));
console.log(JSON.stringify(res));
""")
        for name in ("settings", "hardware", "holdover", "gnss", "antenna", "role", "gps", "reception"):
            with self.subTest(page=name):
                self.assertIn("nicht laden", out[name])
                self.assertIn("HTTP 500", out[name])
                self.assertNotIn("Wird geladen", out[name])
                self.assertNotIn("wird geladen", out[name])
        self.assertIn("Zustand nicht laden", out["dns"].replace("den Zustand nicht laden", "Zustand nicht laden"))
        self.assertNotIn("Zustand wird geladen", out["dns"])
        self.assertIn("Wird geladen", out["loading"])


class LayoutCssTest(unittest.TestCase):
    """Regeln, die der UI-Rundgang im Browser nachmisst (tests/ui/tour.js, layoutFixChecks)."""

    CSS = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")

    def rule(self, selector):
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", self.CSS)
        self.assertIsNotNone(match, selector)
        return match.group(1)

    def test_long_names_wrap(self):
        for selector in (".verdict-title h2", ".hint-title", ".hint-text"):
            self.assertIn("overflow-wrap: anywhere", self.rule(selector), selector)

    def test_focus_not_hidden_behind_bottom_bar(self):
        blocks = re.findall(r"@media \(max-width: 640px\) \{(.*?)\n\}", self.CSS, re.S)
        self.assertTrue(any("scroll-padding-bottom" in block and ".bottombar" in block for block in blocks))

    def test_kv_rows_have_max_width(self):
        self.assertIn("max-width", self.rule(".kv-list"))


if __name__ == "__main__":
    unittest.main()
