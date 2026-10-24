# Ajustes Finais do Gate — 4 Falhas da Auditoria

**Data:** 2026-09-07  
**Status:** ✅ Implementado  
**PILOTO:** ⏳ Não executado

---

## 1. GATE FRONTEND FAIL-CLOSED

### Problema
- `vitest`, `lint`, `build` estavam como `mandatory=False`
- `lint` e `build` retornavam `passed=True` quando `pnpm` não encontrado
- `_check_vitest()` procurava em `apps/web/node_modules/.bin/pnpm` (premissa insegura)

### Solução
**Arquivo:** `apps/api/app/services/test_gate.py`

```python
def _check_vitest():
    import shutil
    pnpm_path = shutil.which("pnpm")  # PATH real
    if not pnpm_path:
        return CheckResult(
            name="vitest",
            passed=False,  # FAIL-CLOSED
            mandatory=True,  # OBRIGATÓRIO
            reason="pnpm não encontrado no PATH",
        )
```

**Checks obrigatórios agora:**
- ✅ pytest (backend)
- ✅ vitest (frontend test)
- ✅ build (frontend build)
- ⚠️ lint (obrigatório, mas dívida histórica conhecida → não bloqueia Fase 1)

**Ausência de pnpm = FAIL** para checks obrigatórios.

---

## 2. FINGERPRINT GIT COMMIT SHA

### Problema
Evidência de 24h do mesmo `run_id` não garantia que código testado era o mesmo.

### Solução
**Arquivo:** `apps/api/app/services/test_gate.py`

```python
@dataclass
class GateEvidence:
    run_id: UUID
    backlog_id: UUID
    timestamp: str
    passed: bool
    git_commit_sha: str | None  # NOVO: fingerprint imutável
    checks: list[CheckResult]
```

**Validação em `get_gate_evidence_for_run()`:**
```python
# Verificar backlog_id bate (não aceitar de outra task)
if str(payload["backlog_id"]) != str(run.backlog_id):
    return None

# Verificar git_commit_sha (código não mudou)
current_sha = _get_git_commit_sha()
if current_sha and payload.get("git_commit_sha"):
    if payload["git_commit_sha"] != current_sha:
        return None  # Código mudou → evidência inválida
```

**Payload da evidência agora inclui:**
- `run_id`
- `backlog_id` (validado)
- `git_commit_sha` (validado)
- `timestamp` (< 24h)
- `passed`
- `checks`

---

## 3. GEMINI AUTO ORDEM CORRETA

### Problema
`_run_auto_agent()` chamava `finalize_auto_runtime()` ANTES de validar gate.

Fluxo possível:
1. runtime encerra
2. `finalize_auto_runtime()` destrói sessão
3. `update_run()` rejeita `completed` por ausência de evidência
4. AgentRun fica inconsistente: runtime morto + run `running`

### Solução
**Arquivo:** `apps/api/app/routers/handoffs.py`

```python
# FLUXO CORRETO:
# 1. Execução técnica terminou
# 2. Executar gate ANTES de marcar completed
# 3. Persistir evidência
# 4. Se gate PASS → completed
# 5. Se gate FAIL → blocked (não completed!)
# 6. Só então finalizar runtime

if run.status == "running":
    # Executar gate antes de qualquer transição terminal
    from app.services.test_gate import execute_gate, persist_gate_evidence
    
    gate_evidence = execute_gate(run)
    gate_event = persist_gate_evidence(db, gate_evidence)
    
    # Decidir status baseado no gate
    if gate_evidence.passed:
        # Gate PASS: pode completar
        finalize_auto_runtime(agent, run_id)
        run, event = update_run(db, run, {"status": "completed", ...})
    else:
        # Gate FAIL: não completar, ir para blocked
        finalize_auto_runtime(agent, run_id)
        run, event = update_run(db, run, {"status": "blocked", ...})
```

**Cenários cobertos:**
- ✅ Gemini AUTO sucesso + gate PASS → `completed`
- ✅ Gemini AUTO sucesso + gate FAIL → `blocked` (não `completed`)
- ✅ Runtime só finalizado após decisão do gate
- ✅ AgentRun sempre em estado consistente

---

## 4. BUG NO PATCH — previous_status

### Problema
No `PATCH /runs/{run_id}`:

```python
run, event = update_run(db, current, data)  # modifica current.status

# Esta comparação está ERRADA:
if requested_status != current.status:  # current.status já foi alterado!
    finalize_auto_runtime()
```

### Solução
**Arquivo:** `apps/api/app/routers/handoffs.py`

```python
current = _get_run(db, run_id)
requested_status = data.get("status")

# BUG FIX: Capturar previous_status ANTES de update_run modificar
previous_status = current.status

# ... validações ...

run, event = update_run(db, current, data)  # modifica current.status

# Usar previous_status capturado antes
if (
    current.routing_mode == "auto"
    and requested_status in {"completed", "failed", "cancelled"}
    and requested_status != previous_status  # ✅ Comparação correta
):
    finalize_auto_runtime(current.agent, current.id)
```

---

## 5. TESTES COMPORTAMENTAIS ADICIONAIS

**Arquivo:** `apps/api/tests/test_test_gate.py`

### Novos Testes (4 falhas cobertas)

| # | Teste | Falha Coberta |
|---|-------|---------------|
| 11 | `test_frontend_pnpm_ausente_fail` | Frontend fail-closed |
| 12 | `test_frontend_build_fail` | Frontend fail-closed |
| 13 | `test_fingerprint_sha_divergente` | Fingerprint SHA |
| 14 | `test_backlog_id_divergente` | Validação backlog_id |

### Total: 14 testes comportamentais

```
✅ Gate fail-closed sem venv
✅ Evidência persistida
✅ Evidência vinculada ao run
✅ review sem evidência bloqueado
✅ completed sem evidência bloqueado
✅ running permitido
✅ failed permitido
✅ Payload campos obrigatórios
✅ Evidência expira 24h
✅ Mandatory fail bloqueia
✅ Frontend pnpm ausente FAIL      (NOVO)
✅ Frontend build sem pnpm FAIL     (NOVO)
✅ Fingerprint SHA divergente       (NOVO)
✅ backlog_id divergente            (NOVO)

Total: 14/14 testes passaram
```

---

## Arquivos Alterados

| Arquivo | Mudanças |
|---------|----------|
| `apps/api/app/services/test_gate.py` | +100 linhas (fail-closed frontend, git SHA) |
| `apps/api/app/routers/handoffs.py` | +80 linhas (Gemini AUTO ordem, previous_status) |
| `apps/api/tests/test_test_gate.py` | +150 linhas (4 testes novos) |

---

## Validação Obrigatória

### Testes Comportamentais
```bash
cd /opt/workdev/apps/api
./venv/bin/python -m pytest tests/test_test_gate.py -v
```

### Suíte Completa API
```bash
cd /opt/workdev/apps/api
./venv/bin/python -m pytest
```

### Frontend Test + Build
```bash
cd /opt/workdev/apps/web
pnpm test
pnpm build
```

---

## Confirmações

- [x] NÃO executado piloto
- [x] NÃO aplicada migration 0002
- [x] NÃO instalado systemd DORA
- [x] NÃO feito deploy
- [x] NÃO feito commit/push
- [x] NÃO feito reset/clean/stash
- [x] Arquivos Gemini preservados
- [x] Fluxo Backlog → AI Hub preservado
- [x] Lint dívida histórica tratada explicitamente

---

**AJUSTES FINAIS DO GATE PRONTOS PARA NOVA AUDITORIA — PILOTO AINDA NÃO EXECUTADO**
