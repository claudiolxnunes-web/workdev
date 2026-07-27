#!/bin/bash
# Healthcheck do workdev-api.service: reinicia o serviço se /health não
# responder com 200 dentro do timeout. Rodado via cron a cada 5 min.
set -uo pipefail

URL="http://127.0.0.1:8000/health"
TIMEOUT=10
LOG=/var/log/workdev-api-healthcheck.log

http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$URL")
curl_exit=$?

if [ "$curl_exit" -ne 0 ] || [ "$http_code" != "200" ]; then
    echo "$(date -Iseconds) workdev-api unhealthy (curl_exit=$curl_exit http_code=$http_code) — reiniciando" >> "$LOG"
    systemctl restart workdev-api.service
fi
