"""Per-run Observer choice, stored in the existing run event log."""
from app.models.handoff import AgentRunEvent


def current(db, run_id):
    event = (db.query(AgentRunEvent).filter_by(run_id=run_id,
        event_type='observer.configured').order_by(
        AgentRunEvent.created_at.desc(), AgentRunEvent.id.desc()).first())
    if event is None:
        return None
    payload = event.payload or {}
    return {'enabled': bool(payload.get('enabled')),
            'provider': payload.get('provider'), 'model': payload.get('model'),
            'runtime_id': payload.get('runtime_id'), 'configured_at': event.created_at}
