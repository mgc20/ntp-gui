"""CI-Job „Oberfläche“: Rundgang und Browser-Tests laufen in der CI, nicht nur lokal.

* der Job hat nur Leserechte, Playwright in fester Version, Zeitgrenzen und lädt den Befund nur bei
  einem Fehlschlag hoch;
* tests/ui/ci.sh kennt nur gültige Varianten und macht fehlendes Playwright zu einem Fehler;
* rundgang.sh überspringt ohne Playwright weiterhin still – außer mit TOUR_REQUIRE_PLAYWRIGHT=1;
* NTPGUI_WERKZEUGE_PFLICHT=1 macht aus einem Überspringen wegen fehlender Werkzeuge einen Fehlschlag.

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

    def test_playwright_pinned_and_required(self):
        version = re.search(r'PLAYWRIGHT_VERSION: "([^"]+)"', self.job)
        self.assertIsNotNone(version)
        self.assertRegex(version.group(1), r"^\d+\.\d+\.\d+$")
        self.assertIn('"playwright@${PLAYWRIGHT_VERSION}"', self.job)
        self.assertNotIn("@latest", self.job)
        self.assertIn("--ignore-scripts", self.job)
        self.assertIn('NTPGUI_WERKZEUGE_PFLICHT: "1"', self.job)
        self.assertIn("test_darstellung_browser test_live_eingaben test_ptp_gm", self.job)
        self.assertIn("linuxptp", self.job)
        self.assertIn("tests/ui/ci.sh", self.job)

    def test_artifact_only_on_failure(self):
        uses = [USES_RE.match(line).group(1) for line in self.job.splitlines() if USES_RE.match(line)]
        self.assertEqual([u.split("@")[0] for u in uses],
                         ["actions/checkout", "actions/setup-python", "actions/upload-artifact"])
        upload = self.job.split("name: Befund hochladen\n", 1)[1]
        self.assertIn("if: failure()", upload)
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
        self.assertIn("timeout -s TERM", script)
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
