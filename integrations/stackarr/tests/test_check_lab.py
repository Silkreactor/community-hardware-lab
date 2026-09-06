# SPDX-License-Identifier: GPL-3.0-only
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import check_lab


class CheckLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / check_lab.REFERENCE
        self.path.parent.mkdir(parents=True)
        self.engine_id = '00000000-0000-0000-0000-000000000001'
        raw = json.dumps({'engine': {'ID': self.engine_id, 'Name': 'colima-lab'}}).encode()
        self.path.write_bytes(raw)
        self.sha = patch('check_lab.REFERENCE_SHA256', hashlib.sha256(raw).hexdigest())
        self.sha.start()

    def tearDown(self):
        self.sha.stop()
        self.temp.cleanup()

    def test_reads_identity_only_from_existing_reviewed_record(self):
        host, identity, evidence = check_lab.load_reference(self.root)
        self.assertEqual(identity, self.engine_id)
        self.assertEqual(host, 'unix://' + str(check_lab.lab_socket_path()))
        self.assertEqual(evidence, self.path)
        self.assertFalse((self.root/'engine.json').exists())

    def test_missing_and_changed_reference_refused(self):
        self.path.write_bytes(self.path.read_bytes() + b' ')
        with self.assertRaises(check_lab.SetupProblem):
            check_lab.load_reference(self.root)
        self.path.unlink()
        with self.assertRaises(check_lab.SetupProblem):
            check_lab.load_reference(self.root)

    def test_conflicting_and_duplicate_setup_fields_refused(self):
        expected={'id': self.engine_id, 'host': 'unix://' + str(check_lab.lab_socket_path()), 'name': 'colima-lab'}
        setup=self.root/'engine.json';setup.write_text(json.dumps(expected))
        self.assertEqual(check_lab.load_reference(self.root)[1], self.engine_id)
        for changed in ({**expected,'id':'00000000-0000-0000-0000-000000000002'},
                        {**expected,'host':'unix:///var/run/docker.sock'}, {**expected,'name':'default'},
                        {**expected,'extra':True}):
            setup.write_text(json.dumps(changed))
            with self.assertRaises(check_lab.SetupProblem):
                check_lab.load_reference(self.root)
        setup.write_text('{"id":"other",'+json.dumps(expected)[1:])
        with self.assertRaises(check_lab.SetupProblem):
            check_lab.load_reference(self.root)

    def test_symlinked_reference_and_setup_refused(self):
        original=self.path.read_bytes();self.path.unlink()
        target=self.root/'copy.json';target.write_bytes(original);self.path.symlink_to(target)
        with self.assertRaises(check_lab.SetupProblem):
            check_lab.load_reference(self.root)
        self.path.unlink();self.path.write_bytes(original)
        (self.root/'engine.json').symlink_to(self.root/'missing')
        with self.assertRaises(check_lab.SetupProblem):
            check_lab.load_reference(self.root)
        (self.root/'engine.json').unlink()
        (self.root/'engine.json').symlink_to(self.root/'engine.json')
        with self.assertRaises(check_lab.SetupProblem):
            check_lab.load_reference(self.root)

    def test_invalid_setup_never_calls_doctor_or_discovery(self):
        with patch('check_lab.load_reference',side_effect=check_lab.SetupProblem('The saved setup has changed since it was verified.')),patch('check_lab.report') as doctor,contextlib.redirect_stdout(io.StringIO()) as output:
            code=check_lab.main([])
        self.assertEqual(code,2);doctor.assert_not_called()
        self.assertIn('Nothing was started or changed',output.getvalue())

    def test_passes_only_verified_reference_to_same_doctor(self):
        saved=('unix:///fixture',self.engine_id,self.path)
        result={'lab':{'state':'unknown'}}
        with patch('check_lab.load_reference',return_value=saved),patch('check_lab.report',return_value=result) as doctor,patch('check_lab.render',return_value='unavailable') as render,contextlib.redirect_stdout(io.StringIO()):
            code=check_lab.main(['--details'])
        doctor.assert_called_once_with(*saved);render.assert_called_once_with(result,True)
        self.assertEqual(code,2)

    def test_wrapper_missing_runtime_is_explanatory_and_does_not_install(self):
        wrapper=Path(__file__).resolve().parents[3]/'check-my-lab'
        copied=self.root/'check-my-lab';shutil.copyfile(wrapper,copied);copied.chmod(0o755)
        result=subprocess.run([str(copied)],cwd='/',capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('Nothing was installed or started',result.stdout)
        self.assertFalse((self.root/'.runtime').exists())

    def test_missing_dependencies_are_explained_without_traceback(self):
        source=Path(check_lab.__file__)
        result=subprocess.run([sys.executable,'-S',str(source)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('tools are incomplete',result.stdout)
        self.assertNotIn('Traceback',result.stderr)


if __name__ == '__main__':
    unittest.main()
