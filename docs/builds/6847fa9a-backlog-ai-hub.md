# Backlog → AI Hub

Execução: `6847fa9a-99fd-4ed0-b380-b611a89762ed`  
Task: `07571b21-9b8f-4410-bef0-b57739b1f050`  
Revisor independente: Gemini

## Contrato implementado

- O botão Enviar ao AI Hub consulta a elegibilidade no servidor: somente tasks abertas (`todo`, `doing`, `blocked`) sem plano draft, needs_revision ou approved.
- O POST revalida a elegibilidade e devolve 409 em conflito. Entradas repetidas antes da criação de plano reutilizam a sessão existente.
- Sessões novas e restauradas expõem `backlog_id`, preservando o campo legado `task_id` na entrada. O contexto de sistema permanece persistido no servidor.
- Conversas vinculadas não podem trocar de projeto. Os providers recebem o vínculo persistido; as tools de prévia/criação preenchem o task_id omitido e rejeitam outro task_id.
- O painel de planos filtra pelo backlog_id da conversa.
- Criação de plano e entrada pelo Backlog bloqueiam a mesma linha de Backlog com `FOR UPDATE`, serializando a verificação de duplicidade. Não há cache operacional novo nem migration adicional.
- Os serviços existentes de aprovação, fila e resultado de deploy preservam Plan → AgentRun → DeploymentOutcome. O gate prepare → approve → deploy não foi alterado.

## Decisão humana

ADR `21a47198-9eab-4f4c-b9d0-e798d6cd413f`, opção 1 aceita: aprovação e envio ao Build continuam ações separadas. Aprovar um plano não cria AgentRun. A fila é acionada somente após aprovação e envio explícito com executor/revisor selecionados. O adendo foi registrado na execução.

## Validação

`apps/api/tests/test_backlog_ai_hub_flow.py` verifica persistência do contexto, reutilização de sessão, bloqueio de duplicados nos três estados ativos, rejeição de task concluída, vínculo das tools, contexto enviado aos dois caminhos de provider, aprovação sem execução, fila após aprovação e vínculo até DeploymentOutcome.

A integração usa SQLite temporário com ORM e serviços reais. Não chama modelos externos nem realiza deploy. O contrato `FOR UPDATE` é compilado para PostgreSQL; este teste não comprova o escalonamento concorrente de transações num servidor PostgreSQL real.

Os testes React verificam elegibilidade, erro de duplicidade no envio e filtragem do painel por task. O build de produção também é obrigatório. A evidência final do gate, com SHA e resultados das suítes, deve ser consultada nos eventos desta execução; não confundir os resultados simulados de deploy dos testes com um deploy real.

Não houve push nem deploy nesta entrega. Arquivos preexistentes fora do escopo foram preservados. A aprovação final pertence ao revisor independente.
