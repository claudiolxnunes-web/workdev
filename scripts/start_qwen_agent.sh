#!/usr/bin/env bash
set -euo pipefail

# O env real do serviço; o antigo apps/api/.env é resíduo root:root 600.
WORKDEV_ENV_FILE="${WORKDEV_ENV_FILE:-/etc/workdev/workdev-api.env}"
QWEN_EXECUTABLE="${QWEN_EXECUTABLE:-/usr/bin/qwen}"
QWEN_SETTINGS_FILE="${QWEN_SETTINGS_FILE:-/opt/workdev/scripts/qwen-agent-settings.json}"
export COLORTERM="${COLORTERM:-truecolor}"
QWEN_PROVIDER="${QWEN_PROVIDER:-openrouter}"

if [[ ! -r "$WORKDEV_ENV_FILE" ]]; then
  echo "Qwen Code Agent: arquivo de configuração não encontrado" >&2
  exit 1
fi
if [[ ! -x "$QWEN_EXECUTABLE" ]]; then
  echo "Qwen Code Agent: CLI qwen não instalada" >&2
  exit 1
fi
if [[ ! -r "$QWEN_SETTINGS_FILE" ]]; then
  echo "Qwen Code Agent: catálogo de providers não encontrado" >&2
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
qwen_provider="$QWEN_PROVIDER"

use_dashscope() {
  selected_model="qwen3-coder-plus"
}

use_openrouter() {
  # Modelo escolhido na UI ou default histórico. O catálogo em
  # qwen-agent-settings.json é reescrito com esse modelo para garantir que a
  # seleção seja efetiva, já que o Qwen Code pode dar precedência a
  # model.name do system settings sobre o argumento --model.
  selected_model="${QWEN_MODEL:-qwen/qwen3.5-397b-a17b}"
}

[[ -n "$dashscope_key" ]] && export DASHSCOPE_API_KEY="$dashscope_key"
[[ -n "$openrouter_key" ]] && export OPENROUTER_API_KEY="$openrouter_key"

case "$qwen_provider" in
  dashscope)
    if [[ -z "$dashscope_key" ]]; then
      echo "Qwen Code Agent: DASHSCOPE_API_KEY não configurada" >&2
      exit 1
    fi
    use_dashscope
    ;;
  openrouter)
    if [[ -z "$openrouter_key" ]]; then
      echo "Qwen Code Agent: OPENROUTER_API_KEY não configurada" >&2
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
      echo "Qwen Code Agent: configure DASHSCOPE_API_KEY ou OPENROUTER_API_KEY" >&2
      exit 1
    fi
    ;;
  *)
    echo "Qwen Code Agent: QWEN_PROVIDER inválido ('$qwen_provider')." >&2
    exit 1
    ;;
esac

# Gera system settings efêmero com model.name sincronizado com a seleção da UI.
# Isso torna a escolha efetiva mesmo quando a CLI prioriza o settings file.
QWEN_EFFECTIVE_SETTINGS_FILE="$(mktemp -t qwen-settings-XXXXXX.json)"
python3 - "$QWEN_SETTINGS_FILE" "$selected_model" "$QWEN_EFFECTIVE_SETTINGS_FILE" <<'PYEOF'
import json, sys
src, model, dst = sys.argv[1:4]
with open(src, "r") as handle:
    settings = json.load(handle)
settings["model"] = {"name": model}
with open(dst, "w") as handle:
    json.dump(settings, handle)
PYEOF

unset dashscope_key openrouter_key qwen_provider
unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_MODEL
export QWEN_CODE_SYSTEM_SETTINGS_PATH="$QWEN_EFFECTIVE_SETTINGS_FILE"
export QWEN_CODE_SKIP_UPDATE_CHECK_ONCE="true"
export NO_UPDATE_NOTIFIER="1"

cd "${WORKDEV_AGENT_CWD:-${WORKDEV_DIR:-/opt/workdev}}"
exec "$QWEN_EXECUTABLE" --model "$selected_model" "$@"
