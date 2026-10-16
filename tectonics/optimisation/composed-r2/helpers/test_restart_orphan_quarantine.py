"""Runner hook for decision 4: resuming after a failed interval attempt quarantines
the orphaned candidate (logged rename, never delete) and the next interval begins."""
import contextlib
import gc
import io
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from concurrent.futures import CancelledError
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPACT = HERE / 'compact-geometry-r1'
RUNTIME = HERE.parent / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

import numpy as np
from atlas_tectonics.resources import WorkBudget
from compact_restart_store import CompactRestartStore
from content_cache import create_retained_scope


def key(text):
    return sha256(text.encode()).hexdigest()


class RestartQuarantineTests(unittest.TestCase):
    def setUp(self):
        temporary_root = HERE.parents[3] / '_t'
        temporary_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='w1-restart-', dir=temporary_root)
        self.root = Path(self.temp.name)
        self.budget = WorkBudget(768 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='w1-restart-tests')
        self.store = CompactRestartStore.create_migration(self.root / 'catalog.json',
            workflow_id=key('workflow'), scope=self.scope, producer_identity=key('producer'),
            runtime_identity=key('runtime'))
        self.others = []

    def tearDown(self):
        for store in self.others:
            store.close()
        self.store.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        for path in self.root.iterdir():
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.temp.cleanup()

    def test_resume_after_failed_attempt_quarantines_and_begins(self):
        first = key('first')
        self.store.put(first, {'values': np.arange(9000, dtype='<i8')}, {'sequence': 0})
        self.store.seal_and_promote(first)
        # A failed attempt: the successor candidate is cancelled mid-write.
        failed = self.store.begin_interval(producer_identity=key('p2'), runtime_identity=key('runtime'))
        token = threading.Event()
        token.set()
        with self.assertRaises((CancelledError, InterruptedError)):
            failed.put(key('half'), {'values': np.arange(10, dtype='<i8')}, {'sequence': 1}, cancel=token)
        failed.candidate.close()
        failed.close()
        self.store.close()
        # Fresh resume: without the reason the orphan still refuses, as before.
        self.store = CompactRestartStore.open_catalog(self.root / 'catalog.json', scope=self.scope)
        orphan = self.root / 'interval-0001.sqlite'
        self.assertTrue(orphan.exists())
        digest = sha256(orphan.read_bytes()).hexdigest()
        with self.assertRaises(FileExistsError):
            self.store.begin_interval(producer_identity=key('p2'), runtime_identity=key('runtime'))
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            successor = self.store.begin_interval(producer_identity=key('p2'), runtime_identity=key('runtime'),
                                                  resume_after_failure='resume after failed interval 1')
        self.others.append(successor)
        self.assertIn('quarantined orphaned interval candidate', log.getvalue())
        line = next(text for text in log.getvalue().splitlines() if text.startswith('compact restart:'))
        record = json.loads(line.split(': ', 2)[2])
        self.assertEqual(record['reason'], 'resume after failed interval 1')
        moved = [row for row in record['files'] if row['original'] == 'interval-0001.sqlite']
        self.assertEqual(moved[0]['sha256'], digest)
        self.assertEqual(sha256((self.root / moved[0]['quarantined']).read_bytes()).hexdigest(), digest)
        second = key('second')
        successor.put(second, {'values': successor.reference(first, 'values')}, {'sequence': 1})
        entry = successor.seal_and_promote(second)
        self.assertEqual(entry.interval, 1)

    def test_resume_with_nothing_orphaned_is_silent_and_start_next_interval_hook(self):
        first = key('first')
        self.store.put(first, {'values': np.arange(100, dtype='<i8')}, {'sequence': 0})
        self.store.seal_and_promote(first)
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            self.assertIs(self.store.start_next_interval(producer_identity=key('p2'), runtime_identity=key('runtime'),
                                                         resume_after_failure='resume'), self.store)
        self.assertEqual(log.getvalue(), '')
        self.assertEqual(list(self.root.glob('*.quarantined-*')), [])


if __name__ == '__main__':
    unittest.main()
