"""DNS für ntp-gui (dnsfwd): Wire-Format-Hilfen, Upstreams (UDP/TCP, DoT, DoH) gegen
eigene Test-Server, Ausfall/Rückfall/Cache/Schleifenschutz, Server nur auf Loopback,
resolv.conf-Umschaltung, Einstellungen, Hinweise und Firewall-Anleitungen.

Kein Internet nötig: Alle Upstreams laufen in diesem Prozess auf 127.0.0.1; TLS mit
einer eigenen Test-CA (openssl), sonst werden die TLS-Tests übersprungen.
"""

import errno
import http.server
import ipaddress
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import dnsfwd  # noqa: E402
import enforce  # noqa: E402
import insights  # noqa: E402
import settings  # noqa: E402

ANSWER_IP = "192.0.2.53"


def make_answer(query: bytes, ip: str = ANSWER_IP, ttl: int = 120, count: int = 1, rcode: int = 0) -> bytes:
    ident, flags, qd, _an, _ns, _ar = struct.unpack("!HHHHHH", query[:12])
    end = dnsfwd.question_end(query)
    head = struct.pack("!HHHHHH", ident, 0x8180 | (flags & 0x0100) | rcode, qd, count if not rcode else 0, 0, 0)
    body = query[12:end]
    if not rcode:
        base = int(ipaddress.IPv4Address(ip))
        for i in range(count):
            body += b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, ttl, 4) + ipaddress.IPv4Address(base + i).packed
    return head + body


class FakeDns:
    """UDP+TCP-DNS auf 127.0.0.1 mit zufälligem Port. big=True → Antwort > 512 Byte;
    tc=True → per UDP nur TC-Bit (der Client muss per TCP nachfragen)."""

    def __init__(self, ip: str = ANSWER_IP, big: bool = False, tc: bool = False, ttl: int = 120,
                 delay: dict | None = None, rcode: int = 0) -> None:
        self.ip, self.big, self.tc, self.ttl = ip, big, tc, ttl
        self.delay = delay or {}  # Name → Sekunden bis zur Antwort
        self.rcode = rcode
        self.udp_count = 0
        self.tcp_count = 0
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.port = self.udp.getsockname()[1]
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(("127.0.0.1", self.port))
        self.tcp.listen(8)
        self.stop = False
        threading.Thread(target=self._udp, daemon=True).start()
        threading.Thread(target=self._tcp, daemon=True).start()

    def answer(self, query: bytes) -> bytes:
        return make_answer(query, self.ip, self.ttl, 40 if self.big else 1, self.rcode)

    def _udp(self) -> None:
        while not self.stop:
            try:
                data, addr = self.udp.recvfrom(65535)
            except OSError:
                return
            self.udp_count += 1
            threading.Thread(target=self._udp_one, args=(data, addr), daemon=True).start()

    def _udp_one(self, data: bytes, addr) -> None:
        name = data[13:13 + data[12]].decode("ascii", "replace") if len(data) > 13 else ""
        wait = self.delay.get(name)
        if wait:
            time.sleep(wait)
        reply = self.answer(data)
        if self.tc:
            reply = dnsfwd.truncated(reply)
        try:
            self.udp.sendto(reply, addr)
        except OSError:
            pass

    def _tcp(self) -> None:
        while not self.stop:
            try:
                conn, _ = self.tcp.accept()
            except OSError:
                return
            threading.Thread(target=self.serve_stream, args=(conn,), daemon=True).start()

    def serve_stream(self, conn) -> None:
        with conn:
            try:
                (n,) = struct.unpack("!H", dnsfwd._recv_exact(conn, 2, time.monotonic() + 3))
                query = dnsfwd._recv_exact(conn, n, time.monotonic() + 3)
            except OSError:
                return
            self.tcp_count += 1
            reply = self.answer(query)
            conn.sendall(struct.pack("!H", len(reply)) + reply)

    def close(self) -> None:
        self.stop = True
        self.udp.close()
        self.tcp.close()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ask_udp(port: int, query: bytes, timeout: float = 6.0) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(query, ("127.0.0.1", port))
        return s.recv(65535)


class WireTest(unittest.TestCase):
    def test_query_roundtrip(self):
        query = dnsfwd.build_query("pool.ntp.org", dnsfwd.TYPE_A)
        self.assertEqual(dnsfwd.question(query), b"\x04pool\x03ntp\x03org\x00\x00\x01\x00\x01")
        answer = make_answer(query, ttl=77)
        self.assertTrue(dnsfwd.valid_response(query, answer))
        self.assertEqual(dnsfwd.addresses(answer, dnsfwd.TYPE_A), ([ANSWER_IP], 77))
        self.assertEqual(dnsfwd.cache_ttl(answer), 77)

    def test_invalid_response_rejected(self):
        query = dnsfwd.build_query("a.example", dnsfwd.TYPE_A)
        other = dnsfwd.build_query("b.example", dnsfwd.TYPE_A)
        self.assertFalse(dnsfwd.valid_response(query, make_answer(other)))   # andere Frage
        self.assertFalse(dnsfwd.valid_response(query, query))                # kein QR-Bit
        self.assertFalse(dnsfwd.valid_response(query, dnsfwd.with_id(make_answer(query), 1 ^ struct.unpack("!H", query[:2])[0])))
        self.assertFalse(dnsfwd.valid_response(query, b"\x00" * 5))

    def test_cache_ttl_caps_and_negative(self):
        query = dnsfwd.build_query("a.example", dnsfwd.TYPE_A)
        self.assertEqual(dnsfwd.cache_ttl(make_answer(query, ttl=86400)), dnsfwd.CACHE_MAX_TTL)
        self.assertEqual(dnsfwd.cache_ttl(make_answer(query, rcode=3)), dnsfwd.CACHE_NEG_TTL)
        self.assertEqual(dnsfwd.cache_ttl(make_answer(query, rcode=2)), 0)
        self.assertEqual(dnsfwd.cache_ttl(dnsfwd.truncated(make_answer(query))), 0)

    def test_patch_ttls(self):
        query = dnsfwd.build_query("a.example", dnsfwd.TYPE_A)
        patched = dnsfwd.patch_ttls(make_answer(query, ttl=100, count=2), 30)
        self.assertEqual([r["ttl"] for r in dnsfwd.records(patched)], [70, 70])

    def test_udp_limit_and_truncation(self):
        query = dnsfwd.build_query("a.example", dnsfwd.TYPE_A)
        self.assertEqual(dnsfwd.udp_limit(query), 512)
        edns = query[:10] + b"\x00\x01" + query[12:] + b"\x00" + struct.pack("!HHIH", 41, 1232, 0, 0)
        self.assertEqual(dnsfwd.udp_limit(edns), 1232)
        big = make_answer(query, count=40)
        cut = dnsfwd.truncated(big)
        self.assertTrue(struct.unpack("!H", cut[2:4])[0] & dnsfwd.FLAG_TC)
        self.assertLess(len(cut), 512)

    def test_malformed_names(self):
        for bad in (b"\x00" * 12 + b"\x05ab", b"\x00\x00\x00\x00\x00\x01" + b"\x00" * 6 + b"\x80\x00"):
            data = bad[:4] + b"\x00\x01" + bad[6:] if len(bad) >= 6 else bad
            with self.assertRaises(dnsfwd.DnsError):
                dnsfwd.question_end(data)
        loop = b"\x00\x01\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + b"\x01a" * 200 + b"\x00\x00\x01\x00\x01"
        with self.assertRaises(dnsfwd.DnsError):
            dnsfwd.question_end(loop)

    def test_reply_code(self):
        query = dnsfwd.build_query("a.example", dnsfwd.TYPE_A)
        fail = dnsfwd.reply_code(query, dnsfwd.RCODE_SERVFAIL)
        self.assertEqual(fail[:2], query[:2])
        self.assertEqual(struct.unpack("!H", fail[2:4])[0] & 0x800F, 0x8002)
        self.assertIsNone(dnsfwd.reply_code(b"\x01", 2))


class PlainUpstreamTest(unittest.TestCase):
    def test_udp_and_tcp_fallback_on_tc(self):
        fake = FakeDns(tc=True)
        self.addCleanup(fake.close)
        up = dnsfwd.PlainUpstream("127.0.0.1", fake.port)
        query = dnsfwd.build_query("pool.ntp.org", dnsfwd.TYPE_A)
        data = up.exchange(query, time.monotonic() + 3)
        self.assertEqual(dnsfwd.addresses(data, dnsfwd.TYPE_A)[0], [ANSWER_IP])
        self.assertEqual((fake.udp_count, fake.tcp_count), (1, 1))

    def test_timeout(self):
        silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        silent.bind(("127.0.0.1", 0))
        self.addCleanup(silent.close)
        up = dnsfwd.PlainUpstream("127.0.0.1", silent.getsockname()[1])
        started = time.monotonic()
        with self.assertRaises(OSError):
            up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 0.3)
        self.assertLess(time.monotonic() - started, 2)


def _make_ca(directory: Path):
    """Test-CA und Server-Zertifikat für dns.test (+ IP 127.0.0.1) per openssl."""
    openssl = shutil.which("openssl")
    if not openssl:
        return None
    run = lambda *args: subprocess.run([openssl, *args], cwd=directory, capture_output=True, check=True, timeout=60)
    (directory / "ext.cnf").write_text("subjectAltName=DNS:dns.test,IP:127.0.0.1\n"
                                       "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\n"
                                       "extendedKeyUsage=serverAuth\n")
    try:
        run("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
            "-keyout", "ca.key", "-out", "ca.pem", "-days", "2", "-subj", "/CN=ntp-gui Test-CA",
            "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        run("req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
            "-keyout", "srv.key", "-out", "srv.csr", "-subj", "/CN=dns.test")
        run("x509", "-req", "-in", "srv.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
            "-out", "srv.pem", "-days", "2", "-extfile", "ext.cnf")
    except subprocess.CalledProcessError:
        return None
    client = ssl.create_default_context(cafile=str(directory / "ca.pem"))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(str(directory / "srv.pem"), str(directory / "srv.key"))
    return client, server


class TlsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        ctxs = _make_ca(cls.tmp)
        if not ctxs:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise unittest.SkipTest("openssl fehlt – TLS-Tests übersprungen")
        cls.client_ctx, cls.server_ctx = ctxs

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def bootstrap(self, ips=("127.0.0.1",)):
        boot = mock.Mock()
        boot.resolve.return_value = list(ips)
        return boot


class DotTest(TlsBase):
    def start_dot(self):
        fake = FakeDns()
        self.addCleanup(fake.close)
        lsock = socket.socket()
        lsock.bind(("127.0.0.1", 0))
        lsock.listen(4)
        self.addCleanup(lsock.close)

        def loop():
            while True:
                try:
                    conn, _ = lsock.accept()
                except OSError:
                    return
                try:
                    tls = self.server_ctx.wrap_socket(conn, server_side=True)
                except (OSError, ssl.SSLError):
                    conn.close()
                    continue
                threading.Thread(target=fake.serve_stream, args=(tls,), daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()
        return fake, lsock.getsockname()[1]

    def test_dot_with_pin_and_cert_check(self):
        fake, port = self.start_dot()
        boot = self.bootstrap()
        up = dnsfwd.DotUpstream("dns.test", "dns.test", port, ["127.0.0.1"], boot, self.client_ctx)
        query = dnsfwd.build_query("pool.ntp.org", dnsfwd.TYPE_A)
        data = up.exchange(query, time.monotonic() + 3)
        self.assertEqual(dnsfwd.addresses(data, 1)[0], [ANSWER_IP])
        boot.resolve.assert_not_called()  # feste Adresse: kein System-DNS nötig
        self.assertEqual(fake.tcp_count, 1)

    def test_dot_bootstrap_used_without_pin(self):
        _fake, port = self.start_dot()
        boot = self.bootstrap()
        up = dnsfwd.DotUpstream("dns.test", "dns.test", port, [], boot, self.client_ctx)
        up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 3)
        boot.resolve.assert_called_once()

    def test_dot_wrong_name_fails(self):
        _fake, port = self.start_dot()
        up = dnsfwd.DotUpstream("falsch.test", "falsch.test", port, ["127.0.0.1"], self.bootstrap(), self.client_ctx)
        with self.assertRaises(OSError):
            up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 3)

    def test_dot_untrusted_ca_fails(self):
        _fake, port = self.start_dot()
        up = dnsfwd.DotUpstream("dns.test", "dns.test", port, ["127.0.0.1"], self.bootstrap(), dnsfwd.tls_context())
        with self.assertRaises(OSError):
            up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 3)


class DohTest(TlsBase):
    def start_doh(self, mode="ok"):
        calls = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                calls.append((self.path, self.headers.get("Content-Type"), self.headers.get("Accept"),
                              self.headers.get("User-Agent")))
                if mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://dns.test/anders")
                    self.end_headers()
                    return
                reply = make_answer(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/html" if mode == "html" else "application/dns-message")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        httpd.socket = self.server_ctx.wrap_socket(httpd.socket, server_side=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return calls, httpd.server_address[1]

    def test_doh_post(self):
        calls, port = self.start_doh()
        url = f"https://dns.test:{port}/dns-query"
        up = dnsfwd.DohUpstream(url, ["127.0.0.1"], self.bootstrap(), self.client_ctx)
        data = up.exchange(dnsfwd.build_query("pool.ntp.org", 1), time.monotonic() + 3)
        self.assertEqual(dnsfwd.addresses(data, 1)[0], [ANSWER_IP])
        self.assertEqual(calls, [("/dns-query", "application/dns-message", "application/dns-message", None)])

    def test_doh_redirect_and_wrong_type_rejected(self):
        for mode in ("redirect", "html"):
            calls, port = self.start_doh(mode)
            up = dnsfwd.DohUpstream(f"https://dns.test:{port}/dns-query", ["127.0.0.1"], self.bootstrap(),
                                    self.client_ctx)
            with self.assertRaises(OSError):
                up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 3)
            self.assertEqual(len(calls), 1, mode)  # keiner Weiterleitung gefolgt

    def start_drip(self, phase):
        """TLS-Server, der Kopf oder Antwort Byte für Byte tröpfeln lässt (DNS-SEC-1)."""
        lsock = socket.socket()
        lsock.bind(("127.0.0.1", 0))
        lsock.listen(4)
        stop = threading.Event()
        self.addCleanup(stop.set)
        self.addCleanup(lsock.close)

        def serve(conn):
            tls = None
            try:
                tls = self.server_ctx.wrap_socket(conn, server_side=True)
                tls.recv(65535)
                head = (b"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\n"
                        b"Content-Length: 60000\r\n\r\n")
                if phase == "body":
                    tls.sendall(head)
                    head = b"x" * 60000
                for byte in head:
                    if stop.wait(0.2):
                        break
                    tls.sendall(bytes([byte]))
            except (OSError, ssl.SSLError):
                pass
            finally:
                (tls or conn).close()

        def loop():
            while True:
                try:
                    conn, _ = lsock.accept()
                except OSError:
                    return
                threading.Thread(target=serve, args=(conn,), daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()
        return lsock.getsockname()[1]

    def test_doh_slow_drip_respects_deadline(self):
        for phase in ("head", "body"):
            port = self.start_drip(phase)
            up = dnsfwd.DohUpstream(f"https://dns.test:{port}/dns-query", ["127.0.0.1"], self.bootstrap(),
                                    self.client_ctx)
            started = time.monotonic()
            with self.assertRaises(OSError, msg=phase):
                up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 1.0)
            self.assertLess(time.monotonic() - started, 2.0, phase)

    def test_doh_label_hides_path(self):
        self.assertEqual(dnsfwd.doh_label("https://dns.nextdns.io/abc123"), "https://dns.nextdns.io/…")
        self.assertEqual(dnsfwd.doh_label("https://dns.quad9.net/dns-query"), "https://dns.quad9.net/dns-query")


class ForwarderTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.gate = dnsfwd.EventGate(lambda level, title, data: self.events.append((level, title, data)))

    def dead_port(self):
        return free_port()  # nichts lauscht – ICMP „Port unerreichbar“ bzw. Zeitüberschreitung

    def test_failover_to_second_upstream(self):
        fake = FakeDns()
        self.addCleanup(fake.close)
        dead = dnsfwd.PlainUpstream("127.0.0.1", self.dead_port())
        good = dnsfwd.PlainUpstream("127.0.0.1", fake.port)
        fwd = dnsfwd.Forwarder("servers", [dead, good], use_fallback=False, on_change=self.gate)
        query = dnsfwd.build_query("pool.ntp.org", 1)
        reply = fwd.resolve(query)
        self.assertEqual(reply[:2], query[:2])
        self.assertEqual(dnsfwd.addresses(reply, 1)[0], [ANSWER_IP])
        self.assertEqual((dead.fail, good.ok), (1, 1))
        self.assertGreater(dead.down_until, time.time())
        self.assertEqual(fwd.state, "ok")
        self.assertEqual(self.events, [])  # „ok“ direkt nach dem Start ist kein Ereignis
        # Zweite Anfrage (anderer Name): ausgefallener Server wird übersprungen
        fwd.resolve(dnsfwd.build_query("time.example", 1))
        self.assertEqual(dead.fail, 1)

    def test_fallback_event_and_recovery(self):
        system = FakeDns(ip="198.51.100.7")
        self.addCleanup(system.close)
        dead = dnsfwd.PlainUpstream("127.0.0.1", self.dead_port())
        fwd = dnsfwd.Forwarder("servers", [dead], lambda: [("127.0.0.1", system.port)], on_change=self.gate)
        reply = fwd.resolve(dnsfwd.build_query("pool.ntp.org", 1))
        self.assertEqual(dnsfwd.addresses(reply, 1)[0], ["198.51.100.7"])
        self.assertEqual(fwd.state, "fallback")
        self.assertEqual(fwd.stats["fallback"], 1)
        self.assertEqual(self.events[0][0], "warn")
        self.assertIn("Rückfall", self.events[0][1])
        # Upstream wieder da → Ereignis „wieder erreichbar“
        fake = FakeDns()
        self.addCleanup(fake.close)
        dead.port = fake.port
        dead.down_until = 0
        fwd.resolve(dnsfwd.build_query("other.example", 1))
        self.assertEqual(fwd.state, "ok")
        self.assertEqual(self.events[-1][0], "info")

    def test_all_fail_servfail_and_crit_event(self):
        dead = dnsfwd.PlainUpstream("127.0.0.1", self.dead_port())
        fwd = dnsfwd.Forwarder("servers", [dead], lambda: [], on_change=self.gate)
        query = dnsfwd.build_query("pool.ntp.org", 1)
        reply = fwd.resolve(query)
        self.assertEqual(struct.unpack("!H", reply[2:4])[0] & 0xF, dnsfwd.RCODE_SERVFAIL)
        self.assertEqual(fwd.state, "failing")
        self.assertEqual(self.events[-1][0], "crit")

    def test_event_rate_limit(self):
        clock = [1000.0]
        gate = dnsfwd.EventGate(lambda *a: self.events.append(a), clock=lambda: clock[0])
        for _ in range(3):
            gate("ok", "fallback", {})
            gate("fallback", "ok", {})
        self.assertEqual(len(self.events), 2)
        clock[0] += dnsfwd.EVENT_REPEAT + 1
        gate("ok", "fallback", {})
        self.assertEqual(len(self.events), 3)

    def test_cache(self):
        fake = FakeDns(ttl=60)
        self.addCleanup(fake.close)
        fwd = dnsfwd.Forwarder("servers", [dnsfwd.PlainUpstream("127.0.0.1", fake.port)], use_fallback=False)
        q1 = dnsfwd.build_query("pool.ntp.org", 1)
        q2 = dnsfwd.with_id(q1, 4711)
        fwd.resolve(q1)
        reply = fwd.resolve(q2)
        self.assertEqual(fake.udp_count, 1)
        self.assertEqual(struct.unpack("!H", reply[:2])[0], 4711)
        self.assertEqual(fwd.stats["cache_hits"], 1)
        self.assertLessEqual(dnsfwd.records(reply)[0]["ttl"], 60)

    def test_loop_guard(self):
        fwd = dnsfwd.Forwarder("servers", [], use_fallback=True)
        query = dnsfwd.build_query("pool.ntp.org", 1)
        ident, key = struct.unpack("!H", query[:2])[0], dnsfwd.question(query)
        fwd.inflight.track(ident, key)  # genau diese Anfrage hat der Weiterleiter selbst gestellt
        reply = fwd.resolve(query)
        self.assertEqual(struct.unpack("!H", reply[2:4])[0] & 0xF, dnsfwd.RCODE_SERVFAIL)
        self.assertEqual(fwd.stats["loops"], 1)
        self.assertIsNotNone(fwd.stats["loop_last"])
        fwd.inflight.untrack(ident, key)
        self.assertFalse(fwd.inflight.is_loop(ident, key))

    def test_concurrent_same_question_is_no_loop(self):
        """DNS-2: zwei gleiche Anfragen gleichzeitig im Rückfall – beide bekommen die Antwort,
        die Frage geht nur einmal hinaus, und es gibt keinen Schleifenalarm."""
        system = FakeDns(ip="198.51.100.7", delay={"same": 0.3})
        self.addCleanup(system.close)
        dead = dnsfwd.PlainUpstream("127.0.0.1", self.dead_port())
        dead.down_until = time.time() + 60
        fwd = dnsfwd.Forwarder("servers", [dead], lambda: [("127.0.0.1", system.port)])
        query = dnsfwd.build_query("same.example", 1)
        results = []
        threads = [threading.Thread(target=lambda q=q: results.append(fwd.resolve(q)))
                   for q in (query, dnsfwd.with_id(query, 4711))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(len(results), 2)
        for reply in results:
            self.assertEqual(dnsfwd.rcode_of(reply), 0)
            self.assertEqual(dnsfwd.addresses(reply, 1)[0], ["198.51.100.7"])
        self.assertEqual(sorted(struct.unpack("!H", r[:2])[0] for r in results),
                         sorted([struct.unpack("!H", query[:2])[0], 4711]))
        self.assertEqual(fwd.stats["loops"], 0)
        self.assertEqual(fwd.stats["coalesced"], 1)
        self.assertEqual(system.udp_count, 1)

    def test_bootstrap_name_query_is_no_loop(self):
        """DNS-2: Fragt ein Client nach dem DoT-Namen, während der Bootstrap ihn auflöst, ist das
        keine Schleife (andere ID)."""
        fwd = dnsfwd.Forwarder("servers", [], use_fallback=False)
        boot_query = dnsfwd.build_query("dns.quad9.net", 1)
        fwd.inflight.track(struct.unpack("!H", boot_query[:2])[0], dnsfwd.question(boot_query))
        client = dnsfwd.with_id(boot_query, (struct.unpack("!H", boot_query[:2])[0] + 1) & 0xFFFF)
        fwd.resolve(client)
        self.assertEqual(fwd.stats["loops"], 0)

    def test_self_loop_via_upstream_ends_at_once(self):
        """DNS-SEC-2: zeigt ein Upstream auf den Weiterleiter selbst, endet die Anfrage nach einem
        Umlauf mit SERVFAIL statt alle Worker zu belegen."""
        port = free_port()
        fwd = dnsfwd.Forwarder("servers", [dnsfwd.PlainUpstream("127.0.0.1", port)], use_fallback=False)
        server = dnsfwd.Server(fwd, port, hosts=("127.0.0.1",))
        server.start()
        self.addCleanup(server.stop)
        started = time.monotonic()
        reply = ask_udp(port, dnsfwd.build_query("pool.ntp.org", 1))
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(dnsfwd.rcode_of(reply), dnsfwd.RCODE_SERVFAIL)
        self.assertEqual(fwd.stats["queries"], 2)
        self.assertEqual(fwd.stats["loops"], 1)

    def test_one_slow_name_does_not_take_upstream_down(self):
        """DNS-3: eine Zeitüberschreitung bei einem Namen ist kein Ausfall des Servers."""
        fake = FakeDns(delay={"slow": 3})
        system = FakeDns(ip="198.51.100.7")
        self.addCleanup(fake.close)
        self.addCleanup(system.close)
        up = dnsfwd.PlainUpstream("127.0.0.1", fake.port)
        fwd = dnsfwd.Forwarder("servers", [up], lambda: [("127.0.0.1", system.port)], on_change=self.gate)
        self.assertEqual(dnsfwd.addresses(fwd.resolve(dnsfwd.build_query("fast1.example", 1)), 1)[0], [ANSWER_IP])
        slow = fwd.resolve(dnsfwd.build_query("slow.example", 1))
        self.assertEqual(dnsfwd.addresses(slow, 1)[0], ["198.51.100.7"])  # nur diese Anfrage im Rückfall
        self.assertEqual((up.streak, up.down_until), (1, 0.0))
        self.assertEqual(fwd.state, "ok")
        self.assertEqual(self.events, [])
        fast2 = fwd.resolve(dnsfwd.build_query("fast2.example", 1))
        self.assertEqual(dnsfwd.addresses(fast2, 1)[0], [ANSWER_IP])
        self.assertEqual(up.streak, 0)

    def test_repeated_timeouts_take_upstream_down(self):
        silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        silent.bind(("127.0.0.1", 0))
        self.addCleanup(silent.close)
        up = dnsfwd.PlainUpstream("127.0.0.1", silent.getsockname()[1])
        fwd = dnsfwd.Forwarder("servers", [up], use_fallback=False, on_change=self.gate)
        with mock.patch.object(dnsfwd, "UPSTREAM_TIMEOUT", 0.3):
            for i in range(dnsfwd.DOWN_AFTER):
                self.assertEqual(up.down_until, 0.0)
                fwd.resolve(dnsfwd.build_query(f"n{i}.example", 1))
        self.assertGreater(up.down_until, time.time())
        self.assertEqual(fwd.state, "failing")

    def test_system_servfail_is_no_fallback_answer(self):
        """DNS-4: SERVFAIL/REFUSED vom System-DNS → nächster System-Server; sonst „failing“."""
        broken = FakeDns(rcode=dnsfwd.RCODE_SERVFAIL)
        refused = FakeDns(rcode=dnsfwd.RCODE_REFUSED)
        good = FakeDns(ip="198.51.100.7")
        for f in (broken, refused, good):
            self.addCleanup(f.close)
        dead = dnsfwd.PlainUpstream("127.0.0.1", self.dead_port())
        system = [("127.0.0.1", broken.port), ("127.0.0.1", refused.port), ("127.0.0.1", good.port)]
        fwd = dnsfwd.Forwarder("servers", [dead], lambda: system, on_change=self.gate)
        reply = fwd.resolve(dnsfwd.build_query("pool.ntp.org", 1))
        self.assertEqual(dnsfwd.addresses(reply, 1)[0], ["198.51.100.7"])
        self.assertEqual(fwd.state, "fallback")
        # Nur kaputte System-Server: keine „Rückfall“-Antwort, sondern „failing“
        dead2 = dnsfwd.PlainUpstream("127.0.0.1", self.dead_port())
        fwd = dnsfwd.Forwarder("servers", [dead2], lambda: system[:2], on_change=self.gate)
        reply = fwd.resolve(dnsfwd.build_query("pool.ntp.org", 1))
        self.assertEqual(dnsfwd.rcode_of(reply), dnsfwd.RCODE_SERVFAIL)
        self.assertEqual(fwd.state, "failing")
        self.assertEqual((fwd.stats["fallback"], fwd.stats["answered"]), (0, 0))

    def test_upstream_refused_tries_next(self):
        refused = FakeDns(rcode=dnsfwd.RCODE_REFUSED)
        good = FakeDns()
        self.addCleanup(refused.close)
        self.addCleanup(good.close)
        a, b = dnsfwd.PlainUpstream("127.0.0.1", refused.port), dnsfwd.PlainUpstream("127.0.0.1", good.port)
        fwd = dnsfwd.Forwarder("servers", [a, b], use_fallback=False)
        self.assertEqual(dnsfwd.addresses(fwd.resolve(dnsfwd.build_query("x.example", 1)), 1)[0], [ANSWER_IP])
        self.assertEqual((a.fail, b.ok), (1, 1))

    def test_fallback_answers_cached_briefly(self):
        """DNS-SEC-3: Antworten aus dem Rückfall höchstens FALLBACK_CACHE_TTL Sekunden im Cache."""
        system = FakeDns(ip="198.51.100.7", ttl=3600)
        self.addCleanup(system.close)
        dead = dnsfwd.PlainUpstream("127.0.0.1", self.dead_port())
        fwd = dnsfwd.Forwarder("servers", [dead], lambda: [("127.0.0.1", system.port)])
        query = dnsfwd.build_query("pool.ntp.org", 1)
        fwd.resolve(query)
        expires, stored, _data = fwd._cache[query[2:]]
        self.assertLessEqual(expires - stored, dnsfwd.FALLBACK_CACHE_TTL)

    def test_rejects_non_queries(self):
        fwd = dnsfwd.Forwarder("servers", [], use_fallback=False)
        query = dnsfwd.build_query("a.example", 1)
        self.assertIsNone(fwd.resolve(b"kein dns"))
        self.assertIsNone(fwd.resolve(make_answer(query)))       # Antwort statt Frage
        notify = query[:2] + b"\x20\x00" + query[4:]               # Opcode 4 (NOTIFY)
        self.assertEqual(struct.unpack("!H", fwd.resolve(notify)[2:4])[0] & 0xF, dnsfwd.RCODE_NOTIMP)


class ServerTest(unittest.TestCase):
    def start(self, big=False):
        fake = FakeDns(big=big)
        self.addCleanup(fake.close)
        fwd = dnsfwd.Forwarder("servers", [dnsfwd.PlainUpstream("127.0.0.1", fake.port)], use_fallback=False)
        port = free_port()
        server = dnsfwd.Server(fwd, port, hosts=("127.0.0.1",))
        self.assertEqual(server.start(), ["127.0.0.1"])
        self.addCleanup(server.stop)
        return port, fake

    def test_udp_and_tcp(self):
        port, _fake = self.start()
        query = dnsfwd.build_query("pool.ntp.org", 1)
        self.assertEqual(dnsfwd.addresses(ask_udp(port, query), 1)[0], [ANSWER_IP])
        with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
            conn.sendall(struct.pack("!H", len(query)) + query)
            (n,) = struct.unpack("!H", dnsfwd._recv_exact(conn, 2, time.monotonic() + 5))
            reply = dnsfwd._recv_exact(conn, n, time.monotonic() + 5)
        self.assertEqual(dnsfwd.addresses(reply, 1)[0], [ANSWER_IP])

    def test_large_answer_truncated_over_udp(self):
        port, fake = self.start(big=True)
        fake.tc = False
        query = dnsfwd.build_query("big.example", 1)
        reply = ask_udp(port, query)
        self.assertTrue(struct.unpack("!H", reply[2:4])[0] & dnsfwd.FLAG_TC)
        self.assertLessEqual(len(reply), 512)

    def test_loopback_only(self):
        self.assertTrue(dnsfwd.is_loopback("127.0.0.1"))
        self.assertTrue(dnsfwd.is_loopback("::1"))
        self.assertTrue(dnsfwd.is_loopback("::ffff:127.0.0.1"))
        for addr in ("192.168.1.10", "10.0.0.1", "fe80::1%eth0", "", "x"):
            self.assertFalse(dnsfwd.is_loopback(addr), addr)
        self.assertEqual(dnsfwd.LISTEN_HOSTS, ("127.0.0.1", "::1"))


class ResolvTest(unittest.TestCase):
    ORIGINAL = "# Docker\nsearch lan\nnameserver 127.0.0.11\nnameserver 192.168.1.2\noptions ndots:0\n"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.resolv = self.tmp / "resolv.conf"
        self.backup = self.tmp / "data" / "resolv.conf.system"
        self.resolv.write_text(self.ORIGINAL)

    def test_point_and_restore(self):
        result = dnsfwd.point_local(str(self.resolv), str(self.backup))
        self.assertEqual(result, {"state": "local", "message": ""})
        text = self.resolv.read_text()
        self.assertIn(dnsfwd.MARKER, text)
        self.assertIn("nameserver 127.0.0.1", text)
        self.assertNotIn("127.0.0.11", text)
        self.assertIn("search lan", text)
        self.assertEqual(self.backup.read_text(), self.ORIGINAL)
        self.assertEqual(oct(self.backup.stat().st_mode & 0o777), "0o600")
        # Rückfall-Server kommen aus der Sicherung
        self.assertEqual(dnsfwd.system_servers(str(self.resolv), str(self.backup)),
                         [("127.0.0.11", 53), ("192.168.1.2", 53)])
        # Zweites Umstellen (Neustart) überschreibt die Sicherung nicht mit der eigenen Datei
        dnsfwd.point_local(str(self.resolv), str(self.backup))
        self.assertEqual(self.backup.read_text(), self.ORIGINAL)
        self.assertEqual(dnsfwd.restore_system(str(self.resolv), str(self.backup))["state"], "system")
        self.assertEqual(self.resolv.read_text(), self.ORIGINAL)
        self.assertFalse(self.backup.exists())
        # Nicht von uns: nichts anfassen
        self.assertEqual(dnsfwd.restore_system(str(self.resolv), str(self.backup))["state"], "system")
        self.assertEqual(self.resolv.read_text(), self.ORIGINAL)

    def test_readonly(self):
        with mock.patch.object(dnsfwd, "_write_in_place", side_effect=OSError(errno.EROFS, "Read-only file system")):
            result = dnsfwd.point_local(str(self.resolv), str(self.backup))
        self.assertEqual(result["state"], "readonly")
        self.assertEqual(self.resolv.read_text(), self.ORIGINAL)

    def test_missing_backup(self):
        self.resolv.write_text(dnsfwd.render_local(self.ORIGINAL))
        self.assertEqual(dnsfwd.restore_system(str(self.resolv), str(self.backup))["state"], "error")
        self.assertEqual(dnsfwd.system_servers(str(self.resolv), str(self.backup)), [])

    def test_own_address_never_fallback(self):
        self.assertEqual(dnsfwd.nameservers("nameserver 127.0.0.1\nnameserver ::1\nnameserver 9.9.9.9\n"),
                         [("9.9.9.9", 53)])


class BootstrapLoopbackTest(unittest.TestCase):
    """DNS-1: Mit „dns: 127.0.0.1“ enthält die gesicherte resolv.conf nur den Weiterleiter selbst."""

    def test_backup_only_self(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        resolv, backup = tmp / "resolv.conf", tmp / "resolv.conf.system"
        resolv.write_text("nameserver 127.0.0.1\n")
        self.assertEqual(dnsfwd.point_local(str(resolv), str(backup))["state"], "local")
        self.assertEqual(backup.read_text(), "nameserver 127.0.0.1\n")
        self.assertEqual(dnsfwd.system_servers(str(resolv), str(backup)), [])
        boot = dnsfwd.Bootstrap(lambda: dnsfwd.system_servers(str(resolv), str(backup)))
        up = dnsfwd.DotUpstream("dns.quad9.net", "dns.quad9.net", 853, [], boot, None)
        with self.assertRaises(dnsfwd.BootstrapError) as ctx:
            up.exchange(dnsfwd.build_query("pool.ntp.org", 1), time.monotonic() + 1)
        self.assertIn("Feste Adressen", str(ctx.exception))
        self.assertTrue(dnsfwd.hard_failure(ctx.exception))
        info = up.public()
        self.assertEqual((info["host"], info["pinned"], info["bootstrap_failed"]), ("dns.quad9.net", False, True))
        # Über den Forwarder: Ausfall sofort erkannt, Hinweis auf feste Adressen
        fwd = dnsfwd.Forwarder("dot", [up], lambda: dnsfwd.system_servers(str(resolv), str(backup)))
        reply = fwd.resolve(dnsfwd.build_query("pool.ntp.org", 1))
        self.assertEqual(dnsfwd.rcode_of(reply), dnsfwd.RCODE_SERVFAIL)
        status = dict(fwd.public(), mode="dot", effective_mode="dot", time=time.time())
        self.assertEqual(status["state"], "failing")
        self.assertIn("dns_pin_needed", [i["key"] for i in insights.dns_insights(status, {})])
        # Mit fester Adresse braucht es keinen System-DNS
        pinned = dnsfwd.DotUpstream("dns.quad9.net", "dns.quad9.net", 853, ["9.9.9.9"], boot, None)
        self.assertEqual(pinned.targets(time.monotonic() + 1), ["9.9.9.9"])
        self.assertTrue(pinned.public()["pinned"])


class SettingsTest(unittest.TestCase):
    def test_valid(self):
        clean = settings.validate({
            "dns_mode": "dot", "dns_servers": "9.9.9.9, [2620:fe::fe]:5353\n1.1.1.1:53",
            "dns_dot": "dns.quad9.net one.one.one.one:853 1.1.1.1", "dns_doh": "https://dns.quad9.net/dns-query{?dns}",
            "dns_pin": ["dns.quad9.net=9.9.9.9"], "dns_fallback": "nein"})
        self.assertEqual(clean["dns_servers"], ["9.9.9.9", "[2620:fe::fe]:5353", "1.1.1.1"])
        self.assertEqual(clean["dns_dot"], ["dns.quad9.net", "one.one.one.one", "1.1.1.1"])
        self.assertEqual(clean["dns_doh"], ["https://dns.quad9.net/dns-query"])
        self.assertFalse(clean["dns_fallback"])
        # IPv4-gemappte Adressen werden zu IPv4; Loopback mit anderem Port bleibt erlaubt
        self.assertEqual(settings.validate({"dns_servers": "::ffff:9.9.9.9 127.0.0.1:5353"})["dns_servers"],
                         ["9.9.9.9", "127.0.0.1:5353"])

    def test_invalid(self):
        for key, value in (("dns_mode", "dnscrypt"), ("dns_servers", "127.0.0.1"), ("dns_servers", "dns.google"),
                           ("dns_servers", "9.9.9.9:99999"), ("dns_servers", "224.0.0.1"),
                           ("dns_dot", "evil\nhost"), ("dns_dot", "-x.example"), ("dns_doh", "http://dns.example/q"),
                           ("dns_doh", "https://user:pw@dns.example/q"), ("dns_doh", "https://dns.example/q x"),
                           ("dns_pin", "dns.quad9.net"), ("dns_pin", "dns.quad9.net=127.0.0.1"),
                           # DNS-SEC-2: jede Loopback-Adresse auf Port 53, auch IPv4-gemappt
                           ("dns_servers", "::ffff:127.0.0.1"), ("dns_servers", "[::ffff:127.0.0.1]:53"),
                           ("dns_servers", "127.0.0.53"), ("dns_servers", "[::1]:53"),
                           ("dns_servers", " ".join(f"9.9.9.{i}" for i in range(9)))):
            with self.assertRaises(settings.ValidationError, msg=f"{key}={value!r}"):
                settings.validate({key: value})

    def test_defaults_and_effective_mode(self):
        self.assertEqual(settings.FIELDS["dns_mode"]["default"], "system")
        for key in ("dns_mode", "dns_servers", "dns_dot", "dns_doh", "dns_pin", "dns_fallback"):
            self.assertTrue(settings.FIELDS[key]["help"], key)
            self.assertTrue(settings.FIELDS[key]["env"], key)
        self.assertEqual(dnsfwd.effective_mode({"dns_mode": "servers", "dns_servers": []}), "system")
        self.assertTrue(dnsfwd.config_warnings({"dns_mode": "dot", "dns_dot": []}))
        self.assertEqual(dnsfwd.effective_mode({"dns_mode": "doh", "dns_doh": ["https://x.example/q"]}), "doh")

    def test_env(self):
        cfg = settings.values({"DNS_MODE": "servers", "DNS_SERVERS": "9.9.9.9,149.112.112.112"})
        self.assertEqual(cfg["dns_mode"], "servers")
        self.assertEqual(cfg["dns_servers"], ["9.9.9.9", "149.112.112.112"])

    def test_build_upstreams(self):
        boot = dnsfwd.Bootstrap(lambda: [])
        cfg = {"dns_mode": "dot", "dns_dot": ["dns.quad9.net", "one.one.one.one:8853"],
               "dns_pin": ["dns.quad9.net=9.9.9.9"]}
        ups = dnsfwd.build_upstreams(cfg, boot)
        self.assertEqual([(u.proto, u.label, u.port, u.pins) for u in ups],
                         [("dot", "dns.quad9.net", 853, ["9.9.9.9"]), ("dot", "one.one.one.one:8853", 8853, [])])
        ups = dnsfwd.build_upstreams({"dns_mode": "servers", "dns_servers": ["[2620:fe::fe]:5353", "9.9.9.9"]}, boot)
        self.assertEqual([(u.ip, u.port) for u in ups], [("2620:fe::fe", 5353), ("9.9.9.9", 53)])


class StatusTest(unittest.TestCase):
    def test_api_status(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.assertEqual(dnsfwd.api_status({"dns_mode": "system"}, tmp)["state"], "system")
        cfg = {"dns_mode": "dot", "dns_dot": ["dns.quad9.net"]}
        self.assertEqual(dnsfwd.api_status(cfg, tmp)["state"], "down")
        dnsfwd.write_json(dnsfwd.status_path(tmp), {"pid": os.getpid(), "state": "fallback",
                                                     "upstreams": [], "resolv": {"state": "local"}})
        status = dnsfwd.api_status(cfg, tmp)
        self.assertTrue(status["running"])
        self.assertEqual(status["state"], "fallback")
        self.assertEqual(status["effective_label"], "DNS-over-TLS")

    def test_event_line(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        dnsfwd.emit_event("warn", "Titel", {"a": 1}, tmp)
        line = json.loads(Path(tmp, "events.jsonl").read_text())
        self.assertEqual((line["kind"], line["level"], line["title"]), ("dns", "warn", "Titel"))
        import events
        self.assertIn("dns", events.KINDS)


class DiagnosticsTest(unittest.TestCase):
    def test_doh_path_not_in_bundle(self):
        import diagnostics
        out = diagnostics._collect_settings({"dns_doh": ["https://dns.nextdns.io/abc123"], "dns_mode": "doh"}, {})
        self.assertEqual(out["values"]["dns_doh"], ["https://dns.nextdns.io/…"])


class InsightsTest(unittest.TestCase):
    def keys(self, items):
        return [i["key"] for i in items]

    def test_loop_with_system_dns(self):
        sources = [{"mode": "^", "name": "192.168.1.5", "hostname": "pool.ntp.org"},
                   {"mode": "^", "name": "192.0.2.1", "hostname": "ptbtime1.ptb.de"}]
        out = insights.dns_insights({"mode": "system"}, {"dns_mode": "system"}, sources, ["192.168.1.5"])
        self.assertEqual(self.keys(out), ["dns_loop"])
        self.assertEqual(out[0]["level"], "warn")
        self.assertIn("pool.ntp.org", out[0]["text"])
        self.assertIn("DNS für ntp-gui", out[0]["text"])
        # Aus der Prüfung „Zeitserver erzwingen“
        out = insights.dns_insights({"mode": "system"}, {}, [], [], [{"host": "de.pool.ntp.org"}])
        self.assertIn("de.pool.ntp.org", out[0]["text"])
        # Mit eigenem DNS-Modus keine Schleifenwarnung
        out = insights.dns_insights({"mode": "dot", "effective_mode": "dot", "state": "ok"}, {}, sources, ["192.168.1.5"])
        self.assertEqual(out, [])

    def test_loop_risk_only_when_enforce_used(self):
        cfg = {"dns_mode": "system", "ntp_sources": [{"host": "de.pool.ntp.org"}, {"host": "ptbtime1.ptb.de"}]}
        self.assertEqual(insights.dns_insights({"mode": "system"}, cfg), [])
        out = insights.dns_insights({"mode": "system"}, cfg, enforce_used=True)
        self.assertEqual(self.keys(out), ["dns_loop_risk"])
        self.assertIn("de.pool.ntp.org", out[0]["text"])
        self.assertNotIn("ptbtime1", out[0]["text"])

    def test_forwarder_states(self):
        base = {"mode": "dot", "effective_mode": "dot"}
        self.assertEqual(self.keys(insights.dns_insights(dict(base, state="fallback"), {})), ["dns_fallback"])
        self.assertEqual(self.keys(insights.dns_insights(dict(base, state="failing"), {})), ["dns_failing"])
        self.assertEqual(self.keys(insights.dns_insights(dict(base, resolv={"state": "readonly"}), {})),
                         ["dns_resolv_readonly"])
        self.assertIn("dns: 127.0.0.1", insights.dns_insights(dict(base, resolv={"state": "readonly"}), {})[0]["text"])
        self.assertEqual(self.keys(insights.dns_insights({"mode": "dot", "effective_mode": "system"}, {})),
                         ["dns_no_servers"])
        now = time.time()
        self.assertEqual(self.keys(insights.dns_insights(
            dict(base, state="ok", time=now, stats={"loops": 2, "loop_last": now - 60}), {})), ["dns_loop_fallback"])
        # DNS-2: eine alte Schleife (Zähler seit Start) warnt nicht dauerhaft
        self.assertEqual(insights.dns_insights(
            dict(base, state="ok", time=now, stats={"loops": 2, "loop_last": now - 3600}), {}), [])
        self.assertEqual(insights.dns_insights(dict(base, state="ok", stats={"loops": 2}), {}), [])

    def test_pin_needed(self):
        """DNS-1: DoT/DoH-Name ohne feste Adresse, den der System-DNS nicht liefert."""
        base = {"mode": "dot", "effective_mode": "dot", "state": "failing", "fallback_servers": []}
        ups = [{"label": "dns.quad9.net", "host": "dns.quad9.net", "pinned": False, "bootstrap_failed": True}]
        out = insights.dns_insights(dict(base, upstreams=ups), {})
        self.assertEqual(self.keys(out), ["dns_pin_needed", "dns_failing"])
        self.assertIn("dns.quad9.net=9.9.9.9", out[0]["text"])
        self.assertIn("Feste Adressen", out[0]["text"])
        pinned = [dict(ups[0], pinned=True, bootstrap_failed=False)]
        self.assertNotIn("dns_pin_needed", self.keys(insights.dns_insights(dict(base, upstreams=pinned), {})))
        # Schleife über Docker-DNS (Backup 127.0.0.11) bei ungepinntem Namen
        now = time.time()
        looped = dict(base, state="fallback", time=now, stats={"loops": 3, "loop_last": now},
                      upstreams=[dict(ups[0], bootstrap_failed=False)])
        self.assertIn("dns_pin_needed", self.keys(insights.dns_insights(looped, {})))
        # Readonly-Hinweis nennt die festen Adressen
        text = insights.dns_insights(dict(base, state="ok", resolv={"state": "readonly"}), {})[0]["text"]
        self.assertIn("Feste Adressen", text)


class EnforceTest(unittest.TestCase):
    def test_rewritten_sources(self):
        self.assertEqual(enforce.rewritten_sources(["de.pool.ntp.org", "ptbtime1.ptb.de", "time.windows.com",
                                                    "cam.example.com"], ["cam.example.com"]),
                         ["de.pool.ntp.org", "time.windows.com", "cam.example.com"])

    def test_dns_redirect_snippets(self):
        result = enforce.snippets("all", "192.168.1.5", [], 123, "192.168.1.2")
        nat = [s for s in result["snippets"] if s["kind"] == "nat"]
        self.assertEqual({s["id"] for s in nat}, {"unifi", "opnsense", "mikrotik", "openwrt", "nftables"})
        for item in nat:
            block = item["blocks"][-1]
            self.assertIn("DNS-Umleitung", block["title"])
            self.assertIn("53", block["code"])
            self.assertIn("192.168.1.5", block["code"], item["id"])  # Ausnahme für ntp-gui
            self.assertIn("192.168.1.2", block["code"], item["id"])
            notes = " ".join(item["notes"])
            self.assertIn("Pflicht", notes)
            self.assertIn("DNS-over-TLS", notes)
        for item in result["snippets"]:
            if item["kind"] == "dns":
                self.assertFalse(any("DNS-Umleitung per Firewall" in b["title"] for b in item["blocks"]))
        # ohne Adressen: Platzhalter, keine erfundenen Adressen
        result = enforce.snippets("nftables", None, [], 123, "kaputt; rm -rf /")
        code = result["snippets"][0]["blocks"][-1]["code"]
        self.assertIn(enforce.DNS_PLACEHOLDER, code)
        self.assertIn(enforce.IP_PLACEHOLDER, code)
        self.assertNotIn("rm -rf", code)


class ServeTest(unittest.TestCase):
    """serve() als Ganzes: lauscht, beantwortet, schreibt Status – ohne resolv.conf (hoher Port)."""

    def test_serve_end_to_end(self):
        fake = FakeDns()
        self.addCleanup(fake.close)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        port = free_port()
        cfg = {"dns_mode": "servers", "dns_servers": [f"127.0.0.1:{fake.port}"], "dns_fallback": False}
        stop = threading.Event()
        thread = threading.Thread(target=dnsfwd.serve, kwargs={"cfg": cfg, "port": port, "run_dir": tmp,
                                                               "resolv": os.path.join(tmp, "resolv.conf"),
                                                               "stop": stop}, daemon=True)
        thread.start()
        for _ in range(50):
            if os.path.exists(os.path.join(tmp, dnsfwd.READY_NAME)):
                break
            time.sleep(0.05)
        reply = ask_udp(port, dnsfwd.build_query("pool.ntp.org", 1))
        self.assertEqual(dnsfwd.addresses(reply, 1)[0], [ANSWER_IP])
        status = dnsfwd.read_status(tmp)
        self.assertEqual(status["listening"][0], "127.0.0.1")
        self.assertFalse(os.path.exists(os.path.join(tmp, "resolv.conf")))  # hoher Port: resolv.conf bleibt
        stop.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(dnsfwd.read_status(tmp)["state"], "stopped")


if __name__ == "__main__":
    unittest.main()
