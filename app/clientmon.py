"""Passive Messung der Client-Uhren aus ihren NTP-Anfragen.

Jede NTP-Anfrage (Modus 3) enthält im Feld „Transmit Timestamp“ die Uhrzeit des
Clients beim Absenden. Der Kernel stempelt das Paket beim Empfang mit der Zeit
dieses Servers (SO_TIMESTAMPNS). Die Differenz

    Abweichung = Sendezeit laut Client − Empfangszeit laut Server

ist die Abweichung der Client-Uhr minus der Laufzeit des Pakets (im LAN meist
< 1 ms). Positiv heißt: die Uhr des Clients geht vor.

Es wird nichts gesendet – ein AF_PACKET-Socket liest nur mit. Ein klassischer
BPF-Filter im Kernel lässt nur UDP-Pakete an den NTP-Port durch, damit bei viel
Verkehr nicht jedes Paket in Python landet. VLAN-Tags entfernt der Kernel vor
dem Mitlesen; parse_ethernet() kommt trotzdem mit Tags zurecht (Mitschnitte).

Manche Clients (chrony, OpenNTPD, NTPsec, NTS) schreiben absichtlich eine
Zufallszahl statt ihrer Uhrzeit in das Feld, damit Dritte ihre Uhr nicht
auslesen können. Das ist gutes Verhalten – die Abweichung ist dann „nicht
messbar“. Erkennbar daran, dass die Werte absurd groß sind und von Anfrage zu
Anfrage wild springen. Eine wirklich falsch gehende Uhr (z. B. 1970 nach
Batterietausch) liefert dagegen gleichbleibend große Werte.

Benötigt CAP_NET_RAW (in Docker standardmäßig vorhanden) und sieht die echten
Client-Adressen nur, wenn die Pakete nicht per NAT umgeschrieben werden
(network_mode: host oder Docker-Portfreigabe ohne userland-proxy).
"""

from __future__ import annotations

import ipaddress
import os
import socket
import struct
import threading
import time
from collections import OrderedDict, deque
from typing import Any

NTP_EPOCH_OFFSET = 2208988800
TWO32 = 1 << 32
TWO64 = 1 << 64

MAX_CLIENTS = 2000
ABSURD = 86400.0          # |Abweichung| > 1 Tag → verdächtig
CONSISTENT = 60.0         # zwei absurde Werte, die so nah beieinander liegen → echte falsche Uhr
EWMA_ALPHA = 0.2
DEDUP = 512               # gleiche Anfrage auf mehreren Interfaces (Bridge, veth) nur einmal zählen
PERSIST_INTERVAL = 300.0

ETH_P_ALL = 0x0003
ETH_P_IP = 0x0800
ETH_P_IPV6 = 0x86DD
ETH_P_8021Q = 0x8100
ETH_P_8021AD = 0x88A8
PACKET_OUTGOING = 4
SOL_PACKET = 263
PACKET_STATISTICS = 6
SO_ATTACH_FILTER = 26
SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)
SCM_TIMESTAMPNS = SO_TIMESTAMPNS

# Zustände je Client
OK = "ok"
OBFUSCATED = "verschleiert"
NO_TIMESTAMP = "ohne Zeitstempel"
WRONG_CLOCK = "falsche Uhr"
STATE_TEXT = {
    OK: "messbar",
    OBFUSCATED: "nicht messbar (Client verschleiert seine Zeit)",
    NO_TIMESTAMP: "nicht messbar (Client sendet keine Uhrzeit)",
    WRONG_CLOCK: "messbar – Uhr liegt mehr als einen Tag daneben",
}


# ---------------------------------------------------------------------------
# Reine Funktionen: Pakete zerlegen, Zeit rechnen
# ---------------------------------------------------------------------------

def parse_ntp(payload: bytes | memoryview) -> dict | None:
    """NTP-Kopf einer Client-Anfrage. None, wenn kein Modus-3-Paket (≥ 48 Byte)."""
    if len(payload) < 48:
        return None
    first = payload[0]
    mode = first & 7
    version = (first >> 3) & 7
    if mode != 3 or version < 1 or version > 4:
        return None
    poll = payload[2]
    if poll > 127:
        poll -= 256
    sec, frac = struct.unpack_from("!II", payload, 40)
    return {"version": version, "mode": mode, "poll": poll, "xmit": (sec << 32) | frac}


def parse_udp(proto_payload: bytes | memoryview, port: int) -> tuple[int, memoryview] | None:
    """UDP-Kopf → (Quellport, Nutzdaten), wenn der Zielport passt."""
    if len(proto_payload) < 8:
        return None
    sport, dport, length = struct.unpack_from("!HHH", proto_payload, 0)
    if dport != port:
        return None
    mv = memoryview(proto_payload)
    end = min(len(mv), length) if length >= 8 else len(mv)
    return sport, mv[8:end]


def parse_network(ethertype: int, data: bytes | memoryview, port: int) -> dict | None:
    """IPv4/IPv6-Paket (ab IP-Kopf) → Anfrage-Infos oder None."""
    mv = memoryview(data)
    if ethertype == ETH_P_IP:
        if len(mv) < 20 or mv[0] >> 4 != 4:
            return None
        ihl = (mv[0] & 0x0F) * 4
        if ihl < 20 or len(mv) < ihl + 8 or mv[9] != 17:
            return None
        frag = struct.unpack_from("!H", mv, 6)[0]
        if frag & 0x1FFF or frag & 0x2000:  # Fragmente: nicht zuverlässig auswertbar
            return None
        total = struct.unpack_from("!H", mv, 2)[0]
        src = socket.inet_ntop(socket.AF_INET, bytes(mv[12:16]))
        udp = parse_udp(mv[ihl:total if ihl < total <= len(mv) else len(mv)], port)
    elif ethertype == ETH_P_IPV6:
        if len(mv) < 48 or mv[0] >> 4 != 6:
            return None
        nxt, offset = mv[6], 40
        # Einfache Erweiterungs-Header (Hop-by-Hop, Routing, Destination) überspringen.
        for _ in range(4):
            if nxt in (0, 43, 60) and len(mv) >= offset + 8:
                nxt, offset = mv[offset], offset + (mv[offset + 1] + 1) * 8
            else:
                break
        if nxt != 17:
            return None
        src = socket.inet_ntop(socket.AF_INET6, bytes(mv[8:24]))
        udp = parse_udp(mv[offset:], port)
    else:
        return None
    if udp is None:
        return None
    sport, payload = udp
    ntp = parse_ntp(payload)
    if ntp is None:
        return None
    ntp["src"] = src
    ntp["sport"] = sport
    return ntp


def parse_ethernet(frame: bytes | memoryview, port: int) -> dict | None:
    """Ethernet-Frame (auch mit 802.1Q/802.1ad-Tags) → Anfrage-Infos oder None."""
    mv = memoryview(frame)
    if len(mv) < 14:
        return None
    ethertype = struct.unpack_from("!H", mv, 12)[0]
    offset = 14
    vlan = None
    for _ in range(2):  # höchstens Q-in-Q
        if ethertype in (ETH_P_8021Q, ETH_P_8021AD) and len(mv) >= offset + 4:
            tci, ethertype = struct.unpack_from("!HH", mv, offset)
            vlan = tci & 0x0FFF if vlan is None else vlan
            offset += 4
    result = parse_network(ethertype, mv[offset:], port)
    if result is not None and vlan is not None:
        result["vlan"] = vlan
    return result


def unix_to_ntp64(unix_seconds: float) -> int:
    """Unix-Zeit → 64-Bit-NTP-Festkomma (Ära modulo 2^32 Sekunden)."""
    whole = int(unix_seconds // 1)
    frac = unix_seconds - whole
    return (((whole + NTP_EPOCH_OFFSET) % TWO32) << 32) | (int(frac * TWO32) & 0xFFFFFFFF)


def ntp_offset(client_xmit: int, receive_unix_ns: int) -> float:
    """Abweichung Client − Server in Sekunden, über Ära-Grenzen hinweg (±68 Jahre).

    Rechnet ganzzahlig im 32.32-Festkomma, damit Nanosekunden nicht in Gleitkomma-
    Rundung untergehen. receive_unix_ns: Kernel-Empfangszeit in ns seit 1970.
    """
    sec, nsec = divmod(receive_unix_ns, 1_000_000_000)
    ours = (((sec + NTP_EPOCH_OFFSET) % TWO32) << 32) | ((nsec << 32) // 1_000_000_000)
    diff = (client_xmit - ours) % TWO64
    if diff >= 1 << 63:
        diff -= TWO64
    return diff / TWO32


def classify(xmit: int, offset: float, previous_absurd: float | None) -> str:
    """Zustand einer einzelnen Anfrage."""
    if xmit == 0:
        return NO_TIMESTAMP
    if abs(offset) <= ABSURD:
        return OK
    if previous_absurd is not None and abs(offset - previous_absurd) < CONSISTENT:
        return WRONG_CLOCK
    return OBFUSCATED


def parse_timestamp_cmsg(ancdata: list) -> int | None:
    """SCM_TIMESTAMPNS (struct timespec, native long) → ns seit 1970."""
    for level, kind, data in ancdata:
        if level == socket.SOL_SOCKET and kind == SCM_TIMESTAMPNS:
            size = struct.calcsize("@ll")
            if len(data) >= size:
                sec, nsec = struct.unpack_from("@ll", data)
                return sec * 1_000_000_000 + nsec
    return None


# ---------------------------------------------------------------------------
# BPF-Filter (klassisch): nur UDP an den NTP-Port, IPv4 + IPv6, unabhängig vom Link-Typ
# ---------------------------------------------------------------------------

SKF_AD_OFF = -0x1000
SKF_AD_PROTOCOL = 0
SKF_NET_OFF = -0x100000

BPF_LD, BPF_LDX, BPF_JMP, BPF_RET = 0x00, 0x01, 0x05, 0x06
BPF_W, BPF_H, BPF_B = 0x00, 0x08, 0x10
BPF_ABS, BPF_IND, BPF_MSH = 0x20, 0x40, 0xA0
BPF_JEQ, BPF_JSET = 0x10, 0x40
BPF_K = 0x00


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def bpf_program(port: int) -> list[tuple[int, int, int, int]]:
    """(code, jt, jf, k)-Befehle. Offsets relativ zum Netzwerk-Kopf (SKF_NET_OFF)."""
    net = SKF_NET_OFF
    prog = [
        (BPF_LD | BPF_H | BPF_ABS, 0, 0, _u32(SKF_AD_OFF + SKF_AD_PROTOCOL)),  # 0: A = skb->protocol
        (BPF_JMP | BPF_JEQ | BPF_K, 0, 7, ETH_P_IP),                          # 1: IPv4? sonst → 9
        (BPF_LD | BPF_B | BPF_ABS, 0, 0, _u32(net + 9)),                       # 2: A = IP-Protokoll
        (BPF_JMP | BPF_JEQ | BPF_K, 0, 12, 17),                                # 3: UDP? sonst → drop(16)
        (BPF_LD | BPF_H | BPF_ABS, 0, 0, _u32(net + 6)),                       # 4: A = Flags/Fragment
        (BPF_JMP | BPF_JSET | BPF_K, 10, 0, 0x1FFF),                           # 5: Fragment → drop(16)
        (BPF_LDX | BPF_B | BPF_MSH, 0, 0, _u32(net + 0)),                      # 6: X = IHL*4
        (BPF_LD | BPF_H | BPF_IND, 0, 0, _u32(net + 2)),                       # 7: A = UDP-Zielport
        (BPF_JMP | BPF_JEQ | BPF_K, 6, 7, port),                               # 8: passt → accept(15)
        (BPF_JMP | BPF_JEQ | BPF_K, 0, 6, ETH_P_IPV6),                         # 9: IPv6? sonst → drop(16)
        (BPF_LD | BPF_B | BPF_ABS, 0, 0, _u32(net + 6)),                       # 10: A = Next Header
        (BPF_JMP | BPF_JEQ | BPF_K, 0, 4, 17),                                 # 11: UDP? sonst → drop(16)
        (BPF_LD | BPF_H | BPF_ABS, 0, 0, _u32(net + 42)),                      # 12: A = UDP-Zielport
        (BPF_JMP | BPF_JEQ | BPF_K, 1, 2, port),                               # 13: passt → accept(15)
        (BPF_RET | BPF_K, 0, 0, 0),                                            # 14: (nicht erreicht)
        (BPF_RET | BPF_K, 0, 0, 512),                                          # 15: accept (512 Byte)
        (BPF_RET | BPF_K, 0, 0, 0),                                            # 16: drop
    ]
    return prog


def _attach_filter(sock: socket.socket, port: int) -> bool:
    import ctypes
    prog = bpf_program(port)
    raw = b"".join(struct.pack("HBBI", code, jt, jf, k) for code, jt, jf, k in prog)
    buf = ctypes.create_string_buffer(raw)
    fprog = struct.pack("HL", len(prog), ctypes.addressof(buf))
    try:
        sock.setsockopt(socket.SOL_SOCKET, SO_ATTACH_FILTER, fprog)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Statistik je Client
# ---------------------------------------------------------------------------

class ClientTable:
    """Begrenzte LRU-Tabelle mit Messwerten je Client-Adresse."""

    def __init__(self, limit: int = MAX_CLIENTS) -> None:
        self.limit = limit
        self.clients: OrderedDict[str, dict] = OrderedDict()
        self.lock = threading.Lock()

    def update(self, ip: str, req: dict, offset: float | None, now: float) -> dict:
        with self.lock:
            entry = self.clients.get(ip)
            if entry is None:
                entry = {"requests": 0, "count": 0, "obfuscated": 0, "no_timestamp": 0,
                         "last_offset": None, "ewma": None, "min": None, "max": None,
                         "first_seen": now, "absurd": None, "state": None}
                self.clients[ip] = entry
                while len(self.clients) > self.limit:
                    self.clients.popitem(last=False)
            else:
                self.clients.move_to_end(ip)
            entry["requests"] += 1
            entry["version"] = req.get("version")
            entry["poll"] = req.get("poll")
            entry["last_seen"] = now
            if req.get("vlan") is not None:
                entry["vlan"] = req["vlan"]
            state = classify(req["xmit"], offset if offset is not None else 0.0, entry.get("absurd"))
            if offset is not None and abs(offset) > ABSURD:
                entry["absurd"] = offset
            if state == NO_TIMESTAMP:
                entry["no_timestamp"] += 1
            elif state == OBFUSCATED:
                entry["obfuscated"] += 1
            elif offset is not None:
                entry["count"] += 1
                entry["last_offset"] = offset
                entry["ewma"] = offset if entry["ewma"] is None else \
                    entry["ewma"] + EWMA_ALPHA * (offset - entry["ewma"])
                entry["min"] = offset if entry["min"] is None else min(entry["min"], offset)
                entry["max"] = offset if entry["max"] is None else max(entry["max"], offset)
            entry["state"] = state
            return entry

    def snapshot(self) -> dict[str, dict]:
        with self.lock:
            items = list(self.clients.items())
        return {ip: public_entry(e) for ip, e in items}

    def restore(self, rows: dict[str, dict]) -> None:
        with self.lock:
            for ip, entry in sorted(rows.items(), key=lambda kv: kv[1].get("last_seen") or 0):
                if ip in self.clients or not isinstance(entry, dict):
                    continue
                base = {"requests": 0, "count": 0, "obfuscated": 0, "no_timestamp": 0,
                        "last_offset": None, "ewma": None, "min": None, "max": None,
                        "first_seen": None, "absurd": None, "state": None}
                base.update({k: entry.get(k) for k in base if k in entry})
                base.update({k: entry.get(k) for k in ("version", "poll", "last_seen", "vlan") if k in entry})
                self.clients[ip] = base
            while len(self.clients) > self.limit:
                self.clients.popitem(last=False)


def public_entry(entry: dict) -> dict:
    """Werte für die API: Zustand nach Mehrheit, nicht nur nach der letzten Anfrage."""
    total = entry.get("requests") or 0
    measured = entry.get("count") or 0
    obfuscated = entry.get("obfuscated") or 0
    no_ts = entry.get("no_timestamp") or 0
    state = entry.get("state")
    if measured and measured >= obfuscated + no_ts:
        state = WRONG_CLOCK if state == WRONG_CLOCK or abs(entry.get("ewma") or 0) > ABSURD else OK
    elif obfuscated >= no_ts and obfuscated:
        state = OBFUSCATED
    elif no_ts:
        state = NO_TIMESTAMP
    measurable = state in (OK, WRONG_CLOCK)
    out = {
        "state": state,
        "state_text": STATE_TEXT.get(state, "noch keine Anfrage"),
        "measurable": measurable,
        "offset": entry.get("last_offset") if measurable else None,
        "ewma": entry.get("ewma") if measurable else None,
        "min": entry.get("min") if measurable else None,
        "max": entry.get("max") if measurable else None,
        "count": measured, "requests": total,
        "version": entry.get("version"), "poll": entry.get("poll"),
        "first_seen": entry.get("first_seen"), "last_seen": entry.get("last_seen"),
    }
    if entry.get("vlan") is not None:
        out["vlan"] = entry["vlan"]
    return out


# ---------------------------------------------------------------------------
# Hintergrund-Thread
# ---------------------------------------------------------------------------

class Monitor:
    def __init__(self, port: int) -> None:
        self.port = port
        self.table = ClientTable()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.sock: socket.socket | None = None
        self.available = False
        self.reason: str | None = None
        self.filtered = False
        self.packets = 0
        self.ignored = 0
        self.since = time.time()
        self.kernel_drops = 0
        self._seen: deque = deque(maxlen=DEDUP)
        self._seen_set: set = set()
        self._last_persist = time.monotonic()

    # -- Socket ---------------------------------------------------------------
    def open(self) -> bool:
        if not hasattr(socket, "AF_PACKET"):
            self.reason = "Nur unter Linux verfügbar (AF_PACKET fehlt)."
            return False
        try:
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(ETH_P_ALL))
        except PermissionError:
            self.reason = ("Keine Berechtigung zum Mitlesen (CAP_NET_RAW fehlt). Docker gibt sie "
                           "normalerweise mit; wurde sie per cap_drop entfernt, ergänze "
                           "`cap_add: [NET_RAW]`. Gemessen wird trotzdem nichts gesendet.")
            return False
        except OSError as exc:
            self.reason = f"Mitlesen nicht möglich: {exc.strerror or exc}"
            return False
        try:
            sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
        except OSError:
            pass  # dann gilt die Zeit beim Abholen – ungenauer, aber brauchbar
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        except OSError:
            pass
        self.filtered = _attach_filter(sock, self.port)
        sock.setblocking(False)
        self.sock = sock
        self.available = True
        self.reason = None
        return True

    def start(self) -> None:
        if not self.open():
            return
        self._restore()
        self.thread = threading.Thread(target=self._run, daemon=True, name="clientmon")
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(2.0)
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        self._persist()

    # -- Schleife -------------------------------------------------------------
    def _run(self) -> None:
        import select
        sock = self.sock
        assert sock is not None
        buf = bytearray(2048)
        anc = socket.CMSG_SPACE(struct.calcsize("@ll"))
        while not self.stop_event.is_set():
            try:
                ready, _, _ = select.select([sock], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not ready:
                self._housekeeping()
                continue
            # Alles abholen, was anliegt – aber begrenzt, damit stop() schnell greift.
            for _ in range(1000):
                try:
                    nbytes, ancdata, _flags, addr = sock.recvmsg_into([buf], anc)
                except BlockingIOError:
                    break
                except OSError:
                    break
                self.handle(memoryview(buf)[:nbytes], addr, ancdata)
            self._housekeeping()

    def handle(self, data: memoryview, addr: Any, ancdata: list) -> None:
        """Ein mitgelesenes Paket verarbeiten (ab IP-Kopf, SOCK_DGRAM)."""
        try:
            proto, pkttype = addr[1], addr[2]
        except (TypeError, IndexError):
            return
        if pkttype == PACKET_OUTGOING:
            return  # eigene Anfragen von chronyd an seine Quellen
        try:
            req = parse_network(proto, data, self.port)
        except (struct.error, ValueError, IndexError):
            req = None
        if req is None:
            self.ignored += 1
            return
        key = (req["src"], req["sport"], req["xmit"])
        if key in self._seen_set:
            return
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(key)
        self._seen_set.add(key)
        stamp = parse_timestamp_cmsg(ancdata)
        if stamp is None:
            stamp = time.time_ns()
        offset = ntp_offset(req["xmit"], stamp) if req["xmit"] else None
        self.packets += 1
        self.table.update(_norm_ip(req["src"]), req, offset, stamp / 1e9)

    def _housekeeping(self) -> None:
        if self.sock is not None:
            try:
                raw = self.sock.getsockopt(SOL_PACKET, PACKET_STATISTICS, 8)
                self.kernel_drops += struct.unpack("II", raw)[1]  # Zähler wird beim Lesen zurückgesetzt
            except OSError:
                pass
        if time.monotonic() - self._last_persist > PERSIST_INTERVAL:
            self._persist()

    # -- Speichern (optional) ---------------------------------------------------
    def _persist(self) -> None:
        self._last_persist = time.monotonic()
        snap = self.table.snapshot()
        if not snap:
            return
        try:
            import json
            import store  # spät: fehlt store, läuft die Messung trotzdem
            _migrate(store)
            now = time.time()
            with store.transaction() as conn:
                conn.executemany(
                    "INSERT INTO clientmon_clients(ip, data, updated) VALUES(?, ?, ?) "
                    "ON CONFLICT(ip) DO UPDATE SET data=excluded.data, updated=excluded.updated",
                    [(ip, json.dumps(entry), now) for ip, entry in snap.items()])
                conn.execute("DELETE FROM clientmon_clients WHERE updated < ?", (now - 30 * 86400,))
        except Exception:  # noqa: BLE001 – Speichern ist nur ein Zusatz
            pass

    def _restore(self) -> None:
        try:
            import json
            import store
            _migrate(store)
            rows = store.query("SELECT ip, data FROM clientmon_clients ORDER BY updated DESC LIMIT ?",
                               (MAX_CLIENTS,))
            restored = {}
            for ip, data in rows:
                entry = json.loads(data)
                restored[ip] = {"requests": entry.get("requests"), "count": entry.get("count"),
                                "last_offset": entry.get("offset"), "ewma": entry.get("ewma"),
                                "min": entry.get("min"), "max": entry.get("max"),
                                "first_seen": entry.get("first_seen"), "last_seen": entry.get("last_seen"),
                                "version": entry.get("version"), "poll": entry.get("poll"),
                                "state": entry.get("state"), "obfuscated": 0, "no_timestamp": 0}
                if entry.get("state") == OBFUSCATED:
                    restored[ip]["obfuscated"] = max(1, entry.get("requests") or 1)
                elif entry.get("state") == NO_TIMESTAMP:
                    restored[ip]["no_timestamp"] = max(1, entry.get("requests") or 1)
            self.table.restore(restored)
        except Exception:  # noqa: BLE001
            pass


def _migrate(store_mod) -> None:
    store_mod.migrate("clientmon", [
        "CREATE TABLE IF NOT EXISTS clientmon_clients (ip TEXT PRIMARY KEY, data TEXT NOT NULL, "
        "updated REAL NOT NULL)",
        "CREATE INDEX IF NOT EXISTS clientmon_updated ON clientmon_clients(updated)",
    ])


def _norm_ip(ip: str) -> str:
    """::ffff:192.0.2.1 → 192.0.2.1, damit ein Client nicht doppelt erscheint."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6 and addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    return str(addr)


def default_gateway() -> str | None:
    """IPv4-Standard-Gateway aus /proc/net/route (für den NAT-Hinweis)."""
    try:
        with open("/proc/net/route", encoding="ascii") as handle:
            next(handle, None)
            for line in handle:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000":
                    return socket.inet_ntoa(struct.pack("<I", int(parts[2], 16)))
    except (OSError, ValueError):
        pass
    return None


def nat_hint(clients: dict[str, dict], gateway: str | None) -> str | None:
    """Kommen alle Anfragen vom Gateway des Containers, sieht ntp-gui nur NAT-Adressen."""
    if not clients or not gateway:
        return None
    if set(clients) == {gateway}:
        return (f"Alle Anfragen kommen von {gateway}, dem Gateway des Containers. Vermutlich schreibt "
                "Docker die Absender um (Bridge-Netz mit userland-proxy oder IPv6-Weiterleitung). Dann "
                "lassen sich die Geräte nicht unterscheiden – mit `network_mode: host` siehst du die echten "
                "Adressen.")
    return None


# ---------------------------------------------------------------------------
# Modul-API
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_MONITOR: Monitor | None = None
_LAST_REASON: str | None = "Nicht gestartet (in den Einstellungen ausgeschaltet)."


def start(port: int = 123) -> dict:
    """Startet die Messung (idempotent; anderer Port → Neustart)."""
    global _MONITOR, _LAST_REASON
    with _LOCK:
        if _MONITOR is not None and _MONITOR.port == port and _MONITOR.thread and _MONITOR.thread.is_alive():
            return status()
        if _MONITOR is not None:
            _MONITOR.stop()
            _MONITOR = None
        monitor = Monitor(int(port))
        monitor.start()
        if monitor.available:
            _MONITOR = monitor
            _LAST_REASON = None
        else:
            _LAST_REASON = monitor.reason
    return status()


def stop() -> None:
    global _MONITOR, _LAST_REASON
    with _LOCK:
        if _MONITOR is not None:
            _MONITOR.stop()
            _MONITOR = None
        _LAST_REASON = "Nicht gestartet (in den Einstellungen ausgeschaltet)."


def sync(enabled: bool, port: int) -> None:
    """Passt den Zustand an die Einstellungen an (für den Server-Thread)."""
    if enabled:
        with _LOCK:
            running = _MONITOR is not None and _MONITOR.port == port
            failed_before = _MONITOR is None and _LAST_REASON is not None and \
                not _LAST_REASON.startswith("Nicht gestartet")
        if not running and not failed_before:
            start(port)
    else:
        with _LOCK:
            active = _MONITOR is not None
        if active:
            stop()


def watch(get_cfg, stop_event: threading.Event | None = None, interval: float = 10.0) -> None:
    """Hintergrund-Schleife: folgt clientmon_enable/ntp_port ohne Neustart."""
    stop_event = stop_event or threading.Event()
    while True:
        try:
            cfg = get_cfg()
            sync(bool(cfg.get("clientmon_enable")), int(cfg.get("ntp_port") or 123))
        except Exception:  # noqa: BLE001
            pass
        if stop_event.wait(interval):
            stop()
            return


def status() -> dict:
    """{"available","reason","clients":{ip:{…}},"packets","since", …}"""
    monitor = _MONITOR
    if monitor is None:
        return {"available": False, "running": False, "reason": _LAST_REASON, "clients": {},
                "packets": 0, "since": None}
    clients = monitor.table.snapshot()
    return {
        "available": True,
        "running": bool(monitor.thread and monitor.thread.is_alive()),
        "reason": nat_hint(clients, default_gateway()),
        "clients": clients,
        "packets": monitor.packets,
        "ignored": monitor.ignored,
        "kernel_drops": monitor.kernel_drops,
        "filtered": monitor.filtered,
        "port": monitor.port,
        "since": monitor.since,
    }
