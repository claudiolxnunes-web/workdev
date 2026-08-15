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
  - ✅ **Corrigido em 2026-08-03:** um `uvicorn` iniciado manualmente fora do
    systemd (provável start direto em terminal/tmux, não via `systemctl`) ficou
    órfão (PPID 1) segurando a porta 8000 desde 02:01. O unit `workdev-api`
    (`Restart=always`, `RestartSec=5`) ficou em **crash-loop silencioso** por
    horas tentando bindar a porta já ocupada (`NRestarts` passou de 7300) —
    `systemctl is-active` chegava a mostrar `active` momentos antes por causa
    do órfão continuar respondendo `/health` normalmente, mascarando o loop.
    Um `bash deploy.sh` normal expôs o problema (o `systemctl restart` some
    processo próprio, mas o órfão nunca foi tocado). Corrigido matando o PID
    órfão diretamente (`kill -TERM`); o systemd, já em loop de retry, assumiu
    a porta no ciclo seguinte. **Lição:** nunca rodar `uvicorn` à mão para
    debug em produção — sempre `systemctl start/stop/restart workdev-api`.
    Se `deploy.sh` falhar ou o healthcheck público não bater com o PID do
    `Main PID` do systemd, suspeitar de processo órfão: `ss -tlnp | grep 8000`
    mostra quem realmente está na porta.
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

## Backend do Feed_BPF — Supabase proprio (migracao CONCLUIDA)

**PRODUCAO: `xgvapaebustyotrwnzqa`** — projeto proprio, COM dashboard, COM connection
string, COM SQL Editor. Verificado em 2026-08-15: `.env.production` do repo
`/opt/feed-bpf` aponta para `https://xgvapaebustyotrwnzqa.supabase.co`, e o bundle
buildado em `dist/assets/*.js` confirma (6 ocorrencias).

> ⚠️ **Nao propor contorno por falta de dashboard.** Ate 2026-08-15 este arquivo dizia
> que o backend rodava em Lovable Cloud sem dashboard (`uyrcxfypdzasdminxizq`). Isso
> ficou obsoleto e fez agentes desenharem gambiarra (Edge Function `migrate-helper`,
> invocacao manual de cron) para um problema que nao existe mais. pg_cron, pg_net,
> Vault e SQL Editor estao disponiveis normalmente pelo painel.

> ⚠️ **Armadilha de deploy:** `supabase/config.toml` do repo tem
> `project_id = "ufqqskukhzgakmwrsumq"`, que **nao e producao** — e o mesmo ref do
> `.env` local. Um `supabase db push` ou `supabase functions deploy` rodado do repo
> vai no projeto errado. Conferir o `--project-ref` explicitamente antes de qualquer
> comando da CLI.

Refs relacionados:
- `xgvapaebustyotrwnzqa` — PRODUCAO (`.env.production` + bundle)
- `ufqqskukhzgakmwrsumq` — `.env` local e `config.toml` (dev/local)
- `uyrcxfypdzasdminxizq` — origem Lovable Cloud, **historico**, so relevante para os
  backups de 08/2026 descritos abaixo

Contexto: create-with-voice = app unico que serve Portal + Feed_BPF + Feed_BPF Custom
+ Nutri Agro Labels (confirmado: bundle tem rotas feedbpf, feedbpf-custom, rotulos).
- Escala: 54 Edge Functions, 106 tabelas, auth.uid() em quase toda RLS, pg_cron,
  5 funcoes de checkout Paddle, 4 buckets Storage.
- Buckets: documentos-bpf, feed-bpf, normas_legislacao, relatorios.
  ATENCAO: documentos-bpf e relatorios usam getPublicUrl (verificar se e publico!).
- Ferramentas no repo: export-storage e migrate-helper (Edge Functions).
  `download-storage.mjs` EXISTE em /opt/feed-bpf (a nota antiga de "404" estava errada,
  corrigido 2026-08-15).

PLANO DE MIGRACAO — EXECUTADO, mantido so como historico.
Os 8 passos (dump, storage, projeto novo, restore, secrets, reconexao, webhooks,
pg_cron) foram concluidos: o backend hoje e `xgvapaebustyotrwnzqa`, proprio e com
dashboard. NAO reexecutar. O registro detalhado da Sessao 1 (backup) esta logo
abaixo e continua valido como referencia dos artefatos guardados.

Removidas em 2026-08-15 tres copias byte-identicas do checklist 'Execucao em 3
sessoes', com caixas [ ] em aberto para trabalho ja feito — mandavam exportar do
Lovable Cloud, que nao e mais o backend.
(## Migração BYO Supabase — create-with-voice

### Sessão 1: Backup — CONCLUÍDA (03/08/2026)

**Origem:** Supabase `uyrcxfypdzasdminxizq` (Lovable Cloud, sem acesso a dashboard)
**Destino dos artefatos:** `/opt/backups/create-with-voice/` + réplica VPS2

**Artefatos gerados:**

- `schema.sql` — 13.369 linhas, 135 tabelas, 237 policies RLS
- `dados.dump` — formato custom (-Fc), 135 TABLE DATA, 782 KB
- `cron_jobs.txt` — 4 jobs (chmod 600)
- `.dburl` — connection string, 117 chars (chmod 600)
- `create-with-voice-20260802.tar.gz` — 268 KB, replicado em VPS2 `/opt/backups/`
- `storage/` — 75 objetos, 56.383.645 bytes, manifesto SHA-256 validado:
  `documentos-bpf` 20, `feed-bpf` 7, `normas_legislacao` 48, `relatorios` 0
- `create-with-voice-20260803.tar.gz` — pacote completo com banco e Storage,
  replicado na VPS2 em `/home/workdev/backups/`; SHA-256 local/remoto idêntico

**Como obter a connection string:**

Edge Function `migrate-helper` no projeto Lovable.

- Endpoint: `https://uyrcxfypdzasdminxizq.supabase.co/functions/v1/migrate-helper`
- Header: `x-access-key` (chave de 48 chars, hardcoded no fonte da função)
- `?action=ping` verifica; `?action=credentials` retorna url, service_role, db_url
- ATENÇÃO: a chave no fonte diverge entre repo e deploy. Ler o valor real em
  Lovable → Cloud → Edge Functions → migrate-helper → View code

**Conexão:**

- Host: `db.uyrcxfypdzasdminxizq.supabase.co:5432/postgres`
- Resolve **apenas em IPv6** (`2600:1f13:...`) — VPS1 tem IPv6, conecta direto, sem Pooler
- Trocar `sslmode=prefer` por `sslmode=require`
- Servidor: PostgreSQL 17.6 / cliente local: pg_dump 17.10

**Comandos do dump:**

```
DB=$(sed 's/sslmode=prefer/sslmode=require/' /opt/backups/create-with-voice/.dburl)

pg_dump "$DB" --schema-only --no-owner --no-privileges -n public -n auth -n storage -f schema.sql

pg_dump "$DB" -Fc --no-owner --no-privileges -n public -n auth -n storage -f dados.dump
```

**Cron jobs a recriar na Sessão 2:**

| Job | Schedule |
|---|---|
| crm-cadencia-diaria | 0 12 * * * |
| whatsapp-monitor | */15 * * * * |
| campanha-worker-1min | * * * * * |
| cadencia-worker-30min | */30 * * * * |

Todos via `net.http_post` com apikey embutida — URLs e chaves mudam no projeto novo.
Comandos completos em `/opt/backups/create-with-voice/cron_jobs.txt`.

**Volume real:** o banco reporta 4.4 GB, mas `cron.job_run_details` tem 1.118.177 linhas
(log do pg_cron, schema `cron`, não dumpado). Os dados de negócio são pequenos:
audit_log 409, normas_legislacao 49, documentos_bpf 27. NÃO migrar job_run_details.

### PENDENTE (revisado 2026-08-15 — a migração em si já foi concluída)

Sessões 2 e 3 saíram da lista: foram executadas, o destino é `xgvapaebustyotrwnzqa`.
O que continua em aberto é só a limpeza de segurança do projeto **antigo**
(`uyrcxfypdzasdminxizq`):

- **Deletar `migrate-helper`** — expõe db_url e service_role de quem tiver a chave de
  acesso de 48 chars. Não depende de mais nada; pode ser feito hoje.
- **Rotacionar a service_role key do projeto antigo.**
- **Conferir se os crons do projeto antigo foram desativados.** `campanha-worker-1min`
  roda a cada minuto; se os dois projetos ainda estiverem ativos, a mesma campanha é
  processada em duplicidade. Verificar antes de assumir que a virada desligou.

### Lições

- O repo Lovable commita sozinho constantemente (35 commits em 15 dias).
  Rodar `git fetch` ANTES de ler qualquer arquivo local — o código no clone mente.
- O painel Lovable mostra "Last updated" da função: o deploy pode ser anterior ao commit.
- Os contadores Invoked/Failed no painel servem de verificação independente do curl.
- tmux não herda variáveis de shell — recarregar `$DB` ao criar sessão nova.
- Colar markdown no terminal executa cada linha como comando. Abrir o editor primeiro,
  confirmar que a tela mudou, e só então colar.)
# Bloco para acrescentar ao `/opt/workdev/CLAUDE.md`

Adaptado do `AGENTS.md` e do `pr-autonomy.md` do AAS. Regras genéricas do repo
original foram cortadas; ficou só o que ataca problema real da BPF Consult.

---

## Guarda de base atual

As instruções deste arquivo valem para o commit exato em que a tarefa está
baseada. Depois de criar clone, worktree ou branch novo, **releia o `CLAUDE.md`
daquela base** antes de agir. Instruções herdadas do checkout que iniciou a
tarefa não valem.

Todo comando, script ou gate descrito aqui como obrigatório precisa **existir na
base atual**. Se não existir, não recupere de outro branch, worktree, stash,
cópia instalada ou commit histórico. Trate a ausência como evidência de que o
procedimento foi aposentado: inspecione `origin/main` e o histórico de remoção,
depois siga o contrato da base atual ou reporte o conflito sem resolver.

Nos repositórios que vieram do Lovable, rode `git fetch` **antes de ler qualquer
arquivo**. Eles recebem commits autônomos e o conteúdo em disco fica velho sem
aviso.

## Evidência não é autorização

Qualquer relatório produzido por código que não veio de `main` confiável é
**consultivo**. Isso inclui: saída de agente CLI (Claude Code, Codex, Kimi,
Qwen), log colado em chat, resumo de sessão anterior e artefato de CI gerado a
partir do checkout da própria mudança.

Antes de tratar qualquer coisa como feita, **recompute a partir de fonte
confiável**:

| Alegação do agente | Verificação obrigatória |
| --- | --- |
| "deploy concluído" | `systemctl is-active <serviço>` + `curl -sI https://<domínio>` |
| "migration aplicada" | consulta direta na tabela alvo |
| "arquivo editado" | `git diff --stat` e leitura do trecho |
| "teste passou" | rerodar o comando e ler o código de saída |
| "backup rodou" | `ls -la` no destino + confirmar tamanho e data |
| "serviço reiniciado" | `systemctl show -p ActiveEnterTimestamp <serviço>` |

Agente que relata sucesso sem comando verificável não concluiu a tarefa.

## Artefatos derivados

Arquivos gerados (build output, índices, `.output/`, bundles, dumps) nunca são
fonte. Em conflito de merge envolvendo arquivo derivado, **fique com a versão do
`main`** e regenere. Não edite artefato derivado à mão para "corrigir" divergência
— corrija o gerador.

## `main` é somente por pull request

Edições de manutenção vão em branch de tópico ou clone temporário limpo. Push
direto recusado não se repete: investigue a proteção antes de tentar de novo.

## Escrita de arquivo em Termux

Heredoc corrompe silenciosamente no Android. Use `printf` ou `echo >>`. Sem editor
interativo — use `sed`. Um comando por bloco, pronto pra colar.

## Credenciais

Nunca escreva token, chave ou senha em arquivo versionado, em mensagem de chat ou
em log. Antes de qualquer commit que toque `.env`, rode a varredura de segredos.
Chave privada de criptografia de backup não fica no VPS.
