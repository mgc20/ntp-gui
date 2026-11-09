"""Zahlen in Nutzertexten des Servers – deutsch und genau wie im Frontend (util.js fmtNumber/fmtSeconds).

Regeln (dieselben wie im Dashboard):
  * Komma als Dezimalzeichen: „1,4 ms“, nie „1.4 ms“.
  * Minus ist das typografische „−“ (U+2212), nie der Bindestrich: „−3,2 ms“.
  * Keine Nullen am Ende: „1,5 s“ statt „1,50 s“, „5 ms“ statt „5,0 ms“.
  * „−0“ nach dem Runden wird zu „0“; mit signed=True steht „+“ vor positiven Werten, nie vor 0.
  * Tausenderpunkt nur, wenn gewünscht (group=True, Standard wie im Frontend); für Sekunden und
    Messwerte ohne („1000 s“ – „1.000 s“ läse sich als eine Sekunde).

Hinweise (insights), Ereignistitel, Benachrichtigungen und Prüfbefunde nutzen nur diese Helfer,
damit kein Modul mehr eigene „.replace('.', ',')“-Varianten pflegt.
"""

from __future__ import annotations

import math
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

MINUS = "−"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _group(digits: str) -> str:
    out = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return ".".join(out)


def number(value: Any, digits: int = 0, *, signed: bool = False, group: bool = True,
           floor: bool = False, empty: str = "–") -> str:
    """Zahl mit höchstens digits Nachkommastellen (kaufmännisch gerundet wie Intl.NumberFormat,
    floor=True rundet stattdessen ab – für Schwellen, die durch Runden nicht überschritten werden dürfen)."""
    val = _finite(value)
    if val is None:
        return empty
    try:
        exact = Decimal(repr(abs(val)))
    except InvalidOperation:
        return empty
    quantum = Decimal(1).scaleb(-max(0, int(digits)))
    if floor:
        rounded = (Decimal(repr(val))).quantize(quantum, rounding=ROUND_FLOOR)
        negative = rounded < 0
        rounded = abs(rounded)
    else:
        rounded = exact.quantize(quantum, rounding=ROUND_HALF_UP)
        negative = val < 0
    text = format(rounded, "f")
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0")
    if group:
        whole = _group(whole)
    body = f"{whole},{frac}" if frac else whole
    if rounded == 0:
        return body  # kein „−0“, kein „+0“
    if negative:
        return MINUS + body
    return f"+{body}" if signed else body


def seconds(value: Any, digits: int = 3, *, signed: bool = False, empty: str = "–") -> str:
    """Messwert in Sekunden mit passender Einheit (ns/µs/ms/s) – wie fmtSeconds im Frontend."""
    val = _finite(value)
    if val is None:
        return empty
    a = abs(val)
    if a == 0:
        return "0 s"
    units = [
        ("ns", 1e9, 1 if a < 1e-8 else 0),
        ("µs", 1e6, 2 if a < 1e-5 else 1),
        ("ms", 1e3, min(digits, 1 if a >= 0.1 else 2 if a >= 0.01 else 3)),
        ("s", 1.0, digits),
    ]
    index = 0 if a < 1e-6 else 1 if a < 1e-3 else 2 if a < 1 else 3
    # Rundet der Wert auf 1000 der Einheit (999,96 µs → „1000 µs“), gilt die nächstgrößere: „1 ms“.
    while index < 3:
        _unit, factor, places = units[index]
        if abs(round(a * factor, places)) < 1000:
            break
        index += 1
    unit, factor, places = units[index]
    return f"{number(val * factor, places, signed=signed, group=False)} {unit}"


def ms(value: Any, digits: int = 1, *, signed: bool = False, absolute: bool = False, empty: str = "–") -> str:
    """Sekunden fest in Millisekunden: „12,3 ms“ (höchstens digits Nachkommastellen)."""
    val = _finite(value)
    if val is None:
        return empty
    if absolute:
        val = abs(val)
    return f"{number(val * 1000.0, digits, signed=signed, group=False)} ms"


def adaptive(value: Any, *, signed: bool = False, empty: str = "–") -> str:
    """Eine Nachkommastelle unter 10, darüber ganze Zahlen: „4,2“, „12“ (wie die Texte zu GPS/Holdover)."""
    val = _finite(value)
    if val is None:
        return empty
    return number(val, 0 if abs(val) >= 10 else 1, signed=signed, group=False)
