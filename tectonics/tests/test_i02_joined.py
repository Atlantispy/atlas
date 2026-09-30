"""Focused I02.7 checks: the joined route against direct execution, and its bounded timing harness.

One existing nontrivial coupled case, the layered order-8 column with a signed initial departure and inherited
weakening history, over its 16 whole steps: the retained direct evolve, the stored workflow in chunks with
savepoints and exchanges attached, and a run saved half-way and continued by a fresh process. Fields AND every
carried and derived account are compared: bitwise where the numerical path is the same, within the retained warm/cold
parity after a cold reconstruction, with the retained conservation identities closing. The timing harness must check
that its modes compute the same history before it reports raw seconds.
SPDX-License-Identifier: AGPL-3.0-only
"""
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import integration_clock as K, integration_evolution as E, integration_ledger as L
from atlas_tectonics import integration_state as I

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent/'tools'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TOOLS))
import i02_workflow_fixtures as F
import check_i01_finite_strain as tfs

SRC = str(Path(atlas_tectonics.__file__).resolve().parents[1])
ENV = dict(os.environ, PYTHONPATH=SRC)
STEPS = 16
PARITY = F.POLICY['parity_relative']
DERIVED = ('surface_loss_j_m', 'basal_gain_j_m', 'motion_work_relative', 'drive_displacement_relative',
           'partition_relative', 'column_energy_relative', 'work_to_heat_relative', 'drag_excluded_relative',
           'energy_relative', 'absolute_energy_relative')
EXTENSIVE = I.STAGE_ACCOUNTS+I.THERMAL_ACCOUNTS+DERIVED[:2]
FIX = {}


def setUpModule():
    with threadpool_limits(limits=1, user_api='blas'):
        FIX['prepared'] = F.preparation()
        FIX['root'] = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)


def near(value, reference, relative=PARITY):
    value, reference = np.asarray(value, dtype=float), np.asarray(reference, dtype=float)
    return float(np.abs(value-reference).max()) <= relative*max(float(np.abs(reference).max()), 1e-300)


class Joined(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.path = self.folder/'ledger'/'ledger.sqlite'

    def direct(self, run):
        """The retained evolve of all 16 steps on the continuation's own prepared bytes: the direct solver."""
        r, root = run.runner, FIX['root']
        return E.evolve(r.base, r.thermal, F.LAW, root.column.initial_kappa, F.DRIVE, duration_s=r.dt*STEPS,
                        steps=STEPS, window=root.settings.window_mapping(), temperature_step_k=F.REP['max_temperature_step_k'],
                        fractions=(1., 1.), policy=F.POLICY, modes=r.modes, theta0=root.column.initial_theta_k,
                        inputs=FIX['prepared'][2])

    def assert_same_run(self, report, whole):
        """Bitwise: every retained scalar diagnostic, array, carried and derived account, conservation and stage."""
        for name in tfs.SCALARS:
            if name not in ('status', 'reason'):
                self.assertEqual(report[name], whole[name], name)
        for name in ('theta', 'theta0', 'kappa', 'kappa0', 'yielded'):
            np.testing.assert_array_equal(report[name], whole[name])
        self.assertEqual(set(report['accounts']), set(I.STAGE_ACCOUNTS+I.THERMAL_ACCOUNTS+DERIVED))
        for name in ('accounts', 'conservation', 'reference'):
            self.assertEqual(report[name], whole[name], name)
        for name in ('velocity_m_s', 'force', 'rate', 'msource', 'kdot'):
            np.testing.assert_array_equal(report['final'][name], whole['final'][name])


class JoinedRouteTests(Joined):
    def test_direct_workflow_and_chunked_runs_agree_bitwise_on_fields_and_accounts(self):
        store = F.store(self.path)
        self.addCleanup(store.close)
        ledger, root = L.Ledger.create(store, FIX['root'], exteriors=(('inflow', 'source'), ('outflow', 'sink')))
        clock = K.Clock(ledger)
        whole = self.direct(clock.continuation)
        self.assertEqual((whole['status'], whole['accepted_steps']), ('COMPLETE', STEPS))
        self.assertTrue(np.any(whole['theta0'] < 0) and np.any(whole['kappa'] > whole['kappa0']))  # nonzero history
        feed = L.Transfer(label='feed', producer='joined-check', donor='inflow', receiver='store-b',
                          component_mass_kg={'A': .5, 'B': .25}, enthalpy_j=-.75, basis=F.BASIS, start_step=4,
                          end_step=5)
        drain = L.Transfer(label='drain', producer='joined-check', donor='store-a', receiver='outflow',
                           component_mass_kg={'A': 1., 'B': 0.}, enthalpy_j=2., basis=F.BASIS, start_step=8,
                           end_step=9)
        outcomes = [clock.advance(steps=3), clock.advance(steps=5, savepoint_steps=2, transfers=(feed,)),
                    clock.advance(until_s=clock.time_at(12), transfers=(drain,)), clock.advance(steps=4)]
        self.assertEqual([o.status for o in outcomes], [K.COMPLETED]*3+[K.HISTORY_COMPLETE])
        final = ledger.state(ledger.head())
        self.assert_same_run(clock.continuation.report(final), whole)       # workflow and chunks = direct
        # The exchanges rode on the same accepted clock without touching the column physics.
        exchange = ledger.exchange(ledger.head())
        np.testing.assert_array_equal(exchange.inventory.component_mass_kg, [[4., 2.], [1.5, .75]])
        self.assertEqual(exchange.inventory.time_s, final.time_s)
        closure = exchange.closure()
        self.assertEqual(closure['component_residual_kg'], [0., 0.])
        self.assertLess(abs(closure['enthalpy_residual_j']), 1e-12)
        # One uninterrupted in-memory continuation piece is the same history too.
        single = I.Continuation(FIX['root'])
        self.assertEqual(single.advance(FIX['root'], STEPS).state.column.column_state_id, final.column.column_state_id)

    def test_saved_and_fresh_process_restored_run_agrees_within_parity(self):
        store = F.store(self.path)
        ledger, root = L.Ledger.create(store, FIX['root'], exteriors=(('inflow', 'source'), ('outflow', 'sink')))
        clock = K.Clock(ledger)
        whole = self.direct(clock.continuation)
        clock.advance(steps=STEPS//2, savepoint_steps=4)
        ledger_id = ledger.ledger_id
        store.close()
        script = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from threadpoolctl import threadpool_limits
import i02_workflow_fixtures as F
from atlas_tectonics import integration_clock as K, integration_ledger as L
with threadpool_limits(limits=1, user_api='blas'):
    store = F.store(Path(sys.argv[2]))
    ledger = L.Ledger.open(store, sys.argv[3], source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
    clock = K.Clock(ledger)
    outcome = clock.advance(steps=%d-clock.head.accepted_steps)
    report = clock.continuation.report(ledger.state(ledger.head()))
store.close()
print(json.dumps(dict(status=outcome.status, report={k: (v.tolist() if hasattr(v, 'tolist') else v)
                                                     for k, v in report.items() if k != 'final'})))
""" % STEPS
        done = subprocess.run([sys.executable, '-B', '-c', script, str(HERE), str(self.path), ledger_id],
                              capture_output=True, text=True, env=ENV, timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout.strip().splitlines()[-1])
        report = out['report']
        self.assertEqual((out['status'], report['accepted_steps'], report['stages']),
                         (K.HISTORY_COMPLETE, STEPS, whole['stages']))
        for name in ('stretch', 'log_strain', 'log_path', 'clock_s', 'displacement_m', 'velocity_end_m_s',
                     'mean_history_gain'):
            self.assertLess(abs(report[name]-whole[name]), PARITY*abs(whole[name]), name)
        for name in ('theta', 'kappa'):
            self.assertTrue(near(report[name], whole[name]), name)
        self.assertEqual(report['yielded'], whole['yielded'].tolist())
        self.assertTrue(near([report['accounts'][n] for n in EXTENSIVE], [whole['accounts'][n] for n in EXTENSIVE]))
        # The retained conservation identities close for the restored run as they do for the direct one.
        restored = dict(report, status='COMPLETE', theta=np.array(report['theta']), kappa=np.array(report['kappa']))
        self.assertTrue(tfs.closed(restored, F.POLICY))
        self.assertTrue(tfs.closed(dict(whole), F.POLICY))


class TimingHarnessTests(Joined):
    def test_the_harness_times_one_workload_only_after_checking_it_is_the_same(self):
        output = self.folder/'timing.json'
        done = subprocess.run([sys.executable, '-B', str(TOOLS/'measure_i02_workflow.py'), '--output', str(output),
                               '--repetitions', '2', '--savepoint-steps', '4'], capture_output=True, text=True,
                              env=ENV, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr)
        written = output.read_bytes()
        record = json.loads(written.decode('utf-8'))
        self.assertEqual(record['status'], 'MEASURED')
        self.assertTrue(all(record['checks'].values()))
        self.assertEqual(record['platform']['system'], platform.system())         # the running platform, named
        self.assertIn('one %s machine' % platform.system(), record['scope'])
        self.assertEqual((record['workload']['steps'], record['workload']['repetitions']), (STEPS, 2))
        for name in ('bare_cold_prepare_and_evolve', 'bare_warm_evolve', 'continuation_rebuild', 'continuation_steps',
                     'workflow_create', 'workflow_total', 'workflow_commits', 'reopen_open_root',
                     'reopen_head_restore', 'reopen_operator_rebuild', 'uninterrupted_remaining_steps'):
            mode = record['results'][name]
            self.assertEqual(len(mode['samples_s']), 2, name)
            self.assertTrue(all(sample > 0 for sample in mode['samples_s']), name)
            self.assertIsNotNone(mode['warm_median_s'], name)
        growth = record['growth'][-1]
        self.assertEqual((growth['snapshots'], growth['successor_commits']), (5, 4))
        self.assertLess(growth['root_array_bytes']+growth['successor_array_bytes'],
                        growth['whole_state_per_commit_bytes'])        # unchanged payloads are not duplicated
        self.assertIn('workflow_total_vs_bare_warm_percent', record['derived'])
        again = subprocess.run([sys.executable, '-B', str(TOOLS/'measure_i02_workflow.py'), '--output', str(output),
                                '--repetitions', '2'], capture_output=True, text=True, env=ENV, timeout=600)
        self.assertNotEqual(again.returncode, 0)                            # the harness never overwrites a result
        self.assertIn('already exists', again.stderr)
        self.assertEqual(output.read_bytes(), written)
        refused = self.folder/'refused.json'
        bad = subprocess.run([sys.executable, '-B', str(TOOLS/'measure_i02_workflow.py'), '--output', str(refused),
                              '--repetitions', '1'], capture_output=True, text=True, env=ENV, timeout=600)
        self.assertNotEqual(bad.returncode, 0)
        self.assertFalse(refused.exists())                                  # nothing is created for a refused request
        nowhere = self.folder/'missing'/'timing.json'
        lost = subprocess.run([sys.executable, '-B', str(TOOLS/'measure_i02_workflow.py'), '--output', str(nowhere),
                               '--repetitions', '2'], capture_output=True, text=True, env=ENV, timeout=600)
        self.assertNotEqual(lost.returncode, 0)                             # refused before measuring, not after
        self.assertIn('output folder does not exist', lost.stderr)

    def test_a_measurement_whose_modes_disagree_records_failed_equality(self):
        import measure_i02_workflow as harness
        evolve = E.evolve

        def shifted(*args, **kwargs):                                     # bare physics leaves the history ...
            out = evolve(*args, **kwargs)
            return dict(out, theta=out['theta']+1.)
        with mock.patch.object(E, 'evolve', shifted), mock.patch.object(harness, 'CHILD', 'raise SystemExit(3)'):
            record = harness.measure(2, 4)                                 # ... and the reopen child fails
        self.assertEqual((record['status'], record['results'], record['growth'], record['derived']),
                         ('FAILED_EQUALITY', None, None, None))
        self.assertFalse(record['checks']['bare_equals_continuation'] or record['checks']['reopened_within_parity'])
        self.assertTrue(record['checks']['workflow_equals_continuation'])
        self.assertIn('the reopen child failed', ' '.join(record['detail']))

    def test_a_run_that_fails_an_equality_check_withholds_every_timing(self):
        import measure_i02_workflow as harness
        timings = dict(bare_warm_evolve=dict(warm_median_s=1.), workflow_total=dict(warm_median_s=2.))
        record = harness._record(dict(bare_equals_continuation=False, reopened_within_parity=True), timings,
                                 [dict(database_bytes_final=2, database_bytes_after_root=1, successor_commits=1)],
                                 dict(steps=STEPS))
        self.assertEqual((record['status'], record['results'], record['growth'], record['derived']),
                         ('FAILED_EQUALITY', None, None, None))
        self.assertIn('withheld', record['withheld'])
        self.assertEqual(harness._record({}, timings, [], dict(steps=STEPS))['status'], 'FAILED_EQUALITY')
        with mock.patch.object(harness.platform, 'system', return_value='Linux'):     # named from the running one
            elsewhere = harness._record(dict(check=False), timings, [], dict(steps=STEPS))
        self.assertEqual(elsewhere['platform']['system'], 'Linux')
        self.assertIn('one Linux machine', elsewhere['scope'])
        self.assertNotIn('Windows', elsewhere['scope'])



class ConcurrentPollTests(Joined):
    """Status and inspection polls while an advance runs, as a UI would: on Windows a reader holding status.json
    blocks its replacement, and an open during a replacement is refused; neither may fail or stop the run, and full
    status reads take read-only snapshots of the ledger while the worker commits."""

    def test_tight_polls_and_held_status_files_never_fail_a_running_advance(self):
        import i02_column_workflow as W
        root, project = self.folder/'projects', '0123456789abcdef0123456789abcdef'
        root.mkdir()
        W.create(root, project)
        status = root/project/'status.json'
        results = []
        for mode in ('read', 'hold'):
            log = (self.folder/('worker-%s.out' % mode)).open('w+', encoding='utf-8')
            self.addCleanup(log.close)
            worker = subprocess.Popen([sys.executable, '-B', str(TOOLS/'i02_column_workflow.py'), 'advance', '--root',
                                       str(root), '--project', project, '--steps', '8', '--savepoint-steps', '1'],
                                      stdout=log, stderr=subprocess.STDOUT, text=True, env=ENV)
            polls = errors = full = 0
            while worker.poll() is None:
                if mode == 'read':
                    try:
                        W._status(root/project)
                        if polls % 20 == 0:                  # a full status: a read-only snapshot of the live ledger
                            full += W.status(root, project)['project']['head']['accepted_steps'] >= 0
                        polls += 1
                    except Exception:
                        errors += 1
                else:
                    try:
                        with status.open('rb'):
                            polls += 1
                            time.sleep(.2)
                    except OSError:
                        pass
                    time.sleep(.01)
            self.assertEqual(worker.wait(timeout=300), 0)
            log.seek(0)
            answer = json.loads(log.read().strip().splitlines()[-1])
            self.assertEqual(answer['status'], 'ok', answer)
            results.append((mode, polls, errors, answer['project']['run']['state']))
            if mode == 'read':
                self.assertGreater(full, 0)
        self.assertEqual([(mode, errors, state) for mode, _, errors, state in results],
                         [('read', 0, 'completed'), ('hold', 0, 'completed')])
        self.assertTrue(all(polls > 0 for _, polls, _, _ in results))
        self.assertEqual(W.status(root, project)['project']['head']['accepted_steps'], STEPS)

    def test_a_journal_vanishing_while_a_store_opens_is_absent_not_an_error(self):
        from unittest import mock
        path = self.folder/'store'/'ledger.sqlite'
        F.store(path).close()
        real = Path.lstat
        for error in (FileNotFoundError, PermissionError):
            def racing(self_, *args, **kwargs):
                if self_.name.endswith(('-journal', '-wal', '-shm')):
                    raise error(2, 'deleted by another connection just now')
                return real(self_, *args, **kwargs)
            with self.subTest(error=error.__name__), mock.patch.object(Path, 'lstat', racing):
                F.store(path).close()
            with self.subTest(error=error.__name__, target='database'):
                def denied(self_, *args, **kwargs):
                    if self_.name == 'ledger.sqlite':
                        raise PermissionError(13, 'denied')
                    return real(self_, *args, **kwargs)
                if error is PermissionError:
                    with mock.patch.object(Path, 'lstat', denied), self.assertRaises(PermissionError):
                        F.store(path)
        import stat
        import types

        def deleting(self_, *args, **kwargs):
            if self_.name.endswith('-journal'):    # caught mid-deletion: a regular file with no remaining link
                return types.SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_nlink=0, st_file_attributes=0)
            return real(self_, *args, **kwargs)
        with self.subTest(journal='no remaining link'), mock.patch.object(Path, 'lstat', deleting):
            F.store(path).close()                  # absent, not a hard-linked database


if __name__ == '__main__':
    unittest.main()
