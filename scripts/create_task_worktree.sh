#!/usr/bin/env bash
# Criar worktree isolado para execução de task por agente.
#
# Uso: ./scripts/create_task_worktree.sh <task-id> [agent]
# Exemplo: ./scripts/create_task_worktree.sh 339e074d-faa3-4062-a2a2-e114fd627454 qwen

set -euo pipefail

WORKDIR="/opt/workdev"
WORKTREES_DIR="$WORKDIR/.workdev/worktrees"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date -u '+%Y-%m-%d %H:%M:%S UTC')]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

if [[ $# -lt 1 ]]; then
    echo "Uso: $0 <task-id> [agent]"
    echo "  task-id: ID da task no backlog (UUID)"
    echo "  agent: Agente executor (opcional, default: agent)"
    exit 1
fi

TASK_ID="$1"

# TASK_ID entra tanto no caminho do worktree quanto no nome da branch.
# Aceitar somente UUID canônico evita path traversal e nomes Git inesperados.
if [[ ! "$TASK_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
    error "task-id inválido: esperado UUID canônico"
    exit 2
fi

AGENT="${2:-agent}"
WORKTREE_PATH="$WORKTREES_DIR/task-${TASK_ID}"
BRANCH_NAME="task/${TASK_ID}"

log "Criando worktree para task $TASK_ID (agente: $AGENT)"

# 1. Verificar worktree existente
if [[ -d "$WORKTREE_PATH" ]]; then
    warn "Worktree já existe em $WORKTREE_PATH"
    echo ""
    echo "Opções:"
    echo "  1. Reutilizar worktree existente (padrão)"
    echo "  2. Remover e recriar (requer confirmação)"
    echo ""
    read -p "Deseja remover e recriar? [y/N] " -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log "Removendo worktree existente..."
        if git worktree remove "$WORKTREE_PATH" 2>/dev/null; then
            log "Worktree removido com sucesso"
        else
            git worktree prune
            if ! git worktree remove "$WORKTREE_PATH" 2>/dev/null; then
                error "Falha ao remover worktree. Execute: git worktree remove --force $WORKTREE_PATH"
                exit 1
            fi
        fi
    else
        log "Reutilizando worktree existente"
        git worktree list | grep "task-${TASK_ID}" || true
        exit 0
    fi
fi

mkdir -p "$WORKTREES_DIR"

# 2. Verificar branch existente
if git rev-parse --verify "$BRANCH_NAME" >/dev/null 2>&1; then
    warn "Branch $BRANCH_NAME já existe"
    error "Por segurança, o script não removerá uma branch existente automaticamente."
    error "Revise a branch/worktree existente ou remova-a manualmente antes de recriar."
    exit 1
fi

# 3. Criar worktree + branch em operação única a partir de develop
# Worktree principal NÃO faz checkout da branch da task
log "Criando worktree com branch $BRANCH_NAME a partir de develop..."
if ! git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" develop; then
    error "Falha ao criar worktree"
    exit 1
fi

# 4. Configurar permissões
chmod -R u+rwX "$WORKTREE_PATH"

# 5. Criar arquivo de estado
cat > "$WORKTREE_PATH/.task-state.json" << EOF
{
    "task_id": "$TASK_ID",
    "agent": "$AGENT",
    "branch": "$BRANCH_NAME",
    "worktree_path": "$WORKTREE_PATH",
    "created_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
    "status": "ready",
    "base_branch": "develop",
    "base_commit": "$(git rev-parse develop)"
}
EOF

# 6. Verificar estado final
MAIN_BRANCH=$(git rev-parse --abbrev-ref HEAD)
WORKTREE_BRANCH=$(git -C "$WORKTREE_PATH" rev-parse --abbrev-ref HEAD)

log "✅ Worktree criado com sucesso"
echo ""
echo "=== Estado Final ==="
echo "Worktree principal ($WORKDIR):"
echo "  Branch: $MAIN_BRANCH"
echo "  Commit: $(git rev-parse --short HEAD)"
echo ""
echo "Worktree da task ($WORKTREE_PATH):"
echo "  Branch: $WORKTREE_BRANCH"
echo "  Commit: $(git -C "$WORKTREE_PATH" rev-parse --short HEAD)"
echo "  Base: develop @ $(git rev-parse --short develop)"
echo ""
echo "=== Próximos Passos ==="
echo "1. Agente trabalha isolado em: cd $WORKTREE_PATH"
echo "2. Ao finalizar: git add -A && git commit -m 'feat: task $TASK_ID'"
echo "3. Após revisão: git worktree remove $WORKTREE_PATH && git merge $BRANCH_NAME"
echo ""
echo "Estado: $WORKTREE_PATH/.task-state.json"
