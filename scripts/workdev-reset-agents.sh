#!/usr/bin/env bash
set -euo pipefail

WORKDEV_DIR="${WORKDEV_DIR:-/opt/workdev}"
ACTION="${1:-}"
if [[ "${ACTION}" != "preview" && "${ACTION}" != "execute" ]]; then
  echo "uso: $0 preview | execute --confirmation-token TOKEN" >&2
  exit 2
fi

# Dentro da API/worker, o banco e os segredos já chegam pelo ambiente e o
# engine pode ser chamado diretamente. No terminal do operador, o usuário
# workdev não lê o EnvironmentFile protegido: nesse caso usamos a mesma API
# autenticada, que também é dona do socket tmux correto.
if [[ -n "${DATABASE_URL:-}" ]]; then
  export PYTHONPATH="${WORKDEV_DIR}/apps/api${PYTHONPATH:+:${PYTHONPATH}}"
  exec "${WORKDEV_DIR}/apps/api/venv/bin/python" -m app.services.agent_reset "$@"
fi

API_BASE="${WORKDEV_LOCAL_API:-http://127.0.0.1:8000/api}"
API_KEY="${WORKDEV_API_KEY:-}"
if [[ -z "${API_KEY}" ]]; then
  if [[ ! -t 0 ]]; then
    echo "WORKDEV_API_KEY ausente; execute em terminal interativo para informá-la sem eco" >&2
    exit 2
  fi
  read -r -s -p "WORKDEV_API_KEY: " API_KEY
  echo >&2
fi

if [[ "${ACTION}" == "preview" ]]; then
  printf 'header = "X-API-Key: %s"\n' "${API_KEY}" |
    curl --config - --silent --show-error --fail-with-body "${API_BASE}/agents/reset/preview"
  echo
  exit 0
fi

if [[ "${2:-}" != "--confirmation-token" || -z "${3:-}" ]]; then
  echo "execute exige --confirmation-token retornado pelo preview" >&2
  exit 2
fi
TOKEN="${3}"
printf 'header = "X-API-Key: %s"\n' "${API_KEY}" |
  curl --config - --silent --show-error --fail-with-body -X POST \
    -H 'Content-Type: application/json' \
    --data "{\"confirmation_token\":\"${TOKEN}\"}" \
    "${API_BASE}/agents/reset"
echo
