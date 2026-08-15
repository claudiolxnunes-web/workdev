#!/usr/bin/env bash
set -euo pipefail

WORKDEV_ENV_FILE="${WORKDEV_ENV_FILE:-/opt/workdev/apps/api/.env}"
KIMI_EXECUTABLE="${KIMI_EXECUTABLE:-/usr/bin/kimi}"
KIMI_PROVIDER="${KIMI_PROVIDER:-moonshot}"

if [[ ! -r "$WORKDEV_ENV_FILE" ]]; then
  echo "Kimi Agent: arquivo de configuração não encontrado" >&2
  exit 1
fi
if [[ ! -x "$KIMI_EXECUTABLE" ]]; then
  echo "Kimi Agent: CLI kimi não instalada" >&2
  exit 1
fi

_read_env_var() {
  local var="$1" value
  value=$(sed -n "s/^${var}=//p" "$WORKDEV_ENV_FILE" | tail -n 1)
  value=${value%\"}
  value=${value#\"}
  value=${value%\'}
  value=${value#\'}
  printf '%s' "$value"
}

case "$KIMI_PROVIDER" in
  moonshot)
    api_key=$(_read_env_var MOONSHOT_API_KEY)
    if [[ -z "$api_key" ]]; then
      echo "Kimi Agent: MOONSHOT_API_KEY não configurada" >&2
      exit 1
    fi
    export KIMI_MODEL_NAME="kimi-k2.7-code"
    export KIMI_MODEL_DISPLAY_NAME="Kimi K2.7 Code"
    export KIMI_MODEL_BASE_URL="https://api.moonshot.cn/v1"
    export KIMI_MODEL_PROVIDER_TYPE="kimi"
    ;;
  openrouter)
    api_key=$(_read_env_var OPENROUTER_API_KEY)
    if [[ -z "$api_key" ]]; then
      echo "Kimi Agent: OPENROUTER_API_KEY não configurada" >&2
      exit 1
    fi
    export KIMI_MODEL_NAME="moonshotai/kimi-k2.7-code"
    export KIMI_MODEL_DISPLAY_NAME="Kimi K2.7 Code (OpenRouter)"
    export KIMI_MODEL_BASE_URL="https://openrouter.ai/api/v1"
    export KIMI_MODEL_PROVIDER_TYPE="openai"
    ;;
  *)
    echo "Kimi Agent: KIMI_PROVIDER inválido ('$KIMI_PROVIDER'); use moonshot ou openrouter" >&2
    exit 1
    ;;
esac

export KIMI_MODEL_API_KEY="$api_key"
export KIMI_MODEL_MAX_CONTEXT_SIZE="${KIMI_MODEL_MAX_CONTEXT_SIZE:-262144}"
export KIMI_DISABLE_TELEMETRY="1"
unset api_key

cd /opt/workdev
exec "$KIMI_EXECUTABLE" "$@"
