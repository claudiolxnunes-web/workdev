# Workspace Local — execução assistida com modelo local

Status: **proposta para o operador**. Data: 2026-10-25.
Escopo: **somente o Workspace Local**. A Bancada Local não é tocada.

## 1. O problema

O modelo local não é ruim — ele nunca começa. O harness da CLI cola 22–30 mil
tokens de prompt antes de qualquer trabalho, e na CPU (31 GB, sem GPU) isso
são 7 a 10 minutos de prefill antes do primeiro token. Medido em 2026-10-24:
prefill a 47–61 tok/s com o modelo quente, ou seja ~20 s por 1.000 tokens.

A Bancada Local resolve o contexto: o AI Hub lê o repo real, localiza os
arquivos e as linhas, e entrega um plano com trechos — o modelo local recebe
1–3 mil tokens em vez de 22 mil. Mas a Bancada **só propõe**: nada é aplicado.

E o Workspace, que é onde a pessoa está, hoje não serve para executar: o editor
é somente leitura ("repositório só leitura · o modelo local só propõe") e o
chat da direita é a Bancada embutida (`ChatLocal` → `/bancada/rodar`).

Falta o lugar onde a mudança acontece: um Workspace onde o modelo local executa
um plano fatiado, aplica cada fatia de forma isolada e auditável, e a pessoa
assiste e decide.

## 2. A forma

| Ambiente | Quem planeja | Quem lê | Quem propõe | Quem aplica |
|---|---|---|---|---|
| **Bancada** (não muda) | AI Hub (Fable) | AI Hub | modelo local | ninguém — a Bancada só propõe |
| **Workspace** (novo) | supervisor, no chat lateral | modelo local (tools) | modelo local | modelo local, no worktree da sessão; **incorporar é do operador** |
| CLI (o que trava) | harness | harness | harness | — |

O Workspace deixa de ser a Bancada embutida e passa a ser o lugar da execução
assistida. A Bancada continua na própria página, com o contrato de sempre.

## 3. Layout (novo)

Hoje (`apps/web/src/pages/Workspace.tsx`): `Explorer | Centro: Editor (+ Terminal) | Direita: ChatLocal`.

Novo:

```
┌───────────┬────────────────────────────────────┬──────────────────────┐
│ Explorer  │  Centro: Editor                    │  Lateral: Chat do    │
│           │            + Terminal (tmux)       │  supervisor (AI Hub) │
│           │            + Chat do modelo local  │                      │
└───────────┴────────────────────────────────────┴──────────────────────┘
```

- **Lateral (direita): o supervisor.** Chat com o modelo grande (Luna,
  DeepSeek ou Qwen via OpenRouter), no desenho do Copilot do VS Code. É por
  ele que se pede o plano e se acompanha o avanço. É o "modelo que fica
  supervisionando" do enunciado.
- **Centro: o editor**, que é o lugar de editar com o modelo local. O editor
  passa a **gravar** — mas apenas no worktree da sessão (§5). O banner do
  cabeçalho ("repositório só leitura · o modelo local só propõe, nada é
  aplicado") muda para refletir o contrato novo.
- **Chat do modelo local** desce para o centro, ao lado do editor e do
  terminal. Continua sendo o chat que conhece anexos, proposta, checagens e
  pareceres — agora com execução.
- **Terminal**: continua sendo o attach na sessão tmux. É por ele que se
  assiste o agente de CLI, se quiser.
- **Mobile**: as quatro áreas viram abas (Explorer · Editor · Local ·
  Supervisor), no padrão do `abaMovel` que já existe.

O que muda no código: o painel direito deixa de ser o `ChatLocal` e passa a ser
o chat do supervisor; o `ChatLocal` entra no centro; o `Editor` ganha escrita.

### 3.1 O que já está feito (entrada no Workspace)

O backlog ganhou o terceiro destino, ao lado de "Enviar ao AI Hub" e "Plano
para a Bancada Local":

- **"Plano para o Workspace Local"** (`POST /api/chat/workspace/planejar`):
  cria uma sessão de chat em modo Observar com o prompt do supervisor
  (`_workspace_planning_context`) e abre `/workspace?session=<id>&autostart=workspace`.
  A sessão do Workspace **não** toma a vaga da task reservada ao AI Hub
  (`uq_chat_sessions_task_id`) e **não** mexe na chave `workdev_chat_session`:
  a conversa do supervisor é do Workspace, não do AI Hub.
- **Lateral direita: `ChatSupervisor`** (`modules/workspace/ChatSupervisor.tsx`).
  Conversa com o modelo grande, com seletor de modelo: **todos** os modelos
  ficam à mão — os da nuvem (OpenRouter) e os locais. A escolha fica guardada.
- **Centro: o chat do modelo local** desceu para o painel inferior, com abas
  `Terminal | Local` no padrão do rodapé do VS Code. O chat do supervisor ficou
  à direita, como o Copilot do VS Code.
- **Troca do modelo local**: `GET /api/bancada/modelo/opcoes` e
  `POST /api/bancada/modelo/trocar` (o llama-server é compartilhado pela
  Bancada, pelo Workspace e pelo local-code). O seletor
  (`modules/local/SeletorModeloLocal.tsx`) aparece na Bancada e no chat do
  Workspace. O padrão segue sendo o **Qwen3.8 35B A3B MoE**; trocar reinicia o
  llama-server e é recusado (`agent_busy`) enquanto o local-code tem trabalho
  em andamento.

### 3.2 O supervisor precisa ver o estado do trabalho

O operador para uma configuração no meio da execução e pede ao supervisor para
olhar. Isso **não** é possível hoje: o supervisor só enxerga o repositório
(`ler_trecho`), não o que a sessão já fez.

Falta uma ferramenta de leitura do estado da sessão, com o mesmo espírito de
`ler_trecho` (somente leitura, sem escopo amplo):

- `ler_estado_sessao`: o diff acumulado do worktree da sessão, os arquivos já
  tocados, a última resposta do modelo local e o gate pendente.
- Sem ela, o supervisor planeja no escuro: não sabe o que já foi aplicado e
  repropõe o que já existe.

Esta é a próxima peça do laço de execução (§4) e entra antes da escrita no
editor (§5).

## 4. O laço de execução

Uma fatia por vez, com a pessoa no comando:

```
supervisor (lateral)             local (centro)                    worktree da sessão
─────────────────────             ──────────────                    ────────────────────
pede o plano  ──────────────►    fatia 1: instrução + trechos
                                  o local lê o que precisar
                                  (tools de leitura)
                                  propõe o patch
                                                                   git apply --check
                                                                   aplica (commit)
                                                                   gate (testes)
◄── diff ao vivo, gate, pausa ─────────────────────────────────────┘
                                  fatia 2: ...
```

Regras do laço:

- **Uma fatia por vez.** A próxima só começa depois que a anterior foi aplicada
  e passou no gate. O gate entre fatias é o que impede a fatia 3 de consertar a
  fatia 2 quebrada.
- **Falha não derruba a sessão.** Falha de gate, de aplicação ou de modelo vira
  um resultado com código (o `BuildOutcome` já é exatamente esse contrato) e
  a sessão para, esperando o operador.
- **Pausa e retomada** a qualquer momento (`run_pause` já existe).
- **Trilha**: cada passo grava `AgentRunEvent` — o mesmo mecanismo que o
  `local_code_build` usa hoje.
- **O modelo nunca commita na sua branch, nunca faz merge e nunca faz push.**

## 5. Sessão, worktree e incorporação

O `build_worktree` já faz quase tudo isso, mas no formato efêmero de um build.
Para o Workspace:

- **Um worktree por sessão**, não por fatia: a sessão mantém a árvore viva
  enquanto as fatias acumulam commit a commit. O helper atual remove o
  diretório na saída; aqui a remoção é no fim da sessão, e o branch permanece
  (como hoje: "o branch permanece, de propósito").
- **Branch `workspace/{sessao}`** — prefixo próprio, para não se confundir com
  `build/...`. Nunca é pushado: o branch é o único lugar onde os commits
  existem.
- **Base limpa**: o worktree nasce no HEAD, então alteração não commitada da sua
  árvore não está lá dentro. Se você estiver no meio de um trabalho, o modelo
  aplicaria um diff contra um estado que não é o seu. Regra: a sessão começa
  só com árvore limpa (o Workspace já tem `alteracoes()` para avisar), e a
 incorporação roda `git apply --check` antes.
- **Uma sessão ativa por repo.** Duas sessões = dois worktrees; se as duas
  mexerem no mesmo arquivo, a segunda incorporação conflita. O repo já tem
  esse padrão em `agent_lifecycle` (lock por agente/run).
- **Incorporar é escolha do operador**, com duas formas na tela: *merge* do
  branch (N commits, um por fatia) ou *squash* num commit só. O diff
  acumulado aparece antes, para review.

## 6. Banco: fora da proteção do worktree

O worktree isola o **código**, e só o código. Prova no próprio
`build_worktree.py`:

> `.env` do `apps/api` também fica fora — o worktree não precisa de credencial
> de banco para rodar o gate.

Ou seja: a escrita no banco acontece pelo **API que está no ar**, contra o
**banco real** — o worktree não participa. "Está num worktree separado" não
protege dado nenhum. Cada fatia de banco precisa de:

- transação (tudo ou nada);
- registro do "antes" (para desfazer);
- caminho de reversão explícito, ou idempotência para repetir sem duplicar;
- registro na trilha de auditoria da sessão.

### 6.1 Decisões do operador para as fatias de banco (2026-10-25)

- **Só dados:** INSERT, UPDATE e DELETE. CREATE/ALTER/DROP e afins são recusados e
  viram fatia de código com migration do Alembic (aplicada só com confirmação).
- **Só as tabelas de registro:** `projects`, `backlog`, `backlog_subtasks`,
  `knowledge`, `decisions`, `adrs`, `rfcs`.
- **No máximo 50 linhas** por fatia.
- O modelo lê só a **estrutura** das tabelas, nunca os dados.
- Fluxo: o modelo propõe o SQL → **simulação** (transação, "antes", verificação,
  rollback) → o operador clica **Aplicar** (refaz na transação; recusa se o
  conjunto de linhas mudou desde a simulação) → "antes" e "depois" gravados →
  **Reverter** restaura a partir do "antes", recusando se a linha mudou depois.
- INSERT cria o nó no Engineering Graph; DELETE deixa nó órfão (pendência
  conhecida do cascade Postgres → grafo).

## 7. Leitura pelo modelo local

> **Feito em 2026-10-25** (`feat/workspace-ferramentas-leitura`): o chat Local manda
> `ferramentas: true` e o modelo local usa `buscar_texto`, `listar_pasta` e
> `ler_arquivo` por function calling (`--jinja`, fixado no `workdev-llama-run`).
> A leitura é uma só para o local e o supervisor: `app/services/leitura_repo.py`,
> contra o checkout de trabalho (não a release), com `git grep` respeitando o
> `.gitignore`. Tetos: 6 voltas, 24 mil caracteres acumulados, 6 mil por leitura.
> O supervisor ganhou `buscar_texto` e `listar_pasta` (nível Observar). A página
> da Bancada segue sem ferramentas.

O local recebe três tools, que já existem no `scripts/bancada_local.py`:
`ler_arquivo`, `listar_pasta`, `buscar_texto`. Reaproveitar as três mantém uma
implementação só e herda o que já está feito: teto de linhas por leitura,
validação de caminho, recusa de caminho fora do repo.

Duas regras para o custo:

- **Buscar antes de ler.** `buscar_texto` roda localmente, de graça; o modelo
  lê só as linhas que casaram. É o que segura o prefill: ~20 s por leitura de
  1.000 tokens.
- **Teto de contexto acumulado** por sessão. Sem ele, 8 voltas × 3 leituras ×
  200 linhas ≈ 24.000 tokens — o problema antigo, voltando por outro caminho.

Sem shell, sem rede, sem escrita fora do worktree da sessão.

## 8. Medição

A instrumentação de `timings` já existe (prefill × geração × cache). O
Workspace registra em `tmp/workspace/`, separado da Bancada, para não poluir o
"aproveitamento por modelo" dela.

Com o plano na mão, o **tamanho do contexto é conhecido antes de rodar**: a tela
mostra "contexto previsto: 3.400 tokens → prefill ~70 s". É aí que a decisão
de "gasto com leitura ou não" fica visível, em vez de aparecer depois.

O que o painel do Workspace mostra: por sessão, prefill, geração, cache,
leituras feitas, custo do supervisor em US$, e o que saiu do ambiente local.

## 9. O que NÃO muda (Bancada Local)

Nada abaixo é tocado por este plano:

- `scripts/bancada_local.py` — tools, broker, `medir_timings`, `medicoes`;
- `/bancada/*` — endpoints, `_resumo.json`, `registro.jsonl`, painel de medição;
- o contrato da Bancada: o modelo local só propõe, sem aplicar, commitar ou
  implantar;
- o `validar_lote_bancada` do AI Hub, que continua planejando para a Bancada;
- o `local-code` da aba Agentes, que segue como está.

## 10. ADR em rascunho (registrada como ADR 015)

**Decisão.** O Workspace Local passa a executar planos fatiados, com o modelo
local aplicando cada fatia num worktree isolado da sessão e o operador
incorporando. O modelo local ganha três tools de leitura e nenhum acesso a
shell, rede ou escrita fora do worktree. Commit na branch principal, merge e
push permanecem do operador. O plano vem do supervisor (modelo grande) pelo
chat lateral, fatiado em subtasks com objetivo único e gate próprio.

**Alternativas.** (a) Manter o Workspace somente-leitura e executar tudo na
Bancada — preserva o isolamento, mas tira da pessoa o lugar onde ela está. (b)
Dar shell ao modelo local — mais simples, e contra o princípio de que o
modelo não decide o que toca o disco. (c) Aplicar direto na árvore de trabalho
— sem isolamento, e o diff foi gerado contra outro estado.

**Consequências.** O Workspace ganha um contrato de escrita e um caminho de
reversão. A Bancada e o Workspace passam a ter contratos diferentes: a Bancada
propõe, o Workspace aplica. Toda escrita no banco precisa de trilha e
reversão próprias, porque o worktree não a protege.

**O que continua do operador.** Merger, commit na branch principal, push,
escrita no banco e a decisão de começar a sessão.

## 11. Ordem de implementação

| # | Etapa | Entrega | O que mede |
|---|---|---|---|
| 1 | Sessão e worktree | worktree da sessão, branch `workspace/{sessao}`, uma ativa por repo, árvore limpa exigida | nada — é a base |
| 2 | Laço assistido, sem banco | fatia → local → `git apply --check` → aplica → diff ao vivo → gate → próxima, com pausa e `AgentRunEvent` | tempo por etapa, prefill por fatia |
| 3 | Tools de leitura | as 3 tools no local, com teto de contexto acumulado | prefill por leitura |
| 4 | Chat do supervisor no lateral | painel direito com o modelo grande; o `ChatLocal` desce para o centro; editor ganha escrita | custo US$ e tempo do supervisor |
| 5 | Plano fatiado | `plan_granularity.suggest_slices` alimenta o laço; cada fatia com objetivo único e gate próprio | fatias por sessão |
| 6 | Banco | fatia de banco com transação, "antes", reversão e trilha | reverts, falhas por fatia |

Cada etapa entra por branch própria, com o diff entregue para incorporação.

**Estado em 2026-10-25:**

| # | Situação | Branch |
|---|---|---|
| 1 Sessão e worktree | ✅ feito — `workspace_sessao.py`, barra da sessão; estado em JSON + git, sem migration | `feat/workspace-sessao` |
| 2 Laço assistido | ✅ feito — `workspace_execucao.py`, aba Execução; uma fatia por chamada, estado gravado por etapa. Trilha no JSON da sessão (não em `AgentRunEvent`: a sessão não tem `agent_run`) | `feat/workspace-sessao` |
| 3 Tools de leitura | ✅ feito — local e supervisor; o local lê a **cópia da sessão** | `feat/workspace-ferramentas-leitura` |
| 4 Supervisor no lateral + escrita no editor | ✅ feito — editor grava na cópia da sessão e commita com a identidade do operador (decisão 4); Explorer/editor/chat Local leem a cópia | PR #9 + `feat/workspace-sessao` |
| 5 Plano fatiado | ✅ feito pelo "Aprovar plano" (bloco json do supervisor); `suggest_slices` não foi ligado | `feat/workspace-sessao` |
| 6 Banco | ✅ feito — `workspace_banco.py`: fatia `tipo: banco`, simulação com rollback, aplicar com trava e confirmação, reverter com trava; decisões em §6.1 | `feat/workspace-fatias-banco` |
| — Backlog (decisão 6) | ✅ fatias viram subtasks; task `doing`; subtask `done`/`blocked` | `feat/workspace-sessao` |
| — Supervisor vê a sessão (§3.2) | ✅ `ler_estado_sessao` | `feat/workspace-sessao` |

**Fechamento em 2026-10-26** (branch `feat/workspace-supervisor-acoes`, ADR 015):

| Item | Situação |
|---|---|
| Supervisor valida o plano, lê o resultado da fatia e as referências canônicas | ✅ `validar_plano_workspace`, `ler_resultado_fatia`, `ler_referencias` (Observar) |
| Contexto canônico no Workspace | ✅ no prompt do supervisor (redigido); não no modelo local, de propósito |
| Medição (§8) | ✅ `GET /sessao/{id}/medicao`: previsão de prefill por fatia, medido, custo do supervisor |
| Repetição automática | ✅ até 2 vezes, desligável |
| Gate em duas camadas | ✅ testes da área por fatia; suíte completa antes de incorporar |
| Sessões anteriores | ✅ lista e apagar branch com confirmação |
| `suggest_slices` | ⏸ não ligado: `validar_plano` + `validar_plano_workspace` cobrem a validação |

Gate da fatia (decisão 3): roda sempre, mas são os checks fixos do projeto
(`test_gate`), escolhidos pela área tocada — o texto `gate` do supervisor é a
lista que o operador confere, nunca é executado. Ambiente mínimo: sem as
credenciais da API, com `.env` e arquivo de modelos falsos.

Validado com o modelo real em 2026-10-25: fatia "docstring em `_sse`" — 1 leitura,
diff em 18 s, pytest completo dentro da cópia em 73 s, commit no branch da sessão.

## 12. Decisões do operador

**Decididas em 2026-10-25** (Cláudio aceitou as seis recomendações):

1. Supervisor: escolha livre de modelo, com **DeepSeek Flash como padrão**;
   trocar para Luna quando o plano sair ruim.
2. O supervisor **não escreve no banco**: só propõe, o operador confirma.
3. O gate entre fatias roda **sempre**, em toda fatia.
4. A escrita no editor passa pelo worktree da sessão, com a mesma checagem, e
   vira commit — nada grava direto no checkout.
5. Sessão abandonada: worktree e branch **ficam para inspeção**; só são apagados
   por ordem do operador.

6. **Aprovada em 2026-10-25:** o Workspace atualiza o backlog. No "Aprovar plano" as fatias
   viram subtasks da task (nível Planejar), a task vai para `doing` ao começar,
   fatia que passa no gate fecha a subtask e fatia que falha a deixa `blocked`
   com o motivo. Fechar a task continua do operador.

Texto original das perguntas, para referência:


1. O modelo do chat lateral: Luna (padrão do observer), DeepSeek Flash (mais
   barato) ou Qwen via OpenRouter? E o default?
2. O supervisor pode escrever no banco, ou só propor a escrita para o
   operador confirmar?
3. O gate entre fatias roda sempre, ou só em fatias marcadas como críticas?
4. A escrita no editor é livre ou passa pelo mesmo `git apply --check`?
5. O que acontece quando a sessão fica abandonada: o worktree e o branch ficam
   para inspeção, como nos builds?
