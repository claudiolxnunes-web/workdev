# Task 7 — Fase 0: Discovery da implementação terminal (read-only)

Data: 2026-09-13. Base: branch `task/9de8d5de-run-reconnect` (commit `9bd4fb8`,
contém Tasks 4–6 já commitadas). Documento produzido sem alterar código.

## 1. Rota WebSocket do Run Terminal

- Arquivo: `apps/api/app/routers/run_terminal.py`
- Símbolo: `run_terminal_ws(websocket: WebSocket, run_id: str)` — handler de
  `/ws/runs/{run_id}/terminal`. Autentica via `websocket_is_authenticated`,
  resolve/cria TerminalSession (`_create` ou `_health` quando `?existing=1`),
  faz attach (`_attach`) e dispara `_stream_output`.
- Símbolo: `_stream_output(websocket, conn, pending)` — loop de output PTY → WS
  (fecha 1000 no EOF do worker).
- REST no mesmo router: `create_run_terminal` (POST), `run_terminal_state` (GET),
  `reconnect_run_terminal` (POST), `close_run_terminal` (DELETE).
- Registro: `apps/api/app/main.py` linha 80, `app.include_router(run_terminal_router)`.

## 2. Autenticação

- Arquivo: `apps/api/app/auth.py`
- Símbolo: `websocket_is_authenticated(websocket)` — valida cookie
  `workdev_session` (HMAC-SHA256 em `validate_session_token`, TTL
  `WORKDEV_SESSION_TTL_SECONDS`, default 43200 s). Usada pelo handler WS.
- Símbolo: `request_is_authenticated(request)` — cookie OU header
  `X-API-Key` comparado com `hmac.compare_digest`. Usada pelo middleware
  `require_api_key` em `app/main.py` (linhas 40–45), que protege todo
  `/api/*` exceto `/api/auth/login`. Cobre os endpoints REST do terminal.
- Lacuna: WS aceita só cookie; clients não-browser sem cookie não passam.
  Resto preservado — Fase 1 só reforça/testa o mecanismo existente.

## 3. TerminalSession — 13 colunas

- Arquivo: `apps/api/app/models/terminal_session.py`
- Classe: `TerminalSession(Base)`, tabela `terminal_sessions`
- Colunas (13): `id, run_id (FK agent_runs, unique, RESTRICT), state
  (CHECK IN STARTING/RUNNING/STOPPING/CLOSED/ERROR), supervisor_pid, pid,
  process_identity, pty_path, socket_path, cwd, exit_code, error,
  created_at, closed_at`. `run` = relationship.

## 4. TerminalSessionManager

- Arquivo: `apps/api/app/services/terminal_sessions.py`
- Classe: `TerminalSessionManager` — `create/health/snapshot/reattach/write/
  resize/attach/close/stop`, helpers `_session`, `_request` (socket Unix,
  JSON por linha), `_apply`.
- Erro: `TerminalSessionError(RuntimeError)`.
- Diretório: `WORKDEV_TERMINAL_DIR` (default `/tmp/workdev-terminals`, modo
  0700, verificação de ownership no `__init__`).

## 5. Worker PTY

- Arquivo: `apps/api/app/services/terminal_worker.py`
- Função: `main()` — único dono do PTY; socket Unix com ops
  `close/write/resize/health/attach`; buffer circular de 64 KiB; cleanup por
  `killpg` + pidfd em SIGTERM→SIGKILL; resultado final em
  `{session_id}.json`; remove o socket ao terminar.
- Função: `identity(pid)` — fingerprint `boot_id:starttime` via `/proc`.

## 6. Rastreamento de atividade

- Lacuna explícita: não existe `last_activity` nem timeout. O worker mede só
  o loop de output. Reaper (Fase 4) precisará introduzir timestamp de
  atividade no worker (output + ops write/resize/attach renovam), com
  timeout configurável por `WORKDEV_TERMINAL_IDLE_TIMEOUT_SECONDS`.

## 7. Logging / redaction

- Lacuna explícita: nenhum `logging` em `run_terminal.py`,
  `terminal_sessions.py`, `terminal_worker.py`. `logger` só existe em
  `app/routers/handoffs.py`, `app/services/incident_parser.py`,
  `app/services/engineering_graph.py`. Redaction (Fase 5) introduz logger
  `workdev.terminal` com eventos de ciclo de vida (metadata: run/session/pid,
  role, motivo) — nunca stdin/stdout nem buffers.

## 8. Testes existentes (baseline não quebrar)

- `apps/api/tests/test_terminal.py` — 40 testes (manager/worker, permissões).
- `apps/api/tests/test_terminal_sessions.py` — 9 testes.
- `apps/api/tests/test_terminal_transcript.py` — 3 testes.
- `apps/api/tests/test_run_terminal.py` — 13 testes REST/WS (fixture
  `api_terminal` SQLite).
- `apps/api/tests/test_run_terminal_browser.py` — 1 E2E Playwright opt-in
  (`PLAYWRIGHT_E2E=1`).
- Frontend relevante: `apps/web/src/modules/agents/RunTerminal.tsx`,
  `RunTerminalPage.tsx`, teste `RunTerminal.test.tsx`.

## Decisões A VALIDAR NO CÓDIGO → resolvidas

- Papel writer/observer: query param `role=observer` (default writer,
  retrocompatível). Exclusividade/limite por registro in-process no router
  (produção roda uvicorn single-process).
- Takeover: `role=writer&takeover=1` derruba writer atual (close 1000) e
  assume; observers nunca recebem escrita.
- Protocolo WS: somente aditivo — campo `role` na mensagem `status` e novo
  parâmetro de query. `type=input/resize` continuam idênticos; observers os
  têm ignorados.
- Idle: worker fecha por inatividade (output/ops) e escreve resultado
  CLOSED; API `create()` purga linha CLOSED/ERROR para permitir nova sessão.
- Logs: eventos de metadata apenas; sem payloads de terminal.
