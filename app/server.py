"""HTTP-Server für Dashboard und API – nur Python-Standardbibliothek.

Lesend: Status, Verlauf, Konfiguration, Geräte, Metriken.
Schreibend (POST): Einstellungen, Passwort, Neustart der Zeitdienste.

Schutz der schreibenden Routen:
  * ist ein Zugang gesetzt (Env oder Dashboard), gilt Basic-Auth für alles
    außer /healthz;
  * WEB_READONLY=true sperrt alle Änderungen;
  * gegen Cross-Site-Requests: nur JSON, Pflicht-Header X-NTP-GUI, und ein
    mitgeschickter Origin muss zum Host passen.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import signal
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import chrony
import devices
import gps
import history as historymod
import insights
import ptp
import settings

STATIC_DIR = Path(__file__).with_name("static")
CHRONY_CONF = os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")
PTP4L_CONF = os.environ.get("PTP4L_CONF", "/etc/linuxptp/ptp4l.conf")
RUN_DIR = os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")
START_TIME = time.time()
MAX_BODY = 64 * 1024
VERSION = os.environ.get("NTPGUI_VERSION", "1.1.0")


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


def collector() -> None:
    restored = HISTORY.load()
    if restored:
        print(f"[web] Verlauf wiederhergestellt: {restored} Messpunkte", flush=True)
    while True:
        try:
            HISTORY.add(collect_sample())
            HISTORY.save()
        except Exception as exc:  # ein Messfehler darf den Thread nie beenden
            print(f"[web] Messung fehlgeschlagen: {exc}", flush=True)
        try:
            interval = float(settings.values()["history_interval"])
        except Exception:
            interval = 10.0
        time.sleep(max(2.0, interval))


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
    status["insights"] = insights.build(status, cfg)
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
    return "\n".join(lines) + "\n"


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
        self._send(HTTPStatus.UNAUTHORIZED, b"authentication required\n", "text/plain; charset=utf-8",
                   {"WWW-Authenticate": 'Basic realm="ntp-gui", charset="UTF-8"'})

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
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/healthz":
            healthy = bool(chrony.tracking())
            self._send_json({"status": "ok" if healthy else "degraded", "chrony": healthy},
                            HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if not self._authorised():
            self._deny_auth()
            return
        try:
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
            self._send_json(schema)
        elif path == "/api/settings/export":
            body = json.dumps(settings.export_values(), indent=2, ensure_ascii=False).encode()
            self._send(HTTPStatus.OK, body, "application/json; charset=utf-8",
                       {"Content-Disposition": 'attachment; filename="ntp-gui-einstellungen.json"',
                        "Cache-Control": "no-store"})
        elif path == "/api/reload":
            self._send_json(reload_status())
        elif path == "/api/devices":
            self._send_json(devices.summary(settings.values()))
        elif path == "/api/gps/calibration":
            cfg = settings.values()
            window = env_like(query.get("window"), 0.0)
            since = time.time() - window if window > 0 else None
            self._send_json(historymod.calibrate(HISTORY.snapshot(since), cfg["gps_refid"],
                                                 float(cfg["gps_offset"]), float(cfg["gps_delay"])))
        elif path == "/metrics":
            self._send(HTTPStatus.OK, build_metrics().encode(), "text/plain; version=0.0.4; charset=utf-8")
        else:
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    # --- POST ----------------------------------------------------------------
    def _csrf_ok(self) -> bool:
        if self.headers.get("X-NTP-GUI") != "1":
            return False
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
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
        path = urlparse(self.path).path.rstrip("/")
        if not self._authorised():
            self._deny_auth()
            return
        if not self._csrf_ok():
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
            self._route_post(path, data)
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

    def _route_post(self, path: str, data: dict) -> None:
        if path == "/api/settings":
            changes = data.get("changes")
            if not isinstance(changes, dict) or not changes:
                raise settings.ValidationError("Keine Änderungen übergeben")
            self._send_json(self._after_change(settings.save(changes)))
        elif path == "/api/settings/reset":
            keys = data.get("keys")
            if not isinstance(keys, list) or not keys:
                raise settings.ValidationError("Keine Einstellungen zum Zurücksetzen übergeben")
            self._send_json(self._after_change(settings.reset([str(k) for k in keys])))
        elif path == "/api/settings/import":
            values = data.get("values")
            if not isinstance(values, dict):
                raise settings.ValidationError("Datei enthält keine Einstellungen")
            self._send_json(self._after_change(settings.save(values)))
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

    threading.Thread(target=collector, daemon=True, name="collector").start()

    def save_and_exit(*_):
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
        HISTORY.save(force=True)
        server.server_close()


if __name__ == "__main__":
    main()
