# Relatório — Backlog aberto e itens em débito

- **Data da compilação:** 2026-09-02
- **Fonte:** tabela `backlog` do Postgres do WorkDev (fonte oficial). O `backlog.md` exportado em 2026-08-13 está desatualizado.
- **Escopo:** itens com status `todo`, `doing`, `blocked` (exclui `done`).

## 1. Panorama

| Métrica | Valor |
|---|---|
| Itens abertos (total) | 110 |
| `todo` | 103 |
| `doing` | 5 |
| `blocked` | 2 |
| Concluídos (`done`, histórico) | 87 |
| Críticos abertos | 8 |
| Maior tempo sem atualização | 51 dias |

**Estagnação:** a maioria dos itens abertos está parada há semanas; há `doing` com 50 dias sem movimento e `todo` com até 51 dias.

## 2. Por projeto (abertos)

| Projeto | todo | doing | blocked | críticas abertas | mais dias parado |
|---|---|---|---|---|---|
| WorkDev Core | 44 | 3 | 0 | 1 | 51 |
| BPF Suite | 20 | 0 | 0 | 1 | 38 |
| AUDITS BPF | 9 | 0 | 1 | 4 | 28 |
| Agro RC CRM | 8 | 0 | 0 | 2 | 38 |
| NutriGestor CRM | 7 | 1 | 0 | 0 | 51 |
| FeedOptimize | 5 | 0 | 0 | 0 | 7 |
| Infra BPF | 2 | 0 | 0 | 0 | 37 |
| NutriCRM | 2 | 0 | 0 | 0 | 37 |
| Agent Hub Pro | 1 | 0 | 1 | 0 | 9 |
| AgroGestao CRM | 1 | 0 | 0 | 0 | 37 |
| AgroGestor Regional CRM | 1 | 0 | 0 | 0 | 37 |
| Ngrep BPF | 1 | 0 | 0 | 0 | 37 |
| FeedOps | 1 | 0 | 0 | 0 | 21 |
| NutriAgro Labels | 1 | 0 | 0 | 0 | 38 |

## 3. Críticas — ação imediata

| Projeto | ID | Status | Dias parado | Título |
|---|---|---|---|---|
| AUDITS BPF | `82080b7c-413e-449b-8f07-e6616815b4aa` | todo | 28 | [BLOCKER] Validação pré-shutdown Lovable: checklist críticas |
| AUDITS BPF | `2f62c908-74af-4d86-811b-7f28b0e6056b` | todo | 28 | [CRITICAL] IA Gateway: trocar Lovable → provider direto |
| AUDITS BPF | `0669004e-a91f-49d7-a4cb-9f63f6482b91` | todo | 28 | [CRITICAL] Secrets: restaurar Paddle + Sentry |
| AUDITS BPF | `e62e2178-0853-43de-bb29-24f223844c19` | todo | 28 | [CRITICAL] Storage: criar 3 buckets privados + políticas |
| Agro RC CRM | `8f8bdfbf-5925-4fef-a55d-373abd0dd3b0` | todo | 7 | Despublicar soil-to-client.lovable.app |
| Agro RC CRM | `4ec13675-cbe5-46af-abdf-60b1068389a4` | todo | 38 | Reconciliar fonte de verdade e anexos do Agro CRM |
| BPF Suite | `7e44096c-0889-4f32-acda-c4df70c206da` | todo | 38 | Validar auth.users, storage e os seis produtos após restore |
| WorkDev Core | `dbd5ac2c-0d9e-479d-b88a-3441eacf4095` | todo | 20 | Agentes CLI persistem credenciais em texto plano |

## 4. Em andamento (`doing`) e bloqueadas (`blocked`)

| Projeto | ID | Status | Dias parado | Título |
|---|---|---|---|---|
| WorkDev Core | `7151c604-35df-4969-bd9c-7139f19d4d2c` | doing | 1 | Frota de Agentes — Fase 0 (destravar) e Fase 1 (isolamento por git) |
| WorkDev Core | `23745328-ad67-47bc-9b8c-48dc5cc1b6fd` | doing | 1 | Indexar knowledge e backlog no RAG via API, no molde do coletor de ADR |
| WorkDev Core | `55db95a6-c8a5-48b5-a620-5e438fd41084` | doing | 5 | Investigar e mitigar travamento do serviço workdev-api.service |
| NutriGestor CRM | `3c6bedef-c6c5-4e9e-ba4e-ba9be4aa3706` | doing | 50 | IA Comercial |
| Agent Hub Pro | `232e1fd6-9867-477d-bac4-ddbd71062d70` | blocked | 4 | Validar RLS e recriar integrações do Agent Hub Pro |
| AUDITS BPF | `d2591025-05d3-4884-b233-21fdd2714ce6` | blocked | 28 | Executar restore drill e validar RLS do AUDITS BPF |

## 5. Altas (`high`) — em débito

Ordenadas por dias sem atualização.

| Projeto | ID | Dias parado | Título |
|---|---|---|---|
| NutriGestor CRM | `a1572736-d2e3-4bb9-a043-6dd324d3a3d5` | 51 | Dashboard Executivo |
| WorkDev Core | `c46f58bd-eeeb-476d-86a7-c770c3229f78` | 47 | Completar kit da fuga com export data e storage do Lovable |
| NutriAgro Labels | `ca5130f1-626d-4a8d-a9d1-c3d9e0e33625` | 38 | Aplicar pacote de migração do Gerador de Rótulos em staging |
| WorkDev Core | `fe9520e4-c05d-4d3d-ac5c-bf38f8aea878` | 38 | Executar checklist final de saída Lovable/Manus |
| Infra BPF | `041123b9-023e-4b0c-9e45-29f4e813adf6` | 37 | Rotacionar database passwords dos Supabase e remover `/root/*_auth.sql` da VPS1 |
| Agro RC CRM | `7087533f-ecdf-46f5-8603-3154b322250d` | 28 | P2: Limpar `cron.job_run_details` (auditoria) |
| AUDITS BPF | `b61e7f4f-166e-4c43-b864-17b130144b28` | 28 | [HIGH] pg_cron: validar job backup-semanal |
| Agro RC CRM | `ec3bf0ec-97d2-47ca-b35e-0d1439b72b84` | 23 | Ativar hook Send Email no painel do Supabase (Agro RC) |
| Agro RC CRM | `cb858580-db4e-4262-a692-0dcb478a935e` | 22 | Migrar preview-transactional-email com secret próprio |
| Agro RC CRM | `d155de26-91c4-4d5f-84bf-0f3166033a8a` | 22 | Migrar handle-email-suppression para Standard Webhooks |
| BPF Suite | `827a7c40-3239-459b-852e-d9899c94b56b` | 22 | Testar funções de IA e e-mail publicadas |
| WorkDev Core | `cff03174-5de5-4632-a40e-87d1f7aa3956` | 21 | Engineering Graph: corrigir falha silenciosa e reconciliar dados |
| FeedOps | `8b05f194-0930-4dfc-a86d-d55abb1c8894` | 21 | Fundação: schema base, auth, RLS e has_role |
| BPF Suite | `6e78b757-0e58-4ffc-8250-6161fc1202bf` | 18 | Rotacionar PAT do GitHub exposto no remote de /opt/feed-bpf |
| BPF Suite | `eb076bfd-7c8b-415a-a377-cc63e53cebcb` | 18 | Páginas jurídicas declaram Paddle como Merchant of Record |
| BPF Suite | `b1fe8948-65c4-44fa-b040-cb4e305e92b6` | 18 | handle-email-suppression ainda importa pacote privado do Lovable |
| BPF Suite | `b60a8826-c3b8-4812-afc5-f6b6be67df0b` | 18 | _shared/paddle.ts roteia todo o Paddle pelo gateway do Lovable |
| WorkDev Core | `00fdc75b-e604-4340-9c8d-5ccc6a2d8ffa` | 17 | RAG indexa disco, não o Postgres (283 registros fora do índice) |
| Agent Hub Pro | `0cb2dee8-ed95-467c-99a4-58fc2aafaa8a` | 9 | Reordenar modelos AIHub |
| BPF Suite | `dcd41aa4-edd2-4090-b7e0-74a6fdb6735d` | 7 | www.bpfconsult.com.br responde por dois servidores diferentes |
| FeedOptimize | `708281bb-1434-4b7e-805d-f7823f149228` | 7 | Configurar Paddle no FeedOptimize |
| WorkDev Core | `20fde1dd-43e0-4b68-8b24-19a602282abf` | 1 | Refatorar ingestão RAG: coleta de knowledge e backlog |

## 6. Recomendações

1. **Agrupar épicos de desligamento Lovable/Manus** — AUDITS BPF (4 críticas + restore-drill blocked), WorkDev Core (kit da fuga, checklist final) e BPF Suite (Paddle, páginas jurídicas) têm dependências entre si; tratá-los juntos evita retrabalho.
2. **Segurança primeiro:** rotação de senhas de DB (`041123b9`), PAT do GitHub (`6e78b757`) e credenciais em texto plano (`dbd5ac2c`) — as três podem virar um único bloco de higienização de segredos.
3. **Revisar `doing` há 50 dias** (`3c6bedef`, NutriGestor IA Comercial): retomar ou voltar para `todo`.
4. **Unblock AUDITS BPF:** restore drill (`d2591025`) está blocked há 28 dias e o pré-shutdown (`82080b7c`) é literalmente blocker — identificar dependência real e desbloquear.
5. **Triagem do backlog genérico:** títulos sem descrição ("Balance", "P3: arquivar repos") — anexar a épico/ADR ou fechar duplicatas que o `backlog.md` de 08-13 já mostra como ambíguos.
6. **Regenerar `backlog.md`:** o arquivo exportado diverge do Postgres source-of-truth; considerar automação da exportação ou aviso de staleness.

> Gerado por consulta direta a `backlog` + `projects` no Postgres da VPS1.
> Consultas reproduzidas via `psql` com o `DATABASE_URL` de `/etc/workdev/workdev-api.env`.
