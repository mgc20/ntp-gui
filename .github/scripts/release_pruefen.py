#!/usr/bin/env python3
"""Vor einem Release prüfen, ob die Version überall stimmt.

Aufruf (im Release-Workflow, Schritt „Version prüfen“):

    python3 .github/scripts/release_pruefen.py 1.6.0

Bricht mit Exit-Code 1 und einer ::error::-Zeile ab, wenn
  * die Version kein SemVer (x.y.z) ist,
  * der Standard von VERSION in app/server.py nicht gleich der Version ist
    (sonst meldet sich das Image mit der alten Nummer – so geschehen bei 1.5.5),
  * CHANGELOG.md keinen Abschnitt „## [<version>]“ hat.

Nur Standardbibliothek; wird auch von tests/test_release_version.py benutzt.
"""

import argparse
import re
import sys
from pathlib import Path

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
# Gleiche Form, die docker/entrypoint.sh per sed liest.
SERVER_VERSION_RE = re.compile(r'^VERSION = os\.environ\.get\("NTPGUI_VERSION", "([^"]*)"\)', re.M)
SECTION_RE = re.compile(r"^## \[([^\]]+)\]", re.M)
UNRELEASED = "Unveröffentlicht"


def server_version(root: Path) -> str:
    text = (root / "app" / "server.py").read_text(encoding="utf-8")
    match = SERVER_VERSION_RE.search(text)
    if not match:
        raise ValueError('app/server.py: Zeile VERSION = os.environ.get("NTPGUI_VERSION", "…") fehlt')
    return match.group(1)


def changelog_state(text: str) -> tuple[bool, list[str]]:
    """(hat [Unveröffentlicht] Einträge?, veröffentlichte Versionen von oben nach unten)."""
    matches = list(SECTION_RE.finditer(text))
    unreleased = False
    released: list[str] = []
    for index, match in enumerate(matches):
        name = match.group(1)
        if name == UNRELEASED:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end():end]
            unreleased = any(line.lstrip().startswith(("-", "*")) for line in body.splitlines())
        elif SEMVER_RE.match(name):
            released.append(name)
    return unreleased, released


def check(version: str, root: Path) -> list[str]:
    if not SEMVER_RE.match(version):
        return [f"Version '{version}' ist kein SemVer (erwartet z. B. 1.0.0)"]
    errors = []
    try:
        current = server_version(root)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    else:
        if current != version:
            errors.append(f"app/server.py hat VERSION {current}, der Release soll {version} werden – "
                          "VERSION erst im Vorbereitungs-PR anheben")
    _, released = changelog_state((root / "CHANGELOG.md").read_text(encoding="utf-8"))
    if version not in released:
        errors.append(f"CHANGELOG.md hat keinen Abschnitt „## [{version}]“ – "
                      "[Unveröffentlicht] erst im Vorbereitungs-PR umbenennen")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    errors = check(args.version, args.root)
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print(f"Version {args.version}: app/server.py und CHANGELOG.md passen.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
