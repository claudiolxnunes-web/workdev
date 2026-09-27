# Reset manual das sessões de agentes

O reset encerra todas as sessões do servidor tmux do usuário `workdev`, remove
os arquivos `.workdev/lifecycle/*.json` e fecha runs `running` e jobs
`queued/running` como `cancelled`, preservando registros e eventos de auditoria.
Ele não inicia agentes nem altera timers/services.

Na interface, abra **Agentes → Resetar sessões…**, revise as quatro listas e
digite `RESETAR`. Se o impacto mudar depois do preview, a API recusa a ação e
exige nova revisão.

Pelo terminal, o fluxo equivalente é:

```bash
scripts/workdev-reset-agents.sh preview
scripts/workdev-reset-agents.sh execute --confirmation-token '<token-do-preview>'
```

Execute o segundo comando fora do próprio tmux (por SSH/console). O script
usa a API local autenticada quando o ambiente não contém acesso direto ao
banco; se necessário, solicita `WORKDEV_API_KEY` sem eco. A execução física
ocorre no processo da API, fora da sessão que será encerrada.

O token expira em cinco minutos e é vinculado ao conjunto exato de sessões,
arquivos, runs e jobs exibido. Execuções repetidas são idempotentes. O timer de
health pode posteriormente recuperar somente `ALWAYS_ON_AGENTS`; isso é externo
ao reset e não deve ser antecipado manualmente.
