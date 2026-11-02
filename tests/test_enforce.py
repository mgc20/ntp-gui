"""Tests für „Zeitserver erzwingen“ (enforce.py): Namensliste, Snippets, Prüfung."""

import os
import socket
import struct
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import enforce  # noqa: E402

IP = "192.168.1.10"


def reply_packet(nonce: bytes, stratum=2, ref_id=b"\xc0\xa8\x01\x01", ref_time=1_700_000_000.0,
                 root_delay=0.01, mode=4) -> bytes:
    def ts(value):
        value += enforce.NTP_EPOCH_OFFSET
        return struct.pack("!II", int(value), int((value % 1) * 2**32))
    return (struct.pack("!BBbb", (4 << 3) | mode, stratum, 6, -20)
            + struct.pack("!iI", int(root_delay * 65536), 100) + ref_id + ts(ref_time)
            + nonce + ts(ref_time + 1) + ts(ref_time + 1.0001))


class HostListTest(unittest.TestCase):
    def test_known_hosts_valid_and_unique(self):
        hosts = [h["host"] for h in enforce.KNOWN_TIME_HOSTS]
        self.assertEqual(len(hosts), len(set(hosts)))
        for host in hosts:
            self.assertRegex(host, enforce._HOST_RE)
            self.assertIsNone(enforce.is_never_rewrite(host), host)
        for must in ("time.windows.com", "time.apple.com", "time.google.com", "time.android.com",
                     "pool.ntp.org", "2.europe.pool.ntp.org", "ntp.ubuntu.com", "3.ubnt.pool.ntp.org"):
            self.assertIn(must, hosts)

    def test_never_rewrite(self):
        for host in ("time.cloudflare.com", "nts.netnod.se", "ptbtime1.ptb.de", "nts.time.nl",
                     "ntp.zeitgitter.net", "fritz.box", "nts.example.org", "a.nts.example.org",
                     "cloudflare.com", "ptb.de", "box.fritz.box"):
            self.assertTrue(enforce.is_never_rewrite(host), host)
        hosts, skipped = enforce.merged_hostnames(["cam.example.com", "time.cloudflare.com", "Bad_Name",
                                                   "time.windows.com", "cloudflare.com"])
        names = [h["host"] for h in hosts]
        self.assertIn("cam.example.com", names)
        self.assertEqual(names.count("time.windows.com"), 1)
        self.assertEqual({s["host"] for s in skipped}, {"time.cloudflare.com", "bad_name", "cloudflare.com"})

    def test_collapse(self):
        zones = enforce.collapse_zones(["pool.ntp.org", "0.pool.ntp.org", "de.pool.ntp.org",
                                        "0.de.pool.ntp.org", "time.apple.com", "time.euro.apple.com"])
        self.assertEqual(sorted(zones), ["pool.ntp.org", "time.apple.com", "time.euro.apple.com"])


class SnippetTest(unittest.TestCase):
    def test_clean_server_ip(self):
        self.assertEqual(enforce.clean_server_ip(" 192.168.1.10 "), IP)
        self.assertEqual(enforce.clean_server_ip("[fd00::10]"), "fd00::10")
        for bad in (None, "", "127.0.0.1", "0.0.0.0", "::1", "172.17.0.2", "224.0.0.1",
                    "1.2.3.4; rm -rf /", "time.example.com", "192.168.1.10\naddress=/x/1.1.1.1"):
            self.assertIsNone(enforce.clean_server_ip(bad), bad)

    def test_all_systems_with_ip(self):
        result = enforce.snippets("all", IP, ["cam.example.com"], 123)
        self.assertEqual(result["server_ip"], IP)
        self.assertEqual([s["id"] for s in result["snippets"]], enforce.SYSTEM_IDS)
        for item in result["snippets"]:
            text = "\n".join(b["code"] for b in item["blocks"])
            self.assertIn(IP, text, item["id"])
            self.assertNotIn(enforce.IP_PLACEHOLDER, text, item["id"])
            self.assertNotIn("cloudflare", text)
            self.assertNotIn("ptbtime", text)
            self.assertIn(item["kind"], ("dns", "nat"))
            self.assertTrue(item["intro"])

    def test_without_ip_uses_placeholder(self):
        result = enforce.snippets("all", "127.0.0.1", [], 123)
        self.assertIsNone(result["server_ip"])
        for item in result["snippets"]:
            text = "\n".join(b["code"] for b in item["blocks"])
            self.assertIn(enforce.IP_PLACEHOLDER, text, item["id"])
            self.assertNotRegex(text, r"\b(?:192\.168|10\.\d+\.\d+\.\d+)", item["id"])

    def test_dns_contents(self):
        adguard = enforce.snip_adguard(IP, ["pool.ntp.org", "0.pool.ntp.org", "time.windows.com"])
        rules = adguard["blocks"][0]["code"].splitlines()
        self.assertIn(f"||pool.ntp.org^$dnsrewrite={IP},client=~{IP}", rules)
        self.assertEqual(len(rules), 2)
        dnsmasq = enforce.snip_dnsmasq(IP, ["pool.ntp.org", "time.windows.com"])["blocks"][0]["code"]
        self.assertIn(f"address=/pool.ntp.org/{IP}", dnsmasq)
        self.assertIn("local=/pool.ntp.org/", dnsmasq)
        unbound = enforce.snip_unbound("fd00::10", ["time.apple.com"])["blocks"][0]["code"]
        self.assertIn('local-zone: "time.apple.com." redirect', unbound)
        self.assertIn('"time.apple.com. 300 IN AAAA fd00::10"', unbound)
        pihole = enforce.snip_pihole(IP, ["time.apple.com"])
        self.assertIn(f'"{IP} time.apple.com"', pihole["blocks"][2]["code"])

    def test_nat_contents(self):
        mikrotik = enforce.snip_mikrotik(IP, [], 123)["blocks"][0]["code"]
        self.assertIn("src-address-list=!ntpgui", mikrotik)
        self.assertIn("action=masquerade", mikrotik)
        self.assertIn("connection-nat-state=dstnat", mikrotik)
        nft = enforce.snip_nftables(IP, [], 1123)["blocks"][0]["code"]
        self.assertIn("ip saddr != $NTPGUI", nft)
        self.assertIn("dnat to $NTPGUI:1123", nft)
        self.assertIn("ct status dnat", nft)
        openwrt = enforce.snip_openwrt(IP, [], 123)["blocks"][0]["code"]
        self.assertIn(f"src_ip='!{IP}'", openwrt)
        self.assertIn("MASQUERADE", openwrt)
        for func in (enforce.snip_opnsense, enforce.snip_unifi):
            item = func(IP, [], 123)
            self.assertTrue(any("Hairpin" in n for n in item["notes"]))

    def test_unknown_system(self):
        result = enforce.snippets("cisco", IP, [], 123)
        self.assertEqual(result["snippets"], [])
        self.assertIn("error", result)

    def test_port_warning_for_dns(self):
        item = enforce.snip_dnsmasq(IP, ["pool.ntp.org"], 1123)
        self.assertTrue(any("1123" in note for note in item["notes"]))


class ReplyTest(unittest.TestCase):
    def test_parse_reply(self):
        nonce = b"12345678"
        reply = enforce.parse_reply(reply_packet(nonce), nonce)
        self.assertEqual(reply["stratum"], 2)
        self.assertEqual(reply["ref_id"], "C0A80101")
        self.assertAlmostEqual(reply["ref_time"], 1_700_000_000.0, places=5)
        self.assertAlmostEqual(reply["root_delay"], 0.01, places=4)
        self.assertIsNone(enforce.parse_reply(reply_packet(nonce), b"other!!!"))
        self.assertIsNone(enforce.parse_reply(reply_packet(nonce, mode=3), nonce))
        self.assertIsNone(enforce.parse_reply(b"\x24" * 20))
        gps = enforce.parse_reply(reply_packet(nonce, stratum=1, ref_id=b"GPS\x00"), nonce)
        self.assertEqual(gps["ref_label"], "GPS")

    def test_request(self):
        packet, nonce = enforce.build_request()
        self.assertEqual(len(packet), 48)
        self.assertEqual(packet[0], 0x23)
        self.assertEqual(packet[40:], nonce)

    def test_same_server(self):
        ours = {"stratum": 2, "ref_id": "C0A80101", "ref_time": 1_700_000_000.0, "root_delay": 0.01}
        self.assertTrue(enforce.same_server(dict(ours, ref_time=1_700_000_000.0004), ours))
        self.assertFalse(enforce.same_server(dict(ours, stratum=1), ours))
        self.assertFalse(enforce.same_server(dict(ours, ref_id="474F4F47"), ours))
        self.assertFalse(enforce.same_server(dict(ours, ref_time=1_700_000_010.0), ours))
        self.assertFalse(enforce.same_server(None, ours))
        self.assertFalse(enforce.same_server(ours, None))

    def test_probe_many_local(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        server.settimeout(2)
        port = server.getsockname()[1]

        def serve():
            try:
                data, addr = server.recvfrom(100)
                server.sendto(b"junk", addr)                  # fremdes Paket wird ignoriert
                server.sendto(reply_packet(data[40:48]), addr)
            except OSError:
                pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            # Großzügige Frist: probe_many endet, sobald alle geantwortet haben – auf einem vollen
            # Runner muss der Server-Thread aber erst einmal drankommen.
            started = time.monotonic()
            result = enforce.probe_many([("127.0.0.1", port)], timeout=5)
        finally:
            thread.join(2)
            server.close()
        self.assertEqual(result[("127.0.0.1", port)]["stratum"], 2)
        self.assertLess(time.monotonic() - started, 5)

    def test_probe_many_quiet_target_times_out(self):
        silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        silent.bind(("127.0.0.1", 0))
        self.addCleanup(silent.close)
        quiet = silent.getsockname()
        self.assertEqual(enforce.probe_many([quiet], timeout=0.3), {quiet: None})


class CheckTest(unittest.TestCase):
    OURS = {"stratum": 2, "ref_id": "C0A80101", "ref_time": 1_700_000_000.0, "root_delay": 0.01}
    OTHER = {"stratum": 1, "ref_id": "474F4F47", "ref_time": 1_700_000_001.0, "root_delay": 0.0}

    def setUp(self):
        enforce._reset_rate_limit()

    def run_check(self, dns, replies, sources=None, **kw):
        def resolver(hosts, timeout):
            return {h: dns.get(h, ["203.0.113.9"]) for h in hosts}

        def prober(targets, timeout):
            return {t: replies.get(t[0]) for t in targets}

        return enforce.check([IP], ["cam.example.com"], 123, None, sources or [],
                             resolver=resolver, prober=prober, **kw)

    def test_verdicts(self):
        dns = {"time.windows.com": [IP], "time.apple.com": ["192.168.1.99"],
               "time.google.com": "Name nicht auflösbar", "pool.ntp.org": ["198.51.100.1"],
               "time.android.com": [IP, "2001:db8::1"]}
        replies = {"127.0.0.1": self.OURS, "192.168.1.99": self.OURS, "198.51.100.1": self.OTHER,
                   "216.239.35.0": self.OTHER, "162.159.200.1": None}
        result = self.run_check(dns, replies)
        rows = {r["host"]: r for r in result["hosts"]}
        self.assertEqual(rows["time.windows.com"]["state"], "dns_rewrite")
        self.assertEqual(rows["time.apple.com"]["state"], "answered_by_us")
        self.assertEqual(rows["time.google.com"]["state"], "dns_error")
        self.assertEqual(rows["pool.ntp.org"]["state"], "not_redirected")
        self.assertEqual(rows["time.android.com"]["state"], "dns_partial")
        self.assertEqual(rows["ntp.ubuntu.com"]["state"], "no_reply")
        self.assertIn("cam.example.com", rows)
        self.assertLessEqual(len(rows), enforce.MAX_TEST_HOSTS)
        public = {p["ip"]: p for p in result["public"]}
        self.assertEqual(public["216.239.35.0"]["state"], "direct")
        self.assertEqual(public["162.159.200.1"]["state"], "no_reply")
        self.assertEqual(result["loops"], [])
        for row in result["hosts"] + result["public"]:
            self.assertTrue(row["verdict"])

    def test_loop_detection(self):
        replies = {"127.0.0.1": self.OURS, "216.239.35.0": self.OURS, "162.159.200.1": self.OURS}
        result = self.run_check({"de.pool.ntp.org": [IP]}, replies, sources=["de.pool.ntp.org"])
        self.assertEqual(result["level"], "crit")
        self.assertEqual({p["state"] for p in result["public"]}, {"loop"})
        self.assertEqual(result["loops"][0]["host"], "de.pool.ntp.org")

    def test_tracking_fallback(self):
        tracking = {"stratum": 2, "ref_id": "c0a80101", "ref_time": 1_700_000_000.0, "root_delay": 0.01}

        def prober(targets, timeout):
            return {t: (self.OURS if t[0] == "192.168.1.99" else None) for t in targets}

        result = enforce.check([IP], [], 123, tracking, [],
                               resolver=lambda hosts, t: {h: ["192.168.1.99"] for h in hosts}, prober=prober)
        self.assertTrue(all(r["state"] == "answered_by_us" for r in result["hosts"]))
        self.assertEqual(result["level"], "good")

    def test_rate_limit(self):
        clock = [1000.0]
        first = self.run_check({}, {}, now=lambda: clock[0], clock=lambda: clock[0])
        self.assertFalse(first["cached"])
        clock[0] += 10
        second = self.run_check({}, {}, now=lambda: clock[0], clock=lambda: clock[0])
        self.assertTrue(second["cached"])
        self.assertGreater(second["retry_after"], 0)
        clock[0] += 25
        self.assertFalse(self.run_check({}, {}, now=lambda: clock[0], clock=lambda: clock[0])["cached"])

    def test_rate_limit_ignores_wall_clock_step(self):
        """Regression: Stellt chrony die Uhr zurück (Pi ohne RTC), darf das die 30-s-Sperre nicht
        verlängern – der Abstand wird monoton gemessen, die Uhrzeit nur angezeigt."""
        wall, mono = [2_000_000_000.0], [500.0]
        kw = {"now": lambda: wall[0], "clock": lambda: mono[0]}
        self.assertFalse(self.run_check({}, {}, **kw)["cached"])
        wall[0] -= 86400  # Uhr springt einen Tag zurück
        mono[0] += 31
        result = self.run_check({}, {}, **kw)
        self.assertFalse(result["cached"])
        self.assertEqual(result["time"], wall[0])

    def test_never_probes_protected_names(self):
        result = self.run_check({}, {}, sources=[])
        self.assertFalse(any(enforce.is_never_rewrite(r["host"]) for r in result["hosts"]))
        enforce._reset_rate_limit()
        result = enforce.check([IP], ["time.cloudflare.com"], 123, None, [],
                               resolver=lambda h, t: {x: [] for x in h}, prober=lambda t, s: {})
        self.assertNotIn("time.cloudflare.com", [r["host"] for r in result["hosts"]])

    def test_source_hosts_from(self):
        cfg = {"ntp_sources": [{"host": "pool.ntp.org"}, {"host": "192.0.2.1"}, {"host": "ptbtime1.ptb.de"}]}
        self.assertEqual(enforce.source_hosts_from(cfg), ["pool.ntp.org", "ptbtime1.ptb.de"])


if __name__ == "__main__":
    unittest.main()
