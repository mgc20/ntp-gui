"""Austauschbare Datenquellen: eine einzige Stelle für alle Abfragen an chronyc,
pmc, ethtool und den gpsd-Socket – mit Aufzeichnung und Wiedergabe.

Warum eine Engstelle? Nur so lässt sich vollständig mitschneiden, was das
Dashboard von den Diensten zu sehen bekommt (für Fehlerberichte), und dieselben
Antworten später ohne echte Hardware wieder abspielen (Entwicklung, Demo-Modus).

Aufzeichnung: start_recording(seconds) schreibt JSON-Zeilen
    {"t": Unixzeit, "kind": "chronyc"|"pmc"|"ethtool"|"gpsd", "args": [...], "out": "..."}
nach RUN_DIR/recording-<Zeitstempel>.jsonl (höchstens 3600 s und 20 MB).
Zusätzliche Felder: "rc" (Rückgabecode), "err" (stderr, falls vorhanden),
"error" ("missing"/"timeout"/"unreachable", wenn der Aufruf gar nicht lief) und
bei gpsd "s" (Sitzungsnummer – alle Zeilen einer Socket-Verbindung).
Die Datei bleibt lokal; was davon die Instanz verlässt, läuft durch egress.py.

Wiedergabe: NTPGUI_REPLAY=<datei.jsonl> (Tempo: NTPGUI_REPLAY_SPEED, Standard 1)
– dann führt kein Provider mehr echte Befehle aus. Für jede (kind, args)-Kombination
gilt der Eintrag, dessen t am nächsten ≤ (Start der Aufzeichnung + vergangene
Zeit × Tempo) liegt; am Ende beginnt die Wiedergabe von vorn.

CLI: python3 app/providers.py replay-info <datei.jsonl>
"""

from __future__ import annotations

import bisect
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

KINDS = ("chronyc", "pmc", "ethtool")
MAX_SECONDS = 3600
MAX_BYTES = 20 * 1024 * 1024
KEEP_RECORDINGS = 3  # ältere recording-*.jsonl werden beim Start einer neuen gelöscht

_DEFAULT_BINARIES = {
    "chronyc": "/usr/bin/chronyc",
    "pmc": "/usr/sbin/pmc",
    "ethtool": "/usr/sbin/ethtool",
}
# Pfad-Überschreibung, z. B. für Tests mit einem gefälschten chronyc.
_BINARY_ENV = {"chronyc": "NTPGUI_CHRONYC", "pmc": "NTPGUI_PMC", "ethtool": "NTPGUI_ETHTOOL"}


class ProviderError(RuntimeError):
    """Ein Provider-Aufruf ist gescheitert.

    reason: "missing" (Programm fehlt), "timeout", "failed" (Rückgabecode ≠ 0),
    "replay" (Eintrag fehlt in der Aufzeichnung), "unreachable" (gpsd).
    """

    def __init__(self, message: str, reason: str = "failed", returncode: int | None = None,
                 stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.reason = reason
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Result:
    """Ergebnis eines Befehls (wie subprocess.CompletedProcess, aber schlank)."""

    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode: int, stdout: str, stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __repr__(self) -> str:  # pragma: no cover - nur Fehlersuche
        return f"Result(rc={self.returncode}, stdout={len(self.stdout)} B)"


def run_dir() -> str:
    return os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")


def binary(kind: str) -> str:
    """Pfad zum Programm für einen Provider (Umgebungsvariable > PATH > Standard)."""
    override = os.environ.get(_BINARY_ENV.get(kind, ""), "").strip()
    if override:
        return override
    return shutil.which(kind) or _DEFAULT_BINARIES.get(kind, kind)


# ---------------------------------------------------------------------------
# Aufzeichnung
# ---------------------------------------------------------------------------

_REC_LOCK = threading.Lock()
_REC: dict[str, Any] = {
    "active": False, "until": None, "started": None, "path": None, "bytes": 0,
    "entries": 0, "stopped": None, "reason": None, "session": 0,
}


def _expire_locked(now: float | None = None) -> None:
    if _REC["active"] and _REC["until"] is not None and (now or time.time()) >= _REC["until"]:
        _REC["active"] = False
        _REC["stopped"] = _REC["until"]
        _REC["reason"] = "zeit"


def _cleanup_old(directory: str, keep: int) -> None:
    try:
        names = sorted(n for n in os.listdir(directory)
                       if n.startswith("recording-") and n.endswith(".jsonl"))
    except OSError:
        return
    for name in names[:max(0, len(names) - keep)]:
        try:
            os.unlink(os.path.join(directory, name))
        except OSError:
            pass


def start_recording(seconds: float = 300) -> dict[str, Any]:
    """Startet eine neue Aufzeichnung (läuft eine, wird sie beendet). 1 ≤ seconds ≤ 3600."""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        raise ValueError("Dauer muss eine Zahl (Sekunden) sein") from None
    if not 1 <= seconds <= MAX_SECONDS:
        raise ValueError(f"Dauer muss zwischen 1 und {MAX_SECONDS} Sekunden liegen")
    directory = run_dir()
    os.makedirs(directory, exist_ok=True)
    now = time.time()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    path = os.path.join(directory, f"recording-{stamp}.jsonl")
    suffix = 1
    while os.path.exists(path):
        suffix += 1
        path = os.path.join(directory, f"recording-{stamp}-{suffix}.jsonl")
    with _REC_LOCK:
        _cleanup_old(directory, KEEP_RECORDINGS - 1)
        with open(path, "w", encoding="utf-8"):
            pass
        try:
            os.chmod(path, 0o600)  # enthält Client-Adressen und ggf. Position
        except OSError:
            pass
        _REC.update(active=True, until=now + seconds, started=now, path=path, bytes=0,
                    entries=0, stopped=None, reason=None)
    return status()


def stop() -> dict[str, Any]:
    """Beendet die laufende Aufzeichnung; die Datei bleibt erhalten."""
    with _REC_LOCK:
        if _REC["active"]:
            _REC["active"] = False
            _REC["stopped"] = time.time()
            _REC["reason"] = "gestoppt"
    return status()


stop_recording = stop


def status() -> dict[str, Any]:
    """{"active","until","path","bytes","entries", ...} der aktuellen/letzten Aufzeichnung."""
    with _REC_LOCK:
        _expire_locked()
        result = {key: _REC[key] for key in ("active", "until", "started", "path", "bytes",
                                             "entries", "stopped", "reason")}
    result["max_seconds"] = MAX_SECONDS
    result["max_bytes"] = MAX_BYTES
    result["replay"] = replay_info_active()
    return result


def _record(kind: str, args: list[str], out: str, **extra: Any) -> None:
    if not _REC["active"]:  # schneller Pfad ohne Sperre
        return
    entry: dict[str, Any] = {"t": round(time.time(), 3), "kind": kind, "args": list(args), "out": out}
    for key, value in extra.items():
        if value not in (None, ""):
            entry[key] = value
    line = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    with _REC_LOCK:
        _expire_locked()
        if not _REC["active"] or not _REC["path"]:
            return
        if _REC["bytes"] + len(line) > MAX_BYTES:
            _REC["active"] = False
            _REC["stopped"] = time.time()
            _REC["reason"] = "größe"
            return
        try:
            with open(_REC["path"], "ab") as handle:
                handle.write(line)
        except OSError:
            _REC["active"] = False
            _REC["stopped"] = time.time()
            _REC["reason"] = "schreibfehler"
            return
        _REC["bytes"] += len(line)
        _REC["entries"] += 1


def _next_session() -> int:
    with _REC_LOCK:
        _REC["session"] += 1
        return _REC["session"]


# ---------------------------------------------------------------------------
# Wiedergabe
# ---------------------------------------------------------------------------

class Replay:
    """Eine geladene Aufzeichnung samt Wiedergabeuhr."""

    def __init__(self, path: str, speed: float = 1.0, clock=time.monotonic):
        self.path = path
        self.speed = speed if speed > 0 else 1.0
        self.clock = clock
        self.started = clock()
        self.commands: dict[tuple, tuple[list[float], list[dict]]] = {}
        self.gpsd: dict[str, list[tuple[float, list[dict]]]] = {}
        self.first_t = self.last_t = 0.0
        self.entries = 0
        self.skipped = 0
        self._load()

    def _load(self) -> None:
        commands: dict[tuple, list[dict]] = {}
        sessions: dict[tuple, list[dict]] = {}
        times: list[float] = []
        with open(self.path, encoding="utf-8") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                try:
                    entry = json.loads(raw)
                    t = float(entry["t"])
                    kind = str(entry["kind"])
                    args = [str(a) for a in entry.get("args") or []]
                except (ValueError, KeyError, TypeError):
                    self.skipped += 1
                    continue
                entry["t"], entry["args"] = t, args
                times.append(t)
                self.entries += 1
                if kind == "gpsd":
                    watch = args[0] if args else ""
                    sessions.setdefault((watch, entry.get("s", 0)), []).append(entry)
                else:
                    commands.setdefault(replay_key(kind, args), []).append(entry)
        if times:
            self.first_t, self.last_t = min(times), max(times)
        for key, items in commands.items():
            items.sort(key=lambda e: e["t"])
            self.commands[key] = ([e["t"] for e in items], items)
        for (watch, _), items in sessions.items():
            items.sort(key=lambda e: e["t"])
            self.gpsd.setdefault(watch, []).append((items[0]["t"], items))
        for watch in self.gpsd:
            self.gpsd[watch].sort(key=lambda s: s[0])

    @property
    def duration(self) -> float:
        return max(0.0, self.last_t - self.first_t)

    def position(self) -> float:
        """Aktuelle Wiedergabezeit (im Zeitraster der Aufzeichnung), mit Schleife."""
        elapsed = max(0.0, self.clock() - self.started) * self.speed
        if self.duration <= 0:
            return self.first_t
        # +1 s Pause zwischen Ende und Neubeginn, damit der letzte Stand kurz gilt.
        return self.first_t + elapsed % (self.duration + 1.0)

    def lookup(self, kind: str, args: list[str]) -> dict | None:
        found = self.commands.get(replay_key(kind, args))
        if not found:
            return None
        stamps, items = found
        index = bisect.bisect_right(stamps, self.position()) - 1
        return items[max(index, 0)]

    def gpsd_session(self, watch: str) -> list[dict] | None:
        sessions = self.gpsd.get(watch)
        if not sessions:
            # anderer WATCH-Befehl aufgezeichnet? Dann die längste passende Liste.
            sessions = max(self.gpsd.values(), key=len) if self.gpsd else None
        if not sessions:
            return None
        stamps = [s[0] for s in sessions]
        index = bisect.bisect_right(stamps, self.position()) - 1
        return sessions[max(index, 0)][1]


def replay_key(kind: str, args: list[str]) -> tuple:
    """Schlüssel für die Wiedergabe. Bei pmc zählt nur der Management-Befehl
    (letztes Argument) – Socketpfad und Domäne hängen vom jeweiligen Aufbau ab."""
    if kind == "pmc" and args:
        return (kind, args[-1])
    return (kind, *args)


_REPLAY_LOCK = threading.Lock()
_REPLAY: dict[str, Any] = {"key": None, "obj": None, "error": None}


def _replay() -> Replay | None:
    path = os.environ.get("NTPGUI_REPLAY", "").strip()
    if not path:
        return None
    try:
        speed = float(os.environ.get("NTPGUI_REPLAY_SPEED", "1") or 1)
    except ValueError:
        speed = 1.0
    try:
        mtime = os.stat(path).st_mtime
    except OSError as exc:
        with _REPLAY_LOCK:
            _REPLAY.update(key=None, obj=None, error=str(exc))
        raise ProviderError(f"Wiedergabedatei nicht lesbar: {exc}", reason="replay") from exc
    key = (path, mtime, speed)
    with _REPLAY_LOCK:
        if _REPLAY["key"] != key:
            try:
                _REPLAY["obj"] = Replay(path, speed)
                _REPLAY["error"] = None
            except OSError as exc:
                _REPLAY.update(obj=None, error=str(exc))
                raise ProviderError(f"Wiedergabedatei nicht lesbar: {exc}", reason="replay") from exc
            _REPLAY["key"] = key
        return _REPLAY["obj"]


def reset_replay() -> None:
    """Vergisst die geladene Wiedergabe (Tests, oder um von vorn zu beginnen)."""
    with _REPLAY_LOCK:
        _REPLAY.update(key=None, obj=None, error=None)


def replay_active() -> bool:
    return bool(os.environ.get("NTPGUI_REPLAY", "").strip())


def replay_info_active() -> dict[str, Any] | None:
    if not replay_active():
        return None
    try:
        rep = _replay()
    except ProviderError as exc:
        return {"active": True, "error": str(exc)}
    return {"active": True, "file": os.path.basename(rep.path), "speed": rep.speed,
            "duration": round(rep.duration, 1), "entries": rep.entries,
            "position": round(rep.position() - rep.first_t, 1)}


def _from_replay(kind: str, args: list[str]) -> Result:
    rep = _replay()
    entry = rep.lookup(kind, args) if rep else None
    if entry is None:
        raise ProviderError(f"{kind} {' '.join(args)}: nicht in der Aufzeichnung", reason="replay")
    error = entry.get("error")
    if error:
        raise ProviderError(f"{kind} {' '.join(args)}: {error} (aufgezeichnet)",
                            reason=error if error in ("missing", "timeout") else "failed")
    rc = entry.get("rc", 0)
    return Result(rc if isinstance(rc, int) else 0, str(entry.get("out", "")), str(entry.get("err", "")))


# ---------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------

def call(kind: str, args: list[str] | tuple[str, ...], timeout: float = 5.0, *,
         binary_path: str | None = None, prefix: list[str] | None = None) -> Result:
    """Führt einen Provider-Befehl aus und liefert Result (auch bei Rückgabecode ≠ 0).

    prefix: Argumente, die vor args stehen, aber nicht aufgezeichnet werden
    (z. B. „-h <socket>“ bei chronyc – ein lokaler Pfad, für die Wiedergabe egal).
    Wirft ProviderError nur, wenn das Programm fehlt oder die Zeit abläuft.
    """
    if kind not in KINDS:
        raise ValueError(f"unbekannter Provider: {kind}")
    args = [str(a) for a in args]
    if replay_active():
        return _from_replay(kind, args)
    exe = binary_path or binary(kind)
    try:
        proc = subprocess.run([exe, *(prefix or []), *args], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        _record(kind, args, "", error="timeout")
        raise ProviderError(f"{kind} {' '.join(args)} timed out", reason="timeout") from exc
    except OSError as exc:  # Programm fehlt / nicht ausführbar
        _record(kind, args, "", error="missing")
        raise ProviderError(str(exc), reason="missing") from exc
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    _record(kind, args, stdout, rc=proc.returncode, err=stderr.strip()[:2000])
    return Result(proc.returncode, stdout, stderr)


def run(kind: str, args: list[str] | tuple[str, ...], timeout: float = 5.0) -> str:
    """Vertrag: stdout des Befehls; ProviderError bei Fehler oder Rückgabecode ≠ 0.

    Für chronyc wird CHRONYC_HOST (nur Entwicklung/Tests) als „-h“ vorangestellt.
    """
    prefix = None
    if kind == "chronyc":
        host = os.environ.get("CHRONYC_HOST")
        prefix = ["-h", host] if host else None
    result = call(kind, args, timeout, prefix=prefix)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise ProviderError(message or f"{kind} {' '.join(map(str, args))} failed", reason="failed",
                            returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    return result.stdout


# ---------------------------------------------------------------------------
# gpsd
# ---------------------------------------------------------------------------

class _LiveLines:
    def __init__(self, sock: socket.socket, deadline: float, watch: str, session: int):
        self.sock, self.deadline, self.watch, self.session = sock, deadline, watch, session

    def __iter__(self) -> Iterator[str]:
        buffer = b""
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                return
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(8192)
            except socket.timeout:
                return
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                raw, _, buffer = buffer.partition(b"\n")
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                _record("gpsd", [self.watch], line, s=self.session)
                yield line


@contextmanager
def gpsd_lines(host: str, port: int, watch: str, timeout: float = 4.0) -> Iterator[Iterator[str]]:
    """Verbindet sich mit gpsd, sendet den WATCH-Befehl und liefert die JSON-Zeilen
    (als Text, ohne Zeilenende) bis timeout abgelaufen ist oder gpsd schließt.

        with providers.gpsd_lines(host, port, '?WATCH={...}', 4.0) as lines:
            for line in lines: ...

    OSError beim Betreten, wenn gpsd nicht erreichbar ist (auch in der Wiedergabe,
    wenn die Aufzeichnung keine gpsd-Zeilen enthält). Abbruch der Schleife ist
    jederzeit erlaubt.
    """
    watch = watch.strip()
    deadline = time.monotonic() + timeout
    if replay_active():
        try:
            rep = _replay()
        except ProviderError as exc:
            raise ConnectionRefusedError(str(exc)) from exc
        session = rep.gpsd_session(watch) if rep else None
        if not session:
            raise ConnectionRefusedError("gpsd: nicht in der Aufzeichnung")
        yield iter([str(e.get("out", "")) for e in session if e.get("out")])
        return
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.sendall(watch.encode("utf-8") + b"\n")
        yield _LiveLines(sock, deadline, watch, _next_session() if _REC["active"] else 0)
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def replay_info(path: str) -> dict[str, Any]:
    """Überblick über eine Aufzeichnung (für die CLI und die Oberfläche)."""
    rep = Replay(path)
    kinds: dict[str, int] = {}
    for key, (_, items) in rep.commands.items():
        kinds[key[0]] = kinds.get(key[0], 0) + len(items)
    gpsd_sessions = sum(len(s) for s in rep.gpsd.values())
    gpsd_lines_n = sum(len(items) for s in rep.gpsd.values() for _, items in s)
    if gpsd_lines_n:
        kinds["gpsd"] = gpsd_lines_n
    return {
        "file": path,
        "entries": rep.entries,
        "skipped": rep.skipped,
        "first": rep.first_t or None,
        "last": rep.last_t or None,
        "duration": round(rep.duration, 3),
        "kinds": kinds,
        "commands": sorted(" ".join(k) for k in rep.commands),
        "gpsd_sessions": gpsd_sessions,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "replay-info":
        print("Aufruf: python3 app/providers.py replay-info <datei.jsonl>", file=sys.stderr)
        return 2
    try:
        info = replay_info(argv[1])
    except OSError as exc:
        print(f"Datei nicht lesbar: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
