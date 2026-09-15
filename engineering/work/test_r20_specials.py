"""One bounded owner S01-S15 semantic check; no actual map generation."""
from copy import deepcopy
import unittest

from work.generator_upgrade_r20 import inputs, owner, specials


class SpecialTests(unittest.TestCase):
    def test_owner_special_semantics_and_actual_profile_inventory(self):
        cases = owner.read_cases()['semantic_cases']
        binding = {'mainland_generation': 'frozen-synthetic-mainland',
                   'shoreline_generation': 'frozen-synthetic-shoreline',
                   'distance_source_sha256': '1'*64,
                   'context': {key: 'synthetic-fixed-context' for key in inputs.FRAME_FIELDS},
                   'source_status': 'SYNTHETIC TEST', 'distance_unit': 'm',
                   'source_role': 'WATER_BOUNDARY_DISTANCE'}
        seen = set()
        for case in cases:
            with self.subTest(case=case['id']):
                seen.add(case['id'].split('-')[0])
                kind = case['kind']
                if kind == 'whole_unit_lock':
                    before = deepcopy(case['members'])
                    result = specials.whole_unit_locks(case['members'], case['atom_locks'])
                    self.assertEqual(result['status'], case['expected'])
                    self.assertEqual(case['members'], before)
                    self.assertEqual(result['unit_mutations'], 0)
                elif kind == 'surface_accounting':
                    result = specials.surface_accounting(case['units'])
                    self.assertEqual(result['surface_area'], str(case['expected_surface_area']))
                    self.assertEqual(result['area_by_unit']['forest'], str(case['expected_forest_area']))
                    rows = {row['id']: row for row in result['units']}
                    self.assertEqual(rows['host']['owner'], case['expected_host_owner'])
                    self.assertEqual(rows['gate']['owner'], case['expected_gate_owner'])
                    self.assertEqual(rows['host']['service_sponsor'], 'B')
                    self.assertFalse(result['sponsorship_transfers_sovereignty'])
                elif kind == 'island_distance':
                    result = specials.island_owner(case['distances'], case['eligible'],
                        near_tie_u=case['near_tie_u'], shoreline_binding=binding)
                    self.assertEqual(result['owner'] or result['status'], case['expected'])
                    self.assertEqual(result['binding'], binding)
                elif kind == 'reachability':
                    result = specials.reachability(case['physical'], case['permission'])
                    self.assertEqual(result['status'], case['expected'])
                    self.assertEqual(result['permission'], case['permission'])
                    self.assertFalse(result['sovereignty_transfer'])
                elif kind == 'hydraulic_path':
                    result = specials.hydraulic_path(case['edges'], case['source'],
                                                    case['target'], coverage_complete=True)
                    self.assertEqual(result['all_open_path'], case['expected_all_open_path'])
                    self.assertEqual(result['status'], case.get('expected_acceptance', 'PASS'))
                elif kind == 'arena':
                    result = specials.arena(case['geometry_type'], case['owner'], case['represented_area'])
                    self.assertEqual(result['status'], case['expected'])
                    self.assertIsNone(result['owner'])
                    self.assertEqual(result['represented_area'], '0')
                    self.assertFalse(result['physical_size_assertion'])
                elif kind == 'hierarchy_cut':
                    atoms = sorted({atom for row in case['members'].values() for atom in row})
                    result = specials.hierarchy_cut(case['members'], case['selected'], atoms)
                    self.assertEqual(result['status'], case['expected'])
                    self.assertTrue(result['overlaps'])
                elif kind == 'source_role':
                    result = specials.phase_role(case['phase'], case['role'])
                    self.assertEqual(result['status'], case['expected'])
                else:
                    self.fail('unimplemented owner semantic kind: '+kind)
        self.assertEqual(seen, {'S'+str(i).zfill(2) for i in range(1, 16)})

        contract = owner.contract()
        matrix = owner.read_matrix()
        source_row = next(row for row in contract['sources'] if row['id'] == 'CM')
        source = {'path': str(owner.source_path(source_row, contract)),
                  'sha256': source_row['sha256'], 'status': source_row['status']}
        profile = specials.profile(matrix, source=source)
        self.assertEqual(len(profile['primary_records']), 20)
        self.assertEqual(len(profile['ordinary_fill_ids']), 18)
        self.assertEqual(len(profile['surface_fills']), 20)
        self.assertEqual(profile['sea_owner_ids'], sorted(contract['diadem_constraints']['sea_required']))
        self.assertEqual(len(profile['natural_island_ids']), 14)
        fills = {row['id']: row for row in profile['surface_fills']}
        self.assertEqual(len(fills[profile['shared_fill_id']]['primary_haus_ids']), 2)
        self.assertEqual(fills[profile['neutral_fill_id']]['primary_haus_ids'], [])
        self.assertEqual(profile['status'], matrix['status'])
        self.assertFalse(profile['actual_geometry_accepted'])


if __name__ == '__main__':
    unittest.main()
