# ADR 015 — O Workspace Local executa planos fatiados; a Bancada continua só propondo

Status: proposed (aguarda ratificação do Cláudio).
Plano de origem: `docs/planning/workspace-local-execucao-assistida.md` (o rascunho
dele se chamava "ADR 010"; o número foi tomado pela ADR do contexto canônico).

## Contexto

O modelo local (Qwen3.8 35B A3B MoE) roda na CPU: cada 1.000 tokens de prompt
custam ~20 s de prefill. Pelas CLIs com harness (22–30 mil tokens antes de
qualquer trabalho), ele leva de 7 a 10 minutos para começar. Na Bancada ele
responde rápido porque recebe 1–3 mil tokens, mas só propõe: aplicar, testar e
commitar ficava à mão do operador.

O operador quer trabalhar com o modelo local onde já está, no Workspace, com um
modelo grande supervisionando ao lado, como o chat do Copilot no VS Code.

## Decisão

1. **O Workspace aplica; a Bancada propõe.** No Workspace, cada fatia de um
   plano aprovado é aplicada pelo sistema numa cópia isolada (worktree) da
   sessão, passa pelo gate e vira commit no branch `workspace/<sessão>`. A
   Bancada, o `validar_lote_bancada` e o `local-code` não mudam.
2. **O modelo local não tem shell, rede nem escrita.** Ele tem só as leituras
   (`buscar_texto`, `listar_pasta`, `ler_arquivo`) da cópia da sessão, com teto
   de contexto acumulado. Quem aplica o diff é o sistema, com `git apply --check`.
3. **O supervisor (modelo grande, lateral direita) só lê.** Suas ferramentas do
   Workspace são `ler_estado_sessao`, `validar_plano_workspace`,
   `ler_resultado_fatia` e `ler_referencias`, todas no nível Observar. O plano
   que ele entrega vira cartão; aprovar, executar, aplicar no banco e incorporar
   são botões do operador.
4. **Referências canônicas vão ao supervisor, não ao modelo local.** O prompt de
   abertura do supervisor recebe o bloco de ADR/knowledge/decision
   (`canonical_context.planning_block`, redigido). O modelo local não recebe:
   seriam até ~2 mil tokens (~40 s) a mais em toda fatia. Cabe ao supervisor
   escrever na instrução da fatia a restrição que importa.
5. **Gate em duas camadas.** Cada fatia roda os checks fixos do projeto pela
   área tocada, com o pytest limitado aos testes que casam pelo nome do módulo
   (sem correspondência, a suíte inteira). Antes de incorporar roda a suíte
   completa sobre tudo que a sessão mudou; reprovada, nada é incorporado.
6. **Falha repete sozinha até 2 vezes**, com o erro anterior no contexto. Depois
   para e espera o operador. Desligável no painel.
7. **Banco fica fora da proteção do worktree.** Fatia de banco simula com
   rollback, guarda o "antes", grava só com confirmação do operador e tem
   reversão (ver §6 do plano).
8. **Sessão encerrada deixa o branch para inspeção.** Apagar o branch é ordem do
   operador, com aviso explícito quando há commit não incorporado.

## Alternativas consideradas

- **Manter o Workspace só leitura e executar tudo na Bancada.** Preserva o
  isolamento, mas tira o operador do lugar onde ele trabalha.
- **Dar shell ao modelo local.** Mais simples, e contra o princípio de que o
  modelo não decide o que toca o disco.
- **Aplicar direto no checkout.** Sem isolamento, e o diff seria gerado contra
  um estado que pode não ser o do operador.
- **Deixar o supervisor aprovar e executar.** Tira o operador do laço; a decisão
  de 2026-10-25 é que o supervisor só propõe.
- **Mandar o bloco canônico também ao modelo local.** Mais contexto ao executor,
  ao custo de prefill em toda fatia.

## Consequências

- Bancada e Workspace passam a ter contratos diferentes. O guia
  (`docs/bancada-local/GUIA_PRATICO.md`) diz qual usar.
- O Workspace grava estado em JSON + git (`/opt/workdev-builds/workspace`), sem
  migration: a sessão não tem `agent_run`, então a trilha fica no JSON da
  sessão, não em `AgentRunEvent`.
- O custo do supervisor vem do `ai_call_logs` da conversa; o do modelo local,
  da medição de `timings` do llama-server. Os dois aparecem no painel Execução.
- Incorporar fica mais lento (suíte completa), em troca de as fatias ficarem
  mais rápidas.

## O que continua do operador

Começar a sessão, aprovar o plano, executar, aplicar e reverter no banco,
incorporar, apagar branch, commitar no branch principal, push e deploy.
