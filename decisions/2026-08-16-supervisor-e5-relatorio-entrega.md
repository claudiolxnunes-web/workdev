# ADR — Supervisor E5: o corte que protege o crítico e a entrega que não perde achado

- **Data:** 2026-08-16
- **Status:** aceita, implementada e validada (units criadas, **não habilitadas**)
- **Escopo:** `relatorio.py`, `entrega.py`, units systemd
- **Relacionado:** `docs/supervisor-mvp-plano.md` (seções 6, 9 e 13), ADRs de E1 a E4

## Contexto

E1–E4 apuram, deduplicam, priorizam e explicam. E5 decide o que sai — e é aqui
que o MVP encontra seu risco de produto: um relatório que ninguém termina de
ler é igual a relatório nenhum, e um alerta perdido por falha de rede é pior
que um alerta atrasado.

## Decisão 1 — o limite de três protege a atenção, não a formatação

No máximo três achados detalhados por execução. Um `critical` **nunca** é
rebaixado a linha de excedente para caber no limite.

A exceção é deliberada e assimétrica: é melhor um relatório longo num dia ruim
do que um crítico silenciado por regra de formatação. Na execução real de hoje
isso produziu seis blocos — todos `critical` — e uma linha para os doze
restantes:

```
+12 achado(s) não detalhado(s) (8 high, 2 info, 2 medium)
```

Resolvidos não competem por vaga: viram uma linha própria, porque a informação
útil ali é "sumiu", não o detalhe de como sumiu.

O relatório **não reordena**. A ordem vem pronta da E4 — prioridade do LLM
quando existe, ordem determinística por severidade quando não. Ele decide
profundidade, nunca importância.

## Decisão 2 — falha de entrega não persiste o estado

Esta é a decisão menos óbvia de E5.

O `state.json` registra o que já foi **comunicado**, não o que foi observado.
Se a entrega falhar e o estado for gravado assim mesmo, o achado vira
`persistente` na execução seguinte — e nunca é entregue. Um alerta crítico
desapareceria em silêncio por causa de uma instabilidade de rede.

Então: entrega primeiro, persistência depois, e **se a entrega falhar, o estado
novo não é gravado**. O estado anterior permanece intacto em disco (nada é
apagado), e o achado volta a ser novidade na próxima execução.

O custo é reenvio se a falha se repetir por dias. A uma execução diária, com o
Telegram fora, isso é um item repetido — muito mais barato que um crítico
perdido.

`entrega.deve_persistir(dry_run, resultado)` isola a regra em uma função com
teste próprio, em vez de deixá-la como condição solta no `__main__`.

## Decisão 3 — o token não existe fora do transporte

`ResultadoEntrega.estado` vai direto para as métricas e para o journald, então
carrega só o tipo do erro. A mensagem de uma `URLError` do Telegram contém a
URL inteira — e a URL do Telegram carrega o token no caminho. Guardar
`str(erro)` seria vazar credencial no log a cada falha de rede.

Verificado contra a credencial real, com o transporte substituído:

```
credencial carregada do alerta.env: sim (46 chars)
texto da mensagem      contém token: nao
metrica delivery       contém token: nao
campo erro             contém token: nao
transporte recebeu o token separado do texto: sim
```

A mensagem também vai sem markdown: títulos de task carregam `[`, `]` e `_` à
vontade (`[CRITICAL] IA Gateway: trocar Lovable → provider direto`), e qualquer
modo de formatação transformaria isso em erro de parse ou texto mutilado.

## Decisão 4 — as units existem, mas nada foi habilitado

`workdev-supervisor.service`, `.timer` e `-falhou.service` estão no repositório
e passam por `systemd-analyze verify`. **Nenhum foi copiado para
`/etc/systemd/system`, habilitado ou iniciado** — isso é decisão humana, na
etapa E7 (semana de sombra).

Quatro escolhas dentro das units:

- **`WorkingDirectory=/opt/workdev` é obrigatório**, não estilo:
  `-m scripts.supervisor` resolve o pacote como namespace package a partir da
  raiz do repositório. De outro cwd é `ModuleNotFoundError`.
- **`Environment=HOME=/root`**: serviço systemd não herda o HOME do login, e
  python-dotenv, psycopg e o SDK consultam o diretório do usuário.
- **`flock -n`** contra concorrência: o timer não sobrepõe uma execução lenta, e
  uma chamada manual durante a execução agendada sai na hora em vez de duplicar
  leitura e mensagem.
- **`ProtectSystem=strict` + `ReadWritePaths=/var/lib/workdev-supervisor`**: o
  Nível 0 deixa de depender só do código. Mesmo com um bug, o processo não tem
  permissão de escrever em `/opt/workdev`.

`OnFailure=workdev-supervisor-falhou.service` existe porque, sem ele, o
Supervisor repetiria em si mesmo o defeito que existe para encontrar: falhar e
o silêncio parecer normalidade.

## Validação

```
18 reportáveis  → detailed_findings=6  overflow_findings=12  (6 critical furam o limite)
2ª execução     → new_findings=0  delivery=skipped:sem_novidade  llm_calls=0
--sem-entrega   → delivery=skipped:desativada
sem credencial  → delivery=skipped:sem_credencial   (não é falha)
transporte cai  → delivery=failed:ConnectionError  state_persisted=0  status=degraded
```

Note `llm_calls=0` na segunda execução: sem novidade, não há o que priorizar,
e a chamada não acontece. A deduplicação de E2 economiza o custo de E4.

31 testes novos (9 subtests), cobrindo 0/1/2/3/>3 achados, `critical` nunca
cortado, Telegram indisponível, ausência de spam entre execuções, token não
vazado e as units ainda desabilitadas.

## Estado após E5

Nível 0 mantido: sem ações, sem escrita em banco ou schema, sem tocar backlog,
agentes, RAG ou deploy. Falta E6 (observabilidade completa) e E7 (semana de
sombra, quando o timer é habilitado).
