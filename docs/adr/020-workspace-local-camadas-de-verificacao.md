# ADR 020 — Workspace Local: o modelo propõe, o sistema verifica, a pessoa decide

Status: accepted (decidido pelo Cláudio em 2026-10-27, #25; complementado em
2026-11-06 por #26, #27 e #28). Contrato-base:
[ADR 015](015-workspace-local-execucao-assistida.md).

## Contexto

O Workspace Local deixa o modelo local executar uma tarefa de verdade: ele lê
o repositório, produz um patch, e o sistema aplica, verifica e cria o commit.

O primeiro exercício de prática (2026-11-04) mostrou que **a qualidade da
execução não depende só do modelo**. Depende de quantas camadas verificam,
independentemente, o que ele fez.

O caso concreto: uma docstring que deveria documentar a função `criar` foi
parar **depois do `return` de outra função**. Quatro camadas deram verde
(`git apply --check`, `exige`, `pytest`, auditoria do observer). O commit
entrou em produção com a mudança no lugar errado.

A causa não era o modelo — era que **cada camada verificava uma coisa
diferente, e nenhuma verificava a coisa que importa**:

- `git apply --check` verificava que o patch *aplica*, não que aplica *no
  lugar certo*;
- `exige` verificava que o código pedido *existe*, não que está *onde foi
  pedido*;
- `pytest` verificava que nada *quebrou*, e código morto não quebra nada;
- o observer verificava a *proposta*, não o *resultado*.

## Decisão

O Workspace Local tem **quatro camadas**, e a ordem é deliberada — do mais
barato e determinístico ao mais caro e subjetivo:

| # | Camada | Pergunta | Custo |
|---|---|---|---|
| 1 | `aplicar` | o patch tem **ânncora**? | AST/sqrt, instantâneo |
| 2 | `exige` | o código pedido está presente? | regex, instantâneo |
| 3 | `semantica` | o código caiu **no lugar certo**? | AST do arquivo aplicado |
| 4 | `gate` | os testes da área passam? | pytest/vitest/lint/build |

E depois do gate, o **observer** — que julga o *sentido* da mudança, com LLM,
e só pode reprovar por parecer, nunca por falha.

Três decisões que daí decorrem:

1. **As camadas mecânicas reprovam; o observer orienta.** O observer dá
   `aproveitada`, `correcao_pequena` ou `descartada`. A falha do observer
   **não** reprova a fatia — um observer fora do ar não pode travar o trabalho
   do agente local.

2. **O observer vê o disco, não só a proposta.** Recebe o diff que o sistema
   aplicou e o conteúdo do arquivo já alterado. Era exatamente a proposta que
   o enganava.

3. **Repetição automática com limite.** Até 2 novas tentativas com o erro
   anterior; depois disso, a execução para e aguarda a pessoa.

### O que a experiência ensinou sobre o modelo local

Medido com o Qwen3.8 35B A3B (ver
[relatório](bancada-local/relatorio-qwen35b-2026-11.md)):

- **38% de aproveitamento** nos pareceres — o modelo propõe, a pessoa decide;
- **27%** das propostas com diff são recusadas por falta de âncora;
- **~65 tok/s** de prefill, **~14 tok/s** de geração, **89% mais rápido** com
  cache de prefixo;
- function calling funciona (é o que permite “ler o repo”).

É um **executor de patch pequeno e rápido**, não um programador autônomo. As
camadas não são desconfiança do modelo — são o que torna o modelo local
usável em produção.

## Alternativas descartadas

- **Confiar no observer.** Ele leu a proposta, aprovou, e o resultado estava
  errado. Um LLM que julga texto não substitui uma verificação determinística
  sobre o arquivo.
- **Deixar o gate decidir tudo.** O gate roda depois da aplicação — quando o
  patch já mudou o arquivo. As camadas 1 e 3 são *antes*.
- **Uma camada só, com LLM.** Caro, não determinístico, e não cobre o que o
  `git` faz de silencioso.
- **Exigir revisão humana de cada patch.** inviável para o volume; a revisão
  humana fica onde ela vale — no *incorporar* e no *deploy*.

## Consequências

- Mudança aplicada no lugar errado é **recusada antes de tocar o disco**.
- O Workspace tem uma **etapa nova** (`semantica`) no fluxo — a UI mostra os
  achados.
- O modelo local erra a âncora em 27% das vezes: a taxa que justifica a
  barreira, e que o prompt (“diff com 3 linhas de contexto antes e depois”)
  reduz.
- Cada camada é testada isoladamente, com a **reprodução do comportamento do
  git** — não com a expectativa sobre o git.

## Verificação

- 1952 testes no gate de pre-deploy (era 1882 na origem).
- Confirmado na **release em produção**: o caso real é recusado, com o
  arquivo intocado.
- Exercício real automatizado (2026-11-06): docstring na função pedida →
  passou, commit; função nova no fim do arquivo → reprovada em `aplicar`,
  com `hunk_sem_ancora`.

Ver também: [ADR 018](018-patch-sem-ancora.md) — a regra do git que motivou a
primeira camada.
