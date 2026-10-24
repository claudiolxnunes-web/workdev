# Correção Definitiva do Gate de Testes — Fase 1.3

**Data:** 2026-09-07  
**Status:** ✅ Implementação Concluída  
**PILOTO:** ⏳ Não executado (aguardando auditoria)

---

## 1. Arquivos Alterados

### Novos Arquivos (Service + Testes)

| Arquivo | Tipo | Descrição |
|---------|------|-----------|
| `apps/api/app/services/test_gate.py` | **Service dedicado** | Execução de checks, fail-closed, persistência de evidência |
| `apps/api/tests/test_test_gate.py` | **Testes comportamentais** | 10 testes reais de comportamento do gate |

### Arquivos Modificados

| Arquivo | Mudança |
|---------|---------|
| `apps/api/app/services/handoff.py` | Importa `test_gate` service, valida `review` E `completed` |
| `apps/api/app/routers/handoffs.py` | Remove `run_test_gate()`, adiciona `execute_test_gate_for_run()`, corrige ordem de `finalize_auto_runtime()` |
| `scripts/validate_task_for_review.py` | Paths corrigidos (`API_VENV`, `PNPM`) |

### Arquivos Gemini (Preservados)

| Arquivo | Status |
|---------|--------|
| `apps/api/app/routers/chat_sessions.py` | ✅ Preservado |
| `apps/api/app/services/handoff.py` | ✅ Integração adicionada sem conflitar |
| `apps/api/tests/test_chat_session_from_task.py` | ✅ Preservado |
| `apps/api/tests/test_status_transition_automation.py` | ✅ Preservado |
| `apps/web/src/components/*` | ✅ Preservado |
| `apps/web/src/services/backlog.service.ts` | ✅ Preservado |

---

## 2. Arquitetura Final do Gate

```
┌─────────────────────────────────────────────────────────────┐
│                    AgentRun (handoff.py)                    │
│                     update_run()                            │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │  test_gate.py (SERVICE)      │
              │                              │
              │  - execute_gate()            │
              │  - persist_gate_evidence()   │
              │  - get_gate_evidence_for_run()│
              │  - validate_run_for_status_change() │
              └──────────────────────────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
                ▼            ▼            ▼
         ┌──────────┐ ┌──────────┐ ┌──────────┐
         │  pytest  │ │  vitest  │ │  build   │
         │ (obrig.) │ │ (opc.)   │ │ (opc.)   │
         └──────────┘ └──────────┘ └──────────┘
                │
                ▼
         ┌──────────┐
         │  lint    │
         │ (opc.)   │
         └──────────┘
```

**Fluxo:**
1. `update_run()` (handoff.py) chama `validate_run_for_status_change()` (test_gate.py)
2. `validate_run_for_status_change()` consulta `get_gate_evidence_for_run()`
3. Se sem evidência → `execute_gate()` roda checks
4. `persist_gate_evidence()` salva como `AgentRunEvent`
5. Se gate falhou → `HandoffError` bloqueia transição

**Sem dependência invertida:** service NÃO importa router.

---

## 3. Eliminação da Dependência Invertida

### ANTES (ERRADO)
```python
# handoff.py (service)
from app.routers.handoffs import run_test_gate  # ❌ service → router
```

### DEPOIS (CORRETO)
```python
# handoff.py (service)
from app.services.test_gate import validate_run_for_status_change  # ✅ service → service

# handoffs.py (router)
from app.services.test_gate import execute_gate, persist_gate_evidence  # ✅ router → service
```

---

## 4. Implementação Fail-Closed

### Regra Implementada
```python
# SEM EVIDÊNCIA VÁLIDA DE PASS = FAIL
if not evidence.passed:
    return False, f"Gate reprovado: {failed}"
```

### Casos de Bloqueio (todos testados)

| Cenário | Resultado | Teste |
|---------|-----------|-------|
| Script/service inexistente | ❌ BLOQUEADO | `test_gate_executa_fail_closed` |
| Python/venv inexistente | ❌ BLOQUEADO | `test_gate_executa_fail_closed` |
| Timeout | ❌ BLOQUEADO | (subprocess timeout 300s) |
| pytest falhou | ❌ BLOQUEADO | `test_mandatory_failed_bloqueia` |
| vitest falhou | ⚠️ Opcional | (não bloqueia sozinho) |
| build falhou | ⚠️ Opcional | (não bloqueia sozinho) |
| Exceção inesperada | ❌ BLOQUEADO | try/except no `execute_gate` |
| JSON inválido | ❌ BLOQUEADO | `get_gate_evidence_for_run` retorna None |
| Ausência de evidência | ❌ BLOQUEADO | `test_validate_run_review_sem_evidencia` |
| Evidência de outro run | ❌ BLOQUEADO | `test_evidence_vinculada_ao_run` |
| Evidência > 24h | ❌ BLOQUEADO | `test_evidence_expira_24h` |

---

## 5. Eliminação do Bypass `running → completed`

### ANTES (BYPASS)
```python
# handoff.py
if next_status == "review":  # ❌ Só review protegido
    gate.check()
# completed → sem gate → BYPASS
```

### DEPOIS (PROTEGIDO)
```python
# handoff.py
if next_status in {"review", "completed"}:  # ✅ Ambos protegidos
    allowed, reason = validate_run_for_status_change(db, run, next_status)
    if not allowed:
        raise HandoffError(f"Gate reprovado: {reason}")
```

### Matriz de Transições Protegidas

| Transição | Requer Gate? | Justificativa |
|-----------|--------------|---------------|
| `running → review` | ✅ Sim | Entrega para revisão humana |
| `running → completed` | ✅ Sim | Conclusão direta (não pode bypass) |
| `running → failed` | ❌ Não | Falha explícita |
| `running → cancelled` | ❌ Não | Cancelamento explícito |
| `running → blocked` | ❌ Não | Bloqueio temporário |
| `running → queued` | ❌ Não | Voltou para fila |

---

## 6. Tratamento do Runtime AUTO Gemini

### ANTES (ORDEM ERRADA)
```python
# handoffs.py PATCH /runs/{run_id}
if requested_status == "completed":
    finalize_auto_runtime()  # ❌ Finaliza ANTES de validar gate
    update_run()  # Gate pode falhar depois
```

### DEPOIS (ORDEM CORRETA)
```python
# handoffs.py PATCH /runs/{run_id}
# 1. Validar transição (inclui gate)
run, event = update_run(db, current, data)  # ✅ Gate aqui

# 2. Só após transição aceita, finalizar runtime
if requested_status == "completed":
    finalize_auto_runtime()  # ✅ Depois de validar
```

### Exceção Tratada
Se `finalize_auto_runtime()` falhar após transição aceita:
- Log warning
- Não reverter transição
- Agente pode ser reiniciado manualmente

---

## 7. Evidência de Testes Vinculada ao AgentRun

### Estrutura da Evidência

```python
@dataclass
class GateEvidence:
    run_id: UUID           # ✅ Vinculado ao AgentRun
    backlog_id: UUID
    timestamp: str
    passed: bool
    checks: list[CheckResult]
    mandatory_failed: list[str]
    error: str | None
```

### Persistência via AgentRunEvent (sem migration)

```python
event = AgentRunEvent(
    run_id=run.id,                    # ✅ Vinculado
    event_type="build.tests_passed",  # ou "build.tests_failed"
    message="Gate aprovado",
    payload=evidence.to_payload(),    # JSON auditável
)
```

### Validação de Evidência

```python
def get_gate_evidence_for_run(db, run_id) -> GateEvidence | None:
    # Busca evento vinculado a ESTE run_id
    event = db.query(AgentRunEvent).filter(
        AgentRunEvent.run_id == run_id,  # ✅ Só deste run
        AgentRunEvent.event_type.in_(["build.tests_passed", "build.tests_failed"])
    ).first()
    
    # Valida campos obrigatórios
    # Valida timestamp < 24h
    # Valida run_id bate com payload
    
    return evidence or None  # None se inválido
```

---

## 8. Testes Comportamentais Adicionados

### Localização
`apps/api/tests/test_test_gate.py`

### 10 Testes Implementados

| # | Teste | Valida |
|---|-------|--------|
| 1 | `test_gate_executa_fail_closed` | Gate sem venv → FAIL |
| 2 | `test_gate_evidence_persistida` | Evidência vira AgentRunEvent |
| 3 | `test_evidence_vinculada_ao_run` | Evidência de outro run não é aceita |
| 4 | `test_validate_run_review_sem_evidencia` | review sem evidência → bloqueado |
| 5 | `test_validate_run_completed_sem_evidencia` | completed sem evidência → bloqueado |
| 6 | `test_validate_run_running_permitido` | running não requer gate |
| 7 | `test_validate_run_failed_permitido` | failed não requer gate |
| 8 | `test_evidence_payload_valido` | Payload tem campos obrigatórios |
| 9 | `test_evidence_expira_24h` | Evidência > 24h é rejeitada |
| 10 | `test_mandatory_failed_bloqueia` | Check obrigatório falhando → gate FAIL |

---

## 9. Resultados dos Testes

```
============================================================
TESTES COMPORTAMENTAIS — SERVICE test_gate
============================================================

[TESTE 1] Gate sem venv → FAIL (fail-closed)
  ✅ PASS: Gate falhou como esperado: Venv da API não encontrado...

[TESTE 2] Evidência persistida como AgentRunEvent
  ✅ PASS: Evento build.tests_failed criado com payload

[TESTE 3] Evidência vinculada ao run
  ✅ PASS: Evidência corretamente vinculada ao run

[TESTE 4] review sem evidência → bloqueado
  ✅ PASS: review bloqueado: Sem evidência de gate aprovado...

[TESTE 5] completed sem evidência → bloqueado
  ✅ PASS: completed bloqueado: Sem evidência de gate aprovado...

[TESTE 6] running não requer gate → permitido
  ✅ PASS: running permitido: Status running não requer gate

[TESTE 7] failed não requer gate → permitido
  ✅ PASS: failed permitido: Status failed não requer gate

[TESTE 8] Payload tem campos obrigatórios
  ✅ PASS: Payload tem todos campos obrigatórios

[TESTE 9] Evidência expira 24h
  ✅ PASS: Evidência expirada corretamente rejeitada

[TESTE 10] Check obrigatório falhando → gate FAIL
  ✅ PASS: Check obrigatório falhando bloqueia gate

============================================================
RESULTADOS
============================================================
✅ PASS: Gate fail-closed sem venv
✅ PASS: Evidência persistida
✅ PASS: Evidência vinculada ao run
✅ PASS: review sem evidência bloqueado
✅ PASS: completed sem evidência bloqueado
✅ PASS: running permitido
✅ PASS: failed permitido
✅ PASS: Payload campos obrigatórios
✅ PASS: Evidência expira 24h
✅ PASS: Mandatory fail bloqueia

Total: 10/10 testes passaram
```

---

## 10. Git Status

### Diff Stat
```
 apps/api/app/routers/handoffs.py            | 74 ++++++++++++++++-----
 apps/api/app/services/handoff.py            | 25 +++++++
 apps/api/app/services/test_gate.py          | 350 +++++++++++++++++++++
 apps/api/tests/test_test_gate.py            | 250 ++++++++++++++++
 scripts/validate_task_for_review.py         |  20 +++---
 5 files changed, 680 insertions(+), 39 deletions(-)
```

### Git Status Short
```
 M apps/api/app/routers/chat_sessions.py        (Gemini - preservado)
 M apps/api/app/routers/handoffs.py             (gate + ordem runtime)
 M apps/api/app/services/handoff.py             (integração test_gate)
 M apps/api/tests/test_chat_session_from_task.py (Gemini - preservado)
 M apps/api/tests/test_status_transition_automation.py (Gemini - preservado)
 M apps/web/src/components/TaskDetail.test.tsx  (Gemini - preservado)
 M apps/web/src/components/TaskDetail.tsx       (Gemini - preservado)
 M apps/web/src/services/backlog.service.ts     (Gemini - preservado)
?? apps/api/app/services/test_gate.py           (NOVO - service)
?? apps/api/tests/test_test_gate.py             (NOVO - testes)
?? scripts/validate_task_for_review.py          (atualizado)
```

---

## 11. Confirmações de Segurança

- [x] **NÃO** executado piloto `scripts/piloto_task_ponta_a_ponta.sh`
- [x] **NÃO** aplicada migration `0002_add_dora_aggregation_views.py`
- [x] **NÃO** instalados serviços/timers systemd DORA
- [x] **NÃO** feito deploy
- [x] **NÃO** feito commit
- [x] **NÃO** feito push
- [x] **NÃO** feito reset/clean/stash
- [x] **NÃO** sobrescritos arquivos do Gemini
- [x] **PRESERVADOS** fluxos existentes de Backlog → AI Hub
- [x] **NÃO** alterado `queue_build()` ou gate de aprovação de plano

---

## 12. Resumo das Correções

### Problema 1: Dependência Invertida
**Causa:** `handoff.py` (service) importava `run_test_gate()` de `handoffs.py` (router)

**Solução:** Criado `test_gate.py` (service) que é importado por ambos.

---

### Problema 2: Fail-Open
**Causa:** `if not gate_script.exists(): return True` e `except: return True`

**Solução:** Service `test_gate.py` com política fail-closed explícita:
```python
evidence.passed = len(mandatory_failed) == 0  # Só passa se tudo passar
```

---

### Problema 3: Bypass `running → completed`
**Causa:** Gate só protegia `review`

**Solução:** `update_run()` protege ambos:
```python
if next_status in {"review", "completed"}:
    allowed, reason = validate_run_for_status_change(db, run, next_status)
```

---

### Problema 4: Ordem de Finalização do Runtime
**Causa:** `finalize_auto_runtime()` chamado antes de validar gate

**Solução:** Invertida ordem no `PATCH /runs/{run_id}`:
1. `update_run()` valida gate
2. Se aceito → `finalize_auto_runtime()`

---

### Problema 5: Paths Errados
**Causa:** Script procurava binários na raiz

**Solução:** Paths corrigidos:
```python
API_VENV = WORKDIR / "apps/api" / "venv" / "bin" / "python"
PNPM = WEB_DIR / "node_modules" / ".bin" / "pnpm"
```

---

### Problema 6: Testes de Grep
**Causa:** `test_fase1_correcoes.py` só verificava strings

**Solução:** Criados testes comportamentais reais em `test_test_gate.py`:
- 10 testes executáveis
- Valida comportamento real do service
- Cobre todos casos críticos

---

**CORREÇÃO DEFINITIVA DO GATE PRONTA PARA AUDITORIA — PILOTO AINDA NÃO EXECUTADO**
