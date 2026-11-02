"""Wer fragt wirklich – und kommt die Anfrage verschlüsselt an? (Reverse Proxy, HTTPS-Hinweis)

ntp-gui spricht selbst nur HTTP (E5: kein TLS im Python-Server). HTTPS kommt von einem
Reverse Proxy davor (Caddy, Nginx Proxy Manager, Zoraxy, Traefik). Dann sieht der Server als
Gegenstelle nur den Proxy; die echte Adresse des Browsers steht im Kopf „X-Forwarded-For“, das
Protokoll des Browsers in „X-Forwarded-Proto“.

Diese Köpfe kann jeder mitschicken. Darum gelten sie NUR, wenn die Gegenstelle in
TRUSTED_PROXIES steht (Standard: leer = niemandem trauen). Sie dienen ausschließlich dem
Zugriffsprotokoll und dem HTTPS-Hinweis – nie einer Zugriffsentscheidung (Anmeldung,
DNS-Rebinding, CSRF bleiben unabhängig davon).

TransportWatch merkt sich, ob Anmeldedaten (Passwort oder API-Schlüssel) zuletzt über
unverschlüsseltes HTTP ankamen, und liefert daraus einen Hinweis für die Übersicht.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from typing import Any, Iterable

MAX_CHAIN = 20          # mehr Einträge in X-Forwarded-For wertet niemand aus
WINDOW = 24 * 3600.0    # so lange bleibt ein Hinweis nach dem letzten Zugriff stehen
SCHEMES = ("http", "https")


def parse_networks(items: Iterable[str] | None) -> list:
    """Liste aus den Einstellungen → ip_network-Objekte; Ungültiges wird übersprungen."""
    out = []
    for item in items or []:
        try:
            net = ipaddress.ip_network(str(item).strip(), strict=False)
        except ValueError:
            continue
        if net.prefixlen == 0:
            continue  # „allen trauen“ gibt es nicht – das hieße: jeder darf seine Adresse fälschen
        out.append(net)
    return out


def parse_ip(text: str | None):
    """Eine Adresse aus einem Kopf: „1.2.3.4“, „1.2.3.4:5678“, „[2001:db8::1]:443“, „fe80::1%eth0“."""
    value = (text or "").strip().strip('"')
    if not value or len(value) > 64:
        return None
    if value.startswith("["):
        value = value[1:].split("]", 1)[0]
    elif value.count(":") == 1:
        value = value.split(":", 1)[0]
    value = value.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if address.version == 6 and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _trusted(address, networks: list) -> bool:
    return address is not None and any(address.version == net.version and address in net for net in networks)


def _header_values(headers: Any, name: str) -> list[str]:
    if headers is None:
        return []
    getter = getattr(headers, "get_all", None)
    raw = getter(name) if getter else None
    if raw is None:
        single = headers.get(name)
        raw = [single] if single else []
    values: list[str] = []
    for line in raw:
        values += [part.strip() for part in str(line).split(",") if part.strip()]
    return values


FORWARD_HEADERS = ("X-Forwarded-For", "X-Forwarded-Proto", "X-Real-IP", "Forwarded")


def resolve(peer: str, headers: Any, networks: list) -> dict[str, Any]:
    """Echte Gegenstelle und Protokoll einer Anfrage.

    Rückgabe: client (Adresse als Text), scheme ("http"/"https"), proxied (über einen
    vertrauenswürdigen Proxy), untrusted_forward (Proxy-Köpfe von einer Gegenstelle, der
    niemand traut – sie wurden ignoriert), peer_loopback.
    """
    peer_ip = parse_ip(peer)
    peer_text = str(peer_ip) if peer_ip is not None else str(peer or "")
    info = {"client": peer_text, "scheme": "http", "proxied": False, "untrusted_forward": False,
            "peer_loopback": bool(peer_ip is not None and peer_ip.is_loopback)}
    has_forward = any(headers is not None and headers.get(name) for name in FORWARD_HEADERS)
    if not _trusted(peer_ip, networks):
        info["untrusted_forward"] = has_forward
        return info
    if not has_forward:
        return info
    info["proxied"] = True
    chain = _header_values(headers, "X-Forwarded-For")[-MAX_CHAIN:]
    client = peer_ip
    # Von rechts lesen: Rechts steht, was der nächste (vertrauenswürdige) Proxy gesehen hat. Die
    # erste Adresse, die selbst kein vertrauenswürdiger Proxy ist, ist der Browser. Alles weiter
    # links könnte der Browser selbst geschrieben haben.
    for entry in reversed(chain):
        address = parse_ip(entry)
        if address is None:
            break
        client = address
        if not _trusted(address, networks):
            break
    info["client"] = str(client)
    protos = [p.lower() for p in _header_values(headers, "X-Forwarded-Proto")]
    if protos and protos[-1] in SCHEMES:
        info["scheme"] = protos[-1]  # vom nächsten Proxy gesetzt – dem, dem wir trauen
    return info


class TransportWatch:
    """Merkt sich, wie Anmeldedaten zuletzt ankamen – für den HTTPS-Hinweis."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.last_plain: float | None = None        # Passwort/Schlüssel über HTTP aus dem Netz
        self.last_untrusted: float | None = None    # Proxy-Köpfe von einer nicht eingetragenen Gegenstelle
        self.last_https: float | None = None
        self.plain_kinds: set[str] = set()

    def note(self, info: dict[str, Any], kind: str | None, now: float | None = None) -> None:
        """kind: "basic" (Passwort) oder "key" (API-Schlüssel); alles andere zählt nicht."""
        if kind not in ("basic", "key"):
            return
        now = self._clock() if now is None else now
        with self._lock:
            if info.get("scheme") == "https":
                self.last_https = now
            elif info.get("untrusted_forward"):
                self.last_untrusted = now
            elif info.get("peer_loopback") and not info.get("proxied"):
                return  # Skript auf demselben Rechner: verlässt den Host nicht
            else:
                self.last_plain = now
                self.plain_kinds.add(kind)

    def reset(self) -> None:
        with self._lock:
            self.last_plain = self.last_untrusted = self.last_https = None
            self.plain_kinds.clear()

    @staticmethod
    def _recent(when: float | None, now: float) -> bool:
        return when is not None and now - when <= WINDOW

    def insights(self, trusted: list | None = None, now: float | None = None) -> list[dict[str, Any]]:
        now = self._clock() if now is None else now
        with self._lock:
            plain = self._recent(self.last_plain, now)
            untrusted = self._recent(self.last_untrusted, now)
            kinds = set(self.plain_kinds)
        out: list[dict[str, Any]] = []
        if plain:
            what = " und ".join(label for key, label in (("basic", "dein Passwort"), ("key", "ein API-Schlüssel"))
                                if key in kinds) or "Anmeldedaten"
            out.append({
                "level": "warn", "key": "web_plain_http", "action": "settings",
                "title": "Dashboard über unverschlüsseltes HTTP mit Anmeldung",
                "text": f"In den letzten 24 Stunden kam {what} über einfaches HTTP an. Basic-Auth und "
                        "Bearer-Schlüssel sind nur Base64 bzw. Klartext – jedes Gerät auf dem Weg (WLAN, "
                        "Switch mit Spiegelport, ein kompromittiertes Smart-Home-Gerät) kann sie mitlesen. "
                        "ntp-gui macht bewusst kein eigenes TLS; setz einen Reverse Proxy davor (fertige "
                        "Caddy-Vorlage in docker-compose.all-in-one.yml, Anleitung in "
                        "docs/integrationen/https.md) und trag seine Adresse in TRUSTED_PROXIES ein. "
                        "Aufrufe von diesem Rechner selbst (127.0.0.1) zählen nicht.",
            })
        if untrusted:
            out.append({
                "level": "info", "key": "web_proxy_untrusted", "action": "settings",
                "title": "Reverse Proxy erkannt, aber nicht eingetragen",
                "text": "Anfragen mit Anmeldung tragen Proxy-Köpfe (X-Forwarded-For/-Proto), kommen aber von "
                        "einer Adresse, die nicht in „Vertrauenswürdige Proxys“ (TRUSTED_PROXIES) steht. "
                        "ntp-gui ignoriert diese Köpfe deshalb – jeder könnte sie fälschen. Folge: Das "
                        "Zugriffsprotokoll zeigt den Proxy statt des Browsers, und ntp-gui kann nicht "
                        "erkennen, ob der Browser HTTPS benutzt. Steht dein Proxy davor, trag seine Adresse "
                        "ein (Caddy auf demselben Host: 127.0.0.1/32 und ::1/128).",
            })
        return out


WATCH = TransportWatch()
