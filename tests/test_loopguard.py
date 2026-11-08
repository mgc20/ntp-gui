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
     +-- 192.168.1.0/24 2 0 2
        |-- 192.168.1.0
           /24 link UNICAST
        |-- 192.168.1.40
           /32 host LOCAL
        |-- 192.168.1.255
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
        src["name"] = src["ntp"]["remote"] = "192.168.1.2"
        echo_own(src, self.track)
        verdict = loopguard.assess(src, self.own, self.track, {"192.168.1.2": True})
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
        src["name"] = src["ntp"]["remote"] = "192.168.1.1"
        verdict = loopguard.assess(src, self.own, self.track, {"192.168.1.1": True})
        self.assertEqual(verdict["cause"], "nat")
        self.assertNotIn("192.168", verdict["title"])

    def test_loopback_and_refclock(self):
        self.assertIsNone(loopguard.assess({"mode": "#", "name": "GPS"}, self.own, self.track))
        verdict = loopguard.assess({"mode": "^", "name": "127.0.0.1", "hostname": "pool.ntp.org", "ntp": {}},
                                   set(), self.track)
        self.assertEqual(verdict["cause"], "dns")


    def test_own_address_other_port_is_another_server(self):
        """Ein zweiter NTP-Server auf demselben Rechner (anderer Port, z. B. chronyd des Hosts) ist
        keine Schleife – gefunden im 1.5.0-Labor mit Upstreams auf 127.0.0.1:10323/127.0.0.2:10325."""
        other = {"mode": "^", "name": "127.0.0.1", "hostname": None,
                 "ntp": {"remote": "127.0.0.1", "remote_port": 10323, "local": "127.0.0.1"}}
        self.assertIsNone(loopguard.assess(other, set(), self.track, ntp_port=10324))
        same = dict(other, ntp=dict(other["ntp"], remote_port=10324))
        self.assertEqual(loopguard.assess(same, set(), self.track, ntp_port=10324)["cause"], "self_ip")
        # Port unbekannt (kein ntpdata): wie bisher vorsichtig als Schleife.
        unknown = dict(other, ntp={})
        self.assertEqual(loopguard.assess(unknown, set(), self.track, ntp_port=10324)["cause"], "self_ip")
        # Anderer Port, aber die Antwort ist die eigene: die Antwort zählt weiter.
        src = find(self.sources, "ptbtime1.ptb.de")
        echo_own(src, self.track)
        src["name"] = src["ntp"]["remote"] = "127.0.0.1"
        src["ntp"]["remote_port"] = 10323
        verdict = loopguard.assess(src, set(), self.track, ntp_port=10324)
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict["evidence"], ["reply"])


class IntervalTest(unittest.TestCase):
    def test_interval_follows_poll(self):
        self.assertEqual(loopguard.check_interval(detailed()), loopguard.MAX_INTERVAL)  # poll 9/10
        self.assertEqual(loopguard.check_interval([{"mode": "^", "poll": 6}]), 32.0)
        self.assertEqual(loopguard.check_interval([{"mode": "^", "poll": 4}]), loopguard.MIN_INTERVAL)
        self.assertEqual(loopguard.check_interval([{"mode": "#", "poll": 2}]), 30.0)


class _GuardBase(unittest.TestCase):
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


class GuardTest(_GuardBase):
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
        fixed = detailed()
        find(fixed, "ptbtime3.ptb.de")["ntp"]["total_valid_rx"] += 1   # neue fremde Antwort
        self.run_check(copy.deepcopy(fixed))
        self.assertEqual(len(self.rec.events), 1)  # ein Messpunkt reicht nicht
        self.run_check(copy.deepcopy(fixed))
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


class FindingsTest(_GuardBase):
    """Prüfbefunde zu 1.5 dns-nat (F1/LG-1, LG-2, F2, F4)."""

    def silent_local_prober(self, source_reply):
        """Standard-chronyd: 127.0.0.1 und LAN-Adressen ohne passende Freigabe → keine Antwort."""
        def prober(targets, timeout):
            self.probes.append(list(targets))
            return {t: (None if t[0] in ("127.0.0.1", LOCAL) else dict(source_reply)) for t in targets}
        return prober

    def guard_with(self, prober, tracker=None):
        self.guard = loopguard.LoopGuard(self.rec, prober=prober, tracker=tracker, clock=lambda: self.clock[0],
                                         wall=lambda: self.wall[0])

    def nat_echo(self, echoed_tracking):
        sources = detailed()
        echo_own(find(sources, "ptbtime3.ptb.de"), echoed_tracking)
        return sources

    def test_nat_found_without_localhost_answer(self):
        # F1: GPS-Referenz 16 s neuer als die Antwort in ntpdata („partial“), 127.0.0.1 stumm.
        self.guard_with(self.silent_local_prober(OURS_REPLY), tracker=tracking)
        older = dict(tracking(), ref_time=tracking()["ref_time"] - 16)
        self.run_check(self.nat_echo(older))
        self.assertEqual(self.rec.events, [])
        self.run_check(self.nat_echo(older))
        self.assertEqual(len(self.rec.events), 1)
        self.assertIn("NAT-Umleitung ohne Ausnahme", self.rec.events[0]["title"])
        self.assertEqual(self.rec.events[0]["data"]["evidence"], ["probe"])
        # gefragt wurden 127.0.0.1 und die eigene LAN-Adresse am NTP-Port
        self.assertIn(("127.0.0.1", 123), self.probes[0])
        self.assertIn((LOCAL, 123), self.probes[0])

    def test_tracking_after_probe_counts(self):
        # Referenzzeit wechselt zwischen tracking und Probe: tracking danach passt.
        calls = []

        def tracker():
            calls.append(1)
            track = tracking()
            return track if len(calls) % 2 == 0 else dict(track, ref_time=track["ref_time"] - 16)
        self.guard_with(self.silent_local_prober(OURS_REPLY), tracker=tracker)
        self.run_check(self.nat_echo(tracking()))
        self.run_check(self.nat_echo(tracking()))
        self.assertEqual(len(self.rec.events), 1)

    def test_foreign_pool_server_with_same_upstream_is_no_loop(self):
        # LG-1: fremder Stratum-2-Server an derselben PTB-Quelle, Referenzzeit 0,4 s anders;
        # ntpdata passt auf die Sekunde („match“). 127.0.0.1 stumm → Vergleich mit tracking.
        foreign = dict(OURS_REPLY, ref_time=OURS_REPLY["ref_time"] + 0.4, root_delay=0.031)
        self.guard_with(self.silent_local_prober(foreign), tracker=tracking)
        sources = detailed()
        src = find(sources, "de.pool.ntp.org")
        echo_own(src, tracking())
        self.assertEqual(loopguard.reply_pattern(src["ntp"], tracking()), "match")
        for _ in range(4):
            self.assertEqual(self.run_check(copy.deepcopy(sources)), [])
        self.assertEqual(self.rec.events, [])

    def test_inconclusive_probe_public_match_not_confirmed(self):
        # LG-1: Gegenprobe nicht vergleichbar (Adresse antwortet der Probe nicht) → die passive
        # Übereinstimmung allein bestätigt bei öffentlichen Adressen keine Schleife.
        def prober(targets, timeout):
            self.probes.append(list(targets))
            return {}
        self.guard_with(prober, tracker=tracking)
        sources = detailed()
        echo_own(find(sources, "de.pool.ntp.org"), tracking())
        for _ in range(4):
            self.assertEqual(self.run_check(copy.deepcopy(sources)), [])
        self.assertEqual(self.rec.events, [])
        # ohne Prober (keine Gegenprobe möglich) zählt die passive Übereinstimmung weiter
        self.guard_with(None)
        self.run_check(copy.deepcopy(sources))
        self.assertEqual(len(self.run_check(copy.deepcopy(sources))), 1)

    def test_probe_rate_when_localhost_never_answers(self):
        # LG-2: höchstens eine Gegenprobe je Adresse und PROBE_EVERY, auch ohne 127.0.0.1.
        foreign = dict(FOREIGN_REPLY, stratum=2, ref_id="C0356768")
        self.guard_with(self.silent_local_prober(foreign), tracker=tracking)
        older = dict(tracking(), ref_time=tracking()["ref_time"] - 40)   # „partial“ → verdächtig
        for _ in range(10):   # 10 × 60 s
            self.run_check(self.nat_echo(older))
        asked = [t for batch in self.probes for t in batch if t[0] == "192.53.103.103"]
        self.assertLessEqual(len(asked), 2)
        self.assertEqual(self.rec.events, [])

    def test_inconclusive_probe_backs_off(self):
        # Adresse antwortet der Probe nicht: einmal nach 60 s, danach nur alle 5 min.
        def prober(targets, timeout):
            self.probes.append(list(targets))
            return {}
        self.guard_with(prober, tracker=tracking)
        older = dict(tracking(), ref_time=tracking()["ref_time"] - 40)
        for _ in range(11):   # 0 … 600 s
            self.run_check(self.nat_echo(older))
        self.assertEqual(len(self.probes), 3)   # t=60, 120, 420

    def test_unsynced_loop_via_own_lan_address(self):
        # 127.0.0.1 stumm, eigene LAN-Adresse antwortet (Standard-Freigaben) → unsynchron erkennbar.
        unsynced = dict(tracking(), stratum=0, ref_id="00000000", ref_time=0.0)
        echo = {"leap": 3, "stratum": 0, "ref_id": "00000000", "precision": -20, "root_delay": 0.0,
                "root_dispersion": 1.2, "ref_time": None}
        sources = [s for s in detailed() if s.get("hostname") == "ptbtime2.ptb.de"]
        sources[0]["ntp"].update(stratum=0, reference_id="00000000")
        self.replies = {LOCAL: echo, "192.53.103.104": dict(echo)}
        self.run_check(copy.deepcopy(sources), unsynced)
        self.run_check(copy.deepcopy(sources), unsynced)
        self.assertEqual(len(self.rec.events), 1)
        self.assertIn("NAT-Umleitung", self.rec.events[0]["title"])

    def test_hostname_hiccup_keeps_state(self):
        # F2: chronyc sourcename fällt zweimal aus → kein „beendet“/„neu“-Paar, Ursache bleibt.
        self.replies = {"127.0.0.1": OURS_REPLY, "192.53.103.103": dict(OURS_REPLY)}
        for ok in (True, True, False, False, True, True):
            sources = self.nat_sources()
            if not ok:
                find(sources, "ptbtime3.ptb.de")["hostname"] = None
            self.run_check(sources)
        self.assertEqual(len(self.rec.events), 1)
        self.assertTrue(self.rec.events[0]["title"].startswith("ptbtime3.ptb.de zeigt auf dich selbst"))
        self.assertEqual(self.guard.loops()[0]["host"], "ptbtime3.ptb.de")

    def test_dns_loop_cause_survives_missing_name(self):
        # F2: eigene Adresse per Name (dns) darf ohne Namen nicht zu „self_ip“ werden.
        sources = detailed()
        find(sources, "de.pool.ntp.org")["name"] = LOCAL
        self.run_check(copy.deepcopy(sources))
        self.run_check(copy.deepcopy(sources))
        nameless = copy.deepcopy(sources)
        next(s for s in nameless if s["name"] == LOCAL)["hostname"] = None
        for _ in range(3):
            loops = self.run_check(copy.deepcopy(nameless))
        self.assertEqual(loops[0]["cause"], "dns")
        self.assertEqual(len(self.rec.events), 1)

    def test_first_name_after_address_moves_state(self):
        # Name fehlte schon bei der ersten Prüfung: Zustand wandert zur Namens-Quelle, kein Paar.
        self.replies = {"127.0.0.1": OURS_REPLY, "192.53.103.103": dict(OURS_REPLY)}
        sources = self.nat_sources()
        find(sources, "ptbtime3.ptb.de")["hostname"] = None
        self.run_check(copy.deepcopy(sources))
        self.run_check(copy.deepcopy(sources))
        self.assertEqual(len(self.rec.events), 1)
        for _ in range(3):
            self.run_check(self.nat_sources())
        self.assertEqual(len(self.rec.events), 1)

    def test_resolved_without_reply_is_not_called_foreign(self):
        # F4: Quelle zeigt jetzt auf eine Adresse ohne NTP-Server → keine Behauptung „fremder Server“.
        sources = detailed()
        find(sources, "de.pool.ntp.org")["name"] = LOCAL
        find(sources, "de.pool.ntp.org")["ntp"]["remote"] = LOCAL
        self.run_check(copy.deepcopy(sources))
        self.run_check(copy.deepcopy(sources))
        moved = detailed()
        src = find(moved, "de.pool.ntp.org")
        src["name"] = src["ntp"]["remote"] = "172.31.77.53"
        src["ntp"].update(total_valid_rx=0, stratum=0, reference_id="00000000")
        self.run_check(copy.deepcopy(moved))
        self.run_check(copy.deepcopy(moved))
        self.assertEqual(self.rec.events[-1]["title"],
                         "Schleife bei de.pool.ntp.org beendet – die Quelle antwortet derzeit nicht")
        self.assertEqual(self.rec.events[-1]["data"]["how"], "silent")

    def test_resolved_new_address_with_foreign_reply(self):
        sources = detailed()
        find(sources, "de.pool.ntp.org")["name"] = LOCAL
        self.run_check(copy.deepcopy(sources))
        self.run_check(copy.deepcopy(sources))
        self.run_check(detailed())   # echte Adresse, gültige fremde Antworten (Stratum 3)
        self.run_check(detailed())
        self.assertEqual(self.rec.events[-1]["title"],
                         "Schleife behoben: de.pool.ntp.org erreicht wieder einen fremden Server")

    def test_same_address_without_new_reply_is_silent(self):
        self.replies = {"127.0.0.1": OURS_REPLY, "192.53.103.103": dict(OURS_REPLY)}
        self.run_check(self.nat_sources())
        self.run_check(self.nat_sources())
        self.replies = {"127.0.0.1": OURS_REPLY, "192.53.103.103": FOREIGN_REPLY}
        self.clock[0] += loopguard.PROBE_EVERY
        self.run_check(detailed())   # gleicher Zähler wie in der Schleife: keine neue Antwort
        self.run_check(detailed())
        self.assertIn("antwortet derzeit nicht", self.rec.events[-1]["title"])

    def test_server_syncing_from_us_is_not_foreign(self):
        src = {"name": "192.53.103.103", "ntp": {"stratum": 3, "reference_id": "C0A80128", "total_valid_rx": 5}}
        self.assertFalse(loopguard.foreign_reply(src, {LOCAL}, None, False))
        src["ntp"]["reference_id"] = "50544200"
        self.assertTrue(loopguard.foreign_reply(src, {LOCAL}, None, False))
        self.assertFalse(loopguard.foreign_reply(src, {LOCAL}, 5, True))
        self.assertTrue(loopguard.foreign_reply(src, {LOCAL}, 4, True))

    def test_seconds_until_due(self):
        self.assertEqual(self.guard.seconds_until_due(), 0.0)
        self.guard.check(detailed(), tracking(), [], 123)
        self.assertEqual(self.guard.seconds_until_due(), loopguard.MAX_INTERVAL)
        self.clock[0] += 50
        self.assertAlmostEqual(self.guard.seconds_until_due(), 10.0)


class SourceNameTest(unittest.TestCase):
    """F2: chronyc sourcename-Aussetzer werden nicht 10 min gecacht."""

    def setUp(self):
        chrony._NAME_CACHE.clear()
        self.addCleanup(chrony._NAME_CACHE.clear)

    def test_failure_keeps_previous_name_and_retries_soon(self):
        from unittest import mock
        now = [1000.0]
        answers = ["ptbtime3.ptb.de", chrony.ChronyError("Zeitüberschreitung"), "ptbtime3.ptb.de"]

        def run(*args, **kwargs):
            item = answers.pop(0)
            if isinstance(item, Exception):
                raise item
            return item + "\n"
        with mock.patch.object(chrony, "run", side_effect=run), \
                mock.patch.object(chrony.time, "monotonic", side_effect=lambda: now[0]):
            self.assertEqual(chrony.source_name("192.53.103.103"), "ptbtime3.ptb.de")
            now[0] += chrony.NAME_TTL
            self.assertEqual(chrony.source_name("192.53.103.103"), "ptbtime3.ptb.de")  # Fehler: alter Name
            now[0] += chrony.NAME_RETRY
            self.assertEqual(chrony.source_name("192.53.103.103"), "ptbtime3.ptb.de")
            self.assertEqual(answers, [])

    def test_failure_without_name_is_not_cached_long(self):
        from unittest import mock
        now = [1000.0]
        answers = [chrony.ChronyError("weg"), "pool.ntp.org"]

        def run(*args, **kwargs):
            item = answers.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        with mock.patch.object(chrony, "run", side_effect=run), \
                mock.patch.object(chrony.time, "monotonic", side_effect=lambda: now[0]):
            self.assertIsNone(chrony.source_name("1.2.3.4"))
            now[0] += chrony.NAME_RETRY
            self.assertEqual(chrony.source_name("1.2.3.4"), "pool.ntp.org")


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
