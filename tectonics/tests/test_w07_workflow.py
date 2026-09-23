"""Bounded W07 geological workflow joins, physical accounts and exact recovery.

Inputs come from the real W01/W02 producer. These synthetic numerical controls
are not observed geological calibration or whole-W07 scientific acceptance.
"""
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np

from atlas_tectonics._validation import TectonicsError
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


if __name__ == '__main__':
    unittest.main()
