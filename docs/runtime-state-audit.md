# Auditoria de estados dos runtimes

O ponto canônico é `agent_snapshot.publish`, compartilhado pelo lifecycle e
pelo único collector `agents_healthcheck`. UI, HTTP GET e WebSocket não escrevem
histórico. O ADR `f178a0b4-3ffe-4caa-8ab3-a2f211b1d5fe` registra a ampliação
aceita por Cláudio para confirmação canônica de falhas.

## Policy

- Runtime: OFFLINE, STARTING, ONLINE, STOPPING, ERROR.
- Atividade: IDLE, BUSY, WAITING_INPUT; só é significativa em ONLINE.
- Intenções e resultados explícitos de lifecycle são publicados imediatamente.
  STARTING e STOPPING também são transições auditáveis, inclusive intenções
  de comandos que terminem de forma idempotente.
- Mudança para ERROR/OFFLINE proveniente de healthcheck exige duas observações
  distintas do mesmo estado, separadas por pelo menos 10 segundos. Uma publicação
  repetida do mesmo sample não conta. Recuperação ONLINE e atividade são imediatas.
- Durante confirmação, o snapshot confirmado anterior é preservado, inclusive
  seu checked_at. A leitura continua tratando dados obsoletos como indisponíveis;
  isso não inventa uma transição histórica.
- Amostras antigas são descartadas. Lifecycle novo cancela confirmação pendente.
- Primeira observação estabelece baseline, sem evento fictício de estado anterior.
  A auditoria não reconstrói transições anteriores à instalação.
- Comparação usa runtime + atividade; checked_at, processo e run_id isoladamente
  não geram transição.

## Persistência e recuperação

Reutiliza AgentRunEvent, tipo `runtime.state_changed`, sem migration ou tabela
nova. Sob o flock existente, snapshot novo e eventos pendentes são salvos juntos
com rename + fsync. Cada evento possui UUID estável. Depois são inseridos no
PostgreSQL em transação; replay verifica UUID/payload e não duplica registros.
Uma falha entre commit e limpeza do journal é recuperável na próxima publicação.

Durante indisponibilidade do banco, os eventos ficam em `audit_pending` no próprio
snapshot e o log indica replay pendente. O histórico SQL estará temporariamente
atrasado até a recuperação; não é apagado nem declarado sincronizado. Corrupção do
journal impede sobrescrita silenciosa. Preserve/backupe o snapshot junto do banco.
Não remover status.json como forma de limpar estado: isso também apagaria o journal.

Campos payload: runtime_id, estado_anterior e novo_estado (objetos runtime/activity),
timestamp UTC canônico de confirmação, source, sequence e stream_id. Timestamps
são crescentes por stream mesmo se o relógio recuar. run_id e erro são incluídos
quando presentes; erro é redigido antes de persistir. A FK run_id fica NULL para
que excluir uma run não apague, por CASCADE, transições do runtime. A associação
com a execução fica em payload.run_id.

A API genérica de eventos rejeita o prefixo `runtime.`: eventos de auditoria
são propriedade do backend.

## Consulta

```sql
SELECT created_at, payload->>'runtime_id' AS runtime_id,
       payload->'estado_anterior' AS estado_anterior,
       payload->'novo_estado' AS novo_estado,
       payload->>'run_id' AS run_id, payload->>'erro' AS erro,
       payload->>'sequence' AS sequence
FROM agent_run_events
WHERE event_type = 'runtime.state_changed'
  AND payload->>'runtime_id' = 'local-code'
ORDER BY created_at, id;
```

ONLINE → OFFLINE confirmado → ONLINE observado gera exatamente dois eventos.
Um comando explícito de parada inclui STOPPING e, portanto, é outro cenário:
ONLINE → STOPPING → OFFLINE. Polling sem mudança não gera eventos.

## Validação

`test_runtime_state_audit.py`: policy, SQLite isolado, ordenação, deduplicação,
concorrência e recuperação em falhas antes/depois do commit. Integrações de
lifecycle usam socket tmux privado e processo Python descartável, sem modelos
reais. Teste HTTP confirma que abrir/pollar o status não duplica auditoria.
