"""Geführte Fehlersuche „Mein Gerät bekommt keine Zeit“ (1.11): jeder Befundzweig, Eingabeprüfung,
Socket-Liste aus /proc und der Endpunkt (nur mit Anmeldung, rein lesend, keine Namensauflösung)."""

import base64
import http.client
import json
import os
import shutil
import socket
import subprocess
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import clientinfo  # noqa: E402
import clientmon  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import troubleshoot as ts  # noqa: E402

NOW = 1_800_000_000.0
SYNCED = {"synchronised": True, "stratum": 2, "local_reference": False}
CFG = {"allow_networks": list(settings.PRIVATE_NETWORKS), "deny_networks": [], "ntp_port": 123,
       "bind_address": "", "serve_unsynced": True, "ntp_ratelimit": "schonend"}
ROW = {"address": "192.168.1.40", "ntp_packets": 40, "ntp_dropped": 0, "ntp_interval": 6.0, "ntp_last_rx": 20}
ENTRY = {"state": clientmon.OK, "measurable": True, "ewma": 0.002, "requests": 40, "count": 40,
         "last_seen": NOW - 20, "interval": 64.0}


def run(ip="192.168.1.40", cfg=None, **kw):
    args = dict(tracking=SYNCED, chrony_row=ROW, entry=ENTRY, listeners=["0.0.0.0", "::"],
                net_mode="host", gateway=None, others=(), now=NOW)
    args.update(kw)
    return ts.run(ip, {**CFG, **(cfg or {})}, **args)


def check(result, key):
    return next(c for c in result["checks"] if c["key"] == key)


class EingabeTest(unittest.TestCase):
    def test_gueltige_adressen(self):
        self.assertEqual(ts.clean_target(" 192.168.1.5 "), "192.168.1.5")
        self.assertEqual(ts.clean_target("[fd00::1]"), "fd00::1")
        self.assertEqual(ts.clean_target("::ffff:192.168.1.5"), "192.168.1.5")

    def test_namen_und_unsinn_abgelehnt(self):
        for bad in ("", "drucker.lan", "time.windows.com", "192.168.1", "1.2.3.4/24", "fe80::1%eth0",
                    "0.0.0.0", "::", "224.0.0.1", "ff02::1", "255.255.255.255", "x" * 100, "192.168.1.5;rm",
                    "<script>"):
            with self.subTest(bad=bad), self.assertRaises(ts.InputError):
                ts.clean_target(bad)
        with self.assertRaises(ts.InputError) as cm:
            ts.clean_target("nas.fritz.box")
        self.assertIn("Namen", str(cm.exception))

    def test_keine_namensaufloesung(self):
        with mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS")), \
                mock.patch.object(socket, "gethostbyname", side_effect=AssertionError("DNS")), \
                mock.patch.object(socket, "gethostbyaddr", side_effect=AssertionError("DNS")):
            with self.assertRaises(ts.InputError):
                ts.clean_target("router.example")
            run()


class ZugriffTest(unittest.TestCase):
    def test_genaueste_zeile_gilt(self):
        self.assertTrue(ts.access("10.1.2.3", ["10.0.0.0/8"], ["10.1.2.0/24"])["allowed"] is False)
        self.assertTrue(ts.access("10.1.2.3", ["10.1.2.0/24"], ["10.0.0.0/8"])["allowed"])
        self.assertFalse(ts.access("10.1.2.3", ["10.0.0.0/8"], ["10.0.0.0/8"])["allowed"])  # Gleichstand: deny
        self.assertTrue(ts.access("2001:db8::1", ["all"], [])["allowed"])
        self.assertFalse(ts.access("192.168.1.1", ["fd00::/8"], [])["allowed"])

    def test_all_in_ausgenommenen_netzen_sperrt_alle(self):
        # chronyd: „deny all“ nach den allow-Zeilen hebt auch die genaueren allow-Zeilen auf.
        self.assertEqual(ts.access("10.0.0.1", ["10.0.0.0/8"], ["all"]),
                         {"allowed": False, "allow": None, "deny": "all"})
        self.assertFalse(ts.access("fd00::1", ["fd00::/8"], ["ALL"])["allowed"])
        r = run(cfg={"deny_networks": ["all"]})
        self.assertEqual(r["verdict"]["key"], "access")
        self.assertEqual(r["verdict"]["level"], "crit")
        self.assertIn("„all“", r["verdict"]["text"])
        self.assertIn("DENY_NETWORKS", r["verdict"]["next"])

    def test_reihenfolge_wie_confgen(self):
        # allow all, danach genauere deny-Zeilen: die deny-Zeile gilt, der Rest bleibt erlaubt.
        self.assertFalse(ts.access("10.1.2.3", ["all"], ["10.0.0.0/8"])["allowed"])
        self.assertTrue(ts.access("192.168.1.1", ["all"], ["10.0.0.0/8"])["allowed"])
        # „all“ setzt Vorheriges zurück, spätere genauere Zeilen gelten wieder.
        self.assertTrue(ts.access("10.1.2.3", ["192.168.0.0/16", "all", "10.0.0.0/8"], [])["allowed"])
        self.assertEqual(ts.access("10.1.2.3", ["all", "10.0.0.0/8"], [])["allow"], "10.0.0.0/8")
        self.assertFalse(ts.access("10.1.2.3", [], [])["allowed"])

    def test_nicht_erlaubt(self):
        r = run("203.0.113.9", entry=None, chrony_row=None)
        self.assertEqual(r["verdict"]["key"], "access")
        self.assertEqual(r["verdict"]["level"], "crit")
        self.assertIn("ALLOW_NETWORKS", r["verdict"]["next"])
        self.assertEqual(r["verdict"]["action"], "settings")

    def test_ausgenommen(self):
        r = run(cfg={"deny_networks": ["192.168.1.0/24"]})
        self.assertEqual(r["verdict"]["key"], "access")
        self.assertIn("DENY_NETWORKS", r["verdict"]["next"])

    def test_oeffentlich_erlaubt_mit_hinweis(self):
        r = run("203.0.113.9", cfg={"allow_networks": ["all"]}, chrony_row=dict(ROW, address="203.0.113.9"))
        self.assertEqual(check(r, "access")["status"], "ok")
        self.assertIn("öffentlich", check(r, "access")["text"])


class LauschenTest(unittest.TestCase):
    def test_kein_dienst(self):
        r = run(listeners=[])
        self.assertEqual(r["verdict"]["key"], "listen")
        self.assertEqual(r["verdict"]["action"], "diagnose")

    def test_nicht_lesbar_ist_nur_info(self):
        r = run(listeners=None)
        self.assertEqual(check(r, "listen")["status"], "info")
        self.assertEqual(r["verdict"]["key"], "ok")

    def test_bind_nur_ipv4_fuer_ipv6_geraet(self):
        r = run("fd00::5", listeners=["192.168.1.2"], cfg={"bind_address": "192.168.1.2"})
        self.assertEqual(r["verdict"]["key"], "listen")
        self.assertIn("BIND_ADDRESS", r["verdict"]["next"])

    def test_bind_adresse_wird_genannt(self):
        r = run(listeners=["192.168.1.2", "::"], cfg={"bind_address": "192.168.1.2"})
        self.assertEqual(check(r, "listen")["status"], "ok")
        self.assertIn("nur auf 192.168.1.2", check(r, "listen")["text"])

    def test_anderer_port_ohne_anfragen(self):
        r = run(cfg={"ntp_port": 1123}, chrony_row=None, entry=None)
        self.assertEqual(check(r, "listen")["status"], "warn")
        self.assertIn("NTP_PORT", check(r, "listen")["next"])
        self.assertEqual(r["verdict"]["key"], "seen")
        self.assertIn("UDP-Port 1123", r["verdict"]["next"])

    def test_anderer_port_geraet_fragt_erfolgreich(self):
        # Das Gerät fragt nachweislich auf Port 1123 und bekommt Zeit – kein Rat, den Port zu ändern.
        r = run(cfg={"ntp_port": 1123}, chrony_row=dict(ROW, ntp_packets=500),
                entry=dict(ENTRY, requests=500, ewma=0.001))
        self.assertEqual(check(r, "listen")["status"], "ok")
        self.assertIn("fragt bereits Port 1123", check(r, "listen")["text"])
        self.assertEqual(r["verdict"]["key"], "ok")
        self.assertEqual([c["status"] for c in r["checks"]], ["ok"] * 7)

    def test_bridge_anderer_port_nennt_nur_passende_freigabe(self):
        r = run(cfg={"ntp_port": 1123}, net_mode="bridge")
        text = check(r, "listen")["text"]
        self.assertEqual(check(r, "listen")["status"], "ok")
        self.assertIn("123:1123/udp", text)
        self.assertNotIn("123:123/udp", text)
        r = run(net_mode="bridge")
        self.assertIn("123:123/udp", check(r, "listen")["text"])


class ServerTest(unittest.TestCase):
    def test_chronyd_laeuft_nicht(self):
        r = run(tracking={})
        self.assertEqual(r["verdict"]["key"], "server")
        self.assertEqual(r["verdict"]["level"], "crit")

    def test_inselbetrieb(self):
        r = run(tracking={"synchronised": False, "local_reference": True, "stratum": 10})
        self.assertEqual(r["verdict"]["key"], "server")
        self.assertEqual(r["verdict"]["level"], "warn")

    def test_noch_nicht_synchron_mit_inselbetrieb(self):
        r = run(tracking={"synchronised": False, "stratum": 0})
        self.assertEqual(r["verdict"]["level"], "warn")
        self.assertEqual(r["verdict"]["action"], "sources")

    def test_nicht_synchron_ohne_inselbetrieb(self):
        r = run(tracking={"synchronised": False, "stratum": 0}, cfg={"serve_unsynced": False})
        self.assertEqual(r["verdict"]["key"], "server")
        self.assertEqual(r["verdict"]["level"], "crit")
        self.assertIn("SERVE_UNSYNCED=true", r["verdict"]["next"])
        self.assertNotIn("öffentliche", r["verdict"]["text"])

    def test_regel_fuer_oeffentliche_netze(self):
        r = run(tracking={"synchronised": False, "stratum": 0},
                cfg={"serve_unsynced": False, "allow_networks": ["192.168.0.0/16", "all"]})
        self.assertIn("öffentliche Adressen", r["verdict"]["text"])
        self.assertIn("reines LAN", r["verdict"]["next"])


class NetzmodusTest(unittest.TestCase):
    def test_nur_gateway_sichtbar(self):
        r = run(chrony_row=None, entry=None, net_mode="bridge", gateway="172.18.0.1",
                others=["172.18.0.1"])
        self.assertEqual(r["verdict"]["key"], "bridge")
        self.assertIn("network_mode: host", r["verdict"]["next"])
        self.assertEqual(check(r, "seen")["status"], "fail")  # die Prüfliste bleibt vollständig

    def test_host_netz_gateway_egal(self):
        r = run(chrony_row=None, entry=None, net_mode="host", gateway="192.168.1.1", others=["192.168.1.1"])
        self.assertEqual(r["verdict"]["key"], "seen")

    def test_bridge_mit_echter_adresse(self):
        r = run(net_mode="bridge", gateway="172.18.0.1", others=["172.18.0.1", "192.168.1.40"])
        self.assertEqual(check(r, "bridge")["status"], "info")
        self.assertEqual(r["verdict"]["key"], "ok")


class AnfragenTest(unittest.TestCase):
    def test_nichts_angekommen(self):
        r = run(chrony_row=None, entry=None)
        self.assertEqual(r["verdict"]["key"], "seen")
        self.assertTrue(r["verdict"]["snippets"])
        self.assertFalse(r["known"])
        self.assertFalse(r["probe_allowed"])
        self.assertEqual(check(r, "ratelimit")["status"], "skip")
        self.assertEqual(check(r, "clock")["status"], "skip")

    def test_nur_chrony_kennt_das_geraet(self):
        r = run(entry=None)
        self.assertEqual(check(r, "seen")["status"], "ok")
        self.assertEqual(check(r, "clock")["status"], "info")
        self.assertEqual(r["verdict"]["key"], "ok")

    def test_verstummt(self):
        entry = dict(ENTRY, last_seen=NOW - 3 * 86400, requests=30)
        r = run(chrony_row=None, entry=entry)
        self.assertEqual(r["verdict"]["key"], "seen")
        self.assertEqual(r["verdict"]["level"], "warn")
        self.assertIn("verstummt", r["verdict"]["text"])


class BegrenzungTest(unittest.TestCase):
    def test_teilweise_verworfen(self):
        r = run(chrony_row=dict(ROW, ntp_packets=100, ntp_dropped=10))
        self.assertEqual(r["verdict"]["key"], "ratelimit")
        self.assertEqual(r["verdict"]["level"], "warn")
        self.assertIn("NTP_RATELIMIT", r["verdict"]["next"])

    def test_meist_verworfen(self):
        r = run(chrony_row=dict(ROW, ntp_packets=100, ntp_dropped=80))
        self.assertEqual(r["verdict"]["level"], "crit")

    def test_lan_rat_zum_lockern(self):
        r = run(chrony_row=dict(ROW, ntp_packets=100, ntp_dropped=10))
        self.assertIn("schonend", r["verdict"]["next"])

    def test_oeffentlich_kein_rat_zum_lockern(self):
        # Öffentliche Adresse oder öffentlich erlaubte Netze: nur das Abfrageintervall des Geräts, keine Lockerung.
        for ip, nets in (("203.0.113.9", ["all"]), ("192.168.1.40", list(settings.PRIVATE_NETWORKS) + ["0.0.0.0/0"])):
            with self.subTest(ip=ip):
                r = run(ip, cfg={"allow_networks": nets, "ntp_ratelimit": "streng"},
                        chrony_row=dict(ROW, address=ip, ntp_packets=100, ntp_dropped=10))
                self.assertEqual(r["verdict"]["key"], "ratelimit")
                nxt = r["verdict"]["next"]
                self.assertIn("Abfrageintervall", nxt)
                self.assertIn("nicht lockern", nxt)
                self.assertNotIn("schonend", nxt)
                self.assertNotIn("„aus“", nxt)

    def test_ohne_chrony_zeile_nur_info(self):
        r = run(chrony_row=None)
        self.assertEqual(check(r, "ratelimit")["status"], "info")


class UhrTest(unittest.TestCase):
    def test_falsche_uhr(self):
        r = run(entry=dict(ENTRY, state=clientmon.WRONG_CLOCK, ewma=5 * 86400.0))
        self.assertEqual(r["verdict"]["key"], "clock")
        self.assertEqual(r["verdict"]["level"], "crit")
        self.assertTrue(r["verdict"]["snippets"])

    def test_grosse_abweichung(self):
        r = run(entry=dict(ENTRY, ewma=3.5))
        self.assertEqual(r["verdict"]["key"], "clock")
        self.assertEqual(r["verdict"]["level"], "warn")
        self.assertIn("+3,5 s", r["verdict"]["text"])

    def test_nicht_messbar_mit_nachmessen(self):
        entry = dict(ENTRY, state=clientmon.OBFUSCATED, measurable=False, ewma=None, obfuscated=40, count=0)
        r = run(entry=entry)
        self.assertEqual(check(r, "clock")["status"], "info")
        self.assertTrue(r["probe_allowed"])
        self.assertIn("Aktiv nachmessen", check(r, "clock")["text"])
        self.assertEqual(r["verdict"]["key"], "ok")

    def test_kein_nachmessen_bei_oeffentlicher_adresse(self):
        r = run("203.0.113.9", cfg={"allow_networks": ["all"]})
        self.assertFalse(r["probe_allowed"])
        r = run("fe80::1", entry=ENTRY)
        self.assertFalse(r["probe_allowed"])

    def test_alles_in_ordnung(self):
        r = run()
        self.assertEqual(r["verdict"]["key"], "ok")
        self.assertEqual(r["verdict"]["level"], "ok")
        self.assertEqual([c["key"] for c in r["checks"]],
                         ["access", "listen", "server", "bridge", "seen", "ratelimit", "clock"])


class BefundTest(unittest.TestCase):
    def test_problem_vor_hinweis_und_genau_ein_befund(self):
        # Hinweis (Inselbetrieb) steht früher in der Liste als das Problem (Begrenzung) – das Problem gewinnt.
        r = run(tracking={"synchronised": False, "local_reference": True, "stratum": 10},
                chrony_row=dict(ROW, ntp_packets=10, ntp_dropped=9))
        self.assertEqual(r["verdict"]["key"], "ratelimit")
        self.assertIsInstance(r["verdict"], dict)


class SocketListeTest(unittest.TestCase):
    def test_proc_net_udp(self):
        with tempfile.TemporaryDirectory() as tmp:
            v4 = os.path.join(tmp, "udp")
            v6 = os.path.join(tmp, "udp6")
            head = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            lan = "%08X" % struct.unpack("<I", socket.inet_aton("192.168.1.2"))[0]
            with open(v4, "w") as f:
                f.write(head + "  1: 00000000:007B 00000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 1\n"
                        + f"  2: {lan}:007B 00000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 2\n"
                        + "  3: 0100007F:0035 00000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 3\n")
            with open(v6, "w") as f:
                f.write(head + "  1: 00000000000000000000000000000000:007B 00000000000000000000000000000000:0000 07 x\n"
                        + "  2: 000080FE00000000FF0000AA00BB00CC:007B 00000000000000000000000000000000:0000 07 x\n")
            found = ts.udp_listeners(123, (v4, v6))
            self.assertEqual(found[:3], ["0.0.0.0", "192.168.1.2", "::"])
            self.assertEqual(len(found), 4)
            self.assertTrue(found[3].startswith("fe80::"))
            self.assertEqual(ts.udp_listeners(53, (v4,)), ["127.0.0.1"])
            self.assertEqual(ts.udp_listeners(9999, (v4,)), [])
            self.assertIsNone(ts.udp_listeners(123, (os.path.join(tmp, "fehlt"),)))


class EndpunktTest(unittest.TestCase):
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
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        _, cls.read_key = apikeys.create("Lesen", "read")

    @classmethod
    def tearDownClass(cls):
        import apikeys
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        cls.server.AUTH_CACHE.clear()
        cls.tmp.cleanup()

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def basic(self):
        return {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode()}

    def test_nur_mit_anmeldung(self):
        for path in ("/api/clients/troubleshoot?ip=192.168.1.40", "/api/v1/clients/troubleshoot?ip=192.168.1.40"):
            self.assertEqual(self.get(path)[0], 401, path)

    def test_nur_get(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = dict(self.basic(), **{"X-NTP-GUI": "1", "Content-Type": "application/json"})
        conn.request("POST", "/api/clients/troubleshoot", body=b'{"ip": "192.168.1.40"}', headers=headers)
        status = conn.getresponse().status
        conn.close()
        self.assertIn(status, (404, 405))

    def test_befund_und_eingabe(self):
        import chrony
        import devices
        row = dict(ROW, ntp_dropped=30, ntp_packets=40)
        with mock.patch.object(chrony, "clients", return_value=[row]), \
                mock.patch.object(chrony, "tracking", return_value=dict(SYNCED)), \
                mock.patch.object(devices, "network_mode", return_value="host"), \
                mock.patch.object(ts, "udp_listeners", return_value=["0.0.0.0"]), \
                mock.patch.object(clientinfo, "reverse_name", side_effect=AssertionError("DNS")), \
                mock.patch.object(socket, "gethostbyaddr", side_effect=AssertionError("DNS")):
            status, data = self.get("/api/clients/troubleshoot?ip=192.168.1.40", self.basic())
            bearer = {"Authorization": f"Bearer {self.read_key}"}
            status_key, _ = self.get("/api/v1/clients/troubleshoot?ip=192.168.1.40", bearer)
            bad = self.get("/api/clients/troubleshoot?ip=drucker.lan", self.basic())
            empty = self.get("/api/clients/troubleshoot", self.basic())
        self.assertEqual(status, 200, data)
        self.assertEqual(status_key, 200)
        self.assertEqual(data["verdict"]["key"], "ratelimit")
        self.assertEqual(data["verdict"]["level"], "crit")
        self.assertEqual(bad[0], 400)
        self.assertIn("Namen", bad[1]["error"])
        self.assertEqual(empty[0], 400)

    def test_keine_messung_ausgeloest(self):
        import chrony
        with mock.patch.object(chrony, "clients", return_value=[]), \
                mock.patch.object(chrony, "tracking", return_value=dict(SYNCED)), \
                mock.patch.object(clientinfo, "ntp_query", side_effect=AssertionError("Messung")), \
                mock.patch.object(clientinfo, "probe", side_effect=AssertionError("Messung")):
            status, data = self.get("/api/clients/troubleshoot?ip=192.168.1.41", self.basic())
        self.assertEqual(status, 200, data)
        self.assertEqual(data["verdict"]["key"] in {"seen", "listen", "bridge"}, True)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class KarteTest(unittest.TestCase):
    """Die Karte im echten JS-Interpreter: Befund auch bei Langform/Großschreibung/::ffff:-Eingabe."""

    def run_js(self, body: str):
        from test_frontend_states import DOM
        js = Path(__file__).resolve().parents[1] / "app" / "static" / "js"
        page = json.dumps((js / "pages" / "troubleshoot.js").resolve().as_uri())
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dom.mjs").write_text(DOM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            script.write_text('import { text, ctx } from "./dom.mjs";\n'
                              f"const ts = await import({page});\n" + body, encoding="utf-8")
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_befund_bei_anderer_schreibweise(self):
        out = self.run_js(r"""
const answers = { "FD00:0:0::0001": "fd00::1", "::ffff:192.168.1.10": "192.168.1.10", "[fd00::1]": "fd00::1",
  "192.168.1.77": "192.168.1.77" };
let asked = "";
globalThis.fetch = async (url) => {
  asked = decodeURIComponent(String(url).split("ip=")[1]);
  const body = { address: answers[asked], lan: true, known: false, probe_allowed: false, checks: [],
    verdict: { key: "seen", level: "fail", title: "Anfragen angekommen", text: "BEFUND", next: null } };
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
};
const out = {};
for (const input of Object.keys(answers)) {
  ts._reset();
  const c = ctx();
  await ts.run(c, input);
  const card = ts.troubleshootCard(c, null);
  const find = (n) => (n.tagName === "INPUT" ? n : (n.childNodes || []).map(find).find(Boolean));
  const field = find(card);
  out[input] = { shown: text(card).includes("BEFUND"), field: field.value ?? field.attrs.value ?? null };
}
console.log(JSON.stringify(out));
""")
        for raw in ("FD00:0:0::0001", "::ffff:192.168.1.10", "[fd00::1]", "192.168.1.77"):
            with self.subTest(raw=raw):
                self.assertTrue(out[raw]["shown"], out)
        self.assertEqual(out["::ffff:192.168.1.10"]["field"], "192.168.1.10")
        self.assertEqual(out["FD00:0:0::0001"]["field"], "fd00::1")

    def test_sprungziel_von_der_diagnose(self):
        out = self.run_js(r"""
const after = [];
window.location.hash = "#/clients?s=fehlersuche";
const c = ctx({ afterRender: (fn) => after.push(fn) });
ts.troubleshootCard(c, null);
ts.troubleshootCard(c, null);  // Neuzeichnen im Hintergrund springt nicht erneut
window.location.hash = "#/clients";
const plain = ctx({ afterRender: (fn) => after.push(fn) });
ts.troubleshootCard(plain, null);
console.log(JSON.stringify({ jumps: after.length, scrolled: c.uiState.scrolled === true }));
""")
        self.assertEqual(out, {"jumps": 1, "scrolled": True})


if __name__ == "__main__":
    unittest.main()
