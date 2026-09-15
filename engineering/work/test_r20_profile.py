"""Bound actual-profile compilation only; synthetic memberships, no map solve."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest

from work.generator_upgrade_r20 import inputs, pipeline, profile, provenance as p


class ProfileTests(unittest.TestCase):
    def test_actual_profile_restrictions_and_missing_or_stale_masks(self):
        contract, actual = profile.inventory()
        fills = sorted(row['id'] for row in actual['surface_fills'])
        atom_for = {fill: 'a'+str(i) for i, fill in enumerate(fills)}
        mapping = {atom: 'u'+str(i) for i, atom in enumerate(atom_for.values())}
        frozen = {'status': 'PASS', 'assignment_allowed': True,
                  'atom_to_assignment_unit': mapping,
                  'assignment_prepared': {'supports': [{'id': unit} for unit in mapping.values()]}}
        context = {key: 'synthetic-profile-context' for key in inputs.FRAME_FIELDS}
        frame = {'spatial_frame_id': context['spatial_frame_id'], 'horizontal_unit': 'm',
                 'x_direction': 'east', 'y_direction': 'north',
                 'vertical_reference': context['vertical_reference'], 'evidence': 'SYNTHETIC TEST'}
        binding = {'context': context, 'frame': frame, 'terrain_generation': 'synthetic-terrain',
                   'water_generation': 'synthetic-water', 'freeze_sha256': p.sha(frozen)}
        path = Path(__file__).resolve()
        source = {'path': str(path), 'sha256': hashlib.sha256(p.checked(path)).hexdigest(),
                  'role': 'STAGE2_CONTEXT', 'status': 'SYNTHETIC TEST'}
        expected = dict(binding, source_binding=source)
        by_haus = {row['haus_id']: row['surface_fill_id'] for row in actual['primary_records']}
        named = {'forest': actual['shared_fill_id'], 'neutral': actual['neutral_fill_id'],
                 'dunkelhauch': by_haus['haus_dunkelhauch']}
        packet = {'binding': binding, 'source_binding': source, 'geometry_status': 'FROZEN_COMPLETE',
            'sea_atoms': [atom_for[by_haus[ident]] for ident in actual['sea_owner_ids']],
            'envelopes': {name: {'core_atoms': [atom_for[fill]], 'allowed_atoms': [atom_for[fill]],
                                'excluded_atoms': []} for name, fill in named.items()},
            'forest_exclusion_atoms': [atom_for[actual['shared_fill_id']]],
            'neutral_flanks': {'west_northwest_atoms': [atom_for[by_haus['haus_edelstein']]],
                              'east_southeast_atoms': [atom_for[by_haus['haus_glanzgrund']]]}}
        before = deepcopy((frozen, packet))
        result = profile.compile_restrictions(frozen, packet, expected_binding=expected)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual((frozen, packet), before)
        restrictions = result['restrictions']
        self.assertEqual(len(restrictions['owners']), 20)
        self.assertEqual(restrictions['required_owners'], restrictions['owners'])
        self.assertEqual(len(restrictions['required_adjacency']), len(contract['diadem_constraints']['direct_frontiers_required']))
        self.assertEqual(len(restrictions['prohibited_adjacency']), len(contract['diadem_constraints']['direct_frontiers_excluded']))
        sea_fills = {by_haus[ident] for ident in actual['sea_owner_ids']}
        self.assertEqual({row['owner'] for row in restrictions['required_presence']}, sea_fills)
        for atom in packet['sea_atoms']:
            self.assertLessEqual(set(restrictions['eligible'][mapping[atom]]), sea_fills)
        for name, fill in named.items():
            self.assertEqual(restrictions['eligible'][mapping[atom_for[fill]]], [fill])
        self.assertNotIn(by_haus['haus_frostglanz'], restrictions['required_any_adjacency'][0]['other_owners'])
        self.assertEqual(len(restrictions['surface_relations'][actual['shared_fill_id']]), 2)
        self.assertEqual(restrictions['surface_relations'][actual['neutral_fill_id']], [])
        self.assertFalse(result['actual_diadem_map_accepted'])
        original_problem = {'owners': fills, 'unit_ids': list(mapping.values()),
            'eligible': {unit: list(fills) for unit in mapping.values()},
            'required_owners': [], 'connected_owners': [], 'required_adjacency': [],
            'prohibited_adjacency': [], 'required_presence': []}
        integrated = pipeline.apply_profile(original_problem, result, restrictions['surface_relations'])
        self.assertEqual(integrated['eligible'], restrictions['eligible'])
        self.assertEqual(integrated['required_any_adjacency'], restrictions['required_any_adjacency'])
        self.assertEqual(integrated['required_presence'], restrictions['required_presence'])
        self.assertEqual(original_problem['required_owners'], [])
        with self.assertRaises(ValueError):
            pipeline.apply_profile(dict(original_problem, owners=fills[:-1]), result, restrictions['surface_relations'])
        missing = deepcopy(packet); missing['envelopes']['neutral']['allowed_atoms'] = None
        self.assertEqual(profile.compile_restrictions(frozen, missing, expected_binding=expected)['status'], 'INPUT_INCOMPLETE')
        stale = deepcopy(packet); stale['binding']['water_generation'] = 'another-water'
        with self.assertRaises(ValueError):
            profile.compile_restrictions(frozen, stale, expected_binding=expected)
        conflict = deepcopy(packet)
        conflict['sea_atoms'].append(atom_for[actual['neutral_fill_id']])
        self.assertEqual(profile.compile_restrictions(frozen, conflict, expected_binding=expected)['status'], 'INFEASIBLE_NO_SPLIT')


if __name__ == '__main__':
    unittest.main()
