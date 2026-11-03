"""GPS ohne PPS und schwacher Empfang (1.5): Empfangsbewertung, ehrliche Fehlerschranke,
Rolle des GPS und Antennen-Test.

Ausgangslage (Konzept 1.5, Thema 3; Entscheidung E16): Ein USB-Empfänger wie der VK-162
liefert die Zeit nur als NMEA-Zeile – ohne PPS. Sie schwankt um einige bis einige zehn
Millisekunden. Mit gutem Internet sind NTS-Quellen meist genauer, ohne Internet (oder mit
wackeligem Mobilfunk) ist das GPS die bessere oder einzige Quelle. Darum bleibt das GPS
eine Zeitquelle, aber als **Rückfallebene**: chrony bekommt eine ehrliche Fehlerschranke
(Refclock-Option „delay“, aus der gemessenen Streuung), wählt so die guten Netzquellen
und nimmt das GPS von selbst, wenn das Netz schlecht wird oder ausfällt. „Nur beobachten“
(noselect) bleibt eine bewusste Wahl in den Einstellungen – nie Standard, nie Automatik.

Bausteine:
  * cn0_top4(satellites)       Median-C/N0 der vier stärksten Satelliten (je gpsd-Abfrage)
  * assess(samples, now)       Empfangsbewertung über 24 h aus dem Verlauf → Ampel + Satz
  * spread(diffs)/measure(...) Streuung GPS − Netz und die daraus folgende Fehlerschranke
  * refclock_values(cfg)       delay/precision, die confgen in die GPS-Zeile schreibt
  * maybe_tick(...)            stündlich: Schranke messen, bei deutlicher Änderung anwenden
  * role(cfg, sources)         welche Rolle das GPS gerade spielt (für GPS-Seite, Hardware)
  * Antennen-Test              5 Minuten messen, umstellen, erneut messen, vergleichen

Offset-Änderung (1.5.1): Die Schranke misst GPS − Netz, und darin steckt der eingestellte
gps_offset. Ändert er sich (von Hand, „Auf Standard zurücksetzen“ oder durch die automatische
Kalibrierung), passen ältere Messpunkte nicht mehr zur laufenden Konfiguration. Gewählt ist die
einfachere sichere Variante: **Gemessen wird nur ab der letzten Offset-Änderung** (plus
OFFSET_SETTLE für den Neustart von chronyd) – alte Werte werden nicht umgerechnet. Den Zeitpunkt
merkt sich note_offset() (aus der Messschleife, bei jedem Messpunkt; nur ein Vergleich im
Speicher, geschrieben wird nur bei einer Änderung). Die 12-h-Sperre fürs Verkleinern gilt nach
einer Offset-Änderung als erfüllt, sobald OFFSET_SHRINK_MIN (2 h) Messung danach vorliegt – die
alte Schranke beruhte ja auf dem alten Offset. Größer wird sie wie immer höchstens stündlich.
Dieselbe Grenze nutzt der Kalibrier-Assistent (/api/gps/calibration): Er mischt keine Werte
vor und nach einer Offset-Änderung mehr.

Sicherheit und Umkehrbarkeit: Größer wird die Schranke, sobald die gemessene Streuung die
eingestellte übersteigt (höchstens ein Mal je Stunde, mit etwas Reserve – das GPS ist dann
schlechter als angenommen; eine zu kleine Schranke wäre unehrlich). Kleiner wird sie nur
bei deutlicher Änderung (Faktor 1,5) und höchstens alle 12 h, auch nicht in den 12 h nach
einem Zurücksetzen. Immer mit Ereignis im Protokoll. Abschalten: Einstellung
gps_bound_mode = „manual“ (dann gelten gps_delay/gps_precision wie bisher), Zurücksetzen
auf den vorsichtigen Standard über POST /api/gps/bound {"action": "reset"}.

Datenschutz: Hier wird nichts gespeichert, was den Standort verrät – keine Position, keine
Satellitenwinkel. Der Antennen-Test merkt sich nur Signalstärken, Satellitenzahlen und den
Fix-Anteil; er bleibt lokal (kein Teil des Diagnosepakets).
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
from typing import Any, Callable

import store

# --- Empfangsbewertung -------------------------------------------------------------------
ASSESS_HOURS = 24.0
MIN_ASSESS_SECONDS = 1800.0   # weniger als 30 min Messdaten: noch kein Urteil
GAP_SECONDS = 300.0           # größere Lücken im Verlauf zählen nicht als Messzeit
# Schwellen der Ampel (red/yellow). Begründung je Kennzahl steht in HELP (gpsq_*).
FIX_RED, FIX_YELLOW = 0.80, 0.98          # Anteil der Zeit mit 2D/3D-Fix
CHANGES_RED, CHANGES_YELLOW = 4.0, 0.5    # Fix-Wechsel je Stunde
CN0_RED, CN0_YELLOW = 22.0, 30.0          # dB-Hz, Median der vier stärksten
USED_RED, USED_YELLOW = 4.0, 6.0          # genutzte Satelliten (Median bei Fix)

# --- Fehlerschranke ----------------------------------------------------------------------
BOUND_HOURS = 6.0             # Messfenster für die Streuung GPS − Netz
BOUND_MIN_SAMPLES = 60
BOUND_MIN_SECONDS = 1800.0
DEFAULT_DELAY = 0.2           # unbekannte Streuung: vorsichtig (± 100 ms)
DELAY_MIN = 0.02              # NMEA ohne PPS: nie enger als ± 10 ms ansetzen
DELAY_MAX = 1.0               # Obergrenze wie die Einstellung gps_delay
PRECISION_MIN, PRECISION_MAX = 0.001, 0.1
CHANGE_FACTOR = 1.5           # kleiner erst ab dieser Änderung (sonst Neustart ohne Nutzen)
GROW_HEADROOM = 1.25          # größer: mindestens um diesen Faktor – weniger Neustarts bei Kriechen
GROW_INTERVAL = 3600.0        # größer (GPS schlechter als angenommen): frühestens nach 1 h
SHRINK_INTERVAL = 12 * 3600.0  # kleiner: frühestens nach 12 h
TICK_INTERVAL = 3600.0
OFFSET_SETTLE = 900.0         # nach einer Offset-Änderung: Neustart von chronyd + Medianfilter abwarten
OFFSET_SHRINK_MIN = 2 * 3600.0  # … und kleiner werden darf die Schranke, sobald so viel Messung danach vorliegt
OFFSET_EPS = 5e-5             # Offsets gelten als gleich (Rundung auf 0,1 ms, wie autocal)

# --- Antennen-Test -----------------------------------------------------------------------
ANTENNA_SECONDS = 300
ANTENNA_MIN_SECONDS, ANTENNA_MAX_SECONDS = 60, 900
ANTENNA_INTERVAL = 5.0
ANTENNA_KEEP = 20
LABEL_RE = re.compile(r"^[\w .,:;+()/#'-]{0,40}$")

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS gps_bound (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS antenna_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        t REAL NOT NULL,
        json TEXT NOT NULL
    );
    """,
]

_LOCK = threading.RLock()
_READY: dict[str, Any] = {"for": None}


class QualityError(ValueError):
    """Ungültige Eingabe (→ HTTP 400) oder unpassender Zustand (→ HTTP 409, conflict=True)."""

    def __init__(self, message: str, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


# =========================================================================================
# Kleine Helfer
# =========================================================================================

def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _median(values: list[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _quantile(values: list[float], q: float) -> float | None:
    """Empirisches Quantil (nächster Rang, aufgerundet) – nie kleiner als der Anteil q der Werte."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _ceil_ms(seconds: float) -> float:
    """Auf volle Millisekunden AUFrunden – eine Schranke darf durch Runden nie kleiner werden."""
    return math.ceil(seconds * 1000.0 - 1e-9) / 1000.0


def fmt_ms(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    ms = seconds * 1000.0
    text = f"{ms:.0f}" if ms >= 10 else f"{ms:.1f}"
    return text.replace(".", ",") + " ms"


def _fmt_pct(share: float) -> str:
    return f"{share * 100:.0f} %"


def _fmt_rate(rate: float) -> str:
    text = f"{rate:.0f}" if rate >= 10 else f"{rate:.1f}"
    return text.replace(".", ",")


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min"
    hours, rest = divmod(seconds, 3600)
    return f"{hours} h {rest // 60} min" if rest >= 60 else f"{hours} h"


# =========================================================================================
# Signalstärke
# =========================================================================================

def cn0_top4(satellites: Any) -> float | None:
    """Median der C/N0 (dB-Hz) der vier stärksten empfangenen Satelliten.

    Warum die vier stärksten: Für einen Fix braucht der Empfänger vier Satelliten. Ihr
    Pegel sagt, wie gut der Empfang wirklich ist – der Mittelwert über alle sichtbaren
    zieht sonst schwache Satelliten am Horizont mit hinein. gpsd meldet für nicht
    empfangene Satelliten 0; die zählen nicht. Akzeptiert die rohe gpsd-Liste („ss“)
    und die aufbereitete aus gps.parse_reports („snr“).
    """
    values = []
    for sat in satellites or []:
        if not isinstance(sat, dict):
            continue
        value = _num(sat.get("ss", sat.get("snr")))
        if value is not None and value > 0:
            values.append(value)
    if not values:
        return None
    return round(_median(sorted(values, reverse=True)[:4]), 1)


# =========================================================================================
# Empfangsbewertung (24 h)
# =========================================================================================

def _gps_points(samples: list[dict], since: float) -> list[tuple[float, dict]]:
    points = []
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        t = _num(sample.get("t"))
        gps = sample.get("gps")
        if t is None or t < since or not isinstance(gps, dict):
            continue
        points.append((t, gps))
    points.sort(key=lambda p: p[0])
    return points


def _has_fix(gps: dict) -> bool | None:
    mode = _num(gps.get("mode"))
    return None if mode is None else mode >= 2


def _count_changes(fixes: list[bool]) -> int:
    """Bestätigte Fix-Wechsel: ein neuer Zustand zählt erst nach zwei Messpunkten in Folge
    (wie statewatch) – ein einzelner Ausreißer ist kein Wechsel."""
    state, candidate, run, changes = None, None, 0, 0
    for fix in fixes:
        if fix == candidate:
            run += 1
        else:
            candidate, run = fix, 1
        if run >= 2 and fix != state:
            if state is not None:
                changes += 1
            state = fix
    return changes


def assess(samples: list[dict], now: float | None = None, hours: float = ASSESS_HOURS) -> dict[str, Any]:
    """Empfangsbewertung aus gespeicherten Messpunkten (history.py, Gruppe „gps“).

    Ergebnis: level green/yellow/red/unknown, sentence (ein Satz fürs Dashboard), reasons
    (je auffälliger Kennzahl ein Grund mit Erklärung) und die Kennzahlen selbst.
    """
    now = time.time() if now is None else now
    points = _gps_points(samples, now - hours * 3600.0)
    result: dict[str, Any] = {
        "available": bool(points), "hours": hours, "level": "unknown", "samples": len(points),
        "covered_seconds": 0.0, "fix_share": None, "fix3d_share": None, "changes": None,
        "changes_per_hour": None, "cn0_top4": None, "cn0_source": None, "used_median": None,
        "reasons": [],
    }
    fixes = [(t, _has_fix(g), _num(g.get("mode"))) for t, g in points]
    fixes = [(t, f, m) for t, f, m in fixes if f is not None]
    if not fixes:
        result["sentence"] = ("Keine GPS-Messwerte im Verlauf – gpsd lief nicht oder der Empfänger "
                              "fehlt. Ohne Messwerte gibt es keine Bewertung.")
        return result
    covered = fix_s = fix3d_s = 0.0
    for (t0, f0, m0), (t1, _f1, _m1) in zip(fixes, fixes[1:]):
        dt = t1 - t0
        if dt <= 0 or dt > GAP_SECONDS:
            continue
        covered += dt
        if f0:
            fix_s += dt
        if m0 is not None and m0 >= 3:
            fix3d_s += dt
    result["covered_seconds"] = round(covered, 1)
    changes = _count_changes([f for _t, f, _m in fixes])
    result["changes"] = changes
    cn4 = [v for v in (_num(g.get("cn4")) for _t, g in points) if v is not None and v > 0]
    if cn4:
        result["cn0_top4"], result["cn0_source"] = round(_median(cn4), 1), "top4"
    else:  # ältere Messpunkte (vor 1.5): nur der Mittelwert der genutzten Satelliten
        avg = [v for v in (_num(g.get("snr")) for _t, g in points) if v is not None and v > 0]
        if avg:
            result["cn0_top4"], result["cn0_source"] = round(_median(avg), 1), "used_avg"
    used = [v for v in (_num(g.get("used")) for _t, g in points if _has_fix(g)) if v is not None]
    if used:
        result["used_median"] = _median(used)
    if covered < MIN_ASSESS_SECONDS:
        result["sentence"] = (f"Noch zu wenig Messdaten ({fmt_duration(covered)}) – die Bewertung "
                              "braucht mindestens 30 Minuten, aussagekräftig sind 24 Stunden.")
        return result

    share = fix_s / covered
    rate = changes / (covered / 3600.0)
    result.update(fix_share=round(share, 4), fix3d_share=round(fix3d_s / covered, 4),
                  changes_per_hour=round(rate, 2))
    reasons: list[dict[str, str]] = []

    def add(level: str, key: str, text: str) -> None:
        reasons.append({"level": level, "key": key, "text": text})

    if share < FIX_RED:
        add("red", "fix", f"Fix nur {_fmt_pct(share)} der Zeit – in den Lücken liefert das GPS keine Zeit.")
    elif share < FIX_YELLOW:
        add("yellow", "fix", f"Fix {_fmt_pct(share)} der Zeit – immer wieder Lücken ohne Zeit vom GPS.")
    if rate > CHANGES_RED:
        add("red", "changes", f"{_fmt_rate(rate)} Fix-Wechsel je Stunde – der Fix kommt und geht, chrony "
                              "verwirft das GPS dann oft.")
    elif rate > CHANGES_YELLOW:
        add("yellow", "changes", f"{_fmt_rate(rate)} Fix-Wechsel je Stunde – der Empfang reißt gelegentlich ab.")
    cn = result["cn0_top4"]
    if cn is not None:
        what = "der vier stärksten Satelliten" if result["cn0_source"] == "top4" else "der genutzten Satelliten"
        if cn < CN0_RED:
            add("red", "cn0", f"Signal {what} im Median nur {cn:.0f} dB-Hz – zu schwach für stabilen "
                              "Empfang (gut: ab 30 dB-Hz).")
        elif cn < CN0_YELLOW:
            add("yellow", "cn0", f"Signal {what} im Median {cn:.0f} dB-Hz – knapp (gut: ab 30 dB-Hz).")
    um = result["used_median"]
    if um is not None:
        if um < USED_RED:
            add("red", "used", f"Im Median nur {um:.0f} genutzte Satelliten – unter 4 gibt es keinen 3D-Fix.")
        elif um < USED_YELLOW:
            add("yellow", "used", f"Im Median {um:.0f} genutzte Satelliten – wenig Reserve (gut: ab 6).")
    level = "red" if any(r["level"] == "red" for r in reasons) else \
        "yellow" if reasons else "green"
    result["level"] = level
    result["reasons"] = reasons
    change_text = "kein Wechsel" if changes == 0 else f"{_fmt_rate(rate)} Wechsel/h"
    head = f"Fix {_fmt_pct(share)} der Zeit, {change_text}"
    tail = {
        "red": "Empfang zu schwach für eine stabile Zeitquelle",
        "yellow": "Empfang mäßig – als Rückfallebene brauchbar, mit Lücken",
        "green": "Empfang gut",
    }[level]
    result["sentence"] = f"{head} – {tail}"
    return result


# =========================================================================================
# Streuung GPS − Netz und ehrliche Fehlerschranke
# =========================================================================================

def spread(diffs: list[float]) -> dict[str, Any] | None:
    """Kennzahlen der Differenzen GPS − Netz (Sekunden) und die daraus folgende Schranke.

    bound = größte zu erwartende Abweichung des GPS von der Netzzeit: das 95-%-Quantil von
    |Differenz|, mindestens |Median| + 3 · MAD (robuste Streuung, auf σ skaliert). Der Median
    zählt mit, weil ein noch nicht kalibrierter Versatz genauso ein Fehler ist wie Rauschen.
    chrony rechnet für eine Refclock mit einer Unsicherheit von delay/2 – darum delay = 2·bound,
    begrenzt auf DELAY_MIN … DELAY_MAX und auf volle ms AUFgerundet.
    """
    values = [d for d in (_num(x) for x in diffs or []) if d is not None]
    if not values:
        return None
    median = _median(values)
    mad = _median([abs(d - median) for d in values]) * 1.4826
    p95 = _quantile([abs(d) for d in values], 0.95)
    p95_dev = _quantile([abs(d - median) for d in values], 0.95)
    bound = max(p95, abs(median) + 3.0 * mad)
    delay = min(DELAY_MAX, max(DELAY_MIN, _ceil_ms(2.0 * bound)))
    precision = min(PRECISION_MAX, max(PRECISION_MIN, _ceil_ms(mad)))
    return {
        "n": len(values), "median": median, "mad": mad, "p95_abs": p95, "p95_dev": p95_dev,
        "bound": bound, "delay": delay, "precision": precision,
    }


def measure(samples: list[dict], gps_name: str, now: float | None = None,
            hours: float = BOUND_HOURS, not_before: float | None = None) -> dict[str, Any]:
    """Streuung der letzten Stunden aus dem Verlauf (Vergleich wie beim Kalibrier-Assistenten).

    not_before: nur Messpunkte ab diesem Zeitpunkt (letzte Offset-Änderung + Einschwingzeit)."""
    import history  # spät: history importiert dieses Modul für calibrate()
    now = time.time() if now is None else now
    since = now - hours * 3600.0
    if not_before is not None and not_before > since:
        since = not_before
    window = [s for s in samples or [] if isinstance(s, dict) and (_num(s.get("t")) or 0) >= since]
    diffs, times = history.gps_differences(window, gps_name, for_bound=True)
    duration = (times[-1] - times[0]) if times else 0.0
    result: dict[str, Any] = {"t": now, "hours": hours, "samples": len(diffs), "duration_seconds": duration}
    if not_before is not None:
        result["not_before"] = not_before
    if len(diffs) < BOUND_MIN_SAMPLES or duration < BOUND_MIN_SECONDS:
        result["status"] = "insufficient"
        return result
    stats = spread(diffs) or {}
    result.update(status="measured", **{k: (round(v, 6) if isinstance(v, float) else v)
                                        for k, v in stats.items()})
    return result


# =========================================================================================
# Gespeicherter Zustand (SQLite) – auch für confgen lesbar
# =========================================================================================

def _ensure() -> None:
    key = store.path()
    if _READY["for"] == key:
        return
    store.migrate("gpsquality", _SCHEMA)
    _READY["for"] = key


def load_state(db_path: str | None = None) -> dict[str, Any]:
    """Gespeicherter Zustand der Fehlerschranke – nur lesend, legt nichts an.

    Auch confgen (eigener Prozess beim Start/Neuladen) und der Hardware-Check lesen hier;
    Lesen darf deshalb weder die Datenbank noch Tabellen erzeugen. Fehlt etwas, ist sie
    gesperrt oder kaputt: {} (→ vorsichtiger Standard)."""
    path = db_path or store.path()
    if not os.path.isfile(path):
        return {}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return {}
    try:
        row = conn.execute("SELECT json FROM gps_bound WHERE id = 1").fetchone()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    try:
        state = json.loads(row[0]) if row else {}
    except (ValueError, TypeError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    _ensure()
    store.execute("INSERT INTO gps_bound(id, json) VALUES(1, ?) "
                  "ON CONFLICT(id) DO UPDATE SET json = excluded.json",
                  (json.dumps(state, separators=(",", ":")),))


_OFFSET: dict[str, Any] = {"for": None, "value": None, "since": None}


def note_offset(cfg: dict, now: float | None = None) -> float | None:
    """Merkt sich gps_offset und wann er sich zuletzt geändert hat; gibt diesen Zeitpunkt zurück.

    Aufruf aus der Messschleife bei jedem Messpunkt: im Normalfall nur ein Vergleich im Speicher.
    Geschrieben wird beim ersten Aufruf (since = None: Änderungszeit unbekannt, alle Werte zählen)
    und wenn sich der Offset ändert. GPS aus: nichts tun (legt keine Datenbank an)."""
    if not cfg.get("gps_enable"):
        return None
    now = time.time() if now is None else now
    value = _num(cfg.get("gps_offset"))
    value = 0.0 if value is None else value
    with _LOCK:
        key = store.path()
        if _OFFSET["for"] != key:
            stored = load_state().get("offset")
            stored = stored if isinstance(stored, dict) else {}
            _OFFSET.update({"for": key, "value": _num(stored.get("value")), "since": _num(stored.get("since"))})
            if _OFFSET["value"] is None:
                _OFFSET.update(value=value, since=None)
                _save_offset()
        if abs(value - float(_OFFSET["value"])) > OFFSET_EPS:
            _OFFSET.update(value=value, since=now)
            _save_offset()
        return _OFFSET["since"]


def _save_offset() -> None:
    try:
        state = load_state()
        state["offset"] = {"value": _OFFSET["value"], "since": _OFFSET["since"]}
        save_state(state)
    except Exception:
        pass   # dann gilt die Änderung nur im Speicher – die Messung bleibt vorsichtig


def offset_not_before(cfg: dict, now: float | None = None) -> float | None:
    """Ab wann Messpunkte zum eingestellten Offset passen (letzte Änderung + Einschwingzeit)."""
    since = note_offset(cfg, now)
    return None if since is None else since + OFFSET_SETTLE


def read_applied(db_path: str | None = None) -> dict[str, Any] | None:
    """Die angewandte Schranke (für confgen). Werte außerhalb der Grenzen werden verworfen."""
    return _valid_applied(load_state(db_path).get("applied"))


def _valid_applied(applied: Any) -> dict[str, Any] | None:
    if not isinstance(applied, dict):
        return None
    delay, precision = _num(applied.get("delay")), _num(applied.get("precision"))
    if delay is None or precision is None:
        return None
    if not (DELAY_MIN <= delay <= DELAY_MAX and PRECISION_MIN <= precision <= PRECISION_MAX):
        return None
    return dict(applied, delay=delay, precision=precision)


def has_pps(cfg: dict, exists: Callable[[str], bool] = os.path.exists) -> bool:
    """Hat chrony wirklich einen PPS-Refclock? Dieselbe Entscheidung wie confgen.render_chrony:
    PPS-Gerät eingestellt UND vorhanden – oder (ohne Gerät) „PPS über gpsd“. Ein eingestelltes,
    aber fehlendes Gerät (z. B. pps-gpio-Overlay nicht geladen) überspringt confgen mit Warnung;
    dann läuft das GPS als reine NMEA-Quelle und braucht die ehrliche Schranke wie ohne PPS."""
    device = str(cfg.get("gps_pps_device") or "").strip()
    if device:
        try:
            return bool(exists(device))
        except (OSError, ValueError):
            return False
    return bool(cfg.get("gps_pps_shm"))


def managed(cfg: dict) -> bool:
    """Bestimmt ntp-gui die Fehlerschranke? Nur ohne PPS und im Modus „gemessen“."""
    return bool(cfg.get("gps_enable")) and not has_pps(cfg) and cfg.get("gps_bound_mode", "measured") == "measured"


def refclock_values(cfg: dict, applied: dict | None | bool = False) -> dict[str, Any]:
    """delay/precision für die GPS-Zeile in chrony.conf und woher sie kommen.

    source: "pps" (mit PPS zählt der Impuls; die NMEA-Zeile nummeriert nur die Sekunden –
    Einstellungen gelten), "manual" (Modus von Hand), "measured" (gemessene Schranke),
    "default" (noch nicht gemessen: mindestens DEFAULT_DELAY – ein von früher zu klein
    gespeicherter gps_delay wird nicht übernommen).
    applied=False: aus der Datenbank lesen (confgen); None/dict: vorgegeben (Tests, Web).
    """
    delay = float(cfg.get("gps_delay") or DEFAULT_DELAY)
    precision = float(cfg.get("gps_precision") or 0.1)
    if has_pps(cfg):
        return {"delay": delay, "precision": precision, "source": "pps"}
    if cfg.get("gps_bound_mode", "measured") != "measured":
        return {"delay": delay, "precision": precision, "source": "manual"}
    if applied is False:
        applied = read_applied()
    applied = _valid_applied(applied)
    if applied:
        return {"delay": applied["delay"], "precision": applied["precision"], "source": "measured"}
    return {"delay": max(delay, DEFAULT_DELAY), "precision": precision, "source": "default"}


def annotate_calibration(result: dict[str, Any], cfg: dict, applied: dict | None | bool = False) -> dict[str, Any]:
    """Kalibrier-Ergebnis um den Delay ergänzen, den chrony wirklich nutzt.

    Im Modus „gemessen“ (ohne PPS) gilt nicht die Einstellung gps_delay, sondern die gemessene
    Schranke bzw. der vorsichtige Standard. Dann zeigt „aktuell“ diesen Wert, und der
    Assistent übernimmt nur den Offset (delay_managed=True)."""
    values = refclock_values(cfg, applied)
    is_managed = managed(cfg)
    result["delay_managed"] = is_managed
    result["delay_source"] = values["source"]
    if is_managed:
        result["current_delay"] = values["delay"]
    return result


def status_hint(cfg: dict) -> dict[str, Any]:
    """Kurzfassung für /api/status (GPS-Seite): PPS wirklich aktiv? Welcher Delay gilt?"""
    if not cfg.get("gps_enable"):
        return {"pps": False, "managed": False, "delay": None, "source": None}
    try:
        values = refclock_values(cfg)
    except Exception:
        values = {"delay": float(cfg.get("gps_delay") or DEFAULT_DELAY), "source": "manual"}
    return {"pps": has_pps(cfg), "managed": managed(cfg), "delay": values["delay"], "source": values["source"]}


# =========================================================================================
# Stündliche Prüfung
# =========================================================================================

_DEPS: dict[str, Any] = {"history": None, "trigger_reload": None, "emit": None}
_LAST_TICK: dict[str, Any] = {"mono": None}


def configure(history: Any = None, trigger_reload: Callable[[], bool] | None = None,
              emit: Callable[..., Any] | None = None) -> None:
    if history is not None:
        _DEPS["history"] = history
    if trigger_reload is not None:
        _DEPS["trigger_reload"] = trigger_reload
    if emit is not None:
        _DEPS["emit"] = emit


def _emit(kind: str, level: str, title: str, data: dict) -> None:
    emit = _DEPS.get("emit")
    if emit is None:
        import events
        emit = events.emit
    try:
        emit(kind, level, title, data)
    except Exception:
        pass


def _since(t: Any, now: float) -> float | None:
    """Sekunden seit t; None = unbekannt (kein t oder t liegt in der Zukunft – Uhr sprang zurück)."""
    value = _num(t)
    if value is None:
        return None
    since = now - value
    return since if since >= 0 else None


def decide(measured: dict, applied: dict | None, now: float, reset_at: float | None = None,
           offset_changed_at: float | None = None) -> dict[str, Any]:
    """Reine Entscheidung: neue Schranke anwenden oder nicht (mit Grund).

    Größer (das GPS streut stärker als die eingestellte Schranke): sofort, sobald die Messung
    darüber liegt – höchstens einmal je Stunde. Neue Schranke dann mindestens GROW_HEADROOM ×
    die alte, damit langsames Kriechen nicht stündlich chronyd neu startet. Kleiner: nur bei
    deutlicher Änderung (Faktor 1,5) und frühestens 12 h nach der letzten Änderung bzw. dem
    letzten Zurücksetzen. Wurde der Offset danach geändert (offset_changed_at), gilt die Sperre
    als erfüllt, sobald OFFSET_SHRINK_MIN Messung nach der Änderung vorliegt (measure misst dann
    nur diese). Sprang die Uhr zurück (Zeitpunkt in der Zukunft), gilt „unbekannt“:
    größer erlaubt (die sichere Richtung), kleiner gesperrt.
    Ergebnis bei apply: delay = die neue Schranke (Delay in Sekunden)."""
    if measured.get("status") != "measured":
        return {"apply": False, "reason": "Noch zu wenig gemeinsame Messungen von GPS und Netzquellen."}
    current = applied["delay"] if applied else DEFAULT_DELAY
    new = float(measured["delay"])
    if applied:
        since = _since(applied.get("t"), now)
    elif reset_at is not None:
        since = _since(reset_at, now)
    else:
        since = math.inf
    if new > current + 1e-9:
        if since is not None and since < GROW_INTERVAL:
            return {"apply": False, "reason": "Die Streuung ist größer als die eingestellte Schranke – die nächste "
                                              "Anpassung ist frühestens eine Stunde nach der letzten möglich."}
        target = min(DELAY_MAX, max(new, _ceil_ms(current * GROW_HEADROOM)))
        return {"apply": True, "delay": target,
                "reason": "Das GPS streut stärker als angenommen – die Schranke wird größer."}
    if new <= current / CHANGE_FACTOR:
        last_change = max(_num((applied or {}).get("t")) or -math.inf, reset_at if reset_at is not None else -math.inf)
        after_offset = (offset_changed_at is not None and offset_changed_at <= now
                        and offset_changed_at > last_change
                        and (_num(measured.get("duration_seconds")) or 0.0) >= OFFSET_SHRINK_MIN)
        if after_offset:
            return {"apply": True, "delay": new,
                    "reason": "Der GPS-Offset wurde geändert und die Messung seitdem zeigt weniger Streuung – "
                              "die Schranke wird kleiner."}
        if since is None or since < SHRINK_INTERVAL:
            return {"apply": False, "reason": "Die Streuung ist kleiner geworden – kleiner wird die "
                                              "Schranke höchstens alle 12 Stunden (auch nach einem Zurücksetzen)."}
        return {"apply": True, "delay": new,
                "reason": "Das GPS streut weniger als angenommen – die Schranke wird kleiner."}
    return {"apply": False, "reason": "Die gemessene Streuung passt zur eingestellten Schranke."}


def tick(cfg: dict, now: float | None = None, samples: list[dict] | None = None) -> dict[str, Any]:
    """Einmal messen und ggf. anwenden. Wirft nie (Fehler stehen im Ergebnis)."""
    now = time.time() if now is None else now
    with _LOCK:
        try:
            state = load_state()
            if not managed(cfg):
                return {"apply": False, "reason": "Die Fehlerschranke wird nicht gemessen (PPS, GPS aus "
                                                  "oder Modus „von Hand“)."}
            if samples is None:
                hist = _DEPS.get("history")
                samples = hist.snapshot(now - BOUND_HOURS * 3600.0) if hist is not None else []
            offset_since = note_offset(cfg, now)
            if offset_since is not None and offset_since > now:
                offset_since = None          # Uhr sprang zurück: Zeitpunkt unbrauchbar
            measured = measure(samples, str(cfg.get("gps_refid") or "GPS"), now,
                               not_before=None if offset_since is None else offset_since + OFFSET_SETTLE)
            state = load_state()             # note_offset kann gerade geschrieben haben
            applied = _valid_applied(state.get("applied"))
            # Zeitpunkte in der Zukunft (Uhr lief vor und wurde korrigiert): auf jetzt kürzen,
            # sonst bliebe das Verkleinern bis dahin gesperrt.
            if applied and (_num(applied.get("t")) or 0.0) > now:
                applied["t"] = now
                state["applied"] = dict(state["applied"], t=now)
            reset_at = _num(state.get("reset_at"))
            if reset_at is not None and reset_at > now:
                reset_at = state["reset_at"] = now
            decision = decide(measured, applied, now, reset_at, offset_since)
            state["measured"] = measured
            state["decision"] = dict(decision, t=now)
            if decision["apply"]:
                old = applied["delay"] if applied else DEFAULT_DELAY
                new_delay = float(decision.get("delay", measured["delay"]))
                state["applied"] = {"delay": new_delay, "precision": measured["precision"],
                                    "bound": measured["bound"], "samples": measured["samples"],
                                    "hours": measured["hours"], "t": now}
                save_state(state)
                trigger = _DEPS.get("trigger_reload")
                reloaded = bool(trigger()) if trigger else False
                decision["reload_triggered"] = reloaded
                _emit("gps", "info",
                      f"GPS-Fehlerschranke angepasst: ± {fmt_ms(old / 2)} → ± {fmt_ms(new_delay / 2)}",
                      {"old_delay": old, "new_delay": new_delay, "measured_delay": measured["delay"],
                       "new_precision": measured["precision"], "spread_ms": round(measured["bound"] * 1000, 1),
                       "samples": measured["samples"], "hours": measured["hours"],
                       "reason": decision["reason"], "reload_triggered": reloaded})
            else:
                save_state(state)
            return decision
        except Exception as exc:  # nie die Messschleife stören
            return {"apply": False, "reason": f"Prüfung fehlgeschlagen: {exc}", "error": str(exc)}


def maybe_tick(cfg_fn: Callable[[], dict], clock: Callable[[], float] = time.monotonic) -> dict | None:
    """Aus der Messschleife: höchstens einmal je TICK_INTERVAL."""
    mono = clock()
    last = _LAST_TICK["mono"]
    if last is not None and mono - last < TICK_INTERVAL:
        return None
    _LAST_TICK["mono"] = mono
    try:
        return tick(cfg_fn())
    except Exception:
        return None


def reset(cfg: dict, now: float | None = None) -> dict[str, Any]:
    """Zurück auf den vorsichtigen Standard (± 100 ms) – Ereignis + Neustart der Zeitdienste."""
    now = time.time() if now is None else now
    with _LOCK:
        state = load_state()
        applied = _valid_applied(state.get("applied"))
        if not applied:
            raise QualityError("Es ist keine gemessene Fehlerschranke aktiv.", conflict=True)
        state["applied"] = None
        # Ohne Sperre würde die nächste stündliche Prüfung dieselbe kleine Schranke sofort wieder
        # setzen: Verkleinern erst wieder 12 h nach dem Zurücksetzen (Vergrößern jederzeit).
        state["reset_at"] = now
        state["decision"] = {"apply": False, "t": now,
                             "reason": "Von Hand auf den Standard zurückgesetzt – kleiner wird die Schranke "
                                       "frühestens in 12 Stunden wieder."}
        save_state(state)
        trigger = _DEPS.get("trigger_reload")
        reloaded = bool(trigger()) if trigger else False
        _emit("gps", "info",
              f"GPS-Fehlerschranke zurückgesetzt: ± {fmt_ms(applied['delay'] / 2)} → ± {fmt_ms(DEFAULT_DELAY / 2)}",
              {"old_delay": applied["delay"], "new_delay": DEFAULT_DELAY, "reload_triggered": reloaded,
               "reason": "von Hand"})
        return {"ok": True, "reload_triggered": reloaded, "delay": DEFAULT_DELAY}


# =========================================================================================
# Rolle des GPS
# =========================================================================================

def _gps_source(sources: Any, refid: str) -> dict | None:
    for src in sources or []:
        if isinstance(src, dict) and src.get("name") == refid and src.get("mode") in {"#", None}:
            return src
    return None


def role(cfg: dict, sources: Any = None, state: dict | None = None) -> dict[str, Any]:
    """Welche Rolle spielt das GPS? role: off | fallback | reference | observe.

    label: „Rückfallebene“, „Referenz“, „nur beobachten“ (bewusste Wahl). active: ob chrony
    das GPS gerade zum Stellen der Uhr nutzt („*“/„+“), None wenn unbekannt.
    """
    if not cfg.get("gps_enable"):
        return {"role": "off", "label": "aus", "tone": "muted", "active": None,
                "text": "GPS ist ausgeschaltet."}
    state = load_state() if state is None else state
    applied = _valid_applied(state.get("applied"))
    values = refclock_values(cfg, applied)
    measured = state.get("measured") if isinstance(state.get("measured"), dict) else None
    src = _gps_source(sources, str(cfg.get("gps_refid") or "GPS")) if sources is not None else None
    active = None if sources is None else bool(src and src.get("state") in {"*", "+"})
    result: dict[str, Any] = {"delay": values["delay"], "precision": values["precision"],
                              "bound": values["delay"] / 2, "bound_source": values["source"],
                              "active": active, "warnings": []}
    select = cfg.get("gps_select") or "auto"
    if select == "noselect":
        result.update(role="observe", label="nur beobachten", tone="info",
                      text="Du hast „nur beobachten“ gewählt: chrony misst das GPS und vergleicht es mit dem Netz, "
                           "stellt die Uhr aber nie danach – auch nicht, wenn das Internet ausfällt.")
        return result
    if has_pps(cfg):
        result.update(role="reference", label="Referenz", tone="good",
                      text="Mit PPS ist das GPS genauer als jede Internetquelle: chrony nimmt es als Referenz, "
                           "die NMEA-Zeit nummeriert nur die Sekunden.")
        return result
    bound = fmt_ms(values["delay"] / 2)
    if select == "prefer":
        result.update(role="reference", label="Referenz (bevorzugt, ohne PPS)", tone="warn",
                      text=f"Du hast „bevorzugen“ gewählt: chrony nimmt das GPS (± {bound}) als erste Wahl, solange "
                           "es plausibel ist. Ohne PPS sind gute Netzquellen meist genauer – bei Mobilfunk, "
                           "Starlink oder ohne Internet ist das trotzdem richtig. Mit „automatisch“ wird das GPS "
                           "zur Rückfallebene.")
        return result
    result.update(role="fallback", label="Rückfallebene", tone="good" if values["source"] == "measured" else "info",
                  text=f"chrony nimmt die Netzquellen, solange sie besser sind. Wird das Internet schlecht oder "
                       f"fällt es aus, übernimmt das GPS von selbst – mit ehrlicher Fehlerschranke ± {bound}.")
    honest = measured.get("delay") if measured and measured.get("status") == "measured" else None
    if values["source"] == "default" and honest is None:
        result["text"] += (" Die Schranke ist noch der vorsichtige Standard; nach einigen Stunden gemeinsamer "
                           "Messung mit den Netzquellen setzt ntp-gui sie auf die gemessene Streuung.")
    elif values["source"] == "default" and honest <= values["delay"]:
        result["text"] += (f" Die gemessene Streuung (± {fmt_ms(honest / 2)}) liegt nah am vorsichtigen Standard – "
                           "die Schranke bleibt darum beim Standard.")
    if honest is not None and values["delay"] < honest:
        if values["source"] == "manual":
            result["warnings"].append(
                f"Deine Schranke (Delay {values['delay']} s = ± {bound}) ist kleiner als die gemessene Streuung "
                f"(± {fmt_ms(honest / 2)}). chrony könnte das GPS dann guten Netzquellen vorziehen. Modus "
                "„gemessen“ oder ein größerer Delay behebt das.")
        else:
            result["warnings"].append(
                f"Die gemessene Streuung (± {fmt_ms(honest / 2)}) ist größer als die Schranke in chrony "
                f"(± {bound}). ntp-gui vergrößert sie bei der nächsten stündlichen Prüfung – höchstens "
                "einmal je Stunde.")
    try:
        minsources = int(cfg.get("ntp_minsources") or 1)
    except (TypeError, ValueError):
        minsources = 1
    if minsources > 1:
        result["warnings"].append(
            f"„Mindestzahl Quellen“ steht auf {minsources}: Fällt das Internet ganz aus, ist das GPS allein "
            "und chrony stellt die Uhr nicht danach. Für eine echte Rückfallebene 1 einstellen.")
    if active:
        result["text"] += " Gerade nutzt chrony das GPS – die Netzquellen sind schlechter oder fehlen."
    return result


# =========================================================================================
# Antennen-Test
# =========================================================================================

def _poll_point(status: dict) -> dict[str, Any] | None:
    if not isinstance(status, dict) or not status.get("running"):
        return None
    sats = [s for s in status.get("satellites") or [] if isinstance(s, dict)]
    tracked = [s for s in sats if (_num(s.get("snr")) or 0) > 0]
    return {
        "fix": bool((_num(status.get("mode")) or 0) >= 2),
        "used": _num(status.get("satellites_used")),
        "seen": _num(status.get("satellites_seen")),
        "tracked": len(tracked),
        "strong": sum(1 for s in tracked if (_num(s.get("snr")) or 0) >= 30),
        "cn4": cn0_top4(sats),
    }


def summarize_antenna(points: list[dict]) -> dict[str, Any]:
    """Kennzahlen einer Messung – ohne Winkel, ohne Position."""
    points = [p for p in points if isinstance(p, dict)]
    n = len(points)

    def med(key: str) -> float | None:
        values = [v for v in (_num(p.get(key)) for p in points) if v is not None]
        value = _median(values)
        return None if value is None else round(value, 1)

    return {
        "samples": n,
        "fix_share": round(sum(1 for p in points if p.get("fix")) / n, 3) if n else None,
        "cn0_top4": med("cn4"), "used": med("used"), "seen": med("seen"),
        "tracked": med("tracked"), "strong": med("strong"),
    }


def compare(a: dict, b: dict) -> dict[str, Any]:
    """Vergleich zweier Messungen: welche Antennenposition ist besser und warum."""
    def diff(key: str) -> float | None:
        va, vb = _num((a or {}).get(key)), _num((b or {}).get(key))
        return None if va is None or vb is None else round(vb - va, 3)

    deltas = {key: diff(key) for key in ("cn0_top4", "fix_share", "used", "tracked", "strong")}
    score = 0.0
    if deltas["cn0_top4"] is not None:
        score += deltas["cn0_top4"] / 3.0          # 3 dB-Hz = ein Punkt
    if deltas["fix_share"] is not None:
        score += deltas["fix_share"] * 20.0        # 5 Prozentpunkte = ein Punkt
    if deltas["used"] is not None:
        score += deltas["used"] / 2.0
    name_a = (a or {}).get("label") or "A"
    name_b = (b or {}).get("label") or "B"
    parts = []
    if deltas["cn0_top4"] is not None:
        parts.append(f"{deltas['cn0_top4']:+.0f} dB-Hz bei den vier stärksten".replace("+0 ", "±0 ")
                     .replace("-0 ", "±0 "))
    if deltas["fix_share"] is not None and abs(deltas["fix_share"]) >= 0.01:
        parts.append(f"Fix {_fmt_pct(b['fix_share'])} statt {_fmt_pct(a['fix_share'])}")
    if deltas["used"] is not None and abs(deltas["used"]) >= 1:
        parts.append(f"{b['used']:.0f} statt {a['used']:.0f} genutzte Satelliten")
    detail = ", ".join(parts)
    if score >= 1.0:
        verdict, better = f"„{name_b}“ ist besser" + (f": {detail}" if detail else ""), "b"
    elif score <= -1.0:
        verdict, better = f"„{name_a}“ ist besser" + (f": {detail}" if detail else ""), "a"
    else:
        verdict, better = "Kaum Unterschied" + (f" ({detail})" if detail else "") + \
            " – miss zu verschiedenen Tageszeiten, die Satelliten wandern.", None
    return {"deltas": deltas, "score": round(score, 2), "better": better, "verdict": verdict}


def check_label(label: Any) -> str:
    label = "" if label is None else str(label).strip()
    if not LABEL_RE.match(label):
        raise QualityError("Name der Messung: höchstens 40 Zeichen, nur Buchstaben, Ziffern, Leerzeichen "
                           "und .,:;+()/#'-")
    return label


class AntennaTest:
    """Eine laufende Messung (höchstens eine gleichzeitig). poll liefert gps.status()."""

    def __init__(self, poll: Callable[[], dict], save: Callable[[dict], int | None],
                 wall: Callable[[], float] = time.time, mono: Callable[[], float] = time.monotonic) -> None:
        self._poll, self._save, self._wall, self._mono = poll, save, wall, mono
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.current: dict[str, Any] | None = None
        self.last_error: str | None = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, label: str, seconds: float = ANTENNA_SECONDS, interval: float = ANTENNA_INTERVAL) -> dict:
        with self._lock:
            if self.running():
                raise QualityError("Es läuft bereits eine Messung.", conflict=True)
            self._stop = threading.Event()
            self.current = {"label": label, "seconds": float(seconds), "started": self._wall(),
                            "points": [], "mono_start": self._mono()}
            self.last_error = None
            self._thread = threading.Thread(target=self._run, args=(self.current, self._stop, interval),
                                            daemon=True, name="gps-antenna")
            self._thread.start()
            return self.status()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self, run: dict, stop: threading.Event, interval: float) -> None:
        deadline = run["mono_start"] + run["seconds"]
        while not stop.is_set():
            try:
                point = _poll_point(self._poll())
            except Exception:
                point = None
            if point is not None:
                run["points"].append(point)
            remaining = deadline - self._mono()
            if remaining <= 0:
                break
            stop.wait(min(interval, remaining))
        summary = summarize_antenna(run["points"])
        result = dict(summary, label=run["label"], started=run["started"], ended=self._wall(),
                      seconds=run["seconds"], complete=not stop.is_set())
        if summary["samples"] >= 3:
            try:
                result["id"] = self._save(result)
            except Exception as exc:
                self.last_error = f"Messung nicht gespeichert: {exc}"
        else:
            self.last_error = ("Die Messung hatte zu wenige Werte von gpsd – läuft gpsd, und ist der "
                               "Empfänger eingesteckt?")
        run["result"] = result

    def status(self) -> dict[str, Any]:
        run = self.current
        if not run:
            return {"running": False, "error": self.last_error}
        elapsed = max(0.0, self._mono() - run["mono_start"])
        running = self.running()
        return {
            "running": running, "label": run["label"], "started": run["started"],
            "seconds": run["seconds"], "elapsed": round(min(elapsed, run["seconds"]), 1) if running else run["seconds"],
            "live": summarize_antenna(run["points"]) if running else None,
            "error": self.last_error,
        }


def save_antenna(result: dict) -> int:
    _ensure()
    with store.transaction() as db:
        cur = db.execute("INSERT INTO antenna_tests(t, json) VALUES(?, ?)",
                         (float(result.get("ended") or time.time()), json.dumps(result, separators=(",", ":"))))
        new_id = int(cur.lastrowid or 0)
        db.execute("DELETE FROM antenna_tests WHERE id NOT IN "
                   "(SELECT id FROM antenna_tests ORDER BY id DESC LIMIT ?)", (ANTENNA_KEEP,))
    return new_id


def antenna_results() -> list[dict]:
    try:
        _ensure()
        rows = store.query("SELECT id, json FROM antenna_tests ORDER BY id DESC LIMIT ?", (ANTENNA_KEEP,))
    except (sqlite3.Error, OSError):
        return []
    out = []
    for row_id, text in rows:
        try:
            item = json.loads(text)
        except ValueError:
            continue
        if isinstance(item, dict):
            item["id"] = row_id
            out.append(item)
    return out


def delete_antenna(test_id: Any) -> bool:
    if isinstance(test_id, bool) or not isinstance(test_id, int) or test_id <= 0:
        raise QualityError("id muss eine positive Zahl sein")
    _ensure()
    return store.execute("DELETE FROM antenna_tests WHERE id = ?", (test_id,)) > 0


ANTENNA: AntennaTest | None = None


def antenna() -> AntennaTest:
    global ANTENNA
    if ANTENNA is None:
        import gps
        ANTENNA = AntennaTest(gps.status, save_antenna)
    return ANTENNA


def antenna_status(a: Any = None, b: Any = None) -> dict[str, Any]:
    results = antenna_results()
    by_id = {r["id"]: r for r in results}

    def pick(value: Any, fallback: dict | None) -> dict | None:
        try:
            return by_id.get(int(value)) if value not in (None, "") else fallback
        except (TypeError, ValueError):
            return fallback

    first = pick(a, results[1] if len(results) > 1 else None)
    second = pick(b, results[0] if results else None)
    comparison = None
    if first and second and first is not second:
        comparison = dict(compare(first, second), a=first["id"], b=second["id"])
    return {"test": antenna().status(), "results": results, "comparison": comparison,
            "default_seconds": ANTENNA_SECONDS}


def antenna_action(data: dict) -> dict[str, Any]:
    action = str(data.get("action") or "")
    test = antenna()
    if action == "start":
        label = check_label(data.get("label"))
        seconds = data.get("seconds", ANTENNA_SECONDS)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) \
                or not ANTENNA_MIN_SECONDS <= seconds <= ANTENNA_MAX_SECONDS:
            raise QualityError(f"seconds: {ANTENNA_MIN_SECONDS}–{ANTENNA_MAX_SECONDS}")
        import settings
        if not settings.values().get("gps_enable"):
            raise QualityError("GPS ist ausgeschaltet – ohne Empfänger gibt es nichts zu messen.", conflict=True)
        test.start(label, float(seconds))
    elif action == "stop":
        test.stop()
    elif action == "delete":
        if not delete_antenna(data.get("id")):
            raise QualityError("Diese Messung gibt es nicht (mehr).", conflict=True)
    else:
        raise QualityError("action muss „start“, „stop“ oder „delete“ sein")
    return antenna_status()


# =========================================================================================
# API
# =========================================================================================

_ASSESS_CACHE: dict[str, Any] = {"mono": None, "value": None, "key": None}
ASSESS_TTL = 60.0


def _cached_assessment(history: Any, now: float, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Empfangsbewertung, höchstens einmal je ASSESS_TTL neu gerechnet (GPS-Seite und Übersicht)."""
    hist = history if history is not None else _DEPS.get("history")
    mono = clock()
    cached = _ASSESS_CACHE
    if cached["value"] is not None and cached["key"] == id(hist) and cached["mono"] is not None \
            and mono - cached["mono"] < ASSESS_TTL:
        return cached["value"]
    samples = hist.snapshot(now - ASSESS_HOURS * 3600.0) if hist is not None else []
    assessment = assess(samples, now)
    cached.update(mono=mono, value=assessment, key=id(hist))
    return assessment


def overview(cfg: dict, history: Any = None, sources: Any = None, stability: dict | None = None,
             now: float | None = None, clock: Callable[[], float] = time.monotonic) -> dict[str, Any] | None:
    """Kurzfassung für die Übersicht (/api/status → gps_summary): Rolle, Empfangsampel, unstet.

    Nur Wörter und Ampelstufen – keine Satellitenwinkel, keine Position.
    """
    if not cfg.get("gps_enable"):
        return None
    now = time.time() if now is None else now
    try:
        assessment = _cached_assessment(history, now, clock)
    except Exception:
        assessment = {"available": False, "level": "unknown"}
    try:
        info = role(cfg, sources)
    except Exception:
        info = {"role": "unknown", "label": "–", "active": None, "warnings": []}
    stab = (stability or {}).get("state") or "unbekannt"
    return {
        "role": info.get("role"), "role_label": info.get("label"), "active": info.get("active"),
        "role_warnings": len(info.get("warnings") or []),
        "level": assessment.get("level") if assessment.get("available") else "unknown",
        "sentence": assessment.get("sentence") if assessment.get("available") else None,
        "stability": stab,
        "unstet_changes": (stability or {}).get("unstet_changes") if stab == "unstet" else None,
    }


def insights(summary: dict | None) -> list[dict[str, Any]]:
    """Hinweise für die Übersicht: GPS unstet bzw. Empfang rot (Info – kein Dauer-Alarm bei Innenantennen)."""
    if not summary:
        return []
    out: list[dict[str, Any]] = []
    if summary.get("stability") == "unstet":
        n = summary.get("unstet_changes")
        count = f" ({n} Fix-Wechsel bisher)" if isinstance(n, int) and n > 0 else ""
        out.append({"level": "info", "key": "gps_unstet", "action": "gps", "title": "GPS-Empfang unstet" + count,
                    "text": "Der Fix kommt und geht. Ohne PPS bleibt das GPS trotzdem die Rückfallebene – chrony "
                            "nimmt es nur, solange es plausibel ist. Besserer Platz für die Antenne: GPS-Seite → "
                            "Antennen-Test."})
    elif summary.get("level") == "red":
        out.append({"level": "info", "key": "gps_reception", "action": "gps", "title": "GPS-Empfang schwach (24 h)",
                    "text": (summary.get("sentence") or "Der Empfang reicht nicht für eine stabile Zeitquelle.")
                            + ". Tipps und Antennen-Test findest du auf der GPS-Seite."})
    return out


def api_status(cfg: dict, history: Any = None, sources: Any = None, stability: dict | None = None,
               now: float | None = None, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Alles für GET /api/gps/quality."""
    now = time.time() if now is None else now
    if not cfg.get("gps_enable"):
        return {"enabled": False, "available": False,
                "reason": "GPS ist ausgeschaltet – Empfangsbewertung nicht verfügbar."}
    assessment = _cached_assessment(history, now, clock)
    state = load_state()
    applied = _valid_applied(state.get("applied"))
    return {
        "enabled": True,
        "available": assessment.get("available", False),
        "assessment": assessment,
        "stability": stability or {"state": "unbekannt"},
        "role": role(cfg, sources, state),
        "bound": {
            "mode": cfg.get("gps_bound_mode", "measured"),
            "managed": managed(cfg),
            "effective": refclock_values(cfg, applied),
            "applied": applied,
            "measured": state.get("measured"),
            "decision": state.get("decision"),
            "default_delay": DEFAULT_DELAY,
        },
    }
