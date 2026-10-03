"""I03a-2: histories with migrating junctions through the I02 ledger and clock, and I03a's v1 records. WORKING NON-CANON.

Round 1 of the coordinator's verification (3 October 2026) found two test gaps: the fresh-process continuation of a
history with migrating junctions was tested only through descriptors, not through Ledger.open and the clock; and no
test showed that I03a's v1 records are refused rather than misread. Values come from cases/i03_controls_v2.json.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import integration_clock as K, integration_ledger as L, integration_sphere as S
from atlas_tectonics import integration_transfer as T
from atlas_tectonics._validation import TectonicsError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i02_workflow_fixtures as F2
import i03_fixtures as F
import test_i03_junctions as J

SRC = str(Path(atlas_tectonics.__file__).resolve().parents[1])
STEPS = F.control('clock_commit')['column_steps']
FIX = {}


def setUpModule():
    with threadpool_limits(limits=1, user_api='blas'):
        FIX['prepared'] = F2.preparation()


def advance(clock, **request):
    return clock.advance(deadline=time.perf_counter()+F.CASE['resources']['clock_deadline_s'], **request)


CONTINUE = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import i02_workflow_fixtures as F2
import i03_fixtures as F
import test_i03_junctions as J
from atlas_tectonics import integration_clock as K, integration_ledger as L
store = F2.store(sys.argv[2])
ledger = L.Ledger.open(store, sys.argv[3], source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
head = ledger.verify_chain()
start, steps = head.accepted_steps, int(sys.argv[4])
moves = tuple(J.north_motion(k) for k in range(start, start+steps))
outcome = K.Clock(ledger).advance(steps=steps, transfers=moves,
                                  deadline=time.perf_counter()+F.CASE['resources']['clock_deadline_s'])
state = ledger.sphere(outcome.head)
print(outcome.status, outcome.head.accepted_steps, state.state_id, len(ledger.chain()))
store.close()
'''


class LedgerContinuationTests(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)

    def ledger(self, path):
        store = F2.store(path)
        self.addCleanup(store.close)
        sphere = F.crust(J.rotating_north(epoch=F2.EPOCH, start=F2.START))
        ledger, _ = L.Ledger.create(store, F2.root(STEPS, prepared=FIX['prepared']), sphere=sphere)
        return store, ledger

    def run_steps(self, ledger, first, count):
        outcome = advance(K.Clock(ledger), steps=count, transfers=tuple(J.north_motion(k)
                                                                        for k in range(first, first+count)))
        self.assertIn(outcome.status, (K.COMPLETED, K.HISTORY_COMPLETE), outcome.reason)
        return outcome

    def test_migrating_junctions_saved_and_continued_by_the_clock_in_a_new_process(self):
        rule = J.control('ledger_continuation')
        whole, saved = rule['uninterrupted_steps'], rule['saved_after_steps']
        _, uninterrupted = self.ledger(self.folder/'whole'/'ledger.sqlite')
        final = uninterrupted.sphere(self.run_steps(uninterrupted, 0, whole).head)
        path = self.folder/'saved'/'ledger.sqlite'
        store, ledger = self.ledger(path)
        self.run_steps(ledger, 0, saved)
        store.close()
        env = dict(os.environ, PYTHONPATH=SRC)
        done = subprocess.run([sys.executable, '-B', '-c', CONTINUE, str(HERE), str(path), ledger.ledger_id,
                               str(whole-saved)], capture_output=True, text=True, env=env,
                              timeout=F.CASE['resources']['child_timeout_s'])
        self.assertEqual(done.returncode, 0, done.stderr)
        status, steps, state_id, commits = done.stdout.split()
        self.assertEqual((status, int(steps), int(commits)), (K.COMPLETED, whole, whole+1))
        self.assertEqual(state_id, final.state_id)                       # exactly the uninterrupted state
        again_store = F2.store(path)
        self.addCleanup(again_store.close)
        again = L.Ledger.open(again_store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        chain = again.chain()
        self.assertEqual(again.verify_chain().key, chain[-1].key)
        self.assertEqual(again.sphere(chain[-1]).state_id, final.state_id)


class VersionOneTests(unittest.TestCase):
    def test_i03a_v1_records_are_refused_not_misread(self):
        state = F.crust(F.three_plates())
        step = T.advance(state, F.one_plate_motion(.5), end_time_s=F.MYR_S)
        after = step.state

        def v1(record, *path):
            record = json.loads(json.dumps(record))
            node = record
            for key in path:
                node = node[key]
            node['schema'] = node['schema'].rsplit('.v', 1)[0] + '.v1'
            return record
        for path in ((), ('network',), ('material',)):
            with self.subTest(record='state' + ''.join('/'+key for key in path)):
                with self.assertRaises(TectonicsError) as caught:
                    S.restore_sphere(v1(after.descriptor(), *path), after.arrays())
                self.assertIn('schema', str(caught.exception))
        with self.assertRaises(TectonicsError):
            S.restore_network(v1(after.network.descriptor()), after.network.arrays())
        with self.assertRaises(TectonicsError):
            T.restored(state, {'sphere': v1(step.record()), 'transfers': []}, step.arrays())
        old_step = json.loads(json.dumps(step.record()))
        old_step['schema'] = old_step['schema'].rsplit('.v', 1)[0] + '.v2'
        with self.assertRaises(TectonicsError):
            T.restored(state, {'sphere': old_step, 'transfers': []}, step.arrays())
        self.assertEqual(S.restore_sphere(after.descriptor(), after.arrays()).state_id, after.state_id)


if __name__ == '__main__':
    unittest.main()
