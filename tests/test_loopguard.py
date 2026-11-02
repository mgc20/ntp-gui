"""Tests für die Schleifen-Erkennung (loopguard.py, 1.5 Thema 10).

Grundlage sind echte chronyc-Ausgaben vom Pi 4 des Maintainers (tests/fixtures/loop_pi4_chronyc.json,
mit korrekten Ausnahmen, Adressen synthetisch). Daraus werden die beiden
Fehlerbilder aus R1 nachgebaut: DNS-Umschreibung ohne Ausnahme und NAT-Umleitung ohne Ausnahme.
"""

import copy
import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import chrony  # noqa: E402
import loopguard  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "loop_pi4_chronyc.json").read_text(encoding="utf-8"))
LOCAL = FIXTURE["local"]


def tracking():
    return chrony.parse_tracking(FIXTURE["tracking"])


def detailed():
    """Wie chrony.detailed_sources(), aus den aufgezeichneten Ausgaben."""
    ntp = {b["remote"]: b for b in chrony.parse_ntpdata(FIXTURE["ntpdata"])}
    out = chrony.parse_sources(FIXTURE["sources"])
    for src in out:
        if src.get("mode") in ("^", "="):
            src["ntp"] = copy.deepcopy(ntp.get(src["name"]))
            src["hostname"] = FIXTURE["hostnames"].get(src["name"])
    return out


def find(sources, host):
    return next(s for s in sources if s.get("hostname") == host)


def reftime_text(epoch):
    return time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(int(epoch)))


def echo_own(src, track):
    """Die Antwort des eigenen chronyd, wie ntpdata sie für eine Schleifen-Quelle zeigt."""
    src["ntp"].update(stratum=track["stratum"], reference_id=track["ref_id"],
                      reference_time=reftime_text(track["ref_time"]), reference_name="")


OURS_REPLY = {"stratum": 2, "ref_id": "C0356768", "ref_time": 1793607834.5096, "root_delay": 0.02,
              "root_dispersion": 0.0006, "precision": -20, "leap": 0}
FOREIGN_REPLY = {"stratum": 1, "ref_id": "50544200", "ref_time": 1793607877.0, "root_delay": 0.0,
                 "root_dispersion": 0.00001, "precision": -26, "leap": 0}


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, kind, level, title, data=None, source="web"):
        self.events.append({"kind": kind, "level": level, "title": title, "data": data or {}})


class ParseTest(unittest.TestCase):
    def test_reftime_utc(self):
        self.assertEqual(loopguard.parse_reftime("Mon Nov 02 08:24:37 2026"), 1793607877.0)
        self.assertIsNone(loopguard.parse_reftime("Thu Jan 01 00:00:00 1970x"))
        self.assertIsNone(loopguard.parse_reftime(None))

    def test_fixture_is_consistent(self):
        sources = detailed()
        self.assertEqual(len([s for s in sources if s["mode"] == "^"]), 5)
        self.assertTrue(all(s["ntp"] for s in sources if s["mode"] == "^"))
        self.assertEqual(tracking()["ref_id"], "C0356768")


FIB_TRIE = """Main:
  +-- 0.0.0.0/0 3 0 5
     |-- 0.0.0.0
        /0 universe UNICAST
     +-- 192.168.178.0/24 2 0 2
        |-- 192.168.178.0
           /24 link UNICAST
        |-- 192.168.1.40
           /32 host LOCAL
        |-- 192.168.178.255
           /32 link BROADCAST
Local:
  +-- 127.0.0.0/8 2 0 2
     |-- 127.0.0.1
        /32 host LOCAL
     |-- 192.168.1.40
        /32 host LOCAL
"""
IF_INET6 = """00000000000000000000000000000001 01 80 10 80       lo
fe80000000000000ba27ebfffe123456 02 40 20 80     eth0
zz bad
"""


class InterfaceTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(loopguard.parse_fib_trie(FIB_TRIE), ["192.168.1.40", "127.0.0.1"])
        self.assertEqual(loopguard.parse_if_inet6(IF_INET6), ["::1", "fe80::ba27:ebff:fe12:3456"])

    def test_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fib, v6 = Path(tmp, "fib"), Path(tmp, "v6")
            fib.write_text(FIB_TRIE)
            v6.write_text(IF_INET6)
            self.assertEqual(loopguard.interface_addresses(str(fib), str(v6)),
                             ["192.168.1.40", "127.0.0.1", "::1", "fe80::ba27:ebff:fe12:3456"])
            self.assertEqual(loopguard.interface_addresses(str(Path(tmp, "x")), str(Path(tmp, "y"))), [])


class PatternTest(unittest.TestCase):
    def test_real_sources_show_no_pattern(self):
        track = tracking()
        for src in detailed():
            if src["mode"] == "^":
                self.assertIsNone(loopguard.reply_pattern(src["ntp"], track), src["name"])

    def test_match_and_partial(self):
        track = tracking()
        src = find(detailed(), "ptbtime3.ptb.de")
        echo_own(src, track)
        self.assertEqual(loopguard.reply_pattern(src["ntp"], track), "match")
        src["ntp"]["reference_time"] = reftime_text(track["ref_time"] - 40)
        self.assertEqual(loopguard.reply_pattern(src["ntp"], track), "partial")
        src["ntp"]["stratum"] = 3
        self.assertIsNone(loopguard.reply_pattern(src["ntp"], track))

    def test_unsynced_tracking_never_matches_passively(self):
        track = dict(tracking(), stratum=0, ref_id="00000000")
        src = find(detailed(), "ptbtime3.ptb.de")
        src["ntp"].update(stratum=0, reference_id="00000000")
        self.assertIsNone(loopguard.reply_pattern(src["ntp"], track))

    def test_fingerprint_unsynced(self):
        a = {"leap": 3, "stratum": 0, "ref_id": "00000000", "precision": -20, "root_delay": 0.0,
             "root_dispersion": 0.5, "ref_time": None}
        self.assertTrue(loopguard.fingerprint_match(dict(a), dict(a, root_dispersion=0.5004)))
        self.assertFalse(loopguard.fingerprint_match(dict(a), dict(a, precision=-24)))
        self.assertFalse(loopguard.fingerprint_match(dict(a, leap=0), dict(a)))
        self.assertTrue(loopguard.fingerprint_match(OURS_REPLY, dict(OURS_REPLY)))
        self.assertFalse(loopguard.fingerprint_match(FOREIGN_REPLY, OURS_REPLY))


class AssessTest(unittest.TestCase):
    def setUp(self):
        self.track = tracking()
        self.sources = detailed()
        self.own = loopguard.own_set([], self.sources)

    def test_correct_setup_no_loop(self):
        self.assertIn(LOCAL, self.own)
        for src in self.sources:
            self.assertIsNone(loopguard.assess(src, self.own, self.track), src["name"])

    def test_dns_rewrite_to_own_address(self):
        src = find(self.sources, "de.pool.ntp.org")
        src["name"] = LOCAL
        src["ntp"]["remote"] = LOCAL
        verdict = loopguard.assess(src, self.own, self.track)
        self.assertEqual(verdict["cause"], "dns")
        self.assertIn("address", verdict["evidence"])
        self.assertEqual(verdict["title"], "de.pool.ntp.org zeigt auf dich selbst – vermutlich "
                                           "DNS-Umschreibung ohne Ausnahme für ntp-gui")

    def test_dns_rewrite_to_host_ip_in_bridge_network(self):
        # Docker-Bridge: Die Host-IP im LAN ist für den Container keine eigene, die Antwort aber schon.
        src = find(self.sources, "de.pool.ntp.org")
        src["name"] = src["ntp"]["remote"] = "192.168.178.2"
        echo_own(src, self.track)
        verdict = loopguard.assess(src, self.own, self.track, {"192.168.178.2": True})
        self.assertEqual(verdict["cause"], "dns")
        self.assertIn("probe", verdict["evidence"])

    def test_nat_redirect_by_name(self):
        src = find(self.sources, "ptbtime3.ptb.de")
        echo_own(src, self.track)
        verdict = loopguard.assess(src, self.own, self.track, {"192.53.103.103": True})
        self.assertEqual(verdict["cause"], "nat")
        self.assertEqual(verdict["title"], "ptbtime3.ptb.de zeigt auf dich selbst – vermutlich "
                                           "NAT-Umleitung ohne Ausnahme für ntp-gui")

    def test_nat_redirect_fixed_ip(self):
        src = find(self.sources, "ptbtime3.ptb.de")
        src["hostname"] = None
        echo_own(src, self.track)
        verdict = loopguard.assess(src, self.own, self.track)  # ohne Gegenprobe: passive Übereinstimmung
        self.assertEqual(verdict["cause"], "nat")
        self.assertEqual(verdict["evidence"], ["reply"])
        self.assertTrue(verdict["title"].startswith("192.53.103.103 zeigt auf dich selbst"))

    def test_probe_false_overrides_passive_match(self):
        src = find(self.sources, "ptbtime3.ptb.de")
        echo_own(src, self.track)
        self.assertIsNone(loopguard.assess(src, self.own, self.track, {"192.53.103.103": False}))

    def test_own_fixed_ip_title_without_lan_address(self):
        src = find(self.sources, "ptbtime1.ptb.de")
        src["hostname"] = None
        src["name"] = LOCAL
        verdict = loopguard.assess(src, self.own, self.track)
        self.assertEqual(verdict["cause"], "self_ip")
        self.assertNotIn(LOCAL, verdict["title"])

    def test_lan_source_nat_title_without_address(self):
        src = find(self.sources, "ptbtime1.ptb.de")
        src["hostname"] = None
        src["name"] = src["ntp"]["remote"] = "192.168.178.1"
        verdict = loopguard.assess(src, self.own, self.track, {"192.168.178.1": True})
        self.assertEqual(verdict["cause"], "nat")
        self.assertNotIn("192.168", verdict["title"])

    def test_loopback_and_refclock(self):
        self.assertIsNone(loopguard.assess({"mode": "#", "name": "GPS"}, self.own, self.track))
        verdict = loopguard.assess({"mode": "^", "name": "127.0.0.1", "hostname": "pool.ntp.org", "ntp": {}},
                                   set(), self.track)
        self.assertEqual(verdict["cause"], "dns")


class IntervalTest(unittest.TestCase):
    def test_interval_follows_poll(self):
        self.assertEqual(loopguard.check_interval(detailed()), loopguard.MAX_INTERVAL)  # poll 9/10
        self.assertEqual(loopguard.check_interval([{"mode": "^", "poll": 6}]), 32.0)
        self.assertEqual(loopguard.check_interval([{"mode": "^", "poll": 4}]), loopguard.MIN_INTERVAL)
        self.assertEqual(loopguard.check_interval([{"mode": "#", "poll": 2}]), 30.0)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.wall = [1_793_607_900.0]
        self.rec = Recorder()
        self.probes = []
        self.replies = {}

        def prober(targets, timeout):
            self.probes.append(list(targets))
            return {t: self.replies.get(t[0]) for t in targets}

        self.guard = loopguard.LoopGuard(self.rec, prober=prober, clock=lambda: self.clock[0],
                                         wall=lambda: self.wall[0])

    def run_check(self, sources, track=None):
        self.clock[0] += 60
        self.wall[0] += 60
        return self.guard.check(sources, track or tracking(), [], 123)

    def nat_sources(self):
        sources = detailed()
        echo_own(find(sources, "ptbtime3.ptb.de"), tracking())
        return sources

    def test_correct_setup_never_emits(self):
        for _ in range(5):
            self.assertEqual(self.run_check(detailed()), [])
        self.assertEqual(self.rec.events, [])
        self.assertEqual(self.probes, [])  # nichts verdächtig → keine einzige Gegenprobe
        self.assertEqual(self.guard.status()["level"], "good")

    def test_nat_loop_confirmed_after_two_checks(self):
        self.replies = {"127.0.0.1": OURS_REPLY, "192.53.103.103": dict(OURS_REPLY)}
        self.assertEqual(self.run_check(self.nat_sources()), [])
        self.assertEqual(self.rec.events, [])
        loops = self.run_check(self.nat_sources())
        self.assertEqual(len(loops), 1)
        self.assertEqual(len(self.rec.events), 1)
        event = self.rec.events[0]
        self.assertEqual((event["kind"], event["level"]), ("source", "crit"))
        self.assertIn("NAT-Umleitung ohne Ausnahme", event["title"])
        self.assertEqual(event["data"]["cause"], "nat")
        self.assertIn("probe", event["data"]["evidence"])
        # Gegenprobe höchstens alle 5 min je Adresse
        self.assertEqual(len(self.probes), 1)
        # weitere Prüfungen: kein zweites Ereignis
        self.run_check(self.nat_sources())
        self.assertEqual(len(self.rec.events), 1)
        status = self.guard.status()
        self.assertEqual(status["level"], "crit")
        self.assertIn("NAT-Regel", status["loops"][0]["remedy"])

    def test_resolution_event(self):
        self.replies = {"127.0.0.1": OURS_REPLY, "192.53.103.103": dict(OURS_REPLY)}
        self.run_check(self.nat_sources())
        self.run_check(self.nat_sources())
        self.run_check(detailed())
        self.assertEqual(len(self.rec.events), 1)  # ein Messpunkt reicht nicht
        self.run_check(detailed())
        self.assertEqual(len(self.rec.events), 2)
        self.assertEqual(self.rec.events[1]["level"], "info")
        self.assertEqual(self.rec.events[1]["title"],
                         "Schleife behoben: ptbtime3.ptb.de erreicht wieder einen fremden Server")
        self.assertEqual(self.guard.loops(), [])

    def test_dns_loop_without_probe(self):
        sources = detailed()
        src = find(sources, "de.pool.ntp.org")
        src["name"] = src["ntp"]["remote"] = LOCAL
        self.run_check(copy.deepcopy(sources))
        self.run_check(copy.deepcopy(sources))
        self.assertEqual(len(self.rec.events), 1)
        self.assertIn("DNS-Umschreibung ohne Ausnahme", self.rec.events[0]["title"])
        self.assertEqual(self.probes, [])

    def test_chronyd_silent_keeps_state(self):
        self.replies = {"127.0.0.1": OURS_REPLY, "192.53.103.103": dict(OURS_REPLY)}
        self.run_check(self.nat_sources())
        self.run_check(self.nat_sources())
        for _ in range(3):
            self.assertEqual(len(self.run_check([])), 1)
        self.assertEqual(len(self.rec.events), 1)

    def test_foreign_probe_suppresses_false_alarm(self):
        # Anderer Server mit gleicher Quelle und zufällig gleicher Sekunde: Gegenprobe sagt „fremd“.
        self.replies = {"127.0.0.1": OURS_REPLY, "192.53.103.103": FOREIGN_REPLY}
        for _ in range(3):
            self.assertEqual(self.run_check(self.nat_sources()), [])
        self.assertEqual(self.rec.events, [])

    def test_unsynced_loop_found_by_probe(self):
        unsynced = dict(tracking(), stratum=0, ref_id="00000000", ref_time=0.0)
        echo = {"leap": 3, "stratum": 0, "ref_id": "00000000", "precision": -20, "root_delay": 0.0,
                "root_dispersion": 1.2, "ref_time": None}
        sources = [s for s in detailed() if s.get("hostname") == "ptbtime2.ptb.de"]
        sources[0]["ntp"].update(stratum=0, reference_id="00000000", leap="Not synchronised")
        self.replies = {"127.0.0.1": echo, "192.53.103.104": dict(echo)}
        self.run_check(copy.deepcopy(sources), unsynced)
        self.run_check(copy.deepcopy(sources), unsynced)
        self.assertEqual(len(self.rec.events), 1)
        self.assertIn("NAT-Umleitung", self.rec.events[0]["title"])

    def test_due(self):
        self.assertTrue(self.guard.due())
        self.guard.check(detailed(), tracking(), [], 123)
        self.assertFalse(self.guard.due())
        self.clock[0] += loopguard.MAX_INTERVAL
        self.assertTrue(self.guard.due())

    def test_emit_failure_is_swallowed(self):
        def broken(*args, **kwargs):
            raise RuntimeError("db voll")
        guard = loopguard.LoopGuard(broken, clock=lambda: self.clock[0])
        sources = detailed()
        find(sources, "de.pool.ntp.org")["name"] = LOCAL
        guard.check(sources, tracking(), [], 123)
        self.assertEqual(len(guard.check(sources, tracking(), [], 123)), 1)


class InsightTest(unittest.TestCase):
    def test_keys_per_cause(self):
        loops = [{"cause": "dns", "title": "a zeigt auf dich selbst"}, {"cause": "nat", "title": "b …"},
                 {"cause": "nat", "title": "c …"}]
        out = loopguard.insights(loops)
        self.assertEqual([i["key"] for i in out], ["dns_loop", "loop_nat"])
        self.assertTrue(all(i["level"] == "crit" for i in out))
        self.assertIn("b …; c …", out[1]["text"])
        self.assertEqual(loopguard.insights([]), [])


if __name__ == "__main__":
    unittest.main()
