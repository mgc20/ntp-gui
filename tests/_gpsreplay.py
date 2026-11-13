"""Replay „USB-GPS drinnen ohne PPS“ (1.5.4): GPS-Fix-Folge über 4 Tage.

Grundlage ist tests/fixtures/gps_vk162_fixflaps.jsonl – eine realistische, anonymisierte
Fix-Folge (nur Zeit ab Beginn, Fix-Art, genutzte Satelliten; keine Position).
Was die Datei nicht enthält, wird deterministisch synthetisiert (fester Startwert):

  * innerhalb einer Episode „unstet“ das Kommen und Gehen des Fix (Fix ~3 min, Lücke ~1,5 min),
  * kurze Aussetzer (20–40 s) auch außerhalb – sie blieben schon in 1.5.3 unter der Haltezeit,
  * die genutzten Satelliten als Zufallsweg 3–7 ab dem Wert im Ereignis; 3 → 2D, 4 → 3D mit
    häufigem Rückfall auf 2D,
  * HDOP passend zur Satellitenzahl (3: 5–20, 4: 3,5–12, 5: 2,2–6, 6: 1,6–4,5, 7: 1,2–3),
  * die Position: ein erfundener Ort, Fehler = HDOP × Entfernungsfehler; der Entfernungsfehler
    (Mehrwege drinnen) ist ein korrelierter Zufallsweg (τ = 2 min, σ = 7 m). eph rechnet der Empfänger
    mit 3 m (2 × 3 m × HDOP) – drinnen zu optimistisch (Sprünge über 100 m trotz Schwelle 3 × eph).
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gps_vk162_fixflaps.jsonl"
HOME = (45.0, 10.0)                       # erfundener Ort, nur für die Rechnung
STEP = 10.0
UERE = 7.0                                # Entfernungsfehler drinnen (m, 1 σ)
EPH_UERE = 3.0                            # so rechnet der Empfänger eph – drinnen zu optimistisch
HDOP = {3: (5.0, 20.0), 4: (3.5, 12.0), 5: (2.2, 6.0), 6: (1.6, 4.5), 7: (1.2, 3.0)}


def events() -> list[dict]:
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if "_" not in r]


def fix_timeline(seed: int = 11) -> list[tuple[float, bool, int]]:
    """[(t, fix, used_start)] in STEP-Schritten über die ganze Aufzeichnung."""
    rng = random.Random(seed)
    evs = events()
    end = evs[-1]["t"] + 3600
    out: list[tuple[float, bool, int]] = []
    i = 0
    fix, unstet, used0 = True, False, 4
    flap_fix, flap_until = True, 0.0
    dropout_until = -1.0
    t = 0.0
    while t < end:
        while i < len(evs) and evs[i]["t"] <= t:
            ev = evs[i]
            if ev["ev"] in ("back", "calm"):
                fix, used0 = True, int(ev.get("used") or 4)
            elif ev["ev"] in ("lost", "gone"):
                fix = False
            if ev["ev"] == "unstet":
                unstet = True
            elif ev["ev"] in ("calm", "gone"):
                unstet = False
            i += 1
        now_fix = fix
        if unstet:
            if t >= flap_until:
                flap_fix = not flap_fix
                flap_until = t + rng.expovariate(1 / (180.0 if flap_fix else 90.0)) + STEP
            now_fix = flap_fix
        elif fix:
            if t >= dropout_until and rng.random() < STEP / 1200.0:
                dropout_until = t + rng.uniform(20.0, 40.0)
            if t < dropout_until:
                now_fix = False
        out.append((t, now_fix, used0))
        t += STEP
    return out


def observations(seed: int = 11, jump=None) -> list[dict]:
    """Beobachtungen wie gnssguard.observation() sie baut (mode, used, hdop, pos) – ohne Zeitquellen.

    jump(t) → (Meter nach Norden, used, hdop) erzwingt einen echten Sprung mit guter Geometrie."""
    rng = random.Random(seed * 7 + 1)
    out = []
    used = 4
    ex = ey = 0.0
    alpha = math.exp(-STEP / 120.0)
    for t, fix, used0 in fix_timeline(seed):
        forced = jump(t) if jump is not None else None   # ein Spoofer liefert immer einen Fix
        if not fix and forced is None:
            out.append({"t": t, "mode": 1, "used": 0, "hdop": None})
            used = used0
            continue
        if rng.random() < STEP / 60.0 * 0.3:
            used = min(7, max(3, used + rng.choice((-1, 1))))
        mode = 2 if used <= 3 else (2 if used == 4 and rng.random() < 0.3 else 3)
        lo, hi = HDOP[used]
        hdop = round(rng.uniform(lo, hi), 1)
        # Positionsfehler ≈ HDOP × Entfernungsfehler; der Entfernungsfehler (Mehrwege drinnen)
        # ändert sich langsam (korreliert über τ = 2 min), die Geometrie springt mit den Satelliten.
        ex = alpha * ex + math.sqrt(1 - alpha * alpha) * rng.gauss(0, UERE)
        ey = alpha * ey + math.sqrt(1 - alpha * alpha) * rng.gauss(0, UERE)
        north, east, u, h = hdop * ex, hdop * ey, used, hdop
        if forced is not None:
            metres, u, h = forced
            mode = 3
            north, east = metres + rng.gauss(0, 3.0), rng.gauss(0, 3.0)
        obs = {"t": t, "mode": mode, "used": u, "hdop": h}
        if mode == 3:
            lat = HOME[0] + north / 111_195.0
            lon = HOME[1] + east / (111_195.0 * math.cos(math.radians(HOME[0])))
            obs["pos"] = (lat, lon, round(2.0 * EPH_UERE * h, 1))
        out.append(obs)
    return out


def samples(seed: int = 11, sources: dict | None = None) -> list[dict]:
    """Messpunkte für statewatch (wie server.collect_sample): {"t", "gps": {mode, used}, "sources"}."""
    rows = []
    for obs in observations(seed):
        sample = {"t": obs["t"], "gps": {"mode": obs["mode"], "used": obs["used"]}}
        if sources is not None:
            sample["sources"] = sources
        rows.append(sample)
    return rows
