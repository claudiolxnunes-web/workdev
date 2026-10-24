# Polling e sessões — execução 208fb301

Branch: task/e32bbf55-agent-polling. Data: 2026-09-10.

## Alteração
- Status do frontend: intervalo mínimo de 5000 ms entre o término de uma
  requisição e a próxima; sem sobreposição; pausa por blur e Page Visibility.
- VITE_AGENTS_STATUS_POLL_MS configura o intervalo no build. Valores menores
  que 5000 são elevados ao mínimo; valores não finitos usam 5000.
- Backend: cache de 2 segundos após coleta, por worker, com uma tarefa
  compartilhada entre clientes. Desconectar um cliente não cancela a coleta.
- O supervisor existente recupera sessões ausentes de Claude/Codex.
  Sessões existentes com shell são preservadas e indicadas como offline.
  Kimi/Qwen/Gemini continuam sob demanda.

## Evidências executadas
- unittest: 56 testes do terminal, cache e supervisor passaram.
- vitest: 70 testes passaram, incluindo pausa, retomada e desmontagem.
- Build TypeScript/Vite e lint dos arquivos frontend alterados passaram.
- git diff --check passou. Zero localhost:8000 nos bundles JS.
- Sessão temporária com sleep foi criada, interrompida, recuperada via
  inspect_agent e removida. Nenhuma sessão de agente foi interrompida.
- Mapa antes/depois: code (%17, PID 299515, claude) e codex
  (%18, PID 829490, node). Nenhuma duplicata ou sessão morta nesse servidor.
- Dez coletas locais contra tmux real, com consultas ao banco substituídas:
  sem cache: 90 subprocessos, 0,150 s total, 0,273 s CPU dos filhos;
  com cache: 9 subprocessos, 0,014 s total, 0,026 s CPU dos filhos.
  É uma amostra local, não uma medição de impacto em produção.

## Validação pendente
- DevTools Network: confirmar pausa ao ocultar a aba/perder foco e retomada.
  Não havia ferramenta de navegador disponível nesta sessão.
- A simulação real validou o supervisor; a indicação correspondente na UI
  ainda precisa de validação visual.
- Revisão independente do Gemini e deploy pelo pipeline com prova assinada.
- Após publicar, repetir a observação de frequência e CPU em produção.
