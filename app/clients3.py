"""Clients 3 (1.5): Regeln je Gerät, Gruppen/VLAN-Ansichten, Uhrgüte, NTS-Hinweise, Gerätepass.

Baut auf clientmon.py (passive Messung) und clientinfo.py (Clients 2.0) auf:

  * **Gruppen** aus Netzen, die du benennst („IoT = 10.0.30.0/24“). Der Kernel entfernt VLAN-Tags
    meist vor dem Mitlesen – deshalb Netze statt VLAN-Nummern. Zuordnung: das spezifischste Netz
    gewinnt (längstes Präfix). Ansichten nach Gruppe, nach VLAN (wo die Kennung sichtbar ist) und
    nach (vermuteter oder erwarteter) Software, je Gruppe Anzahl, Median-Abweichung, Anteil „gut“.
  * **Uhrgüte je Gerät** (0–100) aus Abweichung, Stabilität, Regelmäßigkeit der Anfragen und
    Messbarkeit; dazu die **Gangabweichung** in ppm aus dem Sägezahn zwischen zwei Abfragen
    (bzw. aus der Steigung, wenn die Uhr frei läuft).
  * **Regeln je Gerät**: „fragt seit N h nicht mehr“, eigene Alarm-Schwelle „|Abweichung| > X für
    M min“, stumm (Ereignis bleibt lokal), erwartete Client-Software. Zustand der Alarme in SQLite –
    ein Neustart meldet nichts doppelt.
  * **Neues Gerät fragt nach der Zeit** (Inventar, Schalter clients_new_device_alarm).
  * **NTS für Clients**: wer nutzt NTS (chronyc clients -k), wer könnte es (je Software).
  * **Gerätepass**: alles Wichtige zu einem Gerät auf einer druckbaren Seite; eine Kopie zum
    Weitergeben nur gefiltert (egress, Pseudonyme).

Alles bleibt lokal. Gespeicherte Ereignistitel nennen nur die Adresse (wie 1.4); den eigenen Namen
setzen Anzeige (clientinfo.with_display_titles) und Benachrichtigung (notify.outgoing) ein.
Nur Standardbibliothek.
"""

from __future__ import annotations

import ipaddress
import json
import math
import threading
import time
from typing import Any, Callable

import clientinfo
import clientmon

# ---------------------------------------------------------------------------
# Speicher
# ---------------------------------------------------------------------------

MAX_GROUPS = 64
MAX_GROUP_NAME = 40
MAX_RULES = 4 * clientmon.MAX_CLIENTS
HOURLY_RETENTION_H = 30 * 24
HOURLY_BACKFILL_H = 7 * 24        # beim ersten Lauf: so weit zurück (so lange halten die Messpunkte)
HOURLY_PER_TICK = 24              # höchstens so viele Stunden je Durchlauf nachrechnen
HOURLY_SETTLE = 120.0             # eine Stunde erst so lange nach ihrem Ende zusammenfassen
INVENTORY_MAX = 20000
INVENTORY_LEARN = 86400.0         # die ersten 24 h nur lernen
PLAUSIBLE_WALL = 1_704_067_200.0  # 2024-01-01: davor ist die Systemzeit sicher noch nicht gestellt
NEW_DEVICE_PER_HOUR = 5


def _migrate(store_mod) -> None:
    clientmon._migrate(store_mod)
    store_mod.migrate("clients3", [
        "CREATE TABLE IF NOT EXISTS client_groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
        "network TEXT NOT NULL UNIQUE, updated REAL NOT NULL);"
        "CREATE TABLE IF NOT EXISTS client_rules (ip TEXT PRIMARY KEY, silent_h REAL, offset_ms REAL, "
        "offset_min INTEGER NOT NULL DEFAULT 0, mute INTEGER NOT NULL DEFAULT 0, expect TEXT NOT NULL DEFAULT '', "
        "state TEXT NOT NULL DEFAULT '{}', updated REAL NOT NULL);"
        "CREATE TABLE IF NOT EXISTS client_hourly (ip TEXT NOT NULL, hour INTEGER NOT NULL, n INTEGER NOT NULL, "
        "med REAL, p95 REAL, lo REAL, hi REAL, PRIMARY KEY(ip, hour));"
        "CREATE INDEX IF NOT EXISTS client_hourly_hour ON client_hourly(hour);"
        "CREATE TABLE IF NOT EXISTS client_inventory (key TEXT PRIMARY KEY, first_seen REAL NOT NULL);"
        "CREATE TABLE IF NOT EXISTS clients3_meta (key TEXT PRIMARY KEY, value TEXT)",
    ])


def _store():
    import store
    _migrate(store)
    return store


def _meta_get(key: str) -> str | None:
    rows = _store().query("SELECT value FROM clients3_meta WHERE key=?", (key,))
    return rows[0][0] if rows else None


def _meta_set(key: str, value: str) -> None:
    _store().execute("INSERT INTO clients3_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET "
                     "value=excluded.value", (key, value))


class Clients3Error(ValueError):
    """Ungültige Eingabe (Text für die Oberfläche)."""


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _median(values: list[float]) -> float | None:
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _quantile(values: list[float], q: float) -> float | None:
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


# ---------------------------------------------------------------------------
# Gruppen aus Netzen
# ---------------------------------------------------------------------------

_GROUP_CACHE: dict[str, Any] = {"t": None, "data": None}
CACHE_TTL = 30.0
MIN_PREFIX = {4: 8, 6: 16}


def clean_network(value: Any) -> str:
    """„10.0.30.0/24“, „10.0.30.7/24“ (wird zu …0/24), „fd00:30::/64“ – sonst Clients3Error."""
    text = str(value or "").strip()
    if not text or len(text) > 64 or "%" in text:
        raise Clients3Error("Gib ein Netz an, z. B. 10.0.30.0/24 oder fd00:30::/64.")
    if "/" not in text:
        raise Clients3Error("Das Netz braucht eine Präfixlänge, z. B. 10.0.30.0/24.")
    try:
        net = ipaddress.ip_network(text, strict=False)
    except ValueError:
        raise Clients3Error(f"„{text[:64]}“ ist kein gültiges Netz (Beispiel: 10.0.30.0/24).") from None
    if net.prefixlen < MIN_PREFIX[net.version]:
        raise Clients3Error(f"Das Netz ist zu groß – mindestens /{MIN_PREFIX[net.version]}.")
    return str(net)


def clean_group_name(value: Any) -> str:
    try:
        text = clientinfo.clean_name(value)
    except clientinfo.MetaError as exc:
        raise Clients3Error(str(exc).replace("Der Name", "Der Gruppenname")) from None
    if not text:
        raise Clients3Error("Gib der Gruppe einen Namen, z. B. „IoT“ oder „Kameras“.")
    if len(text) > MAX_GROUP_NAME:
        raise Clients3Error(f"Der Gruppenname darf höchstens {MAX_GROUP_NAME} Zeichen lang sein.")
    return text


def groups(fresh: bool = False) -> list[dict]:
    """[{id, name, network}] – 30 s zwischengespeichert."""
    now = time.monotonic()
    cached = _GROUP_CACHE["data"]
    if not fresh and cached is not None and _GROUP_CACHE["t"] is not None and now - _GROUP_CACHE["t"] < CACHE_TTL:
        return cached
    try:
        rows = _store().query("SELECT id, name, network FROM client_groups ORDER BY name COLLATE NOCASE, id")
        data = [{"id": int(i), "name": n, "network": net} for i, n, net in rows]
    except Exception:  # noqa: BLE001 – Gruppen sind ein Zusatz
        data = []
    _GROUP_CACHE.update(t=now, data=data)
    return data


def _drop_group_cache() -> None:
    _GROUP_CACHE.update(t=None, data=None)


def group_names() -> list[str]:
    """Eigene Gruppennamen – für den Datenschutzfilter (egress, Kategorie „name“)."""
    return sorted({g["name"] for g in groups() if g.get("name")})


def save_group(data: Any) -> dict:
    if not isinstance(data, dict):
        raise Clients3Error("Erwartet: {\"name\": …, \"network\": …}")
    name = clean_group_name(data.get("name"))
    network = clean_network(data.get("network"))
    group_id = data.get("id")
    store = _store()
    with store.transaction() as conn:
        clash = conn.execute("SELECT id FROM client_groups WHERE network=?", (network,)).fetchone()
        if group_id in (None, ""):
            if clash:
                raise Clients3Error(f"Für {network} gibt es schon eine Gruppe.")
            count = conn.execute("SELECT COUNT(*) FROM client_groups").fetchone()[0]
            if count >= MAX_GROUPS:
                raise Clients3Error(f"Höchstens {MAX_GROUPS} Gruppen.")
            cur = conn.execute("INSERT INTO client_groups(name, network, updated) VALUES(?, ?, ?)",
                               (name, network, time.time()))
            group_id = cur.lastrowid
        else:
            try:
                group_id = int(group_id)
            except (TypeError, ValueError):
                raise Clients3Error("Ungültige Gruppen-Kennung.") from None
            if clash and int(clash[0]) != group_id:
                raise Clients3Error(f"Für {network} gibt es schon eine Gruppe.")
            cur = conn.execute("UPDATE client_groups SET name=?, network=?, updated=? WHERE id=?",
                               (name, network, time.time(), group_id))
            if cur.rowcount == 0:
                raise Clients3Error("Diese Gruppe gibt es nicht (mehr).")
    _drop_group_cache()
    _forget_names()
    return {"id": int(group_id), "name": name, "network": network}


def delete_group(group_id: Any) -> bool:
    try:
        group_id = int(group_id)
    except (TypeError, ValueError):
        return False
    deleted = _store().execute("DELETE FROM client_groups WHERE id=?", (group_id,))
    _drop_group_cache()
    return bool(deleted)


def _forget_names() -> None:
    """Der Filter der Benachrichtigungen merkt sich bekannte Namen 10 min – neue sofort gelten lassen."""
    import sys
    notify_mod = sys.modules.get("notify")
    if notify_mod is not None and isinstance(getattr(notify_mod, "_KNOWN", None), dict):
        notify_mod._KNOWN["t"] = float("-inf")


def _address(ip: str):
    try:
        addr = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr


class GroupIndex:
    """Zuordnung Adresse → Gruppe: das spezifischste passende Netz gewinnt."""

    def __init__(self, items: list[dict]) -> None:
        nets = []
        for item in items or []:
            try:
                nets.append((ipaddress.ip_network(item["network"], strict=False), item))
            except (KeyError, ValueError, TypeError):
                continue
        nets.sort(key=lambda pair: -pair[0].prefixlen)
        self._nets = nets

    def find(self, ip: str) -> dict | None:
        addr = _address(ip)
        if addr is None:
            return None
        for net, item in self._nets:
            if net.version == addr.version and addr in net:
                return item
        return None


def suggest_networks(ips, items: list[dict], limit: int = 8) -> list[dict]:
    """Gesehene /24- (IPv4) und /64-Netze (IPv6), die noch keine Gruppe abdeckt – meiste Geräte zuerst."""
    index = GroupIndex(items)
    counts: dict[str, int] = {}
    for ip in ips:
        if index.find(ip) is not None:
            continue
        addr = _address(ip)
        if addr is None or addr.is_loopback or (addr.version == 6 and addr.is_link_local):
            continue
        net = ipaddress.ip_network(f"{addr}/{24 if addr.version == 4 else 64}", strict=False)
        counts[str(net)] = counts.get(str(net), 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"network": net, "count": n} for net, n in ranked[:limit]]


# ---------------------------------------------------------------------------
# Uhrgüte je Gerät
# ---------------------------------------------------------------------------

QUALITY_MIN_POINTS = 4
GOOD_OFFSET = 0.010               # „gut“ in den Gruppen: |Abweichung| unter 10 ms


def _linear_fit(points: list[tuple[float, float]]) -> tuple[float, float]:
    """(Achsenabschnitt, Steigung) nach kleinsten Quadraten; t relativ zum ersten Punkt."""
    t0 = points[0][0]
    xs = [t - t0 for t, _ in points]
    ys = [o for _, o in points]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return my, 0.0
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - slope * mx, slope


def _mad(values: list[float]) -> float:
    med = _median(values) or 0.0
    return 1.4826 * (_median([abs(v - med) for v in values]) or 0.0)


def regular_intervals(intervals: list) -> list[float]:
    """Abstände ohne Bursts (wie clientmon.typical_interval)."""
    values = [float(v) for v in intervals or [] if _num(v) is not None and v > 0]
    longer = [v for v in values if v >= clientmon.BURST_GAP]
    return longer or values


def _points_offset(value: float, edges: tuple, points: tuple) -> int:
    for edge, pts in zip(edges, points):
        if value < edge:
            return pts
    return points[-1] if len(points) > len(edges) else 0


def grade(score: int | None) -> tuple[str, str]:
    if score is None:
        return "nicht bewertbar", "muted"
    if score >= 85:
        return "sehr gut", "good"
    if score >= 70:
        return "gut", "good"
    if score >= 50:
        return "mäßig", "warn"
    return "schlecht", "crit"


def clock_quality(entry: dict, points: list | None = None) -> dict:
    """Uhrgüte 0–100 eines Geräts aus seinen letzten Messungen (private_entry["recent"]).

    Gangabweichung: Ein Gerät, das bei jeder Abfrage nachstellt, läuft zwischen zwei Abfragen um
    drift × Intervall weg – genau das misst die Anfrage (Sägezahn): drift ≈ Median(Abweichung) / Intervall.
    Läuft die Uhr dagegen frei (Abweichung wächst gleichmäßig), ist die Steigung die Gangabweichung.
    Gemessen (drift_ppm) wird der Gang nur, wenn er sich vom festen Versatz trennen lässt: frei laufend
    oder bei schwankenden Abständen (Regression über den Abstand). Bei gleichmäßigen Abständen gibt es
    nur eine Obergrenze (drift_bound_ppm = Median / Intervall, method „versatz_oder_gang“).
    Positiv = die Uhr des Geräts läuft zu schnell."""
    state = entry.get("state")
    out: dict[str, Any] = {"score": None, "components": [], "drift_ppm": None, "drift_err_ppm": None,
                           "drift_bound_ppm": None, "method": None, "interval": None, "jitter": None, "median": None, "n": 0}
    intervals = regular_intervals(entry.get("intervals") or [])
    interval = clientmon.typical_interval(entry.get("intervals") or []) or clientinfo.expected_interval(entry)
    out["interval"] = interval
    if state == clientmon.OBFUSCATED:
        out["text"] = ("nicht bewertbar – das Gerät verschleiert seine Sendezeit (chrony, NTPsec, NTS-Clients). "
                       "Das ist gutes Verhalten; messen lässt sich die Uhr dann nur aktiv.")
    elif state == clientmon.NO_TIMESTAMP:
        out["text"] = "nicht bewertbar – das Gerät schickt keine Uhrzeit mit (nur Nullen)."
    elif state not in (clientmon.OK, clientmon.WRONG_CLOCK):
        out["text"] = "nicht bewertbar – noch keine Anfrage gesehen."
    raw = points if points is not None else entry.get("recent") or []
    pts = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            t, o = _num(item[0]), _num(item[1])
            if t is not None and o is not None:
                pts.append((t, o))
    pts.sort()
    out["n"] = len(pts)
    if "text" in out:
        out["grade"], out["tone"] = grade(None)
        return out
    if state == clientmon.WRONG_CLOCK:
        out.update(score=0, text="Die Uhr liegt mehr als einen Tag daneben – sie wird offenbar gar nicht gestellt.")
        out["grade"], out["tone"] = grade(0)
        return out
    pts = [(t, o) for t, o in pts if abs(o) <= clientmon.ABSURD]
    if len(pts) < QUALITY_MIN_POINTS:
        out["text"] = f"noch zu wenige Messungen ({len(pts)} von {QUALITY_MIN_POINTS})."
        out["grade"], out["tone"] = grade(None)
        return out
    offs = [o for _, o in pts]
    med = _median(offs) or 0.0
    jitter_raw = _mad(offs)
    intercept, slope = _linear_fit(pts)
    t0 = pts[0][0]
    resid = [o - (intercept + slope * (t - t0)) for t, o in pts]
    jitter_res = _mad(resid)
    span = pts[-1][0] - pts[0][0]
    free = (span > 0 and (not interval or span >= 3 * interval)
            and abs(slope) * span > max(4 * jitter_res, 0.002) and jitter_res < 0.5 * max(jitter_raw, 1e-9))
    if free:
        out.update(method="frei", drift_ppm=slope * 1e6, jitter=jitter_res,
                   drift_err_ppm=(jitter_res / span * 1e6) if span else None)
        current = abs(pts[-1][1])
    else:
        out["jitter"] = jitter_raw
        current = abs(med)
        saw = _sawtooth(pts)
        if saw is not None:
            # Abstände schwanken genug: Abweichung = Versatz + Gang × Abstand seit der letzten Anfrage.
            bias, drift, err = saw
            out.update(method="saegezahn", drift_ppm=drift * 1e6, drift_err_ppm=err * 1e6, bias=bias)
        elif interval:
            # Gleichmäßige Abstände: Abweichung = Versatz + Gang × Intervall – beides ist nicht zu
            # trennen. Median / Intervall ist nur eine OBERGRENZE des Gangs (fester Versatz 0), keine
            # Messung: 5 ms fester Versatz bei 64 s sähen sonst wie „+78 ppm“ aus.
            drift = med / interval
            if abs(drift) <= MAX_PLAUSIBLE_DRIFT:
                out.update(method="versatz_oder_gang", drift_bound_ppm=drift * 1e6)
            else:
                out["method"] = "versatz"   # gleichbleibende Abweichung: eher fester Versatz als Gang
    out["median"] = med
    jitter = out["jitter"] or 0.0
    comps = []
    p = _points_offset(current, (0.001, 0.005, 0.02, 0.1, 1.0), (35, 30, 22, 12, 5))
    comps.append({"key": "offset", "label": "Abweichung", "points": p, "max": 35,
                  "value": current, "text": f"|Abweichung| {clientinfo.fmt_offset(current).lstrip('+')}"})
    p = _points_offset(jitter, (0.0005, 0.002, 0.01, 0.05), (25, 20, 12, 6))
    comps.append({"key": "stability", "label": "Stabilität", "points": p, "max": 25, "value": jitter,
                  "text": f"Streuung ± {clientinfo.fmt_offset(jitter).lstrip('+')}"})
    if len(intervals) >= 3:
        mean = sum(intervals) / len(intervals)
        cv = math.sqrt(sum((v - mean) ** 2 for v in intervals) / len(intervals)) / mean if mean > 0 else 1.0
        p = 20 if cv < 0.1 else 15 if cv < 0.3 else 8 if cv < 0.6 else 3
        text = f"Abstände schwanken um {cv * 100:.0f} %"
    else:
        cv, p, text = None, 0, "zu wenige Abstände bekannt"
    comps.append({"key": "regularity", "label": "Regelmäßigkeit", "points": p, "max": 20, "value": cv, "text": text})
    requests = entry.get("requests") or 0
    measured = entry.get("count") or 0
    share = measured / requests if requests else 0.0
    p = round(20 * min(1.0, share))
    comps.append({"key": "measurable", "label": "Messbarkeit", "points": p, "max": 20, "value": share,
                  "text": f"{measured} von {requests} Anfragen mit echter Uhrzeit"})
    score = int(sum(c["points"] for c in comps))
    out["score"] = score
    out["components"] = comps
    out["grade"], out["tone"] = grade(score)
    if out["drift_ppm"] is not None:
        how = ("die Abweichung wächst gleichmäßig – die Uhr läuft frei" if free
               else "aus dem Sägezahn zwischen zwei Abfragen")
        out["text"] = f"Gangabweichung ≈ {out['drift_ppm']:+.1f} ppm ({how})".replace(".", ",")
    elif out["method"] == "versatz_oder_gang":
        bound = f"{abs(out['drift_bound_ppm']):.1f}".replace(".", ",")
        out["text"] = (f"Gangabweichung höchstens ≈ {bound} ppm – fester Versatz und Gang lassen sich hier nicht "
                       f"trennen (dafür müssten die Abstände der Anfragen stärker schwanken). Abweichung "
                       f"{clientinfo.fmt_offset(med)} je {clientinfo._fmt_seconds(interval)}.")
    elif out["method"] == "versatz":
        out["text"] = (f"Die Abweichung bleibt bei etwa {clientinfo.fmt_offset(med)} – eher ein fester Versatz "
                       "(z. B. Laufzeit über WLAN/VPN oder ein Zeitdienst, der nur grob stellt) als eine weglaufende Uhr.")
    else:
        out["text"] = "Gangabweichung unbekannt – das Abfrage-Intervall ist noch nicht bekannt."
    return out


MAX_PLAUSIBLE_DRIFT = 200e-6     # mehr Gang hat kaum ein Quarz (typisch < 100 ppm) – dann eher fester Versatz
SAW_MIN_POINTS = 8
SAW_MIN_SPREAD = 0.08            # Abstände müssen um mindestens 8 % schwanken (Standardabweichung/Mittel),
                                 # sonst sind Versatz und Gang nicht zu trennen (dann nur eine Obergrenze)
SAW_MAX_ERR = 10e-6              # und die Steigung muss auf ±10 ppm bestimmt sein – sonst ebenfalls nur Obergrenze


def _sawtooth(pts: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """(Versatz, Gang, Unsicherheit des Gangs) aus Abweichung ~ Versatz + Gang × Abstand zur Vorgänger-Anfrage.

    Nur, wenn die Abstände genug schwanken (z. B. ntpd/chrony mit wechselndem Poll, IoT mit Zufallsanteil) –
    bei streng regelmäßigen Abständen lassen sich fester Versatz und Gang nicht unterscheiden."""
    pairs = []
    for (t1, _o1), (t2, o2) in zip(pts, pts[1:]):
        gap = t2 - t1
        if gap >= clientmon.BURST_GAP:
            pairs.append((gap, o2))
    if len(pairs) < SAW_MIN_POINTS:
        return None
    gaps = [g for g, _ in pairs]
    mean = sum(gaps) / len(gaps)
    spread = math.sqrt(sum((g - mean) ** 2 for g in gaps) / len(gaps)) / mean if mean > 0 else 0.0
    if spread < SAW_MIN_SPREAD:
        return None
    sxx = sum((g - mean) ** 2 for g in gaps)
    my = sum(o for _, o in pairs) / len(pairs)
    slope = sum((g - mean) * (o - my) for g, o in pairs) / sxx
    bias = my - slope * mean
    resid = [o - (bias + slope * g) for g, o in pairs]
    sigma = math.sqrt(sum(r * r for r in resid) / max(1, len(pairs) - 2))
    err = sigma / math.sqrt(sxx)
    if abs(slope) > MAX_PLAUSIBLE_DRIFT or err > SAW_MAX_ERR:
        return None
    return bias, slope, err


_QUALITY_CACHE: dict[str, Any] = {"t": None, "data": None}
QUALITY_TTL = 15.0


# Gespeicherte Messpunkte (24 h) für Geräte, deren Ring „recent“ noch zu kurz ist – z. B. direkt nach dem
# Update von 1.4 (der Ring ist neu und leer) oder bei seltenen Anfragen. Je Gerät einmal gelesen, danach
# mit dem Ring zusammengeführt; so zeigen Liste und Detailseite dieselbe Uhrgüte.
_BACKFILL: dict[str, list] = {}
BACKFILL_PER_CALL = 200          # höchstens so viele Geräte je Aufruf aus SQLite nachladen


def _stored_points(ips: list[str], since: float) -> dict[str, list]:
    out: dict[str, list] = {ip: [] for ip in ips}
    if not ips:
        return out
    try:
        import store
        clientmon._migrate(store)
        monitor = clientmon._MONITOR
        if monitor is not None:
            monitor.flush_samples(prune=False)
        marks = ",".join("?" for _ in ips)
        rows = store.query(f"SELECT ip, t, offset FROM clientmon_samples WHERE ip IN ({marks}) AND t >= ? "
                           "AND offset IS NOT NULL ORDER BY t", (*ips, since))
    except Exception:  # noqa: BLE001 – Uhrgüte ist ein Zusatz
        return out
    for ip, t, offset in rows:
        if _num(t) is not None and _num(offset) is not None:
            out.setdefault(ip, []).append([t, offset])
    return out


def _with_backfill(snap: dict[str, dict], wall: float) -> dict[str, list]:
    """{ip: Messpunkte} für Geräte mit zu kurzem Ring – Ring plus gespeicherte Punkte der letzten 24 h."""
    short = [ip for ip, e in snap.items() if isinstance(e, dict) and len(e.get("recent") or []) < QUALITY_MIN_POINTS
             and e.get("state") in (clientmon.OK, clientmon.WRONG_CLOCK)]
    missing = [ip for ip in short if ip not in _BACKFILL][:BACKFILL_PER_CALL]
    if missing:
        _BACKFILL.update(_stored_points(missing, wall - 86400))
    for ip in [ip for ip in _BACKFILL if ip not in snap]:
        del _BACKFILL[ip]
    out = {}
    for ip in short:
        stored = _BACKFILL.get(ip)
        if not stored:
            continue
        merged = {float(p[0]): p for p in stored if p[0] >= wall - 86400}
        for p in snap[ip].get("recent") or []:
            if isinstance(p, (list, tuple)) and len(p) >= 2 and _num(p[0]) is not None:
                merged[float(p[0])] = p
        out[ip] = [list(merged[t]) for t in sorted(merged)][-clientmon.RECENT_KEPT:]
    return out


def quality_all(snapshot: dict[str, dict] | None = None, fresh: bool = False,
                wall: float | None = None) -> dict[str, dict]:
    """{ip: Uhrgüte} für alle Geräte – 15 s zwischengespeichert (2000 Geräte ≈ wenige ms)."""
    now = time.monotonic()
    if snapshot is None and not fresh and _QUALITY_CACHE["data"] is not None and _QUALITY_CACHE["t"] is not None \
            and now - _QUALITY_CACHE["t"] < QUALITY_TTL:
        return _QUALITY_CACHE["data"]
    snap = clientmon.private_snapshot() if snapshot is None else snapshot
    extra = _with_backfill(snap, time.time() if wall is None else wall) if snapshot is None else {}
    data = {ip: clock_quality(entry, extra.get(ip)) for ip, entry in snap.items() if isinstance(entry, dict)}
    if snapshot is None:
        _QUALITY_CACHE.update(t=now, data=data)
    return data


def quality_overview(qualities: dict[str, dict], meta: dict | None = None, limit: int = 10) -> dict:
    """Kurzfassung für die Liste und „schlechteste Uhren im Haus“."""
    meta = meta if meta is not None else clientinfo.all_meta()
    scores = {}
    rated = []
    for ip, q in qualities.items():
        scores[ip] = {"score": q.get("score"), "grade": q.get("grade"), "tone": q.get("tone"),
                      "drift_ppm": q.get("drift_ppm"), "drift_bound_ppm": q.get("drift_bound_ppm")}
        if q.get("score") is not None:
            rated.append({"address": ip, "name": (meta.get(ip) or {}).get("name") or None,
                          "score": q["score"], "grade": q.get("grade"), "tone": q.get("tone"),
                          "drift_ppm": q.get("drift_ppm"), "drift_bound_ppm": q.get("drift_bound_ppm"),
                          "text": q.get("text")})
    rated.sort(key=lambda r: (r["score"], r["address"]))
    return {"scores": scores, "worst": rated[:limit], "rated": len(rated), "total": len(qualities)}


# ---------------------------------------------------------------------------
# Software: erwartet oder vermutet; NTS je Software
# ---------------------------------------------------------------------------

SOFTWARE_LABELS = {
    "windows": "Windows (w32time)", "timesyncd": "Linux mit systemd-timesyncd",
    "chrony": "chrony / NTPsec / OpenNTPD", "ntpd": "ntpd", "sntp": "SNTP / IoT",
    "apple": "Apple", "mobile": "Smartphone/Laptop",
}
EXPECT_KEYS = ("",) + tuple(SOFTWARE_LABELS)

# (kann NTS: True/False/None = je nach Variante, Erklärung)
NTS_SUPPORT = {
    "windows": (False, "Der Windows-Zeitdienst (w32time) kann kein NTS."),
    "timesyncd": (False, "systemd-timesyncd kann kein NTS – für NTS chrony installieren (`server <Name> iburst nts`)."),
    "chrony": (True, "chrony kann NTS ab Version 4.0: `server <Name> iburst nts` (NTPsec: `server <Name> nts`)."),
    "ntpd": (None, "Der klassische ntpd kann kein NTS, NTPsec schon (`server <Name> nts`)."),
    "sntp": (False, "Einfache SNTP-Clients (ESP32/ESP8266, Kameras, Drucker) können kein NTS."),
    "apple": (False, "macOS, iOS und tvOS können (noch) kein NTS."),
    "mobile": (False, "Smartphones lassen ihren Zeitdienst nicht umstellen – kein NTS."),
}


def software_key(ip: str, entry: dict, rule: dict | None, meta: dict | None = None,
                 guess: dict | None = None) -> tuple[str | None, str]:
    """(Schlüssel, Herkunft „erwartet“|„vermutet“|„unbekannt“)."""
    expect = (rule or {}).get("expect") or ""
    if expect in SOFTWARE_LABELS:
        return expect, "erwartet"
    if guess is None:
        # Wie clientinfo.detail: privater Eintrag (bare, stratum) plus Hersteller aus der MAC –
        # sonst wiche die Gruppen-Ansicht „nach Software“ von der Detailseite ab.
        name = ((meta or {}).get(ip) or {}).get("name") or ""
        guess = clientinfo.guess_software(entry, clientinfo.mac_info(entry.get("mac")), [name])
    candidates = guess.get("candidates") or []
    if candidates:
        return candidates[0]["key"], "vermutet"
    return None, "unbekannt"


_NTS_CACHE: dict[str, Any] = {"t": None, "data": {}}
NTS_TTL = 30.0


def nts_usage(cfg: dict, runner: Callable[[], list] | None = None) -> dict[str, dict]:
    """{ip: {"nts_ke": Anzahl, "last": s}} aus chronyc clients -k – nur bei eingeschaltetem NTS-Server."""
    if not cfg.get("nts_server_enable"):
        return {}
    now = time.monotonic()
    if runner is None and _NTS_CACHE["t"] is not None and now - _NTS_CACHE["t"] < NTS_TTL:
        return _NTS_CACHE["data"]
    if runner is None:
        import chrony
        runner = chrony.clients_nts
    data = {}
    try:
        rows = runner() or []
    except Exception:  # noqa: BLE001
        rows = []
    for row in rows:
        addr = clientinfo.clean_ip(row.get("address"))
        count = row.get("nts_ke")
        if addr and isinstance(count, int) and count > 0:
            data[addr] = {"nts_ke": count, "last": row.get("nts_ke_last_rx")}
    _NTS_CACHE.update(t=now, data=data)
    return data


def nts_for(ip: str, entry: dict, key: str | None, cfg: dict, usage: dict | None = None) -> dict:
    """NTS-Hinweis für ein Gerät: Server an? nutzt es NTS? könnte es?"""
    enabled = bool(cfg.get("nts_server_enable"))
    can, how = NTS_SUPPORT.get(key or "", (None, "Unbekannte Software – ob sie NTS kann, lässt sich nicht sagen."))
    out = {"server": enabled, "can": can, "how": how, "uses": None, "nts_ke": None,
           "server_name": cfg.get("nts_server_name") or None}
    if not enabled:
        out["text"] = ("Der NTS-Server dieser Instanz ist aus – Clients können NTS hier nicht nutzen "
                       "(Einstellungen → NTS → „NTS-Server für das LAN anbieten“).")
        return out
    use = (usage if usage is not None else nts_usage(cfg)).get(ip)
    if use:
        out.update(uses=True, nts_ke=use.get("nts_ke"))
        out["text"] = (f"Nutzt NTS: {use.get('nts_ke')} Schlüsselaustausch(e) über NTS-KE. Die Anfragen tragen dann "
                       "eine Zufallszahl statt der Uhrzeit – „nicht messbar“ ist hier gutes Verhalten.")
    else:
        out["uses"] = False
        out["text"] = ("Kein NTS-Schlüsselaustausch von diesem Gerät gesehen (seit dem letzten Start von chrony). "
                       + ("Es könnte NTS – siehe Empfehlung." if can else how))
    return out


# ---------------------------------------------------------------------------
# Gruppen-Ansichten
# ---------------------------------------------------------------------------

VIEW_BYS = ("group", "vlan", "software")
ACTIVE_WINDOW = 86400.0
EMPTY_GROUP_AFTER = 3600.0        # Hinweis für eine Gruppe ohne jedes Gerät erst, wenn die Messung so lange läuft


def _bucket(key: str, label: str, **extra) -> dict:
    out = {"key": key, "label": label, "members": [], "total": 0, "active": 0, "measured": 0,
           "median_offset": None, "good_share": None, "silent": 0, "worst": None, "score_median": None}
    out.update(extra)
    return out


def view(clients: dict[str, dict], by: str = "group", meta: dict | None = None, rules: dict | None = None,
         qualities: dict | None = None, items: list | None = None, now: float | None = None,
         monitor_since: float | None = None, running: bool = False) -> dict:
    """Geräte nach Gruppe (Netz), VLAN oder Software – je Gruppe Anzahl, Median, Anteil „gut“."""
    by = by if by in VIEW_BYS else "group"
    now = time.time() if now is None else now
    meta = meta if meta is not None else {}
    rules = rules if rules is not None else {}
    qualities = qualities or {}
    items = groups() if items is None else items
    buckets: dict[str, dict] = {}
    if by == "group":
        for g in items:
            buckets[f"g{g['id']}"] = _bucket(f"g{g['id']}", g["name"], network=g["network"], group_id=g["id"])
        index = GroupIndex(items)
    offsets: dict[str, list] = {}
    scores: dict[str, list] = {}
    for ip, entry in clients.items():
        if not isinstance(entry, dict):
            continue
        if by == "group":
            g = index.find(ip)
            key, label = (f"g{g['id']}", g["name"]) if g else ("none", "ohne Gruppe")
        elif by == "vlan":
            vlan = entry.get("vlan")
            key, label = (f"v{vlan}", f"VLAN {vlan}") if isinstance(vlan, int) else ("none", "ohne VLAN-Kennung")
        else:
            sw, _origin = software_key(ip, entry, rules.get(ip), meta)
            key, label = (sw, SOFTWARE_LABELS[sw]) if sw else ("none", "unbekannt")
        b = buckets.get(key)
        if b is None:
            b = buckets[key] = _bucket(key, label)
        b["members"].append(ip)
        b["total"] += 1
        last = entry.get("last_seen")
        if isinstance(last, (int, float)) and now - last < ACTIVE_WINDOW:
            b["active"] += 1
        if clientinfo.silent_reason(entry, now):
            b["silent"] += 1
        q = (qualities.get(ip) or {}).get("score")
        if q is not None:
            scores.setdefault(key, []).append(q)
        value = entry.get("ewma")
        if entry.get("measurable") and _num(value) is not None:
            b["measured"] += 1
            offsets.setdefault(key, []).append((abs(value), ip, entry.get("state")))
    for key, b in buckets.items():
        vals = offsets.get(key) or []
        if vals:
            b["median_offset"] = _median([v for v, _ip, _s in vals])
            good = sum(1 for v, _ip, s in vals if v < GOOD_OFFSET and s == clientmon.OK)
            b["good_share"] = good / len(vals)
            worst = max(vals)
            b["worst"] = {"address": worst[1], "offset": worst[0],
                          "name": (meta.get(worst[1]) or {}).get("name") or None}
        if scores.get(key):
            b["score_median"] = _median(scores[key])
        b["members"].sort(key=lambda ip: (((meta.get(ip) or {}).get("name") or "~").lower(), ip))
        b["hint"] = None
        listened = (now - monitor_since) if isinstance(monitor_since, (int, float)) else None
        if by == "group" and key != "none" and b["active"] == 0 and running and listened is not None:
            # Gezählt wird nur, solange ntp-gui mithört: Nach 2 Tagen Pause sind alle gespeicherten
            # „zuletzt gesehen“ älter als 24 h – das heißt noch nicht, dass dort niemand fragt.
            hint = None
            if listened >= ACTIVE_WINDOW:
                hint = "fragt seit 24 h kein Gerät bei dir"
            elif b["total"] == 0 and listened >= EMPTY_GROUP_AFTER:
                hint = f"hat noch kein Gerät bei dir gefragt, seit ntp-gui mithört ({_fmt_hours(listened)})"
            if hint:
                b["hint"] = (f"In „{b['label']}“ ({b.get('network')}) {hint} – fehlt dort die "
                             "Umleitung oder die DHCP-Option 42? Siehe „Zeitserver erzwingen“.")
    ordered = sorted(buckets.values(), key=lambda b: (b["key"] == "none", -b["total"], b["label"].lower()))
    out = {"by": by, "groups": ordered, "total": len(clients),
           "defined": items if by == "group" else None}
    if by == "group":
        out["suggestions"] = suggest_networks(list(clients), items)
    return out


# ---------------------------------------------------------------------------
# Regeln je Gerät
# ---------------------------------------------------------------------------

_RULE_CACHE: dict[str, Any] = {"t": None, "data": None}


def _bounded(value: Any, lo: float, hi: float, label: str, integer: bool = False) -> float | int | None:
    if value is None or value == "" or value is False:
        return None
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        raise Clients3Error(f"{label}: keine Zahl.") from None
    if not math.isfinite(number) or number < lo or number > hi:
        raise Clients3Error(f"{label}: erlaubt sind {lo:g} bis {hi:g}.".replace(".", ","))
    return int(round(number)) if integer else number


def clean_rule(data: dict) -> dict:
    """Allowlist: nur diese Felder, nur diese Bereiche."""
    silent = _bounded(data.get("silent_h"), 0.25, 720, "Stunden ohne Anfrage")
    offset = _bounded(data.get("offset_ms"), 1, 86_400_000, "Schwelle in ms", integer=True)
    minutes = _bounded(data.get("offset_min"), 0, 1440, "Minuten über der Schwelle", integer=True) or 0
    mute = data.get("mute")
    if mute not in (None, True, False, 0, 1):
        raise Clients3Error("„Stumm“ muss ja oder nein sein.")
    expect = str(data.get("expect") or "")
    if expect not in EXPECT_KEYS:
        raise Clients3Error("Unbekannte Software – erlaubt: " + ", ".join(k for k in EXPECT_KEYS if k) + ".")
    return {"silent_h": silent, "offset_ms": offset, "offset_min": int(minutes), "mute": bool(mute),
            "expect": expect}


def rules(fresh: bool = False) -> dict[str, dict]:
    """{ip: {silent_h, offset_ms, offset_min, mute, expect, state}} – 30 s zwischengespeichert."""
    now = time.monotonic()
    cached = _RULE_CACHE["data"]
    if not fresh and cached is not None and _RULE_CACHE["t"] is not None and now - _RULE_CACHE["t"] < CACHE_TTL:
        return cached
    try:
        rows = _store().query("SELECT ip, silent_h, offset_ms, offset_min, mute, expect, state FROM client_rules")
    except Exception:  # noqa: BLE001
        rows = []
    data = {}
    for ip, silent, offset, minutes, mute, expect, state in rows:
        try:
            st = json.loads(state or "{}")
        except ValueError:
            st = {}
        data[ip] = {"silent_h": silent, "offset_ms": offset, "offset_min": int(minutes or 0),
                    "mute": bool(mute), "expect": expect or "", "state": st if isinstance(st, dict) else {}}
    _RULE_CACHE.update(t=now, data=data)
    return data


def _drop_rule_cache() -> None:
    _RULE_CACHE.update(t=None, data=None)


def public_rule(rule: dict | None) -> dict:
    rule = rule or {}
    st = rule.get("state") or {}
    return {"silent_h": rule.get("silent_h"), "offset_ms": rule.get("offset_ms"),
            "offset_min": rule.get("offset_min") or 0, "mute": bool(rule.get("mute")),
            "expect": rule.get("expect") or "",
            "silent_alarm": bool(st.get("silent")), "offset_alarm": bool(st.get("offset"))}


def save_rule(ip: Any, data: Any, emit: Callable[..., Any] | None = None) -> dict:
    """Regel speichern (leere Regel = löschen). Schließt dabei offene Alarme der geänderten Regel mit
    einem stillen „info“-Ereignis (emit, Standard events.emit) – sonst bliebe der Betreff in den
    Benachrichtigungen offen und jeder spätere Alarm für das Gerät gälte als „schon gemeldet“."""
    addr = clientinfo.clean_ip(ip)
    if addr is None:
        raise Clients3Error("Ungültige IP-Adresse.")
    if not isinstance(data, dict):
        raise Clients3Error("Erwartet: {\"ip\": …, \"silent_h\": …, \"offset_ms\": …}")
    rule = clean_rule(data)
    current = rules(fresh=True).get(addr) or {}
    state = dict(current.get("state") or {})
    # Geänderte Regel: ihren Alarmzustand vergessen (sonst bliebe „still“ nach dem Löschen offen) –
    # und einen offenen Alarm ausdrücklich schließen.
    closing = []
    if rule["silent_h"] != current.get("silent_h"):
        if state.pop("silent", None):
            closing.append(("still", "silent", f"Regel „fragt nicht mehr“ für {addr} geändert – Alarm beendet"))
        state.pop("silent_last", None)
    if rule["offset_ms"] != current.get("offset_ms") or rule["offset_min"] != current.get("offset_min"):
        if state.pop("offset", None):
            closing.append(("abw", "offset", f"Eigene Schwelle für {addr} geändert – Alarm beendet"))
    store = _store()
    empty = rule["silent_h"] is None and rule["offset_ms"] is None and not rule["mute"] and not rule["expect"]
    with store.transaction() as conn:
        if empty:
            conn.execute("DELETE FROM client_rules WHERE ip=?", (addr,))
        else:
            if not current:
                count = conn.execute("SELECT COUNT(*) FROM client_rules").fetchone()[0]
                if count >= MAX_RULES:
                    raise Clients3Error(f"Höchstens {MAX_RULES} Geräte mit eigenen Regeln.")
            conn.execute("INSERT INTO client_rules(ip, silent_h, offset_ms, offset_min, mute, expect, state, updated) "
                         "VALUES(?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(ip) DO UPDATE SET silent_h=excluded.silent_h, "
                         "offset_ms=excluded.offset_ms, offset_min=excluded.offset_min, mute=excluded.mute, "
                         "expect=excluded.expect, state=excluded.state, updated=excluded.updated",
                         (addr, rule["silent_h"], rule["offset_ms"], rule["offset_min"], int(rule["mute"]),
                          rule["expect"], json.dumps(state), time.time()))
    _drop_rule_cache()
    WATCH.forget(addr)
    if closing:
        if emit is None:
            import events
            emit = events.emit
        for suffix, kind, title in closing:
            try:
                emit("clients", "info", title, {"address": addr, "subject": f"{addr}#{suffix}", "rule": kind,
                                                "resolves": True, "notify": False})
            except Exception:  # noqa: BLE001 – Ereignisse sind nie kritisch
                pass
    return {"ip": addr, **public_rule({**rule, "state": state})}


def _save_state(ip: str, state: dict) -> None:
    try:
        _store().execute("UPDATE client_rules SET state=? WHERE ip=?", (json.dumps(state), ip))
    except Exception:  # noqa: BLE001
        pass
    cached = _RULE_CACHE["data"]
    if cached is not None and ip in cached:
        cached[ip]["state"] = state


def is_muted(ip: str) -> bool:
    return bool((rules().get(ip) or {}).get("mute"))


def global_alarm_filter(clients: dict[str, dict], rule_map: dict | None = None) -> dict[str, dict]:
    """Geräte mit eigener Schwelle aus dem allgemeinen Alarm (clients_alarm_ms) herausnehmen."""
    rule_map = rules() if rule_map is None else rule_map
    return {ip: e for ip, e in clients.items() if (rule_map.get(ip) or {}).get("offset_ms") is None}


def own_threshold_ips(rule_map: dict | None = None) -> set[str]:
    """Geräte, deren Abweichung eine eigene Schwelle prüft (Übergabe vom allgemeinen Alarm)."""
    rule_map = rules() if rule_map is None else rule_map
    return {ip for ip, r in rule_map.items() if (r or {}).get("offset_ms") is not None}


def _fmt_hours(seconds: float) -> str:
    return clientinfo._fmt_seconds(max(0.0, seconds))


class RuleWatch:
    """Wertet die Regeln je Gerät aus. Reine Logik: Uhr und emit werden eingespeist.

    Alarmzustände („still“, „über der Schwelle“) stehen in client_rules.state – nach einem Neustart
    wird nichts doppelt gemeldet, und „wieder da“ kommt trotzdem. Flüchtig (nur im Speicher): seit
    wann eine Abweichung über der Schwelle liegt und der letzte gezählte Messzähler.

    Stille misst die monotone Uhr (mono): Ein Pi ohne Echtzeituhr, dessen Systemzeit chrony nach dem
    Start stellt, darf nicht „fragt seit 3 h nicht mehr“ melden, nur weil die Wanduhr gesprungen ist.
    „Fragt wieder“ heißt: eine neue Anfrage seit dem Alarm (Zähler oder last_seen geändert) – nicht
    „last_seen größer als damals“, das bliebe nach einem Rücksprung der Uhr hängen."""

    CONFIRM = 2

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, dict] = {}

    def forget(self, ip: str) -> None:
        with self._lock:
            self._live.pop(ip, None)

    def evaluate(self, clients: dict[str, dict], rule_map: dict[str, dict], now: float,
                 emit: Callable[..., Any], monitor_since: float | None, running: bool,
                 save: Callable[[str, dict], None] = _save_state, mono: float | None = None,
                 listening: float | None = None) -> None:
        """now: Wanduhr (nur für Texte und als erste Schätzung); mono: monotone Uhr (Standard: now –
        für Tests); listening: wie lange die Messung schon mithört, monoton gemessen (Obergrenze der
        ersten Schätzung „still seit“)."""
        mono = now if mono is None else mono
        if not running:
            return  # ohne laufende Messung wissen wir nicht, ob ein Gerät still ist
        with self._lock:
            for ip in [ip for ip in self._live if ip not in rule_map]:
                del self._live[ip]
            for ip, rule in rule_map.items():
                entry = clients.get(ip)
                if not isinstance(entry, dict):
                    continue
                state = dict(rule.get("state") or {})
                before = dict(state)
                extra = {"notify": False} if rule.get("mute") else {}
                self._silent(ip, rule, entry, state, now, mono, listening, emit, monitor_since, extra)
                self._offset(ip, rule, entry, state, now, mono, emit, extra)
                if state != before:
                    save(ip, state)

    def _silent(self, ip, rule, entry, state, now, mono, listening, emit, monitor_since, extra) -> None:
        hours = rule.get("silent_h")
        last = entry.get("last_seen")
        if not hours or not isinstance(last, (int, float)):
            return
        live = self._live.setdefault(ip, {"count": None, "over_since": None, "streak": 0})
        marker = (entry.get("requests"), last)
        asked = False
        if live.get("seen") is None:
            # Erste Sicht (Start, Regel neu): Stille aus der Wanduhr schätzen, aber nur die Zeit, in der
            # ntp-gui auch mitgehört hat (nach einem Neustart nicht sofort „seit 10 h still“, nur weil der
            # Container 10 h aus war) – und höchstens so lange, wie die Messung monoton läuft.
            start = max(last, monitor_since) if isinstance(monitor_since, (int, float)) else last
            guess = max(0.0, now - start)
            if isinstance(listening, (int, float)):
                guess = min(guess, max(0.0, listening))
            live.update(seen=marker, quiet_since=mono - guess)
        elif marker != live["seen"]:
            live.update(seen=marker, quiet_since=mono)
            asked = True
        quiet = mono - live["quiet_since"]
        if state.get("silent"):
            silent_last = state.get("silent_last")
            # Neue Anfrage seit dem Alarm: in diesem Lauf gesehen, oder (nach einem Neustart) last_seen
            # anders als beim Alarm – „anders“, nicht „größer“: nach einem Rücksprung der Uhr ist es kleiner.
            if asked or (isinstance(silent_last, (int, float)) and last != silent_last):
                was = live.get("alarm_mono")   # nur im Speicher: monoton gilt nur bis zum nächsten Neustart
                quiet_was = (mono - was) if was is not None else max(0.0, last - (silent_last or last))
                emit("clients", "info", f"{ip} fragt wieder nach der Zeit (war {_fmt_hours(quiet_was)} still)",
                     {"address": ip, "subject": f"{ip}#still", "rule": "silent", **extra})
                state.pop("silent", None)
                state.pop("silent_last", None)
                live.pop("alarm_mono", None)
            return
        if quiet > hours * 3600:
            # Anzeige: Wanduhr, wenn sie plausibel ist (≥ gemessene Stille), sonst die gemessene Stille.
            shown = now - last if now - last >= quiet else quiet
            emit("clients", "warn", f"{ip} fragt seit {_fmt_hours(shown)} nicht mehr nach der Zeit",
                 {"address": ip, "subject": f"{ip}#still", "rule": "silent", "silent_h": hours,
                  "last_seen": last, **extra})
            state["silent"] = True
            state["silent_last"] = last
            live["alarm_mono"] = live["quiet_since"]

    def _offset(self, ip, rule, entry, state, now, mono, emit, extra) -> None:
        threshold_ms = rule.get("offset_ms")
        if not threshold_ms or not entry.get("measurable"):
            return
        value = _num(entry.get("offset"))
        count = entry.get("count")
        if value is None:
            return
        live = self._live.setdefault(ip, {"count": None, "over_since": None, "streak": 0})
        if count == live["count"]:
            return
        live["count"] = count
        threshold = threshold_ms / 1000.0
        minutes = rule.get("offset_min") or 0
        fmt = clientinfo.fmt_offset
        if not state.get("offset"):
            if abs(value) > threshold:
                live["streak"] += 1
                if live["over_since"] is None:
                    live["over_since"] = mono
                if live["streak"] >= self.CONFIRM and mono - live["over_since"] >= minutes * 60:
                    lasting = f" seit {_fmt_hours(mono - live['over_since'])}" if minutes else ""
                    emit("clients", "warn", f"Uhr von {ip} weicht um {fmt(value)} ab{lasting} (eigene Schwelle)",
                         {"address": ip, "subject": f"{ip}#abw", "rule": "offset", "offset": value,
                          "threshold_ms": threshold_ms, "minutes": minutes, **extra})
                    state["offset"] = True
                    live.update(streak=0, over_since=None)
            else:
                live.update(streak=0, over_since=None)
        else:
            if abs(value) < threshold / 2:
                live["streak"] += 1
                if live["streak"] >= self.CONFIRM:
                    emit("clients", "info", f"Uhr von {ip} wieder im Rahmen ({fmt(value)})",
                         {"address": ip, "subject": f"{ip}#abw", "rule": "offset", "offset": value,
                          "threshold_ms": threshold_ms, **extra})
                    state.pop("offset", None)
                    live.update(streak=0, over_since=None)
            else:
                live["streak"] = 0


WATCH = RuleWatch()


# ---------------------------------------------------------------------------
# Inventar: „Neues Gerät fragt nach der Zeit“
# ---------------------------------------------------------------------------

def inventory_key(ip: str, entry: dict) -> str | None:
    """MAC (im selben Netz) – sonst die IPv4-Adresse. IPv6 ohne MAC: None (Datenschutz-Adressen
    wechseln täglich, jede wäre „neu“)."""
    mac = entry.get("mac")
    if isinstance(mac, str) and mac:
        return "mac:" + mac.lower()
    addr = _address(ip)
    if addr is not None and addr.version == 4:
        return "ip:" + str(addr)
    return None


class Inventory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._known: set | None = None
        self._since: float | None = None
        self._sent: list[float] = []
        self._held = 0

    def reset(self) -> None:
        with self._lock:
            self._known = None
            self._since = None
            self._sent = []
            self._held = 0

    def _load(self, now: float) -> None:
        store = _store()
        self._known = {k for (k,) in store.query("SELECT key FROM client_inventory")}
        since = _meta_get("inventory_since")
        try:
            self._since = float(since) if since is not None else None
        except ValueError:
            self._since = None
        self._check_since(now)

    def _check_since(self, now: float) -> None:
        """Beginn der Lernzeit festlegen bzw. berichtigen. Liegt er in der Zukunft (Uhr stand vorher
        falsch) oder vor 2024 (Uhr noch nicht gestellt), beginnt die Lernzeit jetzt – sonst würde sie
        übersprungen oder endlos verlängert. Solange die eigene Uhr unplausibel ist: weiter lernen."""
        if now < PLAUSIBLE_WALL:
            self._since = None
            return
        if self._since is None or self._since > now + 3600 or self._since < PLAUSIBLE_WALL:
            self._since = now
            _meta_set("inventory_since", repr(now))

    def check(self, snapshot: dict[str, dict], now: float, enabled: bool, emit: Callable[..., Any]) -> int:
        """Neue Geräte lernen; nach der Lernzeit (und nur eingeschaltet) melden. Rückgabe: Zahl neuer."""
        with self._lock:
            if self._known is None:
                self._load(now)
            else:
                self._check_since(now)
            new = []
            for ip, entry in snapshot.items():
                if not isinstance(entry, dict) or not (entry.get("requests") or 0):
                    continue
                key = inventory_key(ip, entry)
                if key is None or key in self._known:
                    continue
                self._known.add(key)
                new.append((key, ip))
            if not new:
                self._flush_held(now, enabled, emit)
                return 0
            store = _store()
            with store.transaction() as conn:
                conn.executemany("INSERT OR IGNORE INTO client_inventory(key, first_seen) VALUES(?, ?)",
                                 [(key, now) for key, _ip in new])
                conn.execute("DELETE FROM client_inventory WHERE key IN (SELECT key FROM client_inventory "
                             "ORDER BY first_seen DESC LIMIT -1 OFFSET ?)", (INVENTORY_MAX,))
            learning = self._since is None or now - self._since < INVENTORY_LEARN
            if enabled and not learning:
                self._sent = [t for t in self._sent if now - t < 3600]
                for _key, ip in new:
                    if len(self._sent) >= NEW_DEVICE_PER_HOUR:
                        self._held += 1
                        continue
                    self._sent.append(now)
                    emit("clients", "warn", f"Neues Gerät fragt nach der Zeit: {ip}",
                         {"address": ip, "subject": f"{ip}#neu", "rule": "new_device", "standalone": True,
                          "resolves": False})
            self._flush_held(now, enabled, emit)
            return len(new)

    def _flush_held(self, now: float, enabled: bool, emit) -> None:
        if not self._held:
            return
        self._sent = [t for t in self._sent if now - t < 3600]
        if not enabled:
            self._held = 0
        elif len(self._sent) < NEW_DEVICE_PER_HOUR:
            self._sent.append(now)
            emit("clients", "warn", f"{self._held} weitere neue Geräte fragen nach der Zeit (zusammengefasst)",
                 {"subject": "neu#sammel", "rule": "new_device", "count": self._held, "standalone": True,
                  "resolves": False})
            self._held = 0

    def status(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            since = self._since
            known = len(self._known) if self._known is not None else None
        return {"since": since, "known": known,
                "learning": since is None or now - since < INVENTORY_LEARN,
                "learn_until": (since + INVENTORY_LEARN) if since is not None else None}


INVENTORY = Inventory()


# ---------------------------------------------------------------------------
# Stundenwerte je Gerät (30 Tage)
# ---------------------------------------------------------------------------

def aggregate_hours(now: float | None = None, store_mod=None) -> int:
    """Abgeschlossene Stunden aus clientmon_samples zu client_hourly zusammenfassen. Rückgabe: Stunden."""
    now = time.time() if now is None else now
    store = store_mod or _store()
    if store_mod is not None:
        _migrate(store_mod)
    current = int((now - HOURLY_SETTLE) // 3600)  # diese Stunde (und spätere) sind noch nicht fertig
    done = None
    try:
        rows = store.query("SELECT value FROM clients3_meta WHERE key='hourly_done'")
        done = int(rows[0][0]) if rows else None
    except (ValueError, TypeError):
        done = None
    if done is not None and done > current:
        # Die Uhr stand einmal in der Zukunft (Pi ohne Echtzeituhr vor dem ersten Stellen): sonst
        # stünde die Zusammenfassung still, bis diese Zeit wieder erreicht ist. Neu nachrechnen
        # (INSERT OR REPLACE) ist harmlos.
        done = None
    start = current - HOURLY_BACKFILL_H if done is None else max(done + 1, current - HOURLY_BACKFILL_H)
    end = min(current, start + HOURLY_PER_TICK)
    hours = 0
    for hour in range(start, end):
        rows = store.query("SELECT ip, offset FROM clientmon_samples WHERE t >= ? AND t < ? AND offset IS NOT NULL",
                           (hour * 3600.0, (hour + 1) * 3600.0))
        by_ip: dict[str, list] = {}
        for ip, offset in rows:
            if _num(offset) is not None and abs(offset) <= clientmon.ABSURD:
                by_ip.setdefault(ip, []).append(offset)
        values = []
        for ip, offs in list(by_ip.items())[:clientmon.MAX_CLIENTS]:
            values.append((ip, hour, len(offs), _median(offs), _quantile([abs(o) for o in offs], 0.95),
                           min(offs), max(offs)))
        with store.transaction() as conn:
            if values:
                conn.executemany("INSERT OR REPLACE INTO client_hourly(ip, hour, n, med, p95, lo, hi) "
                                 "VALUES(?, ?, ?, ?, ?, ?, ?)", values)
            conn.execute("INSERT INTO clients3_meta(key, value) VALUES('hourly_done', ?) ON CONFLICT(key) "
                         "DO UPDATE SET value=excluded.value", (str(hour),))
        hours += 1
    if hours:
        store.execute("DELETE FROM client_hourly WHERE hour < ?", (current - HOURLY_RETENTION_H,))
    return hours


def hourly(ip: str, since: float | None = None) -> list[list]:
    """[[Stundenbeginn, n, Median, P95 |Abw.|, min, max], …] aufsteigend (höchstens 30 Tage)."""
    since = time.time() - HOURLY_RETENTION_H * 3600 if since is None else since
    rows = _store().query("SELECT hour, n, med, p95, lo, hi FROM client_hourly WHERE ip=? AND hour >= ? "
                          "ORDER BY hour", (ip, int(since // 3600)))
    return [[h * 3600, n, med, p95, lo, hi] for h, n, med, p95, lo, hi in rows]


# ---------------------------------------------------------------------------
# Takt (aus dem Mess-Thread des Servers)
# ---------------------------------------------------------------------------

_TICK: dict[str, Any] = {"hourly": None}
HOURLY_CHECK = 600.0


def tick(cfg: dict, emit: Callable[..., Any], now: float | None = None) -> None:
    """Regeln, Inventar und Stundenwerte – wirft nie (Fehler landen im Log)."""
    now = time.time() if now is None else now
    try:
        status = clientmon.status()
        running = bool(status.get("running"))
        if running:
            WATCH.evaluate(status.get("clients") or {}, rules(), now, emit, status.get("since"), running,
                           mono=time.monotonic(), listening=clientmon.listening_seconds())
            if cfg.get("clientmon_enable", True):
                INVENTORY.check(clientmon.private_snapshot(), now, bool(cfg.get("clients_new_device_alarm")), emit)
    except Exception as exc:  # noqa: BLE001
        print(f"[web] Regeln je Gerät nicht geprüft: {exc}", flush=True)
    mono = time.monotonic()
    if _TICK["hourly"] is None or mono - _TICK["hourly"] >= HOURLY_CHECK:
        _TICK["hourly"] = mono
        try:
            aggregate_hours(now)
        except Exception as exc:  # noqa: BLE001
            print(f"[web] Stundenwerte der Clients nicht berechnet: {exc}", flush=True)


# ---------------------------------------------------------------------------
# Detailseite und Gerätepass
# ---------------------------------------------------------------------------

def _recent_from_samples(ip: str, now: float) -> list:
    try:
        rows = clientmon.samples(ip, now - 86400)
    except Exception:  # noqa: BLE001
        return []
    return [[r[0], r[1]] for r in rows if _num(r[1]) is not None][-clientmon.RECENT_KEPT:]


def expect_mismatch(rule: dict | None, guess: dict) -> str | None:
    expect = (rule or {}).get("expect") or ""
    candidates = guess.get("candidates") or []
    if not expect or not candidates:
        return None
    keys = [c["key"] for c in candidates]
    best = candidates[0]
    if expect in keys or best.get("confidence") != "wahrscheinlich":
        return None
    return (f"Erwartet: {SOFTWARE_LABELS[expect]} – die Anfragen sehen aber eher nach „{best['label']}“ aus. "
            "Wurde das Gerät getauscht, oder hat es eine andere Adresse bekommen?")


def detail_extras(ip: str, detail: dict, cfg: dict, now: float | None = None) -> dict:
    """Ergänzt clientinfo.detail(): Uhrgüte, Regel, Gruppe, Software-Abgleich, NTS."""
    now = time.time() if now is None else now
    entry = detail.get("entry") or {}
    points = entry.get("recent") or []
    if len(points) < QUALITY_MIN_POINTS:
        # Nach einem Neustart oder bei seltenen Anfragen: die gespeicherten Messpunkte der letzten 24 h.
        points = _recent_from_samples(ip, now) or points
    quality = clock_quality(entry, points)
    rule = rules().get(ip)
    group = GroupIndex(groups()).find(ip)
    key, origin = software_key(ip, entry, rule, guess=detail.get("software") or {})
    return {
        "quality": quality,
        "rule": public_rule(rule),
        "group": group,
        "software_key": key, "software_origin": origin,
        "expect_options": [{"key": k, "label": SOFTWARE_LABELS[k]} for k in SOFTWARE_LABELS],
        "expect_mismatch": expect_mismatch(rule, detail.get("software") or {}),
        "nts": nts_for(ip, entry, key, cfg),
        "lan_addresses_in_messages": bool(cfg.get("notify_lan_addresses")),
    }


SERVER_PLACEHOLDER = "<IP-des-Servers>"


def recommendations(key: str | None, entry: dict, quality: dict, nts: dict, silent: str | None) -> list[dict]:
    """Konkrete Empfehlungen für den Gerätepass. Code enthält SERVER_PLACEHOLDER (die Seite setzt die
    Adresse ein, die sie kennt)."""
    ip = SERVER_PLACEHOLDER
    name = nts.get("server_name") or "<Name-aus-dem-Zertifikat>"
    out = []
    if key == "windows":
        out.append({"title": "Windows: diesen Server fest eintragen (als Administrator)",
                    "code": f'w32tm /config /manualpeerlist:"{ip},0x8" /syncfromflags:manual /update\nw32tm /resync /force'})
    elif key == "timesyncd":
        out.append({"title": "systemd-timesyncd: /etc/systemd/timesyncd.conf",
                    "code": f"[Time]\nNTP={ip}\n\nsudo systemctl restart systemd-timesyncd"})
    elif key == "chrony":
        line = f"server {name} iburst nts" if nts.get("server") else f"server {ip} iburst"
        out.append({"title": "chrony: /etc/chrony/chrony.conf", "code": f"{line}\n\nsudo systemctl restart chrony"})
    elif key == "ntpd":
        out.append({"title": "ntpd: /etc/ntp.conf", "code": f"server {ip} iburst\n\nsudo systemctl restart ntp"})
    elif key == "apple":
        out.append({"title": "macOS: Zeitserver setzen", "code": f"sudo systemsetup -setnetworktimeserver {ip}"})
        out.append({"title": "iPhone/iPad", "code": "Lässt sich nicht einstellen – nutze „Zeitserver erzwingen“ "
                                                     "(DNS-Umschreibung von time.apple.com)."})
    elif key == "sntp":
        out.append({"title": "IoT-Gerät (ESP32/ESP8266, Kamera, Drucker)",
                    "code": f"Zeitserver in der Weboberfläche/App auf {ip} stellen oder per DHCP Option 42 verteilen.\n"
                            f"ESP-IDF: esp_sntp_setservername(0, \"{ip}\");"})
    elif key == "mobile":
        out.append({"title": "Smartphone", "code": "Lässt sich nicht einstellen – nutze „Zeitserver erzwingen“ "
                                                   "(DNS-Umschreibung)."})
    else:
        out.append({"title": "Per DHCP verteilen (Option 42)", "code": f"dhcp-option=42,{ip}"})
    if nts.get("server") and nts.get("can") and not nts.get("uses") and key not in ("chrony",):
        out.append({"title": "NTS nutzen (NTPsec)", "code": f"server {name} nts"})
    drift = quality.get("drift_ppm")
    interval = quality.get("interval")
    median = quality.get("median")
    if isinstance(median, (int, float)) and abs(median) > 1.0:
        out.append({"title": "Uhr stellt sich kaum nach",
                    "code": "Die Abweichung liegt über 1 s. Prüfe, ob das Gerät diesen Server wirklich nutzt "
                            "(Zeitzone ist es nicht – NTP läuft immer in UTC) und ob sein Zeitdienst läuft."})
    if isinstance(drift, (int, float)) and isinstance(interval, (int, float)) and abs(drift) > 100 and interval > 900:
        out.append({"title": "Öfter fragen lassen",
                    "code": f"Die Uhr läuft um {abs(drift):.0f} ppm weg und das Gerät fragt nur alle "
                            f"{clientinfo._fmt_seconds(interval)} – ein kürzeres Intervall hält sie genauer."})
    if silent:
        out.append({"title": "Fragt nicht mehr", "code": f"{silent}. Ist das Gerät aus, oder fragt es inzwischen "
                                                       "einen anderen Server?"})
    return out


def _offset_stats(samples: list) -> dict:
    offs = [r[1] for r in samples if _num(r[1]) is not None and abs(r[1]) <= clientmon.ABSURD]
    if not offs:
        return {"n": 0, "median": None, "p95": None}
    return {"n": len(offs), "median": _median(offs), "p95": _quantile([abs(o) for o in offs], 0.95)}


def device_pass(ip: Any, cfg: dict, now: float | None = None) -> dict | None:
    """Alles für den Gerätepass (lokale Druckseite). None, wenn das Gerät unbekannt ist."""
    now = time.time() if now is None else now
    # Ohne Reverse-DNS: der Pass soll keine DNS-Anfrage auslösen.
    detail = clientinfo.detail(ip, {**cfg, "clients_rdns": False}, now - clientmon.SAMPLE_RETENTION)
    if detail is None:
        return None
    addr = detail["address"]
    extras = detail_extras(addr, detail, cfg, now)
    entry = detail.get("entry") or {}
    samples = detail.get("samples") or []
    days: dict[int, list] = {}
    for row in samples:
        if _num(row[1]) is not None and abs(row[1]) <= clientmon.ABSURD:
            days.setdefault(int(row[0] // 86400), []).append(row[1])
    daily = [[d * 86400, _median(v), len(v)] for d, v in sorted(days.items())]
    try:
        hours = hourly(addr)
    except Exception:  # noqa: BLE001
        hours = []
    month = [h[2] for h in hours if _num(h[2]) is not None]
    key = extras["software_key"]
    return {
        "address": addr, "name": detail.get("name") or "", "note": detail.get("note") or "",
        "generated": now,
        "group": extras["group"],
        "software": {"key": key, "label": SOFTWARE_LABELS.get(key or "", "unbekannt"),
                     "origin": extras["software_origin"], "guess": detail.get("software")},
        "entry": {k: entry.get(k) for k in ("state", "state_text", "measurable", "ewma", "interval", "poll", "version",
                                            "first_seen", "last_seen", "requests", "count", "vlan")},
        "week": _offset_stats(samples), "daily": daily,
        "series": [[r[0], r[1]] for r in samples if _num(r[1]) is not None],
        "month": {"hours": len(hours), "median": _median(month),
                  "p95": _quantile([h[3] for h in hours if _num(h[3]) is not None], 0.95)},
        "quality": extras["quality"], "nts": extras["nts"], "rule": extras["rule"],
        "silent": detail.get("silent"),
        "recommendations": recommendations(key, entry, extras["quality"], extras["nts"], detail.get("silent")),
        "server_placeholder": SERVER_PLACEHOLDER,
    }


def _fmt_ago(seconds: float | None) -> str:
    if not isinstance(seconds, (int, float)):
        return "–"
    return f"vor {clientinfo._fmt_seconds(max(0.0, seconds))}"


NAME_PLACEHOLDER = "<name>"


def pass_text(data: dict, now: float | None = None, share: bool = False) -> str:
    """Gerätepass als Text (Grundlage der gefilterten Kopie). Ohne Notiz, ohne MAC.

    share=True: eigene Geräte- und Gruppennamen stehen gar nicht erst drin (fester Platzhalter) –
    der Namensabgleich des Filters überspringt kurze Namen („Bob“, „Li“), die Struktur nicht."""
    now = time.time() if now is None else now
    entry = data.get("entry") or {}
    q = data.get("quality") or {}
    week = data.get("week") or {}
    fmt = clientinfo.fmt_offset

    def off(v):
        return fmt(v) if _num(v) is not None else "–"
    name = data.get("name") or ""
    group = (data.get("group") or {}).get("name") or ""
    if share:
        name = NAME_PLACEHOLDER if name else ""
        group = NAME_PLACEHOLDER if group else ""
    q_drift = (f"Gangabweichung: {q['drift_ppm']:+.1f} ppm".replace(".", ",")
               if _num(q.get("drift_ppm")) is not None
               else f"Gangabweichung: höchstens {abs(q['drift_bound_ppm']):.1f} ppm (Versatz und Gang nicht "
                    "trennbar)".replace(".", ",") if _num(q.get("drift_bound_ppm")) is not None
               else "Gangabweichung: –")
    lines = [
        "Gerätepass (ntp-gui)",
        f"Gerät: {data.get('address')}" + (f" – {name}" if name else ""),
        f"Gruppe: {group or 'ohne Gruppe'}",
        f"Software: {data['software']['label']} ({data['software']['origin']})",
        f"Typischer Abstand der Anfragen: {clientinfo._fmt_seconds(entry['interval']) if _num(entry.get('interval')) else '–'}",
        f"Zustand: {entry.get('state_text') or '–'}",
        f"Abweichung 7 Tage: Median {off(week.get('median'))}, P95 |Abw.| {off(week.get('p95')).lstrip('+')} ({week.get('n', 0)} Messungen)",
        f"Uhrgüte: {q.get('score') if q.get('score') is not None else '–'} ({q.get('grade') or '–'})",
        q_drift,
        f"NTS: {'nutzt NTS' if (data.get('nts') or {}).get('uses') else 'nein'}",
        f"Letzte Anfrage: {_fmt_ago(now - entry['last_seen']) if _num(entry.get('last_seen')) else '–'}",
        "Empfehlung:",
    ]
    for rec in data.get("recommendations") or []:
        lines.append(f"- {rec['title']}")
        lines.extend("    " + line for line in str(rec["code"]).split("\n"))
    return "\n".join(lines) + "\n"


class PassLeak(ValueError):
    pass


def shared_pass(data: dict, cfg: dict) -> dict:
    """Kopie zum Weitergeben: durch den Datenschutzfilter (egress, Zweck „diagnostics“) – Adressen als
    Pseudonym, eigene Namen (Geräte, Gruppen) und Hostnamen ersetzt. Notizen stehen nie drin."""
    import diagnostics
    import egress
    names = diagnostics._known_names(cfg)
    known = {"name": sorted(set(clientinfo.export_names()) | set(group_names()))}
    sanitizer = egress.Sanitizer("diagnostics", names, known)
    clean = sanitizer.text(pass_text(data, share=True))
    findings = egress.check_no_leaks(clean)
    if not findings:
        findings = egress.backstop({"geraetepass.txt": clean.encode("utf-8")}, sanitizer.backstop_known())
    if findings:
        raise PassLeak("Der Filter hat die Kopie zurückgehalten (" + ", ".join(sorted({f['kind'] for f in findings})) + ")")
    return {"text": clean, "removed": sanitizer.report()["removed"]}
