"""W1 storage fixes: orphan quarantine (M5), later writer (L17), WAL header (L18),
seal-verification reuse (S4W-5) and measured catalog booking (L16)."""
import gc
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import tracemalloc
import unittest
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(HERE), str(RUNTIME), str(HERE.parent)]
TEMP = HERE.parents[4] / '_t'

import interval_store_set as I
from compact_contracts import (
    BINDING_INDEX_SCHEMA,
    SEGMENT_REF_SCHEMA,
    BindingIndexRef,
    ContractError,
    LogicalIdentity,
    SegmentRef,
    SnapshotLocator,
)
from interval_catalog import (
    Catalog,
    CatalogEntry,
    canonical,
    publish_catalog,
    read_catalog,
)
from interval_store_set import IntervalStoreSet, ReadOnlyNative
from test_interval_store_set import WORKFLOW, add_interval, finish, scope

REASON = 'test: resume after failure'
CHILD = """
import os,sys,threading
from test_interval_store_set import scope,add_interval,finish
from interval_catalog import canonical
from interval_store_set import IntervalStoreSet
s=scope(); stores=IntervalStoreSet.open_catalog(sys.argv[1],scope=s)
phase=sys.argv[2]
if phase=='writing':
    candidate=stores.begin_interval(stores.head,producer_identity='b'*64,runtime_identity='c'*64)
    candidate.put_chunk(canonical({'dtype':'|u1','count':9}),b'unsealed!')
    os._exit(72)
stores.crash_hook=lambda p: os._exit(72) if p==phase else None
candidate,ref,_=add_interval(stores,[b'crash-successor'])
finish(stores,candidate,ref)
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unlock(root):
    for path in Path(root).rglob('*'):
        if path.is_file():
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='w1q-', dir=TEMP)
        self.root = Path(self.temp.name)
        self.sc = scope()
        self.stores = IntervalStoreSet.create_migration(str(self.root / 'catalog.json'),
                                                       workflow_id=WORKFLOW, scope=self.sc)

    def tearDown(self):
        self.stores.close()
        gc.collect()
        self.sc.close()
        unlock(self.root)
        self.temp.cleanup()

    def root_interval(self):
        candidate, ref, chunks = add_interval(self.stores, [b'abc' * 50])
        return finish(self.stores, candidate, ref), ref, chunks

    def reopen(self, directory=None):
        self.stores.close()
        self.stores = IntervalStoreSet.open_catalog(str((directory or self.root) / 'catalog.json'), scope=self.sc)
        return self.stores

    def assert_quarantined_and_advance(self, directory, before):
        stores = self.stores
        with self.assertRaises(FileExistsError):
            stores.begin_interval(stores.head, producer_identity='b' * 64, runtime_identity='c' * 64)
        record = stores.quarantine_orphan(reason=REASON)
        self.assertTrue(record['complete'])
        self.assertEqual(record['reason'], REASON)
        self.assertEqual({f['original'] for f in record['files']}, set(before))
        for row in record['files']:
            target = directory / row['quarantined']
            self.assertTrue(target.exists())
            self.assertFalse((directory / row['original']).exists())
            self.assertEqual(row['sha256'], before[row['original']][0])
            self.assertEqual(row['bytes'], before[row['original']][1])
            self.assertEqual(sha(target), before[row['original']][0])
            self.assertNotRegex(row['quarantined'], r'\.sqlite\Z')
        log = (directory / 'catalog.json.quarantine.jsonl').read_bytes().splitlines()
        self.assertEqual(json.loads(log[-1]), record)
        # The next interval now begins, seals and promotes.
        head = stores.head.interval if stores.head else -1
        candidate, ref, _ = add_interval(stores, [b'after-quarantine'])
        finish(stores, candidate, ref)
        self.assertEqual(stores.head.interval, head + 1)
        return record

    def snapshot(self, directory, interval):
        found = {}
        for suffix in ('', '-journal', '-wal', '-shm'):
            path = directory / f'interval-{interval:04d}.sqlite{suffix}'
            if path.exists():
                found[path.name] = (sha(path), path.stat().st_size)
        return found

    def test_real_crash_at_each_stage_then_quarantine_then_begin(self):
        self.root_interval()
        original = (self.root / 'catalog.json').read_bytes()
        self.stores.close()
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(HERE), str(RUNTIME), str(HERE.parent))))
        for phase in ('writing', 'candidate_quiesced', 'seal_written', 'file_sealed',
                      'catalog_flushed', 'catalog_replaced'):
            with self.subTest(phase=phase):
                dest = self.root / phase
                dest.mkdir()
                shutil.copy2(self.root / 'interval-0000.sqlite', dest / 'interval-0000.sqlite')
                (dest / 'catalog.json').write_bytes(original)
                result = subprocess.run([sys.executable, '-B', '-c', CHILD, str(dest / 'catalog.json'), phase],
                                        capture_output=True, text=True, check=False, env=env, timeout=60)
                self.assertEqual(result.returncode, 72, result.stderr)
                self.stores = IntervalStoreSet.open_catalog(str(dest / 'catalog.json'), scope=self.sc)
                if phase == 'catalog_replaced':
                    # Committed: interval 1 is accepted and is never quarantined.
                    self.assertEqual(self.stores.head.interval, 1)
                    accepted = sha(dest / 'interval-0001.sqlite')
                    self.assertIsNone(self.stores.quarantine_orphan(reason=REASON))
                    self.assertEqual(sha(dest / 'interval-0001.sqlite'), accepted)
                    self.assertFalse((dest / 'catalog.json.quarantine.jsonl').exists())
                else:
                    self.assertEqual(self.stores.head.interval, 0)
                    before = self.snapshot(dest, 1)
                    self.assertIn('interval-0001.sqlite', before)
                    if phase == 'writing':
                        self.assertIn('interval-0001.sqlite-journal', before)
                    self.assert_quarantined_and_advance(dest, before)
                    self.assertEqual(self.stores.head.interval, 1)
                    self.stores.verify_file_sha256(1)
                self.stores.close()
        self.stores = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)

    def test_in_process_cancel_at_each_stage_then_quarantine(self):
        self.root_interval()
        cases = ('cancel_writing', 'cancel_quiesced', 'cancel_sealed', 'cas_refused')
        for case in cases:
            with self.subTest(case=case):
                token = threading.Event()
                candidate, ref, _ = add_interval(self.stores, [case.encode()])
                if case == 'cancel_writing':
                    token.set()
                    with self.assertRaises(InterruptedError):
                        candidate.put_chunk(canonical({'dtype': '|u1', 'count': 1}), b'z', cancel=token)
                elif case == 'cancel_quiesced':
                    self.stores.crash_hook = lambda p, token=token: token.set() if p == 'candidate_quiesced' else None
                    with self.assertRaises(InterruptedError):
                        candidate.seal(ref, cancel=token)
                elif case == 'cancel_sealed':
                    sealed = candidate.seal(ref)
                    token.set()
                    with self.assertRaises((InterruptedError, CancelledError)):
                        self.stores.promote(sealed, expected_catalog_digest=self.stores.catalog_digest, cancel=token)
                else:
                    sealed = candidate.seal(ref)
                    with self.assertRaises(ContractError):
                        self.stores.promote(sealed, expected_catalog_digest='0' * 64)
                self.stores.crash_hook = None
                with self.assertRaisesRegex(ContractError, 'live candidate'):
                    self.stores.quarantine_orphan(reason=REASON)
                candidate.close()
                n = self.stores.head.interval + 1
                before = self.snapshot(self.root, n)
                self.assertTrue(before)
                self.assert_quarantined_and_advance(self.root, before)
        lines = (self.root / 'catalog.json.quarantine.jsonl').read_bytes().splitlines()
        self.assertEqual(len(lines), len(cases))

    def test_migration_orphan_and_fresh_process_store_set(self):
        candidate, _ref, _ = add_interval(self.stores, [b'first'])
        token = threading.Event()
        token.set()
        with self.assertRaises(InterruptedError):
            candidate.put_chunk(canonical({'dtype': '|u1', 'count': 1}), b'q', cancel=token)
        candidate.close()
        self.stores.close()
        self.stores = IntervalStoreSet.create_migration(str(self.root / 'catalog.json'),
                                                       workflow_id=WORKFLOW, scope=self.sc)
        before = self.snapshot(self.root, 0)
        self.assert_quarantined_and_advance(self.root, before)
        self.assertEqual(self.stores.head.interval, 0)
        self.assertIsNone(self.stores.quarantine_orphan(reason=REASON))

    def test_stale_store_set_never_quarantines_a_committed_interval(self):
        self.root_interval()
        stale = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        try:
            candidate, ref, _ = add_interval(self.stores, [b'committed'])
            finish(self.stores, candidate, ref)
            accepted = sha(self.root / 'interval-0001.sqlite')
            with self.assertRaisesRegex(ContractError, 'catalog changed'):
                stale.quarantine_orphan(reason=REASON)
            self.assertEqual(sha(self.root / 'interval-0001.sqlite'), accepted)
            self.assertEqual(list(self.root.glob('*.quarantined-*')), [])
        finally:
            stale.close()

    def test_catalog_listed_name_hard_link_and_bad_reason_refuse(self):
        self.root_interval()
        self.stores.close()
        # An accepted entry that happens to use the next interval's basename.
        (self.root / 'interval-0000.sqlite').rename(self.root / 'interval-0001.sqlite')
        catalog, _ = read_catalog(self.root / 'catalog.json')
        renamed = Catalog(WORKFLOW, 1, (replace(catalog.entries[0], filename='interval-0001.sqlite'),))
        (self.root / 'catalog.json').write_bytes(renamed.to_bytes())
        self.stores = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        accepted = sha(self.root / 'interval-0001.sqlite')
        with self.assertRaisesRegex(ContractError, 'accepted catalog'):
            self.stores.quarantine_orphan(reason=REASON)
        self.assertEqual(sha(self.root / 'interval-0001.sqlite'), accepted)
        for bad in ('', 'x' * 513, 'line\nbreak', None):
            with self.assertRaises(ContractError):
                self.stores.quarantine_orphan(reason=bad)
        # A hard-linked orphan could alias another file: refused, not renamed.
        self.stores.close()
        os.chmod(self.root / 'interval-0001.sqlite', stat.S_IWRITE | stat.S_IREAD)
        (self.root / 'interval-0001.sqlite').rename(self.root / 'interval-0000.sqlite')
        os.chmod(self.root / 'interval-0000.sqlite', stat.S_IREAD)
        (self.root / 'catalog.json').write_bytes(catalog.to_bytes())
        self.stores = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        other = self.root / 'other.bin'
        other.write_bytes(b'not an interval')
        try:
            os.link(other, self.root / 'interval-0001.sqlite')
        except OSError:
            self.skipTest('hard links unavailable')
        with self.assertRaisesRegex(ContractError, 'hard-linked'):
            self.stores.quarantine_orphan(reason=REASON)
        self.assertTrue((self.root / 'interval-0001.sqlite').exists())


def listing(root):
    return sorted(p.name for p in Path(root).iterdir())


class QuarantineSafetyTests(unittest.TestCase):
    """x-storage-fix A2-A4: promote/quarantine race, shared directory, unit rename."""

    def setUp(self):
        TEMP.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='xq-', dir=TEMP)
        self.root = Path(self.temp.name)
        self.sc = scope()
        self.open = []

    def tearDown(self):
        for stores in self.open:
            stores.close()
        gc.collect()
        self.sc.close()
        unlock(self.root)
        self.temp.cleanup()

    def migration(self, name='catalog.json', workflow=WORKFLOW):
        stores = IntervalStoreSet.create_migration(str(self.root / name), workflow_id=workflow, scope=self.sc)
        self.open.append(stores)
        return stores

    def reopen_ok(self, name='catalog.json'):
        stores = IntervalStoreSet.open_catalog(str(self.root / name), scope=self.sc)
        try:
            for entry in stores._entries():
                stores.verify_file_sha256(entry.interval)
            return stores.head.interval
        finally:
            stores.close()

    def hashes(self):
        return {p.name: sha(p) for p in self.root.iterdir() if p.is_file() and not p.name.endswith('.lock')}

    def test_case_a_second_catalog_in_directory_is_refused_nothing_moved(self):
        other = self.migration('other.json')
        candidate, ref, _ = add_interval(other, [b'accepted by other.json'])
        finish(other, candidate, ref)
        other.close()
        self.open.remove(other)
        mine = self.migration('catalog.json')
        before = self.hashes()
        with self.assertRaisesRegex(ContractError, 'not dedicated'):
            mine.quarantine_orphan(reason=REASON)
        self.assertEqual(self.hashes(), before)
        self.assertEqual(self.reopen_ok('other.json'), 0)
        # Without the other lock file the catalog-shaped file still proves sharing.
        os.remove(self.root / 'other.json.lock')
        with self.assertRaisesRegex(ContractError, 'other.json'):
            mine.quarantine_orphan(reason=REASON)
        self.assertEqual(self.hashes(), before)
        self.assertEqual(self.reopen_ok('other.json'), 0)
        self.assertEqual(list(self.root.glob('*.quarantined-*')), [])

    def test_sealed_orphan_of_another_workflow_is_refused(self):
        foreign = self.migration('catalog.json')
        candidate, ref, _ = add_interval(foreign, [b'foreign sealed'])
        candidate.seal(ref)
        candidate.close()
        foreign.close()
        self.open.remove(foreign)
        (self.root / 'catalog.json.lock').unlink(missing_ok=True)
        self.assertTrue(I._immutable(self.root / 'interval-0000.sqlite'))
        # Same directory and catalog name, but a different workflow: the
        # sealed orphan does not carry this workflow's seal.
        mine = self.migration('catalog.json', workflow='f' * 64)
        before = self.hashes()
        with self.assertRaisesRegex(ContractError, "not this catalog's candidate"):
            mine.quarantine_orphan(reason=REASON)
        self.assertEqual(self.hashes(), before)

    def test_case_b_quarantine_before_publish_lock_refuses_promote(self):
        s1 = self.migration()
        candidate, ref, _ = add_interval(s1, [b'root interval'])
        finish(s1, candidate, ref)
        accepted = sha(self.root / 'interval-0000.sqlite')
        candidate, ref, _ = add_interval(s1, [b'successor interval'])
        sealed = candidate.seal(ref)
        s2 = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        self.open.append(s2)
        original, moved = I.publish_catalog, []

        def interleaved(*args, **kwargs):
            # After promote's early token check, before publish takes the lock.
            if not moved:
                moved.append(s2.quarantine_orphan(reason=REASON))
            return original(*args, **kwargs)
        with patch.object(I, 'publish_catalog', interleaved), \
                self.assertRaisesRegex(ContractError, 'changed before promotion'):
            s1.promote(sealed, expected_catalog_digest=s1.catalog_digest)
        self.assertEqual([f['original'] for f in moved[0]['files']], ['interval-0001.sqlite'])
        self.assertEqual(s1.head.interval, 0)
        self.assertEqual(sha(self.root / 'interval-0000.sqlite'), accepted)
        self.assertEqual(list(self.root.glob('catalog.json.tmp-*')), [])
        self.assertEqual(self.reopen_ok(), 0)

    def test_case_b_quarantine_inside_publish_lock_is_refused(self):
        s1 = self.migration()
        candidate, ref, _ = add_interval(s1, [b'root interval'])
        finish(s1, candidate, ref)
        candidate, ref, _ = add_interval(s1, [b'successor interval'])
        sealed = candidate.seal(ref)
        s2 = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        self.open.append(s2)
        attempts = []

        def hook(phase):
            if phase == 'catalog_flushed':
                try:
                    attempts.append(s2.quarantine_orphan(reason=REASON))
                except ContractError as exc:
                    attempts.append(exc)
        s1.crash_hook = hook
        entry = s1.promote(sealed, expected_catalog_digest=s1.catalog_digest)
        s1.crash_hook = None
        self.assertEqual(entry.interval, 1)
        self.assertIsInstance(attempts[0], ContractError)
        self.assertRegex(str(attempts[0]), 'holds the lock')
        self.assertEqual(sha(self.root / 'interval-0001.sqlite'), entry.file_sha256)
        self.assertEqual(list(self.root.glob('*.quarantined-*')), [])
        self.assertEqual(self.reopen_ok(), 1)

    def test_case_c_failed_rename_moves_nothing(self):
        stores = self.migration()
        candidate, ref, _ = add_interval(stores, [b'root interval'])
        finish(stores, candidate, ref)
        main = self.root / 'interval-0001.sqlite'
        main.write_bytes(b'orphan main' * 100)
        Path(str(main) + '-journal').write_bytes(b'hot journal' * 10)
        before, names = self.hashes(), listing(self.root)
        original = I._rename_no_replace

        def held(source, target):
            # The main file is held open without share-delete (portable stand-in).
            if Path(source) == main:
                raise PermissionError(13, 'held by another handle', str(source))
            return original(source, target)
        with patch.object(I, '_rename_no_replace', held), self.assertRaisesRegex(ContractError, 'renamed back'):
            stores.quarantine_orphan(reason=REASON)
        log = json.loads((self.root / 'catalog.json.quarantine.jsonl').read_bytes().splitlines()[-1])
        self.assertEqual((log['complete'], log['files']), (False, []))
        names_after = [n for n in listing(self.root) if n != 'catalog.json.quarantine.jsonl']
        self.assertEqual(names_after, names)
        after = self.hashes()
        after.pop('catalog.json.quarantine.jsonl')
        self.assertEqual(after, before)
        # A later attempt without the holder moves both files as one unit.
        record = stores.quarantine_orphan(reason=REASON)
        self.assertTrue(record['complete'])
        suffixes = {row['quarantined'][len(row['original']):] for row in record['files']}
        self.assertEqual(len(suffixes), 1)
        self.assertEqual(sorted(row['original'] for row in record['files']),
                         ['interval-0001.sqlite', 'interval-0001.sqlite-journal'])

    @unittest.skipUnless(os.name == 'nt', 'Windows share-mode rename failure')
    def test_case_c_real_open_handle_on_windows(self):
        stores = self.migration()
        candidate, ref, _ = add_interval(stores, [b'root interval'])
        finish(stores, candidate, ref)
        main = self.root / 'interval-0001.sqlite'
        main.write_bytes(b'orphan main' * 100)
        Path(str(main) + '-journal').write_bytes(b'hot journal' * 10)
        names = listing(self.root)
        with open(main, 'rb'), self.assertRaisesRegex(ContractError, 'renamed back'):
            stores.quarantine_orphan(reason=REASON)
        self.assertEqual([n for n in listing(self.root) if n != 'catalog.json.quarantine.jsonl'], names)

    def test_sidecar_only_orphan_is_quarantined_then_nothing_left(self):
        # Re-check defect 1: no main file, only a hot journal; the seal check is skipped.
        stores = self.migration()
        candidate, ref, _ = add_interval(stores, [b'root interval'])
        finish(stores, candidate, ref)
        journal = self.root / 'interval-0001.sqlite-journal'
        journal.write_bytes(b'hot journal' * 10)
        record = stores.quarantine_orphan(reason=REASON)
        self.assertTrue(record['complete'])
        self.assertEqual([row['original'] for row in record['files']], ['interval-0001.sqlite-journal'])
        self.assertFalse(journal.exists())
        self.assertIsNone(stores.quarantine_orphan(reason=REASON))
        self.assertEqual(self.reopen_ok(), 0)

    def test_unreadable_moved_file_is_logged_then_refused(self):
        # Re-check defect 2: every rename succeeds but a moved file cannot be read.
        stores = self.migration()
        candidate, ref, _ = add_interval(stores, [b'root interval'])
        finish(stores, candidate, ref)
        main = self.root / 'interval-0001.sqlite'
        main.write_bytes(b'orphan main' * 100)
        Path(str(main) + '-journal').write_bytes(b'hot journal' * 10)
        real_open = Path.open

        def unreadable(path, *args, **kwargs):
            if '.quarantined-' in path.name and path.name.startswith('interval-0001.sqlite') \
                    and not path.name.startswith('interval-0001.sqlite-'):
                raise PermissionError(13, 'no read sharing', str(path))
            return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', unreadable), self.assertRaisesRegex(ContractError, 'could not be hashed'):
            stores.quarantine_orphan(reason=REASON)
        log = json.loads((self.root / 'catalog.json.quarantine.jsonl').read_bytes().splitlines()[-1])
        self.assertTrue(log['complete'])
        rows = {row['original']: row for row in log['files']}
        self.assertEqual(set(rows), {'interval-0001.sqlite', 'interval-0001.sqlite-journal'})
        self.assertIsNone(rows['interval-0001.sqlite']['sha256'])
        self.assertEqual(rows['interval-0001.sqlite']['error'], 'PermissionError')
        self.assertIsNotNone(rows['interval-0001.sqlite-journal']['sha256'])
        self.assertFalse(main.exists())

    @unittest.skipUnless(os.path.normcase('A') == 'a', 'case-insensitive file names only')
    def test_catalog_opened_through_other_case_quarantines_its_own_directory(self):
        # Re-check defect 3: the same catalog opened as CATALOG.JSON is still its own.
        stores = self.migration()
        candidate, ref, _ = add_interval(stores, [b'root interval'])
        finish(stores, candidate, ref)
        stores.close()
        self.open.remove(stores)
        upper = IntervalStoreSet.open_catalog(str(self.root / 'CATALOG.JSON'), scope=self.sc)
        self.open.append(upper)
        (self.root / 'interval-0001.sqlite').write_bytes(b'orphan main' * 100)
        record = upper.quarantine_orphan(reason=REASON)
        self.assertTrue(record['complete'])
        self.assertEqual([row['original'] for row in record['files']], ['interval-0001.sqlite'])


class SealAndReaderTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='w1s-', dir=TEMP)
        self.root = Path(self.temp.name)
        self.sc = scope()
        self.stores = IntervalStoreSet.create_migration(str(self.root / 'catalog.json'),
                                                       workflow_id=WORKFLOW, scope=self.sc)

    def tearDown(self):
        self.stores.close()
        gc.collect()
        self.sc.close()
        unlock(self.root)
        self.temp.cleanup()

    def test_later_writer_after_seal_write_is_refused_before_catalog(self):
        candidate, ref, _ = add_interval(self.stores, [b'root'])
        path = candidate.path
        def foreign(phase):
            if phase == 'seal_written':
                db = sqlite3.connect(path)
                db.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',
                           ('f' * 64, canonical({'dtype': '|u1', 'count': 1}), 'raw', '0' * 64, b'x'))
                db.commit()
                db.close()
        self.stores.crash_hook = foreign
        with self.assertRaisesRegex(ContractError, 'logical seal mismatch'):
            candidate.seal(ref)
        self.assertFalse((self.root / 'catalog.json').exists())
        candidate.close()

    def test_wal_header_refused_without_creating_sidecars(self):
        candidate, ref, _ = add_interval(self.stores, [b'root'])
        finish(self.stores, candidate, ref)
        copy = self.root / 'copy' / 'interval-0000.sqlite'
        copy.parent.mkdir()
        shutil.copy2(self.root / 'interval-0000.sqlite', copy)
        os.chmod(copy, stat.S_IWRITE | stat.S_IREAD)
        db = sqlite3.connect(copy)
        db.execute('PRAGMA journal_mode=WAL')
        db.close()
        os.chmod(copy, stat.S_IREAD)
        listing = sorted(p.name for p in copy.parent.iterdir())
        with self.assertRaisesRegex(ContractError, 'rollback-journal'):
            ReadOnlyNative(copy, scope=self.sc)
        self.assertEqual(sorted(p.name for p in copy.parent.iterdir()), listing)

    def test_reopens_reuse_verified_seal_beyond_eight_ancestors(self):
        for i in range(10):
            candidate, ref, _ = add_interval(self.stores, [bytes([i + 1]) * 30])
            finish(self.stores, candidate, ref)
        calls = []
        original = I._verify_seal
        def counted(reader, entry, workflow_id, cancel=None):
            calls.append(entry.interval)
            return original(reader, entry, workflow_id, cancel)
        candidate = self.stores.begin_interval(self.stores.head, producer_identity='b' * 64,
                                               runtime_identity='c' * 64)
        with patch.object(I, '_verify_seal', counted):
            for i in range(5):
                candidate.put_chunk(canonical({'dtype': '|u1', 'count': 7}), bytes([100 + i]) * 7)
        candidate.close()
        # Each ancestor is fully verified at most once (base: 10 per new chunk).
        self.assertEqual(len(calls), len(set(calls)))
        self.assertLessEqual(len(calls), 10)
        # A changed file is still refused on reopen.
        self.stores.close()
        self.stores = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        for i in range(10):
            self.stores._handle(i)
        target = self.root / 'interval-0000.sqlite'
        info = target.stat()
        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 1000))
        for i in range(1, 10):
            self.stores._handle(i)
        with self.assertRaisesRegex(ContractError, 'identity changed'):
            self.stores._handle(0)


def _entry(i, prev, refs):
    h = lambda *parts: hashlib.sha256(repr(parts).encode()).hexdigest()
    loc = SnapshotLocator(WORKFLOW, i, h('root', i))
    ref = SegmentRef(SEGMENT_REF_SCHEMA, loc, LogicalIdentity('fixture.v1', h('id', i), 1000 + i), 10 ** 9 + i,
                     BindingIndexRef(BINDING_INDEX_SCHEMA, loc, h('bind', i), 7), h('prod', i))
    return CatalogEntry(i, f'interval-{i:04d}.sqlite', h('file', i), h('seal', i), i - 1 if i else None,
                        prev.logical_seal if prev else None, ref, h('p', i), h('r', i), refs)


def _catalog(n, dense):
    entries = []
    for i in range(n):
        refs = tuple((j, entries[j].logical_seal) for j in range(i)) if dense else ()
        entries.append(_entry(i, entries[-1] if entries else None, refs))
    return Catalog(WORKFLOW, n, tuple(entries))


class CatalogBookingTests(unittest.TestCase):
    """tracemalloc for memory only (nothing timed): real <= booked <= 1.3x real."""

    def test_retained_and_transient_catalog_booking_is_honest(self):
        TEMP.mkdir(exist_ok=True)
        results = {}
        with tempfile.TemporaryDirectory(prefix='w1c-', dir=TEMP) as temp:
            for label, n, dense in (('iv-like-3', 3, False), ('flat-max', 796, False),
                                    ('dense-max', 153, True)):
                path = Path(temp) / f'{label}.json'
                publish_catalog(path, _catalog(n, dense), expected_digest=None)
                size = path.stat().st_size
                gc.collect()
                tracemalloc.start()
                base = tracemalloc.get_traced_memory()[0]
                tracemalloc.reset_peak()
                held = read_catalog(path, expected_size=size)
                current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                retained, read_peak = current - base, peak - base
                booked = I.catalog_retained_charge(held[0])
                transient = I.catalog_transient_charge(size)
                results[label] = {'bytes': size, 'retained': retained, 'booked': booked,
                                  'read_peak': read_peak, 'transient': transient}
                self.assertLessEqual(retained, booked, label)
                self.assertLessEqual(booked, 1.3 * retained + 16384 + 768 * n, label)
                self.assertLessEqual(read_peak, transient, label)
                self.assertLessEqual(booked, I.CATALOG_CHARGE)
                del held
        print(json.dumps(results, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
