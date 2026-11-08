#!/usr/bin/env python3
"""Erfundenes chronyc für den UI-Rundgang (tests/ui/tour.js): nur Beispieladressen (RFC 5737),
leicht schwankende Werte. Wird über NTPGUI_CHRONYC eingebunden, siehe README.md."""
import math
import sys
import time

args = [a for a in sys.argv[1:] if a not in ("-c", "-n", "-m")]
now = time.time()
w = math.sin(now / 30)
cmd = args[0] if args else ""
if cmd == "tracking":
    print(f"C0000201,192.0.2.1,2,{now:.6f},{0.000012 * w:.9f},{0.000010 * w:.9f},0.000020,1.457,-0.001,0.029,"
          f"0.02,0.000627907,64.0,Normal")
elif cmd == "sources":
    print(f"#,*,GPS,0,4,377,3,{0.0000021 * w:.9f},{0.000002:.9f},0.0000010")
    print(f"^,+,192.0.2.1,1,6,377,20,{0.000150 * w:.9f},0.000140,0.010")
    print(f"^,-,198.51.100.7,2,6,377,22,{-0.000420 * w:.9f},-0.000400,0.020")
    print(f"^,?,203.0.113.9,2,6,0,0,0.0,0.0,0.0")
elif cmd == "sourcestats":
    print("GPS,10,5,150,0.010,0.002,0.0000010,0.0000020")
    print("192.0.2.1,10,5,600,0.050,0.010,0.000140,0.000050")
    print("198.51.100.7,10,5,600,0.090,0.020,-0.000400,0.000080")
elif cmd == "serverstats":
    print("1234,0,0,0,0,0,0,0,0")
elif cmd == "clients":
    print("192.0.2.10,25,0,6,6,4,0,0,0,-,-")
    print("192.0.2.20,12,0,6,6,8,0,0,0,-,-")
elif cmd == "activity":
    print("200 OK\n3 sources online\n0 sources offline\n0 sources doing burst (return to online)\n"
          "0 sources doing burst (return to offline)\n1 sources with unknown address")
elif cmd == "ntpdata":
    sys.exit(1)
else:
    print("200 OK")
