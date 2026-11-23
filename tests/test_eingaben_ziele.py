"""Eingaben, erzeugte Konfiguration und Ziele ausgehender Verbindungen (1.9).

  * Werte, die in chrony.conf/ptp4l.conf landen, sind immer genau eine Zeile: IPv6-Scope-IDs werden
    abgelehnt, und die erzeugten Zeilen werden vor dem Schreiben noch einmal geprüft.
  * chronyd prüft die neue chrony.conf (chronyd -p), bevor sie die bisherige ersetzt.
  * LEAPSECTZ ist ein Zonenname, kein Pfad; Experten-Variablen werden geprüft.
  * Benachrichtigungen und DNS-Weiterleiter: gesperrte Ziele (netguard), Prüfung nach der Auflösung,
    Bremse und einheitliche Meldung am Test-Knopf.
  * Datenschutzfilter: lange Leerraum-Folgen kosten keine kubische Zeit.
"""

import ipaddress
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import closed_tcp_port  # noqa: E402

import confgen  # noqa: E402
import netguard  # noqa: E402
import notify  # noqa: E402
import settings  # noqa: E402

QUIET = {"warn": lambda *_a, **_k: None}
NEWLINE_SCOPE = "fe80::1%x\nuser root"


def source(host: str) -> list[dict]:
    return [{"type": "server", "host": host, "nts": False, "prefer": False, "noselect": False, "options": ""}]


class ScopeIdTest(unittest.TestCase):
    """Scope-IDs (auch mit Zeilenumbruch) werden in allen Adress- und Netzfeldern abgelehnt."""

    CASES = {
        "ntp_sources": source(NEWLINE_SCOPE),
        "nts_server_name": NEWLINE_SCOPE,
        "allow_networks": [NEWLINE_SCOPE],
        "deny_networks": [NEWLINE_SCOPE],
        "trusted_proxies": [NEWLINE_SCOPE],
        "dns_servers": [NEWLINE_SCOPE],
        "dns_dot": ["[fe80::1%x\nallow]:853"],
        "dns_pin": ["dns.example.org=fe80::1%x\nallow"],
        "bind_address": NEWLINE_SCOPE,
    }

    def test_scope_id_mit_zeilenumbruch_wird_abgelehnt(self):
        for key, value in self.CASES.items():
            with self.subTest(key=key), self.assertRaises(settings.ValidationError):
                settings.validate({key: value})

    def test_scope_id_ohne_zeilenumbruch_wird_ebenso_abgelehnt(self):
        # chrony versteht „allow fe80::1%eth0/128“ nicht und bräche beim Start ab.
        for key, value in (("allow_networks", ["fe80::1%eth0"]), ("ntp_sources", source("fe80::1%eth0")),
                           ("dns_servers", ["fe80::1%eth0"])):
            with self.subTest(key=key), self.assertRaises(settings.ValidationError):
                settings.validate({key: value})

    def test_adressen_und_netze_ohne_scope_id_gehen_weiter(self):
        clean = settings.validate({"allow_networks": ["192.168.0.0/16", "fd00::/8", "10.0.0.0/255.0.0.0"],
                                   "ntp_sources": source("2001:db8::123"), "nts_server_name": "zeit.example.org"})
        self.assertEqual(clean["allow_networks"], ["192.168.0.0/16", "fd00::/8", "10.0.0.0/8"])
        self.assertEqual(clean["ntp_sources"][0]["host"], "2001:db8::123")

    def test_url_mit_scope_id_oder_steuerzeichen_wird_abgelehnt(self):
        for url in ("http://[fe80::1%25x]/", "http://[fe80::1%x\nallow]/", "http://ntfy.lan/x\n",
                    "http://ntfy.lan/\x85x"):
            with self.subTest(url=url):
                self.assertFalse(settings.http_url_ok(url))
        self.assertTrue(settings.http_url_ok("http://[2001:db8::1]:8080/"))

    def test_gespeicherter_wert_mit_scope_id_faellt_auf_den_standard_zurueck(self):
        entry = settings.effective({}, saved={"allow_networks": [NEWLINE_SCOPE],
                                               "nts_server_name": NEWLINE_SCOPE})
        self.assertTrue(entry["allow_networks"]["error"])
        self.assertTrue(entry["nts_server_name"]["error"])
        cfg = {key: e["value"] for key, e in entry.items()}
        self.assertNotIn("user root", confgen.render_chrony(cfg, {}, **QUIET))


class ZeilenSperreTest(unittest.TestCase):
    """Auch an der Prüfung vorbei darf kein Wert eine weitere Zeile erzeugen."""

    def test_chrony_zeile_mit_steuerzeichen_wird_nicht_erzeugt(self):
        base = settings.values({})
        for key, value in (("allow_networks", ["10.0.0.0/8\ncmdallow all"]),
                           ("nts_server_name", "a\rb"), ("makestep", "1 3\x85local stratum 1")):
            cfg = dict(base, **{key: value})
            if key == "nts_server_name":
                cfg.update(nts_server_enable=True)
            with self.subTest(key=key), self.assertRaises(confgen.UnsafeConfig):
                confgen.render_chrony(cfg, {}, nts_files=("/config/c.pem", "/config/k.pem"), **QUIET)

    def test_ptp4l_zeile_mit_steuerzeichen_wird_nicht_erzeugt(self):
        cfg = dict(settings.values({}), ptp_enable=True, ptp_interface="eth0\n[global]")
        with self.assertRaises(confgen.UnsafeConfig):
            confgen.render_ptp4l(cfg, {})

    def test_extra_chrony_conf_bleibt_mehrzeilig(self):
        text = confgen.render_chrony(settings.values({}), {"EXTRA_CHRONY_CONF": "logchange 0.5\\nlog tracking"},
                                     **QUIET)
        self.assertIn("logchange 0.5\nlog tracking\n", text)


class LeapsectzTest(unittest.TestCase):
    def test_nur_zonennamen(self):
        for value in ("Europe/Berlin", "right/UTC", "UTC", "Etc/GMT+1"):
            with self.subTest(value=value):
                self.assertEqual(settings.validate({"leapsectz": value})["leapsectz"], value)
        for value in ("/etc/shadow", "../../etc/shadow", "right/../../etc", "Europe//Berlin", "a\nb"):
            with self.subTest(value=value), self.assertRaises(settings.ValidationError):
                settings.validate({"leapsectz": value})

    def test_absoluter_pfad_landet_nie_in_chrony_conf(self):
        warnings = []
        line = confgen.leap_directive({"leapsectz": "/etc/shadow", "leapseclist": ""},
                                      warn=lambda *a: warnings.append(a), exists=lambda _p: True)
        self.assertIsNone(line)
        self.assertTrue(warnings)
        self.assertEqual(confgen.leap_directive({"leapsectz": "right/UTC"}, exists=lambda _p: True),
                         "leapsectz right/UTC")


class ExpertenVariablenTest(unittest.TestCase):
    def render(self, env):
        cfg = settings.values({})
        return confgen.render_chrony(cfg, env, **QUIET)

    def test_ungueltige_werte_fallen_auf_den_standard(self):
        env = {"CHRONY_LOG": "tracking\ncmdallow all", "MAXUPDATESKEW": "1\nallow all",
               "CLIENTLOGLIMIT": "5 \nallow", "PHC_REFCLOCK_OPTIONS": "poll 0\nallow all"}
        text = self.render(env)
        for bad in ("cmdallow", "allow all"):
            self.assertNotIn(bad, text)
        self.assertIn("maxupdateskew 100.0\n", text)
        self.assertIn("clientloglimit 10000000\n", text)
        self.assertIn("log tracking\n", text)
        notes = " ".join(confgen.expert_env_warnings(env))
        for name in ("CHRONY_LOG", "MAXUPDATESKEW", "CLIENTLOGLIMIT", "PHC_REFCLOCK_OPTIONS"):
            self.assertIn(name, notes)

    def test_gueltige_werte_bleiben(self):
        text = self.render({"CHRONY_LOG": "measurements statistics tracking", "MAXUPDATESKEW": "50.5",
                            "CLIENTLOGLIMIT": "200000"})
        self.assertIn("log measurements statistics tracking\n", text)
        self.assertIn("maxupdateskew 50.5\n", text)
        self.assertIn("clientloglimit 200000\n", text)
        values, notes = confgen.chrony_env_values({"PHC_REFCLOCK_OPTIONS": "poll 0 dpoll -2 offset 0 stratum 1 nocrossts"})
        self.assertEqual(values["phc_options"], "poll 0 dpoll -2 offset 0 stratum 1 nocrossts")
        self.assertEqual(notes, [])

    def test_shm_einheit_als_text_bricht_nicht_ab(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        device = os.path.join(tmp, "ttyGPS")
        Path(device).write_text("", encoding="utf-8")
        cfg = dict(settings.values({}), gps_enable=True, gps_device=device, gps_pps_shm=True, gps_pps_device="")
        text = confgen.render_chrony(cfg, {"GPS_SHM_UNIT": "abc", "GPS_PPS_SHM_UNIT": "1\nallow all"}, **QUIET)
        self.assertIn("refclock SHM 0 refid", text)
        self.assertIn("refclock SHM 1 refid PPS", text)
        self.assertNotIn("allow all", text)


FAKE_CHRONYD = textwrap.dedent("""\
    #!/bin/sh
    # Testersatz für „chronyd -p -f <datei>“: lehnt jede Datei mit der Zeile „ABLEHNEN“ ab.
    file="$3"
    cat "$file"
    if grep -q ABLEHNEN "$file"; then
      echo "2026-01-01T00:00:00Z Fatal error : Invalid directive at line 9 in file $file" >&2
      exit 1
    fi
    exit 0
""")


class ChronydPruefungTest(unittest.TestCase):
    """Lehnt chronyd die neue Konfiguration ab, bleibt die bisherige stehen – und der Grund wird gemeldet."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        fake = os.path.join(self.tmp, "chronyd")
        Path(fake).write_text(FAKE_CHRONYD, encoding="utf-8")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir)
        patches = [
            mock.patch.object(settings, "DATA_DIR", self.tmp),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(self.tmp, "settings.json")),
            mock.patch.object(confgen, "CHRONYD_BIN", fake),
            mock.patch.object(confgen, "CHRONY_CONF", os.path.join(self.tmp, "etc", "chrony.conf")),
            mock.patch.object(confgen, "PTP4L_CONF", os.path.join(self.tmp, "etc", "ptp4l.conf")),
            mock.patch.object(confgen, "CUSTOM_CHRONY", os.path.join(self.tmp, "config", "chrony.conf")),
            mock.patch.object(confgen, "CUSTOM_PTP4L", os.path.join(self.tmp, "config", "ptp4l.conf")),
            mock.patch.object(confgen, "_log", lambda *_a, **_k: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        settings._CACHE.update(mtime=None, data=None)
        self.addCleanup(settings._CACHE.update, mtime=None, data=None)
        self.env = {"GPS_WAIT_SECONDS": "0", "NTPGUI_RUN_DIR": self.run_dir}

    def conf(self):
        return Path(confgen.CHRONY_CONF).read_text(encoding="utf-8")

    def error_file(self):
        return Path(self.run_dir, confgen.CONFIG_ERROR_FILE)

    def test_check_chrony_liefert_den_grund_ohne_pfad(self):
        reason = confgen.check_chrony("server a\nABLEHNEN\n")
        self.assertEqual(reason, "Invalid directive at line 9")
        self.assertIsNone(confgen.check_chrony("server a\n"))
        self.assertIsNone(confgen.check_chrony("ABLEHNEN\n", binary=os.path.join(self.tmp, "fehlt")))

    def test_abgelehnte_konfiguration_ersetzt_die_bisherige_nicht(self):
        confgen.apply(self.env)
        good = self.conf()
        self.assertFalse(self.error_file().exists())
        with self.assertRaises(confgen.ConfigRejected):
            confgen.apply(dict(self.env, EXTRA_CHRONY_CONF="ABLEHNEN"))
        self.assertEqual(self.conf(), good)
        self.assertIn("Invalid directive", self.error_file().read_text(encoding="utf-8"))
        confgen.apply(self.env)
        self.assertFalse(self.error_file().exists(), "nach dem nächsten Erfolg ist die Meldung weg")

    def test_beim_start_ohne_die_gespeicherten_einstellungen(self):
        with mock.patch.object(confgen, "check_chrony",
                               side_effect=lambda text, binary=None: "abgelehnt" if "makestep 9 9" in text else None):
            settings.save({"makestep": "9 9"})
            with self.assertRaises(confgen.ConfigRejected):
                confgen.apply(self.env)
            confgen.apply(self.env, fallback=True)
        self.assertNotIn("makestep 9 9", self.conf())
        self.assertIn("makestep 1.0 3", self.conf())
        self.assertTrue(self.error_file().exists(), "der Supervisor meldet den Start ohne gespeicherte Werte")

    def test_vorschau_nennt_die_ablehnung(self):
        with mock.patch.object(confgen, "check_chrony", return_value="Could not parse makestep directive"):
            shown = confgen.preview({"makestep": "1 3"}, None, self.env)
        self.assertIn("chronyd würde diese Konfiguration ablehnen", shown["notes"][0])

    def test_main_meldet_fehler_mit_exit_code(self):
        with mock.patch.dict(os.environ, dict(self.env, EXTRA_CHRONY_CONF="ABLEHNEN")):
            self.assertEqual(confgen.main(["confgen.py", "apply"]), 1)

    def test_start_ohne_gespeicherte_werte_meldet_keinen_rueckfall(self):
        lines = []
        with mock.patch.object(confgen, "_log", lambda _tag, text: lines.append(text)), \
                self.assertRaises(confgen.ConfigRejected):
            confgen.apply(dict(self.env, EXTRA_CHRONY_CONF="ABLEHNEN"), fallback=True)
        self.assertFalse(any("Start ohne die im Dashboard" in line for line in lines), lines)


class NetguardTest(unittest.TestCase):
    def reason(self, text, purpose="notify", mode=None):
        env = {"OUTBOUND_TARGETS": mode} if mode else {}
        return netguard.reason(ipaddress.ip_address(text), purpose, env)

    def test_metadaten_und_link_local_immer_gesperrt(self):
        for text in ("169.254.169.254", "169.254.170.2", "fe80::1", "fd00:ec2::254", "100.100.100.200", "0.0.0.0",
                     "0.1.2.3", "::", "224.0.0.1", "255.255.255.255", "::ffff:169.254.169.254",
                     "64:ff9b::a9fe:a9fe", "2002:a9fe:a9fe::1"):
            for mode in ("lan", "loopback", "public"):
                with self.subTest(text=text, mode=mode):
                    self.assertIsNotNone(self.reason(text, mode=mode))
                    self.assertIsNotNone(self.reason(text, "dns", mode))

    def test_loopback_nur_mit_schalter(self):
        for text in ("127.0.0.1", "127.1.2.3", "::1", "::ffff:127.0.0.1"):
            with self.subTest(text=text):
                self.assertIsNotNone(self.reason(text))
                self.assertIsNone(self.reason(text, mode="loopback"))
                self.assertIsNone(self.reason(text, "dns"))
                self.assertIsNotNone(self.reason(text, "dns", "public"))

    def test_lan_ziele_gehen_im_standard(self):
        for text in ("192.168.1.5", "10.0.0.2", "172.17.0.3", "fd12:3456::5", "100.64.1.1", "9.9.9.9"):
            with self.subTest(text=text):
                self.assertIsNone(self.reason(text))
        self.assertIsNotNone(self.reason("192.168.1.5", mode="public"))
        self.assertIsNone(self.reason("9.9.9.9", mode="public"))

    def test_unbekannter_modus_gilt_als_standard(self):
        self.assertEqual(netguard.mode({"OUTBOUND_TARGETS": "alles"}), "lan")
        self.assertIn("OUTBOUND_TARGETS", " ".join(confgen.expert_env_warnings({"OUTBOUND_TARGETS": "alles"})))


class NotifyZieleTest(unittest.TestCase):
    def channel(self, url, **extra):
        return {"type": "webhook", "url": url, "secret": "", "topic": "", **extra}

    def deliver(self, channel):
        return notify.deliver(channel, {"title": "t", "text": "x", "level": "info", "kind": "notify", "time": 1.0})

    def test_gesperrte_adresse_wird_beim_speichern_abgelehnt(self):
        for url in ("http://169.254.169.254/latest", "http://[fe80::1]/", "http://127.0.0.1:2375/x",
                    "http://localhost:8000/", "http://[::ffff:169.254.169.254]/"):
            with self.subTest(url=url), self.assertRaisesRegex(notify.NotifyError, "gesperrt"):
                notify.validate({"name": "x", "type": "webhook", "url": url})
        notify.validate({"name": "x", "type": "webhook", "url": "http://192.168.1.5:8123/api/webhook/x"})

    def test_loopback_mit_schalter_erlaubt(self):
        with mock.patch.dict(os.environ, {"OUTBOUND_TARGETS": "loopback"}):
            notify.validate({"name": "x", "type": "webhook", "url": "http://127.0.0.1:8000/"})

    def fake_resolve(self, address):
        def resolve(host, port, *_a, **_k):
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            return [(family, socket.SOCK_STREAM, 6, "", (address, port))]
        return resolve

    def test_name_der_auf_metadaten_zeigt_wird_nach_der_aufloesung_gesperrt(self):
        connects = []
        with mock.patch.object(notify.socket, "getaddrinfo", self.fake_resolve("169.254.169.254")), \
                mock.patch.object(notify.socket.socket, "connect", lambda s, a: connects.append(a)), \
                self.assertRaises(notify.DeliveryError) as caught:
            self.deliver(self.channel("http://metadaten.example.org/"))
        self.assertEqual(connects, [], "keine Verbindung zu einem gesperrten Ziel")
        self.assertEqual(str(caught.exception), notify.UNREACHABLE_TEXT)

    def test_gesperrt_und_geschlossen_sind_nicht_zu_unterscheiden(self):
        with mock.patch.dict(os.environ, {"OUTBOUND_TARGETS": "loopback"}), \
                self.assertRaises(notify.DeliveryError) as closed:
            self.deliver(self.channel(f"http://127.0.0.1:{closed_tcp_port(self)}/"))
        with self.assertRaises(notify.DeliveryError) as blocked:
            self.deliver(self.channel(f"http://127.0.0.1:{closed_tcp_port(self)}/"))
        self.assertEqual(str(closed.exception), str(blocked.exception))
        self.assertEqual(str(blocked.exception), notify.UNREACHABLE_TEXT)

    def test_token_ueber_http_nur_an_aufgeloeste_lokale_adresse(self):
        channel = {"type": "ntfy", "url": "http://ntfy.home", "topic": "t", "secret": "tk_geheim"}
        connects = []
        with mock.patch.object(notify.socket, "getaddrinfo", self.fake_resolve("9.9.9.9")), \
                mock.patch.object(notify.socket.socket, "connect", lambda s, a: connects.append(a)), \
                self.assertRaisesRegex(notify.DeliveryError, "https://"):
            self.deliver(channel)
        self.assertEqual(connects, [])


class TestKnopfBremseTest(unittest.TestCase):
    def setUp(self):
        with notify._TEST_LOCK:
            notify._TEST_TIMES.clear()
            notify._TEST_LAST.clear()
        self.addCleanup(notify._TEST_TIMES.clear)
        self.addCleanup(notify._TEST_LAST.clear)

    def test_je_kanal_und_insgesamt_begrenzt(self):
        notify._test_allowed("a", now=100.0)
        with self.assertRaises(notify.TestRateLimited):
            notify._test_allowed("a", now=101.0)
        notify._test_allowed("a", now=105.5)
        for index, channel in enumerate("bcd"):
            notify._test_allowed(channel, now=106.0 + index)
        with self.assertRaisesRegex(notify.TestRateLimited, "je Minute"):
            notify._test_allowed("e", now=110.0)
        notify._test_allowed("e", now=161.0)


class DnsZieleTest(unittest.TestCase):
    def test_link_local_und_metadaten_sind_nie_dns_server(self):
        for key, value in (("dns_servers", ["169.254.169.254"]), ("dns_servers", ["[fe80::1]:53"]),
                           ("dns_servers", ["100.100.100.200:5353"]), ("dns_dot", ["169.254.169.254:80"]),
                           ("dns_doh", ["https://169.254.169.254/dns-query"]), ("dns_pin", ["dns.example.org=169.254.1.1"]),
                           ("dns_pin", ["dns.example.org=fe80::5"])):
            with self.subTest(key=key, value=value), self.assertRaisesRegex(settings.ValidationError, "gesperrt"):
                settings.validate({key: value})

    def test_loopback_resolver_im_lan_erlaubt_im_modus_public_nicht(self):
        self.assertEqual(settings.validate({"dns_servers": ["127.0.0.1:5335"]})["dns_servers"], ["127.0.0.1:5335"])
        with mock.patch.dict(os.environ, {"OUTBOUND_TARGETS": "public"}):
            for key, value in (("dns_servers", ["127.0.0.1:5335"]), ("dns_dot", ["127.0.0.1:19536"]),
                               ("dns_doh", ["https://127.0.0.1:8443/dns-query"]), ("dns_servers", ["192.168.1.1"])):
                with self.subTest(key=key), self.assertRaises(settings.ValidationError):
                    settings.validate({key: value})
            self.assertEqual(settings.validate({"dns_servers": ["9.9.9.9"]})["dns_servers"], ["9.9.9.9"])


class EcefLueckeTest(unittest.TestCase):
    def test_lange_leerraumfolge_ist_schnell(self):
        code = ("import sys, time; sys.path.insert(0, sys.argv[1]); import egress; t = time.monotonic(); "
                "egress._bs_ecef('1234' + ' ' * 5000 + 'x5678 ' + '9' * 4); "
                "egress._bs_ecef('1234' + ' \\t' * 3000 + ';' + ' ' * 3000 + 'x5678'); "
                "print(time.monotonic() - t)")
        app = str(Path(__file__).resolve().parents[1] / "app")
        try:
            out = subprocess.run([sys.executable, "-c", code, app], capture_output=True, text=True, timeout=20,
                                 check=True)
        except subprocess.TimeoutExpired:
            self.fail("Prüfung der Zahlenlücke braucht zu lange")
        self.assertLess(float(out.stdout.strip()), 2.0)

    def test_erkennung_bleibt(self):
        import egress
        for line in ("4100000, 700000, 4800000", "X: 4100000  Y: 700000   Z: 4800000",
                     "ecef 4100000 cm / 700000 / 4800000"):
            with self.subTest(line=line):
                self.assertTrue(egress._bs_ecef(line))


if __name__ == "__main__":
    unittest.main()
