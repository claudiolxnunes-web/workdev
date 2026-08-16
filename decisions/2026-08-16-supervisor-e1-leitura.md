# ADR — Supervisor E1: somente-leitura imposto pelo servidor e checks sem banco

- **Data:** 2026-08-16
- **Status:** aceita, implementada
- **Escopo:** `scripts/supervisor/` (etapa E1 do plano)
- **Relacionado:** `docs/supervisor-mvp-plano.md`

## Contexto

O MVP do WorkDev Supervisor é de Nível 0: lê, correlaciona e recomenda, sem
alterar nada. "Somente leitura" é a propriedade que sustenta todo o resto do
desenho — é ela que torna o rollback trivial e que permite rodar o supervisor
contra produção sem gate de aprovação.

O problema é que "somente leitura por disciplina de código" não é uma
propriedade: é uma promessa. Um check futuro mal escrito, um `psycopg` com
autocommit e um `UPDATE` de teste esquecido bastam para quebrá-la, e nada no
sistema avisaria.

Três decisões desta etapa merecem registro.

## Decisão 1 — a recusa de escrita é do Postgres, não do Python

A conexão abre com `options="-c default_transaction_read_only=on"`. Qualquer
`INSERT`/`UPDATE`/`DELETE`/`CREATE` é recusado pelo servidor com
`ReadOnlySqlTransaction`, independentemente do que o código tente fazer.

Verificado, não presumido:

```
psycopg.errors.ReadOnlySqlTransaction:
  cannot execute CREATE TABLE in a read-only transaction
```

Há teste de integração (`test_supervisor_leitura.SomenteLeituraTest`) que tenta
`CREATE TEMP TABLE`, `UPDATE` e `DELETE` e exige a exceção nos três casos. Se
alguém trocar a conexão por uma comum, a suíte quebra.

Descartado por ora: role `workdev_supervisor` com `GRANT SELECT` restrito.
É a defesa mais forte, mas é alteração de banco e exige aprovação explícita —
fica como item separado. O `default_transaction_read_only` já é a defesa
efetiva contra a classe de erro que realmente preocupa (bug no supervisor).

## Decisão 2 — `coletar` conhece SQL, `avaliar` não conhece nada

Cada check expõe duas funções:

    coletar(leitor, agora) -> list[Fato]   # consulta e delega
    avaliar(linhas, agora) -> list[Fato]   # lógica pura, sem I/O

Limiares, normalização de prioridade, severidade e bucket vivem em `avaliar`,
que recebe uma lista de dicionários. Consequência prática: 36 testes rodam em
0,19 s sem banco, cobrindo limiar exato, prioridade suja, escalonamento e
estabilidade de fingerprint. Só duas classes de teste precisam de Postgres, e
elas se pulam sozinhas quando ele não está disponível.

O SQL faz filtro grosso (a menor janela configurada); o limiar por prioridade
é aplicado em Python. Um SQL que já decidisse tudo seria mais eficiente e
praticamente não testável.

## Decisão 3 — `ACTIVE_RUN_STATUSES` é espelhado, não importado

O plano previa importar a constante de `app/services/handoff.py` para não
duplicar a máquina de estados. Na prática isso não é seguro: `app.database`
chama `create_engine(DATABASE_URL)` no momento da importação e faz
`load_dotenv()` sem caminho, ou seja, depende do cwd. Importar `handoff` de um
processo rodado por systemd criaria um engine — ou levantaria exceção — como
efeito colateral de um `import`.

A constante foi copiada para `supervisor/config.py`, e a divergência silenciosa
é impedida por um teste que lê `handoff.py` com `ast` e compara os conjuntos.
Cópia com detector de divergência, em vez de acoplamento com efeito colateral.

## Consequência não prevista: o filtro que evitava 50% de falso positivo evitava 100%

O plano registrou que `plan_without_execution` precisa de `b.status <> 'done'`
porque "dos 2 planos aprovados sem run, um pertence a uma task já concluída".
A verificação contra o banco mostrou que **os dois** pertencem a tasks `done`:

| Plano | Aprovado | Status da task |
| --- | --- | --- |
| Adicionar provider Ollama Cloud ao AI Hub | 2026-07-21 | `done` |
| Configuração Final da Plataforma | 2026-08-01 | `done` |

Sem o filtro, o subcheck `never_dispatched` nasceria com 100% de falso
positivo. Com ele, retorna zero — e o zero está correto, não é bug.

Isso reforça a regra de trabalho: um check que retorna vazio precisa ser
confirmado contra os dados brutos antes de ser considerado pronto. Vazio por
filtro correto e vazio por query errada são indistinguíveis pela saída.

## Estado após E1

11 fatos reais na primeira execução (0,03 s): 6 tasks `critical` paradas entre
10 e 20 dias, 4 `high` entre 29 e 34 dias, 1 execução do codex travada em
`blocked` há 10 dias.

Ainda **não** existem: deduplicação, estado em disco, LLM e entrega. A ordem
E2 (deduplicação) antes de E5 (entrega) é deliberada — notificar antes de
deduplicar transformaria a primeira semana num despejo diário dos mesmos 11
itens.
