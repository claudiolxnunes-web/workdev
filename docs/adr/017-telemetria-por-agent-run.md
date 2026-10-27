# ADR 017 — Telemetria por AgentRun: consumo, custo e de onde o número veio

Status: accepted (decidido pelo Cláudio em 2026-10-27, “do 1 ao 4”); implementada em
`feat/referencias-e-telemetria`.
Proposta de origem: `docs/telemetria-agent-run-proposta.md`.

## Contexto

O WorkDev já guardava consumo — mas de outro objeto. `ai_call_logs` registra
tokens e custo das chamadas de LLM do **AI Hub**: provider, modelo,
`input_tokens`, `output_tokens`, custo estimado e custo real. A tabela não tem
`run_id`, e o `AgentRun` não tem coluna de telemetria nenhuma — só `agent`,
`model`, `routing_mode` e `routing_reason`.

O resultado é uma lacuna concreta: **não há como dizer quanto uma execução de
agente custou, nem a quem**. O operador vê o catálogo de preços e vê o gasto do
chat, mas o Build — a parte que realmente roda o trabalho — é cego. Quando a
conta do provedor chega, não há como reconciliar com a run que a produziu.

Dois agravantes, ambos já registrados na auditoria
(`docs/AGENT_REFERENCE_CONTEXT_AUDIT.md`):

1. **O provider da run não é consultável.** A escolha (provider + modelo +
   origem da escolha) vive no payload do evento `build.queued`. Auditável por
   evento, impossível por coluna.
2. **Os números que existem hoje não distinguem origem.** Sem uma marca de onde o
   número veio, um valor estimado por contagem de caracteres apareceria ao lado
   de um valor faturado pela API, e a soma dos dois seria mentira.

E há um terceiro ponto, menos visível: **o consumo de um CLI por assinatura
(Claude Code, Codex, Gemini CLI) não chega ao WorkDev**. A CLI fala com o
provedor por fora; o WorkDev vê o texto, não a conta.

## Decisão

1. **`agent_runs.provider`** — o provider sai do payload do evento e vira
   coluna. Nulo nas runs históricas; a partir daí, consultável por run.

2. **Tabela `agent_run_telemetry`, separada de `agent_runs`.** Uma linha por
   chamada de provedor, não por run: uma execução pode acionar mais de um
   provedor, e somar tudo na linha da run esconderia a composição. `run_id`,
   `backlog_id` e `project_id` (desnormalizados, porque o relatório é por task e
   por projeto), `agent`, `provider`, `model`, tokens de entrada/saída/cache,
   custo estimado e real, moeda, `source` e `cost_class`.

3. **`source` é NOT NULL, e sem default.** `official` = o número veio da API do
   provedor ou do runtime; `estimated` = foi derivado do transcript e do preço
   de catálogo. Ninguém grava número sem dizer de onde ele veio. É esta coluna
   que sustenta o requisito “dados estimados nunca devem ser apresentados
   como faturamento oficial”.

4. **`cost_class` é NOT NULL.** `local` (runtime da própria VPS), `free_quota`,
   `included_plan` (já pago por assinatura) e `paid_api` (cobrança por token).
   Sem isso, somar custo por agente mistura o que é despesa marginal com o que
   já está pago.

5. **Não se inventa número.** Sem contagem oficial e sem custo conhecido,
   **não se grava linha**. Uma linha vazia vira ruído e depois vira relatório.
   O que a rota por run devolve diz explicitamente `reported: false` — ausência
   de consumo é informação, não zero.

6. **O que está instrumentado hoje é o despacho para runtime local.** Ollama e
   llama.cpp devolvem a contagem de tokens na resposta (`prompt_eval_count` /
   `eval_count` e `usage.prompt_tokens` / `usage.completion_tokens`), e ela vira
   linha com `source = 'official'` e `cost_class = 'local'`. O llama.cpp passou
   a pedir `stream_options.include_usage` — sem isso, a contagem não vinha.

7. **Relatório por origem e por classe.** `GET /api/handoffs/telemetry` agrupa
   por agente, provider, modelo, `source` e `cost_class`: oficial e estimado
   nunca somam na mesma linha. `GET /api/handoffs/runs/{id}/telemetry` traz o
   consumo de uma run.

## Opções

- **Colunas de token e custo em `agent_runs`.** Rejeitada: uma run pode ter
  mais de uma chamada de provedor, e a granularidade se perde no agregado.
- **Reaproveitar `ai_call_logs`.** Rejeitada: a tabela é do AI Hub, não tem
  `run_id`, e modelar Build e chat na mesma tabela misturaria dois custos
  diferentes (API cobrada por token e cota de assinatura).
- **Estimar tokens pelo transcript da CLI.** Adiada. É o caminho para cobrir
  Claude Code/Codex/Gemini, mas o número seria derivado de uma contagem
  aproximada: quando entrar, entra como `source = 'estimated'`, nunca como
  oficial, e nunca sozinho — sem o lado de entrada, a conta sai errada.
- **Não medir nada.** Rejeitada: sem consumo, o WorkDev não consegue dizer se
  uma mudança de modelo valeu o custo.

## Consequências

- **A migration tem de entrar antes do código.** `agent_runs.provider` é
  lida pelo ORM em toda serialização de run: código novo com banco velho
  derruba a API. A ordem do deploy é migration, depois release.
- **Runs de CLI por assinatura não aparecem no relatório** até a instrumentação
  do transcript existir. É a ausência que o `reported: false` declara, e não um
  zero silencioso.
- **Custo de runtime local entra como zero de API**, com `cost_class = 'local'`
 separando do que é cobrança. O consumo de CPU da VPS continua sem preço — e
  sem preço, sem número.
- **A migração é reversível**: `downgrade` derruba a tabela e a coluna, sem
  tocar em `ai_call_logs` nem em `agent_run_events`.
