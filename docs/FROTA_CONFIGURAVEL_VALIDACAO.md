# Frota configurável — entrega das subtasks 4–8

Task `dbfb945e-6fc8-4f38-bbc4-51b9898536db`, plano aprovado v5.
Cláudio autorizou concluir as subtasks restantes e revisar o conjunto ao final.

## Configuração e contratos

- AI Hub consulta modelos OpenRouter ativos no catálogo existente e modelos locais
  instalados via inventário Ollama. A identidade do runtime acompanha a seleção.
- O Executor padrão fica em Agentes e persiste em `agents.executor` no arquivo
  canônico de configurações. Workers recarregam o arquivo; escritas usam lock e
  substituição atômica. Override explícito da execução tem precedência. Sem padrão,
  permanece a escolha manual; padrão removido do catálogo exige nova escolha.
- Modelos de execução cloud precisam do vínculo `agent_slug` no catálogo existente.
  Um modelo disponível para chat não ganha automaticamente um CLI executor.
  OpenRouter não deduz agente a partir do nome do modelo.
- A escolha do revisor por fonte/modelo é validada, auditada e incluída no pacote
  de revisão. O despacho e as sessões CLI continuam usando o fluxo existente;
  esta mudança não instala nem reconfigura provedores dentro de CLIs.
- Recusa de revisão recomendada gera `build.review_preference`. A política é
  reavaliada sobre o diff após os gates; escopo sensível continua exigindo revisão
  independente. A lista de sinais sensíveis da política existente foi preservada.
- Resposta textual do modelo não cria estado operacional: somente o executor
  canônico de tools e os recibos do backend confirmam persistência.

## Ollama validado nesta VPS

ADR aceita `f56c149d-ef73-4da9-8b06-e603d5292008`: usar o GGUF Bonsai no Ollama,
com parser/renderer Qwen3.5, em lugar de modificar o Hyphae.

Modelo instalado `workdev-bonsai-27b:q1_0`, contexto explícito 32768; VPS com
32 GiB de RAM e 8 CPUs. O nome não é hardcoded no catálogo da aplicação.
Modelfile e evidência operacional ficam em `.workdev/runtime-validation/bonsai-ollama/`.

Teste real `test_real_local_model_with_canonical_plan_and_tools`: PASS em
700,05 segundos (11min40s), com system PLAN completo, schemas canônicos de tools,
uma chamada `criar_task`, exatamente uma linha persistida em SQLite isolado e
continuação após o recibo. Uso reportado: 11466 tokens de entrada somados às
duas chamadas, 86 de saída. Nenhuma task de produção foi criada pelo teste.

O teste anterior com timeout de 600s expirou durante o processamento inicial.
O cliente local usa timeout configurável de 900s, sem repetição automática,
temperatura zero e limite de contexto verificado antes de cada chamada.
A latência observada em CPU é uma limitação operacional, mesmo com teste aprovado.

## Validação reproduzível

- Backend: `pytest tests/ -q -p no:cacheprovider`, com
  `WORKDEV_API_ENV_FILE=/dev/null` e DSN fictício de testes.
- Frontend: `pnpm exec vitest run` e `pnpm run build` em `apps/web`.
- Visual: `PLAYWRIGHT_E2E=1 pytest tests/test_ai_hub_sources_browser.py`, usando
  Chromium e o build, com fixtures HTTP isoladas, em larguras 1440 e 390.
- Real local (opt-in): `WORKDEV_LOCAL_MODEL_TEST=<modelo instalado>` e
  `WORKDEV_LOCAL_CHAT_TIMEOUT=900`, executando `tests/test_ai_local_roundtrip.py`.
- Gate final: serviço canônico `app.services.test_gate.execute_gate`, com evidência
  ligada à run e ao SHA da entrega; resultados registrados no evento da task.

Esta entrega não executa deploy. Revisão independente e publicação são etapas
posteriores à implementação e às validações.
