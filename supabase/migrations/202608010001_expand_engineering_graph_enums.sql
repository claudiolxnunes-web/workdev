-- Engineering Graph Fase 3: expande os enums usados pelo contrato da aplicação.
-- ADD VALUE IF NOT EXISTS torna a migration segura para reaplicação.
--
-- Rollback não é automático porque PostgreSQL não suporta DROP VALUE de enum.
-- Antes de reconstruir os enums legados, remova/migre todas as linhas que usem
-- estes valores e faça backup de graph_nodes e graph_edges.

alter type public.node_type add value if not exists 'Decision';
alter type public.node_type add value if not exists 'Plan';
alter type public.node_type add value if not exists 'AgentRun';
alter type public.node_type add value if not exists 'AgentEvent';

alter type public.relationship_type add value if not exists 'HAS_DECISION';
alter type public.relationship_type add value if not exists 'BELONGS_TO';
alter type public.relationship_type add value if not exists 'DEPENDS_ON';
alter type public.relationship_type add value if not exists 'RELEASED_IN';
alter type public.relationship_type add value if not exists 'RELATES_TO';
alter type public.relationship_type add value if not exists 'BLOCKS';
alter type public.relationship_type add value if not exists 'CAUSED_BY';
alter type public.relationship_type add value if not exists 'HAS_PLAN';
alter type public.relationship_type add value if not exists 'HAS_RUN';
alter type public.relationship_type add value if not exists 'HAS_EVENT';
