# SPDX-License-Identifier: GPL-3.0-only
"""Small stdio acceptance client. This is not an autonomous production agent."""
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


class PendingApproval:
    """One elicitation opportunity bound to one pending tools/call request."""
    def __init__(self, tool, arguments):
        self.tool = tool
        self.arguments = json.dumps(arguments, sort_keys=True, allow_nan=False)
        self.consumed = False

    def take(self, form):
        if self.consumed:
            return False
        # Consume even a malformed first attempt: the server cannot retry a
        # different form using the same deterministic once-only test decision.
        self.consumed = True
        if not isinstance(form, dict) or form.get('mode') != 'form':
            return False
        message = form.get('message')
        if not isinstance(message, str) or len(message) > 200:
            return False
        match = re.fullmatch(
            r'Stackarr wants to run a destructive action\.\n\nTool: (stackarr_[a-z0-9_]+)'
            r'\nCategory: containers\n\nArguments:\n(\{.*\})', message, re.DOTALL)
        if not match or match[1] != self.tool:
            return False
        try:
            arguments = json.loads(match[2], object_pairs_hook=_unique_object)
            return isinstance(arguments, dict) and json.dumps(arguments, sort_keys=True, allow_nan=False) == self.arguments
        except (ValueError, TypeError):
            return False


class StackarrClient:
    def __init__(self, docker, profile, runtime, *, elicitation=True, baseline=False):
        self.runtime = Path(runtime)
        self.baseline = baseline
        self.counter = 0
        self.events = []
        self.choice = 'decline'
        self.q = queue.Queue()
        self.log = (self.runtime / ('mcp-' + profile + '.log')).open('a')
        self.proc = subprocess.Popen(
            docker + ['exec', '-i', '-e', 'STACKARR_MCP_PROFILE=' + profile,
                      '-e', 'STACKARR_MCP_GROUPS=containers',
                      '-e', 'STACKARR_MCP_CLIENT=hermes', 'lab-stackarr',
                      '/app/bin/stackarr', 'mcp', 'serve'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, bufsize=1)
        def reader():
            for line in self.proc.stdout:
                self.q.put(line)
            self.q.put(None)
        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()
        try:
            self.initialized = self.request('initialize', {
                'protocolVersion': '2025-03-26',
                'capabilities': {'elicitation': {'form': {}}} if elicitation else {},
                'clientInfo': {'name': 'community-lab-acceptance', 'version': '0.1.0'}})
        except BaseException:
            self.close()
            raise
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def send(self, data):
        self.proc.stdin.write(json.dumps(data) + '\n')
        self.proc.stdin.flush()

    def request(self, method, params):
        self.counter += 1
        request_id = self.counter
        pending = PendingApproval(params['name'], params.get('arguments', {})) if method == 'tools/call' else None
        choice = self.choice
        self.send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        while True:
            line = self.q.get(timeout=60)
            if line is None:
                raise RuntimeError('Stackarr exited; inspect its local stderr log')
            message = json.loads(line)
            if message.get('method') == 'elicitation/create':
                form = message['params']
                # Match pending tool AND arguments, with one non-reusable decision.
                # The unchanged Hermes bridge also enforces the exact pinned schema.
                exact = pending.take(form) if pending else False
                answer = {'result': {'action': 'decline'}, 'shown': []}
                if exact:
                    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TMPDIR') if k in os.environ}
                    env['HOME'] = str(self.runtime / 'empty-home')
                    cmd = [str(self.runtime / 'venv/bin/python'), str(self.runtime / 'consent_bridge.py')]
                    if self.baseline:
                        cmd.append('--baseline')
                    completed = subprocess.run(cmd, input=json.dumps({'params': form, 'choice': choice}),
                                               text=True, capture_output=True, check=True, timeout=10, env=env)
                    answer = json.loads(completed.stdout)
                self.events.append({'form': form, 'exact_action': exact, 'answer': answer})
                self.send({'jsonrpc': '2.0', 'id': message['id'], 'result': answer['result']})
            elif message.get('id') == request_id:
                return message

    def call(self, name, arguments=None, *, choice='decline'):
        self.choice = choice
        return self.request('tools/call', {'name': name, 'arguments': arguments or {}})

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=5)
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def payload(message):
    if 'error' in message:
        return {'accepted': False, 'rpc_error': message['error']}
    result = message.get('result', {})
    if 'structuredContent' in result:
        return result['structuredContent']
    for block in result.get('content', []):
        if block.get('type') == 'text':
            try:
                return json.loads(block['text'])
            except ValueError:
                return {'text': block['text'], 'isError': result.get('isError', False)}
    return result
