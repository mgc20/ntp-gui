"""Labor-Treiber: loopguard.LoopGuard gegen einen echten chronyd (läuft im Namensraum lab_gui).

Aufruf: python3 driver.py <chronyc-Socket> <Sekunden>
Gibt JSON aus: Ereignisse mit Zeitpunkt (s seit Start), Quellen am Ende.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "app"))
import chrony  # noqa: E402
import enforce  # noqa: E402
import loopguard  # noqa: E402

SOCK, LIMIT = sys.argv[1], float(sys.argv[2])


def c(*args):
    return subprocess.run(["chronyc", "-h", SOCK, *args], capture_output=True, text=True, timeout=5).stdout


def detailed():
    srcs = chrony.parse_sources(c("-c", "sources"))
    ntp = {b.get("remote"): b for b in chrony.parse_ntpdata(c("ntpdata"))}
    for s in srcs:
        if s.get("mode") in ("^", "="):
            s["ntp"] = ntp.get(s["name"])
            name = c("sourcename", s["name"]).strip()
            s["hostname"] = name if name and name != s["name"] else None
    return srcs


events = []
start = time.monotonic()
guard = loopguard.LoopGuard(lambda kind, level, title, data=None, source="web": events.append(
    {"t": round(time.monotonic() - start, 1), "kind": kind, "level": level, "title": title, "data": data}),
    prober=enforce.probe_many, tracker=lambda: chrony.parse_tracking(c("-c", "tracking")))
while time.monotonic() - start < LIMIT and not events:
    if guard.due():
        guard.check(detailed(), chrony.parse_tracking(c("-c", "tracking")), loopguard.interface_addresses(), 123)
    time.sleep(0.5)
print(json.dumps({"events": events, "elapsed": round(time.monotonic() - start, 1),
                  "sources": [(s["name"], s.get("hostname"), s.get("state")) for s in detailed()
                              if s.get("mode") == "^"]}, ensure_ascii=False))
