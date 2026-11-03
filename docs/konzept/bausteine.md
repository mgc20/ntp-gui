# Open-Source-Bausteine

Stand: 01.11.2026 · Bewertet nach dem [Entscheidungsrahmen](entscheidungsrahmen.md)

Geprüft gegen packages.debian.org, PyPI, die Dokumentation der Projekte und das lokale Test-Image.
Angaben, die nicht neu geprüft wurden, sind mit *(n. g.)* markiert. GitHub-Statistiken (Sterne,
Commits) wurden nicht abgerufen; die Aktivität stützt sich auf Releases, PyPI und Debian.

**Empfehlungen:**
- **übernehmen:** steckt schon im Image oder kommt als Debian-Paket hinein
- **Sidecar:** fremder, offizieller Container daneben, optional, von uns nur dokumentiert
- **klein selbst:** wenige Zeilen Python-stdlib, weil das fertige Paket viel mehr mitbrächte
- **Doku:** gehört auf den Host oder in ein Werkzeug des Nutzers
- **weglassen**

## 1. Querschnitt: Basis-Image auf Debian 13 „trixie“

Debian 12 „bookworm“ ist seit dem Erscheinen von trixie (09.08.2025) oldstable; die reguläre
Sicherheitsunterstützung endete am **12.07.2026**, seitdem pflegt nur noch das LTS-Team
(bis 30.06.2028). Die Pakete dort sind für unsere Pläne zu alt.

| Paket | bookworm (bis 1.3.0) | trixie (ab 1.3.1) | Warum es zählt |
|---|---|---|---|
| chrony | 4.3 | 4.6.1 | `selectopts` (Quelle zur Laufzeit sperren) ab **4.4**, `leapseclist` ab **4.6** |
| gpsd (inkl. `ubxtool`) | 3.22 | 3.25 | bessere u-blox-F9-Unterstützung, `prRes`/`qual` im JSON |
| linuxptp | 3.1.1 | 4.2 | `ts2phc` mit Holdover erst in 4.x |
| python3-paho-mqtt | 1.6.1 | 2.1.0 | API 2.x ist inkompatibel zu 1.6 – gleich auf 2.x festlegen |
| apprise | 1.2.0 | 1.9.3 | (bleibt trotzdem draußen, siehe unten) |

**Falle:** In trixie stecken die Zonen `right/*` nicht mehr in `tzdata`, sondern in
`tzdata-legacy`. Der bisherige Standard `LEAPSECTZ=right/UTC` (bis 1.3.0) liefe ins Leere – chrony hätte
**keine Schaltsekunden-Daten** und meldete das nur im Log. Lösung: auf
`leapseclist /usr/share/zoneinfo/leap-seconds.list` umstellen (in trixie-`tzdata` enthalten,
geprüft; `right/` fehlt dort tatsächlich). Umgesetzt in 1.3.1: `leapseclist
/usr/share/zoneinfo/leap-seconds.list`, Migration Schema 3 (statt `tzdata-legacy`, siehe E2).
`gpsd`-`jam` und Antennenstatus (`ant_stat`) im JSON gibt es erst ab gpsd 3.26 (11.05.2025) – also
in trixie (3.25) **nicht**; erst forky/testing hat 3.27.5. In welcher JSON-Klasse die Felder stehen,
ist vor der Umsetzung im gpsd-Quelltext zu prüfen.

**Umgesetzt in 1.3.1** als eigenes Release direkt nach 1.3.0, mit vollem Container-Test.

## 2. Übersicht

| Baustein | Lizenz | Debian | Zuwachs im Image | Angriffsfläche | Aufwand | Empfehlung |
|---|---|---|---|---|---|---|
| **chrony** `tempcomp`, `selectopts`, `leapseclist` | GPL-2.0 | im Image | 0 | 0 | ◆◆ (Mess-/Fit-Logik) | **übernehmen** |
| **gpsd** `ubxtool` / `gpsctl` | BSD-2 | im Paket `gpsd` (nicht `gpsd-clients`) | `python3-gps` ≈ 0,6 MB | mittel (schreibt in den Empfänger) | ◆◆ | **übernehmen** in 1.5, nur feste Voreinstellungen |
| **tzdata** `leap-seconds.list` | Public Domain | im Image | 0 | 0 | ◆ (≈ 40 Zeilen Parser) | **übernehmen**; kein eigener IERS-Download |
| **linuxptp** `ts2phc` | GPL-2.0 | im Image | 0 | 0 | ◆◆◆ (hardwareabhängig) | **später, experimentell**, ab trixie |
| Webhook (JSON-POST, HMAC) | stdlib | – | 0 | nur ausgehend | ◆ | **klein selbst** |
| ntfy-Client | stdlib (Server Apache-2.0/GPL-2.0) | – | 0 | nur ausgehend | ◆ | **klein selbst** |
| Gotify-Client | stdlib (Server MIT *(n. g.)*) | – | 0 | nur ausgehend | ◆ | **klein selbst** |
| E-Mail (`smtplib`) | PSF | – | 0 | nur ausgehend, TLS | ◆ | **klein selbst** |
| **Apprise** (Bibliothek) | BSD-2 | 1.2.0 (bookworm) / 1.9.3 (trixie); PyPI 2.1.0 | mehrere MB, ≥ 6 Pakete | groß (≈ 170 Dienste) | ◆ | **weglassen im Image** |
| **Apprise-API** (`caronc/apprise-api`) | BSD-2 | – | 0 (eigener Container) | beim Nutzer | ◆ (Doku) | **Sidecar** über den Webhook |
| **paho-mqtt** | EPL-2.0 OR BSD-3 | 1.6.1 / **2.1.0 (trixie)** | klein | mittel (parst Broker-Antworten) | ◆◆ | **übernehmen ab trixie** (siehe 3.2) |
| eigener MQTT-Minimalclient | stdlib | – | 0 | klein, aber eigener Parser | ◆◆ (≈ 150–200 Zeilen) | Rückfall, falls paho wegfällt |
| `mosquitto_pub` | EPL-2.0/EDL-1.0 | 2.0.11 | ≈ 0,5 MB | Fremdprozess je Nachricht | ◆ | **weglassen** (kein sauberes LWT) |
| Home-Assistant-Discovery | Protokoll | – | 0 | – | ◆ | **übernehmen** |
| **AllanTools** | LGPL-3 (letztes Release 2024.6, 04.07.2024) | nein | zig MB (numpy, scipy; matplotlib optional) | groß | – | **nur in CI als Test-Orakel**; ADEV selbst (≈ 50 Zeilen) |
| **keepalived** (VRRP) | GPL-2.0 | 2.2.7 | ≈ 0,5 MB + libnl/libsnmp | braucht `NET_ADMIN`/`NET_RAW` | ◆ (Doku) | **Doku**: auf dem Host oder als Sidecar, `/healthz` als Prüfskript |
| HTTPS mit `ssl` | PSF/OpenSSL | – | 0 | klein | ◆ (≈ 30 Zeilen) | **klein selbst**, opt-in |
| **Caddy** | Apache-2.0 | 2.6.2 (alt, ≈ 36 MB) | 0 (offizielles Image) | beim Nutzer | ◆ (Doku) | **Sidecar** |
| Grafana-Dashboard (JSON) | – | – | 0 | 0 | ◆ | **übernehmen** (Repo + grafana.com) |
| Prometheus-Alarmregeln | – | – | 0 | 0 | ◆ | **übernehmen** |
| **Promtail** | AGPL-3 | – | – | – | – | **weglassen**: seit 02.03.2026 EOL, Nachfolger Grafana Alloy |
| Log-Versand | – | – | 0 | gering | ◆ | **Doku** (Alloy, Vector, Docker-Log-Treiber); optional `SysLogHandler` 🔒 |
| **sigstore-python** | Apache-2.0 | – | groß (cryptography, pydantic, requests …) | mittel | – | **weglassen**; stattdessen Attestation im Release-Workflow |
| `actions/attest` | MIT *(n. g.)* | – | 0 (CI) | 0 | ◆ | **übernehmen** im Release-Workflow |
| **Diun** (nur melden) / **WUD** | MIT *(n. g.)* | – | 0 | beim Nutzer | ◆ (Doku) | **Doku** für Nutzer, die Updates automatisieren wollen. **Nicht** Watchtower empfehlen: `containrrr/watchtower` ist seit 17.12.2025 archiviert, keine Sicherheitsupdates mehr |
| **pyubx2** | BSD-3 *(n. g.)* | nein | klein | mittel | – | **weglassen**; die ≈ 5 benötigten UBX-Nachrichten mit `struct` |
| **Weblate** (Übersetzung) | GPL-3 | – | 0 (gehostet, kostenlos für OSS *(n. g.)*) | 0 | ◆ | **übernehmen** für i18n ab 1.5 |

**Bilanz für 1.4:** höchstens ein neues Python-Paket aus Debian (`python3-paho-mqtt`), dazu
`python3-gps` erst in 1.5. Alles andere ist stdlib-Code, Doku oder fremde Container.

## 3. Einzelbewertungen mit Begründung

### 3.1 Benachrichtigungen
- **Klein selbst** als Modul `notify.py` auf Basis des 1.3-Ereignisprotokolls. Jeder Text läuft durch den zentralen Filter.
  - Webhook: `POST` JSON (`event`, `severity`, `title`, `message`, `ts`, `instance`), optional Header `X-NTPGUI-Signature: sha256=<HMAC>`.
  - ntfy: `POST https://<server>/<topic>`, Header `Title`, `Priority` (1–5), `Tags`, optional Bearer-Token.
  - Gotify: `POST /message` mit App-Token, JSON `{title, message, priority}`.
  - E-Mail: `smtplib` nur mit STARTTLS oder SMTPS.
- **Apprise im Image:** großer Nutzen, aber ≥ 6 Fremdpakete mit eigener CVE-Historie, und die Debian-Fassung hinkt PyPI hinterher. Für den Großteil der Nutzer wäre es Ballast.
- **Ausweg:** Der Webhook kann direkt die **Apprise-API** (`POST /notify/`) ansprechen. Eine Doku-Seite genügt; wer Telegram, Signal, Matrix oder Teams will, startet den Container daneben.
- **Wichtig:** `urllib` folgt Weiterleitungen standardmäßig – ein eigener `HTTPRedirectHandler`, der ablehnt, ist Pflicht (SSRF, Daten an fremde Ziele).

### 3.2 MQTT
Die beiden Vorarbeiten kamen hier zu unterschiedlichen Ergebnissen. Nach dem Entscheidungsrahmen:

| Option | Pro | Contra |
|---|---|---|
| `python3-paho-mqtt` 2.1.0 aus trixie | Debian liefert Sicherheitsupdates; Parser fremder Broker-Antworten ist bewährter Code; LWT, TLS, Reconnect fertig | bricht „nur stdlib“; letztes Upstream-Release 29.04.2024 (stabil, aber langsam gepflegt) |
| eigener Minimalclient (MQTT 3.1.1, QoS 0) | keine neue Abhängigkeit, ≈ 150–200 Zeilen | eigener Binärparser für Netzwerkdaten, den wir allein verantworten |
| `mosquitto_pub` | bewährt | ein Prozess je Nachricht, LWT nur im Dauermodus auf einem Topic, Passwort nicht in die argv |

**Empfehlung:** paho aus Debian ab trixie (Regel „Debian-Paket vor Eigenbau“, Parser fremder
Eingaben gehört in bewährten Code). Der eigene Client bleibt dokumentierter Rückfall, falls paho
aus Debian verschwindet. Tests in CI gegen `eclipse-mosquitto` bzw. das Debian-Paket `mosquitto`.

### 3.3 Temperaturausgleich (chrony `tempcomp`)
- chrony kann es schon: `tempcomp <datei> <intervall> <T0> <k0> <k1> <k2>` oder eine Punktedatei mit linearer Interpolation, Temperatur in Milligrad, Korrektur in ppm, gültig nur innerhalb ±10 ppm; `log tempcomp`.
- **Unser Anteil:** Sensor finden (`/sys/class/thermal/…`, `/sys/class/hwmon/…`, DS18B20), Paare aus Temperatur und Frequenz sammeln, fitten (stdlib), Vorschlag zeigen, erst auf Klick anwenden.
- Ehrlich: Die CPU-Temperatur ist ein schlechter Stellvertreter für die Quarztemperatur; das R² gehört in die Anzeige.

### 3.4 Allan-Abweichung
- AllanTools zieht numpy, scipy und matplotlib nach sich – nicht ins Image. Überlappende ADEV (plus MDEV/TDEV) sind ≈ 50 Zeilen ohne numpy und für ~86 400 Punkte schnell genug.
- AllanTools **nur in CI** als Orakel, dazu die Testwerte aus NIST SP 1065.
- Vorbehalt: Die Daten zeigen die *geregelte* Systemuhr, nicht den frei laufenden Quarz.

### 3.5 u-blox-Konfiguration
- `ubxtool`, `gpsctl` und `ppscheck` liegen im Paket `gpsd` (schon installiert), aber `ubxtool` braucht `python3-gps` (≈ 567 kB). Im Test-Image bricht es ohne dieses Paket mit „failed to import gps“ ab.
- Fähigkeiten: Konstellationen ein/aus, Survey-in (M8T über TMODE2, F9T über `CFG-TMODE-*`), stationäres Modell, Zeitimpuls (`CFG-TP5`), TIM-TP, Speichern, Firmware abfragen. **`-P` (Protokollversion) muss stimmen**, sonst scheitert der Befehl still.
- Nur feste, geprüfte Voreinstellungen, immer über gpsd (nie `-f` neben gpsd), Befehlsvorschau, vorher Konfiguration sichern.

### 3.6 Schaltsekunden
- `leap-seconds.list` (tzdata): TAI−UTC, Ablaufdatum (`#@`), SHA-1 (`#h`, prüfbar mit `hashlib`). Im Test-Image läuft die Datei am 28.06.2027 ab.
- Kein eigener IERS-Download: zusätzlicher ausgehender Verkehr ohne Gewinn; Abhilfe bei Ablauf ist ein Image-Update.

### 3.7 ts2phc, keepalived, HTTPS, Logs
- **ts2phc:** schon im Image, aber hardwareabhängig (i210/i226, TimeHAT), Pins treiberabhängig, Konkurrenz mit gpsd um die serielle Schnittstelle. Später, experimentell, auf Testberichte der Community angewiesen.
- **keepalived:** bräuchte `NET_ADMIN`/`NET_RAW` und eine libnl/libsnmp-Kette – nicht ins Image. Doku: auf dem Host oder als Sidecar mit `network_mode: host`, `track_script` mit `curl -fs http://127.0.0.1:8080/healthz`. Hinweis: Das NTS-Zertifikat muss den Namen der VIP enthalten.
- **HTTPS:** `ssl.SSLContext(PROTOCOL_TLS_SERVER)` mit `minimum_version = TLSv1_2`, Zertifikate aus denselben erlaubten Pfaden wie bei NTS, Neuladen wie bei NTS. Caddy als Sidecar dokumentieren.
  - **Falle (Verfügbarkeit):** Wird der lauschende Socket mit `wrap_socket()` und Standardwerten umhüllt, läuft der TLS-Handshake in `accept()` – also im einzigen Annahme-Thread von `ThreadingHTTPServer`. Ein Client, der verbindet und schweigt, blockiert dann das ganze Dashboard. Darum `do_handshake_on_connect=False` und Handshake mit Timeout im Arbeitsthread (bzw. in `get_request`/`finish_request` mit Socket-Timeout). Das ist genau die Art Detail, die ein Reverse Proxy schon gelöst hat.
- **Logs:** bleiben auf stdout. Abholung auf dem Host (Grafana Alloy, Vector, Docker-Log-Treiber). Logs enthalten LAN-IPs der Clients – ein optionaler Syslog-Versand ist opt-in 🔒 und läuft durch den Filter (Option „LAN-IPs behalten“).

### 3.8 Grafana und Prometheus
- `docs/grafana/ntp-gui.json` mit `${DS_PROMETHEUS}` und Variable `instance`, zusätzlich auf grafana.com veröffentlichen.
- `docs/prometheus/alerts.yml`: Offset, Quellenausfall, NTS-Zertifikat läuft aus, Neustarts.
- Ein Test prüft, dass alle Metriken in Dashboard und Regeln wirklich existieren (sonst veralten sie beim Umbenennen still).

### 3.9 Update-Prüfung und Signaturen
- Die Instanz lädt nichts herunter, braucht also nichts zu verifizieren. sigstore-python im Image widerspräche „Sicherheit durch Einfachheit“.
- Stattdessen `actions/attest` im Release-Workflow (`id-token: write`, `attestations: write`, `packages: write`) und im README `gh attestation verify oci://ghcr.io/mgc20/ntp-gui:<ver> -R mgc20/ntp-gui`.

## 4. Quellen

- Debian-Pakete: [chrony (alle Suiten)](https://packages.debian.org/search?keywords=chrony&searchon=names&exact=1&suite=all&section=all) · [gpsd bookworm](https://packages.debian.org/bookworm/gpsd) · [Dateiliste gpsd](https://packages.debian.org/bookworm/amd64/gpsd/filelist) · [gpsd-clients](https://packages.debian.org/bookworm/gpsd-clients) · [python3-gps](https://packages.debian.org/bookworm/python3-gps) · [python3-paho-mqtt](https://packages.debian.org/bookworm/python3-paho-mqtt) · [mosquitto-clients](https://packages.debian.org/bookworm/mosquitto-clients) · [apprise](https://packages.debian.org/bookworm/apprise) · [keepalived](https://packages.debian.org/bookworm/keepalived) · [caddy](https://packages.debian.org/bookworm/caddy) · [tzdata trixie](https://packages.debian.org/trixie/all/tzdata/filelist) · [tzdata-legacy trixie](https://packages.debian.org/trixie/all/tzdata-legacy/filelist)
- Debian-Lebenszyklus: [bookworm geht an LTS](https://www.debian.org/News/2026/20260712.en.html) · [linuxiac: LTS bis 2028](https://linuxiac.com/debian-12-bookworm-moves-to-lts-extending-security-support-to-2028/)
- chrony: [NEWS (selectopts 4.4, leapseclist 4.6)](https://chrony-project.org/news.html) · [chrony.conf 4.6: tempcomp, leapseclist](https://chrony-project.org/doc/4.6/chrony.conf.html)
- gpsd/linuxptp: [ubxtool-Handbuch](https://gpsd.gitlab.io/gpsd/ubxtool.html) · [gpsd JSON](https://gpsd.gitlab.io/gpsd/gpsd_json.html) · [ts2phc](https://linuxptp.nwtime.org/documentation/ts2phc/)
- Benachrichtigungen/MQTT: [ntfy Publish-API](https://docs.ntfy.sh/publish/) · [Apprise auf PyPI](https://pypi.org/project/apprise/) · [Apprise-API](https://github.com/caronc/apprise-api) · [paho-mqtt auf PyPI](https://pypi.org/project/paho-mqtt/) · [Home Assistant MQTT-Discovery](https://www.home-assistant.io/integrations/mqtt/)
- Allan: [NIST SP 1065](https://tf.nist.gov/general/pdf/2220.pdf) · [AllanTools auf PyPI](https://pypi.org/project/AllanTools/)
- Pflegezustand (geprüft 01.11.2026): [Debian-Paketsuche gpsd](https://packages.debian.org/search?keywords=gpsd&searchon=names&exact=1&suite=all&section=all) · [linuxptp](https://packages.debian.org/search?keywords=linuxptp&searchon=names&exact=1&suite=all&section=all) · [gpsd NEWS (3.26: ant_stat, jam)](https://fossies.org/linux/gpsd/NEWS) · [paho-mqtt Release-Historie](https://pypi.org/project/paho-mqtt/#history) · [Watchtower archiviert (linuxiac)](https://linuxiac.com/docker-update-tool-watchtower-reaches-end-of-maintenance/) · [containrrr/watchtower](https://github.com/containrrr/watchtower)
- Logs: [Promtail EOL (Grafana-Doku)](https://grafana.com/docs/loki/latest/send-data/promtail/) · [Big Bang ADR: Alloy statt Promtail](https://docs-bigbang.dso.mil/latest/docs/community/adrs/0004-alloy-replacing-promtail/)
- Attestations: [actions/attest](https://github.com/actions/attest) · [gh attestation verify](https://cli.github.com/manual/gh_attestation_verify)
- Lokal geprüft im Test-Image: `ubxtool`, `gpsctl`, `ts2phc` vorhanden; `ubxtool` scheitert ohne `python3-gps`; `leap-seconds.list` läuft am 28.06.2027 ab. *(Achtung: Das lokale Test-Image basiert auf Ubuntu 24.04, die Paketversionen darin sind nicht maßgeblich.)*

## 5. Offene Fragen (Entscheidung des Maintainers)

1. **Erste Nicht-stdlib-Abhängigkeit (paho-mqtt):** paho ist stabil, aber seit 29.04.2024 ohne
   Release. Alternative ohne neue Abhängigkeit für die erste Stufe: Home Assistant per
   REST-Sensor gegen `/api/v1` (nur Doku, siehe [version-1.4.md](version-1.4.md#offene-fragen)).
   Lohnt MQTT in 1.4 schon, oder erst, wenn Nutzer danach fragen?
2. ~~**Übergang trixie**~~ – entschieden ([E2](entscheidungen.md)): `leapseclist` sofort, mit
   Migration (umgesetzt in 1.3.1).
3. **HTTPS im Dashboard selbst** (Handshake-Falle, Zertifikats-Neuladen) oder nur Reverse Proxy
   dokumentieren? Sicherheit durch Einfachheit spricht für „nur Doku“, Bequemlichkeit im LAN
   für stdlib-HTTPS.
