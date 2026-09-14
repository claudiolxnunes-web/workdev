# Política de revisão por risco

## Limites da execução

O diff usa dois SHAs completos: a base persistida da execução e o commit validado
pelo gate. Não compara contra develop, HEAD atual ou uma branch móvel.

- Builds manuais capturam `build.review_baseline.base_sha` antes do primeiro
  início pela API. O executor deve preparar a branch de trabalho antes de iniciar
  a Run e preservar seu isolamento durante a execução.
- O runtime CLI também captura a base antes de iniciar o agente.
- O worker em worktree já fornece `build.committed.base_sha`; essa informação é
  reutilizada, sem outra tabela ou migration.
- Tentativas de correção mantêm a primeira base. Transferências herdam a base da
  Run de origem, incluindo o trabalho do executor anterior.
- Runs legadas sem base comprovável ficam `blocked`. Não inferir `HEAD~1` nem
  usar develop: reconstrução histórica exige evidência explícita e auditável do
  primeiro commit da task em `build.review_baseline`.
- A base deve ser ancestral do commit final. Base ausente, inválida ou coleta
  parcial impede conclusão automática.

A classificação conta apenas adições/remoções; cabeçalhos e contexto não entram
nos limiares. O pacote mínimo usa `git diff --numstat`; o patch com contexto zero
só é incluído mediante `?expand=diff`. Base e commit aparecem no pacote/evento.
`context_bytes` e `tokens_estimate` descrevem o pacote mínimo gerado no ciclo;
a estimativa não representa cobrança real do provedor.

## Falha e escalonamento

Gate reprovado, inclusive na segunda leitura após entrar em review, devolve a
Run a `running` com decisão `NO_REVIEW_GATE_FAIL`. Ausência de evidência de diff
ou divergência de revisão leva a `blocked`.

Um revisor econômico que não consegue formar parecer deve rejeitar com feedback
iniciado exatamente por `ESCALATE:` (sem distinção de maiúsculas/minúsculas),
seguido da incerteza e das evidências faltantes. Exemplo:

```
ESCALATE: não consegui provar a ausência de corrida entre dois processos.
```

O backend audita a troca para candidato forte independente. A correção/avaliação
seguinte gera um novo ciclo. Revisor forte não é rebaixado automaticamente.
Risco médio com executor confiável usa revisão econômica e justificativa própria.

## Validação e implantação

`test_review_scope_e2e.py` exercita API ASGI, Git real e persistência SQLite em
ambiente isolado: histórico sensível anterior não contamina mudança pequena;
mudança sensível exige revisão; desaparecimento de gate retorna ao executor;
contexto mínimo não lê patch; base persiste no início e atravessa transferências.
Esses testes não equivalem a deploy ou a uso em produção. Não alterar/aplicar
migration ao corrigir essa política; a migration previamente entregue é aditiva
mas sua autorização operacional deve ser apurada separadamente.
