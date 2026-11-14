"""Studiouhr A6: Link-Baukasten und benannte Profile der Vollbild-Uhr (/clock?p=name).

  * Schema: clockprofiles.PARAMS (Server) und PARAM_SCHEMA (clockkit.js) nennen dieselben Parameter mit denselben
    Typen, Werten und Grenzen; Voreinstellungen sind gültig und in beiden Listen gleich.
  * Allowlist: Fremdfelder, unbekannte Parameter, Standortangaben und Namen außerhalb [a-z0-9-]{1,32} werden
    abgewiesen; der Lesepfad liefert nur name, title, params, builtin (und profiles_rev).
  * Rechte am echten HTTP-Handler: ohne clock_public nur mit Anmeldung, mit clock_public ohne; Schreiben nur über
    POST /api/settings mit Anmeldung und Pflicht-Kopf X-NTP-GUI. profiles_rev ändert sich beim Speichern.
  * Sicherung: Profile überstehen die Rundreise, ein manipuliertes Profil wird beim Wiederherstellen übersprungen.
  * Reine Funktionen aus clocklink.js mit Node: Link bauen, Schichten (Profil < Adresse, gemerkter Stand nur ohne
    Parameter), Vorschaugrößen, Formulargruppen.
"""

import base64
import http.client
import io
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

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, fake_hostnames, stop_http_server  # noqa: E402

import backup  # noqa: E402
import clockprofiles  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

PROFILE = {"title": "Regie 1", "params": {"design": "studio", "until": "20:15", "label": "bis ON AIR",
                                          "show": "time,date", "accent": "ff8800", "tz": "UTC", "lock": "1"}}


def run_node(code: str):
    kit = json.dumps((JS / "clockkit.js").as_uri())
    link = json.dumps((JS / "clocklink.js").as_uri())
    script = f"import * as k from {kit};\nimport * as l from {link};\n{code}"
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class SchemaGleichTest(unittest.TestCase):
    def test_server_und_uhr_kennen_dieselben_parameter(self):
        schema = run_node("console.log(JSON.stringify(k.PARAM_SCHEMA))")
        self.assertEqual([e["name"] for e in schema], list(clockprofiles.PARAMS))
        for entry in schema:
            kind, info = clockprofiles.PARAMS[entry["name"]]
            with self.subTest(name=entry["name"]):
                self.assertEqual(entry["type"], kind)
                if kind in ("enum", "list"):
                    self.assertEqual(entry["values"], list(info["values"]))
                if kind in ("int", "intlist"):
                    self.assertEqual((entry["min"], entry["max"]), (info["min"], info["max"]))
                if kind == "intlist":
                    self.assertEqual(entry["maxItems"], info["max_items"])
                if kind == "label":
                    self.assertEqual(entry["len"], info["len"])
        self.assertNotIn("lat", clockprofiles.PARAMS)
        self.assertNotIn("lon", clockprofiles.PARAMS)
        palette = run_node("console.log(JSON.stringify(Object.keys(k.PALETTE)))")
        self.assertEqual(palette, list(clockprofiles.PALETTE))

    def test_voreinstellungen_gueltig_und_gleich(self):
        names = run_node("console.log(JSON.stringify(l.PRESETS))")
        self.assertEqual(names, list(clockprofiles.PRESETS))
        self.assertEqual(set(names), {"studio", "tile", "banner", "kitchen", "workshop", "night", "nerd"})
        presets = json.dumps({n: p["params"] for n, p in clockprofiles.PRESETS.items()})
        out = run_node(f"""
          const presets = {presets};
          const bad = [];
          for (const [name, params] of Object.entries(presets)) {{
            const parsed = k.parseParams(new URLSearchParams(params).toString());
            if (parsed.ignored.length) bad.push(name + ":" + parsed.ignored.join(","));
          }}
          console.log(JSON.stringify(bad));
        """)
        self.assertEqual(out, [])
        for name, preset in clockprofiles.PRESETS.items():
            with self.subTest(preset=name):
                self.assertEqual(clockprofiles.clean_profile(preset)["params"], preset["params"])
        self.assertEqual(clockprofiles.PRESETS["studio"]["params"]["shift"], "1")
        self.assertEqual(clockprofiles.PRESETS["tile"]["params"]["layout"], "tile")


class AllowlistTest(unittest.TestCase):
    def test_gueltiges_profil(self):
        clean = clockprofiles.clean_profiles({"regie": PROFILE, "kueche-2": {"params": {"timer": "10m"}}})
        self.assertEqual(clean["regie"]["params"]["accent"], "ff8800")
        self.assertEqual(clean["regie"]["title"], "Regie 1")
        self.assertEqual(clean["kueche-2"], {"title": "", "params": {"timer": "10m"}})
        # Schema-Reihenfolge wie in der Adresse
        self.assertEqual(list(clean["regie"]["params"]), ["design", "tz", "show", "accent", "until", "label", "lock"])

    def test_fremdfelder_abgewiesen(self):
        bad = [
            {"regie": {"title": "x", "params": {}, "rundown": []}},
            {"regie": {"params": {"lat": "48.1"}}},
            {"regie": {"params": {"lon": "11.5"}}},
            {"regie": {"params": {"script": "x"}}},
            {"regie": {"params": {"design": "<b>"}}},
            {"regie": {"params": {"accent": "red;background:url(x)"}}},
            {"regie": {"params": {"label": "<script>"}}},
            {"regie": {"params": {"label": "a‮b"}}},
            {"regie": {"params": {"label": "x" * 25}}},
            {"regie": {"params": {"until": "2026-02-31T10:00"}}},
            {"regie": {"params": {"timer": "25h"}}},
            {"regie": {"params": {"warn": "300,300"}}},
            {"regie": {"params": {"show": "time,nerd"}}},
            {"regie": {"params": {"tz": "Mars/Olymp"}}},
            {"regie": {"params": {"tz": "../../etc/passwd"}}},
            {"regie": {"params": {"scale": "500"}}},
            {"regie": {"params": {"design": "x" * 70}}},
            {"regie": {"title": "t" * 41}},
            {"regie": {"title": 5}},
            {"regie": "kein Objekt"},
            ["liste"],
        ]
        for value in bad:
            with self.subTest(value=str(value)[:60]):
                with self.assertRaises(clockprofiles.ProfileError):
                    clockprofiles.clean_profiles(value)
                with self.assertRaises(settings.ValidationError):
                    settings.validate({"clock_profiles": value})

    def test_profilnamen(self):
        for name in ("Regie", "regie 1", "regie_1", "../x", "", "x" * 33, "rég", "a.b", "studio", "nerd"):
            with self.subTest(name=name):
                with self.assertRaises(clockprofiles.ProfileError):
                    clockprofiles.clean_profiles({name: {"params": {}}})
        for name in ("regie", "r", "regie-1", "0", "x" * 32):
            self.assertIn(name, clockprofiles.clean_profiles({name: {"params": {}}}))
        with self.assertRaises(clockprofiles.ProfileError):
            clockprofiles.clean_profiles({f"p{i}": {"params": {}} for i in range(21)})
        self.assertEqual(len(clockprofiles.clean_profiles({f"p{i}": {"params": {}} for i in range(20)})), 20)

    def test_kein_angehaengter_zeilenumbruch(self):
        # `$` passt in Python auch vor einem abschließenden "\n"; Server und Uhr müssen gleich streng sein.
        bad = [{"studio\n": {"params": {}}}, {"regie\n": {"params": {}}}]
        for key, value in (("accent", "ff8800\n"), ("until", "20:15\n"), ("until", "2026-05-01T10:00\n"),
                           ("timer", "5m\n"), ("tz", "UTC\n"), ("scale", "100\n"), ("warn", "300\n")):
            bad.append({"regie": {"params": {key: value}}})
        for value in bad:
            with self.subTest(value=repr(value)):
                with self.assertRaises(clockprofiles.ProfileError):
                    clockprofiles.clean_profiles(value)
        self.assertIsNone(clockprofiles.public_profile("regie\n", {"regie": PROFILE}))

    def test_titel_ohne_steuerzeichen(self):
        clean = clockprofiles.clean_profiles({"regie": {"title": "Regie\u0007‮ 1\n", "params": {}}})
        self.assertNotRegex(clean["regie"]["title"], r"[\x00-\x1f‮]")

    def test_lesepfad_nur_allowlist(self):
        # Gespeicherter Stand, an der Prüfung vorbei manipuliert: nichts davon darf hinaus.
        stored = {"regie": {"title": "Regie", "params": {"design": "studio", "lat": "48.1", "until": "<x>"},
                            "secret": "geheim", "notes": "intern"}}
        out = clockprofiles.public_profile("regie", stored)
        self.assertEqual(set(out), {"name", "title", "params", "builtin"})
        self.assertEqual(out["params"], {"design": "studio"})
        self.assertFalse(out["builtin"])
        self.assertTrue(clockprofiles.public_profile("studio", stored)["builtin"])
        for name in ("Regie", "../regie", "", None, "x" * 33):
            self.assertIsNone(clockprofiles.public_profile(name, stored))
        self.assertIsNone(clockprofiles.public_profile("fehlt", stored))

    def test_revision(self):
        a = clockprofiles.revision({})
        b = clockprofiles.revision({"regie": PROFILE})
        self.assertNotEqual(a, b)
        self.assertEqual(b, clockprofiles.revision(json.loads(json.dumps({"regie": PROFILE}))))
        self.assertRegex(a, r"^[0-9a-f]{12}$")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patch in (mock.patch.object(settings, "DATA_DIR", tmp.name),
                      mock.patch.object(settings, "SETTINGS_FILE", os.path.join(tmp.name, "settings.json"))):
            patch.start()
            self.addCleanup(patch.stop)

    def test_feld_ohne_neustart_und_nicht_im_formular(self):
        field = settings.FIELDS["clock_profiles"]
        self.assertEqual(field["restart"], settings.RESTART_NONE)
        self.assertEqual(field["type"], "clockprofiles")
        page = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
        self.assertIn('f.type !== "clockprofiles"', page)

    def test_profiles_rev_aendert_sich_beim_speichern(self):
        tracking = {"synchronised": True, "stratum": 1, "ref_name": "GPS", "root_delay": 0.0,
                    "root_dispersion": 0.0001, "system_time_offset": 0.0, "leap_status": "Normal"}
        with mock.patch.object(server, "_clock_tracking", return_value=tracking):
            first = server.time_payload(1.0, public=True)["profiles_rev"]
            settings.save({"clock_profiles": {"regie": PROFILE}})
            second = server.time_payload(2.0, public=True)["profiles_rev"]
            settings.save({"web_title": "Anderes"})
            third = server.time_payload(3.0, public=True)["profiles_rev"]
            settings.save({"clock_profiles": {"regie": dict(PROFILE, title="Regie 2")}})
            fourth = server.time_payload(4.0, public=True)["profiles_rev"]
        self.assertNotEqual(first, second)
        self.assertEqual(second, third, "andere Einstellungen ändern profiles_rev nicht")
        self.assertNotEqual(third, fourth)

    def test_profil_payload(self):
        settings.save({"clock_profiles": {"regie": PROFILE}})
        body, status = server.profile_payload("regie")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"name", "title", "params", "builtin", "profiles_rev"})
        self.assertEqual(server.profile_payload("fehlt")[1], 404)
        self.assertEqual(server.profile_payload("Regie")[1], 400)
        self.assertEqual(server.profile_payload("regie\n")[1], 400)
        self.assertEqual(server.profile_payload(None), ({"presets": list(clockprofiles.PRESETS)}, 200))
        self.assertNotIn("regie", json.dumps(server.profile_payload(None)[0]), "ohne p keine gespeicherten Namen")


class ProfilHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"}),
            mock.patch.object(server.chrony, "tracking", return_value={"synchronised": True, "stratum": 2,
                                                                       "ref_name": "nas.fritz.box"}),
        ]
        for patch in cls.patches:
            patch.start()
        os.environ.pop("CLOCK_PUBLIC", None)
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        server.AUTH_CACHE.clear()
        cls.tmp.cleanup()

    def setUp(self):
        fake_hostnames(self)
        server._CLOCK_CACHE.update(t=None, tracking=None)
        settings.save({"clock_profiles": {"regie": PROFILE}})

    def request(self, path, auth=False, method="GET", body=None, csrf=False, host="example.com"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host}
        if auth:
            headers["Authorization"] = "Basic " + base64.b64encode(b"admin:geheim123").decode()
        if body is not None:
            headers["Content-Type"] = "application/json"
        if csrf:
            headers["X-NTP-GUI"] = "1"
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        headers_out = dict(resp.getheaders())
        conn.close()
        return resp.status, data, headers_out

    def set_public(self, value):
        patcher = mock.patch.dict(os.environ, {"CLOCK_PUBLIC": "true" if value else "false"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ohne_clock_public_nur_mit_anmeldung(self):
        self.set_public(False)
        for path in ("/api/v1/clock/profile?p=regie", "/api/v1/clock/profile?p=studio", "/static/js/clocklink.js"):
            self.assertEqual(self.request(path)[0], 401, path)
        status, body, headers = self.request("/api/v1/clock/profile?p=regie", auth=True)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["params"]["until"], "20:15")
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_mit_clock_public_ohne_anmeldung_nur_allowlist(self):
        self.set_public(True)
        status, body, headers = self.request("/api/v1/clock/profile?p=regie", host="uhr.example.org")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(set(payload), {"name", "title", "params", "builtin", "profiles_rev"})
        self.assertEqual(set(payload["params"]) - set(clockprofiles.PARAMS), set())
        self.assertNotIn(b"fritz", body)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(self.request("/api/v1/clock/profile?p=Regie")[0], 400)
        self.assertEqual(self.request("/api/v1/clock/profile?p=fehlt")[0], 404)
        self.assertEqual(self.request("/static/js/clocklink.js", host="uhr.example.org")[0], 200)
        time_payload = json.loads(self.request("/api/v1/time", host="uhr.example.org")[1])
        self.assertEqual(time_payload["profiles_rev"], payload["profiles_rev"])
        # Schreiben bleibt geschützt, auch mit clock_public.
        self.assertEqual(self.request("/api/settings", method="POST", body={"changes": {"clock_profiles": {}}},
                                      csrf=True)[0], 401)

    def test_schreiben_nur_mit_anmeldung_und_csrf(self):
        self.set_public(True)
        before = json.loads(self.request("/api/v1/time")[1])["profiles_rev"]
        changes = {"changes": {"clock_profiles": {"regie": dict(PROFILE, title="Neu")}}}
        self.assertEqual(self.request("/api/settings", method="POST", body=changes, auth=True)[0], 403, "ohne X-NTP-GUI")
        self.assertEqual(json.loads(self.request("/api/v1/time")[1])["profiles_rev"], before)
        bad = {"changes": {"clock_profiles": {"regie": {"params": {"lat": "48.1"}}}}}
        self.assertEqual(self.request("/api/settings", method="POST", body=bad, auth=True, csrf=True)[0], 422)
        status, _body, _h = self.request("/api/settings", method="POST", body=changes, auth=True, csrf=True)
        self.assertEqual(status, 200)
        after = json.loads(self.request("/api/v1/time")[1])["profiles_rev"]
        self.assertNotEqual(before, after)
        self.assertEqual(json.loads(self.request("/api/v1/clock/profile?p=regie")[1])["title"], "Neu")


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ntpgui-profil-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.patches = []
        self.use_dir(os.path.join(self.tmp, "alt"))
        self.addCleanup(self.stop_dirs)

    def use_dir(self, path):
        store.close_all()
        backup.discard()
        os.makedirs(path, exist_ok=True)
        for patch in self.patches:
            patch.stop()
        self.patches = [mock.patch.object(settings, "DATA_DIR", path),
                        mock.patch.object(settings, "SETTINGS_FILE", os.path.join(path, "settings.json"))]
        for patch in self.patches:
            patch.start()

    def stop_dirs(self):
        store.close_all()
        backup.discard()
        for patch in self.patches:
            patch.stop()

    def test_rundreise(self):
        profiles = {"regie": PROFILE, "flur": {"title": "Flur", "params": {"design": "bahnhof"}}}
        settings.save({"clock_profiles": profiles})
        path = os.path.join(self.tmp, "sicherung.tar.gz")
        backup.create(path, "test")
        data = Path(path).read_bytes()
        self.use_dir(os.path.join(self.tmp, "neu"))
        staged = backup.stage_upload(io.BytesIO(data), len(data))
        self.assertFalse(staged["preview"]["settings"]["skipped"])
        backup.apply(staged["token"])
        self.assertEqual(settings.values()["clock_profiles"], clockprofiles.clean_profiles(profiles))

    def test_manipuliertes_profil_wird_uebersprungen(self):
        plan = backup._settings_plan({"schema": settings.SCHEMA_VERSION, "values": {
            "clock_profiles": {"regie": {"params": {"lat": "48.1"}}}, "web_title": "Uhr"}})
        self.assertNotIn("clock_profiles", plan["values"])
        self.assertEqual([s["key"] for s in plan["skipped"]], ["clock_profiles"])
        self.assertEqual(plan["values"]["web_title"], "Uhr")


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class LinkFunktionenTest(unittest.TestCase):
    def test_link_bauen(self):
        out = run_node("""
          console.log(JSON.stringify({
            empty: l.buildQuery({}),
            defaults: l.buildQuery({ layout: "auto", scale: "100", lz: "1", warn: "300,60,10", design: "" }),
            mixed: l.buildQuery({ label: "bis ON AIR", design: "studio", until: "20:15", bogus: "1", accent: "x;y",
              show: "time,date", tz: "Mars/Olymp" }),
            href: [l.clockHref(""), l.clockHref("design=studio"), l.clockHref("", "regie"), l.clockHref("kiosk=1", "regie"),
              l.clockHref("", "../x")],
            raw: l.rawParams("?design=studio&design=nixie&scale=500&lat=48&label=%3Cb%3E&kiosk=1"),
          }));
        """)
        self.assertEqual(out["empty"], "")
        self.assertEqual(out["defaults"], "", "Standardwerte gehören nicht in den Link")
        self.assertEqual(out["mixed"], "design=studio&show=time,date&until=20:15&label=bis+ON+AIR")
        self.assertEqual(out["href"], ["/clock", "/clock?design=studio", "/clock?p=regie", "/clock?p=regie&kiosk=1", "/clock"])
        self.assertEqual(out["raw"], {"design": "studio", "kiosk": "1"})

    def test_schichten(self):
        out = run_node("""
          const profile = { design: "studio", kiosk: "1", until: "20:15", lat: "48" };
          const stored = "design=flip&scale=120";
          console.log(JSON.stringify({
            profileOnly: l.effectiveQuery({ search: "?p=regie", profile, stored }),
            profileUrl: l.effectiveQuery({ search: "?p=regie&kiosk=0&design=nixie", profile, stored }),
            stored: l.effectiveQuery({ search: "", stored }),
            storedIgnored: l.effectiveQuery({ search: "?design=wort", stored }),
            invalidUrl: l.effectiveQuery({ search: "?design=%3Cb%3E", stored }),
            otherParam: l.effectiveQuery({ search: "?foo=1", stored }),
            storedBad: l.effectiveQuery({ search: "", stored: "design=<b>&lat=1&scale=120" }),
            storedLong: l.effectiveQuery({ search: "", stored: "scale=120&" + "x".repeat(3000) }),
            name: [l.profileFromSearch("?p=regie-1"), l.profileFromSearch("?p=Regie"), l.profileFromSearch("?p=a/b"),
              l.profileFromSearch("")],
          }));
        """)
        self.assertEqual(out["profileOnly"], "design=studio&kiosk=1&until=20%3A15")
        self.assertEqual(out["profileUrl"], "design=nixie&kiosk=0&until=20%3A15", "Adresse schlägt Profil")
        self.assertEqual(out["stored"], "design=flip&scale=120")
        self.assertEqual(out["storedIgnored"], "design=wort", "mit Parametern gilt die Adresse, nicht der Speicher")
        self.assertEqual(out["invalidUrl"], "")
        self.assertEqual(out["otherParam"], "design=flip&scale=120")
        self.assertEqual(out["storedBad"], "scale=120")
        self.assertEqual(out["storedLong"], "")
        self.assertEqual(out["name"], ["regie-1", None, None, None])

    def test_vorschau_und_formular(self):
        out = run_node("""
          console.log(JSON.stringify({
            sizes: l.PREVIEW_SIZES, features: l.previewFeatures("phone"), fallback: l.previewFeatures("gibtsnicht"),
            grouped: l.FORM_GROUPS.flatMap((g) => g.names), schema: k.PARAM_SCHEMA.map((e) => e.name),
          }));
        """)
        self.assertEqual(set(out["sizes"]), {"phone", "monitor", "banner", "tile", "stele"})
        self.assertEqual(out["sizes"]["tile"], {"width": 480, "height": 270})
        self.assertGreaterEqual(out["sizes"]["banner"]["width"] / out["sizes"]["banner"]["height"], 3)
        self.assertLess(out["sizes"]["stele"]["width"] / out["sizes"]["stele"]["height"], 1 / 1.6 + 0.01)
        self.assertEqual(out["features"], "popup=yes,width=390,height=844,noopener=yes,noreferrer=yes")
        self.assertIn("width=1280", out["fallback"])
        self.assertEqual(sorted(out["grouped"]), sorted(out["schema"]), "jeder Parameter genau einmal im Formular")
        self.assertEqual(len(out["grouped"]), len(set(out["grouped"])))

    def test_profil_neuversuch_nach_fehlschlag(self):
        out = run_node("""
          const base = { name: "regie", rev: "r1" };
          console.log(JSON.stringify({
            failedDue: l.profileStep({ ...base, loaded: false, error: "error", now: 6000, retryAt: 5000 }),
            failedWait: l.profileStep({ ...base, loaded: false, error: "error", now: 4000, retryAt: 5000 }),
            loginDue: l.profileStep({ ...base, loaded: false, error: "login", now: 9e9, retryAt: 0 }),
            failedNoRev: l.profileStep({ name: "regie", loaded: false, error: "error", rev: null, now: 1, retryAt: 0 }),
            failedBusy: l.profileStep({ ...base, loaded: false, error: "error", busy: true, now: 9e9 }),
            missingAdopt: l.profileStep({ ...base, loaded: false, error: "missing" }),
            loadedAdopt: l.profileStep({ ...base, loaded: true }),
            same: l.profileStep({ ...base, loaded: true, seenRev: "r1" }),
            changed: l.profileStep({ ...base, loaded: true, seenRev: "r0" }),
            noProfile: l.profileStep({ name: null, rev: "r1", loaded: false, error: "error" }),
            delays: [0, 1, 2, 3, 4, 5, 50, -1].map(l.profileRetryDelay),
          }));
        """)
        self.assertEqual(out["failedDue"], "retry", "nicht geladenes Profil wird erneut abgerufen")
        self.assertEqual(out["failedWait"], "none")
        self.assertEqual(out["loginDue"], "retry")
        self.assertEqual(out["failedNoRev"], "retry", "Neuversuch hängt nicht an profiles_rev")
        self.assertEqual(out["failedBusy"], "none")
        self.assertEqual(out["missingAdopt"], "adopt", "fehlendes Profil wartet auf eine Änderung von profiles_rev")
        self.assertEqual(out["loadedAdopt"], "adopt")
        self.assertEqual(out["same"], "none")
        self.assertEqual(out["changed"], "refetch")
        self.assertEqual(out["noProfile"], "none")
        self.assertEqual(out["delays"], [5000, 10000, 20000, 40000, 60000, 60000, 60000, 5000])

    def test_gemerkter_stand_ohne_kiosk_lock_und_nicht_fuer_profile(self):
        out = run_node("""
          const stored = l.buildQuery({ kiosk: "1", lock: "1", design: "flip" });
          console.log(JSON.stringify({
            skip: l.STORE_SKIP,
            storedClean: l.storedQuery(stored),
            plain: l.effectiveQuery({ search: "", stored }),
            onlyModes: l.effectiveQuery({ search: "", stored: "kiosk=1&lock=1" }),
            profileNotLoaded: l.effectiveQuery({ search: "?p=x", stored }),
            profileInvalidName: l.effectiveQuery({ search: "?p=../x", stored }),
            urlKiosk: l.effectiveQuery({ search: "?kiosk=1", stored }),
            presetKey: [l.presetTitleKey({ name: "kitchen", builtin: true }), l.presetTitleKey({ name: "kitchen", builtin: false }),
              l.presetTitleKey({ name: "regie", builtin: true }), l.presetTitleKey(null)],
          }));
        """)
        self.assertEqual(out["skip"], ["kiosk", "lock"])
        self.assertEqual(out["storedClean"], "design=flip")
        self.assertEqual(out["plain"], "design=flip", "kiosk/lock aus dem Speicher wirken nicht")
        self.assertEqual(out["onlyModes"], "")
        self.assertEqual(out["profileNotLoaded"], "", "Profil-Bildschirm ohne Profil zeigt nicht den gemerkten Stand")
        self.assertEqual(out["profileInvalidName"], "design=flip")
        self.assertEqual(out["urlKiosk"], "kiosk=1", "in der Adresse bleibt kiosk erlaubt")
        self.assertEqual(out["presetKey"], ["pages.displays.preset.kitchen", None, None, None])

    def test_kachel_nicht_im_gemerkten_stand(self):
        out = run_node("""
          console.log(JSON.stringify({
            values: l.STORE_SKIP_VALUES,
            tile: l.storedQuery("layout=tile&design=flip"),
            banner: l.storedQuery("layout=banner&design=flip"),
            plain: l.effectiveQuery({ search: "", stored: "layout=tile&scale=120" }),
            url: l.effectiveQuery({ search: "?layout=tile", stored: "" }),
          }));
        """)
        self.assertEqual(out["values"], {"layout": ["tile"]})
        self.assertEqual(out["tile"], "design=flip", "layout=tile sperrte Leiste und Anpassen aus")
        self.assertEqual(out["banner"], "design=flip&layout=banner")
        self.assertEqual(out["plain"], "scale=120")
        self.assertEqual(out["url"], "layout=tile", "in der Adresse bleibt die Kachel erlaubt")
        js = (JS / "clock.js").read_text(encoding="utf-8")
        self.assertIn("excludeValues: link.STORE_SKIP_VALUES", js)
        link_js = (JS / "clocklink.js").read_text(encoding="utf-8")
        self.assertIn("!(excludeValues[name] || []).includes(v)", link_js)
        for lang, word in (("de", "Kachel"), ("en", "tile")):
            data = json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
            self.assertIn(word, data["clock"]["custom_line"])

    def test_design_aus_der_leiste_passt_gemerkten_stand_an(self):
        out = run_node("""
          console.log(JSON.stringify({
            changed: l.storedWith("design=nixie&scale=120", "design", "flip"),
            untouched: l.storedWith("scale=120", "design", "flip"),
            toDefault: l.storedWith("design=nixie", "design", "digital"),
            empty: l.storedWith("", "design", "flip"),
            cleaned: l.storedWith("design=nixie&kiosk=1", "design", "wort"),
          }));
        """)
        self.assertEqual(out["changed"], "design=flip&scale=120")
        self.assertEqual(out["untouched"], "scale=120", "ohne gemerktes Design gilt DESIGN_KEY")
        self.assertEqual(out["toDefault"], "design=digital")
        self.assertEqual(out["empty"], "")
        self.assertEqual(out["cleaned"], "design=wort")
        js = (JS / "clock.js").read_text(encoding="utf-8")
        start = js.index("function setDesign(")
        body = js[start:js.index("\n}\n", start)]
        self.assertIn('link.storedWith(stored, "design", state.design, ZONES)', body)
        # Nur wenn der gemerkte Stand für diese Adresse gilt (kein Profil, keine Parameter).
        self.assertIn("link.storedApplies(window.location.search) ? store(link.STORE_KEY) : null", body)

    def test_gemerkter_stand_gilt_nur_ohne_parameter(self):
        out = run_node("""
          console.log(JSON.stringify({
            plain: l.storedApplies(""),
            q: l.storedApplies("?"),
            unknown: l.storedApplies("?foo=1"),
            design: l.storedApplies("?design=wort&lock=0"),
            profile: l.storedApplies("?p=studio"),
          }));
        """)
        self.assertTrue(out["plain"])
        self.assertTrue(out["q"])
        self.assertTrue(out["unknown"], "fremde Parameter gehören nicht zum Schema")
        self.assertFalse(out["design"])
        self.assertFalse(out["profile"])

    def test_texte_fuer_panel_und_voreinstellungen(self):
        out = run_node("console.log(JSON.stringify({ show: k.SHOW_ITEMS, presets: l.PRESETS }));")
        for lang in ("de", "en"):
            data = json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
            with self.subTest(lang=lang):
                items = data["clock"]["link"]["show_item"]
                self.assertEqual(sorted(items), sorted(out["show"]))
                self.assertTrue(data["clock"]["link"]["example_label"])
                self.assertEqual(sorted(data["pages"]["displays"]["preset"]), sorted(out["presets"]))
        text = (JS / "clocklink.js").read_text(encoding="utf-8")
        self.assertNotIn('"bis ON AIR"', text, "Platzhalter kommt aus i18n")
        self.assertIn("clock.link.show_item.", text)

    def test_rotlicht_deckt_formular_und_hinweise(self):
        css = (ROOT / "app" / "static" / "clock.css").read_text(encoding="utf-8")
        start = css.index(':root[data-mode="red"] {')
        block = css[start:css.index("}", start)]
        for name in ("--surface-3", "--warn-ink", "--crit-ink", "--good-ink", "color-scheme: dark"):
            with self.subTest(name=name):
                self.assertIn(name, block)
        self.assertRegex(block, r"--warn-ink:\s*#ff2a1a")
        self.assertRegex(css, r"\.clock-custom \.link-check input \{ accent-color: var\(--accent\); \}")

    def test_schalter_ohne_anmeldung_ohne_aria_pressed(self):
        text = (JS / "pages" / "displays.js").read_text(encoding="utf-8")
        self.assertNotIn("\"aria-pressed\"", text, "wechselnde Beschriftung und aria-pressed widersprechen sich")
        self.assertIn("st.loaded", text)

    def test_keine_iframes_und_keine_inline_styles(self):
        for path in (JS / "clocklink.js", JS / "pages" / "displays.js"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotRegex(text, r"[\"'`<]iframe", "Vorschau nur im neuen Fenster")
                self.assertNotIn("innerHTML", text)
                self.assertNotRegex(text, r"\.style\.|setAttribute\(\s*\"style\"")
        self.assertIn("frame-ancestors 'none'", (ROOT / "app" / "server.py").read_text(encoding="utf-8"))
