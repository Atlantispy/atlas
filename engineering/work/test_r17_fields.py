"""Two focused synthetic field checks; no owner values or model runs."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from work.generator_upgrade_r17 import fields


def fixture(directory):
    path = Path(directory)/'prior.npy'
    np.save(path, np.array([[2., 6., 18.], [10., -2., 14.]]))
    record = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'array_key': None,
        'grid': {'frame_id': 'SOURCE', 'unit': 'm', 'sample_location': 'nodes',
                 'first_sample_m': [12., -3.], 'step_m': [-4., 3.]},
        'registration': {'source_frame_id': 'SOURCE', 'target_frame_id': 'TARGET',
            'target_to_source_affine': [[1., 0., 2.], [0., 1., -3.]],
            'evidence': 'SYNTHETIC TEST registration', 'source_status': 'SYNTHETIC TEST'},
        'unit': 'dimensionless', 'role': 'continuous_constraint_prior',
        'reference': {'world_id': 'SYNTHETIC', 'snapshot_id': 'FIXED', 'vertical_reference': None},
        'evidence': 'SYNTHETIC TEST field', 'source_status': 'SYNTHETIC TEST'}
    supports = {'first': {'xy_m': [10., 0.], 'area_m2': 7.},
                'interior': {'xy_m': [8., 1.5]}, 'last': {'xy_m': [2., 3.]}}
    return {'prior': record, 'same_record': deepcopy(record)}, supports


class FieldTests(unittest.TestCase):
    def test_signed_unequal_grid_samples_identity_and_distinct_read(self):
        with tempfile.TemporaryDirectory() as directory:
            records, supports = fixture(directory)
            second = Path(directory)/'other.npy'
            np.save(second, np.array([[12., 16., 28.], [20., 8., 24.]]))
            records['other'] = deepcopy(records['prior'])
            records['other'].update(path=str(second), sha256=hashlib.sha256(second.read_bytes()).hexdigest())
            before_records, before_supports = deepcopy(records), deepcopy(supports)
            with patch.object(fields.regional, 'read_field', wraps=fields.regional.read_field) as reader:
                result = fields.sample_fields(records, supports, 'TARGET', 'SYNTHETIC TEST')
            self.assertEqual(reader.call_count, 2)
            self.assertEqual(result['samples'], {
                'first': {'prior': 2., 'same_record': 2., 'other': 12.},
                'interior': {'prior': 4., 'same_record': 4., 'other': 14.},
                'last': {'prior': 14., 'same_record': 14., 'other': 24.}})
            self.assertEqual(result['sources'], before_records)
            self.assertEqual(result['supports'], before_supports)
            self.assertEqual(records, before_records)
            self.assertEqual(supports, before_supports)
            records['prior']['grid']['step_m'][0] = 9.
            supports['first']['xy_m'][0] = 99.
            self.assertEqual(result['sources'], before_records)
            self.assertEqual(result['supports'], before_supports)

    def test_changed_unknown_outside_mismatched_and_unbounded_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            records, supports = fixture(directory)
            changed = deepcopy(records)
            changed['prior']['sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'source changed'):
                fields.sample_fields(changed, supports, 'TARGET', 'SYNTHETIC TEST')
            with self.assertRaisesRegex(ValueError, 'source status'):
                fields.sample_fields(records, supports, 'TARGET', 'UNKNOWN')
            for key in ('source_status', 'registration'):
                changed = deepcopy(records)
                if key == 'source_status':
                    changed['prior'][key] = 'UNKNOWN'
                else:
                    changed['prior'][key]['source_status'] = 'WORKING NON-CANON'
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'status differs'):
                    fields.sample_fields(changed, supports, 'TARGET', 'SYNTHETIC TEST')
            with self.assertRaisesRegex(ValueError, 'target frame'):
                fields.sample_fields(records, supports, 'OTHER', 'SYNTHETIC TEST')
            outside = deepcopy(supports); outside['first']['xy_m'] = [11., 0.]
            with self.assertRaisesRegex(ValueError, 'outside'):
                fields.sample_fields(records, outside, 'TARGET', 'SYNTHETIC TEST')
            path = Path(records['prior']['path'])
            np.save(path, np.array([[2., np.nan, 18.], [10., -2., 14.]]))
            for record in records.values():
                record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'UNKNOWN source coverage'):
                fields.sample_fields(records, supports, 'TARGET', 'SYNTHETIC TEST')
            for bad_records, bad_supports in (({}, supports), (records, {}),
                    ({str(i): records['prior'] for i in range(65)}, supports),
                    (records, {str(i): supports['first'] for i in range(33)})):
                with self.assertRaisesRegex(ValueError, 'between 1 and'):
                    fields.sample_fields(bad_records, bad_supports, 'TARGET', 'SYNTHETIC TEST')
            with patch.object(fields.regional, 'MAX_TOTAL_ARRAY_BYTES', 1), self.assertRaisesRegex(ValueError, 'collection exceeds'):
                fields.sample_fields(records, supports, 'TARGET', 'SYNTHETIC TEST')


if __name__ == '__main__':
    unittest.main()
