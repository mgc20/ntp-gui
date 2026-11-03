"""API-Schlüssel, /api/v1 und Ereignisse aus Zustandswechseln – am echten HTTP-Handler.

Läuft ohne chronyd: nur Routen, die keine chronyc-Abfrage brauchen.
"""

import base64
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, fake_hostnames, stop_http_server  # noqa: E402

import apikeys  # noqa: E402
import diagnostics  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import statewatch  # noqa: E402
import store  # noqa: E402


class ApiAuthTest(unittest.TestCase):
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
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.read_id, cls.read_key = apikeys.create("Lesen", "read")
        cls.admin_id, cls.admin_key = apikeys.create("Verwalten", "admin")

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = json.dumps(body).encode() if body is not None else None
        hdrs = dict(headers or {})
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw
        return resp.status, payload

    def basic(self):
        return {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode(), "X-NTP-GUI": "1"}

    @staticmethod
    def bearer(token):
        return {"Authorization": f"Bearer {token}"}

    def test_without_login_denied(self):
        self.assertEqual(self.request("GET", "/api/v1/instance")[0], 401)

    def test_read_key_reads_but_cannot_write(self):
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=self.bearer(self.read_key))[0], 200)
        status, payload = self.request("POST", "/api/v1/reload", {}, self.bearer(self.read_key))
        self.assertEqual(status, 403)
        self.assertEqual(payload["scope_required"], "admin")

    def test_admin_key_writes_without_csrf_header(self):
        status, payload = self.request("POST", "/api/v1/reload", {}, self.bearer(self.admin_key))
        self.assertEqual(status, 200)
        self.assertIn("reload_triggered", payload)

    def test_key_post_still_needs_json(self):
        status, _ = self.request("POST", "/api/v1/reload", None,
                                 dict(self.bearer(self.admin_key), **{"Content-Type": "text/plain"}))
        self.assertEqual(status, 403)

    def test_session_endpoints_never_with_key(self):
        for path, body in (("/api/apikeys", {"name": "x", "scope": "admin"}), ("/api/auth", {"clear": True}),
                           ("/api/instance/rotate", {}), ("/api/keys/revoke", {"id": self.read_id})):
            with self.subTest(path=path):
                self.assertEqual(self.request("POST", path, body, self.bearer(self.admin_key))[0], 403)
        self.assertEqual(self.request("GET", "/api/apikeys", headers=self.bearer(self.admin_key))[0], 403)

    def test_basic_login_manages_keys(self):
        status, payload = self.request("GET", "/api/keys", headers=self.basic())
        self.assertEqual(status, 200)
        self.assertIn(self.admin_id, [k["id"] for k in payload["keys"]])
        self.assertNotIn("token", json.dumps(payload))

    def test_bad_and_revoked_keys(self):
        status, _ = self.request("GET", "/api/v1/instance", headers=self.bearer("ntpg_AAAAAAAAbbbbbbbbbbbbbbbbbbbbbbbb"))
        self.assertEqual(status, 401)
        key_id, token = apikeys.create("Kurzlebig", "read")
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=self.bearer(token))[0], 200)
        status, _ = self.request("POST", "/api/apikeys/revoke", {"id": key_id}, self.basic())
        self.assertEqual(status, 200)
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=self.bearer(token))[0], 401)

    def test_basic_post_keeps_csrf(self):
        headers = self.basic()
        del headers["X-NTP-GUI"]
        self.assertEqual(self.request("POST", "/api/reload", {}, headers)[0], 403)

    def test_v1_index_and_unknown(self):
        status, payload = self.request("GET", "/api/v1", headers=self.basic())
        self.assertEqual(status, 200)
        paths = {e["path"] for e in payload["endpoints"]}
        for path in ("/api/v1/status", "/api/v1/events", "/api/v1/diagnostics/bundle", "/api/v1/gps/autocal"):
            self.assertIn(path, paths)
        self.assertEqual(self.request("GET", "/api/v1/gibtsnicht", headers=self.basic())[0], 404)

    def test_settings_notes_in_schema(self):
        status, payload = self.request("GET", "/api/v1/settings", headers=self.bearer(self.read_key))
        self.assertEqual(status, 200)
        self.assertEqual(payload["schema_version"], settings.SCHEMA_VERSION)
        self.assertIsInstance(payload["notes"], list)

    def test_doh_path_masked_for_read_key(self):
        """DNS-SEC-4: Konto-Kennung im DoH-Pfad (NextDNS) nur für Admin/Passwort sichtbar."""
        url = "https://dns.nextdns.io/abc123"
        settings.save({"dns_doh": [url]})
        self.addCleanup(settings.save, {"dns_doh": []})

        def doh(payload):
            return next(f for f in payload["fields"] if f["key"] == "dns_doh")["value"]

        for path in ("/api/settings", "/api/v1/settings"):
            status, payload = self.request("GET", path, headers=self.bearer(self.read_key))
            self.assertEqual(status, 200)
            self.assertEqual(doh(payload), ["https://dns.nextdns.io/…"], path)
        status, payload = self.request("GET", "/api/v1/settings/export", headers=self.bearer(self.read_key))
        self.assertEqual(payload["values"]["dns_doh"], ["https://dns.nextdns.io/…"])
        self.assertEqual(payload["masked"], ["dns_doh"])
        self.assertNotIn("abc123", json.dumps(payload))
        # Admin-Schlüssel und Passwort sehen den vollen Wert (Bearbeiten im Dashboard)
        self.assertEqual(doh(self.request("GET", "/api/v1/settings", headers=self.bearer(self.admin_key))[1]), [url])
        self.assertEqual(doh(self.request("GET", "/api/settings", headers=self.basic())[1]), [url])
        status, full = self.request("GET", "/api/settings/export", headers=self.basic())
        self.assertEqual(full["values"]["dns_doh"], [url])
        self.assertNotIn("masked", full)
        # Import einer gekürzten Sicherung überschreibt den echten Wert nicht
        status, _ = self.request("POST", "/api/v1/settings/import", payload, self.bearer(self.admin_key))
        self.assertEqual(status, 200)
        self.assertEqual(settings.values()["dns_doh"], [url])


class HostCheckTest(unittest.TestCase):
    """DNS-Rebinding: ohne Passwort nur bekannte bzw. lokale Host-Namen."""

    def test_host_allowed_rules(self):
        fake_hostnames(self, "ntpbox", "ntpbox.example.net")
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": ""}):
            for ok in ("192.0.2.5:8080", "127.0.0.1", "[::1]:8080", "[fe80::1%eth0]:80", "localhost:8080",
                       "app.localhost", "raspberrypi:8080", "ntpbox", "NTPBOX.example.net.", "pi.local",
                       "pi.lan:8080", "pi.home.arpa", "zeit.internal", "", None):
                with self.subTest(ok=ok):
                    self.assertTrue(server.host_allowed(ok))
            for bad in ("attacker.example:8080", "rebind.evil.com", "192.0.2.5.nip.io", "localhost.evil.com",
                        "fritz.box.evil.com", "local.evil.com",
                        # ".box" ist eine öffentliche Endung – fritz.box war schon fremd registriert
                        "pi.fritz.box", "fritz.box"):
                with self.subTest(bad=bad):
                    self.assertFalse(server.host_allowed(bad))
            self.assertTrue(server.host_allowed("zeit.example.org", nts_name="Zeit.Example.org"))
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "zeit.example.org, *.mein-dorf.us"}):
            self.assertTrue(server.host_allowed("zeit.example.org:8080"))
            self.assertTrue(server.host_allowed("ntp.mein-dorf.us"))
            self.assertTrue(server.host_allowed("mein-dorf.us"))
            self.assertFalse(server.host_allowed("evil-mein-dorf.us"))
            self.assertFalse(server.host_allowed("attacker.example"))
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "*"}):
            self.assertTrue(server.host_allowed("attacker.example"))
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "*.fritz.box"}):
            self.assertTrue(server.host_allowed("pi.fritz.box"))

    def test_dashboard_allow_list_merges_with_env(self):
        """1.5.1: „Erlaubte Namen“ aus dem Dashboard gelten zusätzlich zu WEB_ALLOWED_HOSTS."""
        fake_hostnames(self, "ntpbox", "ntpbox.example.net")
        extra = ["uhr.example.org", "*.mein-dorf.us"]
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "zeit.example.org"}):
            self.assertTrue(server.host_allowed("uhr.example.org:8080", extra=extra))
            self.assertTrue(server.host_allowed("UHR.example.org.", extra=extra))
            self.assertTrue(server.host_allowed("pi.mein-dorf.us", extra=extra))
            self.assertTrue(server.host_allowed("mein-dorf.us", extra=extra))
            self.assertTrue(server.host_allowed("zeit.example.org", extra=extra), "Umgebung gilt weiter")
            self.assertFalse(server.host_allowed("evil-mein-dorf.us", extra=extra))
            self.assertFalse(server.host_allowed("l.example.com", extra=extra))
            self.assertFalse(server.host_allowed("attacker.example", extra=extra))
            self.assertFalse(server.host_allowed("uhr.example.org"), "ohne Dashboard-Eintrag")
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": ""}):
            # „*“ zählt nur aus der Umgebung – ein (z. B. von Hand in settings.json geschriebenes) „*“ nicht.
            self.assertFalse(server.host_allowed("attacker.example", extra=["*", "", None]))

    def test_dashboard_allow_list_needs_no_dns(self):
        """host_allowed bleibt schnell: kein DNS je Anfrage, auch nicht für Dashboard-Einträge."""
        fake_hostnames(self, "ntpbox", "ntpbox.example.net")
        self.assertIn("ntpbox.example.net", diagnostics.own_hostnames(wait=5.0))  # Hintergrund-Abfrage fertig

        def no_dns(*_args, **_kwargs):
            raise AssertionError("DNS-Abfrage in host_allowed")

        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": ""}), \
                mock.patch.object(server.socket, "getaddrinfo", no_dns), \
                mock.patch.object(server.socket, "gethostbyname", no_dns), \
                mock.patch.object(server.socket, "getfqdn", no_dns):
            started = time.monotonic()
            for _ in range(2000):
                server.host_allowed("rebind.evil.com", extra=["zeit.example.org", "*.mein-dorf.us"])
            self.assertLess(time.monotonic() - started, 2.0)

    def test_allow_list_validation(self):
        ok = settings._as_allowed_hosts("Zeit.Example.org., *.fritz.box\nzeit.example.org  uhr.example.org")
        self.assertEqual(ok, ["zeit.example.org", "*.fritz.box", "uhr.example.org"])
        self.assertEqual(settings._as_allowed_hosts([]), [])
        self.assertEqual(settings._as_allowed_hosts(""), [])
        for bad, word in (("*", "WEB_ALLOWED_HOSTS=*"), ("*.com", "Endung"), ("192.168.1.5", "IP-Adresse"),
                          ("::1", "IP-Adresse"), ("[fe80::1]", "IP-Adresse"), ("raspberrypi", "einteilig"),
                          ("zeit.example.org:8080", "kein gültiger"), ("*.*.example.org", "kein gültiger"),
                          ("zeit.*.example.org", "kein gültiger"), ("evil.example/x", "kein gültiger"),
                          ("http://zeit.example.org", "kein gültiger"), ("-bad.example.org", "kein gültiger"),
                          ("a" * 64 + ".example.org", "kein gültiger"), ("zeit .example.org", "einteilig"),
                          ("<script>.example.org", "kein gültiger"), ("zeit_ex.example.org", "kein gültiger")):
            with self.subTest(bad=bad):
                with self.assertRaises(settings.ValidationError) as ctx:
                    settings._as_allowed_hosts(bad)
                self.assertIn(word, str(ctx.exception))
        with self.assertRaises(settings.ValidationError):
            settings._as_allowed_hosts([f"h{i}.example.org" for i in range(settings.MAX_ALLOWED_HOSTS + 1)])

    def test_allow_list_rejects_shared_suffix_wildcards(self):
        for bad in ("*.duckdns.org", "*.ddns.net", "*.dynv6.net", "*.myfritz.net", "*.co.uk", "*.com.au",
                    "*.github.io", "*.no-ip.org", "*.or.at", "*.DuckDNS.org."):
            with self.subTest(bad=bad):
                with self.assertRaises(settings.ValidationError) as ctx:
                    settings._as_allowed_hosts(bad)
                self.assertIn("eigenen", str(ctx.exception))
                self.assertIn("meinzeit.", str(ctx.exception))
        for bad in ("1.2.3", "zeit.123", "*.10.0"):
            with self.subTest(bad=bad):
                with self.assertRaises(settings.ValidationError):
                    settings._as_allowed_hosts(bad)
        ok = settings._as_allowed_hosts("meinzeit.duckdns.org *.meinzeit.duckdns.org *.example.co.uk "
                                        "zeit.example.co.uk *.fritz.box *.example.de 1zeit.example.org")
        self.assertEqual(len(ok), 7)
        self.assertTrue(settings.shared_suffix("co.uk"))
        self.assertFalse(settings.shared_suffix("example.co.uk"))
        with self.assertRaises(settings.ValidationError):
            settings.validate({"web_allowed_hosts": ["*.co.uk"]})
        field = settings.FIELDS["web_allowed_hosts"]
        self.assertEqual((field["section"], field["advanced"], field["restart"], field["env"]),
                         ("web", False, settings.RESTART_NONE, None), "Env bleibt getrennt und gilt zusätzlich")
        self.assertIn("DNS-Rebinding", field["help"])

    def test_logged_host_is_cleaned(self):
        """Der Host-Header landet im Log – überlang oder mit fremden Zeichen nur als <ungültig>."""
        self.assertEqual(server.safe_host_for_log("attacker.example"), "attacker.example")
        self.assertEqual(server.safe_host_for_log("a" * 64 + ".attacker.de"), "<ungültig>")
        self.assertEqual(server.safe_host_for_log("x" * 300), "<ungültig>")
        self.assertEqual(server.safe_host_for_log("evil\u201c.de"), "<ungültig>")
        self.assertEqual(server.safe_host_for_log("evil.de/../x"), "<ungültig>")


class HostNameCacheTest(unittest.TestCase):
    """Regression: host_allowed() fragte bei jedem fremden Host-Kopf socket.getfqdn() – ein
    Rückwärts-DNS, das bei langsamem Resolver Sekunden dauert und den Handler-Thread blockiert."""

    def test_foreign_hosts_do_not_resolve_per_request(self):
        hang = threading.Event()
        calls = []

        def slow_fqdn(*_args):
            calls.append(1)
            hang.wait(10)  # Resolver hängt
            return "ntpbox.example.net"

        fake_hostnames(self, "ntpbox", "unused")
        self.addCleanup(hang.set)
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": ""}), \
                mock.patch.object(server.socket, "getfqdn", slow_fqdn):
            started = time.monotonic()
            for _ in range(5):
                self.assertFalse(server.host_allowed("rebind.evil.com"))
            self.assertTrue(server.host_allowed("ntpbox"))  # gethostname() gilt sofort
            self.assertLess(time.monotonic() - started, 5)  # alter Code: 5 × 10 s
            self.assertEqual(len(calls), 1)
            hang.set()
            end = time.monotonic() + 10
            while time.monotonic() < end and "ntpbox.example.net" not in diagnostics.own_hostnames():
                time.sleep(0.02)
            self.assertTrue(server.host_allowed("ntpbox.example.net"))
            self.assertEqual(len(calls), 1)  # danach aus dem Cache


class HostCheckServerTest(unittest.TestCase):
    def setUp(self):
        fake_hostnames(self)  # kein Rückwärts-DNS des Runners je Anfrage

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k not in {"WEB_USER", "WEB_PASSWORD", "WEB_ALLOWED_HOSTS"}}
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, env, clear=True),
        ]
        for patch in cls.patches:
            patch.start()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        server._REJECTED_HOSTS.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.key_id, cls.key = apikeys.create("Lesen", "read")

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        cls.tmp.cleanup()

    def request(self, method, path, host, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", host)
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        data = json.dumps(body).encode() if body is not None else b""
        if method == "POST":
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data if method == "POST" else None)
        resp = conn.getresponse()
        raw = resp.read()
        ctype = resp.getheader("Content-Type", "")
        conn.close()
        return resp.status, raw, ctype

    def test_ip_and_localhost_allowed(self):
        self.assertEqual(self.request("GET", "/api/v1/instance", f"127.0.0.1:{self.port}")[0], 200)
        self.assertEqual(self.request("GET", "/api/v1/instance", f"localhost:{self.port}")[0], 200)

    def test_foreign_host_rejected_with_german_explanation(self):
        server._REJECTED_HOSTS.clear()
        with mock.patch("builtins.print") as printed:
            status, raw, ctype = self.request("GET", "/api/logs", "attacker.example:8087")
            self.assertEqual(status, 403)
            self.assertIn("json", ctype)
            payload = json.loads(raw)
            self.assertEqual(payload["reason"], "host_not_allowed")
            self.assertIn("WEB_ALLOWED_HOSTS", payload["error"])
            self.assertIn("Passwort", payload["error"])
            status, raw, ctype = self.request("GET", "/", "attacker.example")
            self.assertEqual(status, 403)
            self.assertIn("text/html", ctype)
            self.assertIn("WEB_ALLOWED_HOSTS".encode(), raw)
            self.assertEqual(self.request("POST", "/api/reload", "attacker.example", {"X-NTP-GUI": "1"}, {})[0], 403)
            self.assertEqual(self.request("GET", "/api/status", "attacker.example")[0], 403)
        logged = [c for c in printed.call_args_list if "attacker.example" in str(c)]
        self.assertEqual(len(logged), 1)  # nur einmal je Name protokolliert

    def test_healthz_always_allowed(self):
        self.assertNotEqual(self.request("GET", "/healthz", "attacker.example")[0], 403)

    def test_env_allow_list(self):
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "zeit.example.org"}), mock.patch("builtins.print"):
            self.assertEqual(self.request("GET", "/api/v1/instance", "zeit.example.org:8080")[0], 200)
            self.assertEqual(self.request("GET", "/api/v1/instance", "attacker.example")[0], 403)

    def test_dashboard_allow_list_end_to_end(self):
        """Erlaubte Namen: speichern (Admin + CSRF), sofort wirksam, Env nur lesend, Export/Import."""
        self.addCleanup(settings.reset, ["web_allowed_hosts"])
        local = f"127.0.0.1:{self.port}"
        gui = {"X-NTP-GUI": "1"}
        with mock.patch("builtins.print"):
            self.assertEqual(self.request("GET", "/api/v1/instance", "uhr.example.org")[0], 403)
            # CSRF: ohne X-NTP-GUI kein Speichern; über einen fremden Namen erst recht nicht.
            self.assertEqual(self.request("POST", "/api/settings", local, {},
                                          {"changes": {"web_allowed_hosts": ["uhr.example.org"]}})[0], 403)
            self.assertEqual(self.request("POST", "/api/settings", "uhr.example.org", gui,
                                          {"changes": {"web_allowed_hosts": ["uhr.example.org"]}})[0], 403)
            # Lese-Schlüssel darf nicht schreiben.
            self.assertEqual(self.request("POST", "/api/v1/settings", local,
                                          {"Authorization": f"Bearer {self.key}"},
                                          {"values": {"web_allowed_hosts": ["uhr.example.org"]}})[0], 403)
            status, raw, _ = self.request("POST", "/api/settings", local, gui, {"changes": {"web_allowed_hosts": ["*"]}})
            self.assertEqual(status, 422)
            self.assertIn("web_allowed_hosts", json.loads(raw)["fields"])
            status, raw, _ = self.request("POST", "/api/settings", local, gui,
                                          {"changes": {"web_allowed_hosts": ["Uhr.example.org", "*.dorf.example"]}})
            self.assertEqual(status, 200, raw)
            self.assertFalse(json.loads(raw).get("restart"), "wirkt ohne Neustart")
            self.assertEqual(self.request("GET", "/api/v1/instance", "uhr.example.org")[0], 200)
            self.assertEqual(self.request("GET", "/api/v1/instance", "pi.dorf.example:8080")[0], 200)
            self.assertEqual(self.request("GET", "/api/v1/instance", "attacker.example")[0], 403)
            with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "zeit.example.org,*.fritz.box"}):
                self.assertEqual(self.request("GET", "/api/v1/instance", "zeit.example.org")[0], 200)
                self.assertEqual(self.request("GET", "/api/v1/instance", "uhr.example.org")[0], 200)
                status, raw, _ = self.request("GET", "/api/settings", local)
                field = next(f for f in json.loads(raw)["fields"] if f["key"] == "web_allowed_hosts")
                self.assertEqual(field["value"], ["uhr.example.org", "*.dorf.example"])
                self.assertEqual(field["source"], "gui")
                self.assertEqual(field["env_extra"], {"name": "WEB_ALLOWED_HOSTS",
                                                      "values": ["zeit.example.org", "*.fritz.box"]})
            status, raw, _ = self.request("GET", "/api/settings/export", local)
            exported = json.loads(raw)
            self.assertEqual(exported["values"]["web_allowed_hosts"], ["uhr.example.org", "*.dorf.example"])
            settings.reset(["web_allowed_hosts"])
            self.assertEqual(self.request("GET", "/api/v1/instance", "uhr.example.org")[0], 403)
            status, raw, _ = self.request("POST", "/api/settings/import", local, gui, exported)
            self.assertEqual(status, 200, raw)
            self.assertEqual(self.request("GET", "/api/v1/instance", "uhr.example.org")[0], 200)
            # Import mit „*“ wird wie Speichern abgelehnt.
            bad = {"schema": exported["schema"], "values": {"web_allowed_hosts": ["*"]}}
            self.assertEqual(self.request("POST", "/api/settings/import", local, gui, bad)[0], 422)
            status, raw, _ = self.request("GET", "/api/v1/instance", "attacker.example")
            self.assertEqual(status, 403)
            self.assertIn("Erlaubte Namen", json.loads(raw)["error"])

    def test_api_key_works_with_any_host(self):
        status, _, _ = self.request("GET", "/api/v1/instance", "ntp.example.org",
                                    {"Authorization": f"Bearer {self.key}"})
        self.assertEqual(status, 200)

    def test_with_password_any_host(self):
        with mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"}):
            auth = {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode()}
            self.assertEqual(self.request("GET", "/api/v1/instance", "zeit.example.org", auth)[0], 200)
            self.assertEqual(self.request("GET", "/api/v1/instance", "zeit.example.org")[0], 401)


class StateWatchTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.watch = statewatch.StateWatcher(lambda *a, **k: self.events.append(a), gps_fix_hold=0)

    @staticmethod
    def sample(selected="A", mode=3):
        return {"sources": {"A": {"s": "*" if selected == "A" else "+"},
                            "B": {"s": "*" if selected == "B" else "-"}},
                "gps": {"mode": mode, "used": 8}}

    def feed(self, *samples):
        for s in samples:
            self.watch.sample(s)

    def test_first_state_is_no_event(self):
        self.feed(self.sample(), self.sample(), self.sample())
        self.assertEqual(self.events, [])

    def test_source_change_needs_confirmation(self):
        self.feed(self.sample("A"), self.sample("A"), self.sample("B"), self.sample("A"))
        self.assertEqual(self.events, [])  # ein einzelner Ausreißer
        self.feed(self.sample("B"), self.sample("B"))
        self.assertEqual([(e[0], e[1]) for e in self.events], [("source", "info")])
        self.assertIn("A → B", self.events[0][2])

    def test_fix_lost_and_back(self):
        self.feed(self.sample(mode=3), self.sample(mode=3), self.sample(mode=1), self.sample(mode=1))
        self.feed(self.sample(mode=3), self.sample(mode=3))
        self.assertEqual([(e[0], e[1], e[2]) for e in self.events],
                         [("gps", "warn", "GPS-Fix verloren"), ("gps", "info", "GPS-Fix wieder da")])

    def test_pps_lost_and_back(self):
        live = {"pps": [{"dev": "/dev/pps0", "state": "live"}]}
        silent = {"pps": [{"dev": "/dev/pps0", "state": "silent"}]}
        for rep in (live, {"pps": [{"dev": "/dev/pps0", "state": "unknown"}]}, silent, silent, live):
            self.watch.hardware(rep)
        self.assertEqual([(e[0], e[1]) for e in self.events], [("pps", "warn"), ("pps", "info")])

    def test_never_live_is_not_lost(self):
        for _ in range(3):
            self.watch.hardware({"pps": [{"dev": "/dev/pps1", "state": "never"}]})
        self.assertEqual(self.events, [])



class AuthCacheClockTest(unittest.TestCase):
    """Der Zugangs-Cache misst seine 300 s monoton: Stellt chrony die Uhr zurück, bliebe ein
    geprüfter Zugang sonst um die Sprungweite länger gültig."""

    def test_default_clock_is_monotonic(self):
        self.assertIs(server.AuthCache().clock, time.monotonic)

    def test_expires_after_300_s(self):
        now = [100.0]
        cache = server.AuthCache(clock=lambda: now[0])
        calls = []
        verify = lambda: calls.append(1) or True  # noqa: E731
        self.assertTrue(cache.check("Basic x", verify))
        now[0] += 299
        self.assertTrue(cache.check("Basic x", verify))
        self.assertEqual(len(calls), 1)
        now[0] += 2
        self.assertTrue(cache.check("Basic x", verify))
        self.assertEqual(len(calls), 2)
        self.assertFalse(cache.check("Basic y", lambda: False))


if __name__ == "__main__":
    unittest.main()
