# EXCEPTION WHEN OTHERS em migrations engole falha estrutural

**Data:** 2026-08-15
**Status:** aceita
**Projetos afetados:** Feed_BPF (confirmado), Agro RC, Audits_BPF, AgroGestão (a auditar)

## Contexto

O `process-email-queue` do Feed_BPF ficou quebrado por semanas. O sintoma inicial
era um cron ausente; a investigação mostrou uma cadeia mais funda:

1. O cron não existia — mas criá-lo só trocou o erro de lugar.
2. A função retornava 500 por falta de `LOVABLE_API_KEY`.
3. Abaixo disso, o schema `pgmq` não existia no projeto `xgvapaebustyotrwnzqa`.
4. As 4 funções (`enqueue_email`, `read_email_batch`, `delete_email`,
   `move_to_dlq`) e as 2 tabelas existiam normalmente. **Só as filas faltavam.**

A migration `20260427132427_email_infra.sql` cria as filas assim:

```sql
DO $$ BEGIN PERFORM pgmq.create('auth_emails'); EXCEPTION WHEN OTHERS THEN NULL; END $$;
```

O comentário acima do bloco diz que é para tratar "queue already exists" de forma
idempotente. Mas `WHEN OTHERS` captura **qualquer** exceção — inclusive
`schema "pgmq" does not exist`. A migration reportou sucesso e o banco ficou
estruturalmente incompleto, sem nenhum sinal de erro.

Causa raiz complementar: o dump de origem foi feito com
`pg_dump -n public -n auth -n storage`. O schema `pgmq` nunca foi exportado —
nem a extensão, nem as tabelas de fila, nem as mensagens enfileiradas na virada.
As funções sobreviveram porque moram em `public`. A combinação das duas coisas
produziu um banco que parecia íntegro e não era.

## Decisão

1. **Não usar `EXCEPTION WHEN OTHERS THEN NULL` em migrations.** Quando a
   intenção é idempotência, capturar a condição específica:

   ```sql
   EXCEPTION WHEN duplicate_object THEN NULL;   -- objeto já existe
   EXCEPTION WHEN duplicate_table THEN NULL;
   ```

   `WHEN OTHERS` só é aceitável com `RAISE WARNING` no corpo, nunca com `NULL`.

2. **Dump de migração precisa incluir todo schema de extensão em uso.**
   Enumerar schemas com `-n` exclui silenciosamente o resto. Antes de restaurar,
   comparar `\dn` origem vs destino.

3. **Migração de banco não é validada por "restore sem erro".** Validar por
   contagem de objetos por schema, e por um teste funcional de ponta a ponta do
   caminho crítico — no caso do e-mail, `enqueue → read → delete` direto no SQL,
   antes de qualquer Edge Function.

## Consequências

- Auditar as ocorrências existentes. Levantamento de 2026-08-15:

  | Projeto | Migrations com `EXCEPTION WHEN OTHERS` | Total |
  |---|---|---|
  | feed-bpf | 5 | 144 |
  | create-with-voice (clone) | 5 | 142 |
  | audits-bpf | 2 | 50 |
  | agro-rc | 1 | 106 |
  | agrogestao | 1 | 53 |
  | soil-to-client | 1 | 106 |
  | bpf-solutions-suite | 0 | 12 |
  | friendly-flame-igniter | 0 | 47 |
  | rapid-ai-ally | 0 | 38 |

  Nem toda ocorrência é perigosa — o padrão só é grave quando envolve criação de
  objeto estrutural (extensão, fila, tabela, schema). As de dentro de função de
  runtime têm outro perfil de risco. Triar caso a caso.

- Os outros projetos migrados do Lovable pelo mesmo procedimento de dump podem
  ter a mesma lacuna de schema. Conferir `\dn` e extensões em cada um.

## Verificação da correção (Feed_BPF, 2026-08-15)

- `pg_cron`, `pg_net` e `pgmq` habilitadas no `xgvapaebustyotrwnzqa` — nenhuma
  existia antes.
- 4 filas criadas: `auth_emails`, `transactional_emails` e as duas `_dlq`.
- Cron `process-email-queue` (jobid 2, `*/5`) retornou HTTP 200 às 22:00.
- `email_send_log` registrou `sent` às 22:00:04.
