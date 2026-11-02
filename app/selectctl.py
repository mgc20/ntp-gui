"""Quellen zeitweise abwählen: `chronyc selectopts <quelle> +noselect` / `-noselect` (1.5).

Zwei Funktionen greifen so in die Zeit ein – beide umkehrbar, mit Zeitlimit, Ereignis und
Zustand in SQLite (das steht in den jeweiligen Modulen):

  * die GPS-Sperre bei einer GNSS-Störung (gnssguard.py)
  * der echte Holdover-Test (holdover.py)

Dieses Modul ist die gemeinsame, schmale Stelle dazwischen. Es merkt sich, **wer** eine
Quelle gerade hält („gps-lock“, „holdover“). Eine Quelle wird erst wieder auswählbar,
wenn sie niemand mehr hält – so hebt das Ende eines Holdover-Tests keine GPS-Sperre auf und
umgekehrt. Freigegeben wird nur, was ntp-gui selbst abgewählt hat: Eine Quelle, die schon
vorher „noselect“ trug (chrony.conf, Einstellung „nur beobachten“), bleibt so.

Warum chronyc und nicht chrony.conf? `selectopts` (chrony ≥ 4.4) wirkt sofort, ohne Neustart
und ohne die Messhistorie zu verlieren. Der Preis: Ein Neustart von chronyd (z. B. nach dem
Speichern von Einstellungen) vergisst den Schalter. Die Module prüfen deshalb laufend, ob er
noch wirkt (`effective_noselect`), und setzen ihn neu bzw. brechen den Test ab.

Quellnamen kommen ausschließlich aus `chronyc -c selectdata` (Refclock-RefID oder IP-Adresse)
und werden vor dem Aufruf gegen ein enges Muster geprüft – nichts aus einer Anfrage landet
ungeprüft auf der Kommandozeile.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Callable

NAME_RE = re.compile(r"^[A-Za-z0-9_.:%-]{1,64}$")

_LOCK = threading.RLock()
# Halter → {"names": Quellen, die abgewählt sein sollen, "added": davon die, die ntp-gui selbst
# abgewählt hat}. Nur „added“ wird beim Freigeben zurückgenommen: Was schon vorher „noselect“
# war (chrony.conf, Einstellung „nur beobachten“), bleibt so. Achtung: chronyc selectdata zeigt
# nach selectopts auch in der Spalte „konfiguriert“ die neue Option – woher ein „noselect“
# stammt, lässt sich dort nicht ablesen, darum merkt sich dieses Modul das selbst.
_HOLDS: dict[str, dict[str, set[str]]] = {}
_LOG: list[dict] = []                # letzte Aufrufe (Fehlersuche, Tests)


class SelectError(RuntimeError):
    """selectopts ging nicht (chronyd nicht erreichbar, Quelle unbekannt, chrony zu alt)."""


class ChronyPort:
    """Die drei Aufrufe, die dieses Modul braucht – in Tests durch eine Attrappe ersetzt."""

    def selectdata(self) -> list[dict]:
        import chrony
        return chrony.selectdata()

    def sources(self) -> list[dict]:
        import chrony
        return chrony.sources()

    def selectopts(self, name: str, sign: str) -> None:
        import chrony
        try:
            chrony.run("selectopts", name, f"{sign}noselect", timeout=5.0)
        except chrony.ChronyError as exc:
            raise SelectError(str(exc) or "chronyc selectopts fehlgeschlagen") from exc


_PORT: dict[str, Any] = {"port": ChronyPort()}


def port() -> ChronyPort:
    return _PORT["port"]


def set_port(new: Any) -> Callable[[], None]:
    """Attrappe einsetzen; gibt eine Funktion zurück, die den alten Zustand herstellt."""
    old = _PORT["port"]
    _PORT["port"] = new

    def restore() -> None:
        _PORT["port"] = old
    return restore


def by_name(rows: list[dict] | None) -> dict[str, dict]:
    return {str(r.get("name")): r for r in rows or [] if isinstance(r, dict) and r.get("name")}


def effective_noselect(row: dict | None) -> bool:
    return bool(row) and "noselect" in (row.get("effective_options") or [])


def conf_noselect_refids(path: str | None = None) -> set[str]:
    """Refclocks, die in der erzeugten chrony.conf „noselect“ tragen (Einstellung „nur beobachten“).

    chronyc kann das nach einem selectopts nicht mehr unterscheiden; die Datei schon. Eine
    Freigabe darf diese Quellen nie auswählbar machen – auch nicht, wenn die Einstellung erst
    während einer Sperre geändert wurde."""
    path = path or os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")
    out: set[str] = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                words = line.split("#", 1)[0].split()
                if words[:1] == ["refclock"] and "noselect" in words and "refid" in words[:-1]:
                    out.add(words[words.index("refid") + 1])
    except OSError:
        pass
    return out


def valid_name(name: Any) -> bool:
    return isinstance(name, str) and bool(NAME_RE.match(name))


def _call(name: str, sign: str) -> None:
    if not valid_name(name):
        raise SelectError(f"ungültiger Quellname: {name!r}")
    port().selectopts(name, sign)
    with _LOCK:
        _LOG.append({"name": name, "sign": sign})
        del _LOG[:-50]


def _entry(owner: str) -> dict[str, set[str]]:
    return _HOLDS.setdefault(owner, {"names": set(), "added": set()})


def holders(name: str) -> set[str]:
    with _LOCK:
        return {owner for owner, entry in _HOLDS.items() if name in entry["names"]}


def held(owner: str) -> set[str]:
    with _LOCK:
        return set(_HOLDS.get(owner, {}).get("names", set()))


def added(owner: str) -> set[str]:
    with _LOCK:
        return set(_HOLDS.get(owner, {}).get("added", set()))


def register(owner: str, names: list[str] | set[str], added_names: list[str] | set[str] | None = None) -> None:
    """Halter eintragen, ohne chrony anzufassen (beim Laden des gespeicherten Zustands)."""
    names = {n for n in names if valid_name(n)}
    with _LOCK:
        _HOLDS[owner] = {"names": names,
                         "added": names if added_names is None else {n for n in added_names if n in names}}


def forget(owner: str) -> None:
    with _LOCK:
        _HOLDS.pop(owner, None)


def hold(owner: str, names: list[str], select: dict[str, dict] | None = None) -> list[str]:
    """Quellen für `owner` abwählen. Gibt die Namen zurück, die dafür neu „+noselect“ bekamen.

    Schlägt ein Aufruf fehl, werden die in diesem Aufruf schon gesetzten zurückgenommen und
    SelectError geworfen – halbe Zustände gibt es nicht."""
    select = by_name(port().selectdata()) if select is None else select
    changed: list[str] = []
    with _LOCK:
        try:
            for name in names:
                if not effective_noselect(select.get(name)):
                    _call(name, "+")
                    changed.append(name)
        except SelectError:
            for name in changed:
                try:
                    _call(name, "-")
                except SelectError:
                    pass
            raise
        entry = _entry(owner)
        entry["names"].update(n for n in names if valid_name(n))
        entry["added"].update(changed)
    return changed


def reapply(owner: str, select: dict[str, dict] | None = None) -> list[str]:
    """Nach einem Neustart von chronyd: alle Quellen des Halters erneut abwählen.

    Was nach dem Neustart trotzdem „noselect“ ist, kommt aus chrony.conf – das nimmt ntp-gui
    beim Freigeben dann nicht mehr zurück."""
    names = sorted(held(owner))
    if not names:
        return []
    select = by_name(port().selectdata()) if select is None else select
    missing = [n for n in names if n in select and not effective_noselect(select[n])]
    if missing:
        with _LOCK:
            entry = _entry(owner)
            entry["added"] &= set(missing)
        hold(owner, missing, select)
    return missing


def lost(owner: str, names: list[str], select: dict[str, dict]) -> list[str]:
    """Welche der (von `owner` gesetzten) Quellen sind wieder auswählbar? → chronyd neu gestartet."""
    return [n for n in names if n in select and not effective_noselect(select[n])]


def release(owner: str, select: dict[str, dict] | None = None) -> tuple[list[str], list[str]]:
    """Halter austragen; was ntp-gui für ihn abgewählt hat, wieder auswählbar machen.

    Gibt (freigegeben, Fehler) zurück. Hält ein anderer Halter eine Quelle noch, bleibt sie
    abgewählt und geht in dessen Verantwortung über (er gibt sie später frei)."""
    select = by_name(port().selectdata()) if select is None else select
    with _LOCK:
        entry = _HOLDS.get(owner) or {"names": set(), "added": set()}
        mine = sorted(entry["added"])
        if mine and not select:
            # chronyd antwortet nicht: nichts freigeben, Halter behalten – der nächste Versuch
            # (oder der Neustart von chronyd, der den Schalter ohnehin vergisst) erledigt es.
            return [], mine
        _HOLDS.pop(owner, None)
        observe_only = conf_noselect_refids()
        released, failed = [], []
        for name in mine:
            others = [o for o, e in _HOLDS.items() if name in e["names"]]
            if others:
                _HOLDS[others[0]]["added"].add(name)
                continue
            if not effective_noselect(select.get(name)) or name in observe_only:
                continue
            try:
                _call(name, "-")
                released.append(name)
            except SelectError:
                failed.append(name)
        if failed:
            _HOLDS[owner] = {"names": set(failed), "added": set(failed)}   # für den nächsten Versuch
    return released, failed


def reset_for_tests() -> None:
    with _LOCK:
        _HOLDS.clear()
        _LOG.clear()


def calls() -> list[dict]:
    with _LOCK:
        return list(_LOG)
