"""Zufällige Kennung dieser Instanz.

Eine UUID4, beim ersten Start erzeugt und in DATA_DIR/instance-id gespeichert.
Sie ist bewusst NICHT aus der Hardware abgeleitet (keine MAC-Adresse,
Seriennummer oder Maschinen-ID): Sie verrät nichts über das Gerät, und mit
rotate() lässt sich jederzeit eine neue ziehen – dann ist die Instanz für
spätere, freiwillige Gemeinschaftsfunktionen nicht mehr mit früheren Daten
verknüpfbar. Sie wird nur unter /api/v1/instance angezeigt und verlässt die
Instanz nie von selbst.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import uuid

import settings

FILE_NAME = "instance-id"
_LOCK = threading.Lock()
_MEMORY: dict[str, str] = {}  # nur, wenn DATA_DIR nicht schreibbar ist


def _path() -> str:
    return os.path.join(settings.DATA_DIR, FILE_NAME)


def _valid(text: str) -> bool:
    try:
        return str(uuid.UUID(text)) == text and uuid.UUID(text).version == 4
    except (ValueError, TypeError):
        return False


def _write(value: str) -> None:
    directory = os.path.dirname(_path())
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".instance-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, _path())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def get() -> str:
    """Die Kennung; beim ersten Aufruf erzeugt. Ohne schreibbares Volume: nur für diesen Lauf."""
    with _LOCK:
        try:
            with open(_path(), encoding="utf-8") as handle:
                value = handle.read().strip()
            if _valid(value):
                return value
        except OSError:
            pass
        if _MEMORY.get("id"):
            return _MEMORY["id"]
        value = str(uuid.uuid4())
        try:
            _write(value)
        except OSError:
            _MEMORY["id"] = _MEMORY.get("id") or value
            return _MEMORY["id"]
        return value


def rotate() -> str:
    """Zieht eine neue Kennung. Die alte ist danach nirgends mehr gespeichert."""
    with _LOCK:
        value = str(uuid.uuid4())
        try:
            _write(value)
        except OSError:
            _MEMORY["id"] = value
    try:
        import events
        events.emit("settings", "info", "Instanz-Kennung neu erzeugt", None)
    except Exception:
        pass
    return value


def info() -> dict:
    """Für /api/v1/instance."""
    created = None
    try:
        created = int(os.stat(_path()).st_mtime)
    except OSError:
        pass
    value = get()
    if created is None:
        created = int(time.time())
    return {"instance_id": value, "since": created,
            "note": "Zufällige Kennung, nicht aus der Hardware abgeleitet. Sie verlässt die "
                    "Instanz nie von selbst und lässt sich jederzeit neu erzeugen."}
