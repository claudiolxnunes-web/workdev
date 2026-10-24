---
titulo: Ecossistema de produtos e projetos
tipo: referencia
dominio: produtos
atualizado_em: 2026-08-31
---

# Ecossistema de produtos e projetos

## A plataforma que governa as outras: WorkDev

**WorkDev** (ou **WorkDev Core**) é a plataforma de engenharia de software
assistida por IA que ele construiu para si. Missão declarada: **governar,
documentar, organizar e monitorar** os projetos do ecossistema — **sem
absorvê-los**.

> Regra fundadora, de 12/07/2026: projetos são **INTEGRADOS** ao WorkDev,
> **nunca migrados para dentro dele**. "O WorkDev INTEGRA plataformas;
> não as substitui."

- **URL:** `https://workdev.bpfconsult.com.br`
- **Stack:** monorepo pnpm + Turborepo em `/opt/workdev` (`apps/api` + `apps/web`).
  Frontend React + Vite + TypeScript + Tailwind + shadcn/ui.
  Backend FastAPI + SQLAlchemy + psycopg3 sobre PostgreSQL, migrações com Alembic.
  O build do frontend é servido pela própria FastAPI.
- **Módulos (9):** Dashboard, Projects, Backlog, AI Hub, Knowledge, Engineering,
  Deployments, Monitoring, Settings.
- **Estado:** em produção via systemd (`workdev-api.service`), 454 testes passando
  em 28/08/2026.

### Subsistemas do WorkDev

| Subsistema | O que faz | Estado |
|---|---|---|
| **Backlog Engine** | toda ideia vira item rastreável por projeto | produção |
| **AI Hub** | estágio de PLAN; chat com function calling; gera planos versionados e ADRs. **Sem acesso a shell.** | produção |
| **Task Decomposition Engine** | Objetivo → Tarefas → Subtarefas → Agentes → Execução | produção |
| **Engineering Graph** | grafo de engenharia em Supabase com Realtime | fases 1, 2, 4 em 21/07; fase 3 em 05/08 |
| **Handoff PLAN → BUILD** | contrato persistente entre plano e execução | produção |
| **Agents** | 5 CLIs em tmux: Claude Code, Codex, Kimi, Qwen, Gemini | produção; Claude e Codex sempre ativos, os demais em standby |
| **AUTO Agent Runtime** | classifica complexidade, roteia agente/modelo, ativa e devolve ao standby | aceito em 28/08; **rebaixado a recomendação consultiva em 30/08** |
| **WorkDev Supervisor** | vigilância Nível 0 somente-leitura: 5 checks, deduplicação, uma chamada de LLM, entrega no Telegram | E1–E7 em 16/08; semana de sombra até 23/08 |
| **MCP `workdev-backlog`** | 4 ferramentas de backlog para os agentes CLI | produção |
| **RAG em Postgres** | ingestor + busca semântica sobre a documentação | produção |
| **Fronteira de privilégio do deploy** | broker root-owned, prova PASS assinada, releases | preparado, **não ativado** |

## O portfólio de produtos

| Produto | O que é | Estado |
|---|---|---|
| **Feed_BPF** | Produto estratégico. Conformidade regulatória para fábricas de ração. É também o **hub de checkout** de todo o BPF Consult — sete funções de cobrança dos outros produtos passam por ele. | Implantado em 3 fábricas em 18/08/2026 |
| **Agro RC CRM** | CRM com clientes reais. Repositório `soil-to-client`, em `/opt/agro-rc`. Código duplicado inline, sem pasta `_shared`. | Produção: 17 usuários, 841 clientes, 1.792 vendas |
| **Audits_BPF** | Auditorias: revisão por IA, chat de legislação, geração de plano de ação | Publicado, **nunca exercitado** — sem primeiro cliente |
| **Nutri Agro Labels** | Gerador de rótulos. Construído do zero, sem herança de template. Ele o considera "o único código sem template, gateway ou duplicação — candidato natural a padrão de referência". | Ativo |
| **NutriGestor CRM** | Primeiro projeto operacional governado pelo WorkDev. Era "AgroGestão CRM" até ser renomeado em 14/07/2026. | 25 nós no grafo |
| **AgroGestão CRM** | Herdado de conta secundária do Lovable. TanStack Start + Nitro SSR. | **O server-side nunca executou**; vive só de frontend + RLS |
| **NutriControle / FeedOptimize** | App de formulação de ração animal | Domínio `feedoptimize.app` ainda em parking |
| **AgroGestor Regional** | Origem Manus, MariaDB, em `/opt/agrogestor-regional` | Rota residual, possivelmente inativa |
| **Portal `create-with-voice`** | `www.bpfconsult.com.br`. Centraliza pagamento. 54 edge functions no Lovable Cloud. | No ar; alvo de migração para Supabase próprio |
| **bpf-suite** | `bpfsuite.bpfconsult.com.br` | No ar |
| **OpenClaw** | Plataforma de inteligência na VPS2 | Ativo |
| **Agente Pessoal** | Bot de Telegram na VPS2, coordenador LangGraph | Ativo |
| **Nutricrm** | React + Vite + Node + Drizzle/Postgres. Deploy em Render e Railway. Local, em `~/projects/Nutricrm`. | Último commit 27/07/2026 |

## Relações entre eles

- O **WorkDev governa** todos, mas não hospeda nenhum.
- O **portal** centraliza o checkout; o **Feed_BPF** é o gateway de cobrança.
- O **AgroGestão** redireciona pagamento ao portal, que fecha no Feed_BPF.

## Armadilha de nomenclatura

Três nomes colidem e **nunca devem ser conflatados**:

- **AgroGestor Regional** — origem Manus, MariaDB
- **AgroGestão CRM** — herdado do Lovable, TanStack
- **Agro RC CRM** — o CRM em produção com clientes reais

Além disso, o projeto Supabase do Feed_BPF aparece rotulado no painel como
"NutriAgro_Lables" — rótulo que ele próprio classificou como
"enganoso a ponto de ser perigoso".

## Ligações

Ver [[03-infraestrutura]] para onde cada coisa roda, [[07-terminologia]] para os nomes.
