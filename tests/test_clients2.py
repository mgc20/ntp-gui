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
        self.assertEqual(clientmon.typical_interval([2, 4]), 3)

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


class MetaTest(TempDataMixin, unittest.TestCase):
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

    def test_short_names_are_not_used_in_events(self):
        clientinfo.set_meta("192.168.1.7", "TV")
        self.assertEqual(clientinfo.label("192.168.1.7"), "192.168.1.7")

    def test_names_are_pseudonymised_on_export(self):
        clientinfo.set_meta("192.168.1.5", "Kinderzimmer Laptop")
        known = diagnostics._known_values({})
        self.assertIn("Kinderzimmer Laptop", known["name"])
        sanitizer = egress.Sanitizer("diagnostics", [], known)
        out = sanitizer.text("Uhr von Kinderzimmer Laptop weicht um +2,00 s ab (192.168.1.5)")
        self.assertNotIn("Kinderzimmer", out)
        self.assertNotIn("192.168.1.5", out)

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
        self.assertIsNone(clientinfo.rdns_allowed("192.168.1.5", {"clients_rdns": True, "dns_mode": "system"}))
        self.assertIn("Einstellungen", clientinfo.rdns_allowed("192.168.1.5", {"clients_rdns": False}))
        self.assertIn("öffentliche", clientinfo.rdns_allowed("8.8.8.8", {}))
        self.assertIn("TLS", clientinfo.rdns_allowed("192.168.1.5", {"dns_mode": "doh",
                                                                     "dns_doh": ["https://dns.example/dns-query"]}))
        self.assertIn("öffentlicher", clientinfo.rdns_allowed("192.168.1.5", {"dns_mode": "servers",
                                                                              "dns_servers": ["1.1.1.1"]}))
        self.assertIsNone(clientinfo.rdns_allowed("192.168.1.5", {"dns_mode": "servers",
                                                                  "dns_servers": ["192.168.1.1"]}))

    def test_lookup_cached_and_validated(self):
        calls = []

        def resolver(ip):
            calls.append(ip)
            return ("nas.fritz.box", [], [ip])
        self.assertEqual(clientinfo.reverse_name("192.168.1.5", resolver), "nas.fritz.box")
        self.assertEqual(clientinfo.reverse_name("192.168.1.5", resolver), "nas.fritz.box")
        self.assertEqual(len(calls), 1)
        self.assertIsNone(clientinfo.reverse_name("192.168.1.6", lambda ip: ("<script>", [], [])))

        def failing(ip):
            raise socket.herror(1, "unknown")
        self.assertIsNone(clientinfo.reverse_name("192.168.1.7", failing))

    def test_timeout(self):
        release = threading.Event()

        def slow(ip):
            release.wait(5)
            return ("slow.lan", [], [])
        started = time.monotonic()
        self.assertIsNone(clientinfo.reverse_name("192.168.1.8", slow, timeout=0.2))
        self.assertLess(time.monotonic() - started, 1.5)
        release.set()


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

        def serve():
            data, addr = server.recvfrom(512)
            now = time.time() + skew
            ts = clientinfo_ntp64(now)
            reply = bytes([0x24, 2, 6, 0xEC]) + bytes(8) + b"GPS\x00" + ts + data[40:48] + ts + ts
            server.sendto(b"\x00" * 10, addr)       # Müll wird übergangen
            server.sendto(reply, addr)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            result = clientinfo.ntp_query("127.0.0.1", port, timeout=2.0)
        finally:
            thread.join(3)
            server.close()
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["offset"], skew, delta=0.05)
        self.assertGreaterEqual(result["rtt"], 0)
        self.assertEqual(result["stratum"], 2)

    def test_query_no_answer(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        try:
            started = time.monotonic()
            self.assertIsNone(clientinfo.ntp_query("127.0.0.1", port, timeout=0.3))
            self.assertLess(time.monotonic() - started, 1.5)
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
                           threshold, label=lambda ip: "Kamera Hof", fmt=clientinfo.fmt_offset)

    def test_hysteresis(self):
        self.feed(2.0, 1)
        self.assertEqual(self.events, [])
        self.feed(2.0, 1)      # keine neue Messung → zählt nicht
        self.assertEqual(self.events, [])
        self.feed(2.1, 2)
        self.assertEqual(len(self.events), 1)
        kind, level, title, data = self.events[0]
        self.assertEqual((kind, level), ("clients", "warn"))
        self.assertEqual(title, "Uhr von Kamera Hof weicht um +2,10 s ab")
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
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
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
        cls.httpd.shutdown()
        cls.httpd.server_close()
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
