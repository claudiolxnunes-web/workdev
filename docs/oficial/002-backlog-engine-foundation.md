# WORKDEV OFFICIAL DOCUMENT
**Documento:** 002 · **Título:** Foundation of WorkDev — Backlog Engine · **Versão:** 1.0 · **Status:** 🟢 OFICIAL (implementado no Sprint 2.3)

## Objetivo
Transformar o WorkDev de Catálogo de Projetos em Plataforma Operacional de Engenharia — que sabe o que precisa ser feito, quem faz, o que está bloqueado, prioridades, dependências e qual IA ajuda melhor.

## Problema que resolve
Ideia → anotação → WhatsApp → bloco de notas → esquecimento. O Backlog Engine elimina isso: toda ideia vira item rastreável.

## Conceito
Cada projeto possui backlog próprio (Feed_BPF, CRM, OpenClaw... cada um com seus itens).

## Entidade backlog (campos mínimos da spec)
id, project_id, title, description, priority (enum), status (enum), owner, created_at, updated_at
> Implementação adicionou: type, effort, sprint, rank.

## Estados
Básico: BACKLOG→TODO→DOING→REVIEW→DONE (implementado: todo/doing/blocked/done)
Futuro: IDEA→DISCOVERY→ARCHITECTURE→BACKLOG→TODO→DOING→TEST→REVIEW→DEPLOY→DONE

## Prioridades
P1 Crítica (bloqueia) · P2 Alta (impacta produtividade) · P3 Média · P4 Baixa

## API inicial
GET/POST/PATCH/DELETE /api/backlog — ✅ implementada (+ PATCH /{id}/status)

## Integração com IA
Sugestões de sequenciamento por dependências e padrões pessoais (ex: "resolver OAuth antes do Telegram"; "tarefas de banco rendem de manhã").
> Implementado além da spec: IA cria e decompõe tasks (AI Hub, Sprint 2.5).

## Memória por item (A IMPLEMENTAR — diferencial)
Cada item deve armazenar: decisões, alternativas descartadas, erros, soluções aplicadas, tempo gasto. Ex.: "RLS bloqueando → tentativa 1 (authenticated) falhou → tentativa 2 (policy por organization_id) funcionou." Conhecimento reutilizável pelos agentes.

## Ciclo de melhoria contínua (coração do projeto)
Planejar → Executar → Medir → Aprender → Melhorar → Planejar novamente.

## Primeiros projetos operacionais
NutriGestor CRM (1º), OpenClaw (2º, integrado ao Agente Pessoal na VPS2), Feed_BPF (estratégico: aposentadoria e monetização).

## Resultado esperado (visão)
"Projetos ativos: 3 · Backlog: 47 · Em andamento: 8 · Bloqueados: 2. Sugestão do sistema: resolver OAuth Google antes do Telegram."
