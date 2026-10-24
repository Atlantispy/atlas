"""Actual source admission and independently retained regional continuation.

Predeclared in I04_I05_PORTS.md section 7. Synthetic material, not geology.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

import i03_fixtures as F
import i02_workflow_fixtures as F2
import test_i03_bridges as BF
from atlas_tectonics import integration_sphere as S, integration_material as M
from atlas_tectonics import integration_bridges as B, integration_regional_evolution as O
from atlas_tectonics import integration_volume as V
from atlas_tectonics.integration_regional_workflow import RegionalWorkflow
from atlas_tectonics.constitutive import BoussinesqMaterial, DiffusiveScales, RheologyProfile
from atlas_tectonics.integration_strength import CreepLaw
from atlas_tectonics.regional_evolution3d import PreparedRegionalEvolution3D
from atlas_tectonics.regional_execution import RegionalMechanicsScales, RegionalMechanicalSnapshot
from atlas_tectonics.regional_execution3d import SIDES
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


def source(*, density=1., kappa=0., legacy_copied_stock=False):
    # The two source sectors are reflected across longitude zero. Their own
    # coordinate/area calculations are symmetric; no stock is copied to make a
    # uniform native grid fit unrelated rounded areas.
    geometry = {} if legacy_copied_stock else dict(longitudes_deg=(-240., -180., -120., -60., 0., 60.))
    network = F.three_plates(sphere=F.sphere(radius=1.), time_s=0., **geometry)
    material = F.material(network, phases=('crust',), basis=None,
                          mass_per_area_kg_m2={'crust': density}, thickness_m={'crust': 1.})
    faces = tuple(BF.control('bridge_redistribution')['footprint_faces'])
    volume = next(p.volume_m3[0] for p in material.pieces() if p.face_id == faces[0])
    if legacy_copied_stock:
        # Retained negative control: the old rotated fixture copied one face's
        # stock onto a second face with a seven-ulp different area. Its declared
        # uniform physical h=1 no longer passes the original mass guard there.
        pieces = tuple(replace(p, mass_kg=(density*volume,), volume_m3=(volume,)) if p.face_id in faces else p
                       for p in material.pieces())
        material = S.build_material(network, phases=material.phases, cohorts=material.cohorts, pieces=pieces)
    elif any(p.volume_m3 != (volume,) for p in material.pieces() if p.face_id in faces):
        raise AssertionError('reflected source faces must have exactly equal independently measured volumes')
    sphere = S.initial_sphere(network, material)
    records = []
    for cohort in material.cohorts:
        temperature = 1.25 if cohort.cohort_id == 'inherited-A' else 1.75
        layer = M.Sublayer('synthetic', 'crust', 1., density, 0., .1, 1., 0., temperature,
                           temperature, 'test:constant-creep', 0.)
        records.append(M.CohortRecord(cohort.cohort_id, 'test:profile', 'test:thermal', (layer,),
            1., None, None, (kappa,), M.BondRecord(cohort.cohort_id, False, 'UNKNOWN')))
    moving = M.declare_moving(sphere, tuple(records), enthalpy_reference_k=1.)
    footprint_rule = dict(BF.control('bridge_redistribution'))
    if not legacy_copied_stock:
        footprint_rule['centre_lon_lat_deg'] = (0., -15.)
    footprint = replace(BF.footprint(footprint_rule, representation='map', tolerance=.9,
                                    region='test:regional-owner'), depth_top_m=0., depth_bottom_m=1.)
    patches = {p.face_id: p for p in sphere.material.support.patches}
    allocations = tuple(O.CellAllocation(patches[faces[x]].patch_id, 0, Fraction(1, 4))
                        for x in range(2) for _ in range(4))
    return sphere, moving, footprint, allocations, (2*volume, 1., 1.)


def prepare(lengths, budget, material=None, *, cells=(2, 2, 2), **changes):
    material = material or BoussinesqMaterial('test:constant', 'synthetic-control',
        1., 1., .1, 0., 1., 0., 0., (1., 2.))
    return PreparedRegionalEvolution3D(cells, lengths, material,
        None if changes.get('i01_creep_law') is not None else RheologyProfile('test:constant', 'constant', 'analytic', (('eta', 1.),)),
        DiffusiveScales('test:scales', 1., 1., 1., 1., 1., 1.), RegionalMechanicsScales(1., 1.),
        {s: ('velocity',)*3 for s in SIDES}, composition_values=(0., 1.), frame_id='test:regional-owner',
        vertical_datum='box-top-is-depth-zero', include_viscous_heating=True,
        divergence_rtol=1e-10, max_velocity_correction_m_s=1e-8, max_relative_correction=1e-6,
        budget=budget, mechanics_method='direct', **changes)


def owner(native, fixture, budget, **changes):
    sphere, moving, footprint, allocations, _ = fixture
    law = CreepLaw((dict(a=.5, n=1., energy_j_mol=0., volume_m3_mol=0., grain_exponent=0.),), 'analytic-SI')
    values = dict(plate_ids=('A', 'B'), creep_match=dict(creep_law_id='test:constant-creep', law=law.record()),
                  map_source='test:declared-pure-cell-conservative-volume-map', budget=budget)
    values.update(changes)
    return O.PreparedRegionalOwner(native, sphere, moving, footprint, allocations, **values)


def driving(native):
    ijk = np.indices(native.cells).reshape(3, -1).T
    qijk = np.indices((3, 3, 3)).reshape(3, -1).T
    g, _ = np.polynomial.legendre.leggauss(3)
    points = (ijk[:, None, :]+(g[qijk][None, :, :]+1)/2)*(np.asarray(native.lengths_m)/native.cells)
    length = native.lengths_m[0]
    amplitude = .05
    # Exact Q2 incompressible circulation from psi=a*x(L-x)*z(1-z).
    # No normal wall flow; f=-eta*Laplacian(u), with eta=1 and p=0.
    force = np.zeros_like(points)
    force[..., 0] = 2*amplitude*(1-2*points[..., 2])
    force[..., 2] = -2*amplitude*(length-2*points[..., 0])
    nodes = np.stack(np.meshgrid(*(np.linspace(0, v, 2*n+1) for v, n in
        zip(native.lengths_m, native.cells)), indexing='ij'), axis=-1).reshape(-1, 3)
    velocity = np.zeros_like(nodes)
    velocity[:, 0] = amplitude*nodes[:, 0]*(length-nodes[:, 0])*(1-2*nodes[:, 2])
    velocity[:, 2] = -amplitude*(length-2*nodes[:, 0])*nodes[:, 2]*(1-nodes[:, 2])
    return dict(velocity_m_s=velocity, dynamic_traction_pa={s: 0. for s in SIDES}, gravity_m_s2=(0., 0., 0.),
        additional_body_force_n_m3=force, driving_source='test:closed-recirculation',
        heat_boundaries={s: ('flux', 0.) for s in SIDES}, heat_source_w_m3=0., heat_source='test:no-extra-heat')


def physical_source(budget):
    """Fresh shell source, not conversion of an old prism or saved history."""
    network = F.three_plates(sphere=F.sphere(radius=10.), time_s=0.,
        longitudes_deg=(-240., -180., -120., -60., 0., 60.))
    shell = V.RadialLayer(10., 0., 3., budget=budget)
    factor = shell.volume_per_area_m
    density = 1.1
    material = F.material(network, phases=('crust',), basis=None,
        mass_per_area_kg_m2={'crust': float(Fraction(density)*factor)},
        thickness_m={'crust': float(factor)})
    sphere = S.initial_sphere(network, material)
    records = []
    for cohort in material.cohorts:
        temperature = 1.25 if cohort.cohort_id == 'inherited-A' else 1.75
        layer = M.Sublayer('synthetic', 'crust', 3., density, 0., .1, 1., 0., temperature,
                           temperature, 'test:constant-creep', 0.)
        records.append(M.CohortRecord(cohort.cohort_id, 'test:physical-profile', 'test:thermal', (layer,),
            1., None, None, (.3,), M.BondRecord(cohort.cohort_id, False, 'UNKNOWN'),
            volume_convention=V.PHYSICAL_RADIAL_SHELL, reference_radius_m=10., radial_depths_m=(0., 3.)))
    moving = M.declare_moving(sphere, tuple(records), enthalpy_reference_k=1., budget=budget)
    faces = ('s03-b02', 's04-b02')
    footprint = B.Footprint('test:regional-owner', faces, 0., 0., 0., 0., 3., '3d')
    patches = {p.face_id: p for p in sphere.material.support.patches}
    sources = tuple((patches[faces[x]].patch_id, 0) for x in range(2) for _ in range(4))
    return sphere, moving, footprint, sources, (1., 1., 1.), (-.5, .25, -2.)


def physical_map(fixture, budget, **changes):
    sphere, moving, footprint, sources, lengths, origin = fixture
    values = dict(cells=(2, 2, 2), lengths_m=lengths, origin_local_m=origin,
                  cell_sources=sources, map_source='test:contained-radial-box', budget=budget)
    values.update(changes)
    return O.RegionalVolumeMap(sphere, moving, footprint, **values)


def physical_owner(native, fixture, volume_map, budget):
    return owner(native, (*fixture[:3], None, fixture[4]), budget,
                 volume_map=volume_map, map_source='test:contained-radial-box')


class RegionalOwnerTests(unittest.TestCase):
    def test_physical_containment_ideal_debits_remainder_projection_and_refusals(self):
        budget = WorkBudget(256*1024**2)
        fixture = physical_source(budget)
        sphere, moving = fixture[:2]
        volume_map = physical_map(fixture, budget)
        self.assertEqual(O.RegionalVolumeMap.restore(volume_map.record(), sphere, moving,
                                                    budget=budget).volume_map_id, volume_map.volume_map_id)
        material = BoussinesqMaterial('test:physical-density', 'synthetic-control',
            1.1, 1., .1, 0., 1., 0., 0., (1., 2.))
        with prepare(fixture[4], budget, material) as native, physical_owner(native, fixture, volume_map, budget) as plan:
            self.assertIsNotNone(plan.physical_geometry_binding())
            self.assertEqual(plan.physical_geometry_binding()['volume_map_id'], volume_map.volume_map_id)
            self.assertEqual(plan.physical_geometry_binding()['native_plan_id'], native.plan_id)
            definition = plan.descriptor()
            for account, remainder, projection in zip(definition['admission_accounts'],
                                                       plan.physical_remainder(), plan.admission_projection()):
                for name, source_value in account['source'].items():
                    exact = lambda q: Fraction(*map(int, q))
                    self.assertEqual(exact(source_value), exact(account['native_projection'][name])+
                        exact(remainder['stocks'][name])+exact(projection[name]))
                    self.assertEqual(exact(account['ideal_debit'][name]),
                                     exact(account['native_projection'][name])+exact(projection[name]))
                self.assertGreater(Fraction(*map(int, remainder['stocks']['volume_m3'])), 0)
                self.assertEqual(Fraction(*map(int, account['ideal_debit']['volume_m3'])), Fraction(1, 2))
            state = plan.initial_state
            restored = plan.restore(state.descriptor(), state.arrays(), sphere=sphere, moving=moving)
            self.assertEqual(restored.owner_state_id, state.owner_state_id)
            altered = json.loads(json.dumps(state.descriptor()))
            altered['metadata']['physical_remainder'][0]['stocks']['mass_kg'][0] = '0'
            with self.assertRaises(O.RegionalOwnerRefused):
                plan.restore(altered, state.arrays(), sphere=sphere, moving=moving)
        bad = json.loads(json.dumps(volume_map.record()))
        bad['request']['origin_local_m'][0] += 1.
        with self.assertRaises(O.RegionalOwnerRefused):
            O.RegionalVolumeMap.restore(bad, sphere, moving, budget=budget)
        with self.assertRaises(O.RegionalOwnerRefused):
            physical_map(fixture, budget, origin_local_m=(-.5, .25, -.25))
        with self.assertRaises(MemoryLimitError):
            physical_map(fixture, WorkBudget(1024))
        prism = source()
        prism_footprint = replace(prism[2], centre_lat_rad=0., representation='3d', max_relative_distortion=None)
        with self.assertRaisesRegex(O.RegionalOwnerRefused, 'radial-shell'):
            O.RegionalVolumeMap(prism[0], prism[1], prism_footprint, cells=(2, 2, 2), lengths_m=(1., 1., 1.),
                origin_local_m=(-.5, .25, -2.), cell_sources=tuple((a.patch_id, a.sublayer) for a in prism[3]),
                map_source='test:no-history-conversion', budget=budget)

    def test_physical_shell_to_native_heat_and_actual_store_restart(self):
        budget = WorkBudget(256*1024**2)
        fixture = physical_source(budget); sphere, moving = fixture[:2]
        volume_map = physical_map(fixture, budget)
        material = BoussinesqMaterial('test:physical-density', 'synthetic-control',
            1.1, 1., .1, 0., 1., 0., 0., (1., 2.))
        source_ids = sphere.state_id, moving.moving_id
        with tempfile.TemporaryDirectory() as folder, threadpool_limits(1):
            path = Path(folder)/'physical-region.sqlite'
            with F2.store(path) as store, prepare(fixture[4], budget, material) as native, \
                    physical_owner(native, fixture, volume_map, budget) as plan, \
                    RegionalWorkflow.create(store, plan, sphere=sphere, moving=moving, budget=budget) as flow:
                identity = flow.workflow_id
                first = flow.advance(.01, **driving(native))
                self.assertGreater(np.sum(first.exchange.array('audit:viscous_heat_source_w_m3')), 0.)
                self.assertEqual(volume_map.native_binding(native._mechanical), plan.physical_geometry_binding())
                self.assertEqual(first.state.descriptor()['metadata']['physical_remainder'], plan.physical_remainder())
                expected = plan.advance(first.state, .01, sphere=sphere, moving=moving, **driving(native))
                self.assertFalse(np.array_equal(first.state.native_state.array('component_mass_kg'),
                                                plan.initial_state.native_state.array('component_mass_kg')))
            with F2.store(path) as store, prepare(fixture[4], budget, material) as native, \
                    RegionalWorkflow.open(store, identity, native, budget=budget) as reopened:
                self.assertEqual(reopened.state.owner_state_id, first.state.owner_state_id)
                continued = reopened.advance(.01, **driving(native))
                self.assertEqual(continued.state.owner_state_id, expected.state.owner_state_id)
                self.assertEqual(continued.exchange.result_id, expected.exchange.result_id)
            self.assertEqual(source_ids, (sphere.state_id, moving.moving_id))

    def test_rounded_source_physical_fields_exact_projection_and_restore(self):
        fixture = source(density=1.1, kappa=.3)
        sphere, moving, footprint, allocations, lengths = fixture
        # Six cells per source make the native projection non-dyadic in addition
        # to the ordinary binary64 rho*V declaration. No stock is perturbed.
        selected = (allocations[0].patch_id, allocations[-1].patch_id)
        allocations = tuple(O.CellAllocation(p, 0, Fraction(1, 6)) for p in selected for _ in range(6))
        fixture = sphere, moving, footprint, allocations, lengths
        material = BoussinesqMaterial('test:rounded-density', 'synthetic-control',
            1.1, 1., .1, 0., 1., 0., 0., (1., 2.))
        stocks = {p.patch_id: p.stock for p in sphere.material.support.patches}
        self.assertTrue(any(stocks[p][1] != Fraction(1.1)*stocks[p][2] for p in selected))
        budget = WorkBudget(256*1024**2)
        with prepare(lengths, budget, material, cells=(2, 3, 2)) as native:
            with owner(native, fixture, budget) as plan:
                self.assertEqual(plan.descriptor()['inventory_guard'],
                    dict(method='I05 original piece reference-mass guard', intervals_since_declaration=0))
                state = plan.initial_state
                masses = state.native_state.array('component_mass_kg')
                heat = state.native_state.array('enthalpy_j')
                kappa = state.native_state.array('tracer:source_kappa')
                accounts, residuals = plan.descriptor()['admission_accounts'], plan.admission_projection()
                self.assertTrue(any(Fraction(*map(int, r['mass_kg'])) != 0 for r in residuals))
                for i, (account, residual) in enumerate(zip(accounts, residuals)):
                    mask = masses[i] > 0
                    native_totals = (Fraction(native._volume)*int(np.sum(mask)),
                        sum(map(Fraction, masses[i][mask]), Fraction(0)),
                        sum(map(Fraction, heat[mask]), Fraction(0)),
                        sum(map(Fraction, kappa[mask]), Fraction(0)))
                    names = ('volume_m3', 'mass_kg', 'absolute_heat_j', 'source_kappa_mass_kg')
                    for name, held in zip(names, native_totals):
                        original = Fraction(*map(int, account['exact_'+name]))
                        self.assertEqual(held+Fraction(*map(int, residual[name])), original)
                    np.testing.assert_array_equal(heat[mask],
                        np.full(int(np.sum(mask)), account['physical_temperature_k'])*
                        (native._mass*material.heat_capacity_j_kg_k))
                record, arrays = state.descriptor(), state.arrays()
                self.assertEqual(record['metadata']['source_minus_native_projection'], residuals)
            with owner(native, fixture, budget) as reopened:
                restored = reopened.restore(record, arrays, sphere=sphere, moving=moving)
                self.assertEqual(restored.owner_state_id, state.owner_state_id)
                altered = json.loads(json.dumps(record))
                altered['metadata']['source_minus_native_projection'][0]['mass_kg'][0] = '0'
                with self.assertRaises(O.RegionalOwnerRefused):
                    reopened.restore(altered, arrays, sphere=sphere, moving=moving)

    def test_original_mass_guard_and_missing_physical_field_still_refuse(self):
        with self.assertRaisesRegex(M.TransportRefused, 'reference density contradicts'):
            source(legacy_copied_stock=True)
        fixture = source(density=1.1)
        sphere, moving = fixture[:2]
        piece = sphere.material.pieces()[0]
        bad_piece = replace(piece, mass_kg=(piece.mass_kg[0]*(1+1e-8),))
        bad_material = S.build_material(sphere.network, phases=sphere.material.phases,
            cohorts=sphere.material.cohorts,
            pieces=tuple(bad_piece if p == piece else p for p in sphere.material.pieces()))
        bad_sphere = S.initial_sphere(sphere.network, bad_material)
        with self.assertRaisesRegex(M.TransportRefused, 'reference density contradicts'):
            M.declare_moving(bad_sphere, moving.cohorts, enthalpy_reference_k=moving.enthalpy_reference_k)
        # Historical positioned heat is readable by its own route, but has no
        # retained physical field and cannot be silently migrated by this owner.
        historical = M._issued(sphere, moving.cohorts,
            [moving.heat_j(i).tolist() for i in range(len(moving.pieces))], moving._initial,
            moving._supplied, moving._rounding, moving._allowance, moving.enthalpy_reference_k,
            declared_step=moving.declared_step, patch_heat=dict(moving._patch_heat))
        material = BoussinesqMaterial('test:rounded-density', 'synthetic-control',
            1.1, 1., .1, 0., 1., 0., 0., (1., 2.))
        budget = WorkBudget(256*1024**2)
        with prepare(fixture[-1], budget, material) as native:
            with self.assertRaisesRegex(O.RegionalOwnerRefused, 'retained physical patch columns'):
                owner(native, (sphere, historical, *fixture[2:]), budget)

    def test_actual_i01_thermal_law_binding_and_endpoint_response(self):
        fixture = source(); sphere, moving = fixture[:2]
        budget = WorkBudget(256*1024**2)
        law = CreepLaw((dict(a=.5, n=1., energy_j_mol=8., volume_m3_mol=0., grain_exponent=0.),), 'synthetic-SI-Arrhenius')
        match = dict(creep_law_id='test:constant-creep', law=law.record())
        with threadpool_limits(1), prepare(fixture[-1], budget, i01_creep_law=law) as native:
            with self.assertRaises(O.RegionalOwnerRefused):
                owner(native, fixture, budget)
            with owner(native, fixture, budget, creep_match=match) as plan:
                values = driving(native)
                values.update(velocity_m_s=0., additional_body_force_n_m3=0., heat_source_w_m3=.1)
                step = plan.advance(plan.initial_state, .01, sphere=sphere, moving=moving, **values)
                self.assertEqual(step.exchange.descriptor()['layout'], plan.layout())
                self.assertNotEqual(step.native_advance.initial_mechanics.descriptor()['plan']['viscosity_sha256'],
                                    step.native_advance.mechanics.descriptor()['plan']['viscosity_sha256'])
                self.assertEqual(step.native_advance.source_audit.descriptor()['rheology']['law'], law.record())

    def test_source_admission_exact_accounts_and_no_initial_mixing(self):
        fixture = source(); sphere, moving = fixture[:2]
        budget = WorkBudget(256*1024**2)
        with prepare(fixture[-1], budget) as native, owner(native, fixture, budget) as plan:
            state = plan.initial_state
            with self.assertRaises(O.RegionalOwnerRefused):
                plan.initial_state = state
            masses = state.native_state.array('component_mass_kg')
            self.assertTrue(np.all(np.sum(masses > 0, axis=0) == 1))
            accounts = plan.descriptor()['admission_accounts']
            for i, account in enumerate(accounts):
                exact = Fraction(*map(int, account['exact_mass_kg']))
                rounding = Fraction(*map(int, account['projection_rounding'][1]))
                self.assertEqual(sum((Fraction(float(v)) for v in masses[i].flat), Fraction(0)), exact+rounding)
                self.assertEqual(account['exact_mass_kg'], account['exact_volume_m3'])
            q = sum((Fraction(*map(int, a['exact_relative_heat_j'])) for a in accounts), Fraction(0))
            selected = plan.reservation()['patch_ids']
            self.assertEqual(q, sum((dict(moving._patch_heat)[p][0] for p in selected), Fraction(0)))
            self.assertEqual(set(plan.layout()['plate_ids']), {'A', 'B'})
            with self.assertRaises(O.RegionalOwnerRefused):
                plan.assert_global_available(selected)
            plan.assert_global_available(('unrelated-patch',))
            plan.require_dormant_source(sphere, moving)

    def test_actual_depth_fields_same_solve_heat_and_restart_continuation(self):
        fixture = source(); sphere, moving = fixture[:2]
        source_before = (sphere.state_id, moving.moving_id, tuple(moving._patch_heat))
        budget = WorkBudget(256*1024**2)
        with threadpool_limits(1), prepare(fixture[-1], budget) as native, owner(native, fixture, budget) as plan:
            first = plan.advance(plan.initial_state, .01, sphere=sphere, moving=moving, **driving(native))
            self.assertGreater(np.max(first.exchange.array('strain_increment_ii')), 0.)
            self.assertGreater(np.sum(first.exchange.array('audit:viscous_heat_source_w_m3')), 0.)
            length = native.lengths_m[0]
            analytic_power = 4*.05**2*length*(length**4/30+1/30+length**2/18)
            self.assertAlmostEqual(first.native_advance.initial_mechanics.descriptor()['power_w']['viscous_dissipation'],
                                   analytic_power, delta=2e-8)
            self.assertFalse(np.array_equal(first.state.native_state.array('component_mass_kg'),
                                            plan.initial_state.native_state.array('component_mass_kg')))
            self.assertEqual(first.exchange.descriptor()['initial_mechanics_id'], first.native_advance.initial_mechanics.result_id)
            self.assertTrue(np.all(first.exchange.array('plastic_kappa_increment') == 0))
            record = json.loads(json.dumps(first.state.descriptor()))
            arrays = {k: np.array(v) for k, v in first.state.arrays().items()}
            uninterrupted = plan.advance(first.state, .01, sphere=sphere, moving=moving, **driving(native))
            second_budget = WorkBudget(256*1024**2)
            with prepare(fixture[-1], second_budget) as again, owner(again, fixture, second_budget) as reopened:
                restored = reopened.restore(record, arrays, sphere=sphere, moving=moving)
                continued = reopened.advance(restored, .01, sphere=sphere, moving=moving, **driving(again))
                self.assertEqual(continued.state.owner_state_id, uninterrupted.state.owner_state_id)
                self.assertEqual(continued.exchange.result_id, uninterrupted.exchange.result_id)
                altered = {k: np.array(v) for k, v in arrays.items()}
                altered['regional.native.enthalpy_j'].flat[0] += .01
                with self.assertRaises(O.RegionalOwnerRefused):
                    reopened.restore(record, altered, sphere=sphere, moving=moving)
                forged = O.RegionalOwnerState(restored.native_state, first.exchange,
                    dict(record['metadata'], intervals=0))
                with self.assertRaises(O.RegionalOwnerRefused):
                    reopened.advance(forged, .01, sphere=sphere, moving=moving, **driving(again))
            self.assertEqual(source_before, (sphere.state_id, moving.moving_id, tuple(moving._patch_heat)))

    def test_admission_stale_source_and_boundary_refusals(self):
        fixture = source(); sphere, moving, footprint, allocations, _ = fixture
        budget = WorkBudget(256*1024**2)
        with prepare(fixture[-1], budget) as native, owner(native, fixture, budget) as plan:
            malformed = list(allocations); malformed[0] = replace(malformed[0], share=Fraction(1, 2))
            with self.assertRaises(O.RegionalOwnerRefused):
                owner(native, (*fixture[:3], tuple(malformed), fixture[-1]), budget)
            with self.assertRaises(O.RegionalOwnerRefused):
                owner(native, fixture, budget, plate_ids=('A', 'C'))
            nonlinear = CreepLaw((dict(a=.5, n=2., energy_j_mol=0., volume_m3_mol=0., grain_exponent=0.),), 'unsupported')
            with self.assertRaises(O.RegionalOwnerRefused):
                owner(native, fixture, budget, creep_match=dict(creep_law_id='test:constant-creep', law=nonlinear.record()))
            changed = M.declare_moving(sphere, tuple(replace(r, sublayers=tuple(replace(s,
                top_temperature_k=1.5, bottom_temperature_k=1.5) for s in r.sublayers)) for r in moving.cohorts),
                enthalpy_reference_k=1.)
            with self.assertRaises(O.RegionalOwnerRefused):
                plan.advance(plan.initial_state, .01, sphere=sphere, moving=changed, **driving(native))
            values = driving(native); values['velocity_m_s'] = .1
            with self.assertRaises(O.RegionalOwnerRefused):
                plan.advance(plan.initial_state, .01, sphere=sphere, moving=moving, **values)
            other_fixture = (*fixture[:3], tuple(reversed(allocations)), fixture[-1])
            with owner(native, other_fixture, budget) as changed_map:
                with self.assertRaises(O.RegionalOwnerRefused):
                    changed_map.restore(plan.initial_state.descriptor(), plan.initial_state.arrays(), sphere=sphere, moving=moving)
        different_budget = WorkBudget(256*1024**2)
        incompatible = BoussinesqMaterial('test:different', 'synthetic-control', 1., 2., .1, 0., 1., 0., 0., (1., 2.))
        with prepare(fixture[-1], different_budget, material=incompatible) as native:
            with self.assertRaises(O.RegionalOwnerRefused):
                owner(native, fixture, different_budget)


if __name__ == '__main__':
    unittest.main()
