"""T2 GUI-Erneuerung, Teil „Einstellungen 2.0“ (docs/konzept/version-1.6.md, Punkt 4).

  * Speichervorschau: Vorschau == Datei nach apply – für mehrere Einstellungssätze, in Temp-Verzeichnissen
    (die Vorschau schreibt nichts, kopiert keine NTS-Dateien; der Diff ergibt angewandt genau die neue Datei).
  * Endpunkt POST /api/settings/preview: nur mit Verwaltungsrecht, CSRF-/Origin-Prüfung wie Speichern,
    Größenbegrenzung, kein Pfad aus der Anfrage, keine Geheimnisse im Diff.
  * „zurücksetzen“ = auf den Standard, erst mit dem Speichern (auch gegen einen Wert aus der Umgebung).
  * Hilfetexte: je Feld höchstens eine sichtbare Zeile (≤ 140 Zeichen), der Rest im ⓘ – nichts geht verloren.
  * Keine Versionsgeschichte („Standard ab 1.5.2“) in der Oberfläche.
  * Suche (settings.js im echten JS-Interpreter): findet jedes Feld nach Name, Schlüssel und ⓘ-Text, Reiter
    für jeden Abschnitt, alte Sprungziele (?s=gps, ?s=web …) landen im richtigen Reiter.
"""

import base64
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import apikeys  # noqa: E402
import confgen  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

GPS_DEVICE = "/dev/null"   # existiert überall – confgen schreibt dann die Refclock-Zeile
PPS_DEVICE = "/dev/zero"


def apply_unified(old: str, diff: list[str]) -> str:
    """Wendet einen Zeilen-Diff (difflib.unified_diff, lineterm="") auf old an."""
    lines = old.splitlines()
    out: list[str] = []
    pos = 0
    hunk = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    for line in diff:
        if line.startswith(("---", "+++")):
            continue
        match = hunk.match(line)
        if match:
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) is not None else 1
            start = start - 1 if count else start  # „-0,0“: vor der ersten Zeile
            out.extend(lines[pos:start])
            pos = start
            continue
        tag, text = line[:1], line[1:]
        if tag == " ":
            assert lines[pos] == text, (lines[pos], text)
            out.append(text)
            pos += 1
        elif tag == "-":
            assert lines[pos] == text, (lines[pos], text)
            pos += 1
        elif tag == "+":
            out.append(text)
    out.extend(lines[pos:])
    return "\n".join(out) + ("\n" if out else "")


class TempConfig(unittest.TestCase):
    """Eigenes Datenverzeichnis und eigene Konfigurationsdateien je Test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        tmp = self.tmp
        patches = [
            mock.patch.object(settings, "DATA_DIR", tmp),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(tmp, "settings.json")),
            mock.patch.object(confgen, "CHRONY_CONF", os.path.join(tmp, "etc", "chrony.conf")),
            mock.patch.object(confgen, "PTP4L_CONF", os.path.join(tmp, "etc", "ptp4l.conf")),
            mock.patch.object(confgen, "CUSTOM_CHRONY", os.path.join(tmp, "config", "chrony.conf")),
            mock.patch.object(confgen, "CUSTOM_PTP4L", os.path.join(tmp, "config", "ptp4l.conf")),
            mock.patch.object(confgen, "NTS_CERT_DIR", os.path.join(tmp, "nts-certs")),
            mock.patch.object(confgen, "_log", lambda *_a, **_k: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        settings._CACHE.update(mtime=None, data=None)
        self.addCleanup(settings._CACHE.update, mtime=None, data=None)
        self.env = {"GPS_WAIT_SECONDS": "0"}

    def read(self, path):
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read()
        except FileNotFoundError:
            return None

    def snapshot(self):
        out = {}
        for base, _dirs, names in os.walk(self.tmp):
            for name in names:
                path = os.path.join(base, name)
                with open(path, "rb") as handle:
                    out[path] = handle.read()
        return out


class VorschauGleichDateiTest(TempConfig):
    # (Name, gespeicherte Werte vorher, Umgebung, Änderungen, zurück auf Standard)
    CASES = [
        ("quellen_und_netze", {}, {},
         {"ntp_sources": [{"type": "server", "host": "ptbtime1.ptb.de", "nts": True, "prefer": True, "noselect": False,
                           "options": ""},
                          {"type": "pool", "host": "de.pool.ntp.org", "nts": False, "prefer": False, "noselect": False,
                           "options": ""}],
          "ntp_minsources": 2, "allow_networks": ["192.0.2.0/24", "198.51.100.0/24"], "deny_networks": ["192.0.2.128/25"],
          "nts_nocerttimecheck": True},
         []),
        ("ptp_grandmaster", {"ntp_minsources": 2}, {},
         {"ptp_enable": True, "ptp_interface": "eth0", "ptp_mode": "master", "ptp_profile": "aes67", "ptp_domain": 3},
         []),
        ("gps_mit_pps", {}, {},
         {"gps_enable": True, "gps_device": GPS_DEVICE, "gps_pps_device": PPS_DEVICE, "gps_offset": 0.123,
          "gps_select": "prefer", "serve_unsynced": False},
         []),
        ("zuruecksetzen", {"ntp_minsources": 3, "local_orphan": True, "local_stratum": 8, "ntp_ratelimit": True}, {},
         {"ntp_ratelimit": False}, ["ntp_minsources", "local_orphan"]),
        ("zuruecksetzen_gegen_umgebung", {}, {"NTP_MINSOURCES": "3", "LOCAL_STRATUM": "12"},
         {}, ["ntp_minsources"]),
        ("ptp_aus_und_extra", {"ptp_enable": True, "ptp_interface": "eth0"},
         {"EXTRA_CHRONY_CONF": "logchange 0.5", "EXTRA_PTP4L_CONF": "verbose 1"},
         {"ptp_enable": False, "makestep": "0.5 -1"}, ["ptp_interface"]),
    ]

    def run_case(self, before, env, changes, defaults):
        env = {**self.env, **env}
        with mock.patch.dict(os.environ, env):
            if before:
                settings.save(before)
            confgen.apply(env)
            old = {path: self.read(path) for path in (confgen.CHRONY_CONF, confgen.PTP4L_CONF)}
            snap = self.snapshot()
            planned, _notes = confgen.preview_files(changes, defaults, env)
            shown = confgen.preview(changes, defaults, env)
            self.assertEqual(self.snapshot(), snap, "Vorschau darf nichts schreiben")
            settings.save(changes, defaults)
            confgen.apply(env)
        return old, planned, shown

    def test_vorschau_gleich_datei_nach_apply(self):
        for name, before, env, changes, defaults in self.CASES:
            with self.subTest(case=name):
                self.setUp()  # frisches Verzeichnis je Fall
                old, planned, shown = self.run_case(before, env, changes, defaults)
                files = {entry["name"]: entry for entry in shown["files"]}
                for path, label in ((confgen.CHRONY_CONF, "chrony.conf"), (confgen.PTP4L_CONF, "ptp4l.conf")):
                    after = self.read(path)
                    entry = files[label]
                    if path in planned:
                        self.assertEqual(planned[path], after, f"{label}: Vorschau ≠ Datei nach apply")
                        self.assertEqual(apply_unified(old[path] or "", entry["diff"]), after,
                                         f"{label}: Diff ergibt nicht die Datei nach apply")
                        self.assertEqual(entry["status"], "new" if old[path] is None
                                         else "changed" if old[path] != after else "same")
                    else:
                        self.assertEqual(entry["status"], "unused")
                        self.assertEqual(entry["diff"], [])
                        self.assertEqual(after, old[path], "nicht genutzte Datei bleibt, wie sie ist")

    def test_einzelne_saetze_sichtbar_im_diff(self):
        _old, _planned, shown = self.run_case({}, {}, {"ntp_minsources": 2}, [])
        chrony = shown["files"][0]
        self.assertEqual(chrony["status"], "changed")
        self.assertIn("-minsources 1", chrony["diff"])
        self.assertIn("+minsources 2", chrony["diff"])
        self.assertEqual(shown["files"][1]["status"], "unused")

    def test_zuruecksetzen_gegen_umgebung_speichert_standard(self):
        with mock.patch.dict(os.environ, {"NTP_MINSOURCES": "3"}):
            self.assertEqual(settings.values()["ntp_minsources"], 3)
            result = settings.save({}, ["ntp_minsources"])
            self.assertEqual(settings.values()["ntp_minsources"], 1)
            self.assertEqual(result["changed"], ["ntp_minsources"])
        settings.save({"ntp_ratelimit": True})
        settings.save({}, ["ntp_ratelimit"])
        self.assertNotIn("ntp_ratelimit", settings._load_file().get("values", {}), "ohne Umgebung: Wert entfernt")

    def test_vorschau_prueft_wie_speichern(self):
        snap = self.snapshot()
        with self.assertRaises(settings.ValidationError) as caught:
            confgen.preview({"ntp_minsources": 99, "allow_networks": ["kein netz"]}, None, self.env)
        self.assertEqual(set(caught.exception.fields), {"ntp_minsources", "allow_networks"})
        with self.assertRaises(settings.ValidationError):
            confgen.preview({"gibt_es_nicht": 1}, None, self.env)
        with self.assertRaises(settings.ValidationError):
            confgen.preview({}, ["gibt_es_nicht"], self.env)
        with self.assertRaises(settings.ValidationError):
            confgen.preview({}, "ntp_minsources", self.env)
        self.assertEqual(self.snapshot(), snap)

    def test_nts_server_vorschau_kopiert_nichts(self):
        cert_dir = os.path.join(self.tmp, "certs")
        os.makedirs(cert_dir)
        cert, key = os.path.join(cert_dir, "fullchain.pem"), os.path.join(cert_dir, "privkey.pem")
        with open(cert, "w", encoding="utf-8") as handle:
            handle.write("-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")
        with open(key, "w", encoding="utf-8") as handle:
            handle.write("-----BEGIN PRIVATE KEY-----\nGEHEIMERSCHLUESSEL\n-----END PRIVATE KEY-----\n")
        cfg = dict(settings.values(), nts_server_enable=True, nts_server_cert=cert, nts_server_key=key)
        with mock.patch.object(confgen, "nts_pair_matches", return_value=True):
            paths = confgen.prepare_nts_files(cfg, warn=lambda *_a: None, ids=None, dry_run=True)
            self.assertEqual(paths, (os.path.join(confgen.NTS_CERT_DIR, "server.crt"),
                                     os.path.join(confgen.NTS_CERT_DIR, "server.key")))
            self.assertFalse(os.path.exists(confgen.NTS_CERT_DIR), "Vorschau legt keine Kopien an")
            text = confgen.render_chrony(cfg, self.env, warn=lambda *_a: None, nts_files=paths)
        self.assertIn(f"ntsserverkey {paths[1]}", text)
        self.assertNotIn("GEHEIMERSCHLUESSEL", text, "nur der Pfad, nie der Schlüssel")


class GeheimnisseTest(TempConfig):
    def test_keine_geheimnisse_im_diff(self):
        env = dict(self.env, EXTRA_CHRONY_CONF="keyfile /etc/chrony.keys\\npassword hunter2geheim\\n"
                                              "# doh https://dns.example/abc123kennung")
        with mock.patch.dict(os.environ, env):
            shown = confgen.preview({"ntp_minsources": 2}, None, env)
        text = "\n".join(shown["files"][0]["diff"])
        self.assertIn("keyfile /etc/chrony.keys", text, "Pfade bleiben stehen")
        self.assertNotIn("hunter2geheim", text)
        self.assertIn(f"password {confgen.REDACTED}", text)
        self.assertNotIn("abc123kennung", text)

    def test_gespeicherte_geheimnisse_landen_nicht_in_den_dateien(self):
        # Was confgen schreibt, kommt nur aus dem Schema – DoH-Pfade, Passwort und Tokens gehören nicht dazu.
        settings.set_credentials("admin", "passwort-geheim-123")
        env = dict(self.env)
        changes = {"dns_mode": "doh", "dns_doh": ["https://dns.example/kontokennung42"]}
        planned, _notes = confgen.preview_files(changes, None, env)
        shown = confgen.preview(changes, None, env)
        blob = json.dumps(shown, ensure_ascii=False) + "\n".join(planned.values())
        for secret in ("kontokennung42", "passwort-geheim-123", "dns.example"):
            self.assertNotIn(secret, blob)

    def test_redact_config(self):
        text = confgen.redact_config("server a.example iburst\nntsserverkey /config/key.pem\n  api_key=xyz\n"
                                     "mysecretonly\nurl https://user:pw@dns.example/pfad?x=1")
        self.assertEqual(text.splitlines(), ["server a.example iburst", "ntsserverkey /config/key.pem",
                                             f"  api_key {confgen.REDACTED}", confgen.REDACTED,
                                             f"url https://{confgen.REDACTED}@dns.example/{confgen.REDACTED}"])


class VorschauEndpunktTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = cls.tmp.name
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", tmp),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(tmp, "settings.json")),
            mock.patch.object(server, "RUN_DIR", tmp),
            mock.patch.object(confgen, "CHRONY_CONF", os.path.join(tmp, "chrony.conf")),
            mock.patch.object(confgen, "PTP4L_CONF", os.path.join(tmp, "ptp4l.conf")),
            mock.patch.object(confgen, "CUSTOM_CHRONY", os.path.join(tmp, "custom-chrony.conf")),
            mock.patch.object(confgen, "CUSTOM_PTP4L", os.path.join(tmp, "custom-ptp4l.conf")),
            mock.patch.object(confgen, "NTS_CERT_DIR", os.path.join(tmp, "nts-certs")),
            mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"}),
        ]
        for patch in cls.patches:
            patch.start()
        os.environ.pop("WEB_READONLY", None)
        settings._CACHE.update(mtime=None, data=None)
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        with open(confgen.CHRONY_CONF, "w", encoding="utf-8") as handle:
            handle.write(confgen.render_chrony(settings.values(), {}, warn=lambda *_a: None))
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.read_id, cls.read_key = apikeys.create("Lesen", "read")
        cls.admin_id, cls.admin_key = apikeys.create("Verwalten", "admin")

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        settings._CACHE.update(mtime=None, data=None)
        cls.tmp.cleanup()

    def request(self, body, headers, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = raw if raw is not None else json.dumps(body).encode()
        hdrs = {"Content-Type": "application/json", **headers}
        conn.request("POST", "/api/settings/preview", body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(payload)
        except ValueError:
            return resp.status, payload

    def basic(self, **extra):
        return {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode(), "X-NTP-GUI": "1", **extra}

    def state(self):
        return (os.path.exists(settings.SETTINGS_FILE), Path(confgen.CHRONY_CONF).read_text(encoding="utf-8"),
                os.path.exists(confgen.PTP4L_CONF))

    def test_vorschau_aus_dem_dashboard(self):
        before = self.state()
        status, payload = self.request({"changes": {"ntp_minsources": 2}}, self.basic())
        self.assertEqual(status, 200, payload)
        self.assertIn("+minsources 2", payload["files"][0]["diff"])
        self.assertEqual(self.state(), before, "Vorschau schreibt nichts")

    def test_kein_pfad_aus_der_anfrage(self):
        status, payload = self.request({"changes": {"ntp_minsources": 2}, "path": "/etc/passwd",
                                        "file": "/etc/shadow"}, self.basic())
        self.assertEqual(status, 200)
        self.assertNotIn("root:", json.dumps(payload))
        self.assertEqual([f["name"] for f in payload["files"]], ["chrony.conf", "ptp4l.conf"])

    def test_rechte_csrf_und_groesse(self):
        before = self.state()
        body = {"changes": {"ntp_minsources": 2}}
        self.assertEqual(self.request(body, {})[0], 401)
        self.assertEqual(self.request(body, {"Authorization": f"Bearer {self.read_key}"})[0], 403)
        self.assertEqual(self.request(body, {"Authorization": f"Bearer {self.admin_key}"})[0], 200)
        no_header = self.basic()
        no_header.pop("X-NTP-GUI")
        self.assertEqual(self.request(body, no_header)[0], 403)
        self.assertEqual(self.request(body, self.basic(Origin="http://fremd.example"))[0], 403)
        self.assertEqual(self.request(body, self.basic(**{"Content-Type": "text/plain"}))[0], 403)
        big = json.dumps({"changes": {"web_title": "x" * (server.MAX_BODY + 10)}}).encode()
        self.assertEqual(self.request(None, self.basic(), raw=big)[0], 400)
        status, payload = self.request({"changes": {"ntp_minsources": 99}}, self.basic())
        self.assertEqual(status, 422)
        self.assertIn("ntp_minsources", payload["fields"])
        self.assertEqual(self.request({"changes": {}}, self.basic())[0], 422)
        self.assertEqual(self.state(), before)

    def test_defaults_mit_falschen_eintraegen(self):
        """Listen oder Objekte in „defaults“: 422 ohne Python-Interna, nicht 500."""
        before = self.state()
        for defaults in ([["ntp_minsources"]], [{"a": 1}], [1], [None]):
            with self.subTest(defaults=defaults):
                status, payload = self.request({"changes": {"ntp_minsources": 2}, "defaults": defaults}, self.basic())
                self.assertEqual(status, 422, payload)
                self.assertNotIn("unhashable", json.dumps(payload))
                self.assertIn("defaults", payload["error"])
        self.assertEqual(self.state(), before)

    def test_lesbar_im_v1_verzeichnis(self):
        import apiv1
        self.assertEqual(apiv1.required_scope("POST", "/api/settings/preview"), "admin")
        self.assertEqual(apiv1.required_scope("POST", "/api/v1/settings/preview"), "admin")


class DefaultsPruefungTest(unittest.TestCase):
    """validate_defaults (Speichern und Vorschau): nur Schlüssel als Zeichenketten."""

    def test_eintraege_muessen_zeichenketten_sein(self):
        for defaults in ([["ntp_minsources"]], [{"a": 1}], [1], [True], [None], ["ntp_minsources", ["x"]]):
            with self.subTest(defaults=defaults):
                with self.assertRaises(settings.ValidationError) as caught:
                    settings.validate_defaults(defaults)
                self.assertIn("„defaults“", str(caught.exception))
        self.assertEqual(settings.validate_defaults(["ntp_minsources", "ntp_minsources"]), ["ntp_minsources"])


class HilfetextTest(unittest.TestCase):
    def test_eine_zeile_und_nichts_verloren(self):
        for field in settings.SCHEMA:
            with self.subTest(field=field["key"]):
                hint, more = settings.help_parts(field)
                self.assertTrue(hint, "jedes Feld braucht eine sichtbare Zeile")
                self.assertLessEqual(len(hint), settings.HINT_MAX)
                if field["hint"]:
                    self.assertEqual(more, field["help"].strip(), "mit eigenem Kurztext zeigt das ⓘ den ganzen Text")
                else:
                    self.assertEqual(f"{hint} {more}".strip(), field["help"].strip(), "Rest steht im ⓘ")

    def test_schema_liefert_kurztext_und_rest(self):
        schema = settings.public_schema()
        for field in schema["fields"]:
            with self.subTest(field=field["key"]):
                self.assertLessEqual(len(field["hint"]), 140)
                self.assertIn("more", field)

    def test_keine_versionsgeschichte_in_der_oberflaeche(self):
        pattern = re.compile(r"\b(?:ab|seit|bis|vor|Standard ab|neu in|Version)\s+v?1\.\d+(?:\.\d+)?\b|\(1\.\d+(?:\.\d+)?\)")
        texts = [(f["key"], f["label"] + " " + f["help"]) for f in settings.SCHEMA]
        texts += [(f"section.{k}", f"{l} {d}") for k, l, d in settings.SECTIONS]
        de = json.loads((STATIC / "i18n" / "de.json").read_text(encoding="utf-8"))
        texts += [("i18n.settings", json.dumps(de["settings"], ensure_ascii=False))]
        page = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
        texts += [(f"settings.js:{n}", line) for n, line in enumerate(page.splitlines(), 1)
                  if not line.lstrip().startswith("//")]
        help_web = (JS / "help-web.js").read_text(encoding="utf-8")
        texts += [("help-web.js", help_web[help_web.index("ui_language"):][:1200])]
        for where, text in texts:
            with self.subTest(where=where):
                self.assertNotRegex(text, pattern)


def mod(path: str) -> str:
    return json.dumps((JS / path).resolve().as_uri())


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class SucheUndReiterTest(unittest.TestCase):
    """settings.js im echten JS-Interpreter mit dem Schema vom Server."""

    @classmethod
    def setUpClass(cls):
        from test_frontend_states import DOM
        cls.schema = settings.public_schema()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dom.mjs").write_text(DOM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            schema_path = Path(tmp) / "schema.json"
            schema_path.write_text(json.dumps(cls.schema), encoding="utf-8")
            script.write_text("""
import { text, ctx } from "./dom.mjs";
import { readFileSync } from "node:fs";
const page = await import(%(module)s);
const { HELP } = await import(%(help)s);
const schema = JSON.parse(readFileSync(%(schema)s, "utf-8"));
const out = { tabs: page.TABS.map((t) => t.id), sectionTab: {}, legacy: {}, search: {}, entries: [], tabText: {} };
for (const s of schema.sections) out.sectionTab[s.key] = page.tabOf(s.key);
for (const s of ["gps", "web", "ptp", "ntp", "lan", "nts", "dns", "backup", "api", "auth", "sichern", "zugang", "quatsch", "", null])
  out.legacy[String(s)] = page.tabFromQuery(s === null ? "" : `s=${s}`);
const index = page.searchIndex(schema.fields, HELP);
out.entries = index.map((e) => ({ id: e.id, tab: e.tab }));
const probes = {};
for (const f of schema.fields) {
  const helpKey = page.FIELD_HELP[f.key];
  const words = (f.more || f.hint).split(/\\s+/).filter((w) => w.length > 6);
  const infoText = helpKey && HELP[helpKey] ? HELP[helpKey].text : "";
  const infoWords = infoText.replace(/[*`]/g, "").split(/\\s+/).filter((w) => w.length > 7);
  probes[f.key] = { label: f.label, key: f.key, more: words.slice(-1)[0] || f.label,
    info: infoWords.slice(-1)[0] || f.label, upper: f.label.toUpperCase() };
}
for (const [key, p] of Object.entries(probes)) {
  out.search[key] = Object.fromEntries(Object.entries(p).map(([what, q]) => [what,
    page.search(index, q).map((e) => e.id).includes(key)]));
}
out.empty = page.search(index, "   ").length;
out.nothing = page.search(index, "xyzzy-gibt-es-nicht").length;
out.multi = page.search(index, "pool server").map((e) => e.id).slice(0, 3);
console.log(JSON.stringify(out));
""" % {"module": mod("pages/settings.js"), "help": mod("help.js"), "schema": json.dumps(str(schema_path))},
                encoding="utf-8")
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_reiter(self):
        self.assertEqual(self.out["tabs"], ["quellen", "lan", "gps", "ptp", "zugang", "sichern"])
        for section in ("ntp", "lan", "nts", "dns", "gps", "ptp", "web"):
            self.assertIn(self.out["sectionTab"][section], self.out["tabs"], section)
        self.assertEqual(self.out["sectionTab"]["gps"], "gps")
        self.assertEqual(self.out["sectionTab"]["ptp"], "ptp")
        self.assertEqual(self.out["sectionTab"]["lan"], "lan")
        self.assertEqual(self.out["sectionTab"]["web"], "zugang")

    def test_naechtliche_sicherung_im_reiter_sichern(self):
        tabs = {e["id"]: e["tab"] for e in self.out["entries"]}
        self.assertEqual(tabs["backup_nightly"], "sichern")
        page = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
        self.assertNotIn("Dashboard → Nächtliche Sicherung", page)

    def test_alte_sprungziele(self):
        legacy = self.out["legacy"]
        self.assertEqual(legacy["gps"], "gps")
        self.assertEqual(legacy["web"], "zugang")
        self.assertEqual(legacy["ptp"], "ptp")
        self.assertEqual(legacy["backup"], "sichern")
        self.assertEqual(legacy["sichern"], "sichern")
        self.assertEqual(legacy["quatsch"], "quellen")
        self.assertEqual(legacy[""], "quellen")

    def test_suche_findet_jedes_feld(self):
        keys = {f["key"] for f in self.schema["fields"]}
        self.assertEqual(set(self.out["search"]), keys)
        for key, hits in self.out["search"].items():
            with self.subTest(field=key):
                self.assertEqual(hits, {"label": True, "key": True, "more": True, "info": True, "upper": True})
        ids = {e["id"] for e in self.out["entries"]}
        self.assertTrue(keys <= ids)
        for extra in ("ui_language", "auth", "api", "backup", "export"):
            self.assertIn(extra, ids, "auch Bereiche außerhalb des Schemas sind auffindbar")
        for entry in self.out["entries"]:
            self.assertIn(entry["tab"], self.out["tabs"])
        self.assertEqual(self.out["empty"], 0)
        self.assertEqual(self.out["nothing"], 0)
        self.assertIn("ntp_sources", self.out["multi"])


class SeiteTest(unittest.TestCase):
    def test_suchfeld_und_kuerzel(self):
        page = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
        self.assertIn('type: "search"', page, "„/“ (app.js) fokussiert das erste input[type=search]")
        self.assertIn("/api/settings/preview", page)
        self.assertIn("leaveMessage", page)
        app = (JS / "app.js").read_text(encoding="utf-8")
        self.assertIn('"beforeunload"', app)
        self.assertIn("leaveMessage", app)

    def test_keine_inline_styles_im_diff(self):
        page = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
        self.assertNotRegex(page, r"\bstyle\s*:")
        self.assertNotIn(".style.", page)
        css = (STATIC / "app.css").read_text(encoding="utf-8")
        for cls in (".diff-add", ".diff-del", ".diff-hunk", ".settings-tabs", ".save-bar"):
            self.assertIn(cls, css)

    def test_neue_texte_auch_englisch(self):
        de = json.loads((STATIC / "i18n" / "de.json").read_text(encoding="utf-8"))
        en = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))

        def flat(node, prefix=""):
            out = {}
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else key
                out.update(flat(value, path) if isinstance(value, dict) else {path: value})
            return out
        de_keys = {k for k in flat(de["settings"]) if not k.startswith("section.")}
        en_keys = set(flat(en["settings"]))
        self.assertTrue({"tab.quellen", "search.label", "savebar.preview", "preview.title", "leave"} <= de_keys)
        self.assertEqual(sorted(de_keys - en_keys), [], "neue Schlüssel brauchen einen englischen Text (Beta)")


if __name__ == "__main__":
    unittest.main()
