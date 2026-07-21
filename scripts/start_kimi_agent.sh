#!/usr/bin/env bash
set -euo pipefail

WORKDEV_ENV_FILE="${WORKDEV_ENV_FILE:-/opt/workdev/apps/api/.env}"
KIMI_EXECUTABLE="${KIMI_EXECUTABLE:-/usr/bin/kimi}"

if [[ ! -r "$WORKDEV_ENV_FILE" ]]; then
  echo "Kimi Agent: arquivo de configuração não encontrado" >&2
  exit 1
fi
if [[ ! -x "$KIMI_EXECUTABLE" ]]; then
  echo "Kimi Agent: CLI kimi não instalada" >&2
  exit 1
fi

moonshot_key=$(sed -n 's/^MOONSHOT_API_KEY=//p' "$WORKDEV_ENV_FILE" | tail -n 1)
moonshot_key=${moonshot_key%\"}
moonshot_key=${moonshot_key#\"}
moonshot_key=${moonshot_key%\'}
moonshot_key=${moonshot_key#\'}
if [[ -z "$moonshot_key" ]]; then
  echo "Kimi Agent: MOONSHOT_API_KEY não configurada" >&2
  exit 1
fi

export KIMI_MODEL_NAME="${KIMI_MODEL_NAME:-kimi-k2.7-code}"
export KIMI_MODEL_DISPLAY_NAME="${KIMI_MODEL_DISPLAY_NAME:-Kimi K2.7 Code}"
export KIMI_MODEL_API_KEY="$moonshot_key"
export KIMI_MODEL_BASE_URL="${KIMI_MODEL_BASE_URL:-https://api.moonshot.cn/v1}"
export KIMI_MODEL_PROVIDER_TYPE="kimi"
export KIMI_MODEL_MAX_CONTEXT_SIZE="${KIMI_MODEL_MAX_CONTEXT_SIZE:-262144}"
export KIMI_DISABLE_TELEMETRY="1"
unset moonshot_key

cd /opt/workdev
exec "$KIMI_EXECUTABLE" "$@"
