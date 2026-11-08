// Erklärungen zu „Zeitserver erzwingen“ und zur passiven Messung der Client-Uhren.
// Wird in help.js in HELP übernommen; die Schlüssel stehen gesammelt in
// HELP_GROUP_CLIENTS, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_CLIENTS = {
  // --- Passive Messung -------------------------------------------------------
  clientmon: {
    title: "Uhren der Clients beobachten",
    text: "Jede NTP-Anfrage enthält die Uhrzeit des Geräts beim Absenden. ntp-gui liest die Anfragen "
      + "mit (es sendet nichts zusätzlich) und vergleicht diese Zeit mit dem Empfangszeitpunkt, den der "
      + "Kernel gestempelt hat. So siehst du, **welche Geräte deinen Server wirklich nutzen** und ob ihre "
      + "Uhr stimmt – ohne auf den Geräten etwas zu installieren. Die Werte bleiben auf dieser Instanz. "
      + "Braucht die Berechtigung `NET_RAW` (in Docker Standard) und echte Client-Adressen, also am "
      + "besten `network_mode: host`.",
  },
  client_offset: {
    title: "Uhr geht falsch um",
    text: "Wie weit die Uhr des Geräts von diesem Server abweicht – geglättet über die letzten Anfragen. "
      + "**Positiv** heißt: die Uhr des Geräts geht vor, **negativ**: sie geht nach. Die Laufzeit des "
      + "Pakets steckt mit drin (im LAN meist unter 1 ms), deshalb sind Werte unter etwa **5 ms** "
      + "praktisch „richtig“. Die Messung zeigt den Stand **vor** der Antwort: Ein Gerät, das gerade "
      + "erst anfängt, deinen Server zu fragen, nähert sich danach Schritt für Schritt an. Bleibt ein "
      + "Wert dauerhaft groß, stellt das Gerät seine Uhr nicht nach (oder fragt nur selten).",
  },
  client_measurable: {
    title: "Messbar?",
    text: "**messbar**: Das Gerät schickt seine echte Uhrzeit mit. **verschleiert**: Das Gerät schreibt "
      + "absichtlich eine Zufallszahl statt seiner Uhrzeit in die Anfrage – chrony, OpenNTPD, NTPsec "
      + "und NTS-Clients machen das, damit niemand im Netz ihre Uhr auslesen kann. Das ist gutes "
      + "Verhalten, nur messen lässt es sich dann nicht. **ohne Zeitstempel**: Das Gerät sendet "
      + "Nullen (manche einfachen SNTP-Clients). **Uhr > 1 Tag daneben**: Die Abweichung ist riesig, "
      + "aber von Anfrage zu Anfrage gleich – das Gerät hat wirklich eine falsche Uhr (z. B. nach "
      + "Stromausfall ohne Pufferbatterie).",
  },
  clientmon_status: {
    title: "Messung der Client-Uhren: Zustand",
    text: "Zeigt, ob die passive Messung läuft. **Nicht verfügbar** heißt meist: Dem Container fehlt "
      + "die Berechtigung `NET_RAW` (wurde per `cap_drop` entfernt) oder die Funktion ist in den "
      + "Einstellungen aus. Im **Bridge-Netz** von Docker kann es passieren, dass alle Anfragen vom "
      + "Docker-Gateway zu kommen scheinen, weil Docker die Absender umschreibt – dann hilft "
      + "`network_mode: host`.",
  },

  // --- Clients 2.0: Detailseite und Netzüberblick ----------------------------------
  client_detail: {
    title: "Ein Gerät im Detail",
    text: "Ein Klick auf ein Gerät in der Liste öffnet seine Seite: wie seine Uhr über die Zeit lag, wie oft "
      + "es fragt, ob es messbar ist (und warum nicht), welche Software vermutlich fragt, sein Name im DNS, "
      + "MAC-Adresse und Hersteller (nur im selben Netz). Alles stammt aus den Anfragen, die das Gerät "
      + "ohnehin schickt – ntp-gui sendet nur dann selbst etwas, wenn du **Aktiv nachmessen** drückst. "
      + "Die Daten bleiben auf dieser Instanz.",
  },
  client_offset_chart: {
    title: "Abweichung über die Zeit",
    text: "Jeder Punkt ist eine Anfrage des Geräts: seine Uhrzeit minus die Uhrzeit dieses Servers beim "
      + "Empfang. Gespeichert wird höchstens alle **2 Minuten** ein Punkt je Gerät, **7 Tage** lang – "
      + "das reicht, um zu sehen, ob ein Gerät langsam wegläuft und dann springt (typisch für Windows "
      + "und IoT-Geräte, die selten nachstellen) oder ruhig dicht an null bleibt. Ein Sägezahn heißt: "
      + "Die Uhr läuft gleichmäßig weg und wird bei jeder Abfrage zurückgestellt. Verschleiert das Gerät "
      + "seine Zeit, bleibt das Diagramm leer.",
  },
  client_interval_chart: {
    title: "Abstand der Anfragen und Poll",
    text: "**Abstand der Anfragen**: wie lange das Gerät zwischen zwei Anfragen wirklich gewartet hat. "
      + "**Poll-Feld**: was das Gerät in die Anfrage schreibt (2^poll Sekunden) – sein eigener Plan. "
      + "chrony und ntpd fragen anfangs oft (64 s) und werden ruhiger, wenn die Uhr stabil läuft; Windows "
      + "fragt meist nur alle paar Stunden bis einmal pro Woche. Logarithmische Achse, damit Sekunden und "
      + "Tage in ein Bild passen.",
  },
  client_typical_interval: {
    title: "Typischer Abstand",
    text: "Der Median der letzten 16 Abstände zwischen zwei Anfragen. Abstände unter **4 s** gelten als "
      + "Schwall (Burst) und zählen nicht, sobald es längere gibt – ntpd mit iburst schickt beim Start acht "
      + "Anfragen im Abstand von 2 s, ntpdate/sntp mehrere hintereinander. Kommen **nur** kurze Abstände, "
      + "steht hier erst nach zwölf davon ein Wert; vorher war es vielleicht nur ein Start-Schwall. "
      + "Unter **8 s** fragt ein Gerät auffällig oft – meist ein Fehler in der Firmware oder ein Client, "
      + "der keine Antwort bekommt und es immer wieder versucht.",
  },
  client_version: {
    title: "NTP-Version",
    text: "Die Protokollversion, die das Gerät in die Anfrage schreibt. Heute üblich ist **4**. **3** "
      + "schicken vor allem Windows und ältere SNTP-Clients – kein Problem, der Server antwortet in "
      + "derselben Version.",
  },
  client_seen: {
    title: "Zuerst und zuletzt gesehen",
    text: "Wann ntp-gui die erste und die letzte Anfrage dieses Geräts mitgelesen hat. Die Werte "
      + "überstehen Neustarts von chrony und vom Container (gespeichert in der Datenbank, 30 Tage). "
      + "**Verstummt** heißt: Das Gerät hat länger als dreimal seinen üblichen Abstand oder über 24 h "
      + "nicht gefragt – ausgeschaltet, anderer Zeitserver oder keine Verbindung.",
  },
  client_rdns: {
    title: "Name aus dem DNS",
    text: "Ist „Namen der Clients per DNS nachschlagen“ eingeschaltet (Standard: aus), fragt ntp-gui den "
      + "DNS nach dem Namen zur Adresse (Reverse-DNS, z. B. „nas.fritz.box“) – höchstens 1 s lang, das "
      + "Ergebnis wird eine Stunde gemerkt. Gefragt wird nur bei privaten Adressen und nur, wenn jeder "
      + "DNS-Server, über den die Frage gehen kann, selbst eine private Adresse hat – nie über DoT/DoH "
      + "oder einen öffentlichen Server (Docker trägt z. B. 8.8.8.8 ein, wenn der Host nur 127.0.0.53 "
      + "kennt). Denn die Frage verrät die Adresse deines Geräts, und die geht niemanden außerhalb "
      + "deines Netzes etwas an. Warum nicht gefragt wurde, steht unter der Gerätetabelle.",
  },
  client_mac: {
    title: "MAC-Adresse und Hersteller",
    text: "Die MAC-Adresse steht im Ethernet-Kopf der Anfrage. Sie ist nur dann die des Geräts, wenn es "
      + "im **selben Netz** steht – kommt die Anfrage über einen Router, wäre es dessen MAC; dann zeigt "
      + "ntp-gui keine. Den Hersteller liest ntp-gui aus einer OUI-Liste, falls eine im Image liegt "
      + "(oder du sie als `/config/oui.txt` einhängst). **Zufällige MAC**: iPhone, Android und Windows "
      + "wählen im WLAN je Netz eine zufällige Adresse – sie verrät keinen Hersteller. MAC-Adressen "
      + "verlassen die Instanz nie (sie werden in jedem Export entfernt).",
  },
  client_vlan: {
    title: "VLAN",
    text: "Die VLAN-Nummer, wenn die Anfrage mit 802.1Q-Markierung ankam. Meist leer: Der Kernel entfernt "
      + "die Markierung, bevor ntp-gui mitliest, oder das Netz nutzt keine VLANs.",
  },
  client_software: {
    title: "Vermutete Client-Software",
    text: "Eine **Vermutung** aus Indizien – kein Beweis. Ausgewertet werden NTP-Version, Poll-Feld, ob "
      + "das Gerät die übrigen Kopffelder ausfüllt, ob es seine Sendezeit verschleiert, der Abstand der "
      + "Anfragen, Hersteller und Namen. Typisch: **Windows** schickt Version 3 mit Poll 10 … 15; "
      + "**chrony, NTPsec, OpenNTPD** verschleiern die Sendezeit; **systemd-timesyncd** und viele "
      + "**IoT-Geräte** (ESP32) füllen nur die Sendezeit aus; **ntpd** schreibt sein eigenes Stratum mit. "
      + "Viele Geräte nutzen dieselbe Bibliothek – zwei Kandidaten mit „möglich“ heißen: nicht zu "
      + "unterscheiden.",
  },
  client_meta: {
    title: "Eigener Name und Notiz",
    text: "Gib Geräten einen Namen, den du wiedererkennst („Drucker Büro“), und eine Notiz. Beides steht "
      + "in der Datenbank dieser Instanz und erscheint in der Liste, im Netzüberblick und in Ereignissen. "
      + "Gespeicherte Ereignisse enthalten nur die **Adresse** – den Namen setzt erst die Anzeige ein. So "
      + "bleibt ein alter Name nach Umbenennen oder Löschen nirgends stehen, und im **Diagnosepaket** wird "
      + "die Adresse zu client-01 usw., ein Name zu `<name>`. **Benachrichtigungen** über ein Gerät "
      + "nennen seinen eigenen Namen statt der Adresse – du sollst auf dem Handy erkennen, welches Gerät "
      + "gemeint ist; die LAN-Adresse nur mit dem Schalter „LAN-Adressen in Nachrichten“. Ohne Namen heißt "
      + "es dort „Gerät ohne Namen“. Notizen werden nie exportiert. Ändern dürfen nur Admins.",
  },
  client_probe: {
    title: "Aktiv nachmessen",
    text: "Schickt **eine** NTP-Anfrage an das Gerät (Port 123, Zeitlimit 2 s, zufälliger Sendezeitstempel – "
      + "sie verrät nichts über diesen Server). Viele Router, NAS und manche Kameras sind selbst "
      + "Zeitserver und antworten; dann siehst du ihre Uhr samt Laufzeit, auch wenn sie ihre Sendezeit "
      + "verschleiern. Die meisten Geräte antworten **nicht** – das ist normal und kein Fehler. Nur für "
      + "Geräte mit privater Adresse, die diesen Server schon gefragt haben; je Gerät höchstens alle "
      + "30 s, insgesamt 10 Messungen pro Minute. Nicht bei IPv6-Adressen mit **fe80::**: Die sind nur "
      + "zusammen mit der Netzwerkschnittstelle eindeutig, und die merkt sich die passive Messung nicht.",
  },
  clients_overview: {
    title: "Netzüberblick",
    text: "Alle Geräte auf einen Blick: wie weit ihre Uhren danebenliegen, welche am weitesten, welche "
      + "verstummt sind und welche auffällig oft fragen. Ein Klick auf ein Gerät öffnet seine Detailseite.",
  },
  clients_histogram: {
    title: "Wie weit gehen die Uhren falsch?",
    text: "Die aktuelle (geglättete) Abweichung jedes messbaren Geräts, in Stufen von jeweils Faktor 10. "
      + "**Unter 1 ms** und **1–10 ms** ist für Menschen und fast alle Anwendungen „richtig“. Ab "
      + "**0,1 s** merkt man es bei Logs und Videoaufnahmen, ab **1 s** stimmt etwas nicht. **Falsche "
      + "Uhr**: mehr als einen Tag daneben, meist nach Stromausfall ohne Pufferbatterie. Geräte, die seit "
      + "über 24 h nicht gefragt haben, zählen nicht mit.",
  },
  clients_worst: {
    title: "Größte Abweichung",
    text: "Die fünf messbaren Geräte, deren Uhr gerade am weitesten von diesem Server abweicht.",
  },
  clients_silent: {
    title: "Verstummt",
    text: "Geräte, die früher gefragt haben, jetzt aber länger als **dreimal ihr üblicher Abstand** "
      + "(mindestens 2 min) oder über **24 h** still sind. Ausgeschaltet, im Urlaub, auf einen anderen "
      + "Zeitserver umgestellt – oder die Anfragen kommen nicht mehr an (Firewall, DHCP-Änderung).",
  },
  clients_chatty: {
    title: "Fragt auffällig oft",
    text: "Geräte, die gerade öfter als alle **8 s** fragen. Normal sind 64 s bis mehrere Stunden. "
      + "Häufige Gründe: Die Antworten kommen nicht an (Hairpin-Problem, Firewall), die Firmware ist "
      + "fehlerhaft, oder mehrere Geräte stecken hinter einer Adresse (NAT).",
  },
  clients_alarm: {
    title: "Alarm bei falsch gehender Client-Uhr",
    text: "Liegt die gemessene Uhr eines Geräts zweimal hintereinander weiter als die Schwelle daneben, "
      + "schreibt ntp-gui das Ereignis „Uhr von … weicht um … ab“ (Art **Clients**, Stufe Warnung). Das "
      + "kann eine Benachrichtigung auslösen. „Wieder im Rahmen“ folgt erst unter der halben Schwelle – "
      + "so meldet ein Gerät an der Grenze nicht ständig hin und her. Nur messbare Geräte zählen.",
  },

  // --- Clients 3 (1.5): Uhrgüte, Regeln, Gruppen, NTS, Gerätepass ------------------
  client_quality: {
    title: "Uhrgüte",
    text: "Eine Zahl von 0 bis 100: Wie gut hält dieses Gerät seine Uhr? Sie fasst vier Dinge zusammen – "
      + "**Abweichung** (bis 35 Punkte), **Stabilität** (Streuung der Messungen, bis 25), **Regelmäßigkeit** "
      + "der Anfragen (bis 20) und **Messbarkeit** (Anteil der Anfragen mit echter Uhrzeit, bis 20). Ab 85 "
      + "„sehr gut“, ab 70 „gut“, ab 50 „mäßig“, darunter „schlecht“. Grundlage sind die letzten 32 Messungen "
      + "(nach einem Neustart die gespeicherten der letzten 24 h); es braucht mindestens 4. Geräte, die ihre "
      + "Zeit verschleiern (chrony, NTS), bekommen **keine** Note – das ist gutes Verhalten, nur messbar ist es nicht.",
  },
  client_quality_parts: {
    title: "Wie die Punkte der Uhrgüte entstehen",
    text: "**Abweichung**: unter 1 ms 35 Punkte, unter 5 ms 30, unter 20 ms 22, unter 100 ms 12, unter 1 s 5. "
      + "**Stabilität** (Streuung als robuste Standardabweichung, bei frei laufender Uhr um die Gerade): unter "
      + "0,5 ms 25, unter 2 ms 20, unter 10 ms 12, unter 50 ms 6. **Regelmäßigkeit** (Schwankung der Abstände "
      + "ohne Bursts): unter 10 % 20, unter 30 % 15, unter 60 % 8, sonst 3. **Messbarkeit**: 20 × Anteil der "
      + "Anfragen mit echter Uhrzeit. Die Streuung enthält auch die Laufzeit im Netz – im WLAN ist sie größer.",
  },
  client_drift: {
    title: "Gangabweichung (ppm)",
    text: "Wie schnell die Uhr des Geräts wegläuft, in Millionstel (1 ppm ≈ 86 ms pro Tag). Ein Gerät, das bei "
      + "jeder Abfrage nachstellt, läuft bis zur nächsten Abfrage um Gangabweichung × Intervall weg – genau das "
      + "sieht ntp-gui in der Anfrage (**Sägezahn**): 3,2 ms bei 64 s heißen 50 ppm. Wächst die Abweichung "
      + "gleichmäßig, läuft die Uhr **frei** (sie wird nicht gestellt) – dann ist die Steigung die "
      + "Gangabweichung. Schwanken die Abstände der Anfragen genug, trennt ntp-gui dabei einen **festen Versatz** "
      + "(z. B. Laufzeit über WLAN) vom Gang. Bei gleichmäßigen Abständen geht das nicht: Dann zeigt ntp-gui nur "
      + "„**höchstens** … ppm“ – so viel wäre es, wenn die ganze Abweichung Gang wäre; ein fester Versatz von "
      + "5 ms sähe bei 64 s sonst wie 78 ppm aus. Ergäbe sich mehr als 200 ppm (das schafft kaum ein Quarz), "
      + "zeigt ntp-gui „fester Versatz“ statt einer Zahl. "
      + "Positiv: die Uhr läuft zu schnell. Ein Gerät mit gutem Zeitdienst (chrony, ntpd) "
      + "gleicht seine Frequenz selbst aus – dann bleibt nur ein kleiner Rest. Das ± ist die Unsicherheit "
      + "aus der Streuung.",
  },
  client_rules: {
    title: "Regeln für ein Gerät",
    text: "Eigene Meldungen für einzelne Geräte, zusätzlich zur allgemeinen Schwelle in den Einstellungen: "
      + "„fragt seit N Stunden nicht mehr“, eine eigene Alarm-Schwelle mit Mindestdauer, „stumm“ und die "
      + "erwartete Software. Die Meldungen sind Ereignisse der Art **Clients** und laufen über deine "
      + "Benachrichtigungskanäle – entprellt wie alle. Offene Alarme stehen in der Datenbank: Ein Neustart "
      + "meldet nichts doppelt, „wieder da“ kommt trotzdem. Ändern dürfen nur Admins.",
  },
  client_rule_silent: {
    title: "Melden, wenn es nicht mehr fragt",
    text: "Für Geräte, die immer fragen sollten – Kamera, SPS, NAS, Zeiterfassung. Fragt das Gerät länger als "
      + "die eingestellten Stunden nicht, entsteht **einmal** „… fragt seit … nicht mehr nach der Zeit“; "
      + "kommt wieder eine Anfrage, folgt „… fragt wieder nach der Zeit“. Gezählt wird nur die Zeit, in der "
      + "ntp-gui mithört – nach einem Neustart des Containers beginnt die Uhr neu. Wähle die Stunden "
      + "großzügig: Viele IoT-Geräte fragen nur stündlich oder täglich (siehe „Typischer Abstand“).",
  },
  client_rule_offset: {
    title: "Eigene Alarm-Schwelle",
    text: "Ersetzt für dieses Gerät die allgemeine Schwelle (Einstellungen → „Alarm, wenn eine Client-Uhr "
      + "abweicht“). Gemeldet wird, wenn die Abweichung mindestens zweimal hintereinander **und** mindestens "
      + "so viele Minuten über der Schwelle liegt – „|Abweichung| > X für M Minuten“. „Wieder im Rahmen“ erst "
      + "unter der halben Schwelle. Sinnvoll z. B. 50 ms für eine Zeiterfassung, 2000 ms für eine Kamera.",
  },
  client_rule_mute: {
    title: "Stumm",
    text: "Meldungen zu diesem Gerät (auch die der allgemeinen Schwelle) bleiben im Ereignisprotokoll, gehen "
      + "aber nicht als Benachrichtigung hinaus. Gut für Geräte, die bekanntermaßen falsch gehen und die du "
      + "nicht ändern kannst.",
  },
  client_rule_expect: {
    title: "Erwartete Client-Software",
    text: "Wenn du weißt, was auf dem Gerät läuft (Windows, chrony, IoT …), trag es ein. Es gilt dann statt "
      + "der Vermutung in der Ansicht „nach Software“, für NTS-Hinweise und Empfehlungen im Gerätepass. Passt "
      + "das Verhalten deutlich nicht dazu, zeigt die Detailseite einen Hinweis – vielleicht wurde das Gerät "
      + "getauscht oder hat eine andere Adresse bekommen.",
  },
  client_group: {
    title: "Gruppe",
    text: "Die Gruppe, deren Netz diese Adresse enthält. Passen mehrere, gewinnt das **spezifischste** Netz "
      + "(z. B. 10.0.30.0/26 vor 10.0.30.0/24). Gruppen legst du auf der Clients-Seite unter „Gruppen und "
      + "Netze“ an.",
  },
  client_nts: {
    title: "NTS für Clients",
    text: "NTS sichert die Zeit kryptografisch ab. Nutzen können es Geräte nur, wenn der **NTS-Server** dieser "
      + "Instanz an ist (Einstellungen → NTS) und ihre Software NTS spricht: chrony ab 4.0 und NTPsec ja; "
      + "Windows, systemd-timesyncd, Apple, Smartphones und die meisten IoT-Geräte nein. Ob ein Gerät NTS "
      + "**nutzt**, zeigt chrony über die Zahl seiner NTS-KE-Schlüsselaustausche (`chronyc clients -k`, zählt "
      + "seit dem letzten Start von chrony). NTS-Clients schreiben Zufall statt Uhrzeit in die Anfrage – passiv "
      + "„nicht messbar“ ist dort **gutes** Verhalten.",
  },
  client_pass: {
    title: "Gerätepass",
    text: "Alles Wichtige zu einem Gerät auf einer druckbaren Seite: Name, Gruppe, vermutete oder erwartete "
      + "Software, Abfrage-Intervall, Abweichung (Median und 95 %-Wert über 7 Tage, 30-Tage-Median aus den "
      + "Stundenwerten), Gangabweichung, Uhrgüte, NTS, letzte Anfrage und eine **Empfehlung** mit dem passenden "
      + "Befehl. Gedruckt wird mit dem Browser (auch „Als PDF speichern“) – die Seite bleibt lokal. Zum "
      + "Weitergeben (Forum, Ticket) gibt es eine **gefilterte Kopie**.",
  },
  client_pass_share: {
    title: "Gefilterte Kopie des Gerätepasses",
    text: "Der Gerätepass als Text, durch denselben Datenschutzfilter wie das Diagnosepaket: Adressen werden "
      + "zu client-01 usw., eigene Geräte- und Gruppennamen zu `<name>`, eigene Hostnamen zu `<hostname-1>`. "
      + "Die Notiz und die MAC-Adresse stehen nie drin. Findet die Schlussprüfung trotzdem etwas, gibt es keine "
      + "Kopie. Verschickt wird nichts – du kopierst den Text selbst.",
  },
  client_pass_values: {
    title: "Werte im Gerätepass",
    text: "**Median** ist der mittlere Wert aller gespeicherten Messungen (7 Tage, höchstens alle 2 min eine), "
      + "**P95** der Betrag, unter dem 95 % der Messungen liegen – er zeigt die Ausreißer. Der **30-Tage-Median** "
      + "kommt aus den Stundenwerten, die ntp-gui je Gerät 30 Tage aufhebt.",
  },
  clients_groups: {
    title: "Gruppen und Netze",
    text: "Fasse Geräte zu Gruppen zusammen – z. B. „IoT = 10.0.30.0/24“, „Kameras = 10.0.40.0/24“. ntp-gui "
      + "sieht die VLAN-Nummer meist nicht (der Kernel entfernt die Markierung, bevor mitgelesen wird), "
      + "deshalb entstehen Gruppen aus **Netzen**. Je Gruppe siehst du Anzahl (davon in den letzten 24 h "
      + "aktiv), wie viele messbar sind, die **Median-Abweichung** und den **Anteil „gut“** (unter 10 ms). "
      + "Fragt in einer Gruppe seit 24 h kein Gerät, erscheint ein Hinweis: Oft fehlt dort die DHCP-Option 42 "
      + "oder die Umleitung (siehe „Zeitserver erzwingen“). Gruppen bleiben lokal; ihre Namen ersetzt der "
      + "Datenschutzfilter beim Export.",
  },
  clients_group_by: {
    title: "Ansicht: nach Gruppe, VLAN oder Software",
    text: "**Gruppe**: nach deinen Netzen (spezifischstes Netz gewinnt), Rest unter „ohne Gruppe“. **VLAN**: "
      + "nach der VLAN-Kennung im Paket – nur, wo sie sichtbar ist (Trunk-Port am Host); sonst stehen alle "
      + "unter „ohne VLAN-Kennung“. **Software**: nach der erwarteten Software (Regel) bzw. der Vermutung aus "
      + "den Anfragen – immer „vermutlich“.",
  },
  clients_group_stats: {
    title: "Werte je Gruppe",
    text: "**Geräte**: alle bekannten, dahinter die in den letzten 24 h aktiven. **Messbar**: Geräte mit "
      + "echter Uhrzeit in der Anfrage. **Median**: mittlere |Abweichung| der messbaren Geräte. **Anteil gut**: "
      + "messbare Geräte unter 10 ms. **Uhrgüte**: Median der Uhrgüte aller bewerteten Geräte der Gruppe.",
  },
  clients_group_suggest: {
    title: "Vorschläge für Gruppen",
    text: "Netze, aus denen Geräte fragen, die noch zu keiner Gruppe gehören – als /24 (IPv4) bzw. /64 (IPv6), "
      + "die meisten Geräte zuerst. Ein Klick übernimmt das Netz ins Formular; den Namen wählst du selbst.",
  },
  clients_worst_clocks: {
    title: "Schlechteste Uhren im Haus",
    text: "Die Geräte mit der niedrigsten Uhrgüte – dort lohnt sich ein Blick zuerst. Die Zahl dahinter ist die "
      + "Uhrgüte (0–100), dazu die Gangabweichung in ppm. Geräte, die ihre Zeit verschleiern oder noch zu "
      + "wenige Messungen haben, stehen hier nicht.",
  },
  clients_new_device: {
    title: "Neues Gerät fragt nach der Zeit",
    text: "Meldet (Art **Clients**, Stufe Warnung), wenn ein Gerät zum ersten Mal fragt, das ntp-gui noch nie "
      + "gesehen hat – ein einfacher Hinweis auf unbekannte Geräte im Netz. Erkannt wird an der MAC-Adresse "
      + "(wenn das Gerät im selben Netz steht), sonst an der IPv4-Adresse; IPv6-Adressen ohne MAC zählen nicht, "
      + "weil Datenschutz-Adressen täglich wechseln. Die ersten **24 Stunden** lernt ntp-gui nur, danach höchstens "
      + "5 Meldungen pro Stunde (der Rest kommt zusammengefasst). Die Meldung steht für sich – es gibt kein "
      + "„behoben“.",
  },
  notify_lan_addresses: {
    title: "LAN-Adressen in Nachrichten",
    text: "Benachrichtigungen über ein Gerät nennen seinen **eigenen Namen** (Clients → Gerät → Name), ohne "
      + "Namen „Gerät ohne Namen“. Eingeschaltet steht die private LAN-Adresse dabei: „NAS (192.168.1.20)“. "
      + "Standard **aus**: Die Nachricht läuft über fremde Dienste (ntfy, Gotify, Apprise …), und Adressen "
      + "verraten dort den Aufbau deines Netzes. MAC-Adressen und öffentliche Adressen gehen nie hinaus; alles "
      + "andere filtert der Datenschutzfilter wie bisher.",
  },
  client_score: {
    title: "Güte (Spalte)",
    text: "Die Uhrgüte des Geräts von 0 bis 100 (Details auf seiner Seite). „–“: nicht bewertbar, weil das Gerät "
      + "seine Zeit verschleiert, keine sendet oder noch zu wenige Messungen hat.",
  },

  // --- Zeitserver erzwingen ----------------------------------------------------
  enforce: {
    title: "Zeitserver erzwingen",
    text: "Viele Geräte ignorieren den Zeitserver aus DHCP und fragen fest eingebaute Namen wie "
      + "`time.windows.com`, `time.apple.com` oder `pool.ntp.org`. Damit trotzdem alle die gleiche, "
      + "genaue Zeit bekommen, leitest du diese Anfragen auf ntp-gui um – per **DNS-Umschreibung** "
      + "oder per **Firewall-Umleitung**. Das spart außerdem Verkehr ins Internet und funktioniert "
      + "auch, wenn die Internetleitung ausfällt.",
  },
  enforce_dns: {
    title: "DNS-Umschreibung",
    text: "Dein DNS-Server (AdGuard Home, Pi-hole, dnsmasq, Unbound) beantwortet die bekannten "
      + "Zeitserver-Namen mit der Adresse von ntp-gui. Einfach und sauber, erreicht aber nur Geräte, "
      + "die einen **Namen** fragen und **deinen** DNS-Server nutzen. Wichtig: ntp-gui selbst muss "
      + "von der Umschreibung ausgenommen sein, sonst sucht es seine eigenen Quellen bei sich selbst. "
      + "AAAA-Anfragen (IPv6) sollten leer beantwortet werden, sonst weichen Geräte über IPv6 aus.",
  },
  enforce_nat: {
    title: "Firewall-Umleitung (DNAT)",
    text: "Der Router fängt jedes NTP-Paket (UDP-Port 123) ab, das ins Internet will, und schickt es "
      + "an ntp-gui – auch von Geräten mit fest eingetragener IP-Adresse. Pflicht ist eine **Ausnahme "
      + "für ntp-gui selbst**, sonst landen dessen Anfragen an die echten Zeitquellen wieder bei ihm "
      + "(Schleife). Stehen Gerät und ntp-gui im selben Netz, kommt das Hairpin-Problem dazu.",
  },
  enforce_hairpin: {
    title: "Hairpin-Problem",
    text: "Leitet der Router ein Paket an ntp-gui im **selben Netz** um, antwortet ntp-gui direkt dem "
      + "Gerät – am Router vorbei und mit der eigenen Adresse als Absender. Das Gerät hat aber den "
      + "echten Server gefragt und verwirft die Antwort. Abhilfe: Der Router ersetzt bei umgeleiteten "
      + "Paketen den Absender durch seine eigene Adresse (**Masquerade**/SNAT), dann läuft die "
      + "Antwort über ihn zurück. Nachteil: ntp-gui sieht diese Geräte unter der Adresse des Routers. "
      + "Am saubersten ist ein eigenes Netz (VLAN) für ntp-gui.",
  },
  enforce_nts: {
    title: "NTS-Server nie umschreiben",
    text: "Bei NTS prüft das Gerät per TLS-Zertifikat, dass es mit genau dem gewählten Server spricht "
      + "(z. B. `time.cloudflare.com`, `ptbtime1.ptb.de`, `nts.netnod.se`). Eine Umleitung fällt "
      + "dabei auf – das Gerät hätte dann **gar keine** Zeit mehr. Wer NTS nutzt, hat sich bewusst "
      + "für einen Server entschieden. Diese Namen eignen sich dafür gut als Quellen für ntp-gui "
      + "selbst, weil sie nie zu dir zurückgebogen werden.",
  },
  enforce_not_ntp: {
    title: "Geräte ohne NTP",
    text: "Manche Geräte holen die Zeit gar nicht per NTP, sondern per HTTPS vom Hersteller – etwa "
      + "Samsung- und LG-Fernseher. Eine DNS-Umschreibung auf ntp-gui hilft dort nicht, sie würde nur "
      + "die Zeitabfrage scheitern lassen. Diese Namen stehen deshalb absichtlich nicht in der Liste.",
  },
  enforce_hostnames: {
    title: "Umgeleitete Namen",
    text: "Die Liste der Zeitserver-Namen, die die Anleitungen umleiten: geprüfte Standardnamen von "
      + "Windows, Apple, Google/Android, Amazon, Linux-Distributionen, Routern, Sonos und der "
      + "FRITZ!Box, dazu deine eigenen Namen aus den Einstellungen („Weitere Namen für Zeitserver "
      + "erzwingen“). Wo ein System Subdomains mit erfasst, reicht ein Eintrag wie `pool.ntp.org` "
      + "für alle Pool-Namen.",
  },
  enforce_check: {
    title: "Prüfen",
    text: "ntp-gui löst einige bekannte Namen über **seinen** DNS-Server auf und schickt je eine "
      + "NTP-Anfrage an die Antwort sowie an zwei öffentliche Server (Google, Cloudflare). Stimmen "
      + "Stratum, Referenz und Referenzzeit der Antwort mit diesem Server überein, kam sie von "
      + "ntp-gui. Dabei verlassen nur normale NTP-Anfragen die Instanz, keine Daten. Höchstens "
      + "alle 30 Sekunden. Eine Firewall-Umleitung lässt sich von hier aus nur auf die Schleife hin "
      + "prüfen (ntp-gui ist ja ausgenommen) – ob Geräte umgeleitet werden, zeigt der Selbsttest.",
  },
  enforce_verdict: {
    title: "Ergebnis der Prüfung",
    text: "**DNS-Umschreibung wirkt**: Der Name zeigt auf ntp-gui. **Antwortet wie dieser Server**: "
      + "Der Name zeigt auf eine Adresse, hinter der ntp-gui steckt (z. B. die Host-IP im "
      + "Bridge-Netz). **Nicht umgeschrieben**: Der echte Server antwortet. **Keine Antwort**: NTP "
      + "nach außen ist gesperrt. **Schleife**: Anfragen von ntp-gui selbst landen bei ntp-gui – "
      + "dringend die Ausnahme eintragen.",
  },
  enforce_upstream: {
    title: "Eigene Quellen: Name → Resolver → Adresse → Antwort",
    text: "Für jede Quelle aus „Zeitquellen“ zeigt die Prüfung die ganze Kette: welcher **Resolver** den Namen "
      + "aufgelöst hat (System-DNS des Containers oder deine eigenen Server unter „DNS für ntp-gui“), welche "
      + "**Adresse** dabei herauskam und wer dort **antwortet**. Antwortet ein fremder Server, ist alles gut. "
      + "Ist die Adresse eine eigene, schreibt der DNS den Namen auf ntp-gui um (**DNS-Umschreibung ohne "
      + "Ausnahme**). Ist die Adresse richtig, aber die Antwort trägt Stratum, Referenz-ID und Referenzzeit "
      + "dieses Servers, leitet der Router das Paket auf ntp-gui zurück (**NAT-Umleitung ohne Ausnahme**). "
      + "Quellen mit fester IP-Adresse fragen keinen Resolver – bei ihnen kann nur die NAT-Umleitung "
      + "eine Schleife bauen. Unabhängig von dieser Prüfung beobachtet ntp-gui seine Quellen laufend "
      + "und schreibt bei einer Schleife ein Ereignis „Zeitquelle“ (kritisch).",
  },
  enforce_selftest: {
    title: "Selbsttest auf einem Gerät",
    text: "Auf einem Gerät im LAN einen **öffentlichen** Zeitserver abfragen und Stratum und "
      + "Referenz-ID der Antwort mit diesem Server vergleichen. Stimmen beide überein, hat die "
      + "Umleitung gegriffen. Zusätzlich taucht das Gerät dann in der Client-Liste oben auf. "
      + "Hast du DNS-Umschreibung **und** Firewall-Umleitung, teste beide getrennt: per **Name** "
      + "(time.google.com) greift schon der DNS – die Firewall-Regel prüfst du nur **per IP-Adresse** "
      + "(216.239.35.0 gehört zu time.google.com). Antwortet die IP gar nicht, das Gerät steht aber "
      + "in der Client-Liste, ist es das Hairpin-Problem.",
  },
};

export const HELP_GROUP_CLIENTS = {
  title: "Zeitserver erzwingen und Client-Uhren",
  keys: [
    "clientmon", "clientmon_status", "client_offset", "client_measurable",
    "clients_overview", "clients_histogram", "clients_worst", "clients_silent", "clients_chatty", "clients_alarm",
    "client_detail", "client_offset_chart", "client_interval_chart", "client_typical_interval", "client_version",
    "client_seen", "client_rdns", "client_mac", "client_vlan", "client_software", "client_meta", "client_probe",
    "client_quality", "client_quality_parts", "client_drift", "client_score", "clients_worst_clocks",
    "client_rules", "client_rule_silent", "client_rule_offset", "client_rule_mute", "client_rule_expect",
    "client_group", "clients_groups", "clients_group_by", "clients_group_stats", "clients_group_suggest",
    "client_nts", "client_pass", "client_pass_share", "client_pass_values", "clients_new_device", "notify_lan_addresses",
    "enforce", "enforce_dns", "enforce_nat", "enforce_hairpin", "enforce_nts", "enforce_not_ntp",
    "enforce_hostnames", "enforce_check", "enforce_verdict", "enforce_upstream", "enforce_selftest",
  ],
};
