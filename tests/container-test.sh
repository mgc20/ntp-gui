#!/usr/bin/env bash
# Integrationstest gegen ein gebautes Image.
#
#   docker build -t ntp-gui:test .
#   tests/container-test.sh ntp-gui:test
#
# Prüft das Laufzeitverhalten, das sich mit Unittests nicht abbilden lässt:
# Capability-Erkennung, Healthcheck, Basic-Auth, gemountete Konfiguration,
# Verhalten ohne GPS-/PTP-Hardware, Einstellungen über die API samt Neustart
# der Dienste und sauberes Stoppen.
set -uo pipefail

IMAGE="${1:-ntp-gui:test}"
PREFIX="ntpgui-it-$$"
CFG_DIR="$(mktemp -d)"
PASS=0
FAIL=0

cleanup() {
  docker rm -f "${PREFIX}-a" "${PREFIX}-b" "${PREFIX}-c" "${PREFIX}-d" "${PREFIX}-e" "${PREFIX}-f" >/dev/null 2>&1
  docker volume rm "${PREFIX}-data" >/dev/null 2>&1
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
contains "Eigene Konfiguration wird übernommen" "$(docker logs "${PREFIX}-b" 2>&1)" "verwende gemountete /config/chrony.conf"
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
contains "Warnung wegen fehlendem GPS-Gerät" "$LOGS" "/dev/ttyACM0 nicht gefunden"
contains "Warnung wegen fehlendem PTP-Interface" "$LOGS" "kein Interface gewählt"
check "Container läuft trotzdem" running "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-c")"
REFCLOCKS=$(docker exec "${PREFIX}-c" sh -c 'grep -c refclock /etc/chrony/chrony.conf || true')
check "Keine tote Refclock-Zeile" 0 "$REFCLOCKS"

echo
echo "5) Dienst stirbt beim Start (wait -n hätte das übersehen)"
docker run -d --name "${PREFIX}-d" \
  -e EXTRA_CHRONY_CONF="diese zeile versteht chronyd nicht" \
  -e NTP_PORT=10126 -e NTP_POOLS="" "$IMAGE" >/dev/null
DEAD=0
for _ in $(seq 1 30); do
  if [[ "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-d")" == "exited" ]]; then DEAD=1; break; fi
  sleep 1
done
if [[ "$DEAD" == 1 ]]; then ok "Container beendet sich, statt kaputt weiterzulaufen"; else bad "Container läuft trotz totem chronyd weiter"; fi
check "Exit-Code signalisiert Fehler" 1 "$(docker inspect -f '{{.State.ExitCode}}' "${PREFIX}-d")"
contains "Watchdog meldet den toten Dienst" "$(docker logs "${PREFIX}-d" 2>&1)" "unerwartet beendet"
docker rm -f "${PREFIX}-d" >/dev/null 2>&1

echo
echo "6) Einstellungen über das Dashboard"
docker volume create "${PREFIX}-data" >/dev/null
docker run -d --name "${PREFIX}-e" -p 18083:8080 -v "${PREFIX}-data:/var/lib/chrony" \
  -e NTP_PORT=10127 -e NTP_POOLS="" "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18083/healthz 90 || true
API=http://127.0.0.1:18083/api/settings
post() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "$@"; }
check "Einstellungen abrufbar" 200 "$(http "$API")"
check "POST ohne CSRF-Header abgewiesen" 403 "$(post -H 'Content-Type: application/json' -d '{"changes":{"web_title":"x"}}' "$API")"
check "POST von fremder Origin abgewiesen" 403 "$(post -H 'Content-Type: application/json' -H 'X-NTP-GUI: 1' -H 'Origin: http://evil.example' -d '{"changes":{"web_title":"x"}}' "$API")"
check "Ungültiger Wert abgewiesen" 422 "$(post -H 'Content-Type: application/json' -H 'X-NTP-GUI: 1' -d '{"changes":{"allow_networks":["10.0.0.0/8\ncmdallow"]}}' "$API")"
RESULT=$(curl -s --max-time 10 -X POST -H 'Content-Type: application/json' -H 'X-NTP-GUI: 1' \
  -d '{"changes":{"local_stratum":8,"web_title":"IT-Uhr"}}' "$API")
contains "Speichern löst Neustart aus" "$RESULT" '"reload_triggered": true'
STATE=""
for _ in $(seq 1 40); do
  STATE=$(curl -s --max-time 5 http://127.0.0.1:18083/api/reload | python3 -c "import json,sys; print(json.load(sys.stdin).get('state'))" 2>/dev/null)
  [[ "$STATE" == "done" || "$STATE" == "error" ]] && break
  sleep 1
done
check "Dienste neu gestartet" done "$STATE"
contains "chrony.conf enthält neuen Wert" "$(docker exec "${PREFIX}-e" cat /etc/chrony/chrony.conf)" "local stratum 8"
STRATUM=""
for _ in $(seq 1 20); do
  STRATUM=$(curl -s http://127.0.0.1:18083/api/status | python3 -c "import json,sys; print(json.load(sys.stdin)['tracking'].get('stratum'))" 2>/dev/null)
  [[ "$STRATUM" == "8" ]] && break
  sleep 1
done
check "chronyd nutzt neuen Wert" 8 "$STRATUM"
check "Container läuft nach Neustart" running "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-e")"
PERMS=$(docker exec "${PREFIX}-e" stat -c '%a' /var/lib/chrony/ntp-gui/settings.json)
check "settings.json nur für root lesbar" 600 "$PERMS"
docker rm -f "${PREFIX}-e" >/dev/null 2>&1
docker run -d --name "${PREFIX}-f" -p 18084:8080 -v "${PREFIX}-data:/var/lib/chrony" \
  -e NTP_PORT=10128 -e NTP_POOLS="" -e WEB_READONLY=true "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18084/healthz 90 || true
contains "Einstellungen überleben Neuerstellung" "$(docker exec "${PREFIX}-f" cat /etc/chrony/chrony.conf)" "local stratum 8"
check "WEB_READONLY sperrt Änderungen" 403 "$(post -H 'Content-Type: application/json' -H 'X-NTP-GUI: 1' -d '{"changes":{"web_title":"x"}}' http://127.0.0.1:18084/api/settings)"
docker rm -f "${PREFIX}-f" >/dev/null 2>&1

echo
echo "7) Sauberes Stoppen"
docker stop -t 15 "${PREFIX}-c" >/dev/null
check "Exit-Code bei SIGTERM" 0 "$(docker inspect -f '{{.State.ExitCode}}' "${PREFIX}-c")"
docker exec "${PREFIX}-a" pkill -x chronyd >/dev/null 2>&1
sleep 5
check "Exit-Code, wenn ein Dienst stirbt" 1 "$(docker inspect -f '{{.State.ExitCode}}' "${PREFIX}-a")"

echo
echo "------------------------------------------------------------"
printf 'Bestanden: %d   Fehlgeschlagen: %d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
