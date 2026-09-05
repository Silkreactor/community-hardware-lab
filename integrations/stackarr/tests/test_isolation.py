# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import yaml
import acceptance
from isolation import validate_isolation
import provision


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.sock_path = self.home / '.colima/lab/docker.sock'
        self.sock_path.parent.mkdir(parents=True)
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(self.sock_path))
        self.host = 'unix://' + str(self.sock_path)
        self.config_path = self.home / '.colima/_lima/colima-lab/lima.yaml'
        self.config_path.parent.mkdir(parents=True)
        self.config = {'vmType': 'vz', 'ssh': {'forwardAgent': False, 'loadDotSSHPubKeys': False},
                       'portForwards': [{'guestSocket': '/var/run/docker.sock', 'hostSocket': str(self.sock_path)}]}
        self.write()
        self.home_patch = patch('isolation.Path.home', return_value=self.home)
        self.home_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        self.sock.close()
        self.temp.cleanup()

    def write(self):
        self.config_path.write_text(yaml.safe_dump(self.config))

    def test_valid_exact_pair(self):
        self.assertEqual(validate_isolation(self.host)['socket'], str(self.sock_path))

    def test_different_socket_with_a_plausible_name_refused(self):
        wrong = self.home / 'other.sock'
        with socket.socket(socket.AF_UNIX) as other:
            other.bind(str(wrong))
            with self.assertRaises(ValueError):
                validate_isolation('unix://' + str(wrong))

    def test_config_cannot_describe_a_different_socket(self):
        self.config['portForwards'][0]['hostSocket'] = '/some/other/docker.sock'
        self.write()
        with self.assertRaises(ValueError):
            validate_isolation(self.host)

    def test_host_mounts_in_alternate_yaml_format_refused(self):
        for text in ('mounts: [{location: /private}]\n', 'mounts:\n    - location: /private\n'):
            self.write()
            with self.config_path.open('a') as stream:
                stream.write(text)
            with self.assertRaises(ValueError):
                validate_isolation(self.host)

    def test_agent_true_string_or_missing_refused(self):
        for value in (True, 'false', None):
            self.config['ssh']['forwardAgent'] = value
            self.write()
            with self.assertRaises(ValueError):
                validate_isolation(self.host)

    def test_missing_and_malformed_configuration_refused(self):
        self.config_path.unlink()
        with self.assertRaises(ValueError):
            validate_isolation(self.host)
        self.config_path.write_text('ssh: [unclosed')
        with self.assertRaises(ValueError):
            validate_isolation(self.host)

    def test_duplicate_yaml_cannot_hide_mounts(self):
        with self.config_path.open('a') as stream:
            stream.write('mounts: [{location: /private}]\nmounts: []\n')
        with self.assertRaises(ValueError):
            validate_isolation(self.host)

    def test_regular_file_is_not_socket(self):
        self.sock.close()
        self.sock_path.unlink()
        self.sock_path.write_text('not a socket')
        with self.assertRaises(ValueError):
            validate_isolation(self.host)

    def test_acceptance_rechecks_configuration_drift_before_docker(self):
        trial = object.__new__(acceptance.Trial)
        trial.docker = ['docker', '--host', self.host]
        self.config['mounts'] = [{'location': '/private'}]
        self.write()
        with patch.object(trial, 'inspect') as inspect:
            with self.assertRaises(ValueError):
                trial.guard('lab-media')
        inspect.assert_not_called()

    def test_mocked_empty_engine_provisioning_commands_stay_scoped(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            args = command[3:]
            if args[0] == 'info':
                return json.dumps({'Name': 'colima-lab', 'OSType': 'linux', 'Containers': 0, 'ID': 'test-engine'})
            if args[:2] == ['volume', 'ls']:
                return ''
            if '--entrypoint' in args and args[args.index('--entrypoint') + 1] == 'stat':
                return '991'
            return 'synthetic-result'
        with patch('provision.RUNTIME', self.home / 'runtime'), patch('provision.subprocess.check_output', side_effect=run):
            provision.provision(self.host)
        self.assertTrue(all(c[:3] == ['docker', '--host', self.host] for c in commands))
        pulls = [c[4] for c in commands if c[3] == 'pull']
        self.assertEqual(pulls, [acceptance.STACKARR, acceptance.JELLYFIN])
        starts = [c for c in commands if c[3:5] == ['run', '-d']]
        self.assertEqual(len(starts), 2)
        self.assertIn('127.0.0.1:18096:8096', starts[1])
        self.assertIn('991', starts[0])
        self.assertTrue(all('--privileged' not in c and '--network=host' not in c for c in commands))


if __name__ == '__main__':
    unittest.main()
