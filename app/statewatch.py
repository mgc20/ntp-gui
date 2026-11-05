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
from collections import deque
from typing import Any, Callable

CONFIRM = 2  # so oft hintereinander muss ein neuer Zustand gemessen werden
# GPS-Fix: Bei schwachem Empfang (Antenne innen) kommt und geht der Fix im Minutentakt. Ein
# Wechsel zählt erst, wenn er so lange anhält – sonst füllt sich das Protokoll mit
# „verloren/wieder da“-Paaren, die nichts aussagen (chrony überbrückt kurze Lücken ohnehin).
GPS_FIX_HOLD = 60.0
# 1.5: Flattert der Fix trotzdem (VK-162 drinnen: verloren/wieder da alle paar Minuten), wird
# daraus EIN Zustand „unstet“ statt Dutzender Paare. Gezählt werden schnelle Wechsel (zwei
# Messpunkte in Folge, ohne Haltezeit). So viele im Fenster → „unstet“; so lange ohne Wechsel →
# wieder „stetig“ (ein Abschlussereignis mit der Zahl der Wechsel).
GPS_FLAP_WINDOW = 1800.0
GPS_FLAP_ENTER = 6
GPS_FLAP_CALM = 3600.0
# Während „unstet“: Bleibt der Fix so lange am Stück weg, endet die Episode (still – was dann
# zählt, entscheidet GPS_LONG_LOST).
GPS_UNSTET_LOST = 10 * GPS_FIX_HOLD
# 1.5.4: Schwacher Empfang (Episode „unstet“, oder die 24-h-Empfangsbewertung sagt „Fix kommt und
# geht“) wird für GPS_WEAK_MEMORY seit dem letzten Fix-Wechsel gemerkt. So lange gibt es keine
# Einzelmeldungen „verloren/wieder da“, sondern höchstens EINE Info-Zeile je Stunde
# („GPS-Fix 7-mal verloren in der letzten Stunde, zusammen 23 min ohne Fix“). Eine Warnung gibt es
# nur, wenn der Fix GPS_LONG_LOST am Stück fehlt UND das GPS gerade gebraucht wird (keine
# brauchbare Netzquelle, GPS/PPS ausgewählt oder PPS eingerichtet) – sonst eine stille Info.
GPS_WEAK_MEMORY = 24 * 3600.0
GPS_SUMMARY_INTERVAL = 3600.0
GPS_SUMMARY_MAX = 6 * 3600.0   # flattert es Stunde um Stunde weiter, verdoppelt sich das Fenster bis 6 h
GPS_LONG_LOST = 3600.0
GPS_GAP_MAX = 300.0     # größere Lücken zwischen Messpunkten zählen nicht als Zeit ohne Fix


def _fmt_span(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min"
    hours, rest = divmod(seconds, 3600)
    return f"{hours} h {rest // 60} min" if rest >= 60 else f"{hours} h"


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


def gps_matters(sample: dict) -> bool:
    """Braucht chrony das GPS gerade? Ja, wenn eine Refclock (GPS/PPS) ausgewählt ist, eine
    PPS-Refclock eingerichtet ist oder keine Netzquelle brauchbar („*“/„+“) ist."""
    net_ok = False
    for name, src in (sample.get("sources") or {}).items():
        if not isinstance(src, dict):
            continue
        state = src.get("s")
        if src.get("k") == "#":
            if state == "*" or "PPS" in str(name).upper():
                return True
        elif state in ("*", "+"):
            net_ok = True
    return not net_ok


def _extra(data_for: Callable[[str], dict] | None, ip: str) -> dict:
    if data_for is None:
        return {}
    try:
        extra = data_for(ip)
    except Exception:  # Zusatzdaten sind nie kritisch
        return {}
    return {k: v for k, v in (extra or {}).items() if k not in ("address", "offset", "threshold_ms")}


class StateWatcher:
    def __init__(self, emit: Callable[..., None], confirm: int = CONFIRM,
                 gps_fix_hold: float | None = None, clock: Callable[[], float] = time.monotonic,
                 flap_window: float | None = None, flap_enter: int | None = None,
                 flap_calm: float | None = None, wall: Callable[[], float] = time.time,
                 unstet_lost: float | None = None, weak_reception: Callable[[], bool] | None = None,
                 summary_interval: float | None = None, long_lost: float | None = None,
                 weak_memory: float | None = None) -> None:
        self._emit = emit
        self._confirm = confirm
        self._lock = threading.Lock()
        self._source = _Tracker(confirm)
        self._chronyd = _Tracker(confirm)
        self._fix_hold = GPS_FIX_HOLD if gps_fix_hold is None else gps_fix_hold
        self._clock = clock
        self._fix = self._fix_tracker()
        self._wall = wall
        self._flap_window = GPS_FLAP_WINDOW if flap_window is None else flap_window
        self._flap_enter = GPS_FLAP_ENTER if flap_enter is None else max(2, int(flap_enter))
        self._flap_calm = GPS_FLAP_CALM if flap_calm is None else flap_calm
        self._unstet_lost = GPS_UNSTET_LOST if unstet_lost is None else unstet_lost
        self._weak_reception = weak_reception
        self._summary_interval = GPS_SUMMARY_INTERVAL if summary_interval is None else summary_interval
        self._summary_max = max(self._summary_interval, GPS_SUMMARY_MAX * self._summary_interval / GPS_SUMMARY_INTERVAL)
        self._long_lost = GPS_LONG_LOST if long_lost is None else long_lost
        self._weak_memory = GPS_WEAK_MEMORY if weak_memory is None else weak_memory
        self._flap_reset()
        self._pps: dict[str, _Tracker] = {}
        self._clients: dict[str, dict] = {}
        self._clients_threshold: float | None = None

    def _fix_tracker(self) -> _Tracker:
        return _Tracker(self._confirm, self._fix_hold, self._clock)

    def _flap_reset(self) -> None:
        self._fix_fast = _Tracker(self._confirm, 0.0, self._clock)
        self._flaps: deque = deque()
        self._unstet = False
        self._unstet_since: float | None = None      # monotonic
        self._unstet_since_wall: float | None = None
        self._unstet_changes = 0
        self._unstet_announced = False                # Beginn der Episode wurde gemeldet
        self._last_flap: float | None = None
        self._weak_last: float | None = None          # schwacher Empfang zuletzt gesehen (monotonic)
        self._last_t: float | None = None             # letzter Messpunkt (Zeit ohne Fix aufsummieren)
        self._last_fix_t: float | None = None         # zuletzt mit (schnell bestätigtem) Fix
        self._lost_since: float | None = None         # Fix (schnell bestätigt) weg seit
        self._loss_reported = False                   # Verlust wurde einzeln gemeldet („GPS-Fix verloren“)
        self._long_level: str | None = None           # Meldung „seit 1 h ohne Fix“ gesendet (Stufe)
        self._sum_start: float | None = None          # Stundenzusammenfassung: Beginn des Fensters
        self._sum_losses = 0
        self._sum_nofix = 0.0
        self._sum_window = getattr(self, "_summary_interval", GPS_SUMMARY_INTERVAL)

    def _send(self, kind: str, level: str, title: str, data: dict | None = None) -> None:
        try:
            self._emit(kind, level, title, data, source="web")
        except Exception:  # Ereignisse sind nie kritisch
            pass

    def _close_client(self, ip: str, why: str) -> None:
        """Offenen Client-Alarm still schließen (nur Protokoll; notify-Router schließt den Betreff)."""
        state = self._clients.get(ip)
        if not state or not state.get("alarm"):
            return
        state["alarm"] = False
        self._send("clients", "info", f"Alarm für {ip} beendet – {why}",
                   {"address": ip, "resolves": True, "notify": False, "reason": why})

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
            if self._unstet:  # die offene Episode „unstet“ sauber beenden
                self._send("gps", "info",
                           f"GPS ausgeschaltet – Empfang war unstet ({self._unstet_changes} Fix-Wechsel)",
                           {"state": "aus", "changes": self._unstet_changes, "notify": False})
            self._fix = self._fix_tracker()
            self._flap_reset()
            return
        gps = sample.get("gps") or {}
        data = {"mode": gps.get("mode"), "used": gps.get("used")}
        now = self._clock()
        self._flap_update(fix, data, now)
        self._outage_update(sample, data, now)
        self._summary_update(now)
        changed, _old = self._fix.update(fix)
        if not changed:
            return
        if fix:
            # „wieder da“ gehört zu einem einzeln gemeldeten „verloren“ – auch bei schwachem Empfang,
            # sonst bliebe das Problem in den Benachrichtigungen offen.
            if self._loss_reported:
                self._loss_reported = False
                self._send("gps", "info", "GPS-Fix wieder da", data)
            return
        if self._unstet or self._weak(now, ask=True):
            return  # schwacher Empfang: keine Einzelmeldungen, höchstens eine Zeile je Stunde (_summary_update)
        self._send("gps", "warn", "GPS-Fix verloren", data)
        self._loss_reported = True

    def _weak(self, now: float, ask: bool = False) -> bool:
        """Schwacher Empfang: Episode „unstet“, in den letzten 24 h gesehen oder (ask) laut 24-h-Bewertung."""
        if self._unstet:
            return True
        if self._weak_last is not None and now - self._weak_last < self._weak_memory:
            return True
        if ask and self._weak_reception is not None:
            try:
                weak = bool(self._weak_reception())
            except Exception:  # Bewertung nie kritisch
                weak = False
            if weak:
                self._weak_last = now
                return True
        return False

    def _flap_update(self, fix: bool, data: dict, now: float) -> None:
        changed, _old = self._fix_fast.update(fix)
        if changed:
            self._flaps.append(now)
            self._last_flap = now
            if self._unstet:
                self._unstet_changes += 1
            if self._weak(now, ask=not fix):   # bei einem Verlust auch die 24-h-Bewertung fragen
                self._weak_last = now
            if not fix:
                self._sum_losses += 1
        while self._flaps and now - self._flaps[0] > self._flap_window:
            self._flaps.popleft()
        if not self._unstet:
            if len(self._flaps) >= self._flap_enter:
                fresh = not self._weak(now)
                self._unstet = True
                self._weak_last = now
                self._unstet_since, self._unstet_since_wall = now, self._wall()
                self._unstet_changes = len(self._flaps)
                self._unstet_announced = fresh
                if fresh:  # ab 1.5.4 nur Info – und nur, wenn der schwache Empfang neu ist
                    minutes = max(1, round(self._flap_window / 60))
                    self._send("gps", "info",
                               f"GPS-Empfang unstet: Fix kam und ging {len(self._flaps)}-mal in {minutes} min",
                               dict(data, state="unstet", changes=len(self._flaps), window_s=self._flap_window,
                                    notify=False, resolves=False))
            return
        calm = self._last_flap is not None and now - self._last_flap >= self._flap_calm
        lost = (self._last_flap is not None and self._fix_fast.state is False
                and now - self._last_flap >= self._unstet_lost)
        if calm and self._fix_fast.state and self._unstet_announced:
            duration = max(0.0, (self._last_flap - self._unstet_since) if self._unstet_since is not None else 0.0)
            count = self._unstet_changes
            quiet = _fmt_span(now - self._last_flap)
            info = dict(data, state="stetig", changes=count, duration_s=round(duration), fix=True,
                        outcome="ruhig", quiet_s=round(now - self._last_flap), notify=False, resolves=False)
            self._send("gps", "info", f"GPS-Empfang wieder stetig – seit {quiet} kein Fix-Wechsel "
                                      f"(vorher {count} Fix-Wechsel in {_fmt_span(duration)})", info)
        if calm or lost:
            # Fix dauerhaft weg: Episode still beenden – ob das eine Meldung wert ist, entscheidet
            # _outage_update (erst nach GPS_LONG_LOST und nur, wenn das GPS gebraucht wird).
            self._unstet = False
            self._unstet_since = self._unstet_since_wall = None
            self._unstet_changes = 0
            self._flaps.clear()

    def _outage_update(self, sample: dict, data: dict, now: float) -> None:
        """Zeit ohne Fix aufsummieren; lange Ausfälle bei schwachem Empfang einmal melden."""
        state = self._fix_fast.state if self._fix_fast.known else None
        if self._last_t is not None and state is False:
            dt = now - self._last_t
            if 0 < dt <= GPS_GAP_MAX:
                self._sum_nofix += dt
        self._last_t = now
        if state:
            self._last_fix_t = now
        if state is False:
            if self._lost_since is None:
                self._lost_since = now
            if (self._long_level is None and not self._loss_reported
                    and now - self._lost_since >= self._long_lost):
                span = _fmt_span(now - self._lost_since)
                info = dict(data, outcome="fix_weg", lost_s=round(now - self._lost_since))
                if gps_matters(sample):
                    self._long_level = "warn"
                    self._send("gps", "warn", f"GPS seit {span} ohne Fix – und gerade gebraucht "
                                              "(keine brauchbare Netzquelle oder GPS/PPS ausgewählt)", info)
                else:
                    self._long_level = "info"
                    self._send("gps", "info", f"GPS seit {span} ohne Fix – die Netzquellen tragen die Zeit, "
                                              "das GPS ist nur Rückfallebene", dict(info, notify=False, resolves=False))
            return
        if state and self._lost_since is not None:
            if self._long_level is not None:
                span = _fmt_span(now - self._lost_since)
                extra = {} if self._long_level == "warn" else {"notify": False}
                self._send("gps", "info", f"GPS-Fix wieder da nach {span} ohne Fix",
                           dict(data, lost_s=round(now - self._lost_since), **extra))
            self._lost_since = None
            self._long_level = None

    def _summary_update(self, now: float) -> None:
        """Bei schwachem Empfang: eine Info-Zeile je Fenster statt Einzelmeldungen. Das Fenster ist
        1 h; flattert es weiter, verdoppelt es sich bis 6 h (höchstens rund 6 Zeilen am Tag), nach
        einem ruhigen Fenster beginnt es wieder bei 1 h."""
        if not self._weak(now):
            self._sum_start = None
            self._sum_losses, self._sum_nofix = 0, 0.0
            self._sum_window = self._summary_interval
            return
        if self._sum_start is None:   # Fenster beginnt mit dem schwachen Empfang (Zähler: nur dieser Messpunkt)
            self._sum_start = now
            return
        if now - self._sum_start < self._sum_window:
            return
        if self._sum_losses > 0:
            window = now - self._sum_start
            when = ("in der letzten Stunde" if window < 1.1 * GPS_SUMMARY_INTERVAL
                    else f"in den letzten {_fmt_span(window)}")
            nofix = self._sum_nofix
            gone = "unter 1 min" if nofix < 60 else _fmt_span(nofix)
            self._send("gps", "info",
                       f"GPS-Fix {self._sum_losses}-mal verloren {when}, zusammen {gone} ohne Fix",
                       {"state": "schwach", "losses": self._sum_losses, "nofix_s": round(nofix),
                        "window_s": round(window), "notify": False, "resolves": False})
            self._sum_window = min(self._summary_max, self._sum_window * 2)
        else:
            self._sum_window = self._summary_interval
        self._sum_start = now
        self._sum_losses, self._sum_nofix = 0, 0.0

    def gps_stability(self) -> dict:
        """Zustand des Fix für die GPS-Seite: stetig / unstet / unbekannt (GPS aus, noch keine Werte)."""
        with self._lock:
            if not self._fix_fast.known:
                state = "unbekannt"
            else:
                state = "unstet" if self._unstet else "stetig"
            now = self._clock()
            last_fix = None if self._last_fix_t is None else max(0.0, now - self._last_fix_t)
            return {"state": state, "changes_window": len(self._flaps), "window_s": self._flap_window,
                    "enter_at": self._flap_enter, "calm_s": self._flap_calm,
                    "unstet_since": self._unstet_since_wall, "unstet_changes": self._unstet_changes,
                    "fix": self._fix_fast.state if self._fix_fast.known else None,
                    "weak": self._weak(now), "last_fix_s": None if last_fix is None else round(last_fix)}

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
    def clients(self, clients: Any, threshold_ms: Any, fmt: Callable[[float], str] | None = None,
                data_for: Callable[[str], dict] | None = None, handover: Any = None) -> None:
        """Meldet Client-Uhren, die um mehr als threshold_ms abweichen.

        Hysterese wie bei den übrigen Zuständen: Ein Alarm entsteht erst, wenn ZWEI neue
        Messungen hintereinander über der Schwelle liegen; „wieder im Rahmen“ erst, wenn zwei
        Messungen unter der HÄLFTE liegen. So pendelt ein Gerät an der Grenze nicht. Gezählt
        wird nur, wenn das Gerät wirklich neu gemessen wurde (Zähler „count“ gestiegen).

        Der Titel nennt nur die Adresse, nie den eigenen Namen: Gespeicherte Titel bleiben 90 Tage
        stehen, der Datenschutzfilter kennt aber nur die aktuellen Namen (Umbenennen/Löschen).

        data_for(ip) (1.5): zusätzliche Ereignisdaten je Gerät, z. B. {"notify": False} für
        stummgeschaltete Geräte (Clients 3) – das Ereignis bleibt dann im Protokoll.

        Fällt ein Gerät mit offenem Alarm heraus (eigene Schwelle übernimmt – handover –, Gerät nicht
        mehr in der Liste oder Schwelle ausgeschaltet), schließt ein stilles „info“-Ereignis den Alarm.
        Sonst bliebe er im Protokoll und in den Benachrichtigungen offen, und der nächste Alarm für
        dieses Gerät gälte als „schon gemeldet“.
        """
        try:
            threshold = float(threshold_ms or 0) / 1000.0
        except (TypeError, ValueError):
            threshold = 0.0
        if not isinstance(clients, dict):
            return
        fmt = fmt or (lambda v: f"{v * 1000:+.1f} ms")
        handover = set(handover or ())
        with self._lock:
            if threshold <= 0:
                for ip in list(self._clients):
                    self._close_client(ip, "Alarm-Schwelle ausgeschaltet")
                self._clients.clear()
                self._clients_threshold = None
                return
            if self._clients_threshold != threshold:
                # Neue Schwelle: Zustände neu aufbauen, aber offene Alarme nicht doppelt melden.
                for state in self._clients.values():
                    state["streak"] = 0
                self._clients_threshold = threshold
            for ip in [ip for ip in self._clients if ip not in clients]:
                self._close_client(ip, "eigene Schwelle übernimmt" if ip in handover
                                   else "nicht mehr in der Liste")
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
                        self._send("clients", "warn", f"Uhr von {ip} weicht um {fmt(value)} ab",
                                   {"address": ip, "offset": value, "threshold_ms": threshold * 1000,
                                    **_extra(data_for, ip)})
                else:
                    back = abs(value) < threshold / 2
                    state["streak"] = state["streak"] + 1 if back else 0
                    if state["streak"] >= CONFIRM:
                        state.update(alarm=False, streak=0)
                        self._send("clients", "info", f"Uhr von {ip} wieder im Rahmen ({fmt(value)})",
                                   {"address": ip, "offset": value, "threshold_ms": threshold * 1000,
                                    **_extra(data_for, ip)})
            if len(self._clients) > 5000:
                for ip in list(self._clients)[:len(self._clients) - 5000]:
                    del self._clients[ip]
