"""Tests für API-Schlüssel (apikeys.py), Instanz-Kennung (instance.py) und /api/v1 (apiv1.py)."""

import os
import re
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import apikeys  # noqa: E402
import apiv1  # noqa: E402
import events  # noqa: E402
import instance  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        # PBKDF2 mit 200 000 Runden macht die Tests unnötig langsam.
        self.rounds = mock.patch.object(settings, "_PBKDF2_ROUNDS", 1000)
        self.rounds.start()
        apikeys.clear_cache()
        apikeys._LAST_WRITE.clear()

    def tearDown(self):
        self.rounds.stop()
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class ApiKeysTest(TempDir):
    def test_create_verify_list(self):
        key_id, token = apikeys.create("Home Assistant", "read")
        self.assertRegex(token, r"^ntpg_[A-Za-z0-9_-]{32}$")
        self.assertEqual(token[5:13], key_id)
        self.assertEqual(apikeys.verify(token), {"id": key_id, "name": "Home Assistant", "scope": "read"})
        self.assertEqual(apikeys.verify(token + " "), apikeys.verify(token))
        listed = apikeys.list()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["scope"], "read")
        self.assertIsNotNone(listed[0]["last_used"])
        flat = repr(listed)
        self.assertNotIn(token, flat)
        self.assertNotIn(token[13:], flat)
        self.assertNotIn("hash", listed[0])

    def test_only_hash_stored(self):
        _id, token = apikeys.create("x", "admin")
        stored = store.query("SELECT hash FROM api_keys")[0][0]
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        raw = Path(store.path()).read_bytes() + (Path(store.path() + "-wal").read_bytes()
                                                   if os.path.exists(store.path() + "-wal") else b"")
        self.assertNotIn(token[13:].encode(), raw)

    def test_wrong_tokens(self):
        key_id, token = apikeys.create("x", "admin")
        forged = token[:13] + ("A" if token[13] != "A" else "B") + token[14:]
        for bad in (forged, "ntpg_" + "a" * 32, "", None, "Bearer " + token, token[:-1], 123):
            self.assertIsNone(apikeys.verify(bad), bad)
        self.assertIsNotNone(apikeys.verify(token))

    def test_revoke_takes_effect_immediately(self):
        key_id, token = apikeys.create("x", "admin")
        self.assertIsNotNone(apikeys.verify(token))  # jetzt im Merker
        self.assertTrue(apikeys.revoke(key_id))
        self.assertIsNone(apikeys.verify(token))
        self.assertFalse(apikeys.revoke(key_id))
        self.assertEqual(apikeys.list(), [])

    def test_validation(self):
        for name, scope in (("", "read"), ("a\x00b", "read"), ("x" * 65, "read"), ("ok", "root")):
            with self.assertRaises(settings.ValidationError):
                apikeys.create(name, scope)
        with mock.patch.object(apikeys, "MAX_KEYS", 2):
            apikeys.create("a", "read")
            apikeys.create("b", "read")
            with self.assertRaises(settings.ValidationError):
                apikeys.create("c", "read")

    def test_scope_rules(self):
        self.assertTrue(apikeys.allows("read", "GET"))
        self.assertTrue(apikeys.allows("read", "head"))
        self.assertFalse(apikeys.allows("read", "POST"))
        self.assertTrue(apikeys.allows("admin", "POST"))
        self.assertFalse(apikeys.allows("bogus", "GET"))

    def test_events_logged_without_secret(self):
        _id, token = apikeys.create("Skript", "read")
        rows = events.query(kinds=["settings"])
        self.assertTrue(any("Skript" in r["title"] for r in rows))
        self.assertNotIn(token, repr(rows))


class InstanceTest(TempDir):
    def test_stable_and_rotatable(self):
        first = instance.get()
        self.assertEqual(uuid.UUID(first).version, 4)
        self.assertEqual(instance.get(), first)
        path = os.path.join(settings.DATA_DIR, "instance-id")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        second = instance.rotate()
        self.assertNotEqual(first, second)
        self.assertEqual(instance.get(), second)
        self.assertEqual(instance.info()["instance_id"], second)

    def test_corrupt_file_regenerated(self):
        os.makedirs(settings.DATA_DIR)
        Path(settings.DATA_DIR, "instance-id").write_text("00:11:22:33:44:55\n")
        self.assertEqual(uuid.UUID(instance.get()).version, 4)


class ApiV1Test(unittest.TestCase):
    def test_resolve(self):
        self.assertEqual(apiv1.resolve("/api/v1/status"), "/api/status")
        self.assertEqual(apiv1.resolve("/api/v1/status/"), "/api/status")
        self.assertEqual(apiv1.resolve("/api/v1/history?range=60"), "/api/history")
        self.assertEqual(apiv1.resolve("/api/v1/metrics"), "/metrics")
        self.assertEqual(apiv1.resolve("/api/v1/instance"), "/api/v1/instance")
        self.assertIsNone(apiv1.resolve("/api/v1/nope"))
        self.assertIsNone(apiv1.resolve("/api/v1"))
        self.assertIsNone(apiv1.resolve("/api/status"))
        self.assertTrue(apiv1.is_index("/api/v1/"))

    def test_scopes(self):
        self.assertEqual(apiv1.required_scope("GET", "/api/v1/status"), "read")
        self.assertEqual(apiv1.required_scope("HEAD", "/api/status"), "read")
        self.assertEqual(apiv1.required_scope("POST", "/api/settings"), "admin")
        self.assertEqual(apiv1.required_scope("POST", "/api/v1/settings"), "admin")
        self.assertEqual(apiv1.required_scope("POST", "/api/auth"), "session")
        self.assertEqual(apiv1.required_scope("GET", "/api/apikeys"), "session")
        self.assertEqual(apiv1.required_scope("POST", "/api/apikeys/irgendwas"), "session")
        self.assertEqual(apiv1.required_scope("POST", "/api/unbekannt"), "admin")
        self.assertEqual(apiv1.required_scope("GET", "/api/unbekannt"), "read")
        self.assertEqual(apiv1.required_scope("GET", "/healthz"), "public")

    def test_describe(self):
        doc = apiv1.describe()
        self.assertEqual(doc["version"], "1")
        paths = {(e["method"], e["path"]) for e in doc["endpoints"]}
        self.assertIn(("GET", "/api/v1/status"), paths)
        self.assertIn(("POST", "/api/v1/settings"), paths)
        for entry in doc["endpoints"]:
            self.assertIn(entry["scope"], {"public", "read", "admin", "session"})
            self.assertTrue(entry["description"])
            self.assertTrue(re.match(r"^/api/v1/[a-z/]+$", entry["path"]), entry["path"])

    def test_described_legacy_paths_exist_or_are_planned(self):
        """Jeder beschriebene alte Pfad ist in server.py geroutet – oder steht auf der Liste,
        die der Integrator noch verdrahten muss (wiring)."""
        server = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(encoding="utf-8")
        planned = {"/api/events", "/api/settings/notes", "/api/settings/notes/ack", "/api/apikeys",
                   "/api/apikeys/revoke", "/api/instance/rotate"}
        for entry in apiv1.ENDPOINTS:
            legacy = entry["legacy"]
            if legacy and legacy not in planned:
                self.assertIn(f'"{legacy}"', server, legacy)


if __name__ == "__main__":
    unittest.main()
