#!/usr/bin/env bash
set -euo pipefail

# O env real do serviço; o antigo apps/api/.env é resíduo root:root 600.
WORKDEV_ENV_FILE="${WORKDEV_ENV_FILE:-/etc/workdev/workdev-api.env}"
QWEN_EXECUTABLE="${QWEN_EXECUTABLE:-/usr/bin/qwen}"
QWEN_SETTINGS_FILE="${QWEN_SETTINGS_FILE:-/opt/workdev/scripts/qwen-agent-settings.json}"

if [[ ! -r "$WORKDEV_ENV_FILE" ]]; then
  echo "Qwen Agent: arquivo de configuração não encontrado" >&2
  exit 1
fi
if [[ ! -x "$QWEN_EXECUTABLE" ]]; then
  echo "Qwen Agent: CLI qwen não instalada" >&2
  exit 1
fi
if [[ ! -r "$QWEN_SETTINGS_FILE" ]]; then
  echo "Qwen Agent: catálogo de providers não encontrado" >&2
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
qwen_provider=$(read_env_value QWEN_PROVIDER)

use_dashscope() {
  selected_model="qwen3-coder-plus"
}

use_openrouter() {
  # Modelo principal do Qwen Code, igual ao vinculado ao agente no catálogo.
  selected_model="${QWEN_MODEL:-qwen/qwen3.5-397b-a17b}"
}

[[ -n "$dashscope_key" ]] && export DASHSCOPE_API_KEY="$dashscope_key"
[[ -n "$openrouter_key" ]] && export OPENROUTER_API_KEY="$openrouter_key"

if [[ -z "$qwen_provider" && -t 0 ]]; then
  echo "Qual provider usar para o Qwen3 Coder?" >&2
  [[ -n "$dashscope_key" ]] && echo "  1) DashScope (direto)" >&2
  [[ -n "$openrouter_key" ]] && echo "  2) OpenRouter" >&2
  read -r -p "Escolha [1/2]: " choice
  case "$choice" in
    1) qwen_provider="dashscope" ;;
    2) qwen_provider="openrouter" ;;
    *) echo "Opção inválida." >&2; exit 1 ;;
  esac
fi

case "$qwen_provider" in
  dashscope)
    if [[ -z "$dashscope_key" ]]; then
      echo "Qwen Agent: DASHSCOPE_API_KEY não configurada" >&2
      exit 1
    fi
    use_dashscope
    ;;
  openrouter)
    if [[ -z "$openrouter_key" ]]; then
      echo "Qwen Agent: OPENROUTER_API_KEY não configurada" >&2
      exit 1
    fi
    use_openrouter
    ;;
  "")
    if [[ -n "$dashscope_key" ]]; then
      use_dashscope
    elif [[ -n "$openrouter_key" ]]; then
      use_openrouter
    else
      echo "Qwen Agent: configure DASHSCOPE_API_KEY ou OPENROUTER_API_KEY" >&2
      exit 1
    fi
    ;;
  *)
    echo "Qwen Agent: QWEN_PROVIDER inválido ('$qwen_provider')." >&2
    exit 1
    ;;
esac

unset dashscope_key openrouter_key qwen_provider
unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_MODEL
export QWEN_CODE_SYSTEM_SETTINGS_PATH="$QWEN_SETTINGS_FILE"

cd /opt/workdev
exec "$QWEN_EXECUTABLE" --model "$selected_model" "$@"
