# Configurações e decisões — 2026-10-24

Registro do que foi decidido e alterado nesta sessão. Fonte da verdade do código é o
git; este arquivo guarda o contexto e as decisões, para não precisar redescobri-los.

## 1. Regra de decisão do operador (vale sobre qualquer plano antigo)

- O operador escolhe **modelo e esforço** na aba Agentes, e no plano escolhe só o
  **executor** e, opcionalmente, o **revisor**.
- O WorkDev **pode sugerir e alertar**, nunca bloquear nem substituir agente, modelo,
  esforço, executor ou revisor.
- **Revisão é opcional.** Sem revisor, não se cria revisão nem a task fica aguardando.
- Registrado em `docs/adr/004-plan-build-handoff.md` (seções de 2026-10-24). Na seção
  "Task a4059dd7" os itens do plano v1 que conflitavam ficaram **superados**, com o
  histórico preservado: bloqueio por sessão divergente, rejeição de modelo explícito e
  remoção da recomendação.

## 2. Publicação

| Item | Estado |
|---|---|
| PR #3 `feat/backlog-archived` | mergeado no `main` |
| Deploy | feito e verificado: `workdev-api` ativo desde 17:54:38 UTC, `/health` online, versão 0.7.0 |
| PR #4 `fix/preco-deepseek-v41-flash` | aberto na data deste registro |
| PR #5 `feat/somente-openrouter` | aberto na data deste registro |
| Branch `feat/planos-sem-recomendacao` | commits `58bdd29` (meu) e `0276f74` (logo/PWA, de outra sessão); sem push |

Nada dos PRs #4 e #5 está em produção até haver novo deploy.

## 3. Catálogo e preços (OpenRouter, conferido em 2026-10-24)

**Alterado:** `deepseek/deepseek-v4.1-flash` de US$ 0,03 / 0,50 para **0,02 / 1,00** por 1M
(entrada/saída). Endpoint OpenInference, fp4, sem desconto; cache de leitura 0,015, que o
catálogo do WorkDev não modela. O preço real varia por provedor (entrada de 0,02 a 0,60).

**Pendente:** `DeepSeek V4.1 Pro` **não existe** no OpenRouter (IDs `deepseek-v4.1-pro`,
`-1017` e `v41-pro` deram 404). Não foi substituído por V4 Pro nem por V4.1 Flash.

**Divergências encontradas e NÃO aplicadas** (decisão do operador de restringir o escopo):

| Modelo | No WorkDev hoje | OpenRouter hoje |
|---|---|---|
| `gpt-5.6-sol` | 2,00 / 10,00 | 4,00 / 20,00 |
| `deepseek-v4-flash` | 0,0419 / 0,0837 | 0,091 / 0,182 |
| `kimi-k3` | 0,70 / 15,00 | 0,239 / 10,80 padrão; 0,19 / 8,94 só no provedor Relace |
| `qwen3.5-plus` | não cadastrado | o ID não existe; há `-02-15` (0,26/1,56) e `-20260420` (0,30/1,80) |

Os caches do Qwen 3.6 Flash (0,01875) e Qwen 3.6 Plus (0,0325) não aparecem no catálogo
do OpenRouter e ficaram sem confirmação. Preços do DeepSeek V4 Pro (`deepseek-v4-pro`) estão
em promoção de 88% no provedor mais barato, então não valem como preço padrão.

## 4. Somente OpenRouter para Kimi, Qwen e DeepSeek (PR #5)

- `start_kimi_agent.sh`: sem Moonshot. `start_qwen_agent.sh`: sem DashScope (antes,
  `QWEN_PROVIDER` vazio preferia o DashScope se houvesse chave).
- `qwen-agent-settings.json`: saiu a entrada DashScope. `ai.py`: saiu o provedor Moonshot
  direto do AI Hub.
- **Mantêm chave própria, sem alteração:** OpenAI, Gemini, Anthropic e Grok.
- Agentes em execução só mudam no próximo Ligar.

## 5. Painel de planos (commit `58bdd29`)

- A escolha Sim/Não de revisão por plano sobrevive ao reload (`localStorage`, chave
  `workdev.planos.revisao`).
- Depois do envio, o painel mostra o **modelo registrado** na run.
- O restante da task a4059dd7 (resolução do modelo do executor e do revisor pela aba
  Agentes) já estava no `main`.
- A run `0139fd5b` terminou `cancelled` (transição `cancelled → running` é inválida), sem
  perda: o trabalho está commitado.

## 6. Segurança — pendências

- A chave `DASHSCOPE_API_KEY` apareceu em um log desta sessão. O operador **não tem conta**
  no Alibaba Cloud e decidiu deixá-la como está. O valor não está neste documento.
- `apps/api/.env` está `root:workdev 640` (legível pelo grupo `workdev`, incluindo agentes
  de CLI), mas a documentação diz `root:root 600`. Não se sabe quando mudou. Em aberto.
- Não varrer `apps/api/.env` com `grep` recursivo: excluir `.env*` das buscas.

## 7. Como trabalhar neste terminal

- O terminal do operador quebra comandos longos ao colar. Padrão: **um comando por vez** e,
  para qualquer coisa maior que uma linha, gravar um script curto em `/tmp` e pedir
  `bash /tmp/<nome>.sh`.
- Push só por root: `GIT_SSH_COMMAND="ssh -i /root/.ssh/id_ed25519 -o IdentitiesOnly=yes"`,
  seguido de `chown -R workdev:workdev-runtime /opt/workdev/.git`.
- Deploy só pelo fluxo de `docs/DEPLOY_CANONICO.md`. Depois do merge, atualizar o `main`
  com `git fetch` (root) e `git merge --ff-only origin/main` (como `workdev`).
- Vários agentes e sessões compartilham `/opt/workdev`: um commit de uma sessão pode cair
  na branch da outra. Conferir `git branch --show-current` antes de commitar.

## 8. Ideias na fila

Para a bancada local, em ordem de retorno: `cache_prompt`, escolha automática de
trechos no "Planejar", `broker` na tela e speculative decoding. Detalhes em
`docs/planning/retomada-2026-10-24.md`.

**Feito no mesmo dia:** o item 1 (medir prefill e geração separados, pelo bloco
`timings` do llama-server) — branch `feat/bancada-medicao-prefill`, ainda sem
deploy. O que os números apontaram está em "Item 1" da retomada: o prefill é o
gargalo (26,0 s de 31,6 s na primeira rodada, ~11 tok/s) e o KV cache já resolve o
caso repetido (99% do prefixo reaproveitado, prefill de 26,0 s para 0,2 s).
