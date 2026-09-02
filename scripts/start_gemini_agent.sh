#!/usr/bin/env bash
set -euo pipefail

WORKDEV_ENV_FILE="${WORKDEV_ENV_FILE:-/etc/workdev/workdev-api.env}"
GEMINI_EXECUTABLE="${GEMINI_EXECUTABLE:-/usr/bin/gemini}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash}"
GEMINI_SETTINGS_FILE="${GEMINI_SETTINGS_FILE:-/opt/workdev/scripts/gemini-agent-settings.json}"

if [[ ! -r "$WORKDEV_ENV_FILE" ]]; then
  echo "Gemini Agent: arquivo de configuração não encontrado" >&2
  exit 1
fi

if [[ ! -x "$GEMINI_EXECUTABLE" ]]; then
  echo "Gemini Agent: CLI gemini não instalada" >&2
  exit 1
fi
if [[ ! -r "$GEMINI_SETTINGS_FILE" ]]; then
  echo "Gemini Agent: configuração de sistema não encontrada" >&2
  exit 1
fi

gemini_key=$(sed -n 's/^GEMINI_API_KEY=//p' "$WORKDEV_ENV_FILE" | tail -n 1)
gemini_key=${gemini_key%\"}
gemini_key=${gemini_key#\"}
gemini_key=${gemini_key%\'}
gemini_key=${gemini_key#\'}

if [[ -z "$gemini_key" ]]; then
  echo "Gemini Agent: GEMINI_API_KEY não configurada" >&2
  exit 1
fi

export GEMINI_API_KEY="$gemini_key"
export GEMINI_CLI_SYSTEM_SETTINGS_PATH="$GEMINI_SETTINGS_FILE"
export NO_UPDATE_NOTIFIER=1
unset gemini_key

cd "${WORKDEV_AGENT_CWD:-${WORKDEV_DIR:-/opt/workdev}}"

approval_mode="default"
for argument in "$@"; do
  if [[ "$argument" == "--prompt" || "$argument" == "-p" ]]; then
    approval_mode="yolo"
    break
  fi
done

exec "$GEMINI_EXECUTABLE" \
  --skip-trust \
  --model "$GEMINI_MODEL" \
  --approval-mode "$approval_mode" \
  "$@"
