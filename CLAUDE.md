# WorkDev Core — Contexto para Claude Code

## O que é
Plataforma pessoal de engenharia de Cláudio (BPF Consult) para governar, documentar e
monitorar seu portfólio de projetos de software. Monorepo pnpm em `/opt/workdev`.

## Stack
- Frontend: `apps/web` — React + TypeScript + Vite + Tailwind + shadcn/ui
- Backend: `apps/api` — FastAPI + SQLAlchemy + psycopg3 (Python), Alembic para migrations
- Package manager: pnpm workspace + Turborepo
- Deploy: `bash /opt/workdev/deploy.sh` → `pnpm build && systemctl restart workdev-api`
- Domínio: https://workdev.bpfconsult.com.br (HTTPS via Traefik + Let's Encrypt)

## Infraestrutura
- **VPS1** (`srv1749939`, IP 2.25.199.80, Ubuntu 24.04): Traefik, PostgreSQL (container
  `postgres`, user `evolution`, db `workdev`), Redis, Evolution API, WorkDev em si
  (`/opt/workdev`).
  - ✅ **Corrigido em 2026-07-21:** `DATABASE_URL` em `apps/api/.env` apontava para o
    IP de bridge Docker `172.17.0.1`, que parou de existir depois de um reboot
    (`evolution_evo-net` migrou para `172.18.0.0/16`, `docker0` foi remapeado para
    `172.16.0.1/24` e ficou down). Isso causava **incidente silencioso em produção**:
    o processo já rodando mantinha conexões antigas do pool vivas, mas qualquer
    conexão nova travava indefinidamente — toda rota `/api/*` que tocasse o Postgres
    ficava pendurada sem erro nem timeout, enquanto `/health` (sem DB) continuava
    respondendo normal, mascarando o problema. Trocado `DATABASE_URL` para usar
    `127.0.0.1:5432` (porta publicada pelo container `postgres` no host) em vez do
    IP de bridge — não depende mais de qual container network o Docker realocar
    após reboot. `workdev-api.service` reiniciado e todas as rotas validadas (200,
    sem travar).
- **VPS2** (`srv1750921`, IP 2.25.201.90): OpenClaw, Agente Pessoal (Telegram
  @Clxn2000bot), n8n.
- **GCP** `workspace-clxn-ia` (e2-standard-2, southamerica-east1-c, projeto
  `balmy-edition-500820-v2`): ambiente dev sob demanda, VSCode remote.

## Bancos de dados — DOIS Supabases diferentes, não confundir
1. **WorkDev Graph** (`cxqfwswartqqwsanceaj`): tabelas `graph_nodes` / `graph_edges`
   do Engineering Graph. Frontend usa `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`
   em `apps/web/.env`.
   - ✅ **Corrigido em 2026-07-20:** `VITE_SUPABASE_ANON_KEY` estava com a
     service_role key (`"role":"service_role"` no JWT), exposta no bundle de
     produção via `VITE_*`. RLS + policy de SELECT público em
     `graph_nodes`/`graph_edges` já estavam habilitadas nessa data (validado por
     SELECT direto via REST). Valor final em uso: a **publishable key nova**
     (`sb_publishable_...`, sistema não-JWT do Supabase — substituto direto da
     anon key em `createClient(url, key)`, revogável individualmente sem
     regerar o JWT secret do projeto). Bundle buildado confirmado sem
     `service_role` nem os JWTs antigos (anon/service_role).
   - ✅ **Legacy API keys desativadas em 2026-07-20T12:31:44Z.** Confirmado por
     teste direto: a antiga service_role key agora retorna HTTP 401
     `"Legacy API keys are disabled"`. As legacy anon/service_role JWT desse
     projeto (inclusive a que vazou no bundle) estão inválidas; só as chaves
     novas (`sb_publishable_...` / `sb_secret_...`) funcionam. Pendência de
     segurança encerrada.
   - ✅ **Engineering Realtime ativado em 2026-07-21:** `SUPABASE_SECRET_KEY`
     configurada em `apps/api/.env` (rotacionada pelo Cláudio no dashboard;
     a `sb_secret_...` antiga estava inválida/de outro projeto — nova validada
     por leitura E escrita direta antes de salvar). `workdev-api` reiniciado.
   - ✅ **Descompasso de UUID corrigido em 2026-07-21:** a tabela `projects`
     do Supabase do grafo tinha só a linha seed antiga do WorkDev Core
     (`id=4224987e-a792-4b80-b571-1c47fc734ca4`, `slug=workdev-core`), que
     nunca bateu com o UUID real do projeto no Postgres do WorkDev
     (`id=c33052ce-b322-4394-9bb8-4e3d786183f1`) — toda tentativa de sync
     falhava com FK violation em `graph_nodes.project_id`. Inserida uma
     segunda linha na tabela `projects` do grafo com o UUID real e
     `slug=workdev-core-pg` (a linha antiga foi mantida intacta, sem
     alterar/deletar, para não quebrar os nós já seedados que referenciam
     o UUID antigo). Sync testado ponta a ponta: criar um ADR via
     `POST /api/adrs` gera o nó correspondente em `graph_nodes` em
     background, confirmado por leitura direta no Supabase.
   - Pendência restante: `POST /api/engineering/graph/sync` (backfill do
     histórico existente) ainda não foi executado — só sincroniza dali pra
     frente. Não confirmado se o enum `node_type`/`relationship_type` do
     Postgres do grafo aceita os valores novos usados pelo código
     (`Decision`, `HAS_DECISION`, `BELONGS_TO`, `DEPENDS_ON` etc.) — se não
     aceitar, esses syncs específicos falham graciosamente (logado, não
     quebra a API) até alguém rodar `ALTER TYPE` no Supabase.
2. **NutriGestor CRM** (`ngrepqqlvglzqnoswfug`): projeto separado, não relacionado
   ao WorkDev.
- Postgres principal do WorkDev (backlog, projects, chat) é o container `postgres`
  na VPS1, não Supabase.

## Módulos relevantes do frontend
- `packages/engineering-graph/`: pacote standalone (types, client, service,
  emitter, index) que fala com o Supabase do grafo.
- `apps/web/src/modules/engineering/`: módulo ativo do Engineering (rotas
  `/engineering` e `/projects/:projectId/engineering`). A antiga
  `apps/web/src/pages/Engineering.tsx` é órfã (não referenciada em nenhuma
  rota) — considerar remover.
- `apps/web/src/components/graph/`: `GraphExplorer.tsx` + `useGraphExplorer.ts`
  (React Flow / `@xyflow/react`). Tem `DEFAULT_PROJECT_ID` como fallback quando
  `project_id` vem vazio da rota.
- AI Hub: chat com Fable/Claude via Anthropic API, function-calling tools sobre
  o Postgres do WorkDev (projects, backlog, tasks) — NÃO tem acesso ao Supabase
  do grafo ainda (melhoria futura na fila).

## Convenções de trabalho
- Ambiente mobile (Termux/SSH): prefira heredoc (`cat > arquivo << 'EOF'`) ou
  scripts Python inline (`python3 - <<'EOF' ... EOF`) a editores interativos —
  paste longo quebra fácil em terminal mobile.
- Sempre rodar `pnpm run build` em `apps/web` antes de considerar uma mudança
  pronta; build passando não significa deploy feito.
- `bash /opt/workdev/deploy.sh` só depois de build limpo E revisão do Cláudio,
  a menos que ele peça explicitamente para rodar.
- Nunca commitar ou expor `service_role`/secret keys — apenas anon/publishable
  no frontend. Se uma secret aparecer em terminal/log, sinalizar para rotação.
- Idioma de trabalho: português (Brasil).

## Pendências conhecidas (não fazer sem pedir)
- Code-split do bundle `apps/web` (>500kB, aviso do Vite — candidato óbvio é a
  rota Engineering por causa do `@xyflow/react`).
- Melhorias de UI no AI Hub (markdown nas mensagens, bolhas de chat, erros
  formatados) — ver missão detalhada se solicitada.
- Dar tools de grafo (`graph_nodes`/`graph_edges`) para o Fable no AI Hub.
