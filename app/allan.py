"""Allan-Abweichung (ADEV) der Systemuhr aus dem gespeicherten Verlauf (1.5.4, Seite „Uhrqualität“).

Frage dahinter: Wie stabil ist der Quarz über 10 s … 1 Tag? Die Allan-Abweichung σ(τ) sagt, wie stark
sich die mittlere Frequenz von einem Zeitabschnitt der Länge τ zum nächsten ändert. Grob übersetzt in Zeit:
Läuft die Uhr frei, sammelt sie in der Zeit τ etwa σ(τ) · τ Zeitfehler (1 ppb über 1 h ≈ 3,6 µs).

Welche Messreihe? Der Verlauf speichert je Messpunkt (alle ~10 s) den Offset der Systemuhr und die
Frequenz („freq“, ppm), die chrony für den Quarz gelernt hat. Der Offset ist das, was nach dem Nachregeln
übrig bleibt – er zeigt die Regelung und die Quellen, nicht den Quarz. Die Frequenz ist chronys laufende
Schätzung, wie schnell der Quarz gerade geht. Ihre Schwankung von Abschnitt zu Abschnitt IST die
Frequenzstabilität des Quarzes – mit zwei Einschränkungen, die die Seite nennt:
  * Kurze τ (unter ~15 min): chrony aktualisiert die Frequenz nur bei jeder Messung einer Quelle und
    glättet über mehrere Messungen. Dort zeigt die Kurve vor allem, wie chrony nachführt (und wie
    unruhig die Quellen sind), nicht den Quarz. Diese Punkte sind als „short“ markiert.
  * Auflösung: chronyc meldet die Frequenz auf 0,001 ppm (1 ppb). Werte deutlich darunter sind über
    lange Mittelung möglich, aber nur noch grob.

Rechnung: überlappende Allan-Abweichung aus Frequenzdaten. Die Punkte werden auf ein gleichmäßiges Raster
der Weite τ0 (Messintervall, bei langem Verlauf gröber) gemittelt; Lücken bleiben leer. Für τ = m·τ0:
    σ²(τ) = ½ · Mittel über k von (ȳ[k+m] − ȳ[k])²,  ȳ[k] = Mittel von y[k … k+m−1]
mit allen Startpunkten k (überlappend), bei denen beide Fenster zu mindestens 75 % belegt sind. τ reicht
log-gestuft (5 je Dekade) bis zu einem Viertel der Messdauer. Vertrauensbereich (68 %): Chi-Quadrat mit
der Zahl unabhängiger Paare n ≈ Abschnitte − 1 als Freiheitsgraden (vorsichtig – die Überlappung bringt
mehr), Quantile nach Wilson-Hilferty.

Einschwingen (1.5.4, Prüfbefund): Nach einem Start von chronyd (neue Installation, frisches
chrony-data, Neustart für Kalibrierung oder Fehlerschranke) läuft die Frequenz erst auf ihren Wert ein –
das ist ein einmaliger Übergang, keine Unruhe des Quarzes, würde aber den Wert um 1 h bis zu 200-fach
verfälschen. Darum beginnt an jedem Sprung (|Δfreq| zwischen Nachbarpunkten über STEP_PPM), nach jeder
Lücke über GAP_SECONDS (bei grobem Messintervall: über GAP_FACTOR übliche Abstände der letzten
Punkte) und am Anfang des Verlaufs ein neuer Abschnitt, dessen erste SETTLE_SECONDS weggelassen werden (wie eine Lücke).

Holdover-Tests (Diagnosepaket 2306): Während eines Tests sind alle Quellen abgewählt, chronyd führt die
Frequenz nicht nach – sie bleibt stundenlang konstant und täuschte für τ von Minuten bis Stunden Stabilität
vor. Diese Zeiträume (exclude, aus den Ergebnissen des Holdover-Tests) fallen weg wie eine Lücke; danach
beginnt ein neuer Abschnitt mit Einschwingen.

Aufwand begrenzt: höchstens MAX_SPAN (30 Tage) Verlauf, auch bei größerem HISTORY_DAYS (sonst bei 365 Tagen
gut 1 GB Speicher auf einem Pi), höchstens MAX_BINS Rasterpunkte (τ0 wird bei langem Verlauf gröber), höchstens
MAX_PAIRS Paare je τ (sonst gleichmäßig ausgedünnt, weiter überlappend). Ergebnis 10 min im Speicher;
gleichzeitige Abrufe rechnen nicht doppelt. Reine Mathematik, kein numpy.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any, Callable

CACHE_SECONDS = 600.0
MAX_BINS = 50_000          # 30 Tage bei 10 s wären 260 000 → τ0 dann ~52 s
MAX_PAIRS = 20_000         # Paare je τ, darüber gleichmäßig ausgedünnt
PER_DECADE = 5
MIN_FILL = 0.75            # Fenster gilt, wenn so viel davon belegt ist
MIN_SPAN = 2 * 3600.0      # darunter keine Kurve (τ bis 30 min)
MIN_POINTS = 64
SHORT_TAU = 900.0          # darunter: chronys Nachführung statt Quarz
PPB = 1e-9
MAX_SPAN = 30 * 86400.0    # nur die letzten 30 Tage laden und rechnen (τ bis ~7 Tage)
STEP_PPM = 0.5             # Frequenzsprung zwischen Nachbarpunkten: chronyd neu gestartet
GAP_SECONDS = 600.0        # längere Lücke im Verlauf: Container/chronyd vermutlich neu gestartet
GAP_FACTOR = 3.0           # bei grobem Messintervall: Lücke erst ab so vielen üblichen Abständen
GAP_WINDOW = 7             # üblicher Abstand = Median der letzten so vielen Abstände (lokal)
SETTLE_SECONDS = 2700.0    # so lange nach Start/Sprung/Lücke weglassen (Einschwingen)

# Einordnung nach dem Wert um τ ≈ 1 h (Bruchteil, nicht ppm). Grenzen bewusst grob.
LEVELS = [
    (1e-9, "very_quiet", "sehr ruhig – so stabil wie ein temperaturgeführter Quarz (TCXO) oder ein Gerät in sehr "
                         "gleichmäßiger Umgebung"),
    (1e-8, "quiet", "typisch für einen Pi-Quarz ohne Temperaturkontrolle in ruhiger Umgebung (drinnen, "
                    "gleichmäßige Last)"),
    (1e-7, "typical", "typisch für einen Quarz ohne Temperaturkontrolle mit Temperatur- oder Lastwechseln"),
    (math.inf, "restless", "unruhig – große Temperatursprünge, wechselnde Last oder eine unruhige Referenz"),
]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def grid(times: list[float], values: list[float], max_bins: int = MAX_BINS) -> tuple[float, list[float | None]]:
    """Mittelt (t, y) auf ein gleichmäßiges Raster. Liefert (τ0, Werte mit None für Lücken)."""
    deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not deltas:
        return 0.0, []
    tau0 = max(1.0, float(round(_median(deltas))))
    span = times[-1] - times[0]
    if span / tau0 + 1 > max_bins:
        tau0 = float(math.ceil(span / (max_bins - 1)))
    count = int(span // tau0) + 1
    sums = [0.0] * count
    hits = [0] * count
    start = times[0]
    for t, v in zip(times, values):
        i = min(count - 1, int((t - start) // tau0))
        sums[i] += v
        hits[i] += 1
    return tau0, [s / h if h else None for s, h in zip(sums, hits)]


def _taus(m_max: int, per_decade: int = PER_DECADE) -> list[int]:
    out: list[int] = []
    i = 0
    while True:
        m = int(round(10 ** (i / per_decade)))
        if m > m_max:
            return out
        if not out or m != out[-1]:
            out.append(m)
        i += 1


def _chi2(p_z: float, k: float) -> float:
    """Chi-Quadrat-Quantil (Wilson-Hilferty) zum Standardnormal-Quantil p_z, k Freiheitsgrade."""
    a = 2.0 / (9.0 * k)
    return k * max(1e-6, 1.0 - a + p_z * math.sqrt(a)) ** 3


def adev(y: list[float | None], tau0: float, max_pairs: int = MAX_PAIRS,
         min_fill: float = MIN_FILL) -> list[dict]:
    """Überlappende Allan-Abweichung aus Frequenzwerten (Bruchteil) auf gleichmäßigem Raster."""
    n = len(y)
    psum = [0.0] * (n + 1)
    pcnt = [0] * (n + 1)
    for i, v in enumerate(y):
        psum[i + 1] = psum[i] + (v if v is not None else 0.0)
        pcnt[i + 1] = pcnt[i] + (v is not None)
    out = []
    for m in _taus(n // 4):
        need = max(1, math.ceil(m * min_fill))
        last = n - 2 * m           # k = 0 … last
        if last < 0:
            break
        stride = max(1, math.ceil((last + 1) / max_pairs))
        acc = 0.0
        pairs = 0
        for k in range(0, last + 1, stride):
            c1 = pcnt[k + m] - pcnt[k]
            c2 = pcnt[k + 2 * m] - pcnt[k + m]
            if c1 < need or c2 < need:
                continue
            d = (psum[k + 2 * m] - psum[k + m]) / c2 - (psum[k + m] - psum[k]) / c1
            acc += d * d
            pairs += 1
        if not pairs:
            continue
        sigma = math.sqrt(acc / (2 * pairs))
        # Unabhängige Paare: belegte Länge / m − 1 (bei Überlappung vorsichtig gezählt).
        # Ohne Lücken: (N − 2m + 1)/m + 1 ≈ N/m − 1 = Zahl der nicht überlappenden Paare.
        indep = min(pairs, max(1, int(pairs * stride / m) + 1))
        lo = sigma * math.sqrt(indep / _chi2(1.0, indep)) if sigma else 0.0
        hi = sigma * math.sqrt(indep / _chi2(-1.0, indep)) if sigma else 0.0
        out.append({"tau": m * tau0, "m": m, "adev": sigma, "lo": lo, "hi": hi, "n": indep, "pairs": pairs})
    return out


def _nearest(points: list[dict], tau: float, factor: float = 2.0) -> dict | None:
    best = None
    for p in points:
        ratio = max(p["tau"], tau) / min(p["tau"], tau)
        if ratio <= factor and (best is None or ratio < best[0]):
            best = (ratio, p)
    return best[1] if best else None


def interpret(points: list[dict]) -> dict:
    """Kurzbewertung: Bestwert, Werte um 1 h und 1 Tag, Einordnung."""
    long_ = [p for p in points if not p.get("short")] or points
    best = min(long_, key=lambda p: p["adev"]) if long_ else None
    hour = _nearest(points, 3600.0)
    day = _nearest(points, 86400.0, factor=1.6)
    ref = hour or (long_[-1] if long_ else None)
    level = text = None
    if ref:
        for limit, key, sentence in LEVELS:
            if ref["adev"] < limit:
                level, text = key, sentence
                break
    rising = bool(best and long_ and best is not long_[-1] and long_[-1]["adev"] > best["adev"] * 1.5)
    return {"best": _brief(best), "hour": _brief(hour), "day": _brief(day), "ref": _brief(ref),
            "level": level, "text": text, "rising_after": best["tau"] if rising else None}


def _brief(p: dict | None) -> dict | None:
    return None if p is None else {"tau": p["tau"], "adev": p["adev"]}


def settle(clean: list[tuple[float, float]],
           breaks: set[int] | None = None) -> tuple[list[tuple[float, float]], int, int]:
    """Lässt das Einschwingen nach Start, Sprung oder Lücke weg. (t, ppm) sortiert →
    (behaltene Punkte, Zahl der Abschnitte, weggelassene Punkte).

    Lücke heißt: länger als GAP_SECONDS und als GAP_FACTOR übliche Abstände. Sonst wäre bei einem
    Messintervall um GAP_SECONDS (history_interval bis 600 s) jeder normale Abstand eine Lücke. Der übliche
    Abstand ist der Median der letzten GAP_WINDOW Abstände (lokal, nicht über den ganzen Verlauf): Nach
    einer Umstellung von 10 s auf 600 s machen die alten 10-s-Punkte noch wochenlang die Mehrheit aus, ein
    globaler Median bliebe bei 10 s und jeder 601-s-Abstand gälte als Lücke. Lokal gilt nur der Übergang
    selbst als Lücke (ein Einschwingen). Ohne Vorgeschichte (erster Abstand) zählt der Median aller Abstände.
    breaks: Indizes, an denen in jedem Fall ein neuer Abschnitt beginnt (nach einem ausgeschlossenen Zeitraum)."""
    kept: list[tuple[float, float]] = []
    segments = dropped = 0
    deltas = [b[0] - a[0] for a, b in zip(clean, clean[1:]) if b[0] > a[0]]
    overall = _median(deltas) if deltas else 0.0
    recent: deque[float] = deque(maxlen=GAP_WINDOW)
    start = prev_t = prev_v = None
    for index, (t, v) in enumerate(clean):
        if prev_t is None or (breaks and index in breaks):
            new = True
            if prev_t is not None and t - prev_t > 0:
                recent.append(t - prev_t)
        else:
            step = t - prev_t
            typical = _median(list(recent)) if recent else overall
            new = step > max(GAP_SECONDS, GAP_FACTOR * typical) or abs(v - prev_v) > STEP_PPM
            if step > 0:
                recent.append(step)
        if new:
            start = t
            segments += 1
        if t - start >= SETTLE_SECONDS:
            kept.append((t, v))
        else:
            dropped += 1
        prev_t, prev_v = t, v
    return kept, segments, dropped


def _exclude(clean: list[tuple[float, float]], exclude: Any) -> tuple[list[tuple[float, float]], set[int], int]:
    """Punkte in den Zeiträumen [start, end) weglassen. → (Rest, Indizes mit neuem Abschnitt, weggelassen)."""
    spans = []
    for item in exclude or []:
        try:
            start, end = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(start) and math.isfinite(end) and end >= start:
            spans.append((start, end))
    if not spans:
        return clean, set(), 0
    spans.sort()
    kept: list[tuple[float, float]] = []
    breaks: set[int] = set()
    removed = 0
    pending = False
    for t, v in clean:
        if any(a <= t < b for a, b in spans):
            removed += 1
            pending = True
            continue
        if pending or (kept and any(kept[-1][0] < a and b <= t for a, b in spans)):
            breaks.add(len(kept))
        pending = False
        kept.append((t, v))
    return kept, breaks, removed


def compute(series: list[tuple[float, float]], now: float | None = None, exclude: Any = None) -> dict:
    """Ergebnis für /api/clockquality/allan aus (t, freq in ppm).

    exclude: Zeiträume (start, end) ohne nachgeführte Frequenz (Holdover-Tests) – fallen weg wie Lücken."""
    out: dict[str, Any] = {"available": False, "source": "freq", "unit": "fraction",
                           "samples": len(series), "need_span": MIN_SPAN, "short_tau": SHORT_TAU,
                           "resolution": PPB, "points": [], "summary": None,
                           "computed": now if now is not None else time.time()}
    clean = [(float(t), float(v)) for t, v in series
             if isinstance(v, (int, float)) and math.isfinite(v)]
    clean.sort()
    if len(clean) < 2:
        out["reason"] = "no_history"
        return out
    if clean[-1][0] - clean[0][0] > MAX_SPAN:
        cutoff = clean[-1][0] - MAX_SPAN
        clean = [p for p in clean if p[0] >= cutoff]
    clean, breaks, excluded = _exclude(clean, exclude)
    out["excluded_points"] = excluded
    clean, segments, dropped = settle(clean, breaks)
    out.update(segments=segments, settle_dropped=dropped)
    if len(clean) < 2:
        out["reason"] = "few"
        return out
    times = [t for t, _ in clean]
    values = [v * 1e-6 for _, v in clean]  # ppm → Bruchteil
    span = times[-1] - times[0]
    out.update({"from": times[0], "to": times[-1], "span": span})
    if span < MIN_SPAN or len(clean) < MIN_POINTS:
        out["reason"] = "few"
        return out
    tau0, y = grid(times, values)
    filled = sum(v is not None for v in y)
    out.update(tau0=tau0, bins=len(y), coverage=filled / len(y) if y else 0.0)
    points = adev(y, tau0)
    for p in points:
        p["short"] = p["tau"] < SHORT_TAU
    out["points"] = points
    if not points:
        out["reason"] = "few"
        return out
    out["available"] = True
    out["reason"] = None
    out["summary"] = interpret(points)
    return out


def compact(result: dict | None) -> dict | None:
    """Nur Zahlen für das Diagnosepaket: τ (s), ADEV, n."""
    if not result or not result.get("available"):
        return None if not result else {"available": False, "reason": result.get("reason"),
                                        "samples": result.get("samples")}
    summary = result.get("summary") or {}
    return {
        "available": True, "source": result.get("source"), "tau0": result.get("tau0"),
        "span": result.get("span"), "coverage": round(result.get("coverage") or 0.0, 3),
        "points": [[round(p["tau"], 1), float(f"{p['adev']:.3e}"), p["n"]] for p in result["points"]],
        "level": summary.get("level"),
        "best": summary.get("best"), "hour": summary.get("hour"), "day": summary.get("day"),
    }


class Cache:
    """Ergebnis CACHE_SECONDS lang behalten; ein Abruf rechnet, die übrigen warten darauf."""

    def __init__(self, loader: Callable[[], list[tuple[float, float]]], seconds: float = CACHE_SECONDS,
                 exclude: Callable[[], Any] | None = None) -> None:
        self.loader = loader
        self.exclude = exclude
        self.seconds = seconds
        self._lock = threading.Lock()
        self._result: dict | None = None
        self._at = 0.0

    def get(self, fresh: bool = False, wait: bool = True) -> dict:
        """wait=False (Diagnosepaket): rechnet gerade ein anderer Abruf, nicht warten, sondern das
        letzte Ergebnis liefern (oder reason „busy“)."""
        if not self._lock.acquire(blocking=wait):
            last = self._result
            return dict(last, cached=True) if last is not None else {
                "available": False, "reason": "busy", "points": [], "summary": None}
        try:
            now = time.monotonic()
            if fresh or self._result is None or now - self._at >= self.seconds:
                started = time.monotonic()
                try:
                    result = compute(self.loader(), exclude=self.exclude() if self.exclude else None)
                except Exception as exc:  # Verlauf kaputt: Seite zeigt den Grund, Server läuft weiter
                    # Einzelheiten (evtl. Dateipfade) nur ins Container-Log, nicht an jeden Leser.
                    print(f"[web] Allan-Abweichung nicht berechnet: {exc!r}", flush=True)
                    result = {"available": False, "reason": "error", "points": [],
                              "summary": None, "computed": time.time()}
                result["seconds"] = round(time.monotonic() - started, 3)
                self._result, self._at = result, time.monotonic()
                return dict(result, cached=False)
            return dict(self._result, cached=True)
        finally:
            self._lock.release()

    def peek(self) -> dict | None:
        """Letztes Ergebnis ohne neu zu rechnen (Diagnosepaket)."""
        with self._lock:
            return self._result
