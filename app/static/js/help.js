// Alle Erklärungen an einer Stelle. Die ⓘ-Knöpfe im Dashboard und die
// Hilfeseite nutzen dieselben Texte. **fett** und `code` werden formatiert.

export const HELP = {
  // ---------------------------------------------------------------- Grundlagen
  ntp: {
    title: "NTP – Network Time Protocol",
    text: "Das Standardprotokoll, mit dem praktisch jedes Gerät seine Uhr stellt: PCs, Server, "
      + "Router, Drucker, Kameras, Smart-Home. Ein Client fragt einen Server nach der Zeit, misst "
      + "dabei die Laufzeit der Pakete und rechnet sie heraus. Im LAN erreicht NTP typisch "
      + "**0,1–1 ms** Genauigkeit, über das Internet **1–50 ms**, je nach Leitung.",
  },
  stratum: {
    title: "Stratum",
    text: "Wie viele Schritte eine Uhr von einer echten Referenz entfernt ist. **Stratum 0** ist "
      + "die Referenz selbst (GPS, Atomuhr). **Stratum 1** ist ein Server, der direkt daran hängt "
      + "– z. B. dieser Server mit GPS. Wer einen Stratum-1-Server fragt, wird Stratum 2, und so "
      + "weiter. Stratum sagt nichts direkt über die Genauigkeit, aber kleiner ist in der Regel "
      + "besser. **16** bedeutet: nicht synchronisiert.",
  },
  system_offset: {
    title: "Abweichung der Systemuhr",
    text: "Wie weit die Uhr dieses Servers gerade von der gewählten Referenz entfernt ist. chrony "
      + "regelt sie langsam auf null, statt sie springen zu lassen. **Negativ** heißt: die "
      + "Systemuhr geht vor. Werte unter 1 ms sind für ein Heimnetz sehr gut, mit GPS+PPS sind "
      + "es Mikrosekunden.",
  },
  rms_offset: {
    title: "RMS-Abweichung",
    text: "Der langfristige Mittelwert der Abweichung (quadratisches Mittel). Zeigt, wie ruhig "
      + "die Uhr im Schnitt läuft – ein einzelner Ausreißer fällt hier kaum ins Gewicht.",
  },
  frequency: {
    title: "Frequenzfehler",
    text: "Jeder Quarz geht etwas zu schnell oder zu langsam. chrony misst das und gleicht es "
      + "laufend aus. Angabe in **ppm** (Millionstel): 1 ppm sind 86 ms pro Tag. Werte bis "
      + "±100 ppm sind normal. Wichtig ist, dass der Wert stabil bleibt – große Sprünge deuten "
      + "auf Temperaturschwankungen oder eine zweite Software hin, die auch an der Uhr dreht.",
  },
  skew: {
    title: "Skew",
    text: "Wie sicher sich chrony beim Frequenzfehler ist (Fehlerschranke in ppm). Kleiner ist "
      + "besser; direkt nach dem Start ist der Wert hoch und sinkt mit jeder Messung.",
  },
  root_delay: {
    title: "Root Delay",
    text: "Die gesamte Paketlaufzeit hin und zurück bis zur Stratum-0-Referenz, über alle "
      + "Zwischenstationen. Über das Internet typisch 5–50 ms, mit GPS nahe null.",
  },
  root_dispersion: {
    title: "Root Dispersion",
    text: "Die aufsummierte Unsicherheit aller Zwischenstationen bis zur Referenz: Messfehler, "
      + "Frequenzfehler, Zeit seit der letzten Messung. Wächst, wenn eine Quelle länger nicht "
      + "gefragt wurde.",
  },
  uncertainty: {
    title: "Maximale Abweichung (Root Distance)",
    text: "Die ehrlichste Zahl im Dashboard: **halbe Root Delay + Root Dispersion**. So weit kann "
      + "die Uhr dieses Servers im schlimmsten Fall von der echten Zeit (UTC) entfernt sein. "
      + "Über das Internet einige Millisekunden, mit GPS+PPS Mikrosekunden.",
  },
  leap: {
    title: "Schaltsekunden-Status",
    text: "„Normal“ ist der Regelfall. „Insert/Delete second“ kündigt eine Schaltsekunde zum "
      + "Monatsende an. „Not synchronised“ heißt: noch keine gültige Zeit.",
  },
  update_interval: {
    title: "Aktualisierungsintervall",
    text: "Wie viele Sekunden zwischen den letzten beiden Korrekturen der Uhr lagen.",
  },
  island: {
    title: "Inselbetrieb (local stratum)",
    text: "Ist keine Quelle erreichbar, kann der Server trotzdem seine eigene Uhrzeit verteilen – "
      + "mit absichtlich schlechtem Stratum (Standard 10). So bleiben alle Geräte im LAN "
      + "untereinander einig, auch wenn das Internet ausfällt. Sobald eine echte Quelle zurück "
      + "ist, übernimmt die wieder.",
  },
  minsources: {
    title: "Mindestanzahl übereinstimmender Quellen",
    text: "chrony stellt die Uhr erst, wenn mindestens so viele Quellen dieselbe Zeit nennen. "
      + "Mit 2 oder 3 kann eine einzelne falsche Quelle (gestört, manipuliert, falsch "
      + "konfiguriert) die Zeit nicht verbiegen. Dafür müssen auch so viele erreichbar sein.",
  },
  dhcp42: {
    title: "DHCP Option 42",
    text: "Damit Clients diesen Server automatisch kennen: Im DHCP-Server (meist der Router) die "
      + "Option 42 „NTP-Server“ auf die Adresse dieses Servers setzen. Geräte übernehmen sie beim "
      + "nächsten Verbinden. Nicht jedes Gerät wertet sie aus – Windows z. B. ignoriert sie und "
      + "braucht eine Gruppenrichtlinie oder `w32tm`.",
  },

  // ------------------------------------------------------------ Quellenliste
  source_type: {
    title: "Typ der Quelle",
    text: "**server**: ein einzelner NTP-Server. **pool**: ein Name hinter dem mehrere Server "
      + "stehen, chrony nimmt sich einige davon. **peer**: ein gleichrangiger Server, der sich "
      + "gegenseitig abgleicht. **refclock**: eine lokal angeschlossene Referenzuhr wie GPS, "
      + "PPS oder die PTP-Uhr einer Netzwerkkarte.",
  },
  poll: {
    title: "Abfrageintervall",
    text: "Wie oft chrony diese Quelle fragt. Am Anfang oft, später seltener (bis 17 min), wenn "
      + "die Uhr stabil läuft – das schont die Server. Refclocks werden alle paar Sekunden gelesen.",
  },
  reach: {
    title: "Erreichbarkeit",
    text: "Wie viele der **letzten acht** Anfragen beantwortet wurden. 100 % heißt: alle acht. "
      + "Einzelne Lücken sind unkritisch (verlorene UDP-Pakete). 0 % heißt: die Quelle antwortet "
      + "gar nicht – DNS, Firewall (Port 123/udp) oder der Server selbst.",
  },
  last_rx: {
    title: "Letzte Antwort",
    text: "Wie lange die letzte gültige Antwort dieser Quelle zurückliegt.",
  },
  source_offset: {
    title: "Offset der Quelle",
    text: "Wie weit diese Quelle von der eigenen Systemuhr entfernt ist (letzte Messung). "
      + "**Positiv** heißt: die Systemuhr geht gegenüber dieser Quelle vor. Bei einem GPS ohne "
      + "Kalibrierung ist ein fester Wert von einigen Dutzend Millisekunden typisch.",
  },
  jitter: {
    title: "Jitter (Streuung)",
    text: "Wie stark die Messwerte dieser Quelle schwanken (Standardabweichung). Kleiner ist "
      + "besser. Internet-Server liegen bei 0,1–5 ms, USB-GPS bei 1–5 ms, GPS mit PPS bei "
      + "wenigen Mikrosekunden.",
  },
  interval: {
    title: "Vertrauensbereich",
    text: "Der Bereich, in dem die echte Zeit laut dieser Quelle liegt. chrony sucht den "
      + "Bereich, in dem sich die meisten Quellen überschneiden – wer außerhalb liegt, wird als "
      + "Falseticker aussortiert. Ein sehr breiter Bereich (große angenommene Unsicherheit) "
      + "führt dagegen dazu, dass die Quelle nicht mitzählt.",
  },
  samples: {
    title: "Messwerte",
    text: "Wie viele Messungen chrony für diese Quelle gerade in der Statistik hält und über "
      + "welchen Zeitraum. Mehr Werte = verlässlichere Schätzung.",
  },
  score: {
    title: "Bewertung",
    text: "Wie gut chrony die Quelle im Vergleich bewertet (kleiner = besser). Damit wird "
      + "verhindert, dass ständig zwischen ähnlich guten Quellen hin und her gewechselt wird.",
  },
  hostname_vs_ip: {
    title: "Name und Adresse",
    text: "chrony arbeitet mit IP-Adressen. Der Name dahinter ist der, der in den Einstellungen "
      + "steht. Bei einem Pool zeigt jede Zeile einen anderen Server aus dem Pool.",
  },

  // ---------------------------------------------------------- Auswahl-Zustände
  state_best: {
    title: "Ausgewählt (*)",
    text: "Die beste Quelle. Nach ihr richtet chrony die Uhr vorrangig aus.",
  },
  state_combined: {
    title: "Kombiniert (+)",
    text: "Eine gute Quelle, die **mitgenutzt** wird: chrony mittelt sie zusammen mit der "
      + "ausgewählten. Mehrere kombinierte Quellen machen die Zeit stabiler. Das ist ein "
      + "guter Zustand.",
  },
  state_not_combined: {
    title: "Nicht kombiniert (−)",
    text: "Die Quelle ist erreichbar und plausibel, wird aber gerade **nicht mitgenutzt**, weil "
      + "sie deutlich schlechter ist als die besten (größere Unsicherheit oder Streuung). Das "
      + "ist kein Fehler. Die Spalte „Grund“ nennt die Details.",
  },
  state_falseticker: {
    title: "Falseticker (x)",
    text: "Die Quelle widerspricht der Mehrheit: Ihr Vertrauensbereich überschneidet sich nicht "
      + "mit dem der anderen. chrony ignoriert sie, damit sie die Zeit nicht verbiegt. Bei einem "
      + "GPS ist der Grund fast immer ein fehlender Offset – siehe GPS-Kalibrierung.",
  },
  state_jittery: {
    title: "Zu unruhig (~)",
    text: "Die Messwerte dieser Quelle schwanken zu stark, um sie zu nutzen. Häufig bei "
      + "überlasteten Leitungen oder WLAN.",
  },
  state_unreachable: {
    title: "Nicht erreichbar (?)",
    text: "Keine gültige Antwort in letzter Zeit. Prüfen: Name auflösbar? Port 123/udp nach "
      + "außen offen? Bei Refclocks: liefert das Gerät Daten?",
  },
  sel_noselect: {
    title: "Nur beobachten (N)",
    text: "Mit der Option „noselect“ konfiguriert: wird gemessen und angezeigt, aber nie zur "
      + "Synchronisation genutzt. Praktisch zum Kalibrieren oder Vergleichen.",
  },
  sel_unsynchronised: {
    title: "Quelle selbst nicht synchron (s)",
    text: "Die Quelle meldet, dass sie selbst keine gültige Zeit hat (Stratum 16 oder "
      + "Schaltsekunden-Status „nicht synchron“).",
  },
  sel_missing_samples: {
    title: "Zu wenige Messwerte (M)",
    text: "Noch nicht genug Messungen für eine Bewertung – kurz nach dem Start normal.",
  },
  sel_distance: {
    title: "Zu weit entfernt (d)",
    text: "Die Unsicherheit der Quelle (Root Distance) ist größer als erlaubt (maxdistance).",
  },
  sel_large_distance: {
    title: "Unsicherheit viel größer als bei den besten (D)",
    text: "Die Quelle ist plausibel, aber ihre **angenommene Unsicherheit** ist um ein "
      + "Vielfaches größer als die der ausgewählten Quelle – deshalb wird sie nicht mitgenutzt. "
      + "Typisch für ein GPS mit dem vorsichtigen Standard-Delay von 0,2 s: chrony nimmt an, "
      + "die GPS-Zeit könne bis zu 100 ms daneben liegen, während Internet-Server auf wenige "
      + "Millisekunden genau sind. Nach der Kalibrierung den vorgeschlagenen kleineren Delay "
      + "übernehmen.",
  },
  sel_jittery: {
    title: "Zu unruhig (~)",
    text: "Die Streuung der Messwerte ist zu groß im Vergleich zu den anderen Quellen.",
  },
  sel_waits_others: {
    title: "Wartet auf andere (w/W)",
    text: "Für die Auswahl braucht chrony erst Messwerte weiterer Quellen (z. B. wegen "
      + "„Mindestanzahl übereinstimmender Quellen“).",
  },
  sel_stale: {
    title: "Veraltet (S)",
    text: "Die letzte Messung ist zu alt, um noch zu zählen.",
  },
  sel_orphan: {
    title: "Orphan (O)",
    text: "Die Quelle ist im Orphan-Modus und hat einen höheren Rang als dieser Server.",
  },
  sel_not_trusted: {
    title: "Nicht vertrauenswürdig (T)",
    text: "Es gibt Quellen mit der Option „trust“, und diese hier passt nicht zu ihnen.",
  },
  sel_not_preferred: {
    title: "Nicht bevorzugt (P)",
    text: "Eine andere Quelle ist mit „prefer“ als erste Wahl markiert und plausibel – diese hier "
      + "wird deshalb nicht genutzt. Fällt die bevorzugte aus, springt sie ein.",
  },
  sel_waits_update: {
    title: "Wartet auf neue Messung (U)",
    text: "Seit der letzten Auswahl gab es keine neue Messung dieser Quelle.",
  },
  sel_falseticker: {
    title: "Falseticker (x)",
    text: "Widerspricht der Mehrheit der Quellen und wird ignoriert.",
  },
  sel_best: { title: "Ausgewählt (*)", text: "Die beste verfügbare Quelle." },
  sel_combined: { title: "Kombiniert (+)", text: "Wird zusammen mit der besten Quelle genutzt." },
  sel_not_combined: { title: "Nicht kombiniert (−)", text: "Plausibel, aber schlechter als die besten." },

  // ---------------------------------------------------------- NTP-Details
  peer_delay: {
    title: "Paketlaufzeit (Peer Delay)",
    text: "Wie lange eine Anfrage zu diesem Server und zurück braucht. Davon hängt die "
      + "Genauigkeit ab: Die Hälfte davon ist die maximale Unsicherheit, weil NTP nur annehmen "
      + "kann, dass Hin- und Rückweg gleich lang sind.",
  },
  peer_dispersion: {
    title: "Peer Dispersion",
    text: "Geschätzter Messfehler dieser einzelnen Messung.",
  },
  response_time: {
    title: "Antwortzeit des Servers",
    text: "Wie lange der Server intern zum Antworten gebraucht hat (zwischen Empfang und "
      + "Versand). Ist bereits aus der Laufzeit herausgerechnet.",
  },
  precision: {
    title: "Präzision",
    text: "Wie fein die Uhr des Servers auflöst. Angabe als Zweierpotenz: −25 sind etwa 30 ns.",
  },
  jitter_asymmetry: {
    title: "Asymmetrie des Jitters",
    text: "Ob Schwankungen eher auf dem Hin- (−) oder Rückweg (+) entstehen. Nahe ±0,5 deutet "
      + "auf eine einseitig belastete Leitung hin, z. B. ein ausgelasteter Upload.",
  },
  ntp_tests: {
    title: "NTP-Prüfungen",
    text: "chrony prüft jede Antwort mit zehn Tests in drei Gruppen (Paketformat, Plausibilität, "
      + "Synchronisation des Servers). „10/10“ heißt: alles in Ordnung. Fällt ein Test durch, "
      + "wird die Antwort verworfen.",
  },
  interleaved: {
    title: "Interleaved-Modus",
    text: "Ein Verfahren, bei dem der Server den genauen Sendezeitpunkt im nächsten Paket "
      + "nachliefert. Bringt nur mit Hardware-Zeitstempeln etwas.",
  },
  timestamping: {
    title: "Zeitstempel",
    text: "Wer den Empfangs- und Sendezeitpunkt festhält: **Daemon** (das Programm, ungenau), "
      + "**Kernel** (Betriebssystem, Standard) oder **Hardware** (die Netzwerkkarte, am "
      + "genauesten).",
  },
  packets: {
    title: "Pakete",
    text: "Gesendete Anfragen, empfangene Antworten, davon gültige und davon gute (für die "
      + "Statistik genutzte).",
  },

  // ---------------------------------------------------------------- NTS
  nts: {
    title: "NTS – Network Time Security",
    text: "Normales NTP ist unverschlüsselt und nicht signiert: Wer im Netz dazwischen sitzt, "
      + "kann eine falsche Zeit unterschieben. Mit falscher Zeit lassen sich z. B. abgelaufene "
      + "Zertifikate wieder gültig machen. **NTS** schützt davor: Beim ersten Kontakt tauschen "
      + "Client und Server per TLS (TCP-Port **4460**) Schlüssel aus, danach trägt jedes "
      + "NTP-Paket einen Echtheitsnachweis. Die Genauigkeit bleibt gleich. Server mit NTS: "
      + "`ptbtime1.ptb.de`, `ptbtime2.ptb.de`, `ptbtime3.ptb.de`, `time.cloudflare.com`, "
      + "`nts.netnod.se`. Als Client im Heimnetz sehr empfehlenswert.",
  },
  nts_server: {
    title: "NTS für die eigenen Clients",
    text: "Dieser Server kann NTS auch selbst anbieten. Das lohnt sich im Heimnetz selten: Es "
      + "braucht ein TLS-Zertifikat, dem die Clients vertrauen, und Clients, die NTS sprechen "
      + "(chrony, NTPsec, einige Router). **Windows und macOS können kein NTS.** Für die "
      + "meisten Geräte bleibt es beim normalen NTP, das parallel weiterläuft.",
  },
  nts_cookies: {
    title: "NTS-Cookies",
    text: "Nach dem Schlüsselaustausch hält der Client einen Vorrat an Einmal-Cookies. Jede "
      + "Anfrage verbraucht einen, jede Antwort bringt einen neuen. 8 ist voll. 0 bedeutet: "
      + "Der Schlüsselaustausch muss wiederholt werden.",
  },
  nts_ke: {
    title: "Schlüsselaustausch (NTS-KE)",
    text: "Wann der letzte Schlüsselaustausch per TLS stattfand und wie viele Versuche nötig "
      + "waren. Schlägt er wiederholt fehl, ist meist TCP-Port 4460 gesperrt oder die Uhr beim "
      + "Start so falsch, dass das Zertifikat abgelehnt wird.",
  },
  nocerttimecheck: {
    title: "Zertifikatszeit beim Start",
    text: "TLS-Zertifikate sind nur in einem Zeitfenster gültig. Ein Raspberry Pi ohne "
      + "Echtzeituhr startet mit falscher Zeit und würde jedes Zertifikat ablehnen – ein "
      + "Henne-Ei-Problem. Diese Option erlaubt beim ersten Abgleich eine Ausnahme.",
  },

  // ---------------------------------------------------------------- GPS
  gps: {
    title: "GPS als Zeitquelle",
    text: "GPS-Satelliten tragen Atomuhren und senden deren Zeit. Ein Empfänger bekommt daraus "
      + "die Zeit unabhängig vom Internet – damit wird dieser Server zum **Stratum-1-Server**.",
  },
  gps_value: {
    title: "Was bringt GPS – mit und ohne PPS?",
    text: "**USB-GPS ohne PPS** (z. B. VK-162): nach der Kalibrierung etwa **1–10 ms** genau – "
      + "nicht genauer als die PTB über eine gute Festnetzleitung. Der Gewinn: Die Zeit stimmt "
      + "auch **ohne Internet**, sie ist **unabhängig** von fremden Servern, und bei **Mobilfunk, "
      + "Starlink oder Satellit** (hohe, schwankende Laufzeiten, NTP-Fehler 10–50 ms) ist sie "
      + "deutlich besser. **GPS mit PPS** (Sekundenimpuls über GPIO oder seriell): **unter 1 µs** – "
      + "tausendfach genauer, die Grundlage für ernsthaftes PTP.",
  },
  gps_offset: {
    title: "Warum ein USB-GPS einen Offset braucht",
    text: "Der Empfänger kennt die Zeit genau, meldet sie aber als Textzeile (NMEA) – und die "
      + "kommt **verspätet** an: Der Empfänger rechnet erst, dann wird die Zeile seriell "
      + "übertragen, dann gepuffert über USB. Diese Verspätung ist pro Empfänger, Firmware und "
      + "Baudrate **ziemlich konstant**, typisch 20–150 ms. chrony kann sie nicht selbst "
      + "erkennen. Der Offset gleicht sie aus: Man lässt das GPS einige Stunden neben guten "
      + "Internet-Servern laufen, misst die mittlere Differenz und trägt sie als Offset ein. "
      + "Das macht der Kalibrier-Assistent automatisch.",
  },
  gps_delay: {
    title: "Angenommene Unsicherheit (Delay)",
    text: "Wie sehr chrony der GPS-Zeit misstraut. Der Standard **0,2 s** ist vorsichtig – damit "
      + "wird ein unkalibriertes GPS nie zum Problem, aber auch nie genutzt, solange gute "
      + "Internet-Server da sind (Zustand „D“). Nach der Kalibrierung passt ein Wert, der die "
      + "echte Streuung abdeckt (typisch 0,005–0,02 s).",
  },
  gps_recalibrate: {
    title: "Wann neu kalibrieren?",
    text: "Nach einem Wechsel von Empfänger, USB-Port/Hub, Firmware oder Baudrate. Sonst bleibt "
      + "der Wert über Monate stabil. Der Assistent misst laufend weiter – zeigt er eine "
      + "Abweichung über ~2 ms, lohnt sich ein neuer Vorschlag.",
  },
  fix: {
    title: "Fix",
    text: "**Kein Fix**: zu wenige Satelliten. **2D**: Position ohne Höhe (mind. 3 Satelliten). "
      + "**3D**: volle Position (mind. 4 Satelliten). Für die Zeit genügt ein Satellit, wenn die "
      + "Position bekannt ist – gpsd liefert Zeit aber erst ab einem Fix zuverlässig.",
  },
  satellites: {
    title: "Satelliten",
    text: "**Genutzt** sind die Satelliten, aus denen der Empfänger Position und Zeit berechnet; "
      + "**sichtbar** alle, die er empfängt. 6–12 genutzte sind gut. Wenige deuten auf "
      + "eingeschränkte Sicht zum Himmel hin (Fensterbank, Keller).",
  },
  dop: {
    title: "DOP (Dilution of Precision)",
    text: "Wie günstig die Satelliten am Himmel verteilt sind. **Unter 2** sehr gut, 2–5 gut, über "
      + "10 schlecht. HDOP = horizontal, VDOP = vertikal, PDOP = räumlich, TDOP = Zeit.",
  },
  snr: {
    title: "Signalstärke (SNR)",
    text: "Signal-Rausch-Abstand in dB-Hz. **Über 35** stark, 25–35 brauchbar, unter 20 kaum "
      + "nutzbar. Eine bessere Antennenposition (Fenster, draußen, Abstand zu Elektronik) hilft "
      + "am meisten.",
  },
  skyplot: {
    title: "Himmelskarte",
    text: "Wo die Satelliten stehen: Mitte = direkt über dir (90° Elevation), Rand = Horizont. "
      + "Oben ist Norden. Ausgefüllte Punkte werden genutzt. Fehlen ganze Himmelsrichtungen, "
      + "verdeckt dort etwas die Sicht.",
  },
  gnss: {
    title: "Satellitensysteme",
    text: "GPS (USA), GLONASS (Russland), Galileo (EU), BeiDou (China), dazu SBAS-Korrektursignale "
      + "(EGNOS in Europa). Ältere Empfänger wie der VK-162 (u-blox 7) nutzen ab Werk nur GPS; "
      + "mehrere Systeme gleichzeitig können erst neuere Module (u-blox M8 und später).",
  },
  time_error: {
    title: "Zeitfehler des Empfängers",
    text: "Die vom Empfänger geschätzte Unsicherheit seiner Zeitangabe (ept). Sagt nichts über "
      + "die USB-Verspätung, die erst die Kalibrierung ausgleicht.",
  },
  pps: {
    title: "PPS – Pulse per Second",
    text: "Ein elektrischer Impuls genau zu Beginn jeder Sekunde, auf Mikrosekunden genau. Die "
      + "NMEA-Zeile sagt, **welche** Sekunde es ist, der PPS sagt, **wann** sie beginnt. Am "
      + "Raspberry Pi kommt er über einen GPIO-Pin (`dtoverlay=pps-gpio,gpiopin=18`) und erscheint "
      + "als `/dev/pps0`. USB-Empfänger wie der VK-162 haben keinen PPS-Ausgang.",
  },
  cold_start: {
    title: "Kaltstart",
    text: "Ohne gespeicherte Satellitendaten braucht ein Empfänger bis zu 15 Minuten bis zum "
      + "ersten Fix. Danach reichen meist Sekunden.",
  },
  gps_role: {
    title: "Rolle des GPS bei der Auswahl",
    text: "**Automatisch**: chrony vergleicht GPS und Internet-Server und nimmt das Beste. "
      + "**Bevorzugen**: GPS ist erste Wahl, solange es plausibel ist – sinnvoll bei schlechter "
      + "oder fehlender Internetleitung. **Nur beobachten**: wird gemessen, nie genutzt.",
  },

  // ---------------------------------------------------------------- PTP
  ptp: {
    title: "PTP – Precision Time Protocol (IEEE 1588)",
    text: "Ein Protokoll für Zeit im LAN mit **Nanosekunden**-Genauigkeit. Der Trick: Die "
      + "Netzwerkkarte selbst stempelt jedes Paket beim Senden und Empfangen, statt dass "
      + "Software das tut. Dadurch fallen alle Verzögerungen in Betriebssystem und Treibern weg. "
      + "Gebraucht wird PTP in der Industrie, im Rundfunk (AES67, Dante), im Mobilfunk und im "
      + "Hochfrequenzhandel. **Im Homelab** ist es spannend für Audio-over-IP, Messaufbauten "
      + "und zum Lernen. Für normale PCs reicht NTP völlig.",
  },
  ptp_vs_ntp: {
    title: "PTP oder NTP?",
    text: "**NTP**: jedes Gerät kann es, Millisekunden-Genauigkeit, über das Internet nutzbar. "
      + "**PTP**: nur im LAN, braucht Hardware-Unterstützung auf beiden Seiten, dafür "
      + "Nanosekunden. Dieser Server macht beides gleichzeitig: PTP für Geräte, die es können, "
      + "NTP für alle anderen.",
  },
  ptp_requirements: {
    title: "Was PTP braucht",
    text: "1. Eine **Netzwerkkarte mit Hardware-Zeitstempeln** und eigener PTP-Uhr (prüfen mit "
      + "`ethtool -T eth0`: „hardware-transmit“, „hardware-receive“ und „PTP Hardware Clock: 0“). "
      + "Gut: Intel i210/i211/i225/i226/X550, Raspberry Pi CM4/CM5. **Virtuelle Karten in VMs "
      + "können das nicht.** 2. Den Container im **Host-Netzwerk** (`network_mode: host`), mit "
      + "`cap_add: [NET_ADMIN, NET_RAW]` und dem Gerät `/dev/ptp0`. 3. Eine gute **Referenz** "
      + "– sinnvoll ist PTP als Grandmaster nur mit GPS **plus PPS**; sonst verteilt man mit "
      + "Nanosekunden-Präzision eine Zeit, die auf Millisekunden falsch ist. 4. **Clients mit "
      + "PTP-Unterstützung** (Linux mit linuxptp, viele Netzwerk- und Audiogeräte). 5. Am besten "
      + "**Switches mit PTP-Unterstützung**; einfache Switches gehen, kosten aber Genauigkeit.",
  },
  grandmaster: {
    title: "Grandmaster",
    text: "Die Uhr, nach der sich alle PTP-Teilnehmer richten. Welche das ist, handeln die Geräte "
      + "automatisch aus (Best Master Clock Algorithm): Priority 1, Clock Class, Genauigkeit, "
      + "Priority 2, zuletzt die Kennung. Mit GPS sollte dieser Server Grandmaster sein.",
  },
  port_state: {
    title: "Port-Zustand",
    text: "**MASTER**: gibt den Takt vor. **SLAVE**: übernimmt den Takt eines Masters. "
      + "**LISTENING**: hört zu, ob es einen Master gibt. **UNCALIBRATED**: hat einen Master "
      + "gefunden und gleicht sich gerade an. **PASSIVE**: es gibt einen besseren Master, dieser "
      + "Port schweigt. **FAULTY**: Fehler, meist fehlende Hardware-Zeitstempel. "
      + "**INITIALIZING/DISABLED**: startet oder ist aus.",
  },
  offset_from_master: {
    title: "Offset zum Master",
    text: "Wie weit die PTP-Uhr dieses Geräts von der des Grandmasters entfernt ist. Mit "
      + "Hardware-Zeitstempeln sind wenige Dutzend Nanosekunden normal.",
  },
  mean_path_delay: {
    title: "Mittlere Laufzeit",
    text: "Die gemessene Laufzeit der Pakete zum Master (eine Richtung). Im LAN wenige "
      + "Mikrosekunden. PTP rechnet sie heraus und nimmt an, dass Hin- und Rückweg gleich sind.",
  },
  steps_removed: {
    title: "Steps Removed",
    text: "Wie viele PTP-Stationen (Boundary Clocks) zwischen diesem Gerät und dem Grandmaster "
      + "liegen. 0 heißt: dieses Gerät ist der Grandmaster.",
  },
  clock_class: {
    title: "Clock Class",
    text: "Wie gut ein Takt ist. **6**: an eine Referenz wie GPS gekoppelt. **7**: war gekoppelt, "
      + "läuft gerade frei. **248**: Standard, keine Referenz bekannt. Kleinere Zahlen gewinnen "
      + "die Grandmaster-Wahl.",
  },
  clock_accuracy: {
    title: "Clock Accuracy",
    text: "Angegebene Genauigkeit als Code: 0x20 = 25 ns, 0x21 = 100 ns, 0x22 = 250 ns, "
      + "0x23 = 1 µs … 0xFE = unbekannt.",
  },
  ptp_domain: {
    title: "Domain",
    text: "Trennt mehrere PTP-Netze im selben LAN. Alle Teilnehmer einer Gruppe brauchen dieselbe "
      + "Nummer; 0 ist Standard.",
  },
  ptp_transport: {
    title: "Transport",
    text: "Wie PTP-Pakete reisen: als UDP über IPv4 (Standard), IPv6 oder direkt als "
      + "Ethernet-Rahmen (L2). Alle Teilnehmer müssen dasselbe nutzen.",
  },
  utc_offset: {
    title: "UTC-Offset",
    text: "PTP zählt in TAI (Atomzeit ohne Schaltsekunden). Derzeit liegt TAI 37 Sekunden vor "
      + "UTC – dieser Wert wird mitgeteilt, damit Clients umrechnen können.",
  },
  phc: {
    title: "PTP-Hardwareuhr (PHC)",
    text: "Eine eigene Uhr auf der Netzwerkkarte, z. B. `/dev/ptp0`. ptp4l stellt diese Uhr, "
      + "phc2sys überträgt sie bei Bedarf auf die Systemuhr.",
  },
  phc2sys: {
    title: "phc2sys",
    text: "Kopiert die Zeit von der PTP-Uhr der Netzwerkkarte auf die Systemuhr (oder umgekehrt). "
      + "Als PTP-Slave sinnvoll. Dann stellt phc2sys die Systemuhr und chrony liefert nur noch "
      + "aus – zwei Regler gleichzeitig würden sich gegenseitig stören.",
  },
  ptp_servo: {
    title: "Servo-Zustand",
    text: "Wie weit sich ptp4l eingeregelt hat: **s0** ungeregelt, **s1** einmal gesprungen, "
      + "**s2** eingerastet. Im Normalbetrieb steht hier s2.",
  },
  ptp_rms: {
    title: "RMS / Max",
    text: "Mittlere und größte Abweichung zum Master im letzten Zusammenfassungsintervall – "
      + "die wichtigste Qualitätszahl eines PTP-Slaves.",
  },
  ptp_freq: {
    title: "Frequenzkorrektur",
    text: "Wie stark ptp4l die Uhr der Netzwerkkarte beschleunigt oder bremst, in ppb "
      + "(Milliardstel). Stabil ist wichtiger als klein.",
  },

  // ---------------------------------------------------------------- Clients
  client_packets: {
    title: "Anfragen",
    text: "Wie viele NTP-Anfragen dieses Gerät gestellt hat, seit chrony läuft.",
  },
  client_dropped: {
    title: "Verworfen",
    text: "Anfragen, die nicht beantwortet wurden – meist wegen der Begrenzung (Anfragen "
      + "begrenzen) bei Geräten, die zu oft fragen.",
  },
  client_interval: {
    title: "Intervall",
    text: "Wie oft das Gerät im Schnitt fragt. Typisch: 64 s bis 17 min. Sehr kurze Intervalle "
      + "deuten auf ein falsch eingestelltes Gerät hin.",
  },
  client_last: {
    title: "Letzte Anfrage",
    text: "Wann das Gerät zuletzt gefragt hat.",
  },
  served_rate: {
    title: "Beantwortete Anfragen",
    text: "Wie viele NTP-Anfragen dieser Server im Verlauf beantwortet hat (pro Minute). Steigt, "
      + "sobald die Adresse per DHCP verteilt ist.",
  },
  clock_control: {
    title: "Uhrensteuerung",
    text: "Damit chrony die Uhr stellen darf, braucht der Container `cap_add: [SYS_TIME]`. Ohne "
      + "läuft chrony mit `-x`: Es misst und verteilt, korrigiert aber nichts.",
  },
  settings_source: {
    title: "Herkunft einer Einstellung",
    text: "**Standard**: eingebauter Wert. **Umgebung**: gesetzt per Umgebungsvariable in der "
      + "Compose-Datei. **Dashboard**: hier gespeichert – hat Vorrang vor der Umgebung. "
      + "„Zurücksetzen“ entfernt den Dashboard-Wert, dann gilt wieder Umgebung bzw. Standard.",
  },
};

export const SELECT_STATE_HELP = {
  best: "sel_best", combined: "sel_combined", not_combined: "sel_not_combined",
  falseticker: "sel_falseticker", noselect: "sel_noselect", unsynchronised: "sel_unsynchronised",
  missing_samples: "sel_missing_samples", distance: "sel_distance", large_distance: "sel_large_distance",
  jittery: "sel_jittery", waits_others: "sel_waits_others", stale: "sel_stale", orphan: "sel_orphan",
  not_trusted: "sel_not_trusted", not_preferred: "sel_not_preferred", waits_update: "sel_waits_update",
};

// Kurzbezeichnungen für die Tabellen.
export const SELECT_STATE_SHORT = {
  best: "ausgewählt", combined: "kombiniert", not_combined: "nicht kombiniert",
  falseticker: "Falseticker", noselect: "nur beobachten", unsynchronised: "Quelle nicht synchron",
  missing_samples: "zu wenige Messwerte", distance: "zu unsicher",
  large_distance: "Unsicherheit zu groß", jittery: "zu unruhig", waits_others: "wartet auf andere",
  stale: "veraltet", orphan: "Orphan", not_trusted: "nicht vertrauenswürdig",
  not_preferred: "andere Quelle bevorzugt", waits_update: "wartet auf Messung",
};

export const HELP_GROUPS = [
  { title: "Grundlagen", keys: ["ntp", "stratum", "island", "minsources", "dhcp42", "clock_control"] },
  { title: "Werte der Systemuhr", keys: ["system_offset", "uncertainty", "rms_offset", "frequency", "skew",
    "root_delay", "root_dispersion", "leap", "update_interval"] },
  { title: "Zeitquellen", keys: ["source_type", "hostname_vs_ip", "poll", "reach", "last_rx", "source_offset",
    "jitter", "interval", "samples", "score"] },
  { title: "Warum eine Quelle (nicht) genutzt wird", keys: ["state_best", "state_combined",
    "state_not_combined", "state_falseticker", "state_jittery", "state_unreachable", "sel_large_distance",
    "sel_distance", "sel_not_preferred", "sel_noselect", "sel_missing_samples", "sel_waits_others",
    "sel_unsynchronised", "sel_stale", "sel_waits_update", "sel_not_trusted", "sel_orphan"] },
  { title: "NTP-Details je Server", keys: ["peer_delay", "peer_dispersion", "response_time", "precision",
    "jitter_asymmetry", "ntp_tests", "interleaved", "timestamping", "packets"] },
  { title: "NTS", keys: ["nts", "nts_ke", "nts_cookies", "nocerttimecheck", "nts_server"] },
  { title: "GPS", keys: ["gps", "gps_value", "gps_offset", "gps_delay", "gps_role", "gps_recalibrate", "pps",
    "fix", "satellites", "dop", "snr", "skyplot", "gnss", "time_error", "cold_start"] },
  { title: "PTP", keys: ["ptp", "ptp_vs_ntp", "ptp_requirements", "grandmaster", "port_state",
    "offset_from_master", "mean_path_delay", "steps_removed", "clock_class", "clock_accuracy", "ptp_domain",
    "ptp_transport", "utc_offset", "phc", "phc2sys", "ptp_servo", "ptp_rms", "ptp_freq"] },
  { title: "Clients", keys: ["client_packets", "client_dropped", "client_interval", "client_last", "served_rate"] },
  { title: "Einstellungen", keys: ["settings_source"] },
];
