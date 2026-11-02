"""Clients 3 (1.5): Uhrgüte, Gruppen/VLAN-Ansichten, Regeln je Gerät, Inventar, Stundenwerte,
NTS-Hinweise, Gerätepass und Benachrichtigungen mit eigenem Gerätenamen (F5).

Abnahme aus docs/konzept/version-1.5.md, Thema 9:
  * synthetischer Client mit 50 ppm Drift und 64-s-Intervall → Uhrgüte 50 ± 5 ppm, Intervall 64 s;
  * Regel „fragt nicht mehr“ feuert genau einmal und meldet „wieder da“;
  * Gruppen-Zuordnung (IPv4/IPv6, Überlappung → spezifischeres Netz gewinnt);
  * Gerätepass ohne innerHTML mit Daten;
  * Benachrichtigung enthält ohne Schalter keine IP (Filtertest).

Ohne Sockets zum LAN, ohne Host-/sys,/proc,/dev; Zeiten werden eingespeist.
"""

import base64
import http.client
import json
import os
import random
import re
import shutil
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

import chrony  # noqa: E402
import clientinfo  # noqa: E402
import clientmon  # noqa: E402
import clients3  # noqa: E402
import egress  # noqa: E402
import notify  # noqa: E402
import settings  # noqa: E402
import statewatch  # noqa: E402
import store  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
T0 = 1_800_000_000.0


def reset_caches():
    clientinfo._META_CACHE.update(t=0.0, data=None)
    clients3._drop_group_cache()
    clients3._drop_rule_cache()
    clients3._QUALITY_CACHE.update(t=None, data=None)
    clients3._NTS_CACHE.update(t=None, data={})
    clients3.INVENTORY.reset()
    clients3.WATCH._live.clear()


class TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved_dir = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        reset_caches()

    def tearDown(self):
        store.close_all()
        settings.DATA_DIR = self.saved_dir
        reset_caches()
        shutil.rmtree(self.tmp, ignore_errors=True)


def entry_with(recent, intervals, requests=None, state="ok"):
    return {"state": state, "requests": requests or len(recent), "count": len(recent) if state == "ok" else 0,
            "intervals": intervals, "recent": recent}


class EventSink:
    def __init__(self):
        self.events = []

    def __call__(self, kind, level, title, data=None, **_kw):
        self.events.append({"kind": kind, "level": level, "title": title, "data": dict(data or {})})


# ---------------------------------------------------------------------------
# Uhrgüte
# ---------------------------------------------------------------------------

class QualityTest(unittest.TestCase):
    def test_sawtooth_50ppm_64s(self):
        """Abnahme: Gerät stellt bei jeder Abfrage nach – Messung zeigt 50 ppm × 64 s = 3,2 ms."""
        rng = random.Random(7)
        recent = [[T0 + i * 64 + rng.uniform(-0.3, 0.3), 50e-6 * 64 + rng.gauss(0, 0.0002)] for i in range(32)]
        intervals = [64 + rng.uniform(-0.3, 0.3) for _ in range(16)]
        q = clients3.clock_quality(entry_with(recent, intervals))
        self.assertEqual(q["method"], "saegezahn")
        self.assertAlmostEqual(q["drift_ppm"], 50, delta=5)
        self.assertAlmostEqual(q["interval"], 64, delta=1)
        self.assertIsNotNone(q["score"])
        self.assertIn("ppm", q["text"])

    def test_sawtooth_separates_bias_when_intervals_vary(self):
        rng = random.Random(9)
        t, recent = T0, []
        for _ in range(32):
            gap = rng.uniform(32, 128)
            t += gap
            recent.append([t, 0.020 + 50e-6 * gap + rng.gauss(0, 0.0001)])   # 20 ms fester Versatz + 50 ppm
        q = clients3.clock_quality(entry_with(recent, [64.0] * 16))
        self.assertEqual(q["method"], "saegezahn")
        self.assertAlmostEqual(q["drift_ppm"], 50, delta=5)
        self.assertAlmostEqual(q["bias"], 0.020, delta=0.002)

    def test_constant_offset_is_not_drift(self):
        """30 ms gleichbleibend bei 64 s wären 470 ppm – das ist ein fester Versatz, keine Gangabweichung."""
        rng = random.Random(4)
        recent = [[T0 + i * 64, 0.030 + rng.gauss(0, 0.0005)] for i in range(32)]
        q = clients3.clock_quality(entry_with(recent, [64.0] * 16))
        self.assertEqual(q["method"], "versatz")
        self.assertIsNone(q["drift_ppm"])
        self.assertIn("fester Versatz", q["text"])

    def test_free_running_slope(self):
        rng = random.Random(3)
        recent = [[T0 + i * 64, -50e-6 * i * 64 + rng.gauss(0, 0.0002)] for i in range(32)]
        q = clients3.clock_quality(entry_with(recent, [64.0] * 16))
        self.assertEqual(q["method"], "frei")
        self.assertAlmostEqual(q["drift_ppm"], -50, delta=5)

    def test_good_and_bad_clock_scores(self):
        good = clients3.clock_quality(entry_with([[T0 + i * 64, 0.0002] for i in range(16)], [64.0] * 16))
        self.assertGreaterEqual(good["score"], 85)
        self.assertEqual(good["grade"], "sehr gut")
        rng = random.Random(1)
        bad = clients3.clock_quality(entry_with([[T0 + i * 64, 0.4 + rng.gauss(0, 0.1)] for i in range(16)],
                                                [rng.uniform(10, 900) for _ in range(16)], requests=40))
        self.assertLess(bad["score"], 50)
        self.assertEqual(bad["tone"], "crit")
        self.assertEqual(sum(c["max"] for c in bad["components"]), 100)

    def test_not_rateable(self):
        for state in (clientmon.OBFUSCATED, clientmon.NO_TIMESTAMP, None):
            q = clients3.clock_quality({"state": state, "recent": [], "intervals": [64] * 5})
            self.assertIsNone(q["score"])
            self.assertEqual(q["grade"], "nicht bewertbar")
        q = clients3.clock_quality(entry_with([[T0, 0.001], [T0 + 64, 0.001]], [64.0]))
        self.assertIsNone(q["score"])
        self.assertIn("zu wenige", q["text"])
        wrong = clients3.clock_quality({"state": clientmon.WRONG_CLOCK, "recent": [[T0, 9e5]], "intervals": []})
        self.assertEqual(wrong["score"], 0)

    def test_ring_from_live_table_and_restore(self):
        table = clientmon.ClientTable()
        for i in range(40):
            table.update("192.168.1.5", {"xmit": 1, "version": 4, "poll": 6}, 0.0032, T0 + i * 64)
        snap = table.snapshot(private=True)["192.168.1.5"]
        self.assertEqual(len(snap["recent"]), clientmon.RECENT_KEPT)
        self.assertNotIn("recent", table.snapshot()["192.168.1.5"])  # nicht in der öffentlichen Liste
        restored = clientmon.ClientTable()
        restored.restore({"192.168.1.5": clientmon._from_stored(json.loads(json.dumps(snap)))})
        again = restored.snapshot(private=True)["192.168.1.5"]
        self.assertEqual(len(again["recent"]), clientmon.RECENT_KEPT)
        bad = clientmon._clean_recent([[1, float("nan")], ["x", 1], [1, 2, 3], [5.0, 0.1], True])
        self.assertEqual(bad, [[5.0, 0.1]])
        q = clients3.clock_quality(again)
        self.assertAlmostEqual(q["drift_ppm"], 50, delta=1)

    def test_overview_worst_first(self):
        quals = {"a": {"score": 90, "grade": "sehr gut"}, "b": {"score": 30, "grade": "schlecht"},
                 "c": {"score": None, "grade": "nicht bewertbar"}}
        out = clients3.quality_overview(quals, meta={"b": {"name": "Kamera"}})
        self.assertEqual([w["address"] for w in out["worst"]], ["b", "a"])
        self.assertEqual(out["worst"][0]["name"], "Kamera")
        self.assertEqual(out["rated"], 2)
        self.assertIsNone(out["scores"]["c"]["score"])


# ---------------------------------------------------------------------------
# Gruppen
# ---------------------------------------------------------------------------

class GroupLogicTest(unittest.TestCase):
    def test_clean_network(self):
        self.assertEqual(clients3.clean_network(" 10.0.30.7/24 "), "10.0.30.0/24")
        self.assertEqual(clients3.clean_network("FD00:30::1/64"), "fd00:30::/64")
        for bad in ("", "10.0.30.0", "10.0.0.0/7", "::/8", "300.1.1.1/24", "fe80::1%eth0/64", "x" * 80,
                    "10.0.30.0/24; rm -rf /"):
            with self.assertRaises(clients3.Clients3Error, msg=bad):
                clients3.clean_network(bad)

    def test_group_names_validated(self):
        with self.assertRaises(clients3.Clients3Error):
            clients3.clean_group_name("")
        with self.assertRaises(clients3.Clients3Error):
            clients3.clean_group_name("IoT‮")
        with self.assertRaises(clients3.Clients3Error):
            clients3.clean_group_name("x" * 41)
        self.assertEqual(clients3.clean_group_name("  Kameras   Hof "), "Kameras Hof")

    def test_most_specific_network_wins(self):
        items = [{"id": 1, "name": "LAN", "network": "10.0.0.0/8"},
                 {"id": 2, "name": "IoT", "network": "10.0.30.0/24"},
                 {"id": 3, "name": "Kameras", "network": "10.0.30.64/26"},
                 {"id": 4, "name": "v6-IoT", "network": "fd00:30::/64"},
                 {"id": 5, "name": "v6-ULA", "network": "fd00::/8"}]
        index = clients3.GroupIndex(items)
        self.assertEqual(index.find("10.0.30.70")["name"], "Kameras")
        self.assertEqual(index.find("10.0.30.5")["name"], "IoT")
        self.assertEqual(index.find("10.9.9.9")["name"], "LAN")
        self.assertEqual(index.find("::ffff:10.0.30.70")["name"], "Kameras")   # IPv4 in IPv6
        self.assertEqual(index.find("fd00:30::abcd")["name"], "v6-IoT")
        self.assertEqual(index.find("fd00:99::1")["name"], "v6-ULA")
        self.assertIsNone(index.find("192.168.1.1"))
        self.assertIsNone(index.find("kein-ip"))

    def test_suggestions(self):
        ips = ["192.168.1.2", "192.168.1.3", "10.0.40.2", "fd00:1::2", "fd00:1::3", "fd00:1::4", "fe80::1",
               "10.0.30.5"]
        out = clients3.suggest_networks(ips, [{"id": 1, "name": "IoT", "network": "10.0.30.0/24"}])
        self.assertEqual(out[0], {"network": "fd00:1::/64", "count": 3})
        nets = [s["network"] for s in out]
        self.assertIn("192.168.1.0/24", nets)
        self.assertNotIn("10.0.30.0/24", nets)
        self.assertFalse(any(n.startswith("fe80") for n in nets))


def fixture_clients(now):
    """17 LAN-Clients aus dem Diagnosepaket des Maintainers (Intervalle echt, Adressen synthetisch)."""
    data = json.loads((FIXTURES / "clients3_lan.json").read_text(encoding="utf-8"))["clients"]
    table = clientmon.ClientTable()
    rng = random.Random(11)
    for item in data:
        interval = item["interval"]
        start = now - item["ntp_last_rx"] - interval * 9
        for i in range(10):
            t = start + i * interval
            if item["kind"] == "chrony":
                offset = rng.choice([-1, 1]) * rng.uniform(1e6, 1e9)   # verschleiert
            elif item["kind"] == "windows":
                offset = 0.12 + rng.gauss(0, 0.01)
            else:
                offset = 0.002 + rng.gauss(0, 0.0003)
            version = 3 if item["kind"] == "windows" else 4
            table.update(item["address"], {"xmit": 1, "version": version, "poll": 10 if version == 3 else 6,
                                            "bare": item["kind"] != "windows", "stratum": 0}, offset, t)
    return table


class GroupViewTest(TempData):
    def test_view_by_group_with_fixture(self):
        now = T0
        table = fixture_clients(now)
        clients = table.snapshot()
        items = [{"id": 1, "name": "LAN", "network": "192.168.1.0/24"},
                 {"id": 2, "name": "IoT", "network": "10.0.30.0/24"},
                 {"id": 3, "name": "Gäste", "network": "10.0.50.0/24"}]
        quals = clients3.quality_all(table.snapshot(private=True))
        out = clients3.view(clients, "group", {}, {}, quals, items, now=now, monitor_since=now - 7200, running=True)
        by = {g["label"]: g for g in out["groups"]}
        self.assertEqual(by["LAN"]["total"], 9)
        self.assertEqual(by["IoT"]["total"], 5)
        self.assertEqual(by["ohne Gruppe"]["total"], 3)   # die IPv6-Geräte
        self.assertEqual(by["Gäste"]["total"], 0)
        self.assertIn("fragt seit 24 h kein Gerät", by["Gäste"]["hint"])
        self.assertIsNone(by["LAN"]["hint"])
        lan = by["LAN"]
        self.assertEqual(lan["measured"], 7)                # zwei chrony-Geräte verschleiern
        self.assertAlmostEqual(lan["good_share"], 5 / 7)    # Windows-Geräte liegen bei ~120 ms
        self.assertIsNotNone(lan["median_offset"])
        self.assertIsNotNone(lan["score_median"])
        self.assertEqual(out["suggestions"], [{"network": "fd00:1::/64", "count": 3}])
        # Ohne laufende Messung kein Hinweis „fragt kein Gerät“
        quiet = clients3.view(clients, "group", {}, {}, quals, items, now=now, monitor_since=None, running=False)
        self.assertIsNone(next(g for g in quiet["groups"] if g["label"] == "Gäste")["hint"])

    def test_view_by_vlan_and_software(self):
        table = clientmon.ClientTable()
        table.update("192.168.1.5", {"xmit": 1, "version": 3, "poll": 10, "vlan": 30}, 0.01, T0)
        table.update("192.168.1.6", {"xmit": 1, "version": 4, "poll": 6}, 0.01, T0)
        clients = table.snapshot()
        vlan = clients3.view(clients, "vlan", {}, {}, {}, [], now=T0)
        self.assertEqual({g["label"] for g in vlan["groups"]}, {"VLAN 30", "ohne VLAN-Kennung"})
        rules = {"192.168.1.6": {"expect": "apple"}}
        sw = clients3.view(clients, "software", {}, rules, {}, [], now=T0)
        labels = {g["label"] for g in sw["groups"]}
        self.assertIn(clients3.SOFTWARE_LABELS["windows"], labels)
        self.assertIn(clients3.SOFTWARE_LABELS["apple"], labels)   # Regel schlägt Vermutung
        self.assertEqual(clients3.view(clients, "böse", {}, {}, {}, [], now=T0)["by"], "group")

    def test_save_and_delete_groups(self):
        g = clients3.save_group({"name": "IoT", "network": "10.0.30.9/24"})
        self.assertEqual(g["network"], "10.0.30.0/24")
        with self.assertRaises(clients3.Clients3Error):
            clients3.save_group({"name": "Doppelt", "network": "10.0.30.0/24"})
        changed = clients3.save_group({"id": g["id"], "name": "Smart Home", "network": "10.0.30.0/24"})
        self.assertEqual(changed["name"], "Smart Home")
        self.assertEqual(clients3.groups(fresh=True)[0]["name"], "Smart Home")
        self.assertIn("Smart Home", clients3.group_names())
        import diagnostics
        self.assertIn("Smart Home", diagnostics._client_names())   # Filter ersetzt Gruppennamen
        with self.assertRaises(clients3.Clients3Error):
            clients3.save_group({"id": 999, "name": "x", "network": "10.0.31.0/24"})
        self.assertTrue(clients3.delete_group(g["id"]))
        self.assertFalse(clients3.delete_group(g["id"]))
        self.assertEqual(clients3.groups(fresh=True), [])

    def test_group_limit(self):
        with mock.patch.object(clients3, "MAX_GROUPS", 2):
            clients3.save_group({"name": "a", "network": "10.0.1.0/24"})
            clients3.save_group({"name": "b", "network": "10.0.2.0/24"})
            with self.assertRaises(clients3.Clients3Error):
                clients3.save_group({"name": "c", "network": "10.0.3.0/24"})


# ---------------------------------------------------------------------------
# Regeln je Gerät
# ---------------------------------------------------------------------------

class RuleValidationTest(unittest.TestCase):
    def test_allowlist(self):
        rule = clients3.clean_rule({"silent_h": "6", "offset_ms": 500.4, "offset_min": "10", "mute": True,
                                    "expect": "windows", "evil": "x"})
        self.assertEqual(rule, {"silent_h": 6.0, "offset_ms": 500, "offset_min": 10, "mute": True, "expect": "windows"})
        self.assertEqual(clients3.clean_rule({})["silent_h"], None)
        for bad in ({"silent_h": 0.1}, {"silent_h": "abc"}, {"offset_ms": 0}, {"offset_ms": float("inf")},
                    {"offset_min": 5000}, {"expect": "rm -rf"}, {"mute": "ja"}, {"silent_h": 721}):
            with self.assertRaises(clients3.Clients3Error, msg=bad):
                clients3.clean_rule(bad)


class RuleStoreTest(TempData):
    def test_save_rule_roundtrip_and_delete(self):
        out = clients3.save_rule("192.168.1.40", {"silent_h": 6, "mute": True})
        self.assertEqual(out["ip"], "192.168.1.40")
        self.assertTrue(clients3.is_muted("192.168.1.40"))
        self.assertEqual(clients3.rules(fresh=True)["192.168.1.40"]["silent_h"], 6)
        clients3.save_rule("192.168.1.40", {})
        self.assertEqual(clients3.rules(fresh=True), {})
        with self.assertRaises(clients3.Clients3Error):
            clients3.save_rule("kein-ip", {"silent_h": 1})

    def test_global_alarm_filter(self):
        rules = {"a": {"offset_ms": 100}, "b": {"mute": True, "offset_ms": None}}
        self.assertEqual(set(clients3.global_alarm_filter({"a": {}, "b": {}, "c": {}}, rules)), {"b", "c"})


class SilentRuleTest(TempData):
    def test_fires_exactly_once_and_reports_back(self):
        """Abnahme: „fragt nicht mehr“ genau einmal, danach „wieder da“; Neustart meldet nichts doppelt."""
        clients3.save_rule("192.168.1.50", {"silent_h": 1})
        sink = EventSink()
        watch = clients3.RuleWatch()
        last = T0
        entry = {"last_seen": last, "measurable": False, "requests": 5}
        since = T0 - 86400
        for minute in range(0, 180, 5):                 # 3 h lang alle 5 min prüfen
            watch.evaluate({"192.168.1.50": entry}, clients3.rules(), last + minute * 60, sink, since, True)
        warns = [e for e in sink.events if e["level"] == "warn"]
        self.assertEqual(len(warns), 1)
        self.assertIn("192.168.1.50 fragt seit", warns[0]["title"])
        self.assertEqual(warns[0]["kind"], "clients")
        self.assertEqual(warns[0]["data"]["address"], "192.168.1.50")
        self.assertEqual(warns[0]["data"]["subject"], "192.168.1.50#still")
        self.assertNotIn("notify", warns[0]["data"])
        # Neustart: neuer Watcher, Zustand aus der Datenbank – keine zweite Meldung
        reset_caches()
        watch2 = clients3.RuleWatch()
        watch2.evaluate({"192.168.1.50": entry}, clients3.rules(), last + 4 * 3600, sink, last + 3 * 3600, True)
        self.assertEqual(len([e for e in sink.events if e["level"] == "warn"]), 1)
        # Wieder da
        back = dict(entry, last_seen=last + 5 * 3600)
        watch2.evaluate({"192.168.1.50": back}, clients3.rules(), last + 5 * 3600 + 10, sink, since, True)
        infos = [e for e in sink.events if e["level"] == "info"]
        self.assertEqual(len(infos), 1)
        self.assertIn("fragt wieder", infos[0]["title"])
        watch2.evaluate({"192.168.1.50": back}, clients3.rules(), last + 5 * 3600 + 20, sink, since, True)
        self.assertEqual(len(sink.events), 2)

    def test_counts_only_while_listening(self):
        clients3.save_rule("192.168.1.51", {"silent_h": 2})
        sink = EventSink()
        watch = clients3.RuleWatch()
        entry = {"last_seen": T0 - 10 * 3600}
        # Container war 10 h aus, Messung läuft erst seit 30 min → noch nicht „still“
        watch.evaluate({"192.168.1.51": entry}, clients3.rules(), T0, sink, T0 - 1800, True)
        self.assertEqual(sink.events, [])
        watch.evaluate({"192.168.1.51": entry}, clients3.rules(), T0 + 2 * 3600, sink, T0 - 1800, True)
        self.assertEqual(len(sink.events), 1)
        # Messung läuft nicht: gar nichts
        sink2 = EventSink()
        watch.evaluate({"192.168.1.51": entry}, clients3.rules(), T0 + 9 * 3600, sink2, None, False)
        self.assertEqual(sink2.events, [])

    def test_muted_stays_local(self):
        clients3.save_rule("192.168.1.52", {"silent_h": 1, "mute": True})
        sink = EventSink()
        clients3.RuleWatch().evaluate({"192.168.1.52": {"last_seen": T0}}, clients3.rules(), T0 + 7200, sink,
                                      T0 - 3600, True)
        self.assertIs(sink.events[0]["data"]["notify"], False)


class OffsetRuleTest(TempData):
    def test_threshold_for_minutes(self):
        clients3.save_rule("192.168.1.60", {"offset_ms": 100, "offset_min": 10})
        sink = EventSink()
        watch = clients3.RuleWatch()
        count = 0

        def step(t, value):
            nonlocal count
            count += 1
            watch.evaluate({"192.168.1.60": {"measurable": True, "offset": value, "count": count, "last_seen": t}},
                           clients3.rules(), t, sink, T0 - 3600, True)
        for i in range(5):                 # 4 min über der Schwelle: zu kurz
            step(T0 + i * 60, 0.25)
        self.assertEqual(sink.events, [])
        step(T0 + 300, 0.01)               # Unterbrechung setzt zurück
        for i in range(12):
            step(T0 + 400 + i * 60, -0.3)
        warns = [e for e in sink.events if e["level"] == "warn"]
        self.assertEqual(len(warns), 1)
        self.assertIn("eigene Schwelle", warns[0]["title"])
        self.assertEqual(warns[0]["data"]["subject"], "192.168.1.60#abw")
        # gleiche Messung (count unverändert) zählt nicht
        watch.evaluate({"192.168.1.60": {"measurable": True, "offset": 0.0, "count": count}}, clients3.rules(),
                       T0 + 2000, sink, T0, True)
        step(T0 + 2100, 0.07)              # unter Schwelle, aber über der Hälfte: noch nicht „wieder im Rahmen“
        step(T0 + 2200, 0.07)
        self.assertEqual(len(sink.events), 1)
        step(T0 + 2300, 0.01)
        step(T0 + 2400, 0.01)
        self.assertEqual([e["level"] for e in sink.events], ["warn", "info"])

    def test_statewatch_data_for_and_filter(self):
        sink = EventSink()
        watch = statewatch.StateWatcher(sink)
        clients = {"192.168.1.70": {"measurable": True, "offset": 2.0, "count": 1}}
        watch.clients(clients, 1000, data_for=lambda ip: {"notify": False, "address": "x"})
        watch.clients({"192.168.1.70": dict(clients["192.168.1.70"], count=2)}, 1000,
                      data_for=lambda ip: {"notify": False, "address": "x"})
        self.assertEqual(len(sink.events), 1)
        self.assertIs(sink.events[0]["data"]["notify"], False)
        self.assertEqual(sink.events[0]["data"]["address"], "192.168.1.70")   # nicht überschreibbar


# ---------------------------------------------------------------------------
# Inventar
# ---------------------------------------------------------------------------

class InventoryTest(TempData):
    def snap(self, *ips, mac=None):
        return {ip: {"requests": 1, **({"mac": mac} if mac else {})} for ip in ips}

    def test_learns_first_then_reports(self):
        sink = EventSink()
        inv = clients3.Inventory()
        self.assertEqual(inv.check(self.snap("192.168.1.2", "192.168.1.3"), T0, True, sink), 2)
        self.assertEqual(inv.check(self.snap("192.168.1.4"), T0 + 3600, True, sink), 1)
        self.assertEqual(sink.events, [])                          # Lernzeit
        self.assertTrue(inv.status(T0 + 3600)["learning"])
        inv.check(self.snap("192.168.1.9"), T0 + 86400 + 1, True, sink)
        self.assertEqual(len(sink.events), 1)
        ev = sink.events[0]
        self.assertEqual(ev["title"], "Neues Gerät fragt nach der Zeit: 192.168.1.9")
        self.assertTrue(ev["data"]["standalone"])
        self.assertIs(ev["data"]["resolves"], False)
        inv.check(self.snap("192.168.1.9"), T0 + 86400 + 60, True, sink)   # schon bekannt
        self.assertEqual(len(sink.events), 1)
        # Neustart: Inventar aus der Datenbank
        again = clients3.Inventory()
        self.assertEqual(again.check(self.snap("192.168.1.9", "192.168.1.2"), T0 + 90000, True, sink), 0)

    def test_mac_identity_ipv6_skipped_and_disabled(self):
        sink = EventSink()
        inv = clients3.Inventory()
        inv.check({"192.168.1.2": {"requests": 1, "mac": "AA:BB:CC:00:11:22"}}, T0, True, sink)
        later = T0 + 2 * 86400
        # Gleiche MAC, neue IP (DHCP) → nicht neu; IPv6 ohne MAC → zählt nicht
        inv.check({"192.168.1.77": {"requests": 1, "mac": "aa:bb:cc:00:11:22"},
                   "2001:db8::1234": {"requests": 1}}, later, True, sink)
        self.assertEqual(sink.events, [])
        inv.check(self.snap("192.168.1.80"), later, False, sink)   # Schalter aus: nur lernen
        self.assertEqual(sink.events, [])

    def test_rate_limit_and_summary(self):
        sink = EventSink()
        inv = clients3.Inventory()
        inv.check(self.snap("10.0.0.1"), T0, True, sink)
        later = T0 + 2 * 86400
        inv.check(self.snap(*[f"10.0.1.{i}" for i in range(8)]), later, True, sink)
        self.assertEqual(len(sink.events), clients3.NEW_DEVICE_PER_HOUR)
        inv.check({}, later + 3700, True, sink)
        self.assertEqual(len(sink.events), clients3.NEW_DEVICE_PER_HOUR + 1)
        self.assertIn("3 weitere neue Geräte", sink.events[-1]["title"])


# ---------------------------------------------------------------------------
# Stundenwerte
# ---------------------------------------------------------------------------

class HourlyTest(TempData):
    def test_aggregate_and_prune(self):
        clientmon._migrate(store)
        hour = int(T0 // 3600)
        rows = []
        for i in range(30):
            rows.append(("192.168.1.5", hour * 3600 + i * 120, 0.001 * (i % 5), 6, 4, 120.0))
        rows.append(("192.168.1.5", hour * 3600 + 10, None, 6, 4, None))           # nicht messbar
        rows.append(("192.168.1.6", (hour - 1) * 3600 + 5, 0.5, 6, 4, None))
        with store.transaction() as conn:
            conn.executemany("INSERT INTO clientmon_samples(ip, t, offset, poll, version, interval) "
                             "VALUES(?, ?, ?, ?, ?, ?)", rows)
        now = (hour + 1) * 3600 + clients3.HOURLY_SETTLE + 1
        clients3._migrate(store)
        store.execute("INSERT INTO clients3_meta(key, value) VALUES('hourly_done', ?)", (str(hour - 2),))
        self.assertEqual(clients3.aggregate_hours(now), 2)
        out = clients3.hourly("192.168.1.5", since=0)
        self.assertEqual(len(out), 1)
        start, n, med, p95, lo, hi = out[0]
        self.assertEqual((start, n), (hour * 3600, 30))
        self.assertAlmostEqual(med, 0.002)
        self.assertAlmostEqual(hi, 0.004)
        self.assertEqual(clients3.aggregate_hours(now), 0)                     # nichts doppelt
        # 31 Tage später: alte Stunden weg
        later = now + 31 * 86400
        clients3.aggregate_hours(later)
        self.assertEqual(clients3.hourly("192.168.1.5", since=0), [])

    def test_first_run_bounded(self):
        clients3._migrate(store)
        n = clients3.aggregate_hours(T0)
        self.assertEqual(n, clients3.HOURLY_PER_TICK)


# ---------------------------------------------------------------------------
# NTS
# ---------------------------------------------------------------------------

CLIENTS_K = ("192.168.1.30,120,0,6,-,12,3,0,9,40\n"
             "192.168.1.31,50,0,10,-,600,0,0,-,4294967295\n")


class NtsTest(unittest.TestCase):
    def setUp(self):
        clients3._NTS_CACHE.update(t=None, data={})

    def test_parse_clients_k(self):
        rows = chrony.parse_clients_nts(CLIENTS_K)
        self.assertEqual(rows[0]["nts_ke"], 3)
        self.assertEqual(rows[0]["nts_ke_last_rx"], 40)
        self.assertEqual(rows[1]["nts_ke"], 0)
        self.assertIsNone(rows[1]["nts_ke_last_rx"])

    def test_usage_only_when_server_on(self):
        runner = mock.Mock(return_value=chrony.parse_clients_nts(CLIENTS_K))
        self.assertEqual(clients3.nts_usage({"nts_server_enable": False}, runner), {})
        runner.assert_not_called()
        usage = clients3.nts_usage({"nts_server_enable": True}, runner)
        self.assertEqual(list(usage), ["192.168.1.30"])
        on = {"nts_server_enable": True, "nts_server_name": "zeit.example"}
        used = clients3.nts_for("192.168.1.30", {}, "chrony", on, usage)
        self.assertTrue(used["uses"])
        self.assertIn("gutes Verhalten", used["text"])
        win = clients3.nts_for("192.168.1.31", {}, "windows", on, usage)
        self.assertFalse(win["uses"])
        self.assertFalse(win["can"])
        off = clients3.nts_for("192.168.1.30", {}, "chrony", {}, usage)
        self.assertFalse(off["server"])
        self.assertIn("aus", off["text"])


# ---------------------------------------------------------------------------
# Benachrichtigungen: eigener Gerätename statt Adresse (F5)
# ---------------------------------------------------------------------------

def channel(**kw):
    base = {"id": "abc12345", "name": "Test", "type": "ntfy", "kinds": [], "min_level": "info",
            "debounce_min": 0, "rate_per_hour": 30, "resolved": True}
    base.update(kw)
    return base


class NotifyDeviceTest(TempData):
    def setUp(self):
        super().setUp()
        notify._KNOWN.update(t=0.0, ok=False, names=[], values={})
        self.cfg = {"notify_lan_addresses": False, "notify_dashboard_url": ""}
        patch = mock.patch.object(settings, "values", side_effect=lambda: dict(self.cfg))
        patch.start()
        self.addCleanup(patch.stop)
        import diagnostics
        p2 = mock.patch.object(diagnostics, "_known_names", return_value=["zeitserver.example.org"])
        p2.start()
        self.addCleanup(p2.stop)
        clientinfo.set_meta("192.168.1.20", name="NAS Keller")
        clientinfo.set_meta("192.168.1.21", name="Kamera Hof")

    def tearDown(self):
        notify._KNOWN.update(t=0.0, ok=False, names=[], values={})
        super().tearDown()

    def route(self, event):
        router = notify.ChannelRouter(channel(), clock=lambda: 1000.0, wall=lambda: 1000.0)
        msgs = router.offer({"id": 1, "t": 1000.0, **event})
        return [notify.outgoing(m) for m in msgs]

    def test_name_not_address_by_default(self):
        """Abnahme (Filtertest): ohne Schalter keine IP in der Nachricht."""
        for ip, title in (("192.168.1.20", "Uhr von 192.168.1.20 weicht um +1,20 s ab"),
                          ("192.168.1.99", "192.168.1.99 fragt seit 6 h nicht mehr nach der Zeit"),
                          ("fd00:1::20", "Neues Gerät fragt nach der Zeit: fd00:1::20")):
            out = self.route({"kind": "clients", "level": "warn", "title": title, "data": {"address": ip}})
            self.assertEqual(len(out), 1)
            text = json.dumps(out, ensure_ascii=False)
            self.assertNotIn(ip, text)
            self.assertNotRegex(text, r"\d+\.\d+\.\d+\.\d+")
            self.assertNotIn("client-0", text)
            self.assertNotIn("device", out[0])
        out = self.route({"kind": "clients", "level": "warn", "title": "Uhr von 192.168.1.20 weicht um +1,20 s ab",
                          "data": {"address": "192.168.1.20"}})
        self.assertEqual(out[0]["title"], "Uhr von NAS Keller weicht um +1,20 s ab")
        out = self.route({"kind": "clients", "level": "warn", "title": "192.168.1.99 fragt seit 6 h nicht mehr",
                          "data": {"address": "192.168.1.99"}})
        self.assertEqual(out[0]["title"], "Gerät ohne Namen fragt seit 6 h nicht mehr")

    def test_switch_adds_lan_address(self):
        self.cfg["notify_lan_addresses"] = True
        out = self.route({"kind": "clients", "level": "warn", "title": "Uhr von 192.168.1.20 weicht um +1,20 s ab",
                          "data": {"address": "192.168.1.20"}})
        self.assertEqual(out[0]["title"], "Uhr von NAS Keller (192.168.1.20) weicht um +1,20 s ab")
        # Öffentliche Adressen gehen auch mit Schalter nie hinaus
        out = self.route({"kind": "clients", "level": "warn", "title": "Uhr von 203.0.113.7 weicht ab",
                          "data": {"address": "203.0.113.7"}})
        self.assertNotIn("203.0.113.7", out[0]["title"])

    def test_other_names_and_partial_addresses_filtered(self):
        out = self.route({"kind": "clients", "level": "warn",
                          "title": "Uhr von 192.168.1.2 weicht ab, Kamera Hof und 192.168.1.20 auch",
                          "data": {"address": "192.168.1.2"}})
        title = out[0]["title"]
        self.assertTrue(title.startswith("Uhr von Gerät ohne Namen weicht ab"), title)
        self.assertNotIn("Kamera Hof", title)
        self.assertNotIn("192.168.1.20", title)
        # Ein eigener Name mit Hostname wird trotzdem gefiltert
        clientinfo.set_meta("192.168.1.22", name="Drucker zeitserver.example.org")
        notify._KNOWN["t"] = float("-inf")
        out = self.route({"kind": "clients", "level": "warn", "title": "Uhr von 192.168.1.22 weicht ab",
                          "data": {"address": "192.168.1.22"}})
        self.assertNotIn("zeitserver.example.org", out[0]["title"])

    def test_muted_and_standalone(self):
        out = self.route({"kind": "clients", "level": "warn", "title": "Uhr von 192.168.1.20 weicht ab",
                          "data": {"address": "192.168.1.20", "notify": False}})
        self.assertEqual(out, [])
        router = notify.ChannelRouter(channel(), clock=lambda: 1000.0, wall=lambda: 1000.0)
        router.offer({"id": 1, "t": 1000.0, "kind": "clients", "level": "warn", "title": "Neues Gerät …",
                      "data": {"address": "192.168.1.9", "subject": "192.168.1.9#neu", "standalone": True,
                               "resolves": False}})
        self.assertIsNone(router.state["clients:192.168.1.9#neu"]["open_since"])

    def test_egress_device_message_rejects_leaks(self):
        msg = {"title": f"Uhr von {egress.DEVICE_PLACEHOLDER} weicht ab", "level": "warn", "kind": "clients"}
        out = egress.notify_device_message(msg, [], {"name": ["NAS Keller"]}, "NAS Keller", "192.168.1.20")
        self.assertEqual(out["title"], "Uhr von NAS Keller (192.168.1.20) weicht ab")
        out = egress.notify_device_message(msg, [], {}, "", "2002:c000:0204::1")   # 6to4: keine LAN-Adresse
        self.assertEqual(out["title"], "Uhr von Gerät ohne Namen weicht ab")
        self.assertIsNone(egress.lan_address("8.8.8.8"))
        self.assertEqual(egress.lan_address("::ffff:10.0.0.1"), "10.0.0.1")


# ---------------------------------------------------------------------------
# Gerätepass
# ---------------------------------------------------------------------------

class PassTest(TempData):
    def setUp(self):
        super().setUp()
        now = time.time()
        monitor = clientmon.Monitor(123)
        for i in range(12):
            monitor.table.update("192.168.1.40", {"xmit": 1, "version": 3, "poll": 10}, 0.0032 + i * 1e-5,
                                 now - 3600 + i * 300)
        monitor._persist()
        clientinfo.set_meta("192.168.1.40", name="Büro-PC Müller", note="geheime Notiz")
        clients3.save_group({"name": "Verwaltung", "network": "192.168.1.0/24"})

    def test_pass_data(self):
        data = clients3.device_pass("192.168.1.40", {"nts_server_enable": False})
        self.assertEqual(data["name"], "Büro-PC Müller")
        self.assertEqual(data["group"]["name"], "Verwaltung")
        self.assertEqual(data["software"]["key"], "windows")
        self.assertEqual(data["week"]["n"], 12)
        self.assertTrue(data["series"])
        self.assertIn("w32tm", data["recommendations"][0]["code"])
        self.assertIn(clients3.SERVER_PLACEHOLDER, data["recommendations"][0]["code"])
        self.assertIsNone(clients3.device_pass("192.168.1.41", {}))

    def test_shared_copy_is_filtered(self):
        import diagnostics
        with mock.patch.object(diagnostics, "_known_names", return_value=[]):
            data = clients3.device_pass("192.168.1.40", {})
            out = clients3.shared_pass(data, {})
        text = out["text"]
        self.assertNotIn("192.168.1.40", text)
        self.assertIn("client-01", text)
        self.assertNotIn("Müller", text)
        self.assertNotIn("Verwaltung", text)
        self.assertNotIn("geheime Notiz", text)
        self.assertIn("Gerätepass", text)

    def test_no_innerhtml_in_pass_page(self):
        """Abnahme: Gerätepass ohne innerHTML mit Daten (alle Seiten-Module von Clients 3)."""
        pages = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "pages"
        for name in ("clientpass.js", "clientdetail.js", "clients.js"):
            text = (pages / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", text), name)


# ---------------------------------------------------------------------------
# Leistung: 2000 Geräte
# ---------------------------------------------------------------------------

class PerformanceTest(unittest.TestCase):
    def test_2000_clients_under_one_second(self):
        table = clientmon.ClientTable()
        rng = random.Random(5)
        for i in range(2000):
            ip = f"10.{i // 250}.{(i // 50) % 5}.{i % 250 + 1}"
            for k in range(clientmon.RECENT_KEPT):
                table.update(ip, {"xmit": 1, "version": 4, "poll": 6}, rng.gauss(0.002, 0.001), T0 + k * 64 + i * 0.01)
        snap = table.snapshot(private=True)
        public = table.snapshot()
        items = [{"id": i, "name": f"G{i}", "network": f"10.{i}.0.0/16"} for i in range(8)]
        start = time.perf_counter()
        quals = clients3.quality_all(snap)
        clients3.quality_overview(quals, meta={})
        for by in clients3.VIEW_BYS:
            clients3.view(public, by, {}, {}, quals, items, now=T0 + 3000, monitor_since=T0, running=True)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0, f"{elapsed:.2f} s")


# ---------------------------------------------------------------------------
# HTTP: Endpunkte, Rechte, CSRF
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
        reset_caches()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        _, cls.read_key = apikeys.create("Lesen", "read")
        monitor = clientmon.Monitor(123)
        for i in range(6):
            monitor.table.update("192.168.1.40", {"xmit": 1, "version": 3, "poll": 10}, 0.02, time.time() - 600 + i * 60)
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
        reset_caches()
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

    def test_groups_rules_quality_pass(self):
        status, group = self.request("POST", "/api/clients/groups", {"name": "LAN", "network": "192.168.1.0/24"},
                                     self.basic())
        self.assertEqual(status, 200, group)
        status, payload = self.request("POST", "/api/clients/groups", {"name": "x", "network": "nonsense"}, self.basic())
        self.assertEqual(status, 422)
        status, view = self.request("GET", "/api/v1/clients/groups?by=group", headers=self.basic())
        self.assertEqual(status, 200, view)
        self.assertEqual(view["groups"][0]["label"], "LAN")
        self.assertEqual(view["groups"][0]["total"], 1)
        status, rule = self.request("POST", "/api/clients/rules", {"ip": "192.168.1.40", "silent_h": 6,
                                                                    "expect": "windows"}, self.basic())
        self.assertEqual(status, 200, rule)
        self.assertEqual(rule["silent_h"], 6)
        self.assertEqual(self.request("POST", "/api/clients/rules", {"ip": "192.168.1.40", "silent_h": -1},
                                      self.basic())[0], 422)
        status, rules = self.request("GET", "/api/v1/clients/rules", headers=self.basic())
        self.assertEqual(rules["rules"]["192.168.1.40"]["expect"], "windows")
        status, quality = self.request("GET", "/api/v1/clients/quality", headers=self.basic())
        self.assertEqual(status, 200)
        self.assertIn("192.168.1.40", quality["scores"])
        with mock.patch.object(clientinfo, "reverse_name", return_value=None):
            status, detail = self.request("GET", "/api/clients/detail?ip=192.168.1.40", headers=self.basic())
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["group"]["name"], "LAN")
        self.assertEqual(detail["rule"]["silent_h"], 6)
        self.assertIn("quality", detail)
        self.assertIn("nts", detail)
        status, data = self.request("GET", "/api/v1/clients/pass?ip=192.168.1.40", headers=self.basic())
        self.assertEqual(status, 200, data)
        self.assertEqual(data["software"]["origin"], "erwartet")
        status, shared = self.request("GET", "/api/clients/pass?ip=192.168.1.40&share=1", headers=self.basic())
        self.assertEqual(status, 200, shared)
        self.assertNotIn("192.168.1.40", shared["text"])
        self.assertEqual(self.request("GET", "/api/clients/pass?ip=evil", headers=self.basic())[0], 400)
        self.assertEqual(self.request("GET", "/api/clients/pass?ip=192.168.1.99", headers=self.basic())[0], 404)
        status, _ = self.request("POST", "/api/clients/groups/delete", {"id": group["id"]}, self.basic())
        self.assertEqual(status, 200)
        self.assertEqual(self.request("POST", "/api/clients/groups/delete", {"id": group["id"]}, self.basic())[0], 404)

    def test_read_key_and_csrf(self):
        bearer = {"Authorization": f"Bearer {self.read_key}"}
        for path in ("/api/v1/clients/groups", "/api/v1/clients/rules", "/api/v1/clients/groups/delete",
                     "/api/clients/rules"):
            status, payload = self.request("POST", path, {"ip": "192.168.1.40", "silent_h": 1}, bearer)
            self.assertEqual(status, 403, path)
        self.assertEqual(self.request("GET", "/api/v1/clients/quality", headers=bearer)[0], 200)
        headers = self.basic()
        headers.pop("X-NTP-GUI")
        self.assertEqual(self.request("POST", "/api/clients/rules", {"ip": "192.168.1.40", "silent_h": 1},
                                      headers)[0], 403)


class SettingsTest(unittest.TestCase):
    def test_new_fields_default_off(self):
        fields = {f["key"]: f for f in settings.SCHEMA}
        for key, env in (("clients_new_device_alarm", "CLIENTS_NEW_DEVICE_ALARM"),
                         ("notify_lan_addresses", "NOTIFY_LAN_ADDRESSES")):
            self.assertIs(fields[key]["default"], False)
            self.assertEqual(fields[key]["env"], env)
            self.assertTrue(fields[key]["help"])


if __name__ == "__main__":
    unittest.main()
