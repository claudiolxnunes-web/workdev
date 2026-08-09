# ADR 0004 — Totais incorretos no Agro RC por limite de leitura do PostgREST

- **Data:** 2026-08-09
- **Status:** aceita (correção paliativa aplicada; solução definitiva pendente)
- **Contexto de sistema:** Agro RC CRM (`/opt/agro-rc`, Supabase `ilvfwbtfjtnihtsuuzcb`)

## Sintoma

Após importar 1.750 vendas, o dashboard exibia faturamento de ~R$ 140 mil em
vez dos ~R$ 690 mil reais. O mesmo comportamento já havia ocorrido antes e foi
interpretado como "a importação só vai até 1.000 linhas".

## Diagnóstico

**A importação nunca foi o problema.** `VendasImport.tsx` está corretamente
implementado: leitura paginada via `fetchAllPaged` (páginas de 1.000, teto de
500 mil) e escrita em lotes de 500 num laço sobre o total, sem limite superior.

A causa é o **`max-rows` do PostgREST**, configurado em **1.000** por padrão no
Supabase. Qualquer `SELECT` sem paginação retorna no máximo 1.000 linhas,
silenciosamente. As telas que somam no cliente estavam, portanto, totalizando
apenas as primeiras mil vendas.

Tentativas anteriores de corrigir no lugar errado permaneciam no código:
`Metas.tsx` usa `.limit(5000)` e `PlanejamentoGerencial.tsx` usa `.limit(20000)`
— ambos ignorados, porque `max-rows` prevalece sobre o `limit` da requisição.

**Arquivos que leem `vendas` sem paginação alguma (6):**
`pages/crm/Campo.tsx`, `pages/crm/Metas.tsx`, `pages/crm/Ranking.tsx`,
`pages/crm/PlanejamentoGerencial.tsx`, `components/crm/HistoricoClienteDialog.tsx`,
`components/crm/HistoricoProdutosDialog.tsx`.

Com paginação parcial (1 ocorrência de `range`/`fetchAllPaged`):
`MeusClientesPicker.tsx`, `gerencial/ClientesInativosCard.tsx`,
`gerencial/Top20Recuperar.tsx`. Corretos: `crmService.ts` (7) e
`VendasImport.tsx` (5).

`Campo.tsx` filtra por `user_id` e mês, então dificilmente atingia o teto;
`Ranking.tsx` filtra por `mes_ano`.

## Decisão e correção aplicada

Elevado o `max-rows` de 1.000 para 50.000. O painel do Supabase não expõe mais
essa configuração no caminho anterior (`/settings/api`), então foi aplicada via
SQL Editor:

```sql
alter role authenticator set pgrst.db_max_rows = '50000';
notify pgrst, 'reload config';
```

Verificação:

```sql
select unnest(rolconfig) from pg_roles where rolname = 'authenticator';
-- pgrst.db_max_rows=50000
```

Totais conferidos como corretos após recarregar a aplicação. Nenhuma alteração
de código, nenhum rebuild.

**A mudança é global ao projeto:** vale para todas as tabelas. Consultas sem
filtro passam a poder trazer até 50 mil linhas ao cliente.

## Limitações conhecidas desta correção

É paliativo, não solução. Dois tetos permanecem:

1. **50 mil linhas.** Ultrapassado o volume, o sintoma retorna idêntico —
   silencioso, sem erro, com totais subdimensionados.
2. **`statement_timeout = 8s`** (também em `rolconfig`). As seis telas que
   carregam a tabela inteira para somar no navegador tendem a estourar o tempo
   antes mesmo de atingir o limite de linhas, na casa das dezenas de milhares de
   registros.

## Solução definitiva pendente

Agregar no banco em vez de no cliente: funções RPC em Postgres retornando o
total já somado (`select sum(faturamento_realizado) ... where organizacao_id = ...`),
consumidas via `supabase.rpc()`. Uma requisição, um número, tempo de resposta em
milissegundos independentemente do volume, imune tanto ao `max-rows` quanto ao
`statement_timeout`.

Prioridade: média. O paliativo sustenta a operação atual (1.750 vendas) com
folga; revisar antes de a base passar de ~20 mil registros.

Ao implementar, remover os `.limit(5000)` e `.limit(20000)` residuais, que hoje
apenas mascaram a intenção real do código.

## Nota

O padrão se repete: um limite de infraestrutura silencioso produziu números
errados que pareciam bug de aplicação, e as tentativas anteriores de correção
foram todas no frontend. Antes de ajustar código que calcula totais, verificar
os limites da camada de dados.
