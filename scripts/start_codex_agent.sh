#!/usr/bin/env bash
set -euo pipefail

export NO_UPDATE_NOTIFIER=1

cd /opt/workdev
exec /usr/bin/codex \
  --disable in_app_updates \
  -c check_for_update_on_startup=false \
  "$@"
