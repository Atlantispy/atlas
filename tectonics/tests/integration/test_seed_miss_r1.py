"""A diagnostic seed failure is a miss, not a refusal (REUSE-MISS-SEED-ROUTE-PLAN-r1 and its S-1 addendum, review
conditions C-1 to C-3): run B starts unseeded, anchored to run A's records; the copy target is moved aside, never
deleted; a cancel and every non-diagnostic failure still refuse; interval 2's gate accepts only an anchored miss."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atlas_tectonics._private.integration import run_fresh_interval as F
from atlas_tectonics._private.integration.heat.continuation_guard import GuardAborted

R, V, A, X, RS, SS, PROFILE = ('%x' % n * 64 for n in range(1, 8))
VERDICT, ADOPTED = {'verdict': 'PASS'}, {'adopted': 0}


class _Stop(Exception):
    pass


class MoveAside(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.target = Path(folder.name)/F.MEASUREMENT_STORE

    def test_store_and_side_files_move_together(self):   # C-1; kills "sidecars left"
        self.target.write_bytes(b'store')
        Path(str(self.target)+'-wal').write_bytes(b'wal')
        moved = F._move_aside(self.target)
        self.assertEqual([Path(m['from']).name for m in moved], [F.MEASUREMENT_STORE, F.MEASUREMENT_STORE+'-wal'])
        self.assertEqual({Path(m['to']).name.split('.aside-')[1] for m in moved}.__len__(), 1)   # one stamp
        self.assertEqual(sorted(p.name for p in self.target.parent.iterdir()), sorted(Path(m['to']).name for m in moved))
        self.assertEqual(Path(moved[1]['to']).read_bytes(), b'wal')   # renamed, not deleted

    def test_a_taken_name_gets_a_counter(self):
        self.target.write_bytes(b'one')
        first = F._move_aside(self.target)
        self.target.write_bytes(b'two')
        with mock.patch.object(F.time, 'strftime', lambda *a: Path(first[0]['to']).name.split('.aside-')[1]):
            second = F._move_aside(self.target)
        self.assertTrue(second[0]['to'].endswith('-1'))
        self.assertEqual(Path(first[0]['to']).read_bytes(), b'one')

    def test_nothing_there_moves_nothing(self):
        self.assertEqual(F._move_aside(self.target), [])

    def test_a_failed_rename_puts_back_and_refuses(self):   # C-1: all or none
        self.target.write_bytes(b'store')
        Path(str(self.target)+'-journal').write_bytes(b'journal')
        real, calls = os.replace, []

        def replace(a, b):
            calls.append(a)
            if len(calls) == 2:
                raise OSError('locked')
            real(a, b)
        with mock.patch.object(F.os, 'replace', replace), self.assertRaises(F.FreshRefused):
            F._move_aside(self.target)
        self.assertEqual(sorted(p.name for p in self.target.parent.iterdir()),
                         [F.MEASUREMENT_STORE, F.MEASUREMENT_STORE+'-journal'])


class SeedFailure(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.target = Path(folder.name)/F.MEASUREMENT_STORE
        self.target.write_bytes(b'partial')
        self.seed = {'receipt_sha256': R, 'store_sha256': X}

    def failure(self, error, diagnostic, capture=lambda *a: (X, VERDICT, ADOPTED)):
        with mock.patch.object(F, '_root_capture', capture):
            return F._seed_failure(self.seed, error, diagnostic, self.target, receipt_path=Path('root/run.json'),
                                   store_directory='store', root_runner={})

    def test_diagnostic_failure_is_an_anchored_miss(self):
        record = self.failure(F.FreshRefused('store pin differs'), True)
        self.assertEqual(record['status'], F.SEED_MISS)
        self.assertEqual(record['miss']['message'], 'store pin differs')
        self.assertEqual(record['receipt'], {'path': str(Path('root/run.json')), 'sha256': R})
        self.assertEqual(record, {**record, **F._anchor(Path('root/run.json'), R, VERDICT, ADOPTED)})
        self.assertFalse(self.target.exists())   # kills "partial copy left"

    def test_unreadable_run_a_records_leave_no_anchor(self):
        def capture(*a):
            raise FileNotFoundError('verdict')
        record = self.failure(ValueError('x'), True, capture)
        self.assertEqual(record['status'], F.SEED_MISS)
        self.assertNotIn('verdict_sha256', record)
        self.assertEqual(record['anchor_missing']['type'], 'FileNotFoundError')

    def test_cancel_and_non_diagnostic_still_refuse(self):   # C-3
        for error, diagnostic in ((GuardAborted('guard'), True), (F.CancelledError(), True), (ValueError('x'), False)):
            with self.subTest(type(error).__name__, diagnostic=diagnostic):
                record = self.failure(error, diagnostic)
                self.assertEqual(record['status'], 'REFUSED_BEFORE_ADMISSION')
                self.assertTrue(self.target.exists())


class IntervalTwoGate(unittest.TestCase):
    def gate(self, diagnostic=True, recorded=None, **changes):
        reused = {'schema': F.SEED_SCHEMA, 'status': F.SEED_MISS, 'receipt': {'sha256': R},
                  'verdict_sha256': V, 'adopted_sha256': A}
        receipt = {'schema': F.RESULT_SCHEMA, 'mode': 'interval', 'interval': 1, 'profile_sha256': PROFILE,
                   'runner_record': {'sha256': RS}, 'sealed_awaiting_reader': {'sha256': SS},
                   'production_acceptance': False, 'final_reserved_bytes': 0,
                   'status': F.SEALED_STATUS['interval'], 'errors': [], 'reused_initial_cache': reused}
        for key, value in changes.items():
            (reused if key in reused or key == 'drop' else receipt)[key] = value
        reused.pop(reused.pop('drop', None), None)
        chain = [{'verdict': {'producer_receipt_sha256': R}, 'link': {'verdict_sha256': V, 'adopted_sha256': A}},
                 {'verdict': {'producer_receipt_sha256': X}, 'link': {'runner_sha256': RS, 'sealed_sha256': SS},
                  'adopted': {}}]
        with mock.patch.object(F.RUN, 'pinned_json', lambda *a: receipt):
            return F.root_anchor(chain, {'output': 'one', 'profile_sha256': PROFILE, 'diagnostic': diagnostic}, recorded)

    def test_anchored_miss_passes(self):
        self.assertIsNone(self.gate())

    def test_refusals(self):
        for name, kwargs in (('other verdict', {'verdict_sha256': X}),          # kills "anchor skipped"
                             ('no anchor', {'drop': 'adopted_sha256'}),
                             ('not diagnostic', {'diagnostic': False}),
                             ('interval 1 errors', {'errors': [{'type': 'E'}]})):   # C-2
            with self.subTest(name), self.assertRaises(F.FreshRefused):
                self.gate(**kwargs)


class SeedEnvironment(unittest.TestCase):
    def call(self, diagnostic):
        class Profile:
            def record(self):
                raise _Stop

        class Sources:
            profile = Profile()
        out = io.StringIO()
        with mock.patch.object(F, 'FreshProfile', Profile), mock.patch.object(F, 'FreshSources', Sources), \
                mock.patch.object(F, 'diagnostic_tree', lambda sources: diagnostic), \
                mock.patch.dict(F.os.environ, {F.SEED_ENVIRONMENT: 'anything'}), contextlib.redirect_stdout(out):
            F.run_fresh_interval(Sources.profile, sources=Sources(), guard=None, record={}, save=None, mode='interval')
        return out.getvalue()

    def test_diagnostic_tree_prints_and_carries_on(self):
        with self.assertRaises(_Stop):
            self.call(True)

    def test_other_trees_refuse(self):
        with self.assertRaises(F.FreshRefused):
            self.call(False)


if __name__ == '__main__':
    unittest.main()
