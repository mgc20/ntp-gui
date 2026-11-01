# ntp-gui – Chrony (NTP) + linuxptp (PTP) + Web-Dashboard in einem Container.
FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
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
    && mkdir -p /var/run/chrony /var/lib/chrony /var/log/chrony /etc/linuxptp /config

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
