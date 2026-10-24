# TerminalSession e TerminalSessionManager

Execução: `636fdbbc-d52b-45e4-8025-c9405313980c`  
Task: `95193b18-32b9-4b65-aa58-9b7de5e4b3e6`  
Plano: v3 — revisor independente Kimi.

## Implementação

`TerminalSession` registra a identidade do terminal: run_id único, PID do supervisor e do processo PTY, identidade Linux (boot_id + starttime), caminho do PTY/socket, diretório, estado, exit_code e timestamps. A FK RESTRICT impede remover o Run e perder o controle do terminal. O relacionamento ORM é um-para-um.

`TerminalSessionManager` oferece `create`, `health`, `reattach`, `write`, `close` e alias `stop`. Use uma Session SQLAlchemy dedicada: cada operação gerencia sua transação. `create` bloqueia a linha do Run e persiste intenção antes de iniciar o supervisor. Chamadas repetidas devolvem a mesma sessão, inclusive quando encerrada; não há recriação silenciosa.

Um processo Python separado mantém o master PTY e um socket Unix privado. Não há tmux ou dependência nova. `pty.fork` cria o terminal controlador e o grupo da shell. O supervisor drena a saída, mantém os últimos 64 KiB para reattach e limita o protocolo de controle. Ele usa subreaper Linux para recolher filhos órfãos; no close envia TERM/KILL ao grupo e usa pidfds para filhos adotados, inclusive os que chamaram setsid. `waitpid` recolhe os processos. Se a limpeza não terminar, registra ERROR.

O supervisor recebe ambiente mínimo, sem repassar variáveis de credenciais do backend. O diretório padrão `/tmp/workdev-terminals` deve pertencer ao usuário do runtime e ter modo 0700; pode ser configurado por `WORKDEV_TERMINAL_DIR`. A API não sinaliza PIDs sem um supervisor verificável. Resultado de encerramento é gravado atomicamente em JSON privado e reconciliado pelo health, sem loop de healthcheck adicional.

## Persistência e limites

Recriar o manager ou conectar por outro processo cliente preserva PID e PTY. O supervisor é o dono real do descritor; guardar apenas um número de FD no banco não permitiria reattach.

Esta camada não modifica os endpoints tmux existentes nem instala um serviço systemd. Parar o cgroup que contém o supervisor ou reiniciar o host encerra os processos: `start_new_session` isola sessão/process group, não cgroup. Portanto esta entrega não promete sobrevivência a `systemctl restart` do serviço que a hospedar. Após perda do runtime, health reflete ERROR e não sinaliza um PID possivelmente reutilizado. Supervisores vivos precisam ser encerrados pelo manager antes de remover seus registros/artefatos. Os JSONs finais preservam a evidência de encerramento; a saída de 64 KiB não é um transcript durável.

Linux VPS1, com `/proc`, PTYs e pidfds, é o alvo. O processo roda com o mesmo usuário do runtime; não é um sandbox de código não confiável.

## Migration aplicada

Revisão `6a8e139c204f`, após `d4a1c7e39b52`. Aplicada com Alembic no banco PostgreSQL `workdev`; revisão e 13 colunas conferidas por consulta direta. Migration aditiva: apenas a nova tabela, FK, unicidade e check de estados.

Antes da aplicação foram validados upgrade, persistência de run_id, downgrade e re-upgrade em schema PostgreSQL isolado, revertido ao fim. Backup do schema anterior: `/tmp/workdev-schema-before-636fdbbc.sql` (34.402 bytes, modo 0600). Não é backup de dados. Não foi executado rollback na tabela de produção.

## Validações

Nove testes em `apps/api/tests/test_terminal_sessions.py` usam PTYs e processos reais com persistência SQLite isolada: create idempotente, reattach em novo manager/processo, escrita, saída natural/exit_code, SIGKILL, TERM ignorado, descendentes com setsid, ausência de zumbis após close, FK/unicidade e recusa de sinalizar PID não verificado.

A validação da migration usa PostgreSQL real, conforme descrito acima. O gate final do commit será registrado nos eventos da execução, incluindo testes completos e build do frontend. A aprovação final pertence exclusivamente ao Kimi.

Nenhum push, deploy ou reinício dos serviços foi executado nesta implementação. As quatro subtasks foram atualizadas conforme as validações concluíram.
