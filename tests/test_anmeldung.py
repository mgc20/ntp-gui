"""Anmeldung und Zugang (1.9): Bremse gegen Passwort-Raten, fail-closed, WEB_REQUIRE_AUTH,
WEB_PASSWORD_FILE, Passwortänderung mit bisherigem Passwort, Abmelden, HSTS, PBKDF2-Runden.

Läuft ohne chronyd: nur Routen, die keine chronyc-Abfrage brauchen (oder chrony gemockt)."""

import base64
import hashlib
import http.client
import json
import os
import sys
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
import authguard  # noqa: E402
import events  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

AUTH_ENV = ("WEB_USER", "WEB_PASSWORD", "WEB_PASSWORD_FILE", "WEB_REQUIRE_AUTH", "WEB_READONLY")


def basic(user, password):
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


class GuardTest(unittest.TestCase):
    """Die Bremse für sich: je Quelle, gesamt, Negativ-Merker, gleichzeitige Prüfungen."""

    def setUp(self):
        self.now = [1000.0]
        self.guard = authguard.Guard(clock=lambda: self.now[0])

    def test_source_is_slowed_after_free_failures(self):
        for _ in range(authguard.FREE_FAILURES - 1):
            self.guard.failure("192.0.2.1")
        self.assertEqual(self.guard.retry_after("192.0.2.1"), 0)
        result = self.guard.failure("192.0.2.1")
        self.assertTrue(result["started"])
        self.assertGreater(self.guard.retry_after("192.0.2.1"), 0)
        self.assertEqual(self.guard.retry_after("192.0.2.2"), 0)  # andere Quelle unberührt

    def test_wait_grows_and_is_capped(self):
        waits = [self.guard.failure("192.0.2.1")["blocked_for"] for _ in range(30)]
        grown = [w for w in waits if w]
        self.assertEqual(grown[:3], [2.0, 4.0, 8.0])
        self.assertEqual(max(grown), authguard.MAX_BLOCK)

    def test_success_and_window_forget(self):
        for _ in range(authguard.FREE_FAILURES):
            self.guard.failure("192.0.2.1")
        self.guard.success("192.0.2.1")
        self.assertEqual(self.guard.retry_after("192.0.2.1"), 0)
        for _ in range(authguard.FREE_FAILURES - 1):
            self.guard.failure("192.0.2.3")
        self.now[0] += authguard.WINDOW + 1
        self.assertFalse(self.guard.failure("192.0.2.3")["blocked_for"])

    def test_global_limit_spares_known_good_sources(self):
        self.guard.success("192.0.2.200")
        for i in range(authguard.GLOBAL_LIMIT + 1):
            self.guard.failure(f"198.51.100.{i}")
        self.assertGreater(self.guard.retry_after("203.0.113.9"), 0)
        self.assertEqual(self.guard.retry_after("192.0.2.200"), 0)
        self.now[0] += authguard.GLOBAL_BLOCK + 1
        self.assertEqual(self.guard.retry_after("203.0.113.9"), 0)

    def test_ipv6_counts_per_64(self):
        self.assertEqual(authguard.source_key("2001:db8:1:2::5"), authguard.source_key("2001:db8:1:2:ffff::1"))
        self.assertNotEqual(authguard.source_key("2001:db8:1:2::5"), authguard.source_key("2001:db8:1:3::5"))
        self.assertEqual(authguard.source_key("::ffff:192.0.2.7"), "192.0.2.7")

    def test_negative_memory_for_identical_header(self):
        self.guard.failure("192.0.2.1", "Basic abc|gui")
        self.assertTrue(self.guard.is_negative("Basic abc|gui"))
        self.assertFalse(self.guard.is_negative("Basic abd|gui"))
        self.now[0] += authguard.NEGATIVE_SECONDS + 1
        self.assertFalse(self.guard.is_negative("Basic abc|gui"))

    def test_identical_wrong_header_counts_once(self):
        for _ in range(authguard.FREE_FAILURES + 3):
            result = self.guard.failure("192.0.2.1", "Basic alt|gui")
            self.now[0] += authguard.NEGATIVE_SECONDS + 1  # Negativ-Merker abgelaufen: erneut geprüft
        self.assertFalse(result["counted"])
        self.assertEqual(self.guard.retry_after("192.0.2.1"), 0)
        for i in range(authguard.FREE_FAILURES):  # verschiedene falsche Köpfe zählen weiter
            self.guard.failure("192.0.2.1", f"Basic x{i}|gui")
        self.assertGreater(self.guard.retry_after("192.0.2.1"), 0)

    def test_running_checks_count_like_failures(self):
        reserved = [self.guard.reserve("192.0.2.1") for _ in range(authguard.FREE_FAILURES)]
        self.assertEqual(reserved, [0.0] * authguard.FREE_FAILURES)
        self.assertGreater(self.guard.reserve("192.0.2.1"), 0)
        self.assertEqual(self.guard.reserve("192.0.2.2"), 0)  # andere Quelle unberührt
        self.guard.release("192.0.2.2")
        for i in range(authguard.FREE_FAILURES):
            self.guard.failure("192.0.2.1", f"Basic f{i}|gui")
            self.guard.release("192.0.2.1")
        self.assertGreater(self.guard.reserve("192.0.2.1"), 0)  # jetzt gebremst

    def test_known_good_survives_restart_without_addresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bekannt.json")
            self.guard.persist(path)
            self.guard.success("192.0.2.200")
            text = Path(path).read_text()
            self.assertNotIn("192.0.2", text)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            restarted = authguard.Guard(clock=lambda: self.now[0])
            restarted.persist(path)
            for i in range(authguard.GLOBAL_LIMIT + 1):
                restarted.failure(f"198.51.100.{i}")
            self.assertEqual(restarted.retry_after("192.0.2.200"), 0)
            self.assertGreater(restarted.retry_after("203.0.113.9"), 0)

    def test_concurrent_checks_are_limited(self):
        with mock.patch.object(authguard, "SLOT_WAIT", 0.01):
            with self.guard.slot() as a, self.guard.slot() as b:
                self.assertTrue(a and b)
                with self.guard.slot() as c:
                    self.assertFalse(c)
            with self.guard.slot() as d:
                self.assertTrue(d)

    def test_events_are_throttled(self):
        first = self.guard.failure("192.0.2.1")
        second = self.guard.failure("192.0.2.1")
        self.assertTrue(first["report"])
        self.assertFalse(second["report"])
        self.now[0] += authguard.EVENT_EVERY
        third = self.guard.failure("192.0.2.1")
        self.assertTrue(third["report"])
        self.assertEqual(third["reported"], 2)


class PasswordHashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patch in (mock.patch.object(settings, "DATA_DIR", self.tmp.name),
                      mock.patch.object(settings, "SETTINGS_FILE", os.path.join(self.tmp.name, "settings.json"))):
            patch.start()
            self.addCleanup(patch.stop)

    def test_rounds_follow_recommendation(self):
        encoded = settings.hash_password("ein langes Passwort")
        self.assertGreaterEqual(int(encoded.split("$")[1]), 600_000)
        self.assertFalse(settings.needs_rehash(encoded))

    def test_old_hash_still_valid_and_upgraded(self):
        salt = b"s" * 16
        old = "pbkdf2_sha256$200000${}${}".format(
            base64.b64encode(salt).decode(),
            base64.b64encode(hashlib.pbkdf2_hmac("sha256", b"altes-passwort-1", salt, 200_000)).decode())
        self.assertTrue(settings.verify_password("altes-passwort-1", old))
        self.assertTrue(settings.needs_rehash(old))
        settings._write_file({"auth": {"user": "admin", "hash": old}})
        self.assertFalse(settings.upgrade_hash("admin", "altes-passwort-1", "anderer-hash"))
        self.assertTrue(settings.upgrade_hash("admin", "altes-passwort-1", old))
        stored = settings.stored_credentials()["hash"]
        self.assertFalse(settings.needs_rehash(stored))
        self.assertTrue(settings.verify_password("altes-passwort-1", stored))

    def test_absurd_round_count_is_rejected(self):
        salt = base64.b64encode(b"s" * 16).decode()
        with mock.patch.object(settings.hashlib, "pbkdf2_hmac", side_effect=AssertionError("gerechnet")):
            self.assertFalse(settings.verify_password("x", f"pbkdf2_sha256$999999999${salt}$AAAA"))

    def test_weak_dashboard_password_rejected(self):
        for weak in ("bitte-aendern", "admin123", "aaaaaaaaaa"):
            with self.subTest(weak=weak), self.assertRaises(settings.ValidationError):
                settings.set_credentials("admin", weak)
        with self.assertRaises(settings.ValidationError):
            settings.set_credentials("verwalter", "Verwalter")
        settings.set_credentials("admin", "lang-und-eigen-42")

    def test_weakness_reasons(self):
        self.assertIsNotNone(settings.password_weakness("kurz123"))
        self.assertIsNotNone(settings.password_weakness("bitte-aendern"))
        self.assertIsNone(settings.password_weakness("ein-langes-eigenes-Passwort"))


class _ServerBase(unittest.TestCase):
    """Ein echter Handler je Test mit leerem Datenverzeichnis und eigener Umgebung."""

    ENV: dict = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k not in AUTH_ENV}
        env.update(self.ENV)
        patches = [
            mock.patch.object(settings, "DATA_DIR", self.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(self.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", self.tmp.name),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(server.chrony, "tracking", return_value={"ref_id": "x"}),
        ]
        for patch in patches:
            patch.start()
        self.patches = patches
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        authguard.GUARD.clear()
        self.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        stop_http_server(self.httpd)
        for patch in reversed(self.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        authguard.GUARD.clear()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = json.dumps(body).encode() if body is not None else None
        hdrs = {"Host": "localhost"}
        hdrs.update(headers or {})
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
            hdrs.setdefault("X-NTP-GUI", "1")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        headers_out = dict(resp.getheaders())
        conn.close()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw
        return resp.status, payload, headers_out

    def access_events(self):
        return [e["title"] for e in events.query(kinds=["access"])]


class FailClosedTest(_ServerBase):
    def test_only_password_set_requires_login_as_admin(self):
        with mock.patch.dict(os.environ, {"WEB_PASSWORD": "ein-langes-geheimnis"}):
            self.assertEqual(self.request("GET", "/api/v1/instance")[0], 401)
            status, _, _ = self.request("POST", "/api/auth", {"user": "x", "password": "uebernahme-123"})
            self.assertEqual(status, 401)
            ok = {"Authorization": basic("admin", "ein-langes-geheimnis")}
            self.assertEqual(self.request("GET", "/api/v1/instance", headers=ok)[0], 200)

    def test_changed_password_file_ends_remembered_login(self):
        secret = os.path.join(self.tmp.name, "pw-wechsel")
        with open(secret, "w", encoding="utf-8") as handle:
            handle.write("altes-passwort-123\n")
        old = {"Authorization": basic("admin", "altes-passwort-123")}
        new = {"Authorization": basic("admin", "neues-passwort-456")}
        with mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD_FILE": secret}):
            self.assertEqual(self.request("GET", "/api/v1/instance", headers=old)[0], 200)
            replacement = secret + ".tmp"
            with open(replacement, "w", encoding="utf-8") as handle:
                handle.write("neues-passwort-456\n")
            os.replace(replacement, secret)   # so erneuert der Supervisor seine Kopie
            self.assertEqual(self.request("GET", "/api/v1/instance", headers=old)[0], 401)
            self.assertEqual(self.request("GET", "/api/v1/instance", headers=new)[0], 200)

    def test_only_user_set_locks_dashboard(self):
        with mock.patch.dict(os.environ, {"WEB_USER": "admin"}):
            status, payload, _ = self.request("GET", "/api/v1/instance")
            self.assertEqual(status, 503)
            self.assertEqual(payload["reason"], "auth_setup_required")

    def test_password_file(self):
        secret = os.path.join(self.tmp.name, "pw")
        with open(secret, "w", encoding="utf-8") as handle:
            handle.write("aus-der-datei-123\n")
        with mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD_FILE": secret}):
            self.assertEqual(self.request("GET", "/api/v1/instance")[0], 401)
            ok = {"Authorization": basic("admin", "aus-der-datei-123")}
            self.assertEqual(self.request("GET", "/api/v1/instance", headers=ok)[0], 200)
        with mock.patch.dict(os.environ, {"WEB_USER": "admin",
                                          "WEB_PASSWORD_FILE": os.path.join(self.tmp.name, "fehlt")}):
            self.assertEqual(self.request("GET", "/api/v1/instance")[0], 503)


class RequireAuthTest(_ServerBase):
    ENV = {"WEB_REQUIRE_AUTH": "true"}

    def test_without_credentials_everything_but_healthz_is_locked(self):
        _, token = apikeys.create("Skript", "admin")
        status, payload, _ = self.request("GET", "/api/status", headers={"Accept": "application/json"})
        self.assertEqual(status, 503)
        self.assertEqual(payload["reason"], "auth_setup_required")
        self.assertEqual(self.request("GET", "/api/v1/instance", headers={"Authorization": f"Bearer {token}"})[0], 503)
        self.assertEqual(self.request("POST", "/api/auth", {"user": "x", "password": "uebernahme-123"})[0], 503)
        status, body, _ = self.request("GET", "/", headers={"Accept": "text/html"})
        self.assertEqual(status, 503)
        self.assertIn("Einrichtung nötig", body.decode())
        self.assertEqual(self.request("GET", "/healthz")[0], 200)

    def test_with_credentials_normal_and_cannot_be_removed(self):
        settings.set_credentials("admin", "lang-und-eigen-42")
        auth = {"Authorization": basic("admin", "lang-und-eigen-42")}
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=auth)[0], 200)
        status, payload, _ = self.request("POST", "/api/auth", {"clear": True, "current_password": "lang-und-eigen-42"},
                                          auth)
        self.assertEqual(status, 422)
        self.assertIn("WEB_REQUIRE_AUTH", payload["error"])
        self.assertIsNotNone(settings.stored_credentials())

    def test_startup_warns_loudly(self):
        lines = "\n".join(server.startup_auth_warnings("0.0.0.0"))
        self.assertIn("GESPERRT", lines)


class StartupWarningTest(_ServerBase):
    def test_open_on_all_addresses_warns(self):
        self.assertIn("OHNE PASSWORT", "\n".join(server.startup_auth_warnings("0.0.0.0")))
        self.assertIn("OHNE PASSWORT", "\n".join(server.startup_auth_warnings("::")))
        self.assertEqual(server.startup_auth_warnings("127.0.0.1"), [])

    def test_weak_env_password_warns(self):
        with mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "bitte-aendern"}):
            self.assertIn("schwach", "\n".join(server.startup_auth_warnings("127.0.0.1")))
            self.assertTrue(server.auth_info()["weak"])
        with mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "ein-langes-geheimnis"}):
            self.assertEqual(server.startup_auth_warnings("0.0.0.0"), [])


class BruteForceTest(_ServerBase):
    ENV = {"WEB_USER": "admin", "WEB_PASSWORD": "ein-langes-geheimnis"}

    def test_repeated_failures_get_429_with_retry_after(self):
        good = {"Authorization": basic("admin", "ein-langes-geheimnis")}
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=good)[0], 200)  # schon geprüft
        statuses = []
        for i in range(authguard.FREE_FAILURES + 1):
            status, _, headers = self.request("GET", "/api/v1/instance",
                                              headers={"Authorization": basic("admin", f"falsch-{i}")})
            statuses.append(status)
        self.assertEqual(statuses[:authguard.FREE_FAILURES - 1], [401] * (authguard.FREE_FAILURES - 1))
        self.assertEqual(statuses[-1], 429)
        self.assertGreaterEqual(int(headers["Retry-After"]), 1)
        # Ein schon geprüfter, gültiger Zugang ist nie gebremst …
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=good)[0], 200)
        # … ein neuer (noch ungeprüfter) dagegen schon – ohne dass das Passwort geprüft wird.
        server.AUTH_CACHE.clear()
        with mock.patch.object(server.Handler, "_check_password", side_effect=AssertionError("geprüft")):
            self.assertEqual(self.request("GET", "/api/v1/instance", headers=good)[0], 429)
        self.assertIn("Anmeldung fehlgeschlagen", self.access_events())

    def test_identical_wrong_header_is_not_checked_again(self):
        wrong = {"Authorization": basic("admin", "falsch")}
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=wrong)[0], 401)
        with mock.patch.object(server.Handler, "_check_password", side_effect=AssertionError("geprüft")):
            self.assertEqual(self.request("GET", "/api/v1/instance", headers=wrong)[0], 401)

    def test_stale_tab_with_old_password_does_not_lock_out(self):
        old = {"Authorization": basic("admin", "altes-passwort")}
        with mock.patch.object(authguard, "NEGATIVE_SECONDS", 0.0):  # jede Abfrage wird neu geprüft
            statuses = [self.request("GET", "/api/v1/instance", headers=old)[0]
                        for _ in range(authguard.FREE_FAILURES + 3)]
        self.assertEqual(set(statuses), {401})
        good = {"Authorization": basic("admin", "ein-langes-geheimnis")}
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=good)[0], 200)

    def test_logout_placeholder_is_not_a_failure(self):
        placeholder = {"Authorization": basic(server.LOGOUT_USER, server.LOGOUT_USER)}
        for _ in range(authguard.FREE_FAILURES + 2):
            status, _, headers = self.request("GET", "/", headers=placeholder)
            self.assertEqual(status, 401)
            self.assertIn("Basic", headers.get("WWW-Authenticate", ""))
        self.assertEqual(self.access_events(), [])
        self.assertEqual(authguard.GUARD.retry_after("127.0.0.1"), 0)
        self.assertEqual(authguard.GUARD.reserve("127.0.0.1"), 0)  # kein Fehlversuch gezählt
        authguard.GUARD.release("127.0.0.1")

    def _parallel(self, headers_list):
        results = [None] * len(headers_list)

        def run(i):
            results[i] = self.request("GET", "/api/v1/instance", headers=headers_list[i])[0]

        threads = [threading.Thread(target=run, args=(i,)) for i in range(len(headers_list))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        return results

    def test_parallel_wrong_passwords_get_at_most_free_checks(self):
        checks = []
        lock = threading.Lock()
        real = server.Handler._check_password

        def slow(info, user, password):
            with lock:
                checks.append(password)
            time.sleep(0.05)
            return real(info, user, password)

        with mock.patch.object(server.Handler, "_check_password", staticmethod(slow)):
            statuses = self._parallel([{"Authorization": basic("admin", f"falsch-{i}")} for i in range(30)])
            self.assertLessEqual(len(checks), authguard.FREE_FAILURES)
            self.assertIn(429, statuses)
            # Aus der gebremsten Quelle wird auch das richtige Passwort nicht geprüft.
            good = {"Authorization": basic("admin", "ein-langes-geheimnis")}
            self.assertEqual(self.request("GET", "/api/v1/instance", headers=good)[0], 429)
        self.assertLessEqual(len(checks), authguard.FREE_FAILURES)

    def test_parallel_identical_valid_header_is_checked_once(self):
        checks = []
        lock = threading.Lock()
        real = server.Handler._check_password

        def slow(info, user, password):
            with lock:
                checks.append(password)
            time.sleep(0.5)
            return real(info, user, password)

        good = {"Authorization": basic("admin", "ein-langes-geheimnis")}
        with mock.patch.object(server.Handler, "_check_password", staticmethod(slow)):
            statuses = self._parallel([good] * 6)
        self.assertEqual(statuses, [200] * 6)
        self.assertEqual(len(checks), 1)

    def test_trusted_proxy_counts_real_client(self):
        settings.save({"trusted_proxies": ["127.0.0.1/32"]})
        for i in range(authguard.FREE_FAILURES):
            self.request("GET", "/api/v1/instance", headers={"Authorization": basic("admin", f"x{i}"),
                                                             "X-Forwarded-For": "198.51.100.7"})
        blocked = {"Authorization": basic("admin", "y"), "X-Forwarded-For": "198.51.100.7"}
        other = {"Authorization": basic("admin", "y"), "X-Forwarded-For": "198.51.100.8"}
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=blocked)[0], 429)
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=other)[0], 401)

    def test_untrusted_forwarded_header_does_not_dodge(self):
        for i in range(authguard.FREE_FAILURES):
            self.request("GET", "/api/v1/instance", headers={"Authorization": basic("admin", f"x{i}"),
                                                             "X-Forwarded-For": f"198.51.100.{i}"})
        status, _, _ = self.request("GET", "/api/v1/instance", headers={"Authorization": basic("admin", "z"),
                                                                       "X-Forwarded-For": "198.51.100.99"})
        self.assertEqual(status, 429)


class PasswordChangeTest(_ServerBase):
    def setUp(self):
        super().setUp()
        settings.set_credentials("admin", "lang-und-eigen-42")
        self.auth = {"Authorization": basic("admin", "lang-und-eigen-42")}

    def test_change_needs_current_password_and_is_logged(self):
        body = {"user": "admin", "password": "noch-laenger-und-neu-7"}
        self.assertEqual(self.request("POST", "/api/auth", body, self.auth)[0], 403)
        self.assertEqual(self.request("POST", "/api/auth", dict(body, current_password="falsch"), self.auth)[0], 403)
        status, payload, _ = self.request("POST", "/api/auth", dict(body, current_password="lang-und-eigen-42"),
                                          self.auth)
        self.assertEqual(status, 200)
        self.assertIn("Passwort des Dashboards geändert", self.access_events())

    def test_clear_needs_current_password_and_is_logged(self):
        self.assertEqual(self.request("POST", "/api/auth", {"clear": True}, self.auth)[0], 403)
        self.assertIsNotNone(settings.stored_credentials())
        status, _, _ = self.request("POST", "/api/auth", {"clear": True, "current_password": "lang-und-eigen-42"},
                                    self.auth)
        self.assertEqual(status, 200)
        self.assertIsNone(settings.stored_credentials())
        self.assertTrue(any(t.startswith("Zugang zum Dashboard entfernt") for t in self.access_events()))

    def test_wrong_current_password_is_slowed(self):
        body = {"clear": True, "current_password": "falsch"}
        statuses = [self.request("POST", "/api/auth", dict(body, current_password=f"f{i}"), self.auth)[0]
                    for i in range(authguard.FREE_FAILURES + 1)]
        self.assertEqual(statuses[-1], 429)

    def test_login_upgrades_old_hash(self):
        salt = b"t" * 16
        old = "pbkdf2_sha256$200000${}${}".format(
            base64.b64encode(salt).decode(),
            base64.b64encode(hashlib.pbkdf2_hmac("sha256", b"lang-und-eigen-42", salt, 200_000)).decode())
        settings._write_file({"auth": {"user": "admin", "hash": old}})
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=self.auth)[0], 200)
        self.assertFalse(settings.needs_rehash(settings.stored_credentials()["hash"]))


class OpenModeKeysTest(_ServerBase):
    def test_keys_from_open_mode_are_shown_after_first_password(self):
        status, created, _ = self.request("POST", "/api/apikeys", {"name": "irgendwer", "scope": "admin"})
        self.assertEqual(status, 200)
        status, payload, _ = self.request("POST", "/api/auth", {"user": "admin", "password": "lang-und-eigen-42"})
        self.assertEqual(status, 200)
        self.assertEqual([k["id"] for k in payload["open_keys"]], [created["id"]])
        self.assertIn("Zugang zum Dashboard eingerichtet", self.access_events())
        auth = {"Authorization": basic("admin", "lang-und-eigen-42")}
        status, listing, _ = self.request("GET", "/api/apikeys", headers=auth)
        self.assertTrue(listing["keys"][0]["open_mode"])
        # Mit Anmeldung angelegt: nicht markiert. „Behalten“ entfernt die Markierung.
        status, second, _ = self.request("POST", "/api/apikeys", {"name": "ich", "scope": "read"}, auth)
        self.assertEqual(status, 200)
        flags = {k["id"]: k["open_mode"] for k in apikeys.list()}
        self.assertFalse(flags[second["id"]])
        self.assertEqual(self.request("POST", "/api/apikeys/keep", {"id": created["id"]}, auth)[0], 200)
        self.assertEqual(apikeys.open_mode_keys(), [])


class OpenModeMigrationTest(_ServerBase):
    """Update von einer Installation vor 1.9: vorhandene Schlüssel ohne Zugang gelten als offen angelegt."""

    def _old_install_with_key(self):
        store.migrate("apikeys", apikeys._SCHEMA[:1])  # Stand vor 1.9: ohne Spalte open_mode
        store.execute("INSERT INTO api_keys(id, name, scope, hash, created) VALUES(?, ?, ?, ?, ?)",
                      ("altkey01", "alt", "admin", apikeys.hash_token("ntpg_" + "a" * 32), time.time()))
        apikeys._READY["db"] = None

    def test_old_keys_without_access_are_shown_after_first_password(self):
        self._old_install_with_key()
        status, payload, _ = self.request("POST", "/api/auth", {"user": "admin", "password": "lang-und-eigen-42"})
        self.assertEqual(status, 200)
        self.assertEqual([k["id"] for k in payload["open_keys"]], ["altkey01"])

    def test_old_keys_with_password_stay_unmarked(self):
        settings.set_credentials("admin", "lang-und-eigen-42")
        self._old_install_with_key()
        self.assertEqual(apikeys.open_mode_keys(), [])


class UserNameVisibilityTest(_ServerBase):
    ENV = {"WEB_USER": "verwalter", "WEB_PASSWORD": "ein-langes-geheimnis"}

    def test_read_key_does_not_see_user_name(self):
        _, token = apikeys.create("Anzeige", "read")
        with mock.patch.object(server, "build_status",
                               return_value={"ui": {"auth": server.auth_public(server.auth_info(), None)},
                                             "insights": []}):
            _, payload, _ = self.request("GET", "/api/status", headers={"Authorization": f"Bearer {token}"})
            self.assertNotIn("user", payload["ui"]["auth"])
            self.assertTrue(payload["ui"]["auth"]["enabled"])
            _, payload, _ = self.request("GET", "/api/status",
                                         headers={"Authorization": basic("verwalter", "ein-langes-geheimnis")})
            self.assertEqual(payload["ui"]["auth"]["user"], "verwalter")
            self.assertTrue(payload["ui"]["auth"]["login"])
        _, payload, _ = self.request("GET", "/api/settings", headers={"Authorization": f"Bearer {token}"})
        self.assertNotIn("user", payload["auth"])


class LogoutAndTransportTest(_ServerBase):
    ENV = {"WEB_USER": "admin", "WEB_PASSWORD": "ein-langes-geheimnis"}

    def test_logout_forgets_checked_login(self):
        auth = {"Authorization": basic("admin", "ein-langes-geheimnis")}
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=auth)[0], 200)
        key = auth["Authorization"] + "|env"
        self.assertTrue(server.AUTH_CACHE.known(key))
        self.assertEqual(self.request("POST", "/api/auth/logout", {}, auth)[0], 200)
        self.assertFalse(server.AUTH_CACHE.known(key))

    def test_logout_probe(self):
        status, _, headers = self.request("GET", "/logout", headers={"Authorization": basic("abgemeldet", "abgemeldet")})
        self.assertEqual(status, 200)
        status, _, headers = self.request("GET", "/logout")
        self.assertEqual(status, 401)
        self.assertIn("Basic", headers.get("WWW-Authenticate", ""))
        status, _, headers = self.request("GET", "/logout", headers={"Authorization": basic("admin", "x")})
        self.assertEqual(status, 401)
        self.assertNotIn("WWW-Authenticate", headers)
        status, body, _ = self.request("GET", "/logout", headers={"Accept": "text/html"})
        self.assertEqual(status, 200)
        self.assertIn("Abgemeldet", body.decode())

    def test_hsts_only_via_trusted_https_proxy(self):
        auth = {"Authorization": basic("admin", "ein-langes-geheimnis")}
        _, _, headers = self.request("GET", "/api/v1/instance", headers=dict(auth, **{"X-Forwarded-Proto": "https"}))
        self.assertNotIn("Strict-Transport-Security", headers)
        settings.save({"trusted_proxies": ["127.0.0.1/32"]})
        _, _, headers = self.request("GET", "/api/v1/instance",
                                     headers=dict(auth, **{"X-Forwarded-For": "192.0.2.5",
                                                           "X-Forwarded-Proto": "https"}))
        self.assertIn("max-age=", headers.get("Strict-Transport-Security", ""))
        _, _, headers = self.request("GET", "/api/v1/instance",
                                     headers=dict(auth, **{"X-Forwarded-For": "192.0.2.5",
                                                           "X-Forwarded-Proto": "http"}))
        self.assertNotIn("Strict-Transport-Security", headers)


if __name__ == "__main__":
    unittest.main()
