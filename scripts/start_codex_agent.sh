#!/usr/bin/env bash
set -euo pipefail

cd /opt/workdev
exec /usr/bin/codex "$@"
