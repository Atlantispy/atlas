"""WP10 synthetic sealed-reader/segment integration, without shared source edits.

Run separately: this process loads transformed source under the native module
name. The fixture policy evidence tests the gate's shape; it is deliberately
invented test data, never a real measurement or an adoption recommendation.
"""
from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / 'composed-r1' / 'runtime-src'
sys.path[:0] = [str(HERE), str(RUNTIME)]

from storage_codec_integration_patch import interval_source, segment_source
from storage_codec_patch import transform


def _candidate_module(name, path, code):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(code, str(path) + '[wp10-candidate]', 'exec'), module.__dict__)
    return module


import atlas_tectonics
from atlas_tectonics import storage as original_storage
from atlas_tectonics.resources import WorkBudget

native_path = RUNTIME / 'atlas_tectonics' / 'storage.py'
candidate_storage = _candidate_module('atlas_tectonics.storage', native_path,
    transform(native_path.read_text(encoding='utf-8')))
atlas_tectonics.storage = candidate_storage
intervals = _candidate_module('interval_store_set', HERE / 'interval_store_set.py',
    interval_source((HERE / 'interval_store_set.py').read_text(encoding='utf-8')))
segments = _candidate_module('segment_store', HERE / 'segment_store.py',
    segment_source((HERE / 'segment_store.py').read_text(encoding='utf-8')))

from compact_contracts import LogicalIdentity, SegmentRef
from content_cache import ChargeSpec, OwnedStream, create_retained_scope


def fixture_policy(schema='wp10.fixture.v1'):
    # Shape-only test evidence. The shipped codec_policy.json enables nothing.
    # Keys are '<record_schema>/<column>', as segment_source passes them.
    return dict(schema='atlas.codec-policy.v1', default=dict(codec='raw', enabled=False),
        arrays={schema + '/offsets': dict(codec='delta-v1', enabled=True, evidence=dict(
            scope='real', report_sha256='1' * 64, compression_ratio=0.2,
            added_decode_fraction=0.01, cold_saving_bytes=50 << 20,
            baseline_total_seconds=2.0, candidate_total_seconds=1.0))},
        parallel_workers=1, prefetch=False)


FIXTURE_SCHEMA = 'wp10.fixture.v1'


class Source:
    def __init__(self, scope, name, array):
        self.scope, self.array = scope, array
        self.info = segments.ArrayInfo(name, array.dtype.str, array.shape, array.nbytes)

    def blocks(self, *, max_owned_bytes):
        def generate():
            width = max_owned_bytes // self.array.dtype.itemsize
            for start in range(0, len(self.array), width):
                part = self.array[start:start + width]
                with self.scope.reserve(ChargeSpec('wp10-input', part.nbytes)) as reservation:
                    yield reservation.commit(part.tobytes())
        return OwnedStream(generate(), scope=self.scope)


def _read_hash(stores, reference, scope, name):
    view = segments.SegmentBackend().open(stores, reference, scope=scope)
    try:
        # A small fixture still traverses real compact segment/index structures.
        with view.read(name, 0, 3 * 8192, max_owned_bytes=3 * 65536) as owned:
            return hashlib.sha256(owned.value).hexdigest()
    finally:
        view.close()


class WP10IntegrationTests(unittest.TestCase):
    def setUp(self):
        # Default under the system temporary folder: from the live compact folder, cwd-based
        # scratch plus a catalog temp name (about 49 characters) passes Windows MAX_PATH (260).
        scratch = Path(os.environ.get('WP10_TEST_ROOT', str(Path(tempfile.gettempdir()) / 'wp10-tests')))
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='sealed-', dir=scratch)
        self.root = Path(self.temp.name)
        self.budget = WorkBudget(512 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='wp10-integration-fixture')
        self.stores = intervals.IntervalStoreSet.create_migration(self.root / 'catalog.json',
            workflow_id='a' * 64, scope=self.scope)

    def tearDown(self):
        self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        for path in self.root.rglob('*'):
            if path.is_file():
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        self.temp.cleanup()

    def publish(self, offsets, *, key, policy):
        candidate = self.stores.begin_interval(self.stores.head,
            producer_identity='b' * 64, runtime_identity='c' * 64, codec_policy=policy)
        values = np.arange(3 * 8192, dtype='<f8') * 0.25
        identity = LogicalIdentity('wp10.fixture.v1', hashlib.sha256(key.encode()).hexdigest(), offsets.nbytes)
        sources = [Source(self.scope, 'offsets', offsets), Source(self.scope, 'values', values)]
        reference = segments.SegmentBackend().publish(candidate, record_schema=identity.record_schema,
            identity=identity, metadata=b'{}', arrays=lambda: iter(sources), producer='b' * 64,
            representation_profile='wp10.fixture.columns.v1', scope=self.scope)
        return candidate, reference

    def promote(self, candidate, reference):
        sealed = candidate.seal(reference)
        return self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)

    def test_new_codec_survives_seal_and_independent_fresh_reader(self):
        offsets = np.arange(3 * 8192, dtype='<u8')
        candidate, reference = self.publish(offsets, key='compressed', policy=fixture_policy())
        labels = [row[0] for row in candidate._db.execute('SELECT codec FROM chunks')]
        self.assertTrue(any(label.startswith('delta-v1') for label in labels), labels)
        self.promote(candidate, reference)
        expected = hashlib.sha256(offsets.tobytes()).hexdigest()
        self.assertEqual(_read_hash(self.stores, reference, self.scope, 'offsets'), expected)
        self.stores.close()
        completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--fresh',
            str(self.root / 'catalog.json'), json.dumps(reference.to_wire()), expected],
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('wp10-fresh-reader-pass', completed.stdout)

    def test_raw_ancestor_reused_while_only_changed_chunk_uses_delta(self):
        offsets = np.arange(3 * 8192, dtype='<u8')
        default = json.loads((HERE / 'codec_policy.json').read_text(encoding='utf-8'))
        first, ref = self.publish(offsets, key='raw', policy=default)
        first_entry = self.promote(first, ref)
        original_bytes = (self.root / first_entry.filename).read_bytes()
        changed = offsets.copy()
        changed[-8192:] += 100
        second, newer = self.publish(changed, key='changed', policy=fixture_policy())
        self.assertEqual(second.local_statistics()['local_chunks'], 1)
        self.promote(second, newer)
        self.assertEqual((self.root / first_entry.filename).read_bytes(), original_bytes)
        self.assertEqual(_read_hash(self.stores, newer, self.scope, 'offsets'),
                         hashlib.sha256(changed.tobytes()).hexdigest())
        self.assertEqual(_read_hash(self.stores, ref, self.scope, 'offsets'),
                         hashlib.sha256(offsets.tobytes()).hexdigest())

    def test_no_policy_disabled_and_other_schema_rules_write_identical_rows(self):
        # Disabled, unlisted and foreign-schema classes all keep the writer's own
        # pre-WP10 bytes, including its Blosc2 zstd; only an enabled matching rule differs.
        offsets = np.arange(3 * 8192, dtype='<u8')
        default = json.loads((HERE / 'codec_policy.json').read_text(encoding='utf-8'))
        rows = {}
        for label, policy in (('none', None), ('shipped', default),
                              ('other-schema', fixture_policy('another.record.v1')),
                              ('matching', fixture_policy())):
            (self.root / label).mkdir()
            stores = intervals.IntervalStoreSet.create_migration(self.root / label / 'catalog.json',
                workflow_id='a' * 64, scope=self.scope)
            original, self.stores = self.stores, stores
            try:
                candidate, _ = self.publish(offsets, key='same', policy=policy)
                rows[label] = candidate._db.execute(
                    'SELECT id,descriptor,codec,stored_sha,payload FROM chunks ORDER BY id').fetchall()
                candidate.close()
            finally:
                self.stores = original
                stores.close()
        self.assertEqual(rows['shipped'], rows['none'])
        self.assertEqual(rows['other-schema'], rows['none'])
        self.assertNotEqual(rows['matching'], rows['none'])
        self.assertTrue(any(row[2].startswith('blosc2-zstd-byte:') for row in rows['none']), rows['none'])
        self.assertTrue(any(row[2] == 'delta-v1' for row in rows['matching']))

    def test_chunk_codec_work_books_only_the_writer_reservation(self):
        # rev2 (refuter p_booking): put_chunk reserves codec_workspace_bytes + 32 chunks on
        # the run budget around its encode and verification decode, and a chunk the
        # candidate already holds is decoded under codec_workspace_bytes + 8 chunks. WP10
        # books its work inside those reservations (on the candidate's codec ledger),
        # never on the run budget a second time, so today's headroom admits every kind.
        from atlas_tectonics.resources import MemoryLimitError
        chunk, allowance = intervals.NATIVE_CHUNK_BYTES, intervals.LIMITS.codec_workspace_bytes
        rng = np.random.default_rng(1)
        arrays = {'blosc2-zstd-byte': np.arange(8192, dtype='<u8') * 3,
                  'raw': rng.integers(0, 256, 65536, dtype='u1'),
                  'palette-packed-v1': rng.integers(0, 4, 65536, dtype='u1')}
        total = 512 << 20
        trial = 0

        def put(array, headroom, *, again):
            nonlocal trial
            trial += 1
            (self.root / f'booking-{trial}').mkdir()
            stores = intervals.IntervalStoreSet.create_migration(self.root / f'booking-{trial}' / 'catalog.json',
                workflow_id='a' * 64, scope=self.scope)
            candidate = stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)
            try:
                descriptor = intervals.canonical({'dtype': array.dtype.str, 'count': int(array.size)})
                if again:
                    candidate.put_chunk(descriptor, array.tobytes())
                with self.budget.reserve(total - self.budget.reserved_bytes - headroom, category='ballast'):
                    try:
                        candidate.put_chunk(descriptor, array.tobytes())
                    except MemoryLimitError:
                        return None
                self.assertEqual(candidate._codec_state.budget.reserved_bytes, 0)
                return candidate._db.execute('SELECT codec FROM chunks').fetchone()[0].split(':', 1)[0]
            finally:
                candidate.close()
                stores.close()
        encode_need, decode_need = allowance + 32 * chunk, allowance + 8 * chunk
        for label, array in arrays.items():
            with self.subTest(label=label):
                self.assertEqual(put(array, encode_need, again=False), label)
                self.assertIsNone(put(array, encode_need - 4096, again=False))
                # Own-chunk decode: the reservation plus its owned output (two chunks of slack).
                self.assertEqual(put(array, decode_need + 2 * chunk, again=True), label)
                self.assertIsNone(put(array, decode_need - 4096, again=True))

    def test_sealed_chunk_decode_books_only_the_reader_reservation(self):
        # R1-batch storage (pre-existing in live WP10): IntervalStoreSet.resolve_chunk reserves
        # codec_workspace_bytes + 8 chunks on the run budget around a sealed interval's chunk
        # decode, and WP10's decode inside it booked on the run budget again (8 MiB more for a
        # Blosc2 row, 1.06 MiB more for a palette row). It now books on the reader's own codec
        # ledger, so today's reservation plus the owned output admits every kind.
        from atlas_tectonics.resources import MemoryLimitError
        chunk, allowance = intervals.NATIVE_CHUNK_BYTES, intervals.LIMITS.codec_workspace_bytes
        rng = np.random.default_rng(1)
        arrays = {'blosc2-zstd-byte': np.arange(8192, dtype='<u8') * 3,
                  'raw': rng.integers(0, 256, 65536, dtype='u1'),
                  'palette-packed-v1': rng.integers(0, 4, 65536, dtype='u1')}
        candidate = self.stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)
        identity = LogicalIdentity(FIXTURE_SCHEMA, hashlib.sha256(b'sealed-decode').hexdigest(), 3 * 65536)
        sources = sorted((Source(self.scope, name.split('-')[0], array) for name, array in arrays.items()),
                         key=lambda source: source.info.name)       # segment names are in UTF-8 order
        reference = segments.SegmentBackend().publish(candidate, record_schema=identity.record_schema,
            identity=identity, metadata=b'{}', arrays=lambda: iter(sources), producer='b' * 64,
            representation_profile='wp10.fixture.columns.v1', scope=self.scope)
        expected = {intervals.canonical({'dtype': array.dtype.str, 'count': int(array.size)}) + b'|' +
                    array.tobytes(): label for label, array in arrays.items()}
        rows = {}
        for key, descriptor, codec in candidate._db.execute('SELECT id,descriptor,codec FROM chunks'):
            rows.setdefault(codec.split(':', 1)[0], []).append((key, descriptor))
        self.assertTrue(set(arrays) <= set(rows), sorted(rows))
        self.promote(candidate, reference)
        interval = self.stores.head.interval
        total = 512 << 20
        decode_need = allowance + 8 * chunk

        def read(key, descriptor, headroom=None):
            if headroom is None:
                owned = self.stores.resolve_chunk(interval, interval, key, descriptor)
            else:
                with self.budget.reserve(total - self.budget.reserved_bytes - headroom, category='ballast'):
                    try:
                        owned = self.stores.resolve_chunk(interval, interval, key, descriptor)
                    except MemoryLimitError:
                        return None
            with owned:
                return descriptor + b'|' + bytes(owned.value)

        found = set()
        for label in arrays:
            for key, descriptor in rows[label]:
                with self.subTest(label=label, chunk=key[:12]):
                    read(key, descriptor)                  # opens the sealed handle outside the ballast
                    content = read(key, descriptor, decode_need + 2 * chunk)
                    self.assertIsNotNone(content)
                    found.add(expected.get(content))
                    self.assertIsNone(read(key, descriptor, decode_need - 4096))
        self.assertTrue(set(arrays) <= found, found)        # each kind was one of this fixture's arrays
        reader = self.stores._handles[interval].value
        self.assertEqual(reader._codec_state.budget.reserved_bytes, 0)

    def test_invalid_policy_refuses_before_candidate_file_exists(self):
        policy = fixture_policy()
        policy['parallel_workers'] = 3
        with self.assertRaises(ValueError):
            self.stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64,
                                       codec_policy=policy)
        self.assertFalse((self.root / 'interval-0000.sqlite').exists())

    def test_transforms_refuse_changed_or_already_transformed_sources(self):
        for name, patch in [('interval_store_set.py', interval_source), ('segment_store.py', segment_source)]:
            source = (HERE / name).read_text(encoding='utf-8')
            with self.assertRaises(ValueError):
                patch(source + '\n# changed\n')
            with self.assertRaises(ValueError):
                patch(patch(source))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fresh':
        budget = WorkBudget(512 << 20)
        scope = create_retained_scope(budget, process_epoch='wp10-fresh-reader')
        stores = intervals.IntervalStoreSet.open_catalog(sys.argv[2], scope=scope)
        try:
            assert _read_hash(stores, SegmentRef.from_wire(json.loads(sys.argv[3])), scope, 'offsets') == sys.argv[4]
            assert stores.verify_file_sha256(stores.head.interval)
        finally:
            stores.close()
            scope.close()
        assert budget.reserved_bytes == 0
        print('wp10-fresh-reader-pass')
    else:
        unittest.main()
