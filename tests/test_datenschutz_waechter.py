"""Datenschutz-Wächter (.github/scripts/datenschutz_waechter.py): Repository sauber, Prüfungen greifen.

Testadressen und -orte liegen bewusst außerhalb der Beispielbereiche; diese Datei steht darum in
den Ausnahmen des Wächters.
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("datenschutz_waechter",
                                              ROOT / ".github" / "scripts" / "datenschutz_waechter.py")
waechter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waechter
SPEC.loader.exec_module(waechter)


class RepositoryTest(unittest.TestCase):
    def test_repository_ist_sauber(self):
        funde = waechter.pruefe_dateien()
        self.assertEqual([str(f) for f in funde], [])


class CiTest(unittest.TestCase):
    def test_ci_ruft_den_waechter_auf(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("name: Datenschutz-Wächter", ci)
        self.assertIn('--commits "$BASE..$HEAD_SHA" --pr-text', ci)
        self.assertIn("PR_BODY: ${{ github.event.pull_request.body }}", ci)

    def test_ausgabe_in_actions_ohne_wert(self):
        fund = waechter.pruefe_text("server 10.200.0.5 iburst", "x")[0]
        self.assertNotIn("10.200", str(fund))
        self.assertIn("10.200.0.5", fund.lokal())


class LanTest(unittest.TestCase):
    def test_echte_netze_werden_gefunden(self):
        for text in ("server 10.200.0.5 iburst", "172.20.1.1", "192.168.77.10", "allow 192.168.77.0/24",
                     "fd3c:1a2b:3c4d::10", "ip fd3c:1a2b:3c4d::/48"):
            with self.subTest(text=text):
                self.assertTrue(waechter.lan_adressen(text))

    def test_beispiele_und_bereiche_sind_erlaubt(self):
        for text in ("192.168.1.5", "z. B. 10.0.30.0/24", "allow 10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                     "fd00::1", "fd00:30::/64", "fc00::/7", "fd12:3456:789a::5", "docker 172.17.0.1",
                     "192.0.2.10", "8.8.8.8", "Version 1.5.4", "1.2.3.4.5", "10.0.0.256"):
            with self.subTest(text=text):
                self.assertFalse(waechter.lan_adressen(text))


class KoordinatenTest(unittest.TestCase):
    def test_echte_koordinaten_werden_gefunden(self):
        for text in ('{"lat": 50.1109, "lon": 8.6821}', "lat=50.11", "Position 50.11092, 8.68212",
                     "-23.5505 -46.6333", "$GPGGA,123519,5006.655,N,00840.926,E,1,08",
                     "https://www.openstreetmap.org/?mlat=50.1109&mlon=8.6821"):
            with self.subTest(text=text):
                self.assertTrue(waechter.koordinaten(text))

    def test_beispielorte_und_kleine_zahlen_sind_erlaubt(self):
        for text in ('{"lat": 48.1371543, "lon": 11.5761249}', "52.52001, 13.405",
                     "$GPGGA,123519,4807.038,N,01131.000,E,1,08", "0.0015, -0.0031", "offset 0.001249811,-0.000712812",
                     '"lat": 0.25', "Version 1.5.4", "lat=48.14"):
            with self.subTest(text=text):
                self.assertFalse(waechter.koordinaten(text))


class HerkunftTest(unittest.TestCase):
    """Herkunftsangaben zu Nutzerdaten (wessen Daten, welches Paket, welcher Screenshot) gehören nicht
    ins Repository – die fachliche Begründung reicht."""

    def test_herkunftsangaben_werden_gefunden(self):
        for text in ("# Diagnosepaket eines Nutzers: Fix kommt und geht",
                     "aus dem Diagnosepaket des Maintainers", "Diagnosepaket der Rückmeldung",
                     "Diagnosepaket vom Dienstag", "Diagnosepaket 1234: Tagesgang", "das 2.0.1-Diagnosepaket",
                     "Fall aus einem Nutzer-Screenshot", "Screenshot des Nutzers: zweite Karte",
                     "Aufzeichnungen eines Nutzers", "Paket des Maintainers", "Rückmeldung aus einem Paket",
                     "Rückmeldung mit 1.3.2", "Rückmeldung: Test brach ab", "17 Clients (wie im Paket)",
                     "wie im Diagnosepaket des Nutzers", "Nutzerfall: Offset zurückgesetzt",
                     "pendelte sie (Paket 1.5.3: ± 22 ms)", "im Paket der Rückmeldung",
                     "nach Auswertung eines Diagnosepakets", "chronyc-Ausgaben vom Pi 4 des Maintainers",
                     "Diagnose 1.6.0: Fix fehlt", "siehe Rückmeldung R1"):
            with self.subTest(text=text):
                self.assertTrue(waechter.herkunftsangaben(text))
                self.assertTrue(waechter.pruefe_text(text, "x"))

    def test_produktfunktion_und_rollen_sind_erlaubt(self):
        for text in ("Diagnosepaket (ein Klick, mit Vorschau)", "Das Diagnosepaket entfernt Seriennummern.",
                     "genau das, was im Paket stünde", "Liste aus dem Paket tzdata", "Repositories eines Nutzers",
                     "Ping an einen Dienst des Nutzers", "Entscheidung des Maintainers", "Rückmeldungen im Formular",
                     "wie beim Diagnosepaket", "Ins Diagnosepaket kommt sie nur, wenn du es ankreuzt",
                     "Diagnosepaket mit Aufzeichnung deutlich schneller", "seit Version 1.6.3"):
            with self.subTest(text=text):
                self.assertFalse(waechter.herkunftsangaben(text))

    def test_commit_nachricht_wird_geprueft(self):
        repo = CommitTest._repo(self, "12345+jemand@users.noreply.github.com", "Diagnosepaket 1234: Schranke")
        funde = waechter.pruefe_commits("HEAD~1..HEAD", cwd=repo)
        self.assertEqual([f.art for f in funde], ["Herkunftsangabe zu Nutzerdaten"])

    def test_waechter_selbst_ist_ausgenommen(self):
        self.assertIn(".github/scripts/datenschutz_waechter.py", waechter.HERKUNFT_AUSNAHMEN)


class CommitTest(unittest.TestCase):
    def _repo(self, mail: str, nachricht: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)], check=False))
        env = {"GIT_AUTHOR_NAME": "Jemand", "GIT_AUTHOR_EMAIL": mail, "GIT_COMMITTER_NAME": "Jemand",
               "GIT_COMMITTER_EMAIL": mail, "HOME": str(tmp), "PATH": "/usr/bin:/bin"}
        for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "Anfang"],
                     ["commit", "-q", "--allow-empty", "-m", nachricht]):
            subprocess.run(["git", *args], cwd=tmp, env=env, check=True)
        return tmp

    def test_noreply_ist_pflicht(self):
        repo = self._repo("jemand@example.org", "Änderung")
        arten = [f.art for f in waechter.pruefe_commits("HEAD~1..HEAD", cwd=repo)]
        self.assertIn("Autor ohne noreply-Adresse", arten)
        self.assertIn("Committer ohne noreply-Adresse", arten)

    def test_nachricht_wird_geprueft(self):
        repo = self._repo("12345+jemand@users.noreply.github.com", "Server 10.200.0.5 ergänzt")
        funde = waechter.pruefe_commits("HEAD~1..HEAD", cwd=repo)
        self.assertEqual(len(funde), 1)
        self.assertIn("LAN-Adresse", funde[0].art)

    def test_saubere_commits(self):
        for mail in ("12345+jemand@users.noreply.github.com", "noreply@github.com", "noreply@anthropic.com",
                     "41898282+github-actions[bot]@users.noreply.github.com"):
            with self.subTest(mail=mail):
                repo = self._repo(mail, "Doku ergänzt")
                self.assertEqual(waechter.pruefe_commits("HEAD~1..HEAD", cwd=repo), [])


if __name__ == "__main__":
    unittest.main()
