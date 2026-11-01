"""NTS-Server hinter einem Reverse Proxy: Einstellungen, chrony.conf, Zertifikatskopie,
Namensprüfung (auch Wildcard), Hinweise und die Zertifikatsüberwachung im Entrypoint."""

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import chrony  # noqa: E402
import confgen  # noqa: E402
import insights  # noqa: E402
import settings  # noqa: E402

FIELDS = {field["key"]: field for field in settings.SCHEMA}


def convert(key, value):
    return FIELDS[key]["convert"](value)


class SettingsTest(unittest.TestCase):
    def test_fields_exist_with_env(self):
        self.assertEqual(FIELDS["nts_server_name"]["env"], "NTS_SERVER_NAME")
        self.assertEqual(FIELDS["nts_server_port"]["env"], "NTS_SERVER_PORT")
        self.assertEqual(FIELDS["nts_server_port"]["default"], 4460)
        for key in ("nts_server_name", "nts_server_port", "nts_server_cert", "nts_server_key"):
            self.assertEqual(FIELDS[key]["section"], "nts")
            self.assertTrue(FIELDS[key]["help"])

    def test_cert_paths_accepted(self):
        for path in ("/config/nts.crt", "/certs/live/npm-1/fullchain.pem",
                     "/certs/zoraxy/time.example.com.pem", "/certs/_.example.com.key",
                     "/etc/letsencrypt/live/time.example.com/privkey.pem"):
            self.assertEqual(convert("nts_server_cert", f"  {path} "), path)

    def test_cert_paths_rejected(self):
        for bad in ("", "config/nts.crt", "/etc/shadow", "/config/../etc/shadow",
                    "/certs/./x.pem", "/config/", "/config", "/certs//x.pem",
                    "/config/a b.pem", "/config/x.pem\nntsport 1", "/config/x.pem;rm",
                    "/certs/x$(id).pem", "/configx/nts.crt", "/config/x\x00.pem"):
            with self.subTest(path=bad), self.assertRaises(settings.ValidationError):
                convert("nts_server_key", bad)

    def test_name(self):
        self.assertEqual(convert("nts_server_name", ""), "")
        self.assertEqual(convert("nts_server_name", " Time.Example.COM. "), "time.example.com")
        self.assertEqual(convert("nts_server_name", "192.0.2.5"), "192.0.2.5")
        for bad in ("time.example.com\nntsport 1", "time example.com", "*.example.com",
                    "evil;x", "-bad.example.com", "a" * 300):
            with self.subTest(name=bad), self.assertRaises(settings.ValidationError):
                convert("nts_server_name", bad)

    def test_port(self):
        self.assertEqual(convert("nts_server_port", "4461"), 4461)
        for bad in ("0", "65536", "abc", "44 60"):
            with self.subTest(port=bad), self.assertRaises(settings.ValidationError):
                convert("nts_server_port", bad)

    def test_env(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with mock.patch.object(settings, "SETTINGS_FILE", os.path.join(tmp, "settings.json")):
            values = settings.values({"NTS_SERVER_NAME": "time.example.com",
                                      "NTS_SERVER_PORT": "4461",
                                      "NTS_SERVER_CERT": "/certs/live/npm-3/fullchain.pem"})
            self.assertEqual(values["nts_server_name"], "time.example.com")
            self.assertEqual(values["nts_server_port"], 4461)
            self.assertEqual(values["nts_server_cert"], "/certs/live/npm-3/fullchain.pem")
            # Ungültige Umgebungswerte fallen auf den Standard zurück.
            values = settings.values({"NTS_SERVER_CERT": "/etc/shadow", "NTS_SERVER_PORT": "0"})
            self.assertEqual(values["nts_server_cert"], "/config/nts.crt")
            self.assertEqual(values["nts_server_port"], 4460)


def base_cfg(**extra):
    tmp = tempfile.mkdtemp()
    with mock.patch.object(settings, "SETTINGS_FILE", os.path.join(tmp, "settings.json")):
        cfg = settings.values({})
    shutil.rmtree(tmp)
    cfg.update(extra)
    return cfg


class RenderTest(unittest.TestCase):
    def render(self, **extra):
        cfg = base_cfg(nts_server_enable=True, **extra)
        return confgen.render_chrony(cfg, {}, warn=lambda *a: None,
                                     nts_files=("/var/lib/chrony/nts-certs/server.crt",
                                                "/var/lib/chrony/nts-certs/server.key"))

    def test_defaults(self):
        text = self.render()
        self.assertIn("ntsservercert /var/lib/chrony/nts-certs/server.crt\n", text)
        self.assertIn("ntsserverkey /var/lib/chrony/nts-certs/server.key\n", text)
        self.assertNotIn("ntsport", text)
        self.assertNotIn("ntsntpserver", text)

    def test_name_and_port(self):
        text = self.render(nts_server_name="time.example.com", nts_server_port=4461)
        self.assertIn("\nntsport 4461\n", text)
        self.assertIn("\nntsntpserver time.example.com\n", text)

    def test_no_files_no_server(self):
        cfg = base_cfg(nts_server_enable=True, nts_server_name="time.example.com")
        text = confgen.render_chrony(cfg, {}, warn=lambda *a: None, nts_files=())
        self.assertNotIn("ntsservercert", text)
        self.assertNotIn("ntsntpserver", text)

    def test_legacy_paths_when_not_prepared(self):
        warnings = []
        cfg = base_cfg(nts_server_enable=True, nts_server_cert="/config/missing.crt")
        text = confgen.render_chrony(cfg, {}, warn=lambda *a: warnings.append(a))
        self.assertNotIn("ntsservercert", text)
        self.assertTrue(warnings)


def _openssl_pair(directory: Path, name: str):
    openssl = shutil.which("openssl")
    if not openssl:
        return None
    cert, key = directory / f"{name}.crt", directory / f"{name}.key"
    proc = subprocess.run([openssl, "req", "-x509", "-newkey", "ec", "-pkeyopt",
                           "ec_paramgen_curve:prime256v1", "-nodes", "-days", "2",
                           "-subj", f"/CN={name}.example.com", "-keyout", str(key),
                           "-out", str(cert)], capture_output=True, timeout=30, check=False)
    return (cert, key) if proc.returncode == 0 else None


class PrepareFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.target = self.tmp / "nts-certs"
        self.warnings = []

    def prepare(self, cert, key):
        cfg = {"nts_server_enable": True, "nts_server_cert": str(cert), "nts_server_key": str(key)}
        return confgen.prepare_nts_files(cfg, str(self.target),
                                         warn=lambda *a: self.warnings.append(a[1]), ids=None)

    def test_disabled(self):
        self.assertIsNone(confgen.prepare_nts_files({"nts_server_enable": False}))

    def test_missing(self):
        self.assertIsNone(self.prepare(self.tmp / "a.crt", self.tmp / "a.key"))
        self.assertIn("fehlt", self.warnings[0])

    def test_not_pem(self):
        (self.tmp / "a.crt").write_text("hallo")
        (self.tmp / "a.key").write_text("-----BEGIN PRIVATE KEY-----\n")
        self.assertIsNone(self.prepare(self.tmp / "a.crt", self.tmp / "a.key"))
        self.assertFalse(self.target.exists())

    def test_symlink_outside_roots_refused(self):
        outside = self.tmp / "secret"
        outside.write_text("-----BEGIN CERTIFICATE-----\n")
        link = self.tmp / "link.crt"
        link.symlink_to(outside)
        (self.tmp / "a.key").write_text("-----BEGIN PRIVATE KEY-----\n")
        self.assertIsNone(self.prepare(link, self.tmp / "a.key"))
        self.assertIn("außerhalb", self.warnings[0])

    def test_copy_private_and_mismatch(self):
        first = _openssl_pair(self.tmp, "eins")
        second = _openssl_pair(self.tmp, "zwei")
        if not first or not second:
            self.skipTest("openssl kann kein Testzertifikat erzeugen")
        paths = self.prepare(*first)
        self.assertEqual(paths, (str(self.target / "server.crt"), str(self.target / "server.key")))
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o750)
        for path in paths:
            # Nur lesbar für die Gruppe _chrony: sonst meldet chronyd Schreibzugriff.
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)
        self.assertEqual(Path(paths[0]).read_bytes(), first[0].read_bytes())
        self.assertEqual(Path(paths[1]).read_bytes(), first[1].read_bytes())
        # Mitten in der Erneuerung: neues Zertifikat, alter Schlüssel -> alte Kopien bleiben.
        self.assertEqual(self.prepare(second[0], first[1]), paths)
        self.assertEqual(Path(paths[0]).read_bytes(), first[0].read_bytes())
        self.assertIn("passen", self.warnings[-1])
        # Ohne frühere Kopien bleibt der NTS-Server bei einem falschen Paar aus.
        shutil.rmtree(self.target)
        self.assertIsNone(self.prepare(second[0], first[1]))

    def test_copy_failure_falls_back_to_originals(self):
        pair = _openssl_pair(self.tmp, "eins")
        if not pair:
            self.skipTest("openssl kann kein Testzertifikat erzeugen")
        blocker = self.tmp / "datei"
        blocker.write_text("x")
        cfg = {"nts_server_enable": True, "nts_server_cert": str(pair[0]),
               "nts_server_key": str(pair[1])}
        result = confgen.prepare_nts_files(cfg, str(blocker / "sub"), warn=lambda *a: None, ids=None)
        self.assertEqual(result, (str(pair[0]), str(pair[1])))

    def test_watch_paths(self):
        cfg = {"nts_server_enable": True, "nts_server_cert": "/certs/a.pem",
               "nts_server_key": "/certs/a.key"}
        with mock.patch.object(confgen, "CUSTOM_CHRONY", str(self.tmp / "keine.conf")):
            self.assertEqual(confgen.nts_watch_paths(cfg), ["/certs/a.pem", "/certs/a.key"])
            self.assertEqual(confgen.nts_watch_paths({"nts_server_enable": False}), [])


class NameMatchTest(unittest.TestCase):
    def test_exact_and_case(self):
        self.assertTrue(chrony.cert_covers_name("Time.Example.com.", ["time.example.com"]))
        self.assertFalse(chrony.cert_covers_name("time.example.com", ["zeit.example.com"]))
        self.assertFalse(chrony.cert_covers_name("", ["time.example.com"]))

    def test_wildcard(self):
        names = ["*.example.com"]
        self.assertTrue(chrony.cert_covers_name("time.example.com", names))
        self.assertFalse(chrony.cert_covers_name("example.com", names))
        self.assertFalse(chrony.cert_covers_name("a.time.example.com", names))
        self.assertFalse(chrony.cert_covers_name("time.example.org", names))
        self.assertFalse(chrony.cert_covers_name("time.com", ["*.com"]))
        self.assertFalse(chrony.cert_covers_name("timeexample.com", names))

    def test_ip(self):
        self.assertTrue(chrony.cert_covers_name("2001:db8::1", ["2001:DB8:0:0:0:0:0:1"]))
        self.assertTrue(chrony.cert_covers_name("192.0.2.5", ["time.lan", "192.0.2.5"]))
        self.assertFalse(chrony.cert_covers_name("192.0.2.5", ["*.0.2.5"]))

    def test_issuer_parse(self):
        info = chrony.parse_openssl_cert(
            "issuer=C = US, O = Let's Encrypt, CN = R11\nsubject=CN = time.example.com\n")
        self.assertEqual(info["issuer"], "Let's Encrypt – R11")
        info = chrony.parse_openssl_cert("issuer=/C=DE/O=Heim/CN=Heim CA\n")
        self.assertEqual(info["issuer"], "Heim – Heim CA")


OPENSSL_LE = """notAfter=Nov 11 13:40:28 2026 GMT
subject=CN = time.example.com
issuer=C = US, O = Let's Encrypt, CN = R11
X509v3 Subject Alternative Name:
    DNS:*.example.com, DNS:example.com
"""


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cert, self.key = self.tmp / "c.pem", self.tmp / "k.pem"
        self.cert.write_text("c")
        self.key.write_text("k")
        chrony._CERT_CACHE.clear()
        self.addCleanup(chrony._CERT_CACHE.clear)

    def status(self, name, stdout=OPENSSL_LE, port=4460):
        cfg = {"nts_server_enable": True, "nts_server_cert": str(self.cert),
               "nts_server_key": str(self.key), "nts_server_name": name, "nts_server_port": port}
        chrony._CERT_CACHE.clear()
        done = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
        with mock.patch.object(chrony, "OPENSSL", "/usr/bin/openssl"), \
                mock.patch.object(chrony.subprocess, "run", return_value=done) as run:
            result = chrony.nts_server_status(cfg, stats={})
        self.assertIn("-issuer", run.call_args[0][0])
        return result

    def test_fields(self):
        result = self.status("time.example.com", port=4461)
        self.assertEqual(result["name"], "time.example.com")
        self.assertEqual(result["port"], 4461)
        self.assertTrue(result["name_matches_cert"])
        self.assertEqual(result["cert_issuer"], "Let's Encrypt – R11")
        self.assertFalse(result["cert_self_signed"])
        # bestehende Felder bleiben
        for key in ("cert_exists", "key_readable", "days_left", "subject", "names", "ke_accepted"):
            self.assertIn(key, result)

    def test_mismatch_and_unknown(self):
        self.assertFalse(self.status("time.example.org")["name_matches_cert"])
        self.assertIsNone(self.status("")["name_matches_cert"])
        self.assertIsNone(self.status("time.example.com", stdout="")["name_matches_cert"])

    def test_cn_only_without_san(self):
        result = self.status("time.example.com",
                             stdout="subject=CN = time.example.com\nissuer=CN = time.example.com\n")
        self.assertTrue(result["name_matches_cert"])
        self.assertTrue(result["cert_self_signed"])

    def test_disabled_still_reports_name(self):
        result = chrony.nts_server_status({"nts_server_enable": False, "nts_server_name": "a.b"})
        self.assertEqual((result["name"], result["port"]), ("a.b", 4460))


class InsightTest(unittest.TestCase):
    def base(self, **extra):
        nts = {"enabled": True, "cert": "/certs/c.pem", "key": "/certs/k.pem",
               "cert_exists": True, "key_exists": True, "cert_readable": True,
               "key_readable": True, "days_left": 80.0, "name": "time.example.com",
               "name_matches_cert": True, "names": ["*.example.com"]}
        nts.update(extra)
        return {i["key"]: i for i in insights.nts_server_insights(nts)}

    def test_fine(self):
        self.assertEqual(self.base(), {})
        self.assertEqual(self.base(name_matches_cert=None), {})

    def test_mismatch(self):
        items = self.base(name="time.example.org", name_matches_cert=False)
        self.assertEqual(items["nts_name_mismatch"]["level"], "warn")
        self.assertIn("Zertifikat passt nicht zum Namen time.example.org", items["nts_name_mismatch"]["text"])
        self.assertIn("*.example.com", items["nts_name_mismatch"]["text"])

    def test_no_name(self):
        items = self.base(name="", name_matches_cert=None)
        self.assertEqual(items["nts_no_name"]["level"], "info")
        self.assertIn("ntsntpserver", items["nts_no_name"]["text"])
        # Fehlt das Zertifikat, ist das wichtiger als der Namenshinweis.
        self.assertNotIn("nts_no_name", self.base(name="", cert_exists=False))

    def test_expiry_rules_stay(self):
        self.assertEqual(self.base(days_left=3.0)["nts_cert_expiring"]["level"], "warn")
        self.assertEqual(self.base(days_left=-1.0)["nts_cert_expired"]["level"], "crit")


def _entrypoint_functions(*names):
    text = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    chunks = []
    for name in names:
        match = re.search(rf"^{name}\(\) \{{.*?^\}}$", text, re.S | re.M)
        assert match, name
        chunks.append(match.group(0))
    return "\n".join(chunks)


@unittest.skipUnless(shutil.which("bash") and shutil.which("stat"), "bash/stat fehlen")
class EntrypointWatchTest(unittest.TestCase):
    def test_change_needs_to_settle(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        cert, key = tmp / "c.pem", tmp / "k.pem"
        cert.write_text("a")
        key.write_text("b")
        script = _entrypoint_functions("file_signature", "check_nts_cert") + f"""
set -euo pipefail
NTS_CERT_EVERY=60; NTS_CERT_SETTLE=10; NEXT_NTS_CERT=0; NTS_CERT_PENDING=""
NTS_WATCH="{cert} {key}"
NTS_CERT_SIG="$(file_signature $NTS_WATCH)"
r() {{ if check_nts_cert "$1"; then echo "$1:reload:$NEXT_NTS_CERT"; else echo "$1:no:$NEXT_NTS_CERT"; fi; }}
r 100
printf 'neu' > "{cert}"; touch -d '2030-01-01' "{cert}"
r 160
r 170
r 230
rm "{key}"
r 290
r 300
NTS_WATCH=""
r 400
"""
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                             timeout=30, check=True).stdout.split()
        self.assertEqual(out, ["100:no:160", "160:no:170", "170:reload:230", "230:no:290",
                               "290:no:300", "300:reload:360", "400:no:360"])


if __name__ == "__main__":
    unittest.main()
