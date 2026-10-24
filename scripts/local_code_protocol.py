#!/usr/bin/env python3
"""Qwen hook adapter and ephemeral overlay; never reads backend credentials."""
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile


def settings(source):
    value = json.loads(Path(source).read_text())
    script = Path(__file__).resolve()
    python = Path('/opt/workdev/apps/api/venv/bin/python')
    command = f'{shlex.quote(str(python))} {shlex.quote(str(script))} hook'
    hooks = value.setdefault('hooks', {})
    for event in ('SessionStart', 'UserPromptSubmit', 'Stop', 'StopFailure', 'SessionEnd', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure'):
        hooks.setdefault(event, []).append({'hooks': [{
            'type': 'command', 'command': command, 'timeout': 10,
        }]})
    directory = Path(tempfile.mkdtemp(prefix='workdev-local-code-settings-'))
    input_file = directory / 'input.jsonl'
    input_file.touch(mode=0o600)
    value['dualOutput'] = {**value.get('dualOutput', {}), 'inputFile': str(input_file)}
    path = directory / 'settings.json'
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return str(path)


def main():
    if sys.argv[1] == 'settings':
        print(settings(sys.argv[2]))
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'apps/api'))
    from app.services.local_code_channel import hook
    try:
        result = hook(json.load(sys.stdin))
        print(json.dumps(result))
        return 0
    except Exception as error:
        # Hooks must not fail open when the durable protocol is unavailable.
        print(f'WorkDev: protocolo local-code indisponível ({getattr(error, "code", type(error).__name__)}); operação recusada', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
