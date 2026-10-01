#!/usr/bin/env bash
set -euo pipefail

# DeepSeek pela OpenRouter, executado pela CLI qwen: mesmo transporte, catálogo
# (qwen-agent-settings.json) e OPENROUTER_API_KEY do agente qwen. Não existe
# CLI nem chave própria do DeepSeek nesta VPS.
export QWEN_PROVIDER=openrouter
export QWEN_MODEL="${DEEPSEEK_MODEL:-deepseek/deepseek-v4-flash}"
exec "$(dirname "$(realpath "$0")")/start_qwen_agent.sh" "$@"
