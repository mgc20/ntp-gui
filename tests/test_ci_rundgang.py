"""CI-Job „Oberfläche“: Rundgang und Browser-Tests laufen in der CI, nicht nur lokal.

* der Job hat nur Leserechte, Playwright in fester Version, Zeitgrenzen und lädt den Befund nur bei
  einem Fehlschlag hoch;
* tests/ui/ci.sh kennt nur gültige Varianten und macht fehlendes Playwright zu einem Fehler;
* rundgang.sh überspringt ohne Playwright weiterhin still – außer mit TOUR_REQUIRE_PLAYWRIGHT=1;
* NTPGUI_WERKZEUGE_PFLICHT=1 macht aus einem Überspringen wegen fehlender Werkzeuge einen Fehlschlag;
* die Höchstdauer je Variante beendet Variante und Testserver, die nächste Variante startet;
* die Befehle im Messblatt (docs/messblatt-pi.md) liefern kein falsches „bestanden“.

Ohne YAML-Bibliothek (PyYAML ist keine Abhängigkeit): Textprüfung wie in test_supplychain.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402
from test_supplychain import USES_RE, jobs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
UI = ROOT / "tests" / "ui"


class CiJobTest(unittest.TestCase):
    def setUp(self):
        self.job = jobs(CI.read_text(encoding="utf-8"))["ui"]

    def test_minimal_rights_and_time_limits(self):
        self.assertIn("    permissions:\n      contents: read\n", self.job)
        self.assertNotRegex(self.job, r"write|secrets\.|id-token")
        self.assertRegex(self.job, r"\n    timeout-minutes: \d+\n")
        for step in ("Playwright, Chromium und ptp4l installieren", "Unittests mit Browser und ptp4l", "Rundgang"):
            with self.subTest(step=step):
                body = self.job.split(f"name: {step}\n", 1)[1].split("\n      - ", 1)[0]
                self.assertRegex(body, r"timeout-minutes: \d+")
        self.assertIn("persist-credentials: false", self.job)

    def test_step_limits_below_job_limit(self):
        """Greift die Job-Grenze vor einer Schritt-Grenze, gilt der Job als abgebrochen statt fehlgeschlagen."""
        job_limit = int(re.search(r"\n    timeout-minutes: (\d+)\n", self.job).group(1))
        steps = [int(m) for m in re.findall(r"\n        timeout-minutes: (\d+)\n", self.job)]
        self.assertEqual(len(steps), 3)
        self.assertGreaterEqual(job_limit - sum(steps), 10, "zu wenig Reserve für Checkout und Upload")
        tour_limit = int(re.search(r'TOUR_CI_LIMIT: "(\d+)"', self.job).group(1))
        rundgang = int(self.job.split("name: Rundgang\n", 1)[1].split("timeout-minutes: ", 1)[1].split("\n")[0])
        self.assertLess(tour_limit, rundgang * 60)

    def test_playwright_pinned_and_required(self):
        version = re.search(r'PLAYWRIGHT_VERSION: "([^"]+)"', self.job)
        self.assertIsNotNone(version)
        self.assertRegex(version.group(1), r"^\d+\.\d+\.\d+$")
        self.assertIn("npm ci --prefix", self.job)                   # nur aus dem Lockfile, mit Prüfsummen
        self.assertNotRegex(self.job, r"(?m)^\s+npm install")              # kein Auflösen ohne Lockfile
        self.assertIn("tests/ui/package-lock.json", self.job)
        self.assertNotIn("@latest", self.job)
        self.assertIn("--ignore-scripts", self.job)
        self.assertIn('NTPGUI_WERKZEUGE_PFLICHT: "1"', self.job)
        self.assertIn("test_darstellung_browser test_live_eingaben test_ptp_gm", self.job)
        self.assertIn("linuxptp", self.job)
        self.assertIn("tests/ui/ci.sh", self.job)

    def test_lockfile_matches_pinned_version(self):
        """package.json und package-lock.json in tests/ui legen Playwright mit Prüfsumme fest – dieselbe
        Version wie PLAYWRIGHT_VERSION und das README."""
        import json
        version = re.search(r'PLAYWRIGHT_VERSION: "([^"]+)"', self.job).group(1)
        package = json.loads((UI / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((UI / "package-lock.json").read_text(encoding="utf-8"))
        self.assertTrue(package.get("private"))
        self.assertEqual(package["dependencies"], {"playwright": version})
        self.assertEqual(lock["packages"][""]["dependencies"], {"playwright": version})
        names = {key.split("node_modules/")[-1] for key in lock["packages"] if key}
        self.assertEqual(names, {"playwright", "playwright-core"})
        for key, entry in lock["packages"].items():
            if not key:
                continue
            with self.subTest(paket=key):
                self.assertEqual(entry["version"], version)
                self.assertRegex(entry["integrity"], r"^sha512-[A-Za-z0-9+/]{86}==$")
                self.assertTrue(entry["resolved"].startswith("https://registry.npmjs.org/"))
        self.assertIn(f"playwright@{version}", (UI / "README.md").read_text(encoding="utf-8"))

    def test_artifact_only_on_failure(self):
        uses = [USES_RE.match(line).group(1) for line in self.job.splitlines() if USES_RE.match(line)]
        self.assertEqual([u.split("@")[0] for u in uses],
                         ["actions/checkout", "actions/setup-python", "actions/upload-artifact"])
        upload = self.job.split("name: Befund hochladen\n", 1)[1]
        self.assertIn("if: failure() || cancelled()", upload)
        self.assertIn("retention-days:", upload)


class CiScriptTest(unittest.TestCase):
    def test_variants_known_to_tour(self):
        script = (UI / "ci.sh").read_text(encoding="utf-8")
        tour = (UI / "tour.js").read_text(encoding="utf-8")
        variants = re.search(r'^CI_VARIANTS="([^"]+)"', script, re.M).group(1).split()
        self.assertIn("routen", variants)
        for variant in variants:
            with self.subTest(variant=variant):
                case = re.search(rf"^\s+{variant}\) echo \"([^\"]*)\"", script, re.M)
                self.assertIsNotNone(case, "Variante ohne Eintrag in env_for")
                for name in re.findall(r"(TOUR_[A-Z_]+)=", case.group(1)):
                    self.assertIn(f"process.env.{name}", tour, f"{name} kennt tour.js nicht")
        self.assertIn("TOUR_REQUIRE_PLAYWRIGHT=1", script)
        self.assertIn("timeout -k 30 -s TERM", script)  # ohne -k wartet timeout unbegrenzt
        self.assertIn("TOUR_SHOTS=$OUT/hilfe-fotos", script)
        self.assertTrue(os.access(UI / "ci.sh", os.X_OK))
        self.assertTrue(os.access(UI / "rundgang.sh", os.X_OK))

    @unittest.skipUnless(shutil.which("bash"), "bash fehlt")
    def test_unknown_variant_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, TOUR_CI_VARIANTS="gibtsnicht")
            proc = subprocess.run(["bash", str(UI / "ci.sh"), "19714", tmp], capture_output=True, text=True,
                                  env=env, timeout=60)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Unbekannte Variante", proc.stderr)


@unittest.skipUnless(shutil.which("bash") and shutil.which("timeout"), "bash oder timeout fehlt")
class CiZeitgrenzeTest(unittest.TestCase):
    """Höchstdauer je Variante: Der echte Testserver startet, tour.js hängt (Ersatz-node schläft). Nach der Grenze
    muss die Variante mit 124 enden, der Server beendet sein und die nächste Variante starten."""

    PORT = "19717"

    def test_limit_ends_variant_and_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "node"
            # „node -e require.resolve(...)“ meldet Playwright als vorhanden, „node tour.js“ hängt.
            fake.write_text('#!/bin/sh\nif [ "$1" = "-e" ]; then exit 0; fi\nexec sleep 600\n', encoding="utf-8")
            fake.chmod(0o755)
            out = Path(tmp) / "out"
            work = Path(tmp) / "work"
            work.mkdir()
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", TMPDIR=str(work),
                       TOUR_CI_LIMIT="6", TOUR_WARMUP="0", TOUR_CI_VARIANTS="hilfe zeitleiste")
            proc = subprocess.run(["bash", str(UI / "ci.sh"), self.PORT, str(out)], capture_output=True,
                                  text=True, env=env, timeout=180, start_new_session=True)
            leftovers = [p.name for p in work.iterdir() if p.name.startswith("ntpgui-ui-")]
            ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
            logs = sorted(p.name for p in out.iterdir())
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertRegex(proc.stdout, r"hilfe: Rückgabecode 124 nach \d+ s")
        self.assertRegex(proc.stdout, r"zeitleiste: Rückgabecode 124 nach \d+ s")
        self.assertIn("Befund in: hilfe zeitleiste", proc.stderr)
        self.assertEqual(leftovers, [], "Temp-Verzeichnis des Servers bleibt liegen")
        self.assertNotIn(str(work), ps, "Testserver läuft nach der Zeitgrenze weiter")
        self.assertIn("hilfe-server.log", logs)
        self.assertIn("zeitleiste-server.log", logs)


@unittest.skipUnless(shutil.which("bash") and shutil.which("node"), "bash oder node fehlt")
class RundgangOhnePlaywrightTest(unittest.TestCase):
    """rundgang.sh mit einem node, das Playwright sicher nicht findet (leeres NODE_PATH, eigenes HOME)."""

    def run_script(self, **extra):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": os.environ["PATH"], "HOME": tmp, "NODE_PATH": tmp, "TMPDIR": tmp, **extra}
            probe = subprocess.run(["node", "-e", "require.resolve('playwright')"], cwd=tmp, env=env,
                                   capture_output=True, timeout=30)
            if probe.returncode == 0:
                self.skipTest("Playwright ist global installiert")
            proc = subprocess.run(["bash", str(UI / "rundgang.sh"), "19714"], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=60)
            leftovers = [p.name for p in Path(tmp).iterdir() if p.name.startswith("ntpgui-ui-")]
        self.assertEqual(leftovers, [], "Temp-Verzeichnis bleibt liegen")
        return proc

    def test_local_default_skips_quietly(self):
        proc = self.run_script()
        self.assertEqual(proc.returncode, 0)
        self.assertIn("übersprungen", proc.stderr)

    def test_required_in_ci_fails(self):
        proc = self.run_script(TOUR_REQUIRE_PLAYWRIGHT="1")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("nicht möglich", proc.stderr)


MESSBLATT = ROOT / "docs" / "messblatt-pi.md"


def sh_blocks(text):
    return re.findall(r"```sh\n(.*?)```", text, re.S)


class MessblattTest(unittest.TestCase):
    """docs/messblatt-pi.md: Die Befehle dürfen keinen falschen Bestanden-Wert liefern."""

    def setUp(self):
        self.text = MESSBLATT.read_text(encoding="utf-8")
        self.blocks = sh_blocks(self.text)

    @unittest.skipUnless(shutil.which("bash"), "bash fehlt")
    def test_blocks_parse(self):
        self.assertGreaterEqual(len(self.blocks), 5)
        for block in self.blocks:
            with self.subTest(block=block[:40]):
                proc = subprocess.run(["bash", "-n"], input=block, capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_key_not_on_command_line(self):
        self.assertNotIn("Authorization: Bearer $KEY\")", self.text)
        self.assertIn('AUTH=(-K "$H")', self.text)
        self.assertIn("umask 077", self.text)
        for line in self.text.splitlines():
            if "curl" in line and "/api/v1/" in line:
                with self.subTest(line=line):
                    self.assertIn('"${AUTH[@]}"', line)

    def test_status_checked(self):
        overview = self.text.split("## 4.", 1)[1]
        self.assertIn("%{http_code} %{time_starttransfer}", overview)
        self.assertIn('if [ "$code" != 200 ]', overview)
        self.assertIn("HTTP 200 mit Größe > 0", self.text.split("## 3.", 1)[1].split("## 4.", 1)[0])

    def test_tone_not_in_kiosk_profile(self):
        tone = self.text.split("## 2.", 1)[1].split("## 3.", 1)[0]
        self.assertNotIn("clock?p=studio`", tone)          # Kiosk ohne Kopfzeile: kein Ton-Knopf
        self.assertIn("clock?design=studio&look=studio&fun=0", tone)
        self.assertIn("clock?p=studio&test=sync", tone)    # Prüfbild mit Ton-Klick geht auch mit kiosk=1

    def run_cpu(self, pid_lists):
        """CPU-Block mit Ersatz-pgrep (gibt je Aufruf die nächste PID-Liste aus) und ohne Wartezeit."""
        block = next(b for b in self.blocks if "snap()" in b).replace("sleep 60", "sleep 0")
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            for i, pids in enumerate(pid_lists):
                (Path(tmp) / f"pids{i}").write_text("".join(f"{p}\n" for p in pids), encoding="utf-8")
            fake = bin_dir / "pgrep"
            fake.write_text(f'#!/bin/sh\nn=$(cat "{tmp}/n" 2>/dev/null || echo 0)\necho $((n + 1)) > "{tmp}/n"\n'
                            f'cat "{tmp}/pids$n"\n', encoding="utf-8")
            fake.chmod(0o755)
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
            proc = subprocess.run(["bash", "-c", block], cwd=tmp, env=env, capture_output=True, text=True,
                                  timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    @unittest.skipUnless(shutil.which("bash") and Path("/proc/self/stat").exists(), "bash oder /proc fehlt")
    def test_cpu_vanished_process_and_empty(self):
        me = os.getpid()
        # Eine PID gibt es nicht (Prozess beendet): Die übrigen werden trotzdem gezählt, kein stilles 0,0 %.
        self.assertRegex(self.run_cpu([[me, 999999999], [me, 999999999]]), r"^\d+\.\d % \(1 Prozesse\)$")
        self.assertIn("ungültig", self.run_cpu([[], []]))                 # kein Chromium: kein Hängen, kein 0 %
        self.assertIn("ungültig", self.run_cpu([[me], [me, os.getppid()]]))  # Prozessmenge hat sich geändert


class WerkzeugPflichtTest(unittest.TestCase):
    def test_without_flag_skips(self):
        with mock.patch.dict(os.environ, {_support.PFLICHT_ENV: ""}):
            @_support.skip_unless_tool(False, "fehlt")
            class Probe(unittest.TestCase):
                def test_x(self):
                    pass
            result = unittest.TestResult()
            unittest.defaultTestLoader.loadTestsFromTestCase(Probe).run(result)
        self.assertEqual(len(result.skipped), 1)
        self.assertTrue(result.wasSuccessful())

    def test_with_flag_class_fails(self):
        with mock.patch.dict(os.environ, {_support.PFLICHT_ENV: "1"}):
            @_support.skip_unless_tool(False, "Werkzeug X fehlt")
            class Probe(unittest.TestCase):
                def test_x(self):
                    pass
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(Probe))
        result = unittest.TestResult()
        suite.run(result)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.skipped, [])
        self.assertIn("Werkzeug X fehlt", "".join(err for _, err in result.errors))

    def test_with_flag_method_and_runtime_skip_fail(self):
        with mock.patch.dict(os.environ, {_support.PFLICHT_ENV: "1"}):
            class Probe(unittest.TestCase):
                @_support.skip_unless_tool(False, "Werkzeug Y fehlt")
                def test_decorated(self):
                    pass

                def test_runtime(self):
                    _support.skip_tool(self, "Browser fehlt")
            result = unittest.TestResult()
            unittest.defaultTestLoader.loadTestsFromTestCase(Probe).run(result)
        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.failures) + len(result.errors), 2)

    def test_present_tool_runs_normally(self):
        with mock.patch.dict(os.environ, {_support.PFLICHT_ENV: "1"}):
            @_support.skip_unless_tool(True, "da")
            class Probe(unittest.TestCase):
                def test_x(self):
                    pass
            result = unittest.TestResult()
            unittest.defaultTestLoader.loadTestsFromTestCase(Probe).run(result)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 1)


if __name__ == "__main__":
    unittest.main()
