# Telemetria por AgentRun — auditoria do schema e proposta

> Escrito em 2026-09-08, na branch `task/d6fb67a5-agent-choice`, que não foi
> incorporada. Trazido para a `main` em 2026-10-27, quando o Cláudio decidiu
> ("do 1 ao 4") — ver ADR 017.
>
> Task `d6fb67a5-e311-4924-8d2f-8e48c17cb5c0`. **Aplicado em 2026-10-27**, com
> uma diferença em relação ao texto original: a coluna `provider` ficou
> **nullable** (o plano falava em `NOT NULL`), porque as runs anteriores à
> decisão não têm provider — e uma migration que recusa linhas existentes
> não é reversível na prática. O resto do schema é o que está lá em
> `apps/api/alembic/versions/20261027t090000_agent_run_telemetry.py`.

Por isso o SQL abaixo está **fora de `apps/api/alembic/versions/`** — um arquivo
lá seria aplicado no próximo `alembic upgrade head` sem ninguém decidir.

## O que já existe

### `ai_call_logs`

Cobre boa parte do pedido, mas para as chamadas de LLM do **AI Hub**, não para
execuções de agente:

| Campo pedido | Situação |
|---|---|
| input_tokens | ✅ `input_tokens integer` |
| output_tokens | ✅ `output_tokens integer` |
| custo estimado | ✅ `estimated_cost_usd numeric` |
| custo real | ✅ `actual_cost_usd numeric` |
| provider | ✅ `provider varchar` |
| modelo | ✅ `selected_model varchar` |
| free quota | ⚠️ só `is_free boolean` |
| cached_input_tokens | ❌ ausente |
| total de tokens | ❌ ausente (derivável) |
| moeda | ❌ ausente (USD implícito nos nomes) |
| origem do dado | ❌ ausente |
| classificação de custo | ❌ ausente |

**O bloqueio principal:** `ai_call_logs` referencia `session_id` e
`correlation_id`. **Não tem `run_id`.** Não há como agregar consumo por
AgentRun, por task ou por projeto de execução hoje.

### `agent_runs`

Sem nenhuma coluna de telemetria. Também **sem `provider`** — só `agent`,
`model`, `routing_mode`, `routing_reason`.

### `ai_budgets`

`scope_type`/`scope_key`/`limit_usd`. Serve para franquia, mas não registra
consumo.

## Como a implementação atual contorna

Sem migration, o par provider/recomendação já é auditável: `queue_build` grava
no payload JSON do evento `build.queued` os campos `provider`,
`recommended_agent`, `recommended_model` e `selection_source: "human"`. Isso
resolve a rastreabilidade da **escolha**, não a de **consumo**.

Telemetria de tokens e custo por run continua **não implementada** — depende
das colunas abaixo.

## Proposta

Duas mudanças independentes; a primeira é barata e destrava a segunda.

### 1. `agent_runs.provider`

```sql
ALTER TABLE agent_runs ADD COLUMN provider varchar(60);
```

Nulo para os runs históricos. O backend já valida que o provider corresponde à
linha do catálogo; passa a persistir em coluna em vez de só no evento.

### 2. `agent_run_telemetry`

Tabela separada, não colunas em `agent_runs`: um run pode ter várias chamadas
de provedor, e misturar o agregado com o registro do run perde a granularidade.

```sql
CREATE TABLE agent_run_telemetry (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    backlog_id          uuid REFERENCES backlog(id),
    project_id          uuid REFERENCES projects(id),
    agent               varchar(40)  NOT NULL,
    provider            varchar(60)  NOT NULL,
    model               varchar(120) NOT NULL,

    input_tokens        integer,
    cached_input_tokens integer,
    output_tokens       integer,
    total_tokens        integer,

    estimated_cost      numeric(12,6),
    actual_cost         numeric(12,6),
    currency            varchar(3) NOT NULL DEFAULT 'USD',

    -- 'official'  = número veio da API do provedor
    -- 'estimated' = derivado do runtime/transcript e do preço de catálogo
    source              varchar(16) NOT NULL
        CHECK (source IN ('official', 'estimated')),

    -- local | free_quota | included_plan | paid_api
    cost_class          varchar(20) NOT NULL
        CHECK (cost_class IN ('local', 'free_quota', 'included_plan', 'paid_api')),

    recorded_at         timestamptz NOT NULL DEFAULT now(),
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX agent_run_telemetry_run_idx     ON agent_run_telemetry (run_id);
CREATE INDEX agent_run_telemetry_agent_idx   ON agent_run_telemetry (agent, recorded_at);
CREATE INDEX agent_run_telemetry_project_idx ON agent_run_telemetry (project_id, recorded_at);
```

`source` é a coluna que sustenta o requisito "dados estimados nunca devem ser
apresentados como faturamento oficial": a UI lê `source` e rotula. Ela é
`NOT NULL` de propósito — sem default, para que ninguém grave número sem dizer
de onde veio.

`cost_class` separa CLI local (Ollama futuro), franquia gratuita, plano já pago
por assinatura (Claude/Codex por assinatura) e API cobrada por token. Sem isso,
somar custo por agente mistura o que é despesa marginal com o que já está pago.

### Agregações que passam a ser possíveis

```sql
-- por agente
SELECT agent, sum(total_tokens), sum(coalesce(actual_cost, estimated_cost))
FROM agent_run_telemetry
WHERE cost_class = 'paid_api'
GROUP BY agent;

-- por projeto
SELECT project_id, source, sum(coalesce(actual_cost, estimated_cost))
FROM agent_run_telemetry
GROUP BY project_id, source;
```

Agrupar por `source` no relatório evita somar oficial com estimado na mesma
linha.

## Ordem sugerida

1. Aplicar a migration (decisão do Cláudio; migrations não são automáticas). Feito em 2026-10-27 — a migration entra **antes** do deploy do código, porque `agent_runs.provider` é lida pelo ORM.
2. Passar `provider` de `queue_build` para a coluna, além do evento.
3. Instrumentar os coletores por agente — cada CLI expõe consumo de um jeito
   diferente, e Claude/Codex por assinatura talvez não exponham nada. Onde não
   houver número oficial, gravar `source='estimated'` com o preço do catálogo.
4. UI de consumo, sempre distinguindo oficial de estimado.

Os passos 3 e 4 são trabalho de tamanho próprio e não cabem nesta task.
