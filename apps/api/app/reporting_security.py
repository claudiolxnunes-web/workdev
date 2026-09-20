"""Least-privilege reporting identity. Never log headers, queries or bodies."""
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone

from starlette.responses import JSONResponse

logger = logging.getLogger('workdev.reporting.audit')
SAFE_ROUTES = re.compile(
    r'/api/(?:reporting/weekly-status|backlog(?:/[a-z0-9-]+)?|decisions|'
    r'deployments/(?:status|outcomes(?:/[a-zA-Z0-9-]+)?)|'
    r'handoffs/(?:plans|runs)(?:/[0-9a-fA-F-]{36})?|'
    r'metrics/executive|monitoring/status|agent-runtimes|subtasks/[0-9a-fA-F-]{36})'
)
# Direct source endpoints retain only an explicitly public reporting projection.
PUBLIC_FIELDS = frozenset('''id project_id backlog_id plan_id proof_id title task_title
project_name project version status priority type owner agent reviewer_agent model
created_at updated_at approved_at started_at finished_at deployed_at commit_sha
outcome execution_order assigned_agent items data runs plans runtimes agents
checked_at generated_at gerado_em resumo summary total online apps services name
slug estado http latencia_ms latency_ms configured busy dispatchable status_label
runtime_state activity_state active_run_id run_status metrics deployment_frequency
weekly_average last_4_weeks total_in_period week successful degraded failed
change_failure_rate percent failed_count total_count mttr median_minutes mean_minutes
incident_count lead_time median_hours mean_hours min_hours max_hours completed_count
period_days dora_score dora_level source probe_requested'''.split())


def readonly_key(supplied: str | None) -> bool:
    expected = os.getenv('WORKDEV_READONLY_API_KEY')
    return bool(expected and supplied and hmac.compare_digest(supplied.encode(), expected.encode()))


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        for name, secret in os.environ.items():
            if len(secret) >= 8 and any(part in name.upper() for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'DATABASE_URL')):
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'\b(?:sk-[\w-]{10,}|ghp_[\w]{20,}|github_pat_[\w]+|sb_secret_[\w-]+|eyJ[\w-]+\.[\w-]+\.[\w-]+)', '[REDACTED]', value)
        value = re.sub(r'([a-zA-Z][\w+.-]*://)[^\s/@:]+:[^\s/@]+@', r'\1[REDACTED]@', value)
        value = re.sub(r'(?i)\b(?:bearer\s+|(?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+', '[REDACTED]', value)
    return value


def project_public(value):
    if isinstance(value, dict):
        return {k: project_public(v) for k, v in value.items() if k in PUBLIC_FIELDS}
    if isinstance(value, list):
        return [project_public(v) for v in value]
    return scrub(value)


class ReportingAccessMiddleware:
    """Enforce before routing, including WS, login and a simultaneous full cookie."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        supplied_keys = [value.decode('latin1') for name, value in scope.get('headers', [])
                         if name.lower() == b'x-api-key']
        # Starlette picks the first duplicate header; a dict would pick the last.
        # Any reporting credential keeps the entire request restricted.
        if not any(readonly_key(value) for value in supplied_keys):
            return await self.app(scope, receive, send)
        path = scope['path']
        allowed = scope['type'] == 'http' and scope['method'] == 'GET' and SAFE_ROUTES.fullmatch(path)
        status = 403
        try:
            if not allowed:
                if scope['type'] == 'websocket':
                    if 'websocket.http.response' in scope.get('extensions', {}):
                        await send({'type': 'websocket.http.response.start', 'status': 403, 'headers': []})
                        await send({'type': 'websocket.http.response.body', 'body': b'Forbidden'})
                    else:
                        await send({'type': 'websocket.close', 'code': 1008})
                else:
                    await JSONResponse({'detail': 'Reporting credential is read-only'}, status_code=403)(scope, receive, send)
                return
            status = 500
            chunks = []
            async def capture(message):
                nonlocal status
                if message['type'] == 'http.response.start':
                    status = message['status']
                elif message['type'] == 'http.response.body':
                    chunks.append(message.get('body', b''))
            await self.app(scope, receive, capture)
            if status >= 400:
                result = {'detail': 'Reporting source unavailable', 'status': status}
            else:
                try:
                    body = json.loads(b''.join(chunks))
                    result = scrub(body) if path == '/api/reporting/weekly-status' else project_public(body)
                except (ValueError, TypeError):
                    status, result = 502, {'detail': 'Invalid reporting source'}
            await JSONResponse(result, status_code=status)(scope, receive, send)
        finally:
            logger.info('reporting_access at=%s identity=reporting method=%s route=%s status=%s',
                        datetime.now(timezone.utc).isoformat(), scope.get('method', 'WEBSOCKET'),
                        audit_route(path), status)


def audit_route(path: str) -> str:
    if not SAFE_ROUTES.fullmatch(path):
        return '[forbidden]'
    return re.sub(r'(/api/(?:backlog|subtasks|handoffs/(?:plans|runs)|deployments/outcomes))/[^/]+$',
                  r'\1/{id}', path)
