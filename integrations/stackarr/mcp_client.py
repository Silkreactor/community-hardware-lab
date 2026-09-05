# SPDX-License-Identifier: GPL-3.0-only
"""Small stdio acceptance client. This is not an autonomous production agent."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading


class StackarrClient:
    def __init__(self, docker, profile, runtime, *, elicitation=True, baseline=False):
        self.runtime = Path(runtime)
        self.baseline = baseline
        self.counter = 0
        self.events = []
        self.choice = 'decline'
        self.expected = None
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
        self.send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        while True:
            line = self.q.get(timeout=60)
            if line is None:
                raise RuntimeError('Stackarr exited; inspect its local stderr log')
            message = json.loads(line)
            if message.get('method') == 'elicitation/create':
                form = message['params']
                # Match the exact action requested by this test before even asking
                # the real Hermes consent handler to translate its once-only reply.
                try:
                    displayed = json.loads(form['message'].split('Arguments:\n', 1)[1])
                    exact = displayed == self.expected
                except (KeyError, ValueError, IndexError):
                    exact = False
                answer = {'result': {'action': 'decline'}, 'shown': []}
                if exact:
                    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TMPDIR') if k in os.environ}
                    env['HOME'] = str(self.runtime / 'empty-home')
                    cmd = [str(self.runtime / 'venv/bin/python'), str(self.runtime / 'consent_bridge.py')]
                    if self.baseline:
                        cmd.append('--baseline')
                    completed = subprocess.run(cmd, input=json.dumps({'params': form, 'choice': self.choice}),
                                               text=True, capture_output=True, check=True, timeout=10, env=env)
                    answer = json.loads(completed.stdout)
                self.events.append({'form': form, 'exact_action': exact, 'answer': answer})
                self.send({'jsonrpc': '2.0', 'id': message['id'], 'result': answer['result']})
            elif message.get('id') == request_id:
                return message

    def call(self, name, arguments=None, *, choice='decline'):
        self.choice = choice
        self.expected = arguments or {}
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
