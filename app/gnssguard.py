"""GNSS-Störungen erkennen und melden, GPS bei Störung sperren (1.5, Themen 1 und 2).

Was gpsd 3.25 (Debian trixie) liefert, reicht für Muster, die mit **jedem** Empfänger
funktionieren – auch mit dem VK-162 ohne PPS: C/N0 je Satellit (SKY „ss“), genutzte
Satelliten, die Position (TPV). Dazu kommen chronys eigene Messungen: der Abstand der
GPS-Zeit zu den Netzquellen und ob chrony das GPS für falsch hält. Ein „jam“-Feld gibt es
erst ab gpsd 3.26, Spoofing-Flags nur bei neueren u-blox-Generationen – beides wird hier
nicht gebraucht. Auf den Empfänger wird nichts geschrieben.

Signale (Konzept 1.4, Thema 12; 1.5, Thema 1)
-----------------------------------------------
schwach (allein nur „Hinweis“ – Schnee, Flugzeuge, ein Lkw vor dem Fenster):
  * cn0_drop     C/N0 der meisten Satelliten bricht gleichzeitig um ≥ 6 dB ein, innerhalb von
                 60 s (Jamming oder Abschattung). Ein langsamer Abfall über Minuten bis Stunden
                 (Schnee auf der Antenne) zählt nicht. Ebenso wenig (seit 1.6.3) ein Einbruch derselben
                 Satelliten genau einen Sterntag (± 90 s) nach einem früheren: wiederkehrende
                 Abschattung durch einen festen Gegenstand, nur vermerkt (cn0.recurring_shadow).
  * uniform      unnatürlich gleichmäßiges C/N0: ≥ 6 Satelliten fast gleich stark (ein Spoofer
                 sendet alle Signale aus einer Antenne; echte Satelliten stehen verschieden hoch).
  * falseticker  chrony markiert das GPS dauerhaft als Falseticker. Hält das mit ≥ 2 NTS-Quellen
                 5 min an, zählt es als **stark** – das fängt auch einen Spoofer, der die Zeit so
                 langsam wegzieht (< 10 ms/h), dass der Zeitanker mitwandert. Ausnahme (1.5.1,
                 nur ohne PPS): Ist das GPS seit dem Start bzw. seit einer Änderung der
                 GPS-Einstellungen (Offset, Gerät, Name) noch nie 15 min lang brauchbar gewesen
                 und gleich „x“ – typisch nach „Offset zurücksetzen“: GPS dauerhaft rund +51 ms
                 neben dem Netz –, gilt der Abstand, der dabei gemessen wird, als vermutlicher
                 Kalibrierfehler. Solange die GPS-Zeit innerhalb der Zeitschwelle bei diesem
                 Abstand bleibt (auch in späteren Falseticker-Phasen bis zur nächsten Änderung),
                 bleibt es „Hinweis“ mit dem Rat, den Offset zu kalibrieren; entfernt sie sich
                 um mindestens die Zeitschwelle (nie unter 20 ms), gilt wieder die Regel oben.
                 Die Ausnahme übersteht einen Neustart von ntp-gui nur, wenn sie vorher schon
                 galt (sie steht mit dem Zeitanker in SQLite); ein Neustart macht aus einem
                 erkannten Spoofer nie einen „Kalibrierfehler“. Nach einer „Störung“ im selben
                 Abschnitt gibt es keine Ausnahme mehr.
                 Grob (> 1 s) daneben ist immer stark. Mit PPS (1.5.2): Die NMEA-Zeile nummeriert
                 nur die Sekunden, die Zeit kommt vom PPS. Nutzt chrony die PPS-Quelle („*“/„+“)
                 und liegt die NMEA-Zeit unter 0,5 s neben dem Netz, bleibt ihr Falseticker
                 schwach – eine NMEA-Verspätung über der Fehlerschranke ist dann keine Störung,
                 und die Automatik bleibt nicht gesperrt. Ein Spoofer verschiebt auch das PPS;
                 dann ist die PPS-Quelle selbst nicht mehr genutzt und es gilt die Regel oben. Ein Spoofer,
                 der schon beim Start da war oder genau nach einer Einstellungsänderung einsetzt
                 und die Zeit nur um einen festen Betrag verschiebt, ist davon nicht zu
                 unterscheiden – ihn fängt erst ein Zeit- oder Positionssprung.
stark (→ „Störung“):
  * time         GPS-Zeit weicht vom Median von ≥ 2 NTS-Quellen ab (ohne NTS: ≥ 3 Netzquellen),
                 deutlich über der gewohnten Streuung. Gemessen wird gegen einen **Anker**: Er
                 startet beim Median der ersten Minuten und folgt der 30-min-Grundlinie höchstens
                 10 ms je Stunde. Ein Spoofer, der die Zeit langsam wegzieht (0,5 … 2 ms/min),
                 entfernt sich so vom Anker und wird nach ein bis zwei Stunden erkannt, statt
                 still in die Grundlinie zu wandern. Insgesamt darf der Anker höchstens 30 ms von
                 seinem Startwert (Start bzw. letzte Änderung der GPS-Einstellungen) wegwandern
                 (1.5.1): Ein Spoofer, der noch langsamer zieht (wenige ms je Stunde) und dabei
                 hinter der mitwachsenden Fehlerschranke bleibt (chrony markiert das GPS dann nie
                 als „x“), fällt so spätestens bei rund 30 ms + Zeitschwelle auf. Der Anker samt
                 Startwert (nur Zeitabstände, keine Position) steht in SQLite und gilt nach einem
                 Neustart von ntp-gui weiter; ändern sich die GPS-Einstellungen (Offset, Gerät,
                 Name), wird er neu gelernt.
  * position     Positionssprung > 100 m bei einem stationären Empfänger (und > 3 × eph), ebenfalls
                 gegen einen Anker, der höchstens 20 m je Stunde wandert (nur im Speicher).
                 1.5.4: Nur verlässliche Fixe zählen – 3D, ≥ 5 genutzte Satelliten, HDOP ≤ 4
                 (ohne HDOP: eph ≤ 50 m) –, für die Referenz wie für den Sprung. Und der Sprung
                 muss über ≥ 5 gute Fixe in Folge und ≥ 50 s anhalten. Drinnen (2D/3D im Wechsel,
                 HDOP 5–20) gab es sonst Fehlalarme „Position um … m gesprungen“.

Solange ein Signal anschlägt, sind seine Grundlinien eingefroren: Eine Störung, die einfach
bleibt, wird nie zur neuen Normalität – sie endet erst, wenn die Werte zurückkommen, oder mit
„Neu lernen“. Fehlen einem aktiven Signal die Daten (kein 3D-Fix, GPS unerreichbar), erlischt es
nach der doppelten Haltezeit mit „keine Messwerte mehr“, statt ewig „Störung“ zu zeigen.

Stufen: „Hinweis“ (ein schwaches Signal) → „Warnung“ (zwei schwache) → „Störung“ (ein starkes).
Hysterese: Ein Signal zählt erst, wenn es mehrmals hintereinander anschlägt, und erlischt erst
nach 2 min (schwach) bzw. 5 min (stark) ohne Befund. Ereignisse (Art „gps“, Betreff „gnss“):
Hinweis = info, Warnung = warn, Störung = crit, Ende = info „GNSS wieder unauffällig“.
Benachrichtigt wird standardmäßig nur bei „Störung“ (Einstellung gnss_notify); darunter
tragen die Ereignisse data.notify = false und bleiben im Protokoll. Was gnss_notify freigibt,
trägt data.notify = true – der Verteiler schickt es dann auch unterhalb der Mindeststufe des
Kanals (sonst bliebe „Hinweis – jeder Befund“ bei Kanälen ab „Warnung“ wirkungslos).

GPS-Sperre (Thema 2)
--------------------
Einstellung gnss_guard: „off“ / „report“ (Standard, nur melden) / „lock“ (opt-in). Mit
„lock“ wählt ntp-gui bei einem **starken** Signal GPS (und PPS) per `chronyc selectopts
<refid> +noselect` ab – reines Jamming (C/N0) sperrt nie, chrony schaltet bei Fix-Verlust
ohnehin auf das Netz. Freigabe nach 30 min ohne jedes Signal, höchstens dreimal hintereinander
automatisch; die vierte Sperre in Folge bleibt bis zur Freigabe von Hand. Sperren und
Freigeben gehen auch von Hand (admin). Der Zustand steht in SQLite: Nach einem Neustart von
chronyd (z. B. Einstellungen gespeichert) wählt der Supervisor das GPS sofort wieder ab
(selectctl: noselect.list), nach einem Neustart von ntp-gui setzt der Prüftakt die Sperre neu.
Automatisch gesperrt wird nur, wenn mindestens zwei andere erreichbare, auswählbare Netzquellen
bleiben – sonst liefe die Uhr ohne jede Quelle frei; dann gibt es nur die Meldung „Sperre
ausgelassen“. Von Hand geht es auch dann, aber nur mit ausdrücklicher Bestätigung (force).

Datenschutz
-----------
Die Referenzposition liegt **nur im Speicher** dieses Prozesses (Median der letzten Stunde) –
sie wird nie gespeichert, nie angezeigt und nie exportiert. Ereignisse, API und Oberfläche
nennen nur die Abweichung in Metern (auf 10 m gerundet), keine Richtung, keine Koordinaten.
Satellitenwinkel werden hier gar nicht verwendet.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from typing import Any, Callable

import numfmt
import selectctl
import store

INTERVAL = 10.0                 # Prüftakt (eigener Thread, unabhängig vom Diagramm-Intervall)

# --- C/N0-Einbruch ------------------------------------------------------------------------
CN0_DROP_DB = 6.0
CN0_WINDOW = 60.0               # „vorher“ = Werte, die 15 … 60 s alt sind
CN0_MIN_AGE = 15.0
CN0_MIN_BEFORE = 20.0           # nur Satelliten, die vorher mindestens so stark waren
CN0_MIN_SATS = 4
CN0_SHARE = 0.6                 # so viele davon müssen gleichzeitig einbrechen
CN0_RECOVER_DB = 3.0            # erholt, wenn der Median wieder bis auf 3 dB an „vorher“ heran ist
# Hysterese: Ein betroffener Satellit, der nicht mehr gemeldet wird, zählt als 0 dB (ein Störsender nimmt
# den Lock ganz weg) – außer er wurde nach Beginn des Einbruchs noch mindestens so lange weiter gemeldet:
# Dann ist er später verschwunden, nicht mit dem Einbruch (untergegangen oder hinter dem Hindernis).
CN0_VANISH_GRACE = CN0_WINDOW
# Ein fester Gegenstand (Fensterrahmen, Hauswand) schattet jeden Sterntag zur selben
# Konstellation dieselben Satelliten ab. Gab es genau einen Sterntag vorher (± CN0_RECUR_TOLERANCE) einen
# Einbruch, an dem mindestens CN0_RECUR_OVERLAP der jetzt betroffenen Satelliten beteiligt waren, gilt er
# als wiederkehrende Abschattung – kein GNSS-Hinweis. Die Toleranz bleibt deutlich unter den 236 s, um die
# ein Sonnentag länger ist: Ein Störsender, der jeden Tag zur selben Uhrzeit läuft, fällt weiter auf.
SIDEREAL_DAY = 86164.0905
CN0_RECUR_TOLERANCE = 90.0
CN0_RECUR_OVERLAP = 0.6
CN0_RECUR_MIN_SATS = 3
CN0_RECUR_KEEP = 2 * SIDEREAL_DAY  # so lange bleiben Einbrüche (nur Zeit + Satelliten-Schlüssel) im Speicher

# --- Gleichmäßiges C/N0 ----------------------------------------------------------------------
UNIFORM_MIN_SATS = 6
UNIFORM_MIN_CN0 = 15.0
UNIFORM_STDEV = 1.0
UNIFORM_RANGE = 3.0

# --- Zeitabgleich ----------------------------------------------------------------------------
TIME_MIN_NTS = 2
TIME_MIN_PLAIN = 3
TIME_BASE_WINDOW = 1800.0       # Grundlinie: Median GPS − Netz der letzten 30 min …
TIME_BASE_EXCLUDE = 120.0       # … ohne die letzten 2 min
TIME_BASE_MIN = 20
TIME_THRESHOLD_MIN = 0.020      # nie enger als 20 ms (NMEA ohne PPS)
TIME_SPREAD_FACTOR = 5.0        # und mindestens 5 × die gewohnte Streuung (MAD)
TIME_ABS_LIMIT = 1.0            # ohne Grundlinie zählt nur ein grober Fehler (> 1 s)
TIME_THRESHOLD_MAX = 0.100      # die Schwelle aus der Streuung wächst nie über 100 ms
TIME_ANCHOR_RATE = 0.010 / 3600.0   # der Anker folgt der Grundlinie höchstens 10 ms je Stunde …
TIME_ANCHOR_WANDER = 0.030      # … und insgesamt höchstens 30 ms weg vom Startwert des Abschnitts (1.5.1)
ANCHOR_STEP_MAX = 60.0          # je Durchgang zählt höchstens 1 min (Datenlücken schieben nicht)
TIME_ANCHOR_SAVE_EVERY = 600.0
TIME_ANCHOR_MAX_AGE = 7 * 86400.0   # ein gespeicherter Anker gilt höchstens eine Woche
FALSETICKER_STRONG_S = 300.0    # Falseticker mit ≥ 2 NTS-Quellen so lange → starkes Signal
FALSETICKER_SETTLED_S = 900.0   # Ausnahme „Kalibrierfehler“ nur, solange das GPS seit Start/Änderung
                                # noch nicht so lange brauchbar war (siehe Modulbeschreibung)
FALSETICKER_RECENT = 120.0      # Abstand GPS − Netz für den Falseticker: Median der letzten 2 min
PPS_REFID = "PPS"               # refid der PPS-Zeile (confgen)
PPS_NMEA_LIMIT = 0.5            # mit genutztem PPS: NMEA nur Sekundennummerierung, solange < 0,5 s daneben

# --- Position ----------------------------------------------------------------------------------
POS_JUMP_M = 100.0
POS_EPH_FACTOR = 3.0
POS_REF_MIN = 30                # ~5 min 3D-Fix, bevor die Referenz gilt
POS_REF_WINDOW = 3600.0
POS_FRESH = 30.0
POS_ANCHOR_RATE = 20.0 / 3600.0     # Positionsanker wandert höchstens 20 m je Stunde
# 1.5.4: Nur verlässliche Fixe zählen – für die Referenz und für den Sprung. Drinnen (VK-162,
# 3–4 Satelliten, HDOP 5–20, 2D/3D im Wechsel) streut die Position um 100 m und mehr; ein
# „Sprung“ daraus ist kein Spoofing. Ein Spoofer liefert dagegen ein sauberes Signal mit guter
# Geometrie – den fängt die Prüfung weiter.
POS_MIN_USED = 5                # mindestens so viele genutzte Satelliten
POS_MAX_HDOP = 4.0              # HDOP höchstens …
POS_MAX_EPH = 50.0              # … oder, ohne HDOP, gpsd-eph (95-%-Fehler, m) höchstens
POS_PERSIST_S = 50.0            # ein Sprung zählt erst, wenn er so lange über gute Fixe anhält …
POS_PERSIST_FIXES = 5           # … und über so viele gute Fixe in Folge (ersetzt die Bestätigung)
POS_PERSIST_GAP = 120.0         # längere Lücke ohne guten Fix: Zählung beginnt neu
EARTH_M = 6_371_000.0

CONFIRM = {"cn0_drop": 2, "uniform": 3, "falseticker": 3, "time": 3, "position": 1}
HOLD = {"weak": 120.0, "strong": 300.0}
STALE_FACTOR = 2.0              # ohne Daten erlischt ein aktives Signal nach 2 × Haltezeit
AUTO_LOCK_MIN_OTHERS = 2        # automatisch sperren nur, wenn so viele andere Quellen bleiben
ANCHOR_KEYS = ("gps_offset", "gps_device", "gps_refid")   # ändern sie sich, gilt der Zeitanker nicht mehr
SIGNALS = {
    "cn0_drop": ("weak", "Gleichzeitiger C/N0-Einbruch"),
    "uniform": ("weak", "Unnatürlich gleichmäßige Signale"),
    "falseticker": ("weak", "chrony hält das GPS für falsch"),
    "time": ("strong", "GPS-Zeit weicht von den Netzquellen ab"),
    "position": ("strong", "Positionssprung"),
}
STAGES = ("ok", "hinweis", "warnung", "stoerung")
STAGE_LABELS = {"ok": "unauffällig", "hinweis": "Hinweis", "warnung": "Warnung", "stoerung": "Störung"}
STAGE_LEVEL = {"hinweis": "info", "warnung": "warn", "stoerung": "crit"}

# --- Sperre --------------------------------------------------------------------------------------
LOCK_OWNER = "gps-lock"
RELEASE_AFTER = 1800.0          # 30 min ohne Signal → automatische Freigabe
MAX_AUTO_RELEASES = 3           # danach bleibt die nächste Sperre bis zur Freigabe von Hand
FREERUN_ALERT = 6 * 3600.0      # 1.5.4: so lange gesperrt ohne andere auswählbare Quelle → „Uhr läuft frei“
SERIES_RESET = 24 * 3600.0      # nach 24 h ohne Sperre beginnt die Zählung neu

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS gnss_state (key TEXT PRIMARY KEY, json TEXT NOT NULL);",
]


class GuardError(ValueError):
    """Ungültige Eingabe (→ 400) oder unpassender Zustand (→ 409, conflict=True)."""

    def __init__(self, message: str, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


# =========================================================================================
# Helfer
# =========================================================================================

def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _median(values: list[float]) -> float | None:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return None
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Abstand zweier Punkte (Grad) in Metern – flache Näherung, auf 100 m … km genau genug."""
    lat0 = math.radians((a[0] + b[0]) / 2.0)
    dy = math.radians(a[0] - b[0]) * EARTH_M
    dx = math.radians(a[1] - b[1]) * EARTH_M * math.cos(lat0)
    return math.hypot(dx, dy)


def good_geometry(used: Any, hdop: Any, eph: Any) -> bool:
    """Ist ein 3D-Fix verlässlich genug für den Positionsvergleich? Unbekannte Werte zählen nicht
    gegen den Fix (ältere gpsd ohne SKY), bekannte schlechte schon."""
    used, hdop, eph = _num(used), _num(hdop), _num(eph)
    if used is not None and used < POS_MIN_USED:
        return False
    if hdop is not None:
        return hdop <= POS_MAX_HDOP
    return eph is None or eph <= POS_MAX_EPH


def fmt_ms(seconds: float) -> str:
    return f"{numfmt.adaptive(abs(seconds) * 1000.0)} ms"


def round_m(metres: float) -> int:
    """Abweichung in Metern, auf 10 m gerundet – genug für die Aussage, kein Feinwert."""
    return int(round(metres / 10.0) * 10)


def stage_rank(stage: str) -> int:
    return STAGES.index(stage) if stage in STAGES else 0


# =========================================================================================
# Hysterese je Signal
# =========================================================================================

class _Signal:
    def __init__(self, key: str) -> None:
        self.key = key
        self.strength, self.label = SIGNALS[key]
        self.confirm = CONFIRM[key]
        self.hold = HOLD[self.strength]
        self.streak = 0
        self.active = False
        self.since: float | None = None
        self.last_true: float | None = None
        self.detail: dict[str, Any] = {}
        self.text = ""
        self.last_data: float | None = None
        self.stale = False          # zuletzt erloschen, weil die Daten fehlten

    def update(self, cond: bool | None, now: float, detail: dict | None = None, text: str = "") -> str | None:
        """cond None = keine Daten. Gibt „on“/„off“ beim Wechsel zurück.

        Ohne Daten bleibt der Zustand – aber nicht ewig: Ein aktives Signal erlischt nach
        STALE_FACTOR × Haltezeit ohne Daten („keine Messwerte mehr“). Sonst stünde nach einem
        Positionssprung und anschließendem Fix-Verlust tagelang „Störung“ da, ohne Ende-Meldung
        und ohne automatische Freigabe der Sperre."""
        if cond is None:
            if (self.active and self.last_data is not None
                    and now - self.last_data >= STALE_FACTOR * self.hold):
                self.active = False
                self.since = None
                self.streak = 0
                self.stale = True
                return "off"
            return None
        self.last_data = now
        self.stale = False
        if cond:
            self.streak += 1
            self.last_true = now
            if detail is not None:
                self.detail = detail
                self.text = text
            if not self.active and self.streak >= self.confirm:
                self.active = True
                self.since = now
                return "on"
            return None
        self.streak = 0
        if self.active and (self.last_true is None or now - self.last_true >= self.hold):
            self.active = False
            self.since = None
            return "off"
        return None

    def public(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "strength": self.strength, "active": self.active,
                "text": self.text if self.active else "", **({k: v for k, v in self.detail.items()} if self.active else {})}


# =========================================================================================
# Erkennung (reine Logik, eingespeiste Zeit)
# =========================================================================================

class Detector:
    """Wertet Beobachtungen aus. obs (alle Felder optional):

    t           Sekunden (monoton; Tests: frei gewählt)
    sats        {Satellit: C/N0 in dB-Hz} der gerade gemeldeten Satelliten, None = keine Liste
    mode        Fix-Art (0/1 kein Fix, 2 = 2D, 3 = 3D)
    pos         (lat, lon, eph) eines 3D-Fix – bleibt in diesem Objekt, wird nie ausgegeben
    used, hdop  genutzte Satelliten und HDOP (gpsd SKY) – nur verlässliche Fixe zählen für die Position
    gps_offset  Offset der GPS-Quelle in chrony (s), gps_state ihr Zustand (*, +, -, x, ?)
    refs        Offsets der Referenz-Netzquellen (s), ref_kind „nts“ oder „ntp“
    """

    def __init__(self) -> None:
        self.signals = {key: _Signal(key) for key in SIGNALS}
        self._cn0: dict[str, deque] = {}
        self._cn0_ref: dict[str, float] = {}
        self._cn0_ref_since = 0.0                  # Beginn des Einbruchs, zu dem _cn0_ref gehört
        self._cn0_ref_seen: dict[str, float] = {}  # zuletzt gemeldet (nur Satelliten aus _cn0_ref)
        self._cn0_drops: deque = deque()            # (Beginn, Satelliten) früherer Einbrüche, nur im Speicher
        self._cn0_episode: dict[str, Any] | None = None   # laufender Einbruch {start, keys, recurring}
        self._diffs: deque = deque()
        self._recent_dev: deque = deque()          # (t, GPS − Netz) der letzten 2 min
        self._positions: deque = deque()
        self.time_anchor: float | None = None      # Zeitabstand GPS − Netz, langsam nachgeführt
        self._time_anchor_t: float | None = None
        self.anchor_start: float | None = None     # erster Anker des Abschnitts (Grenze fürs Wandern)
        self._pos_anchor: tuple[float, float] | None = None   # nur im Speicher, nie ausgegeben
        self._pos_anchor_t: float | None = None
        self._jump_since: float | None = None      # Sprung über gute Fixe seit …
        self._jump_last: float | None = None
        self._jump_fixes = 0
        self.last: dict[str, Any] = {}
        self.pps = False                           # mit PPS gibt es keine Ausnahme „Kalibrierfehler“
        self._pps_ok = False                       # mit PPS: NMEA-Falseticker nur Sekundennummerierung
        self.autocal = "off"                       # Modus der automatischen Kalibrierung (nur für den Text)
        self._reset_epoch()

    def _reset_epoch(self) -> None:
        """Neuer Abschnitt (Start, geänderte GPS-Einstellungen): Ausnahme „Kalibrierfehler“ neu prüfen."""
        self._epoch_good = 0.0                      # so lange war das GPS seitdem brauchbar (nicht „x“)
        self._epoch_t: float | None = None
        self._excuse: dict[str, Any] | None = None  # {"diff": Abstand GPS − Netz beim vermuteten Kalibrierfehler}
        self._ft_episode: float | None = None
        self._ft_excused = False

    def seed_time_anchor(self, value: float, start: float | None = None, epoch_good: float | None = None,
                         excuse: float | None = None) -> None:
        """Gespeicherten Zeitanker übernehmen (Neustart von ntp-gui, gleiche GPS-Einstellungen).

        Mit ihm kommt der Zustand des Abschnitts zurück: Startwert des Ankers, wie lange das GPS
        schon brauchbar war, und eine schon geltende Ausnahme „Kalibrierfehler“. Fehlt die Angabe
        (älterer Eintrag), gilt der Abschnitt als eingeschwungen – ein Neustart darf eine erkannte
        Störung nie zum „Kalibrierfehler“ herabstufen."""
        if _num(value) is None or self.time_anchor is not None:
            return
        self.time_anchor = float(value)
        self._time_anchor_t = None
        self.anchor_start = float(start) if _num(start) is not None else float(value)
        good = _num(epoch_good)
        self._epoch_good = FALSETICKER_SETTLED_S if good is None else max(0.0, min(good, FALSETICKER_SETTLED_S))
        self._excuse = {"diff": float(excuse)} if _num(excuse) is not None else None

    def anchor_record(self) -> dict[str, Any] | None:
        """Was mit dem Zeitanker gespeichert wird (nur Zeitabstände, keine Position)."""
        if self.time_anchor is None:
            return None
        excuse = (self._excuse or {}).get("diff")
        return {"value": self.time_anchor, "start": self.anchor_start,
                "epoch_good": min(self._epoch_good, FALSETICKER_SETTLED_S),
                "excuse": excuse if _num(excuse) is not None else None}

    def reset_time(self) -> None:
        """Nur den Zeitabstand neu lernen (GPS-Einstellungen geändert)."""
        self._diffs.clear()
        self._recent_dev.clear()
        self.last.pop("time_base_median", None)
        self.time_anchor = None
        self._time_anchor_t = None
        self.anchor_start = None
        self._reset_epoch()
        self.signals["time"].update(False, math.inf)
        self.signals["time"].streak = 0

    def reset_baselines(self) -> None:
        """Grundlinien vergessen (Empfänger umgezogen, neue Antenne)."""
        self._diffs.clear()
        self._recent_dev.clear()
        self.last.pop("time_base_median", None)
        self._reset_epoch()
        self._positions.clear()
        self.time_anchor = None
        self._time_anchor_t = None
        self.anchor_start = None
        self._pos_anchor = None
        self._pos_anchor_t = None
        self._jump_since = self._jump_last = None
        self._jump_fixes = 0
        self._cn0.clear()
        self._cn0_ref.clear()
        self._cn0_ref_seen.clear()
        self._cn0_drops.clear()
        self._cn0_episode = None
        for signal in self.signals.values():
            signal.update(False, math.inf)
            signal.streak = 0
        self.last = {}

    # --- C/N0 ---------------------------------------------------------------------------------
    def _check_cn0(self, now: float, sats: dict[str, float] | None) -> tuple[bool | None, dict, str]:
        if not sats:
            return None, {}, ""
        for key, value in sats.items():
            self._cn0.setdefault(key, deque()).append((now, value))
        for key in list(self._cn0):
            hist = self._cn0[key]
            while hist and now - hist[0][0] > CN0_WINDOW + 30.0:
                hist.popleft()
            if not hist:
                del self._cn0[key]
        before: dict[str, float] = {}
        for key, hist in self._cn0.items():
            values = [v for t, v in hist if CN0_MIN_AGE <= now - t <= CN0_WINDOW]
            if values:
                before[key] = _median(values)
        eligible = {k: v for k, v in before.items() if v >= CN0_MIN_BEFORE}
        sig = self.signals["cn0_drop"]
        cond = False
        drop = None
        if len(eligible) >= CN0_MIN_SATS:
            drops = [b - sats.get(k, 0.0) for k, b in eligible.items()]
            share = sum(1 for d in drops if d >= CN0_DROP_DB) / len(drops)
            drop = _median(drops)
            cond = share >= CN0_SHARE and drop >= CN0_DROP_DB
            if cond and not sig.active:
                if not self._cn0_ref:
                    self._cn0_ref_since = now
                self._cn0_ref = dict(eligible)
            detail = {"satellites": len(eligible), "drop_db": round(drop, 1)}
            if cond and self._cn0_episode is None:
                keys = frozenset(k for k, b in eligible.items() if b - sats.get(k, 0.0) >= CN0_DROP_DB)
                self._cn0_episode = {"start": now, "keys": keys, "recurring": self._cn0_recurs(now, keys)}
                self._cn0_drops.append((now, keys))
        else:
            detail = {}
        if not cond and sig.active and self._cn0_ref:
            # Hysterese: aktiv bleiben, solange die betroffenen Satelliten nicht zurück sind. Ein nicht mehr
            # gemeldeter Satellit zählt als 0 dB – ein Störsender nimmt den Lock oft ganz weg. Wurde er nach
            # Beginn des Einbruchs aber noch CN0_VANISH_GRACE lang gemeldet, ist er erst später verschwunden
            # (untergegangen, hinter dem Hindernis) und zählt nicht mehr (sonst hielt er das Signal
            # über eine halbe Stunde fest). Bleibt keiner übrig, hält die Hysterese nicht.
            current_values: dict[str, float] = {}
            for k in self._cn0_ref:
                if k in sats:
                    current_values[k] = sats[k]
                elif self._cn0_ref_seen.get(k, -math.inf) - self._cn0_ref_since < CN0_VANISH_GRACE:
                    current_values[k] = 0.0
            if current_values:
                ref = _median([self._cn0_ref[k] for k in current_values])
                current = _median(list(current_values.values()))
                if ref is not None and current is not None and current < ref - CN0_RECOVER_DB:
                    cond = True
                    drop = ref - current
                    detail = {"satellites": len(current_values), "drop_db": round(drop, 1)}
        if not cond and not sig.active:
            self._cn0_ref = {}
        for k in self._cn0_ref:
            if k in sats:
                self._cn0_ref_seen[k] = now
        if not self._cn0_ref:
            self._cn0_ref_seen.clear()
        if not cond:
            self._cn0_episode = None
            self.last.pop("cn0_recurring", None)   # Einbruch vorbei: kein alter Vermerk in status()
        episode = self._cn0_episode
        if cond and episode and episode["recurring"]:
            # Wiederkehrende Abschattung: kein GNSS-Hinweis, nur vermerkt (Rat zur Antennenposition).
            self.last["cn0_recurring"] = {"satellites": len(episode["keys"]), "drop_db": round(drop, 1)}
            self.last["cn0_drop_db"] = round(drop, 1) if drop is not None else None
            self.last["cn0_satellites"] = len(eligible)
            return False, {}, ""
        text = (f"Signale von {detail.get('satellites')} Satelliten gleichzeitig um "
                f"{numfmt.number(detail.get('drop_db', 0))} dB eingebrochen") if cond else ""
        self.last["cn0_drop_db"] = round(drop, 1) if drop is not None else None
        self.last["cn0_satellites"] = len(eligible)
        return cond, detail, text

    def _cn0_recurs(self, now: float, keys: frozenset) -> bool:
        """Gab es einen Sterntag vorher einen Einbruch derselben Satelliten? Alte Einträge fallen weg."""
        while self._cn0_drops and now - self._cn0_drops[0][0] > CN0_RECUR_KEEP:
            self._cn0_drops.popleft()
        if len(keys) < CN0_RECUR_MIN_SATS:
            return False
        for start, before in self._cn0_drops:
            if abs(now - start - SIDEREAL_DAY) <= CN0_RECUR_TOLERANCE and \
                    len(keys & before) >= CN0_RECUR_OVERLAP * len(keys):
                return True
        return False

    def _check_uniform(self, sats: dict[str, float] | None) -> tuple[bool | None, dict, str]:
        if not sats:
            return None, {}, ""
        values = [v for v in sats.values() if v >= UNIFORM_MIN_CN0]
        if len(values) < UNIFORM_MIN_SATS:
            return False, {}, ""
        mean = sum(values) / len(values)
        sd = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        cond = sd < UNIFORM_STDEV and max(values) - min(values) <= UNIFORM_RANGE
        detail = {"satellites": len(values), "stdev_db": round(sd, 2)}
        self.last["cn0_stdev_db"] = round(sd, 2)
        text = (f"{len(values)} Satelliten mit fast gleicher Signalstärke "
                f"(Streuung {numfmt.number(sd, 1)} dB)") if cond else ""
        return cond, detail, text

    # --- Zeit -----------------------------------------------------------------------------------
    def _check_time(self, now: float, obs: dict) -> tuple[bool | None, dict, str]:
        gps = _num(obs.get("gps_offset"))
        refs = [r for r in (obs.get("refs") or []) if _num(r) is not None]
        kind = obs.get("ref_kind")
        needed = TIME_MIN_NTS if kind == "nts" else TIME_MIN_PLAIN
        self.last["references"] = len(refs)
        self.last["ref_kind"] = kind if len(refs) >= needed else None
        if gps is None or obs.get("gps_state") == "?" or len(refs) < needed:
            self.last["time_diff"] = self.last["time_recent_diff"] = None
            return None, {}, ""
        diff = gps - _median(refs)
        self.last["time_diff"] = diff
        sig = self.signals["time"]
        if not sig.active:
            # Während einer Störung bleibt die Grundlinie eingefroren: Sie darf nicht einfach
            # auslaufen, sonst wäre eine Fälschung, die bleibt, nach 30 min „normal“.
            while self._diffs and now - self._diffs[0][0] > TIME_BASE_WINDOW:
                self._diffs.popleft()
        base = [d for t, d in self._diffs if now - t > TIME_BASE_EXCLUDE]
        if len(base) >= TIME_BASE_MIN:
            middle = _median(base)
            self.last["time_base_median"] = middle
            mad = _median([abs(d - middle) for d in base]) * 1.4826
            threshold = min(TIME_THRESHOLD_MAX, max(TIME_THRESHOLD_MIN, TIME_SPREAD_FACTOR * mad))
            if self.time_anchor is None:
                self.time_anchor = middle
            elif not sig.active:
                # Der Anker folgt der Grundlinie nur langsam – ein langsames Wegziehen bleibt sichtbar.
                dt = 0.0 if self._time_anchor_t is None else min(ANCHOR_STEP_MAX, max(0.0, now - self._time_anchor_t))
                step = TIME_ANCHOR_RATE * dt
                self.time_anchor += max(-step, min(step, middle - self.time_anchor))
            if self.anchor_start is None:
                self.anchor_start = self.time_anchor
            # … und insgesamt nur begrenzt weit: Ein sehr langsamer Spoofer zieht ihn sonst mit.
            self.time_anchor = max(self.anchor_start - TIME_ANCHOR_WANDER,
                                   min(self.anchor_start + TIME_ANCHOR_WANDER, self.time_anchor))
            self._time_anchor_t = now
            center, baseline = self.time_anchor, True
        elif self.time_anchor is not None:
            # Gespeicherter Anker, aber noch keine frische Grundlinie (Neustart): grobe Schwelle.
            center, threshold, baseline = self.time_anchor, TIME_THRESHOLD_MAX, True
        else:
            center, threshold, baseline = 0.0, TIME_ABS_LIMIT, False
        deviation = diff - center
        cond = abs(deviation) > threshold
        wandered = (self.time_anchor - self.anchor_start
                    if self.time_anchor is not None and self.anchor_start is not None else 0.0)
        self.last["time_wander"] = wandered
        self._recent_dev.append((now, diff))
        while self._recent_dev and now - self._recent_dev[0][0] > FALSETICKER_RECENT:
            self._recent_dev.popleft()
        self.last["time_recent_diff"] = _median([x for _t, x in self._recent_dev])
        if not cond and not sig.active:
            self._diffs.append((now, diff))   # Grundlinie lernt nur aus unauffälligen Werten
        self.last.update(time_deviation=deviation, time_threshold=threshold, time_baseline=baseline)
        source = "NTS-Quellen" if kind == "nts" else "Netzquellen"
        detail = {"deviation_ms": round(deviation * 1000.0, 1), "threshold_ms": round(threshold * 1000.0, 1),
                  "references": len(refs), "ref_kind": kind}
        text = f"GPS-Zeit weicht {fmt_ms(deviation)} vom Median von {len(refs)} {source} ab" if cond else ""
        if cond and abs(wandered) >= TIME_ANCHOR_WANDER - 1e-6:
            text += (f" – der gewohnte Abstand war seit dem Start bzw. der letzten Änderung der GPS-Einstellungen "
                     f"schon um {fmt_ms(wandered)} gewandert (langsames Wegziehen?)")
        return cond, detail, text

    # --- Position -------------------------------------------------------------------------------
    def _check_position(self, now: float, obs: dict) -> tuple[bool | None, dict, str]:
        pos = obs.get("pos")
        if obs.get("mode") != 3 or not pos:
            return None, {}, ""
        lat, lon = _num(pos[0]), _num(pos[1])
        eph = _num(pos[2]) if len(pos) > 2 else None
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, {}, ""
        if not good_geometry(obs.get("used"), obs.get("hdop"), eph):
            # Schwache Geometrie: weder Referenz noch neuer Sprung (wie „keine Daten“). Ist das Signal
            # schon aktiv, hält auch ein schwacher Fix außerhalb der Schwelle es aktiv – sonst käme nach
            # 2 × Haltezeit „wieder unauffällig“, obwohl die falsche Position noch anliegt.
            self.last["position_quality"] = "schwach"
            sig = self.signals["position"]
            if sig.active and self._pos_anchor is not None:
                deviation = distance_m((lat, lon), self._pos_anchor)
                threshold = max(POS_JUMP_M, POS_EPH_FACTOR * eph if eph else 0.0)
                if deviation > threshold:
                    detail = {"deviation_m": round_m(deviation), "threshold_m": round_m(threshold)}
                    return True, detail, f"Position um {round_m(deviation)} m gesprungen (Empfänger steht fest)"
            return None, {}, ""
        self.last["position_quality"] = "gut"
        sig = self.signals["position"]
        if not sig.active:   # während eines Sprungs eingefroren (sonst lernt sie den falschen Ort)
            while self._positions and now - self._positions[0][0] > POS_REF_WINDOW:
                self._positions.popleft()
        if len(self._positions) >= POS_REF_MIN:
            middle = (_median([p[1] for p in self._positions]), _median([p[2] for p in self._positions]))
            if self._pos_anchor is None:
                self._pos_anchor = middle
            elif not sig.active:
                dt = 0.0 if self._pos_anchor_t is None else min(ANCHOR_STEP_MAX, max(0.0, now - self._pos_anchor_t))
                gap = distance_m(middle, self._pos_anchor)
                step = POS_ANCHOR_RATE * dt
                if gap > 0:
                    share = min(1.0, step / gap)
                    self._pos_anchor = (self._pos_anchor[0] + (middle[0] - self._pos_anchor[0]) * share,
                                        self._pos_anchor[1] + (middle[1] - self._pos_anchor[1]) * share)
            self._pos_anchor_t = now
        if self._pos_anchor is None:
            if not sig.active:
                self._positions.append((now, lat, lon))
            self.last.update(position_learned=False, position_deviation_m=None)
            return False, {}, ""
        ref = self._pos_anchor
        deviation = distance_m((lat, lon), ref)
        threshold = max(POS_JUMP_M, POS_EPH_FACTOR * eph if eph else 0.0)
        jump = deviation > threshold
        if jump:
            if (self._jump_since is None or self._jump_last is None
                    or now - self._jump_last > POS_PERSIST_GAP):
                self._jump_since, self._jump_fixes = now, 0
            self._jump_fixes += 1
            self._jump_last = now
        else:
            self._jump_since = self._jump_last = None
            self._jump_fixes = 0
        # Ein Sprung zählt erst, wenn er über mehrere gute Fixe anhält; ist das Signal schon aktiv,
        # reicht jeder gute Fix außerhalb der Schwelle, damit es aktiv bleibt.
        persisted = (jump and self._jump_since is not None and now - self._jump_since >= POS_PERSIST_S
                     and self._jump_fixes >= POS_PERSIST_FIXES)
        cond = jump if sig.active else persisted
        if not jump and not sig.active:
            self._positions.append((now, lat, lon))
        self.last.update(position_learned=True, position_deviation_m=round_m(deviation))
        detail = {"deviation_m": round_m(deviation), "threshold_m": round_m(threshold)}
        text = f"Position um {round_m(deviation)} m gesprungen (Empfänger steht fest)" if cond else ""
        return cond, detail, text

    # --- alles zusammen ----------------------------------------------------------------------------
    def update(self, obs: dict) -> dict[str, Any]:
        now = float(obs.get("t", 0.0))
        sats = obs.get("sats")
        state = obs.get("gps_state")
        if self._epoch_t is not None and state not in (None, "?", "x"):
            self._epoch_good += min(ANCHOR_STEP_MAX, max(0.0, now - self._epoch_t))
        self._epoch_t = now
        self.last["pps_state"] = obs.get("pps_state")
        checks = {
            "cn0_drop": self._check_cn0(now, sats),
            "uniform": self._check_uniform(sats),
            "falseticker": ((obs.get("gps_state") == "x") if obs.get("gps_state") not in (None, "?") else None,
                            {}, "chrony hält das GPS für einen Falseticker (die Netzquellen sind sich einig)"),
            "time": self._check_time(now, obs),
            "position": self._check_position(now, obs),
        }
        changes = {}
        for key, (cond, detail, text) in checks.items():
            change = self.signals[key].update(cond, now, detail, text)
            if change:
                changes[key] = change
        self._grade_falseticker(now)
        stage = self.stage()
        if stage == "stoerung":
            # Nach einer Störung gibt es in diesem Abschnitt keine Ausnahme „Kalibrierfehler“ mehr.
            self._epoch_good = max(self._epoch_good, FALSETICKER_SETTLED_S)
            self._excuse = None
            self._ft_excused = False
        return {"stage": stage, "changes": changes}

    def _grade_falseticker(self, now: float) -> None:
        """Falseticker: stark nach 5 min mit ≥ 2 NTS-Quellen – außer beim vermuteten Kalibrierfehler
        (siehe Modulbeschreibung): ohne PPS, das GPS war seit Start/Änderung nie brauchbar, und die
        GPS-Zeit bleibt beim dabei gemessenen Abstand. Grob (> 1 s) daneben ist immer stark."""
        ft = self.signals["falseticker"]
        if not ft.active:
            ft.strength = "weak"
            self._ft_episode = None
            return
        last = self.last
        diff = _num(last.get("time_recent_diff"))
        limit = max(TIME_THRESHOLD_MIN, _num(last.get("time_threshold")) or 0.0)
        if self._ft_episode != ft.since:          # neue Falseticker-Phase: einmal einordnen
            self._ft_episode = ft.since
            self._ft_excused = not self.pps and (self._excuse is not None
                                                 or self._epoch_good < FALSETICKER_SETTLED_S)
            if self._ft_excused and self._excuse is None:
                self._excuse = {"diff": None}
        if self._ft_excused and diff is not None:
            if self._excuse["diff"] is None:
                anchor = self.time_anchor
                # Ein gespeicherter Anker (Neustart) mit anderem Abstand: kein Kalibrierfehler.
                if anchor is not None and abs(diff - anchor) >= limit:
                    self._ft_excused = False
                else:
                    self._excuse["diff"] = diff
            elif abs(diff - self._excuse["diff"]) >= limit:
                self._ft_excused = False          # die GPS-Zeit wandert weg: keine Ausnahme mehr
        gross = diff is not None and abs(diff) > TIME_ABS_LIMIT
        lasting = ft.since is not None and now - ft.since >= FALSETICKER_STRONG_S
        nts = last.get("ref_kind") == "nts"
        # Mit PPS: Die Zeit kommt vom (genutzten) PPS, die NMEA-Zeile nummeriert nur die Sekunden. Ohne
        # frischen Messwert (kurz kein Fix) gilt die letzte Einordnung weiter.
        if not self.pps:
            self._pps_ok = False
        elif diff is not None:
            self._pps_ok = last.get("pps_state") in {"*", "+"} and abs(diff) < PPS_NMEA_LIMIT
        pps_ok = self._pps_ok
        strong = lasting and nts and not pps_ok and (gross or not self._ft_excused)
        if pps_ok:
            ft.text = ("Die NMEA-Zeit liegt " + (f"{fmt_ms(diff)} " if diff is not None else "")
                       + "neben dem Netz, die Zeit kommt aber vom PPS (genutzt) – "
                       "die NMEA-Zeile nummeriert nur die Sekunden, das ist keine Störung"
                       + ("; die automatische Kalibrierung gleicht den Offset nach und nach an" if self.autocal == "auto"
                          else "; mit kalibriertem Offset verschwindet der Hinweis"))
        elif strong:
            ft.text = (f"chrony hält das GPS seit {int((now - ft.since) // 60)} min für einen Falseticker "
                       f"– {last.get('references')} NTS-Quellen sind sich einig"
                       + (f", die GPS-Zeit weicht {fmt_ms(diff)} vom Netz ab" if diff is not None else ""))
        elif self._ft_excused and diff is not None and abs(diff) >= TIME_THRESHOLD_MIN:
            # Für den Text der ruhigere Wert: Median der letzten 30 min, sobald es ihn gibt.
            typical = _num(last.get("time_base_median")) if last.get("time_baseline") else None
            diff = diff if typical is None else typical
            sign = "+" if diff > 0 else "−"
            where = (f"GPS liegt seit dem Start bzw. der letzten Änderung der GPS-Einstellungen gleichbleibend "
                     f"rund {sign}{fmt_ms(diff)} neben dem Netz")
            fix = ("die automatische Kalibrierung korrigiert das nach einigen Stunden Messung selbst "
                   "(Plan: GPS-Seite → „GPS kalibrieren“)" if self.autocal == "auto"
                   else "Offset kalibrieren (GPS-Seite → „GPS kalibrieren“)")
            if nts:
                ft.text = (f"{where} – vermutlich ein Kalibrierfehler, keine Störung: {fix}; stimmt der Versatz "
                           "danach nicht, Antenne und Umgebung prüfen")
            else:
                ft.text = (f"{where} – {fix}; stimmt der Versatz danach nicht, Antenne und Umgebung prüfen "
                           "(ohne zwei NTS-Quellen ist der Vergleich weniger sicher)")
        else:
            ft.text = "chrony hält das GPS für einen Falseticker (die Netzquellen sind sich einig)"
        ft.strength = "strong" if strong else "weak"

    def active(self) -> list[_Signal]:
        return [s for s in self.signals.values() if s.active]

    def stage(self) -> str:
        active = self.active()
        if any(s.strength == "strong" for s in active):
            return "stoerung"
        weak = sum(1 for s in active if s.strength == "weak")
        return "warnung" if weak >= 2 else "hinweis" if weak == 1 else "ok"


# =========================================================================================
# Beobachtung aus gpsd + chrony
# =========================================================================================

def observation(now: float, gps_state: dict | None, sources: list[dict] | None, select: dict[str, dict] | None,
                refid: str, position: tuple | None = None) -> dict[str, Any]:
    """Baut eine Beobachtung aus gps.status(), chronyc sources und selectdata."""
    obs: dict[str, Any] = {"t": now}
    gps_state = gps_state or {}
    if gps_state.get("running"):
        obs["mode"] = gps_state.get("mode")
        sats: dict[str, float] = {}
        for sat in gps_state.get("satellites") or []:
            if not isinstance(sat, dict):
                continue
            snr = _num(sat.get("snr"))
            if snr is None or sat.get("prn") is None:
                continue
            sats[f"{sat.get('system') or '?'}:{sat.get('prn')}"] = snr
        obs["sats"] = sats or None
        used = _num(gps_state.get("satellites_used"))
        if used is not None and used <= 0:
            # 0 heißt hier „unbekannt“ (kein SKY im Abfragefenster, NMEA ohne GSA) – kein Fix kommt
            # mit 0 Satelliten aus. Sonst wäre die Positionsprüfung still dauerhaft aus.
            used = None
        obs["used"] = used
        obs["hdop"] = _num(gps_state.get("hdop"))
        if position and obs.get("mode") == 3:
            obs["pos"] = position
    select = select or {}
    refs_auth, refs_all = [], []
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        name = src.get("name")
        # chrony 4.6 zeigt abgewählte Quellen (noselect: GPS-Sperre, Holdover-Test) in „sources“
        # mit Zustand „?“, misst sie aber weiter. Gemessen heißt darum: Erreichbarkeitsregister ≠ 0.
        state = src.get("state")
        if state == "?" and src.get("reach"):
            state = "-"
        if src.get("mode") == "#" and name == refid:
            obs["gps_offset"] = _num(src.get("offset"))
            obs["gps_state"] = state if src.get("reach") else "?"
            continue
        if src.get("mode") == "#" and name == PPS_REFID:
            obs["pps_state"] = state if src.get("reach") else "?"
            continue
        if src.get("mode") not in {"^", "="}:
            continue
        if state in {"x", "~"} or not src.get("reach"):
            continue
        offset = _num(src.get("offset"))
        if offset is None:
            continue
        refs_all.append(offset)
        if (select.get(name) or {}).get("authenticated"):
            refs_auth.append(offset)
    if len(refs_auth) >= TIME_MIN_NTS:
        obs["refs"], obs["ref_kind"] = refs_auth, "nts"
    else:
        obs["refs"], obs["ref_kind"] = refs_all, "ntp"
    return obs


# =========================================================================================
# Gespeicherter Zustand (SQLite)
# =========================================================================================

_READY: dict[str, Any] = {"for": None}


def _ensure() -> None:
    key = store.path()
    if _READY["for"] != key:
        store.migrate("gnssguard", _SCHEMA)
        _READY["for"] = key


def load(key: str) -> dict[str, Any]:
    try:
        _ensure()
        rows = store.query("SELECT json FROM gnss_state WHERE key = ?", (key,))
        value = json.loads(rows[0][0]) if rows else {}
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def save(key: str, value: dict[str, Any]) -> None:
    _ensure()
    store.execute("INSERT INTO gnss_state(key, json) VALUES(?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET json = excluded.json",
                  (key, json.dumps(value, separators=(",", ":"))))


# =========================================================================================
# Wächter: Erkennung + Ereignisse + Sperre
# =========================================================================================

def _holdover_running() -> bool:
    """Läuft gerade ein Holdover-Test (er wählt GPS selbst ab)? Wirft nie."""
    try:
        import holdover
        return holdover.TEST.running()
    except Exception:
        return False


def _default_emit(kind: str, level: str, title: str, data: dict) -> None:
    import events
    events.emit(kind, level, title, data)


class Guard:
    def __init__(self, emit: Callable[..., Any] | None = None, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._emit_fn = emit
        self.clock = clock
        self.wall = wall
        self.lock = threading.RLock()
        self.detector = Detector()
        self.stage = "ok"
        self.episode: dict[str, Any] | None = None
        self.calm_since: float | None = None
        self.state: dict[str, Any] | None = None    # Sperre, aus SQLite
        self.last_error: str | None = None
        self.last_tick: float | None = None
        self.enabled = False
        self.other_sources: int | None = None       # andere auswählbare Netzquellen (letzte Prüfung)
        self._skip_noted: bool | str = False         # „Sperre ausgelassen“ nur einmal je Episode („holdover“: im Test)
        self._anchor_fp: str | None = None           # GPS-Einstellungen, zu denen der Zeitanker gehört
        self._anchor_saved: float | None = None
        self._anchor_saved_key: tuple = (None,)
        self._alarm_wall: float | None = None        # zuletzt „Warnung“/„Störung“ (Wanduhr, für autocal)
        self._alarm_stage: str | None = None         # höchste Stufe dabei
        self._alarm_saved: float | None = None
        self._relearn_wall: float | None = None      # letztes „Neu lernen“ (Wanduhr, für autocal)
        self._relearn_loaded = False
        self._freerun_since: float | None = None     # gesperrt und keine andere Quelle seit (monotone Uhr)

    # --- Ereignisse --------------------------------------------------------------------------
    def _emit(self, level: str, title: str, data: dict) -> None:
        try:
            (self._emit_fn or _default_emit)("gps", level, title, data)
        except Exception:
            pass

    # --- Sperre: Zustand ---------------------------------------------------------------------
    def _lock_state(self) -> dict[str, Any]:
        if self.state is None:
            state = load("lock")
            self.state = {"locked": bool(state.get("locked")), "since": _num(state.get("since")),
                          "manual": bool(state.get("manual")), "auto_release": bool(state.get("auto_release")),
                          "reason": str(state.get("reason") or ""), "targets": [
                              t for t in state.get("targets") or [] if selectctl.valid_name(t)],
                          "repeats": int(state.get("repeats") or 0), "series_t": _num(state.get("series_t")),
                          "auto_releases": int(state.get("auto_releases") or 0),
                          "suppress": bool(state.get("suppress")),
                          "freerun_noted": bool(state.get("freerun_noted")),
                          "added": [t for t in state.get("added") or [] if selectctl.valid_name(t)]}
            if self.state["locked"]:
                selectctl.register(LOCK_OWNER, self.state["targets"], self.state["added"])
        return self.state

    def _save_lock(self) -> None:
        state = self._lock_state()
        state["added"] = sorted(selectctl.added(LOCK_OWNER)) if state["locked"] else []
        try:
            save("lock", self._lock_state())
        except Exception as exc:
            self.last_error = f"Zustand der Sperre nicht gespeichert: {exc}"

    @staticmethod
    def targets(select: dict[str, dict], refid: str) -> list[str]:
        """GPS-Refclock und ein PPS, das an ihm hängt (gefälschte Zeit verschiebt auch den Impuls)."""
        return [name for name in (refid, "PPS") if name in select]

    @staticmethod
    def count_others(select: dict[str, dict] | None, sources: list[dict] | None, exclude: set[str]) -> int:
        """Erreichbare, auswählbare Netzquellen außer den zu sperrenden – bleibt nach der Sperre
        etwas, woran sich chrony halten kann?"""
        count = 0
        for src in sources or []:
            if not isinstance(src, dict) or src.get("mode") not in {"^", "="}:
                continue
            name = src.get("name")
            if name in exclude or not src.get("reach") or src.get("state") in {"x", "~"}:
                continue
            if select and selectctl.effective_noselect(select.get(name)):
                continue
            count += 1
        return count

    @staticmethod
    def _fetch_sources() -> list[dict] | None:
        try:
            return selectctl.port().sources()
        except Exception:
            return None

    def do_lock(self, cfg: dict, reason: str, manual: bool, auto_release: bool = False,
                select: dict[str, dict] | None = None, force: bool = False,
                sources: list[dict] | None = None) -> dict[str, Any]:
        with self.lock:
            state = self._lock_state()
            if state["locked"]:
                raise GuardError("Das GPS ist schon gesperrt.", conflict=True)
            if not cfg.get("gps_enable"):
                raise GuardError("GPS ist ausgeschaltet – es gibt nichts zu sperren.", conflict=True)
            select = selectctl.by_name(selectctl.port().selectdata()) if select is None else select
            refid = str(cfg.get("gps_refid") or "GPS")
            targets = self.targets(select, refid)
            if not targets:
                raise GuardError(f"chrony kennt keine Quelle „{refid}“ – läuft chronyd, ist das GPS eingesteckt?",
                                 conflict=True)
            sources = self._fetch_sources() if sources is None else sources
            if sources is not None:
                self.other_sources = self.count_others(select, sources, set(targets))
            if manual and not force and self.other_sources == 0:
                raise GuardError("Keine andere auswählbare Zeitquelle – ohne GPS liefe die Uhr frei (Holdover) und "
                                 "driftet mit der Zeit weg. Sperren nur mit ausdrücklicher Bestätigung "
                                 "(„Trotzdem sperren“).", conflict=True)
            try:
                selectctl.hold(LOCK_OWNER, targets, select)
            except selectctl.SelectError as exc:
                raise GuardError(f"chronyc selectopts ging nicht: {exc}", conflict=True) from exc
            now = self.wall()
            state.update(locked=True, since=now, manual=manual, auto_release=auto_release, reason=reason,
                         targets=targets, suppress=False, freerun_noted=False)
            self._freerun_since = None
            if not manual:
                state["series_t"] = now
            self._save_lock()
            names = " und ".join(targets)
            if manual:
                self._emit("info", f"GPS von Hand gesperrt – chrony nutzt {names} nicht mehr",
                           {"subject": "gps-sperre", "targets": targets, "manual": True, "resolves": False})
            else:
                rest = ("Freigabe nach 30 min ohne Störungssignal" if auto_release
                        else f"nach {MAX_AUTO_RELEASES} automatischen Freigaben bleibt die Sperre bis zur Freigabe von Hand")
                self._emit("warn", f"GPS automatisch gesperrt: {reason} – {rest}",
                           {"subject": "gps-sperre", "targets": targets, "manual": False,
                            "auto_release": auto_release, "repeat": state["repeats"]})
            return self.lock_status()

    def do_unlock(self, reason: str, manual: bool, select: dict[str, dict] | None = None) -> dict[str, Any]:
        with self.lock:
            state = self._lock_state()
            if not state["locked"]:
                if manual:
                    raise GuardError("Das GPS ist nicht gesperrt.", conflict=True)
                return self.lock_status()
            released, failed = selectctl.release(LOCK_OWNER, select)
            if failed:
                raise GuardError("Freigabe ging nicht – chronyd antwortet nicht. Wird beim nächsten Durchgang "
                                 "erneut versucht.", conflict=True)
            if manual:
                state.update(repeats=0, auto_releases=0)
                # Läuft die Störung noch, nicht sofort wieder automatisch sperren: Wer von Hand
                # freigibt, hat entschieden. Erst nach einer ruhigen Phase sperrt die Automatik wieder.
                state["suppress"] = self.stage != "ok"
            elif state["auto_release"]:
                state["auto_releases"] += 1
            duration = max(0.0, self.wall() - (state["since"] or self.wall()))
            state.update(locked=False, since=None, manual=False, auto_release=False, reason="", targets=[],
                         freerun_noted=False)
            self._freerun_since = None
            self._save_lock()
            self._emit("info", f"GPS-Sperre aufgehoben – {reason}",
                       {"subject": "gps-sperre", "released": released, "manual": manual,
                        "duration_s": round(duration), "resolves": True})
            return self.lock_status()

    def maintain(self, select: dict[str, dict]) -> list[str]:
        """Sperre nach einem Neustart von chronyd erneuern (Laufzeitschalter gehen dabei verloren)."""
        with self.lock:
            state = self._lock_state()
            if not state["locked"] or not select:
                return []
            try:
                renewed = selectctl.reapply(LOCK_OWNER, select)
            except selectctl.SelectError as exc:
                self.last_error = f"Sperre nicht erneuert: {exc}"
                return []
            if renewed:
                self._save_lock()
                self._emit("info", f"GPS-Sperre nach Neustart von chronyd erneuert ({', '.join(renewed)})",
                           {"subject": "gps-sperre-erneuert", "targets": renewed, "resolves": False})
            return renewed

    def lock_status(self) -> dict[str, Any]:
        state = self._lock_state()
        out = {k: state[k] for k in ("locked", "since", "manual", "auto_release", "reason", "targets")}
        out.update(auto_releases=state["auto_releases"], max_auto_releases=MAX_AUTO_RELEASES,
                   release_after_s=RELEASE_AFTER, other_sources=self.other_sources)
        if state["locked"] and state["auto_release"] and self.calm_since is not None:
            out["release_in_s"] = max(0, round(RELEASE_AFTER - (self.clock() - self.calm_since)))
        return out

    # --- Erkennung ----------------------------------------------------------------------------
    def _signal_texts(self) -> list[str]:
        order = sorted(self.detector.active(), key=lambda s: (s.strength != "strong", s.key))
        return [s.text for s in order if s.text]

    def _stage_event(self, stage: str, cfg: dict) -> None:
        texts = self._signal_texts()
        label = {"hinweis": "GNSS-Hinweis", "warnung": "GNSS-Warnung", "stoerung": "GNSS-Störung"}[stage]
        threshold = {"stoerung": 3, "warnung": 2, "hinweis": 1}.get(str(cfg.get("gnss_notify") or "stoerung"), 3)
        data: dict[str, Any] = {"subject": "gnss", "stage": stage,
                                "signals": [s.key for s in self.detector.active()],
                                "notify": stage_rank(stage) >= threshold}
        for signal in self.detector.active():
            for key, value in signal.detail.items():
                if key in {"deviation_m", "deviation_ms", "drop_db", "satellites", "references", "stdev_db"}:
                    data[f"{signal.key}_{key}"] = value
        self._emit(STAGE_LEVEL[stage], f"{label}: {'; '.join(texts) or SIGNALS[data['signals'][0]][1]}", data)

    def tick(self, cfg: dict, obs: dict | None = None, select: dict[str, dict] | None = None,
             sources: list[dict] | None = None) -> dict[str, Any]:
        """Ein Durchgang: beobachten, Stufe bestimmen, Ereignisse, Sperre. Wirft nie.

        chronyc und gpsd werden **vor** dem Sperren von self.lock abgefragt: Antwortet chronyd
        langsam (Neustart, bis 5 s je Aufruf), soll /api/status (status()) nicht mitwarten."""
        mode = str(cfg.get("gnss_guard") or "report")
        enabled = bool(cfg.get("gps_enable")) and mode != "off"
        now = self.clock()
        try:
            locked = self._lock_state()["locked"]
            if select is None and (locked or enabled):
                select = selectctl.by_name(selectctl.port().selectdata())
            if enabled and obs is None:
                if sources is None:
                    sources = selectctl.port().sources()
                obs = live_observation(cfg, now, select, sources)
        except Exception as exc:
            self.last_error = str(exc)
            return {"error": str(exc)}
        with self.lock:
            try:
                return self._tick(cfg, obs, select, sources, now)
            except Exception as exc:  # die Erkennung darf nichts anderes stören
                self.last_error = str(exc)
                return {"error": str(exc)}

    def _housekeeping(self, state: dict, select: dict[str, dict]) -> None:
        """Haltertabelle und Sperrzustand in Einklang halten (nach Abstürzen, Übergaben)."""
        orphans = selectctl.reconcile(select)
        if orphans:
            self._emit("info", f"Übrig gebliebene Abwahl aufgehoben ({', '.join(orphans)}) – keine Sperre aktiv",
                       {"subject": "gps-sperre", "released": orphans, "resolves": False})
        if not state["locked"] and selectctl.held(LOCK_OWNER):
            released, _failed = selectctl.release(LOCK_OWNER, select)
            if released:
                self._emit("info", f"Übrig gebliebene GPS-Sperre aufgehoben ({', '.join(released)})",
                           {"subject": "gps-sperre", "released": released, "resolves": False})

    def _anchor_prepare(self, cfg: dict) -> None:
        """Zeitanker laden (Neustart) bzw. verwerfen, wenn sich die GPS-Einstellungen geändert haben."""
        fp = json.dumps([cfg.get(k) for k in ANCHOR_KEYS], sort_keys=True, default=str)
        if self._anchor_fp is None:
            self._anchor_fp = fp
            stored = load("time_anchor")
            value, saved = _num(stored.get("value")), _num(stored.get("wall"))
            if (stored.get("fp") == fp and value is not None and saved is not None
                    and 0.0 <= self.wall() - saved <= TIME_ANCHOR_MAX_AGE):
                self.detector.seed_time_anchor(value, stored.get("start"), stored.get("epoch_good"),
                                               stored.get("excuse"))
        elif fp != self._anchor_fp:
            self._anchor_fp = fp
            self.detector.reset_time()
            self._store_anchor(None)
            self._emit("info", "GPS-Einstellungen geändert – der gewohnte Zeitabstand GPS ↔ Netz wird neu gelernt",
                       {"subject": "gnss-grundlinie", "resolves": False})

    @staticmethod
    def _anchor_key(record: dict | None) -> tuple:
        """Was sofort gespeichert werden muss, wenn es sich ändert (nicht erst nach 10 min)."""
        if not record:
            return (None,)
        return (record.get("start"), record.get("excuse"), record.get("epoch_good", 0.0) >= FALSETICKER_SETTLED_S)

    def _store_anchor(self, record: dict | None) -> None:
        self._anchor_saved = None if record is None else self.clock()
        self._anchor_saved_key = self._anchor_key(record)
        try:
            save("time_anchor", dict(record or {"value": None}, wall=self.wall(), fp=self._anchor_fp))
        except Exception as exc:
            self.last_error = f"Zeitanker nicht gespeichert: {exc}"

    def _tick(self, cfg: dict, obs: dict | None, select: dict[str, dict] | None,
              sources: list[dict] | None, now: float) -> dict[str, Any]:
        mode = str(cfg.get("gnss_guard") or "report")
        self.last_tick = now
        state = self._lock_state()
        if select:
            self._housekeeping(state, select)
            self.maintain(select)
            if sources is not None:   # für die Oberfläche: Bleibt nach einer Sperre noch eine Quelle?
                refid = str(cfg.get("gps_refid") or "GPS")
                self.other_sources = self.count_others(select, sources, set(self.targets(select, refid)))
        self._check_freerun(state, now)
        self.enabled = bool(cfg.get("gps_enable")) and mode != "off"
        if not self.enabled:
            if self.stage != "ok":
                self._finish_episode("Störungserkennung ausgeschaltet")
            self.detector = Detector()
            self._anchor_fp = None          # beim Einschalten den gespeicherten Anker neu laden
            self.calm_since = None
            if state["locked"] and not state["manual"]:
                self._safe_unlock("die automatische Sperre ist ausgeschaltet", select)
            return {"stage": "ok", "enabled": False}
        self._anchor_prepare(cfg)
        try:
            import gpsquality
            self.detector.pps = gpsquality.has_pps(cfg)
        except Exception:
            self.detector.pps = False
        self.detector.autocal = str(cfg.get("gps_autocal") or "off")
        result = self.detector.update(obs if obs is not None else {"t": now})
        record = self.detector.anchor_record()
        if record is not None and (self._anchor_saved is None or now - self._anchor_saved >= TIME_ANCHOR_SAVE_EVERY
                                   or self._anchor_key(record) != self._anchor_saved_key):
            self._store_anchor(record)
        stage = result["stage"]
        if stage_rank(stage) > stage_rank(self.stage):
            if self.episode is None:
                self.episode = {"since": self.wall(), "mono": now, "max": stage}
            self.episode["max"] = max(self.episode["max"], stage, key=stage_rank)
            self._stage_event(stage, cfg)
        elif stage == "ok" and self.stage != "ok":
            stale = [k for k, c in result["changes"].items() if c == "off" and self.detector.signals[k].stale]
            self.stage = stage
            self._finish_episode("keine Messwerte mehr (kein 3D-Fix oder GPS-Quelle unerreichbar) – der Befund "
                                 "lässt sich nicht mehr prüfen" if stale
                                 else "alle Signale seit einigen Minuten unauffällig")
        self.stage = stage
        if stage_rank(stage) >= stage_rank("warnung"):
            self._note_alarm()
        self.calm_since = (self.calm_since or now) if stage == "ok" else None
        if stage == "ok":
            state["suppress"] = False
        self._auto_lock(cfg, mode, select, sources)
        return {"stage": stage, "enabled": True, "changes": result["changes"]}

    def _check_freerun(self, state: dict, now: float) -> None:
        """1.5.4: GPS gesperrt und seit FREERUN_ALERT keine andere auswählbare Quelle – die Uhr läuft
        frei (Holdover) und driftet weg. Einmal je Sperre „crit“ mit Benachrichtigung. Ein laufender
        Holdover-Test (wählt selbst alles ab) zählt nicht mit; eine wieder erreichbare Quelle setzt
        die Uhr zurück. Die Frist läuft auf der monotonen Uhr; nach einem Neustart beginnt sie neu."""
        if not state["locked"] or self.other_sources is None or _holdover_running():
            self._freerun_since = None
            return
        if self.other_sources > 0:
            self._freerun_since = None
            return
        if self._freerun_since is None:
            self._freerun_since = now
            return
        if state.get("freerun_noted") or now - self._freerun_since < FREERUN_ALERT:
            return
        state["freerun_noted"] = True
        self._save_lock()
        names = " und ".join(state.get("targets") or []) or "GPS"
        hours = round((now - self._freerun_since) / 3600.0)
        how = "von Hand" if state.get("manual") else "automatisch"
        self._emit("crit", f"GPS gesperrt, Uhr läuft frei: {names} seit über {hours} h {how} gesperrt und "
                           "keine andere auswählbare Zeitquelle – die Uhr driftet. Sperre aufheben (GNSS-Seite) "
                           "oder eine Netzquelle erreichbar machen.",
                   {"subject": "gps-sperre", "freerun": True, "hours": hours, "manual": bool(state.get("manual")),
                    "resolves": False})

    def _note_alarm(self) -> None:
        """Merkt sich (in SQLite, höchstens alle 10 min geschrieben), wann zuletzt „Warnung“ oder
        „Störung“ war – und die höchste Stufe dieser Episode."""
        wall = self.wall()
        new_episode = self._alarm_wall is None or wall - self._alarm_wall > TIME_ANCHOR_SAVE_EVERY
        stronger = new_episode or stage_rank(self.stage) > stage_rank(self._alarm_stage or "ok")
        self._alarm_wall = wall
        if stronger:
            self._alarm_stage = self.stage
        if stronger or self._alarm_saved is None or wall - self._alarm_saved >= TIME_ANCHOR_SAVE_EVERY:
            self._alarm_saved = wall
            try:
                save("last_alarm", {"wall": wall, "stage": self._alarm_stage})
            except Exception as exc:
                self.last_error = f"Störungszeitpunkt nicht gespeichert: {exc}"

    def _last_alarm(self) -> tuple[float | None, str | None]:
        if self._alarm_wall is not None:
            return self._alarm_wall, self._alarm_stage
        try:
            stored = load("last_alarm")
            legacy = _num(load("last_stoerung").get("wall"))   # bis 1.5.1-Entwicklungsstand
        except Exception:
            return None, None
        wall, stage = _num(stored.get("wall")), stored.get("stage")
        if legacy is not None and (wall is None or legacy >= wall):
            wall, stage = legacy, "stoerung"
        return wall, stage if stage in STAGES else "stoerung"

    def relearned_at(self) -> float | None:
        """Wann zuletzt „Neu lernen“ gedrückt wurde (Wanduhr) oder None. Die automatische Kalibrierung
        beginnt dort ihre Messung neu: Ein Mensch hat bestätigt, dass der neue Abstand GPS ↔ Netz echt
        ist (Empfänger oder Antenne gewechselt) – ohne das hielte eine Störung davor sie bis zu 24 h auf,
        und das Messfenster mischte alten und neuen Abstand."""
        with self.lock:
            if not self._relearn_loaded:
                self._relearn_loaded = True
                try:
                    self._relearn_wall = _num(load("relearn").get("wall"))
                except Exception:
                    self._relearn_wall = None
            return self._relearn_wall

    def calibration_hold(self, since_wall: float | None) -> str | None:
        """Darf die automatische Kalibrierung den Offset jetzt ändern? None = ja, sonst der Grund.

        Nein, solange die GPS-Sperre gilt, gerade „Warnung“ oder „Störung“ gemeldet wird, gerade
        unnatürlich gleichmäßige Signale anschlagen (ein Spoofer sendet alle Signale aus einer
        Antenne) oder seit Beginn des Messzeitraums (since_wall, Wanduhr) „Warnung“ oder „Störung“
        war – sonst könnte sie einen Spoofer, der die Zeit gleichbleibend verschiebt, als Offset
        „einrechnen“ (der Zeitanker würde dabei neu gelernt, die Sperre löste sich). Ein einzelner
        schwacher Hinweis (z. B. Falseticker nach „Offset zurücksetzen“) hält sie nicht auf – genau
        den soll sie ja beheben."""
        with self.lock:
            try:
                if self._lock_state().get("locked"):
                    return "die GPS-Sperre der GNSS-Störungserkennung ist aktiv"
            except Exception:
                pass
            if any(s.strength == "strong" for s in self.detector.active()):
                return "die GNSS-Störungserkennung meldet gerade eine Störung"
            if self.detector.stage() == "warnung":
                return "die GNSS-Störungserkennung meldet gerade eine Warnung"
            if self.detector.signals["uniform"].active:
                return "die GNSS-Störungserkennung meldet gerade unnatürlich gleichmäßige Signale"
            last, stage = self._last_alarm()
            if last is not None and (since_wall is None or last >= since_wall):
                what = "eine Störung" if stage == "stoerung" else "eine Warnung"
                return f"im Messzeitraum meldete die GNSS-Störungserkennung {what}"
        return None

    def _finish_episode(self, why: str) -> None:
        episode = self.episode or {}
        duration = max(0.0, self.wall() - episode.get("since", self.wall()))
        self._emit("info", "GNSS wieder unauffällig",
                   {"subject": "gnss", "stage": "ok", "max_stage": episode.get("max"), "duration_s": round(duration),
                    "resolves": True, "why": why})
        self.episode = None
        self.stage = "ok"
        self._skip_noted = False

    def _safe_unlock(self, reason: str, select: dict | None) -> None:
        try:
            self.do_unlock(reason, manual=False, select=select)
        except GuardError as exc:
            self.last_error = str(exc)

    def _auto_lock(self, cfg: dict, mode: str, select: dict | None, sources: list[dict] | None = None) -> None:
        state = self._lock_state()
        if state["locked"] and not state["manual"] and mode != "lock":
            self._safe_unlock("die automatische Sperre ist ausgeschaltet (Einstellung „nur melden“)", select)
            return
        strong = [s for s in self.detector.active() if s.strength == "strong"]
        if mode == "lock" and strong and not state["locked"] and not state["suppress"]:
            # Nur sperren, wenn chrony danach noch etwas hat, woran es sich halten kann. Ein
            # GPS-only-Server (isoliertes Netz) liefe sonst ohne jede Quelle frei – womöglich wegen
            # eines Fehlalarms der Position bei schwachem Empfang.
            sources = self._fetch_sources() if sources is None else sources
            if select:
                refid = str(cfg.get("gps_refid") or "GPS")
                self.other_sources = (None if sources is None else
                                      self.count_others(select, sources, set(self.targets(select, refid))))
            if self.other_sources is None or self.other_sources < AUTO_LOCK_MIN_OTHERS:
                testing = _holdover_running()
                if self._skip_noted == "holdover" and not testing:
                    self._skip_noted = False   # während des Tests nur als „info“ gemeldet – jetzt ernst
                if not self._skip_noted:
                    self._skip_noted = "holdover" if testing else True
                    have = "unbekannt (chronyd antwortet nicht)" if self.other_sources is None else self.other_sources
                    self._emit("warn", f"GPS-Sperre ausgelassen: keine andere Zeitquelle – ohne GPS liefe die Uhr frei "
                                       f"(andere auswählbare Netzquellen: {have}, nötig: {AUTO_LOCK_MIN_OTHERS})",
                               {"subject": "gps-sperre-ausgelassen", "others": self.other_sources, "resolves": False})
                return
            if state["series_t"] is not None and self.wall() - state["series_t"] > SERIES_RESET:
                state.update(repeats=0, auto_releases=0)
            state["repeats"] += 1
            auto_release = state["auto_releases"] < MAX_AUTO_RELEASES
            reason = strong[0].text or strong[0].label
            try:
                self.do_lock(cfg, reason, manual=False, auto_release=auto_release, select=select, sources=sources)
            except GuardError as exc:
                state["repeats"] -= 1
                self.last_error = str(exc)
            return
        if (state["locked"] and state["auto_release"] and self.calm_since is not None
                and self.clock() - self.calm_since >= RELEASE_AFTER):
            self._safe_unlock("30 min ohne Störungssignal", select)

    # --- Anzeige -------------------------------------------------------------------------------
    def status(self, cfg: dict) -> dict[str, Any]:
        with self.lock:
            mode = str(cfg.get("gnss_guard") or "report")
            last = self.detector.last
            deviation = last.get("time_deviation")
            return {
                "enabled": bool(cfg.get("gps_enable")) and mode != "off",
                "gps_enable": bool(cfg.get("gps_enable")),
                "mode": mode, "notify": str(cfg.get("gnss_notify") or "stoerung"),
                "stage": self.stage, "stage_label": STAGE_LABELS[self.stage],
                "since": (self.episode or {}).get("since"),
                "signals": [s.public() for s in self.detector.signals.values()],
                "time": {"deviation_ms": None if deviation is None else round(deviation * 1000.0, 1),
                         "threshold_ms": None if last.get("time_threshold") is None
                         else round(last["time_threshold"] * 1000.0, 1),
                         "baseline": bool(last.get("time_baseline")),
                         "references": last.get("references"), "ref_kind": last.get("ref_kind")},
                "position": {"learned": bool(last.get("position_learned")),
                             "deviation_m": last.get("position_deviation_m")},
                "cn0": {"drop_db": last.get("cn0_drop_db"), "satellites": last.get("cn0_satellites"),
                        "stdev_db": last.get("cn0_stdev_db"), "recurring_shadow": last.get("cn0_recurring")},
                "lock": self.lock_status(),
                "error": self.last_error,
            }

    def action(self, cfg: dict, data: dict) -> dict[str, Any]:
        """POST /api/gnss: {"action": "lock"|"unlock"|"relearn"}."""
        action = str((data or {}).get("action") or "")
        if action == "lock":
            self.do_lock(cfg, "von Hand", manual=True, force=(data or {}).get("force") is True)
        elif action == "unlock":
            self.do_unlock("von Hand freigegeben", manual=True)
        elif action == "relearn":
            with self.lock:
                self.detector.reset_baselines()
                self._store_anchor(None)
                self._relearn_wall, self._relearn_loaded = self.wall(), True
                try:
                    save("relearn", {"wall": self._relearn_wall})
                except Exception as exc:
                    self.last_error = f"Zeitpunkt von „Neu lernen“ nicht gespeichert: {exc}"
                if self.stage != "ok":
                    self._finish_episode("Grundlinien neu gelernt")
                self._emit("info", "GNSS-Störungserkennung lernt Position und Zeitabstand neu",
                           {"subject": "gnss-grundlinie", "resolves": False})
        else:
            raise GuardError("action muss „lock“, „unlock“ oder „relearn“ sein")
        return self.status(cfg)


# =========================================================================================
# Live-Betrieb
# =========================================================================================

def live_observation(cfg: dict, now: float, select: dict[str, dict] | None,
                     sources: list[dict] | None = None) -> dict[str, Any]:
    import gps
    status = gps.status() if cfg.get("gps_enable") else {}
    position = gps.private_position(max_age=POS_FRESH)
    sources = selectctl.port().sources() if sources is None else sources
    return observation(now, status, sources, select, str(cfg.get("gps_refid") or "GPS"), position)


GUARD = Guard()


def run(cfg_fn: Callable[[], dict], stop: threading.Event | None = None, interval: float = INTERVAL) -> None:
    """Eigener Thread: Erkennung, Sperre und Holdover-Test im festen Takt (wirft nie)."""
    import holdover
    stop = stop or threading.Event()
    if stop.wait(5.0):
        return
    while True:
        try:
            cfg = cfg_fn()
            # chronyc einmal je Durchgang, außerhalb der Sperren der beiden Module.
            port = selectctl.port()
            select = selectctl.by_name(port.selectdata())
            sources = port.sources() if select else []
            holdover.TEST.tick(cfg, select, sources)       # zuerst: erkennt einen Neustart von chronyd
            GUARD.tick(cfg, select=select, sources=sources)
        except Exception as exc:
            print(f"[web] GNSS-Prüfung fehlgeschlagen: {exc}", flush=True)
        if stop.wait(interval):
            return


def insights(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Hinweise für die Übersicht: laufende Störung (ab „Warnung“) und eine aktive GPS-Sperre."""
    out: list[dict[str, Any]] = []
    stage = status.get("stage")
    if stage in {"warnung", "stoerung"}:
        texts = [s.get("text") for s in status.get("signals") or [] if s.get("active") and s.get("text")]
        out.append({"level": "crit" if stage == "stoerung" else "warn", "key": "gnss_stage", "action": "gps",
                    "title": "GNSS-Störung erkannt" if stage == "stoerung" else "GNSS-Empfang auffällig",
                    "text": ("; ".join(texts) or "Mehrere Signale schlagen an")
                    + ". Die GPS-Seite zeigt die Befunde – bei „Störung“ ist das GPS als Zeitquelle verdächtig."})
    lock = status.get("lock") or {}
    if lock.get("locked"):
        how = "von Hand" if lock.get("manual") else "automatisch"
        others = lock.get("other_sources")
        rest = ("hält sich an die Netzquellen." if others is None or others > 0
                else "hat gerade keine andere auswählbare Quelle – die Uhr läuft frei und driftet mit der Zeit.")
        out.append({"level": "warn", "key": "gnss_lock", "action": "gps", "title": f"GPS {how} gesperrt",
                    "text": f"chrony nutzt das GPS gerade nicht (selectopts noselect) und {rest} "
                            + ("Freigabe automatisch nach 30 min ohne Störung."
                               if lock.get("auto_release") else "Freigabe auf der GPS-Seite.")})
    return out
