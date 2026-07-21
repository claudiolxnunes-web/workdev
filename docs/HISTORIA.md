# WorkDev — Memória do Projeto
> Crônica completa, da fundação ao presente. Atualizar a cada sprint.

## O que é o WorkDev
Plataforma de engenharia pessoal da BPF Consult (Cláudio Nunes). Missão:
**governar, documentar, organizar e monitorar** os projetos do ecossistema —
sem absorvê-los. Decisão arquitetural fundadora (12/07/2026): projetos como
NutriGestor CRM são INTEGRADOS ao WorkDev, nunca migrados para dentro dele.

## Ecossistema
- VPS1 (srv1749939, Hostinger): Traefik, PostgreSQL, Redis, Evolution API,
  WorkDev (/opt/workdev)
- VPS2 (srv1750921, Hostinger): OpenClaw, Agente Pessoal (Telegram), n8n
- GCP workspace-clxn-ia: dev sob demanda (VSCode remoto, Claude Code)
- Projetos governados: WorkDev Core, NutriGestor CRM, Agente Pessoal,
  OpenClaw, Feed_BPF, NutriControle

## Fase 1 — Fundação (jun–jul/2026)
- Monorepo pnpm workspace + Turborepo em /opt/workdev (apps/api + apps/web)
- Frontend: React + Vite + TypeScript + Tailwind + shadcn/ui
- Backend: FastAPI + SQLAlchemy + psycopg3 sobre PostgreSQL (container
  postgres, db workdev, user evolution)
- 9 módulos visuais: Dashboard, Projects, Backlog, AI Hub, Knowledge,
  Engineering, Deployments, Monitoring, Settings (inicialmente mockados)
- Tabela projects (16 campos) + endpoints GET /api/projects[/{slug}]

## Sprint 2.3 — Backlog Engine (13/07/2026, madrugada)
1. Limpeza: removido app/routers/main.py duplicado; model Project completado
   e espelhado com o banco (tipos exatos, unique slug, server_defaults)
2. Alembic instalado; env.py configurado (.env + models); baseline
   e963c5ccdea8 + stamp; "alembic check" limpo como critério de sanidade
3. Tabela backlog via migration 9482064eb825 (FK projects CASCADE, campos:
   type/priority/status com convenções, effort, sprint, rank)
4. API v0.2.0: 6 endpoints CRUD backlog (+ atalho PATCH /{id}/status)
5. Convenções: type=feature|bug|chore|infra; priority=low|medium|high|
   critical; status=todo|doing|blocked|done

## Sprint 2.3b — Produção e segurança (13/07/2026)
1. Descoberto uvicorn em terminal com --reload exposto em 0.0.0.0 (UFW
   inativo!) → criado workdev-api.service (systemd, Restart=always),
   rebind 127.0.0.1
2. X-API-Key: middleware exige header em /api (chave em .env WORKDEV_API_KEY)
3. Traefik: adicionado file provider (--providers.file em /opt/traefik/
   dynamic, montado no container); rota workdev.yml → http://172.17.0.1:8000
4. API rebind para 172.17.0.1 (ponte Docker; invisível à internet)
5. DNS GoDaddy: A workdev → 2.25.199.80 (typo "wokdev" atrasou o Let's
   Encrypt; corrigido + restart traefik = certificado emitido)
6. https://workdev.bpfconsult.com.br no ar (HTTPS válido, API 401 sem chave)
7. Frontend: build de produção servido pela PRÓPRIA FastAPI (mount /assets +
   fallback SPA para index.html); tmux do Vite aposentado
8. Same-origin: middleware libera sec-fetch-site=same-origin → dashboard não
   precisa de chave embutida (fim do VITE_API_KEY; .env do web removido)
9. deploy.sh: pnpm build + systemctl restart workdev-api
10. Git: .gitignore (.env, venv, dist...), commit 5055 linhas, repo GitHub
    privado claudiolxnunes-web/workdev (deploy key vps1, write access)

## AI Hub v1 (13/07/2026, noite)
- SDKs openai + anthropic instalados; escolhido Claude (claude-sonnet-4-6)
- Router ai.py: POST /api/ai/chat com function calling (loop até 5 passos)
- Tools iniciais: listar_projetos, listar_backlog, criar_task
- Frontend AIHub.tsx: chat (histórico em memória do navegador)
- Primeiro teste: listou os 8 itens do NutriGestor em tabela, perfeito
- Kanban: modal + New Task, mover por clique, botão ✕ deletar (confirm)

## Sprint 2.5 — Task Decomposition Engine (13–14/07/2026)
- Visão: sair de Projeto→Tarefa para Objetivo→Tarefas→Subtarefas→Agentes→
  Execução (fundação de plataforma agêntica)
- Tabela backlog_subtasks (criada manualmente; regularizada no Alembic via
  model espelhado + __table_args__ com nomes reais dos índices idx_* +
  revision de referência 7c6e17952774)
- Campos-chave: execution_order (sequência), assigned_agent e result
  (reservados para execução por agentes)
- API: GET/POST/PATCH/DELETE /api/subtasks
- ai.py v2 (reescrito limpo): + tools decompor_task e listar_subtasks;
  o LLM decide as subtasks e grava ordenadas
- TaskDetail.tsx: clique no card abre painel (badges, subtasks com checkbox,
  progresso N/N, botão Avançar status)
- Marco: primeira decomposição por IA — "IA Comercial" em 8 subtasks
  arquitetadas pelo Claude (multi-tool: criou + decompôs num turno)

## Procedimentos padrão
- Deploy frontend/api: /opt/workdev/deploy.sh
- Nova tabela: model → import no alembic/env.py → alembic check →
  revision → upgrade/stamp → check limpo
- Fim de sessão: git add -A → conferir nenhum .env staged → commit → push
- Acesso: dashboard sem chave (same-origin); externos com X-API-Key
- Terminal Hostinger embaralha colagens grandes → heredocs em partes,
  ou patches via sed/python3

## Engineering Graph — fases 1, 2 e 4 (21/07/2026)

- Modelo e migration Supabase documentados para `graph_nodes`/`graph_edges`,
  com RLS somente leitura no frontend e publicação Realtime.
- `@workdev/engineering-graph` consolidado com mutations, queries, timeline,
  eventos, Overview e testes unitários.
- Engineering Module completo: Overview, Timeline, Graph Explorer, ADRs,
  RFCs, Decisions, visualizações por Feature/Release e Time Machine.
- ADRs e RFCs agora podem ser ligados a Features, e Knowledge a uma task do
  backlog; migrations PostgreSQL `b18c3f9e7210` e `af39d82c1107` aplicadas,
  com Alembic sem drift.
- Backend preparado para sincronizar automaticamente Project, Task, Subtask,
  Knowledge, ADR, RFC, Decision, Commit, Deployment e Monitoring.
- Fase 3 permanece bloqueada apenas para ativação: falta configurar uma
  `SUPABASE_SECRET_KEY`, aplicar a migration Realtime no Supabase e executar
  `POST /api/engineering/graph/sync` com os IDs reais do PostgreSQL.

## Backlog de evolução (registrado)
- Persistir histórico do AI Hub; auto-refresh do kanban
- Tool node agente_workdev no coordenador LangGraph do VPS2 (voz→backlog)
- UFW + reboot kernel VPS1 (janela calma)
- Módulo Knowledge real (este arquivo é o embrião)
- assigned_agent ganhar vida: agentes executando subtasks
