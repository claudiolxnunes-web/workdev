# Deploy só pelo `workdev-deployctl` instalado, nunca pela cópia do repositório

**Data:** 2026-10-02
**Status:** aceito (runbook alterado em `b525c3c`)
**Projetos afetados:** WorkDev Core

## Contexto

O `docs/DEPLOY_CANONICO.md` mandava rodar, **como root**,
`sh scripts/deploy/workdev-deployctl prepare|approve|deploy` a partir do checkout.

Pelo contrato de permissões (`scripts/deploy/permission_contract.py`) o checkout
`/opt/workdev` pertence ao usuário `workdev` (750), e `scripts/deploy/workdev-deployctl`
é `workdev:workdev-runtime 640`. Ou seja: qualquer processo rodando como `workdev` —
inclusive os agentes CLI nas sessões tmux — pode alterar esse arquivo, e o próximo
operador que seguir o runbook executa o conteúdo alterado como root. Escalada de
privilégio latente, sem exploração conhecida (em 2026-10-02 a cópia era idêntica à
instalada).

O `deploy.sh` já fazia o certo: chama `/usr/local/sbin/workdev-deployctl` e recusa se
o controlador não for `root:root 755`. Só o runbook (e o `prepare`/`approve`) apontava
para o repositório.

## Decisão

- `prepare` e `approve` usam **`/usr/local/sbin/workdev-deployctl`** (root:root 755).
- `deploy` usa **`bash /opt/workdev/deploy.sh <proof_id>`** (confere o dono do controlador).
- A cópia em `scripts/deploy/` é só a fonte versionada que o `install-manifest.txt`
  instala; nunca é executada como root.

## Consequências

- Mudança no `workdev-deployctl` só vale depois de reinstalada por root (fluxo do
  `install-manifest.txt`) — o que é exatamente a barreira desejada.
- Vale o mesmo princípio para qualquer script do repo: **root não executa arquivo que
  o `workdev` pode escrever**. O `deploy.sh` continua `root:root` pelo mesmo motivo,
  embora o dono da pasta (`workdev`) ainda possa substituí-lo — a defesa real é ele só
  delegar ao controlador instalado e verificado.
- Pendente avaliar: outros comandos documentados que root roda a partir do checkout
  (ex.: scripts de instalação em `scripts/deploy/`).
