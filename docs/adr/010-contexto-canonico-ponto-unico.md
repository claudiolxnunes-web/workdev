# ADR 010 — Contexto canônico: um único ponto de montagem

Status: accepted (ratificado pelo Cláudio em 2026-10-26); implementada em `feat/referencias-canonicas-fase2`.
Registro: `adrs.id = 7c4a4961-0930-4291-8910-67870a331694`.
Task: auditoria das referências canônicas (Fase 1) → Fase 2.
Achado que motiva: `docs/AGENT_REFERENCE_CONTEXT_AUDIT.md`, achados Alto #1 e Alto #2.

## Contexto

`build_context` já recolhia, para toda run, até 20 ADRs, 20 knowledge e 20
decisions do projeto. `render_agent_prompt` não consome nenhuma dessas três
chaves: o f-string do prompt do executor (plano, task, projeto, subtasks,
roteamento) é montado sem elas. A entrada do contexto canônico no prompt
acontecia em outro lugar — `build_rag.augment_prompt` — e esse lugar era
chamado em **dois dos quatro** caminhos de despacho:

| Caminho | `augment_prompt` | Bloco canônico no prompt |
|---|---|---|
| Worker isolado (GPU) | sim | sim |
| Despacho Ollama | sim | sim |
| AUTO por tmux | **não** | **não** |
| `local-code` | **não** | **não** |

O resultado era falha silenciosa: o agente recebia um plano aprovado e nada
mais — nenhuma ADR do projeto, nenhuma decisão registrada, nenhum knowledge.
Nem evento, nem log, nem status diziam que aquilo era uma escolha; parecia
que o projeto não tinha histórico. Confirmado em runtime: 3 prompts de Build
entregues, 0 blocos "Contexto recuperado" nos transcripts.

Duas causas, e as duas precisavam ser corrigidas:

1. **Não havia um ponto único de montagem.** Cada caminho montava o prompt do
   seu jeito, e a montagem do canônico era um detalhe do `build_rag` — um
   módulo cuja função declarada é *selecionar*, não *entregar*.
2. **Não havia teste na fronteira.** A cobertura provava que o `build_rag`
   selecionava e que o despacho enfileirava. Nenhum teste afirmava que **o
   prompt entregue ao agente** carregava o bloco canônico. A falha podia
   acontecer sem quebrar teste nenhum — e aconteceu.

## Decisão

1. **`canonical_context` é o único ponto de montagem do prompt de agente.**
   `apps/api/app/services/canonical_context.py`. Todo prompt de agente passa
   por `canonical_context.build_prompt` (entrega remota) ou
   `canonical_context.build_local_prompt` (entrega local).
2. **A divisão de responsabilidade fica explícita:**
   - `build_context` — o que existe no banco (consulta);
   - `build_rag` — o que é relevante (seleção e renderização, em texto plano);
   - `canonical_context` — a ordem e o contrato de entrega (montagem);
   - `context_egress` — o que pode sair da máquina (política de egresso).
3. **Os quatro caminhos de despacho usam o mesmo módulo:** worker isolado,
   despacho Ollama, AUTO por tmux e `local-code`.
4. **`build_rag.augment_prompt` sai.** A montagem não é mais responsabilidade
   do módulo de seleção.
5. **O bloco canônico no prompt do executor é decisão, não accidents.** O
   executor recebe as ADRs, knowledge e decisions que casam com o
   vocabulário da task e do plano, marcadas como referência somente-leitura:
   nenhum comando pode ser rodado a partir daquele bloco.
6. **Testes de fronteira, não de função.** Os testes affirmam o prompt
   **na saída de cada caminho**: `tests/test_canonical_context.py` cobre AUTO
   (argumento entregue ao `add_task`), worker isolado (`build_prompt`),
   despacho Ollama (prompt entregue ao consumidor do job) e `local-code`
   (conteúdo do arquivo gravado para o agente).

## Consequências

- O AUTO e o `local-code` passam a receber o mesmo contexto canônico que a
  GPU. A diferença entre os caminhos deixa de existir no plano do conteúdo e
  passa a existir só no transporte e na política de egresso.
- O `local-code` não pode mais ser usado para "ver o prompt cru": o que chega
  ao agente é o prompt montado. Isso é o ponto.
- A seleção continua sendo lexical no Build (ver ADR 011). Unificar a seleção
  com a do AI Hub é trabalho separado, não bloqueio deste.
- O `local-code` passa a gravar no arquivo do prompt um bloco com trechos do
  banco. O arquivo é `0600` e fica no diretório do canal local, como antes.
- Mudança de conteúdo do prompt muda o `prompt_sha256` do job. Registros
  antigos continuam válidos como registro do que foi entregue na época.
- A montagem deixou de ser um detalhe interno de dois módulos: quem precisar
  mudar o formato do prompt do agente muda em um lugar só.
