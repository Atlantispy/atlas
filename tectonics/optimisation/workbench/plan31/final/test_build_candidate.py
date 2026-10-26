"""Source-only actual receiving and refusal controls; no native/runtime launch."""
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]


def loaded(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE/filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class FinalSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = loaded('final_source_under_test', 'build_candidate.py')
        cls.temporary = tempfile.TemporaryDirectory(prefix='p31-')
        cls.root = Path(cls.temporary.name)
        cls.out = cls.root/'source'
        cls.result = cls.builder.materialise(REPO, cls.out)
        cls.b, cls.tier, cls.readers, cls.utilities, cls.mapping = cls.builder.contract(REPO)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_actual_complete_receiving(self):
        result = self.result
        self.assertEqual((result['source_members'], result['native_members'], result['helper_members']), (697, 287, 410))
        self.assertEqual(len(result['changed_rows_from_s1a']), 15)
        self.assertEqual(self.builder.verify_inventory(self.out, result['files'], self.utilities), result['files'])
        for name, pin in self.mapping['native_runtime_outputs'].items():
            self.assertEqual(result['files'][name], pin)
        for flag in (*self.builder.FLAGS, 'IV_permitted', 'N9_width_selected', 'condition5_selected', 'private_A1_selected'):
            self.assertIs(result[flag], False)

    def test_changed_component_pin_refuses(self):
        before = copy.deepcopy(self.builder.COMPONENTS)
        try:
            self.builder.COMPONENTS['b']['sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'source pin differs'):
                self.builder.materialise(REPO, self.root/'wrong-pin')
            self.assertFalse((self.root/'wrong-pin').exists())
        finally:
            self.builder.COMPONENTS.clear()
            self.builder.COMPONENTS.update(before)

    def test_occupied_output_refuses(self):
        with self.assertRaises(FileExistsError):
            self.builder.materialise(REPO, self.out)
        self.builder.verify_inventory(self.out, self.result['files'], self.utilities)

    def test_overlapping_repo_refuses(self):
        candidate = HERE/'not-an-output'
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.builder.materialise(REPO, candidate)
        self.assertFalse(candidate.exists())

    def test_mixed_predecessor_refuses(self):
        _, _, mapping, transform, prerequisite = self.tier.load(REPO)
        raws = {row['member']: self.utilities.read_source(REPO, row['public_base']) for row in mapping['rows']}
        first = next(iter(raws))
        raws[first] += b'\n# disposable source fault\n'
        with self.assertRaises(ValueError):
            self.tier.derive(raws, mapping, transform, prerequisite)

    def test_undeclared_output_member_refuses(self):
        extra = self.out/'unexpected.py'
        extra.write_bytes(b'# disposable\n')
        try:
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                self.builder.verify_inventory(self.out, self.result['files'], self.utilities)
        finally:
            extra.unlink()

    def test_changed_output_bytes_refuse(self):
        target = self.out/'helpers/run_fresh_interval.py'
        before = target.read_bytes()
        try:
            target.write_bytes(before+b'\n# disposable\n')
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                self.builder.verify_inventory(self.out, self.result['files'], self.utilities)
        finally:
            target.write_bytes(before)

    def test_linked_output_parent_refuses(self):
        real, alias = self.root/'real', self.root/'alias'
        real.mkdir()
        try:
            os.symlink(real, alias, target_is_directory=True)
        except OSError as error:
            self.skipTest('Windows symlink creation unavailable: '+str(error))
        try:
            with self.assertRaises(ValueError):
                self.builder.materialise(REPO, alias/'child')
            self.assertFalse((real/'child').exists())
        finally:
            alias.unlink()

    def test_explicit_emitter_context_cannot_rebind(self):
        emitter = loaded('explicit_final_context', 'source_emitter.py')
        binding = {'path': str(self.root/'component.py'), 'sha256': '509936760484459ce1f41aca15965d33dab5e2be26a2eae18df63bf5c7d44f60'}
        emitter.configure(control_root=self.root/'controls', workspace=self.root/'workspace', plan02_binding=binding)
        self.assertEqual(emitter.TARGET, self.root/'workspace/ac/n12f-r1')
        with self.assertRaisesRegex(ValueError, 'already bound'):
            emitter.configure(control_root=self.root/'other', workspace=self.root/'other', plan02_binding=binding)

    def test_wrong_component_binding_refuses_before_io(self):
        emitter = loaded('wrong_final_context', 'source_emitter.py')
        with self.assertRaisesRegex(ValueError, 'accepted Plan02'):
            emitter.configure(control_root=self.root/'controls', workspace=self.root/'workspace',
                              plan02_binding={'path': str(self.root/'missing.py'), 'sha256': '0'*64})
        self.assertIsNone(emitter.HERE)

    def test_explicit_public_component_path_has_no_fallback(self):
        support = loaded('explicit_profile_dependency', 'profile_support.py')
        binding = support.public_plan02(REPO)
        self.assertEqual(Path(binding['path']), REPO/support.PLAN02_RELATIVE)
        self.assertEqual(binding['sha256'], support.PLAN02_SHA256)
        with self.assertRaisesRegex(ValueError, 'explicit absolute'):
            support.public_plan02('relative-root')


if __name__ == '__main__':
    unittest.main(verbosity=2)
