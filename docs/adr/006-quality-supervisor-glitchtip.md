# ADR 006 — Quality Supervisor separado do Supervisor de processo, alimentado pelo GlitchTip

- Status: aceito
- Data: 2026-09-17
- Aprovado por: Cláudio em 2026-09-17
- Projeto: WorkDev Core
- Relacionado: `decisions/2026-09-17-quality-supervisor-glitchtip.md`, PR #1 (`feat/sentry-frontend`)

## Contexto

O WorkDev Supervisor (`scripts/supervisor/`) observa processo — backlog,
deploy, agentes — não a qualidade do que é produzido. Nenhum dos seus checks
lê erro de aplicação. O backend já tinha `sentry-sdk` configurado contra um
GlitchTip self-hosted (`erros.bpfconsult.com.br`); o frontend não reportava
erro nenhum.

## Decisão

1. Frontend instrumentado com `@sentry/react`, em projeto GlitchTip próprio
   (`workdev-web`), separado do backend (`workdev-api`).
2. Novo serviço, `scripts/quality_supervisor/`, irmão do Supervisor de
   processo — não um check a mais nele. Lê issues não resolvidas dos dois
   projetos no GlitchTip e avisa no Telegram o que é novo ou agravado.
   Reaproveita modelo, estado, redação e entrega do supervisor existente.

Separado por serem naturezas de checagem incompatíveis: o Supervisor de
processo não faz chamada de rede, por design, e roda 1x/dia; erro de
produção precisa de resposta em minutos. Nível 0 nos dois: leem e avisam,
não resolvem, não silenciam, não fazem deploy.

## Consequência

Timer instalado (10 min), validado ponta a ponta (entrega real confirmada
no Telegram), mas não ativado — ligar fica como ação operacional separada.
