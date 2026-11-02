"""Kurzfassungen in /api/status für die Übersicht (1.4): Schaltsekunden-Liste und Benachrichtigungen."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import server  # noqa: E402


class LeapSummaryTest(unittest.TestCase):
    def test_keeps_only_overview_fields(self):
        info = {"available": True, "source": "list", "level": "ok", "reason": "ok", "days_left": 200,
                "expired": False, "expires_date": "2027-06-28", "tai_utc": 37,
                "path": "/usr/share/zoneinfo/leap-seconds.list", "entries": 28}
        out = server._leap_summary(info)
        self.assertEqual(out["days_left"], 200)
        self.assertEqual(out["tai_utc"], 37)
        self.assertNotIn("path", out)
        self.assertNotIn("entries", out)

    def test_disabled_list(self):
        out = server._leap_summary({"available": False, "source": "none", "level": "warn", "reason": "disabled"})
        self.assertEqual(out["reason"], "disabled")
        self.assertIsNone(out["days_left"])


class NotifySummaryTest(unittest.TestCase):
    def _with(self, channels):
        return mock.patch.object(server.notify, "api_status", return_value={"channels": channels, "running": True})

    def test_counts_only(self):
        channels = [
            {"id": "a", "type": "ntfy", "enabled": True, "status": {"state": "ok"}},
            {"id": "b", "type": "webhook", "enabled": True, "status": {"state": "error", "last_error": "x"}},
            {"id": "c", "type": "gotify", "enabled": False, "status": {"state": "off"}},
        ]
        with self._with(channels):
            out = server._notify_summary()
        self.assertEqual(out, {"channels": 3, "enabled": 2, "failing": 1})

    def test_no_channels(self):
        with self._with([]):
            self.assertEqual(server._notify_summary(), {"channels": 0, "enabled": 0, "failing": 0})

    def test_never_raises(self):
        with mock.patch.object(server.notify, "api_status", side_effect=RuntimeError("db")):
            self.assertEqual(server._notify_summary(), {"channels": 0, "enabled": 0, "failing": 0})


if __name__ == "__main__":
    unittest.main()
