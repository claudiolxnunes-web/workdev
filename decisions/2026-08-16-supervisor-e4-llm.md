# ADR — Supervisor E4: o LLM ordena e explica, não descobre nem age

- **Data:** 2026-08-16
- **Status:** aceita, implementada e validada
- **Escopo:** `scripts/supervisor/llm.py`
- **Relacionado:** `docs/supervisor-mvp-plano.md` (seções 7 e 8), ADRs de E1 a E3

## Contexto

O princípio arquitetural do MVP é que o LLM não descubra o que pode ser
apurado por SQL, git ou systemd. E1–E3 produzem fatos determinísticos; E4
acrescenta a única etapa em que um modelo participa.

O risco desta etapa não é o custo — é o modelo virar caminho de execução, ou
virar dependência sem a qual o Supervisor deixa de funcionar.

## Decisão 1 — a ausência de tools é a garantia, não a instrução

A chamada é um `messages.create` sem `tools`, sem `tool_choice`, sem
`mcp_servers`. Não existe ferramenta declarada, logo não existe caminho pelo
qual o modelo possa tocar banco, shell, git ou arquivo — independentemente do
que o prompt diga ou de como ele seja manipulado.

Isso é preferível a instruir o modelo a não agir: instrução se negocia, ausência
de ferramenta não. Há teste que inspeciona os argumentos da chamada e falha se
qualquer um desses campos aparecer.

O modelo também não recebe conteúdo: o payload leva id, check, severidade,
título, medidas e os comandos de verificação — nunca corpo de documento,
connection string ou valor de variável. Teste dedicado varre o payload.

## Decisão 2 — a resposta é copiada campo a campo, nunca aplicada em bloco

`severity`, `entity_id`, `bucket`, `evidencia`, `fingerprint` e `status` são
lidos dos Fatos **depois** da resposta, não dela. O modelo só consegue
preencher `prioridade`, `impacto`, `risco`, `recomendacao` e `acao_sugerida`.

Um `id` que não existe na entrada é descartado e contado em `llm_invalid_ids`.
Um achado que o modelo ignorou não some do relatório: recebe a posição
determinística e segue sem prosa, contado em `llm_missing_ids`.

Na primeira execução real ambos deram zero, mas as duas contagens ficam no log
justamente para que a degradação silenciosa apareça.

A prosa do modelo passa pela mesma varredura de segredos que o resto da saída.
Ele não recebe segredo nenhum, então a chance é remota — mas a redação é
fail-closed por princípio, e não abre exceção para o LLM.

## Decisão 3 — o fallback determinístico é o caminho normal, não a exceção

Toda falha — rede, timeout, 429, 5xx, `stop_reason: refusal`, JSON inválido,
resposta sem bloco de texto, chave ausente, modelo inexistente — cai na ordem
por severidade, com `llm_failures=1` e `status=degraded`. `priorizar()` nunca
propaga exceção.

Validado em seis cenários por teste e em dois contra o sistema real:

```
chave ausente        → llm_calls=0 llm_failures=1 status=degraded exit=0
modelo inexistente   → llm_calls=0 llm_failures=1 status=degraded exit=0
```

Nos dois, os 18 fatos continuaram saindo, priorizados por severidade.

`--sem-llm` força o caminho determinístico sem falha (`status=ok`), e nem
`--dry-run` nem `--seed` gastam chamada — critério de aceite 1 do plano.

## Decisão 4 — sem lock-in além do que o plano já assumiu

O modelo é `config.LLM_MODELO` (`claude-opus-5`), sobrescrevível por
`--modelo` ou `SUPERVISOR_MODELO`. A dependência é a mesma que a plataforma já
tem: o SDK `anthropic` e a `ANTHROPIC_API_KEY` que o AI Hub usa. Nenhum venv
novo, nenhum pacote novo, nenhuma conta nova.

A tabela de preços em `LLM_PRECOS_USD_POR_MTOK` serve só para estimar custo no
log; um modelo fora dela apenas reporta custo zero, sem quebrar.

O que **é** específico da Anthropic: `output_config.format` com json_schema e
`output_config.effort`. Trocar de provedor exigiria reescrever `_extrair_json` e
a montagem da chamada — cerca de 40 linhas, todas em `llm.py`. O resto do
Supervisor não sabe que existe um modelo.

Não foi usado `thinking: {"type": "disabled"}`: no Opus 5 isso induz vazamento
de tag `<thinking>` no texto e chamadas de tool escritas como texto. Efeito
adaptativo padrão com `effort: medium` é a configuração certa para ordenar e
escrever.

## Custo medido

Primeira execução real, 8 achados enviados:

```
llm_calls=1  llm_input_tokens=4160  llm_output_tokens=2238
llm_cost_usd=0.0767  duration_seconds=33.1
```

US$ 0,077 por execução. A uma execução diária: **~US$ 2,30/mês** — dentro da
estimativa de US$ 2,60 feita no plano, e a razão de o plano ter descartado uma
camada de triagem barata: ela economizaria centavos ao custo de um segundo
prompt, um segundo schema e um modo de falha a mais.

`llm_calls` conta chamadas **concluídas**. Numa falha de rede fica 0 com
`llm_failures=1`; numa recusa fica 1 com `llm_failures=1`, porque a chamada
aconteceu e foi cobrada.

## Limite conhecido

O LLM recebe no máximo `LLM_MAX_FATOS` (8) achados. Na execução real havia 18
reportáveis; os 10 restantes saíram sem prioridade e sem prosa. Isso é por
desenho — o corte final para 3 achados no relatório é da etapa E5, e é lá que
os excedentes viram uma linha-resumo em vez de uma lista.

## Correção acoplada em `deploy_drift`

Revisão apontou que o subcheck `uncommitted_in_production` afirmava, para
qualquer arquivo rastreado modificado, que ele "já está em produção". Falso
para boa parte da árvore: `deploy.sh` builda `apps/web` e reinicia
`workdev-api`, e nada além disso é servido.

Os arquivos modificados passaram a ser classificados em três grupos:

| Grupo | Exemplo | Achado |
| --- | --- | --- |
| Servido pelo deploy | `apps/web/src/`, `apps/api/app/` | `uncommitted_in_production` (high) |
| Já em execução por timer/cron | `scripts/agents_healthcheck.py` | `uncommitted_in_production` (high) |
| Fora do runtime | testes, ADRs, código sem unit | `uncommitted_work` (info) |

O terceiro grupo existe porque o risco ali é perder trabalho, não publicar
código não revisado — e tratá-lo como produção transformaria o estado normal
de quem está desenvolvendo em alerta diário.

Na árvore atual, os arquivos do próprio Supervisor caem no terceiro grupo: ele
ainda não tem timer nem faz parte do build.

## Estado após E4

Uma chamada por execução, sem tools, schema fixo e validado, fallback
determinístico obrigatório. Nível 0 mantido: sem ações, sem Telegram, sem
timer, sem escrita em banco ou schema, sem tocar RAG, agentes ou deploy.

18 testes novos (6 com subtests), 118 no Supervisor, 191 na API.
