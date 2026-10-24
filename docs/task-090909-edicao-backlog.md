# Task 09.09.09 — edição de tasks existentes

Task: `fd5df885-e9f2-4088-a799-d076c65a4743`.
Plano oficial aprovado v1: `56aa9daa-2806-4e7f-986c-a5144bd73519`.
Execução: `40e80cae-e85e-408f-b430-79eb153c27ea`.
Branch: `task/fd5df885-edit-tasks`, criada da base local `53d0880`.

## Discovery — classificação D

O backend já oferece `PATCH /api/backlog/{item_id}` em
`apps/api/app/routers/backlog.py`. Busca a linha por UUID, aplica somente campos
presentes em `BacklogUpdate`, atualiza `updated_at` e faz commit na mesma linha.
Não recria a task. Mantém a restrição existente: concluir com subtasks pendentes
retorna HTTP 400 com `detail.code`, `detail.message` e `detail.details`.
UUID inválido/body inválido retornam 422; UUID inexistente retorna 404.

O schema `BacklogUpdate` e o model `BacklogItem` confirmam `title`, `description`,
`priority` e `status`. Não há coluna própria para contexto/escopo; o formulário
de criação já usa `description` para esse conteúdo. Nenhuma migration necessária.
Sprint, tipo, projeto, responsável e data de criação ficam fora da edição.

A causa raiz está no frontend: `backlog.service.ts` não tinha operação de edição,
e `TaskDetail.tsx`, compartilhado pelo backlog global e pelo backlog do projeto,
só oferecia planejamento, subtasks e avanço de status. Nem exibia a descrição.
O teste de regressão `BacklogEditing.test.tsx` foi executado antes da correção:
os quatro cenários iniciais falharam por ausência do botão **Editar task**.

O teste HTTP com persistência confirmou o endpoint existente funcionando antes
de qualquer alteração em backend de produção. Somente código frontend e testes
foram alterados: a Fase 1 foi pulada conforme a classificação D.

## Implementação

- Edição dentro do modal de detalhes existente, com título, descrição/contexto/
  escopo, prioridade e status. O formulário de criação permanece intacto.
- PATCH envia apenas campos alterados, sem reenviar status quando só texto mudou.
  Limpar descrição envia string vazia; título em branco é rejeitado no formulário.
- Resposta persistida substitui o item pelo mesmo ID no modal e no backlog.
  Ao mudar status, a coluna correspondente é selecionada também no mobile.
- Durante o envio, edição e outras mutações no modal ficam desabilitadas.
  Erro mantém o rascunho; cancelar descarta a edição local.
- Mensagens de erro suportam `detail` textual, `detail.message`, validação 422
  em lista e fallback com código HTTP para resposta não JSON.

## Evidências e limites

- HTTP via FastAPI TestClient e SQLite temporário com FKs: 16 testes passaram
  em `test_backlog_edit.py` e `test_backlog_ai_hub_flow.py`.
- O teste de edição compara os registros completos de subtasks, planos, runs,
  eventos, chats e mensagens antes/depois; confirma ID, `created_at` e campos
  fora do escopo intactos. GET em outra requisição confirma o commit.
- SQLite usa adaptação de defaults JSONB/UUID e relógio SQL do PostgreSQL na
  fixture. Isso não constitui validação de triggers ou constraints da produção.
  Nenhuma task de produção foi modificada para teste.
- UI testada com React Testing Library, páginas e serviço reais, HTTP simulado:
  editar, salvar, fechar/reabrir, limpar descrição, título em branco, erro e cancelamento.
  Não foi realizado teste em navegador contra produção.
- Suíte frontend final: 121 testes passaram em 17 arquivos.
- `pnpm run build`: passou; bundle `index-*.js` com zero ocorrências de
  `localhost:8000`. Lint de todos os arquivos frontend alterados: passou.
- `pnpm run lint`: falhou com três erros `react-hooks/set-state-in-effect` em
  `DatabaseTab.tsx:43`, `MonitoringTab.tsx:40` e `RepositoryTab.tsx:51`.
  `git diff --exit-code HEAD -- <esses arquivos>` retornou zero: são arquivos
  idênticos à base. Não foram alterados por estarem fora do escopo.
- Suíte completa backend: 1114 testes passaram, 24 skipped, 26 subtests
  passaram, 39 warnings; código de saída zero. Executada com
  `DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/fake`,
  `WORKDEV_API_ENV_FILE=/dev/null`, `PYTHONDONTWRITEBYTECODE=1` e
  `venv/bin/python -m pytest tests/ -q -p no:cacheprovider --tb=short`.
  TestClient travou na primeira tentativa dentro do sandbox; a execução fora
  do sandbox passou. A tentativa anterior foi interrompida (saída 130).

O critério de lint global verde permanece pendente pelos erros preexistentes.
Entrega para revisão não equivale a aprovação. Sem migration, merge, push ou deploy.
