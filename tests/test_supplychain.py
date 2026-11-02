"""Lieferkette: Workflows, Dependabot und Dockerfile halten, was die Kommentare versprechen.

* jede Action ist auf einen vollen Commit-SHA festgenagelt (mit Versionskommentar);
* das OIDC-Token (id-token: write) gibt es nur im Job „attest“, und dort läuft nur
  actions/attest-build-provenance;
* das Basis-Image ist per Digest festgenagelt (sonst hat Dependabot nichts zu vergleichen);
* Release-Builds laufen ohne Cache, SBOM und Scan gelten dem hochgeladenen Digest je Architektur.

Ohne YAML-Bibliothek (PyYAML ist keine Abhängigkeit): zeilenweise Prüfung.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")


def jobs(text: str) -> dict[str, str]:
    """Job-Name → Text des Jobs (Einrückung zwei Leerzeichen unter „jobs:“)."""
    body = text.split("\njobs:\n", 1)[1]
    out: dict[str, str] = {}
    name = None
    for line in body.splitlines():
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            name = match.group(1)
            out[name] = ""
        elif name:
            out[name] += line + "\n"
    return out


class SupplyChainTest(unittest.TestCase):
    def test_every_action_pinned_to_sha(self):
        self.assertTrue(WORKFLOWS)
        for path in WORKFLOWS:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                match = USES_RE.match(line)
                if not match:
                    continue
                ref, rest = match.groups()
                with self.subTest(file=path.name, line=number):
                    if ref.startswith("./"):
                        continue
                    self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$", "Action nicht per Commit-SHA festgenagelt")
                    self.assertRegex(rest, r"#\s*v\d+\.\d+\.\d+", "Versionskommentar fehlt")

    def test_oidc_token_only_in_attest_job(self):
        text = RELEASE.read_text(encoding="utf-8")
        top = "\n".join(line for line in text.split("\njobs:\n", 1)[0].splitlines() if not line.startswith("#"))
        self.assertIn("permissions: {}", top)
        self.assertNotIn("id-token", top)
        found = {name: body for name, body in jobs(text).items() if "id-token: write" in body}
        self.assertEqual(sorted(found), ["attest"])
        uses = [USES_RE.match(line).group(1) for line in found["attest"].splitlines() if USES_RE.match(line)]
        self.assertEqual([u.split("@")[0] for u in uses], ["actions/attest-build-provenance"])

    def test_release_scans_pushed_digest_per_arch_without_cache(self):
        text = RELEASE.read_text(encoding="utf-8")
        self.assertNotIn("type=gha", text)
        self.assertEqual(text.count("no-cache: true"), 2)
        self.assertIn("push-by-digest=true", text)
        self.assertIn('registry:${REF}" --platform "linux/${arch}"', text)
        self.assertIn("for arch in amd64 arm64", text)
        self.assertIn("--only-fixed --fail-on critical", text)
        self.assertNotIn("ntp-gui:release-test\n          format", text)
        # Image-Tags erst nach Scan und Nachweis
        self.assertIn("needs: [build, attest]", text)
        # Privates Repository: Nachweis wird übersprungen, der Release läuft trotzdem (1.4.0-Release-Lauf)
        self.assertIn("github.event.repository.private == false", text)
        self.assertIn("needs.attest.result == 'skipped'", text)

    def test_base_image_pinned_by_digest(self):
        froms = [line for line in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
                 if line.startswith("FROM ")]
        self.assertTrue(froms)
        for line in froms:
            self.assertRegex(line, r"^FROM debian:trixie-slim@sha256:[0-9a-f]{64}(\s|$)")
        dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        self.assertIn("package-ecosystem: docker", dependabot)
        self.assertIn("package-ecosystem: github-actions", dependabot)


if __name__ == "__main__":
    unittest.main()
