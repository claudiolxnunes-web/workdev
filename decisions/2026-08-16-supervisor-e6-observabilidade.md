# ADR — Supervisor E6: métricas que nunca faltam, retenção que não decide sozinha

- **Data:** 2026-08-16
- **Status:** aceita, implementada e validada
- **Escopo:** `config.METRICAS_OBRIGATORIAS`, `estado.rotacionar_execucoes`, `__main__`
- **Relacionado:** `docs/supervisor-mvp-plano.md` (seção 10), ADRs de E1 a E5

## Contexto

Antes da semana de sombra, a instrumentação precisa ser confiável: é ela que
vai dizer se o MVP merece continuar existindo. Um log incompleto ou um campo
que some em certos caminhos torna o critério de desligamento inauditável.

## Divergência encontrada e corrigida

O enunciado da missão lista **11** métricas obrigatórias. O plano que escrevi
dizia "12 campos" em dois lugares — erro de contagem meu, não uma décima
segunda métrica escondida. O plano foi corrigido para 11, e a lista canônica
passou a viver em `config.METRICAS_OBRIGATORIAS`, onde um teste a compara com o
enunciado.

`duration` do enunciado é registrado como `duration_seconds`, para casar com o
formato que o ingestor do RAG já emite. A diferença está documentada na
constante.

## Decisão 1 — falha de redação não pode virar apagão de observabilidade

A rede de segurança que varre Fatos por segredo antes de publicá-los levantava
`RuntimeError`. O efeito era perverso: um problema de redação **matava a
execução antes de qualquer métrica ser emitida**. O Supervisor ficaria mudo
exatamente no caso em que mais se quer saber o que aconteceu.

Agora o fato suspeito é descartado, contado em `redaction_failures`, e a
execução segue com `status=failed`. Nada é publicado, o problema aparece no
log, e o exit code 1 aciona o `OnFailure`.

## Decisão 2 — a redação roda antes de persistir, inclusive sobre as métricas

`redigir_valor` passa sobre o dicionário de métricas antes de ir para o
journald e para o `runs.jsonl`. O motivo concreto: `llm_model` vem de
`--modelo`, que é entrada externa. Um operador que colasse uma chave ali
gravaria a chave no log permanentemente.

Verificado com segredo sintético:

```
--modelo sk-ant-api03-ZZZ…  →  "llm_model": "[REDIGIDO]"
runs.jsonl varrido: nenhum padrão de segredo
state.json varrido: nenhum padrão de segredo
```

## Decisão 3 — a rotação não apaga o que não consegue datar

`runs.jsonl` guarda 90 dias. A rotação roda **antes** de gravar a linha da
execução atual, para que ela registre a própria limpeza que provocou
(`log_entries_pruned`).

Linha ilegível é **preservada e contada** em `log_invalid_lines`, não apagada.
Sem `started_at` não há como saber a idade dela, e descartar dado que não se
consegue datar seria o programa decidindo por conta própria. A contagem no log
torna o problema visível se o arquivo começar a acumular lixo.

Outras garantias: escrita atômica (tmp no mesmo diretório + replace), arquivo
ausente ou vazio não é erro, nada a remover não reescreve o arquivo, e
`state.json` nunca é tocado.

Validado com nove linhas sintéticas:

```
linhas antes:            9
removidas (>90 dias):    3     (200, 120, 91)
inválidas (preservadas): 2
linhas depois:           6     (90, 45, 10, 1 + as 2 inválidas)
state.json intacto:      True
arquivos no diretório:   ['runs.jsonl', 'state.json']   (sem temporário)
```

O limite é exato: 90 dias ficam, 91 saem.

## Decisão 4 — campo faltando é reportado, não escondido

Antes de gravar, `main` compara as chaves com `METRICAS_OBRIGATORIAS` e, se
faltar alguma, acrescenta `missing_required_metrics` com os nomes ausentes.
Um teste garante que esse campo nunca aparece — mas se um refactor futuro
quebrar o contrato, o log dirá qual campo sumiu em vez de simplesmente não
tê-lo.

## Onde cada métrica obrigatória é produzida

| Métrica | Origem |
| --- | --- |
| `started_at` | `__main__.main`, primeiro `agora_utc()` |
| `finished_at` | `__main__.main`, ao fechar as métricas |
| `duration_seconds` | `__main__.main`, `time.monotonic()` |
| `checks_executed` | `__main__.main`, quantidade de checks pedidos |
| `facts_detected` | `__main__.main`, fatos após redação e descarte |
| `new_findings` | `estado.Reconciliacao.contagens["novo"]` |
| `persistent_findings` | `estado.Reconciliacao.contagens["persistente"]` |
| `resolved_findings` | `estado.Reconciliacao.contagens["resolvido"]` |
| `llm_calls` | `llm.ResultadoLLM.chamadas` |
| `llm_failures` | `llm.ResultadoLLM.falhas` |
| `status` | `__main__.main`, derivado de conexão, checks, LLM, entrega e redação |

Todas seguem por dois caminhos: `emitir_metricas` (stdout → journald, formato
`chave=valor` do ingestor) e `Estado.registrar_execucao` (runs.jsonl, JSON).

Uma linha completa tem 35 campos; os 11 são o piso, não o teto. Os extras
existentes foram mantidos — nenhum duplica outro, e não foi criada métrica
nova além de `redaction_failures`, `log_entries_pruned` e `log_invalid_lines`.

## Cobertura por cenário

Sete cenários rodam `main()` em processo, com banco real e com LLM e entrega
substituídos — nenhum teste chama a API da Anthropic nem envia Telegram:

| Cenário | Resultado |
| --- | --- |
| Execução normal | `status=ok`, 11/11 presentes |
| Sem novidade | `new_findings=0`, `delivery=skipped:sem_novidade` |
| Falha parcial de check | `checks_degraded=1`, `status=degraded`, os outros checks seguem |
| Fallback de LLM | `llm_failures=1`, `status=degraded`, `failures` contém `llm:…` |
| Falha de entrega | `delivery=failed:…`, `state_persisted=0`, `status=degraded` |
| `--dry-run` | emite métricas, não grava linha |
| `--seed` | `seed=1`, `new_findings=0` |

Um teste garante o que o enunciado pediu explicitamente: **nenhuma falha vira
`status=ok` em silêncio**. Com LLM e entrega falhando juntos, o status é
`degraded` e `failures` lista os dois.

## Estado após E6

249 testes na API, 176 do Supervisor. Nível 0 mantido: sem ações, sem Telegram
real, sem timer, sem units instaladas, sem deploy, sem alterar banco, schema ou
RAG. Falta apenas E7 — a semana de sombra, quando o timer é habilitado.
