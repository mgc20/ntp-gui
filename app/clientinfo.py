"""Clients 2.0: Detailseite, Netzüberblick und „Aktiv nachmessen“ (1.4).

Baut auf clientmon.py auf (passive Messung, Verlauf in SQLite) und ergänzt:

  * eigene Namen und Notizen je Client-Adresse (SQLite, Tabelle clientmon_meta) –
    nur lokal; im Diagnosepaket und in Benachrichtigungen ersetzt egress die Namen
    (diagnostics._known_values, Kategorie „name“);
  * Reverse-DNS über den System-Resolver (nur eingeschaltet, 1 s Zeitlimit, zwischengespeichert),
    nur für private Adressen und nie über DoT/DoH oder öffentliche DNS-Server;
  * Hersteller zur MAC-Adresse, wenn eine OUI-Liste im Image liegt (kein Paket nötig);
  * eine VERMUTUNG, welche Client-Software fragt – aus NTP-Version, Poll-Feld,
    Kopffeldern, Abstand der Anfragen, Hersteller und Namen;
  * den Netzüberblick (Histogramm, schlechteste Geräte, verstummte und auffällig oft
    fragende Geräte);
  * eine einzelne aktive NTP-Anfrage an ein Gerät (nur bekannte Clients mit privater
    Adresse, mit Ratenbegrenzung je Gerät und insgesamt).

Alles hier ist reine Standardbibliothek. Nichts davon verlässt die Instanz von selbst.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import struct
import sys
import threading
import time
import unicodedata
from typing import Any, Callable, Iterable

import clientmon

NTP_EPOCH_OFFSET = 2208988800

MAX_NAME = 64
MAX_NOTE = 500

# ---------------------------------------------------------------------------
# Adressen
# ---------------------------------------------------------------------------


def clean_ip(value: Any) -> str | None:
    """Normalisierte IP-Adresse oder None (Allowlist: nur, was ipaddress versteht)."""
    text = str(value or "").strip().strip("[]")
    if not text or len(text) > 45 or "%" in text:
        return None
    try:
        return clientmon._norm_ip(str(ipaddress.ip_address(text)))
    except ValueError:
        return None


# Explizite Liste statt „nicht global“: 6to4 (2002::/16), Teredo (2001::/32), NAT64 und andere
# IANA-Sonderbereiche gelten bei ipaddress als „nicht global“, werden aber über das Internet
# geroutet (6to4/Teredo tragen sogar eine öffentliche IPv4-Adresse in sich).
LAN_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16", "127.0.0.0/8",
    "fc00::/7", "fe80::/10", "::1/128"))


def is_lan(ip: str) -> bool:
    """Private (RFC 1918), CGNAT-, Link-lokale, ULA- oder Loopback-Adresse – nur diese."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return any(addr.version == net.version and addr in net for net in LAN_NETWORKS)


def is_link_local(ip: str) -> bool:
    """IPv6-Link-lokal (fe80::/10): ohne Schnittstelle (Scope-ID) nicht ansprechbar."""
    try:
        addr = ipaddress.ip_address(ip)
        return addr.version == 6 and addr.is_link_local
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Eigene Namen und Notizen
# ---------------------------------------------------------------------------

class MetaError(ValueError):
    """Ungültiger Name oder ungültige Notiz (Text für die Oberfläche)."""


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def _has_control(text: str) -> bool:
    """Steuer- und unsichtbare Formatzeichen: Unicode-Kategorien Cc und Cf (Bidi-Steuerung wie
    U+202E/U+2066, LRM/RLM/ALM, Nullbreite-Zeichen, BOM) sowie Zeilen-/Absatztrenner. Sie
    könnten Text in Liste, Ereignissen und Meldungen umsortieren oder Namen unsichtbar verändern."""
    return bool(_CONTROL.search(text)) or any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in text)


def clean_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if _has_control(text):
        raise MetaError("Der Name darf keine Steuerzeichen enthalten.")
    if len(text) > MAX_NAME:
        raise MetaError(f"Der Name darf höchstens {MAX_NAME} Zeichen lang sein.")
    return text


def clean_note(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\t", " ").strip()
    if _has_control(text.replace("\n", " ")):
        raise MetaError("Die Notiz darf keine Steuerzeichen enthalten.")
    if len(text) > MAX_NOTE:
        raise MetaError(f"Die Notiz darf höchstens {MAX_NOTE} Zeichen lang sein.")
    return text


_META_CACHE: dict[str, Any] = {"t": 0.0, "data": None}
META_TTL = 30.0


def all_meta(fresh: bool = False) -> dict[str, dict]:
    """{ip: {"name", "note", "updated"}} – 30 s zwischengespeichert (Liste, Alarm, Export)."""
    now = time.monotonic()
    if not fresh and _META_CACHE["data"] is not None and now - _META_CACHE["t"] < META_TTL:
        return _META_CACHE["data"]
    try:
        import store
        clientmon._migrate(store)
        rows = store.query("SELECT ip, name, note, updated FROM clientmon_meta")
        data = {ip: {"name": name or "", "note": note or "", "updated": updated}
                for ip, name, note, updated in rows}
    except Exception:  # noqa: BLE001 – Namen sind nur ein Zusatz
        data = {}
    _META_CACHE.update(t=now, data=data)
    return data


def names() -> dict[str, str]:
    """{ip: Name} für alle Clients mit eigenem Namen."""
    return {ip: m["name"] for ip, m in all_meta().items() if m.get("name")}


def export_names() -> list[str]:
    """Eigene Namen für den Datenschutzfilter (egress, Kategorie „name“)."""
    out: list[str] = []
    for meta in all_meta().values():
        if meta.get("name"):
            out.append(meta["name"])
    return sorted(set(out))


def set_meta(ip: Any, name: Any = None, note: Any = None) -> dict:
    """Name/Notiz setzen (None = unverändert, "" = löschen). Beides leer → Eintrag weg."""
    addr = clean_ip(ip)
    if addr is None:
        raise MetaError("Ungültige IP-Adresse.")
    current = all_meta(fresh=True).get(addr, {"name": "", "note": ""})
    new_name = current.get("name", "") if name is None else clean_name(name)
    new_note = current.get("note", "") if note is None else clean_note(note)
    import store
    clientmon._migrate(store)
    with store.transaction() as conn:
        if not new_name and not new_note:
            conn.execute("DELETE FROM clientmon_meta WHERE ip = ?", (addr,))
        else:
            conn.execute("INSERT INTO clientmon_meta(ip, name, note, updated) VALUES(?, ?, ?, ?) "
                         "ON CONFLICT(ip) DO UPDATE SET name=excluded.name, note=excluded.note, "
                         "updated=excluded.updated", (addr, new_name, new_note, time.time()))
    _META_CACHE.update(t=0.0, data=None)
    # Der Filter für Benachrichtigungen merkt sich die bekannten Namen 10 min – ein neuer Name
    # muss sofort gelten, sonst ginge er in der nächsten Meldung im Klartext hinaus.
    notify_mod = sys.modules.get("notify")
    if notify_mod is not None and isinstance(getattr(notify_mod, "_KNOWN", None), dict):
        notify_mod._KNOWN["t"] = float("-inf")
    return {"ip": addr, "name": new_name, "note": new_note}


def label(ip: str, meta: dict | None = None) -> str:
    """Bezeichnung für die lokale Anzeige: eigener Name oder die Adresse.

    Nie in gespeicherte Texte (Ereignistitel) schreiben – dort steht nur die Adresse, die egress
    beim Export pseudonymisiert. Ein Name im Titel bliebe nach Umbenennen/Löschen stehen, und der
    Filter kennt nur die aktuellen Namen."""
    name = ((meta if meta is not None else all_meta()).get(ip) or {}).get("name") or ""
    return name or ip


def client_event_title(row: dict) -> str | None:
    """Titel eines „clients“-Ereignisses neu aus den Daten gebaut (nur Adresse, kein Name) –
    für Export und Diagnosepaket. None, wenn das Ereignis keine gültige Adresse trägt."""
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    addr = clean_ip(data.get("address"))
    if addr is None:
        return None
    offset = data.get("offset")
    value = fmt_offset(offset) if isinstance(offset, (int, float)) and not isinstance(offset, bool) else None
    if row.get("level") == "info":
        return f"Uhr von {addr} wieder im Rahmen ({value})" if value else f"Uhr von {addr} wieder im Rahmen"
    return f"Uhr von {addr} weicht um {value} ab" if value else f"Uhr von {addr} weicht ab"


def without_client_name(row: Any) -> Any:
    """Ereignis für den Export: Titel eines „clients“-Ereignisses ohne frei gewählten Namen
    (Entwicklungsstände von 1.4 schrieben ihn noch hinein)."""
    if not isinstance(row, dict) or row.get("kind") != "clients":
        return row
    title = client_event_title(row)
    if title is None:
        title = "Uhr eines Clients weicht ab" if row.get("level") != "info" else "Uhr eines Clients wieder im Rahmen"
    return {**row, "title": title}


def with_display_titles(rows: list, meta: dict | None = None) -> list:
    """Für die lokale Anzeige: „clients“-Ereignisse bekommen display_title mit dem AKTUELLEN
    eigenen Namen (der gespeicherte Titel enthält nur die Adresse)."""
    out = []
    current: dict | None = meta
    for row in rows:
        if isinstance(row, dict) and row.get("kind") == "clients":
            title = client_event_title(row)
            if title is not None:
                if current is None:
                    current = all_meta()
                addr = clean_ip((row.get("data") or {}).get("address"))
                name = (current.get(addr) or {}).get("name") or ""
                row = {**row, "display_title": title.replace(f"Uhr von {addr} ", f"Uhr von {name} ", 1)
                       if name else title}
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Reverse-DNS (System-Resolver, 1 s, zwischengespeichert)
# ---------------------------------------------------------------------------

RDNS_TIMEOUT = 1.0
RDNS_TTL = 3600.0
RDNS_FAIL_TTL = 600.0
RDNS_PARALLEL = 4
_RDNS: dict[str, tuple[float, str | None]] = {}
_RDNS_LOCK = threading.Lock()
_RDNS_SLOTS = threading.BoundedSemaphore(RDNS_PARALLEL)
_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,62})(?:\.[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,62}))*\.?$")


def _system_resolvers() -> list[str] | None:
    """Adressen der System-Resolver (resolv.conf bzw. ihre Sicherung) – None, wenn unlesbar."""
    try:
        import dnsfwd
        return [host for host, _port in dnsfwd.system_servers()]
    except Exception:  # noqa: BLE001
        return None


def _public_resolver_reason(resolvers: list[str] | None) -> str | None:
    if not resolvers:
        return ("Der System-DNS ist unbekannt (/etc/resolv.conf ohne lesbare nameserver-Zeile) – "
                "deshalb wird nicht nachgeschlagen.")
    public = [r for r in resolvers if not is_lan(r)]
    if public:
        return (f"Der System-DNS enthält einen öffentlichen Server ({public[0]}) – die Frage nach einer "
                "LAN-Adresse ginge ins Internet, deshalb wird nicht nachgeschlagen. Docker trägt z. B. "
                "8.8.8.8 ein, wenn der Host nur 127.0.0.53 kennt.")
    return None


def rdns_allowed(ip: str, cfg: dict, resolvers: Callable[[], list[str] | None] = _system_resolvers) -> str | None:
    """None, wenn nachgeschlagen werden darf – sonst der Grund (für die Oberfläche).

    Nur, wenn eingeschaltet (Standard: aus), nur für private Adressen und nur, wenn JEDER
    Resolver, über den die Frage gehen kann, selbst eine private Adresse hat. Ein lokaler
    Stub (127.0.0.53, Dockers 127.0.0.11) zählt als privat – wohin er weiterfragt, sieht
    ntp-gui nicht; das hast du mit dem Einschalten bewusst in Kauf genommen (Hilfe-Text)."""
    if not cfg.get("clients_rdns", False):
        return "In den Einstellungen ausgeschaltet („Namen der Clients per DNS nachschlagen“)."
    if not is_lan(ip):
        return "Keine private Adresse – die Frage ginge an öffentliche DNS-Server."
    try:
        import dnsfwd
        mode = dnsfwd.effective_mode(cfg)
    except Exception:  # noqa: BLE001
        mode = "system"
    if mode in ("dot", "doh"):
        return ("ntp-gui nutzt DNS-over-TLS/HTTPS – die Frage nach einer LAN-Adresse ginge an einen "
                "öffentlichen Dienst, deshalb wird nicht nachgeschlagen.")
    if mode == "servers":
        servers = [str(s) for s in cfg.get("dns_servers") or []]
        hosts = [dnsfwd.split_host_port(s, 53)[0] for s in servers]
        if not hosts or not all(is_lan(h) for h in hosts):
            return ("Unter den eigenen DNS-Servern ist ein öffentlicher – die Frage nach einer "
                    "LAN-Adresse ginge ins Internet, deshalb wird nicht nachgeschlagen.")
        if not cfg.get("dns_fallback", True):
            return None
        # Mit „Rückfall auf den System-DNS“ kann die Frage auch dort landen.
    return _public_resolver_reason(resolvers())


def reverse_name(ip: str, resolver: Callable[[str], Any] = socket.gethostbyaddr,
                 timeout: float = RDNS_TIMEOUT) -> str | None:
    """PTR-Name über den System-Resolver. Höchstens `timeout` Sekunden, Ergebnis 1 h gemerkt."""
    now = time.monotonic()
    with _RDNS_LOCK:
        hit = _RDNS.get(ip)
        if hit and now < hit[0]:
            return hit[1]
    if not _RDNS_SLOTS.acquire(blocking=False):
        return None  # schon genug Abfragen unterwegs – beim nächsten Laden erneut
    result: dict[str, Any] = {}

    def work() -> None:
        try:
            result["name"] = resolver(ip)[0]
        except (OSError, UnicodeError, IndexError, TypeError):
            result["name"] = None
        finally:
            _RDNS_SLOTS.release()

    thread = threading.Thread(target=work, daemon=True, name="rdns")
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        name = None
        ttl = RDNS_FAIL_TTL
    else:
        raw = result.get("name")
        name = str(raw).rstrip(".") if raw and _HOSTNAME.match(str(raw)) else None
        if name and name == ip:
            name = None
        ttl = RDNS_TTL if name else RDNS_FAIL_TTL
    with _RDNS_LOCK:
        if len(_RDNS) > 4000:
            _RDNS.clear()
        _RDNS[ip] = (time.monotonic() + ttl, name)
    return name


# ---------------------------------------------------------------------------
# Hersteller zur MAC (nur, wenn eine OUI-Liste vorhanden ist)
# ---------------------------------------------------------------------------

OUI_PATHS = ("/config/oui.txt", "/usr/share/ieee-data/oui.txt", "/usr/share/hwdata/oui.txt",
             "/usr/share/misc/oui.txt", "/var/lib/ieee-data/oui.txt", "/usr/share/nmap/nmap-mac-prefixes")
_OUI: dict[str, Any] = {"loaded": False, "table": {}, "path": None}
_OUI_LOCK = threading.Lock()
_OUI_LINE = re.compile(r"^\s*([0-9A-Fa-f]{2})[-:]?([0-9A-Fa-f]{2})[-:]?([0-9A-Fa-f]{2})\s+(?:\((?:hex|base 16)\)\s*)?(.+?)\s*$")
OUI_MAX_BYTES = 16 * 1024 * 1024


def parse_oui(lines: Iterable[str]) -> dict[str, str]:
    """IEEE-oui.txt („00-00-0C   (hex)  Cisco“) oder nmap-mac-prefixes („00000C Cisco“)."""
    table: dict[str, str] = {}
    for line in lines:
        if line.startswith("#"):
            continue
        m = _OUI_LINE.match(line)
        if not m:
            continue
        key = (m.group(1) + m.group(2) + m.group(3)).upper()
        vendor = " ".join(m.group(4).split())[:80]
        if vendor and key not in table and not _has_control(vendor):
            table[key] = vendor
    return table


def _load_oui(paths: Iterable[str] = OUI_PATHS) -> None:
    for path in paths:
        try:
            if os.path.getsize(path) > OUI_MAX_BYTES:
                continue
            with open(path, encoding="utf-8", errors="replace") as handle:
                table = parse_oui(handle)
        except OSError:
            continue
        if table:
            _OUI.update(table=table, path=path)
            break
    _OUI["loaded"] = True


def mac_info(mac: str | None, paths: Iterable[str] = OUI_PATHS) -> dict | None:
    """{"mac", "vendor"|None, "random": bool, "source"} – random = lokal verwaltete Adresse
    (Smartphones und Laptops wählen sie aus Datenschutzgründen je WLAN zufällig)."""
    if not mac or not re.match(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$", mac):
        return None
    first = int(mac[:2], 16)
    random_mac = bool(first & 0x02)
    with _OUI_LOCK:
        if not _OUI["loaded"]:
            _load_oui(paths)
    vendor = None if random_mac else _OUI["table"].get(mac.replace(":", "")[:6].upper())
    return {"mac": mac, "vendor": vendor, "random": random_mac, "vendor_list": bool(_OUI["table"])}


# ---------------------------------------------------------------------------
# Vermutete Client-Software
# ---------------------------------------------------------------------------

def _poll_text(poll: Any) -> str:
    if poll == 0:
        return "Poll-Feld 0 (nicht gesetzt)"
    if isinstance(poll, int) and -6 <= poll <= 17:
        return f"Poll-Feld {poll} (2^{poll} = {_fmt_seconds(2.0 ** poll)})"
    return f"Poll-Feld {poll}"


def _fmt_seconds(value: float) -> str:
    if value < 1:
        return f"{value * 1000:.0f} ms"
    if value < 120:
        return f"{value:.0f} s"
    if value < 7200:
        return f"{value / 60:.0f} min"
    return f"{value / 3600:.0f} h".replace(".", ",")


_IOT_VENDORS = ("espressif", "tuya", "shelly", "allterco", "sonoff", "itead", "raspberry", "texas instruments",
                "silicon labs", "nordic", "realtek semiconductor", "azurewave", "murata", "hui zhou gaoshengda",
                "beijing xiaomi", "xiaomi", "signify", "philips lighting", "ubiquiti", "tp-link", "avm")
_APPLE_HINT = re.compile(r"(?i)(iphone|ipad|macbook|imac|mac-?mini|apple-?tv|homepod|\bmbp\b|\bapple\b)")
_WINDOWS_HINT = re.compile(r"(?i)^(desktop|laptop|win)-[a-z0-9]{4,}|windows")
_IOT_HINT = re.compile(r"(?i)(esp[-_]?(32|8266)?[-_][0-9a-f]{4,}|esp32|esp8266|shelly|tasmota|sonoff|tuya|wled|"
                       r"espressif|hue-?bridge|\bplug\b)")
_ANDROID_HINT = re.compile(r"(?i)(android|galaxy|pixel)")


def guess_software(entry: dict, mac: dict | None = None, hostnames: Iterable[str] = ()) -> dict:
    """Vermutung, welche Software hinter den Anfragen steckt. Kein Beweis – nur Indizien.

    Rückgabe: {"candidates": [{"label", "confidence": "wahrscheinlich"|"möglich",
    "reasons": [...]}], "basis": [...]} – höchstens drei Kandidaten, bester zuerst.
    """
    version = entry.get("version")
    poll = entry.get("poll")
    state = entry.get("state")
    bare = entry.get("bare")
    stratum = entry.get("stratum")
    interval = entry.get("interval")
    vendor = ((mac or {}).get("vendor") or "").lower()
    names = " ".join(h for h in hostnames if h)
    scores: dict[str, list] = {}

    def add(key: str, points: int, reason: str) -> None:
        scores.setdefault(key, [0, []])
        scores[key][0] += points
        scores[key][1].append(reason)

    poll_ok = isinstance(poll, int) and not isinstance(poll, bool)
    # Windows-Zeitdienst (w32time): NTP-Version 3, Poll-Feld meist 10 … 15 (17 = eine Woche).
    if version == 3 and poll_ok and 10 <= poll <= 17:
        add("windows", 3, f"NTP-Version 3 und {_poll_text(poll)} – typisch für den Windows-Zeitdienst")
    elif version == 3:
        add("windows", 1, "NTP-Version 3 – nutzen vor allem Windows und ältere SNTP-Clients")
        add("sntp", 1, "NTP-Version 3 – nutzen vor allem Windows und ältere SNTP-Clients")
    if version in (1, 2):
        add("sntp", 3, f"NTP-Version {version} – sehr alter oder sehr einfacher Client")
    if state == clientmon.OBFUSCATED:
        add("chrony", 3, "Sendezeit absichtlich verschleiert (Zufallszahl) – machen chrony, NTPsec und OpenNTPD")
        if poll_ok and 6 <= poll <= 10:
            add("chrony", 1, f"{_poll_text(poll)} – Standardbereich von chrony")
    if state == clientmon.NO_TIMESTAMP:
        add("sntp", 3, "Sendezeit leer (Nullen) – typisch für schlanke SNTP-Clients in Mikrocontrollern")
    if state in (clientmon.OK, clientmon.WRONG_CLOCK) and version == 4:
        if bare:
            add("timesyncd", 2, "NTP-Version 4, nur Sendezeit gefüllt (Stratum, Referenz leer) – "
                                "so fragen systemd-timesyncd und andere schlanke Clients")
            add("sntp", 1, "Nur Sendezeit gefüllt – schlanker SNTP-Client")
            add("apple", 1, "Nur Sendezeit gefüllt – fragen auch Apple-Geräte so")
            if isinstance(interval, (int, float)) and 30 <= interval <= 2100:
                add("timesyncd", 1, f"Abstand der Anfragen etwa {_fmt_seconds(interval)} – im Bereich "
                                    "von systemd-timesyncd (32 s … 34 min)")
        elif isinstance(stratum, int) and stratum > 0:
            add("ntpd", 3, f"Echte Sendezeit und eigenes Stratum ({stratum}) im Kopf – macht der "
                           "klassische ntpd (oder ein anderer vollständiger NTP-Client)")
            if poll_ok and 6 <= poll <= 10:
                add("ntpd", 1, f"{_poll_text(poll)} – Standardbereich von ntpd")
    if isinstance(interval, (int, float)) and interval >= 3000 and bare is not False:
        add("sntp", 1, f"Fragt nur etwa alle {_fmt_seconds(interval)} – typisch für IoT-Geräte "
                       "(ESP-IDF fragt standardmäßig stündlich)")
    if vendor:
        if "apple" in vendor:
            add("apple", 4, f"Hersteller laut MAC: {mac.get('vendor')}")
        elif "microsoft" in vendor:
            add("windows", 2, f"Hersteller laut MAC: {mac.get('vendor')}")
        elif any(v in vendor for v in _IOT_VENDORS):
            add("sntp", 3, f"Hersteller laut MAC: {mac.get('vendor')} – baut vor allem Funkmodule/IoT-Technik")
    if (mac or {}).get("random"):
        add("apple", 1, "Zufällige (private) MAC-Adresse – nutzen iPhone, Android und Windows im WLAN")
        add("mobile", 2, "Zufällige (private) MAC-Adresse – nutzen iPhone, Android und Windows im WLAN")
    if names:
        if _APPLE_HINT.search(names):
            add("apple", 3, "Name deutet auf ein Apple-Gerät hin")
        if _WINDOWS_HINT.search(names):
            add("windows", 3, "Name sieht nach einem Windows-PC aus (DESKTOP-…/LAPTOP-…)")
        if _IOT_HINT.search(names):
            add("sntp", 3, "Name deutet auf ein IoT-Gerät hin (ESP, Shelly, Tasmota …)")
        if _ANDROID_HINT.search(names):
            add("mobile", 2, "Name deutet auf ein Android-Gerät hin")

    labels = {
        "windows": "Windows (Zeitdienst w32time)",
        "timesyncd": "Linux mit systemd-timesyncd",
        "chrony": "chrony, NTPsec oder OpenNTPD (Linux/BSD, Router, NAS)",
        "ntpd": "ntpd (klassischer NTP-Dienst, z. B. ältere NAS und Router)",
        "sntp": "Einfacher SNTP-Client (ESP32/ESP8266, IoT, Kameras, Drucker)",
        "apple": "Apple (macOS, iOS, tvOS)",
        "mobile": "Smartphone oder Laptop",
    }
    ranked = sorted(scores.items(), key=lambda kv: -kv[1][0])
    candidates = []
    for key, (points, reasons) in ranked[:3]:
        if points < 2 and candidates:
            continue
        candidates.append({"key": key, "label": labels[key],
                           "confidence": "wahrscheinlich" if points >= 4 else "möglich",
                           "reasons": reasons})
    basis = []
    if version is not None:
        basis.append(f"NTP-Version {version}")
    if poll is not None:
        basis.append(_poll_text(poll))
    if isinstance(interval, (int, float)):
        basis.append(f"Abstand der Anfragen ≈ {_fmt_seconds(interval)}")
    return {"candidates": candidates, "basis": basis}


# ---------------------------------------------------------------------------
# Netzüberblick
# ---------------------------------------------------------------------------

BINS = (("lt1ms", "< 1 ms", 0.001), ("1-10ms", "1–10 ms", 0.01), ("10-100ms", "10–100 ms", 0.1),
        ("0.1-1s", "0,1–1 s", 1.0), ("gt1s", "> 1 s", float("inf")))
CHATTY_INTERVAL = 8.0
CHATTY_MIN_REQUESTS = 5
CHATTY_RECENT = 600.0
SILENT_FACTOR = 3.0
SILENT_MAX = 86400.0
SILENT_MIN = 120.0
LIST_LIMIT = 10


def expected_interval(entry: dict) -> float | None:
    """Gemessener typischer Abstand, sonst das Poll-Feld (2^poll) als Ersatz."""
    interval = entry.get("interval")
    if isinstance(interval, (int, float)) and interval > 0:
        return float(interval)
    poll = entry.get("poll")
    if isinstance(poll, int) and not isinstance(poll, bool) and 4 <= poll <= 17:
        return float(2 ** poll)
    return None


def silent_reason(entry: dict, now: float) -> str | None:
    """Warum ein Gerät als verstummt gilt – oder None."""
    last = entry.get("last_seen")
    if not isinstance(last, (int, float)) or (entry.get("requests") or 0) < 2:
        return None
    age = now - last
    if age > SILENT_MAX:
        return "seit über 24 h keine Anfrage"
    expected = expected_interval(entry)
    if expected and age > max(SILENT_FACTOR * expected, SILENT_MIN):
        return f"fragt sonst etwa alle {_fmt_seconds(expected)}, seit {_fmt_seconds(age)} still"
    return None


def overview(clients: dict[str, dict], meta: dict[str, dict] | None = None,
             now: float | None = None) -> dict:
    """Netzüberblick aus clientmon.status()["clients"]."""
    now = time.time() if now is None else now
    meta = meta or {}
    bins = {key: 0 for key, _label, _limit in BINS}
    bins["wrong"] = 0
    unmeasurable = 0
    measured = []
    silent = []
    chatty = []

    def item(ip: str, entry: dict, **extra) -> dict:
        out = {"address": ip, "name": (meta.get(ip) or {}).get("name") or None,
               "offset": entry.get("ewma"), "state": entry.get("state"),
               "last_seen": entry.get("last_seen"), "interval": entry.get("interval")}
        out.update(extra)
        return out

    for ip, entry in clients.items():
        if not isinstance(entry, dict):
            continue
        reason = silent_reason(entry, now)
        if reason:
            silent.append(item(ip, entry, reason=reason))
        interval = entry.get("interval")
        last = entry.get("last_seen")
        if (isinstance(interval, (int, float)) and 0 < interval < CHATTY_INTERVAL
                and (entry.get("requests") or 0) >= CHATTY_MIN_REQUESTS
                and isinstance(last, (int, float)) and now - last < CHATTY_RECENT):
            chatty.append(item(ip, entry, rate_per_min=60.0 / interval))
        if not entry.get("measurable") or not isinstance(entry.get("ewma"), (int, float)):
            unmeasurable += 1
            continue
        if reason and now - (last or 0) > SILENT_MAX:
            continue  # alte Werte verzerren das „jetzt“
        value = abs(entry["ewma"])
        if entry.get("state") == clientmon.WRONG_CLOCK or value > clientmon.ABSURD:
            bins["wrong"] += 1
        else:
            for key, _label, limit in BINS:
                if value < limit:
                    bins[key] += 1
                    break
        measured.append(item(ip, entry))
    worst = sorted(measured, key=lambda c: -abs(c["offset"]))[:5]
    silent.sort(key=lambda c: -(c.get("last_seen") or 0))
    chatty.sort(key=lambda c: c.get("interval") or 0)
    labels = [{"key": key, "label": label_text} for key, label_text, _ in BINS]
    labels.append({"key": "wrong", "label": "falsche Uhr"})
    return {
        "histogram": [{**b, "count": bins[b["key"]]} for b in labels],
        "measured": len(measured), "unmeasurable": unmeasurable, "total": len(clients),
        "worst": worst,
        "silent": silent[:LIST_LIMIT], "silent_total": len(silent),
        "chatty": chatty[:LIST_LIMIT], "chatty_total": len(chatty),
        "limits": {"chatty_interval": CHATTY_INTERVAL, "silent_factor": SILENT_FACTOR,
                   "silent_max": SILENT_MAX},
    }


# ---------------------------------------------------------------------------
# Messbar? – mit Grund
# ---------------------------------------------------------------------------

def measurable_reason(entry: dict) -> str:
    state = entry.get("state")
    total = entry.get("requests") or 0
    measured = entry.get("count") or 0
    obf = entry.get("obfuscated") or 0
    nots = entry.get("no_timestamp") or 0
    counts = f"{measured} von {total} Anfragen mit echter Uhrzeit"
    if state == clientmon.OK:
        return f"Das Gerät schickt seine echte Uhrzeit mit ({counts})."
    if state == clientmon.WRONG_CLOCK:
        return (f"Das Gerät schickt eine Uhrzeit, die gleichbleibend mehr als einen Tag danebenliegt – "
                f"die Uhr ist wirklich falsch gestellt ({counts}).")
    if state == clientmon.OBFUSCATED:
        return (f"Das Gerät schreibt absichtlich eine Zufallszahl statt seiner Uhrzeit in die Anfrage "
                f"({obf} von {total} Anfragen) – gutes Verhalten gegen Mitlesen, nur messen lässt es sich so nicht.")
    if state == clientmon.NO_TIMESTAMP:
        return f"Das Gerät schickt keine Uhrzeit mit, nur Nullen ({nots} von {total} Anfragen)."
    return "Noch keine Anfrage gesehen."


# ---------------------------------------------------------------------------
# Aktiv nachmessen: eine NTP-Anfrage an das Gerät
# ---------------------------------------------------------------------------

PROBE_TIMEOUT = 2.0
PROBE_PER_CLIENT = 30.0       # Sekunden zwischen zwei Messungen desselben Geräts
PROBE_GLOBAL = 10             # höchstens so viele Messungen …
PROBE_WINDOW = 60.0           # … in diesem Zeitraum
_PROBE_LOCK = threading.Lock()
_PROBE_LAST: dict[str, float] = {}
_PROBE_RECENT: list[float] = []


LINK_LOCAL_PROBE = ("Link-lokale Adresse – Nachmessen nicht möglich: Für fe80::-Adressen bräuchte die Anfrage "
                    "die Netzwerkschnittstelle, und die merkt sich die passive Messung nicht.")


class ProbeLimited(Exception):
    def __init__(self, text: str, retry_after: float) -> None:
        super().__init__(text)
        self.retry_after = retry_after


def _ntp_ts(raw: bytes) -> float:
    sec, frac = struct.unpack("!II", raw)
    return sec - NTP_EPOCH_OFFSET + frac / 2**32


def parse_server_reply(data: bytes, nonce: bytes) -> dict | None:
    """Antwort im Server-Modus (4) mit unserer Zufalls-Sendezeit als Origin – sonst None."""
    if len(data) < 48:
        return None
    lvm, stratum = data[0], data[1]
    if lvm & 7 != 4 or data[24:32] != nonce:
        return None
    if stratum == 0:  # Kiss-o'-Death oder nicht synchron
        return {"kod": data[12:16].decode("ascii", "replace").strip("\x00 "), "stratum": 0,
                "leap": lvm >> 6, "version": (lvm >> 3) & 7}
    return {"stratum": stratum, "leap": lvm >> 6, "version": (lvm >> 3) & 7,
            "rx": _ntp_ts(data[32:40]), "tx": _ntp_ts(data[40:48])}


def _reset_probe_limits() -> None:
    with _PROBE_LOCK:
        _PROBE_LAST.clear()
        _PROBE_RECENT.clear()


def _reserve(ip: str, now: float) -> None:
    with _PROBE_LOCK:
        last = _PROBE_LAST.get(ip)
        if last is not None and now - last < PROBE_PER_CLIENT:
            wait = PROBE_PER_CLIENT - (now - last)
            raise ProbeLimited(f"Dieses Gerät wurde gerade erst gemessen – erneut in {wait:.0f} s.", wait)
        _PROBE_RECENT[:] = [t for t in _PROBE_RECENT if now - t < PROBE_WINDOW]
        if len(_PROBE_RECENT) >= PROBE_GLOBAL:
            wait = PROBE_WINDOW - (now - _PROBE_RECENT[0])
            raise ProbeLimited(f"Höchstens {PROBE_GLOBAL} Messungen pro Minute – erneut in {wait:.0f} s.", wait)
        _PROBE_LAST[ip] = now
        _PROBE_RECENT.append(now)
        if len(_PROBE_LAST) > 4000:
            for key, t in list(_PROBE_LAST.items()):
                if now - t >= PROBE_PER_CLIENT:
                    del _PROBE_LAST[key]


def ntp_query(ip: str, port: int = 123, timeout: float = PROBE_TIMEOUT) -> dict | None:
    """Eine Anfrage im Client-Modus (Sendezeit zufällig – verrät nichts über unsere Uhr)."""
    nonce = os.urandom(8)
    packet = b"\x23" + bytes(39) + nonce
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.connect((ip, port))  # nur Antworten genau dieses Geräts annehmen
        t1 = time.time()
        m1 = time.monotonic()
        sock.send(packet)
        deadline = m1 + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            sock.settimeout(left)
            try:
                data = sock.recv(512)
            except (socket.timeout, ConnectionRefusedError):
                return None
            m4 = time.monotonic()
            reply = parse_server_reply(data, nonce)
            if reply is not None:
                break
        t4 = t1 + (m4 - m1)
        if "rx" in reply:
            reply["offset"] = ((reply["rx"] - t1) + (reply["tx"] - t4)) / 2
            reply["rtt"] = max(0.0, (t4 - t1) - (reply["tx"] - reply["rx"]))
            del reply["rx"], reply["tx"]
        else:
            reply["rtt"] = m4 - m1
        return reply
    except OSError:
        return None
    finally:
        sock.close()


def probe(ip: Any, known: Callable[[str], bool], query: Callable[..., dict | None] = ntp_query,
          now: float | None = None) -> dict:
    """„Aktiv nachmessen“: nur bekannte Clients mit privater Adresse; Ratenbegrenzung."""
    addr = clean_ip(ip)
    if addr is None:
        raise MetaError("Ungültige IP-Adresse.")
    if not is_lan(addr):
        raise MetaError("Nachmessen geht nur bei privaten Adressen im LAN.")
    if is_link_local(addr):
        raise MetaError(LINK_LOCAL_PROBE)
    if not known(addr):
        raise MetaError("Dieses Gerät hat diesen Server bisher nicht gefragt – nachgemessen werden nur bekannte Clients.")
    _reserve(addr, time.monotonic() if now is None else now)
    reply = query(addr)
    stamp = time.time()
    if reply is None:
        return {"ip": addr, "t": stamp, "answered": False,
                "text": "antwortet nicht auf NTP (normal für die meisten Geräte)"}
    if reply.get("kod") is not None:
        return {"ip": addr, "t": stamp, "answered": True, "offset": None, "rtt": reply.get("rtt"),
                "stratum": 0, "text": f"antwortet, hat aber selbst keine gültige Zeit (Stratum 0, „{reply['kod']}“)"}
    return {"ip": addr, "t": stamp, "answered": True, "offset": reply.get("offset"), "rtt": reply.get("rtt"),
            "stratum": reply.get("stratum"), "leap": reply.get("leap"), "version": reply.get("version"),
            "text": "antwortet auf NTP – das Gerät ist selbst ein Zeitserver"}


# ---------------------------------------------------------------------------
# Detailseite
# ---------------------------------------------------------------------------

def detail(ip: Any, cfg: dict, since: float | None = None,
           resolver: Callable[[str], Any] = socket.gethostbyaddr) -> dict | None:
    addr = clean_ip(ip)
    if addr is None:
        raise MetaError("Ungültige IP-Adresse.")
    entry = clientmon.client(addr)
    meta = all_meta().get(addr, {})
    try:
        history = clientmon.samples(addr, since)
    except Exception:  # noqa: BLE001
        history = []
    if entry is None and not history and not meta:
        return None
    entry = dict(entry or {})
    # Zuerst gesehen: auch ein älterer gespeicherter Messpunkt zählt (Tabelle nach Verlust neu begonnen).
    if history and (not isinstance(entry.get("first_seen"), (int, float)) or history[0][0] < entry["first_seen"]):
        entry["first_seen"] = history[0][0]
    mac = mac_info(entry.get("mac"))
    rdns_reason = rdns_allowed(addr, cfg)
    rdns = reverse_name(addr, resolver) if rdns_reason is None else None
    software = guess_software(entry, mac, [rdns or "", meta.get("name") or ""])
    out = {
        "address": addr,
        "entry": {k: v for k, v in entry.items() if k != "mac"},
        "samples": history,
        "name": meta.get("name") or "",
        "note": meta.get("note") or "",
        "rdns": rdns,
        "rdns_skipped": rdns_reason,
        "mac": mac,
        "measurable_reason": measurable_reason(entry),
        "software": software,
        "silent": silent_reason(entry, time.time()) if entry else None,
        "probe_allowed": is_lan(addr) and not is_link_local(addr) and bool(entry),
        "probe_blocked": LINK_LOCAL_PROBE if is_link_local(addr) else None,
        "retention_days": clientmon.SAMPLE_RETENTION // 86400,
    }
    return out


def fmt_offset(value: float) -> str:
    """Abweichung deutsch formatiert, mit Vorzeichen: „+12,3 ms“, „−1,25 s“, „+3 Tage“."""
    sign = "+" if value >= 0 else "−"
    a = abs(value)
    if a >= 86400:
        days = a / 86400
        text = f"{days:.0f} Tage" if days >= 2 else f"{days:.1f} Tage"
    elif a >= 1:
        text = f"{a:.2f} s"
    elif a >= 0.01:
        text = f"{a * 1000:.0f} ms"
    else:
        text = f"{a * 1000:.1f} ms"
    return sign + text.replace(".", ",")
