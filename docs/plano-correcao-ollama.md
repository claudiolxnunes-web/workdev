# Plano de correção — integração Ollama (revisão independente)

**Status: EM EXECUÇÃO em 2026-09-09 — ADR 005 aceito, as 3 migrações aplicadas
em produção, fatia 1 implementada (`f79add7`) e o achado 10 fechado após quatro
rodadas de rejeição do Codex (`9eacb8e`, `a557efb`, `9767b13`, `895565e`).
`895565e` está em produção desde 18:08 UTC, o que fecha o achado 11. Fatias 2 a 5
não começaram.**
Base: `f54c9b8` (develop). Commits revisados: `38c944d`, `5a8615a`, `bef40b8`,
`61d459c`, `20f0714`.

O objetivo original (PLAN → BUILD com revisão cruzada obrigatória) **não muda**.
A fatia 2 abaixo altera o *significado* de "runtime Ollama como executor" e por
isso estava condicionada a um ADR aprovado antes de qualquer código — condição
**satisfeita**: o ADR 005 foi aceito em 2026-09-09.

---

## 1. Verificação dos achados

Todos os sete achados foram confirmados lendo o código da base atual. Dois
achados adicionais apareceram na verificação.

| # | Sev | Achado | Evidência na base |
|---|---|---|---|
| 1 | crítico | Frontend nunca chama `POST /api/handoffs/runs/{id}/dispatch` | `apps/web/src/services/handoff.service.ts` não tem a rota (só `reviews`, `reviewer`, `transfer`, `context`, `subtasks`). `grep -rn dispatch apps/web/src` só acha o campo `dispatchable`. Run com executor Ollama nasce `queued` e fica parada — não existe sessão tmux para `local-code`/`gpu-*`, ao contrário dos agentes CLI |
| 2 | crítico | Não é executor de Build | `ollama_driver.dispatch()` faz `POST /api/generate` e devolve texto; o texto vira o evento `build.ollama_response` (`handoffs.py:1229`). Nenhum arquivo é editado, nenhum gate roda, nenhum commit é produzido. O `test_gate.execute_gate()` só é chamado no caminho AUTO do Gemini (`handoffs.py:407-455`) |
| 3 | alta | Ollama pode ser revisor sem fluxo de veredito | `SUPPORTED_AGENTS = CLI_AGENTS \| OLLAMA_AGENT_IDS` (`handoff.py:40`) e `validate_review_pair` só checa pertencimento (`handoff.py:136`). Na UI, o seletor de revisor usa a **mesma** lista `choices` do executor (`PlanningPanel.tsx:406-413`). O veredito só entra por `POST /runs/{id}/reviews`, que ninguém dispara para runtime Ollama. **Resolvido por restrição** — ver seção 2.1 |
| 4 | alta | `degraded` e runtime sem modelo aparecem despacháveis | `DISPATCHABLE_STATUSES = {online, degraded}` (`agent_runtimes.py:243`). Pior: se `WORKDEV_OLLAMA_*_MODEL` não estiver setada, `model_for()` devolve `None`, o teste de `degraded` é pulado e o runtime vira **`online`** (`agent_runtimes.py:356-375`); `ensure_dispatchable` passa, a run é criada, e só o `dispatch()` estoura `model_not_configured` (`ollama_driver.py:122`) |
| 5 | alta | Despacho sem lock nem idempotência | `dispatch_run_to_ollama` (`handoffs.py:1161`) lê a run, checa `status in {queued, running}` e chama o driver. Dois POSTs simultâneos passam os dois: duas inferências, dois eventos `build.ollama_response`, custo/GPU duplicados. Não há `FOR UPDATE`, token de idempotência nem estado `dispatching` |
| 6 | média | Rota segura a sessão DB por até 900 s | `DEFAULT_DISPATCH_TIMEOUT_SECONDS = 900.0` (`ollama_driver.py:26`) dentro de uma rota com `db: Session = Depends(get_db)`. A sessão só fecha no `finally` do generator. Agrava: a rota é `async def` mas faz I/O **síncrono** de SQLAlchemy (`_get_run`, `build_context`), bloqueando o event loop |
| 7 | média | Contexto vai para GPU remota sem classificação/redaction/consentimento | `build_context` monta ADRs, knowledge, decisions e plano (`handoff.py:925+`), `augment_prompt` anexa trechos, e o prompt sai igual para `local-code` (loopback) e para `gpu-hostinger`/`gpu-runpod` (internet, terceiros). Nenhuma etapa de classificação, redaction ou consentimento entre os dois |
| 8 | média | `agent_runtimes` router pendurado dentro de `terminal.py` | `terminal.py:737-739` inclui o router porque `apps/api/app/main.py` é `root:root 644` e não pôde ser editado pelo usuário `workdev`. É a pendência de ownership já registrada no `CLAUDE.md`, agora com efeito estrutural na árvore de rotas |
| 9 | baixa | `test_gate` é fixo em `/opt/workdev` | `WORKDIR = Path("/opt/workdev")` (`test_gate.py:28`). Qualquer execução isolada (worktree) exige parametrizar isso antes |
| 10 | alta | Gate de fatiamento aceita qualquer subtask como decomposição | `plan_granularity.py:91` faz `"decomposed": bool(subtasks)` e a linha 93, `"requires_decomposition": oversized and not subtasks`. **Uma** subtask antiga, única e sem relação com as fatias sugeridas satisfaz o gate. Não há checagem de quantidade, de correspondência com as fatias propostas, nem de gate próprio por fatia — exatamente o que `72b5360` prometia exigir. Achado da revisão independente do Codex em 2026-09-09 |
| 11 | ~~crítico~~ ✅ | ~~Release em produção está ~11 commits atrás~~ — **fechado em 2026-09-09** | Deploy às 18:08 UTC, prova `1a26f2f9-e37f-4782-bb40-1b405be49402`, actor `claudio`, promoveu `895565e`. Release verificada byte-idêntica ao repo em `plan_granularity.py` e `handoff.py`; `POST /runs/{id}/reviews` responde **401** (existe), não mais 405 |

Suíte atual passa: `45 passed` em `tests/test_ollama_dispatch.py` + `tests/test_agent_runtimes.py`.
Os testes existentes são honestos — eles testam o driver de texto, não um executor
de Build. O problema não é teste faltando, é o contrato estar menor do que a UI promete.

### Revisão independente do Codex — `rejected` (2026-09-09)

Run `8491f6db-9d83-4bba-9e38-b8a3c0ba39fe`, sobre os 11 commits da integração
Ollama. Veredito: **rejeitado**, com gates **verdes**:

| Gate | Resultado |
|---|---|
| Backend | 670 passed, 19 skipped, 20 subtests |
| Frontend | 61 passed |
| Build | passou |
| Lint | 4 erros **preexistentes**, fora do diff |

A distinção importa e é o resumo deste documento inteiro: **gate verde responde
"não quebrou"; revisão responde "faz o que promete"**. Os três motivos da rejeição
são de contrato, não de teste quebrado:

1. Runtime Ollama/GPU selecionável como revisor sem fluxo de despacho de revisão
   nem UI que consuma `submitRunReview` → **é o achado 3 deste plano**, confirmado
   de forma independente. Fechado pela fatia 1.
2. `plan_granularity.assess` aceita qualquer subtask como decomposição suficiente
   → **achado 10**, novo, não estava neste plano.
3. A própria task foi entregue com zero subtasks persistidas, apesar de o critério
   de aceite exigir fatiamento auditável.

O veredito **não pôde ser gravado na trilha oficial**: `workdev_agent.py verdict`
devolveu `HTTP 405` — ver achado 11. A rejeição existe como transcrição de sessão,
não como registro em `agent_run_reviews`.

**Situação em 2026-09-09, após o deploy das 18:08:** a rota existe em produção e o
bloqueio técnico acabou, mas `agent_run_reviews` continua com **zero linhas** para
esta run. As quatro rejeições seguem só como transcrição. Elas **não serão gravadas
retroativamente pelo executor** — quem assina veredito é o revisor, e o executor
escrever no lugar dele destruiria justamente a garantia que a revisão cruzada
existe para dar. O registro oficial nasce na próxima rodada, emitida pelo próprio
Codex.

---

## 2. Papéis: sugestão na UI, escolha sempre do operador

Decisão do Cláudio (2026-09-09), em duas partes:

1. Na prática, **revisor é sempre modelo de ponta** — `claude` (sessão `code`),
   `codex`, `gemini`, `kimi`.
2. Isso é **sugestão, não trava**: "sempre eu vou escolher o executor e revisor".
   O operador decide os dois papéis, manualmente, em todo envio.

O estado atual já respeita (2): `reviewer` é obrigatório no `BuildRequest`
(`schemas/handoff.py:141`) **inclusive no modo AUTO** — o roteador escolhe o
executor, nunca o revisor. O plano não mexe nisso; só não pode quebrar.

Para não repetir o erro que gerou este documento, é preciso separar duas coisas
que estavam misturadas no achado 3:

| | Natureza | Quem decide |
|---|---|---|
| **Quem *deve* revisar** | preferência de qualidade | Cláudio, por envio |
| **Quem *consegue* emitir veredito** | capacidade implementada | o código |

A primeira vira **camada de UI**: os agentes de ponta aparecem primeiro no
seletor de revisor, marcados como recomendados. Nada é escondido à força e não
há regra de backend proibindo por gosto.

A segunda continua sendo bloqueio real: hoje **não existe** caminho pelo qual um
runtime Ollama emita veredito. Escolhê-lo como revisor não produz uma revisão de
qualidade inferior — produz uma **run travada em `review` para sempre**, porque
ninguém dispara `POST /runs/{id}/reviews`. Isso é ausência de capacidade, não
preferência, e é o que a fatia 1 fecha.

Consequências no código:

- Constante explícita `AGENTS_WITH_REVIEW_CHANNEL` em `app/services/handoff.py`
  — nome descreve **capacidade**, não hierarquia de qualidade. Hoje = os 5
  agentes CLI (todos têm sessão tmux e a CLI `workdev_agent.py verdict`).
- `validate_review_pair()` recusa identidade fora dessa constante com código
  `reviewer_has_no_review_channel` e mensagem que diz a verdade: *"não há canal
  de veredito para este runtime; a run ficaria parada em review"*.
- Na UI, os agentes de ponta são **ordenados primeiro e marcados como
  recomendados** no seletor de revisor. Sem proibição por preferência.
- Se um dia você quiser Ollama revisando, o que falta é a **fatia opcional B**
  (seção 4) — não é uma regra a derrubar.

**Resolvido (Cláudio, 2026-09-09): `qwen` é executor.** Ele mantém sessão tmux e
canal de veredito, então continua tecnicamente elegível como revisor — o que muda é
o posicionamento na UI: aparece entre os executores, fora do destaque de revisor
recomendado. Não vira bloqueio de backend, porque não é ausência de capacidade.

E a regra que governa tudo isto, reafirmada pelo operador no mesmo dia:

> **Todas as decisões de papel são do Cláudio. Ele elege executor e revisor, sempre.**

Nenhum código infere, trava ou sobrescreve qualquer um dos dois papéis. "Recomendado"
é dica visual, nunca filtro: nada some do seletor por preferência. A única recusa que
o backend faz é por **capacidade ausente** — identidade sem canal de veredito
deixaria a run parada em `review` para sempre, o que é defeito, não gosto.

## 3. ADR necessário antes da fatia 3

`docs/adr/005-execucao-de-build-por-runtime-ollama.md`, status **`accepted`**
(aprovado pelo Cláudio em 2026-09-09).

Decisão registrada: um runtime Ollama **não é** um agente CLI com acesso a shell.
Ele produz uma *proposta estruturada de mudança*; quem aplica, testa e commita é um
worker da VPS, dentro de um worktree isolado. O modelo nunca executa comando, nunca
recebe credencial, nunca toca `develop`/`main`, nunca dispara deploy.

Enquanto o ADR estava `proposed`, os runtimes Ollama ficariam rotulados como
**assessor** (fatia 1), não executor. Com a aprovação, o rótulo de executor passa
a ser legítimo — mas só depois que a fatia 3 existir. Até lá o rótulo honesto da
fatia 1 continua valendo: prometer na UI o que o código não faz é justamente o
defeito que originou este documento.

---

## 4. Fatias

Cada fatia é uma unidade auditável: commit próprio, testes próprios, reversível
isoladamente. Ordem é dependência real.

### Fatia 1 — Honestidade de rótulo e portas fechadas ✅ IMPLEMENTADA (2026-09-09)
Fecha 3, 4, 10 e parte de 1. Nenhuma promessa nova na UI.

> **Entregue em `f79add7`.** Gates: API 680 passed / 19 skipped (era 670);
> frontend 64 passed (era 61); `tsc --noEmit` limpo; build com 0 ocorrências de
> `localhost:8000` no bundle. O achado 10 entrou junto por acoplamento na
> mensagem de erro de `approve_plan`. Sem migração — revertível por
> `git revert` isolado.

- `DISPATCHABLE_STATUSES = {STATUS_ONLINE}` — `degraded` deixa de ser despachável.
- `check_runtime()` passa a exigir modelo resolvido: sem `*_MODEL` e sem
  `default_model`, o estado é `unconfigured` (motivo: variável ausente), não `online`.
- `ensure_dispatchable()` resolve o modelo **antes** de liberar, para o erro
  aparecer no envio e não depois da run criada.
- `AGENTS_WITH_REVIEW_CHANNEL` explícito; `validate_review_pair()` recusa quem
  está fora com `reviewer_has_no_review_channel` e mensagem que explica o motivo
  técnico (run travaria em `review`), não preferência de qualidade.
- `PlanningPanel`: seletor de revisor **ordena os agentes de ponta primeiro**, com
  marca de recomendado; runtimes Ollama aparecem desabilitados com o motivo à
  vista ("sem canal de veredito"), em vez de sumirem sem explicação.
- Seletor de executor mantém os runtimes Ollama, mas o rótulo diz **"assessor
  (não edita arquivos)"** enquanto a fatia 3 não existir.

Sem migração. Reversível por `git revert`.

> **Corrigido após leitura do código:** a versão anterior deste plano previa
> validar a *saúde do revisor* no `POST /plans/{id}/build`. Está errado por dois
> motivos: `agent_runtime_snapshot()` é declaradamente consultivo e devolve
> `checked: False` quando não consegue sondar o tmux (`terminal.py:586-607`) — e
> o revisor só entra em cena horas depois, no fim da execução. Bloquear o envio
> porque a sessão do revisor está parada agora seria acoplamento indevido. Vira
> **aviso não-bloqueante na UI + evento na run**, nunca 409.

### Fatia 2 — Estado de despacho persistido, lock e idempotência
Fecha 5 e 6. Depende da fatia 1.

- Migração aditiva em `agent_runs`: `dispatch_state`
  (`idle|queued|dispatching|dispatched|failed`, default `idle`),
  `dispatch_attempts` int default 0, `last_dispatch_at`, `dispatch_token` uuid.
- Tabela nova `agent_build_jobs`: `id`, `run_id` FK, `runtime_id`, `state`,
  `attempt`, `prompt_sha256`, `created_at`, `started_at`, `finished_at`, `error`.
  Índice único parcial `(run_id) WHERE state IN ('queued','running')` — o banco,
  não a aplicação, garante um despacho ativo por run.
- Rota `POST /runs/{id}/dispatch` vira **202**: cria o job com
  `SELECT ... FOR UPDATE` na run, devolve `{job_id, dispatch_state}` e sai.
  Chamada concorrente devolve 409 `dispatch_already_active` com o `job_id` vivo.
- Rota nova `GET /runs/{id}/dispatch/{job_id}` para a UI acompanhar.
- A inferência sai da rota: vai para o worker da fatia 3. Sessão DB deixa de
  ficar aberta 900 s; a rota volta a ser `def` síncrona (coerente com o resto do
  router) ou `async` com repositório assíncrono — **não** o híbrido atual.

### Fatia 3 — Worker de build isolado (systemd)
Depende da fatia 2 e do ADR aprovado.

`workdev-build-worker.service`: `User=workdev`, `Group=workdev`,
`NoNewPrivileges=true`, `Restart=always`, unit **separada** de `workdev-api`
(deploy só reinicia a API; o worker precisa de entrada explícita no runbook).

Loop: `SELECT ... FOR UPDATE SKIP LOCKED` em `agent_build_jobs` → monta prompt →
`ollama_driver.dispatch()` → persiste envelope → aplica → gate → commit → `review`.

Isolamento da execução:

1. `git worktree add /opt/workdev-builds/<run_id> -b build/<run_id> <base_sha>` —
   a árvore de trabalho de `/opt/workdev` **não** é tocada.
2. O worktree não recebe `.env`, `venv/`, `/etc/workdev`, nem token de git.
3. O modelo devolve um **envelope JSON** validado por Pydantic:
   `{summary, files: [{path, action, content|diff}], checks: [...]}`.
   - `checks` só aceita nomes de um allowlist fixo (`pytest`, `vitest`, `lint`,
     `build`) — os mesmos do `test_gate`. O modelo **escolhe entre**, não escreve
     comando. Nada de shell arbitrário.
   - `path` recusado se: absoluto, contém `..`, casa `**/.env*`, `**/venv/**`,
     `.github/workflows/**`, `deploy.sh`, `scripts/*deploy*`, `alembic/versions/**`.
     Migração continua sendo decisão humana (regra do `CLAUDE.md`).
   - Envelope inválido → evento `build.envelope_rejected`, tentativa contabilizada,
     máximo `WORKDEV_OLLAMA_BUILD_MAX_ATTEMPTS` (default 3), depois `blocked`.
4. `git apply --check` antes de `git apply`. Falha → `build.patch_rejected`.
5. Gate no worktree: `test_gate.WORKDIR` vira parâmetro (achado 9). Evidência
   persistida com o SHA do worktree, reaproveitando `persist_gate_evidence`.
6. Gate PASS → commit em `build/<run_id>` (nunca push, nunca `develop`/`main`) →
   run para `review`. Gate FAIL → `blocked` com os checks reprovados.
7. O worker **nunca** roda `deploy.sh`, `systemctl` ou `alembic upgrade`.

Precondição de infra: `/opt/workdev-builds` criado `workdev:workdev`. Não resolver
via `chown -R /opt/workdev` (pendência de ownership do `CLAUDE.md` continua
separada, mas o achado 8 precisa ser destravado por você para editar `main.py`).

### Fatia 4 — Classificação, redaction e consentimento de egresso
Fecha 7. Independente da 3; pode entrar antes.

- Migração aditiva: `projects.context_classification`
  (`internal|restricted`, default `internal`).
- `local-code` = loopback, sem egresso: liberado por padrão.
- `gpu-hostinger` / `gpu-runpod` = egresso para terceiro. Exigem
  `WORKDEV_OLLAMA_ALLOW_REMOTE_CONTEXT=true` **e** um evento
  `build.egress_consent` registrado na run (quem consentiu, quando, qual runtime).
  Sem os dois: 409 `remote_egress_not_consented`.
- Projeto `restricted` nunca vai para runtime remoto — regra dura, sem flag.
- Passe de redaction sobre o prompt antes de qualquer runtime remoto: JWT,
  `sb_secret_*`/`sb_publishable_*`, `sk-*`, `ghp_*`/`github_pat_*`, `AKIA*`,
  URLs com credencial embutida, `postgres://user:pass@`, e-mail, CPF/CNPJ.
  Achado → substituído por `[REDACTED:<tipo>]` e contabilizado no evento.
- Log grava `prompt_sha256` e a contagem por tipo redigido — **nunca** o prompt.

### Fatia 5 — UI do ciclo completo
Depende de 2 (para os estados) e 3 (para o resultado).

- `PlanningPanel`: após "Enviar ao Build" com executor Ollama, dispara o despacho
  e mostra o estado (`despachando` / `aplicando patch` / `gate` / `em revisão`).
- `AgentsPage`: painel do runtime com job ativo, tentativas, último erro, botão
  "Repetir despacho" (desabilitado se offline ou se já houver job ativo) e link
  para o branch `build/<run_id>`.
- Estado de erro é explícito e acionável — nada de run silenciosamente parada em
  `queued`, que é o sintoma do achado 1.

### Fatia opcional B — Canal de veredito para runtime Ollama
**Não planejada para execução.** Fica registrada porque a restrição da fatia 1 é
de capacidade, não de regra: se um dia você quiser um runtime Ollama revisando,
é isto que falta — nada precisa ser "destravado".

- Job de revisão: o worker envia ao revisor o **diff do branch + evidência de
  gate**, não o repositório.
- Envelope de veredito: `{verdict: approved|rejected, feedback}`; `rejected`
  exige feedback não vazio (regra que já vale hoje).
- Entra por `record_review` com `reviewer_kind='ollama'` — mesma trilha
  append-only, mesma primazia do gate: **gate reprovado jamais vira aprovação**.
- Exigiria migração aditiva `agent_run_reviews.reviewer_kind`.
- Custo estimado: comparável à fatia 3. Só faz sentido se a prática mudar.

---

## 5. Migrações necessárias

Todas **aditivas**, com `downgrade()` funcional. Nenhum `DROP`, nenhuma reescrita
de dado.

**Aprovadas e APLICADAS em 2026-09-09** no Postgres de produção (container
`postgres` da VPS1, db `workdev`), pelo Cláudio via `alembic upgrade head`.

Estado verificado por consulta direta ao banco, não pela saída do comando:

| Verificação | Resultado |
|---|---|
| `alembic_version` | `d4a1c7e39b52` (head) |
| Colunas em `agent_runs` | `dispatch_state` NOT NULL default `idle`, `dispatch_attempts` NOT NULL default 0, `last_dispatch_at` nullable, `dispatch_token` uuid nullable |
| `agent_build_jobs` | criada, 13 colunas, 0 linhas |
| Índice único parcial | `uq_agent_build_jobs_active_run` sobre `(run_id) WHERE state IN ('queued','running')` — confirmado em `pg_indexes` |
| FK | `agent_build_jobs_run_id_fkey → agent_runs(id) ON DELETE CASCADE` |
| `projects.context_classification` | NOT NULL default `internal` |
| Dados preservados | `agent_runs` 57 linhas (todas `dispatch_state='idle'`), `projects` 19 (todas `internal'`) |
| API após a migração | `/health` 200; `GET /api/projects` autenticado 200 em 28 ms — sem restart, sem rota pendurada |

- Backup pré-migração:
  `/opt/backups/workdev/workdev-pre-ollama-20260909-1550.dump` (custom, 719 KB).
- Não houve validação em staging: o usuário `workdev_app` não tem `CREATEDB`.
  Mitigação aceita: DDL transacional, migrações aditivas, nenhum código
  consumindo as colunas ainda. **O `downgrade()` continua não exercitado** —
  está escrito e é simétrico, não foi rodado.

Rollback: `alembic downgrade a1c7e5b93f10`, ou um passo por vez com
`alembic downgrade -1`.

| Fatia | Migração | Conteúdo |
|---|---|---|
| 2 | `xxxx_add_dispatch_state_to_agent_runs` | 4 colunas em `agent_runs`, todas nullable ou com default |
| 2 | `xxxx_create_agent_build_jobs` | tabela nova + índice único parcial |
| 4 | `xxxx_add_context_classification` | 1 coluna em `projects`, default `internal` |

São **três**, não quatro: a migração `reviewer_kind` saiu junto com a fatia de
canal de veredito para Ollama (agora fatia opcional B, não planejada).

Cada uma roda isolada. Ordem = ordem das fatias. Rodar em staging local
(`DATABASE_URL` de teste) antes de qualquer coisa em produção.

Grafo: `agent_build_jobs` **não** é projetado no Engineering Graph nesta etapa —
os enums do Supabase não têm tipo compatível e criar um exigiria `ALTER TYPE`
(fora de escopo, e o `CLAUDE.md` já registra o custo disso). Eventos de despacho
continuam saindo como `AgentEvent`, que já existe.

---

## 6. Testes E2E — UI → despacho → execução → revisão

### Backend (pytest, `apps/api/tests/`)
- `test_dispatch_returns_202_and_persists_state` — a rota não bloqueia e o estado
  fica no banco.
- `test_concurrent_dispatch_creates_single_job` — N threads, 1 job, N-1 respostas
  409 (regressão direta do achado 5).
- `test_degraded_runtime_is_not_dispatchable` (achado 4).
- `test_runtime_without_model_reports_unconfigured` (achado 4, o caminho pior).
- `test_build_rejects_reviewer_without_review_channel` (achado 3, fatia 1) — e o
  par `test_reviewer_choice_is_never_overridden_by_auto`, garantindo que o
  roteador AUTO continua escolhendo só o executor.
- `test_envelope_rejects_path_traversal_env_and_workflows` — parametrizado por
  padrão proibido.
- `test_envelope_rejects_command_outside_allowlist`.
- `test_gate_runs_inside_worktree_not_in_opt_workdev` — assert no `cwd` usado.
- `test_worker_never_touches_develop` — `git rev-parse develop` antes/depois.
- `test_restricted_project_never_reaches_remote_runtime` (achado 7).
- `test_redaction_removes_all_known_secret_shapes` — parametrizado por tipo.
- `test_gate_failure_overrides_approved_verdict` — regressão da primazia do gate.

### Frontend (vitest)
- `PlanningPanel`: seletor de revisor lista os agentes de ponta primeiro e
  marcados como recomendados; runtime Ollama aparece **desabilitado com motivo
  visível**, não escondido. Executor Ollama mostra o rótulo de assessor.
- `PlanningPanel`: envio com executor Ollama exibe estado de despacho e não
  deixa a run em `queued` sem feedback visual.
- `AgentsPage`: "Repetir despacho" desabilitado com runtime offline ou job ativo.

### E2E real (`scripts/e2e_ollama_build.sh`, contra `local-code` na VPS1)
Roda contra a API local com `X-API-Key`, em projeto de teste, nunca em produção:

1. criar plano → `POST /plans/{id}/decompose` → aprovar
2. `POST /plans/{id}/build` com executor `local-code`, revisor `claude`
3. asserir `dispatch_state=queued` em ≤ 2 s (**a rota não pode demorar 900 s**)
4. aguardar o worker: job `running` → envelope → patch aplicado
5. asserir branch `build/<run_id>` existe e `develop` está no mesmo SHA de antes
6. asserir evidência de gate persistida com o SHA do worktree
7. asserir run em `review`, nunca em `completed` direto
8. veredito do revisor → `completed`
9. asserir: nenhum `deploy.sh` executado, nenhum push, nenhum `.env` no diff

Cada passo com timeout e saída não-zero em falha — script de monitoramento que
falha em silêncio não conta como verificação.

---

## 7. Critérios de aceite

Objetivos, verificáveis por comando. Um "não" reprova a fatia.

1. Nenhuma run com executor Ollama fica em `queued` sem job correspondente:
   `SELECT count(*) FROM agent_runs r LEFT JOIN agent_build_jobs j ON j.run_id=r.id
   WHERE r.agent IN ('local-code','gpu-hostinger','gpu-runpod') AND r.status='queued'
   AND j.id IS NULL` → **0**.
2. `POST /runs/{id}/dispatch` responde em **< 2 s** (p95, medido no E2E).
3. 20 POSTs simultâneos de despacho → exatamente **1** evento
   `build.ollama_response` e 1 linha em `agent_build_jobs`.
4. Runtime `degraded` ou sem `*_MODEL` → não aparece despachável na API nem na UI,
   e o envio devolve 409 **antes** de criar a run.
5. Um Build completo com `local-code` produz branch `build/<run_id>` com commit,
   evidência de gate e run em `review` — sem intervenção manual entre o envio e a
   revisão.
6. `git log develop..build/<run_id>` não vazio; `git log build/<run_id>..develop`
   vazio; `develop` inalterada.
7. Nenhum diff aceito toca `.env*`, `alembic/versions/`, `deploy.sh`,
   `.github/workflows/`.
8. Prompt enviado a runtime remoto passa por redaction: teste com secret plantada
   confirma `[REDACTED:*]` e ausência do valor original no payload.
9. Projeto `restricted` + runtime remoto → 409, sempre, sem flag que contorne.
10. `pnpm run build` em `apps/web` limpo e
    `grep -c "localhost:8000" apps/web/dist/assets/index-*.js` → **0**.
11. Suíte da API verde rodando como `workdev`
    (`WORKDEV_API_ENV_FILE=/tmp/test.env venv/bin/python -m pytest tests/ -q -p no:cacheprovider`).
12. Estado terminal `completed` continua inalcançável sem gate aprovado
    (regressão do contrato PLAN → BUILD).
13. **Escolha de papéis continua sua**: `reviewer` segue obrigatório no payload,
    inclusive em AUTO, e nenhum código passa a inferir revisor. Verificável por
    `test_reviewer_choice_is_never_overridden_by_auto`.
14. Nenhum revisor escolhido pode resultar em run parada: toda identidade
    aceita como revisor tem canal de veredito implementado.

---

## 8. Estratégia de rollback

**Flag mestre.** `WORKDEV_OLLAMA_BUILD_ENABLED` (default `false`). Todo o caminho
novo de execução fica atrás dela. Com a flag desligada, o sistema se comporta
exatamente como hoje, menos as portas fechadas da fatia 1 (que são restrição, não
funcionalidade nova — não precisam de rollback).

**Por camada:**

| Camada | Como reverter | Custo |
|---|---|---|
| Comportamento | `WORKDEV_OLLAMA_BUILD_ENABLED=false` em `/etc/workdev/workdev-api.env` + `systemctl restart workdev-api` | segundos |
| Execução | `systemctl stop workdev-build-worker` — a API segue de pé, runs param de avançar em vez de avançar errado | segundos |
| Código | cada fatia é um commit; `git revert <sha>` da fatia isolada | minutos |
| Deploy | `deploy.sh` já tem rollback automático se o postcheck falhar (ver `CLAUDE.md`) | automático |
| Banco | `alembic downgrade -1` por migração; todas aditivas, `downgrade()` testado antes de aplicar | minutos |
| Worktrees | `/opt/workdev-builds/<run_id>` é descartável: `git worktree remove --force` + `git branch -D build/<run_id>`. Nenhum estado de negócio mora lá | segundos |

**Ponto de atenção:** o `deploy.sh` só reinicia `workdev-api.service`. O
`workdev-build-worker` precisa de reinício explícito no runbook, senão fica
rodando código velho depois de um deploy — exatamente o tipo de descompasso
silencioso que já mordeu esta VPS antes. Isso entra como item de documentação
obrigatório da fatia 3, não como "a gente lembra".

**O que este plano não faz em nenhuma hipótese:** não aplica migração sem seu OK,
não roda deploy, não faz push, não mexe em `/root/.ssh`, não altera
`workdev-agents.service` (derrubaria todas as sessões tmux de uma vez).

---

## 9. Ordem sugerida e o que decidir agora

| Ordem | Fatia | Bloqueio |
|---|---|---|
| ~~1º~~ | ~~1 — rótulo, recomendação de revisor, portas fechadas~~ | ✅ feita em `f79add7`; achado 10 estabilizado em `895565e` após 4 rodadas |
| 2º | 4 — classificação e redaction | nenhum (independe do worker) |
| 3º | 2 — estado, lock, idempotência | migração precisa do seu OK |
| 4º | ADR 005 | sua aprovação |
| 5º | 3 — worker isolado | ADR + `main.py` destravado (achado 8) |
| 6º | 5 — UI do ciclo | fatias 2 e 3 |
| — | opcional B — canal de veredito Ollama | não planejada |

Decisões tomadas (2026-09-09):

1. ✅ **Ollama é executor real.** ADR 005 escrito em
   `docs/adr/005-execucao-de-build-por-runtime-ollama.md`, status `proposed` —
   aguardando sua aprovação. Fatias 3 e 5 mantidas no escopo.
2. ✅ **Migrações escritas, não aplicadas.** Os três arquivos estão em
   `apps/api/alembic/versions/`, encadeados a partir do head `a1c7e5b93f10`:
   `b2e8f4a17c30` → `c3f9a5b28d41` → `d4a1c7e39b52`. Cadeia validada com
   `alembic history` (head único, linear). **Nenhum `alembic upgrade` foi
   executado, em banco nenhum.**

3. ✅ **ADR 005 aprovado** pelo Cláudio em 2026-09-09. Status mudou de
   `proposed` para `accepted`. A fatia 3 está desbloqueada.
4. ✅ **Ownership de `apps/api/app/main.py` destravado** em 2026-09-09
   (`chown workdev:workdev`, arquivo isolado — não foi `chown -R`). O achado 8
   deixa de bloquear: o router `agent_runtimes` pode migrar de `terminal.py`
   para `main.py`. A pendência geral de ownership de `/opt/workdev` continua
   aberta no `CLAUDE.md` e não foi tocada.
5. ✅ **`qwen` é executor** (Cláudio, 2026-09-09) — ver seção 2.
6. ✅ **Migrações aprovadas** pelo Cláudio em 2026-09-09 para aplicação.

Pendências que continuam abertas:

7. **Medição do custo real de um Build completo em `local-code`.** Não bloqueia o
   ADR (já aceito); bloqueia ligar `WORKDEV_OLLAMA_BUILD_ENABLED=true`.
8. **`/opt/workdev-builds` ainda não existe** — precondição de infra da fatia 3,
   tem que nascer `workdev:workdev`.

## Histórico de revisão

- **2026-09-09, v1** — versão inicial após revisão independente dos 5 commits.
- **2026-09-09, v2** — decisão sobre revisores (modelos de ponta, como sugestão
  e não trava). Fatia de canal de veredito Ollama passa a opcional B; migrações
  caem de 4 para 3; validação de saúde do revisor no envio foi **retirada** por
  estar errada (ver nota na fatia 1).
- **2026-09-09, v3** — Ollama confirmado como executor real: ADR 005 escrito com
  status `proposed` e as 3 migrações escritas para revisão (não aplicadas).
  Nenhuma fatia de código implementada.
- **2026-09-09, v4** — ADR 005 aprovado (`accepted`); ownership de `main.py`
  destravado; `qwen` definido como executor; as 3 migrações **aplicadas** em
  produção (`alembic_version = d4a1c7e39b52`, verificado por consulta direta).
  Reafirmada como regra permanente a eleição manual de executor e revisor pelo
  operador. Continua sem nenhuma fatia de código implementada.
- **2026-09-09, v5** — primeira fatia de código em produção. `f79add7` entregou a
  fatia 1; o achado 10 exigiu quatro rodadas de rejeição do Codex até fechar
  (`9eacb8e` cobertura em vez de contagem, `a557efb` remoção do piso
  insatisfazível, `9767b13` identificador estável no título, `895565e` piso de
  duas fatias + compatibilidade com os 216 títulos legados). Deploy às 18:08 UTC
  (prova `1a26f2f9`, actor `claudio`) levou `895565e` para produção e **fechou o
  achado 11**: a rota de veredito responde de novo. Pendem: 5ª rodada de revisão
  sobre `895565e`, `agent_run_reviews` ainda vazia para a run `8491f6db`, e as
  fatias 2 a 5.
