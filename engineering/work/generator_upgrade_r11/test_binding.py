"""New successor byte bindings preserve all sealed parents."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from . import binding, provenance


class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load()

    def test_sealed_parent_preserved(self):
        self.assertEqual(self.bundle.parent.verify(), provenance.PARENT_SOURCE_SHA256)
        self.assertEqual(len(provenance.retained_record()['source_snapshot']), 29)

    def test_actual_transport_and_crop_sources(self):
        self.assertEqual(Path(self.bundle.transport.__file__), provenance.TASK/'work/generator_upgrade_r2/multicommodity.py')
        self.assertEqual(Path(self.bundle.agroclimate.__file__), provenance.TASK/'work/generator_upgrade_r1/agroclimate.py')
        self.bundle.graph.verify()

    def test_actual_carbon_and_nutrient_sources(self):
        self.assertEqual(Path(self.bundle.organic.__file__), provenance.TASK/'work/generator_upgrade_r7/organic.py')
        self.assertEqual(Path(self.bundle.fertility.__file__), provenance.TASK/'work/generator_upgrade_r7/fertility.py')

    def test_no_canonical_predecessor_imports(self):
        self.assertFalse(any(k.startswith(('work.generator_upgrade_r10.', 'work.generator_upgrade_r7.')) for k in sys.modules))

    def test_private_module_ignores_stale_canonical(self):
        name = 'work.generator_upgrade_r11.snapshot'; fake = types.ModuleType(name); fake.marker = True
        with patch.dict(sys.modules, {name: fake}):
            result = self.bundle.module('snapshot')
        self.assertIsNot(result, fake); self.assertFalse(hasattr(result, 'marker'))

    def test_wrong_source_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source changed'):
            provenance.checked(provenance.HERE/'binding.py', '0'*64)

    def test_relative_and_traversing_paths_rejected(self):
        for path in ('binding.py', str(provenance.HERE/'..'/'binding.py')):
            with self.assertRaises(ValueError):
                provenance.checked(path)

    def test_undeclared_project_import_rejected(self):
        with self.assertRaisesRegex(ValueError, 'undeclared'):
            self.bundle.graph.import_module('work.undeclared', fromlist=('solver',))

    def test_actual_species_owner_delivery_bound_not_inferred(self):
        package = self.bundle.module('owner_inputs').species(self.bundle)
        self.assertEqual(package['manifest_sha256'], provenance.SPECIES_MANIFEST_SHA256)
        self.assertEqual(len(package['source_bindings']), 24)
        entry = package['documents']['BIOLOGICAL_INPUT_CONTRACT_R1.json']
        self.assertEqual(entry['counts']['identities'], 36)
        self.assertEqual(entry['compiler_ready_numeric_field_records'], [])

    def test_owner_delivery_change_requires_rebinding_not_silent_adoption(self):
        altered = dict(self.bundle.identity['external_reference_sources'])
        altered[str(provenance.SPECIES_MANIFEST)] = '0'*64
        with patch.dict(self.bundle.identity, {'external_reference_sources': altered}):
            with self.assertRaisesRegex(ValueError, 'binding changed'):
                self.bundle.module('owner_inputs').species(self.bundle)


if __name__ == '__main__':
    unittest.main()
