"""Small stdlib HTTP server that exposes the chrony/ptp state and the dashboard.

Deliberately dependency free: the container only needs python3 from Debian, so
the image stays small and builds without a package index for Python.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import socket
import threading
import time
from collections import deque
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import chrony
import gps
import ptp

STATIC_DIR = Path(__file__).with_name("static")
CHRONY_CONF = os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")
START_TIME = time.time()



def env_number(name: str, default, kind=float, minimum=None):
    """Numeric environment variable that never takes the container down.

    A typo in a compose file must not turn into a crash loop, so an unusable
    value falls back to the default instead of raising.
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


HISTORY_SIZE = env_number("HISTORY_SIZE", 720, int, minimum=2)
HISTORY_INTERVAL = env_number("HISTORY_INTERVAL", 10.0, float, minimum=1.0)

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class History:
    """Ring buffer of clock samples so the chart survives a browser reload."""

    def __init__(self, size: int) -> None:
        self._samples: deque[dict] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, tracking: dict, ptp_state: dict) -> None:
        sample = {
            "t": int(time.time()),
            "offset": tracking.get("system_time_offset"),
            "rms": tracking.get("rms_offset"),
            "freq": tracking.get("frequency_ppm"),
            "root_dispersion": tracking.get("root_dispersion"),
            "stratum": tracking.get("stratum"),
        }
        ptp_offset = ptp_state.get("offset_ns")
        if isinstance(ptp_offset, (int, float)):
            sample["ptp_offset"] = ptp_offset / 1e9
        with self._lock:
            self._samples.append(sample)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._samples)


HISTORY = History(HISTORY_SIZE)


def collector() -> None:
    while True:
        try:
            HISTORY.add(chrony.tracking(), ptp.status() if ptp.enabled() else {})
            if gps.enabled():
                gps.status()  # keep the gpsd cache warm for the dashboard
        except Exception:  # a sampling hiccup must never kill the thread
            pass
        time.sleep(HISTORY_INTERVAL)


def system_info() -> dict:
    info = {
        "hostname": socket.gethostname(),
        "time": time.time(),
        "timezone": time.strftime("%Z"),
        "uptime_seconds": int(time.time() - START_TIME),
        "title": os.environ.get("WEB_TITLE", "NTP / PTP Time Server"),
        "refresh_seconds": env_number("WEB_REFRESH_SECONDS", 5.0, float, minimum=1.0),
        "ntp_port": env_number("NTP_PORT", 123, int),
    }
    try:
        with open("/proc/uptime") as handle:
            info["host_uptime_seconds"] = int(float(handle.read().split()[0]))
    except OSError:
        pass
    info["addresses"] = []
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None):
            address = sockaddr[0]
            if address not in info["addresses"]:
                info["addresses"].append(address)
    except socket.gaierror:
        pass
    return info


def build_status() -> dict:
    tracking = chrony.tracking()
    ptp_state = ptp.status()
    clients = chrony.clients()
    return {
        "system": system_info(),
        "tracking": tracking,
        "sources": chrony.merged_sources(),
        "activity": chrony.activity(),
        "serverstats": chrony.serverstats(),
        "clients": clients,
        "client_count": len(clients),
        "ptp": ptp_state,
        "gps": gps.status(),
        "chrony_running": bool(tracking),
    }


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

    for source in chrony.merged_sources():
        labels = '{source="%s",mode="%s"}' % (
            _escape_label(source.get("name", "")), _escape_label(source.get("mode_label", "")))
        _metric(lines, "ntpgui_source_offset_seconds", source.get("offset"), "Offset per source", labels=labels)
        _metric(lines, "ntpgui_source_stratum", source.get("stratum"), "Stratum per source", labels=labels)
        _metric(lines, "ntpgui_source_reach_percent", source.get("reach_percent"), "Reachability per source", labels=labels)
        _metric(lines, "ntpgui_source_selected", 1 if source.get("state") == "*" else 0, "1 for the selected source", labels=labels)

    stats = chrony.serverstats()
    _metric(lines, "ntpgui_ntp_packets_received_total", stats.get("ntp_packets_received"), "NTP packets served", kind="counter")
    _metric(lines, "ntpgui_ntp_packets_dropped_total", stats.get("ntp_packets_dropped"), "NTP packets dropped", kind="counter")
    _metric(lines, "ntpgui_clients", len(chrony.clients()), "Known NTP clients")

    gps_state = gps.status()
    if gps_state.get("enabled"):
        _metric(lines, "ntpgui_gps_running", 1 if gps_state.get("running") else 0, "1 when gpsd answers")
        _metric(lines, "ntpgui_gps_fix_mode", gps_state.get("mode"), "gpsd fix mode (0-3)")
        _metric(lines, "ntpgui_gps_satellites_used", gps_state.get("satellites_used"), "Satellites used for the fix")
        _metric(lines, "ntpgui_gps_satellites_seen", gps_state.get("satellites_seen"), "Satellites in view")
        _metric(lines, "ntpgui_gps_hdop", gps_state.get("hdop"), "Horizontal dilution of precision")

    ptp_state = ptp.status()
    if ptp_state.get("enabled"):
        _metric(lines, "ntpgui_ptp_running", 1 if ptp_state.get("running") else 0, "1 when ptp4l answers")
        _metric(lines, "ntpgui_ptp_offset_seconds", (ptp_state.get("offset_ns") or 0) / 1e9 if isinstance(ptp_state.get("offset_ns"), (int, float)) else None, "PTP offset from master")
        _metric(lines, "ntpgui_ptp_mean_path_delay_seconds", (ptp_state.get("meanPathDelay") or 0) / 1e9 if isinstance(ptp_state.get("meanPathDelay"), (int, float)) else None, "PTP mean path delay")
        _metric(lines, "ntpgui_ptp_steps_removed", ptp_state.get("stepsRemoved"), "Steps removed from the grandmaster")
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    server_version = "ntp-gui"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, credentials: tuple[str, str] | None = None, **kwargs) -> None:
        self._credentials = credentials
        super().__init__(*args, **kwargs)

    # --- helpers -----------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # quieter access log
        if env_flag("WEB_ACCESS_LOG"):
            super().log_message(fmt, *args)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str, extra_headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=str).encode()
        self._send(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _authorised(self) -> bool:
        if not self._credentials:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        except Exception:
            return False
        user, _, password = decoded.partition(":")
        expected_user, expected_password = self._credentials
        # compare_digest refuses str with non-ASCII characters, so compare bytes.
        return (hmac.compare_digest(user.encode("utf-8"), expected_user.encode("utf-8"))
                & hmac.compare_digest(password.encode("utf-8"), expected_password.encode("utf-8")))

    def _serve_static(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        if not path.is_file() or STATIC_DIR.resolve() not in path.parents:
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            return
        content_type = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, path.read_bytes(), content_type, {"Cache-Control": "no-cache"})

    # --- routing -----------------------------------------------------------
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
            self._send(
                HTTPStatus.UNAUTHORIZED,
                b"authentication required\n",
                "text/plain; charset=utf-8",
                {"WWW-Authenticate": 'Basic realm="ntp-gui"'},
            )
            return

        try:
            if path == "/":
                self._serve_static("index.html")
            elif path.startswith("/static/"):
                self._serve_static(path[len("/static/"):])
            elif path == "/api/status":
                self._send_json(build_status())
            elif path == "/api/history":
                self._send_json({"samples": HISTORY.snapshot(), "interval": HISTORY_INTERVAL})
            elif path == "/api/config":
                try:
                    text = Path(CHRONY_CONF).read_text()
                except OSError as exc:
                    text = f"# {CHRONY_CONF} nicht lesbar: {exc}"
                self._send_json({"path": CHRONY_CONF, "content": text})
            elif path == "/metrics":
                self._send(HTTPStatus.OK, build_metrics().encode(), "text/plain; version=0.0.4; charset=utf-8")
            else:
                self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
        except BrokenPipeError:
            pass
        except Exception as exc:  # never take the dashboard down on a parse error
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    port = env_number("WEB_PORT", 8080, int, minimum=1)
    bind = os.environ.get("WEB_BIND", "0.0.0.0")
    user = os.environ.get("WEB_USER", "").strip()
    password = os.environ.get("WEB_PASSWORD", "")
    credentials = (user, password) if user and password else None
    if bool(user) != bool(password):
        print("[web] WARNUNG: WEB_USER und WEB_PASSWORD müssen beide gesetzt sein – "
              "das Dashboard läuft ohne Authentifizierung.", flush=True)

    threading.Thread(target=collector, daemon=True, name="collector").start()

    handler = partial(Handler, credentials=credentials)
    try:
        server = ThreadingHTTPServer((bind, port), handler)
    except OSError as exc:
        raise SystemExit(f"[web] Port {bind}:{port} nicht verfügbar ({exc}). "
                         f"WEB_PORT anpassen oder den belegenden Dienst beenden.")
    server.daemon_threads = True
    auth_note = "mit Basic-Auth" if credentials else "ohne Authentifizierung"
    print(f"[web] dashboard on http://{bind}:{port} ({auth_note})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
