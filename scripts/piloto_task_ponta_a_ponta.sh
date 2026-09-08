#!/usr/bin/env bash
# Executar task piloto ponta a ponta — validação da Frota de Agentes Fase 1.
#
# Este script orquestra todo o fluxo:
# 1. Criar worktree para task
# 2. Executar validações pré-task
# 3. Simular execução do agente
# 4. Executar portão de testes
# 5. Validar checkpoint de 24h
# 6. Consolidar resultado

set -euo pipefail

WORKDIR="/opt/workdev"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date -u '+%Y-%m-%d %H:%M:%S UTC')]${NC} $*"
}

step() {
    echo -e "${YELLOW}>>> $*${NC}"
}

error() {
    echo -e "${RED}❌ $*${NC}" >&2
}

success() {
    echo -e "${GREEN}✅ $*${NC}"
}

# Task piloto (usar task real do backlog)
TASK_ID="${1:-339e074d-faa3-4062-a2a2-e114fd627454}"
AGENT="${2:-qwen}"

log "=== PILOTO: Task ponta a ponta ==="
log "Task ID: $TASK_ID"
log "Agente: $AGENT"
echo ""

# Estado do piloto
STATE_FILE="$WORKDIR/.workdev/piloto-state.json"
RESULTS=()

# 1. Validar pré-requisitos
step "1. Validar pré-requisitos"
if ! command -v git &> /dev/null; then
    error "git não encontrado"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    error "python3 não encontrado"
    exit 1
fi

success "Pré-requisitos OK"
echo ""

# 2. Criar worktree
step "2. Criar worktree para task"
if [[ -d "$WORKDIR/.workdev/worktrees/task-$TASK_ID" ]]; then
    log "Worktree já existe, pulando criação"
else
    log "Criando worktree..."
    bash "$WORKDIR/scripts/create_task_worktree.sh" "$TASK_ID" "$AGENT" || {
        error "Falha ao criar worktree"
        exit 1
    }
fi
success "Worktree criado"
echo ""

# 3. Instalar hook de bloqueio
step "3. Instalar hook de bloqueio de agentes"
HOOKS_DIR="$WORKDIR/.git/hooks"
mkdir -p "$HOOKS_DIR"
cp "$WORKDIR/scripts/hooks/pre-commit-agents" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"
success "Hook instalado em $HOOKS_DIR/pre-commit"
echo ""

# 4. Executar portão de testes (simulado)
step "4. Executar portão de testes"
if python3 "$WORKDIR/scripts/validate_task_for_review.py" "$TASK_ID"; then
    success "Portão de testes aprovado"
    RESULTS+=("gate:pass")
else
    error "Portão de testes reprovado"
    RESULTS+=("gate:fail")
fi
echo ""

# 5. Executar checkpoint de 24h
step "5. Executar checkpoint de 24h"
if python3 "$WORKDIR/scripts/checkpoint_24h.py"; then
    success "Checkpoint de 24h aprovado"
    RESULTS+=("checkpoint:pass")
else
    warn "Checkpoint de 24h reprovado (pode ser esperado)"
    RESULTS+=("checkpoint:fail")
fi
echo ""

# 6. Consolidar resultado
step "6. Consolidar resultado"
TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

cat > "$STATE_FILE" << EOF
{
    "task_id": "$TASK_ID",
    "agent": "$AGENT",
    "timestamp": "$TIMESTAMP",
    "results": {
        $(IFS=,; echo "${RESULTS[*]}" | sed 's/:/": "/g' | sed 's/,/", "/g')
    },
    "status": "completed"
}
EOF

success "Resultado persistido em $STATE_FILE"
echo ""

# Resumo final
echo "========================================"
echo "         PILOTO CONCLUÍDO"
echo "========================================"
echo "Task: $TASK_ID"
echo "Agente: $AGENT"
echo "Data: $TIMESTAMP"
echo ""
echo "Resultados:"
for result in "${RESULTS[@]}"; do
    echo "  - $result"
done
echo ""
echo "Estado: $STATE_FILE"
echo ""

# Verificar se tudo passou
if [[ "${RESULTS[*]}" == *"fail"* ]]; then
    error "PILOTO: Algumas validações falharam"
    exit 1
else
    success "PILOTO: Todas validações passaram"
    exit 0
fi
