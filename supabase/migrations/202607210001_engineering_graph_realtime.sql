-- Engineering Graph: modelo idempotente, índices, RLS de leitura e Realtime.
-- Escritas são feitas somente pelo backend com SUPABASE_SECRET_KEY.

create extension if not exists pgcrypto;

create table if not exists public.graph_nodes (
  id uuid primary key default gen_random_uuid(),
  type text not null,
  entity_id text not null,
  project_id uuid not null,
  created_at timestamptz not null default now()
);

create table if not exists public.graph_edges (
  id uuid primary key default gen_random_uuid(),
  source_node uuid not null references public.graph_nodes(id) on delete cascade,
  target_node uuid not null references public.graph_nodes(id) on delete cascade,
  relationship text not null,
  created_at timestamptz not null default now()
);

alter table public.graph_nodes
  alter column entity_id type text using entity_id::text;

create index if not exists graph_nodes_project_idx
  on public.graph_nodes(project_id);
create index if not exists graph_nodes_entity_idx
  on public.graph_nodes(project_id, entity_id, type);
create index if not exists graph_edges_source_idx
  on public.graph_edges(source_node);
create index if not exists graph_edges_target_idx
  on public.graph_edges(target_node);

alter table public.graph_nodes enable row level security;
alter table public.graph_edges enable row level security;

grant select on public.graph_nodes to anon, authenticated;
grant select on public.graph_edges to anon, authenticated;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'graph_nodes'
      and policyname = 'Engineering graph nodes are readable'
  ) then
    create policy "Engineering graph nodes are readable"
      on public.graph_nodes for select to anon, authenticated using (true);
  end if;
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'graph_edges'
      and policyname = 'Engineering graph edges are readable'
  ) then
    create policy "Engineering graph edges are readable"
      on public.graph_edges for select to anon, authenticated using (true);
  end if;
end $$;

alter table public.graph_nodes replica identity full;
alter table public.graph_edges replica identity full;

do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'graph_nodes'
  ) then
    alter publication supabase_realtime add table public.graph_nodes;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'graph_edges'
  ) then
    alter publication supabase_realtime add table public.graph_edges;
  end if;
end $$;
