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
    precision = payload[3]
    if precision > 127:
        precision -= 256
    sec, frac = struct.unpack_from("!II", payload, 40)
    rest = bytes(payload[4:40])
    # Für die Vermutung „welche Client-Software?“: Füllt der Client die übrigen Kopffelder
    # (Stratum, Präzision, Referenz …) aus wie ntpd/chrony, oder schickt er nur Version,
    # Modus und Sendezeit wie schlanke SNTP-Clients (systemd-timesyncd, Mikrocontroller)?
    return {"version": version, "mode": mode, "poll": poll, "xmit": (sec << 32) | frac,
            "stratum": payload[1], "precision": precision,
            "bare": payload[1] == 0 and precision == 0 and not any(rest)}


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

INTERVALS_KEPT = 16       # so viele Abstände zwischen Anfragen je Client (Median = typisches Intervall)
MIN_INTERVAL = 0.2        # kürzere Abstände sind Wiederholungen/Bursts, kein Intervall
BURST_GAP = 4.0           # kürzere Abstände gehören zu einem Burst (ntpd iburst: 2 s, ntpdate/sntp-Serien)
BURST_MIN_GAPS = 12       # erst so viele kurze Abstände OHNE längeren dazwischen = wirklich so oft

# Verlauf je Client in SQLite (Tabelle clientmon_samples)
SAMPLE_RETENTION = 7 * 86400
SAMPLE_SPACING = 120.0     # höchstens ein gespeicherter Messpunkt je Client in diesem Abstand
MAX_SAMPLES_PER_CLIENT = 5000   # 7 Tage bei SAMPLE_SPACING passen hinein
SAMPLE_FLUSH = 30.0        # gesammelte Messpunkte so oft in die Datenbank schreiben
SAMPLE_PRUNE = 3600.0
MAX_PENDING = 2000         # höchstens so viele Messpunkte je Schreibrunde (SAMPLE_FLUSH)
MAX_NEW_PER_FLUSH = 200    # … davon höchstens so viele von Adressen mit erst EINER Anfrage
MAX_SAMPLES_TOTAL = 2_000_000   # Obergrenze der ganzen Tabelle (≈ 150 MB), älteste fliegen zuerst
ORPHAN_GRACE = 3600.0      # Punkte von Adressen ohne gespeicherten Client nach 1 h löschen
MAX_STORED_CLIENTS = 4 * MAX_CLIENTS  # Zeilen in clientmon_clients (neueste bleiben)
# Warum so knapp: Wer Absenderadressen wechselt (gefälschte Absender im LAN, jede IPv6-Adresse
# aus einem /64, offener Port 123), erzeugt sonst mit jedem Paket eine neue Zeile – die LRU-Tabelle
# vergisst verdrängte Adressen samt Sperrabstand. Ohne Grenzen wären das zig GB auf /data.


def _new_entry(now: float | None) -> dict:
    return {"requests": 0, "count": 0, "obfuscated": 0, "no_timestamp": 0,
            "last_offset": None, "ewma": None, "min": None, "max": None,
            "first_seen": now, "absurd": None, "state": None, "intervals": []}


def typical_interval(intervals: list) -> float | None:
    """Median der letzten Abstände – robust gegen Bursts und einzelne verlorene Anfragen.

    Abstände unter BURST_GAP gehören zu einem Burst (ntpd mit iburst schickt 8 Anfragen im
    Abstand von 2 s, ntpdate/sntp-Läufe mehrere hintereinander) und zählen nicht, sobald es
    längere Abstände gibt. Gibt es NUR kurze, ist das Intervall erst nach BURST_MIN_GAPS
    Abständen bekannt – vorher kann es ebenso gut ein einzelner Start-Burst gewesen sein.
    """
    values = sorted(v for v in intervals or [] if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0)
    if not values:
        return None
    longer = [v for v in values if v >= BURST_GAP]
    if longer:
        values = longer
    elif len(values) < BURST_MIN_GAPS:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


class ClientTable:
    """Begrenzte LRU-Tabelle mit Messwerten je Client-Adresse.

    Zusätzlich sammelt sie Messpunkte für den Verlauf je Client (pending), die der
    Monitor gebündelt in SQLite schreibt – höchstens einen je SAMPLE_SPACING und Client.
    """

    def __init__(self, limit: int = MAX_CLIENTS) -> None:
        self.limit = limit
        self.clients: OrderedDict[str, dict] = OrderedDict()
        self.lock = threading.Lock()
        self.pending: list[tuple] = []
        self._stored: dict[str, float] = {}
        self._new_pending = 0
        self.dropped = 0   # wegen der Grenzen nicht gespeicherte Messpunkte (seit Start)

    def update(self, ip: str, req: dict, offset: float | None, now: float) -> dict:
        with self.lock:
            entry = self.clients.get(ip)
            if entry is None:
                entry = _new_entry(now)
                self.clients[ip] = entry
                while len(self.clients) > self.limit:
                    old, _ = self.clients.popitem(last=False)
                    self._stored.pop(old, None)
            else:
                self.clients.move_to_end(ip)
            previous = entry.get("last_seen")
            interval = None
            if isinstance(previous, (int, float)) and now - previous >= MIN_INTERVAL:
                interval = now - previous
                intervals = entry.setdefault("intervals", [])
                intervals.append(round(interval, 3))
                del intervals[:-INTERVALS_KEPT]
            if entry.get("first_seen") is None:
                entry["first_seen"] = now
            entry["requests"] += 1
            entry["version"] = req.get("version")
            entry["poll"] = req.get("poll")
            entry["last_seen"] = now
            for key in ("stratum", "precision", "bare"):
                if key in req:
                    entry[key] = req[key]
            if req.get("vlan") is not None:
                entry["vlan"] = req["vlan"]
            if req.get("mac"):
                entry["mac"] = req["mac"]
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
            self._queue_sample(ip, now, offset if state in (OK, WRONG_CLOCK) else None, req, interval,
                               first=entry["requests"] <= 1)
            return entry

    def _queue_sample(self, ip: str, now: float, offset: float | None, req: dict,
                      interval: float | None, first: bool = False) -> None:
        """Messpunkt für den Verlauf vormerken (unter self.lock). Auch nicht messbare Anfragen –
        ohne Abweichung, aber mit Poll und Abstand, damit das Intervall-Diagramm etwas zeigt.

        Je Schreibrunde höchstens MAX_PENDING Punkte, davon MAX_NEW_PER_FLUSH von Adressen mit
        erst einer Anfrage – was darüber liegt, fällt weg (die Tabelle im Speicher misst weiter)."""
        last = self._stored.get(ip)
        if last is not None and now - last < SAMPLE_SPACING:
            return
        if len(self.pending) >= MAX_PENDING:
            self.dropped += 1
            return
        if first:
            if self._new_pending >= MAX_NEW_PER_FLUSH:
                self.dropped += 1
                return
            self._new_pending += 1
        self._stored[ip] = now
        self.pending.append((ip, now, offset, req.get("poll"), req.get("version"),
                             round(interval, 3) if interval is not None else None))

    def take_pending(self) -> list[tuple]:
        with self.lock:
            rows, self.pending = self.pending, []
            self._new_pending = 0
        return rows

    def get(self, ip: str) -> dict | None:
        with self.lock:
            entry = self.clients.get(ip)
            return public_entry(entry) if entry is not None else None

    def snapshot(self, private: bool = False) -> dict[str, dict]:
        convert = private_entry if private else public_entry
        with self.lock:
            items = [(ip, convert(e)) for ip, e in self.clients.items()]
        return dict(items)

    def restore(self, rows: dict[str, dict]) -> None:
        with self.lock:
            for ip, entry in sorted(rows.items(), key=lambda kv: kv[1].get("last_seen") or 0):
                if ip in self.clients or not isinstance(entry, dict):
                    continue
                base = _new_entry(None)
                base.update({k: entry.get(k) for k in base if k in entry and entry.get(k) is not None})
                base.update({k: entry.get(k) for k in RESTORED_KEYS if k in entry})
                if not isinstance(base.get("intervals"), list):
                    base["intervals"] = []
                self.clients[ip] = base
            while len(self.clients) > self.limit:
                self.clients.popitem(last=False)


RESTORED_KEYS = ("version", "poll", "last_seen", "vlan", "mac", "stratum", "precision", "bare")


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
        "interval": typical_interval(entry.get("intervals") or []),
    }
    if entry.get("vlan") is not None:
        out["vlan"] = entry["vlan"]
    return out


def private_entry(entry: dict) -> dict:
    """Wie public_entry, dazu Merkmale für die Detailseite (MAC, Kopffelder, Abstände).

    Nur für die lokale Detailansicht – die MAC-Adresse steht absichtlich nicht in der
    Liste (/api/clients/offsets), die auch in Diagnose und Metriken landen kann."""
    out = public_entry(entry)
    out["obfuscated"] = entry.get("obfuscated") or 0
    out["no_timestamp"] = entry.get("no_timestamp") or 0
    out["intervals"] = list(entry.get("intervals") or [])
    for key in ("mac", "stratum", "precision", "bare"):
        if entry.get(key) is not None:
            out[key] = entry[key]
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
        self._last_flush = time.monotonic()
        self._last_prune = float("-inf")  # monotonic() zählt ab Systemstart – 0.0 hieße „vor Kurzem“

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
            except (OSError, ValueError) as exc:
                self.reason = f"Mitlesen abgebrochen: {exc} – neuer Versuch folgt."
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
        src = _norm_ip(req["src"])
        mac = frame_mac(addr)
        if mac and on_link(src, addr[0]):
            req["mac"] = mac
        self.table.update(src, req, offset, stamp / 1e9)

    def _housekeeping(self) -> None:
        if self.sock is not None:
            try:
                raw = self.sock.getsockopt(SOL_PACKET, PACKET_STATISTICS, 8)
                self.kernel_drops += struct.unpack("II", raw)[1]  # Zähler wird beim Lesen zurückgesetzt
            except OSError:
                pass
        now = time.monotonic()
        if now - self._last_flush > SAMPLE_FLUSH:
            self.flush_samples()
        if now - self._last_persist > PERSIST_INTERVAL:
            self._persist()

    # -- Speichern (optional) ---------------------------------------------------
    def flush_samples(self, prune: bool | None = None) -> int:
        """Vorgemerkte Messpunkte in clientmon_samples schreiben; stündlich alte entfernen."""
        self._last_flush = time.monotonic()
        rows = self.table.take_pending()
        if prune is None:
            prune = time.monotonic() - self._last_prune > SAMPLE_PRUNE
        if not rows and not prune:
            return 0
        try:
            import store
            _migrate(store)
            if rows:
                with store.transaction() as conn:
                    conn.executemany("INSERT INTO clientmon_samples(ip, t, offset, poll, version, interval) "
                                     "VALUES(?, ?, ?, ?, ?, ?)", rows)
            if prune:
                self._last_prune = time.monotonic()
                prune_samples(store)
        except Exception:  # noqa: BLE001 – Verlauf ist nur ein Zusatz
            return 0
        return len(rows)

    def _persist(self) -> None:
        self._last_persist = time.monotonic()
        self.flush_samples(prune=False)
        snap = self.table.snapshot(private=True)
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
                conn.execute("DELETE FROM clientmon_clients WHERE updated < ?", (now - CLIENT_RETENTION,))
                # Verdrängte Adressen bleiben 30 Tage stehen – bei wechselnden Absendern wären das
                # beliebig viele Zeilen. Die neuesten MAX_STORED_CLIENTS genügen.
                conn.execute("DELETE FROM clientmon_clients WHERE ip IN (SELECT ip FROM clientmon_clients "
                             "ORDER BY updated DESC LIMIT -1 OFFSET ?)", (MAX_STORED_CLIENTS,))
        except Exception:  # noqa: BLE001 – Speichern ist nur ein Zusatz
            pass

    def _restore(self) -> None:
        try:
            self.table.restore(stored_clients())
        except Exception:  # noqa: BLE001
            pass


CLIENT_RETENTION = 30 * 86400


def _from_stored(entry: dict) -> dict:
    """Gespeicherte Zeile (private_entry als JSON) → Tabelleneintrag."""
    out = {"requests": entry.get("requests"), "count": entry.get("count"),
           "last_offset": entry.get("offset"), "ewma": entry.get("ewma"),
           "min": entry.get("min"), "max": entry.get("max"),
           "first_seen": entry.get("first_seen"), "last_seen": entry.get("last_seen"),
           "version": entry.get("version"), "poll": entry.get("poll"),
           "state": entry.get("state"), "intervals": entry.get("intervals") or [],
           "obfuscated": entry.get("obfuscated") or 0, "no_timestamp": entry.get("no_timestamp") or 0}
    for key in ("vlan", "mac", "stratum", "precision", "bare"):
        if entry.get(key) is not None:
            out[key] = entry[key]
    # Zeilen aus 1.3 kannten die Zähler nicht: Zustand über die Zahl der Anfragen halten.
    if entry.get("state") == OBFUSCATED and not out["obfuscated"]:
        out["obfuscated"] = max(1, entry.get("requests") or 1)
    elif entry.get("state") == NO_TIMESTAMP and not out["no_timestamp"]:
        out["no_timestamp"] = max(1, entry.get("requests") or 1)
    return out


def stored_clients(ip: str | None = None) -> dict[str, dict]:
    """Gespeicherte Clients (alle oder einer) als Tabelleneinträge – auch ohne laufende Messung."""
    import json
    import store
    _migrate(store)
    if ip is None:
        rows = store.query("SELECT ip, data FROM clientmon_clients ORDER BY updated DESC LIMIT ?",
                           (MAX_CLIENTS,))
    else:
        rows = store.query("SELECT ip, data FROM clientmon_clients WHERE ip=?", (ip,))
    out = {}
    for addr, data in rows:
        try:
            entry = json.loads(data)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out[addr] = _from_stored(entry)
    return out


def prune_samples(store_mod, now: float | None = None, keep: int = MAX_SAMPLES_PER_CLIENT,
                  total: int = MAX_SAMPLES_TOTAL) -> None:
    """Älter als 7 Tage weg; Punkte von Adressen, die nicht (mehr) in clientmon_clients stehen,
    nach ORPHAN_GRACE weg; insgesamt höchstens `total` Punkte (die neuesten bleiben); je Client
    höchstens `keep` Punkte."""
    now = time.time() if now is None else now
    with store_mod.transaction() as conn:
        conn.execute("DELETE FROM clientmon_samples WHERE t < ?", (now - SAMPLE_RETENTION,))
        conn.execute("DELETE FROM clientmon_samples WHERE t < ? AND ip NOT IN (SELECT ip FROM clientmon_clients)",
                     (now - ORPHAN_GRACE,))
        conn.execute("DELETE FROM clientmon_samples WHERE rowid IN (SELECT rowid FROM clientmon_samples "
                     "ORDER BY t DESC LIMIT -1 OFFSET ?)", (max(1, int(total)),))
        crowded = conn.execute("SELECT ip FROM clientmon_samples GROUP BY ip HAVING COUNT(*) > ?",
                               (keep,)).fetchall()
        for (addr,) in crowded:
            conn.execute("DELETE FROM clientmon_samples WHERE ip = ? AND t < (SELECT t FROM clientmon_samples "
                         "WHERE ip = ? ORDER BY t DESC LIMIT 1 OFFSET ?)", (addr, addr, keep - 1))


def samples(ip: str, since: float | None = None, limit: int = MAX_SAMPLES_PER_CLIENT) -> list[list]:
    """Verlauf eines Clients: [[t, Abweichung|None, Poll, Version, Abstand|None], …] aufsteigend."""
    import store
    _migrate(store)
    monitor = _MONITOR
    if monitor is not None:
        monitor.flush_samples(prune=False)  # frisch Vorgemerktes mitnehmen
    since = time.time() - SAMPLE_RETENTION if since is None else since
    rows = store.query("SELECT t, offset, poll, version, interval FROM clientmon_samples "
                       "WHERE ip = ? AND t >= ? ORDER BY t DESC LIMIT ?", (ip, since, int(limit)))
    return [list(row) for row in reversed(rows)]


def _migrate(store_mod) -> None:
    store_mod.migrate("clientmon", [
        "CREATE TABLE IF NOT EXISTS clientmon_clients (ip TEXT PRIMARY KEY, data TEXT NOT NULL, "
        "updated REAL NOT NULL)",
        "CREATE INDEX IF NOT EXISTS clientmon_updated ON clientmon_clients(updated)",
        # 1.4: Verlauf je Client (7 Tage) und eigene Namen/Notizen
        "CREATE TABLE IF NOT EXISTS clientmon_samples (ip TEXT NOT NULL, t REAL NOT NULL, offset REAL, "
        "poll INTEGER, version INTEGER, interval REAL);"
        "CREATE INDEX IF NOT EXISTS clientmon_samples_ip_t ON clientmon_samples(ip, t);"
        "CREATE INDEX IF NOT EXISTS clientmon_samples_t ON clientmon_samples(t)",
        "CREATE TABLE IF NOT EXISTS clientmon_meta (ip TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', "
        "note TEXT NOT NULL DEFAULT '', updated REAL NOT NULL)",
    ])


# ---------------------------------------------------------------------------
# MAC-Adresse aus dem Link-Kopf – nur, wenn das Gerät im selben Netz (L2) steht
# ---------------------------------------------------------------------------

ARPHRD_ETHER = 1
# t=None: noch nie gelesen. Nicht 0.0 – monotonic() zählt ab Systemstart, in der ersten Minute
# nach dem Booten galt der leere Anfangs-Cache sonst als frisch (alle Clients „nicht im Netz“).
_ROUTES: dict = {"t": None, "v4": [], "v6": []}
ROUTES_TTL = 60.0


def frame_mac(addr: Any) -> str | None:
    """Absender-MAC aus der sockaddr_ll von recvmsg (nur Ethernet)."""
    try:
        hatype, raw = addr[3], addr[4]
    except (TypeError, IndexError):
        return None
    if hatype != ARPHRD_ETHER or not isinstance(raw, (bytes, bytearray)) or len(raw) < 6:
        return None
    raw = bytes(raw[:6])
    if raw == bytes(6) or raw[0] & 1:  # leer oder Multicast
        return None
    return ":".join(f"{b:02x}" for b in raw)


def _connected_routes() -> tuple[list, list]:
    """Direkt angeschlossene Netze je Interface aus /proc (ohne Gateway)."""
    now = time.monotonic()
    if _ROUTES["t"] is not None and now - _ROUTES["t"] < ROUTES_TTL:
        return _ROUTES["v4"], _ROUTES["v6"]
    v4, v6 = [], []
    try:
        with open("/proc/net/route", encoding="ascii") as handle:
            next(handle, None)
            for line in handle:
                parts = line.split()
                if len(parts) < 8 or parts[2] != "00000000":
                    continue
                dest = socket.inet_ntoa(struct.pack("<I", int(parts[1], 16)))
                mask = socket.inet_ntoa(struct.pack("<I", int(parts[7], 16)))
                if mask == "0.0.0.0":
                    continue
                v4.append((parts[0], ipaddress.ip_network(f"{dest}/{mask}", strict=False)))
    except (OSError, ValueError):
        pass
    try:
        with open("/proc/net/ipv6_route", encoding="ascii") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 10 or parts[4] != "0" * 32 or int(parts[1], 16) == 0:
                    continue
                dest = ipaddress.IPv6Address(bytes.fromhex(parts[0]))
                if dest.is_multicast or dest.is_loopback:
                    continue
                v6.append((parts[9], ipaddress.ip_network(f"{dest}/{int(parts[1], 16)}", strict=False)))
    except (OSError, ValueError):
        pass
    _ROUTES.update(t=now, v4=v4, v6=v6)
    return v4, v6


def on_link(ip: str, ifname: Any) -> bool:
    """Steht der Absender im selben Netz wie das Interface? Sonst ist die MAC die des Routers."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version == 6 and addr.is_link_local:
        return True
    v4, v6 = _connected_routes()
    for name, net in (v4 if addr.version == 4 else v6):
        if (not ifname or name == ifname) and addr in net:
            return True
    return False


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
RETRY_SECONDS = 300.0   # nach einem Fehlstart (z. B. CAP_NET_RAW fehlt) erst so spät erneut
# Letzter Fehlstart: Port und Zeitpunkt (monotonic). Ein anderer Port wird sofort versucht.
_FAILED: dict = {"port": None, "t": None}


def _alive(monitor: Monitor | None) -> bool:
    return monitor is not None and monitor.thread is not None and monitor.thread.is_alive()


def start(port: int = 123) -> dict:
    """Startet die Messung (idempotent; anderer Port → Neustart)."""
    global _MONITOR, _LAST_REASON
    with _LOCK:
        if _MONITOR is not None and _MONITOR.port == port and _alive(_MONITOR):
            return status()
        if _MONITOR is not None:
            _MONITOR.stop()
            _MONITOR = None
        monitor = Monitor(int(port))
        monitor.start()
        if monitor.available:
            _MONITOR = monitor
            _LAST_REASON = None
            _FAILED.update(port=None, t=None)
        else:
            _LAST_REASON = monitor.reason
            _FAILED.update(port=int(port), t=time.monotonic())
    return status()


def stop() -> None:
    global _MONITOR, _LAST_REASON
    with _LOCK:
        if _MONITOR is not None:
            _MONITOR.stop()
            _MONITOR = None
        _LAST_REASON = "Nicht gestartet (in den Einstellungen ausgeschaltet)."
        _FAILED.update(port=None, t=None)


def sync(enabled: bool, port: int) -> None:
    """Passt den Zustand an die Einstellungen an (für den Server-Thread)."""
    if enabled:
        with _LOCK:
            # Läuft nur, wenn der Mess-Thread lebt: endet _run (select/OSError), wird neu gestartet.
            running = _MONITOR is not None and _MONITOR.port == port and _alive(_MONITOR)
            failed_t = _FAILED["t"]
            # Fehlstart auf DIESEM Port: nicht alle 10 s erneut, aber nach RETRY_SECONDS
            # (Rechte nachgereicht?) – ein anderer Port wird sofort versucht.
            wait = _MONITOR is None and _FAILED["port"] == port and failed_t is not None \
                and time.monotonic() - failed_t < RETRY_SECONDS
        if not running and not wait:
            start(port)
    else:
        with _LOCK:
            active = _MONITOR is not None or _FAILED["port"] is not None
        if active:
            stop()  # setzt auch einen Fehlstart zurück: Wiedereinschalten versucht sofort


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
        "running": _alive(monitor),
        "reason": nat_hint(clients, default_gateway()) if _alive(monitor) or not monitor.reason
        else monitor.reason,
        "clients": clients,
        "packets": monitor.packets,
        "ignored": monitor.ignored,
        "kernel_drops": monitor.kernel_drops,
        "filtered": monitor.filtered,
        "port": monitor.port,
        "since": monitor.since,
    }


def client(ip: str) -> dict | None:
    """Ein Client für die Detailseite (private_entry, mit MAC) – aus der laufenden Messung,
    sonst aus dem gespeicherten Zustand. None, wenn unbekannt."""
    monitor = _MONITOR
    if monitor is not None:
        with monitor.table.lock:
            entry = monitor.table.clients.get(ip)
            if entry is not None:
                return private_entry(entry)
    try:
        stored = stored_clients(ip).get(ip)
    except Exception:  # noqa: BLE001
        stored = None
    return private_entry(stored) if stored else None
