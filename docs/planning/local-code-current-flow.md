# local-code — discovery do BUILD e terminal persistente

Execução: `0cfdaf23-51f3-41fa-aeb7-69a2537b7365`.
Plano: `79c20440-bea0-42dc-88dd-87f7d78145b4`, versão 1.
Data: 2026-09-21. Inspeção de código, sem operação no Qwen real.

## Base e escopo verificados

Base `62bd9e2`, branch `feat/local-code-llamacpp`. A leitura de `.git/config`
foi restaurada pelo operador. As alterações anteriores de lifecycle/systemd
estão preservadas. Alterações concorrentes em `docs/agents` e
`compare_report.md` não pertencem a esta task.

O fluxo abaixo descreve a base anterior à implementação. A decisão final
está no ADR 007 e a evidência de validação em `local-code-validation.md`.

## Fluxo observado

1. `routers/handoffs.py` aprova/envia por `services/handoff.queue_build`,
   criando `AgentRun` e evento `build.queued`. No envio manual de runtime HTTP,
   `ensure_dispatchable_blocking` verifica disponibilidade antes da criação.
2. `BuildQueue.tsx` oferece despacho. `POST /handoffs/runs/{id}/dispatch`
   resolve modelo/health, gera contexto, aplica política de egresso e abre
   `AgentBuildJob` por `build_jobs.open_job`. O evento
   `build.dispatch_requested` contém run/job/runtime/modelo/hash do prompt.
3. `open_job` trava a run e o índice parcial impede dois jobs ativos para a
   mesma run. Isso não equivale a exclusividade entre duas runs do mesmo agente.
4. Com `WORKDEV_OLLAMA_BUILD_ENABLED`, `scripts/workdev_build_worker.py`
   consome jobs. `claim_next_job` usa `FOR UPDATE SKIP LOCKED` por job;
   `process_job` marca running, acrescenta contrato de envelope, chama
   `llamacpp_driver.dispatch` ou `ollama_driver.dispatch` e entrega a resposta
   a `execute_build`, que aplica a proposta e registra resultado/gates.
5. Sem essa flag, a rota agenda `_consume_dispatch_job` em background.
   Portanto a unificação precisa excluir local-code dos dois caminhos HTTP,
   sem criar um terceiro consumidor concorrente.
6. O Qwen interativo é outro processo: `start_local_agent.sh` executa
   `/usr/bin/qwen` com catálogo local, modelo `workdev-qwen27b` e diretório
   padrão `/opt/workdev`. `terminal.ALLOWED_SESSIONS` mapeia local-code para
   `local-code`; `STANDBY_COMMANDS` já aponta para esse launcher.
7. `/ws/agents/local-code` faz `tmux attach-session -t =local-code`.
   No disconnect encerra o cliente attach/PTY da ponte, não a sessão tmux.
   Abrir o WebSocket não cria sessão nem inicia modelo.
8. A base inspecionada já mostra local-code em `AgentTerminal` na aba Agentes:
   `AgentsPage.tsx` distingue remoto por prefixo `gpu-` e
   `AgentTerminalPage.tsx` aceita local-code explicitamente. A premissa de
   que a aba ainda oculta o terminal não se confirma neste código.
   Os links por run continuam apontando ao terminal por run.

## Autoridades e lacunas

| Componente | Autoridade existente | Tratamento previsto no plano |
| --- | --- | --- |
| `agent_runtimes` | Catálogo, engine, modelo e health | Preservar inferência/health; distinguir capacidade de execução CLI de transporte HTTP. |
| `agent_lifecycle` | Start/stop físico, lock por agente/run, registro durável PID/starttime | Completar para vínculo à sessão persistente; não criar segundo owner físico. |
| `build_jobs` / `AgentBuildJob` | Fila persistida e unicidade de job ativo por run | Completar exclusividade por runtime e recuperação de entrega incerta após crash. |
| `build_worker` | Claim e execução de proposta HTTP | Para local-code, converter em despachante da CLI; preservar demais runtimes. |
| `terminal.py` | Catálogo de sessões, attach e launch de agentes | Preservar attach canônico; impedir caminho `auto-local-code-<run>` para esta entrega. |
| `TerminalSessionManager` | Supervisor PTY persistido por run, replay e attach | Reutilizar como acesso ao executor vinculado, sem criar Qwen/bashes auxiliares para local-code. |
| `agent_snapshot` | Projeção operacional consolidada | Preservar como leitor; fila é workflow, sem novo healthcheck na UI. |
| `AgentRunEvent` | Auditoria persistida | Completar identidade da entrega, confirmação e cancelamento; não confundir hash com prova de recebimento. |
| `AgentsPage` / `AgentTerminal` | Terminal do agente e reconexão | Preservar caminho já presente e cobrir regressão; completar links por run e indicação de fila. |
| Consumidor HTTP de local-code | Caminho concorrente com CLI | Remover do despacho local-code quando o consumidor canônico estiver implementado. |

## Vínculo e parada: pontos que o ADR precisa resolver

`agent_lifecycle.bind_run` exige `auto-<agent>-<run_id>` e sessão Linux
exclusiva. `stop_run_process` mata essa sessão tmux e seus grupos verificados.
Reutilizar essas funções sem distinguir vínculo persistente destruiria o
Qwen que o plano manda preservar.

`agent_workspace.stop_run` exige confirmação da parada física antes de
persistir cancelled. `docs/AGENT_WORKSPACE_CONTRACT.md` documenta essa ordem.
Enviar Ctrl-C e declarar cancelled sem confirmação não preserva esse contrato.
O novo vínculo deve distinguir interrupção confirmada da run de parada do
agente; cancelamento incerto deve manter a sessão reservada e registrar erro.

`run_terminal._create_unlocked` já resolve o binding e passa
`tmux attach-session` ao manager. Sem binding, o manager cria um bash auxiliar;
esse fallback não representa o executor local-code. Não há necessidade
demonstrada de outro gerenciador PTY.

A base do launcher não fornecia canal auditável. A inspeção da CLI Qwen
0.24.0 instalada confirmou entrada nativa JSONL (`dualOutput.inputFile`),
que aguarda o estado ocioso da TUI para submeter `type=submit`, e hooks
UserPromptSubmit, Stop e ferramentas. Isso permite manter o mesmo processo.
Stop precede o estado ocioso da TUI; por isso a implementação acrescenta um
marcador de barreira pelo mesmo canal nativo antes de liberar a fila.

## Fluxo implementado

1. `queue_build` abre AgentRun/AgentBuildJob; local-code dispensa probe HTTP.
2. O worker existente seleciona a fila, respeitando disponibilidade e outro job
   running. O lock de lifecycle serializa a reserva entre processos.
3. `local_code_channel` persiste vínculo, nonce e contexto imutável com SHA-256.
   `local_code_build` grava intenção em AgentRunEvent e commita antes do envio.
4. O JSONL leva somente o marcador. UserPromptSubmit valida a identidade,
   carrega o contexto e confirma recebimento. Worker recupera o recibo após
   restart sem repetir o prompt. O caminho HTTP provisório também exclui local-code.
5. Terminal do agente usa attach ao mesmo tmux. O terminal de run só aceita
   um binding existente; não cria bash auxiliar para local-code sem entrega.
6. Parar Run espera barreira de cancelamento, mantendo Qwen/modelo. Uma CLI
   perdida pode ser cancelada sem sinalizar sua substituta apenas quando a
   identidade antiga terminou e não há ferramenta/background pendente.
7. Liberação exige workflow terminal/review mais fim de turno confirmado.
   Segunda run, trabalho manual e CLI sem protocolo mantêm a fila aguardando.
8. O coletor lê local-code como sessão híbrida; persistência não significa
   always-on. Não há recuperação automática que carregue o modelo no boot.

Não foi criado outro manager, tabela de fila ou processo executor. A decisão
substitui o envelope do ADR 005 somente para local-code. Runtimes remotos
mantêm o caminho anterior.
