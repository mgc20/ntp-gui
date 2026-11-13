#!/usr/bin/env python3
"""Datenschutz-Wächter: ein Sicherheitsnetz gegen Versehen, bevor Privates öffentlich wird.

Prüft alle Dateien im Repository und (in Pull Requests) die neuen Commits sowie Titel und
Beschreibung des PR auf:

1. **Private LAN-Adressen** (RFC 1918, IPv6-ULA) außerhalb der Beispielnetze unten – typisch,
   wenn Testdaten aus einem echten Diagnosepaket oder einer echten Konfiguration entstehen.
2. **Echte Koordinaten**: Werte bei lat/lon, Zahlenpaare im Koordinatenformat, NMEA-Positionen
   und mlat/mlon in Karten-Links – außer bekannten Beispielorten.
3. **Herkunftsangaben zu Nutzerdaten**: Kommentare, Tests, Doku und Commit-Nachrichten begründen
   fachlich, nicht mit der Herkunft der Daten (kein „Diagnosepaket eines Nutzers“, keine Paketnummer,
   kein „Screenshot des Nutzers“, keine „Rückmeldung: …“). Das Wort „Diagnosepaket“ als Name der
   Produktfunktion bleibt erlaubt. Die Muster sind allgemein; private Kennungen stehen hier nie.
4. **Commit-Metadaten**: Autor und Committer nur mit noreply-Adresse; Namen und Nachricht laufen
   durch dieselben Prüfungen wie Dateien.

Bewusst schlank: Es fängt Versehen ab, keine Absicht, und kennt nicht jede Schreibweise.

Aufruf:
    python3 .github/scripts/datenschutz_waechter.py                 # alle Dateien
    python3 .github/scripts/datenschutz_waechter.py --commits A..B  # zusätzlich Commits A..B

Nur Standardbibliothek. Exit-Code 1 bei Funden. In GitHub Actions nennt die Ausgabe nur Ort und
Art, nie den gefundenen Wert – sonst stünde er im öffentlichen Log.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Beispielnetze, die in Doku, Oberfläche und Tests vorkommen dürfen. Alles andere aus RFC 1918
# bzw. fc00::/7 gilt als echtes Netz. Neue Beispiele bitte aus diesen Bereichen nehmen oder aus
# den Doku-Bereichen RFC 5737 (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) bzw. 2001:db8::/32.
BEISPIELNETZE = tuple(ipaddress.ip_network(n) for n in (
    "192.168.1.0/24", "192.168.0.0/24", "192.168.3.0/24", "192.168.20.0/24",
    "10.0.0.0/16", "10.1.2.0/24", "10.9.9.0/24", "10.77.0.0/24",
    "172.16.0.0/24", "172.17.0.0/16", "172.18.0.0/16",  # 172.17/18: Docker-Standardnetze
    "172.31.77.0/24", "172.31.78.0/24",
    "fd00::/16", "fc00::/16", "fd12:3456:789a::/48",  # letzteres: übliches ULA-Beispiel
))
# Die privaten Gesamtbereiche selbst (z. B. „10.0.0.0/8“ in Code und Doku) sind kein Netz eines Nutzers.
PRIVATE_BEREICHE = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7", "fd00::/8",
))
RFC1918 = PRIVATE_BEREICHE[:3]
ULA = ipaddress.ip_network("fc00::/7")

# Beispielorte (Breite, Länge): bekannte öffentliche Plätze und erfundene Testwerte.
BEISPIELORTE = (
    (48.1372, 11.5761),  # München, Marienplatz
    (52.5200, 13.4050),  # Berlin, Mitte
    (48.1173, 11.5167),  # NMEA-Normbeispiel „4807.038,N,01131.000,E“
    (45.1235, 10.5432),  # erfundener Testwert
    (33.8688, 151.2093),  # Sydney, Opernhaus-Viertel
    (53.3613, 6.5056),   # gpsd-Dokumentation, Beispielsatz „5321.6802,N,00630.3372,W“
)
TOLERANZ_GRAD = 0.01  # ≈ 1 km

# Dateien, die nicht geprüft werden (Binärdateien werden ohnehin übersprungen).
AUSNAHMEN = frozenset({
    "tests/fixtures/leap-seconds.list",          # offizielle IERS-Datei, unverändert
    "tests/fixtures/leap-seconds-expired.list",
    "tests/test_datenschutz_waechter.py",        # enthält absichtlich Fundbeispiele
})

# Nur für die Herkunftsprüfung ausgenommen: Diese Datei beschreibt die Muster selbst.
HERKUNFT_AUSNAHMEN = frozenset({
    ".github/scripts/datenschutz_waechter.py",
})

NOREPLY_RE = re.compile(r"^(?:\d+\+)?[^@\s]+@users\.noreply\.github\.com$|^noreply@(?:github|anthropic)\.com$")

IPV4_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2}))?(?![\d]|\.\d)")
IPV6_RE = re.compile(r"(?<![0-9a-f:])(f[cd][0-9a-f]{2}:[0-9a-f:]*[0-9a-f:])(?:/(\d{1,3}))?", re.IGNORECASE)
KOORD_SCHLUESSEL_RE = re.compile(
    r"\b(m?lat|latitude|m?lon|lng|longitude)\b[\"']?\s*[:=]\s*[\"']?(-?\d{1,3}\.\d{2,})", re.IGNORECASE)
KOORD_PAAR_RE = re.compile(r"(?<![\d.])(-?\d{1,2}\.\d{4,})\s*[,; ]\s*(-?\d{1,3}\.\d{4,})(?![\d.])")
NMEA_RE = re.compile(r"(\d{2})(\d{2}\.\d+),([NS]),(\d{3})(\d{2}\.\d+),([EW])")
# Herkunftsangaben zu Nutzerdaten: wessen Paket, welche Paketnummer, welcher Screenshot.
HERKUNFT_RE = re.compile(r"""
    Diagnosepakets?\s+(?:eines|des|der)\s+(?:Nutzers|Nutzerin|Anwenders|Maintainers|Rückmeldung)
  | Diagnosepakets?\s+(?:vom|aus)\b
  | Diagnosepakets?\s+\d
  | \d+\.\d+(?:\.\d+)?-(?:Diagnose)?pakets?\b
  | (?:Screenshot|Aufzeichnung(?:en)?|Paket|Diagnosepaket)\s+(?:eines|des)\s+(?:Nutzers|Nutzerin|Maintainers)
  | Nutzer-?Screenshot | Nutzerfall
  | Rückmeldung\s*(?:aus\b|mit\b|:|\()
  | wie\s+im\s+(?:Diagnose)?paket\b
  | \bPaket\s+\d+\.\d
  | \bPakets?\s+der\s+Rückmeldung
  | Auswertung\s+(?:eines|des)\s+(?:Diagnose)?pakets\b
  | \bvom\s+\S+(?:\s+\S+)?\s+des\s+(?:Nutzers|Nutzerin|Maintainers)\b
  | Diagnose\s+\d+\.\d+\.\d+:
  | Rückmeldung\s+R\d
""", re.IGNORECASE | re.VERBOSE)


@dataclass(frozen=True)
class Fund:
    ort: str
    zeile: int
    art: str
    wert: str = ""

    def __str__(self) -> str:
        return f"{self.ort}:{self.zeile}: {self.art}"

    def lokal(self) -> str:
        return f"{self}: {self.wert}" if self.wert else str(self)


def _privat_und_kein_beispiel(netz: ipaddress._BaseNetwork) -> bool:
    if netz in PRIVATE_BEREICHE:
        return False
    if netz.version == 4 and not any(netz.subnet_of(n) for n in RFC1918):
        return False
    if netz.version == 6 and not netz.subnet_of(ULA):
        return False
    return not any(netz.version == b.version and netz.subnet_of(b) for b in BEISPIELNETZE)


def lan_adressen(text: str) -> list[tuple[str, str]]:
    arten = []
    for match in IPV4_RE.finditer(text):
        addr, prefix = match.groups()
        try:
            netz = ipaddress.ip_network(f"{addr}/{prefix or 32}", strict=False)
        except ValueError:
            continue
        if _privat_und_kein_beispiel(netz):
            arten.append(("private LAN-Adresse außerhalb der Beispielnetze", netz.with_prefixlen))
    for match in IPV6_RE.finditer(text):
        addr, prefix = match.groups()
        try:
            if addr.endswith(":") and not addr.endswith("::"):
                addr = addr[:-1]
            netz = ipaddress.ip_network(f"{addr}/{prefix or 128}", strict=False)
        except ValueError:
            continue
        if _privat_und_kein_beispiel(netz):
            arten.append(("private IPv6-Adresse außerhalb der Beispielnetze", netz.with_prefixlen))
    return arten


def _nah(wert: float, ziel: float) -> bool:
    return abs(abs(wert) - ziel) <= TOLERANZ_GRAD


def _beispielort(breite: float, laenge: float) -> bool:
    return any(_nah(breite, b) and _nah(laenge, l) for b, l in BEISPIELORTE)


def _beispielwert(wert: float) -> bool:
    """Ein einzelner Wert verrät keinen Ort; erlaubt, wenn er zu irgendeinem Beispielort passt."""
    return any(_nah(wert, b) or _nah(wert, l) for b, l in BEISPIELORTE)


def koordinaten(text: str) -> list[tuple[str, str]]:
    arten = []
    for match in KOORD_SCHLUESSEL_RE.finditer(text):
        schluessel, wert = match.group(1).lower(), float(match.group(2))
        if abs(wert) < 1:
            continue  # 0,0x° ist kein Ort, eher eine Abweichung
        if not _beispielwert(wert):
            arten.append((f"Koordinate bei „{schluessel}“", match.group(2)))
    for match in KOORD_PAAR_RE.finditer(text):
        a, b = float(match.group(1)), float(match.group(2))
        if 1 <= abs(a) <= 90 and 1 <= abs(b) <= 180 and not (_beispielort(a, b) or
                                                              (_beispielwert(a) and _beispielwert(b))):
            arten.append(("Zahlenpaar im Koordinatenformat", match.group(0)))
    for match in NMEA_RE.finditer(text):
        breite = int(match.group(1)) + float(match.group(2)) / 60
        laenge = int(match.group(4)) + float(match.group(5)) / 60
        if not _beispielort(breite, laenge):
            arten.append(("Position in einem NMEA-Satz", match.group(0)))
    return arten


def herkunftsangaben(text: str) -> list[tuple[str, str]]:
    return [("Herkunftsangabe zu Nutzerdaten", m.group(0)) for m in HERKUNFT_RE.finditer(text)]


def pruefe_text(text: str, ort: str, herkunft: bool = True) -> list[Fund]:
    funde = []
    for nummer, zeile in enumerate(text.splitlines(), 1):
        arten = lan_adressen(zeile) + koordinaten(zeile)
        if herkunft:
            arten += herkunftsangaben(zeile)
        for art, wert in arten:
            funde.append(Fund(ort, nummer, art, wert))
    return funde


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def pruefe_dateien() -> list[Fund]:
    funde = []
    for name in _git("ls-files", "-z").split("\0"):
        if not name or name in AUSNAHMEN:
            continue
        pfad = ROOT / name
        if not pfad.is_file():
            continue
        roh = pfad.read_bytes()
        if b"\0" in roh[:8192]:
            continue  # Binärdatei
        funde.extend(pruefe_text(name, f"{name} (Dateiname)"))
        funde.extend(pruefe_text(roh.decode("utf-8", errors="replace"), name,
                                 herkunft=name not in HERKUNFT_AUSNAHMEN))
    return funde


def pruefe_commits(bereich: str, cwd: Path = ROOT) -> list[Fund]:
    funde = []
    trenner = "\x1e"
    log = _git("log", f"--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B{trenner}", bereich, cwd=cwd)
    for eintrag in log.split(trenner):
        if not eintrag.strip():
            continue
        sha, an, ae, cn, ce, nachricht = eintrag.strip("\n").split("\x1f", 5)
        ort = f"Commit {sha[:10]}"
        for rolle, mail in (("Autor", ae), ("Committer", ce)):
            if not NOREPLY_RE.match(mail.strip().lower()):
                funde.append(Fund(ort, 0, f"{rolle} ohne noreply-Adresse"))
        funde.extend(pruefe_text("\n".join((an, cn, nachricht)), ort))
    return funde


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commits", metavar="A..B", help="zusätzlich die Commits in diesem Bereich prüfen")
    parser.add_argument("--keine-dateien", action="store_true", help="nur Commits prüfen")
    parser.add_argument("--pr-text", action="store_true",
                        help="zusätzlich Titel und Beschreibung des PR aus PR_TITLE/PR_BODY prüfen")
    args = parser.parse_args(argv)
    funde = [] if args.keine_dateien else pruefe_dateien()
    if args.commits:
        funde.extend(pruefe_commits(args.commits))
    if args.pr_text:
        funde.extend(pruefe_text(os.environ.get("PR_TITLE", ""), "PR-Titel"))
        funde.extend(pruefe_text(os.environ.get("PR_BODY", ""), "PR-Beschreibung"))
    for fund in funde:
        print(f"::error::{fund}" if "GITHUB_ACTIONS" in os.environ else fund.lokal())
    if funde:
        print(f"\nDatenschutz-Wächter: {len(funde)} Fund(e). Bitte entfernen oder durch Beispielwerte ersetzen "
              "(Beispielnetze und -orte stehen in .github/scripts/datenschutz_waechter.py).", file=sys.stderr)
        return 1
    print("Datenschutz-Wächter: keine Funde.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
