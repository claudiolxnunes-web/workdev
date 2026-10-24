# ADR — Supervisor E2: dupla identidade e resolução automática conservadora

- **Data:** 2026-08-16
- **Status:** aceita, implementada
- **Escopo:** `scripts/supervisor/estado.py` (etapa E2 do plano)
- **Relacionado:** `docs/supervisor-mvp-plano.md`, ADR de E1

## Contexto

O Supervisor roda todo dia sobre os mesmos dados. Sem memória entre execuções,
ele entregaria os mesmos 11 achados diariamente até alguém desligá-lo — o modo
de falha mais provável do projeto inteiro, e a razão de E2 vir obrigatoriamente
antes da entrega (E5).

O problema não é reconhecer repetição: é distinguir repetição de piora.

## Decisão 1 — duas identidades, não uma

Cada achado carrega dois identificadores derivados:

- **`fingerprint`** = `sha256(check | subcheck | entity_id | bucket)` — a
  identidade do *achado*, faixa incluída.
- **`chave_entidade`** = `check | subcheck | entity_id` — a identidade da
  *coisa observada*, faixa excluída.

Com só o fingerprint, uma task que envelhece de 14 para 15 dias produz um hash
novo e seria reportada como achado novo — indistinguível de um problema
realmente inédito. Com só a chave de entidade, a piora de patamar não seria
detectada.

As duas juntas resolvem os três casos:

| Situação | Fingerprint | Chave de entidade | Estado |
| --- | --- | --- | --- |
| Mesmo problema, um dia mais velho | igual | igual | `persistente` (calado) |
| Mesmo problema, patamar pior | **muda** | igual | `agravado` (reportado) |
| Problema inédito | novo | novo | `novo` (reportado) |

O `bucket_ordem` acompanha o rótulo da faixa porque rótulos não são
comparáveis: `"15-30"` e `"7-14"` não se ordenam por string. É a ordem que
diz se a transição foi para pior ou para melhor.

Severidade também é comparada dentro da mesma faixa: uma `high` que cruza 45
dias vira `critical` sem mudar de bucket, e isso é agravamento.

## Decisão 2 — só resolve quem rodou, e quem rodou bem

Um achado ausente da execução atual seria, ingenuamente, um achado resolvido.
Duas regras impedem que isso vire ruído:

1. **Só um check que rodou pode resolver os próprios achados.** Rodar com
   `--check critical_stalled` não marca os achados de `plan_without_execution`
   como resolvidos.
2. **Só um check que rodou com sucesso pode resolver.** Se um check falhar ou
   degradar, seus achados ficam intactos.

A segunda regra é a que importa. Sem ela, uma falha transitória — RAG fora do
ar, timeout, exceção num check — marcaria a base inteira como resolvida, e a
execução seguinte a traria de volta como novidade. O Supervisor produziria seu
maior pico de ruído exatamente quando estivesse com defeito.

## Decisão 3 — silêncio não é resolução

Um achado `critical` ou `high` que persiste volta ao relatório a cada 14 dias
(`REFORCO_DIAS`), mesmo sem mudança. Sem esse reforço, "o problema sumiu" e "o
problema segue lá, calado" ficam indistinguíveis para quem lê — a mesma classe
de falha do `EXCEPTION WHEN OTHERS` registrada em 2026-08-15, deslocada para a
camada de notificação.

Achados resolvidos são reportados **uma vez** e ficam no estado por 7 dias
(`RESOLVIDO_TTL_DIAS`), para que um problema intermitente não apareça como
novidade a cada volta.

## Decisão 4 — o estado nunca derruba a execução

`state.json` corrompido, com versão divergente ou com raiz inesperada faz o
Supervisor recomeçar vazio e marcar `estado_recuperado=1` nas métricas. Não há
migração silenciosa de formato e não há abortar.

O mecanismo anti-ruído não pode virar ponto único de falha: perder a memória
custa um dia de achados repetidos; abortar custa a execução inteira.

Escrita atômica (`tmp` no mesmo diretório + `replace`), mesmo padrão do
`agents_healthcheck.py`.

## Validação

Contra o banco real, com estado descartável:

```
--seed         → facts_detected=11  reportable_findings=0
execução 2     → new_findings=0     persistent_findings=11
piora simulada → worsened_findings=2  reportable_findings=2
execução 4     → worsened_findings=0  reportable_findings=0
```

E a transição visível:

```
[high    ] AGRAVADO  a1a874fc6511c446  NutriGestor CRM — task high parada há 34 dias
             faixa 7-14 → 31-60 (visto 2x desde 2026-08-16)
```

25 testes cobrindo semeadura, repetição, transição nos dois sentidos,
resolução, purga, reaparecimento, reforço, corrupção e as duas regras de
segurança da resolução.

## Armadilha registrada

Ao montar a validação ponta a ponta, alterar o campo `bucket` dentro do
`state.json` não simula piora nenhuma: a **chave** do registro é o fingerprint,
derivado do bucket. Sem reindexar o registro sob o fingerprint da faixa
anterior, a execução seguinte encontra o registro pela chave antiga e conclui,
corretamente, que nada mudou. Quem for reproduzir cenários de transição à mão
precisa recalcular a chave, não só o campo.

## Estado após E2

Ainda **não** existem: LLM, timer, entrega, ações. Nenhuma escrita no Postgres,
nenhuma alteração de schema. O estado vive em
`/var/lib/workdev-supervisor/{state.json,runs.jsonl}` — `rm -rf` do diretório é
rollback completo da memória, sem tocar em nada da plataforma.
