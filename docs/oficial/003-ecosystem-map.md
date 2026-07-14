# WORKDEV OFFICIAL DOCUMENT
**Documento:** 003 · **Título:** WorkDev Ecosystem Map · **Versão:** 1.1 · **Status:** 🟢 OFICIAL · **Data:** Julho de 2026
> v1.1 (14/07/2026): AgroGestão CRM → NutriGestor CRM; n8n realocado para VPS2. Diagrama visual: docs/oficial/ecossistema.png

## Objetivo
Ecossistema em camadas independentes; cada camada tem responsabilidade específica e nenhuma assume responsabilidade de outra. Garante organização, escalabilidade, baixo acoplamento e evolução contínua.

## Camada 1 — Workspace Pessoal
Ambiente pessoal do engenheiro (NÃO faz parte do produto). Componentes: Google Cloud Workspace, Chrome Remote Desktop, VS Code, Git, SSH, Docker, ferramentas pessoais. Responsabilidade: desenvolver e administrar os projetos.

## Camada 2 — WorkDev Core
O produto principal; toda a inteligência de engenharia. Módulos: Dashboard, Projects, AI Hub, Knowledge Engine, Engineering Engine, Insights. Responsabilidade: organizar todo o ciclo de engenharia de software.

## Camada 3 — Serviços da Plataforma
Serviços compartilhados. Dados: Supabase, PostgreSQL. Código: Git, GitHub. Infra: Docker, Storage, CI/CD. Responsabilidade: serviços técnicos ao funcionamento do WorkDev.

## Camada 4 — Plataformas Externas
**4A Deploy:** Hostinger, Vercel, Netlify — deploy em qualquer plataforma suportada; nenhuma faz parte do núcleo.
**4B Plataforma de Inteligência:** OpenClaw, Agente Pessoal, provedores (OpenAI, Claude, Gemini, Ollama, OpenRouter). O WorkDev consome por interfaces bem definidas; a implementação interna não é escopo do Core.

## Camada 5 — Sistemas
Produtos desenvolvidos com o WorkDev: Feed_BPF, NutriGestor CRM, NutriControle, aplicações futuras, produtos comerciais. Não fazem parte do Core.

## Infraestrutura de Produção (Hostinger)
- VPS1 — Infraestrutura: Docker, Traefik, PostgreSQL, Redis, Evolution API, WorkDev
- VPS2 — Inteligência: OpenClaw, Agente Pessoal, n8n, integrações (Gmail, Calendar, Telegram)

## Princípio de Separação
Toda nova funcionalidade responde: "Em qual camada esta responsabilidade pertence?" Em dúvida, interromper até revisão arquitetural.

## Fluxo Oficial
Workspace Pessoal → WorkDev Core → Serviços da Plataforma → Deploy/Inteligência → Sistemas

## Regra Fundamental
O WorkDev INTEGRA plataformas; não as substitui. Organiza, orquestra e potencializa a engenharia, preservando conhecimento.

## Cláusula Final
Referência arquitetural oficial. Alterações somente mediante nova decisão registrada por ADR.
