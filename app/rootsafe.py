"""Dateizugriffe des Supervisors (root) in Verzeichnissen, die dem Benutzer ntpgui gehören (1.9).

Das Dashboard läuft als ntpgui und kann in seinem Datenverzeichnis und in REQUEST_DIR beliebige
Namen anlegen, umbenennen und ersetzen. Prüft root dort erst einen Pfad und öffnet ihn danach,
kann sich zwischen beiden Schritten das Objekt ändern. Darum arbeitet dieses Modul nur über
Dateideskriptoren: erst öffnen (ohne Links zu folgen, ohne zu blockieren), dann am geöffneten
Objekt prüfen und handeln.

  hold <datei>              gibt die ersten 16 Zeichen einer gewöhnlichen Datei aus (reload.hold);
                            Links, Pipes und andere Dateiarten ergeben eine leere Ausgabe.
  chown <verzeichnis> <benutzer>
                            übergibt Verzeichnisse und Dateien mit genau einem Namen an den
                            Benutzer. Dateien mit weiteren Namen (Hardlinks) bleiben unverändert,
                            sie könnten auf Dateien außerhalb des Verzeichnisses zeigen, und
                            werden ausgegeben. Links, Pipes und Sockets bleiben ebenfalls, wie sie sind.

Nur Standardbibliothek; Exit-Code 0, auch wenn einzelne Einträge übersprungen wurden.
"""

from __future__ import annotations

import os
import stat
import sys

HOLD_MAX = 16


def read_hold(path: str) -> str:
    """Inhalt (höchstens HOLD_MAX Zeichen) einer gewöhnlichen Datei, sonst ""."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
    except OSError:
        return ""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return ""
        return os.read(fd, HOLD_MAX).decode("ascii", "replace")
    except OSError:
        return ""
    finally:
        os.close(fd)


def _chown_entry(dir_fd: int, name: str, uid: int, gid: int, chown=os.chown) -> str:
    """Einen Eintrag übergeben -> "ok", "skip-links", "skip-type" oder "gone"."""
    try:
        fd = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    except OSError:
        return "gone"
    try:
        st = os.fstat(fd)
        if st.st_uid == uid and st.st_gid == gid:
            return "ok"
        if stat.S_ISREG(st.st_mode):
            if st.st_nlink != 1:
                return "skip-links"
        elif not stat.S_ISDIR(st.st_mode):
            return "skip-type"   # Links, Pipes, Sockets: weder nötig noch sicher
        # Über den Deskriptor: trifft genau das geprüfte Objekt, auch wenn der Name inzwischen
        # auf etwas anderes zeigt.
        chown(f"/proc/self/fd/{fd}", uid, gid)
        return "ok"
    except OSError:
        return "gone"
    finally:
        os.close(fd)


def chown_tree(top: str, uid: int, gid: int, chown=os.chown) -> list[str]:
    """Verzeichnisbaum übergeben (fwalk: folgt keinen Links). Gibt die übersprungenen Pfade zurück."""
    skipped: list[str] = []
    try:
        top_fd = os.open(top, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return skipped
    try:
        parent, base = os.path.split(os.path.abspath(top))
        parent_fd = os.open(parent or "/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            if _chown_entry(parent_fd, base, uid, gid, chown) == "skip-links":
                skipped.append(top)
        finally:
            os.close(parent_fd)
    finally:
        os.close(top_fd)
    for dirpath, dirnames, filenames, dir_fd in os.fwalk(top, follow_symlinks=False):
        for name in dirnames + filenames:
            result = _chown_entry(dir_fd, name, uid, gid, chown)
            if result == "skip-links":
                skipped.append(os.path.join(dirpath, name))
    return skipped


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "hold":
        sys.stdout.write(read_hold(argv[1]))
        return 0
    if len(argv) == 3 and argv[0] == "chown":
        import pwd
        entry = pwd.getpwnam(argv[2])
        for path in chown_tree(argv[1], entry.pw_uid, entry.pw_gid):
            print(path)
        return 0
    print("Aufruf: rootsafe.py hold <datei> | chown <verzeichnis> <benutzer>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
