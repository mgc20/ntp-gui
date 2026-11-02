"""Temperatur des Geräts: Sensoren finden und lesen (1.4: nur messen).

Warum: Der Quarz der Systemuhr ändert seine Frequenz mit der Temperatur
(typisch 0,05–0,5 ppm/K). chrony regelt das mit GPS oder guten NTP-Quellen
weg – im Verlauf sieht man es trotzdem an der Frequenz, und ohne Referenz
(Holdover, reines NTP über schlechte Netze) wird es zum Zeitfehler. 1.4
zeichnet deshalb zu jedem Messpunkt die Temperatur auf; 1.5 kann daraus einen
Vorschlag für chronys `tempcomp` berechnen.

Quellen (alle nur lesend unter NTPGUI_SYS_ROOT, Standard /sys):
  * thermal_zone*/temp + type      – SoC/CPU (Raspberry Pi: cpu-thermal)
  * hwmon*/temp*_input + name      – PC-Sensoren (k10temp, coretemp …)
  * w1/devices/28-*/temperature    – DS18B20 am 1-Wire-Bus (oder w1_slave)
Alle liefern Milligrad Celsius.

Kennungen sind Namen statt Nummern (hwmonN/thermal_zoneN können nach einem
Neustart anders nummeriert sein): „thermal:cpu-thermal“, „hwmon:k10temp:temp1“,
„w1:28-0123456789ab“. Gibt es einen Namen mehrfach, bekommt das zweite
Vorkommen „:2“ usw. angehängt. Die Einstellung temp_sensor wird nur gegen die
gefundenen Kennungen verglichen – nie als Pfad benutzt.

In VMs und Docker Desktop gibt es meist keine Sensoren: dann liefert alles
None bzw. available=False, nie einen Fehler.
"""

from __future__ import annotations

import glob
import os
import re
import threading
import time
from typing import Any

# Reihenfolge für „auto“: zuerst der Chip, der dem Quarz am nächsten ist.
PREFERRED_THERMAL = ("cpu-thermal", "cpu_thermal", "soc-thermal", "soc_thermal", "soc", "x86_pkg_temp")
PREFERRED_HWMON = ("cpu_thermal", "k10temp", "coretemp", "zenpower", "soc_thermal")

MIN_C, MAX_C = -40.0, 125.0
# DS18B20: 85 °C ist der Wert nach dem Einschalten (Messung nicht fertig), −127 heißt „kein Sensor“.
W1_INVALID = (85.0, -127.0)

DISCOVER_TTL = 300.0
_NAME_RE = re.compile(r"[^A-Za-z0-9_.+-]")


def sys_root() -> str:
    return os.environ.get("NTPGUI_SYS_ROOT", "/sys")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(4096).replace("\x00", "").strip()
    except OSError:
        return ""


def _clean_name(text: str, fallback: str) -> str:
    name = _NAME_RE.sub("_", text.strip())[:40]
    return name or fallback


def _plausible(celsius: float | None) -> float | None:
    if celsius is None or not (MIN_C <= celsius <= MAX_C):
        return None
    return round(celsius, 2)


def parse_millidegrees(text: str) -> float | None:
    """'48312' → 48.312 °C; Unsinn → None."""
    try:
        value = int(text.strip())
    except (ValueError, AttributeError):
        return None
    return _plausible(value / 1000.0)


def parse_w1_slave(text: str) -> float | None:
    """Ausgabe von w1_slave (zwei Zeilen, erste endet auf YES, zweite enthält t=…)."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2 or not lines[0].endswith("YES"):
        return None  # Prüfsumme falsch – Wert verwerfen statt raten
    match = re.search(r"t=(-?\d+)$", lines[1])
    return parse_w1_value(match.group(1)) if match else None


def parse_w1_value(text: str) -> float | None:
    value = parse_millidegrees(text)
    if value is None or value in W1_INVALID:
        return None
    return value


def _rank(sensor: dict[str, Any]) -> tuple[int, int, str]:
    kind, name = sensor["kind"], sensor["name"]
    if kind == "thermal" and name in PREFERRED_THERMAL:
        return (0, PREFERRED_THERMAL.index(name), sensor["id"])
    if kind == "hwmon" and name in PREFERRED_HWMON:
        return (1, PREFERRED_HWMON.index(name), sensor["id"])
    if kind == "w1":
        return (2, 0, sensor["id"])
    if kind == "thermal":
        return (3, 0, sensor["id"])
    return (4, 0, sensor["id"])


def _unique(sensors: list[dict[str, Any]]) -> None:
    seen: dict[str, int] = {}
    for sensor in sensors:
        base = sensor["id"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            sensor["id"] = f"{base}:{seen[base]}"


def discover(root: str | None = None) -> list[dict[str, Any]]:
    """Alle lesbaren Temperatursensoren, beste zuerst (Reihenfolge von „auto“)."""
    root = root or sys_root()
    found: list[dict[str, Any]] = []

    zones = sorted(glob.glob(os.path.join(root, "class", "thermal", "thermal_zone*")),
                   key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0))
    thermal = []
    for zone in zones:
        path = os.path.join(zone, "temp")
        celsius = parse_millidegrees(_read(path))
        if celsius is None:
            continue
        name = _clean_name(_read(os.path.join(zone, "type")), os.path.basename(zone))
        thermal.append({"id": f"thermal:{name}", "kind": "thermal", "name": name, "label": name,
                        "path": path, "celsius": celsius})
    _unique(thermal)
    found += thermal

    hwmon = []
    for chip in sorted(glob.glob(os.path.join(root, "class", "hwmon", "hwmon*")),
                       key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
        name = _clean_name(_read(os.path.join(chip, "name")), os.path.basename(chip))
        inputs = sorted(glob.glob(os.path.join(chip, "temp*_input")),
                        key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0))
        for path in inputs:
            celsius = parse_millidegrees(_read(path))
            if celsius is None:
                continue
            channel = os.path.basename(path)[:-len("_input")]
            if not re.fullmatch(r"temp\d{1,2}", channel):
                continue
            label = _read(path[:-len("_input")] + "_label")[:40]
            hwmon.append({"id": f"hwmon:{name}:{channel}", "kind": "hwmon", "name": name,
                          "label": f"{name} {label or channel}", "path": path, "celsius": celsius})
    _unique(hwmon)
    found += hwmon

    for device in sorted(glob.glob(os.path.join(root, "bus", "w1", "devices", "28-*"))):
        serial = os.path.basename(device).lower()
        if not re.fullmatch(r"28-[0-9a-f]{12}", serial):
            continue
        sensor = {"id": f"w1:{serial}", "kind": "w1", "name": "DS18B20", "label": f"DS18B20 ({serial})",
                  "path": os.path.join(device, "temperature"), "celsius": None}
        sensor["celsius"] = read(sensor)
        if sensor["celsius"] is None and not os.path.exists(sensor["path"]):
            sensor["path"] = os.path.join(device, "w1_slave")
            sensor["celsius"] = read(sensor)
        found.append(sensor)  # auch ohne Wert zeigen: dann stimmt die Verkabelung nicht

    found.sort(key=_rank)
    return found


def read(sensor: dict[str, Any] | None) -> float | None:
    """Aktueller Wert eines Sensors aus discover() in °C oder None."""
    if not sensor:
        return None
    path = sensor.get("path") or ""
    if sensor.get("kind") == "w1":
        if path.endswith("w1_slave"):
            return parse_w1_slave(_read(path))
        return parse_w1_value(_read(path))
    return parse_millidegrees(_read(path))


def choose(sensors: list[dict[str, Any]], setting: str | None) -> dict[str, Any] | None:
    """Den eingestellten Sensor wählen: „off“ → None, „auto“/unbekannt → bester mit Wert."""
    setting = (setting or "auto").strip()
    if setting == "off":
        return None
    if setting != "auto":
        for sensor in sensors:
            if sensor["id"] == setting:
                return sensor
        return None  # eingestellter Sensor fehlt (abgesteckt) – nicht still einen anderen nehmen
    for sensor in sensors:
        if sensor.get("celsius") is not None:
            return sensor
    return None


def public(sensor: dict[str, Any] | None) -> dict[str, Any] | None:
    """Sensor für API/Hardware-Check – ohne Pfad und ohne DS18B20-Seriennummer im Namen."""
    if not sensor:
        return None
    out = {k: sensor.get(k) for k in ("id", "kind", "name", "label", "celsius")}
    return out


class Monitor:
    """Merkt sich die Sensorliste (alle DISCOVER_TTL s neu) und liest den gewählten Sensor."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sensors: list[dict[str, Any]] | None = None
        self._time = 0.0
        self.last: dict[str, Any] = {"t": None, "celsius": None}

    def sensors(self, refresh: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            now = time.monotonic()
            if refresh or self._sensors is None or now - self._time > DISCOVER_TTL:
                try:
                    self._sensors = discover()
                except Exception:  # sysfs seltsam – dann eben keine Sensoren
                    self._sensors = []
                self._time = now
            return list(self._sensors)

    def selected(self, setting: str | None) -> dict[str, Any] | None:
        return choose(self.sensors(), setting)

    def sample(self, setting: str | None) -> float | None:
        """Aktuelle Temperatur des gewählten Sensors (für den Messpunkt) oder None."""
        sensor = self.selected(setting)
        value = read(sensor) if sensor else None
        self.last = {"t": time.time(), "celsius": value}
        return value

    def status(self, setting: str | None) -> dict[str, Any]:
        sensors = self.sensors()
        sensor = choose(sensors, setting)
        setting = (setting or "auto").strip()
        reason = None
        if setting == "off":
            reason = "off"
        elif not sensors:
            reason = "none"
        elif sensor is None:
            reason = "missing" if setting != "auto" else "no_value"
        return {
            "available": sensor is not None,
            "setting": setting,
            "reason": reason,
            "sensor": public(sensor),
            "celsius": read(sensor) if sensor else None,
            "candidates": [public(s) for s in sensors],
        }


MONITOR = Monitor()


# ---------------------------------------------------------------------------
# Auswertung für die Seite „Uhrqualität“ (1.4: nur beschreiben, kein Fit)
# ---------------------------------------------------------------------------

READY_DAYS = 3.0      # ab so vielen Tagen Daten …
READY_SPAN_K = 4.0    # … und dieser Temperaturspanne lohnt in 1.5 ein Fit


def pairs_from_samples(samples: list[dict]) -> list[list[float]]:
    """[[t, temp, freq], …] aus Verlaufspunkten, nur wo beides gemessen ist."""
    out = []
    for sample in samples:
        temp, freq, t = sample.get("temp"), sample.get("freq"), sample.get("t")
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (temp, freq, t)):
            out.append([t, round(float(temp), 3), float(freq)])
    return out


def summarize(pairs: list[list[float]]) -> dict[str, Any]:
    """Kennzahlen: Anzahl, Dauer, Spanne, Korrelation und ob die Daten schon reichen."""
    info: dict[str, Any] = {"count": len(pairs), "days": 0.0, "temp_min": None, "temp_max": None,
                            "span_k": 0.0, "freq_min": None, "freq_max": None, "correlation": None,
                            "ready": False, "need_days": READY_DAYS, "need_span_k": READY_SPAN_K}
    if not pairs:
        return info
    times = [p[0] for p in pairs]
    temps = [p[1] for p in pairs]
    freqs = [p[2] for p in pairs]
    info.update(days=round((max(times) - min(times)) / 86400.0, 2),
                temp_min=min(temps), temp_max=max(temps), span_k=round(max(temps) - min(temps), 2),
                freq_min=min(freqs), freq_max=max(freqs))
    n = len(pairs)
    if n >= 10:
        mt, mf = sum(temps) / n, sum(freqs) / n
        st = sum((x - mt) ** 2 for x in temps)
        sf = sum((y - mf) ** 2 for y in freqs)
        if st > 0 and sf > 0:
            cov = sum((x - mt) * (y - mf) for x, y in zip(temps, freqs))
            info["correlation"] = round(cov / (st * sf) ** 0.5, 3)
    info["ready"] = info["days"] >= READY_DAYS and info["span_k"] >= READY_SPAN_K
    return info
