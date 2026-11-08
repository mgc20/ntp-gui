"""Pi-Zustand: Unterspannung, Takt-Drosselung, Takt und Lüfter (1.6, T4) – nur lesen.

Warum: Ein Raspberry Pi mit schwachem Netzteil fällt kurzzeitig unter 4,63 V
(Unterspannung) und drosselt dann den Takt; bei Hitze ebenso. Beides ändert die
Last und die Temperatur am Quarz und erklärt Sprünge in Frequenz und Offset, die
man sonst nirgends sieht. Gelesen wird nur aus sysfs – kein vcgencmd (bräuchte
/dev/vchiq), keine neue Capability, kein neues Volume.

Quellen (jede optional, alle unter NTPGUI_SYS_ROOT, Standard /sys):
  * devices/platform/soc/soc:firmware/get_throttled – Bitfeld der Firmware, so wie
    „vcgencmd get_throttled“ es liefert. Das Attribut stammt aus dem Kernel der
    Raspberry-Pi-Foundation (drivers/firmware/raspberrypi.c, „get_throttled“,
    Ausgabe hexadezimal ohne „0x“, z. B. „50005“); der Mainline-Kernel hat es
    nicht. Nach bestem Wissen ist das der Pfad auf Pi 3/4 – auf dem Pi 5 hängt
    der Firmware-Knoten womöglich anders im Baum, deshalb wird zusätzlich unter
    devices/platform/*firmware und devices/platform/*/*firmware gesucht
    (UNSICHER: der genaue Pfad auf dem Pi 5 ist nicht nachgeprüft).
    Bits: 0 Unterspannung jetzt, 1 Takt gedeckelt jetzt, 2 gedrosselt jetzt,
    3 weiche Temperaturgrenze jetzt; 16–19 dasselbe „seit dem Start des Pi“.
  * class/hwmon/hwmon*/ mit name „rpi_volt“: in0_lcrit_alarm = 1 heißt
    Unterspannung jetzt (Treiber raspberrypi-hwmon, auch im Mainline-Kernel).
  * class/hwmon/hwmon*/fan1_input – Lüfterdrehzahl in U/min (Pi 5: „pwmfan“).
  * devices/system/cpu/cpu0/cpufreq/scaling_cur_freq und scaling_max_freq (kHz).

Die Karte „Pi-Zustand“ erscheint nur, wenn eine Pi-eigene Quelle da ist
(get_throttled oder rpi_volt). Auf einem PC gibt es Lüfter und cpufreq auch –
dort bleibt die Karte trotzdem weg: kein „unbekannt“-Rauschen auf x86.

Ereignisse (Art „pi“): „Unterspannung erkannt“ und „Takt gedrosselt“ – genau
eines je Übergang. Entprellt wird über QUIET_SECONDS: erst wenn das Bit so lange
aus war, endet die Episode („… vorbei“, info) und ein neues Auftreten zählt
wieder. Ist beim Start des Dashboards nur das „seit Start“-Bit gesetzt, gibt es
kein Ereignis (das war vor uns – die Karte zeigt es trotzdem). Fällt die
Spannung zwischen zwei Messpunkten kurz ab, merkt man das am neu gesetzten
„seit Start“-Bit; das zählt als Auftreten.

Verlauf: Ein Feld „pi_state“ je Messpunkt (0 = alles gut, 1 = gedrosselt oder
Takt gedeckelt, 2 = Unterspannung), nur wenn die Quelle da ist.
"""

from __future__ import annotations

import glob
import os
import re
import threading
import time
from typing import Any, Callable

UV_NOW, CAPPED_NOW, THROTTLED_NOW, SOFT_TEMP_NOW = 0x1, 0x2, 0x4, 0x8
UV_SINCE, CAPPED_SINCE, THROTTLED_SINCE, SOFT_TEMP_SINCE = 0x10000, 0x20000, 0x40000, 0x80000
FLAGS = {  # Schlüssel: (Bit jetzt, Bit seit Start)
    "undervoltage": (UV_NOW, UV_SINCE),
    "capped": (CAPPED_NOW, CAPPED_SINCE),
    "throttled": (THROTTLED_NOW, THROTTLED_SINCE),
    "soft_temp_limit": (SOFT_TEMP_NOW, SOFT_TEMP_SINCE),
}
LABELS = {"undervoltage": "Unterspannung", "capped": "Takt gedeckelt", "throttled": "Gedrosselt",
          "soft_temp_limit": "Temperaturgrenze"}

QUIET_SECONDS = 600.0      # so lange muss ein Bit aus sein, bis ein neues Auftreten wieder zählt
METRIC_MAX_AGE = 900.0     # Metriken nur aus einem frischen Messpunkt
FAN_NAMES = ("pwmfan", "cooling_fan", "rpi_fan")
THROTTLED_PATH = ("devices", "platform", "soc", "soc:firmware", "get_throttled")
THROTTLED_GLOBS = (("devices", "platform", "*firmware", "get_throttled"),
                   ("devices", "platform", "*", "*firmware", "get_throttled"))
POWER_HINT = ("Am zuverlässigsten ist das offizielle Netzteil (Pi 5: 27 W USB-C, 5,1 V/5 A; Pi 4: "
              "15 W USB-C, 5,1 V/3 A) mit kurzem, dickem Kabel – USB-Ladegeräte und dünne Kabel "
              "liefern unter Last oft zu wenig.")

EVENTS = {
    "undervoltage": ("Unterspannung erkannt", "Unterspannung vorbei"),
    "throttled": ("Takt gedrosselt", "Takt wieder frei"),
}


def sys_root() -> str:
    try:
        import devices
        return devices.sys_root()
    except Exception:  # pragma: no cover – devices fehlt nie, aber pistate soll allein lauffähig sein
        return os.environ.get("NTPGUI_SYS_ROOT", "/sys")


def _read(path: str) -> str | None:
    """Dateiinhalt oder None, wenn es die Datei nicht gibt oder sie nicht lesbar ist."""
    try:
        with open(path, encoding="ascii", errors="replace") as handle:
            return handle.read(256).replace("\x00", "").strip()
    except OSError:
        return None


def _int(text: str | None, base: int = 10) -> int | None:
    if text is None:
        return None
    try:
        value = int(text.strip(), base)
    except (ValueError, AttributeError):
        return None
    return value if value >= 0 else None


def parse_throttled(text: str | None) -> int | None:
    """„50005“ oder „0x50005“ → 0x50005; Unsinn → None. Die Firmware schreibt hexadezimal."""
    if text is None:
        return None
    text = text.strip().lower()
    if text.startswith("throttled="):  # Ausgabe von vcgencmd, falls jemand sie einspielt
        text = text.split("=", 1)[1]
    if not re.fullmatch(r"(0x)?[0-9a-f]{1,8}", text):
        return None
    return int(text, 16)


def decode(bits: int | None) -> dict[str, dict[str, bool | None]]:
    """Bitfeld → {flag: {"now": bool, "since_boot": bool}}; ohne Bitfeld alles None."""
    out = {}
    for key, (now_bit, since_bit) in FLAGS.items():
        if bits is None:
            out[key] = {"now": None, "since_boot": None}
        else:
            out[key] = {"now": bool(bits & now_bit), "since_boot": bool(bits & since_bit)}
    return out


def _throttled_file(root: str) -> str | None:
    path = os.path.join(root, *THROTTLED_PATH)
    if os.path.isfile(path):
        return path
    for pattern in THROTTLED_GLOBS:
        for candidate in sorted(glob.glob(os.path.join(root, *pattern))):
            if os.path.isfile(candidate):
                return candidate
    return None


def _hwmons(root: str) -> list[tuple[str, str]]:
    chips = glob.glob(os.path.join(root, "class", "hwmon", "hwmon*"))
    chips.sort(key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0))
    return [(chip, (_read(os.path.join(chip, "name")) or "")[:40]) for chip in chips]


def read(root: str | None = None) -> dict[str, Any]:
    """Liest alle Quellen einmal. Wirft nie; fehlende Dateien heißen „Quelle fehlt“, nicht Fehler."""
    root = root or sys_root()
    state: dict[str, Any] = {"available": False, "sources": [], "bits": None,
                             "freq_mhz": None, "freq_max_mhz": None, "fan_rpm": None}
    bits = None
    path = _throttled_file(root)
    if path:
        bits = parse_throttled(_read(path))
        if bits is not None:
            state["sources"].append("get_throttled")
            state["bits"] = bits
    flags = decode(bits)
    chips = _hwmons(root)
    for chip, name in chips:
        if name != "rpi_volt":
            continue
        alarm = _int(_read(os.path.join(chip, "in0_lcrit_alarm")))
        if alarm is None:
            continue
        state["sources"].append("rpi_volt")
        if flags["undervoltage"]["now"] is None:
            flags["undervoltage"]["now"] = bool(alarm)
        else:  # beide Quellen da: was eine sieht, gilt
            flags["undervoltage"]["now"] = flags["undervoltage"]["now"] or bool(alarm)
        break
    state.update(flags)
    fans = [(chip, name) for chip, name in chips if os.path.isfile(os.path.join(chip, "fan1_input"))]
    fans.sort(key=lambda item: 0 if item[1] in FAN_NAMES else 1)
    for chip, _name in fans:
        rpm = _int(_read(os.path.join(chip, "fan1_input")))
        if rpm is not None and rpm < 100_000:
            state["fan_rpm"] = rpm
            break
    cpufreq = os.path.join(root, "devices", "system", "cpu", "cpu0", "cpufreq")
    cur = _int(_read(os.path.join(cpufreq, "scaling_cur_freq")))
    top = _int(_read(os.path.join(cpufreq, "scaling_max_freq")))
    state["freq_mhz"] = round(cur / 1000) if cur else None
    state["freq_max_mhz"] = round(top / 1000) if top else None
    state["available"] = bool(state["sources"])
    return state


def flag_text(entry: dict | None) -> str | None:
    """„jetzt und seit Start“, „jetzt“, „seit Start (jetzt nicht)“, „nein“ – None ohne Wert."""
    if not entry or entry.get("now") is None:
        return None
    now, since = entry.get("now"), entry.get("since_boot")
    if now and since:
        return "jetzt und seit Start"
    if now:
        return "jetzt"
    if since:
        return "seit Start (jetzt nicht)"
    return "nein"


def summary(state: dict | None) -> str | None:
    """Ein Satz für Hardware-Check und Diagnose, z. B. „Unterspannung jetzt und seit Start“."""
    if not state or not state.get("available"):
        return None
    parts = []
    for key in ("undervoltage", "throttled", "capped", "soft_temp_limit"):
        text = flag_text(state.get(key))
        if text and text != "nein":
            parts.append(f"{LABELS[key]} {text}")
    return "; ".join(parts) if parts else "Keine Unterspannung, keine Drosselung"


def severity(state: dict | None) -> int | None:
    """Wert für den Verlauf: 0 alles gut, 1 gedrosselt/gedeckelt, 2 Unterspannung – None ohne Quelle."""
    if not state or not state.get("available"):
        return None
    if (state.get("undervoltage") or {}).get("now"):
        return 2
    if any((state.get(k) or {}).get("now") for k in ("throttled", "capped")):
        return 1
    return 0


class Monitor:
    """Merkt sich den letzten Zustand (für Metriken) und entprellt die Ereignisse."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self.clock = clock
        self.last: dict[str, Any] = {"t": None, "state": None}
        self._prev: dict[str, Any] | None = None
        self._active: dict[str, bool] = {k: False for k in EVENTS}
        self._last_on: dict[str, float] = {}
        self._seen: dict[str, bool] = {k: False for k in EVENTS}

    def reset(self) -> None:
        with self._lock:
            self.last = {"t": None, "state": None}
            self._prev = None
            self._active = {k: False for k in EVENTS}
            self._last_on = {}
            self._seen = {k: False for k in EVENTS}

    def _fill_since(self, state: dict) -> None:
        # Nur rpi_volt (kein Bitfeld): „seit Start“ = seit Start des Dashboards gesehen, sonst unbekannt.
        entry = state.get("undervoltage") or {}
        if entry.get("now") is not None and entry.get("since_boot") is None:
            entry["since_boot"] = True if (entry["now"] or self._seen["undervoltage"]) else None

    def current(self, root: str | None = None) -> dict[str, Any]:
        """Frisch gelesener Zustand für Karte und Hardware-Check (ohne Ereignisse)."""
        try:
            state = read(root)
        except Exception:  # sysfs seltsam – dann eben keine Karte
            return {"available": False, "sources": []}
        with self._lock:
            self._fill_since(state)
        state["summary"] = summary(state)
        return state

    def sample(self, emit: Callable[..., Any] | None = None, root: str | None = None) -> dict[str, Any]:
        """Für den Messpunkt: lesen, Ereignisse entprellen, Zustand merken. Wirft nie."""
        try:
            state = read(root)
        except Exception:
            state = {"available": False, "sources": []}
        pending = []
        with self._lock:
            now = self.clock()
            if state.get("available"):
                pending = self._update(state, now)
                self._fill_since(state)
            self.last = {"t": time.time(), "state": state}
        for args in pending:
            if emit is not None:
                try:
                    emit(*args)
                except Exception:  # Protokoll kaputt – die Messung läuft weiter
                    pass
        return state

    def _still_open(self, key: str) -> bool:
        """Ist das jüngste pi-Ereignis zu ``key`` im gespeicherten Protokoll ein „erkannt“ ohne
        folgendes „vorbei“? (Das Protokoll überlebt Neustarts, der Speicher hier nicht.)"""
        try:
            import events
            rows = events.query(kinds=["pi"], limit=50)
        except Exception:
            return False
        for row in rows:  # neueste zuerst
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            if data.get("subject") == key:
                return row.get("title") == EVENTS[key][0]
        return False

    def _update(self, state: dict, now: float) -> list[tuple]:
        """Aufruf unter self._lock. Liefert die zu schreibenden Ereignisse."""
        out = []
        prev = self._prev
        for key, (on_title, off_title) in EVENTS.items():
            entry = state.get(key) or {}
            if entry.get("now") is None:
                continue
            was = (prev or {}).get(key) or {}
            fresh_since = bool(entry.get("since_boot")) and was.get("since_boot") is False
            happened = bool(entry["now"]) or fresh_since
            if entry["now"]:
                self._seen[key] = True
            if happened:
                self._last_on[key] = now
                if prev is None and self._still_open(key):
                    # Erster Messpunkt nach einem Neustart des Dashboards, und das letzte „erkannt“
                    # im Protokoll ist noch offen: dieselbe Episode – kein zweites Ereignis samt
                    # Benachrichtigung.
                    self._active[key] = True
                elif not self._active[key]:
                    self._active[key] = True
                    level = "warn"
                    data = {"subject": key, "now": bool(entry["now"]),
                            "since_boot": entry.get("since_boot"), "bits": state.get("bits"),
                            "freq_mhz": state.get("freq_mhz")}
                    if key == "undervoltage":
                        data["hint"] = POWER_HINT
                    out.append(("pi", level, on_title, data))
            elif self._active[key] and now - self._last_on.get(key, now) >= QUIET_SECONDS:
                self._active[key] = False
                out.append(("pi", "info", off_title, {"subject": key, "quiet_s": int(QUIET_SECONDS)}))
        self._prev = {k: dict(state.get(k) or {}) for k in EVENTS}
        return out

    def metrics_state(self) -> dict[str, Any] | None:
        """Der zuletzt im Messpunkt gelesene Zustand, wenn frisch und vorhanden – sonst None."""
        last = self.last
        state = last.get("state")
        if not isinstance(last.get("t"), (int, float)) or time.time() - last["t"] > METRIC_MAX_AGE:
            return None
        if not isinstance(state, dict) or not state.get("available"):
            return None
        return state


MONITOR = Monitor()
