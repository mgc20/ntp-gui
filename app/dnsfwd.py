"""DNS für ntp-gui: kleiner Weiterleiter auf 127.0.0.1:53 im Container (1.4).

Warum: Schreibt der DNS-Server im LAN (AdGuard Home, Pi-hole, dnsmasq) Zeitserver-
Namen wie pool.ntp.org auf ntp-gui um („Zeitserver erzwingen“) und fragt ntp-gui
selbst diesen DNS-Server, fragt chronyd am Ende sich selbst – eine Schleife. Mit
diesem Weiterleiter löst ntp-gui seine eigenen Namen (Zeitquellen, NTS-KE, die
Prüfung „Zeitserver erzwingen“) über eigene Server auf:

  system   Standard: nichts ändert sich, der Container nutzt seinen DNS wie bisher.
  servers  klassisches DNS an feste IP-Adressen (UDP, bei abgeschnittener Antwort TCP).
  dot      DNS-over-TLS (RFC 7858), Name[:Port]; Zertifikat wird gegen die System-CAs
           und den Namen geprüft (SNI), optional mit fester IP (dns_pin).
  doh      DNS-over-HTTPS (RFC 8484), POST mit application/dns-message.

Der Supervisor (docker/entrypoint.sh) startet ``dnsfwd.py serve`` als optionalen
Dienst (Neustart mit Backoff). Sobald der Weiterleiter lauscht, zeigt
/etc/resolv.conf auf 127.0.0.1 (das Original wird gesichert und beim Wechsel auf
„system“, beim Beenden und nach einem Absturz zurückgeschrieben).

Sicherheit, bewusst einfach gehalten:
  * lauscht nur auf 127.0.0.1 (und ::1) und beantwortet nur Absender aus Loopback;
  * leitet die Anfrage Byte für Byte weiter – nur die ID wird für den Upstream durch
    eine zufällige ersetzt und in der Antwort zurückgetauscht; keine eigene Rekursion;
  * Antworten werden geprüft (QR-Bit, ID, gleiche Frage) und sind auf 64 KB begrenzt;
  * höchstens MAX_WORKERS gleichzeitige Anfragen, MAX_TCP gleichzeitige TCP-Verbindungen;
  * kleiner Cache, der die TTL respektiert (höchstens 5 min, negative Antworten 30 s);
  * fallen alle eigenen Server aus, fragt er die ursprünglichen System-Resolver
    (abschaltbar) und meldet das als Ereignis (Art „dns“); diese unverschlüsselten
    Antworten cacht er nur wenige Sekunden. Eine Anfrage, die über einen Upstream oder
    den System-DNS wieder bei ihm landet (z. B. Docker-DNS → 127.0.0.1, gleiche ID und
    Frage), erkennt er und beantwortet sie mit SERVFAIL statt endlos zu kreisen;
    gleichzeitige gleiche Fragen gehen nur einmal hinaus.

Nur Standardbibliothek; Import ohne Seiteneffekte (confgen und server.py nutzen die
reinen Funktionen).
"""

from __future__ import annotations

import errno
import http.client
import ipaddress
import json
import os
import secrets
import signal
import socket
import ssl
import struct
import sys
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUN_DIR = os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")
RESOLV_CONF = os.environ.get("NTPGUI_RESOLV_CONF", "/etc/resolv.conf")
STATUS_NAME = "dns.json"
READY_NAME = "dnsfwd.ready"
EVENTS_NAME = "events.jsonl"
MARKER = "# ntp-gui: dnsfwd"

MODES = ("system", "servers", "dot", "doh")
MODE_LABELS = {"system": "System-DNS", "servers": "eigene DNS-Server", "dot": "DNS-over-TLS",
               "doh": "DNS-over-HTTPS"}
LISTEN_HOSTS = ("127.0.0.1", "::1")
DNS_PORT = 53
DOT_PORT = 853

MAX_MSG = 65535            # größte DNS-Nachricht (TCP-Längenpräfix: 16 Bit)
UDP_DEFAULT = 512          # ohne EDNS darf eine UDP-Antwort nicht größer sein
UDP_MAX = 4096             # mehr verspricht der Weiterleiter Clients per UDP nicht
UPSTREAM_TIMEOUT = 2.0     # je Upstream-Versuch
QUERY_DEADLINE = 4.5       # gesamte Anfrage (glibc wartet 5 s, bevor es neu fragt)
FALLBACK_MIN = 1.5         # so viel Zeit bekommt der System-DNS mindestens
DOWN_SECONDS = 30.0        # ein ausgefallener Upstream wird so lange übersprungen
DOWN_AFTER = 3             # so viele Zeitüberschreitungen in Folge, bis er als ausgefallen gilt
FALLBACK_CACHE_TTL = 5     # Antworten des System-DNS (Rückfall) nur kurz cachen
LOOP_RECENT = 600.0        # so lange gilt eine erkannte Schleife als „aktuell“
MAX_WORKERS = 64
MAX_TCP = 16
TCP_IDLE = 10.0
TCP_MAX_QUERIES = 100
CACHE_MAX = 512
CACHE_MAX_TTL = 300
CACHE_NEG_TTL = 30
STATUS_EVERY = 10.0
EVENT_REPEAT = 300.0       # gleicher Zustandswechsel höchstens alle 5 min als Ereignis
HEALTH_FIRST = 20.0        # erste Erreichbarkeitsprobe aller eigenen Server nach dem Start
HEALTH_EVERY = 900.0       # danach alle 15 min (eine A-Anfrage je Server)
BOOTSTRAP_MIN_TTL = 60
BOOTSTRAP_MAX_TTL = 3600

TYPE_A, TYPE_AAAA, TYPE_OPT = 1, 28, 41
FLAG_QR, FLAG_TC = 0x8000, 0x0200
RCODE_SERVFAIL, RCODE_NOTIMP, RCODE_FORMERR, RCODE_REFUSED = 2, 4, 1, 5


def _log(message: str) -> None:
    print(f"[dns] {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Einstellungen → Upstreams (reine Funktionen)
# ---------------------------------------------------------------------------

def _mode_list(cfg: dict, mode: str) -> list[str]:
    key = {"servers": "dns_servers", "dot": "dns_dot", "doh": "dns_doh"}.get(mode)
    return [str(item) for item in (cfg.get(key) or [])] if key else []


def effective_mode(cfg: dict) -> str:
    """Der Modus, der wirklich gilt: ohne eingetragene Server bleibt es beim System-DNS."""
    mode = cfg.get("dns_mode") or "system"
    if mode not in MODES:
        return "system"
    if mode != "system" and not _mode_list(cfg, mode):
        return "system"
    return mode


def config_warnings(cfg: dict) -> list[str]:
    mode = cfg.get("dns_mode") or "system"
    if mode in MODES and mode != "system" and not _mode_list(cfg, mode):
        return [f"WARNUNG: DNS-Modus „{mode}“ ohne eingetragene Server – ntp-gui nutzt weiter den System-DNS."]
    return []


def split_host_port(text: str, default_port: int) -> tuple[str, int]:
    """'1.2.3.4', '1.2.3.4:5353', '[fd00::1]:53', 'fd00::1', 'dns.quad9.net:853' → (host, port)."""
    text = str(text).strip()
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") else default_port
        return host, port
    if text.count(":") == 1:
        host, _, port = text.partition(":")
        return host, int(port)
    return text, default_port


def pins_from(cfg: dict) -> dict[str, list[str]]:
    pins: dict[str, list[str]] = {}
    for item in cfg.get("dns_pin") or []:
        name, _, ip = str(item).partition("=")
        if name and ip:
            pins.setdefault(name.lower().rstrip("."), []).append(ip)
    return pins


def doh_label(url: str) -> str:
    """Nur Schema + Host – der Pfad kann eine Konto-Kennung enthalten (z. B. NextDNS)."""
    parts = urlsplit(url)
    return f"https://{parts.netloc}/…" if parts.path not in ("", "/", "/dns-query") else f"https://{parts.netloc}{parts.path}"


# ---------------------------------------------------------------------------
# Minimale Wire-Format-Hilfen (nur Kopf, Frage, Längen und TTL – keine Rekursion)
# ---------------------------------------------------------------------------

class DnsError(ValueError):
    """Nachricht ist kein gültiges DNS-Paket."""


def header(msg: bytes) -> tuple[int, int, int, int, int, int]:
    if len(msg) < 12:
        raise DnsError("zu kurz")
    return struct.unpack("!HHHHHH", msg[:12])


def skip_name(msg: bytes, off: int) -> int:
    for _ in range(128):
        if off >= len(msg):
            raise DnsError("Name abgeschnitten")
        length = msg[off]
        if length == 0:
            return off + 1
        if length & 0xC0 == 0xC0:
            if off + 2 > len(msg):
                raise DnsError("Zeiger abgeschnitten")
            return off + 2
        if length & 0xC0:
            raise DnsError("unbekanntes Label")
        off += 1 + length
    raise DnsError("Name zu lang")


def question_end(msg: bytes) -> int:
    _id, _flags, qd, _an, _ns, _ar = header(msg)
    off = 12
    for _ in range(qd):
        off = skip_name(msg, off) + 4
        if off > len(msg):
            raise DnsError("Frage abgeschnitten")
    return off


def question(msg: bytes) -> bytes:
    """Fragebereich (Name, Typ, Klasse) klein geschrieben – zum Vergleichen."""
    return msg[12:question_end(msg)].lower()


def records(msg: bytes) -> list[dict]:
    """Alle Einträge aus Antwort-, Autoritäts- und Zusatzbereich (Abschnitt, Typ, Klasse,
    TTL samt Position, Daten-Position)."""
    _id, _flags, _qd, an, ns, ar = header(msg)
    off = question_end(msg)
    out = []
    for section, count in (("an", an), ("ns", ns), ("ar", ar)):
        for _ in range(count):
            off = skip_name(msg, off)
            if off + 10 > len(msg):
                raise DnsError("Eintrag abgeschnitten")
            rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", msg[off:off + 10])
            if off + 10 + rdlen > len(msg):
                raise DnsError("Daten abgeschnitten")
            out.append({"section": section, "type": rtype, "class": rclass, "ttl": ttl,
                        "ttl_off": off + 4, "rdata": off + 10, "rdlen": rdlen})
            off += 10 + rdlen
    return out


def cache_ttl(msg: bytes) -> int:
    """Wie lange eine Antwort in den Cache darf (0 = gar nicht)."""
    try:
        _id, flags, _qd, an, _ns, _ar = header(msg)
        rrs = records(msg)
    except DnsError:
        return 0
    if flags & FLAG_TC:
        return 0
    rcode = flags & 0xF
    ttls = [r["ttl"] for r in rrs if r["section"] in ("an", "ns") and r["type"] != TYPE_OPT]
    if rcode == 0 and an:
        return max(0, min(min(ttls), CACHE_MAX_TTL))
    if rcode in (0, 3):  # NODATA bzw. NXDOMAIN
        return max(0, min(min(ttls), CACHE_NEG_TTL)) if ttls else CACHE_NEG_TTL
    return 0


def with_id(msg: bytes, ident: int) -> bytes:
    return struct.pack("!H", ident) + msg[2:]


def reply_code(query: bytes, rcode: int) -> bytes | None:
    """Kurze Antwort mit Fehlercode (SERVFAIL, NOTIMP …) und der Frage – oder None."""
    try:
        ident, flags, qd, _an, _ns, _ar = header(query)
        end = question_end(query)
    except DnsError:
        return None
    flags = FLAG_QR | (flags & 0x7900) | 0x0080 | rcode  # Opcode + RD übernehmen, RA setzen
    return struct.pack("!HHHHHH", ident, flags, qd, 0, 0, 0) + query[12:end]


def udp_limit(query: bytes) -> int:
    """Größte UDP-Antwort, die der Client annimmt (EDNS-Angabe, sonst 512)."""
    try:
        for rr in records(query):
            if rr["type"] == TYPE_OPT:
                return max(UDP_DEFAULT, min(rr["class"], UDP_MAX))
    except DnsError:
        pass
    return UDP_DEFAULT


def truncated(response: bytes) -> bytes:
    """Antwort mit TC-Bit und nur der Frage: Der Client fragt dann per TCP."""
    ident, flags, qd, _an, _ns, _ar = header(response)
    end = question_end(response)
    return struct.pack("!HHHHHH", ident, flags | FLAG_TC, qd, 0, 0, 0) + response[12:end]


def patch_ttls(msg: bytes, elapsed: int) -> bytes:
    """TTLs um die Zeit im Cache verringern (OPT-Einträge haben keine TTL)."""
    data = bytearray(msg)
    for rr in records(msg):
        if rr["type"] == TYPE_OPT:
            continue
        struct.pack_into("!I", data, rr["ttl_off"], max(0, rr["ttl"] - elapsed))
    return bytes(data)


def valid_response(query: bytes, response: bytes) -> bool:
    try:
        qid = header(query)[0]
        rid, flags, *_rest = header(response)
        return (len(response) <= MAX_MSG and bool(flags & FLAG_QR) and rid == qid
                and question(response) == question(query))
    except DnsError:
        return False


def build_query(name: str, qtype: int) -> bytes:
    labels = [part for part in name.rstrip(".").split(".") if part]
    body = b"".join(bytes([len(p)]) + p.encode("ascii") for p in labels) + b"\0"
    return struct.pack("!HHHHHH", secrets.randbits(16), 0x0100, 1, 0, 0, 0) + body + struct.pack("!HH", qtype, 1)


def addresses(msg: bytes, qtype: int) -> tuple[list[str], int]:
    """A-/AAAA-Adressen aus dem Antwortbereich und die kleinste TTL."""
    out, ttl = [], BOOTSTRAP_MAX_TTL
    for rr in records(msg):
        if rr["section"] != "an" or rr["type"] != qtype:
            continue
        raw = msg[rr["rdata"]:rr["rdata"] + rr["rdlen"]]
        if qtype == TYPE_A and len(raw) == 4:
            out.append(str(ipaddress.IPv4Address(raw)))
        elif qtype == TYPE_AAAA and len(raw) == 16:
            out.append(str(ipaddress.IPv6Address(raw)))
        else:
            continue
        ttl = min(ttl, rr["ttl"])
    return out, ttl


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

class UpstreamError(OSError):
    """Upstream hat nicht (brauchbar) geantwortet."""


class BootstrapError(UpstreamError):
    """Die Adresse eines DoT-/DoH-Servers ließ sich nicht ermitteln."""


def hard_failure(exc: BaseException) -> bool:
    """Fehler, der den ganzen Server betrifft (abgelehnt, unerreichbar, TLS, Adresse unbekannt) –
    anders als eine Zeitüberschreitung, die auch nur an einem langsamen Namen liegen kann."""
    if isinstance(exc, (BootstrapError, ConnectionError, ssl.SSLError)):
        return True
    return getattr(exc, "errno", None) in (errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH)


def rcode_of(msg: bytes) -> int:
    return header(msg)[1] & 0xF


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise UpstreamError("Zeitüberschreitung")
    return left


def _family(ip: str) -> int:
    return socket.AF_INET6 if ":" in ip else socket.AF_INET


def udp_exchange(ip: str, port: int, query: bytes, deadline: float) -> bytes:
    with socket.socket(_family(ip), socket.SOCK_DGRAM) as sock:
        sock.connect((ip, port))  # verbunden: Pakete anderer Absender kommen gar nicht an
        sock.settimeout(_remaining(deadline))
        sock.send(query)
        while True:
            sock.settimeout(_remaining(deadline))
            try:
                data = sock.recv(MAX_MSG)
            except socket.timeout:
                raise UpstreamError("Zeitüberschreitung") from None
            if valid_response(query, data):
                return data


def _recv_exact(sock, count: int, deadline: float) -> bytes:
    buf = bytearray()
    while len(buf) < count:
        sock.settimeout(_remaining(deadline))
        try:
            chunk = sock.recv(count - len(buf))
        except socket.timeout:
            raise UpstreamError("Zeitüberschreitung") from None
        if not chunk:
            raise UpstreamError("Verbindung vorzeitig beendet")
        buf += chunk
    return bytes(buf)


def stream_exchange(sock, query: bytes, deadline: float) -> bytes:
    """Eine Anfrage über TCP/TLS (2-Byte-Längenpräfix, RFC 1035 4.2.2 / RFC 7858)."""
    sock.settimeout(_remaining(deadline))
    sock.sendall(struct.pack("!H", len(query)) + query)
    (length,) = struct.unpack("!H", _recv_exact(sock, 2, deadline))
    if length < 12:
        raise UpstreamError("Antwort zu kurz")
    data = _recv_exact(sock, length, deadline)
    if not valid_response(query, data):
        raise UpstreamError("Antwort passt nicht zur Anfrage")
    return data


def tcp_exchange(ip: str, port: int, query: bytes, deadline: float) -> bytes:
    with socket.create_connection((ip, port), timeout=_remaining(deadline)) as sock:
        return stream_exchange(sock, query, deadline)


def plain_exchange(ip: str, port: int, query: bytes, deadline: float) -> bytes:
    """UDP; ist die Antwort abgeschnitten (TC), dieselbe Frage per TCP."""
    data = udp_exchange(ip, port, query, deadline)
    if header(data)[1] & FLAG_TC:
        return tcp_exchange(ip, port, query, deadline)
    return data


def tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()  # System-CAs, Namensprüfung, CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS zu einer festen IP, Zertifikat und SNI für den Namen aus der URL."""

    def __init__(self, host: str, port: int, ip: str, context: ssl.SSLContext, timeout: float) -> None:
        super().__init__(host, port, context=context, timeout=timeout)
        self._pin_ip = ip
        self._pin_ctx = context

    def connect(self) -> None:
        sock = socket.create_connection((self._pin_ip, self.port), self.timeout)
        try:
            self.sock = self._pin_ctx.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


# ---------------------------------------------------------------------------
# Upstreams
# ---------------------------------------------------------------------------

class Upstream:
    """Ein eigener DNS-Server mit Statistik."""

    proto = "udp"

    def __init__(self, label: str) -> None:
        self.label = label
        self.ok = 0
        self.fail = 0
        self.last_ok: float | None = None
        self.last_error = ""
        self.last_error_t: float | None = None
        self.rtt_ms: float | None = None
        self.down_until = 0.0  # time.monotonic(): ein Sprung der Uhr verlängert keinen Ausfall
        self.streak = 0  # Fehlschläge in Folge
        self.reported_down = False  # „nicht erreichbar“ schon gemeldet (Ereignis je Server)

    def exchange(self, query: bytes, deadline: float) -> bytes:  # pragma: no cover - abstrakt
        raise NotImplementedError

    def public(self) -> dict:
        # down_until ist monotonic (für die Dauer); nach außen als Uhrzeit (Epoch) wie die übrigen Zeiten.
        left = self.down_until - time.monotonic()
        return {"label": self.label, "proto": self.proto, "ok": self.ok, "fail": self.fail,
                "last_ok": self.last_ok, "last_error": self.last_error, "last_error_t": self.last_error_t,
                "rtt_ms": self.rtt_ms, "down_until": time.time() + left if left > 0 else None,
                "streak": self.streak}


class PlainUpstream(Upstream):
    proto = "udp"

    def __init__(self, ip: str, port: int = DNS_PORT) -> None:
        super().__init__(f"[{ip}]:{port}" if ":" in ip and port != DNS_PORT else
                         (ip if port == DNS_PORT else f"{ip}:{port}"))
        self.ip, self.port = ip, port

    def exchange(self, query: bytes, deadline: float) -> bytes:
        return plain_exchange(self.ip, self.port, query, deadline)


class _NamedUpstream(Upstream):
    """Gemeinsames für DoT und DoH: Adresse fest (dns_pin) oder per System-DNS ermittelt."""

    def __init__(self, label: str, host: str, port: int, pins: list[str],
                 bootstrap: "Bootstrap", context: ssl.SSLContext | None) -> None:
        super().__init__(label)
        self.host, self.port, self.pins = host, port, list(pins)
        self.bootstrap = bootstrap
        self.context = context or tls_context()
        self.bootstrap_failed = False

    def is_pinned(self) -> bool:
        """Adresse steht fest (IP statt Name oder dns_pin) – kein System-DNS nötig."""
        try:
            ipaddress.ip_address(self.host)
            return True
        except ValueError:
            return bool(self.pins)

    def targets(self, deadline: float) -> list[str]:
        try:
            ipaddress.ip_address(self.host)
            return [self.host]
        except ValueError:
            pass
        if self.pins:
            return self.pins[:2]
        ips = self.bootstrap.resolve(self.host, deadline)
        self.bootstrap_failed = not ips
        if not ips:
            raise BootstrapError(f"Adresse von {self.host} unbekannt (System-DNS liefert sie nicht – "
                                 "unter „Feste Adressen für DoT/DoH“ eintragen)")
        return ips[:2]

    def public(self) -> dict:
        data = super().public()
        data.update(host=self.host, pinned=self.is_pinned(), bootstrap_failed=self.bootstrap_failed)
        return data


class DotUpstream(_NamedUpstream):
    proto = "dot"

    def exchange(self, query: bytes, deadline: float) -> bytes:
        error: Exception | None = None
        for ip in self.targets(deadline):
            try:
                with socket.create_connection((ip, self.port), timeout=_remaining(deadline)) as raw:
                    with self.context.wrap_socket(raw, server_hostname=self.host) as tls:
                        return stream_exchange(tls, query, deadline)
            except (OSError, ssl.SSLError, DnsError) as exc:
                error = exc
        raise UpstreamError(str(error) or "keine Verbindung")


class DohUpstream(_NamedUpstream):
    proto = "doh"

    def __init__(self, url: str, pins: list[str], bootstrap: "Bootstrap",
                 context: ssl.SSLContext | None) -> None:
        parts = urlsplit(url)
        host = parts.hostname or ""
        super().__init__(doh_label(url), host, parts.port or 443, pins, bootstrap, context)
        self.path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")

    def exchange(self, query: bytes, deadline: float) -> bytes:
        error: Exception | None = None
        for ip in self.targets(deadline):
            conn = _PinnedHTTPS(self.host, self.port, ip, self.context, _remaining(deadline))
            # Harte Frist für die ganze Anfrage: Ein Server, der Kopf oder Antwort Byte für Byte
            # tröpfeln lässt, hielte sonst einen Worker beliebig lange (der Socket-Timeout gilt nur
            # je recv). Bei Fristende wird die Verbindung von außen beendet.
            guard: list[socket.socket] = []
            timer = threading.Timer(max(0.0, deadline - time.monotonic()), _abort_connection, args=(guard,))
            timer.daemon = True
            timer.start()
            try:
                conn.request("POST", self.path, body=query, headers={
                    "Content-Type": "application/dns-message", "Accept": "application/dns-message"})
                conn.sock.settimeout(_remaining(deadline))
                # Eigenes Duplikat des Sockets: getresponse() gibt conn.sock bei „Connection: close“
                # ab, und der Deskriptor darf nicht neu vergeben sein, wenn die Frist abläuft.
                guard.append(socket.socket(fileno=os.dup(conn.sock.fileno())))
                resp = conn.getresponse()
                if resp.status != 200:  # auch keine Weiterleitungen (3xx)
                    raise UpstreamError(f"HTTP {resp.status}")
                ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/dns-message":
                    raise UpstreamError(f"falscher Inhaltstyp „{ctype[:40]}“")
                length = resp.getheader("Content-Length")
                if length and (not length.isdigit() or int(length) > MAX_MSG):
                    raise UpstreamError("Antwort zu groß")
                data = _read_body(resp, deadline)
                if not valid_response(query, data):
                    raise UpstreamError("Antwort passt nicht zur Anfrage")
                return data
            except (OSError, ssl.SSLError, http.client.HTTPException, DnsError) as exc:
                error = exc
            finally:
                timer.cancel()
                timer.join()
                for dup in guard:
                    dup.close()
                conn.close()
            if time.monotonic() >= deadline:
                raise UpstreamError("Zeitüberschreitung")
        raise UpstreamError(str(error) or "keine Verbindung")


def _abort_connection(guard: list[socket.socket]) -> None:
    """Frist abgelaufen: Verbindung beenden – ein hängendes recv kehrt sofort zurück.
    Über ein eigenes Duplikat, damit der TLS-Zustand nicht aus diesem Thread berührt wird."""
    for sock in guard:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _read_body(resp: http.client.HTTPResponse, deadline: float) -> bytes:
    """Antwortkörper in kleinen Stücken, vor jedem Stück die Frist prüfen."""
    buf = bytearray()
    while True:
        _remaining(deadline)
        chunk = resp.read1(16384)
        if not chunk:
            return bytes(buf)
        buf += chunk
        if len(buf) > MAX_MSG:
            raise UpstreamError("Antwort zu groß")


class Flight:
    """Eine Frage, die gerade hinausgeht; gleiche Fragen warten auf ihre Antwort."""

    __slots__ = ("done", "data")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.data: bytes | None = None


class Inflight:
    """Was dieser Weiterleiter gerade selbst fragt – zwei Dinge:

    * Schleifen: (zufällige ID, Frage) jeder Anfrage, die gerade an einen Upstream, den
      System-DNS oder den Bootstrap geht. Kommt genau diese Anfrage hier wieder an, hat der
      Gefragte (z. B. Docker-DNS mit „dns: 127.0.0.1“, behält die ID beim Weiterreichen)
      diesen Weiterleiter gefragt – eine Schleife, die sofort mit SERVFAIL endet.
    * Bündeln: Fragen mehrere Clients gleichzeitig dasselbe, geht die Frage nur einmal
      hinaus; die anderen warten auf diese Antwort. So gibt es weder Fehlalarme („Schleife“
      bei zwei gleichen Anfragen) noch ein Auffächern, falls ein Gefragter die ID ändert."""

    def __init__(self) -> None:
        self._ids: dict[tuple[int, bytes], int] = {}
        self._flights: dict[bytes, Flight] = {}
        self._lock = threading.Lock()

    def is_loop(self, ident: int, key: bytes) -> bool:
        with self._lock:
            return bool(self._ids.get((ident, key)))

    def track(self, ident: int, key: bytes) -> None:
        with self._lock:
            self._ids[(ident, key)] = self._ids.get((ident, key), 0) + 1

    def untrack(self, ident: int, key: bytes) -> None:
        with self._lock:
            left = self._ids.get((ident, key), 1) - 1
            if left <= 0:
                self._ids.pop((ident, key), None)
            else:
                self._ids[(ident, key)] = left

    def join(self, key: bytes) -> tuple[Flight, bool]:
        """(Flug, True) für den Ersten, der fragt; (laufender Flug, False) für alle weiteren."""
        with self._lock:
            flight = self._flights.get(key)
            if flight is not None:
                return flight, False
            flight = self._flights[key] = Flight()
            return flight, True

    def land(self, key: bytes, flight: Flight, data: bytes | None) -> None:
        with self._lock:
            if self._flights.get(key) is flight:
                del self._flights[key]
        flight.data = data
        flight.done.set()


class Bootstrap:
    """Löst die Namen der DoT/DoH-Server über die System-Resolver auf (ohne getaddrinfo –
    das liefe über /etc/resolv.conf und damit über diesen Weiterleiter selbst)."""

    def __init__(self, servers: Callable[[], list[tuple[str, int]]], inflight: Inflight | None = None) -> None:
        self.servers = servers
        self.inflight = inflight or Inflight()
        self._cache: dict[str, tuple[float, list[str]]] = {}
        self._lock = threading.Lock()

    def resolve(self, host: str, deadline: float) -> list[str]:
        host = host.lower().rstrip(".")
        with self._lock:
            hit = self._cache.get(host)
            if hit and hit[0] > time.monotonic():
                return list(hit[1])
        found: list[str] = []
        ttl = BOOTSTRAP_MAX_TTL
        for qtype in (TYPE_A, TYPE_AAAA):
            for ip, port in self.servers():
                try:
                    query = build_query(host, qtype)
                except (UnicodeError, ValueError):
                    return []
                key, ident = question(query), header(query)[0]
                self.inflight.track(ident, key)
                try:
                    data = plain_exchange(ip, port, query, min(deadline, time.monotonic() + 1.5))
                    if rcode_of(data) in (RCODE_SERVFAIL, RCODE_REFUSED):
                        continue
                    ips, rr_ttl = addresses(data, qtype)
                except (OSError, DnsError):
                    continue
                finally:
                    self.inflight.untrack(ident, key)
                found += [a for a in ips if a not in found]
                ttl = min(ttl, rr_ttl)
                break
            if found and qtype == TYPE_A:
                break  # IPv4 genügt; AAAA nur, wenn es keine A-Adresse gibt
        if found:
            with self._lock:
                self._cache[host] = (time.monotonic() + max(BOOTSTRAP_MIN_TTL, ttl), found)
        return found


def build_upstreams(cfg: dict, bootstrap: Bootstrap, context: ssl.SSLContext | None = None) -> list[Upstream]:
    mode = effective_mode(cfg)
    pins = pins_from(cfg)
    ups: list[Upstream] = []
    for item in _mode_list(cfg, mode):
        if mode == "servers":
            ip, port = split_host_port(item, DNS_PORT)
            ups.append(PlainUpstream(ip, port))
        elif mode == "dot":
            host, port = split_host_port(item, DOT_PORT)
            up = DotUpstream(host if port == DOT_PORT else f"{host}:{port}", host, port,
                             pins.get(host.lower(), []), bootstrap, context)
            ups.append(up)
        elif mode == "doh":
            ups.append(DohUpstream(item, pins.get((urlsplit(item).hostname or "").lower(), []),
                                   bootstrap, context))
    return ups


# ---------------------------------------------------------------------------
# resolv.conf
# ---------------------------------------------------------------------------

def backup_path() -> str:
    import settings
    return os.environ.get("NTPGUI_RESOLV_BACKUP", os.path.join(settings.DATA_DIR, "resolv.conf.system"))


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(65536)
    except OSError:
        return None


def _write_in_place(path: str, text: str) -> None:
    """Docker bindet /etc/resolv.conf als Datei ein – ein rename darüber scheitert (EBUSY),
    deshalb wird der Inhalt ersetzt statt die Datei."""
    with open(path, "r+", encoding="utf-8") as handle:
        handle.seek(0)
        handle.write(text)
        handle.truncate()


_WRITE_LOCK = threading.Lock()  # Status-Schreiber (Worker + Hauptschleife) nacheinander


def _atomic_write(path: str, text: str, mode: int | None = None) -> None:
    """Schreibt über eine eigene Temp-Datei je Aufruf und ersetzt dann atomar. Ein fester Name
    „path.tmp“ ließe zwei gleichzeitige Schreiber dieselbe Datei kürzen und überschreiben
    (halbe Datei veröffentlicht, der andere bekommt FileNotFoundError)."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with _WRITE_LOCK:
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(tmp, 0o600 if mode is None else mode)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _write_private(path: str, text: str) -> None:
    _atomic_write(path, text, 0o600)


def nameservers(text: str | None, port: int = DNS_PORT) -> list[tuple[str, int]]:
    """nameserver-Zeilen einer resolv.conf – ohne diesen Weiterleiter selbst."""
    out: list[tuple[str, int]] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            addr = parts[1].split("%")[0]
            try:
                ip = str(ipaddress.ip_address(addr))
            except ValueError:
                continue
            if ip in LISTEN_HOSTS and port == DNS_PORT:
                continue
            if (ip, DNS_PORT) not in out:
                out.append((ip, DNS_PORT))
    return out


def render_local(original: str | None) -> str:
    keep = [line for line in (original or "").splitlines()
            if line.split()[:1] and line.split()[0] in ("search", "domain", "options")]
    return "\n".join([MARKER + " – DNS für ntp-gui (Einstellungen → DNS für ntp-gui).",
                      "# Das Original liegt gesichert daneben und kommt beim Modus „system“ zurück.",
                      "nameserver 127.0.0.1", *keep]) + "\n"


def point_local(resolv: str = RESOLV_CONF, backup: str | None = None) -> dict:
    """resolv.conf auf 127.0.0.1 umstellen (Original sichern). Ergebnis für dns.json."""
    backup = backup or backup_path()
    current = _read(resolv)
    if current is None:
        return {"state": "error", "message": f"{resolv} nicht lesbar"}
    if MARKER in current:
        if _read(backup) is None:
            return {"state": "local", "message": "Original-resolv.conf unbekannt – Rückfall auf den "
                                                  "System-DNS nicht möglich"}
        return {"state": "local", "message": ""}
    try:
        _write_private(backup, current)
    except OSError as exc:
        return {"state": "error", "message": f"Sicherung nicht möglich: {exc.strerror or exc}"}
    try:
        _write_in_place(resolv, render_local(current))
    except OSError as exc:
        readonly = exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
        return {"state": "readonly" if readonly else "error",
                "message": f"{resolv} lässt sich nicht ändern ({exc.strerror or exc})"}
    return {"state": "local", "message": ""}


def restore_system(resolv: str = RESOLV_CONF, backup: str | None = None) -> dict:
    """Original-resolv.conf zurückschreiben, falls sie von uns stammt."""
    backup = backup or backup_path()
    current = _read(resolv)
    if current is None or MARKER not in current:
        return {"state": "system", "message": ""}
    original = _read(backup)
    if original is None or MARKER in original:
        return {"state": "error", "message": "resolv.conf zeigt noch auf 127.0.0.1, die Sicherung fehlt – "
                                             "Container neu erstellen (docker compose up -d --force-recreate)"}
    try:
        _write_in_place(resolv, original)
    except OSError as exc:
        return {"state": "error", "message": f"{resolv} lässt sich nicht zurückschreiben ({exc.strerror or exc})"}
    try:
        os.unlink(backup)
    except OSError:
        pass
    return {"state": "system", "message": ""}


def system_servers(resolv: str = RESOLV_CONF, backup: str | None = None) -> list[tuple[str, int]]:
    """Die ursprünglichen Resolver: aus der Sicherung, solange resolv.conf auf uns zeigt."""
    current = _read(resolv)
    if current is not None and MARKER in current:
        return nameservers(_read(backup or backup_path()))
    return nameservers(current)


# ---------------------------------------------------------------------------
# Weiterleiter
# ---------------------------------------------------------------------------

class Forwarder:
    """Beantwortet eine Anfrage: Cache → eigene Server → System-DNS → SERVFAIL."""

    def __init__(self, mode: str, upstreams: list[Upstream],
                 fallback: Callable[[], list[tuple[str, int]]] | None = None, *,
                 use_fallback: bool = True, cache: bool = True,
                 on_change: Callable[[str, str, dict], None] | None = None,
                 inflight: Inflight | None = None,
                 clock: Callable[[], float] = time.time,
                 on_upstream: Callable[[str, str, str], None] | None = None) -> None:
        self.mode = mode
        self.on_upstream = on_upstream
        self.upstreams = upstreams
        self.fallback = fallback or (lambda: [])
        self.use_fallback = use_fallback
        self.cache_on = cache
        self.on_change = on_change
        self.clock = clock
        self.state = "starting"
        self.state_since = clock()
        self.stats = {"queries": 0, "answered": 0, "servfail": 0, "cache_hits": 0,
                      "fallback": 0, "fallback_last": None, "loops": 0, "loop_last": None,
                      "coalesced": 0, "dropped": 0}
        self._cache: dict[bytes, tuple[float, float, bytes]] = {}
        self.inflight = inflight or Inflight()
        self._lock = threading.Lock()

    # --- Zustand -----------------------------------------------------------
    def _set_state(self, state: str, detail: dict) -> None:
        with self._lock:
            if state == self.state:
                return
            old, self.state, self.state_since = self.state, state, self.clock()
        if self.on_change:
            try:
                self.on_change(old, state, detail)
            except Exception:  # Ereignis/Status darf nie eine Antwort verhindern
                pass

    # --- Cache -------------------------------------------------------------
    def _cache_get(self, key: bytes, ident: int) -> bytes | None:
        if not self.cache_on:
            return None
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if not hit:
                return None
            expires, stored, data = hit
            if expires <= now:
                del self._cache[key]
                return None
            self.stats["cache_hits"] += 1
        try:
            return with_id(patch_ttls(data, int(now - stored)), ident)
        except DnsError:
            return None

    def _cache_put(self, key: bytes, data: bytes, max_ttl: int = CACHE_MAX_TTL) -> None:
        if not self.cache_on:
            return
        ttl = min(cache_ttl(data), max_ttl)
        if ttl <= 0:
            return
        now = time.monotonic()
        with self._lock:
            if len(self._cache) >= CACHE_MAX:
                for old in sorted(self._cache, key=lambda k: self._cache[k][0])[:CACHE_MAX // 8 or 1]:
                    self._cache.pop(old, None)
            self._cache[key] = (now + ttl, now, data)

    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    # --- Anfrage -----------------------------------------------------------
    def resolve(self, query: bytes) -> bytes | None:
        try:
            ident, flags, qd, *_rest = header(query)
            qkey = question(query)
        except DnsError:
            return None  # kein DNS – keine Antwort
        with self._lock:
            self.stats["queries"] += 1
        if flags & FLAG_QR:
            return None
        if (flags >> 11) & 0xF != 0:
            return reply_code(query, RCODE_NOTIMP)
        if qd != 1:
            return reply_code(query, RCODE_FORMERR)
        cached = self._cache_get(query[2:], ident)
        if cached is not None:
            with self._lock:
                self.stats["answered"] += 1
            return cached
        if self.inflight.is_loop(ident, qkey):
            # Genau diese Anfrage (gleiche ID, gleiche Frage) hat dieser Weiterleiter gerade
            # selbst gestellt – der Gefragte reicht sie hierher zurück. Schleife.
            with self._lock:
                self.stats["loops"] += 1
                self.stats["loop_last"] = self.clock()
                self.stats["servfail"] += 1
            return reply_code(query, RCODE_SERVFAIL)
        flight, leader = self.inflight.join(qkey)
        if not leader:
            # Dieselbe Frage ist schon unterwegs: auf deren Antwort warten statt erneut fragen.
            flight.done.wait(QUERY_DEADLINE)
            with self._lock:
                self.stats["coalesced"] += 1
                self.stats["answered" if flight.data is not None else "servfail"] += 1
            return with_id(flight.data, ident) if flight.data is not None else reply_code(query, RCODE_SERVFAIL)
        data: bytes | None = None
        try:
            data = self._resolve_out(query, qkey)
        finally:
            self.inflight.land(qkey, flight, data)
        if data is None:
            return reply_code(query, RCODE_SERVFAIL)
        return with_id(data, ident)

    def _all_down(self) -> bool:
        now = time.monotonic()
        return all(u.down_until > now for u in self.upstreams)

    def _resolve_out(self, query: bytes, qkey: bytes) -> bytes | None:
        """Fragt die eigenen Server, dann (falls erlaubt) den System-DNS. Antwort mit der
        zufälligen Upstream-ID oder None (→ SERVFAIL)."""
        deadline = time.monotonic() + QUERY_DEADLINE
        upstream_id = secrets.randbits(16)
        upstream_query = with_id(query, upstream_id)
        self.inflight.track(upstream_id, qkey)
        try:
            return self._resolve_tracked(query, upstream_query, deadline)
        finally:
            self.inflight.untrack(upstream_id, qkey)

    def _resolve_tracked(self, query: bytes, upstream_query: bytes, deadline: float) -> bytes | None:
        errors: list[str] = []
        now = time.monotonic()
        candidates = [u for u in self.upstreams if u.down_until <= now]
        if not candidates and not (self.use_fallback and self.fallback()):
            candidates = list(self.upstreams)
        for up in candidates:
            left = deadline - time.monotonic() - (FALLBACK_MIN if self.use_fallback else 0)
            if left <= 0.2:
                break
            data, text = self._ask_one(up, upstream_query, time.monotonic() + min(UPSTREAM_TIMEOUT, left))
            if data is None:
                errors.append(f"{up.label}: {text}")
                continue
            with self._lock:
                self.stats["answered"] += 1
            self._cache_put(query[2:], data)
            self._set_state("ok", {"upstream": up.label})
            return data

        if self.use_fallback:
            data = self._ask_system(upstream_query, deadline)
            if data is not None:
                with self._lock:
                    self.stats["answered"] += 1
                    self.stats["fallback"] += 1
                    self.stats["fallback_last"] = self.clock()
                # Unverschlüsselt und evtl. umgeschrieben: nur kurz cachen, damit nach der
                # Rückkehr der eigenen Server sofort wieder sie gefragt werden.
                self._cache_put(query[2:], data, FALLBACK_CACHE_TTL)
                if self._all_down():
                    self._set_state("fallback", {"errors": errors[:4]})
                return data
        with self._lock:
            self.stats["servfail"] += 1
        if self._all_down():
            self._set_state("failing", {"errors": errors[:4]})
        return None

    def _ask_one(self, up: Upstream, query: bytes, deadline: float) -> tuple[bytes | None, str]:
        """Ein Upstream, eine Anfrage: Statistik und Ausfallzustand pflegen.
        Wechselt der Server zwischen „nicht erreichbar“ und „antwortet wieder“, meldet
        on_upstream das (Ereignis je Server, 1.5) – bisher gab es nur den Gesamtzustand."""
        started = time.monotonic()
        try:
            data = up.exchange(query, deadline)
            if rcode_of(data) == RCODE_REFUSED:
                raise UpstreamError("Anfrage abgelehnt (REFUSED)")
        except (OSError, ssl.SSLError, DnsError, http.client.HTTPException, ValueError) as exc:
            text = " ".join(str(exc).split())[:160] or exc.__class__.__name__
            went_down = False
            with self._lock:
                up.fail += 1
                up.streak += 1
                up.last_error, up.last_error_t = text, self.clock()
                # Eine einzelne Zeitüberschreitung kann an einem langsamen Namen liegen –
                # erst mehrere in Folge (oder ein harter Fehler) gelten als Ausfall.
                if hard_failure(exc) or up.streak >= DOWN_AFTER:
                    up.down_until = time.monotonic() + DOWN_SECONDS
                    if not up.reported_down:
                        up.reported_down = went_down = True
            if went_down:
                self._upstream_changed(up, "down", text)
            return None, text
        with self._lock:
            up.ok += 1
            up.streak = 0
            up.last_ok = self.clock()
            up.rtt_ms = round((time.monotonic() - started) * 1000, 1)
            up.down_until = 0.0
            came_back, up.reported_down = up.reported_down, False
        if came_back:
            self._upstream_changed(up, "up", "")
        return data, ""

    def _upstream_changed(self, up: Upstream, state: str, error: str) -> None:
        if self.on_upstream:
            try:
                self.on_upstream(up.label, state, error)
            except Exception:  # Ereignis darf nie eine Antwort verhindern
                pass

    def health_check(self, name: str, deadline_each: float = UPSTREAM_TIMEOUT) -> dict:
        """Fragt JEDEN eigenen Server einmal nach name (A-Eintrag), unabhängig vom Cache.

        chronyd löst seine Namen selten auf (beim Start, nach Ausfällen) – ohne diese Probe
        wüsste niemand, ob der zweite Server überhaupt antwortet, bis er gebraucht wird.
        Nur im Modus servers/dot/doh (die Server hat der Nutzer selbst eingetragen)."""
        query = build_query(name, TYPE_A)
        results = {}
        for up in self.upstreams:
            data, text = self._ask_one(up, query, time.monotonic() + deadline_each)
            results[up.label] = {"ok": data is not None, "error": text or None}
        with self._lock:
            self.stats["health_last"] = self.clock()
            self.stats["health_ok"] = sum(1 for r in results.values() if r["ok"])
            self.stats["health_total"] = len(results)
        if results and any(r["ok"] for r in results.values()):
            self._set_state("ok", {"upstream": next(l for l, r in results.items() if r["ok"])})
        return results

    def _ask_system(self, query: bytes, deadline: float) -> bytes | None:
        """System-DNS der Reihe nach; SERVFAIL/REFUSED zählt als Fehlschlag (nächster Server)."""
        servers = self.fallback()
        end = max(deadline, time.monotonic() + FALLBACK_MIN)
        for ip, port in servers:
            try:
                data = plain_exchange(ip, port, query, min(end, time.monotonic() + FALLBACK_MIN))
                if rcode_of(data) in (RCODE_SERVFAIL, RCODE_REFUSED):
                    continue
                return data
            except (OSError, DnsError):
                continue
        return None

    def public(self) -> dict:
        with self._lock:
            return {"state": self.state, "state_since": self.state_since, "mode": self.mode,
                    "upstreams": [u.public() for u in self.upstreams],
                    "stats": dict(self.stats), "cache_entries": len(self._cache),
                    "fallback_enabled": self.use_fallback,
                    "fallback_servers": [ip for ip, _port in self.fallback()] if self.use_fallback else []}


# ---------------------------------------------------------------------------
# Server (nur Loopback)
# ---------------------------------------------------------------------------

def is_loopback(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback


class Server:
    def __init__(self, forwarder: Forwarder, port: int = DNS_PORT, hosts=LISTEN_HOSTS) -> None:
        self.forwarder = forwarder
        self.port = port
        self.hosts = hosts
        self.sockets: list[socket.socket] = []
        self.listening: list[str] = []
        self._workers = threading.BoundedSemaphore(MAX_WORKERS)
        self._tcp = threading.BoundedSemaphore(MAX_TCP)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> list[str]:
        """Bindet UDP+TCP auf jeder Adresse. 127.0.0.1 ist Pflicht, ::1 nur, wenn es IPv6 gibt."""
        for host in self.hosts:
            family = _family(host)
            try:
                udp = socket.socket(family, socket.SOCK_DGRAM)
                tcp = socket.socket(family, socket.SOCK_STREAM)
            except OSError:
                if host == self.hosts[0]:
                    raise
                continue
            try:
                if family == socket.AF_INET6:
                    for s in (udp, tcp):
                        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                udp.bind((host, self.port))
                tcp.bind((host, self.port))
                tcp.listen(16)
            except OSError:
                udp.close()
                tcp.close()
                if host == self.hosts[0]:
                    raise
                continue
            self.sockets += [udp, tcp]
            self.listening.append(host)
            for target, sock, kind in ((self._udp_loop, udp, "udp"), (self._tcp_loop, tcp, "tcp")):
                thread = threading.Thread(target=target, args=(sock,), daemon=True, name=f"dns-{kind}-{host}")
                thread.start()
                self._threads.append(thread)
        return list(self.listening)

    def stop(self, timeout: float = 2.0) -> None:
        """Beendet die Schleifen und gibt den Port frei. close() allein weckt unter Linux kein
        recvfrom()/accept() in einem anderen Thread – der Port bliebe bis dahin belegt.
        shutdown() weckt beide (bei UDP mit ENOTCONN, das Aufwecken geschieht trotzdem)."""
        self._stop.set()
        for sock in self.sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        end = time.monotonic() + timeout
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(max(0.0, end - time.monotonic()))
        for sock in self.sockets:
            try:
                sock.close()
            except OSError:
                pass

    def _udp_loop(self, sock: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(MAX_MSG)
            except OSError:
                if self._stop.is_set():
                    return
                continue
            if self._stop.is_set():
                return
            if not addr or not is_loopback(addr[0]):
                continue
            if not self._workers.acquire(blocking=False):
                self.forwarder.stats["dropped"] += 1
                continue
            threading.Thread(target=self._udp_one, args=(sock, data, addr), daemon=True).start()

    def _udp_one(self, sock: socket.socket, data: bytes, addr) -> None:
        try:
            response = self.forwarder.resolve(data)
            if response is None:
                return
            if len(response) > udp_limit(data):
                response = truncated(response)
            sock.sendto(response, addr)
        except (OSError, DnsError):
            pass
        finally:
            self._workers.release()

    def _tcp_loop(self, sock: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = sock.accept()
            except OSError:
                if self._stop.is_set():
                    return
                continue
            if self._stop.is_set():
                conn.close()
                return
            if not is_loopback(addr[0]) or not self._tcp.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._tcp_one, args=(conn,), daemon=True).start()

    def _tcp_one(self, conn: socket.socket) -> None:
        try:
            with conn:
                for _ in range(TCP_MAX_QUERIES):
                    deadline = time.monotonic() + TCP_IDLE
                    try:
                        (length,) = struct.unpack("!H", _recv_exact(conn, 2, deadline))
                        query = _recv_exact(conn, length, deadline) if length else b""
                    except (OSError, struct.error):
                        return
                    if not self._workers.acquire(timeout=1.0):
                        return
                    try:
                        response = self.forwarder.resolve(query)
                    finally:
                        self._workers.release()
                    if response is None:
                        return
                    conn.sendall(struct.pack("!H", len(response)) + response)
        except OSError:
            pass
        finally:
            self._tcp.release()


# ---------------------------------------------------------------------------
# Status und Ereignisse
# ---------------------------------------------------------------------------

def status_path(run_dir: str | None = None) -> str:
    return os.path.join(run_dir or RUN_DIR, STATUS_NAME)


def write_json(path: str, data: dict) -> None:
    _atomic_write(path, json.dumps(data, ensure_ascii=False), 0o644)


def emit_event(level: str, title: str, data: dict | None = None, run_dir: str | None = None) -> None:
    """Eine Zeile in events.jsonl (liest das Dashboard wie die Supervisor-Ereignisse ein)."""
    line = json.dumps({"t": int(time.time()), "kind": "dns", "level": level, "title": title,
                       "data": data or {}}, ensure_ascii=False) + "\n"
    try:
        os.makedirs(run_dir or RUN_DIR, exist_ok=True)
        fd = os.open(os.path.join(run_dir or RUN_DIR, EVENTS_NAME), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


TRANSITIONS = {
    "fallback": ("warn", "DNS für ntp-gui: eigene Server nicht erreichbar – Rückfall auf den System-DNS"),
    "failing": ("crit", "DNS für ntp-gui: keine Namensauflösung möglich"),
    "ok": ("info", "DNS für ntp-gui: eigene Server antworten wieder"),
}


class EventGate:
    """Zustandswechsel → Ereignis, je Wechsel höchstens alle EVENT_REPEAT Sekunden.
    „ok“ nach dem Start ist kein Ereignis (nur die Rückkehr aus einer Störung)."""

    def __init__(self, emit: Callable[..., None] = emit_event, clock: Callable[[], float] = time.monotonic) -> None:
        self.emit = emit
        self.clock = clock
        self._last: dict[tuple[str, str], float] = {}

    def __call__(self, old: str, new: str, detail: dict) -> None:
        if new not in TRANSITIONS or (new == "ok" and old == "starting"):
            return
        now = self.clock()
        key = (old, new)
        if now - self._last.get(key, -1e18) < EVENT_REPEAT:
            return
        self._last[key] = now
        level, title = TRANSITIONS[new]
        data = {"from": old, "to": new}
        if detail.get("errors"):
            data["errors"] = "; ".join(str(e) for e in detail["errors"])[:400]
        if detail.get("upstream"):
            data["upstream"] = detail["upstream"]
        self.emit(level, title, data)


class UpstreamGate:
    """Ereignis je eigenem Server (1.5): „nicht erreichbar – <Fehler>“ und „antwortet wieder“.
    Gleicher Wechsel desselben Servers höchstens alle EVENT_REPEAT Sekunden."""

    def __init__(self, emit: Callable[..., None] = emit_event, clock: Callable[[], float] = time.monotonic) -> None:
        self.emit = emit
        self.clock = clock
        self._last: dict[tuple[str, str], float] = {}

    def __call__(self, label: str, state: str, error: str) -> None:
        now = self.clock()
        key = (label, state)
        if now - self._last.get(key, float("-inf")) < EVENT_REPEAT:
            return
        self._last[key] = now
        if state == "down":
            self.emit("warn", f"DNS für ntp-gui: {label} nicht erreichbar",
                      {"upstream": label, "state": "down", "error": (error or "")[:300]})
        else:
            self.emit("info", f"DNS für ntp-gui: {label} antwortet wieder", {"upstream": label, "state": "up"})


def health_name(cfg: dict) -> str | None:
    """Name für die Erreichbarkeitsprobe: die erste eigene Zeitquelle mit Namen (die fragt
    chronyd ohnehin bei diesen Servern an) – keine Quelle mit Namen → keine Probe."""
    for entry in cfg.get("ntp_sources") or []:
        host = str((entry or {}).get("host") or "").strip().rstrip(".")
        if not host:
            continue
        try:
            ipaddress.ip_address(host.strip("[]"))
            continue
        except ValueError:
            pass
        labels = host.split(".")
        if all(label and len(label) <= 63 and label.replace("-", "").isalnum() and label.isascii()
               for label in labels):
            return host.lower()
    return None


def nts_note(cfg: dict, upstream_count: int) -> str | None:
    """NTS-Quellen brauchen ihren Namen (Zertifikat) – eine „letzte gute IP“ hilft dort nicht."""
    nts = [str(e.get("host")) for e in cfg.get("ntp_sources") or [] if isinstance(e, dict) and e.get("nts")]
    if not nts or effective_mode(cfg) == "system" or upstream_count >= 2:
        return None
    return (f"NTS-Quelle{'n' if len(nts) > 1 else ''} {', '.join(nts[:4])} "
            f"{'brauchen' if len(nts) > 1 else 'braucht'} ihren Namen: Das Zertifikat wird gegen den Namen "
            "geprüft, eine zuletzt bekannte IP-Adresse hilft hier nicht. Mit nur einem eigenen DNS-Server "
            "hängt NTS an diesem einen – trag einen zweiten, unabhängigen ein (z. B. dns.quad9.net und "
            "one.one.one.one).")


def read_status(run_dir: str | None = None) -> dict | None:
    try:
        with open(status_path(run_dir), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def api_status(cfg: dict, run_dir: str | None = None) -> dict:
    """GET /api/dns – eingestellter Modus, Zustand des Weiterleiters, resolv.conf."""
    mode = cfg.get("dns_mode") or "system"
    effective = effective_mode(cfg)
    raw = read_status(run_dir)
    running = bool(raw) and _pid_alive(raw.get("pid")) and raw.get("state") != "stopped"
    out: dict[str, Any] = {
        "mode": mode, "mode_label": MODE_LABELS.get(mode, mode),
        "effective_mode": effective, "effective_label": MODE_LABELS.get(effective, effective),
        "fallback_enabled": bool(cfg.get("dns_fallback", True)),
        "running": running, "warnings": config_warnings(cfg),
    }
    if raw and running:
        for key in ("state", "state_since", "listening", "upstreams", "stats", "cache_entries",
                    "fallback_servers", "resolv", "started", "time", "error"):
            if key in raw:
                out[key] = raw[key]
    elif raw and raw.get("error"):
        out["error"] = raw.get("error")
        out["resolv"] = raw.get("resolv")
    if effective == "system":
        out["state"] = "system"
    elif not running:
        out["state"] = "down"
    ups = (out.get("upstreams") or []) if effective != "system" else []
    oks = [u.get("last_ok") for u in ups if isinstance(u.get("last_ok"), (int, float))]
    out["last_success"] = max(oks) if oks else None
    out["reachable"] = sum(1 for u in ups if u.get("ok") and not u.get("down_until")
                           and (not u.get("last_error_t") or (u.get("last_ok") or 0) >= u["last_error_t"]))
    out["upstream_count"] = len(_mode_list(cfg, effective)) if effective != "system" else 0
    out["nts_note"] = nts_note(cfg, out["upstream_count"])
    return out


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def serve(cfg: dict | None = None, *, port: int | None = None, run_dir: str | None = None,
          resolv: str | None = None, manage_resolv: bool = True,
          stop: threading.Event | None = None) -> int:
    import settings
    cfg = settings.values() if cfg is None else cfg
    run_dir = run_dir or RUN_DIR
    resolv = resolv or RESOLV_CONF
    port = port or int(os.environ.get("NTPGUI_DNS_PORT", DNS_PORT) or DNS_PORT)
    mode = effective_mode(cfg)
    for note in config_warnings(cfg):
        _log(note)
    if mode == "system":
        _log("Modus „system“ – kein eigener Weiterleiter nötig.")
        return 0

    fallback = (lambda: system_servers(resolv)) if cfg.get("dns_fallback", True) else (lambda: [])
    inflight = Inflight()
    bootstrap = Bootstrap(lambda: system_servers(resolv), inflight)
    upstreams = build_upstreams(cfg, bootstrap)
    started = time.time()
    resolv_state = {"state": "system", "message": ""}
    stop = stop or threading.Event()

    def snapshot() -> dict:
        data = forwarder.public()
        data.update(pid=os.getpid(), time=time.time(), started=started, listening=server.listening,
                    resolv=resolv_state)
        return data

    def on_change(old: str, new: str, detail: dict) -> None:
        gate(old, new, detail)
        try:
            write_json(status_path(run_dir), snapshot())
        except OSError:
            pass

    gate = EventGate(lambda level, title, data: emit_event(level, title, data, run_dir))
    upgate = UpstreamGate(lambda level, title, data: emit_event(level, title, data, run_dir))
    forwarder = Forwarder(mode, upstreams, fallback, use_fallback=bool(cfg.get("dns_fallback", True)),
                          on_change=on_change, inflight=inflight, on_upstream=upgate)
    probe_name = health_name(cfg)
    server = Server(forwarder, port)
    try:
        listening = server.start()
    except OSError as exc:
        reason = exc.strerror or str(exc)
        if exc.errno == errno.EADDRINUSE:
            reason += f" – Port {port} auf 127.0.0.1 ist belegt"
            if port == DNS_PORT:
                reason += " (network_mode: host mit eigenem DNS-Server?)"
        elif exc.errno in (errno.EACCES, errno.EPERM) and port < 1024:
            reason += f" – Port {port} braucht NET_BIND_SERVICE (cap_drop: ALL?)"
        _log(f"FEHLER: kann nicht auf 127.0.0.1:{port} lauschen: {reason}")
        try:
            write_json(status_path(run_dir), {"pid": os.getpid(), "time": time.time(), "state": "stopped",
                                              "error": f"Kann nicht auf 127.0.0.1:{port} lauschen: {reason}",
                                              "resolv": resolv_state})
        except OSError:
            pass
        return 2
    labels = ", ".join(u.label for u in upstreams)
    _log(f"lausche auf {', '.join(listening)} Port {port}; Modus {MODE_LABELS[mode]}: {labels}")

    if manage_resolv and port == DNS_PORT:
        resolv_state = point_local(resolv)
        if resolv_state["state"] == "local":
            _log(f"{resolv} zeigt jetzt auf 127.0.0.1" + (f" ({resolv_state['message']})" if resolv_state["message"] else ""))
        else:
            _log(f"WARNUNG: {resolv_state['message']} – chronyd nutzt weiter den System-DNS. "
                 "Abhilfe: in der Compose-Datei „dns: 127.0.0.1“ setzen.")
    try:
        with open(os.path.join(run_dir, READY_NAME), "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except OSError:
        pass

    def finish(signum, _frame) -> None:
        stop.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, finish)
        signal.signal(signal.SIGINT, finish)
    last = float("-inf")  # monotonic() zählt ab Systemstart
    next_health = time.monotonic() + HEALTH_FIRST
    while not stop.is_set():
        if probe_name and time.monotonic() >= next_health:
            next_health = time.monotonic() + HEALTH_EVERY
            try:
                forwarder.health_check(probe_name)
            except Exception as exc:  # die Probe darf den Weiterleiter nie beenden
                _log(f"Erreichbarkeitsprobe gescheitert: {exc}")
            last = float("-inf")  # Ergebnis gleich in dns.json
        if time.monotonic() - last >= STATUS_EVERY:
            last = time.monotonic()
            try:
                write_json(status_path(run_dir), snapshot())
            except OSError:
                pass
        stop.wait(1.0)
    server.stop()
    if manage_resolv and port == DNS_PORT:
        result = restore_system(resolv)
        if result["state"] != "system":
            _log(f"WARNUNG: {result['message']}")
        resolv_state = result
    try:
        data = snapshot()
        data["state"] = "stopped"
        write_json(status_path(run_dir), data)
        os.unlink(os.path.join(run_dir, READY_NAME))
    except OSError:
        pass
    _log("beendet.")
    return 0


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "serve"
    if command == "serve":
        return serve()
    if command == "restore":
        result = restore_system()
        if result["state"] != "system":
            _log(f"WARNUNG: {result['message']}")
            return 1
        return 0
    if command == "status":
        print(json.dumps(read_status() or {}, ensure_ascii=False, indent=1))
        return 0
    print("Aufruf: dnsfwd.py serve|restore|status", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
