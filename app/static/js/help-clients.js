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
    "enforce", "enforce_dns", "enforce_nat", "enforce_hairpin", "enforce_nts", "enforce_not_ntp",
    "enforce_hostnames", "enforce_check", "enforce_verdict", "enforce_selftest",
  ],
};
