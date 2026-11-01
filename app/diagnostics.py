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
RECORDING_CAP = 4 * 1024 * 1024
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
    return [_without_key_name(row) for row in rows]


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
    return {"values": values, "herkunft": sources}


def _stats(values: list[float]) -> dict | None:
    nums = sorted(v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not nums:
        return None
    absolute = sorted(abs(v) for v in nums)
    p95 = absolute[min(len(absolute) - 1, int(round(0.95 * (len(absolute) - 1))))]
    return {"n": len(nums), "min": nums[0], "max": nums[-1], "mean": sum(nums) / len(nums),
            "p95_abs": p95, "last": values[-1] if isinstance(values[-1], (int, float)) else None}


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
    for key in ("offset", "rms", "freq", "skew", "root_delay", "root_dispersion", "stratum", "clients"):
        stats = _stats([s.get(key) for s in samples])
        if stats:
            out["metrics"][key] = stats
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


def _known_names(cfg: dict) -> list[str]:
    """Eigene Host- und Domainnamen: Rechner, NTS, Quellen, Erzwingen-Liste, Zertifikat, bind_address."""
    names = set()
    try:
        names.add(socket.gethostname())
        names.add(socket.getfqdn())
    except OSError:
        pass
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
    }


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


def _build(cfg: dict, sections: list[str] | None, options: dict) -> tuple[dict, dict, dict]:
    options = dict(options or {})
    names = _sections(options, sections)
    raw = _collect(cfg or {}, names, options)
    sanitizer = egress.Sanitizer("diagnostics", _known_names(cfg or {}), _known_values(cfg or {}))
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
    findings = egress.backstop(rendered, sanitizer.backstop_known()) + egress.backstop_compact_json(compact)
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
    for finding in egress.backstop({"abschnitt": text.encode("utf-8")}, sanitizer.backstop_known()):
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
    content, _sanitizer, _cut = _build(cfg, sections, options or {})
    return content


def _report_with_labels(report: dict) -> dict:
    removed = report.get("removed", {})
    return {"removed": removed, "pseudonyms": report.get("pseudonyms", 0),
            "labels": {k: egress.CATEGORIES.get(k, k) for k in removed}}


def preview(cfg: dict, options: dict | None = None) -> dict:
    """Für GET /api/diagnostics/preview: genau das, was im Paket stünde."""
    options = options or {}
    content, sanitizer, truncated = _build(cfg, None, options)
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
    options = options or {}
    content, sanitizer, truncated = _build(cfg, None, options)
    report = sanitizer.report()
    generated = time.time()
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
                               sanitizer.backstop_known())
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


_lock = threading.Lock()  # nie zwei Pakete gleichzeitig bauen (CPU auf dem Pi schonen)


def preview_locked(cfg: dict, options: dict | None = None) -> dict:
    with _lock:
        return preview(cfg, options)


def bundle_locked(cfg: dict, options: dict | None = None) -> bytes:
    with _lock:
        return bundle(cfg, options)
