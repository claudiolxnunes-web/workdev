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

## Revisão independente retroativa (2026-09-26)

Revisão feita por agente diferente do Codex (que escreveu a mudança), conforme
exigido na descrição original da task ("revisão por agente diferente").

Diff revisado: commit `52b24ea` — uma única linha em `handoff.py` (remove a
exclusão `agent != 'local-code'`), mais 9 cenários de teste novos em
`test_adaptive_supervision.py` cobrindo local-code habilitado/desabilitado,
falha/timeout/restricted, separação executor/revisor e piso critical.

Achados: nenhum bloqueador. Todas as guardas preexistentes (feature flag,
Session, classificação determinística, fallback conservador, bloqueio de
egresso restricted, separação executor/revisor) permanecem intactas.

Validação adicional feita nesta sessão, que não existia na entrega original:
- Confirmadas 3 chamadas reais ao Jev em produção (routing.jev_decision, com
  custo/tokens reais), incluindo o próprio caminho local-code.
- Corrigido o bug real que mascarava essas chamadas: threshold de confiança
  único (0.75) fazia toda decisão cair no fallback conservador. Agora dois
  thresholds separados (0.35 roteamento / 0.75 aprovação humana).
- Suíte completa (1349 testes) validada como usuário `workdev` (mesmo usuário
  do gate de deploy), não como root.

Task `201334b9` e as 2 subtasks associadas marcadas como `done` via API.
Nenhuma mudança de código adicional foi necessária — a implementação de
`52b24ea` está correta e agora está com a validação real que faltava.
