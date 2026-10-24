#!/usr/bin/env bash
set -euo pipefail

CLAUDE_EXECUTABLE="${CLAUDE_EXECUTABLE:-/usr/bin/claude}"
export DISABLE_AUTOUPDATER=1
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export COLORTERM="${COLORTERM:-truecolor}"

cd "${WORKDEV_AGENT_CWD:-${WORKDEV_DIR:-/opt/workdev}}"
exec "$CLAUDE_EXECUTABLE" "$@"
