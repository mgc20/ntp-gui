"""Diagnosepaket: alles Wichtige für eine Fehlersuche – ohne Standort, ohne Kennungen.

``preview(cfg, options)`` zeigt im Dashboard genau das, was exportiert würde,
``bundle(cfg, options)`` liefert dasselbe als tar.gz (eine Datei je Abschnitt
plus MANIFEST.txt). Beides läuft durch den zentralen Datenschutzfilter
(egress, Zweck "diagnostics"). Danach zwei Schranken: ``egress.check_no_leaks``
und die davon unabhängige ``egress.backstop`` auf den fertigen Bytes (sie sucht
u. a. exakt nach allem, was die Konfiguration an eigenen Namen, Seriennummern
und Interfaces kennt). Findet eine davon etwas, wird **nichts** exportiert.

Hochgeladen wird nichts: Das Paket landet nur im Browser der Person, die es
anfordert. Sie entscheidet, wem sie es gibt.

Außerdem: ``logs()`` für die Log-Seite (lokal, ungefiltert – verlässt die
Instanz nicht).
"""

from __future__ import annotations

import gzip
import io
import ipaddress
import json
import os
import platform
import re
import socket
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from typing import Any, Callable

import egress

RUN_DIR = os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")
CHRONY_CONF = os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")
PTP4L_CONF = os.environ.get("PTP4L_CONF", "/etc/linuxptp/ptp4l.conf")

DEADLINE = 2.5               # Sekunden für alle Sammler zusammen
SECTION_CAP = 512 * 1024     # Bytes je Abschnitt (nach dem Filtern)
# Eine Aufzeichnung von 1 h ist bei typischem Betrieb 6–10 MB groß. 4 MB schnitten sie auf die
# letzte halbe Stunde (Rückmeldung mit 1.3.2). Gefiltert wird seit 1.3.2 in einem eigenen Prozess
# mit niedriger Priorität – auf dem Pi dauert ein großes Paket länger, das Dashboard bleibt aber
# bedienbar.
RECORDING_CAP = 12 * 1024 * 1024
LOG_LINES = 2000
LOG_READ_BYTES = 1024 * 1024
EVENT_DAYS = 7
# Tabellen im CSV-Modus (-c): Im Klartext kürzt chronyc lange Namen mit ">" – eine gekürzte
# IPv6-Adresse würde der Filter nicht mehr sicher erkennen. Schlüssel/Wert-Ausgaben (tracking,
# ntpdata, serverstats, activity) kürzen nichts und bleiben lesbarer Klartext.
CHRONY_COMMANDS = [
    ("tracking", ("tracking",)),
    ("sources", ("-n", "-c", "sources")),
    ("sourcestats", ("-n", "-c", "sourcestats")),
    ("selectdata", ("-n", "-c", "selectdata")),
    ("ntpdata", ("-n", "ntpdata")),
    ("serverstats", ("serverstats",)),
    ("activity", ("activity",)),
    ("authdata", ("-n", "-c", "authdata")),
]
CHRONY_ARGS = dict(CHRONY_COMMANDS)
CSV_COLUMNS = {
    "sources": "Modus,Zustand,Name/IP,Stratum,Poll,Reach,LastRx,Offset (korrigiert),Offset (gemessen),"
               "Fehlerschranke (auf 10 ms gerundet)",
    "sourcestats": "Name/IP,Messpunkte,Läufe,Spanne,Frequenz (ppm),Frequenz-Schiefe (ppm),Offset,Std.-Abw.",
    "selectdata": "Zustand,Name/IP,Auth,Optionen (konfiguriert …),Optionen (wirksam …),Letzte Messung,Score,"
                  "Intervall unten,Intervall oben (Netzquellen auf 10 ms gerundet),Schaltsekunde",
    "authdata": "Name/IP,Modus,KeyID,Typ,Schlüssellänge,Letzter Schlüsseltausch,Versuche,NAK,Cookies,Cookie-Länge",
}

SECTION_TITLES = {
    "meta": "Version, Laufzeit, Plattform",
    "config": "Erzeugte Konfiguration (chrony.conf, ptp4l.conf)",
    "chrony": "chronyc-Ausgaben (tracking, sources, sourcestats, selectdata, ntpdata, serverstats, activity, authdata)",
    "clients": "Client-Liste (pseudonymisiert)",
    "gps": "GPS-Status und Geräte",
    "ptp": "PTP-Status und Log-Ende",
    "hardware": "Hardware-Check",
    "services": "Zustand der Dienste",
    "events": f"Ereignisse der letzten {EVENT_DAYS} Tage",
    "logs": f"Log (letzte {LOG_LINES} Zeilen)",
    "settings": "Einstellungen (ohne Zugangsdaten)",
    "history": "Verlauf der letzten 24 h (nur Kennzahlen)",
    "recording": "Aufzeichnung der Datenquellen",
}
DEFAULT_SECTIONS = ["meta", "config", "chrony", "gps", "ptp", "hardware", "services", "events",
                    "logs", "settings", "history"]
TEXT_SECTIONS = {"config", "chrony", "logs", "recording"}


class LeakError(RuntimeError):
    """Der Datenschutzfilter hat nach dem Filtern noch etwas gefunden."""

    def __init__(self, findings: list[dict]) -> None:
        self.findings = findings
        kinds = sorted({f.get("kind", "?") for f in findings})
        super().__init__("Export abgebrochen: Die Schlussprüfung hat noch personenbezogene oder "
                         f"ortsbezogene Daten gefunden ({', '.join(kinds)}). Bitte melde das als Fehler – "
                         "es wurde nichts exportiert.")


# ---------------------------------------------------------------------------
# Optionen
# ---------------------------------------------------------------------------

def _flag(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "ja"}


def options_from_query(query: dict) -> dict:
    """Query-Parameter (?clients=1&recording=1&sections=a,b) → Optionen."""
    opts = {"include_clients": _flag(query.get("clients", "0")),
            "include_recording": _flag(query.get("recording", "0"))}
    if query.get("sections"):
        opts["sections"] = [s for s in str(query["sections"]).split(",") if s in SECTION_TITLES]
    return opts


def _sections(options: dict, sections: list[str] | None) -> list[str]:
    chosen = list(sections or options.get("sections") or DEFAULT_SECTIONS)
    if options.get("include_clients") and "clients" not in chosen:
        chosen.insert(chosen.index("chrony") + 1 if "chrony" in chosen else len(chosen), "clients")
    if options.get("include_recording") and "recording" not in chosen:
        chosen.append("recording")
    return [s for s in dict.fromkeys(chosen) if s in SECTION_TITLES]


# ---------------------------------------------------------------------------
# Dateien lesen
# ---------------------------------------------------------------------------

def _read_tail(path: str, max_bytes: int) -> tuple[str, bool]:
    """Ende einer Datei (höchstens max_bytes), angeschnittene erste Zeile verworfen."""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        data = handle.read().decode("utf-8", errors="replace")
    cut = size > max_bytes
    if cut and "\n" in data:
        data = data.split("\n", 1)[1]
    return data, cut


def _cap_text(text: str, cap: int = SECTION_CAP) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= cap:
        return text, False
    # das Ende behalten – dort steht meist das Interessante
    tail = raw[-cap:].decode("utf-8", errors="ignore")
    if "\n" in tail:
        tail = tail.split("\n", 1)[1]
    return "[… gekürzt …]\n" + tail, True


def log_path() -> str:
    return os.path.join(RUN_DIR, "ntp-gui.log")


def _log_lines(max_lines: int) -> list[str]:
    lines: list[str] = []
    path = log_path()
    try:
        text, _ = _read_tail(path, LOG_READ_BYTES)
        lines = text.splitlines()
    except OSError:
        pass
    if len(lines) < max_lines:
        try:
            older, _ = _read_tail(path + ".1", LOG_READ_BYTES)
            lines = older.splitlines() + lines
        except OSError:
            pass
    return lines[-max_lines:]


# ---------------------------------------------------------------------------
# Log-Seite (lokal)
# ---------------------------------------------------------------------------

_CRIT_RE = re.compile(r"(?i)\b(fehler|error|fatal|failed|fehlgeschlagen|ausgefallen|kein start|crit)\b"
                      r"|unerwartet beendet|Traceback")
_WARN_RE = re.compile(r"(?i)\b(warnung|warning|warn|fehlt|verschwunden|zeitüberschreitung|timeout|timed out"
                      r"|nicht erreichbar|can't|cannot|could not|konnte nicht)\b")
_SOURCE_RE = re.compile(r"^\[([\w.-]{1,20})\]")


def line_level(text: str) -> str:
    if _CRIT_RE.search(text):
        return "crit"
    if _WARN_RE.search(text):
        return "warn"
    return "info"


def logs(lines: int = 500, q: str = "", level: str = "") -> dict:
    """Für GET /api/logs: die letzten Zeilen des Supervisor-Logs, optional gefiltert.

    q: Text, der vorkommen muss (Groß/Klein egal). level: "warn" zeigt nur
    Warnungen und Fehler, "crit" nur Fehler. Bleibt lokal – kein Filter nötig.
    """
    try:
        wanted = max(1, min(int(lines), 5000))
    except (TypeError, ValueError):
        wanted = 500
    available = os.path.exists(log_path())
    raw = _log_lines(20000 if (q or level) else wanted)
    needle = (q or "").strip().lower()[:200]
    rank = {"info": 0, "warn": 1, "crit": 2}
    minimum = rank.get(level or "info", 0)
    out = []
    for number, text in enumerate(raw, 1):
        lvl = line_level(text)
        if rank[lvl] < minimum:
            continue
        if needle and needle not in text.lower():
            continue
        match = _SOURCE_RE.match(text)
        out.append({"n": number, "text": text[:2000], "level": lvl,
                    "source": match.group(1) if match else ""})
    truncated = len(out) > wanted
    return {"available": available, "file": "ntp-gui.log", "total": len(raw),
            "lines": out[-wanted:], "truncated": truncated}


# ---------------------------------------------------------------------------
# Sammler (roh, ungefiltert)
# ---------------------------------------------------------------------------

def _chronyc(args: tuple[str, ...], timeout: float = 2.0) -> str:
    try:
        import providers  # P5: Aufzeichnung/Wiedergabe
        run = getattr(providers, "run", None)
    except ImportError:
        run = None
    if run is not None:
        return run("chronyc", list(args), timeout)
    import chrony
    return chrony.run(*args, timeout=timeout)


def _collect_meta(cfg: dict, options: dict) -> dict:
    now = time.time()
    offset = time.strftime("%z")
    meta: dict[str, Any] = {
        "programm": "ntp-gui",
        "version": options.get("version") or os.environ.get("NTPGUI_VERSION") or "unbekannt",
        "erstellt": int(now),
        "erstellt_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "utc_offset": f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else "+00:00",
        "dashboard_uptime_seconds": options.get("uptime_seconds"),
        "arch": platform.machine(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "container": None,
        "zweck": "diagnostics",
    }
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            meta["host_uptime_seconds"] = int(float(handle.read().split()[0]))
    except (OSError, ValueError, IndexError):
        pass
    if os.path.exists("/.dockerenv"):
        meta["container"] = "docker"
    elif os.path.exists("/run/.containerenv"):
        meta["container"] = "podman"
    try:
        import chrony
        meta["chronyc"] = chrony.CHRONYC
    except ImportError:
        pass
    return meta


def _collect_config(cfg: dict, options: dict) -> dict:
    files = {}
    for name, path in (("chrony.conf", options.get("chrony_conf") or CHRONY_CONF),
                       ("ptp4l.conf", options.get("ptp4l_conf") or PTP4L_CONF)):
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                files[name] = handle.read(SECTION_CAP)
        except OSError as exc:
            files[name] = f"# nicht lesbar: {exc.strerror or exc}"
    return files


def _collect_chrony(cfg: dict, options: dict) -> dict:
    out: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(CHRONY_COMMANDS)) as pool:
        futures = {name: pool.submit(_chronyc, args) for name, args in CHRONY_COMMANDS}
        for name, future in futures.items():
            try:
                text = future.result(timeout=DEADLINE)
                if name in CSV_COLUMNS and isinstance(text, str):
                    text = f"# Spalten: {CSV_COLUMNS[name]}\n{text}"
                out[name] = text
            except Exception as exc:  # chronyd weg, Zeitüberschreitung …
                out[name] = f"Fehler: {exc}"
    try:
        import chrony
        out["clients_count"] = len(chrony.clients())
        out["sources_detail"] = chrony.detailed_sources()
    except Exception as exc:
        out["sources_detail"] = f"Fehler: {exc}"
    return out


def _collect_clients(cfg: dict, options: dict) -> list:
    import chrony
    return chrony.clients()[:500]


def _collect_gps(cfg: dict, options: dict) -> dict:
    import devices
    import gps
    result: dict[str, Any] = {"status": gps.status()}
    try:
        result["devices"] = devices.summary(cfg)
    except Exception as exc:
        result["devices"] = f"Fehler: {exc}"
    return result


def _collect_ptp(cfg: dict, options: dict) -> dict:
    import ptp
    status = ptp.status()
    status.pop("log", None)
    return {"status": status, "log": "\n".join(ptp.log_tail(lines=300))}


def _collect_hardware(cfg: dict, options: dict) -> dict:
    import hardware
    return hardware.cached_report() or hardware.report(cfg)


def _collect_services(cfg: dict, options: dict) -> Any:
    try:
        with open(os.path.join(RUN_DIR, "services.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        return {"fehler": f"services.json nicht lesbar: {exc}"}


def _collect_events(cfg: dict, options: dict) -> Any:
    try:
        import events
    except ImportError:
        return {"hinweis": "Ereignisprotokoll nicht verfügbar"}
    rows = events.query(since=time.time() - EVENT_DAYS * 86400, limit=2000)
    try:
        import clientinfo
        strip_client = clientinfo.without_client_name
    except ImportError:  # pragma: no cover
        def strip_client(row: Any) -> Any:
            return row
    return [strip_client(_without_key_name(row)) for row in rows]


def _without_key_name(row: Any) -> Any:
    """Ältere Ereignisse trugen den frei gewählten Namen eines API-Schlüssels im Titel."""
    if not isinstance(row, dict) or not str(row.get("title", "")).startswith("API-Schlüssel"):
        return row
    row = dict(row)
    data = dict(row.get("data") or {}) if isinstance(row.get("data"), dict) else {}
    data.pop("name", None)
    key_id = data.get("id")
    head = str(row["title"]).split(":", 1)[0]
    row["title"] = f"{head}: {key_id}" if key_id else head
    row["data"] = data
    return row


def _collect_logs(cfg: dict, options: dict) -> str:
    lines = _log_lines(LOG_LINES)
    if not lines:
        return "# Kein Log vorhanden (ntp-gui.log fehlt – Dashboard ohne Supervisor gestartet?)"
    return "\n".join(lines)


def _collect_settings(cfg: dict, options: dict) -> dict:
    import settings
    values = dict(cfg) if cfg else dict(settings.values())
    # Herkunft gruppiert ({"env": [schlüssel …]}), nicht je Schlüssel – sonst hielte der
    # Filter "default" unter web_title für einen Titel.
    sources: dict[str, list] = {}
    try:
        for key, entry in settings.effective().items():
            if isinstance(entry, dict):
                sources.setdefault(str(entry.get("source")), []).append(key)
    except Exception:
        pass
    for key in list(values):
        if re.search(r"(?i)pass|hash|secret|token|auth", key):
            values.pop(key)
    if isinstance(values.get("dns_doh"), list):
        # Der Pfad einer DoH-Adresse kann eine Konto-Kennung sein (z. B. NextDNS) – nur der Server.
        import dnsfwd
        values["dns_doh"] = [dnsfwd.doh_label(str(url)) for url in values["dns_doh"]]
    return {"values": values, "herkunft": sources}


def _stats(values: list[float]) -> dict | None:
    nums = sorted(v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not nums:
        return None
    absolute = sorted(abs(v) for v in nums)
    p95 = absolute[min(len(absolute) - 1, int(round(0.95 * (len(absolute) - 1))))]
    return {"n": len(nums), "min": nums[0], "max": nums[-1], "mean": sum(nums) / len(nums),
            "p95_abs": p95, "last": values[-1] if isinstance(values[-1], (int, float)) else None}


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def summarize_history(samples: list[dict], since: float | None = None) -> dict:
    """Kennzahlen statt Rohdaten: Anzahl, Min/Max/Mittel, 95 %-Wert je Größe."""
    if since is not None:
        samples = [s for s in samples if isinstance(s, dict) and s.get("t", 0) >= since]
    samples = [s for s in samples if isinstance(s, dict)]
    if not samples:
        return {"samples": 0}
    out: dict[str, Any] = {
        "samples": len(samples),
        "from": samples[0].get("t"), "to": samples[-1].get("t"),
        "metrics": {},
    }
    for key in ("offset", "rms", "freq", "skew", "root_delay", "root_dispersion", "stratum", "clients", "temp"):
        stats = _stats([s.get(key) for s in samples])
        if stats:
            out["metrics"][key] = stats
    # Temperatur ↔ Frequenz (Grundlage für den Temperaturausgleich): Mittel je Stunde seit Beginn
    # des Zeitraums – nur Kennzahlen, keine Rohdaten; Stunden zählen ab „from“, nicht nach Uhrzeit.
    start = samples[0].get("t") or 0
    hours: dict[int, dict[str, list]] = {}
    for sample in samples:
        temp, freq = sample.get("temp"), sample.get("freq")
        if not (_num(temp) and _num(freq)):
            continue
        slot = hours.setdefault(int(((sample.get("t") or start) - start) // 3600), {"temp": [], "freq": []})
        slot["temp"].append(float(temp))
        slot["freq"].append(float(freq))
    if hours:
        out["temp_freq_hourly"] = [
            {"h": h, "n": len(v["temp"]), "temp": round(sum(v["temp"]) / len(v["temp"]), 2),
             "freq": round(sum(v["freq"]) / len(v["freq"]), 4)}
            for h, v in sorted(hours.items())]
    strata = [s.get("stratum") for s in samples if s.get("stratum") is not None]
    out["stratum_changes"] = sum(1 for a, b in zip(strata, strata[1:]) if a != b)
    sources: dict[str, dict] = {}
    for sample in samples:
        for name, entry in (sample.get("sources") or {}).items():
            if not isinstance(entry, dict):
                continue
            item = sources.setdefault(str(name), {"samples": 0, "states": {}, "_o": []})
            item["samples"] += 1
            state = str(entry.get("s"))
            item["states"][state] = item["states"].get(state, 0) + 1
            item["_o"].append(entry.get("o"))
    for item in sources.values():
        item["offset"] = _stats(item.pop("_o"))
    out["sources"] = sources
    for group in ("gps", "ptp"):
        rows = [s.get(group) for s in samples if isinstance(s.get(group), dict)]
        if rows:
            keys = sorted({k for row in rows for k in row})
            out[group] = {k: _stats([row.get(k) for row in rows]) for k in keys}
    return out


def _collect_history(cfg: dict, options: dict) -> dict:
    samples = options.get("history")
    if samples is None:
        import settings
        path = os.path.join(settings.DATA_DIR, "history.json.gz")
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                samples = json.load(handle)
        except (OSError, ValueError, EOFError):
            samples = []
    if not isinstance(samples, list):
        samples = []
    return summarize_history(samples, since=time.time() - 86400)


def _collect_recording(cfg: dict, options: dict) -> str:
    try:
        import providers
    except ImportError:
        return "# Aufzeichnung nicht verfügbar (Modul providers fehlt)"
    status = providers.status() if hasattr(providers, "status") else {}
    path = (status or {}).get("path") or (status or {}).get("file")
    if not path or not os.path.isfile(path):
        return "# Keine Aufzeichnung vorhanden – starte sie auf der Seite „Diagnose“."
    text, cut = _read_tail(path, RECORDING_CAP)
    return ("# [Anfang gekürzt]\n" if cut else "") + text


COLLECTORS: dict[str, Callable[[dict, dict], Any]] = {
    "meta": _collect_meta, "config": _collect_config, "chrony": _collect_chrony,
    "clients": _collect_clients, "gps": _collect_gps, "ptp": _collect_ptp,
    "hardware": _collect_hardware, "services": _collect_services, "events": _collect_events,
    "logs": _collect_logs, "settings": _collect_settings, "history": _collect_history,
    "recording": _collect_recording,
}


def _collect(cfg: dict, names: list[str], options: dict) -> dict:
    """Alle Abschnitte parallel; was nach DEADLINE nicht fertig ist, wird vermerkt."""
    results: dict[str, Any] = {}
    pool = ThreadPoolExecutor(max_workers=max(1, len(names)), thread_name_prefix="diag")
    futures = {name: pool.submit(COLLECTORS[name], cfg, options) for name in names}
    futures_wait(list(futures.values()), timeout=DEADLINE)
    for name, future in futures.items():
        if not future.done():
            results[name] = {"fehler": f"Zeitüberschreitung nach {DEADLINE:g} s – Abschnitt fehlt"}
            continue
        try:
            results[name] = future.result()
        except Exception as exc:
            results[name] = {"fehler": f"{type(exc).__name__}: {exc}"}
    pool.shutdown(wait=False, cancel_futures=True)
    return results


# ---------------------------------------------------------------------------
# Filtern, Prüfen, Verpacken
# ---------------------------------------------------------------------------

def _read_first_line(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


def _sys_root() -> str:
    return os.environ.get("NTPGUI_SYS_ROOT", "/sys")


def _hardware_serials() -> list[str]:
    """Echte Seriennummern dieses Geräts (USB, DMI) – für die exakte Suche im Export."""
    import glob
    root = _sys_root()
    found = []
    for path in sorted(glob.glob(os.path.join(root, "bus", "usb", "devices", "*", "serial")))[:256]:
        found.append(_read_first_line(path))
    for name in ("product_serial", "board_serial", "chassis_serial", "product_uuid"):
        found.append(_read_first_line(os.path.join(root, "class", "dmi", "id", name)))
    # DS18B20-Temperaturfühler (1.4): die Kennung „28-…“ ist die eindeutige ROM-Seriennummer.
    for path in sorted(glob.glob(os.path.join(root, "bus", "w1", "devices", "28-*")))[:64]:
        name = os.path.basename(path)
        found += [name, name[3:]]
    return [v for v in dict.fromkeys(found) if egress.serial_is_specific(v)]


def _interface_names(cfg: dict) -> list[str]:
    names = [cfg.get("ptp_interface"), cfg.get("ntp_hw_timestamp_interface")]
    try:
        names += os.listdir(os.path.join(_sys_root(), "class", "net"))
    except OSError:
        pass
    return [str(n) for n in dict.fromkeys(names) if n and str(n) not in {"*", "auto"}]


def _cert_names(cfg: dict) -> list[str]:
    path = cfg.get("nts_server_cert")
    if not path or not os.path.isfile(str(path)):
        return []
    try:
        import chrony
        info = chrony._cert_info(str(path))
    except Exception:
        return []
    names = [info.get("common_name"), *(info.get("alt_names") or [])]
    return [str(n).lstrip("*.") for n in names if n]


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(str(text).strip().strip("[]").split("%", 1)[0])
        return True
    except ValueError:
        return False


# --- Eigene Rechnernamen ------------------------------------------------------
# socket.getfqdn() fragt das DNS rückwärts – bei einem langsamen Resolver (Hostname nicht in
# /etc/hosts, „timeout:2 attempts:3“) dauert das Sekunden. Früher geschah das bei jeder Anfrage
# mit fremdem Host-Kopf (blockierte einen Handler-Thread, von außen auslösbar) und beim
# Diagnose-Export außerhalb seiner Frist. Jetzt: einmal im Hintergrund, Ergebnis gemerkt.
OWN_NAMES_TTL = 3600.0
_OWN: dict[str, Any] = {"fqdn": None, "t": None, "thread": None, "started": None, "done": threading.Event()}
_OWN_LOCK = threading.Lock()


def _lookup_fqdn(done: threading.Event) -> None:
    try:
        fqdn = socket.getfqdn()
    except (OSError, UnicodeError):
        fqdn = ""
    with _OWN_LOCK:
        if _OWN["thread"] is threading.current_thread():  # nach _reset_own_names() verwerfen
            _OWN.update(fqdn=fqdn, t=time.monotonic(), thread=None)
    done.set()


def own_hostnames(wait: float = 0.0) -> set[str]:
    """Eigene Rechnernamen (klein, ohne Punkt am Ende): gethostname() sofort, dazu der FQDN aus
    einer Hintergrund-Abfrage (stündlich aufgefrischt). Solange die allererste Abfrage läuft,
    wartet ein Aufrufer bis höchstens `wait` Sekunden nach deren Start – alle Aufrufer zusammen
    also nicht länger als einmal `wait`, egal wie lange der Resolver hängt."""
    names = set()
    try:
        names.add(socket.gethostname())
    except OSError:
        pass
    now = time.monotonic()
    with _OWN_LOCK:
        stale = _OWN["t"] is None or now - _OWN["t"] >= OWN_NAMES_TTL
        if stale and _OWN["thread"] is None:
            done = _OWN["done"] if _OWN["t"] is None else threading.Event()
            thread = threading.Thread(target=_lookup_fqdn, args=(done,), daemon=True, name="own-fqdn")
            _OWN.update(thread=thread, started=now)
            thread.start()
        done, fqdn, started = _OWN["done"], _OWN["fqdn"], _OWN["started"]
    if fqdn is None and wait > 0 and started is not None:
        done.wait(max(0.0, started + wait - now))
        fqdn = _OWN["fqdn"]
    if fqdn:
        names.add(fqdn)
    return {n.lower().rstrip(".") for n in names if n}


def _reset_own_names() -> None:
    """Für Tests: Cache vergessen (die nächste Abfrage startet neu, laufende werden verworfen)."""
    with _OWN_LOCK:
        _OWN.update(fqdn=None, t=None, thread=None, started=None, done=threading.Event())


def _known_names(cfg: dict) -> list[str]:
    """Eigene Host- und Domainnamen: Rechner, NTS, Quellen, Erzwingen-Liste, Zertifikat, bind_address."""
    names = set(own_hostnames(wait=min(1.0, DEADLINE / 2)))
    for key in ("nts_server_name", "bind_address"):
        if cfg.get(key):
            names.add(str(cfg[key]))
    for source in cfg.get("ntp_sources") or []:
        if isinstance(source, dict) and source.get("host"):
            names.add(str(source["host"]))
    hosts = cfg.get("enforce_hostnames") or []
    if isinstance(hosts, str):
        hosts = re.split(r"[\s,]+", hosts)
    names.update(str(h) for h in hosts if h)
    names.update(_cert_names(cfg))
    for env in ("HOSTNAME", "NTPGUI_PUBLIC_NAME"):
        if os.environ.get(env):
            names.add(os.environ[env])
    out = []
    for name in names:
        n = str(name).strip().strip("[]").rstrip(".")
        if not n or n in {"localhost", "localhost.localdomain", "*", "auto"} or _is_ip(n):
            continue
        if egress.is_public_host(n):
            continue  # öffentliche Zeitdienste (ptbtime1.ptb.de …) bleiben lesbar
        out.append(n)
    return out


def _known_values(cfg: dict) -> dict:
    """Weitere exakt zu suchende Werte: Titel, Seriennummern, eigene Interface-Namen."""
    title = str(cfg.get("web_title") or "").strip()
    return {
        "titel": [title] if title and title not in egress.DEFAULT_TITLES else [],
        "seriennummer": _hardware_serials(),
        "schnittstelle": _interface_names(cfg),
        "name": _client_names(),
    }


def _client_names() -> list[str]:
    """Selbst vergebene Namen der Clients (Clients-Detailseite) – egress ersetzt sie durch <name>."""
    try:
        import clientinfo
        return clientinfo.export_names()
    except Exception:  # noqa: BLE001
        return []


def _render(name: str, content: Any) -> tuple[str, str]:
    """Abschnitt → (Dateiname, Text) – genau so landet er im Paket."""
    if name in TEXT_SECTIONS and isinstance(content, dict) and all(isinstance(v, str) for v in content.values()):
        parts = [f"===== {key} =====\n{value.rstrip()}\n" for key, value in content.items()]
        return f"{name}.txt", "\n".join(parts)
    if name in TEXT_SECTIONS and isinstance(content, dict):
        texts = {k: v for k, v in content.items() if isinstance(v, str)}
        rest = {k: v for k, v in content.items() if not isinstance(v, str)}
        parts = [f"===== {key} =====\n{value.rstrip()}\n" for key, value in texts.items()]
        if rest:
            parts.append("===== weitere Daten (JSON) =====\n"
                         + json.dumps(rest, indent=2, ensure_ascii=False, default=str) + "\n")
        return f"{name}.txt", "\n".join(parts)
    if isinstance(content, str):
        suffix = "jsonl" if name == "recording" else "txt"
        return f"{name}.{suffix}", content if content.endswith("\n") else content + "\n"
    return f"{name}.json", json.dumps(content, indent=2, ensure_ascii=False, default=str) + "\n"


def _gather(cfg: dict, sections: list[str] | None, options: dict) -> dict:
    """Rohdaten einsammeln (im Dashboard-Prozess: GPS-, Client- und Aufzeichnungszustand liegen
    dort im Speicher). Ergebnis ist reines JSON – der Filter kann in einem eigenen Prozess laufen."""
    options = dict(options or {})
    names = _sections(options, sections)
    known = {key: sorted(str(v) for v in values) for key, values in _known_values(cfg or {}).items()}
    job = {"names": names, "raw": _collect(cfg or {}, names, options),
           "known_names": sorted(_known_names(cfg or {})), "known_values": known}
    # Rundreise durch JSON auch im selben Prozess: Worker und Direktaufruf sehen dieselben Daten.
    return json.loads(json.dumps(job, ensure_ascii=False, default=str))


def _build(cfg: dict, sections: list[str] | None, options: dict) -> tuple[dict, dict, dict]:
    return _process(_gather(cfg, sections, options))


def _backstop_memo(sanitizer: Any) -> "egress.BackstopMemo":
    """Ein Zwischenspeicher für egress.backstop je Exportlauf: Dieselben Zeilen laufen in
    drop_leaky_lines, in _process und in _bundle_of durch die Prüfung. Gilt nur für die bekannten
    Werte dieses Laufs (backstop prüft das) und verschwindet mit dem Sanitizer."""
    memo = getattr(sanitizer, "_diag_backstop_memo", None)
    if memo is None:
        memo = egress.BackstopMemo(sanitizer.backstop_known())
        sanitizer._diag_backstop_memo = memo
    return memo


def _process(job: dict) -> tuple[dict, Any, dict]:
    """Filtern und beide Schlussprüfungen – reine Funktion der eingesammelten Rohdaten."""
    names, raw = job["names"], job["raw"]
    sanitizer = egress.Sanitizer("diagnostics", job["known_names"], job["known_values"])
    content: dict[str, Any] = {}
    truncated: dict[str, bool] = {}
    for name in names:
        value = raw.get(name)
        cut = False
        if isinstance(value, str):
            value, cut = _cap_text(value, RECORDING_CAP if name == "recording" else SECTION_CAP)
        if name == "chrony" and isinstance(value, dict):
            clean = {sanitizer.text(k): (sanitizer.chronyc(CHRONY_ARGS[k], v) if k in CHRONY_ARGS
                                         and isinstance(v, str) else sanitizer.obj(v))
                     for k, v in value.items()}
        else:
            clean = sanitizer.obj(value)
        filename, text = _render(name, clean)
        cap = RECORDING_CAP if name == "recording" else SECTION_CAP
        if len(text.encode("utf-8")) > cap:
            text, more = _cap_text(text, cap)
            cut = cut or more
            clean = text  # gekürzt: als Text weiterreichen, damit Vorschau == Paket
        if name in LINE_SECTIONS and isinstance(clean, str):
            clean = drop_leaky_lines(clean, sanitizer)
        elif name == "ptp" and isinstance(clean, dict) and isinstance(clean.get("log"), str):
            clean = dict(clean, log=drop_leaky_lines(clean["log"], sanitizer))
        content[name] = clean
        truncated[name] = cut
    findings = egress.check_no_leaks(content)
    if findings:
        raise LeakError(findings)
    rendered = {}
    compact = {}
    for name, value in content.items():
        filename, text = _render(name, value)
        rendered[filename] = text.encode("utf-8")
        if not isinstance(value, str):
            # Eingerückt steht jede Zahl auf einer eigenen Zeile – kompakt sieht die Schlussprüfung
            # auch Zahlenpaare in Listen und Objekten.
            compact[f"{filename} (kompakt)"] = json.dumps(value, separators=(",", ":"), ensure_ascii=False,
                                                          default=str).encode("utf-8")
    findings = (egress.backstop(rendered, sanitizer.backstop_known(), _backstop_memo(sanitizer))
                + egress.backstop_compact_json(compact))
    if findings:
        raise LeakError(findings)
    return content, sanitizer, truncated


LINE_SECTIONS = {"logs", "recording"}
DROPPED_LINE = "[Zeile entfernt – Datenschutz]"


def drop_leaky_lines(text: str, sanitizer: "egress.Sanitizer") -> str:
    """Log-Zeilen, die eine der beiden Schlussprüfungen beanstandet, ganz entfernen.

    In Logs und Aufzeichnungen steht fremder Text (z. B. ein abgelehnter Host-Name). Statt den
    ganzen Export abzubrechen – das ließe sich von außen erzwingen –, fliegt nur die Zeile raus.
    Danach laufen beide Prüfungen wie immer über das ganze Paket.
    """
    bad: set[int] = set()
    for finding in egress.check_no_leaks(text):
        match = re.search(r"Zeile (\d+)", str(finding.get("path", "")))
        if match:
            bad.add(int(match.group(1)))
    for finding in egress.backstop({"abschnitt": text.encode("utf-8")}, sanitizer.backstop_known(),
                                   _backstop_memo(sanitizer)):
        match = re.search(r"Zeile (\d+)", str(finding.get("path", "")))
        if match:
            bad.add(int(match.group(1)))
    if not bad:
        return text
    lines = text.split("\n")
    for number in bad:
        if 1 <= number <= len(lines):
            lines[number - 1] = DROPPED_LINE
    sanitizer.count("zeile_entfernt", len(bad))
    return "\n".join(lines)


def build(cfg: dict, sections: list[str] | None = None, options: dict | None = None) -> dict:
    """Gefilterte Abschnitte {name: inhalt}. Wirft LeakError, wenn die Schlussprüfung anschlägt."""
    try:
        content, _sanitizer, _cut = _build(cfg, sections, options or {})
    finally:
        egress.clear_check_caches()
    return content


def _report_with_labels(report: dict) -> dict:
    removed = report.get("removed", {})
    return {"removed": removed, "pseudonyms": report.get("pseudonyms", 0),
            "labels": {k: egress.CATEGORIES.get(k, k) for k in removed}}


def preview(cfg: dict, options: dict | None = None) -> dict:
    """Für GET /api/diagnostics/preview: genau das, was im Paket stünde."""
    try:
        return _preview_of(*_build(cfg, None, options or {}))
    finally:
        egress.clear_check_caches()


def _preview_of(content: dict, sanitizer: Any, truncated: dict) -> dict:
    report = sanitizer.report()
    sections = []
    for name, value in content.items():
        filename, text = _render(name, value)
        sections.append({"name": name, "title": SECTION_TITLES.get(name, name), "file": filename,
                         "size": len(text.encode("utf-8")), "truncated": truncated.get(name, False)})
    return {"ok": True, "generated": int(time.time()), "filename": filename_for(),
            "sections": sections, "removed": _report_with_labels(report), "content": content}


def filename_for(now: float | None = None) -> str:
    return time.strftime("ntp-gui-diagnose-%Y%m%d-%H%M%S.tar.gz", time.gmtime(now or time.time()))


def manifest(sections: list[dict], report: dict, generated: float) -> str:
    lines = [
        "ntp-gui – Diagnosepaket",
        "=======================",
        "",
        f"Erstellt: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(generated))}",
        "",
        "Dieses Paket wurde auf deinem Gerät erzeugt und nirgendwohin hochgeladen. Du entscheidest,",
        "wem du es gibst (z. B. als Anhang an ein GitHub-Issue). Schau vorher gern hinein – es sind",
        "nur Text- und JSON-Dateien.",
        "",
        "Inhalt",
        "------",
    ]
    for section in sections:
        note = " (gekürzt)" if section.get("truncated") else ""
        lines.append(f"  {section['file']:<18} {section['title']}{note}")
    lines += [
        "",
        "Was der Datenschutzfilter entfernt oder ersetzt hat – und warum",
        "--------------------------------------------------------------",
        "Ziel: Aus diesem Paket lässt sich kein Standort bestimmen und kein Gerät wiedererkennen.",
        "",
    ]
    removed = report.get("removed", {})
    if removed:
        for key, count in sorted(removed.items()):
            # Schlüssel in Klammern, nicht "schlüssel: wert" – sonst sähe die Schlussprüfung
            # in "seriennummer: Seriennummern …" selbst eine Seriennummer.
            lines.append(f"  {count:>5} × [{key}] {egress.CATEGORIES.get(key, key)}")
    else:
        lines.append("  Nichts gefunden, das entfernt werden musste.")
    lines += [
        "",
        f"  Vergebene Pseudonyme: {report.get('pseudonyms', 0)} (z. B. client-01, <hostname-1>). Sie sind",
        "  nur innerhalb dieses Pakets stabil und lassen sich nicht auf echte Adressen zurückführen.",
        "",
        "Immer entfernt, auch wenn nichts davon vorkam: Koordinaten, Höhe, Geschwindigkeit,",
        "Satellitenwinkel, Seriennummern, MAC-Adressen, öffentliche IP-Adressen, eigene Domains,",
        "Zertifikatsnamen, Zeitzonennamen (nur der UTC-Versatz bleibt), Passwörter.",
        "Die Client-Liste ist nur enthalten, wenn du sie ausdrücklich eingeschlossen hast – dann",
        "mit Pseudonymen statt Adressen.",
        "",
    ]
    return "\n".join(lines)


def bundle(cfg: dict, options: dict | None = None) -> bytes:
    """Für GET /api/diagnostics/bundle: tar.gz mit einer Datei je Abschnitt + MANIFEST.txt."""
    try:
        return _bundle_of(*_build(cfg, None, options or {}))
    finally:
        egress.clear_check_caches()


def _bundle_of(content: dict, sanitizer: Any, truncated: dict, generated: float | None = None) -> bytes:
    report = sanitizer.report()
    generated = generated or time.time()
    base = filename_for(generated)[:-len(".tar.gz")]
    files: list[tuple[str, bytes]] = []
    sections = []
    for name, value in content.items():
        filename, text = _render(name, value)
        files.append((filename, text.encode("utf-8")))
        sections.append({"name": name, "file": filename, "title": SECTION_TITLES.get(name, name),
                         "truncated": truncated.get(name, False)})
    # Auch das MANIFEST durch den Filter: Ein Titel wie „Zeitserver“ stünde sonst in unseren
    # eigenen Erklärungen und die Schlussprüfung bräche (zu Recht) ab.
    manifest_text = sanitizer.text(manifest(sections, report, generated))
    # Schlussprüfung auf genau den Bytes, die das Paket verlassen.
    for filename, data in files + [("MANIFEST.txt", manifest_text.encode("utf-8"))]:
        findings = egress.check_no_leaks(data.decode("utf-8"))
        if findings:
            raise LeakError([dict(f, path=f"{filename}: {f['path']}") for f in findings])
    findings = egress.backstop(dict(files + [("MANIFEST.txt", manifest_text.encode("utf-8"))]),
                               sanitizer.backstop_known(), _backstop_memo(sanitizer))
    if findings:
        raise LeakError(findings)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for filename, data in [("MANIFEST.txt", manifest_text.encode("utf-8"))] + files:
            info = tarfile.TarInfo(f"{base}/{filename}")
            info.size = len(data)
            info.mtime = int(generated)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Für den Server: eigener Prozess + Wiederverwendung der Vorschau
# ---------------------------------------------------------------------------
# Filter und Prüfungen sind reine Rechenarbeit (auf dem Pi für 10 min Aufzeichnung etliche
# Sekunden). Im Dashboard-Prozess würden sie über das GIL jede andere Anfrage ausbremsen.
# Deshalb rechnet ein kurzlebiger Kindprozess mit niedriger Priorität (nice 10); er bekommt die
# Rohdaten als JSON und liefert Vorschau *und* Paket in einem Durchgang. Der Download nach der
# Vorschau nimmt dieses Ergebnis – das Paket ist damit genau das, was die Vorschau gezeigt hat.

_lock = threading.Lock()  # nie zwei Pakete gleichzeitig bauen (CPU auf dem Pi schonen)
WORKER_TIMEOUT = 900.0
REUSE_SECONDS = 600.0      # so lange gilt eine Vorschau für den Download
# {"key", "t", "done", "token", "preview", "bundle", "filename"} – nur unter _lock lesen/schreiben.
_last: dict[str, Any] = {}


def _package(job: dict) -> dict:
    """Vorschau und Paket aus einem Filterlauf. LeakError steigt auf."""
    try:
        content, sanitizer, truncated = _process(job)
        generated = time.time()
        view = _preview_of(content, sanitizer, truncated)
        view["generated"] = int(generated)
        view["filename"] = filename_for(generated)
        return {"preview": view, "bundle": _bundle_of(content, sanitizer, truncated, generated)}
    finally:
        egress.clear_check_caches()


def _worker_failed(returncode: int, stderr: bytes) -> str:
    """Fehlermeldung, wenn der Kindprozess kein Ergebnis geliefert hat – mit Signal/Rückgabewert,
    damit sich ein OOM-Kill (Signal 9) von einem Absturz unterscheiden lässt."""
    import signal
    if returncode < 0:
        try:
            name = signal.Signals(-returncode).name
        except ValueError:
            name = f"Signal {-returncode}"
        why = f"beendet durch {name} ({-returncode})"
        if returncode == -9:
            why += " – vermutlich zu wenig Arbeitsspeicher"
    else:
        why = f"Rückgabewert {returncode}"
    tail = stderr.decode("utf-8", errors="replace").strip().splitlines()[-1:]
    return f"Diagnose-Prozess fehlgeschlagen ({why})" + (f": {tail[0]}" if tail else "")


def _run_worker(job: dict) -> dict:
    """_package in einem eigenen Python-Prozess; fällt auf den Dashboard-Prozess zurück,
    wenn kein Kindprozess gestartet werden kann."""
    import base64
    import subprocess
    import sys
    payload = json.dumps(job, ensure_ascii=False).encode("utf-8")
    try:
        proc = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__), "--worker"],
                              input=payload, capture_output=True, timeout=WORKER_TIMEOUT)
    except (OSError, ValueError):
        return _package(job)
    except subprocess.TimeoutExpired:
        message = f"Das Diagnosepaket wurde nach {WORKER_TIMEOUT:g} s nicht fertig."
        print(f"diagnostics: {message}", file=sys.stderr, flush=True)
        raise RuntimeError(message) from None
    try:
        result = json.loads(proc.stdout.decode("utf-8"))
    except ValueError:
        message = _worker_failed(proc.returncode, proc.stderr)
        print(f"diagnostics: {message}", file=sys.stderr, flush=True)  # landet im Container-Log
        raise RuntimeError(message) from None
    if not result.get("ok"):
        if result.get("findings") is not None:
            raise LeakError(result["findings"])
        raise RuntimeError(result.get("error") or "Diagnose-Prozess fehlgeschlagen")
    return {"preview": result["preview"], "bundle": base64.b64decode(result["bundle"])}


def _recording_identity() -> Any:
    """Welche Aufzeichnung gerade gilt (Pfad, Größe, Änderungszeit) – eine neue oder weiter
    wachsende Aufzeichnung darf kein altes Ergebnis wiederverwenden."""
    try:
        import providers
        status = providers.status() if hasattr(providers, "status") else {}
    except Exception:  # noqa: BLE001 – dann eben keine Wiederverwendung über diesen Schlüssel hinaus
        return ["unbekannt", time.time()]
    path = (status or {}).get("path") or (status or {}).get("file")
    try:
        st = os.stat(path) if path else None
    except OSError:
        st = None
    return [path, bool((status or {}).get("active")),
            [st.st_ino, st.st_size, st.st_mtime_ns] if st else None]


def _key(cfg: dict, options: dict) -> str:
    """Was die Auswahl bestimmt – nicht Laufzeit oder Verlauf, die sich jede Sekunde ändern.
    Mit Aufzeichnung auch, welche Aufzeichnung (Datei, Größe, Zeit) gerade gilt."""
    chosen = {k: options.get(k) for k in ("include_clients", "include_recording", "sections")}
    names = _sections(options, None)
    data = _recording_identity() if "recording" in names else None
    return json.dumps([cfg, chosen, data], sort_keys=True, ensure_ascii=False, default=str)


def _produce(cfg: dict, options: dict) -> dict:
    """Neu bauen (unter _lock). Vorher das alte Ergebnis verwerfen: Schlägt der Lauf fehl, darf
    ein späterer Download nicht stillschweigend ein älteres Paket liefern."""
    import secrets
    _last.clear()
    key = _key(cfg, options)  # vor dem Einsammeln: wächst die Aufzeichnung inzwischen, passt er nicht mehr
    result = _run_worker(_gather(cfg, None, options))
    token = secrets.token_hex(8)
    result["preview"]["reuse"] = token
    _last.update(key=key, t=time.monotonic(), token=token, filename=result["preview"].get("filename"),
                 **result)
    return result


def _fresh_for(arrived: float, key: str) -> bool:
    """Ein Lauf mit gleichem Schlüssel ist fertig geworden, während diese Anfrage gewartet hat –
    sein Ergebnis ist so frisch wie ein neuer Lauf (mehrfach geklickt, Seite neu geladen)."""
    return bool(_last) and _last.get("key") == key and _last.get("t", 0.0) >= arrived


def preview_locked(cfg: dict, options: dict | None = None) -> dict:
    options = options or {}
    arrived = time.monotonic()
    with _lock:
        if _fresh_for(arrived, _key(cfg, options)):
            return _last["preview"]
        return _produce(cfg, options)["preview"]


def bundle_locked(cfg: dict, options: dict | None = None, reuse: str | None = None) -> tuple[bytes, str]:
    """(tar.gz, Dateiname). Das Ergebnis der Vorschau gilt nur mit ihrem Merker (``reuse``, kommt
    von der Seite, wenn genau diese Vorschau angezeigt wird), mit gleichen Schaltern, gleicher
    Aufzeichnung und höchstens REUSE_SECONDS alt – sonst wird neu gebaut."""
    options = options or {}
    arrived = time.monotonic()
    with _lock:
        key = _key(cfg, options)
        if _last and _last.get("key") == key and (
                _last.get("t", 0.0) >= arrived
                or (reuse and reuse == _last.get("token")
                    and time.monotonic() - _last.get("t", 0.0) < REUSE_SECONDS)):
            return _last["bundle"], _last.get("filename") or filename_for()
        result = _produce(cfg, options)
        return result["bundle"], result["preview"].get("filename") or filename_for()


def _worker_main() -> int:
    import base64
    import sys
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    try:
        job = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        result = _package(job)
        out = {"ok": True, "preview": result["preview"],
               "bundle": base64.b64encode(result["bundle"]).decode("ascii")}
    except LeakError as exc:
        out = {"ok": False, "findings": exc.findings}
    except Exception as exc:  # noqa: BLE001 – Fehler als JSON an den Server
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--worker"]:
        raise SystemExit(_worker_main())
