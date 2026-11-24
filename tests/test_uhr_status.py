"""Studiouhr B3 und B5: Statuszeile (PTP, Holdover), Kachel und das Prüfbild test=sync.

Server: clock_status bzw. /api/v1/time nennen den Zustand von PTP nur als festen Wert und einen Holdover als
Wahrheitswert mit Dauer. Ohne Anmeldung (public=True) enthält die Antwort nur Schlüssel einer Allowlist, und kein Wert
trägt einen Namen, eine Adresse oder eine Kennung – geprüft mit präparierten Daten von chrony und ptp4l, die genau
solche Angaben enthalten.

Uhr: Die reinen Rechnungen stehen in app/static/js/clockkit.js und laufen hier mit Node – Marken der Statuszeile,
Dauer des Holdovers, Sekundenblitz (Wechsel genau zur vollen Sekunde, höchstens einer je Sekunde), Start nur aus der
Adresse und nie bei „weniger Bewegung“. Dazu: derselbe Parameter in Schema, Server-Allowlist, Link-Baukasten und
Doku, die Texte in beiden Sprachen und Regeln für clock.js, clock.css und clock.html.
"""

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import clockprofiles  # noqa: E402
import server  # noqa: E402

# Präparierte Angaben, die nie in der öffentlichen Antwort stehen dürfen.
SECRET_HOST = "gm-regie-7.studio.example"
SECRET_IP4 = "198.51.100.44"
SECRET_IP6 = "2001:db8:17::beef"
SECRET_GM = "001b21.fffe.8a4c7e"
SECRET_PORT = "001b21.fffe.8a4c7e-1"
SECRET_IFACE = "enp3s0f1"
SECRETS = (SECRET_HOST, SECRET_IP4, SECRET_IP6, SECRET_GM, SECRET_PORT, SECRET_IFACE, "8a4c7e", "regie", "studio.example")

TRACKING = {"synchronised": True, "stratum": 2, "ref_id": "C633642C", "ref_name": SECRET_HOST, "ref_time": 1_794_000_000.0,
            "root_delay": 0.001, "root_dispersion": 0.0001, "system_time_offset": 0.00001, "leap_status": "Normal",
            "local_reference": False}
SOURCES = [{"name": SECRET_IP4, "state": "*", "mode": "^", "reach": 0o377},
           {"name": SECRET_IP6, "state": "+", "mode": "^", "reach": 0o377}]
PTP_STATUS = {"enabled": True, "running": True, "interface": SECRET_IFACE, "mode": "slave", "transport": "UDPv4",
              "domain": "17", "clockIdentity": SECRET_GM, "grandmasterIdentity": SECRET_GM, "gmIdentity": SECRET_GM,
              "parentPortIdentity": SECRET_PORT, "portIdentity": SECRET_PORT, "portState": "SLAVE",
              "port_state_label": f"Slave an {SECRET_HOST}", "stepsRemoved": 1, "offset_ns": 12,
              "log": [f"selected best master clock {SECRET_GM} on {SECRET_IFACE}"]}

# Schlüssel der öffentlichen Antwort und was ihr Wert sein darf.
LEVELS = {"good", "warn", "crit"}
KINDS = {None, "GPS", "GPS + PPS", "GNSS", "PTP", "DCF77", "NTP", "Referenzuhr", "lokal (Inselbetrieb)"}
LEAPS = {None, "Normal", "Insert second", "Delete second", "Not synchronised"}
PUBLIC_VALUES = {
    "t1": lambda v: isinstance(v, float),
    "t2": lambda v: isinstance(v, float),
    "public": lambda v: v is True,
    "source": lambda v: v is None,
    "synchronised": lambda v: isinstance(v, bool),
    "running": lambda v: isinstance(v, bool),
    "level": lambda v: v in LEVELS,
    "accuracy": lambda v: v is None or isinstance(v, float),
    "stratum": lambda v: v is None or (isinstance(v, int) and 0 <= v <= 16),
    "leap": lambda v: v in LEAPS,
    "leap_next": lambda v: v is None or bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v)),
    "tai_utc": lambda v: v is None or (isinstance(v, int) and not isinstance(v, bool) and 10 <= v <= 100),
    "source_kind": lambda v: v in KINDS,
    "zone": lambda v: v is None or bool(re.fullmatch(r"[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+){0,2}", v)),
    "profiles_rev": lambda v: bool(re.fullmatch(r"[0-9a-f]{12}", v)),
    "ptp_state": lambda v: v in server.PTP_STATES,
    "holdover": lambda v: v is None or isinstance(v, bool),
    "holdover_seconds": lambda v: v is None or (isinstance(v, int) and not isinstance(v, bool) and v >= 0),
    "signal": lambda v: v in ("off", "on_air", "rec"),
    "signal_rev": lambda v: bool(re.fullmatch(r"[0-9a-f]{12}", v)),
}


def run_node(code: str):
    mods = {name: json.dumps((JS / f"{name}.js").as_uri()) for name in ("clockkit", "clocklink")}
    script = f"import * as k from {mods['clockkit']};\nimport * as l from {mods['clocklink']};\n{code}"
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class ExtraState:
    """Stand von note_clock_extra für einen Test zurücksetzen und danach wiederherstellen."""

    def __enter__(self):
        self.saved = dict(server._CLOCK_EXTRA)
        server._CLOCK_EXTRA.update(t=None, ptp_state="unknown", lost=None, since=None, lost_t=None)
        return self

    def __exit__(self, *exc):
        server._CLOCK_EXTRA.update(self.saved)


class PtpZustandTest(unittest.TestCase):
    def test_nur_feste_werte(self):
        cases = {"SLAVE": "locked", "MASTER": "master", "GRAND_MASTER": "master", "LISTENING": "acquiring",
                 "UNCALIBRATED": "acquiring", "PRE_MASTER": "acquiring", "INITIALIZING": "acquiring",
                 "PASSIVE": "passive", "FAULTY": "fault", "DISABLED": "fault"}
        for port, want in cases.items():
            with self.subTest(port=port):
                self.assertEqual(server.ptp_state({**PTP_STATUS, "portState": port}), want)
        self.assertEqual(server.ptp_state({"enabled": False, "running": False}), "off")
        self.assertEqual(server.ptp_state({**PTP_STATUS, "running": False}), "down")
        self.assertEqual(set(cases.values()) | {"off", "down", "unknown"}, set(server.PTP_STATES))

    def test_fremde_werte_werden_unbekannt(self):
        for port in (None, "", "slave", "SLAVE ", SECRET_GM, SECRET_IFACE, f"SLAVE {SECRET_GM}", 7, ["SLAVE"], {"a": 1}):
            with self.subTest(port=port):
                self.assertEqual(server.ptp_state({**PTP_STATUS, "portState": port}), "unknown")
        for status in (None, "", [], "SLAVE", 3):
            self.assertEqual(server.ptp_state(status), "unknown")

    def test_ergebnis_ist_immer_ein_fester_wert(self):
        for port in ("SLAVE", SECRET_GM, SECRET_HOST, SECRET_IFACE, None):
            for running in (True, False):
                state = server.ptp_state({**PTP_STATUS, "portState": port, "running": running})
                self.assertIn(state, server.PTP_STATES)
                for secret in SECRETS:
                    self.assertNotIn(secret, state)


class HoldoverTest(unittest.TestCase):
    def test_referenz_verloren(self):
        lost = server.reference_lost
        self.assertFalse(lost(TRACKING, SOURCES), "Quelle ausgewählt: kein Holdover")
        unselected = [{**SOURCES[0], "state": "?"}, {**SOURCES[1], "state": "-"}]
        self.assertTrue(lost(TRACKING, unselected), "chrony nennt noch eine Referenz, hat aber keine Quelle ausgewählt")
        self.assertTrue(lost({**TRACKING, "synchronised": False, "local_reference": True}, SOURCES), "Inselbetrieb")
        self.assertTrue(lost(TRACKING, SOURCES, test_active=True), "Holdover-Test hat die Quellen abgewählt")
        self.assertFalse(lost({**TRACKING, "synchronised": False}, unselected), "nie synchron war kein Holdover")
        self.assertIs(lost({**TRACKING, "synchronised": False}, unselected), False)
        # Keine Aussage ist kein „nein“: chronyc antwortete nicht (kein tracking, keine Quellenliste).
        self.assertIsNone(lost({}, unselected), "chronyd antwortet nicht")
        self.assertIsNone(lost(None, None))
        self.assertIsNone(lost(TRACKING, []), "ohne Quellenliste keine Aussage")
        self.assertIsNone(lost(TRACKING, None))
        self.assertIsNone(lost(TRACKING, "?"))
        self.assertIsNone(lost(None, None, was_lost=True))
        self.assertIs(lost(TRACKING, None, test_active=True), True, "der Holdover-Test braucht keine Quellenliste")
        # Ein laufender Holdover endet erst mit einer ausgewählten Quelle – auch wenn chrony die Referenz aufgibt.
        gone = {**TRACKING, "synchronised": False, "leap_status": "Not synchronised"}
        self.assertIs(lost(gone, unselected, was_lost=True), True)
        self.assertIs(lost(gone, unselected, was_lost=False), False)
        self.assertIs(lost(gone, SOURCES, was_lost=True), False, "Quelle wieder ausgewählt")
        self.assertIs(lost(TRACKING, SOURCES, was_lost=True), False)

    def test_ohne_antwort_bleibt_der_letzte_stand(self):
        unselected = [{**SOURCES[0], "state": "?"}]
        wall = TRACKING["ref_time"] + 4000.0
        for tracking, sources in ((TRACKING, []), (None, None), ({}, unselected), (TRACKING, None)):
            with self.subTest(tracking=bool(tracking), sources=sources), ExtraState(), \
                    mock.patch.object(server.ptp, "status", return_value=dict(PTP_STATUS)), \
                    mock.patch.object(server.ptp, "enabled", return_value=True), \
                    mock.patch.object(server.holdover.TEST, "running", return_value=False):
                server.note_clock_extra(TRACKING, unselected, mono=1000.0, wall=wall)
                self.assertEqual(server.clock_extra(mono=1000.0)["holdover_seconds"], 4000)
                server.note_clock_extra(tracking, sources, mono=1010.0, wall=wall + 10.0)
                self.assertEqual(server.clock_extra(mono=1010.0),
                                 {"ptp_state": "locked", "holdover": True, "holdover_seconds": 4010},
                                 "eine Messung ohne Antwort beendet den Holdover nicht")
                server.note_clock_extra(TRACKING, unselected, mono=1020.0, wall=wall + 20.0)
                self.assertEqual(server.clock_extra(mono=1020.0)["holdover_seconds"], 4020, "der Beginn bleibt")
                # Bleibt die Antwort aus, wird der Stand unbekannt (null) – nie ein festes „kein Holdover“.
                late = 1020.0 + server.CLOCK_EXTRA_MAX_AGE + 1.0
                server.note_clock_extra(tracking, sources, mono=late, wall=wall + late)
                self.assertEqual(server.clock_extra(mono=late), {"ptp_state": "locked", "holdover": None, "holdover_seconds": None})
        # Ebenso umgekehrt: Aus „kein Holdover“ wird ohne Antwort kein Holdover und kein Wechsel.
        with ExtraState(), mock.patch.object(server.ptp, "status", return_value=dict(PTP_STATUS)), \
                mock.patch.object(server.ptp, "enabled", return_value=True), \
                mock.patch.object(server.holdover.TEST, "running", return_value=False):
            server.note_clock_extra(TRACKING, [], mono=5.0, wall=wall)
            self.assertIsNone(server.clock_extra(mono=5.0)["holdover"], "nie etwas gesehen: unbekannt")
            server.note_clock_extra(TRACKING, SOURCES, mono=10.0, wall=wall)
            server.note_clock_extra(TRACKING, [], mono=20.0, wall=wall)
            self.assertIs(server.clock_extra(mono=20.0)["holdover"], False)

    def test_holdover_endet_erst_mit_ausgewaehlter_quelle(self):
        unselected = [{**SOURCES[0], "state": "?"}]
        gone = {"synchronised": False, "local_reference": False, "leap_status": "Not synchronised", "stratum": 0}
        wall = TRACKING["ref_time"] + 4000.0
        with ExtraState(), mock.patch.object(server.ptp, "status", return_value=dict(PTP_STATUS)), \
                mock.patch.object(server.ptp, "enabled", return_value=True), \
                mock.patch.object(server.holdover.TEST, "running", return_value=False):
            # Seit dem Start nie synchron: kein Holdover.
            server.note_clock_extra(gone, unselected, mono=900.0, wall=wall - 100.0)
            self.assertEqual(server.clock_extra(mono=900.0)["holdover"], False)
            server.note_clock_extra(TRACKING, SOURCES, mono=950.0, wall=wall - 50.0)
            server.note_clock_extra(TRACKING, unselected, mono=1000.0, wall=wall)
            self.assertEqual(server.clock_extra(mono=1000.0)["holdover_seconds"], 4000)
            # chrony gibt die Referenz ganz auf: Die Uhr läuft weiter ohne Referenz, die Dauer zählt weiter.
            server.note_clock_extra(gone, unselected, mono=1060.0, wall=wall + 60.0)
            self.assertEqual(server.clock_extra(mono=1060.0), {"ptp_state": "locked", "holdover": True, "holdover_seconds": 4060})
            status = server.clock_status(gone, {}, server.clock_extra(mono=1060.0))
            self.assertEqual((status["holdover"], status["holdover_seconds"], status["synchronised"]), (True, 4060, False))
            server.note_clock_extra(gone, unselected, mono=1120.0, wall=wall + 120.0)
            self.assertEqual(server.clock_extra(mono=1120.0)["holdover_seconds"], 4120)
            # Erst eine ausgewählte Quelle beendet ihn; danach ist „nicht synchronisiert“ wieder kein Holdover.
            server.note_clock_extra(TRACKING, SOURCES, mono=1180.0, wall=wall + 180.0)
            self.assertEqual(server.clock_extra(mono=1180.0), {"ptp_state": "locked", "holdover": False, "holdover_seconds": None})
            server.note_clock_extra(gone, unselected, mono=1240.0, wall=wall + 240.0)
            self.assertEqual(server.clock_extra(mono=1240.0)["holdover"], False)

    def test_beginn_ist_die_letzte_korrektur(self):
        unselected = [{**SOURCES[0], "state": "?"}]
        with ExtraState(), mock.patch.object(server.ptp, "status", return_value=dict(PTP_STATUS)), \
                mock.patch.object(server.ptp, "enabled", return_value=True), \
                mock.patch.object(server.holdover.TEST, "running", return_value=False):
            wall = TRACKING["ref_time"] + 185.0
            server.note_clock_extra(TRACKING, unselected, mono=1000.0, wall=wall)
            self.assertEqual(server.clock_extra(mono=1000.0),
                             {"ptp_state": "locked", "holdover": True, "holdover_seconds": 185})
            # Der Beginn bleibt stehen, auch wenn chrony die Angabe später ändert; gezählt wird monoton.
            server.note_clock_extra({**TRACKING, "ref_time": wall}, unselected, mono=1060.0, wall=wall + 60.0)
            self.assertEqual(server.clock_extra(mono=1062.5)["holdover_seconds"], 247)
            # Quelle wieder ausgewählt: vorbei, die Dauer verschwindet.
            server.note_clock_extra(TRACKING, SOURCES, mono=1070.0, wall=wall + 70.0)
            self.assertEqual(server.clock_extra(mono=1070.0),
                             {"ptp_state": "locked", "holdover": False, "holdover_seconds": None})

    def test_inselbetrieb_zaehlt_ab_der_ersten_beobachtung(self):
        island = {**TRACKING, "synchronised": False, "local_reference": True, "ref_time": 12.0}
        with ExtraState(), mock.patch.object(server.ptp, "status", return_value={"enabled": False, "running": False}), \
                mock.patch.object(server.ptp, "enabled", return_value=False), \
                mock.patch.object(server.holdover.TEST, "running", return_value=False):
            server.note_clock_extra(island, SOURCES, mono=50.0, wall=2_000_000_000.0)
            self.assertEqual(server.clock_extra(mono=50.0), {"ptp_state": "off", "holdover": True, "holdover_seconds": 0})
            self.assertEqual(server.clock_extra(mono=170.9)["holdover_seconds"], 120)

    def test_unsinnige_letzte_korrektur_zaehlt_nicht(self):
        unselected = [{**SOURCES[0], "state": "?"}]
        with ExtraState(), mock.patch.object(server.ptp, "status", return_value=dict(PTP_STATUS)), \
                mock.patch.object(server.ptp, "enabled", return_value=True), \
                mock.patch.object(server.holdover.TEST, "running", return_value=False):
            for ref in (0.0, None, "gestern", TRACKING["ref_time"] + 10_000.0, True):
                server._CLOCK_EXTRA.update(t=None, lost=None, since=None, lost_t=None)
                server.note_clock_extra({**TRACKING, "ref_time": ref}, unselected, mono=10.0, wall=TRACKING["ref_time"])
                with self.subTest(ref=ref):
                    self.assertEqual(server.clock_extra(mono=10.0)["holdover_seconds"], 0)

    def test_alte_beobachtung_gilt_als_unbekannt(self):
        with ExtraState(), mock.patch.object(server.ptp, "status", return_value=dict(PTP_STATUS)), \
                mock.patch.object(server.ptp, "enabled", return_value=True), \
                mock.patch.object(server.holdover.TEST, "running", return_value=False):
            self.assertEqual(server.clock_extra(mono=5.0), {"ptp_state": "unknown", "holdover": None, "holdover_seconds": None},
                             "nie beobachtet")
            server.note_clock_extra(TRACKING, SOURCES, mono=100.0, wall=TRACKING["ref_time"])
            self.assertEqual(server.clock_extra(mono=100.0 + server.CLOCK_EXTRA_MAX_AGE)["holdover"], False)
            stale = server.clock_extra(mono=101.0 + server.CLOCK_EXTRA_MAX_AGE)
            self.assertEqual(stale, {"ptp_state": "unknown", "holdover": None, "holdover_seconds": None})
            # Langes Messintervall (bis 600 s): Der Stand gilt drei Messungen lang.
            self.assertEqual(server.clock_extra(mono=101.0 + server.CLOCK_EXTRA_MAX_AGE, interval=600.0)["holdover"], False)
            self.assertIsNone(server.clock_extra(mono=1901.0, interval=600.0)["holdover"])
            for interval in (None, "600", -5, 0, True, 1e9):
                self.assertIsNone(server.clock_extra(mono=101.0 + server.CLOCK_EXTRA_MAX_AGE, interval=interval)["holdover"])
            with mock.patch.object(server.ptp, "enabled", return_value=False):
                self.assertEqual(server.clock_extra(mono=9999.0)["ptp_state"], "off", "ausgeschaltet steht sofort da")

    def test_beobachtung_wirft_nie(self):
        with ExtraState(), mock.patch.object(server.ptp, "status", side_effect=RuntimeError("pmc fehlt")), \
                mock.patch.object(server.ptp, "enabled", side_effect=RuntimeError("kaputt")), \
                mock.patch.object(server.holdover.TEST, "running", side_effect=RuntimeError("kaputt")):
            server.note_clock_extra(TRACKING, SOURCES, mono=1.0, wall=TRACKING["ref_time"])
            server.note_clock_extra(None, None, mono=2.0, wall=TRACKING["ref_time"])
            self.assertEqual(server.clock_extra(mono=2.0), {"ptp_state": "unknown", "holdover": False, "holdover_seconds": None},
                             "ohne Antwort gilt der letzte Stand")
            with mock.patch("builtins.print"):
                server.note_clock_extra("kein dict", object(), mono=3.0, wall=TRACKING["ref_time"])
                server.note_clock_extra(TRACKING, [None, "x", 3], mono=4.0, wall=TRACKING["ref_time"])

    def test_messthread_meldet_den_zustand(self):
        source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        collector = source[source.index("def collector()"):source.index("def collector()") + 2500]
        self.assertIn("note_clock_extra(tracking, sources)", collector)
        payload = source[source.index("def time_payload("):source.index("def profile_payload(")]
        self.assertIn('clock_status(tracking, cfg, clock_extra(interval=cfg.get("history_interval")))', payload)
        for forbidden in ("ptp.status(", "chrony.sources(", "chrony.detailed_sources(", "subprocess"):
            self.assertNotIn(forbidden, payload, "/api/v1/time startet für den Zustand keinen Prozess")
        extra = source[source.index("def clock_extra("):source.index("def clock_status(")]
        self.assertNotIn("ptp.status(", extra)


class ClockStatusTest(unittest.TestCase):
    def test_felder_und_standard(self):
        out = server.clock_status(TRACKING)
        self.assertEqual((out["ptp_state"], out["holdover"], out["holdover_seconds"]), ("unknown", None, None))
        out = server.clock_status(TRACKING, {}, {"ptp_state": "locked", "holdover": True, "holdover_seconds": 185})
        self.assertEqual((out["ptp_state"], out["holdover"], out["holdover_seconds"]), ("locked", True, 185))
        out = server.clock_status(TRACKING, {}, {"ptp_state": "master", "holdover": False, "holdover_seconds": 185})
        self.assertEqual((out["holdover"], out["holdover_seconds"]), (False, None), "Dauer nur im Holdover")
        out = server.clock_status({}, {}, {"ptp_state": "down", "holdover": True, "holdover_seconds": 5})
        self.assertEqual((out["ptp_state"], out["holdover"], out["holdover_seconds"]), ("down", None, None),
                         "chronyd antwortet nicht: keine Aussage über einen Holdover")

    def test_nur_feste_werte_aus_extra(self):
        for state in (SECRET_GM, SECRET_IFACE, "LOCKED", "locked ", "", None, 7, ["locked"], {"x": 1}):
            with self.subTest(state=state):
                self.assertEqual(server.clock_status(TRACKING, {}, {"ptp_state": state})["ptp_state"], "unknown")
        for hold in (SECRET_HOST, "true", 1, 0, [True], None):
            with self.subTest(hold=hold):
                out = server.clock_status(TRACKING, {}, {"holdover": hold, "holdover_seconds": 60})
                self.assertEqual((out["holdover"], out["holdover_seconds"]), (None, None))
        for seconds in (SECRET_IP4, "60", -1, None, True, float("inf"), float("nan"), 1e12, [60]):
            with self.subTest(seconds=seconds):
                out = server.clock_status(TRACKING, {}, {"holdover": True, "holdover_seconds": seconds})
                self.assertEqual((out["holdover"], out["holdover_seconds"]), (True, None))
        self.assertEqual(server.clock_status(TRACKING, {}, {"holdover": True, "holdover_seconds": 61.9})["holdover_seconds"], 61)
        for extra in ("locked", ["locked"], 5):
            self.assertEqual(server.clock_status(TRACKING, {}, extra)["ptp_state"], "unknown")


class OeffentlicheAntwortTest(unittest.TestCase):
    """Akzeptanz B: /api/v1/time ohne Login enthält keine Namen, IPs oder IDs – auch nicht im PTP-Feld."""

    def payload(self, tracking, sources, ptp_status, public=True, cfg=None):
        cfg = {"gps_refid": "GPS", "ptp_interface": SECRET_IFACE, "ptp_enable": True,
               "clock_profiles": {"regie": {"title": SECRET_HOST, "params": {"label": "geheim"}}}, **(cfg or {})}
        with ExtraState(), mock.patch.object(server.ptp, "status", return_value=ptp_status), \
                mock.patch.object(server.ptp, "enabled", return_value=bool(ptp_status.get("enabled"))), \
                mock.patch.object(server.holdover.TEST, "running", return_value=False), \
                mock.patch.object(server, "_clock_tracking", return_value=tracking), \
                mock.patch.object(server.settings, "values", return_value=cfg), \
                mock.patch.object(server, "_clock_zone", return_value="Europe/Berlin"), \
                mock.patch.object(server.leap, "status", return_value={"available": True, "next_leap_date": "2027-01-01",
                                                                        "path": f"/srv/{SECRET_HOST}/leap.list"}):
            server.note_clock_extra(tracking, sources)
            return server.time_payload(1_794_000_200.5, public=public)

    def check_public(self, payload):
        self.assertEqual(set(payload), set(PUBLIC_VALUES), "nur Schlüssel der Allowlist")
        for key, allowed in PUBLIC_VALUES.items():
            with self.subTest(key=key):
                self.assertTrue(allowed(payload[key]), f"{key} = {payload[key]!r}")
        text = json.dumps(payload, ensure_ascii=False)
        for secret in SECRETS:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, text)
        # Nichts, was wie eine Adresse oder Kennung aussieht: IPv4, IPv6, MAC bzw. EUI-64, Clock-Identity.
        strings = [v for v in payload.values() if isinstance(v, str)]
        for value in strings:
            with self.subTest(value=value):
                self.assertIsNone(re.search(r"[0-9]{1,3}(\.[0-9]{1,3}){3}", value), "IPv4")
                self.assertIsNone(re.search(r"[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}", value), "MAC")
                self.assertIsNone(re.search(r"[0-9a-fA-F]{6}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{6}", value), "Clock-Identity")
                self.assertIsNone(re.search(r"[0-9a-fA-F]{1,4}(:[0-9a-fA-F]{0,4}){2,}", value), "IPv6")

    def test_allowlist_der_schluessel_und_werte(self):
        payload = self.payload(TRACKING, SOURCES, PTP_STATUS)
        self.check_public(payload)
        self.assertEqual((payload["ptp_state"], payload["holdover"], payload["source_kind"]), ("locked", False, "NTP"))

    def test_jeder_zustand_von_ptp_bleibt_ein_fester_wert(self):
        ports = ["SLAVE", "MASTER", "GRAND_MASTER", "LISTENING", "UNCALIBRATED", "PASSIVE", "FAULTY", "DISABLED",
                 "PRE_MASTER", "INITIALIZING", SECRET_GM, SECRET_PORT, SECRET_IFACE, f"SLAVE on {SECRET_IFACE}", None]
        for port in ports:
            for running in (True, False):
                with self.subTest(port=port, running=running):
                    self.check_public(self.payload(TRACKING, SOURCES, {**PTP_STATUS, "portState": port, "running": running}))
        self.check_public(self.payload(TRACKING, SOURCES, {"enabled": False, "running": False, "interface": SECRET_IFACE}))

    def test_holdover_und_refclock_mit_eigenem_namen(self):
        unselected = [{**SOURCES[0], "state": "?"}, {**SOURCES[1], "state": "x"}]
        payload = self.payload(TRACKING, unselected, PTP_STATUS)
        self.check_public(payload)
        self.assertIs(payload["holdover"], True)
        self.assertIsInstance(payload["holdover_seconds"], int)
        # Stratum 1 mit eigener Refid (eine Einstellung): nur die Art, nie der Name.
        own = {**TRACKING, "stratum": 1, "ref_name": "REGIE", "ref_id": "52454749"}
        payload = self.payload(own, [{"name": "REGIE", "state": "*", "mode": "#"}], PTP_STATUS, cfg={"gps_refid": "GPS"})
        self.check_public(payload)
        self.assertEqual(payload["source_kind"], "Referenzuhr")
        island = {**TRACKING, "synchronised": False, "local_reference": True, "stratum": 10, "ref_name": SECRET_HOST}
        payload = self.payload(island, SOURCES, {**PTP_STATUS, "portState": "MASTER"})
        self.check_public(payload)
        self.assertEqual((payload["ptp_state"], payload["holdover"]), ("master", True))
        self.check_public(self.payload({}, [], {**PTP_STATUS, "running": False}))

    def test_mit_anmeldung_kommt_nur_der_quellenname_dazu(self):
        payload = self.payload(TRACKING, SOURCES, PTP_STATUS, public=False)
        self.assertEqual(set(payload), set(PUBLIC_VALUES))
        self.assertEqual(payload["source"], SECRET_HOST)
        self.assertIs(payload["public"], False)
        rest = json.dumps({k: v for k, v in payload.items() if k != "source"}, ensure_ascii=False)
        for secret in SECRETS:
            self.assertNotIn(secret, rest, "auch angemeldet keine Kennung von PTP und keine Schnittstelle")

    def test_api_beschreibung_nennt_die_felder(self):
        source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        block = source[source.index('apiv1.endpoint("GET", "/time"'):source.index('apiv1.endpoint("GET", "/clock/profile"')]
        for field in ("ptp_state", "holdover", "holdover_seconds"):
            self.assertIn(f'"{field}"', block)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class StatuszeileTest(unittest.TestCase):
    def test_marken_nur_aus_festen_werten(self):
        out = run_node("""
          const c = (s) => k.statusChips(s);
          console.log(JSON.stringify({
            states: k.PTP_STATES, shown: Object.keys(k.PTP_SHOWN),
            all: k.PTP_STATES.map((s) => c({ ptp_state: s }).ptp),
            bad: ["LOCKED", "locked ", "<b>locked</b>", "__proto__", "constructor", "toString", "", null, 7, ["locked"], { a: 1 },
              "001b21.fffe.8a4c7e"].map((s) => c({ ptp_state: s }).ptp),
            hold: [true, false, null, "true", 1, undefined].map((h) => c({ holdover: h, holdover_seconds: 185 }).holdover),
            noSeconds: c({ holdover: true, holdover_seconds: null }).holdover,
            textSeconds: c({ holdover: true, holdover_seconds: "<img>" }).holdover,
            empty: [c(null), c(undefined), c("x"), c(7)],
            icons: Object.values(k.PTP_SHOWN).map((v) => v.icon).concat([k.HOLDOVER_ICON]),
          }));
        """)
        self.assertEqual(out["states"], list(server.PTP_STATES), "Uhr und Server kennen dieselben Zustände")
        self.assertEqual(sorted(out["shown"]), sorted(set(server.PTP_STATES) - {"off", "unknown"}))
        shown = {entry["state"]: entry for entry in out["all"] if entry}
        self.assertEqual(sorted(shown), sorted(out["shown"]), "off und unknown zeigen nichts")
        self.assertEqual({s: e["level"] for s, e in shown.items()},
                         {"master": "good", "locked": "good", "acquiring": "warn", "passive": "info", "fault": "crit", "down": "crit"})
        self.assertEqual(out["bad"], [None] * 12, "fremde Werte zeigen nichts")
        self.assertEqual(out["hold"], [{"icon": "H", "span": "3 min"}, None, None, None, None, None])
        self.assertEqual(out["noSeconds"], {"icon": "H", "span": ""})
        self.assertEqual(out["textSeconds"], {"icon": "H", "span": ""})
        self.assertEqual(out["empty"], [{"ptp": None, "holdover": None}] * 4)
        for icon in out["icons"]:
            self.assertTrue(icon.strip(), "immer ein Symbol – die Farbe ist nur Zusatz")

    def test_dauer_des_holdovers(self):
        out = run_node("""
          console.log(JSON.stringify([0, 59.9, 60, 185, 3599, 3600, 7500, 86399, 86400, 273600, -1, NaN, Infinity, "60", null]
            .map((s) => k.holdSpan(s))));
        """)
        self.assertEqual(out, ["< 1 min", "< 1 min", "1 min", "3 min", "59 min", "1 h 0 min", "2 h 5 min", "23 h 59 min",
                               "1 d 0 h", "3 d 4 h", "", "", "", "", ""])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class PruefbildTest(unittest.TestCase):
    def test_start_nur_mit_ausdruecklichem_parameter(self):
        out = run_node("""
          const m = (q, o) => k.testMode(q, o);
          console.log(JSON.stringify({
            run: m("?test=sync"), withOthers: m("?design=studio&test=sync&lead=40"),
            off: ["", "?", "?test=", "?test=1", "?test=SYNC", "?test=sync%20", "?test=flash", "?design=studio", "?Test=sync",
              "?p=regie", "?test=off&test=sync"].map((q) => m(q)),
            notString: [null, undefined, 7, { test: "sync" }].map((q) => m(q)),
            reduced: m("?test=sync", { reduced: true }), eink: m("?test=sync", { eink: true }),
            both: m("?test=sync", { reduced: true, eink: true }), reducedOff: m("?design=tc", { reduced: true }),
          }));
        """)
        self.assertEqual((out["run"], out["withOthers"]), ("run", "run"))
        self.assertEqual(set(out["off"]), {"off"})
        self.assertEqual(set(out["notString"]), {"off"})
        self.assertEqual(out["reduced"], "reduced", "bei „weniger Bewegung“ kein Blitz")
        self.assertEqual(out["eink"], "eink")
        self.assertEqual(out["both"], "reduced")
        self.assertEqual(out["reducedOff"], "off")

    def test_nie_aus_profil_oder_gemerktem_stand(self):
        out = run_node("""
          console.log(JSON.stringify({
            only: k.ADDRESS_ONLY, skip: l.STORE_SKIP,
            profile: l.effectiveQuery({ search: "", profile: { design: "studio", test: "sync" } }),
            profileUrl: l.effectiveQuery({ search: "?test=sync", profile: { design: "studio" } }),
            stored: l.effectiveQuery({ search: "", stored: "design=flip&test=sync" }),
            storedQuery: l.storedQuery("test=sync&design=flip"),
            storedWith: l.storedWith("design=flip&test=sync", "design", "nixie"),
            storedSet: l.storedSet("design=flip&test=sync", "lead", 40),
            profileParams: l.profileParams({ design: "tc", test: "sync", lead: "40" }),
            parsedProfile: k.parseParams(l.effectiveQuery({ search: "?p=regie", profile: { test: "sync" } })).test,
            parsedUrl: k.parseParams("?test=sync").test,
            modeProfile: k.testMode("?p=regie"),
          }));
        """)
        self.assertEqual(out["only"], ["test"])
        self.assertIn("test", out["skip"])
        self.assertEqual(out["profile"], "design=studio", "aus dem Profil kommt das Prüfbild nie")
        self.assertEqual(out["profileUrl"], "design=studio&test=sync", "ausdrücklich in der Adresse gilt es")
        self.assertEqual(out["stored"], "design=flip")
        self.assertEqual(out["storedQuery"], "design=flip")
        self.assertEqual(out["storedWith"], "design=nixie")
        self.assertEqual(out["storedSet"], "design=flip&lead=40")
        self.assertEqual(out["profileParams"], {"design": "tc", "lead": "40"})
        self.assertIsNone(out["parsedProfile"])
        self.assertEqual(out["parsedUrl"], "sync")
        self.assertEqual(out["modeProfile"], "off")

    def test_pruefbild_misst_die_gemerkte_anzeige_ein(self):
        out = run_node("""
          const stored = "design=studio&lead=80";
          const eff = (search, more = {}) => l.effectiveQuery({ search, stored, ...more });
          console.log(JSON.stringify({
            plain: eff(""), test: eff("?test=sync"), parsed: k.parseParams(eff("?test=sync")),
            unknown: eff("?test=sync&foo=1"), badTest: eff("?test=1"),
            withParam: eff("?test=sync&lead=10"), withDesign: eff("?design=flip&test=sync"),
            profile: eff("?p=regie&test=sync", { profile: { design: "tc" } }), profilePending: eff("?p=regie&test=sync"),
            applies: ["", "?test=sync", "?test=1", "?test=sync&foo=1", "?test=sync&lead=10", "?lead=10", "?p=regie&test=sync",
              "?test=sync&kiosk=1", "?test=sync&lock=1"].map((q) => l.storedApplies(q)),
            has: [l.hasSchemaParams("?test=sync"), l.hasSchemaParams("?foo=1")],
            set: [l.storedSet(stored, "lead", 90), l.storedSet(stored, "lead", 0), l.storedSet("lead=80", "lead", 0),
              l.storedSet("design=flip", "lead", 30), l.storedSet(stored, "lead", 999), l.storedSet("", "lead", 20),
              l.storedSet("kiosk=1&design=flip&layout=tile", "lead", 20)],
            done: k.testDoneSearch("?test=sync", null),
          }));
        """)
        self.assertEqual(out["plain"], "design=studio&lead=80")
        self.assertEqual(out["test"], "design=studio&lead=80&test=sync", "der gemerkte Stand bleibt die Grundlage")
        self.assertEqual((out["parsed"]["design"], out["parsed"]["lead"], out["parsed"]["test"]), ("studio", 80, "sync"))
        self.assertEqual(out["unknown"], "design=studio&lead=80&test=sync")
        self.assertEqual(out["badTest"], "design=studio&lead=80", "ein ungültiger Wert kommt nicht durch")
        self.assertEqual(out["withParam"], "lead=10&test=sync", "nennt die Adresse einen Wert der Anzeige, gilt sie allein")
        self.assertEqual(out["withDesign"], "design=flip&test=sync")
        self.assertEqual(out["profile"], "design=tc&test=sync", "mit Profil nie der gemerkte Stand")
        self.assertEqual(out["profilePending"], "test=sync")
        self.assertEqual(out["applies"], [True, True, True, True, False, False, False, False, False])
        self.assertEqual(out["has"], [True, False], "hasSchemaParams selbst zählt test weiter mit")
        self.assertEqual(out["set"], ["design=studio&lead=90", "design=studio", "", "design=flip&lead=30", "design=studio",
                                      "lead=20", "design=flip&lead=20"])
        self.assertEqual(out["done"], "", "die Adresse bleibt /clock – der Vorlauf steht im gemerkten Stand")

    def test_flaeche_wechselt_genau_zur_vollen_sekunde(self):
        out = run_node("""
          const base = Date.UTC(2026, 5, 30, 8, 15, 40);
          // Zehn Sekunden in 1-ms-Schritten: Wann wechselt die Fläche, und wie oft?
          const changes = [];
          let prev = k.flashStep(base).on;
          for (let ms = base + 1; ms <= base + 10_000; ms += 1) {
            const on = k.flashStep(ms).on;
            if (on !== prev) changes.push(ms - base);
            prev = on;
          }
          // Zeitgeber-Kette wie in clock.js: immer um delay weiter, mit bis zu 3 ms Verspätung.
          const fired = [];
          let now = base + 137.4;
          for (let i = 0; i < 8; i += 1) {
            const step = k.flashStep(now);
            fired.push([Math.round((now - base) * 10) / 10, step.on, step.delay]);
            now += step.delay + (i % 4);
          }
          console.log(JSON.stringify({
            changes, early: k.FLASH_EARLY_MS, fired,
            at: [0, 1, 499, 979, 980, 999, 1000, 1001, 1979, 1980].map((d) => { const s = k.flashStep(base + d); return [s.on, s.delay, s.second - base / 1000]; }),
            bad: [NaN, Infinity, undefined, null, "x"].map((v) => k.flashStep(v)),
            negative: k.flashStep(-500.5),
          }));
        """)
        early = out["early"]
        self.assertEqual(out["changes"], [1000 * n - early for n in range(1, 11)],
                         "genau ein Wechsel je Sekunde, an der Sekundengrenze (der Zeitgeber darf wenige ms früher feuern)")
        self.assertLessEqual(early, 20)
        gaps = [b - a for a, b in zip(out["changes"], out["changes"][1:])]
        self.assertEqual(set(gaps), {1000}, "nie schneller als ein Wechsel je Sekunde (höchstens 1 Hz)")
        self.assertEqual(out["at"], [[True, 1000, 0], [True, 999, 0], [True, 501, 0], [True, 21, 0], [False, 1020, 1],
                                     [False, 1001, 1], [False, 1000, 1], [False, 999, 1], [False, 21, 1], [True, 1020, 2]])
        # Die Kette feuert jede Sekunde einmal, abwechselnd hell und dunkel, immer kurz nach der Grenze.
        self.assertEqual([on for _at, on, _delay in out["fired"]], [True, False, True, False, True, False, True, False])
        for index, (at, _on, delay) in enumerate(out["fired"][1:], start=1):
            self.assertLessEqual(at - 1000 * index, 4.0, "der Wechsel fällt auf die volle Sekunde")
            self.assertGreaterEqual(at - 1000 * index, 0.0)
            self.assertGreaterEqual(delay, 990)
        self.assertEqual(out["bad"], [None] * 5)
        self.assertGreaterEqual(out["negative"]["delay"], 1)

    def test_vorlauf_und_adresse_nach_dem_beenden(self):
        out = run_node("""
          console.log(JSON.stringify({
            up: [0, 40, 195, 200, NaN, 44.6].map((v) => k.leadStep(v, 1)),
            down: [0, 5, 40, 200, undefined].map((v) => k.leadStep(v, -1)),
            step: k.LEAD_STEP_MS, max: k.LEAD_MAX_MS, schema: k.PARAM_SCHEMA.find((e) => e.name === "lead"),
            done: [
              k.testDoneSearch("?test=sync", null), k.testDoneSearch("?test=sync&lead=40", null),
              k.testDoneSearch("?design=studio&test=sync&lead=40&p=regie", 70), k.testDoneSearch("?test=sync&lead=40", 0),
              k.testDoneSearch("?tz=Europe/London,Asia/Tokyo&until=20:15&test=sync", 30), k.testDoneSearch("?test=sync", 250),
              k.testDoneSearch("?test=sync&test=sync", 12.5), k.testDoneSearch(null, 20),
            ],
            zero: [
              k.testDoneSearch("?p=studio&test=sync", 0), k.testDoneSearch("?p=studio&test=sync&lead=40", 0),
              k.testDoneSearch("?p=studio&test=sync", null), k.testDoneSearch("?p=studio&test=sync&lead=40", null),
              k.testDoneSearch("?design=flip&test=sync&lead=40", 0), k.testDoneSearch("?p=studio&test=sync", 200),
              k.testDoneSearch("?p=studio&test=sync&lead=40", 201), k.testDoneSearch("?p=studio&test=sync&lead=40", -10),
            ],
            reload: k.parseParams(l.effectiveQuery({ search: k.testDoneSearch("?p=studio&test=sync", 0), profile: { lead: "40" } })).lead,
            reloadOld: k.parseParams(l.effectiveQuery({ search: "?p=studio", profile: { lead: "40" } })).lead,
            // Über clocklink: lead=0 bleibt stehen, wenn die Adresse sonst nichts mehr zur Anzeige nennte.
            keep: [
              l.testDoneSearch("?lead=20&test=sync", 0), l.testDoneSearch("?test=sync&lead=40", 0), l.testDoneSearch("?lead=20&test=sync", 30),
              l.testDoneSearch("?lead=20&test=sync", null), l.testDoneSearch("?test=sync", 0), l.testDoneSearch("?test=sync", null),
              l.testDoneSearch("?design=flip&test=sync&lead=40", 0), l.testDoneSearch("?p=studio&test=sync&lead=40", 0),
              l.testDoneSearch("?lead=20&test=sync&foo=1", 0), l.testDoneSearch("?design=studio&lead=30&test=sync", 40),
              l.testDoneSearch("?lead=abc&test=sync", 0),
            ],
            keepReload: k.parseParams(l.effectiveQuery({ search: l.testDoneSearch("?lead=20&test=sync", 0), stored: "design=studio&lead=80" })),
            lostReload: k.parseParams(l.effectiveQuery({ search: "", stored: "design=studio&lead=80" })),
          }));
        """)
        self.assertEqual(out["up"], [10, 50, 200, 200, 10, 55])
        self.assertEqual(out["down"], [0, 0, 30, 190, 0])
        self.assertEqual((out["step"], out["max"]), (10, out["schema"]["max"]))
        self.assertEqual(out["done"], ["", "?lead=40", "?design=studio&lead=70&p=regie", "", 
                                       "?tz=Europe/London,Asia/Tokyo&until=20:15&lead=30", "", "", "?lead=20"])
        # Mit Profil steht ein eingemessener Vorlauf 0 ausdrücklich da: Sonst gälte wieder der Wert des Profils.
        self.assertEqual(out["zero"], ["?p=studio&lead=0", "?p=studio&lead=0", "?p=studio", "?p=studio&lead=40",
                                       "?design=flip", "?p=studio&lead=200", "?p=studio", "?p=studio"])
        self.assertEqual((out["reload"], out["reloadOld"]), (0, 40))
        # Nur lead= in der Adresse und auf 0 eingemessen: lead=0 bleibt, sonst gälte der gemerkte Stand mit seinem Vorlauf.
        self.assertEqual(out["keep"], ["?lead=0", "?lead=0", "?lead=30", "?lead=20", "", "", "?design=flip", "?p=studio&lead=0",
                                       "?lead=0&foo=1", "?design=studio&lead=40", "?lead=0"])
        self.assertEqual((out["keepReload"]["lead"], out["keepReload"]["design"]), (0, None))
        self.assertEqual((out["lostReload"]["lead"], out["lostReload"]["design"]), (80, "studio"))
        for search in out["done"] + out["zero"] + out["keep"]:
            self.assertNotIn("test", search, "ein Neuladen startet das Prüfbild nicht wieder")

    def test_klick_auf_jeder_vollen_sekunde(self):
        out = run_node("""
          const clock = { audio: 10, server: Date.UTC(2026, 5, 30, 8, 15, 58) + 400, exact: true };
          const tones = k.planTones(clock, { mode: "click", horizonMs: 3000 });
          const again = k.planTones(clock, { mode: "click", afterSecond: tones[0].second, horizonMs: 3000 });
          console.log(JSON.stringify({ tones: tones.map((t) => [t.second % 60, Math.round(t.at * 1000) / 1000, t.kind, t.freq, t.dur]),
            again: again.map((t) => t.second % 60), beep: k.BEEP.click,
            seconds: k.planTones(clock, { mode: "seconds", horizonMs: 3000 }).map((t) => t.kind) }));
        """)
        self.assertEqual(out["tones"], [[59, 10.6, "click", 2000, 0.02], [0, 11.6, "click", 2000, 0.02], [1, 12.6, "click", 2000, 0.02]],
                         "auch zur vollen Minute ein Klick, kein langer Ton")
        self.assertEqual(out["again"], [0, 1], "keine Sekunde doppelt")
        self.assertLessEqual(out["beep"]["dur"], 0.03, "ein Klick, kein Piep")
        self.assertEqual(out["seconds"], ["short", "long", "short"], "der Sekundenpiep bleibt, wie er war")


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class ParameterTest(unittest.TestCase):
    """test=sync: gleich in Schema, Server-Allowlist, Link-Baukasten und Doku."""

    def test_schema(self):
        out = run_node("""
          const p = (q) => k.parseParams(q);
          console.log(JSON.stringify({
            entry: k.PARAM_SCHEMA.find((e) => e.name === "test"), last: k.PARAM_SCHEMA[k.PARAM_SCHEMA.length - 1].name,
            ok: p("?test=sync"), dflt: p("?design=tc").test,
            bad: ["1", "true", "SYNC", "sync ", "flash", "<script>", "sync,sync", ""].map((v) => p("?test=" + encodeURIComponent(v)))
              .map((r) => [r.test, r.ignored]),
            show: k.SHOW_ITEMS.includes("status"),
          }));
        """)
        self.assertEqual(out["entry"], {"name": "test", "type": "enum", "values": ["sync"], "default": None})
        self.assertEqual(out["last"], "test")
        self.assertEqual((out["ok"]["test"], out["ok"]["ignored"]), ("sync", []))
        self.assertIsNone(out["dflt"])
        for value, ignored in out["bad"]:
            self.assertEqual((value, ignored), (None, ["test"]))
        self.assertTrue(out["show"], "show=status steuert die Statuszeile")

    def test_server_allowlist(self):
        self.assertEqual(clockprofiles.PARAMS["test"], ("enum", {"values": ("sync",)}))
        self.assertEqual(list(clockprofiles.PARAMS)[-1], "test")
        self.assertEqual(clockprofiles.ADDRESS_ONLY, ("test",))
        self.assertEqual(clockprofiles.check_value("test", "sync"), "sync")
        for bad in ("1", "SYNC", "sync\n", " sync", "", "flash", True, 1, None, ["sync"]):
            with self.subTest(bad=bad):
                with self.assertRaises(clockprofiles.ProfileError):
                    clockprofiles.check_value("test", bad)
        clean = clockprofiles.clean_profile({"title": "Regie", "params": {"design": "studio", "lead": "40", "test": "sync"}})
        self.assertEqual(clean["params"], {"design": "studio", "lead": "40"}, "das Prüfbild wird nicht im Profil gespeichert")
        with self.assertRaises(clockprofiles.ProfileError):
            clockprofiles.clean_profile({"title": "Regie", "params": {"test": "flash"}})
        stored = {"regie": {"title": "Regie", "params": {"design": "studio", "test": "sync"}}}
        self.assertEqual(clockprofiles.public_profile("regie", stored)["params"], {"design": "studio"},
                         "auch ein von Hand gespeicherter Wert wird nicht ausgeliefert")
        for name, preset in clockprofiles.PRESETS.items():
            self.assertNotIn("test", preset["params"], name)
        self.assertIn("status", clockprofiles.SHOW_ITEMS)

    def test_link_baukasten(self):
        out = run_node("""
          console.log(JSON.stringify({
            groups: l.FORM_GROUPS.filter((g) => g.names.includes("test")).map((g) => g.key),
            all: k.PARAM_SCHEMA.every((e) => l.FORM_GROUPS.filter((g) => g.names.includes(e.name)).length === 1),
            link: l.buildQuery({ design: "studio", lead: "40", test: "sync" }),
            bad: l.buildQuery({ test: "flash" }),
            valid: [l.rawValid("test", "sync"), l.rawValid("test", "1"), l.rawValid("test", "")],
            href: l.clockHref(l.buildQuery({ test: "sync" })),
          }));
        """)
        self.assertEqual(out["groups"], ["mode"])
        self.assertTrue(out["all"], "jeder Parameter steht in genau einer Gruppe")
        self.assertEqual(out["link"], "design=studio&lead=40&test=sync", "im Link ist das Prüfbild erlaubt")
        self.assertEqual(out["bad"], "")
        self.assertEqual(out["valid"], [True, False, True])
        self.assertEqual(out["href"], "/clock?test=sync")
        displays = (JS / "pages" / "displays.js").read_text(encoding="utf-8")
        self.assertIn("link.profileParams(", displays, "„Als Profil speichern“ lässt das Prüfbild weg")

    def test_doku_nennt_gemerkten_stand_und_sperren(self):
        doc = (ROOT / "docs" / "integrationen" / "studiouhr.md").read_text(encoding="utf-8")
        part = doc[doc.index("## Prüfbild"):doc.index("## Timecode-Anzeige")]
        for needle in ("/clock?p=regie&test=sync", "Anpassen", "gemerkte Stand", "`lead=0`", "`lock=1`", "Tastenkürzel"):
            with self.subTest(needle=needle):
                self.assertIn(needle, part)

    def test_doku_nennt_parameter_und_grenzen(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        help_text = (JS / "help-uhr.js").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "integrationen" / "studiouhr.md").read_text(encoding="utf-8")
        for name, text in (("README", readme), ("help-uhr.js", help_text), ("studiouhr.md", guide)):
            with self.subTest(name=name):
                self.assertIn("test=sync", text)
                self.assertIn("lead=", text)
                self.assertRegex(text, r"nie\s+aus\s+einem\s+Profil|In\s+einem\s+Profil\s+wird\s+der\s+Wert\s+nicht")
                self.assertRegex(text, r"weniger\s+Bewegung")
                self.assertRegex(text, r"[Nn]icht\s+ins\s+Sendebild")
                self.assertIn("Holdover", text)
                self.assertRegex(text, r"`\??show=`")
                self.assertIn("layout=tile", text)
        for word in ("OBS Studio", "vMix", "CasparCG", "Bitfocus Companion", "Generic: HTTP", "/api/v1/time", "ptp_state",
                     "holdover_seconds", "Authorization: Bearer", "prefers-reduced-motion", "Esc"):
            with self.subTest(word=word):
                self.assertIn(word, guide)
        for state in server.PTP_STATES:
            self.assertIn(f"`{state}`", guide)
            self.assertIn(f"`{state}`", readme)
        self.assertNotIn("iframe src", guide)


class TexteUndSeiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")
        cls.cat = {lang: json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
                   for lang in ("de", "en")}

    def test_texte_in_beiden_sprachen(self):
        keys = ["ptp_title", "holdover", "holdover_since", "holdover_title", "test_title", "test_group", "test_warn",
                "test_note", "test_lead", "test_tone", "test_tone_on", "test_tone_blocked", "test_less", "test_more",
                "test_stop", "test_reduced", "test_eink", "test_ended", "holdover_span", "test_note_locked",
                "test_ended_stored"]
        for lang, cat in self.cat.items():
            for key in keys:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(cat.get(key, "").strip())
            self.assertEqual(sorted(cat["ptp_state"]), sorted(set(server.PTP_STATES) - {"off", "unknown"}), lang)
            self.assertTrue(cat["link"]["f"]["test"].strip())
            self.assertEqual(list(cat["link"]["test_value"]), ["sync"])
            self.assertIn("{since}", cat["holdover_since"])
            self.assertIn("{since}", cat["holdover_span"])
            self.assertEqual(f'{cat["holdover"]} {cat["holdover_span"]}', cat["holdover_since"], "Band und Kachel nennen dasselbe")
            self.assertIn("{ms}", cat["test_ended_stored"])
            # lock=1: Der Text fordert nicht zu Tasten auf, die dort gesperrt sind.
            self.assertIn("lock=1", cat["test_note_locked"])
            self.assertIn("lead=", cat["test_note_locked"])
            self.assertNotRegex(cat["test_note_locked"], r"Pfeiltasten|arrow keys")
            self.assertEqual(cat["test_lead"].count("{ms}"), 2)
            self.assertIn("lead={ms}", cat["test_lead"])
            self.assertIn("Esc", cat["test_warn"])
            self.assertIn("Esc", cat["test_stop"])
        de = self.cat["de"]
        self.assertIn("Achtung", de["test_warn"])
        self.assertIn("weniger Bewegung", de["test_reduced"])
        for key in ("test_note", "test_note_locked", "test_reduced", "holdover_title"):
            self.assertNotRegex(de[key], r"\bSie\b|\bIhr(e|en|em)?\b", "du-Form")

    def test_seite_hat_die_elemente(self):
        for node_id in ("band-status", "chip-ptp", "chip-ptp-icon", "chip-ptp-text", "chip-hold", "chip-hold-text", "chip-hold-since",
                        "clock-hold", "clock-hold-text", "tile-title", "sync-test", "sync-test-warn", "sync-test-flash",
                        "sync-test-sec", "sync-test-note", "sync-test-lead", "sync-test-tone", "sync-test-less",
                        "sync-test-more", "sync-test-stop", "sync-test-status"):
            with self.subTest(node_id=node_id):
                self.assertEqual(self.html.count(f'id="{node_id}"'), 1)
        self.assertRegex(self.html, r'<section class="clock-test" id="sync-test"[^>]* hidden>', "das Prüfbild ist zunächst aus")
        self.assertRegex(self.html, r'id="band-status" hidden>')
        self.assertRegex(self.html, r'id="sync-test-flash" data-on="0" aria-hidden="true"')
        self.assertNotIn("style=", self.html, "keine Inline-Styles (CSP)")
        self.assertNotRegex(self.html, r"<script(?![^>]*\bsrc=)", "keine Inline-Skripte (CSP)")
        # Marken im Band und Holdover-Symbol: Symbol ohne Bedeutung für Screenreader, daneben immer Text.
        self.assertRegex(self.html, r'id="chip-ptp-icon" aria-hidden="true"></span> <span id="chip-ptp-text">')
        self.assertRegex(self.html, r'class="clock-hold-icon" aria-hidden="true">H</span><span class="sr-only" id="clock-hold-text">')
        # Das Band ist eine Live-Region: Die Dauer des Holdovers (wechselt jede Minute) steht darin mit aria-live="off".
        self.assertRegex(self.html, r'<footer class="clock-band" id="band"[^>]* aria-live="polite">')
        self.assertRegex(self.html, r'<span id="chip-hold-text"></span> <span id="chip-hold-since" aria-live="off"></span></span>')
        start = self.js.index("function renderChips(")
        chips = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn('setText($("chip-hold-text"), hold ? t("clock.holdover") : "");', chips)
        self.assertIn('setText($("chip-hold-since"), hold && hold.span ? t("clock.holdover_span", { since: hold.span }) : "");', chips)

    def test_pruefbild_bei_wenig_hoehe_und_auf_grossen_flaechen(self):
        block = self.css[self.css.index("Studiouhr B5: Prüfbild"):]
        low = block[block.index("@media (max-height: 320px)"):]
        # Ohne Fläche („weniger Bewegung“, E-Ink) ist der Hinweistext der ganze Inhalt: Er bleibt auch bei wenig Höhe.
        self.assertIn('.clock-test[data-mode="run"] .clock-test-note { display: none; }', low.replace(
            ".clock-test-title, .clock-test-status, ", ""))
        self.assertNotRegex(low, r"(?<!\] )\.clock-test-note[^{]*\{ display: none; \}")
        size = re.search(r"\.clock-test-actions \{ font-size: ([0-9.]+)px; \}", low)
        self.assertGreaterEqual(float(size.group(1)) * 0.9, 12.0, "Knöpfe (0,9 em) mindestens 12 px")
        # Schriften wachsen mit der Fläche (4K ohne Skalierung), keine festen Pixelwerte als Obergrenze.
        self.assertRegex(block, r"\.clock-test-actions \{[^}]*font-size: clamp\(14px, [0-9.]+vw \+ 8px, 30px\); \}")
        self.assertRegex(block, r"\.clock-test-warn \{[^}]*font-size: clamp\(13px, 1vw \+ 8px, max\(22px, 2vh\)\);")
        self.assertRegex(block, r"\.clock-test-note, \.clock-test-lead, \.clock-test-status \{[^}]*max\(20px, 1\.8vh\)\); \}")

    def test_pruefbild_ohne_bewegung_im_css(self):
        start = self.css.index("Studiouhr B5: Prüfbild")
        block = self.css[start:]
        self.assertNotRegex(block, r"\banimation\b|\btransition\b|@keyframes", "die Fläche wechselt ohne Übergang, nichts blinkt per CSS")
        self.assertIn('.clock-test-flash[data-on="1"]', block)
        self.assertIn(".clock-test[hidden] { display: none; }", block)
        self.assertRegex(self.css, r':root\[data-show\]:not\(\[data-show~="status"\]\) :is\(\.clock-band-status, \.clock-hold\) \{ display: none; \}')
        self.assertRegex(self.css, r"body\.is-tile \.clock-tile-title:not\(\[hidden\]\)")
        self.assertIn("body.is-tile.has-tile-title .clock-stage > .clock-main { padding-top:", self.css,
                      "die Kachel hält für den Titel eine Zeile frei")

    def test_regeln_in_clock_js(self):
        js = self.js
        self.assertIn("kit.testMode(window.location.search, { reduced: reducedMotion.matches, eink: params.eink })", js,
                      "das Prüfbild liest nur die Adresse und fragt „weniger Bewegung“ ab")
        self.assertNotIn("params.test", js, "nie über die zusammengeführten Werte (Profil, gemerkter Stand)")
        start = js.index("function flashTick()")
        flash = js[start:js.index("\n}\n", start)]
        self.assertIn('if (!test || test.mode !== "run") return;', flash, "ohne Modus run kein Blitz")
        self.assertIn("kit.flashStep(serverMs())", flash, "Wechsel auf der angezeigten Zeit (mit Vorlauf)")
        self.assertIn("setTimeout(flashTick, step.delay)", flash)
        self.assertNotIn("requestAnimationFrame", flash)
        self.assertNotIn("setInterval", flash)
        start = js.index("function testTone()")
        tone = js[start:js.index("\n}\n", start)]
        self.assertIn("kit.audioClock(tone.ctx, perf, trueMs(perf), 0)", tone, "der Klick fällt auf die wahre Sekunde, ohne Vorlauf")
        self.assertIn('kit.planTones(clock, { mode: "click"', tone)
        self.assertIn("kit.scheduleTone(", tone, "derselbe Tonweg wie „Ton auf der Sekunde“")
        # Esc beendet auch mit lock=1: eigener Listener, der params.lock nicht abfragt.
        start = js.index('if (event.key !== "Escape") return;')
        esc = js[start:js.index("});", start)]
        self.assertIn("stopTest();", esc)
        self.assertNotIn("params.lock", esc)
        self.assertIn('reducedMotion.addEventListener("change"', js, "„weniger Bewegung“ gilt sofort")
        # Hinter dem Prüfbild ruhen die Kürzel der Uhr (nur Hilfe und Vollbild), die Bühne ist inert.
        start = js.index("function onKey(event)")
        keys = js[start:js.index("\n}\n", start)]
        guard = 'if (state.test && key !== "?" && key.toLowerCase() !== "f") return;'
        self.assertIn(guard, keys)
        self.assertLess(keys.index(guard), keys.index("toggleTimer();"), "vor Leertaste und allen Aktionen")
        self.assertLess(keys.index('if (key === "Escape")'), keys.index(guard))
        start = js.index("function coverStage(")
        cover = js[start:js.index("\n}\n", start)]
        self.assertIn("main.inert = covered;", cover)
        start = js.index("function startTest()")
        self.assertIn("coverStage(true);", js[start:js.index("\n}\n", start)])
        # lock=1: eigener Erklärtext ohne Aufforderung zu gesperrten Tasten.
        self.assertIn('(params.lock ? "clock.test_note_locked" : "clock.test_note")', js)
        start = js.index("function stopTest(")
        stop = js[start:js.index("\n}\n", start)]
        self.assertIn("clearTimeout(test.timer)", stop)
        self.assertIn("link.testDoneSearch(", stop)
        self.assertNotIn("kit.testDoneSearch(", stop)
        self.assertIn("coverStage(false);", stop)
        self.assertLess(stop.index("coverStage(false);"), stop.index("if (keep) return;"))
        # Gilt der gemerkte Stand, kommt der eingemessene Vorlauf dort hinein und nicht in die Adresse.
        self.assertIn("test.leadChanged && link.storedApplies(window.location.search)", stop)
        self.assertIn('link.storedSet(stored, "lead", params.lead, ZONES)', stop)
        self.assertIn("test.leadChanged && !remembered ? params.lead : null", stop)
        # Wechselt „weniger Bewegung“ mitten im Einmessen, startet das Prüfbild neu – der Vermerk „Vorlauf geändert“ bleibt.
        start = js.index('reducedMotion.addEventListener("change"')
        change = js[start:js.index("\n  });\n", start)]
        self.assertIn("const leadChanged = state.test.leadChanged;", change)
        self.assertLess(change.index("const leadChanged"), change.index("stopTest(true);"))
        self.assertLess(change.index("startTest();"), change.index("if (state.test) state.test.leadChanged = leadChanged;"))
        # „Link kopieren“ im Panel: ohne Parameter, die nur aus der Adresse wirken (test=sync).
        start = js.index("function currentRaw()")
        self.assertIn("return link.profileParams(link.rawParams(query, ZONES));", js[start:js.index("\n}\n", start)])
        # Statuszeile: Text nur aus dem Katalog bzw. aus festen Werten, nie Text aus der Antwort.
        start = js.index("function renderChips(")
        chips = js[start:js.index("\n}\n", start)]
        self.assertIn("kit.statusChips(state.status)", chips)
        self.assertNotRegex(chips, r"state\.status\.(ptp_state|holdover)")
        self.assertNotIn("innerHTML", js)
        self.assertIn("t(`clock.ptp_state.${chips.ptp.state}`)", chips)

    def test_oeffentliche_dateien_unveraendert(self):
        # Keine neue Datei für /clock: Alles steht in Dateien, die schon öffentlich sind.
        imports = set(re.findall(r'from "\./([a-z0-9]+\.js)"', self.js))
        for name in imports:
            self.assertIn(f"/static/js/{name}", server.CLOCK_PUBLIC_PATHS)


if __name__ == "__main__":
    unittest.main()
