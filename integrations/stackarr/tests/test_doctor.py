# SPDX-License-Identifier: GPL-3.0-only
from datetime import datetime, timezone, timedelta
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import doctor


class DoctorTests(unittest.TestCase):
    def test_storage_realistic_and_low_space_fixture(self):
        normal = 'Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/a 10000000 1000000 9000000 10% /\n/dev/b 10000000 2000000 8000000 20% /var/lib/docker'
        self.assertEqual(doctor.storage_result(normal)['state'], 'known')
        low = normal.replace('2000000 8000000 20%', '9500000 500000 95%')
        self.assertEqual(doctor.storage_result(low)['state'], 'low')
        self.assertNotIn('/var/lib', json.dumps(doctor.storage_result(low)))

    def test_bad_missing_negative_storage_is_unknown(self):
        for value in ('', 'error: /private/client/file', 'header\na -1 2 3 5% /\nb 10 1 9 10% /x',
                      'header\na 10 1 9 10% /', 'header\na 10 1 9 101% /\nb 10 1 9 10% /x'):
            with self.subTest(value=value):
                self.assertEqual(doctor.storage_result(value)['state'], 'unknown')

    def test_backup_fresh_stale_missing_tampered_wrong_scope_and_future(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'result.json'
            now = datetime(2026, 9, 6, tzinfo=timezone.utc)
            names = ['journey_complete', 'recovered_application_records_and_login', 'recovered_media_bytes',
                     'separate_recovery_instance_and_volumes', 'rollback_original_remains_usable']
            record = {'completed': (now-timedelta(hours=1)).isoformat(), 'engine': {'ID': 'test'},
                      'images': {'stackarr': doctor.STACKARR, 'jellyfin': doctor.JELLYFIN},
                      'checks': [{'name': n, 'passed': True} for n in names], 'backups': {}}
            for name in ('config.tar', 'media.tar'):
                (root/name).write_bytes(b'labelled test fixture, not a real backup')
                record['backups'][name] = hashlib.sha256((root/name).read_bytes()).hexdigest()
            def result():
                path.write_text(json.dumps(record))
                return doctor.backup_result(path, 'test', now, root)
            self.assertEqual(result()['state'], 'recorded')
            record['completed'] = (now-timedelta(days=2)).isoformat()
            self.assertEqual(result()['state'], 'stale')
            record['completed'] = (now+timedelta(hours=1)).isoformat()
            self.assertEqual(result()['state'], 'unknown')
            record['completed'] = now.isoformat(); record['engine']['ID'] = 'other'
            self.assertEqual(result()['state'], 'unknown')
            record['engine']['ID'] = 'test'; record['checks'][0]['passed'] = 1
            self.assertEqual(result()['state'], 'unknown')
            record['checks'][0]['passed'] = True
            (root/'config.tar').write_bytes(b'changed')
            self.assertEqual(result()['state'], 'unknown')
            (root/'config.tar').unlink()
            self.assertEqual(result()['state'], 'unknown')
            self.assertEqual(doctor.backup_result(None, 'test', now, root)['state'], 'unknown')

    def test_no_runtime_errors_or_host_paths_leak(self):
        with patch('doctor.validate_isolation', side_effect=ValueError('/private/secret TOKEN=bad')):
            result = doctor.report('unix:///wrong', 'test')
        text = doctor.render(result)
        self.assertEqual(result['lab']['state'], 'unknown')
        self.assertNotIn('/private', text)
        self.assertNotIn('TOKEN', text)

    def test_running_but_unreachable_stopped_and_read_only_commands(self):
        commands = []
        def run(args, **_kwargs):
            commands.append(args)
            if args[3] == 'info':
                return json.dumps({'ID': 'test', 'Name': 'colima-lab', 'OSType': 'linux'})
            if args[3] == 'inspect':
                media = args[4] == 'lab-media'
                return json.dumps([{'Config': {'Labels': {'community-lab.trial': 'true'}, 'Image': doctor.JELLYFIN if media else doctor.STACKARR},
                                    'State': {'Running': media}, 'HostConfig': {'NetworkMode': 'bridge',
                                    'PortBindings': {'8096/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18096'}]}}}])
            raise subprocess.TimeoutExpired('df', 15)
        with patch('doctor.validate_isolation'), patch('doctor.subprocess.check_output', side_effect=run), patch('doctor.public_jellyfin', side_effect=OSError('connection refused')):
            result = doctor.report('unix:///fixture', 'test')
        self.assertEqual(result['services']['Service manager']['state'], 'stopped')
        self.assertEqual(result['services']['Media library']['state'], 'unavailable')
        self.assertEqual(result['storage']['state'], 'unknown')
        self.assertEqual(result['next_actions'], doctor.next_actions(result))
        self.assertEqual(len(commands), 4)
        self.assertTrue(all(c[3] in ('info', 'inspect') if c[0]=='docker' else c[-4:] == ['df','-Pk','/','/var/lib/docker'] for c in commands))

    def test_unsafe_port_skips_http_probe(self):
        def run(args, **kwargs):
            if args[3] == 'info': return json.dumps({'ID':'test','Name':'colima-lab','OSType':'linux'})
            if args[3] == 'inspect':
                return json.dumps([{'Config':{'Labels':{'community-lab.trial':'true'},'Image':doctor.JELLYFIN},
                    'State':{'Running':True},'HostConfig':{'PortBindings':{'8096/tcp':[{'HostIp':'0.0.0.0','HostPort':'18096'}]}}}])
            return ''
        with patch('doctor.validate_isolation'),patch('doctor.subprocess.check_output',side_effect=run),patch('doctor.public_jellyfin') as http:
            result=doctor.report('unix:///fixture','test')
        http.assert_not_called()
        self.assertEqual(result['services']['Media library']['state'],'unknown')


class NextActionTests(unittest.TestCase):
    def sample(self, lab='known', storage='known', backup='recorded', manager='running', media='responding'):
        return {'observed_at': 'fixture', 'scope': 'Labelled fixture',
                'lab': doctor.finding(lab, 'Fixture lab', ''),
                'storage': doctor.finding(storage, 'Fixture storage', ''),
                'backup': doctor.finding(backup, 'Fixture backup', ''),
                'services': {'Service manager': doctor.finding(manager, 'Fixture manager', ''),
                             'Media library': doctor.finding(media, 'Fixture media', '')}}

    def test_mixed_states_are_prioritized_independent_of_input_order(self):
        result = self.sample(storage='low', backup='stale', manager='stopped', media='unavailable')
        expected = ['review-storage', 'refresh-recovery-check', 'recheck-media-library', 'confirm-service-manager']
        actions = doctor.next_actions(result)
        self.assertEqual([a['id'] for a in actions], expected)
        self.assertEqual([a['priority'] for a in actions], [10, 20, 40, 50])
        result['services'] = dict(reversed(list(result['services'].items())))
        self.assertEqual(doctor.next_actions(result), actions)
        plain = doctor.render(result)
        positions = [plain.index(a['action']) for a in actions]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('intentionally stopped', actions[-1]['action'])

    def test_unverified_lab_suppresses_even_contradictory_service_storage_diagnosis(self):
        for state in ('unknown', 'unexpected', None):
            result = self.sample(lab=state, storage='low', backup='stale', manager='stopped', media='unavailable')
            actions = doctor.next_actions(result)
            self.assertEqual([a['id'] for a in actions], ['verify-lab', 'refresh-recovery-check'])
            self.assertNotIn('low on space', json.dumps(actions))
            self.assertNotIn('intentionally stopped', json.dumps(actions))
            self.assertIn('not verified', actions[-1]['reason'])

    def test_unknown_measurements_and_stable_service_ties(self):
        actions = doctor.next_actions(self.sample(storage='unknown', backup='unknown', manager='unknown', media='unknown'))
        self.assertEqual([a['id'] for a in actions], ['verify-recovery', 'verify-storage', 'verify-service-manager', 'verify-media-library'])
        self.assertEqual(actions[2]['priority'], actions[3]['priority'])
        self.assertIn('unknown', actions[1]['reason'])
        minimal = doctor.next_actions({})
        self.assertEqual([a['id'] for a in minimal], ['verify-lab', 'verify-recovery'])

    def test_recovery_never_becomes_current_protection_even_with_healthy_services(self):
        for state, code in [('recorded', 'review-current-recovery'), ('stale', 'refresh-recovery-check'),
                            ('unknown', 'verify-recovery'), ('unsupported', 'verify-recovery')]:
            actions = doctor.next_actions(self.sample(backup=state))
            self.assertEqual([a['id'] for a in actions], [code])
            self.assertTrue('not verified' in actions[0]['reason'] or 'unknown' in actions[0]['reason'])

    def test_helper_pure_private_text_not_copied_and_results_not_shared(self):
        result = self.sample(storage='low', backup='stale', manager='stopped')
        secret = '/private/client TOKEN=secret unix:///socket'
        result['services'][secret] = doctor.finding('unavailable', secret, secret)
        result['storage']['summary'] = secret
        result['backup']['guidance'] = secret
        result['engine_id'] = secret
        before = copy.deepcopy(result)
        with patch('doctor.subprocess.check_output', side_effect=AssertionError('extra command')), \
             patch('doctor.validate_isolation', side_effect=AssertionError('extra probe')), \
             patch('doctor.public_jellyfin', side_effect=AssertionError('extra network')), \
             patch('builtins.open', side_effect=AssertionError('extra file access')):
            actions = doctor.next_actions(result)
        self.assertEqual(result, before)
        self.assertNotIn(secret, json.dumps(actions))
        actions[0]['action'] = 'changed output'
        self.assertNotEqual(doctor.next_actions(result), actions)

    def test_report_json_and_plain_guidance_share_actions_without_extra_commands(self):
        with patch('doctor.validate_isolation', side_effect=ValueError('private')), \
             patch('doctor.subprocess.check_output') as commands, patch('doctor.public_jellyfin') as http:
            result = doctor.report('unix:///fixture', 'test')
        commands.assert_not_called()
        http.assert_not_called()
        self.assertEqual(result['next_actions'], doctor.next_actions(result))
        self.assertEqual(json.loads(json.dumps(result))['next_actions'], result['next_actions'])
        for action in result['next_actions']:
            self.assertIn(action['action'], doctor.render(result))
            self.assertIn(action['reason'], doctor.render(result, details=True))


if __name__ == '__main__':
    unittest.main()
