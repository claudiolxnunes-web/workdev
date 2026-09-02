# Resgate manual antes da Frota — 2026-09-02

Base: `991976cb62657e16af5ce694770fcac961bb9f3c` (`develop`).

## Classificação

- **Resgatar em task própria — Dashboard Executivo/DORA:** as 15 mudanças staged
  em `apps/api`, `apps/web`, `scripts/deploy/pipeline.py` e
  `supabase/views/dora_metrics.sql`. Não pertencem à Frota e não foram levadas
  para `feat/agent-fleet-phase0`.
- **Resgatar em task própria — RAG por API:**
  `apps/api/tests/test_rag_adr_projection_contract.py`. Não pertence à Frota.
- **Lixo confirmado, mas preservado:** `.ingestor_task_23745328.py`, cópia de
  trabalho byte-idêntica a `/opt/rag-postgres/ingestor.py`; não há mudança a
  resgatar desse arquivo.
- **Resgatar como relatório:**
  `docs/relatorio-backlog-urgente-2026-09-02.md`.
- **Lixo confirmado, mas preservado:** `sudo`, arquivo vazio criado em
  2026-09-01 22:39 UTC. Pode ser removido após o resgate ser revisado.
- **Adicionar ao `.gitignore`:** `.workdev-recovery/`, depois que este snapshot
  for copiado para armazenamento persistente fora da árvore. Não foi ignorado
  agora para permanecer visível à revisão manual.

## Artefatos

- `tracked.patch`: diff binário completo de `HEAD`, incluindo staged e unstaged.
- `untracked.tar.gz`: os três arquivos untracked classificados acima.

Proibido limpar a árvore original até confirmar a restauração do patch e listar
o conteúdo do tarball.
