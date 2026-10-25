# Deploy Canônico do WorkDev

Fonte canônica para TODOS os agentes.

## Regra

NUNCA improvisar o processo de deploy.
NUNCA executar `deploy.sh` sem `proof_id`.
NUNCA gerar prova manualmente com `deploy_proof.py`.
NUNCA redescobrir o fluxo procurando scripts, salvo se este runbook estiver comprovadamente desatualizado.

## Fluxo oficial

> ⚠️ **Sempre o caminho instalado, `/usr/local/sbin/workdev-deployctl`** (root:root 755).
> Nunca `sh scripts/deploy/workdev-deployctl` do repositório: o checkout é do usuário
> `workdev`, que pode alterar aquele arquivo — rodá-lo como root entregaria root a quem
> controla o `workdev` (agentes inclusos). O `deploy.sh` já faz essa checagem de dono.
> A cópia do repo é só a fonte versionada que `install-manifest.txt` instala.

### 1. Prepare

```bash
/usr/local/sbin/workdev-deployctl prepare
```

- Precisa rodar como `root` (o wrapper delega internamente pro usuário `workdev-deploy`).
- Primeiro roda o gate de pre-deploy (`workdev-predeploy-gate`), que executa `verificar-deploy.sh --testes` **como usuário `workdev`** (não root!), validando: git limpo, escopo dos arquivos alterados, segredos versionados, sintaxe Python/shell, build do frontend, porta 8000 e a suíte de testes inteira.
- Se o gate passar, empacota via `git archive HEAD` (**só o que estiver commitado** — mudanças salvas no disco mas não commitadas nunca entram) + o build do frontend, e cria uma release imutável em `/opt/workdev-runtime/releases/<uuid>`.
- Imprime um `proof_id`, válido por 900s (15 min) por padrão.

### 2. Approve

```bash
/usr/local/sbin/workdev-deployctl approve <proof_id> --actor "<seu nome>"
```

Esse é o ponto de aprovação humana explícita do pipeline — quem roda assume a responsabilidade pelo deploy.

### 3. Deploy

```bash
bash /opt/workdev/deploy.sh <proof_id>
```

(Equivale a `/usr/local/sbin/workdev-deployctl deploy <proof_id>`, mas antes confere que o controlador instalado é `root:root 755`.)

Promove a release preparada pra `current` (symlink atômico), reinicia `workdev-api.service`, roda checagem pós-deploy, e faz rollback automático (volta pra release anterior + reinicia) se algo falhar.

## Atalhos práticos `wd-*` — forma preferida de operar (decisão do operador, 2026-10-25)

O operador quer deployar **sempre por este caminho**: o agente (como `workdev`) faz tudo que
não exige root, e o operador roda **um comando curto de cada vez** como root. Os atalhos
só encadeiam o fluxo oficial acima; não o substituem nem pulam etapas.

| Comando (root) | O que faz |
|---|---|
| `wd-sync` | `git fetch` com a chave do root, devolve o `.git` a `workdev:workdev-runtime`, `checkout main` e `merge --ff-only origin/main` como `workdev`. Termina com `SYNC_OK` |
| `wd-push [branch]` | publica a branch atual (ou a informada) com a chave do root e acerta o dono do `.git`. Recusa o `main`. Termina com `PUSH_OK (<branch>)` |
| `wd-prepare` | passo 1: roda o gate e emite a prova; guarda o `proof_id` em `/run/workdev-last-proof` (só root escreve) |
| `wd-deploy` | passos 2 e 3: `approve --actor Claudio` (ou `WD_ACTOR`) + `deploy.sh <proof_id>`; recusa prova com mais de 840 s; termina com `DEPLOY_OK` e chama `wd-verificar` |
| `wd-verificar` | só leitura, não precisa de root: `workdev-api` ativo, PID da porta 8000 = `MainPID`, `/health` online, site 200, bundle sem `localhost:8000`. `VERIFICACAO_OK` ou sai com 1 |

O `post_deploy_gate` **já roda dentro do `deploy`** (`deploy_broker.py` chama `wait_for_checks`,
com rollback automático); não é um passo manual separado.

### Roteiro de um deploy, do começo ao fim

1. **Agente (`workdev`)**: valida a branch (lint, build, testes), abre o PR e faz o merge com `gh`.
   Nunca faz push: o `workdev` só lê o GitHub.
2. **Root**: `wd-push` (se a branch ainda não está no GitHub), depois `wd-sync` depois do merge.
3. **Agente (`workdev`)**: `pnpm run build` em `apps/web` **a partir do `main` atualizado** e confere
   `grep -c "localhost:8000" apps/web/dist/assets/index-*.js` = 0. O build tem que existir ANTES do `prepare`.
4. **Root**: `wd-prepare`, e só então `wd-deploy` (a prova vale 900 s).
5. **Agente**: confere por fora com `wd-verificar` (ou os comandos dele à mão) antes de dar o deploy por feito.

### Instalação (uma vez, e de novo se um atalho mudar)

Fonte versionada em `scripts/deploy/atalhos/`, destino `/usr/local/sbin/wd-*` (`root:root 0755`),
listados em `scripts/deploy/install-manifest.txt`. **Nunca rodar os atalhos de dentro do
repositório como root** (mesma regra do `workdev-deployctl`): o checkout é do `workdev`, que pode
alterar o arquivo. Instalar a cópia em `/usr/local/sbin` e rodar só ela. Antes de instalar, ler o
que mudou (`git log -p -- scripts/deploy/atalhos`), porque o root passa a executar essa cópia.

### Regras do terminal do operador

- O terminal quebra comandos longos ao colar: **um comando por vez**, curtos. Para qualquer coisa
  maior, gravar num script e pedir `bash <caminho>`; os `wd-*` existem por isso.
- Agentes não devem inventar novos fluxos de root: se faltar um atalho, propor a mudança em PR.

## Incidentes já vividos (leia antes de repetir)

- **Commitar antes do `prepare`.** Ele empacota `git archive HEAD` — nada de não commitado entra na release, mesmo que já esteja salvo em disco.
- **Rodar a suíte de testes como `root` mascara bugs reais de permissão.** O gate roda os testes como usuário `workdev`, restrito. Testes que passam como root podem falhar no gate por causa disso — e pior, podem criar arquivos de estado (`/var/lib/agents-healthcheck/*.json`) com dono `root:root`, ilegíveis pelo `workdev` real depois, quebrando produção silenciosamente. Valide sempre com:
```bash
  runuser -u workdev -g workdev-runtime -G workdev -- env -u WORKDEV_API_ENV_FILE \
    apps/api/venv/bin/python -m pytest -q apps/api/tests/
```
- **Working tree compartilhado com outros trabalhos em andamento.** `git status` pode mostrar mudanças de outra tarefa (ex.: fine-tuning local-code) que não são suas — confirme o escopo antes de commitar pro deploy.
- **Testes ocasionalmente flaky fora do escopo do que você mudou** (ex.: `test_agent_review_regressions.py`, `test_terminal.py`) podem falhar uma vez e passar limpo logo depois, sem relação com sua mudança — mas sempre confirme rodando de novo antes de assumir que é flakiness.

## Referência rápida dos scripts (só usar se este runbook estiver desatualizado)

- `/usr/local/sbin/workdev-deployctl` — wrapper que exige root e delega pro broker como `workdev-deploy` (fonte versionada em `scripts/deploy/workdev-deployctl`; nunca executar a fonte como root).
- `/usr/local/lib/workdev-deploy/deploy_broker.py` — CLI real: subcomandos `prepare`, `approve --actor`, `deploy`.
- `/usr/local/libexec/workdev-predeploy-gate` — roda `verificar-deploy.sh --testes` como usuário `workdev`.
- `/usr/local/lib/workdev-deploy/verificar-deploy.sh` — as 8 checagens (git, escopo, segredos, sintaxe Python/shell, build, porta 8000, testes).
- `/usr/local/lib/workdev-deploy/release_manager.py` — cria/promove/reverte as releases imutáveis em `/opt/workdev-runtime`.
- `scripts/deploy/permission_contract.py` — contrato declarativo de ownership/permissão dos caminhos sensíveis (cobre diretórios fixos, não arquivos individuais gerados em runtime).
