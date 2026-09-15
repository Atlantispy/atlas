"""Bounded synthetic transport ports; no regional material calibration."""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from work.generator_upgrade_r13 import soil
from work.generator_upgrade_r14 import provenance, remap, transport
from work.test_r13_soil import fixture as soil_fixture


EVIDENCE = 'Explicit small synthetic transport experiment; not Diadem parameters'


def erosion(material, rate):
    def prop(name, value, unit):
        return {'name': name, 'value': value, 'unit': unit, 'evidence': EVIDENCE, 'status': 'SYNTHETIC TEST'}
    return {'material_id': material, 'phase': 'mobile_sediment',
            'k_per_year': prop('erosion_coefficient_at_reference_runoff', rate, '1/year'),
            'reference_runoff_m_year': prop('reference_runoff', 1., 'm/year')}


def fixture():
    cells, templates, erosion_laws, sediment_laws = {}, {}, [], []
    _, _, controls = soil_fixture()
    for key, area, base, temperature, rate in (('a', 3., 10., 280., .001), ('b', 1., 0., 285., 0.)):
        model, _, _ = soil_fixture()
        layer = model['layers'][0]
        layer.update(layer_id=key+'-original', thickness_m=.125, theta_r=.0625, theta_s=.5)
        state = soil.initial_state(model, [-1.], [temperature])
        material = {'material_id': key, 'phase': 'mobile_sediment',
                    'grain_density_kg_m3': 2500., 'dry_mass_kg_m2': 156.25, 'evidence': EVIDENCE}
        cells[key] = {'area_m2': area, 'base_elevation_m': base, 'model': model, 'soil': state,
                      'materials': [material], 'surface_water_m3': 4. if key == 'a' else 0.,
                      'surface_enthalpy_j': 4.*1000.*(334000.+4180.*5.) if key == 'a' else 0.,
                      'surface_residence_seconds': 2.}
        templates[key] = deepcopy(layer)
        erosion_laws.append(erosion(key, rate))
        sediment_laws.append({'material_id': key, 'settling_m_year': 20.,
                             'deposited_porosity': .5, 'deposition_order': len(sediment_laws), 'evidence': EVIDENCE})
    connectors = [dict(connector_id='ab', source_id='a', receiver_id='b', length_m=10., outlet_elevation_m=None, evidence=EVIDENCE),
                  dict(connector_id='out', source_id='b', receiver_id=None, length_m=1., outlet_elevation_m=-1., evidence=EVIDENCE)]
    return cells, connectors, erosion_laws, sediment_laws, templates, controls


def run_case(case, duration=1.):
    cells, edges, laws, sediment, templates, controls = case
    return transport.step(cells, edges, laws, sediment, templates, duration_s=duration,
        seconds_per_year=100., controls={'max_relief_change_fraction': .5, 'max_solid_liquid_ratio': .2, 'evidence': EVIDENCE},
        soil_controls=controls, evidence=EVIDENCE)


def inventory(cells):
    water = energy = capacity = F()
    material = {}
    for cell in cells.values():
        area = F(cell['area_m2'])
        water += F(cell['surface_water_m3'])
        energy += F(cell['surface_enthalpy_j'])
        # Independently read actual public state, not transport's transfer ledger.
        for layer, metadata, theta, enthalpy in zip(cell['model']['layers'], cell['materials'],
                                                   cell['soil']['total_water'], cell['soil']['enthalpy_j_m2']):
            water += area*F(layer['thickness_m'])*F(theta)
            energy += area*F(enthalpy)
            capacity += area*F(layer['thickness_m'])*F(layer['dry_heat_capacity_j_m3_k'])
            key = metadata['material_id']
            material[key] = material.get(key, F())+area*F(metadata['dry_mass_kg_m2'])
    return water, energy, capacity, material


class TransportTests(unittest.TestCase):
    def test_unequal_area_material_water_heat_and_exports(self):
        case = fixture(); before = inventory(case[0]); result = run_case(case)
        after = inventory(result['cells']); ledger = result['ledger']
        self.assertLess(abs(float(before[0]-after[0]-F(ledger['runoff_export_m3'])-F(ledger['sediment_water_export_m3']))), 1e-10)
        energy_residual = before[1]-after[1]-F(ledger['runoff_export_enthalpy_j'])-F(ledger['sediment_enthalpy_export_j'])
        self.assertEqual(energy_residual, F(ledger['enthalpy_residual_j']))
        self.assertLess(abs(float(energy_residual)), case[5]['energy_atol_j_m2']*4)
        self.assertEqual(ledger['exact_target_enthalpy_residual_j'], '0')
        self.assertEqual(ledger['exact_target_water_residual_m3'], '0')
        for key, mass in before[3].items():
            self.assertEqual(mass, after[3].get(key, F())+F(ledger['material_export_kg'][key]))
        self.assertGreater(F(ledger['sediment_water_export_m3']), 0)
        self.assertGreater(F(ledger['sediment_enthalpy_export_j']), 0)
        self.assertTrue(any(r['cell_id'] == 'b' and F(r['water_m3']) > 0 for r in ledger['deposits']))
        source = remap.layer_stocks(case[0]['a']['model'], case[0]['a']['soil'], case[0]['a']['materials'])[0]
        source_mass = F(case[0]['a']['materials'][0]['dry_mass_kg_m2'])*3
        for row in ledger['wet_exports']:
            if row['source_cell'] == 'a':
                self.assertEqual(F(row['water_m3']), F(source['water_m'])*3*F(row['mass_kg'])/source_mass)
                self.assertEqual(F(row['enthalpy_j']), F(source['enthalpy_j_m2'])*3*F(row['mass_kg'])/source_mass)
        self.assertLess(abs(float(before[2]-after[2]-F(ledger['exported_dry_heat_capacity_j_k']))), 1e-8)

    def test_transit_release_preserves_clock_input_and_sealed_sources(self):
        case = fixture(); old = deepcopy(case[0]); _, tt = provenance.backend()
        paths = (Path(tt.__file__), Path(soil.__file__))
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        result = run_case(case)
        self.assertEqual(case[0], old)
        fraction = F(-math.expm1(-.5))
        self.assertEqual(F(result['ledger']['runoff_export_m3']), 4*fraction)
        for key, cell in result['cells'].items():
            self.assertEqual(cell['soil']['elapsed_seconds'], old[key]['soil']['elapsed_seconds'])
            self.assertEqual(F(cell['surface_water_m3']), F(old[key]['surface_water_m3'])*(1-fraction))
            self.assertEqual(F(cell['surface_enthalpy_j']), F(old[key]['surface_enthalpy_j'])*(1-fraction))
        self.assertEqual(hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])

    def test_dry_frozen_identity_does_not_rebuild_or_invent_erosion(self):
        case = fixture()
        for cell in case[0].values():
            cell['soil'] = soil.initial_state(cell['model'], [-1.], [272.])
            cell['surface_water_m3'] = cell['surface_enthalpy_j'] = 0.
        with patch.object(remap, 'rebuild', side_effect=AssertionError('unchanged geometry must preserve state exactly')):
            result = run_case(case)
        self.assertEqual(result['cells'], case[0] | {k: dict(v, surface_water_m3='0', surface_enthalpy_j='0') for k, v in case[0].items()})
        self.assertEqual(result['ledger']['sediment_water_export_m3'], '0')

    def test_eroded_ice_rejected_without_mutating_input(self):
        case = fixture()
        case[0]['a']['soil'] = soil.initial_state(case[0]['a']['model'], [-1.], [272.])
        old = deepcopy(case[0])
        with self.assertRaisesRegex(ValueError, 'unsupported frozen-sediment law'):
            run_case(case)
        self.assertEqual(case[0], old)

    def test_deposit_overfill_is_not_clipped(self):
        case = fixture()
        case[3][0]['deposited_porosity'] = .125
        case[4]['a'].update(theta_s=.125, theta_r=.01)
        with self.assertRaisesRegex(ValueError, 'pore-volume overflow'):
            run_case(case)

    def test_refreshed_receiver_uses_actual_new_geometry(self):
        case = fixture(); cells = case[0]
        cells['a']['model']['layers'][0]['thickness_m'] = 2.
        cells['a']['materials'][0]['dry_mass_kg_m2'] = 2500.
        cells['a']['soil'] = soil.initial_state(cells['a']['model'], [-1.], [280.])
        cells['b']['base_elevation_m'] = 5.875
        cells['c'] = deepcopy(cells['b']); cells['c']['base_elevation_m'] = -.125
        def edge(name, source, target, length=1., level=None):
            return dict(connector_id=name, source_id=source, receiver_id=target,
                        length_m=length, outlet_elevation_m=level, evidence=EVIDENCE)
        case = (cells, [edge('ab', 'a', 'b'), edge('ac', 'a', 'c', 2.), edge('bc', 'b', 'c'), edge('out', 'c', None, level=-1.)], *case[2:])
        for law in case[3]: law['settling_m_year'] = 0.
        result = run_case(case)
        self.assertEqual(result['routes_before']['receivers']['a'], 'b')
        self.assertEqual(result['routes_after']['receivers']['a'], 'c')
        self.assertEqual(result['routes_after'], transport.routes(result['cells'], case[1], seconds_per_year=100.))

    def test_explicit_packing_and_common_enthalpy_datum_required(self):
        case = fixture(); case[4]['a']['theta_s'] = .4
        with self.assertRaisesRegex(ValueError, 'porosity differ'):
            run_case(case)
        case = fixture(); case[0]['b']['model']['constants']['melting_temperature_k'] += 1
        with self.assertRaisesRegex(ValueError, 'common fluid/enthalpy datum'):
            run_case(case)

    def test_saturated_deposit_negative_donor_has_only_unvalidated_seed(self):
        case = fixture(); cell = case[0]['a']; cell['area_m2'] = 1.
        cell['model']['layers'][0].update(theta_r=0., theta_s=.75, vg_n=2., vg_alpha_per_m=math.sqrt(8.))
        # Power-of-two density keeps the deposited pore volume exactly
        # representable after binary64 partial-transfer rounding. This test
        # requires actual saturation, not a sub-ULP unsaturated pore deficit.
        cell['materials'][0].update(grain_density_kg_m3=2048., dry_mass_kg_m2=64.)
        cell['soil'] = soil.initial_state(cell['model'], [-1.], [280.])
        self.assertEqual(cell['soil']['total_water'], [.25])
        # Exact half-settling branches retain representable saturated packing.
        case[2][0]['k_per_year']['value'] = 2.**-10
        case[3][0]['settling_m_year'] = 4.*(-math.expm1(-.5))
        case[4]['a'].update(theta_s=.5, theta_r=0.)
        result = transport.step(*case[:5], duration_s=1., seconds_per_year=1.,
            controls={'max_relief_change_fraction': .5, 'max_solid_liquid_ratio': .2, 'evidence': EVIDENCE},
            soil_controls=case[5], evidence=EVIDENCE)
        self.assertTrue(result['ledger']['deposits'])
        for row in result['ledger']['deposits']:
            self.assertEqual(row['head_guess_m'], 0.)
            self.assertFalse(row['pressure_certified'])
            self.assertIn('NONLINEAR_INITIAL_GUESS', row['head_guess_meaning'])
        self.assertEqual(result['cells']['a']['soil']['head_m'][0], 0.)

    def test_native_reversal_preserves_distinct_uneroded_lower_layer(self):
        case = fixture(); cell = case[0]['a']
        lower = deepcopy(cell['model']['layers'][0]); lower['layer_id'] = 'buried-original'
        cell['model']['layers'].append(lower)
        cell['materials'].append(deepcopy(cell['materials'][0]))
        cell['soil'] = soil.initial_state(cell['model'], [-1., -2.], [280., 286.])
        result = run_case(case)
        layers = result['cells']['a']['model']['layers']
        self.assertEqual(layers[-1]['layer_id'], 'buried-original')
        self.assertEqual(F(result['cells']['a']['materials'][-1]['dry_mass_kg_m2']), 156.25)
        self.assertAlmostEqual(result['cells']['a']['soil']['temperature_k'][-1], 286., delta=case[5]['temperature_atol_k'])


class NativeGeometryArithmeticTests(unittest.TestCase):
    """Native-only arithmetic probes, not >128-layer R13 column support."""
    @staticmethod
    def native():
        # No solver, scientific bundle walk or time integration is involved.
        from work.generator_upgrade_r3 import terrain_transport
        return terrain_transport

    def test_many_distinct_porosity_divisors_are_not_added_to_native_depth(self):
        native = self.native(); rows = []
        for i in range(200):
            sample = int.from_bytes(hashlib.sha256(str(i).encode()).digest()[:7], 'big')/(2**56)
            phi = .2+.6*sample
            rows.append({'layer': {'layer_id': str(i), 'thickness_m': .125, 'theta_s': phi},
                         'material': {'material_id': str(i), 'phase': 'mobile_sediment',
                                      'grain_density_kg_m3': 2500.,
                                      'dry_mass_kg_m2': float(2500*(1-phi)*.125), 'evidence': EVIDENCE}})
        cell = {'area_m2': 3., 'base_elevation_m': 2., 'model': {'source_status': 'SYNTHETIC TEST'}}
        old_layers = tuple(native.Layer(r['material']['material_id'], F(r['material']['dry_mass_kg_m2'])*3,
                                       2500, F(r['layer']['theta_s']), 'mobile_sediment', EVIDENCE) for r in reversed(rows))
        old_column = native.Column(3, 2, old_layers, 'SYNTHETIC TEST')
        self.assertGreater(max(old_column.surface_m.numerator.bit_length(), old_column.surface_m.denominator.bit_length()), 8192)
        with self.assertRaisesRegex(ValueError, 'absolute column surface exceeds bounded exact-arithmetic resources'):
            native.LandscapeState((('a', old_column),))
        recorded = []
        state = transport._landscape(native, {'a': cell}, {'a': rows}, F(), reconciliation=recorded)
        self.assertEqual(state.column_map['a'].surface_m, F(27))
        self.assertEqual(state.column_map['a'].mass_kg, old_column.mass_kg)
        self.assertEqual(len(recorded), 200)
        for layer, source, note in zip(state.column_map['a'].layers, reversed(rows), recorded):
            self.assertEqual(layer.bulk_volume_m3/3, F(source['layer']['thickness_m']))
            self.assertEqual(F(note['native_minus_soil_porosity'])*F(source['layer']['thickness_m']), -F(note['solid_volume_residual_m']))
            self.assertEqual(note['native_depth_residual_m'], '0')

    def test_reconciliation_does_not_overwrite_retained_hydraulic_porosity(self):
        native = self.native(); model, _, _ = soil_fixture()
        source = {'layer': model['layers'][0], 'material': {'evidence': EVIDENCE}}
        original = source['layer']['theta_s']
        physical = native.Layer('a', 1, 2500, F(original)+F(1, 2**50), 'mobile_sediment', EVIDENCE)
        retained = transport._target(source, physical, F(1), F(), F(), F(1), -1.)
        deposited = transport._target(source, physical, F(1), F(), F(), F(1), -1., layer_id='new')
        self.assertEqual(retained['layer']['theta_s'], original)
        self.assertEqual(deposited['layer']['theta_s'], float(physical.porosity))
        self.assertNotEqual(deposited['layer']['theta_s'], original)

    def test_reconciliation_keeps_existing_64_ulp_guard(self):
        native = self.native()
        cell = {'area_m2': 1., 'base_elevation_m': 0., 'model': {'source_status': 'SYNTHETIC TEST'}}
        rows = [{'layer': {'layer_id': 'bad', 'thickness_m': .125, 'theta_s': .5},
                 'material': {'material_id': 'bad', 'phase': 'mobile_sediment',
                              'dry_mass_kg_m2': 200., 'grain_density_kg_m3': 2500., 'evidence': EVIDENCE}}]
        with self.assertRaisesRegex(ValueError, '64 represented ULP'):
            transport._landscape(native, {'a': cell}, {'a': rows}, F())


if __name__ == '__main__':
    unittest.main()
