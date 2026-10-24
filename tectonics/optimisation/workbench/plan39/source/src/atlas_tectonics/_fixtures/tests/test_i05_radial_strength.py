"""Source-bound full-3D constitutive controls, not calibrated lithosphere fits.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
import math
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

import i03_fixtures as F
from test_i04_regional_driving import mapping
from test_i05_heat import still
from atlas_tectonics import integration_radial_strength as R
from atlas_tectonics import integration_material as M, integration_sphere as S
from atlas_tectonics import integration_transfer as T, integration_volume as V
from atlas_tectonics import integration_regional_evolution as O
from atlas_tectonics import integration_regional_driving as D
from atlas_tectonics.integration_strength import CreepLaw
from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
from atlas_tectonics.regional_evolution3d import PreparedRegionalEvolution3D
from atlas_tectonics.constitutive import BoussinesqMaterial, DiffusiveScales
from atlas_tectonics.integration_regional_exchange import regional_exchange, LAYOUT_SCHEMA
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def material(*, plastic=.5, friction=.2):
    return R.RadialPlasticity3D(.1, friction, plastic, 1., (0., 1.), .5, .5,
        'synthetic SI input in the explicitly declared 3D convention; not converted 2D calibration')


def fixture(budget, *, temperature=500., kappa=.25, energy=0., plastic=.5, friction=.2):
    network = F.three_plates(sphere=F.sphere(radius=10.), time_s=0.)
    volume = float(V.RadialLayer(10., 0., 3., budget=budget).volume_per_area_m)
    stock = F.material(network, phases=('crust',), basis=None,
                       mass_per_area_kg_m2={'crust': volume}, thickness_m={'crust': volume})
    sphere = S.initial_sphere(network, stock)
    layer = M.Sublayer('rock', 'crust', 3., 1., 0., 1., 1., 0., temperature, temperature,
                       creep_law_id='creep', pore_pressure_pa=0.)
    records = tuple(M.CohortRecord(c.cohort_id, 'test:radial-strength-profile', 'test:constant profile',
        (layer,), temperature, temperature, None, (kappa,), M.BondRecord(c.cohort_id, False, 'UNKNOWN'),
        volume_convention=V.PHYSICAL_RADIAL_SHELL, reference_radius_m=10.) for c in stock.cohorts)
    moving = M.declare_moving(sphere, records, enthalpy_reference_k=400., budget=budget)
    pattern = {s: ('velocity',)*3 for s in SIDES}
    native = PreparedRegionalStokes3D((2, 2, 2), (1., 1., 1.), 1., pattern,
        scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=1.,
        frame_id='test:coupled-box', vertical_datum='actual embedded shell box',
        physical_mean_pressure_pa=5., material_source='test:explicit iteration seed',
        method='direct', budget=budget)
    footprint, args, frame = mapping(network, native)
    centres = np.stack(np.meshgrid((.25, .75), (.25, .75), (.25, .75), indexing='ij'), axis=-1).reshape(-1, 3)
    points = frame.positions_to_cartesian(centres+args['origin_local_m'], budget=budget)
    patches = sphere.material.support.patches
    sources = tuple((next(p.patch_id for p in patches if p.face_id in footprint.face_ids
                         and D._contains(p.cells, point)), 0) for point in points)
    volume_map = O.RegionalVolumeMap(sphere, moving, footprint, cells=(2, 2, 2), lengths_m=(1., 1., 1.),
        origin_local_m=args['origin_local_m'], cell_sources=sources, map_source='test:pure shell cells', budget=budget)
    laws = {'creep': CreepLaw((dict(a=.5, n=1., energy_j_mol=energy),), 'synthetic already-SI creep')}
    materials = {'rock': material(plastic=plastic, friction=friction)}
    source = R.radial_strength_source(moving, sphere, volume_map, materials=materials, creep_laws=laws,
                                     provenance='test:actual retained source fields', budget=budget)
    return sphere, moving, volume_map, native, source, materials, laws


class RadialStrengthTests(unittest.TestCase):
    def setUp(self):
        self.threads = threadpool_limits(limits=1); self.threads.__enter__()
        self.budget = WorkBudget(256*1024**2)

    def tearDown(self):
        self.threads.__exit__(None, None, None)

    def test_three_dimensional_oracle_work_partition_and_objectivity(self):
        sphere, moving, mapping_, native, source, materials, _ = fixture(self.budget, friction=.2)
        try:
            strain = np.zeros((8, 27, 3, 3)); strain[..., 0, 1] = strain[..., 1, 0] = .5
            reply = R.evaluate_radial_strength(source, strain, 5., budget=self.budget)
            m = materials['rock']; lc, lf = .875, .875
            y = 6*(m.cohesion_pa*lc*math.cos(m.friction_rad*lf)+5*math.sin(m.friction_rad*lf))/(
                math.sqrt(3)*(3+math.sin(m.friction_rad*lf)))
            # The fixture is subyield if this 3D pressure supplies enough confinement.
            s = 1. if 1. <= y else (.5+y)/1.5
            np.testing.assert_allclose(reply.array('stress_ii_pa'), s, rtol=2e-11, atol=0.)
            np.testing.assert_allclose(reply.array('yield_stress_pa'), y, rtol=2e-15, atol=0.)
            np.testing.assert_allclose(reply.array('creep_power_w_m3')+reply.array('plastic_power_w_m3'),
                reply.array('dissipation_w_m3'), rtol=4e-11, atol=0.)
            self.assertTrue(np.all(reply.array('plastic_kappa_rate_s_1') <= 1.+2e-11))
            fast = strain*4
            low_pressure = R.evaluate_radial_strength(source, fast, 2., budget=self.budget)
            high_pressure = R.evaluate_radial_strength(source, fast, 5., budget=self.budget)
            self.assertTrue(np.all(high_pressure.array('stress_ii_pa') > low_pressure.array('stress_ii_pa')))
            rotation = np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
            rotated = rotation@strain@rotation.T
            transformed = R.evaluate_radial_strength(source, rotated, 5., budget=self.budget)
            np.testing.assert_array_equal(transformed.array('viscosity_pa_s'), reply.array('viscosity_pa_s'))
            np.testing.assert_array_equal(transformed.array('deviatoric_stress_pa'),
                                          rotation@reply.array('deviatoric_stress_pa')@rotation.T)
            self.assertEqual(moving.moving_id, source.descriptor()['source']['moving_id'])
            with self.assertRaises((AttributeError, TypeError)):
                source._materials = ()
        finally:
            native.close()

    def test_same_q1_pressure_load_sign_full_and_incremental_reactions(self):
        budget = WorkBudget(256*1024**2)
        pattern = {s: ('velocity',)*3 for s in SIDES}
        nodes = np.indices((3, 3, 3)).reshape(3, -1).T/2
        pref = 5.+2*nodes[:, 2]
        def plan(reference=None, partition=None):
            return PreparedRegionalStokes3D((2, 2, 2), (1., 1., 1.), 1., pattern,
                scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=1., frame_id='reference-test',
                vertical_datum='explicit box', material_source='constant-viscosity-control',
                physical_mean_pressure_pa=6., method='direct', budget=budget,
                **({} if reference is None else dict(pressure_reference_pa=reference,
                    pressure_reference_source='explicit Q1 p=5+2z, including its normal reaction',
                    pressure_load_partition=partition)))
        request = dict(parent_state_id='source', epoch_id='epoch', time_s=0., force_source='explicit loads',
                       boundary_source='affine incompressible prescribed boundary')
        with threadpool_limits(limits=1), plan() as whole:
            xyz = whole.coordinates('velocity')
            velocity = np.stack((xyz[:, 0], np.zeros(len(xyz)), -xyz[:, 2]), axis=-1)
            body = np.zeros((8, 27, 3)); body[..., 2] = 2.
            direct = whole.solve(body, velocity, {s: 0. for s in SIDES}, **request)
        for partition in ('full', 'incremental'):
            with self.subTest(partition=partition), threadpool_limits(limits=1), plan(pref, partition) as split:
                result = split.solve(body if partition == 'full' else 0., velocity,
                                     {s: 0. for s in SIDES}, **request)
                np.testing.assert_allclose(result.array('velocity_m_s'), direct.array('velocity_m_s'),
                                           atol=2e-9, rtol=0.)
                np.testing.assert_allclose(result.array('physical_pressure_pa'), pref, rtol=2e-9, atol=0.)
                np.testing.assert_allclose(result.array('full_velocity_constraint_reaction_n'),
                    direct.array('velocity_constraint_reaction_n'), atol=2e-9, rtol=0.)
                reference_work = float(np.sum(velocity*result.array('reference_velocity_constraint_reaction_n')))
                # integral(-p n).u = -integral(grad(p).u) = +1 here;
                # the reference body work is -1. Their sum is zero.
                self.assertAlmostEqual(reference_work, 1., delta=5e-9)
                reference_id = split.descriptor()['pressure_reference']['reference_id']
                coupling = dict(boundary_modes_m=velocity[None], external_generalized_force_j=[1.],
                    external_resistance_j_s=[[1.]], coupling_source='exterior already owns reference',
                    pressure_reference_id=reference_id)
                driven = split.solve_force_coupled(body if partition == 'full' else 0., 0.,
                    {s: 0. for s in SIDES}, **coupling, **request)
                # Regional 4 + exterior 1; reference reaction +1 is NOT applied twice.
                np.testing.assert_allclose(driven.array('generalized_rates_s_inv'), [.2], rtol=5e-9, atol=0.)
                with self.assertRaisesRegex(TectonicsError, 'same incremental'):
                    split.solve_force_coupled(0., 0., {s: 0. for s in SIDES},
                        **dict(coupling, pressure_reference_id='wrong'), **request)
        # A constant Q1 reference has no body gradient and no work against an
        # incompressible affine mode, but its boundary normal reaction exists.
        with plan() as whole:
            constant_direct = whole.solve(0., velocity, {s: 0. for s in SIDES}, **request)
        with plan(np.full(27, 6.), 'full') as split:
            constant = split.solve(0., velocity, {s: 0. for s in SIDES}, **request)
            np.testing.assert_allclose(constant.array('physical_pressure_pa'), 6., rtol=2e-9, atol=0.)
            np.testing.assert_allclose(constant.array('full_velocity_constraint_reaction_n'),
                constant_direct.array('velocity_constraint_reaction_n'), atol=2e-9, rtol=0.)
            self.assertAlmostEqual(float(np.sum(velocity*constant.array('reference_velocity_constraint_reaction_n'))),
                                   0., delta=5e-9)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_current_patch_heat_and_plastic_history_change_actual_response(self):
        sphere, moving, map_, native, source, mats, laws = fixture(self.budget, energy=1000., friction=.2)
        try:
            strain = np.zeros((8, 27, 3, 3)); strain[..., 0, 1] = strain[..., 1, 0] = 2.
            cold = R.evaluate_radial_strength(source, strain, 2., budget=self.budget)
            step = T.advance(sphere, still(sphere.network), end_time_s=1.)
            selected = tuple(sorted({row['patch_id'] for row in map_.record()['cell_sources']}))
            heated = M.advance_moving(moving, sphere, step, M.MovingAdvance(0, 1,
                mechanical_patch_energy_j=tuple((p, (2.,)) for p in selected)), budget=self.budget).state
            new_map = O.RegionalVolumeMap.restore(dict(map_.record()), sphere, moving, budget=self.budget)
            # Restoring the old source exactly is legal; using it with new heat is not.
            with self.assertRaisesRegex(R.RadialStrengthRefused, 'stale'):
                R.radial_strength_source(heated, step.state, new_map, materials=mats, creep_laws=laws,
                                         provenance='test:stale source', budget=self.budget)
            request = map_.record()['request']
            from atlas_tectonics.integration_bridges import Footprint
            next_map = O.RegionalVolumeMap(step.state, heated, Footprint(**request['footprint']),
                cells=tuple(request['cells']), lengths_m=tuple(request['lengths_m']),
                origin_local_m=tuple(request['origin_local_m']),
                cell_sources=tuple(tuple(r) for r in request['cell_sources']), map_source=request['map_source'],
                budget=self.budget)
            hot = R.radial_strength_source(heated, step.state, next_map, materials=mats, creep_laws=laws,
                                          provenance='test:current heated fields', budget=self.budget)
            hotter = R.evaluate_radial_strength(hot, strain, 2., budget=self.budget)
            self.assertTrue(np.all(hot.array('temperature_k') > source.array('temperature_k')))
            self.assertTrue(np.all(hotter.array('stress_ii_pa') < cold.array('stress_ii_pa')))
            # A separately authored inherited-history state has actual weaker material.
            records = tuple(replace(c, kappa=(.75,)) for c in moving.cohorts)
            weak = M.declare_moving(sphere, records, enthalpy_reference_k=400., budget=self.budget)
            weak_map = O.RegionalVolumeMap(sphere, weak, Footprint(**request['footprint']),
                cells=tuple(request['cells']), lengths_m=tuple(request['lengths_m']),
                origin_local_m=tuple(request['origin_local_m']),
                cell_sources=tuple(tuple(r) for r in request['cell_sources']), map_source=request['map_source'],
                budget=self.budget)
            weakened = R.radial_strength_source(weak, sphere, weak_map, materials=mats, creep_laws=laws,
                                               provenance='test:inherited history', budget=self.budget)
            soft = R.evaluate_radial_strength(weakened, strain, 2., budget=self.budget)
            self.assertTrue(np.all(soft.array('stress_ii_pa') < cold.array('stress_ii_pa')))
        finally:
            native.close()

    def test_actual_full_stress_pressure_and_no_added_hydrostatic_load(self):
        sphere, moving, map_, native, source, _, _ = fixture(self.budget, friction=0.)
        try:
            coordinates = native.coordinates('velocity')
            velocity = np.zeros_like(coordinates); velocity[:, 0] = coordinates[:, 1]
            kwargs = dict(parent_state_id=sphere.state_id, epoch_id=sphere.network.epoch_id,
                time_s=0., force_source='explicit zero body force', boundary_source='affine shear velocity')
            result = R.solve_radial_strength(native, source, 0., velocity, {s: 0. for s in SIDES}, **kwargs)
            expected_y = 6*.1*.875/(math.sqrt(3)*3)
            expected_s = (.5+expected_y)/1.5
            np.testing.assert_allclose(result.constitutive.array('stress_ii_pa'), expected_s, rtol=1e-8, atol=0.)
            np.testing.assert_allclose(result.constitutive.array('physical_mean_pressure_pa'), 5., rtol=1e-10, atol=0.)
            self.assertEqual(result.mechanics.descriptor()['power_w']['body_work'], 0.)
            self.assertLessEqual(result.constitutive_log_residual, R.LOG_TOL)
            self.assertEqual(result.constitutive.descriptor()['mechanical_result_id'], result.mechanics.result_id)
            self.assertEqual(moving.moving_id, source.descriptor()['source']['moving_id'])
            with self.assertRaises(MemoryLimitError):
                R.evaluate_radial_strength(source, np.zeros((8, 27, 3, 3)), 5., budget=WorkBudget(1024))
        finally:
            native.close()

    def test_actual_evolution_sources_plastic_heat_once_and_restarts_current_fields(self):
        sphere, moving, map_, seed, source, _, _ = fixture(self.budget, energy=1000., friction=0.)
        seed.close()
        rows = map_.record()['cell_sources']
        keys = sorted({(r['patch_id'], r['sublayer']) for r in rows})
        fractions = np.zeros((len(keys), 2, 2, 2))
        for i, row in enumerate(rows):
            fractions[(keys.index((row['patch_id'], row['sublayer'])), *np.unravel_index(i, (2, 2, 2)))] = 1.
        def prepare():
            return PreparedRegionalEvolution3D((2, 2, 2), (1., 1., 1.),
                BoussinesqMaterial('synthetic', 'same source material', 1., 1., 1., 0., 500., 0., 0., (400., 600.)),
                None, DiffusiveScales('synthetic', 1., 1., 1., 400., 200., 1.), RegionalMechanicsScales(1., 1.),
                {s: ('velocity',)*3 for s in SIDES}, composition_values=(0.,)*len(keys),
                frame_id='test:coupled-box', vertical_datum='actual embedded shell box',
                include_viscous_heating=True, divergence_rtol=1e-10, max_velocity_correction_m_s=1e-8,
                max_relative_correction=1e-6, mechanics_method='direct', budget=self.budget,
                radial_constitutive=source, physical_mean_pressure_pa=5.)
        xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
        velocity = np.zeros_like(xyz); velocity[:, 0] = xyz[:, 1]
        strain = np.zeros((8, 27, 3, 3)); strain[..., 0, 1] = strain[..., 1, 0] = .5
        def advance(plan, state):
            current = R.refresh_radial_strength(source, state, plan, budget=self.budget)
            analytic = R.evaluate_radial_strength(current, strain, 5., budget=self.budget)
            # Explicit synthetic inlet reservoirs match the donor's uniform
            # source endpoint. This isolates the exact affine law; it is not a
            # claim that an unheated planetary halo has this temperature/history.
            dt = .01
            temperature = float(current.array('temperature_k')[0, 0])+dt*float(analytic.array('dissipation_w_m3')[0, 0])
            total_kappa = float(current.array('plastic_kappa')[0, 0])+dt*float(analytic.array('plastic_kappa_rate_s_1')[0, 0])
            original = .25
            stocks = {s: plan.boundary_stock(s, 10., (10./len(keys),)*len(keys), 10.*temperature,
                {'damage': 0., 'accumulated_strain_ii': 0., 'source_kappa': 10.*original,
                 'radial_plastic_kappa': 10.*(total_kappa-original)}) for s in SIDES}
            return plan.advance(state, dt, velocity_m_s=velocity, dynamic_traction_pa={s: 0. for s in SIDES},
                gravity_m_s2=(0., 0., 0.), additional_body_force_n_m3=0., driving_source='uniform affine shear',
                heat_boundaries={s: ('flux', 0.) for s in SIDES}, heat_source_w_m3=0.,
                heat_source='mechanical heat only', boundary_stocks=stocks)
        with prepare() as plan:
            parent = plan.initial_state(500., fractions, 0., time_s=0., state_source='actual shell admission')
            first = advance(plan, parent)
            mass = np.sum(first.state.array('component_mass_kg'), axis=0)
            self.assertTrue(np.all(first.state.array('enthalpy_j')/mass > 500.))
            self.assertTrue(np.all(first.state.array('tracer:radial_plastic_kappa') > 0.))
            current = R.refresh_radial_strength(source, first.state, plan, budget=self.budget)
            self.assertTrue(np.all(current.array('temperature_k') > source.array('temperature_k')))
            self.assertTrue(np.all(current.array('plastic_kappa') > source.array('plastic_kappa')))
            audit = first.source_audit
            np.testing.assert_allclose(audit.array('creep_dissipation_w_m3')+
                audit.array('plastic_dissipation_w_m3'), audit.array('viscous_dissipation_w_m3'), rtol=4e-11, atol=0.)
            np.testing.assert_array_equal(audit.array('external_heat_source_w_m3'), np.zeros((2, 2, 2)))
            layout = dict(schema=LAYOUT_SCHEMA, region_id='test:coupled-box', cells=[2, 2, 2], lengths_m=[1., 1., 1.],
                plate_ids=['B', 'C'], components=[dict(patch_id=p, sublayer=j,
                    plate_id=next(r['plate_id'] for r in rows if r['patch_id'] == p)) for p, j in keys],
                native_plan_id=plan.plan_id, transfer_id=map_.volume_map_id)
            exchange = regional_exchange(first, layout=layout, parent_state=parent, budget=self.budget)
            self.assertTrue(np.all(exchange.array('plastic_kappa_increment') > 0.))
            continued = advance(plan, first.state)
            record = first.state.descriptor()
            arrays = {k: first.state.array(k) for k in first.state.array_names}
            original_plan = plan.plan_id
        with prepare() as fresh:
            self.assertEqual(fresh.plan_id, original_plan)
            restored = RegionalMechanicalSnapshot(record, arrays)
            replay = advance(fresh, restored)
            for name in ('state', 'initial_mechanics', 'mechanics', 'transport', 'heat', 'source_audit'):
                self.assertEqual(getattr(continued, name).result_id, getattr(replay, name).result_id, name)
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_automatic_full_gravity_and_nonmatching_reference_gradient(self):
        _, _, _, seed, source, _, _ = fixture(self.budget, friction=0.)
        seed.close()
        nodes = np.indices((3, 3, 3)).reshape(3, -1).T/2
        args = dict(composition_values=(0.,), frame_id='test:coupled-box',
            vertical_datum='actual embedded shell box', include_viscous_heating=True,
            divergence_rtol=1e-10, max_velocity_correction_m_s=1e-8, max_relative_correction=1e-6,
            mechanics_method='direct', budget=self.budget, radial_constitutive=source,
            physical_mean_pressure_pa=6., pressure_reference_pa=5.+2*nodes[:, 2],
            pressure_reference_source='explicit Q1 gradient 2, distinct from physical rho*g=1')
        def prepare(partition, scales=None):
            return PreparedRegionalEvolution3D((2, 2, 2), (1., 1., 1.),
                BoussinesqMaterial('test', 'actual source', 1., 1., 1., 0., 500., 0., 0., (400., 600.)),
                None, scales or DiffusiveScales('test', 1., 1., 1., 400., 200., 1.), RegionalMechanicsScales(1., 1.),
                {s: ('velocity',)*3 for s in SIDES}, pressure_load_partition=partition, **args)
        with self.assertRaisesRegex(TectonicsError, 'full physical loads'):
            prepare('incremental')
        with prepare('full') as native:
            state = native.initial_state(500., np.ones((1, 2, 2, 2)), 0., time_s=0., state_source='actual source')
            xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
            velocity = np.zeros_like(xyz); velocity[:, 0] = xyz[:, 1]
            solved, _, _, _ = native._mechanics(state, velocity,
                {s: np.zeros((4, 9, 3)) for s in SIDES}, np.array([0., 0., 1.]),
                np.zeros((8, 27, 3)), 'full actual gravity, not reference gradient', None, None)
            np.testing.assert_allclose(solved.array('physical_pressure_pa'), 5.5+nodes[:, 2], rtol=1e-9, atol=0.)
        # Unlike the old dimensionless benchmark profiles, this source law is
        # dimensioned in actual Kelvin/metres. Its response cannot change when
        # unused depth/temperature presentation scales put those values >1.
        with prepare('full', DiffusiveScales('different presentation', 1., 1., 1., 100., 10., .1)) as scaled:
            state = scaled.initial_state(500., np.ones((1, 2, 2, 2)), 0., time_s=0., state_source='actual source')
            self.assertGreater(float(np.max(scaled._depth)), 1.)
            self.assertIn('actual radius-bound', scaled.descriptor()['depth'])
            again, _, _, _ = scaled._mechanics(state, velocity,
                {s: np.zeros((4, 9, 3)) for s in SIDES}, np.array([0., 0., 1.]),
                np.zeros((8, 27, 3)), 'full actual gravity, not reference gradient', None, None)
            for key in ('velocity_m_s', 'physical_pressure_pa', 'extra_plus_viscous_stress_pa'):
                np.testing.assert_array_equal(again.array(key), solved.array(key))
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_changed_viscosity_preserves_actual_plate_driver_reconstruction(self):
        from atlas_tectonics import integration_driving as driving
        import i04_fixtures as X
        sphere, moving, map_, seed, source, _, _ = fixture(self.budget, energy=1000., plastic=None)
        seed.close()
        with PreparedRegionalStokes3D((2, 2, 2), (1., 1., 1.), 1.,
                {s: ('velocity',)*3 if s[0] == 'x' else ('traction',)*3 for s in SIDES},
                scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=1.,
                frame_id='test:coupled-box', vertical_datum='actual embedded shell box',
                material_source='test:fixed actual radial owner', method='direct', budget=self.budget,
                pressure_reference_pa=np.full(27, 5.), pressure_reference_source='explicit discrete reference',
                pressure_load_partition='incremental') as native:
            footprint, args, _ = mapping(sphere.network, native)
            force = X.authored_forcing(sphere.network,
                {'A': (1., -.4, .2), 'B': (.8, 1.1, .5), 'C': (-.3, -.6, -.2)}, drag=.001)
            exterior_plan = driving.prepare(sphere.network, force)
            exterior = driving.balance(sphere.network, force, prepared=exterior_plan,
                parent_state_id=sphere.state_id, interval=(0, 1, 0., 1.))
            with D.PlateBoundaryLift(sphere.network, native, footprint, 'boundary-m00',
                    **args, volume_map=map_, budget=self.budget) as lift, \
                    D.PreparedRegionalDriving(sphere.network, force, exterior, exterior_plan,
                                              lift, budget=self.budget) as driver:
                solved = R.solve_radial_strength(native, source, 0., 0., {s: 0. for s in SIDES},
                    parent_state_id=sphere.state_id, epoch_id=sphere.network.epoch_id, time_s=0.,
                    force_source='explicit incremental loads', boundary_source='actual plate walls',
                    coupling=driver.coupling())
                self.assertGreater(solved.iterations, 1)
                self.assertEqual(solved.mechanics.descriptor()['plan']['material_source'],
                                 native.descriptor()['material_source'])
                joined = driver.reconstruct(solved.mechanics, parent_state_id=sphere.state_id, time_s=0.)
                self.assertEqual(joined.mechanical.result_id, solved.mechanics.result_id)
        self.assertEqual(self.budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
