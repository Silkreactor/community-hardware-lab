# SPDX-License-Identifier: GPL-3.0-only
import io
import json
from pathlib import Path
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mcp_client import PendingApproval, StackarrClient

TOOL = 'stackarr_manage_container_resource'
ARGS = {'kind': 'container', 'action': 'restart', 'id': 'lab-media'}


def form(tool=TOOL, args=None):
    return {'mode': 'form', 'message': 'Stackarr wants to run a destructive action.\n\nTool: ' + tool +
            '\nCategory: containers\n\nArguments:\n' + json.dumps(ARGS if args is None else args, indent=2)}


class ProtocolTests(unittest.TestCase):
    def test_exact_tool_and_arguments_only_once(self):
        pending = PendingApproval(TOOL, ARGS)
        self.assertTrue(pending.take(form()))
        self.assertFalse(pending.take(form()))

    def test_different_tool_with_identical_args_cannot_spend_approval(self):
        pending = PendingApproval(TOOL, ARGS)
        self.assertFalse(pending.take(form('stackarr_remove_docker_volume')))
        self.assertFalse(pending.take(form()))

    def test_changed_target_is_refused(self):
        self.assertFalse(PendingApproval(TOOL, ARGS).take(form(args={**ARGS, 'id': 'production'})))

    def test_malformed_or_wrong_mode_forms_are_refused(self):
        for invalid in (None, {}, {'mode': 'url'}, {**form(), 'message': 'Arguments:\n{}'},
                        {**form(), 'message': form()['message'] + '\nextra'},
                        {**form(), 'mode': 'url'}):
            with self.subTest(invalid=invalid):
                self.assertFalse(PendingApproval(TOOL, ARGS).take(invalid))

    def test_duplicate_keys_and_json_type_coercion_refused(self):
        duplicate = {**form(), 'message': form()['message'].replace('"kind": "container",', '"kind": "image", "kind": "container",')}
        self.assertFalse(PendingApproval(TOOL, ARGS).take(duplicate))
        self.assertFalse(PendingApproval(TOOL, {'force': 1}).take(form(args={'force': True})))

    def test_request_scope_routes_only_one_of_replayed_forms_to_bridge(self):
        client = object.__new__(StackarrClient)
        client.runtime = Path('/unused-test-runtime')
        client.baseline = False
        client.counter = 0
        client.choice = 'once'
        client.events = []
        client.proc = SimpleNamespace(stdin=io.StringIO())
        client.q = queue.Queue()
        for request_id in (101, 102):
            client.q.put(json.dumps({'id': request_id, 'method': 'elicitation/create', 'params': form()}))
        client.q.put(json.dumps({'id': 1, 'result': {'accepted': True}}))
        with patch('mcp_client.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps({'result': {'action': 'accept', 'content': {'approve': True}}}))) as bridge:
            client.request('tools/call', {'name': TOOL, 'arguments': ARGS})
        self.assertEqual(bridge.call_count, 1)
        replies = [json.loads(line) for line in client.proc.stdin.getvalue().splitlines()][1:]
        self.assertEqual(replies[0]['result']['action'], 'accept')
        self.assertEqual(replies[1]['result']['action'], 'decline')
        self.assertEqual([event['exact_action'] for event in client.events], [True, False])

    def test_non_tool_request_never_routes_an_elicitation_to_bridge(self):
        client = object.__new__(StackarrClient)
        client.counter = 0
        client.choice = 'once'
        client.events = []
        client.proc = SimpleNamespace(stdin=io.StringIO())
        client.q = queue.Queue()
        client.q.put(json.dumps({'id': 101, 'method': 'elicitation/create', 'params': form()}))
        client.q.put(json.dumps({'id': 1, 'result': {}}))
        with patch('mcp_client.subprocess.run') as bridge:
            client.request('tools/list', {})
        bridge.assert_not_called()


if __name__ == '__main__':
    unittest.main()
