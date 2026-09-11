# Task 3 — estado de runtime dos agentes

Execução: `75cb912b-f065-47f2-82b6-9fca8a20a57a`.
Plano v2 com adendo autorizado pelo usuário: ADR `e9440787-da85-48c2-930d-b3ee260096e1`, opção 2, accepted. O adendo inclui persistência e integração com o lifecycle da Task 2, preservando seu gerenciamento físico.

## Contrato e implementação

- Runtime: OFFLINE, STARTING, ONLINE, STOPPING, ERROR. Atividade: IDLE, BUSY, WAITING_INPUT.
- `agent_snapshot.py`: contrato Pydantic, leitura única do arquivo por requisição, validade por agente (45 segundos), erro explícito para ausência/corrupção/expiração. Nenhum cache operacional no backend.
- `/api/agents/status`, `/api/agents/{agent}/lifecycle`, `/api/agent-runtimes` e recomendação leem o snapshot. Metadados de catálogo nunca tornam um runtime ONLINE. Sondas pontuais de despacho continuam separadas da exibição e não mantêm cache em RAM.
- Escritas usam lock do sistema operacional, arquivo temporário, fsync e rename. Amostras antigas não sobrescrevem uma transição mais recente; a ordem da resposta é estável entre processos.
- Lifecycle usa locks por agente entre processos e registro durável dos grupos, sem fallback de identidade em memória. Guarda intenção, fase e identidade do processo responsável antes da ação física. Publica STARTING/STOPPING por evento, sem novo loop. Uma falha interrompida é reconciliada pelo coletor central; operação incompleta tem prazo de 60 segundos antes de ERROR.
- `agents_healthcheck.py` é o único coletor periódico. Reutiliza `read_state` e `start` da Task 2, inclui modelos locais/GPU e respeita desconexão explícita dos agentes persistentes. Aprovação/entrada pendente prevalece sobre BUSY na classificação do terminal. Texto de terminal não é publicado.
- UI separa runtime e atividade e oferece Conectar/Desconectar via `/start` e `/stop?confirm=true`. GPU remota não recebe controle local. O botão não presume ONLINE ao receber resposta. Falha de leitura/ação aparece como ERROR.
- Nenhuma recomendação de modelo ou requisito de RAM foi ampliado.

## Validação executada

Backend (em `apps/api`, com DSN fictício e env `/dev/null`):

```sh
DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/fake WORKDEV_API_ENV_FILE=/dev/null PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest tests/test_agent_runtime_integration.py tests/test_agent_snapshot.py tests/test_agent_lifecycle.py tests/test_agents_healthcheck.py tests/test_agent_runtimes.py tests/test_agent_recommendation.py tests/test_terminal.py -q -p no:cacheprovider --tb=short
```

Resultado: **221 testes e 7 subtests passaram**. Um aviso de depreciação de Starlette/TestClient; sem falha. O sandbox bloqueia sockets tmux e a execução foi repetida com permissão, em socket privado e com agentes Python descartáveis.

Evidências cobertas pelos testes:

- SIGKILL de agente descartável em tmux privado: snapshot transita de ONLINE para OFFLINE/ERROR em menos de cinco segundos.
- STOPPING permanece visível enquanto a parada física está retida; dois processos FastAPI/TestClient iniciados separadamente retornam o mesmo snapshot durante essa parada.
- Reinício de processos FastAPI/TestClient com agente BUSY preserva a resposta inteira.
- 48 leituras HTTP concorrentes idênticas; 24 escritores preservam todos os registros; oito processos separados respeitam o lock.
- Start repetido conserva o PID; stop repetido retorna already_offline. Desconexão explícita não aciona autorrecuperação.
- Corrupção/expiração, modelo desconhecido, grupos sobreviventes e operação interrompida resultam em ERROR.

Frontend (`apps/web`): `pnpm test`: **75 testes em 13 arquivos passaram**. Incluem WAITING_INPUT, STOPPING, atualização ONLINE → OFFLINE, falha de ação e ausência de suposição otimista de ONLINE.

`pnpm run build`: **passou** (TypeScript + Vite). Bundle `index-*.js` sem `localhost:8000`. `git diff --check` sem erros.

O gate formal completo também executou a suíte inteira de Python: **940 testes e 23 subtests passaram**, com 19 skips e 35 avisos. Vitest e build passaram. Lint global apresentou dívida preexistente em DatabaseTab, MonitoringTab, RepositoryTab e AIHub; o lint dos fontes frontend desta task passou após correção do componente de controles. A política existente do gate trata o lint histórico como não bloqueante. O resultado final vinculado ao commit fica nos eventos da execução.

## Limites e ativação

Os reinícios são de processos FastAPI isolados usando ASGI/TestClient; não houve restart do serviço de produção. A UI foi validada por testes de componentes, sem teste de navegador contra produção.

Implementação preparada na branch `task/72d5846f-agent-runtime-state`. O gate formal será vinculado ao commit e seu resultado registrado nos eventos da execução. Não houve push, deploy ou instalação de units nesta execução. Os fontes do serviço usam o Python do venv; o timer existente foi ajustado de cinco minutos para cinco segundos (AccuracySec=1s). A instalação/ativação desse timer e a atualização coordenada do coletor/API/UI devem integrar a implantação revisada. Manter o timer antigo com o novo contrato produziria ERROR por expiração de 45 segundos; snapshots v1 também são tratados como ERROR até a primeira coleta v2.

A conclusão e o veredito pertencem ao revisor independente Claude.
