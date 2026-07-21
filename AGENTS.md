# WorkDev Core — Instruções para Agents

Antes de atuar neste repositório, leia `/opt/workdev/CLAUDE.md` por completo. Ele
é a fonte de contexto sobre arquitetura, infraestrutura, segurança e deploy.

- Preserve alterações preexistentes e arquivos que não pertencem à task.
- No fluxo PLAN → BUILD, implemente somente o plano aprovado recebido na fila.
- Se surgir incompatibilidade arquitetural, registre bloqueio em vez de alterar
  silenciosamente o objetivo aprovado.
- Execute as validações do plano e não declare teste, commit ou deploy que não
  tenha ocorrido.
- Nunca imprima, copie para prompts ou versione secrets dos arquivos `.env`.
- Registre o estado com `python3 /opt/workdev/scripts/workdev_agent.py --help`.
- O Build aceita `codex`, `claude`, `kimi` e `qwen`; a sessão `qwen` deve ser
  iniciada por `scripts/start_qwen_agent.sh`, sem expor as chaves do backend.
