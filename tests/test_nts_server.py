"""NTS-Server-Status: Zertifikatsdateien, openssl-Auswertung, Zähler und Hinweise."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import chrony  # noqa: E402
import insights  # noqa: E402

OPENSSL_OUT = """notAfter=Nov 11 13:40:28 2026 GMT
subject=CN = ntp.lan
X509v3 Subject Alternative Name:
    DNS:ntp.lan, DNS:zeit.lan, IP Address:192.168.1.10
"""
# Ältere OpenSSL-Versionen schreiben den Subject ohne Leerzeichen.
OPENSSL_OLD = "notAfter=Jan  5 00:00:00 2030 GMT\nsubject=/C=DE/CN=zeit.example\n"

SERVERSTATS = """NTP packets received       : 120
NTP packets dropped        : 0
Command packets received   : 5
Command packets dropped    : 0
Client log records dropped : 0
NTS-KE connections accepted: 7
NTS-KE connections dropped : 2
Authenticated NTP packets  : 95
"""


class OpensslParseTest(unittest.TestCase):
    def test_enddate_subject_and_san(self):
        info = chrony.parse_openssl_cert(OPENSSL_OUT)
        self.assertEqual(info["not_after"], 1794404428)
        self.assertEqual(info["common_name"], "ntp.lan")
        self.assertEqual(info["alt_names"], ["ntp.lan", "zeit.lan", "192.168.1.10"])

    def test_old_format_and_padded_day(self):
        info = chrony.parse_openssl_cert(OPENSSL_OLD)
        self.assertEqual(info["common_name"], "zeit.example")
        self.assertEqual(time.gmtime(info["not_after"])[:3], (2030, 1, 5))
        self.assertEqual(info["alt_names"], [])

    def test_garbage(self):
        info = chrony.parse_openssl_cert("unable to load certificate\n")
        self.assertIsNone(info["not_after"])
        self.assertIsNone(info["common_name"])

    def test_serverstats_labels(self):
        stats = chrony.parse_serverstats(SERVERSTATS)
        self.assertEqual(stats["nts_ke_connections_accepted"], 7)
        self.assertEqual(stats["nts_ke_connections_dropped"], 2)
        self.assertEqual(stats["authenticated_ntp_packets"], 95)


class NtsServerStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cert = self.dir / "nts.crt"
        self.key = self.dir / "nts.key"
        chrony._CERT_CACHE.clear()

    def tearDown(self):
        self.tmp.cleanup()
        chrony._CERT_CACHE.clear()

    def cfg(self, enabled=True):
        return {"nts_server_enable": enabled, "nts_server_cert": str(self.cert),
                "nts_server_key": str(self.key)}

    def test_disabled_is_cheap(self):
        with mock.patch.object(chrony, "serverstats") as stats, mock.patch.object(chrony.subprocess, "run") as run:
            result = chrony.nts_server_status(self.cfg(enabled=False))
        self.assertFalse(result["enabled"])
        stats.assert_not_called()
        run.assert_not_called()

    def test_missing_files(self):
        result = chrony.nts_server_status(self.cfg(), stats={})
        self.assertTrue(result["enabled"])
        self.assertFalse(result["cert_exists"])
        self.assertFalse(result["key_exists"])
        self.assertFalse(result["cert_readable"])
        self.assertIsNone(result["not_after"])
        self.assertIsNone(result["days_left"])

    def test_with_mocked_openssl_and_counters(self):
        self.cert.write_text("cert")
        self.key.write_text("key")
        completed = subprocess.CompletedProcess([], 0, stdout=OPENSSL_OUT, stderr="")
        with mock.patch.object(chrony, "OPENSSL", "/usr/bin/openssl"), \
                mock.patch.object(chrony.subprocess, "run", return_value=completed) as run, \
                mock.patch.object(chrony.time, "time", return_value=1794404428 - 3 * 86400):
            result = chrony.nts_server_status(self.cfg(), stats=chrony.parse_serverstats(SERVERSTATS))
            # Zweiter Aufruf kommt aus dem Cache, ohne openssl erneut zu starten.
            chrony.nts_server_status(self.cfg(), stats={})
        self.assertEqual(run.call_count, 1)
        args = run.call_args[0][0]
        self.assertEqual(args[:3], ["/usr/bin/openssl", "x509", "-noout"])
        self.assertIn(str(self.cert), args)
        self.assertEqual(result["not_after"], 1794404428)
        self.assertEqual(result["days_left"], 3.0)
        self.assertEqual(result["subject"], "ntp.lan")
        self.assertEqual(result["names"], ["ntp.lan", "zeit.lan", "192.168.1.10"])
        self.assertEqual(result["ke_accepted"], 7)
        self.assertEqual(result["ke_dropped"], 2)
        self.assertEqual(result["authenticated_packets"], 95)

    def test_openssl_fallback_without_ext(self):
        self.cert.write_text("cert")
        self.key.write_text("key")
        fail = subprocess.CompletedProcess([], 1, stdout="", stderr="x509: Unknown parameter -ext\n")
        ok = subprocess.CompletedProcess([], 0, stdout=OPENSSL_OLD, stderr="")
        with mock.patch.object(chrony, "OPENSSL", "/usr/bin/openssl"), \
                mock.patch.object(chrony.subprocess, "run", side_effect=[fail, ok]) as run:
            result = chrony.nts_server_status(self.cfg(), stats={})
        self.assertEqual(run.call_count, 2)
        self.assertNotIn("-ext", run.call_args[0][0])
        self.assertEqual(result["subject"], "zeit.example")
        self.assertIsNone(result["cert_error"])

    def test_openssl_timeout_and_missing_binary(self):
        self.cert.write_text("cert")
        self.key.write_text("key")
        with mock.patch.object(chrony, "OPENSSL", "/usr/bin/openssl"), \
                mock.patch.object(chrony.subprocess, "run", side_effect=subprocess.TimeoutExpired("openssl", 5)):
            result = chrony.nts_server_status(self.cfg(), stats={})
        self.assertIsNone(result["not_after"])
        self.assertTrue(result["cert_error"])
        chrony._CERT_CACHE.clear()
        with mock.patch.object(chrony, "OPENSSL", None):
            result = chrony.nts_server_status(self.cfg(), stats={})
        self.assertFalse(result["openssl"])
        self.assertTrue(result["cert_readable"])

    @unittest.skipIf(os.geteuid() == 0, "root liest auch Dateien ohne Leserecht")
    def test_unreadable(self):
        self.cert.write_text("cert")
        self.key.write_text("key")
        os.chmod(self.key, 0)
        result = chrony.nts_server_status(self.cfg(), stats={})
        self.assertTrue(result["key_exists"])
        self.assertFalse(result["key_readable"])

    @unittest.skipUnless(chrony.OPENSSL, "openssl fehlt")
    def test_real_openssl(self):
        made = subprocess.run(
            [chrony.OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
             "-keyout", str(self.key), "-out", str(self.cert), "-subj", "/CN=ntp.lan",
             "-addext", "subjectAltName=DNS:ntp.lan"], capture_output=True, timeout=60, check=False)
        if made.returncode != 0:
            self.skipTest("openssl req konnte kein Testzertifikat erzeugen")
        result = chrony.nts_server_status(self.cfg(), stats={})
        self.assertEqual(result["subject"], "ntp.lan")
        self.assertIn("ntp.lan", result["names"])
        self.assertTrue(29 <= result["days_left"] <= 30.1)


class NtsServerInsightTest(unittest.TestCase):
    def levels(self, nts):
        return {item["key"]: item["level"] for item in insights.nts_server_insights(nts)}

    def ok(self, **extra):
        base = {"enabled": True, "cert": "/config/nts.crt", "key": "/config/nts.key",
                "cert_exists": True, "key_exists": True, "cert_readable": True, "key_readable": True,
                "days_left": 200.0}
        base.update(extra)
        return base

    def test_disabled_or_fine(self):
        self.assertEqual(self.levels({"enabled": False}), {})
        self.assertEqual(self.levels(self.ok()), {})

    def test_missing_cert(self):
        items = insights.nts_server_insights(self.ok(cert_exists=False, cert_readable=False, days_left=None))
        self.assertEqual([i["level"] for i in items], ["warn"])
        self.assertIn("/config/nts.crt", items[0]["text"])

    def test_unreadable_key(self):
        self.assertEqual(self.levels(self.ok(key_readable=False)), {"nts_server_files": "warn"})

    def test_expiry(self):
        self.assertEqual(self.levels(self.ok(days_left=13.5)), {"nts_cert_expiring": "warn"})
        self.assertEqual(self.levels(self.ok(days_left=14.0)), {})
        self.assertEqual(self.levels(self.ok(days_left=-2.0)), {"nts_cert_expired": "crit"})

    def test_part_of_build(self):
        status = {"chrony_running": True, "tracking": {}, "sources": [], "system": {},
                  "nts_server": self.ok(days_left=-1.0), "ui": {"auth": {"enabled": True}}}
        keys = [i["key"] for i in insights.build(status, {"ntp_minsources": 1})]
        self.assertIn("nts_cert_expired", keys)


if __name__ == "__main__":
    unittest.main()
