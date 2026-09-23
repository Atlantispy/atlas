"""Bounded assembled W01 witnesses; no Earth calibration or new physics.

These checks add cross-stage scenarios absent from the component suites. The
material transport case retains ownership of numerical comparison tolerances.
"""
from concurrent.futures import CancelledError
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import MaterialBoundary
from atlas_tectonics.regional_workflow import (
    PreparedRegionalWorkflow, load_regional_workflow, save_regional_workflow,
)
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import CachePolicy, cached_material_transport
from atlas_tectonics.storage import ArrayStore
from test_w01_regional_forcing import store_limits
from test_w01_workflow import (
    LEFT, RIGHT, cohort_values, spherical_fixture, workflow_fixture,
)


CASE = json.loads((Path(__file__).resolve().parents[1]/'cases/material_transport.json').read_text())
RTOL = CASE['tests']['relative_tolerance']
ATOL = CASE['tests']['absolute_tolerance']
ALWAYS = CachePolicy(mode='always')


def compare_fields_and_accounts(test, expected, actual):
    """Numerical equivalence is distinct from backend execution identities."""
    test.assertEqual(expected.material.cohorts, actual.material.cohorts)
    test.assertEqual(expected.material.time_s, actual.material.time_s)
    assert_allclose(actual.material.thickness_m, expected.material.thickness_m, rtol=RTOL, atol=ATOL)
    wanted = expected.material.transition_record['cohort_accounts_m2']
    found = actual.material.transition_record['cohort_accounts_m2']
    test.assertEqual(set(wanted), set(found))
    for cohort_id in wanted:
        keys = sorted(wanted[cohort_id])
        test.assertEqual(set(keys), set(found[cohort_id]))
        assert_allclose([found[cohort_id][key] for key in keys],
                        [wanted[cohort_id][key] for key in keys], rtol=RTOL, atol=ATOL)


class AssembledW01Acceptance(unittest.TestCase):
    def test_setup_outputs_remain_admitted_until_prepared_ownership_takes_over(self):
        from atlas_tectonics.precursor_sampling import PreparedPrecursor
        budget = WorkBudget(128 << 20)
        observed = []
        def observe(frame, event, value):
            if event == 'call' and frame.f_code is PreparedPrecursor.sample_cells.__code__:
                observed.append(budget.statistics()['categories'].get('workflow-setup-retained', 0))
        previous = sys.getprofile()
        try:
            sys.setprofile(observe)
            with PreparedRegionalWorkflow(*workflow_fixture(), budget=budget) as plan:
                plan.initialise()
                active = budget.statistics()['categories']
                self.assertEqual(active.get('workflow-setup-retained', 0), 0)
                self.assertGreater(active.get('workflow-prepared', 0), 0)
        finally:
            sys.setprofile(previous)
        self.assertEqual(len(observed), 1)
        self.assertGreater(observed[0], 0)
        self.assertGreater(budget.statistics()['category_peaks']['workflow-setup-retained'], 0)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_axial_spherical_transport_crosses_longitude_seam_and_restores_history(self):
        args = list(spherical_fixture(cells=2))
        args[2] = replace(args[2], start_direction=(-1., 1., 0.))
        # R=10, depth 0..2, solid angle pi/2: V=244*pi/3. The
        # reference metric is ds*10, so q=V/(5*pi*10)=122/75.
        q = 122./75.
        speed, duration, spacing, width = .1, .25, 2.5*math.pi, 10.
        courant = speed*duration/spacing
        left = MaterialBoundary('open', {'a': 2.*q}, 'spherical-exterior')
        with PreparedRegionalWorkflow(*args, scheme='upwind') as plan:
            start = plan.initialise()
            result = plan.advance(start, left=left, right=RIGHT)
        xyz = start.forcing.samples.positions_m
        self.assertAlmostEqual(math.atan2(xyz[0, 1], xyz[0, 0]), 3.*math.pi/4.)
        self.assertAlmostEqual(math.atan2(xyz[-1, 1], xyz[-1, 0]), -3.*math.pi/4.)
        assert_allclose(start.forcing.face_velocity_m_s, speed, rtol=RTOL, atol=ATOL)
        assert_allclose(cohort_values(result, 'a'), [q*(1.+courant), q], rtol=RTOL, atol=ATOL)
        account = result.material.transition_record['cohort_accounts_m2']['a']
        before = q*5.*math.pi
        inflow, outflow = 2.*q*speed*duration, q*speed*duration
        assert_allclose([account['solid_volume_per_width_before_m2'], account['inflow_m2'],
                         account['outflow_m2'], account['solid_volume_per_width_after_m2']],
                        [before, inflow, outflow, before+inflow-outflow], rtol=RTOL, atol=ATOL)
        self.assertGreater(inflow, outflow)
        self.assertAlmostEqual(before*width, 244.*math.pi/3.)
        assert_allclose(sum(cohort_values(result, 'a'))*spacing*width,
                        244.*math.pi/3.+(inflow-outflow)*width, rtol=RTOL, atol=ATOL)
        self.assertIs(result.initial_samples, start.initial_samples)
        self.assertEqual(result.initial_samples.state.case.time_s, 0.)
        self.assertEqual(result.material.time_s, duration)
        assert_array_equal(result.initial_samples.temperature(), [300., 300.])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'spherical.db'
            with ArrayStore(path, store_limits()) as store:
                save_regional_workflow(result, store)
            with ArrayStore(path, store_limits()) as store:
                restored = load_regional_workflow(store, result.workflow_id)
        self.assertEqual(restored.workflow_id, result.workflow_id)
        self.assertEqual(restored.execution_id, result.execution_id)
        self.assertEqual(restored.forcing.forcing_id, result.forcing.forcing_id)
        self.assertEqual(restored.initial_samples.state.descriptor(), args[0].descriptor())
        self.assertEqual(restored.parent.material.state_id, start.material.state_id)
        self.assertEqual(restored.material.transition_record, result.material.transition_record)
        self.assertEqual(restored.descriptor()['temperature_semantics'],
                         'initial-epoch only; not evolved heat or temperature')

    def test_nonuniform_muscl_native_and_reference_fields_and_accounts_agree(self):
        args = workflow_fixture(cells=6)
        results = []
        for backend in ('reference', 'numba'):
            with PreparedRegionalWorkflow(*args, scheme='muscl', backend=backend) as plan:
                initial = plan.initialise()
                result = plan.advance(initial, .125, left=LEFT, right=RIGHT)
            self.assertEqual(result.scheme, 'muscl')
            self.assertEqual(result.backend, backend)
            self.assertFalse(np.array_equal(initial.material.thickness_m, result.material.thickness_m))
            results.append(result)
        compare_fields_and_accounts(self, results[0], results[1])
        self.assertEqual(results[0].initial_samples.state.case.definition_id,
                         results[1].initial_samples.state.case.definition_id)

    def test_changed_exterior_and_interval_get_distinct_correct_cached_results(self):
        other_left = MaterialBoundary('open', {'a': 3., 'b': 1.}, 'different-exterior')
        requests = ((.125, LEFT), (.125, other_left), (.25, LEFT))
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'request-cache.db', store_limits()) as store, \
                 PreparedRegionalWorkflow(*workflow_fixture()) as plan:
                initial = plan.initialise()
                results = []
                for duration, left in requests:
                    expected = plan.advance(initial, duration, left=left, right=RIGHT)
                    actual = plan.advance(initial, duration, left=left, right=RIGHT,
                                          store=store, cache_policy=ALWAYS)
                    compare_fields_and_accounts(self, expected, actual)
                    self.assertEqual(actual.workflow_id, expected.workflow_id)
                    self.assertEqual(actual.material.transition_record['duration_s'], duration)
                    self.assertEqual(actual.material.transition_record['left']['reservoir_id'], left.reservoir_id)
                    results.append(actual)
                self.assertEqual(store.statistics()['snapshots'], len(requests))
                self.assertEqual(len({r.material.state_id for r in results}), len(requests))
                self.assertFalse(np.array_equal(results[0].material.thickness_m, results[1].material.thickness_m))
                self.assertFalse(np.array_equal(results[0].material.thickness_m, results[2].material.thickness_m))

    def test_changed_spherical_reference_width_preserves_physical_inventory_without_wrong_cache_hit(self):
        args = list(spherical_fixture())
        outputs = []
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'metric-cache.db', store_limits()) as store:
                for width in (10., 5.):
                    args[3] = replace(args[3], reference_width_m=width)
                    q = (122./75.)*(10./width)
                    left = MaterialBoundary('open', {'a': q}, 'same-physical-exterior')
                    with PreparedRegionalWorkflow(*args) as plan:
                        initial = plan.initialise()
                        expected = plan.advance(initial, left=left, right=RIGHT)
                        actual = plan.advance(initial, left=left, right=RIGHT,
                                              store=store, cache_policy=ALWAYS)
                    compare_fields_and_accounts(self, expected, actual)
                    assert_allclose(cohort_values(actual, 'a'), [q], rtol=RTOL, atol=ATOL)
                    assert_allclose(sum(cohort_values(actual, 'a'))*5.*math.pi*width,
                                    244.*math.pi/3., rtol=RTOL, atol=ATOL)
                    outputs.append(actual)
                self.assertEqual(store.statistics()['snapshots'], 2)
        self.assertNotEqual(outputs[0].material.state_id, outputs[1].material.state_id)
        self.assertNotEqual(outputs[0].forcing.forcing_id, outputs[1].forcing.forcing_id)
        self.assertEqual(outputs[0].initial_samples.state.state_id, outputs[1].initial_samples.state.state_id)

    def test_mid_advance_cancellation_preserves_saved_accepted_state_and_releases_work(self):
        budget, store_budget = WorkBudget(128 << 20), WorkBudget(128 << 20)
        token = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cancel-recovery.db'
            with ArrayStore(path, store_limits(), budget=store_budget) as store:
                with PreparedRegionalWorkflow(*workflow_fixture(duration=1.5), budget=budget) as plan:
                    accepted = plan.advance(plan.initialise(), .25, left=LEFT, right=RIGHT)
                    save_regional_workflow(accepted, store)
                    snapshots_before = store.statistics()['snapshots']
                    before = accepted.material.thickness_m.tobytes()
                    held = budget.reserved_bytes
                    completed = []
                    def cancel_after_first_completed_kernel(frame, event, value):
                        if event == 'return' and frame.f_code is cached_material_transport.__code__ and value is not None:
                            completed.append(value.state.state_id)
                            token.set()
                    previous = sys.getprofile()
                    try:
                        sys.setprofile(cancel_after_first_completed_kernel)
                        with self.assertRaises(CancelledError):
                            plan.advance(accepted, left=LEFT, right=RIGHT, store=store,
                                         cache_policy=ALWAYS, cancel=token)
                    finally:
                        sys.setprofile(previous)
                    self.assertEqual(len(completed), 1)
                    self.assertGreater(store.statistics()['snapshots'], snapshots_before)
                    self.assertEqual(accepted.material.thickness_m.tobytes(), before)
                    self.assertEqual(accepted.material.time_s, .25)
                    self.assertEqual(budget.reserved_bytes, held)
                self.assertEqual(budget.reserved_bytes, 0)
            self.assertEqual(store_budget.reserved_bytes, 0)
            with ArrayStore(path, store_limits(), budget=store_budget) as store:
                restored = load_regional_workflow(store, accepted.workflow_id)
            self.assertEqual(restored.workflow_id, accepted.workflow_id)
            self.assertEqual(restored.material.transition_record, accepted.material.transition_record)
            self.assertEqual(restored.material.thickness_m.tobytes(), before)
            token.clear()
            with PreparedRegionalWorkflow.from_state(restored, budget=budget) as plan:
                finished = plan.advance(restored, left=LEFT, right=RIGHT, cancel=token)
            self.assertEqual(finished.material.time_s, 1.5)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(store_budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
