# ADR 009 — Backlog: semântica do status `archived`

Status: accepted (revisão do codex aprovada; em produção desde a release 1d3d59d6, 2026-10-12).
Registro: `adrs.id = 276d00d0-4c36-46f3-8aee-576526122a44`.
Task: `1d735ecb-6563-46ab-af3a-104b9822f7e9`.
Plano aprovado v1. Run: `8fdb8936-a21b-46a1-86fc-458351d78edb`.

## Contexto

Tasks que concluíram fora do fluxo, perderam sentido ou não têm destravamento previsto ficavam presas em todo/blocked ou eram marcadas done com prefixo [Descartada] no título. DELETE /backlog/{id} existe mas apaga o registro (viola Backlog Zero, knowledge cf47f7d0). status era varchar(20) livre, sem CHECK no banco e sem validação de domínio na API; os 261 registros atuais já estão em todo|doing|blocked|done. Execução 8fdb8936, task 1d735ecb.

## Decisão

1. Domínio de status: todo|doing|blocked|done|archived, validado na API (POST e os dois PATCH). Fora do domínio → 422 {code: invalid_status, message, details: {allowed, received}}. Sem CHECK no banco (alteração mínima; a API é a porta de escrita).
2. Motivos fixos: concluida_fora, obsoleta, sem_destravamento. Texto livre opcional (archived_note na requisição), gravado como '<motivo>: <texto>' em archived_reason. Motivo é obrigatório para arquivar (422 archived_reason_required / invalid_archived_reason). archived_reason enviado sem status=archived → 422.
3. Persistência: colunas backlog.archived_at (timestamp, now() do servidor) e backlog.archived_reason (text), via Alembic. Invariante: archived_at/archived_reason preenchidos se e somente se status=archived.
4. Gate de subtasks: active_subtasks_remaining continua protegendo só done. Arquivar com subtasks pendentes é permitido, porque o motivo é obrigatório.
5. Leitura padrão: GET /backlog e GET /backlog/{slug} excluem archived; include_archived=true inclui. GET /backlog?status=archived é pedido explícito e devolve as arquivadas. Consumidores que filtram por status aberto (context_engine, supervisor, bancada, elegibilidade de planejamento) já não as veem; plan_without_execution e reporting passam a excluir archived junto com done.
6. Contadores e colunas do Kanban: as 4 colunas ficam; arquivadas não entram em nenhum contador. Toggle 'Mostrar arquivadas' exibe uma seção à parte.
7. Desarquivar: só para todo (409 archived_must_return_to_todo para qualquer outro destino). Limpa archived_at/archived_reason; status anterior não é guardado.
8. Quem arquiva: operador pela UI/API; AI Hub pela tool atualizar_task (exige motivo). Transições automáticas de agent_runs (handoff) não mexem no status de task arquivada.
9. Convivência com done+[Descartada]: títulos antigos ficam como estão; a triagem é card separado. done continua significando entregue.

## Consequências

Positivas: encerramento auditável e reversível, sem DELETE; fluxo ativo e contadores limpos. Negativas: desarquivar apaga o motivo anterior (sem histórico de transições, igual ao resto do backlog); escrita com status fora do domínio, que antes passava, agora é 422. Pendência: o portão de confirmação da ADR b759fe50 ainda não existe no servidor; atualizar_task segue gravando direto, como já fazia para done.
