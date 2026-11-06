# Changelog

Alle nennenswerten Änderungen an ntp-gui. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/).

## [1.5.4] – 2026-11-06

Schwerpunkt: GPS bei schwachem Empfang ruhig – keine Positions-Fehlalarme, weniger Ereignisse, stabile
Fehlerschranke (Rückmeldung: Diagnosepaket 1.5.3, VK-162 drinnen ohne PPS). Dazu die Allan-Abweichung auf
der Seite „Uhrqualität“, Reverse Proxy per Klick eintragen und die Restpunkte aus der Abschlussprüfung.

### Behoben
- **Kein Fehlalarm „GNSS-Störung: Position um 160 m gesprungen“ mehr bei schwachem Empfang.** Für den
  Positionssprung zählen nur noch verlässliche Fixe – 3D, mindestens 5 genutzte Satelliten, HDOP höchstens 4
  (ohne HDOP: eph höchstens 50 m) –, für die Referenz wie für den Vergleich; 2D-Fixe und schlechte
  Geometrie werden ignoriert. Ein Sprung zählt erst, wenn er über mindestens 5 gute Fixe und 50 s anhält.
  Ein echter Spoofer (sauberes Signal, gute Geometrie, bleibender Sprung) wird weiter in unter einer
  Minute erkannt. Ist die Störung schon gemeldet, halten auch schwache Fixe außerhalb der Schwelle sie
  aufrecht – „GNSS wieder unauffällig“ kommt nicht mehr, nur weil ein Spoofer auf schlechte Geometrie
  umschaltet. Meldet gpsd keine Satellitenliste (kein SKY im Abfragefenster, NMEA ohne GSA), gilt die
  Satellitenzahl als unbekannt statt als 0 – sonst wäre die Positionsprüfung still dauerhaft aus. Replay der Fix-Folge aus dem Paket (4 Tage, Positionsstreuung nach HDOP): vorher rund 40
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
  wartet nicht auf eine laufende Rechnung. Aus den Stundenmitteln im Paket der Rückmeldung: rund 2 ppb über
  1 h, 5 ppb über 6 h.
- **Reverse Proxy per Klick eintragen** (Rückmeldung: Der Hinweis zeigte die Adresse des Proxys, das
  richtige Eintragen gelang trotzdem tagelang nicht). Die Hinweise „Reverse Proxy erkannt, aber nicht
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

## [1.5.3] – 2026-11-04

Schwerpunkt: Ein Holdover-Test läuft bis zum Ende – keine Automatik startet chronyd mehr dazwischen.

### Behoben
- **Holdover-Test wird von Automatiken nicht mehr abgebrochen** (Rückmeldung: 6-h-Test ohne GPS und
  Netzquellen, nach 4 h 35 min abgebrochen, weil die automatische Anpassung der GPS-Fehlerschranke
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
  sich gleiche Zeilen, Vorschau und Paket entstehen in einem Durchgang. Mit einer echten
  10-Minuten-Aufzeichnung (2347 Einträge, 1,5 MB) brauchten Vorschau und Download bisher
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
