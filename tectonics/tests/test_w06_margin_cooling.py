"""Independent inherited-profile, boundary-heat and source/support join checks."""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
from threading import Event
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy.integrate import quad

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.constitutive import BoussinesqMaterial
from atlas_tectonics.geological_records import ThermalInitialProfile
from atlas_tectonics.margin_cooling import PreparedMarginCooling
import atlas_tectonics.margin_cooling as margin_module
from atlas_tectonics.parameters import ThermalParameters, PlateCoolingParameters
from atlas_tectonics.precursor import InitialConditionState, InitialScalarField
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.thermal_support import ThermalSupportParameters
import precursor_fixtures as fixture


PLATE = PlateCoolingParameters(ThermalParameters('inherited-plate', 'synthetic conduction choice',
                                                300., 1300., 1e-6), 100000., 3.)
DEPTHS = np.array([0., 20000., 65000., 100000.])


def inherited(amplitude=1., *, mode='tabulated', initial=False, **case_changes):
    material = replace(fixture.ROCK, thermal_expansion_per_k=1e-5)
    profile = ThermalInitialProfile('initial', 'fixture', mode, tuple(DEPTHS),
        tuple(300.+DEPTHS/100000.*1000.+amplitude*np.array([0., 150., 200., 0.])))
    case = fixture.case(materials=(material,), thermal_profiles=(profile,),
        columns=(fixture.column(layers=(fixture.layer(thickness=40000.),
            fixture.layer('mantle', 60000., 'lithospheric_mantle'))),), **case_changes)
    state = fixture.state(case)
    if initial:
        state = InitialConditionState(case, origins=state.origins, cooling_history=state.cooling_history,
                                      material_bases=state.material_bases)
    return state


def changed_case(case, **changes):
    names = ('case_id', 'topology', 'time_s', 'epoch_id', 'depth_reference_id', 'source_id',
             'sources', 'materials', 'cohorts', 'thermal_profiles', 'columns', 'geometries',
             'provinces', 'faults', 'weak_zones', 'precedence')
    return fixture.case(**({name:getattr(case, name) for name in names}|changes))


def independent_reference(source, elapsed, edges):
    """Quadrature of original table into independent Fourier modes and depths.

    This never calls production preparation, slope-jump coefficients or cell
    integration. The smallest positive reference time is tau=1e-4, where 240
    modes have exp(-56.8) suppression and the controlled tail is negligible.
    """
    profile = source.case.thermal_profiles[0]
    x = np.asarray(profile.depths_m)/PLATE.thickness_m
    values = np.asarray(profile.temperatures_k)
    tau = elapsed*PLATE.thermal.diffusivity_m2_s/PLATE.thickness_m**2
    def perturbation(z):
        return float(np.interp(z, x, values))-(300.+1000.*z)
    coefficients = []
    for n in range(1, 241):
        pieces = [quad(lambda z: 2*perturbation(z)*math.sin(n*math.pi*z), a, b,
                       epsabs=2e-11, epsrel=2e-12, limit=100)[0] for a, b in zip(x[:-1], x[1:])]
        coefficients.append(math.fsum(pieces))
    n = np.arange(1, 241)
    evolved = np.asarray(coefficients)*np.exp(-n*n*math.pi**2*tau)
    def temperature(z):
        return 300.+1000.*z+float(np.dot(evolved, np.sin(n*math.pi*z)))
    means = [quad(temperature, a/100000., b/100000., epsabs=1e-10, epsrel=1e-12)[0]*100000./(b-a)
             for a, b in zip(edges[:-1], edges[1:])]
    weights = [math.fsum(quad(lambda z: w(z)*perturbation(z), a, b, epsabs=1e-11)[0]
                        for a, b in zip(x[:-1], x[1:])) for w in (lambda z: 1-z, lambda z:z)]
    heat = np.array([1000.*tau+weights[0]-np.sum(evolved/(n*math.pi)),
                     -1000.*tau+weights[1]+np.sum((-1.)**n*evolved/(n*math.pi))])*3e11
    return np.asarray(means), heat


class MarginCoolingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def plan(self, source=None, **changes):
        arguments = dict(thinning_source_id='fixture', geometry_reference_id='reference-surface',
                         context=self.context)
        arguments.update(changes)
        return PreparedMarginCooling(inherited() if source is None else source, 'continent', PLATE, **arguments)

    def evaluate(self, plan, time_s, edges=(0., 7000., 40000., 65000., 100000.)):
        return plan.evaluate(time_s=time_s, epoch_id=fixture.REQUEST['epoch_id'], depth_edges_m=edges)

    def test_zero_epoch_preserves_actual_source_and_exact_piecewise_means(self):
        source = inherited(initial=True)
        with self.plan(source) as plan:
            result = self.evaluate(plan, 0., (0., 15000., 20000., 90000., 100000.))
            expected = []
            for a, b in zip(result.depth_edges_m[:-1], result.depth_edges_m[1:]):
                points = [float(z) for z in DEPTHS if a < z < b]
                expected.append(quad(lambda z: np.interp(z, DEPTHS, source.case.thermal_profiles[0].temperatures_k),
                                     a, b, points=points, epsabs=1e-5)[0]/(b-a))
            # Independent quadrature and segment summation have distinct
            # binary64 rounding; this is far below the 1e-3 K W06 gate.
            assert_allclose(result.mean_temperature_k, expected, rtol=0, atol=1e-11)
            assert_array_equal(result.mean_temperature_k, result.initial_reference_temperature_k)
            assert_array_equal(result.outward_heat_j_m2, [0., 0.])
            self.assertIs(result.source_state, source)
            self.assertIs(result.source_column, source.case.columns[0])
            self.assertIs(result.source_profile, source.case.thermal_profiles[0])
            self.assertEqual(result.cooling_history.start_time_s, -10.)
            self.assertEqual(result.elapsed_s, 0.)  # Never mistaken for that history's cooling age.
            self.assertEqual(result.thinning_source_id, source.case.sources[0].source_id)
            for array in (result.mean_temperature_k, result.initial_reference_temperature_k,
                          result.depth_edges_m, result.temperature_change_k, result.outward_heat_j_m2):
                with self.assertRaises(ValueError):
                    array.flags.writeable = True

    def test_hot_and_cool_fields_against_independent_quad_and_boundary_heat(self):
        edges = (0., 7000., 20000., 53000., 99900., 100000.)
        for amplitude in (1., -.8):
            source = inherited(amplitude)
            with self.plan(source) as plan:
                for tau in (1e-4, .02, 1/16, .063, .7):
                    with self.subTest(amplitude=amplitude, tau=tau):
                        elapsed = tau*1e16
                        result = self.evaluate(plan, elapsed, edges)
                        expected, heat = independent_reference(source, elapsed, edges)
                        assert_allclose(result.mean_temperature_k, expected, rtol=0, atol=2e-9)
                        assert_allclose(result.outward_heat_j_m2, heat, rtol=2e-10, atol=.03)
                        energy_change = 3e6*np.dot(result.temperature_change_k, np.diff(edges))
                        residual = energy_change+math.fsum(result.outward_heat_j_m2)
                        scale = max(abs(energy_change), sum(abs(result.outward_heat_j_m2)))
                        self.assertLess(abs(residual)/scale, 2e-12)

    def test_steady_profile_and_constant_compatible_profile(self):
        with self.plan(inherited(0.)) as plan:
            for elapsed in (0., 1e-6, 1e12, 1e16):
                result = self.evaluate(plan, elapsed)
                assert_allclose(result.temperature_change_k, 0., atol=1e-12)
                assert_allclose(result.outward_heat_j_m2, [3e-2*elapsed, -3e-2*elapsed], rtol=2e-14)
        constant = replace(PLATE, thermal=replace(PLATE.thermal, mantle_temperature_k=300.))
        source = fixture.state(fixture.case(materials=(fixture.ROCK,), columns=(fixture.column(
            layers=(fixture.layer(thickness=40000.), fixture.layer('mantle', 60000., 'lithospheric_mantle'))),)))
        with PreparedMarginCooling(source, 'continent', constant, thinning_source_id='fixture',
             geometry_reference_id='reference-surface', context=self.context) as plan:
            result = self.evaluate(plan, 1e16)
            assert_array_equal(result.mean_temperature_k, np.full(4, 300.))
            assert_array_equal(result.outward_heat_j_m2, [0., 0.])

    def test_young_corner_and_narrow_depth_cells_do_not_reset_or_floor_age(self):
        source = inherited()
        elapsed = 1e-2
        tau = elapsed*1e-16
        scale_m = math.sqrt(tau)*1e5
        edges = (0., 20000.-scale_m/10, 20000., 20000.+scale_m/10, 100000.)
        with self.plan(source) as plan:
            result = self.evaluate(plan, elapsed, edges)
            slopes = np.diff(source.case.thermal_profiles[0].temperatures_k)/np.diff(DEPTHS/1e5)
            jump = slopes[1]-slopes[0]
            for i in (1, 2):
                a, b = (edges[i]-20000.)/1e5, (edges[i+1]-20000.)/1e5
                expected = jump*quad(lambda r: math.sqrt(tau/math.pi)*math.exp(-r*r/(4*tau))
                    -abs(r)/2*math.erfc(abs(r)/(2*math.sqrt(tau))), a, b, epsabs=1e-30)[0]/(b-a)
                self.assertAlmostEqual(result.temperature_change_k[i]/expected, 1., delta=3e-7)
            self.assertLess(result.temperature_change_k[1], 0.)
            expected_heat = np.array([slopes[0], -slopes[-1]])*tau*3e11
            assert_allclose(result.outward_heat_j_m2, expected_heat, rtol=2e-14)

    def test_evaluations_remain_bound_to_original_epoch_and_partition_independent(self):
        with self.plan() as plan:
            direct = self.evaluate(plan, 1e15)
            for t in np.linspace(0., 1e15, 5):
                _ = self.evaluate(plan, t)
            repeated = self.evaluate(plan, 1e15)
            self.assertEqual(direct.state_id, repeated.state_id)
            assert_array_equal(direct.mean_temperature_k, repeated.mean_temperature_k)
            nearby = self.evaluate(plan, math.nextafter(1e15, math.inf))
            assert_allclose(nearby.mean_temperature_k, direct.mean_temperature_k, atol=1e-12, rtol=0)
            self.assertNotEqual(nearby.state_id, direct.state_id)

    def test_mixed_hot_cold_profile_uses_named_nonzero_epoch_without_inventing_age(self):
        source = inherited()
        profile = replace(source.case.thermal_profiles[0], temperatures_k=(300., 650., 800., 1300.))
        case = changed_case(source.case, time_s=1e12, thermal_profiles=(profile,))
        unknown = replace(source.cooling_history[0], start_time_s=None, unknown_reason='earlier thermal history unknown')
        source = fixture.state(case, cooling_history=(unknown,))
        with self.plan(source) as plan:
            result = self.evaluate(plan, 1e12+1e14)
            expected, heat = independent_reference(source, 1e14, result.depth_edges_m)
            assert_allclose(result.mean_temperature_k, expected, rtol=0, atol=2e-9)
            assert_allclose(result.outward_heat_j_m2, heat, rtol=2e-10, atol=.03)
            self.assertEqual(result.elapsed_s, 1e14)
            self.assertEqual(result.source_time_s, 1e12)
            self.assertIsNone(result.cooling_history.start_time_s)
            with self.assertRaises(TectonicsError):
                self.evaluate(plan, 1e12-1.)

    def test_refuses_unsupported_source_profiles_geometry_and_properties(self):
        source = inherited()
        for mode, changes in (
                ('unknown', dict(unknown_reason='not supplied')),
                ('half_space', dict(temperatures_k=(300., 1300.), diffusivity_m2_s=1e-6, cooling_start_time_s=-10.)),
                ('constant', dict(temperatures_k=(1000.,)))):
            profile = ThermalInitialProfile('initial', 'fixture', mode, **changes)
            bad = fixture.state(changed_case(source.case, thermal_profiles=(profile,)))
            with self.subTest(mode=mode), self.assertRaises(TectonicsError):
                self.plan(bad)
        for changes in (dict(thinning_source_id='invented'), dict(geometry_reference_id='invented')):
            with self.assertRaises(TectonicsError):
                self.plan(source, **changes)
        for material in (replace(source.case.materials[0], conductivity_w_m_k=4.),
                         replace(source.case.materials[0], heat_production_w_m3=1.)):
            with self.assertRaises(TectonicsError):
                self.plan(fixture.state(changed_case(source.case, materials=(material,))))
        bad_profile = replace(source.case.thermal_profiles[0], temperatures_k=(301., 650., 1150., 1300.))
        with self.assertRaises(TectonicsError):
            self.plan(fixture.state(changed_case(source.case, thermal_profiles=(bad_profile,))))

    def test_epoch_closed_cancel_budget_and_live_source_guards(self):
        event = Event(); event.set()
        with self.assertRaises(CancelledError):
            self.plan(cancel=event)
        budget = WorkBudget(128*1024**2)
        with self.plan(budget=budget) as plan:
            with self.assertRaises(TectonicsError):
                plan.evaluate(time_s=1., epoch_id='wrong', depth_edges_m=(0., 100000.))
            with self.assertRaises(TectonicsError):
                self.evaluate(plan, -1.)
            with self.assertRaises(CancelledError):
                plan.evaluate(time_s=1., epoch_id=fixture.REQUEST['epoch_id'],
                              depth_edges_m=(0., 100000.), cancel=event)
            with self.assertRaises(MemoryLimitError):
                plan.evaluate(time_s=1., epoch_id=fixture.REQUEST['epoch_id'], depth_edges_m=(0., 100000.),
                              budget=WorkBudget(1024, parent=budget))
            with self.assertRaises(TectonicsError):
                plan.evaluate(time_s=1., epoch_id=fixture.REQUEST['epoch_id'], depth_edges_m=(0., 100000.),
                              budget=WorkBudget(128*1024**2))
            with mock.patch('atlas_tectonics.reuse._source_bytes', return_value={}):
                with self.assertRaisesRegex(TectonicsError, 'source changed'):
                    self.evaluate(plan, 1.)
            with mock.patch.object(margin_module, '_corner_mean', lambda *args: 0.):
                with self.assertRaisesRegex(TectonicsError, 'implementation changed'):
                    self.evaluate(plan, 1.)
        self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaisesRegex(TectonicsError, 'closed'):
            self.evaluate(plan, 1.)

    def support_inputs(self, source):
        m = source.case.materials[0]
        material = BoussinesqMaterial(m.material_id, m.source_id, m.density_kg_m3,
            m.specific_heat_j_kg_k, m.conductivity_w_m_k, m.thermal_expansion_per_k,
            m.reference_temperature_k, 0., 0., (300., 2000.), .05)
        parameters = ThermalSupportParameters('reference-surface', 'synthetic inherited reference',
            'reference-surface', 'column-isostasy', 3300., 1030., 9.81, .05)
        return dict(materials={m.material_id:material}, parameters=parameters, initial_depth_m=2000.,
                    area_m2=10., water_stock_m3=1e6, water_source_id='finite-test-ocean')

    def test_young_image_work_is_bounded_before_scalar_interactions(self):
        with mock.patch.object(margin_module, '_MAX_IMAGE_INTERACTIONS', 1):
            with ExecutionContext('reference') as context:
                with self.plan(context=context) as plan:
                    with self.assertRaisesRegex(TectonicsError, 'interaction budget'):
                        self.evaluate(plan, 1e12)

    def test_source_bound_support_water_and_unchanged_material_accounts(self):
        for amplitude in (1., -.8):
            source = inherited(amplitude)
            arguments = self.support_inputs(source)
            with self.plan(source) as plan:
                result = plan.support(time_s=1e15, epoch_id=fixture.REQUEST['epoch_id'], **arguments)
                expected, _ = independent_reference(source, 1e15, source.case.columns[0].layer_edges_m)
                sheet = 3000.*1e-5*np.dot(result.thermal.initial_reference_temperature_k-expected, [40000.,60000.])
                self.assertAlmostEqual(result.sheet_anomaly_kg_m2, sheet, delta=1e-7)
                self.assertAlmostEqual(result.downward_displacement_m, sheet/2270., delta=1e-10)
                self.assertEqual(result.reference_water_m3, 20000.)
                self.assertAlmostEqual(result.water_change_m3, 10.*result.downward_displacement_m)
                self.assertAlmostEqual(result.represented_water_m3+result.water_remaining_m3, 1e6)
                self.assertEqual(sum(row[2] for row in result.reference_material_mass_kg), 3e9)
                self.assertEqual(result.thermal_owner, 'column-isostasy')
                self.assertLess(result.trajectory_depth_bounds_m[0], result.water_depth_m)
                self.assertGreater(result.trajectory_depth_bounds_m[1], result.water_depth_m)
                self.assertEqual(math.copysign(1., result.downward_displacement_m), math.copysign(1., amplitude))
                zero = plan.support(time_s=0., epoch_id=fixture.REQUEST['epoch_id'], **arguments)
                self.assertEqual(zero.downward_displacement_m, 0.)
                self.assertEqual(zero.reference_material_mass_kg, result.reference_material_mass_kg)

    def test_support_refuses_duplicate_owner_material_mismatch_water_exhaustion_and_emergence(self):
        source = inherited(-.8)
        with self.plan(source) as plan:
            args = self.support_inputs(source)
            for changes in (
                dict(parameters=replace(args['parameters'], thermal_owner='flexure')),
                dict(parameters=replace(args['parameters'], reference_id='unrelated')),
                dict(materials={'grain_a':replace(args['materials']['grain_a'], source='invented')}),
                dict(materials={'grain_a':replace(args['materials']['grain_a'], density_kg_m3=3100.)}),
                dict(water_stock_m3=1.), dict(initial_depth_m=.001)):
                with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                    plan.support(time_s=1e15, epoch_id=fixture.REQUEST['epoch_id'], **(args|changes))

    def test_uplift_cannot_hide_insufficient_initial_water_or_unproven_trajectory(self):
        source = inherited(-.8)
        args = self.support_inputs(source)
        with self.plan(source) as plan:
            reference = args['initial_depth_m']*args['area_m2']
            result = plan.support(time_s=1e15, epoch_id=fixture.REQUEST['epoch_id'], **args)
            self.assertLess(result.represented_water_m3, reference-1.)
            with self.assertRaisesRegex(TectonicsError, 'reference geometry'):
                plan.support(time_s=1e15, epoch_id=fixture.REQUEST['epoch_id'],
                             **(args|dict(water_stock_m3=reference-1.)))
            # Both target and reference would fit; the whole trajectory is not
            # certified by this endpoint observation and must refuse visibly.
            with self.assertRaisesRegex(TectonicsError, 'trajectory.*unproven'):
                plan.support(time_s=1e15, epoch_id=fixture.REQUEST['epoch_id'],
                             **(args|dict(water_stock_m3=reference+1.)))


if __name__ == '__main__':
    unittest.main()
