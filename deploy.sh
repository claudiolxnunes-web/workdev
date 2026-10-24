#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "BLOQUEIA: uso: bash /opt/workdev/deploy.sh <proof_id>" >&2
    exit 1
fi

if [[ ${EUID} -ne 0 ]]; then
    echo "BLOQUEIA: deploy exige o approval gate administrativo" >&2
    exit 1
fi

CONTROLADOR=/usr/local/sbin/workdev-deployctl
if [[ ! -x "$CONTROLADOR" ]] || [[ $(stat -c '%U:%G:%a' "$CONTROLADOR") != "root:root:755" ]]; then
    echo "BLOQUEIA: controlador confiavel ausente ou com ownership invalido" >&2
    exit 1
fi

exec "$CONTROLADOR" deploy "$1"
