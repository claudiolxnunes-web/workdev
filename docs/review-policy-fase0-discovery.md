# Fluxo de revisão em 8 fases — Fase 0: discovery (read-only)

Data: 2026-09-14. Base: branch `task/e45f5f46-review-policy`. Documento
produzido sem alterar código. (Reescrita após wipe externo do working tree;
conteúdo equivalente à versão inspecionada antes.)

## 1. Estados e transições de AgentRun

- `apps/api/app/models/handoff.py`
- `AgentRun` — status ∈ queued/running/blocked/review/completed/failed/cancelled;
  `reviewer_agent` (designado no PLAN), `review_attempts`, `model`,
  `complexity`, `complexity_score`, `routing_mode`.
- `AgentRunReview` — histórico cumulativo (attempt UNIQUE por run); payload com
  feedback_category/confidence/reason e training_candidate.
- `AgentRunEvent` — eventos `build.*`/`review.*`/`workspace.*` com payload.
- `apps/api/app/services/handoff.py`
- `RUN_TRANSITIONS` (linhas 66–74): `running → review`; só `review → completed`;
  rejeição devolve a `running`.
- `update_run(db, run, data)` — valida transição; em review/completed exige gate
  via `validate_run_for_status_change`.
- `record_review(db, run, reviewer, verdict, feedback)` — revisor ≠ executor,
  revisor designado; approved exige gate; rejected exige feedback;
  classifica via `services/feedback_classifier.classify_review_feedback`.

## 2. Gates objetivos

- `apps/api/app/services/test_gate.py`: `execute_gate` (pytest obrigatório;
  vitest/lint/build), `persist_gate_evidence` → `build.tests_passed/failed`,
  `get_gate_evidence_for_run` (valida run_id/backlog_id/git_commit_sha),
  `validate_run_for_status_change`. Gate é chamado no PATCH de runs e no fluxo
  headless (build_executor). GatePaths com raiz fixa `/opt/workdev`.

## 3. Roteamento atual do revisor

- `reviewer_agent` designado no PLAN; troca auditada por `swap_run_reviewer`.
- Sem roteamento por risco: qualquer run exige revisor LLM, mesmo mudança
  trivial.
- `GET /handoffs/runs/{id}/context` remonta contexto inteiro para o revisor —
  origem da duplicação de custo.
- Veredito somente via CLI `workdev_agent.py verdict` → `POST /runs/{id}/reviews`.

## 4. Permissões OS e guardrails existentes

- `deploy.sh`/`workdev-deployctl` recusam EUID ≠ 0.
- API/testes rodam como `workdev`; nada detecta artefatos root-owned em
  `apps/web/dist` (incidente recorrente, ver CLAUDE.md). Sem guardrail.

## 5. Métricas existentes

- Custos de IA em migrations `e4a19c7d3b21_ai_cost_safety`; nenhuma métrica por
  ciclo de revisão (tokens/duração/modelo/risco).

## 6. Diff/worktree dos gates

- `services/build_worktree.py` — worktree isolado + GatePaths; gates podem
  operar na raiz fixa.

## Lacunas confirmadas

1. Sem classificação objetiva de risco (risk/sensitive scope).
2. Gates não precedem decisão de revisão com justificativa persistida.
3. Contexto do revisor é sempre completo (endpoint `context`).
4. Sem métricas/auditoria do ciclo de revisão.
5. Sem guardrail de identidade OS (root) nem detecção de artefatos root-owned.
