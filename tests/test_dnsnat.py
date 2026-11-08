"""DNS- und NAT-Härtung (1.5, Thema 10): Upstream-Kette im Selbsttest, Resolver-Zustand,
Ereignisse je eigenem DNS-Server, Anleitungen und Verdrahtung von /api/loops."""

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import dnsfwd  # noqa: E402
import enforce  # noqa: E402
import insights  # noqa: E402
import test_dnsfwd as dnsfx  # noqa: E402 – FakeDns, refusing_udp_port (nur Hilfen, Modul-Import)

IP = "192.168.1.40"
OURS = {"stratum": 2, "ref_id": "C0356768", "ref_label": "C0356768", "ref_time": 1_793_607_834.5,
        "root_delay": 0.02, "root_dispersion": 0.0006, "precision": -20, "leap": 0}
PTB = {"stratum": 1, "ref_id": "50544200", "ref_label": "PTB", "ref_time": 1_793_607_877.0,
       "root_delay": 0.0, "root_dispersion": 0.00001, "precision": -26, "leap": 0}


class ChainTest(unittest.TestCase):
    def setUp(self):
        enforce._reset_rate_limit()

    def run_check(self, dns, replies, sources, resolver_info=None):
        def resolver(hosts, timeout):
            return {h: dns.get(h, ["203.0.113.9"]) for h in hosts}

        def prober(targets, timeout):
            return {t: replies.get(t[0]) for t in targets}

        return enforce.check([IP], [], 123, None, enforce.source_hosts_from({"ntp_sources": sources}),
                             resolver=resolver, prober=prober, sources=sources,
                             resolver_info=resolver_info or enforce.resolver_label({"effective_mode": "system"}))

    def test_correct_setup(self):
        sources = [{"host": "ptbtime1.ptb.de", "nts": True}, {"host": "192.53.103.103"}]
        replies = {"127.0.0.1": OURS, "192.53.103.108": PTB, "192.53.103.103": PTB, "216.239.35.0": PTB,
                   "162.159.200.1": PTB}
        result = self.run_check({"ptbtime1.ptb.de": ["192.53.103.108"]}, replies, sources)
        rows = {r["host"]: r for r in result["upstream"]}
        self.assertEqual(rows["ptbtime1.ptb.de"]["state"], "foreign")
        self.assertEqual(rows["ptbtime1.ptb.de"]["resolver"], "System-DNS des Containers")
        self.assertEqual(rows["ptbtime1.ptb.de"]["address"], "192.53.103.108")
        self.assertTrue(rows["ptbtime1.ptb.de"]["nts"])
        self.assertEqual(rows["192.53.103.103"]["by"], "ip")
        self.assertIsNone(rows["192.53.103.103"]["resolver"])
        self.assertIn("PTB", rows["192.53.103.103"]["verdict"])
        self.assertEqual(result["loops"], [])
        self.assertNotEqual(result["level"], "crit")

    def test_dns_rewrite_and_nat_redirect(self):
        # R1: AdGuard schreibt pool.ntp.org um, UniFi leitet UDP 123 um – beides ohne Ausnahme.
        sources = [{"host": "de.pool.ntp.org"}, {"host": "ptbtime3.ptb.de"}, {"host": "192.53.103.104"}]
        replies = {"127.0.0.1": OURS, "192.53.103.103": dict(OURS), "192.53.103.104": dict(OURS),
                   "216.239.35.0": dict(OURS), "162.159.200.1": dict(OURS)}
        result = self.run_check({"de.pool.ntp.org": [IP], "ptbtime3.ptb.de": ["192.53.103.103"]}, replies, sources)
        rows = {r["host"]: r for r in result["upstream"]}
        self.assertEqual((rows["de.pool.ntp.org"]["state"], rows["de.pool.ntp.org"]["cause"]),
                         ("self_address", "dns"))
        self.assertIn("DNS-Umschreibung ohne Ausnahme", rows["de.pool.ntp.org"]["verdict"])
        self.assertEqual((rows["ptbtime3.ptb.de"]["state"], rows["ptbtime3.ptb.de"]["cause"]), ("self_reply", "nat"))
        self.assertIn("NAT-Umleitung ohne Ausnahme", rows["ptbtime3.ptb.de"]["verdict"])
        self.assertEqual(rows["192.53.103.104"]["cause"], "nat")
        self.assertEqual(result["level"], "crit")
        self.assertEqual({l["host"] for l in result["loops"]}, {"de.pool.ntp.org", "ptbtime3.ptb.de", "192.53.103.104"})

    def test_only_aaaa_rewritten_chain_agrees_with_loops(self):
        # Prüfbefund F5: AdGuard schreibt nur AAAA auf ntp-gui um, A bleibt echt. Kette und
        # Schleifen-Liste müssen dasselbe sagen.
        sources = [{"host": "ptbtime1.ptb.de", "nts": True}]
        replies = {"127.0.0.1": OURS, "192.53.103.108": PTB, "216.239.35.0": PTB, "162.159.200.1": PTB}

        def resolver(hosts, timeout):
            return {h: (["192.53.103.108", "fd00::5"] if h == "ptbtime1.ptb.de" else ["1.2.3.4"]) for h in hosts}

        result = enforce.check([IP, "fd00::5"], [], 123, None, ["ptbtime1.ptb.de"], force=True,
                               resolver=resolver, prober=lambda t, to: {x: replies.get(x[0]) for x in t},
                               sources=sources)
        row = result["upstream"][0]
        self.assertEqual((row["state"], row["cause"], row["level"]), ("self_address", "dns", "crit"))
        self.assertIn("IPv6-Antwort", row["verdict"])
        self.assertIn("IPv4-Antwort zeigt auf einen fremden Server", row["verdict"])
        self.assertEqual(result["level"], "crit")
        self.assertEqual([l["host"] for l in result["loops"]], ["ptbtime1.ptb.de"])

    def test_rewrite_to_host_ip_counts_as_dns(self):
        sources = [{"host": "pool.ntp.org"}]
        replies = {"127.0.0.1": OURS, "192.168.1.2": dict(OURS)}
        result = self.run_check({"pool.ntp.org": ["192.168.1.2"]}, replies, sources)
        row = result["upstream"][0]
        self.assertEqual((row["state"], row["cause"]), ("self_reply", "dns"))

    def test_dns_error_and_no_reply(self):
        sources = [{"host": "nts.example.net"}, {"host": "ptbtime2.ptb.de"}]
        result = self.run_check({"nts.example.net": "Name nicht auflösbar", "ptbtime2.ptb.de": ["192.53.103.104"]},
                                {"127.0.0.1": OURS}, sources)
        rows = {r["host"]: r for r in result["upstream"]}
        self.assertEqual(rows["nts.example.net"]["state"], "dns_error")
        self.assertEqual(rows["ptbtime2.ptb.de"]["state"], "no_reply")

    def test_invalid_entries_skipped(self):
        entries = enforce._chain_entries([{"host": "bad host"}, {"host": "[2001:db8::1]"}, "x",
                                          {"host": "Pool.NTP.org."}, {"host": "pool.ntp.org"}], [])
        self.assertEqual([(e["host"], e["by"]) for e in entries], [("2001:db8::1", "ip"), ("pool.ntp.org", "name")])

    def test_resolver_label(self):
        self.assertEqual(enforce.resolver_label(None)["mode"], "system")
        label = enforce.resolver_label({"effective_mode": "dot", "effective_label": "DNS-over-TLS",
                                        "state": "fallback", "upstreams": [{"label": "dns.quad9.net"},
                                                                           {"label": "one.one.one.one"}]})
        self.assertEqual(label["label"], "DNS-over-TLS: dns.quad9.net, one.one.one.one")
        self.assertIn("Rückfall", label["note"])


class SnippetTest(unittest.TestCase):
    def test_adguard_exception_and_cname_variant(self):
        snip = enforce.snippets("adguard", IP, [])["snippets"][0]
        codes = {b["title"]: b["code"] for b in snip["blocks"]}
        exception = next(c for t, c in codes.items() if t.startswith("Ausnahme"))
        self.assertIn(f"@@||pool.ntp.org^$dnsrewrite,client={IP}", exception)
        cname = next(c for t, c in codes.items() if "CNAME" in t)
        self.assertIn("||time.amazon.com^$dnsrewrite=time.lan", cname)
        self.assertIn(f"time.lan  →  {IP}", cname)
        notes = " ".join(snip["notes"])
        for word in ("Client-spezifische Regel", "NTS-Namen nie", "Privatem DNS", "IPv6"):
            self.assertIn(word, notes)
        # NTS-Namen stehen nie in den Umschreib-Regeln
        self.assertNotIn("time.cloudflare.com", cname + exception)

    def test_unifi_mentions_detection(self):
        snip = enforce.snippets("unifi", IP, [])["snippets"][0]
        notes = " ".join(snip["notes"])
        self.assertIn("NAT-Umleitung ohne Ausnahme", notes)
        self.assertIn(f"Quelle ≠ {IP}", snip["blocks"][0]["code"])


class UpstreamEventTest(unittest.TestCase):
    def test_down_and_up_events_per_server(self):
        events = []
        clock = [1000.0]
        gate = dnsfwd.UpstreamGate(lambda level, title, data: events.append((level, title, data)),
                                   clock=lambda: clock[0])
        up = dnsfwd.PlainUpstream("127.0.0.1", dnsfx.refusing_udp_port(self))
        fwd = dnsfwd.Forwarder("servers", [up], use_fallback=False, on_upstream=gate)
        fwd.resolve(dnsfwd.build_query("pool.ntp.org", 1))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "warn")
        self.assertIn(f"{up.label} nicht erreichbar", events[0][1])
        self.assertTrue(events[0][2]["error"])
        # gleicher Server fällt erneut aus: kein zweites Ereignis (schon gemeldet)
        up.down_until = 0
        fwd.resolve(dnsfwd.build_query("time.example", 1))
        self.assertEqual(len(events), 1)
        fake = dnsfx.FakeDns()
        self.addCleanup(fake.close)
        up.port = fake.port
        up.down_until = 0
        fwd.resolve(dnsfwd.build_query("other.example", 1))
        self.assertEqual(len(events), 1)  # im 5-min-Fenster: wartet, geht aber nicht verloren
        clock[0] += dnsfwd.EVENT_REPEAT
        gate.flush()
        self.assertEqual(events[-1][0], "info")
        self.assertIn("antwortet wieder", events[-1][1])

    def test_gate_rate_limit(self):
        clock = [0.0]
        events = []
        gate = dnsfwd.UpstreamGate(lambda *a: events.append(a), clock=lambda: clock[0])
        gate("a", "down", "x")
        gate("a", "down", "x")   # schon gemeldet
        gate("b", "down", "x")   # anderer Server: eigenes Fenster
        self.assertEqual(len(events), 2)
        clock[0] += 60
        gate("a", "up", "")      # im Fenster: wartet
        self.assertEqual(len(events), 2)
        self.assertEqual(gate.pending(), {"a": "up"})
        clock[0] += dnsfwd.EVENT_REPEAT
        gate.flush()
        self.assertEqual(len(events), 3)
        self.assertEqual((events[-1][0], events[-1][1]), ("info", "DNS für ntp-gui: a antwortet wieder"))
        self.assertEqual(gate.pending(), {})

    def test_gate_down_up_down_ends_down(self):
        # Prüfbefund F3: down → up → down innerhalb von 5 min darf nicht mit „antwortet wieder“ enden.
        clock = [1000.0]
        events = []
        gate = dnsfwd.UpstreamGate(lambda level, title, data: events.append((level, title)), clock=lambda: clock[0])
        gate("dns.quad9.net", "down", "refused")
        clock[0] += 60
        gate("dns.quad9.net", "up", "")
        clock[0] += 60
        gate("dns.quad9.net", "down", "refused")
        for _ in range(40):
            clock[0] += 60
            gate.flush()
        self.assertEqual(events, [("warn", "DNS für ntp-gui: dns.quad9.net nicht erreichbar")])

    def test_gate_suppressed_down_is_sent_later(self):
        # up → down im Fenster nach „antwortet wieder“: das zweite „nicht erreichbar“ kommt nach.
        clock = [1000.0]
        events = []
        gate = dnsfwd.UpstreamGate(lambda level, title, data: events.append((level, title)), clock=lambda: clock[0])
        gate("s", "down", "x")
        clock[0] += dnsfwd.EVENT_REPEAT
        gate("s", "up", "")
        clock[0] += 30
        gate("s", "down", "timeout")
        self.assertEqual(len(events), 2)
        clock[0] += dnsfwd.EVENT_REPEAT
        gate.flush()
        self.assertEqual([e[0] for e in events], ["warn", "info", "warn"])

    def test_forwarder_down_up_down_within_window(self):
        # wie repro4: echter Forwarder, Fake-Upstream, Uhr gesteuert
        class Fake(dnsfwd.Upstream):
            def __init__(self):
                super().__init__("dns.quad9.net")
                self.fail_now = False

            def exchange(self, query, deadline):
                if self.fail_now:
                    raise ConnectionRefusedError("refused")
                return bytes(query[:2]) + b"\x81\x80" + query[4:]

        clock = [1000.0]
        events = []
        gate = dnsfwd.UpstreamGate(lambda level, title, data: events.append((level, title)), clock=lambda: clock[0])
        up = Fake()
        fwd = dnsfwd.Forwarder("servers", [up], use_fallback=False, on_upstream=gate, cache=False)

        def step(fail, dt, name):
            clock[0] += dt
            up.fail_now = fail
            up.down_until = 0
            fwd.resolve(dnsfwd.build_query(name, 1))
            gate.flush()

        step(True, 0, "a.example")
        step(False, 60, "b.example")
        step(True, 60, "c.example")
        for i in range(30):
            step(True, 60, f"d{i}.example")
        self.assertEqual(events[-1][0], "warn")
        self.assertNotIn(("info", "DNS für ntp-gui: dns.quad9.net antwortet wieder"), events)

    def test_health_check_asks_every_server(self):
        fake = dnsfx.FakeDns()
        self.addCleanup(fake.close)
        good = dnsfwd.PlainUpstream("127.0.0.1", fake.port)
        dead = dnsfwd.PlainUpstream("127.0.0.1", dnsfx.refusing_udp_port(self))
        fwd = dnsfwd.Forwarder("servers", [good, dead], use_fallback=False)
        result = fwd.health_check("ptbtime1.ptb.de")
        self.assertEqual(result[good.label], {"ok": True, "error": None})
        self.assertFalse(result[dead.label]["ok"])
        self.assertEqual((fwd.stats["health_ok"], fwd.stats["health_total"]), (1, 2))
        self.assertIsNotNone(good.last_ok)
        self.assertEqual(fwd.state, "ok")
        # der Cache spielt keine Rolle: zweite Probe fragt erneut
        before = fake.udp_count
        fwd.health_check("ptbtime1.ptb.de")
        self.assertGreater(fake.udp_count, before)

    def test_health_name(self):
        self.assertEqual(dnsfwd.health_name({"ntp_sources": [{"host": "192.53.103.108"},
                                                             {"host": "PTBtime1.ptb.de."}]}), "ptbtime1.ptb.de")
        self.assertIsNone(dnsfwd.health_name({"ntp_sources": [{"host": "192.53.103.108"}]}))
        self.assertIsNone(dnsfwd.health_name({"ntp_sources": [{"host": "bad_name!.de"}]}))
        self.assertIsNone(dnsfwd.health_name({}))


class ResolverStateTest(unittest.TestCase):
    def test_nts_note(self):
        cfg = {"dns_mode": "dot", "dns_dot": ["dns.quad9.net"],
               "ntp_sources": [{"host": "ptbtime1.ptb.de", "nts": True}, {"host": "pool.ntp.org"}]}
        self.assertIn("ptbtime1.ptb.de braucht ihren Namen", dnsfwd.nts_note(cfg, 1))
        self.assertIsNone(dnsfwd.nts_note(cfg, 2))
        self.assertIsNone(dnsfwd.nts_note(dict(cfg, dns_mode="system"), 0))
        self.assertIsNone(dnsfwd.nts_note(dict(cfg, ntp_sources=[{"host": "pool.ntp.org"}]), 1))

    def test_api_status_last_success(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cfg = {"dns_mode": "dot", "dns_dot": ["dns.quad9.net", "one.one.one.one"],
               "ntp_sources": [{"host": "ptbtime1.ptb.de", "nts": True}]}
        dnsfwd.write_json(dnsfwd.status_path(tmp), {
            "pid": os.getpid(), "state": "ok", "resolv": {"state": "local"},
            "upstreams": [{"label": "dns.quad9.net", "ok": 3, "last_ok": 1000.0, "last_error_t": None},
                          {"label": "one.one.one.one", "ok": 1, "last_ok": 900.0, "last_error_t": 950.0}]})
        status = dnsfwd.api_status(cfg, tmp)
        self.assertEqual(status["last_success"], 1000.0)
        self.assertEqual(status["reachable"], 1)
        self.assertEqual(status["upstream_count"], 2)
        self.assertIsNone(status["nts_note"])
        single = dict(cfg, dns_dot=["dns.quad9.net"])
        self.assertTrue(dnsfwd.api_status(single, tmp)["nts_note"])
        self.assertIsNone(dnsfwd.api_status({"dns_mode": "system"}, tmp)["last_success"])

    def test_insight(self):
        dns = {"mode": "dot", "effective_mode": "dot", "state": "ok", "nts_note": "NTS-Quelle x braucht …"}
        keys = [i["key"] for i in insights.dns_insights(dns, {"dns_mode": "dot"})]
        self.assertIn("dns_nts_single", keys)

    def test_nat_loop_from_check_is_no_dns_insight(self):
        # Eine NAT-Schleife aus der Prüfung darf nicht als „Schleife durch DNS-Umschreibung“ erscheinen.
        self.assertEqual(insights.dns_insights({"mode": "system"}, {}, [], [], [{"host": "x", "cause": "nat"}]), [])
        keys = [i["key"] for i in insights.dns_insights({"mode": "system"}, {}, [], [], [{"host": "x", "cause": "dns"}])]
        self.assertEqual(keys, ["dns_loop"])


class LoopsEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        import settings
        cls.server = server
        cls.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k not in ("WEB_USER", "WEB_PASSWORD", "WEB_READONLY")}
        cls.patches = [mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
                       mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
                       mock.patch.object(server, "RUN_DIR", cls.tmp.name),
                       mock.patch.dict(os.environ, env, clear=True)]
        for patch in cls.patches:
            patch.start()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        import store
        store.close_all()
        cls.tmp.cleanup()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)

    def test_loops_and_v1(self):
        for path in ("/api/loops", "/api/v1/loops"):
            status, payload = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn("loops", payload)
            self.assertIn(payload["level"], ("good", "crit"))
        status, payload = self.get("/api/v1")
        self.assertIn("/api/v1/loops", {e["path"] for e in payload["endpoints"]})

    def test_loop_check_never_raises(self):
        with mock.patch.object(self.server.chrony, "detailed_sources", side_effect=RuntimeError("weg")):
            self.server.LOOP_GUARD._last_mono = None
            self.server.loop_check()  # wirft nicht

    def test_loop_guard_runs_on_its_own_timer(self):
        # F6: Die Schleifen-Prüfung hängt nicht am Verlaufs-Takt (history_interval bis 600 s).
        self.assertNotIn("loop_check()", __import__("inspect").getsource(self.server.collector))
        stop = threading.Event()
        calls = []
        waits = []

        def fake_check():
            calls.append(1)
            if len(calls) >= 3:
                stop.set()
        real_wait = stop.wait
        with mock.patch.object(self.server, "loop_check", side_effect=fake_check), \
                mock.patch.object(self.server.LOOP_GUARD, "seconds_until_due", return_value=16.0), \
                mock.patch.object(stop, "wait", side_effect=lambda t: (waits.append(t), real_wait(0))[1]):
            runner = threading.Thread(target=self.server.loop_guard_runner, args=(stop,), daemon=True)
            runner.start()
            runner.join(30)
        self.assertFalse(runner.is_alive())
        self.assertEqual(len(calls), 3)
        self.assertTrue(waits and all(w == 16.0 for w in waits), waits)


if __name__ == "__main__":
    unittest.main()
