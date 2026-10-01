"""Local-code model selection and the root wrapper must resolve identical keys."""
import json
from contextlib import nullcontext
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import local_model, local_code_channel, agent_lifecycle

ROOT = Path(__file__).resolve().parents[3]
PATHS = {
    'prod': '/opt/workdev/models/workdev-14b-codigo-q4_k_m.gguf',
    'dev': '/opt/workdev/models/workdev-7b-q4_k_m.gguf',
    'fast': '/opt/workdev/models/workdev-4b-code70-fidelity30-v1-q4_k_m.gguf',
}


@pytest.mark.parametrize('raw,expected', [
    (None, 'prod'),
    ('', 'prod'),
    ('prod\n', 'prod'),
    ('dev\n', 'dev'),
    ('fast\n', 'fast'),
    ('q4\n', 'prod'),
    ('q2\n', 'prod'),
    ('bonsai\n', 'prod'),
    ('unknown', 'prod'),
    ('PROD', 'prod'),
])
def test_python_and_wrapper_resolve_same_model(tmp_path, monkeypatch, raw, expected):
    key = tmp_path / 'model'
    if raw is not None:
        key.write_text(raw)
    monkeypatch.setattr(local_model, 'KEY_FILE', key)
    assert local_model.current() == expected
    fake = tmp_path / 'llama-server'
    fake.write_text('#!/usr/bin/python3\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\n')
    fake.chmod(0o755)
    wrapper = (ROOT / 'scripts/deploy/workdev-llama-run').read_text()
    wrapper = wrapper.replace('/var/lib/workdev-llama/model', str(key))
    wrapper = wrapper.replace('/opt/llama.cpp/build/bin/llama-server', str(fake))
    script = tmp_path / 'wrapper'
    script.write_text(wrapper)
    args = json.loads(subprocess.check_output(['sh', str(script)], text=True))
    assert args[args.index('-m') + 1] == PATHS[expected]
    assert args[args.index('-a') + 1] == 'workdev-qwen'
    assert args[args.index('--port') + 1] == '8080'
    assert args[args.index('-c') + 1] == '32768'
    if expected == 'fast':
        assert args[args.index('--chat-template-kwargs') + 1] == '{"enable_thinking":false}'
    else:
        assert '--chat-template-kwargs' not in args


def test_local_model_endpoints_were_removed():
    from app.routers.terminal import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/api/agents/local-code/model').status_code == 404
        assert client.post('/api/agents/local-code/model', json={'model': 'dev'}).status_code in {404, 405}


@pytest.mark.parametrize('busy', [True, False])
def test_fast_switch_respects_busy_and_offline_state(tmp_path, monkeypatch, busy):
    key = tmp_path / 'model'
    key.write_text('dev\n')
    monkeypatch.setattr(local_model, 'KEY_FILE', key)
    monkeypatch.setattr(agent_lifecycle, 'agent_lock', lambda *a, **k: nullcontext())
    monkeypatch.setattr(agent_lifecycle, 'active_work', lambda *a: {'run_id': 'busy'} if busy else None)
    monkeypatch.setattr(local_code_channel, 'read', lambda: {'phase': 'idle'})
    service = Mock(return_value=False)
    monkeypatch.setattr(agent_lifecycle, '_llama_service', service)
    if busy:
        with pytest.raises(local_model.SwitchError, match='trabalho ativo'):
            local_model.switch('fast', Mock())
        assert key.read_text() == 'dev\n'
        service.assert_not_called()
    else:
        assert local_model.switch('fast', Mock()) == {'model': 'fast', 'switched': True, 'restarted': False}
        assert key.read_text() == 'fast\n'
        service.assert_called_once_with('is-active')
