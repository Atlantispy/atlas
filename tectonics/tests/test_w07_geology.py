"""W07 source binding: synthetic authored geology passed through real W01/W02.

No hand-built mechanical arrays are accepted as geological inputs. Independent
layer integrals test both the thermal/inventory meaning and shear dual support.
"""
from concurrent.futures import CancelledError
from dataclasses import replace
import unittest
import threading
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (BoundaryRegion, CohortDescription, FeaturePrecedence,
    GeologicalCase, GeologicalProvince, LayerComponent, MaterialCohort,
    RegionalGrid1D, SurfaceSelector, TectonicsError, build_boundary_network)
from atlas_tectonics.regional_geology import (GeologicalMaterialLaw,
    RegionalGeologicalInputs, RegionalPhysicsOwnership, bind_regional_geology)
from atlas_tectonics.regional_forcing import RegionalReduction
from atlas_tectonics.regional_workflow import PreparedRegionalWorkflow
from atlas_tectonics.regional_workflow_geometry import RegionalColumnSupport
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from test_w01_geological_description import SOURCE, ROCK, TEMP, column, layer
from test_w01_initial_sampling import initial
from test_w01_regional_forcing import box, definition, motion, planar
from test_w01_workflow import workflow_fixture, STEADY_LEFT, RIGHT


def geology_fixture(*, layered=False, thermal=False, speed=0., density_law='reference-constant',
                    nx=4, nz=4, upper_thickness=.63, heat_production=0.,budget=None):
    """A real typed W01 description, then its public W01/W02 initial producer."""
    domain = box(x1=2., y1=1.)
    topology = build_boundary_network(domain, (BoundaryRegion('whole', 'A', domain),))
    low = replace(ROCK, density_kg_m3=2., thermal_expansion_per_k=1e-4,
                  heat_production_w_m3=heat_production)
    high = replace(low, material_id='other-rock', density_kg_m3=3.)
    a = CohortDescription(MaterialCohort('a', 'rock', 'origin-a', -10.), 'synthetic')
    b = CohortDescription(MaterialCohort('b', 'other-rock', 'origin-b', -20.), 'synthetic')
    ls = ((layer('upper', thickness=upper_thickness, components=(LayerComponent('b', 1.),)),
           layer('lower', thickness=1.-upper_thickness, components=(LayerComponent('a', 1.),)))
          if layered else (layer('whole', thickness=1., components=(LayerComponent('a', 1.),)),))
    profile = replace(TEMP, mode='tabulated', depths_m=(0., 1.), temperatures_k=(300., 500.)) if thermal else TEMP
    case = GeologicalCase(case_id='w07-geology-synthetic', topology=topology, time_s=0.,
        epoch_id='epoch', depth_reference_id='original-inward-surface', source_id='synthetic',
        sources=(SOURCE,), materials=(low, high) if layered else (low,),
        cohorts=(a, b) if layered else (a,), thermal_profiles=(profile,),
        columns=(column(layers=ls),),
        provinces=(GeologicalProvince('whole', 'continental', SurfaceSelector('domain'), 'synthetic'),),
        precedence=FeaturePrecedence(('whole',)))
    args = (initial(case), definition(topology, (motion(translation=(speed, 0., 0.)),)),
            planar(origin_m=(0., .5, 0.), length_m=2.),
            RegionalReduction('planar-columns', 'frozen-at-start', SOURCE, 1.),
            RegionalGrid1D(nx, 2.), RegionalColumnSupport('planar-strip', 0., 1., SOURCE))
    with PreparedRegionalWorkflow(*args, backend='reference',budget=budget) as plan:
        state = plan.initialise()
    laws = (GeologicalMaterialLaw('rock', 1., SOURCE, density_law),)
    if layered:
        laws += (GeologicalMaterialLaw('other-rock', 1000., SOURCE, density_law),)
    kwargs = dict(nz=nz, material_laws=laws, ownership=RegionalPhysicsOwnership(SOURCE, SOURCE, SOURCE, SOURCE),
        gravity_m_s2=1., vertical_datum='mechanical-bottom-z0')
    return state, kwargs


class GeologicalBindingTests(unittest.TestCase):
    def test_actual_geological_fields_inventory_and_immutable_capture(self):
        state, kwargs = geology_fixture()
        result = bind_regional_geology(state, **kwargs)
        result.verify()
        self.assertEqual(result.descriptor()['initial_state_id'], state.initial_samples.state.state_id)
        self.assertEqual(result.descriptor()['material_state_id'], state.material.state_id)
        self.assertEqual(result.descriptor()['transform']['inward_depth_origin_m'], 1.)
        assert_array_equal(result.array('cohort_partial_thickness_m'), state.material.thickness_m)
        assert_array_equal(result.array('temperature_k'), np.full((4, 4), 300.))
        assert_array_equal(result.array('force_w_n_m3'), np.full((5, 4), -2.))
        self.assertEqual(float(result.array('phase_volume_m3').sum()), 2.)
        self.assertEqual(float(result.array('reference_mass_kg').sum()), 4.)
        self.assertEqual(result.surface_parameters()['density_kg_m3'], 2.)
        self.assertEqual(result.homogeneous_material['conductivity_w_m_k'], 3.)
        with self.assertRaises(ValueError):
            result.array('temperature_k')[0, 0] = 999.
        changed = result.array('temperature_k')
        changed.shape = (16,)
        self.assertEqual(result.array('temperature_k').shape, (4, 4))
        d = result.descriptor()
        d['ownership']['vertical_response_owner'] = 'W04'
        self.assertEqual(result.descriptor()['ownership']['vertical_response_owner'], 'W07')

    def test_source_labelled_raw_arrays_are_not_a_geological_producer(self):
        with self.assertRaisesRegex(TectonicsError, 'typed W01/W02'):
            RegionalGeologicalInputs({'source': 'geological-looking'}, {'temperature_k': np.ones((2, 2))})

    def test_unaligned_series_shear_support_and_reference_inventory(self):
        state, kwargs = geology_fixture(layered=True)
        result = bind_regional_geology(state, **kwargs)
        # Bottom low-viscosity layer ends at z=.37. At z=.25, the dual
        # interval [.125,.375] has .245 of eta=1 and .005 of eta=1000.
        expected = .25/(.245+.005/1000.)
        self.assertAlmostEqual(result.array('eta_vertex_pa_s')[1, 0], expected)
        assert_array_equal(result.array('eta_center_pa_s')[:, 0], [1., 1000., 1000., 1000.])
        self.assertAlmostEqual(result.array('density_w_kg_m3')[1, 0], (.245*2.+.005*3.)/.25)
        assert_allclose(result.array('phase_volume_m3').sum(axis=(1, 2)), [.74, 1.26], rtol=2e-15)
        assert_allclose(result.array('reference_mass_kg').sum(axis=(1, 2)), [1.48, 3.78], rtol=2e-15)
        self.assertIsNone(result.homogeneous_material)
        with self.assertRaises(TectonicsError):
            result.surface_parameters()

    def test_original_thermal_profile_buoyancy_is_not_reference_mass(self):
        state, kwargs = geology_fixture(thermal=True, density_law='boussinesq-linear-reference')
        result = bind_regional_geology(state, **kwargs)
        assert_array_equal(result.array('temperature_k')[:, 0], [475., 425., 375., 325.])
        assert_array_equal(result.array('temperature_vertex_k')[:, 0], [500., 450., 400., 350., 300.])
        assert_allclose(result.array('density_center_kg_m3')[:, 0], 2*(1-1e-4*np.array([175., 125., 75., 25.])))
        self.assertEqual(float(result.array('reference_mass_kg').sum()), 4.)
        self.assertEqual(result.descriptor()['thermal_profiles'][0]['depths_m'], [0., 1.])
        self.assertIn('not evolved heat', result.descriptor()['temperature_semantics'])
        with self.assertRaises(TectonicsError):
            result.surface_parameters()

    def test_actual_uniform_motion_is_retained_and_replacement_refuses_active_motion(self):
        state, kwargs = geology_fixture(speed=.25)
        result = bind_regional_geology(state, **kwargs)
        assert_array_equal(result.array('source_face_velocity_m_s'), np.full(5, .25))
        self.assertFalse(result.descriptor()['surface_eligible'])
        kwargs['ownership'] = replace(kwargs['ownership'], boundary_motion_owner='W07-boundary', boundary_source=SOURCE)
        with self.assertRaisesRegex(TectonicsError, 'active source S6 motion'):
            bind_regional_geology(state, **kwargs)

    def test_isothermal_surface_cannot_discard_known_heat_production(self):
        state, kwargs = geology_fixture(heat_production=2.)
        result = bind_regional_geology(state, **kwargs)
        self.assertEqual(result.homogeneous_material['heat_production_w_m3'], 2.)
        self.assertFalse(result.descriptor()['surface_eligible'])
        with self.assertRaisesRegex(TectonicsError, 'zero heat production'):
            result.surface_parameters()

    def test_ownership_refuses_duplicate_load_heat_water_and_compensation(self):
        original = RegionalPhysicsOwnership(SOURCE, SOURCE, SOURCE, SOURCE)
        for changes in ({'w04_state_id': 'existing-compensation'}, {'vertical_response_owner': 'W04'},
                        {'water_state_id': 'ocean'}, {'extra_gravity_sources': (SOURCE,)},
                        {'extra_thermal_sources': (SOURCE,)}, {'extra_displacement_sources': (SOURCE,)},
                        {'boundary_motion_owner': 'W07-boundary'}):
            with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                replace(original, **changes)

    def test_evolved_material_and_lateral_geometry_refuse(self):
        with PreparedRegionalWorkflow(*workflow_fixture(uniform=True), backend='reference') as plan:
            original = plan.initialise()
            evolved = plan.advance(original, left=STEADY_LEFT, right=RIGHT)
        kwargs = dict(nz=4, material_laws=(GeologicalMaterialLaw('rock', 1., SOURCE),
            GeologicalMaterialLaw('other-rock', 1000., SOURCE)),
            ownership=RegionalPhysicsOwnership(SOURCE, SOURCE, SOURCE, SOURCE),
            gravity_m_s2=1., vertical_datum='bottom')
        with self.assertRaisesRegex(TectonicsError, 'evolved W02'):
            bind_regional_geology(evolved, **kwargs)
        with PreparedRegionalWorkflow(*workflow_fixture(), backend='reference') as plan:
            lateral = plan.initialise()
        with self.assertRaisesRegex(TectonicsError, 'lateral|full planar'):
            bind_regional_geology(lateral, **kwargs)

    def test_source_identity_budget_cancellation_and_missing_law_refuse(self):
        state, kwargs = geology_fixture()
        with self.assertRaises(MemoryLimitError):
            bind_regional_geology(state, **kwargs, budget=WorkBudget(1024))
        cancellation = threading.Event()
        cancellation.set()
        with self.assertRaises(CancelledError):
            bind_regional_geology(state, **kwargs, cancel=cancellation)
        with self.assertRaisesRegex(TectonicsError, 'each represented'):
            bind_regional_geology(state, **dict(kwargs, material_laws=(GeologicalMaterialLaw('other-rock', 1., SOURCE),)))
        result = bind_regional_geology(state, **kwargs)
        with mock.patch('atlas_tectonics.regional_geology.ExecutionContext') as cls:
            cls.return_value.__enter__.return_value.identity = 'changed'
            with self.assertRaisesRegex(TectonicsError, 'source/runtime changed'):
                result.verify()


if __name__ == '__main__':
    unittest.main()
