#!/usr/bin/env bash
# UI-Rundgang starten: Server mit erfundenem chronyc in einem Temp-Verzeichnis, tour.js, Server beenden.
# Aufruf aus dem Repository: tests/ui/rundgang.sh [Port]   (Standard 18300)
# TOUR_REQUIRE_PLAYWRIGHT=1: fehlendes Playwright ist ein Fehler (Rückgabecode 3) statt eines stillen Überspringens.
# TOUR_SERVER_LOG=<Datei>: Protokoll des Testservers beim Beenden dorthin kopieren.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PORT="${1:-18300}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ntpgui-ui-XXXXXX")"
mkdir -p "$TMP/data" "$TMP/run" "$TMP/etc"

if ! node -e "require.resolve('playwright')" >/dev/null 2>&1; then
  rm -rf "$TMP"
  if [ "${TOUR_REQUIRE_PLAYWRIGHT:-}" = "1" ]; then
    echo "Node mit Playwright fehlt – Rundgang nicht möglich." >&2
    exit 3
  fi
  echo "Node mit Playwright fehlt – Rundgang übersprungen." >&2
  exit 0
fi

NTPGUI_DATA_DIR="$TMP/data" NTPGUI_RUN_DIR="$TMP/run" CHRONY_CONF="$TMP/etc/chrony.conf" \
PTP4L_CONF="$TMP/etc/ptp4l.conf" NTPGUI_NTS_CERT_DIR="$TMP/nts-certs" \
NTPGUI_CHRONYC="$HERE/fake_chronyc.py" WEB_BIND=127.0.0.1 WEB_PORT="$PORT" \
  python3 "$ROOT/app/server.py" >"$TMP/server.log" 2>&1 &
SERVER=$!
# Server genau einmal beenden: Bei einer Zeitüberschreitung (ci.sh, timeout) hat er SIGTERM schon mit der
# Prozessgruppe bekommen (SIGNALED=1) – dann kein zweites TERM. Sonst einmal TERM schicken. Nach einer Frist
# hart beenden, damit ein hängender Server den Rundgang nicht festhält.
SIGNALED=0
cleanup() {
  trap - TERM INT
  if kill -0 "$SERVER" 2>/dev/null; then
    [ "$SIGNALED" = 1 ] || kill "$SERVER" 2>/dev/null || true
    for _i in $(seq 1 50); do
      kill -0 "$SERVER" 2>/dev/null || break
      sleep 0.2
    done
    kill -9 "$SERVER" 2>/dev/null || true
  fi
  wait "$SERVER" 2>/dev/null || true
  if [ -n "${TOUR_SERVER_LOG:-}" ]; then cp "$TMP/server.log" "$TOUR_SERVER_LOG" 2>/dev/null || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT
trap 'SIGNALED=1; exit 143' TERM
trap 'exit 130' INT

for _ in $(seq 1 50); do
  if python3 -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=1)" "http://127.0.0.1:$PORT/" 2>/dev/null; then break; fi
  sleep 0.2
done
# Ein paar Sekunden Verlauf sammeln lassen, damit Diagramme Punkte haben.
sleep "${TOUR_WARMUP:-8}"
node "$HERE/tour.js" "http://127.0.0.1:$PORT"
