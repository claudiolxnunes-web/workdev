# Engineering Graph

## Fluxo de dados

1. Projects, Backlog, Subtasks, Knowledge, ADRs, RFCs e Decisions persistem no
   PostgreSQL principal do WorkDev.
2. Após cada criação, o backend agenda uma sincronização idempotente para
   `graph_nodes` e `graph_edges` no Supabase.
3. Commits, deployments e eventos de monitoring podem entrar por
   `POST /api/engineering/graph/events`.
4. Overview, Timeline, Graph Explorer e Time Machine usam o pacote
   `@workdev/engineering-graph` e recebem mudanças pelo Supabase Realtime.

## Segurança

- O frontend recebe apenas `VITE_SUPABASE_ANON_KEY`/publishable key e tem
  política RLS somente de leitura.
- O Supabase público guarda somente tipos e IDs. Títulos são resolvidos pela
  API autenticada `GET /api/engineering/graph/labels`, evitando expor nomes de
  projetos, tasks, ADRs e RFCs pela chave pública.
- Escritas exigem `SUPABASE_SECRET_KEY` no `.env` de `apps/api`. Essa variável
  nunca pode usar prefixo `VITE_`, ser commitada ou aparecer no bundle.
- `GET /api/engineering/graph/status` informa apenas se a integração está
  configurada; nunca retorna a chave.

## Ativação e backfill

1. Aplicar `supabase/migrations/202607210001_engineering_graph_realtime.sql`
   no projeto Supabase do WorkDev Graph.
2. Criar uma secret key dedicada no Supabase e definir
   `SUPABASE_SECRET_KEY` no backend.
3. Reiniciar `workdev-api`.
4. Executar uma vez `POST /api/engineering/graph/sync`. A operação pode ser
   repetida: nós e relações existentes são reaproveitados.

ADRs/RFCs aceitam `feature_id`, e a tool `registrar_conhecimento` aceita
`task_id` ou `titulo_task`; assim, essas entidades entram no ramo correto do
grafo em vez de ficarem ligadas apenas ao Project.

## Eventos externos

Exemplo de commit ligado a uma task:

```json
{
  "kind": "commit",
  "entity_id": "UUID_DO_COMMIT",
  "project_id": "UUID_DO_PROJETO",
  "parent_entity_id": "UUID_DA_TASK"
}
```

Para deployment, use `kind: "deployment"` e o commit em
`parent_entity_id`. A API exige a autenticação normal do WorkDev.
