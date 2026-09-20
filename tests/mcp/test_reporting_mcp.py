"""Run using the isolated MCP interpreter; no API secrets or live services."""
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest

import httpx
from starlette.testclient import TestClient

spec = importlib.util.spec_from_file_location('reporting_mcp', Path(__file__).resolve().parents[2] / 'mcp/reporting/server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
READ = 'read-' + 'r' * 40
TOKEN = 'mcp-' + 't' * 40
PARAMS = {'desde': '2026-09-01T00:00:00Z', 'ate': '2026-09-08T00:00:00Z'}


def report():
    return {'schema_version': 1, 'generated_at': PARAMS['ate'], 'period': {}, 'status': 'available',
            'no_news': True, 'message': 'Sem novidades', 'notes': [], 'progress': {},
            'current_work': {}, 'priority_pending': [], 'next_steps': [], 'risks_and_blockers': [],
            'attention_changes': [], 'sources': {}, 'dora': {}, 'supervisors': {},
            'agents': {}, 'health': {}, 'gaps': []}


class ReportingMCPTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        def backend(request):
            self.requests.append(request)
            return httpx.Response(200, json=report())
        self.server = module.create_server('http://127.0.0.1:8000', READ,
            'https://reporting.example.com', transport=httpx.MockTransport(backend))

    def test_single_readonly_tool_and_structured_schema(self):
        async def check():
            tools = await self.server.list_tools()
            self.assertEqual([t.name for t in tools], ['resumo_semanal_workdev'])
            self.assertTrue(tools[0].annotations.readOnlyHint)
            self.assertFalse(tools[0].annotations.destructiveHint)
            self.assertIsNotNone(tools[0].outputSchema)
            content, structured = await self.server.call_tool('resumo_semanal_workdev', PARAMS)
            self.assertTrue(structured['no_news'])
        asyncio.run(check())
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(request.method, 'GET')
        self.assertEqual(request.url.path, '/api/reporting/weekly-status')
        self.assertEqual(request.headers['X-API-Key'], READ)
        self.assertNotIn('authorization', request.headers)

    def test_invalid_interval_does_not_call_backend(self):
        async def check():
            for params in [{**PARAMS, 'desde': '2026-09-01'}, {**PARAMS, 'desde': PARAMS['ate']},
                           {**PARAMS, 'desde': '2020-01-01T00:00:00Z'}]:
                with self.assertRaises(Exception):
                    await self.server.call_tool('resumo_semanal_workdev', params)
        asyncio.run(check())
        self.assertFalse(self.requests)

    def test_http_requires_bearer_and_lists_only_reporting_tool(self):
        app = module.BearerGate(self.server.streamable_http_app(), TOKEN)
        with TestClient(app, base_url='http://127.0.0.1:8788') as client:
            for headers in [{}, {'Authorization': 'Bearer bad'}]:
                self.assertEqual(client.post('/mcp', json={}, headers=headers).status_code, 401)
            headers = {'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/json, text/event-stream'}
            result = client.post('/mcp', headers=headers, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                           'clientInfo': {'name': 'test', 'version': '1'}}})
            self.assertEqual(result.status_code, 200, result.text)
            tools = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
            self.assertEqual([t['name'] for t in tools.json()['result']['tools']], ['resumo_semanal_workdev'])
            called = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                'params': {'name': 'resumo_semanal_workdev', 'arguments': PARAMS}})
            self.assertTrue(called.json()['result']['structuredContent']['no_news'])
            denied = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                'params': {'name': 'concluir_pendencia', 'arguments': {}}})
            self.assertTrue(denied.json()['result']['isError'])

    def test_backend_error_masks_body_and_credentials(self):
        def backend(request):
            return httpx.Response(403, text=READ)
        server = module.create_server('http://127.0.0.1:8000', READ,
            'https://reporting.example.com', transport=httpx.MockTransport(backend))
        async def check():
            with self.assertRaises(Exception) as raised:
                await server.call_tool('resumo_semanal_workdev', PARAMS)
            self.assertNotIn(READ, str(raised.exception))
        asyncio.run(check())

    def test_startup_rejects_missing_or_reused_credentials(self):
        from unittest.mock import patch
        for env in [{}, {'WORKDEV_READONLY_API_KEY': READ, 'WORKDEV_REPORTING_MCP_TOKEN': READ},
                    {'WORKDEV_READONLY_API_KEY': READ, 'WORKDEV_REPORTING_MCP_TOKEN': TOKEN, 'WORKDEV_API_KEY': 'general'}]:
            with patch.dict(module.os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    module.create_app()


if __name__ == '__main__':
    unittest.main()
