#!/usr/bin/env bash
set -euo pipefail

# Grok pela OpenRouter, executado pela CLI qwen: mesmo transporte, catálogo
# (qwen-agent-settings.json) e OPENROUTER_API_KEY do agente qwen. Não existe
# CLI nem chave própria do Grok nesta VPS.
export QWEN_PROVIDER=openrouter
export QWEN_MODEL="${GROK_MODEL:-x-ai/grok-4.7}"
exec "$(dirname "$(realpath "$0")")/start_qwen_agent.sh" "$@"
