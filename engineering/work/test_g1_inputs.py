"""Focused numeric/prepared-input boundaries; no regional or annual run."""
from copy import deepcopy
import hashlib
import io as streams
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from work.generator_upgrade_r15 import regional as old
from work.generator_upgrade_r17 import fields as old_fields
from work.geology_r1 import fields, io, working


def record(path, key=None):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'array_key': key, 'grid': {'frame_id': 'TEST', 'unit': 'm',
            'sample_location': 'cell_centres', 'first_sample_m': [0, 0], 'step_m': [1, 1]},
        'registration': {'source_frame_id': 'TEST', 'target_frame_id': 'TEST',
            'target_to_source_affine': [[1., 0., 0.], [0., 1., 0.]],
            'evidence': 'explicit synthetic transform', 'source_status': 'SYNTHETIC TEST'},
        'unit': 'm', 'role': 'continuous_constraint_prior',
        'reference': {'world_id': 'TEST', 'snapshot_id': 'TEST', 'vertical_reference': None},
        'evidence': 'synthetic boundary fixture', 'source_status': 'SYNTHETIC TEST'}


SUPPORTS = {'p': {'xy_m': [0.5, 0.5], 'area_m2': 1}}


def science_without_execution_identity(value):
    value = deepcopy(value)
    # These exact two locations describe implementation, not physical output.
    value['source_sha256'] = '<execution source identity>'
    value['regional_input']['execution_binding_sha256'] = '<execution source identity>'
    return value


class InputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='g1i-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'a.npy'
        np.save(self.path, np.arange(4, dtype='float64').reshape(2, 2))

    def test_bounded_reader_numeric_parity_and_archive(self):
        r = record(self.path)
        np.testing.assert_array_equal(old.read_field(r), io.read_field(r))
        z = self.root/'a.npz'
        np.savez_compressed(z, a=np.arange(4, dtype='float64').reshape(2, 2))
        r = record(z, 'a')
        np.testing.assert_array_equal(old.read_field(r), io.read_field(r))
        r['array_key'] = None
        with self.assertRaises(ValueError):
            io.read_field(r)
        np.save(self.path, np.array([[{}]], dtype=object))
        with self.assertRaises(ValueError):
            io.read_field(record(self.path))

    def test_chunks_growth_size_and_sha(self):
        raw = b'abcdefgh'
        sizes = []
        class Growing(streams.BytesIO):
            def read(self, size=-1):
                sizes.append(size)
                return super().read(size)
        with patch.object(io, 'CHUNK_BYTES', 3), patch.object(io.Path, 'open', return_value=Growing(raw)), \
                patch.object(io.Path, 'stat', return_value=SimpleNamespace(st_size=1)):
            with self.assertRaisesRegex(ValueError, 'byte budget'):
                io.read_bound(self.path, hashlib.sha256(raw).hexdigest(), limit=7)
        self.assertLessEqual(max(sizes), 3)
        r = record(self.path)
        with self.assertRaises(ValueError):
            io.read_bound(self.path, r['sha256'], self.path.stat().st_size-1)
        with self.assertRaises(ValueError):
            io.verify_bound(self.path, '0'*64)

    def test_prepared_exact_records_detachment_and_no_redecode(self):
        source = record(self.path)
        sources = {'a': source, 'b': deepcopy(source)}
        expected = old_fields.sample_fields(sources, SUPPORTS, 'TEST', 'SYNTHETIC TEST')
        with patch.object(io, 'read_field', wraps=io.read_field) as reader:
            with fields.Prepared(sources, 'TEST', 'SYNTHETIC TEST') as prepared:
                self.assertEqual(reader.call_count, 1)
                sources['a']['grid']['first_sample_m'][0] = 800
                first = prepared.sample(SUPPORTS)
                self.assertEqual(first, expected)
                first['sources']['a']['registration']['target_to_source_affine'][0][0] = 30
                first['samples']['p']['a'] = 20
                self.assertEqual(prepared.sample(SUPPORTS), expected)
                self.assertEqual(reader.call_count, 1)
                # Storage cannot be made writable, even through its NumPy base.
                array = prepared._Prepared__arrays[0][1]
                with self.assertRaises(ValueError):
                    array.flags.writeable = True
                with self.assertRaises(ValueError):
                    array.base.flags.writeable = True
        with self.assertRaises(ValueError):
            prepared.sample(SUPPORTS)
        other = deepcopy(source)
        source = record(self.path)
        other = deepcopy(source); other['unit'] = 'km'
        with patch.object(io, 'read_field', wraps=io.read_field) as reader:
            with fields.Prepared({'a': source, 'b': other}, 'TEST', 'SYNTHETIC TEST'):
                self.assertEqual(reader.call_count, 2)

    def test_field_collection_limit_precedes_second_decode(self):
        r = record(self.path); other = deepcopy(r); other['unit'] = 'km'
        with patch.object(io.np, 'load', wraps=io.np.load) as decoder:
            with self.assertRaisesRegex(ValueError, 'byte budget'):
                fields.Prepared({'a': r, 'b': other}, 'TEST', 'SYNTHETIC TEST', max_total_bytes=63)
            self.assertEqual(decoder.call_count, 1)

    def test_drift_unknown_registration_and_mask_fail_closed(self):
        r = record(self.path)
        with fields.Prepared({'a': r}, 'TEST', 'SYNTHETIC TEST') as prepared:
            np.save(self.path, np.ones((2, 2), dtype='float64'))
            with self.assertRaisesRegex(ValueError, 'changed'):
                prepared.sample(SUPPORTS)
        np.save(self.path, np.array([[0., np.nan], [1., 2.]]))
        with fields.Prepared({'a': record(self.path)}, 'TEST', 'SYNTHETIC TEST') as prepared:
            with self.assertRaisesRegex(ValueError, 'UNKNOWN'):
                prepared.sample(SUPPORTS)
        r = record(self.path); r['registration']['target_frame_id'] = 'OTHER'
        with self.assertRaisesRegex(ValueError, 'target differs'):
            fields.Prepared({'a': r}, 'TEST', 'SYNTHETIC TEST')
        z = self.root/'mask.npz'; np.savez(z, valid=np.array([[1, 2], [1, 1]], dtype='uint8'))
        spec = {'source_root': str(self.root), 'frame': {'array_shape': [2, 2]},
                'selection': {}, 'sources': {'validity_masks': {'relative_path': z.name,
                'sha256': hashlib.sha256(z.read_bytes()).hexdigest(), 'size_bytes': z.stat().st_size}},
                'source_resolution': {'validity_array': 'valid'}}
        with self.assertRaisesRegex(ValueError, 'not Boolean'):
            working._mask(spec)

    def test_one_owner_support_preserved_with_repeated_prepared_build(self):
        from work.generator_upgrade_r18 import working as retained
        spec = working.inputs()
        supports = dict(list(working.case_supports(spec).items())[:1])
        expected = science_without_execution_identity(retained.build(supports)['scientific'])
        with working.Prepared() as prepared:
            self.assertLessEqual(prepared.nbytes, fields.MAX_TOTAL_ARRAY_BYTES)
            result = prepared.build(supports)
            self.assertEqual(science_without_execution_identity(result['scientific']), expected)
            result['scientific']['regional_input']['owner_programme']['evidence'] = 'caller mutation'
            self.assertEqual(science_without_execution_identity(prepared.build(supports)['scientific']), expected)
        with self.assertRaisesRegex(ValueError, 'closed'):
            prepared.build(supports)

    def test_prepared_rechecks_resolved_source_locations(self):
        with working.Prepared() as prepared:
            with patch.object(working, '_bindings', return_value=()):
                with self.assertRaisesRegex(ValueError, 'source paths changed'):
                    prepared.verify_sources()


if __name__ == '__main__':
    unittest.main()
