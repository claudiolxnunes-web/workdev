# ADR 016 — AI Hub: decisões no contexto e listagem dedicada de ADR e decisão

Status: proposed (rascunho local; registro no banco via `POST /api/adrs` pendente)
Branch: `feat/referencias-e-telemetria`
Achado que motiva: `docs/AGENT_REFERENCE_CONTEXT_AUDIT.md`, achado Médio #3.
Pendência que motiva: `docs/AGENT_REFERENCE_CONTEXT_FASE2.md`, item 4 ("Tools de
ADR/decision para o AI Hub").

## Contexto

O AI Hub monta o contexto do projeto em `context_engine.montar_contexto_projeto`.
As três fontes de referência canônica — ADR, knowledge e decision — não entram
da mesma forma:

| Fonte | Onde o AI Hub lia | O que chegava ao modelo |
|---|---|---|
| ADR | `coletar_adrs` | `{titulo, status}` — índice, sem corpo |
| knowledge | `coletar_knowledge` | `{titulo, categoria, tags}` — índice, sem conteúdo |
| decision | **nenhuma** | **nada** |

A tabela `decisions` existe (`app/models/decision.py`), é lida pelo Build
(`build_context`) e pela tool `ler_referencias`, mas o `context_engine` não a
importa. O planejador via os ADRs como índice e nenhuma decisão — mesmo
sabendo que a decisão existe, ele não tinha como saber que existia.

Na outra ponta, a descoberta dependia de uma tool só: `ler_referencias`, que
devolve o **texto integral** (contexto, decisão, consequências, descrição) e
filtra por termo. Para o modelo, a sequência era: adivinhar um termo →
filtrar → receber 3.000 caracteres de texto por referência. Sem termo, a
tool devolve até 10 referências inteiras; com termo errado, não devolve nada.
Faltava o passo do meio — *saber o que existe* antes de *ler o que existe*.

O achado Baixo #1 da auditoria e o item 4 das pendências da Fase 2 apontam
exatamente essa lacuna: "o AI Hub hoje só tem `buscar_conhecimento` e
`buscar_rag`; não há leitura direta de ADR nem de decision".

## Decisão

1. **A `decision` entra no contexto automático do projeto, como índice com
   recorte.** `context_engine.coletar_decisoes` devolve `titulo`, `data` e
   `descricao` truncada em 200 caracteres (`LIMITE_TEXTO_DECISAO`), com limite
   de 5 itens (`LIMITE_DECISOES`), igual às outras coleções. A descrição é um
   resumo: o texto integral continua sendo coisa de `ler_referencias`.
2. **O texto integral de ADR não entra no contexto.** O `context_engine` segue
   como índice (`titulo`, `status`, `data`); quem entrega o corpo é a tool
   `ler_referencias`, que o modelo chama e que tem redação de segredo
   (ADR 012). O contexto automático não redige — e por isso não pode receber
   texto que o operador escreveu ao longo de meses.
3. **Duas tools de listagem, do nível Observar.** `listar_adrs` (título, status,
   data) e `listar_decisoes` (título, data). Sem corpo, sem descrição. São o
   índice que faltava: o modelo descobre o que existe e, se precisar do texto,
   chama `ler_referencias` com `tipo=adr` ou `tipo=decision`.
4. **O bloco de referências tem teto próprio.** `LIMITE_BLOCO_REFERENCIAS`
   (4.000 caracteres) limita o bloco de ADRs + decisões que entra no system
   prompt, e o corte é marcado (`referências truncadas no teto de …`), nunca
   silencioso. O bloco compete com a conversa pelo mesmo orçamento de tokens.
5. **A lista de ADR e a de decisão são sustentadas pelo gate de autoridade.**
   `autoridade.NIVEL_POR_TOOL` classifica as duas como `observe`: são leitura,
   como `ler_referencias`. Tool sem classificação é negada por definição.
6. **O escopo global não muda.** `decisions` é por projeto; o contexto global
   continua sem ADRs e sem decisões.

## Opções

1. **Só a coleta no `context_engine`, sem tools.** Mais simples, e resolve a
   metade "o modelo não sabe que a decisão existe". Deixava de fora a
   descoberta sob demanda: quando o contexto está truncado, ou quando a
   pergunta é sobre um ADR específico, o modelo continuaria sem porta de
   entrada própria.
2. **Subir o limite de ADR/knowledge no `context_engine` (5 → 20).** A auditoria
   sugeria isso. Rejeitado: 20 ADRs com título e status já são ~5 KB só de
   índice, e o modelo passa a ver referências que não têm relação com a
   pergunta. O limite curto com lista dedicada é mais barato que o limite
   largo.
3. **Entregar o corpo no contexto automático.** Rejeitado: o contexto
   automático não passa pela redação de segredo (`context_redaction`), e o
   corpo de ADR é justamente o texto onde o operador cola chave
   (ADR 012). `ler_referencias` redige antes de devolver.
4. **Uma tool só (`listar_referencias` com `tipo`).** Rejeitado: `ler_referencias`
   já existe com essa forma e devolve o texto. Uma tool de listagem separada
   serve a outro contrato — devolver índice, sem texto — e deixa o modelo
   escolher quando quer o detalhe.

## Consequências

- O planejador passa a saber que o projeto tem decisões registradas, sem que
  o contexto carregue o texto delas.
- O modelo ganha descoberta explícita de ADR e de decisão, no nível Observar —
  o mesmo em que já lê `ler_referencias`.
- O `context_engine` ganha uma dependência nova (`Decision`) e três constantes
  de limite. Nenhuma migration: `decisions` já existe no banco.
- O teste que fixa o conjunto de tools do nível Observar
  (`test_authority_gate.py::test_observe_so_tem_leitura`) e a contagem do
  catálogo por provider mudaram — é o contrato que acompanha o gate.
- A pendência 4 da Fase 2 ("tools de ADR/decision para o AI Hub") fica
  respondida por estas duas tools; a pendência 5 (registrar as ADRs da fase no
  banco) continua aberta e não é tocada aqui.
- O ADR 011 ("Seleção de referência: lexical no Build, semântica no AI Hub")
  continua valendo: esta mudança não mexe na seleção, e o AI Hub continua com
  contexto curto por desenho — o que muda é que o índice agora cobre também as
  decisões e que existe uma porta de entrada explícita para o texto.
