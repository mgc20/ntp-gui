"""Tests für versionierte Einstellungen (Schema + Migrationen) und die neuen Felder in 1.3."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import settings  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (settings.DATA_DIR, settings.SETTINGS_FILE)
        settings.DATA_DIR = os.path.join(self.tmp, "ntp-gui")
        settings.SETTINGS_FILE = os.path.join(settings.DATA_DIR, "settings.json")
        settings._CACHE.update(mtime=None, data=None)
        self.env = dict(os.environ)
        for key in list(os.environ):
            if key.startswith(("NTP_", "GPS_", "PTP_", "NTS_", "WEB_", "PHC", "CLIENTMON", "ENFORCE")):
                del os.environ[key]

    def tearDown(self):
        settings.DATA_DIR, settings.SETTINGS_FILE = self.saved
        settings._CACHE.update(mtime=None, data=None)
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, data):
        os.makedirs(settings.DATA_DIR, exist_ok=True)
        Path(settings.SETTINGS_FILE).write_text(json.dumps(data), encoding="utf-8")
        settings._CACHE.update(mtime=None, data=None)

    def stored(self):
        return json.loads(Path(settings.SETTINGS_FILE).read_text(encoding="utf-8"))


class MigrationTest(_Base):

    def test_new_file_gets_current_schema(self):
        settings.save({"web_title": "Zeit"})
        self.assertEqual(self.stored()["schema"], settings.SCHEMA_VERSION)
        self.assertEqual(settings.migration_notes(), [])

    def test_1_to_2_drops_cert_paths_outside_roots(self):
        self.write({"values": {"nts_server_cert": "/etc/shadow", "nts_server_key": "/config/nts.key",
                               "web_title": "bleibt"},
                    "auth": {"user": "admin", "hash": "x"}})
        values = settings.values()
        self.assertEqual(values["nts_server_cert"], "/config/nts.crt")  # Standard
        self.assertEqual(values["nts_server_key"], "/config/nts.key")
        self.assertEqual(values["web_title"], "bleibt")
        data = self.stored()
        self.assertEqual(data["schema"], settings.SCHEMA_VERSION)
        self.assertNotIn("nts_server_cert", data["values"])
        self.assertEqual(data["auth"]["user"], "admin")
        notes = settings.migration_notes()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["keys"], ["nts_server_cert"])
        self.assertIn("1.2.0", notes[0]["text"])
        self.assertIn("/certs", notes[0]["text"])
        # Kein Fehler mehr „Gespeicherter Wert ungültig“.
        self.assertIsNone(settings.effective()["nts_server_cert"]["error"])

    def test_migration_runs_once_and_ack(self):
        self.write({"values": {"nts_server_key": "/root/key.pem"}})
        self.assertEqual(len(settings.migration_notes()), 1)
        settings._CACHE.update(mtime=None, data=None)
        self.assertEqual(len(settings.migration_notes()), 1)  # nicht doppelt
        self.assertEqual(settings.ack_migration_notes(), 1)
        self.assertEqual(settings.migration_notes(include_seen=False), [])
        self.assertEqual(len(settings.migration_notes()), 1)
        self.assertEqual(settings.ack_migration_notes(), 0)

    def test_valid_file_migrates_silently(self):
        self.write({"values": {"nts_server_cert": "/certs/live/x/fullchain.pem"}})
        self.assertEqual(settings.values()["nts_server_cert"], "/certs/live/x/fullchain.pem")
        self.assertEqual(self.stored()["schema"], settings.SCHEMA_VERSION)
        self.assertEqual(settings.migration_notes(), [])

    def test_newer_schema_untouched(self):
        self.write({"schema": 99, "values": {"web_title": "Zukunft"}})
        self.assertEqual(settings.values()["web_title"], "Zukunft")
        self.assertEqual(self.stored()["schema"], 99)
        self.assertEqual(settings.schema_version(), 99)

    def test_readonly_volume_migrates_in_memory(self):
        self.write({"values": {"nts_server_cert": "/etc/passwd"}})
        os.chmod(settings.DATA_DIR, 0o500)
        try:
            if os.access(settings.DATA_DIR, os.W_OK):
                self.skipTest("läuft als root – Verzeichnis bleibt schreibbar")
            self.assertEqual(settings.values()["nts_server_cert"], "/config/nts.crt")
            self.assertEqual(len(settings.migration_notes()), 1)
        finally:
            os.chmod(settings.DATA_DIR, 0o700)

    def test_import_of_old_export(self):
        values, notes = settings.migrate_import({"values": {"nts_server_cert": "/etc/shadow",
                                                            "web_title": "x"}})
        self.assertEqual(values, {"web_title": "x"})
        self.assertEqual(len(notes), 1)
        with self.assertRaises(settings.ValidationError):
            settings.migrate_import({"schema": 99, "values": {}})
        with self.assertRaises(settings.ValidationError):
            settings.migrate_import({"nothing": 1})
        self.assertEqual(settings.export_values()["schema"], settings.SCHEMA_VERSION)

    def test_migrations_cover_every_version(self):
        for version in range(2, settings.SCHEMA_VERSION + 1):
            self.assertIn(version, settings.MIGRATIONS)


class NewFieldsTest(_Base):
    def test_defaults(self):
        values = settings.values({})
        self.assertEqual(values["gps_autocal"], "suggest")
        self.assertEqual(values["gps_autocal_max_step_ms"], 5.0)
        self.assertEqual(values["gps_autocal_min_hours"], 6.0)
        self.assertIs(values["clientmon_enable"], True)
        self.assertEqual(values["enforce_hostnames"], [])

    def test_env(self):
        values = settings.values({"GPS_AUTOCAL": "auto", "CLIENTMON": "false",
                                  "GPS_AUTOCAL_MAX_STEP_MS": "2.5", "GPS_AUTOCAL_MIN_HOURS": "12",
                                  "ENFORCE_HOSTNAMES": "Time.Example.com, ntp.cam.local"})
        self.assertEqual(values["gps_autocal"], "auto")
        self.assertIs(values["clientmon_enable"], False)
        self.assertEqual(values["gps_autocal_max_step_ms"], 2.5)
        self.assertEqual(values["gps_autocal_min_hours"], 12.0)
        self.assertEqual(values["enforce_hostnames"], ["time.example.com", "ntp.cam.local"])

    def test_validation(self):
        for key, bad in (("gps_autocal", "immer"), ("gps_autocal_max_step_ms", 0),
                         ("gps_autocal_max_step_ms", 500), ("gps_autocal_min_hours", 0.1),
                         ("enforce_hostnames", ["192.168.1.1"]), ("enforce_hostnames", "a b;c"),
                         ("enforce_hostnames", ["x\nserver evil"]), ("enforce_hostnames", "localhost")):
            with self.assertRaises(settings.ValidationError, msg=f"{key}={bad!r}"):
                settings.validate({key: bad})
        self.assertEqual(settings.validate({"enforce_hostnames": "a.de\nb.de,a.de"})["enforce_hostnames"],
                         ["a.de", "b.de"])

    def test_runtime_fields_need_no_restart(self):
        for key in ("gps_autocal", "gps_autocal_max_step_ms", "gps_autocal_min_hours",
                    "clientmon_enable", "enforce_hostnames"):
            self.assertEqual(settings.FIELDS[key]["restart"], settings.RESTART_NONE, key)
            self.assertTrue(settings.FIELDS[key]["help"], key)
        result = settings.save({"gps_autocal": "off", "clientmon_enable": False})
        self.assertFalse(result["restart"])


class LeapMigrationTest(unittest.TestCase):
    def test_right_utc_removed_with_note(self):
        data, notes = settings.migrate_data({"schema": 2, "values": {"leapsectz": "right/UTC"}})
        self.assertNotIn("leapsectz", data["values"])
        self.assertEqual([n["id"] for n in notes], ["3-leapsectz"])
        self.assertEqual(data["schema"], settings.SCHEMA_VERSION)

    def test_custom_zone_kept(self):
        data, notes = settings.migrate_data({"schema": 2, "values": {"leapsectz": "right/Europe/Berlin"}})
        self.assertEqual(data["values"]["leapsectz"], "right/Europe/Berlin")
        self.assertEqual(notes, [])

    def test_leapseclist_path_checked(self):
        self.assertRaises(settings.ValidationError, settings._as_leapseclist, "/etc/shadow")
        self.assertRaises(settings.ValidationError, settings._as_leapseclist, "/config/../etc/x")
        self.assertEqual(settings._as_leapseclist("/config/leap-seconds.list"), "/config/leap-seconds.list")


if __name__ == "__main__":
    unittest.main()
