# Messblatt: Abnahmen auf dem Raspberry Pi 4

Einige Zusagen lassen sich nur auf echter Hardware prüfen. Die CI misst sie nicht, der Rundgang
(`tests/ui/`) auch nicht: Er läuft auf einem schnellen Rechner mit erfundenem `chronyc`. Dieses
Blatt beschreibt, wie du die vier Werte auf einem Pi 4 misst und wo du sie einträgst.

Trag nur Werte ein, die du selbst gemessen hast. Ein leeres Feld heißt „noch nicht gemessen“. Bei
„bestanden?“ schreibst du **ja** oder **nein**. Eine Schätzung oder ein Wert von einem anderen Gerät
gehört nicht in die Tabelle.

| Zusage | Grenze | Abschnitt |
|---|---|---|
| Studiouhr im Chromium-Kiosk, Design Studio | < 10 % CPU | [1](#1-studiouhr-im-chromium-kiosk-cpu) |
| Studiouhr im Chromium-Kiosk, Design Digital | < 3 % CPU | [1](#1-studiouhr-im-chromium-kiosk-cpu) |
| Ton auf der Sekunde im Chromium-Kiosk | ±5 ms um die volle Sekunde (ohne Laufzeit des Lautsprechers) | [2](#2-ton-auf-der-sekunde) |
| Sicherung mit 30 Tagen Verlauf | < 10 s, andere Anfragen laufen weiter | [3](#3-sicherung-mit-30-tagen-verlauf) |
| Übersicht | < 500 ms Serverzeit | [4](#4-übersicht-serverzeit) |

## Angaben zum Aufbau

Einmal je Messreihe ausfüllen. Alle Befehle laufen auf dem Pi, wenn nicht anders angegeben.

| Feld | Befehl | Eintrag |
|---|---|---|
| Datum der Messung | – | |
| ntp-gui-Version | `curl -s "${AUTH[@]}" http://127.0.0.1:8080/api/v1/status \| grep -o '"version": *"[^"]*"'` (vorher [Schlüssel bereitlegen](#schlüssel-bereitlegen)) | |
| Modell | `tr -d '\0' < /proc/device-tree/model` | |
| Arbeitsspeicher | `free -h \| awk '/^Mem/ {print $2}'` | |
| Betriebssystem | `. /etc/os-release && echo "$PRETTY_NAME"` | |
| Kernel | `uname -r` | |
| Chromium-Version | `chromium --version \|\| chromium-browser --version` | |
| Grafik (Wayland/X11) | `echo "$XDG_SESSION_TYPE"` | |
| Auflösung des Bildschirms | `wlr-randr \|\| xrandr --current \| head -3` | |
| Kühlung / Gehäuse | – | |
| Temperatur vor der Messung | `cat /sys/class/thermal/thermal_zone0/temp` (Milligrad) | |
| Drosselung | `vcgencmd get_throttled` (0x0 = keine) | |
| Läuft ntp-gui auf demselben Pi? | – | |

### Schlüssel bereitlegen

Ist ein Passwort gesetzt, brauchen die Abrufe in den Abschnitten 3 und 4 und die Versionsabfrage einen
API-Schlüssel. Leg ihn in den Einstellungen unter **API-Schlüssel** an – für Abschnitt 3 mit dem Recht
„lesen und verwalten“, sonst genügt „nur lesen“ – und widerruf ihn nach der Messung. Den Schlüssel nur
in die Shell geben, nicht in dieses Blatt. Er landet in einer Datei, die nur du lesen kannst, und nicht
in der Befehlszeile von `curl` (die sehen andere Konten mit `ps`):

```sh
read -rs KEY   # Schlüssel ntpg_… einfügen, Enter (ohne Passwort: einfach Enter)
H=$(umask 077; mktemp)
[ -n "$KEY" ] && printf 'header = "Authorization: Bearer %s"\n' "$KEY" > "$H"
unset KEY
AUTH=(-K "$H")
BASE=http://127.0.0.1:8080
```

Nach der Messung: `rm -f "$H"; unset H AUTH` und den Schlüssel widerrufen.

Vor jeder CPU-Messung: Pi mindestens 10 min laufen lassen, keine anderen Fenster offen, kein
Update im Hintergrund (`pgrep -a apt; pgrep -a unattended`).

## 1. Studiouhr im Chromium-Kiosk (CPU)

**Grenze:** Design Studio < 10 %, Design Digital < 3 %. Gemeint ist die Summe aller
Chromium-Prozesse in Prozent **eines** Kerns (wie `top` sie zeigt), gemittelt über 60 s,
1080p-Bildschirm, Ruhebetrieb (keine Bedienung, kein Countdown, kein Prüfbild).

Kiosk starten (je Design einmal, vorher alle Chromium-Fenster schließen):

```sh
# Design Studio (Profil studio: kiosk=1, fun=0)
chromium --kiosk --noerrdialogs --disable-session-crashed-bubble --disable-infobars \
  --check-for-update-interval=31536000 "http://zeitserver.lan:8080/clock?p=studio" &

# Design Digital
chromium --kiosk --noerrdialogs --disable-session-crashed-bubble --disable-infobars \
  --check-for-update-interval=31536000 "http://zeitserver.lan:8080/clock?design=digital&kiosk=1" &
```

Heißt das Programm bei dir `chromium-browser`, nimm diesen Namen. Ersetze `zeitserver.lan:8080`
durch die Adresse deines Servers.

Nach dem Start 2 min warten, dann per SSH auf dem Pi messen (der Kiosk bleibt ungestört):

```sh
# CPU-Zeit aller Chromium-Prozesse über 60 s, in Prozent eines Kerns
snap() { for p in $(pgrep -f 'chrom(e|ium)'); do
  awk -v p="$p" '{ sub(/^[0-9]+ \([^)]*\) /, ""); print p, $12 + $13 }' "/proc/$p/stat" 2>/dev/null
done; }
snap > cpu-a.txt; sleep 60; snap > cpu-b.txt
awk -v hz="$(getconf CLK_TCK)" '
  NR == FNR { a[$1] = $2; na++; next }
  { nb++ } ($1 in a) { d += $2 - a[$1]; n++ }
  END { if (n == 0 || n != na || n != nb) print "ungültig: Chromium-Prozesse haben sich geändert oder fehlen"
        else printf "%.1f %% (%d Prozesse)\n", d * 100 / (60 * hz), n }' cpu-a.txt cpu-b.txt
```

Jeder Prozess wird einzeln gelesen; endet oder startet einer während der 60 s, ist der Lauf
**ungültig** und wird wiederholt (kein Wert eintragen). Läuft gar kein Chromium, ebenfalls.

Dreimal hintereinander messen. Zur Gegenprobe: `top -b -d 60 -n 2 | grep -i chrom` (zweiter Block).

| Design | Lauf 1 | Lauf 2 | Lauf 3 | Mittel | Grenze | bestanden? |
|---|---|---|---|---|---|---|
| Studio (`?p=studio`) | | | | | < 10 % | |
| Digital (`?design=digital&kiosk=1`) | | | | | < 3 % | |

Bemerkungen (z. B. Bildschirm, Hardwarebeschleunigung laut `chrome://gpu`):

## 2. Ton auf der Sekunde

**Grenze:** Der Klick beginnt innerhalb von ±5 ms um die volle Sekunde. Die Laufzeit des
Lautsprechers (Bluetooth, HDMI-Fernseher) zählt nicht mit; miss deshalb über Kopfhörer- bzw.
Analogausgang oder zieh eine bekannte Laufzeit ab.

Du brauchst eine Bezugssekunde, die nicht vom Browser kommt. Am einfachsten ist die PPS-LED des
GPS-Empfängers am Zeitserver (sie blinkt zur vollen Sekunde) oder ein Funkuhr-/GPS-Sekundenton.

1. Chromium wie in Abschnitt 1 mit `--kiosk` starten, aber mit
   `http://zeitserver.lan:8080/clock?design=studio&look=studio&fun=0` – also **ohne** `kiosk=1` bzw.
   das Profil `studio`. Mit `kiosk=1` blendet die Uhr Kopfzeile und Panels aus, und für den Ton gibt
   es kein Tastenkürzel; dort lässt sich der Sekundenton nicht einschalten. Einmal tippen bzw.
   klicken, in der Kopfzeile **Ton** öffnen und **Sekundenpiep** einschalten (Browser spielen Ton erst
   nach einer Bedienung). Maus bzw. Finger danach wegnehmen, bis die Kopfzeile verschwindet.

   Soll die Uhr dabei genau wie im Betrieb mit `kiosk=1` laufen, nimm das Prüfbild:
   `http://zeitserver.lan:8080/clock?p=studio&test=sync` und dort **Ton-Klick** (siehe
   [Studiouhr](integrationen/studiouhr.md)). Der Klick wird gleich geplant wie der Sekundenton und
   fällt auf die wahre Sekunde, unabhängig vom Vorlauf der Fläche. Notier, welchen Weg du genommen hast.
2. Prüfen, dass die Uhr synchron ist: Zustandszeile ohne „frei“ bzw. „ungewiss“.
3. Mit einem Handy oder einer Kamera bei mindestens 120 Bildern/s (Zeitlupe) die PPS-LED aufnehmen
   und den Ton gleichzeitig aufzeichnen. Lautsprecher dicht an das Mikrofon, damit die Schalllaufzeit
   (≈ 3 ms je Meter) klein bleibt; den Abstand notieren.
4. Am Rechner Tonspur und Bild Bild für Bild ansehen (z. B. Audacity für den Ton, ein Videoprogramm
   mit Einzelbildschritt für die LED) und je Sekunde den Abstand zwischen Aufleuchten der LED und
   Beginn des Klicks bestimmen. Bei 120 Bildern/s ist die Auflösung etwa 8 ms; für die Grenze von
   ±5 ms also 240 Bilder/s nehmen oder über viele Sekunden mitteln.
5. Mindestens 20 Sekunden auswerten.

| Feld | Eintrag |
|---|---|
| Weg (Sekundenpiep ohne `kiosk=1` / Prüfbild mit Ton-Klick) | |
| Bezug (PPS-LED, Funkuhr, …) | |
| Aufnahmegerät, Bilder/s | |
| Abstand Lautsprecher–Mikrofon (m) | |
| Ausgang (Klinke, HDMI, USB) | |
| Ausgewertete Sekunden | |
| Mittelwert Klick minus Bezug (ms) | |
| kleinster / größter Wert (ms) | |
| Grenze | ±5 ms |
| bestanden? | |

## 3. Sicherung mit 30 Tagen Verlauf

**Grenze:** Eine neue Sicherung mit 30 Tagen Verlauf ist nach weniger als 10 s fertig
heruntergeladen. Andere Anfragen laufen währenddessen weiter.

Voraussetzung: Der Server läuft seit mindestens 30 Tagen mit `HISTORY_DAYS` ≥ 30 (Standard 30), und
im Dashboard zeigt **Verlauf → 30 Tage** Daten über den ganzen Zeitraum. Größe der Datenbank:

```sh
docker exec ntp-gui ls -l /var/lib/chrony/ntp-gui/ntp-gui.db
```

Ist ein Passwort gesetzt, braucht die Sicherung einen API-Schlüssel mit dem Recht „lesen und
verwalten“ ([Schlüssel bereitlegen](#schlüssel-bereitlegen)).

```sh
# Gegenprobe im Hintergrund: jede Sekunde /healthz, Status und Antwortzeit in Sekunden
( for i in $(seq 1 30); do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' "$BASE/healthz"; sleep 1; done ) > healthz.txt &

# Sicherung messen (Datei wird verworfen; sie enthält Client-Adressen, nicht weitergeben)
curl -s -o /dev/null "${AUTH[@]}" \
  -w 'HTTP %{http_code}, %{size_download} Bytes, %{time_total} s\n' "$BASE/api/v1/backup"

wait
grep -vc '^200 ' healthz.txt               # muss 0 sein: jede /healthz-Antwort mit HTTP 200
sort -k2 -n healthz.txt | tail -1          # langsamste /healthz-Antwort währenddessen
```

Zählt nur, wenn die Sicherung mit **HTTP 200** und mehr als 0 Bytes endet. Eine Absage (401/403:
Schlüssel fehlt oder hat zu wenig Rechte, 429: eine andere Sicherung läuft noch) kommt sofort und ist
kein Messwert – Ursache beheben und den Lauf wiederholen.

Dreimal messen, zwischen den Läufen 1 min Pause (eine Sicherung gleichzeitig; eine zweite
Anfrage bekommt sonst eine Absage).

| Feld | Lauf 1 | Lauf 2 | Lauf 3 |
|---|---|---|---|
| Größe von `ntp-gui.db` | | | |
| HTTP-Status der Sicherung | | | |
| Größe der Sicherung (Bytes) | | | |
| Dauer der Sicherung (s) | | | |
| langsamste `/healthz`-Antwort währenddessen (s) | | | |

| Grenze | bestanden? |
|---|---|
| jede Sicherung HTTP 200 mit Größe > 0 und < 10 s, `/healthz` immer HTTP 200 und < 1 s | |

## 4. Übersicht (Serverzeit)

**Grenze:** Die Anfragen, die die Übersicht beim Öffnen stellt, beantwortet der Server zusammen in
weniger als 500 ms. Gemessen wird die Zeit bis zum ersten Byte (`time_starttransfer`) direkt auf dem
Pi über 127.0.0.1, also ohne Netz und ohne Browser. Bedingung wie in Abschnitt 3: 30 Tage Verlauf
vorhanden.

Ist ein Passwort gesetzt, brauchst du einen API-Schlüssel mit dem Recht „nur lesen“
([Schlüssel bereitlegen](#schlüssel-bereitlegen)). Jeder Abruf muss mit HTTP 200 antworten; sonst
bricht die Schleife ab und die Messung ist **ungültig** (eine Absage mit 401/403 kommt sofort und sähe
sonst wie eine sehr schnelle Antwort aus).

```sh
PATHS="status history?range=3600&points=600 timeline timeline/markers?range=2678400 clients/offsets events?limit=5 setup"
for run in 1 2 3 4 5 6 7 8 9 10; do
  sum=0; max=0
  for p in $PATHS; do
    r=$(curl -s -o /dev/null "${AUTH[@]}" -w '%{http_code} %{time_starttransfer}' "$BASE/api/v1/$p")
    code=${r%% *}; s=${r#* }
    if [ "$code" != 200 ]; then echo "ungültig: HTTP $code für $p – Messung abgebrochen"; break 2; fi
    sum=$(awk -v a="$sum" -v b="$s" 'BEGIN { print a + b }')
    max=$(awk -v a="$max" -v b="$s" 'BEGIN { print (b > a) ? b : a }')
  done
  echo "Lauf $run: Summe ${sum} s, langsamste ${max} s"
  sleep 5
done
```

Die Liste entspricht den Abrufen der Übersicht in `app/static/js/app.js`, `pages/overview.js` und
`timeline.js` (Verlauf mit dem Standardzeitraum 1 h). Ändert sich das Frontend, die Liste anpassen.
Die Summe ist strenger als die Wirklichkeit, weil der Browser die Abrufe gleichzeitig stellt.

| Feld | Eintrag |
|---|---|
| Summe, Median der 10 Läufe (ms) | |
| Summe, größter Wert (ms) | |
| langsamster Einzelabruf und sein Pfad | |
| Grenze | Median der Summe < 500 ms |
| bestanden? | |

## Ablage

Ein ausgefülltes Blatt gehört zu genau einem Release. Halte darin keine Adressen, Gerätenamen,
Seriennummern oder Standorte fest, und keine Schlüssel. Fotos und Videos aus Abschnitt 2 bleiben
bei dir.
