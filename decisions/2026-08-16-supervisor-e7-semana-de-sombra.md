# ADR — Supervisor E7: instalação em sombra e o drift que o próprio check não vê

- **Data:** 2026-08-16
- **Status:** aceita, em execução (sombra até 23/08/2026)
- **Escopo:** units em `/etc/systemd/system`, estado em `/var/lib/workdev-supervisor`
- **Relacionado:** `docs/supervisor-mvp-plano.md` (seções 9 e 15), ADRs de E1 a E6

## O que foi instalado

`workdev-supervisor.service`, `.timer` e `-falhou.service` copiados para
`/etc/systemd/system`, `daemon-reload`, e o timer habilitado:

```
workdev-supervisor.timer    enabled / active (waiting)
próximo disparo             diário, 10:00 UTC (07:00 America/Sao_Paulo)
workdev-supervisor.service  disabled — quem agenda é o timer (TriggeredBy)
```

O service ficar `disabled` é correto e não acidental: habilitá-lo faria o
Supervisor rodar no boot, fora da janela pretendida. Um teste passou a cobrar
essa distinção.

## Decisão 1 — o resíduo de teste foi arquivado, não apagado

O primeiro `--seed` partiu de um diretório que já tinha **7 execuções de
teste** de E4 e E5, rodadas sem `--estado-dir`. O estado herdado tinha 20
achados, um deles já marcado `resolvido`, e linhas de `runs.jsonl` anteriores a
E5 — sem o campo `delivery`. A semana de sombra mediria ruído contaminado, e o
número que decide se o MVP continua existindo sairia errado.

O material foi **movido** para
`/var/lib/workdev-supervisor/pre-sombra-20260816-190041/`, não removido, e o
seed refeito do zero:

```
17 achados, todos persistentes, resolved=0, reportable_findings=0
por severidade: 6 critical, 8 high, 2 medium, 1 info
```

São 17 e não 18 porque a árvore ficou limpa após o commit de E6 e o
`uncommitted_work` deixou de existir.

## Decisão 2 — a entrega fica suprimida por drop-in, e o drop-in é versionado

A unit não tem `--sem-entrega`; a supressão veio de um drop-in
(`shadow.conf`), que é a forma correta — o arquivo base continua idêntico ao
versionado.

O problema é que **`deploy_drift` não inspeciona drop-ins de systemd**. Uma
configuração que existisse só em `/etc/systemd/system` sumiria com a máquina
sem ninguém detectar, e a semana seguinte começaria a mandar Telegram sem
que ninguém tivesse decidido isso.

Duas medidas:

1. `scripts/workdev-supervisor-sombra.conf` versiona o drop-in, com o porquê e
   os comandos de instalar e remover.
2. Dois testes comparam o que roda com o que está no repositório —
   `test_unit_instalada_nao_divergiu_do_repositorio` e
   `test_drop_in_de_sombra_nao_divergiu_do_repositorio`. Eles se pulam onde as
   units não estão instaladas (dev, CI) e falham onde divergirem.

É a rede que o `deploy_drift` não oferece. Ampliar o check para ler
`/etc/systemd/system/**/*.d/*.conf` fica registrado como possível melhoria,
fora do escopo do MVP.

## Decisão 3 — o teste do timer virou verificação de coerência

`test_timer_continua_desabilitado` nasceu em E5 para impedir que o timer fosse
habilitado antes da hora. E7 habilitou — que era o objetivo — e o teste passou
a cobrar um estado que já não existe. Ficou vermelho por estar certo sobre o
passado.

Reescrito como `test_instalacao_do_timer_e_coerente`, que verifica uma regra
válida nos dois mundos: o pacote pode não estar instalado; se estiver, o timer
é `enabled` e o service **não** é habilitado direto.

A lição vale além deste caso: teste que fixa um estado transitório de projeto
vira dívida no dia em que o projeto avança. O que dura é a invariante.

## O que a sombra vai medir, até 23/08

Uma execução por dia. Ao fim, `runs.jsonl` responde com números, não com
impressão: achados novos, persistentes, agravados, resolvidos, falhas de LLM,
falhas de entrega e custo diário. Falsos positivos e ruído percebido são
julgamento humano e não saem do log.

O critério de desligamento continua o do plano, e está comentado em
`config.py`: se em 3 semanas não houver **1 achado novo e útil por semana**,
desligar ou redesenhar.

## Datas previsíveis

- **17/08, 10:04 UTC** — primeira execução agendada.
- **30/08** — os 6 críticos semeados hoje completam 14 dias e voltam juntos
  pelo reforço (`REFORCO_DIAS`), numa única mensagem com 6 blocos, já que
  `critical` fura o limite de 3. É comportamento aprovado em E5; a data é
  consequência aritmética da semeadura.

## Nível 0 mantido

Nenhuma ação sobre backlog, banco, schema, agentes, RAG ou deploy. A única
escrita do Supervisor continua sendo `/var/lib/workdev-supervisor`, garantida
pelo `ProtectSystem=strict` + `ReadWritePaths` da unit.
