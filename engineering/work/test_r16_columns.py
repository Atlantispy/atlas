"""Three bounded prescribed-column cases; no region or terrain runs."""
from fractions import Fraction as F
import json
import unittest

from work.generator_upgrade_r14 import provenance
from work.generator_upgrade_r16 import columns

EVIDENCE = 'Explicit synthetic finite-geology construction, not Diadem inputs'
STATUS = 'SYNTHETIC TEST'


def event(eid, kind, **payload):
    return {'event_id': eid, 'cell_id': 'a', 'kind': kind,
            'evidence': EVIDENCE, 'source_status': STATUS, **payload}


class ColumnsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.tt = provenance.backend()

    def source(self):
        rock = self.tt.Layer('rock', F(12), F(4), F(1, 4), 'bedrock', EVIDENCE)
        sand = self.tt.Layer('sand', F(2), F(2), F(1, 2), 'mobile_sediment', EVIDENCE)
        return {'a': self.tt.Column(F(2), F(-5), (rock, sand), STATUS)}

    def test_translation_emplacement_preserves_source_and_accounts(self):
        initial = self.source(); original = initial['a']; start = original.surface_m
        emplacement = {'material_id': 'new', 'grain_density_kg_m3': 4,
            'porosity': F(1, 2), 'phase': 'bedrock', 'thickness_m': '3/2', 'evidence': EVIDENCE}
        after, receipt = columns.build_columns(initial,
            [event('up', 'translate_base', displacement_m='7/3'), event('new', 'emplace', layer=emplacement)])
        self.assertIs(initial['a'], original)
        self.assertEqual(after['a'].layers[:2], original.layers)
        self.assertEqual(after['a'].surface_m, start+F(7, 3)+F(3, 2))
        self.assertEqual(after['a'].mass_kg, original.mass_kg+6)
        imported = {r['material_id']: r for r in receipt['material_accounts']}['new']
        self.assertEqual(imported['external_import_mass_kg'], '6')
        self.assertEqual(imported['external_import_solid_volume_m3'], '3/2')
        json.dumps(receipt, allow_nan=False)

    def test_exposure_tracks_each_material_and_exact_exhaustion(self):
        initial = self.source(); target = initial['a'].basal_elevation_m+F(1)
        after, receipt = columns.build_columns(initial, [event('cut', 'strip_to_elevation', surface_m=target)])
        self.assertEqual(after['a'].surface_m, target)
        self.assertEqual(after['a'].exposed.material_id, 'rock')
        accounts = {r['material_id']: r for r in receipt['material_accounts']}
        self.assertEqual(accounts['sand']['export_mass_kg'], '2')
        self.assertEqual(accounts['rock']['export_mass_kg'], '6')
        self.assertTrue(all(r['residual_mass_kg'] == r['residual_solid_volume_m3'] == '0' for r in accounts.values()))
        empty, exhausted = columns.build_columns(initial, [event('empty', 'strip_to_elevation', surface_m=-5)])
        self.assertEqual(empty['a'].layers, ())
        self.assertEqual(exhausted['exhausted_cells'], ['a'])
        self.assertIsNone(exhausted['events'][0]['exposed_material'])
        self.assertTrue(exhausted['events'][0]['exhausted'])
        fill = {'material_id': 'rock', 'grain_density_kg_m3': 4, 'porosity': '1/4',
                'phase': 'bedrock', 'thickness_m': 1, 'evidence': EVIDENCE}
        refilled, _ = columns.build_columns(empty, [event('fill', 'emplace', layer=fill)])
        self.assertEqual(refilled['a'].surface_m, -4)

    def test_invalid_inputs_refuse_without_mutation(self):
        initial = self.source(); original = initial['a']
        examples = [
            [event('below', 'strip_to_elevation', surface_m=-6)],
            [event('above', 'strip_to_elevation', surface_m=10)],
            [event('nan', 'translate_base', displacement_m=float('nan'))],
            [event('bool', 'translate_base', displacement_m=True)],
            [event('big', 'translate_base', displacement_m=F(1, 2**8192))],
            [event('same', 'translate_base', displacement_m=0)]*2,
            [dict(event('unknown', 'translate_base', displacement_m=0), source_status='UNKNOWN')],
            [dict(event('mixed', 'translate_base', displacement_m=0), source_status='WORKING NON-CANON')],
            [event('conflict', 'emplace', layer={'material_id': 'rock', 'grain_density_kg_m3': 5,
              'porosity': '1/4', 'phase': 'bedrock', 'thickness_m': 1, 'evidence': EVIDENCE})],
        ]
        for events in examples:
            with self.subTest(kind=events[0]['event_id']), self.assertRaises(ValueError):
                columns.build_columns(initial, events)
            self.assertIs(initial['a'], original)


if __name__ == '__main__':
    unittest.main()
