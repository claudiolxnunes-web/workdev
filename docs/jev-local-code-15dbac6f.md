# JEV no local-code — decisão do Cláudio e revisão

Execução: `15dbac6f-aa2c-43ee-9380-fe46817d2f93`.
Task: `201334b9-bb28-4563-871a-06c20945f7b2`.

## Decisão do responsável

Cláudio decidiu encerrar a task com revisão pelo próprio executor Codex devido
às dificuldades de revisão independente: o Gemini estava sem crédito.
Autorizou explicitamente registrar essa decisão, encerrar a task, commitar,
fazer push e deploy. Não houve aprovação independente nem veredito do Gemini.
Esta decisão não altera as regras de revisão ou de conclusão do aplicativo.

## Implementação e autorrevisão

Removida somente a exclusão de `local-code` na condição de supervisão adaptativa
em `apps/api/app/services/handoff.py`. Preservados o feature flag, a exigência
de Session, a classificação determinística, o fallback conservador, o bloqueio
de egresso restricted e a separação executor/revisor.

Codex não encontrou bloqueadores na mudança. Nove novos cenários cobrem a
inclusão de local-code e a continuidade de codex, desativação do recurso,
recusa restricted antes da criação do cliente OpenRouter, auditoria e vínculo
do evento à AgentRun, falha/timeout, separação de papéis e piso critical.

Validação executada com venv, DSN fictício e sem carregar o env de produção:

```text
python -m pytest apps/api/tests/test_adaptive_supervision.py apps/api/tests/test_adaptive_ai.py apps/api/tests/test_handoff.py apps/api/tests/test_handoff_review.py apps/api/tests/test_local_code_build.py -q --tb=short -p no:cacheprovider
108 passed, 3 subtests passed
```

Os testes usam Session/commits reais em SQLite, classificação e guarda de
egresso reais; transporte do provider e despacho local são simulados.
Não houve chamada real ao OpenRouter nem teste no PostgreSQL de produção.
Projetos internos com local-code passam a assumir a latência/custo do JEV,
limitados pelas guardas existentes. Falha mantém fallback conservador.

As alterações preexistentes de terminal, interface e config foram preservadas
e não integram esta entrega. Autorização de publicação não significa deploy
realizado: conclusão na API, push e deploy precisam de confirmação operacional.
