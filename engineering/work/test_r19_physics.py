"""Three bounded R19 physics checks; SYNTHETIC TEST, not actual coast geometry.

Water METHOD_R2 / WORKING_SCENARIO_R2 parameters; no production/annual runs.
Allowances are declared before execution and use gross changed quantities.
"""
from copy import deepcopy
from fractions import Fraction as F
import math
import unittest

from work.generator_upgrade_r16 import regional
from work.generator_upgrade_r18 import composite
from work.generator_upgrade_r19 import flow, sediment, state


CONSTANTS = {'gravity_m_s2': 9.81, 'water_density_kg_m3': 1000}
LOCAL_REFINEMENT_RTOL = .05
STATUS = 'SYNTHETIC TEST'


def palette_fixture():
    """Two synthetic constituents, preserving congruent mass/solid accounts."""
    descriptor = composite.create([
        {'unit_id': 'TEST-A', 'bulk_weight': '1/2', 'grain_density_kg_m3': '2000', 'porosity': '2/5'},
        {'unit_id': 'TEST-B', 'bulk_weight': '1/2', 'grain_density_kg_m3': '3000', 'porosity': '2/5'},
    ], '1/100000', phase='mobile_sediment', evidence=STATUS+'; illustrative constituent properties')
    mid = descriptor['material_id']
    return {mid: descriptor}, mid


def cell_fixture(palette, mid, *, free=1, surface=0, area=1, thickness=1,
                 porosity=None, pore=0, suspended=None, momentum=(0., 0.), kind='water'):
    _, native = regional.p.backend()
    area, thickness, surface = F(area), F(thickness), F(surface)
    rho = state.density(mid, palette)
    phi = F(palette[mid]['porosity']) if porosity is None else F(porosity)
    layers = () if not thickness else (native.Layer(mid, area*thickness*rho*(1-phi),
        rho, phi, 'mobile_sediment', STATUS+'; finite substrate'),)
    column = native.Column(area, surface-thickness, layers, STATUS)
    result = state.Cell(column, [F(pore)] if layers else [], F(free),
        {k: F(v) for k, v in (suspended or {}).items()}, tuple(momentum), kind)
    result.validate(palette)
    return result


def two_cell_faces(left='L', right='R'):
    """Two adjoining unit-square numerical cells with ALL perimeter walls."""
    rows = [{'id': 'internal', 'left': left, 'right': right, 'width_m': 1, 'normal_xy': [1, 0]}]
    for key, sides in ((left, [('west', [-1, 0]), ('north', [0, -1]), ('south', [0, 1])]),
                       (right, [('east', [1, 0]), ('north', [0, -1]), ('south', [0, 1])])):
        rows.extend({'id': key+'-'+side, 'left': key, 'right': None,
                     'width_m': 1, 'normal_xy': normal} for side, normal in sides)
    return rows


def parameters_fixture():
    return {'water_density_kg_m3': 1000, 'bottom_drag_coefficient': .003,
        'sediment_settling_m_s': .001, 'fresh_mobile_deposit_porosity': .4,
        'dilute_suspended_solid_volume_fraction_max': .001,
        'bedrock': {'coastal_beta_m_s': 1e-10, 'critical_shear_Pa': 2},
        'mobile': {'coastal_beta_m_s': 1e-7, 'critical_shear_Pa': .2, 'contrast': 1}}


def forcing_fixture(wave=0, points=16):
    return {'wind_stress_Pa': [0., 0.], 'wave_rms_shear_Pa': wave,
            'wave_direction_xy': [1., 0.], 'phase_points': points}


class CoastalPhysicsTests(unittest.TestCase):
    def _closed(self, before, cells, palette, imported_water=F()):
        after = state.inventory(cells, palette)
        imported = {'water_m3': F(imported_water), 'materials_kg': {}, 'solid_m3': {}}
        receipt = state.balances(before, imported, after, palette)
        self.assertEqual(F(receipt['water_residual_m3']), 0)
        for row in receipt['materials']:
            self.assertEqual(F(row['mass_residual_kg']), 0)
            self.assertEqual(F(row['solid_residual_m3']), 0)
        for row in receipt['constituents']:
            self.assertEqual(F(row['residual_mass_kg']), 0)
            self.assertEqual(F(row['residual_solid_volume_m3']), 0)
        return after

    def test_lake_rest_wet_dry_and_finite_mouth_reversal(self):
        palette, mid = palette_fixture()
        params, forcing, faces = parameters_fixture(), forcing_fixture(), two_cell_faces()
        lake = {'L': cell_fixture(palette, mid, free=1, surface=0),
                'R': cell_fixture(palette, mid, free='1/2', surface='1/2')}
        saved = {k: c.as_dict() for k, c in lake.items()}
        before = state.inventory(lake, palette)
        dt = flow.stable_dt(lake, palette, faces, [], CONSTANTS, params, forcing, .01)
        rest = flow.advance(lake, palette, faces, [], dt, CONSTANTS, params, forcing)
        self.assertEqual({k: c.as_dict() for k, c in lake.items()}, saved)
        self.assertEqual(F(rest['gross_mixture_transfer_m3']), 0)
        self._closed(before, lake, palette)
        with self.assertRaises(ValueError):
            flow.validate_geometry(lake, faces[:-1], [])

        wet_dry = {'L': cell_fixture(palette, mid, suspended={mid: '1/4'}),
                   'R': cell_fixture(palette, mid, free=0)}
        before = state.inventory(wet_dry, palette)
        beds = {k: c.column.as_dict() for k, c in wet_dry.items()}
        dt = flow.stable_dt(wet_dry, palette, faces, [], CONSTANTS, params, forcing, .01)
        moved = flow.advance(wet_dry, palette, faces, [], dt, CONSTANTS, params, forcing)
        self.assertGreater(wet_dry['R'].free, 0)
        self.assertGreater(wet_dry['R'].suspended[mid], 0)
        self.assertGreater(wet_dry['R'].momentum[0], 0)
        self.assertGreater(F(moved['gross_mixture_transfer_m3']), 0)
        self.assertEqual({k: c.column.as_dict() for k, c in wet_dry.items()}, beds)
        self._closed(before, wet_dry, palette)

        link = [{'id': 'mouth', 'left': 'L', 'right': 'R', 'crest_m': 0, 'conductance_m2_s': 1}]
        reach = {'L': cell_fixture(palette, mid, free=2, kind='reach',
                                  suspended={mid: '1/4'}, momentum=(.2, 0.)),
                 'R': cell_fixture(palette, mid, free=1, kind='reach')}
        before = state.inventory(reach, palette)
        outgoing = flow.advance(reach, palette, [], link, .1, CONSTANTS, params, forcing)
        self.assertEqual(outgoing['transfers'][0]['donor'], 'L')
        self.assertLess(outgoing['momentum_ports_m4_s']['reduced_link_support'][0], 0)
        self.assertTrue(all(c.momentum == (0., 0.) for c in reach.values()))
        self._closed(before, reach, palette)
        before_pulse = state.inventory(reach, palette)
        reach['R'].free += F(3)  # Explicit external boundary pulse, not a level reset.
        reverse = flow.advance(reach, palette, [], link, .1, CONSTANTS, params, forcing)
        self.assertEqual(reverse['transfers'][0]['donor'], 'R')
        self.assertLess(reverse['transfers'][0]['signed_discharge_m3_s'], 0)
        self._closed(before_pulse, reach, palette, imported_water=F(3))
        self.assertTrue(all(c.free >= 0 for c in reach.values()))

        dry = {'L': cell_fixture(palette, mid, free=0, surface=1, kind='reach'),
               'R': cell_fixture(palette, mid, free=0, kind='reach')}
        before = state.inventory(dry, palette)
        capped = flow.advance(dry, palette, [], link, .1, CONSTANTS, params, forcing)
        self.assertTrue(capped['link_demands'][0]['dry_donor_availability_cap'])
        self.assertGreater(capped['link_demands'][0]['head_law_discharge_m3_s'], 0)
        self.assertEqual(capped['link_demands'][0]['effective_discharge_m3_s'], 0)
        self.assertGreater(F(capped['link_demands'][0]['effective_current_bed_crest_m']),
                           F(capped['link_demands'][0]['fixed_crest_m']))
        self.assertEqual(F(capped['gross_mixture_transfer_m3']), 0)
        self._closed(before, dry, palette)

    def test_saturated_pore_inverse_momentum_and_insufficient_liquid(self):
        palette, mid = palette_fixture()
        grain = F('0.0001')  # Final Water R2 pore oracle; not interim R1 amount.
        mass = grain*state.density(mid, palette)
        for phi in (F(0), F('0.2'), F('0.4'), F('0.6')):
            with self.subTest(porosity=str(phi)):
                cell = cell_fixture(palette, mid, suspended={mid: mass}, momentum=(2., -1.))
                before = state.inventory({'C': cell}, palette)
                original, eta, volume = cell.as_dict(), cell.eta(palette), cell.volume(palette)
                deposited = sediment.deposit(cell, palette, mid, mass, phi, STATUS+'; pore oracle')
                pore = grain*phi/(1-phi)
                self.assertEqual(F(deposited['pore_liquid_debited_m3']), pore)
                self.assertEqual(cell.free, F(1)-pore)
                self.assertEqual(cell.eta(palette), eta)
                expected_ratio = float((volume-grain/(1-phi))/volume)
                for axis, initial in enumerate(original['momentum']):
                    self.assertEqual(cell.momentum[axis], initial*expected_ratio)
                    self.assertAlmostEqual(cell.momentum[axis]+deposited['momentum_to_bed_m4_s'][axis],
                                           initial, delta=1e-12)
                retained_momentum = cell.momentum
                self._closed(before, {'C': cell}, palette)
                eroded = sediment.erode_top(cell, palette, mass)
                self.assertEqual(F(eroded['pore_liquid_released_m3']), pore)
                self.assertEqual(cell.column.as_dict(), original['column'])
                self.assertEqual(cell.pores, [F(v) for v in original['pores']])
                self.assertEqual(cell.free, 1)
                self.assertEqual(cell.suspended[mid], mass)
                self.assertEqual(cell.eta(palette), eta)
                self.assertEqual(cell.momentum, retained_momentum)  # Stationary entrainment, not momentum recreation.
                self.assertEqual(eroded['momentum_to_bed_m4_s'], [0., 0.])
                self._closed(before, {'C': cell}, palette)

        insufficient = cell_fixture(palette, mid, free='0.00001', suspended={mid: mass})
        unchanged = insufficient.as_dict()
        with self.assertRaisesRegex(ValueError, 'insufficient free liquid'):
            sediment.deposit(insufficient, palette, mid, mass, F('0.6'), STATUS+'; no groundwater')
        self.assertEqual(insufficient.as_dict(), unchanged)
        partial = cell_fixture(palette, mid, porosity='0.4', pore='0.1')
        before = state.inventory({'C': partial}, palette)
        released = sediment.erode_top(partial, palette, partial.column.layers[-1].mass_kg/2)
        self.assertEqual(F(released['pore_liquid_released_m3']), F('0.05'))
        self.assertEqual(partial.pores, [F('0.05')])
        self._closed(before, {'C': partial}, palette)

    def test_transient_settling_wave_response_and_local_refinement(self):
        palette, mid = palette_fixture()
        params, calm = parameters_fixture(), forcing_fixture()
        initial_mass = state.density(mid, palette)*F('0.0000001')
        start = cell_fixture(palette, mid, suspended={mid: initial_mass})
        depth, duration = float(start.depth(palette)), 100
        oracle = float(initial_mass)*math.exp(-.001*duration/depth)
        oracle_gross = float(initial_mass)-oracle
        settling_outputs = []
        for steps in (1, 2):
            cell = deepcopy(start); before = state.inventory({'C': cell}, palette)
            deposited = F()
            for _ in range(steps):
                result = sediment.evolve(cell, palette, F(duration, steps), params, calm)
                deposited += F(result['deposited_mass_kg'].get(mid, 0))
                self.assertEqual(result['wave_mean_momentum_added_m4_s'], [0., 0.])
            remaining = float(cell.suspended[mid])
            self.assertLessEqual(abs(remaining-oracle), LOCAL_REFINEMENT_RTOL*oracle_gross)
            self.assertEqual(initial_mass-cell.suspended[mid], deposited)
            self.assertLess(float(cell.column.surface_m-start.column.surface_m)/depth, 1e-6)
            self._closed(before, {'C': cell}, palette)
            settling_outputs.append(float(deposited))
        self.assertLessEqual(abs(settling_outputs[0]-settling_outputs[1]),
                             LOCAL_REFINEMENT_RTOL*max(settling_outputs))

        wave_params = deepcopy(params)
        wave_params['sediment_settling_m_s'] = 0  # Isolate shear; no duplicate settling model.
        amplitude_ratio = math.sqrt(2)*3/.2
        continuous_response = 2/math.pi*(math.sqrt(amplitude_ratio**2-1)-math.acos(1/amplitude_ratio))
        baseline = cell_fixture(palette, mid)
        layer = baseline.column.layers[-1]
        expected = 1e-7*continuous_response*float(layer.grain_density_kg_m3*(1-layer.porosity))
        erosion_outputs = {}
        for points, steps in ((16, 1), (32, 1), (32, 2)):
            cell = deepcopy(baseline); before = state.inventory({'C': cell}, palette)
            eroded = F()
            for _ in range(steps):
                result = sediment.evolve(cell, palette, F(1, steps), wave_params, forcing_fixture(3, points))
                eroded += F(result['eroded_mass_kg'].get(mid, 0))
                self.assertEqual(result['wave_mean_momentum_added_m4_s'], [0., 0.])
                self.assertEqual(cell.momentum, (0., 0.))
            self.assertGreater(eroded, 0)
            self.assertLessEqual(abs(float(eroded)-expected), LOCAL_REFINEMENT_RTOL*expected)
            self._closed(before, {'C': cell}, palette)
            erosion_outputs[points, steps] = float(eroded)
        self.assertLess(abs(erosion_outputs[32, 1]-expected), abs(erosion_outputs[16, 1]-expected))
        self.assertLessEqual(abs(erosion_outputs[16, 1]-erosion_outputs[32, 1]),
                             LOCAL_REFINEMENT_RTOL*erosion_outputs[32, 1])
        self.assertLessEqual(abs(erosion_outputs[32, 1]-erosion_outputs[32, 2]),
                             LOCAL_REFINEMENT_RTOL*erosion_outputs[32, 2])
        calm_cell = deepcopy(baseline)
        no_erosion = sediment.evolve(calm_cell, palette, 1, wave_params, calm)
        self.assertEqual(no_erosion['eroded_mass_kg'], {})
        # A non-dilute starting state cannot be repaired by silently subcycling.
        invalid = cell_fixture(palette, mid, suspended={mid: state.density(mid, palette)*F('0.002')})
        saved = invalid.as_dict()
        with self.assertRaisesRegex(ValueError, 'non-dilute'):
            sediment.evolve(invalid, palette, F(1, 1000), params, calm)
        self.assertEqual(invalid.as_dict(), saved)


if __name__ == '__main__':
    unittest.main()
