#!/usr/bin/env bash
set -euo pipefail

# DeepSeek pela OpenRouter, executado pela CLI qwen: mesmo transporte, catálogo
# (qwen-agent-settings.json) e OPENROUTER_API_KEY do agente qwen. Não existe
# CLI nem chave própria do DeepSeek nesta VPS.
export QWEN_PROVIDER=openrouter
export QWEN_MODEL="${DEEPSEEK_MODEL:-deepseek/deepseek-v4-flash}"
# A CLI qwen injeta "You are Qwen Code" no prompt de sistema; esta instrução
# só acrescenta a identidade real, sem trocar as instruções das ferramentas.
IDENTITY="Identidade: você é o DeepSeek (DeepSeek), modelo $QWEN_MODEL, acessado pela OpenRouter. Você roda dentro da CLI Qwen Code, que só fornece as ferramentas. Quando perguntarem quem você é ou qual modelo usa, responda que é o DeepSeek (modelo $QWEN_MODEL), não o Qwen Code."
exec "$(dirname "$(realpath "$0")")/start_qwen_agent.sh" --append-system-prompt "$IDENTITY" "$@"
