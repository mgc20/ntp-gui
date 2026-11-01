"""Tests für die passive Messung der Client-Uhren (clientmon.py).

Alle Pakete werden von Hand gebaut – es wird kein Socket geöffnet.
"""

import os
import shutil
import socket
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import clientmon  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402


def ntp_request(xmit: int, version: int = 4, mode: int = 3, poll: int = 6) -> bytes:
    head = struct.pack("!BBbb", (version << 3) | mode, 0, poll, -20)
    return head + bytes(36) + struct.pack("!Q", xmit)


def udp(payload: bytes, dport: int = 123, sport: int = 40000) -> bytes:
    return struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload


def ipv4(src: str, dst: str, l4: bytes, proto: int = 17, frag: int = 0, options: bytes = b"") -> bytes:
    ihl = (20 + len(options)) // 4
    head = struct.pack("!BBHHHBBH4s4s", 0x40 | ihl, 0, 20 + len(options) + len(l4), 1, frag, 64, proto, 0,
                       socket.inet_aton(src), socket.inet_aton(dst))
    return head + options + l4


def ipv6(src: str, dst: str, l4: bytes, nxt: int = 17, ext: bytes = b"") -> bytes:
    head = struct.pack("!IHBB16s16s", 6 << 28, len(ext) + len(l4), nxt, 64,
                       socket.inet_pton(socket.AF_INET6, src), socket.inet_pton(socket.AF_INET6, dst))
    return head + ext + l4


def ether(payload: bytes, ethertype: int) -> bytes:
    return b"\x02" * 6 + b"\x04" * 6 + struct.pack("!H", ethertype) + payload


class ParseTest(unittest.TestCase):
    def test_ipv4_ethernet(self):
        xmit = clientmon.unix_to_ntp64(1_700_000_000.5)
        frame = ether(ipv4("192.168.1.23", "192.168.1.10", udp(ntp_request(xmit, poll=10))), 0x0800)
        req = clientmon.parse_ethernet(frame, 123)
        self.assertEqual(req["src"], "192.168.1.23")
        self.assertEqual(req["sport"], 40000)
        self.assertEqual(req["version"], 4)
        self.assertEqual(req["poll"], 10)
        self.assertEqual(req["xmit"], xmit)

    def test_ipv4_with_options(self):
        pkt = ipv4("10.0.0.5", "10.0.0.1", udp(ntp_request(1)), options=b"\x01" * 4)
        self.assertEqual(clientmon.parse_network(0x0800, pkt, 123)["src"], "10.0.0.5")

    def test_ipv6_ethernet(self):
        pkt = ipv6("fd00::23", "fd00::1", udp(ntp_request(5, version=3)))
        req = clientmon.parse_ethernet(ether(pkt, 0x86DD), 123)
        self.assertEqual(req["src"], "fd00::23")
        self.assertEqual(req["version"], 3)

    def test_ipv6_hop_by_hop(self):
        ext = bytes([17, 0]) + bytes(6)  # Next Header UDP, Länge 0 → 8 Byte
        pkt = ipv6("fe80::1", "fe80::2", udp(ntp_request(7)), nxt=0, ext=ext)
        self.assertEqual(clientmon.parse_network(0x86DD, pkt, 123)["xmit"], 7)

    def test_vlan_and_qinq(self):
        inner = ipv4("192.168.20.7", "192.168.20.1", udp(ntp_request(9)))
        frame = b"\x02" * 6 + b"\x04" * 6 + struct.pack("!HHH", 0x8100, 20, 0x0800) + inner
        req = clientmon.parse_ethernet(frame, 123)
        self.assertEqual(req["vlan"], 20)
        frame = b"\x02" * 6 + b"\x04" * 6 + struct.pack("!HHHHH", 0x88A8, 100, 0x8100, 20, 0x0800) + inner
        req = clientmon.parse_ethernet(frame, 123)
        self.assertEqual(req["src"], "192.168.20.7")
        self.assertEqual(req["vlan"], 100)

    def test_rejects(self):
        good = udp(ntp_request(1))
        cases = [
            ipv4("1.2.3.4", "5.6.7.8", udp(ntp_request(1)), proto=6),             # TCP
            ipv4("1.2.3.4", "5.6.7.8", udp(ntp_request(1), dport=124)),           # anderer Port
            ipv4("1.2.3.4", "5.6.7.8", udp(ntp_request(1, mode=4))),              # Server-Antwort
            ipv4("1.2.3.4", "5.6.7.8", udp(ntp_request(1, mode=1))),              # symmetrisch
            ipv4("1.2.3.4", "5.6.7.8", udp(ntp_request(1, version=0))),           # Version 0
            ipv4("1.2.3.4", "5.6.7.8", udp(b"\x23" * 20)),                        # zu kurz
            ipv4("1.2.3.4", "5.6.7.8", good, frag=0x2000),                        # Fragment (MF)
            ipv4("1.2.3.4", "5.6.7.8", good, frag=0x0010),                        # Folgefragment
            ipv4("1.2.3.4", "5.6.7.8", good)[:30],                                # abgeschnitten
            b"",
            b"\x45",
            b"\x60" + bytes(10),
        ]
        for pkt in cases:
            self.assertIsNone(clientmon.parse_network(0x0800, pkt, 123))
        self.assertIsNone(clientmon.parse_network(0x0806, ipv4("1.2.3.4", "5.6.7.8", good), 123))
        self.assertIsNone(clientmon.parse_ethernet(b"\x00" * 10, 123))
        # Unsinn darf nie eine Ausnahme werfen.
        import random
        rnd = random.Random(1)
        for _ in range(2000):
            blob = bytes(rnd.getrandbits(8) for _ in range(rnd.randint(0, 120)))
            clientmon.parse_ethernet(blob, 123)
            clientmon.parse_network(0x0800, blob, 123)
            clientmon.parse_network(0x86DD, blob, 123)

    def test_custom_port(self):
        pkt = ipv4("1.2.3.4", "5.6.7.8", udp(ntp_request(1), dport=1123))
        self.assertIsNotNone(clientmon.parse_network(0x0800, pkt, 1123))
        self.assertIsNone(clientmon.parse_network(0x0800, pkt, 123))


class TimeTest(unittest.TestCase):
    def test_offset_simple(self):
        rx = 1_700_000_000 * 10**9
        self.assertAlmostEqual(clientmon.ntp_offset(clientmon.unix_to_ntp64(1_700_000_000.25), rx), 0.25, places=6)
        self.assertAlmostEqual(clientmon.ntp_offset(clientmon.unix_to_ntp64(1_699_999_998.0), rx), -2.0, places=6)

    def test_offset_nanoseconds(self):
        rx = 1_700_000_000 * 10**9 + 123_456_789
        xmit = clientmon.unix_to_ntp64(1_700_000_000.123456789 + 0.000_002)
        self.assertAlmostEqual(clientmon.ntp_offset(xmit, rx), 0.000_002, delta=2e-7)

    def test_era_rollover(self):
        # 2036-02-07 06:28:16 UTC: NTP-Sekunden laufen über (Ära 1 beginnt).
        rollover = TWO32 = 2**32
        rx_unix = rollover - 2208988800 + 1     # 1 s nach dem Überlauf
        client_ntp_seconds = TWO32 - 1          # Client: 1 s vor dem Überlauf, alte Ära
        xmit = client_ntp_seconds << 32
        self.assertAlmostEqual(clientmon.ntp_offset(xmit, rx_unix * 10**9), -2.0, places=6)
        # Und umgekehrt: Client schon in der neuen Ära, Server noch in der alten.
        xmit = 1 << 32
        self.assertAlmostEqual(clientmon.ntp_offset(xmit, (rollover - 2208988800 - 1) * 10**9), 2.0, places=6)

    def test_classify(self):
        self.assertEqual(clientmon.classify(0, 0.0, None), clientmon.NO_TIMESTAMP)
        self.assertEqual(clientmon.classify(5, 0.3, None), clientmon.OK)
        self.assertEqual(clientmon.classify(5, -3e7, None), clientmon.OBFUSCATED)
        self.assertEqual(clientmon.classify(5, -3e7 + 0.5, -3e7), clientmon.WRONG_CLOCK)
        self.assertEqual(clientmon.classify(5, 1e9, -3e7), clientmon.OBFUSCATED)

    def test_cmsg(self):
        data = struct.pack("@ll", 1_700_000_000, 5)
        self.assertEqual(clientmon.parse_timestamp_cmsg([(socket.SOL_SOCKET, clientmon.SCM_TIMESTAMPNS, data)]),
                         1_700_000_000 * 10**9 + 5)
        self.assertIsNone(clientmon.parse_timestamp_cmsg([]))

    def test_bpf_program_shape(self):
        prog = clientmon.bpf_program(123)
        self.assertLessEqual(len(prog), 64)
        for index, (code, jt, jf, _k) in enumerate(prog):
            if code & 0x07 == 0x05:  # Sprung: Ziel innerhalb des Programms
                self.assertLess(index + 1 + jt, len(prog))
                self.assertLess(index + 1 + jf, len(prog))
        self.assertEqual(prog[-1][0] & 0x07, 0x06)


class TableTest(unittest.TestCase):
    def feed(self, table, ip, offsets, xmit=1):
        for value in offsets:
            table.update(ip, {"xmit": xmit, "version": 4, "poll": 6}, value, time.time())

    def test_stats_and_states(self):
        table = clientmon.ClientTable()
        self.feed(table, "192.168.1.5", [0.010, 0.012, 0.008])
        self.feed(table, "192.168.1.6", [-4e8, 3e9, 1e9])          # chrony: Zufall
        self.feed(table, "192.168.1.7", [0.0], xmit=0)             # kein Zeitstempel
        self.feed(table, "192.168.1.8", [-1.7e9, -1.7e9 + 0.01, -1.7e9 + 0.02])  # Uhr auf 1970
        snap = table.snapshot()
        good = snap["192.168.1.5"]
        self.assertTrue(good["measurable"])
        self.assertEqual(good["count"], 3)
        self.assertAlmostEqual(good["min"], 0.008)
        self.assertAlmostEqual(good["max"], 0.012)
        self.assertAlmostEqual(good["offset"], 0.008)
        self.assertEqual(snap["192.168.1.6"]["state"], clientmon.OBFUSCATED)
        self.assertFalse(snap["192.168.1.6"]["measurable"])
        self.assertIsNone(snap["192.168.1.6"]["offset"])
        self.assertEqual(snap["192.168.1.7"]["state"], clientmon.NO_TIMESTAMP)
        self.assertEqual(snap["192.168.1.8"]["state"], clientmon.WRONG_CLOCK)
        self.assertTrue(snap["192.168.1.8"]["measurable"])

    def test_lru_bound(self):
        table = clientmon.ClientTable(limit=50)
        for i in range(120):
            self.feed(table, f"10.0.{i // 250}.{i % 250}", [0.001])
        self.assertEqual(len(table.clients), 50)
        self.assertIn("10.0.0.119", table.clients)
        self.assertNotIn("10.0.0.0", table.clients)

    def test_norm_ip(self):
        self.assertEqual(clientmon._norm_ip("::ffff:192.168.1.9"), "192.168.1.9")
        self.assertEqual(clientmon._norm_ip("FD00::1"), "fd00::1")


class MonitorHandleTest(unittest.TestCase):
    """Monitor.handle() ohne Socket: Duplikate, ausgehende Pakete, Kernel-Zeitstempel."""

    def setUp(self):
        self.monitor = clientmon.Monitor(123)

    def test_handle(self):
        rx_ns = 1_700_000_000 * 10**9
        pkt = ipv4("192.168.1.30", "192.168.1.10", udp(ntp_request(clientmon.unix_to_ntp64(1_700_000_000.5))))
        anc = [(socket.SOL_SOCKET, clientmon.SCM_TIMESTAMPNS, struct.pack("@ll", 1_700_000_000, 0))]
        self.monitor.handle(memoryview(pkt), ("eth0", 0x0800, 0, 1, b""), anc)
        self.monitor.handle(memoryview(pkt), ("docker0", 0x0800, 0, 1, b""), anc)   # Duplikat
        self.monitor.handle(memoryview(pkt), ("eth0", 0x0800, 4, 1, b""), anc)      # ausgehend
        self.monitor.handle(memoryview(b"\x45garbage"), ("eth0", 0x0800, 0, 1, b""), anc)
        self.assertEqual(self.monitor.packets, 1)
        self.assertEqual(self.monitor.ignored, 1)
        entry = self.monitor.table.snapshot()["192.168.1.30"]
        self.assertAlmostEqual(entry["offset"], 0.5, places=6)
        self.assertEqual(rx_ns // 10**9, int(entry["last_seen"]))


class ModuleTest(unittest.TestCase):
    def test_status_when_stopped(self):
        clientmon.stop()
        state = clientmon.status()
        self.assertFalse(state["available"])
        self.assertTrue(state["reason"])
        self.assertEqual(state["clients"], {})

    def test_nat_hint(self):
        self.assertIsNone(clientmon.nat_hint({}, "172.17.0.1"))
        self.assertIn("network_mode: host", clientmon.nat_hint({"172.17.0.1": {}}, "172.17.0.1"))
        self.assertIsNone(clientmon.nat_hint({"192.168.1.5": {}, "172.17.0.1": {}}, "172.17.0.1"))

    def test_persist_roundtrip(self):
        tmp = tempfile.mkdtemp()
        saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(tmp, "data")
        try:
            monitor = clientmon.Monitor(123)
            monitor.table.update("192.168.1.40", {"xmit": 1, "version": 4, "poll": 6}, 0.02, time.time())
            monitor._persist()
            again = clientmon.Monitor(123)
            again._restore()
            entry = again.table.snapshot()["192.168.1.40"]
            self.assertAlmostEqual(entry["offset"], 0.02)
            self.assertTrue(entry["measurable"])
        finally:
            store.close_all()
            settings.DATA_DIR = saved
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
