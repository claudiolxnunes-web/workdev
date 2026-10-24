# Backlog — WorkDev Core

Exportado em 2026-08-13 20:58 — 84 itens.

## Critical

| id | título | prioridade | status |
|---|---|---|---|
| `dbd5ac2c-0d9e-479d-b88a-3441eacf4095` | Agentes CLI persistem credenciais em texto plano | critical | todo |
| `f13f513e-0887-4055-9d28-31c02f82ba3e` | Configuração Final da Plataforma — Segurança, Infra e WorkDev Core | critical | done |
| `afbc1aa9-0b0b-49be-a267-7bbd259e5dc1` | Detectar e responder aprovação pendente nos agentes | critical | done |
| `b1eba355-7720-4700-bc16-633670cc07fa` | Feature: Project Workspace v0.5.0 | critical | done |

## High / Alta

| id | título | prioridade | status |
|---|---|---|---|
| `55c48bc5-81aa-4df2-84c7-8e2613232560` | Atualizar descrição do projeto BPF Suite | high | todo |
| `159ce2a3-04b6-42e4-af82-5c4c7c241d6b` | Backup diário automatizado do Postgres (pg_dump via cron + cópia fora do VPS) | high | done |
| `4c04b205-54b9-436c-b461-336fb0d54120` | Completar abas de projeto no WorkDev — Monitoring, Database, Repository, AI e Engineering Graph | high | done |
| `c46f58bd-eeeb-476d-86a7-c770c3229f78` | Completar kit da fuga com export data e storage do Lovable | high | todo |
| `7380f2f5-ce04-458d-99e9-42f9f3fc2d9b` | Conectar módulo Backlog do frontend | high | done |
| `d21f9c89-4590-4843-84ff-ce7642c2c82b` | Confirmar identidade de Nutri_Agro Labels: modulo do BPF Suite ou mesmo produto que Gerador de Rotulos? | high | done |
| `c4b54b6c-3130-4b8e-b1e0-ea09c6fa39a8` | Create Settings page for WorkDev Core | Alta | todo |
| `be5a3afe-b32a-4da8-9516-baf3a6455acf` | Criar task para implementar Settings (Centro de Configuração Global) no WorkDev | High | done |
| `1cf7d633-103f-4e30-9498-5dcd8c9f24df` | Dropdown de seleção de modelo no AI Hub | high | done |
| `6ba42f4a-6efb-4baf-9a09-25de8934d50c` | Engineering Graph — Fase 1: Modelo de Dados | high | done |
| `5a0603ac-50cc-4b37-9146-f59f3dd66940` | Engineering Graph — Fase 2: Graph Service | high | done |
| `c28ca32c-121f-4e75-bcc2-85a3a1f83233` | Engineering Graph — Fase 3: Integração Automática | high | blocked |
| `cff03174-5de5-4632-a40e-87d1f7aa3956` | Engineering Graph: corrigir falha silenciosa e reconciliar dados | high | todo |
| `5e6857dc-2021-4315-9f5d-d6369c29662a` | Enviar prompt pela UI (POST /api/agents/{session}/send) | high | done |
| `fe9520e4-c05d-4d3d-ac5c-bf38f8aea878` | Executar checklist final de saída Lovable/Manus | high | todo |
| `5aa32f40-ed19-4952-81a5-c7b6a9ee8d61` | Expor API via Traefik + X-API-Key | high | done |
| `2975c813-67bf-480c-b57c-b90965491946` | Feature: Engineering Module | high | done |
| `2fe2373d-76e8-413d-b681-006de8173789` | Fix: minimap do React Flow sem estilo no tema dark (retângulo branco) | high | done |
| `038596de-e3bd-45a9-a6f8-8ae8b2ceee60` | Fix: nó duplicado no grafo (dedup por ID antes de montar array de nodes) | high | done |
| `8ef15834-6682-4206-9429-829c61d3dfba` | Fix: truncamento de labels cortando início do texto nos nós do grafo | high | done |
| `42ddf839-138e-4027-b09a-7e678bee5ce1` | Fixar acesso ao Postgres de forma estável — publicar 5432 no 127.0.0.1 via compose ou IP estático na evo-net, pois o IP do container muda a cada reboot | high | done |
| `55db95a6-c8a5-48b5-a620-5e438fd41084` | Investigar e mitigar travamento do serviço workdev-api.service | high | done |
| `ebb58d94-7299-4012-9624-ec34f1e6191b` | Knowledge Engine MVP — tabela knowledge (categoria: decisão/lição/solução/referência) + tools registrar_conhecimento e buscar_conhecimento no AI Hub | high | done |
| `95a23b01-eb6e-4ed8-844b-cc3621933313` | Package: Engineering Graph Service | high | done |
| `7ec4cffb-d6cd-4c43-af93-5c7096559a37` | Persistência de conversas do AI Hub (tabelas chat_sessions/chat_messages no Postgres, endpoint grava histórico, frontend lista sessões e restaura conversa ao navegar) | high | done |
| `929f1129-fb50-4a5b-9891-151f4ca1a736` | Planejar e ativar UFW (liberar 22/80/443 antes) | high | done |
| `bb956299-7623-4f86-a678-8d4f69124f63` | Página Knowledge no dashboard — cards por categoria com cores, filtro, busca e visualização do conteúdo markdown, com endpoints REST GET /api/knowledge | high | done |
| `818a210e-cbca-46d0-b0fc-0ca6d355e990` | Refatorar visualização do Engineering Graph (GraphExplorer) | high | done |
| `76864947-7033-444b-ac77-93bd4a37a3b7` | Refatorar visualização do Engineering Graph (GraphExplorer) | high | done |
| `397224a7-2900-4297-a66b-a1a411c28092` | Registrar fechamento de sessão 27/07/2026 — correções, limpeza de custos e heartbeat Supabase | high | todo |
| `6d8c38f9-3b52-4ee1-8a6c-e557aaa93cd0` | Registrar migrações Lovable→Supabase e inventário de produtos CRM/apps (25-26/07/2026) | high | done |
| `dbe3c495-cb5a-4e1b-979c-d2ac9b47d5ea` | Regra de permissão inoperante no Claude Code | high | done |
| `d5e081a0-cdee-4fde-9f0f-4e2d5cf81574` | Settings: AI Providers - conectar com endpoint /api/ai/providers já existente | high | done |
| `8bb06ab9-25bd-412b-b7ac-5e456c772aa4` | Validar e corrigir configuração de IP na DATABASE_URL | high | done |
| `52816e04-c804-4643-94f1-f9c88e92dd0d` | migração dados Lovable/Manus | high | done |

## Medium

| id | título | prioridade | status |
|---|---|---|---|
| `5302fb3f-89e4-4af4-b569-41cd0acf2b30` | AI Hub / painel de Planos não permite reprovar/cancelar/arquivar um plano em Draft pela UI — apenas aprovar. Implementar ação de descarte explícito para evitar acúmulo de planos obsoletos na fila. | medium | done |
| `e8d05708-8b52-4683-b3a0-041857c98840` | API nao tem endpoint POST para /api/knowledge - so GET existe. Implementar criacao de entradas de conhecimento via API. | medium | todo |
| `a8530d88-4886-469a-a0ff-48e91dfae345` | Adicionar provider Ollama Cloud ao AI Hub | medium | done |
| `1b886949-c6fe-40af-8213-07c62c5ce747` | Backup fase 2 — upload offsite (rclone/B2) + criptografia (gpg/age) + alerta de falha | medium | done |
| `0f26d99f-d704-4bd5-afa9-ad3bee678997` | Balance | medium | todo |
| `5ce32b36-accd-42b7-a316-8fd86c4e69ae` | Dar vida à aba Monitoring | medium | done |
| `c1cd6c6c-b0af-46b5-8f3a-35b9f0325215` | Dashboard: substituir conteúdo estático por dados reais | medium | done |
| `fc87444e-3544-4e31-9589-1aef62dc8420` | Definir ChatGPT como IA de preferência no AI Hub | medium | done |
| `61eb078f-90c4-493a-b1c8-78662295ed53` | Engineering Graph — Fase 4: Graph Explorer + Time Machine | medium | done |
| `4afa4f72-ae07-4ed0-b920-b5cb655b685b` | Engineering Graph: cadastrar os outros 5 projetos na tabela projects do grafo | medium | todo |
| `c3f1caf6-2ab4-4d05-9067-d94a7fbbb33e` | Engineering Graph: cadastrar os seis projetos migrados e executar backfill | medium | todo |
| `198527b7-9ac7-4d67-9a9c-93797365326b` | Engineering Graph: confirmar enum node_type/relationship_type do Supabase aceita Decision/HAS_DECISION/BELONGS_TO etc | medium | todo |
| `d5fd697f-4796-4501-a1c7-af1f6cf9024e` | Fechamento de sessão de infra 03/08/2026 — migrations feed-bpf, cron, restore, WORKDEV_API_KEY, deploy.sh | medium | done |
| `667834de-1c16-49c1-8d0b-4aa0ddf7f8d0` | Fix: nós exibindo hash de ID em vez do título (fallback e busca de título real) | medium | todo |
| `8728229a-bba6-428a-bf2c-1dfbad66ad39` | Implementar POST /api/knowledge | medium | todo |
| `0d8b123f-17ec-42ef-a18e-5ddde6c09ea9` | Lição pós-reboot — bind 172.17.0.1 nunca existiu (rede real era a bridge evolution_evo-net), UFW barrou tráfego interno, IP do Postgres mudou no boot | medium | done |
| `2a173cbd-c0b9-479b-ad28-4607333ff795` | Modal Nova Task sem campo de descricao | medium | todo |
| `ba455183-6ae1-430c-8a3c-394453d0050b` | Modal perde estado ao sair da aba | medium | todo |
| `cccf6901-ee81-4408-81fb-d8f4b3d6e948` | Modo painel para mobile na aba Agents | medium | done |
| `b74107e9-8cf0-418c-a5a1-a6320f6aed29` | Monitoring: conectar com checagem real de serviços | medium | done |
| `ca35fabe-aba9-4998-a680-5560bb847b2c` | NewProject: implementar wizard funcional (form state + criação real) | medium | done |
| `11130a30-637d-4354-9ff4-6e1cdfef7c87` | P3: Arquivar ~14 repos legados + renomear vars supabase-db.env | medium | todo |
| `411f35b3-cb3a-414a-b573-c0ea5f20f3cd` | ProjectDetails: tornar página dinâmica por projeto | medium | done |
| `50d4e029-ed03-440f-bc5c-2d5504d9ccd7` | Provisionar swap na VPS1 | medium | todo |
| `f9a2b754-12f4-4627-af6c-173c8a63b9a8` | Reboot VPS1 (kernel 6.8.0-134 + docker.service) | medium | done |
| `8bac3174-8bdb-4432-9ca4-84db926160a0` | Relatório de Execução padronizado do Fable | medium | todo |
| `1d7212f9-e69e-479a-a33d-f2b8b5987bc5` | Revisar e commitar lote Settings system (SettingsPanel, testes, vitest, scripts) | medium | todo |
| `c8499d8d-5a36-4b3f-a7e5-e16143d860d7` | Settings: API Keys - listar/gerenciar keys sem expor valores | medium | todo |
| `fd707712-1888-4d6c-936d-cd94060949ff` | Sincronizar dados do app Balance com Supabase | medium | todo |
| `5155e380-20fd-4616-85c2-1f7ad2f1a1fa` | Stack Padrão BPF Consult - Decisões Arquiteturais | medium | todo |
| `5b4f837e-d0fb-4871-b661-2593877cd658` | Tool node WorkDev no Agente Pessoal (backlog por voz) | medium | todo |
| `b48cfaa8-562d-446b-9b5c-d6b46a58d317` | UI não distingue agente inexistente de agente conectado | medium | todo |
| `269e68ef-dc42-421b-8ba9-dad48ca4dfdf` | Verificar se Agro CRM e NutriGestor CRM sao registros duplicados do mesmo sistema no WorkDev | medium | done |
| `c96d4c6f-ecba-4f27-959f-4dd4c8ff9aaa` | documento_versoes permite UPDATE/DELETE pelo dono | medium | todo |
| `8bbb39c2-adf9-447e-8260-51715597606e` | registrarAuditLog falha em silêncio | medium | todo |
| `0fcf2b61-51f5-4bdc-a3e4-06e510375200` | registro completo da migração e inventário de plataformas | medium | done |

## Low / Baixa

| id | título | prioridade | status |
|---|---|---|---|
| `c7f4c84a-bec0-4fd8-be06-fb8f3446673c` | Baixar binários dos buckets de storage do Lovable de todos os projetos migrados (acesso garantido até maio/2027) | low | todo |
| `4735ed32-4da5-46a7-aa9e-c6c45a316cd1` | Chore: remover nó de teste bbbbbbbb do banco e adicionar filtro anti-lixo | low | todo |
| `7cd35745-4a9d-481a-bd8e-7453a49b7696` | Colorir prompts dos terminais VPS1 e VPS2 | low | todo |
| `e4f37cf4-691c-492a-b010-8924262328e6` | Engineering Graph: cascade de exclusão Postgres → grafo | low | todo |
| `25832c97-e842-4448-8170-a950a9819b09` | Engineering: implementar abas Overview, Timeline, ADRs, RFCs e Decisions | low | done |
| `f2dc1858-8e14-4d2f-acea-3cded64178f4` | Logrotate para workdev-api-healthcheck.log | low | todo |
| `89632564-54ab-4e6e-80f2-1a92c5013b85` | Rotacionar credenciais antes de encerrar contas de origem (Lovable/Manus/Verdent) | low | todo |
| `374c327c-857b-4dba-878d-b1012da008c6` | Settings: implementar funcionalidade real ou remover cards não aplicáveis | low | todo |
| `46119309-be87-4f2e-8654-b7c51a6af673` | workdev-agents.service sem supervisão | low | todo |
