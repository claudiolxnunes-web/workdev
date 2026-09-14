# Agent Workspace — contrato de arquitetura

Status: contrato e correção das incompatibilidades aprovados pelo Cláudio em 2026-09-14; implementação entregue para revisão independente.
Data da inspeção: 2026-09-14.
Task: 202526fc-53fc-4133-a68e-5cc7b1562f70.
Execução atual: 0a60435c-286a-43cc-9d01-bfee347ccf8e (transferida do Gemini).
Plano aprovado: 26c75002-84c8-44d9-9b65-4168d37b6a90, versão 2.

Este documento foi produzido isoladamente na Fase 1. Cláudio aprovou a ordem
da parada e depois a associação física por Run, autorizando resolver as
incompatibilidades. O inventário abaixo registra a base anterior; a seção 10
descreve a implementação e a validação, sem substituir a revisão independente.

## 1. Inventário e autoridades existentes

| Informação / operação | Autoridade e evidência no código | Contrato do Workspace |
| --- | --- | --- |
| Identidade/configuração de agentes | Catálogos em `services/agent_runtimes.py` e `routers/terminal.py` | Reutilizar; não criar tabela de agentes. Configuração não comprova ONLINE. |
| Runtime e atividade | `services/agent_snapshot.py`: `AgentSnapshot`, `read_snapshot`, `publish`; arquivo consolidado `status.json` | Uma leitura consolidada por resposta, sem cache operacional da API ou sondagem física no polling. |
| Processo, sessão, modelo e operações físicas | `services/agent_lifecycle.py`: `read_state`, `start`, `stop`, `lifecycle_operation` | Reutilizar locks, identidade de processos e mecanismo existente; sem scripts paralelos de controle. |
| Run, plano e task | `models/handoff.py`: `AgentRun`, `ExecutionPlan`, campos de associação; roteador `handoffs.py` | Banco é autoridade do workflow, não prova de processo vivo. Preservar máquina de estados e gates existentes. |
| Terminal de Run | `models/terminal_session.py`: `TerminalSession.run_id` único, FK RESTRICT; `services/terminal_sessions.py`: `TerminalSessionManager` | Resolver por run_id; não presumir que todo agente tenha TerminalSession. |
| Processo PTY e replay | `services/terminal_worker.py`; manager `snapshot`, `attach`, `close` | Reutilizar worker existente. Buffer exposto com limite de 65536 bytes e retenção durante a vida do worker; não prometer histórico ilimitado. |
| Eventos de Run | `models/handoff.py`: `AgentRunEvent` e rotas de eventos | Reutilizar auditoria de Run; verificar cobertura de ações sem Run antes de escolher extensão mínima. |
| UI atual | `AgentsPage.tsx`, `RuntimeControls.tsx`, `AgentTerminal.tsx`, `BuildQueue.tsx`, `RunTerminal.tsx` | Compor o cockpit a partir destes componentes, preservando reconexão e controles existentes. |

Caminhos de backend acima são relativos a `apps/api/app/`; componentes a
`apps/web/src/modules/agents/`.

## 2. Estados e associação

Runtime canônico: OFFLINE, STARTING, ONLINE, STOPPING, ERROR.
Atividade canônica: IDLE, BUSY, WAITING_INPUT. Ambos permanecem separados.
ONLINE/IDLE representa disponível; ONLINE/BUSY representa ocupado;
ONLINE/WAITING_INPUT representa aguardando entrada (rótulo visual WAITING).
STARTING, STOPPING e ERROR nunca são substituídos por um rótulo de atividade.

`read_snapshot` já transforma arquivo ausente/inválido, linha inválida e amostra
vencida em ERROR. O prazo padrão existente é 45 segundos. A UI deve mostrar
motivo e data da amostra, sem deduzir ONLINE de tmux ou cadastro estático.
Falha HTTP deve ser apresentada como indisponibilidade, sem manter aparência
enganosa de estado atualizado.

O Workspace associa agentes e Runs usando identificadores persistidos, exibindo
run_id, task/backlog_id e status de workflow separadamente do estado físico.
Não escolher arbitrariamente a última Run quando houver associação ambígua.
Conflito entre associação persistida e snapshot deve ser explícito e impedir
controle destrutivo com alvo incerto.

## 3. Contratos HTTP e WebSocket a reutilizar

| Contrato existente | Uso |
| --- | --- |
| GET `/api/agents/status` | Snapshot canônico de agentes. |
| GET `/api/agent-runtimes` | Catálogo/modelos enriquecidos pelo mesmo snapshot; `refresh` não cria sondagem. |
| GET `/api/agents/{agent}/lifecycle` | Detalhe consolidado de lifecycle. |
| POST `/api/agents/{agent}/start` | Início idempotente via lifecycle. |
| POST `/api/agents/{agent}/stop?confirm=true` | Parada via lifecycle; recusa trabalho em execução. |
| Rotas existentes `/api/handoffs/runs` | Consultar workflow, associações e eventos, preservando contratos. |
| WS `/ws/agents/{agent}` | Attach à sessão do agente, com alvo tmux exato. |
| GET `/api/runs/{run_id}/terminal` | Estado da sessão, processo, PTY e buffer. |
| POST `/api/runs/{run_id}/terminal/reconnect` | Localizar terminal vivo existente; 409 quando encerrado. |
| WS `/ws/runs/{run_id}/terminal?existing=1` | Reattach sem criar processo. Preservar writer/observer e takeover explícito. |
| POST `/api/runs/{run_id}/terminal` | Criação explícita idempotente; nunca efeito colateral de reconnect. |
| DELETE `/api/runs/{run_id}/terminal` | Encerrar PTY; não equivale sozinho a cancelar workflow da Run. |

Na Fase 2, preferir extensão compatível do endpoint de status para devolver a
associação com Runs. Uma requisição consolidada deve ler um único snapshot,
sem recompor estados de múltiplas leituras concorrentes. Consultar detalhes de
PTY apenas para terminal selecionado ou ação explícita; não sondar todos os
processos a cada polling. Não criar endpoint redundante sem demonstrar lacuna.

## 4. Fluxos e limites de ações

- Abrir terminal de agente: attach ao agente selecionado, sem start implícito.
- Abrir terminal de Run: recuperar sessão por run_id; criação, se oferecida,
  deve ser ação explícita distinta de recuperar.
- Reconectar: recriar somente bridge, preservando processo, Run e buffer.
- Fechar painel/aba: detach apenas. `terminal.py` encerra seu cliente attach;
  `RunTerminal.tsx` fecha WebSocket no cleanup. Nunca chamar stop/cancel no cleanup.
- Iniciar/parar agente: usar lifecycle existente, atualizar UI após resposta,
  preservar confirmação de parada e recusa quando há execução ativa.
- Parar Run: validar autorização, transição e alvo antes de qualquer sinal;
  parar fisicamente o runtime identificado; confirmar término; só então persistir
  cancelamento do workflow e evento de sucesso. Não parar agente compartilhado
  por inferência baseada apenas no nome.

Lacuna comprovada: `routers/handoffs.py`, atualização de Run, chama `update_run`
antes de `finalize_auto_runtime` e apenas registra warning se a finalização
falhar. Esse fluxo não satisfaz a ordem exigida para a ação Parar Run do Workspace.
A Fase 2 deve separar validação da persistência nessa operação, reutilizando a
validação existente e o controle físico existente. Não inverter genericamente
conclusão/review/deploy nem duplicar máquina de estados.

Se parada física falhar ou ficar incompleta, manter workflow sem falso
cancelamento concluído, retornar erro/pendência e auditar motivo. Se a persistência
falhar depois da parada física, expor inconsistência recuperável, permitindo
repetição idempotente sem relançar processo. Testar concorrência e alvo já encerrado.

## 5. Auditoria, usuário e atualização

Auditar solicitação, alvo exato (agente, Run e sessão quando aplicável), ator
obtido do contexto autenticado disponível, horário, resultado e motivo de erro.
Não registrar tokens, comandos com secrets, conteúdo de terminal ou credenciais.
Eventos de Run existentes são reutilizáveis. Logs técnicos de attach/lifecycle
não devem ser declarados auditoria completa sem verificar retenção e consulta.
Para ações sem Run, inspecionar armazenamento de auditoria existente antes da
implementação; não criar nova fonte de estado operacional.

Executar lifecycle e attach como usuário WorkDev, no mesmo escopo/socket do
runtime. O teste obrigatório deve incluir sessão Kimi pertencente a workdev e
não visível ao root. Não remediar com execução em root nem buscas amplas que
atinjam sessões de outro usuário.

Polling do cockpit: 5–10 segundos, sem requisições sobrepostas, com cancelamento
no unmount e atualização imediata após ações. UI representa respostas do backend;
`pending` local é estado da requisição, não transição persistente do runtime.

## 6. Validação antes da entrega das Fases 2–5

1. Registrar revisão e aprovação deste documento antes de implementar.
2. Integração com snapshot real da VPS: associação agente/Run/task, amostra
   inválida/vencida e indisponibilidade; sem segundo healthcheck.
3. UI real/mock: todos os estados, agente sem Run, Runs encerradas, falhas e
   ações distintas; polling controlado e feedback imediato.
4. E2E terminais de agente e Run: abrir, fechar e recuperar mantendo processo,
   Run.id e replay; encerrado não ressuscita; writer/observer preservados.
5. E2E lifecycle: start/stop idempotentes e recusa BUSY; Stop Run confirma
   parada física antes do workflow; falhas, concorrência e auditoria verificadas.
6. Regressão Kimi no usuário correto; suites existentes de lifecycle, snapshot,
   terminal e run_terminal; build frontend obrigatório antes de entrega completa.

## 7. Registro histórico da Fase 1

Inspeção de código concluída e contrato proposto. Nenhuma implementação das
Fases 2–5, teste E2E, commit ou deploy é declarado por este documento.
Operações Git estavam impedidas por permissão de leitura em `.git/config`;
a inspeção preservou arquivos existentes e não alterou permissões do repositório.
Naquele momento a aprovação estava pendente; foi recebida nas decisões
registradas nas seções 8–10.

## 8. Decisão aprovada pelo Cláudio — Parar Run

Em 2026-09-14, após apresentação explícita da solução, Cláudio respondeu
“sim, aprovado”. A aprovação cobre validar transição e alvo exato, parar pelo
lifecycle existente, confirmar término físico e somente então persistir
`cancelled` com auditoria. Se a parada falhar, não declarar cancelamento
concluído. Se a gravação falhar depois da parada física, permitir repetição
idempotente sem reinício. Não modificar gates de conclusão, revisão e deploy.

Esta aprovação de arquitetura não representa veredito da implementação pelo
revisor independente, execução de testes ou autorização de deploy.

## 9. Impedimento descoberto ao validar o alvo físico

O acesso Git foi corrigido e a branch `task/202526fc-agent-workspace` foi
criada, preservando o arquivo preexistente `deploy/workdev-deploy-prepare.sudoers`.

A aprovação da seção 8 resolve a ordem da parada, mas não fornece identidade
física onde ela ainda não existe. Evidências da base inspecionada:

- `agent_lifecycle.remember_group` registra PGID/starttime sob a chave do agente,
  sem run_id. `stop` termina todos os grupos conhecidos desse agente. Portanto
  passar uma sessão específica para `stop` não limita todos os sinais àquela Run.
- `TerminalSessionManager.create` inicia por padrão um bash independente. A FK
  run_id prova o vínculo do terminal, não que o agente esteja executando nele.
- `active_work` e o coletor associam trabalho consultando estado persistido de
  Runs/jobs; essa associação não prova qual processo executa uma Run manual.
- `_auto_session` fornece nome específico para execuções AUTO, mas não resolve
  Runs manuais executadas em sessão persistente compartilhada.

Assim, encerrar somente TerminalSession pode deixar o agente executando; chamar
stop do agente pode encerrar outras execuções. Nenhuma dessas alternativas
satisfaz simultaneamente isolamento e confirmação física para todas as Runs.

Revisão proposta: explicitar como pré-requisito a associação física por Run no
registro/launcher existente e parada restrita a esse alvo em agent_lifecycle.
Runs legadas sem associação comprovada recusam parada sem sinalizar processos.
Alternativa: restringir o aceite de Parar Run a execuções já isoladas e comprovadas,
adiando suporte pleno das manuais; isso exige reduzir explicitamente o escopo.
Não criar tabela de agentes, fonte paralela de estado ou gerenciador PTY.
Nenhum código operacional foi alterado com base em uma escolha presumida.

## 10. Implementação após aprovação da associação física

Cláudio aprovou: “sim, aprovado. Resolva as incompatibilidades todas.”
ADR `aef9b61e-90e4-4a4c-b704-22a9fad4acea` registrado como accepted.

- O registro existente de lifecycle agora inclui vínculos por Run com agente,
  sessão exclusiva (quando há tmux), PID, sessão Linux, identidade de início,
  grupos e confirmação persistida da parada. Não existe tabela de agentes nova.
- Launchers registram identidade antes de entregar o trabalho. Gemini headless
  preserva a espera síncrona e registra o processo isolado, sem inventar um TTY.
- POST `/api/handoffs/runs/{id}/start` reutiliza o executor existente para iniciar
  uma Run CLI aguardando em sessão isolada. Não cria outra Run ou outro plano.
- PATCH da Run para cancelled valida e serializa a transição, audita intenção,
  encerra exclusivamente o processo vinculado e o terminal associado, confirma
  o término e só então usa `update_run`. O validador existente permanece único.
- Finalizadores automáticos respeitam a confirmação de parada e não restauram
  standby depois de Parar Run. Tentativas com PID/sessão substituídos são recusadas.
- GET `/api/agents/status?workspace=true` acrescenta Runs/task ao snapshot único,
  sem sondagem física no polling. A forma anterior continua disponível sem DB.
- O cockpit mostra links por Run, Parar Run, controles do agente e detach
  explícito. Polling fica em 5–10s; respostas antigas de outra seleção não podem
  substituir o contexto atual. Divergência da associação vira ERROR.
- TerminalSession ligada a executor tmux usa o mesmo manager/worker para attach.
  Seu ID é verificado contra o vínculo da Run, recusando um terminal auxiliar
  anterior. Terminais auxiliares são identificados como tais na UI. Runs
  headless não oferecem um terminal interativo fictício.
- Auditoria reutiliza `AgentRunEvent`, inclusive eventos sem Run para start/stop
  do agente. GET `/api/agents/{agent}/events` permite consultá-los. O ator é
  `authenticated_operator`, pois a autenticação atual compartilhada não fornece
  identidade individual. Não são armazenados prompts ou credenciais.

### Validação realizada

- Backend: 261 testes passaram (mais 10 subtests), incluindo isolamento real
  de tmux, PTY, identidade, concorrência, transições, persistência de auditoria,
  snapshot/restart e regressões dos launchers.
- Frontend: 89 testes em 14 arquivos passaram.
- Dois E2E Chromium passaram: refresh/fechar aba/chat indisponível preservando
  Run e buffer; cockpit com terminal do agente e da Run, detach/reconnect,
  parada física e auditoria persistida em banco isolado.
- Sessões reais descartáveis pertencentes ao usuário workdev foram utilizadas;
  a Run vizinha e o standby permaneceram vivos após parar a Run alvo. Nenhuma
  sessão operacional real de Kimi foi encerrada para testar.
- Consulta ao snapshot/PostgreSQL da VPS1 em transação READ ONLY encontrou
  8 agentes e 7 Runs, com associação por agente verificada.
- Build frontend e lint dos quatro arquivos de UI alterados passaram.
- Artefatos locais: `/tmp/workdev-workspace-real.png` (runtime de teste real,
  dados de workflow isolados) e `/tmp/workdev-reconnect-e2e.png`.

### Limites explícitos

Runs legadas sem vínculo físico não recebem sinais por inferência: a API retorna
409 e audita a recusa. O operador pode continuar pelo terminal do agente.
Processos headless continuam sem terminal interativo. O teste de separação de
usuários usa sessões pertencentes a workdev; não foi aberta sessão privilegiada
root para simular descoberta. O runtime e os controles não dependem de root.
Não houve migration, deploy ou mudança nos gates prepare/approve/deploy.
O gate oficial e o veredito final são registrados na execução, separadamente
deste relatório. Arquivo preexistente de sudoers preservado fora da mudança.
