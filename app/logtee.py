#!/usr/bin/env python3
"""Kleiner, robuster „tee“ für die Ausgabe des Supervisors.

Liest stdin zeilenweise, gibt jede Zeile unverändert auf stdout aus (Container-
Log, ``docker logs``) und hängt sie an ``$NTPGUI_RUN_DIR/ntp-gui.log`` an –
dort liest die Log-Seite des Dashboards und das Diagnosepaket.

* Rotation: ab 2 MB wird die Datei zu ``ntp-gui.log.1`` (nur eine alte Datei).
* Jede Zeile wird sofort geschrieben (flush), damit nichts im Puffer hängt.
* Schreibfehler an der Datei (voll, gelöscht, keine Rechte) beenden den tee nie:
  dann geht es nur auf stdout weiter; später wird es erneut versucht.
* Ein Fehler auf stdout (Leser weg) beendet ihn ebenfalls nicht – die Datei
  bekommt die Zeilen weiter.
* SIGTERM/SIGINT/SIGHUP werden ignoriert: Der Supervisor wird beim Stoppen
  benachrichtigt und schreibt danach noch Zeilen. Der tee endet erst, wenn
  stdin geschlossen ist (alle Schreiber beendet).
"""

from __future__ import annotations

import os
import signal
import sys
import time

MAX_BYTES = 2 * 1024 * 1024
RETRY_AFTER = 30.0  # Sekunden bis zum nächsten Öffnungsversuch nach einem Fehler


class RotatingFile:
    def __init__(self, path: str, max_bytes: int = MAX_BYTES) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.handle = None
        self.size = 0
        self.failed_at = 0.0

    def _open(self) -> bool:
        if self.handle is not None:
            return True
        if self.failed_at and time.monotonic() - self.failed_at < RETRY_AFTER:
            return False
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            self.handle = open(self.path, "ab", buffering=0)
            self.size = self.handle.tell()
            self.failed_at = 0.0
            return True
        except OSError:
            self.handle = None
            self.failed_at = time.monotonic()
            return False

    def close(self) -> None:
        self._close()

    def _close(self) -> None:
        if self.handle is not None:
            try:
                self.handle.close()
            except OSError:
                pass
        self.handle = None

    def _rotate(self) -> None:
        self._close()
        try:
            os.replace(self.path, self.path + ".1")
        except OSError:
            # Umbenennen klappt nicht: lieber kürzen als unbegrenzt wachsen.
            try:
                with open(self.path, "wb"):
                    pass
            except OSError:
                pass
        self.size = 0

    def write(self, data: bytes) -> None:
        try:
            if self.handle is not None and not os.path.exists(self.path):
                self._close()  # Datei wurde gelöscht – neu anlegen
            if not self._open():
                return
            if self.size + len(data) > self.max_bytes and self.size > 0:
                self._rotate()
                if not self._open():
                    return
            self.handle.write(data)
            self.size += len(data)
        except (OSError, ValueError):
            self._close()
            self.failed_at = time.monotonic()


def log_path(run_dir: str | None = None) -> str:
    run_dir = run_dir or os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")
    return os.path.join(run_dir, "ntp-gui.log")


def run(stdin=None, stdout=None, path: str | None = None, max_bytes: int = MAX_BYTES) -> int:
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    target = RotatingFile(path or log_path(), max_bytes)
    stdout_ok = True
    while True:
        try:
            line = stdin.readline()
        except KeyboardInterrupt:
            continue
        except OSError:
            break
        if not line:
            break
        if stdout_ok:
            try:
                stdout.write(line)
                stdout.flush()
            except (OSError, ValueError):
                stdout_ok = False
        target.write(line)
    target.close()
    return 0


def main() -> int:
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, signal.SIG_IGN)
        except (OSError, ValueError):
            pass
    path = sys.argv[1] if len(sys.argv) > 1 else None
    return run(path=path)


if __name__ == "__main__":
    sys.exit(main())
