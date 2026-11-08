# ADR 018 — Patch sem âncora: o Workspace não aplica o que não pode ancorar

Status: accepted (decidido pelo Cláudio em 2026-11-06, “ataca o git apply”);
implementada em `fix/hunk-sem-contexto` (#26), `feat/segunda-camada-semantica`
(#27) e `fix/ancora-hunk-sem-contexto-depois` (#28).

## Contexto

Em 2026-11-04, um exercício do Workspace Local produziu uma mudança **no lugar
errado** — e todas as quatro camadas de verificação deram verde:

| Camada | Por que passou |
|---|---|
| `git apply --check` | aplicava — só que no fim do arquivo |
| `exige` | a string existia, mas em outra função |
| `pytest` | string morta não quebra nada |
| auditoria do observer | leu a *proposta*, não o *resultado* |

O resultado foi um commit em que `criar` continuava **sem docstring** e
`apagar_branch` recebia uma string solta depois do `return`.

A causa é um fato do git que ninguém tinha medido: **um hunk unidiff sem
linhas de contexto não tem âncora**. O git aplica o trecho onde ele consegue
encaixar — no fim do arquivo. Medido em repositório de teste: hunks declarados
nas linhas 10, 50 e 90 de um arquivo de 100 linhas caíram **todos** na linha
101.

E há uma segunda camada, mais sutil: **com contexto, o git ancora pelo
conteúdo** — procura o trecho no arquivo e aplica onde ele casar, ignorando a
posição declarada. E o contexto **depois** da mudança é o que ancora; sem ele,
o git recusa o patch no meio do arquivo e aplica no fim.

## Decisão

1. **`scripts/hunk_validator.py` — nenhum patch é aplicado sem âncora.** Três
   regras, todas verificadas contra o git real:
   - `hunk_sem_contexto` — hunk sem nenhuma linha de contexto;
   - `hunk_sem_ancora` — hunk só de adições, sem contexto **depois** da
     mudança;
   - `hunk_contagem_incoerente` — contagem do cabeçalho `@@` que não fecha
     (aviso, não erro: o `--recount` corrige na aplicação).

   Aplicado em **três** pontos, todos antes de qualquer `git apply`:
   `workspace_execucao.py` (execução da fatia), `scripts/bancada_checks.py`
   (checagem mecânica) e `scripts/bancada_local.py extrair` (patch que o
   operador aplica à mão).

2. **Segunda camada: o código caiu no lugar certo?** — `scripts/verificador_aplicado.py`
   lê o **AST do arquivo já aplicado** e responde o que o `exige` não
   responde: `codigo_morto` (linha nova depois de um `return`),
   `simbolo_em_outro_escopo` (caiu em outra função) e `funcao_nao_alterada` (a
   função pedida não recebeu linha nova). Roda entre o `exige` e o gate, e
   reprova a fatia na etapa `semantica`.

3. **O observer passa a ver o disco.** Recebe o diff que o sistema aplicou e o
   conteúdo do arquivo já alterado, além da proposta — porque era exatamente a
   proposta que o enganava.

4. **O prompt que pede o diff ao modelo local exige contexto** ("3 antes e 3
   depois"), e o `GUIA_PRATICO` ensina o por.

## Alternativas descartadas

- **Deixar o git decidir.** Ele decide — aplica no fim do arquivo, e nada
  denuncia.
- **Só avisar o operador.** Um aviso em log não impede o commit errado.
- **Usar o `context_redaction` da API nos arquivos de sessão.** Ele foi feito
  para o contexto que sai da VPS, onde redigir demais custa nada. Em arquivo
  de sessão o histórico *é* o trabalho do agente — ver ADR 019.
- **Patch só de remoção, sem contexto.** Se ancorar pela remoção, a
  substituição continua ancorando; o problema é a adição pura no fim do
  arquivo.

## Consequências

- Mudança que era **aplicada errado** agora é recusada antes de tocar o disco.
- Três camadas onde havia uma; o preço é um `git apply` a mais por proposta.
- O modelo local erra a âncora em **27%** das propostas com diff (medido em
  2026-11-06) — a taxa que justifica a barreira.
- O `exige` continua sendo necessário: ele verifica *conteúdo*, a nova camada
  verifica *lugar*.

## Verificação

- 1952 testes no gate de pre-deploy (era 1882), incluindo a **reprodução do
  comportamento do git**: contexto antes e depois aplica; só contexto antes,
  no meio do arquivo, não aplica; no fim do arquivo, aplica — e é o bug.
- Confirmado na **release em produção**: importado de
  `/opt/workdev-runtime/current`, o patch real do caso é recusado com o
  arquivo intocado.

Ver também: [ADR 015](015-workspace-local-execucao-assistida.md),
[ADR 019](019-protecao-de-credenciais-dos-agentes.md).
