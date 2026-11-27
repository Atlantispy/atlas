"""A reuse difference is a miss, never a refusal (REUSE-MISS-NOT-REFUSAL-PLAN-r1): each reader entry point prints the
same miss line, returns REUSE_MISS_EXIT and writes nothing at the reader's paths, so the ordinary reader that follows
the recomputed producer finds them free (review C-1)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atlas_tectonics._private.integration import reopen_fresh_restart as R
from atlas_tectonics._private.integration import reuse_previous_run as REUSE

PIN = '0'*64


class _Profile:
    sha256 = '1'*64

    def __init__(self, folder):
        self._row = {'output_directory': folder, 'store_directory': str(Path(folder)/'store')}

    def record(self):
        return dict(self._row)


class ReuseMissEntryPoints(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.profile = _Profile(folder.name)
        self.reader = R.reader_output(self.profile.record(), 'interval')
        self.reader.mkdir(parents=True)

    def reuse(self, miss):
        return {'previous': self.profile, 'execution_identity': '3'*64,
                'record': {'identity_override': False, 'miss': miss}}

    def call(self, entry, plan_miss=None, producer_miss=None):
        reuse = self.reuse(plan_miss)

        def producer(*_, reuse, **__):
            reuse['record']['miss'] = producer_miss
        out = io.StringIO()
        with mock.patch.object(R.F, 'FreshSources', lambda profile: object()), \
                mock.patch.object(R, '_recording', lambda *a: None), \
                mock.patch.object(R.sys, 'dont_write_bytecode', True), \
                mock.patch.object(R.REUSE, 'plan', lambda *a, **k: reuse), \
                mock.patch.object(R, '_producer_inputs_retry', producer), \
                mock.patch.object(R.OR, 'read_json', lambda *a, **k: ({}, PIN)), \
                contextlib.redirect_stdout(out):
            code = entry()
        return code, json.loads(out.getvalue())

    def entries(self):
        common = dict(mode='interval', producer_receipt_sha256=PIN, reuse_previous=('previous.json', PIN, False),
                      _previous=self.profile)   # _reader_admission (reopen_fresh_restart.py:844) reads no file
        return {'command': lambda: R.command(self.profile, 'python', **common),
                'workload': lambda: R._workload(self.profile, **common),
                'finalise': lambda: R.finalise(self.profile, reopen_receipt_sha256=PIN, guard_receipt_sha256=PIN,
                                               guard_control_sha256=PIN, **common)}

    def assert_miss(self, code, line, reason):
        self.assertEqual(code, REUSE.REUSE_MISS_EXIT)   # kills a mutant that treats the miss as success (0)
        self.assertEqual(line['status'], REUSE.MISS_STATUS)
        self.assertEqual(line['message'], f"reuse miss: {reason}; this run's producer must run (recompute)")
        self.assertEqual(list(self.reader.iterdir()), [])   # C-1: the later ordinary reader finds its paths free

    def test_plan_miss_is_the_same_at_every_entry_point(self):
        reason = 'control case files differ: b.json'
        lines = []
        for name, entry in self.entries().items():
            with self.subTest(name):
                code, line = self.call(entry, plan_miss=reason)
                self.assert_miss(code, line, reason)
                lines.append(line)
        self.assertEqual(lines[0], lines[1])
        self.assertEqual(lines[0], lines[2])

    def test_producer_miss_at_command_and_finalise(self):
        reason = 'previous run has another execution identity'
        for name in ('command', 'finalise'):
            with self.subTest(name):
                code, line = self.call(self.entries()[name], producer_miss=reason)
                self.assert_miss(code, line, reason)


if __name__ == '__main__':
    unittest.main()
