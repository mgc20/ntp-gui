// Erklärungen zum Hardware-Check, zu den GPS-Fakten und zu den PTP-Details.
// Wird in help.js in HELP übernommen; die Schlüssel stehen gesammelt in
// HELP_GROUP_HARDWARE, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_HARDWARE = {
  // --- Hardware-Check allgemein ---------------------------------------------
  hw_check: {
    title: "Hardware-Check",
    text: "Liest nur aus, was Kernel und Container über die Hardware verraten (`/sys`, `/proc`, `/dev`, "
      + "`ethtool`, gpsd) – es wird nichts umgestellt und keine serielle Schnittstelle geöffnet. Ergebnis: "
      + "Was von dem, was ntp-gui kann, auf **genau diesem Gerät** geht, was eine Änderung braucht und was "
      + "gar nicht geht. Die Prüfung läuft auch, wenn GPS oder PTP ausgeschaltet sind – ideal vor dem Kauf "
      + "oder Einrichten.",
  },
  hw_platform: {
    title: "Plattform",
    text: "Worauf ntp-gui läuft: Board oder PC, Container-Laufzeit und Netzwerkmodus. Das entscheidet, "
      + "welche Hardware überhaupt erreichbar ist. In **Docker Desktop** (macOS/Windows) und **WSL2** "
      + "läuft der Container in einer kleinen VM: USB, PPS und PTP sind dort praktisch nicht nutzbar, und "
      + "„Uhr stellen“ betrifft nur diese VM.",
  },
  hw_board: {
    title: "Board / Modell",
    text: "Das Modell aus dem Device-Tree (Raspberry Pi) oder aus den DMI-Daten (PC, VM). Beim Pi lässt "
      + "sich daraus ableiten, was zu erwarten ist: **Pi 5, CM4, CM5** haben Hardware-PTP an der "
      + "eingebauten Netzwerkbuchse, der **Pi 4** nicht. Maßgeblich bleibt das Live-Ergebnis von `ethtool -T`.",
  },
  hw_arch: {
    title: "Architektur",
    text: "Prozessorarchitektur, z. B. `x86_64` (PC, Server) oder `aarch64` (Raspberry Pi mit 64-Bit-System). "
      + "Das Image gibt es für beide.",
  },
  hw_hypervisor: {
    title: "Virtualisierung",
    text: "Läuft das System in einer VM (KVM/Proxmox, VMware, Hyper-V, VirtualBox), sind Netzwerkkarten meist "
      + "**emuliert** – ohne Hardware-Zeitstempel, also ohne echtes PTP. USB-Geräte wie ein GPS-Stick "
      + "müssen per USB-Durchreichung an die VM gegeben werden. Netzwerkkarten gehen nur per "
      + "**PCI-Passthrough** mit voller Leistung durch.",
  },
  hw_container: {
    title: "Container",
    text: "Ob ntp-gui in Docker oder Podman läuft. Wichtig: `/sys` zeigt im Container auch Hardware des "
      + "**Hosts**, die gar nicht in den Container gereicht wurde. Deshalb unterscheidet der Check "
      + "„am Host vorhanden“ und „im Container nutzbar“ – genau dort liegt der häufigste Fehler.",
  },
  hw_matrix: {
    title: "Was diese Hardware kann",
    text: "Für jede Funktion von ntp-gui eine Zeile: **geht**, **geht mit Änderung** (dann steht die genaue "
      + "Änderung zum Kopieren darunter), **eingeschränkt** (geht, aber mit Abstrichen) oder **geht nicht** "
      + "(mit Begründung). „aktiv“ heißt: die Funktion ist in den Einstellungen gerade eingeschaltet – "
      + "Probleme dort betreffen den laufenden Betrieb.",
  },
  hw_fix: {
    title: "Nötige Änderung",
    text: "Ein fertiger Ausschnitt für `docker-compose.yml`, die `.env`-Datei oder die Boot-Konfiguration "
      + "des Hosts. Nach einer Änderung an der Compose-Datei den Container mit `docker compose up -d` neu "
      + "erzeugen – ein einfacher Neustart übernimmt neue Geräte und Rechte nicht.",
  },
  hw_accuracy: {
    title: "Erreichbare Genauigkeit",
    text: "Grobe Richtwerte, wie genau die Zeit mit dieser Hardware werden kann. Sie hängen vom Weg ab, "
      + "auf dem der Sekundentakt in den Rechner kommt: nur NMEA-Text (Millisekunden), Impuls über USB "
      + "(~1 ms), über eine echte serielle Schnittstelle (wenige µs) oder über GPIO (~1 µs).",
  },
  hw_ntp_server: {
    title: "NTP-Server",
    text: "chronyd beantwortet Zeitanfragen auf Port 123/udp. Das geht praktisch immer. Im Docker-"
      + "**Bridge-Netz** sehen Clients wegen NAT nur die Docker-Adresse; für echte Client-Adressen in der "
      + "Client-Liste `network_mode: host` verwenden.",
  },
  hw_clock_control: {
    title: "Uhr stellen",
    text: "Damit chrony die Systemuhr stellen darf, braucht der Container `cap_add: [SYS_TIME]`. Ohne das "
      + "Recht misst und verteilt chrony nur. Die Systemuhr gehört dem **Host**: Es sollte dort kein "
      + "zweiter Zeitdienst (systemd-timesyncd, chrony, ntpd) laufen, sonst stellen zwei Regler dieselbe Uhr.",
  },
  hw_nts: {
    title: "NTS auf dieser Hardware",
    text: "NTS prüft TLS-Zertifikate – dafür muss die Uhr beim Start schon ungefähr stimmen. Geräte **ohne "
      + "Echtzeituhr** (Pi 4, Pi 5 ohne Akku) starten nach einem Stromausfall mit einer Zeit in der "
      + "Vergangenheit. Dann muss „Zertifikatszeit beim Start nicht prüfen“ (`NTS_NOCERTTIMECHECK`) "
      + "eingeschaltet bleiben, sonst kommt NTS nie in Gang.",
  },
  hw_gps_usb: {
    title: "USB-GPS (Millisekunden)",
    text: "Ein Empfänger, der nur Text (NMEA) liefert. Genau auf **1–10 ms** nach der Kalibrierung – "
      + "unabhängig vom Internet. Voraussetzung: das Gerät (`/dev/ttyACM0` o. ä.) ist im Container, und "
      + "am Host belegt kein anderer gpsd oder ModemManager den Port.",
  },
  hw_gps_pps: {
    title: "GPS + PPS (Mikrosekunden)",
    text: "Der Sekundenimpuls (PPS) markiert den Sekundenbeginn auf Mikrosekunden genau. Er braucht einen "
      + "eigenen elektrischen Weg in den Rechner – GPIO-Pin (Raspberry Pi), DCD-Leitung einer seriellen "
      + "Schnittstelle oder eine Timecard. Ein gewöhnlicher USB-Stick hat diesen Weg nicht.",
  },
  hw_ptp_hw: {
    title: "PTP mit Hardware-Zeitstempeln",
    text: "Die Netzwerkkarte stempelt PTP-Pakete selbst und hat eine eigene Uhr (`/dev/ptpN`). Erst dann "
      + "erreicht PTP Nanosekunden bis wenige Mikrosekunden. Dazu braucht der Container `network_mode: "
      + "host`, `NET_ADMIN` und die PTP-Uhr als Gerät.",
  },
  hw_ptp_sw: {
    title: "PTP mit Software-Zeitstempeln",
    text: "Geht mit fast jeder Karte, solange der Container im Host-Netz läuft. Der Kernel stempelt die "
      + "Pakete – damit ist PTP **nicht genauer als gutes NTP** (Mikrosekunden bis Millisekunden). Sinnvoll "
      + "nur, wenn Geräte ausschließlich PTP verstehen.",
  },
  hw_ptp_to_ntp: {
    title: "PTP → NTP (Brücke)",
    text: "Im Slave-Modus übernimmt ptp4l die Zeit eines vorhandenen PTP-Grandmasters in die Uhr der "
      + "Netzwerkkarte, chrony liest diese Uhr als Quelle (`PHC_REFCLOCK=/dev/ptp0`) und verteilt die "
      + "Zeit per NTP an alle Geräte, die kein PTP können. Braucht Hardware-PTP.",
  },
  hw_gps_to_ptp: {
    title: "GPS → PTP (Grandmaster)",
    text: "chrony stellt die Systemuhr nach GPS, **phc2sys kopiert die Systemuhr in die Uhr der "
      + "Netzwerkkarte** (dafür `PHC2SYS_ENABLE=true` setzen), ptp4l verteilt diese Uhr als Grandmaster. Sinnvoll nur mit **PPS**: Mit einem "
      + "USB-GPS würde PTP eine auf Millisekunden ungenaue Zeit nanosekundengenau verteilen. Profi-Variante "
      + "(PPS direkt an einen Pin der Karte, ts2phc) unterstützt ntp-gui nicht.",
  },
  hw_warnings: {
    title: "Auffälligkeiten",
    text: "Dinge, die beim Auslesen aufgefallen sind und nicht zu einer einzelnen Funktion gehören, z. B. "
      + "widersprüchliche Einstellungen. Sie verhindern den Betrieb meist nicht, sollten aber geprüft werden.",
  },
  hw_refresh: {
    title: "Neu prüfen",
    text: "Das Ergebnis wird etwa 30 Sekunden zwischengespeichert. „Neu prüfen“ liest alles sofort neu – "
      + "z. B. nach dem Einstecken eines Empfängers. Beim ersten Lesen wartet die Prüfung gut eine Sekunde, "
      + "um zu zählen, ob PPS-Impulse ankommen.",
  },

  // --- GPS-Empfänger ----------------------------------------------------------
  hw_receiver: {
    title: "GPS-Empfänger",
    text: "Alle seriellen Geräte, die ein GPS sein können (`ttyACM`, `ttyUSB`, `ttyAMA`, `ttyS`), mit dem, "
      + "was sich über sie herausfinden lässt. Entscheidend für die Genauigkeit ist nicht der Chip, sondern "
      + "**wie** der Empfänger angeschlossen ist: Nur mit einem eigenen PPS-Weg geht es unter eine Millisekunde.",
  },
  hw_verdict: {
    title: "Urteil",
    text: "Die Zusammenfassung für deinen Empfänger: was er kann, wie genau er wird und was du für mehr "
      + "Genauigkeit bräuchtest.",
  },
  hw_interface: {
    title: "Schnittstelle",
    text: "Wie der Empfänger angebunden ist. **USB (CDC-ACM)**: der Empfänger meldet sich als USB-Modem "
      + "(u-blox-Sticks wie VK-162) – kein PPS möglich. **USB-Seriell** (FTDI, CP210x, PL2303): PPS nur, wenn "
      + "das Board ihn auf DCD legt. **UART**: echte serielle Schnittstelle, z. B. GPS-HAT am Pi.",
  },
  hw_tty_driver: {
    title: "Kernel-Treiber",
    text: "Der Treiber, der die serielle Schnittstelle bereitstellt, z. B. `cdc_acm`, `ftdi_sio`, `cp210x`, "
      + "`pl2303`, `uart-pl011` (Pi). Daran erkennt der Check, ob ein PPS-Weg überhaupt möglich ist.",
  },
  hw_device_path: {
    title: "Gerät",
    text: "Der Gerätename, unter dem der Empfänger erscheint. Namen wie `/dev/ttyACM0` können sich beim "
      + "Umstecken ändern – deshalb besser den stabilen Pfad verwenden.",
  },
  hw_stable_path: {
    title: "Stabiler Pfad",
    text: "`/dev/serial/by-id/…` heißt immer gleich, egal an welchem USB-Port der Empfänger steckt oder in "
      + "welcher Reihenfolge Geräte erkannt werden. Für `GPS_DEVICE` die beste Wahl. Sichtbar ist er nur, "
      + "wenn `/dev` des Hosts im Container eingehängt ist.",
  },
  hw_usb_id: {
    title: "USB-Kennung",
    text: "Hersteller- und Produktnummer (VID:PID), z. B. `1546:01a7` für einen u-blox-7-Stick (VK-162). "
      + "Damit lässt sich ein Gerät eindeutig zuordnen. Die Geschwindigkeit zeigt, ob der Empfänger mit "
      + "Full-Speed (12 Mbit/s) oder High-Speed (480 Mbit/s) angebunden ist – das begrenzt PPS über USB.",
  },
  hw_gpsd_driver: {
    title: "gpsd-Erkennung",
    text: "Was gpsd über den Empfänger meldet: Treiber (`u-blox`, `SiRF`, `NMEA0183` …), Chip-Generation und "
      + "– bei u-blox 8 und neuer – das genaue Modul. Ein Modul mit **T** am Ende (LEA-M8T, ZED-F9T) ist ein "
      + "**Timing-Modul**: ideal für PPS und im Stand genauer.",
  },
  hw_gpsd_activated: {
    title: "Von gpsd geöffnet",
    text: "„ja“ heißt: gpsd konnte den Port öffnen und liest Daten. „nein“ heißt meist: Der Port ist am "
      + "Host belegt (eigener gpsd, ModemManager) oder dem Container fehlt die Freigabe für das Gerät.",
  },
  hw_presence: {
    title: "Am Host / im Container",
    text: "**Am Host**: der Kernel kennt das Gerät. **Im Container**: `/dev/…` ist im Container sichtbar. "
      + "**Nutzbar**: es lässt sich auch öffnen. Am Host vorhanden, im Container nicht → in der Compose-Datei "
      + "`devices: - /dev/X:/dev/X` ergänzen. Sichtbar, aber nicht nutzbar → bei eingehängtem `/dev` fehlt die "
      + "passende `device_cgroup_rules`-Zeile.",
  },
  hw_pps_path: {
    title: "PPS-Weg",
    text: "Auf welchem Weg der Sekundenimpuls in den Rechner kommen kann. **Kein PPS**: USB-Modem-Gerät, "
      + "nur NMEA-Text. **DCD über USB**: ~1 ms, begrenzt durch den USB-Takt. **DCD am UART**: wenige µs. "
      + "**GPIO**: ~1 µs. **GPIO möglich**: Empfänger am Pi-UART, es fehlt nur das Overlay "
      + "`dtoverlay=pps-gpio,gpiopin=18` in `/boot/firmware/config.txt`.",
  },
  hw_ladder: {
    title: "Genauigkeitsstufen",
    text: "Von links nach rechts genauer: **NMEA** (nur Text, ~10 ms), **USB-DCD** (Impuls über USB-Seriell, "
      + "~1 ms), **UART-DCD** (Impuls an echter serieller Schnittstelle, ~5 µs), **GPIO** (Impuls an einem Pin "
      + "des Pi, ~1 µs) und **PTP-Hardware** (Netzwerkkarte stempelt selbst, unter 1 µs). ▲ zeigt, wo dein "
      + "Empfänger jetzt steht, ◇ was mit dieser Hardware erreichbar wäre.",
  },
  hw_gpsd_pps: {
    title: "PPS über gpsd",
    text: "Ob gpsd selbst Sekundenimpulse sieht (DCD-Leitung). Das betrifft nur Empfänger an einer seriellen "
      + "Schnittstelle ohne eigene `/dev/pps`-Quelle. Bei PPS über GPIO liest chrony `/dev/pps0` direkt – "
      + "dann meldet gpsd keine Impulse, und das ist richtig so.",
  },
  hw_toff: {
    title: "NMEA-Verspätung",
    text: "Um wie viel die NMEA-Zeitangabe nach dem tatsächlichen Sekundenbeginn eintrifft – gemessen von "
      + "gpsd. Typisch 20–150 ms bei USB-Empfängern. Genau diese Verspätung gleicht die GPS-Kalibrierung als "
      + "Offset aus.",
  },

  // --- PPS --------------------------------------------------------------------
  hw_pps_sources: {
    title: "PPS-Quellen",
    text: "Alle Sekundenimpuls-Geräte, die der Kernel kennt (`/sys/class/pps`). Die Prüfung liest den "
      + "Impulszähler zweimal im Abstand von gut einer Sekunde und erkennt so, ob wirklich Impulse ankommen.",
  },
  hw_pps_kind: {
    title: "Art der PPS-Quelle",
    text: "**GPIO** (pps-gpio, Impuls an einem Pin des Pi), **seriell** (pps-ldisc, Impuls auf der DCD-Leitung "
      + "einer seriellen Schnittstelle) oder **Netzwerkkarte** (PTP-Uhr, die einen Sekundentakt an den Kernel "
      + "gibt).",
  },
  hw_pps_state: {
    title: "Impulse",
    text: "**live**: der Zähler läuft mit ~1 Impuls pro Sekunde – alles gut. **keine Impulse**: das Gerät ist "
      + "da, aber seit der letzten Messung kam nichts – meist noch kein GPS-Fix (Antenne, freie Sicht) oder "
      + "falscher Pin/Kabel. **noch nie**: seit dem Systemstart kam kein einziger Impuls – Overlay-Pin "
      + "(`gpiopin=`) und Verkabelung prüfen.",
  },
  hw_pps_rate: {
    title: "Impulsrate",
    text: "Gemessene Impulse pro Sekunde. Richtig ist **1 Hz**. Deutlich mehr deutet auf Störungen auf der "
      + "Leitung hin, weniger auf Aussetzer.",
  },
  hw_pps_phase: {
    title: "Lage zur Sekundengrenze",
    text: "Wie weit der letzte Impuls von der vollen Sekunde der Systemuhr entfernt lag. Bei synchroner Uhr "
      + "sind wenige Mikrosekunden normal. Ein großer, gleichbleibender Wert ist kein Fehler, sondern ein "
      + "fester Versatz (Kabellänge, Empfänger-Einstellung).",
  },
  hw_pps_configured: {
    title: "Eingetragen",
    text: "Diese Quelle steht in den Einstellungen als PPS-Gerät (`GPS_PPS_DEVICE`) und wird von chrony "
      + "genutzt. Eine Quelle, die live ist, aber nicht eingetragen, verschenkt Genauigkeit.",
  },

  // --- PTP-Uhren und Netzwerkkarten ---------------------------------------------
  hw_ptp_clocks: {
    title: "PTP-Uhren",
    text: "Alle PTP-Hardwareuhren (`/dev/ptpN`), die der Kernel kennt. Eine Uhr gehört normalerweise zu einer "
      + "Netzwerkkarte. Eine Uhr **ohne** Karte ist oft die virtuelle Uhr einer VM (`KVM virtual PTP`, "
      + "`hyperv`): Für chrony im Gast sehr gut, für PTP im Netz unbrauchbar.",
  },
  hw_clock_name: {
    title: "Name der Uhr",
    text: "So nennt der Treiber die Uhr, z. B. `gem-ptp-timer` (Raspberry Pi 5), `bcm_phy_ptp` (CM4) oder "
      + "die MAC-Adresse bei Intel-Karten.",
  },
  hw_ptp_kind: {
    title: "Art der Uhr",
    text: "**Netzwerkkarte**: echte Hardwareuhr für PTP. **VM-Uhr**: vom Hypervisor bereitgestellt, nur "
      + "innerhalb der VM sinnvoll. **unbekannt**: die Zuordnung zur Karte gelang nicht (z. B. weil der "
      + "Container nicht im Host-Netz läuft).",
  },
  hw_ptp_pins: {
    title: "Pins und externe Zeitstempel",
    text: "Hat die Karte Pins für externe Zeitstempel, kann ein GPS-PPS direkt in die Karte (ts2phc) – die "
      + "beste Grandmaster-Variante mit Nanosekunden. ntp-gui unterstützt das (noch) nicht; es ist ein "
      + "Hinweis für Profis.",
  },
  hw_pps_available: {
    title: "PPS an den Kernel",
    text: "Ob die Uhr der Karte einen Sekundentakt an den Kernel liefern kann. Nur informativ.",
  },
  hw_max_adj: {
    title: "Max. Korrektur",
    text: "Wie stark (in ppb) sich die Uhr der Karte maximal beschleunigen oder bremsen lässt. Übliche Werte "
      + "liegen zwischen 62 500 000 und 1 000 000 000 – für PTP reicht jeder davon.",
  },
  hw_nic_class: {
    title: "Eignung für PTP",
    text: "Bewertung nach Treiber und `ethtool -T`. **gut**: Hardware-Zeitstempel und PTP-Uhr (Intel "
      + "i210/i225/i226, Pi 5, CM4). **eingeschränkt**: geht, aber mit bekannten Schwächen (z. B. Intel I219, "
      + "`e1000e`). **keine**: nur Software-Zeitstempel (Realtek, USB-Adapter, WLAN, Pi 4). **virtuell**: "
      + "Karte einer VM oder von Docker.",
  },
  hw_passthrough: {
    title: "PCI-Passthrough",
    text: "Eine echte Netzwerkkarte, die direkt an die VM gegeben wurde. Dann geht Hardware-PTP auch in "
      + "der VM.",
  },

  // --- Rechte und Geräte ---------------------------------------------------------
  hw_caps: {
    title: "Rechte (Capabilities)",
    text: "Linux teilt root-Rechte in einzelne Fähigkeiten auf. Docker gibt Containern nur einen Teil davon. "
      + "`CapEff` ist die Bitmaske der tatsächlich wirksamen Rechte; die wichtigen sind einzeln aufgeführt.",
  },
  hw_privileged: {
    title: "Privilegiert",
    text: "Mit `privileged: true` hat der Container alle Rechte und sieht alle Geräte des Hosts. Praktisch "
      + "für einen ersten Hardware-Check, im Dauerbetrieb aber nicht empfohlen – besser gezielt "
      + "`cap_add` und `devices` eintragen.",
  },
  hw_sys_time: {
    title: "SYS_TIME",
    text: "Erlaubt das Stellen der Systemuhr. Ohne läuft chrony mit `-x`: Es misst und verteilt, korrigiert "
      + "aber nichts. Eintragen mit `cap_add: [SYS_TIME]`.",
  },
  hw_net_admin: {
    title: "NET_ADMIN",
    text: "Erlaubt ptp4l (und chrony), Hardware-Zeitstempel an der Netzwerkkarte einzuschalten. Ohne meldet "
      + "das PTP-Log „ioctl SIOCSHWTSTAMP failed“. Eintragen mit `cap_add: [NET_ADMIN]`.",
  },
  hw_net_raw: {
    title: "NET_RAW",
    text: "Erlaubt Pakete direkt auf Ebene 2 – nötig für PTP mit `PTP_TRANSPORT=L2`. In Docker meist schon "
      + "vorhanden, in Podman oft nicht.",
  },
  hw_sys_nice: {
    title: "SYS_NICE",
    text: "Würde ptp4l/phc2sys Echtzeit-Priorität erlauben. ntp-gui nutzt das derzeit nicht – nur zur Info.",
  },
  hw_network: {
    title: "Netzwerkmodus",
    text: "**Host-Netz** (`network_mode: host`): der Container nutzt die echten Netzwerkkarten – nötig für PTP "
      + "und echte Client-Adressen. **Bridge**: Docker-eigenes Netz mit NAT; NTP geht, PTP nicht.",
  },
  hw_dev_mounted: {
    title: "/dev vom Host eingehängt",
    text: "Mit `volumes: - /dev:/dev` sieht der Container alle Geräte des Hosts, auch später eingesteckte. "
      + "Öffnen darf er sie aber nur mit passender Regel unter `device_cgroup_rules` (Major-Nummer des "
      + "Gerätetyps). Ohne eingehängtes `/dev` braucht jedes Gerät eine `devices:`-Zeile.",
  },
  hw_modules: {
    title: "Kernel-Module",
    text: "Treiber, die der Host-Kernel geladen hat, z. B. `pps_gpio` (PPS am GPIO-Pin) oder `cdc_acm` "
      + "(USB-GPS). Fehlt eines, heißt das nur „nicht nachweisbar“ – eingebaute Treiber tauchen nicht "
      + "immer in der Liste auf.",
  },
  hw_majors: {
    title: "Major-Nummern",
    text: "Jeder Gerätetyp hat eine Nummer. PPS und PTP bekommen sie vom Kernel **dynamisch** – sie "
      + "unterscheiden sich je System. Für die All-in-one-Compose gehören sie als `PPS_MAJOR=` und "
      + "`PTP_MAJOR=` in die `.env`; daraus entstehen die `device_cgroup_rules`.",
  },

  // --- Pi-Zustand (1.6) ----------------------------------------------------------
  pi_state: {
    title: "Pi-Zustand",
    text: "Was die Firmware des Raspberry Pi über Stromversorgung und Takt meldet – nur gelesen aus `/sys` "
      + "(Firmware-Bitfeld `get_throttled`, Sensor `rpi_volt`, Lüfter, `cpufreq`), ohne `vcgencmd` und ohne "
      + "zusätzliche Rechte. Unterspannung und Drosselung ändern Last und Temperatur am Quarz und erklären "
      + "Sprünge in Frequenz und Offset. Die Karte erscheint nur auf einem Pi; Wechsel landen als Ereignis "
      + "„Unterspannung erkannt“ bzw. „Takt gedrosselt“ im Protokoll.",
  },
  pi_undervoltage: {
    title: "Unterspannung",
    text: "„jetzt“: Die Spannung liegt gerade unter etwa 4,63 V. „seit Start“: Das ist seit dem Einschalten "
      + "des Pi mindestens einmal passiert – auch kurz, zwischen zwei Messungen. Fast immer liegt es am "
      + "Netzteil oder am Kabel: Am zuverlässigsten ist das **offizielle Netzteil** (Pi 5: 27 W, Pi 4: 15 W) "
      + "mit kurzem Kabel; USB-Festplatten und GPS-Sticks ziehen zusätzlich Strom.",
  },
  pi_throttled: {
    title: "Gedrosselt",
    text: "Die Firmware senkt den Takt der CPU – wegen Unterspannung oder weil der Chip zu heiß wird "
      + "(ab etwa 80 °C). „jetzt“ heißt gerade, „seit Start“ heißt mindestens einmal seit dem Einschalten. "
      + "Für die Uhr bedeutet das wechselnde Last und Temperatur, also eine unruhigere Frequenz.",
  },
  pi_capped: {
    title: "Takt gedeckelt",
    text: "Die Firmware lässt den Takt nicht bis zum Höchstwert steigen (meist wegen Unterspannung). Die Zeile "
      + "erscheint nur, wenn das jetzt oder seit dem Start des Pi der Fall war.",
  },
  pi_soft_temp: {
    title: "Temperaturgrenze",
    text: "Die weiche Temperaturgrenze (Pi 3B+ und neuer, um 60 °C) war aktiv: Der Takt wird schon vor der "
      + "eigentlichen Drosselung gesenkt. Kühlkörper oder Lüfter helfen. Die Zeile erscheint nur, wenn das "
      + "jetzt oder seit dem Start des Pi der Fall war.",
  },
  pi_freq: {
    title: "Takt",
    text: "Aktueller Takt der CPU (`scaling_cur_freq`) und der eingestellte Höchstwert. Ein niedriger Takt im "
      + "Leerlauf ist normal (Stromsparen); dauerhaft unter dem Höchstwert trotz Last spricht für Drosselung.",
  },
  pi_fan: {
    title: "Lüfter",
    text: "Drehzahl des Lüfters in Umdrehungen pro Minute (Pi 5: offizieller Active Cooler). „steht“ ist "
      + "normal, solange der Chip kühl genug ist – der Lüfter läuft erst ab etwa 50 °C an.",
  },
  hw_pi_power: {
    title: "Stromversorgung (Pi)",
    text: "Meldet die Firmware Unterspannung oder Drosselung – jetzt oder seit dem Start des Pi –, steht hier "
      + "„eingeschränkt“. Die Zeitausgabe läuft weiter, wird aber unruhiger; bei starker Unterspannung startet "
      + "der Pi im schlimmsten Fall neu. Abhilfe: **offizielles Netzteil** (Pi 5: 27 W USB-C, 5,1 V/5 A; "
      + "Pi 4: 15 W USB-C, 5,1 V/3 A) und ein kurzes Kabel.",
  },

  // --- RTC ---------------------------------------------------------------------
  hw_rtc: {
    title: "Echtzeituhr (RTC)",
    text: "Eine batteriegepufferte Uhr, die auch ohne Strom weiterläuft. Ohne RTC (Pi 4, Pi 5 ohne Akku an "
      + "**J5**) startet das Gerät mit der zuletzt gespeicherten Zeit. Für NTP egal – chrony korrigiert das "
      + "in Sekunden. Für **NTS** wichtig: Mit falscher Startzeit scheitert die Zertifikatsprüfung, deshalb "
      + "„Zertifikatszeit beim Start nicht prüfen“ eingeschaltet lassen.",
  },
  hw_rtc_drift: {
    title: "Abweichung der RTC",
    text: "Unterschied zwischen RTC und Systemuhr in ganzen Sekunden – die RTC zählt nur ganze Sekunden, ± 1 s "
      + "ist also Ableseauflösung. Wenige Sekunden sind normal. Bei mehr als zwei Minuten "
      + "stimmt die RTC nicht – leere Batterie oder Akku fehlt.",
  },
  hw_hctosys: {
    title: "Beim Start übernommen",
    text: "„ja“ heißt: Der Kernel hat beim Booten die Systemuhr aus dieser RTC gestellt. Dann beginnt das "
      + "Gerät schon mit ungefähr richtiger Zeit.",
  },

  // --- GPS-Seite ----------------------------------------------------------------
  gps_receiver_card: {
    title: "Dein Empfänger",
    text: "Was der Hardware-Check über den eingetragenen (oder ersten gefundenen) Empfänger herausgefunden "
      + "hat: Anschluss, PPS-Weg und die damit erreichbare Genauigkeit. Alle Details stehen auf der Seite "
      + "„Hardware“.",
  },
  gps_device: {
    title: "Gerät",
    text: "Die serielle Schnittstelle, von der gpsd liest, dahinter der von gpsd erkannte Treiber "
      + "(z. B. `u-blox`, `NMEA0183`).",
  },
  gps_baud: {
    title: "Baudrate",
    text: "Übertragungsgeschwindigkeit der seriellen Schnittstelle. gpsd erkennt sie selbst; bei USB-CDC-"
      + "Empfängern spielt sie praktisch keine Rolle. Nur bei UART-Empfängern muss sie zum Modul passen "
      + "(meist 9600 oder 38400).",
  },
  gpsd_version: {
    title: "gpsd",
    text: "Version des GPS-Dienstes im Container. gpsd liest den Empfänger aus und stellt chrony die Zeit "
      + "über Shared Memory bereit.",
  },
  gps_time: {
    title: "GPS-Zeit",
    text: "Die Uhrzeit aus der letzten Positionsmeldung (UTC). Sie dient nur zur Kontrolle – chrony nutzt "
      + "die genauere Messung über Shared Memory.",
  },
  gps_leapseconds: {
    title: "Schaltsekunden (GPS−UTC)",
    text: "GPS-Zeit zählt keine Schaltsekunden und läuft UTC derzeit **18 s** voraus. Der Empfänger kennt "
      + "diesen Wert aus dem Almanach; direkt nach einem Kaltstart kann er bis zu 12,5 Minuten fehlen.",
  },
  gps_position: {
    title: "Position",
    text: "Breite, Länge und Höhe laut Empfänger. Für die Zeit unwichtig, aber ein guter Plausibilitäts-"
      + "check: Springt die Position stark, ist der Empfang schlecht.",
  },
  gps_samples: {
    title: "Datenbasis",
    text: "Wie viele Vergleiche zwischen GPS und Netzwerkquellen in den Vorschlag eingehen und über welchen "
      + "Zeitraum. Mehr Messungen über mehrere Stunden ergeben einen stabileren Wert.",
  },
  gps_source_state: {
    title: "Zustand in chrony",
    text: "Wie chrony die GPS-Quelle gerade einordnet: ausgewählt (stellt die Uhr), kombiniert, nur "
      + "beobachtet, Falseticker oder ohne Daten. Die einzelnen Zustände erklärt die Seite „Zeitquellen“.",
  },
  gps_select_reason: {
    title: "Grund",
    text: "Warum chrony die GPS-Quelle (nicht) nutzt – laut `chronyc selectdata`. Häufig bei USB-GPS: "
      + "„Unsicherheit zu groß“, weil der eingestellte Delay größer ist als die Unsicherheit der "
      + "Netzwerkquellen. Der Kalibrier-Assistent behebt das.",
  },

  // --- PTP-Seite ------------------------------------------------------------------
  ptp_interface: {
    title: "Interface",
    text: "Die Netzwerkkarte, über die ptp4l PTP spricht. Für Hardware-PTP muss genau diese Karte "
      + "Hardware-Zeitstempel und eine eigene PTP-Uhr haben.",
  },
  ptp_clock_identity: {
    title: "Eigene Kennung",
    text: "Die weltweit eindeutige Kennung dieser PTP-Uhr (meist aus der MAC-Adresse gebildet). Ist sie "
      + "gleich der Grandmaster-Kennung, ist dieser Server selbst der Grandmaster.",
  },
  ptp_time_traceable: {
    title: "Zeit rückverfolgbar",
    text: "Der Grandmaster meldet, dass seine Zeit auf eine echte Referenz (GPS, Atomuhr) zurückgeht. Clients "
      + "und Switches werten das teils aus. Bei einem GPS-Grandmaster sollte hier „ja“ stehen, sobald das "
      + "GPS synchron ist.",
  },
  ptp_grandmaster_flow: {
    title: "So arbeitet der Grandmaster",
    text: "Drei Schritte: **chrony** stellt die Systemuhr nach GPS/PPS, **phc2sys** kopiert die Systemuhr in "
      + "die PTP-Uhr der Netzwerkkarte (inklusive der 37 s Abstand zwischen UTC und der PTP-Zeitskala TAI; "
      + "dafür muss phc2sys eingeschaltet sein, `PHC2SYS_ENABLE=true`), "
      + "**ptp4l** verteilt diese Uhr ins Netz. Im Slave-Modus läuft es umgekehrt: ptp4l stellt die Karte, "
      + "und chrony oder phc2sys übernehmen die Zeit in die Systemuhr.",
  },
  nic_driver: {
    title: "Treiber",
    text: "Der Kernel-Treiber der Netzwerkkarte. Er verrät viel über die PTP-Fähigkeit: `igb`, `igc`, "
      + "`ixgbe`, `ice`, `macb` (Pi 5) sind gut; `r8169`, `r8152`, `lan78xx`, `virtio_net` können kein "
      + "Hardware-PTP.",
  },
  nic_state: {
    title: "Zustand",
    text: "Verbindungszustand laut Kernel: `up` = Kabel steckt und Verbindung steht, `down` = keine "
      + "Verbindung, `unknown` = der Treiber meldet nichts (typisch bei virtuellen Karten).",
  },
  nic_hw_timestamps: {
    title: "Hardware-Zeitstempel (senden / empfangen)",
    text: "Ob die Karte laut `ethtool -T` beim Senden und Empfangen selbst Zeitstempel setzt "
      + "(`hardware-transmit` / `hardware-receive`). Beides ist für Hardware-PTP nötig.",
  },
  nic_suitability: {
    title: "Eignung",
    text: "Zusammenfassung: **PTP-tauglich** heißt Hardware-Zeitstempel in beide Richtungen und eine PTP-Uhr. "
      + "Sonst geht PTP nur mit Software-Zeitstempeln – nicht genauer als NTP.",
  },
  ptp_chk_network: {
    title: "Netzwerk zwischen den Teilnehmern",
    text: "Lässt sich nicht automatisch prüfen. Jeder Switch verzögert Pakete unterschiedlich lang. Für "
      + "Nanosekunden braucht es Switches mit Transparent- oder Boundary-Clock oder eine Direktverbindung.",
  },
  ptp_chk_clients: {
    title: "PTP-fähige Clients",
    text: "Lässt sich nicht automatisch prüfen. Linux mit linuxptp, viele Audio-Geräte (AES67, Ravenna; "
      + "Dante nur im AES67-Modus) und Messgeräte können PTP. Alle anderen nutzen NTP von diesem Server.",
  },
};

export const HELP_GROUP_HARDWARE = {
  title: "Hardware-Check",
  keys: [
    "hw_check", "hw_refresh", "hw_platform", "hw_board", "hw_arch", "hw_hypervisor", "hw_container",
    "hw_matrix", "hw_fix", "hw_accuracy", "hw_ladder", "hw_ntp_server", "hw_clock_control", "hw_nts",
    "hw_gps_usb", "hw_gps_pps", "hw_ptp_hw", "hw_ptp_sw", "hw_ptp_to_ntp", "hw_gps_to_ptp", "hw_warnings",
    "hw_receiver", "hw_verdict", "hw_interface", "hw_tty_driver", "hw_device_path", "hw_stable_path",
    "hw_usb_id", "hw_gpsd_driver", "hw_gpsd_activated", "hw_presence", "hw_pps_path", "hw_gpsd_pps", "hw_toff",
    "hw_pps_sources", "hw_pps_kind", "hw_pps_state", "hw_pps_rate", "hw_pps_phase", "hw_pps_configured",
    "hw_ptp_clocks", "hw_clock_name", "hw_ptp_kind", "hw_ptp_pins", "hw_pps_available", "hw_max_adj",
    "hw_nic_class", "hw_passthrough", "hw_caps", "hw_privileged", "hw_sys_time", "hw_net_admin", "hw_net_raw",
    "hw_sys_nice", "hw_network", "hw_dev_mounted", "hw_modules", "hw_majors", "hw_rtc", "hw_rtc_drift",
    "hw_hctosys", "pi_state", "pi_undervoltage", "pi_throttled", "pi_capped", "pi_soft_temp", "pi_freq",
    "pi_fan", "hw_pi_power",
    "gps_receiver_card", "gps_device", "gps_baud", "gpsd_version", "gps_time", "gps_leapseconds",
    "gps_position", "gps_samples", "gps_source_state", "gps_select_reason",
    "ptp_interface", "ptp_clock_identity", "ptp_time_traceable", "ptp_grandmaster_flow", "nic_driver",
    "nic_state", "nic_hw_timestamps", "nic_suitability", "ptp_chk_network", "ptp_chk_clients",
  ],
};
