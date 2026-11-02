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

Die Haltertabelle (wer hält welche Quelle, was hat ntp-gui selbst abgewählt) steht in SQLite
(Tabelle select_holds) und wird bei jedem Halten, Freigeben und Übergeben sofort geschrieben.
So überlebt auch eine Übergabe (Holdover-Test endet, GPS-Sperre übernimmt das GPS) einen
Neustart von ntp-gui – sonst bliebe eine Quelle abgewählt, obwohl beide Funktionen „frei“
melden.

Für die GPS-Sperre schreibt dieses Modul zusätzlich DATA_DIR/noselect.list (eine RefID je
Zeile). Der Supervisor (docker/entrypoint.sh) wählt diese Quellen direkt nach jedem Start von
chronyd wieder ab – bevor die erste GPS-Messung da ist. Ohne das wäre das gesperrte GPS nach
dem Speichern von Einstellungen bis zum nächsten Prüftakt (~10 s) wieder auswählbar, und
chronyd könnte in dieser Zeit sogar die Uhr darauf stellen (makestep beim Start).
"""

from __future__ import annotations

import os
import re
import tempfile
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
_READY: dict[str, Any] = {"for": None, "orphans": set()}

# Halter, deren Quellen der Supervisor nach einem Neustart von chronyd sofort wieder abwählt
# (noselect.list). Der Holdover-Test gehört bewusst nicht dazu: Er bricht bei einem Neustart ab.
RESTART_OWNERS = ("gps-lock",)
RUNTIME_FILE = "noselect.list"

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS select_holds (owner TEXT NOT NULL, name TEXT NOT NULL, "
    "added INTEGER NOT NULL, PRIMARY KEY (owner, name));",
]


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


# --- Haltertabelle in SQLite ----------------------------------------------------------------

def _runtime_path() -> str:
    import store
    return os.path.join(store.data_dir(), RUNTIME_FILE)


def _read_runtime() -> set[str]:
    try:
        with open(_runtime_path(), encoding="utf-8", errors="replace") as handle:
            return {line.strip() for line in handle if valid_name(line.strip())}
    except OSError:
        return set()


def _write_runtime() -> None:
    names = sorted({n for owner in RESTART_OWNERS for n in _HOLDS.get(owner, {}).get("names", set())
                    if valid_name(n)})
    path = _runtime_path()
    try:
        if not names:
            if os.path.exists(path):
                os.unlink(path)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".noselect-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("".join(f"{n}\n" for n in names))
        os.replace(tmp, path)
    except OSError:
        pass


def _load() -> None:
    """Haltertabelle einmal je Datenbank aus SQLite lesen (Start von ntp-gui, Tests)."""
    import store
    key = store.path()
    if _READY["for"] == key:
        return
    _READY["for"] = key
    try:
        store.migrate("selectctl", _SCHEMA)
        rows = store.query("SELECT owner, name, added FROM select_holds")
    except Exception:
        return
    _HOLDS.clear()
    for owner, name, was_added in rows:
        if not valid_name(name):
            continue
        entry = _entry(str(owner))
        entry["names"].add(name)
        if was_added:
            entry["added"].add(name)
    # Was der Supervisor laut Datei abwählt, aber niemand mehr hält (Absturz zwischen zwei
    # Schreibvorgängen): Kandidaten für reconcile().
    held_now = {n for e in _HOLDS.values() for n in e["names"]}
    _READY["orphans"] = _read_runtime() - held_now
    _write_runtime()


def _persist() -> None:
    import store
    try:
        _write_runtime()
        with store.transaction() as conn:
            conn.execute("DELETE FROM select_holds")
            conn.executemany("INSERT INTO select_holds(owner, name, added) VALUES(?, ?, ?)",
                             [(owner, name, 1 if name in entry["added"] else 0)
                              for owner, entry in _HOLDS.items() for name in sorted(entry["names"])])
    except Exception:
        pass   # ohne Datenbank (Tests ohne Datenverzeichnis) gilt der Stand im Speicher


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
        _load()
        return {owner for owner, entry in _HOLDS.items() if name in entry["names"]}


def held(owner: str) -> set[str]:
    with _LOCK:
        _load()
        return set(_HOLDS.get(owner, {}).get("names", set()))


def added(owner: str) -> set[str]:
    with _LOCK:
        _load()
        return set(_HOLDS.get(owner, {}).get("added", set()))


def register(owner: str, names: list[str] | set[str], added_names: list[str] | set[str] | None = None) -> None:
    """Halter eintragen, ohne chrony anzufassen (beim Laden des gespeicherten Zustands).

    Steht der Halter schon in der Haltertabelle (SQLite), gilt die: Sie kennt auch Übergaben,
    die der gespeicherte Zustand des Moduls nicht kennt."""
    names = {n for n in names if valid_name(n)}
    with _LOCK:
        _load()
        if owner in _HOLDS:
            return
        _HOLDS[owner] = {"names": names,
                         "added": names if added_names is None else {n for n in added_names if n in names}}
        _persist()


def forget(owner: str) -> None:
    with _LOCK:
        _load()
        if _HOLDS.pop(owner, None) is not None:
            _persist()


def hold(owner: str, names: list[str], select: dict[str, dict] | None = None) -> list[str]:
    """Quellen für `owner` abwählen. Gibt die Namen zurück, die dafür neu „+noselect“ bekamen.

    Schlägt ein Aufruf fehl, werden die in diesem Aufruf schon gesetzten zurückgenommen und
    SelectError geworfen – halbe Zustände gibt es nicht."""
    select = by_name(port().selectdata()) if select is None else select
    changed: list[str] = []
    with _LOCK:
        _load()
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
        _persist()
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
            # Was jetzt noch „noselect“ trägt und laut chrony.conf so konfiguriert ist (Einstellung
            # „nur beobachten“, während der Sperre gesetzt), gibt ntp-gui später nicht frei. Alles
            # andere, was ntp-gui selbst abgewählt hat, bleibt in „added“ – auch wenn nur ein Teil
            # der Quellen fehlt.
            observe_only = conf_noselect_refids()
            entry = _entry(owner)
            entry["added"] -= {n for n in entry["added"] if n not in missing and n in select
                               and effective_noselect(select[n]) and n in observe_only}
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
        _load()
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
        _persist()      # auch Übergaben an einen anderen Halter – sie müssen einen Neustart überleben
    return released, failed


def reconcile(select: dict[str, dict] | None) -> list[str]:
    """Sicherheitsnetz nach dem Start von ntp-gui: Quellen, die der Supervisor laut
    noselect.list nach einem chronyd-Start abgewählt hat, die aber kein Halter mehr hält
    (Absturz zwischen zwei Schreibvorgängen), wieder auswählbar machen. Gibt die Namen zurück.

    Nur diese Kandidaten – ein „noselect“, das jemand anders gesetzt hat (chronyc von Hand,
    chrony.conf), fasst ntp-gui nie an."""
    if not select:
        return []
    out = []
    with _LOCK:
        _load()
        candidates = sorted(_READY["orphans"])
        if not candidates:
            return []
        held_now = {n for e in _HOLDS.values() for n in e["names"]}
        observe_only = conf_noselect_refids()
        for name in candidates:
            if name in held_now or name in observe_only or not effective_noselect(select.get(name)):
                _READY["orphans"].discard(name)
                continue
            try:
                _call(name, "-")
                out.append(name)
                _READY["orphans"].discard(name)
            except SelectError:
                pass
    return out


def reset_for_tests() -> None:
    """Speicher leeren – wie ein Neustart von ntp-gui (die Haltertabelle in SQLite bleibt)."""
    with _LOCK:
        _HOLDS.clear()
        _LOG.clear()
        _READY.update({"for": None, "orphans": set()})


def calls() -> list[dict]:
    with _LOCK:
        return list(_LOG)
