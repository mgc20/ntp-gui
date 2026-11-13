"""Sicherung und Wiederherstellung (1.6, T5): Rundreise, keine Position, keine Geheimnisse,
bösartige Archive, Rechte und CSRF am echten HTTP-Handler.

Testkoordinaten: München, Marienplatz (Beispielort des Datenschutz-Wächters).
"""

import base64
import gzip
import hashlib
import http.client
import io
import json
import os
import shutil
import sqlite3
import struct
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import apikeys  # noqa: E402
import autocal  # noqa: E402
import backup  # noqa: E402
import clientinfo  # noqa: E402
import clientmon  # noqa: E402
import clients3  # noqa: E402
import events  # noqa: E402
import gnssguard  # noqa: E402
import gpsquality  # noqa: E402
import history  # noqa: E402
import notify  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import timeline  # noqa: E402

LAT, LON, ALT = 48.137154, 11.576124, 519.25
TOKENS = ("tk_TESTTOKEN_ntfy_4711", "GOTIFY_TEST_TOKEN_0815", "WEBHOOKSECRET4242", "geheimespasswort",
          "zeit_thema_geheim")
DOH = "https://dns.example.org/dns-query/abc123geheim"


def _reset_modules() -> None:
    store.close_all()
    events._STATE["ready_for"] = None
    notify._READY["db"] = None
    apikeys._READY["db"] = None
    apikeys.clear_cache()
    gnssguard._READY["for"] = None
    gpsquality._READY["for"] = None
    clientinfo._META_CACHE.update(t=0.0, data=None)
    clients3._drop_group_cache()
    clients3._drop_rule_cache()
    backup.discard()


class _DataDir:
    """Eigenes Datenverzeichnis je Test (settings.DATA_DIR, settings.json, Datenbank)."""

    def use_dir(self, path: str) -> None:
        _reset_modules()
        os.makedirs(path, exist_ok=True)
        for patch in getattr(self, "_dir_patches", []):
            patch.stop()
        self._dir_patches = [mock.patch.object(settings, "DATA_DIR", path),
                             mock.patch.object(settings, "SETTINGS_FILE", os.path.join(path, "settings.json"))]
        for patch in self._dir_patches:
            patch.start()
        self.data_dir = path

    def stop_dirs(self) -> None:
        _reset_modules()
        for patch in getattr(self, "_dir_patches", []):
            patch.stop()
        self._dir_patches = []


def populate(now: float) -> dict:
    """Ein Datenverzeichnis wie im Betrieb – mit Position und Geheimnissen an allen Stellen, wo sie liegen."""
    settings.save({"web_title": "Testuhr Keller", "gps_offset": 0.1234, "gps_delay": 0.05,
                   "allow_networks": ["192.168.1.0/24"], "dns_doh": [DOH]})
    settings.set_credentials("admin", TOKENS[3])
    autocal.save({"version": 1, "changes": [
        {"id": 1, "t": now - 86400, "kind": "auto", "old_offset": 0.1, "new_offset": 0.1234, "reason": "Messung",
         "lat": LAT, "position": {"lon": LON}}],
        "observed": {"offset": 0.1234, "since": now - 3600, "fp": "x"}, "last_decision": None,
        "last_tick": now - 60, "last_suggestion": None, "pending": None, "no_fast": None})
    store.migrate("history", history._SCHEMA)
    rows = []
    for i in range(400):
        t = int(now) - (400 - i) * 300
        sample = {"t": t, "offset": 1e-5 * (i % 7), "rms": 2e-6, "freq": -3.25, "stratum": 1, "served": 1000 + i,
                  "sources": {"ptbtime1.ptb.de": {"o": 1e-4, "s": "*", "k": "^", "j": 2e-5},
                              "GPS": {"o": 3e-4, "s": "+", "k": "#", "j": 1e-4}},
                  "gps": {"used": 8, "seen": 12, "hdop": 0.9, "snr": 33.5, "mode": 3, "cn4": 41.0}}
        if i == 5:
            sample["gps"].update(lat=LAT, lon=LON, alt=ALT, sky=[{"az": 123, "el": 45}])
            sample["lat"] = LAT
        rows.append((t, json.dumps(sample, separators=(",", ":"))))
    with store.transaction() as conn:
        conn.executemany("INSERT INTO samples(t, json) VALUES(?, ?)", rows)
        conn.execute("INSERT INTO samples_5m(b, t, json) VALUES(?, ?, ?)",
                     (int(now) // 300, int(now), json.dumps({"t": int(now), "offset": 1e-5})))
        # Ein gelöschter Messpunkt mit Position: bleibt in freien Seiten von ntp-gui.db stehen.
        conn.execute("INSERT INTO samples(t, json) VALUES(?, ?)",
                     (int(now) - 10, json.dumps({"t": int(now) - 10, "lat": LAT, "lon": LON})))
        conn.execute("DELETE FROM samples WHERE t = ?", (int(now) - 10,))
    events.emit("gps", "warn", "GPS-Fix verloren", {"satellites": 3})
    events.emit("gps", "info", f"Position {LAT}, {LON} gelernt", {"lat": LAT, "lon": LON, "elevation": 30})
    events.emit("settings", "info", "Einstellungen geändert: web_title", {"keys": ["web_title"]})
    clients3._migrate(store)
    with store.transaction() as conn:
        for n, ip in enumerate(("192.168.1.20", "192.168.1.21", "fd00::5")):
            conn.execute("INSERT INTO clientmon_clients(ip, data, updated) VALUES(?, ?, ?)",
                         (ip, json.dumps({"requests": 10 + n, "offset": 0.001, "first_seen": now - 9000,
                                          "last_seen": now - 5}), now))
            conn.execute("INSERT INTO clientmon_samples(ip, t, offset, poll, version, interval) "
                         "VALUES(?, ?, ?, ?, ?, ?)", (ip, now - 60, 0.0012, 6, 4, 64.0))
        conn.execute("INSERT INTO client_hourly(ip, hour, n, med, p95, lo, hi) VALUES(?, ?, ?, ?, ?, ?, ?)",
                     ("192.168.1.20", int(now // 3600) - 2, 60, 0.001, 0.002, -0.001, 0.003))
        conn.execute("INSERT INTO client_inventory(key, first_seen) VALUES(?, ?)", ("ip:192.168.1.20", now - 90000))
        conn.execute("INSERT INTO client_rules(ip, silent_h, offset_ms, offset_min, mute, expect, state, updated) "
                     "VALUES(?, ?, ?, ?, ?, ?, ?, ?)", ("192.168.1.21", 12.0, 50.0, 3, 0, "", "{}", now))
    clientinfo.set_meta("192.168.1.20", "Drucker Flur", "neben der Tür")
    clientinfo.set_meta("fd00::5", "Kamera", "")
    clients3.save_group({"name": "IoT", "network": "10.0.30.0/24"})
    clients3.save_group({"name": "Kameras", "network": "192.168.1.0/28"})
    notify.save_channel({"name": "Handy", "type": "ntfy", "url": "https://ntfy.sh", "topic": TOKENS[4],
                         "secret": TOKENS[0], "min_level": "warn"})
    notify.save_channel({"name": "Gotify", "type": "gotify", "url": "https://gotify.example.org",
                         "secret": TOKENS[1]})
    notify.save_channel({"name": "Hausautomation", "type": "webhook",
                         "url": f"https://ha.example.org/api/webhook/{TOKENS[2]}"})
    notify.save_channel({"name": "Ohne Token", "type": "webhook", "url": "https://hooks.example.org"})
    _key_id, api_token = apikeys.create("Skript", "admin")
    # Tabellen, die nie in die Sicherung gehören: Position, Satellitenwinkel.
    gnssguard.save("position", {"lat": LAT, "lon": LON, "alt": ALT})
    gpsquality._ensure() if hasattr(gpsquality, "_ensure") else store.migrate("gpsquality", gpsquality._SCHEMA)
    with store.transaction() as conn:
        conn.execute("INSERT INTO antenna_tests(t, json) VALUES(?, ?)",
                     (now, json.dumps({"sats": [{"prn": 5, "az": 123.5, "el": 45.25}], "lat": LAT})))
        conn.execute("CREATE TABLE IF NOT EXISTS pos_test (lat REAL, lon REAL)")
        conn.execute("INSERT INTO pos_test VALUES(?, ?)", (LAT, LON))
    return {"api_token": api_token}


def table_rows(table: str, columns: str, order: str) -> list[tuple]:
    return store.query(f"SELECT {columns} FROM {table} ORDER BY {order}")


def snapshot() -> dict:
    """Inhalte, die eine Rundreise unverändert überstehen müssen (ohne ausgeschlossene Spalten)."""
    return {
        "samples": table_rows("samples", "t, json", "t"),
        "samples_5m": table_rows("samples_5m", "b, t, json", "b"),
        "events": table_rows("events", "t, kind, level, title, data, source", "id"),
        "clientmon_clients": table_rows("clientmon_clients", "ip, data, updated", "ip"),
        "clientmon_samples": table_rows("clientmon_samples", "ip, t, offset, poll, version, interval", "ip, t"),
        "clientmon_meta": table_rows("clientmon_meta", "ip, name, note, updated", "ip"),
        "client_groups": table_rows("client_groups", "id, name, network, updated", "id"),
        "client_rules": table_rows("client_rules", "*", "ip"),
        "client_hourly": table_rows("client_hourly", "*", "ip, hour"),
        "client_inventory": table_rows("client_inventory", "*", "key"),
        "notify_channels": table_rows("notify_channels", "id, name, type, min_level, kinds, debounce_min, "
                                      "rate_per_hour, resolved, created, updated", "id"),
    }


def tar_bytes(members: list, compress=True) -> bytes:
    """members: (TarInfo, bytes|None) – Archiv bauen, wie es ein Angreifer täte."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz" if compress else "w", format=tarfile.PAX_FORMAT) as tar:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)
    return raw.getvalue()


def regular(name: str, data: bytes) -> tuple:
    info = tarfile.TarInfo(name)
    info.mode = 0o600
    return info, data


class BackupTestBase(_DataDir, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ntpgui-backup-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(self.stop_dirs)
        self.now = time.time()
        self.use_dir(os.path.join(self.tmp, "alt"))
        self.secrets = populate(self.now)
        self.before = snapshot()

    def make_backup(self) -> bytes:
        path = os.path.join(self.tmp, "sicherung.tar.gz")
        backup.create(path, "1.6.0-test")
        with open(path, "rb") as handle:
            return handle.read()

    def unpacked(self, data: bytes) -> dict[str, bytes]:
        out = {}
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                out[member.name] = tar.extractfile(member).read()
        return out

    def parts_from(self, data: bytes) -> dict[str, bytes]:
        return self.unpacked(data)

    def rebuild(self, parts: dict[str, bytes], manifest_patch=None, fix_hashes=True, extra=()) -> bytes:
        """Archiv aus (veränderten) Teilen; Prüfsummen im Manifest auf Wunsch passend."""
        manifest = json.loads(parts[backup.MANIFEST])
        if fix_hashes:
            for item in manifest["parts"]:
                item["sha256"] = hashlib.sha256(parts[item["name"]]).hexdigest()
                item["size"] = len(parts[item["name"]])
        if manifest_patch:
            manifest_patch(manifest)
        members = [regular(backup.MANIFEST, json.dumps(manifest).encode())]
        members += [regular(name, parts[name]) for name in backup.PARTS if name != backup.MANIFEST]
        members += list(extra)
        return tar_bytes(members)

    def assert_rejected(self, data: bytes, *words: str):
        settings_before = Path(settings.SETTINGS_FILE).read_bytes()
        with self.assertRaises(backup.RestoreError) as caught:
            backup.stage_upload(io.BytesIO(data), len(data))
        text = str(caught.exception)
        for word in words:
            self.assertIn(word, text)
        # Nichts geschrieben: Daten wie vorher, kein Upload liegen geblieben, nichts außerhalb.
        self.assertEqual(snapshot(), self.before)
        self.assertEqual(Path(settings.SETTINGS_FILE).read_bytes(), settings_before)
        self.assertEqual(os.listdir(backup.staging_root()), [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil")))
        self.assertFalse(os.path.exists(os.path.join(self.data_dir, "evil")))
        return text

    def good_parts(self) -> dict[str, bytes]:
        return self.parts_from(self.make_backup())


class RoundTripTest(BackupTestBase):
    def test_round_trip_into_fresh_data_dir(self):
        data = self.make_backup()
        before_settings = settings.export_values()["values"]
        before_autocal = autocal.load()
        self.use_dir(os.path.join(self.tmp, "neu"))  # „frischer Container“
        staged = backup.stage_upload(io.BytesIO(data), len(data))
        preview = staged["preview"]
        self.assertEqual(preview["devices"], 3)
        self.assertEqual(preview["names"], 2)
        self.assertEqual(preview["groups"], 2)
        self.assertEqual(preview["rules"], 1)
        self.assertEqual(preview["channels"]["count"], 4)
        self.assertEqual({c["name"] for c in preview["channels"]["reenter"]}, {"Handy", "Gotify", "Hausautomation"})
        self.assertGreater(preview["history"]["days"], 1.3)
        self.assertEqual([r["key"] for r in preview["settings"]["reenter"]], ["dns_doh"])
        self.assertAlmostEqual(preview["calibration"]["last_change"], self.now - 86400, places=1)
        # Die Vorschau ändert nichts.
        self.assertFalse(os.path.exists(settings.SETTINGS_FILE))
        result = backup.apply(staged["token"], "1.6.0", emit=events.emit)
        self.assertTrue(result["ok"])
        after = snapshot()
        for table in self.before:
            expected = self.before[table]
            if table in ("samples", "samples_5m"):
                expected = [row[:-1] + (backup.sample_json(row[-1]),) for row in expected]
            if table == "events":
                expected = [row[:3] + (backup.scrub_text(row[3]), backup.scrub_json(row[4]), row[5])
                            for row in expected]
                # Dazu kommt „Wiederhergestellt aus Sicherung vom …“ (und nichts sonst).
                self.assertEqual(after[table][:len(expected)], expected)
                self.assertTrue(after[table][-1][3].startswith("Wiederhergestellt aus Sicherung vom "))
                continue
            self.assertEqual(after[table], expected, table)
        # Nur die Messpunkte mit Position wurden verändert – sonst alles bitgenau gleich.
        changed = [a for a, b in zip(self.before["samples"], after["samples"]) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertNotIn("lat", after["samples"][5][1])
        expected_settings = {k: v for k, v in before_settings.items() if k != "dns_doh"}
        self.assertEqual(settings.export_values()["values"], expected_settings)
        self.assertIsNone(settings.stored_credentials(), "Passwort darf nicht mitkommen")
        restored = autocal.load()
        self.assertEqual(restored["changes"][0]["new_offset"], before_autocal["changes"][0]["new_offset"])
        self.assertNotIn("lat", restored["changes"][0])
        self.assertNotIn("position", restored["changes"][0])
        self.assertEqual(restored["observed"], before_autocal["observed"])
        # Kanäle: ohne Token; in einer neuen Instanz alle ausgeschaltet; Webhook nur noch bis zum Host.
        channels = {c["name"]: c for c in notify._load_all()}
        self.assertEqual(channels["Handy"]["secret"], "")
        self.assertEqual(channels["Handy"]["topic"], "")  # ntfy-Thema zählt als Geheimnis
        self.assertFalse(channels["Handy"]["enabled"])
        self.assertFalse(channels["Ohne Token"]["enabled"])  # neu hier: erst nach Prüfung einschalten
        self.assertEqual(channels["Hausautomation"]["url"], "https://ha.example.org")
        self.assertFalse(channels["Hausautomation"]["enabled"])
        # API-Schlüssel und GNSS-Zustand kommen nicht mit.
        self.assertEqual(apikeys.list(), [])
        self.assertEqual(gnssguard.load("position"), {})
        # Vorher automatisch gesichert; Upload aufgeräumt.
        self.assertTrue(os.path.isfile(os.path.join(backup.backup_dir(), result["before"])))
        self.assertEqual(os.listdir(backup.staging_root()), [])
        self.assertIn("Kanal „Gotify“: Token", result["reenter"])
        self.assertIn("Kanal „Handy“: Token und Thema", result["reenter"])
        self.assertTrue(result["restart"])

    def test_restore_keeps_tables_outside_allowlist(self):
        data = self.make_backup()
        staged = backup.stage_upload(io.BytesIO(data), len(data))
        backup.apply(staged["token"])
        self.assertEqual(len(apikeys.list()), 1)
        self.assertEqual(gnssguard.load("position")["lat"], LAT)
        self.assertIsNotNone(settings.stored_credentials())
        self.assertEqual(settings.export_values()["values"]["dns_doh"], [DOH])

    def test_old_events_do_not_notify(self):
        data = self.make_backup()
        self.use_dir(os.path.join(self.tmp, "neu"))
        notify.NOTIFIER.last_id = 0
        staged = backup.stage_upload(io.BytesIO(data), len(data))
        with mock.patch.object(notify.NOTIFIER, "_save_position"):
            backup.apply(staged["token"])
        self.assertGreaterEqual(notify.NOTIFIER.last_id, events.max_id())

    def test_token_only_once_and_expires(self):
        data = self.make_backup()
        staged = backup.stage_upload(io.BytesIO(data), len(data))
        backup.apply(staged["token"])
        with self.assertRaises(backup.RestoreError):
            backup.apply(staged["token"])
        staged = backup.stage_upload(io.BytesIO(data), len(data))
        backup.cleanup_staging(now=time.monotonic() + backup.PENDING_TTL + 1)
        with self.assertRaises(backup.RestoreError):
            backup.apply(staged["token"])
        self.assertEqual(os.listdir(backup.staging_root()), [])

    def test_stored_backups_rotate(self):
        for day in range(9):
            backup.save_local(backup.NIGHTLY_PREFIX, backup.KEEP_NIGHTLY, now=self.now - day * 86400)
        names = [item["name"] for item in backup.stored()]
        self.assertEqual(len(names), backup.KEEP_NIGHTLY)
        self.assertIsNotNone(backup.stored_path(names[0]))
        self.assertIsNone(backup.stored_path("../settings.json"))
        self.assertIsNone(backup.stored_path("nacht-20260101.tar.gz/../x"))

    def test_nightly_due_only_when_enabled_and_once(self):
        night = time.mktime((2026, 11, 8, backup.NIGHTLY_HOUR, 10, 0, 0, 0, -1))
        self.assertFalse(backup.nightly_due(False, night))
        self.assertTrue(backup.nightly_due(True, night))
        self.assertFalse(backup.nightly_due(True, night + 3 * 3600))
        backup.save_local(backup.NIGHTLY_PREFIX, backup.KEEP_NIGHTLY, now=night)
        self.assertFalse(backup.nightly_due(True, night + 600))
        self.assertIs(settings.FIELDS["backup_nightly"]["default"], False)


class NoLeakTest(BackupTestBase):
    def test_no_position_no_secrets_in_backup(self):
        data = self.make_backup()
        parts = self.unpacked(data)
        self.assertEqual(set(parts), set(backup.PARTS))
        blob = b"".join(parts.values()) + gzip.decompress(data)
        needles = {
            "Breite als Text": [b"48.137154", b"48.13715", b"48.1372", b"48.137", b"48,137"],
            "Länge als Text": [b"11.576124", b"11.57612", b"11.5761", b"11.576", b"11,576"],
            "Höhe": [b"519.25"],
        }
        for value in (LAT, LON, ALT, 123.5, 45.25):
            for order in (">d", "<d"):
                needles.setdefault("binär", []).append(struct.pack(order, value))
        for token in TOKENS + (self.secrets["api_token"], DOH, "abc123geheim", "pbkdf2_sha256"):
            needles.setdefault("Geheimnis", []).append(token.encode())
        for what, items in needles.items():
            for needle in items:
                self.assertNotIn(needle, blob, f"{what}: {needle!r} steht in der Sicherung")
        for table in (b"gnss_state", b"antenna_tests", b"api_keys", b"gps_bound", b"pos_test", b"holdover"):
            self.assertNotIn(table, parts[backup.DB_PART])
        self.assertNotIn(b"secret", parts[backup.DB_PART].replace(b"secret_set", b""))

    def test_dump_schema_is_exactly_the_allowlist(self):
        parts = self.unpacked(self.make_backup())
        path = os.path.join(self.tmp, "abzug.sqlite")
        with open(path, "wb") as handle:
            handle.write(parts[backup.DB_PART])
        conn = sqlite3.connect(path)
        try:
            objects = conn.execute("SELECT type, name FROM sqlite_master ORDER BY name").fetchall()
            self.assertEqual({o for o in objects}, {("table", t) for t in backup.ALLOWLIST})
            schema = {t: [(r[1], r[2]) for r in conn.execute(f'PRAGMA table_info("{t}")')] for t in backup.ALLOWLIST}
            self.assertEqual(schema, backup.allowlist_schema())
            self.assertEqual(conn.execute("PRAGMA freelist_count").fetchone()[0], 0)
        finally:
            conn.close()
        manifest = json.loads(parts[backup.MANIFEST])
        self.assertEqual(manifest["schema"]["dump"], backup.DUMP_SCHEMA)
        for item in manifest["parts"]:
            self.assertEqual(item["sha256"], hashlib.sha256(parts[item["name"]]).hexdigest())

    def test_allowlist_names_no_position_or_secret_columns(self):
        for table, columns in backup.allowlist_schema().items():
            for name, _kind in columns:
                self.assertFalse(backup._drop_key(name) and name != "secret_set", f"{table}.{name}")

    def test_sample_fast_matches_slow_path(self):
        samples = ['{"t":1,"offset":1e-5,"sources":{"a.b":{"o":1,"s":"*"}},"gps":{"used":3}}',
                   '{"t":2,"offset":2e-5,"sources":{"a.b":{"o":-1,"s":"+"}},"gps":{"used":null}}',
                   '{"t":1,"gps":{"used":3,"lat":48.1}}', '{"t":1,"sources":{"x":{"o":1,"el":30}}}',
                   '{"t":1,"sources":{"x":[1,2]}}', '{"t":{"lat":1}}', '{"t":1,"sources":{"x:1,":{"o":1}}}',
                   '{"t":1,"sources":{"x:2,":{"lat":1}}}', '{"t":1,"a\\"b":2}', '[1,2]']
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(backup.sample_fast(text), backup.sample_json(text))


class HistoryFieldsTest(BackupTestBase):
    """Felder, die der Verlauf schreibt (Messpunkt aus server.collect_sample, „z“ in samples_5m), überstehen
    Sicherung und Wiederherstellung vollständig – kein Feld geht still verloren."""

    def collected(self) -> dict:
        """Ein Messpunkt wie im Betrieb: mit Temperatur, Pi-Zustand, GPS und PTP."""
        import chrony
        import gps
        import pistate
        import ptp
        import thermal
        source = {"name": "GPS", "offset": 1e-4, "state": "*", "mode": "#", "std_dev": 2e-5}
        patches = [mock.patch.object(chrony, "tracking", return_value={
                       "system_time_offset": 1e-5, "rms_offset": 2e-6, "frequency_ppm": -3.25, "skew_ppm": 0.01,
                       "root_delay": 1e-4, "root_dispersion": 2e-4, "stratum": 1}),
                   mock.patch.object(chrony, "serverstats", return_value={"ntp_packets_received": 42}),
                   mock.patch.object(chrony, "clients", return_value=[{}]),
                   mock.patch.object(chrony, "merged_sources", return_value=[source]),
                   mock.patch.object(thermal.MONITOR, "sample", return_value=41.5),
                   mock.patch.object(pistate.MONITOR, "sample", return_value={}),
                   mock.patch.object(pistate, "severity", return_value=1),
                   mock.patch.object(gps, "enabled", return_value=True),
                   mock.patch.object(gps, "status", return_value={
                       "satellites_used": 8, "satellites_seen": 12, "hdop": 0.9, "snr_avg": 33.5, "mode": 3,
                       "cn0_top4": 41.0, "lat": LAT, "lon": LON}),
                   mock.patch.object(ptp, "enabled", return_value=True),
                   mock.patch.object(ptp, "status", return_value={
                       "offset_ns": 12, "meanPathDelay": 800, "log_metrics": {"freq_ppb": -5.0, "rms_ns": 9}}),
                   mock.patch.object(events, "emit")]
        for patch in patches:
            patch.start()
        try:
            return server.collect_sample()
        finally:
            for patch in reversed(patches):
                patch.stop()

    def write_history(self, base: int) -> history.History:
        """Ein 5-Minuten-Fenster über History.add/save: 7 gute Punkte, 3 Fehler (Offset 0,1 s), Pi gedrosselt."""
        sample = self.collected()
        self.assertEqual(sample["pi_state"], 1)
        self.use_dir(os.path.join(self.tmp, "quelle"))  # nur dieses Fenster im Verlauf
        hist = history.History(None, path=os.path.join(self.data_dir, "history.json.gz"))
        self.assertEqual(hist.backend, "sqlite")
        for i in range(10):
            hist.add(dict(sample, t=base + i * 10, offset=0.1 if i < 3 else 1e-5))
        self.assertTrue(hist.save(force=True))
        return hist

    def test_every_field_history_writes_is_in_the_allowlist(self):
        self.assertLessEqual(set(history._NUMERIC_TOP) | set(history._GROUPS) | {"t", "served", "sources", "z"},
                             backup._SAMPLE_TOP)
        self.assertEqual(backup._SAMPLE_Z, frozenset(timeline.CODES))
        base = (int(self.now) // 300 - 3) * 300
        self.write_history(base)
        rows = store.query("SELECT json FROM samples WHERE t >= ? UNION ALL "
                           "SELECT json FROM samples_5m WHERE b = ?", (base, base // 300))
        self.assertEqual(len(rows), 11)
        self.assertIn("z", json.loads(rows[-1][0]))
        for (text,) in rows:
            with self.subTest(text=text):
                self.assertTrue(backup._sample_ok(json.loads(text)), text)
                self.assertEqual(backup.sample_json(text), text)
                self.assertEqual(backup.sample_fast(text), text)
        # Die Position aus dem GPS-Status kommt gar nicht erst in den Verlauf (und damit nie in die Sicherung).
        self.assertNotIn("48.137", json.dumps(rows))

    def test_state_counts_and_pi_state_survive_round_trip(self):
        base = (int(self.now) // 300 - 3) * 300
        hist = self.write_history(base)
        before_5m = store.query("SELECT b, t, json FROM samples_5m WHERE b = ?", (base // 300,))
        self.assertEqual(json.loads(before_5m[0][2])["z"], {"c": 3, "g": 7})
        before_band = hist.band_counts(base, base + 299)
        self.assertEqual(timeline.bucket_state(before_band[base // 300]), "c")
        data = self.make_backup()
        self.use_dir(os.path.join(self.tmp, "neu"))
        backup.apply(backup.stage_upload(io.BytesIO(data), len(data))["token"])
        self.assertEqual(store.query("SELECT b, t, json FROM samples_5m WHERE b = ?", (base // 300,)), before_5m)
        restored = history.History(None, path=os.path.join(self.data_dir, "history.json.gz"))
        self.assertEqual(restored.band_counts(base, base + 299), before_band)
        pi = [json.loads(text).get("pi_state") for (text,) in
              store.query("SELECT json FROM samples WHERE t >= ? ORDER BY t", (base,))]
        self.assertEqual(pi, [1] * 10)

    def test_forged_state_counts_are_filtered(self):
        good = '{"t":1,"offset":1e-5,"z":{"g":20,"c":10},"pi_state":1}'
        self.assertEqual(backup.sample_json(good), good)
        self.assertEqual(backup.sample_fast(good), good)
        for forged, expected in (('{"t":1,"z":{"g":2,"lat":48.137154}}', {"t": 1, "z": {"g": 2}}),
                                 ('{"t":1,"z":{"g":"48.137154, 11.576124"}}', {"t": 1, "z": {"g": "[Position entfernt]"}}),
                                 ('{"t":1,"z":[48.137154,11.576124]}', {"t": 1}),
                                 ('{"t":1,"z":{"g":{"x":1}}}', {"t": 1, "z": {}})):
            with self.subTest(forged=forged):
                self.assertEqual(json.loads(backup.sample_json(forged)), expected)
                self.assertEqual(backup.sample_fast(forged), backup.sample_json(forged))

    def test_restore_drops_cached_daily_report(self):
        # Frische Installation nach 00:15 Uhr: Der (leere) Bericht für gestern gilt als abgeschlossen. Nach dem
        # Einspielen muss er aus dem wiederhergestellten Verlauf neu gerechnet werden, nicht erst nach Mitternacht.
        start, end = timeline.day_bounds(self.now)
        source = history.History(None, path=os.path.join(self.data_dir, "history.json.gz"))
        for i in range(12):
            source.add({"t": int(start) + 600 + i * 60, "offset": 1e-5,
                        "sources": {"GPS": {"o": 1e-4, "s": "*", "k": "#"}}})
        self.assertTrue(source.save(force=True))
        data = self.make_backup()
        self.use_dir(os.path.join(self.tmp, "leer"))
        hist = history.History(None, path=os.path.join(self.data_dir, "history.json.gz"))
        timeline.reset_cache()
        self.addCleanup(timeline.reset_cache)
        now = end + timeline.REPORT_SETTLE + 60
        self.assertEqual(timeline.cached_report(hist, now=now, wait=5.0)["samples"], 0)
        backup.apply(backup.stage_upload(io.BytesIO(data), len(data))["token"])
        report = timeline.cached_report(hist, now=now, wait=5.0)
        self.assertGreaterEqual(report["samples"], 12)
        self.assertEqual(report["samples"], timeline.daily_report(hist, start, end)["samples"])


class MaliciousArchiveTest(BackupTestBase):
    def test_path_traversal(self):
        parts = self.good_parts()
        self.assert_rejected(self.rebuild(parts, extra=[regular("../evil", b"x")]), "Pfad")
        self.assert_rejected(self.rebuild(parts, extra=[regular("teile/../../evil", b"x")]), "Pfad")

    def test_absolute_path(self):
        self.assert_rejected(self.rebuild(self.good_parts(), extra=[regular("/tmp/evil", b"x")]), "Pfad")

    def test_symlink(self):
        info = tarfile.TarInfo(backup.DB_PART)
        info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
        data = tar_bytes([regular(backup.MANIFEST, b"{}"), (info, None)])
        self.assert_rejected(data, "Link")

    def test_hardlink(self):
        info = tarfile.TarInfo(backup.SETTINGS_PART)
        info.type, info.linkname = tarfile.LNKTYPE, backup.MANIFEST
        self.assert_rejected(tar_bytes([regular(backup.MANIFEST, b"{}"), (info, None)]), "Link")

    def test_device_file(self):
        info = tarfile.TarInfo(backup.DB_PART)
        info.type, info.devmajor, info.devminor = tarfile.CHRTYPE, 1, 3
        self.assert_rejected(tar_bytes([(info, None)]), "Gerätedatei")

    def test_unknown_file_and_directory(self):
        self.assert_rejected(self.rebuild(self.good_parts(), extra=[regular("evil.sh", b"rm -rf /")]), "Unbekannte Datei")
        info = tarfile.TarInfo("teile")
        info.type = tarfile.DIRTYPE
        self.assert_rejected(tar_bytes([(info, None)]), "abgelehnt")

    def test_oversized_part(self):
        parts = self.good_parts()
        with mock.patch.dict(backup.PART_LIMITS, {backup.DB_PART: 4096}):
            self.assert_rejected(self.rebuild(parts), "zu groß")

    def test_upload_too_large(self):
        with mock.patch.object(backup, "MAX_UPLOAD", 1000):
            with self.assertRaises(backup.RestoreError) as caught:
                backup.stage_upload(io.BytesIO(b"x" * 2000), 2000)
        self.assertIn("zu groß", str(caught.exception))

    def test_wrong_checksum(self):
        parts = self.good_parts()
        same_size = dict(parts)
        same_size[backup.SETTINGS_PART] = parts[backup.SETTINGS_PART].replace(b"Testuhr", b"Fremdeu")
        self.assert_rejected(self.rebuild(same_size, fix_hashes=False), "Prüfsumme")
        # Andere Länge: fällt schon am Tar-Kopf auf, bevor der Teil geschrieben wird.
        parts[backup.SETTINGS_PART] = parts[backup.SETTINGS_PART].replace(b"Testuhr", b"Fremduhr")
        self.assert_rejected(self.rebuild(parts, fix_hashes=False), "Größe", "manifest.json")

    def test_newer_schema(self):
        parts = self.good_parts()

        def newer(manifest):
            manifest["schema"]["dump"] = backup.DUMP_SCHEMA + 1
        self.assert_rejected(self.rebuild(parts, newer), "neueren Version")

        def newer_settings(manifest):
            manifest["schema"]["settings"] = settings.SCHEMA_VERSION + 1
        self.assert_rejected(self.rebuild(parts, newer_settings), "neueren Version")

        def newer_format(manifest):
            manifest["format_version"] = backup.FORMAT_VERSION + 1
        self.assert_rejected(self.rebuild(parts, newer_format), "neueren Version")

    def test_gzip_bomb(self):
        # Ein Teil, der sich weit über das Limit entpacken würde – abgelehnt, ohne alles zu entpacken.
        zeros = b"\0" * (8 * 1024 * 1024)
        bomb = tar_bytes([regular(backup.MANIFEST, b"{}"), regular(backup.DB_PART, zeros)])
        self.assertLess(len(bomb), 64 * 1024)
        with mock.patch.object(backup, "MAX_UNPACKED", 1024 * 1024):
            self.assert_rejected(bomb, "Gzip-Bombe")
        with mock.patch.dict(backup.PART_LIMITS, {backup.DB_PART: 1024 * 1024}):
            self.assert_rejected(bomb, "zu groß")
        # Nur Nullen, kein Tar: kein gültiges Archiv.
        self.assert_rejected(gzip.compress(zeros), "fehlt")

    def test_one_gigabyte_part_rejected_before_writing(self):
        # T5: „1-GB-Datei wird abgelehnt, nichts wird geschrieben“ – ohne herabgesetzte Grenzen. Das Archiv
        # ist ein echtes .tar.gz (wenige MB) mit gültigem Manifest und 10^9 Byte Nullen als daten.sqlite.
        size = 10 ** 9
        self.assertGreater(size, backup.PART_LIMITS[backup.DB_PART])
        manifest = json.loads(self.good_parts()[backup.MANIFEST])
        for item in manifest["parts"]:
            if item["name"] == backup.DB_PART:
                item["size"] = size
        path = os.path.join(self.tmp, "gb.tar.gz")
        zero_chunk = b"\0" * (1024 * 1024)

        class Zeros(io.RawIOBase):
            left = size

            def readable(self):
                return True

            def readinto(self, buffer):
                n = min(len(buffer), self.left, len(zero_chunk))
                buffer[:n] = zero_chunk[:n]
                self.left -= n
                return n

        with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT, compresslevel=1) as tar:
            data = json.dumps(manifest).encode()
            info, _ = regular(backup.MANIFEST, data)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            info, _ = regular(backup.DB_PART, b"")
            info.size = size
            tar.addfile(info, io.BufferedReader(Zeros(), 1024 * 1024))
        self.assertLess(os.path.getsize(path), 8 * 1024 * 1024)
        with open(path, "rb") as handle:
            data = handle.read()

        # Größter Stand des Upload-Ordners: gemessen direkt vor dem Aufräumen (dann liegt dort alles, was
        # geschrieben wurde – Upload und entpackte Teile).
        peak = []
        real_rmtree = shutil.rmtree

        def measure(target, *args, **kwargs):
            total = 0
            for root, _dirs, files in os.walk(target):
                total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
            peak.append(total)
            return real_rmtree(target, *args, **kwargs)

        with mock.patch.object(backup.shutil, "rmtree", side_effect=measure):
            self.assert_rejected(data, backup.DB_PART, "zu groß")
        self.assertTrue(peak)
        self.assertLess(max(peak), len(data) + 64 * 1024)  # nur der Upload selbst, keine entpackten Daten

    def test_db_limit_is_realistic(self):
        # Grenze aus der Messung (30 Tage Verlauf plus Client-Daten an ihren Obergrenzen ≈ 352 MiB) mit
        # Reserve, aber deutlich unter 1 GB; ein größerer HISTORY_DAYS hebt sie an.
        self.assertGreaterEqual(backup.db_limit(30), 400 * backup.MIB)
        self.assertLess(backup.db_limit(30), 10 ** 9)
        self.assertEqual(backup.db_limit(1), backup.db_limit(30))
        self.assertGreater(backup.db_limit(365), 2 * 1024 * backup.MIB)
        self.assertEqual(backup.PART_LIMITS[backup.DB_PART], backup.upload_db_limit())
        self.assertEqual(backup.upload_db_limit(30), backup.db_limit(30))

    def test_upload_limit_stays_below_one_gigabyte(self):
        # T5 auch bei großem HISTORY_DAYS (bis 3650 Tage erlaubt): Hochgeladenes bleibt unter 10^9 Byte.
        for days in (30, 87, 90, 365, 3650):
            self.assertLess(backup.upload_db_limit(days), 10 ** 9, days)
        limits = {**backup.PART_LIMITS, backup.DB_PART: backup.upload_db_limit(3650)}
        self.assertLess(sum(limits.values()) + backup.MIB, 10 ** 9)
        self.assertLess(backup.MAX_UNPACKED, 10 ** 9)
        # Was durch MAX_UPLOAD passt (echte Sicherungen packen 2,5 bis 4,5 : 1), liegt unter der Deckelung.
        self.assertGreaterEqual(backup.UPLOAD_DB_CAP, backup.MAX_UPLOAD * 4)

    def test_own_backup_may_exceed_upload_limit(self):
        # Die eigene automatische Sicherung (Zurückspielen) nutzt db_limit() ohne Deckel.
        parts = self.good_parts()
        data = self.rebuild(parts)
        archive = os.path.join(self.tmp, "eigen.tar.gz")
        with open(archive, "wb") as handle:
            handle.write(data)
        small = len(parts[backup.DB_PART]) - 1
        with mock.patch.dict(backup.PART_LIMITS, {backup.DB_PART: small}), \
                mock.patch.object(backup, "db_limit", return_value=small + 4096):
            for own, expect_ok in ((False, False), (True, True)):
                workdir = tempfile.mkdtemp(dir=self.tmp)
                if expect_ok:
                    self.assertIn(backup.DB_PART, backup.unpack(archive, workdir, own=own))
                else:
                    with self.assertRaises(backup.RestoreError) as caught:
                        backup.unpack(archive, workdir, own=own)
                    self.assertIn("zu groß", str(caught.exception))

    def test_too_little_free_space(self):
        parts = self.good_parts()
        usage = shutil.disk_usage(self.tmp)
        tight = usage._replace(free=backup.DISK_RESERVE + 1024)
        with mock.patch.object(backup.shutil, "disk_usage", return_value=tight):
            text = self.assert_rejected(self.rebuild(parts), "Zu wenig freier Speicher", "MiB")
        self.assertIn(backup.DB_PART, text)
        # Kleine Teile werden in KiB genannt, nicht auf „1 MiB“ aufgerundet.
        self.assertRegex(text, r"braucht \d+ KiB")

    def test_own_backup_ignores_reserve_but_needs_room(self):
        # Zurückspielen der eigenen Sicherung: keine DISK_RESERVE, aber der Teil selbst muss passen.
        data = self.rebuild(self.good_parts())
        archive = os.path.join(self.tmp, "eigen.tar.gz")
        with open(archive, "wb") as handle:
            handle.write(data)
        usage = shutil.disk_usage(self.tmp)
        tight = usage._replace(free=backup.DISK_RESERVE // 2)
        with mock.patch.object(backup.shutil, "disk_usage", return_value=tight):
            with self.assertRaises(backup.RestoreError):
                backup.unpack(archive, tempfile.mkdtemp(dir=self.tmp))
            self.assertEqual(len(backup.unpack(archive, tempfile.mkdtemp(dir=self.tmp), own=True)),
                             len(backup.PARTS))
        with mock.patch.object(backup.shutil, "disk_usage", return_value=usage._replace(free=100)):
            with self.assertRaises(backup.RestoreError) as caught:
                backup.unpack(archive, tempfile.mkdtemp(dir=self.tmp), own=True)
        self.assertIn("frei sind nur 0 KiB", str(caught.exception))

    def test_compression_ratio(self):
        # 40 MiB Nullen packen sich auf wenige KiB – weit über dem Verhältnis echter Sicherungen (2,5–4,5).
        parts = self.good_parts()
        parts[backup.DB_PART] = b"\0" * (40 * 1024 * 1024)
        data = self.rebuild(parts)
        self.assertLess(len(data), 1024 * 1024)
        self.assert_rejected(data, "Gzip-Bombe", backup.DB_PART)

    def test_manifest_must_come_first(self):
        parts = self.good_parts()
        members = [regular(name, parts[name]) for name in (backup.SETTINGS_PART, backup.MANIFEST,
                                                           backup.AUTOCAL_PART, backup.DB_PART)]
        self.assert_rejected(tar_bytes(members), "manifest.json", "erste Datei")

    def test_bad_manifest_rejected_before_parts_are_written(self):
        parts = self.good_parts()
        parts[backup.MANIFEST] = b"{}"
        written = []
        real_open = os.open

        def track(path, *args, **kwargs):
            written.append(os.path.basename(path))
            return real_open(path, *args, **kwargs)

        with mock.patch.object(backup.os, "open", side_effect=track):
            self.assert_rejected(tar_bytes([regular(name, parts[name]) for name in backup.PARTS]),
                                 "keine Sicherung von ntp-gui")
        self.assertNotIn(backup.DB_PART, written)

    def test_huge_pax_header(self):
        info = tarfile.TarInfo(backup.MANIFEST)
        info.pax_headers = {"comment": "x" * (backup.MAX_META_HEADER + 10)}
        self.assert_rejected(tar_bytes([(info, b"{}")]), "Kopfeintrag")

    def test_not_an_archive(self):
        self.assert_rejected(b"PK\x03\x04 kein tar", "keine lesbare Sicherung")
        self.assert_rejected(gzip.compress(b"x" * 600), "keine lesbare Sicherung")

    def test_missing_part(self):
        parts = self.good_parts()
        members = [regular(name, parts[name]) for name in (backup.MANIFEST, backup.SETTINGS_PART, backup.DB_PART)]
        self.assert_rejected(tar_bytes(members), "fehlt", backup.AUTOCAL_PART)

    def test_duplicate_part(self):
        parts = self.good_parts()
        self.assert_rejected(self.rebuild(parts, extra=[regular(backup.SETTINGS_PART, b"{}")]), "doppelt")

    def test_database_with_foreign_objects(self):
        for sql, word in (("CREATE TABLE gnss_state (key TEXT, json TEXT)", "mehr als erlaubt"),
                          ("CREATE VIEW v AS SELECT 1", "mehr als erlaubt"),
                          ("CREATE TRIGGER tr AFTER INSERT ON samples BEGIN DELETE FROM events; END",
                           "mehr als erlaubt"),
                          ("ALTER TABLE events ADD COLUMN lat REAL", "andere Spalten"),
                          ("DROP TABLE events", "erwarteten Tabellen")):
            with self.subTest(sql=sql):
                parts = self.good_parts()
                path = os.path.join(self.tmp, "manipuliert.sqlite")
                with open(path, "wb") as handle:
                    handle.write(parts[backup.DB_PART])
                conn = sqlite3.connect(path)
                conn.execute(sql)
                conn.commit()
                conn.close()
                parts[backup.DB_PART] = Path(path).read_bytes()
                self.assert_rejected(self.rebuild(parts), word)

    def test_database_not_sqlite(self):
        parts = self.good_parts()
        parts[backup.DB_PART] = b"kein sqlite" * 100
        self.assert_rejected(self.rebuild(parts), "keine SQLite-Datenbank")

    def test_invalid_rows_are_skipped(self):
        parts = self.good_parts()
        path = os.path.join(self.tmp, "zeilen.sqlite")
        with open(path, "wb") as handle:
            handle.write(parts[backup.DB_PART])
        conn = sqlite3.connect(path)
        conn.execute("INSERT INTO client_groups(id, name, network, updated) VALUES(99, 'Böse', 'kein netz', 1)")
        conn.execute("INSERT INTO clientmon_meta(ip, name, note, updated) VALUES('nicht-ip', 'x', '', 1)")
        conn.execute("INSERT INTO samples(t, json) VALUES('abc', 'kein json')")
        conn.commit()
        conn.close()
        parts[backup.DB_PART] = Path(path).read_bytes()
        data = self.rebuild(parts)
        staged = backup.stage_upload(io.BytesIO(data), len(data))
        backup.apply(staged["token"])
        self.assertEqual(len(store.query("SELECT * FROM client_groups")), 2)
        self.assertEqual(len(store.query("SELECT * FROM clientmon_meta")), 2)
        self.assertEqual(store.query("SELECT count(*) FROM samples WHERE typeof(t) <> 'integer'"), [(0,)])

    def test_older_settings_schema_is_migrated(self):
        parts = self.good_parts()
        part = json.loads(parts[backup.SETTINGS_PART])
        part["schema"] = 1
        part["values"]["nts_server_cert"] = "/etc/shadow"  # 1.2.0 hätte das noch gespeichert
        parts[backup.SETTINGS_PART] = json.dumps(part).encode()

        def older(manifest):
            manifest["schema"]["settings"] = 1
        data = self.rebuild(parts, older)
        staged = backup.stage_upload(io.BytesIO(data), len(data))
        self.assertTrue(staged["preview"]["schema"]["migrated"])
        backup.apply(staged["token"])
        self.assertNotIn("nts_server_cert", settings.export_values()["values"])
        self.assertEqual(settings.export_values()["values"]["web_title"], "Testuhr Keller")


def edit_dump(tmp: str, parts: dict, *statements, setup=None) -> dict:
    """daten.sqlite einer Sicherung verändern (wie ein Angreifer) – Prüfsummen passt rebuild() an."""
    path = os.path.join(tmp, "bearbeitet.sqlite")
    with open(path, "wb") as handle:
        handle.write(parts[backup.DB_PART])
    conn = sqlite3.connect(path)
    if setup:
        setup(conn)
    for sql in statements:
        if isinstance(sql, tuple):
            conn.execute(*sql)
        else:
            conn.executescript(sql)
    conn.commit()
    conn.close()
    parts = dict(parts)
    parts[backup.DB_PART] = Path(path).read_bytes()
    os.unlink(path)
    return parts


class RestoreSafetyTest(BackupTestBase):
    """Nachbesserung T5: Filter beim Einspielen, Kanäle, laufende Messung, alles oder nichts."""

    def staged(self, data: bytes) -> dict:
        return backup.stage_upload(io.BytesIO(data), len(data))

    def fresh(self, data: bytes) -> dict:
        self.use_dir(os.path.join(self.tmp, "neu"))
        settings.save({"web_title": "Neue Instanz"})
        clients3.save_group({"name": "Neu", "network": "10.9.9.0/24"})
        return self.staged(data)

    # --- Kanäle --------------------------------------------------------------------------------------
    def test_restore_into_same_instance_keeps_channel_secrets(self):
        before = {c["name"]: c for c in notify._load_all()}
        backup.apply(self.staged(self.make_backup())["token"])
        after = {c["name"]: c for c in notify._load_all()}
        for name in ("Handy", "Gotify", "Hausautomation", "Ohne Token"):
            for key in ("secret", "topic", "url", "enabled", "type"):
                self.assertEqual(after[name][key], before[name][key], f"{name}.{key}")
        self.assertEqual(after["Handy"]["secret"], TOKENS[0])
        self.assertEqual(after["Hausautomation"]["url"], f"https://ha.example.org/api/webhook/{TOKENS[2]}")

    def test_forged_active_channels_come_switched_off(self):
        now = time.time()
        row = ("INSERT INTO notify_channels VALUES (?, ?, ?, 1, ?, 0, '', 0, ?, 'info', '[]', 15, 600, 1, ?, ?)")
        parts = edit_dump(self.tmp, self.good_parts(),
                          (row, ("abcdef12", "Handy 2", "webhook", "http://evil.example.com", 0, now, now)),
                          (row, ("abcdef13", "Gotify ohne Token", "gotify", "https://g.example.com", 0, now, now)))
        staged = self.fresh(self.rebuild(parts))
        items = {i["name"]: i for i in staged["preview"]["channels"]["items"]}
        self.assertEqual(items["Handy 2"]["host"], "evil.example.com")
        self.assertFalse(items["Handy 2"]["known"])
        self.assertTrue(items["Handy 2"]["switched_off"])
        self.assertIn("App-Token", items["Gotify ohne Token"]["dropped"])
        backup.apply(staged["token"])
        channels = {c["name"]: c for c in notify._load_all()}
        self.assertFalse(channels["Handy 2"]["enabled"])
        self.assertNotIn("Gotify ohne Token", channels)
        self.assertFalse(any(c["enabled"] for c in channels.values()))

    def test_preview_names_channels_that_restore_deletes(self):
        # Kanal nach der Sicherung angelegt: Er steht nicht in der Sicherung und wird samt Token gelöscht –
        # das muss die Vorschau sagen, und der Bestätigungsdialog darf nicht das Gegenteil versprechen.
        data = self.make_backup()
        notify.save_channel({"name": "Neu Gotify", "type": "gotify", "url": "https://gotify2.example.org",
                             "secret": "NEU_GOTIFY_TOKEN_1234"})
        staged = self.staged(data)
        removed = staged["preview"]["channels"]["removed"]
        self.assertEqual([(c["name"], c["type"], c["host"], c["secret"]) for c in removed],
                         [("Neu Gotify", "Gotify", "gotify2.example.org", True)])
        self.assertNotIn("NEU_GOTIFY_TOKEN_1234", json.dumps(staged["preview"]))
        backup.apply(staged["token"])
        self.assertNotIn("Neu Gotify", {c["name"] for c in notify._load_all()})
        page = (Path(backup.__file__).parent / "static/js/pages/settings.js").read_text(encoding="utf-8")
        self.assertTrue("channels.removed" in page, "Vorschau zeigt wegfallende Kanäle nicht")
        self.assertFalse("vorhandene Kanäle behalten ihre Tokens" in page, "Bestätigung verspricht zu viel")

    def test_preview_names_channel_replaced_by_invalid_backup_entry(self):
        # Gleiche Kennung, aber der Eintrag in der Sicherung ist ungültig: Der Kanal hier wird trotzdem gelöscht.
        data = self.make_backup()
        staged = self.staged(data)
        self.assertEqual(staged["preview"]["channels"]["removed"], [])
        backup.discard(staged["token"])
        cid = next(c["id"] for c in notify._load_all() if c["name"] == "Gotify")
        parts = edit_dump(self.tmp, self.parts_from(data),
                          ("UPDATE notify_channels SET kinds = 'kaputt' WHERE id = ?", (cid,)))
        removed = self.staged(self.rebuild(parts))["preview"]["channels"]["removed"]
        self.assertEqual([c["name"] for c in removed], ["Gotify"])

    def test_preview_names_channel_replaced_by_other_server(self):
        # Gleiche Kennung, aber seit der Sicherung auf einen anderen Server umgestellt: Die Fassung aus der
        # Sicherung ersetzt den Kanal, der jetzige Token geht verloren – das muss die Vorschau sagen, und der
        # Bestätigungsdialog darf keinen Tokenerhalt für alle Kanäle versprechen, die hier und dort stehen.
        data = self.make_backup()
        current = next(c for c in notify._load_all() if c["name"] == "Gotify")
        notify.save_channel({"id": current["id"], "name": "Gotify", "type": "gotify",
                             "url": "https://gotify-neu.example.org", "secret": "NEUTOKEN_999"})
        staged = self.staged(data)
        channels = staged["preview"]["channels"]
        self.assertEqual(channels["removed"], [])
        self.assertEqual([(c["name"], c["host"], c["new_host"], c["secret"]) for c in channels["replaced"]],
                         [("Gotify", "gotify-neu.example.org", "gotify.example.org", True)])
        self.assertNotIn("NEUTOKEN_999", json.dumps(staged["preview"]))
        # Unverändert gebliebener Kanal: nicht als ersetzt geführt.
        backup.discard(staged["token"])
        self.assertEqual(self.staged(self.make_backup())["preview"]["channels"]["replaced"], [])
        page = (Path(backup.__file__).parent / "static/js/pages/settings.js").read_text(encoding="utf-8")
        self.assertIn("channels?.replaced", page)
        self.assertIn("gleicher Kennung, gleicher Art und gleichem Server behalten ihre Tokens", page)
        self.assertNotIn("die hier und in der Sicherung stehen, behalten ihre Tokens", page)

    def test_forged_rule_state_is_filtered(self):
        # client_rules.state läuft beim Erstellen durch scrub – beim Einspielen muss derselbe Filter gelten.
        forged = {"lat": LAT, "lon": LON, "note": f"Pos {LAT}, {LON}", "pos": [LAT, LON], "silent": 1}
        insert = ("INSERT INTO client_rules(ip, silent_h, offset_ms, offset_min, mute, expect, state, updated) "
                  "VALUES(?, ?, ?, ?, ?, ?, ?, ?)")
        parts = edit_dump(self.tmp, self.good_parts(),
                          (insert, ("192.0.2.5", None, None, 0, 0, "", json.dumps(forged), 1.0)),
                          (insert, ("192.0.2.6", None, None, 0, 1, "",
                                    json.dumps({"x": "a" * 9000, "silent": 1}), 1.0)))
        backup.apply(self.staged(self.rebuild(parts))["token"])
        state = json.loads(store.query("SELECT state FROM client_rules WHERE ip = '192.0.2.5'")[0][0])
        self.assertEqual(state, {"note": "Pos [Position entfernt]", "silent": 1})
        # Übergroßer Zustand: Die Regel bleibt, ihr Alarmzustand fängt leer an.
        mute, state = store.query("SELECT mute, state FROM client_rules WHERE ip = '192.0.2.6'")[0]
        self.assertEqual((mute, json.loads(state)), (1, {}))

    def test_apprise_key_is_a_secret(self):
        notify.save_channel({"name": "Ap", "type": "apprise", "url": "http://apprise:8000", "topic": "APPRISEKEY77",
                             "secret": "tgram://BOTTOKEN55/123"})
        data = self.make_backup()
        self.assertNotIn(b"APPRISEKEY77", b"".join(self.unpacked(data).values()))
        staged = self.fresh(data)
        reenter = {c["name"]: c["what"] for c in staged["preview"]["channels"]["reenter"]}
        self.assertIn("Schlüssel", reenter["Ap"])

    # --- Einstellungen -------------------------------------------------------------------------------
    def test_dot_and_pin_are_not_in_backup_and_kept(self):
        settings.save({"dns_dot": ["abc123.dns.nextdns.io"], "dns_pin": ["abc123.dns.nextdns.io=45.90.28.0"]})
        data = self.make_backup()
        self.assertNotIn(b"abc123", b"".join(self.unpacked(data).values()))
        backup.apply(self.staged(data)["token"])  # dieselbe Instanz: Werte bleiben
        self.assertEqual(settings.export_values()["values"]["dns_pin"], ["abc123.dns.nextdns.io=45.90.28.0"])
        staged = self.fresh(data)
        keys = [r["key"] for r in staged["preview"]["settings"]["reenter"]]
        self.assertEqual(sorted(keys), ["dns_doh", "dns_dot", "dns_pin"])

    def test_security_relevant_settings_are_listed(self):
        parts = self.good_parts()
        part = json.loads(parts[backup.SETTINGS_PART])
        part["values"].update(trusted_proxies=["10.0.0.0/8"], notify_lan_addresses=True)
        parts[backup.SETTINGS_PART] = json.dumps(part).encode()
        security = {s["key"]: s for s in self.staged(self.rebuild(parts))["preview"]["settings"]["security"]}
        self.assertEqual(security["trusted_proxies"]["after"], "10.0.0.0/8")
        self.assertEqual(security["notify_lan_addresses"]["after"], "an")
        self.assertNotIn("web_title", security)

    # --- Filter für die großen Tabellen --------------------------------------------------------------
    def test_forged_rows_in_large_tables_are_filtered(self):
        sample = json.dumps({"t": 1, "gps": {"lat": 48.1, "lon": 11.5, "used": 3}, "lat": 48.1,
                             "sky": [{"az": 1, "el": 2}]})
        parts = edit_dump(
            self.tmp, self.good_parts(),
            ("INSERT INTO samples(t, json) VALUES(?, ?)", (1000, sample)),
            ("INSERT INTO samples_5m(b, t, json) VALUES(?, ?, ?)", (3, 1000, sample)),
            ("INSERT INTO events(t, kind, level, title, data, source) VALUES(?, ?, ?, ?, ?, ?)",
             (5.0, "<img src=x>", "info", "x", None, "web")),
            ("INSERT INTO events(t, kind, level, title, data, source) VALUES(?, ?, ?, ?, ?, ?)",
             (6.0, "gps", "info", f"Position {LAT}, {LON} <script>",
              json.dumps({"lat": 48.1, "lon": 11.5, "password": "x", "ok": 1}), "web")),
            ("INSERT INTO events(t, kind, level, title, data, source) VALUES(?, ?, ?, ?, ?, ?)",
             (7.0, "gps", "info", "y", None, "<b>")),
            ("INSERT INTO clientmon_clients(ip, data, updated) VALUES(?, ?, ?)", ("not-an-ip<script>", "{}", 1.0)),
            ("INSERT INTO clientmon_clients(ip, data, updated) VALUES(?, ?, ?)",
             ("10.0.0.9", json.dumps({"requests": 1, "position": {"lat": 1}}), 1.0)),
            ("INSERT INTO client_inventory(key, first_seen) VALUES(?, ?)", ("<x>", 1.0)),
            ("INSERT INTO clientmon_samples(ip, t, offset, poll, version, interval) VALUES(?, ?, ?, ?, ?, ?)",
             ("10.0.0.9", 1.0, "abc", 6, 4, 64.0)),
            ("INSERT INTO client_hourly(ip, hour, n, med, p95, lo, hi) VALUES(?, ?, ?, ?, ?, ?, ?)",
             ("kaputt", 1, 1, 0, 0, 0, 0)))
        backup.apply(self.staged(self.rebuild(parts))["token"])
        for table in ("samples", "samples_5m"):
            stored = store.query(f"SELECT json FROM {table} WHERE t = 1000")[0][0]
            self.assertEqual(json.loads(stored), {"t": 1, "gps": {"used": 3}})
        kinds = {r[0] for r in store.query("SELECT kind FROM events")}
        self.assertNotIn("<img src=x>", kinds)
        self.assertEqual(store.query("SELECT count(*) FROM events WHERE source = '<b>'"), [(0,)])
        title, data = store.query("SELECT title, data FROM events WHERE t = 6.0")[0]
        self.assertNotIn("48.13", title)
        self.assertEqual(json.loads(data), {"ok": 1})
        ips = {r[0] for r in store.query("SELECT ip FROM clientmon_clients")}
        self.assertNotIn("not-an-ip<script>", ips)
        self.assertEqual(json.loads(store.query("SELECT data FROM clientmon_clients WHERE ip='10.0.0.9'")[0][0]),
                         {"requests": 1})
        self.assertEqual(store.query("SELECT count(*) FROM client_inventory WHERE key = '<x>'"), [(0,)])
        self.assertEqual(store.query("SELECT count(*) FROM clientmon_samples WHERE typeof(offset) = 'text'"), [(0,)])
        self.assertEqual(store.query("SELECT count(*) FROM client_hourly WHERE ip = 'kaputt'"), [(0,)])

    def test_other_coordinate_notations_are_removed(self):
        events.emit("gps", "info", "Standort N 48°08'13.8\" E 11°34'34.0\"", {"pos": [LAT, LON]})
        blob = b"".join(self.unpacked(self.make_backup()).values())
        for needle in (b"48\xc2\xb008", b"11\xc2\xb034", b"48.137154"):
            self.assertNotIn(needle, blob)

    def test_newer_samples_are_kept(self):
        staged = self.staged(self.make_backup())
        late = int(time.time()) + 5
        store.execute("INSERT INTO samples(t, json) VALUES(?, ?)", (late, json.dumps({"t": late, "offset": 1e-6})))
        backup.apply(staged["token"])
        self.assertEqual(store.query("SELECT count(*) FROM samples WHERE t = ?", (late,)), [(1,)])

    # --- Laufende Client-Messung ---------------------------------------------------------------------
    def test_running_monitor_does_not_overwrite_restored_devices(self):
        data = self.make_backup()
        self.use_dir(os.path.join(self.tmp, "neu"))
        monitor = clientmon.Monitor(123)
        monitor.table.update("192.168.1.20", {"version": 4, "poll": 6, "xmit": 0}, 0.001, time.time())
        self.addCleanup(setattr, clientmon, "_MONITOR", clientmon._MONITOR)
        clientmon._MONITOR = monitor
        backup.apply(self.staged(data)["token"])
        self.assertEqual(set(monitor.table.snapshot()), {"192.168.1.20", "192.168.1.21", "fd00::5"})
        self.assertEqual(monitor.table.pending, [])
        monitor._persist()
        stored = json.loads(store.query("SELECT data FROM clientmon_clients WHERE ip='192.168.1.20'")[0][0])
        self.assertEqual(stored["requests"], 10)
        self.assertEqual(store.query("SELECT count(*) FROM clientmon_samples"), [(3,)])

    def test_persist_with_snapshot_from_before_restore_does_not_write(self):
        data = self.make_backup()
        self.use_dir(os.path.join(self.tmp, "neu"))
        monitor = clientmon.Monitor(123)
        monitor.table.update("192.168.1.20", {"version": 4, "poll": 6, "xmit": 0}, 0.001, time.time())
        self.addCleanup(setattr, clientmon, "_MONITOR", clientmon._MONITOR)
        clientmon._MONITOR = monitor
        old_snapshot = monitor.table.snapshot_gen(private=True)
        staged = self.staged(data)
        backup.apply(staged["token"])
        with mock.patch.object(monitor.table, "snapshot_gen", return_value=old_snapshot):
            monitor._persist()
        stored = json.loads(store.query("SELECT data FROM clientmon_clients WHERE ip='192.168.1.20'")[0][0])
        self.assertEqual(stored["requests"], 10)

    def test_reset_clears_and_rebuilds_under_one_lock(self):
        # Zwischen Leeren und Neuaufbau darf keine Anfrage einen Eintrag anlegen (sonst überspränge der
        # Neuaufbau das Gerät, und das nächste Speichern überschriebe die wiederhergestellte Zeile).
        table = clientmon.Monitor(123).table
        real = table.lock
        acquired = []

        class Counting:
            def __enter__(self):
                acquired.append(1)
                return real.__enter__()

            def __exit__(self, *exc):
                return real.__exit__(*exc)

            def acquire(self, *a, **k):
                acquired.append(1)
                return real.acquire(*a, **k)

            def release(self):
                return real.release()
        table.lock = Counting()
        table.reset({"192.168.1.20": {"requests": 10, "first_seen": 5.0, "last_seen": 6.0}})
        self.assertEqual(len(acquired), 1)
        table.lock = real
        self.assertEqual(table.get("192.168.1.20")["requests"], 10)

    # --- Alles oder nichts ---------------------------------------------------------------------------
    def assert_unchanged_fresh(self):
        self.assertEqual(settings.export_values()["values"].get("web_title"), "Neue Instanz")
        self.assertEqual([r[0] for r in store.query("SELECT name FROM client_groups")], ["Neu"])
        self.assertEqual(autocal.load()["changes"], [])
        self.assertFalse(any(e["title"] == "GPS-Fix verloren" for e in events.query(limit=50)))
        leftovers = [n for n in os.listdir(self.data_dir) if n.startswith((".settings-", ".autocal-"))]
        self.assertEqual(leftovers, [])

    def test_settings_write_error_changes_nothing(self):
        staged = self.fresh(self.make_backup())
        real = settings.tempfile.mkstemp
        with mock.patch.object(settings.tempfile, "mkstemp",
                               side_effect=lambda *a, **k: (_ for _ in ()).throw(OSError(28, "Kein Platz frei"))
                               if k.get("prefix") == ".settings-" else real(*a, **k)):
            with self.assertRaises(backup.RestoreError) as caught:
                backup.apply(staged["token"])
        self.assertNotIn("Kein Platz", str(caught.exception))
        self.assertNotIn("OSError", str(caught.exception))
        self.assert_unchanged_fresh()

    def test_autocal_write_error_changes_nothing(self):
        staged = self.fresh(self.make_backup())
        with mock.patch.object(autocal, "save", side_effect=OSError(28, "Kein Platz frei")):
            with self.assertRaises(backup.RestoreError) as caught:
                backup.apply(staged["token"])
        self.assertNotIn("Kein Platz", str(caught.exception))
        self.assert_unchanged_fresh()

    def test_settings_replace_error_changes_nothing(self):
        # Dateien werden vor dem COMMIT eingesetzt: Scheitert os.replace für settings.json, kommt die schon
        # eingesetzte Kalibrierung zurück und die Transaktion wird verworfen – kein Stand „nach dem COMMIT“.
        staged = self.fresh(self.make_backup())
        real = os.replace
        calls = []

        def flaky(src, dst, *args, **kwargs):
            if str(dst).endswith("settings.json") and not calls:
                calls.append(dst)
                raise OSError(28, "Kein Platz frei")
            return real(src, dst, *args, **kwargs)
        with mock.patch.object(backup.settings.os, "replace", side_effect=flaky):
            with self.assertRaises(backup.RestoreError) as caught:
                backup.apply(staged["token"])
        self.assertTrue(calls)
        self.assertIn("nichts wurde geändert", str(caught.exception))
        self.assertNotIn("Kein Platz", str(caught.exception))
        self.assert_unchanged_fresh()
        self.assertEqual([n for n in os.listdir(self.data_dir) if n.startswith(".alt-")], [])

    def test_commit_error_puts_files_back(self):
        staged = self.fresh(self.make_backup())
        real = store.connect

        class FailingCommit:
            def __init__(self, conn):
                self._conn = conn

            def __getattr__(self, name):
                return getattr(self._conn, name)

            def execute(self, sql, *args):
                if sql == "COMMIT":
                    raise sqlite3.OperationalError("database or disk is full")
                return self._conn.execute(sql, *args)
        with mock.patch.object(backup.store, "connect", side_effect=lambda *a: FailingCommit(real(*a))):
            with self.assertRaises(backup.RestoreError) as caught:
                backup.apply(staged["token"])
        self.assertIn("nichts wurde geändert", str(caught.exception))
        self.assert_unchanged_fresh()

    def _old_backup_without_channels(self, **manifest) -> bytes:
        parts = edit_dump(self.tmp, self.good_parts(), "DELETE FROM notify_channels")
        return self.rebuild(parts, manifest_patch=(lambda m: m.update(manifest)) if manifest else None)

    def test_error_after_commit_rolls_back_with_channel_secrets(self):
        # Eine ältere Sicherung derselben Instanz ohne Kanäle; nach dem COMMIT scheitert etwas. Das
        # Zurückspielen muss Tokens, Themen, vollständige Adressen und Ein/Aus der Kanäle erhalten – die
        # automatische Sicherung enthält sie nicht.
        before = store.query("SELECT * FROM notify_channels ORDER BY id")
        self.assertTrue(any(TOKENS[0] in map(str, row) for row in before))
        staged = self.staged(self._old_backup_without_channels())
        real = backup._on_commit
        calls = []

        def flaky(max_event):
            real(max_event)
            if not calls:
                calls.append(max_event)
                raise RuntimeError("Fehler nach dem COMMIT")
        notify.NOTIFIER.last_id = 0
        with mock.patch.object(backup, "_on_commit", side_effect=flaky), \
                mock.patch.object(notify.NOTIFIER, "_save_position"):
            with self.assertRaises(backup.RestoreError) as caught:
                backup.apply(staged["token"])
        self.assertTrue(calls)
        self.assertIn("es gilt alles wie vorher", str(caught.exception))
        self.assertEqual(store.query("SELECT * FROM notify_channels ORDER BY id"), before)
        channels = {c["name"]: c for c in notify._load_all()}
        self.assertEqual(channels["Handy"]["secret"], TOKENS[0])
        self.assertEqual(channels["Handy"]["topic"], TOKENS[4])
        self.assertEqual(channels["Hausautomation"]["url"], f"https://ha.example.org/api/webhook/{TOKENS[2]}")
        self.assertTrue(all(c["enabled"] for c in channels.values()))
        self.assertEqual(settings.export_values()["values"].get("web_title"), "Testuhr Keller")
        self.assertGreaterEqual(notify.NOTIFIER.last_id, events.max_id())

    def test_rollback_succeeds_with_little_free_space(self):
        # Knapper Platz ist nach einem Fehler nach dem COMMIT wahrscheinlich: DISK_RESERVE darf das
        # Zurückspielen der (kleinen) automatischen Sicherung nicht verhindern.
        before = store.query("SELECT * FROM notify_channels ORDER BY id")
        staged = self.staged(self._old_backup_without_channels())
        real = backup._on_commit
        calls = []

        def flaky(max_event):
            real(max_event)
            if not calls:
                calls.append(max_event)
                raise RuntimeError("Fehler nach dem COMMIT")
        tight = shutil.disk_usage(self.tmp)._replace(free=backup.DISK_RESERVE + 1024)
        with mock.patch.object(backup, "_on_commit", side_effect=flaky), \
                mock.patch.object(backup.shutil, "disk_usage", return_value=tight), \
                mock.patch.object(notify.NOTIFIER, "_save_position"):
            with self.assertRaises(backup.RestoreError) as caught:
                backup.apply(staged["token"])
        self.assertTrue(calls)
        self.assertIn("es gilt alles wie vorher", str(caught.exception))
        self.assertEqual(store.query("SELECT * FROM notify_channels ORDER BY id"), before)
        self.assertEqual(settings.export_values()["values"].get("web_title"), "Testuhr Keller")

    def test_rollback_says_so_when_channels_differ(self):
        staged = self.staged(self._old_backup_without_channels())
        real = backup._on_commit
        calls = []

        def flaky(max_event):
            real(max_event)
            if not calls:
                calls.append(max_event)
                raise RuntimeError("Fehler nach dem COMMIT")
        with mock.patch.object(backup, "_on_commit", side_effect=flaky), \
                mock.patch.object(backup, "_channels_now", return_value=[]):
            with self.assertRaises(backup.RestoreError) as caught:
                backup.apply(staged["token"])
        self.assertNotIn("alles wie vorher", str(caught.exception))
        self.assertIn("Benachrichtigungskanäle", str(caught.exception))

    def test_detach_error_after_commit_is_not_reported_as_unchanged(self):
        data = self.make_backup()
        self.use_dir(os.path.join(self.tmp, "neu"))
        settings.save({"web_title": "Neue Instanz"})
        staged = self.staged(data)
        real = store.connect

        class FailingDetach:
            def __init__(self, conn):
                self._conn = conn

            def __getattr__(self, name):
                return getattr(self._conn, name)

            def execute(self, sql, *args):
                if sql.startswith("DETACH"):
                    raise sqlite3.OperationalError("database bak is locked")
                return self._conn.execute(sql, *args)
        with mock.patch.object(backup.store, "connect", side_effect=lambda *a: FailingDetach(real(*a))):
            result = backup.apply(staged["token"])  # kein Mischstand: alles übernommen
        self.assertTrue(result["ok"])
        self.assertEqual(settings.export_values()["values"].get("web_title"), "Testuhr Keller")
        self.assertEqual(sorted(r[0] for r in store.query("SELECT name FROM client_groups")), ["IoT", "Kameras"])
        self.assertIn("bak", [r[1] for r in store.connect().execute("PRAGMA database_list")])
        # Das hängen gebliebene „bak“ hält das nächste Wiederherstellen nicht auf.
        backup.apply(self.staged(data)["token"])
        self.assertNotIn("bak", [r[1] for r in store.connect().execute("PRAGMA database_list")])

    def test_exception_after_commit_inside_restore_database_is_after_commit(self):
        data = self.make_backup()
        workdir = os.path.join(self.tmp, "teile")
        os.makedirs(workdir)
        backup.unpack(self._write(data), workdir)
        with self.assertRaises(backup._AfterCommit):
            backup.restore_database(os.path.join(workdir, backup.DB_PART), time.time(),
                                    after_commit=mock.Mock(side_effect=RuntimeError("x")))

    def _write(self, data: bytes) -> str:
        path = os.path.join(self.tmp, "upload.tar.gz")
        Path(path).write_bytes(data)
        return path

    # --- Zeitpunkt der Sicherung (manifest.created) --------------------------------------------------
    def test_created_before_history_is_flagged_in_preview(self):
        staged = self.fresh(self.rebuild(self.good_parts(), manifest_patch=lambda m: m.update(created=1)))
        history = staged["preview"]["history"]
        self.assertEqual(history["samples"], 0)
        self.assertEqual(history["skipped"], len(self.before["samples"]) + len(self.before["samples_5m"]))
        self.assertIn("nicht übernommen", history["warning"])
        result = backup.apply(staged["token"])
        self.assertEqual(result["rows"]["samples"], 0)

    def test_created_far_in_future_is_rejected(self):
        future = time.time() + 20 * 86400
        self.assert_rejected(self.rebuild(self.good_parts(), manifest_patch=lambda m: m.update(created=future)),
                             "Zukunft", "abgelehnt")

    def test_future_samples_are_dropped(self):
        now = int(time.time())
        parts = edit_dump(self.tmp, self.good_parts(),
                          ("INSERT INTO samples(t, json) VALUES(?, ?)",
                           (now + 3 * 3600, json.dumps({"t": now + 3 * 3600, "offset": 9.9}))))
        staged = self.fresh(self.rebuild(parts, manifest_patch=lambda m: m.update(created=now + 6 * 3600)))
        self.assertEqual(staged["preview"]["history"]["skipped"], 1)
        backup.apply(staged["token"])
        self.assertEqual(store.query("SELECT count(*) FROM samples WHERE t > ?", (now + 3600,)), [(0,)])
        self.assertEqual(store.query("SELECT count(*) FROM samples"), [(len(self.before["samples"]),)])

    # --- Koordinaten in Messpunkten und Ereignissen --------------------------------------------------
    def test_coordinates_in_sample_texts_and_event_lists_are_removed(self):
        now = int(self.now)
        forged = {"t": now - 5, "temp": f"{LAT}, {LON}", "offset": 1e-5,
                  "sources": {f"{LAT},{LON}": {"o": 1}, "N48 08.229 E011 34.567": {"o": 2, "s": f"{LAT} {LON}"},
                              "ptbtime1.ptb.de": {"o": 3, "s": "*"}},
                  "gps": {"used": 4, "mode": f"{LAT};{LON}"}}
        parts = edit_dump(
            self.tmp, self.good_parts(),
            ("INSERT INTO samples(t, json) VALUES(?, ?)", (now - 5, json.dumps(forged))),
            ("INSERT INTO samples_5m(b, t, json) VALUES(?, ?, ?)", (now // 300 - 1, now - 5, json.dumps(forged))),
            ("INSERT INTO events(t, kind, level, title, data, source) VALUES(?, ?, ?, ?, ?, ?)",
             (now, "gps", "info", "Ort", json.dumps({"p": [LAT, LON], "q": {"r": [[LAT, LON, ALT]]},
                                                     "t": (LON, LAT), "ok": [1, 2], "ms": [0.25, 3.5]}), "gps")),
            ("INSERT INTO clientmon_clients(ip, data, updated) VALUES(?, ?, ?)",
             ("10.0.0.7", json.dumps({"requests": 2, "w": [LAT, LON], "intervals": [64.012, 63.998, 64.0],
                                      "recent": [[now - 10.5, 0.0012345], [now - 5.25, -0.0003]]}), 1.0)))
        backup.apply(self.fresh(self.rebuild(parts))["token"])
        blob = json.dumps(store.query("SELECT json FROM samples UNION ALL SELECT json FROM samples_5m")
                          + store.query("SELECT data FROM events UNION ALL SELECT data FROM clientmon_clients"))
        for needle in ("48.137", "11.576", "48 08", "34.567"):
            self.assertNotIn(needle, blob)
        sample = json.loads(store.query("SELECT json FROM samples WHERE t = ?", (now - 5,))[0][0])
        self.assertEqual(sample["offset"], 1e-5)
        self.assertEqual(sample["sources"]["ptbtime1.ptb.de"], {"o": 3, "s": "*"})
        self.assertEqual(sample["gps"]["used"], 4)
        data = json.loads(store.query("SELECT data FROM events WHERE kind = 'gps' AND title = 'Ort'")[0][0])
        self.assertEqual(data, {"q": {"r": []}, "ok": [1, 2], "ms": [0.25, 3.5]})
        client = json.loads(store.query("SELECT data FROM clientmon_clients WHERE ip = '10.0.0.7'")[0][0])
        self.assertEqual(client["intervals"], [64.012, 63.998, 64.0])
        self.assertEqual(client["recent"], [[now - 10.5, 0.0012345], [now - 5.25, -0.0003]])
        self.assertNotIn("w", client)

    def test_coordinates_in_sample_texts_never_enter_a_backup(self):
        now = int(self.now)
        store.execute("INSERT INTO samples(t, json) VALUES(?, ?)",
                      (now - 3, json.dumps({"t": now - 3, "temp": f"{LAT}, {LON}",
                                            "sources": {f"{LAT},{LON}": {"o": 1}}})))
        events.emit("gps", "info", "Ort", {"wo": [LAT, LON]})
        blob = b"".join(self.unpacked(self.make_backup()).values())
        for needle in (b"48.137154", b"11.576124"):
            self.assertNotIn(needle, blob)

    def test_scrub_keeps_real_measurements(self):
        # Listen, die in Ereignissen und Client-Daten legitim vorkommen, bleiben unverändert.
        fixtures = Path(__file__).resolve().parent / "fixtures"
        docs = [json.loads((fixtures / name).read_text()) for name in ("clients3_lan.json", "loop_pi4_chronyc.json")]
        for name in ("gps_vk162_indoor.jsonl", "gps_vk162_fixflaps.jsonl"):
            docs += [json.loads(line) for line in (fixtures / name).read_text().splitlines() if line.strip()]
        with mock.patch.object(backup, "_coord_list", return_value=False):
            reference = [backup.scrub(doc) for doc in docs]
        self.assertEqual([backup.scrub(doc) for doc in docs], reference)
        for keep in ([64.012, 63.998], [64.0, 128.0, 1024.0], [1.5, 2.25], [-3.254, 0.012], [0.0012, 0.0031],
                     [1731000000.5, 0.001], [48, 11], [True, False], [1.2345, 200.5], [95.12345, 11.5]):
            self.assertEqual(backup.scrub({"x": keep}), {"x": keep}, keep)
        for drop in ([LAT, LON], [LAT, LON, ALT], [-33.8688, 151.2093], [LON, LAT], (LAT, LON)):
            self.assertEqual(backup.scrub({"x": drop, "y": [drop]}), {"y": []}, drop)

    def test_notifier_skips_old_events_right_after_commit(self):
        seen = []
        real = notify.NOTIFIER.skip_to

        def spy(event_id):
            seen.append(store.lock()._is_owned())
            return real(event_id)
        with mock.patch.object(notify.NOTIFIER, "skip_to", side_effect=spy):
            backup.apply(self.staged(self.make_backup())["token"])
        self.assertEqual(seen, [True])

    def test_wal_is_truncated_after_restore(self):
        data = self.make_backup()
        backup.apply(self.staged(data)["token"])
        wal = store.path() + "-wal"
        self.assertLess(os.path.getsize(wal) if os.path.exists(wal) else 0, 64 * 1024)

    def test_create_is_fast_and_does_not_block_readers(self):
        # Akzeptanz: 30 Tage Verlauf (259 200 Punkte) auf dem Pi 4 unter 10 s. Hier ein Fünftel davon mit
        # großzügiger Grenze (CI-Rechner schwanken) – und parallele Lesezugriffe warten nicht auf create().
        rows = []
        base = int(self.now) - 90 * 86400
        sample = {"offset": 1e-5, "rms": 2e-6, "freq": -3.25, "stratum": 1, "served": 1000,
                  "sources": {"ptbtime1.ptb.de": {"o": 1e-4, "s": "*", "k": "^", "j": 2e-5}},
                  "gps": {"used": 8, "seen": 12, "hdop": 0.9, "snr": 33.5, "mode": 3, "cn4": 41.0}}
        for i in range(52_000):
            rows.append((base + i * 10, json.dumps(dict(sample, t=base + i * 10), separators=(",", ":"))))
        with store.transaction() as conn:
            conn.executemany("INSERT INTO samples(t, json) VALUES(?, ?)", rows)
        waits, stop = [], threading.Event()

        def reader():
            while not stop.is_set():
                start = time.monotonic()
                store.query("SELECT count(*) FROM events")
                waits.append(time.monotonic() - start)
                time.sleep(0.005)
        thread = threading.Thread(target=reader)
        thread.start()
        try:
            start = time.monotonic()
            self.make_backup()
            took = time.monotonic() - start
        finally:
            stop.set()
            thread.join()
        self.assertLess(took, 20.0)
        self.assertTrue(waits)
        self.assertLess(max(waits), 1.0)

    # --- Robustheit beim Prüfen ----------------------------------------------------------------------
    def test_many_chained_meta_headers(self):
        for kind, payload in ((tarfile.XHDTYPE, b"13 comment=x\n"), (tarfile.GNUTYPE_LONGNAME, b"manifest.json\0")):
            with self.subTest(kind=kind):
                raw = io.BytesIO()
                for _ in range(600):
                    info = tarfile.TarInfo("kopf")
                    info.type, info.size = kind, len(payload)
                    raw.write(info.tobuf(tarfile.USTAR_FORMAT))
                    raw.write(payload + b"\0" * (512 - len(payload)))
                info = tarfile.TarInfo(backup.MANIFEST)
                info.size = 2
                raw.write(info.tobuf(tarfile.USTAR_FORMAT) + b"{}" + b"\0" * 510 + b"\0" * 1024)
                self.assert_rejected(gzip.compress(raw.getvalue()), "Kopfeinträge")

    def test_unexpected_table_definitions(self):
        def collation(conn):
            conn.create_collation("evil", lambda a, b: 0)
        for sql, setup in (
                ('DROP TABLE client_inventory; CREATE TABLE client_inventory ("key" TEXT COLLATE evil, '
                 '"first_seen" REAL)', collation),
                ('DROP TABLE client_inventory; CREATE TABLE client_inventory ("key" TEXT PRIMARY KEY, '
                 '"first_seen" REAL) WITHOUT ROWID', None),
                ('DROP TABLE client_inventory; CREATE TABLE client_inventory ("key" TEXT, "first_seen" REAL, '
                 'x GENERATED ALWAYS AS (1))', None),
                ('DROP TABLE client_inventory; CREATE TABLE client_inventory ("key" TEXT DEFAULT \'x\', '
                 '"first_seen" REAL)', None)):
            with self.subTest(sql=sql):
                parts = edit_dump(self.tmp, self.good_parts(), sql, setup=setup)
                self.assert_rejected(self.rebuild(parts), "abgelehnt")

    def test_broken_calibration_is_dropped(self):
        parts = self.good_parts()
        cal = json.loads(parts[backup.AUTOCAL_PART])
        good = cal["changes"][0]
        cal.update(changes=[{"id": 7, "t": "gestern", "new_offset": "abc", "old_offset": 0, "kind": "auto"}, good],
                   observed="kaputt", pending=[1, 2], last_tick="bald", last_decision={"action": 1})
        parts[backup.AUTOCAL_PART] = json.dumps(cal).encode()
        staged = self.staged(self.rebuild(parts))
        dropped = staged["preview"]["calibration"]["dropped"]
        self.assertEqual(len(dropped), 4, dropped)
        backup.apply(staged["token"])
        state = autocal.load()
        self.assertEqual([c["id"] for c in state["changes"]], [good["id"]])
        self.assertIsNone(state["observed"])
        self.assertIsNone(state["pending"])
        self.assertIsNone(state["last_tick"])
        self.assertIsNone(state["last_decision"])
        cfg = dict(settings.values(), gps_offset=good["new_offset"])
        self.assertTrue(autocal.api_status(cfg)["rollback"]["possible"])


class HttpTest(_DataDir, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"})
        cls.env.start()
        os.environ.pop("WEB_READONLY", None)
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        cls.env.stop()
        server.AUTH_CACHE.clear()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ntpgui-backup-http-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(self.stop_dirs)
        self.use_dir(os.path.join(self.tmp, "daten"))
        self.addCleanup(server.AUTH_CACHE.clear)
        populate(time.time())
        _key, self.read_key = apikeys.create("Lesen", "read")
        _key, self.admin_key = apikeys.create("Verwalten", "admin")

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, body=body, headers=dict(headers or {}))
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, raw, resp

    @staticmethod
    def basic(**extra):
        return {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode(), **extra}

    def test_backup_requires_admin(self):
        self.assertEqual(self.request("GET", "/api/backup")[0], 401)
        self.assertEqual(self.request("GET", "/api/backup", headers={"Authorization": f"Bearer {self.read_key}"})[0], 403)
        self.assertEqual(self.request("GET", "/api/v1/backup", headers={"Authorization": f"Bearer {self.read_key}"})[0], 403)
        self.assertEqual(self.request("GET", "/api/backup/list", headers={"Authorization": f"Bearer {self.read_key}"})[0], 403)
        status, raw, resp = self.request("GET", "/api/backup", headers=self.basic())
        self.assertEqual(status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "application/gzip")
        self.assertRegex(resp.getheader("Content-Disposition"), r'filename="ntp-gui-sicherung-\d{8}-\d{4}\.tar\.gz"')
        self.assertEqual(raw[:2], b"\x1f\x8b")
        status, _raw, _resp = self.request("GET", "/api/backup", headers={"Authorization": f"Bearer {self.admin_key}"})
        self.assertEqual(status, 200)
        # Der Server löscht die Download-Datei erst nach dem Senden (finally in _send_backup); unter Last kann der
        # Client die Antwort schon haben, bevor der Server-Thread aufgeräumt hat – deshalb kurz darauf warten.
        folder = os.path.join(self.data_dir, backup.DOWNLOAD_DIR)
        deadline = time.monotonic() + 5
        while os.listdir(folder) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(os.listdir(folder), [])

    def test_restore_auth_and_csrf(self):
        _status, data, _resp = self.request("GET", "/api/backup", headers=self.basic())
        gz = {"Content-Type": "application/gzip"}
        # ohne Anmeldung, mit Lese-Schlüssel, ohne Pflicht-Kopf, fremder Origin, falscher Typ
        self.assertEqual(self.request("POST", "/api/restore/preview", data, dict(gz, **{"X-NTP-GUI": "1"}))[0], 401)
        self.assertEqual(self.request("POST", "/api/restore/preview", data,
                                      dict(gz, Authorization=f"Bearer {self.read_key}"))[0], 403)
        self.assertEqual(self.request("POST", "/api/restore/preview", data, self.basic(**gz))[0], 403)
        self.assertEqual(self.request("POST", "/api/restore/preview", data,
                                      self.basic(**gz, **{"X-NTP-GUI": "1", "Origin": "http://fremd.example"}))[0], 403)
        self.assertEqual(self.request("POST", "/api/restore/preview", data,
                                      self.basic(**{"Content-Type": "text/plain", "X-NTP-GUI": "1"}))[0], 403)
        self.assertEqual(os.listdir(backup.staging_root()) if os.path.isdir(backup.staging_root()) else [], [])
        status, raw, _resp = self.request("POST", "/api/restore/preview", data, self.basic(**gz, **{"X-NTP-GUI": "1"}))
        self.assertEqual(status, 200, raw)
        token = json.loads(raw)["token"]
        body = json.dumps({"token": token}).encode()
        js = {"Content-Type": "application/json"}
        self.assertEqual(self.request("POST", "/api/restore/apply", body, js)[0], 401)
        self.assertEqual(self.request("POST", "/api/restore/apply", body,
                                      dict(js, Authorization=f"Bearer {self.read_key}"))[0], 403)
        self.assertEqual(self.request("POST", "/api/restore/apply", body, self.basic(**js))[0], 403)
        with mock.patch.object(server, "trigger_reload", return_value=True):
            status, raw, _resp = self.request("POST", "/api/restore/apply", body, self.basic(**js, **{"X-NTP-GUI": "1"}))
        self.assertEqual(status, 200, raw)
        result = json.loads(raw)
        self.assertTrue(result["ok"])
        self.assertIn("reload_triggered", result)
        titles = [e["title"] for e in events.query(limit=5)]
        self.assertTrue(any(t.startswith("Wiederhergestellt aus Sicherung vom") for t in titles))
        # Merker gilt nur einmal.
        status, _raw, _resp = self.request("POST", "/api/restore/apply", body, self.basic(**js, **{"X-NTP-GUI": "1"}))
        self.assertEqual(status, 409)

    def test_admin_key_may_restore_without_csrf_header(self):
        _status, data, _resp = self.request("GET", "/api/backup", headers=self.basic())
        status, raw, _resp = self.request("POST", "/api/v1/restore/preview", data,
                                          {"Content-Type": "application/gzip", "Authorization": f"Bearer {self.admin_key}"})
        self.assertEqual(status, 200, raw)
        token = json.loads(raw)["token"]
        status, _raw, _resp = self.request("POST", "/api/v1/restore/cancel", json.dumps({"token": token}).encode(),
                                           {"Content-Type": "application/json",
                                            "Authorization": f"Bearer {self.admin_key}"})
        self.assertEqual(status, 200)
        self.assertEqual(os.listdir(backup.staging_root()), [])

    def test_malicious_upload_gives_clear_message(self):
        evil = tar_bytes([regular("../evil", b"x")])
        status, raw, _resp = self.request("POST", "/api/restore/preview", evil,
                                          self.basic(**{"Content-Type": "application/gzip", "X-NTP-GUI": "1"}))
        self.assertEqual(status, 422)
        payload = json.loads(raw)
        self.assertIn("unzulässigen Pfad", payload["error"])
        self.assertFalse(payload["written"])

    def test_unexpected_schema_gives_422(self):
        _status, data, _resp = self.request("GET", "/api/backup", headers=self.basic())
        parts = BackupTestBase.unpacked(self, data)
        parts = edit_dump(self.tmp, parts, 'DROP TABLE client_inventory; CREATE TABLE client_inventory '
                          '("key" TEXT PRIMARY KEY, "first_seen" REAL) WITHOUT ROWID')
        evil = BackupTestBase.rebuild(self, parts)
        status, raw, _resp = self.request("POST", "/api/restore/preview", evil,
                                          self.basic(**{"Content-Type": "application/gzip", "X-NTP-GUI": "1"}))
        self.assertEqual(status, 422, raw)
        self.assertEqual(os.listdir(os.path.join(self.data_dir, backup.BACKUP_DIR))
                         if os.path.isdir(os.path.join(self.data_dir, backup.BACKUP_DIR)) else [], [])

    def test_upload_over_limit_rejected_before_reading(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("POST", "/api/restore/preview")
        for key, value in self.basic(**{"Content-Type": "application/gzip", "X-NTP-GUI": "1"}).items():
            conn.putheader(key, value)
        conn.putheader("Content-Length", str(backup.MAX_UPLOAD + 1))
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 413)
        conn.close()

    def test_readonly_blocks_restore(self):
        with mock.patch.dict(os.environ, {"WEB_READONLY": "true"}):
            status, _raw, _resp = self.request("POST", "/api/restore/preview", b"x",
                                               self.basic(**{"Content-Type": "application/gzip", "X-NTP-GUI": "1"}))
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
