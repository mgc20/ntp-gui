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
    text: "Der Median der letzten acht Abstände zwischen zwei Anfragen. Der Median übergeht den kurzen "
      + "Schwall beim Start (iburst: vier Anfragen im Abstand von 2 s) und einzelne verlorene Pakete. "
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
    text: "ntp-gui fragt den DNS nach dem Namen zur Adresse (Reverse-DNS, z. B. „nas.fritz.box“) – "
      + "höchstens 1 s lang, das Ergebnis wird eine Stunde gemerkt. Gefragt wird nur bei privaten "
      + "Adressen und nie über DoT/DoH oder öffentliche DNS-Server: Die Frage verrät die Adresse deines "
      + "Geräts, und die geht niemanden außerhalb deines Netzes etwas an. Abschalten: Einstellungen → "
      + "„Namen der Clients per DNS nachschlagen“.",
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
      + "Im **Diagnosepaket** und in **Benachrichtigungen** ersetzt der Datenschutzfilter den Namen durch "
      + "`<name>` – Namen ab 4 Zeichen; kürzere stehen in Ereignissen deshalb gar nicht, dort steht die "
      + "Adresse (die beim Export zu client-01 usw. wird). Notizen werden nie exportiert. Ändern dürfen "
      + "nur Admins.",
  },
  client_probe: {
    title: "Aktiv nachmessen",
    text: "Schickt **eine** NTP-Anfrage an das Gerät (Port 123, Zeitlimit 2 s, zufälliger Sendezeitstempel – "
      + "sie verrät nichts über diesen Server). Viele Router, NAS und manche Kameras sind selbst "
      + "Zeitserver und antworten; dann siehst du ihre Uhr samt Laufzeit, auch wenn sie ihre Sendezeit "
      + "verschleiern. Die meisten Geräte antworten **nicht** – das ist normal und kein Fehler. Nur für "
      + "Geräte mit privater Adresse, die diesen Server schon gefragt haben; je Gerät höchstens alle "
      + "30 s, insgesamt 10 Messungen pro Minute.",
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
    "enforce", "enforce_dns", "enforce_nat", "enforce_hairpin", "enforce_nts", "enforce_not_ntp",
    "enforce_hostnames", "enforce_check", "enforce_verdict", "enforce_selftest",
  ],
};
