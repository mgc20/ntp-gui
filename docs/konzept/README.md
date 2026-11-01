# Konzept-Dokumente

Stand: 01.11.2026 · Grundlage: [README](../../README.md), [ROADMAP](../../ROADMAP.md), Stand von 1.3 im Arbeitsbaum

Dieser Ordner hält fest, **wie** ntp-gui weiterentwickelt wird und **warum** etwas so entschieden
wurde. Die [ROADMAP](../../ROADMAP.md) sagt kurz, *was* kommt. Diese Dokumente liefern die
Begründung, die Abwägungen, die geprüften Fremdprojekte und die Abnahmekriterien.

## Kurzfassung

ntp-gui ist ein Ein-Personen-Projekt mit KI-Hilfe. Darum gilt für jede neue Funktion: **größter
Nutzen für die Community bei überschaubarem Aufwand, Sicherheit durch Einfachheit und so viel
bewährte Open-Source-Software wie möglich.** Neue Fähigkeiten kommen bevorzugt aus Debian-Paketen,
die schon im Image sind (chrony, gpsd, linuxptp), aus der Python-Standardbibliothek oder aus
fremden Containern, die der Nutzer *optional* daneben betreibt (Apprise-API, Caddy, Healthchecks).
Eigener Code bleibt klein und dort, wo es nichts Passendes gibt.

Version **1.4** („Melden, Einbinden, Uhrqualität sichtbar“) baut auf dem trixie-Image aus 1.3.1 auf
und bringt Benachrichtigungen, MQTT/Home Assistant, Allan-Abweichung, Messung für den
Temperaturausgleich, Schaltsekunden-Übersicht, Vollbild-Uhr und einen opt-in Update-Hinweis.
Nichts davon schreibt auf Hardware. Riskanteres (u-blox konfigurieren, GPS automatisch sperren,
Einstellungen im Verbund teilen) folgt in **1.5**, wenn die Praxisdaten aus 1.3/1.4 vorliegen.
Die **Community-Dienste** starten ohne eigenen Server-Code (Hardware-Liste über GitHub-Issues,
Pool-Server mit ntp-gui selbst); der erste eigene Dienst ist der Server-Test als Selbsttest.

**Gegenprüfung (01.11.2026):** Das volle 1.4 ist für einen Maintainer eher 3–4 Monate Arbeit;
[version-1.4.md](version-1.4.md#realistischer-gesamtaufwand-gegenprüfung) schlägt ein schlankes
1.4 vor. Jedes Dokument endet mit **„Offene Fragen“** – dort stehen die Entscheidungen, die nur
der Maintainer treffen kann.

## Die Dokumente

| Dokument | Inhalt | Wann lesen |
|---|---|---|
| [entscheidungsrahmen.md](entscheidungsrahmen.md) | Bewertungsschema, Faustregeln, wann „nein“, Vorlage für Entscheidungen (ADR), Beispiele aus dem Projekt | vor jeder neuen Funktion oder Abhängigkeit |
| [entscheidungen.md](entscheidungen.md) | Getroffene Entscheidungen zu den offenen Fragen (E1–E14 …) | wenn eine Frage schon entschieden sein könnte |
| [bausteine.md](bausteine.md) | Geprüfte Open-Source-Bausteine mit Empfehlung (übernehmen / Sidecar / klein selbst / weglassen) und Quellen | wenn eine Funktion Fremdsoftware brauchen könnte |
| [version-1.4.md](version-1.4.md) | Staffelung 1.4 / 1.5 / später, Bewertung je Thema, Abhängigkeiten zu 1.3, Abnahmekriterien, Sicherheit | beim Planen und Abnehmen der nächsten Versionen |
| [community-dienste.md](community-dienste.md) | Architektur der Dienste im eigenen Repository, Missbrauchs- und Datenschutz, Datenverträge mit ntp-gui, Startempfehlung | bevor am Community-Repository gearbeitet wird |

## So sind die Dokumente gedacht

- **Lebende Dokumente.** Sie werden geändert, wenn sich Fakten ändern (neue Debian-Version, ein
  Projekt wird eingestellt, Praxiswerte widerlegen eine Annahme). Jede Datei trägt oben ihr
  Stand-Datum.
- **Entscheidungen werden festgehalten.** Wer eine Abwägung trifft, trägt sie als kurzen
  Entscheidungseintrag (Vorlage im [Entscheidungsrahmen](entscheidungsrahmen.md#5-entscheidungen-festhalten-kurz-adr))
  ein. Das Projekt soll in zwei Jahren noch wissen, *warum* es z. B. keinen eigenen NTP-Code hat.
- **Quellen bleiben verlinkt.** Fakten zu Fremdprojekten (Version, Lizenz, Pflegezustand) altern
  schnell. Was nicht neu geprüft wurde, ist als solches markiert.
- **Die ROADMAP bleibt die kurze Fassung.** Ändert sich hier die Staffelung, wird die ROADMAP
  beim nächsten Release nachgezogen.
- **Kein Versprechen.** Aufwandsangaben sind Schätzungen für einen Maintainer mit KI-Hilfe. Die
  Reihenfolge darf sich ändern, wenn die Community etwas anderes dringender braucht.

## Legende (in allen Dokumenten gleich)

| Zeichen | Bedeutung |
|---|---|
| ★ / ★★ / ★★★ | Nutzen für die Community (gering / mittel / hoch) |
| ◆ / ◆◆ / ◆◆◆ | Aufwand für den Maintainer (≈ 1–3 Abende / 1–2 Wochenenden / mehrere Wochen) |
| R1 / R2 / R3 | Risiko bzw. neue Angriffsfläche (niedrig / mittel / hoch) |
| 🔒 | betrifft Daten, die die Instanz verlassen (läuft durch den zentralen Datenschutzfilter `app/egress.py`) |
| PT | Personentag (für die Community-Dienste) |
