---
name: feedops
description: Contrato de engenharia do FeedOps — SaaS de gestão de produção para fábricas de ração da BPF Consult. Use SEMPRE que a tarefa envolver o FeedOps de qualquer forma: criar tabela, escrever migração, definir RLS, criar edge function, montar tela, calcular KPI, revisar código ou planejar etapa. Vale também quando o pedido citar apenas o domínio (ordem de produção, parada, OEE, ton/h, kWh/ton, PDCA, não conformidade, custo por tonelada) sem nomear o FeedOps. Nenhum código do FeedOps deve ser escrito sem ler esta skill primeiro — ela define schema, convenções e proibições que não podem ser renegociadas por tarefa.
---

# FeedOps — Contrato de Engenharia

FeedOps é o SaaS de gestão de produção e melhoria contínua para fábricas de ração da BPF Consult.

Esta skill é **contrato, não sugestão**. O schema, as convenções de RLS e as proibições abaixo foram fixados uma vez para que múltiplos agentes trabalhando no mesmo repositório produzam código consistente. Se uma tarefa parecer exigir violar algo aqui, **pare e reporte ao Cláudio** em vez de decidir sozinho — divergência silenciosa entre agentes é o principal risco do projeto.

## Contexto obrigatório antes de qualquer coisa

- **Stack:** TanStack Start + Nitro (alvo Node), React, TanStack Query, Supabase (Postgres + Auth + Storage) em conta própria da BPF Consult.
- **Deploy:** VPS1, systemd + Traefik (file provider), mesmo padrão do AgroGestão.
- **Repositório:** monorepo próprio, GitHub desde o commit inicial.
- **Ambiente do operador:** o Cláudio trabalha majoritariamente por Termux/SSH no celular. Isso muda como você entrega instruções (ver "Operação em mobile").

---

## 1. Proibições absolutas

Cada item abaixo veio de um incidente real. Não são preferências.

| Proibido | Por quê |
|---|---|
| Qualquer import `npm:@lovable.dev/*`, variável `LOVABLE_*`, endpoint `*.lovable.dev` | O gateway Lovable proxiava IA, e-mail **e pagamento**. Migrar depois custa semanas (ADR 0003). |
| Habilitar Lovable Cloud ou qualquer backend gerenciado por terceiro | O banco de produção precisa estar em conta controlada pela BPF Consult. |
| Preset Cloudflare Workers, KV, bindings, Deno-only APIs | O AgroGestão exigiu conversão completa para Node depois. Alvo é Node/Nitro desde o início. |
| Função de login rápido, bypass de auth, seed de usuário admin com senha fixa | `devQuickLogin` foi encontrado em produção. Nunca crie atalho de autenticação, nem "só para dev". |
| Papel de usuário em `profiles` ou em coluna do usuário | Papel vive em `user_roles` + função `has_role`. Papel no perfil é escalonamento de privilégio por UPDATE. |
| `service_role` em qualquer variável `VITE_*` ou em qualquer código do cliente | Incidente já ocorrido, exigiu rotação de chave. Ver seção 6. |
| Escrever token, chave ou senha em resposta, log, commit ou arquivo de documentação | Inclui parciais. Se precisar referenciar, use o nome da variável. |
| `supabase.from(...)` fora da camada de acesso | Ver seção 4. |
| Chave de IA ou de pagamento no frontend | Sempre via função no servidor, chave em secret do Supabase. |

**Verificação semanal e antes de todo deploy:**

```bash
grep -riE "lovable|LOVABLE_|quickLogin|devLogin|service_role" src/ app/ supabase/ || echo "OK"
```

---

## 2. Schema — nomes congelados

Convenções: tabelas em `snake_case` plural, PK `id uuid default gen_random_uuid()`, timestamps `created_at`/`updated_at timestamptz default now()`, FK no singular com sufixo `_id`, dinheiro em `numeric(14,4)`, massa em kg (`numeric(14,3)`), energia em kWh.

**Nunca use `integer` como PK ou FK.** O bug do `email_send_state` (`id integer` num schema UUID) bloqueou todas as escritas silenciosamente.

### Organização e acesso
- `organizations` — cliente do SaaS
- `factories` — `organization_id`, nome, cidade/UF
- `production_lines` — `factory_id`, tipo (`fareladora`, `peletizadora`, `extrusora`)
- `profiles` — 1:1 com `auth.users`, sem papel
- `user_roles` — `user_id`, `organization_id`, `factory_id` (nullable = todas), `role` enum (`admin`, `gestor`, `operador`)

### Cadastros
- `products` — produto/ração acabada, `organization_id`
- `product_formulas` — `product_id`, `version int`, `valid_from`, `valid_to`, `is_active`. **Fórmula é versionada**: o custo de um lote depende da versão vigente na data.
- `formula_items` — `product_formula_id`, `material_id`, `inclusion_pct`
- `line_capacities` — `production_line_id`, `product_id`, `nominal_tph numeric`. **Sem isto o OEE é ficção** (ver seção 3).
- `materials` — matéria-prima e insumos
- `suppliers`, `employees`, `cost_centers`

### Produção
- `production_orders` — `factory_id`, `production_line_id`, `product_id`, `product_formula_id`, `batch_code`, `planned_qty_kg`, `produced_qty_kg`, `started_at`, `finished_at`, `status`
- `downtime_events` — `production_order_id`, `reason_id`, `started_at`, `ended_at`, `is_planned boolean not null`. **Parada programada (troca de fórmula, higienização, flushing de medicado) nunca entra no cálculo de disponibilidade não programada.**
- `downtime_reasons` — catálogo por organização, com categoria (6M)
- `consumption_records` — `production_order_id`, `material_batch_id`, `qty_kg`, `unit_cost`
- `energy_records` — `production_order_id`, `equipment` (`moinho`, `peletizadora`, `misturador`, `geral`), `kwh`. Separado por equipamento: é onde está o custo.
- `material_batches` — lote de matéria-prima, `material_id`, `supplier_id`, `received_at`, `qty_kg`, `unit_cost`
- `stock_movements` — entrada/saída/ajuste, custo médio ponderado. Sem esta tabela o custo por tonelada é estimativa.
- `quality_records` — `production_order_id`, finos %, PDI/durabilidade, retrabalho kg

### Indicadores
- `kpi_targets` — `factory_id`, `kpi_code`, `target`, `warning_threshold`
- `kpi_daily_facts` — **tabela-fato agregada** por `factory_id × production_line_id × product_id × date`. Ver seção 5.

### Melhoria contínua
- `pdca_cycles` — vinculável a `kpi_code`, `production_order_id` ou `nonconformity_id`
- `ishikawa_causes` — `pdca_cycle_id`, categoria 6M, causa
- `action_items` — 5W2H: `what`, `why`, `where`, `who`, `when`, `how`, `how_much`, `status`, `effectiveness_verified_at`
- `five_whys` — `pdca_cycle_id`, ordem, pergunta, resposta

### Projetos
- `projects`, `tasks` (kanban `status` + `start_date`/`due_date` para o Gantt)

### Financeiro
- `finance_entries` — `cost_center_id`, `production_order_id` (nullable), tipo, valor, data
- `cost_allocations` — regra de rateio (energia por hora de linha, MO por hora, overhead por tonelada). **Defina a regra antes de codar a tela.**

### BPF / Diagnóstico
- `bpf_checklists`, `bpf_checklist_items`, `nonconformities` — `classification`, `due_date`, `pdca_cycle_id` (FK, não importação por CSV)

> **Integração com o Feed_BPF é por FK ou API interna, nunca por planilha.** CSV entre dois sistemas do mesmo dono é dívida técnica, não integração. Importação de CSV existe apenas para dados de **cliente externo**.

---

## 3. Regras de cálculo de KPI

Fábrica de ração é processo de batelada, não manufatura discreta. Aplicar OEE de linha de montagem gera número errado e destrói a confiança do cliente.

- **ton/h efetiva** = `produced_qty_kg / 1000 / horas_operando` (exclui paradas). Indicador principal.
- **Rendimento** = `produced_qty_kg / planned_qty_kg`
- **Disponibilidade** = `tempo_operando / (tempo_disponível − paradas_programadas)`
- **Desempenho** = `ton/h efetiva / nominal_tph` da combinação **produto × linha** (`line_capacities`). Se não houver capacidade nominal cadastrada, **retorne NULL, não 100%**.
- **Qualidade** = `(produzido − retrabalho − refugo) / produzido`, de `quality_records`. Se não houver registro, **NULL**.
- **OEE** = produto dos três. **Se qualquer fator for NULL, OEE é NULL.** Nunca preencha fator ausente com 1.0 — isso produz OEE inflado e indefensável em auditoria.
- **kWh/ton** por equipamento e total
- **Custo/ton** = (MP a custo médio + energia + MO rateada + overhead) / toneladas
- **Variação padrão × real** = custo da fórmula vigente × produzido, comparado ao consumo real. Com preço de MP oscilando, isto vale mais que margem bruta.

Semáforo: dentro / atenção / fora, contra `kpi_targets`. KPI sem meta cadastrada aparece neutro, não verde.

---

## 4. Padrões de código

### Camada de acesso única

Todo acesso a dados passa por `src/lib/api/` (uma função por caso de uso) ou por server function do TanStack Start. **Nenhum componente chama `supabase.from()` diretamente.** Motivo: se o backend mudar, é um diretório; não são 40 componentes.

```ts
// src/lib/api/production-orders.ts
export async function listProductionOrders(factoryId: string, range: DateRange) { ... }
```

Componentes consomem via TanStack Query com chaves padronizadas: `['production-orders', factoryId, range]`.

### Migrações

Toda migração inclui, no mesmo arquivo, nesta ordem: DDL → RLS enable → policies → **grants explícitos** → índices. Grants em migração separada são esquecidos.

```sql
alter table public.production_orders enable row level security;

grant select, insert, update, delete on public.production_orders to authenticated;
grant usage on schema public to authenticated;
```

### RLS — isolamento em dois níveis

Isolar por **organização e por fábrica**. Operador de uma planta não deve ver outra.

`has_role` e o helper de organização são `SECURITY DEFINER` para evitar recursão infinita quando a policy de `user_roles` precisa consultar `user_roles`:

```sql
create or replace function public.has_role(_role app_role, _factory_id uuid default null)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.user_roles ur
    where ur.user_id = auth.uid()
      and ur.role = _role
      and (_factory_id is null or ur.factory_id is null or ur.factory_id = _factory_id)
  );
$$;
```

Toda tabela de dado operacional carrega `factory_id` (mesmo que derivável por join) para que a policy seja um teste direto, sem join — join em policy é o que estoura o `statement_timeout`.

### Auditoria

`audit_log` com trigger em `production_orders`, `downtime_events`, `consumption_records`, `nonconformities`, `action_items`. Sem trilha, o KPI não se sustenta numa auditoria MAPA nem numa discussão com o cliente.

---

## 5. Limites de infraestrutura já conhecidos

- **PostgREST `statement_timeout = 8s`** no ambiente da BPF. View de KPI calculada em tempo real sobre histórico vai estourar. Por isso `kpi_daily_facts`: agregação por dia × linha × produto, atualizada por trigger na conclusão da ordem ou por cron noturno. Telas leem a fato, nunca a base bruta.
- **`max-rows`**: confirmar o teto do projeto antes de qualquer tela de listagem. Subnotificação silenciosa de dashboard já ocorreu.
- **Free tier auto-pause**: incluir o projeto FeedOps no `/opt/scripts/heartbeat-supabase.sh` (tabela `heartbeat`, RLS select anon).
- **Backup**: incluir no `/opt/scripts/supabase_backup.sh` antes do primeiro dado de cliente real.

---

## 6. Checagem de segurança antes de cada deploy

1. Decodificar o JWT de `VITE_SUPABASE_ANON_KEY` e confirmar `"role": "anon"`:
   ```bash
   echo "$VITE_SUPABASE_ANON_KEY" | cut -d. -f2 | base64 -d 2>/dev/null | grep -o '"role":"[^"]*"'
   ```
   Se aparecer `service_role`, **pare tudo e rotacione a chave**. Precedente existe.
2. `.env` sem linhas duplicadas — só a última vale, e isso já mascarou variável errada:
   ```bash
   grep -oE '^[A-Z_]+=' .env | sort | uniq -d
   ```
3. Nenhum secret em `VITE_*`. Regra: `VITE_` é público por definição.
4. Rodar o grep da seção 1.

---

## 7. Protocolo de trabalho com agentes

O histórico deste ambiente inclui agentes relatando sucesso em arquivos que não criaram, repositórios inventados e configurações falsamente confirmadas. Portanto:

**Nunca reporte conclusão sem prova executável.** Cada entrega termina com o comando e a saída real:

- Migração → `psql ... -c "\d+ tabela"` mostrando colunas e policies
- Endpoint → `curl` com status e corpo
- Build → `npm run build` completo, sem erro
- RLS → consulta com JWT de outra organização retornando vazio

Se não conseguiu executar a verificação, diga que **não verificou**. Relatório otimista custa mais caro que atraso.

**Tamanho da fatia:** uma tabela + policies + camada de acesso + tela. Se não cabe numa verificação de poucos minutos no terminal, é grande demais — quebre.

**Fundação por um agente só:** o passo 1 (schema base, auth, RLS, `has_role`) é feito de uma vez, por um único agente. Fundação repartida entre agentes é onde a inconsistência custa mais para desfazer.

---

## 8. Ordem de execução

1. Schema base + auth + RLS + `has_role` (agente único, fatia grande)
2. Cadastros: produtos, fórmulas versionadas, insumos, linhas, **`line_capacities`**
3. Apontamento de produção mobile-first + paradas com `is_planned`
4. Estoque, lotes de MP, rastreabilidade lote-a-lote
5. `kpi_daily_facts` + painel de indicadores + metas
6. Custo por tonelada e variação padrão × real
7. Melhoria contínua (PDCA, Ishikawa, 5W2H, 5 Porquês)
8. Projetos/Kanban, diagnóstico BPF, landing

Itens 7 e 8 vêm por último de propósito: módulo de melhoria contínua sem dado confiável vira formulário vazio.

**Risco de adoção nº 1:** operador de fábrica não preenche formulário web. A tela de apontamento (passo 3) precisa ser PWA, offline-first, tablet/celular, três toques para registrar produção ou parada. Se depender de digitação cuidadosa, o painel enche de lixo em três semanas e o cliente cancela. Trate isso como requisito, não como polimento.

---

## 9. Operação em mobile (Termux)

O Cláudio executa muita coisa por SSH no celular. Ao entregar comandos:

- **Nunca heredoc** — corrompe silenciosamente no Termux. Use `echo >>` sequencial.
- **Credenciais em `nano`**, nunca colagem multilinha — é a causa raiz de `.env` corrompido.
- **`sed` para edição de código**, um comando por vez.
- Comandos longos: quebre em passos numerados, cada um verificável isoladamente.

---

## 10. Serviços externos

- **E-mail:** Resend, reaproveitando `_shared/resend.ts` do Feed_BPF. Nada de outro provedor.
- **IA:** chave direta do provedor (Gemini ou OpenRouter) em secret do Supabase, chamada por edge function própria. Streaming SSE segue o padrão já validado no portal Feed_BPF.
- **Pagamento:** Stripe direto, chave restrita, webhook em função própria. Nunca por intermediário.
- **PAT do Supabase:** um PAT só enxerga projetos da conta que o gerou. `403` em `functions deploy` com token válido = conta errada, não permissão errada.
