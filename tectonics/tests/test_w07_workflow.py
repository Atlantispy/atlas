"""Bounded W07 geological workflow joins, physical accounts and exact recovery.

Inputs come from the real W01/W02 producer. These synthetic numerical controls
are not observed geological calibration or whole-W07 scientific acceptance.
"""
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import replace
import gc
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import traceback
import unittest
from unittest.mock import patch

import numpy as np

from atlas_tectonics import reuse
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_checkpoint import restore_regional_snapshots
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot, RegionalMechanicsScales
from atlas_tectonics.regional_geology import bind_regional_geology
from atlas_tectonics.regional_strength import DryStrengthProfile
from atlas_tectonics.regional_transport import HeatBoundary
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.storage import ArrayStore, Compression, StoreError, StoreLimits
from atlas_tectonics.surface_geometry import cell_volume_and_flux
from atlas_tectonics.w07_workflow import PreparedW07Workflow, W07BoundaryMotion
from test_w01_geological_description import SOURCE
from test_w07_geology import geology_fixture


LIMITS = StoreLimits(65536, 8*1024**2, 64*1024**2)
SCALES = RegionalMechanicsScales(1., 1.)


def open_store(path, budget, cls=ArrayStore):
    """Explicit temporary-store policy, shared with the acceptance runner."""
    return cls(path, limits=LIMITS,
        compression=Compression(codec='raw', shuffle='none'), budget=budget)


@contextmanager
def make_workflow_fixture(route, *, layered=False, nx=4, nz=4, store=None,
        budget=None, output_times_s=None, interval_steps=None, speed=0.,
        thermal=False, heat_production=0., density_law='reference-constant',
        boundary_kind=None, shear_rate_s_1=0., surface_amplitude_m=0.,
        **workflow_changes):
    """Yield a real W01/W02 -> geological binding -> prepared W07 workflow.

    The fixture creates no store by itself. Default outputs are (0,) for steady
    and (0,.01,.02) for evolving routes. Public keyword overrides are explicit
    workflow inputs; source material fields remain owned by geology_fixture.
    """
    owner = WorkBudget(128*1024**2) if budget is None else budget
    state, bind = geology_fixture(layered=layered, thermal=thermal, speed=speed,
        density_law=density_law, nx=nx, nz=nz, heat_production=heat_production, budget=owner)
    kind = ('source-translation' if speed else 'closed') if boundary_kind is None else boundary_kind
    if kind != 'source-translation':
        bind['ownership'] = replace(bind['ownership'], boundary_motion_owner='W07-boundary', boundary_source=SOURCE)
    geology = bind_regional_geology(state, **bind, budget=owner)
    times = ((0.,) if route == 'steady' else (0., .01, .02)) if output_times_s is None else output_times_s
    arguments = dict(route=route, scales=SCALES, interval_steps=interval_steps, store=store, budget=owner)
    if route != 'surface':
        arguments.update(boundary_motion=W07BoundaryMotion(kind, SOURCE, shear_rate_s_1), physical_mean_pressure_pa=10.)
    if route == 'thermal':
        arguments.update(heat_boundaries={side: HeatBoundary(None, 'outward_flux', 0.)
            for side in ('left', 'right', 'bottom', 'top')}, heat_boundary_source=SOURCE)
    if route == 'surface' and surface_amplitude_m:
        arguments.update(surface_perturbation_m=surface_amplitude_m*np.cos(np.pi*np.linspace(0., 1., 2*nx+1)),
            perturbation_source=SOURCE)
    arguments.update(workflow_changes)
    with PreparedW07Workflow(geology, times, **arguments) as workflow:
        yield workflow


def output_signature(output):
    """Complete scientific identity, independent of the persistence codec."""
    return dict(output_id=output.output_id, checkpoint_id=output.checkpoint_id,
        output_index=output.output_index, state_id=output.state.result_id,
        mechanics_id=output.mechanics.result_id, receipt=output.descriptor())


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def rehash_manifest(store, key, mutate, *, rebind_output=False):
    """Corrupt one test manifest while preserving its internal storage checksums."""
    original = store._db.execute('SELECT body,digest FROM snapshots WHERE id=?', (key,)).fetchone()
    manifest = json.loads(original[0])
    metadata = manifest['metadata']
    mutate(metadata)
    if rebind_output:
        snapshots = {record['name']: record for record in metadata['payload']['snapshots']}
        metadata['output_id'] = hashlib.sha256(encoded(dict(state=snapshots['state']['result_id'],
            mechanics=snapshots['mechanics']['result_id'], receipt=metadata['receipt']))).hexdigest()
    metadata['content_id'] = hashlib.sha256(encoded({k: v for k, v in metadata.items() if k != 'content_id'})).hexdigest()
    body = encoded(manifest)
    store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?',
        (body, hashlib.sha256(body).hexdigest(), key))
    return original


class InterruptingStore(ArrayStore):
    """Cancellation through the real publication callback inside the transaction."""
    fail = False

    def put(self, invocation, arrays, metadata=None, **kwargs):
        check = kwargs.pop('publication_check', None)
        def publication_check():
            if check is not None:
                check()
            if self.fail:
                self.fail = False
                raise CancelledError('synthetic W07 pre-commit interruption')
        return super().put(invocation, arrays, metadata, publication_check=publication_check, **kwargs)


class W07WorkflowTests(unittest.TestCase):
    def equal(self, actual, expected):
        self.assertEqual(output_signature(actual), output_signature(expected))
        for first, second in ((actual.state, expected.state), (actual.mechanics, expected.mechanics)):
            self.assertEqual(first.array_names, second.array_names)
            for name in first.array_names:
                self.assertEqual(first.array(name).shape, second.array(name).shape)
                self.assertEqual(first.array(name).tobytes(), second.array(name).tobytes())

    def test_steady_hydrostatic_and_layered_source_translation_match_bound_geology(self):
        for layered, speed in ((False, 0.), (True, .125)):
            with self.subTest(layered=layered), make_workflow_fixture('steady', layered=layered, speed=speed) as workflow:
                result = workflow.run()
                geology = workflow.geology
                np.testing.assert_allclose(result.mechanics.array('u_m_s'), speed, atol=1e-10, rtol=0.)
                np.testing.assert_allclose(result.mechanics.array('w_m_s'), 0., atol=1e-10, rtol=0.)
                pressure = result.mechanics.array('physical_pressure_pa')
                np.testing.assert_allclose(np.diff(pressure, axis=0)/(geology.height_m/geology.nz),
                    geology.array('force_w_n_m3')[1:-1], atol=1e-9, rtol=1e-9)
                np.testing.assert_array_equal(result.mechanics.array('force_w_n_m3'), geology.array('force_w_n_m3'))
                self.assertAlmostEqual(float(pressure.mean()), 10., delta=1e-10)
                self.assertEqual(result.state.result_id, geology.binding_id)
                self.assertEqual(result.descriptor()['ownership']['vertical_response_owner'], 'W07')
                self.assertEqual(result.descriptor()['end_time_s'], 0.)
                self.assertIs(workflow.run(), result)
                self.assertEqual(workflow.statistics()['computed_outputs'], 1)

    def test_thermal_source_temperature_radiogenic_heat_reference_mass_and_partial_restart(self):
        owner = WorkBudget(128*1024**2)
        parameters = dict(thermal=True, heat_production=2., density_law='boussinesq-linear-reference', budget=owner)
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'thermal.db'
            with make_workflow_fixture('thermal', **parameters) as direct:
                expected = tuple(direct.run(through=i) for i in range(3))
                np.testing.assert_array_equal(expected[0].state.array('temperature_k')[:, 0], [475., 425., 375., 325.])
                source_mass = direct.geology.array('reference_mass_kg')
                for output in expected:
                    np.testing.assert_array_equal(output.state.array('reference_mass_kg'), source_mass)
                self.assertEqual(float(source_mass.sum()), 4.)
                for output in expected[1:]:
                    heat = output.descriptor()['heat']
                    self.assertAlmostEqual(heat['source_energy_j'], 2.*2.*.01, delta=1e-13)
                    self.assertAlmostEqual(heat['heat_after_j']-heat['heat_before_j'], .04, delta=1e-8)
                    self.assertLessEqual(heat['balance_relative'], 1e-9)
                self.assertGreater(float(expected[-1].state.array('temperature_k').mean()), 400.)
                # The total body force is source-linked buoyancy, not duplicate rho*g.
                np.testing.assert_allclose(expected[0].mechanics.array('force_w_n_m3')[1:-1, 0],
                    -2.*(1.-1e-4*np.array([150., 100., 50.])), rtol=1e-12, atol=1e-12)
            with open_store(path, owner) as store, make_workflow_fixture('thermal', store=store, **parameters) as partial:
                self.assertIsNone(partial.load(0))
                self.equal(partial.run(through=1), expected[1])
                self.assertEqual(store.statistics()['snapshots'], 2)
            with open_store(path, owner) as store, make_workflow_fixture('thermal', store=store, **parameters) as resumed:
                self.equal(resumed.run(), expected[-1])
                self.assertEqual(resumed.statistics()['computed_outputs'], 1)
                self.assertEqual(resumed.statistics()['restored_outputs'], 1)
                for index, output in enumerate(expected):
                    self.equal(resumed.load(index), output)
                before = resumed.statistics()['computed_outputs']
                self.equal(resumed.run(), expected[-1])
                self.assertEqual(resumed.statistics()['computed_outputs'], before)
                self.assertEqual(store.statistics()['snapshots'], 3)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_surface_volume_material_inventory_and_exact_partial_restart(self):
        owner = WorkBudget(128*1024**2)
        parameters = dict(surface_amplitude_m=1e-4, budget=owner)
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'surface.db'
            with make_workflow_fixture('surface', **parameters) as direct:
                expected = tuple(direct.run(through=i) for i in range(3))
                for output in expected:
                    volume, _ = cell_volume_and_flux(output.state.array('mesh_nodes_m'))
                    np.testing.assert_allclose(volume.sum(), 2., atol=1e-9, rtol=0.)
                    np.testing.assert_allclose(output.state.array('cell_mass_kg').sum(), 4., atol=1e-9, rtol=0.)
                    np.testing.assert_allclose(output.state.array('cell_mass_kg'), 2.*volume, atol=1e-10, rtol=1e-9)
                    self.assertEqual(output.mechanics.descriptor()['state_id'], output.state.result_id)
                self.assertLess(np.ptp(expected[-1].state.array('mesh_nodes_m')[-1, :, 1]),
                                np.ptp(expected[0].state.array('mesh_nodes_m')[-1, :, 1]))
            with open_store(path, owner) as store, make_workflow_fixture('surface', store=store, **parameters) as partial:
                self.equal(partial.run(through=1), expected[1])
            with open_store(path, owner) as store, make_workflow_fixture('surface', store=store, **parameters) as resumed:
                self.equal(resumed.run(), expected[-1])
                self.assertEqual(resumed.statistics()['computed_outputs'], 1)
                self.assertEqual(resumed.load(2).state.descriptor()['accepted_steps'], 2)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_full_mantissa_output_times_land_exactly_on_both_routes(self):
        # R1: t+(T-t)*n/n and time+dt missed the requested output by one ulp;
        # the workflow then refused its own fresh result as a restore mismatch.
        t1, a, b = 0.011583828702548055, 0.006394989738541456, 0.02878803804725395
        for times, steps in (((0., t1), (0, 3)), ((0., a, b), (0, 1, 1))):
            for route, extra in (('surface', dict(surface_amplitude_m=1e-4)),
                                 ('thermal', dict(thermal=True, heat_production=1e-6))):
                with self.subTest(route=route, times=times), make_workflow_fixture(
                        route, output_times_s=times, interval_steps=steps, **extra) as wf:
                    out = wf.run()
                    self.assertEqual(out.state.descriptor()['time_s'], times[-1])
                    if route == 'thermal':
                        self.assertEqual(out.descriptor()['heat']['time_s'], times[-1])
                    else:
                        self.assertEqual(out.descriptor()['surface']['intervals'][-1]['end_time_s'], times[-1])

    def test_supplied_dry_strength_simple_shear_preserves_physical_pressure(self):
        law = DryStrengthProfile('synthetic W07 yield', 'source-declared dry law', .1, 0., 1., (1e-10, 10.), 0., 0.)
        owner = WorkBudget(128*1024**2)
        parameters = dict(boundary_kind='simple-shear', shear_rate_s_1=1., strength_profile=law, budget=owner)
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'strength.db', owner) as store:
            with make_workflow_fixture('steady', store=store, **parameters) as workflow:
                result = workflow.run()
                np.testing.assert_allclose(result.mechanics.array('viscosity_center_pa_s'), .1, rtol=1e-8, atol=1e-10)
                np.testing.assert_allclose(result.mechanics.array('stress_xz_pa'), .1, rtol=1e-8, atol=1e-10)
                self.assertGreater(float(result.mechanics.array('physical_pressure_pa').min()), 8.)
                self.assertEqual(workflow.descriptor()['strength']['profile_id'], law.descriptor()['profile_id'])
                self.assertIn('strength_vertex_yield_stress_pa', result.mechanics.array_names)
            with make_workflow_fixture('steady', store=store, **parameters) as workflow:
                self.equal(workflow.run(), result)
                self.assertEqual(workflow.statistics()['computed_outputs'], 0)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_schedule_and_cumulative_256_step_ceiling_refuse(self):
        with make_workflow_fixture('steady') as source:
            geology = source.geology
            settings = dict(route='thermal', scales=SCALES, boundary_motion=W07BoundaryMotion('closed', SOURCE),
                physical_mean_pressure_pa=10., heat_boundaries={s: HeatBoundary(None, 'outward_flux', 0.)
                    for s in ('left', 'right', 'bottom', 'top')}, heat_boundary_source=SOURCE)
            cases = [((0., .01, .02), (0, 128, 129)), ((0., .01), (0, 257)),
                ((0., .01), (1, 1)), ((0., .01), (0, 0)), ((0., .01), (0, True)),
                ((0., 0.), (0, 0)), ((-.01, 0.), (1, 0)), ((), ()),
                (tuple(float(i) for i in range(257)), (0,)+(1,)*256)]
            for times, steps in cases:
                with self.subTest(times=times[:3], steps=steps[:3]), self.assertRaises(TectonicsError):
                    with PreparedW07Workflow(geology, times, interval_steps=steps, **settings):
                        pass
            with self.assertRaises(TectonicsError):
                with PreparedW07Workflow(geology, (0., 1.), route='steady', scales=SCALES,
                        boundary_motion=W07BoundaryMotion('closed', SOURCE), physical_mean_pressure_pa=10.):
                    pass

    def test_unsupported_material_routes_and_source_owner_mismatch_refuse(self):
        for route in ('thermal', 'surface'):
            with self.subTest(route=route), self.assertRaises(TectonicsError):
                with make_workflow_fixture(route, layered=True):
                    pass
        with self.assertRaises(TectonicsError):
            with make_workflow_fixture('surface', thermal=True):
                pass
        with self.assertRaises(TectonicsError):
            with make_workflow_fixture('surface', heat_production=1.):
                pass
        with self.assertRaises(TectonicsError):
            with make_workflow_fixture('steady', speed=.25, boundary_kind='closed'):
                pass
        with make_workflow_fixture('steady') as source:
            foreign = replace(SOURCE, statement='a different declared boundary provenance')
            with self.assertRaises(TectonicsError):
                with PreparedW07Workflow(source.geology, (0.,), route='steady', scales=SCALES,
                        boundary_motion=W07BoundaryMotion('closed', foreign), physical_mean_pressure_pa=10.):
                    pass

    def test_public_configuration_and_output_descriptors_are_immutable(self):
        with make_workflow_fixture('thermal') as workflow:
            for name, value in (('route', 'steady'), ('times', (0.,)), ('steps', (0,)),
                                ('geology', None), ('store', None), ('plan_id', '0'*64), ('execution_id', '0'*64)):
                with self.subTest(name=name), self.assertRaises((AttributeError, TectonicsError)):
                    setattr(workflow, name, value)
            descriptor = workflow.descriptor()
            descriptor['route'] = 'surface'
            self.assertEqual(workflow.descriptor()['route'], 'thermal')
            output = workflow.run(through=0)
            changed = output.descriptor(); changed['ownership']['vertical_response_owner'] = 'W04'
            self.assertEqual(output.descriptor()['ownership']['vertical_response_owner'], 'W07')
            with self.assertRaises(ValueError):
                output.state.array('temperature_k').setflags(write=True)

    def test_storage_and_resealed_physical_receipt_corruption_refuse(self):
        owner = WorkBudget(128*1024**2)
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'corrupt.db', owner) as store:
            with make_workflow_fixture('thermal', heat_production=2., store=store, budget=owner) as workflow:
                workflow.run(through=1)
                key = workflow.checkpoint_id(1)
                changes = [lambda m: m['receipt'].update(start_time_s=-10.),
                    lambda m: m['receipt'].update(source_status='CANON'),
                    lambda m: m['receipt']['ownership'].update(vertical_response_owner='W04'),
                    lambda m: m['receipt']['heat'].update(source_energy_j=10.)]
                for index, mutation in enumerate(changes):
                    original = rehash_manifest(store, key, mutation, rebind_output=True)
                    try:
                        with self.subTest(index=index), self.assertRaises((TectonicsError, StoreError)):
                            workflow.load(1)
                    finally:
                        store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?', (*original, key))
                original = store._db.execute('SELECT body,digest FROM snapshots WHERE id=?', (key,)).fetchone()
                store._db.execute('UPDATE snapshots SET body=? WHERE id=?', (b'corrupt', key))
                try:
                    with self.assertRaises(StoreError):
                        workflow.run(through=1)
                finally:
                    store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?', (*original, key))
                store._db.execute('UPDATE chunks SET payload=?', (b'corrupt',))
                with self.assertRaises(StoreError):
                    workflow.load(0)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_atomic_cancellation_preserves_prefix_and_budget_refusal(self):
        owner = WorkBudget(128*1024**2)
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'atomic.db'
            with open_store(path, owner, InterruptingStore) as store, make_workflow_fixture('thermal', store=store, budget=owner) as workflow:
                accepted = workflow.run(through=1)
                before = store.statistics()
                store.fail = True
                with self.assertRaises(CancelledError):
                    workflow.run(through=2)
                self.assertFalse(store.contains(workflow.checkpoint_id(2)))
                for key in ('unique_chunks', 'encoded_payload_bytes', 'snapshots'):
                    self.assertEqual(store.statistics()[key], before[key])
                self.equal(workflow.load(1), accepted)
                cancelled = Event(); cancelled.set()
                with self.assertRaises(CancelledError):
                    workflow.run(cancel=cancelled)
                self.assertFalse(store.contains(workflow.checkpoint_id(2)))
            with open_store(path, owner) as store, make_workflow_fixture('thermal', store=store, budget=owner) as resumed:
                result = resumed.run()
                self.assertEqual(result.output_index, 2)
                self.assertEqual(resumed.statistics()['computed_outputs'], 1)
                self.assertEqual(store.statistics()['snapshots'], 3)
        self.assertEqual(owner.reserved_bytes, 0)
        with self.assertRaises(MemoryLimitError):
            with make_workflow_fixture('steady', budget=WorkBudget(1024)):
                pass

    def test_conservative_velocity_transfer_preserves_closed_flux_and_refuses_excess(self):
        with make_workflow_fixture('thermal') as workflow:
            initial = workflow.run(through=0).mechanics
            grid = workflow._heat.grid
            x, z = np.meshgrid(np.linspace(0., np.pi, grid.nx+1), np.linspace(0., np.pi, grid.nz+1))
            psi = np.sin(x)*np.sin(z); psi[[0, -1], :] = 0.; psi[:, [0, -1]] = 0.
            u, w = np.diff(psi, axis=0)/grid.dz, -np.diff(psi, axis=1)/grid.dx
            original = u.copy(); u[1, 2] += 1e-12
            mechanics = RegionalMechanicalSnapshot(initial.descriptor(), dict(u_m_s=u, w_m_s=w))
            (actual_u, actual_w), receipt = workflow._transport_velocity(mechanics)
            np.testing.assert_allclose(actual_u, original, atol=1e-14, rtol=0.)
            np.testing.assert_allclose(actual_w, w, atol=1e-14, rtol=0.)
            self.assertLess(np.abs(np.diff(actual_u, axis=1)/grid.dx+np.diff(actual_w, axis=0)/grid.dz).max(), 1e-14)
            self.assertEqual(receipt['mechanical_input_id'], mechanics.result_id)
            u[1, 2] += 1e-3
            with self.assertRaises(TectonicsError):
                workflow._transport_velocity(RegionalMechanicalSnapshot(initial.descriptor(), dict(u_m_s=u, w_m_s=w)))

    def test_initial_state_forces_and_resealed_surface_history_corruption_refuse(self):
        with make_workflow_fixture('thermal') as workflow:
            output = workflow.run(through=0)
            state = RegionalMechanicalSnapshot(output.state.descriptor(), dict(
                temperature_k=output.state.array('temperature_k')+1., reference_mass_kg=output.state.array('reference_mass_kg')))
            with self.assertRaisesRegex(TectonicsError, 'initial temperature'):
                workflow._validate_output(replace(output, state=state), None)
            arrays = {k: output.mechanics.array(k) for k in output.mechanics.array_names}
            arrays['force_w_n_m3'] = arrays['force_w_n_m3']+1.
            mechanics = RegionalMechanicalSnapshot(output.mechanics.descriptor(), arrays)
            with self.assertRaisesRegex(TectonicsError, 'stored mechanical forces'):
                workflow._validate_output(replace(output, mechanics=mechanics), None)
        owner = WorkBudget(128*1024**2)
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'surface-corrupt.db', owner) as store:
            with make_workflow_fixture('surface', surface_amplitude_m=1e-4, store=store, budget=owner) as workflow:
                initial = workflow.run(through=0)
                state = workflow._mechanical.initial_state(1.+2e-4*np.cos(np.pi*np.linspace(0., 1., 9)), epoch_id=workflow.geology.epoch_id)
                arrays = {k: initial.mechanics.array(k) for k in initial.mechanics.array_names}
                arrays['mesh_nodes_m'] = state.array('mesh_nodes_m')
                mechanics = RegionalMechanicalSnapshot(dict(initial.mechanics.descriptor(), state_id=state.result_id), arrays)
                with self.assertRaisesRegex(TectonicsError, 'initial surface'):
                    workflow._validate_output(replace(initial, state=state, mechanics=mechanics), None)
                workflow.run(through=1)
                key = workflow.checkpoint_id(1)
                for mutation in (lambda m: m['receipt']['surface'].update(initial_state_id='0'*64),
                        lambda m: m['receipt']['surface'].update(final_state_id='0'*64),
                        lambda m: m['receipt']['surface'].update(heat_or_heterogeneous_remap=True),
                        lambda m: m['receipt']['surface']['intervals'][0].update(mass_residual_scaled=1.)):
                    original = rehash_manifest(store, key, mutation, rebind_output=True)
                    try:
                        with self.assertRaises(TectonicsError):
                            workflow.load(1)
                    finally:
                        store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?', (*original, key))
        self.assertEqual(owner.reserved_bytes, 0)

    def test_recovery_reuses_completed_mechanics_without_solving_again(self):
        owner = WorkBudget(128*1024**2)
        for route in ('thermal', 'surface'):
            with self.subTest(route=route), TemporaryDirectory() as tmp:
                path = Path(tmp)/'reuse.db'
                with open_store(path, owner) as store, make_workflow_fixture(route, store=store, budget=owner) as workflow:
                    accepted = workflow.run(through=1)
                with open_store(path, owner) as store, make_workflow_fixture(route, store=store, budget=owner) as workflow:
                    with patch.object(workflow._mechanical._core, 'solve', wraps=workflow._mechanical._core.solve) as solve:
                        self.equal(workflow.run(through=1), accepted)
                        self.assertEqual(solve.call_count, 0)
                        workflow.run()
                        self.assertEqual(solve.call_count, 2 if route == 'surface' else 1)
        self.assertEqual(owner.reserved_bytes, 0)


def cancel_in_factorisation(core, event):
    original = core._numeric
    def numeric(coefficients, cancel):
        event.set()
        return original(coefficients, cancel)
    core._numeric = numeric


def cancel_after_core_refill(core, event):
    original = core.refill_viscosity
    def refill(**kwargs):
        answer = original(**kwargs)
        event.set()
        return answer
    core.refill_viscosity = refill


def fail_in_factorisation(core, event):
    def numeric(coefficients, cancel):
        raise ValueError('synthetic factorisation failure')
    core._numeric = numeric


class Abort(BaseException):
    """An interruption that is not an Exception, as a keyboard interrupt or an interpreter exit is."""


def abort_in_factorisation(core, event):
    def numeric(coefficients, cancel):
        raise Abort('synthetic interruption')
    core._numeric = numeric


class AfterAcceptedRefill:
    """Cancel token that fires once, at the first check after the plan accepted a numeric refill.

    The plan is usable again only when the refill is accepted, so that check is the
    closing one of the regional operation: the plan then holds the new coefficients.
    """
    def __init__(self, plan):
        self.plan, self.fired = plan, False

    def is_set(self):
        if not self.fired and self.plan.usable and self.plan.statistics().get('coefficient_refills', 0):
            self.fired = True
            return True
        return False


class DuringReplacement:
    """Cancel token that fires at the n-th check made while a replacement plan is being prepared."""
    def __init__(self, workflow, n):
        self.workflow, self.n, self.calls = workflow, n, 0

    def is_set(self):
        if self.workflow._active and self.workflow._mechanical is None:
            self.calls += 1
            return self.calls == self.n
        return False


class InterruptedStrengthRefillTests(unittest.TestCase):
    """R7 (3g): an interrupted Picard coefficient refill must not disable the workflow.

    The dry-strength route refills the workflow's own regional plan at every Picard
    iteration. Cancellations and failures are injected through cancel tokens and
    through instance attributes of the one plan or workflow object. Replacing a
    function of the bound package would itself be refused as a changed
    implementation; only the source-change methods do so, as the existing
    source-drift tests do, because a changed source is what they emulate.
    """
    equal = W07WorkflowTests.equal

    @classmethod
    def setUpClass(cls):
        state, bind = geology_fixture()
        bind['ownership'] = replace(bind['ownership'], boundary_motion_owner='W07-boundary', boundary_source=SOURCE)
        cls.geology = bind_regional_geology(state, **bind)
        cls.law = DryStrengthProfile('synthetic W07 yield', 'source-declared dry law', .1, 0., 1., (1e-10, 10.), 0., 0.)
        with cls.prepare(WorkBudget(128*1024**2)) as workflow:
            cls.expected = workflow.run()

    @classmethod
    def prepare(cls, owner, store=None):
        return PreparedW07Workflow(cls.geology, (0.,), route='steady', scales=SCALES,
            boundary_motion=W07BoundaryMotion('simple-shear', SOURCE, 1.), physical_mean_pressure_pa=10.,
            strength_profile=cls.law, store=store, budget=owner)

    def interrupt(self, workflow, inject=cancel_in_factorisation, failure=CancelledError):
        """Interrupt a run inside a coefficient refill; return the plan it was using."""
        plan = workflow._mechanical
        event = Event()
        inject(plan._core, event)
        with self.assertRaises(failure):
            workflow.run(cancel=event)
        return plan

    def test_strength_workflow_resumes_after_an_interrupted_coefficient_refill(self):
        for inject, failure in ((cancel_in_factorisation, CancelledError),
                                (cancel_after_core_refill, CancelledError),
                                (fail_in_factorisation, ValueError),
                                (abort_in_factorisation, Abort)):
            owner = WorkBudget(128*1024**2)
            with self.subTest(inject=inject.__name__), TemporaryDirectory() as tmp, \
                    open_store(Path(tmp)/'refill.db', owner) as store, self.prepare(owner, store) as workflow:
                self.interrupt(workflow, inject, failure)
                self.assertFalse(store.contains(workflow.checkpoint_id(0)))
                # The same workflow computes, publishes and restores what an
                # uninterrupted workflow publishes.
                self.equal(workflow.run(), self.expected)
                self.assertEqual(workflow.statistics()['computed_outputs'], 1)
                self.assertTrue(store.contains(workflow.checkpoint_id(0)))
                self.equal(workflow.load(0), self.expected)
            self.assertEqual(owner.reserved_bytes, 0)

    def test_interrupted_refill_releases_the_plan_and_the_next_operation_replaces_it(self):
        owner = WorkBudget(128*1024**2)
        with self.prepare(owner) as workflow:
            prepared = owner.reserved_bytes
            definition, identifier = workflow._mechanical.descriptor(), workflow._mechanical.plan_id
            plan = self.interrupt(workflow)
            # The invalidated plan is closed and released, not kept.
            self.assertTrue(plan._closed)
            self.assertFalse(plan.usable)
            self.assertIsNone(workflow._mechanical)
            self.assertEqual(owner.reserved_bytes, prepared-plan._retained_allowance)
            # Any next operation prepares the replacement first, a load as well as a
            # run, with the definition the first plan was prepared with.
            self.assertIsNone(workflow.load(0))
            self.assertIsNot(workflow._mechanical, plan)
            self.assertTrue(workflow._mechanical.usable)
            self.assertEqual(workflow._mechanical.descriptor(), definition)
            self.assertEqual(workflow._mechanical.plan_id, identifier)
            self.assertEqual(owner.reserved_bytes, prepared)
        self.assertEqual(owner.reserved_bytes, 0)
        # A workflow that is closed while it holds no plan releases everything too.
        with self.prepare(owner) as workflow:
            self.interrupt(workflow)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_retry_is_admitted_by_the_smallest_budget_that_admits_the_route(self):
        # The released plan returns its retained allowance before the replacement
        # reserves it again, so a retry needs no more than an uninterrupted run.
        # Every reservation is deterministic.
        roomy = WorkBudget(128*1024**2)
        with self.prepare(roomy) as workflow:
            workflow.run()
        owner = WorkBudget(roomy.peak_reserved_bytes)
        with self.prepare(owner) as workflow:
            self.interrupt(workflow)
            self.equal(workflow.run(), self.expected)
        self.assertEqual(owner.peak_reserved_bytes, roomy.peak_reserved_bytes)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_replacement_refused_by_the_budget_is_not_adopted_and_the_next_operation_tries_again(self):
        owner = WorkBudget(128*1024**2)
        with self.prepare(owner) as workflow:
            plan = self.interrupt(workflow)
            released = owner.reserved_bytes
            # Another consumer takes the room meanwhile: one byte too little is left
            # for the plan's retained allowance.
            taken = owner.available_bytes-plan._retained_allowance+1
            with owner.reserve(taken, category='another-consumer'):
                with self.assertRaises(MemoryLimitError):
                    workflow.run()
                self.assertIsNone(workflow._mechanical)
                self.assertEqual(owner.reserved_bytes, released+taken)
            self.equal(workflow.run(), self.expected)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_failure_that_leaves_the_plan_usable_keeps_it(self):
        owner = WorkBudget(128*1024**2)
        with self.prepare(owner) as workflow:
            plan = workflow._mechanical
            cancelled = Event(); cancelled.set()
            with self.assertRaises(CancelledError):
                workflow.run(cancel=cancelled)
            self.assertIs(workflow._mechanical, plan)
            # Cancelled just after an accepted refill: the plan holds an intermediate
            # Picard viscosity and is still usable. The next run starts from the creep
            # viscosity again, so nothing left behind enters the result.
            token = AfterAcceptedRefill(plan)
            with self.assertRaises(CancelledError):
                workflow.run(cancel=token)
            self.assertTrue(token.fired)
            self.assertIs(workflow._mechanical, plan)
            self.assertTrue(plan.usable)
            self.equal(workflow.run(), self.expected)
            self.assertIs(workflow._mechanical, plan)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_released_plan_is_replaced_before_a_stored_output_is_restored(self):
        owner = WorkBudget(128*1024**2)
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'shared.db', owner) as store:
            with self.prepare(owner, store) as workflow:
                plan = self.interrupt(workflow)
                # Another workflow on the same store publishes the output meanwhile.
                with self.prepare(owner, store) as other:
                    self.equal(other.run(), self.expected)
                # A restore checks the stored mechanics against the plan's definition,
                # so the replacement has to exist although no solve is needed.
                self.equal(workflow.run(), self.expected)
                self.assertIsNot(workflow._mechanical, plan)
                statistics = workflow.statistics()
                self.assertEqual((statistics['computed_outputs'], statistics['restored_outputs']), (0, 1))
        self.assertEqual(owner.reserved_bytes, 0)

    def test_cancellation_at_every_check_of_a_replacement_leaves_a_workflow_that_can_try_again(self):
        owner = WorkBudget(128*1024**2)
        with self.prepare(owner) as workflow:
            prepared = owner.reserved_bytes
            plan = self.interrupt(workflow)
            released = prepared-plan._retained_allowance
            stages = set()
            for n in range(1, 257):
                try:
                    result = workflow.run(cancel=DuringReplacement(workflow, n))
                except CancelledError as stopped:
                    # A cancelled replacement is not adopted and holds nothing.
                    stages.update(frame.name for frame in traceback.extract_tb(stopped.__traceback__))
                    self.assertIsNone(workflow._mechanical)
                    self.assertEqual(owner.reserved_bytes, released)
                    continue
                break
            else:
                self.fail('the replacement was never completed')
            # The scan cancelled the preparation in its topology build and its factorisation.
            self.assertLessEqual({'_prepare_mechanical', '_build', '_numeric'}, stages)
            self.equal(result, self.expected)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_interrupted_replacement_plan_is_released_and_replaced_as_well(self):
        owner = WorkBudget(128*1024**2)
        with self.prepare(owner) as workflow:
            prepared = owner.reserved_bytes
            first = self.interrupt(workflow)
            released = prepared-first._retained_allowance
            self.assertIsNone(workflow.load(0))
            second = self.interrupt(workflow, cancel_after_core_refill)
            self.assertIsNot(second, first)
            self.assertTrue(second._closed)
            self.assertIsNone(workflow._mechanical)
            self.assertEqual(owner.reserved_bytes, released)
            self.equal(workflow.run(), self.expected)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_replacement_plan_cannot_adopt_another_execution_identity(self):
        owner = WorkBudget(128*1024**2)
        with self.prepare(owner) as workflow:
            prepared = owner.reserved_bytes
            plan = self.interrupt(workflow)
            released = prepared-plan._retained_allowance
            recorded = workflow.execution_id
            self.assertEqual(recorded, plan._context_id)
            # Stand in for a workflow that was prepared under other source bytes.
            object.__setattr__(workflow, 'execution_id', 'identity-of-an-earlier-source')
            try:
                for _ in range(2):
                    try:
                        workflow.run()
                    except TectonicsError:
                        # The refused plan was closed, not left to the garbage collector: its
                        # allowance is back while this refusal's traceback still refers to it.
                        self.assertEqual(owner.reserved_bytes, released)
                    else:
                        self.fail('a plan under another execution identity was adopted')
                    self.assertIsNone(workflow._mechanical)
                    self.assertEqual(owner.reserved_bytes, released)
            finally:
                object.__setattr__(workflow, 'execution_id', recorded)
            self.equal(workflow.run(), self.expected)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_source_change_is_reported_and_no_replacement_is_adopted_under_it(self):
        original = reuse._source_bytes
        def changed():
            sources = original()
            sources['synthetic-source-drift.py'] = b'not the accepted implementation'
            return sources
        drift = patch.object(reuse, '_source_bytes', changed)
        owner = WorkBudget(128*1024**2)
        with self.prepare(owner) as workflow:
            prepared = owner.reserved_bytes
            plan = workflow._mechanical
            released = prepared-plan._retained_allowance
            core_refill = plan._core.refill_viscosity
            def refill(**kwargs):
                answer = core_refill(**kwargs)
                drift.start()  # the source changes while the coefficients are being replaced
                return answer
            plan._core.refill_viscosity = refill
            try:
                # The post-refill source check refuses. Closing the invalidated plan
                # refuses as well: that second error must not replace the first (it
                # would carry the first as its context), and the plan's storage is
                # released all the same.
                with self.assertRaises(TectonicsError) as caught:
                    workflow.run()
                self.assertIsNone(caught.exception.__context__)
                self.assertTrue(plan._closed)
                self.assertIsNone(workflow._mechanical)
                self.assertEqual(owner.reserved_bytes, released)
                # While the source differs the workflow's own check refuses first.
                with self.assertRaises(TectonicsError):
                    workflow.run()
                self.assertIsNone(workflow._mechanical)
            finally:
                drift.stop()
            # The source changes again, now between the workflow's own check and the
            # preparation of the replacement: the replacement is refused, not adopted.
            checked = workflow._check
            def check(cancel=None):
                checked(cancel)
                drift.start()
            workflow._check = check
            try:
                with self.assertRaises(TectonicsError):
                    workflow.run()
            finally:
                drift.stop()
                del workflow._check
            self.assertIsNone(workflow._mechanical)
            self.assertEqual(owner.reserved_bytes, released)
            result = workflow.run()
            self.equal(result, self.expected)
            self.assertEqual(result.mechanics.descriptor()['context_id'], workflow.execution_id)
        self.assertEqual(owner.reserved_bytes, 0)


def recoupled(output, coupling):
    """The same output with another heat-coupling record in its receipt."""
    receipt = output.descriptor()
    receipt['heat']['coupling'] = coupling
    return replace(output, _receipt=encoded(receipt))


class HeatCouplingRestoreTests(unittest.TestCase):
    """R7 (3b): a thermal restore regenerates the heat-coupling record from stored input mechanics.

    Linear Boussinesq buoyancy and a laterally varying bottom heat flux drive a real
    flow, so the mechanics that enter the second heat interval move and share no
    solved field with its endpoint. The first interval's input is the solve at the
    geological epoch. Records are tampered with in two ways, and both leave every
    stored hash consistent: rehash_manifest rewrites a receipt and all digests over
    it, and ``published`` writes a record through the workflow's own packer with a
    substituted snapshot. Only the workflow's physical checks can then refuse.
    """
    equal = W07WorkflowTests.equal

    @classmethod
    def setUpClass(cls):
        state, bind = geology_fixture(thermal=True, heat_production=2., density_law='boussinesq-linear-reference')
        bind['ownership'] = replace(bind['ownership'], boundary_motion_owner='W07-boundary', boundary_source=SOURCE)
        cls.geology = bind_regional_geology(state, **bind)
        # Heat leaves through the left half of the closed bottom and enters through the right half.
        cls.boundaries = {side: HeatBoundary(None, 'outward_flux', 0.) for side in ('left', 'right', 'top')}
        cls.boundaries['bottom'] = HeatBoundary(None, 'outward_flux', np.array([5e4, 5e4, -5e4, -5e4]))
        with cls.prepare(WorkBudget(128*1024**2)) as workflow:
            cls.expected = tuple(workflow.run(through=index) for index in range(2))

    @classmethod
    def prepare(cls, owner, store=None, times=(.01, .02), steps=(1, 1), geology=None):
        """By default every output evolves heat, the first one from the geological epoch."""
        return PreparedW07Workflow(cls.geology if geology is None else geology, times, route='thermal',
            scales=SCALES, interval_steps=steps,
            boundary_motion=W07BoundaryMotion('closed', SOURCE), physical_mean_pressure_pa=10.,
            heat_boundaries=cls.boundaries, heat_boundary_source=SOURCE, store=store, budget=owner)

    @staticmethod
    def stored(store, key, owner):
        """The snapshots of one published checkpoint, decoded by the public codec alone."""
        return restore_regional_snapshots(store.get(key, budget=owner), store.metadata(key)['payload'], budget=owner)

    def first_input(self, owner):
        """The epoch mechanics an honest run stores with its first output."""
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'honest.db', owner) as store:
            with self.prepare(owner, store) as workflow:
                workflow.run(through=0)
            return self.stored(store, self.expected[0].checkpoint_id, owner)['coupling_mechanics']

    @contextmanager
    def published(self, owner, *records, **schedule):
        """A workflow on a new store that holds the given (output, coupling mechanics) records."""
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'published.db', owner) as store, \
                self.prepare(owner, store, **schedule) as workflow:
            for output, mechanics in records:
                arrays, metadata = (workflow._pack(output, None) if mechanics is None
                                    else workflow._pack(output, None, mechanics))
                store.put(output.checkpoint_id, arrays, metadata, budget=owner)
            yield workflow

    def test_resealed_heat_coupling_refuses_at_the_first_and_at_a_later_interval(self):
        owner = WorkBudget(128*1024**2)
        bogus = 'f'*64
        changes = dict(
            input_id=lambda heat: heat['coupling'].update(mechanical_input_id=bogus),
            velocity=lambda heat: heat['coupling'].update(velocity_sha256=[bogus, bogus]),
            swapped_velocity=lambda heat: heat['coupling']['velocity_sha256'].reverse(),
            malformed_velocity=lambda heat: heat['coupling'].update(velocity_sha256=['not-a-digest', 7]),
            correction=lambda heat: heat['coupling'].update(maximum_correction_m_s=123.),
            next_correction=lambda heat: heat['coupling'].update(maximum_correction_m_s=float(
                np.nextafter(heat['coupling']['maximum_correction_m_s'], 1.))),
            record_as_list=lambda heat: heat.update(coupling=[heat['coupling']]),
            record_missing=lambda heat: heat.update(coupling=None))
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'coupling.db', owner) as store, \
                self.prepare(owner, store) as workflow:
            workflow.run()
            for index, expected in enumerate(self.expected):
                key = workflow.checkpoint_id(index)
                # A real mechanics identity of the same record, but not the one that carried the heat.
                endpoint = expected.mechanics.result_id
                named = dict(changes, endpoint_as_input=lambda heat: heat['coupling'].update(mechanical_input_id=endpoint))
                for name, change in named.items():
                    original = rehash_manifest(store, key, lambda m: change(m['receipt']['heat']), rebind_output=True)
                    try:
                        with self.subTest(index=index, field=name), self.assertRaises(TectonicsError):
                            workflow.load(index)
                    finally:
                        store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?', (*original, key))
                self.equal(workflow.load(index), expected)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_run_does_not_continue_from_a_resealed_latest_record(self):
        owner = WorkBudget(128*1024**2)
        schedule = dict(times=(.01, .02, .03), steps=(1, 1, 1))
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'resumed.db'
            with open_store(path, owner) as store, self.prepare(owner, store, **schedule) as workflow:
                workflow.run(through=1)
                key = workflow.checkpoint_id(1)
                original = rehash_manifest(store, key, lambda m: m['receipt']['heat']['coupling'].update(
                    velocity_sha256=['f'*64, 'f'*64], maximum_correction_m_s=123.), rebind_output=True)
            with open_store(path, owner) as store, self.prepare(owner, store, **schedule) as resumed:
                with self.assertRaises(TectonicsError):
                    resumed.run()
                self.assertEqual(resumed.statistics()['computed_outputs'], 0)
                self.assertFalse(store.contains(resumed.checkpoint_id(2)))
                store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?', (*original, key))
                self.assertEqual(resumed.run().output_index, 2)
                self.assertEqual(resumed.statistics()['computed_outputs'], 1)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_exactly_zero_correction_in_another_encoding_is_refused(self):
        # Without gravity there is no body force and nothing moves, so the honest
        # correction is exactly 0.0. A record that states it as -0.0 or as the integer 0
        # holds an equal number but other receipt bytes: it would restore as another output.
        state, bind = geology_fixture(thermal=True, heat_production=2., density_law='boussinesq-linear-reference')
        bind['ownership'] = replace(bind['ownership'], boundary_motion_owner='W07-boundary', boundary_source=SOURCE)
        bind['gravity_m_s2'] = 0.
        schedule = dict(times=(.01, .02, .03), steps=(1, 1, 1), geology=bind_regional_geology(state, **bind))
        reseal = lambda value: lambda m: m['receipt']['heat']['coupling'].update(maximum_correction_m_s=value)
        owner = WorkBudget(128*1024**2)
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'zero.db', owner) as store, \
                self.prepare(owner, store, **schedule) as workflow:
            for index in range(2):
                honest = workflow.run(through=index)
                key = workflow.checkpoint_id(index)
                self.assertEqual(encoded(honest.descriptor()['heat']['coupling']['maximum_correction_m_s']), b'0.0')
                for value in (-0., 0):
                    original = rehash_manifest(store, key, reseal(value), rebind_output=True)
                    try:
                        with self.subTest(index=index, value=repr(value)), self.assertRaises(TectonicsError):
                            workflow.load(index)
                    finally:
                        store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?', (*original, key))
                self.equal(workflow.load(index), honest)
            # A run does not continue from a latest record resealed that way.
            original = rehash_manifest(store, key, reseal(-0.), rebind_output=True)
            with self.assertRaises(TectonicsError):
                workflow.run()
            self.assertEqual(workflow.statistics()['computed_outputs'], 2)
            self.assertFalse(store.contains(workflow.checkpoint_id(2)))
            store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?', (*original, key))
            self.assertEqual(workflow.run().output_index, 2)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_every_evolved_thermal_checkpoint_stores_the_mechanics_that_carried_its_heat(self):
        owner = WorkBudget(128*1024**2)
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'stored.db', owner) as store:
            with self.prepare(owner, store) as workflow:
                workflow.run()
            first, second = (self.stored(store, output.checkpoint_id, owner) for output in self.expected)
        for snapshots, output in ((first, self.expected[0]), (second, self.expected[1])):
            self.assertEqual(set(snapshots), {'state', 'mechanics', 'coupling_mechanics'})
            self.assertEqual(snapshots['coupling_mechanics'].result_id,
                output.descriptor()['heat']['coupling']['mechanical_input_id'])
            self.assertEqual(snapshots['mechanics'].result_id, output.mechanics.result_id)
        # The first interval's input is the solve at the geological epoch, which no output holds.
        self.assertEqual(first['coupling_mechanics'].descriptor()['request']['time_s'], self.geology.time_s)
        self.assertNotEqual(first['coupling_mechanics'].result_id, first['mechanics'].result_id)
        # A later interval's input is its parent's endpoint. Here it moves, and its
        # velocity differs from the endpoint velocity of its own interval.
        moving = second['coupling_mechanics']
        self.assertEqual(moving.result_id, self.expected[0].mechanics.result_id)
        self.assertGreater(float(np.abs(moving.array('u_m_s')).max()), 1e-7)
        self.assertFalse(np.array_equal(moving.array('u_m_s'), second['mechanics'].array('u_m_s')))
        # An output at the geological epoch evolves no heat and stores no input.
        schedule = dict(times=(0., .01), steps=(0, 1))
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'epoch.db', owner) as store:
            with self.prepare(owner, store, **schedule) as workflow:
                keys = [workflow.run(through=index).checkpoint_id for index in range(2)]
            self.assertEqual(set(self.stored(store, keys[0], owner)), {'state', 'mechanics'})
            self.assertEqual(set(self.stored(store, keys[1], owner)), {'state', 'mechanics', 'coupling_mechanics'})
        self.assertEqual(owner.reserved_bytes, 0)

    def test_first_interval_restore_equals_the_continuous_run_and_solves_nothing(self):
        owner = WorkBudget(128*1024**2)
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'first.db'
            with open_store(path, owner) as store, self.prepare(owner, store) as workflow:
                self.equal(workflow.run(through=0), self.expected[0])
            with open_store(path, owner) as store, self.prepare(owner, store) as workflow:
                with patch.object(workflow._mechanical._core, 'solve', wraps=workflow._mechanical._core.solve) as solve:
                    self.equal(workflow.load(0), self.expected[0])
                    self.assertEqual(solve.call_count, 0)
                    # The continuation takes the restored endpoint as its input and
                    # solves one new endpoint; restoring that output solves nothing.
                    self.equal(workflow.run(), self.expected[1])
                    self.assertEqual(solve.call_count, 1)
                    self.equal(workflow.load(1), self.expected[1])
                    self.assertEqual(solve.call_count, 1)
                statistics = workflow.statistics()
                self.assertEqual((statistics['computed_outputs'], statistics['restored_outputs']), (1, 3))
        self.assertEqual(owner.reserved_bytes, 0)

    def test_checkpoint_without_its_input_mechanics_or_with_an_unexpected_one_is_refused(self):
        owner = WorkBudget(128*1024**2)
        schedule = dict(times=(0., .01), steps=(0, 1))
        with self.prepare(owner, **schedule) as direct:
            initial, evolved = (direct.run(through=index) for index in range(2))
        # An evolved output published without the mechanics that carried its heat.
        with self.published(owner, (initial, None), (evolved, None), **schedule) as workflow:
            self.equal(workflow.load(0), initial)
            with self.assertRaises(TectonicsError):
                workflow.load(1)
            with self.assertRaises(TectonicsError):
                workflow.run()
            self.assertEqual(workflow.statistics()['computed_outputs'], 0)
        # An output at the geological epoch, which evolved no heat, published with one.
        with self.published(owner, (initial, initial.mechanics), **schedule) as workflow:
            with self.assertRaises(TectonicsError):
                workflow.load(0)
        # The complete records: the evolved output's input is the initial endpoint.
        with self.published(owner, (initial, None), (evolved, initial.mechanics), **schedule) as workflow:
            self.equal(workflow.load(1), evolved)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_first_interval_input_is_held_to_the_geological_epoch_its_source_and_the_gates(self):
        owner = WorkBudget(128*1024**2)
        first = self.expected[0]
        honest = self.first_input(owner)
        endpoint = first.mechanics
        fields = lambda snapshot: {name: snapshot.array(name) for name in snapshot.array_names}
        # The endpoint fields under a request that claims the geological epoch.
        request = dict(endpoint.descriptor()['request'], time_s=self.geology.time_s)
        relabelled = RegionalMechanicalSnapshot(dict(endpoint.descriptor(), request=request,
            request_id=hashlib.sha256(encoded(request)).hexdigest()), fields(endpoint))
        # The honest input fields under diagnostics that did not pass the gates ...
        descriptor = honest.descriptor()
        ungated = RegionalMechanicalSnapshot(dict(descriptor,
            diagnostics=dict(descriptor['diagnostics'], gates_passed=False)), fields(honest))
        # ... and under a request at the first output's time: only the time is wrong.
        request = dict(descriptor['request'], time_s=first.descriptor()['end_time_s'])
        mistimed = RegionalMechanicalSnapshot(dict(descriptor, request=request,
            request_id=hashlib.sha256(encoded(request)).hexdigest()), fields(honest))
        with self.prepare(owner) as direct:
            # Receipt and snapshot agree: the record is the one the substitute generates.
            consistent = lambda mechanics: (recoupled(first, direct._transport_velocity(mechanics)[1]), mechanics)
            cases = dict(endpoint=(first, endpoint), consistent_endpoint=consistent(endpoint),
                relabelled_endpoint=consistent(relabelled), ungated_input=consistent(ungated),
                mistimed_input=consistent(mistimed))
        for name, record in cases.items():
            with self.subTest(case=name), self.published(owner, record) as workflow:
                with self.assertRaises(TectonicsError):
                    workflow.load(0)
                with self.assertRaises(TectonicsError):
                    workflow.run()
                self.assertEqual(workflow.statistics()['computed_outputs'], 0)
        # Finite velocities that overflow the regeneration give a correction that is not a
        # number. No stored record equals it: a refusal like the others, not an encoding error.
        overflowing = RegionalMechanicalSnapshot(descriptor, dict(fields(honest),
            w_m_s=np.full_like(honest.array('w_m_s'), 1e308)))
        with self.published(owner, (first, overflowing)) as workflow, np.errstate(over='ignore', invalid='ignore'):
            with self.assertRaises(TectonicsError):
                workflow.load(0)
        with self.published(owner, (first, honest)) as workflow:
            self.equal(workflow.load(0), first)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_later_interval_input_must_be_the_parent_endpoint_and_regenerate_its_record(self):
        owner = WorkBudget(128*1024**2)
        first, second = self.expected
        epoch = self.first_input(owner)
        honest = first.mechanics
        fields = {name: honest.array(name) for name in honest.array_names}
        descriptor = honest.descriptor()
        with self.prepare(owner) as direct:
            consistent = lambda mechanics: (recoupled(second, direct._transport_velocity(mechanics)[1]), mechanics)
            cases = dict(
                # Another accepted mechanics of the same run, with the record it generates.
                own_endpoint=consistent(second.mechanics), epoch_solve=consistent(epoch),
                # The parent's endpoint fields, but not on the heat grid's velocity support ...
                other_support=(second, RegionalMechanicalSnapshot(descriptor,
                    dict(fields, u_m_s=fields['w_m_s'], w_m_s=fields['u_m_s']))),
                # ... or without the diagnostics that set the admitted correction.
                no_diagnostics=(second, RegionalMechanicalSnapshot(
                    {k: v for k, v in descriptor.items() if k != 'diagnostics'}, fields)))
        for name, record in cases.items():
            with self.subTest(case=name), self.published(owner, (first, epoch), record) as workflow:
                self.equal(workflow.load(0), first)
                with self.assertRaises(TectonicsError):
                    workflow.load(1)
        with self.published(owner, (first, epoch), (second, honest)) as workflow:
            self.equal(workflow.load(1), second)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_interval_input_is_not_held_into_the_next_interval(self):
        # run() hands each interval's input mechanics to the packer. Held any longer,
        # the previous interval's input would stay alive while the next endpoint is solved.
        owner = WorkBudget(128*1024**2)
        alive = lambda: sum(type(item) is RegionalMechanicalSnapshot for item in gc.get_objects())
        gc.collect()
        before, seen = alive(), []
        with self.prepare(owner, times=(.01, .02, .03, .04), steps=(1, 1, 1, 1)) as workflow:
            core = workflow._mechanical._core
            solve = core.solve
            def counted(*args, **kwargs):
                gc.collect()
                seen.append(alive()-before)
                return solve(*args, **kwargs)
            core.solve = counted
            workflow.run()
        # The solves are the epoch input and four endpoints. The first sees the geological
        # source alone, the second also the epoch input. From then on the workflow holds
        # its source and the parent output's state and mechanics, and nothing older.
        self.assertEqual(seen, [1, 2, 3, 3, 3])
        self.assertEqual(owner.reserved_bytes, 0)

    def test_restore_is_admitted_by_the_smallest_budget_that_admits_the_run(self):
        # The stored input adds to what a restore decodes. A budget that can publish
        # a checkpoint must still be able to restore it. Every reservation is deterministic.
        roomy = WorkBudget(128*1024**2)
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'roomy.db', roomy) as store, \
                self.prepare(roomy, store) as workflow:
            workflow.run()
        smallest = roomy.peak_reserved_bytes
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'tight.db'
            with self.assertRaises(MemoryLimitError):
                refused = WorkBudget(smallest-1)
                with open_store(Path(tmp)/'refused.db', refused) as store, self.prepare(refused, store) as workflow:
                    workflow.run()
            owner = WorkBudget(smallest)
            with open_store(path, owner) as store, self.prepare(owner, store) as workflow:
                self.equal(workflow.run(), self.expected[1])
            self.assertEqual(owner.reserved_bytes, 0)
            owner = WorkBudget(smallest)
            with open_store(path, owner) as store, self.prepare(owner, store) as workflow:
                reserved = 0
                for index, expected in enumerate(self.expected):
                    self.equal(workflow.load(index), expected)
                    # The run needs far more than a restore, so the budget alone would not show
                    # a restore that came to reserve more. What a restore reserves for itself is
                    # held here: four times the record's distinct stored array bytes plus 64 KiB,
                    # which covers those arrays and every snapshot decoded from them, the
                    # stored input mechanics included.
                    key = expected.checkpoint_id
                    arrays = store.get(key, budget=owner)
                    snapshots = restore_regional_snapshots(arrays, store.metadata(key)['payload'], budget=owner)
                    distinct = sum(array.nbytes for array in arrays.values())
                    reserved = max(reserved, 4*distinct+65536)
                    self.assertEqual(workflow.statistics()['budget']['category_peaks']['w07-restore'], reserved)
                    self.assertGreater(4*distinct+65536,
                        distinct+sum(snapshot.nbytes for snapshot in snapshots.values()))
                    del arrays, snapshots
            self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
