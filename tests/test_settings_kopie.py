"""settings.json: letzte funktionierende Fassung als settings.json.bak, beschädigte Datei aufheben.

Ist settings.json vorhanden, aber nicht lesbar, sperrt das Dashboard (Schutzmodus, seit 1.9). Damit sich der
Stand wiederherstellen lässt, legt jedes erfolgreiche Speichern dieselbe Fassung als settings.json.bak ab;
die beschädigte Datei wird als settings.json.defekt-<Zeit> aufgehoben, bevor jemand sie ersetzt. Meldung und
Hinweis nennen beide Dateien."""

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_korrekturen import _TempData  # noqa: E402 – setzt auch die Pfade (_isolation)

import insights  # noqa: E402
import settings  # noqa: E402


def _bump(path):
    """mtime sicher ändern (der Zwischenspeicher prüft die mtime)."""
    now = time.time_ns() + 10 ** 9
    os.utime(path, ns=(now, now))


class GoodCopyTest(_TempData):
    def bak(self):
        return Path(settings.SETTINGS_FILE + ".bak")

    def test_save_keeps_identical_good_copy(self):
        settings.save({"web_title": "Erste"})
        self.assertTrue(self.bak().exists())
        self.assertEqual(self.bak().read_bytes(), Path(settings.SETTINGS_FILE).read_bytes())
        self.assertEqual(self.bak().stat().st_mode & 0o777, 0o600)
        settings.save({"web_title": "Zweite"})
        self.assertEqual(json.loads(self.bak().read_text(encoding="utf-8"))["values"]["web_title"], "Zweite")

    def test_password_and_replace_refresh_copy(self):
        settings.set_credentials("admin", "lang-und-eigen-42")
        self.assertIn("auth", json.loads(self.bak().read_text(encoding="utf-8")))
        settings.replace_values({"web_title": "Ersetzt"})
        self.assertEqual(self.bak().read_bytes(), Path(settings.SETTINGS_FILE).read_bytes())

    def test_no_leftover_temp_files(self):
        settings.save({"web_title": "Sauber"})
        names = sorted(os.listdir(self.tmp))
        self.assertEqual(names, ["settings.json", "settings.json.bak"])

    def test_broken_file_is_kept_and_message_names_copies(self):
        settings.set_credentials("admin", "lang-und-eigen-42")
        good = Path(settings.SETTINGS_FILE).read_bytes()
        broken = good[: len(good) // 2]
        Path(settings.SETTINGS_FILE).write_bytes(broken)
        _bump(settings.SETTINGS_FILE)
        error = settings.load_error()
        self.assertIsNotNone(error)
        self.assertIn("settings.json.bak", error)
        kept = [n for n in os.listdir(self.tmp) if n.startswith("settings.json.defekt-")]
        self.assertEqual(len(kept), 1, os.listdir(self.tmp))
        self.assertIn(kept[0], error)
        self.assertEqual((Path(self.tmp) / kept[0]).read_bytes(), broken)
        self.assertEqual((Path(self.tmp) / kept[0]).stat().st_mode & 0o777, 0o600)
        # Die Kopie ist unverändert die letzte gute Fassung, settings.json bleibt, wie sie ist.
        self.assertEqual(self.bak().read_bytes(), good)
        self.assertEqual(Path(settings.SETTINGS_FILE).read_bytes(), broken)
        self.assertTrue(settings.storage_info()["good_copy"])

    def test_same_broken_content_is_kept_once(self):
        Path(settings.SETTINGS_FILE).write_text("{", encoding="utf-8")
        self.assertIsNotNone(settings.load_error())
        for _ in range(3):
            settings._CACHE.update(mtime=None, data=None, error=None)   # wie ein Neustart des Dashboards
            _bump(settings.SETTINGS_FILE)
            self.assertIsNotNone(settings.load_error())
        kept = [n for n in os.listdir(self.tmp) if n.startswith("settings.json.defekt-")]
        self.assertEqual(len(kept), 1)
        self.assertNotIn("settings.json.bak", settings.load_error())   # es gibt keine
        self.assertFalse(settings.storage_info()["good_copy"])

    def test_at_most_a_few_broken_copies(self):
        for index in range(settings.DEFECT_KEEP + 3):
            Path(settings.SETTINGS_FILE).write_text("{" * (index + 1), encoding="utf-8")
            _bump(settings.SETTINGS_FILE)
            self.assertIsNotNone(settings.load_error())
        kept = [n for n in os.listdir(self.tmp) if n.startswith("settings.json.defekt-")]
        self.assertEqual(len(kept), settings.DEFECT_KEEP)

    def test_restoring_copy_unlocks(self):
        settings.save({"web_title": "Gut"})
        Path(settings.SETTINGS_FILE).write_text("kaputt", encoding="utf-8")
        _bump(settings.SETTINGS_FILE)
        self.assertIsNotNone(settings.load_error())
        Path(settings.SETTINGS_FILE).write_bytes(self.bak().read_bytes())
        _bump(settings.SETTINGS_FILE)
        self.assertIsNone(settings.load_error())
        self.assertEqual(settings.values()["web_title"], "Gut")

    def test_invalid_copy_is_not_offered(self):
        settings.save({"web_title": "Gut"})
        self.bak().write_text("auch kaputt", encoding="utf-8")
        Path(settings.SETTINGS_FILE).write_text("kaputt", encoding="utf-8")
        _bump(settings.SETTINGS_FILE)
        self.assertNotIn("settings.json.bak", settings.load_error())

    def test_link_as_copy_is_not_followed(self):
        target = Path(self.tmp) / "anderswo.json"
        target.write_text(json.dumps({"values": {}}), encoding="utf-8")
        os.symlink(target, self.bak())
        Path(settings.SETTINGS_FILE).write_text("kaputt", encoding="utf-8")
        _bump(settings.SETTINGS_FILE)
        self.assertNotIn("settings.json.bak", settings.load_error())
        settings._CACHE.update(mtime=None, data=None, error=None)
        os.unlink(settings.SETTINGS_FILE)
        settings.save({"web_title": "Neu"})
        self.assertFalse(self.bak().is_symlink())   # ersetzt, nicht durch den Link geschrieben
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"values": {}})

    def test_insight_mentions_copy(self):
        for good, expect in ((True, True), (False, False)):
            status = {"chrony_running": True, "ui": {"storage": {"error": "x", "good_copy": good}}}
            found = [i for i in insights.build(status, {}) if i.get("key") == "settings_unreadable"]
            self.assertTrue(found)
            self.assertEqual(found[0]["level"], "crit")
            self.assertEqual("settings.json.bak" in found[0]["text"], expect)

if __name__ == "__main__":
    unittest.main()
