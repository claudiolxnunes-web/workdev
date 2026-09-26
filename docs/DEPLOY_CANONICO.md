# Deploy Canônico do WorkDev

Fonte canônica para TODOS os agentes.

## Regra

NUNCA improvisar o processo de deploy.
NUNCA executar `deploy.sh` sem `proof_id`.
NUNCA gerar prova manualmente com `deploy_proof.py`.
NUNCA redescobrir o fluxo procurando scripts, salvo se este runbook estiver comprovadamente desatualizado.

## Fluxo oficial

### 1. Prepare

```bash
cd /opt/workdev
sh scripts/deploy/workdev-deployctl prepare
```

- Precisa rodar como `root` (o wrapper delega internamente pro usuário `workdev-deploy`).
- Primeiro roda o gate de pre-deploy (`workdev-predeploy-gate`), que executa `verificar-deploy.sh --testes` **como usuário `workdev`** (não root!), validando: git limpo, escopo dos arquivos alterados, segredos versionados, sintaxe Python/shell, build do frontend, porta 8000 e a suíte de testes inteira.
- Se o gate passar, empacota via `git archive HEAD` (**só o que estiver commitado** — mudanças salvas no disco mas não commitadas nunca entram) + o build do frontend, e cria uma release imutável em `/opt/workdev-runtime/releases/<uuid>`.
- Imprime um `proof_id`, válido por 900s (15 min) por padrão.

### 2. Approve

```bash
sh scripts/deploy/workdev-deployctl approve <proof_id> --actor "<seu nome>"
```

Esse é o ponto de aprovação humana explícita do pipeline — quem roda assume a responsabilidade pelo deploy.

### 3. Deploy

```bash
sh scripts/deploy/workdev-deployctl deploy <proof_id>
```

Promove a release preparada pra `current` (symlink atômico), reinicia `workdev-api.service`, roda checagem pós-deploy, e faz rollback automático (volta pra release anterior + reinicia) se algo falhar.

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

- `scripts/deploy/workdev-deployctl` — wrapper que exige root e delega pro broker como `workdev-deploy`.
- `/usr/local/lib/workdev-deploy/deploy_broker.py` — CLI real: subcomandos `prepare`, `approve --actor`, `deploy`.
- `/usr/local/libexec/workdev-predeploy-gate` — roda `verificar-deploy.sh --testes` como usuário `workdev`.
- `/usr/local/lib/workdev-deploy/verificar-deploy.sh` — as 8 checagens (git, escopo, segredos, sintaxe Python/shell, build, porta 8000, testes).
- `/usr/local/lib/workdev-deploy/release_manager.py` — cria/promove/reverte as releases imutáveis em `/opt/workdev-runtime`.
- `scripts/deploy/permission_contract.py` — contrato declarativo de ownership/permissão dos caminhos sensíveis (cobre diretórios fixos, não arquivos individuais gerados em runtime).
