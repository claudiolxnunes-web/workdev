# WorkDev Core

Plataforma pessoal de engenharia da BPF Consult para **governar, documentar, organizar
e monitorar** o portfólio de projetos de software — sem absorvê-los: os projetos são
integrados ao WorkDev, nunca migrados para dentro dele.

Produção: <https://workdev.bpfconsult.com.br>

## O que tem aqui

| Área | O que faz |
|---|---|
| **Dashboard / Executive** | visão do portfólio e métricas DORA |
| **Projects / Backlog** | projetos, backlog, tasks e subtasks |
| **AI Hub** | chat com Claude/Fable via Anthropic API, com tools sobre o Postgres; cria planos de execução versionados e ADRs |
| **Agents** | fila PLAN → BUILD: planos aprovados viram *runs* executadas por agentes CLI (Claude Code, Codex, Kimi, Qwen, Grok, DeepSeek, Gemini) em sessões tmux, com revisão independente e observer |
| **Bancada Local** | modelos locais (llama-server) recebem micro-tarefas e devolvem **propostas**, avaliadas por checagens mecânicas e por um observer via OpenRouter — nada é aplicado ao repositório |
| **Workspace Local** | tela estilo VS Code: explorer + editor só leitura + chat do modelo local, com seleção de linhas → "Adicionar ao chat" |
| **Knowledge / Engineering** | base de conhecimento, ADRs/RFCs/decisões e o Engineering Graph (nós e arestas no Supabase) |
| **Deployments / Monitoring** | histórico de deploys e saúde dos serviços |

## Estrutura

```
apps/
  api/        FastAPI + SQLAlchemy + psycopg3, migrations Alembic
  web/        React + TypeScript + Vite + Tailwind + shadcn/ui
packages/
  engineering-graph/   cliente/tipos do Engineering Graph (Supabase)
scripts/      CLIs dos agentes (workdev_agent.py), Bancada Local, deploy, systemd
docs/         runbooks, contratos e relatórios (deploy: docs/DEPLOY_CANONICO.md)
docs/adr/, decisions/   decisões de arquitetura
knowledge/    lições e registros de sessão (indexados no RAG)
```

Monorepo **pnpm workspace + Turborepo**. Fonte oficial de dados: PostgreSQL do WorkDev;
o Engineering Graph é uma projeção em Supabase.

## Desenvolvimento

Pré-requisitos: Node + pnpm 11, Python 3.12, PostgreSQL.

```bash
# dependências (no servidor, sempre como o usuário workdev — nunca root)
pnpm install --frozen-lockfile

# frontend
cd apps/web
pnpm dev          # Vite
pnpm lint
pnpm test         # Vitest
pnpm build        # tsc + vite build

# backend
cd apps/api
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/alembic upgrade head
venv/bin/uvicorn app.main:app --reload --port 8000
```

### Variáveis de ambiente

- O backend lê o dotenv indicado em `WORKDEV_API_ENV_FILE` (em produção,
  `/etc/workdev/workdev-api.env`). Exige ao menos `DATABASE_URL`.
- O frontend só recebe variáveis `VITE_*` **públicas** (URL e chave *publishable* do
  Supabase). **Nunca** coloque secret/service_role em `VITE_*` — vai parar no bundle.
- Nenhum `.env` com valor real é versionado.

### Testes

```bash
# backend — DSN falso basta: os testes não conectam no banco
printf 'DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/fake\n' > /tmp/test.env
cd apps/api
WORKDEV_API_ENV_FILE=/tmp/test.env venv/bin/python -m pytest tests/ -q

# frontend
cd apps/web && pnpm test
```

No servidor, rode os testes como `workdev`: rodar como root mascara erros de permissão
e pode deixar arquivos de estado com dono errado.

## Deploy

Pipeline com prova assinada — **não** é `build && restart`. Fonte canônica:
[`docs/DEPLOY_CANONICO.md`](docs/DEPLOY_CANONICO.md).

```bash
/usr/local/sbin/workdev-deployctl prepare                       # gate + release + proof_id
/usr/local/sbin/workdev-deployctl approve <proof_id> --actor <nome>
bash /opt/workdev/deploy.sh <proof_id>                          # promove, reinicia, rollback automático
```

O `prepare` empacota só o que está **commitado**, e o gate exige árvore limpa.
Use sempre o controlador instalado, nunca a cópia de `scripts/deploy/`.

## Agentes

- Contexto obrigatório para qualquer agente: [`CLAUDE.md`](CLAUDE.md) e
  [`AGENTS.md`](AGENTS.md).
- CLI segura para registrar estado de runs: `python3 scripts/workdev_agent.py --help`.
- Bancada Local: [`docs/bancada-local/`](docs/bancada-local/) — inclui o prompt do
  planejador de micro-tarefas e o comparativo de observers.

## Histórico

A crônica do projeto está em [`docs/HISTORIA.md`](docs/HISTORIA.md).
