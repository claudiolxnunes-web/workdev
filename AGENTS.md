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
- O Qwen mantém DashScope e OpenRouter no catálogo `scripts/qwen-agent-settings.json`;
  a troca manual de provider é feita pelo comando `/model` dentro do agente.

## Aprovacao de comandos (Termux/celular)

- Prompt truncado nao se aprova. Se aparecer "[... N lines]", cancelar com esc e pedir o comando completo impresso antes da proposta.
- Nunca usar "don't ask again" (opcao 2) em sessao pelo celular.
- install, rm, systemctl, git push, docker: ler integralmente antes de aprovar, sem excecao.
- Agente deve imprimir o comando em bloco normal antes de propor execucao quando a sessao for mobile.

## Decisoes que exigem o Claudio

- Decisao de rumo que nao e do agente vira ADR com status proposed, via POST /api/adrs.
- context: o problema e por que parou. decision: as opcoes vistas, uma por linha, com o trade-off de cada uma.
- Nao deixar decisao pendente so no chat da sessao.
- Nao usar ADR para aprovacao de comando pontual, que continua no fluxo do terminal.
