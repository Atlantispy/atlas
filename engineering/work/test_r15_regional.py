"""Six focused connection tests; no regional/world/year run."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from work.generator_upgrade_r14 import reference, pipeline
from work.generator_upgrade_r15 import regional as r


def fixture(directory):
    template = reference.recipe(duration_s=1., event_count=1, erosion=False)
    path = Path(directory)/'z.npy'
    np.save(path, np.array([[2., 0.], [4., 2.]]))
    frame = template['context']['spatial_frame_id']
    evidence = 'SYNTHETIC TEST: explicit regional inputs, not Diadem calibration'
    registration = {'source_frame_id': 'NORTH_M', 'target_frame_id': frame,
        'target_to_source_affine': [[1., 0., 0.], [0., -1., 10.]],
        'evidence': evidence, 'source_status': 'SYNTHETIC TEST'}
    field = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'array_key': None, 'grid': {'frame_id': 'NORTH_M', 'unit': 'm',
            'sample_location': 'cell_centres', 'first_sample_m': [0., 10.], 'step_m': [10., -10.]},
        'registration': registration, 'role': 'physical_base_elevation', 'unit': 'm',
        'reference': {k: template['context'][k] for k in ('world_id', 'snapshot_id', 'vertical_reference')},
        'evidence': evidence, 'source_status': 'SYNTHETIC TEST'}
    columns = {}
    for key, xy in (('upper', [0., 0.]), ('lower', [10., 0.])):
        cell = deepcopy(template['cells'][key]); del cell['base_elevation_m']
        columns[key] = {'xy_m': xy, 'physical_column': cell, 'assignment_evidence': evidence,
                        'source_status': 'SYNTHETIC TEST'}
    packet = {'schema': r.SCHEMA, 'context': deepcopy(template['context']),
        'source_status': 'SYNTHETIC TEST', 'evidence': evidence,
        'fields': {'base': field}, 'columns': columns}
    return template, packet


class ConnectionTests(unittest.TestCase):
    def test_cell_centres_nodes_and_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            _, packet = fixture(directory); field = packet['fields']['base']
            grid, registration = field['grid'], field['registration']
            a = np.array([[2., 0.], [4., 2.]])
            self.assertEqual(r.sample(a, grid, registration, [5., 5.]), 2.)
            grid['sample_location'] = 'nodes'
            grid['first_sample_m'] = [-5., 15.]
            self.assertEqual(r.sample(a, grid, registration, [0., 0.]), 2.)
            # Actual first-sample coordinates, not a label-only half-cell shift.
            self.assertEqual(r.sample(a, grid, registration, [-5., -5.]), 2.)

    def test_unknown_coverage_and_no_extrapolation(self):
        with tempfile.TemporaryDirectory() as directory:
            _, packet = fixture(directory); field = packet['fields']['base']
            a = np.array([[1., np.nan], [2., 3.]])
            for xy in ([5., 5.], [-1., 0.]):
                with self.assertRaises(ValueError):
                    r.sample(a, field['grid'], field['registration'], xy)
            self.assertEqual(r.sample(a, field['grid'], field['registration'], [0., 0.]), 1.)

    def test_actual_material_and_drainage_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            template, packet = fixture(directory)
            before = deepcopy(template)
            # Same physical geometry/porosity, twice the supplied grain density.
            from fractions import Fraction
            for row in packet['columns'].values():
                cell = row['physical_column']
                cell['materials'][0]['grain_density_kg_m3'] *= 2
                cell['materials'][0]['dry_mass_kg_m2'] = str(2*Fraction(cell['materials'][0]['dry_mass_kg_m2']))
            for name in ('reference_specific_volume_m3_kg', 'reference_water_m3_kg'):
                template['deformation_laws']['mineral'][name] /= 2
            before = deepcopy(template)
            prepared, receipt = r.prepare(template, packet)
            self.assertEqual(template, before)
            self.assertEqual(prepared['cells']['upper']['base_elevation_m'], 2.)
            self.assertGreater(pipeline.stocks(prepared['cells'])['material_kg']['mineral'],
                               pipeline.stocks(template['cells'])['material_kg']['mineral'])
            old = r.transport.routes(template['cells'], template['connectors'], seconds_per_year=template['seconds_per_year'])
            self.assertNotEqual(receipt['initial_routes']['slopes'], old['slopes'])
            self.assertFalse(receipt['plate_kinematics_modelled'])
            self.assertTrue(prepared['evidence'].endswith(r.digest(receipt)))

    def test_source_binding_and_npz(self):
        with tempfile.TemporaryDirectory() as directory:
            template, packet = fixture(directory)
            first, _ = r.prepare(template, packet)
            packet['columns']['upper']['assignment_evidence'] += '; revised source decision'
            second, _ = r.prepare(template, packet)
            self.assertNotEqual(r.digest(first), r.digest(second))
            field = packet['fields']['base']; field['sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'source changed'):
                r.prepare(template, packet)
            path = Path(directory)/'z.npz'; np.savez(path, bed=np.ones((2, 2)))
            field.update(path=str(path), array_key='bed', sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            np.testing.assert_array_equal(r.read_field(field), np.ones((2, 2)))
            from unittest.mock import patch
            with patch.object(r, 'MAX_SOURCE_BYTES', 1), self.assertRaisesRegex(ValueError, 'byte budget'):
                r.read_field(field)
            with patch.object(r, 'MAX_ARRAY_BYTES', 1), self.assertRaisesRegex(ValueError, 'budget|bounded NPZ'):
                r.read_field(field)

    def test_mismatch_missing_physics_and_resume_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            template, packet = fixture(directory)
            changes = [lambda p: p['fields']['base'].update(role='continuous_constraint_prior'),
                lambda p: p['fields']['base']['reference'].update(vertical_reference='OTHER'),
                lambda p: p['fields']['base']['registration'].update(source_status='UNKNOWN'),
                lambda p: p['columns']['upper']['physical_column']['soil'].update(elapsed_seconds=1),
                lambda p: p['columns']['upper'].update(xy_m=[1., 0.]),
                lambda p: p['columns']['upper']['physical_column']['materials'][0].update(grain_density_kg_m3=None)]
            for change in changes:
                other = deepcopy(packet); change(other)
                with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                    r.prepare(template, other)

    def test_public_driver_one_second(self):
        with tempfile.TemporaryDirectory() as directory:
            template, packet = fixture(directory)
            result = r.run(template, packet)
            self.assertEqual(result['ground']['scientific']['status'], 'MODELLED_GROUND_FEEDBACK')
            self.assertEqual(result['ground']['scientific']['completed_events'], 1)
            self.assertFalse(result['ground']['scientific']['whole_diadem_year_verified'])


if __name__ == '__main__':
    unittest.main()
