#!/usr/bin/env bash
# Integrationstest gegen ein gebautes Image.
#
#   docker build -t ntp-gui:test .
#   tests/container-test.sh ntp-gui:test
#
# Prüft das Laufzeitverhalten, das sich mit Unittests nicht abbilden lässt:
# Capability-Erkennung, Healthcheck, Basic-Auth, gemountete Konfiguration,
# Verhalten ohne GPS-/PTP-Hardware und sauberes Stoppen.
set -uo pipefail

IMAGE="${1:-ntp-gui:test}"
PREFIX="ntpgui-it-$$"
CFG_DIR="$(mktemp -d)"
PASS=0
FAIL=0

cleanup() {
  docker rm -f "${PREFIX}-a" "${PREFIX}-b" "${PREFIX}-c" >/dev/null 2>&1
  rm -rf "$CFG_DIR"
}
trap cleanup EXIT

ok()   { PASS=$((PASS + 1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  \033[31m✗\033[0m %s\n' "$1"; }
check() { # check <Beschreibung> <erwartet> <tatsächlich>
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (erwartet: $2, war: $3)"; fi
}
contains() { # contains <Beschreibung> <Text> <Suchbegriff>
  if grep -qF -e "$3" <<<"$2"; then ok "$1"; else bad "$1 (»$3« fehlt)"; fi
}
http() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }

wait_for_health() { # wait_for_health <url> <sekunden>
  local url="$1" limit="${2:-60}" i
  for ((i = 0; i < limit; i++)); do
    [[ "$(http "$url")" == "200" ]] && return 0
    sleep 1
  done
  return 1
}

echo "Image: $IMAGE"
echo
echo "1) Start ohne CAP_SYS_TIME"
docker run -d --name "${PREFIX}-a" -p 18080:8080 \
  -e NTP_PORT=10123 -e NTP_POOLS="" -e NTP_SERVERS="" -e ALLOW_NETWORKS="0.0.0.0/0" \
  "$IMAGE" >/dev/null
if wait_for_health http://127.0.0.1:18080/healthz 90; then ok "healthz wird gesund"; else bad "healthz bleibt ungesund"; fi
LOGS=$(docker logs "${PREFIX}-a" 2>&1)
contains "Fehlende Capability wird erkannt" "$LOGS" "CAP_SYS_TIME fehlt"
CMDLINE=$(docker exec "${PREFIX}-a" sh -c 'ps -o args= -C chronyd | head -1')
contains "chronyd läuft mit -x" "$CMDLINE" "-x"
check "Dashboard antwortet"        200 "$(http http://127.0.0.1:18080/)"
check "Stylesheet wird geliefert"  200 "$(http http://127.0.0.1:18080/static/app.css)"
check "API antwortet"              200 "$(http http://127.0.0.1:18080/api/status)"
check "Verlauf antwortet"          200 "$(http http://127.0.0.1:18080/api/history)"
check "Konfiguration abrufbar"     200 "$(http http://127.0.0.1:18080/api/config)"
check "Metriken antworten"         200 "$(http http://127.0.0.1:18080/metrics)"
check "Unbekannte Route -> 404"    404 "$(http http://127.0.0.1:18080/gibtsnicht)"
check "Kein Ausbruch aus /static"  404 "$(curl -s -o /dev/null -w '%{http_code}' --path-as-is http://127.0.0.1:18080/static/../server.py)"

STATUS=$(curl -s --max-time 10 http://127.0.0.1:18080/api/status)
if python3 -c "
import json, sys
d = json.loads(sys.argv[1])
assert d['chrony_running'], 'chronyd antwortet nicht'
assert d['tracking'].get('stratum') is not None, 'kein Stratum'
assert 'system' in d and 'sources' in d and 'gps' in d and 'ptp' in d, 'Felder fehlen'
" "$STATUS" 2>/dev/null; then ok "API liefert vollständigen Status"; else bad "API-Status unvollständig"; fi
contains "Metrik ntpgui_up vorhanden" "$(curl -s http://127.0.0.1:18080/metrics)" "ntpgui_up 1"

echo
echo "2) NTP-Dienst im Netz"
IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${PREFIX}-a")
if command -v chronyd >/dev/null 2>&1; then
  QUERY=$(timeout 25 chronyd -Q -t 15 "server $IP port 10123 iburst maxsamples 1" 2>&1)
  contains "Container beantwortet NTP-Anfragen" "$QUERY" "System clock wrong by"
else
  echo "  – chronyd auf dem Host nicht vorhanden, NTP-Abfrage übersprungen"
fi

echo
echo "3) Gemountete Konfiguration und Basic-Auth"
cat > "$CFG_DIR/chrony.conf" <<CONF
local stratum 7
allow 0.0.0.0/0
port 10124
bindcmdaddress /var/run/chrony/chronyd.sock
cmdport 0
CONF
docker run -d --name "${PREFIX}-b" -p 18081:8080 -v "$CFG_DIR:/config:ro" \
  -e WEB_USER=admin -e WEB_PASSWORD='S3hr geheim' "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18081/healthz 90 || true
contains "Eigene Konfiguration wird übernommen" "$(docker logs "${PREFIX}-b" 2>&1)" "gemountete /config/chrony.conf"
STRATUM=$(curl -s -u 'admin:S3hr geheim' http://127.0.0.1:18081/api/status | python3 -c "import json,sys; print(json.load(sys.stdin)['tracking'].get('stratum'))" 2>/dev/null)
check "Stratum aus eigener Konfiguration" 7 "$STRATUM"
check "Ohne Login abgewiesen"   401 "$(http http://127.0.0.1:18081/api/status)"
check "Falsches Passwort abgewiesen" 401 "$(http -u admin:falsch http://127.0.0.1:18081/api/status)"
check "Mit Login erlaubt"       200 "$(http -u 'admin:S3hr geheim' http://127.0.0.1:18081/api/status)"
check "healthz bleibt offen"    200 "$(http http://127.0.0.1:18081/healthz)"

echo
echo "4) GPS und PTP aktiviert, aber keine Hardware vorhanden"
docker run -d --name "${PREFIX}-c" -p 18082:8080 \
  -e GPS_ENABLE=true -e GPS_DEVICE=/dev/ttyACM0 -e GPS_WAIT_SECONDS=2 \
  -e PTP_ENABLE=true -e NTP_PORT=10125 -e NTP_POOLS="" "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18082/healthz 90 || true
LOGS=$(docker logs "${PREFIX}-c" 2>&1)
contains "Warnung wegen fehlendem GPS-Gerät" "$LOGS" "gpsd wird nicht gestartet"
contains "Warnung wegen fehlendem PTP-Interface" "$LOGS" "PTP_INTERFACE ist leer"
check "Container läuft trotzdem" running "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-c")"
REFCLOCKS=$(docker exec "${PREFIX}-c" sh -c 'grep -c refclock /etc/chrony/chrony.conf || true')
check "Keine tote Refclock-Zeile" 0 "$REFCLOCKS"

echo
echo "5) Sauberes Stoppen"
docker stop -t 15 "${PREFIX}-c" >/dev/null
check "Exit-Code bei SIGTERM" 0 "$(docker inspect -f '{{.State.ExitCode}}' "${PREFIX}-c")"
docker exec "${PREFIX}-a" pkill -x chronyd >/dev/null 2>&1
sleep 5
check "Exit-Code, wenn ein Dienst stirbt" 1 "$(docker inspect -f '{{.State.ExitCode}}' "${PREFIX}-a")"

echo
echo "------------------------------------------------------------"
printf 'Bestanden: %d   Fehlgeschlagen: %d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
