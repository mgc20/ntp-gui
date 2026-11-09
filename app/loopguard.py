"""Schleifen-Erkennung (1.5, Thema 10): Fragt chronyd über eine eigene Quelle sich selbst?

Zwei Wege führen in die Schleife (Rückmeldung R1: AdGuard-Umschreibung + UniFi-NAT):

* **DNS-Umschreibung ohne Ausnahme:** AdGuard/Pi-hole schreibt pool.ntp.org auf ntp-gui um,
  und ntp-gui fragt denselben DNS. chronyd bekommt die eigene Adresse – oder, bei Docker im
  Bridge-Netz, die LAN-Adresse des Hosts, die per Portweiterleitung wieder bei ihm landet.
* **NAT-Umleitung ohne Ausnahme:** Der Router leitet jedes ausgehende UDP 123 auf ntp-gui um.
  Die Quelle hat die richtige (fremde) Adresse, aber die Antwort kommt von ntp-gui selbst.

Erkennung je Quelle (nur lesend, nichts an der Zeit wird verändert):

1. **Adresse:** Die Quelladresse ist eine eigene (Interface, Loopback, oder chronyds eigene
   lokale Adresse für diese Verbindung ist gleich der Gegenstelle).
2. **Antwort:** Was chronyd von der Quelle zuletzt bekam (`chronyc ntpdata`), trägt die eigene
   Referenz-ID, den eigenen Stratum (also „unsere Quelle + 1“) und dieselbe Referenzzeit wie
   `chronyc tracking` – das ist die Antwort des eigenen chronyd.
3. **Gegenprobe:** Passt nur ein Teil (Referenz-ID und Stratum, aber die Zeit nicht lesbar)
   oder ist die eigene Uhr unsynchron, fragt ntp-gui die Adresse einmal selbst und vergleicht
   mit der Antwort des eigenen chronyd (`enforce.same_server`). Der eigene chronyd wird über
   127.0.0.1 und seine eigenen LAN-Adressen gefragt (die Standard-Freigaben enthalten 127/8
   nicht); antwortet keiner, gilt `chronyc tracking` direkt vor und nach der Probe als eigene
   Antwort (wie der Selbsttest). Höchstens alle 5 min je Adresse; ein nicht vergleichbares
   Ergebnis wird einmal nach 60 s wiederholt, danach auch nur alle 5 min – damit kein
   öffentlicher Server zu viele Anfragen bekommt. Ohne vergleichbare Gegenprobe reicht die
   passive Übereinstimmung bei öffentlichen Adressen nicht (ein anderer Server mit derselben
   Quelle sieht ähnlich aus).

Ursache: Quelle per **Name** und Adresse eigen bzw. im LAN → DNS-Umschreibung. Adresse
fremd/öffentlich (oder Quelle per **fester IP**) und Antwort eigen → NAT-Umleitung. Eine fest
eingetragene eigene IP heißt „self_ip“ (Tippfehler in der Quellenliste).

Ein Ereignis entsteht erst, wenn zwei Prüfungen in Folge dasselbe sagen (wie statewatch).
Die Prüfung läuft im Takt des halben kleinsten Poll-Intervalls (10–60 s, eigener Thread,
unabhängig vom Verlaufs-Takt), dadurch steht das Ereignis spätestens zwei Poll-Intervalle
nach der ersten Antwort im Protokoll.

Der Zustand hängt am Quellnamen; ein Name, den `chronyc sourcename` einmal nicht liefert,
wird je Adresse gemerkt – ein Aussetzer erzeugt kein „beendet“/„neu“-Paar. „Schleife
behoben … erreicht wieder einen fremden Server“ steht nur da, wenn seit der Schleife eine
gültige fremde Antwort kam; sonst „Schleife bei … beendet – die Quelle antwortet derzeit nicht“.

Titel nennen nur Quellnamen bzw. öffentliche Adressen – keine LAN-Adressen (F5: in
Benachrichtigungen nur eigene Gerätenamen; Adressen stehen in den Ereignisdaten).
"""

from __future__ import annotations

import calendar
import ipaddress
import threading
import time
from typing import Any, Callable

CONFIRM = 2
MIN_INTERVAL = 10.0
MAX_INTERVAL = 60.0
PROBE_EVERY = 300.0         # Gegenprobe je Adresse höchstens so oft
PROBE_TIMEOUT = 1.0
REFTIME_TOLERANCE = 1.5     # ntpdata zeigt die Referenzzeit nur auf die Sekunde
MAX_SOURCES = 32

CAUSE_LABEL = {"dns": "DNS-Umschreibung", "nat": "NAT-Umleitung", "self_ip": "eigene Adresse als Quelle"}
EVIDENCE_LABEL = {
    "address": "Adresse ist eine eigene",
    "reply": "Antwort trägt eigene Referenz-ID, eigenen Stratum und eigene Referenzzeit",
    "probe": "Gegenprobe: dort antwortet dieser Server",
}


def _ip(text: Any) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(str(text or "").strip().strip("[]").split("%")[0])
    except ValueError:
        return None


def own_set(addresses: list[str] | None, sources: list[dict] | None = None) -> set[str]:
    """Eigene Adressen: übergebene (Interfaces, Browser-Adresse) plus die lokalen Adressen,
    die chronyd je Quelle benutzt (ntpdata „Local address“) – die sind sicher eigene."""
    out: set[str] = set()
    for addr in addresses or []:
        ip = _ip(addr)
        if ip is not None and not ip.is_unspecified:
            out.add(str(ip))
    for src in sources or []:
        ntp = (src or {}).get("ntp") or {}
        ip = _ip(ntp.get("local"))
        if ip is not None and not ip.is_unspecified:
            out.add(str(ip))
    return out


FIB_TRIE = "/proc/net/fib_trie"
IF_INET6 = "/proc/net/if_inet6"


def parse_fib_trie(text: str) -> list[str]:
    """Eigene IPv4-Adressen aus /proc/net/fib_trie: die Zeile vor „/32 host LOCAL“."""
    out: list[str] = []
    last = None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("|--"):
            last = stripped[3:].strip()
        elif stripped.startswith("/32 host LOCAL") and last:
            ip = _ip(last)
            if ip is not None and str(ip) not in out:
                out.append(str(ip))
    return out


def parse_if_inet6(text: str) -> list[str]:
    """Eigene IPv6-Adressen aus /proc/net/if_inet6 (32 Hex-Zeichen je Zeile)."""
    out: list[str] = []
    for line in (text or "").splitlines():
        raw = line.split()[0] if line.split() else ""
        if len(raw) != 32:
            continue
        try:
            ip = ipaddress.IPv6Address(bytes.fromhex(raw))
        except ValueError:
            continue
        if str(ip) not in out:
            out.append(str(ip))
    return out


def interface_addresses(fib_trie: str = FIB_TRIE, if_inet6: str = IF_INET6) -> list[str]:
    """Alle Adressen der Interfaces im eigenen Netz-Namensraum (Container: dessen eigene).
    Stdlib kennt keine Interface-Adressen; /proc/net ist je Namensraum und billig zu lesen."""
    out: list[str] = []
    for path, parse in ((fib_trie, parse_fib_trie), (if_inet6, parse_if_inet6)):
        try:
            with open(path, encoding="ascii", errors="replace") as handle:
                text = handle.read(1_000_000)
        except OSError:
            continue
        out += [a for a in parse(text) if a not in out]
    return out


def parse_reftime(text: Any) -> float | None:
    """„Mon Nov 02 08:20:17 2026“ (chronyc ntpdata, UTC) → Epoch-Sekunden."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return float(calendar.timegm(time.strptime(text.strip(), "%a %b %d %H:%M:%S %Y")))
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _usable_stratum(value: Any) -> bool:
    num = _num(value)
    return num is not None and 0 < num < 16


def reply_pattern(ntp: dict | None, tracking: dict | None) -> str | None:
    """Vergleicht die letzte Antwort einer Quelle (ntpdata) mit dem eigenen tracking.

    "match"   – Referenz-ID, Stratum und Referenzzeit (± 1,5 s) wie beim eigenen chronyd.
    "partial" – Referenz-ID und Stratum gleich, Zeit nicht vergleichbar oder abweichend
                (z. B. ein anderer Server mit derselben Quelle) → Gegenprobe.
    None      – kein Hinweis auf eine Schleife.
    """
    if not ntp or not tracking:
        return None
    own_ref = str(tracking.get("ref_id") or "").strip().upper()
    ref = str(ntp.get("reference_id") or "").strip().upper()
    if not own_ref or own_ref == "00000000" or ref != own_ref:
        return None
    if not _usable_stratum(tracking.get("stratum")) or _num(ntp.get("stratum")) != _num(tracking.get("stratum")):
        return None
    theirs = parse_reftime(ntp.get("reference_time"))
    ours = _num(tracking.get("ref_time"))
    if theirs is not None and ours is not None and abs(theirs - int(ours)) <= REFTIME_TOLERANCE:
        return "match"
    return "partial"


def _unsynced(tracking: dict | None) -> bool:
    if not tracking:
        return True
    return not _usable_stratum(tracking.get("stratum")) or str(tracking.get("ref_id") or "") in ("", "00000000")


def fingerprint_match(reply: dict | None, ours: dict | None) -> bool:
    """Antwort einer Adresse == Antwort des eigenen chronyd? Synchron: enforce.same_server
    (Stratum, Referenz-ID, Referenzzeit ± 2 ms). Unsynchron (beide leap 3, keine Referenzzeit):
    gleiche Referenz-ID, Präzision und Root-Werte – im selben Augenblick gefragt."""
    import enforce
    if enforce.same_server(reply, ours):
        return True
    if not reply or not ours:
        return False
    if reply.get("leap") != 3 or ours.get("leap") != 3:
        return False
    if reply.get("ref_id") != ours.get("ref_id") or reply.get("precision") != ours.get("precision"):
        return False
    if reply.get("stratum") != ours.get("stratum"):
        return False
    for key in ("root_delay", "root_dispersion"):
        a, b = _num(reply.get(key)), _num(ours.get(key))
        if a is None or b is None or abs(a - b) > 0.002:
            return False
    return True


def _refid_of(addr: str) -> str | None:
    """Referenz-ID, die ein Server trägt, der von dieser IPv4-Adresse synchronisiert."""
    ip = _ip(addr)
    if ip is None or ip.version != 4:
        return None
    return ip.packed.hex().upper()


def foreign_reply(src: dict | None, own: set[str], since_rx: float | None, same_address: bool) -> bool:
    """Kam von dieser Quelle seit der Schleife eine gültige Antwort eines fremden Servers?

    Gültig: Stratum 1–15, Referenz-ID ist keine eigene Adresse (sonst synchronisiert der Server
    von uns), und der Zähler gültiger Antworten ist gestiegen (gleiche Adresse) bzw. > 0 (neue
    Adresse – chronyd zählt dann neu)."""
    ntp = (src or {}).get("ntp") or {}
    if not ntp or not _usable_stratum(ntp.get("stratum")):
        return False
    ref = str(ntp.get("reference_id") or "").strip().upper()
    if ref in {_refid_of(a) for a in own}:
        return False
    rx = _num(ntp.get("total_valid_rx"))
    if rx is None or rx <= 0:
        return False
    if same_address and since_rx is not None:
        return rx > since_rx
    return True


def assess(source: dict, own: set[str], tracking: dict | None,
           probes: dict[str, bool | None] | None = None, ntp_port: int | None = None) -> dict | None:
    """Entscheidung für eine Quelle aus chrony.detailed_sources(). None = keine Schleife.

    probes: Ergebnis der Gegenprobe je Adresse (True = dort antwortet dieser Server,
    False = ein fremder, None/fehlt = nicht geprüft oder nicht vergleichbar).
    ntp_port: eigener NTP-Port. Eine eigene Adresse mit anderem Port (laut chronyc ntpdata) ist
    ein anderer Server auf demselben Rechner, keine Schleife – dann zählen nur Antwort/Gegenprobe."""
    if not isinstance(source, dict) or source.get("mode") not in ("^", "="):
        return None
    ip = _ip(source.get("name"))
    if ip is None:
        return None
    addr = str(ip)
    host = str(source.get("hostname") or "").strip().rstrip(".").lower() or None
    ntp = source.get("ntp") or {}
    evidence: list[str] = []
    remote_port = _num(ntp.get("remote_port"))
    other_port = bool(ntp_port) and remote_port is not None and int(remote_port) != int(ntp_port)
    if (addr in own or ip.is_loopback) and not other_port:
        evidence.append("address")
    elif addr in own or ip.is_loopback:
        pass  # eigener Rechner, aber anderer Port: anderer Server (z. B. chronyd des Hosts)
    else:
        remote, local = _ip(ntp.get("remote")), _ip(ntp.get("local"))
        if remote is not None and remote == local:
            evidence.append("address")
    probes = probes or {}
    probe = probes.get(addr)
    # Gegenprobe gelaufen, aber nicht vergleichbar: bei öffentlichen Adressen reicht die passive
    # Übereinstimmung dann nicht – ein fremder Server mit derselben Quelle (Pool-Server an der
    # PTB) trägt dieselbe Referenz-ID, denselben Stratum und oft dieselbe Sekunde.
    inconclusive_public = addr in probes and probe is None and ip.is_global
    if probe is True:
        evidence.append("probe")
    elif probe is None and not inconclusive_public and reply_pattern(ntp, tracking) == "match":
        # Ohne Gegenprobe zählt die passive Übereinstimmung; eine Gegenprobe mit fremder
        # Antwort hat Vorrang (ein anderer Server mit derselben Quelle sieht ähnlich aus).
        evidence.append("reply")
    if not evidence:
        return None
    if "address" in evidence:
        cause = "dns" if host else "self_ip"
    elif host and (ip.is_private or ip.is_link_local) and not ip.is_loopback:
        # Öffentlicher Name, Antwort eigen, Adresse im LAN: DNS hat auf den Host umgeschrieben
        # (Docker im Bridge-Netz kennt die LAN-Adresse des Hosts nicht als eigene).
        cause = "dns"
    else:
        cause = "nat"
    return {"key": host or addr, "host": host, "address": addr, "by": "name" if host else "ip",
            "cause": cause, "cause_label": CAUSE_LABEL[cause], "evidence": evidence,
            "title": sentence(host, addr, cause), "level": "crit"}


def _label(host: str | None, addr: str) -> str:
    """Name der Quelle für Titel – LAN-Adressen nie (F5), öffentliche Adressen schon."""
    if host:
        return host
    ip = _ip(addr)
    if ip is not None and ip.is_global:
        return addr
    return "Eine Zeitquelle im LAN"


def sentence(host: str | None, addr: str, cause: str) -> str:
    label = _label(host, addr)
    if cause == "dns":
        return f"{label} zeigt auf dich selbst – vermutlich DNS-Umschreibung ohne Ausnahme für ntp-gui"
    if cause == "nat":
        return f"{label} zeigt auf dich selbst – vermutlich NAT-Umleitung ohne Ausnahme für ntp-gui"
    return "Eine Zeitquelle ist eine eigene Adresse von ntp-gui – chronyd fragt sich selbst"


REMEDY = {
    "dns": "Der DNS-Server im LAN schreibt den Namen auf ntp-gui um, und ntp-gui fragt denselben DNS. "
           "Abhilfe: unter System → Einstellungen → Quellen → „DNS für ntp-gui“ eigene Server (DoT/DoH) "
           "eintragen, oder im "
           "DNS-Server eine Ausnahme für die IP von ntp-gui anlegen (AdGuard: „client=~<IP>“ in der Regel "
           "bzw. eigener Client ohne Umschreibung).",
    "nat": "Der Router leitet ausgehendes NTP (UDP 123) auch von ntp-gui auf ntp-gui um. Abhilfe: in der "
           "NAT-Regel die Adresse von ntp-gui als Quelle ausnehmen (UniFi: Quelle ≠ ntp-gui) oder ntp-gui "
           "in ein eigenes Netz legen, auf das die Regel nicht wirkt.",
    "self_ip": "In der Quellenliste steht eine Adresse, unter der ntp-gui selbst erreichbar ist. Trag dort "
               "einen fremden Server ein.",
}


def poll_interval(sources: list[dict] | None) -> float | None:
    """Kleinstes Poll-Intervall (s) der NTP-Quellen aus `chronyc sources` (log2)."""
    best = None
    for src in sources or []:
        if not isinstance(src, dict) or src.get("mode") not in ("^", "="):
            continue
        poll = _num(src.get("poll"))
        if poll is None or not -6 <= poll <= 24:
            continue
        seconds = 2.0 ** poll
        best = seconds if best is None else min(best, seconds)
    return best


def check_interval(sources: list[dict] | None) -> float:
    poll = poll_interval(sources)
    if poll is None:
        return 30.0
    return max(MIN_INTERVAL, min(MAX_INTERVAL, poll / 2.0))


class LoopGuard:
    """Hält den bestätigten Schleifen-Zustand je Quelle und schreibt Ereignisse.

    emit(kind, level, title, data, source="web") wie events.emit.
    prober(targets, timeout) wie enforce.probe_many (nur für die Gegenprobe).
    tracker() wie chrony.tracking – frische eigene Referenz direkt vor/nach der Gegenprobe,
    wenn der eigene chronyd über 127.0.0.1/LAN nicht antwortet (fehlt: das übergebene tracking).
    """

    def __init__(self, emit: Callable[..., Any], *, prober: Callable[..., dict] | None = None,
                 tracker: Callable[[], dict | None] | None = None,
                 confirm: int = CONFIRM, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._emit = emit
        self._prober = prober
        self._tracker = tracker
        self._confirm = max(1, int(confirm))
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        # key -> {"loop": dict|None, "streak": int, "since": wall, "rx": float|None, "address": str|None}
        self._state: dict[str, dict] = {}
        self._probes: dict[str, tuple[float, bool | None, int]] = {}  # Adresse -> (fällig ab, Ergebnis, Fehlversuche)
        self._names: dict[str, str] = {}       # Adresse -> zuletzt bekannter Quellname
        self._last_mono: float | None = None
        self._last_wall: float | None = None
        self._interval = 30.0

    # --- Zeitplan ----------------------------------------------------------------
    def due(self) -> bool:
        with self._lock:
            return self._last_mono is None or self._clock() - self._last_mono >= self._interval

    def seconds_until_due(self) -> float:
        with self._lock:
            if self._last_mono is None:
                return 0.0
            return max(0.0, self._interval - (self._clock() - self._last_mono))

    # --- Gegenprobe --------------------------------------------------------------
    def _fresh_tracking(self, fallback: dict | None) -> dict | None:
        if not self._tracker:
            return fallback
        try:
            return self._tracker() or fallback
        except Exception:
            return fallback

    def _probe(self, candidates: list[str], ntp_port: int, tracking: dict | None,
               own_locals: list[str]) -> dict[str, bool | None]:
        if not self._prober or not candidates:
            return {}
        now = self._clock()
        out: dict[str, bool | None] = {}
        todo = []
        for addr in candidates:
            last = self._probes.get(addr)
            if last is not None and now < last[0]:
                out[addr] = last[1]
            else:
                todo.append(addr)
        if not todo:
            return out
        port = int(ntp_port or 123)
        # Der eigene chronyd: 127.0.0.1 (nur mit „allow 127.0.0.1“) und seine LAN-Adressen
        # (von den Standard-Freigaben gedeckt).
        refs = [("127.0.0.1", port)] + [(a, port) for a in own_locals[:2]]
        before = self._fresh_tracking(tracking)
        targets = refs + [(addr, 123) for addr in todo if (addr, 123) not in refs]
        try:
            replies = self._prober(targets, PROBE_TIMEOUT) or {}
        except Exception:
            return out
        import enforce
        ours_list = [replies.get(ref) for ref in refs if replies.get(ref)]
        if not ours_list and not _unsynced(before):
            # Kein eigener chronyd erreichbar: tracking direkt vor und nach der Probe (die
            # Referenzzeit kann sich dazwischen ändern, z. B. GPS alle 16 s).
            after = self._fresh_tracking(None) if self._tracker else None
            ours_list = [o for o in (enforce.ours_from_tracking(before),
                                     enforce.ours_from_tracking(after) if not _unsynced(after) else None) if o]
        for addr in todo:
            reply = replies.get((addr, 123))
            # Ohne eigene Referenz oder ohne Antwort der Adresse ist nichts vergleichbar (None).
            hit = any(fingerprint_match(reply, ours) for ours in ours_list) if ours_list and reply else None
            misses = 0 if hit is not None else (self._probes.get(addr, (0.0, None, 0))[2] + 1)
            # Nicht vergleichbar: einmal nach 60 s erneut, danach auch nur alle 5 min.
            wait = PROBE_EVERY if hit is not None or misses > 1 else 60.0
            self._probes[addr] = (now + wait, hit, misses)
            out[addr] = hit
        if len(self._probes) > 256:
            for key in sorted(self._probes, key=lambda k: self._probes[k][0])[:64]:
                self._probes.pop(key, None)
        return out

    # --- Prüfung -----------------------------------------------------------------
    def _named(self, src: dict) -> dict:
        """Kopie der Quelle mit dem zuletzt bekannten Namen, falls chronyc ihn gerade nicht lieferte."""
        ip = _ip(src.get("name"))
        host = str(src.get("hostname") or "").strip().rstrip(".").lower() or None
        if ip is None:
            return src
        addr = str(ip)
        if host:
            self._names[addr] = host
        else:
            host = self._names.get(addr)
        return dict(src, hostname=host)

    def check(self, sources: list[dict] | None, tracking: dict | None, own_addresses: list[str] | None,
              ntp_port: int = 123) -> list[dict]:
        """Eine Prüfung. sources leer/None = chronyd hat nicht geantwortet → Zustand bleibt."""
        with self._lock:
            self._last_mono, self._last_wall = self._clock(), self._wall()
            if not sources:
                return self._current()
            self._interval = check_interval(sources)
            ntp_sources = [self._named(s) for s in sources
                           if isinstance(s, dict) and s.get("mode") in ("^", "=")][:MAX_SOURCES]
            addresses = {str(ip) for ip in (_ip(s.get("name")) for s in ntp_sources) if ip is not None}
            for addr in [a for a in self._names if a not in addresses]:
                del self._names[addr]
            own = own_set(own_addresses, ntp_sources)
            own_locals = []
            for src in ntp_sources:
                ip = _ip(((src.get("ntp") or {}).get("local")))
                if ip is not None and not ip.is_unspecified and not ip.is_loopback and str(ip) not in own_locals:
                    own_locals.append(str(ip))
            suspects = []
            for src in ntp_sources:
                ip = _ip(src.get("name"))
                if ip is None or str(ip) in own or ip.is_loopback:
                    continue
                pattern = reply_pattern(src.get("ntp"), tracking)
                ntp = src.get("ntp") or {}
                if pattern in ("match", "partial") or (_unsynced(tracking) and ntp and (_num(ntp.get("total_valid_rx")) or 0) > 0):
                    suspects.append(str(ip))
            probes = self._probe(list(dict.fromkeys(suspects)), ntp_port, tracking, own_locals)
            found: dict[str, dict] = {}
            current: dict[str, dict] = {}
            for src in ntp_sources:
                ip = _ip(src.get("name"))
                if ip is None:
                    continue
                host = src.get("hostname")
                current.setdefault(host or str(ip), src)
                # Name kam erst jetzt dazu: Zustand unter der Adresse auf den Namen umhängen.
                if host and str(ip) in self._state and host not in self._state:
                    self._state[host] = self._state.pop(str(ip))
                verdict = assess(src, own, tracking, probes, ntp_port)
                if verdict and verdict["key"] not in found:
                    found[verdict["key"]] = verdict
            self._update(found, current, own)
            return self._current()

    def _update(self, found: dict[str, dict], current: dict[str, dict], own: set[str]) -> None:
        for key in set(self._state) | set(found):
            state = self._state.setdefault(key, {"loop": None, "streak": 0, "since": None,
                                                  "rx": None, "address": None})
            loop = found.get(key)
            if loop:
                # Antwortzähler, solange die Schleife sichtbar ist: was danach kommt, ist neu.
                state["rx"] = _num(((current.get(key) or {}).get("ntp") or {}).get("total_valid_rx"))
                state["address"] = loop["address"]
            active = state["loop"] is not None
            if bool(loop) == active:
                state["streak"] = 0
                if loop:
                    state["loop"] = dict(loop, since=state["since"])  # Ursache/Belege aktuell halten
                continue
            state["streak"] += 1
            if state["streak"] < self._confirm:
                continue
            state["streak"] = 0
            if loop:
                state["since"] = self._wall()
                state["loop"] = dict(loop, since=state["since"])
                self._send("crit", loop["title"], {
                    "host": loop["host"], "address": loop["address"], "cause": loop["cause"],
                    "by": loop["by"], "evidence": loop["evidence"], "state": "loop"})
            else:
                old = state["loop"]
                src = current.get(key)
                label = _label(old.get("host"), old.get("address") or "")
                if src is None:
                    title, how = f"Schleife bei {label} beendet – die Quelle ist nicht mehr eingetragen", "gone"
                else:
                    same = _ip(src.get("name")) is not None and str(_ip(src.get("name"))) == state.get("address")
                    if foreign_reply(src, own, state.get("rx"), same):
                        title, how = f"Schleife behoben: {label} erreicht wieder einen fremden Server", "foreign"
                    else:
                        title, how = f"Schleife bei {label} beendet – die Quelle antwortet derzeit nicht", "silent"
                self._send("info", title, {"host": old.get("host"), "address": old.get("address"),
                                           "cause": old.get("cause"), "state": "resolved", "how": how,
                                           "duration_s": round(self._wall() - (state["since"] or self._wall()))})
                state.update(loop=None, since=None, rx=None, address=None)
        for key in [k for k, s in self._state.items() if s["loop"] is None and s["streak"] == 0 and k not in found]:
            del self._state[key]

    def _send(self, level: str, title: str, data: dict) -> None:
        try:
            self._emit("source", level, title, data, source="web")
        except Exception:  # Ereignisse sind nie kritisch
            pass

    def _current(self) -> list[dict]:
        return [dict(s["loop"]) for s in self._state.values() if s["loop"]]

    # --- Lesen -------------------------------------------------------------------
    def loops(self) -> list[dict]:
        with self._lock:
            return self._current()

    def status(self) -> dict:
        with self._lock:
            loops = self._current()
            return {"loops": [dict(l, remedy=REMEDY.get(l["cause"], "")) for l in loops],
                    "checked": self._last_wall, "interval_s": self._interval,
                    "confirm": self._confirm, "level": "crit" if loops else "good"}


def insights(loops: list[dict] | None) -> list[dict]:
    """Hinweise für die Übersicht: je Ursache einer (dns → Einstellungen, nat → Anleitungen)."""
    out = []
    by_cause: dict[str, list[dict]] = {}
    for loop in loops or []:
        by_cause.setdefault(loop.get("cause") or "nat", []).append(loop)
    titles = {"dns": "Schleife durch DNS-Umschreibung", "nat": "Schleife durch NAT-Umleitung",
              "self_ip": "Schleife: eigene Adresse als Quelle"}
    keys = {"dns": "dns_loop", "nat": "loop_nat", "self_ip": "loop_self"}
    actions = {"dns": "settings", "nat": "clients", "self_ip": "sources"}
    for cause, items in by_cause.items():
        lines = "; ".join(dict.fromkeys(item.get("title") or "" for item in items))
        out.append({"level": "crit", "title": titles.get(cause, "Schleife"),
                    "text": f"{lines}. chronyd fragt dann sich selbst und hat keine echte Quelle. "
                            + REMEDY.get(cause, ""),
                    "action": actions.get(cause, "sources"), "key": keys.get(cause, "loop_nat")})
    return out
