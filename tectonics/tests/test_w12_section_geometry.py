"""Deterministic geometry checks; no native runtime, simulation or stored runs."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from w12_section_geometry import SectionError, build_section


def fixture():
    """Nonuniform cells, arbitrary native IDs, mixed parcels and unequal values."""
    def array(values, units, shape, **spec):
        return dict(values=values, spec=dict(units=units, shape=shape, dtype='<f8', **spec))
    cohorts = [dict(cohort_id='a-grain'), dict(cohort_id='z-grain'), dict(cohort_id='water')]
    parcels = [dict(parcel_id=name, source_id='authored-'+name, parameters={'profile_id': 'law'},
                    components=[dict(cohort=cohorts[1], solid_volume_fraction=.75),
                                dict(cohort=cohorts[0], solid_volume_fraction=.25)])
               for name in ('z-top', 'a-middle', 'm-bottom')]
    names = ['inventory_load', 'void_replacement_load', 'thermal_load', 'external_load',
             'total_downward_load', 'downward_displacement_from_reference',
             'sediment_surface_change_up', 'reservoir_surface_change_up']
    columns = [dict(name=name, units='Pa' if i < 5 else 'm') for i, name in enumerate(names)]
    columns[7]['known'] = dict(mask_field='support.reservoir_surface_known', meaning='water exists at both dates')
    return dict(producer='atlas-tectonics-column-assembly-v1', route='w04-support.v1',
        source_status='WORKING NON-CANON', context=dict(spatial_frame_id='strip', vertical_reference='source-datum'),
        support=dict(kind='planar-strip', width_m=2., frame_id='strip', depth_reference_id='source-datum',
            cell_ids=['native-9', 'native-2', 'native-18'], cell_edges_m=[-1., 0., 2., 5.],
            cell_centres_m=[-.5, 1., 3.5], material_cohorts=cohorts, compaction_rows=parcels),
        provenance=dict(verified=dict(product=True, native_state=True, completed_output=True, source_runtime=True),
            native_state_descriptor=dict(schema='atlas.w03-columns.v1', reference_width_m=2.,
                binding=dict(depth_reference_id='source-datum')),
            native_descriptor=dict(native=dict(schema='atlas.w04-support-result.v1',
                depth_reference_id='source-datum', reference_time_s=11., total_reference_result=True, feedback_applied=False))),
        fields=dict(grain_volume_m3=array([[2., 8., 18.], [4., 4., 6.], [2., 12., 12.]], 'm3', [3, 3], known='all values known'),
            void_ratio=array([[.5, .25, 1.], [0., 1., .5], [1., 0., .25]], '1', [3, 3], known='all values known'),
            **{'support.values': array([[0., 0., 0., 0., 0., -.25, .5, 0.],
                                       [0., 0., 0., 0., 0., .5, -.25, .75],
                                       [0., 0., 0., 0., 0., 1., -.5, 1.25]], ['Pa'] * 5 + ['m'] * 3, [3, 8], columns=columns),
               'support.reservoir_surface_known': dict(values=[False, True, True], spec=dict(shape=[3], dtype='|b1'))}))


class SectionGeometryTests(unittest.TestCase):
    def test_nonuniform_support_exact_heights_and_native_order(self):
        original = fixture()
        result = build_section(original)
        self.assertEqual(result['top_depth_m'], [[0., 0., 0.], [1.5, 2.5, 6.], [3.5, 4.5, 7.5]])
        self.assertEqual(result['bottom_depth_m'], [[1.5, 2.5, 6.], [3.5, 4.5, 7.5], [5.5, 7.5, 10.]])
        self.assertEqual(result['column_bulk_thickness_m'], [5.5, 7.5, 10.])
        self.assertEqual([p['parcel_id'] for p in result['parcels']], ['z-top', 'a-middle', 'm-bottom'])
        self.assertEqual(result['support']['cell_ids'], ['native-9', 'native-2', 'native-18'])
        self.assertEqual(result['support']['cell_widths_m'], [1., 2., 3.])
        self.assertEqual(result['field']['values'], original['fields']['void_ratio']['values'])
        self.assertEqual(original, fixture())
        result['parcels'][0]['components'][0]['solid_volume_fraction'] = 0
        self.assertEqual(original, fixture())

    def test_reconstructs_saved_grain_volume_and_porosity(self):
        original = fixture()
        section = build_section(original, field='porosity')
        for r, row in enumerate(section['field']['values']):
            for c, porosity in enumerate(row):
                h = section['bottom_depth_m'][r][c] - section['top_depth_m'][r][c]
                area = section['support']['width_m'] * section['support']['cell_widths_m'][c]
                self.assertAlmostEqual(h * area * (1-porosity), original['fields']['grain_volume_m3']['values'][r][c])
        for field, unit in [('void_ratio', '1'), ('porosity', '1'), ('bulk_thickness_m', 'm'), ('grain_volume_m3', 'm3')]:
            with self.subTest(field=field):
                answer = build_section(original, field=field)
                self.assertEqual(answer['field']['unit'], unit)
                self.assertEqual(answer['field']['known'], [[True] * 3 for _ in range(3)])
        self.assertEqual(build_section(original, field='bulk_thickness_m')['field']['values'],
                         [[1.5, 2.5, 6.], [2., 2., 1.5], [2., 3., 2.5]])
        self.assertEqual(build_section(original, field='grain_volume_m3')['field']['values'], original['fields']['grain_volume_m3']['values'])

    def test_slice_preserves_original_edges_ids_and_values(self):
        original = fixture()
        full = build_section(original)
        section = build_section(original, cell_start=1, cell_stop=3)
        self.assertEqual(section['support']['cell_edges_m'], [0., 2., 5.])
        self.assertEqual(section['support']['cell_ids'], ['native-2', 'native-18'])
        self.assertEqual(section['top_depth_m'], [row[1:] for row in full['top_depth_m']])
        self.assertEqual(section['bottom_depth_m'], [row[1:] for row in full['bottom_depth_m']])
        self.assertEqual(section['selection']['source_cell_count'], 3)
        self.assertEqual(build_section(original, cell_start=2)['support']['cell_edges_m'], [2., 5.])
        for start, stop in [(True, 2), (0, False), (-1, 2), (1, 1), (2, 1), (0, 4), (1., 3)]:
            with self.subTest(start=start, stop=stop), self.assertRaises(SectionError):
                build_section(original, cell_start=start, cell_stop=stop)

    def test_relative_datum_and_separate_signed_curves_preserve_unknowns(self):
        original = fixture()
        section = build_section(original)
        self.assertEqual(section['vertical']['positive'], 'down')
        self.assertFalse(section['vertical']['absolute_elevation_available'])
        self.assertEqual(section['vertical']['datum'], 'current sediment surface')
        curves = section['signed_curves']
        self.assertEqual(curves['downward_displacement_from_reference']['values'], [-.25, .5, 1.])
        self.assertEqual(curves['downward_displacement_from_reference']['positive'], 'down')
        water = curves['reservoir_surface_change_up']
        self.assertEqual(water['positive'], 'up')
        self.assertEqual(water['known'], [False, True, True])
        self.assertEqual(water['values'], [0., .75, 1.25])
        self.assertEqual(water['spec'], original['fields']['support.values']['spec']['columns'][7])
        self.assertEqual(water['reference_time_s'], 11.)
        json.dumps(section, allow_nan=False)

    def test_sixty_four_cells_are_preserved_without_decimation(self):
        candidate = fixture()
        support = candidate['support']
        support['cell_ids'] = ['native-' + str(1000-i) for i in range(64)]
        support['cell_edges_m'] = [i * .25 for i in range(65)]
        support['cell_centres_m'] = [(i + .5) * .25 for i in range(64)]
        for name in ('grain_volume_m3', 'void_ratio'):
            entry = candidate['fields'][name]
            entry['values'] = [[row[i % 3] for i in range(64)] for row in entry['values']]
            entry['spec']['shape'] = [3, 64]
        for name in ('support.values', 'support.reservoir_surface_known'):
            entry = candidate['fields'][name]
            entry['values'] = [entry['values'][i % 3] for i in range(64)]
            entry['spec']['shape'][0] = 64
        section = build_section(candidate)
        self.assertEqual(section['support']['cell_ids'], support['cell_ids'])
        self.assertEqual(section['support']['cell_edges_m'], support['cell_edges_m'])
        self.assertTrue(all(len(row) == 64 for row in section['field']['values']))
        self.assertEqual(section['field']['values'], candidate['fields']['void_ratio']['values'])
        support['cell_ids'].append('over-envelope')
        with self.assertRaisesRegex(SectionError, 'envelope'):
            build_section(candidate)

    def test_wrong_envelope_authentication_route_and_field_refuse(self):
        cases = [dict(schema='atlas.tectonics-ui-result.v1', status='ok', result=fixture())]
        for path, value in [(('route',), 'w07'), (('support', 'kind'), 'spherical'),
                            (('provenance', 'verified', 'native_state'), False),
                            (('provenance', 'native_state_descriptor', 'reference_width_m'), 3.),
                            (('context', 'vertical_reference'), 'different')]:
            candidate = fixture(); target = candidate
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value; cases.append(candidate)
        for candidate in cases:
            with self.subTest(candidate=candidate.get('route')), self.assertRaises(SectionError):
                build_section(candidate)
        for field in ('cohort_thickness_m', 'elevation_m', ['void_ratio']):
            with self.subTest(field=field), self.assertRaises(SectionError):
                build_section(fixture(), field=field)

    def test_bad_geometry_values_shapes_and_masks_refuse(self):
        edits = [(('support', 'width_m'), 0.), (('support', 'cell_edges_m'), [-1., 0., 0., 5.]),
            (('support', 'cell_ids'), ['x', 'x', 'z']), (('support', 'cell_centres_m'), [-.5, 8., 3.5]),
            (('fields', 'void_ratio', 'values'), [[1.], [2.], [3.]]),
            (('fields', 'void_ratio', 'spec', 'units'), 'm'),
            (('fields', 'void_ratio', 'spec', 'known'), 'unknown'),
            (('fields', 'support.reservoir_surface_known', 'values'), [0, True, True])]
        for path, value in edits:
            candidate = fixture(); target = candidate
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(SectionError): build_section(candidate)
        for name, values in [('grain_volume_m3', [0., -1., float('inf'), float('nan'), True, '2']),
                             ('void_ratio', [-1., float('inf'), float('nan'), False, None])]:
            for value in values:
                candidate = fixture(); candidate['fields'][name]['values'][0][0] = value
                with self.subTest(name=name, value=value), self.assertRaises(SectionError):
                    build_section(candidate, cell_start=1)

    def test_unrepresentable_depth_and_overflow_refuse(self):
        candidate = fixture()
        candidate['fields']['grain_volume_m3']['values'][0][0] = 1e300
        with self.assertRaisesRegex(SectionError, 'interval is unrepresentable'): build_section(candidate)
        candidate = fixture()
        candidate['fields']['grain_volume_m3']['values'][0][0] = 1e308
        candidate['fields']['void_ratio']['values'][0][0] = 1e308
        with self.assertRaisesRegex(SectionError, 'finite'): build_section(candidate)
        candidate = fixture()
        candidate['fields']['grain_volume_m3']['values'][0][0] = 5e-324
        with self.assertRaisesRegex(SectionError, 'underflows'): build_section(candidate)


if __name__ == '__main__':
    unittest.main()
