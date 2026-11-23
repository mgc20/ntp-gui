"""Netzdienste (1.9): Ratelimit für NTP und NTS-KE, Client-Log, Inselbetrieb und Hinweise, wenn der
Zeitserver öffentlichen Adressen antwortet oder nur das Gateway des Docker-Netzes sieht.

  * „Anfragen begrenzen“ hat Stufen (aus/schonend/streng); Standard „schonend“, bei öffentlichen
    Adressen unter „Erlaubte Netze“ „streng“. Ja/Nein aus älteren Versionen gilt weiter.
  * Mit eigenem NTS-Server steht passend dazu „ntsratelimit“ in chrony.conf.
  * Inselbetrieb ist bei öffentlichen Adressen standardmäßig aus; ausdrücklich gesetzte Werte bleiben.
  * Übersicht und Container-Log weisen auf einen offenen Zeitserver und auf das Docker-Gateway hin.
"""

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import confgen  # noqa: E402
import insights  # noqa: E402
import settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QUIET = {"warn": lambda *_a, **_k: None}
NTS_FILES = ("/var/lib/chrony/nts/server.crt", "/var/lib/chrony/nts/server.key")


def cfg_for(env=None, saved=None):
    return {key: entry["value"] for key, entry in settings.effective(env or {}, saved=saved or {}).items()}


def render(env=None, saved=None, nts=False):
    cfg = cfg_for(env, saved)
    if nts:
        cfg["nts_server_enable"] = True
    return confgen.render_chrony(cfg, env or {}, nts_files=NTS_FILES if nts else None, **QUIET)


class RatelimitTest(unittest.TestCase):
    def test_standard_ist_schonend_und_steht_in_chrony_conf(self):
        self.assertEqual(cfg_for()["ntp_ratelimit"], "schonend")
        self.assertIn("ratelimit interval -2 burst 32 leak 2\n", render())

    def test_ja_nein_aus_frueheren_versionen_gilt_weiter(self):
        self.assertEqual(cfg_for({"NTP_RATELIMIT": "true"})["ntp_ratelimit"], "streng")
        self.assertEqual(cfg_for({"NTP_RATELIMIT": "false"})["ntp_ratelimit"], "aus")
        self.assertEqual(cfg_for(saved={"ntp_ratelimit": True})["ntp_ratelimit"], "streng")
        self.assertEqual(cfg_for(saved={"ntp_ratelimit": False})["ntp_ratelimit"], "aus")
        self.assertIn("ratelimit interval 1 burst 16 leak 2\n", render({"NTP_RATELIMIT": "true"}))

    def test_aus_schreibt_keine_ratelimit_zeile(self):
        text = render({"NTP_RATELIMIT": "aus"}, nts=True)
        self.assertNotRegex(text, r"(?m)^(nts)?ratelimit ")

    def test_unbekannte_stufe_wird_abgelehnt(self):
        with self.assertRaises(settings.ValidationError):
            settings.FIELDS["ntp_ratelimit"]["convert"]("sehr")
        entry = settings.effective({"NTP_RATELIMIT": "sehr"}, saved={})["ntp_ratelimit"]
        self.assertEqual(entry["value"], "schonend")
        self.assertTrue(entry["error"])

    def test_nts_server_bekommt_ntsratelimit(self):
        self.assertIn("ntsratelimit interval 0 burst 16 leak 2\n", render(nts=True))
        self.assertIn("ntsratelimit interval 3 burst 8 leak 2\n", render({"NTP_RATELIMIT": "streng"}, nts=True))

    def test_ohne_nts_server_kein_ntsratelimit(self):
        self.assertNotIn("ntsratelimit", render({"NTP_RATELIMIT": "streng"}))

    def test_schonend_ist_grosszuegiger_als_streng(self):
        def numbers(line):
            return [int(x) for x in re.findall(r"-?\d+", line)]
        for index in (0, 1):
            soft, strict = (numbers(confgen.RATELIMIT_LINES[level][index]) for level in ("schonend", "streng"))
            with self.subTest(zeile=index):
                self.assertLess(soft[0], strict[0])     # kürzerer mittlerer Abstand
                self.assertGreaterEqual(soft[1], strict[1])  # mindestens so großer Stoß


class ClientLogTest(unittest.TestCase):
    def test_standard_kleiner(self):
        self.assertIn("clientloglimit 2097152\n", render())

    def test_eigener_wert_bleibt(self):
        self.assertIn("clientloglimit 500000\n", render({"CLIENTLOGLIMIT": "500000"}))


class OeffentlicheNetzeTest(unittest.TestCase):
    def test_erkennung(self):
        public = settings.public_networks(["10.0.0.0/8", "all", "0.0.0.0/0", "::/0", "fc00::/7", "fe80::/10",
                                           "100.64.0.0/10", "8.8.8.0/24", "2a00::/16", "172.16.0.0/12"])
        self.assertEqual(public, ["all", "0.0.0.0/0", "::/0", "8.8.8.0/24", "2a00::/16"])
        self.assertEqual(settings.public_networks(settings.PRIVATE_NETWORKS), [])

    def test_oeffentlich_heisst_streng_und_kein_inselbetrieb(self):
        cfg = cfg_for({"ALLOW_NETWORKS": "all"})
        self.assertEqual(cfg["ntp_ratelimit"], "streng")
        self.assertFalse(cfg["serve_unsynced"])
        text = render({"ALLOW_NETWORKS": "all"})
        self.assertIn("ratelimit interval 1 burst 16 leak 2\n", text)
        self.assertNotIn("local stratum", text)

    def test_privat_bleibt_inselbetrieb(self):
        self.assertTrue(cfg_for()["serve_unsynced"])
        self.assertIn("local stratum 10\n", render())

    def test_ausdruecklich_gesetzte_werte_bleiben(self):
        env = {"ALLOW_NETWORKS": "0.0.0.0/0", "SERVE_UNSYNCED": "true", "NTP_RATELIMIT": "schonend"}
        cfg = cfg_for(env)
        self.assertTrue(cfg["serve_unsynced"])
        self.assertEqual(cfg["ntp_ratelimit"], "schonend")
        cfg = cfg_for({"ALLOW_NETWORKS": "all"}, saved={"serve_unsynced": True, "ntp_ratelimit": "aus"})
        self.assertTrue(cfg["serve_unsynced"])
        self.assertEqual(cfg["ntp_ratelimit"], "aus")

    def test_dashboard_wert_fuer_erlaubte_netze_zaehlt(self):
        cfg = cfg_for(saved={"allow_networks": ["all"]})
        self.assertEqual(cfg["ntp_ratelimit"], "streng")
        self.assertFalse(cfg["serve_unsynced"])

    def test_log_warnt_bei_oeffentlichen_adressen(self):
        self.assertEqual(confgen.exposure_warnings(cfg_for()), [])
        notes = confgen.exposure_warnings(cfg_for({"ALLOW_NETWORKS": "all"}))
        self.assertEqual(len(notes), 1)
        self.assertIn("öffentlichen Adressen", notes[0])
        notes = " ".join(confgen.exposure_warnings(
            cfg_for({"ALLOW_NETWORKS": "all", "SERVE_UNSYNCED": "true", "NTP_RATELIMIT": "false"})))
        self.assertIn("Ratelimit ist aus", notes)
        self.assertIn("SERVE_UNSYNCED=false", notes)

    def test_apply_schreibt_die_warnung_ins_log(self):
        source = (ROOT / "app" / "confgen.py").read_text(encoding="utf-8")
        body = source[source.index("def apply("):]
        self.assertIn("exposure_warnings(cfg)", body[:body.index("\ndef ")])


class HinweiseTest(unittest.TestCase):
    def keys(self, items):
        return {item["key"]: item for item in items}

    def test_offener_zeitserver(self):
        self.assertEqual(insights.exposure_insights(cfg_for()), [])
        found = self.keys(insights.exposure_insights(cfg_for({"ALLOW_NETWORKS": "all"})))
        self.assertEqual(found["allow_public"]["level"], "info")
        found = self.keys(insights.exposure_insights(cfg_for({"ALLOW_NETWORKS": "all", "SERVE_UNSYNCED": "1"})))
        self.assertEqual(found["allow_public"]["level"], "warn")
        self.assertIn("SERVE_UNSYNCED=false", found["allow_public"]["text"])

    def test_docker_gateway_wird_erkannt(self):
        clients = [{"address": "::ffff:172.17.0.1"}, {"address": "192.168.1.20"}]
        found = self.keys(insights.exposure_insights(cfg_for(), clients, "172.17.0.1", "bridge"))
        self.assertEqual(found["docker_gateway"]["level"], "info")
        self.assertIn("172.17.0.1", found["docker_gateway"]["text"])
        found = self.keys(insights.exposure_insights(cfg_for({"NTP_RATELIMIT": "streng"}), clients,
                                                     "172.17.0.1", "bridge"))
        self.assertEqual(found["docker_gateway"]["level"], "warn")

    def test_kein_gateway_hinweis_im_host_netz_oder_ohne_gateway_client(self):
        cfg = cfg_for()
        self.assertEqual(insights.exposure_insights(cfg, [{"address": "192.168.1.1"}], "192.168.1.1", "host"), [])
        self.assertEqual(insights.exposure_insights(cfg, [{"address": "192.168.1.20"}], "172.17.0.1", "bridge"), [])
        self.assertEqual(insights.exposure_insights(cfg, [], None, "bridge"), [])

    def test_status_nutzt_die_hinweise(self):
        source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        self.assertIn("insights.exposure_insights(cfg, clients", source)


class DokuTest(unittest.TestCase):
    def test_einstellungs_hilfe(self):
        help_js = (ROOT / "app" / "static" / "js" / "help.js").read_text(encoding="utf-8")
        settings_js = (ROOT / "app" / "static" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")
        self.assertIn('ntp_ratelimit: "ratelimit"', settings_js)
        self.assertIn("  ratelimit: {", help_js)
        self.assertIn("keine Authentifizierung", help_js)
        for key in ("ntp_ratelimit", "serve_unsynced", "allow_networks"):
            with self.subTest(key=key):
                self.assertIn("öffentliche", settings.FIELDS[key]["help"])

    def test_readme(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("### Öffentlich erreichbarer Zeitserver", readme)
        self.assertIn("**Keine Authentifizierung.**", readme)
        self.assertIn("| `CLIENTLOGLIMIT` | `2097152` |", readme)
        self.assertIn("| `NTP_RATELIMIT` | `schonend`", readme)

    def test_vps_vorlage(self):
        text = (ROOT / "docker-compose.vps.yml").read_text(encoding="utf-8")
        for line in ('WEB_REQUIRE_AUTH: "true"', 'NTP_RATELIMIT: "streng"', 'SERVE_UNSYNCED: "false"',
                     'WEB_BIND: "127.0.0.1"', "network_mode: host"):
            with self.subTest(line=line):
                self.assertRegex(text, r"(?m)^\s+" + re.escape(line) + r"\s*$")


if __name__ == "__main__":
    unittest.main()
