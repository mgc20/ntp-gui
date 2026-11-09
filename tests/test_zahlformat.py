"""1.6.1: Zahlen in Nutzertexten des Servers – deutsch wie im Dashboard (Komma, „−“, keine Nullen am Ende).

Anlass: „Das GPS fließt in die Zeit ein (Abweichung 1.4 ms).“ – Dezimalpunkt in einem Hinweis der Übersicht.
Alle Hinweise, Ereignistitel und Benachrichtigungstexte formatieren Zahlen über app/numfmt.py; diese Tests
erzwingen das Format für die Hinweise (insights) und die Format-Helfer der Module.
"""

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import autocal  # noqa: E402
import clientinfo  # noqa: E402
import gnssguard  # noqa: E402
import gpsquality  # noqa: E402
import hardware  # noqa: E402
import holdover  # noqa: E402
import insights  # noqa: E402
import numfmt  # noqa: E402
import statewatch  # noqa: E402

UNIT = r"(?:ns|µs|ms|s|min|h|ppm|ppb|%|dB|dB-Hz|Tage|Tagen|Impulse/s)"
# Dezimalpunkt vor einer Einheit („1.4 ms“), Bindestrich als Minus („-3 ms“), Nullen am Ende („1,50 s“).
FORBIDDEN = [
    (re.compile(rf"\d\.\d+\s?{UNIT}(?![\w-])"), "Dezimalpunkt"),
    (re.compile(rf"(?:^|[\s(=±→≈])-\d"), "Bindestrich statt −"),
    (re.compile(rf"\d,\d*0\s?{UNIT}(?![\w-])"), "Null am Ende"),
    (re.compile(r"[−+]0(?:,0+)?\s?" + UNIT + r"(?![\w-])"), "Vorzeichen vor 0"),
]


def problems(text):
    return [f"{label}: {m.group(0)!r} in {text!r}" for pattern, label in FORBIDDEN
            for m in pattern.finditer(text or "")]


def status_with(**over):
    status = {
        "chrony_running": True,
        "tracking": {"synchronised": True, "stratum": 1, "system_time_offset": -1.5e-6, "ref_name": "GPS"},
        "sources": [
            {"mode": "#", "name": "GPS", "state": "*", "select_state": "best", "offset": 0.0014, "reach": 255},
            {"mode": "^", "name": "192.0.2.1", "hostname": "ntp.example", "state": "+", "reach": 255},
        ],
        "system": {"clock_control": True},
        "gps": {"enabled": True, "running": True, "has_fix": True},
        "ui": {"auth": {"enabled": True}, "storage": {"persistent": True}},
        "client_count": 2,
    }
    status.update(over)
    return status


class NumberHelperTest(unittest.TestCase):
    def test_number(self):
        self.assertEqual(numfmt.number(1.4, 1), "1,4")
        self.assertEqual(numfmt.number(-1.4, 1), "−1,4")
        self.assertEqual(numfmt.number(1.50, 2), "1,5")
        self.assertEqual(numfmt.number(2.0, 1), "2")
        self.assertEqual(numfmt.number(-0.04, 1), "0")
        self.assertEqual(numfmt.number(-0.04, 1, signed=True), "0")
        self.assertEqual(numfmt.number(0.25, 1, signed=True), "+0,3")
        self.assertEqual(numfmt.number(12345.678, 1), "12.345,7")
        self.assertEqual(numfmt.number(12345.678, 1, group=False), "12345,7")
        self.assertEqual(numfmt.number(None), "–")
        self.assertEqual(numfmt.number(float("nan")), "–")
        self.assertEqual(numfmt.number(29.96, 1, floor=True), "29,9")

    def test_seconds_like_frontend(self):
        # Dieselben Fälle wie fmtSeconds in util.js (tests/test_gui_bausteine.py prüft das Frontend).
        self.assertEqual(numfmt.seconds(0.0014, 2), "1,4 ms")
        self.assertEqual(numfmt.seconds(-0.0014, 2), "−1,4 ms")
        self.assertEqual(numfmt.seconds(-1.5e-6), "−1,5 µs")
        self.assertEqual(numfmt.seconds(2.5e-7), "250 ns")
        self.assertEqual(numfmt.seconds(0.99996e-3), "1 ms")
        self.assertEqual(numfmt.seconds(1.5), "1,5 s")
        self.assertEqual(numfmt.seconds(1234.5, 1), "1234,5 s")
        self.assertEqual(numfmt.seconds(0), "0 s")
        self.assertEqual(numfmt.seconds(0.0123, 3, signed=True), "+12,3 ms")

    def test_module_helpers(self):
        texts = [
            clientinfo.fmt_offset(1.5), clientinfo.fmt_offset(-0.0042), clientinfo.fmt_offset(-1.25),
            clientinfo.fmt_offset(-1.5 * 86400), clientinfo._fmt_seconds(0.5), clientinfo._fmt_seconds(5400),
            autocal._ms(0.0125), autocal._signed_ms(-0.002), autocal._hours(6 * 3600), autocal._off(-0.02),
            autocal._off(0.145),
            gnssguard.fmt_ms(-0.005), gpsquality.fmt_ms(-0.005), gpsquality.fmt_ms(0.0102),
            holdover.fmt_ms(0.005), holdover.fmt_ms(0.0004),
            hardware._fmt_rate(0.5), hardware._fmt_rate(2.0),
        ]
        for text in texts:
            self.assertEqual(problems(text), [], text)
        self.assertEqual(clientinfo.fmt_offset(1.5), "+1,5 s")
        self.assertEqual(autocal._off(-0.02), "−0,02")
        self.assertEqual(hardware._fmt_rate(0.5), "0,5 Impulse/s")
        self.assertEqual(gpsquality.fmt_ms(-0.005), "−5 ms")


class InsightTextTest(unittest.TestCase):
    """Alle Insight-Texte, die Zahlen enthalten können, mit typischen (auch negativen) Werten."""

    def all_texts(self):
        out = []
        cfg = {"gps_refid": "GPS", "gps_autocal": "suggest", "ntp_minsources": 3}
        scenarios = [
            status_with(),
            status_with(sources=[{"mode": "#", "name": "GPS", "select_state": "falseticker", "offset": -0.0254},
                                 {"mode": "^", "name": "192.0.2.1", "state": "*", "reach": 255}]),
            status_with(sources=[{"mode": "#", "name": "GPS", "select_state": "combined", "offset": 0.0251},
                                 {"mode": "^", "name": "192.0.2.1", "state": "*", "reach": 255}]),
            status_with(tracking={"synchronised": True, "stratum": 2, "system_time_offset": 1.25, "ref_name": "x"}),
            status_with(tracking={"synchronised": False, "local_reference": True, "stratum": 10}),
            status_with(gps={"enabled": True, "running": True, "has_fix": False, "satellites_seen": 7,
                             "satellites_used": 2},
                        gps_summary={"last_fix_s": 4000.0}),
        ]
        for status in scenarios:
            for item in insights.build(status, cfg):
                out.append(item)
        for days in (-2.0, 3.5, 0.4):
            out += insights.nts_server_insights({"enabled": True, "cert_exists": True, "key_exists": True,
                                                 "cert_readable": True, "name": "", "days_left": days})
        out += holdover.insights({"active": True, "run": {"remaining_s": 5400.0, "deviation_ms": 5.0}})
        out += holdover.insights({"active": True, "run": {"remaining_s": 60.0, "deviation_ms": -0.25}})
        return out

    def test_gps_used_text_has_comma(self):
        items = insights.build(status_with(), {"gps_refid": "GPS"})
        used = next(i for i in items if i["key"] == "gps_used")
        self.assertEqual(used["text"], "Das GPS fließt in die Zeit ein (Abweichung 1,4 ms).")
        synced = next(i for i in items if i["key"] == "synced")
        self.assertIn("Abweichung −1,5 µs", synced["text"])

    def test_all_insight_texts_german(self):
        found = []
        items = self.all_texts()
        self.assertGreater(len(items), 8)
        for item in items:
            found += problems(item.get("title", "")) + problems(item.get("text", ""))
        self.assertEqual(found, [])

    def test_event_title_default_format(self):
        sent = []
        watch = statewatch.StateWatcher(lambda kind, level, title, data=None, **_kw: sent.append(title))
        for count in (1, 2):
            watch.clients({"192.0.2.5": {"measurable": True, "offset": -0.0042, "count": count}}, 1)
        self.assertTrue(sent)
        for title in sent:
            self.assertEqual(problems(title), [], title)
        self.assertIn("−4,2 ms", sent[0])


if __name__ == "__main__":
    unittest.main()
