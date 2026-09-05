# Operação dos terminais dos agentes

## Responsabilidades

- tmux preserva um processo independente para cada agente;
- o WebSocket transporta entrada e saída interativa;
- `agent-transcripts/` guarda saída append-only privada;
- `/api/agents/status` publica estado operacional e aprovação;
- o frontend apresenta terminal, transcript e estado sem controlar lifecycle
  implicitamente.

Fechar, trocar de aba ou usar **Reconectar navegador** nunca encerra uma sessão.
O endpoint de encerramento exige `confirm=true` e recusa agentes com execução
ativa. O supervisor não mata uma sessão existente só porque seu foreground
parece ser um shell.

## tmux

- `history-limit=100000` é aplicado antes da criação de novos painéis;
- painéis criados antes dessa configuração mantêm o limite original até seu
  próximo reinício natural; o transcript persistente cobre esse intervalo;
- `alternate-screen` permanece habilitado para compatibilidade com os TUIs;
- scroll no navegador é local e não coloca o painel compartilhado em copy-mode;
- `TERM=tmux-256color` é fornecido pelo tmux e os launchers definem
  `COLORTERM=truecolor` em novos processos.

## Nomes das sessões

As sessões canônicas são `codex`, `gemini`, `kimi` e `qwen`. Claude ainda usa o
nome legado `code`. A migração para `claude` fica adiada até uma janela em que a
sessão esteja comprovadamente sem execução; ela não justifica interromper o
processo atual.

## Transcript

Os arquivos ficam em `/opt/workdev/agent-transcripts`, modo `0600`, dentro de
diretório `0700`. São rotacionados em 20 MiB e não são versionados. A API remove
ANSI, OSC e caracteres de controle antes de devolver texto ao navegador.

Para reativar pipes sem reiniciar agentes:

```bash
/opt/workdev/scripts/configure_agent_transcripts.py
```
