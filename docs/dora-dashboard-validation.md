# Validação — Dashboard Executivo DORA

**Data:** 2026-09-07
**Task:** `339e074d-faa3-4062-a2a2-e114fd627454`
**Status:** Implementação concluída, validação pendente

---

## Critérios de Aceite do Plano

### ✅ 1. Instrumentar deployments
- [x] Tabela `deployment_outcomes` criada (migration `0001`)
- [x] Enum `deployment_outcome` com valores: `success`, `rolled_back`, `hotfixed`, `degraded`
- [x] Endpoint `POST /api/deployments/outcomes` implementado
- [x] Idempotência: HTTP 200 para retry compatível, 409 para divergência
- [x] Pipeline chama `_persist_deployment_outcome()` após postcheck
- [ ] **Validação pendente:** Confirmar se deploy em produção está persistindo outcome

### ⚠️ 2. Views de agregação
- [x] Migration `0002_add_dora_aggregation_views.py` criada
- [x] 5 views implementadas:
  - `dora_deployment_frequency_weekly`
  - `dora_change_failure_rate_30d`
  - `dora_mttr_incidents`
  - `dora_lead_time_completed`
  - `dora_monthly_summary`
- [ ] **Validação pendente:** Aplicar migration no banco
- [ ] **Validação pendente:** Consultas batem com contagem manual?

### ⚠️ 3. Parser de eventos do supervisor
- [x] `apps/api/app/services/incident_parser.py` existe (294 linhas)
- [x] Script `scripts/incident_parser.py` criado para integração
- [x] Eventos `incident_detected` e `incident_resolved` persistidos em `agent_run_events`
- [ ] **Validação pendente:** Log das últimas 24h do supervisor bate com eventos persistidos?
- [ ] **Validação pendente:** MTTR do card é derivado dos eventos?

### ✅ 4. Endpoint de métricas
- [x] `GET /api/metrics/executive` implementado
- [x] Cache em memória com TTL de 300s (5 min)
- [x] Retorna 4 métricas DORA + DORA Score + DORA Level
- [x] Filtro por `project_id` e `days`
- [ ] **Validação pendente:** Tempo de resposta < 300ms com cache quente?

### ✅ 5. UI do painel
- [x] `apps/web/src/pages/ExecutiveDashboard.tsx` (372 linhas)
- [x] 4 cards para as métricas DORA
- [x] DORA Score com benchmarks (Elite/High/Medium/Low)
- [x] Responsivo, sem scroll horizontal em 1280px
- [x] Error handling por card
- [ ] **Validação pendente:** Testar renderização em 1280px

### ✅ 6. Job de refresh
- [x] Script `scripts/refresh_dora_views.py` criado
- [x] Service `workdev-dora-refresh.service` criado
- [x] Timer `workdev-dora-refresh.timer` criado (5 min)
- [x] Alerta Telegram em caso de falha
- [x] Métricas de observabilidade (latência, status)
- [ ] **Validação pendente:** Instalar units no systemd
- [ ] **Validação pendente:** Job atualiza com defasagem < 5 min?

### ❌ 7. Validação com uso real
- [ ] Backfill de dados históricos (30 dias)
- [ ] Validar dados na tabela `deployment_outcomes`
- [ ] Validar eventos de incidente em `agent_run_events`
- [ ] Testar endpoint com dados reais
- [ ] Validar UI em produção

---

## Comandos de Validação

### 1. Verificar tabela deployment_outcomes
```bash
psql "postgresql://workdev_app:t6RnjZwYB1W2rPAasY6GHcZd9ksMjyTfPn2hz8WB@127.0.0.1:5432/workdev" -c "
SELECT outcome, COUNT(*)
FROM deployment_outcomes
GROUP BY outcome;
"
```

### 2. Aplicar migration das views
```bash
cd /opt/workdev/apps/api && python3 -m alembic upgrade head
```

### 3. Testar views
```bash
psql "postgresql://workdev_app:t6RnjZwYB1W2rPAasY6GHcZd9ksMjyTfPn2hz8WB@127.0.0.1:5432/workdev" -c "
SELECT * FROM dora_deployment_frequency_weekly LIMIT 5;
SELECT * FROM dora_change_failure_rate_30d;
SELECT COUNT(*) FROM dora_mttr_incidents;
SELECT COUNT(*) FROM dora_lead_time_completed;
"
```

### 4. Testar endpoint (requer API key)
```bash
API_KEY=$(cat /etc/workdev-deploy/api.key)
curl -s -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:8000/api/metrics/executive?days=30" | \
  python3 -m json.tool
```

### 5. Medir latência do endpoint
```bash
API_KEY=$(cat /etc/workdev-deploy/api.key)
for i in {1..5}; do
  start=$(date +%s%N)
  curl -s -H "X-API-Key: $API_KEY" "http://127.0.0.1:8000/api/metrics/executive?days=30" > /dev/null
  end=$(date +%s%N)
  latency=$(( (end - start) / 1000000 ))
  echo "Request $i: ${latency}ms"
done
```

### 6. Instalar job de refresh
```bash
sudo cp /opt/workdev/scripts/workdev-dora-refresh.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable workdev-dora-refresh.timer
sudo systemctl start workdev-dora-refresh.timer
sudo systemctl status workdev-dora-refresh.timer
```

### 7. Validar eventos de incidente
```bash
psql "postgresql://workdev_app:t6RnjZwYB1W2rPAasY6GHcZd9ksMjyTfPn2hz8WB@127.0.0.1:5432/workdev" -c "
SELECT
  event_type,
  COUNT(*) AS total,
  payload->>'service_name' AS service,
  payload->>'detected_at' AS detected,
  payload->>'resolved_at' AS resolved
FROM agent_run_events
WHERE event_type IN ('incident_detected', 'incident_resolved')
GROUP BY event_type, payload->>'service_name', payload->>'detected_at', payload->>'resolved_at'
ORDER BY detected DESC
LIMIT 20;
"
```

---

## Estado Atual da Implementação

| Subtask | Arquivos Criados/Modificados | Status |
|---------|------------------------------|--------|
| 1. Instrumentar deploy | `models/deployment.py`, `schemas/deployment.py`, `routers/deployments.py`, `scripts/deploy/pipeline.py` | ✅ Concluída |
| 2. Views | `alembic/versions/0002_add_dora_aggregation_views.py` | ⏳ Aguardando aplicação |
| 3. Parser | `services/incident_parser.py`, `scripts/incident_parser.py` | ⚠️ Integração pendente |
| 4. Endpoint | `routers/metrics.py` | ✅ Concluída |
| 5. UI | `pages/ExecutiveDashboard.tsx` | ✅ Concluída |
| 6. Job refresh | `scripts/refresh_dora_views.py`, `workdev-dora-refresh.{service,timer}` | ✅ Concluída |
| 7. Validação | `docs/dora-dashboard-validation.md` | ❌ Pendente |

---

## Próximos Passos

1. **Aplicar migration** `0002` no banco
2. **Instalar job de refresh** no systemd
3. **Executar validação** com os comandos acima
4. **Backfill de dados** se necessário (últimos 30 dias)
5. **Testar UI** em 1280px
6. **Commit e deploy** em produção
