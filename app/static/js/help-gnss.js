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
      + "mit der Zahl der Wechsel.",
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
      + "6 Stunden (95 % der Abweichungen liegen innerhalb, mindestens ± 10 ms). **Vorsichtiger Standard**: "
      + "± 100 ms, bis genug gemessen ist. **Von Hand**: Delay und Auflösung aus den Einstellungen. **Mit "
      + "PPS** zählt der Impuls, die NMEA-Zeit nummeriert nur die Sekunden. Umstellen: Einstellungen → GPS → "
      + "„Fehlerschranke ohne PPS“.",
  },
  gpsq_spread: {
    title: "Gemessene Streuung",
    text: "Wie weit das GPS von den genutzten Netzwerkquellen abweicht: das 95-%-Quantil der Abweichungen, "
      + "mindestens der Median plus dreimal die robuste Streuung (MAD). Ein noch nicht kalibrierter Versatz "
      + "zählt mit – er ist genauso ein Fehler wie Rauschen. Gemessen wird stündlich; chrony bekommt eine neue "
      + "Schranke erst bei einer deutlichen Änderung (Faktor 1,5), größer frühestens nach 1 h, kleiner "
      + "frühestens nach 12 h. Jede Änderung steht im Ereignisprotokoll und startet chronyd kurz neu.",
  },
  gpsq_bound_check: {
    title: "Letzte Prüfung",
    text: "Wann die Streuung zuletzt geprüft wurde und was daraus folgte. „Auf Standard zurücksetzen“ setzt "
      + "die Schranke auf ± 100 ms zurück (mit Ereignis); nach der nächsten Messung passt ntp-gui sie wieder an. "
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
};

export const HELP_GROUP_GNSS = {
  title: "GPS ohne PPS und Empfang",
  keys: ["gpsq_assessment", "gpsq_fix_share", "gpsq_changes", "gpsq_cn0", "gpsq_used", "gpsq_unstet",
    "gpsq_basis", "gpsq_tips", "gpsq_role", "gpsq_bound", "gpsq_bound_mode", "gpsq_spread", "gpsq_bound_check",
    "gpsq_antenna", "gpsq_antenna_label", "gpsq_antenna_compare", "gpsq_antenna_list", "gpsq_tracked", "gpsq_strong"],
};
