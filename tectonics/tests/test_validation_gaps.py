"""Independent validation-gap regressions; synthetic SI cases, WORKING NON-CANON.

Run with the existing declared scientific environment using -I -B. No existing TestCase is executed,
and no repository files are written. Existing fixtures construct typed inputs;
the new flexure oracle is independent of every production flexure kernel.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO/'tectonics/src'), str(REPO/'tectonics/tests')]

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics.evolving_flexure import PreparedEvolvingW04Support
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore
from atlas_tectonics.tectonic_history import PreparedTectonicHistory
from test_evolving_flexure import PERIODIC, datum, supplied
from test_tectonic_history import (SOURCE as HISTORY_SOURCE, make_history_case,
                                   open_store, result_arrays)
from test_w03_workflow import initialise, workflow_fixture
from test_w04_variable_workflow import ACCURACY, profile
from test_w04_workflow import surface

CAP = 128 << 20
EVIDENCE = {}


def periodic_step_load_oracle(pressure, length_m, rigidity_n_m, restoring_pa_m,
                              *, terms=2048):
    """Continuum cell-centre w for D*w''''+K*w=q with periodic stepwise q.

    qhat(n) is the exact integral over the pressure cells, not an FFT point-
    sample approximation: sinc(n/N)/N * sum(q_j*exp(-ik*x_j)). For n>=1,
    w=sum(2*Re[qhat(n)*exp(ik*x)]/(D*k**4+K)) + mean(q)/K.
    |qhat(n)|<=mean(abs(q)) gives the conservative omitted-mode bound below
    using sum(n>M, n^-4) <= 1/(3*M^3). It also bounds each sampled displacement.
    No Atlas flexure or transform kernel supplies the expected answer.
    """
    q = np.asarray(pressure, dtype=float)
    centres = (np.arange(len(q))+.5)*length_m/len(q)
    n = np.arange(1, terms+1, dtype=float)
    k = 2*np.pi*n/length_m
    phase = np.exp(1j*np.outer(k, centres))
    qhat = np.sinc(n/len(q))*(phase.conj()@q)/len(q)
    w = np.mean(q)/restoring_pa_m + 2*np.real(
        (qhat/(rigidity_n_m*k**4+restoring_pa_m))@phase)
    tail = (2*np.mean(np.abs(q))*length_m**4 /
            (3*rigidity_n_m*(2*np.pi)**4*terms**3))
    return w, float(tail)


class AfterCommitInterruption(RuntimeError):
    """The committed output exists, but the history has not adopted it."""


class AfterCommitStore(ArrayStore):
    fail_key = None

    def put(self, invocation, arrays, metadata=None, **kwargs):
        value = super().put(invocation, arrays, metadata, **kwargs)
        if invocation == self.fail_key:
            self.fail_key = None
            # This is after the real transaction returns, NOT publication_check.
            assert self.contains(invocation)
            raise AfterCommitInterruption('injected after committed store.put')
        return value


@contextmanager
def producer_calls(prepared):
    """Observe genuine solve/evaluate entries without altering guarded code."""
    function = prepared.solve if hasattr(prepared, 'solve') else prepared.evaluate
    code = function.__func__.__code__
    calls = []
    previous = sys.getprofile()
    if previous is not None:
        raise RuntimeError('Do not displace an existing profiler')

    def observe(frame, event, arg):
        if event == 'call' and frame.f_code is code and frame.f_locals.get('self') is prepared:
            calls.append(frame.f_locals.get('time_s', 'typed-mechanical-request'))

    sys.setprofile(observe)
    try:
        yield calls
    finally:
        sys.setprofile(previous)


class FocusedGapChecks(unittest.TestCase):
    def exact_output(self, actual, expected):
        self.assertIs(type(actual.result), type(expected.result))
        for name in ('index', 'time_s', 'output_id', 'checkpoint_id'):
            self.assertEqual(getattr(actual, name), getattr(expected, name), name)
        self.assertEqual(actual.descriptor(), expected.descriptor())
        self.assertEqual(actual.result.descriptor(), expected.result.descriptor())
        left, right = result_arrays(actual.result), result_arrays(expected.result)
        self.assertEqual(set(left), set(right))
        for name in left:
            self.assertEqual(left[name].shape, right[name].shape, name)
            self.assertEqual(left[name].dtype, right[name].dtype, name)
            self.assertEqual(left[name].tobytes(), right[name].tobytes(), name)
        if hasattr(actual.result, 'polygons'):
            self.assertEqual(tuple(p.geometry_id for p in actual.result.polygons),
                             tuple(p.geometry_id for p in expected.result.polygons))
        if hasattr(actual.result, 'reservoir_surface_known'):
            assert_array_equal(actual.result.reservoir_surface_known,
                               expected.result.reservoir_surface_known)

    def test_two_absolute_equilibria_against_independent_periodic_fourier_solution(self):
        owner = WorkBudget(CAP)
        reference = initialise(workflow_fixture(cells=8, length_m=8.))
        ref_surface = surface(reference)
        phase = 2*np.pi*(np.arange(8)+.5)/8
        q0 = 25.+100.*np.sin(phase)+35.*np.cos(2*phase)
        p0 = profile(reference, te=np.ones(8), far=False)
        p1 = profile(reference, te=np.full(8, 2.), far=False)
        # Compute the physical stiffness independently from declared properties.
        e, nu = PERIODIC.elastic.young_modulus_pa, PERIODIC.elastic.poisson_ratio
        d0, d1 = e/(12*(1-nu**2)), e*2.**3/(12*(1-nu**2))
        k = PERIODIC.elastic.density_contrast_kg_m3*PERIODIC.elastic.gravity_m_s2
        accuracy = replace(ACCURACY, relative_tolerance=1e-4,
                           absolute_displacement_m=1e-11)
        records = []
        with owner.reserve(8 << 20, category='independent-fourier-oracle'):
            w0, tail0 = periodic_step_load_oracle(q0, 8., d0, k)
            with PreparedEvolvingW04Support(reference, ref_surface, PERIODIC,
                    reference_rigidity=supplied(reference, p0),
                    reference_absolute_load=datum(reference, ref_surface, q0),
                    accuracy=accuracy, budget=owner) as plan:
                for label, extra in (
                        ('changed_stiffness_same_load', np.zeros(8)),
                        ('changed_stiffness_and_load', 15.+40.*np.cos(phase)+20.*np.sin(3*phase))):
                    with self.subTest(case=label):
                        result = plan.solve(reference, surface(reference, pressure=extra),
                                            rigidity=supplied(reference, p1))
                        w1, tail1 = periodic_step_load_oracle(q0+extra, 8., d1, k)
                        change = w1-w0
                        self.assertLess(tail0+tail1, 1e-11)
                        self.assertGreater(float(np.max(np.abs(change))), 1e-4)
                        assert_allclose(result.absolute_values[:, 2], w0, rtol=0., atol=1e-7)
                        assert_allclose(result.absolute_values[:, 3], w1, rtol=0., atol=1e-7)
                        assert_allclose(result.downward_displacement_from_reference_m,
                                        change, rtol=0., atol=1e-7)
                        assert_allclose(result.sediment_surface_change_m, -change, rtol=0., atol=1e-7)
                        assert_array_equal(result.downward_load_pa, extra)
                        assert_array_equal(result.absolute_values[:, :2], np.column_stack((q0, q0+extra)))
                        # Explicitly reject the tempting but physically wrong delta-load-only answer.
                        wrong, _ = periodic_step_load_oracle(extra, 8., d1, k)
                        self.assertGreater(float(np.max(np.abs(change-wrong))), 1e-4)
                        self.assertEqual(result.descriptor()['response'],
                                         'current-absolute-minus-reference-absolute')
                        records.append(dict(case=label, maximum_displacement_error_m=float(
                            np.max(np.abs(result.downward_displacement_from_reference_m-change))),
                            fourier_tail_bound_m=tail0+tail1, tolerance_m=1e-7,
                            reference_subdivisions=result.descriptor()['reference_subdivisions'],
                            current_subdivisions=result.descriptor()['current_subdivisions'],
                            execution_id=result.descriptor()['execution_id']))
        self.assertEqual(owner.reserved_bytes, 0)
        self.assertLessEqual(owner.peak_reserved_bytes, CAP)
        EVIDENCE['independent_flexure'] = dict(cases=records,
                                             accounted_peak_bytes=owner.peak_reserved_bytes)

    def test_postcommit_interruption_restores_exact_snapshot_without_repeating_physics(self):
        records = []
        for route in ('underthrust', 'w04', 'regional'):
            with self.subTest(route=route):
                owner = WorkBudget(CAP)
                prepared, inputs = make_history_case(route, budget=owner)
                with prepared, PreparedTectonicHistory(prepared, inputs, source_id=HISTORY_SOURCE) as control:
                    expected = tuple(control.run(through=i) for i in range(3))
                self.assertEqual(owner.reserved_bytes, 0)
                with TemporaryDirectory(prefix='atlas-gap-check-') as tmp:
                    path = Path(tmp)/'postcommit.db'
                    with open_store(path, owner, AfterCommitStore) as store:
                        prepared, inputs = make_history_case(route, budget=owner)
                        with prepared, PreparedTectonicHistory(prepared, inputs,
                                source_id=HISTORY_SOURCE, store=store) as interrupted:
                            self.exact_output(interrupted.run(through=0), expected[0])
                            retained_latest_before = interrupted._resource.statistics()['categories'][
                                'tectonic-history-latest']
                            store.fail_key = interrupted.checkpoint_id(1)
                            with producer_calls(prepared) as calls:
                                with self.assertRaises(AfterCommitInterruption):
                                    interrupted.run(through=1)
                            self.assertEqual(len(calls), 1)
                            self.assertTrue(store.contains(interrupted.checkpoint_id(1)))
                            self.assertEqual(store.statistics()['snapshots'], 2)
                            # The output was committed while adoption/statistics remain at index 0.
                            self.exact_output(interrupted._current, expected[0])
                            self.assertEqual(interrupted.statistics()['computed_outputs'], 1)
                            self.assertEqual(interrupted._resource.statistics()['categories'].get(
                                'tectonic-history-latest'), retained_latest_before)
                    self.assertEqual(owner.reserved_bytes, 0)
                    # Close/reopen both the store and producer: no warm object can hide replay.
                    with open_store(path, owner) as store:
                        prepared, inputs = make_history_case(route, budget=owner)
                        with prepared, PreparedTectonicHistory(prepared, inputs,
                                source_id=HISTORY_SOURCE, store=store) as restored:
                            with producer_calls(prepared) as recovery_calls:
                                latest = restored.run(through=1)
                            self.assertEqual(recovery_calls, [])
                            self.exact_output(latest, expected[1])
                            self.assertEqual(restored.statistics()['computed_outputs'], 0)
                            self.assertEqual(restored.statistics()['restored_outputs'], 1)
                            with producer_calls(prepared) as continuation_calls:
                                final = restored.run()
                            self.assertEqual(len(continuation_calls), 1)
                            self.exact_output(final, expected[2])
                            self.assertEqual(restored.statistics()['computed_outputs'], 1)
                            self.assertEqual(store.statistics()['snapshots'], 3)
                            with producer_calls(prepared) as warm_calls:
                                self.exact_output(restored.run(), expected[2])
                            self.assertEqual(warm_calls, [])
                            if route == 'underthrust':
                                # Supplied 7 N * 2 m and -3 N * 0 m; work is not paid twice.
                                assert_array_equal(latest.result.boundary_work_j, [7., 0.])
                                assert_array_equal(final.result.boundary_work_j, [14., 0.])
                            records.append(dict(route=route, committed_snapshots=3,
                                producer_calls_during_restore=0, producer_calls_to_complete=1,
                                producer_calls_for_warm_latest=0, exact_output_id=final.output_id,
                                restored_snapshot_id=latest.checkpoint_id,
                                accounted_peak_bytes=owner.peak_reserved_bytes))
                    self.assertEqual(owner.reserved_bytes, 0)
                    self.assertLessEqual(owner.peak_reserved_bytes, CAP)
        EVIDENCE['postcommit_recovery'] = records


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FocusedGapChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print('GAP_CHECK_EVIDENCE='+json.dumps(dict(success=result.wasSuccessful(),
        tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        evidence=EVIDENCE), sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)
