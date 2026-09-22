# Discovery — auditoria de transições de runtimes

Execução: `103f81df-e034-45b0-832e-b331f4c574e9`.
Discovery realizado por Codex a pedido do operador; roteamento recebido ainda
indica local-code como executor e Codex como revisor.

## Pontos existentes

| Componente | Tratamento | Evidência / lacuna |
| --- | --- | --- |
| `agent_snapshot.publish` | Preservar/completar | Publicação canônica sob flock; rejeita amostras anteriores ao snapshot. Persistência atual em JSON, sem transação com PostgreSQL. |
| `agent_lifecycle.lifecycle_operation` | Preservar | Publica intenção STARTING/STOPPING e resultado físico ou ERROR. |
| `agents_healthcheck.collect_agent` | Preservar, decisão necessária | Publica ERROR na primeira exceção; não há confirmação de falha para o estado canônico. |
| `agents_healthcheck.collect_snapshot` | Preservar, decisão necessária | Timeout de coleta também publica ERROR imediatamente. |
| `agents_healthcheck.notify_transitions` | Preservar | Debounce de 10 segundos e cooldown de 300 segundos são exclusivamente de Telegram; agrupa ERROR/OFFLINE como down. Não confirma estado do lifecycle. |
| `agent_snapshot.read_snapshot` | Preservar | Leitura pode representar snapshot obsoleto como ERROR; não deve gerar auditoria. |
| `AgentRunEvent` | Reutilizar | `run_id` já aceita NULL; payload JSONB e created_at suportam auditoria sem run. Não há justificativa para RuntimeStateAudit. |
| Transferência de execução | Completar roteamento | API aceita novo executor e revisor juntos; CLI transfer não expõe reviewer. Transferir para o revisor vigente é corretamente recusado. |

Estados canônicos: OFFLINE, STARTING, ONLINE, STOPPING, ERROR.
Atividade separada: IDLE, BUSY, WAITING_INPUT. A comparação de auditoria deve
considerar ambas as dimensões, sem gerar evento por mudança apenas de checked_at.

## Incompatibilidade que impede implementação silenciosa

O plano exige simultaneamente preservar a policy canônica e não auditar uma
falha isolada como transição definitiva. A policy atual publica essa falha
imediatamente como ERROR. Copiar o debounce do Telegram apenas para a auditoria
criaria uma segunda definição de estado confirmado, divergente do backend.

É necessária decisão do operador sobre ampliar o plano para introduzir
confirmação de falhas no ponto canônico. Alternativa: revisar o aceite e auditar
também ERROR transitório conforme a policy atual. Não foi escolhido limiar novo
nem alterado comportamento operacional neste discovery.

Também deve ser especificada a atomicidade entre snapshot JSON e AgentRunEvent:
gravar primeiro um deles não garante ausência de gaps após crash. A solução
precisa de recuperação durável/idempotente no ponto canônico ou autoridade
transacional no banco; um callback de auditoria best-effort não atende ao aceite.

## Validação a executar após a decisão

Testes de transição com banco isolado, deduplicação de amostras repetidas e
antigas, ciclo ONLINE/OFFLINE/ONLINE, falha isolada versus confirmada, atividade,
concorrência entre lifecycle e collector e recuperação de crash entre gravações.
Depois: regressões do lifecycle/healthcheck, lint, build e gate canônico.
Nenhum serviço, sessão ou modelo real foi iniciado ou interrompido no discovery.

## Decisão posterior ao discovery

ADR `f178a0b4-3ffe-4caa-8ab3-a2f211b1d5fe` aceito após autorização de Cláudio.
A implementação amplia a confirmação no ponto canônico (duas observações
separadas por 10 segundos), mantém comandos explícitos imediatos e reutiliza
AgentRunEvent com journal no snapshot para recuperação idempotente. Nenhuma
tabela nova. Detalhes em `docs/runtime-state-audit.md`.

Transferência registrada: execução original cancelada pelo fluxo canônico;
nova run `bc3dc0c3-524c-4fd4-a7c8-fde3d903cf2e`, executor Codex, revisor Claude.
A autorrevisão solicitada pelo operador não será registrada como independente.
