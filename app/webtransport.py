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
import re
import threading
import time
from typing import Any, Iterable

MAX_CHAIN = 20          # mehr Einträge in X-Forwarded-For wertet niemand aus
WINDOW = 24 * 3600.0    # so lange bleibt ein Hinweis nach dem letzten Zugriff stehen
FIXED_WINDOW = 3600.0   # … und nur so lange, wenn danach nur noch geschützte Zugriffe kamen
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


# Alle Köpfe, an denen man einen Proxy erkennt. Ausgewertet werden X-Forwarded-For/-Proto, ersatzweise
# „Forwarded“ (RFC 7239) und für die Adresse zuletzt X-Real-IP. Schickt ein eingetragener Proxy nur
# X-Real-IP (oder gar nur „Forwarded: by=…“), kam die Anfrage trotzdem über ihn – nur sagt er nicht,
# ob der Browser HTTPS sprach (proto_missing), statt fälschlich „direkt per HTTP“.
FORWARD_HEADERS = ("X-Forwarded-For", "X-Forwarded-Proto", "X-Real-IP", "Forwarded")
_PROTO_TOKEN = re.compile(r"[a-z0-9.+-]{1,16}")


def _forwarded_elements(headers: Any) -> list[dict[str, str]]:
    """RFC 7239: „for=1.2.3.4;proto=https, for=…“ → [{"for": …, "proto": …}, …] (links → rechts)."""
    out: list[dict[str, str]] = []
    for element in _header_values(headers, "Forwarded")[-MAX_CHAIN:]:
        pairs: dict[str, str] = {}
        for pair in element.split(";"):
            name, sep, value = pair.partition("=")
            if sep:
                pairs[name.strip().lower()] = value.strip().strip('"')
        out.append(pairs)
    return out


def resolve(peer: str, headers: Any, networks: list) -> dict[str, Any]:
    """Echte Gegenstelle und Protokoll einer Anfrage.

    Rückgabe: client (Adresse als Text), peer (unmittelbare Gegenstelle), scheme ("http"/"https"),
    proxied (über einen vertrauenswürdigen Proxy), proto_missing (vertrauenswürdiger Proxy ohne
    brauchbares X-Forwarded-Proto/Forwarded proto=), untrusted_forward (Proxy-Köpfe von einer
    Gegenstelle, der niemand traut – sie wurden ignoriert), peer_loopback, peer_trusted (Gegenstelle
    steht in TRUSTED_PROXIES), forward_headers (welche Proxy-Köpfe kamen), proto_value (unbekannter
    Proto-Wert, gekürzt; sonst "").
    """
    peer_ip = parse_ip(peer)
    peer_text = str(peer_ip) if peer_ip is not None else str(peer or "")
    info = {"client": peer_text, "peer": peer_text, "scheme": "http", "proxied": False,
            "untrusted_forward": False, "proto_missing": False,
            "peer_loopback": bool(peer_ip is not None and peer_ip.is_loopback),
            "peer_trusted": False, "forward_headers": (), "proto_value": ""}
    sent = tuple(name for name in FORWARD_HEADERS if headers is not None and headers.get(name))
    info["forward_headers"] = sent
    if not _trusted(peer_ip, networks):
        info["untrusted_forward"] = bool(sent)
        return info
    info["peer_trusted"] = True
    if not sent:
        return info  # eingetragene Gegenstelle ganz ohne Proxy-Köpfe: ein direkter Zugriff
    info["proxied"] = True
    xff = _header_values(headers, "X-Forwarded-For")
    xfp = [p.lower() for p in _header_values(headers, "X-Forwarded-Proto")]
    elements = _forwarded_elements(headers)
    # Jede Angabe für sich: Adresse aus X-Forwarded-For, sonst Forwarded for=, sonst X-Real-IP;
    # Protokoll aus X-Forwarded-Proto, sonst Forwarded proto= (z. B. HAProxy mit „option forwardfor“
    # und „option forwarded“).
    chain = xff or [e["for"] for e in elements if e.get("for")]
    if not chain:
        chain = _header_values(headers, "X-Real-IP")[-1:]
    protos = xfp or [e["proto"].lower() for e in elements[-1:] if e.get("proto")]
    client = peer_ip
    # Von rechts lesen: Rechts steht, was der nächste (vertrauenswürdige) Proxy gesehen hat. Die
    # erste Adresse, die selbst kein vertrauenswürdiger Proxy ist, ist der Browser. Alles weiter
    # links könnte der Browser selbst geschrieben haben.
    for entry in reversed(chain[-MAX_CHAIN:]):
        address = parse_ip(entry)
        if address is None:
            break
        client = address
        if not _trusted(address, networks):
            break
    info["client"] = str(client)
    if protos and protos[-1] in SCHEMES:
        info["scheme"] = protos[-1]  # vom nächsten Proxy gesetzt – dem, dem wir trauen
    else:
        info["proto_missing"] = True  # Proxy sagt nicht, wie der Browser sprach – unbekannt, nicht „http“
        if protos:
            info["proto_value"] = protos[-1] if _PROTO_TOKEN.fullmatch(protos[-1]) else "?"
    return info


MAX_SOURCES = 8         # so viele verschiedene Absender merkt sich der Hinweis höchstens
SHOW_SOURCES = 3        # … und so viele nennt er im Text

KIND_LABEL = {"basic": "dein Passwort", "key": "ein API-Schlüssel"}

# Warum kamen Anmeldedaten ungeschützt an? (Ursache → Satzteil im Hinweis)
CAUSE_LABEL = {
    "direct": "direkt per HTTP",
    "direct_proxy": "direkt per HTTP (eingetragener Proxy, aber ohne jeden Proxy-Kopf)",
    "proxy_http": "über den eingetragenen Proxy {via}, aber der Browser sprach mit ihm nur HTTP",
    "untrusted": "über {via}, das Proxy-Köpfe schickt, aber nicht in TRUSTED_PROXIES steht",
}

PROTO_HELP = ("So schickt dein Proxy den Kopf: Caddy, Nginx Proxy Manager, Zoraxy und Traefik setzen "
              "X-Forwarded-Proto von selbst – fehlt er, überschreibt meist eine eigene Regel die Köpfe "
              "(bei NPM unter „Advanced“ nach „proxy_set_header“ suchen; nötig ist "
              "„proxy_set_header X-Forwarded-Proto $scheme;“). Nginx von Hand: dieselbe Zeile im "
              "location-Block. HAProxy: „http-request set-header X-Forwarded-Proto https if { ssl_fc }“ "
              "im frontend. Traefik: am Entrypoint kein „forwardedHeaders.insecure“ und keine Middleware, "
              "die X-Forwarded-Proto entfernt. Apache: nur im <VirtualHost *:443> "
              "„RequestHeader set X-Forwarded-Proto \"expr=%{REQUEST_SCHEME}\"“ – nie pauschal „https“, "
              "sonst gilt auch ein HTTP-Zugriff als geschützt.")


def ago(seconds: float) -> str:
    """„gerade eben“, „vor 12 min“, „vor 3 h“ – für Hinweistexte."""
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return "gerade eben"
    if seconds < 5400:
        return f"vor {round(seconds / 60)} min"
    return f"vor {round(seconds / 3600)} h"


class TransportWatch:
    """Merkt sich, wie Anmeldedaten zuletzt ankamen – für den HTTPS-Hinweis.

    Fälle, je mit Zeitpunkt des letzten Zugriffs:
      plain          Passwort/Schlüssel kam über einfaches HTTP aus dem Netz – je Absender mit
                     Ursache: „direct“ (direkt per HTTP), „proxy_http“ (eingetragener Proxy meldet
                     X-Forwarded-Proto: http), „untrusted“ (Proxy-Köpfe von einer nicht eingetragenen
                     Gegenstelle – die Strecke zu ntp-gui war dann sicher HTTP).
      no_proto       eingetragener Proxy, aber ohne brauchbares X-Forwarded-Proto bzw. Forwarded
                     proto=: Ob der Browser HTTPS sprach, ist unbekannt – eigener Hinweis.
      last_hop_plain Der eingetragene Proxy sitzt auf einem anderen Gerät (Browser → Proxy HTTPS oder
                     unbekannt): Die Strecke Proxy → ntp-gui trägt die Anmeldedaten sicher
                     unverschlüsselt durchs LAN. last_hop_https: dasselbe, Browser sprach nachweislich HTTPS.
      last_https     durchgehend geschützt (Proxy auf demselben Rechner, HTTPS zum Browser).
      last_proto     je Proxy (Gegenstelle): letzter Zugriff MIT Proto-Kopf.
    Ein Hinweis verschwindet, sobald das Problem behoben ist: Kommen danach nur noch geschützte
    Zugriffe, gilt statt 24 Stunden nur noch FIXED_WINDOW (1 Stunde). Einträge „ohne Proto-Kopf“
    gelten nur dann als behoben, wenn DERSELBE Proxy danach den Kopf schickt.

    Die Absenderadressen stehen nur im Hinweis der eigenen, angemeldeten Übersicht. Hinweise
    gehen weder in Benachrichtigungen noch ins Diagnosepaket; wer sie dorthin bringt, muss sie
    durch egress schicken (private Adressen → Pseudonyme).
    """

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.plain: dict[tuple[str, str, str], dict[str, Any]] = {}     # (Ursache, Client, über) → Zugriff
        self.no_proto: dict[tuple[str, str], dict[str, Any]] = {}       # (Proxy, Client) → Zugriff
        self.last_hop_plain: float | None = None    # Proxy auf anderem Gerät: HTTP durchs LAN zu ntp-gui
        self.last_hop_https: float | None = None    # … und der Browser sprach nachweislich HTTPS mit ihm
        self.last_untrusted: float | None = None    # Proxy-Köpfe von einer nicht eingetragenen Gegenstelle
        self.last_https: float | None = None        # durchgehend verschlüsselt
        self.last_proto: dict[str, float] = {}      # Proxy → letzter Zugriff mit Proto-Kopf

    # Kompatibel zu 1.5.0 (Tests, Aufrufer): Zeitpunkt und Arten des letzten Klartext-Zugriffs.
    @property
    def last_plain(self) -> float | None:
        return max((e["at"] for e in self.plain.values()), default=None)

    @property
    def plain_kinds(self) -> set[str]:
        return {k for e in self.plain.values() for k in e["kinds"]}

    @staticmethod
    def _remember(table: dict, key: tuple, kind: str, now: float, **extra: Any) -> None:
        entry = table.get(key)
        if entry is None:
            if len(table) >= MAX_SOURCES:
                del table[min(table, key=lambda k: table[k]["at"])]
            entry = table[key] = {"kinds": set(), **extra}
        entry["at"] = now
        entry["kinds"].add(kind)

    def note(self, info: dict[str, Any], kind: str | None, now: float | None = None) -> None:
        """kind: "basic" (Passwort) oder "key" (API-Schlüssel); alles andere zählt nicht."""
        if kind not in ("basic", "key"):
            return
        now = self._clock() if now is None else now
        loopback = bool(info.get("peer_loopback"))
        client = str(info.get("client") or "unbekannter Adresse")
        peer = str(info.get("peer") or client)
        with self._lock:
            if info.get("untrusted_forward"):
                self.last_untrusted = now
                if loopback:
                    return  # Proxy auf diesem Rechner: die Strecke zu ntp-gui verlässt den Host nicht
                # Was die Köpfe behaupten, zählt nicht: Bei ntp-gui kam die Anfrage per HTTP aus dem Netz.
                self._remember(self.plain, ("untrusted", peer, peer), kind, now)
                return
            if info.get("proxied"):
                self.last_untrusted = None  # ein eingetragener Proxy ist angekommen – Hinweis erledigt
                if not info.get("proto_missing"):
                    if peer not in self.last_proto and len(self.last_proto) >= MAX_SOURCES:
                        del self.last_proto[min(self.last_proto, key=self.last_proto.get)]
                    self.last_proto[peer] = now
                if info.get("scheme") == "https" and not info.get("proto_missing"):
                    if loopback:
                        self.last_https = now
                    else:
                        self.last_hop_plain = self.last_hop_https = now
                    return
                if info.get("proto_missing"):
                    if not loopback:
                        self.last_hop_plain = now  # Proxy → ntp-gui ist sicher HTTP durchs LAN
                    self._remember(self.no_proto, (peer, client), kind, now, loopback=loopback)
                    entry = self.no_proto[(peer, client)]
                    entry["sent"] = tuple(info.get("forward_headers") or ())
                    entry["value"] = str(info.get("proto_value") or "")
                    return
                self._remember(self.plain, ("proxy_http", client, peer), kind, now)
                return
            if loopback:
                return  # Skript auf demselben Rechner: verlässt den Host nicht
            cause = "direct_proxy" if info.get("peer_trusted") else "direct"
            self._remember(self.plain, (cause, client, peer), kind, now)

    def reset(self) -> None:
        """Alles vergessen – nach einer Änderung von TRUSTED_PROXIES gilt die neue Lage."""
        with self._lock:
            self.last_untrusted = self.last_https = self.last_hop_plain = self.last_hop_https = None
            self.last_proto.clear()
            self.plain.clear()
            self.no_proto.clear()

    @staticmethod
    def _recent(when: float | None, now: float, fixed_by: tuple = ()) -> bool:
        """Steht der Hinweis noch? Kam danach nur noch Besseres (fixed_by), gilt FIXED_WINDOW."""
        if when is None:
            return False
        later = any(other is not None and other > when for other in fixed_by)
        return now - when <= (FIXED_WINDOW if later else WINDOW)

    @staticmethod
    def _kinds(kinds: set[str]) -> str:
        return " und ".join(KIND_LABEL[k] for k in ("basic", "key") if k in kinds) or "Anmeldedaten"

    @staticmethod
    def _expiry_note(entries: list[dict[str, Any]], fixed: tuple) -> str:
        if any(other is not None and other > entries[0]["at"] for other in fixed):
            return ("Seitdem kamen nur noch geschützte Zugriffe – der Hinweis verschwindet 1 Stunde nach "
                    "dem letzten ungeschützten von selbst.")
        return ("Der Hinweis verschwindet 1 Stunde nach dem letzten ungeschützten Zugriff, wenn danach "
                "nur noch geschützte kommen, sonst 24 Stunden danach.")

    def _fresh(self, table: dict, now: float, fixed) -> list[dict[str, Any]]:
        """fixed: Zeitpunkte, die einen Eintrag als behoben gelten lassen – oder eine Funktion key → Zeitpunkte."""
        rows = [dict(entry, key=key) for key, entry in table.items()
                if self._recent(entry["at"], now, fixed(key) if callable(fixed) else fixed)]
        rows.sort(key=lambda e: e["at"], reverse=True)
        return rows

    def insights(self, trusted: list | None = None, now: float | None = None) -> list[dict[str, Any]]:
        now = self._clock() if now is None else now
        with self._lock:
            plain_fixed = (self.last_https, self.last_hop_https)
            plain = self._fresh(self.plain, now, plain_fixed)
            # Ohne Proto-Kopf weiß niemand, ob es HTTPS war – „behoben“ ist es, sobald DERSELBE Proxy
            # den Kopf schickt (ein anderer Proxy oder Weg sagt über diesen nichts).
            noproto = self._fresh(self.no_proto, now, lambda key: (self.last_proto.get(key[0]),))
            hop = self._recent(self.last_hop_plain, now, (self.last_https,))
            hop_https = self._recent(self.last_hop_https, now, (self.last_https,))
            untrusted = self._recent(self.last_untrusted, now)
        out: list[dict[str, Any]] = []
        if plain:
            parts = []
            for entry in plain[:SHOW_SOURCES]:
                cause, client, via = entry["key"]
                how = CAUSE_LABEL[cause].format(via=via)
                who = f"von {client} " if cause != "untrusted" else ""
                parts.append(f"{self._kinds(entry['kinds'])} {who}{how}, zuletzt {ago(now - entry['at'])}")
            more = len(plain) - SHOW_SOURCES
            listing = "; ".join(parts) + (f" (und {more} weitere)" if more > 0 else "")
            causes = {e["key"][0] for e in plain}
            advice = []
            if "direct_proxy" in causes:
                advice.append("„eingetragener Proxy, aber ohne jeden Proxy-Kopf“ heißt: Entweder reicht dein "
                              "Proxy die Anfrage ohne X-Forwarded-For/-Proto weiter – dann prüft ntp-gui das "
                              "Protokoll nicht, und die Strecke Proxy → ntp-gui ist ohnehin HTTP –, oder ein "
                              "Programm auf dem Proxy-Gerät ruft http://…:8080 direkt auf. " + PROTO_HELP)
            if "direct" in causes:
                advice.append("„direkt per HTTP“ heißt: Dieses Gerät ruft http://…:8080 selbst auf – ein "
                              "Lesezeichen, eine Home-Assistant-Integration, ein Homepage-/Uptime-Kuma-Widget "
                              "oder ein Skript. Stell es auf die HTTPS-Adresse deines Proxys um oder setz "
                              "WEB_BIND=127.0.0.1, wenn der Proxy auf diesem Rechner läuft.")
            if "proxy_http" in causes:
                advice.append("Beim Proxy „Force SSL“ bzw. die Umleitung HTTP → HTTPS einschalten.")
            if "untrusted" in causes:
                advice.append("Ist das dein Proxy, trag seine Adresse unter „Vertrauenswürdige Proxys“ ein.")
            if not advice or causes == {"direct"}:
                advice.append("Noch kein Proxy? Anleitung mit fertigem Caddy-Beispiel (eigener Stack) in "
                              "docs/integrationen/https.md.")
            out.append({
                "level": "warn", "key": "web_plain_http", "action": "settings",
                "title": "Dashboard über unverschlüsseltes HTTP mit Anmeldung",
                "text": f"Ungeschützt angekommen: {listing}. Basic-Auth und Bearer-Schlüssel sind nur "
                        "Base64 bzw. Klartext – jedes Gerät auf dem Weg (WLAN, Switch mit Spiegelport, ein "
                        "kompromittiertes Smart-Home-Gerät) kann sie mitlesen. " + " ".join(advice) +
                        " Aufrufe von diesem Rechner selbst (127.0.0.1) zählen nicht. "
                        + self._expiry_note(plain, plain_fixed),
            })
        if noproto:
            shown = noproto[:SHOW_SOURCES]
            parts = [f"{self._kinds(e['kinds'])} von {e['key'][1]} über {e['key'][0]}, zuletzt {ago(now - e['at'])}"
                     for e in shown]
            # Je Proxy sagen, was er tatsächlich schickt (neuester Eintrag zählt).
            what: dict[str, str] = {}
            for e in shown:
                proxy = e["key"][0]
                if proxy in what:
                    continue
                if e.get("value"):
                    what[proxy] = (f"{proxy} schickt X-Forwarded-Proto bzw. „Forwarded: proto=“ mit dem "
                                   f"unbekannten Wert „{e['value']}“ (erwartet: http oder https)")
                else:
                    sent = ", ".join(e.get("sent") or ()) or "keine Proxy-Köpfe"
                    what[proxy] = (f"{proxy} schickt {sent}, aber weder X-Forwarded-Proto noch "
                                   "„Forwarded: proto=…“")
            remote = any(not e.get("loopback") for e in noproto)
            if remote:
                certainty = ("ob dein Browser mit dem Proxy HTTPS spricht, ist unbekannt. Sicher ist: Der "
                             "Proxy läuft auf einem anderen Gerät, die Strecke Proxy → ntp-gui ist "
                             "unverschlüsselt (siehe „Strecke Proxy → ntp-gui ist unverschlüsselt“).")
            else:
                certainty = ("ob dein Browser HTTPS benutzt, ist unbekannt – der Proxy läuft auf diesem "
                             "Rechner, das ist also kein Hinweis auf Klartext, nur eine Lücke in der Prüfung.")
            out.append({
                "level": "info", "key": "web_proxy_no_proto", "action": "settings",
                "title": "Eingetragener Proxy meldet nicht, ob HTTPS benutzt wurde",
                "text": f"{'; '.join(parts)}. Der Proxy steht in „Vertrauenswürdige Proxys“, aber "
                        f"{'; '.join(what.values())}. Darum gilt: {certainty} " + PROTO_HELP + " "
                        "Der Hinweis verschwindet 1 Stunde nach dem letzten Zugriff ohne Kopf, wenn derselbe "
                        "Proxy danach nur noch Zugriffe mit Kopf schickt, sonst 24 Stunden danach.",
            })
        if hop:
            out.append({
                "level": "info", "key": "web_proxy_hop_plain", "action": "settings",
                "title": "Strecke Proxy → ntp-gui ist unverschlüsselt",
                "text": ("Dein Browser spricht HTTPS mit dem Reverse Proxy – der Proxy läuft aber auf einem "
                         "anderen Gerät und reicht" if hop_https else
                         "Der eingetragene Reverse Proxy läuft auf einem anderen Gerät und reicht") +
                        " Passwort bzw. API-Schlüssel per einfachem HTTP an ntp-gui "
                        "weiter. Auf dieser Strecke kann jedes Gerät dazwischen mitlesen. Am sichersten: den "
                        "Proxy auf demselben Rechner wie ntp-gui betreiben (Caddy-Beispiel in "
                        "docs/integrationen/https.md) und WEB_BIND=127.0.0.1 setzen. Sonst die Strecke "
                        "auf ein abgetrenntes, vertrauenswürdiges Netz legen und Port 8080 per Firewall nur "
                        "für den Proxy öffnen. Läuft der Proxy auf diesem Rechner in einem eigenen "
                        "Docker-Netz (z. B. 172.18.0.2), verlässt die Strecke den Host nicht – dann kannst "
                        "du diesen Hinweis übergehen.",
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
                        "ein (Proxy im Host-Netzwerk auf demselben Rechner: 127.0.0.1/32 und ::1/128).",
            })
        return out


WATCH = TransportWatch()
