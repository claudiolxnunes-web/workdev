#!/usr/bin/env bash
set -euo pipefail

# Agente local: reaproveita o CLI qwen (compatível OpenAI), mas apontando
# para o llama.cpp local (127.0.0.1:8080), nunca para OpenRouter/DashScope.
QWEN_EXECUTABLE="${QWEN_EXECUTABLE:-/usr/bin/qwen}"
LOCAL_SETTINGS_FILE="${LOCAL_SETTINGS_FILE:-/opt/workdev/scripts/local-agent-settings.json}"
export COLORTERM="${COLORTERM:-truecolor}"

if [[ ! -x "$QWEN_EXECUTABLE" ]]; then
  echo "Local Agent: CLI qwen não instalada" >&2
  exit 1
fi
if [[ ! -r "$LOCAL_SETTINGS_FILE" ]]; then
  echo "Local Agent: catálogo de providers não encontrado" >&2
  exit 1
fi

# O llama.cpp local não exige autenticação; placeholder só pra satisfazer o CLI.
export WORKDEV_LOCAL_CODE_KEY="${WORKDEV_LOCAL_CODE_KEY:-local-sem-autenticacao}"

unset DASHSCOPE_API_KEY OPENROUTER_API_KEY
unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_MODEL
# Overlay only: provider/model catalog remains untouched.
PROTOCOL_SCRIPT="$(dirname "$(realpath "$0")")/local_code_protocol.py"
export QWEN_CODE_SYSTEM_SETTINGS_PATH
QWEN_CODE_SYSTEM_SETTINGS_PATH="$(python3 "$PROTOCOL_SCRIPT" settings "$LOCAL_SETTINGS_FILE")"
export WORKDEV_LOCAL_CODE_INPUT_FILE="$(dirname "$QWEN_CODE_SYSTEM_SETTINGS_PATH")/input.jsonl"
export QWEN_CODE_SKIP_UPDATE_CHECK_ONCE="true"
export NO_UPDATE_NOTIFIER="1"
# CPU: prompt frio pode passar de 4 min; evita cancelamento e reenvio da CLI
export QWEN_STREAM_IDLE_TIMEOUT_MS="${QWEN_STREAM_IDLE_TIMEOUT_MS:-1200000}"
export QWEN_STREAM_MAX_LIFETIME_MS="${QWEN_STREAM_MAX_LIFETIME_MS:-2400000}"
export QWEN_CODE_API_TIMEOUT_MS="${QWEN_CODE_API_TIMEOUT_MS:-2400000}"

cd "${WORKDEV_AGENT_CWD:-${WORKDEV_DIR:-/opt/workdev}}"
exec "$QWEN_EXECUTABLE" --model "${WORKDEV_LOCAL_CODE_MODEL:-workdev-qwen27b}" --prompt-interactive WORKDEV_READY "$@"
