# ADR 004 — Separar PLAN no AI Hub e BUILD nos Agents

- Status: aceito
- Data: 2026-07-21
- Projeto: WorkDev Core

## Contexto

O AI Hub já consultava e alterava backlog, subtasks e Knowledge, enquanto a área
Agents expunha os terminais tmux de Codex e Claude Code. Não existia, porém, um
contrato persistente entre planejamento e execução. O contexto era transferido
manualmente, sem versão de plano, aprovação ou trilha de execução.

## Decisão

O WorkDev passa a ter dois estágios com responsabilidades explícitas:

1. **PLAN — AI Hub:** cria plano versionado, critérios de aceite, validações,
   restrições e ADRs. Não executa shell, código ou deploy.
2. **BUILD — Agents:** recebe somente um plano aprovado, executa no ambiente real
   e registra início, progresso, bloqueio, revisão e conclusão.

O PostgreSQL do WorkDev é a fonte oficial. `execution_plans`, `agent_runs` e
`agent_run_events` preservam o contrato e a auditoria. O Engineering Graph no
Supabase recebe projeções compatíveis com os enums existentes
(`AIConversation`, `Task` e `Monitoring`), usadas para atualização em tempo real;
os tipos de domínio continuam sendo Plan, AgentRun e AgentEvent no PostgreSQL e
na API. Polling periódico permanece como fallback.

## Máquina de estados

Planos: `draft → approved`, com `needs_revision` e `superseded`.

Execuções: `queued → running → review → completed`. Uma execução pode passar por
`blocked`, voltar a `running`, ou terminar em `failed`/`cancelled`.

## Segurança

- O envio ao BUILD exige aprovação explícita.
- Conteúdo do plano nunca é concatenado a comandos de shell.
- Secrets permanecem no backend e não entram no prompt.
- A CLI local autentica na API sem imprimir a chave.
- Divergência arquitetural bloqueia o BUILD e retorna ao PLAN.

## Consequências

Há rastreabilidade entre task, plano e execução, e Codex/Claude/Kimi compartilham
o mesmo contrato. O custo adicional é manter estados e eventos consistentes; por
isso transições inválidas são recusadas pela API e estados finais são imutáveis.

## Evolução AUTO v2 — 2026-08-30

Depois da aprovação do PLAN, `routing_mode=auto` classifica semanticamente a task,
o plano e as subtasks reais, seleciona agente/modelo pelo catálogo e inicia um
runtime isolado `auto-<agent>-<run_id>`. Restrições e negações locais não contam
como ações críticas.

Modelos sem confirmação são preferidos quando atingem a capacidade mínima. Se
somente modelos premium atenderem, a API responde
`premium_confirmation_required` com uma recomendação estruturada. A confirmação
autoriza apenas o custo; agente e modelo continuam sendo escolhidos pelo AUTO.

O contexto segue o schema estrito `auto-runtime.v2`, incluindo task, PLAN e
subtasks ordenadas pelo vínculo `backlog_id`. Uma conclusão AUTO só é persistida
com resultado e depois que a sessão daquela run foi encerrada e o standby do
agente foi confirmado. Um monitor com timeout falha runtimes que desaparecem ou
excedem o prazo, sem tocar em sessões de outras execuções.

## Recomendação consultiva — 2026-08-30

O WorkDev deixou de decidir e iniciar agente/modelo automaticamente como caminho
principal. O fluxo passa a ser: Task → Subtasks → PLAN → **recomendação** →
decisão do usuário → envio manual ao agente escolhido, entre os cinco
configurados (Claude Code, Codex, Kimi Code, Qwen Code, Gemini).

`GET /api/handoffs/plans/{id}/recommendation` devolve agente e modelo sugeridos,
complexidade, motivo curto, custo relativo, disponibilidade e uma alternativa.
Não cria execução, não inicia runtime e não desabilita nenhum agente — o usuário
pode ignorá-la.

A recomendação reaproveita o que já existia: `classify_task` continua sendo o
único classificador de complexidade, `describe_workload` apenas descreve o tipo
de trabalho a partir dos mesmos marcadores, e a seleção de modelo usa o mapa
provider→agente, a cobertura de capacidades e o preço do `agent_router`.

Ordem dos critérios: adequação ao tipo de trabalho, complexidade, custo e
disponibilidade. Entre modelos tecnicamente suficientes vence o mais barato, mas
custo nunca supera capacidade — um modelo que não atinge a cobertura mínima da
complexidade é marcado como inadequado em vez de ser sugerido por ser barato.

Preço e categoria vêm sempre do `ai_model_catalog`; não há preço no código. A
fronteira econômico/moderado é a mediana dos modelos que o próprio catálogo
classificou como `economic`.

Disponibilidade usa apenas o que o WorkDev consegue conferir: modelo ativo no
catálogo e estado real da sessão do agente. Quando a sonda falha, o estado é
"não verificada", nunca "disponível". Cota é reportada como esgotada só quando
existe erro real registrado em `agent_runs` ou `ai_call_logs`; sem esse sinal a
disponibilidade financeira fica "não verificada". O WorkDev não estima saldo,
créditos ou tokens restantes, e não autoriza custo premium sozinho.

### Papel do tmux

O tmux é o terminal persistente e manual dos agentes, com isolamento estrito de
uma sessão por agente configurado. Ele não é mecanismo de orquestração: o botão
"Enviar em AUTO" saiu da aba de PLAN e a criação dinâmica de runtime
`auto-<agent>-<run_id>` passou a exigir opt-in explícito via
`WORKDEV_AUTO_RUNTIME_ENABLED`. Desligada (padrão), uma execução AUTO ainda
classifica, roteia e enfileira — o agente a recolhe pela CLI, na sua sessão de
sempre. Todo o backend do AUTO v2 (classificação semântica, subtasks reais,
erros estruturados, lifecycle e isolamento de sessão) permanece intacto e não
foi expandido.

## Modelo é decisão prévia por agente, nunca por envio — 2026-10-24

A tela de planos (PLAN → BUILD) deixa de oferecer qualquer seletor de modelo —
inclusive no bloco de recomendação, que continua mostrando o modelo sugerido
só como texto. O operador escolhe ali apenas **quem** (executor, revisor
opcional, observer opcional), nunca **qual modelo**. O modelo de cada agente
de CLI (Claude, Codex, Kimi, Qwen, Grok, DeepSeek, Gemini) é decidido antes,
na aba Agentes (`GET/PUT /api/cli-agent-models/{agent}`), e vale para toda run
nova até ser trocado ali — nunca por envio.

Isso formaliza o que já estava implícito em "Recomendação consultiva": o
WorkDev pode sugerir agente e modelo, nunca decidir quem executa ou qual
modelo roda. A decisão de agente, revisor e modelo é sempre e exclusivamente
do operador — soberana, sem hierarquia de qualidade entre agentes.

No envio, o backend resolve o modelo do executor e, quando houver, do revisor
pela configuração salva na aba Agentes (mesmo contrato, sem catálogo
paralelo); registra agente, provider e modelo efetivamente usados no evento
`build.queued` da run. Observer é exceção deliberada: não tem configuração na
aba Agentes, então mantém seletor próprio na tela de planos, sem mudança.

Configuração ausente, incompatível (fora do catálogo do agente) ou
indisponível (sessão viva rodando outro modelo, sem o procedimento de
reinício) **bloqueia o envio com erro claro — nunca substitui o modelo em
silêncio nem deixa passar como aviso.** Uma tentativa de revisão transformou
esses bloqueios em avisos que deixavam o envio seguir mesmo assim
(`feat(handoff): escolhas do operador viram alertas, nunca bloqueios`); foi
revertida por contrariar esta decisão.

Exceção preservada, fora do escopo desta decisão: chamadas diretas e legadas
da API (fora da tela de planos) que informam `model` explícito no payload
continuam sem checar a sessão viva — comportamento anterior a esta mudança,
usado por scripts e integrações que dependem dele de propósito. A tela de
planos nunca envia modelo explícito para agentes de CLI, então não é afetada.

### Verificação

```bash
# nenhum seletor de modelo na tela de planos
grep -c "Modelo do executor\|Modelo do revisor" apps/web/src/components/ai-hub/PlanningPanel.tsx  # 0

# executor e revisor resolvem pela aba Agentes; revisor bloqueia por sessão viva
cd apps/api && WORKDEV_API_ENV_FILE=/tmp/test.env venv/bin/python -m pytest \
  tests/test_executor_model_resolution.py -q
```
