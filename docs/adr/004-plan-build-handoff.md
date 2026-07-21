# ADR 004 — Separar PLAN no AI Hub e BUILD nos Agents

- Status: aceito
- Data: 2026-07-21
- Projeto: WorkDev Core

## Contexto

O AI Hub já consultava e alterava backlog, subtasks e Knowledge, enquanto a área
Agents expunha os terminais tmux de Codex e Claude Code. Não existia, porém, um
contrato persistente entre planejamento e execução. O contexto era transferido
manualmente, sem versão de plano, aprovação ou trilha de execução.

## Decisão

O WorkDev passa a ter dois estágios com responsabilidades explícitas:

1. **PLAN — AI Hub:** cria plano versionado, critérios de aceite, validações,
   restrições e ADRs. Não executa shell, código ou deploy.
2. **BUILD — Agents:** recebe somente um plano aprovado, executa no ambiente real
   e registra início, progresso, bloqueio, revisão e conclusão.

O PostgreSQL do WorkDev é a fonte oficial. `execution_plans`, `agent_runs` e
`agent_run_events` preservam o contrato e a auditoria. O Engineering Graph no
Supabase recebe projeções compatíveis com os enums existentes
(`AIConversation`, `Task` e `Monitoring`), usadas para atualização em tempo real;
os tipos de domínio continuam sendo Plan, AgentRun e AgentEvent no PostgreSQL e
na API. Polling periódico permanece como fallback.

## Máquina de estados

Planos: `draft → approved`, com `needs_revision` e `superseded`.

Execuções: `queued → running → review → completed`. Uma execução pode passar por
`blocked`, voltar a `running`, ou terminar em `failed`/`cancelled`.

## Segurança

- O envio ao BUILD exige aprovação explícita.
- Conteúdo do plano nunca é concatenado a comandos de shell.
- Secrets permanecem no backend e não entram no prompt.
- A CLI local autentica na API sem imprimir a chave.
- Divergência arquitetural bloqueia o BUILD e retorna ao PLAN.

## Consequências

Há rastreabilidade entre task, plano e execução, e Codex/Claude/Kimi compartilham
o mesmo contrato. O custo adicional é manter estados e eventos consistentes; por
isso transições inválidas são recusadas pela API e estados finais são imutáveis.
