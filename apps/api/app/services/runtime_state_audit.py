"""Persistência idempotente das transições confirmadas pelo snapshot canônico."""
from datetime import datetime
from uuid import UUID

from app.models.handoff import AgentRunEvent


EVENT_TYPE = 'runtime.state_changed'


def _session():
    from app.database import SessionLocal
    return SessionLocal()


def persist(entries):
    if not entries:
        return
    with _session() as db:
        for entry in entries:
            key = UUID(entry['event_id'])
            existing = db.get(AgentRunEvent, key)
            if existing is not None:
                if existing.event_type != EVENT_TYPE or existing.payload != entry['payload']:
                    raise ValueError('runtime audit identity conflict')
                continue
            payload = entry['payload']
            if payload['estado_anterior'] == payload['novo_estado']:
                raise ValueError('runtime audit requires a transition')
            # A auditoria pertence ao runtime. Vincular a FK à run faria ON
            # DELETE CASCADE apagar parte do histórico; run_id fica no payload.
            db.add(AgentRunEvent(id=key, run_id=None, event_type=EVENT_TYPE,
                message='Transição confirmada no lifecycle canônico', payload=payload,
                created_at=datetime.fromisoformat(payload['timestamp'])))
        db.commit()
