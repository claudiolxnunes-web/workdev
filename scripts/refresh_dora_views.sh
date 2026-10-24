#!/bin/bash
# Wrapper para refresh DORA — carrega WORKDEV_API_KEY do .env da API
set -a
source /opt/workdev/apps/api/.env
set +a
exec /opt/workdev/apps/api/venv/bin/python /opt/workdev/scripts/refresh_dora_views.py
