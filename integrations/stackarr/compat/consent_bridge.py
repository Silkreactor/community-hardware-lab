"""Isolated full-module Hermes consent fixture; no agent/provider/config access.

Only unused registry/config/environment/UI dependencies are stand-ins. The
ElicitationHandler, consent router, gateway queue/resolver and SDK result type
execute from the actual pinned modules (plus the local two-file patch).
"""
import asyncio
import contextvars
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types
from contextlib import redirect_stdout
from types import SimpleNamespace
from mcp.types import ElicitResult, ElicitRequestFormParams

ROOT = Path(__file__).parent

def stub(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

stub('tools', __path__=[])
stub('tools.registry', tool_error=lambda *a, **k: None)
stub('tools.ansi_strip', strip_unicode_tags=lambda text: text)
stub('tools.interrupt', is_interrupted=lambda: False)
stub('hermes_cli', __path__=[])
stub('hermes_cli.config', cfg_get=lambda *a, **k: None, load_config_readonly=lambda: {})
stub('utils', env_var_enabled=lambda key: False, is_truthy_value=lambda val: val in (True, '1', 'true'))
stub('gateway', __path__=[])
stub('gateway.session_context', get_session_env=lambda key, default='': 'telegram' if key == 'HERMES_SESSION_PLATFORM' else default)

source = ROOT / ('hermes-baseline' if '--baseline' in sys.argv else 'hermes-fix')
approval = load('tools.approval', source / 'tools/approval.py')
handler_module = load('trial_mcp_tool', source / 'tools/mcp_tool.py')
handler_module.ElicitResult = ElicitResult

async def respond(params, choice='once', *, server='stackarr', sdk_params=True):
    shown = []
    session = 'isolated-' + os.urandom(8).hex()
    token = approval._approval_session_key.set(session)
    old_timeout = approval._get_approval_timeout
    approval._get_approval_timeout = lambda: 0.025 if choice == 'timeout' else 2
    def notify(data):
        shown.append(data)
        if choice == 'error':
            raise RuntimeError('fixture notification failure')
        if choice == 'timeout':
            return
        if choice == 'cancel':
            approval.unregister_gateway_notify(session)
            return
        assert approval.resolve_gateway_approval(session, choice, request_id=data['request_id']) == 1
    if choice != 'absent':
        approval.register_gateway_notify(session, notify)
    owner = SimpleNamespace(_pending_call_context=contextvars.copy_context())
    handler = handler_module.ElicitationHandler(server, {'timeout': 1}, owner=owner)
    output = io.StringIO()
    try:
        request = ElicitRequestFormParams.model_validate(params) if sdk_params else SimpleNamespace(**params)
        with redirect_stdout(output):
            result = await handler(None, request)
        assert not approval.list_gateway_approvals(session)
        assert not approval._session_approved
        assert not approval._permanent_approved
        return {'result': result.model_dump(by_alias=True, exclude_none=True), 'shown': shown, 'metrics': handler.metrics, 'prompt': output.getvalue()}
    finally:
        approval.unregister_gateway_notify(session)
        approval._get_approval_timeout = old_timeout
        approval._approval_session_key.reset(token)

if __name__ == '__main__':
    data = json.load(sys.stdin)
    try:
        answer = asyncio.run(respond(data['params'], data.get('choice', 'once')))
    except Exception as error:
        answer = {'result': {'action': 'decline'}, 'error': type(error).__name__ + ': ' + str(error), 'shown': []}
    print(json.dumps(answer))
