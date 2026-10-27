# ADR 012 — A política de segredo vale também para a entrega local

Status: accepted (ratificado pelo Cláudio em 2026-10-26); implementada em `feat/referencias-canonicas-fase2`.
Registro: `adrs.id = 09d2df7b-186b-4a22-9fbc-17cd8caf68c0`.
Achado que motiva: `docs/AGENT_REFERENCE_CONTEXT_AUDIT.md`, achado Alto #3.

## Contexto

`context_egress` define três regras: projeto `restricted` nunca sai; runtime
remoto exige consentimento por run; runtime remoto sempre passa por
redaction. O loopback (`local-code`, runtime de `kind != gpu`) era isento das
três, com o comentário literal "nada deixa a máquina, nada a redigir nem a
consentir".

O argumento do texto não sai da máquina é verdadeiro e não é suficiente. O
prompt do loopback **chega a um modelo**: o `local-code` é uma CLI que fala
com o llama.cpp na própria VPS, e o AUTO por tmux é uma CLI que fala com um
provedor externo. E o conteúdo do contexto canônico é, por construção, o
texto que o operador escreveu ao longo de meses — o material onde mais
provavelmente existe uma chave colada num troubleshooting. A própria
docstring do `context_redaction` diz isso: *"O prompt de Build carrega ADRs,
knowledge e decisions — texto que o operador escreveu ao longo de meses e que
perfeitamente pode conter uma chave colada num troubleshooting."*

Ou seja: a mesma justificativa que motivou a redaction no caminho remoto
motivava a ausência dela no caminho local. E como a Fase 2 passou a injetar
contexto canônico no AUTO e no `local-code` (ADR 010), a lacuna passaria a
ser maior, não menor.

O custo de redigir é real: um trecho de contexto some quando ele casa com
padrão de segredo. A resposta da política é "fail-safe, não fail-clever: na
dúvida, redige" — o que já vale no remoto.

## Decisão

1. **A redaction vale nos dois sentidos.** `context_egress.prepare` redige
   também no loopback, e a entrega local (`canonical_context.build_local_prompt`)
   aplica a mesma `context_redaction.redact`.
2. **O que muda no loopback é apenas o consentimento**, que continua
   exclusive do egresso: não há egresso para consentir.
3. **A contagem é registrada.** A entrega local que remove algo gera o evento
   `build.context_redacted`, com a mesma contagem por tipo e a mesma regra de
   nunca registrar o valor achado.
4. **O texto redigido continua legível.** A política preserva o nome da
   variável (`DATABASE_PASSWORD=[REDACTED:assigned_secret]`) — perder o nome
   tornaria o contexto inútil para o modelo.
5. **A redação é aplicada uma vez por prompt.** No caminho remoto, quem
   redige é o `context_egress`, que precisa contar; a montagem não redige
   (senão a contagem do evento seria zero). No caminho local, quem redige é a
   própria montagem. A implementação é a mesma função nos dois lados.
6. **O endpoint de referências (ADR 014) também entrega texto redigido**,
   porque o destino é o terminal do operador.

## Consequências

- Uma chave de verdade colada num ADR deixa de chegar ao modelo, inclusive
  no caminho local. O contexto perde esse trecho, e o operador recebe a
  contagem do que foi retirado.
- O teste que fixava "loopback não redige" foi invertido: hoje se garante
  que o loopback redige e que texto limpo sai intacto.
- `EgressDecision.redaction` deixa de ser `None` no loopback. Quem consome
  esse campo para decidir "houve redaction?" passa a ver a verdade.
- O `local-code` grava no arquivo de prompt o texto já redigido: o arquivo
  `0600` deixa de ser um lugar onde uma chave vive em claro.
- Um texto que **parece** segredo é redigido mesmo sendo innocent — a
  política é fail-safe. É o preço Known do fail-safe, e o mesmo preço já
  pago no remoto.
