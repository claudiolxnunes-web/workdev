# Engineering Graph Fase 3 — validação de 05/08/2026

## Bloqueador identificado

O sync automático estava configurado e recebia eventos, mas falhava com HTTP 409:
`graph_nodes.project_id` referencia `projects.id` no Supabase e os projetos ainda
não cadastrados eram rejeitados pela foreign key. Os seis projetos previstos para
esta fase já estão cadastrados no destino e possuem nós; eventos de projetos fora
desse conjunto continuam sendo recusados até o cadastro explícito.

## Validações do grafo

- Criação temporária de uma task via `POST /api/backlog`: nó `Task` apareceu
  automaticamente no Supabase; task, aresta e nó temporários foram removidos.
- Enums confirmados pelo OpenAPI do PostgREST:
  - `node_type`: inclui `Decision`, `Plan`, `AgentRun` e `AgentEvent`.
  - `relationship_type`: inclui `HAS_DECISION`, `HAS_PLAN`, `HAS_RUN`,
    `HAS_EVENT`, `BELONGS_TO`, `DEPENDS_ON`, `RELEASED_IN`, `RELATES_TO`,
    `BLOCKS` e `CAUSED_BY`.
- Nós por projeto após backfill:
  - WorkDev Core: 792
  - Agente Pessoal: 1
  - OpenClaw: 1
  - Feed_BPF: 3
  - NutriControle: 2
  - NutriGestor CRM: 25
- Cinco nós seed com prefixo `bbbbbbbb-0001-0001-0001-` e suas cinco arestas
  foram removidos. A consulta posterior pelo prefixo retornou vazia.
- O frontend agora filtra esse padrão seed e não usa UUID como label fallback.

## Settings e Knowledge

- Os quatro cards atuais de Settings possuem função real (sistema/migrations,
  providers, backfill do grafo e preferências); nenhum foi removido.
- `GET /api/settings/keys` retorna somente `provider`, `label` e `configured`.
- `POST /api/knowledge` permanece protegido pelo middleware global da API e
  agora agenda a criação automática do nó/relação no Engineering Graph.

## Domínios

- `workdev.bpfconsult.com.br` resolve para `2.25.199.80`; HTTPS válido com
  certificado Let's Encrypt até 11/10/2026.
- `feedoptimize.app` ainda resolve para `192.64.119.137` e CNAME
  `parkingpage.namecheap.com`, não para Netlify. A correção depende de acesso ao
  DNS da Namecheap e deve ser validada novamente após a propagação.

## Decisão de custo — ngrep

O projeto `ngrepqqlvglzqnoswfug` está cadastrado no WorkDev como `Suspended` e o
token disponível não tem acesso válido ao projeto. Decisão: mantê-lo suspenso e
fora da organização Pro até existir necessidade operacional. Em uma organização
Pro, cada projeto Micro adicional custa aproximadamente US$ 10/mês; os US$ 10 de
crédito mensal cobrem somente um projeto. Referência:
https://supabase.com/docs/guides/platform/manage-your-usage/compute

## Backlog duplicado

Foram encontrados três itens “Adicionar provider Ollama Cloud ao AI Hub”. Foi
mantido o item concluído com seu plano aprovado v2. Dois itens `todo` e um plano
aprovado redundante, sem AgentRun associado, foram removidos.
