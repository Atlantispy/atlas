"""Step 9(a) storage primitives: the pending-interval read view and adopt_and_promote.

Option B: the runner seals the next interval and exits; the independent reader
reads the pending sealed file through IntervalStoreSet.open_pending; on PASS the
launcher calls adopt_and_promote. Synthetic data only, real native SQLite files
under the tree's _t folder; real child processes for the crash points.
"""
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
import tracemalloc
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(HERE), str(RUNTIME), str(HERE.parent)]
TEMP = HERE.parents[4] / '_t'

import interval_store_set as I
import segment_store as S
import test_segment_store as fixture
from atlas_tectonics.resources import WorkBudget
from compact_contracts import (
    BINDING_INDEX_SCHEMA,
    SEGMENT_REF_SCHEMA,
    BindingIndexRef,
    ContractError,
    LogicalIdentity,
    SegmentRef,
    SnapshotLocator,
)
from content_cache import create_retained_scope
from interval_catalog import Catalog, CatalogEntry, canonical, read_catalog
from interval_store_set import IntervalStoreSet, ReadOnlyNative, seal_key
from test_interval_store_set import WORKFLOW, add_interval, finish, scope

REASON = 'test: reader refused the pending interval'
# Runner phases: the runner writes its durable record of the head and the two
# identities (which the sealed file does not bind) BEFORE it seals, as the
# Steps 8-9 wiring must. Adopt phases: the launcher adopts with the recorded
# values and the reader's verdict (pending_view_digest = the view's digest).
CHILD = """
import json,os,sys
from test_interval_store_set import scope,add_interval
from interval_catalog import CatalogEntry
from interval_store_set import IntervalStoreSet,pending_view_digest
s=scope(); stores=IntervalStoreSet.open_catalog(sys.argv[1],scope=s)
phase=sys.argv[2]
stores.crash_hook=lambda p: os._exit(72) if p==phase else None
if phase in ('candidate_quiesced','seal_written','file_sealed'):
    candidate,ref,_=add_interval(stores,[b'crash-successor'])
    with open(sys.argv[3],'w') as f:
        json.dump({'head':ref.to_wire(),'producer_identity':candidate.producer_identity,
                   'runtime_identity':candidate.runtime_identity,
                   'expected_catalog_digest':stores.catalog_digest},f)
        f.flush(); os.fsync(f.fileno())
    candidate.seal(ref)
else:
    with open(sys.argv[3]) as f: entry=CatalogEntry.from_wire(json.load(f)['entry'])
    stores.adopt_and_promote(entry.filename,expected_sha256=entry.file_sha256,
        expected_logical_seal=entry.logical_seal,head=entry.head,
        producer_identity=entry.producer_identity,runtime_identity=entry.runtime_identity,
        expected_catalog_digest=stores.catalog_digest,
        reader_view_digest=pending_view_digest(stores.catalog_digest,entry))
os._exit(0)
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unlock(root):
    for path in Path(root).rglob('*'):
        if path.is_file():
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def expected(entry):
    return {'expected_sha256': entry.file_sha256, 'expected_logical_seal': entry.logical_seal,
            'head': entry.head, 'producer_identity': entry.producer_identity,
            'runtime_identity': entry.runtime_identity}


def adopting(entry, digest, **changes):
    """adopt_and_promote arguments: the runner's recorded values, the accepted
    digest and the reader's verdict for this entry (reader_view_digest is
    mandatory; pending_view_digest equals the reader view's catalog_digest,
    test_reader_view_digest_binds_adoption_to_the_entry_the_reader_read)."""
    values = dict(expected(entry), expected_catalog_digest=digest,
                  reader_view_digest=I.pending_view_digest(digest, entry))
    values.update(changes)
    return values


class _Crash(Exception):
    pass


class PendingTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='s9a-', dir=TEMP)
        self.root = Path(self.temp.name)
        self.catalog = self.root / 'catalog.json'
        self.sc = scope()
        self.open = []

    def tearDown(self):
        for stores in self.open:
            stores.close()
        gc.collect()
        self.sc.close()
        unlock(self.root)
        self.temp.cleanup()

    def track(self, stores):
        self.open.append(stores)
        return stores

    def runner_seals_and_exits(self, values=(b'successor interval',), share=True):
        """Interval 0 accepted; interval 1 sealed, NOT promoted; runner store set closed."""
        stores = IntervalStoreSet.create_migration(str(self.catalog), workflow_id=WORKFLOW, scope=self.sc)
        try:
            shared = b'shared root bytes' * 9
            candidate, ref, _ = add_interval(stores, [shared])
            finish(stores, candidate, ref)
            accepted = stores.catalog_digest
            candidate, ref, chunks = add_interval(stores, list(values), share=(shared,) if share else ())
            sealed = candidate.seal(ref)
            self.assertEqual(sealed.expected_catalog_digest, accepted)
        finally:
            stores.close()
        return sealed.entry, accepted, chunks

    def view(self, entry, digest, *, name=None, workflow=WORKFLOW):
        return self.track(IntervalStoreSet.open_pending(
            str(self.catalog), name or entry.filename, scope=self.sc, workflow_id=workflow,
            expected_catalog_digest=digest, **expected(entry)))

    def accepted(self):
        return self.track(IntervalStoreSet.open_catalog(str(self.catalog), scope=self.sc))

    def state(self):
        return {p.name: sha(p) for p in self.root.iterdir() if p.is_file() and not p.name.endswith('.lock')}

    # (a) the pending read view -------------------------------------------------

    def test_pending_view_reads_exactly_one_pending_file(self):
        entry, digest, chunks = self.runner_seals_and_exits()
        before = self.state()
        ordinary = self.accepted()
        self.assertEqual(ordinary.head.interval, 0)
        with self.assertRaisesRegex(ContractError, 'unlisted interval'):
            ordinary.resolve_manifest(1, entry.head.root_key)
        view = self.view(entry, digest)
        self.assertIs(type(view), IntervalStoreSet)   # the reader facade's resolver type
        self.assertEqual(view.head, entry)
        self.assertEqual(view.pending_entry, entry)
        self.assertEqual(view.accepted_catalog_digest, digest)
        self.assertNotEqual(view.catalog_digest, digest)
        self.assertIsNone(ordinary.pending_entry)
        self.assertEqual(ordinary.accepted_catalog_digest, ordinary.catalog_digest)
        with view.resolve_manifest(1, entry.head.root_key) as body:
            self.assertEqual(json.loads(body.value)['metadata']['reference'], entry.head.to_wire())
        with view.read_batch():
            for row in chunks:
                with view.resolve_chunk(1, row['owner'], row['key'], row['descriptor'].encode()) as raw:
                    self.assertTrue(raw.value)
        self.assertEqual([row['owner'] for row in chunks], [0, 1])
        self.assertTrue(view.verify_file_sha256(1))
        view.assert_cached_read_safe()
        with self.assertRaisesRegex(ContractError, 'unlisted interval'):
            view.resolve_manifest(2, entry.head.root_key)
        for call in (lambda: view.begin_interval(view.head, producer_identity='b' * 64, runtime_identity='c' * 64),
                     lambda: view.quarantine_orphan(reason=REASON),
                     lambda: view.adopt_and_promote(entry.filename, **adopting(entry, digest))):
            with self.assertRaisesRegex(ContractError, 'pending-interval view is read-only'):
                call()
        # Nothing was written by the view: same files, same bytes, catalog unchanged.
        self.assertEqual(self.state(), before)

    def test_reader_facade_takes_the_pending_view_as_its_resolver(self):
        import compact_restart_store as R
        entry, digest, _ = self.runner_seals_and_exits()
        view = self.view(entry, digest)
        store = R.CompactRestartStore(view, scope=self.sc)
        try:
            self.assertTrue(store.readonly)
            self.assertEqual(store._intervals(), (1, 0))
            self.assertFalse(hasattr(store, 'interval'))
            with self.assertRaisesRegex(ContractError, 'pending-interval view is read-only'):
                store.begin_interval(producer_identity='b' * 64, runtime_identity='c' * 64)
        finally:
            store.close()

    def test_pending_view_is_token_checked_like_sealed_files(self):
        entry, digest, _ = self.runner_seals_and_exits()
        view = self.view(entry, digest)
        path = self.root / entry.filename
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000))
        with self.assertRaisesRegex(ContractError, 'identity changed'):
            view.assert_cached_read_safe()
        with self.assertRaisesRegex(ContractError, 'identity changed'), view.read_batch():
            pass

    def test_real_segment_reader_through_the_pending_view(self):
        stores = IntervalStoreSet.create_migration(str(self.catalog), workflow_id=WORKFLOW, scope=self.sc)
        backend = S.SegmentBackend()

        def publish(candidate, source, name):
            identity = LogicalIdentity('fixture.record.v1', sha256(name.encode()).hexdigest(), 99)
            return backend.publish(candidate, record_schema=identity.record_schema, identity=identity,
                                   metadata=b'{}', arrays=lambda: iter([source]), producer='b' * 64,
                                   representation_profile='fixture.columns.v1', scope=self.sc)
        try:
            candidate = stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)
            ref0 = publish(candidate, fixture.GeneratedSource(self.sc, 3 * 65536 + 5), 'zero')
            finish(stores, candidate, ref0)
            digest = stores.catalog_digest
            candidate = stores.begin_interval(stores.head, producer_identity='b' * 64, runtime_identity='c' * 64)
            source = fixture.GeneratedSource(self.sc, 21 * 65536 + 7)
            ref1 = publish(candidate, source, 'one')
            entry = candidate.seal(ref1).entry
        finally:
            stores.close()
        view = self.view(entry, digest)
        segment = backend.open(view, ref1, scope=self.sc)
        try:
            self.assertIsNotNone(segment.cache_identity())
            start, stop = 5 * 65536 + 3, 17 * 65536 + 11
            with segment.read('payload', start, stop, max_owned_bytes=stop - start) as owned:
                whole = b''.join(source.block(i, 65536) for i in range(22))[:source.info.logical_bytes]
                self.assertEqual(owned.value, whole[start:stop])
        finally:
            segment.close()

    def test_pending_interval_zero_without_a_catalog(self):
        stores = IntervalStoreSet.create_migration(str(self.catalog), workflow_id=WORKFLOW, scope=self.sc)
        try:
            candidate, ref, _ = add_interval(stores, [b'first interval'])
            entry = candidate.seal(ref).entry
        finally:
            stores.close()
        self.assertFalse(self.catalog.exists())
        view = self.view(entry, None)
        self.assertEqual(view.head.interval, 0)
        self.assertTrue(view.verify_file_sha256(0))
        adopter = self.track(IntervalStoreSet.create_migration(str(self.catalog), workflow_id=WORKFLOW, scope=self.sc))
        self.assertEqual(adopter.adopt_and_promote(entry.filename, reader_view_digest=view.catalog_digest,
                                                   expected_catalog_digest=None, **expected(entry)), entry)
        self.assertEqual(self.catalog.read_bytes(), Catalog(WORKFLOW, 1, (entry,)).to_bytes())

    def test_no_catalog_is_accepted_only_for_pending_interval_zero(self):
        # Coordinator (16 Oct): expected_catalog_digest=None is the ONLY no-catalog case, and only
        # for a pending interval 0 when no catalog exists. With an accepted catalog present it refuses.
        entry, digest, _ = self.runner_seals_and_exits()
        before = self.state()
        with self.assertRaises((ContractError, FileExistsError)):
            self.view(entry, None)
        with self.assertRaises((ContractError, FileExistsError)):
            adopter = self.track(IntervalStoreSet.create_migration(
                str(self.catalog), workflow_id=WORKFLOW, scope=self.sc))
            adopter.adopt_and_promote(entry.filename, **adopting(entry, None))
        self.assertEqual(self.state(), before)
        # The accepted catalog itself is still required to match for a successor.
        self.assertEqual(self.view(entry, digest).head.interval, 1)

    # (b) adopt_and_promote ------------------------------------------------------

    def test_adopt_after_reader_writes_exactly_the_catalog_promote_would(self):
        entry, digest, chunks = self.runner_seals_and_exits()
        view = self.view(entry, digest)
        view.verify_file_sha256(1)
        verdict = view.catalog_digest   # recorded in the reader's verdict
        view.close()
        self.open.remove(view)
        stores = self.accepted()
        accepted0 = stores.head
        result = stores.adopt_and_promote(entry.filename, expected_catalog_digest=digest,
                                          reader_view_digest=verdict, **expected(entry))
        self.assertEqual(result, entry)
        self.assertEqual(stores.head, entry)
        # Byte-identical to what promote() publishes for the same sealed entry.
        self.assertEqual(self.catalog.read_bytes(), Catalog(WORKFLOW, 2, (accepted0, entry)).to_bytes())
        self.assertEqual(stores.catalog_digest, hashlib.sha256(self.catalog.read_bytes()).hexdigest())
        fresh = self.accepted()
        self.assertEqual(fresh.head, entry)
        self.assertTrue(fresh.verify_file_sha256(1))
        with fresh.resolve_chunk(1, chunks[-1]['owner'], chunks[-1]['key'], chunks[-1]['descriptor'].encode()) as raw:
            self.assertTrue(raw.value)
        # The next interval now begins on the adopted head.
        candidate, ref, _ = add_interval(fresh, [b'third interval'])
        self.assertEqual(finish(fresh, candidate, ref).interval, 2)

    def test_refusals_leave_catalog_and_files_unchanged(self):
        entry, digest, _ = self.runner_seals_and_exits()
        stores = self.accepted()
        cases = {
            'SHA-256 mismatch': dict(expected(entry), expected_sha256='0' * 64),
            'reserved seal metadata': dict(expected(entry), expected_logical_seal='1' * 64),
            'does not bind the supplied SegmentRef': dict(expected(entry), head=replace(
                entry.head, logical_bytes=entry.head.logical_bytes + 1)),
            'invalid pending interval head': dict(expected(entry), head=replace(
                entry.head, root_key=replace(entry.head.root_key, interval=2))),
            'producer_identity': dict(expected(entry), producer_identity='B' * 64),
        }
        before = self.state()
        verdict = I.pending_view_digest(digest, entry)
        for message, values in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ContractError, message):
                stores.adopt_and_promote(entry.filename, expected_catalog_digest=digest,
                                         reader_view_digest=verdict, **values)
            self.assertEqual(self.state(), before)
        names = {'named by the accepted catalog': 'interval-0000.sqlite',
                 'not the next interval file': 'interval-0002.sqlite',
                 'outside the catalog directory': str(self.root / 'elsewhere' / entry.filename)}
        for message, name in names.items():
            with self.subTest(message=message), self.assertRaisesRegex(ContractError, message):
                stores.adopt_and_promote(name, **adopting(entry, digest))
            with self.subTest(view=message), self.assertRaisesRegex(ContractError, message):
                self.view(entry, digest, name=name)
        with self.assertRaisesRegex(ContractError, 'stale expected catalog digest'):
            stores.adopt_and_promote(entry.filename, **adopting(entry, '2' * 64))
        with self.assertRaisesRegex(ContractError, 'stale expected catalog digest'):
            self.view(entry, '2' * 64)
        with self.assertRaisesRegex(ContractError, 'foreign workflow'):
            self.view(entry, digest, workflow='f' * 64)
        self.assertEqual(self.state(), before)
        self.assertEqual(stores.head.interval, 0)
        # Still adoptable after every refusal.
        self.assertEqual(stores.adopt_and_promote(entry.filename, **adopting(entry, digest)), entry)

    def test_reader_view_digest_is_mandatory(self):
        # Coordinator (16 Oct): the launcher always passes the reader's verdict.
        entry, digest, _ = self.runner_seals_and_exits()
        stores = self.accepted()
        before = self.state()
        with self.assertRaises(TypeError):
            stores.adopt_and_promote(entry.filename, expected_catalog_digest=digest, **expected(entry))
        for bad in (None, '', 'A' * 64, digest[:63]):
            with self.subTest(reader_view_digest=bad), self.assertRaisesRegex(ContractError, 'reader view digest'):
                stores.adopt_and_promote(entry.filename, **adopting(entry, digest, reader_view_digest=bad))
        # A well-formed digest of no reader's view (here: the accepted catalog's own digest).
        with self.assertRaisesRegex(ContractError, 'reader verified a different pending entry'):
            stores.adopt_and_promote(entry.filename, **adopting(entry, digest, reader_view_digest=digest))
        self.assertEqual(self.state(), before)
        self.assertEqual(stores.head.interval, 0)
        self.assertEqual(stores.adopt_and_promote(entry.filename, **adopting(entry, digest)), entry)

    def test_reader_view_digest_binds_adoption_to_the_entry_the_reader_read(self):
        entry, digest, _ = self.runner_seals_and_exits()
        verdict = self.view(entry, digest).catalog_digest
        self.assertEqual(verdict, I.pending_view_digest(digest, entry))
        stores = self.accepted()
        # The accepted head's root is also a valid root inside the pending
        # file's closure: the head is the caller's assertion (as in seal()),
        # so the reader's view digest is what binds it.
        other = dict(expected(entry), head=stores.head.head)
        for values in (other, dict(expected(entry), runtime_identity='d' * 64)):
            with self.assertRaisesRegex(ContractError, 'reader verified a different pending entry'):
                stores.adopt_and_promote(entry.filename, expected_catalog_digest=digest,
                                         reader_view_digest=verdict, **values)
        self.assertEqual(stores.head.interval, 0)
        self.assertEqual(stores.adopt_and_promote(entry.filename, expected_catalog_digest=digest,
                                                  reader_view_digest=verdict, **expected(entry)), entry)

    def test_second_unlisted_file_or_sidecar_refuses(self):
        entry, digest, _ = self.runner_seals_and_exits()
        stores = self.accepted()
        for stray in ('interval-0002.sqlite', 'interval-0001.sqlite-journal', 'interval-0000.sqlite-wal'):
            with self.subTest(stray=stray):
                (self.root / stray).write_bytes(b'')
                try:
                    with self.assertRaisesRegex(ContractError, 'another unlisted interval file'):
                        stores.adopt_and_promote(entry.filename, **adopting(entry, digest))
                    # A sidecar of the accepted head is already refused when the
                    # view opens the accepted catalog.
                    with self.assertRaisesRegex(ContractError, 'another unlisted interval file|journal/WAL sidecar'):
                        self.view(entry, digest)
                finally:
                    (self.root / stray).unlink()
        # Quarantined names and publish temporaries are not live interval files.
        (self.root / 'interval-0002.sqlite.quarantined-20261016T000000Z-0').write_bytes(b'q')
        (self.root / ('catalog.json.tmp-' + '0' * 32)).write_bytes(b'{}')
        self.view(entry, digest)
        self.assertEqual(stores.adopt_and_promote(entry.filename, **adopting(entry, digest)), entry)

    def test_writable_missing_or_changed_file_refuses(self):
        entry, digest, _ = self.runner_seals_and_exits()
        stores = self.accepted()
        path = self.root / entry.filename
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        with self.assertRaisesRegex(ContractError, 'not sealed read-only'):
            stores.adopt_and_promote(entry.filename, **adopting(entry, digest))
        with self.assertRaisesRegex(ContractError, 'not sealed read-only'):
            self.view(entry, digest)
        # Changed after the reader verified it: another writer adds a table.
        db = sqlite3.connect(path)
        db.execute('CREATE TABLE intruder (value INTEGER)')
        db.commit()
        db.close()
        os.chmod(path, stat.S_IREAD)
        with self.assertRaisesRegex(ContractError, 'SHA-256 mismatch'):
            stores.adopt_and_promote(entry.filename, **adopting(entry, digest))
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        path.unlink()
        with self.assertRaisesRegex(ContractError, 'missing'):
            stores.adopt_and_promote(entry.filename, **adopting(entry, digest))
        self.assertEqual(stores.head.interval, 0)
        self.assertEqual(self.accepted().head.interval, 0)

    def test_file_changed_between_verification_and_replace_refuses(self):
        entry, digest, _ = self.runner_seals_and_exits()
        before = self.catalog.read_bytes()
        stores = self.accepted()
        path = self.root / entry.filename

        def touch(phase):
            if phase == 'catalog_flushed':
                info = path.stat()
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000))
        stores.crash_hook = touch
        with self.assertRaisesRegex(ContractError, 'changed before adoption'):
            stores.adopt_and_promote(entry.filename, **adopting(entry, digest))
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertEqual(list(self.root.glob('catalog.json.tmp-*')), [])
        self.assertEqual(stores.head.interval, 0)

    def test_foreign_workflow_file_refuses(self):
        foreign = self.root / 'foreign'
        foreign.mkdir()
        other = IntervalStoreSet.create_migration(str(foreign / 'catalog.json'), workflow_id='f' * 64, scope=self.sc)
        try:
            candidate = other.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)
            raw = b'foreign interval'
            descriptor = canonical({'dtype': '|u1', 'count': len(raw)})
            _, key = candidate.put_chunk(descriptor, raw)
            root = hashlib.sha256(b'foreign-root').hexdigest()
            locator = SnapshotLocator('f' * 64, 0, root)
            ref = SegmentRef(SEGMENT_REF_SCHEMA, locator, LogicalIdentity('synthetic.component.v1', key, len(raw)),
                             len(raw), BindingIndexRef(BINDING_INDEX_SCHEMA, locator, 'd' * 64, 1), 'e' * 64)
            candidate.put_manifest(root, {'schema': 'atlas.segment-root.v1', 'reference': ref.to_wire()})
            foreign_entry = candidate.seal(ref).entry
        finally:
            other.close()
        mine = self.root / 'mine'
        mine.mkdir()
        shutil.copyfile(foreign / 'interval-0000.sqlite', mine / 'interval-0000.sqlite')
        os.chmod(mine / 'interval-0000.sqlite', stat.S_IREAD)
        foreign_head = foreign_entry.head
        own_head = replace(foreign_head, root_key=replace(foreign_head.root_key, workflow_id=WORKFLOW),
                           array_bindings=replace(foreign_head.array_bindings, root_key=replace(
                               foreign_head.array_bindings.root_key, workflow_id=WORKFLOW)))
        values = dict(expected(foreign_entry), head=own_head)
        with self.assertRaisesRegex(ContractError, "does not carry this workflow's seal"):
            IntervalStoreSet.open_pending(str(mine / 'catalog.json'), 'interval-0000.sqlite', scope=self.sc,
                                          workflow_id=WORKFLOW, expected_catalog_digest=None, **values)
        adopter = self.track(IntervalStoreSet.create_migration(str(mine / 'catalog.json'), workflow_id=WORKFLOW,
                                                               scope=self.sc))
        verdict = I.pending_view_digest(None, foreign_entry)
        with self.assertRaisesRegex(ContractError, "does not carry this workflow's seal"):
            adopter.adopt_and_promote('interval-0000.sqlite', expected_catalog_digest=None,
                                      reader_view_digest=verdict, **values)
        with self.assertRaisesRegex(ContractError, 'invalid pending interval head'):
            adopter.adopt_and_promote('interval-0000.sqlite', **adopting(foreign_entry, None))
        self.assertFalse((mine / 'catalog.json').exists())

    def test_two_adopts_racing_second_sees_compare_and_swap_conflict(self):
        entry, digest, _ = self.runner_seals_and_exits()
        first, second = self.accepted(), self.accepted()
        self.assertEqual(first.adopt_and_promote(entry.filename, **adopting(entry, digest)), entry)
        after = self.catalog.read_bytes()
        with self.assertRaisesRegex(ContractError, 'compare-and-swap conflict'):
            second.adopt_and_promote(entry.filename, **adopting(entry, digest))
        self.assertEqual(self.catalog.read_bytes(), after)
        with self.assertRaisesRegex(ContractError, 'named by the accepted catalog'):
            self.accepted().adopt_and_promote(entry.filename, **adopting(entry, first.catalog_digest))

    def test_quarantine_before_adopt_lock_refuses_adopt(self):
        entry, digest, _ = self.runner_seals_and_exits()
        adopter, other = self.accepted(), self.accepted()
        original, moved = I.publish_catalog, []

        def interleaved(*args, **kwargs):
            if not moved:
                moved.append(other.quarantine_orphan(reason=REASON))
            return original(*args, **kwargs)
        with patch.object(I, 'publish_catalog', interleaved), \
                self.assertRaisesRegex(ContractError, 'changed before adoption'):
            adopter.adopt_and_promote(entry.filename, **adopting(entry, digest))
        self.assertEqual([f['original'] for f in moved[0]['files']], [entry.filename])
        self.assertEqual(adopter.head.interval, 0)
        self.assertEqual(self.accepted().head.interval, 0)
        self.assertEqual(list(self.root.glob('catalog.json.tmp-*')), [])

    def test_quarantine_inside_adopt_lock_is_refused(self):
        entry, digest, _ = self.runner_seals_and_exits()
        adopter, other = self.accepted(), self.accepted()
        attempts = []

        def hook(phase):
            if phase == 'catalog_flushed':
                try:
                    attempts.append(other.quarantine_orphan(reason=REASON))
                except ContractError as exc:
                    attempts.append(exc)
        adopter.crash_hook = hook
        self.assertEqual(adopter.adopt_and_promote(entry.filename, **adopting(entry, digest)), entry)
        self.assertRegex(str(attempts[0]), 'holds the lock')
        self.assertEqual(sha(self.root / entry.filename), entry.file_sha256)
        self.assertEqual(list(self.root.glob('*.quarantined-*')), [])
        with self.assertRaisesRegex(ContractError, 'accepted catalog changed'):
            other.quarantine_orphan(reason=REASON)

    # Crash points between seal and promotion -----------------------------------

    def assert_unlisted_then_explicit_choice(self, entry, digest, *, adopt):
        stores = self.accepted()
        self.assertEqual(stores.head.interval, 0)   # never auto-adopted
        with self.assertRaises(FileExistsError):
            stores.begin_interval(stores.head, producer_identity='b' * 64, runtime_identity='c' * 64)
        if adopt:
            view = self.view(entry, digest)
            self.assertTrue(view.verify_file_sha256(1))
            self.assertEqual(stores.adopt_and_promote(entry.filename, expected_catalog_digest=digest,
                                                      reader_view_digest=view.catalog_digest,
                                                      **expected(entry)), entry)
            self.assertEqual(self.accepted().head, entry)
        else:
            record = stores.quarantine_orphan(reason=REASON)
            self.assertEqual([f['original'] for f in record['files']], [entry.filename])
            candidate, ref, _ = add_interval(stores, [b'after quarantine'])
            self.assertEqual(finish(stores, candidate, ref).interval, 1)

    def test_crash_after_seal_and_after_reader_then_adopt_or_quarantine(self):
        for adopt in (True, False):
            for after_reader in (False, True):
                with self.subTest(adopt=adopt, after_reader=after_reader):
                    entry, digest, _ = self.runner_seals_and_exits()
                    if after_reader:
                        view = self.view(entry, digest)
                        view.verify_file_sha256(1)
                        view.close()   # launcher crash: no adopt, nothing written
                        self.open.remove(view)
                    self.assert_unlisted_then_explicit_choice(entry, digest, adopt=adopt)
                    for stores in self.open:
                        stores.close()
                    self.open.clear()
                    unlock(self.root)
                    for path in self.root.iterdir():
                        path.unlink()

    def test_in_process_crash_inside_adopt(self):
        for phase in ('adopt_verified', 'catalog_flushed', 'catalog_replaced'):
            with self.subTest(phase=phase):
                entry, digest, _ = self.runner_seals_and_exits()
                before = self.catalog.read_bytes()
                stores = self.accepted()

                def crash(p, phase=phase):
                    if p == phase:
                        raise _Crash(p)
                stores.crash_hook = crash
                with self.assertRaises(_Crash):
                    stores.adopt_and_promote(entry.filename, **adopting(entry, digest))
                self.after_adopt_crash(entry, digest, before, phase)
                for opened in self.open:
                    opened.close()
                self.open.clear()
                unlock(self.root)
                for path in self.root.iterdir():
                    path.unlink()

    def after_adopt_crash(self, entry, digest, before, phase):
        reopened = self.accepted()
        if phase == 'catalog_replaced':
            # Committed: the adopted interval is accepted, verified on reopen,
            # never adopted twice and never quarantined.
            self.assertEqual(reopened.head, entry)
            self.assertTrue(reopened.verify_file_sha256(1))
            with self.assertRaisesRegex(ContractError, 'named by the accepted catalog'):
                reopened.adopt_and_promote(entry.filename, **adopting(entry, reopened.catalog_digest))
            self.assertIsNone(reopened.quarantine_orphan(reason=REASON))
            candidate, ref, _ = add_interval(reopened, [b'resume'])
            self.assertEqual(finish(reopened, candidate, ref).interval, 2)
        else:
            self.assertEqual(self.catalog.read_bytes(), before)
            self.assertEqual(reopened.head.interval, 0)
            if phase == 'catalog_flushed':
                # The publish temporary is preserved (interval_catalog rule).
                self.assertEqual(len(list(self.root.glob('catalog.json.tmp-*'))), 1)
            self.assert_unlisted_then_explicit_choice(entry, digest, adopt=True)

    def test_real_process_crash_at_each_point_between_seal_and_promotion(self):
        stores = IntervalStoreSet.create_migration(str(self.catalog), workflow_id=WORKFLOW, scope=self.sc)
        try:
            candidate, ref, _ = add_interval(stores, [b'root interval'])
            finish(stores, candidate, ref)
        finally:
            stores.close()
        original = {p.name: p.read_bytes() for p in self.root.iterdir() if p.name in ('catalog.json', 'interval-0000.sqlite')}
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(HERE), str(RUNTIME), str(HERE.parent))))
        for phase in ('candidate_quiesced', 'seal_written', 'file_sealed',
                      'adopt_verified', 'catalog_flushed', 'catalog_replaced'):
            with self.subTest(phase=phase):
                dest = self.root / phase
                dest.mkdir()
                for name, raw in original.items():
                    (dest / name).write_bytes(raw)
                os.chmod(dest / 'interval-0000.sqlite', stat.S_IREAD)
                record = dest.parent / f'{phase}.json'
                if phase.startswith(('adopt', 'catalog')):
                    seeded = self.track(IntervalStoreSet.open_catalog(str(dest / 'catalog.json'), scope=self.sc))
                    candidate, ref, _ = add_interval(seeded, [b'crash-successor'])
                    entry = candidate.seal(ref).entry
                    seeded.close()
                    self.open.remove(seeded)
                    record.write_text(json.dumps({'entry': entry.to_wire()}))
                result = subprocess.run([sys.executable, '-B', '-c', CHILD, str(dest / 'catalog.json'), phase,
                                         str(record)], capture_output=True, text=True, check=False, env=env, timeout=60)
                self.assertEqual(result.returncode, 72, result.stderr)
                self.catalog = dest / 'catalog.json'
                if phase in ('candidate_quiesced', 'seal_written'):
                    # Not sealed read-only yet: never viewable or adoptable; quarantine is the way on.
                    stores = self.accepted()
                    self.assertEqual(stores.head.interval, 0)
                    self.assertFalse(I._immutable(dest / 'interval-0001.sqlite'))
                    with self.assertRaisesRegex(ContractError, 'not sealed read-only'):
                        stores.adopt_and_promote('interval-0001.sqlite',
                                                 **adopting(stores.head, stores.catalog_digest))
                    self.assertTrue(stores.quarantine_orphan(reason=REASON)['complete'])
                elif phase == 'file_sealed':
                    # The runner crashed after sealing, before its post-seal
                    # record. The explicit recovery takes the head and the two
                    # identities from the runner's durable pre-seal record (the
                    # file does not bind them) and derives the rest from the
                    # file; the reader verifies, then adopt. Without that record
                    # the file is quarantine-only.
                    entry = self.recover_entry(dest, record)
                    self.assert_unlisted_then_explicit_choice(entry, self.accepted().catalog_digest, adopt=True)
                elif phase == 'catalog_replaced':
                    self.assertEqual(self.accepted().head, entry)
                    self.assertTrue(self.accepted().verify_file_sha256(1))
                else:
                    self.assertEqual((dest / 'catalog.json').read_bytes(), original['catalog.json'])
                    self.assert_unlisted_then_explicit_choice(entry, self.accepted().catalog_digest, adopt=True)
                for opened in self.open:
                    opened.close()
                self.open.clear()

    def recover_entry(self, directory, record):
        """What an explicit adopt-after-reader tool reads when the runner crashed after
        sealing but before its post-seal record.

        The sealed file binds only its SHA-256, the logical seal, the parent seal and
        the references. The head SegmentRef and the producer and runtime identities
        come from the runner's durable record written BEFORE the seal; without that
        record the file is quarantine-only (never adopted under guessed values).
        """
        with open(record, encoding='utf-8') as handle:
            durable = json.load(handle)
        stores = self.track(IntervalStoreSet.open_catalog(str(directory / 'catalog.json'), scope=self.sc))
        self.assertEqual(durable['expected_catalog_digest'], stores.catalog_digest)
        path = directory / 'interval-0001.sqlite'
        reader = ReadOnlyNative(path, scope=self.sc)
        try:
            seal = json.loads(reader.manifest(seal_key(WORKFLOW, 1), memo=False))['metadata']
        finally:
            reader.close()
        # What the seal binds; head and identities are not in it.
        self.assertEqual(set(seal), {'schema', 'workflow_id', 'interval', 'logical_seal', 'parent_seal',
                                     'references'})
        head = SegmentRef.from_wire(durable['head'])
        return CatalogEntry(1, path.name, sha(path), seal['logical_seal'], 0, seal['parent_seal'], head,
                            durable['producer_identity'], durable['runtime_identity'],
                            tuple(tuple(p) for p in seal['references']))


class PendingBookingTests(unittest.TestCase):
    """tracemalloc for memory only (nothing timed): real <= booked.

    New allocations: the verification transients (file hash blocks, seal
    manifest parse, inventory scan, head root parse; booked as run-budget
    workspaces) and the decoded catalog with the new entry (booked with
    catalog_retained_charge, the L16 bound). The handle is HANDLE_CHARGE (W1).
    """

    def test_open_pending_and_adopt_booking_covers_python_memory(self):
        TEMP.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='s9b-', dir=TEMP) as temp:
            root = Path(temp)
            catalog = root / 'catalog.json'
            setup = scope()
            stores = IntervalStoreSet.create_migration(str(catalog), workflow_id=WORKFLOW, scope=setup)
            candidate, ref, _ = add_interval(stores, [b'root' * 300])
            finish(stores, candidate, ref)
            digest = stores.catalog_digest
            candidate, ref, _ = add_interval(stores, [bytes([i]) * 4000 for i in range(40)])
            entry = candidate.seal(ref).entry
            stores.close()
            gc.collect()
            setup.close()
            results = {}
            for label in ('open_pending', 'adopt_and_promote'):
                budget = WorkBudget(512 << 20)
                sc = create_retained_scope(budget, process_epoch=f's9a-booking-{label}')
                adopter = IntervalStoreSet.open_catalog(str(catalog), scope=sc) if label == 'adopt_and_promote' else None
                values = adopting(entry, digest)
                gc.collect()
                reserved_before = budget.reserved_bytes
                tracemalloc.start()
                base = tracemalloc.get_traced_memory()[0]
                tracemalloc.reset_peak()
                if adopter is None:
                    held = IntervalStoreSet.open_pending(str(catalog), entry.filename, scope=sc, workflow_id=WORKFLOW,
                                                         expected_catalog_digest=digest, **expected(entry))
                else:
                    adopter.adopt_and_promote(entry.filename, **values)
                    held = adopter
                peak = tracemalloc.get_traced_memory()[1]
                gc.collect()
                current = tracemalloc.get_traced_memory()[0]
                tracemalloc.stop()
                real_peak, real_retained = peak - base, current - base
                booked_peak = budget.peak_reserved_bytes - reserved_before
                results[label] = {'real_peak': real_peak, 'booked_peak_over_start': booked_peak,
                                  'real_retained_growth': real_retained,
                                  'booked_retained_growth': budget.reserved_bytes - reserved_before}
                self.assertLessEqual(real_peak, booked_peak, (label, results[label]))
                held.close()
                gc.collect()
                sc.close()
                self.assertEqual(budget.reserved_bytes, 0)
            # The decoded catalog both hold (accepted entries + the pending entry,
            # byte-identical to the adopted catalog) against its retained charge.
            size = catalog.stat().st_size
            gc.collect()
            tracemalloc.start()
            base = tracemalloc.get_traced_memory()[0]
            held = read_catalog(catalog, expected_size=size)
            retained = tracemalloc.get_traced_memory()[0] - base
            tracemalloc.stop()
            self.assertEqual(held[0].entries[-1], entry)
            results['catalog'] = {'real_retained': retained, 'booked': I.catalog_retained_charge(held[0])}
            self.assertLessEqual(retained, I.catalog_retained_charge(held[0]), results)
            print('s9a booking:', json.dumps(results, sort_keys=True), file=sys.stderr)
            unlock(root)


class CodecAnchorTests(unittest.TestCase):
    def test_wp10_source_patch_anchors_stay_unique(self):
        """storage_codec_integration_patch threads the WP10 policy through
        these exact interval_store_set lines; each must still occur once."""
        source = (HERE / 'interval_store_set.py').read_text(encoding='utf-8')
        anchors = [
            '    def begin_interval(self, parent, *, producer_identity, runtime_identity, cancel=None):\n',
            '                reader = ReadOnlyNative(path, scope=self.scope)\n',
            '            reader = ReadOnlyNative(self.path, scope=self.scope, require_immutable=False)\n',
            '        candidate = UnlistedCandidate(self, producer_identity, runtime_identity, cancel=cancel)\n',
            '    def __init__(self, stores, producer_identity, runtime_identity, *, cancel=None):\n',
            '        self.compression = native.Compression()\n',
            '    def put_chunk(self, descriptor, raw, *, cancel=None):\n',
            ('        owner = self._find_chunk_location(key, descriptor, cancel=cancel)\n'
             '        if owner is not None:\n'),
            '            codec, payload = native.ArrayStore._encode(self, raw, dt)\n',
        ]
        for anchor in anchors:
            self.assertEqual(source.count(anchor), 1, anchor)
        self.assertEqual((HERE / 'segment_store.py').read_text(encoding='utf-8').count(
            '                owner, chunk_id = candidate.put_chunk(descriptor, raw, cancel=cancel)\n'), 1)


if __name__ == '__main__':
    unittest.main()
