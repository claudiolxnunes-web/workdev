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

## Correções da revisão independente fe9e5e0e

A primeira revisão de Claude rejeitou duas regressões. A autorrecuperação agora consulta `desired` sob o mesmo lock do lifecycle: `ONLINE` concluído permite novas recuperações, enquanto `OFFLINE` explícito impede recuperação. O lock da recuperação é não bloqueante; a coleta não fica na fila atrás de start/stop da API.

`finalize_auto_runtime` usa a recuperação do lifecycle e respeita a desconexão explícita. As rotas legadas POST/DELETE `/session` delegam aos mesmos endpoints de lifecycle de Conectar/Desconectar, atualizando a intenção durável.

A detecção de aprovação foi centralizada em `agent_activity.py`, preservando os padrões anteriores, 20 linhas não vazias e o guarda de retomada. O status não transporta texto de comandos: o aviso da UI orienta o usuário a conferir as opções no terminal, sem painel de prompt duplicado. Apenas Claude/Codex fora de uma sessão AUTO são classificados como persistentes; os outros agentes são sob demanda. GPU sem configuração continua identificada como `unconfigured` no contrato de catálogo.

O healthcheck volta a sair com código 1 quando um always-on termina OFFLINE/ERROR. Os novos testes estão em `test_agent_review_regressions.py`, incluindo recuperações sucessivas, desconexão seguida de finalização AUTO e reconexão pela rota legada, lock ocupado, padrões de aprovação, retomada, exit code e persistência.

## Procedimento de ativação para o operador após revisão

Não executar estes passos como parte do BUILD. O broker de deploy não instala units. A promoção deve incluir o coletor, suas units e API/UI compatíveis:

1. Confirmar a revisão do commit e preparar a implantação assinada conforme `CLAUDE.md`.
2. Pausar somente o timer de healthcheck e aguardar a coleta corrente terminar. Não parar `workdev-agents.service` nem suas sessões tmux.
3. Promover API/UI pelo fluxo `prepare` → `approve` → `deploy.sh <proof_id>`, usando o build revisado. A release contém também o coletor; o script resolve sua raiz imutável e importa os módulos dessa mesma release.
4. Instalar como operador/root os fontes revisados `scripts/workdev-agents-health.service` e `scripts/workdev-agents-health.timer` em `/etc/systemd/system/`. O ExecStart aponta para `/opt/workdev-runtime/current/scripts/agents_healthcheck.py`, nunca para o checkout mutável.
5. Executar `systemctl daemon-reload`, iniciar somente o timer de healthcheck e uma coleta. Conferir units e snapshot v2 novo. A próxima coleta ocorre 5s após a anterior encerrar; TimeoutStartSec=35s. Durante a transição, snapshot ausente/antigo aparece como ERROR até a primeira coleta válida.
6. Verificar o endpoint de status da release promovida. Em rollback, restaurar timer/unit e release como conjunto compatível; nunca deixar o leitor v2 com cadência de 5min.

Esses passos não foram executados neste BUILD.


## Correções da segunda revisão (9de78221)

- [1, 7] Falhas de lifecycle encerram `running` e atualizam o timestamp. A informação de falha é exibida por 60s, depois o coletor reconcilia a evidência física. Registro ilegível e inconsistência física continuam ERROR.
- [2] Uma intenção OFFLINE concluída impede autorrecuperação, mas não invalida um início manual posterior observado fisicamente. STARTING/STOPPING em voo continuam tendo precedência.
- [3] O coletor consolida `run_status` no arquivo. `blocked`, `review` e `completed` voltam aos badges sem transformar atividade humana em BUSY nem consultar banco na leitura REST/WebSocket. Foram removidos o parâmetro ignorado e a consulta/classe de badge antigos da API.
- [4] Sondas paralelas pertencem ao único coletor, sem novo loop. São três consultas de contexto por coleta, sem sessão SQLAlchemy compartilhada entre threads. Agentes saudáveis são publicados assim que respondem. Após orçamento de 25s, sondas pendentes recebem `collection_timeout`; o serviço tem limite físico de 35s. Chamadas subjacentes também possuem timeouts. O timer usa OnUnitInactiveSec=5s (não há fila de ativações do mesmo serviço).
- [5] Ledger durável de notificações exige estabilidade por 10s, intervalo mínimo de 300s por agente e no máximo uma mensagem por coleta. ERROR/OFFLINE são uma classe de falha para evitar alternância de alertas. A chamada Telegram tem timeout de 2s.
- [6] Texto do terminal é evidência de atividade, nunca prova de falha física. Motivo de bloqueio textual fica em `activity_reason`; números 401/429 e a palavra billing isolados não classificam falha de runtime.
- [8, 9] A falha de ação usa o snapshot vigente quando a requisição rejeita. Abortar o polling ao perder foco preserva o último estado e a aprovação pendente.
- [10] Finalização AUTO volta a lançar erro se uma restauração efetivamente tentada deixou a CLI sem processo pronto. Desconexão deliberada ou lock ocupado continuam respeitados.
- [11] Cliente deixou de enviar refresh=true. Compatibilidade REST informa `source=status.json` e `probe_requested=false`: atualizar relê o arquivo; forçar outra sonda violaria o plano aprovado.
- [12] Serviço, coletor e imports usam a mesma release promovida. O procedimento de ativação acima foi atualizado, sem executar deploy ou instalar units.

Validação operacional: SIGKILL/tmux, reinício de processos FastAPI e concorrência são exercitados com agentes descartáveis e arquivos isolados. A UI é exercitada em componentes. Isso não equivale a uma prova de campo no navegador contra produção, nem a reiniciar a API de produção. O gate vinculado ao novo SHA será registrado na execução; aprovação independente continua necessária.
