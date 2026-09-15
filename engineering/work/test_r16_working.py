"""Only missing Physical Frame working-model integration and native rate checks."""
from fractions import Fraction as F
import math
import unittest

from work.generator_upgrade_r14 import erosion
from work.generator_upgrade_r16 import working as w, provenance as p


class WorkingModelTests(unittest.TestCase):
    def test_owner_recipe_analytic_compilation_and_native_construction(self):
        authored = w.owner_recipe()
        compiled, analytic = w.compile_recipe()
        # Ignore evidence wording only; compare every actual construction value.
        for a, b in zip(authored['events'], compiled['events']):
            self.assertEqual((a['event_id'], a['kind']), (b['event_id'], b['kind']))
            if a['kind'] == 'emplace':
                for key in ('thickness_m', 'grain_density_kg_m3', 'porosity'):
                    self.assertEqual(F(a['layer'][key]), F(b['layer'][key]))
            else:
                key = 'surface_m' if a['kind'] == 'strip_to_elevation' else 'displacement_m'
                self.assertEqual(F(a[key]), F(b[key]))
        self.assertEqual(len(compiled['events']), 17)
        self.assertEqual(len(authored['events']), 17)
        result = w.build()
        type(self).working_result = result
        science = result['scientific']
        self.assertEqual([science['stratigraphy'][key]['exposed_material'] for key in ('crest', 'shoulder', 'trough')],
                         ['R16_WEAK_SEDIMENTARY', 'R16_CARBONATE', 'R16_BASALT'])
        for row in science['construction']['material_accounts']:
            self.assertEqual(row['residual_mass_kg'], '0')
            self.assertEqual(row['residual_solid_volume_m3'], '0')
        self.assertEqual(result['execution']['scientific_sha256'], p.sha(science))
        for row in analytic.values():
            self.assertEqual(row['reference_bulk_volumes_m3'], row['current_bulk_volumes_m3'])

    def test_actual_r14_rates_and_contact_crossing(self):
        _, tt = p.backend()
        def prop(name, value, unit):
            return tt.PhysicalProperty(name, value, unit, w.EVIDENCE, w.STATUS)
        forcing = tt.landscape.Forcing(prop('discharge', 1e6, 'm3/year'), prop('hydraulic_slope', .1, '1'))
        columns = []
        for mid, density, phi, _ in w.MATERIALS:
            layer = tt.Layer(mid, F(density)*(1-F(phi)), F(density), F(phi), 'bedrock', w.EVIDENCE)
            columns.append((mid, tt.Column(F(1), F(0), (layer,), w.STATUS)))
        initial = tt.LandscapeState(tuple(columns))
        duration = F(1, 1000)
        result = erosion.advance(initial, {key: forcing for key, _ in columns}, w.erosion_laws(), duration)
        rates = {}
        for key, _, _, k in w.MATERIALS:
            rate = (initial.column_map[key].surface_m-result.state.column_map[key].surface_m)/duration
            self.assertTrue(math.isclose(float(rate), 100*k, rel_tol=1e-12, abs_tol=1e-14))
            rates[key] = {'expected_m_year': 100*k, 'actual_m_year': float(rate)}
        # Thin numerical contact probe: owner material laws, not regional history.
        lower, upper = initial.column_map[w.MATERIALS[0][0]].layers[0], initial.column_map[w.MATERIALS[1][0]].layers[0]
        from dataclasses import replace
        top = replace(upper, mass_kg=upper.mass_kg*F(1, 1000))
        start = tt.LandscapeState((('probe', tt.Column(F(1), F(0), (lower, top), w.STATUS)),))
        crossed = erosion.advance(start, {'probe': forcing}, w.erosion_laws(), F(1, 5))
        self.assertEqual(crossed.state.column_map['probe'].exposed.material_id, w.MATERIALS[0][0])
        self.assertTrue(math.isclose(float(start.column_map['probe'].surface_m-crossed.state.column_map['probe'].surface_m), .0011, rel_tol=1e-12))
        for row in crossed.receipt['global_material_balance']:
            self.assertEqual(row['residual_mass_kg'], [0, 1])
            self.assertEqual(row['residual_solid_volume_m3'], [0, 1])
        type(self).rate_result = {'rates': rates, 'duration_years': str(duration),
            'rate_receipt': result.receipt, 'contact_probe_receipt': crossed.receipt,
            'scope': 'CONTROLLED_RATE_AND_THIN_CONTACT_CHECK; NOT_REGIONAL_HYDROLOGY_OR_HISTORY'}


if __name__ == '__main__':
    unittest.main()
