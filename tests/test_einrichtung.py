"""Willkommens-Assistent (1.6, T3): Erststart/Update, setup_done, Checkliste, Rechte, „Überspringen ändert nichts“.

Testaufbau „ohne Volume, ohne SYS_TIME“: derselbe gefälschte Host wie im Hardware-Check (test_hardware.FakeHost)
mit den Docker-Standardrechten; Schritt (a) muss beide Probleme mit je einer Abhilfe nennen.
Nur Beispielwerte (RFC 5737); keine Verbindung nach außen.
"""

import base64
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import apikeys  # noqa: E402
import onboarding  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
from test_hardware import CAP_DEFAULT, HardwareTestCase, base_cfg  # noqa: E402

JS = APP / "static" / "js"
NTS_SOURCES = [{"type": "server", "host": "ptbtime1.ptb.de", "nts": True, "prefer": False, "noselect": False,
                "options": ""}]


class DataDirCase(unittest.TestCase):
    """Eigenes, leeres Datenverzeichnis je Test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [mock.patch.object(settings, "DATA_DIR", self.tmp),
                        mock.patch.object(settings, "SETTINGS_FILE", os.path.join(self.tmp, "settings.json"))]
        for patch in self.patches:
            patch.start()
        onboarding._MEMORY.clear()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        onboarding._MEMORY.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stored(self):
        with open(os.path.join(self.tmp, onboarding.STATE_NAME), encoding="utf-8") as handle:
            return json.load(handle)


class ErststartTest(DataDirCase):
    def test_leeres_datenverzeichnis_ist_erststart(self):
        st = onboarding.state(now=1793527200)
        self.assertEqual(st["install"], "fresh")
        self.assertIsNone(st["done"])
        self.assertEqual(self.stored()["install"], "fresh")
        brief = onboarding.brief(readonly=False)
        self.assertTrue(brief["auto_open"])
        self.assertFalse(brief["hint"])
        self.assertTrue(brief["checklist"])

    def test_bestehende_daten_sind_ein_update(self):
        for name in ("settings.json", "ntp-gui.db", "history.json.gz", "autocal.json", "instance-id"):
            with self.subTest(name=name):
                onboarding._MEMORY.clear()
                for leftover in os.listdir(self.tmp):
                    os.unlink(os.path.join(self.tmp, leftover))
                with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as handle:
                    handle.write("{}")
                self.assertEqual(onboarding.state()["install"], "update")
                brief = onboarding.brief(readonly=False)
                self.assertFalse(brief["auto_open"], "Update von 1.5.x: kein automatischer Assistent")
                self.assertTrue(brief["hint"], "… nur der dezente Hinweis „Einrichtung prüfen“")
                self.assertFalse(brief["checklist"])

    def test_leere_dateien_und_ordner_zaehlen_nicht(self):
        open(os.path.join(self.tmp, "settings.json"), "w").close()
        os.mkdir(os.path.join(self.tmp, "sicherungen"))
        self.assertFalse(onboarding.existing_install(self.tmp))
        with open(os.path.join(self.tmp, "sicherungen", "nacht-20261108.tar.gz"), "wb") as handle:
            handle.write(b"x")
        self.assertTrue(onboarding.existing_install(self.tmp))

    def test_entscheidung_bleibt_auch_wenn_spaeter_daten_entstehen(self):
        self.assertEqual(onboarding.state()["install"], "fresh")
        with open(os.path.join(self.tmp, "settings.json"), "w", encoding="utf-8") as handle:
            handle.write('{"values": {}}')
        self.assertEqual(onboarding.state()["install"], "fresh")

    def test_hinweis_nur_einmal_und_schliessbar(self):
        with open(os.path.join(self.tmp, "settings.json"), "w", encoding="utf-8") as handle:
            handle.write('{"values": {}}')
        self.assertTrue(onboarding.brief(False)["hint"])
        onboarding.action("close_hint", now=1793527300)
        self.assertFalse(onboarding.brief(False)["hint"])
        self.assertEqual(self.stored()["hint_closed"], 1793527300)
        self.assertIsNone(self.stored()["done"])

    def test_setup_done_und_zuruecksetzen(self):
        onboarding.state()
        st = onboarding.action("done", now=1793527400)
        self.assertEqual(st["done"], 1793527400)
        brief = onboarding.brief(False)
        self.assertFalse(brief["auto_open"])
        self.assertTrue(brief["done"])
        self.assertTrue(brief["checklist"], "nach „Fertig“ steht die Checkliste auf der Übersicht")
        onboarding.action("close_checklist", now=1793527500)
        self.assertFalse(onboarding.brief(False)["checklist"])
        onboarding.action("reset")
        self.assertTrue(onboarding.brief(False)["auto_open"])
        with self.assertRaises(ValueError):
            onboarding.action("alles_loeschen")

    def test_nicht_mehr_zeigen_schliesst_auch_die_checkliste(self):
        # „Nicht mehr zeigen“ heißt Ruhe: kein Assistent, kein Hinweis und keine Checkliste auf der Übersicht.
        onboarding.state()
        st = onboarding.action("never", now=1793527450)
        self.assertEqual((st["done"], st["checklist_closed"], st["hint_closed"]), (1793527450,) * 3)
        brief = onboarding.brief(False)
        self.assertFalse(brief["auto_open"] or brief["hint"] or brief["checklist"])
        onboarding.action("reset")
        self.assertTrue(onboarding.brief(False)["checklist"])

    def test_wiederherstellen_auf_frischer_installation_ist_bestehend(self):
        # Sicherung auf neuer Karte eingespielt: kein Assistent mehr von selbst, sondern einmal „Einrichtung prüfen“.
        self.assertEqual(onboarding.state()["install"], "fresh")
        st = onboarding.restored()
        self.assertEqual(st["install"], "update")
        self.assertEqual(self.stored()["install"], "update")
        brief = onboarding.brief(False)
        self.assertFalse(brief["auto_open"])
        self.assertTrue(brief["hint"])

    def test_wiederherstellen_nach_fertig_aendert_nichts(self):
        onboarding.state()
        onboarding.action("done", now=1793527400)
        self.assertEqual(onboarding.restored()["install"], "fresh")
        self.assertTrue(onboarding.brief(False)["checklist"])

    def test_nur_lesen_oeffnet_nichts_von_selbst(self):
        brief = onboarding.brief(readonly=True)
        self.assertFalse(brief["auto_open"] or brief["hint"] or brief["checklist"])

    def test_kaputte_datei_wird_neu_entschieden(self):
        with open(os.path.join(self.tmp, onboarding.STATE_NAME), "w", encoding="utf-8") as handle:
            handle.write('{"install": "irgendwas"}')
        self.assertIn(onboarding.state()["install"], {"fresh", "update"})

    def test_nicht_schreibbar_nur_im_speicher(self):
        with mock.patch.object(onboarding, "_write", side_effect=OSError("nur lesbar")):
            self.assertEqual(onboarding.state()["install"], "fresh")
            onboarding.action("done", now=1793527600)
            self.assertTrue(onboarding.brief(False)["done"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, onboarding.STATE_NAME)))


class ServerStartTest(unittest.TestCase):
    """server.py legt beim Import die Datenbank an – die Entscheidung fällt trotzdem vorher."""

    def run_server_import(self, data_dir):
        env = dict(os.environ, NTPGUI_DATA_DIR=data_dir)
        code = ("import server, onboarding, json, os; onboarding.remember(); "
                "print(json.dumps({'install': onboarding.state()['install'], 'files': sorted(os.listdir(%r))}))"
                % data_dir)
        out = subprocess.run([sys.executable, "-c", code], cwd=str(APP), env=env, capture_output=True, text=True,
                             timeout=60, check=True)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_frische_installation(self):
        with tempfile.TemporaryDirectory() as data:
            first = self.run_server_import(data)
            self.assertEqual(first["install"], "fresh")
            self.assertIn("ntp-gui.db", first["files"])  # beim Import angelegt – zählt nicht
            self.assertIn(onboarding.STATE_NAME, first["files"])
            # Neustart des Containers ohne „Fertig“: bleibt Erststart.
            self.assertEqual(self.run_server_import(data)["install"], "fresh")

    def test_update_von_15(self):
        with tempfile.TemporaryDirectory() as data:
            with open(os.path.join(data, "settings.json"), "w", encoding="utf-8") as handle:
                json.dump({"schema": 4, "values": {"web_title": "Zeitserver"}}, handle)
            self.assertEqual(self.run_server_import(data)["install"], "update")


class PruefenTest(HardwareTestCase):
    """Schritt (a) mit dem Testaufbau „ohne Volume, ohne SYS_TIME“."""

    def test_ohne_volume_ohne_sys_time_beide_probleme_mit_abhilfe(self):
        self.host.caps(CAP_DEFAULT)
        rep = self.run_report(base_cfg())
        found = onboarding.checks(base_cfg(), rep, {"persistent": False})
        problems = {c["key"]: c for c in found if c["status"] == "problem"}
        self.assertEqual(set(problems), {"volume", "sys_time"})
        for check in problems.values():
            with self.subTest(check=check["key"]):
                self.assertTrue(check["remedy"], "jeder rote Punkt hat genau eine Abhilfe")
                self.assertIsInstance(check["fix"], str)
        self.assertEqual(problems["sys_time"]["fix"], "cap_add:\n  - SYS_TIME")
        self.assertIn("/var/lib/chrony", problems["volume"]["fix"])
        self.assertIn("volumes:", problems["volume"]["fix"])
        # Checkliste: Punkt „Prüfen“ offen und zählt beide.
        items = {i["id"]: i for i in onboarding.checklist(base_cfg(), rep, {"persistent": False}, {}, 0, 0)["items"]}
        self.assertFalse(items["check"]["ok"])
        self.assertEqual(items["check"]["count"], 2)

    def test_volume_abhilfe_enthaelt_die_deklaration(self):
        # Der Kopieren-Knopf muss beide Teile liefern: den Eintrag beim Dienst und „chrony-data:“ auf oberster Ebene,
        # sonst bricht „docker compose up -d“ ab (Volume nicht definiert).
        found = {c["key"]: c for c in onboarding.checks({}, {"matrix": []}, {"persistent": False})}
        fix = found["volume"]["fix"].splitlines()
        self.assertTrue(any(line.strip() == "- chrony-data:/var/lib/chrony" for line in fix), fix)
        top = [i for i, line in enumerate(fix) if line == "volumes:"]
        self.assertTrue(top, f"„volumes:“ auf oberster Ebene fehlt: {fix}")
        self.assertIn("  chrony-data:", fix[top[-1] + 1:], fix)
        self.assertLess(fix.index(next(l for l in fix if l.strip() == "- chrony-data:/var/lib/chrony")), top[-1])

    def test_mit_volume_und_sys_time_alles_gruen(self):
        rep = self.run_report(base_cfg())
        found = onboarding.checks(base_cfg(), rep, {"persistent": True})
        self.assertEqual([c for c in found if c["status"] == "problem"], [])
        self.assertEqual({c["key"] for c in found} >= {"volume", "sys_time", "gps"}, True)


class ChecklisteTest(unittest.TestCase):
    REPORT = {"matrix": [{"key": "clock_control", "status": "ok", "text": "darf stellen"}], "gps": {"receivers": []}}

    def items(self, cfg, tracking, clients=0, channels=0, report=None):
        result = onboarding.checklist(cfg, report or self.REPORT, {"persistent": True}, tracking, clients, channels)
        return result, {i["id"]: i for i in result["items"]}

    def test_vier_von_fuenf_ist_gruen_benachrichtigung_optional(self):
        result, items = self.items({"ntp_sources": NTS_SOURCES}, {"synchronised": True}, clients=3)
        self.assertEqual((result["done"], result["total"]), (4, 5))
        self.assertTrue(result["complete"])
        self.assertTrue(items["notify"]["optional"])
        self.assertFalse(items["notify"]["ok"])

    def test_ohne_nts_oder_ohne_sync_offen(self):
        pool = [{"type": "pool", "host": "pool.ntp.org", "nts": False}]
        result, items = self.items({"ntp_sources": pool}, {"synchronised": True}, clients=1)
        self.assertFalse(items["sources"]["ok"])
        self.assertFalse(result["complete"])
        _, items = self.items({"ntp_sources": NTS_SOURCES}, {"synchronised": False}, clients=1)
        self.assertFalse(items["sources"]["ok"])

    def test_gps_gefunden_aber_aus_ist_offen(self):
        report = dict(self.REPORT, gps={"receivers": [{"gps_like": True, "product": "u-blox 7", "dev": "/dev/ttyACM0",
                                                       "stable_path": "/dev/serial/by-id/usb-u-blox"}]})
        _, items = self.items({"ntp_sources": NTS_SOURCES}, {"synchronised": True}, report=report)
        self.assertFalse(items["gps"]["ok"])
        self.assertTrue(items["gps"]["receiver"])
        self.assertEqual(onboarding.gps_receiver(report)["device"], "/dev/serial/by-id/usb-u-blox")
        _, items = self.items({"ntp_sources": NTS_SOURCES}, {"synchronised": True})
        self.assertTrue(items["gps"]["ok"], "kein Empfänger, GPS aus: nichts zu tun")

    def test_clients_und_benachrichtigung(self):
        _, items = self.items({"ntp_sources": NTS_SOURCES}, {"synchronised": True}, clients=0, channels=1)
        self.assertFalse(items["clients"]["ok"])
        self.assertTrue(items["notify"]["ok"])


class ChecklisteBleibtWegTest(DataDirCase):
    """Einmal alles grün: Die Karte kommt nicht wieder, auch wenn chrony kurz die Synchronisation verliert."""

    REPORT = ChecklisteTest.REPORT

    def summary(self, synced):
        return onboarding.summary({"ntp_sources": NTS_SOURCES}, self.REPORT, {"persistent": True},
                                  {"synchronised": synced}, 2, 0, readonly=False, can_write=True)

    def test_einmal_gruen_bleibt_weg(self):
        onboarding.action("done", now=1793527400)
        first = self.summary(synced=True)["checklist"]
        self.assertTrue(first["complete"])
        self.assertFalse(first["show"])
        self.assertTrue(self.stored()["checklist_done"])
        again = self.summary(synced=False)["checklist"]
        self.assertFalse(again["complete"], "der Punkt selbst darf ehrlich offen sein")
        self.assertFalse(again["show"], "nach einmal „alles grün“ kommt die Karte nicht wieder")
        self.assertFalse(onboarding.brief(False)["checklist"])
        onboarding.action("reset")
        self.assertTrue(self.summary(synced=False)["checklist"]["show"])

    def test_nicht_gruen_wird_nicht_gemerkt(self):
        onboarding.action("done", now=1793527400)
        self.assertTrue(self.summary(synced=False)["checklist"]["show"])
        self.assertIsNone(self.stored().get("checklist_done"))

    def test_nur_lesen_merkt_nichts(self):
        onboarding.summary({"ntp_sources": NTS_SOURCES}, self.REPORT, {"persistent": True},
                           {"synchronised": True}, 2, 0, readonly=True, can_write=False)
        self.assertIsNone(self.stored().get("checklist_done"))


class ApiTest(unittest.TestCase):
    """GET/POST /api/setup und /api/v1/setup: Rechte, CSRF/Origin, WEB_READONLY, „Überspringen ändert nichts“."""

    REPORT = {"matrix": [{"key": "clock_control", "status": "ok", "text": "darf stellen"}],
              "gps": {"receivers": [], "role": {"role": "off", "label": "aus"}}}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"}),
            mock.patch.object(server.hardware, "report", lambda cfg, refresh=False: cls.REPORT),
            mock.patch.object(server.chrony, "tracking", lambda: {"synchronised": True}),
            mock.patch.object(server.chrony, "clients", lambda: [{"address": "192.0.2.10"}]),
            mock.patch.object(server, "trigger_reload", lambda: False),
        ]
        for patch in cls.patches:
            patch.start()
        os.environ.pop("WEB_READONLY", None)
        onboarding._MEMORY.clear()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        _, cls.read_key = apikeys.create("Lesen", "read")
        _, cls.admin_key = apikeys.create("Verwalten", "admin")

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        onboarding._MEMORY.clear()
        cls.tmp.cleanup()

    def setUp(self):
        path = os.path.join(self.tmp.name, onboarding.STATE_NAME)
        if os.path.exists(path):
            os.unlink(path)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        data = json.dumps(body).encode() if body is not None else None
        hdrs = dict(headers or {})
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

    def basic(self, csrf=True):
        out = {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode()}
        if csrf:
            out["X-NTP-GUI"] = "1"
        return out

    def snapshot(self):
        """Inhalt aller Dateien im Datenverzeichnis außer Datenbank und Zustand des Assistenten."""
        out = {}
        for name in sorted(os.listdir(self.tmp.name)):
            path = os.path.join(self.tmp.name, name)
            if os.path.isfile(path) and not name.startswith(("ntp-gui.db", onboarding.STATE_NAME)):
                with open(path, "rb") as handle:
                    out[name] = handle.read()
        return out

    def test_lesen_v1_und_alt(self):
        for path in ("/api/setup", "/api/v1/setup"):
            with self.subTest(path=path):
                status, payload = self.request("GET", path, headers=self.basic())
                self.assertEqual(status, 200)
                for key in ("install", "done", "auto_open", "hint", "checks", "checklist", "can_write"):
                    self.assertIn(key, payload)
                self.assertTrue(payload["can_write"])
                self.assertEqual(payload["clients"]["count"], 1)
        self.assertEqual(self.request("GET", "/api/setup")[0], 401)

    def test_beschrieben_in_api_v1(self):
        status, payload = self.request("GET", "/api/v1", headers=self.basic())
        self.assertEqual(status, 200)
        found = {(e["method"], e["path"]): e["scope"] for e in payload["endpoints"]}
        self.assertEqual(found[("GET", "/api/v1/setup")], "read")
        self.assertEqual(found[("POST", "/api/v1/setup")], "admin")

    def test_schreiben_braucht_csrf_und_verwaltungsrecht(self):
        self.assertEqual(self.request("POST", "/api/setup", {"action": "done"}, self.basic(csrf=False))[0], 403)
        foreign = dict(self.basic(), Origin="http://198.51.100.7")
        self.assertEqual(self.request("POST", "/api/setup", {"action": "done"}, foreign)[0], 403)
        status, payload = self.request("POST", "/api/v1/setup", {"action": "done"},
                                       {"Authorization": f"Bearer {self.read_key}"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["scope_required"], "admin")
        status, payload = self.request("GET", "/api/setup", headers={"Authorization": f"Bearer {self.read_key}"})
        self.assertEqual(status, 200)
        self.assertFalse(payload["can_write"], "Leserecht: Assistent nur lesend")
        self.assertFalse(onboarding.brief(False)["done"])
        status, payload = self.request("POST", "/api/v1/setup", {"action": "done"},
                                       {"Authorization": f"Bearer {self.admin_key}"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["done"])
        self.assertEqual(self.request("POST", "/api/setup", {"action": "kaputt"}, self.basic())[0], 400)

    def test_web_readonly_sperrt(self):
        with mock.patch.dict(os.environ, {"WEB_READONLY": "true"}):
            self.assertEqual(self.request("POST", "/api/setup", {"action": "done"}, self.basic())[0], 403)
            status, payload = self.request("GET", "/api/setup", headers=self.basic())
            self.assertEqual(status, 200)
            self.assertFalse(payload["can_write"] or payload["auto_open"] or payload["hint"])
            self.assertFalse(payload["checklist"]["show"])
        self.assertFalse(onboarding.brief(False)["done"])

    def test_ueberspringen_aendert_nichts(self):
        before = self.snapshot()
        settings_before = settings.values()["ntp_sources"]
        # Alles, was der Assistent beim Durchklicken ohne „Übernehmen“ tut: lesen und Vorschau.
        for path in ("/api/setup", "/api/settings", "/api/notify", "/api/setup?x=1"):
            self.assertEqual(self.request("GET", path, headers=self.basic())[0], 200, path)
        preview = {"changes": {"ntp_sources": settings_before + NTS_SOURCES}}
        status, payload = self.request("POST", "/api/settings/preview", preview, self.basic())
        self.assertEqual(status, 200, payload)
        self.assertEqual(self.snapshot(), before, "Überspringen darf keine Datei ändern")
        self.assertEqual(settings.values()["ntp_sources"], settings_before)
        self.assertFalse(onboarding.brief(False)["done"], "setup_done nur mit „Fertig“")

    def test_uebernehmen_laeuft_ueber_die_einstellungen(self):
        # Ungültige Quelle: dieselbe Prüfung wie die Einstellungsseite.
        status, payload = self.request("POST", "/api/settings", {"changes": {"ntp_sources": [
            {"type": "server", "host": "bad host;", "nts": True}]}}, self.basic())
        self.assertEqual(status, 422)
        self.assertIn("ntp_sources", payload.get("fields", {}))

    def test_wiederherstellen_stellt_frische_installation_um(self):
        onboarding.state()
        with open(os.path.join(self.tmp.name, onboarding.STATE_NAME), "w", encoding="utf-8") as handle:
            json.dump({"install": "fresh", "first_seen": 1793527200}, handle)
        with mock.patch.object(server.backup, "apply", lambda token, version, emit=None: {"ok": True, "changed": []}):
            status, payload = self.request("POST", "/api/restore/apply", {"token": "x"}, self.basic())
        self.assertEqual(status, 200, payload)
        self.assertEqual(onboarding.state()["install"], "update")
        self.assertTrue(onboarding.brief(False)["hint"])

    def test_status_nennt_kurzfassung(self):
        status = server.build_status
        with mock.patch.object(server, "build_status", lambda: {"ui": {"setup": onboarding.brief(False)},
                                                                 "insights": []}):
            code, payload = self.request("GET", "/api/status", headers=self.basic())
        self.assertIs(server.build_status, status)
        self.assertEqual(code, 200)
        self.assertIn("auto_open", payload["ui"]["setup"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class FrontendTest(unittest.TestCase):
    """Routen, Schritte und Vorlagen (ohne DOM) – und dass die Seite nur über bestehende Wege schreibt."""

    def test_routen_und_schritte(self):
        script = """
const r = await import(%s);
console.log(JSON.stringify({
  first: r.setupHref(0), sources: r.setupHref("sources"), notify: r.setupHref(4),
  resolved: r.resolve("#/system/einrichtung/quellen").page.id, sub: r.resolve("#/system/einrichtung/quellen").sub,
  steps: r.SETUP_STEPS.map((s) => s.key), action: r.actionHref("setup"),
}));
""" % json.dumps((JS / "routes.js").as_uri())
        out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                             timeout=60, check=True)
        data = json.loads(out.stdout)
        self.assertEqual(data["first"], "#/system/einrichtung")
        self.assertEqual(data["sources"], "#/system/einrichtung/quellen")
        self.assertEqual(data["notify"], "#/system/einrichtung/benachrichtigung")
        self.assertEqual((data["resolved"], data["sub"]), ("setup", "quellen"))
        self.assertEqual(data["steps"], list(onboarding.CHECKLIST))
        self.assertEqual(data["action"], "#/system/einrichtung")

    def test_seite_schreibt_nur_ueber_bestehende_wege(self):
        text = (JS / "pages" / "setup.js").read_text(encoding="utf-8")
        posts = set(__import__("re").findall(r'apiPost\("([^"]+)"', text))
        self.assertEqual(posts, {"/api/settings/preview", "/api/settings", "/api/setup"})
        self.assertNotIn("fetch(", text)
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("innerHTML", text)
        self.assertNotRegex(text, r"\.style\.|style:")

    def test_vorlagen_sind_feste_nts_liste(self):
        settings_js = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
        for host in ("ptbtime1.ptb.de", "time.cloudflare.com", "nts.netnod.se"):
            self.assertIn(f'"{host}", true', settings_js)

    def test_uebersicht_zeigt_checkliste(self):
        overview = (JS / "pages" / "overview.js").read_text(encoding="utf-8")
        self.assertIn('ctx.data("setup", "/api/setup"', overview)
        self.assertIn("setupCard(ctx, status.ui?.setup)", overview)
        app = (JS / "app.js").read_text(encoding="utf-8")
        self.assertIn("auto_open", app)
        self.assertIn("ntp-gui-setup-opened", app)


if __name__ == "__main__":
    unittest.main()
