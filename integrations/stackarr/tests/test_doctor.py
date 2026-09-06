# SPDX-License-Identifier: GPL-3.0-only
from datetime import datetime, timezone, timedelta
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


if __name__ == '__main__':
    unittest.main()
