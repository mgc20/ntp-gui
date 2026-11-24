"""Prometheus-Metriken zum Betrieb (1.11) und eine Prüfung des Textformats ohne promtool.

- Textformat 0.0.4: Namen, Labels, Maskierung, HELP/TYPE vor dem ersten Wert, jede Familie am Stück,
  keine doppelte Reihe, Zähler enden auf _total, Werte sind Zahlen.
- Client-Güte und Gruppen nur als Summen; Gruppennamen abschaltbar; nie Adressen oder Gerätenamen.
- Benachrichtigungen je Kanal-Art ohne Kennung/Name/Adresse; Zähler im Speicher.
- Nächtliche Sicherung (Alter, Fehlschlag), ntpgui_events_total je Art und Stufe, letzter Holdover-Test,
  GPS-Automatik (nur aus dem gespeicherten Stand), Zeitwächter-Ping.
- GPS: HDOP nur als Stufe, keine Satellitenzahlen (wie in der Aufzeichnung des Diagnosepakets).
"""

import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import autocal  # noqa: E402
import backup  # noqa: E402
import events  # noqa: E402
import holdover  # noqa: E402
import notify  # noqa: E402
import opsmetrics  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import test_integrations  # noqa: E402

NAME_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\\n]|\\[\\"n])*)"')
SAMPLE_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^\n]*\})? (\S+)( -?\d+)?$")
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}\b", re.I)


def check_exposition(text: str) -> list[str]:
    """Prüft das Prometheus-Textformat 0.0.4. Liefert die Fehler (leer = in Ordnung)."""
    errors: list[str] = []
    if not text.endswith("\n"):
        errors.append("Text endet nicht mit Zeilenumbruch")
    types: dict[str, str] = {}
    helps: set[str] = set()
    finished: set[str] = set()
    current = None
    seen: set[tuple] = set()
    for no, line in enumerate(text.rstrip("\n").split("\n"), 1):
        if not line:
            errors.append(f"{no}: leere Zeile")
            continue
        if line.startswith("#"):
            parts = line.split(" ", 3)
            if len(parts) < 3 or parts[1] not in ("HELP", "TYPE"):
                continue   # gewöhnlicher Kommentar
            name = parts[2]
            if not NAME_RE.fullmatch(name):
                errors.append(f"{no}: ungültiger Name {name!r}")
            if name in finished or (current and name != current and name in types):
                errors.append(f"{no}: Familie {name} nicht am Stück")
            if parts[1] == "TYPE":
                kind = parts[3] if len(parts) > 3 else ""
                if kind not in ("counter", "gauge", "untyped", "summary", "histogram"):
                    errors.append(f"{no}: unbekannter Typ {kind!r}")
                if name in types:
                    errors.append(f"{no}: TYPE doppelt für {name}")
                types[name] = kind
            else:
                if name in helps:
                    errors.append(f"{no}: HELP doppelt für {name}")
                if len(parts) < 4 or not parts[3].strip():
                    errors.append(f"{no}: HELP ohne Text für {name}")
                helps.add(name)
            if current and current != name:
                finished.add(current)
            current = name
            continue
        match = SAMPLE_RE.match(line)
        if not match:
            errors.append(f"{no}: Zeile nicht lesbar: {line!r}")
            continue
        name, labels, value = match.group(1), match.group(2) or "", match.group(3)
        if name not in types:
            errors.append(f"{no}: {name} ohne vorheriges TYPE")
        if name != current:
            if name in finished or name in types and current != name:
                errors.append(f"{no}: Familie {name} nicht am Stück")
            if current:
                finished.add(current)
            current = name
        pairs = []
        if labels:
            inner = labels[1:-1]
            pos = 0
            while pos < len(inner):
                lm = LABEL_RE.match(inner, pos)
                if not lm:
                    errors.append(f"{no}: Labels nicht lesbar: {labels!r}")
                    break
                if lm.group(1).startswith("__"):
                    errors.append(f"{no}: reservierter Label-Name {lm.group(1)}")
                pairs.append((lm.group(1), lm.group(2)))
                pos = lm.end()
                if pos < len(inner):
                    if inner[pos] != ",":
                        errors.append(f"{no}: Trenner fehlt in {labels!r}")
                        break
                    pos += 1
            if len({k for k, _v in pairs}) != len(pairs):
                errors.append(f"{no}: Label doppelt in {labels!r}")
        try:
            float(value)
        except ValueError:
            errors.append(f"{no}: Wert {value!r} ist keine Zahl")
        key = (name, tuple(sorted(pairs)))
        if key in seen:
            errors.append(f"{no}: Reihe doppelt: {line!r}")
        seen.add(key)
        if types.get(name) == "counter" and not name.endswith("_total"):
            errors.append(f"{no}: Zähler {name} endet nicht auf _total")
    return errors


def label_values(text: str) -> list[str]:
    return [v for line in text.splitlines() if not line.startswith("#")
            for _k, v in LABEL_RE.findall(line[line.find("{"):line.rfind("}") + 1] if "{" in line else "")]


class ValidatorSelfTest(unittest.TestCase):
    """Der Prüfer selbst muss die typischen Fehler finden – sonst beweist ein grüner Test nichts."""

    GOOD = "# HELP a_total x\n# TYPE a_total counter\na_total{k=\"v\\\"\"} 1\n# HELP b y\n# TYPE b gauge\nb 2.5\n"

    def test_good(self):
        self.assertEqual(check_exposition(self.GOOD), [])

    def test_detects_errors(self):
        cases = {
            "ohne TYPE": "c 1\n",
            "nicht am Stück": "# HELP a x\n# TYPE a gauge\na 1\n# HELP b y\n# TYPE b gauge\nb 1\na{x=\"1\"} 2\n",
            "doppelt": "# HELP a x\n# TYPE a gauge\na 1\na 2\n",
            "Zähler ohne _total": "# HELP a x\n# TYPE a counter\na 1\n",
            "kein Wert": "# HELP a x\n# TYPE a gauge\na abc\n",
            "kaputtes Label": "# HELP a x\n# TYPE a gauge\na{k=\"v} 1\n",
            "falsche Maskierung": "# HELP a x\n# TYPE a gauge\na{k=\"a\\tb\"} 1\n",
            "kein Zeilenende": "# HELP a x\n# TYPE a gauge\na 1",
            "leere Zeile": "# HELP a x\n# TYPE a gauge\n\na 1\n",
        }
        for what, text in cases.items():
            with self.subTest(what):
                self.assertTrue(check_exposition(text), what)


class ExpositionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = test_integrations.full_metrics()

    def test_format_valid(self):
        self.assertEqual(check_exposition(self.text), [])

    def test_new_families_present(self):
        for name in ("ntpgui_clients_quality", "ntpgui_clients_silent", "ntpgui_clients_offset_alarm",
                     "ntpgui_client_group_devices", "ntpgui_client_group_median_offset_seconds",
                     "ntpgui_notify_channels_failing", "ntpgui_notify_queue", "ntpgui_notify_deliveries_total",
                     "ntpgui_backup_nightly_age_seconds", "ntpgui_events_total", "ntpgui_holdover_last_result",
                     "ntpgui_gps_autocal_mode", "ntpgui_gps_autocal_phase", "ntpgui_heartbeat_enabled"):
            self.assertRegex(self.text, rf"(?m)^# TYPE {name} ")

    def test_no_addresses_or_device_names_in_labels(self):
        values = label_values(self.text)
        self.assertTrue(values)
        for value in values:
            self.assertIsNone(IP_RE.search(value), value)
        self.assertNotIn("Kameras", values)   # Gruppenname nur eingeschaltet (Standard aus)
        values_on = label_values(test_integrations.full_metrics({"metrics_group_names": True}))
        self.assertIn("Kameras", values_on)
        for value in values_on:
            self.assertIsNone(IP_RE.search(value), value)

    def test_gps_hdop_step_and_no_satellite_counts(self):
        self.assertNotIn("ntpgui_gps_satellites", self.text)
        self.assertRegex(self.text, r"(?m)^ntpgui_gps_hdop 1$")   # 0.8 → Stufe 1

    def test_gps_snr_only_strongest(self):
        # Der Mittelwert springt mit jedem schwachen Satelliten am Horizont – nur der stärkste Wert bleibt.
        self.assertNotIn("ntpgui_gps_snr_avg", self.text)
        self.assertRegex(self.text, r"(?m)^ntpgui_gps_snr_max_db 44$")

    def test_listening_seconds(self):
        self.assertRegex(self.text, r"(?m)^ntpgui_clients_listening_seconds 90000$")


class GroupNamesSwitchTest(unittest.TestCase):
    VIEW = {"groups": [{"key": "g3", "label": "Wohnzimmer \"oben\"", "total": 4, "active": 3, "silent": 1,
                        "measured": 2, "median_offset": 0.004, "good_share": 0.5, "score_median": 80},
                       {"key": "none", "label": "ohne Gruppe", "total": 1, "active": 1, "silent": 0,
                        "measured": 0, "median_offset": None, "good_share": None, "score_median": None},
                       {"key": "v7", "label": "VLAN 7", "total": 9}]}

    def render(self, rows):
        lines: list[str] = []
        for name, value, help_text, kind, labels in rows:
            server._metric(lines, name, value, help_text, kind=kind, labels=labels)
        return "\n".join(lines) + "\n"

    def test_names_on(self):
        text = self.render(opsmetrics.group_rows(self.VIEW, True))
        self.assertEqual(check_exposition(text), [])
        self.assertIn('ntpgui_client_group_devices{group_id="g3",group="Wohnzimmer \\"oben\\""} 4', text)
        self.assertIn('ntpgui_client_group_devices{group_id="none",group=""} 1', text)
        self.assertNotIn("v7", text)
        self.assertNotIn('group_id="none",group=""} None', text)

    def test_names_off(self):
        text = self.render(opsmetrics.group_rows(self.VIEW, False))
        self.assertEqual(check_exposition(text), [])
        self.assertNotIn("Wohnzimmer", text)
        self.assertNotIn("group=", text)
        self.assertIn('ntpgui_client_group_median_offset_seconds{group_id="g3"} 0.004', text)

    def test_setting(self):
        field = settings.FIELDS["metrics_group_names"]
        self.assertIs(field["default"], False)   # Gruppennamen nur bewusst eingeschaltet
        self.assertEqual(field["env"], "METRICS_GROUP_NAMES")
        self.assertIs(settings.validate({"metrics_group_names": "false"})["metrics_group_names"], False)

    def test_collect_honours_switch(self):
        text_default = test_integrations.full_metrics()
        text_on = test_integrations.full_metrics({"metrics_group_names": True})
        text_off = test_integrations.full_metrics({"metrics_group_names": False})
        self.assertNotIn("Kameras", text_default)
        self.assertNotIn("group=", text_default)
        self.assertIn('group="Kameras"', text_on)
        self.assertNotIn("Kameras", text_off)
        self.assertIn('group_id="g1"', text_off)
        self.assertEqual(check_exposition(text_off), [])

    def test_sources_contiguous(self):
        text = test_integrations.full_metrics()
        block = [l.split("{")[0] for l in text.splitlines() if l.startswith("ntpgui_source_offset_seconds")]
        self.assertEqual(len(block), 2)
        lines = text.splitlines()
        first = lines.index(next(l for l in lines if l.startswith("ntpgui_source_offset_seconds{")))
        self.assertTrue(lines[first + 1].startswith("ntpgui_source_offset_seconds{"))


class ClientRowsTest(unittest.TestCase):
    def test_sums_only(self):
        now = 1_000_000.0
        clients = {"192.168.1.5": {"last_seen": now - 10}, "192.168.1.6": {"last_seen": now - 10},
                   "fd00::7": {"last_seen": now - 90000}, "bad": "x"}
        qualities = {"192.168.1.5": {"score": 90}, "192.168.1.6": {"score": 40}}
        rows = opsmetrics.client_rows(clients, qualities, lambda e, t: t - e["last_seen"] > 86400, 2, 1, None,
                                      True, now=now)
        by = {(r[0], r[4]): r[1] for r in rows}
        self.assertEqual(by[("ntpgui_clients_monitored", "")], 3)
        self.assertEqual(by[("ntpgui_clients_quality", '{grade="very_good"}')], 1)
        self.assertEqual(by[("ntpgui_clients_quality", '{grade="poor"}')], 1)
        self.assertEqual(by[("ntpgui_clients_quality", '{grade="unrated"}')], 1)
        self.assertEqual(by[("ntpgui_clients_quality", '{grade="good"}')], 0)
        self.assertEqual(by[("ntpgui_clients_silent", "")], 1)
        self.assertEqual(by[("ntpgui_clients_offset_alarm", "")], 2)
        self.assertEqual(by[("ntpgui_clients_silent_alarm", "")], 1)
        for row in rows:
            self.assertNotIn("192.168", row[4])

    def test_listening_only_while_measuring(self):
        rows = opsmetrics.client_rows({}, {}, lambda e, t: False, 0, 0, None, False, now=1.0, listening=None)
        self.assertNotIn("ntpgui_clients_listening_seconds", [r[0] for r in rows])
        rows = opsmetrics.client_rows({}, {}, lambda e, t: False, 0, 0, None, False, now=1.0, listening=3600.4)
        self.assertIn(("ntpgui_clients_listening_seconds", 3600), [(r[0], r[1]) for r in rows])

    def test_grade_thresholds_match_clients3(self):
        import clients3
        mapping = {"sehr gut": "very_good", "gut": "good", "mäßig": "moderate", "schlecht": "poor",
                   "nicht bewertbar": "unrated"}
        for score in (None, 0, 49, 50, 69, 70, 84, 85, 100):
            self.assertEqual(opsmetrics.grade_key(score), mapping[clients3.grade(score)[0]], score)


class NotifyMetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = self.tmp
        notify._reset_for_tests()

    def tearDown(self):
        notify._reset_for_tests()
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_summary_per_type_without_identity(self):
        a = notify.save_channel({"name": "Handy von Max", "type": "ntfy", "url": "http://192.168.1.20/thema-geheim",
                                 "enabled": True})
        b = notify.save_channel({"name": "Hook", "type": "webhook", "url": "http://192.168.1.21/hook",
                                 "enabled": False})
        notify._record(a["id"], False, "Zeitüberschreitung", kind="ntfy")
        notify._record(a["id"], True, dropped=1, attempt=False, kind="ntfy")
        notify._record(b["id"], True, kind="webhook")
        summary = notify.metrics_summary()
        self.assertEqual(summary["ntfy"]["channels"], 1)
        self.assertEqual(summary["ntfy"]["enabled"], 1)
        self.assertEqual(summary["ntfy"]["failing"], 1)
        self.assertEqual(summary["ntfy"]["failed"], 1)
        self.assertEqual(summary["ntfy"]["dropped"], 1)
        self.assertEqual(summary["webhook"]["ok"], 1)
        self.assertEqual(summary["webhook"]["failing"], 0)   # aus: zählt nicht als gestört
        lines: list[str] = []
        for name, value, help_text, kind, labels in opsmetrics.notify_rows(summary, False):
            server._metric(lines, name, value, help_text, kind=kind, labels=labels)
        text = "\n".join(lines) + "\n"
        self.assertEqual(check_exposition(text), [])
        for secret in ("Handy", "Max", "192.168", "thema-geheim", a["id"], b["id"]):
            self.assertNotIn(secret, text)
        self.assertIn('ntpgui_notify_deliveries_total{type="ntfy",result="failed"} 1', text)

    def test_unknown_kind_ignored(self):
        notify._tally("evil{x}", True, 0, True)
        self.assertNotIn("evil{x}", notify._TALLY)


class EventsCounterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = self.tmp

    def tearDown(self):
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_counts_by_kind_and_level(self):
        before = events.counts()
        events.emit("gps", "warn", "GPS ohne Fix")
        events.emit("frei erfunden", "crit", "x")
        after = events.counts()
        self.assertEqual(after.get(("gps", "warn"), 0) - before.get(("gps", "warn"), 0), 1)
        self.assertEqual(after.get(("other", "crit"), 0) - before.get(("other", "crit"), 0), 1)
        self.assertNotIn(("frei erfunden", "crit"), after)

    def test_supervisor_ingest_counts(self):
        path = os.path.join(self.tmp, "events.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": time.time(), "kind": "service", "level": "crit",
                                     "title": "chronyd beendet"}) + "\n")
        before = events.counts().get(("service", "crit"), 0)
        self.assertEqual(events.ingest_supervisor(path), 1)
        self.assertEqual(events.counts().get(("service", "crit"), 0) - before, 1)

    def test_rows_cover_all_kinds(self):
        rows = opsmetrics.event_rows({("gps", "warn"): 3}, events.KINDS)
        self.assertEqual(len(rows), len(events.KINDS) * 3)
        self.assertIn(("ntpgui_events_total", 3), [(r[0], r[1]) for r in rows if r[4] == '{kind="gps",level="warn"}'])


class BackupMetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = self.tmp
        backup.NIGHTLY_RESULT.update(t=None, ok=None)

    def tearDown(self):
        backup.NIGHTLY_RESULT.update(t=None, ok=None)
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_age_of_newest_nightly(self):
        self.assertEqual(backup.nightly_metrics(True), {"enabled": True, "stored": 0, "age": None, "failed": False})
        os.makedirs(backup.backup_dir())
        old = os.path.join(backup.backup_dir(), backup.NIGHTLY_PREFIX + "20261120.tar.gz")
        new = os.path.join(backup.backup_dir(), backup.NIGHTLY_PREFIX + "20261121.tar.gz")
        for path, t in ((old, 1000.0), (new, 5000.0)):
            Path(path).write_bytes(b"x")
            os.utime(path, (t, t))
        info = backup.nightly_metrics(True, now=8600.0)
        self.assertEqual(info["stored"], 2)
        self.assertEqual(info["age"], 3600.0)
        rows = {r[0]: r[1] for r in opsmetrics.backup_rows(info)}
        self.assertEqual(rows["ntpgui_backup_nightly_age_seconds"], 3600.0)
        self.assertEqual(rows["ntpgui_backup_nightly_failed"], 0)
        self.assertEqual({r[0] for r in opsmetrics.backup_rows({"enabled": False})}, {"ntpgui_backup_nightly_enabled"})

    def test_failed_attempt_marked(self):
        with mock.patch.object(backup, "save_local", side_effect=OSError("voll")):
            self.assertFalse(backup.nightly_attempt())
        self.assertTrue(backup.nightly_metrics(True)["failed"])
        with mock.patch.object(backup, "save_local", return_value="x"):
            self.assertTrue(backup.nightly_attempt())
        self.assertFalse(backup.nightly_metrics(True)["failed"])


class HoldoverMetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = self.tmp

    def tearDown(self):
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_last_result(self):
        test = holdover.HoldoverTest(emit=lambda *a: None)
        self.assertIsNone(test.last_result())
        holdover._ensure()
        for outcome, dev in (("done", 1.0), ("limit", 12.5)):
            store.execute("INSERT INTO holdover_runs(started, json) VALUES(?, ?)",
                          (1.0, json.dumps({"outcome": outcome, "deviation_ms": dev, "duration_s": 7200,
                                            "drift_ppm": None, "ended": 9000.4, "include_network": False})))
        last = test.last_result()
        self.assertEqual(last["outcome"], "limit")
        rows = {(r[0], r[4]): r[1] for r in opsmetrics.holdover_rows(last)}
        self.assertEqual(rows[("ntpgui_holdover_last_result", '{outcome="limit"}')], 1)
        self.assertEqual(rows[("ntpgui_holdover_last_result", '{outcome="done"}')], 0)
        self.assertAlmostEqual(rows[("ntpgui_holdover_last_deviation_seconds", "")], 0.0125)
        self.assertEqual(rows[("ntpgui_holdover_last_free_running", "")], 0)
        self.assertNotIn(("ntpgui_holdover_last_drift_ppm", ""), rows)
        self.assertEqual(opsmetrics.holdover_rows({"outcome": "kaputt"}), [])
        self.assertEqual(opsmetrics.holdover_rows(None), [])


class AutocalMetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "autocal.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_off_and_waiting_without_recompute(self):
        with mock.patch.object(autocal, "_evaluate", side_effect=AssertionError("rechnet neu")):
            self.assertEqual(autocal.metrics_state({"gps_autocal": "off"}, file=self.file)["phase"], "off")
            state = autocal.metrics_state({"gps_autocal": "auto"}, file=self.file)
        self.assertEqual(state, {"mode": "auto", "phase": "waiting", "active_changes": 0, "last_change": None})

    def test_stored_decision(self):
        saved = autocal._empty()
        saved["last_decision"] = {"action": "none", "phase": "calibrated", "t": 100.0}
        saved["last_tick"] = 100.0
        saved["changes"] = [{"id": 1, "t": 50.0, "kind": "auto", "old_offset": 0.1, "new_offset": 0.12},
                            {"id": 2, "t": 80.0, "kind": "manual"}]
        autocal.save(saved, self.file)
        with mock.patch.object(autocal, "_evaluate", side_effect=AssertionError("rechnet neu")):
            state = autocal.metrics_state({"gps_autocal": "suggest", "gps_offset": 0.12}, now=200.0, file=self.file)
        self.assertEqual(state["mode"], "suggest")
        self.assertEqual(state["phase"], "calibrated")
        self.assertEqual(state["active_changes"], 1)
        self.assertEqual(state["last_change"], 50.0)
        rows = {(r[0], r[4]): r[1] for r in opsmetrics.autocal_rows(state, autocal.MODE_LABELS, autocal.PHASE_KEYS,
                                                                     0.12)}
        self.assertEqual(rows[("ntpgui_gps_autocal_mode", '{mode="suggest"}')], 1)
        self.assertEqual(rows[("ntpgui_gps_autocal_mode", '{mode="auto"}')], 0)
        self.assertEqual(rows[("ntpgui_gps_autocal_phase", '{phase="calibrated"}')], 1)
        self.assertEqual(sum(v for (n, _l), v in rows.items() if n == "ntpgui_gps_autocal_phase"), 1)
        self.assertEqual(rows[("ntpgui_gps_offset_seconds", "")], 0.12)


class HeartbeatMetricsTest(unittest.TestCase):
    def test_rows(self):
        self.assertEqual([r[1] for r in opsmetrics.heartbeat_rows({"enabled": False, "url": "geheim"})], [0])
        rows = {r[0]: r[1] for r in opsmetrics.heartbeat_rows(
            {"enabled": True, "failures": 4, "last_ok": 1234.6, "last_state": "down", "url": "http://x/geheim"})}
        self.assertEqual(rows, {"ntpgui_heartbeat_enabled": 1, "ntpgui_heartbeat_consecutive_failures": 4,
                                "ntpgui_heartbeat_last_success_timestamp_seconds": 1235,
                                "ntpgui_heartbeat_reported_down": 1})


class RobustnessTest(unittest.TestCase):
    def test_broken_part_does_not_break_metrics(self):
        with mock.patch.object(notify, "metrics_summary", side_effect=RuntimeError("kaputt")), \
                mock.patch("builtins.print"):
            text = test_integrations.full_metrics()
        self.assertNotIn("ntpgui_notify_channels", text)
        self.assertIn("ntpgui_events_total", text)
        self.assertEqual(check_exposition(text), [])


if __name__ == "__main__":
    unittest.main()


class AlertRulesTest(unittest.TestCase):
    """Die Alarmregeln dürfen nicht anschlagen, wo die Dashboard-Seiten bewusst schweigen."""

    @classmethod
    def setUpClass(cls):
        text = (Path(__file__).resolve().parents[1] / "docs" / "prometheus" / "alerts.yml").read_text(encoding="utf-8")
        cls.rules = {}
        for block in text.split("      - alert: ")[1:]:
            name = block.split("\n", 1)[0].strip()
            cls.rules[name] = block

    def expr(self, name):
        return next(l for l in self.rules[name].splitlines() if l.strip().startswith("expr:"))

    def for_(self, name):
        return next(l.split(":", 1)[1].strip() for l in self.rules[name].splitlines() if l.strip().startswith("for:"))

    def test_group_silent_waits_for_listening_and_skips_none(self):
        expr = self.expr("NtpGuiClientGroupSilent")
        self.assertIn('group_id!="none"', expr)
        self.assertIn("ntpgui_clients_listening_seconds > 86400", expr)

    def test_backup_missing_waits_for_first_night(self):
        self.assertNotIn("unless", self.expr("NtpGuiNightlyBackupOld"))
        self.assertIn("unless", self.expr("NtpGuiNightlyBackupMissing"))
        self.assertEqual(self.for_("NtpGuiNightlyBackupMissing"), "26h")

    def test_holdover_result_only_fresh(self):
        self.assertIn("time() - ntpgui_holdover_last_end_timestamp_seconds", self.expr("NtpGuiHoldoverTestFailed"))
