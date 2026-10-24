# Workspace Local (estilo VS Code) só leitura; modelo local só propõe

**Data:** 2026-10-02
**Status:** aceito (implementado em `2b8d658` e `e72988b`; deploy pendente)
**Projetos afetados:** WorkDev Core

## Contexto

A Bancada Local (llama-server, MoE 35B) foi validada em 02/10: 5/5 tarefas de triagem
com JSON válido e sem invenção; observers comparados em 8 casos calibrados. Faltava uma
forma prática de mandar tarefas ao modelo local sem digitar caminho e linhas à mão.

## Decisão

Página `/workspace` no desenho do VS Code:

- **Explorer:** árvore do checkout carregada pasta a pasta + alterações vs HEAD.
- **Editor só leitura:** arquivo com seleção de linhas → "Adicionar ao chat"; diff do
  git; proposta do modelo local como diff.
- **Chat do modelo local:** trechos anexados (até 8, ≤400 linhas cada), resposta ao
  vivo (SSE), checagens mecânicas, parecer do observer escolhido, reenvio com o prompt
  de correção. Ações finais: "Abrir no editor" e "Copiar patch". **Nada é aplicado.**
- **Terminal tmux** opcional, só aberto por pedido explícito (não rouba a sessão).
- Painéis com `react-resizable-panels` 4.x; abas no celular.

API nova, **somente GET** (`/api/workspace/{arvore,arquivo,alteracoes,diff}`):

- a lista vem do **git** (`ls-files -co --exclude-standard`), não do disco — `.env`,
  `node_modules`, venvs, `models/`, `dist`, `tmp/` e ignorados ficam de fora;
- por cima, a lista de bloqueio da Bancada + `tmp/`, `__pycache__`, `.ssh/`,
  `.workdev-recovery/` (patches e tarballs de recuperação = conteúdo arbitrário);
- `realpath` preso ao checkout (symlink para fora é recusado), 200 KB por arquivo/diff,
  binário não exibido, timeout de 10 s no git;
- máscara de `sk-…`, `sb_secret_…`, `sb_publishable_…`, `Bearer …`, JWT `eyJ…`,
  tokens GitHub e `AKIA…` em todo conteúdo.

O envio continua pelas rotas POST da Bancada (uma execução por vez, lock).

## Alternativas descartadas

- Workspace com terminal dos agentes CLI no centro: mistura dois mundos; o terminal
  ficou como painel opcional.
- Divisor próprio sem dependência: chegou a ser feito, trocado pela biblioteca depois
  que a pendência de ownership do `node_modules` foi resolvida.

## Próximo passo

Fase B ("Enviar ao Build"): proposta aprovada vira run na fila de Agents com executor
escolhido pelo operador — quem aplica no repo é sempre um agente CLI auditado.
