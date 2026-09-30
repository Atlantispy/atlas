"""Regression coverage for real cold continuation and recovery from a rejected storage commit.

The stress root must meet the unchanged constitutive tolerance even where adjacent log-stress floats cannot
resolve it. Complete resumed histories are compared with uninterrupted physics; prepared operators are rebuilt,
not serialised, and no accepted prefix is replayed. WORKING NON-CANON.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from threadpoolctl import threadpool_limits

from atlas_tectonics import _integration_heat as H, _integration_motion as M
from atlas_tectonics import integration_clock as K, integration_evolution as E, integration_ledger as L
from atlas_tectonics import integration_state as I

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i02_workflow_fixtures as F

PARITY = F.POLICY['parity_relative']


def insulated(steps=16):
    base, _, key, inputs = F.preparation()
    inputs = copy.deepcopy(inputs)
    for prop, conductivity, production in zip(inputs['props'], (2.1, 2.9, 3.3, 4.), (1e-7, 0., 0., 0.)):
        prop.update(conductivity_w_m_k=conductivity, radiogenic_w_m3=production)
    inputs['boundaries'] = dict(top=dict(type='insulated'), bottom=dict(type='temperature', value_k=900.))
    thermal = H.prepare_thermal(base.layer, base.depth_m, base.weight, inputs['thicknesses'], inputs['props'],
                                inputs['densities'], inputs['boundaries'], mechanical_fingerprint=base.fingerprint)
    return F.root(steps, duration=F.DURATION, prepared=(base, thermal, key, inputs))


def values(state):
    column = state.column
    return dict(theta=column.theta_k.tolist(), kappa=column.kappa.tolist(),
                yields=column.yield_stage_counts.tolist(), stages=column.counters['stages'],
                accounts=column.accounts_j_m, stretch=column.stretch, displacement=column.displacement_m,
                clock=column.clock_s, path=column.log_path, quadrature=column.log_strain_quadrature,
                elapsed=column.elapsed_s, accepted=column.accepted_steps)


class RestartTests(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'ledger'/'ledger.sqlite'

    def ledger(self, root):
        store = F.store(self.path)
        self.addCleanup(store.close)
        ledger, _ = L.Ledger.create(store, root)
        return ledger

    def parity(self, actual, reference):
        for name in ('yields', 'stages', 'elapsed', 'accepted'):
            self.assertEqual(actual[name], reference[name], name)
        for name in ('theta', 'kappa', 'stretch', 'displacement', 'clock', 'path', 'quadrature'):
            a, b = np.asarray(actual[name]), np.asarray(reference[name])
            self.assertLessEqual(float(np.max(np.abs(a-b))), PARITY*max(float(np.max(np.abs(b))), 1e-300), name)
        self.assertEqual(set(actual['accounts']), set(reference['accounts']))
        for name, reference_value in reference['accounts'].items():
            self.assertLessEqual(abs(actual['accounts'][name]-reference_value),
                                 PARITY*max(abs(reference_value), 1e-300), name)

    def test_insulated_checkpoint_continues_in_a_fresh_process_at_both_schedules(self):
        script = r'''
import json, sys
from pathlib import Path
from threadpoolctl import threadpool_limits
sys.path.insert(0, sys.argv[1])
import test_i02_restart_regressions as T
from atlas_tectonics import integration_clock as K, integration_evolution as E, integration_ledger as L
with threadpool_limits(limits=1, user_api='blas'):
    store = T.F.store(Path(sys.argv[2]))
    ledger = L.Ledger.open(store, sys.argv[3], source_id=T.F.SOURCE_ID, runtime_id=T.F.RUNTIME_ID)
    verified = ledger.verify_chain().accepted_steps
    clock = K.Clock(ledger)
    calls, original = [], E.stage
    def counted(*args, **kwargs):
        calls.append(args[3])
        return original(*args, **kwargs)
    E.stage = counted
    result = clock.advance(steps=clock.state.remaining_steps)
    print(json.dumps(dict(status=result.status, verified=verified, calls=len(calls), values=T.values(clock.state))))
    store.close()
'''
        for steps, checkpoint in ((16, 5), (256, 128)):
            with self.subTest(steps=steps):
                root = insulated(steps)
                whole = I.Continuation(root).advance(root, steps)
                self.assertEqual(whole.status, I.HISTORY_COMPLETE)
                path = self.path.parent/str(steps)/'ledger.sqlite'
                with F.store(path) as store:
                    ledger, _ = L.Ledger.create(store, root)
                    clock = K.Clock(ledger)
                    self.assertEqual(clock.advance(steps=checkpoint).step, checkpoint)
                    ledger_id = ledger.ledger_id
                process = subprocess.run([sys.executable, '-B', '-c', script, str(HERE), str(path), ledger_id],
                                         capture_output=True, text=True, timeout=30,
                                         env=dict(os.environ, PYTHONPATH=str(HERE.parent/'src')))
                self.assertEqual(process.returncode, 0, process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual((result['status'], result['verified']), (K.HISTORY_COMPLETE, checkpoint))
                self.assertEqual(result['calls'], 1+2*(steps-checkpoint))  # only one cold balance; no prefix replay
                self.parity(result['values'], values(whole.state))

    def test_failed_commit_can_continue_from_its_accepted_head_after_storage_recovers(self):
        root = insulated()
        whole = I.Continuation(root).advance(root, 16)
        ledger = self.ledger(root)
        clock = K.Clock(ledger)
        clock.advance(steps=5)
        before = clock.head
        with mock.patch.object(L.Ledger, 'commit', side_effect=OSError('injected storage failure')):
            with self.assertRaises(OSError) as caught:
                clock.advance(steps=1)
        self.assertIn('after global step 5 up to 6 were not committed', '\n'.join(caught.exception.__notes__))
        self.assertEqual((clock.head.key, ledger.head().key), (before.key, before.key))
        outcome = clock.advance(steps=11)
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.HISTORY_COMPLETE, 11))
        self.parity(values(clock.state), values(whole.state))

    def test_compression_with_large_drag_has_the_same_complete_warm_and_cold_outcome(self):
        drive = M.Drive(-F.DRIVE.force_n_m, 100*F.DRIVE.drag_pa_s, F.DRIVE.width_m)
        root = F.root(16, duration=F.DURATION, drive=drive)
        run = I.Continuation(root)
        head = run.advance(root, 1).state
        warm = run.advance(head, 15)
        cold = I.Continuation(head).advance(head, 15)
        self.assertEqual((warm.status, warm.accepted_steps), (I.HISTORY_COMPLETE, 15))
        self.assertEqual((cold.status, cold.accepted_steps), (I.HISTORY_COMPLETE, 15))
        self.parity(values(cold.state), values(warm.state))

    def test_genuine_cold_failure_keeps_the_accepted_time_in_its_exception(self):
        ledger = self.ledger(F.root(16))
        original = K.Clock(ledger)
        original.advance(steps=5)
        clock = K.Clock(ledger)
        before = clock.head
        # Fail the first re-solved stage, before the request has computed a pending step. The numerical failure is
        # still raised, with the accepted-time record attached; it is not turned into a successful/refused outcome.
        with mock.patch.object(E, 'stage', side_effect=ValueError('injected constitutive failure')):
            with self.assertRaisesRegex(ValueError, 'injected constitutive failure') as caught:
                clock.advance(steps=1)
        self.assertEqual((clock.head.key, ledger.head().key), (before.key, before.key))
        notes = '\n'.join(caught.exception.__notes__)
        self.assertIn('last accepted global step is 5', notes)
        self.assertIn('%r s' % before.time_s, notes)
        self.assertIn(before.key, notes)


if __name__ == '__main__':
    unittest.main()
