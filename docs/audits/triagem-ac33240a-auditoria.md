# Auditoria da triagem ac33240a — trilha de arquivamento e rótulos pendentes

**Task:** `a8ba9042-1cf8-4607-9485-8bc211ff0fe6`
**Run de execução:** `7c123e9b-8f0f-4812-b278-6aaaae771f8c` (executor deepseek; revisor independente: qwen)
**Data da auditoria:** 2026-10-15 (baseline inicial 21:19 UTC; baseline final 2026-10-16T01:48 UTC)
**Protocolo de rótulos:** Backlog Zero — knowledge `cf47f7d0-30bb-433f-9891-9136de0626f3` (criado 2026-09-05 12:33)
**Tipo:** somente leitura. Zero escrita no backlog (GET/POST/PATCH/DELETE e UPDATE/DELETE ausentes; apenas SELECT/GET).

Este relatório é o artefato único desta auditoria e existe em commit isolado que não
toca código de aplicação nem dados do backlog.

---

## 1. Sumário executivo

1. **Arquivados (34):** todos os 34 itens `archived` do workdev-core possuem `archived_reason`
   e `archived_at` legíveis pela API REST (`GET /backlog?status=archived` e
   `GET /backlog/workdev-core?include_archived=true`). **Nenhum item está sem motivo ou sem data.**
   Distribuição dos motivos (`obsoleta` 12, `concluida_fora` 21, `sem_destravamento` 1). Não houve
   reavaliação dos itens; a triagem executada pela run 0022528b é citada como origem de 12
   arquivamentos datados de 2026-10-14T15:48:26; os 3 da família local-code (12/10/2026) foram
   identificados e **não padronizados** (fora de escopo).
2. **Abertos (20 — 17 todo + 3 blocked):** cada item recebeu exatamente um rótulo do
   vocabulário cf47f7d0 (`MANTER`, `CONCLUIR`, `OBSOLETA`, `DUPLICATA`, `SUBSTITUÍDA`,
   `REBAIXAR`, `AGUARDAR DECISÃO`, `VERIFICAR`). **13 em VERIFICAR** (sem fonte conclusiva),
   7 em MANTER com fonte citável. Nenhuma conclusão por idade/título.
3. **Divergência:** a triagem ac33240a (task `done`) e sua run 0022528b reportaram inventário e
   arquivamento como concluídos, mas (a) a subtask 3 (Verificação final e registro no Knowledge)
   consta **todo** — não done; (b) **não existe entrada de Knowledge da triagem** — a única
   entrada que menciona `ac33240a` é o post-mortem `d72cf19d` criado em 2026-10-15 20:11, após a
   run; (c) o inventário `/tmp/inventario_backlog_zero.md` existe (14/10 14:51) com soma interna
   inconsistente (corpo: ARQUIVAR 12, MANTER 6, VERIFICAR 13; sumário: 11/5/15); (d) a run
   0022528b registra `error` com BLOQUEIO (35 vs 31 itens) e `summary` afirmando conclusão —
   estados contraditórios no mesmo registro. Nenhuma causa é inferida; os fatos são declarados
   com fonte.

---

## 2. Baseline congelado (Fase 1)

Fonte: `GET /api/backlog/workdev-core?include_archived=true` (rota confirmada em
`apps/api/app/routers/backlog.py:42-53`) e `GET /api/backlog?status=archived`
(`backlog.py:29-39`).

| status | baseline 21:19 | baseline 01:48 | delta |
|---|---|---|---|
| todo | 17 | 17 | 0 |
| blocked | 3 | 3 | 0 |
| doing | 2 | 2 | 0 |
| done | 102 | 102 | 0 |
| archived | 34 | 34 | 0 |
| **total** | **158** | **158** | **0** |

- `archived_reason` presente: **34/34** (100%).
- `archived_at` presente: **34/34** (100%).
- Número de linhas do inventário (34) == registros retornados (34) == contagem `archived` (34). ✔
- Contagens idênticas antes e depois da auditoria (delta 0 declarado).

Nota de divergência de baseline (sem inferir causa):

- Descrição da task e knowledge `d72cf19d` (criado 2026-10-15T20:11): "157 total", "19 abertos"
  (17 todo + 2 blocked).
- Nota de baseline do plano aprovado (seção "Evidências já confirmadas nesta sessão"):
  "todo 18, blocked 2" — distribuição divergente da descrição (18×17 em todo), mesmo total 158.
- Esta auditoria observa: **158 total**, **20 abertos** (17 todo + 3 blocked), idêntico entre
  21:19 e 01:48.

Diferença de **+1 em blocked** (e +1 no total) frente à descrição da task: o item
`a8ba9042` (esta própria task) consta como `blocked` e foi criado em 2026-10-15T20:58:22 — após
a criação do knowledge `d72cf19d` (20:11). O `todo` observado (17) é igual ao da descrição e
**não** confirma o "todo 18" anotado no plano; o ponto a confirmar 2 do plano
("origem do delta de 1 em todo (17 → 18)") fica registrado aqui como não reproduzido pela
leitura da API nesta auditoria.

---

## 3. Inventário dos 34 arquivados (Fase 2)

Fonte: saída literal de `GET /backlog/workdev-core?include_archived=true`
(timestamp 2026-10-15T21:20:21 UTC), filtrada em memória por `status == "archived"` e ordenada
por `archived_at`. A saída bruta integral está preservada em anexo (A.1) — inclui
`archived_at` e `archived_reason` completos de cada um dos 34.

### 3.1 Tabela item a item (id, título, motivo, data)

| # | id | título | motivo (prefixo) | archived_at (UTC) |
|---|---|---|---|---|
| 1 | bf5e2d16-c4ce-424e-9f64-cb98dd174c77 | [Descartada] Task 1-30.09.2026 - Smoke test — Local Mod… | obsoleta | 2026-10-12T14:36:53.286 |
| 2 | de801bf7-7264-46c6-a66d-f99a0a8b3dcc | [Descartada] Unificar BUILD e terminal real do local-co… | obsoleta | 2026-10-12T14:36:53.295 |
| 3 | 4bbd36e3-ba5e-4780-b1ab-a1d0e55eb388 | [Descartada] Teste E2E local-code llama.cpp — 18.09.26 | obsoleta | 2026-10-12T14:36:53.300 |
| 4 | 397224a7-2900-4297-a66b-a1a411c28092 | Registrar fechamento de sessão 27/07/2026 — correções… | concluida_fora | 2026-10-14T11:36:49.202 |
| 5 | d5fd697f-4796-4501-a1c7-af1f6cf9024e | Fechamento de sessão de infra 03/08/2026 — migrations f… | concluida_fora | 2026-10-14T11:37:17.464 |
| 6 | 0fcf2b61-51f5-4bdc-a3e4-06e510375200 | registro completo da migração e inventário de plataform… | concluida_fora | 2026-10-14T11:37:17.473 |
| 7 | 6d8c38f9-3b52-4ee1-8a6c-e557aaa93cd0 | Registrar migrações Lovable→Supabase e inventário de pr… | concluida_fora | 2026-10-14T11:37:17.481 |
| 8 | 52816e04-c804-4643-94f1-f9c88e92dd0d | migração dados Lovable/Manus | concluida_fora | 2026-10-14T11:37:17.492 |
| 9 | fe9520e4-c05d-4d3d-ac5c-bf38f8aea878 | Executar checklist final de saída Lovable/Manus | concluida_fora | 2026-10-14T11:37:17.499 |
| 10 | 0d8b123f-17ec-42ef-a18e-5ddde6c09ea9 | Lição pós-reboot — bind 172.17.0.1 nunca existiu (rede… | concluida_fora | 2026-10-14T11:37:17.504 |
| 11 | 177a2f03-8afb-49c7-abde-4646d0eea90b | Task 2 -09.09.26— Ligar e desligar agentes locais de ve… | obsoleta | 2026-10-14T11:37:17.509 |
| 12 | ef5d5dd8-3f92-4de2-ba94-198983293cb3 | Integrar agentes Ollama locais/GPU ao Build com revisão… | obsoleta | 2026-10-14T11:37:17.515 |
| 13 | 201334b9-bb28-4563-871a-06c20945f7b2 | Ativar JEV também para o executor local-code | obsoleta | 2026-10-14T11:37:17.521 |
| 14 | dbd33dc1-0d76-40d9-aa89-cf1a3564bfd6 | local-code: gravar modelo fisico real (current()) em ca… | obsoleta | 2026-10-14T11:37:17.527 |
| 15 | 292d642e-c259-4964-94ef-806c7b6df78e | Adicionar workdev-local-fast (Qwen3.8-4B) como modelo l… | obsoleta | 2026-10-14T11:37:17.532 |
| 16 | b8bebeb7-98e4-48e0-a44a-dd86f922037c | [Duplicada/Descartada] Frota de Agentes — Fase 0 e Fase… | concluida_fora | 2026-10-14T11:37:17.538 |
| 17 | 786318a7-32c0-43ac-be1a-284c46e672e7 | Tabelas decisions e rfcs têm model, router e migration… | sem_destravamento | 2026-10-14T11:37:17.543 |
| 18 | 9dff551c-c064-4b31-a41e-168e17686a4f | Discovery: mapear fontes e health check dos runtimes | obsoleta | 2026-10-14T11:37:17.549 |
| 19 | 8eddb391-812a-4118-8b94-962aa48cbe95 | Backend: endpoint agregado de saúde dos runtimes | obsoleta | 2026-10-14T11:37:17.554 |
| 20 | 0f5fd9b3-56a7-4b9c-87d8-7ab78882b1b8 | Frontend: painel de saúde dos runtimes na aba Agentes | obsoleta | 2026-10-14T11:37:17.560 |
| 21 | b48cfaa8-562d-446b-9b5c-d6b46a58d317 | UI não distingue agente inexistente de agente conectado… | obsoleta | 2026-10-14T11:37:17.567 |
| 22 | d5009e15-3d4d-4fc4-b798-f5aae3563e68 | Painel de Saúde dos Runtimes | concluida_fora | 2026-10-14T11:37:17.573 |
| 23 | 670136e1-4867-4c05-b281-076e238f444c | MCP somente leitura para resumo semanal do WorkDev | concluida_fora | 2026-10-14T15:48:26.828 |
| 24 | c8499d8d-5a36-4b3f-a7e5-e16143d860d7 | Settings: API Keys — listar/gerenciar keys sem expor va… | concluida_fora | 2026-10-14T15:48:26.843 |
| 25 | 198527b7-9ac7-4d67-9a9c-93797365326b | Engineering Graph: confirmar enum node_type/relationshi… | concluida_fora | 2026-10-14T15:48:26.855 |
| 26 | 667834de-1c16-49c1-8d0b-4aa0ddf7f8d0 | Fix: nós exibindo hash de ID em vez do título (fallback… | concluida_fora | 2026-10-14T15:48:26.867 |
| 27 | 4735ed32-4da5-46a7-aa9e-c6c45a316cd1 | Chore: remover nó de teste bbbbbbbb do banco e adiciona… | concluida_fora | 2026-10-14T15:48:26.876 |
| 28 | d21f9c89-4590-4843-84ff-ce7642c2c82b | Confirmar identidade de Nutri_Agro Labels: modulo do BP… | concluida_fora | 2026-10-14T15:48:26.885 |
| 29 | 269e68ef-dc42-421b-8ba9-dad48ca4dfdf | Verificar se Agro CRM e NutriGestor CRM sao registros d… | concluida_fora | 2026-10-14T15:48:26.894 |
| 30 | ba455183-6ae1-430c-8a3c-394453d0050b | Modal perde estado ao sair da aba | concluida_fora | 2026-10-14T15:48:26.905 |
| 31 | 46119309-be87-4f2e-8654-b7c51a6af673 | workdev-agents.service sem supervisão | concluida_fora | 2026-10-14T15:48:26.915 |
| 32 | 23f3792c-69e3-4c8e-883d-7e4899cd758e | Servidor MCP para registro de pendencia pelos agentes | concluida_fora | 2026-10-14T15:48:26.924 |
| 33 | 28687219-e72c-4f49-ad9a-40324714448f | Dashboard: derivar saude dos projetos do healthcheck, n… | concluida_fora | 2026-10-14T15:48:26.932 |
| 34 | 393ec904-25fe-40e1-b5e9-5f7431029416 | Task: 12/09 — Automatizar ciclo Executor → Gate → Revis… | concluida_fora | 2026-10-14T15:48:26.940 |

Soma das linhas: **34** == 34 registros == baseline. ✔

### 3.2 Certidão de lacunas — SEM MOTIVO / SEM DATA

**Nenhum dos 34 itens está sem motivo ou sem data.** `archived_reason` e `archived_at`
preenchidos em 34/34. A coluna `archived_reason` segue o formato `<motivo>: <texto>` (ADR 009,
`docs/adr/009-backlog-archived.md:15`), com prefixos observados: `obsoleta` (12),
`concluida_fora` (21), `sem_destravamento` (1).

### 3.3 Família local-code (não padronizada — fora de escopo)

3 itens arquivados em 2026-10-12T14:36:53 (antes do lote de 14/10) referem-se ao executor
`local-code` extinto e carregam prefixo `[Descartada]` no título (itens 1-3 da tabela acima).
Conforme escopo aprovado, **não foram reavaliados nem padronizados**; os motivos gravados são
transcritos como estão.

### 3.4 Observação factual de concentração de datas (sem causa)

31 dos 34 itens foram arquivados em 2026-10-14 (11:36-11:37 à tarde e 15:48:26), e 3 em
2026-10-12T14:36:53. Nenhuma causa é afirmada para essa concentração.

---

## 4. Rótulos dos itens abertos (Fase 3)

Fonte dos itens: `GET /api/backlog/workdev-core?include_archived=true` filtrado por
`status in (todo, blocked)` (timestamp 2026-10-15T21:20:21). Vocabulário: cf47f7d0.

| # | id | status | título (resumo) | rótulo | fonte |
|---|---|---|---|---|---|
| 1 | 5b4f837e-d0fb-4871-b661-2593877cd658 | todo | Tool node WorkDev no Agente Pessoal (backlog por voz) | MANTER | `docs/perfil/02-ecossistema.md:62` (Agente Pessoal ativo) |
| 2 | 7cd35745-4a9d-481a-bd8e-7453a49b7696 | todo | Colorir prompts dos terminais VPS1 e VPS2 | VERIFICAR | sem fonte citável |
| 3 | fd707712-1888-4d6c-936d-cd94060949ff | todo | Sincronizar dados do app Balance com Supabase | VERIFICAR | sem fonte citável |
| 4 | 8bac3174-8bdb-4432-9ca4-84db926160a0 | todo | Relatório de Execução padronizado do Fable | VERIFICAR | `knowledge dd6efb9e` registra decisão (07/15) mas não entrega/migração do relatório; sem fonte de conclusão |
| 5 | 95a23b01-eb6e-4ed8-844b-cc3621933313 | todo | Package: Engineering Graph Service | MANTER | `packages/engineering-graph/` (pacote ativo, knowledge `9b08f855`) |
| 6 | e4f37cf4-691c-492a-b010-8924262328e6 | todo | Engineering Graph: cascade de exclusão Postgres → grafo | MANTER | `apps/api/app/routers/adrs.py:106-111` — `delete_adr` sem remoção do nó no grafo (comportamento descrito na própria task) |
| 7 | 5155e380-20fd-4616-85c2-1f7ad2f1a1fa | todo | Stack Padrão BPF Consult - Decisões Arquiteturais | VERIFICAR | `knowledge bd8add5d` registra decisão (07/29); sem fonte de conclusão |
| 8 | cff03174-5de5-4632-a40e-87d1f7aa3956 | todo | Engineering Graph: corrigir falha silenciosa e reconciliar dados | MANTER | `apps/api/app/services/engineering_graph.py:278-289` — `sync_safely` engole exceções; dados declarados divergentes na própria task |
| 9 | f2dc1858-8e14-4d2f-acea-3cded64178f4 | todo | Logrotate para workdev-api-healthcheck.log | MANTER | `scripts/healthcheck_api.sh:8` — arquivo de log sem rotação; ausência de conf em `/etc/logrotate.d/` |
| 10 | 8bbb39c2-adf9-447e-8260-51715597606e | todo | registrarAuditLog falha em silêncio | VERIFICAR | sem ocorrência da função no repositório (grep vazio) |
| 11 | c96d4c6f-ecba-4f27-959f-4dd4c8ff9aaa | todo | documento_versoes permite UPDATE/DELETE pelo dono | VERIFICAR | tabela não encontrada no repositório (grep vazio) |
| 12 | 42daabd4-3900-41a8-bc29-d75222062afe | todo | Teste de websocket pendura na suite de terminal | VERIFICAR | teste existe (`apps/api/tests/test_terminal.py:123`) e passa na suíte atual (45 passed, 2026-10-16T01:47); sem fonte de commit que resolva o pendurar |
| 13 | b3f12e1f-303f-49e8-99d8-5b15c8878054 | todo | busca.py na VPS divergente do original | VERIFICAR | `/opt/rag-postgres/busca.py` existe mas ilegível para leitura (perm root:root 0600); sem fonte |
| 14 | 8123773b-0fb1-4621-ad15-94601cfb1003 | todo | Avisos do WorkDev no agente pessoal | VERIFICAR | sem fonte citável |
| 15 | c63605fe-f949-42d2-9d0f-1b30849d292a | todo | Dashboard: projetos duplicados e mistura de produto com agrupador | VERIFICAR | knowledge `0d1cf035`/`8b2f264d` confirmam duplicidade; sem fonte de entrega |
| 16 | cb6bf706-7e2e-4b27-adce-994671acf495 | todo | Chat do AI Hub sem streaming: turno com tools espera mi… | VERIFICAR | rota bloqueante em `apps/api/app/routers/ai.py:1653` (sem SSE); sem fonte de entregue |
| 17 | 6df0e91b-4319-4512-9921-ed86c3fdc7a3 | todo | 14.09.26 — Auditar e unificar referências canônicas | MANTER | task de auditoria recente (15/09) com descrição de escopo ativa; sem sucessora |
| 18 | 8b09a19f-fe90-4b2a-a955-5a850d21ba06 | blocked | Teste Qwen 27B — Card “Resumo do Ambiente” na Dashboard | VERIFICAR | sem fonte citável (card não encontrado em `apps/web/src`) |
| 19 | 23793d87-6a2d-4c2d-a959-6caa9dfe7f36 | blocked | Validação e hardening: testes, idempotência, permissões… | VERIFICAR | sem fonte citável |
| 20 | a8ba9042-1cf8-4607-9485-8bc211ff0fe6 | blocked | Auditoria da triagem ac33240a (esta própria task) | MANTER | task em execução ativa (run 7c123e9b); escopo aprovado |

### 4.1 Pendências VERIFICAR

**13 de 20** itens abertos ficaram em `VERIFICAR` sem conclusão embutida (itens 2, 3, 4, 7, 10,
11, 12, 13, 14, 15, 16, 18, 19 da tabela). Cada um exige query anotada antes de qualquer
decisão (cf47f7d0, regra de evidência). Os itens 4 e 7 têm fonte parcial (knowledge registra a
decisão pedida, mas sem evidência de entrega do artefato no fluxo), portanto permanecem em
VERIFICAR.

Nota de método: os rótulos acima são desta auditoria, independentes do inventário da triagem
(`/tmp/inventario_backlog_zero.md`), que é arquivo temporário fora do controle de versão (ver §5,
item 3). Foram usadas como fonte exclusivamente: arquivo:linha no repositório atual, knowledge (com id),
ADR, e a descrição da própria task. Nenhum rótulo foi atribuído por idade/título.

---

## 5. Divergência entre o relatado e o observado (Fase 4)

Sem inferência de causa. Cada linha declara fato com fonte.

| # | Relatado como concluído | Observado agora | Fonte |
|---|---|---|---|
| 1 | Triagem ac33240a "fechou subtasks como done" | Subtask 3 ("Verificação final e registro no Knowledge") está **todo**, não done; subtasks 1 e 2 constam done **sem resultado gravado** | `GET /api/subtasks/ac33240a-f871-4d18-b8d1-78db38ac9dd1` (3 subtasks: done, done, todo — resultados vazios) |
| 2 | "Entrada de Knowledge da triagem não existe (busca por texto e semântica retornam vazio)" | Busca por termo `ac33240a` em `/api/knowledge` retorna **1** entrada: `d72cf19d` (post-mortem, cat=licao, created 2026-10-15 20:11 — **após** o encerramento da run). Busca semântica RAG (`buscar_rag`) retorna `rag:openai_api_key_ausente` (indisponível). Não existe entrada de Knowledge produzida pela triagem | `GET /api/knowledge?termo=ac33240a` (2026-10-15T21:2x); `rag_search.search` 2026-10-16 |
| 3 | Inventário da triagem "não é recuperável" | O arquivo `/tmp/inventario_backlog_zero.md` **existe** (criado 2026-10-14T14:51, 8.670 bytes), mas está fora do repositório e não foi registrado no Knowledge; sua soma interna **não fecha** (corpo: ARQUIVAR 12, MANTER 6, VERIFICAR 13; sumário: ARQUIVAR 11, MANTER 5, VERIFICAR 15 — ambas somam 31) | `ls -la /tmp/inventario_backlog_zero.md`; contagem manual do arquivo |
| 4 | Run 0022528b status `completed` com `summary` de conclusão | O mesmo registro carrega `error` = "BLOQUEIO: incompatibilidade entre plano aprovado e estado real do backlog… 35 vs 31 … Revisão necessária" — estados conflitantes (completed + bloqueio) no mesmo registro | `GET /api/handoffs/runs/0022528b-67e7-4acb-b8c7-22b06b59725f` (status completed; error preenchido; summary) |
| 5 | Run 0022528b "11 ARQUIVAR concluida_fora… 5 MANTER, 15 VERIFICAR" | 12 itens do backlog carregam `archived_reason` com prefixo "Triagem Backlog Zero (run 0022528b)" e `archived_at` 2026-10-14T15:48:26 — **doze**, não onze; e o arquivo de inventário não lista 12+5+15 (ver #3) | `GET /api/backlog/workdev-core?include_archived=true` filtro por prefixo (2026-10-16T01:48) |
| 6 | Tool de listagem (`listar_backlog`) devolve motivo/data de arquivamento | `listar_backlog` em `apps/api/app/routers/ai.py:722-737` devolve apenas id/titulo/status/prioridade/tipo/sprint — **sem** `archived_reason`/`archived_at`; `_ler_task` (ai.py:564-590) também não os expõe | leitura de `apps/api/app/routers/ai.py` + Schemas (`BacklogOut` expõe os campos; a tool não) |
| 7 | Task ac33240a "concluída" | A task está `done` no backlog, mas a subtask 3 (registro no Knowledge) segue `todo` (ver #1) | `GET /api/backlog/workdev-core?include_archived=true` (ac33240a, status done, updated 2026-10-14T16:03) + `GET /api/subtasks/…` |

Síntese factual (sem causa): o que foi registrado como encerrado (run completed, subtasks 1-2
done, task done) difere do que se observa (subtask 3 todo, knowledge sem registro, inventário
com soma interna inconsistente, run com BLOQUEIO no campo error).

---

## 6. Rodapé de invariância (Fase 5)

- Baseline inicial (21:19) == baseline final (01:48) == contagens do item 2. Delta 0.
- Nenhum POST/PUT/PATCH/DELETE foi emitido contra `/api/backlog*`, `/api/subtasks*`,
  `/api/knowledge`, `/api/plans` ou `/api/handoffs/*` nesta auditoria (todas as chamadas foram
  GET ou leitura local).
- `git status --short` após o commit deve listar **apenas** este arquivo
  (`docs/audits/triagem-ac33240a-auditoria.md`); nenhum arquivo de aplicação ou migração muda.
- O revisor independente (qwen) pode reexecutar as fontes citadas (amostra): issues 6 (adrs.py),
  8 (engineering_graph.py), 9 (healthcheck_api.sh), e a consulta do Anexo A.1.

---

## 7. Anexo de evidências

### A.1 — Saída bruta: 34 arquivados (comando + timestamp)

Comando:
`GET http://127.0.0.1:8000/api/backlog/workdev-core?include_archived=true`
Timestamp: `2026-10-15T21:20:21.710913` (e reconsultado em `2026-10-16T01:48:09.074581` sem delta).

Resposta (campos relevantes por item, 34 registros; `archived_reason`/`archived_at` de todos os
34 presentes — nominais na tabela 3.1). Registro-exemplo:

```json
{"id": "fe9520e4-c05d-4d3d-ac5c-bf38f8aea878", "title": "Executar checklist final de saída Lovable/Manus", "status": "archived",
 "archived_at": "2026-10-14T11:37:17.499091+00:00",
 "archived_reason": "concluida_fora: Checklist de saída Lovable/Manus; encerrado fora do fluxo."}
```

### A.2 — Baseline por status (comando + timestamp)

Comando: `GET /api/backlog/workdev-core?include_archived=true` (+ `GET /api/backlog?status=archived`)
Timestamp: 2026-10-15T21:19:56 e 2026-10-16T01:48:09 (idênticos).
Resultado: `{"done": 102, "todo": 17, "archived": 34, "doing": 2, "blocked": 3}` total 158.

### A.3 — Confirmação da Lacuna 1 (Knowledge) — consulta preservada

Comando: `GET /api/knowledge?termo=ac33240a` — timestamp 2026-10-15T21:2x.
Resultado: `[{"id": "d72cf19d-aba9-4dbf-be17-fd54763999c0", "title": "Triagem ac33240a — paralisação no meio, contexto não recuperado e subtask fechada sem artefato", "category": "licao", "created_at": "2026-10-15 20:11:24.758522"}]` — única entrada; criada após a run.

Semântica (buscar_rag): `rag_search.search("Triagem ac33240a arquivar tasks obsoletas")` →
`RagSearchUnavailable: rag:openai_api_key_ausente` (2026-10-16). Indisponível, não vazio.

### A.4 — Subtasks da triagem (comando + timestamp)

Comando: `GET /api/subtasks/ac33240a-f871-4d18-b8d1-78db38ac9dd1` — timestamp 2026-10-15T21:2x.
Resultado (3 subtasks):
- [done] "Inventário com evidência — classificar os 32 itens `todo` + 3 `blocked`…" (sem resultado)
- [done] "Arquivamento em lotes com motivo — executar `atualizar_task(status=archived)`…" (sem resultado)
- [todo] "Verificação final e registro no Knowledge — conferir efeitos…" (sem resultado)

### A.5 — Run 0022528b (comando + timestamp)

Comando: `GET /api/handoffs/runs/0022528b-67e7-4acb-b8c7-22b06b59725f` — timestamp 2026-10-15T21:2x.
`status=completed`; `error` preenchido com o BLOQUEIO (35 vs 31); `summary` com a contagem
11/5/15 e texto de conclusão; `created_at 2026-10-14T14:28:22`, `updated_at 2026-10-14T15:47:21`.

### A.6 — Inventário da triagem (local, fora do repo)

`/tmp/inventario_backlog_zero.md` (2026-10-14T14:51, 8.670 bytes) — 31 linhas; soma interna do
corpo: ARQUIVAR concluida_fora 12 / MANTER 6 / VERIFICAR 13; sumário próprio: 11/5/15.
Arquivo temporário fora do controle de versão; não é fonte canônica desta auditoria.

### A.7 — Fontes de código (arquivo:linha)

- `apps/api/app/routers/backlog.py:29-39` — GET /backlog com `status` + `include_archived`.
- `apps/api/app/routers/backlog.py:42-53` — GET /backlog/{project_slug} (sem filtro status).
- `apps/api/app/schemas/backlog.py:39-40` — `BacklogOut` expõe `archived_at`/`archived_reason`.
- `apps/api/app/routers/ai.py:722-737` — tool `listar_backlog` sem motivo/data.
- `apps/api/app/routers/ai.py:564-590` — `_ler_task` sem motivo/data.
- `apps/api/app/routers/adrs.py:106-111` — `delete_adr` sem remoção de nó no grafo.
- `apps/api/app/services/engineering_graph.py:278-289` — `sync_safely` engole exceções.
- `scripts/healthcheck_api.sh:8` — `LOG=/var/log/workdev-api-healthcheck.log`.
- `docs/perfil/02-ecossistema.md:62` — Agente Pessoal ativo.
- `docs/adr/009-backlog-archived.md` — semântica do status archived / motivos fixos.

---

## 8. Fora de escopo (declarado)

- Nenhum item foi arquivado/desarquivado; nenhuma escrita no backlog.
- Itens arquivados não foram reavaliados; os 3 da família local-code (12/10) não padronizados.
- Nenhuma conclusão por idade/título (proibido por cf47f7d0).
- Nenhuma referência a TaskList/processos de sessão como fonte.
- Causa da divergência: **A CONFIRMAR** (não inferida).