"""Reuse of a previous run refuses when the two trees' control case files differ (landing 1, addendum 2 G1)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atlas_tectonics._private.integration import reuse_previous_run as REUSE


class _Profile:
    def __init__(self, sha256, native_root, workspace):
        self.sha256, self._row = sha256, {
            'workspace': workspace, 'historical_inputs': 'inputs', 'native_root': native_root,
            'qualification_status': REUSE.DIAGNOSTIC, REUSE.F.QUERY_STORE_FLAG: 'store'}

    def record(self):
        return dict(self._row)


class ReusePreviousRunCaseFileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.workspace = folder.name
        for tree in ('old', 'new'):
            cases = Path(folder.name)/tree/'atlas_tectonics'/'_fixtures'/'cases'
            cases.mkdir(parents=True)
            for name in ('a.json', 'b.json'):
                (cases/name).write_bytes(b'{"case": "' + name.encode() + b'"}')

    def plan(self, new_root='new'):
        new, old = _Profile('1'*64, new_root, self.workspace), _Profile('2'*64, 'old', self.workspace)
        with mock.patch('atlas_tectonics.integration.reuse.execution_identity', return_value='3'*64):
            return REUSE.plan(new, None, 'previous.json', old.sha256, previous=old)

    def test_equal_case_files_pass(self):
        self.assertEqual(self.plan()['execution_identity'], '3'*64)

    def test_one_changed_byte_refuses_and_names_the_file(self):
        path = Path(self.workspace)/'new'/'atlas_tectonics'/'_fixtures'/'cases'/'b.json'
        path.write_bytes(path.read_bytes()[:-1] + b']')
        with self.assertRaisesRegex(Exception, r'differ in control case files: b\.json$'):
            self.plan()

    def test_same_root_does_not_hash(self):
        with mock.patch.object(REUSE, '_case_files', side_effect=AssertionError('hashed')):
            self.assertEqual(self.plan(new_root='old')['execution_identity'], '3'*64)


if __name__ == '__main__':
    unittest.main()
