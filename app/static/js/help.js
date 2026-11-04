import { HELP_HARDWARE, HELP_GROUP_HARDWARE } from "./help-hardware.js";
import { HELP_CLIENTS, HELP_GROUP_CLIENTS } from "./help-clients.js";
import { HELP_AUTOCAL, HELP_GROUP_AUTOCAL } from "./help-autocal.js";
import { HELP_DIAGNOSE, HELP_GROUP_DIAGNOSE } from "./help-diagnose.js";
import { HELP_API, HELP_GROUP_API } from "./help-api.js";
import { HELP_NOTIFY, HELP_GROUP_NOTIFY } from "./help-notify.js";
import { HELP_DNS, HELP_GROUP_DNS } from "./help-dns.js";
import { HELP_UHR, HELP_GROUP_UHR } from "./help-uhr.js";
import { HELP_UPDATE, HELP_GROUP_UPDATE } from "./help-update.js";
import { HELP_GNSS, HELP_GROUP_GNSS } from "./help-gnss.js";
import { HELP_WEB, HELP_GROUP_WEB } from "./help-web.js";

// Alle Erklärungen an einer Stelle. Die ⓘ-Knöpfe im Dashboard und die
// Hilfeseite nutzen dieselben Texte. **fett** und `code` werden formatiert.

export const HELP = {
  // ---------------------------------------------------------------- Übersicht und Diagramme
  overview_verdict: {
    title: "Gesamtzustand",
    text: "Das Urteil oben auf der Übersicht fasst alles zusammen – dieselbe Bewertung zeigt die Kopfzeile "
      + "rechts oben: **Grün** – die Uhr ist synchron und kein Hinweis verlangt etwas. **Gelb** – die Uhr ist "
      + "noch nicht synchron, läuft im Inselbetrieb oder ein Hinweis sollte geprüft werden. **Rot** – chronyd "
      + "antwortet nicht oder es gibt eine Störung, die Clients betrifft. Die Kennzahlen daneben zeigen den "
      + "aktuellen Wert und als kleine Linie den Verlauf im gewählten Zeitraum; einzelne Spitzen sind dort "
      + "abgeschnitten. Ist eine Kennzahl auffällig, steht das als Wort darunter („erhöht“, „kritisch“).",
  },
  overview_hints: {
    title: "Hinweise",
    text: "**Störungen** (rot) stehen mit ganzer Erklärung im Statusband. **Warnungen** (gelb) sind eine "
      + "Zeile mit Titel und dem Bereich, den sie betreffen – **Details** klappt die Erklärung auf. Derselbe "
      + "Bereich darunter (z. B. „Systemuhr“) färbt sich gelb bzw. rot und nennt den Hinweis noch einmal. "
      + "Reine Informationen sind zu einer Zeile zusammengefasst – **anzeigen** klappt sie auf. Die Hinweise "
      + "entstehen bei jeder Aktualisierung neu aus dem aktuellen Zustand; erledigte verschwinden von selbst.",
  },
  overview_best_source: {
    title: "Ausgewählte Quelle",
    text: "Die Zeitquelle, der chrony gerade folgt (Zeichen `*`), und in Klammern ihr letzter gemessener "
      + "Offset. Weitere Quellen mit `+` werden mitgemittelt. Wechselt die Auswahl häufig, steht das im "
      + "Ereignisprotokoll.",
  },
  overview_restarts: {
    title: "Neustarts der Dienste",
    text: "„2× neu“ heißt: Der Supervisor hat den Dienst seit dem Containerstart zweimal neu gestartet, "
      + "weil er sich beendet hatte. Einzelne Neustarts nach dem Ab- und Anstecken eines GPS-Empfängers sind "
      + "normal; steigt die Zahl ständig, nennt das Log auf der Diagnose-Seite den Grund. Fährt man mit der "
      + "Maus über einen Dienst, steht dort, seit wann er im jetzigen Zustand ist.",
  },
  overview_events: {
    title: "Letzte Ereignisse",
    text: "Die fünf neuesten Einträge aus dem Ereignisprotokoll: Quellenwechsel, GPS-Fix verloren oder "
      + "wieder da, PPS-Ausfälle, Neustarts von Diensten, gespeicherte Einstellungen. Die Diagnose-Seite zeigt "
      + "alle Ereignisse der letzten 90 Tage mit Filtern.",
  },
  chart_stats: {
    title: "Diagramme lesen",
    text: "Über jedem Verlauf steht der **aktuelle Wert** (**jetzt** = Live-Wert wie im Statusband, "
      + "**letzter Wert** = letzter gespeicherter Messpunkt) und dazu **min**, **max** und **Ø** (Mittelwert) im "
      + "gewählten Zeitraum. Die x-Achse zeigt immer den ganzen gewählten Zeitraum bis jetzt; reicht der "
      + "Verlauf noch nicht so weit zurück, ist der Anfang grau mit „Verlauf ab …“ markiert. Fährt man mit der "
      + "Maus über das Diagramm (oder tippt darauf, oder fokussiert es mit Tab und blättert mit den "
      + "Pfeiltasten), zeigt ein Fadenkreuz Zeitpunkt und genauen Wert. "
      + "**Ausgeblendete Spitzen**: Ein einzelner Ausreißer – typisch die Einschwingphase nach dem Start von "
      + "chrony – würde den Alltag zu einer flachen Linie drücken. Dann wird die Skala auf den üblichen "
      + "Bereich begrenzt, ein ▲ bzw. ▼ am Rand markiert die Spitze, die Kopfzeile nennt ihren Wert, und min, "
      + "max und Ø zählen sie nicht mit. Die jüngsten Werte werden nie ausgeblendet – ein echter neuer Sprung "
      + "bleibt sichtbar. **Graue Streifen** sind Zeiten ohne Messwerte (Container aus, Neustart) – dort wird "
      + "nichts verbunden. Die Einheit der y-Achse steht einmal oben links. Gelb und rot getönte Flächen "
      + "markieren Bereiche, in denen ein Wert zu groß wird; sie erscheinen nur, wenn der Verlauf dorthin reicht.",
  },
  // ---------------------------------------------------------------- Grundlagen
  ntp: {
    title: "NTP – Network Time Protocol",
    text: "Das Standardprotokoll, mit dem praktisch jedes Gerät seine Uhr stellt: PCs, Server, "
      + "Router, Drucker, Kameras, Smart-Home. Ein Client fragt einen Server nach der Zeit, misst "
      + "dabei die Laufzeit der Pakete und rechnet sie heraus. Im LAN erreicht NTP typisch "
      + "**0,1–1 ms** Genauigkeit, über das Internet **1–50 ms**, je nach Leitung.",
  },
  services: {
    title: "Dienste im Container",
    text: "Der Container startet mehrere Programme: **chronyd** (Zeitdienst), das Dashboard und je "
      + "nach Einstellung **gpsd**, **ptp4l** und **phc2sys**. Fällt ein optionaler Dienst aus – "
      + "etwa weil der GPS-Empfänger abgezogen wurde –, startet der Supervisor ihn mit wachsender "
      + "Pause (5 s, 15 s, 1 min, 5 min) neu, statt den ganzen Container zu beenden. So läuft NTP "
      + "weiter. „aus“ heißt: in den Einstellungen nicht eingeschaltet. Fällt chronyd oder das "
      + "Dashboard aus, startet der ganze Container neu, weil ohne sie nichts mehr funktioniert.",
  },
  chronyd: {
    title: "Zeitdienst (chronyd)",
    text: "**chronyd** ist das Programm, das hier die Uhr stellt und die Zeit per NTP an das LAN "
      + "verteilt. Das Dashboard fragt es alle paar Sekunden über `chronyc` ab. Antwortet es nicht, "
      + "startet es gerade neu (z. B. nach dem Speichern von Einstellungen) oder ist abgestürzt – "
      + "dann bekommen die Clients keine Zeit, und das Container-Log nennt den Grund.",
  },
  reference: {
    title: "Referenz",
    text: "Die Quelle, nach der sich die Systemuhr gerade richtet – ein Server aus der Liste der "
      + "Zeitquellen oder das GPS. chrony nennt sie über ihre **Reference ID**: bei Servern die "
      + "IP-Adresse, bei Refclocks einen Namen wie `GPS` oder `PPS`. Steht hier nichts oder "
      + "`7F7F0101` (LOCAL), läuft der Server im Inselbetrieb.",
  },
  ref_time: {
    title: "Referenzzeit",
    text: "Zeitpunkt der letzten Messung, mit der chrony die Uhr korrigiert hat. Sie sollte nur "
      + "wenige Sekunden bis Minuten zurückliegen (je nach Abfrageintervall). Liegt sie Stunden "
      + "zurück, kommt keine Quelle mehr durch – die Uhr läuft dann frei weiter.",
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
    text: "„Normal“ ist der Regelfall. „Schaltsekunde wird eingefügt/entfernt“ kündigt eine "
      + "Schaltsekunde zum Monatsende an – chrony und die Clients bekommen das mit. „Nicht "
      + "synchron“ heißt: noch keine gültige Zeit. Diesen Status reicht der Server an seine Clients "
      + "weiter.",
  },
  leap_source: {
    title: "Woher kommen die Schaltsekunden?",
    text: "Schaltsekunden werden vom IERS Monate vorher angekündigt. chrony liest diese "
      + "Ankündigungen aus einer Datei und gibt sie an die Clients weiter – sonst wären alle Uhren "
      + "nach einer Schaltsekunde für eine Weile um eine Sekunde daneben. Seit 1.3.1 (Debian 13) "
      + "kommt die Liste aus **leap-seconds.list** im Paket tzdata; sie wird mit jedem Image-Update "
      + "aktuell. Die alte Zeitzone „right/UTC“ gibt es in Debian 13 nicht mehr. Eine eigene Liste "
      + "kannst du unter /config ablegen.",
  },
  update_interval: {
    title: "Aktualisierungsintervall",
    text: "Wie viele Sekunden zwischen den letzten beiden Korrekturen der Uhr lagen. Es folgt dem "
      + "Abfrageintervall der genutzten Quellen: kurz nach dem Start wenige Sekunden, später "
      + "typisch 64–1024 s. Ein großer Wert ist kein Fehler – die Uhr läuft dann stabil.",
  },
  island: {
    title: "Inselbetrieb (local stratum)",
    text: "Ist keine Quelle erreichbar, kann der Server trotzdem seine eigene Uhrzeit verteilen – "
      + "mit absichtlich schlechtem Stratum (Standard 10). So bleiben alle Geräte im LAN "
      + "untereinander einig, auch wenn das Internet ausfällt. Sobald eine echte Quelle zurück "
      + "ist, übernimmt die wieder.",
  },
  local_orphan: {
    title: "Orphan-Modus (zwei Server im Verbund)",
    text: "Für zwei (oder mehr) ntp-gui-Server, die sich gegenseitig als Quelle eingetragen haben. "
      + "Ohne Orphan-Modus liefert im Inselbetrieb jeder Server seine **eigene** Uhrzeit aus – die "
      + "Geräte im LAN sehen dann zwei leicht verschiedene Zeiten. Mit Orphan-Modus einigen sich die "
      + "Server auf **eine** gemeinsame Inselzeit: Der Server mit der kleinsten Referenz-ID gibt den "
      + "Takt vor, der andere folgt ihm. Sobald eine echte Quelle zurück ist, gilt wieder sie. "
      + "Wirkt nur zusammen mit „Auch ohne Quelle Zeit ausliefern“; beide Server brauchen dasselbe "
      + "Stratum im Inselbetrieb.",
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
    title: "Letzter Empfang",
    text: "Wie lange die letzte gültige Antwort dieser Quelle zurückliegt. Normal ist etwa ein "
      + "Abfrageintervall. Deutlich mehr heißt: Die Antworten kommen nicht mehr an – chrony "
      + "arbeitet dann mit älteren Messwerten, bis die Quelle als veraltet gilt.",
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
  select_reason: {
    title: "Grund (Auswertung von chrony)",
    text: "Warum chrony eine Quelle gerade nutzt oder nicht – direkt aus `chronyc selectdata`. "
      + "**ausgewählt (*)** und **kombiniert (+)** fließen in die Zeit ein. Alles andere sagt, was "
      + "fehlt: zu unsicher oder zu unruhig im Vergleich zu den besten Quellen, Widerspruch zur "
      + "Mehrheit (**Falseticker**), zu wenige oder zu alte Messwerte, oder eine Option wie „nur "
      + "beobachten“ bzw. „bevorzugen“ bei einer anderen Quelle. Das ⓘ in jeder Zeile erklärt den "
      + "konkreten Grund.",
  },
  select_options: {
    title: "Optionen der Quelle",
    text: "Die Optionen, mit denen chrony diese Quelle tatsächlich bewertet. **prefer**: erste "
      + "Wahl, solange sie plausibel ist. **noselect**: nur messen, nie nutzen (z. B. zum "
      + "Kalibrieren). **trust**: gilt immer als richtig, auch gegen die Mehrheit. **require**: "
      + "ohne diese Quelle wird die Uhr nicht gestellt. „keine“ ist der Normalfall.",
  },
  server_reference: {
    title: "Referenz des Servers",
    text: "Woher dieser Server selbst seine Zeit hat (seine Reference ID). Eine IP-Adresse heißt: "
      + "Er fragt seinerseits einen anderen NTP-Server (dann Stratum 2 oder höher). Ein Name wie "
      + "`GPS`, `PPS`, `PTB` oder `DCF` heißt: Er hängt direkt an einer Referenzuhr (Stratum 1). "
      + "Praktisch, um zu sehen, ob zwei Quellen am Ende dieselbe Herkunft haben.",
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
    text: "Die Streuung der Messwerte ist zu groß im Vergleich zu den anderen Quellen. Typisch für "
      + "Quellen hinter Mobilfunk oder WLAN; meist erholt sich das von allein.",
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
    text: "Widerspricht der Mehrheit der Quellen und wird ignoriert: Ihr Vertrauensbereich "
      + "überschneidet sich nicht mit dem der anderen. Bei einem USB-GPS fast immer ein fehlender "
      + "Offset – also ein Kalibrierfall.",
  },
  sel_best: {
    title: "Ausgewählt (*)",
    text: "Die beste verfügbare Quelle: plausibel, mit der kleinsten Unsicherheit. Nach ihr richtet "
      + "sich die Systemuhr; ihr Stratum + 1 ist das Stratum dieses Servers.",
  },
  sel_combined: {
    title: "Kombiniert (+)",
    text: "Fast so gut wie die ausgewählte Quelle und wird mit ihr gemittelt. Mehrere kombinierte "
      + "Quellen machen die Zeit ruhiger und robuster gegen Ausreißer einer einzelnen.",
  },
  sel_not_combined: {
    title: "Nicht kombiniert (−)",
    text: "Plausibel, aber deutlich schlechter als die besten (größere Unsicherheit oder Streuung). "
      + "Bleibt als Reserve bereit und springt ein, wenn eine bessere ausfällt.",
  },

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
  nts_authenticated: {
    title: "Authentifiziert",
    text: "**ja** heißt: Die letzte Antwort dieser Quelle trug einen gültigen NTS-Echtheitsnachweis "
      + "– niemand dazwischen kann die Zeit verfälscht haben. **nein** bei einer NTS-Quelle heißt: "
      + "Der Schlüsselaustausch hat (noch) nicht geklappt. chrony nutzt die Quelle dann nicht, "
      + "statt ungeschützt auf normales NTP zurückzufallen.",
  },
  nts_server_files: {
    title: "Zertifikat und Schlüssel des NTS-Servers",
    text: "Der NTS-Server braucht ein TLS-Zertifikat (PEM) und den passenden privaten Schlüssel, "
      + "beide für den Container lesbar – am einfachsten in `/config` gemountet. Fehlt eine Datei, "
      + "startet chrony ohne NTS-Server; normales NTP läuft weiter. Die Clients müssen dem "
      + "Zertifikat vertrauen: entweder ein öffentliches (z. B. Let's Encrypt für einen echten "
      + "Domainnamen) oder ein eigenes, dessen CA auf den Clients hinterlegt ist.",
  },
  nts_cert_expiry: {
    title: "Gültigkeit des Zertifikats",
    text: "TLS-Zertifikate laufen ab – Let's-Encrypt-Zertifikate nach 90 Tagen. Ist es abgelaufen, "
      + "lehnen die Clients den Schlüsselaustausch ab und bekommen keine abgesicherte Zeit mehr. "
      + "Das Dashboard warnt 14 Tage vorher. chrony liest das Zertifikat nur beim Start – deshalb "
      + "prüft der Container jede Minute, ob Zertifikat oder Schlüssel ersetzt wurden, und lädt "
      + "chronyd dann automatisch neu. Passen die beiden Dateien (noch) nicht zusammen, z. B. mitten "
      + "in der Erneuerung, bleibt das zuletzt gültige Paar aktiv.",
  },
  nts_cert_subject: {
    title: "Name im Zertifikat",
    text: "Für welche Namen das Zertifikat gilt (CN und alternative Namen). Die Clients müssen den "
      + "Server unter **genau diesem Namen** eintragen, z. B. `server ntp.example.lan nts` – mit "
      + "der IP-Adresse oder einem anderen Namen schlägt die Prüfung fehl.",
  },
  nts_server_name: {
    title: "Servername für Clients",
    text: "Unter diesem Namen (und Port) sollen die Clients den NTS-Server erreichen – wichtig, wenn "
      + "ein Reverse-Proxy oder eine Portweiterleitung davorsteht. chrony gibt den Namen per "
      + "`ntsntpserver` im Schlüsselaustausch weiter, damit die Clients ihre NTP-Pakete (UDP 123) an "
      + "den richtigen Rechner schicken. Der Name **muss im Zertifikat stehen** (CN oder alternativer "
      + "Name, `*.example.com` deckt genau eine Ebene ab), sonst lehnen die Clients die TLS-Verbindung "
      + "ab. Der Port wird nur angezeigt, wenn er vom Standard 4460 abweicht.",
  },
  nts_cert_issuer: {
    title: "Aussteller des Zertifikats",
    text: "Wer das Zertifikat unterschrieben hat, z. B. **Let's Encrypt**. Ein öffentlicher "
      + "Aussteller wird von den Clients automatisch akzeptiert. Steht hier derselbe Name wie im "
      + "Zertifikat selbst, ist es **selbst signiert** – dann müssen die Clients genau dieses "
      + "Zertifikat (oder deine eigene CA) als vertrauenswürdig hinterlegt haben, sonst schlägt NTS fehl.",
  },
  nts_ke_server: {
    title: "NTS-KE-Verbindungen",
    text: "Wie oft Clients seit dem Start von chrony per TLS (TCP-Port 4460) einen Schlüssel "
      + "geholt haben. **Abgelehnt** zählt Verbindungen, die chrony verworfen hat – meist wegen "
      + "zu vieler gleichzeitiger Verbindungen. Jeder Client braucht nur selten einen neuen "
      + "Schlüssel; die Zahl bleibt also klein.",
  },
  nts_auth_packets: {
    title: "Authentifizierte Anfragen",
    text: "Wie viele NTP-Anfragen mit gültigem NTS-Nachweis dieser Server beantwortet hat. Steht "
      + "hier 0, obwohl Clients NTS nutzen sollen, scheitert bei ihnen der Schlüsselaustausch "
      + "oder sie fragen ohne NTS.",
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
      + "Das macht die automatische Kalibrierung selbst (Standard ab 1.5.2) – nach gut 6 Stunden Messung.",
  },
  gps_delay: {
    title: "Angenommene Unsicherheit (Delay)",
    text: "Wie sehr chrony der GPS-Zeit misstraut. Der Standard **0,2 s** ist vorsichtig – damit "
      + "wird ein unkalibriertes GPS nie zum Problem, aber auch nie genutzt, solange gute "
      + "Internet-Server da sind (Zustand „D“). Der Wert muss die **echte Streuung** abdecken – "
      + "nie kleiner: Ein Delay von 0,03 s bei ± 60 ms Streuung ließ chrony das GPS guten "
      + "NTS-Quellen vorziehen. Ohne PPS setzt ntp-gui ihn deshalb ab 1.5 selbst aus der "
      + "gemessenen Streuung („Fehlerschranke ohne PPS: gemessen“), der Kalibrier-Assistent "
      + "schlägt nie weniger vor. In diesem Modus zeigt „Delay in chrony“ den gemessenen Wert "
      + "(bzw. den Standard), und „Vorschlag übernehmen“ setzt nur den Offset.",
  },
  gps_recalibrate: {
    title: "Wann neu kalibrieren?",
    text: "Nach einem Wechsel von Empfänger, USB-Port/Hub, Firmware oder Baudrate. Sonst bleibt "
      + "der Wert über Monate stabil. Im Modus „automatisch“ (Standard) erledigt das ntp-gui selbst: "
      + "Ein anderes Gerät in den Einstellungen startet die Messung neu, eine gleichbleibende Abweichung "
      + "danach korrigiert sie von selbst. Meldet die GNSS-Störungserkennung nach dem Wechsel eine "
      + "Störung, dort „Neu lernen“ drücken. Im Modus „vorschlagen“ misst der Assistent laufend weiter – "
      + "zeigt er eine Abweichung über ~2 ms, lohnt sich ein neuer Vorschlag.",
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
    text: "**Automatisch**: chrony vergleicht GPS und Internet-Server und nimmt das Beste – ohne "
      + "PPS ist das GPS damit die **Rückfallebene**, die einspringt, wenn das Internet schlecht wird "
      + "oder ausfällt. **Bevorzugen**: GPS ist erste Wahl, solange es plausibel ist – sinnvoll bei "
      + "schlechter oder fehlender Internetleitung. **Nur beobachten**: wird gemessen, nie genutzt – "
      + "auch nicht bei einem Internetausfall; eine bewusste Wahl, nie Standard.",
  },

  // ---------------------------------------------------------------- PTP
  ptp: {
    title: "PTP – Precision Time Protocol (IEEE 1588)",
    text: "Ein Protokoll für Zeit im LAN mit **Nanosekunden**-Genauigkeit. Der Trick: Die "
      + "Netzwerkkarte selbst stempelt jedes Paket beim Senden und Empfangen, statt dass "
      + "Software das tut. Dadurch fallen alle Verzögerungen in Betriebssystem und Treibern weg. "
      + "Gebraucht wird PTP in der Industrie, im Mobilfunk, im Hochfrequenzhandel und im "
      + "Rundfunk – dort für Audio über IP: AES67 (Dante nur im AES67-Modus), Ravenna. "
      + "**Im Homelab** ist es spannend für Audio-over-IP, Messaufbauten "
      + "und zum Lernen. Für normale PCs reicht NTP völlig. Hinweis: Natives Dante nutzt PTPv1 – "
      + "dieser Server (linuxptp) spricht nur PTPv2, Dante-Geräte müssen also im AES67-Modus laufen.",
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
  ptp_profile: {
    title: "PTP-Profil",
    text: "Ein Profil ist ein Satz passender Grundwerte, damit dieser Server mit bestimmten Geräten "
      + "zusammenspielt. Felder, die du selbst änderst, haben Vorrang. "
      + "**Standard** (IEEE 1588 Default-Profil): passt für Linux-Clients mit linuxptp und die meisten "
      + "Messaufbauten. "
      + "**AES67** (Audio über IP, auch Ravenna und Dante im AES67-Modus): UDPv4, End-to-End, 8 Sync "
      + "pro Sekunde, Announce alle 2 s und DSCP 46 (EF), damit Switches die Pakete bevorzugen. "
      + "**gPTP** (IEEE 802.1AS für AVB/TSN, Automotive): Ethernet direkt (L2), Peer-to-Peer-"
      + "Laufzeitmessung und die Werte aus linuxptp `gPTP.cfg` – jeder Switch im Weg muss 802.1AS "
      + "beherrschen. Alle Teilnehmer im Netz müssen dasselbe Profil nutzen.",
  },
  utc_offset: {
    title: "UTC-Offset",
    text: "PTP zählt in TAI (Atomzeit ohne Schaltsekunden). Derzeit liegt TAI 37 Sekunden vor "
      + "UTC – dieser Wert wird mitgeteilt, damit Clients umrechnen können.",
  },
  phc: {
    title: "PTP-Hardwareuhr (PHC)",
    text: "Eine eigene Uhr auf der Netzwerkkarte, z. B. `/dev/ptp0`. ptp4l stellt diese Uhr, "
      + "phc2sys koppelt sie mit der Systemuhr – als Grandmaster Systemuhr → Karte, als Slave "
      + "Karte → Systemuhr.",
  },
  phc2sys: {
    title: "phc2sys",
    text: "Koppelt die Systemuhr mit der PTP-Uhr der Netzwerkkarte (nur bei Hardware-Zeitstempeln, "
      + "eingeschaltet mit `PHC2SYS_ENABLE=true`); die Richtung wählt ntp-gui je nach Rolle selbst. "
      + "**Als Grandmaster ist phc2sys Pflicht:** Es kopiert die von chrony nach GPS/NTP gestellte "
      + "Systemuhr in die Uhr der Karte, chrony regelt dabei weiter die Systemuhr. Ohne phc2sys "
      + "läuft die Kartenuhr frei und ptp4l verteilt eine falsche Zeit. "
      + "**Als Slave** stellt phc2sys die Systemuhr nach der PTP-Zeit (alternativ liest chrony die "
      + "Kartenuhr selbst über `PHC_REFCLOCK`). Mit phc2sys läuft chrony mit `-x` "
      + "und liefert die Zeit nur noch aus – zwei Regler an derselben Uhr würden sich gegenseitig "
      + "stören. Bei Software-Zeitstempeln gibt es keine Kartenuhr; phc2sys startet dann nicht.",
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
  client_address: {
    title: "Adresse des Clients",
    text: "Die IP-Adresse, von der die Anfragen kamen. Läuft der Container im Bridge-Netz (ohne "
      + "`network_mode: host`), sieht chrony wegen NAT oft nur die Adresse des Docker-Gateways – "
      + "dann erscheinen alle Geräte als eine Zeile. Für echte Client-Adressen den Host-Netzmodus "
      + "nutzen.",
  },
  client_packets: {
    title: "Anfragen",
    text: "Wie viele NTP-Anfragen dieses Gerät gestellt hat, seit chrony läuft. chrony beginnt bei jedem "
      + "Neustart (z. B. nach dem Speichern von Einstellungen) von vorn. Kennt chrony ein Gerät noch nicht "
      + "wieder, zeigt ntp-gui den Wert der eigenen Messung, markiert mit *.",
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
    text: "Wann das Gerät zuletzt gefragt hat. Mit * stammt der Wert aus der eigenen Messung von ntp-gui, "
      + "weil chrony seine Liste beim letzten Neustart geleert hat. Ohne Messung und ohne chrony-Eintrag "
      + "steht „–“.",
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
  setup_accuracy: {
    title: "Genauigkeit eines Aufbaus",
    text: "Typische Abweichung der Uhr dieses Servers zu UTC im eingeschwungenen Zustand. Clients "
      + "im LAN liegen per NTP noch etwa **0,1–1 ms** darüber, per PTP mit Hardware-Zeitstempeln im "
      + "Bereich von Mikrosekunden. Die Werte sind Richtgrößen: Leitung, Last und Hardware "
      + "verschieben sie.",
  },
  settings_source: {
    title: "Herkunft einer Einstellung",
    text: "**Standard**: eingebauter Wert. **Umgebung**: gesetzt per Umgebungsvariable in der "
      + "Compose-Datei. **Dashboard**: hier gespeichert – hat Vorrang vor der Umgebung. "
      + "„Zurücksetzen“ entfernt den Dashboard-Wert, dann gilt wieder Umgebung bzw. Standard.",
  },
  web_title: {
    title: "Titel des Dashboards",
    text: "Steht oben links und im Browser-Tab. Praktisch, wenn mehrere Zeitserver laufen – z. B. "
      + "„Zeitserver Keller“ und „Zeitserver Büro“. Wirkt sofort, ohne Neustart.",
  },
  web_refresh: {
    title: "Aktualisierung",
    text: "Wie oft das Dashboard neue Werte vom Server holt (Standard **5 s**). Kürzer wirkt lebendiger, "
      + "kostet aber etwas mehr Last auf kleinen Geräten wie dem Raspberry Pi. Ändert nichts an der "
      + "Zeitsynchronisation selbst.",
  },
  history_interval: {
    title: "Messintervall für Diagramme",
    text: "Alle wie viele Sekunden ein Messpunkt für die Verlaufsdiagramme gespeichert wird (Standard "
      + "**10 s**). Kürzer zeigt mehr Details, füllt aber die Datenbank schneller; die Werte werden für "
      + "längere Zeiträume ohnehin zusammengefasst. chrony misst davon unabhängig.",
  },
  allow_networks: {
    title: "Erlaubte Netze",
    text: "Nur Geräte aus diesen Netzen bekommen eine NTP-Antwort, alle anderen werden still ignoriert. "
      + "Standard sind alle **privaten Netze** (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, IPv6 ULA "
      + "und Link-Local). Ein Netz pro Zeile in CIDR-Schreibweise. `all` erlaubt jedem – nur sinnvoll, "
      + "wenn eine Firewall davor sitzt, sonst kann der Server für Angriffe missbraucht werden.",
  },
  gps_show_position: {
    title: "Position anzeigen",
    text: "Der GPS-Empfänger kennt seine Position auf wenige Meter genau – und damit den **Standort** "
      + "dieses Servers. Deshalb ist die Anzeige standardmäßig **aus**: Dashboard und API zeigen dann "
      + "keine Koordinaten. Für die Zeit spielt die Position keine Rolle. Das Diagnosepaket entfernt "
      + "Koordinaten unabhängig von dieser Einstellung immer.",
  },
  settings_export: {
    title: "Sicherung der Einstellungen",
    text: "„Exportieren“ lädt die hier gespeicherten Werte als JSON-Datei herunter, **ungefiltert** und ohne "
      + "Passwort – gedacht als Sicherung oder zum Übertragen auf einen zweiten Server. Sie enthält "
      + "Servernamen, Hostnamen und Netze im Klartext. Für einen Fehlerbericht ist das **Diagnosepaket** "
      + "auf der Seite „Diagnose“ gedacht: Es filtert solche Angaben heraus und zeigt vorher eine Vorschau.",
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
  { title: "Übersicht und Diagramme", keys: ["overview_verdict", "overview_hints", "overview_best_source",
    "overview_restarts", "overview_events", "chart_stats"] },
  { title: "Grundlagen", keys: ["ntp", "chronyd", "services", "stratum", "island", "minsources", "dhcp42", "clock_control", "local_orphan",
    "setup_accuracy"] },
  { title: "Werte der Systemuhr", keys: ["reference", "system_offset", "uncertainty", "rms_offset", "frequency",
    "skew", "root_delay", "root_dispersion", "leap", "leap_source", "update_interval", "ref_time"] },
  { title: "Zeitquellen", keys: ["source_type", "hostname_vs_ip", "poll", "reach", "last_rx", "source_offset",
    "jitter", "interval", "samples", "score", "select_options", "server_reference"] },
  { title: "Warum eine Quelle (nicht) genutzt wird", keys: ["select_reason", "state_best", "state_combined",
    "state_not_combined", "state_falseticker", "state_jittery", "state_unreachable", "sel_best", "sel_combined",
    "sel_not_combined", "sel_falseticker", "sel_jittery", "sel_large_distance",
    "sel_distance", "sel_not_preferred", "sel_noselect", "sel_missing_samples", "sel_waits_others",
    "sel_unsynchronised", "sel_stale", "sel_waits_update", "sel_not_trusted", "sel_orphan"] },
  { title: "NTP-Details je Server", keys: ["peer_delay", "peer_dispersion", "response_time", "precision",
    "jitter_asymmetry", "ntp_tests", "interleaved", "timestamping", "packets"] },
  { title: "NTS", keys: ["nts", "nts_authenticated", "nts_ke", "nts_cookies", "nocerttimecheck", "nts_server",
    "nts_server_files", "nts_server_name", "nts_cert_expiry", "nts_cert_subject", "nts_cert_issuer",
    "nts_ke_server", "nts_auth_packets"] },
  { title: "GPS", keys: ["gps", "gps_value", "gps_offset", "gps_delay", "gps_role", "gps_recalibrate", "pps",
    "fix", "satellites", "dop", "snr", "skyplot", "gnss", "time_error", "cold_start"] },
  HELP_GROUP_GNSS,
  HELP_GROUP_AUTOCAL,
  { title: "PTP", keys: ["ptp", "ptp_vs_ntp", "ptp_requirements", "grandmaster", "port_state",
    "offset_from_master", "mean_path_delay", "steps_removed", "clock_class", "clock_accuracy", "ptp_domain",
    "ptp_transport", "ptp_profile", "utc_offset", "phc", "phc2sys", "ptp_servo", "ptp_rms", "ptp_freq"] },
  { title: "Clients", keys: ["client_address", "client_packets", "client_dropped", "client_interval", "client_last", "served_rate"] },
  HELP_GROUP_CLIENTS,
  { title: "Einstellungen", keys: ["settings_source", "settings_export", "web_title", "web_refresh", "history_interval",
    "allow_networks", "gps_show_position"] },
  HELP_GROUP_API,
  HELP_GROUP_NOTIFY,
  HELP_GROUP_DNS,
  HELP_GROUP_UHR,
  HELP_GROUP_UPDATE,
  HELP_GROUP_WEB,
  HELP_GROUP_DIAGNOSE,
  HELP_GROUP_HARDWARE,
];

Object.assign(HELP, HELP_HARDWARE);
Object.assign(HELP, HELP_CLIENTS);
Object.assign(HELP, HELP_AUTOCAL);
Object.assign(HELP, HELP_DIAGNOSE);
Object.assign(HELP, HELP_API);
Object.assign(HELP, HELP_NOTIFY);
Object.assign(HELP, HELP_DNS);
Object.assign(HELP, HELP_UHR);
Object.assign(HELP, HELP_UPDATE);
Object.assign(HELP, HELP_GNSS);
Object.assign(HELP, HELP_WEB);
