# Checkout do WorkDev pertence ao `workdev`; pnpm e pytest só como `workdev`

**Data:** 2026-10-02
**Status:** aceito (executado em 2026-10-02)
**Projetos afetados:** WorkDev Core

## Contexto

Pendência aberta desde 2026-08-20 (depois de `7d14fab`, serviços sem privilégio):
arquivos do checkout continuavam `root:root`, criados por sessões rodando como root.

Levantamento de 2026-10-02 (fora de `.git`, venvs e `node_modules`): **198 itens root**.

- ~170 arquivos **versionados** de código/docs (644): legíveis, mas só root escrevia —
  agentes CLI (que rodam como `workdev`) recebiam `EACCES` ao editar.
- 3 árvores `node_modules` com 4.166 itens root e o **store do pnpm em
  `/root/.local/share/pnpm/store`**, ilegível pelo `workdev`: `pnpm add` como `workdev`
  falhava; o contorno com `sudo pnpm install` recriava tudo como root.
- 15 pastas `__pycache__`/`.pytest_cache` root: `pytest` como `workdev` exigia
  `-p no:cacheprovider`.
- `dist/` buildado como root faz o predeploy-gate (que builda como `workdev`) falhar
  no `emptyDir` do Vite.

## Decisão

- Arquivos rastreados pelo git (via `git ls-files`) e suas pastas →
  `workdev:workdev-runtime`, preservando modo.
- `node_modules` reinstalado como `workdev` com store próprio
  (`/home/workdev/.local/share/pnpm/store/v11`), lockfile inalterado.
- Caches Python root apagados (são recriados como `workdev`).
- **Ficam root de propósito:** `.env*` (600/640), `deploy.sh` (root o executa),
  `models/`, `.backups/`, `.local/`, `.claude/`, venvs e saídas ignoradas de `training/`.

## Regras daqui em diante

- `pnpm add|install|build`: `runuser -u workdev -- env CI=true pnpm …`
  (reinstalar: `pnpm install --frozen-lockfile --config.confirmModulesPurge=false`).
- `pytest`: como `workdev`, sem `-p no:cacheprovider`.
- Sessão root que editar código termina com `chown workdev:workdev-runtime` nos
  arquivos tocados; git como root termina com `chown -R workdev:workdev-runtime .git`.
- Nunca `chown -R` no `/opt/workdev` inteiro: venvs e `.env` têm dono proposital.

## Consequências

- Agentes CLI editam qualquer arquivo versionado; o gate de deploy builda e testa sem
  ajuste manual.
- Contrapartida aceita: o `workdev` agora escreve em todo o código versionado — por
  isso nada que root execute pode vir do checkout (ver
  `2026-10-02-deployctl-caminho-instalado.md`).
