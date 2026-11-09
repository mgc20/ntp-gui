"""Release mit richtiger Version (Befund 1.5.5: Image v1.5.5 meldete sich als 1.5.4).

* VERSION in app/server.py passt zum CHANGELOG: gleich dem obersten veröffentlichten Abschnitt,
  höher nur, wenn unter [Unveröffentlicht] schon etwas steht (Release-Vorbereitung). So blockiert
  der Test keinen normalen PR, fällt aber auf, sobald ein Release ohne angehobene VERSION
  vorbereitet wird.
* Der Release-Workflow bricht ab, wenn VERSION nicht gleich inputs.version ist oder der CHANGELOG
  keinen Abschnitt „## [<version>]“ hat (.github/scripts/release_pruefen.py).
"""

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "release_pruefen.py"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"


def load_script():
    spec = importlib.util.spec_from_file_location("release_pruefen", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def semver(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def make_repo(base: Path, version: str, changelog: str) -> Path:
    (base / "app").mkdir()
    (base / "app" / "server.py").write_text(
        'import os\nVERSION = os.environ.get("NTPGUI_VERSION", "%s")\n' % version, encoding="utf-8")
    (base / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return base


CHANGELOG = """# Changelog

## [Unveröffentlicht]

### Behoben
- etwas

## [2.1.0] – 2026-01-02

### Behoben
- etwas anderes

## [2.0.0] – 2026-01-01
"""


class VersionMatchesChangelogTest(unittest.TestCase):
    def test_server_version_consistent_with_changelog(self):
        mod = load_script()
        version = mod.server_version(ROOT)
        unreleased, released = mod.changelog_state((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertTrue(released, "CHANGELOG ohne veröffentlichten Abschnitt")
        top = released[0]
        if unreleased:
            self.assertGreaterEqual(
                semver(version), semver(top),
                f"VERSION {version} in app/server.py ist älter als der oberste Abschnitt [{top}] im CHANGELOG")
        else:
            self.assertEqual(
                version, top,
                f"VERSION {version} in app/server.py passt nicht zum obersten Abschnitt [{top}] im CHANGELOG "
                "(höher nur, wenn unter [Unveröffentlicht] schon Einträge stehen)")

    def test_changelog_state_parsing(self):
        mod = load_script()
        self.assertEqual(mod.changelog_state(CHANGELOG), (True, ["2.1.0", "2.0.0"]))
        empty = CHANGELOG.replace("### Behoben\n- etwas\n\n## [2.1.0]", "## [2.1.0]", 1)
        self.assertEqual(mod.changelog_state(empty), (False, ["2.1.0", "2.0.0"]))

    def test_entrypoint_sed_still_matches_server_line(self):
        # entrypoint.sh liest die Version per sed aus server.py – die Zeile muss genau diese Form haben.
        line = next(l for l in (ROOT / "app" / "server.py").read_text(encoding="utf-8").splitlines()
                    if l.startswith("VERSION = "))
        self.assertRegex(line, r'^VERSION = os\.environ\.get\("NTPGUI_VERSION", "\d+\.\d+\.\d+"\)$')
        self.assertIn('s/^VERSION = os\\.environ\\.get("NTPGUI_VERSION", "\\([^"]*\\)").*/\\1/p',
                      ENTRYPOINT.read_text(encoding="utf-8"))


class ReleaseCheckScriptTest(unittest.TestCase):
    def run_check(self, version: str, server: str, changelog: str = CHANGELOG):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(Path(tmp), server, changelog)
            return subprocess.run([sys.executable, "-I", str(SCRIPT), version, "--root", tmp],
                                  capture_output=True, text=True, timeout=30)

    def test_ok_when_version_and_section_match(self):
        result = self.run_check("2.1.0", "2.1.0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fails_when_server_version_not_raised(self):
        # genau der Fall 1.5.5: Release-Version eingetragen, server.py noch auf der alten
        result = self.run_check("2.1.0", "2.0.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("::error::", result.stdout)
        self.assertIn("2.0.0", result.stdout)

    def test_fails_without_changelog_section(self):
        result = self.run_check("2.2.0", "2.2.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("## [2.2.0]", result.stdout)

    def test_unreleased_heading_does_not_count(self):
        result = self.run_check("2.2.0", "2.2.0", CHANGELOG.replace("[Unveröffentlicht]", "[2.2.0-rc]"))
        self.assertNotEqual(result.returncode, 0)

    def test_fails_on_non_semver(self):
        result = self.run_check("2.1", "2.1")
        self.assertNotEqual(result.returncode, 0)


class ReleaseWorkflowUsesCheckTest(unittest.TestCase):
    def test_version_step_runs_check_before_build(self):
        text = RELEASE.read_text(encoding="utf-8")
        build = text.split("\n  build:\n", 1)[1].split("\n  attest:\n", 1)[0]
        step = re.search(r"- name: Version prüfen\n(.*?)(?=\n      - )", build, re.S)
        self.assertIsNotNone(step, "Schritt „Version prüfen“ fehlt")
        self.assertIn('python3 .github/scripts/release_pruefen.py "$VERSION"', step.group(1))
        self.assertLess(build.index("Version prüfen"), build.index("build-push-action"))


if __name__ == "__main__":
    unittest.main()
