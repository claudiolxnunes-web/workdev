# WorkDev Supervisor — Plano do MVP (Nível 0, somente leitura)

- **Data:** 2026-08-16
- **Status:** plano, não implementado
- **Base:** `develop` @ `da28678`
- **Veredito:** **PLANO RECOMENDADO** (justificativa na seção 20)

> Este documento é resultado de investigação do estado real (Postgres do WorkDev,
> Postgres do RAG, git, systemd, arquivos de estado). Todos os números citados
> foram medidos em 2026-08-16, não estimados.

---

## 1. O que a investigação encontrou

Antes da arquitetura, os fatos que justificam (ou não) cada check. Isto é a
linha de base contra a qual o MVP será avaliado.

### 1.1 Postgres do WorkDev (`127.0.0.1:5432/workdev`, user `workdev_app`)

13 tabelas: `projects`, `backlog`, `backlog_subtasks`, `execution_plans`,
`agent_runs`, `agent_run_events`, `adrs`, `rfcs`, `decisions`, `knowledge`,
`chat_sessions`, `chat_messages`, `alembic_version`.

| Fato medido | Valor |
| --- | --- |
| Projetos | 19 (1 `Suspended`: Ngrep BPF) |
| Backlog aberto, `critical` | 7 itens, o mais antigo parado há 20 dias |
| Backlog aberto, `high` | 22 itens, o mais antigo parado há 34 dias |
| `execution_plans` | 33 (25 `approved`, 4 `discarded`, 4 `superseded`) |
| Planos `approved` sem nenhum `agent_run` | 2 |
| `agent_runs` | 35, **todos em estado terminal**; o último terminou em 2026-08-10 |
| `backlog_subtasks` abertas | 100 `todo` + 1 `blocked` |
| `adrs` | 19 |
| `knowledge` | 85 (46 lição, 22 decisão, 12 solução, 4 referência, 1 operações) |
| `decisions` | **0** |
| `rfcs` | **0** |

Duas armadilhas de schema que a implementação precisa respeitar:

1. **`priority` é texto livre e está sujo.** Convivem `critical`, `high`,
   `medium`, `low` com `Alta` e `High`. Qualquer filtro precisa de
   `lower(priority)` + mapa de sinônimos, ou perde itens silenciosamente.
2. **`backlog.created_at` / `updated_at` são `timestamp without time zone`**,
   enquanto `execution_plans` e `agent_runs` usam `timestamptz`. Comparar com
   `now()` direto funciona por coerção implícita, mas o correto é
   `now() AT TIME ZONE 'UTC'` do lado do `backlog`.

`updated_at` do backlog é confiável como "último toque": o PATCH em
`app/routers/backlog.py` seta o campo explicitamente (`SELECT now()`), não
depende de trigger.

`owner` é nulo em praticamente todo o backlog aberto — **não serve como sinal**.

### 1.2 RAG (`127.0.0.1:5433`, tabela `documentos`)

Postgres separado (container do `/opt/rag-postgres/docker-compose.yml`).
`workdev-rag-ingest.timer` roda o ingestor a cada 5 minutos. Raízes varridas
(`ALVOS` em `ingestor.py`): `docs/adr`, `decisions`, `backlog.md`, `knowledge`.

Indexado hoje: **13 documentos** — 10 `decision` (os `.md` de `decisions/`),
1 `adr` (`docs/adr/004-plan-build-handoff.md`), 1 `backlog`, 1 `knowledge`.

**Divergência real e mensurável:**

- Os **19 ADRs da tabela `adrs`** e as **85 linhas de `knowledge`** do Postgres
  não estão no RAG — não são arquivos, e o ingestor só varre disco.
- `backlog.md` diz "Exportado em 2026-08-13 — 84 itens". O banco tem **179**.
  O RAG serve, portanto, uma foto do backlog com 95 itens a menos.
- Há **duplicação com divergência**: "ADR — RAG em Postgres para a base de
  conhecimento" existe como linha em `knowledge` (2026-08-15) *e* como
  `decisions/2026-08-15-rag-postgres.md` (indexado). O mesmo vale para os ADRs
  de credenciais dos agentes, MCP do backlog e pré-implantação do Feed_BPF.
- `decisions` (tabela) e `rfcs` estão vazias mas têm routers ativos
  (`/api/decisions`, `/api/rfcs`) — estrutura morta que compete com `adrs` e
  com os `.md` de `decisions/`.

### 1.3 Git / deploy

```
develop  da28678   [origin/develop: ahead 3]
main     dacbe04   [origin/main:   ahead 2]
main..develop = 43 commits
```

- **3 commits em `develop` existem só nesta VPS** (não empurrados), incluindo
  `57a6dad feat: instrumentar WorkDev API com GlitchTip`.
- `main` está 43 commits atrás de `develop`. O `CLAUDE.md` diz que `main` é
  somente por PR — na prática ninguém abre o PR.
- **`deploy.sh` builda a partir da árvore de trabalho**, não de um commit.
- A política de agentes foi posteriormente consolidada no commit
  `0d63fee feat: keep Kimi and Qwen in standby`, eliminando o risco específico
  de perda dessa configuração por alterações locais não commitadas.
- `dist/` buildado em 2026-08-15 13:53; `workdev-api` reiniciado 20:31.
  Nenhum fonte mais novo que o build. Estado atual: **coerente**.
- Não existe tabela de deployments. `deployments.json` é só uma lista de URLs
  para ping (`/api/deployments/status`).

### 1.4 Agentes

`scripts/agents_healthcheck.py` grava `/var/lib/agents-healthcheck/status.json`
a cada 5 min (`workdev-agents-health.timer`), com
`{agent, session, status, process, reason, checked_at, recovered}` e
`status ∈ {idle, busy, blocked, offline}`. Alerta no Telegram só em transição.
`always_on = {claude, codex}`.

Estado em 2026-08-16T03:57Z: `claude=idle`, `codex=idle`, `kimi=offline`,
`qwen=offline`. Os dois offline são **intencionais** (standby) — a versão
não-commitada do `bootstrap_agents.sh` já removeu kimi/qwen do boot.

### 1.5 O que já existe de monitoramento

| Peça | O que faz | Reuso pelo Supervisor |
| --- | --- | --- |
| `scripts/agents_healthcheck.py` | supervisão tmux + Telegram + anti-spam | **consumir `status.json`**, nunca reimplementar |
| `scripts/healthcheck_api.sh` | cron 5 min, reinicia API, anti-spam 6h | copiar o *padrão* de anti-spam |
| `verificar-deploy.sh` | gate pré-deploy | **só o subconjunto read-only** (ver 4.3) |
| `/api/monitoring/status` | systemd VPS1 + SSH VPS2 + docker | opcional, fase 2 |
| `/api/system/migrations` | alembic `current` vs `head` | sim, no `deploy_drift` |
| `/api/deployments/status` | ping HTTP de 8 apps | não no MVP |
| `app/services/handoff.py` | máquina de estados de plan/run | **importar** `ACTIVE_RUN_STATUSES` |
| `/opt/rag-postgres/ingestor.py` | métricas `chave=valor`, `roots_unavailable` | copiar o formato de log |
| `/opt/scripts/alerta.env` | `TG_TOKEN` / `TG_CHAT` | canal de entrega |
| GlitchTip (`sentry-sdk`) | erros da API | fora do escopo |

---

## 2. Arquitetura proposta

```
                     ┌───────────── camada de leitura (read-only) ─────────────┐
  Postgres workdev ──┤ readers/db_workdev.py   (SET TRANSACTION READ ONLY)     │
  Postgres rag  ─────┤ readers/db_rag.py       (porta 5433)                    │
  git / filesystem ──┤ readers/repo.py         (subprocess git, somente leitura)│
  systemd ───────────┤ readers/systemd.py      (systemctl show / is-active)     │
  status.json ───────┤ readers/agents.py                                        │
  HTTP local ────────┤ readers/api.py          (GET /api/system/migrations)     │
                     └────────────────────────┬──────────────────────────────┘
                                              │  linhas cruas
                                              ▼
                         checks/*.py  ── 5 checks determinísticos
                                              │  Fato[] (dataclass, sem prosa)
                                              ▼
                         redacao.py   ── varredura de segredos (fail-closed)
                                              │
                                              ▼
                         estado.py    ── fingerprint, transições, supressão
                                              │  novos + agravados + resolvidos
                                              ▼
                         llm.py       ── 1 chamada, sem tools, schema fixo
                                              │  prioridade + prosa
                                              ▼
                         relatorio.py ── ≤3 achados + linha de persistentes
                                              │
                          ┌───────────────────┴───────────────────┐
                          ▼                                       ▼
                  Telegram (entrega)                  /var/lib/workdev-supervisor/
                                                      state.json + runs.jsonl
```

**Invariante central:** nenhum campo determinístico (`check`, `severity`,
`entity_id`, `evidence`, `fingerprint`, `detected_at`) passa pelo LLM. O LLM
recebe fatos e devolve *ordenação e prosa*, referenciando fatos por `id`. Um
`id` que não existe na entrada é descartado.

### 2.1 Localização e dependências

```
/opt/workdev/scripts/supervisor/
├── __main__.py          # CLI: --once --dry-run --seed --json --check X --modelo Y
├── config.py            # limiares, política de agentes, caminhos
├── modelo.py            # dataclasses Fato, Achado, Execucao
├── readers/
├── checks/
│   ├── critical_stalled.py
│   ├── plan_without_execution.py
│   ├── deploy_drift.py
│   ├── knowledge_drift.py
│   └── agent_health.py
├── redacao.py
├── estado.py
├── llm.py
├── relatorio.py
└── entrega.py
```

Roda com o venv que já existe: `/opt/workdev/apps/api/venv/bin/python` — já tem
`psycopg`, `anthropic`, `python-dotenv`, `requests`. **Zero dependência nova,
zero venv novo.** Credenciais vêm de `/opt/workdev/apps/api/.env` via `dotenv`,
lido explicitamente (mesma lição do RAG e dos wrappers de agente: shell não
interativo não lê `.bashrc`).

---

## 3. Estrutura de dados

```python
@dataclass(frozen=True)
class Fato:
    check: str                 # "critical_stalled"
    subcheck: str | None       # "never_dispatched"
    entity_type: str           # "backlog" | "execution_plan" | "repo" | "documento" | "agente"
    entity_id: str             # UUID, path, nome de branch, nome de agente
    project_id: str | None
    project_name: str | None
    severity: str              # critical | high | medium | info  (DETERMINÍSTICO)
    bucket: str                # faixa da condição — entra no fingerprint
    titulo: str                # frase curta, sem LLM
    medidas: dict              # {"dias_parado": 20, "prioridade": "critical", ...}
    evidencia: list[str]       # comandos/queries que qualquer um pode reexecutar
    detected_at: str           # ISO-8601 UTC

    @property
    def fingerprint(self) -> str:      # sha256(check|subcheck|entity_id|bucket)[:16]

@dataclass
class Achado:                   # Fato + estado + saída do LLM
    fato: Fato
    fingerprint: str
    status: str                 # novo | persistente | agravado | resolvido
    first_seen_at: str
    last_seen_at: str
    ocorrencias: int
    prioridade: int | None      # do LLM (1 = mais urgente)
    impacto: str | None         # do LLM
    risco: str | None           # do LLM
    recomendacao: str | None    # do LLM
    acao_sugerida: str | None   # do LLM — texto, nunca executável
```

Diferenças em relação à estrutura sugerida na missão, com justificativa:

- **`severity` é determinística, `prioridade` é do LLM.** Separar as duas evita
  que o modelo rebaixe algo crítico e evita que a supressão de ruído dependa de
  saída não determinística.
- **`bucket` é campo de primeira classe**, porque é ele — e não a idade exata —
  que entra no fingerprint (seção 5).
- **`situation` virou `titulo` (determinístico) + `impacto` (LLM).** Uma frase
  factual que existe mesmo se o LLM falhar.
- **`medidas` e `evidencia` separados**: números para comparação entre execuções,
  comandos para auditoria humana.

---

## 4. Os 5 checks — fontes, SQL e comandos

Limiares em `config.py`, todos ajustáveis sem alterar código de check.

### 4.1 `critical_stalled`

Fonte: `backlog` ⨝ `projects`, com `backlog_subtasks` e `agent_runs` para contexto.

```sql
SELECT p.name                                        AS projeto,
       p.id                                          AS project_id,
       b.id, b.title, b.priority, b.status, b.owner,
       b.updated_at,
       (EXTRACT(epoch FROM (now() AT TIME ZONE 'UTC') - b.updated_at)/86400)::int AS dias_parado,
       (SELECT count(*) FROM backlog_subtasks s
         WHERE s.backlog_id = b.id AND s.status <> 'done')                        AS subtasks_abertas,
       (SELECT max(ar.updated_at) FROM agent_runs ar WHERE ar.backlog_id = b.id)  AS ultima_execucao,
       (SELECT count(*) FROM execution_plans ep
         WHERE ep.backlog_id = b.id AND ep.status = 'approved')                   AS planos_aprovados
FROM backlog b
JOIN projects p ON p.id = b.project_id
WHERE b.status IN ('todo','doing','blocked')
  AND lower(b.priority) IN ('critical','critica','crítica','high','alta')
  AND p.status <> 'Suspended'
  AND b.updated_at < (now() AT TIME ZONE 'UTC')
                     - (%(limite_dias)s::text || ' days')::interval
ORDER BY b.updated_at ASC;
```

Limiares: `critical` > **7** dias, `high` > **21** dias (calibrado para que a
carga inicial não estoure — hoje isso daria 7 críticas e ~8 altas, não 29).

Buckets: `7-14`, `15-30`, `31-60`, `60+` dias.
Severidade: `critical` do backlog → `critical`; `high` → `high`, subindo para
`critical` se `dias_parado > 45`.

Evidência emitida: `SELECT ... FROM backlog WHERE id='<uuid>'` e a URL da task.

### 4.2 `plan_without_execution`

Dois subchecks com fingerprints distintos.

```sql
SELECT pr.name AS projeto, pr.id AS project_id,
       b.id AS backlog_id, b.title AS task, b.status AS task_status,
       ep.id AS plano_id, ep.title AS plano, ep.version, ep.status AS plano_status,
       ep.approved_at,
       (EXTRACT(epoch FROM now() - ep.approved_at)/86400)::int AS dias_desde_aprovacao,
       ar.id AS run_id, ar.agent, ar.status AS run_status, ar.updated_at AS run_updated_at,
       (EXTRACT(epoch FROM now() - ar.updated_at)/86400)::int AS dias_sem_evento
FROM execution_plans ep
JOIN backlog   b  ON b.id  = ep.backlog_id
JOIN projects  pr ON pr.id = b.project_id
LEFT JOIN LATERAL (
    SELECT a.* FROM agent_runs a
     WHERE a.plan_id = ep.id
     ORDER BY a.created_at DESC LIMIT 1
) ar ON true
WHERE ep.status = 'approved'
  AND b.status <> 'done'
  AND (
        (ar.id IS NULL  AND ep.approved_at < now() - interval '3 days')
     OR (ar.status = ANY(%(ativos)s) AND ar.updated_at < now() - interval '2 days')
      );
```

- `%(ativos)s` vem de `ACTIVE_RUN_STATUSES` importado de
  `app.services.handoff` — **não redefinir a máquina de estados.**
- `b.status <> 'done'` é obrigatório: dos 2 planos aprovados sem run hoje, um
  pertence a uma task já concluída. Sem esse filtro o check nasce com 50% de
  falso positivo.
- Subcheck `run_stalled` hoje retorna vazio (nenhum run ativo desde 2026-08-10).
  Isso é o comportamento correto, não um bug.

Buckets: dias em faixas `3-7`, `8-21`, `22+`.
Severidade: `high`; `critical` se a task-alvo for `critical`.

### 4.3 `deploy_drift`

Não é CI/CD. São seis leituras baratas de estado, todas somente leitura.

| Sinal | Comando | Dispara quando |
| --- | --- | --- |
| Código em produção não commitado | `git -C /opt/workdev status --porcelain` filtrado por `^ M\|^M ` | ≥1 arquivo rastreado modificado (deploy usa a árvore de trabalho) |
| Commits só na VPS | `git rev-list --count origin/develop..develop` | > 0 por mais de 2 dias |
| `main` estagnada | `git rev-list --count main..develop` | cruza faixa de bucket |
| Build desatualizado | mtime de `apps/web/dist/index.html` vs `find apps/web/src -newer` | qualquer fonte mais novo que o build |
| Serviço rodando código velho | `systemctl show workdev-api -p ActiveEnterTimestamp` vs mtime de `apps/api/app/**/*.py` | fonte mais novo que o restart |
| Migration pendente | `GET http://127.0.0.1:8000/api/system/migrations` | `up_to_date == false` |
| Órfão na 8000 | `ss -tlnp \| grep -c ':8000 '` | > 1 |

**Decisão explícita: o Supervisor NÃO invoca `verificar-deploy.sh`.** Aquele
script roda `pnpm build`, que escreve em `dist/` e leva minutos — viola tanto o
"somente leitura" quanto o orçamento de tempo. O Supervisor reimplementa apenas
os itens 1, 2 e 7 daquele script (os read-only). Dívida registrada: a longo
prazo, extrair esses três para um módulo comum lido pelos dois.

Buckets: para "commits não empurrados" e "main atrás", bucketizar por faixa
(`1-5`, `6-20`, `21-50`, `50+`) — senão cada commit novo vira achado novo.
Severidade: `high` para código não commitado em produção e migration pendente;
`medium` para o resto; `critical` para órfão na 8000.

> Hoje esse check dispararia dois achados legítimos: os dois `scripts/*` rodando
> em produção sem commit, e os 3 commits que só existem nesta VPS.

### 4.4 `knowledge_drift`

Cinco subchecks. Fonte A = Postgres WorkDev; fonte B = Postgres RAG (5433);
fonte C = disco.

```sql
-- fonte B (porta 5433, banco rag)
SELECT fonte_id, titulo, metadados->>'tipo' AS tipo, conteudo_hash, atualizado_em
  FROM documentos
 WHERE fonte = 'workdev';
```

| Subcheck | Regra | Estado hoje |
| --- | --- | --- |
| `adr_fora_do_rag` | título normalizado de `adrs` sem correspondente em `documentos` | **19 de 19** |
| `knowledge_fora_do_rag` | linhas de `knowledge` sem correspondente | **85 de 85** |
| `backlog_md_defasado` | `Exportado em <data>` + contagem no cabeçalho vs `count(*)` do banco | 84 vs **179**, 3 dias |
| `arquivo_nao_indexado` | `.md` sob as raízes do ingestor ausente de `documentos.fonte_id` | 0 |
| `fonte_duplicada` | mesmo título normalizado em ≥2 stores (`knowledge` + `decisions/*.md`) | **4 pares** |

Normalização de título: minúsculas, remoção de acentos, colapso de espaços,
remoção de prefixo `ADR NNNN — `. Comparação exata sobre o normalizado — nada de
similaridade difusa no MVP (não determinístico o suficiente para fingerprint).

`adr_fora_do_rag` e `knowledge_fora_do_rag` são achados de **volume**: um único
Fato por subcheck, com a contagem em `medidas`, e o bucket sobre a contagem
(`1-5`, `6-20`, `21-100`, `100+`). Isso evita 104 achados no primeiro dia.

As tabelas `decisions` e `rfcs` vazias entram como Fato `info` de subcheck
`estrutura_morta` — dispara uma vez, vira persistente e some do relatório até
mudar. É o caso de uso ideal do mecanismo de supressão.

Se o Postgres do RAG estiver inacessível, o check retorna `indisponivel` e a
execução termina com `status=degraded` — **nunca `failed`**, e nunca marcando os
documentos como ausentes (o mesmo erro que o `roots_unavailable` do ingestor
evita).

### 4.5 `agent_health`

Lê `/var/lib/agents-healthcheck/status.json`. **Não executa tmux, não reinicia
nada, não abre sessão.**

Política em `config.py`:

```python
SEMPRE_ATIVOS = {"claude", "codex"}
STANDBY_PERMITIDO = {"kimi", "qwen"}
IDADE_MAXIMA_ESTADO_MIN = 20     # timer roda a cada 5
```

Dispara em quatro situações e só nelas:

1. `agente ∈ SEMPRE_ATIVOS` e `status ∈ {offline, blocked}` → `critical`.
2. Qualquer agente com `reason ∈ {authentication, billing, api_key}` — inclusive
   em standby, porque chave inválida não é decisão de política → `high`.
3. **`updated_at` do `status.json` mais velho que 20 minutos** → `critical`,
   subcheck `supervisao_parada`. É o único sinal, em todo o sistema, de que o
   próprio healthcheck morreu; hoje ninguém detecta isso.
4. `agente ∈ SEMPRE_ATIVOS` em `idle` **enquanto existe** `agent_run` em
   `queued`/`running` há mais de 6h → `high`, subcheck `fila_parada`. Hoje não
   dispararia (fila vazia) — correto.

`kimi=offline` e `qwen=offline` **não geram achado**. Está na política.

---

## 5. Deduplicação

```
fingerprint = sha256(f"{check}|{subcheck}|{entity_id}|{bucket}")[:16]
```

O `bucket` é o que torna o mecanismo útil: a idade em dias muda todo dia, a
faixa não. Uma task parada há 8 dias e há 9 dias produz o mesmo fingerprint; ao
cruzar 15 dias, o fingerprint muda e a transição é registrada como `agravado`.

`state.json` (mapa `fingerprint → registro`):

```json
{
  "versao": 1,
  "atualizado_em": "2026-08-16T10:00:03Z",
  "achados": {
    "9f2c1ab34de5f607": {
      "check": "critical_stalled",
      "entity_id": "…uuid…",
      "bucket": "15-30",
      "first_seen_at": "2026-08-16T10:00:03Z",
      "last_seen_at":  "2026-08-19T10:00:02Z",
      "ocorrencias": 4,
      "ultimo_reforco_em": "2026-08-16T10:00:03Z",
      "severity": "critical"
    }
  }
}
```

Máquina de estados por fingerprint:

| Situação | Estado emitido | Vai ao relatório? |
| --- | --- | --- |
| Fingerprint inédito | `novo` | sim |
| Fingerprint já conhecido, sem mudança | `persistente` | não (só na linha-resumo) |
| Mesmo `entity_id`+`check`, bucket pior | `agravado` | sim |
| Mesmo `entity_id`+`check`, bucket melhor | `melhorou` | linha-resumo |
| Ausente nesta execução | `resolvido` | sim, uma vez |
| `resolvido` há mais de 7 dias | removido do estado | — |
| `persistente` sem reforço há 14 dias e severity ≥ high | reforço único | sim, uma vez |

O reforço de 14 dias existe para que um problema crítico nunca desapareça de vez
por ter sido visto uma vez. Sem ele, "silêncio" e "resolvido" ficam
indistinguíveis — que é exatamente a falha do `EXCEPTION WHEN OTHERS` registrada
no ADR de 2026-08-15, na camada de notificação.

**Escrita atômica** do `state.json`: `NamedTemporaryFile` no mesmo diretório +
`Path.replace()`, idêntico ao `write_state()` do `agents_healthcheck.py`.

---

## 6. Priorização e limitação de ruído

Duas etapas, nessa ordem:

**Etapa determinística (antes do LLM).** Ordena por
`(peso_severity, peso_status, dias)` onde
`peso_severity = {critical:0, high:1, medium:2, info:3}` e
`peso_status = {agravado:0, novo:1, resolvido:2}`. Corta em **8 fatos**, que é o
que vai ao LLM. Fatos `info` só entram se sobrar espaço.

**Etapa do LLM.** Recebe os ≤8 e devolve prioridade 1..N e prosa.

**Corte final.** Relatório entrega **no máximo 3 achados completos**. Exceções:

- todo fato `severity == critical` é entregue, mesmo que estoure o limite;
- `resolvido` não conta contra o limite (é uma linha, não um bloco);
- persistentes viram uma linha única: `12 achados persistentes (3 critical, 9 high) — veja state.json`.

---

## 7. Papel exato do LLM

**Entra:** JSON com metadados da execução e a lista de fatos já filtrados,
redigidos e sem segredos.
**Sai:** JSON validado contra schema.
**Não tem:** tools, shell, acesso a banco, acesso a arquivo, acesso à rede.

```python
resp = client.messages.create(
    model=MODELO,                       # config, default claude-opus-5
    max_tokens=8000,
    output_config={
        "effort": "medium",
        "format": {"type": "json_schema", "schema": SCHEMA_ACHADOS},
    },
    system=SYSTEM_PROMPT,               # estável, sem timestamp
    messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
)
```

`SCHEMA_ACHADOS`:

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["resumo", "achados"],
  "properties": {
    "resumo": {"type": "string"},
    "achados": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["fato_id","prioridade","impacto","risco","recomendacao","acao_sugerida"],
        "properties": {
          "fato_id":       {"type": "string"},
          "prioridade":    {"type": "integer"},
          "impacto":       {"type": "string"},
          "risco":         {"type": "string"},
          "recomendacao":  {"type": "string"},
          "acao_sugerida": {"type": "string"}
        }
      }
    }
  }
}
```

Validação pós-resposta, obrigatória:

1. Todo `fato_id` precisa existir no payload de entrada — os que não existirem
   são **descartados e contados** em `llm_ids_invalidos`.
2. Fatos de entrada ausentes na resposta recebem prioridade pela ordem
   determinística e prosa vazia — nunca somem.
3. Nada da resposta sobrescreve `severity`, `entity_id`, `evidencia` ou
   `fingerprint`.

**Modo degradado.** Se a chamada falhar (timeout, 429, 5xx, refusal, schema
inválido), a execução continua: relatório sai só com os campos determinísticos,
`llm_failures=1`, `status=degraded`. O Supervisor nunca deixa de entregar por
causa do LLM. Sem retry agressivo — 1 tentativa, o SDK já faz 2 retries internos.

**Não** dar `thinking: {type: "disabled"}` a esta chamada: no Opus 5 isso ativa
dois modos de falha conhecidos (chamada de tool virando texto, vazamento de tag
`<thinking>`). Efeito adaptativo padrão + `effort: medium` é a configuração certa
para "ordenar e explicar".

---

## 8. Modelo e provedor recomendado

A missão pergunta entre (A) triagem barata + modelo forte quando necessário e
(B) um único modelo intermediário. **A resposta certa aqui é (C): um único
modelo forte** — porque o volume torna a economia irrelevante.

Volume real: 1 execução/dia × ~7k tokens de entrada × ~2k de saída.

| Modelo | Preço in/out (US$/MTok) | Custo/execução | Custo/mês (1×/dia) |
| --- | --- | --- | --- |
| Claude Opus 5 (`claude-opus-5`) | 5,00 / 25,00 | ~US$ 0,085 | **~US$ 2,60** |
| Claude Sonnet 5 (`claude-sonnet-5`) | 3,00 / 15,00 (intro 2,00/10,00 até 31/08) | ~US$ 0,051 | ~US$ 1,55 |
| Claude Haiku 4.5 | 1,00 / 5,00 | ~US$ 0,017 | ~US$ 0,52 |

**Recomendação: `claude-opus-5`**, provedor Anthropic direto, reutilizando
`ANTHROPIC_API_KEY` já presente em `apps/api/.env` (o AI Hub já usa
`ANTHROPIC_MODEL=claude-opus-5`).

Justificativa — e note que ela **não** é "porque é o melhor":

1. A diferença mensal entre Opus 5 e Haiku 4.5 é de **US$ 2**. Construir uma
   camada de triagem para economizar US$ 2/mês adiciona um segundo prompt, um
   segundo schema, uma regra de escalonamento e um modo de falha — custo de
   manutenção maior que a economia, por uma ordem de grandeza.
2. A tarefa é correlacionar fatos de cinco domínios distintos e decidir o que
   merece atenção. É julgamento, não classificação — é exatamente onde a
   diferença de modelo aparece.
3. `modelo` fica em `config.py` e é sobrescrevível por `--modelo`. Trocar para
   Sonnet 5 é uma linha, sem refatoração.

**Gatilho para reavaliar:** se algum check passar a gerar dezenas de fatos por
execução, ou se a frequência subir para horária, refazer esta conta antes de
manter Opus 5. A recomendação é do volume atual, não permanente.

---

## 9. Frequência

**Recomendação: 1 execução por dia, 10:00 UTC (07:00 America/Sao_Paulo), mais
execução manual.** A missão propôs 2/dia; abaixo o porquê de reduzir:

- A granularidade dos dados é diária. `backlog.updated_at` muda quando alguém
  edita; `execution_plans.approved_at` é evento raro (25 em 4 semanas); o drift
  de conhecimento se move em dias. Uma segunda execução vespertina olharia o
  mesmo estado e, pela deduplicação, entregaria zero achado — treinando o
  Cláudio a ignorar a mensagem.
- **A camada rápida já existe.** `agents_healthcheck` roda a cada 5 min e
  `healthcheck_api.sh` também, ambos com Telegram. O Supervisor não é o caminho
  rápido e não deve fingir que é.
- O critério de sucesso é 1 achado útil por semana. Dobrar a cadência dobra a
  chance de fadiga sem dobrar o sinal.

```ini
# workdev-supervisor.timer
[Timer]
OnCalendar=*-*-* 10:00:00
Persistent=true
RandomizedDelaySec=120
```

`Persistent=true` para que um reboot às 09:55 não pule o dia. Execução manual:
`apps/api/venv/bin/python -m scripts.supervisor --once`. Reavaliar para 2×/dia só se, após 3 semanas, a
execução única estiver consistentemente cheia (≥3 achados novos por dia).

---

## 10. Observabilidade

Uma linha `chave=valor` por campo no stdout (mesmo formato do `ingestor.py`,
capturada pelo journald via `SyslogIdentifier=workdev-supervisor`), **e** uma
linha JSON por execução em `/var/lib/workdev-supervisor/runs.jsonl`.

```
started_at=2026-08-16T10:00:00Z
finished_at=2026-08-16T10:00:07Z
duration_seconds=7.412
checks_executed=5
checks_failed=0
checks_degraded=0
facts_detected=31
facts_after_dedup=6
new_findings=4
worsened_findings=1
persistent_findings=25
resolved_findings=1
reported_findings=3
llm_calls=1
llm_failures=0
llm_model=claude-opus-5
llm_input_tokens=6912
llm_output_tokens=1840
llm_invalid_ids=0
delivery=telegram:ok
status=ok
```

`status ∈ {ok, degraded, failed}`. Exit code: `0` para `ok`/`degraded`, `1` para
`failed` — e o unit ganha `OnFailure=` apontando para um oneshot que manda uma
linha ao Telegram. Sem isso o Supervisor repete o defeito que ele existe para
detectar: falhar em silêncio.

**Segredos.** `redacao.py` roda sobre todo texto que entra em Fato, no payload
do LLM e no relatório, com fail-closed: padrões `sk-[A-Za-z0-9-]{16,}`,
`sk-or-v1-`, `sk-ant-`, `eyJ[A-Za-z0-9_-]{10,}`, `sb_secret_`, `sb_publishable_`,
`postgres(ql)?://[^@]+@`, `bot\d{6,}:[A-Za-z0-9_-]{30,}` → substituídos por
`[REDIGIDO]`. Nenhum check lê conteúdo de `.env`, nenhum imprime connection
string, nenhum inclui corpo de documento (só título e caminho).

---

## 11. Persistência

**Fase 1 (MVP): arquivos, sem migration.**

```
/var/lib/workdev-supervisor/
├── state.json     # dedup, mapa fingerprint → registro (escrita atômica)
└── runs.jsonl     # 1 linha por execução, append, rotacionado em 90 dias
```

Motivos, em ordem de peso:

1. **Torna o "somente leitura" literal.** O Supervisor abre uma única conexão
   com o Postgres do WorkDev, em modo read-only, e nunca escreve nele. Não há
   bug de supervisor capaz de corromper dado da plataforma. Com tabelas
   próprias, essa garantia vira "ele só escreve nas tabelas dele" — mais fraca.
2. **A missão proíbe migration nesta fase**, e o padrão já existe e funciona
   (`agents-healthcheck/status.json`).
3. **Rollback trivial:** `rm -rf /var/lib/workdev-supervisor`.
4. O volume é irrisório: ~50 achados ativos, ~365 execuções/ano.

**Fase 2 (só se o MVP passar no critério de 3 semanas):** tabelas
`supervisor_runs` e `supervisor_findings` via Alembic, com o mesmo schema dos
dataclasses. Elas só se justificam quando houver UI ou consulta histórica —
antes disso são custo sem uso. O esquema fica pré-desenhado abaixo, **para
referência, não para aplicar:**

```
supervisor_runs(id uuid pk, started_at, finished_at, duration_ms int,
                status, checks_executed int, facts_detected int,
                new_findings int, persistent_findings int, resolved_findings int,
                llm_model text, llm_calls int, llm_failures int, metrics jsonb)

supervisor_findings(id uuid pk, run_id uuid fk, fingerprint text,
                    check text, subcheck text, severity text, status text,
                    entity_type text, entity_id text, project_id uuid null,
                    titulo text, medidas jsonb, evidencia jsonb,
                    prioridade int null, impacto text, risco text,
                    recomendacao text, acao_sugerida text,
                    first_seen_at, last_seen_at, ocorrencias int)
                    -- unique(fingerprint) parcial onde status <> 'resolvido'
```

Reuso considerado e descartado: gravar achados em `knowledge` (é escrita na
plataforma, e polui a base com ruído operacional) e criar tasks no `backlog`
(é ação, viola Nível 0, e é justamente o que o MCP faz).

---

## 12. Segurança

- **Conexão read-only por construção.** Ambas as conexões abrem com
  `options="-c default_transaction_read_only=on"` no DSN. Um `INSERT` acidental
  levanta `ReadOnlySqlTransaction` — é teste de aceite, não confiança.
- **Proposta opcional (exige aprovação, não incluída no MVP):** role
  `workdev_supervisor` com `GRANT CONNECT` + `GRANT SELECT` apenas nas tabelas
  necessárias. Recomendado, mas é alteração de banco — fica como item separado
  para o Cláudio decidir. Sem ele, o `default_transaction_read_only` já é a
  defesa efetiva.
- **Nenhum comando destrutivo.** A lista de comandos externos é fechada e
  auditável: `git status/rev-list/log`, `systemctl show/is-active`, `ss -tlnp`,
  `curl` local. Sem `shell=True`, sem interpolação de string em comando.
- **O LLM não tem tools.** Nenhuma. `acao_sugerida` é texto para humano ler.
- **O Supervisor não fala com agentes.** Não escreve em tmux, não chama
  `workdev_agent.py`, não usa o MCP `workdev-backlog` (que é caminho de escrita).
- **Nenhum segredo persistido.** `state.json` e `runs.jsonl` contêm só
  identificadores e números. Chaves só existem em memória, lidas do `.env`.

---

## 13. Integração futura com a UI

**Recomendação única para começar: Telegram, reusando `/opt/scripts/alerta.env`.**

Motivos: o canal já existe e já é o que o Cláudio lê; o terminal de trabalho é
mobile; entrega zero linha de frontend; e o formato de ≤3 achados cabe numa
mensagem. Formato:

```
🔎 WorkDev Supervisor — 16/08 07:00

1. [CRÍTICO] AUDITS BPF — 5 tasks critical paradas há 10 dias
   Impacto: … | Ação sugerida: …
2. [ALTO] WorkDev Core — 2 scripts rodando em produção sem commit
3. [ALTO] Conhecimento — 104 registros do Postgres fora do RAG

✅ resolvido: 1   ● persistentes: 25 (3 crit)
```

Caminho posterior, quando e só quando o MVP provar valor:

1. `GET /api/supervisor/latest` — endpoint **somente leitura** que serve o
   `runs.jsonl` mais recente + `state.json`, autenticado pelo `X-API-Key`
   existente. ~40 linhas.
2. Card na Dashboard (`apps/web/src/pages/Dashboard.tsx`), no mesmo padrão dos
   cards de deploys e providers que já existem ali: contagem por severidade +
   os 3 títulos.
3. Aba `/supervisor` só se o card ficar pequeno demais.

**Descartados para o MVP:** painel no AI Hub (misturaria leitura de supervisão
com um chat que tem tools de escrita — má fronteira), e-mail, e qualquer coisa
que exija build do frontend.

---

## 14. Riscos

| # | Risco | Probabilidade | Mitigação |
| --- | --- | --- | --- |
| 1 | **Avalanche no dia 1** — 179 itens de backlog e 104 registros fora do RAG geram dezenas de achados e o Cláudio desliga na primeira semana | **alta** | modo `--seed`: primeira execução grava tudo como `persistente` e **não notifica**. Só o que aparecer depois é `novo`. Sem isso o MVP morre no dia 1. |
| 2 | Ruído por dados sujos (`Alta`/`High`, `owner` nulo, `done` usado como "descartado") | alta | normalização de prioridade; `owner` não é sinal; limiares conservadores (`high` só a partir de 21 dias) |
| 3 | Drift crônico vira alarme permanente (`main` 43 commits atrás é o estado normal deste repo) | alta | fingerprint por *bucket*: o estado crônico vira `persistente` na primeira execução e some do relatório |
| 4 | **O Supervisor falha em silêncio** e vira mais um sistema não monitorado | média | exit code ≠ 0 + `OnFailure=` no systemd; e o relatório do dia seguinte abre com "execução anterior falhou" |
| 5 | LLM inventa fato ou rebaixa severidade | média | validação de `fato_id`; severidade nunca vem do LLM; modo degradado entrega o relatório sem prosa |
| 6 | Postgres do RAG (5433) fora do ar → falso "104 documentos sumiram" | média | check retorna `indisponivel` e a execução vira `degraded`; nunca marca ausência |
| 7 | Achados verdadeiros mas sem ação possível (falta tempo, não informação) | **média-alta** | é o risco de fundo do produto — endereçado pelo critério de desligamento em 3 semanas, não por engenharia |
| 8 | Custo de LLM cresce sem ninguém notar | baixa | tokens e custo estimado no log de toda execução |
| 9 | `git` num estado estranho (rebase/merge em andamento) quebra o reader | baixa | `check=False` em todo subprocess + timeout de 10s; erro do reader → check `degraded`, não `failed` |

---

## 15. Rollback

Três níveis, todos sem efeito colateral — consequência direta de o MVP ser
somente leitura e guardar estado em arquivo.

1. **Parar:** `systemctl disable --now workdev-supervisor.timer`.
   Nada mais acontece. Nenhum dado da plataforma foi tocado, então não há o que
   reverter.
2. **Zerar a memória:** `rm -rf /var/lib/workdev-supervisor`.
   Próxima execução recomeça do `--seed`.
3. **Remover:** `git revert` do commit + `rm` dos units.
   **Zero migrations para desfazer. Zero linhas para apagar em qualquer tabela
   do WorkDev.**

Não há rollback parcial necessário: um check com defeito é desligado
individualmente por `CHECKS_ATIVOS` em `config.py`, sem tocar no resto.

---

## 16. Etapas de implementação

| # | Etapa | Entrega verificável | Esforço |
| --- | --- | --- | --- |
| E0 | Esqueleto: pacote, `config.py`, `modelo.py`, `redacao.py`, CLI | `apps/api/venv/bin/python -m scripts.supervisor --once` roda e imprime `status=ok` com 0 checks | 1h |
| E1 | Readers do Postgres (read-only) + `critical_stalled` + `plan_without_execution` | `--json` imprime Fatos reais; teste de read-only passa | 3h |
| E2 | `estado.py`: fingerprint, buckets, transições, `--seed` | rodar 2× seguidas → 2ª execução com `new_findings=0` | 2h |
| E3 | `deploy_drift` + `knowledge_drift` + `agent_health` | os 5 checks produzindo Fatos; RAG derrubado → `degraded` | 4h |
| E4 | `llm.py`: chamada única, schema, validação, modo degradado | sem `ANTHROPIC_API_KEY` o relatório sai mesmo assim | 2h |
| E5 | `relatorio.py` + `entrega.py` (Telegram) + units systemd + `OnFailure` | mensagem chega ao Telegram; timer agendado | 1,5h |
| E6 | Observabilidade completa + suíte de testes | as 11 métricas obrigatórias no log; retenção de 90 dias; `pytest` verde; varredura de segredo limpa | 2h |
| E7 | **Semana de sombra** — roda diário, entrega só ao Cláudio, mede ruído | 7 dias de `runs.jsonl` para calibrar limiares | 1 semana |

Implementação: **~15,5 horas**. Avaliação: 1 semana de sombra + 3 semanas de
critério de sucesso.

Ordem inegociável: **E2 antes de E5.** Entregar notificação antes de ter
deduplicação garante que a primeira semana seja um despejo diário de 100 itens
repetidos.

---

## 17. Critérios de aceite

1. `apps/api/venv/bin/python -m scripts.supervisor --once --dry-run` conclui em **< 60s** e não escreve
   em disco nem chama o LLM.
2. Um `INSERT` na conexão do Supervisor levanta `ReadOnlySqlTransaction`.
   (Teste automatizado, não inspeção.)
3. `--seed` na primeira execução real: `new_findings=0`, `delivery=skipped`.
4. Nenhum relatório entrega mais de 3 achados completos, exceto `critical`.
5. Duas execuções consecutivas sem mudança nos dados → 2ª com `new_findings=0`.
6. `docker stop` no Postgres do RAG → execução termina `status=degraded`,
   exit 0, com os outros 4 checks completos.
7. `ANTHROPIC_API_KEY` ausente → relatório determinístico entregue,
   `llm_failures=1`, `status=degraded`.
8. `grep -rE 'sk-|sk-ant-|eyJ|sb_secret|postgres://' /var/lib/workdev-supervisor
   /var/log/…` retorna **0 linhas**.
9. As 11 métricas obrigatórias presentes em toda linha de `runs.jsonl`
   (lista em `config.METRICAS_OBRIGATORIAS`; `duration` do enunciado é
   registrado como `duration_seconds`).
10. `kimi=offline` e `qwen=offline` não produzem nenhum achado.
11. Nenhuma escrita em `backlog`, `execution_plans`, `agent_runs`,
    `graph_nodes`, RAG, tmux ou MCP — verificado por revisão do diff e pelo
    teste (2).

---

## 18. Testes

Estratégia: **separar SQL de lógica.** Cada check é `f(linhas: list[dict]) -> list[Fato]`.
A query vive num módulo de reader. Isso permite testar 90% da lógica sem banco.

| Suíte | Casos |
| --- | --- |
| `test_checks_puros` | fixtures sintéticas por check: limiar exato, prioridade `Alta`/`High`, projeto `Suspended` ignorado, task `done` com plano aprovado não dispara, `run_stalled` só com status ativo |
| `test_fingerprint` | mesmo fato → mesmo hash; 8→9 dias → mesmo hash; 14→15 dias → hash diferente + `agravado`; bucket melhor → `melhorou` |
| `test_estado` | novo→persistente→resolvido→expirado; reforço aos 14 dias; escrita atômica sobrevive a `state.json` corrompido (reinicia vazio, não explode) |
| `test_ruido` | 10 fatos → 3 achados; 4 críticos → 4 achados; resolvidos não contam no limite |
| `test_llm` | cliente falso: resposta válida; `fato_id` inventado é descartado e contado; exceção → fallback determinístico; schema inválido → fallback |
| `test_redacao` | `sk-ant-…`, JWT, DSN com senha, token de bot → `[REDIGIDO]`; string legítima não é mutilada |
| `test_readonly` (integração) | conexão real, `INSERT` levanta erro; todas as queries executam com `LIMIT 0` e retornam as colunas esperadas |
| `test_agent_health` | `status.json` velho → `supervisao_parada`; kimi offline → nada; kimi `blocked/billing` → achado |

Rodam pelo mesmo caminho já usado: `apps/api/venv/bin/python -m pytest`.
Testes de integração marcados com `@pytest.mark.integracao` para poderem ser
excluídos onde não houver banco.

---

## 19. Estimativa de complexidade

**Média-baixa.** ~900–1200 linhas de Python, ~400 de teste.

Por quê é baixa: nenhuma migration, nenhuma dependência nova, nenhum serviço
novo (um oneshot + timer), nenhuma UI, nenhuma escrita, uma única chamada de LLM
sem loop de agente, e reuso do venv, do canal de alerta e do formato de log.

Onde está a complexidade real, em ordem: (1) calibrar limiares e buckets para
não afogar em ruído — resolvido empiricamente na semana de sombra, não no
design; (2) normalização de títulos no `knowledge_drift`; (3) leitura de git em
estados incomuns.

---

## 20. Respostas às cinco perguntas

### O que NÃO devemos construir agora

Interface web. Tabelas no Postgres. Qualquer ação corretiva, mesmo com
aprovação. Tools de escrita para o LLM. Um segundo healthcheck de agentes.
CI/CD de verdade. Agente autônomo. Integração com o Engineering Graph do
Supabase (já é pendência conhecida, os enums podem não aceitar os tipos e ele
falha graciosamente — não é base para construir em cima). Checks sobre os outros
projetos (Feed_BPF, Agro RC, AUDITS): o MVP olha o WorkDev, e as tasks desses
projetos aparecem só porque vivem no backlog do WorkDev. Busca semântica no RAG
para "enriquecer" achados — o Supervisor compara metadados, não conteúdo.

### Que partes do Supervisor já existem

Mais do que parece, e é por isso que o MVP é pequeno:

- **`agent_health` já existe inteiro.** `agents_healthcheck.py` faz detecção,
  classificação, recuperação, estado em JSON, alerta Telegram e anti-spam. O
  Supervisor **consome** o `status.json` e aplica política. Escrever qualquer
  linha de tmux nele seria duplicação pura.
- **Parte do `deploy_drift`:** `verificar-deploy.sh` já checa árvore suja,
  escopo e órfão na 8000. O que falta é o subconjunto ficar disponível sem rodar
  `pnpm build`.
- **Anti-spam:** `healthcheck_api.sh` tem o padrão (janela de 6h, arquivo de
  estado). A supressão do Supervisor é a mesma ideia com granularidade por
  fingerprint.
- **Formato de log de execução:** `ingestor.py` já emite `started_at`,
  `finished_at`, `duration_seconds`, contagens e `status` — o formato pedido na
  missão já é padrão da casa.
- **Máquina de estados de plan/run:** `app/services/handoff.py` (`RUN_TRANSITIONS`,
  `ACTIVE_RUN_STATUSES`) é a fonte de verdade; o check importa, não copia.
- **Canal de entrega:** `/opt/scripts/alerta.env`.
- **Fatos brutos:** `/api/system/migrations`, `/api/monitoring/status`,
  `/api/deployments/status`.

O que **não** existe, e é a razão do projeto: a camada que correlaciona essas
fontes e decide o que merece atenção. Hoje cada peça sabe do seu pedaço e
ninguém junta.

### Onde existe risco de duplicação arquitetural

1. **`agent_health` virar um segundo healthcheck.** Maior risco do projeto.
   Regra: `agents.py` só faz `json.loads` de um arquivo. Zero `subprocess`.
2. **`deploy_drift` virar um segundo `verificar-deploy.sh`.** Mitigação de curto
   prazo: reimplementar só o subconjunto read-only e registrar a dívida.
   Longo prazo: extrair para módulo comum.
3. **Reimplementar a máquina de estados de planos/runs.** Importar de
   `handoff.py`.
4. **`supervisor_findings` competindo com `backlog`.** O Supervisor nunca cria
   task. Isso é escrita e é papel do MCP/AI Hub.
5. **Terceiro store de conhecimento.** O Supervisor detecta drift entre
   Postgres, RAG e disco — ele não pode virar o quarto lugar onde a informação
   mora. Por isso o estado guarda só fingerprints e números.
6. **Segundo canal de alerta.** Mesmo `alerta.env`, mesmo bot.

### Qual é a menor versão que já gera valor

**E1 + E2, sem LLM e sem Telegram.** Dois checks (`critical_stalled` e
`plan_without_execution`), deduplicação, saída no terminal:

```
cd /opt/workdev
apps/api/venv/bin/python -m scripts.supervisor --once --json
```

~5 horas. Já responde "o que está parado, há quanto tempo, e há plano aprovado
para isso?" — pergunta que hoje exige três queries manuais e que ninguém faz.
Se essa versão não for consultada na primeira semana, as outras 10 horas não
salvam o projeto e o resto não deve ser construído.

### Existe alguma razão forte para não construir este MVP

Existe uma, e é honesta: **os problemas que os checks apontam já são
conhecidos.** Os 7 críticos parados, o Feed_BPF indo pra fábrica em 18/08, o
`main` estagnado — nada disso está parado por falta de visibilidade. Está parado
por falta de tempo. Um supervisor não cria tempo, e o risco real é ele virar
mais uma notificação diária que se aprende a ignorar.

Contra-argumento, medido nesta própria investigação — três divergências que
**não** eram conhecidas e que nenhuma fonte isolada mostraria:

1. Os **19 ADRs e 85 registros de conhecimento** do Postgres estão 100% fora do
   RAG. Quem pergunta ao RAG recebe uma base que não sabe da maior parte do que
   foi decidido.
2. `backlog.md` — que **é** o que o RAG indexa — está 95 itens defasado.
3. Se o `workdev-agents-health.timer` parar, **nada no sistema detecta**. O
   `status.json` congela e o silêncio é indistinguível de "tudo bem". É
   exatamente a classe de falha registrada no ADR de `EXCEPTION WHEN OTHERS`,
   uma camada acima.

E há um quarto, visível agora: dois scripts estão **rodando em produção sem
commit**, e três commits só existem nesta VPS.

Nenhum desses aparece olhando uma fonte por vez. É o que o Supervisor faz.

**Portanto: PLANO RECOMENDADO**, com três condições inegociáveis:

1. `--seed` na primeira execução (sem isso o dia 1 mata o projeto);
2. deduplicação (E2) implementada **antes** da entrega (E5);
3. o critério de desligamento em 3 semanas escrito no `config.py` como
   comentário e cobrado — se não render **1 achado novo e útil por semana**,
   desligar sem cerimônia. Um supervisor que ninguém lê é pior que nenhum:
   consome atenção e dá falsa sensação de cobertura.
