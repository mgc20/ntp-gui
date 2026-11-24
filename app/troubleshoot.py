"""Geführte Fehlersuche „Mein Gerät bekommt keine Zeit“ (1.11).

Vom Symptom her: Für eine eingegebene IP-Adresse geht ntp-gui eine feste Prüfliste durch und endet mit
genau einem Befund und dem nächsten Schritt.

  1. Erlaubte/ausgenommene Netze (ALLOW_NETWORKS, DENY_NETWORKS) – wie chronyd sie auswertet
  2. Dienst lauscht (NTP-Port, BIND_ADDRESS) – aus /proc/net/udp und /proc/net/udp6
  3. Server synchron bzw. Inselbetrieb (SERVE_UNSYNCED, mit der Regel für öffentliche Netze)
  4. Bridge- statt Host-Netz (Anfragen erscheinen als Gateway des Docker-Netzes)
  5. Anfragen dieser Adresse gesehen (chronyd und eigene passive Messung)
  6. Verworfen durch die Begrenzung (Ratelimit)
  7. Uhr des Geräts messbar und wie weit daneben

Rein lesend: Die Prüfung schickt nichts ins Netz und löst keine Namen auf – nur IP-Adressen werden
angenommen. Nachmessen bleibt beim vorhandenen, gedrosselten „Aktiv nachmessen“ (clientinfo.probe,
nur private Adressen bekannter Geräte). Der Befund ist die erste Prüfung mit Ergebnis „fail“, sonst die
erste mit „warn“, sonst „ok“.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import time
from typing import Any, Iterable

import clientinfo
import clientmon
import settings

OK, WARN, FAIL, INFO, SKIP = "ok", "warn", "fail", "info", "skip"
LEVEL = {OK: "ok", WARN: "warn", FAIL: "crit"}

# Ab dieser Abweichung übernimmt das Gerät die Zeit offenbar nicht (normale Clients liegen weit darunter).
OFFSET_WARN = 0.5
# Anteil verworfener Anfragen, ab dem das Gerät praktisch keine Antworten mehr bekommt.
DROP_FAIL = 0.5

UDP_PATHS = ("/proc/net/udp", "/proc/net/udp6")


class InputError(ValueError):
    """Ungültige Eingabe – Text für die Antwort 400."""


def clean_target(value: Any) -> str:
    """Nur eine IP-Adresse (IPv4/IPv6, ohne Zonen-Angabe). Namen werden bewusst nicht aufgelöst."""
    text = str(value or "").strip()
    if not text:
        raise InputError("Bitte die IP-Adresse des Geräts eingeben.")
    if len(text) > 45:
        raise InputError("Das ist keine IP-Adresse.")
    addr = clientinfo.clean_ip(text)
    if addr is None:
        if any(ch.isalpha() for ch in text) and ":" not in text:
            raise InputError("Bitte eine IP-Adresse eingeben – Namen werden hier nicht aufgelöst.")
        raise InputError("Das ist keine gültige IPv4- oder IPv6-Adresse.")
    ip = ipaddress.ip_address(addr)
    if ip.is_unspecified or ip.is_multicast or (ip.version == 4 and addr == "255.255.255.255"):
        raise InputError("Das ist keine Adresse eines einzelnen Geräts.")
    return addr


# ---------------------------------------------------------------------------
# Erlaubte Netze wie chronyd: die genaueste passende Zeile gilt, bei Gleichstand „deny“
# (confgen schreibt die deny-Zeilen nach den allow-Zeilen).
# ---------------------------------------------------------------------------

def _networks(items: Iterable[Any]) -> list[tuple[Any, str]]:
    out = []
    for item in items or []:
        text = str(item).strip()
        if text.lower() == "all":
            out += [(ipaddress.ip_network("0.0.0.0/0"), text), (ipaddress.ip_network("::/0"), text)]
            continue
        try:
            out.append((ipaddress.ip_network(text, strict=False), text))
        except ValueError:
            continue
    return out


def access(addr: str, allow: Iterable[Any], deny: Iterable[Any]) -> dict:
    """{"allowed": bool, "allow": Eintrag|None, "deny": Eintrag|None} für eine (bereinigte) Adresse."""
    ip = ipaddress.ip_address(addr)

    def best(items):
        hits = [(net.prefixlen, text) for net, text in _networks(items) if net.version == ip.version and ip in net]
        return max(hits, default=None)

    a, d = best(allow), best(deny)
    allowed = a is not None and (d is None or a[0] > d[0])
    return {"allowed": allowed, "allow": a[1] if a else None, "deny": d[1] if d and not allowed else None}


# ---------------------------------------------------------------------------
# Lauscht chronyd? – /proc/net/udp{,6}
# ---------------------------------------------------------------------------

def _hex_addr(text: str) -> str | None:
    try:
        if len(text) == 8:
            return socket.inet_ntoa(struct.pack("<I", int(text, 16)))
        if len(text) == 32:
            raw = b"".join(struct.pack("<I", int(text[i:i + 8], 16)) for i in range(0, 32, 8))
            return str(ipaddress.IPv6Address(raw))
    except (ValueError, OSError):
        return None
    return None


def udp_listeners(port: int, paths: Iterable[str] = UDP_PATHS) -> list[str] | None:
    """Lokale Adressen mit einem UDP-Socket auf diesem Port; None, wenn nichts lesbar war."""
    found: list[str] = []
    readable = False
    for path in paths:
        try:
            with open(path, encoding="ascii", errors="replace") as handle:
                readable = True
                next(handle, None)
                for line in handle:
                    parts = line.split()
                    if len(parts) < 4 or ":" not in parts[1]:
                        continue
                    host, _, hexport = parts[1].rpartition(":")
                    try:
                        if int(hexport, 16) != port:
                            continue
                    except ValueError:
                        continue
                    addr = _hex_addr(host)
                    if addr and addr not in found:
                        found.append(addr)
        except OSError:
            continue
    return found if readable else None


# ---------------------------------------------------------------------------
# Die Prüfliste
# ---------------------------------------------------------------------------

def _check(key: str, title: str, status: str, text: str, nxt: str | None = None, *,
           snippets: bool = False, action: str | None = None) -> dict:
    return {"key": key, "title": title, "status": status, "text": text, "next": nxt,
            "snippets": snippets, "action": action}


def _ago(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 90:
        return f"vor {int(seconds)} s"
    if seconds < 5400:
        return f"vor {int(round(seconds / 60))} min"
    if seconds < 172800:
        return f"vor {int(round(seconds / 3600))} h"
    return f"vor {int(round(seconds / 86400))} Tagen"


def _check_access(addr: str, cfg: dict) -> dict:
    title = "Erlaubte Netze"
    result = access(addr, cfg.get("allow_networks") or [], cfg.get("deny_networks") or [])
    if result["deny"]:
        return _check("access", title, FAIL,
                      f"{addr} liegt in „Ausgenommene Netze“ ({result['deny']}) – chronyd antwortet diesem Gerät nicht.",
                      "Unter System → Einstellungen → LAN-Server das Netz aus „Ausgenommene Netze“ (DENY_NETWORKS) nehmen "
                      "oder enger fassen.", action="settings")
    if not result["allowed"]:
        listed = ", ".join(str(n) for n in cfg.get("allow_networks") or []) or "leer"
        return _check("access", title, FAIL,
                      f"{addr} liegt in keinem der erlaubten Netze ({listed}) – chronyd antwortet diesem Gerät nicht.",
                      "Unter System → Einstellungen → LAN-Server das Netz des Geräts zu „Erlaubte Netze“ (ALLOW_NETWORKS) "
                      "hinzufügen.", action="settings")
    text = f"{addr} ist erlaubt (passt zu {result['allow']})."
    if not clientinfo.is_lan(addr):
        text += (" Die Adresse ist öffentlich: Dafür gelten strengere Standards – Begrenzung „streng“ und "
                 "kein Inselbetrieb.")
    return _check("access", title, OK, text)


def _check_listen(addr: str, cfg: dict, listeners: list[str] | None, net_mode: str) -> dict:
    title = "Dienst lauscht"
    port = int(cfg.get("ntp_port") or 123)
    bind = str(cfg.get("bind_address") or "").strip()
    if listeners is None:
        return _check("listen", title, INFO, "Nicht prüfbar: Die Socket-Liste des Systems ist nicht lesbar.")
    if not listeners:
        return _check("listen", title, FAIL,
                      f"Auf UDP-Port {port} lauscht kein Dienst – chronyd nimmt keine NTP-Anfragen an.",
                      "Das Container-Log auf der Diagnose-Seite nennt meist den Grund (Port belegt, "
                      "„Nur auf dieser Adresse lauschen“ mit einer Adresse, die es hier nicht gibt).",
                      action="diagnose")
    version = ipaddress.ip_address(addr).version
    wildcard = {4: "0.0.0.0", 6: "::"}[version]
    same_family = [a for a in listeners if ipaddress.ip_address(a).version == version]
    if wildcard not in listeners and not same_family and "::" not in listeners:
        family = "IPv6" if version == 6 else "IPv4"
        return _check("listen", title, FAIL,
                      f"chronyd lauscht nur auf {', '.join(listeners)} – für ein {family}-Gerät ist keine "
                      f"Adresse offen.",
                      "„Nur auf dieser Adresse lauschen“ (BIND_ADDRESS) leeren oder dem Gerät die Adresse geben, "
                      "auf der chronyd lauscht.", action="settings")
    text = f"chronyd lauscht auf UDP-Port {port}"
    bound_here = bool(bind) and clientinfo.clean_ip(bind) is not None and ipaddress.ip_address(
        clientinfo.clean_ip(bind)).version == version
    text += f" nur auf {bind} – das Gerät muss genau diese Adresse fragen." if bound_here else " (alle Adressen)."
    if port != 123:
        if net_mode == "bridge":
            text += (f" Im Bridge-Netz zählt der Port, den die Compose-Datei nach außen freigibt "
                     f"(z. B. „123:{port}/udp“).")
        else:
            return _check("listen", title, WARN,
                          f"chronyd lauscht auf UDP-Port {port} statt 123. Die meisten Geräte (Windows-Zeitdienst, "
                          "systemd-timesyncd, Router) fragen nur Port 123.",
                          "NTP-Port (NTP_PORT) auf 123 zurückstellen oder den Port im Gerät eintragen, falls es "
                          "das kann.", action="settings")
    if net_mode == "bridge":
        text += " Im Bridge-Netz muss die Compose-Datei den Port freigeben (ports: „123:123/udp“)."
    return _check("listen", title, OK, text)


def _check_server(cfg: dict, tracking: dict) -> dict:
    title = "Server synchron"
    if not tracking:
        return _check("server", title, FAIL, "chronyd läuft nicht – kein Gerät bekommt gerade Zeit.",
                      "Das Container-Log auf der Diagnose-Seite nennt meist den Grund.", action="diagnose")
    if tracking.get("synchronised"):
        stratum = tracking.get("stratum")
        return _check("server", title, OK, f"Der Server ist synchron (Stratum {stratum}) und liefert gültige Zeit.")
    if tracking.get("local_reference"):
        return _check("server", title, WARN,
                      "Inselbetrieb: Keine Quelle erreichbar, der Server liefert seine eigene Uhrzeit "
                      f"(Stratum {tracking.get('stratum')}). Geräte mit weiteren Zeitservern bevorzugen dann diese.",
                      "Auf der Seite Zeitquellen nachsehen, warum keine Quelle erreichbar ist.", action="sources")
    if cfg.get("serve_unsynced"):
        return _check("server", title, WARN,
                      "Der Server ist noch nicht synchron. Bis eine Quelle gewählt ist, beantwortet chronyd "
                      "Anfragen als „nicht synchron“ – Geräte übernehmen diese Zeit nicht.",
                      "Kurz warten (nach dem Start dauert es meist unter einer Minute) oder auf der Seite "
                      "Zeitquellen nachsehen.", action="sources")
    text = ("Der Server ist nicht synchron und „Auch ohne Quelle Zeit ausliefern“ (SERVE_UNSYNCED) ist aus: "
            "chronyd markiert seine Antworten als „nicht synchron“, Geräte übernehmen diese Zeit nicht.")
    nxt = "Auf der Seite Zeitquellen nachsehen, warum keine Quelle erreichbar ist."
    if settings.public_networks(cfg.get("allow_networks")):
        text += (" Weil „Erlaubte Netze“ öffentliche Adressen enthält, ist der Inselbetrieb standardmäßig aus – "
                 "Geräte aus dem Internet sollen dann auf andere Server ausweichen.")
        nxt += " Nur für ein reines LAN den Inselbetrieb ausdrücklich einschalten (SERVE_UNSYNCED=true)."
    else:
        nxt += " Soll das LAN auch ohne Quelle Zeit bekommen: SERVE_UNSYNCED=true."
    return _check("server", title, FAIL, text, nxt, action="sources")


def _check_bridge(addr: str, seen: bool, net_mode: str, gateway: str | None, others: set[str]) -> dict:
    title = "Netzmodus"
    gw_only = bool(gateway) and gateway != addr and gateway in others
    if not seen and gw_only and net_mode != "host":
        return _check("bridge", title, FAIL,
                      f"Von {addr} kommt nichts an, aber Anfragen vom Gateway des Docker-Netzes ({gateway}). "
                      "Im Bridge-Netz schreibt Docker die Absender oft um – das Gerät bekommt vermutlich Zeit, "
                      "erscheint hier aber als Gateway. Erlaubte Netze und Begrenzung gelten dann für diese "
                      "eine Adresse.",
                      "Für echte Adressen den Container im Host-Netz starten (network_mode: host) oder auf "
                      "dem Gerät selbst prüfen, ob es die Zeit übernimmt.")
    if net_mode == "host":
        return _check("bridge", title, OK, "Host-Netz: chronyd sieht die echten Adressen der Geräte.")
    if net_mode == "bridge":
        return _check("bridge", title, INFO,
                      "Bridge-Netz: Ohne Umschreibung durch Docker sieht chronyd die echten Adressen; mit "
                      "Host-Netz (network_mode: host) ist das sicher.")
    return _check("bridge", title, INFO, "Netzmodus nicht erkennbar.")


def _check_seen(addr: str, row: dict | None, entry: dict | None, now: float, port: int = 123) -> tuple[dict, bool]:
    title = "Anfragen angekommen"
    packets = (row or {}).get("ntp_packets") or 0
    requests = (entry or {}).get("requests") or 0
    if not packets and not requests:
        return _check("seen", title, FAIL,
                      f"Von {addr} ist bisher keine NTP-Anfrage angekommen – weder chronyd noch die eigene "
                      "Messung kennen das Gerät.",
                      "Das Gerät auf diesen Server einstellen (Anleitungen unten). Fragt es schon: Firewall "
                      f"zwischen Gerät und Server (UDP-Port {port}) prüfen und ob das Gerät wirklich diese Adresse "
                      "hat (DHCP, wechselnde IPv6-Adressen).", snippets=True), False
    parts = []
    if packets:
        parts.append(f"chronyd: {packets} Anfragen")
    if requests:
        parts.append(f"eigene Messung: {requests} Anfragen")
    last = (entry or {}).get("last_seen")
    last_rx = (row or {}).get("ntp_last_rx")
    age = None
    if isinstance(last_rx, (int, float)):
        age = float(last_rx)
    if isinstance(last, (int, float)):
        age = min(age, now - last) if age is not None else now - last
    text = "Anfragen kommen an (" + ", ".join(parts) + ")"
    text += f", zuletzt {_ago(age)}." if age is not None else "."
    silent = clientinfo.silent_reason(entry, now) if entry else None
    if silent and (age is None or age > clientinfo.SILENT_MIN):
        return _check("seen", title, WARN,
                      f"Das Gerät hat früher gefragt, ist aber verstummt ({silent}).",
                      "Prüfen, ob das Gerät eine neue Adresse bekommen hat oder inzwischen einen anderen "
                      "Zeitserver fragt.", snippets=True), True
    return _check("seen", title, OK, text), True


def _check_drops(cfg: dict, row: dict | None) -> dict:
    title = "Begrenzung (Ratelimit)"
    if not row:
        return _check("ratelimit", title, INFO,
                      "chronyd führt für dieses Gerät gerade keine Zähler (nach jedem Neustart leer).")
    packets = row.get("ntp_packets") or 0
    dropped = row.get("ntp_dropped") or 0
    if not dropped:
        return _check("ratelimit", title, OK, "Keine Anfrage dieses Geräts wurde verworfen.")
    share = dropped / packets if packets else 1.0
    level = (cfg.get("ntp_ratelimit") or "")
    text = (f"{dropped} von {packets} Anfragen wurden durch die Begrenzung verworfen "
            f"(Stufe „{level or '?'}“). Das Gerät fragt zu oft – oder viele Geräte teilen sich diese Adresse "
            "(NAT, Docker-Gateway).")
    nxt = ("Unter System → Einstellungen → LAN-Server „Anfragen begrenzen“ (NTP_RATELIMIT) lockern, z. B. auf „schonend“; "
           "hinter NAT auch „aus“. Ein einzelnes Gerät auf ein längeres Abfrageintervall stellen.")
    return _check("ratelimit", title, FAIL if share >= DROP_FAIL else WARN, text, nxt, action="settings")


def _check_clock(addr: str, entry: dict | None, probe_allowed: bool) -> dict:
    title = "Uhr des Geräts"
    if not entry or not entry.get("requests"):
        return _check("clock", title, INFO,
                      "Die eigene Messung hat von diesem Gerät noch nichts gesehen (aus, gerade gestartet "
                      "oder Bridge-Netz) – die Abweichung ist nicht bekannt.")
    state = entry.get("state")
    ewma = entry.get("ewma")
    if state == clientmon.WRONG_CLOCK:
        return _check("clock", title, FAIL,
                      "Das Gerät fragt, aber seine Uhr liegt mehr als einen Tag daneben – es übernimmt die "
                      "Antworten nicht.",
                      "Auf dem Gerät den Zeitdienst prüfen: Windows korrigiert große Sprünge nur nach "
                      "„w32tm /resync /force“, Linux-Dienste brauchen ggf. einen Neustart (Anleitungen unten).",
                      snippets=True)
    if entry.get("measurable") and isinstance(ewma, (int, float)):
        shown = clientinfo.fmt_offset(ewma)
        if abs(ewma) >= OFFSET_WARN:
            return _check("clock", title, WARN,
                          f"Das Gerät fragt, seine Uhr weicht aber um {shown} ab – es übernimmt die Zeit "
                          "offenbar nicht oder nur langsam.",
                          "Auf dem Gerät den Zeitdienst neu einrichten (Anleitungen unten) und danach den "
                          "Status abfragen.", snippets=True)
        return _check("clock", title, OK, f"Die Uhr des Geräts weicht um {shown} ab – es bekommt Zeit.")
    text = clientinfo.measurable_reason(entry)
    if probe_allowed:
        text += " „Aktiv nachmessen“ kann es noch per NTP-Anfrage versuchen."
    return _check("clock", title, INFO, text)


def run(ip: Any, cfg: dict, *, tracking: dict | None, chrony_row: dict | None, entry: dict | None,
        listeners: list[str] | None, net_mode: str, gateway: str | None, others: Iterable[str] = (),
        now: float | None = None) -> dict:
    """Prüfliste und genau ein Befund. others: alle Adressen, die chronyd oder die Messung gerade kennen."""
    addr = clean_target(ip)
    now = time.time() if now is None else now
    gw = clientinfo.clean_ip(gateway) if gateway else None
    known = {clientinfo.clean_ip(a) for a in others}
    seen_check, seen = _check_seen(addr, chrony_row, entry, now, int(cfg.get("ntp_port") or 123))
    probe_allowed = (clientinfo.is_lan(addr) and not clientinfo.is_link_local(addr) and bool(entry))
    checks = [
        _check_access(addr, cfg),
        _check_listen(addr, cfg, listeners, net_mode),
        _check_server(cfg, tracking or {}),
        _check_bridge(addr, seen, net_mode, gw, known),
        seen_check,
    ]
    if seen:
        checks += [_check_drops(cfg, chrony_row), _check_clock(addr, entry, probe_allowed)]
    else:
        checks += [_check("ratelimit", "Begrenzung (Ratelimit)", SKIP, "Entfällt – keine Anfrage gesehen."),
                   _check("clock", "Uhr des Geräts", SKIP, "Entfällt – keine Anfrage gesehen.")]
    found = (next((c for c in checks if c["status"] == FAIL), None)
             or next((c for c in checks if c["status"] == WARN), None))
    if found:
        verdict = {"key": found["key"], "level": LEVEL[found["status"]], "title": found["title"],
                   "text": found["text"], "next": found["next"], "snippets": found["snippets"],
                   "action": found["action"]}
    else:
        verdict = {"key": "ok", "level": "ok", "title": "Alles in Ordnung",
                   "text": "Dieses Gerät fragt den Server und bekommt Antworten.",
                   "next": "Nichts zu tun. Zeigt das Gerät trotzdem eine falsche Zeit, die Zeitzone im Gerät prüfen.",
                   "snippets": False, "action": None}
    return {"address": addr, "lan": clientinfo.is_lan(addr), "known": seen, "probe_allowed": probe_allowed,
            "checks": checks, "verdict": verdict}
