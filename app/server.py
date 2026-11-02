"""HTTP-Server für Dashboard und API – nur Python-Standardbibliothek.

Lesend: Status, Verlauf, Konfiguration, Geräte, Metriken.
Schreibend (POST): Einstellungen, Passwort, Neustart der Zeitdienste.
Versionierte API: /api/v1/<pfad> ist ein Alias der bisherigen Pfade (apiv1.py).

Schutz der schreibenden Routen:
  * ist ein Zugang gesetzt (Env oder Dashboard), gilt Basic-Auth für alles
    außer /healthz – oder ein API-Schlüssel („Authorization: Bearer ntpg_…“)
    mit dem Recht, das apiv1.required_scope() für den Pfad verlangt;
  * ein mitgeschickter API-Schlüssel gilt immer mit seinem Recht, auch wenn
    kein Passwort gesetzt ist – ein „read“-Schlüssel kann nie schreiben;
  * WEB_READONLY=true sperrt alle Änderungen;
  * gegen Cross-Site-Requests (Browser mit Basic-Auth): nur JSON, Pflicht-Header
    X-NTP-GUI, und ein mitgeschickter Origin muss zum Host passen. Mit
    API-Schlüssel entfällt X-NTP-GUI – den Schlüssel schickt kein Browser von
    sich aus mit;
  * gegen DNS-Rebinding (eine fremde Webseite lässt ihren Namen auf die
    LAN-Adresse zeigen und liest dann Log, Status und Position): ohne Passwort
    werden nur Anfragen an IP-Adressen, localhost, den eigenen Hostnamen,
    lokale Namen (*.local, *.lan, *.home.arpa, *.internal …), den
    NTS-Namen und WEB_ALLOWED_HOSTS beantwortet (host_allowed). Mit Passwort
    schützt die Anmeldung, dann gilt jeder Name. /healthz ist immer offen.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import signal
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import apikeys
import apiv1
import autocal
import chrony
import clientmon
import devices
import diagnostics
import enforce
import events
import gps
import hardware
import history as historymod
import insights
import instance
import notify
import providers
import ptp
import settings
import statewatch

STATIC_DIR = Path(__file__).with_name("static")
CHRONY_CONF = os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")
PTP4L_CONF = os.environ.get("PTP4L_CONF", "/etc/linuxptp/ptp4l.conf")
RUN_DIR = os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")
START_TIME = time.time()
MAX_BODY = 64 * 1024
VERSION = os.environ.get("NTPGUI_VERSION", "1.3.2")
EVENTS_INTERVAL = 5.0          # so oft liest der Server die Supervisor-Ereignisse ein
CALIBRATION_DEFAULT_WINDOW = 86400.0  # /api/gps/calibration ohne window: letzte 24 h



def env_number(name: str, default, kind=float, minimum=None):
    """Zahl aus der Umgebung, die den Container nie abstürzen lässt.

    Ein Tippfehler in der Compose-Datei darf keine Neustartschleife auslösen:
    ein unbrauchbarer Wert fällt auf den Standard zurück.
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = kind(str(raw).strip())
    except (TypeError, ValueError):
        print(f"[web] {name}={raw!r} ist keine Zahl – verwende {default}", flush=True)
        return default
    if minimum is not None and value < minimum:
        print(f"[web] {name}={value} ist zu klein – verwende {minimum}", flush=True)
        return minimum
    return value


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# 24 h bei 10 s Abstand. Komprimiert gesichert sind das wenige MB.
HISTORY_SIZE = env_number("HISTORY_SIZE", 8640, int, minimum=2)
HISTORY = historymod.History(HISTORY_SIZE, os.path.join(settings.DATA_DIR, "history.json.gz"))

# Endpunkte von 1.3, die auch unter /api/v1 erreichbar sind (Recht je Endpunkt).
apiv1.endpoint("GET", "/logs", "/api/logs", "read",
               "Die letzten Zeilen des Container-Logs (lokal, ungefiltert).",
               ["available", "file", "total", "truncated", "lines"],
               {"lines": "Anzahl (1–5000, Standard 500)", "q": "Text, der vorkommen muss",
                "level": "warn oder crit: nur Warnungen/Fehler"})
apiv1.endpoint("GET", "/diagnostics/preview", "/api/diagnostics/preview", "read",
               "Vorschau des Diagnosepakets – genau das, was beim Herunterladen drinstünde, gefiltert.",
               ["ok", "generated", "filename", "sections", "removed", "content", "reuse"],
               {"clients": "1 = Client-Liste einschließen (pseudonymisiert)",
                "recording": "1 = letzte Aufzeichnung einschließen (gefiltert)"})
apiv1.endpoint("GET", "/diagnostics/bundle", "/api/diagnostics/bundle", "read",
               "Diagnosepaket als tar.gz (gefiltert, mit MANIFEST.txt). Wird nie hochgeladen.", [],
               {"clients": "wie bei der Vorschau", "recording": "wie bei der Vorschau",
                "reuse": "Merker „reuse“ einer Vorschau: genau dieses Paket sofort (gleiche Schalter, "
                         "höchstens 10 min alt, Aufzeichnung unverändert); sonst neu gebaut"})
apiv1.endpoint("GET", "/recording", "/api/recording", "read",
               "Zustand der Aufzeichnung der Datenquellen.", ["active", "ends", "entries", "size", "available"])
apiv1.endpoint("POST", "/recording", "/api/recording", "admin",
               "Aufzeichnung starten ({\"seconds\": 300}) oder beenden ({\"action\": \"stop\"}).",
               ["active", "ends", "entries", "size", "available"])
apiv1.endpoint("GET", "/enforce/snippets", "/api/enforce/snippets", "read",
               "Anleitungen, um Zeitserver per DNS oder Firewall auf diesen Server umzuleiten.",
               ["server_ip", "systems", "hostnames", "snippets"],
               {"system": "adguard, pihole, dnsmasq, unbound, opnsense, mikrotik, openwrt, nftables, unifi oder all",
                "ip": "Adresse dieses Servers aus Sicht der Clients"})
apiv1.endpoint("GET", "/enforce/check", "/api/enforce/check", "read",
               "Prüft, ob die Umleitung wirkt (höchstens alle 30 s).", ["level", "summary", "hosts"],
               {"ip": "Adresse dieses Servers aus Sicht der Clients"})
apiv1.endpoint("GET", "/clients/offsets", "/api/clients/offsets", "read",
               "Passiv gemessene Abweichung der Client-Uhren.", ["available", "running", "reason", "clients"])
apiv1.endpoint("GET", "/notify", "/api/notify", "admin",
               "Benachrichtigungen: Kanäle mit Filtern und Zustellstand. Tokens nur als „gesetzt“ "
               "(secret_set), nie im Klartext.", ["channels", "types", "levels", "kinds", "defaults", "limits",
                                                 "dashboard_url", "running"])
apiv1.endpoint("GET", "/notify/status", "/api/notify/status", "read",
               "Zustellstand je Benachrichtigungskanal (Name, Art, zuletzt gesendet, letzter Fehler) – "
               "ohne Adressen und Tokens.", ["channels", "running"])
apiv1.endpoint("POST", "/notify/channels", "/api/notify/channels", "admin",
               "Benachrichtigungskanal anlegen (ohne id) oder ändern (mit id). Body: name, type "
               "(webhook|ntfy|gotify|apprise), url, topic, secret (weglassen = behalten, \"\" = löschen), "
               "min_level, kinds, debounce_min, rate_per_hour, resolved, enabled.", ["channel"])
apiv1.endpoint("POST", "/notify/channels/delete", "/api/notify/channels/delete", "admin",
               "Benachrichtigungskanal löschen. Body: {\"id\": …}.", ["ok"])
apiv1.endpoint("POST", "/notify/test", "/api/notify/test", "admin",
               "Testnachricht sofort über einen Kanal senden (ohne Wiederholung). Body: {\"id\": …}.",
               ["ok", "error", "status"])
apiv1.endpoint("GET", "/gps/autocal", "/api/gps/autocal", "read",
               "Automatische GPS-Kalibrierung: Modus, aktuelle Entscheidung, letzte Änderungen.",
               ["mode", "decision", "changes", "rollback"], {"fresh": "0 = letzte gespeicherte Entscheidung"})
apiv1.endpoint("POST", "/gps/autocal/rollback", "/api/gps/autocal/rollback", "admin",
               "Letzte automatische Änderung(en) zurücknehmen. Body: {\"steps\": 1}.",
               ["ok", "restored_offset", "restored_delay", "reload_triggered", "change"])

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}


# ---------------------------------------------------------------------------
# Datensammlung
# ---------------------------------------------------------------------------

def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def collect_sample() -> dict:
    tracking = chrony.tracking()
    stats = chrony.serverstats()
    sample: dict = {
        "t": int(time.time()),
        "offset": tracking.get("system_time_offset"),
        "rms": tracking.get("rms_offset"),
        "freq": tracking.get("frequency_ppm"),
        "skew": tracking.get("skew_ppm"),
        "root_delay": tracking.get("root_delay"),
        "root_dispersion": tracking.get("root_dispersion"),
        "stratum": tracking.get("stratum"),
        "served": stats.get("ntp_packets_received"),
        "clients": len(chrony.clients()),
        "sources": {},
    }
    for source in chrony.merged_sources():
        name = source.get("name")
        if name:
            sample["sources"][name] = {"o": source.get("offset"), "s": source.get("state"),
                                       "k": source.get("mode"), "j": source.get("std_dev")}
    if gps.enabled():
        g = gps.status()
        sample["gps"] = {"used": _num(g.get("satellites_used")), "seen": _num(g.get("satellites_seen")),
                         "hdop": _num(g.get("hdop")), "snr": _num(g.get("snr_avg")),
                         "mode": _num(g.get("mode"))}
    if ptp.enabled():
        p = ptp.status()
        metrics = p.get("log_metrics") or {}
        sample["ptp"] = {
            "offset_ns": _num(p.get("offset_ns")),
            "delay_ns": _num(p.get("meanPathDelay")) or _num(metrics.get("path_delay_ns")),
            "freq_ppb": _num(metrics.get("freq_ppb")),
            "rms_ns": _num(metrics.get("rms_ns")),
        }
    return sample


# Erkennt Quellenwechsel, GPS-Fix verloren/wieder da und PPS-Ausfälle → Ereignisprotokoll.
STATE_WATCH = statewatch.StateWatcher(events.emit)


def collector() -> None:
    restored = HISTORY.load()
    if restored:
        print(f"[web] Verlauf wiederhergestellt: {restored} Messpunkte", flush=True)
    while True:
        try:
            sample = collect_sample()
            HISTORY.add(sample)
            HISTORY.save()
            STATE_WATCH.sample(sample)
            autocal.maybe_tick()   # höchstens einmal pro Stunde, wirft nie
        except Exception as exc:  # ein Messfehler darf den Thread nie beenden
            print(f"[web] Messung fehlgeschlagen: {exc}", flush=True)
        try:
            # Als PTP-Grandmaster die angekündigte Uhrqualität an den Zustand von chrony anpassen.
            ptp.update_grandmaster(settings.values(), chrony.tracking(), chrony.detailed_sources())
        except Exception as exc:
            print(f"[web] Grandmaster-Daten nicht gesetzt: {exc}", flush=True)
        try:
            interval = float(settings.values()["history_interval"])
        except Exception:
            interval = 10.0
        time.sleep(max(2.0, interval))


HARDWARE_FIRST_DELAY = 5.0
HARDWARE_INTERVAL = 300.0


def hardware_refresher(stop: threading.Event | None = None) -> None:
    """Erzeugt den Hardware-Bericht im Hintergrund, damit Hinweise und Metriken
    Daten haben, ohne dass eine Anfrage auf die PPS-Probe (≈ 1 s) wartet."""
    stop = stop or threading.Event()
    if stop.wait(HARDWARE_FIRST_DELAY):
        return
    while True:
        try:
            STATE_WATCH.hardware(hardware.report(settings.values(), refresh=True))
        except Exception as exc:  # die Prüfung darf das Dashboard nie stören
            print(f"[web] Hardware-Prüfung fehlgeschlagen: {exc}", flush=True)
        if stop.wait(HARDWARE_INTERVAL):
            return


def events_ingester(stop: threading.Event | None = None, interval: float = EVENTS_INTERVAL) -> None:
    """Übernimmt die Ereignisse des Supervisors (RUN_DIR/events.jsonl) ins Protokoll."""
    stop = stop or threading.Event()
    path = os.path.join(RUN_DIR, "events.jsonl")
    while True:
        try:
            events.ingest_supervisor(path)
        except Exception as exc:  # nie den Thread verlieren
            print(f"[web] Ereignisse des Supervisors nicht gelesen: {exc}", flush=True)
        if stop.wait(interval):
            return


def recording_status() -> dict:
    """Zustand der Aufzeichnung für die Diagnose-Seite – ohne vollen Dateipfad."""
    raw = providers.status()
    out = {key: raw.get(key) for key in ("active", "until", "started", "bytes", "entries", "stopped",
                                         "reason", "max_seconds", "max_bytes", "replay")}
    path = raw.get("path")
    out["file"] = os.path.basename(path) if path else None
    out["available"] = bool(path and os.path.isfile(path))
    out["ends"] = raw.get("until")     # Namen, die pages/diagnose.js liest
    out["size"] = raw.get("bytes")
    return out


def clock_control() -> dict:
    """Läuft chronyd mit -x? Liest die Kommandozeile aus /proc."""
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/comm", encoding="utf-8") as handle:
                if handle.read().strip() != "chronyd":
                    continue
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                args = handle.read().split(b"\0")
        except OSError:
            continue
        return {"clock_control": b"-x" not in args, "chronyd_pid": int(entry)}
    return {"clock_control": None, "chronyd_pid": None}


def system_info(cfg: dict) -> dict:
    info = {
        "hostname": socket.gethostname(),
        "time": time.time(),
        "timezone": time.strftime("%Z"),
        "uptime_seconds": int(time.time() - START_TIME),
        "title": cfg["web_title"],
        "refresh_seconds": cfg["web_refresh_seconds"],
        "ntp_port": cfg["ntp_port"],
        "version": VERSION,
        "addresses": [],
    }
    info.update(clock_control())
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            info["host_uptime_seconds"] = int(float(handle.read().split()[0]))
    except OSError:
        pass
    try:
        for _family, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None):
            if sockaddr[0] not in info["addresses"]:
                info["addresses"].append(sockaddr[0])
    except socket.gaierror:
        pass
    return info


def reload_status() -> dict:
    try:
        with open(os.path.join(RUN_DIR, "reload.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"state": "unknown"}


SERVICE_LABELS = {"chronyd": "chronyd (NTP)", "gpsd": "gpsd (GPS)", "ptp4l": "ptp4l (PTP)",
                  "phc2sys": "phc2sys (PTP-Uhr ↔ Systemuhr)", "web": "Dashboard"}
SERVICE_STATES = {"running", "restarting", "failed", "stopped"}


def services_status() -> dict:
    """Zustand der Dienste aus RUN_DIR/services.json (schreibt der Supervisor).

    Fehlt die Datei oder ist sie kaputt (z. B. Dashboard ohne Supervisor
    gestartet), gibt es ein leeres Ergebnis – das Dashboard läuft trotzdem.
    """
    try:
        with open(os.path.join(RUN_DIR, "services.json"), encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}
    entries = raw.get("services") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}
    out: dict = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        state = entry.get("state")
        restarts = entry.get("restarts")
        out[str(name)] = {
            "state": state if state in SERVICE_STATES else "unknown",
            "restarts": restarts if isinstance(restarts, int) and not isinstance(restarts, bool) else 0,
            "last_exit": entry.get("last_exit") if isinstance(entry.get("last_exit"), int) else None,
            "since": entry.get("since") if isinstance(entry.get("since"), (int, float)) else None,
            "pid": entry.get("pid") if isinstance(entry.get("pid"), int) else None,
            "optional": entry.get("optional") is True,
            "next_retry": entry.get("next_retry") if isinstance(entry.get("next_retry"), (int, float)) else None,
            "message": str(entry.get("message") or ""),
            "label": SERVICE_LABELS.get(str(name), str(name)),
        }
    return out


# Hinweis-Schlüssel → Schlüssel, deren Anwesenheit ihn überflüssig macht (gleiche
# Ursache, schon ausführlicher gemeldet). Explizit statt Textvergleich.
INSIGHT_SUPPRESSED_BY = {
    # Läuft gpsd nicht, meldet "gpsd antwortet nicht" das Problem bereits; der
    # Hardware-Hinweis zum Empfänger wäre ein zweiter Eintrag für dieselbe Ursache.
    "hw_gps_usb": {"gpsd_down"},
}


def combine_insights(*lists: list[dict]) -> list[dict]:
    """Hinweislisten zusammenführen: doppelte Schlüssel und unterdrückte Hinweise
    (INSIGHT_SUPPRESSED_BY) entfernen, Reihenfolge beibehalten."""
    merged = [item for items in lists for item in items]
    keys = {item.get("key") for item in merged}
    out, seen = [], set()
    for item in merged:
        key = item.get("key")
        if (key is not None and key in seen) or INSIGHT_SUPPRESSED_BY.get(key, set()) & keys:
            continue
        seen.add(key)
        out.append(item)
    return out


def service_insights(services: dict, now: float | None = None) -> list[dict]:
    """Hinweise zu ausgefallenen Diensten (nur die optionalen startet der Supervisor neu)."""
    now = time.time() if now is None else now
    out: list[dict] = []
    for name, svc in services.items():
        label = svc.get("label") or name
        note = f" Letzte Meldung: {svc['message']}" if svc.get("message") else ""
        exit_text = f" (Exit-Code {svc['last_exit']})" if svc.get("last_exit") is not None else ""
        if svc.get("state") == "restarting":
            attempt = (svc.get("restarts") or 0) + 1  # restarts = bisherige Neustarts, dieser ist der nächste
            retry = svc.get("next_retry")
            wait = f" Nächster Versuch in etwa {max(0, int(retry - now))} s." if isinstance(retry, (int, float)) else ""
            out.append({
                "level": "warn", "key": f"service_{name}",
                "title": f"{label} ist ausgefallen und wird neu gestartet (Versuch {attempt})",
                "text": f"Der Dienst hat sich beendet{exit_text}. Der Supervisor startet ihn mit wachsender "
                        "Pause neu, damit ein dauerhaft fehlendes Gerät nicht den Container blockiert – "
                        f"die übrigen Zeitdienste laufen weiter.{wait or note} Häufige Ursache: das Gerät "
                        "(GPS-Empfänger, Netzwerkkarte) ist abgesteckt oder im Container nicht freigegeben.",
                "action": "hardware",
            })
        elif svc.get("state") == "failed":
            out.append({
                "level": "crit", "key": f"service_{name}",
                "title": f"{label} läuft nicht",
                "text": f"Der Dienst ist eingeschaltet, läuft aber nicht{exit_text}.{note} Fehlt ein Gerät, "
                        "startet der Supervisor den Dienst von selbst, sobald es wieder auftaucht (Prüfung "
                        "alle 30 s). Prüfe auf der Hardware-Seite, ob das Gerät im Container sichtbar ist; "
                        "nach dem Speichern der Einstellungen startet der Supervisor die Dienste neu.",
                "action": "hardware",
            })
    return out


def trigger_reload() -> bool:
    """Bittet den Supervisor per SIGHUP, die Zeitdienste neu zu starten."""
    try:
        with open(os.path.join(RUN_DIR, "supervisor.pid"), encoding="utf-8") as handle:
            pid = int(handle.read().strip())
        os.kill(pid, signal.SIGHUP)
        return True
    except (OSError, ValueError):
        return False


def auth_info() -> dict:
    if os.environ.get("WEB_USER") and os.environ.get("WEB_PASSWORD"):
        return {"enabled": True, "source": "env", "user": os.environ["WEB_USER"]}
    stored = settings.stored_credentials()
    if stored:
        return {"enabled": True, "source": "gui", "user": stored["user"]}
    return {"enabled": False, "source": None, "user": None}


def build_status() -> dict:
    cfg = settings.values()
    tracking = chrony.tracking()
    clients = chrony.clients()
    status = {
        "system": system_info(cfg),
        "tracking": tracking,
        "sources": chrony.detailed_sources(),
        "activity": chrony.activity(),
        "serverstats": chrony.serverstats(),
        "clients": clients,
        "client_count": len(clients),
        "ptp": ptp.status(),
        "gps": gps.status(),
        "nts_server": chrony.nts_server_status(cfg),
        "services": services_status(),
        "chrony_running": bool(tracking),
        "config": {key: cfg[key] for key in (
            "gps_enable", "gps_device", "gps_offset", "gps_delay", "gps_select", "gps_refid",
            "gps_pps_device", "ptp_enable", "ptp_interface", "ptp_mode", "ptp_time_stamping",
            "ntp_minsources", "serve_unsynced", "allow_networks", "ntp_port", "phc2sys_enable",
            "phc_refclock")},
        "ui": {
            "readonly": env_flag("WEB_READONLY"),
            "auth": auth_info(),
            "storage": settings.storage_info(),
            "reload": reload_status(),
        },
    }
    status["insights"] = combine_insights(insights.build(status, cfg),
                                          service_insights(status["services"]),
                                          hardware.cached_insights(cfg))
    return status


# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------

def _metric(lines: list[str], name: str, value, help_text: str, kind: str = "gauge", labels: str = "") -> None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    if not any(line.startswith(f"# TYPE {name} ") for line in lines):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
    lines.append(f"{name}{labels} {value}")


def _escape_label(value) -> str:
    """Prometheus label values escape backslash, quote and newline."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def build_metrics() -> str:
    tracking = chrony.tracking()
    lines: list[str] = []
    _metric(lines, "ntpgui_up", 1 if tracking else 0, "1 when chronyd answers")
    _metric(lines, "ntpgui_stratum", tracking.get("stratum"), "Stratum reported by chronyd")
    _metric(lines, "ntpgui_system_time_offset_seconds", tracking.get("system_time_offset"), "System clock offset")
    _metric(lines, "ntpgui_last_offset_seconds", tracking.get("last_offset"), "Last measured offset")
    _metric(lines, "ntpgui_rms_offset_seconds", tracking.get("rms_offset"), "Long term RMS offset")
    _metric(lines, "ntpgui_frequency_ppm", tracking.get("frequency_ppm"), "Clock frequency error")
    _metric(lines, "ntpgui_skew_ppm", tracking.get("skew_ppm"), "Estimated frequency error bound")
    _metric(lines, "ntpgui_root_delay_seconds", tracking.get("root_delay"), "Root delay")
    _metric(lines, "ntpgui_root_dispersion_seconds", tracking.get("root_dispersion"), "Root dispersion")
    _metric(lines, "ntpgui_synchronised", 1 if tracking.get("synchronised") else 0, "1 when the clock is synchronised")

    for source in chrony.detailed_sources():
        labels = '{source="%s",mode="%s"}' % (
            _escape_label(source.get("name", "")), _escape_label(source.get("mode_label", "")))
        _metric(lines, "ntpgui_source_offset_seconds", source.get("offset"), "Offset per source", labels=labels)
        _metric(lines, "ntpgui_source_stratum", source.get("stratum"), "Stratum per source", labels=labels)
        _metric(lines, "ntpgui_source_reach_percent", source.get("reach_percent"), "Reachability per source", labels=labels)
        _metric(lines, "ntpgui_source_jitter_seconds", source.get("std_dev"), "Standard deviation per source", labels=labels)
        _metric(lines, "ntpgui_source_selected", 1 if source.get("state") == "*" else 0, "1 for the selected source", labels=labels)
        _metric(lines, "ntpgui_source_combined", 1 if source.get("state") in {"*", "+"} else 0, "1 when the source is used", labels=labels)
        _metric(lines, "ntpgui_source_authenticated", 1 if source.get("authenticated") else 0, "1 when NTS-authenticated", labels=labels)

    stats = chrony.serverstats()
    _metric(lines, "ntpgui_ntp_packets_received_total", stats.get("ntp_packets_received"), "NTP packets served", kind="counter")
    _metric(lines, "ntpgui_ntp_packets_dropped_total", stats.get("ntp_packets_dropped"), "NTP packets dropped", kind="counter")
    _metric(lines, "ntpgui_nts_ke_connections_accepted_total", stats.get("nts_ke_connections_accepted"), "NTS-KE connections accepted", kind="counter")
    _metric(lines, "ntpgui_clients", len(chrony.clients()), "Known NTP clients")

    gps_state = gps.status()
    if gps_state.get("enabled"):
        _metric(lines, "ntpgui_gps_running", 1 if gps_state.get("running") else 0, "1 when gpsd answers")
        _metric(lines, "ntpgui_gps_fix_mode", gps_state.get("mode"), "gpsd fix mode (0-3)")
        _metric(lines, "ntpgui_gps_satellites_used", gps_state.get("satellites_used"), "Satellites used for the fix")
        _metric(lines, "ntpgui_gps_satellites_seen", gps_state.get("satellites_seen"), "Satellites in view")
        _metric(lines, "ntpgui_gps_hdop", gps_state.get("hdop"), "Horizontal dilution of precision")
        _metric(lines, "ntpgui_gps_snr_avg_db", gps_state.get("snr_avg"), "Average SNR of used satellites")

    ptp_state = ptp.status()
    if ptp_state.get("enabled"):
        _metric(lines, "ntpgui_ptp_running", 1 if ptp_state.get("running") else 0, "1 when ptp4l answers")
        offset = ptp_state.get("offset_ns")
        delay = ptp_state.get("meanPathDelay")
        _metric(lines, "ntpgui_ptp_offset_seconds", offset / 1e9 if isinstance(offset, (int, float)) else None, "PTP offset from master")
        _metric(lines, "ntpgui_ptp_mean_path_delay_seconds", delay / 1e9 if isinstance(delay, (int, float)) else None, "PTP mean path delay")
        _metric(lines, "ntpgui_ptp_steps_removed", ptp_state.get("stepsRemoved"), "Steps removed from the grandmaster")

    for name, svc in services_status().items():
        labels = '{service="%s"}' % _escape_label(name)
        _metric(lines, "ntpgui_service_up", 1 if svc["state"] == "running" else 0,
                "1 when the supervised service is running", labels=labels)
        _metric(lines, "ntpgui_service_restarts_total", svc["restarts"],
                "Restarts of the service by the supervisor", kind="counter", labels=labels)

    nts = chrony.nts_server_status(settings.values(), stats)
    if nts.get("enabled"):
        _metric(lines, "ntpgui_nts_server_cert_days_left", nts.get("days_left"),
                "Days until the NTS server certificate expires")

    _hardware_metrics(lines)
    return "\n".join(lines) + "\n"


def _hardware_metrics(lines: list[str]) -> None:
    """Nur aus dem zwischengespeicherten Hardware-Bericht – /metrics wartet nie auf PPS-Proben."""
    getter = getattr(hardware, "cached_report", None)
    try:
        rep = getter() if callable(getter) else getattr(hardware, "_REPORT", None)
    except Exception:  # Bericht kaputt → Metriken ohne Hardwareteil
        return
    if not isinstance(rep, dict):
        return
    for pps in rep.get("pps") or []:
        if isinstance(pps, dict) and pps.get("dev"):
            _metric(lines, "ntpgui_pps_live", 1 if pps.get("state") == "live" else 0,
                    "1 when pulses arrive on the PPS device", labels='{device="%s"}' % _escape_label(pps["dev"]))
    for row in rep.get("matrix") or []:
        if isinstance(row, dict) and row.get("key") and row.get("status"):
            labels = '{key="%s",status="%s"}' % (_escape_label(row["key"]), _escape_label(row["status"]))
            _metric(lines, "ntpgui_hardware_capability", 1, "Result of the hardware check per capability",
                    labels=labels)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class AuthCache:
    """PBKDF2 kostet auf einem Pi spürbar Zeit – geprüfte Zugänge kurz merken."""

    def __init__(self) -> None:
        self._ok: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, header: str, verify) -> bool:
        key = hashlib.sha256(header.encode()).hexdigest()
        now = time.time()
        with self._lock:
            if self._ok.get(key, 0) > now:
                return True
        if verify():
            with self._lock:
                self._ok = {k: v for k, v in self._ok.items() if v > now}
                self._ok[key] = now + 300
            return True
        return False

    def clear(self) -> None:
        with self._lock:
            self._ok.clear()


AUTH_CACHE = AuthCache()


# --- Schutz vor DNS-Rebinding -------------------------------------------------

# Namen, die keine fremde Webseite für sich auf eine LAN-Adresse zeigen lassen
# kann: reservierte bzw. nie öffentlich vergebene Endungen. Bewusst NICHT dabei:
# ".fritz.box" – ".box" ist eine echte, öffentlich vergebene Endung (fritz.box war
# schon fremd registriert). Wer das Dashboard über name.fritz.box öffnet, trägt
# WEB_ALLOWED_HOSTS=*.fritz.box ein oder setzt ein Passwort.
LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".lan", ".home.arpa", ".internal", ".home", ".corp",
                       ".localdomain", ".intranet", ".private", ".speedport.ip")
_REJECTED_HOSTS: set[str] = set()
_REJECTED_LOCK = threading.Lock()


def _host_name(header: str) -> str:
    """Host-Header → Name ohne Port, klein, ohne Schlusspunkt ('[::1]:80' → '::1')."""
    host = (header or "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def safe_host_for_log(host: str) -> str:
    """Host-Header für Log und Fehlermeldung: nur [a-z0-9.-:], Labels ≤ 63 Zeichen, sonst „<ungültig>“.

    Der Wert kommt ungeprüft von außen; ein überlanger oder seltsamer Name im Log würde sonst
    später das Diagnosepaket stören (Schlussprüfung).
    """
    host = (host or "").strip().lower()
    if not host or len(host) > 253 or not re.fullmatch(r"[a-z0-9.:-]+", host):
        return "<ungültig>"
    if any(len(label) > 63 for label in host.split(".")):
        return "<ungültig>"
    return host


def _env_allowed_hosts() -> list[str]:
    return [h.strip().lower().rstrip(".") for h in os.environ.get("WEB_ALLOWED_HOSTS", "").split(",")
            if h.strip()]


def host_allowed(header: str | None, nts_name: str = "") -> bool:
    """Darf eine Anfrage mit diesem Host-Header ohne Anmeldung beantwortet werden?"""
    if header is None or not header.strip():
        return True  # HTTP/1.0 ohne Host – das schickt kein Browser
    host = _host_name(header)
    allowed = _env_allowed_hosts()
    if "*" in allowed:
        return True
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        pass
    if not host or "." not in host:
        return True  # einteilige Namen (raspberrypi, localhost) löst kein öffentliches DNS auf
    if host.endswith(LOCAL_HOST_SUFFIXES):
        return True
    own = set()
    try:
        own = {socket.gethostname().lower().rstrip("."), socket.getfqdn().lower().rstrip(".")}
    except OSError:
        pass
    if host in own:
        return True
    if nts_name and host == str(nts_name).strip().lower().rstrip("."):
        return True
    for entry in allowed:
        if entry.startswith("*.") and (host.endswith(entry[1:]) or host == entry[2:]):
            return True
        if host == entry:
            return True
    return False


def host_rejection_text(host: str) -> str:
    return (f"Zugriff über den Namen „{host}“ abgelehnt. Ohne Passwort beantwortet ntp-gui nur Anfragen "
            "an IP-Adressen, localhost, den eigenen Hostnamen, einteilige Namen und lokale Namen (*.local, "
            "*.lan, *.home.arpa, *.internal). Das schützt vor DNS-Rebinding: Sonst könnte jede "
            "Webseite, die du besuchst, über einen eigenen Namen Log, Status und Position aus deinem "
            "Netz lesen. Abhilfe: den Namen in WEB_ALLOWED_HOSTS eintragen (z. B. "
            f"WEB_ALLOWED_HOSTS={host}, mehrere mit Komma, „*.example.org“ für alle Unternamen) oder "
            "im Dashboard bzw. per WEB_USER/WEB_PASSWORD ein Passwort setzen – dann gilt jeder Name.")


class Handler(BaseHTTPRequestHandler):
    server_version = "ntp-gui"
    protocol_version = "HTTP/1.1"

    # --- Helfer --------------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:
        if env_flag("WEB_ACCESS_LOG"):
            super().log_message(fmt, *args)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str, extra_headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload, status: HTTPStatus = HTTPStatus.OK, extra: dict | None = None) -> None:
        body = json.dumps(payload, default=str).encode()
        headers = {"Cache-Control": "no-store"}
        headers.update(extra or {})
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _error(self, status: HTTPStatus, message: str, **extra) -> None:
        self._send_json({"error": message, **extra}, status)

    def _identity(self) -> dict | None:
        """Wer fragt? {"kind": "open"|"basic"|"key", "scope"?} oder None (abgelehnt).

        Ein API-Schlüssel gilt immer mit seinem Recht – auch ohne gesetztes
        Passwort. Sonst: ohne Passwort ist alles offen, mit Passwort Basic-Auth.
        """
        header = self.headers.get("Authorization", "")
        if header[:7].lower() == "bearer ":
            key = apikeys.verify(header[7:].strip())
            return {"kind": "key", "scope": key["scope"], "id": key["id"]} if key else None
        if not auth_info()["enabled"]:
            return {"kind": "open"}
        return {"kind": "basic"} if self._authorised() else None

    def _host_ok(self, ident: dict) -> bool:
        """DNS-Rebinding: ohne Anmeldung nur bekannte/lokale Namen. Antwortet selbst mit 403."""
        if ident.get("kind") != "open":
            return True  # Passwort oder API-Schlüssel schützen
        header = self.headers.get("Host")
        try:
            nts_name = str(settings.values().get("nts_server_name") or "")
        except Exception:
            nts_name = ""
        if host_allowed(header, nts_name):
            return True
        host = safe_host_for_log(_host_name(header or ""))
        with _REJECTED_LOCK:
            first = host not in _REJECTED_HOSTS and len(_REJECTED_HOSTS) < 1000
            if first:
                _REJECTED_HOSTS.add(host)
        if first:
            print(f"[web] Anfrage für unbekannten Host-Namen „{host}“ abgelehnt (Schutz vor DNS-Rebinding) – "
                  "erlauben mit WEB_ALLOWED_HOSTS oder ein Passwort setzen.", flush=True)
        text = host_rejection_text(host)
        self.close_connection = True  # ein evtl. POST-Body bleibt ungelesen
        path = urlparse(self.path).path
        if path.startswith("/api") or path == "/metrics" or "json" in self.headers.get("Accept", ""):
            self._error(HTTPStatus.FORBIDDEN, text, reason="host_not_allowed")
        else:
            body = ("<!doctype html><html lang=\"de\"><meta charset=\"utf-8\"><title>Zugriff abgelehnt</title>"
                    "<body style=\"font-family:sans-serif;max-width:42em;margin:2em auto;padding:0 1em\">"
                    f"<h1>Zugriff abgelehnt</h1><p>{html.escape(text)}</p></body></html>\n")
            self._send(HTTPStatus.FORBIDDEN, body.encode("utf-8"), "text/html; charset=utf-8",
                       {"Cache-Control": "no-store"})
        return False

    def _scope_ok(self, ident: dict, method: str, path: str) -> bool:
        """Darf diese Identität die Methode auf dem Pfad nutzen (apiv1.required_scope)?"""
        if ident["kind"] != "key":
            return True
        needed = apiv1.required_scope(method, path)
        if needed == "session":
            return False  # Zugang und Schlüssel nur mit Benutzer/Passwort verwalten
        if needed == "admin" and ident["scope"] != "admin":
            return False
        return apikeys.allows(ident["scope"], method)

    def _deny_scope(self, ident: dict, method: str, path: str) -> None:
        needed = apiv1.required_scope(method, path)
        if needed == "session":
            text = ("Das geht nur mit Benutzer und Passwort, nicht mit einem API-Schlüssel – "
                    "so kann ein entwendeter Schlüssel weder das Passwort ändern noch neue Schlüssel ausstellen.")
        else:
            text = (f"Dieser API-Schlüssel hat das Recht „{ident.get('scope')}“; hier ist "
                    f"„{needed}“ nötig.")
        self._error(HTTPStatus.FORBIDDEN, text, scope_required=needed)

    def _authorised(self) -> bool:
        info = auth_info()
        if not info["enabled"]:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        except Exception:
            return False
        user, _, password = decoded.partition(":")

        def verify() -> bool:
            if info["source"] == "env":
                ok_user = hmac.compare_digest(user.encode(), os.environ["WEB_USER"].encode())
                ok_pass = hmac.compare_digest(password.encode(), os.environ["WEB_PASSWORD"].encode())
                return ok_user & ok_pass
            stored = settings.stored_credentials()
            if not stored:
                return False
            return (hmac.compare_digest(user.encode(), stored["user"].encode())
                    & settings.verify_password(password, stored["hash"]))

        return AUTH_CACHE.check(header + "|" + str(info["source"]), verify)

    def _deny_auth(self) -> None:
        if self.headers.get("Authorization", "")[:7].lower() == "bearer ":
            # Kein Basic-Dialog im Browser für ein Skript mit falschem Schlüssel.
            self._send_json({"error": "API-Schlüssel ungültig oder widerrufen"}, HTTPStatus.UNAUTHORIZED,
                            {"WWW-Authenticate": 'Bearer realm="ntp-gui"'})
            return
        self._send(HTTPStatus.UNAUTHORIZED, b"authentication required\n", "text/plain; charset=utf-8",
                   {"WWW-Authenticate": 'Basic realm="ntp-gui", charset="UTF-8"'})

    @staticmethod
    def _api_path(raw: str) -> tuple[str, bool]:
        """Normalisiert den Pfad: /api/v1/<x> → bisheriger Pfad, /api/keys → /api/apikeys.

        Gibt (Pfad, ist_v1_index) zurück. Unbekannte /api/v1/-Pfade bleiben, wie sie
        sind (→ 404).
        """
        path = urlparse(raw).path.rstrip("/") or "/"
        if apiv1.is_index(path):
            return path, True
        legacy = apiv1.resolve(path)
        if legacy:
            path = legacy
        if path == "/api/keys" or path.startswith("/api/keys/"):
            path = "/api/apikeys" + path[len("/api/keys"):]
        return path, False

    def _serve_static(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        if not path.is_file() or STATIC_DIR.resolve() not in path.parents:
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            return
        content_type = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, path.read_bytes(), content_type, {"Cache-Control": "no-cache"})

    def _query(self) -> dict:
        return {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}

    # --- GET -----------------------------------------------------------------
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path, index = self._api_path(self.path)
        if path == "/healthz":
            healthy = bool(chrony.tracking())
            self._send_json({"status": "ok" if healthy else "degraded", "chrony": healthy},
                            HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE)
            return
        ident = self._identity()
        if ident is None:
            self._deny_auth()
            return
        if not self._host_ok(ident):
            return
        if not self._scope_ok(ident, "GET", path):
            self._deny_scope(ident, "GET", path)
            return
        try:
            if index:
                self._send_json(apiv1.describe())
            else:
                self._route_get(path)
        except BrokenPipeError:
            pass
        except Exception as exc:  # nie wegen eines Parserfehlers ausfallen
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _route_get(self, path: str) -> None:
        query = self._query()
        if path == "/":
            self._serve_static("index.html")
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path == "/api/status":
            self._send_json(build_status())
        elif path == "/api/history":
            seconds = env_like(query.get("range"), 3600.0)
            points = int(env_like(query.get("points"), 600))
            samples = HISTORY.query(seconds if seconds > 0 else None, max(10, min(points, 3000)))
            self._send_json({"samples": samples,
                             "interval": settings.values()["history_interval"]})
        elif path == "/api/config":
            files = []
            for name, file_path in (("chrony.conf", CHRONY_CONF), ("ptp4l.conf", PTP4L_CONF)):
                try:
                    files.append({"name": name, "path": file_path,
                                  "content": Path(file_path).read_text()})
                except OSError:
                    continue
            primary = files[0] if files else {"path": CHRONY_CONF, "content": f"# {CHRONY_CONF} nicht lesbar"}
            self._send_json({"path": primary["path"], "content": primary["content"], "files": files})
        elif path == "/api/settings":
            schema = settings.public_schema()
            schema["readonly"] = env_flag("WEB_READONLY")
            schema["auth"] = auth_info()
            schema["reload"] = reload_status()
            schema["schema_version"] = settings.SCHEMA_VERSION
            schema["notes"] = settings.migration_notes(include_seen=False)
            self._send_json(schema)
        elif path == "/api/settings/notes":
            self._send_json({"schema": settings.schema_version(), "notes": settings.migration_notes()})
        elif path == "/api/settings/export":
            body = json.dumps(settings.export_values(), indent=2, ensure_ascii=False).encode()
            self._send(HTTPStatus.OK, body, "application/json; charset=utf-8",
                       {"Content-Disposition": 'attachment; filename="ntp-gui-einstellungen.json"',
                        "Cache-Control": "no-store"})
        elif path == "/api/reload":
            self._send_json(reload_status())
        elif path == "/api/devices":
            self._send_json(devices.summary(settings.values()))
        elif path == "/api/hardware":
            refresh = query.get("refresh") in {"1", "true"}
            self._send_json(hardware.report(settings.values(), refresh=refresh))
        elif path == "/api/gps/calibration":
            cfg = settings.values()
            # Ohne window die letzten 24 h: über 30 Tage SQLite-Verlauf dauert es sonst Sekunden.
            window = env_like(query.get("window", query.get("seconds")), CALIBRATION_DEFAULT_WINDOW)
            since = time.time() - window if window > 0 else None
            self._send_json(historymod.calibrate(HISTORY.snapshot(since), cfg["gps_refid"],
                                                 float(cfg["gps_offset"]), float(cfg["gps_delay"])))
        elif path == "/api/gps/autocal":
            self._send_json(autocal.api_status(settings.values(), fresh=query.get("fresh") != "0"))
        elif path == "/api/events":
            limit = int(env_like(query.get("limit"), 500))
            since = env_like(query.get("since"), 0.0) or None
            until = env_like(query.get("until"), 0.0) or None
            level = query.get("level") if query.get("level") in events.LEVELS else None
            self._send_json({"events": events.query(since=since, until=until, kinds=query.get("kinds") or None,
                                                    level=level, limit=max(1, min(limit, 5000)))})
        elif path == "/api/logs":
            level = query.get("level") if query.get("level") in {"warn", "crit"} else ""
            self._send_json(diagnostics.logs(int(env_like(query.get("lines"), 500)),
                                             str(query.get("q") or ""), level))
        elif path == "/api/diagnostics/preview":
            try:
                self._send_json(diagnostics.preview_locked(settings.values(), self._diag_options(query)))
            except (diagnostics.LeakError, RuntimeError) as exc:
                self._leak_error(exc)
        elif path == "/api/diagnostics/bundle":
            try:
                body, filename = diagnostics.bundle_locked(settings.values(), self._diag_options(query),
                                                           reuse=str(query.get("reuse") or "") or None)
            except (diagnostics.LeakError, RuntimeError) as exc:
                self._leak_error(exc)
                return
            # Name aus dem Zeitpunkt des Pakets (wie Ordner und MANIFEST darin), nicht des Downloads.
            self._send(HTTPStatus.OK, body, "application/gzip",
                       {"Content-Disposition": f'attachment; filename="{filename}"',
                        "Cache-Control": "no-store"})
        elif path == "/api/recording":
            self._send_json(recording_status())
        elif path == "/api/enforce/snippets":
            self._send_json(enforce.api_snippets(query, settings.values()))
        elif path == "/api/enforce/check":
            cfg = settings.values()
            self._send_json(enforce.api_check(query, cfg, system_info(cfg)["addresses"], chrony.tracking()))
        elif path == "/api/clients/offsets":
            self._send_json(clientmon.status())
        elif path == "/api/notify":
            self._send_json(notify.api_config())
        elif path == "/api/notify/status":
            self._send_json(notify.api_status())
        elif path == "/api/apikeys":
            self._send_json({"keys": apikeys.list(), "auth_enabled": auth_info()["enabled"]})
        elif path == "/api/v1/instance":
            self._send_json(instance.info())
        elif path == "/metrics":
            self._send(HTTPStatus.OK, build_metrics().encode(), "text/plain; version=0.0.4; charset=utf-8")
        else:
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    def _diag_options(self, query: dict) -> dict:
        options = diagnostics.options_from_query(query)
        options.update(version=VERSION, uptime_seconds=int(time.time() - START_TIME),
                       chrony_conf=CHRONY_CONF,
                       history=HISTORY.snapshot(time.time() - 86400))
        return options

    def _leak_error(self, exc: Exception) -> None:
        # Nur Art und Fundstelle – den gefundenen Text selbst nicht noch einmal ausgeben.
        leaks = [{"kind": f.get("kind"), "path": f.get("path")} for f in getattr(exc, "findings", [])]
        self._send_json({"ok": False, "error": str(exc), "leaks": leaks}, HTTPStatus.INTERNAL_SERVER_ERROR)

    # --- POST ----------------------------------------------------------------
    def _csrf_ok(self, ident: dict | None = None) -> bool:
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return False
        if ident is not None and ident.get("kind") == "key":
            # Einen Bearer-Schlüssel hängt kein Browser von sich aus an eine fremde Anfrage.
            return True
        if self.headers.get("X-NTP-GUI") != "1":
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            if urlparse(origin).netloc != host:
                return False
        return True

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            raise ValueError("Anfrage zu groß")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("JSON-Objekt erwartet")
        return data

    def do_POST(self) -> None:
        path, index = self._api_path(self.path)
        ident = self._identity()
        if ident is None:
            self._deny_auth()
            return
        if not self._host_ok(ident):
            return
        if index:
            self._error(HTTPStatus.METHOD_NOT_ALLOWED, "GET /api/v1 beschreibt die API; hier gibt es nichts zu senden")
            return
        if not self._scope_ok(ident, "POST", path):
            self._deny_scope(ident, "POST", path)
            return
        if not self._csrf_ok(ident):
            self._error(HTTPStatus.FORBIDDEN, "Anfrage abgelehnt (nur aus dem Dashboard heraus)")
            return
        if env_flag("WEB_READONLY"):
            self._error(HTTPStatus.FORBIDDEN, "Einstellungen sind gesperrt (WEB_READONLY)")
            return
        try:
            data = self._read_json()
        except (ValueError, UnicodeDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, f"Ungültige Anfrage: {exc}")
            return
        try:
            self._route_post(path, data, ident)
        except settings.ValidationError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc),
                        fields=getattr(exc, "fields", {}))
        except BrokenPipeError:
            pass
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _after_change(self, result: dict) -> dict:
        reloaded = trigger_reload() if result.get("restart") else False
        result["reload_triggered"] = reloaded
        if result.get("restart") and not reloaded:
            result["reload_note"] = ("Gespeichert. Der Neustart der Zeitdienste konnte nicht "
                                     "ausgelöst werden – bitte den Container neu starten.")
        return result

    @staticmethod
    def _settings_event(title: str, result: dict, ident: dict) -> None:
        """Nur die Schlüssel ins Protokoll, nie die Werte (Hostnamen, Pfade …)."""
        changed = result.get("changed")
        keys = sorted(changed) if isinstance(changed, (list, dict, set, tuple)) else []
        if not keys:
            return
        data = {"keys": keys[:50], "restart": bool(result.get("restart"))}
        if ident.get("kind") == "key":
            data["api_key"] = ident.get("id")
        events.emit("settings", "info", f"{title}: {', '.join(keys[:8])}{' …' if len(keys) > 8 else ''}",
                    data, source="api" if ident.get("kind") == "key" else "web")

    def _route_post(self, path: str, data: dict, ident: dict | None = None) -> None:
        ident = ident or {"kind": "open"}
        if path == "/api/settings":
            # „changes“ (Dashboard) oder „values“ (so beschreibt es /api/v1)
            changes = data.get("changes", data.get("values"))
            if not isinstance(changes, dict) or not changes:
                raise settings.ValidationError("Keine Änderungen übergeben")
            result = settings.save(changes)
            self._settings_event("Einstellungen geändert", result, ident)
            self._send_json(self._after_change(result))
        elif path == "/api/settings/reset":
            keys = data.get("keys")
            if not isinstance(keys, list) or not keys:
                raise settings.ValidationError("Keine Einstellungen zum Zurücksetzen übergeben")
            result = settings.reset([str(k) for k in keys])
            self._settings_event("Einstellungen zurückgesetzt", result, ident)
            self._send_json(self._after_change(result))
        elif path == "/api/settings/import":
            values = data.get("values")
            if not isinstance(values, dict):
                raise settings.ValidationError("Datei enthält keine Einstellungen")
            # Auch Sicherungen älterer Versionen: erst auf das aktuelle Schema bringen.
            values, notes = settings.migrate_import({"schema": data.get("schema", 1), "values": values})
            result = settings.save(values) if values else {"changed": [], "restart": False}
            self._settings_event("Einstellungen importiert", result, ident)
            result = self._after_change(result)
            result["notes"] = notes
            self._send_json(result)
        elif path == "/api/settings/notes/ack":
            self._send_json({"acknowledged": settings.ack_migration_notes()})
        elif path == "/api/gps/autocal/rollback":
            try:
                self._send_json(autocal.rollback(data.get("steps", 1), cfg=settings.values()))
            except autocal.AutocalError as exc:
                self._error(HTTPStatus.CONFLICT, str(exc))
        elif path == "/api/recording":
            action = "stop" if data.get("stop") else str(data.get("action", "start"))
            if action == "stop":
                providers.stop()
                self._send_json(recording_status())
            elif action == "start":
                try:
                    providers.start_recording(data.get("seconds", 300))
                except ValueError as exc:
                    self._error(HTTPStatus.BAD_REQUEST, str(exc))
                    return
                events.emit("settings", "info", "Aufzeichnung der Datenquellen gestartet",
                            {"seconds": data.get("seconds", 300)})
                self._send_json(recording_status())
            else:
                self._error(HTTPStatus.BAD_REQUEST, "action muss „start“ oder „stop“ sein")
        elif path == "/api/notify/channels":
            try:
                self._send_json({"channel": notify.save_channel(data)})
            except notify.NotifyError as exc:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
        elif path == "/api/notify/channels/delete":
            if not notify.delete_channel(str(data.get("id", ""))):
                self._error(HTTPStatus.NOT_FOUND, "Diesen Kanal gibt es nicht (mehr)")
                return
            self._send_json({"ok": True})
        elif path == "/api/notify/test":
            try:
                self._send_json(notify.send_test(str(data.get("id", ""))))
            except notify.NotifyError as exc:
                self._error(HTTPStatus.NOT_FOUND, str(exc))
        elif path == "/api/apikeys":
            key_id, token = apikeys.create(data.get("name"), data.get("scope"))
            entry = next((k for k in apikeys.list() if k["id"] == key_id), {})
            self._send_json({"id": key_id, "token": token, "name": entry.get("name"),
                             "scope": entry.get("scope"), "scope_label": entry.get("scope_label")})
        elif path == "/api/apikeys/revoke":
            if not apikeys.revoke(str(data.get("id", ""))):
                self._error(HTTPStatus.NOT_FOUND, "Diesen Schlüssel gibt es nicht (mehr)")
                return
            self._send_json({"ok": True})
        elif path == "/api/instance/rotate":
            instance.rotate()  # schreibt selbst ein Ereignis
            self._send_json(instance.info())
        elif path == "/api/auth":
            if auth_info()["source"] == "env":
                raise settings.ValidationError("Der Zugang ist per WEB_USER/WEB_PASSWORD festgelegt "
                                               "und lässt sich hier nicht ändern.")
            if data.get("clear"):
                settings.set_credentials("", None)
            else:
                settings.set_credentials(str(data.get("user", "")), str(data.get("password", "")))
            AUTH_CACHE.clear()
            self._send_json({"ok": True, "auth": auth_info()})
        elif path == "/api/reload":
            self._send_json({"reload_triggered": trigger_reload()})
        else:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannte Aktion")


def env_like(raw, default: float) -> float:
    try:
        return float(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def main() -> None:
    port = env_number("WEB_PORT", 8080, int, minimum=1)
    bind = os.environ.get("WEB_BIND", "0.0.0.0")
    if bool(os.environ.get("WEB_USER", "").strip()) != bool(os.environ.get("WEB_PASSWORD", "")):
        print("[web] WARNUNG: WEB_USER und WEB_PASSWORD müssen beide gesetzt sein – "
              "das Dashboard läuft ohne Authentifizierung.", flush=True)

    autocal.configure(history=HISTORY, trigger_reload=trigger_reload)
    threading.Thread(target=collector, daemon=True, name="collector").start()
    threading.Thread(target=hardware_refresher, daemon=True, name="hardware").start()
    threading.Thread(target=events_ingester, daemon=True, name="events").start()
    notify.start(VERSION)  # eigener Thread je Kanal; ohne angelegte Kanäle geht nichts hinaus
    # Folgt clientmon_enable/ntp_port ohne Neustart.
    threading.Thread(target=clientmon.watch, args=(settings.values,), daemon=True, name="clientmon-watch").start()

    def save_and_exit(*_):
        clientmon.stop()
        HISTORY.save(force=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, save_and_exit)

    try:
        server = ThreadingHTTPServer((bind, port), Handler)
    except OSError as exc:
        raise SystemExit(f"[web] Port {bind}:{port} nicht verfügbar ({exc}). "
                         f"WEB_PORT anpassen oder den belegenden Dienst beenden.")
    server.daemon_threads = True
    note = {"env": "mit Basic-Auth (Umgebungsvariable)", "gui": "mit Passwort aus dem Dashboard",
            None: "ohne Passwort"}[auth_info()["source"]]
    print(f"[web] Dashboard auf http://{bind}:{port} ({note})", flush=True)
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        clientmon.stop()
        HISTORY.save(force=True)
        server.server_close()


if __name__ == "__main__":
    main()
