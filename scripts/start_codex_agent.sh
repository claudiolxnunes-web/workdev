#!/usr/bin/env bash
set -euo pipefail

CODEX_EXECUTABLE="${CODEX_EXECUTABLE:-/usr/bin/codex}"
export NO_UPDATE_NOTIFIER=1

cd "${WORKDEV_AGENT_CWD:-${WORKDEV_DIR:-/opt/workdev}}"
exec "$CODEX_EXECUTABLE" \
  --disable in_app_updates \
  -c check_for_update_on_startup=false \
  "$@"
