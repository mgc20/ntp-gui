// Erklärungen zu „GPS ohne PPS und schwacher Empfang“ (1.5): Empfangsbewertung, Rolle des GPS
// mit Fehlerschranke, Antennen-Test und Praxistipps. Wird in help.js in HELP übernommen; die
// Schlüssel stehen gesammelt in HELP_GROUP_GNSS, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_GNSS = {
  gpsq_assessment: {
    title: "Empfangsbewertung (24 h)",
    text: "Fasst die letzten 24 Stunden aus dem gespeicherten Verlauf zusammen: Wie viel der Zeit hatte der "
      + "Empfänger einen Fix, wie oft kam und ging er, wie stark sind die Signale, wie viele Satelliten nutzt "
      + "er. **Grün**: stabiler Empfang. **Gelb**: brauchbar, aber mit Lücken – als Rückfallebene in Ordnung. "
      + "**Rot**: zu schwach für eine verlässliche Zeitquelle. Der Satz darunter nennt jeweils den Grund. "
      + "Ehrlich gesagt: Software macht schwachen Empfang nicht stärker – helfen kann nur ein besserer Platz "
      + "für die Antenne (siehe Tipps).",
  },
  gpsq_fix_share: {
    title: "Fix-Anteil",
    text: "Anteil der Messzeit mit 2D- oder 3D-Fix. Ohne Fix liefert gpsd keine verlässliche Zeit, chrony "
      + "verwirft das GPS dann. **Ab 98 %** gut, **unter 80 %** zu lückenhaft. In Klammern der Anteil mit "
      + "3D-Fix (mindestens 4 Satelliten).",
  },
  gpsq_changes: {
    title: "Fix-Wechsel je Stunde",
    text: "Wie oft der Fix kam oder ging – gezählt erst, wenn ein neuer Zustand zwei Messpunkte in Folge "
      + "hält, ein einzelner Ausreißer zählt nicht. **Unter 0,5/h** ruhig, **über 4/h** flattert der Empfang. "
      + "Typisch für einen USB-Stick drinnen hinter der Scheibe.",
  },
  gpsq_cn0: {
    title: "Signalstärke der vier stärksten (C/N0)",
    text: "Median des Signal-Rausch-Abstands (dB-Hz) der vier stärksten empfangenen Satelliten. Vier, weil "
      + "der Empfänger für einen Fix vier braucht – schwache Satelliten am Horizont ziehen den Wert so nicht "
      + "herunter. **Ab 30 dB-Hz** gut (draußen typisch 40–48), **unter 22** kaum nutzbar. Bei Messpunkten "
      + "von vor 1.5 steht hier der Mittelwert der genutzten Satelliten.",
  },
  gpsq_used: {
    title: "Genutzte Satelliten (Median)",
    text: "Wie viele Satelliten der Empfänger im Median für den Fix nutzt, solange er einen hat. **Ab 6** "
      + "gibt es Reserve, **unter 4** keinen 3D-Fix. Ein VK-162 (u-blox 7) nutzt ab Werk nur GPS – neuere "
      + "Module sehen mit Galileo und BeiDou deutlich mehr.",
  },
  gpsq_unstet: {
    title: "Fix gerade: stetig oder unstet",
    text: "Kommt und geht der Fix mindestens **sechsmal in 30 Minuten**, gilt der Empfang als **unstet**. "
      + "Dann gibt es **ein** Ereignis „GPS-Empfang unstet“ mit Zählung statt Dutzender Paare „verloren/wieder "
      + "da“. Die Folge für chrony: Das GPS ist oft unbrauchbar, chrony stellt die Uhr dann nach den "
      + "Netzwerkquellen – **das ist richtig so**. Nach einer Stunde ohne Wechsel kommt ein Abschlussereignis "
      + "mit der Zahl der Wechsel. **Ab 1.5.4** merkt sich ntp-gui den schwachen Empfang 24 Stunden lang (auch nach "
      + "einem Neustart, aus der 24-h-Bewertung): So lange gibt es keine Einzelmeldungen „verloren/wieder da“, "
      + "sondern höchstens eine Info-Zeile je Stunde, z. B. „GPS-Fix 7-mal verloren in der letzten Stunde, "
      + "zusammen 23 min ohne Fix“ – flattert es weiter, wird das Fenster bis 6 Stunden länger. Eine **Warnung** "
      + "gibt es, wenn das GPS gebraucht wird (keine brauchbare Netzquelle, GPS/PPS ausgewählt oder PPS "
      + "eingerichtet) und der Fix **10 Minuten am Stück** fehlt; tragen die Netzquellen die Zeit, steht ein "
      + "Ausfall erst nach einer Stunde als Info im Protokoll. Bei "
      + "**stetig** steht dahinter, wie viele Fix-Wechsel es in der letzten halben Stunde trotzdem gab (unter sechs).",
  },
  gpsq_basis: {
    title: "Datenbasis",
    text: "Messzeit und Zahl der Messpunkte, aus denen die Bewertung stammt. Lücken über 5 Minuten (Neustart, "
      + "gpsd weg) zählen nicht. Unter 30 Minuten gibt es noch kein Urteil; belastbar wird es nach einem ganzen "
      + "Tag, weil die Satelliten im Lauf des Tages wandern.",
  },
  gpsq_tips: {
    title: "Tipps für besseren Empfang",
    text: "**USB-Verlängerung ans Fenster**: Ein 2–3 m langes USB-2-Kabel bringt den Stick an die Scheibe oder "
      + "aufs Fensterbrett – oft der größte Gewinn. **USB 3 stört das GPS-Band**: USB-3-Ports, -Kabel und "
      + "-SSDs strahlen im Bereich um 1,5 GHz ab, genau dort sendet GPS (L1, 1575 MHz). Abstand halten, einen "
      + "USB-2-Port nehmen oder ein Verlängerungskabel. **Beschichtetes Glas dämpft stark**: Wärmeschutz- und "
      + "Sonnenschutzverglasung (Metallschicht) und Metalldächer schlucken viel Signal; ein Platz mit Blick zum "
      + "Himmel ohne solche Scheibe oder draußen ist deutlich besser. **Freie Sicht nach Süden** (in Mitteleuropa "
      + "stehen dort mehr Satelliten). Mit dem Antennen-Test unten siehst du, ob ein Umstellen wirklich hilft.",
  },
  gpsq_role: {
    title: "Rolle des GPS",
    text: "**Rückfallebene** (ohne PPS, Standard): chrony nimmt die Netzwerkquellen, solange sie besser sind, "
      + "und übernimmt das GPS von selbst, wenn das Internet schlecht wird oder ausfällt (Mobilfunk, Störung, "
      + "Insel). Das klappt, weil ntp-gui dem GPS eine **ehrliche Fehlerschranke** gibt. **Referenz**: mit PPS "
      + "(genauer als jede Internetquelle) oder wenn du „bevorzugen“ gewählt hast. **Nur beobachten**: deine "
      + "bewusste Wahl in den Einstellungen – das GPS wird gemessen, aber nie genutzt, auch nicht bei einem "
      + "Internetausfall. ntp-gui schlägt das nie von selbst vor. „Gerade genutzt“ heißt: chrony stellt die "
      + "Uhr im Moment (auch) nach dem GPS.",
  },
  gpsq_bound: {
    title: "Fehlerschranke",
    text: "So weit darf die GPS-Zeit laut chrony danebenliegen (die Hälfte des Refclock-„delay“). chrony "
      + "vergleicht diese Schranke mit der der Netzwerkquellen und nimmt die genauere. Zu klein (z. B. "
      + "Delay 0,03 s bei ± 60 ms Streuung) wählt chrony das GPS, obwohl gute NTS-Quellen da sind; zu groß "
      + "verschenkt nichts, solange das Netz gut ist – fällt es aus, nimmt chrony das GPS trotzdem.",
  },
  gpsq_bound_mode: {
    title: "Herkunft der Fehlerschranke",
    text: "**Gemessen**: aus der Streuung des GPS gegen deine genutzten Netzwerkquellen über die letzten "
      + "6 Stunden (95 % der Abweichungen liegen innerhalb, mindestens ± 10 ms). Auch Werte, die chrony als "
      + "Falschgeber („x“) verworfen hat, zählen mit – gerade sie zeigen, wie weit das GPS danebenliegen kann. "
      + "Hat chrony das GPS gewählt, dienen die übrigen erreichbaren Netzquellen als Vergleich. **Vorsichtiger Standard**: "
      + "± 100 ms, bis genug gemessen ist. **Von Hand**: Delay und Auflösung aus den Einstellungen. **Mit "
      + "PPS** zählt der Impuls, die NMEA-Zeit nummeriert nur die Sekunden – aber nur, wenn das PPS-Gerät "
      + "wirklich da ist; fehlt es, gilt das GPS als „ohne PPS“. Umstellen: Einstellungen → GPS → "
      + "„Fehlerschranke ohne PPS“.",
  },
  gpsq_spread: {
    title: "Gemessene Streuung",
    text: "Wie weit das GPS von den genutzten Netzwerkquellen abweicht: das 95-%-Quantil der Abweichungen, "
      + "mindestens der Median plus dreimal die robuste Streuung (MAD). Ein noch nicht kalibrierter Versatz "
      + "zählt mit – er ist genauso ein Fehler wie Rauschen. Gemessen wird stündlich. **Größer** wird die "
      + "Schranke, sobald die Streuung sie übersteigt (höchstens einmal je Stunde, mit etwas Reserve, damit "
      + "chronyd nicht ständig neu startet) – eine zu kleine Schranke wäre unehrlich. **Kleiner** nur, wenn die "
      + "neue Schranke höchstens 0,6 × die jetzige ist, auch die Streuung der **letzten 48 Stunden** (nicht nur "
      + "der letzten 6) mit Reserve hineinpasst – sonst pendelte sie nach einer ruhigen Nacht hin und her –, "
      + "und frühestens nach 12 h. Jede Änderung steht im Ereignisprotokoll "
      + "und startet chronyd kurz neu. **Nach einer Offset-Änderung** (von Hand, „zurücksetzen“ oder automatische "
      + "Kalibrierung) zählen nur noch Messwerte ab der Änderung (plus 15 Minuten für den Neustart) – ältere "
      + "passen nicht mehr zum laufenden Offset. Kleiner werden darf die Schranke dann schon, sobald 5,5 Stunden "
      + "Messung nach der Änderung vorliegen (fast das ganze 6-h-Messfenster), statt erst nach 12 h.",
  },
  gpsq_bound_check: {
    title: "Letzte Prüfung",
    text: "Wann die Streuung zuletzt geprüft wurde und was daraus folgte. „Auf Standard zurücksetzen“ setzt "
      + "die Schranke auf ± 100 ms zurück (mit Ereignis). Größer kann sie danach jederzeit werden, kleiner "
      + "frühestens nach 12 Stunden – sonst setzte die nächste stündliche Prüfung sofort wieder die alte. "
      + "Dauerhaft abschalten: „Fehlerschranke ohne PPS: von Hand“.",
  },
  gpsq_antenna: {
    title: "Antennen-Test",
    text: "Misst 5 Minuten lang Fix-Anteil, Signalstärke und Satelliten. Danach den Empfänger umstellen (anderes "
      + "Fenster, Verlängerung, anderer USB-Port) und erneut messen – die Tabelle vergleicht beide Messungen. "
      + "Die Messung bleibt auf diesem Gerät: Satellitenwinkel und Position werden dafür weder gespeichert noch "
      + "exportiert, sie ist auch nicht Teil des Diagnosepakets. Tipp: zu ähnlichen Uhrzeiten vergleichen, "
      + "die Satelliten wandern im Lauf des Tages.",
  },
  gpsq_antenna_label: {
    title: "Name der Messung",
    text: "Damit du die Messungen auseinanderhältst, z. B. „Fensterbank“ oder „Schrank, USB 3“. Höchstens 40 "
      + "Zeichen: Buchstaben, Ziffern, Leerzeichen und .,:;+()/#'-",
  },
  gpsq_antenna_compare: {
    title: "Vergleich zweier Messungen",
    text: "Spalte „B − A“ zeigt, um wie viel die zweite Messung besser (+) oder schlechter (−) ist. Das Ergebnis "
      + "gewichtet: 3 dB-Hz mehr Signal, 5 Prozentpunkte mehr Fix oder 2 genutzte Satelliten mehr zählen je "
      + "einen Punkt; ab einem Punkt Unterschied nennt es den besseren Platz, sonst „kaum Unterschied“.",
  },
  gpsq_antenna_list: {
    title: "Gespeicherte Messungen",
    text: "Die letzten 20 Messungen, neueste oben. „Abgebrochen“ heißt: vor Ablauf der 5 Minuten gestoppt – "
      + "die Werte gelten, sind aber weniger belastbar.",
  },
  gpsq_tracked: {
    title: "Empfangene Satelliten",
    text: "Satelliten mit messbarem Signal (C/N0 über 0) – mehr als genutzt, weil der Empfänger schwache "
      + "oder gerade erst gefundene Satelliten noch nicht für den Fix verwendet.",
  },
  gpsq_strong: {
    title: "Starke Satelliten",
    text: "Satelliten mit mindestens 30 dB-Hz. Davon sollten für einen stabilen Fix vier oder mehr da sein.",
  },
  gnss_guard: {
    title: "Störungserkennung (Jamming/Spoofing)",
    text: "GPS lässt sich stören (**Jamming**: ein Störsender übertönt die schwachen Satellitensignale) und fälschen "
      + "(**Spoofing**: ein Sender spielt falsche Satelliten vor – samt falscher Zeit). ntp-gui prüft laufend fünf "
      + "Muster, die mit **jedem** Empfänger gehen, auch mit dem VK-162: Signaleinbruch aller Satelliten, unnatürlich "
      + "gleichmäßige Signale, chronys Urteil, GPS-Zeit gegen die NTS-Quellen und Positionssprung. Gelesen wird nur aus "
      + "gpsd und chrony; auf den Empfänger wird nichts geschrieben. **Ehrliche Grenze:** Langsames Spoofing, das die "
      + "Zeit unterhalb der Netz-Unsicherheit (einige ms) verschiebt, ist so nicht erkennbar.",
  },
  gnss_stage: {
    title: "Stufen: Hinweis, Warnung, Störung",
    text: "**Hinweis**: ein schwaches Signal (Signaleinbruch, gleichmäßige Signale oder Falseticker) – oft harmlos: "
      + "Schnee, ein Flugzeug, ein Lkw vor dem Fenster. **Warnung**: zwei schwache Signale zugleich. **Störung**: ein "
      + "starkes Signal – Zeitabweichung zu den NTS-Quellen oder Positionssprung. Ein Signal zählt erst, wenn es "
      + "mehrmals hintereinander anschlägt, und erlischt erst nach 2 bzw. 5 Minuten ohne Befund (Hysterese). Ins "
      + "Protokoll kommt alles; benachrichtigt wird standardmäßig nur bei „Störung“ – sonst lernt man, Alarme zu "
      + "ignorieren.",
  },
  gnss_cn0_drop: {
    title: "Gleichzeitiger Signaleinbruch (C/N0)",
    text: "Fällt die Signalstärke der meisten Satelliten **innerhalb einer Minute um 6 dB oder mehr**, ist das typisch "
      + "für einen Störsender in der Nähe (oder etwas, das die Antenne plötzlich abdeckt). Verglichen wird jeder "
      + "Satellit mit sich selbst vor 15–60 s; gezählt werden nur Satelliten, die vorher mindestens 20 dB-Hz hatten. "
      + "Ein **langsamer** Abfall über Minuten bis Stunden – Schnee oder Eis auf der Antenne – zählt nicht. Allein "
      + "ist das nur ein „Hinweis“, und es sperrt das GPS nie: Bei Fix-Verlust schaltet chrony ohnehin aufs Netz.",
  },
  gnss_uniform: {
    title: "Unnatürlich gleichmäßige Signale",
    text: "Echte Satelliten stehen verschieden hoch am Himmel – ihre Signale unterscheiden sich um viele dB. Ein "
      + "einfacher Spoofer sendet alle Signale aus einer Antenne, sie kommen deshalb fast gleich stark an. "
      + "Angeschlagen wird bei mindestens 6 Satelliten mit weniger als 1 dB Streuung (Spanne ≤ 3 dB).",
  },
  gnss_falseticker: {
    title: "Urteil von chrony",
    text: "chrony vergleicht alle Quellen. Liegt das GPS dauerhaft außerhalb dessen, worauf sich die übrigen Quellen "
      + "einigen, markiert chrony es als **Falseticker** und nutzt es nicht. Kurzzeitig ist das ein schwaches Signal: Es kann "
      + "auch an einer zu kleinen Fehlerschranke liegen. Hält es **5 Minuten** an und widersprechen mindestens zwei "
      + "**NTS-Quellen**, zählt es als starkes Signal (Stufe „Störung“) – das fängt auch eine Fälschung, die die Zeit "
      + "so langsam wegzieht, dass der Zeitabgleich mitwandert. **Ausnahme ohne PPS:** War das GPS seit dem Start bzw. "
      + "seit einer Änderung der GPS-Einstellungen (Offset, Gerät, Name) noch nie 15 Minuten lang brauchbar und gleich "
      + "Falseticker – typisch nach „Offset zurücksetzen“: „gleichbleibend rund +51 ms“ –, ist das **vermutlich ein "
      + "Kalibrierfehler**. Solange die GPS-Zeit bei diesem Abstand bleibt (innerhalb der Zeitschwelle, mindestens 20 ms), "
      + "bleibt es beim „Hinweis“ mit dem Rat, den Offset zu kalibrieren (GPS-Seite → „GPS kalibrieren“; ohne PPS "
      + "erledigt das die automatische Kalibrierung nach etwa 6 Stunden); es sperrt nie und benachrichtigt nur, wenn "
      + "du „Hinweis – jeder Befund“ gewählt hast. Wandert die GPS-Zeit weiter weg oder liegt sie mehr als 1 s daneben, "
      + "gilt wieder die Regel oben. Stimmt der Versatz nach dem Kalibrieren nicht, Antenne und Umgebung prüfen. **Mit "
      + "PPS** gibt es diese Ausnahme nicht; dort nummeriert die NMEA-Zeile nur die Sekunden, die Zeit kommt vom PPS. "
      + "Nutzt chrony die PPS-Quelle und liegt die NMEA-Zeit unter 0,5 s neben dem Netz, bleibt ihr Falseticker ein "
      + "Hinweis. Eine Fälschung verschiebt auch das PPS – dann ist die PPS-Quelle selbst nicht mehr genutzt, und es "
      + "gilt die Regel oben. Grenze: Eine Fälschung, die schon beim Start oder genau nach einer Änderung "
      + "einsetzt und die Zeit nur um einen festen Betrag verschiebt, sieht aus wie ein Kalibrierfehler – sie fällt erst "
      + "mit einem Zeit- oder Positionssprung auf.",
  },
  gnss_time: {
    title: "GPS-Zeit gegen die Netzquellen",
    text: "Der Abstand der GPS-Zeit zum **Median von mindestens zwei NTS-Quellen** (ohne NTS: drei normale "
      + "Netzquellen). Weil ein GPS ohne PPS einen festen Versatz und Streuung hat, zählt die Abweichung von der "
      + "**gewohnten** Lage. Verglichen wird mit einem **Anker**: Er beginnt beim Median der ersten Minuten und folgt "
      + "der Lage der letzten 30 Minuten höchstens 10 ms pro Stunde. Schwelle ist das Fünffache der gewohnten "
      + "Streuung, mindestens 20 ms, höchstens 100 ms. Ein Sprung von 50 ms fällt so in unter einer Minute auf; eine "
      + "Fälschung, die die Zeit langsam wegzieht (0,5–2 ms pro Minute), nach etwa ein bis zwei Stunden – statt "
      + "unbemerkt in die Grundlinie zu wandern. Solange der Befund anhält, lernt die Erkennung nichts dazu: Eine "
      + "Fälschung, die bleibt, wird nie zur neuen Normalität. Der Anker (nur ein Zeitabstand, kein Ort) wird "
      + "gespeichert und gilt nach einem Neustart weiter; änderst du Offset, Gerät oder Namen des GPS, wird er neu "
      + "gelernt. Ein starkes Signal: Es "
      + "führt zur Stufe „Störung“ und – mit „automatisch sperren“ – zur GPS-Sperre. Eine **Abweichung** wie diese "
      + "kann auch eine falsche NTS-Quelle bedeuten; darum zählt der Median mehrerer.",
  },
  gnss_position: {
    title: "Positionssprung",
    text: "Ein Zeitserver steht still. Springt die gemeldete Position um **mehr als 100 m** (und mehr als das Dreifache "
      + "der vom Empfänger geschätzten Ungenauigkeit), ist das ein starkes Zeichen für Spoofing. Gezählt werden nur "
      + "**verlässliche** Fixe – 3D, mindestens 5 genutzte Satelliten, HDOP höchstens 4 (ohne HDOP: geschätzte "
      + "Ungenauigkeit höchstens 50 m) –, für die Referenz wie für den Vergleich, und der Sprung muss über "
      + "mindestens 5 solche Fixe und 50 Sekunden anhalten. Drinnen (2D/3D im Wechsel, 3–4 Satelliten, HDOP 5–20) "
      + "streut die Position um 100 m und mehr – das ist kein Spoofing; ein Spoofer liefert dagegen ein sauberes "
      + "Signal mit guter Geometrie und fällt weiter auf. Die Referenz folgt einem echten Umzug höchstens 20 m pro Stunde und bleibt während eines Sprungs "
      + "eingefroren – ein langsames Wegziehen fällt so ebenfalls auf. Fehlen nach einem Befund die Daten (kein "
      + "3D-Fix, GPS unerreichbar), erlischt er nach 10 Minuten mit „keine Messwerte mehr“. **Datenschutz:** Die Referenzposition liegt nur im Arbeitsspeicher von ntp-gui – sie wird nie "
      + "gespeichert, nie angezeigt und nie exportiert. Hier, im Protokoll und in Benachrichtigungen steht nur die "
      + "Abweichung in Metern (auf 10 m gerundet).",
  },
  gnss_mode: {
    title: "Verhalten bei Störung",
    text: "**Nur melden** (Standard): Ereignis im Protokoll und – ab „Störung“ – Benachrichtigung. **Automatisch "
      + "sperren** (opt-in): bei einem starken Befund wählt ntp-gui das GPS (und PPS) per `chronyc selectopts "
      + "+noselect` ab – aber nur, wenn mindestens zwei andere erreichbare Netzquellen auswählbar bleiben. Ohne "
      + "sie liefe die Uhr ohne jede Quelle frei; dann steht nur „Sperre ausgelassen“ im Protokoll. Erst "
      + "Praxisdaten sammeln, dann einschalten. Einstellbar unter Einstellungen → GPS.",
  },
  gnss_lock: {
    title: "GPS-Sperre",
    text: "Gesperrt heißt: chrony misst das GPS weiter, wählt es aber nicht als Zeitquelle (`selectopts +noselect`) "
      + "und hält sich an die Netzquellen. **Automatisch** gesperrt wird nur bei starken Befunden; freigegeben wird "
      + "nach 30 Minuten ohne Befund – höchstens dreimal hintereinander, die vierte Sperre bleibt bis zur Freigabe "
      + "von Hand. **Von Hand** gesperrt bleibt sie, bis du sie aufhebst. Der Schalter überlebt keinen Neustart von "
      + "chronyd – deshalb wählt der Supervisor das GPS direkt nach jedem Start von chronyd (auch nach dem Speichern "
      + "von Einstellungen) wieder ab, bevor die erste GPS-Messung da ist. Von Hand sperren ohne andere auswählbare "
      + "Quelle geht nur nach einer zweiten Bestätigung: Die Uhr liefe dann frei. "
      + "Jede Sperre und Freigabe steht im Ereignisprotokoll. Bleibt das GPS gesperrt und ist **6 Stunden lang keine "
      + "andere auswählbare Quelle** da, kommt einmal je Sperre die Störungsmeldung „GPS gesperrt, Uhr läuft frei“ "
      + "(siehe „Uhr läuft frei“).",
  },
  gnss_freerun: {
    title: "GPS gesperrt, Uhr läuft frei",
    text: "Das GPS ist gesperrt, und chrony hat keine andere auswählbare Zeitquelle – keine Netzquelle ist erreichbar "
      + "oder alle sind abgewählt. Dann stellt niemand die Uhr: Sie läuft frei (Holdover) und driftet, bei einem "
      + "Raspberry Pi typisch einige Millisekunden pro Stunde, je nach Temperatur auch mehr. Dauert das **6 Stunden**, "
      + "meldet ntp-gui das einmal als Störung (mit Benachrichtigung). Was tun: Ist die Störung vorbei (Seite GNSS, "
      + "Stufe „unauffällig“), die Sperre aufheben. Sonst eine Netzquelle erreichbar machen (Internet, Firewall, "
      + "DNS). Während eines Holdover-Tests zählt die Zeit nicht – der wählt absichtlich alles ab.",
  },
  gnss_moved: {
    title: "Empfänger umgezogen → Position neu lernen",
    text: "Die Störungserkennung lernt, wo der Empfänger steht, und meldet einen Sprung dieser Position als möglichen "
      + "Angriff (Spoofing). Hast du den Empfänger oder die Antenne **an einen anderen Platz** gestellt – anderes "
      + "Fenster, anderes Stockwerk, anderer Ort – oder einen anderen Empfänger angesteckt, drück „Neu lernen“. Sonst "
      + "meldet sie den Umzug als „Position gesprungen“. Danach lernt sie die neue Position in einigen Minuten mit "
      + "gutem 3D-Fix. Kleine Bewegungen (Stick ein paar Zentimeter verrückt) brauchen das nicht: Gezählt wird erst ein "
      + "Sprung über der Schwelle, der über mehrere gute Fixe anhält. Bei einer Meldung, die du dir nicht erklären kannst, "
      + "nicht neu lernen – erst die Ursache klären.",
  },
  gnss_lock_reason: {
    title: "Grund der Sperre",
    text: "Der Befund, der zur automatischen Sperre geführt hat, oder „von Hand“.",
  },
  gnss_relearn: {
    title: "Neu lernen",
    text: "Vergisst die gelernte Position und den gewohnten Zeitabstand zum Netz. Nötig, wenn du den Empfänger "
      + "umgestellt oder eine andere Antenne angeschlossen hast – sonst hält die Erkennung den Umzug für einen "
      + "Positionssprung. Das Lernen dauert danach einige Minuten. Achtung: Was zum Zeitpunkt des Neulernens "
      + "empfangen wird, gilt danach als normal – bei einem laufenden Befund also erst die Ursache klären. "
      + "Auch die automatische GPS-Kalibrierung beginnt ihre Messung dort neu: Störungsmeldungen davor halten sie "
      + "nicht mehr auf, und den neuen Abstand (anderer Empfänger, andere Verspätung) übernimmt sie nach gut 6 h selbst.",
  },
};

export const HELP_GROUP_GNSS = {
  title: "GPS ohne PPS, Empfang und Störungen",
  keys: ["gpsq_assessment", "gpsq_fix_share", "gpsq_changes", "gpsq_cn0", "gpsq_used", "gpsq_unstet",
    "gpsq_basis", "gpsq_tips", "gpsq_role", "gpsq_bound", "gpsq_bound_mode", "gpsq_spread", "gpsq_bound_check",
    "gpsq_antenna", "gpsq_antenna_label", "gpsq_antenna_compare", "gpsq_antenna_list", "gpsq_tracked", "gpsq_strong",
    "gnss_guard", "gnss_stage", "gnss_cn0_drop", "gnss_uniform", "gnss_falseticker", "gnss_time", "gnss_position",
    "gnss_mode", "gnss_lock", "gnss_freerun", "gnss_lock_reason", "gnss_relearn", "gnss_moved"],
};
