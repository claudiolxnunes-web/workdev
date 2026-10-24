# Discovery — Jev Decision Router e Run Observer

Run `e5c11a18-c3d2-4112-b1e2-32490368cfc4`; base `a932856`.
Fase 1: inspeção somente leitura do código funcional; nenhum componente novo
foi implementado antes deste registro. UI e local-code fora do escopo.

| Componente | Estado atual | Reutilizar / tratamento | Lacuna |
| --- | --- | --- | --- |
| task_complexity.py | LOW/MEDIUM/HIGH/CRITICAL determinísticos | Preservar como piso conservador | Decisão Jev, confiança e probabilidades |
| agent_router.py / agent_recommendation.py | Catálogo/custo/capacidade escolhem executor | Preservar | Entrada de complexidade classificada antes da execução |
| routers/ai.py get_openai, COMPAT_PROVIDERS | OpenRouter e demais providers já configurados | Completar transporte de Decisions sobre o cliente existente | Endpoint alpha/decisions, sem provider paralelo |
| AIModelCatalog / ai_cost_guard | Catálogo, preços, confirmação e budgets | Preservar | Seleção configurável de modelos/fallback do Observer |
| AICallLog | Modelo solicitado/selecionado, custo/tokens/correlação | Completar uso | Registrar Jev e Observer, inclusive falhas |
| AgentRun / queue_build | complexidade/score, modo/motivo, revisor independente | Completar | Aplicar decisão supervision_policy e vincular evidência pré-run |
| AgentRunEvent / add_run_event | Histórico durável dos eventos | Completar | Contrato de eventos relevantes e recibos idempotentes de observação |
| workdev_build_worker.py | Consumidor existente de trabalho em background | Completar | Consumo de eventos persistidos, sem polling do projeto, sem outra fila/tabela |
| review_policy / review_cycle | Gate primeiro, diff imutável, decisão/ciclo persistidos | Completar | Observer pendente/finding e piso HIGH/CRITICAL antes de dispensa |
| test_gate | Evidência vinculada ao SHA | Completar | Remover exceção antiga que tolera lint reprovado |
| update_run / create_review | Máquina de estados e executor != reviewer | Preservar/completar | Conclusão adaptativa apenas com evidência atual e gates verdes |
| Supervisor de Qualidade | Infra/checks próprios | Preservar intacto | Não participa deste Observer |
| Contratos Jev/Observer | Ausentes | Criar contratos Pydantic e adaptadores mínimos | Sem ferramentas de escrita, shell ou ação em respostas |
| Bus, fila, tabela novos | Ausentes | Não criar | Eventos existentes bastam para consumo e auditoria |

O canal de eventos é AgentRunEvent. O worker existente consome eventos relevantes
com recibos vinculados aos seus IDs; a API/CLI não aguarda inferência do Observer.
Falhas físicas são tratadas deterministicamente antes de qualquer consulta IA.
O backend decide transições; a resposta do Observer não executa ações nem aprova.

A política legada dispensa revisão para risco baixo/trusted e respeita escolha do
usuário apenas sem caminhos sensíveis. O adaptador deve conservar essas regras
soberanas e acrescentar requisitos, nunca permitir que Jev/Observer neutralizem
gates, diff indisponível ou revisão HIGH/CRITICAL.
