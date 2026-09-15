"""Tests of the source-only review tool, not tests of Atlas's generator."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import check_coding_safety as guard

SOURCE = '''from work.previous import worker

def helper(function):
    return function

run = clone(worker, verify=check)
raise RuntimeError("This fixture must never be imported")
'''


class CodingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'tools').mkdir()
        self.source = self.root / 'route.py'
        self.source.write_text(SOURCE, encoding='utf-8')
        (self.root / 'test_route.py').write_text('# evidence path\n', encoding='utf-8')
        self.inventory = {
            'schema': guard.SCHEMA,
            'reviewed_public_commit': 'a' * 40,
            'scope': 'synthetic static fixture',
            'required_files': ['route.py', 'test_route.py'],
            'source_checks': [{
                'path': 'route.py',
                'imports': ['from work.previous import worker'],
                'adapters': ['clone(worker, verify=check)'],
                'anchors': ['def helper(function):\n    return function'],
            }],
        }

    def check(self):
        return guard.check(self.root, self.inventory)

    def change(self, before, after):
        self.source.write_text(SOURCE.replace(before, after), encoding='utf-8')

    def save_map(self):
        (self.root / 'tools/coding_safety_manifest.json').write_text(
            json.dumps(self.inventory), encoding='utf-8')

    def test_accepts_documented_wiring_without_importing_fixture(self):
        self.assertEqual(self.check(), [])

    def test_whitespace_and_comments_are_not_drift(self):
        self.change('run = clone(worker, verify=check)',
                    '# explanation\nrun=clone( worker, verify = check )')
        self.assertEqual(self.check(), [])

    def test_changed_import_requires_review(self):
        self.change('work.previous', 'work.other')
        self.assertTrue(any('import map' in e for e in self.check()))

    def test_nested_local_import_requires_review(self):
        self.change('return function', 'from work.hidden import thing\n    return function')
        self.assertTrue(any('import map' in e for e in self.check()))

    def test_removed_adapter_requires_review(self):
        self.change('run = clone(worker, verify=check)', 'run = worker')
        self.assertTrue(any('adapter target' in e for e in self.check()))

    def test_added_adapter_requires_review(self):
        self.change('run = clone(worker, verify=check)',
                    'run = clone(worker, verify=check)\nother = clone(worker, verify=check)')
        self.assertTrue(any('adapter target' in e for e in self.check()))

    def test_changed_adapter_target_requires_review(self):
        self.change('clone(worker,', 'clone(other_worker,')
        self.assertTrue(any('adapter target' in e for e in self.check()))

    def test_changed_override_requires_review(self):
        self.change('verify=check', 'verify=skip')
        self.assertTrue(any('adapter target' in e for e in self.check()))

    def test_attribute_adapter_is_detected(self):
        self.change('clone(worker', 'module.clone(worker')
        self.assertTrue(any('adapter target' in e for e in self.check()))

    def test_duplicate_call_multiplicity_is_preserved(self):
        self.inventory['source_checks'][0]['adapters'] *= 2
        self.assertTrue(any('adapter target' in e for e in self.check()))

    def test_helper_body_change_requires_review(self):
        self.change('return function', 'return None')
        self.assertTrue(any('helper/default/alias' in e for e in self.check()))

    def test_missing_required_test_is_failure(self):
        (self.root / 'test_route.py').unlink()
        self.assertTrue(any('test_route.py: missing file' in e for e in self.check()))

    def test_missing_source_is_failure(self):
        self.source.unlink()
        self.assertTrue(self.check())

    def test_syntax_error_is_failure(self):
        self.source.write_text('def broken(', encoding='utf-8')
        self.assertTrue(self.check())

    def test_invalid_encoding_is_failure(self):
        self.source.write_bytes(b'\xff')
        self.assertTrue(self.check())

    def test_invalid_expected_snippet_is_failure(self):
        self.inventory['source_checks'][0]['adapters'] = ['broken(']
        self.assertTrue(self.check())

    def test_path_escape_and_non_portable_paths_are_refused(self):
        for path in ('../outside.py', '/outside.py', 'C:/outside.py',
                     'nested\\outside.py', 'nested/../outside.py', './route.py',
                     'nested//outside.py', ''):
            with self.subTest(path=path):
                self.inventory['required_files'] = [path]
                self.assertTrue(self.check())

    def test_symlink_is_refused(self):
        link = self.root / 'alias.py'
        try:
            link.symlink_to(self.source)
        except (NotImplementedError, OSError):
            self.skipTest('this environment cannot create a test symlink')
        self.inventory['required_files'].append('alias.py')
        self.assertTrue(any('symlink' in e for e in self.check()))

    def test_duplicate_source_entries_are_refused(self):
        self.inventory['source_checks'] *= 2
        with self.assertRaises(guard.MapError):
            self.check()

    def test_empty_source_inventory_is_refused(self):
        self.inventory['source_checks'] = []
        with self.assertRaises(guard.MapError):
            self.check()

    def test_wrong_schema_is_refused(self):
        self.inventory['schema'] = 'unknown'
        with self.assertRaises(guard.MapError):
            self.check()

    def test_malformed_inventory_fields_are_refused(self):
        for field, value in [('required_files', []), ('scope', ''),
                             ('reviewed_public_commit', 'main')]:
            with self.subTest(field=field):
                changed = deepcopy(self.inventory)
                changed[field] = value
                with self.assertRaises(guard.MapError):
                    guard.check(self.root, changed)

    def test_unknown_inventory_field_is_refused(self):
        self.inventory['silently_update'] = True
        with self.assertRaises(guard.MapError):
            self.check()

    def test_oversized_source_is_refused(self):
        with patch.object(guard, 'MAX_FILE_BYTES', 16):
            self.assertTrue(any('size limit' in e for e in self.check()))

    def test_duplicate_json_key_is_refused(self):
        (self.root / 'tools/coding_safety_manifest.json').write_text(
            '{"schema":"one","schema":"two"}', encoding='utf-8')
        with self.assertRaises(guard.MapError):
            guard.load_map(self.root)

    def test_cli_success_is_read_only(self):
        self.save_map()
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file()}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.main(['--root', str(self.root)]), 0)
        after = {p.relative_to(self.root): p.read_bytes()
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertIn('Atlas was not imported or executed', output.getvalue())

    def test_cli_drift_is_nonzero_and_does_not_update_map(self):
        self.save_map()
        map_path = self.root / 'tools/coding_safety_manifest.json'
        original = map_path.read_bytes()
        self.change('verify=check', 'verify=skip')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(guard.main(['--root', str(self.root)]), 1)
        self.assertEqual(map_path.read_bytes(), original)

    def test_cli_missing_root_is_clean_failure(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(guard.main(['--root', str(self.root / 'absent')]), 1)

    def test_cli_bad_json_is_clean_failure(self):
        (self.root / 'tools/coding_safety_manifest.json').write_text('{', encoding='utf-8')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(guard.main(['--root', str(self.root)]), 1)

    def test_untracked_behaviour_is_explicitly_outside_scope(self):
        # This guard is not a semantic verifier: unrelated code is not certified.
        self.source.write_text(SOURCE + '\nphysical_constant = 123\n', encoding='utf-8')
        self.assertEqual(self.check(), [])

    def test_checked_in_route_inventory_matches_source(self):
        repository = Path(__file__).resolve().parents[1]
        self.assertEqual(guard.check(repository, guard.load_map(repository)), [])


if __name__ == '__main__':
    unittest.main()
