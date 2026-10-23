"""Boundary controls for immutable selected source construction; no Atlas imports."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_selection as B


class ConstructionBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='heat-builder-control-')
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.here = self.repo / 'authoring'
        self.here.mkdir()
        base = self.repo / 'base.py'
        base.write_bytes(b'VALUE = 1\n')
        entry = dict(member='source/src/atlas_tectonics/base.py', public_path='base.py',
                     public_sha256=B.digest(base.read_bytes()))
        parent = json.dumps(dict(entries=[entry])).encode()
        (self.repo / 'parent.json').write_bytes(parent)
        self.parent_sha = B.digest(parent)
        self.entries = [entry]
        for name in B.C8:
            relative = B.PREFIX + 'implementation-r1/solve-finish/' + name
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'VALUE = 2\n')
            self.entries.append(dict(member='source/helpers/' + name, public_path=relative,
                                     public_sha256=B.digest(path.read_bytes())))
        self.mapping = dict(schema='atlas.plan40b.receiving-source-map/v1', receiving_bindings_complete=True,
                            selected_candidates=['C3', 'C8'], runtime_admission=False,
                            checkpoint_migration=False, scientific_acceptance=False,
                            predecessor_source_map_sha256=self.parent_sha, entries=self.entries,
                            public_selection_sha256=B.generation(self.entries))
        for name, value in (('PARENT', 'parent.json'), ('PARENT_SHA', self.parent_sha), ('HERE', self.here)):
            context = patch.object(B, name, value)
            context.start()
            self.addCleanup(context.stop)
        self.save()

    def save(self):
        (self.here / 'SOURCE-MAP.json').write_text(json.dumps(self.mapping), encoding='utf-8')

    def test_complete_build_and_existing_destination_refusal(self):
        output = self.repo / 'built'
        result = B.materialise(self.repo, output)
        self.assertEqual(result['files'], 4)
        self.assertEqual((output / 'src/atlas_tectonics/base.py').read_bytes(), b'VALUE = 1\n')
        sentinel = output / 'keep.txt'
        sentinel.write_text('preserve', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            B.materialise(self.repo, output)
        self.assertEqual(sentinel.read_text(), 'preserve')

    def test_source_drift_refuses_before_creating_output(self):
        (self.repo / 'base.py').write_bytes(b'changed\n')
        output = self.repo / 'not-created'
        with self.assertRaisesRegex(ValueError, 'drift'):
            B.materialise(self.repo, output)
        self.assertFalse(output.exists())

    def test_receipt_binds_validated_map_snapshot(self):
        map_path = self.here / 'SOURCE-MAP.json'
        validated_bytes = map_path.read_bytes()
        validate = B.validate_map

        def replace_map_after_validation(repo, mapping):
            payloads = validate(repo, mapping)
            map_path.write_bytes(b'{"different": "later authoring state"}\n')
            return payloads

        output = self.repo / 'built'
        with patch.object(B, 'validate_map', side_effect=replace_map_after_validation):
            B.materialise(self.repo, output)
        receipt = json.loads((output / 'SOURCE-MANIFEST.json').read_bytes())
        self.assertEqual(receipt['source_map_sha256'], B.digest(validated_bytes))
        self.assertEqual(receipt['selection_sha256'], self.mapping['public_selection_sha256'])
        self.assertEqual((output / 'src/atlas_tectonics/base.py').read_bytes(), b'VALUE = 1\n')

    def test_missing_duplicate_escape_and_unrelated_rebinding_refused(self):
        variants = []
        missing = copy.deepcopy(self.mapping)
        missing['entries'].pop()
        variants.append(missing)
        duplicate = copy.deepcopy(self.mapping)
        duplicate['entries'].append(copy.deepcopy(duplicate['entries'][0]))
        variants.append(duplicate)
        escape = copy.deepcopy(self.mapping)
        escape['entries'][0]['public_path'] = '../outside.py'
        variants.append(escape)
        rebound = copy.deepcopy(self.mapping)
        rebound['entries'][0]['public_sha256'] = 'f' * 64
        variants.append(rebound)
        for mapping in variants:
            mapping['public_selection_sha256'] = B.generation(mapping['entries'])
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                B.validate_map(self.repo, mapping)

    def test_identity_and_false_admission_cannot_be_upgraded(self):
        for field, value in (('public_selection_sha256', '0' * 64), ('runtime_admission', True),
                             ('checkpoint_migration', True), ('scientific_acceptance', True),
                             ('receiving_bindings_complete', False)):
            mapping = copy.deepcopy(self.mapping)
            mapping[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                B.validate_map(self.repo, mapping)


if __name__ == '__main__':
    unittest.main()
