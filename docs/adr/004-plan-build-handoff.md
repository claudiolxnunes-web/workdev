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

As escolhas do operador (agentes e modelos) prevalecem: o envio **nunca é
bloqueado nem tem o modelo trocado** por causa delas. Sessão viva rodando outro
modelo, modelo fora da lista permitida em Settings e modelo fora do catálogo da
CLI geram **alerta** (`build.warning` na run e `warnings` na resposta; a tela de
planos mostra "Alerta: …") e o envio segue com a escolha. Continua bloqueando só
o que não dá para executar: seleção salva que saiu do catálogo (erro claro, sem
substituir o modelo em silêncio), revisor sem canal de veredito e runtime
indisponível. Regra do operador (2026-10-24): "o sistema só pode sugerir e
alertar".

Chamadas diretas e legadas da API que informam `model` explícito no payload
seguem aceitas como antes; a tela de planos nunca envia modelo para agentes de
CLI.

### Verificação

```bash
# nenhum seletor de modelo na tela de planos
grep -c "Modelo do executor\|Modelo do revisor" apps/web/src/components/ai-hub/PlanningPanel.tsx  # 0

# executor e revisor resolvem pela aba Agentes; sessão divergente só alerta
cd apps/api && WORKDEV_API_ENV_FILE=/tmp/test.env venv/bin/python -m pytest \
  tests/test_executor_model_resolution.py -q
```

## Esforço por agente e vigia do healthcheck — 2026-10-24

Complementa a decisão acima ("modelo é decisão prévia por agente"); mesma regra,
agora também para esforço de raciocínio e saúde dos agentes.

- **Esforço é escolha prévia por agente**, salvo na aba Agentes junto do modelo
  (`PUT /api/cli-agent-models/{agent}/effort`) e vale no próximo "Ligar". Só é
  injetado onde a CLI tem mecanismo comprovado: `claude --effort`,
  `codex -c model_reasoning_effort`, `kimi KIMI_MODEL_THINKING_EFFORT`. Gemini,
  Qwen, Grok e DeepSeek não oferecem o seletor; sem escolha, a CLI usa o padrão
  dela. Nunca é decidido por envio nem pelo sistema (9891146).
- **Healthcheck mantém os sete agentes de CLI ligados** (antes só Claude e
  Codex). A recuperação automática respeita a intenção OFFLINE (desligar pela
  aba Agentes), com 3 tentativas e backoff de 5 min (c7b620b).
- **Healthcheck vigia memória disponível**: alerta no Telegram (baixa < 6 GB,
  crítica < 3 GB, swap > 8 GB, após 120 s) e sai com exit 1 se crítica ou se não
  conseguir medir (4e6be40). Motivo: 31 GB sem GPU dividem RAM com modelos
  locais e as sessões dos agentes.
- **Decisão do operador reafirmada:** planos e agentes são sempre escolha do
  operador; o sistema só sugere e alerta, nunca bloqueia nem troca em silêncio.

Estado em 2026-10-24: branch `feat/backlog-archived` verde (build, eslint,
1656 testes), aguardando push por root e abertura de PR.

## Task a4059dd7 (execução 0139fd5b): itens do plano v1 superados — 2026-10-24

O plano v1 da task "Centralizar modelos em Agentes e simplificar os planos" previa
comportamentos que contradizem a decisão do operador já registrada acima. Por decisão
do operador, a decisão registrada prevalece e os itens abaixo ficam **superados**
(o texto do plano v1 permanece como histórico; não vale como contrato):

| Item do plano v1 | Situação | Vale agora |
|---|---|---|
| F5: sessão ativa com modelo incompatível ou não identificável **bloqueia** o envio | Superado | Gera **alerta** (`model_requires_new_session`); o envio segue com a escolha do operador. Sem reinício de tmux |
| F5/API: modelo explícito de outro cliente só aceito se igual à aba Agentes; divergência rejeitada | Superado | Chamadas diretas e legadas com `model` explícito seguem aceitas como antes; divergência do catálogo só alerta |
| Remover recomendação do painel | Superado | A recomendação do WorkDev é **consultiva**: pode sugerir e ordenar, nunca preenche nem substitui executor, revisor ou modelo |
| Revisão obrigatória pelo revisor independente nesta execução | Dispensada | Revisão é opcional; o operador decidiu não usar revisor nesta task, pois a maior parte já estava pronta |

Continua valendo e foi entregue: o modelo vem só da aba Agentes (sem seletor no painel),
seleção salva inválida bloqueia sem fallback, `DEFAULT` só sem seleção salva, e o modelo
efetivamente usado fica registrado na run.

Lacunas fechadas nesta execução (2B): a escolha Sim/Não de revisão por plano agora
sobrevive ao reload (`localStorage`, chave `workdev.planos.revisao`) e, depois do envio,
o painel mostra o **modelo registrado** na run. O modelo configurado já era exibido
antes do envio.
