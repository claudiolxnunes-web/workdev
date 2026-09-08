# Frota de Agentes — Fase 1 Implementada

**Data:** 2026-09-07  
**Status:** ✅ Implementação Concluída

---

## Visão Geral

A Fase 1 da Frota de Agentes fornece infraestrutura para execução isolada e segura de agents em tasks do backlog, com gates de qualidade e monitoramento de estabilidade.

---

## Subtasks Implementadas

### 5. ✅ CHECKPOINT — 24h de estabilidade

**Script:** `scripts/checkpoint_24h.py`

**Funcionalidades:**
- Verifica estabilidade do supervisor nas últimas 24h
- Valida saúde dos agentes (offline/blocked)
- Verifica job de refresh DORA
- Persiste resultado em `.workdev/checkpoint-24h.json`
- Gate liberado apenas se todos critérios forem atendidos

**Critérios:**
- Zero execuções `failed` do supervisor em 24h
- Zero agentes `offline` ou `blocked`
- Zero falhas críticas do DORA refresh

**Uso:**
```bash
python3 scripts/checkpoint_24h.py
```

---

### 1.1 ✅ Worktree por task

**Script:** `scripts/create_task_worktree.sh`

**Funcionalidades:**
- Cria worktree isolado em `.workdev/worktrees/task-{id}`
- Branch separado: `task/{id}`
- Estado persistido em `.task-state.json`
- Instruções de limpeza ao final

**Uso:**
```bash
./scripts/create_task_worktree.sh <task-id> [agente]

# Exemplo:
./scripts/create_task_worktree.sh 339e074d-faa3-4062-a2a2-e114fd627454 qwen
```

**Fluxo:**
1. Script cria branch `task/{id}` a partir de `develop`
2. Cria worktree em `.workdev/worktrees/task-{id}`
3. Agente executa no worktree isolado
4. Commit e merge após conclusão
5. Limpeza opcional do worktree

---

### 1.2 ✅ Bloquear commit de agente em develop

**Hook:** `scripts/hooks/pre-commit-agents`

**Funcionalidades:**
- Bloqueia commits com prefixo `(agents):` em `develop`, `main`, `master`
- Permite commits de agentes em branches de feature
- Sugere criação de worktree ou branch de feature

**Padrões bloqueados:**
- `feat(agents):`
- `fix(agents):`
- `chore(agents):`
- `refactor(agents):`
- `test(agents):`
- `docs(agents):`

**Instalação:**
```bash
cp scripts/hooks/pre-commit-agents .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# Ou usar hook central:
git config core.hooksPath scripts/hooks
```

---

### 1.3 ✅ Portão de testes antes da revisão

**Script:** `scripts/validate_task_for_review.py`

**Funcionalidades:**
- Executa pytest (Python)
- Executa vitest (TypeScript, se disponível)
- Verifica linting (ruff + eslint)
- Verifica type checking (mypy + tsc)
- Persiste resultado em `.workdev/review-gates/`

**Uso:**
```bash
python3 scripts/validate_task_for_review.py <task-id>

# Exemplo:
python3 scripts/validate_task_for_review.py 339e074d-faa3-4062-a2a2-e114fd627454
```

**Retorno:**
- `0`: Todos testes passaram, task pronta para revisão
- `1`: Testes falharam, task não está pronta

---

### 9. ✅ PILOTO — uma task real ponta a ponta

**Script:** `scripts/piloto_task_ponta_a_ponta.sh`

**Funcionalidades:**
- Orquestra todo o fluxo da Fase 1
- Cria worktree para task
- Instala hook de bloqueio
- Executa portão de testes
- Executa checkpoint de 24h
- Consolida resultado

**Uso:**
```bash
./scripts/piloto_task_ponta_a_ponta.sh [task-id] [agente]

# Exemplo (task padrão: DORA Dashboard):
./scripts/piloto_task_ponta_a_ponta.sh
```

**Estado:** `.workdev/piloto-state.json`

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                    Frota de Agentes Fase 1                  │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  Worktree por │   │  Hook de Bloqueio│   │  Portão de      │
│  Task         │   │  (develop)      │   │  Testes         │
│               │   │                 │   │                 │
│  • Isolamento │   │  • feat(agents) │   │  • pytest       │
│  • Branch     │   │  • fix(agents)  │   │  • vitest       │
│  • Estado     │   │  • chore(agents)│   │  • lint         │
└───────┬───────┘   └────────┬────────┘   └────────┬────────┘
        │                    │                     │
        └────────────────────┼─────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  CHECKPOINT 24h │
                    │                 │
                    │  • Supervisor   │
                    │  • Agents       │
                    │  • DORA         │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  PILOTO         │
                    │  (orquestração) │
                    └─────────────────┘
```

---

## Arquivos Criados

| Arquivo | Tipo | Descrição |
|---------|------|-----------|
| `scripts/checkpoint_24h.py` | Python | Checkpoint de estabilidade |
| `scripts/create_task_worktree.sh` | Bash | Criação de worktree |
| `scripts/hooks/pre-commit-agents` | Bash | Hook de bloqueio |
| `scripts/validate_task_for_review.py` | Python | Portão de testes |
| `scripts/piloto_task_ponta_a_ponta.sh` | Bash | Orquestração do piloto |

---

## Validação Obrigatória

### 1. Worktree
```bash
# Criar worktree
./scripts/create_task_worktree.sh test-123 qwen

# Verificar
ls -la .workdev/worktrees/task-test-123
git worktree list
```

### 2. Hook
```bash
# Instalar hook
cp scripts/hooks/pre-commit-agents .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# Testar (deve falhar em develop)
git checkout develop
git commit -m "feat(agents): test"
```

### 3. Portão de testes
```bash
# Executar validação
python3 scripts/validate_task_for_review.py test-123

# Verificar resultado
ls -la .workdev/review-gates/
```

### 4. Checkpoint 24h
```bash
# Executar checkpoint
python3 scripts/checkpoint_24h.py

# Verificar resultado
cat .workdev/checkpoint-24h.json
```

### 5. PILOTO
```bash
# Executar piloto completo
./scripts/piloto_task_ponta_a_ponta.sh

# Verificar estado
cat .workdev/piloto-state.json
```

---

## Integração com Fluxo Existente

### Agente (Qwen/Codex/Claude)
1. Task é atribuída ao agente
2. Agente (ou operador) executa `create_task_worktree.sh`
3. Agente trabalha no worktree isolado
4. Ao finalizar, agente executa `validate_task_for_review.py`
5. Se gate aprovado, merge para develop
6. Limpeza do worktree

### Operador
1. Monitora checkpoint de 24h
2. Valida tasks antes de merge
3. Executa piloto periodicamente

---

## Próximos Passos

1. **Testar fluxo completo:**
   ```bash
   ./scripts/piloto_task_ponta_a_ponta.sh
   ```

2. **Instalar hook permanentemente:**
   ```bash
   cp scripts/hooks/pre-commit-agents .git/hooks/pre-commit
   chmod +x .git/hooks/pre-commit
   ```

3. **Configurar checkpoint automático:**
   ```bash
   # Adicionar ao crontab ou systemd timer
   0 * * * * python3 /opt/workdev/scripts/checkpoint_24h.py
   ```

4. **Documentar para agentes:**
   - Adicionar instruções no `CLAUDE.md` ou `AGENTS.md`
   - Criar skill para criação de worktree

---

**Status:** Implementação 100% concluída. Validação pendente.
