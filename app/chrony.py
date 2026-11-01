"""Thin wrapper around chronyc that turns its output into JSON-friendly dicts.

We use chronyc's CSV mode (-c) wherever it is available because the field order
is stable across chrony releases, and fall back to parsing the human readable
"Name : value" output for reports whose column set changes between versions
(serverstats being the prominent example).
"""

from __future__ import annotations

import calendar
import ipaddress
import os
import re
import shutil
import time
import subprocess
from typing import Any

CHRONYC = shutil.which("chronyc") or "/usr/bin/chronyc"

# chronyc -c tracking, in field order.
_TRACKING_FIELDS = [
    ("ref_id", str),
    ("ref_name", str),
    ("stratum", int),
    ("ref_time", float),
    ("system_time_offset", float),
    ("last_offset", float),
    ("rms_offset", float),
    ("frequency_ppm", float),
    ("residual_frequency_ppm", float),
    ("skew_ppm", float),
    ("root_delay", float),
    ("root_dispersion", float),
    ("update_interval", float),
    ("leap_status", str),
]

# chronyc -c sources, in field order.
_SOURCE_FIELDS = [
    ("mode", str),
    ("state", str),
    ("name", str),
    ("stratum", int),
    ("poll", int),
    ("reach", "octal"),
    ("last_rx", int),
    ("offset", float),
    ("original_offset", float),
    ("error", float),
]

# chronyc -c sourcestats, in field order.
_SOURCESTAT_FIELDS = [
    ("name", str),
    ("samples", int),
    ("runs", int),
    ("span", int),
    ("frequency_ppm", float),
    ("frequency_skew_ppm", float),
    ("offset", float),
    ("std_dev", float),
]

# chronyc -c clients, in field order.
_CLIENT_FIELDS = [
    ("address", str),
    ("ntp_packets", int),
    ("ntp_dropped", int),
    ("ntp_interval", float),
    ("ntp_interval_limit", float),
    ("ntp_last_rx", int),
    ("cmd_packets", int),
    ("cmd_dropped", int),
    ("cmd_interval", float),
    ("cmd_last_rx", int),
]

MODE_LABELS = {"^": "server", "=": "peer", "#": "refclock"}
STATE_LABELS = {
    "*": "synced",
    "+": "combined",
    "-": "excluded",
    "?": "unreachable",
    "x": "falseticker",
    "~": "variable",
}


class ChronyError(RuntimeError):
    """chronyd could not be queried."""


def run(*args: str, timeout: float = 5.0) -> str:
    """Run chronyc with the given arguments and return stdout."""
    try:
        host = os.environ.get("CHRONYC_HOST")  # nur für Entwicklung/Tests
        prefix = ["-h", host] if host else []
        proc = subprocess.run(
            [CHRONYC, *prefix, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # chronyc missing entirely
        raise ChronyError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise ChronyError(f"chronyc {' '.join(args)} timed out") from exc
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        raise ChronyError(message or f"chronyc {' '.join(args)} failed")
    return proc.stdout


def _coerce(value: str, kind) -> Any:
    value = value.strip()
    if kind is str:
        return value
    if kind == "octal":
        # chronyc prints the reachability register in octal (e.g. 377 = 8/8).
        try:
            return int(value, 8)
        except ValueError:
            return None
    try:
        return kind(value)
    except ValueError:
        return None


def _parse_csv_row(row: str, fields: list[tuple[str, Any]]) -> dict[str, Any]:
    parts = row.split(",")
    record: dict[str, Any] = {}
    for index, (name, kind) in enumerate(fields):
        record[name] = _coerce(parts[index], kind) if index < len(parts) else None
    return record


def _csv_rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def parse_tracking(text: str) -> dict[str, Any]:
    rows = _csv_rows(text)
    if not rows:
        return {}
    record = _parse_csv_row(rows[0], _TRACKING_FIELDS)
    leap = (record.get("leap_status") or "").lower()
    # 7F7F0101 (127.127.1.1) is chrony's reference id for "local" mode, i.e. the
    # server hands out its own unsynchronised clock. That is a valid island-mode
    # state, but it must not be reported as synchronised to an upstream source.
    record["local_reference"] = record.get("ref_id") == "7F7F0101" or not record.get("ref_name")
    record["synchronised"] = bool(
        record.get("stratum")
        and record["stratum"] < 16
        and leap in {"normal", "insert second", "delete second"}
        and not record["local_reference"]
    )
    return record


def parse_sources(text: str) -> list[dict[str, Any]]:
    sources = []
    for row in _csv_rows(text):
        record = _parse_csv_row(row, _SOURCE_FIELDS)
        record["mode_label"] = MODE_LABELS.get(record.get("mode"), record.get("mode"))
        record["state_label"] = STATE_LABELS.get(record.get("state"), record.get("state"))
        reach = record.get("reach")
        # reach is an octal register of the last 8 polls; show it as a percentage.
        record["reach_percent"] = round(bin(reach).count("1") / 8 * 100) if isinstance(reach, int) else None
        # chrony reports "never heard from" as an unsigned -1.
        if record.get("last_rx") == 0xFFFFFFFF:
            record["last_rx"] = None
        sources.append(record)
    return sources


def parse_sourcestats(text: str) -> list[dict[str, Any]]:
    return [_parse_csv_row(row, _SOURCESTAT_FIELDS) for row in _csv_rows(text)]


def parse_clients(text: str) -> list[dict[str, Any]]:
    clients = []
    for row in _csv_rows(text):
        record = _parse_csv_row(row, _CLIENT_FIELDS)
        if not record.get("address"):
            continue
        for field in ("ntp_last_rx", "cmd_last_rx"):
            if record.get(field) == 0xFFFFFFFF:
                record[field] = None
        # An interval of 127 is chrony's "-" placeholder in the client report.
        for field in ("ntp_interval", "ntp_interval_limit", "cmd_interval"):
            if record.get(field) == 127:
                record[field] = None
        clients.append(record)
    return clients


def parse_activity(text: str) -> dict[str, Any]:
    """chronyc -c activity returns five counters on a single comma separated line."""
    fields = [field for row in _csv_rows(text) for field in row.split(",")]
    values = [int(v) for v in fields if v.strip().lstrip("-").isdigit()]
    keys = ["online", "offline", "burst_online", "burst_offline", "unresolved"]
    activity = dict(zip(keys, values))
    activity["total"] = sum(activity.get(k, 0) for k in ("online", "offline", "burst_online", "burst_offline"))
    return activity


def parse_serverstats(text: str) -> dict[str, Any]:
    """serverstats gains fields with every chrony release, so parse it by label."""
    stats: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        key = label.strip().lower()
        for char in " -/":
            key = key.replace(char, "_")
        value = value.strip()
        try:
            stats[key] = int(value)
        except ValueError:
            try:
                stats[key] = float(value)
            except ValueError:
                stats[key] = value
    return stats


def _safe(func, *args, default):
    try:
        return func(*args)
    except ChronyError:
        return default


def tracking() -> dict[str, Any]:
    return _safe(lambda: parse_tracking(run("-c", "tracking")), default={})


def sources() -> list[dict[str, Any]]:
    return _safe(lambda: parse_sources(run("-c", "sources")), default=[])


def sourcestats() -> list[dict[str, Any]]:
    return _safe(lambda: parse_sourcestats(run("-c", "sourcestats")), default=[])


def clients() -> list[dict[str, Any]]:
    return _safe(lambda: parse_clients(run("-c", "clients")), default=[])


def activity() -> dict[str, Any]:
    return _safe(lambda: parse_activity(run("-c", "activity")), default={})


def serverstats() -> dict[str, Any]:
    return _safe(lambda: parse_serverstats(run("serverstats")), default={})


def merged_sources() -> list[dict[str, Any]]:
    """sources + sourcestats joined on the source name."""
    stats = {row["name"]: row for row in sourcestats() if row.get("name")}
    merged = []
    for source in sources():
        extra = stats.get(source.get("name"), {})
        merged.append(
            {
                **source,
                "samples": extra.get("samples"),
                "span": extra.get("span"),
                "std_dev": extra.get("std_dev"),
                "frequency_skew_ppm": extra.get("frequency_skew_ppm"),
            }
        )
    return merged


# ---------------------------------------------------------------------------
# Quellenauswahl, NTP-Details und NTS (chrony >= 4.1)
# ---------------------------------------------------------------------------

# Zustandsbuchstaben aus "chronyc selectdata" (identisch in 4.3 und 4.5).
SELECT_STATES = {
    "*": "best", "+": "combined", "-": "not_combined", "x": "falseticker",
    "N": "noselect", "s": "unsynchronised", "M": "missing_samples",
    "d": "distance", "D": "large_distance", "~": "jittery", "w": "waits_others",
    "W": "waits_others", "S": "stale", "O": "orphan", "T": "not_trusted",
    "P": "not_preferred", "U": "waits_update",
}
_OPTION_LETTERS = {"N": "noselect", "P": "prefer", "T": "trust", "R": "require"}


def _options(letters: list[str]) -> list[str]:
    return [_OPTION_LETTERS[c] for c in letters if c in _OPTION_LETTERS]


def parse_selectdata(text: str) -> list[dict[str, Any]]:
    """chronyc -c selectdata: state,name,auth,<conf opts>,<eff opts>,last,score,lo,hi,leap.

    Die Zahl der Optionsspalten hat sich zwischen Versionen geändert; die
    festen Felder am Anfang und Ende werden deshalb von beiden Seiten gelesen.
    """
    rows = []
    for row in _csv_rows(text):
        parts = row.split(",")
        if len(parts) < 8:
            continue
        head, tail = parts[:3], parts[-5:]
        middle = parts[3:-5]
        half = len(middle) // 2
        try:
            lo, hi = float(tail[2]), float(tail[3])
        except ValueError:
            lo = hi = None
        rows.append({
            "state_code": head[0],
            "select_state": SELECT_STATES.get(head[0], head[0]),
            "name": head[1],
            "authenticated": head[2] == "Y",
            "configured_options": _options(middle[:half]),
            "effective_options": _options(middle[half:]),
            "last_sample_ago": _coerce(tail[0], int),
            "score": _coerce(tail[1], float),
            "interval_low": lo,
            "interval_high": hi,
            "leap": tail[4],
        })
    return rows


_NTPDATA_KEYS = {
    "Remote address": "remote", "Remote port": "remote_port", "Local address": "local",
    "Leap status": "leap", "Version": "version", "Mode": "mode", "Stratum": "stratum",
    "Poll interval": "poll", "Precision": "precision", "Root delay": "root_delay",
    "Root dispersion": "root_dispersion", "Reference ID": "reference_id",
    "Reference time": "reference_time", "Offset": "offset", "Peer delay": "peer_delay",
    "Peer dispersion": "peer_dispersion", "Response time": "response_time",
    "Jitter asymmetry": "jitter_asymmetry", "NTP tests": "ntp_tests",
    "Interleaved": "interleaved", "Authenticated": "authenticated",
    "TX timestamping": "tx_timestamping", "RX timestamping": "rx_timestamping",
    "Total TX": "total_tx", "Total RX": "total_rx", "Total valid RX": "total_valid_rx",
    "Total good RX": "total_good_rx",
}


def _leading_number(text: str):
    match = re.match(r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", text)
    if not match:
        return None
    number = float(match.group(1))
    return int(number) if re.fullmatch(r"[-+]?\d+", match.group(1)) else number


def parse_ntpdata(text: str) -> list[dict[str, Any]]:
    """chronyc ntpdata (Klartext, Blöcke durch Leerzeilen getrennt).

    Die Klartextausgabe ist über Versionen stabiler als die CSV-Spalten.
    """
    blocks, current = [], {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        label, sep, value = line.partition(":")
        if not sep:
            continue
        key = _NTPDATA_KEYS.get(label.strip())
        if not key:
            continue
        value = value.strip()
        if key in {"remote", "local", "reference_id"}:
            current[key] = value.split(" (")[0].strip()
            if key == "reference_id" and "(" in value:
                current["reference_name"] = value.split("(", 1)[1].rstrip(")")
        elif key in {"leap", "mode", "interleaved", "authenticated", "tx_timestamping",
                     "rx_timestamping", "reference_time", "ntp_tests"}:
            current[key] = value
        elif key in {"poll", "precision"}:
            current[key] = _leading_number(value)
            seconds = re.search(r"\(([-+\d.eE]+) seconds\)", value)
            if seconds:
                current[key + "_seconds"] = float(seconds.group(1))
        else:
            current[key] = _leading_number(value)
    if current:
        blocks.append(current)
    for block in blocks:
        tests = (block.get("ntp_tests") or "").replace(" ", "")
        if tests:
            block["ntp_tests_passed"] = tests.count("1")
            block["ntp_tests_total"] = len(tests)
    return blocks


def parse_authdata(text: str) -> list[dict[str, Any]]:
    """chronyc -c authdata: name,mode,keyid,type,klen,last_ke,attempts,nak,cookies,cookie_len."""
    rows = []
    for row in _csv_rows(text):
        parts = row.split(",")
        if len(parts) < 10:
            continue
        last = _coerce(parts[5], int)
        rows.append({
            "name": parts[0], "mode": parts[1], "key_id": _coerce(parts[2], int),
            "key_type": _coerce(parts[3], int), "key_length": _coerce(parts[4], int),
            "last_ke_ago": None if last == 0xFFFFFFFF else last,
            "ke_attempts": _coerce(parts[6], int), "nak": _coerce(parts[7], int),
            "cookies": _coerce(parts[8], int), "cookie_length": _coerce(parts[9], int),
        })
    return rows


def selectdata() -> list[dict[str, Any]]:
    return _safe(lambda: parse_selectdata(run("-c", "selectdata")), default=[])


def ntpdata() -> list[dict[str, Any]]:
    return _safe(lambda: parse_ntpdata(run("ntpdata")), default=[])


def authdata() -> list[dict[str, Any]]:
    return _safe(lambda: parse_authdata(run("-c", "authdata")), default=[])


_NAME_CACHE: dict[str, tuple[float, str]] = {}


def source_name(address: str) -> str | None:
    """Konfigurierter Name (z. B. ptbtime1.ptb.de) zu einer Quell-IP, 10 min gecacht."""
    now = time.time()
    cached = _NAME_CACHE.get(address)
    if cached and now - cached[0] < 600:
        return cached[1] or None
    try:
        name = run("sourcename", address, timeout=2.0).strip()
    except ChronyError:
        name = ""
    if name == address:
        name = ""
    _NAME_CACHE[address] = (now, name)
    return name or None


def detailed_sources() -> list[dict[str, Any]]:
    """Alles, was chrony je Quelle weiß, zusammengeführt."""
    merged = merged_sources()
    select = {row["name"]: row for row in selectdata()}
    ntp = {row.get("remote"): row for row in ntpdata() if row.get("remote")}
    auth = {row["name"]: row for row in authdata()}
    for source in merged:
        name = source.get("name") or ""
        sel = select.get(name)
        if sel:
            source.update({k: v for k, v in sel.items() if k != "name"})
        if source.get("mode") in {"^", "="}:
            source["ntp"] = ntp.get(name)
            source["auth"] = auth.get(name)
            source["hostname"] = source_name(name)
    return merged


OPENSSL = shutil.which("openssl")
_CERT_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_CERT_TTL = 60.0


def _readable(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            handle.read(1)
        return True
    except OSError:
        return False


def parse_openssl_cert(text: str) -> dict[str, Any]:
    """Ausgabe von `openssl x509 -noout -enddate -subject -ext subjectAltName`.

    Liefert not_after (Unix-Zeit), den CN und die alternativen Namen (SAN).
    """
    info: dict[str, Any] = {"not_after": None, "common_name": None, "alt_names": [],
                            "issuer": None, "issuer_cn": None}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("notAfter="):
            raw = " ".join(stripped.split("=", 1)[1].split())
            for fmt in ("%b %d %H:%M:%S %Y %Z", "%b %d %H:%M:%S %Y"):
                try:
                    info["not_after"] = calendar.timegm(time.strptime(raw, fmt))
                    break
                except ValueError:
                    continue
        elif stripped.startswith("issuer="):
            # "issuer=C = US, O = Let's Encrypt, CN = R11" (alt: "/C=US/O=.../CN=R11")
            org = re.search(r"(?:^|[,/=]\s*)O\s*=\s*([^,/]+)", stripped.split("=", 1)[1])
            cn = re.search(r"CN\s*=\s*([^,/]+)", stripped)
            info["issuer_cn"] = cn.group(1).strip() if cn else None
            parts = [m.group(1).strip() for m in (org, cn) if m]
            info["issuer"] = " – ".join(dict.fromkeys(parts)) or None
        elif stripped.startswith("subject="):
            match = re.search(r"CN\s*=\s*([^,/]+)", stripped)
            if match:
                info["common_name"] = match.group(1).strip()
        elif "Subject Alternative Name" in stripped and index + 1 < len(lines):
            names = []
            for part in lines[index + 1].split(","):
                _, _, value = part.strip().partition(":")
                if value:
                    names.append(value.strip())
            info["alt_names"] = names
    return info


def _cert_info(path: str) -> dict[str, Any]:
    """openssl-Auswertung des Zertifikats, 60 s gecacht (Schlüssel: Pfad + mtime)."""
    if not OPENSSL:
        return {"openssl": False}
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return {"openssl": True}
    now = time.time()
    key = (path, mtime)
    cached = _CERT_CACHE.get(key)
    if cached and now - cached[0] < _CERT_TTL:
        return cached[1]
    info: dict[str, Any] = {"openssl": True, "error": None}
    # -ext gibt es erst ab OpenSSL 1.1.1; ohne SAN reicht notfalls auch der CN.
    for args in (["-enddate", "-subject", "-issuer", "-ext", "subjectAltName"],
                 ["-enddate", "-subject", "-issuer"]):
        try:
            proc = subprocess.run([OPENSSL, "x509", "-noout", *args, "-in", path],
                                  capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            info["error"] = str(exc)
            break
        if proc.returncode == 0:
            info.update(parse_openssl_cert(proc.stdout))
            info["error"] = None
            break
        lines = (proc.stderr or "").strip().splitlines()
        info["error"] = lines[-1] if lines else "openssl konnte das Zertifikat nicht lesen"
    _CERT_CACHE.clear()  # immer nur ein Zertifikat – alte Einträge nicht ansammeln
    _CERT_CACHE[key] = (now, info)
    return info


def cert_covers_name(name: str, cert_names: list[str]) -> bool:
    """Deckt ein Zertifikatsname (CN/SAN, auch *.example.com) den Hostnamen ab?

    Regeln wie RFC 6125 6.4.3: Groß/Kleinschreibung egal, ein Wildcard ersetzt
    genau EIN Label ganz links (*.example.com passt auf time.example.com, nicht
    auf example.com oder a.b.example.com). IP-Adressen nur exakt.
    """
    wanted = (name or "").strip().rstrip(".").lower()
    if not wanted:
        return False
    try:
        wanted_ip = ipaddress.ip_address(wanted)
    except ValueError:
        wanted_ip = None
    for raw in cert_names:
        candidate = str(raw or "").strip().rstrip(".").lower()
        if not candidate:
            continue
        if wanted_ip is not None:
            try:
                if ipaddress.ip_address(candidate) == wanted_ip:
                    return True
            except ValueError:
                pass
            continue
        if candidate == wanted:
            return True
        if candidate.startswith("*.") and "*" not in candidate[2:]:
            suffix = candidate[1:]  # ".example.com"
            head, dot, rest = wanted.partition(".")
            if head and dot and "." + rest == suffix and suffix.count(".") >= 2:
                return True
    return False


def nts_server_status(cfg: dict, stats: dict | None = None) -> dict:
    """Zustand des eigenen NTS-Servers: Dateien, Ablaufdatum, Zähler aus serverstats."""
    enabled = bool(cfg.get("nts_server_enable"))
    cert = cfg.get("nts_server_cert") or ""
    key = cfg.get("nts_server_key") or ""
    name = cfg.get("nts_server_name") or ""
    try:
        port = int(cfg.get("nts_server_port") or 4460)
    except (TypeError, ValueError):
        port = 4460
    result: dict[str, Any] = {"enabled": enabled, "cert": cert, "key": key,
                              "name": name, "port": port}
    if not enabled:
        return result
    result.update({
        "cert_exists": bool(cert) and os.path.isfile(cert),
        "key_exists": bool(key) and os.path.isfile(key),
    })
    result["cert_readable"] = result["cert_exists"] and _readable(cert)
    result["key_readable"] = result["key_exists"] and _readable(key)
    info = _cert_info(cert) if result["cert_readable"] else {}
    not_after = info.get("not_after")
    names = [n for n in [info.get("common_name"), *info.get("alt_names", [])] if n]
    result.update({
        "openssl": info.get("openssl", bool(OPENSSL)),
        "cert_error": info.get("error"),
        "not_after": not_after,
        "days_left": None if not_after is None else round((not_after - time.time()) / 86400, 1),
        "subject": info.get("common_name"),
        "names": list(dict.fromkeys(names)),
        "cert_issuer": info.get("issuer"),
        # Selbst signiert: Clients brauchen das Zertifikat dann als vertrauenswürdige CA.
        "cert_self_signed": (None if not info.get("issuer_cn") or not info.get("common_name")
                             else info.get("issuer_cn") == info.get("common_name")),
    })
    # Clients prüfen den Namen gegen die SAN-Einträge; nur ohne SAN zählt der CN.
    match_names = info.get("alt_names") or ([info["common_name"]] if info.get("common_name") else [])
    result["name_matches_cert"] = (cert_covers_name(name, match_names)
                                   if name and match_names else None)
    if stats is None:
        stats = serverstats()
    result.update({
        "ke_accepted": stats.get("nts_ke_connections_accepted"),
        "ke_dropped": stats.get("nts_ke_connections_dropped"),
        "authenticated_packets": stats.get("authenticated_ntp_packets"),
    })
    return result
