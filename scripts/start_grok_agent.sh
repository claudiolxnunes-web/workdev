#!/usr/bin/env bash
set -euo pipefail

# Grok pela OpenRouter, executado pela CLI qwen: mesmo transporte, catálogo
# (qwen-agent-settings.json) e OPENROUTER_API_KEY do agente qwen. Não existe
# CLI nem chave própria do Grok nesta VPS.
export QWEN_PROVIDER=openrouter
export QWEN_MODEL="${GROK_MODEL:-x-ai/grok-4.7}"
# A CLI qwen injeta "You are Qwen Code" no prompt de sistema; esta instrução
# só acrescenta a identidade real, sem trocar as instruções das ferramentas.
IDENTITY="Identidade: você é o Grok (xAI), modelo $QWEN_MODEL, acessado pela OpenRouter. Você roda dentro da CLI Qwen Code, que só fornece as ferramentas. Quando perguntarem quem você é ou qual modelo usa, responda que é o Grok (modelo $QWEN_MODEL), não o Qwen Code."
exec "$(dirname "$(realpath "$0")")/start_qwen_agent.sh" --append-system-prompt "$IDENTITY" "$@"
