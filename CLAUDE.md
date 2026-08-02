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
- Handoff PLAN → BUILD (v0.5.0): AI Hub cria `execution_plans` versionados e ADRs;
  aprovação e envio criam `agent_runs`; Codex/Claude/Kimi/Qwen acompanham a fila
  na tela Agents e registram eventos em `agent_run_events`. A CLI segura é
  `python3 /opt/workdev/scripts/workdev_agent.py --help`. Postgres é a fonte
  oficial; Plan/AgentRun/AgentEvent são projetados no Engineering Graph usando
  tipos compatíveis com os enums legados do Supabase.
- Kimi Code: CLI oficial instalada globalmente; sessão tmux `kimi` iniciada por
  `scripts/start_kimi_agent.sh`, que usa `kimi-k2.7-code` no endpoint
  `api.moonshot.cn` e lê `MOONSHOT_API_KEY` somente do `.env` do backend.
- Qwen Code: CLI oficial instalada globalmente; sessão tmux `qwen` iniciada por
  `scripts/start_qwen_agent.sh`. DashScope (`DASHSCOPE_API_KEY`) e OpenRouter
  (`OPENROUTER_API_KEY`) ficam ativos no catálogo `scripts/qwen-agent-settings.json`;
  o operador escolhe o provider na inicialização ou pelo `/model`.

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
- Cadastrar os outros 5 projetos (Agente Pessoal, OpenClaw, Feed_BPF,
  NutriControle, NutriGestor CRM) na tabela `projects` do grafo Supabase —
  hoje só o WorkDev Core tem linha lá, o backfill falha pros outros por FK.
- Cascade de exclusão Postgres → grafo (deletar ADR/RFC/Decision não limpa o
  nó órfão em `graph_nodes`).
- Confirmar se o enum `node_type`/`relationship_type` do Supabase aceita os
  valores novos usados pelo `graph_sync` (`Decision`, `HAS_DECISION`,
  `BELONGS_TO` etc.) — não verificado ainda.
- Revisar e commitar o lote "Settings system" do frontend (SettingsPanel,
  testes, vitest.config.ts, scripts/setup-config.sh, docs/settings-system.md)
  — o backend já foi revisado e commitado (42ce003), falta essa parte.
- Dar tools de grafo (`graph_nodes`/`graph_edges`) para o Fable no AI Hub.


## workdev-api.service
- Unit SEM EnvironmentFile — o .env é lido pela app (dotenv), não pelo systemd
- Arquivo real: /opt/workdev/apps/api/.env  (o /opt/workdev/.env NÃO é lido)
- venv: /opt/workdev/apps/api/venv  (sem ponto)
- ExecStart: venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
- User=root
- Teste de carga da variável (NÃO usar /proc/PID/environ — dá 0 mesmo funcionando):
  /opt/workdev/apps/api/venv/bin/python -c "from dotenv import load_dotenv; import os; load_dotenv('/opt/workdev/apps/api/.env'); v=os.getenv('VAR'); print('OK', len(v)) if v else print('AUSENTE')"
- GITHUB_TOKEN: fine-grained, All repos, Contents+Metadata Read-only, sem expiracao

## Build do frontend
- .env.local do Vite tem precedencia e vaza VITE_API_URL=localhost no bundle de producao
- Solucao: renomeado para .env.development; existe .env.production com VITE_API_URL vazio
- Sempre verificar apos build: grep -c "localhost:8000" apps/web/dist/assets/index-*.js  (esperado 0)


## Mapeamento projeto -> repositorio GitHub
(nomes-codigo do Lovable sao opacos; identificados via title do index.html / src/routes)
- WorkDev Core            -> workdev
- Feed_BPF Custom + Nutri Agro Labels -> bpf-solutions-suite (Lovable "BPF Site Sync"; rota /rotulos = gerador)
- Audits_BPF / AuditMAPA  -> friendly-flame-igniter
- Agent Hub Pro           -> rapid-ai-ally
- Site BPF_Consult        -> create-with-voice
- FeedOptimize            -> feedoptimize
- NutriControle Pro       -> nutricontrole-pro
- AgroGestao CRM          -> regional-fixer-charm
- AgroGestor Regional CRM -> Agrogestor-Regional-CRM
- Agente Pessoal          -> agente-pessoal
- Agro RC CRM (producao, slug agro-crm) -> soil-to-client; nutrigestor-crm = migracao parada, Supabase deletado
- OpenClaw                -> sem repositorio
- ATENCAO: doc "meus_programas_bpf.md" secao 2 lista repos clxn/* — conta de TERCEIRO, repos inexistentes. Repos reais: claudiolxnunes-web/*
- WorkDev usa usuario Postgres proprio: workdev_app (NAO evolution). DATABASE_URL=postgresql://workdev_app:...@127.0.0.1:5432/workdev
- NutriGestor/Agro RC CRM: projeto Supabase deletado (custo ~$40/mes). Schema preservado em nutrigestor-crm/supabase/migrations (83 arquivos). Dados reconstruiveis via Power BI da empresa. Recriar com: supabase link + db push.

## Migracao BYO Supabase — create-with-voice (PENDENTE)
Contexto: create-with-voice = app unico que serve Portal + Feed_BPF + Feed_BPF Custom
+ Nutri Agro Labels (confirmado: bundle tem rotas feedbpf, feedbpf-custom, rotulos).
- Roda em LOVABLE CLOUD: Supabase uyrcxfypdzasdminxizq NAO esta em nenhuma conta
  propria — sem dashboard, sem connection string, sem pg_dump. Zero backup hoje.
- Escala: 54 Edge Functions, 106 tabelas, auth.uid() em quase toda RLS, pg_cron,
  5 funcoes de checkout Paddle, 4 buckets Storage.
- Buckets: documentos-bpf, feed-bpf, normas_legislacao, relatorios.
  ATENCAO: documentos-bpf e relatorios usam getPublicUrl (verificar se e publico!).
- Ferramentas que JA EXISTEM no repo: export-storage e migrate-helper (Edge Functions).
  NAO existe download-storage.mjs (404).

PLANO (nesta ordem):
1. Exportar dump: Lovable Settings > Cloud > Export data (nao inclui schema auth)
2. Exportar Storage via Edge Function export-storage
3. Criar projeto Supabase em claudiolx.nunes@gmail.com (org Claudio's Org, mesma
   do WorkDev — evita 5a conta e o token de Management ja alcanca)
4. Restaurar dump no SQL Editor; auth.users via migrate-helper
5. Reconfigurar ~12 secrets (PADDLE_API_KEY, PADDLE_WEBHOOK_SECRET, EVOLUTION_*,
   RESEND_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, CRON_SECRET, LOVABLE_API_KEY)
6. Reconectar Lovable: Settings > Supabase > Connect to an existing project
7. RECONFIGURAR WEBHOOKS (maior risco): Paddle, Google Forms, Evolution
8. Recriar jobs pg_cron (nao vem no dump)

PRAZO: documentos reais de conformidade MAPA comecam em ~2 semanas (meados/08).
Fazer ANTES — hoje sao 26 documentos, depois vira operacao.
