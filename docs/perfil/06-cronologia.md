---
titulo: Cronologia do ecossistema
tipo: cronologia
dominio: historico
atualizado_em: 2026-08-31
---

# Cronologia

Todas as datas vêm de registros datados nos ADRs e notas de sessão.

## 2026

| Data | Marco |
|---|---|
| jun–jul | Fase 1 do WorkDev — fundação: monorepo, FastAPI + React, 9 módulos |
| julho | Foundation Charter e Ecosystem Map redigidos |
| **12/07** | **Decisão fundadora:** projetos são integrados, nunca migrados |
| 13/07 | Sprint 2.3 — Backlog Engine |
| 13/07 | Sprint 2.3b — produção e segurança. `workdev.bpfconsult.com.br` no ar. Primeiro commit no repositório privado: 5.055 linhas |
| 13/07 (noite) | AI Hub v1, com function calling |
| 13–14/07 | Task Decomposition Engine. Primeira decomposição por IA |
| 14/07 | Ecosystem Map v1.1 — AgroGestão CRM renomeado para NutriGestor CRM |
| **21/07** | Engineering Graph fases 1, 2 e 4. ADR do handoff PLAN→BUILD. Kimi Code Agent integrado. Correções de produção |
| 02–03/08 | Backups do portal `create-with-voice`; primeira sessão da migração para Supabase próprio |
| 04/08 | Rotação de credenciais |
| **05/08** | Engineering Graph fase 3 validada — 792 nós no WorkDev Core, 25 no NutriGestor, 3 no Feed_BPF. Projeto `ngrep` suspenso por custo |
| 08/08 | Chave do Resend recriada como `workdev-core` |
| **09/08** | Quatro ADRs no mesmo dia: atualização da VPS1 em blocos verificados; mapeamento das 22 ocorrências de chave do Lovable; mapa de arquitetura dos 4 apps; ajuste do `max-rows` do PostgREST de 1.000 para 50.000 |
| **10–11/08** | **Desacoplamento do Lovable** — IA migrada para a API direta do Google, e-mail para o Resend |
| 13/08 | Backlog exportado com 84 itens (o banco já tinha 179) |
| 14–15/08 | Wrappers de credencial dos agentes CLI; healthcheck a cada 5 minutos |
| **15/08** | RAG em Postgres concluído. MCP `workdev-backlog` em produção. `verificar-deploy.sh` criado. Busca web com Tavily. Licenciamento validado na prática pelo re-grant da Agrocampo |
| **16/08** | Plano do Supervisor e **etapas E1 a E7 implementadas no mesmo dia**. Seed com 17 achados |
| 17/08 | Primeira execução agendada do Supervisor |
| **18/08** | **Implantação do Feed_BPF em três fábricas** |
| 23/08 | Fim da semana de sombra do Supervisor |
| ~26/08 | Expiração prevista do trial das fábricas |
| **28/08** | ADR do AUTO Agent Runtime — ciclo automático PLAN→BUILD→execução→standby, cinco agentes, 454 testes passando |
| **30/08** | **AUTO v2 e recuo estratégico:** o WorkDev deixa de iniciar agente automaticamente como caminho principal; passa a recomendação consultiva, desligada por padrão |
| 31/08 | Limpeza do notebook Windows: espaço livre de 19,3 para 43,5 GB |

## Leitura da trajetória

O ritmo é intenso e documentado: em pouco mais de seis semanas ele saiu de um
monorepo vazio para uma plataforma em produção com governança, grafo de
engenharia, RAG, supervisão automatizada e cinco agentes de IA orquestrados.
O marco de 30/08 é o mais revelador do método: tendo construído a automação
completa, ele a rebaixou a recomendação consultiva — recuo deliberado, não falha.
