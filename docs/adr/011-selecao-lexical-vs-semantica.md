# ADR 011 — Seleção de referência: lexical no Build, semântica no AI Hub

Status: proposed no banco (ratificação do Cláudio pendente); implementada em `feat/referencias-canonicas-fase2`.
Registro: `adrs.id = 1cc6ac67-677b-4a68-a825-c44b8554446e`.
Achado que motiva: `docs/AGENT_REFERENCE_CONTEXT_AUDIT.md`, achado Médio #5.

## Contexto

Depois de ADR 010, todo agente recebe referências canônicas — mas o WorkDev
tem hoje **dois mecanismos de seleção diferentes**, e eles não conversam:

1. **Build (worker GPU, Ollama, AUTO, `local-code`)** — seleção **lexical** em
   `build_rag`: sobreposição de tokens entre o vocabulário da task/plano e o
   texto das entradas candidatas. Sem embedding, sem vetor, sem serviço
   externo. Corte de 6 trechos de 1200 caracteres, disputados entre ADR,
   knowledge e decision.
2. **AI Hub (chat/PLAN)** — seleção **semântica** em `rag_search`: consulta
   ao índice pgvector externo (porta 5433), embedding de
   `text-embedding-3-small`, operador `<=>`, limite de 8 a 20 documentos.
   O AI Hub usa o RAG pela ferramenta `buscar_rag` (nível mínimo `observe`).

A seleção lexical tem uma fraqueza conhecida e concreta: **quem não usa as
mesmas palavras fica de fora**. Uma ADR sobre "separação entre PLAN e BUILD"
não entra no prompt de uma task que fala de "roteamento de agent run" — não
há token em comum, e a entrada é descartada. O mesmo vale para o inverso: uma
knowledge sobre "endpoint de health" não é recuperada por uma task que
fala de "sonda de disponibilidade".

A seleção semântica não sofre disso, mas tem outros problemas: depende de um
serviço externo (o índice pgvector), de embedding (custo e latência) e de um
indexador que **não está neste repositório** — o que foi indexado sob a fonte
`workdev` não é verificável aqui.

## Decisão

1. **A seleção do Build continua lexical, nesta fase.** O corte de 6 trechos,
   o teto de 1200 caracteres e a ausência de embedding são contrato
   assumido: o que entra no prompt é texto que dá para ler e auditar depois,
   sem depender de serviço que pode estar fora.
2. **A divergência fica registrada, não escondida.** É uma escolha
   consciente: lexical onde a auditoria importa, semântico onde a cobertura
   importa.
3. **Unificar é trabalho separado e não bloqueia a Fase 2.** O caminho
   natural não é trocar o lexical pelo semântico, e sim **unir os dois**: o
   lexical como piso (sem rede, sem custo, sempre presente) e o semântico
   como complemento, com o `build_rag` função pura e o `rag_search` como
   fonte adicional — com o mesmo teto de trechos e o mesmo teto de caracteres
   valendo para os dois.
4. **A cobertura do índice RAG precisa ser verificável antes disso.** Enquanto
   não se sabe o que está indexado sob `fonte = 'workdev'`, semântico não pode
   ser o critério de completude do contexto do Build.
5. **O AI Hub não muda.** O AI Hub é PLAN, tem contexto curto por desenho
   (`context_engine`, com ADRs como índice de título/status) e a busca
   semântica como ferramenta explícita do modelo. Não é o mesmo problema do
   Build.

## Consequências

- A divergência entre "o que o Build vê" e "o que o AI Hub vê" continua
  existindo, e é explícita: Build = lexical, AI Hub = semântico.
- Um problema concreto permanece: referência canônica relevante escrita com
  vocabulário diferente do da task continua fora do prompt do Build. O
  endpoint `GET /handoffs/runs/{run_id}/references` (ADR 014) dá ao operador
  uma forma de ver o recorte e pedir a referência à mão.
- Nenhuma dependência nova entra no caminho do Build: o corte continua
  funcionando com a VPS offline do RAG.
- Quando a unificação for feita, ela tem que respeitar o teto de trechos e o
  contrato de somente-leitura — não vale substituir o corte por "traz o que
  o vetor trouxer".
