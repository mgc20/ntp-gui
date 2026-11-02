// Erklärungen zur Seite „Uhrqualität“ (1.4): Temperatur, Schaltsekunden, Vollbild-Uhr.
// Wird in help.js in HELP übernommen; die Schlüssel stehen gesammelt in HELP_GROUP_UHR.
export const HELP_UHR = {
  uq_page: {
    title: "Uhrqualität",
    text: "Diese Seite zeigt, was die Uhr dieses Geräts **ohne** Hilfe von außen taugen würde und was sie "
      + "langfristig beeinflusst: die Temperatur des Quarzes, die Schaltsekunden-Liste und eine große Uhr "
      + "für den Wandmonitor. Nichts hier verändert die Zeit oder die Einstellungen von chrony – außer dem "
      + "**Holdover-Test**, den du selbst startest und der sich danach von allein zurückstellt.",
  },
  holdover: {
    title: "Holdover-Test",
    text: "**Holdover** heißt: Wie gut hält die Uhr die Zeit, wenn alle Zeitquellen weg sind (GPS gestört, Internet "
      + "aus)? Der Test misst das echt statt es zu schätzen: ntp-gui wählt GPS/PPS und – wenn angehakt – alle "
      + "Netzquellen per `chronyc selectopts … +noselect` ab. chrony stellt die Uhr dann nicht mehr nach, sie läuft "
      + "mit der zuletzt gelernten Frequenz frei. Die Netzquellen werden aber **weiter gemessen** – sie sind die "
      + "Messlatte, ohne die Zeit zu beeinflussen. Nach der eingestellten Dauer werden alle Quellen automatisch "
      + "wieder auswählbar, auch nach einem Neustart von ntp-gui (die Endzeit steht in der Datenbank). Jeder "
      + "Schritt steht im Ereignisprotokoll. Startet chronyd während des Tests neu (z. B. weil du Einstellungen "
      + "speicherst), ist der Schalter weg – der Test wird dann abgebrochen, weil das Ergebnis nicht mehr stimmt.",
  },
  holdover_hours: {
    title: "Dauer des Holdover-Tests",
    text: "1 bis 24 Stunden, Standard 2 h. Kurz zeigt die Gangabweichung des Quarzes, lang zeigt zusätzlich den "
      + "Einfluss der Temperatur (Tag/Nacht). Ein Raspberry Pi ohne Temperaturausgleich verliert typisch einige "
      + "Millisekunden pro Stunde – deshalb gibt es die Abbruchgrenze.",
  },
  holdover_limit: {
    title: "Abbruchgrenze",
    text: "Wird der gemessene Zeitfehler größer als diese Grenze (Standard **10 ms**), bricht der Test sofort ab und "
      + "alle Quellen sind wieder auswählbar. So bekommen deine Clients nie eine Zeit, die weiter danebenliegt. "
      + "Das Ergebnis lautet dann „Grenze nach … erreicht“ – auch das ist eine Aussage über die Uhr.",
  },
  holdover_network: {
    title: "Auch Netzquellen abschalten",
    text: "**An (Standard, echter Holdover):** GPS/PPS und alle Netzquellen werden abgewählt, die Uhr läuft frei. "
      + "**Aus:** Nur GPS/PPS werden abgewählt – chrony regelt dann über das Netz weiter. Das zeigt, wie gut die "
      + "Zeit ohne GPS ist (z. B. vor einer Antennen-Umrüstung), ist aber kein Freilauf. Die Netzquellen werden in "
      + "beiden Fällen gemessen.",
  },
  holdover_refs: {
    title: "Messreferenzen",
    text: "Erreichbare Netzquellen, gegen die der Zeitfehler gemessen wird. Ohne mindestens **zwei** startet der "
      + "Test nicht: Mit nur einer Quelle wäre nicht zu unterscheiden, ob die eigene Uhr oder die Quelle wandert. "
      + "Als Ergebnis zählt der Median aller Referenzen.",
  },
  holdover_progress: {
    title: "Laufender Holdover-Test",
    text: "Seit wann der Test läuft und wie lange noch. Während des Tests stellt chrony die Uhr nicht nach – "
      + "Clients bekommen eine etwas ungenauere Zeit; die Übersicht zeigt einen Hinweis. „Test abbrechen“ macht "
      + "alle Quellen sofort wieder auswählbar.",
  },
  holdover_deviation: {
    title: "Zeitfehler im Holdover",
    text: "Wie weit sich die eigene Uhr seit dem Start von den Messreferenzen entfernt hat: Median der Offsets aller "
      + "erreichbaren Netzquellen minus dem Wert beim Start. Das ist der Fehler, den die Uhr ohne Quelle aufgebaut "
      + "hat. Die Netzquellen selbst schwanken um einige Zehntel Millisekunden – kleinere Werte sind Rauschen.",
  },
  holdover_drift: {
    title: "Gangabweichung (ppm)",
    text: "Steigung des Zeitfehlers über die Zeit: 1 ppm = 3,6 ms pro Stunde. chrony hat die Frequenz vor dem Test "
      + "gelernt – die Gangabweichung zeigt, wie gut dieser Wert hält. Wandert sie mit der Temperatur, hilft später "
      + "der Temperaturausgleich.",
  },
  holdover_result: {
    title: "Ergebnis des Holdover-Tests",
    text: "„Die Uhr hält X ms in Y h“: der gemessene Zeitfehler am Ende des Tests. Er gilt für die Bedingungen in der "
      + "Zeit (Temperatur, Last) – ein zweiter Test zu einer anderen Tageszeit zeigt die Spanne. Gerechnet wird je "
      + "Netzquelle (jetzt gegen Start) und davon der Median – fällt eine aus, springt der Wert nicht. Ein Test nur "
      + "ohne GPS/PPS heißt „Ohne GPS/PPS: Abweichung …“, weil das Netz die Uhr weiter regelt (kein Freilauf). "
      + "„Ungültig“: chrony hat während des Tests eine neue Quelle aufgenommen, die sich nicht abwählen ließ. Gespeichert werden "
      + "die letzten 20 Ergebnisse, nur auf diesem Gerät.",
  },
  temp_freq: {
    title: "Temperatur und Frequenz",
    text: "Der Quarz, der die Systemuhr antreibt, schwingt je nach Temperatur etwas schneller oder langsamer – "
      + "typisch 0,05 bis 0,5 ppm pro Grad, und zwar nicht linear. chrony gleicht das mit GPS oder guten "
      + "NTP-Quellen laufend aus; man sieht es dann am **Frequenzfehler**, der im Tagesgang mit der Temperatur "
      + "mitwandert. Wichtig wird es, wenn die Referenz fehlt (GPS-Ausfall, Internet weg): Dann läuft die Uhr "
      + "mit dem zuletzt gelernten Wert weiter, und jede Temperaturänderung wird direkt zum Zeitfehler. "
      + "ntp-gui speichert deshalb zu jedem Messpunkt die Temperatur. Daraus kann **1.5** einen Vorschlag für "
      + "chronys Temperaturausgleich (`tempcomp`) berechnen – in 1.4 wird nur gemessen, nichts verstellt.",
  },
  temp_sensor: {
    title: "Temperatursensor",
    text: "Woher die Temperatur kommt. „auto“ nimmt den Chip, der dem Quarz am nächsten ist: beim Raspberry Pi "
      + "`cpu-thermal` (der Quarz sitzt neben dem SoC), am PC `x86_pkg_temp`, `k10temp` oder `coretemp`. Besser "
      + "ist ein **DS18B20** am 1-Wire-Bus direkt am Quarz oder am GPS-Modul – der misst die Umgebung statt der "
      + "Rechenlast. Welche Sensoren es gibt, zeigt der **Hardware-Check**; auswählen lässt sich einer in den "
      + "Einstellungen (Dashboard → Temperatursensor). In virtuellen Maschinen und unter Docker Desktop gibt es "
      + "meist keinen – dann steht hier „nicht verfügbar“.",
  },
  temp_now: {
    title: "Temperatur jetzt",
    text: "Der zuletzt gelesene Wert des gewählten Sensors in °C. Die CPU-Temperatur steigt mit der Last – "
      + "ein Sprung beim Kompilieren oder bei einem Backup ist normal und zeigt sich auch im Diagramm.",
  },
  temp_span: {
    title: "Temperaturspanne",
    text: "Kleinster und größter Wert im gewählten Zeitraum. Für einen belastbaren Zusammenhang braucht es "
      + "mindestens **4 K** Spanne – ein Gerät in einem klimatisierten Raum hat sie vielleicht nie; dann ist "
      + "Temperaturausgleich auch nicht nötig.",
  },
  temp_duration: {
    title: "Messdauer",
    text: "Wie lange Temperatur und Frequenz schon gemeinsam aufgezeichnet sind (im gewählten Zeitraum). Es "
      + "braucht **mindestens 1–3 Tage mit Tag-/Nacht-Wechsel**: Erst dann sieht man, ob die Frequenz der "
      + "Temperatur folgt oder nur zufällig schwankt. Ein Vorschlag für den Ausgleich (1.5) kommt frühestens "
      + "nach 3 Tagen und 4 K Spanne.",
  },
  temp_correlation: {
    title: "Zusammenhang (r)",
    text: "Korrelationskoeffizient nach Pearson zwischen Temperatur und Frequenz: **±1** = die Frequenz folgt der "
      + "Temperatur genau (Gerade), **0** = kein linearer Zusammenhang. Werte ab etwa |r| = 0,5 zeigen, dass die "
      + "Temperatur die Uhr spürbar beeinflusst. Ein negatives r ist genauso aussagekräftig wie ein positives – "
      + "es hängt nur vom Schliff des Quarzes ab. Kleine Werte bei großer Spanne heißen: Der Quarz ist gutmütig, "
      + "oder chronys Frequenz wird von etwas anderem bestimmt (Quellenwechsel, Netzlast).",
  },
  temp_scatter: {
    title: "Streudiagramm Temperatur ↔ Frequenz",
    text: "Jeder Punkt ist ein Messpunkt: rechts/links die Temperatur, oben/unten chronys Frequenzfehler in ppm. "
      + "Ältere Punkte sind blasser, der neueste ist hervorgehoben. Liegen die Punkte auf einer Linie oder einem "
      + "flachen Bogen, bestimmt die Temperatur die Gangabweichung – genau das, was ein Temperaturausgleich "
      + "wegrechnen könnte. Eine Wolke ohne Richtung heißt: wenig Einfluss, oder noch zu wenig Spanne. Mehrere "
      + "parallele Linien entstehen, wenn der Quarz altert oder chrony die Quelle gewechselt hat. Über jedem "
      + "Fenster wird gemittelt, einzelne Ausreißer (z. B. der Start von chrony) sind am Rand markiert.",
  },
  temp_history: {
    title: "Temperaturverlauf",
    text: "Die Temperatur über die Zeit. Ein deutlicher Tag-/Nacht-Gang ist für die Auswertung gut: Er liefert "
      + "die Spanne, aus der sich der Einfluss auf die Frequenz ablesen lässt. Darunter steht zum Vergleich der "
      + "Frequenzfehler im selben Zeitraum.",
  },
  temp_candidates: {
    title: "Temperatursensoren",
    text: "Alle Temperaturfühler, die der Container lesen kann: **thermal** (Kernel-Thermalzonen, z. B. "
      + "`cpu-thermal`), **hwmon** (Sensorchips am PC, z. B. `k10temp`) und **DS18B20** am 1-Wire-Bus "
      + "(Raspberry Pi: `dtoverlay=w1-gpio` in der config.txt). Die Kennung in der ersten Spalte trägst du in "
      + "den Einstellungen bei „Temperatursensor“ ein, wenn „auto“ den falschen wählt. Ein DS18B20 ohne Wert ist "
      + "meist falsch verkabelt (4,7-kΩ-Widerstand zwischen Daten und 3,3 V fehlt). Die Kennung eines DS18B20 "
      + "ist seine Seriennummer – das Diagnosepaket entfernt sie.",
  },
  leap_overview: {
    title: "Schaltsekunden",
    text: "UTC folgt der Erdrotation, Atomuhren (TAI) nicht. Weil sich die Erde unregelmäßig dreht, wird UTC ab "
      + "und zu um eine **Schaltsekunde** angepasst (23:59:60 am 30. Juni oder 31. Dezember). Ob eine kommt, "
      + "kündigt das IERS in Paris im **Bulletin C** rund sechs Monate vorher an; die Datei leap-seconds.list "
      + "fasst alle Ankündigungen zusammen. chrony liest sie, kündigt eine Schaltsekunde an seine Clients an und "
      + "fügt sie zum richtigen Zeitpunkt ein. Seit 2017 gab es keine mehr. Die Zahlen hier stammen aus der Datei, "
      + "die chrony wirklich liest. Ist die Einstellung „Schaltsekunden-Liste“ leer, steht hier „abgeschaltet“; "
      + "nutzt chrony eine „right/“-Zeitzone, ist die Liste nur zur Information und ihr Ablauf löst keinen Hinweis aus.",
  },
  leap_tai_utc: {
    title: "TAI − UTC",
    text: "So viele Sekunden geht die Atomzeit TAI der koordinierten Weltzeit UTC voraus – derzeit **37 s** "
      + "(10 s Startabstand 1972 plus 27 Schaltsekunden). GPS-Zeit liegt fest 19 s hinter TAI, also 18 s vor "
      + "UTC; PTP verteilt TAI und nennt den Abstand im Feld currentUtcOffset.",
  },
  leap_last: {
    title: "Letzte Schaltsekunde",
    text: "Datum, ab dem der aktuelle Abstand TAI−UTC gilt. Die Schaltsekunde selbst war die Sekunde davor: "
      + "für den Eintrag 1. Januar 2017 also 31.12.2016 23:59:60 UTC.",
  },
  leap_next: {
    title: "Angekündigte Schaltsekunde",
    text: "Steht in der Liste bereits eine künftige Schaltsekunde, nennt diese Zeile ihr Datum. chrony meldet "
      + "sie dann am Tag davor als „Schaltsekunde wird eingefügt“ und reicht das an die Clients weiter.",
  },
  leap_expiry: {
    title: "Liste gültig bis",
    text: "Das IERS sagt nur ein halbes Jahr voraus, ob eine Schaltsekunde kommt. Darum hat die Liste ein "
      + "Ablaufdatum, das mit jedem Bulletin C um sechs Monate wächst. ntp-gui lädt die Datei bewusst **nicht** "
      + "selbst aus dem Internet: Sie kommt mit dem Paket tzdata im Image. Läuft sie in weniger als **60 Tagen** "
      + "ab, erscheint ein Hinweis und ein Ereignis „Schaltsekunde“ – das Image ist zu alt, ein Update "
      + "(docker compose pull && docker compose up -d) bringt die neue Liste mit. Nach dem Ablauf weiß chrony "
      + "nicht mehr, ob eine Schaltsekunde ansteht.",
  },
  leap_hash: {
    title: "Prüfsumme",
    text: "Die Datei enthält in der Zeile „#h“ eine SHA-1-Prüfsumme über alle Daten (Aktualisierung, Ablauf und "
      + "jede Schaltsekunde). ntp-gui rechnet sie nach: „stimmt“ heißt, die Liste ist unverändert so, wie das "
      + "IERS sie veröffentlicht hat. „stimmt nicht“ deutet auf eine beschädigte oder von Hand bearbeitete Datei.",
  },
  leap_future: {
    title: "Schaltsekunden werden abgeschafft",
    text: "Die Generalkonferenz für Maß und Gewicht (CGPM) hat im November 2022 beschlossen (Resolution 4), "
      + "dass UT1 und UTC spätestens ab **2035** weiter auseinanderlaufen dürfen als bisher (0,9 s) – damit "
      + "fallen die Schaltsekunden praktisch weg. Bis dahin können noch welche kommen; die Erde dreht sich "
      + "derzeit sogar etwas schneller, eine erstmals **negative** Schaltsekunde gilt als möglich. Quelle: "
      + "bipm.org/en/cgpm-2022/resolution-4.",
  },
  clock_page: {
    title: "Vollbild-Uhr",
    text: "Unter **/clock** zeigt ntp-gui eine große Uhr für Wandmonitor, Tablet oder Werkstatt: Ortszeit, UTC, "
      + "Datum, Kalenderwoche und unten ein Band mit dem Zustand des Servers. Taste **F** schaltet Vollbild um; "
      + "Hell/Dunkel und **Rotlicht** (schont die Dunkeladaption der Augen) merkt sich der Browser. Der Bildschirm "
      + "bleibt an, wenn der Browser das erlaubt (Wake Lock – meist nur über HTTPS oder localhost). Kommt 10 s "
      + "keine Antwort vom Server, wird die Ampel grau; die Uhr läuft mit dem letzten Abgleich weiter.",
  },
  clock_sync: {
    title: "Wie genau ist die Anzeige?",
    text: "Die Uhr im Browser zeigt **Serverzeit**, nicht die oft ungenaue Uhr des Tablets. Dazu misst die Seite "
      + "wie NTP mit vier Zeitstempeln (Senden, Empfang am Server, Antwort vom Server, Empfang) fünfmal den "
      + "Versatz; die Messung mit der kürzesten Laufzeit (RTT) gewinnt, weil sie am wenigsten gewartet hat. "
      + "Schlimmstenfalls liegt sie um die halbe Laufzeit daneben – das ist das „± …“ hinter „Anzeige“. Im LAN "
      + "sind das wenige Millisekunden, über WLAN mit Stromsparmodus auch mal 50 ms. Dazu kommt die Genauigkeit "
      + "des Servers selbst („Server ± …“, aus chronys Root Delay und Root Dispersion). Alle 60 s wird neu "
      + "abgeglichen.",
  },
  clock_public: {
    title: "Vollbild-Uhr ohne Anmeldung",
    text: "Normalerweise ist /clock wie das Dashboard geschützt. Eingeschaltet ist die Uhr samt /api/v1/time "
      + "**ohne Passwort** erreichbar – praktisch für einen Wandmonitor, auf dem du kein Passwort hinterlegen "
      + "willst (und einen API-Schlüssel in der Adresse solltest du nie verwenden: der landet in Proxy- und "
      + "Browser-Logs). Sichtbar ist dann nur Uhrzeit, Ampel, Genauigkeit und die Art der Quelle (GPS, NTP …) – "
      + "keine Namen, Adressen oder Einstellungen. Es ist trotzdem die erste offene Seite neben /healthz: Lass "
      + "es aus, wenn das Dashboard aus dem Internet erreichbar ist. Wer sich anmeldet, sieht auf /api/v1/time "
      + "zusätzlich den Namen der Quelle. Für Anfragen ohne Anmeldung gilt der Schutz vor DNS-Rebinding: Sie werden "
      + "nur über IP-Adressen, einteilige oder lokale Namen (*.local, *.lan …) und WEB_ALLOWED_HOSTS beantwortet – "
      + "sonst könnte jede Webseite, die jemand im LAN öffnet, den Zustand deines Servers abfragen.",
  },
};

export const HELP_GROUP_UHR = {
  title: "Uhrqualität",
  keys: ["uq_page", "temp_freq", "temp_sensor", "temp_now", "temp_span", "temp_duration", "temp_correlation",
    "temp_scatter", "temp_history", "temp_candidates", "leap_overview", "leap_tai_utc", "leap_last", "leap_next",
    "leap_expiry", "leap_hash", "leap_future", "clock_page", "clock_sync", "clock_public", "holdover", "holdover_hours",
    "holdover_limit", "holdover_network", "holdover_refs", "holdover_progress", "holdover_deviation", "holdover_drift",
    "holdover_result"],
};
