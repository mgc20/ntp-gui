#!/bin/bash
# Abnahme-Labor „Schleifen erkennen“ (1.5, Thema 10) – braucht root, iproute2 (ip netns), nft, chronyd.
#
#   sudo tests/lab/loop/run.sh            # alle vier Szenarien mit Prüfung
#   sudo tests/lab/loop/run.sh dns        # ein Szenario, JSON-Ausgabe
#
# Aufbau: Namensraum lab_gui = „ntp-gui“ (chronyd, 10.77.0.5, Fake-Resolver auf 127.0.0.53),
#         Namensraum lab_wan = Router + fremder Zeitserver (chronyd, 10.77.0.9).
# Szenarien:
#   ok       pool.lab.test → 10.77.0.9 (fremd)                        → kein Ereignis
#   dns      Resolver schreibt pool.lab.test auf 10.77.0.5 um         → „DNS-Umschreibung ohne Ausnahme“
#   nat      Quelle 10.77.0.9 per IP, Router-DNAT UDP 123 → ntp-gui
#            ohne Ausnahme (wie UniFi, mit Masquerade für Hairpin)     → „NAT-Umleitung ohne Ausnahme“
#   nat_exc  dieselbe Regel mit Ausnahme „ip saddr != ntp-gui“         → kein Ereignis
# Poll-Intervall 16 s (minpoll/maxpoll 4): Ereignis muss in ≤ 32 s kommen.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
POLL=4
LIMIT=${LIMIT:-70}

scenario() {
  local SC=$1 W=/run/looplab/$1
  rm -rf "$W"; mkdir -p -m 700 "$W"
  (
    cleanup() { for p in $(cat "$W"/*.pid 2>/dev/null); do kill "$p" 2>/dev/null; done; sleep 0.3
      ip netns del lab_gui 2>/dev/null; ip netns del lab_wan 2>/dev/null; rm -rf /etc/netns/lab_gui; }
    trap cleanup EXIT
    ip netns add lab_gui; ip netns add lab_wan
    ip link add vgui netns lab_gui type veth peer name vwan netns lab_wan
    ip -n lab_gui link set lo up; ip -n lab_wan link set lo up
    ip -n lab_gui addr add 10.77.0.5/24 dev vgui; ip -n lab_gui link set vgui up
    ip -n lab_wan addr add 10.77.0.9/24 dev vwan; ip -n lab_wan link set vwan up
    mkdir -p /etc/netns/lab_gui; echo "nameserver 127.0.0.53" > /etc/netns/lab_gui/resolv.conf
    printf 'local stratum 1\nallow all\nbindcmdaddress %s/wan.sock\npidfile %s/wan.cpid\n' "$W" "$W" > "$W/wan.conf"
    ip netns exec lab_wan chronyd -x -d -u root -f "$W/wan.conf" >"$W/wan.log" 2>&1 & echo $! > "$W/wan.pid"
    local TARGET=10.77.0.9; [ "$SC" = dns ] && TARGET=10.77.0.5
    ip netns exec lab_gui python3 -I "$HERE/fakedns.py" 127.0.0.53 53 pool.lab.test $TARGET >"$W/dns.log" 2>&1 &
    echo $! > "$W/dns.pid"
    local SRC="pool pool.lab.test iburst minpoll $POLL maxpoll $POLL maxsources 1"
    if [ "$SC" = nat ] || [ "$SC" = nat_exc ]; then
      SRC="server 10.77.0.9 iburst minpoll $POLL maxpoll $POLL"
      local EXC=""; [ "$SC" = nat_exc ] && EXC="ip saddr != 10.77.0.5"
      ip netns exec lab_wan nft -f - <<N
table ip lab {
 chain pre {
  type nat hook prerouting priority -100;
  iifname "vwan" $EXC udp dport 123 dnat to 10.77.0.5
 }
 chain post {
  type nat hook postrouting priority 100;
  oifname "vwan" ip daddr 10.77.0.5 udp dport 123 masquerade
 }
}
N
    fi
    # wie ntp-gui: Inselbetrieb als Rückfall (local stratum), Quellen darüber; Freigaben wie die
    # Voreinstellung (settings.PRIVATE_NETWORKS) – ohne 127/8, 127.0.0.1 bekommt also keine Antwort.
    ALLOW=$(printf 'allow %s\n' 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 fc00::/7 fe80::/10)
    printf '%s\nlocal stratum 8\n%s\nbindcmdaddress %s/gui.sock\npidfile %s/gui.cpid\n' "$SRC" "$ALLOW" "$W" "$W" > "$W/gui.conf"
    sleep 0.5
    ip netns exec lab_gui chronyd -x -d -u root -f "$W/gui.conf" >"$W/gui.log" 2>&1 & echo $! > "$W/gui.pid"
    for _ in $(seq 50); do ip netns exec lab_gui chronyc -h "$W/gui.sock" tracking >/dev/null 2>&1 && break; sleep 0.1; done
    ip netns exec lab_gui python3 "$HERE/driver.py" "$W/gui.sock" "$LIMIT"
  )
}

if [ $# -ge 1 ]; then scenario "$1"; exit; fi
FAIL=0
expect() { # expect <szenario> <erwarteter Satzteil oder leer>
  local out; out=$(scenario "$1")
  python3 - "$1" "$2" "$out" "$((2 * (1 << POLL)))" <<'P' || FAIL=1
import json, sys
sc, want, out, limit = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), float(sys.argv[4])
ev = out["events"]
if not want:
    ok = not ev
    print(("✓" if ok else "✗"), sc, "kein Ereignis in", out["elapsed"], "s" if ok else f"– aber: {ev}")
else:
    ok = bool(ev) and want in ev[0]["title"] and ev[0]["t"] <= limit
    print(("✓" if ok else "✗"), sc, (f"nach {ev[0]['t']} s: {ev[0]['title']}" if ev else "kein Ereignis"))
sys.exit(0 if ok else 1)
P
}
expect ok ""
expect dns "DNS-Umschreibung ohne Ausnahme für ntp-gui"
expect nat "NAT-Umleitung ohne Ausnahme für ntp-gui"
expect nat_exc ""
exit $FAIL
