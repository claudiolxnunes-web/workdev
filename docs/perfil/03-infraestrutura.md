---
titulo: Infraestrutura e operação
tipo: referencia
dominio: infraestrutura
atualizado_em: 2026-08-31
---

# Infraestrutura e operação

## Servidores

**VPS1 — `srv1749939`, Hostinger, Ubuntu 24.04, IP `2.25.199.80`**
Camada de infraestrutura. Docker, Traefik, PostgreSQL, Redis, Evolution API
(WhatsApp) e o WorkDev em `/opt/workdev`. Nove containers, cerca de dez
aplicações com clientes ativos. **Sem ambiente de staging.** 2 GB de swap
provisionados com `vm.swappiness=10`.

**VPS2 — `srv1750921`, Hostinger, IP `2.25.201.90`**
Camada de inteligência. OpenClaw (`/opt/openclaw`), Agente Pessoal do Telegram,
n8n, integrações com Gmail/Calendar/Telegram, GlitchTip em
`erros.bpfconsult.com.br`.

**GCP `workspace-clxn-ia`**, zona `southamerica-east1-c`
Máquina de desenvolvimento sob demanda, ligada pelo alias `liga-work`, com
desligamento automático às 23:00 de Brasília.

## Bancos de dados

- **PostgreSQL do WorkDev:** `127.0.0.1:5432/workdev`, usuário `workdev_app`.
  Treze tabelas, incluindo `projects`, `backlog`, `execution_plans`,
  `agent_runs`, `agent_run_events`, `adrs`, `knowledge`, `chat_sessions`.
- **PostgreSQL do RAG:** container `rag-postgres` em `127.0.0.1:5433`,
  **pgvector com índice HNSW**, tabela `documentos`. Compose em
  `/opt/rag-postgres/docker-compose.yml`. Ingestão a cada 5 minutos por timer.
- **Supabase:** quatro contas, oito projetos. Um PAT por conta.

### Mapa de projetos Supabase (não confundir)

| Ref | Projeto |
|---|---|
| `xgvapaebustyotrwnzqa` | BPF Suite / Feed_BPF |
| `ufqqskukhzgakmwrsumq` | Nutri Agro Labels (rotulado como "NutriAgro_Lables") |
| `ngrepqqlvglzqnoswfug` | NutriGestor CRM — **suspenso por decisão de custo** |
| `cxqfwswartqqwsanceaj` | WorkDev Core / Engineering Graph |
| `ilvfwbtfjtnihtsuuzcb` | Agro RC CRM |
| `dmemealywssefvohyobt` | Audits_BPF |
| `nnwlqpgsqhtyqliwufgw` | AgroGestão CRM |
| `tebrkrbfsjquqpckslks` | NutriControle / FeedOptimize |

Há um cron de heartbeat diário (6h UTC) em todos os projetos de free tier, com
tabela `heartbeat` e RLS anônima, para evitar pausa automática.

## Serviços externos

- **DNS:** GoDaddy para `bpfconsult.com.br`; Namecheap para `feedoptimize.app`.
- **E-mail:** Resend, **uma única chave `workdev-core`** para toda a plataforma.
  SPF e DKIM no GoDaddy. `send_delay_ms` ajustado de 200 para 600 por causa do
  limite padrão de 2 envios por segundo.
- **IA:** Anthropic (`claude-opus-5`), Google Gemini pelo endpoint compatível com
  OpenAI, OpenAI, OpenRouter (Qwen), Moonshot (Kimi K2.7).
- **Busca web:** Tavily, plano Researcher.
- **Pagamento:** Paddle (Seller ID 340394), Pix manual, Asaas planejado.
- **Observabilidade:** Sentry hospedado para os apps de produção; GlitchTip na
  VPS2 para o WorkDev.

## Padrões de deploy

- `deploy.sh` = `pnpm build` + `systemctl restart workdev-api`.
  **Constrói a partir da árvore de trabalho, não de um commit** — daí o gate.
- Gate obrigatório: `bash verificar-deploy.sh && bash deploy.sh`.
  O verificador bloqueia build quebrado, sintaxe inválida, segredo versionado e
  mais de um processo na porta 8000; avisa sobre arquivo sem commit.
- API escuta em `127.0.0.1:8000` atrás do Traefik. Já esteve em `172.17.0.1`
  (bridge do Docker) e quebrou após reboot — lição registrada.
- Autenticação por middleware `X-API-Key` nas rotas `/api`.
- Nova tabela: model → import no `alembic/env.py` → `alembic check` → revision →
  upgrade → check limpo.
- Fim de sessão: `git add -A` → conferir que nenhum `.env` está staged → commit → push.

## Unidades systemd

`workdev-api`, `workdev-agents`, `workdev-agents-health.timer`, `workdev-mcp`,
`workdev-rag-ingest.timer` (a cada 5 min), `workdev-supervisor.timer`
(diário, 10:00 UTC = 07:00 Brasília, com `Persistent=true`),
`workdev-supervisor-falhou.service` como `OnFailure`, e `agrogestao` na porta 3010.

## Chaves SSH

- Chave ED25519 `vivobook-claudio` no ASUS VivoBook, autorizada em VPS1 e VPS2.
- Chave antiga `id_ed25519_vps1` em HD externo, autorizada só na VPS1.
- Chave `note-antigo`, gerada no notebook antigo e inserida na VPS1 via Termux.

## Pendências de higiene registradas por ele

- Backups em dois lugares (`/opt/backups/postgres/` e `/home/workdev/backups/`) —
  consolidar em um só.
- Política de `main` só por PR existe no `CLAUDE.md`, mas na prática ninguém abre PR.
- Fronteira de privilégio do deploy preparada, não ativada.
