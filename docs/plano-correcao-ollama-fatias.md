# Fatiamento executável — pendências da integração Ollama

Complemento de `docs/plano-correcao-ollama.md`. Aqui as pendências viram
**unidades auditáveis** no formato que o próprio gate do WorkDev cobra
(`plan_granularity.assess`): objetivo único, escopo limitado, gate próprio,
revisão independente antes de seguir para a seguinte.

Motivo de existir: as "fatias 3, 4 e 5" do plano original são grandes demais
para serem unidades auditáveis. A fatia 3, do jeito que estava escrita (worker +
envelope + worktree + gate parametrizável + systemd numa tacada), é exatamente o
monólito que o achado 10 mostrou que o gate precisa barrar. Aplicar a régra a si
mesmo é o mínimo.

## Estado verificado em 2026-09-10

Confirmado por comando, não por leitura de documento:

| Item | Estado |
|---|---|
| Migrações `b2e8f4a17c30` → `c3f9a5b28d41` → `d4a1c7e39b52` | **aplicadas** (`alembic current` = `d4a1c7e39b52 (head)`) |
| ADR 005 | **accepted** |
| Fatia 1 (rótulo, portas fechadas) | feita (`f79add7`) |
| Fatia 2 (estado, lock, idempotência) | feita (`30a2d07`) — `build_jobs.py`, `with_for_update()`, índice parcial, rota 202, `GET .../dispatch/{job_id}` |
| Achado 1 (botão de despacho) | feito (`7a760a7`) |
| Achado 10 (gate de fatiamento) | fechado (`895565e`) |
| Achado 11 (release atrasada) | fechado |
| `test_gate.WORKDIR` | **ainda fixo** em `/opt/workdev` (`test_gate.py:28`) |
| Envelope / worktree / worker | **não existem** |
| `workdev-build-worker.service` | **não existe** (unit não registrada) |
| `WORKDEV_OLLAMA_BUILD_ENABLED` | **não existe** no código |
| Consumidor da fila | **provisório**, in-process, declarado como tal em `30a2d07` |

Ou seja: o encanamento está pronto e honesto; a execução real (achado 2, o
crítico) não começou.

> ⚠️ O cabeçalho de `plano-correcao-ollama.md` diz "Fatias 2 a 5 não começaram".
> Está desatualizado — a fatia 2 está em `30a2d07`. Corrigir é a unidade 0a.

---

## Escopo (enumerado para render fatias distintas no gate)

1. Corrigir o cabeçalho do plano para o estado verificado por comando
2. Revisão independente dos 8 commits posteriores a `895565e`
3. Parametrizar o diretório de trabalho do gate de testes
4. Contrato e validação do envelope de mudança, sem aplicar nada
5. Worktree efêmero por run, criar e descartar, sem aplicar patch
6. Aplicação do patch no worktree e execução do gate isolado
7. Commit no branch de build e transição de estado da run
8. Worker systemd definitivo substituindo o consumidor provisório
9. Classificação de contexto e bloqueio de projeto restrito
10. Redaction do prompt antes de egresso remoto
11. Consentimento explícito de egresso por run
12. Estado do ciclo de Build no PlanningPanel
13. Painel de job e repetição de despacho no AgentsPage

---

## Unidades

Cada uma: reversível por `git revert` isolado, com gate próprio. Nenhuma depende
de fatia posterior.

### 0a — Cabeçalho do plano com o estado verificado
**Depende de:** nada. **Tamanho:** mínimo.

Corrigir `plano-correcao-ollama.md` para refletir `30a2d07` e `7a760a7`, e
registrar que o consumidor da fila é provisório.

**Aceite:** o cabeçalho cita fatia 2 como feita, aponta o commit, e nenhum
comando de verificação da tabela de estado contradiz o texto.

### 0b — Revisão independente dos 8 commits novos
**Depende de:** nada. **Tamanho:** médio.

Revisar `8fba6e7`, `30a2d07`, `7a760a7`, `af2d334`, `7e67627`, `af33f42` e os
demais posteriores a `895565e`, no mesmo padrão da revisão original: ler o
código, não o commit message.

**Aceite:** achados numerados com evidência `arquivo:linha`, veredito registrado
em `agent_run_reviews` pelo revisor (não pelo executor), e gates rodados.

### 3a — `test_gate` parametrizável por diretório
**Depende de:** nada. **Tamanho:** pequeno. **Fecha:** achado 9.

`WORKDIR` deixa de ser constante de módulo e vira parâmetro de `execute_gate` e
dos `_check_*`, com **default preservando `/opt/workdev`**. Puramente
preparatória: nenhum comportamento novo.

**Aceite:**
- `execute_gate(run, workdir=tmp)` roda os checks em `tmp`, provado por assert no
  `cwd` do `subprocess.run`;
- chamada sem o parâmetro continua idêntica à de hoje;
- suíte da API verde (hoje: 703 passed, 19 skipped).

### 3b — Contrato e validação do envelope, sem executar nada
**Depende de:** nada (paralelizável com 3a). **Tamanho:** médio.

Modelo Pydantic `BuildEnvelope` (`summary`, `files[]`, `checks[]`), parser
tolerante para extrair o JSON de uma resposta em texto, e as recusas: `path`
absoluto, com `..`, ou casando `**/.env*`, `**/venv/**`, `.github/workflows/**`,
`deploy.sh`, `scripts/*deploy*`, `alembic/versions/**`. `checks` restrito ao
allowlist fixo (`pytest`, `vitest`, `lint`, `build`).

Nada é aplicado nesta unidade — é só o contrato e sua validação.

**Aceite:**
- teste parametrizado recusa **cada** padrão proibido individualmente;
- `checks` fora do allowlist recusado;
- envelope válido produz objeto tipado;
- resposta do modelo sem JSON vira erro de domínio, não exceção crua.

### 3c — Worktree efêmero por run
**Depende de:** nada. **Tamanho:** médio.

`git worktree add /opt/workdev-builds/<run_id> -b build/<run_id>`, remoção e
garantia de limpeza em falha. O worktree não recebe `.env`, `venv/`,
`/etc/workdev` nem credencial de git.

**Aceite:**
- worktree criado e removido; `git worktree list` limpo ao final;
- falha simulada no meio não deixa diretório nem branch órfão;
- `develop` no mesmo SHA antes e depois;
- assert de ausência de `.env` e credencial dentro do worktree.

### 3d — Aplicar patch no worktree e rodar o gate
**Depende de:** 3a, 3b, 3c. **Tamanho:** médio.

`git apply --check` antes de `git apply`; gate roda **dentro do worktree**
(usando 3a); evidência persistida com o SHA do worktree.

**Aceite:**
- patch válido aplicado e gate executado com `cwd` do worktree — nunca
  `/opt/workdev`;
- patch inválido vira evento `build.patch_rejected` sem sujar nada;
- evidência de gate gravada com o SHA correto.

### 3e — Commit no branch e transição da run
**Depende de:** 3d. **Tamanho:** pequeno.

Gate PASS → commit em `build/<run_id>`, **sem push**, run para `review`.
Gate FAIL → `blocked` com os checks reprovados.

**Aceite:**
- `git log develop..build/<run_id>` não vazio;
- `git log build/<run_id>..develop` vazio;
- nenhum push executado (assert no comando);
- run em `review`, nunca `completed` direto;
- gate FAIL leva a `blocked`, não a `review`.

### 3f — Worker systemd definitivo
**Depende de:** 3d, 3e. **Tamanho:** médio. **Fecha:** achado 2 (crítico).

`workdev-build-worker.service` (`User=workdev`, `NoNewPrivileges=true`, unit
separada de `workdev-api`), consumo com `SELECT ... FOR UPDATE SKIP LOCKED`,
limite `WORKDEV_OLLAMA_BUILD_MAX_ATTEMPTS` (default 3), tudo atrás de
`WORKDEV_OLLAMA_BUILD_ENABLED` (default `false`).

> **Corrigido em 2026-09-10:** aqui dizia que 3f **remove** o consumidor
> in-process provisório da fatia 2. Removê-lo deixaria o despacho sem executor
> nenhum, porque a unit do worker não está instalada — a UI aceitaria o clique e
> nada aconteceria. O consumidor passa a ser **condicionado** a
> `build_enabled()`: flag ligada, ele sai de cena e o worker assume; desligada,
> continua sendo o executor. Ele sai de vez quando a unit estiver de pé, não
> antes. Se um agente futuro ler a versão antiga e "consertar" removendo, quebra
> o despacho.

**Aceite:**
- unit ativa e job consumido fora do ciclo da requisição;
- flag `false` → comportamento idêntico ao de hoje;
- dois workers simultâneos não pegam o mesmo job (`SKIP LOCKED`);
- limite de tentativas leva a `blocked`, não a loop;
- **runbook atualizado** com o reinício pós-deploy (o `deploy.sh` só toca
  `workdev-api.service`);
- nenhum `deploy.sh`, `systemctl` ou `alembic upgrade` no caminho do worker.

### 4a — Classificação de contexto e bloqueio de projeto restrito
**Depende de:** nada. **Tamanho:** pequeno. A coluna já existe (`d4a1c7e39b52`).

Expor e usar `projects.context_classification`. `restricted` nunca vai para
runtime remoto — regra dura, sem flag.

**Aceite:** projeto `restricted` + runtime remoto → 409, sempre; `local-code`
(loopback) não é afetado.

### 4b — Redaction do prompt antes de egresso remoto
**Depende de:** nada. **Tamanho:** médio.

Passe sobre o prompt para runtime remoto: JWT, `sb_secret_*`, `sb_publishable_*`,
`sk-*`, `ghp_*`, `github_pat_*`, `AKIA*`, URL com credencial embutida,
`postgres://user:pass@`, e-mail, CPF/CNPJ → `[REDACTED:<tipo>]`.

**Aceite:** teste parametrizado por tipo, com secret plantada, confirma
`[REDACTED:*]` e **ausência do valor original** no payload; log grava
`prompt_sha256` e contagem por tipo, nunca o prompt.

### 4c — Consentimento de egresso por run
**Depende de:** 4a. **Tamanho:** pequeno.

`gpu-hostinger`/`gpu-runpod` exigem `WORKDEV_OLLAMA_ALLOW_REMOTE_CONTEXT=true`
**e** evento `build.egress_consent` na run. Sem os dois: 409
`remote_egress_not_consented`.

**Aceite:** sem consentimento → 409; com consentimento → evento auditável com
quem, quando e qual runtime.

### 5a — Estado do ciclo no PlanningPanel
**Depende de:** 3f. **Tamanho:** pequeno.

Após o envio, mostrar `despachando` → `aplicando patch` → `gate` → `em revisão`.

**Aceite:** vitest cobre cada estado; nenhuma run fica sem feedback visual.

### 5b — Painel de job no AgentsPage
**Depende de:** 3f. **Tamanho:** pequeno.

Job ativo, tentativas, último erro, "Repetir despacho" (desabilitado se offline
ou com job ativo) e link para `build/<run_id>`.

**Aceite:** vitest cobre botão desabilitado nos dois casos; erro é acionável.

---

## Ordem sugerida

Paralelizáveis desde já, sem dependência: **0a, 0b, 3a, 3b, 3c, 4a, 4b**.

```
0a ─┐
0b ─┘ (housekeeping, independentes)

3a ─┐
3b ─┼─→ 3d ─→ 3e ─→ 3f ─→ 5a, 5b
3c ─┘

4a ─→ 4c
4b (independente)
```

Caminho crítico até fechar o achado 2: **3a → 3b → 3c → 3d → 3e → 3f**.

## Verificação de que este fatiamento passa no próprio gate

O escopo acima enumera **13 frentes distintas**, acima do piso
`MIN_SLICES_WHEN_OVERSIZED = 2`. Cada frente tem uma unidade correspondente com
título próprio, então `covered_slices` alcança `required_slices` quando as
subtasks forem materializadas por `POST /plans/{id}/decompose` — sem precisar de
`force=true`.

Nenhuma unidade acumula duas frentes: 3a não mexe em envelope, 3b não toca em
git, 3c não aplica patch, 3e não cria worker. Quando uma falhar, dá para saber
qual.
