# Frota configurável — mapa da Fase 0

Data: 2026-09-15. Plano v5. Base inspecionada: `3a86d85d31b0277dda8175dbeb2338b1e7c956d4`.
Run: `34d73103-ff13-49b3-afa5-f58c1f6cb624`.
Subtask: `07f9b00b-879c-4aea-9286-d2c6f2d717c3` (ordem 9, primeira fatia).

Esta entrega documenta a arquitetura existente. Não implementa as fatias 2–8,
não altera configuração de produção e não certifica disponibilidade de modelos.
A inspeção precedeu a escrita deste documento; nenhum arquivo de aplicação foi alterado.

## CONFIRMADO — fontes e pontos de integração

| Área | Arquivos existentes | Contrato observado |
|---|---|---|
| AI Hub | `apps/web/src/pages/AIHub.tsx`, `apps/web/src/pages/AIHub.models.test.ts` | Lista fixa de opções com provider/model; guarda preferência no localStorage e envia ao backend. Ordem atual inclui Kimi/Qwen fixos e não corresponde ao plano v5. |
| Providers e inferência | `apps/api/app/routers/ai.py` | `COMPAT_PROVIDERS`, integrações diretas OpenAI/Anthropic e compatíveis; endpoint `/api/ai/chat`; seleção passa pelo cost guard. Reutilizar este router. |
| Credenciais | `apps/web/src/components/settings/tabs/AIProvidersTab.tsx`, `apps/api/app/routers/ai.py` | GET de status e PUT/DELETE de chaves por provider. A UI recebe configuração/disponibilidade, não o valor das chaves. |
| Catálogo | `apps/api/app/models/ai_routing.py` | `AIModelCatalog` mapeia `ai_model_catalog`: provider, provider_model_id, active, preços, contexto, capabilities, agent_slug e agent_preference_rank. Não criar outro catálogo. |
| Custo | `apps/api/app/services/ai_cost_guard.py` | Usa o catálogo canônico. A seleção dinâmica não deve contornar confirmação de custo ou aceitar preço inventado pelo cliente. |
| Router de agentes | `apps/api/app/services/agent_router.py` | `PROVIDER_TO_AGENT`, `MODEL_AGENT_OVERRIDES`, `route_agent`. OpenRouter ainda depende de vínculos de modelos específicos a Kimi/Qwen; integração genérica exige remover essa dependência para novas escolhas preservando histórico. |
| Recomendação | `apps/api/app/services/agent_recommendation.py` | Consulta catálogo, vínculos de agente e sinais de runtime; preservar contratos estruturados de recomendação. |
| Runtime local | `apps/api/app/services/agent_runtimes.py`, `apps/api/app/services/ollama_driver.py` | Registro de identidades Ollama separado de modelo; existe sondagem `/api/tags` e configuração por ambiente. |
| Estado dos runtimes | `apps/api/app/routers/agent_runtimes.py` | `list_agent_runtimes` lê `status.json`; o campo `models` representa modelo carregado observado, não inventário completo de modelos baixados. Não acrescentar um segundo loop concorrente de healthcheck. |
| Agentes | `apps/web/src/modules/agents/AgentsPage.tsx`, `apps/web/src/modules/agents/BuildQueue.tsx` | Workspace, filas, terminais e lifecycle; não há nesta página o executor padrão por fonte+modelo pedido. |
| Configuração | `apps/api/app/routers/settings.py`, `apps/api/app/api/endpoints/settings.py`, `apps/api/app/services/config_service.py`, `apps/web/src/services/settings.service.ts` | Endpoints existentes GET/PUT `/api/settings`; ConfigService combina default/ambiente/user.json. Não há preferência global de executor fonte+modelo identificada. |
| Handoff | `apps/api/app/services/handoff.py`, `apps/api/app/routers/handoffs.py`, `apps/api/app/schemas/handoff.py` | Aprovação/queue_build/update_run/veredito são do backend. Mudar provider/model não autoriza recriar workflow nem criar Run antecipadamente. |
| Revisão | `apps/api/app/services/review_policy.py`, `apps/api/app/services/review_cycle.py`, `apps/api/app/services/review_scope.py` | Decisão determinística após gate, base/SHA persistidos e auditoria; configuração em `config/review-policy.json`. Não existe ainda escolha recomendada Sim/Não persistida nesse fluxo. |

Nenhuma referência Hyphae foi encontrada em `apps/api/app` na base inspecionada.
Isso não prova ausência de serviço externo: significa que sua integração não está
implementada nesse código. O registry Ollama não pode ser apresentado como se
já descobrisse modelos Hyphae.

## CONFIRMADO — autoridade e resultados estruturados

ADR aceita `110f9855-f17e-426d-98fc-905acdf09813`, “Execução Canônica Agnóstica
de Agente”, consultada no contexto estruturado da Run:

- WorkDev governa workflow, estado, gates e nível de revisão; trocar agente não troca o processo.
- Texto do modelo não constitui prova de criação, persistência ou conclusão.
- A ADR prevê revisão formal de baixo risco e revisão independente quando exigida.
- Override pertence ao Cláudio e deve ser auditado, sem alterar o fato de um teste ter falhado.

No AI Hub, `send()` projeta `data.reply` como mensagem e utiliza campos retornados
pelo backend, como session_id/authority. Não se encontrou nessa função transição
de Task baseada em procurar palavras como “done” no texto. `BuildQueue` solicita
transições via API e recebe o estado da execução. Preservar essa separação.

O backend de chat possui caminhos que capturam falhas de persistência com rollback;
a fatia transversal de testes deve comprovar que falha de tool/commit não gera
uma confirmação operacional falsa, mesmo se o texto do modelo alegar sucesso.

## PROPOSTO — sequência de mudanças pequenas, uma fatia por revisão

1. Esta Fase 0: revisar o mapa e os contratos, sem implementação.
2. Apresentação do AI Hub: cinco fontes na ordem Gemini → GPT-4o mini → Claude Haiku → OpenRouter → Local. Ordem exclusivamente visual; nenhuma prioridade artificial no router.
3. OpenRouter: estender o router existente para expor entradas ativas de AIModelCatalog; seletor secundário usa provider_model_id. Modelo novo deve aparecer sem editar AIHub.tsx.
4. Local: expor inventário real dos runtimes suportados por adaptadores compatíveis com o registro existente; separar modelo baixado, modelo carregado e runtime indisponível. Não tratar default configurado como prova de disponibilidade.
5. Executor padrão: estender a configuração canônica existente e consumi-la em Agentes; precedência override explícito → preferência padrão → fallback. Não criar outra tabela/store nem gravar preferência apenas no navegador.
6. Revisão recomendada: perguntar Sim/Não; backend conserva a autoridade sobre classificação e obrigatoriedade. A escolha do usuário não pode equivaler a autoaprovação do executor.
7. Auditar recusa e impedir dispensa dos casos obrigatórios definidos pelo plano/ADR; não ampliar a lista por palavra-chave nesta task.
8. Regressão integrada: verificar identidade de executor/revisor, histórico, workflow, falhas parciais e autoridade de resultados estruturados. Sem deploy automático.

As propostas não são alterações já feitas nem decisões novas de produto.

## A CONFIRMAR — antes das fatias dependentes

- Hyphae: contrato do endpoint, autenticação, descoberta de modelos e local de configuração já existentes no runtime real. Não supor que Bonsai é Ollama nem cadastrar modelo fictício para satisfazer a UI.
- Catálogo em produção: existência/active/capabilities/preços da entrada OpenRouter desejada. A inspeção de código não certifica conteúdo de banco ou disponibilidade de provider.
- Preferência: chave/escopo da extensão de ConfigService e persistência entre releases/workers. O serviço atual usa arquivo relativo à raiz do projeto e objeto carregado em memória; isso deve ser verificado antes de prometer persistência do padrão na fatia 5.
- Revisão: conciliar os três estados do plano com a revisão formal prevista na ADR. “Não” pode dispensar revisão independente recomendada, mas não deve ser interpretado silenciosamente como dispensa de todo workflow formal. Se a solução exigir mudar essa decisão, registrar ADR proposta e bloquear a fatia dependente.
- Identidade: definir pelo contrato existente como provider/model genérico se vincula a executor sem criar um agente fictício e sem usar overrides Kimi/Qwen. Não confundir provider igual com executor necessariamente igual.

Nenhuma dessas hipóteses foi aplicada ao código nesta fatia. Não foi presumida
aprovação das fatias posteriores a partir do prompt acumulado.

## Validação desta entrega e cobertura futura

Inspeção manual dos arquivos, contratos e ADR listados; todas as referências a
arquivos devem existir nesta base. O diff da entrega deve conter somente este mapa.
O gate oficial deve ser vinculado ao SHA do documento antes do handoff.

Testes existentes a reutilizar nas fatias de implementação:
`apps/api/tests/test_ai_providers.py`, `apps/api/tests/test_ai_cost_guard.py`,
`apps/api/tests/test_ai_cost_safety_route.py`, `apps/api/tests/test_agent_runtimes.py`,
`apps/api/tests/test_agent_runtime_integration.py`, `apps/api/tests/test_handoff_review.py`,
`apps/api/tests/test_review_lifecycle.py`, `apps/api/tests/test_authority_payload_regression.py`,
`apps/web/src/pages/AIHub.models.test.ts`,
`apps/web/src/modules/agents/AgentsPage.test.tsx`.

A aprovação desta fatia valida o mapa, não certifica seletores, providers,
preferências ou fluxos Sim/Não que ainda não foram implementados. Subtasks 2–8
permanecem pendentes. Não há deploy nesta entrega.
