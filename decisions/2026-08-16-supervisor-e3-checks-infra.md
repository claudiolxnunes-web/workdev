# ADR — Supervisor E3: sem rede, sem duplicar sinal, e o RAG não é fonte

- **Data:** 2026-08-16
- **Status:** aceita, implementada e validada
- **Escopo:** `deploy_drift`, `knowledge_drift`, `agent_health`
- **Relacionado:** `docs/supervisor-mvp-plano.md`, ADRs de E1 e E2

## Contexto

Os três checks de E3 saem do Postgres e vão para git, systemd, disco e um
segundo banco. É onde o Nível 0 fica mais fácil de violar sem perceber, e onde
os sinais mais se sobrepõem aos que já existem.

Quatro decisões mereceram registro — três delas nasceram de defeitos
encontrados durante a validação, não do desenho original.

## Decisão 1 — o estado das migrations vem do banco e do disco, não da API

O plano previa `GET /api/system/migrations`. Ao validar contra o sistema real,
a rota devolveu:

```
{"detail":"Unauthorized"}
```

A API exige autenticação. O código tratava qualquer falha de HTTP como "nada a
reportar", então o check **passaria a vida inteira em silêncio** — e uma
migration pendente de verdade jamais apareceria. Um falso negativo silencioso,
exatamente a classe de defeito que o Supervisor existe para encontrar.

Substituído por comparação direta: `SELECT version_num FROM alembic_version`
contra o head calculado a partir de `apps/api/alembic/versions/*.py`, lidos com
`ast` (sem importar alembic, que puxaria o engine da aplicação). Head é a
revisão que ninguém declara como `down_revision`; mais de um head vira achado
`critical` de histórico bifurcado.

Ganhos colaterais: o check não precisa de credencial, e continua funcionando
com a API fora do ar — que é justamente quando alguém quer saber do banco.

Consequência: **o Supervisor não faz nenhuma requisição de rede.** As fontes
são dois Postgres, comandos git de leitura, `systemctl show`, `ss -tln` e dois
arquivos. Isso simplifica o modelo de segurança a ponto de valer a pena manter
como invariante.

## Decisão 2 — `blocked` não é fila

O `agent_health` originalmente media a fila com `ACTIVE_RUN_STATUSES`
(`queued`, `running`, `blocked`, `review`). A primeira execução real reportou:

```
2 execução(ões) na fila há 262h enquanto codex está ocioso
```

Os dois runs são `blocked` desde 05-06/08 — e um deles **já era reportado** por
`plan_without_execution.run_stalled`. O mesmo problema em dois checks, com dois
fingerprints, ocupando duas linhas do relatório de três.

`queued` é o estado de quem espera alguém pegar; `blocked` espera intervenção
humana e `running` sem evento é travamento. Só `queued` responde à pergunta
"há trabalho parado enquanto agentes estão ociosos?". Restringido a ele
(`config.FILA_STATUS`), o check deixou de disparar hoje — como o plano previa,
e agora pelo motivo certo.

Lição registrada como teste: `test_fila_so_conta_queued`.

## Decisão 3 — o índice do RAG não é um store concorrente

A primeira versão de `fonte_duplicada` contava três stores: `adrs`, `knowledge`
e `rag/disco`. Com isso, um ADR que existe como arquivo **e** está indexado
aparecia como duplicação — ou seja, o check reportava como problema o estado
saudável.

O RAG é índice **derivado** do disco: um documento existe lá porque o arquivo
existe. Os stores que competem de verdade são três, e todos aceitam escrita: a
tabela `adrs`, a tabela `knowledge` e os arquivos em `decisions/`.

Para comparar disco com tabela sem passar pelo índice, o título do arquivo
passou a ser lido do próprio markdown (primeiro `# H1`), que é o mesmo campo
que o ingestor indexa.

O defeito só apareceu porque um teste do cenário saudável falhou. Vale como
padrão: **todo check precisa de um teste do estado em que ele não deve
disparar**, não só dos estados em que deve.

## Decisão 4 — git de leitura é `--no-optional-locks`, e não há fetch

`git status` atualiza o cache de stat dentro de `.git/index`. Sem
`--no-optional-locks`, "somente leitura" deixaria de ser verdade no nível do
arquivo — discretamente, e só sob concorrência.

E não há `git fetch`: seria rede e escrita. Consequência assumida e
documentada no reader: `unpushed_commits` mede divergência contra o
`origin/develop` **local**, isto é, contra o último fetch que alguém fez. O
check mede divergência conhecida, não divergência real com o GitHub.

## Validação contra o sistema real

Cinco checks, 18 fatos, 0,10 s:

| Achado | Confirmado por |
| --- | --- |
| 6 arquivos rastreados modificados | `git status --porcelain` — é o próprio trabalho de E3 |
| main 49 commits atrás de develop | `git rev-list --count main..develop` |
| 18 de 19 ADRs fora do índice | o 19º casou por normalização de título (`ADR 004 — …`) |
| 81 de 85 registros de conhecimento fora do índice | os 4 que casaram são os ADRs de 15/08 que também são arquivos |
| backlog.md declara 84 itens; banco tem 179 | `head -3 backlog.md` + `count(*)` |
| 5 títulos em mais de um store de escrita | — |
| decisions e rfcs vazias com endpoint ativo | `count(*)` nas duas |

Não dispararam, e conferidos um a um: `unpushed_commits` (0 commits à frente do
remoto), `stale_build` (dist mais novo que os fontes), `service_older_than_code`
(nenhum fonte do backend tocado desde o restart), `migration_pending` (head
único `2c53d77a9f4b`, igual ao banco), `port_conflict` (1 socket na 8000),
`supervisao_parada` (status.json com 2 min), `agente_fora` (claude e codex no
ar), `arquivo_nao_indexado` (ingestor em dia).

Degradação, com o RAG apontado para uma porta morta:

```
checks_degraded=1  facts_detected=13  status=degraded  exit=0
failures=degraded:rag:OperationalError
```

Os outros quatro checks seguem produzindo. O mesmo vale para `status.json`
ausente.

## Estado após E3

Cinco checks ativos. 74 testes do Supervisor, 173 na suíte da API. Sem LLM, sem
timer, sem entrega, sem ação, sem escrita em banco ou schema, sem deploy.
