# ADR 005 — Execução de Build por runtime Ollama via worker isolado

- Status: **proposed**
- Data: 2026-09-09
- Projeto: WorkDev Core
- Relacionado: [ADR 004](004-plan-build-handoff.md), `docs/plano-correcao-ollama.md`

## Contexto

Os commits `38c944d`, `5a8615a`, `bef40b8`, `61d459c` e `20f0714` integraram
runtimes Ollama (`local-code`, `gpu-hostinger`, `gpu-runpod`) ao WorkDev. A
revisão independente registrada em `docs/plano-correcao-ollama.md` constatou que
a integração entregue é um **canal de texto**, não um executor de Build:

- `ollama_driver.dispatch()` faz `POST /api/generate` e devolve texto; o texto
  vira o evento `build.ollama_response`.
- Nenhum arquivo é editado, nenhum teste roda, nenhum commit é produzido.
- `test_gate.execute_gate()` só é chamado no caminho AUTO do Gemini.
- Não existe sessão tmux para essas identidades, ao contrário dos agentes CLI.
  A run nasce `queued` e nunca sai de lá.

Mesmo assim a UI oferece essas identidades no seletor de **executor**, ao lado de
`codex` e `claude`, que de fato editam arquivos. O contrato prometido pela
interface é maior que o implementado — e o ADR 004 estabelece que BUILD "executa
no ambiente real e registra início, progresso, bloqueio, revisão e conclusão".

A alternativa de simplesmente dar shell ao modelo (como os agentes CLI têm) foi
descartada: os runtimes Ollama incluem GPUs de terceiros, efêmeras e de
disponibilidade incerta, que não podem receber repositório nem credencial.

## Decisão

Um runtime Ollama **não é** um agente CLI com acesso a shell. Ele é uma fonte de
**propostas estruturadas de mudança**. Quem aplica, testa e commita é um worker
da VPS principal, em ambiente isolado.

### Fronteira

O modelo:

- recebe **texto** (prompt de Build + trechos recuperados por `build_rag`);
- devolve um **envelope JSON validado por Pydantic**:
  `{summary, files: [{path, action, content|diff}], checks: [...]}`;
- **nunca** executa comando, recebe credencial, vê o repositório, toca
  `develop`/`main` ou dispara deploy.

O worker (`workdev-build-worker.service`, `User=workdev`,
`NoNewPrivileges=true`, unit separada de `workdev-api`):

1. cria `git worktree add /opt/workdev-builds/<run_id> -b build/<run_id>` — a
   árvore de `/opt/workdev` não é tocada;
2. o worktree não recebe `.env`, `venv/`, `/etc/workdev`, nem token de git;
3. valida o envelope e **recusa** `path` absoluto, com `..`, ou casando
   `**/.env*`, `**/venv/**`, `.github/workflows/**`, `deploy.sh`,
   `scripts/*deploy*`, `alembic/versions/**`;
4. `git apply --check` antes de `git apply`;
5. roda o gate **dentro do worktree** (`test_gate.WORKDIR` passa a ser
   parâmetro);
6. gate PASS → commit em `build/<run_id>`, sem push, e run para `review`;
   gate FAIL → `blocked` com os checks reprovados;
7. nunca roda `deploy.sh`, `systemctl` ou `alembic upgrade`.

### Comandos são escolha, não texto livre

`checks` aceita apenas nomes de um allowlist fixo (`pytest`, `vitest`, `lint`,
`build`) — os mesmos do `test_gate`. O modelo **escolhe entre** comandos
pré-definidos; não escreve comando. Não há caminho pelo qual texto gerado vire
shell.

### Papéis

Executor ⊇ revisor, nunca o contrário. Runtime Ollama pode **executar**; a
revisão exige canal de veredito implementado, que hoje só os agentes CLI têm
(decisão do operador em 2026-09-09: revisores são modelos de ponta, como
sugestão da UI — a escolha dos dois papéis permanece manual e humana em todo
envio).

## Consequências

**Positivas**

- O achado crítico "não é executor de Build" é resolvido por arquitetura, não
  por rótulo.
- GPU de terceiro nunca recebe repositório nem credencial — continua sendo
  capacidade de inferência descartável, coerente com `bef40b8`.
- O contrato PLAN → BUILD do ADR 004 é preservado: `completed` continua
  inalcançável sem gate aprovado e sem revisão independente.
- Falha de build fica contida em um branch descartável.

**Negativas / custos**

- Superfície nova: worker, envelope, worktrees, 2 migrações.
- Inferência em CPU é lenta (171 s medidos para uma pergunta de uma linha na
  VPS1, `20f0714`); um Build real será bem mais caro. A qualidade do envelope de
  um modelo 14B quantizado é incógnita até haver medição.
- `workdev-build-worker` não é reiniciado por `deploy.sh` (que só toca
  `workdev-api.service`): exige item explícito no runbook, sob pena de rodar
  código velho após deploy.
- Depende de destravar o ownership `root:root` de `apps/api/app/main.py`.

**Riscos aceitos**

- O modelo pode produzir envelopes inválidos repetidamente; mitigado por limite
  de tentativas (`WORKDEV_OLLAMA_BUILD_MAX_ATTEMPTS`, default 3) e transição
  para `blocked`.
- Patch sintaticamente válido e semanticamente ruim passa o `git apply` e é
  barrado pelo gate — que é exatamente o papel dele.

## Alternativas descartadas

1. **Dar shell ao runtime Ollama, como aos agentes CLI.** Exigiria repositório e
   credencial em GPU de terceiro, efêmera. Descartada por segurança.
2. **Manter como assessor (só texto).** Honesto, mas não entrega execução — e a
   UI teria que parar de oferecer a identidade como executor.
3. **Executar o patch na árvore de `/opt/workdev`.** Descartada: build falho
   contaminaria a árvore de trabalho e a release servida em produção.

## Reversão

Tudo atrás de `WORKDEV_OLLAMA_BUILD_ENABLED` (default `false`).
`systemctl stop workdev-build-worker` para a execução sem afetar a API. As
migrações são aditivas com `downgrade()` funcional. Worktrees são descartáveis.

## Pendente para aceitar este ADR

- [ ] Aprovação do Cláudio
- [ ] Destravar ownership de `apps/api/app/main.py`
- [ ] Medição do custo real de um Build completo em `local-code`
