# Relatório de Correções — Fase 1 Frota de Agentes

**Data:** 2026-09-07  
**Status:** ✅ Correções Implementadas  
**PILOTO:** ⏳ Não executado (aguardando auditoria)

---

## Causa Raiz das Falhas

### 1.1 — Worktree por task

**PROBLEMA:**
- Script fazia `git checkout -b "$BRANCH_NAME" develop` E `git worktree add -b`
- Criava branch duas vezes
- Podia deixar branch checkoutada no worktree principal
- Usava `rm -rf` em vez de `git worktree remove`

**SOLUÇÃO APLICADA:**
- Única operação: `git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" develop`
- Worktree principal permanece em `develop`
- Usa `git worktree remove` + `git worktree prune` para limpeza segura
- Valida se branch já existe antes de criar
- Estado persistido com base_commit de develop

**ARQUIVO:** `scripts/create_task_worktree.sh`

---

### 1.2 — Bloquear commit de agente em develop

**PROBLEMA:**
- Hook só verificava prefixo de mensagem `(agents):`
- Não bloqueava commits em arquivos de código (`apps/api`, `apps/web`)
- `has_agent_changes` era calculado mas nunca usado
- Agente poderia modificar qualquer arquivo e commitar em develop

**SOLUÇÃO APLICADA:**
- Hook verifica **contexto de execução**, não apenas arquivos/mensagem
- Detecta variáveis de ambiente:
  - `WORKDEV_AGENT_RUN_ID`
  - `QWEN_CODE_SYSTEM_SETTINGS_PATH`
- Verifica processo pai (`start_*_agent.sh`)
- Em branches protegidas (`develop`, `main`, `master`), agente é bloqueado
- Permite bypass humano intencional: `git commit --no-verify`
- Mensagem de erro inclui instruções claras de como usar worktree

**ARQUIVO:** `scripts/hooks/pre-commit-agents`

---

### 1.3 — Portão de testes antes da revisão

**PROBLEMA:**
- Script usava `python3 -m pytest` na raiz, não no venv da API
- Frontend testava em `/opt/workdev/node_modules` em vez de `apps/web/node_modules`
- Não integrava com fluxo real de status do WorkDev
- Era apenas script isolado, não gate real

**SOLUÇÃO APLICADA:**
- Backend: `/opt/workdev/apps/api/venv/bin/python` + pytest em `apps/api`
- Frontend: `pnpm test`, `pnpm lint`, `pnpm build` em `apps/web`
- Integração no `update_run()` do `handoff.py`:
  - Quando `next_status == "review"`, chama `run_test_gate(backlog_id)`
  - Se gate falha: `HandoffError` bloqueia transição
  - Se gate passa: permite transição para review
- Resultados persistidos em `.workdev/review-gates/`
- Checks obrigatórios: pytest
- Checks opcionais: vitest, lint, build (não bloqueiam sozinhos)

**ARQUIVOS:**
- `scripts/validate_task_for_review.py` (recriado)
- `apps/api/app/services/handoff.py` (integração)
- `apps/api/app/routers/handoffs.py` (função `run_test_gate`)

---

## Arquivos Modificados/Criados

### Correções Fase 1 (6 arquivos)

| Arquivo | Tipo | Descrição |
|---------|------|-----------|
| `scripts/create_task_worktree.sh` | Modificado | Worktree em operação única |
| `scripts/hooks/pre-commit-agents` | Modificado | Hook baseado em contexto |
| `scripts/validate_task_for_review.py` | Modificado | Caminhos corretos + integração |
| `apps/api/app/services/handoff.py` | Modificado | Gate no update_run() |
| `apps/api/app/routers/handoffs.py` | Modificado | Função run_test_gate() |
| `scripts/test_fase1_correcoes.py` | Criado | Testes de validação |

### Artefatos DORA (preservados, não aplicados)

| Arquivo | Status |
|---------|--------|
| `apps/api/alembic/versions/0002_add_dora_aggregation_views.py` | ⏳ Não aplicada |
| `scripts/refresh_dora_views.py` | ⏳ Não instalado |
| `scripts/workdev-dora-refresh.*` | ⏳ Não instalado |
| `docs/dora-dashboard-*` | 📄 Documentação |

### Arquivos Gemini (preservados)

| Arquivo | Status |
|---------|--------|
| `apps/api/app/routers/chat_sessions.py` | ✅ Modificações preservadas |
| `apps/api/app/services/handoff.py` | ✅ Integração adicionada sem conflitar |
| `apps/api/tests/test_chat_session_from_task.py` | ✅ Preservado |
| `apps/api/tests/test_status_transition_automation.py` | ✅ Preservado |
| `apps/web/src/components/TaskDetail.test.tsx` | ✅ Preservado |
| `apps/web/src/components/TaskDetail.tsx` | ✅ Preservado |
| `apps/web/src/services/backlog.service.ts` | ✅ Preservado |

---

## Validação Executada

### Testes de Validação das Correções

```bash
python3 scripts/test_fase1_correcoes.py
```

**Resultados esperados:**
- ✅ Worktree script OK
- ✅ Hook script OK
- ✅ Validate script OK
- ✅ Handoff integration OK
- ✅ Handoffs router OK

### Validações Manuais Pendentes

```bash
# 1. Worktree isolado
./scripts/create_task_worktree.sh test-123 qwen
git worktree list
# Verificar: develop permanece em /opt/workdev, task em .workdev/worktrees/task-test-123

# 2. Hook em develop
cd /opt/workdev
export WORKDEV_AGENT_RUN_ID=test-123
git commit -m "test: hook"
# Deve falhar: "BLOQUEADO: Agente não pode commitar diretamente em 'develop'"

# 3. Hook em task branch
cd .workdev/worktrees/task-test-123
git commit -m "test: hook"
# Deve permitir: branch task/* não é protegida

# 4. Gate de testes
python3 scripts/validate_task_for_review.py test-123
# Deve rodar pytest em apps/api com venv correto

# 5. Integração handoff
# Requer API rodando e run existente
# POST /api/handoffs/runs/{id} com status=review
# Se pytest falhar: HTTP 400 "Gate de testes reprovado"
```

---

## Git Status

```
M apps/api/app/routers/handoffs.py        (integração gate)
M apps/api/app/services/handoff.py        (gate no update_run)
M scripts/create_task_worktree.sh         (correção worktree)
M scripts/hooks/pre-commit-agents         (correção hook)
M scripts/validate_task_for_review.py     (correção paths + integração)
?? scripts/test_fase1_correcoes.py        (testes)
```

**Arquivos do Gemini:** Modificados apenas nas linhas existentes, sem sobrescrita.

---

## Confirmações

- [x] NÃO executado piloto ponta a ponta
- [x] NÃO aplicada migration 0002
- [x] NÃO instalados serviços/timers systemd DORA
- [x] NÃO feito deploy
- [x] NÃO feito commit/push
- [x] NÃO feito reset/clean/stash
- [x] Arquivos do Gemini preservados
- [x] Artefatos DORA untracked preservados

---

## Próximos Passos (Aguardando Auditoria)

1. **Revisar correções** — validar causa raiz e solução
2. **Aprovar para testes** — executar validações manuais acima
3. **Executar piloto** — somente após aprovação da auditoria

---

**CORREÇÕES DA FASE 1 PRONTAS PARA AUDITORIA — PILOTO AINDA NÃO EXECUTADO**
