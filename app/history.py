"""Verlauf der Messwerte für die Diagramme – im Speicher, gesichert als .json.gz.

Ein Messpunkt enthält die Systemuhr (tracking), den Offset jeder Quelle, den
Zähler der beantworteten Anfragen sowie GPS- und PTP-Werte. Gesichert wird
stündlich und beim Beenden, komprimiert – so übersteht der Verlauf Neustarts,
ohne die SD-Karte eines Raspberry Pi mit Schreiblast zu belasten.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import threading
import time
from collections import deque
from typing import Any

_NUMERIC_TOP = ("offset", "rms", "freq", "skew", "root_delay", "root_dispersion",
                "stratum", "served", "clients")


class History:
    def __init__(self, size: int, path: str | None = None) -> None:
        self._samples: deque[dict] = deque(maxlen=max(2, size))
        self._lock = threading.Lock()
        self.path = path
        self._last_save = time.time()

    # --- schreiben -----------------------------------------------------------
    def add(self, sample: dict) -> None:
        sample.setdefault("t", int(time.time()))
        with self._lock:
            self._samples.append(sample)

    def resize(self, size: int) -> None:
        with self._lock:
            if self._samples.maxlen != size:
                self._samples = deque(self._samples, maxlen=max(2, size))

    # --- lesen ---------------------------------------------------------------
    def snapshot(self, since: float | None = None) -> list[dict]:
        with self._lock:
            data = list(self._samples)
        if since is not None:
            data = [s for s in data if s.get("t", 0) >= since]
        return data

    def query(self, seconds: float | None = None, points: int = 600) -> list[dict]:
        """Ausschnitt der letzten `seconds` Sekunden, auf höchstens `points` verdichtet."""
        data = self.snapshot()
        if seconds and data:
            cutoff = data[-1]["t"] - seconds
            data = [s for s in data if s["t"] >= cutoff]
        return downsample(data, points)

    # --- sichern -------------------------------------------------------------
    def load(self) -> int:
        if not self.path or not os.path.exists(self.path):
            return 0
        try:
            with gzip.open(self.path, "rt", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, EOFError):
            return 0
        if not isinstance(data, list):
            return 0
        with self._lock:
            for sample in data[-self._samples.maxlen:]:
                if isinstance(sample, dict) and isinstance(sample.get("t"), (int, float)):
                    self._samples.append(sample)
        return len(self._samples)

    def save(self, force: bool = False, every: float = 3600.0) -> bool:
        if not self.path:
            return False
        now = time.time()
        if not force and now - self._last_save < every:
            return False
        data = self.snapshot()
        directory = os.path.dirname(self.path)
        try:
            os.makedirs(directory, mode=0o700, exist_ok=True)
            tmp = self.path + ".tmp"
            with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as handle:
                json.dump(data, handle, separators=(",", ":"))
            os.replace(tmp, self.path)
        except OSError:
            return False
        self._last_save = now
        return True


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)
              and math.isfinite(v)]
    return sum(values) / len(values) if values else None


def downsample(data: list[dict], points: int) -> list[dict]:
    """Mittelt numerische Werte in gleich großen Zeitfenstern; Zustände: letzter Wert."""
    if points <= 0 or len(data) <= points:
        return data
    bucket = math.ceil(len(data) / points)
    out = []
    for start in range(0, len(data), bucket):
        chunk = data[start:start + bucket]
        merged: dict[str, Any] = {"t": chunk[-1]["t"]}
        for key in _NUMERIC_TOP:
            value = _mean([s.get(key) for s in chunk])
            if value is not None:
                merged[key] = value
        # Zählerstände: letzter Wert, nicht Mittel (sonst stimmt die Rate nicht).
        if "served" in chunk[-1]:
            merged["served"] = chunk[-1]["served"]
        sources: dict[str, dict] = {}
        for sample in chunk:
            for name, values in (sample.get("sources") or {}).items():
                sources.setdefault(name, {"o": [], "s": None, "k": None})
                sources[name]["o"].append(values.get("o"))
                sources[name]["s"] = values.get("s", sources[name]["s"])
                sources[name]["k"] = values.get("k", sources[name]["k"])
        if sources:
            merged["sources"] = {name: {"o": _mean(v["o"]), "s": v["s"], "k": v["k"]}
                                 for name, v in sources.items()}
        for group in ("gps", "ptp"):
            keys = {k for s in chunk for k in (s.get(group) or {})}
            if keys:
                merged[group] = {k: _mean([(s.get(group) or {}).get(k) for s in chunk])
                                 for k in keys}
        out.append(merged)
    return out


# ---------------------------------------------------------------------------
# GPS-Kalibrierung
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def calibrate(samples: list[dict], gps_name: str, current_offset: float,
              current_delay: float) -> dict[str, Any]:
    """Vergleicht den GPS-Offset mit den aktiven Netzwerkquellen.

    Alle Offsets sind relativ zur Systemuhr. Die Differenz GPS − Netz ist
    deshalb unabhängig davon, welche Quelle die Uhr gerade regelt, genau die
    Verspätung des GPS. Die Refclock-Option „offset“ verschiebt die GPS-Zeit
    um ihren Wert nach vorn: neuer Offset = aktueller Offset + gemessene
    Differenz.
    """
    diffs, times = [], []
    for sample in samples:
        sources = sample.get("sources") or {}
        gps = sources.get(gps_name)
        if not gps or not isinstance(gps.get("o"), (int, float)):
            continue
        reference = [v.get("o") for name, v in sources.items()
                     if name != gps_name and v.get("s") in {"*", "+"} and v.get("k") != "#"
                     and isinstance(v.get("o"), (int, float))]
        if not reference:
            continue
        diffs.append(gps["o"] - sum(reference) / len(reference))
        times.append(sample["t"])

    result: dict[str, Any] = {
        "samples": len(diffs), "current_offset": current_offset,
        "current_delay": current_delay, "duration_seconds": (times[-1] - times[0]) if times else 0,
    }
    if len(diffs) < 10:
        result.update(status="insufficient",
                      message="Noch zu wenige gemeinsame Messungen. Es braucht GPS-Werte und "
                              "mindestens eine aktive Netzwerkquelle gleichzeitig.")
        return result

    median = _median(diffs)
    # Robuste Streuung: MAD skaliert auf die Standardabweichung einer Normalverteilung.
    mad = _median([abs(d - median) for d in diffs]) * 1.4826
    result.update(
        bias=median, spread=mad,
        suggested_offset=round(current_offset + median, 4),
        # Delay ≈ doppelte Spanne, in der 99 % der Werte liegen, mit Untergrenze für
        # USB-Jitter und Obergrenze beim vorsichtigen Standard.
        suggested_delay=round(min(0.2, max(0.005, 6 * mad)), 3),
        series=[{"t": t, "d": d} for t, d in zip(times[-600:], diffs[-600:])],
    )
    if result["duration_seconds"] < 1800:
        result.update(status="preliminary",
                      message="Vorläufiger Wert. Für einen belastbaren Offset mindestens 30 "
                              "Minuten, besser einige Stunden messen lassen.")
    elif abs(median) < max(0.5 * mad, 0.0005):
        result.update(status="calibrated",
                      message="Das GPS ist bereits gut kalibriert – die Abweichung liegt im "
                              "Rauschen.")
    else:
        result.update(status="ready",
                      message="Genug Messungen für einen belastbaren Vorschlag.")
    return result
