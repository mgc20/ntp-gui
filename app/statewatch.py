"""Zustandswechsel erkennen und als Ereignis festhalten.

Die Messschleife (server.collector) gibt jeden Messpunkt hierher; der
Hardware-Bericht liefert die PPS-Zustände. Ein Ereignis entsteht nur bei einem
WECHSEL, und erst wenn der neue Zustand zweimal hintereinander gemessen wurde –
sonst würde ein einzelner verpasster Messpunkt (chronyc kurz beschäftigt, gpsd
liefert ein leeres TPV) einen „Fix verloren/wieder da“-Doppelpack erzeugen.

Der allererste Zustand nach dem Start ist kein Wechsel: Nach einem Neustart des
Dashboards soll nicht „Quelle gewechselt“ im Protokoll stehen.

Ein Messpunkt ohne Quellenliste heißt „Zustand unbekannt“ (chronyc gescheitert,
chronyd startet gerade neu) – daraus wird KEIN Quellenwechsel. Antwortet chronyd
gar nicht (weder Quellen noch tracking), gibt es ein eigenes Ereignis
„chronyd nicht erreichbar“ – ebenfalls nur beim bestätigten Wechsel.

Ereignisse bleiben lokal (SQLite); was davon ins Diagnosepaket geht, läuft wie
alles andere durch den Datenschutzfilter (egress).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

CONFIRM = 2  # so oft hintereinander muss ein neuer Zustand gemessen werden
# GPS-Fix: Bei schwachem Empfang (Antenne innen) kommt und geht der Fix im Minutentakt. Ein
# Wechsel zählt erst, wenn er so lange anhält – sonst füllt sich das Protokoll mit
# „verloren/wieder da“-Paaren, die nichts aussagen (chrony überbrückt kurze Lücken ohnehin).
GPS_FIX_HOLD = 60.0


class _Tracker:
    """Merkt sich einen bestätigten Zustand und meldet bestätigte Wechsel.

    Bestätigt heißt: confirm-mal hintereinander gemessen UND seit hold Sekunden unverändert."""

    def __init__(self, confirm: int = CONFIRM, hold: float = 0.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.confirm = max(1, confirm)
        self.hold = max(0.0, hold)
        self._clock = clock
        self.state: Any = None
        self.known = False
        self._candidate: Any = None
        self._count = 0
        self._since = 0.0

    def _seen(self, value: Any) -> bool:
        """Kandidat zählen; True, wenn er bestätigt ist."""
        if value == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count, self._since = value, 1, self._clock()
        return self._count >= self.confirm and self._clock() - self._since >= self.hold

    def update(self, value: Any) -> tuple[bool, Any]:
        """Gibt (Wechsel bestätigt, alter Zustand) zurück."""
        if not self.known:
            self._seen(value)
            if self._count >= self.confirm:  # Ausgangszustand: keine Haltezeit, nur bestätigt
                self.state, self.known = value, True
                self._candidate, self._count = None, 0
            return False, None
        if value == self.state:
            self._candidate, self._count = None, 0
            return False, None
        if self._seen(value):
            old = self.state
            self.state = value
            self._candidate, self._count = None, 0
            return True, old
        return False, None


def _selected_source(sample: dict) -> str | None:
    for name, src in (sample.get("sources") or {}).items():
        if isinstance(src, dict) and src.get("s") == "*":
            return str(name)
    return None


_TRACKING_KEYS = ("stratum", "offset", "freq", "root_delay")


def _chronyd_reachable(sample: dict) -> bool:
    """Hat chronyd geantwortet? Quellen ODER tracking-Werte reichen."""
    if sample.get("sources"):
        return True
    return any(sample.get(key) is not None for key in _TRACKING_KEYS)


def _fix(sample: dict) -> bool | None:
    gps = sample.get("gps")
    if not isinstance(gps, dict):
        return None  # GPS aus – kein Zustand
    mode = gps.get("mode")
    return isinstance(mode, (int, float)) and not isinstance(mode, bool) and mode >= 2


class StateWatcher:
    def __init__(self, emit: Callable[..., None], confirm: int = CONFIRM,
                 gps_fix_hold: float | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._emit = emit
        self._confirm = confirm
        self._lock = threading.Lock()
        self._source = _Tracker(confirm)
        self._chronyd = _Tracker(confirm)
        self._fix_hold = GPS_FIX_HOLD if gps_fix_hold is None else gps_fix_hold
        self._clock = clock
        self._fix = self._fix_tracker()
        self._pps: dict[str, _Tracker] = {}
        self._clients: dict[str, dict] = {}
        self._clients_threshold: float | None = None

    def _fix_tracker(self) -> _Tracker:
        return _Tracker(self._confirm, self._fix_hold, self._clock)

    def _send(self, kind: str, level: str, title: str, data: dict | None = None) -> None:
        try:
            self._emit(kind, level, title, data, source="web")
        except Exception:  # Ereignisse sind nie kritisch
            pass

    # --- Messpunkt -----------------------------------------------------------
    def sample(self, sample: dict) -> None:
        if not isinstance(sample, dict):
            return
        with self._lock:
            reachable = _chronyd_reachable(sample)
            changed, _old = self._chronyd.update(reachable)
            if changed and not reachable:
                self._send("service", "warn", "chronyd nicht erreichbar",
                           {"service": "chronyd"})
            elif changed:
                self._send("service", "info", "chronyd wieder erreichbar", {"service": "chronyd"})
            if sample.get("sources"):
                self._source_update(sample)
            # Ohne Quellenliste ist die Auswahl unbekannt: kein Wechsel, Tracker unverändert.
            self._gps_update(sample)

    def _source_update(self, sample: dict) -> None:
        changed, old = self._source.update(_selected_source(sample))
        if changed:
            new = self._source.state
            if new is None:
                self._send("source", "warn", "Keine Zeitquelle mehr ausgewählt",
                           {"from": old})
            elif old is None:
                self._send("source", "info", f"Zeitquelle ausgewählt: {new}", {"to": new})
            else:
                self._send("source", "info", f"Zeitquelle gewechselt: {old} → {new}",
                           {"from": old, "to": new})

    def _gps_update(self, sample: dict) -> None:
        fix = _fix(sample)
        if fix is None:
            # GPS ausgeschaltet: Zustand vergessen, damit Wiedereinschalten kein Ereignis ist.
            self._fix = self._fix_tracker()
        else:
            changed, _old = self._fix.update(fix)
            if changed:
                gps = sample.get("gps") or {}
                data = {"mode": gps.get("mode"), "used": gps.get("used")}
                if fix:
                    self._send("gps", "info", "GPS-Fix wieder da", data)
                else:
                    self._send("gps", "warn", "GPS-Fix verloren", data)

    # --- Hardware-Bericht ----------------------------------------------------
    def hardware(self, report: Any) -> None:
        if not isinstance(report, dict):
            return
        with self._lock:
            seen = set()
            for pps in report.get("pps") or []:
                if not isinstance(pps, dict) or not pps.get("dev"):
                    continue
                dev, state = str(pps["dev"]), pps.get("state")
                seen.add(dev)
                if state == "unknown":
                    continue  # Probe nicht möglich – weder Verlust noch Rückkehr
                tracker = self._pps.setdefault(dev, _Tracker(1))
                changed, old = tracker.update(state == "live")
                if not changed:
                    continue
                if tracker.state:
                    self._send("pps", "info", f"PPS-Impulse wieder da ({dev})", {"device": dev})
                elif old:
                    self._send("pps", "warn", f"PPS-Impulse ausgeblieben ({dev})",
                               {"device": dev, "state": state})
            for dev in list(self._pps):
                if dev not in seen:
                    del self._pps[dev]

    # --- Client-Uhren (Alarm-Schwelle aus den Einstellungen) -------------------
    def clients(self, clients: Any, threshold_ms: Any, label: Callable[[str], str] = str,
                fmt: Callable[[float], str] | None = None) -> None:
        """Meldet Client-Uhren, die um mehr als threshold_ms abweichen.

        Hysterese wie bei den übrigen Zuständen: Ein Alarm entsteht erst, wenn ZWEI neue
        Messungen hintereinander über der Schwelle liegen; „wieder im Rahmen“ erst, wenn zwei
        Messungen unter der HÄLFTE liegen. So pendelt ein Gerät an der Grenze nicht. Gezählt
        wird nur, wenn das Gerät wirklich neu gemessen wurde (Zähler „count“ gestiegen).
        """
        try:
            threshold = float(threshold_ms or 0) / 1000.0
        except (TypeError, ValueError):
            threshold = 0.0
        if not isinstance(clients, dict):
            return
        fmt = fmt or (lambda v: f"{v * 1000:+.1f} ms")
        with self._lock:
            if threshold <= 0:
                self._clients.clear()
                self._clients_threshold = None
                return
            if self._clients_threshold != threshold:
                # Neue Schwelle: Zustände neu aufbauen, aber offene Alarme nicht doppelt melden.
                for state in self._clients.values():
                    state["streak"] = 0
                self._clients_threshold = threshold
            for ip in [ip for ip in self._clients if ip not in clients]:
                del self._clients[ip]
            for ip, entry in clients.items():
                if not isinstance(entry, dict) or not entry.get("measurable"):
                    continue
                value = entry.get("offset")
                count = entry.get("count")
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                state = self._clients.setdefault(ip, {"alarm": False, "streak": 0, "count": None})
                if count == state["count"]:
                    continue  # keine neue Messung
                state["count"] = count
                if not state["alarm"]:
                    over = abs(value) > threshold
                    state["streak"] = state["streak"] + 1 if over else 0
                    if state["streak"] >= CONFIRM:
                        state.update(alarm=True, streak=0)
                        self._send("clients", "warn", f"Uhr von {label(ip)} weicht um {fmt(value)} ab",
                                   {"address": ip, "offset": value, "threshold_ms": threshold * 1000})
                else:
                    back = abs(value) < threshold / 2
                    state["streak"] = state["streak"] + 1 if back else 0
                    if state["streak"] >= CONFIRM:
                        state.update(alarm=False, streak=0)
                        self._send("clients", "info", f"Uhr von {label(ip)} wieder im Rahmen ({fmt(value)})",
                                   {"address": ip, "offset": value, "threshold_ms": threshold * 1000})
            if len(self._clients) > 5000:
                for ip in list(self._clients)[:len(self._clients) - 5000]:
                    del self._clients[ip]
