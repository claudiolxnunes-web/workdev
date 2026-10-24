---
titulo: Terminologia e vocabulário próprio
tipo: glossario
dominio: vocabulario
atualizado_em: 2026-08-31
---

# Terminologia e vocabulário próprio

Este arquivo existe para que a busca semântica case com as palavras que **ele**
usa, não com sinônimos genéricos.

## Nomes de produto

`WorkDev` · `WorkDev Core` · `BPF Consult` · `Feed_BPF` (grafado também
`feed-bpf`, `feedbpf`, `feed_bpf`) · `Agro RC CRM` (`agro-rc`, repositório
`soil-to-client`) · `Audits_BPF` · `AgroGestão CRM` (`agrogestao`) ·
`AgroGestor Regional` · `NutriGestor CRM` · `NutriControle` · `FeedOptimize` ·
`Nutri Agro Labels` (aparece como `NutriAgro_Lables` no painel) · `Nutricrm` ·
`OpenClaw` · `Agente Pessoal` · `bpf-suite` · `create-with-voice` (o **portal**) ·
`Ngrep BPF` · `Agente4` · `VPS1` / `VPS2`

## Vocabulário do WorkDev

`Backlog Engine` · `AI Hub` · `Knowledge Engine` · `Engineering Engine` ·
`Engineering Graph` · `Graph Explorer` · `Time Machine` · `Insights` ·
`Handoff PLAN → BUILD` · `PLAN` / `BUILD` · `Agents` / `Agent Hub` ·
`AUTO Router` · `AUTO Agent Runtime` · `AUTO v2` · `recomendação consultiva` ·
`standby` · `runtime isolado` · `Sprint 2.3` / `2.3b` / `2.5` ·
`WORKDEV OFFICIAL DOCUMENT` · `Foundation Charter` · `Ecosystem Map` ·
`Camada 1..5` · `Workspace Pessoal` · `Serviços da Plataforma` ·
`Plataforma de Inteligência` · `Sistemas`

## Vocabulário do Supervisor

`WorkDev Supervisor` · `Nível 0` (somente leitura) · `semana de sombra` ·
`semeadura` (`--seed`) · `Fato` / `Achado` · `fingerprint` · `chave_entidade` ·
`bucket` · `coletar` / `avaliar` · estados `novo` / `persistente` / `agravado` /
`melhorou` / `resolvido` · `reforço` · `redação` / `[REDIGIDO]` · `fail-closed` ·
`linha-resumo` / `excedente`

Checks: `critical_stalled`, `plan_without_execution`, `deploy_drift`,
`knowledge_drift`, `agent_health`.

## Vocabulário de deploy e privilégio

`fronteira de privilégio` · `broker` · `prova PASS assinada` · `pós-gate` ·
`break-glass` · `release` / `current` / `previous` · `atributo immutable`

## Bordões — frases que ele repete

- **"relato não é evidência"**
- **"o WorkDev nunca recomeça; ele sempre evolui"**
- **"o WorkDev INTEGRA plataformas; não as substitui"**
- **"desacoplar antes de migrar"**
- **"a ausência de tools é a garantia, não a instrução"**
- **"silêncio não é resolução"**
- **"blocked não é fila"**
- **"o RAG não é fonte"** — é índice derivado do disco
- **"o LLM ordena e explica, não descobre nem age"**
- **"dois modelos de arquitetura por acidente"**
- **"cópia com detector de divergência"**
- **"falso negativo silencioso"** · **"degradação silenciosa"** · **"falha ambígua"**
- **"estrutura morta"** · **"código morto herdado de template"**

## Scripts e aliases que ele nomeia

`deploy.sh` · `verificar.sh` · `verificar-deploy.sh` · `agents.sh` ·
`agents-healthcheck.sh` · `bootstrap_agents.sh` · `workdev_agent.py` ·
`ingestor.py` / `busca.py` · `servidor.py` (MCP) · wrappers `qwen-or`, `kimi-mo` ·
alias `sb-bpf` · hosts SSH `vps1` / `vps2` · alias `liga-work` (GCP)

No PowerShell, perfil `perfil-v2.ps1` com os atalhos `wd`, `wdt`, `wdv`, `wdd`,
`wds`, `wdg`, `wdlog`, `wddiff`, `rag`, `ragup`, `ag`, `aglog`, `wdup`, `wddown`,
e o menu **`Comandos`**.

## Ferramentas MCP e do AI Hub

MCP: `registrar_pendencia`, `listar_pendencias`, `concluir_pendencia`,
`detalhar_pendencia`.

AI Hub: `listar_projetos`, `listar_backlog`, `criar_task`, `decompor_task`,
`listar_subtasks`, `registrar_conhecimento`.
