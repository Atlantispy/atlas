"""Focused completed-diagnostic bundle acceptance and refusal fixtures."""
from concurrent.futures import CancelledError
import gc
from hashlib import sha256
import os
from pathlib import Path
import random
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / 'composed-r1/runtime-src'
sys.path[:0] = [str(HERE), str(RUNTIME)]

from atlas_tectonics.resources import WorkBudget
import cold_archive as A


class ColdArchiveTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ.get('WP10_ARCHIVE_TEST_ROOT',
            r'C:/Users/LOCAL_USER/Documents/Codex/2026-10-15/c-Users-LOCAL_USER-documents-codex-2026-2/work/wp10-results'))
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='tar-tests-', dir=scratch)
        self.root = Path(self.temp.name)
        self.scratch = scratch.resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.budget = WorkBudget(256 << 20)

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.assertEqual(self.root.resolve().parent, self.scratch)
        self.temp.cleanup()

    def compressible(self):
        names = ['diagnostics.json', 'rows.csv']
        (self.source/names[0]).write_bytes(b'{"completed":true,"residual":0,"status":"PASS"}\n'*24000)
        (self.source/names[1]).write_bytes(b'step,bytes,codec,status\n12,65536,raw,PASS\n'*16000)
        return names

    def finalise(self, names, destination=None, **kwargs):
        options = dict(kind='completed-diagnostics', budget=self.budget)
        options.update(kwargs)
        return A.finalise_completed_bundle(self.source, names, destination or self.root/'bundle', **options)

    def restore(self, destination, result, **kwargs):
        return A.restore_completed_bundle(self.root/'bundle', destination,
            expected_receipt_sha256=result['receipt_sha256'], budget=self.budget, **kwargs)

    def hashes(self, root, names):
        return {name: sha256((root/name).read_bytes()).hexdigest() for name in names}

    def test_compressible_completed_files_choose_archive_and_restore_exactly(self):
        names = self.compressible()
        before = self.hashes(self.source, names)
        result = self.finalise(names)
        self.assertEqual(result['selected_format'], 'tar.zst')
        self.assertEqual(result['receipt_sha256'], sha256(Path(result['receipt_path']).read_bytes()).hexdigest())
        self.assertEqual(result['deliverable_bytes'], sum(p.stat().st_size for p in (self.root/'bundle').rglob('*') if p.is_file()))
        restored = self.root/'restored'
        restored_result = self.restore(restored, result)
        self.assertEqual(restored_result['status'], 'ok')
        self.assertEqual(self.hashes(restored, names), before)
        self.assertEqual(self.hashes(self.source, names), before)
        for key in ('peak_job_memory_used_bytes', 'peak_process_memory_used_bytes'):
            self.assertGreater(result['measurements'][key], 0)
            self.assertLessEqual(result['measurements'][key], 128 << 20)

    def test_entropy_chooses_plain_files_and_restore_stays_exact(self):
        names = ['diagnostics-a.bin', 'diagnostics-b.bin']
        random_source = random.Random(20261015)
        for name in names:
            (self.source/name).write_bytes(random_source.randbytes(1 << 20))
        before = self.hashes(self.source, names)
        result = self.finalise(names, kind='cold-export')
        self.assertEqual(result['selected_format'], 'directory')
        self.restore(self.root/'restored', result)
        self.assertEqual(self.hashes(self.root/'restored', names), before)
        self.assertEqual(self.hashes(self.source, names), before)

    def test_single_compressible_file_keeps_plain_format_and_restores(self):
        names = ['completed.json']
        (self.source/names[0]).write_bytes(b'{"completed":true,"status":"PASS"}\n'*4000)
        before = self.hashes(self.source, names)
        result = self.finalise(names)
        self.assertEqual(result['selected_format'], 'directory')
        self.restore(self.root/'restored', result)
        self.assertEqual(self.hashes(self.root/'restored', names), before)
        self.assertEqual(self.hashes(self.source, names), before)

    def test_traversal_absolute_and_windows_case_duplicates_refuse(self):
        (self.source/'safe.json').write_text('{"complete":true}', encoding='utf-8')
        for names in (['../safe.json'], ['..\\safe.json'], [str(self.source/'safe.json')],
                      ['safe.json', 'SAFE.JSON'], ['safe.json', 'safe.json']):
            with self.subTest(names=names), self.assertRaises((ValueError, RuntimeError, OSError)):
                self.finalise(names)
            gc.collect()
            self.assertEqual(self.budget.reserved_bytes, 0)
            self.assertFalse((self.root/'bundle').exists())

    def test_hardlinked_source_is_refused(self):
        source = self.source/'linked.json'
        source.write_text('{"complete":true}', encoding='utf-8')
        try:
            os.link(source, self.root/'outside-link.json')
        except OSError as error:
            self.skipTest(f'host denied hardlink fixture: {error}')
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            self.finalise(['linked.json'])
        self.assertFalse((self.root/'bundle').exists())

    def test_symlinked_source_is_refused(self):
        source = self.root/'outside.json'
        source.write_text('{"complete":true}', encoding='utf-8')
        try:
            (self.source/'linked.json').symlink_to(source)
        except OSError as error:
            self.skipTest(f'host denied symlink fixture: {error}')
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            self.finalise(['linked.json'])
        self.assertFalse((self.root/'bundle').exists())

    def test_existing_destinations_are_untouched(self):
        names = self.compressible()
        existing = self.root/'existing'
        existing.mkdir()
        (existing/'sentinel').write_bytes(b'preserve')
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            self.finalise(names, destination=existing)
        self.assertEqual(list(p.name for p in existing.iterdir()), ['sentinel'])
        result = self.finalise(names)
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            self.restore(existing, result)
        self.assertEqual((existing/'sentinel').read_bytes(), b'preserve')

    def test_receipt_tamper_refuses_before_destination_or_extraction(self):
        result = self.finalise(self.compressible())
        receipt = Path(result['receipt_path'])
        receipt.write_bytes(receipt.read_bytes()+b'\n')
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            self.restore(self.root/'restored', result)
        self.assertFalse((self.root/'restored').exists())

    def test_archive_tamper_refuses_before_destination_or_extraction(self):
        result = self.finalise(self.compressible())
        self.assertEqual(result['selected_format'], 'tar.zst')
        archive = self.root/'bundle/bundle.tar.zst'
        with archive.open('r+b') as stream:
            stream.seek(32)
            value = stream.read(1)
            stream.seek(32)
            stream.write(bytes([value[0] ^ 1]))
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            self.restore(self.root/'restored', result)
        self.assertFalse((self.root/'restored').exists())

    def test_cancelled_work_returns_budget_and_creates_no_bundle(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises((CancelledError, RuntimeError)):
            self.finalise(self.compressible(), cancel=cancel)
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.assertFalse((self.root/'bundle').exists())

    def test_cancellation_after_owned_process_launch_stops_and_joins_job(self):
        cancel = threading.Event()
        actual_job, created = A.TrainingJob, []

        class TrackingJob(actual_job):
            def __init__(self):
                super().__init__()
                self.stopped = self.closed = False
                created.append(self)

            def launch(self, command, env, cwd):
                self.process = super().launch(command, env, cwd)
                cancel.set()
                return self.process

            def stop(self):
                result = super().stop()
                self.stopped = not result['remaining'] and not result['action_errors']
                return result

            def close(self):
                super().close()
                self.closed = True

        with patch.object(A, 'TrainingJob', TrackingJob):
            with self.assertRaises(CancelledError):
                self.finalise(self.compressible(), cancel=cancel)
        gc.collect()
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].stopped and created[0].closed)
        self.assertIsNone(created[0].process.handle)
        self.assertIsNone(created[0].job.handle)
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.assertFalse((self.root/'bundle').exists())

    def test_unsuitable_kind_and_live_database_files_are_refused(self):
        (self.source/'safe.json').write_text('{"complete":true}', encoding='utf-8')
        for kind in ('live-store', 'checkpoint', 'active-diagnostics'):
            with self.subTest(kind=kind), self.assertRaises((ValueError, RuntimeError, OSError)):
                self.finalise(['safe.json'], kind=kind)
            gc.collect()
        for name in ('live.sqlite', 'live.db'):
            (self.source/name).write_bytes(b'not a real database')
            with self.subTest(name=name), self.assertRaises((ValueError, RuntimeError, OSError)):
                self.finalise([name])
            gc.collect()
            self.assertEqual(self.budget.reserved_bytes, 0)
        self.assertFalse((self.root/'bundle').exists())


if __name__ == '__main__':
    unittest.main()
