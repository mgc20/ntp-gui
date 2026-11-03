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
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

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


def hdrs(values):
    msg = Message()
    for name, value in values.items():
        msg[name] = value
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
        self.assertEqual(info, {"client": "192.168.1.5", "peer": "192.168.1.5", "scheme": "http",
                                "proxied": False, "untrusted_forward": False, "proto_missing": False,
                                "peer_loopback": False, "peer_trusted": False, "forward_headers": (),
                                "proto_value": ""})

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

    def test_forwarded_header_rfc7239(self):
        trusted = wt.parse_networks(["127.0.0.1/32"])
        info = wt.resolve("127.0.0.1", hdrs({"Forwarded": "for=192.168.1.50;proto=https"}), trusted)
        self.assertEqual((info["client"], info["scheme"], info["proxied"]), ("192.168.1.50", "https", True))
        info = wt.resolve("127.0.0.1", hdrs({"Forwarded": 'for=1.2.3.4;proto=http, for="[2001:db8::7]:4711";proto=HTTPS'}),
                          trusted)
        self.assertEqual((info["client"], info["scheme"]), ("2001:db8::7", "https"))
        info = wt.resolve("127.0.0.1", hdrs({"Forwarded": "for=_hidden;proto=https"}), trusted)
        self.assertEqual((info["client"], info["scheme"]), ("127.0.0.1", "https"))

    def test_x_forwarded_wins_over_forwarded(self):
        info = wt.resolve("127.0.0.1", hdrs({"X-Forwarded-Proto": "http", "Forwarded": "proto=https"}),
                          wt.parse_networks(["127.0.0.1/32"]))
        self.assertEqual(info["scheme"], "http")

    def test_x_real_ip_alone_is_proxied_without_proto(self):
        trusted = wt.parse_networks(["127.0.0.1/32"])
        info = wt.resolve("127.0.0.1", hdrs({"X-Real-IP": "192.168.1.50"}), trusted)
        self.assertEqual((info["proxied"], info["proto_missing"], info["client"]), (True, True, "192.168.1.50"))
        self.assertFalse(info["untrusted_forward"])
        watch = wt.TransportWatch(clock=lambda: 1.0)
        watch.note(info, "basic")
        items = watch.insights(now=1.0)
        self.assertEqual([i["key"] for i in items], ["web_proxy_no_proto"])  # Proxy auf dem Host
        self.assertIn("kein Hinweis auf Klartext", items[0]["text"])
        self.assertIn("127.0.0.1 schickt X-Real-IP, aber weder", items[0]["text"])
        self.assertTrue(wt.resolve("192.168.1.9", hdrs({"X-Real-IP": "1.2.3.4"}), [])["untrusted_forward"])

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
        self.watch.note({"scheme": "https", "proxied": True, "peer_loopback": True}, "basic")
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

    # --- Prüfbefunde ----------------------------------------------------------------------------

    def test_trusted_lan_proxy_with_https_reports_plain_hop(self):
        # NPM auf 192.168.1.2, eingetragen: Browser → NPM HTTPS, NPM → ntp-gui HTTP durchs LAN.
        info = wt.resolve("192.168.1.2", hdrs({"X-Forwarded-For": "192.168.1.50", "X-Forwarded-Proto": "https"}),
                          wt.parse_networks(["192.168.1.2/32"]))
        self.assertEqual((info["scheme"], info["proxied"], info["peer_loopback"]), ("https", True, False))
        self.watch.note(info, "key")
        items = self.watch.insights(now=1000.0)
        self.assertEqual([i["key"] for i in items], ["web_proxy_hop_plain"])
        self.assertIn("unverschlüsselt", items[0]["title"])
        self.assertIsNone(self.watch.last_https)

    def test_untrusted_lan_proxy_counts_as_plain_too(self):
        info = wt.resolve("192.168.1.50", hdrs({"X-Forwarded-For": "1.2.3.4"}), [])
        self.watch.note(info, "basic")
        self.assertEqual(self.keys(), ["web_plain_http", "web_proxy_untrusted"])

    def test_untrusted_header_claiming_http_or_https_still_plain(self):
        for proto in ("http", "https"):
            with self.subTest(proto=proto):
                watch = wt.TransportWatch(clock=lambda: 1000.0)
                watch.note(wt.resolve("192.168.1.50", hdrs({"X-Forwarded-Proto": proto}), []), "basic")
                self.assertIn("web_plain_http", [i["key"] for i in watch.insights(now=1000.0)])

    def test_untrusted_proxy_on_loopback_only_info(self):
        self.watch.note(wt.resolve("127.0.0.1", hdrs({"X-Forwarded-For": "192.168.1.50"}), []), "basic")
        self.assertEqual(self.keys(), ["web_proxy_untrusted"])

    def test_untrusted_hint_clears_with_first_trusted_proxied_request(self):
        self.watch.note(wt.resolve("127.0.0.1", hdrs({"X-Forwarded-For": "192.168.1.50",
                                                      "X-Forwarded-Proto": "https"}), []), "basic", now=1000.0)
        self.assertEqual(self.keys(now=1000.0), ["web_proxy_untrusted"])
        trusted = wt.parse_networks(["127.0.0.1/32"])
        for step in range(1, 721):  # eine Stunde lang alle 5 s über den nun eingetragenen Proxy
            self.watch.note(wt.resolve("127.0.0.1", hdrs({"X-Forwarded-For": "192.168.1.50",
                                                          "X-Forwarded-Proto": "https"}), trusted),
                            "basic", now=1000.0 + step * 5)
        self.assertEqual(self.keys(now=1000.0 + 3600), [])

    def test_lan_proxy_untrusted_then_trusted_leaves_only_hop_hint(self):
        headers = hdrs({"X-Forwarded-For": "192.168.1.50", "X-Forwarded-Proto": "https"})
        self.watch.note(wt.resolve("192.168.1.2", headers, []), "basic", now=1000.0)
        self.watch.note(wt.resolve("192.168.1.2", headers, wt.parse_networks(["192.168.1.2/32"])), "basic", now=1005.0)
        self.assertNotIn("web_proxy_untrusted", self.keys(now=1010.0))
        self.watch.reset()  # so ruft es der Server nach Änderung von TRUSTED_PROXIES
        self.assertEqual(self.keys(now=1010.0), [])

    def test_plain_hint_expires_after_an_hour_once_https_follows(self):
        self.watch.note({"scheme": "http", "peer_loopback": False}, "basic", now=1000.0)
        self.watch.note({"scheme": "https", "proxied": True, "peer_loopback": True}, "basic", now=1100.0)
        self.assertEqual(self.keys(now=1000.0 + wt.FIXED_WINDOW - 1), ["web_plain_http"])
        self.assertEqual(self.keys(now=1000.0 + wt.FIXED_WINDOW + 1), [])

    def test_plain_hint_keeps_full_window_without_later_https(self):
        self.watch.note({"scheme": "https", "proxied": True, "peer_loopback": True}, "basic", now=900.0)
        self.watch.note({"scheme": "http", "peer_loopback": False}, "basic", now=1000.0)
        self.assertEqual(self.keys(now=1000.0 + wt.FIXED_WINDOW + 1), ["web_plain_http"])

    def test_hop_hint_expires_after_switch_to_local_proxy(self):
        self.watch.note({"scheme": "https", "proxied": True, "peer_loopback": False}, "basic", now=1000.0)
        self.watch.note({"scheme": "https", "proxied": True, "peer_loopback": True}, "basic", now=1001.0)
        self.assertEqual(self.keys(now=1000.0 + wt.FIXED_WINDOW + 1), [])

    # --- 1.5.1: Ursache und Absender ------------------------------------------------------------

    def test_direct_plain_names_client_kind_and_age(self):
        info = wt.resolve("192.168.1.30", hdrs({}), wt.parse_networks(["192.168.1.2/32"]))
        self.watch.note(info, "key", now=1000.0)
        item = self.watch.insights(now=1000.0 + 3 * 3600)[0]
        self.assertEqual(item["key"], "web_plain_http")
        self.assertIn("ein API-Schlüssel von 192.168.1.30 direkt per HTTP", item["text"])
        self.assertIn("zuletzt vor 3 h", item["text"])
        self.assertIn("Home-Assistant", item["text"])
        self.assertIn("1 Stunde", item["text"])
        self.assertIn("24 Stunden", item["text"])

    def test_trusted_lan_proxy_without_proto_is_own_hint_not_plain(self):
        # Fall aus einem Diagnosepaket: Proxy auf anderem Gerät, eingetragen, schickt nur X-Forwarded-For.
        trusted = wt.parse_networks(["192.168.1.2/32"])
        info = wt.resolve("192.168.1.2", hdrs({"X-Forwarded-For": "192.168.1.50"}), trusted)
        self.assertEqual((info["proxied"], info["proto_missing"]), (True, True))
        self.watch.note(info, "basic", now=1000.0)
        items = self.watch.insights(now=1000.0)
        # Proxy auf anderem Gerät: die Strecke Proxy → ntp-gui ist sicher HTTP – Hop-Hinweis gleich mit.
        self.assertEqual([i["key"] for i in items], ["web_proxy_no_proto", "web_proxy_hop_plain"])
        self.assertEqual(items[0]["level"], "info")
        self.assertIn("192.168.1.50 über 192.168.1.2", items[0]["text"])
        self.assertNotIn("kein Hinweis auf Klartext", items[0]["text"])
        self.assertIn("Strecke Proxy → ntp-gui ist unverschlüsselt", items[0]["text"])
        self.assertTrue(items[1]["text"].startswith("Der eingetragene Reverse Proxy läuft auf einem anderen"))
        for name in ("Caddy", "Nginx Proxy Manager", "Traefik", "Zoraxy", "HAProxy", "X-Forwarded-Proto $scheme"):
            self.assertIn(name, items[0]["text"])
        self.assertNotIn("Ungeschützt angekommen", items[0]["text"])
        self.assertIsNone(self.watch.last_plain)

    def test_forwarded_header_without_proto_is_no_proto(self):
        info = wt.resolve("127.0.0.1", hdrs({"Forwarded": "for=192.168.1.50"}), wt.parse_networks(["127.0.0.1/32"]))
        self.assertTrue(info["proto_missing"])
        self.watch.note(info, "basic")
        self.assertEqual(self.keys(), ["web_proxy_no_proto"])

    def test_no_proto_hint_clears_once_header_arrives(self):
        trusted = wt.parse_networks(["192.168.1.2/32"])
        self.watch.note(wt.resolve("192.168.1.2", hdrs({"X-Forwarded-For": "192.168.1.50"}), trusted),
                        "basic", now=1000.0)
        self.watch.note(wt.resolve("192.168.1.2", hdrs({"X-Forwarded-For": "192.168.1.50",
                                                        "X-Forwarded-Proto": "https"}), trusted),
                        "basic", now=1100.0)
        self.assertEqual(self.keys(now=1200.0), ["web_proxy_no_proto", "web_proxy_hop_plain"])
        self.assertEqual(self.keys(now=1000.0 + wt.FIXED_WINDOW + 1), ["web_proxy_hop_plain"])

    # --- 1.5.1: Prüfbefunde „web“ -----------------------------------------------------------------

    def test_lan_proxy_with_only_x_real_ip_is_no_proto_not_direct(self):
        trusted = wt.parse_networks(["192.168.1.5/32"])
        info = wt.resolve("192.168.1.5", hdrs({"X-Real-IP": "192.168.1.30"}), trusted)
        self.watch.note(info, "basic", now=1000.0)
        items = self.watch.insights(now=1000.0)
        self.assertEqual([i["key"] for i in items], ["web_proxy_no_proto", "web_proxy_hop_plain"])
        self.assertIn("dein Passwort von 192.168.1.30 über 192.168.1.5", items[0]["text"])
        self.assertIn("192.168.1.5 schickt X-Real-IP, aber weder X-Forwarded-Proto", items[0]["text"])
        self.assertIn("X-Forwarded-Proto $scheme", items[0]["text"])
        self.assertNotIn("direkt per HTTP", " ".join(i["text"] for i in items))

    def test_trusted_peer_without_any_header_is_labelled(self):
        trusted = wt.parse_networks(["192.168.1.5/32"])
        info = wt.resolve("192.168.1.5", hdrs({}), trusted)
        self.assertEqual((info["proxied"], info["peer_trusted"]), (False, True))
        self.watch.note(info, "basic", now=1000.0)
        item = self.watch.insights(now=1000.0)[0]
        self.assertEqual((item["key"], item["level"]), ("web_plain_http", "warn"))
        self.assertIn("von 192.168.1.5 direkt per HTTP (eingetragener Proxy, aber ohne jeden Proxy-Kopf)",
                      item["text"])
        self.assertIn("X-Forwarded-Proto $scheme", item["text"])

    def test_xff_with_forwarded_proto_uses_forwarded_proto(self):
        # HAProxy mit „option forwardfor“ und „option forwarded“
        trusted = wt.parse_networks(["192.168.1.5/32"])
        info = wt.resolve("192.168.1.5", hdrs({"X-Forwarded-For": "192.168.1.30",
                                               "Forwarded": "for=192.168.1.30;proto=https"}), trusted)
        self.assertEqual((info["scheme"], info["proto_missing"], info["client"]), ("https", False, "192.168.1.30"))

    def test_unknown_proto_value_named(self):
        trusted = wt.parse_networks(["192.168.1.5/32"])
        info = wt.resolve("192.168.1.5", hdrs({"X-Forwarded-For": "192.168.1.30",
                                               "X-Forwarded-Proto": "wss"}), trusted)
        self.assertEqual((info["proto_missing"], info["proto_value"]), (True, "wss"))
        self.watch.note(info, "basic", now=1000.0)
        text = self.watch.insights(now=1000.0)[0]["text"]
        self.assertIn("mit dem unbekannten Wert „wss“", text)
        self.assertNotIn("aber weder X-Forwarded-Proto", text)
        odd = wt.resolve("192.168.1.5", hdrs({"X-Forwarded-For": "192.168.1.30",
                                              "X-Forwarded-Proto": "<b>x</b>"}), trusted)
        self.assertEqual(odd["proto_value"], "?")

    def test_other_proxy_with_header_does_not_clear_no_proto(self):
        trusted = wt.parse_networks(["192.168.1.5/32", "127.0.0.1/32"])
        self.watch.note(wt.resolve("192.168.1.5", hdrs({"X-Forwarded-For": "192.168.1.30"}), trusted),
                        "basic", now=1000.0)
        self.watch.note(wt.resolve("127.0.0.1", hdrs({"X-Forwarded-For": "192.168.1.31",
                                                      "X-Forwarded-Proto": "https"}), trusted), "basic", now=1100.0)
        later = 1000.0 + wt.FIXED_WINDOW + 1
        self.assertIn("web_proxy_no_proto", self.keys(now=later))
        # Erst wenn DERSELBE Proxy den Kopf schickt, gilt es als behoben.
        self.watch.note(wt.resolve("192.168.1.5", hdrs({"X-Forwarded-For": "192.168.1.30",
                                                        "X-Forwarded-Proto": "https"}), trusted), "basic", now=1200.0)
        self.assertNotIn("web_proxy_no_proto", self.keys(now=later))

    def test_no_proto_does_not_clear_direct_plain(self):
        trusted = wt.parse_networks(["192.168.1.5/32"])
        self.watch.note(wt.resolve("192.168.1.40", hdrs({}), trusted), "key", now=1000.0)
        self.watch.note(wt.resolve("192.168.1.5", hdrs({"X-Forwarded-For": "192.168.1.30"}), trusted),
                        "basic", now=1100.0)
        self.assertIn("web_plain_http", self.keys(now=1000.0 + wt.FIXED_WINDOW + 1))

    def test_apache_help_is_conditional(self):
        self.assertIn("expr=%{REQUEST_SCHEME}", wt.PROTO_HELP)
        self.assertNotIn("RequestHeader set X-Forwarded-Proto https", wt.PROTO_HELP)

    def test_proxy_reporting_http_names_browser_and_proxy(self):
        trusted = wt.parse_networks(["127.0.0.1/32"])
        self.watch.note(wt.resolve("127.0.0.1", hdrs({"X-Forwarded-For": "192.168.1.50",
                                                      "X-Forwarded-Proto": "http"}), trusted), "basic")
        text = self.watch.insights(now=1000.0)[0]["text"]
        self.assertIn("dein Passwort von 192.168.1.50 über den eingetragenen Proxy 127.0.0.1", text)
        self.assertIn("Force SSL", text)

    def test_untrusted_proxy_named_as_cause(self):
        self.watch.note(wt.resolve("192.168.1.2", hdrs({"X-Forwarded-For": "192.168.1.50"}), []), "basic")
        items = self.watch.insights(now=1000.0)
        self.assertEqual([i["key"] for i in items], ["web_plain_http", "web_proxy_untrusted"])
        self.assertIn("über 192.168.1.2, das Proxy-Köpfe schickt", items[0]["text"])
        self.assertNotIn("192.168.1.50", items[0]["text"])  # Kopf unbeglaubigt – nicht nennen

    def test_lan_proxy_https_plus_direct_bookmark_both_named(self):
        # Proxy liefert HTTPS (Hop-Hinweis), aber ein anderes Gerät nutzt noch http://ip:8080.
        trusted = wt.parse_networks(["192.168.1.2/32"])
        self.watch.note(wt.resolve("192.168.1.2", hdrs({"X-Forwarded-For": "192.168.1.50",
                                                        "X-Forwarded-Proto": "https"}), trusted), "basic", now=1000.0)
        self.watch.note(wt.resolve("192.168.1.40", hdrs({}), trusted), "key", now=1001.0)
        items = self.watch.insights(now=1002.0)
        self.assertEqual([i["key"] for i in items], ["web_plain_http", "web_proxy_hop_plain"])
        self.assertIn("192.168.1.40 direkt per HTTP", items[0]["text"])
        self.assertNotIn("192.168.1.50", items[0]["text"])

    def test_several_sources_newest_first_and_capped(self):
        for i in range(wt.MAX_SOURCES + 3):
            self.watch.note({"client": f"192.168.1.{100 + i}", "peer": f"192.168.1.{100 + i}"}, "basic",
                            now=1000.0 + i)
        self.assertEqual(len(self.watch.plain), wt.MAX_SOURCES)
        text = self.watch.insights(now=1100.0)[0]["text"]
        newest = f"192.168.1.{100 + wt.MAX_SOURCES + 2}"
        self.assertLess(text.index(newest), text.index(f"192.168.1.{100 + wt.MAX_SOURCES + 1}"))
        self.assertIn(f"(und {wt.MAX_SOURCES - wt.SHOW_SOURCES} weitere)", text)

    def test_expiry_note_after_protected_access(self):
        self.watch.note({"client": "192.168.1.30"}, "basic", now=1000.0)
        self.watch.note({"scheme": "https", "proxied": True, "peer_loopback": True}, "basic", now=1100.0)
        self.assertIn("nur noch geschützte Zugriffe", self.watch.insights(now=1200.0)[0]["text"])

    def test_reset_forgets_sources(self):
        self.watch.note({"client": "192.168.1.30"}, "basic")
        self.watch.note(wt.resolve("192.168.1.2", hdrs({"X-Forwarded-For": "192.168.1.50"}),
                                   wt.parse_networks(["192.168.1.2/32"])), "basic")
        self.watch.reset()
        self.assertEqual(self.keys(), [])
        self.assertEqual((self.watch.plain, self.watch.no_proto), ({}, {}))

    def test_addresses_pseudonymised_if_hint_ever_leaves_through_egress(self):
        import egress
        self.watch.note({"client": "192.168.1.30", "peer": "192.168.1.30"}, "key")
        self.watch.note({"proxied": True, "proto_missing": True, "client": "192.168.1.50",
                         "peer": "192.168.1.2"}, "basic")
        clean, _ = egress.sanitize(self.watch.insights(now=1000.0), "diagnostics")
        self.assertNotIn("192.168.", json.dumps(clean))
        self.assertEqual(egress.check_no_leaks(clean), [])

    def test_ago(self):
        self.assertEqual(wt.ago(10), "gerade eben")
        self.assertEqual(wt.ago(12 * 60), "vor 12 min")
        self.assertEqual(wt.ago(3 * 3600), "vor 3 h")


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
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
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

    def test_saving_trusted_proxies_clears_hints(self):
        self.get("/api/v1", {"X-Forwarded-For": "192.168.1.50", "X-Forwarded-Proto": "https"})
        self.assertEqual([i["key"] for i in wt.WATCH.insights()], ["web_proxy_untrusted"])
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps({"changes": {"trusted_proxies": ["127.0.0.1/32"]}})
        conn.request("POST", "/api/settings", body=body, headers={
            "Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode(),
            "Content-Type": "application/json", "X-NTP-GUI": "1",
            "Origin": f"http://127.0.0.1:{self.port}"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertEqual(wt.WATCH.insights(), [])

    def test_trusted_proxy_without_proto_is_not_plain_warning(self):
        self.trust_local()
        self.get("/api/v1", {"X-Forwarded-For": "192.168.1.50"})
        items = wt.WATCH.insights()
        self.assertEqual([i["key"] for i in items], ["web_proxy_no_proto"])
        self.assertIn("192.168.1.50 über 127.0.0.1", items[0]["text"])

    def test_saving_trusted_proxies_clears_no_proto_hint(self):
        self.trust_local()
        self.get("/api/v1", {"X-Forwarded-For": "192.168.1.50"})
        self.assertTrue(wt.WATCH.no_proto)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps({"changes": {"trusted_proxies": ["::1/128"]}})
        conn.request("POST", "/api/settings", body=body, headers={
            "Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode(),
            "Content-Type": "application/json", "X-NTP-GUI": "1",
            "Origin": f"http://127.0.0.1:{self.port}"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertEqual(wt.WATCH.insights(), [])

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
    """Vorlagen ohne Caddy (1.5.1): Proxy-Option nach der Kommentar-Regel, Caddy nur in der Doku."""

    TEXT = (ROOT / "docker-compose.all-in-one.yml").read_text(encoding="utf-8")
    DOC = (ROOT / "docs" / "integrationen" / "https.md").read_text(encoding="utf-8")

    def uncommented(self):
        return re.sub(r"(?m)^( +)#  ", r"\1", self.TEXT)

    def test_proxy_option_present(self):
        text = self.uncommented()
        self.assertIn("[OPTION Reverse Proxy auf diesem Rechner]", self.TEXT)
        self.assertRegex(text, r'(?m)^      WEB_BIND: "127\.0\.0\.1"$')
        self.assertRegex(text, r'(?m)^      TRUSTED_PROXIES: "127\.0\.0\.1/32,::1/128"$')
        self.assertIn("docs/integrationen/https.md", self.TEXT)

    def test_no_caddy_in_any_template(self):
        for path in sorted(ROOT.glob("docker-compose*.yml")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotRegex(text, r"(?m)^\s*#?\s*caddy(-data)?:")       # weder Dienst noch Volume
                self.assertNotRegex(text, r"(?m)image: caddy")
                self.assertNotIn("OPTION HTTPS mit Caddy", text)
        self.assertNotRegex(self.TEXT, r"(?m)^\s+TRUSTED_PROXIES:")

    def test_version_hint_in_every_template(self):
        for path in sorted(ROOT.glob("docker-compose*.yml")):
            lines = path.read_text(encoding="utf-8").splitlines()
            with self.subTest(path=path.name):
                index = next(i for i, line in enumerate(lines)
                             if line.strip().startswith("image: ghcr.io/mgc20/ntp-gui:latest"))
                hint = "\n".join(lines[max(0, index - 8):index])
                if any(line.strip() == "build: ." for line in lines):
                    self.assertIn("lokalen Stand", hint)  # Version im Tag gilt nur fürs geladene Image
                self.assertIn("„:1.5“", hint)
                self.assertIn("„:1.5.1“", hint)
                self.assertIn("ghcr.io/congp20/ntp-gui", hint)
                # Erklärung, nie eine einkommentierbare Zeile („#  “ nach der Einrückung)
                self.assertNotRegex(hint, r"(?m)^ +#  ")

    def test_no_stale_template_references(self):
        files = [ROOT / "README.md", ROOT / "app" / "webtransport.py", ROOT / "app" / "settings.py",
                 ROOT / "app" / "static" / "js" / "help-web.js", ROOT / "docs" / "integrationen" / "https.md",
                 ROOT / "tests" / "container-test.sh"]
        for path in files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("Caddy-Vorlage", text)
                self.assertNotIn("OPTION HTTPS mit Caddy", text)

    def test_doc_has_standalone_caddy_compose(self):
        match = re.search(r"<!-- compose-caddy[^>]*-->\n```yaml\n(.*?)\n```", self.DOC, re.S)
        self.assertIsNotNone(match, "Caddy-Beispiel mit Markierung für den Container-Test")
        block = match.group(1)
        self.assertRegex(block, r"(?m)^services:\n  caddy:$")
        self.assertRegex(block, r"(?m)^volumes:\n  caddy-data:$")
        self.assertRegex(block, r"(?m)^    image: caddy:\d+\.\d+\.\d+$")  # gepinnt, nie :latest
        self.assertIn('"--internal-certs"', block)
        self.assertNotIn("depends_on", block, "eigener Stack – kein Verweis auf den ntp-gui-Dienst")

    def test_doc_exists_and_mentions_proxies(self):
        for word in ("Caddy", "Nginx Proxy Manager", "Zoraxy", "Traefik", "TRUSTED_PROXIES", "WEB_ALLOWED_HOSTS",
                     "Erlaubte Namen", "root.crt", "--internal-certs"):
            self.assertIn(word, self.DOC)


if __name__ == "__main__":
    unittest.main()
