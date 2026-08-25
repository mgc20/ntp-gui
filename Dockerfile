# ntp-gui – Chrony (NTP) + linuxptp (PTP) + Web-Dashboard in einem Container.
FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chrony \
        linuxptp \
        python3 \
        tzdata \
        ca-certificates \
        iproute2 \
        procps \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/chrony /var/lib/chrony /var/log/chrony /etc/linuxptp /config

COPY app/ /app/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# --- NTP -------------------------------------------------------------------
ENV NTP_POOLS="pool.ntp.org" \
    NTP_SERVERS="" \
    NTP_PEERS="" \
    NTP_PORT="123" \
    ALLOW_NETWORKS="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,fc00::/7,fe80::/10" \
    DENY_NETWORKS="" \
    SERVE_UNSYNCED="true" \
    LOCAL_STRATUM="10" \
    DISABLE_CLOCK_CONTROL="auto"

# --- PTP -------------------------------------------------------------------
ENV PTP_ENABLE="false" \
    PTP_INTERFACE="" \
    PTP_MODE="auto" \
    PTP_DOMAIN="0" \
    PTP_TRANSPORT="UDPv4" \
    PTP_TIME_STAMPING="hardware" \
    PHC2SYS_ENABLE="false"

# --- Web -------------------------------------------------------------------
ENV WEB_PORT="8080" \
    WEB_BIND="0.0.0.0" \
    WEB_TITLE="NTP / PTP Time Server" \
    WEB_REFRESH_SECONDS="5" \
    HISTORY_INTERVAL="10" \
    HISTORY_SIZE="720" \
    PYTHONUNBUFFERED="1"

WORKDIR /app
EXPOSE 123/udp 319/udp 320/udp 8080/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('WEB_PORT','8080')+'/healthz',timeout=4)" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
