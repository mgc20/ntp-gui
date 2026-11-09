"""Willkommens-Assistent „In 3 Minuten fertig“ (1.6, Thema T3): Zustand der Einrichtung und Checkliste.

Der Assistent selbst ist eine Seite im Dashboard (#/system/einrichtung). Hier steht nur, was der Server
dafür wissen muss – alles nur gelesen, außer DATA_DIR/einrichtung.json:

    {"version": 1, "install": "fresh" | "update", "first_seen": 1793527200,
     "done": null | Zeit,            # setup_done: „Fertig“ oder „Nicht mehr zeigen“
     "hint_closed": null | Zeit,     # Hinweis „Einrichtung prüfen“ (Update von 1.5.x) geschlossen
     "checklist_closed": null | Zeit,  # Checkliste auf der Übersicht geschlossen (✕ oder „Nicht mehr zeigen“)
     "checklist_done": null | Zeit}  # Checkliste war einmal ganz grün – sie kommt danach nicht wieder,
                                     # auch wenn chrony kurz die Synchronisation verliert

Erster Start oder Update? Entschieden wird einmal, beim ersten Lauf ohne einrichtung.json:
Liegt im Datenverzeichnis schon etwas von ntp-gui (Einstellungen, Datenbank, Verlauf, Kalibrierung,
Instanz-Kennung, Sicherungen), ist es ein Update (z. B. von 1.5.x) – der Assistent öffnet sich dann
nicht von selbst, die Übersicht zeigt einmalig einen dezenten Hinweis „Einrichtung prüfen“.
Sonst ist es eine frische Installation, und der Assistent erscheint von selbst.

Weil server.py beim Import schon die Datenbank anlegt (store), merkt sich dieses Modul beim eigenen
Import, was vorher da war (_BOOT). server.py importiert es vor seinem eigenen Code; main() schreibt die
Entscheidung dann sofort fest (remember()).

Schreiben nur über POST /api/setup (Recht „admin“, dieselbe CSRF-/Origin-Prüfung wie alle POST-Routen,
gesperrt mit WEB_READONLY). Überspringen im Assistenten schreibt nichts; Einstellungen ändert der
Assistent nur über denselben Weg wie die Einstellungsseite (/api/settings/preview, /api/settings).

Nicht in der Sicherung (backup.py, Allowlist): Der Zustand beschreibt dieses Gerät, nicht die
Einstellungen. Der Erststart legt einrichtung.json mit „fresh“ an, bevor jemand eine Sicherung einspielen
kann. Deshalb stellt ein erfolgreiches POST /api/restore/apply eine frische, noch nicht abgeschlossene
Installation auf „update“ um (restored()): Der Assistent öffnet sich dann nicht mehr von selbst, die
Übersicht zeigt einmalig den Hinweis „Einrichtung prüfen“ – denn Volume, Rechte und GPS hängen von der neuen
Umgebung ab. Nach „Fertig“ ändert eine Wiederherstellung am Zustand nichts. Geheimnisse stehen nicht darin.

Datenschutz: keine Verbindung nach außen, keine Position. Die Vorlagen für Zeitquellen sind eine feste
Liste im Dashboard (pages/settings.js, PRESETS); ob die Server erreichbar sind, prüft chrony selbst nach
dem Speichern.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any

import settings

STATE_NAME = "einrichtung.json"
VERSION = 1
# Spuren einer bestehenden Installation im Datenverzeichnis (Dateien oder Ordner).
EXISTING = ("settings.json", "ntp-gui.db", "history.json.gz", "autocal.json", "instance-id", "sicherungen")
ACTIONS = ("done", "never", "close_hint", "close_checklist", "reset")
CHECKLIST = ("check", "sources", "gps", "clients", "notify")
OPTIONAL = frozenset({"notify"})

# Abhilfe, wenn /var/lib/chrony auf keinem Volume liegt – dieselben Zeilen wie in docker-compose.yml: der Eintrag
# beim Dienst und die Deklaration auf oberster Ebene (ohne sie bricht „docker compose up -d“ ab).
VOLUME_FIX = ("# beim Dienst:\n    volumes:\n      - chrony-data:/var/lib/chrony\n"
              "# ganz unten, ohne Einrückung:\nvolumes:\n  chrony-data:")
SYS_TIME_FIX = "cap_add:\n  - SYS_TIME"

_LOCK = threading.Lock()
_MEMORY: dict[str, dict] = {}  # Datenverzeichnis nicht schreibbar: Zustand nur für diesen Lauf


def existing_install(data_dir: str) -> bool:
    """Liegt in data_dir schon etwas von ntp-gui? (Einstellungen, Datenbank, Verlauf …)"""
    for name in EXISTING:
        path = os.path.join(data_dir, name)
        try:
            if os.path.isdir(path):
                if os.listdir(path):
                    return True
            elif os.path.getsize(path) > 0:
                return True
        except OSError:
            continue
    return False


# Was beim Import im Datenverzeichnis lag – bevor server.py die Datenbank anlegt.
_BOOT = {"dir": os.path.realpath(settings.DATA_DIR), "existing": existing_install(settings.DATA_DIR)}


def _path() -> str:
    return os.path.join(settings.DATA_DIR, STATE_NAME)


def _clean(data: Any) -> dict | None:
    if not isinstance(data, dict) or data.get("install") not in {"fresh", "update"}:
        return None

    def when(key: str) -> float | None:
        value = data.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None

    return {"version": VERSION, "install": data["install"], "first_seen": when("first_seen"),
            "done": when("done"), "hint_closed": when("hint_closed"), "checklist_closed": when("checklist_closed"),
            "checklist_done": when("checklist_done")}


def _read() -> dict | None:
    try:
        with open(_path(), encoding="utf-8") as handle:
            return _clean(json.load(handle))
    except (OSError, ValueError):
        return None


def _write(state: dict) -> None:
    directory = settings.DATA_DIR
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".einrichtung-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, _path())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _store(state: dict) -> None:
    key = os.path.realpath(settings.DATA_DIR)
    try:
        _write(state)
        _MEMORY.pop(key, None)
    except OSError:
        _MEMORY[key] = state


def _classify() -> str:
    here = os.path.realpath(settings.DATA_DIR)
    existing = _BOOT["existing"] if here == _BOOT["dir"] else existing_install(settings.DATA_DIR)
    return "update" if existing else "fresh"


def state(now: float | None = None) -> dict:
    """Zustand der Einrichtung; beim ersten Aufruf ohne Datei wird entschieden und gespeichert."""
    with _LOCK:
        found = _read()
        if found:
            return found
        key = os.path.realpath(settings.DATA_DIR)
        if key in _MEMORY:
            return dict(_MEMORY[key])
        fresh = {"version": VERSION, "install": _classify(), "first_seen": float(now or time.time()),
                 "done": None, "hint_closed": None, "checklist_closed": None, "checklist_done": None}
        _store(fresh)
        return dict(fresh)


def remember() -> dict:
    """Beim Start des Servers: Erststart oder Update festschreiben (wirft nie)."""
    try:
        return state()
    except Exception as exc:  # der Start darf daran nie scheitern
        print(f"[web] Zustand der Einrichtung nicht lesbar: {exc}", flush=True)
        return {"install": "update", "done": None}


def action(name: Any, now: float | None = None) -> dict:
    """POST /api/setup: done | never | close_hint | close_checklist | reset. Gibt den neuen Zustand."""
    if name not in ACTIONS:
        raise ValueError("action muss „done“, „never“, „close_hint“, „close_checklist“ oder „reset“ sein")
    now = float(now or time.time())
    current = state(now)
    with _LOCK:
        new = dict(current)
        if name in {"done", "never"}:
            new["done"] = new["done"] or now
            new["hint_closed"] = new["hint_closed"] or now
            if name == "never":  # „Nicht mehr zeigen“: auch keine Checkliste auf der Übersicht
                new["checklist_closed"] = new["checklist_closed"] or now
        elif name == "close_hint":
            new["hint_closed"] = new["hint_closed"] or now
        elif name == "close_checklist":
            new["checklist_closed"] = new["checklist_closed"] or now
        else:  # reset: Assistent und Checkliste wieder wie neu (Erststart/Update bleibt)
            new.update(done=None, hint_closed=None, checklist_closed=None, checklist_done=None)
        if new != current:
            _store(new)
        return new


def restored() -> dict:
    """Nach POST /api/restore/apply: frische, nicht abgeschlossene Installation gilt als bestehend (wirft nie)."""
    try:
        current = state()
        with _LOCK:
            if current["install"] != "fresh" or current.get("done"):
                return current
            new = dict(current, install="update", hint_closed=None)
            _store(new)
            return new
    except Exception as exc:  # die Wiederherstellung darf daran nie scheitern
        print(f"[web] Zustand der Einrichtung nicht geändert: {exc}", flush=True)
        return {"install": "update", "done": None}


def _mark_checklist_done(now: float | None = None) -> None:
    """Checkliste einmal ganz grün: merken, damit sie nicht wiederkommt."""
    current = state()
    if current.get("checklist_done"):
        return
    with _LOCK:
        _store(dict(current, checklist_done=float(now or time.time())))


# ---------------------------------------------------------------------------
# Schritt (a): Prüfen – aus dem Hardware-Check
# ---------------------------------------------------------------------------

def _check(key: str, title: str, status: str, text: str, remedy: str | None = None,
           fix: str | None = None) -> dict:
    """status: ok | problem | info. Ein Problem hat genau eine Abhilfe (remedy, optional fix zum Kopieren)."""
    return {"key": key, "title": title, "status": status, "text": text, "remedy": remedy, "fix": fix}


def checks(cfg: dict, report: dict | None, storage: dict | None) -> list[dict]:
    """Volume vorhanden? SYS_TIME? GPS gefunden? Pi-Zustand ok? – je Punkt höchstens eine Abhilfe."""
    report = report or {}
    rows = {row.get("key"): row for row in report.get("matrix") or [] if isinstance(row, dict)}
    out: list[dict] = []

    if (storage or {}).get("persistent", True):
        out.append(_check("volume", "Daten-Volume", "ok",
                          "/var/lib/chrony liegt auf einem Volume – Einstellungen und Verlauf überstehen "
                          "ein Neuerstellen des Containers."))
    else:
        out.append(_check("volume", "Daten-Volume", "problem",
                          "/var/lib/chrony liegt nicht auf einem Volume: Einstellungen, Verlauf und Kalibrierung "
                          "gehen beim Neuerstellen des Containers verloren.",
                          "Im Compose ein Volume für /var/lib/chrony eintragen – beide Teile unten: beim Dienst "
                          "unter „volumes:“ und „chrony-data:“ ganz unten unter „volumes:“ – und den Container neu "
                          "erzeugen (docker compose up -d).", VOLUME_FIX))

    clock = rows.get("clock_control")
    if not clock:
        out.append(_check("sys_time", "Recht SYS_TIME", "info", "Noch kein Hardware-Check – gleich noch einmal prüfen."))
    elif clock.get("status") == "change":
        out.append(_check("sys_time", "Recht SYS_TIME", "problem",
                          "Es fehlt das Recht SYS_TIME: chrony liefert die Zeit nur aus und stellt die Uhr nicht.",
                          "Im Compose unter „cap_add:“ die Zeile „- SYS_TIME“ ergänzen und den Container neu "
                          "erzeugen (docker compose up -d).", clock.get("fix") or SYS_TIME_FIX))
    elif clock.get("status") == "ok":
        out.append(_check("sys_time", "Recht SYS_TIME", "ok", str(clock.get("text") or "")))
    else:
        out.append(_check("sys_time", "Recht SYS_TIME", "info", str(clock.get("text") or "")))

    gps_on = bool(cfg.get("gps_enable"))
    usb = rows.get("gps_usb") or {}
    receiver = gps_receiver(report)
    if gps_on and usb.get("status") == "ok":
        out.append(_check("gps", "GPS-Empfänger", "ok", str(usb.get("text") or "")))
    elif gps_on and usb.get("status") in {"change", "no"}:
        out.append(_check("gps", "GPS-Empfänger", "problem",
                          "GPS ist eingeschaltet, aber der Empfänger ist nicht nutzbar.",
                          str(usb.get("text") or ""), usb.get("fix") or None))
    elif gps_on:
        out.append(_check("gps", "GPS-Empfänger", "info", str(usb.get("text") or "GPS ist eingeschaltet.")))
    elif receiver:
        out.append(_check("gps", "GPS-Empfänger", "info",
                          f"Empfänger gefunden ({receiver['label']}), GPS ist aus. Im Schritt „GPS“ kannst du "
                          "es einschalten – optional."))
    else:
        out.append(_check("gps", "GPS-Empfänger", "info",
                          "Kein GPS-Empfänger gefunden. Das ist in Ordnung: GPS ist optional, die Zeit kommt "
                          "aus dem Netz."))

    power = rows.get("pi_power")
    if power:
        if power.get("status") == "ok":
            out.append(_check("pi", "Pi-Zustand", "ok", str(power.get("text") or "")))
        else:
            import pistate
            out.append(_check("pi", "Pi-Zustand", "problem", str(power.get("text") or "").split(". ")[0] + ".",
                              pistate.POWER_HINT))
    return out


def gps_receiver(report: dict | None) -> dict | None:
    """Erster Eintrag, der wie ein GPS-Empfänger aussieht: {label, device} – oder None."""
    for item in ((report or {}).get("gps") or {}).get("receivers") or []:
        if isinstance(item, dict) and item.get("gps_like"):
            device = str(item.get("stable_path") or item.get("dev") or "")
            return {"label": f"{item.get('product') or 'GPS'} an {item.get('dev') or device}",
                    "device": device if device.startswith("/dev/") else ""}
    return None


# ---------------------------------------------------------------------------
# Checkliste (Übersicht)
# ---------------------------------------------------------------------------

def checklist(cfg: dict, report: dict | None, storage: dict | None, tracking: dict | None,
              client_count: int, channels: int) -> dict:
    """Fünf Punkte; „Benachrichtigung“ ist optional und zählt nicht für „alles grün“."""
    found = checks(cfg, report, storage)
    problems = [c for c in found if c["status"] == "problem"]
    sources = cfg.get("ntp_sources") or []
    nts = sum(1 for s in sources if isinstance(s, dict) and s.get("nts"))
    synced = bool((tracking or {}).get("synchronised"))
    gps = next((c for c in found if c["key"] == "gps"), None)
    receiver = gps_receiver(report)
    gps_on = bool(cfg.get("gps_enable"))
    items = [
        {"id": "check", "ok": not problems, "count": len(problems)},
        {"id": "sources", "ok": synced and nts > 0, "nts": nts, "synchronised": synced},
        {"id": "gps", "ok": (gps_on and bool(gps) and gps["status"] == "ok") or (not gps_on and not receiver),
         "enabled": gps_on, "receiver": bool(receiver)},
        {"id": "clients", "ok": client_count > 0, "count": int(client_count)},
        {"id": "notify", "ok": channels > 0, "count": int(channels), "optional": True},
    ]
    done = sum(1 for item in items if item["ok"])
    complete = all(item["ok"] for item in items if item["id"] not in OPTIONAL)
    return {"items": items, "done": done, "total": len(items), "complete": complete}


def brief(readonly: bool) -> dict:
    """Kurzfassung für /api/status (ui.setup): ohne Hardware-Check, wirft nie."""
    try:
        st = state()
    except Exception:
        return {"auto_open": False, "hint": False, "done": False, "install": "update", "checklist": False}
    done = bool(st.get("done"))
    return {
        "install": st["install"], "done": done,
        "auto_open": not readonly and st["install"] == "fresh" and not done,
        "hint": not readonly and st["install"] == "update" and not done and not st.get("hint_closed"),
        # Checkliste möglich (ob sie erscheint, entscheidet GET /api/setup: nicht alles grün)
        "checklist": not readonly and not st.get("checklist_closed") and not st.get("checklist_done")
        and (st["install"] == "fresh" or done),
    }


def summary(cfg: dict, report: dict | None, storage: dict | None, tracking: dict | None,
            client_count: int, channels: int, readonly: bool, can_write: bool) -> dict:
    """Antwort von GET /api/setup."""
    short = brief(readonly)
    items = checklist(cfg, report, storage, tracking, client_count, channels)
    if short["checklist"] and items["complete"]:
        try:
            _mark_checklist_done()
        except OSError:
            pass
        short = brief(readonly)
    st = state()
    items["show"] = bool(short["checklist"]) and not items["complete"]
    items["closed"] = bool(st.get("checklist_closed"))
    receiver = gps_receiver(report)
    role = ((report or {}).get("gps") or {}).get("role") or {}
    sources = [{"type": s.get("type"), "host": s.get("host"), "nts": bool(s.get("nts"))}
               for s in cfg.get("ntp_sources") or [] if isinstance(s, dict)]
    return {
        "install": st["install"], "done": bool(st.get("done")), "done_at": st.get("done"),
        "auto_open": short["auto_open"], "hint": short["hint"],
        "readonly": bool(readonly), "can_write": bool(can_write and not readonly),
        "checks": checks(cfg, report, storage),
        "checklist": items,
        "sources": {"configured": sources, "synchronised": bool((tracking or {}).get("synchronised"))},
        "gps": {"enabled": bool(cfg.get("gps_enable")), "device": str(cfg.get("gps_device") or ""),
                "receiver": receiver, "pps": bool(cfg.get("gps_pps_device") or cfg.get("gps_pps_shm")),
                "role": role.get("role"), "role_label": role.get("label")},
        "clients": {"count": int(client_count)},
        "notify": {"channels": int(channels)},
    }
