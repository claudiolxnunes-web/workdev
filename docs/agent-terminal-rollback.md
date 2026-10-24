# Rollback da estabilização do terminal dos agentes

Ponto de restauração criado antes da implementação:

- branch: `backup/agent-ux-20260904T190000Z`
- commit base: `1d2b23a58e67d3731fb00d60b6fc87b974ca982f`
- artefatos privados: `/opt/workdev/.restore-points/20260904T190000Z-agent-ux`

O diretório privado contém um bundle Git completo, diff/status originais,
configurações tmux e systemd, arquivos críticos e cópias dos arquivos não
rastreados produzidos pela tarefa Gemini. Nenhum `.env` foi incluído.

## Reverter código

Não use `reset --hard` no checkout ativo. Crie um worktree de recuperação e
reverta os commits da estabilização em ordem inversa:

```bash
git worktree add /tmp/workdev-agent-ux-rollback backup/agent-ux-20260904T190000Z
git log --oneline backup/agent-ux-20260904T190000Z..develop
git revert <commit-7> <commit-6> <commit-5> <commit-4> <commit-3> <commit-2> <commit-1>
```

Se o repositório local ficar indisponível, recupere o histórico pelo bundle:

```bash
git clone /opt/workdev/.restore-points/20260904T190000Z-agent-ux/workdev.bundle /tmp/workdev-restored
```

## Reverter tmux

As opções originais estão em `tmux-global-options.txt` e
`tmux-window-options.txt`. O valor original de `history-limit` era `2000`.
Restaurá-lo não exige reiniciar nem recriar sessão:

```bash
tmux set-option -g history-limit 2000
```

Não reinicie `workdev-agents.service`: todas as sessões compartilham o mesmo
cgroup e seriam encerradas. A sessão Gemini nunca deve ser recriada durante uma
execução ativa.

## Reverter produção

O deploy WorkDev cria uma release promovida em `/opt/workdev-runtime`. Use o
registro de release do pipeline para promover a release anterior; depois valide
`workdev-api.service` e `/health`. Não copie arquivos isolados para o runtime e
não reinicie `workdev-agents.service`.

## Verificar os artefatos

```bash
cd /opt/workdev/.restore-points/20260904T190000Z-agent-ux
sha256sum -c SHA256SUMS
git bundle verify workdev.bundle
```
