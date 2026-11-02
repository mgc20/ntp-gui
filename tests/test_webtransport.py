"""Reverse Proxy: X-Forwarded-For nur von TRUSTED_PROXIES, HTTPS-Hinweis, Einstellung, Compose-Vorlage."""

import base64
import http.client
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from email.message import Message
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import apikeys  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import webtransport as wt  # noqa: E402


def headers(**values):
    msg = Message()
    for name, value in values.items():
        for item in value if isinstance(value, list) else [value]:
            msg[name.replace("_", "-")] = item
    return msg


TRUST_LOCAL = wt.parse_networks(["127.0.0.1/32", "::1/128"])


class ResolveTest(unittest.TestCase):
    def test_no_trust_by_default(self):
        info = wt.resolve("192.168.1.5", headers(X_Forwarded_For="203.0.113.9", X_Forwarded_Proto="https"), [])
        self.assertEqual(info["client"], "192.168.1.5")
        self.assertEqual(info["scheme"], "http")
        self.assertFalse(info["proxied"])
        self.assertTrue(info["untrusted_forward"])

    def test_plain_request_without_headers(self):
        info = wt.resolve("192.168.1.5", headers(), TRUST_LOCAL)
        self.assertEqual(info, {"client": "192.168.1.5", "scheme": "http", "proxied": False,
                                "untrusted_forward": False, "peer_loopback": False})

    def test_trusted_proxy_gives_browser_address_and_scheme(self):
        info = wt.resolve("127.0.0.1", headers(X_Forwarded_For="192.168.1.50", X_Forwarded_Proto="https"), TRUST_LOCAL)
        self.assertEqual(info["client"], "192.168.1.50")
        self.assertEqual(info["scheme"], "https")
        self.assertTrue(info["proxied"])

    def test_spoofed_left_entries_are_ignored(self):
        # Der Browser schreibt selbst „1.2.3.4“ hinein; der Proxy hängt die echte Adresse rechts an.
        info = wt.resolve("127.0.0.1", headers(X_Forwarded_For="1.2.3.4, 192.168.1.50"), TRUST_LOCAL)
        self.assertEqual(info["client"], "192.168.1.50")

    def test_chain_of_trusted_proxies(self):
        trusted = wt.parse_networks(["127.0.0.1/32", "192.168.1.2/32"])
        info = wt.resolve("127.0.0.1", headers(X_Forwarded_For=["10.9.9.9, 192.168.1.77", "192.168.1.2"]), trusted)
        self.assertEqual(info["client"], "192.168.1.77")

    def test_invalid_entry_stops_walk(self):
        info = wt.resolve("127.0.0.1", headers(X_Forwarded_For="192.168.1.50, <script>"), TRUST_LOCAL)
        self.assertEqual(info["client"], "127.0.0.1")
        info = wt.resolve("127.0.0.1", headers(X_Forwarded_For="unknown"), TRUST_LOCAL)
        self.assertEqual(info["client"], "127.0.0.1")

    def test_address_forms(self):
        self.assertEqual(str(wt.parse_ip("[2001:db8::1]:443")), "2001:db8::1")
        self.assertEqual(str(wt.parse_ip("192.168.1.5:5555")), "192.168.1.5")
        self.assertEqual(str(wt.parse_ip("fe80::1%eth0")), "fe80::1")
        self.assertEqual(str(wt.parse_ip("::ffff:127.0.0.1")), "127.0.0.1")
        self.assertIsNone(wt.parse_ip("x" * 100))
        self.assertIsNone(wt.parse_ip(""))

    def test_ipv6_proxy(self):
        info = wt.resolve("::1", headers(X_Forwarded_For="fd00::5", X_Forwarded_Proto="https"), TRUST_LOCAL)
        self.assertEqual(info["client"], "fd00::5")
        self.assertEqual(info["scheme"], "https")

    def test_unknown_scheme_ignored(self):
        info = wt.resolve("127.0.0.1", headers(X_Forwarded_For="192.168.1.5", X_Forwarded_Proto="gopher"), TRUST_LOCAL)
        self.assertEqual(info["scheme"], "http")

    def test_overlong_chain_capped(self):
        chain = ", ".join(["127.0.0.1"] * 500 + ["192.168.1.5"])
        info = wt.resolve("127.0.0.1", headers(X_Forwarded_For=chain), TRUST_LOCAL)
        self.assertEqual(info["client"], "192.168.1.5")

    def test_trust_all_is_dropped(self):
        self.assertEqual(wt.parse_networks(["0.0.0.0/0", "::/0", "kaputt"]), [])


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.watch = wt.TransportWatch(clock=lambda: 1000.0)

    def keys(self, now=1000.0):
        return [i["key"] for i in self.watch.insights(now=now)]

    def test_open_access_never_warns(self):
        self.watch.note({"scheme": "http"}, "open")
        self.assertEqual(self.keys(), [])

    def test_plain_http_with_password_warns(self):
        self.watch.note({"scheme": "http", "peer_loopback": False}, "basic")
        items = self.watch.insights(now=1000.0)
        self.assertEqual([i["key"] for i in items], ["web_plain_http"])
        self.assertEqual(items[0]["level"], "warn")
        self.assertIn("dein Passwort", items[0]["text"])
        self.assertIn("https.md", items[0]["text"])

    def test_api_key_named(self):
        self.watch.note({"scheme": "http"}, "key")
        self.assertIn("API-Schlüssel", self.watch.insights(now=1000.0)[0]["text"])

    def test_loopback_script_does_not_count(self):
        self.watch.note({"scheme": "http", "peer_loopback": True, "proxied": False}, "key")
        self.assertEqual(self.keys(), [])

    def test_https_via_proxy_is_fine(self):
        self.watch.note({"scheme": "https", "proxied": True}, "basic")
        self.assertEqual(self.keys(), [])
        self.assertEqual(self.watch.last_https, 1000.0)

    def test_proxied_plain_http_counts_even_from_loopback(self):
        self.watch.note({"scheme": "http", "peer_loopback": True, "proxied": True}, "basic")
        self.assertEqual(self.keys(), ["web_plain_http"])

    def test_untrusted_proxy_info(self):
        self.watch.note({"scheme": "http", "untrusted_forward": True, "peer_loopback": True}, "basic")
        items = self.watch.insights(now=1000.0)
        self.assertEqual([i["key"] for i in items], ["web_proxy_untrusted"])
        self.assertEqual(items[0]["level"], "info")

    def test_window_expires(self):
        self.watch.note({"scheme": "http"}, "basic")
        self.assertEqual(self.keys(now=1000.0 + wt.WINDOW - 1), ["web_plain_http"])
        self.assertEqual(self.keys(now=1000.0 + wt.WINDOW + 1), [])

    def test_fresh_watch_is_quiet(self):
        self.assertEqual(wt.TransportWatch().insights(), [])


class SettingTest(unittest.TestCase):
    def test_default_empty(self):
        field = settings.FIELDS["trusted_proxies"]
        self.assertEqual(field["default"], [])
        self.assertEqual(field["env"], "TRUSTED_PROXIES")

    def test_validation(self):
        convert = settings._as_proxy_list
        self.assertEqual(convert("127.0.0.1, ::1"), ["127.0.0.1/32", "::1/128"])
        self.assertEqual(convert(["192.168.1.2/32", "192.168.1.2"]), ["192.168.1.2/32"])
        self.assertEqual(convert(""), [])
        for bad in ("all", "0.0.0.0/0", "::/0", "proxy.lan", "1.2.3.4; rm -rf /"):
            with self.subTest(bad=bad), self.assertRaises(settings.ValidationError):
                convert(bad)
        with self.assertRaises(settings.ValidationError):
            convert([f"10.0.0.{i}" for i in range(settings.MAX_TRUSTED_PROXIES + 1)])

    def test_dashboard_save_validates(self):
        with self.assertRaises(settings.ValidationError):
            settings.validate({"trusted_proxies": "all"})
        self.assertEqual(settings.validate({"trusted_proxies": "127.0.0.1"})["trusted_proxies"], ["127.0.0.1/32"])

    def test_env_value(self):
        values = settings.values({"TRUSTED_PROXIES": "127.0.0.1/32,::1/128"})
        self.assertEqual(values["trusted_proxies"], ["127.0.0.1/32", "::1/128"])
        self.assertEqual(settings.values({})["trusted_proxies"], [])


class HandlerTest(unittest.TestCase):
    """Am echten Handler: Proxy-Köpfe, Hinweis, Zugriffsprotokoll, Kataloge als JSON."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"}),
        ]
        for patch in cls.patches:
            patch.start()
        os.environ.pop("WEB_READONLY", None)
        os.environ.pop("TRUSTED_PROXIES", None)
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        wt.WATCH.reset()
        cls.tmp.cleanup()

    def setUp(self):
        wt.WATCH.reset()
        try:
            os.remove(settings.SETTINGS_FILE)
        except OSError:
            pass

    def get(self, path, extra=None, auth=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = dict(extra or {})
        if auth:
            hdrs["Authorization"] = "Basic " + base64.b64encode(b"admin:geheim123").decode()
        conn.request("GET", path, headers=hdrs)
        resp = conn.getresponse()
        body = resp.read()
        ctype = resp.getheader("Content-Type")
        conn.close()
        return resp.status, ctype, body

    def trust_local(self):
        settings.save({"trusted_proxies": ["127.0.0.1/32", "::1/128"]})

    def test_local_plain_request_is_quiet(self):
        self.assertEqual(self.get("/api/v1")[0], 200)
        self.assertEqual(wt.WATCH.insights(), [])

    def test_untrusted_forward_headers_ignored_but_reported(self):
        status, _, _ = self.get("/api/v1", {"X-Forwarded-For": "192.168.1.50", "X-Forwarded-Proto": "https"})
        self.assertEqual(status, 200)
        self.assertEqual([i["key"] for i in wt.WATCH.insights()], ["web_proxy_untrusted"])
        self.assertIsNone(wt.WATCH.last_https)

    def test_trusted_proxy_https(self):
        self.trust_local()
        self.get("/api/v1", {"X-Forwarded-For": "192.168.1.50", "X-Forwarded-Proto": "https"})
        self.assertIsNotNone(wt.WATCH.last_https)
        self.assertEqual(wt.WATCH.insights(), [])

    def test_trusted_proxy_plain_http_warns_in_status_insights(self):
        self.trust_local()
        self.get("/api/v1", {"X-Forwarded-For": "192.168.1.50", "X-Forwarded-Proto": "http"})
        keys = [i["key"] for i in wt.WATCH.insights()]
        self.assertEqual(keys, ["web_plain_http"])
        merged = server.combine_insights(wt.WATCH.insights())
        self.assertEqual(merged[0]["action"], "settings")

    def test_wrong_password_is_not_noted(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/v1", headers={
            "Authorization": "Basic " + base64.b64encode(b"admin:falsch").decode(),
            "X-Forwarded-For": "192.168.1.50"})
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()
        self.assertEqual(wt.WATCH.insights(), [])

    def test_access_log_shows_browser_behind_trusted_proxy(self):
        self.trust_local()
        lines = []
        with mock.patch.dict(os.environ, {"WEB_ACCESS_LOG": "true"}), \
                mock.patch.object(server.Handler, "log_date_time_string", lambda self: "jetzt"), \
                mock.patch("sys.stderr") as err:
            err.write.side_effect = lines.append
            self.get("/api/v1", {"X-Forwarded-For": "1.2.3.4, 192.168.1.50"})
        text = "".join(lines)
        self.assertIn("192.168.1.50", text)
        self.assertNotIn("1.2.3.4", text)

    def test_access_log_without_trust_shows_peer(self):
        lines = []
        with mock.patch.dict(os.environ, {"WEB_ACCESS_LOG": "true"}), mock.patch("sys.stderr") as err:
            err.write.side_effect = lines.append
            self.get("/api/v1", {"X-Forwarded-For": "192.168.1.50"})
        text = "".join(lines)
        self.assertIn("127.0.0.1", text)
        self.assertNotIn("192.168.1.50", text)

    def test_catalogs_served_as_json(self):
        status, ctype, body = self.get("/static/i18n/de.json")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("application/json"))
        self.assertIn("nav", json.loads(body))
        self.assertEqual(self.get("/static/i18n/../../server.py")[0], 404)


class ComposeTemplateTest(unittest.TestCase):
    """Die Caddy-Vorlage folgt der Kommentar-Regel der Datei und ist vollständig."""

    TEXT = (ROOT / "docker-compose.all-in-one.yml").read_text(encoding="utf-8")

    def uncommented(self):
        return re.sub(r"(?m)^( +)#  ", r"\1", self.TEXT)

    def test_caddy_block_present(self):
        text = self.uncommented()
        self.assertRegex(text, r"(?m)^  caddy:\n")
        self.assertIn('"--internal-certs"', text)
        self.assertRegex(text, r"(?m)^  caddy-data:$")
        self.assertRegex(text, r'(?m)^      WEB_BIND: "127\.0\.0\.1"$')
        self.assertRegex(text, r'(?m)^      TRUSTED_PROXIES: "127\.0\.0\.1/32,::1/128"$')
        self.assertRegex(text, r"(?m)^    image: caddy:\d+\.\d+\.\d+$")  # gepinnt, nie :latest

    def test_default_file_has_no_caddy(self):
        self.assertNotRegex(self.TEXT, r"(?m)^  caddy:")
        self.assertNotRegex(self.TEXT, r"(?m)^\s+TRUSTED_PROXIES:")

    def test_doc_exists_and_mentions_proxies(self):
        doc = (ROOT / "docs" / "integrationen" / "https.md").read_text(encoding="utf-8")
        for word in ("Caddy", "Nginx Proxy Manager", "Zoraxy", "Traefik", "TRUSTED_PROXIES", "WEB_ALLOWED_HOSTS",
                     "root.crt", "--internal-certs"):
            self.assertIn(word, doc)


if __name__ == "__main__":
    unittest.main()
