#!/usr/bin/env bash
set -euo pipefail

WORKDEV_ENV_FILE="${WORKDEV_ENV_FILE:-/opt/workdev/apps/api/.env}"
QWEN_EXECUTABLE="${QWEN_EXECUTABLE:-/usr/bin/qwen}"

if [[ ! -r "$WORKDEV_ENV_FILE" ]]; then
  echo "Qwen Agent: arquivo de configuração não encontrado" >&2
  exit 1
fi
if [[ ! -x "$QWEN_EXECUTABLE" ]]; then
  echo "Qwen Agent: CLI qwen não instalada" >&2
  exit 1
fi

read_env_value() {
  local name="$1"
  local value
  value=$(sed -n "s/^${name}=//p" "$WORKDEV_ENV_FILE" | tail -n 1)
  value=${value%\"}
  value=${value#\"}
  value=${value%\'}
  value=${value#\'}
  printf '%s' "$value"
}

dashscope_key=$(read_env_value DASHSCOPE_API_KEY)
openrouter_key=$(read_env_value OPENROUTER_API_KEY)

if [[ -n "$dashscope_key" ]]; then
  export DASHSCOPE_API_KEY="$dashscope_key"
  export OPENAI_API_KEY="$dashscope_key"
  export OPENAI_BASE_URL="${QWEN_BASE_URL:-https://dashscope-intl.aliyuncs.com/compatible-mode/v1}"
  export OPENAI_MODEL="${QWEN_MODEL:-qwen3-coder-plus}"
elif [[ -n "$openrouter_key" ]]; then
  export OPENROUTER_API_KEY="$openrouter_key"
  export OPENAI_API_KEY="$openrouter_key"
  export OPENAI_BASE_URL="${QWEN_BASE_URL:-https://openrouter.ai/api/v1}"
  export OPENAI_MODEL="${QWEN_MODEL:-qwen/qwen3-coder-plus}"
else
  echo "Qwen Agent: configure DASHSCOPE_API_KEY ou OPENROUTER_API_KEY" >&2
  exit 1
fi

unset dashscope_key openrouter_key

cd /opt/workdev
exec "$QWEN_EXECUTABLE" --model "$OPENAI_MODEL" "$@"
