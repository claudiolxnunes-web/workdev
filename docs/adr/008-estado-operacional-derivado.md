# ADR 008 — Estado operacional é derivado, nunca armazenado como verdade

Status: proposed (implementação submetida a revisão independente).
Task: `853b702d-0032-4bbc-b524-42a44252fdda`.
Plano aprovado v2. Run: `8a5c04a2-be33-4222-89b7-a9301b32e361`.

## Contexto

`/api/agents/status?workspace=true` publicava Codex como ONLINE enquanto
`/api/agents/codex/send` devolvia HTTP 503. As duas rotas respondiam sobre o
mesmo agente a partir de fontes diferentes:

- `/status` lia o snapshot durável do healthcheck, cujo ONLINE derivava de
  `AgentState.agent_process_running` — e, por tabela, de processos do group
  registrado e do modelo residente;
- `/send` chamava `_live_session()`, que devolvia o nome da sessão standby
  **sem verificar se ela existia**, e só então estourava no `tmux send-keys`.

Com o Codex App Server sobrevivendo a uma sessão tmux morta, `offline` ficava
`False` (há process group vivo), a aba mostrava o agente disponível e o
primeiro envio falhava. A recuperação automática também nunca disparava,
porque estava condicionada a `state.offline`.

A aba parecia "instável" depois de vários reparos pontuais em terminal, AUTO,
reset e seleção de modelo porque o conceito de ONLINE ainda admitia um estado
fisicamente incapaz de receber comandos.

## Decisão

**O estado operacional é derivado do sistema no momento do uso. Snapshot, PID,
PGID e daemon auxiliar descrevem; nunca concedem capacidade.**

1. `app/services/agent_operability.py` é a única definição de "agente
   operacional". `resolve()` devolve um `OperationalState` com `operational`,
   `interactive`, `session_name`, `session_source` (`auto|standby|none`),
   `session_exists`, `process_alive`, `daemon_alive`, `send_ready`,
   `terminal_ready`, `determinate` e `health_reason`.

2. Para agentes CLI, sessão válida exige `has-session` com target exato,
   painel resolvível e painel vivo (`pane_dead=0`). A ordem é AUTO (quando há
   run física) → standby → nenhuma. Nenhum caminho devolve um nome de sessão
   que a sondagem não confirmou.

3. `send_ready` exige sessão viva **com o processo do agente**. Sessão viva só
   com shell abre o terminal (`terminal_ready`) para o operador diagnosticar,
   mas não autoriza `/send`.

4. Sondagem que não conclui (timeout do servidor tmux) não vira OFFLINE nem
   ONLINE: vira `determinate=False` e ERROR com `tmux_probe_timeout`. Isso
   preserva o achado de 29/set/2026 (tmux lento não pode apagar agente vivo da
   aba) sem reabrir a porta do ONLINE mentiroso.

5. Agentes headless/HTTP seguem a regra do próprio runtime. Nenhum requisito
   artificial de tmux.

6. `/send`, `/history`, o WebSocket, o lifecycle e o healthcheck consomem o
   mesmo resolvedor. O snapshot vira cache de observabilidade: carrega
   `send_ready`, `session_source` e `daemon_alive` para a UI, e `public_row`
   zera `send_ready` sempre que o agente não está ONLINE.

7. Divergência entre `/status` e `/send` é erro estruturado, não 503 opaco:
   `{code, message, health_reason, session_source, state}` — e o snapshot é
   reconciliado na hora (`reconcile_snapshot`, source `reconcile`, sem o
   debounce de duas amostras que só vale para o healthcheck).

8. Recuperação automática dispara pela **ausência da sessão**, não por
   `offline`, e revalida fisicamente antes de declarar ONLINE. `started=True`
   é intenção cumprida, não prova de agente no ar. Backoff após três falhas
   consecutivas (5 min), zerado no primeiro sucesso.

9. Sessão existente só com shell **não** é recriada automaticamente: destruir
   um painel que o operador pode estar usando para diagnosticar é pior que o
   ERROR explícito. Quem destrói casca é o start explícito.

10. O snapshot carrega `boot_id`. Um retrato saudável de outro boot descreve um
    sistema que não existe mais e é rejeitado (`snapshot_foreign_boot`), por
    mais recente que seja o `checked_at`.

## Consequências

- Sobreviventes de um stop incompleto, com a sessão viva e a CLI respondendo,
  passam a aparecer ONLINE com `daemon_alive=true` no payload em vez de ERROR.
  A sessão é a verdade sobre operabilidade; o PGID órfão continua visível, e o
  gate `survivors_pending` do start segue protegendo contra vazar memória.
- Cada `/send` e cada abertura de terminal custa uma sondagem tmux (duas
  chamadas). É o preço de não mentir; o `/status` continua servindo do
  snapshot, sem sondar.
- `terminal.ALLOWED_SESSIONS` passou a ser `agent_operability.CLI_SESSIONS`: o
  healthcheck não pode importar o router (puxaria a app FastAPI num oneshot).
- `agent_operability._tmux` delega a `agent_lifecycle._run` de propósito —
  é onde os testes de integração redirecionam o socket tmux.

## Invariantes (gates)

Qualquer mudança futura precisa manter, com teste:

- nenhum caminho determina `running=true`, ONLINE ou `send_ready=true` só a
  partir de PID, PGID, snapshot persistido ou daemon auxiliar;
- `/send` e `/status` derivam do mesmo resolvedor;
- `_live_session()` jamais devolve nome de sessão não comprovada;
- headless/HTTP não ganham requisito de tmux.

Cobertura em `apps/api/tests/test_agent_operability.py` (26 cenários).
