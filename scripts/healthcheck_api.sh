#!/bin/bash
# Healthcheck do workdev-api.service: reinicia o serviço se /health não
# responder com 200 dentro do timeout. Rodado via cron a cada 5 min.
set -uo pipefail

URL="http://127.0.0.1:8000/health"
TIMEOUT=10
LOG=/var/log/workdev-api-healthcheck.log
ALERT_ENV=/opt/scripts/alerta.env
STATE_DIR=/var/lib/healthcheck-api
STATE_FILE="$STATE_DIR/last_alert"
ANTI_SPAM_SECONDS=$((6 * 3600))

http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$URL")
curl_exit=$?

if [ "$curl_exit" -ne 0 ] || [ "$http_code" != "200" ]; then
    echo "$(date -Iseconds) workdev-api unhealthy (curl_exit=$curl_exit http_code=$http_code) — reiniciando" >> "$LOG"
    logger -t healthcheck-api "workdev-api unhealthy (curl_exit=$curl_exit http_code=$http_code) — reiniciando"
    systemctl restart workdev-api.service

    mkdir -p "$STATE_DIR"

    cutoff=$(date -d "-24 hours" -Iseconds)
    restart_count_24h=$(awk -v cutoff="$cutoff" '$1 >= cutoff' "$LOG" 2>/dev/null | wc -l)

    now=$(date +%s)
    last=0
    if [ -f "$STATE_FILE" ]; then
        last=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
        case "$last" in ''|*[!0-9]*) last=0 ;; esac
    fi

    if [ "$now" -ge "$((last + ANTI_SPAM_SECONDS))" ]; then
        if [ -r "$ALERT_ENV" ]; then
            set -a
            # shellcheck disable=SC1090
            . "$ALERT_ENV"
            set +a
            if [ -n "${TG_TOKEN:-}" ] && [ -n "${TG_CHAT:-}" ]; then
                if [ "$restart_count_24h" -gt 1 ]; then
                    classificacao="possível loop de restart"
                else
                    classificacao="falha isolada"
                fi
                texto="[healthcheck-api] workdev-api unhealthy (curl_exit=$curl_exit http_code=$http_code), reiniciado. Reinícios nas últimas 24h: $restart_count_24h ($classificacao)."
                curl -s -o /dev/null -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
                    -d "chat_id=${TG_CHAT}" \
                    -d "text=${texto}"
                echo "$now" > "$STATE_FILE"
                logger -t healthcheck-api "alerta enviado (reinicios 24h: $restart_count_24h, $classificacao)"
            else
                logger -t healthcheck-api "TG_TOKEN/TG_CHAT ausentes após source de $ALERT_ENV — alerta não enviado"
            fi
        else
            logger -t healthcheck-api "$ALERT_ENV ausente ou ilegível — alerta não enviado"
        fi
    else
        logger -t healthcheck-api "alerta suprimido (anti-spam ativo)"
    fi
fi
