"""W06.5 recovery joins on three separate physical routes, not a new grid sweep."""
from concurrent.futures import CancelledError
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreError
from atlas_tectonics.w06_workflow import PreparedW06Workflow
from test_w06_spreading_cooling import cooling_parameters, field_errors
from test_w06_history_cooling import reference_history
from test_w06_margin_cooling import independent_reference
from w06_cooling_reference import CoolingReference
from w06_history_reference import case_events
from w06_workflow_case import (ROUTES, THREAD_VARIABLES, LIMITS, CALLER_ALLOWANCE,
    CASE, COOLING, HISTORY, YEAR, ROOT, verify_frozen_design, route_fixture,
    margin_source, margin_policy, open_store, checkpoint_signature, scientific_arrays)


class InterruptingStore(ArrayStore):
    """Interrupt only the already supported publication callback, inside SQLite."""
    fail = False

    def put(self, invocation, arrays, metadata=None, **kwargs):
        check = kwargs.pop('publication_check', None)
        def publication_check():
            if check is not None:
                check()
            if self.fail:
                self.fail = False
                raise CancelledError('synthetic pre-commit interruption')
        return super().put(invocation, arrays, metadata, publication_check=publication_check, **kwargs)


def rehash_manifest(store, key, mutate):
    """Test semantic validation after internally consistent storage checksums."""
    body = store._db.execute('SELECT body FROM snapshots WHERE id=?', (key,)).fetchone()[0]
    manifest = json.loads(body)
    mutate(manifest['metadata'])
    meta = manifest['metadata']
    header = {k: v for k, v in meta.items() if k != 'content_id'}
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    meta['content_id'] = hashlib.sha256(encode(header)).hexdigest()
    body = encode(manifest)
    store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?',
                      (body, hashlib.sha256(body).hexdigest(), key))


class W06WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        verify_frozen_design()

    def equal(self, actual, expected):
        self.assertEqual(checkpoint_signature(actual), checkpoint_signature(expected))
        self.assertIs(type(actual.state), type(expected.state))
        for first, second in zip(scientific_arrays(actual.state), scientific_arrays(expected.state)):
            np.testing.assert_array_equal(first, second)

    def test_three_routes_exact_restart_and_verified_warm_reuse(self):
        for route in ROUTES:
            owner = WorkBudget(CASE['work_budget_bytes'])
            with self.subTest(route=route), TemporaryDirectory() as tmp, owner.reserve(CALLER_ALLOWANCE):
                path = Path(tmp)/'run.db'
                with route_fixture(route, budget=owner) as (plan, policy, times):
                    with PreparedW06Workflow(plan, times, margin_policy=policy) as direct:
                        expected = tuple(direct.run(through=i) for i in range(len(times)))
                    with open_store(path, owner) as store, PreparedW06Workflow(
                            plan, times, margin_policy=policy, store=store) as workflow:
                        self.assertIsNone(workflow.load(0))
                        self.equal(workflow.run(through=2), expected[2])
                        self.assertEqual(store.statistics()['snapshots'], 3)
                with route_fixture(route, budget=owner) as (plan, policy, times), open_store(path, owner) as store:
                    with PreparedW06Workflow(plan, times, margin_policy=policy, store=store) as workflow:
                        self.equal(workflow.run(), expected[-1])
                        for index, output in enumerate(expected):
                            self.equal(workflow.load(index), output)
                        calls = dict(thermal=0, source_verification=0)
                        def profile(frame, event, arg):
                            if event != 'call':
                                return
                            module, name = frame.f_globals.get('__name__'), frame.f_code.co_name
                            if module in ('atlas_tectonics.spreading_cooling',
                                    'atlas_tectonics.spreading_history_cooling', 'atlas_tectonics.margin_cooling'):
                                if name in ('_values', '_evaluate', 'evaluate', '_images', '_spectral'):
                                    calls['thermal'] += 1
                            if module == 'atlas_tectonics.reuse' and name == 'verify':
                                calls['source_verification'] += 1
                        previous = sys.getprofile()
                        try:
                            sys.setprofile(profile)
                            self.equal(workflow.run(), expected[-1])
                        finally:
                            sys.setprofile(previous)
                        self.assertEqual(calls['thermal'], 0, 'warm output repeated completed thermal work')
                        self.assertGreater(calls['source_verification'], 0)
                        self.assertEqual(store.statistics()['snapshots'], 4)
                        for array in scientific_arrays(workflow.load(3).state):
                            with self.assertRaises(ValueError):
                                array.setflags(write=True)
            self.assertEqual(owner.reserved_bytes, 0)

    def test_restored_history_final_output_against_independent_fields_and_first_exits(self):
        owner = WorkBudget(CASE['work_budget_bytes'])
        with TemporaryDirectory() as tmp, owner.reserve(CALLER_ALLOWANCE):
            path = Path(tmp)/'history.db'
            with route_fixture('history', budget=owner) as (plan, policy, times), open_store(path, owner) as store:
                with PreparedW06Workflow(plan, times, store=store) as workflow:
                    at_event = workflow.run(through=2)
                    original_strips = at_event.state.motion.strips
                    self.assertEqual(at_event.state.motion.intervals, 2)
            with route_fixture('history', budget=owner) as (plan, policy, times), open_store(path, owner) as store:
                with PreparedW06Workflow(plan, times, store=store) as workflow:
                    result = workflow.run().state
                    thermal, reference = CoolingReference(COOLING, CASE['phases']), reference_history()
                    expected = reference.thermal_fields(plan.spreading.grid.edges_m, result.time_s, thermal)
                    for name in ('cell_values', 'centre_values'):
                        errors = field_errors(getattr(result, name), expected[name])
                        contrast = COOLING['compensation_density_kg_m3']-COOLING['water_density_kg_m3']
                        for field, gate in dict(temperature_k=COOLING['mean_temperature_error_k'],
                                sheet_kg_m2=contrast*COOLING['support_error_m'],
                                subsidence_m=COOLING['support_error_m'], depth_m=COOLING['support_error_m'],
                                heat_j_m2=thermal.energy*COOLING['heat_relative_error']).items():
                            self.assertLessEqual(errors[field], gate)
                    np.testing.assert_array_equal(result.centre_valid, expected['centre_valid'])
                    np.testing.assert_allclose(result.ocean_fraction, expected['ocean_fraction'], atol=1e-12, rtol=0.)
                    np.testing.assert_allclose(result.motion.centre_age_s, expected['centre_age_s'], atol=1., rtol=0.)
                    heat, water = reference.thermal_accounts(result.time_s, thermal, width_m=CASE['width_m'])
                    scale = max(heat[0], math.fsum(abs(v) for v in heat[[2, 4, 6, 7]]), 1.)
                    np.testing.assert_allclose(result.heat_accounts_j[:9], heat[:9],
                        atol=scale*COOLING['heat_relative_error'], rtol=0.)
                    self.assertLessEqual(abs(heat[-1]), COOLING['reference_heat_relative_error'])
                    self.assertLessEqual(abs(result.heat_accounts_j[-1]), COOLING['heat_relative_error'])
                    np.testing.assert_allclose(result.water_accounts_m3[:5], water[:5],
                        atol=900000.*COOLING['support_error_m'], rtol=0.)
                    mass = reference.material_accounts(result.time_s, CASE['phases'], width_m=CASE['width_m'])
                    np.testing.assert_allclose(result.motion.accounts_kg, mass, rtol=0.,
                        atol=128*np.finfo(float).eps*np.max(np.abs(mass)))
                    self.assertEqual(result.motion.intervals, 3)
                    self.assertAlmostEqual(result.motion.created_width_m, 900000., delta=1e-7)
                    self.assertEqual(len(result.exports), 1)
                    export = result.exports[0].history
                    self.assertAlmostEqual(export.exported_width_m, 50000., delta=1e-7)
                    independent_exit = reference.first_exits(result.time_s)[0]
                    self.assertEqual(export.plate_id, independent_exit.plate_id)
                    self.assertEqual(export.birth_source_id, independent_exit.birth_source_id)
                    np.testing.assert_allclose([export.birth_offset_first_s, export.birth_offset_last_s,
                        export.exit_offset_first_s, export.exit_offset_last_s, export.exit_age_first_s,
                        export.exit_age_last_s], [independent_exit.birth_first_s, independent_exit.birth_last_s,
                        independent_exit.exit_first_s, independent_exit.exit_last_s, independent_exit.age_first_s,
                        independent_exit.age_last_s], atol=1., rtol=0.)
                    for old in original_strips:
                        inherited_strip = next(s for s in result.motion.strips if
                            (s.side, s.birth_event_id) == (old.side, old.birth_event_id))
                        self.assertEqual(inherited_strip.birth_plate_id, old.birth_plate_id)
                        self.assertEqual(inherited_strip.birth_source_id, old.birth_source_id)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_fresh_process_history_and_inherited_margin_continuation(self):
        script = '''
import json, sys
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.w06_workflow import PreparedW06Workflow
from w06_workflow_case import CASE, CALLER_ALLOWANCE, route_fixture, open_store, checkpoint_signature
budget = WorkBudget(CASE['work_budget_bytes'])
with budget.reserve(CALLER_ALLOWANCE):
    with route_fixture(sys.argv[1], budget=budget) as (plan, policy, times), open_store(sys.argv[2], budget) as store:
        with PreparedW06Workflow(plan, times, margin_policy=policy, store=store) as workflow:
            prior = checkpoint_signature(workflow.load(2))
            final = checkpoint_signature(workflow.run())
print(json.dumps(dict(prior=prior, final=final, reserved=budget.reserved_bytes)))
'''
        for route in ('history', 'margin'):
            owner = WorkBudget(CASE['work_budget_bytes'])
            with self.subTest(route=route), TemporaryDirectory() as tmp, owner.reserve(CALLER_ALLOWANCE):
                path = Path(tmp)/'cold.db'
                with route_fixture(route, budget=owner) as (plan, policy, times):
                    with PreparedW06Workflow(plan, times, margin_policy=policy) as direct:
                        expected = checkpoint_signature(direct.run())
                    with open_store(path, owner) as store, PreparedW06Workflow(
                            plan, times, margin_policy=policy, store=store) as workflow:
                        checkpoint = workflow.run(through=2)
                        prior = checkpoint_signature(checkpoint)
                        if route == 'margin':
                            restored = workflow.load(2).state
                            t = restored.thermal
                            self.assertIs(t.source_state, plan.initial_state)
                            self.assertIs(t.source_profile, plan.source_profile)
                            self.assertEqual(t.source_time_s, 1e12)
                            self.assertEqual(t.elapsed_s, 1e14)
                            self.assertIsNone(t.cooling_history.start_time_s)
                            self.assertEqual(t.cooling_history.unknown_reason, 'earlier thermal history unknown')
                            self.assertEqual(restored.thermal_owner, 'column-isostasy')
                            self.assertEqual(t.geometry_reference_id, 'reference-surface')
                            self.assertEqual(t.thinning_source_id, 'fixture')
                            self.assertEqual(restored.reference_material_mass_kg, checkpoint.state.reference_material_mass_kg)
                            self.assertEqual(restored.trajectory_depth_bounds_m, checkpoint.state.trajectory_depth_bounds_m)
                            means, heat = independent_reference(plan.initial_state, t.elapsed_s, t.depth_edges_m)
                            np.testing.assert_allclose(t.mean_temperature_k, means, rtol=0., atol=1e-5)
                            np.testing.assert_allclose(t.outward_heat_j_m2, heat, rtol=1e-10, atol=.03)
                            self.assertAlmostEqual(restored.represented_water_m3+restored.water_remaining_m3,
                                                   policy.water_stock_m3, delta=1e-9)
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                           PYTHONPATH=os.pathsep.join((str(ROOT/'src'), str(ROOT/'tests'))))
                env.update({key: '1' for key in THREAD_VARIABLES})
                result = subprocess.run([sys.executable, '-B', '-c', script, route, str(path)],
                    env=env, cwd=tmp, capture_output=True, text=True, timeout=120, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                cold = json.loads(result.stdout)
                self.assertEqual(cold['prior'], prior)
                self.assertEqual(cold['final'], expected)
                self.assertEqual(cold['reserved'], 0)
            self.assertEqual(owner.reserved_bytes, 0)

    def test_atomic_publication_and_finite_stock_refusal_preserve_accepted_outputs(self):
        for route in ('constant', 'margin'):
            owner = WorkBudget(CASE['work_budget_bytes'])
            with self.subTest(route=route), TemporaryDirectory() as tmp, owner.reserve(CALLER_ALLOWANCE):
                path = Path(tmp)/'atomic.db'
                with route_fixture(route, budget=owner) as (plan, policy, times):
                    with open_store(path, owner, InterruptingStore) as store, PreparedW06Workflow(
                            plan, times, margin_policy=policy, store=store) as workflow:
                        accepted = workflow.run(through=1)
                        before, retained = store.statistics(), owner.reserved_bytes
                        store.fail = True
                        with self.assertRaises(CancelledError):
                            workflow.run(through=2)
                        self.assertFalse(store.contains(workflow.checkpoint_id(2)))
                        self.equal(workflow._current, accepted)
                        self.assertEqual(owner.reserved_bytes, retained)
                        for key in ('unique_chunks', 'encoded_payload_bytes', 'snapshots'):
                            self.assertEqual(store.statistics()[key], before[key])
                with route_fixture(route, budget=owner) as (plan, policy, times), open_store(path, owner) as store:
                    with PreparedW06Workflow(plan, times, margin_policy=policy, store=store) as resumed, \
                            PreparedW06Workflow(plan, times, margin_policy=policy) as direct:
                        self.equal(resumed.run(), direct.run())
            self.assertEqual(owner.reserved_bytes, 0)
        owner = WorkBudget(CASE['work_budget_bytes'])
        parameters = replace(cooling_parameters(), birth_enthalpy_stock_j=3e20)
        with TemporaryDirectory() as tmp, route_fixture('history', budget=owner, parameters=parameters) as (plan, _, times):
            with open_store(Path(tmp)/'stock.db', owner) as store, PreparedW06Workflow(plan, times, store=store) as workflow:
                accepted = workflow.run(through=2)
                retained = owner.reserved_bytes
                with self.assertRaises(TectonicsError):
                    workflow.run()
                self.equal(workflow.load(2), accepted)
                self.assertEqual(store.statistics()['snapshots'], 3)
                self.assertEqual(owner.reserved_bytes, retained)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_corruption_missing_history_and_consistently_rehashed_foreign_state_refuse(self):
        for route in ROUTES:
            for corruption in ('chunk', 'missing', 'foreign_state', 'reset_count'):
                if route == 'margin' and corruption == 'reset_count':
                    continue
                owner = WorkBudget(CASE['work_budget_bytes'])
                with self.subTest(route=route, corruption=corruption), TemporaryDirectory() as tmp:
                    with route_fixture(route, budget=owner) as (plan, policy, times), open_store(Path(tmp)/'bad.db', owner) as store:
                        with PreparedW06Workflow(plan, times, margin_policy=policy, store=store) as workflow:
                            output = workflow.run(through=1)
                            if corruption == 'chunk':
                                store._db.execute('UPDATE chunks SET payload=?', (b'corrupt',))
                            elif corruption == 'missing':
                                store._db.execute('DELETE FROM snapshots WHERE id=?', (workflow.checkpoint_id(0),))
                            else:
                                key, value = ('thermal_state_id', '0'*64) if corruption == 'foreign_state' else ('intervals', 0)
                                rehash_manifest(store, output.checkpoint_id,
                                    lambda metadata: metadata['payload'].__setitem__(key, value))
                            with self.assertRaises((StoreError, TectonicsError)):
                                workflow.run()
                            self.assertFalse(store.contains(workflow.checkpoint_id(2)))
                self.assertEqual(owner.reserved_bytes, 0)

    def test_changed_recipe_schedule_and_margin_policy_cannot_reuse_wrong_state(self):
        for route in ROUTES:
            owner = WorkBudget(CASE['work_budget_bytes'])
            with self.subTest(route=route), TemporaryDirectory() as tmp, open_store(Path(tmp)/'binding.db', owner) as store:
                with route_fixture(route, budget=owner) as (plan, policy, times):
                    with PreparedW06Workflow(plan, times, margin_policy=policy, store=store) as original:
                        accepted = original.run(through=0)
                        changed_times = times[:-1]+(times[-1]+YEAR,)
                        with PreparedW06Workflow(plan, changed_times, margin_policy=policy, store=store) as changed:
                            self.assertNotEqual(changed.checkpoint_id(0), accepted.checkpoint_id)
                            self.assertIsNone(changed.load(0))
                        if route == 'margin':
                            for alternate in (replace(policy, water_source_id='other-water'),
                                              replace(policy, initial_depth_m=2100.),
                                              replace(policy, source_id='other-policy-source')):
                                with PreparedW06Workflow(plan, times, margin_policy=alternate, store=store) as changed:
                                    self.assertNotEqual(changed.plan_id, original.plan_id)
                                    self.assertIsNone(changed.load(0))
                if route == 'constant':
                    changes = [dict(parameters=replace(cooling_parameters(), water_source_id='other-reservoir'))]
                elif route == 'history':
                    events = case_events(HISTORY)
                    changes = [dict(events=(events[0], dict(events[1], source_id='changed-future-event-source')))]
                else:
                    changes = [dict(source=margin_source(temperature_shift_k=1.)),
                               dict(source=margin_source(unknown_reason='different explicit unknown history'))]
                for arguments in changes:
                    with route_fixture(route, budget=owner, **arguments) as (plan, policy, times):
                        with PreparedW06Workflow(plan, times, margin_policy=policy, store=store) as changed:
                            self.assertNotEqual(changed.checkpoint_id(0), accepted.checkpoint_id)
                            self.assertIsNone(changed.load(0))
            self.assertEqual(owner.reserved_bytes, 0)

    def test_schedules_cumulative_256_bound_resources_and_borrowed_lifetimes(self):
        event = Event(); event.set()
        for route in ROUTES:
            owner = WorkBudget(CASE['work_budget_bytes'])
            with self.subTest(route=route), route_fixture(route, budget=owner) as (plan, policy, times):
                origin = times[0]
                for schedule in ((), (origin, origin), (origin-1.,), (origin+2., origin+1.),
                                 (float('nan'),), tuple(origin+i*YEAR for i in range(257))):
                    with self.assertRaises(TectonicsError):
                        PreparedW06Workflow(plan, schedule, margin_policy=policy)
                with PreparedW06Workflow(plan, tuple(origin+i*YEAR for i in range(256)), margin_policy=policy) as bounded:
                    self.assertEqual(len(bounded.output_times_s), 256)
                retained = owner.reserved_bytes
                with self.assertRaises(MemoryLimitError):
                    PreparedW06Workflow(plan, times, margin_policy=policy, budget=WorkBudget(1, parent=owner))
                self.assertEqual(owner.reserved_bytes, retained)
                with self.assertRaises(TectonicsError):
                    PreparedW06Workflow(plan, times, margin_policy=policy, budget=WorkBudget(CASE['work_budget_bytes']))
                with self.assertRaises(CancelledError):
                    PreparedW06Workflow(plan, times, margin_policy=policy, cancel=event)
                with self.assertRaises(TectonicsError):
                    PreparedW06Workflow(plan, times, margin_policy=None if route == 'margin' else margin_policy(margin_source()))
                with PreparedW06Workflow(plan, times, margin_policy=policy) as workflow:
                    for index in (-1, len(times), True):
                        with self.assertRaises(TectonicsError):
                            workflow.run(through=index)
                    with self.assertRaises(CancelledError):
                        workflow.run(cancel=event)
                    workflow.run(through=1)
                    with self.assertRaises(TectonicsError):
                        workflow.run(through=0)
                with self.assertRaises(TectonicsError):
                    workflow.run()
                # Closing only the wrapper must leave its borrowed route usable.
                if route == 'margin':
                    plan.support(time_s=times[1], epoch_id=plan.initial_state.case.epoch_id, **policy.arguments())
                else:
                    plan.advance(plan.initial, time_s=times[1])
            self.assertEqual(owner.reserved_bytes, 0)

    def test_mid_advance_cancellation_and_bounded_restore_keep_accepted_state(self):
        for route in ('history', 'margin'):
            owner = WorkBudget(CASE['work_budget_bytes'])
            with self.subTest(route=route), TemporaryDirectory() as tmp, owner.reserve(CALLER_ALLOWANCE):
                path = Path(tmp)/'cancel.db'
                with route_fixture(route, budget=owner) as (plan, policy, times), open_store(path, owner) as store:
                    with PreparedW06Workflow(plan, times, margin_policy=policy, store=store) as workflow:
                        accepted = workflow.run(through=1)
                        retained, event, observed = owner.reserved_bytes, Event(), []
                        target = ('atlas_tectonics.margin_cooling', '_images') if route == 'margin' else (
                                  'atlas_tectonics.spreading_history_cooling', '_values')
                        def profile(frame, kind, arg):
                            if kind == 'call' and (frame.f_globals.get('__name__'), frame.f_code.co_name) == target:
                                observed.append(owner.reserved_bytes)
                                event.set()
                        previous = sys.getprofile()
                        try:
                            sys.setprofile(profile)
                            with self.assertRaises(CancelledError):
                                workflow.run(through=2, cancel=event)
                        finally:
                            sys.setprofile(previous)
                        self.assertTrue(observed, 'cancellation must occur during actual thermal work')
                        self.equal(workflow._current, accepted)
                        self.assertEqual(owner.reserved_bytes, retained)
                        self.assertEqual(store.statistics()['snapshots'], 2)
                        self.equal(workflow.load(1), accepted)
                with route_fixture(route, budget=owner) as (plan, policy, times), open_store(
                        path, owner, limits=replace(LIMITS, max_array_bytes=8)) as store:
                    with PreparedW06Workflow(plan, times, margin_policy=policy, store=store) as workflow:
                        with self.assertRaises(StoreError):
                            workflow.load(1)
                with route_fixture(route, budget=owner) as (plan, policy, times), open_store(path, owner) as store:
                    with PreparedW06Workflow(plan, times, margin_policy=policy, store=store) as workflow:
                        self.equal(workflow.load(1), accepted)
            self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
