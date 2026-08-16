#!/usr/bin/env bash
set -euo pipefail

WORKDEV_DIR="${WORKDEV_DIR:-/opt/workdev}"

declare -A AGENT_COMMANDS=(
  [code]="$WORKDEV_DIR/scripts/start_claude_agent.sh"
  [codex]="$WORKDEV_DIR/scripts/start_codex_agent.sh"
)

for session in code codex; do
  if tmux has-session -t "$session" 2>/dev/null; then
    continue
  fi
  tmux new-session -d -s "$session" -c "$WORKDEV_DIR" "${AGENT_COMMANDS[$session]}"
done

"$WORKDEV_DIR/scripts/agents_healthcheck.py" --once --no-restart
