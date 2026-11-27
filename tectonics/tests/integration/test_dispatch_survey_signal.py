"""Kept-worker monitoring in the parallel dispatch: the process survey and the completion signal (speed plan R-3)."""
import io
import tempfile
import threading
import unittest
from pathlib import Path

import psutil

from atlas_tectonics.integration.parallel import dispatch
from atlas_tectonics.integration.parallel.dispatch import _Child


class _Fake:
    """A scripted psutil.Process: live, dead, or a reused PID whose create time moved."""

    def __init__(self, pid, created, *, running=True, now=None, parent=None, kids=()):
        self.pid, self.created, self.running = pid, created, running
        self.now = created if now is None else now
        self._parent, self.kids = parent, list(kids)

    def is_running(self):
        return self.running

    def create_time(self):
        if not self.running:
            raise psutil.NoSuchProcess(self.pid)
        return self.now

    def status(self):
        return psutil.STATUS_RUNNING

    def children(self, recursive=False):
        if not self.running:
            raise psutil.NoSuchProcess(self.pid)
        return self.kids

    def parent(self):
        return self._parent


class DiscoverTest(unittest.TestCase):
    def test_live_dead_and_reused_entries(self):
        # T-R3a: owned live root with a new descendant, a foreign process under it, a dead and a reused entry.
        root = _Fake(10, 1.0)
        child = _Fake(11, 2.0, parent=root)
        grandchild = _Fake(14, 2.5, parent=child)
        foreign = _Fake(13, 3.0, parent=_Fake(99, 0.5))
        root.kids = [child, grandchild, foreign]
        dead = _Fake(20, 4.0, running=False)
        reused = _Fake(12, 5.0, now=9.0)
        with tempfile.TemporaryDirectory() as folder:
            owner = _Child(Path(folder), 60, 1 << 30)
            owner._owned = {(10, 1.0): root, (20, 4.0): dead, (12, 5.0): reused}
            live = owner._discover()
            self.assertEqual(live, [((10, 1.0), root), ((11, 2.0), child), ((14, 2.5), grandchild)])
            # A second call with nothing changed returns the same list.
            self.assertEqual(owner._discover(), live)
            # A live entry that has since died is dropped by the next call.
            child.running = grandchild.running = False
            self.assertEqual(owner._discover(), [((10, 1.0), root)])


class _Pipe(io.BytesIO):
    def __init__(self, on_write):
        super().__init__()
        self.on_write = on_write

    def write(self, data):
        self.on_write(data)
        return len(data)


class _Launched:
    def __init__(self, on_write):
        self.stdin, self.pid, self.returncode = _Pipe(on_write), 1, None

    def poll(self):
        return None


class SignalTest(unittest.TestCase):
    def serve(self, *, make_done, deadline):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        home, batch = Path(folder.name)/'worker', Path(folder.name)/'batch-0'
        home.mkdir()
        batch.mkdir()
        (batch/'binding.json').write_bytes(b'{}')
        (batch/'result.json').write_bytes(b'{"answer": 1}')
        worker = _Child(home, deadline, 1 << 40, interval=dispatch.SURVEY, kept=True)
        worker._worker_identity, worker.exited = (2, 1.0), True    # stop() returns at once

        def written(line):
            # The worker's completion line, with or without its done file.
            if make_done:
                (batch/'done').write_bytes(b'')
            worker._signals[line.rstrip(b'\n').decode('utf8')].set()
        worker.process = _Launched(written)
        worker._measure = lambda process: ([((2, 1.0), None)], False)
        return worker.serve(batch, b'{}'), worker

    def test_signal_with_done_finishes(self):
        result, worker = self.serve(make_done=True, deadline=60)
        self.assertEqual(result, b'{"answer": 1}')
        self.assertEqual(worker._signals, {})

    def test_signal_without_done_does_not_finish(self):
        # T-R3b: the signal alone never completes a batch; the deadline guard is reached instead.
        with self.assertRaisesRegex(RuntimeError, 'resource guard reached'):
            self.serve(make_done=False, deadline=0.3)

    def test_reader_sets_only_the_named_batch(self):
        worker = _Child(Path('.'), 60, 1 << 30, kept=True)
        named, other = threading.Event(), threading.Event()
        worker._signals = {'/b/batch-1': named, '/b/batch-2': other}
        worker._read_signals(io.BytesIO(b'numba says hello\n/b/batch-1\r\n'))
        self.assertTrue(named.is_set())
        self.assertFalse(other.is_set())


if __name__ == '__main__':
    unittest.main()
