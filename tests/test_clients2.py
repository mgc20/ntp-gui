"""Clients 2.0 (1.4): Verlauf je Client, Detailseite, Netzüberblick, Nachmessen, Alarm.

Ohne echte Sockets zum LAN: Pakete von Hand, Resolver und NTP-Abfrage als Attrappen,
für ntp_query ein kleiner NTP-Server auf 127.0.0.1.
"""

import base64
import http.client
import json
import os
import shutil
import socket
import struct
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

import clientinfo  # noqa: E402
import clientmon  # noqa: E402
import diagnostics  # noqa: E402
import egress  # noqa: E402
import settings  # noqa: E402
import statewatch  # noqa: E402
import store  # noqa: E402


def ntp_request(xmit: int, version: int = 4, poll: int = 6, stratum: int = 0, precision: int = 0,
                refid: int = 0) -> bytes:
    head = struct.pack("!BBbb", (version << 3) | 3, stratum, poll, precision)
    return head + struct.pack("!III", 0, 0, refid) + bytes(24) + struct.pack("!Q", xmit)


def ipv4_udp(src: str, payload: bytes, dport: int = 123) -> bytes:
    udp = struct.pack("!HHHH", 40000, dport, 8 + len(payload), 0) + payload
    return struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 1, 0, 64, 17, 0,
                       socket.inet_aton(src), socket.inet_aton("192.168.1.2")) + udp


class TempDataMixin:
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved_dir = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        clientinfo._META_CACHE.update(t=0.0, data=None)
        clientinfo._reset_probe_limits()

    def tearDown(self):
        store.close_all()
        settings.DATA_DIR = self.saved_dir
        clientinfo._META_CACHE.update(t=0.0, data=None)
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# clientmon: Kopffelder, Abstände, Verlauf, MAC
# ---------------------------------------------------------------------------

class ParseTest(unittest.TestCase):
    def test_bare_and_full_header(self):
        bare = clientmon.parse_ntp(ntp_request(5, poll=0))
        self.assertTrue(bare["bare"])
        self.assertEqual(bare["stratum"], 0)
        full = clientmon.parse_ntp(ntp_request(5, stratum=3, precision=-23, refid=0x0A000001))
        self.assertFalse(full["bare"])
        self.assertEqual(full["stratum"], 3)
        self.assertEqual(full["precision"], -23)


class TableTest(unittest.TestCase):
    def test_typical_interval_ignores_burst(self):
        table = clientmon.ClientTable()
        t = 1_700_000_000.0
        for dt in (0, 2, 2, 2, 64, 64, 64, 64, 64):
            t += dt
            table.update("192.168.1.5", {"xmit": 1, "version": 4, "poll": 6}, 0.001, t)
        entry = table.snapshot()["192.168.1.5"]
        self.assertEqual(entry["interval"], 64)
        self.assertEqual(clientmon.typical_interval([]), None)
        self.assertEqual(clientmon.typical_interval([2, 4]), 4)
        self.assertEqual(clientmon.typical_interval([5, 7]), 6)

    def test_burst_alone_is_not_an_interval(self):
        # ntpd mit iburst: 8 Anfragen im Abstand von 2 s, danach erst 64 s (Befund C2-3)
        table = clientmon.ClientTable()
        t = 1_700_000_000.0
        for _ in range(8):
            t += 2
            table.update("192.168.1.6", {"xmit": 1, "version": 4, "poll": 6}, 0.001, t)
        entry = table.snapshot()["192.168.1.6"]
        self.assertIsNone(entry["interval"])
        out = clientinfo.overview({"192.168.1.6": entry}, {}, t + 130)
        self.assertEqual(out["chatty"], [])
        self.assertEqual(out["silent"], [])   # Ersatz 2^6 = 64 s → still erst nach 192 s
        # nach dem ersten echten Poll zählt der lange Abstand
        table.update("192.168.1.6", {"xmit": 1, "version": 4, "poll": 6}, 0.001, t + 64)
        self.assertEqual(table.snapshot()["192.168.1.6"]["interval"], 64)
        # wer dauerhaft alle 2 s fragt, ist wirklich auffällig
        for _ in range(13):
            t += 2
            table.update("192.168.1.7", {"xmit": 1, "version": 4, "poll": 6}, 0.001, t)
        entry = table.snapshot()["192.168.1.7"]
        self.assertEqual(entry["interval"], 2)
        out = clientinfo.overview({"192.168.1.7": entry}, {}, t + 1)
        self.assertEqual([c["address"] for c in out["chatty"]], ["192.168.1.7"])

    def test_cron_multi_sample_then_hourly(self):
        self.assertEqual(clientmon.typical_interval([2, 2, 2, 3600, 2, 2, 2]), 3600)

    def test_samples_are_spaced_and_keep_unmeasurable(self):
        table = clientmon.ClientTable()
        t = 1_700_000_000.0
        for i in range(10):
            table.update("192.168.1.5", {"xmit": 1, "version": 4, "poll": 6}, 0.002, t + i * 30)
        table.update("192.168.1.6", {"xmit": 0, "version": 4, "poll": 6}, None, t)
        rows = table.take_pending()
        mine = [r for r in rows if r[0] == "192.168.1.5"]
        self.assertEqual(len(mine), 3)  # 0, 120, 240 s
        self.assertAlmostEqual(mine[0][2], 0.002)
        other = [r for r in rows if r[0] == "192.168.1.6"]
        self.assertEqual(len(other), 1)
        self.assertIsNone(other[0][2])
        self.assertEqual(table.take_pending(), [])

    def test_mac_only_in_private_entry(self):
        table = clientmon.ClientTable()
        table.update("192.168.1.5", {"xmit": 1, "version": 4, "poll": 6, "mac": "aa:bb:cc:00:11:22"}, 0.001, 1.0)
        self.assertNotIn("mac", table.snapshot()["192.168.1.5"])
        self.assertEqual(table.snapshot(private=True)["192.168.1.5"]["mac"], "aa:bb:cc:00:11:22")


# Anfangszustand des Routen-Caches, wie ihn ein frisch gestarteter Prozess sieht
PRISTINE_ROUTES = dict(clientmon._ROUTES)


class MacTest(unittest.TestCase):
    def test_frame_mac(self):
        self.assertEqual(clientmon.frame_mac(("eth0", 0x800, 0, 1, b"\x00\x11\x22\x33\x44\x55")), "00:11:22:33:44:55")
        self.assertIsNone(clientmon.frame_mac(("eth0", 0x800, 0, 1, b"")))
        self.assertIsNone(clientmon.frame_mac(("eth0", 0x800, 0, 772, b"\x00\x11\x22\x33\x44\x55")))  # Loopback
        self.assertIsNone(clientmon.frame_mac(("eth0", 0x800, 0, 1, b"\x01\x00\x5e\x00\x00\x01")))  # Multicast

    def test_on_link(self):
        import ipaddress
        routes = ([("eth0", ipaddress.ip_network("192.168.1.0/24"))],
                  [("eth0", ipaddress.ip_network("fd00::/64"))])
        with mock.patch.object(clientmon, "_connected_routes", return_value=routes):
            self.assertTrue(clientmon.on_link("192.168.1.9", "eth0"))
            self.assertFalse(clientmon.on_link("192.168.1.9", "eth1"))
            self.assertFalse(clientmon.on_link("10.0.0.9", "eth0"))   # über Router → MAC des Routers
            self.assertTrue(clientmon.on_link("fd00::9", "eth0"))
            self.assertTrue(clientmon.on_link("fe80::1", "eth7"))

    def test_routes_read_shortly_after_boot(self):
        """Regression: monotonic() zählt ab Systemstart. Mit dem Anfangswert t=0.0 galt der leere
        Routen-Cache in der ersten Minute nach dem Booten als frisch – alle Clients „nicht im Netz“."""
        import io
        route = ("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
                 "docker0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n")
        real_open = open

        def fake_open(path, *args, **kwargs):
            if path == "/proc/net/route":
                return io.StringIO(route)
            if path == "/proc/net/ipv6_route":
                return io.StringIO("")
            return real_open(path, *args, **kwargs)

        saved = dict(clientmon._ROUTES)
        self.addCleanup(clientmon._ROUTES.update, saved)
        clientmon._ROUTES.update(PRISTINE_ROUTES)  # Zustand wie direkt nach dem Import
        with mock.patch.object(clientmon.time, "monotonic", return_value=30.0), \
                mock.patch("builtins.open", fake_open):
            v4, _v6 = clientmon._connected_routes()
            self.assertEqual([(i, str(n)) for i, n in v4], [("docker0", "172.17.0.0/16")])
            self.assertTrue(clientmon.on_link("172.17.0.5", "docker0"))

    def test_handle_records_mac_only_on_link(self):
        monitor = clientmon.Monitor(123)
        pkt = ipv4_udp("192.168.1.30", ntp_request(clientmon.unix_to_ntp64(1_700_000_000.0)))
        with mock.patch.object(clientmon, "on_link", side_effect=lambda ip, ifname: ip == "192.168.1.30"):
            monitor.handle(memoryview(pkt), ("eth0", 0x0800, 0, 1, b"\x02\x11\x22\x33\x44\x55"), [])
            pkt2 = ipv4_udp("10.9.9.9", ntp_request(clientmon.unix_to_ntp64(1_700_000_001.0)))
            monitor.handle(memoryview(pkt2), ("eth0", 0x0800, 0, 1, b"\x02\x11\x22\x33\x44\x66"), [])
        snap = monitor.table.snapshot(private=True)
        self.assertEqual(snap["192.168.1.30"]["mac"], "02:11:22:33:44:55")
        self.assertNotIn("mac", snap["10.9.9.9"])


class StorageTest(TempDataMixin, unittest.TestCase):
    def test_samples_roundtrip_and_restore(self):
        monitor = clientmon.Monitor(123)
        now = time.time()
        monitor.table.update("192.168.1.40", {"xmit": 1, "version": 3, "poll": 10, "mac": "00:11:22:33:44:55"},
                             0.02, now - 600)
        monitor.table.update("192.168.1.40", {"xmit": 1, "version": 3, "poll": 10}, 0.03, now - 300)
        self.assertEqual(monitor.flush_samples(), 2)
        with mock.patch.object(clientmon, "_MONITOR", None):
            rows = clientmon.samples("192.168.1.40")
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[-1][1], 0.03)
        self.assertEqual(rows[-1][2], 10)
        self.assertEqual(rows[-1][3], 3)
        self.assertAlmostEqual(rows[-1][4], 300, places=0)
        monitor._persist()
        # „Neustart“: neuer Monitor, erste/letzte Sichtung und MAC bleiben
        again = clientmon.Monitor(123)
        again._restore()
        entry = again.table.snapshot(private=True)["192.168.1.40"]
        self.assertAlmostEqual(entry["first_seen"], now - 600, places=3)
        self.assertAlmostEqual(entry["last_seen"], now - 300, places=3)
        self.assertEqual(entry["mac"], "00:11:22:33:44:55")
        self.assertEqual(entry["interval"], 300)
        # Ohne laufende Messung liefert client() den gespeicherten Stand
        with mock.patch.object(clientmon, "_MONITOR", None):
            self.assertEqual(clientmon.client("192.168.1.40")["version"], 3)
            self.assertIsNone(clientmon.client("192.168.1.99"))

    def test_rotating_sources_are_bounded(self):
        # CL2-SEC-2: wechselnde Absender erzeugen nicht je Paket eine Zeile
        table = clientmon.ClientTable()
        t = 1_700_000_000.0
        for i in range(9000):
            table.update(f"fd00::{i:x}", {"xmit": 1, "version": 4, "poll": 6}, 0.001, t + i * 0.001)
        self.assertEqual(len(table.clients), 2000)
        self.assertEqual(len(table.pending), clientmon.MAX_NEW_PER_FLUSH)
        self.assertGreater(table.dropped, 0)
        table.take_pending()
        # Bekannte Clients (zweite Anfrage) bekommen ihren Punkt weiter, aber höchstens MAX_PENDING
        for i in range(8999, 8999 - 2000, -1):
            table.update(f"fd00::{i:x}", {"xmit": 1, "version": 4, "poll": 6}, 0.001, t + 500)
        self.assertLessEqual(len(table.pending), clientmon.MAX_PENDING)
        self.assertGreater(len(table.pending), clientmon.MAX_NEW_PER_FLUSH)

    def test_prune_total_cap_and_orphans(self):
        clientmon._migrate(store)
        now = time.time()
        with store.transaction() as conn:
            conn.execute("INSERT INTO clientmon_clients(ip, data, updated) VALUES('192.168.1.2', '{}', ?)", (now,))
            conn.executemany("INSERT INTO clientmon_samples(ip, t, offset, poll, version, interval) "
                             "VALUES(?, ?, ?, ?, ?, ?)",
                             [("192.168.1.2", now - i, 0.1, 6, 4, None) for i in range(30)]
                             + [("fd00::99", now - 7200, 0.1, 6, 4, None), ("fd00::98", now - 10, 0.1, 6, 4, None)])
        clientmon.prune_samples(store, now, keep=100, total=20)
        left = dict(store.query("SELECT ip, COUNT(*) FROM clientmon_samples GROUP BY ip"))
        self.assertNotIn("fd00::99", left)        # verwaist und älter als 1 h
        self.assertEqual(sum(left.values()), 20)  # Gesamtgrenze, neueste bleiben
        self.assertIn("fd00::98", left)

    def test_stored_clients_bounded(self):
        monitor = clientmon.Monitor(123)
        with mock.patch.object(clientmon, "MAX_STORED_CLIENTS", 5):
            now = time.time()
            for i in range(8):
                monitor.table.update(f"192.168.5.{i}", {"xmit": 1, "version": 4, "poll": 6}, 0.001, now)
            monitor._persist()
        self.assertEqual(store.query("SELECT COUNT(*) FROM clientmon_clients")[0][0], 5)

    def test_prune_retention_and_cap(self):
        clientmon._migrate(store)
        now = time.time()
        rows = [("192.168.1.1", now - 8 * 86400, 0.1, 6, 4, None)]
        rows += [("192.168.1.2", now - i, 0.1, 6, 4, None) for i in range(20)]
        with store.transaction() as conn:
            conn.executemany("INSERT INTO clientmon_samples(ip, t, offset, poll, version, interval) "
                             "VALUES(?, ?, ?, ?, ?, ?)", rows)
        clientmon.prune_samples(store, now, keep=5)
        left = store.query("SELECT ip, COUNT(*), MIN(t) FROM clientmon_samples GROUP BY ip")
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0][0], "192.168.1.2")
        self.assertEqual(left[0][1], 5)
        self.assertAlmostEqual(left[0][2], now - 4)


# ---------------------------------------------------------------------------
# clientinfo
# ---------------------------------------------------------------------------

class AddressTest(unittest.TestCase):
    def test_clean_ip(self):
        self.assertEqual(clientinfo.clean_ip(" 192.168.1.5 "), "192.168.1.5")
        self.assertEqual(clientinfo.clean_ip("[FD00::1]"), "fd00::1")
        self.assertEqual(clientinfo.clean_ip("::ffff:10.0.0.1"), "10.0.0.1")
        for bad in ("", "foo", "192.168.1.300", "fe80::1%eth0", "1.2.3.4; rm", None, "x" * 100):
            self.assertIsNone(clientinfo.clean_ip(bad), bad)

    def test_is_lan(self):
        for ip in ("192.168.1.5", "10.0.0.1", "172.16.0.1", "fd00::1", "fe80::1", "100.64.0.1", "127.0.0.1"):
            self.assertTrue(clientinfo.is_lan(ip), ip)
        for ip in ("8.8.8.8", "2001:4860:4860::8888", "224.0.0.1", "0.0.0.0"):
            self.assertFalse(clientinfo.is_lan(ip), ip)

    def test_is_lan_rejects_tunnel_and_special_ranges(self):
        # CL2-SEC-4: 6to4 (trägt 8.8.8.8), Teredo, NAT64 und IANA-Sonderbereiche sind kein LAN
        for ip in ("2002:808:808::1", "2001::1", "64:ff9b::808:808", "64:ff9b:1::1",
                   "192.0.0.170", "198.18.0.1", "192.0.2.1", "2001:db8::1"):
            self.assertFalse(clientinfo.is_lan(ip), ip)
        self.assertTrue(clientinfo.is_lan("::ffff:192.168.1.5"))
        self.assertTrue(clientinfo.is_lan("169.254.1.1"))
        self.assertTrue(clientinfo.is_link_local("fe80::1"))
        self.assertFalse(clientinfo.is_link_local("169.254.1.1"))   # IPv4 braucht keinen Scope


class MetaTest(TempDataMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        fake_hostnames(self)  # notify → diagnostics._known_names ohne Rückwärts-DNS des Runners

    def test_set_get_delete(self):
        clientinfo.set_meta("192.168.1.5", "Drucker Büro", "stellt nur nach Neustart")
        self.assertEqual(clientinfo.names(), {"192.168.1.5": "Drucker Büro"})
        clientinfo.set_meta("192.168.1.5", None, "")   # Name bleibt, Notiz weg
        self.assertEqual(clientinfo.all_meta()["192.168.1.5"]["note"], "")
        self.assertEqual(clientinfo.label("192.168.1.5"), "Drucker Büro")
        clientinfo.set_meta("192.168.1.5", "", "")
        self.assertEqual(clientinfo.all_meta(), {})

    def test_validation(self):
        with self.assertRaises(clientinfo.MetaError):
            clientinfo.set_meta("kein-ip", "x")
        with self.assertRaises(clientinfo.MetaError):
            clientinfo.set_meta("192.168.1.5", "a" * 65)
        with self.assertRaises(clientinfo.MetaError):
            clientinfo.set_meta("192.168.1.5", "böse‮eman")
        with self.assertRaises(clientinfo.MetaError):
            clientinfo.set_meta("192.168.1.5", None, "x\x00y")
        self.assertEqual(clientinfo.set_meta("192.168.1.5", "  NAS\n  Keller ", "Zeile 1\nZeile 2")["name"],
                         "NAS Keller")

    def test_invisible_and_bidi_characters_rejected(self):
        # CL2-SEC-5: alle Cc/Cf-Zeichen (LRM, RLM, ALM, Nullbreite, BOM, C1) sowie Zl/Zp
        for ch in ("\u200e", "\u200f", "\u061c", "\u200b", "\u200c", "\u200d", "\ufeff", "\u2066",
                   "\u202e", "\u0085", "\u009b", "\u2028", "\u2029", "\u00ad"):
            with self.assertRaises(clientinfo.MetaError, msg=repr(ch)):
                clientinfo.clean_name(f"ab{ch}cd") if ch not in ("\u0085", "\u2028", "\u2029") \
                    else clientinfo.clean_note(f"ab{ch}cd")
            with self.assertRaises(clientinfo.MetaError, msg=repr(ch)):
                clientinfo.clean_note(f"ab{ch}cd")
        self.assertEqual(clientinfo.clean_note("Zeile 1\nZeile 2"), "Zeile 1\nZeile 2")
        self.assertEqual(clientinfo.clean_name("Küche – Ø 3 € ✓"), "Küche – Ø 3 € ✓")

    def test_label_falls_back_to_address(self):
        self.assertEqual(clientinfo.label("192.168.1.7"), "192.168.1.7")
        clientinfo.set_meta("192.168.1.7", "TV")
        self.assertEqual(clientinfo.label("192.168.1.7"), "TV")

    def test_names_are_pseudonymised_on_export(self):
        clientinfo.set_meta("192.168.1.5", "Kinderzimmer Laptop")
        known = diagnostics._known_values({})
        self.assertIn("Kinderzimmer Laptop", known["name"])
        sanitizer = egress.Sanitizer("diagnostics", [], known)
        out = sanitizer.text("Uhr von Kinderzimmer Laptop weicht um +2,00 s ab (192.168.1.5)")
        self.assertNotIn("Kinderzimmer", out)
        self.assertNotIn("192.168.1.5", out)

    def test_renamed_name_never_leaves_via_events(self):
        # C2-2/CL2-SEC-1: Titel enthält nur die Adresse; alte Titel (Entwicklungsstand) werden
        # beim Export aus den Daten neu gebaut; die Anzeige setzt den aktuellen Namen ein.
        import events
        watch = statewatch.StateWatcher(events.emit)
        clientinfo.set_meta("192.168.1.5", "Wohnzimmer-PC")
        for count in (1, 2):
            watch.clients({"192.168.1.5": {"measurable": True, "offset": 3.0, "count": count}}, 1000,
                          fmt=clientinfo.fmt_offset)
        events.emit("clients", "warn", "Uhr von Kinderzimmer Lisa weicht um +2,00 s ab",
                    {"address": "192.168.1.6", "offset": 2.0, "threshold_ms": 1000})
        rows = [r for r in events.query(limit=50) if r.get("kind") == "clients"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(r["title"] == "Uhr von 192.168.1.5 weicht um +3,00 s ab" for r in rows))
        shown = clientinfo.with_display_titles(rows)
        self.assertIn("Uhr von Wohnzimmer-PC weicht um +3,00 s ab", [r.get("display_title") for r in shown])
        clientinfo.set_meta("192.168.1.5", "", "")
        exported = json.dumps(diagnostics._collect_events({}, {}), ensure_ascii=False)
        self.assertNotIn("Wohnzimmer", exported)
        self.assertNotIn("Kinderzimmer", exported)
        self.assertIn("Uhr von 192.168.1.6 weicht um +2,00 s ab", exported)
        shown = clientinfo.with_display_titles(rows)
        self.assertNotIn("Wohnzimmer", json.dumps([r.get("display_title") for r in shown], ensure_ascii=False))

    def test_client_event_title_without_address(self):
        row = {"kind": "clients", "level": "info", "title": "Uhr von Geheim wieder im Rahmen", "data": {}}
        self.assertEqual(clientinfo.without_client_name(row)["title"], "Uhr eines Clients wieder im Rahmen")
        other = {"kind": "gps", "title": "GPS-Fix verloren"}
        self.assertIs(clientinfo.without_client_name(other), other)

    def test_notify_cache_invalidated(self):
        import notify
        notify._KNOWN["t"] = time.monotonic()
        clientinfo.set_meta("192.168.1.5", "Wohnzimmer Fernseher")
        names, values = notify._known()
        self.assertIn("Wohnzimmer Fernseher", values["name"])


class RdnsTest(unittest.TestCase):
    def setUp(self):
        clientinfo._RDNS.clear()

    def test_allowed(self):
        lan = lambda: ["192.168.1.1"]  # noqa: E731
        on = {"clients_rdns": True}
        self.assertIsNone(clientinfo.rdns_allowed("192.168.1.5", {**on, "dns_mode": "system"}, lan))
        self.assertIn("Einstellungen", clientinfo.rdns_allowed("192.168.1.5", {"clients_rdns": False}, lan))
        self.assertIn("öffentliche", clientinfo.rdns_allowed("8.8.8.8", on, lan))
        self.assertIn("TLS", clientinfo.rdns_allowed("192.168.1.5", {**on, "dns_mode": "doh",
                                                                     "dns_doh": ["https://dns.example/dns-query"]}, lan))
        self.assertIn("öffentlicher", clientinfo.rdns_allowed("192.168.1.5", {**on, "dns_mode": "servers",
                                                                              "dns_servers": ["1.1.1.1"]}, lan))
        self.assertIsNone(clientinfo.rdns_allowed("192.168.1.5", {**on, "dns_mode": "servers",
                                                                  "dns_servers": ["192.168.1.1"]}, lan))

    def test_off_by_default(self):
        # CL2-SEC-3: neuer Weg nach außen → Standard aus
        self.assertFalse(next(f for f in settings.SCHEMA if f["key"] == "clients_rdns")["default"])
        self.assertIn("Einstellungen", clientinfo.rdns_allowed("192.168.1.5", {}, lambda: ["192.168.1.1"]))

    def test_public_system_resolver_blocks(self):
        on = {"clients_rdns": True, "dns_mode": "system"}
        reason = clientinfo.rdns_allowed("192.168.1.5", on, lambda: ["8.8.8.8", "8.8.4.4"])
        self.assertIn("8.8.8.8", reason)
        self.assertIn("System-DNS", clientinfo.rdns_allowed("192.168.1.5", on, lambda: ["192.168.1.1", "1.1.1.1"]))
        self.assertIn("unbekannt", clientinfo.rdns_allowed("192.168.1.5", on, lambda: []))
        self.assertIn("unbekannt", clientinfo.rdns_allowed("192.168.1.5", on, lambda: None))
        self.assertIsNone(clientinfo.rdns_allowed("192.168.1.5", on, lambda: ["127.0.0.11"]))   # lokaler Stub
        # Eigene private Server mit Rückfall auf einen öffentlichen System-DNS: auch gesperrt
        servers = {"clients_rdns": True, "dns_mode": "servers", "dns_servers": ["192.168.1.1"]}
        self.assertIsNotNone(clientinfo.rdns_allowed("192.168.1.5", servers, lambda: ["8.8.8.8"]))
        # Ohne Rückfall entscheidet, wohin resolv.conf gerade zeigt: Weiterleiter aktiv (127.0.0.1) → erlaubt;
        # Weiterleiter ausgefallen und resolv.conf zeigt auf 8.8.8.8 → gesperrt (Befund der Abschlussprüfung 1.4).
        self.assertIsNone(clientinfo.rdns_allowed("192.168.1.5", {**servers, "dns_fallback": False},
                                                  lambda: ["127.0.0.1"]))
        self.assertIsNotNone(clientinfo.rdns_allowed("192.168.1.5", {**servers, "dns_fallback": False},
                                                     lambda: ["8.8.8.8"]))
        # 6to4-Adresse: kein LAN, keine Frage
        self.assertIsNotNone(clientinfo.rdns_allowed("2002:808:808::1", on, lambda: ["192.168.1.1"]))

    def test_system_resolvers_read_resolv_conf(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "resolv.conf")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# Docker\nnameserver 8.8.8.8\nnameserver 8.8.4.4\nsearch lan\n")
            import dnsfwd
            with mock.patch.object(dnsfwd, "RESOLV_CONF", path), \
                    mock.patch.object(dnsfwd.system_servers, "__defaults__", (path, os.path.join(tmp, "b"))):
                self.assertEqual(clientinfo._system_resolvers(), ["8.8.8.8", "8.8.4.4"])
                self.assertIn("8.8.8.8", clientinfo.rdns_allowed("192.168.1.5", {"clients_rdns": True}))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_lookup_cached_and_validated(self):
        calls = []

        def resolver(ip):
            calls.append(ip)
            return ("nas.fritz.box", [], [ip])
        # timeout=5: Hier geht es um Cache und Prüfung, nicht um die Frist (eigener Test unten).
        # Mit der Produktfrist (1 s) würde ein voller Runner None für 10 min cachen.
        self.assertEqual(clientinfo.reverse_name("192.168.1.5", resolver, timeout=5), "nas.fritz.box")
        self.assertEqual(clientinfo.reverse_name("192.168.1.5", resolver, timeout=5), "nas.fritz.box")
        self.assertEqual(len(calls), 1)
        self.assertIsNone(clientinfo.reverse_name("192.168.1.6", lambda ip: ("<script>", [], []), timeout=5))

        def failing(ip):
            raise socket.herror(1, "unknown")
        self.assertIsNone(clientinfo.reverse_name("192.168.1.7", failing, timeout=5))

    def test_timeout(self):
        release = threading.Event()

        self.addCleanup(release.set)

        def slow(ip):
            release.wait(30)  # hängt weit länger als die Schranke unten
            return ("slow.lan", [], [])
        started = time.monotonic()
        self.assertIsNone(clientinfo.reverse_name("192.168.1.8", slow, timeout=0.2))
        self.assertLess(time.monotonic() - started, 5)


class OuiTest(unittest.TestCase):
    def test_parse_and_lookup(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "oui.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("OUI/MA-L\t\t\tOrganization\n"
                             "00-1B-63   (hex)\t\tApple, Inc.\n001B63     (base 16)\t\tApple, Inc.\n"
                             "24-0A-C4   (hex)\t\tEspressif Inc.\n")
            saved = dict(clientinfo._OUI)
            clientinfo._OUI.update(loaded=False, table={}, path=None)
            try:
                info = clientinfo.mac_info("00:1b:63:aa:bb:cc", [path])
                self.assertEqual(info["vendor"], "Apple, Inc.")
                self.assertFalse(info["random"])
                rnd = clientinfo.mac_info("02:1b:63:aa:bb:cc", [path])
                self.assertTrue(rnd["random"])
                self.assertIsNone(rnd["vendor"])
                self.assertIsNone(clientinfo.mac_info("kaputt"))
            finally:
                clientinfo._OUI.clear()
                clientinfo._OUI.update(saved)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_nmap_format(self):
        self.assertEqual(clientinfo.parse_oui(["240AC4 Espressif", "# Kommentar"]), {"240AC4": "Espressif"})

    def test_no_list(self):
        saved = dict(clientinfo._OUI)
        clientinfo._OUI.update(loaded=False, table={}, path=None)
        try:
            info = clientinfo.mac_info("00:1b:63:aa:bb:cc", ["/nonexistent/oui.txt"])
            self.assertIsNone(info["vendor"])
            self.assertFalse(info["vendor_list"])
        finally:
            clientinfo._OUI.clear()
            clientinfo._OUI.update(saved)


class GuessTest(unittest.TestCase):
    def top(self, entry, mac=None, names=()):
        return clientinfo.guess_software(entry, mac, names)["candidates"][0]["key"]

    def test_windows(self):
        self.assertEqual(self.top({"version": 3, "poll": 10, "state": "ok", "stratum": 2}), "windows")
        self.assertEqual(self.top({"version": 4, "poll": 6, "state": "ok"}, names=["DESKTOP-AB12CD3"]), "windows")

    def test_chrony(self):
        self.assertEqual(self.top({"version": 4, "poll": 6, "state": "verschleiert", "stratum": 3}), "chrony")

    def test_timesyncd(self):
        guess = clientinfo.guess_software({"version": 4, "poll": 0, "state": "ok", "bare": True, "interval": 64})
        self.assertEqual(guess["candidates"][0]["key"], "timesyncd")
        self.assertTrue(all(c["confidence"] in ("wahrscheinlich", "möglich") for c in guess["candidates"]))

    def test_ntpd(self):
        self.assertEqual(self.top({"version": 4, "poll": 6, "state": "ok", "bare": False, "stratum": 3}), "ntpd")

    def test_iot(self):
        self.assertEqual(self.top({"version": 4, "poll": 0, "state": "ohne Zeitstempel", "bare": True,
                                   "interval": 3600}), "sntp")
        self.assertEqual(self.top({"version": 4, "state": "ok", "bare": True},
                                  {"vendor": "Espressif Inc.", "random": False}), "sntp")

    def test_apple(self):
        self.assertEqual(self.top({"version": 4, "state": "ok", "bare": True},
                                  {"vendor": "Apple, Inc.", "random": False}), "apple")

    def test_nothing_known(self):
        self.assertEqual(clientinfo.guess_software({})["candidates"], [])


class OverviewTest(unittest.TestCase):
    def test_bins_lists(self):
        now = 1_700_000_000.0
        clients = {
            "192.168.1.1": {"measurable": True, "state": "ok", "ewma": 0.0004, "last_seen": now - 10,
                            "requests": 50, "interval": 64},
            "192.168.1.2": {"measurable": True, "state": "ok", "ewma": -0.05, "last_seen": now - 10,
                            "requests": 50, "interval": 64},
            "192.168.1.3": {"measurable": True, "state": "ok", "ewma": 2.5, "last_seen": now - 5,
                            "requests": 50, "interval": 4},
            "192.168.1.4": {"measurable": True, "state": "falsche Uhr", "ewma": -1.7e9, "last_seen": now - 10,
                            "requests": 5, "interval": 1024},
            "192.168.1.5": {"measurable": False, "state": "verschleiert", "ewma": None, "last_seen": now - 1000,
                            "requests": 9, "interval": 64},
            "192.168.1.6": {"measurable": True, "state": "ok", "ewma": 0.003, "last_seen": now - 3 * 86400,
                            "requests": 9, "interval": None, "poll": 10},
        }
        out = clientinfo.overview(clients, {"192.168.1.3": {"name": "Kamera"}}, now)
        hist = {b["key"]: b["count"] for b in out["histogram"]}
        self.assertEqual(hist, {"lt1ms": 1, "1-10ms": 0, "10-100ms": 1, "0.1-1s": 0, "gt1s": 1, "wrong": 1})
        self.assertEqual(out["worst"][0]["address"], "192.168.1.4")
        self.assertEqual(out["worst"][1]["name"], "Kamera")
        silent = {c["address"] for c in out["silent"]}
        self.assertEqual(silent, {"192.168.1.5", "192.168.1.6"})
        self.assertEqual([c["address"] for c in out["chatty"]], ["192.168.1.3"])
        self.assertEqual(out["unmeasurable"], 1)

    def test_silent_rules(self):
        now = 1000.0
        self.assertIsNone(clientinfo.silent_reason({"last_seen": now - 100, "requests": 5, "interval": 64}, now))
        self.assertIsNotNone(clientinfo.silent_reason({"last_seen": now - 200, "requests": 5, "interval": 64}, now))
        self.assertIsNone(clientinfo.silent_reason({"last_seen": now - 200, "requests": 1, "interval": 64}, now))
        self.assertIsNotNone(clientinfo.silent_reason({"last_seen": now - 90000, "requests": 3}, now + 0))
        # Poll-Feld als Ersatz, wenn kein Abstand bekannt ist (Daten aus 1.3)
        self.assertIsNone(clientinfo.silent_reason({"last_seen": now - 2000, "requests": 3, "poll": 10}, now))
        self.assertIsNotNone(clientinfo.silent_reason({"last_seen": now - 4000, "requests": 3, "poll": 10}, now))


class ProbeTest(unittest.TestCase):
    def setUp(self):
        clientinfo._reset_probe_limits()

    def test_guards(self):
        known = lambda ip: ip == "192.168.1.5"  # noqa: E731
        with self.assertRaises(clientinfo.MetaError):
            clientinfo.probe("8.8.8.8", lambda ip: True, lambda ip: None)
        with self.assertRaises(clientinfo.MetaError):
            clientinfo.probe("192.168.1.6", known, lambda ip: None)
        with self.assertRaises(clientinfo.MetaError):
            clientinfo.probe("nicht-ip", known, lambda ip: None)
        result = clientinfo.probe("192.168.1.5", known, lambda ip: None)
        self.assertFalse(result["answered"])
        self.assertIn("normal", result["text"])

    def test_link_local_and_tunnel_not_probed(self):
        # C2-4: fe80:: ohne Scope-ID nicht erreichbar → klar ablehnen statt „antwortet nicht“
        calls = []
        with self.assertRaises(clientinfo.MetaError) as ctx:
            clientinfo.probe("fe80::1", lambda ip: True, lambda ip: calls.append(ip))
        self.assertIn("Link-lokal", str(ctx.exception))
        # CL2-SEC-4: 6to4/Teredo gehen über das Internet
        for ip in ("2002:808:808::1", "2001::1"):
            with self.assertRaises(clientinfo.MetaError):
                clientinfo.probe(ip, lambda ip: True, lambda ip: calls.append(ip))
        self.assertEqual(calls, [])

    def test_rate_limits(self):
        calls = []
        query = lambda ip: calls.append(ip) or {"offset": 0.01, "rtt": 0.001, "stratum": 2}  # noqa: E731
        ok = clientinfo.probe("192.168.1.5", lambda ip: True, query, now=100.0)
        self.assertAlmostEqual(ok["offset"], 0.01)
        with self.assertRaises(clientinfo.ProbeLimited):
            clientinfo.probe("192.168.1.5", lambda ip: True, query, now=110.0)
        clientinfo.probe("192.168.1.5", lambda ip: True, query, now=131.0)
        for i in range(8):
            clientinfo.probe(f"192.168.2.{i}", lambda ip: True, query, now=140.0)
        with self.assertRaises(clientinfo.ProbeLimited) as ctx:
            clientinfo.probe("192.168.3.1", lambda ip: True, query, now=141.0)
        self.assertGreater(ctx.exception.retry_after, 0)
        self.assertEqual(len(calls), 10)

    def test_query_against_local_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        skew = 0.25
        ready = threading.Event()

        def serve():
            ready.set()
            data, addr = server.recvfrom(512)
            now = time.time() + skew
            ts = clientinfo_ntp64(now)
            reply = bytes([0x24, 2, 6, 0xEC]) + bytes(8) + b"GPS\x00" + ts + data[40:48] + ts + ts
            server.sendto(b"\x00" * 10, addr)       # Müll wird übergangen
            server.sendto(reply, addr)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(10))
        try:
            result = clientinfo.ntp_query("127.0.0.1", port, timeout=5.0)
        finally:
            thread.join(3)
            server.close()
        self.assertIsNotNone(result)
        # Der Fake stempelt beim Antworten, nicht beim Empfang. NTP garantiert dann nur
        # |offset − skew| ≤ rtt/2 – ein fester Wert (0,05 s) scheiterte an jeder Thread-Verzögerung.
        self.assertGreaterEqual(result["rtt"], 0)
        self.assertLessEqual(abs(result["offset"] - skew), result["rtt"] / 2 + 0.02)
        self.assertEqual(result["stratum"], 2)

    def test_query_no_answer(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        try:
            started = time.monotonic()
            self.assertIsNone(clientinfo.ntp_query("127.0.0.1", port, timeout=0.3))
            self.assertLess(time.monotonic() - started, 5)
        finally:
            sock.close()

    def test_reply_needs_our_nonce(self):
        nonce = b"12345678"
        reply = bytes([0x24, 2, 6, 0]) + bytes(20) + nonce + bytes(16)
        self.assertIsNotNone(clientinfo.parse_server_reply(reply, nonce))
        self.assertIsNone(clientinfo.parse_server_reply(reply, b"87654321"))
        self.assertIsNone(clientinfo.parse_server_reply(bytes([0x23]) + reply[1:], nonce))  # Modus 3
        kod = bytes([0x24, 0, 6, 0]) + bytes(8) + b"RATE" + bytes(8) + nonce + bytes(16)
        self.assertEqual(clientinfo.parse_server_reply(kod, nonce)["kod"], "RATE")


def clientinfo_ntp64(unix: float) -> bytes:
    sec = int(unix) + clientinfo.NTP_EPOCH_OFFSET
    frac = int((unix % 1) * 2**32)
    return struct.pack("!II", sec, frac)


class FormatTest(unittest.TestCase):
    def test_fmt_offset(self):
        self.assertEqual(clientinfo.fmt_offset(0.0123), "+12 ms")
        self.assertEqual(clientinfo.fmt_offset(-0.0042), "−4,2 ms")
        self.assertEqual(clientinfo.fmt_offset(1.5), "+1,50 s")
        self.assertEqual(clientinfo.fmt_offset(-3 * 86400), "−3 Tage")


# ---------------------------------------------------------------------------
# Alarm (statewatch)
# ---------------------------------------------------------------------------

class AlarmTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.watch = statewatch.StateWatcher(lambda *a, **k: self.events.append(a))

    def feed(self, offset, count, threshold=1000, measurable=True):
        self.watch.clients({"192.168.1.5": {"measurable": measurable, "offset": offset, "count": count}},
                           threshold, fmt=clientinfo.fmt_offset)

    def test_hysteresis(self):
        self.feed(2.0, 1)
        self.assertEqual(self.events, [])
        self.feed(2.0, 1)      # keine neue Messung → zählt nicht
        self.assertEqual(self.events, [])
        self.feed(2.1, 2)
        self.assertEqual(len(self.events), 1)
        kind, level, title, data = self.events[0]
        self.assertEqual((kind, level), ("clients", "warn"))
        self.assertEqual(title, "Uhr von 192.168.1.5 weicht um +2,10 s ab")
        self.assertEqual(data["address"], "192.168.1.5")
        self.feed(0.7, 3)      # unter Schwelle, aber über der Hälfte: noch kein „wieder im Rahmen“
        self.feed(0.7, 4)
        self.assertEqual(len(self.events), 1)
        self.feed(0.1, 5)
        self.feed(0.1, 6)
        self.assertEqual(len(self.events), 2)
        self.assertEqual(self.events[1][1], "info")
        self.assertIn("wieder im Rahmen", self.events[1][2])

    def test_single_spike_no_alarm(self):
        self.feed(2.0, 1)
        self.feed(0.01, 2)
        self.feed(2.0, 3)
        self.assertEqual(self.events, [])

    def test_off_and_unmeasurable(self):
        self.feed(5.0, 1, threshold=0)
        self.feed(5.0, 2, threshold=0)
        self.feed(5.0, 3, measurable=False)
        self.feed(5.0, 4, measurable=False)
        self.assertEqual(self.events, [])


# ---------------------------------------------------------------------------
# HTTP: Rechte, Validierung, Antworten
# ---------------------------------------------------------------------------

class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import apikeys
        import server
        cls.server = server
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
        clientinfo._META_CACHE.update(t=0.0, data=None)
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        _, cls.read_key = apikeys.create("Lesen", "read")
        # Ein bekannter Client im gespeicherten Zustand (Messung läuft im Test nicht)
        monitor = clientmon.Monitor(123)
        monitor.table.update("192.168.1.40", {"xmit": 1, "version": 3, "poll": 10}, 0.02, time.time() - 30)
        monitor._persist()

    @classmethod
    def tearDownClass(cls):
        import apikeys
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        cls.server.AUTH_CACHE.clear()
        clientinfo._META_CACHE.update(t=0.0, data=None)
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = dict(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def basic(self):
        return {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode(), "X-NTP-GUI": "1"}

    def test_read_key_cannot_write_meta_or_probe(self):
        bearer = {"Authorization": f"Bearer {self.read_key}"}
        for path in ("/api/v1/clients/meta", "/api/v1/clients/probe", "/api/clients/meta"):
            status, payload = self.request("POST", path, {"ip": "192.168.1.40", "name": "x"}, bearer)
            self.assertEqual(status, 403, path)
            self.assertEqual(payload["scope_required"], "admin")
        status, _ = self.request("GET", "/api/v1/clients/overview", headers=bearer)
        self.assertEqual(status, 200)

    def test_csrf_for_browser(self):
        headers = self.basic()
        headers.pop("X-NTP-GUI")
        self.assertEqual(self.request("POST", "/api/clients/meta", {"ip": "192.168.1.40", "name": "Test"},
                                      headers)[0], 403)

    def test_meta_and_detail(self):
        status, payload = self.request("POST", "/api/clients/meta",
                                       {"ip": "192.168.1.40", "name": "Server Keller", "note": "Notiz"}, self.basic())
        self.assertEqual(status, 200, payload)
        status, payload = self.request("POST", "/api/clients/meta", {"ip": "192.168.1.40", "name": "a\x07b"},
                                       self.basic())
        self.assertEqual(status, 422)
        with mock.patch.object(clientinfo, "reverse_name", return_value=None):
            status, detail = self.request("GET", "/api/v1/clients/detail?ip=192.168.1.40", headers=self.basic())
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["name"], "Server Keller")
        self.assertEqual(detail["entry"]["version"], 3)
        self.assertEqual(detail["software"]["candidates"][0]["key"], "windows")
        self.assertTrue(detail["samples"])
        self.assertEqual(self.request("GET", "/api/clients/detail?ip=192.168.1.99", headers=self.basic())[0], 404)
        self.assertEqual(self.request("GET", "/api/clients/detail?ip=evil", headers=self.basic())[0], 400)
        status, offsets = self.request("GET", "/api/clients/offsets", headers=self.basic())
        self.assertEqual(offsets["names"], {"192.168.1.40": "Server Keller"})

    def test_probe_unknown_client(self):
        status, payload = self.request("POST", "/api/clients/probe", {"ip": "192.168.1.77"}, self.basic())
        self.assertEqual(status, 422)
        self.assertIn("bekannte", payload["error"])


if __name__ == "__main__":
    unittest.main()
