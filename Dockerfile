# ntp-gui – Chrony (NTP) + linuxptp (PTP) + Web-Dashboard in einem Container.
# Basis-Image per Digest festgenagelt: nur so kann Dependabot (.github/dependabot.yml) neue
# Debian-Stände als Pull Request vorschlagen – ein reines „trixie-slim“ hat keine Version zum Vergleichen.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2

ARG DEBIAN_FRONTEND=noninteractive
# Paketversionen bewusst nicht festgenagelt: Debian entfernt ältere Stände aus dem Archiv, ein Pin
# ließe den Release-Bau nach dem nächsten Sicherheitsupdate scheitern. Der Release baut ohne Cache mit
# den aktuellen Paketen; welche genau drin sind, belegen SBOM, Schwachstellen-Bericht und
# Herkunftsnachweis am Image-Digest.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chrony \
        linuxptp \
        gpsd \
        python3 \
        tzdata \
        ca-certificates \
        iproute2 \
        procps \
        ethtool \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/chrony /var/lib/chrony /var/log/chrony /etc/linuxptp /config \
    # Eigener Benutzer für Dashboard und DNS-Weiterleiter (der Entrypoint wechselt per setpriv);
    # Mitglied von _chrony für den Kommando-Socket von chronyd. Feste IDs, damit das Datenverzeichnis
    # über Image-Versionen hinweg demselben Benutzer gehört.
    && groupadd --system --gid 990 ntpgui \
    && useradd --system --uid 990 --gid ntpgui --groups _chrony --no-create-home \
         --home-dir /nonexistent --shell /usr/sbin/nologin ntpgui \
    # Keine SUID-/SGID-Programme im Image (su, mount, passwd …): Wer einen Dienst übernimmt, soll
    # darüber nicht zurück zu root kommen.
    && find / -xdev -type f -perm /6000 -exec chmod a-s {} +

COPY app/ /app/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Alle einstellbaren Werte haben ihre Standards im Einstellungsschema
# (app/settings.py) und lassen sich per Umgebungsvariable oder im Dashboard
# setzen. Hier nur, was für den Start des Dashboards selbst nötig ist.
ENV WEB_PORT="8080" \
    WEB_BIND="0.0.0.0" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1"

WORKDIR /app
EXPOSE 123/udp 319/udp 320/udp 4460/tcp 8080/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('WEB_PORT','8080')+'/healthz',timeout=4)" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
