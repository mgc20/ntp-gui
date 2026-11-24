# Changelog

Alle nennenswerten Änderungen an ntp-gui. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/).

## [Unveröffentlicht]

## [1.11.0] – 2026-11-24

Schwerpunkt: Betrieb und Fehlersuche. ntp-gui meldet sich auf Wunsch regelmäßig bei deinem eigenen
Wächter, hat eine strenge Bereitschaftsprüfung `/readyz` für keepalived und Load-Balancer, eine
Fehlersuche „Mein Gerät bekommt keine Zeit“, Betriebsmetriken für Prometheus und eine Hilfe mit
Inhaltsverzeichnis und tiefen Links. Die Einstellungen liegen nach jedem Speichern zusätzlich als
Kopie bereit. Alles Ausgehende bleibt opt-in und standardmäßig aus. `/metrics` enthält keine
Satellitenzahlen und keinen genauen HDOP mehr; lies vor dem Update die Update-Hinweise
„Von 1.10 auf 1.11“ in der [README](README.md#von-110-auf-111).

### Hinzugefügt
- **Kopie der Einstellungen:** Jedes erfolgreiche Speichern legt dieselbe Fassung zusätzlich als
  `settings.json.bak` im Datenverzeichnis ab (Rechte `0600`). Ist `settings.json` beschädigt, hebt das
  Dashboard sie als `settings.json.defekt-<Zeit>` auf (höchstens drei Fassungen), bevor du sie ersetzt.
  Das Container-Log und der Hinweis im angemeldeten Dashboard nennen beide Dateien und den Stand der
  Kopie; die Sperrseite ohne Anmeldung sagt nur, dass eine Kopie daneben liegt. Die README zeigt, wie du
  zum letzten funktionierenden Stand zurückkehrst.
- **Zeitwächter-Ping** (opt-in, Standard aus): ntp-gui meldet sich regelmäßig bei deinem eigenen Wächter
  (Uptime Kuma mit Monitor-Typ „Push“, Healthchecks oder kompatibel). Bleibt der Ping aus (Rechner,
  Container oder Strom weg), schlägt der Wächter Alarm, auch wenn ntp-gui selbst nichts mehr senden kann.
  - Einstellungen unter **System → Einstellungen → Dashboard & Zugang**: Adresse (leer = aus, keine
    Verbindung), Intervall (30–3600 s, Standard 60 s) und Art (automatisch, Healthchecks `…/fail`,
    Uptime Kuma `status=down`, nur Lebenszeichen). Der Zustand steht direkt unter dem Adressfeld.
  - Bei kritischem Zustand (roter Hinweis in der Übersicht) meldet der Ping „ausgefallen“, aber erst nach
    einer Haltezeit von 2 Minuten. Ein Neuladen der Zeitdienste nach einer Einstellung, ein kurzer
    Dienst-Neustart oder der Start des Containers lösen so keinen Alarm aus; nach Ablauf der Haltezeit
    wird sofort nachgeprüft. Mit der Art „nur Lebenszeichen“ geht im kritischen Zustand nichts hinaus.
  - Gesendet wird nur eine GET-Anfrage ohne Inhalt mit dem User-Agent `ntp-gui`. Im Datenschutzfilter ist
    das der neue Zweck `heartbeat` mit leerer Feldliste. Keine Weiterleitungen, höchstens 5 s, das Ziel
    wird wie bei den Benachrichtigungen nach der Namensauflösung geprüft. Ein Wächter im Internet sieht
    die öffentliche IP-Adresse; Empfehlung: Wächter im eigenen Netz.
  - Seite **Benachrichtigungen**: Karte „Zeitwächter-Ping“ mit Ziel (gekürzt), letztem Ergebnis, nächstem
    Ping und **Jetzt senden** (`POST /api/v1/notify/heartbeat/test`, nur Verwaltungsrecht, höchstens alle
    10 s). Läuft gerade ein Ping, kommt „Ein Ping läuft gerade“ (HTTP 409); im kritischen Zustand mit „nur
    Lebenszeichen“ „Zustand kritisch – nichts gesendet“.
  - Ereignisart „Zeitwächter-Ping“: Warnung nach drei Fehlschlägen in Folge, „wieder erreichbar“ bei
    Erfolg. Beides kann an die Benachrichtigungskanäle gehen.
  - Anleitung [docs/integrationen/zeitwaechter.md](docs/integrationen/zeitwaechter.md) (mit den
    Prometheus-Metriken des Pings); `uptime-kuma.md` um den Push von ntp-gui ergänzt.
- **Fehlersuche „Mein Gerät bekommt keine Zeit“** unter Clients, mit einem Verweis darauf auf der
  Diagnose-Seite, der direkt zur Karte springt (`#/clients?s=fehlersuche`) und den Cursor ins Eingabefeld
  setzt. Du gibst die IP-Adresse eines Geräts ein (auch in Langform, in Großbuchstaben oder als
  `::ffff:`-Adresse; das Feld zeigt danach die geprüfte Kurzform), ntp-gui geht eine feste Prüfliste
  durch und nennt genau einen Befund mit dem nächsten Schritt. Geprüft wird:
  - liegt die Adresse in den erlaubten bzw. ausgenommenen Netzen („all“ in „Ausgenommene Netze“ gilt wie
    bei chronyd als Sperre für alle Geräte),
  - lauscht chronyd auf dem NTP-Port und der Bind-Adresse (ein anderer Port als 123 ist kein Problem, wenn
    das Gerät ihn schon erfolgreich fragt; im Bridge-Netz wird die passende Portfreigabe genannt),
  - ist der Server synchron bzw. im Inselbetrieb (samt der Regel für öffentliche Netze),
  - erscheinen die Geräte im Bridge-Netz nur als Docker-Gateway,
  - sind Anfragen angekommen oder ist das Gerät verstummt,
  - hat die Begrenzung Anfragen verworfen (bei öffentlich erreichbarem Server mit dem Rat zu einem
    längeren Abfrageintervall des Geräts statt einer lockeren Begrenzung),
  - ist die Uhr des Geräts messbar und wie weit liegt sie daneben.

  Wo es passt, stehen die Anleitungen für Windows (w32tm), systemd-timesyncd, chrony und macOS darunter.
  Die Prüfung braucht eine Anmeldung und liest nur, was der Server schon weiß: Sie löst keine Namen auf,
  schickt nichts ins Netz und misst nicht. Nachmessen geht weiter nur über das gedrosselte „Aktiv
  nachmessen“ auf der Geräteseite. API: `GET /api/clients/troubleshoot?ip=` (Leserecht).
- **Strenge Bereitschaftsprüfung `/readyz`** für keepalived, Load-Balancer und Uptime-Monitore: `200` nur,
  wenn chrony an eine echte Quelle synchronisiert ist, eine Quelle ausgewählt hat und die Fehlerschranke
  (|Offset| + Root-Dispersion + halber Root-Delay) unter der Grenze liegt, sonst `503`. Im Holdover und
  während eines Holdover-Tests kommt sofort `503`, keepalived gibt die virtuelle IP also spätestens nach
  einem Messintervall ab. Fehlt ein Wert oder ist er unlesbar, gilt das ebenfalls als `503`.
  - Wie `/healthz` ohne Anmeldung, für jeden Host-Namen und auch bei `WEB_REQUIRE_AUTH=true` erreichbar.
    Die Antwort enthält nur Wahrheitswerte (`status`, `chrony`, `synchronised`, `source_selected`,
    `within_limit`), keine Zahlen, Quellen oder Grenze.
  - Die Grenze steht in der neuen Einstellung „Bereitschaft (/readyz): Fehlergrenze“ bzw. in
    `READY_MAX_ERROR_MS` (Standard 100 ms).
  - Anleitung für keepalived (`track_script`), Docker-Healthcheck und Uptime Kuma in
    [docs/integrationen/bereitschaft.md](docs/integrationen/bereitschaft.md), samt der genauen Angabe, was
    `/readyz` ohne Anmeldung verrät.
- **PTP-Profil „SMPTE ST 2059-2 (Broadcast)“** (`PTP_PROFILE=st2059`) als Voreinstellung nach den
  Profilwerten, ohne SMPTE-Zertifizierung: Domain 127, UDPv4, End-to-End, Sync und Delay-Request 2^−3 s,
  Announce 2^−2 s, Announce-Timeout 3, Priority 128/128. Jedes Feld bleibt einzeln überschreibbar; Domain 0
  und Announce-Intervall 1 gelten als „nicht geändert“ (wer sie braucht, nimmt das Profil `default` mit
  eigenen Werten). Werte außerhalb der Profilbereiche meldet die PTP-Seite als Prüfpunkt, und sie stehen
  als Hinweis in `ptp4l.conf`.
- **Betriebsmetriken in `/metrics`**, nur als Summen und feste Werte, ohne Adressen, Gerätenamen,
  Kanal-URLs oder Dateinamen:
  - Client-Uhrgüte je Stufe (`ntpgui_clients_quality{grade}`), verstummte Geräte, offene Client-Alarme und
    wie lange die passive Client-Messung schon ohne Pause mithört (`ntpgui_clients_listening_seconds`).
  - Je Client-Gruppe: Geräte, aktive, stille, messbare, Median der Abweichung, Anteil „gut“ und Median
    der Uhrgüte (`ntpgui_client_group_*`).
  - Benachrichtigungen je Kanal-Art: angelegte, eingeschaltete und fehlschlagende Kanäle,
    Warteschlange, Zustellungen und verworfene Meldungen (`ntpgui_notify_*`).
  - Alter, Anzahl und Fehlschlag der nächtlichen Sicherung (`ntpgui_backup_nightly_*`), Ereignisse je
    Art und Stufe (`ntpgui_events_total`), Ergebnis des letzten Holdover-Tests (`ntpgui_holdover_last_*`),
    Modus und Phase der GPS-Automatik (`ntpgui_gps_autocal_*`) und der Zustand des Zeitwächter-Pings
    (`ntpgui_heartbeat_*`).
- Neue Einstellung „Gruppennamen in /metrics“ (`METRICS_GROUP_NAMES`, Standard aus). Prometheus sieht
  sonst nur die Kennung der Gruppe (`group_id`, z. B. `g3`), weil Gruppennamen oft Räume oder Orte
  beschreiben.
- Grafana-Dashboard: neue Zeile „Clients und Betrieb“. Neue Alarmregeln für Client-Uhren außer Toleranz,
  verstummte Client-Gruppen (erst nach 24 h ununterbrochenem Mithören, nie für „ohne Gruppe“), gestörte
  Benachrichtigungskanäle, hängende Warteschlange, fehlende (`NtpGuiNightlyBackupMissing`: seit über 26 h
  eingeschaltet, aber noch keine), zu alte oder fehlgeschlagene nächtliche Sicherung, kritische
  Ereignisse, gescheiterte Holdover-Tests (24 h nach dem Testende), eine wartende GPS-Automatik und einen
  scheiternden Zeitwächter-Ping.
- **Hilfe mit Inhaltsverzeichnis und Unterseiten:** `#/hilfe` zeigt die Themen nach Abschnitten, jedes
  Thema hat eine eigene Adresse (`#/hilfe/gps`) mit Links zum vorigen und nächsten Thema, jeder Eintrag
  einen festen Link zum Teilen (`#/hilfe/gps/pps`). Die Suche durchsucht weiter alle Themen, „Zurück“ und
  „Vor“ im Browser folgen dem Weg durch die Hilfe und rollen zum Eintrag. Ein Link auf einen Eintrag, der
  inzwischen unter einem anderen Thema steht, führt auf dessen Thema; ein unbekannter Eintrag oder eine
  kaputte Adresse zeigt einen Hinweis.
  - „Mehr in der Hilfe →“ in jedem ⓘ und unter jeder Seite führt direkt zum passenden Eintrag bzw. Thema.
  - Neues Hilfethema „Betrieb und Überwachung“: was wofür (Benachrichtigungen, Zeitwächter-Ping,
    `/healthz`, `/readyz`, `/metrics`, Fehlersuche), Bereitschaft `/readyz` und die Betriebsmetriken.
    Neuer Eintrag „SMPTE ST 2059-2 im Studio“ unter PTP.

### Geändert
- **`/metrics` ohne Satellitenzahlen:** `ntpgui_gps_satellites_used`/`_seen` und
  `ntpgui_gps_snr_avg_db` entfallen; als Signalstärke steht nur noch der stärkste Wert der genutzten
  Satelliten (`ntpgui_gps_snr_max_db`). `ntpgui_gps_hdop` steht nur noch als Stufe (1, 2, 5, 10, 20), wie
  in der Aufzeichnung des Diagnosepakets. Als Zeitreihe grenzen genaue Werte die Region ein. Das
  Grafana-Panel „GPS-Satelliten“ heißt jetzt „GPS-Empfang“ und zeigt HDOP-Stufe, Empfang und Fix-Art.
- Doku und Hilfe zu „Datenschutz in den Metriken“ nennen auch die Namen bzw. Adressen der Zeitquellen
  (Label `source`) und das PPS-Gerät (Label `device`) als frei vergebene Texte.
- Die Adresse des Zeitwächters wird wie ein Geheimnis behandelt: nicht in Sicherungen (die Vorschau meldet
  „neu eingeben“), im Diagnosepaket nur „gesetzt“, für API-Schlüssel mit Leserecht und im Lese-Export nur
  gekürzt (`https://host/…`), in `/api/status` gar nicht. `/api/status` und `GET /api/notify` enthalten
  den Zustand des Pings (`heartbeat`).
- Die Statusabfrage liest die Sicherheitskopie der Einstellungen nur noch, wenn `settings.json` nicht
  lesbar ist.
- `/healthz` bleibt unverändert und ist in der Hilfe (API & Automatisierung) als Lebenszeichen für den
  Container-Healthcheck beschrieben; Load-Balancer stehen bei `/readyz`. Die Sperr-Meldungen nennen beide
  offenen Endpunkte. Die README nennt `POST /api/notify/heartbeat/test` in der API-Übersicht.
- Alte Hilfe-Links `#/hilfe?t=…` öffnen den Eintrag jetzt auf der Unterseite seines Themas. Der
  Zeitwächter-Ping steht in der Hilfe unter „Betrieb und Überwachung“ (bei Benachrichtigungen unter
  „Siehe auch“).

### Behoben
- pmc, phc2sys und die PTP-Statusanzeige verwenden die wirksame Domain des gewählten Profils statt des
  gespeicherten Felds. Ein Profil, das die Domain vorgibt, ließ die Abfragen an ptp4l sonst ins Leere
  laufen.
- `/metrics`: Die Metriken je Zeitquelle stehen jetzt je Familie am Stück, wie es das
  Prometheus-Textformat verlangt. Vorher wechselten sie sich bei mehreren Quellen ab.
- Hilfe „Grund (Auswertung von chrony)“: Die Hervorhebung von „ausgewählt (*)“ und „kombiniert (+)“
  erschien als rohe Sternchen.

## [1.10.0] – 2026-11-24

Schwerpunkt: Die Studiouhr bekommt Spielereien – Eieruhr und Pomodoro, eigene Countdowns, Nachtmodus,
Binäruhr, Mondphase, Nerd-Zeile, Fortschrittsbalken, ein Reaktionsspiel, Zeitzeichen und Ostereier.
Alles rechnet und merkt sich nur dein Browser, nichts wird gesendet. Mit `?fun=0` bzw. `?eggs=0` ist
es abgeschaltet; Studio-, Kachel- und Banner-Voreinstellung, Kiosk und OBS bleiben ruhig wie bisher.

### Hinzugefügt
- **Timer (Studiouhr):** Das neue Panel **Timer** auf `/clock` hat eine Eieruhr (Schnellwahl 1–30 min
  oder eigene Dauer wie `7:30`), „+1 min“ am Countdown und ein deutliches Ende („Zeit ist um!“ mit
  Rahmen, ohne Blinken).
  - **Pomodoro** per Knopf oder `?pomo=25m&pause=5m`: Arbeit und Pause wechseln von selbst, jede vierte
    Pause ist lang, und die Uhr zählt die geschafften Runden.
  - **„Ton am Ende“** piept erst nach deinem Klick und nur, solange die Seite offen ist. Liegt die Seite
    in einem Hintergrund-Tab, plant sie die Töne von Eieruhr und Pomodoro bis zum Ende voraus. Die Hilfe
    nennt, wann der Ton trotzdem ausbleibt.
- **Eigene Countdowns:** Bis zu fünf, die sich nur dieser Browser merkt. Lässt der Browser kein Speichern
  zu, sagt das Panel „nur bis zum Neuladen gemerkt“. Eingebaute Ziele, gerechnet auf der Serverzeit wie
  `?until=`: `?goal=newyear` (Neujahr), `?goal=dst` (nächste Zeitumstellung), `?goal=unix` (Unixzeit
  2 000 000 000), `?goal=y2038` (Jahr-2038-Problem, Unixzeit 2³¹ am 19.01.2038 03:14:08 UTC) und
  `?goal=ntp` (Ende der NTP-Ära 2036).
- **Nachtmodus:** Er dimmt grau oder rot (`?dimred=1`), schaltet nach der Ortszeit des Geräts mit
  `?dim=22-6`, die Helligkeit stellst du mit `?dimlevel=20..80` ein. Von Hand per Knopf **Nacht** oder
  Taste N; das gilt bis zum nächsten Wechsel des Zeitplans. Wünscht das System mehr Kontrast
  (`prefers-contrast: more`), bleibt die Uhr mindestens zu 60 % hell. Das On-Air/REC-Signal wird nie
  gedimmt. Im Link-Baukasten gibt es dafür eine eigene Gruppe „Nachtmodus“.
- **Design „Binär“** (`/clock?design=binary`) mit Lämpchen je Ziffer (8-4-2-1) oder mit `?bin=plain` als
  Dualzahl für Stunde, Minute und Sekunde, Dezimalwerte daneben. Damit gibt es acht Designs, mehr werden
  es nicht.
- **Zusätze unter der Uhr**, standardmäßig aus und per `?show=moon,nerd,progress` einzeln einzuschalten.
  Die Voreinstellung `nerd` zeigt alle drei.
  - **Mondphase**, rein rechnerisch im Browser. Ein Klick auf den Mond zeigt ihn wie auf der
    Südhalbkugel (nur in diesem Browser gemerkt, und nur dort, wo es die Knöpfe Timer und Nacht gibt).
  - **Nerd-Zeile** mit Unixzeit, TAI, GPS-Woche und -Sekunde, MJD, Tag im Jahr und ISO-Woche; auf
    Bühnen ab 700 px Höhe (nicht im Banner) zusätzlich die Unixzeit hexadezimal und die Uhrzeit römisch
    (Mitternacht „N:N“).
  - **Fortschrittsbalken** für Tag, Woche, Monat, Jahr oder die laufende Eieruhr (`?bars=`).
  - Tag im Jahr, ISO-Datum und Kalender-Balken gelten für das angezeigte Datum, im Design `tc` mit
    abweichender Zone des Servers also für die Zone des Servers.
- **Spiel „Tippe auf :00“:** Der Knopf **Spiel** öffnet ein Reaktionsspiel. Du tippst auf „Jetzt!“, genau
  wenn die Uhr auf die volle Sekunde oder die volle Minute springt. Die Uhr zeigt deine Abweichung in ms
  mit Wertung und daneben die Messgenauigkeit (Abgleich ± halbe Laufzeit, Serveruhr, Bildauffrischung).
  Den Bestwert merkt sich nur dein Browser.
- **Zeitzeichen:** Das Panel **Ton** spielt wie im Radio fünf kurze Töne und einen langen zur vollen
  Stunde (oder jede Minute) deiner Ortszeit, im Hintergrund-Tab bis dahin vorausgeplant. Es startet nur
  nach deinem Klick und ist ausdrücklich keine Referenz, weil Browser-Audio und Lautsprecher den Ton
  verzögern.
- **Ostereier:** um 13:37, um 12:34:56, in den ersten zehn Minuten des neuen Jahres (mit Konfetti) und am
  Tag der Zeitumstellung. Der Konami-Code (↑ ↑ ↓ ↓ ← → ← → B A) bringt Konfetti und zeigt bis zum
  Neuladen die Binäruhr. Konfetti fällt nur per CSS; wünscht dein System weniger Bewegung, bleibt es beim
  Text. Ostereier richten sich nach der großen Zeit (im Design `tc` mit Zone des Servers nach deren Zeit
  und Tag; nach Taste U gibt es kein Zeitumstellungs-Ei). `?eggs=0` schaltet alle ab, auch im
  Link-Baukasten und in Profilen.
- `/api/v1/time` meldet `tai_utc`: den heute gültigen Abstand TAI−UTC aus der Schaltsekunden-Liste des
  Images, damit die Nerd-Zeile TAI und GPS-Zeit nicht raten muss. Das Feld steht auch ohne Anmeldung
  dort, wenn die öffentliche Uhr eingeschaltet ist; sonst gibt der öffentliche Pfad nichts Neues preis.

### Geändert
- **`?fun=0`** blendet die Knöpfe **Timer**, **Nacht** und **Spiel**, die Zeitzeichen, die Zusätze und
  die Ostereier aus. Die Voreinstellungen `studio`, `tile` und `banner` setzen `fun=0`, die
  Voreinstellung `night` dimmt von 22 bis 7 Uhr.
- **Ruhige Flächen:** In einer OBS-Browserquelle blendet `/clock` Leiste, Panels und die Knöpfe am
  Countdown aus. Im Kiosk, mit `lock=1` und in der Kachel gibt es keine Knöpfe für Timer und Nacht und
  keine Zusätze; in Kachel, Streifen (auch per Taste L) und auf sehr niedrigen Flächen keine Zusätze, auf
  E-Ink keine Nerd-Zeile. Ostereier und Konfetti gibt es dort ebenso wenig wie während des Prüfbilds
  (`?test=sync`). Fällt der Abruf eines Profils aus (`?p=studio` usw.), bleiben Ostereier, Konfetti und
  die Knöpfe Timer, Spiel und Nacht vorsichtshalber aus, bis das Profil geladen ist.
- **Schaltsekunden-Zeile:** Das Hinweisfeld über der Uhr zur möglichen Schaltsekunde am 30.6. und 31.12.
  („Heute Nacht gibt es eine Schaltsekunde …“) gilt jetzt als Osterei. Es fehlt mit `eggs=0` oder
  `fun=0`, in den Voreinstellungen `studio`, `tile` und `banner`, im Kiosk, mit `lock=1`, in OBS, auf
  E-Ink sowie in Kachel und Streifen. Die Ankündigung einer Schaltsekunde im Band bleibt.
- Nennt `?show=` nur Zusätze (z. B. `show=moon`), bleibt die restliche Uhr wie gewohnt; mit einem Profil
  (`?p=night&show=moon`) bleibt auch dessen Auswahl erhalten.
- Ohne Knöpfe am Countdown (Kiosk, OBS) sagt die Uhr „bereit – Leertaste startet“.
- In Fenstern bis 480 px Höhe (Handy quer, Streifen) bleibt die Kopfzeile einzeilig. Passen nicht alle
  Knöpfe hinein, wischst bzw. rollst du die Knopfgruppe seitlich; die Uhr bleibt so groß wie in 1.9. In
  Fenstern bis 320 px Höhe fehlt der Knopf **Spiel**, in sehr kleinen, flachen Fenstern auch Timer und
  Nacht.
- Die Kürzel-Übersicht nennt die Taste N nur, wo der Nachtmodus von Hand schaltbar ist. Die Hilfe zur Uhr
  beschreibt Kontrast, lange Pomodoro-Pause und den Zeitplan des Nachtmodus genau.

### Behoben
- Link-Baukasten: Eine lange Beschriftung drückt das Kästchen daneben nicht mehr zusammen.

### Intern
- Node-Tests mit Referenzwerten für jede Spielerei: Mondphase gegen eine Tabelle von Neu- und
  Vollmonden, TAI und GPS gegen `app/leap.py`, dazu Tests, dass `eggs=0`, `fun=0` sowie Studio-, Kachel-
  und Kiosk-Profil nie ein Ei oder Konfetti zeigen.
- Containertest: Bei eingeschalteter öffentlicher Uhr wird `/static/js/clockextras.js` ohne Anmeldung
  ausgeliefert (sonst 401), und `tai_utc` steht auch ohne Anmeldung in `/api/v1/time`.

## [1.9.0] – 2026-11-23

Schwerpunkt: Sicherheit und Betrieb auf einem VPS. Anmeldung, HTTP-Server, Eingaben, Netzdienste
und Container sind gehärtet; Dashboard und DNS-Weiterleiter laufen nicht mehr als root. Neu sind
eine Vorlage `docker-compose.vps.yml` und die Anleitung [docs/integrationen/vps.md](docs/integrationen/vps.md).
Einige Standards ändern sich (Ratelimit ab Werk, `CLIENTLOGLIMIT`, Ziele für Benachrichtigungen,
Zugang aus der Umgebung, Besitzer des Datenverzeichnisses). Lies vor dem Update die
Update-Hinweise „Von 1.8 auf 1.9“ in der [README](README.md#von-18-auf-19).

### Sicherheit
- **Anmeldung und Zugang**
  - **Bremse gegen Passwort-Raten:** Nach 5 Fehlversuchen von einer Adresse (IPv6: je /64) muss
    diese warten, zuerst 2 s, dann jeweils doppelt so lange, höchstens 15 min. In der Zeit
    antwortet der Server mit `429` und `Retry-After`, ohne das Passwort zu prüfen. Häufen sich
    Fehlversuche aus vielen Quellen, werden neue Anmeldungen kurz gebremst. Angemeldete Browser und
    Adressen mit erfolgreicher Anmeldung in den letzten 24 h sind davon ausgenommen.
  - Gleichzeitige Passwortprüfungen sind begrenzt, und ein gerade abgelehnter, identischer
    Anmeldekopf wird nicht erneut berechnet. Viele Fehlversuche lasten die CPU damit nicht mehr aus.
  - Fehlversuche stehen mit Absenderadresse im Container-Log, etwa für fail2ban. Ins
    Ereignisprotokoll kommt höchstens eine Zusammenfassung je Minute, ohne Adresse; dafür gibt es
    die neue Ereignisart „Zugang“.
  - **Zugang aus der Umgebung:** Unvollständige Zugangsdaten öffnen das Dashboard nicht mehr: Ist
    nur `WEB_USER` gesetzt oder ist `WEB_PASSWORD_FILE` unlesbar, bleibt es gesperrt. Ist nur
    `WEB_PASSWORD` gesetzt, gilt der Benutzer `admin`. Mit `WEB_REQUIRE_AUTH=true` gilt ein
    schwaches Passwort aus der Umgebung (bekannter Beispielwert, gleich dem Benutzernamen, unter 12
    Zeichen) als nicht gesetzt; das Dashboard bleibt gesperrt, das Start-Log nennt den Grund. Die
    Compose-Vorlagen enthalten kein Beispielpasswort mehr.
  - **Passwort ändern oder entfernen** verlangt das bisherige Passwort; jede Änderung steht im
    Ereignisprotokoll. Eine Anmeldeprüfung, die beim Ändern noch lief, landet nicht mehr im Merker
    für geprüfte Zugänge – das alte Passwort gilt nicht noch einige Minuten weiter.
  - Ein im Dashboard gesetztes Passwort wird mit 600 000 PBKDF2-Runden gespeichert. Ältere Hashes
    werden bei der nächsten Anmeldung umgestellt.
  - `Strict-Transport-Security`, wenn das Dashboard über einen eingetragenen Reverse Proxy per
    HTTPS aufgerufen wird.
- **API-Schlüssel**
  - Schlüssel, die angelegt wurden, als das Dashboard noch ohne Passwort war, werden nach dem
    ersten Setzen eines Passworts zur Prüfung angezeigt (behalten oder widerrufen). „Behalten“
    (`POST /api/apikeys/keep`) geht nur mit Anmeldung per Passwort.
  - Der Benutzername ist für API-Schlüssel nicht mehr sichtbar, auch nicht für Lese-Schlüssel.
  - **Leserecht:** Schlüssel mit Leserecht sehen DoT-Server (`dns_dot`) und feste Adressen
    (`dns_pin`) nur gekürzt – dort kann wie im DoH-Pfad eine Konto-Kennung stehen (z. B. NextDNS).
    Ebenso gekürzt erscheint der Name eines DoT-Servers im DNS-Status (`/api/dns`, Übersicht), in
    dessen Fehlertexten und in den Ereignissen „DNS für ntp-gui: … nicht erreichbar/antwortet
    wieder“.
  - **Alte Schlüssel (PBKDF2, Vorabversion 1.3):** Ihre Prüfung läuft höchstens einmal gleichzeitig
    und nach einem Fehlschlag erst nach einer Sekunde wieder. Falsche Schlüssel binden ohne
    Anmeldung keine beliebige Rechenzeit mehr.
- **Reverse Proxy:** Die echte Adresse zählt nur, wenn der Proxy in `TRUSTED_PROXIES` steht. Schickt
  ein eingetragener Proxy neben `X-Real-IP` auch `X-Forwarded-For` oder `Forwarded`, zählt die
  Kette nur, wenn ihr rechter Eintrag mit `X-Real-IP` übereinstimmt. Widersprechen sich beide, gilt
  keine der Angaben: Die Anmeldebremse zählt solche Anfragen unter einem eigenen Schlüssel, der nie
  als bewährte Quelle gilt und sich nichts mit der Adresse des Proxys teilt (etwa `127.0.0.1` eines
  SSH-Tunnels); die Log-Zeile „Anmeldung fehlgeschlagen von unklarer Adresse (…)“ nennt beide
  Angaben. `Forwarded: proto=` zählt neben `X-Real-IP` nicht, nur `X-Forwarded-Proto`. Vom Browser
  durchgereichte Köpfe bestimmen damit weder Adresse (Anmeldebremse, Zugriffsprotokoll) noch
  HTTPS-Erkennung. Caddy, NPM, Zoraxy und Traefik arbeiten unverändert.
- **HTTP-Server**
  - Das Dashboard hält höchstens `WEB_MAX_CONNECTIONS` Verbindungen gleichzeitig offen (Standard
    200). Weitere schließt es sofort, ohne einen Thread zu starten. Kann ein Thread nicht starten,
    läuft der Server weiter.
  - `/healthz` fragt chronyd höchstens alle 2 Sekunden ab, nicht mehr bei jeder Anfrage.
  - Unerwartete Fehler zeigen dem Client nur noch eine allgemeine Meldung; Einzelheiten wie
    Dateipfade stehen nur im Log. Ungültige Namen unter `/static/` ergeben 404.
  - Neue Schutzköpfe: Trusted Types in der Content-Security-Policy, Cross-Origin-Opener-Policy,
    Cross-Origin-Resource-Policy und Permissions-Policy. Der Server-Kopf nennt keine Python-Version
    mehr.
  - Sicherung herunterladen, Diagnose erstellen und Hardware neu prüfen nehmen keine Aufrufe von
    fremden Seiten mehr an (Sec-Fetch-Site).
- **Konfiguration für chrony und ptp4l:** Werte, die in `chrony.conf` oder `ptp4l.conf` landen, sind
  immer genau eine Zeile. IPv6-Adressen und Netze nehmen keine Scope-ID (`%eth0`) mehr an, und jede
  erzeugte Zeile wird vor dem Schreiben auf Steuerzeichen geprüft. `LEAPSECTZ` und die Zeitzone für
  Schaltsekunden nehmen nur Zonennamen unter `/usr/share/zoneinfo` an, keine Pfade.
- **Ausgehende Ziele**
  - Benachrichtigungen prüfen die Zieladresse nach der Namensauflösung, auch in IPv6-Hüllen.
    Link-local (`169.254.0.0/16`, `fe80::/10`), bekannte Metadaten-Dienste, Multicast und
    reservierte Bereiche sind nie ein Ziel. Loopback ist standardmäßig gesperrt. Ziele im Heimnetz
    und im Docker-Netz gehen weiter. Ein Token über `http://` geht nur noch hinaus, wenn die
    aufgelöste Adresse im eigenen Netz liegt.
  - Der Test-Knopf für Benachrichtigungen meldet abgelehnte, gesperrte und nicht erreichbare Ziele
    einheitlich und lässt höchstens fünf Tests je Minute zu, je Kanal einen alle 5 s.
  - Der DNS-Weiterleiter nimmt keine Link-local- oder Metadaten-Adressen als Server, DoT-/DoH-Ziel
    oder feste Adresse an. Mit `OUTBOUND_TARGETS=public` ist auch Loopback gesperrt. Die Warnung zu
    einer ungültigen DNS-Einstellung (`DNS_DOH`, `DNS_DOT`, `DNS_PIN`) nennt den Wert nicht mehr
    wörtlich, nur die Einstellung und den gekürzten Ersatzwert.
- **Benachrichtigungen und Ereignisse**
  - Kritische Meldungen (`crit`) haben je Kanal einen eigenen Rahmen von 30 je Stunde und scheitern
    nicht mehr daran, dass andere Meldungen das eingestellte Stundenkontingent aufgebraucht haben.
  - **Alarm für Client-Uhren:** Höchstens 10 solcher Meldungen je Stunde – Alarme und „wieder im
    Rahmen“ zusammen – gehen an die Benachrichtigungen, weitere nur ins Ereignisprotokoll. Dort
    haben sie ein eigenes Kontingent und verdrängen keine anderen Ereignisse mehr.
- **Sichern und wiederherstellen:** Es läuft nur ein Upload gleichzeitig, und vor dem Schreiben wird
  geprüft, ob genug Platz bleibt. Auch eine neue Sicherung zum Herunterladen wird nur einmal
  gleichzeitig erstellt. Die Vorschau beim Wiederherstellen nennt zusätzlich Einstellungen, die die
  ausgelieferte Zeit bestimmen (NTP- und NTS-Port, Zertifikat, Stratum, Ratenbegrenzung, makestep,
  Quellen- und GPS-Optionen), und darunter alle weiteren Änderungen mit altem und neuem Wert. Die
  Versionsangabe der Sicherung erscheint nur, wenn sie eine gültige Versionsnummer ist.
- **Verlauf:** Die Verdichtung für `/api/history` läuft über eine eigene Leseverbindung und hält die
  Messschleife nicht mehr auf; höchstens eine läuft gleichzeitig.
- **Zeitserver im Internet**
  - Der NTS-Schlüsselaustausch (NTS-KE) des eigenen NTS-Servers ist je Adresse begrenzt
    (`ntsratelimit`), passend zur Stufe von „Anfragen begrenzen“. „Anfragen begrenzen“ ist
    standardmäßig an; die Stufe „schonend“ bremst nur Überflutung und stört LAN-Clients nicht.
  - Stehen unter „Erlaubte Netze“ öffentliche Adressen (`all`, `0.0.0.0/0`, `::/0`, Provider-Netze),
    gelten sicherere Standards: Ratelimit „streng“ und kein Inselbetrieb. Clients aus dem Internet
    weichen so bei einem Ausfall der Quellen auf andere Server aus, statt eine frei laufende Uhr als
    gültige Zeit zu übernehmen. Ausdrücklich gesetzte Werte bleiben.
  - Übersicht und Container-Log weisen deutlich darauf hin, wenn der Zeitserver allen Adressen
    antwortet, und nennen, was noch fehlt. Die Übersicht erkennt außerdem, wenn Clients nur als
    Gateway des Docker-Netzes erscheinen (Portfreigabe über den userland-proxy), und erklärt die
    Folgen für „Erlaubte Netze“ und das Ratelimit.
- **Container**
  - Dashboard und DNS-Weiterleiter laufen nicht mehr als root, sondern als eigener Benutzer
    `ntpgui` mit no-new-privs und ohne Capabilities. Ausnahmen: `NET_RAW` für die Client-Messung,
    `NET_BIND_SERVICE` für Port 53 bzw. einen Dashboard-Port unter 1024. Nur der Supervisor bleibt
    root, chronyd behält nur `SYS_TIME`.
  - Neustarts der Zeitdienste fordert das Dashboard nur noch über zwei feste Anforderungsdateien in
    seinem eigenen Verzeichnis (`/run/ntp-gui/web`) an. Das Verzeichnis des Supervisors kann es
    nicht beschreiben.
  - Der Watchdog prüft Dienste ohne zusätzliche Prozesse. Bei erreichter Prozessgrenze gilt ein
    laufender Pflichtdienst nicht mehr fälschlich als ausgefallen, und der Container wird nicht
    gestoppt.
  - Das Image enthält keine SUID-/SGID-Programme mehr.
  - Alle Compose-Vorlagen setzen `no-new-privileges`, entfernen alle Capabilities und geben nur die
    nötigen zurück. Sie begrenzen Prozesse und Speicher und rotieren das Docker-Log (10 MB × 3).
- **NTS-Server:** Die Kopie des Schlüssels für chronyd ist nur für chronyd lesbar (`_chrony`,
  `0400`). Die Kopie des Zertifikats (`server.crt`, für die Gruppe `_chrony` lesbar) enthält nur die
  Zertifikatsblöcke; eine kombinierte PEM-Datei mit Zertifikat und privatem Schlüssel gibt den
  Schlüssel nicht mehr an diese Gruppe – und damit an das Dashboard – weiter. Das Dashboard
  erreicht den Kommando-Socket von chronyd über die Gruppe `_chrony`.
- **Supervisor:** `settings.json` und `noselect.list` im Datenverzeichnis liest er nur als
  gewöhnliche Dateien: keinem Link folgen, nicht an Pipes warten, höchstens 4 MiB bzw. 4 KiB. Alles
  andere gilt bei `settings.json` als nicht lesbar: Das Dashboard geht in den Schutzmodus, der
  Zeitserver in den Notbetrieb. Die Konfiguration wird beim Neuladen mit einer Frist erzeugt,
  sodass Watchdog, Neustarts und Hotplug weiterlaufen.
- **Einstellungen**
  - Eine vorhandene, aber nicht lesbare `settings.json` (abgeschnitten, beschädigt, ohne Leserecht)
    lässt den Passwortschutz nicht mehr still wegfallen. Das Dashboard startet dann im Schutzmodus:
    gesperrt bis auf `/healthz`, mit der Meldung „Einstellungen nicht lesbar“ und einer deutlichen
    Warnung im Log. Speichern ist gesperrt, damit die Datei nicht überschrieben wird. Mit
    `WEB_USER`/`WEB_PASSWORD` bleibt das Dashboard mit Anmeldung erreichbar. Nach einer Reparatur
    der Datei hebt sich der Schutzmodus von selbst auf.
  - Muss `settings.json` auf ein neues Schema gehoben werden, speichert der root-Teil
    (Konfiguration für chronyd) das Ergebnis nicht selbst ins Datenverzeichnis des Dashboards; die
    Migration gilt dort nur im Speicher, das Dashboard speichert sie. Die Rechte der Zwischendatei
    werden am geöffneten Deskriptor gesetzt statt über ihren Namen.

### Hinzugefügt
- **`WEB_REQUIRE_AUTH=true`:** Ohne Zugang bleibt das Dashboard gesperrt. Nur `/healthz` und eine
  Einrichtungs-Meldung antworten. Gedacht für Server, die aus dem Internet erreichbar sind (VPS).
- **`WEB_PASSWORD_FILE`:** Passwort aus einer Datei, zum Beispiel einem Docker Secret.
- **`WEB_MAX_CONNECTIONS`** (Standard 200, mindestens 8). Auf einem VPS begrenzt du die Verbindungen
  je Adresse zusätzlich im Reverse Proxy.
- **`OUTBOUND_TARGETS`** (nur per Umgebung): `lan` (Standard), `loopback` (zusätzlich Dienste auf
  demselben Rechner, z. B. Apprise bei `network_mode: host`) oder `public` (nur öffentliche Ziele,
  für einen VPS).
- **Knopf „Abmelden“** unten auf der Seite und unter Einstellungen → Dashboard & Zugang.
- **Warnungen im Start-Log**, wenn das Dashboard ohne Passwort auf allen Adressen lauscht, gesperrt
  ist oder ein schwaches Passwort aus der Umgebung nutzt. Ein schwaches Passwort aus der Umgebung
  meldet auch die Übersicht. Ist `WEB_PASSWORD` gesetzt und im Dashboard zusätzlich ein eigenes
  Passwort gespeichert, warnen Start-Log und Einstellungsseite, dass das Dashboard-Passwort nicht
  gilt.
- **Vorlage `docker-compose.vps.yml`** für einen Zeitserver im Internet: Host-Netz, strenges
  Ratelimit, kein Inselbetrieb, Dashboard nur lokal und mit `WEB_REQUIRE_AUTH=true`,
  schreibgeschütztes Root-Dateisystem mit tmpfs, `TRUSTED_PROXIES` für einen Reverse Proxy auf
  demselben Rechner, ohne Client-Messung.
- **Anleitung [docs/integrationen/vps.md](docs/integrationen/vps.md):** Firewall, Caddy mit Let's
  Encrypt, alternativ Cloudflare Tunnel mit Access (mit der Grenze, dass NTP und NTS nicht durch
  Cloudflare gehen), NTS-Zertifikat, Updates, Sicherung.
- **Benachrichtigungen überstehen einen Neustart:** Offene Probleme, Sperrzeiten und offene
  Client-Alarme liegen in der Datenbank. Es gibt keinen doppelten Alarm, und die Meldung „behoben“
  fehlt nicht.
- Der Supervisor legt die Rechte des Containers beim Start in `/run/ntp-gui/container-caps` ab,
  lesbar für das Dashboard. Hardware-Check, Einrichtungs-Assistent und PTP-Prüfung werten sie aus.
- Hilfe (ⓘ) „Anfragen begrenzen“.

### Geändert
- **„Anfragen begrenzen“** (`NTP_RATELIMIT`) hat die Stufen `aus`, `schonend` (Standard) und
  `streng`. `true` entspricht `streng` (der bisherigen Einstellung), `false` entspricht `aus`.
- **`CLIENTLOGLIMIT`** hat als Standard 2 MiB (etwa 16 000 Adressen) statt 10 MB.
- **Passwörter im Dashboard:** Bekannte Beispielwerte (etwa `bitte-aendern`), sehr gleichförmige
  Passwörter und ein Passwort gleich dem Benutzernamen werden abgelehnt.
- **Expertenvariablen**, die in `chrony.conf` landen (`GPS_SHM_UNIT`, `GPS_PPS_SHM_UNIT`,
  `MAXUPDATESKEW`, `CLIENTLOGLIMIT`, `CHRONY_LOG`, `PHC_REFCLOCK_OPTIONS`), werden geprüft. Ein
  ungültiger Wert fällt mit Warnung im Start-Log auf den Standard zurück.
- **Fehlermeldung bei Benachrichtigungen:** „Ziel nicht erreichbar oder nicht erlaubt“ ersetzt
  „Verbindung abgelehnt“, „Netzwerkfehler“ und „Ungültige Antwort vom Ziel“.
- **Datenverzeichnis:** Beim ersten Start nach dem Update übergibt der Container
  `/var/lib/chrony/ntp-gui` an den Benutzer `ntpgui` (UID/GID 990). Das steht einmal im Log.
- **Anzeige:** Sehr große Abweichungen erscheinen gegliedert (z. B. „−20.717 d 14 h“ statt
  „−1790000000 s“). Schlüssel/Wert-Zeilen haben eine Höchstbreite: Auf sehr breiten Bildschirmen
  stehen Bezeichnung und Wert nicht mehr weit auseinander.
- **Dokumentation:** README mit den Abschnitten „Anmeldung und Zugang“ (mit Beispiel für den
  VPS-Betrieb), „Öffentlich erreichbarer Zeitserver“ (Ratelimit-Stufen, Inselbetrieb,
  Docker-Gateway, NTS-Schlüsselaustausch, Client-Log) und den Update-Hinweisen „Von 1.8 auf 1.9“;
  dazu gesperrte Ziele, `OUTBOUND_TARGETS`, direkt eingetragene Apprise-URLs, eine Firewall-Regel
  gegen Metadaten-Dienste, die Passwortdatei (überschreiben statt ersetzen), Prozesse unter root
  (`ptp4l`/`phc2sys`) und `/var/lib/chrony` (muss beschreibbar sein). PTP hat keine
  Authentifizierung: Es gehört in ein vertrauenswürdiges Netz, und ein Grandmaster mit GPS sollte
  die Rolle „Grandmaster“ haben (README, Hilfe, SECURITY.md). SECURITY.md: unterstützte Version
  1.9.x, Betrieb auf einem VPS ist unterstützt. Versionsbeispiel in den Vorlagen: `:1.9`.

### Behoben
- **Neue Konfiguration abgelehnt:** Lehnt chronyd eine neue Konfiguration ab, bleibt die bisherige
  aktiv, statt dass der Container beim Neustart stehen bleibt. chronyd prüft die Datei vorher
  (`chronyd -p`). Status, Ereignisprotokoll und Vorschau nennen den Grund. Ist eine gespeicherte
  Einstellung beim Start ungültig, startet ntp-gui mit Umgebung und Standardwerten und meldet das.
- **Ohne `CAP_KILL`** (z. B. `cap_drop: [ALL]` ohne `KILL`) hing der Supervisor beim ersten
  Speichern mit Neustart dauerhaft. Jetzt wartet er nur begrenzt, versucht SIGKILL und meldet einen
  gescheiterten Neustart; der laufende chronyd bleibt aktiv. Beim Start warnt das Log, wenn
  `CAP_KILL` fehlt.
- **Schreibgeschütztes Root-Dateisystem:** Mit `read_only: true` startete der Container nicht. Die
  erzeugte Konfiguration liegt dann automatisch unter `/run/ntp-gui-conf`.
- **Dashboard ohne Antwort des Servers:** Es bleibt nicht mehr auf dem letzten Stand stehen;
  Abfragen haben ein Zeitlimit, danach erscheint der Hinweis „Werte veraltet“.
- Einstellungen und andere Formulare melden nicht mehr „Gespeichert“, wenn statt des Dashboards
  etwas anderes leer oder mit einer HTML-Seite antwortet (Proxy, Anmeldeseite). Leere Antworten
  zeigen eine deutsche Meldung statt eines englischen Browsertexts.
- Einstellungen, Hardware-Check, GPS-Empfänger, Kalibrierung, Störungserkennung, Holdover- und
  Antennen-Test zeigen nach einem Serverfehler die Ursache statt endlos „Wird geladen …“.
- **Uhr in der Zukunft:** Ging die Systemuhr weit vor, ging der ganze Verlauf verloren und das
  1-h-Diagramm blieb danach leer. Jetzt bleibt der Verlauf erhalten, die Diagramme enden bei der
  aktuellen Zeit, und Messpunkte aus der Zukunft verschwinden, sobald chrony die Uhr wieder als
  plausibel meldet. Die Update-Prüfung setzt danach nicht mehr wochenlang aus.
- **Sicherungen bei kleinem Messintervall** wurden größer, als die eigene Wiederherstellung annimmt.
  Jetzt wird der Rohverlauf in der Sicherung bei Bedarf ausgedünnt (der 5-Minuten-Verlauf bleibt
  vollständig), sodass jede Sicherung wiederherstellbar ist.
- Eine unendliche oder sehr große Zahl in den Einstellungen (auch über die API) ergibt eine
  verständliche Meldung am Feld statt HTTP 500. Ganzzahl-Felder lehnen Nachkommastellen und
  ungewöhnliche Schreibweisen ab.
- Tief verschachteltes JSON wird mit 400 abgelehnt, statt die Anfrage ohne Antwort abzubrechen. Das
  gilt auch für das Manifest einer Sicherung.
- HEAD auf `/api/backup` und die Diagnose-Downloads ergibt 405 und baut keine Sicherung mehr. Die
  Sicherungs-Antwort trägt den Kopf `X-Content-Type-Options` nur noch einmal. Das Namensmuster
  gespeicherter Sicherungen akzeptiert keinen angehängten Zeilenumbruch mehr.
- Der Datenschutzfilter braucht bei langen Leerraum-Folgen keine übermäßige Rechenzeit mehr.
- `GPS_SHM_UNIT` mit Text bricht die Erzeugung der Konfiguration nicht mehr ab.
- **Diagnosepaket:** Die Aufzeichnung verwarf jede Client-Liste (`chronyc -c clients`) als „Zeile
  entfernt“. chrony schreibt unbekannte Werte dort als 127; zwei Nachbarn wie `0,127,127,184` hielt
  die Schlussprüfung für Dezimalzahlen mit Komma und damit für ein Koordinatenpaar. Ganzzahlige
  Spalten in solchen Bereichen bekommen jetzt ein `+` davor – der Wert bleibt gleich, die Prüfung
  bleibt unverändert streng.
- Lange Rechnernamen und Pfade werden in Statusband und Hinweisen auf dem Handy umgebrochen statt
  abgeschnitten.
- Ein per Tastatur fokussiertes Element liegt auf schmalen Bildschirmen nicht mehr hinter der
  unteren Leiste oder der Speicherleiste.
- Die Client-Messung lässt sich ohne Neustart einschalten, auch wenn sie beim Start des Containers
  aus war: Das Dashboard bekommt `NET_RAW` immer, wenn der Container sie hat.

## [1.8.0] – 2026-11-18

Schwerpunkt: Die Studiouhr bekommt Timecode, Weltzeit, eine Statuszeile für PTP und Holdover, ein
Prüfbild zum Einmessen und ein On-Air/REC-Signal.

### Hinzugefügt
- **Timecode-Anzeige (Design `tc`):** `/clock?design=tc` zeigt die Tageszeit des Servers als Timecode
  `HH:MM:SS` mit Feinstelle, gerechnet in der Zeitzone des Servers. `?fps=24|25|30|50|60|29.97|59.94`
  wählt die Bildrate (Standard 25); bei 29,97 und 59,94 zählt die Uhr Drop-Frame mit `;` vor den Frames.
  - Die Feinstelle zeigt Zehntel. Frames gibt es nur auf ausdrücklichen Wunsch mit `?sub=frames` oder
    Taste T, `?sub=off` blendet sie aus. E-Ink zeigt keine Feinstelle; wünscht dein System weniger
    Bewegung, bleiben es Zehntel.
  - Über der Zeit steht immer „Anzeige-Timecode – nicht genlocked“. Das ⓘ erklärt die Grenze: kein
    Hausreferenzsignal, der Monitor zeichnet in seinem eigenen Takt, rechne mit ± 1 bis 2 Frames.
  - Die Feinstelle wird grau, wenn die Fehlerschranke größer ist als ein halbes Frame (bei Zehnteln
    50 ms) oder dein Browser seine Zeitgeber grob rundet; der Grund steht dabei. Über `?maxerr=`
    verschwindet sie, und die Sekunden kommen aus der Wanduhr.
- **Weltzeit:** `?tz=` nimmt bis zu sechs Zeitzonen (mit Komma getrennt oder mehrfach genannt),
  `?tzl=` die Kurznamen dazu, z. B. `/clock?tz=Europe/London,America/New_York,Asia/Tokyo&tzl=LON,NYC,TYO`.
  - Ab zwei Zonen steht unter der Uhr eine Leiste: je Zone Uhrzeit, Abweichung zur großen Zeit
    („+6 h“, „+5:30 h“), Tageswechsel („+1 Tag“) und Tag oder Nacht als Symbol. Die Abweichung stimmt
    auch an Umstellungstagen.
  - Neues Layout `?layout=world` (auch über Taste L): die Zonen als Raster und Hauptinhalt.
  - Was nicht auf die Fläche passt, blendet die Uhr aus und nennt die Zahl („+2“). Mit `?h12=1` stehen
    auch die Zonen zwölfstündig.
- **Statuszeile:** Das Band der Vollbild-Uhr zeigt den Zustand von PTP („PTP eingerastet“, „PTP sucht“)
  und einen Holdover mit Dauer („Holdover seit 12 min“), immer als Symbol mit Text. Ein Screenreader
  sagt Beginn und Ende an, nicht jede Minute die Dauer.
- **Kachel (`?layout=tile`):** Der Titel des Profils steht oben links, der Zustand als Symbol in der Ecke.
- **Prüfbild `?test=sync`:** Eine Fläche wechselt genau zur vollen Sekunde zwischen hell und dunkel, auf
  Wunsch mit Klick. Damit misst du `?lead=` ein (Pfeiltasten ändern den Vorlauf, Esc beendet). Es startet
  nur mit dem Parameter in der Adresse, nie aus einem Profil, und nicht, wenn dein System weniger
  Bewegung wünscht.
- **On-Air/REC-Signal:** Mit `signal=1` im Link oder Profil zeigt ein Bildschirm einen roten Rahmen und
  einen Balken mit „ON AIR“ oder „REC“ – immer mit Text und Symbol, ohne Blinken.
  - Du schaltest es unter **Uhr & Hardware → Anzeigen → On-Air-Signal**, auf Wunsch mit Ablaufzeit, oder
    per `POST /api/v1/clock/signal` mit `{"state": "on_air"|"rec"|"off", "ttl": Sekunden}` – zum Beispiel
    vom Stream Deck über Bitfocus Companion.
  - Neues Recht für API-Schlüssel „nur On-Air-Signal der Uhr“ (`clock`): Der Schlüssel darf nur das
    Signal setzen, nichts lesen und sonst nichts ändern. Höchstens 10 Anfragen je Sekunde und Schlüssel.
  - Taste O auf der Uhr schaltet „On Air“ nur auf diesem einen Gerät.
  - Es ist eine gespiegelte Anzeige mit bis zu etwa 1 s Verzögerung, kein Tally am Bildmischer.
    Antwortet der Server nicht, bleibt der letzte Zustand stehen und ist als ungewiss markiert. Nach
    einem Neustart ist das Signal aus; in der Sicherung steht es nicht. Jeder Wechsel steht im
    Ereignisprotokoll.
- `/api/v1/time` liefert zusätzlich `ptp_state`, `holdover`, `holdover_seconds`, `signal` und
  `signal_rev`. Auch ohne Anmeldung stehen dort nur feste Zustände, nie Namen, Adressen oder Kennungen.
- Link-Baukasten und Uhr-Profile kennen die neuen Felder (Bildrate, Feinstelle, Zeitzonen, Kurznamen,
  Signal).
- Doku `docs/integrationen/studiouhr.md`: Timecode, Weltzeit, Statuszeile, Prüfbild, On-Air-Signal und
  die Anbindung über Bitfocus Companion.

### Geändert
- Diagnosepaket: In der Aufzeichnung steht HDOP nur noch als Stufe (1, 2, 5, 10, 20) statt auf eine
  Stelle gerundet. Der Wert springt, sobald ein Satellit in die Lösung kommt oder herausfällt – dieselbe
  Spur, wegen der die Satellitenzahlen dort schon fehlen. Im Schnappschuss bleibt er auf eine Stelle.

### Dokumentation
- Sichern und wiederherstellen: Der Datenschutzhinweis nennt jetzt ausdrücklich, dass der Verlauf in der
  Sicherung Satellitenzahlen und HDOP je Messpunkt ungekürzt enthält – ein Grund mehr, sie nicht zu teilen.

### Intern
- UI-Rundgang: Die Überlappungsprüfung überspringt Punkte, die in einem Scrollbereich abgeschnitten sind
  (lange Ereignisliste) – dort ist das Element nicht zu treffen.
- Tests zum Diagnosepaket beginnen ohne Hinweisquelle: Lief vorher ein Test, der den Server lädt, hing die
  Nummerierung client-NN vom dort hinterlassenen Zustand ab.

## [1.7.0] – 2026-11-14

Schwerpunkt: Die Vollbild-Uhr wird zur Studiouhr für TV, Ü-Wagen und Veranstaltungen. Sie passt sich
jeder Fläche an, zählt auf Sendebeginn herunter und lässt sich per Link oder Profil auf vielen
Bildschirmen gleich einrichten. Den Plan beschreibt [docs/konzept/studiouhr.md](docs/konzept/studiouhr.md),
die Einbindung in OBS, vMix, CasparCG und den Pi-Kiosk [docs/integrationen/studiouhr.md](docs/integrationen/studiouhr.md).

### Hinzugefügt
- **Zustand der Anzeige immer sichtbar:** Unter der Uhr steht, wie weit du ihr trauen kannst: „abgeglichen · Anzeige ± 18 ms“, „frei laufend seit 3 min“, „unsicher“ (etwa nach einem Standby) oder „Gerätezeit, nicht abgeglichen“. Den Zustand siehst du immer als Text mit Symbol, nicht nur als Farbe. Sind die Sekunden nicht mehr sicher (Fehlerschranke über 0,5 s), werden sie grau.
- **Vorlauf für Fernseher:** Mit `?lead=0…200` läuft die Anzeige so viele Millisekunden vor und gleicht die Bildverzögerung des Fernsehers aus. Der Ton auf der Sekunde bleibt exakt. Mit `?maxerr=` legst du fest, ab welcher Fehlerschranke die Anzeige als unsicher gilt.
- **Passt sich jeder Fläche an:** Je nach Fläche wählt die Uhr eines von fünf Layouts:
  - Streifen, nur die Zeit
  - Banner für 32:9 oder 1920×200
  - Spalte im Hochformat
  - Kachel für Multiviewer (`?layout=tile` ohne Leiste und Mauszeiger)
  - normal

  Dazu `?safe=` (Sicherheitsrand), `?scale=`, `?show=`, `?bg=black|transparent` zum Keyen, `?weight=` sowie `?shift=` gegen Einbrennen.
- **Design „Studio“:** Kranz aus 60 Sekundenpunkten mit 7-Segment-Ziffern, dazu `?color=`, `?sub=`, `?seconds=` und `?h12=1`. Das Design „Digital“ kann 7-Segment oder Festbreitenschrift (`?face=`), blinkenden Doppelpunkt, Zeit ohne führende Null und verschiedene Datumsformen.
- **Themen und Akzentfarbe:** `?look=studio|contrast|warm|terminal|paper|pastel` und `?accent=` (Name oder Hexwert). Eine zu schwache Akzentfarbe hebt die Uhr automatisch auf eine lesbare Stufe an.
- **Countdown und Count-up:** `?until=20:15` oder `?until=2026-12-31T23:59:59` zählt in der Zeitzone des Servers herunter. So zeigen alle Bildschirme dasselbe, auch an den Tagen der Zeitumstellung. Danach zählt die Uhr die Überzeit hoch (oder bleibt stehen mit `?after=stop`).
  - Farbstufen mit `?warn=`, immer mit Symbol und Text, ohne Blinken.
  - Ansagen für Screenreader, `?beep=` für Pieptöne in den letzten Sekunden.
  - `?label=` für eine Beschriftung, `?cd=main` macht den Countdown zur Hauptanzeige.
- **Eieruhr und Stoppuhr:** `?timer=25m` nur für dieses Gerät. Die Leertaste startet und hält an, R setzt zurück, T zeigt Zehntel.
- **Tastenkürzel:**

  | Taste | Wirkung |
  | --- | --- |
  | F | Vollbild |
  | D | Design |
  | L | Layout |
  | U | UTC groß |
  | + / − | Größe |
  | A | Uhrzeit ansagen |
  | ? | Übersicht |

  `?lock=1` sperrt Tasten und Bedienknöpfe. Rotlicht, Hell/Dunkel und Vollbild bleiben.
- **Reiter „Anzeigen“ unter Uhr & Hardware:** Du stellst die Uhr in einem Formular zusammen, kopierst den Link und öffnest eine Vorschau in fester Größe (Handy, Monitor, Banner, Kachel, Stele). Dort steht auch der Schalter „Uhr ohne Anmeldung“ mit Erklärung, was dann öffentlich ist. Er bleibt standardmäßig aus.
- **Uhr-Profile:** Speichere bis zu 20 Uhren unter einem Namen und ruf sie mit `/clock?p=name` auf. Änderst du ein Profil, übernehmen alle Bildschirme damit die Änderung innerhalb weniger Sekunden.
  - Fest eingebaut sind `studio`, `tile`, `banner`, `kitchen`, `workshop`, `night` und `nerd`.
  - Parameter in der Adresse gehen vor, und die Profile kommen mit in die Sicherung.
  - Neuer lesender Endpunkt `GET /api/v1/clock/profile`. `/api/v1/time` meldet zusätzlich `profiles_rev` und die Zeitzone des Servers.
- **Panel „Anpassen“ (⚙) auf der Uhr:** Der gewählte Stand gilt auf diesem Gerät, wenn du `/clock` ohne Parameter aufrufst.

### Behoben
- **Die Vollbild-Uhr springt nicht mehr mit der Geräteuhr.** Stellte dein Tablet oder PC seine eigene Uhr um (von Hand, nach dem Standby oder durch einen eigenen Zeitabgleich), sprang die Anzeige bis zur nächsten Messung mit. Jetzt läuft sie mit der gleichmäßigen Uhr des Browsers ab dem letzten Abgleich weiter. Erkennt sie einen Sprung oder ein Aufwachen, gleicht sie sofort neu ab.
- Auf sehr flachen oder sehr großen Flächen (1920×200, 480×270, 4K, 32:9, 9:16) bleibt die Uhrzeit ganz im Bild, ohne Umbruch und ohne Scrollbalken.

### Sicherheit
- Die Uhr prüft jeden Adressparameter streng nach Typ, Bereich, Länge und Zeichensatz. Unzulässige Werte bleiben wirkungslos. Der Server prüft die Werte der Profile nach demselben Schema.

### Intern
- Kommentare und Testnamen sachlich formuliert; der Datenschutz-Wächter lehnt Herkunftsangaben zu Nutzerdaten ab.

## [1.6.3] – 2026-11-10

Schwerpunkt: Die GPS-Fehlerschranke pendelt nicht mehr im
Tagesrhythmus, eine wiederkehrende Abschattung der Antenne gilt nicht mehr als Störung, und das Diagnosepaket
verrät über Satellitenzahlen keine Region mehr.

### Behoben
- **GPS-Fehlerschranke pendelt nicht mehr im Tagesrhythmus:** Streut das GPS nur zu bestimmten Tageszeiten stärker, wurde die Schranke nachts verkleinert und nachmittags wieder vergrößert – mit je einem Neustart von chronyd, etwa zweimal am Tag. Beim Verkleinern zählt jetzt das schlechteste 6-h-Fenster der letzten 48 h.
- **Wiederkehrende Abschattung ist keine Störung:** Brechen dieselben Satelliten genau einen Sterntag später erneut ein (fester Gegenstand vor der Antenne), meldet der GNSS-Wächter das nicht mehr als möglichen Störsender. Ein Störsender, der täglich zur selben Uhrzeit sendet, fällt weiter auf.
- **GNSS-Hinweis endet rechtzeitig:** Gehen die betroffenen Satelliten nach einem Einbruch unter, hält das den Hinweis nicht mehr über eine halbe Stunde fest.
- **Allan-Abweichung** lässt die Zeiträume von Holdover-Tests weg – dort ist die Frequenz eingefroren und täuschte Stabilität vor.
- Die harmlose gpsd-Zeile „SHM: shmctl(…) IPC_RMID failed“ beim Beenden steht im Log jetzt als erklärter `[gps]`-Hinweis statt als scheinbarer Fehler.

### Sicherheit
- **Diagnosepaket verrät die Region nicht mehr über Satellitenzahlen:** In der Aufzeichnung steht je GNSS-System nur noch die stärkste Signalstärke – jeder Sprung der Satellitenzahl markierte einen Auf- oder Untergang. PDOP und GDOP entfallen (VDOP/TDOP wären daraus rückrechenbar), das Alter des NTS-Schlüsseltauschs fehlt in der Aufzeichnung. Satelliten ohne Signal zählen nirgends mehr mit.

## [1.6.2] – 2026-11-09

Schwerpunkt: DoH-Server, die nur HTTP/2 sprechen, werden klar erkannt, die
eigenen DNS-Server melden verständliche Gründe, automatische GPS-Anpassungen starten nicht mehr alle Dienste neu,
das Diagnosepaket bleibt vollständig lesbar, und das Dashboard hängt nicht mehr nach abgebrochenen Verbindungen.

### Behoben
- **Dashboard-Server hängt nicht mehr nach abgebrochenen Verbindungen:** Bricht ein Browser oder Proxy seine Verbindung genau zwischen Annahme-Signal und Annahme ab, wartete der Server-Thread bis zur nächsten Verbindung – und ein Neustart des Dashboards konnte so lange hängen. Der lauschende Socket ist jetzt nicht blockierend.

### Intern
- Ursache des sporadisch hängenden Testlaufs gefunden (derselbe Fehler im Testserver, `tests/_support.py`); neuer Test `tests/test_accept_haenger.py`.

### Behoben
- **DoH-Server, die nur HTTP/2 sprechen:** ntp-gui fragt per HTTP/1.1 und kündigt das jetzt auch an (ALPN „http/1.1“). Antwortet der Server trotzdem nur mit HTTP/2, steht statt Binärzeichen oder „Broken pipe“ klar da: „spricht nur HTTP/2 … – nimm DNS-over-TLS oder einen DoH-Server, der HTTP/1.1 kann“. Dafür horcht ntp-gui vor der ersten Anfrage an einen DoH-Server kurz (0,1 s), ob der Server ungefragt sendet.
- **Verständliche Fehler der eigenen DNS-Server:** z. B. „verweigert die Verbindung auf Port 853 – DNS-over-TLS dort nicht eingeschaltet oder Firewall?“ oder „Zertifikat abgelehnt – Name in der Adresse und Uhrzeit prüfen“. Der Hinweis „Eigene DNS-Server nicht erreichbar“ nennt den letzten Fehler je Server. Fehlertexte aus dem Netz (Ereignisse, Benachrichtigungen, Status) enthalten nur noch druckbare Zeichen und sind begrenzt.
- **Kein wiederholter DNS-Ausfall nach Neustarts:** Ein schon gemeldeter, unveränderter Ausfall wird nach einem Neustart des DNS-Weiterleiters nicht erneut gemeldet.
- **Automatische GPS-Fehlerschranke und Kalibrierung** laden nur noch chronyd neu – gpsd, ptp4l, phc2sys und der DNS-Weiterleiter laufen weiter, der GPS-Fix bleibt stehen.
- **GPS-Schranke:** Das Einschwingen direkt nach einem Start von chronyd wird nicht mehr mitgemessen; nach kurzer Messung wächst die Schranke nur bei deutlichem Anstieg.
- **GPS-Rolle ehrlich:** „mitgerechnet“ (chrony nutzt das GPS mit kleinem Gewicht, „+“) wird von „Hauptquelle“ („*“) unterschieden; der Hinweis heißt dann „GPS wird mitgerechnet“ und behauptet nicht mehr, die Netzquellen seien schlechter.
- **NTS-Hinweis:** Das Beispiel für einen zweiten DNS-Server passt zum gewählten Modus (IP-Adressen, Namen oder URLs); lange Quellenlisten enden mit „(und N weitere)“.
- **Diagnosepaket:** Der Datenschutzfilter hielt Spalten von `chronyc -c sourcestats` für Koordinaten und zerstörte jede zweite Zeile der Aufzeichnung – jetzt bleiben die Spalten erhalten. GPS-Fehlerschranken bleiben genau; `power_profile.version` und weitere Schlüssel werden nicht mehr verstümmelt; entfernte Zeilen nennen Fundart und Befehl.

### Sicherheit
- **Diagnosepaket wiedererkennungsärmer:** Kennungen von Benachrichtigungskanälen werden zu `<kanal-N>`, Laufzeiten und der letzte NTS-Schlüsseltausch sind grob gerundet, DOP-Einzelwerte (x/y/v/t) entfallen.

### Intern
- Neues Modul `app/textsafe.py` (druckbare, begrenzte Texte); `RUN_DIR/reload-chronyd.request` lädt nur chronyd neu. Tests in `tests/test_dns_gps_filter.py` mit synthetischen Daten, darunter HTTP/2-Server mit sofortigem Schließen, RST und ALPN „h2“.

## [1.6.1] – 2026-11-09

Schwerpunkt: Die Übersicht wird auf breiten Bildschirmen wieder ruhig, Hinweise sind kompakt, alle Servertexte
im deutschen Zahlformat, und zwei irreführende Warnungen (unverschlüsseltes HTTP hinter einem nicht
eingetragenen Proxy, eigene DNS-Server) sind ehrlich.

### Behoben
- **Übersicht auf breiten Bildschirmen:** Ab etwa 1800 px wurden die Kennzahl-Kacheln so hoch wie die Hinweisliste – mit großen leeren Flächen und den Mini-Diagrammen ganz unten. Die Kacheln haben jetzt ihre natürliche Höhe, das Mini-Diagramm steht direkt unter dem Wert, die Hinweise laufen über die Kartenbreite (auf sehr breiten Bildschirmen höchstens 1200 px). Ebenso auf „Uhrqualität“: keine gestreckte Karte mehr neben „Schaltsekunden“.
- **Hinweise wieder in einer Zeile:** Jeder Hinweis der Übersicht zeigt Titel und eine Zeile, den ganzen Text unter „Details“ bzw. im ⓘ. Informationen sehen aus wie die Warnungen darüber; ein Knopf wie „Als vertrauenswürdigen Proxy eintragen“ ist auch zugeklappt sichtbar. Die Zeile „… Informationen“ zählt Erfolgsmeldungen getrennt („3 Informationen · 1 in Ordnung“).
- **Deutsches Zahlformat** in allen Texten des Servers – Hinweise, Ereignistitel, Benachrichtigungen, Hardware-Check, Diagnosepaket: „Abweichung 1,4 ms“ statt „1.4 ms“, „−“ als Minus, keine Nullen am Ende.
- **Nicht eingetragener Reverse Proxy:** ein einziger Hinweis mit Ursache und Knopf statt zusätzlich „Dashboard über unverschlüsseltes HTTP mit Anmeldung“. Liefen dabei Anmeldedaten im Klartext durchs LAN, heißt er „Anmeldung unverschlüsselt über nicht eingetragenen Proxy“ und nennt die Adresse. Die HTTP-Warnung bleibt für echte Klartext-Zugriffe ohne Proxy.
- **„Eigene DNS-Server nicht erreichbar“ ohne Grund:** War der erste eigene DNS-Server tot und der zweite etwas langsamer, zählte dessen Antwort in der verkürzten Restzeit als Ausfall. Lehnen die Server Anfragen ab (REFUSED), heißt der Hinweis jetzt „Eigene DNS-Server lehnen Anfragen ab“.

### Intern
- Zentraler Formathelfer `app/numfmt.py` (gleiche Regeln wie `fmtNumber` im Frontend) und Test `tests/test_zahlformat.py`, der deutsches Format in allen Hinweistexten erzwingt. UI-Rundgang `heroChecks` (`TOUR_HERO_ONLY=1`): Höhe der Kacheln, Leerflächen, eine Zeile je Hinweis bei 390/1440/2000/2560 px.

## [1.6.0] – 2026-11-09

Schwerpunkt: ruhiger, verständlicher, rein lokal. Neue Navigation mit sieben Bereichen, Einstellungen in
Reitern mit Suche und Vorschau, Willkommens-Assistent „In 3 Minuten fertig“, Sichern und Wiederherstellen,
Pi-Zustand (Unterspannung, Drosselung), Uhr-Werkstatt auf `/clock` und die „Heute“-Zeitleiste mit
Ereignismarkern und Tagesbericht. Keine neue Verbindung nach außen. Englisch bleibt Beta.

### Hinzugefügt
- **Einstellungen in Reitern:** Quellen · LAN-Server · GPS · PTP · Dashboard & Zugang · Sichern, jeder Reiter mit
  eigener Adresse (`#/system/einstellungen?s=gps` …). Alte Sprungziele wie `?s=web`, `?s=nts` oder `?s=dns`
  öffnen den passenden Reiter und scrollen zur Karte.
- **Suche über alle Reiter:** findet jede Einstellung nach Name, Schlüssel (z. B. `ntp_minsources`) oder einem
  Wort aus dem ⓘ; ein Treffer springt zum Feld, auch unter „Erweitert“. `/` setzt den Cursor ins Suchfeld.
  Der Schalter „nur Geänderte“ zeigt nur Werte, die vom Standard abweichen.
- **Vorschau vor dem Speichern:** „Vorschau“ in der Speicherleiste zeigt als +/−-Diff genau die Zeilen, die sich
  in `chrony.conf` und `ptp4l.conf` ändern würden. Ungültige Werte meldet sie wie das Speichern. Dabei wird
  nichts geschrieben und kein Dienst neu gestartet. Für Skripte: `POST /api/v1/settings/preview`
  (Verwaltungsrecht).
- **Nachfrage beim Verlassen:** Wechselst du mit ungespeicherten Änderungen die Seite oder schließt den Tab,
  fragt das Dashboard vorher nach.
- **Untere Leiste auf dem Handy** (bis 640 px): Übersicht, Quellen, GPS, Clients und „Mehr“ für die übrigen
  Bereiche. „Mehr“ schließt mit Esc, einem Tipp daneben oder Tab aus dem Menü heraus. Die Leiste verdeckt
  keinen Inhalt, auch nicht die Speicherleiste der Einstellungen oder den Bereich über dem Home-Indikator.
- **Tastenkürzel:** `g o` Übersicht, `g s` Zeitquellen, `g g` GPS, `g c` Clients, `g u` Uhr & Hardware,
  `g y` System, `/` springt in die Suche der Seite (falls es eine gibt), `?` zeigt alle Kürzel. Solange du in
  einem Eingabefeld tippst oder Strg, Alt oder Cmd hältst, sind sie aus. Reiter lassen sich mit den
  Pfeiltasten wechseln, der Fokus bleibt dabei auf dem Reiter.
- **Sichern und wiederherstellen** (Einstellungen → Sichern): Mit „Sicherung herunterladen“ bekommst du eine
  `.tar.gz`, in der alles steckt, was du sonst bei einer neuen SD-Karte oder einem neuen Container verlierst:
  Einstellungen, Verlauf der Messwerte, Ereignisprotokoll, Geräte mit eigenen Namen und Notizen, Gruppen,
  Regeln, GPS-Kalibrierung und Benachrichtigungskanäle. **Nie** enthalten sind GPS-Position,
  Satellitenwinkel, Passwort, API-Schlüssel, Tokens der Kanäle, ntfy-Themen, Apprise-Schlüssel,
  Webhook-Pfade, DNS-over-HTTPS- und DNS-over-TLS-Server, feste DNS-Adressen sowie NTS-Schlüssel und
  -Zertifikate. Die Datenbank in der Sicherung wird neu angelegt und nur mit festgelegten Tabellen und
  Spalten gefüllt, damit keine gelöschten Werte aus freien Seiten mitkommen. Der Dateiname enthält nur
  Datum und Uhrzeit. Die Sicherung ist ein Download – ntp-gui lädt nichts hoch.
- **Wiederherstellen in zwei Schritten:** Datei wählen → ntp-gui prüft sie und zeigt eine Vorschau, ohne
  etwas zu ändern → „Übernehmen“. Die Vorschau zeigt Zeitraum des Verlaufs, Geräte, Gruppen, Regeln,
  Ereignisse, Kalibrierung, jeden Benachrichtigungskanal (Art, Server, neu oder vorhanden, ob er
  ausgeschaltet übernommen wird, was du neu eingeben musst), sicherheitsrelevante Einstellungen mit altem
  und neuem Wert und alles, was übersprungen oder verworfen wird. Vor dem Übernehmen sichert ntp-gui den
  jetzigen Stand automatisch im Datenverzeichnis (Ordner `sicherungen`). Sicherungen älterer Versionen
  werden umgewandelt, neuere abgelehnt. Messpunkte, die nach dem Zeitpunkt der Sicherung entstanden sind,
  bleiben erhalten, damit keine Lücke entsteht. Danach steht „Wiederhergestellt aus Sicherung vom …“ im
  Ereignisprotokoll. Übernommene alte Ereignisse lösen keine Benachrichtigungen aus, und die Geräte der
  laufenden Client-Messung sind sofort sichtbar.
  Die Vorschau nennt auch die Benachrichtigungskanäle, die es nur hier gibt und die beim Übernehmen samt Token gelöscht oder durch die Fassung aus der Sicherung ersetzt werden.
- **Nächtliche Sicherung** (Einstellungen → Sichern, Standard aus): Gegen 3 Uhr landet eine Sicherung im
  Datenverzeichnis, die letzten 7 Nächte bleiben. Unter „Gespeicherte Sicherungen“ kannst du sie
  herunterladen.
- API: `GET /api/v1/backup`, `GET /api/v1/backup/list`, `POST /api/v1/restore/preview`, `…/apply` und
  `…/cancel` – nur mit Verwaltungsrecht.
- **Pi-Zustand:** Neue Karte auf der Seite Hardware: meldet der Raspberry Pi Unterspannung oder drosselt er
  den Takt – jetzt und seit dem Start des Pi –, dazu aktueller Takt und Lüfterdrehzahl. Gelesen wird nur aus
  sysfs (Firmware-Bitfeld `get_throttled`, Sensor `rpi_volt`, `fan1_input`, `cpufreq`), ohne `vcgencmd`,
  ohne zusätzliche Rechte, ohne neues Volume. Auf PCs und VMs erscheint die Karte nicht.
- Ereignisse „Unterspannung erkannt“ und „Takt gedrosselt“: entprellt, genau eines je Episode – auch über
  einen Neustart des Dashboards hinweg –, „… vorbei“ nach 10 Minuten Ruhe.
- Hardware-Check: Zeile „Stromversorgung (Pi)“ mit Hinweis auf das offizielle Netzteil (bei Hitze-Drosselung
  ein Hinweis auf Kühlung); bei Unterspannung ein Hinweis auf der Übersicht.
- Prometheus-Metriken `ntpgui_pi_undervoltage` und `ntpgui_pi_throttled`; Verlaufsfeld `pi_state`.
- **Gerätenamen direkt in der Liste ändern** (Clients): Tippe auf ✎, gib den Namen ein, Enter speichert, Esc bricht ab. Klappt das Speichern nicht, steht der Grund direkt unter dem Feld. Ohne Schreibrecht gibt es kein ✎.
- **Willkommens-Assistent „In 3 Minuten fertig“** (System → Einrichtung), fünf freiwillige Schritte:
  - **Prüfen:** Daten-Volume, Recht `SYS_TIME`, GPS-Empfänger und Pi-Zustand – bei jedem Problem genau eine Abhilfe mit Compose-Zeilen zum Kopieren.
  - **Zeitquellen:** öffentliche NTS-Server (PTB, Cloudflare, Netnod) mit einem Klick; deine bisherige Auswahl bleibt erhalten.
  - **GPS:** ja oder nein, mit ehrlichem Hinweis, was GPS ohne PPS bringt.
  - **Clients:** Adresse und Rechnername zum Kopieren, Schnipsel für Windows, macOS und Linux, Verweise auf die Anleitungen.
  - **Benachrichtigung:** optional einen Kanal anlegen und eine Testnachricht schicken.
  Geschrieben wird nur mit „Übernehmen“ – mit derselben Prüfung und Diff-Vorschau wie unter Einstellungen. „Weiter“, „Zurück“, „Später“ ändern nichts. Beim ersten Start öffnet sich der Assistent von selbst.
- **Checkliste auf der Übersicht** („3 von 5 erledigt“, Benachrichtigung optional). Sie verschwindet, wenn du sie schließt oder einmal alles grün war, und kommt bei kurzen Synchronisationsverlusten nicht wieder.
- API: `GET /api/v1/setup` (Leserecht) und `POST /api/v1/setup` mit `done`, `never`, `close_hint`, `close_checklist` oder `reset` (Verwaltungsrecht, gesperrt mit `WEB_READONLY`); diese Aufrufe ändern keine Einstellungen.
- **Uhr-Werkstatt auf `/clock`:** Neben der digitalen Anzeige gibt es vier Designs – Bahnhofsuhr (Sekundenzeiger mit kurzem Halt auf der 12), Nixie-Röhren, Klappzahlen und Wortuhr („ES IST VIERTEL NACH ZEHN“, Englisch als Beta). Dein Browser merkt sich die Wahl; fest einstellen geht mit `?design=` (`digital`, `bahnhof`, `nixie`, `flip`, `wort`).
- **Kiosk, E-Ink und zweite Zeitzone:** `?kiosk=1` ohne Leiste und Mauszeiger, `?eink=1` schwarz auf weiß und nur zum Minutenwechsel aktualisiert (auch das Statusband), `?tz=Europe/London` für eine zweite Zeitzone. Unbekannte Werte ignoriert die Uhr.
- **Ton auf der Sekunde:** nach einem Klick ein kurzer Piep je Sekunde, ein langer zur vollen Minute und ein Countdown „Uhr stellen“ – zum Stellen von Backofen, Auto- oder Armbanduhr. Die erwartete Genauigkeit steht dabei; warum Bluetooth-Lautsprecher hinterherhängen, steht im ⓘ.
- **„Wie falsch geht dein Gerät?“** (`/clock` → „Mein Gerät“): wie weit die Uhr deines Handys oder PCs danebenliegt, groß und mit Ampel. Die Messung bleibt in deinem Browser und wird weder gespeichert noch gesendet.
- Kleines Osterei am 30. Juni und 31. Dezember: ein Hinweis, dass heute 23:59:60 möglich wäre.
- `/api/v1/time` liefert zusätzlich `leap_next`, das Datum der nächsten angekündigten Schaltsekunde.
- **„Heute“-Zeitleiste auf der Übersicht:** Ein Band zeigt die letzten 24 Stunden in 5-Minuten-Abschnitten (synchron, Warnung, Fehler, Holdover), darüber Marker für Quellenwechsel, GPS-Ausfall, Neustart, Pi-Spannung und Warnungen. Tippst du auf eine Stelle (oder nutzt Tab, Pfeiltasten und Enter), öffnet sich „So sah es um … aus“: Quelle, Abweichung, Fehlerschranke und Anzahl der Satelliten – nie Satellitenwinkel oder Position.
- **Ereignismarker in allen Zeitdiagrammen:** dünne Linie mit Symbol, per Tastatur erreichbar; dicht liegende Ereignisse werden zusammengefasst. Marker-Arten lassen sich ausblenden, das merkt sich dein Browser.
- **Tagesbericht für gestern:** Anteil synchron, schlechtester Wert, Zahl der Geräte, GPS-Stunden und Pi-Spannung. Der Server rechnet ihn einmal nach Mitternacht im Hintergrund.
- API: `/api/v1/timeline`, `/api/v1/timeline/markers` und `/api/v1/timeline/at` (Leserecht).

### Geändert
- **Abzeichen nur bei geänderten Werten:** „geändert · zurücksetzen“. Zurücksetzen stellt den Standard ein –
  auch gegen einen Wert aus der Compose-Datei – und wirkt erst mit „Speichern“; bis dahin nimmt „rückgängig“
  oder „Verwerfen“ es zurück. Die Herkunfts-Abzeichen (Standard/Umgebung/Dashboard) entfallen.
- **Kürzere Hilfetexte:** Unter jedem Feld steht höchstens eine Zeile, der Rest der Erklärung steht im ⓘ.
  Gelöscht wurde nichts. „Erweitert“ ist je Abschnitt eingeklappt; geänderte erweiterte Werte bleiben sichtbar.
- **Klebende Speicherleiste** mit Zahl der Änderungen, Hinweis „Neustart der Zeitdienste nötig“, Vorschau,
  Speichern und Verwerfen. Die Reiter zeigen, wo ungespeicherte Änderungen liegen.
- Versionsangaben („Standard ab …“) stehen nicht mehr in der Oberfläche.
- **Navigation mit sieben statt elf Einträgen:** Übersicht · Zeitquellen · GPS · Clients · Uhr & Hardware ·
  System · Hilfe. Unter „Uhr & Hardware“ findest du die Reiter Uhrqualität, Hardware und PTP, unter „System“
  die Reiter Diagnose, Benachrichtigungen und Einstellungen. Neue, kurze Adressen wie `#/uhr/ptp` oder
  `#/system/einstellungen`; alte Lesezeichen (`#/ptp`, `#/hardware`, `#/einstellungen?s=gps` …) leiten ohne
  zusätzlichen Eintrag im Browserverlauf weiter. Links in Benachrichtigungen und Hinweisen führen direkt auf
  die neuen Seiten.
- Ist PTP ausgeschaltet, zeigt der Reiter PTP nur noch eine Zeile mit dem Weg zum Einschalten statt einer
  Seite voller leerer Karten.
- Auf dem Handy steht oben nur noch „NTP-GUI“; den vollen Titel und den Rechnernamen siehst du im Menü „Mehr“.
- `/metrics`, `/api/status` und `/healthz` stehen nicht mehr in der Fußzeile, sondern in der Hilfe unter
  „API & Automatisierung“.
- **Zahlen ohne Nullen am Ende:** Zeiten stehen immer in der passenden Einheit (ns, µs, ms, s), also „± 1 ms“ statt
  „± 1,000 ms“, und an Einheitengrenzen „1 ms“ statt „1.000 µs“. Dezimalzeichen, Datum und Uhrzeit folgen der
  gewählten Sprache. Negative Zahlen tragen überall dasselbe Minuszeichen (−), es gibt kein „+0 ns“ mehr, und
  Werte mit Einheit (ppm, ppb, ns bis s) stehen ohne Tausenderpunkt da („12345 ppb“).
- **Ruhigere Diagramme:** Ein leerer Verlauf steht als eine Zeile da („Satelliten im Verlauf: sammelt seit
  23:30“, bei älterem Beginn mit Datum; „keine Messwerte seit …“, wenn Daten fehlen). Ein gleichmäßiger Verlauf
  ebenfalls („Maximaler Fehler zu UTC: stabil um 420 µs – Diagramm zeigen“), Werte, die um 0 pendeln, als
  „stabil innerhalb ± 400 ns“. Verläufe mit Lücken klappen nicht zusammen. Bisher belegte jedes davon rund
  300 px. Gilt für Übersicht, Zeitquellen und GPS.
- **ⓘ leichter zu treffen:** Das Symbol ist kleiner (14 px), die Tippfläche 24 px groß, ohne benachbarte Knöpfe
  zu überdecken. Blass, bis die Maus darauf zeigt oder es den Tastaturfokus hat.
- Alle Zeitraum-Auswahlen nutzen dieselbe Komponente (15 min bis 30 Tage).
- Neue Erklärung „Zahlen und Einheiten“ in der Hilfe. Lange Code-Schnipsel in der Hilfe brechen um; auf dem
  Handy ist die Hilfe-Seite nicht mehr zu breit.
- **Aufgeräumte Seiten:** Je Karte steht nur noch eine Erklärzeile, der Rest steht im ⓘ; längere Anleitungen und Hinweise sind eingeklappt. Gelöscht wurde nichts. Sichtbare Wörter ohne Hilfe: rund 27 % weniger, auf der Clients-Seite rund 60 %.
- Zeitquellen und GPS: Die Spalte „Grund“ erscheint nur noch, wenn er etwas anderes sagt als „Zustand“.
- **Feste Farbe je Zeitquelle:** Dieselbe Quelle hat in jedem Diagramm, nach dem Neuladen und in jedem Browser dieselbe Farbe, egal welche Quellen daneben stehen. Teilen sich zwei Quellen eine Farbe, ist eine gestrichelt. GPS, PPS und andere Referenzuhren haben eine feste Signalfarbe (PPS gestrichelt). Am Linienende steht ein kurzer, eindeutiger Name (Hostname ohne Domain, IP-Adressen unverändert).
- Clients: Spalten ohne einen einzigen Messwert werden ausgeblendet. Auf dem Handy (bis 640 px) stehen die Geräte als Karten untereinander; die ⓘ zu allen Spalten stehen einmal über den Karten.
- PTP und Client-Detail nutzen die neue Diagrammkarte, die Ereignisse in der Diagnose die einheitliche Zeitraum-Auswahl.
- Diagnose: Die Rohdaten der Ereignisse sind leichter anzutippen und bleiben beim automatischen Aktualisieren aufgeklappt, auch der Tastaturfokus bleibt.
- GPS-Kalibrierung: Der Satz zur aktuellen Phase steht nur noch einmal da; bei einer Störungssperre gibt es nur noch eine rote Hinweisbox.
- Nach einem Update von 1.5.x oder nach dem Einspielen einer Sicherung auf einer neuen Installation öffnet sich der Assistent nicht von selbst; die Übersicht zeigt einmal den Hinweis „Einrichtung prüfen“.
- Der Knopf „Kopieren“ hat eine größere Tippfläche.
- `/clock` beachtet „Bewegung reduzieren“ deines Systems (Sekundenzeiger springt, Klappen ruhen) und folgt der im Dashboard gewählten Sprache. Bei „Vollbild-Uhr ohne Anmeldung“ sind dafür auch die Skripte und Sprachkataloge der Uhr ohne Login abrufbar – nur Code und feste Texte, keine Einstellungen.

### Behoben
- **Versionsnummer:** Das Image 1.5.5 meldete sich als 1.5.4. Bei eingeschalteter Update-Prüfung hast du deshalb dauerhaft ein angebliches Update gesehen, und Diagnosepaket, Startereignis und Sicherungen nannten die falsche Version. Ein Release bricht jetzt ab, wenn die Versionsnummer im Programm nicht zur Release-Version und zum Changelog passt.
- **Nicht synchron statt „Inselbetrieb“:** Hat chrony gar keine Referenz (Ref-ID 00000000), meldet ntp-gui das nicht mehr als Inselbetrieb.
- **„Nur auf dieser Adresse lauschen“** nimmt nur noch genau eine IP-Adresse an. Ein Hostname, ein Interface, ein Netz oder zwei Adressen ließen chronyd mit „Fatal error“ abbrechen – bei jedem Neustart wieder. Ein ungültiger gespeicherter Wert fällt auf „alle Adressen“ zurück.
- **Ganzzahl-Optionen** für Quellen, Refclock und PPS (minpoll, poll, rate, stratum …) lehnen Kommazahlen, Exponenten und Ziffern aus anderen Schriften ab; „stratum“ beim Refclock nimmt nur 0 bis 15. Bisher legte ein solcher Tippfehler chronyd lahm.
- Umlaute in `EXTRA_CHRONY_CONF` und `EXTRA_PTP4L_CONF` bleiben erhalten (aus „ä“ wurde „Ã¤“); andere Backslash-Folgen bleiben unverändert stehen.
- **GPS-Kalibrierung:** Die gewählte Rolle (z. B. „bevorzugen“) springt beim automatischen Aktualisieren nicht mehr zurück und wird nicht mehr still durch „auto“ ersetzt.
- **Eingabefelder:** Cursor und Markierung bleiben beim automatischen Aktualisieren erhalten; halb getippte Werte gehen nicht verloren (aus „0,5“ wurde „5“), eine geöffnete Auswahlliste schließt sich nicht mehr, und Klicks gehen nicht mehr verloren, wenn eine Aktualisierung zwischen Drücken und Loslassen fällt.
- **Neustart-Anzeige:** Bezugszeit ist die Serverzeit statt der Browseruhr – bei vorgehender Browseruhr kam sonst nie „aktiv“. Auch das Alter des letzten Temperaturwerts rechnet nach der Serverzeit.
- **Fehlerschranke der GPS-Automatik:** Ohne gespeicherte Schranke vergleicht sie mit dem Delay, den chrony wirklich nutzt, statt mit 0,2 s; eine Verkleinerung unterliegt damit wieder den Schutzregeln (12-h-Sperre, 48-h-Prüfung).
- **Empfangsbewertung:** Satelliten und dB-Hz stehen mit einer Nachkommastelle im Text, damit Zahl und Ampel nicht mehr widersprüchlich wirken.
- **PPS-Impulsrate:** wird aus den Impuls-Zeitstempeln berechnet; eine 1-Hz-PPS erscheint nicht mehr als „1,67 Impulse/s“.
- **RTC-Abweichung** steht in ganzen Sekunden statt mit Scheingenauigkeit.
- **7-/30-Tage-Diagramme:** Der letzte Punkt springt vor dem Speichern nicht mehr.
- **Allan-Abweichung** funktioniert auch mit einem Messintervall von 600 s.
- Abfragewerte wie `nan` oder `inf` (z. B. `/api/history?points=nan`) führen nicht mehr zu HTTP 500, sondern zum Standardwert.

### Sicherheit
- Basis-Image auf den aktuellen Stand von Debian trixie-slim angehoben.
- **Wiederherstellen:** Auch der gespeicherte Zustand der Client-Regeln läuft beim Einspielen durch den Positionsfilter und ist größenbegrenzt; ein verändertes Archiv kann so keine Positionsangaben in die Datenbank bringen.
- **Eingeschleuste Anfragen (HTTP-Desync):** Schickt ein Client einen Inhalt mit, den ntp-gui nicht liest (z. B. bei `GET /healthz`), per `Transfer-Encoding: chunked` oder mit widersprüchlichen `Content-Length`-Köpfen, kann dieser Inhalt nicht mehr als zweite Anfrage laufen. Hinter einem Reverse Proxy wie Caddy ließ sich sonst ohne Anmeldung eine Anfrage vor die Anfragen anderer Nutzer schieben. ntp-gui schließt in diesen Fällen die Verbindung; chunked lehnt es mit 501 ab, widersprüchliche Längen mit 400.
- **Vorschau der Konfiguration:** gleiche Rechte wie das Speichern (nur Verwaltungsrecht, CSRF-/Origin-Prüfung,
  Größengrenze); sie liest nur die Dateien, die ntp-gui selbst erzeugt, nie einen Pfad aus der Anfrage.
  Passwort, Tokens und DoH-Adressen stehen ohnehin nicht in den Konfigurationsdateien; frei eingetragene Zeilen
  (`EXTRA_CHRONY_CONF`, `EXTRA_PTP4L_CONF`, eigene Dateien), die nach Passwort, Token oder Secret aussehen,
  sowie Zugangsdaten und Pfade in URLs werden geschwärzt.
- **Wiederherstellen ohne Vertrauensvorschuss:** Das Manifest ist nicht signiert. Darum filtert ntp-gui
  beim Einspielen jede Zeile genauso wie beim Erstellen: keine Position, keine Satellitenwinkel und keine
  Geheimnisse in Messpunkten, Ereignissen und Gerätedaten, auch nicht in Grad/Minuten/Sekunden-Schreibweise,
  in Texten und Quellnamen von Messpunkten oder als Zahlenliste in Ereignis- und Gerätedaten.
  Es übernimmt nur gültige IP-Adressen und Inventar-Schlüssel und für Ereignisse nur Art und Herkunft nach
  festem Muster. Ein präpariertes Archiv bringt so weder einen Standort noch fremde Werte in die Datenbank.
- **Benachrichtigungskanäle:** Jeder Kanal wird geprüft wie bei einer Eingabe. Gibt es ihn hier schon (gleiche
  Kennung, gleiche Art, gleicher Server), behält er seine Tokens, sein Thema bzw. seinen Schlüssel und seine
  volle Adresse. Alle anderen kommen **ausgeschaltet** an, bis du Ziel und Token geprüft und den Kanal
  eingeschaltet hast. Eine Sicherung kann so keinen aktiven Kanal zu einem fremden Server anlegen.
- **Alles oder nichts:** Einstellungen, Kalibrierung und Datenbank werden in einem Zug getauscht; die beiden
  Dateien werden direkt vor dem Abschluss der Datenbank-Transaktion eingesetzt, bei einem Fehler kommen
  die alten zurück. Geht danach doch etwas schief, spielt ntp-gui die automatische Sicherung zurück – die
  Benachrichtigungskanäle behalten dabei Tokens, Themen, Adressen und Ein/Aus. Fehlermeldungen sind fest formuliert, Einzelheiten stehen nur im Log. Während der
  Übernahme ist das Dashboard einige Sekunden beschäftigt, danach wird die WAL-Datei der Datenbank wieder
  verkleinert.
- **Prüfung des Uploads:** höchstens 200 MiB; nur die vier bekannten Dateien; keine Links, Pfade oder
  Gerätedateien; Schutz vor Gzip-Bomben und vor übergroßen oder zu vielen Tar-Köpfen; Prüfsummen. Die
  Datenbank muss genau das erwartete Schema haben (keine fremden Tabellen, Views, Trigger, WITHOUT ROWID,
  COLLATE oder generierten Spalten). Die Kalibrierung wird auf Zahlen und Aufbau geprüft, Ungültiges wird
  verworfen und genannt. Ein Sicherungszeitpunkt mehr als einen Tag in der Zukunft wird abgelehnt;
  Messpunkte nach dem Sicherungszeitpunkt oder in der Zukunft werden nicht übernommen, die Vorschau nennt
  ihre Zahl. Abgelehnte Dateien bekommen eine klare Meldung (HTTP 422), und nichts bleibt
  liegen.

### Intern
- Gemeinsame Bausteine in `ui.js` (`infoButton`, `statCard`, `kvRow`, `rangePicker`, `emptyState`/`errorState`,
  `chartCard`) und Formatierer in `util.js` (`fmtNumber`, `fmtSeconds`, `fmtDuration`, `fmtPpm`, `fmtDate`).
  Musterseite `#/muster` nur mit `?dev=1`.
- Neuer Test `tests/test_gui_bausteine.py`: verbietet `toFixed`, eigene `toLocale*`-Formate, feste
  Nachkommastellen außerhalb von Achsen und Tausenderpunkte vor Einheiten in den Seiten.
- UI-Rundgang mit Playwright unter `tests/ui/` (Konsolenfehler, CSP, Überbreite, Zahlmuster, ⓘ-Tippflächen);
  läuft nur, wenn Playwright vorhanden ist, und gehört nicht zur Unit-Testsuite.
- Neuer Test `tests/test_seiten.py` (Quellenfarben und Kontrast, Kurznamen, ausgeblendete Spalten, Karten auf dem Handy, ✎ nur mit Schreibrecht, Erklärtexte ohne Verlust). Der UI-Rundgang prüft zusätzlich die Clients bei 1440 und 390 px und misst die sichtbaren Wörter je Seite.
- Seiten mit `live = false` (Diagnose, Hardware, Hilfe, Benachrichtigungen, Einstellungen) werden nicht mehr alle paar Sekunden neu aufgebaut, nur weil eine Karte einen leeren Hinweis zeigt.
- Neuer Test `tests/test_einrichtung.py` (Erststart/Update-Erkennung, Rechte, „Überspringen ändert nichts“, Testaufbau ohne Volume und ohne `SYS_TIME`); der UI-Rundgang durchläuft den Assistenten bei 390 und 1440 px.
- Die 5-Minuten-Vorverdichtung des Verlaufs speichert zusätzlich Zähler je Zustand; ältere Zeilen werden beim Lesen abgeleitet. Neue Tests `tests/test_uhr_werkstatt.py` und `tests/test_timeline.py` (Replay eines Tages, Tagesbericht gegen eine unabhängige SQL-Rechnung, Laufzeit mit 30 Tagen Verlauf).
- `test_backup_requires_admin` wartet auf das Aufräumen der Download-Datei: Unter Last las der Test das Verzeichnis, bevor der Server-Thread die Datei gelöscht hatte (sporadischer Fehlschlag, kein Produktfehler).
- Zweite Fehlersuche auf dem neuen Code von 1.6 (acht Bereiche, jeder Fund gegengeprüft): 14 Fehler vor dem Release behoben, u. a. Sicherungen behalten die neuen Verlaufsfelder (Zustandszähler, Pi-Zustand) – ein Wächtertest gleicht künftig alle Verlaufsfelder mit der Sicherung ab –, passende Abhilfe bei Hitze-Drosselung im Assistenten, `?tz=` nimmt alle gültigen IANA-Zonen, kein verlorener Klick in der Speicherleiste, Tastenkürzel ruhen bei offenen Dialogen.


## [1.5.5] – 2026-11-08

Schwerpunkt: Grundreinigung vor 1.6 – das Diagnosepaket kommt auch mit langer Aufzeichnung hinter einem
Reverse Proxy durch, Uhrsprünge stören keine Abläufe mehr, eine strenge Content-Security-Policy, IPv6 für das
Dashboard, Zeiten in der Zeitzone des Servers, bessere Kontraste und Handy-Ansicht. Dazu Projektarbeit für das
öffentliche Repository (Datenschutz-Wächter, Pläne 1.6/1.7).

### Hinzugefügt
- **Datenschutz-Wächter in der CI:** prüft in jedem PR alle Dateien, neue Commits (Autor, Committer,
  Nachricht) sowie Titel und Beschreibung auf private LAN-Adressen außerhalb der Beispielnetze und echte
  Koordinaten; Git-Identität nur noreply. Ein Sicherheitsnetz gegen Versehen, bewusst schlank.
- **Testdaten ohne echte Netze und Anbieter:** Beispielnetze statt eines verbreiteten Heimnetz-Bereichs,
  Adressen großer öffentlicher Anbieter statt realer Server und Zugangs-Präfixe.
- **Pläne für 1.6 und 1.7:** `docs/konzept/version-1.6.md` (rein lokal: Grundreinigung, Pi-Zustand,
  Sicherung, GUI-Erneuerung, Willkommens-Assistent, Uhr-Werkstatt, „Heute“-Zeitleiste; offene Fragen
  entschieden) und `docs/konzept/version-1.7-entwurf.md` (Community-Funktionen). Die ROADMAP folgt
  dieser Staffelung.

### Geändert
- **Diagramme:** Liegt der Live-Wert sichtbar außerhalb von min/max, steht „min/max aus Mittelwerten“ daneben
  (der Verlauf speichert Mittelwerte je Abschnitt, „jetzt“ ist der Rohwert).
- **Zeitquellen:** „Grund“ erscheint nur, wenn er mehr sagt als „Zustand“.
- **Diagnose → Ereignisse:** Rohdaten eines Ereignisses sind eingeklappt.
- **Bedientexte ohne Versionsgeschichte** („Temperaturausgleich ab 1.5“, „Standard ab 1.5.2“ entfernt).
- **Das Dashboard startet immer auf Deutsch**, auch wenn der Browser auf Englisch steht. Englisch heißt
  „English (Beta)“ und gilt nur, wenn du es ausdrücklich wählst (DE/EN oder Einstellungen → Dashboard);
  eine schon gespeicherte Wahl bleibt. Vollständiges Englisch kommt mit 1.7.

### Behoben
- **Kontraste:** Alle Schriftfarben erreichen in beiden Farbschemata mindestens 4,5:1 auf ihren Flächen
  (Hauptknopf dunkel vorher 3,1:1, gedämpfter Text kräftiger, Hinweise und Fehler in kontraststarken
  Statusfarben). Ein Test rechnet die Verhältnisse direkt aus dem Stylesheet nach.
- **Hardware-Check:** Liefert gpsd ein aktives Gerät, steht dort nicht mehr „Kein GPS-Empfänger
  angeschlossen“ – auch bei gpsd auf einem anderen Rechner (`GPSD_HOST`). Gezählt wird nur ein echter
  Gerätepfad; ein entfernter USB-Stick (ttyACM) gilt richtig als „kein PPS möglich“; als eingetragen gilt es
  nur bei „GPS-Gerät: auto“ oder genau diesem Gerät.
- **Zahlen und Zeiten:** Bewertung und Asymmetrie der Quellen, DOP-Werte, Signalstärke und Position stehen
  mit Komma; die GPS-Zeit erscheint als „08.11.26, 12:34:56 UTC“ statt als roher ISO-Text.
- **Handy:** Die Kästchen im Quellen-Editor haben eine sichtbare Beschriftung und laufen nicht über den Rand,
  der Titel oben ist zweizeilig statt abgeschnitten (bei 320 px zeigt die Kopfzeile den Zustand als Punkt),
  IP-Adressen brechen nicht mehr mitten in der Zahl um.
- **ⓘ-Erklärungen** schließen erst ab 40 px Scrollweg, nicht bei jedem Ruckler.
- **Einstellungen:** Auswahllisten werden nicht mehr abgeschnitten („(empfohle…“); die Erklärung steht im ⓘ.
- **Vollbild-Uhr:** „synchron · GPS“ statt „GPS (GPS)“.
- **Barrierefreiheit:** Die acht Abfrage-Kästchen einer Quelle werden als „Letzte acht Abfragen: 7 von 8
  beantwortet“ vorgelesen.
- **Zeiten zeigen die Zeit des Servers.** Uhrzeit in der Kopfzeile, „aktualisiert …“ in der Fußzeile,
  „Letzte Ereignisse“ und das Ereignisprotokoll der Diagnose standen bisher in der Zeitzone des Browsers
  mit dem Zeitzonen-Etikett des Servers daneben. Jetzt folgen sie dem Server, samt Sommer-/Winterzeit des
  jeweiligen Tages (`/api/status` liefert dafür `system.tz_name` und `system.utc_offset`).
- **Verbindung weg:** Oben steht „Keine Verbindung zum Server – Werte veraltet seit hh:mm:ss“. Kommt das Netz
  zurück oder holst du den Tab wieder nach vorn, fragt das Dashboard sofort neu; ein Tab im Hintergrund fragt
  nicht weiter ab.
- **Kein endloses „Lade …“ mehr:** Lässt sich ein Teil einer Seite nicht laden (Clients, Uhrqualität,
  Übersicht), steht dort der Grund und „neuer Versuch läuft“.
- **Clients:**
  - „Gruppen und Netze“ meldet nicht mehr „Noch keine Geräte gesehen“, während die Liste Geräte zeigt.
  - Jedes Gerät hat eine Detailseite, auch wenn es bisher nur chronyd kennt. Kacheln und Gerätepass
    zeigen dann die Werte von chrony statt „0 Anfragen“ bzw. 404.
  - „Anfragen/min“ springt nicht mehr zwischen 6 und 0, Übersicht und Clients zeigen denselben Wert, und
    die Kachel nennt das tatsächliche Mittelungsfenster.
- **Uhrqualität:** Die Zeitraum-Knöpfe stehen in der Karte „Temperatur und Frequenz“, wo sie wirken; ohne
  Temperatursensor erscheinen sie nicht. Kein falsches „es wird weiter gesammelt“ mehr.
- **`WEB_BIND` mit IPv6 (`::`, `[::1]`).** Das Dashboard brach mit „Address family for hostname not
  supported“ ab. Jetzt startet es; `::` nimmt immer IPv4 und IPv6 an (IPV6_V6ONLY wird ausdrücklich
  ausgeschaltet). Scheitert der Start, nennt die Meldung die passende Ursache: Port belegt (`WEB_PORT`),
  Port unter 1024 ohne Berechtigung (CAP_NET_BIND_SERVICE oder höherer `WEB_PORT`) oder Adresse fehlt
  (`WEB_BIND`). Mit `::1` erreicht der Docker-Healthcheck das Dashboard nicht.
- **Einstellungen übernehmen ist jetzt alles oder nichts.** Scheiterte ein späterer Schritt (z. B. die
  PTP-Konfiguration oder eine Prüfung von GPS-, Hotplug- oder NTS-Pfaden), lief chronyd schon mit der
  neuen Datei, während die Meldung „bisherige Einstellungen weiter aktiv“ sagte. Jetzt werden erst alle
  Prüfungen gerechnet, dann beide Dateien geschrieben; bei einem Fehler bleiben beide unverändert und
  nichts wird neu gestartet. Halb geschriebene Tempdateien bleiben nicht liegen.
- **HTTPS-Anleitung:** nennt jetzt die Zeile `proxy_set_header Host $host;` für nginx und eigene Regeln im
  Nginx Proxy Manager – ohne sie lehnt ntp-gui jede Änderung ab („nur aus dem Dashboard heraus“).
- **Aufräumen nur bei plausibler Systemzeit.** Sprang die Uhr weit vor (z. B. Pi ohne RTC oder falscher
  Zeitserver), löschte ntp-gui Ereignisprotokoll und Client-Verlauf nach Alter komplett. Jetzt wird nach
  Alter nur aufgeräumt, wenn chrony nicht „Not synchronised“ meldet und höchstens 1 s abweicht; der
  Inselbetrieb (lokale Referenz) zählt dazu. Sonst siehst du einmal „Aufräumen ausgesetzt: Systemzeit
  unplausibel“. Ein einzelner Eintrag mit Zeitstempel in der Zukunft hält das Aufräumen nicht auf. Den
  chrony-Wert liefert der regelmäßige Statusabruf; das Aufräumen fragt chronyc nicht mehr selbst und
  blockiert keine anderen Schreibvorgänge. Die Größenobergrenzen gelten immer.
- **Uhrsprünge stören keine Abläufe mehr.** Springt die Systemzeit, frieren GPS- und PTP-Anzeige nicht
  mehr ein, der Verlauf wird weiter regelmäßig gespeichert und die Laufzeit des Webservers ist nicht mehr
  negativ oder riesig – diese Abstände laufen auf der monotonen Uhr. Im Container laufen die Fristen für
  Hotplug, NTS-Zertifikat und den Neustart ausgefallener Dienste über `/proc/uptime`; „Nächster Versuch
  in … s“ stimmt dabei weiter.
- **Diagnosepaket mit langer Aufzeichnung scheiterte hinter einem Reverse Proxy.** Vorschau und Paket
  entstanden in einer einzigen Anfrage, die auf dem Pi mit langer Aufzeichnung über eine Minute offen
  blieb – Proxys wie Nginx Proxy Manager brechen nach 60 s ab. Jetzt baut der Server im Hintergrund,
  die Seite fragt alle 2 s nach und zeigt, wie lange es schon läuft; keine Anfrage bleibt länger als
  etwa 10 s offen. „Herunterladen“ ohne Vorschau erstellt zuerst die Vorschau. Für die API gibt es
  dafür `?async=1` und `?job=…`; ohne sie wartet `/api/v1/diagnostics/preview` wie bisher.
- **Download nach der Vorschau baute bei laufender Aufzeichnung alles noch einmal.** Wuchs die
  Aufzeichnung zwischen Vorschau und Download weiter, verwarf der Server das fertige Paket. Jetzt kommt
  mit dem Merker der Vorschau genau das geprüfte Paket – was du angesehen hast, lädst du herunter. Gilt
  der Merker nicht mehr (älter als 10 Minuten, andere Schalter oder geänderte Einstellungen), antwortet
  der Server mit 409 statt minutenlang neu zu bauen; die Seite erstellt dann eine neue Vorschau.
  Höchstens zwei Hintergrund-Bauten gleichzeitig (sonst 429), damit der Pi nicht ausgelastet wird.

### Sicherheit
- **Content-Security-Policy an jeder Antwort** (auch API und Fehlerseiten): nur eigene Skripte, Stylesheets
  und Verbindungen, keine Inline-Skripte, keine Einbettung in fremde Seiten, Bilder zusätzlich als `data:`.
  Im Browser über alle Seiten in beiden Farbschemata ohne Verstoß geprüft. Die Seite „Zugriff abgelehnt“
  erscheint dafür ohne eigene Formatierung.

## [1.5.4] – 2026-11-08

Schwerpunkt: GPS bei schwachem Empfang ruhig – keine Positions-Fehlalarme, weniger Ereignisse, stabile
Fehlerschranke (USB-GPS drinnen ohne PPS). Dazu die Allan-Abweichung auf
der Seite „Uhrqualität“, Reverse Proxy per Klick eintragen und die Restpunkte aus der Abschlussprüfung.

### Behoben
- **Kein Fehlalarm „GNSS-Störung: Position um … m gesprungen“ mehr bei schwachem Empfang.** Für den
  Positionssprung zählen nur noch verlässliche Fixe – 3D, mindestens 5 genutzte Satelliten, HDOP höchstens 4
  (ohne HDOP: eph höchstens 50 m) –, für die Referenz wie für den Vergleich; 2D-Fixe und schlechte
  Geometrie werden ignoriert. Ein Sprung zählt erst, wenn er über mindestens 5 gute Fixe und 50 s anhält.
  Ein echter Spoofer (sauberes Signal, gute Geometrie, bleibender Sprung) wird weiter in unter einer
  Minute erkannt. Ist die Störung schon gemeldet, halten auch schwache Fixe außerhalb der Schwelle sie
  aufrecht – „GNSS wieder unauffällig“ kommt nicht mehr, nur weil ein Spoofer auf schlechte Geometrie
  umschaltet. Meldet gpsd keine Satellitenliste (kein SKY im Abfragefenster, NMEA ohne GSA), gilt die
  Satellitenzahl als unbekannt statt als 0 – sonst wäre die Positionsprüfung still dauerhaft aus. Replay einer realistischen Fix-Folge (4 Tage, Positionsstreuung nach HDOP): vorher rund 40
  Störungen, jetzt keine.
- **Weniger GPS-Ereignisse bei schwachem Empfang.** Gilt der Empfang als schwach (Episode „unstet“ oder
  die 24-h-Bewertung meldet häufige Fix-Wechsel – auch gleich nach einem Neustart), merkt sich ntp-gui das
  24 h lang. So lange gibt es keine Einzelmeldungen „GPS-Fix verloren/wieder da“ mehr, sondern höchstens
  eine Info-Zeile je Stunde: „GPS-Fix 7-mal verloren in der letzten Stunde, zusammen 23 min ohne Fix“
  (flattert es weiter, wächst das Fenster bis 6 h). „GPS-Empfang unstet“ ist nur noch eine Info ohne
  Benachrichtigung. Wird das GPS gebraucht (keine brauchbare Netzquelle, GPS/PPS ausgewählt oder PPS
  eingerichtet), gibt es eine Warnung (mit Benachrichtigung), sobald der Fix 10 min am Stück fehlt – kurzes
  Flattern bleibt still. Das wird bei jedem Messpunkt neu geprüft: Fallen die Netzquellen erst während des
  Ausfalls weg, wird aus der Info eine Warnung. Tragen die Netzquellen die Zeit, steht ein Ausfall erst nach
  einer Stunde am Stück als stille Info im Protokoll – ohne zusätzliche Stundenzeile „1-mal verloren“ dazu. Bei gutem Empfang
  bleibt jeder Fix-Verlust eine Warnung. Replay: vorher rund 100 GPS-Ereignisse in 4 Tagen (über die
  Hälfte „warn“), jetzt rund 20, alle „info“.
- **Hinweis „GPS hat noch keinen Fix“ passt zur Lage.** Gab es vor kurzem noch einen Fix, heißt er „GPS
  gerade ohne Fix – schwacher Empfang, kommt und geht“ und nennt, wann der letzte Fix war. Tragen die
  Netzquellen die Zeit (und ist kein PPS eingerichtet), ist er nur noch eine Info statt einer Warnung.
- **GPS-Fehlerschranke pendelt nicht mehr** (Paket: ± 22 → ± 12 ms nach einer ruhigen Nacht, 15 h später
  wieder ± 22 ms, jedes Mal ein Neustart von chronyd). Kleiner wird sie nur noch, wenn die gemessene
  Streuung höchstens 0,6 × die jetzige Schranke ist und auch die Messung der letzten 48 h (nicht nur 6 h)
  mit Reserve hineinpasst. Größer wird sie wie bisher sofort, höchstens einmal je Stunde.
- **Kalibrierung liest nicht mehr den ganzen Verlauf** (Prüfbefund: Die Karte „GPS kalibrieren“ fragte
  alle 15 s mit window=0 = „gesamter Verlauf“; über 30 Tage SQLite auf einem Pi 14 s und 1,1 GB). Die
  Karte startet mit „letzte 24 h“, statt „gesamter Verlauf“ gibt es „letzte 7 Tage“ (alle 2 min neu
  gemessen). Der Server begrenzt window auf 7 Tage (0 von älteren Dashboards = 7 Tage), lehnt NaN und
  negative Werte mit 400 ab; die automatische Kalibrierung liest ebenso höchstens 7 Tage. Den Verlauf
  liest ntp-gui in 6-h-Abschnitten, jeder für sich unter der Sperre – die Messschleife wartet höchstens
  einen Abschnitt statt der ganzen Abfrage. Messung (30 Tage im 10-s-Takt, 259 000 Punkte, Testrechner):
  vorher 4,8 s, Prozess bis 1,2 GB, Messschleife bis 0,64 s blockiert; jetzt 7 Tage 0,95 s, 24 h 0,11 s, unter 3 ms.
- **Hängende HTTP-Verbindungen halten keinen Thread mehr fest.** Ein Client, der eine Content-Length
  ankündigt und weniger schickt, eine still offene Keep-alive-Verbindung oder einer, der die Köpfe
  tröpfchenweise schickt, blockierte bisher einen Thread für immer. Jetzt schließt ntp-gui eine
  Keep-alive-Verbindung nach 125 s Leerlauf – länger als die Verbindungs-Pools gängiger Reverse Proxys
  (Caddy 2 min, nginx 60 s), sonst gäbe es dort sporadisch 502 –, und Anfragezeile, Köpfe und Body müssen
  ab ihrem ersten Byte in 60 s ankommen. Eine abgeschnittene Anfrage wird nicht ausgeführt; auch eine
  vollständig gelesene, deren Frist genau im selben Moment abläuft, verliert ihre Antwort nicht mehr.
  Antworten gehen in Stücken von 64 KiB hinaus, die Frist gilt je Stück: Ein großes Diagnosepaket oder
  `/api/history` über eine langsame Mobil- oder VPN-Verbindung bricht nicht mehr still ab.
- **Holdover-Test: Frist auf der monotonen Uhr.** Ein Sprung der Wanduhr verlängert oder verkürzt den
  Test nicht mehr. Gespeichert und angezeigt wird die Frist weiter als Uhrzeit; nach einem Neustart
  rechnet ntp-gui die Restzeit einmal daraus um – nie länger als die ganze Testdauer.

### Neu
- **Allan-Abweichung auf der Seite „Uhrqualität“:** Wie stabil ist der Quarz über 10 s … 1 Tag? Gerechnet
  (überlappend) aus der Frequenz, die chrony in jedem Messpunkt für den Quarz meldet – nicht aus dem Offset,
  der nur zeigt, was nach dem Nachregeln übrig bleibt. τ log-gestuft (5 je Dekade) vom Messintervall bis zu
  einem Viertel der Messdauer, je Punkt 68-%-Bereich und Zahl unabhängiger Paare. Log-log-Diagramm mit
  Tooltip und Tabelle, Kacheln für Bestwert, 1 Stunde und 1 Tag mit dem Zeitfehler, den die Uhr frei laufend
  in dieser Zeit etwa sammeln würde (Wert × τ), und eine Einordnung („typisch für einen Pi-Quarz ohne
  Temperaturkontrolle in ruhiger Umgebung“: 1–10 ppb um 1 h). Punkte unter 15 min sind blass – dort zeigt
  die Kurve vor allem chronys Nachführung. Aufwand begrenzt (höchstens 50 000 Rasterpunkte, 20 000 Paare je
  τ; 30 Tage Verlauf ≈ 0,7 s auf einem PC), Ergebnis 10 min zwischengespeichert. Neu: `GET
  /api/clockquality/allan` (auch /api/v1). Das Diagnosepaket enthält die Kurve im Abschnitt Verlauf als reine
  Zahlen (τ, Wert, n). Das Einschwingen der Frequenz nach einem Start von chronyd (neue Installation,
  frisches chrony-data, Neustart für Kalibrierung oder Fehlerschranke) zählt nicht mit: An jedem
  Frequenzsprung über 0,5 ppm, nach jeder Lücke über 10 min und am Anfang des Verlaufs fallen die ersten
  45 min weg – sonst hätte die erste halbe Stunde einer Neuinstallation einen ruhigen Quarz als „üblich“
  eingeordnet (Wert um 1 h rund 200-fach zu hoch). Gerechnet werden höchstens die letzten 30 Tage, auch bei
  größerem `HISTORY_DAYS` (bei 365 Tagen sonst gut 1 GB Speicher). Ist der Verlauf nicht lesbar, sagt die
  Seite das (statt „noch kein Verlauf“), die Einzelheiten stehen nur im Container-Log; das Diagnosepaket
  wartet nicht auf eine laufende Rechnung. Typische Werte aus Stundenmitteln eines USB-GPS-Systems: rund 2 ppb
  über 1 h, 5 ppb über 6 h.
- **Reverse Proxy per Klick eintragen** (bisher zeigte der Hinweis zwar die Adresse des Proxys, das
  richtige Eintragen blieb trotzdem mühsam). Die Hinweise „Reverse Proxy erkannt, aber nicht
  eingetragen“ und „Dashboard über unverschlüsseltes HTTP mit Anmeldung“ (Ursache: Proxy nicht
  eingetragen) nennen die Adresse und bieten „Als vertrauenswürdigen Proxy eintragen (…/32 bzw. /128)“
  an – mit Rückfrage, was das heißt. Eingetragen wird genau die Adresse, die ntp-gui selbst als
  Gegenstelle gesehen hat, nie ein Netz; der Knopf schickt nur eine Kennung, die Adresse nimmt der Server
  aus seiner eigenen Liste. Nur mit Admin-Recht (Passwort oder Admin-Schlüssel), mit demselben
  CSRF-Schutz wie jede Einstellung; API-Schlüssel mit Leserecht sehen den Knopf nicht – und ihre Anfragen
  schlagen auch keine Adresse dafür vor, ein Gerät mit Lese-Schlüssel kann sich also nicht selbst als
  Proxy anbieten. Der am längsten gesehene Proxy steht zuerst, ein Neuling verdrängt ihn nicht. Ist die
  Adresse das Gateway des Container-Netzes (rootless Docker/Podman, userland-proxy, manche NAS – dann
  kommen dort womöglich alle Zugriffe an), warnen Hinweis und Rückfrage davor. Danach beginnt die
  HTTPS-Prüfung neu. API: `POST /api/v1/web/proxies/trust`.
- **Warnung bei zu breiten Proxy-Einträgen:** Ein Eintrag in „Vertrauenswürdige Proxys“ breiter als /24
  (IPv4) bzw. /64 (IPv6) wird gespeichert, aber beim Speichern und mit einem Hinweis in der Übersicht
  gewarnt – jedes Gerät darin dürfte sonst eine falsche Browser-Adresse und „HTTPS“ vorgeben.
- **„GPS gesperrt, Uhr läuft frei“:** Bleibt das GPS gesperrt und gibt es 6 h lang keine andere
  auswählbare Zeitquelle, meldet ntp-gui das einmal je Sperre als Störung (mit Benachrichtigung). Ein
  laufender Holdover-Test zählt nicht mit. Die GNSS-Seite zeigt „Andere Quellen: keine“ bei der Sperre.
- Hilfe: „GPS gesperrt, Uhr läuft frei“ und „Empfänger umgezogen → Position neu lernen“ an der
  GNSS-Karte; „Vertrauenswürdige Proxys“ erklärt das Eintragen per Klick und die /24-/64-Warnung.

### Projekt
- **Sicherheitslücken vertraulich melden:** `SECURITY.md` beschreibt den Weg über GitHub Private
  Vulnerability Reporting; das Issue-Formular verweist darauf. `.github/CODEOWNERS` legt den
  Standard-Prüfer fest.
- **Release: Herkunftsnachweis scheiterte im öffentlichen Repository** („No credentials found for
  registry ghcr.io“). Der Job „Herkunftsnachweis“ meldet sich jetzt selbst an der Registry an, bevor
  er den Nachweis dort ablegt. Im privaten Repository war der Job bisher immer übersprungen worden.
- **Release: SBOM-Werkzeuge mit drei Versuchen.** Der Download von syft scheiterte zweimal
  nacheinander mit HTTP 504; syft und Grype werden jetzt bis zu dreimal mit Wartezeit geholt.

## [1.5.3] – 2026-11-04

Schwerpunkt: Ein Holdover-Test läuft bis zum Ende – keine Automatik startet chronyd mehr dazwischen.

### Behoben
- **Holdover-Test wird von Automatiken nicht mehr abgebrochen** (bisher brach z. B. ein 6-h-Test ohne GPS und
  Netzquellen nach einigen Stunden ab, weil die automatische Anpassung der GPS-Fehlerschranke
  chronyd neu startete). Solange ein Test läuft, stellen die Fehlerschranke (gpsquality) und die
  automatische Kalibrierung (Offset) ihre Änderung zurück; der Supervisor wartet ebenso mit dem Neustart
  nach einem Gerätewechsel (Hotplug) und nach einem erneuerten NTS-Zertifikat. Im Protokoll steht je
  Automatik ein Ereignis „… – zurückgestellt bis zum Ende des Holdover-Tests“, die Seite Uhrqualität
  zeigt es beim laufenden Test. Nach dem Ende (fertig, Grenze oder Abbruch) holt ntp-gui die Änderung im
  nächsten Durchgang nach, nicht erst eine Stunde später. Die Sperre für den Supervisor
  (`RUN_DIR/reload.hold`) verlängert das Dashboard alle 10 s; stirbt es, läuft sie nach 2 min ab.
- **Keine Warnung mehr durch den eigenen Test:** „Keine Zeitquelle mehr ausgewählt“, Quellenwechsel,
  „Schleife beendet – die Quelle antwortet derzeit nicht“ und „GPS-Sperre ausgelassen: keine andere
  Zeitquelle“ während eines Holdover-Tests und bis 15 min danach stehen als „info“ mit dem Vermerk
  „(Holdover-Test)“ im Protokoll und gehen nicht als Benachrichtigung hinaus. Eine erkannte Schleife,
  ein verlorener GPS-Fix oder ein nicht erreichbarer chronyd bleiben echte Warnungen. Beim Test nur ohne
  GPS gilt das nur für Wechsel von oder zu GPS/PPS: Fallen dabei die Netzquellen aus, bleibt „Keine
  Zeitquelle mehr ausgewählt“ eine Warnung mit Benachrichtigung. „GPS-Sperre ausgelassen“ ist nur während
  des Tests ein Vermerk und kommt danach erneut, wenn die Lage bleibt.
- **Teststart und Neustart treffen sich nicht mehr:** Ist gerade ein Neustart der Zeitdienste angefordert
  oder läuft er, lehnt der Start des Tests mit „in ein paar Sekunden“ ab, statt nach wenigen Sekunden
  als „abgebrochen (chronyd neu gestartet)“ zu enden. Hat eine Automatik gerade gespeichert, als der Test
  begann, folgt ihr Neustart nach dem Ende. Ein neuer Test startet erst kurz nach dem letzten, damit
  Zurückgestelltes nicht immer weiter verschoben wird.
- **Frist auch bei hängendem chronyd:** Antwortet chronyd zum Ende nicht, endet der Test trotzdem; die
  Sperre für Automatiken reicht nie länger als 2 min über das geplante Ende hinaus.
- **Erneuertes NTS-Zertifikat:** Das Zurückstellen steht als Warnung im Protokoll (bis zum Ende bietet
  chronyd das bisherige an – Test abbrechen, wenn das neue sofort gelten soll). Ein Neustart von Hand
  lädt es mit; kein zweiter Neustart danach. Ein zurückgestellter Gerätewechsel verzögert die Warnung
  „GPS-Gerät verschwunden“ nicht mehr.

### Geändert
- **Einstellungen während eines Holdover-Tests:** Was du selbst speicherst, startet die Zeitdienste weiter
  sofort neu und bricht den Test damit ab – die Einstellungsseite fragt vorher nach (Speichern,
  Zurücksetzen eines Felds, Import), und die Speicherleiste sagt es dazu. Ebenso die Knöpfe „Offset
  übernehmen“, „Zurücknehmen“ (Kalibrierung) und „Fehlerschranke zurücksetzen“.
- Das Ende-Ereignis sagt „Zurückgestellt, wird jetzt erneut geprüft: …“ – die Automatik entscheidet auf
  frischen Messwerten, ob die Änderung noch nötig ist.

## [1.5.2] – 2026-11-04

Schwerpunkt: Die GPS-Automatik läuft ab Werk und ohne Zutun – messen, einmal korrigieren,
nur kleinen Drifts folgen.

### Achtung beim Update
- **Die GPS-Kalibrierung läuft jetzt automatisch** (`GPS_AUTOCAL=auto` ist der neue Standard, Entscheidung
  E19). Das betrifft alle mit GPS, die den Modus nie selbst eingestellt haben – also den alten Standard
  „vorschlagen“ hatten. Wer „vorschlagen“ oder „aus“ ausdrücklich gespeichert hat oder `GPS_AUTOCAL` in der
  Compose-Datei setzt, behält das. Nach dem Update misst ntp-gui (die Messung der letzten Stunden zählt mit)
  und stellt den Offset selbst nach; jede Änderung steht im Ereignisprotokoll und lässt sich auf der
  GPS-Seite zurücknehmen. Zurück zum Klick: Einstellungen → GPS → „Automatische Kalibrierung“ auf
  „vorschlagen“ oder `GPS_AUTOCAL=suggest`.

### Geändert
- **GPS-Automatik ohne Zutun:** „Automatisch“ ist Standard; Hinweise und Hilfetexte sagen nicht mehr
  „Offset kalibrieren“, wo die Automatik das ohnehin tut („GPS widerspricht den anderen Quellen“ ist im
  Modus „automatisch“ nur noch ein Info-Hinweis). Ein anderer Empfänger in den Einstellungen (Gerät, Name,
  PPS) startet die Messung von selbst neu, ebenso „Neu lernen“ bei den GNSS-Störungen – Störungsmeldungen
  davor zählen dann nicht mehr; in einem Schritt korrigiert die Automatik danach erst nach einer ganzen
  24-h-Messung ohne Störung (ein Spoofer, den man für einen Antennenwechsel hält, wird so nicht nach 6 h
  eingerechnet). Bei einer GNSS-Störung sagt die GPS-Seite genau, was zu tun ist.
- **Ein Neustart von chronyd weniger:** Steht die Korrektur eines deutlichen Versatzes an, verkleinert
  ntp-gui die Fehlerschranke nicht vorher noch einmal – sie kommt im selben Neustart mit dem neuen Offset.
- **Nach „Rückgängig“ nie mehr eine Korrektur in einem Zug:** 24 h Pause, danach nur kleine Schritte –
  bis du den Offset von Hand änderst, einen anderen Empfänger einstellst oder „Neu lernen“ drückst. Vorher
  konnte die Automatik eine zurückgenommene Änderung nach 6 h (bzw. jeden Tag aufs Neue) ganz wiederholen.
  „Rückgängig“ setzt ohne PPS auch die mit der Korrektur gesetzte Fehlerschranke auf den vorsichtigen
  Standard zurück, im selben Neustart von chronyd; die Meldung sagt, dass „vorschlagen“ die Automatik stoppt.
- **Korrektur in einem Schritt auch ohne NTS:** Mit den Standardquellen (`pool.ntp.org`) oder PTB über
  reines NTP gab es sie nie – der Offset kroch 10–24 Tage lang mit rund zwei Neustarts von chronyd pro Tag.
  Jetzt reichen auch drei genutzte Netzquellen ohne NTS, gemessen über 12 h. `docker-compose.gps.yml` nennt
  dafür drei PTB-Server statt zwei. Fehlen die Quellen nur kurz (wackelige NTS-Verbindung), wartet die
  Automatik bis zu 24 h, statt vorher einen 5-ms-Teilschritt (mit Neustart) zu machen.
- **Fehlerschranke im selben Neustart:** Ohne PPS schreibt jeder automatische Schritt die Schranke mit (nach
  einem Teilschritt samt dem Rest des Versatzes) – kein eigener Neustart „Fehlerschranke“ mehr kurz danach.
- **PPS mit später NMEA-Zeile:** Liegt die NMEA-Zeile (z. B. 120 ms) neben dem Netz, während chrony das PPS
  nutzt, ist ihr Falseticker nur ein Hinweis – vorher eine „Störung“ mit Benachrichtigung, die die Automatik
  dauerhaft sperrte, sodass sie den Versatz nie beheben konnte.
- „GPS widerspricht den anderen Quellen“ ist im Modus „automatisch“ nur dann ein Info-Hinweis, wenn die
  Automatik gerade misst oder korrigiert – nicht bei einer Sperre wegen GNSS-Störung, bei „bitte prüfen“
  oder mit `WEB_READONLY`.
- Der Update-Hinweis nennt einen selbst gesetzten Offset (`GPS_OFFSET` ≠ 0 in der Compose-Datei oder ein
  gespeicherter Wert): Die Automatik verstellt ihn, ein GUI-Wert hat Vorrang vor `GPS_OFFSET`; wer ihn bewusst
  gewählt hat, stellt auf „vorschlagen“.
- „Erlaubte Namen“ steht in Einstellungen → Dashboard jetzt direkt sichtbar und nicht mehr erst
  hinter „Erweitert“ – neben „Vertrauenswürdige Proxys“ war es sonst kaum zu finden.

## [1.5.1] – 2026-11-03

Schwerpunkt: GPS-Automatik einfach, vorhersehbar und sichtbar (messen → einmal korrigieren →
kleinen Drifts folgen), kein GNSS-Fehlalarm nach einer Offset-Änderung, ein HTTPS-Hinweis, der
Ursache und Absender nennt, und der neue Image-Name `ghcr.io/mgc20/ntp-gui`.

### Achtung beim Update
- **Neues Repository und neuer Image-Name:** ntp-gui liegt jetzt unter
  [github.com/mgc20/ntp-gui](https://github.com/mgc20/ntp-gui), das Image unter
  `ghcr.io/mgc20/ntp-gui`. In deiner Compose-Datei `image: ghcr.io/congp20/ntp-gui:latest` durch
  `image: ghcr.io/mgc20/ntp-gui:latest` ersetzen – unter dem alten Namen kommen keine neuen
  Versionen mehr. Der Update-Hinweis von 1.5.0 und älter fragt noch das alte Repository und
  meldet deshalb nichts mehr; ab 1.5.1 fragt er das neue.
- **„latest“ zeigte im neuen Repository auf 1.2.0:** Beim Umzug wurden alle alten Versions-Tags
  neu hochgeladen; der CI-Workflow baute daraufhin jede alte Version und setzte jedes Mal
  „latest“ – gewonnen hat, wer zuletzt fertig war. CI veröffentlicht jetzt nie mehr, nur der
  Release-Workflow setzt „latest“ (geprüft, auf denselben Digest wie die Version).

### Behoben
- **HTTPS-Hinweis nennt Ursache und Absender:** „Dashboard über unverschlüsseltes HTTP mit Anmeldung“
  sagt jetzt, wer ungeschützt kam und warum – Adresse, Passwort/API-Schlüssel und „zuletzt vor 3 h“,
  je Absender (bis zu drei, neueste zuerst): „direkt per HTTP“ (Lesezeichen auf http://…:8080,
  Home-Assistant-Integration, Homepage-/Uptime-Kuma-Widget, Skript), „über den eingetragenen Proxy,
  aber der Browser sprach mit ihm nur HTTP“ oder „über eine Gegenstelle mit Proxy-Köpfen, die nicht
  in TRUSTED_PROXIES steht“. Der Text sagt auch, wann er verschwindet (1 Stunde nach dem letzten
  ungeschützten Zugriff, wenn danach nur geschützte kommen, sonst nach 24 Stunden).
- **Eingetragener Proxy ohne Proto-Kopf ist kein Klartext-Alarm mehr:** Schickt ein Proxy aus
  TRUSTED_PROXIES nur X-Forwarded-For, nur X-Real-IP oder „Forwarded“ ohne proto=, ist unbekannt,
  ob der Browser HTTPS sprach. Dafür gibt es den eigenen Info-Hinweis „Eingetragener Proxy meldet
  nicht, ob HTTPS benutzt wurde“ – mit den Köpfen, die der Proxy tatsächlich schickt, einem
  unbekannten Proto-Wert (z. B. „wss“) beim Namen und Anleitung für Caddy, Nginx Proxy Manager,
  Traefik, Zoraxy, HAProxy und Apache – statt „direkt per HTTP“ mit dem Rat, nach einem Lesezeichen
  zu suchen. Kommt eine Anmeldung vom eingetragenen Proxy ganz ohne Proxy-Köpfe, steht das dabei.
  X-Forwarded-For plus „Forwarded: proto=https“ (HAProxy) wird erkannt. Der Hinweis gilt je Proxy:
  Er verschwindet nur dann schon nach 1 Stunde, wenn derselbe Proxy danach den Kopf schickt.
  Speichern von TRUSTED_PROXIES setzt alle HTTPS-Hinweise weiter sofort zurück.
- **Proxy auf anderem Gerät ohne Proto-Kopf:** Die Strecke Proxy → ntp-gui ist dann sicher
  unverschlüsselt – dafür erscheint jetzt auch „Strecke Proxy → ntp-gui ist unverschlüsselt“, und
  der Satz „kein Hinweis auf Klartext“ steht nur noch, wenn der Proxy auf demselben Rechner läuft.
- **Apache-Anleitung sicher:** `RequestHeader set X-Forwarded-Proto "expr=%{REQUEST_SCHEME}"` nur im
  HTTPS-vHost statt pauschal „https“, das eine echte Klartext-Warnung verschwinden ließ.
- **Weniger Log-Rauschen:** Netzabbrüche einzelner Verbindungen („No route to host“, „Network is
  unreachable“, Zeitüberschreitung u. ä.) schreiben keinen Traceback mehr ins Log; andere Fehler
  weiterhin vollständig.
- **Kein GNSS-Fehlalarm mehr nach einer Offset-Änderung:** Liegt das GPS seit dem Start bzw. seit einer
  Änderung der GPS-Einstellungen gleichbleibend neben dem Netz (z. B. nach „Offset zurücksetzen“
  dauerhaft rund +51 ms) und hält chrony es deshalb für einen Falseticker, ist das vermutlich ein
  Kalibrierfehler: Es bleibt beim „Hinweis“ mit dem Rat „Offset kalibrieren“ – ohne Benachrichtigung,
  ohne Sperre, auch bei einem kleinen NMEA-Laufzeitsprung (10–15 ms). Wandert die GPS-Zeit um
  mindestens die Zeitschwelle (≥ 20 ms) von diesem Abstand weg oder liegt sie mehr als 1 s daneben,
  wird es wieder „Störung“. Die Ausnahme gilt nur ohne PPS und nur, solange das GPS seit Start bzw.
  Änderung noch nie 15 Minuten brauchbar war. Ein Neustart von ntp-gui setzt nur eine Ausnahme fort,
  die vorher schon galt (sie steht mit dem Zeitanker in SQLite) – er macht aus einer erkannten
  Störung nie einen „Kalibrierfehler“. Nach einer „Störung“ gibt es bis zur nächsten Änderung der
  GPS-Einstellungen keine Ausnahme mehr.
  Der Hinweistext sagt nur noch „vermutlich ein Kalibrierfehler“ (und nur mit NTS-Vergleich) und
  rät, danach Antenne und Umgebung zu prüfen.
- **Langsam ziehender Spoofer wird wieder erkannt:** War das GPS brauchbar und wird es ohne
  Einstellungsänderung zum Falseticker, gilt wie in 1.5.0 „Störung“ nach 5 Minuten mit ≥ 2
  NTS-Quellen. Zieht ein Spoofer so langsam (wenige ms je Stunde), dass die mitwachsende
  Fehlerschranke chrony nie „x“ melden lässt, fällt er trotzdem auf: Der Zeitanker der
  Störungserkennung darf höchstens 30 ms von seinem Startwert (Start bzw. letzte Änderung der
  GPS-Einstellungen) wegwandern, danach wird es „Störung“ – spätestens bei rund 50 ms statt (bisher
  unentdeckt) bis 500 ms.
- **Automatische Kalibrierung rechnet keine GNSS-Störung ein:** Meldet die Störungserkennung gerade
  „Warnung“, „Störung“ oder unnatürlich gleichmäßige Signale, hält die GPS-Sperre oder gab es im
  Messzeitraum „Warnung“ oder „Störung“, wird der Offset nicht automatisch geändert. Die GPS-Seite
  zeigt dann „gesperrt wegen GNSS-Störung – erst Antenne/Umgebung prüfen“ statt eines Datums und
  lädt nicht zum Übernehmen ein; „Vorschlag übernehmen“ fragt in dieser Lage nach. Der Schritt in
  einem Zug setzt zusätzlich voraus, dass der Messzeitraum keinen Sprung enthält.
- **Fehlerschranke ohne PPS wächst nicht mehr stündlich:** Ändert sich `gps_offset` (von Hand,
  Zurücksetzen oder automatische Kalibrierung), zählen für die Schranke nur Messpunkte ab der
  Änderung (plus 15 Minuten für den Neustart von chronyd) – bisher maß sie den alten Versatz mit und
  wuchs stündlich (± 10 → 80 ms). Kleiner werden darf sie nach 5,5 Stunden Messung statt erst nach
  12 Stunden, nicht schon nach 2 Stunden (sonst hätte jeder kleine Kalibrierschritt die Sperre
  umgangen). Jede neue Schranke bekommt 25 % Reserve auf den Messwert; bisher startete schon 1 ms
  mehr Streuung chronyd erneut neu (± 64 → ± 80 ms eine Stunde später).
- **GPS ohne PPS rückt nicht vor die NTS-Quellen:** Die Fehlerschranke wird nie enger als das
  1,5-Fache der Root Distance der besten genutzten NTS-Quelle – sonst wählte chrony das NMEA-GPS
  und stellte die Uhr danach.
- **Offset-Änderung von Hand sofort erkannt:** Die automatische Kalibrierung nimmt den genauen
  Zeitpunkt aus der Messschleife – die GPS-Seite nannte vorher bei jedem Aufruf einen anderen
  Messbeginn und ein wanderndes Datum. Nach einer Änderung von Hand gilt die Pendel-Sperre
  (doppelte Schwelle für die Gegenrichtung) nicht mehr, die Korrektur in einem Schritt also schon.
  Der Kalibrier-Assistent mischt keine Werte vor und nach einer Offset-Änderung mehr – der Vorschlag
  beruht nur auf Messungen zum eingestellten Offset.
- **Kalibrierung hat auch Daten, solange chrony das GPS als Falseticker verwirft:** Messwerte mit
  „x“ zählen für den Offset, wenn mindestens zwei genutzte Netzquellen dagegenstehen. Vorschlag und
  schnelle Korrektur kommen so nach etwa 6 Stunden, ohne dass erst die Fehlerschranke stündlich
  über den Versatz wachsen muss.
- **Vollbild-Uhr über jeden Namen:** Mit „Vollbild-Uhr ohne Anmeldung“ (`clock_public`) bekamen
  `/clock` und `/api/v1/time` über einen eigenen DNS-Namen (z. B. `uhr.example.com`) ohne Passwort
  „Zugriff über den Namen … abgelehnt“ (403), obwohl die Uhr öffentlich sein sollte. Jetzt antworten
  `/clock`, ihre vier statischen Dateien und `/api/v1/time` dann über jeden Host-Namen ohne
  Namensprüfung – der Inhalt ist bewusst öffentlich (Uhrzeit, Ampel, Genauigkeit, Art der Quelle).
  Den Namen der Quelle gibt es ohne Anmeldung nur über einen erlaubten Namen; über einen fremden
  Namen kommt immer die öffentliche Antwort ohne Namen, Adressen oder Position. Alle anderen
  Seiten und die übrige API bleiben gegen DNS-Rebinding geprüft. Ablehnungstext, Hilfe und README
  sagen das.

### Geändert
- **Diagnosepaket enthält die aktiven Hinweise:** Neue Datei `hints.json` mit den Hinweisen, die das
  Dashboard gerade zeigt (Schlüssel, Stufe, Titel, Text) – so ist im Fehlerbericht zu sehen, ob z. B.
  „Dashboard über unverschlüsseltes HTTP“ erscheint. Wie alles im Paket läuft sie durch den
  Datenschutzfilter: Absender-Adressen in den Texten werden zu `client-NN` bzw. `<öffentliche-IP>`,
  Positionen werden entfernt.
- **Automatische Kalibrierung: einfacher Ablauf – messen → einmal korrigieren → kleinen Drifts
  folgen.** Ist das GPS die Rückfallebene (ohne PPS, Fehlerschranke „gemessen“, Rolle nicht
  „bevorzugen“) und liegt es deutlich daneben (≥ 10 ms und ≥ 3 × Schwelle, gemessen über ≥ 6 h,
  ≥ 2 genutzte NTS-Quellen), korrigiert sie den ganzen Versatz in einem Schritt statt 5 ms je 24 h –
  und schreibt die passende Fehlerschranke im selben Neustart von chronyd mit (nach „Offset
  zurücksetzen“ zwei statt vier Neustarts). Mit PPS bleibt es bei kleinen Schritten. Kleinen Drifts
  folgt sie nur nach einer ganzen 24-h-Messung: Tagesschwankungen der Netzlaufzeit ließen den Offset
  sonst hin- und herpendeln (+2,7 ms, einen Tag später −2,8 ms).
- **GPS-Seite zeigt die Phase der automatischen Kalibrierung** – „misst (2,1 von 6 h)“, „korrigiert
  bei nächster Prüfung (≈ 14:05)“, „kalibriert – folgt nur kleinen Drifts“ oder „gesperrt wegen
  GNSS-Störung“ – samt nächstem Schritt. Steht nichts an, nennt sie auch kein Datum (bisher
  „nächste mögliche Änderung: jetzt“, bei jedem Aufruf eine Stunde später). Nach einer
  Offset-Änderung von Hand bietet sie „Vorschlag übernehmen“ direkt im Hinweis an. Die Texte
  (Einstellung, Hilfe, README) beschreiben den neuen Ablauf; der GNSS-Hinweis „vermutlich ein
  Kalibrierfehler“ sagt im Modus „automatisch“, dass sie das selbst korrigiert.
- **Klarere Ereignistitel bei unstetem Empfang:** „GPS-Fix seit 10 min weg (vorher 50 Fix-Wechsel in
  2 h 31 min)“ und „GPS-Empfang wieder stetig – seit 1 h kein Fix-Wechsel (vorher …)“. Die Felder im
  Ereignis bleiben, neu ist `outcome` („ruhig“ oder „fix_weg“).
- **Erlaubte Namen im Dashboard:** Einstellungen → Dashboard → Erweitert → **Erlaubte Namen** –
  Namen, über die das Dashboard ohne Passwort antworten darf (Schutz vor DNS-Rebinding, in der
  Hilfe in einfachen Worten erklärt). Gilt zusätzlich zu `WEB_ALLOWED_HOSTS`; Namen aus der
  Umgebung stehen unter dem Feld (nur lesend). Streng geprüft: Namen mit Punkt oder `*.domain`,
  keine IP-Adressen, Ports, ganzen Endungen (`*.com`, `*.co.uk`), keine Wildcards auf DynDNS- und
  Hosting-Domains (`*.duckdns.org`, `*.myfritz.net`, `*.github.io` – dort nur den eigenen Namen wie
  `meinzeit.duckdns.org`), keine Namen, die auf Ziffern enden (`1.2.3`), und nicht `*` allein – den
  Schutz ganz abschalten geht nur per `WEB_ALLOWED_HOSTS=*`. Steht so eine Wildcard in
  `WEB_ALLOWED_HOSTS`, warnt das Log beim Start. Wirkt ohne Neustart, nur mit Admin-Recht und
  CSRF-Schutz wie jede Einstellung, Teil von Sichern/Wiederherstellen. Die Prüfung je Anfrage
  bleibt ein reiner Textvergleich ohne DNS.
- **Compose-Vorlagen ohne Caddy:** Der auskommentierte Caddy-Dienst, das Volume `caddy-data` und
  die Kommentare „[OPTION HTTPS mit Caddy]“ sind aus `docker-compose.all-in-one.yml` entfernt. Das
  Caddy-Beispiel steht jetzt nur noch in `docs/integrationen/https.md` – als eigenständige
  Compose-Datei für einen eigenen Stack neben ntp-gui. In der Vorlage bleibt
  „[OPTION Reverse Proxy auf diesem Rechner]“ mit `WEB_BIND` und `TRUSTED_PROXIES`. Hinweise im
  Dashboard, Hilfe und README verweisen auf die Anleitung. Wer Caddy aus der alten Vorlage
  betreibt, muss nichts ändern.
- **Versionshinweis in jeder Compose-Vorlage:** Über `image: ghcr.io/mgc20/ntp-gui:latest` steht,
  wie man die Version festhält (`:1.5` bleibt auf 1.5.x, `:1.5.1` fest) und dass das Image von
  `ghcr.io/congp20/ntp-gui` umgezogen ist (dort keine neuen Versionen mehr). In den Vorlagen mit
  `build: .` steht dazu, dass der Tag nur fürs geladene Image gilt – `up --build` baut den lokalen
  Stand.

## [1.5.0] – 2026-11-02

Schwerpunkt: GPS ohne PPS als ehrliche Rückfallebene, Schleifen durch DNS-Umschreibung und
NAT-Umleitung erkennen, GNSS-Störungen samt GPS-Sperre und Holdover-Test, Clients 3, HTTPS per
Reverse Proxy und ein Gerüst für Englisch.

### Achtung beim Update
- **GPS ohne PPS (z. B. VK-162):** Ein früher gespeicherter, zu kleiner Delay (z. B. 0,03 s)
  gilt nicht mehr. ntp-gui misst jetzt die Streuung des GPS gegen deine Netzquellen und gibt
  chrony daraus die Fehlerschranke; bis zur ersten Messung (nach etwa 6 Stunden Daten) gilt
  vorsichtig ± 100 ms. Genau der zu kleine Delay ließ chrony das GPS bisher guten NTS-Quellen
  vorziehen. Wer die alten Werte behalten will, stellt „Fehlerschranke ohne PPS“ auf „von Hand“
  (`GPS_BOUND_MODE=manual`).
- **Benachrichtigungen über ein Gerät nennen jetzt den Namen, den du ihm gegeben hast**
  („Uhr von NAS Keller weicht um +1,2 s ab“), ohne Namen „Gerät ohne Namen“. Bisher stand dort
  immer eine Pseudo-Adresse. Die LAN-Adresse kommt nur mit der neuen Einstellung „LAN-Adressen
  in Nachrichten“ (`NOTIFY_LAN_ADDRESSES`, Standard aus) dazu; öffentliche Adressen und
  MAC-Adressen gehen nie hinaus.
- **Zwei neue Hintergrundabfragen, beide nur an Server, die du selbst eingetragen hast:** Der
  DNS-Gesundheitscheck fragt deine eigenen DNS-Server alle 15 Minuten einmal an (nur in den
  Modi „eigene Server“, DoT und DoH). Die Schleifenerkennung schickt höchstens alle 5 Minuten je
  Adresse eine eigene NTP-Anfrage an eine eingetragene Zeitquelle. Fremde Dienste werden dabei
  nicht kontaktiert.

### Hinzugefügt

#### GPS ohne PPS und schwacher Empfang (Entscheidung E16)
- **GPS ohne PPS ist die Rückfallebene mit ehrlicher Fehlerschranke:** ntp-gui misst über die
  letzten 6 Stunden, wie stark das GPS gegenüber deinen Netzquellen streut (95-%-Wert, mindestens
  |Median| + 3 × robuste Streuung), und schreibt daraus `delay`/`precision` in chrony.conf. So
  nimmt chrony gute Internetquellen und springt von selbst auf das GPS um, wenn das Internet
  schlecht wird oder ausfällt (Mobilfunk, Störung, Insel).
  - Die Schranke wächst, sobald die Streuung sie übersteigt (höchstens stündlich, mit Reserve),
    und schrumpft nur deutlich und frühestens nach 12 Stunden – auch nach „Auf Standard
    zurücksetzen“. Jede Anpassung steht im Ereignisprotokoll und startet chronyd kurz neu.
  - Gezählt werden auch GPS-Werte, die chrony als Falschgeber („x“) oder zu unruhig („~“)
    verworfen hat; hat chrony das GPS gewählt, vergleicht ntp-gui mit den übrigen erreichbaren
    Netzquellen. So kann die Schranke sich nicht selbst kleinrechnen oder einfrieren.
  - Ein eingestelltes, aber fehlendes PPS-Gerät zählt als „ohne PPS“.
  - Zurücksetzen auf der GPS-Seite, abschalten mit „Fehlerschranke ohne PPS: von Hand“.
- **Rolle des GPS** auf der GPS-Seite, im Hardware-Check und neu in der Übersicht:
  „Rückfallebene“, „Referenz“ (mit PPS oder bei „bevorzugen“) oder „nur beobachten“ (nur als
  deine bewusste Wahl, nie Standard). Dazu, ob chrony das GPS gerade nutzt, und Warnungen bei
  einer zu kleinen Schranke von Hand oder bei „Mindestzahl Quellen“ über 1.
- **Empfangsbewertung über 24 Stunden:** Fix-Anteil, Fix-Wechsel je Stunde, Signalstärke der
  vier stärksten Satelliten und genutzte Satelliten als Ampel mit einem Satz und dem Grund je
  Kennzahl, z. B. „Fix 92 % der Zeit, 9,6 Wechsel/h – Empfang zu schwach für eine stabile
  Zeitquelle“. Die Ampel steht auch in der GPS-Kachel der Übersicht.
- **Fix-Flattern wird zusammengefasst:** Kommt und geht der Fix mindestens sechsmal in
  30 Minuten, gibt es **ein** Ereignis „GPS-Empfang unstet“ mit Zählung statt Dutzender
  „verloren/wieder da“. Nach einer Stunde Ruhe folgt ein Abschlussereignis; bleibt der Fix
  10 Minuten am Stück weg, kommt „GPS-Fix verloren“ sofort. „Fix gerade: stetig“ nennt die Zahl
  der Fix-Wechsel der letzten halben Stunde.
- **Antennen-Test:** „5 Minuten messen“, Empfänger umstellen, erneut messen, nebeneinander
  vergleichen. Die Messung bleibt lokal – ohne Satellitenwinkel, ohne Position und nicht im
  Diagnosepaket.
- **Kalibrier-Assistent:** schlägt nie einen Delay vor, der kleiner ist als die gemessene
  Streuung (95-%-Quantil statt mittlerer Streuung). Im Modus „gemessen“ zeigt er den Delay, den
  chrony wirklich nutzt, „Vorschlag übernehmen“ setzt dann nur Offset und Rolle, und die
  automatische Kalibrierung ändert nur noch den Offset.
- **Praxistipps in ⓘ:** USB-Verlängerung ans Fenster, USB 3 stört das GPS-Band (1,5 GHz),
  Wärmeschutzglas dämpft stark.

#### Schleifen erkennen (DNS-Umschreibung, NAT-Umleitung)
- ntp-gui prüft laufend jede eigene Zeitquelle darauf, ob chronyd über sie sich selbst fragt –
  anhand der eigenen Adresse, einer Antwort mit eigener Referenz-ID, eigenem Stratum und eigener
  Referenzzeit und einer kurzen Gegenprobe beim eigenen chronyd (127.0.0.1 und eigene
  LAN-Adresse, sonst Vergleich mit `chronyc tracking`). Ergebnis ist ein kritisches Ereignis
  „pool.ntp.org zeigt auf dich selbst – vermutlich DNS-Umschreibung ohne Ausnahme für ntp-gui“
  bzw. „… NAT-Umleitung ohne Ausnahme für ntp-gui“, spätestens nach zwei Poll-Intervallen, dazu
  ein Hinweis in der Übersicht. Titel nennen keine LAN-Adressen.
  - Ist der Fehler behoben, folgt „Schleife behoben … erreicht wieder einen fremden Server“ – nur,
    wenn wirklich ein fremder Server geantwortet hat; sonst „Schleife bei … beendet – die Quelle
    antwortet derzeit nicht“.
  - Eine passive Übereinstimmung allein reicht bei öffentlichen Adressen nicht (kein Fehlalarm bei
    Pool-Servern, die an derselben Quelle hängen). Gegenprobe höchstens alle 5 min je Adresse.
  - Die Prüfung läuft im eigenen Takt und ändert nichts an der Zeit.
- **Selbsttest mit Upstream-Kette:** „Zeitserver erzwingen → Prüfen“ zeigt für jede eigene Quelle
  den Weg Name → Resolver → Adresse → Antwort, für alle Adressen eines Namens (z. B. nur AAAA
  umgeschrieben).
- **Zustand der eigenen DNS-Server:** Fällt ein eigener DNS-Server (klassisch, DoT, DoH) aus oder
  antwortet wieder, steht das je Server im Ereignisprotokoll; Wechsel innerhalb von 5 min werden
  nachgereicht statt verschluckt. Alle eigenen Server werden 20 s nach dem Start und dann alle
  15 min geprüft. Die Einstellungen zeigen „Letzte erfolgreiche Auflösung“ und „Erreichbar“.
- **Hinweis zu NTS:** NTS-Quellen brauchen ihren Namen; mit nur einem eigenen DNS-Server rät
  ntp-gui zu einem zweiten, unabhängigen.
- **Anleitungen nachgeschärft:** AdGuard-Ausnahme `@@||…^$dnsrewrite,client=<IP>` und
  „Client-spezifische Regel“, die Variante „ein Ziel“ (`||time.amazon.com^$dnsrewrite=time.lan`)
  mit ihren Grenzen (nie für NTS-Namen, Privates DNS/DoH umgeht sie, AAAA bedenken); UniFi: woran
  du siehst, ob die Ausnahme greift.

#### GNSS-Störungen, GPS-Sperre, Holdover-Test
- **GNSS-Störungen erkennen (Jamming/Spoofing)** mit jedem Empfänger, auch ohne PPS – gelesen
  wird nur aus gpsd und chrony:
  - gleichzeitiger Signaleinbruch der meisten Satelliten (≥ 6 dB in 60 s), unnatürlich
    gleichmäßige Signale, chrony hält das GPS für falsch (schwache Befunde);
  - GPS-Zeit weicht vom Median von ≥ 2 NTS-Quellen ab, Position springt um > 100 m, chrony
    markiert das GPS 5 min lang als Falschgeber, während ≥ 2 NTS-Quellen da sind (starke
    Befunde).
  - Zeit und Position werden gegen einen langsam nachgeführten Anker geprüft (höchstens 10 ms
    bzw. 20 m pro Stunde): Ein Spoofer, der die Zeit langsam wegzieht, fällt auf, und eine
    Fälschung, die einfach bleibt, wird nicht nach einer Weile „normal“. Der gewohnte Abstand
    GPS ↔ Netz übersteht Neustarts und wird neu gelernt, wenn sich Offset, Gerät oder Name des
    GPS ändern.
  - Stufen „Hinweis“, „Warnung“ und „Störung“ mit Hysterese; Schnee auf der Antenne oder ein
    Flugzeug lösen höchstens einen Hinweis aus. Ohne neue Messwerte endet ein Befund nach
    10 min mit „keine Messwerte mehr“.
  - Benachrichtigt wird standardmäßig nur bei „Störung“ (`GNSS_NOTIFY`), ins Protokoll kommt
    alles. Die Referenzposition bleibt im Arbeitsspeicher – Protokoll, Benachrichtigungen und
    API nennen nur die Abweichung in Metern.
- **GPS-Sperre per `chronyc selectopts`:** Einstellung „Störungserkennung“ (`GNSS_GUARD`):
  aus / nur melden (Standard) / automatisch sperren.
  - Gesperrt wird nur bei starken Befunden, nie bei reinem Jamming, und automatisch nur, wenn
    mindestens zwei andere auswählbare Netzquellen bleiben. Von Hand ohne andere Quelle nur nach
    ausdrücklicher Bestätigung.
  - Freigabe nach 30 min ohne Befund, höchstens dreimal in Folge, danach nur von Hand. Sperren,
    Freigeben und „Neu lernen“ gehen auch auf der GPS-Seite.
  - Die Sperre übersteht das Speichern von Einstellungen und Neustarts: Der Supervisor wählt das
    gesperrte GPS direkt nach jedem Start von chronyd wieder ab. Jede Sperre und Freigabe steht
    im Ereignisprotokoll.
- **Echter Holdover-Test (Seite Uhrqualität):** GPS/PPS und auf Wunsch alle Netzquellen werden
  für 1–24 h abgewählt; chrony misst die Netzquellen weiter als Messlatte. Ergebnis: „Die Uhr hält
  X ms in Y h“ samt Gangabweichung in ppm.
  - Abbruch über der Grenze (Standard 10 ms), bei einem Neustart von chronyd oder per Knopf;
    danach automatisch zurück, auch nach einem Neustart von ntp-gui.
  - Zeitfehler je Referenz gerechnet (kein Sprung, wenn ein Server ausfällt); Quellen, die
    während des Tests dazukommen, werden mit abgewählt (sonst „ungültig“). Ein Lauf nur ohne
    GPS/PPS heißt „Ohne GPS/PPS: Abweichung …“.
  - Hinweis in der Übersicht, solange der Test läuft. Übergaben zwischen GPS-Sperre und
    Holdover-Test überleben einen Neustart von ntp-gui.

#### Clients 3 – mehr über die Uhren im Haus
- **Uhrgüte je Gerät** (0–100) aus Abweichung, Stabilität, Regelmäßigkeit der Anfragen und
  Messbarkeit – als Spalte „Güte“ in der Client-Liste (gleich nach dem Update, aus den
  gespeicherten Messpunkten), als Kachel und Karte auf der Detailseite. Dazu die
  **Gangabweichung in ppm**; bei gleichmäßigen Abständen der Anfragen zeigt ntp-gui ehrlich nur
  „höchstens … ppm“, weil fester Versatz und Gang dann nicht zu trennen sind. Geräte, die ihre
  Zeit verschleiern (chrony, NTS), bekommen bewusst keine Note.
- **„Schlechteste Uhren im Haus“** im Netzüberblick.
- **Gruppen und Netze:** Benenne Netze („IoT = 10.0.30.0/24“), das spezifischste Netz gewinnt
  (IPv4 und IPv6). Ansicht nach Gruppe, VLAN (wo die Kennung sichtbar ist) oder Software, je
  Gruppe Anzahl, aktive Geräte, Median-Abweichung, Anteil „gut“ und Uhrgüte. Vorschläge aus den
  gesehenen /24- und /64-Netzen; Hinweis, wenn in einer Gruppe kein Gerät fragt („fehlt dort
  die Umleitung?“) – erst, wenn ntp-gui lange genug mithört.
- **Regeln je Gerät:** „fragt seit N h nicht mehr“ (meldet genau einmal, danach „fragt wieder“,
  gemessen mit der monotonen Uhr), eigene Alarm-Schwelle „|Abweichung| > X ms für M min“,
  **stumm** (Ereignis bleibt lokal) und **erwartete Client-Software** mit Hinweis, wenn das
  Verhalten nicht dazu passt. Offene Alarme überstehen Neustarts und werden beim Stummschalten
  oder Ändern der Regel still geschlossen.
- **Neues Gerät fragt nach der Zeit:** `CLIENTS_NEW_DEVICE_ALARM` (Standard aus), erkannt an MAC
  bzw. IPv4-Adresse, die ersten 24 h nur Lernen, höchstens 5 Meldungen pro Stunde.
- **NTS für Clients:** Die Detailseite zeigt, ob ein Gerät NTS nutzt (NTS-KE-Verbindungen aus
  `chronyc clients -k`, nur bei eingeschaltetem NTS-Server) und ob seine Software NTS kann.
- **Gerätepass** (`#/clients/<adresse>/pass`): alles Wichtige zu einem Gerät auf einer
  druckbaren Seite, mit Empfehlung und passendem Befehl (z. B. `w32tm …`). Zum Weitergeben gibt
  es eine **gefilterte Kopie** (Adressen als Pseudonym, Geräte- und Gruppennamen ersetzt – auch
  kurze –, ohne Notiz und MAC).
- **Stundenwerte je Gerät** werden 30 Tage aufgehoben.

#### HTTPS fürs Dashboard per Reverse Proxy (Entscheidung E5)
- In `docker-compose.all-in-one.yml` steht ein fertiger, auskommentierter Block
  **[OPTION HTTPS mit Caddy]**: im LAN mit Caddys eigener Zertifizierungsstelle
  (`--internal-certs`), mit öffentlichem Namen Let's Encrypt, dazu `WEB_BIND=127.0.0.1` und
  `TRUSTED_PROXIES`. `docs/integrationen/https.md` erklärt, wie du Caddys Root-Zertifikat auf
  Windows, macOS, Linux, iOS und Android einträgst, und nennt die Einstellungen für Nginx Proxy
  Manager, Zoraxy und Traefik. ntp-gui selbst bleibt bei HTTP.
- **Einstellung „Vertrauenswürdige Proxys“ (`TRUSTED_PROXIES`):** Nur von diesen Adressen glaubt
  ntp-gui `X-Forwarded-For`/`-Proto` bzw. den Standard-Kopf `Forwarded` (RFC 7239); dann nennt
  das Zugriffsprotokoll den Browser statt des Proxys. Standard: leer. „all“ und `/0` werden
  abgelehnt. Über Anmeldung und Zugriff entscheiden diese Köpfe nie.
- **Hinweise in der Übersicht:** „Dashboard über unverschlüsseltes HTTP mit Anmeldung“, wenn
  Passwort oder API-Schlüssel per HTTP aus dem Netz ankommen (auch über einen nicht
  eingetragenen Proxy); „Strecke Proxy → ntp-gui ist unverschlüsselt“, wenn der Proxy auf einem
  anderen Gerät läuft; ein Info-Hinweis, wenn ein nicht eingetragener Proxy seine Köpfe
  mitschickt. Die Hinweise verschwinden, sobald das Problem behoben ist (Speichern der Proxy-Liste
  setzt sie sofort zurück, nach späteren HTTPS-Zugriffen bleibt der HTTP-Hinweis höchstens eine
  Stunde).

#### Englisch (Gerüst)
- Mit dem Knopf „DE/EN“ oben rechts oder unter Einstellungen → Dashboard wählst du die Sprache;
  sie gilt je Browser, ohne Wahl gilt die Sprache des Browsers. Übersetzt sind bisher
  Navigation, Kopfzeile, das Statusband der Übersicht und die Abschnitte der Einstellungen. Fehlt
  ein englischer Text, erscheint der deutsche; die ⓘ-Erklärungen und Meldungen vom Server sind
  vorerst deutsch. Kann der Sprachkatalog nicht geladen werden, bleibt die Oberfläche deutsch
  statt rohe Schlüssel zu zeigen.
- **Übersetzen leicht gemacht:** Texte in `app/static/i18n/<sprache>.json` (Weblate-tauglich,
  Format i18next v4), Anleitung in CONTRIBUTING.md unter „Übersetzen“. Fehlende englische Texte
  stehen in einem Bericht (`python3 tests/test_i18n.py --report`).

#### Übersicht, API und Monitoring
- **GPS-Kachel der Übersicht** zeigt Rolle („Rückfallebene · in Benutzung“), Empfangsampel
  (24 h) und „unstet“. Neue Hinweise: „GPS-Empfang unstet“ bzw. „GPS-Empfang schwach (24 h)“
  (Info), GNSS-Störung/-Warnung, GPS gesperrt (färbt die GPS-Kachel), Holdover-Test läuft
  (färbt die Uhr-Kachel), Schleifen (Quellen-Kachel).
- **Neue API-Endpunkte** (auch unter `/api/v1`): lesen `GET /gps/quality`, `/gps/antenna`,
  `/loops`, `/gnss`, `/holdover`, `/clients/groups?by=group|vlan|software`, `/clients/quality`,
  `/clients/rules`, `/clients/pass?ip=…[&share=1]`; verwalten (Recht „admin“) `POST /gps/antenna`,
  `/gps/bound`, `/gnss`, `/holdover`, `/clients/groups`, `/clients/groups/delete`,
  `/clients/rules`. `/status` liefert zusätzlich `gps_summary`, `/clients/detail` Uhrgüte, Regel,
  Gruppe und NTS.
- **Neue Prometheus-Metriken:** `ntpgui_gps_error_bound_seconds`, `ntpgui_gps_reception_level`,
  `ntpgui_gps_unstable`, `ntpgui_gnss_stage`, `ntpgui_gps_locked`, `ntpgui_source_loops`,
  `ntpgui_holdover_test_running`. Neue Alarmregeln `NtpGuiSourceLoop` und
  `NtpGuiGnssDisturbance` in `docs/prometheus/alerts.yml`.
- Neue Einstellungen: `GPS_BOUND_MODE`, `GNSS_GUARD`, `GNSS_NOTIFY`, `CLIENTS_NEW_DEVICE_ALARM`,
  `NOTIFY_LAN_ADDRESSES`, `TRUSTED_PROXIES`.

### Geändert
- **Diagnosepaket nimmt bis zu 12 MB Aufzeichnung mit** (bisher 4 MB). Eine einstündige
  Aufzeichnung wurde sonst auf die letzte halbe Stunde gekürzt. Auf dem Raspberry Pi dauert das
  Paket damit länger; das Dashboard bleibt währenddessen bedienbar.
- Die Verlaufs-Kennzahlen im Diagnosepaket enthalten die Temperatur und ein Stundenprofil
  Temperatur ↔ Frequenz (Mittel je Stunde) – Grundlage für den Temperaturausgleich.
- Benachrichtigungen: Ereignisse mit `data.notify = false` bleiben lokal (GNSS-Hinweise unter der
  Schwelle, stumm geschaltete Geräte, Holdover-Test). Ereignisse, die ausdrücklich gemeldet werden
  sollen (z. B. „GNSS ab Hinweis“), gehen auch an Kanäle mit höherer Mindeststufe.
- GPS-Kachel der Übersicht: Rolle und Empfangsampel ersetzen die Zeile HDOP (steht weiter auf
  der GPS-Seite).
- Datenschutzfilter: Eigene Gruppennamen werden im Diagnosepaket wie Gerätenamen ersetzt.

### Behoben
- Bricht ein Browser eine Verbindung ab (Tab zu, Neuladen, Handy im Standby), steht im Log kein
  Python-Traceback mehr. Bisher landeten dort mehrere ineinander verschränkte Fehlermeldungen.
- Ein kurzer Aussetzer von `chronyc sourcename` lässt den Namen einer Quelle nicht mehr für
  10 Minuten verschwinden; ntp-gui behält den letzten Namen und fragt nach 30 s erneut.

## [1.4.0] – 2026-11-02

### Hinzugefügt
- **Benachrichtigungen:** Der Server meldet sich, wenn etwas passiert – über **ntfy**,
  **Gotify**, **Webhook** (JSON, optional mit HMAC-SHA256-Signatur im Header
  `X-NTPGUI-Signature`) oder **Apprise-API** (E-Mail, Telegram, Matrix, Signal und über 100
  weitere Dienste über einen Zusatz-Container). Neue Seite „Benachrichtigungen“: Kanäle
  anlegen, Filter nach Stufe und Art, „Testnachricht senden“, Zustellstand je Kanal. Ohne
  angelegten Kanal verlässt nichts den Server.
  - Gleiche Meldungen werden **entprellt** (Standard: höchstens alle 15 min je Art und
    Gerät/Dienst). Ist ein Problem vorbei, kommt „behoben“ mit Dauer („GPS-Fix wieder da –
    Dauer 40 min“); als „behoben“ zählen nur echte Gegenstücke. Ein zurückgehaltenes Problem,
    das am Ende der Sperrzeit noch besteht, wird nachgeholt. „Kritisch“ geht immer sofort
    hinaus – auch nach einer Warnung oder direkt nach einem „behoben“.
  - Klappt die Zustellung nicht, versucht der Server es nach 30 s, 2 min und 10 min erneut;
    danach wird die Nachricht verworfen und das steht im Ereignisprotokoll (neue Art
    „Benachrichtigung“). Je Kanal gilt ein Limit (Standard 30 je Stunde), jeder Kanal hat einen
    eigenen Thread, jede Zustellung eine Gesamtfrist von 10 s (Namensauflösung, Verbindung und
    Antwort zusammen). Nach einem Neustart werden schon zugestellte Meldungen nicht noch einmal
    verschickt.
  - `https://ntfy.sh/<thema>` wird erkannt; bei ntfy, Gotify und Apprise wird eine Adresse mit
    `?…` abgelehnt.
  - Neue Einstellung „Adresse des Dashboards (für Links)“ (`NOTIFY_DASHBOARD_URL`): Nachrichten
    verlinken dann direkt auf die passende Seite.
- **Eigene DNS-Server für ntp-gui:** Unter Einstellungen → „DNS für ntp-gui“ stellst du ein,
  worüber ntp-gui selbst Namen auflöst: System-DNS (Standard, wie bisher), eigene DNS-Server
  (klassisches DNS an feste IP-Adressen), DNS-over-TLS oder DNS-over-HTTPS (`DNS_MODE`,
  `DNS_SERVERS`, `DNS_DOT`, `DNS_DOH`, `DNS_PIN`, `DNS_FALLBACK`). So läuft chronyd nicht mehr in
  eine Schleife, wenn AdGuard Home oder Pi-hole Zeitserver-Namen wie pool.ntp.org auf ntp-gui
  umschreibt. Dafür startet ein kleiner Weiterleiter nur auf 127.0.0.1 im Container, und
  `/etc/resolv.conf` zeigt darauf. Das Original wird gesichert und beim Zurückschalten, beim
  Beenden und nach einem Absturz zurückgeschrieben.
  - DoT/DoH prüfen das Zertifikat des Servers. Optional trägst du feste Adressen ein
    (z. B. `dns.quad9.net=9.9.9.9`) – nötig, wenn der Container keinen anderen DNS hat
    (`dns: 127.0.0.1`); ein eigener Hinweis sagt das. Antwortet keiner deiner Server, fragt
    ntp-gui den ursprünglichen DNS des Containers (abschaltbar; Antworten daraus bleiben nur
    5 s im Cache) und meldet das als Ereignis der neuen Art „DNS“.
  - Ein einzelner langsamer Name schaltet einen Server nicht ab; erst drei
    Zeitüberschreitungen in Folge oder ein harter Fehler zählen als Ausfall. DoH hat eine harte
    Frist je Anfrage, auch gegen Server, die ihre Antwort Byte für Byte tröpfeln lassen.
  - Neuer Hinweis „Schleife durch DNS-Umschreibung“: erscheint, wenn eine eigene Zeitquelle
    per DNS auf ntp-gui selbst zeigt, und empfiehlt einen eigenen DNS-Modus.
  - Zeitserver erzwingen: Die Firewall-Anleitungen (UniFi, OPNsense/pfSense, MikroTik,
    OpenWrt, nftables) enthalten jetzt eine optionale „DNS-Umleitung per Firewall“ (Port 53
    auf AdGuard/Pi-hole), mit Pflicht-Ausnahme für ntp-gui.
- **Clients im Detail:**
  - **Verlauf je Client:** 7 Tage Abweichung, Poll-Feld, NTP-Version und tatsächlicher
    Abstand der Anfragen (höchstens alle 2 min ein Punkt). Erste und letzte Sichtung überstehen
    Neustarts.
  - **Detailseite je Gerät** (`#/clients/<adresse>`, ein Klick in der Client-Liste): Diagramm
    der Abweichung (1 h bis 7 Tage), Abstand der Anfragen und Poll, „messbar“ mit Begründung,
    VLAN, erste/letzte Sichtung, Name aus dem Reverse-DNS, MAC-Adresse (nur wenn das Gerät im
    selben Netz steht) und Hersteller, falls eine OUI-Liste vorhanden ist (`/config/oui.txt`).
  - **Vermutete Client-Software** (Windows/w32time, systemd-timesyncd, chrony/NTPsec/OpenNTPD,
    ntpd, SNTP/IoT, Apple) – begründet und klar als Vermutung gekennzeichnet.
  - **Eigene Namen und Notizen** für Geräte (nur Admins): bleiben lokal, erscheinen in Liste,
    Überblick und Ereignisanzeige. Gespeicherte Ereignisse nennen nur die Adresse; im
    Diagnosepaket und in Benachrichtigungen wird nie ein Name verschickt, Notizen werden nie
    exportiert.
  - **Netzüberblick** auf der Clients-Seite: Verteilung der Abweichungen (< 1 ms … > 1 s,
    falsche Uhr), die fünf Geräte mit der größten Abweichung, verstummte Geräte und Geräte, die
    öfter als alle 8 s fragen (kurze Schwälle wie ntpd-iburst zählen nicht).
  - **„Aktiv nachmessen“:** eine einzelne NTP-Anfrage an ein bekanntes Gerät im LAN zeigt bei
    Routern, NAS und manchen Kameras Abweichung und Laufzeit, auch wenn sie ihre Sendezeit
    verschleiern. Pro Gerät höchstens alle 30 s, insgesamt höchstens 10 pro Minute; nicht für
    link-lokale IPv6-Adressen.
  - **Alarm bei falsch gehender Client-Uhr:** neue Einstellung `CLIENTS_ALARM_MS` (Standard
    aus). Gemeldet wird nach zwei Messungen in Folge über der Schwelle („Uhr von … weicht um …
    ab“, Art Clients), „wieder im Rahmen“ erst unter der halben Schwelle.
  - Neue Einstellung `CLIENTS_RDNS` (Standard **aus**): Reverse-DNS nur für private Adressen,
    nur beim Öffnen der Detailseite, nie über DoT/DoH und nie, wenn ein beteiligter DNS-Server
    öffentlich ist.
- **Neue Seite „Uhrqualität“** (Navigation nach PTP):
  - **Temperatur wird aufgezeichnet** (nur messen, noch kein Temperaturausgleich): Thermalzonen
    (Raspberry Pi `cpu-thermal`), Sensorchips am PC (`k10temp`, `coretemp`, `x86_pkg_temp`) und
    DS18B20 am 1-Wire-Bus werden selbst gefunden. Streudiagramm Temperatur ↔ Frequenz,
    Temperatur- und Frequenzverlauf, Spanne, Messdauer und Zusammenhang (r). Nach 1–3 Tagen mit
    Tag-/Nacht-Wechsel siehst du, ob sich ein Temperaturausgleich lohnt – den Vorschlag dafür
    bringt 1.5. Neue Einstellung **Temperatursensor** (`TEMP_SENSOR`, Standard `auto`, `off` =
    aus); der Hardware-Check listet alle gefundenen Sensoren; ein Sensor ohne plausiblen Wert
    (z. B. DS18B20 auf 85 °C) wird als „liefert keinen Wert“ gemeldet.
  - **Schaltsekunden-Übersicht:** TAI−UTC, letzte Schaltsekunde, Ablaufdatum der
    `leap-seconds.list` mit verbleibenden Tagen, SHA-1-Prüfsumme und Leap-Status von chrony –
    immer für die Datei, die chrony wirklich liest. Läuft die Liste in weniger als 60 Tagen ab
    (oder ist sie abgelaufen oder verändert), erscheint der Hinweis „Image zu alt – Update
    einspielen“ und ein Ereignis „Schaltsekunde“. ntp-gui lädt die Liste bewusst nicht selbst
    aus dem Internet.
- **Vollbild-Uhr unter `/clock`** für Wandmonitor und Tablet: große Ortszeit und UTC, Datum,
  Kalenderwoche und ein Statusband (Ampel, Genauigkeit, Art der Quelle). Die Anzeige wird wie
  bei NTP mit vier Zeitstempeln an die Serveruhr angeglichen (fünf Messungen, kürzeste Laufzeit
  gewinnt) – die Uhr des Tablets ist egal. Hell, Dunkel und Rotlicht, Wake Lock (wo der Browser
  es erlaubt), Taste F für Vollbild, graue Ampel nach 10 s ohne Verbindung. Erreichbar über das
  neue Uhr-Symbol oben rechts. Neue Einstellung **Vollbild-Uhr ohne Anmeldung**
  (`CLOCK_PUBLIC`, Standard aus): nur `/clock` und `/api/v1/time` ohne Passwort – mit Uhrzeit,
  Ampel, Genauigkeit und Art der Quelle, ohne Namen, Adressen oder Einstellungen.
- **Update-Hinweis (opt-in, Standard aus):** Einmal am Tag zu einer zufälligen Uhrzeit fragt
  ntp-gui bei GitHub nach der neuesten Version (`releases/latest`) und vergleicht sie lokal.
  Ist eine neuere da, erscheinen ein Banner und in der Übersicht ein Hinweis mit Release-Titel,
  Link zu den Release-Notizen und der Markierung „Achtung beim Update“, wenn der Release-Text
  „BREAKING“ oder „Achtung“ enthält. Kein Download, kein automatisches Update; für
  Automatisierung Diun oder What's up Docker. Einschalten unter Einstellungen → Dashboard →
  „Update-Hinweis“ oder `UPDATE_CHECK=true`. Ehrlich gesagt: GitHub sieht dann einmal am Tag
  deine öffentliche IP-Adresse (grob ortbar) und dass dort vermutlich ntp-gui läuft.
- **Grafana-Dashboard** `docs/grafana/ntp-gui.json` und **Prometheus-Alarmregeln**
  `docs/prometheus/alerts.yml` (nicht synchron, Abweichung zu groß, keine Quelle, GPS ohne
  Fix, PPS weg, Dienst gestört, NTS-Zertifikat und Schaltsekunden-Liste laufen ab, neue
  Version). Ein Test stellt sicher, dass jede verwendete Metrik in `/metrics` existiert.
- **Anleitungen für Integrationen** unter `docs/integrationen/`: Home Assistant, Homepage und
  Glance, Uptime Kuma, Grafana/Prometheus.
- **Übersicht:** Die Kachel „Systemuhr“ zeigt Temperatur (wenn ein Sensor aufzeichnet) und
  wie lange die Schaltsekunden-Liste noch gilt; die Kachel „Dienste“ zeigt den DNS-Weiterleiter,
  den DNS-Modus und den Zustand der Benachrichtigungen.
- **Neue Metriken:** `ntpgui_max_error_seconds`, `ntpgui_sources`, `ntpgui_sources_usable`,
  `ntpgui_info{version}`, `ntpgui_service_enabled`, `ntpgui_temperature_celsius`,
  `ntpgui_leapseconds_list_days_left`, `ntpgui_tai_utc_offset_seconds`; mit Update-Hinweis
  `ntpgui_update_available` und `ntpgui_update_check_last_success_timestamp_seconds`.
- **Neue API-Endpunkte** (alle auch unter `/api/v1`, beschrieben in `GET /api/v1`):
  `/notify/status` (Leserecht, nur Kennung, Art und Zustellstand), `/notify`,
  `/notify/channels`, `/notify/channels/delete`, `/notify/test` (Verwaltungsrecht), `/dns`,
  `/clients/overview`, `/clients/detail?ip=…`, `/clients/meta` und `/clients/probe`
  (Verwaltungsrecht), `/temperature`, `/leap`, `/time`, `/update`. `/api/v1/status` hat neu
  `dns`, `leap`, `notify` und `update`, `/clients/offsets` liefert zusätzlich `names`,
  `/events` zusätzlich `display_title`.

### Geändert
- Alarm `NtpGuiServiceDown` und Grafana-Kachel „Dienste gestört“ zählen nur Dienste, die laut
  Einstellungen laufen sollen (`ntpgui_service_enabled`) – absichtlich gestoppte Dienste lösen
  keinen Alarm aus.
- Das Update-Banner liegt nicht in der klebenden Kopfzeile und ist auf dem Handy kompakt.
- Im Diagramm-Kopf steht bei Zeiträumen über einem Tag auch das Datum („Verlauf ab …“).

### Behoben
- **Hardware-Check schlug beim VK-162 & Co. weiter „/dev/pps0 einbinden“ vor.** gpsd hängt beim
  Öffnen selbst eine PPS-Leitungsdisziplin an `/dev/ttyACM0` (`/dev/pps0`, Name „acm0“); über einen
  USB-Empfänger kommt dort aber nie ein Impuls. Der Empfänger bleibt jetzt „kein PPS“, der Check
  erklärt, woher `/dev/pps0` stammt, und rät nicht mehr zum Einbinden. Allgemein: Ein PPS-Gerät,
  das am Host noch nie einen Impuls gezählt hat, wird nicht mehr zum Einbinden vorgeschlagen.
- Hardware-Check auf dem Pi: Neben einem erkannten USB-Empfänger erscheint die leere Mini-UART
  `ttyS0` nicht mehr als zweite „Empfänger“-Karte mit „PPS über GPIO möglich“.
- **Container konnte sich beim Speichern von Einstellungen beenden** (auch in 1.3.x): Kam eine
  Änderung genau, während die Zeitdienste neu starteten, traf das Signal an den Supervisor die
  bash mitten in einer Befehlsersetzung („trap: unexpected EOF while looking for matching `)'“) –
  der Supervisor und damit der Container endeten. Das Dashboard bittet jetzt per Datei
  (`/run/ntp-gui/reload.request`) um das Neuladen statt per SIGHUP. Im Belastungstest (150
  schnelle Wechsel) bleibt der Container stabil; vorher endete er nach 21 bzw. 48 Wechseln.
- Ein frisch gestarteter Dienst galt in den ersten Millisekunden als „beendet“ (der Prozess trug
  noch den Namen der Shell); der Supervisor wartet jetzt kurz auf den Start.
- Sperrzeiten (Benachrichtigungen, Prüfung „Zeitserver erzwingen“, Anmelde-Cache) laufen auf der
  monotonen Uhr: Stellt chrony die Systemuhr (Pi ohne Echtzeituhr), verlängert das keine Sperre
  mehr. Mehrere Zeitvergleiche gingen in der ersten Stunde nach dem Systemstart falsch
  (Startwert 0 statt „noch nie“) – u. a. blieb das Benachrichtigungs-Ereignis „gedrosselt“ aus.
- Eigener Rechnername: Der vollständige Name (Rückwärts-DNS) wird einmal im Hintergrund
  ermittelt und gemerkt, statt bei jeder Anfrage mit fremdem Host-Kopf – ein langsamer Resolver
  hielt sonst jedes Mal einen Anfrage-Thread fest.
- DNS-Weiterleiter: Die Statusdatei konnte bei gleichzeitigem Schreiben halb geschrieben gelesen
  werden (Dashboard zeigte den Weiterleiter dann als „gestoppt“); die Meldung bei belegtem Port
  nennt jetzt den richtigen Port.

### Sicherheit
- **Datenschutz bei Benachrichtigungen:** Jede Nachricht läuft durch den Datenschutzfilter
  (neuer Zweck `notify` mit eigener Feldliste). Hinaus gehen nur Titel, Text, Stufe, Art und
  Zeit – keine Koordinaten (auch nicht mit Nullen am Ende wie „52.5200, 13.4050“), keine
  öffentlichen IP-Adressen, keine eigenen Hostnamen, keine Ereignisdaten, keine Client-Namen.
  Kann die Liste eigener Namen nicht ermittelt werden, wird nicht gesendet. Weiterleitungen
  werden nie befolgt, Proxys aus der Umgebung nicht benutzt, Antworten höchstens 64 KiB.
- Benachrichtigungs-Tokens werden nur als „gesetzt“ angezeigt, stehen nie im Ereignisprotokoll
  oder Diagnosepaket und gehen nie an ein geändertes Ziel (Art, Host, Port oder Schema
  geändert ⇒ Token neu eingeben). Über `http://` nur an Adressen im eigenen Netz. Adressen mit
  Pfad (Webhook-IDs) zeigen Dashboard und API nur gekürzt.
- Update-Hinweis: Die Anfrage an GitHub ist fest verdrahtet (eigener Filterzweck
  `update_check`): User-Agent nur „ntp-gui“, ohne Version und Kennung, keine Daten der Instanz,
  keine Weiterleitungen, Gesamtfrist 20 s, Antwort höchstens 512 KiB. Ausgeschaltet gibt es
  keinerlei Netzzugriff.
- DNS für ntp-gui: Loopback-Adressen auf Port 53 (auch `::ffff:127.0.0.1`) sind als
  DNS-Server abgelehnt; API-Schlüssel mit Leserecht sehen DoH-Adressen nur gekürzt (sie können
  eine Konto-Kennung enthalten, z. B. bei NextDNS). Status, Ereignisse und Diagnosepaket nennen
  nur den Servernamen.
- Clients: MAC-Adressen verlassen die Instanz nie; Namen und Notizen lehnen unsichtbare und
  Bidi-Steuerzeichen ab; „private Adresse“ heißt genau RFC 1918, CGNAT, Link-lokal, ULA,
  Loopback (6to4, Teredo, NAT64 zählen nicht). Der Client-Verlauf ist auch insgesamt begrenzt
  (höchstens 2 Mio. Messpunkte), wechselnde Absenderadressen können `/data` nicht füllen.
- Vollbild-Uhr ohne Anmeldung: Anonyme Anfragen an `/clock` und `/api/v1/time` unterliegen dem
  Schutz vor DNS-Rebinding; `/api/v1/time` fragt chrony höchstens einmal pro Sekunde ab.
- Diagnosepaket: Seriennummern von DS18B20-Fühlern werden entfernt.
- **Lieferkette:** Jeder Release bringt je Architektur (amd64, arm64) eine SBOM (SPDX) und einen
  Schwachstellen-Bericht (Grype) mit, beide aus dem veröffentlichten Digest; der Release bricht
  bei einer kritischen Lücke mit verfügbarer Korrektur ab. Herkunftsnachweis (SLSA Build
  Provenance) am Image, prüfbar mit `gh attestation verify`. Alle GitHub Actions per
  Commit-SHA festgenagelt, OIDC-Token nur im eigenen Job, Release-Builds ohne Cache,
  Basis-Image per Digest festgenagelt; Dependabot schlägt Updates für Actions und Basis-Image
  vor. Image-Tags werden erst nach Scan und Nachweis gesetzt.
- Integrations-Doku: Hinweis, dass der API-Schlüssel über HTTP im Klartext reist – HTTPS über
  einen Reverse-Proxy oder ein vertrauenswürdiges Netz nutzen, je Integration ein eigener
  Lese-Schlüssel.

## [1.3.2] – 2026-11-02

### Geändert
- **Übersicht neu als „Single Pane of Glass“:** Statusband mit Gesamturteil und vier
  Kennzahlen samt Verlaufslinie; Hinweise einzeilig (Details aufklappbar) und dem passenden
  Bereich zugeordnet, der ihre Farbe übernimmt; Kacheln für Systemuhr, Zeitquellen, GPS, PTP,
  Clients, Dienste und die letzten Ereignisse.
- **Klarere Diagramme** auf allen Seiten: Kopfzeile mit jetzt/min/max/Mittel, einzelne
  Ausreißer (z. B. beim Start) werden ausgeblendet und markiert statt die Skala zu sprengen,
  Lücken sichtbar, Fadenkreuz mit Tooltip (Maus, Touch, Tastatur), Zeitachse in Ortszeit, eine
  Einheit je Achse, Zahlen einheitlich mit Dezimalkomma; bessere Kontraste und Texte für
  Bildschirmleser.
- **GPS-Fix-Ereignisse erst nach 60 s:** Bei schwachem Empfang kam und ging der Fix im
  Minutentakt und füllte das Protokoll mit „verloren/wieder da“-Paaren.
- **Selbsttest „Zeitserver erzwingen“** prüft DNS-Umschreibung (per Name) und
  Firewall-Umleitung (per IP-Adresse, `216.239.35.0`) getrennt – per Name greift schon der DNS.
  Dazu ein Hinweis, wie man das Hairpin-Problem erkennt.
- **Diagnosepaket mit Aufzeichnung deutlich schneller:** Filter und Schlussprüfungen merken
  sich gleiche Zeilen, Vorschau und Paket entstehen in einem Durchgang. Mit einer
  10-Minuten-Aufzeichnung (rund 2300 Einträge, 1,5 MB) brauchten Vorschau und Download bisher
  zusammen 78 s (33 s + 45 s), jetzt 9 s (gemessen auf x86; auf einem Raspberry Pi entsprechend
  länger). Das Ergebnis ist byteweise dasselbe wie vorher.
- **Das Dashboard bleibt währenddessen bedienbar**, auch in anderen Tabs: Gefiltert wird in
  einem eigenen Prozess mit niedriger Priorität (`nice 10`), nicht mehr im Dashboard-Prozess.
- **Download nach der Vorschau sofort und identisch:** Steht eine Vorschau auf der Seite
  (gleiche Schalter, höchstens 10 Minuten alt, Aufzeichnung unverändert), liefert
  „Herunterladen“ genau dieses Paket, ohne neu zu bauen. Dateiname, Ordner und MANIFEST tragen
  den Zeitpunkt des Pakets.
- Mehrfach geklickt oder Seite neu geladen: Wartende Anfragen bekommen das Ergebnis des gerade
  laufenden Baus, statt jede für sich neu zu bauen.

### Behoben
- **Clients:** „Zuletzt“ und „Anfragen“ zeigten bei manchen Geräten „–“. chrony leert seine
  Client-Liste bei jedem Neustart (etwa nach dem Speichern von Einstellungen); ntp-gui nimmt
  dann die Werte der eigenen Messung (mit * markiert).
- Der Download lieferte nach einer fehlgeschlagenen Vorschau oder nach einer neuen Aufzeichnung
  ein älteres Paket. Er nimmt jetzt nur die Vorschau, die gerade angezeigt wird; nach dem
  Umschalten von „Client-Liste“ oder „Aufzeichnung einschließen“ verschwindet die alte Vorschau.
- Wird der Diagnose-Prozess beendet (z. B. vom OOM-Killer), nennt die Meldung das Signal
  („beendet durch SIGKILL (9) – vermutlich zu wenig Arbeitsspeicher“) und steht auch im
  Container-Log.
- Zwischenspeicher der Prüfungen sind nach Speicher begrenzt und werden nach jedem Paket
  geleert – kein langsam wachsender Speicherverbrauch im Dashboard-Prozess.
- Hinweis während des Bauens: Mit Aufzeichnung dauert es auf einem Raspberry Pi „eine bis
  mehrere Minuten“ (bisher „etwa eine Minute“).

## [1.3.1] – 2026-11-01

### Geändert
- **Basis-Image Debian 13 „trixie“** (`debian:trixie-slim`) statt bookworm: chrony 4.6.1,
  gpsd 3.25, linuxptp 4.2, Python 3.13. bookworm bekommt seit 07/2026 nur noch LTS-Updates.
- **Schaltsekunden über `leapseclist /usr/share/zoneinfo/leap-seconds.list`** (neue
  Einstellung `LEAPSECLIST`); trixie hat keine Zone `right/UTC` mehr. Ein gespeichertes
  `LEAPSECTZ=right/UTC` wird beim ersten Start automatisch entfernt (Einstellungs-Schema 3,
  Hinweiskarte auf der Einstellungsseite). `LEAPSECTZ` bleibt nur für eigene Images mit
  `right/`-Zonen; fehlt die Zone, nimmt ntp-gui die Liste.
- `ptp4l.conf` schreibt `clientOnly`/`serverOnly` statt `slaveOnly`/`masterOnly`. linuxptp 4.2
  meldete die alten Namen bei jedem Start als veraltet im PTP-Log.

### Behoben
- **Diagnosepaket mit Aufzeichnung** brach mit „latenz_gerundet“ ab, obwohl richtig gefiltert
  war: Die Schlussprüfung las die JSON-Zeilen der Aufzeichnung als Rohtext, so stand z. B.
  „Precision (0.000000030 seconds)“ neben „Root delay“. Sie prüft JSON-Zeilen jetzt wie der
  Filter.
- **Datenschutz:** chrony-RefIDs von IPv6-Adressen (ein Hash der Adresse, z. B.
  `Local address … (E41BC59B)` in `ntpdata`) blieben stehen, wenn sie zufällig im
  Multicast-Bereich lagen. Unbedenklich sind jetzt nur Namen (GPS, PPS …), Loopback und 0.0.0.0.
- „timezone to …“ in chrony-Logs wurde fälschlich als Zeitzone ersetzt.
- Ohne `NTPGUI_VERSION` meldeten Dashboard, `/api/status` und Diagnosepaket noch Version
  1.3.0; das Startereignis hatte keine Version.

## [1.3.0] – 2026-11-01

### Hinzugefügt
- **Seite „Diagnose“**: Container-Log mit Text- und Stufenfilter (`/api/logs`; der
  Supervisor schreibt dafür zusätzlich nach `/run/ntp-gui/ntp-gui.log`, rotiert ab 2 MB,
  abschaltbar mit `NTPGUI_LOGTEE=0`), Ereignisprotokoll und ein **Diagnosepaket**
  (`/api/diagnostics/preview`, `/api/diagnostics/bundle`) mit Vorschau und deutscher
  `MANIFEST.txt`. Das Paket wird nur heruntergeladen, nie hochgeladen.
- **Zentraler Datenschutzfilter** (`app/egress.py`) für alles, was die Instanz verlässt:
  keine Koordinaten, Höhe, Geschwindigkeit, Satellitenwinkel (Azimut/Elevation),
  Seriennummern (USB, DMI, `/dev/serial/by-id`), MAC-Adressen und PTP-Clock-IDs,
  öffentlichen IP-Adressen, eigenen Hostnamen, Domains und Zertifikatsnamen, Zeitzonennamen;
  private Adressen werden zu stabilen Pseudonymen (`client-07`). Laufzeiten zu Servern
  (Root/Peer delay, Fehlerschranken, RTT – auch in chronyc-Ausgaben und Aufzeichnungen) werden
  für jeden Zweck auf 10 ms gerundet; von Satelliten bleiben nur Summen je System (keine
  Satellitennummern). Zwei Schlussprüfungen – eine mit den Regeln des Filters, eine davon
  unabhängige auf den fertigen Bytes – laufen über jede Datei des Pakets und brechen den
  Export ab, wenn sie noch etwas finden; in Log und Aufzeichnung wird stattdessen nur die
  beanstandete Zeile entfernt.
- **Schutz vor DNS-Rebinding:** Ohne Passwort beantwortet das Dashboard nur Anfragen an
  IP-Adressen, `localhost`, den eigenen bzw. einteilige Hostnamen, lokale Endungen (`*.local`,
  `*.lan`, `*.home.arpa`, `*.internal` …), den NTS-Namen und `WEB_ALLOWED_HOSTS` (neu,
  kommagetrennt, `*.domain`, `*` schaltet ab); alles andere bekommt `403` mit Erklärung.
  `*.fritz.box` gilt bewusst nicht als lokal (`.box` ist eine öffentliche Endung). Mit
  Passwort oder API-Schlüssel gilt jeder Name, `/healthz` ist immer offen.
- **Ereignisprotokoll** (`/api/events`, 90 Tage): Neustarts und Ausfälle von Diensten,
  Neuladen, Zertifikate, GPS-Gerät weg/neu angesteckt (vom Supervisor), Wechsel der
  ausgewählten Quelle, GPS-Fix verloren/wieder da, PPS-Impulse ausgeblieben/wieder da,
  geänderte Einstellungen (nur Feldnamen), Kalibrierung, API-Schlüssel.
- **Zeitserver erzwingen** (Seite „Clients“, `/api/enforce/snippets`, `/api/enforce/check`):
  Anleitungen für DNS-Umschreibung (AdGuard Home, Pi-hole, dnsmasq, Unbound) und
  Firewall-Umleitung (OPNsense/pfSense, MikroTik, OpenWrt, nftables, UniFi) mit Ausnahme
  für ntp-gui selbst und Hairpin-Regel, eigene Namen per `ENFORCE_HOSTNAMES`. NTS-Server
  und `fritz.box` werden nie umgeschrieben. Die Prüfung (höchstens alle 30 s) erkennt
  wirksame Umschreibung, fehlende IPv6-Sperre und Schleifen.
- **Passive Messung der Client-Uhren** (`/api/clients/offsets`, `CLIENTMON`): Abweichung
  jeder Client-Uhr aus ihren NTP-Anfragen, ohne etwas an die Geräte zu senden; erkennt
  Clients, die ihre Zeit absichtlich verschleiern. Braucht `NET_RAW` und Host-Netzwerk.
- **Automatische GPS-Kalibrierung** (`GPS_AUTOCAL=off|suggest|auto`,
  `GPS_AUTOCAL_MAX_STEP_MS`, `GPS_AUTOCAL_MIN_HOURS`): höchstens ein kleiner Schritt je
  24 h, nur mit vertrauenswürdiger Netzreferenz, jede Änderung im Ereignisprotokoll und
  per Knopf umkehrbar (`/api/gps/autocal`, `POST /api/gps/autocal/rollback`). Die
  Automatik stellt nie weiter, solange nicht belegt ist, dass die letzte Änderung wirkt
  (Offset in der laufenden `chrony.conf` und erfolgreiches Neuladen); gemessen wird ab dem
  Zeitpunkt, an dem sie aktiv wurde.
- **API-Schlüssel** mit Recht „nur lesen“ oder „lesen und verwalten“
  (`Authorization: Bearer ntpg_…`, gespeichert wird nur ein SHA-256-Hash – PBKDF2 hätte bei
  144 Bit Zufall nichts gebracht, aber jede Anfrage mit erfundenem Schlüssel teuer gemacht;
  Schlüssel aus Vorabversionen werden beim nächsten Gebrauch umgestellt). Im
  Ereignisprotokoll steht nur die Kennung eines Schlüssels, nie sein Name. Passwort und Schlüssel
  lassen sich nur mit Benutzer/Passwort verwalten, nie mit einem Schlüssel.
- **Versionierte API `/api/v1`**; `GET /api/v1` beschreibt alle Endpunkte samt nötigem Recht.
- **Aufzeichnung und Wiedergabe** der Datenquellen (`/api/recording`, `NTPGUI_REPLAY`,
  `NTPGUI_REPLAY_SPEED`, `python3 app/providers.py replay-info`): alle Abfragen an chronyc,
  pmc, ethtool und gpsd laufen über eine Stelle (`app/providers.py`).
- Zufällige **Instanz-Kennung** (`/api/v1/instance`), jederzeit neu erzeugbar.
- Integrationstest: Log-Seite, Diagnosepaket ohne Standort und Kennungen, API-Schlüssel,
  Schutz vor DNS-Rebinding und `WEB_ALLOWED_HOSTS` (111 Prüfungen statt 68).

### Geändert
- Verlauf, Ereignisse, Client-Messwerte und API-Schlüssel liegen in SQLite (`ntp-gui.db`).
  Der Verlauf reicht jetzt **30 Tage** (`HISTORY_DAYS`), lange Zeiträume kommen aus einer
  5-Minuten-Vorverdichtung. Neue Punkte werden alle 5 Minuten geschrieben (schont
  SD-Karten). `HISTORY_SIZE` ist nur noch eine Obergrenze, wenn es gesetzt ist. Ein
  vorhandenes `history.json.gz` wird beim ersten Start übernommen und als `.migrated`
  aufbewahrt.
- Einstellungen tragen eine **Schema-Version** und werden beim Update einmalig migriert; was
  dabei geändert wurde, zeigt die Einstellungsseite oben an (`/api/settings/notes`). Auch
  Sicherungen älterer Versionen lassen sich importieren. Migration 1→2 entfernt gespeicherte
  NTS-Zertifikatspfade außerhalb von `/config`, `/certs` und `/etc/letsencrypt`.
- `/api/gps/calibration` ohne `window` wertet die letzten 24 h aus (`window=0`: alles) –
  über 30 Tage Verlauf würde die Berechnung sonst Sekunden dauern.
- Neue Navigationsseite „Diagnose“; die Einstellungsseite hat Karten für API-Schlüssel,
  Instanz-Kennung und Update-Hinweise.

### Behoben
- **Kopieren-Knöpfe** (Clients, PTP, Hardware, API-Schlüssel) funktionieren auch über
  einfaches `http://` im LAN: Ohne sichere Verbindung greift ein Ersatzweg; klappt auch der
  nicht, wird der Text markiert und ein Hinweis zeigt Strg+C.
- Hardware-Check: Ein USB-GPS an `ttyACM` (z. B. VK-162) wurde fälschlich als
  USB-Seriell-Adapter mit möglichem DCD-PPS eingestuft, wenn der Treiber-Link in `/sys`
  nicht lesbar war. `ttyACM`-Geräte kommen immer von `cdc_acm` und liefern kein PPS. Der
  GPIO-PPS-Vorschlag bei „geht nicht“ ist jetzt klar als Lösung mit anderer Hardware
  gekennzeichnet.

## [1.2.0] – 2026-11-01

### Achtung beim Update (Breaking Change)
- **NTS-Zertifikatspfade sind eingeschränkt:** `NTS_SERVER_CERT` und `NTS_SERVER_KEY`
  dürfen nur noch unter `/config`, `/certs` oder `/etc/letsencrypt` liegen (auch das Ziel
  eines Symlinks). Ein Pfad woanders (z. B. `/etc/ssl/…`) wird abgelehnt, es gilt der
  Standard `/config/nts.crt`/`/config/nts.key` – fehlen die Dateien dort, bleibt der
  NTS-Server nach dem Update aus (normales NTP läuft weiter). Grund: Die Dateien werden in
  ein für chronyd lesbares Verzeichnis kopiert; ein freier Pfad würde z. B. erlauben,
  `/etc/shadow` dorthin zu kopieren. Abhilfe: den Zertifikatsordner nach `/certs` (oder
  `/etc/letsencrypt`) mounten und die Pfade anpassen.
- `PHC2SYS_OPTIONS="-a -r -m"` (der alte Standard aus 1.1.0) wird als Grandmaster durch
  die automatische Wahl `-a -rr -m` ersetzt (Hinweis im Log) – die Variable kann entfallen.

### Hinzugefügt
- **Hardware-Check** (Seite „Hardware“, `GET /api/hardware`, `?refresh=1` prüft neu):
  erkennt GPS-Empfänger über USB-ID, gpsd und Anschlussart (USB-Modem, USB-Seriell,
  UART), den PPS-Weg (GPIO, DCD, keiner) samt live ankommender Impulse, PTP-fähige
  Netzwerkkarten, VM/Hypervisor, Docker Desktop/WSL, Container-Rechte und RTC. Eine
  Matrix sagt je Funktion „geht / geht mit Änderung / eingeschränkt / geht nicht“ – mit
  erreichbarer Genauigkeit und fertigem Ausschnitt für Compose-Datei, `.env` oder
  Boot-Konfiguration. Läuft im Hintergrund alle 5 Minuten; Ergebnisse auch als Hinweise
  und in `/metrics`.
- **`docker-compose.all-in-one.yml`**: eine Datei zum Kopieren. Aktiv ist, was jeder
  braucht; GPS, PPS, PTP, NTS-Server, Orphan-Verbund, Passwort, Bridge-Alternative und
  Hotplug (`/dev` + `device_cgroup_rules`, Major-Nummern für PPS/PTP aus `.env`) stehen
  als erklärte Blöcke zum Einkommentieren daneben.
- **NTS-Server hinter einem Reverse Proxy**: Zertifikate von Nginx Proxy Manager, Zoraxy,
  certbot & Co. direkt nutzbar (`/certs`, `/etc/letsencrypt`), `NTS_SERVER_NAME`
  (`ntsntpserver`) und `NTS_SERVER_PORT` (`ntsport`). Cert und Key werden geprüft (PEM,
  Größe, passendes Paar) und für chronyd kopiert; bei Erneuerung startet chronyd
  automatisch neu, ein unpassendes Paar ersetzt nie das letzte gültige. Anleitung für
  NPM, Zoraxy, Traefik, nginx und HAProxy im README.
- **NTS-Server-Status** im Dashboard: Name, Port, Aussteller, Restlaufzeit, selbst
  signiert, ob der Name im Zertifikat steht – mit Hinweisen, wenn etwas nicht passt.
- **Grandmaster-Ankündigung**: ntp-gui setzt `clockClass`, `clockAccuracy`, `timeSource`
  und UTC-Offset per `GRANDMASTER_SETTINGS_NP` laufend nach dem Zustand von chrony
  (`clockClass 6`/`timeSource GPS` erst mit stabilem GPS + PPS).
- **PTP-Profile** `default`, `aes67` und `gptp` (`PTP_PROFILE`) sowie
  `PTP_LOG_ANNOUNCE_INTERVAL`, `PTP_ANNOUNCE_RECEIPT_TIMEOUT` und
  `PTP_LOG_MIN_DELAY_REQ_INTERVAL`.
- **Orphan-Modus** für zwei Server im Verbund (`LOCAL_ORPHAN`).
- **Karte „Dienste“** in der Übersicht: Zustand, Neustarts und nächster Versuch je Dienst;
  Hinweis bei Ausfall; Prometheus-Metriken `ntpgui_service_up`,
  `ntpgui_service_restarts_total`, `ntpgui_hardware_capability`, `ntpgui_pps_live`,
  `ntpgui_nts_server_cert_days_left`.
- Erklärung (ⓘ) zu jedem neuen Wert; ein Test stellt sicher, dass kein angezeigter Wert
  ohne Erklärung bleibt.
- Integrationstest: NTS-Server mit selbst signiertem Zertifikat inkl. Zertifikatswechsel,
  Neustart eines abgestürzten gpsd (jetzt 68 Prüfungen; 245 Unittests).

### Geändert
- **Supervisor**: Fällt gpsd, ptp4l oder phc2sys aus, startet nur dieser Dienst neu
  (Pause 5 s, 15 s, 60 s, danach alle 5 min) – NTP läuft weiter. Nur ein Ausfall von
  chronyd oder dem Dashboard beendet den Container. Fehlende Geräte werden alle 30 s
  gesucht und automatisch übernommen. Zustand in `services.json`.
- NTS-Zertifikatspfade nur noch unter `/config`, `/certs` oder `/etc/letsencrypt` –
  siehe „Achtung beim Update“.
- Die Kopien von Zertifikat und Schlüssel gehören `root:_chrony` mit `0640` – chronyd
  kann sie lesen, aber nicht verändern.
- `PHC2SYS_OPTIONS` ist standardmäßig leer und wird passend zur Rolle gewählt.
- Compose-Vorlagen verweisen auf die All-in-one-Datei und die Hardware-Seite;
  `docker-compose.pi-gps.yml` mit Healthcheck, PPS/GPIO-Variante und Kalibrierung über
  das Dashboard; `docker-compose.ptp.yml` und `docker-compose.gps.yml` mit Healthcheck.
- README: neue Abschnitte „Alles in einem“, „Hardware-Check“, „NTS hinter einem Reverse
  Proxy“, „Dienste und Neustarts“, PTP-Rollen und -Profile; bisher fehlende Variablen
  dokumentiert (u. a. `GPS_OPTIONS`, `GPS_PPS_POLL`, `GPS_PPS_OPTIONS`,
  `GPS_PPS_SHM_UNIT`, `PHC_REFCLOCK_OPTIONS`, `CHRONY_LOG`, `GPSD_HOST`,
  `CUSTOM_CHRONY_CONF`, `CUSTOM_PTP4L_CONF`, `MAXUPDATESKEW`).

### Behoben
- **PTP-Grandmaster verteilte nicht die Zeit von chrony/GPS**: phc2sys stellte im
  Master-Betrieb die falsche Uhr. Jetzt `phc2sys -a -rr` – chronyd regelt die
  Systemuhr, phc2sys überträgt sie mit korrektem UTC-Offset auf die Netzwerkkarte. Als
  Slave weiterhin `-a -r` mit chronyd `-x`.
- Ein abgestürzter optionaler Dienst (z. B. gpsd nach Abziehen des Empfängers) stoppte
  den ganzen Container samt NTP.
- README: Kalibrier-Endpunkt heißt `?window=` (`?seconds=` geht weiter), time-pi richtig
  beschrieben (PPS dort direkt in die i226 per `ts2phc`, das ntp-gui nicht unterstützt),
  „Dante“ präzisiert zu „AES67 (Dante nur im AES67-Modus)“.
- `docker-compose.pi-gps.yml` verwies zur Kalibrierung noch auf `chronyc sourcestats`
  statt auf den Assistenten im Dashboard.
- Dashboard zeigte als Version weiterhin 1.1.0.

#### Behoben nach dem Review vor dem Release
- **PTP-Grandmaster:** Nach jedem Neustart von ptp4l (Speichern, Hotplug, Absturz)
  kündigte er bis zu 5 Minuten `clockClass 248` an – die Daten werden jetzt sofort neu
  gesendet. Ein `PHC_REFCLOCK` zusammen mit `PTP_MODE=master` hätte chrony seine eigene
  Zeit zurückgeliefert (Zeitschleife); die Refclock-Zeile entfällt dann mit WARNUNG.
  Das Dashboard warnt, wenn ein Grandmaster mit Hardware-Zeitstempeln ohne phc2sys
  läuft; das Beispiel auf der PTP-Seite setzt `PHC2SYS_ENABLE` jetzt mit.
- **NTS-Zertifikatserneuerung** startet nur noch chronyd neu, nicht mehr gpsd, ptp4l
  und phc2sys.
- Das PTP-Profil (z. B. `gptp` → Layer 2) wird jetzt auch beim Rechte-Check (`NET_RAW`)
  und in der PTP-Statusanzeige berücksichtigt.
- Ungültige Expertenwerte (`PTP_UTC_OFFSET`, `PTP_HOLDOVER_SECONDS`,
  `PTP_TX_TIMESTAMP_TIMEOUT`, `PTP_UDS_ADDRESS`) fallen mit WARNUNG im Log auf den
  Standard zurück.
- Dashboard: keine doppelten NTS-Hinweise mehr, Grammatik „fehlen/fehlt“, PTP-Kachel
  „läuft nicht“ statt „aus“, fehlende (i)-Erklärungen in den Einstellungen, die
  Clients-Seite erfindet keine Server-IP mehr, „/dev vom Host eingehängt“ nur noch im
  Container.
- **Compose-Dateien:** Der Healthcheck liest `WEB_PORT` (wie im Dockerfile) – ein anderer
  Dashboard-Port macht den Container nicht mehr „unhealthy“. In
  `docker-compose.pi-gps.yml` erzeugte die PPS-Variante beim Einkommentieren einen
  doppelten `GPS_DEVICE`-Schlüssel. Die All-in-one-Datei lässt sich mechanisch
  einkommentieren (eingerückte `#` + zwei Leerzeichen); Kopfzeilen erfüllen das Muster
  nicht mehr.
- **Raspberry Pi:** Anleitung für den GPS-HAT korrigiert – beim Pi 3/4 liegt am Header
  sonst der Mini-UART `/dev/ttyS0` (dafür `dtoverlay=disable-bt` und
  `systemctl disable hciuart`), serielle Konsole abschalten, `/dev/serial0` empfohlen;
  beim Pi 5 ist es `/dev/ttyAMA0`.
- **README:** NPM-Zertifikatsordner per `openssl`-Schleife finden (die alte
  `grep`-Suche fand mit DNS-Challenge nichts), die zwei Namen bei NTS hinter einem Proxy
  (Zertifikat = Proxy-Name, `NTS_SERVER_NAME` = Host von ntp-gui) klar getrennt,
  Port-Veröffentlichung für Proxys in Docker, nginx-`map` mit `default`, Bridge-Modus
  verbirgt Client-IPs nur je nach Docker-Setup, `PHC_REFCLOCK` nur als Slave,
  Holdover (`clockClass 7`) und `timeSource NTP` beschrieben, `PTP_UTC_OFFSET`,
  `PTP_HOLDOVER_SECONDS`, `PTP_TX_TIMESTAMP_TIMEOUT` und `PTP_UDS_ADDRESS` dokumentiert.

## [1.1.0] – 2026-11-01

### Hinzugefügt
- **Einstellungen im Dashboard**: Zeitquellen (mit Vorlagen für PTB, Cloudflare,
  Netnod, pool.ntp.org), Zugriff aus dem LAN, NTS, GPS, PTP und das Dashboard selbst.
  Reihenfolge: Dashboard > Umgebungsvariable > Standard; jedes Feld zeigt seine Herkunft
  und lässt sich zurücksetzen. Speichern startet die Zeitdienste per SIGHUP neu, ohne
  den Container neu zu erstellen. Export/Import als JSON, Sperre mit `WEB_READONLY`.
- Dashboard-Passwort im GUI setzen (PBKDF2-Hash in `settings.json`).
- **NTS**: je Quelle zuschaltbar (`NTP_NTS_SERVERS`), Anzeige von Authentifizierung,
  Cookies und Schlüsselaustausch, `nocerttimecheck` für Geräte ohne Echtzeituhr,
  optional eigener NTS-Server (`NTS_SERVER`).
- **GPS-Kalibrierassistent**: misst die Verspätung des USB-Empfängers gegen die genutzten
  Netzwerkquellen und übernimmt Offset, Delay und Rolle (`GPS_SELECT`) per Klick.
- Neue Oberfläche mit sieben Seiten (Übersicht, Zeitquellen, GPS, PTP, Clients,
  Einstellungen, Hilfe), ⓘ-Erklärung zu jedem Wert, Hinweis-Kasten („Was gerade los ist“)
  mit konkreten Handlungsempfehlungen, Glossar und Entscheidungshilfe.
- Zeitquellen mit Auswahlzustand **und Grund** (`chronyc selectdata`), NTP-Details
  (`ntpdata`), Offset-Verlauf je Quelle.
- GPS: Himmelskarte, Signalstärke je Satellit, GNSS-Systeme, DOP-Werte, Satelliten-Verlauf.
- PTP: Voraussetzungs-Check (Host-Netzwerk, Interface, Hardware-Zeitstempel, PTP-Uhr),
  Netzwerkkarten-Übersicht per `ethtool -T`, Kennzahlen und Zustandswechsel aus dem
  ptp4l-Log, weitere Optionen (Delay-Mechanismus, Clock Class, Sync-Intervall).
- Weitere Optionen: `NTP_MINSOURCES`, `NTP_RATELIMIT`, `LEAPSECTZ`.
- Clients: Einrichtungs-Snippets für DHCP-Server und Betriebssysteme.
- Verlauf über 24 h (`HISTORY_SIZE` 8640), wird stündlich und beim Stoppen gesichert.
- Unittests für Einstellungen, Konfigurationserzeugung (inkl. `chronyd -p`),
  Kalibrierung, Hinweise und neue Parser; Integrationstest für Speichern, Neustart,
  Persistenz, CSRF-Schutz und Readonly.
- `docker-compose.pi-gps.yml`: Vorlage für einen Raspberry Pi mit USB-GPS
  (Host-Netzwerk, PTB als Rückfallebene, Vorbereitungen im Kopfkommentar).
- Grafiken im README: Banner, Architektur, DHCP-Ablauf und Genauigkeitsvergleich,
  jeweils in heller und dunkler Variante (`docs/graphics/`, erzeugt von
  `docs/graphics/make_graphics.py`).
- Dieses Changelog.

### Geändert
- chrony behält Messwerte über Neustarts (`dumpdir`, `chronyd -r`).
- Container-Image enthält `ethtool`; Standardwerte stehen nur noch im Einstellungsschema.

## [1.0.0] – 2026-11-01

Erste Veröffentlichung.

### Hinzugefügt
- NTP-Server mit chronyd, konfiguriert über Umgebungsvariablen oder eine eigene
  `chrony.conf` unter `/config`.
- Web-Dashboard ohne externe Abhängigkeiten: Status, Offset-Verlauf, Zeitquellen,
  NTP-Clients, GPS-Fix, PTP-Zustand und aktive Konfiguration, hell und dunkel.
- GPS als Referenzuhr über gpsd (z. B. VK-162 per USB), optional mit PPS.
- PTP (IEEE 1588) mit ptp4l und phc2sys, als Master, Slave oder PTP→NTP-Brücke.
- JSON-API, Prometheus-Endpunkt `/metrics` und `/healthz` für den Healthcheck.
- Optionale HTTP-Basic-Auth für das Dashboard.
- Supervisor, der jeden Dienst überwacht und den Container bei einem Ausfall
  beendet, damit die Restart-Policy greift.
- Automatische Erkennung von fehlendem `CAP_SYS_TIME` (chronyd läuft dann mit `-x`).
- Compose-Beispiele für Standard-, GPS- und PTP-Betrieb.
- CI mit Unittests und Integrationstest gegen das gebaute Image; Release-Workflow,
  der das Image für amd64 und arm64 nach ghcr.io veröffentlicht.

[1.11.0]: https://github.com/mgc20/ntp-gui/compare/v1.10.0...v1.11.0
[1.10.0]: https://github.com/mgc20/ntp-gui/compare/v1.9.0...v1.10.0
[1.9.0]: https://github.com/mgc20/ntp-gui/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/mgc20/ntp-gui/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/mgc20/ntp-gui/compare/v1.6.3...v1.7.0
[1.6.3]: https://github.com/mgc20/ntp-gui/compare/v1.6.2...v1.6.3
[1.6.2]: https://github.com/mgc20/ntp-gui/compare/v1.6.1...v1.6.2
[1.6.1]: https://github.com/mgc20/ntp-gui/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/mgc20/ntp-gui/compare/v1.5.5...v1.6.0
[1.5.5]: https://github.com/mgc20/ntp-gui/compare/v1.5.4...v1.5.5
[1.5.4]: https://github.com/mgc20/ntp-gui/compare/v1.5.3...v1.5.4
[1.5.3]: https://github.com/mgc20/ntp-gui/compare/v1.5.2...v1.5.3
[1.5.2]: https://github.com/mgc20/ntp-gui/compare/v1.5.1...v1.5.2
[1.5.1]: https://github.com/mgc20/ntp-gui/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/mgc20/ntp-gui/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/mgc20/ntp-gui/compare/v1.3.2...v1.4.0
[1.3.2]: https://github.com/mgc20/ntp-gui/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/mgc20/ntp-gui/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/mgc20/ntp-gui/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/mgc20/ntp-gui/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/mgc20/ntp-gui/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/mgc20/ntp-gui/releases/tag/v1.0.0
