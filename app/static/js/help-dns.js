// Erklärungen zu „DNS für ntp-gui“ (1.4). Wird in help.js in HELP übernommen; die Schlüssel stehen
// gesammelt in HELP_GROUP_DNS, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_DNS = {
  dns: {
    title: "DNS für ntp-gui",
    text: "Legt fest, über welche DNS-Server ntp-gui **selbst** Namen auflöst – die Namen seiner Zeitquellen "
      + "(pool.ntp.org, ptbtime1.ptb.de …), den NTS-Schlüsselaustausch und die Prüfung „Zeitserver erzwingen“. "
      + "Warum das wichtig ist: Schreibt AdGuard Home oder Pi-hole Zeitserver-Namen auf ntp-gui um, damit Geräte "
      + "im LAN deinen Server nutzen, und fragt ntp-gui denselben DNS-Server, bekommt chronyd für pool.ntp.org die "
      + "eigene Adresse – und fragt sich selbst. Mit eigenen Servern sieht ntp-gui die Umschreibung nicht. "
      + "Technisch startet ntp-gui dafür einen kleinen Weiterleiter **nur auf 127.0.0.1** im Container und stellt "
      + "/etc/resolv.conf darauf um; im Modus „System-DNS“ bleibt alles wie bisher.",
  },
  dns_modes: {
    title: "Welcher Modus?",
    text: "**System-DNS**: wie bisher, der DNS aus Docker bzw. vom Router. **Eigene DNS-Server**: klassisches DNS "
      + "(Port 53) an feste Adressen wie 9.9.9.9 – einfach, aber unverschlüsselt und von einer DNS-Umleitung per "
      + "Firewall betroffen. **DNS-over-TLS** (Port 853) und **DNS-over-HTTPS** (Port 443): verschlüsselt, das "
      + "Zertifikat des Servers wird geprüft – eine Umschreibung oder Umleitung im LAN kann sie nicht verbiegen. "
      + "Für die meisten Heimnetze mit AdGuard/Pi-hole ist DoT mit zwei Servern (z. B. dns.quad9.net und "
      + "one.one.one.one) die robusteste Wahl.",
  },
  dns_state: {
    title: "Zustand",
    text: "**läuft** – die eigenen Server antworten. **wartet auf erste Anfrage** – der Weiterleiter läuft, hat aber "
      + "noch nichts aufgelöst. **Rückfall auf System-DNS** – keiner der eigenen Server hat zuletzt geantwortet, "
      + "ntp-gui fragt den ursprünglichen DNS (Ereignis „DNS“). **keine Auflösung** – auch der System-DNS antwortet "
      + "nicht. **nicht gestartet** – der Weiterleiter läuft nicht; dann zeigt resolv.conf wieder auf den System-DNS. "
      + "Der Stand stammt vom Laden der Seite.",
  },
  dns_resolv: {
    title: "resolv.conf",
    text: "Die Datei, in der Linux nachschaut, welchen DNS-Server es fragen soll. Im Modus „System-DNS“ schreibt sie "
      + "Docker. In den anderen Modi trägt ntp-gui dort 127.0.0.1 ein (das Original wird gesichert und beim "
      + "Zurückschalten, beim Beenden und nach einem Absturz des Weiterleiters zurückgeschrieben). Ist die Datei "
      + "schreibgeschützt (z. B. `read_only: true`), trag in der Compose-Datei beim Dienst `dns: 127.0.0.1` ein – "
      + "dann zeigt Docker selbst auf den Weiterleiter. Dann gibt es aber keinen System-DNS mehr, der die Namen "
      + "von DoT/DoH-Servern auflösen könnte: Trag sie unter „Feste Adressen“ ein (z. B. dns.quad9.net=9.9.9.9) "
      + "oder nimm „Eigene DNS-Server“ mit IP-Adressen.",
  },
  dns_upstreams: {
    title: "Eigene Server",
    text: "Die eingetragenen Server in ihrer Reihenfolge: wie oft sie geantwortet haben, wann zuletzt, die letzte "
      + "Antwortzeit und – falls es einen gab – der letzte Fehler. Ist ein Server nicht erreichbar (abgelehnt, "
      + "TLS-Fehler, Adresse unbekannt) oder läuft er dreimal in Folge in eine Zeitüberschreitung, überspringt "
      + "ntp-gui ihn 30 Sekunden lang und fragt den nächsten. Eine einzelne langsame Antwort zählt nicht als "
      + "Ausfall – dafür gibt es Namen mit trägen Nameservern zu oft. Bei DNS-over-HTTPS steht nur der Servername da, weil der Pfad "
      + "eine Konto-Kennung enthalten kann (z. B. bei NextDNS).",
  },
  dns_fallback: {
    title: "Rückfall auf den System-DNS",
    text: "Antwortet keiner der eigenen Server, fragt ntp-gui den DNS, den der Container ursprünglich hatte, und "
      + "schreibt ein Ereignis. Das hält die Zeitquellen auflösbar, bringt aber das Schleifenrisiko zurück, falls "
      + "dieser DNS Zeitserver-Namen umschreibt – und die Frage geht unverschlüsselt hinaus. Deshalb bleiben solche "
      + "Antworten nur 5 Sekunden im Cache: Sind die eigenen Server zurück, werden sofort wieder sie gefragt. "
      + "Antwortet der System-DNS mit einem Fehler (SERVFAIL, REFUSED), gilt das nicht als Antwort. Kommt eine "
      + "weitergegebene Anfrage bei ntp-gui selbst wieder an (etwa Docker-DNS mit `dns: 127.0.0.1`), bricht "
      + "ntp-gui sie sofort ab, statt sie kreisen zu lassen. Wer DoT/DoH aus Datenschutzgründen nutzt, kann den "
      + "Rückfall abschalten.",
  },
  dns_pin: {
    title: "Feste Adressen",
    text: "DoT- und DoH-Server haben Namen. Deren Adresse muss ntp-gui zuerst erfahren – über den System-DNS. Mit "
      + "einem festen Eintrag (dns.quad9.net=9.9.9.9) entfällt diese Abfrage. Das Zertifikat wird trotzdem gegen "
      + "den Namen geprüft, ein falscher Eintrag führt also zu einem Fehler, nicht zu einem fremden Server. "
      + "Pflicht, wenn in der Compose-Datei `dns: 127.0.0.1` steht: Dann wäre der System-DNS wieder ntp-gui selbst, "
      + "und der Name bliebe unauflösbar.",
  },
  dns_counts: {
    title: "Anfragen",
    text: "Seit dem Start des Weiterleiters: Anfragen insgesamt, davon aus dem Cache beantwortet (der Cache hält "
      + "Antworten höchstens so lange wie ihre TTL, maximal 5 Minuten), über den System-DNS beantwortet "
      + "(Rückfall) und ohne Antwort (SERVFAIL). Die Zahlen beginnen nach jedem Speichern der Einstellungen neu.",
  },
};

export const HELP_GROUP_DNS = {
  title: "DNS für ntp-gui",
  keys: ["dns", "dns_modes", "dns_state", "dns_resolv", "dns_upstreams", "dns_fallback", "dns_pin", "dns_counts"],
};
