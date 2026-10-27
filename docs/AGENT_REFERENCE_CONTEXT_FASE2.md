# Fase 2 — Referências canônicas nos agentes do WorkDev

Documento de implementação da Fase 2, aberta pela auditoria
(`docs/AGENT_REFERENCE_CONTEXT_AUDIT.md`, FASE 1) e pelas decisões registradas
em `docs/adr/010` a `docs/adr/014`.

> Status: implementada em `feat/referencias-canonicas-fase2`, com a suíte
> completa do backend verde (1778 passed, 28 skipped).

## O problema, em uma linha

O WorkDev recolhia ADR, knowledge e decisions para toda run, mas o bloco
canônico só entrava no prompt em **dois dos quatro** caminhos de despacho. O
AUTO por tmux e o `local-code` entregavam um plano aprovado e mais nada — sem
ADR, sem decisão, sem knowledge — e nada no log, no evento ou no status dizia
que aquilo era uma escolha.

## O que mudou

| Caminho | Antes | Agora |
|---|---|---|
| Worker isolado (GPU) | bloco canônico | bloco canônico (mesmo módulo) |
| Despacho Ollama | bloco canônico | bloco canônico (mesmo módulo) |
| **AUTO por tmux** | **sem canônico** | **com canônico, redigido** |
| **`local-code`** | **sem canônico** | **com canônico, redigido** |

E o `adaptive_ai` (observer/JEV), que descartava o texto redigido devolvido
pela guarda de egresso e enviava o payload original — redaction que só existia
no papel — passou a enviar o texto redigido.

## A peça nova: `canonical_context`

`apps/api/app/services/canonical_context.py` é o **único** ponto de montagem
do prompt de agente. Antes, a montagem do canônico era detalhe do `build_rag`
— um módulo cuja função declarada é *selecionar* — e por isso cada caminho
montava o prompt do seu jeito.

A divisão de responsabilidade fica explícita:

```
build_context      →  o que existe no banco (consulta)
build_rag          →  o que é relevante (seleção e renderização, texto plano)
canonical_context  →  a ordem e o contrato de entrega (montagem)
context_egress     →  o que pode sair da máquina (política de egresso)
```

Duas portas, porque a política de egresso difere nos dois casos:

- `canonical_context.build_prompt` — entrega remota. **Não redige**: quem
  redige é o `context_egress.prepare`, que precisa contar o que retirou para
  registrar na trilha da run.
- `canonical_context.build_local_prompt` — entrega local (AUTO, `local-code`).
  **Redige**: o texto não sai da VPS, mas chega a um modelo, e o contexto
  canônico é o texto que o operador escreveu ao longo de meses.

`build_rag.augment_prompt` saiu: a montagem não é mais responsabilidade do
módulo de seleção.

## Arquivos tocados

| Arquivo | Mudança |
|---|---|
| `app/services/canonical_context.py` | **novo** — ponto único de montagem |
| `app/services/build_rag.py` | `augment_prompt` removido; docstring ajustada |
| `app/services/build_worker.py` | usa `canonical_context.build_prompt` |
| `app/services/local_code_build.py` | usa `canonical_context.build_local_prompt` |
| `app/routers/handoffs.py` | AUTO e `POST /start` usam a montagem local; despacho Ollama usa a remota; **novo** `GET /runs/{run_id}/references` |
| `app/services/context_egress.py` | redaction também no loopback |
| `app/services/adaptive_ai.py` | envia o payload redigido, não o original |

## A política de segredo, dos dois lados

O `context_egress` tinha três regras, e o loopback era isento das três com o
comentário "nada deixa a máquina, nada a redigir nem a consentir". O texto não
sair da máquina é verdade e não basta: o prompt **chega a um modelo**, e o
conteúdo do contexto canônico é justamente onde uma chave colada num
troubleshooting tem mais chance de estar.

Agora a redaction vale dos dois lados; o consentimento continua exclusivo do
egresso (não há egresso para consentir). A entrega local que remove algo
gera o evento `build.context_redacted`, com contagem por tipo e sem o valor
achado. Ver ADR 012.

## O agente manual da tmux

A sessão conduzida por pessoa não tem montagem de prompt — o backend não
escreve o que o operador digita, e continua assim. O que mudou é que existe
uma porta de consulta:

```
GET /handoffs/runs/{run_id}/references
  → {run_id, snippets: [{source, id, title, text, score}], block}
```

O `block` é exatamente o texto que o Build recebe, e os `snippets` são as
entradas selecionadas com a mesma seleção do Build. O texto sai **redigido**,
porque o destino é o terminal. A integração na `AgentTerminal.tsx` (um botão
"trazer referências desta run") é a pendência nomeada da ADR 014.

## O que NÃO mudou (e onde está registrado)

- **O revisor** continua com escopo mínimo, sem ADR, knowledge e decisions.
  É desenho, não defeito: o revisor julga a mudança, e o pacote mínimo é o
  que mantém a revisão barata e comparável. A assimetria é nomeada e tem
  gatilho de reavaliação. Ver ADR 013.
- **A seleção continua lexical no Build** (sobreposição de tokens) e
  semântica no AI Hub (pgvector). A unificação é trabalho separado, com o
  lexical como piso e o semântico como complemento. Ver ADR 011.
- **O AI Hub não muda.** É PLAN, tem contexto curto por desenho, e a busca
  semântica é ferramenta explícita do modelo.
- **O `local-code` não pode mais ser usado para ver o prompt cru.** O que
  chega ao agente é o prompt montado — que é o ponto da mudança.

## Cobertura de fronteira

O achado central da auditoria foi que a cobertura parava no limite da função:
o `build_rag` tinha teste, o despacho tinha teste, e nada afirmava que **o
prompt entregue ao agente** carregava o bloco canônico. Por isso a falha podia
acontecer sem quebrar teste nenhum.

`apps/api/tests/test_canonical_context.py` afirma o prompt **na saída de cada
caminho**:

- AUTO — o prompt entregue ao `add_task` (o que o agente recebe);
- worker isolado — o prompt de `build_prompt`;
- despacho Ollama — o prompt entregue ao consumidor do job;
- `local-code` — o **conteúdo do arquivo gravado** para o agente;
- `GET /references` — o bloco e os snippets devolvidos;
- redaction local — o segredo sai, o nome da variável fica.

O teste do `adaptive_ai` afirma que o payload enviado ao provedor é o
redigido (e falha se a correção for desfeita).

## Como verificar

```bash
printf 'DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/fake\n' > /tmp/test.env
cd /opt/workdev/apps/api
WORKDEV_API_ENV_FILE=/tmp/test.env venv/bin/python -m pytest tests/ -q
```

Rodar como `workdev` (o `apps/api/.env` real é root e tem a credencial de
produção — teste não usa). Ver CLAUDE.md.

## Pendências que sobraram (não feitas aqui, de propósito)

1. **UI da referência manual** — botão na `AgentTerminal.tsx` (ADR 014).
2. **Unificar a seleção** — lexical + semântico, com teto de trechos e
   contrato de somente-leitura preservados (ADR 011).
3. **Cobertura do índice RAG** — o indexador não está neste repositório; o
   que está indexado sob `fonte = 'workdev'` continua não verificável aqui.
4. **Tools de ADR/decision para o AI Hub** — o AI Hub hoje só tem
   `buscar_conhecimento` e `buscar_rag`; não há leitura direta de ADR nem de
   decision (achado Baixo #1 da auditoria).
5. **ADR 013 no banco** — as ADRs desta fase precisam ser registradas em
   `adrs` (status `proposed`) para que o AI Hub as veja como referência.
