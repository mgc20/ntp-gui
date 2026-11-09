"""Eingaben, die chronyd/ptp4l nicht lesen können, dürfen gar nicht erst in die Konfiguration.

  * bind_address: chrony erwartet bei „bindaddress“ genau eine IP-Adresse. Ein Hostname, ein
    Interface, ein Netz oder zwei Adressen ließen chronyd mit „Fatal error“ abbrechen – und mit ihm
    den ganzen Container, bei jedem Neustart wieder.
  * Quellen- und Refclock-Optionen: chrony liest viele Argumente als Ganzzahl. „minpoll 1.5“ oder
    „poll 1e3“ machten die ganze Zeile ungültig, ebenso „stratum -1“ bei einem Refclock.
  * EXTRA_CHRONY_CONF/EXTRA_PTP4L_CONF: „\\n“ wird zum Zeilenumbruch, Umlaute bleiben erhalten.

Die Grenzen sind mit chronyd 4.5 (chronyd -p) nachgemessen.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import confgen  # noqa: E402
import settings  # noqa: E402


class BindAddressTest(unittest.TestCase):
    def test_eine_ip_adresse_geht(self):
        for value in ("192.0.2.5", "198.51.100.1", "2001:db8::1", "0.0.0.0", "::"):
            with self.subTest(value=value):
                self.assertEqual(settings.validate({"bind_address": value})["bind_address"], value)

    def test_leer_heisst_alle_adressen(self):
        self.assertEqual(settings.validate({"bind_address": "  "})["bind_address"], "")

    def test_wird_normalisiert(self):
        self.assertEqual(settings.validate({"bind_address": " 2001:DB8:0::1 "})["bind_address"], "2001:db8::1")

    def test_alles_andere_wird_abgelehnt(self):
        for value in ("localhost", "nas-keller", "eth0", "192.0.2.5/24", "192.0.2.5 198.51.100.1",
                      "fe80::1%eth0", "192.0.2.256"):
            with self.subTest(value=value), self.assertRaises(settings.ValidationError) as ctx:
                settings.validate({"bind_address": value})
            self.assertIn("z. B.", str(ctx.exception), "die Meldung nennt ein Beispiel")

    def test_ungueltiger_wert_aus_der_umgebung_landet_nicht_in_chrony_conf(self):
        cfg = settings.values({"BIND_ADDRESS": "eth0"})
        self.assertEqual(cfg["bind_address"], "")
        self.assertNotIn("bindaddress", confgen.render_chrony(cfg, {}, warn=lambda *_a: None))

    def test_gueltiger_wert_aus_der_umgebung(self):
        cfg = settings.values({"BIND_ADDRESS": "192.0.2.5"})
        self.assertIn("bindaddress 192.0.2.5\n", confgen.render_chrony(cfg, {}, warn=lambda *_a: None))


class GanzzahlOptionenTest(unittest.TestCase):
    SOURCE_INT = ("minpoll", "maxpoll", "presend", "minstratum", "polltarget", "version", "port",
                  "ntsport", "filter", "minsamples", "maxsamples", "maxsources", "certset")
    SOURCE_FLOAT = ("maxdelay", "maxdelayratio", "maxdelaydevratio", "mindelay", "asymmetry", "offset")
    REFCLOCK_INT = ("poll", "dpoll", "rate", "minsamples", "maxsamples", "stratum", "filter", "maxlockage")
    REFCLOCK_FLOAT = ("offset", "delay", "precision", "maxdispersion", "width")

    def test_quellen_ganzzahl_optionen_lehnen_kommazahl_und_exponent_ab(self):
        for word in self.SOURCE_INT:
            for value in ("1.5", "1e3"):
                with self.subTest(word=word, value=value), self.assertRaises(settings.ValidationError) as ctx:
                    settings._as_source_options(f"iburst {word} {value}")
                self.assertIn("ganze Zahl", str(ctx.exception))

    def test_quellen_ganzzahl_optionen_nehmen_ganzzahlen(self):
        for word in self.SOURCE_INT:
            for value in ("6", "-1"):  # chronyd 4.5 liest bei allen auch negative Werte
                with self.subTest(word=word, value=value):
                    self.assertEqual(settings._as_source_options(f"iburst {word} {value}"),
                                     f"iburst {word} {value}")

    def test_quellen_kommazahl_optionen_bleiben_wie_bisher(self):
        for word in self.SOURCE_FLOAT:
            for value in ("0.5", "-1", "1e-3", "2"):
                with self.subTest(word=word, value=value):
                    self.assertEqual(settings._as_source_options(f"{word} {value}"), f"{word} {value}")

    def test_refclock_ganzzahl_optionen_lehnen_kommazahl_und_exponent_ab(self):
        for word in self.REFCLOCK_INT:
            for value in ("1.5", "1e3"):
                with self.subTest(word=word, value=value), self.assertRaises(settings.ValidationError):
                    settings._as_refclock_options(f"{word} {value}")

    def test_refclock_ganzzahl_optionen_nehmen_ganzzahlen(self):
        for word in self.REFCLOCK_INT:
            with self.subTest(word=word):
                self.assertEqual(settings._as_refclock_options(f"{word} 2"), f"{word} 2")
        self.assertEqual(settings._as_refclock_options("poll 0 dpoll -2"), "poll 0 dpoll -2")

    def test_refclock_stratum_nur_0_bis_15(self):
        for value in ("0", "1", "15"):
            with self.subTest(value=value):
                self.assertEqual(settings._as_refclock_options(f"stratum {value}"), f"stratum {value}")
        for value in ("-1", "16", "99"):
            with self.subTest(value=value), self.assertRaises(settings.ValidationError) as ctx:
                settings._as_refclock_options(f"stratum {value}")
            self.assertIn("0 bis 15", str(ctx.exception))

    def test_refclock_kommazahl_optionen_bleiben_wie_bisher(self):
        for word in self.REFCLOCK_FLOAT:
            for value in ("0.5", "-1", "1e-3"):
                with self.subTest(word=word, value=value):
                    self.assertEqual(settings._as_refclock_options(f"{word} {value}"), f"{word} {value}")

    def test_pps_optionen_pruefen_genauso(self):
        with self.assertRaises(settings.ValidationError):
            settings._as_pps_options("rate 1.5")

    def test_ueber_validate(self):
        with self.assertRaises(settings.ValidationError):
            settings.validate({"ntp_source_options": "iburst minpoll 1.5"})
        with self.assertRaises(settings.ValidationError):
            settings.validate({"gps_refclock_options": "stratum -1"})

    def test_nur_ascii_ziffern(self):
        # chrony liest Zahlen mit sscanf; Unicode-Ziffern (arabisch-indisch, Vollbreite)
        # würden die pool-/refclock-Zeile ungültig machen und chronyd abbrechen lassen.
        for value in ("\u0666", "\uff16", "1\u0665", "-\u0661"):
            with self.subTest(value=value):
                with self.assertRaises(settings.ValidationError):
                    settings.validate({"ntp_source_options": f"iburst minpoll {value}"})
                with self.assertRaises(settings.ValidationError):
                    settings._as_refclock_options(f"stratum {value}")
                with self.assertRaises(settings.ValidationError):
                    settings._as_refclock_options(f"offset {value}")
        self.assertEqual(settings.validate({"ntp_source_options": "iburst minpoll 6"}),
                         {"ntp_source_options": "iburst minpoll 6"})

    def test_weitere_zahlenfelder_nur_ascii_ziffern(self):
        with self.assertRaises(settings.ValidationError):
            settings._as_makestep("\u0661.0 3")
        self.assertEqual(settings._as_makestep("1.0 3"), "1.0 3")
        with self.assertRaises(settings.ValidationError):
            settings._check_digits("\uff19\uff16\uff10\uff10")
        self.assertEqual(settings._check_digits("9600"), "9600")
        with self.assertRaises(settings.ValidationError):
            settings._dns_port("\u0665\u0663")
        self.assertEqual(settings._dns_port("53"), 53)
        self.assertFalse(settings.http_url_ok("http://192.0.2.1:\u0668\u0660/"))
        self.assertTrue(settings.http_url_ok("http://192.0.2.1:80/"))


class ExtraZeilenTest(unittest.TestCase):
    def chrony(self, extra):
        cfg = settings.values({})
        return confgen.render_chrony(cfg, {"EXTRA_CHRONY_CONF": extra}, warn=lambda *_a: None)

    def ptp4l(self, extra):
        cfg = dict(settings.values({}), ptp_enable=True, ptp_interface="eth0")
        return confgen.render_ptp4l(cfg, {"EXTRA_PTP4L_CONF": extra})

    def test_chrony_umlaute_bleiben_erhalten(self):
        text = self.chrony("# Zusätzlich: Messung\\nlog measurements")
        self.assertIn("# EXTRA_CHRONY_CONF\n# Zusätzlich: Messung\nlog measurements\n", text)
        self.assertNotIn("Ã", text)

    def test_ptp4l_umlaute_bleiben_erhalten(self):
        text = self.ptp4l("# Größere Abstände\\nlogSyncInterval 0")
        self.assertIn("# Größere Abstände\nlogSyncInterval 0\n", text)
        self.assertNotIn("Ã", text)

    def test_tab_und_backslash_wie_bisher(self):
        self.assertIn("logchange\t0.5\n", self.chrony("logchange\\t0.5"))
        self.assertIn("# a\\nb\n", self.chrony("# a\\\\nb"))

    def test_echte_zeilenumbrueche_gehen_auch(self):
        self.assertIn("\nlogchange 0.5\nlog measurements\n", self.chrony("logchange 0.5\nlog measurements"))

    def test_andere_backslashfolgen_bleiben_stehen_statt_abzustuerzen(self):
        self.assertIn("# C:\\xyz \\d+\n", self.chrony("# C:\\xyz \\d+"))


if __name__ == "__main__":
    unittest.main()
