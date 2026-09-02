#!/usr/bin/env bash
set -euo pipefail

export DISABLE_AUTOUPDATER=1
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

cd /opt/workdev
exec /usr/bin/claude "$@"
