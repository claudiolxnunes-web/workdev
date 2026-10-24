# Renomear agente cli `qwen` para `openrouter`

**Data:** 2026-10-01
**Status:** proposto
**Projetos afetados:** WorkDev Core

## Contexto

O agente CLI atualmente identificado pelo slug `qwen` deixou de ser exclusivo do
modelo Qwen. Seu catálogo OpenRouter agora inclui:

- `qwen/qwen3.5-397b-a17b`
- `deepseek/deepseek-v4-flash`
- `x-ai/grok-4.7`

Além disso, os modelos Kimi (`moonshotai/kimi-k2.7-code` e
`moonshotai/kimi-k2.6`) foram recentemente movidos para o agente `kimi`,
corrigindo um vazamento semântico. Resta agora o próprio nome do agente, que
ainda sugere algo específico da família Qwen enquanto funciona como gateway
OpenRouter genérico.

Na interface essa inconsistência já foi parcialmente endereçada com o rótulo
aberto: **"OpenRouter (Qwen / DeepSeek / Grok)"**. Mas no banco, nas
políticas de review, nos scripts de lançamento e nas migrations o slug `qwen`
persiste, gerando confusão técnica e operacional.

## Decisão

Renomear o slug interno do agente de `"qwen"` para `"openrouter"` em todo o
ecossistema WorkDev Core.

Ações necessárias:

1. **Catálogo e seleção de modelos**
   - `apps/api/app/services/cli_agent_models.py`: substituir chave `qwen` por
     `openrouter` no dicionário `MODELS` e em `DEFAULTS`.
   - Atualizar função `launcher()` para reconhecer `agent == "openrouter"` e
     injetar `QWEN_PROVIDER=openrouter` / `QWEN_MODEL=<model>` (mantendo o nome
     das variáveis por compatibilidade com o executável `qwen` existente).

2. **Banco de dados**
   - Nova migration para atualizar `ai_model_catalog.agent_slug` de `"qwen"`
     para `"openrouter"`.
   - Garantir reversibilidade da migration para rollback seguro.

3. **Roteamento e handoff**
   - `apps/api/app/services/handoff.py`: lista de `AGENTS`.
   - `apps/api/app/routers/handoffs.py`: fallback `model = selected("qwen")`
     passa a `selected("openrouter")`.
   - `apps/api/app/routers/terminal.py`: `AGENT_SESSION_NAMES`,
     `STANDBY_COMMANDS`, `_PROCESS_LABELS`, fallback de `model` para runs
     antigas.

4. **Políticas e recomendação**
   - `apps/api/app/services/review_policy.py`: `trusted_agents` e tier
     `economic`.
   - `apps/api/app/services/agent_recommendation.py`: catálogo de agentes,
     labels e fatores de custo.

5. **Frontend**
   - `apps/web/src/services/handoff.service.ts`: `CliAgentName`,
     `CLI_AGENTS`, `SelectableCliAgent` e `agentLabels`.
   - `apps/web/src/modules/agents/AgentsPage.tsx`: lista e label (passa a
     "OpenRouter" simples).
   - `apps/web/src/components/ai-hub/PlanningPanel.tsx`: referências ao slug
     e chamadas `getCliAgentModel("qwen")`.
   - `apps/web/src/components/settings/tabs/AIProvidersTab.tsx`: mapeamento de
     labels.

6. **Scripts e infraestrutura**
   - `scripts/start_qwen_agent.sh`: renomear para `scripts/start_openrouter_agent.sh`
     ou manter nome por conveniência e ajustar somente a documentação?
     **Sugestão:** manter o nome do arquivo para não quebrar chamadas externas e
     scripts legados; ajustar comment/header.
   - `scripts/agents_healthcheck.py`, `scripts/configure_agent_transcripts.py`,
     `scripts/workdev_agent.py`, `scripts/supervisor/config.py`.
   - `config/review-policy.json`.

7. **Testes**
   - Atualizar todos os testes que usam o slug `"qwen"` como agente.
   - Garantir testes de compatibilidade: runs históricas com `agent="qwen"`
     continuam carregáveis e visíveis.

8. **Migrations legadas**
   - Migrations anteriores que referenciam `agent_slug = 'qwen'` (ex:
     `a2f6d8c91b04`, `c7f21a9d4e05`) **não serão alteradas**, pois já
     representam o estado do banco no momento em que foram aplicadas. A nova
     migration assume a correção do estado atual.

## Alternativas consideradas

1. **Manter slug `qwen` e melhorar só os labels.**
   - *Prós:* quase zero risco, não toca em banco/scripts/políticas.
   - *Contras:* dívida técnica permanece; modelos DeepSeek/Grok continuam
     sendo executados por um agente cujo slug indica Qwen; dificulta
     manutenção e novos integradores.

2. **Criar agentes separados (`qwen`, `deepseek`, `grok`) ao invés de um
   OpenRouter genérico.**
   - *Prós:* cada modelo teria sua própria sessão e configuração independente.
   - *Contras:* multiplica processos idle, aumenta complexidade do handoff e
     não reflete a arquitetura atual de "agente = runtime de CLI" com
     múltiplos modelos dentro.

3. **Renomear para `openrouter` (escolhida).**
   - *Prós:* o nome reflete a realidade funcional; resolve a confusão do
     usuário e simplifica documentação; mantém a arquitetura atual.
   - *Contras:* alto número de arquivos alterados; exige coordenação com
     deploy e migrations; requer validação de que histórico com `agent="qwen"`
     continua acessível.

## Consequências

- Todos os locais que consomem `agent` como slug precisam ser revisitados
  (inclusive relatórios, dashboards e scripts de healthcheck).
- O campo `Run.agent` no banco pode passar a armazenar `"openrouter"`; runs
  antigas com `"qwen"` precisam ser tratadas como equivalentes em leitura.
- A URL/execução do agente CLI (`qwen` via `scripts/start_qwen_agent.sh`)
  pode ser mantida para reduzir atrito operacional.
- Documentação em `docs/perfil/03-infraestrutura.md` deve ser atualizada para
  refletir o novo slug.

## Verificação proposta

- `pytest tests/test_cli_agent_models.py tests/test_openrouter_agent.py
  tests/test_agent_recommendation.py tests/test_fleet_preferences.py
  tests/test_handoff.py tests/test_review_policy.py` passando.
- `pnpm test` no frontend passando.
- `alembic upgrade head` aplicando sem erro e populando
  `ai_model_catalog.agent_slug = 'openrouter'`.
- Dashboard de agentes mostrando execuções históricas `qwen` e atuais
  `openrouter` no mesmo painel.
