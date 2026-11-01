#!/usr/bin/env python3
"""Erzeugt die README-Grafiken als SVG, jeweils in einer hellen und einer dunklen Variante.

    python3 docs/graphics/make_graphics.py

Die Farben folgen den GitHub-Themes (Primer), damit die Grafiken in beiden
Darstellungen wie ein Teil der Seite wirken. Das README bindet sie per
<picture> ein, GitHub wählt die passende Variante selbst.
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent

THEMES = {
    "light": {
        "bg": "#ffffff", "panel": "#f6f8fa", "card": "#ffffff", "border": "#d0d7de",
        "ink": "#1f2328", "ink2": "#59636e", "muted": "#818b98", "grid": "#e8ecf0",
        "accent": "#0969da", "accent_soft": "#ddf4ff",
        "ntp": "#0969da", "ntp_soft": "#ddf4ff",
        "gps": "#bc4c00", "gps_soft": "#fff1e5",
        "ptp": "#8250df", "ptp_soft": "#fbefff",
        "good": "#1a7f37", "good_soft": "#dafbe1",
    },
    "dark": {
        "bg": "#0d1117", "panel": "#151b23", "card": "#0d1117", "border": "#3d444d",
        "ink": "#f0f6fc", "ink2": "#9198a1", "muted": "#7d8590", "grid": "#262c36",
        "accent": "#4493f8", "accent_soft": "#0d2a4a",
        "ntp": "#4493f8", "ntp_soft": "#0d2a4a",
        "gps": "#f0883e", "gps_soft": "#3a2414",
        "ptp": "#ab7df8", "ptp_soft": "#2a1d47",
        "good": "#3fb950", "good_soft": "#12321d",
    },
}

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Svg:
    def __init__(self, width: int, height: int, t: dict, title: str, desc: str) -> None:
        self.w, self.h, self.t = width, height, t
        self.parts: list[str] = []
        self.head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
            f"<title id=\"title\">{esc(title)}</title><desc id=\"desc\">{esc(desc)}</desc>"
            f"<defs>{self._markers()}</defs>"
        )

    def _markers(self) -> str:
        out = []
        for name in ("ink2", "ntp", "gps", "ptp", "accent", "muted", "good"):
            out.append(
                f'<marker id="arr-{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0.5 L10,5 L0,9.5 z" '
                f'fill="{self.t[name]}"/></marker>'
            )
        return "".join(out)

    def add(self, s: str) -> None:
        self.parts.append(s)

    def rect(self, x, y, w, h, fill, stroke=None, r=12, sw=1, dash=None) -> None:
        stroke_attr = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"{stroke_attr}{dash_attr}/>')

    def text(self, x, y, s, size=15, fill=None, weight=400, anchor="start", mono=False, spacing=None) -> None:
        family = MONO if mono else FONT
        ls = f' letter-spacing="{spacing}"' if spacing else ""
        self.add(
            f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill or self.t["ink"]}" text-anchor="{anchor}"{ls}>{esc(s)}</text>'
        )

    def line(self, points, color="ink2", width=2, dash=None, arrow=True, start_arrow=False) -> None:
        d = "M" + " L".join(f"{x},{y}" for x, y in points)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        end = f' marker-end="url(#arr-{color})"' if arrow else ""
        start = f' marker-start="url(#arr-{color})"' if start_arrow else ""
        self.add(
            f'<path d="{d}" fill="none" stroke="{self.t[color]}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round"{dash_attr}{end}{start}/>'
        )

    def pill(self, x, y, label, fg, bg, size=12, anchor="start") -> float:
        width = len(label) * size * 0.6 + 20
        if anchor == "end":
            x -= width
        self.rect(x, y, width, size + 12, bg, r=(size + 12) / 2)
        self.text(x + width / 2, y + size + 2.5, label, size=size, fill=fg, weight=600, anchor="middle")
        return width

    def save(self, name: str) -> None:
        body = self.head + "".join(self.parts) + "</svg>\n"
        (OUT / name).write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------
# Logo: Zifferblatt mit Funkbögen – Zeit, die ins Netz verteilt wird
# --------------------------------------------------------------------------
def logo_mark(s: Svg, cx: float, cy: float, scale: float, color: str, wave: str) -> None:
    r = 38 * scale
    s.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{6 * scale}"/>')
    for i in range(12):
        angle = math.radians(i * 30)
        inner = r - (9 if i % 3 == 0 else 6) * scale
        outer = r - 3 * scale
        s.add(
            f'<line x1="{cx + inner * math.sin(angle):.1f}" y1="{cy - inner * math.cos(angle):.1f}" '
            f'x2="{cx + outer * math.sin(angle):.1f}" y2="{cy - outer * math.cos(angle):.1f}" '
            f'stroke="{color}" stroke-width="{(3 if i % 3 == 0 else 1.6) * scale:.1f}" stroke-linecap="round"/>'
        )
    s.add(
        f'<path d="M{cx},{cy} L{cx},{cy - 22 * scale} M{cx},{cy} L{cx + 15 * scale},{cy + 9 * scale}" '
        f'stroke="{color}" stroke-width="{5 * scale}" stroke-linecap="round" fill="none"/>'
    )
    s.add(f'<circle cx="{cx}" cy="{cy}" r="{4.5 * scale}" fill="{color}"/>')
    # Funkbögen oben rechts
    ox, oy = cx + 30 * scale, cy - 30 * scale
    for i, rr in enumerate((16, 28, 40)):
        rr *= scale
        a1, a2 = math.radians(-80), math.radians(-10)
        x1, y1 = ox + rr * math.cos(a1), oy + rr * math.sin(a1)
        x2, y2 = ox + rr * math.cos(a2), oy + rr * math.sin(a2)
        opacity = 1 - i * 0.28
        s.add(
            f'<path d="M{x1:.1f},{y1:.1f} A{rr:.1f},{rr:.1f} 0 0 1 {x2:.1f},{y2:.1f}" fill="none" '
            f'stroke="{wave}" stroke-width="{5 * scale:.1f}" stroke-linecap="round" opacity="{opacity:.2f}"/>'
        )


def make_logo() -> None:
    t = THEMES["light"]
    s = Svg(160, 160, t, "ntp-gui", "Logo: Uhr mit Funkbögen")
    logo_mark(s, 74, 86, 1.45, "#0969da", "#1a7f37")
    s.save("logo.svg")


# --------------------------------------------------------------------------
# Banner
# --------------------------------------------------------------------------
def make_banner(theme: str) -> None:
    t = THEMES[theme]
    s = Svg(1200, 300, t, "ntp-gui",
            "Zeitserver-Appliance für das LAN: NTP, GPS und PTP mit Web-Dashboard")
    s.rect(1, 1, 1198, 298, t["panel"], t["border"], r=18)
    # dezente Gitterpunkte rechts
    for gx in range(760, 1180, 28):
        for gy in range(28, 290, 28):
            s.add(f'<circle cx="{gx}" cy="{gy}" r="1.4" fill="{t["grid"]}"/>')
    logo_mark(s, 150, 150, 1.6, t["accent"], t["good"])
    s.text(270, 138, "ntp-gui", size=68, weight=700, spacing="-1.5")
    s.text(272, 182, "Zeitserver-Appliance für das LAN", size=26, fill=t["ink2"], weight=500)
    x = 272
    for label, fg, bg in (
        ("NTP · chrony", t["ntp"], t["ntp_soft"]),
        ("GPS · gpsd", t["gps"], t["gps_soft"]),
        ("PTP · linuxptp", t["ptp"], t["ptp_soft"]),
        ("Web-Dashboard", t["good"], t["good_soft"]),
    ):
        x += s.pill(x, 210, label, fg, bg, size=14) + 10
    # Stratum-Treppe rechts: 0 -> 1 -> 2 als Signet der Zeitverteilung
    steps = [("Stratum 0", "GPS / PPS", t["gps"]), ("Stratum 1", "ntp-gui", t["accent"]),
             ("Stratum 2", "dein LAN", t["good"])]
    for i, (st, sub, color) in enumerate(steps):
        bx, by = 830 + i * 112, 70 + i * 52
        s.rect(bx, by, 100, 58, t["card"], t["border"], r=10)
        s.rect(bx, by, 5, 58, color, r=2)
        s.text(bx + 16, by + 25, st, size=14, weight=700)
        s.text(bx + 16, by + 45, sub, size=13, fill=t["ink2"])
        if i < 2:
            s.line([(bx + 100, by + 29), (bx + 132, by + 29), (bx + 132, by + 52 - 3)], color="muted", width=1.8)
    s.save(f"banner-{theme}.svg")


# --------------------------------------------------------------------------
# Architektur
# --------------------------------------------------------------------------
def make_architecture(theme: str) -> None:
    t = THEMES[theme]
    s = Svg(1200, 640, t, "Architektur von ntp-gui",
            "Zeitquellen (Internet-NTP, GPS, PTP) speisen chronyd im Container; "
            "der verteilt die Zeit per NTP ins LAN, die Adresse kommt per DHCP Option 42.")
    s.rect(1, 1, 1198, 638, t["panel"], t["border"], r=18)

    def header(x, label):
        s.text(x, 46, label, size=13, fill=t["muted"], weight=700, spacing="1.2")

    # --- Spalte 1: Zeitquellen ---
    header(32, "ZEITQUELLEN")
    sources = [
        (135, "Internet-NTP", "pool.ntp.org · PTB", "Stratum 1–3", "ntp"),
        (290, "GPS-Empfänger", "VK-162 per USB, PPS optional", "Stratum 0", "gps"),
        (445, "PTP-Grandmaster", "IEEE 1588 im LAN", "optional", "ptp"),
    ]
    for cy, title, sub, tag, key in sources:
        s.rect(32, cy - 52, 268, 104, t["card"], t["border"])
        s.rect(32, cy - 52, 6, 104, t[key], r=3)
        s.text(56, cy - 14, title, size=19, weight=700)
        s.text(56, cy + 12, sub, size=14, fill=t["ink2"])
        s.pill(56, cy + 24, tag, t[key], t[f"{key}_soft"], size=12)

    # --- Spalte 2: Container ---
    s.rect(352, 66, 496, 548, t["card"], t["border"], r=16, sw=1.5, dash="7 6")
    s.text(376, 46, "DOCKER-CONTAINER", size=13, fill=t["muted"], weight=700, spacing="1.2")
    s.pill(848, 32, "ntp-gui", t["accent"], t["accent_soft"], size=13, anchor="end")

    # chronyd (zentral)
    s.rect(604, 96, 220, 284, t["accent_soft"], t["accent"], r=14, sw=1.5)
    s.text(714, 178, "chronyd", size=26, weight=700, anchor="middle", mono=True)
    s.text(714, 206, "NTP-Server", size=15, fill=t["ink2"], anchor="middle")
    s.text(714, 228, "wählt die beste Quelle,", size=13, fill=t["ink2"], anchor="middle")
    s.text(714, 247, "regelt die Uhr", size=13, fill=t["ink2"], anchor="middle")
    s.pill(714 - 46, 300, "Stratum 1", t["accent"], t["card"], size=13)

    # gpsd
    s.rect(380, 258, 170, 64, t["gps_soft"], t["gps"], r=12, sw=1.2)
    s.text(465, 287, "gpsd", size=18, weight=700, anchor="middle", mono=True)
    s.text(465, 308, "liest NMEA + PPS", size=12.5, fill=t["ink2"], anchor="middle")
    # ptp4l
    s.rect(380, 413, 170, 64, t["ptp_soft"], t["ptp"], r=12, sw=1.2)
    s.text(465, 442, "ptp4l / phc2sys", size=16, weight=700, anchor="middle", mono=True)
    s.text(465, 463, "PTP-Port + NIC-Uhr", size=12.5, fill=t["ink2"], anchor="middle")
    # Dashboard
    s.rect(380, 524, 444, 66, t["good_soft"], t["good"], r=12, sw=1.2)
    s.text(402, 553, "Web-Dashboard", size=18, weight=700)
    s.text(402, 575, ":8080 · /api · /metrics · /healthz", size=13, fill=t["ink2"], mono=True)

    # Pfeile: Quellen -> Container
    s.line([(300, 135), (600, 135)], color="ntp", width=2.2)
    s.text(452, 125, "NTP · UDP 123", size=12.5, fill=t["ink2"], anchor="middle")
    s.line([(300, 290), (376, 290)], color="gps", width=2.2)
    s.text(338, 280, "USB", size=12.5, fill=t["ink2"], anchor="middle")
    s.line([(300, 445), (376, 445)], color="ptp", width=2.2)
    s.text(338, 435, "PTP", size=12.5, fill=t["ink2"], anchor="middle")
    # intern
    s.line([(550, 290), (600, 290)], color="gps", width=2.2)
    s.text(576, 280, "SHM", size=12, fill=t["ink2"], anchor="middle", mono=True)
    s.line([(550, 430), (650, 430), (650, 384)], color="ptp", width=2.2)
    s.text(660, 412, "PHC", size=12, fill=t["ink2"], mono=True)
    s.line([(780, 384), (780, 520)], color="ink2", width=2, dash="5 5")
    s.text(790, 424, "chronyc", size=12, fill=t["ink2"], mono=True)

    # --- Spalte 3: LAN ---
    header(902, "DEIN LAN")
    lan = [
        (135, "NTP-Clients", "PCs, Server, Drucker, IoT", "ntp"),
        (445, "PTP-Slaves", "Hardware-Zeitstempel", "ptp"),
        (557, "Browser · Prometheus", "Status und Metriken", "good"),
    ]
    for cy, title, sub, key in lan:
        s.rect(902, cy - 44, 266, 88, t["card"], t["border"])
        s.rect(902, cy - 44, 6, 88, t[key], r=3)
        s.text(926, cy - 6, title, size=18, weight=700)
        s.text(926, cy + 18, sub, size=14, fill=t["ink2"])

    # DHCP-Karte
    s.rect(902, 230, 266, 120, t["card"], t["border"], dash="6 5")
    s.text(926, 266, "DHCP-Server", size=18, weight=700)
    s.text(926, 290, "verteilt die Adresse", size=14, fill=t["ink2"])
    s.pill(926, 304, "Option 42 → ntp-gui", t["accent"], t["accent_soft"], size=12.5)
    s.line([(1035, 230), (1035, 183)], color="accent", width=2, dash="5 4")

    # Pfeile: Container -> LAN
    s.line([(824, 135), (898, 135)], color="ntp", width=2.2)
    s.line([(550, 462), (870, 462), (870, 445), (898, 445)], color="ptp", width=2.2)
    s.line([(824, 557), (898, 557)], color="good", width=2.2)
    s.save(f"architecture-{theme}.svg")


# --------------------------------------------------------------------------
# DHCP-Ablauf
# --------------------------------------------------------------------------
def make_dhcp(theme: str) -> None:
    t = THEMES[theme]
    s = Svg(1200, 470, t, "Wie ein Client den Zeitserver findet",
            "Ablauf: DHCP-Discover, Offer mit Option 42, Request, Ack, danach NTP-Anfrage an ntp-gui.")
    s.rect(1, 1, 1198, 468, t["panel"], t["border"], r=18)
    lanes = [(190, "Client", "PC, IoT, …", "ink2"), (600, "DHCP-Server", "Router / Firewall", "accent"),
             (1010, "ntp-gui", "192.168.1.10", "good")]
    for x, title, sub, key in lanes:
        s.rect(x - 105, 26, 210, 64, t["card"], t["border"])
        s.rect(x - 105, 26, 210, 5, t[key] if key != "ink2" else t["muted"], r=2)
        s.text(x, 60, title, size=18, weight=700, anchor="middle")
        s.text(x, 80, sub, size=13, fill=t["ink2"], anchor="middle", mono=(key == "good"))
        s.line([(x, 92), (x, 446)], color="muted", width=1.5, dash="3 6", arrow=False)

    def msg(y, x1, x2, label, color="ink2", note=None, highlight=False, dashed=False):
        if highlight:
            lo, hi = min(x1, x2), max(x1, x2)
            s.rect(lo + 12, y - 30, hi - lo - 24, 42, t["accent_soft"], r=8)
        s.line([(x1, y), (x2 - 6 if x2 > x1 else x2 + 6, y)], color=color, width=2.2,
               dash="7 5" if dashed else None)
        mid = (x1 + x2) / 2
        s.text(mid, y - 9, label, size=14.5, weight=600 if highlight else 500,
               fill=t["ink"] if highlight else t["ink2"], anchor="middle")
        if note:
            s.text(mid, y + 22, note, size=12.5, fill=t["muted"], anchor="middle")

    msg(130, 190, 600, "DHCPDISCOVER (Broadcast)", dashed=True)
    msg(190, 600, 190, "DHCPOFFER · Option 42: 192.168.1.10", color="accent", highlight=True)
    msg(250, 190, 600, "DHCPREQUEST", dashed=True)
    msg(310, 600, 190, "DHCPACK · Option 42: 192.168.1.10", color="accent", highlight=True)
    msg(375, 190, 1010, "NTP-Anfrage · UDP 123", color="ntp")
    msg(425, 1010, 190, "Zeit · Stratum 1", color="good")
    # Schritt-Nummern
    for i, y in enumerate((130, 190, 250, 310, 375, 425), start=1):
        s.add(f'<circle cx="52" cy="{y - 5}" r="13" fill="{t["card"]}" stroke="{t["border"]}"/>')
        s.text(52, y, str(i), size=13, weight=700, anchor="middle", fill=t["ink2"])
    s.save(f"dhcp-flow-{theme}.svg")


# --------------------------------------------------------------------------
# Genauigkeit (log-Skala, Bereichsbalken)
# --------------------------------------------------------------------------
def make_accuracy(theme: str) -> None:
    t = THEMES[theme]
    s = Svg(1200, 430, t, "Typische Genauigkeit je Zeitquelle",
            "Logarithmische Skala von 10 Nanosekunden bis 100 Millisekunden. Internet-NTP 1 bis 50 ms, "
            "USB-GPS ohne PPS 1 bis 10 ms, GPS mit PPS 0,1 bis 1 µs, PTP mit Hardware-Zeitstempeln 20 ns bis 1 µs.")
    s.rect(1, 1, 1198, 428, t["panel"], t["border"], r=18)
    x0, x1 = 380, 1150
    lo, hi = -8, -1  # 10 ns .. 100 ms

    def X(seconds: float) -> float:
        return x0 + (math.log10(seconds) - lo) / (hi - lo) * (x1 - x0)

    s.text(40, 52, "Abweichung zur echten Zeit, logarithmisch", size=14, fill=t["muted"], weight=600)
    ticks = [(1e-8, "10 ns"), (1e-7, "100 ns"), (1e-6, "1 µs"), (1e-5, "10 µs"),
             (1e-4, "100 µs"), (1e-3, "1 ms"), (1e-2, "10 ms"), (1e-1, "100 ms")]
    top, bottom = 78, 362
    for value, label in ticks:
        x = X(value)
        s.add(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="{t["grid"]}" stroke-width="1"/>')
        s.text(x, bottom + 26, label, size=13, fill=t["muted"], anchor="middle")
    rows = [
        ("Internet-NTP", "Pool, über das Internet", 1e-3, 5e-2, "ntp", "1–50 ms"),
        ("USB-GPS ohne PPS", "z. B. VK-162, kalibriert", 1e-3, 1e-2, "gps", "1–10 ms"),
        ("GPS mit PPS", "HAT / GPIO, /dev/pps0", 1e-7, 1e-6, "gps", "0,1–1 µs"),
        ("PTP mit HW-Zeitstempeln", "IEEE 1588 im LAN", 2e-8, 1e-6, "ptp", "20 ns–1 µs"),
    ]
    for i, (name, sub, a, b, key, value) in enumerate(rows):
        cy = 112 + i * 66
        s.text(40, cy - 2, name, size=17, weight=700)
        s.text(40, cy + 18, sub, size=13.5, fill=t["ink2"])
        xa, xb = X(a), X(b)
        s.rect(xa, cy - 9, max(xb - xa, 10), 18, t[key], r=9)
        s.text(xb + 12, cy + 5, value, size=14, weight=600, fill=t["ink"])
    s.save(f"accuracy-{theme}.svg")


def main() -> None:
    make_logo()
    for theme in THEMES:
        make_banner(theme)
        make_architecture(theme)
        make_dhcp(theme)
        make_accuracy(theme)
    print("Grafiken geschrieben nach", OUT)


if __name__ == "__main__":
    main()
