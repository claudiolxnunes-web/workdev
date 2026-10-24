# ADR — Credenciais e supervisão dos agentes CLI na VPS1

- **Data:** 2026-08-15 (consolidando trabalho de 14 e 15/08)
- **Status:** aceita; um agente ainda pendente
- **Autor:** Cláudio L. X. Nunes

## Contexto

Quatro agentes CLI (Claude Code, Codex, Kimi, Qwen) rodam em sessões tmux
gerenciadas por `/opt/scripts/agents.sh` via `workdev-agents.service`.

Dois problemas persistentes:

1. **Credenciais não chegavam aos agentes.** `Environment` e `EnvironmentFile`
   no systemd eram ignorados. A causa: `agents.sh` usa `tmux send-keys` para
   lançar os binários, o que os inicia dentro de um shell interativo — e a linha
   100 de `/root/.bashrc` exporta uma chave global que sobrescreve qualquer
   coisa vinda do systemd. O ambiente do serviço nunca vencia.
2. **Morte silenciosa de agentes.** O serviço é `Type=oneshot`; processos que
   morriam depois do start não eram detectados.

Leitura de erro que economiza diagnóstico: "Incorrect API key" significa que a
chave chegou e foi rejeitada; "Missing Authentication header" significa que
nenhuma chave chegou.

## Decisão

**Wrappers em `/usr/local/bin/`.** Cada agente que precisa de credencial própria
ganha um wrapper no padrão:

    set -a; . /root/.<agente>/.env; set +a; exec <binário>

O `set -a` exporta tudo do arquivo antes do `exec`, de modo que o ambiente é
montado depois do `.bashrc` e não é sobrescrito por ele. É a inversão de ordem
que resolve o problema — não uma mudança no systemd.

**Supervisão em duas camadas.** Bootstrap no boot recria as sessões; um cron a
cada 5 minutos (`/opt/scripts/agents-healthcheck.sh`) verifica e ressuscita,
com `flock` contra concorrência, alertas no Telegram e anti-spam de 6 horas por
agente.

## Situação por agente

- **Qwen:** resolvido. `/usr/local/bin/qwen-or` + `/root/.qwen/.env`, via
  OpenRouter no modelo `qwen3-coder-plus`.
- **Codex:** usa a chave global do `.bashrc`, sem wrapper. Configurado com
  `approval_policy = "on-request"` e `sandbox_mode = "workspace-write"` no
  `config.toml`, o que eliminou os pedidos de aprovação para leitura.
  `bubblewrap` instalado para o sandbox.
- **Claude Code:** sem pendência de credencial.
- **Kimi Code (v0.34.0):** pendente. Não lê credenciais de variáveis de
  ambiente — mantém registro interno de provedores em
  `/root/.kimi-code/config.toml`, que nasce vazio e só é populado pelo fluxo
  `/provider` na TUI. O `.env` e o wrapper `kimi-mo` já estão prontos; falta a
  navegação manual. A chave direta da Moonshot só atende até o K2.7; o K3 exige
  OpenRouter.

## Consequências

- Auditoria de 15/08 confirmou: nenhum supervisor duplicado, wrappers
  reimplementados corretamente dentro dos scripts de start, chaves presentes.
- O healthcheck se provou em operação real ao recriar sozinho a sessão do Codex.
- **Cuidado operacional:** nunca reiniciar `workdev-agents.service` durante
  navegação na TUI do Kimi — derruba o fluxo `/provider` e obriga a recomeçar.
