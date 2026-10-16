"""WP10 follow-ups: disabled means legacy, exact palette pre-check, schema-qualified keys.

rev2 adds: read scopes book codec work on their own ledger (a read during a put, a
parallel put's check of an existing Blosc2 chunk), use_dict written without Blosc2,
and the pinned 173,397-byte chunk bound of the legacy encode.

Run on its own (it loads transformed storage under the native module name).
Every expected representation comes from the untransformed composed-r1 encode.
Fixture evidence is invented shape-only test data, never an adoption result.
"""
from __future__ import annotations

import importlib.abc
import importlib.util
import os
import pathlib
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
FROZEN = HERE.parent / 'composed-r1' / 'runtime-src'
sys.path.insert(0, str(FROZEN))
sys.path.insert(0, str(HERE))
import storage_codec_integration_patch as integration
import storage_codec_patch as patch
import storage_codec_runtime as codec


class _Source(importlib.abc.SourceLoader):
    """Load given source text as a module; no bytecode cache is read or written."""
    def __init__(self, path, text):
        self.path, self.text = str(path), text

    def get_filename(self, fullname):
        return self.path

    def get_data(self, path):
        return self.text.encode('utf-8')


def _load(name, path, text):
    spec = importlib.util.spec_from_loader(name, _Source(path, text))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_storage():
    path = FROZEN / 'atlas_tectonics' / 'storage.py'
    source = path.read_text(encoding='utf-8')
    importlib.import_module('atlas_tectonics')
    original = _load('atlas_tectonics._wp10_followups_original_storage', path, source)
    candidate = _load('atlas_tectonics.storage', path, patch.transform(source))
    return original, candidate


OLD, STORAGE = load_storage()
import blosc2
from atlas_tectonics.resources import WorkBudget

LEDGER = 'atlas.private.heat-ledger.logical.v1'
PARTITION = 'atlas.compact-partition.v2'
STORE = 'atlas.array-store.v1'
EVIDENCE = {'scope': 'real', 'report_sha256': '1' * 64, 'compression_ratio': 0.2,
            'added_decode_fraction': 0.01, 'cold_saving_bytes': 50 << 20,
            'baseline_total_seconds': 2.0, 'candidate_total_seconds': 1.0}


def disabled(name='raw'):
    return {'codec': name, 'enabled': False}


def policy(arrays=None, default=None, workers=1):
    return {'schema': codec.POLICY_SCHEMA, 'default': default or disabled(), 'arrays': arrays or {},
            'parallel_workers': workers, 'prefetch': False}


def enabled(name):
    return {'codec': name, 'enabled': True, 'evidence': dict(EVIDENCE)}


def receiver(compression, policy_value=None, chunk_bytes=65536):
    """Shaped like the interval writer: no store schema, names arrive qualified."""
    value = types.SimpleNamespace(
        compression=compression, _stats={'encodes': 0}, _budget=WorkBudget(64 << 20),
        _blosc=blosc2 if compression.codec == 'zstd' else None,
        limits=STORAGE.StoreLimits(chunk_bytes, 512 << 20, 4 << 30, max_staging_bytes=1 << 30))
    if policy_value is not None:
        value._codec_policy = codec.normalise_policy(policy_value)
    return value


def legacy(compression, raw, dt):
    reference = types.SimpleNamespace(compression=compression, _stats={'encodes': 0},
                                      _blosc=blosc2 if compression.codec == 'zstd' else None)
    return OLD.ArrayStore._encode(reference, raw, np.dtype(dt))


def chunks():
    """Representative chunks: every legacy outcome, both sides of the 16-value boundary."""
    rng = np.random.default_rng(20261016)
    result = [np.zeros(65536, 'u1'), np.full(8192, 7, '<u8'),
              rng.integers(0, 256, 65536, dtype='u1'),                       # raw
              np.repeat(rng.integers(0, 256, 300, dtype='u1'), 200)[:65536],  # many values, RLE wins
              np.arange(65536, dtype='u4').astype('u1'),                     # 256 values, zstd wins
              rng.integers(0, 16, 65536, dtype='u1'),                        # 16 values, palette wins
              rng.integers(0, 17, 65536, dtype='u1'),                        # 17 values, no palette
              rng.integers(-128, 128, 65536, dtype='i1'),
              rng.integers(0, 2, 65536, dtype='u1').astype('?'),
              np.repeat(rng.integers(0, 40, 64, dtype='u1'), 1024),
              rng.integers(0, 5, 32768, dtype='<u2'), np.arange(8192, dtype='<u8') * 3,
              rng.standard_normal(8192)]
    for n in (2, 3, 4, 5, 15, 16, 17, 18, 64, 255, 256):
        values = rng.permutation(256)[:n].astype('u1')
        result.append(values[rng.integers(0, n, 65536)])
        result.append(np.repeat(values, 65536 // n + 1)[:65536])
    for size in (1, 2, 3, 17, 100, 4097):
        result.append(rng.integers(0, 256, size, dtype='u1'))
    return result


class DisabledMeansLegacyTests(unittest.TestCase):
    def test_no_policy_disabled_and_unlisted_equal_the_untransformed_encode(self):
        policies = [None, policy(), policy({f'{LEDGER}/x': disabled('zstd')}),
                    policy({f'{LEDGER}/other': enabled('delta-v1')})]
        for compression in (STORAGE.Compression(), STORAGE.Compression(codec='raw'),
                            STORAGE.Compression(shuffle='bit', level=3)):
            for index, array in enumerate(chunks()):
                raw, dt = array.tobytes(), array.dtype
                expected = legacy(OLD.Compression(**{f: getattr(compression, f) for f in compression.__slots__}),
                                  raw, dt)
                for value in policies:
                    with self.subTest(compression=compression, chunk=index, policy=value is not None):
                        store = receiver(compression, value)
                        self.assertEqual(STORAGE.ArrayStore._encode(store, raw, dt, array_name=f'{LEDGER}/x'),
                                         expected)
                        self.assertEqual(store._budget.reserved_bytes, 0)
                        self.assertEqual(store._codec_state.budget.reserved_bytes, 0)

    def test_historical_blosc2_encode_is_admitted_under_the_whole_codec_allowance(self):
        store = receiver(STORAGE.Compression(), policy())
        seen = []
        real = blosc2.compress2

        def watch(*args, **kwargs):
            seen.append((store._codec_state.budget.reserved_bytes, store._budget.reserved_bytes))
            return real(*args, **kwargs)
        raw = np.arange(8192, dtype='<u8').tobytes()
        with mock.patch.object(blosc2, 'compress2', side_effect=watch):
            label, payload = STORAGE.ArrayStore._encode(store, raw, np.dtype('<u8'), array_name=f'{LEDGER}/x')
        allowance = store.limits.codec_workspace_bytes
        self.assertTrue(label.startswith('blosc2-zstd-byte:1:'), label)
        self.assertEqual(seen, [(allowance, allowance)])
        self.assertEqual(store._codec_state.budget.reserved_bytes, 0)
        self.assertNotIn(codec._NATIVE_GAP, store._codec_state.fallbacks)
        self.assertEqual(STORAGE.ArrayStore._decode(store, label, payload, np.dtype('<u8'), 8192), raw)
        raw_store = receiver(STORAGE.Compression(codec='raw'))
        observed = []
        real_unique = np.unique

        def unique(*args, **kwargs):
            observed.append(raw_store._codec_state.budget.reserved_bytes)
            return real_unique(*args, **kwargs)
        with mock.patch.object(np, 'unique', side_effect=unique):
            STORAGE.ArrayStore._encode(raw_store, np.arange(4096, dtype='<u2').tobytes(), np.dtype('<u2'))
        self.assertEqual(observed, [65536 + 48 * 8192])

    def test_use_dict_is_written_as_live_wp10_wrote_it_without_blosc2(self):
        # rev2: a Blosc2 dictionary encode peaks at 9-12 MB, above the 8 MiB allowance.
        # Live WP10 wrote such a store without Blosc2; no production writer sets use_dict.
        for config in ({'use_dict': True}, {'level': 9, 'shuffle': 'bit', 'use_dict': True}):
            for index, array in enumerate(chunks()):
                raw, dt = array.tobytes(), array.dtype
                store = receiver(STORAGE.Compression(**config))
                with self.subTest(config=config, chunk=index):
                    with mock.patch.object(blosc2, 'compress2', side_effect=AssertionError('dictionary encode ran')):
                        got = STORAGE.ArrayStore._encode(store, raw, dt)
                    self.assertEqual(got, legacy(OLD.Compression(codec='raw'), raw, dt))
                    self.assertIn(codec._USE_DICT_GAP, store._codec_state.fallbacks)
                    self.assertEqual(store._codec_state.budget.reserved_bytes, 0)
                    self.assertEqual(store._budget.reserved_bytes, 0)

    def test_chunk_size_bound_of_the_legacy_encode_is_pinned(self):
        # Known limit, kept (rev2 documents it; no limit is raised): the legacy encode
        # needs 65536 + 48 n, so the default 8 MiB allowance admits n <= 173,397 B.
        allowance = STORAGE.StoreLimits(65536, 512 << 20, 4 << 30).codec_workspace_bytes
        self.assertEqual((allowance - 65536) // 48, 173397)
        rng = np.random.default_rng(3)
        cases = [(173392, np.cumsum(rng.integers(0, 64, 173392 // 8)).astype('<u8')),
                 (173392, rng.integers(0, 4, 173392, dtype='u1')),
                 (173397, np.repeat(rng.integers(0, 40, 173397, dtype='u1'), 9)[:173397]),
                 (173398, np.repeat(rng.integers(0, 40, 173398, dtype='u1'), 9)[:173398]),
                 (173400, np.cumsum(rng.integers(0, 64, 173400 // 8)).astype('<u8')),
                 (173400, rng.integers(0, 4, 173400, dtype='u1'))]
        for size, array in cases:
            raw = array.tobytes()
            store = receiver(STORAGE.Compression(), chunk_bytes=size)
            with self.subTest(size=size, dtype=array.dtype.str):
                got = STORAGE.ArrayStore._encode(store, raw, array.dtype)
                if size <= 173397:
                    self.assertEqual(got, legacy(OLD.Compression(), raw, array.dtype))
                    self.assertNotEqual(got[0], 'raw')
                else:
                    self.assertEqual(got, ('raw', raw))
                self.assertEqual(store._codec_state.budget.reserved_bytes, 0)

    def test_enabled_rule_still_selects_its_candidate(self):
        offsets = np.arange(8192, dtype='<u8')
        store = receiver(STORAGE.Compression(), policy({f'{LEDGER}/offsets': enabled('delta-v1')}))
        label, _ = STORAGE.ArrayStore._encode(store, offsets.tobytes(), offsets.dtype,
                                               array_name=f'{LEDGER}/offsets')
        self.assertEqual(label, 'delta-v1')
        self.assertEqual(STORAGE.ArrayStore._encode(store, offsets.tobytes(), offsets.dtype,
                                                    array_name=f'{PARTITION}/offsets'),
                         legacy(OLD.Compression(), offsets.tobytes(), offsets.dtype))


class StoreTests(unittest.TestCase):
    def setUp(self):
        scratch = pathlib.Path(os.environ.get('WP10_TEST_ROOT', str(pathlib.Path.cwd() / 'work' / 'wp10-followups')))
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = pathlib.Path(self.temp.name)
        self.budget = WorkBudget(256 << 20)
        self.limits = STORAGE.StoreLimits(65536, 8 << 20, 64 << 20, max_manifest_bytes=65536,
                                          verified_cache_entries=16, sqlite_cache_bytes=4096)
        self.stores = []

    def tearDown(self):
        for store in self.stores:
            store.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temp.cleanup()

    def store(self, name, value=None, compression=None):
        store = STORAGE.ArrayStore(self.root / name, self.limits, compression or STORAGE.Compression(),
                                   budget=self.budget)
        self.stores.append(store)
        if value is not None:
            store.configure_codec_policy(value)
        return store

    def rows(self, store):
        return store._db.execute('SELECT id,descriptor,codec,stored_sha,payload FROM chunks ORDER BY id').fetchall()

    def test_store_rows_equal_without_policy_disabled_and_parallel_preparation(self):
        rng = np.random.default_rng(7)
        arrays = {'kinds': rng.integers(0, 9, 70000, dtype='u1'), 'bytes': rng.integers(0, 256, 70000, dtype='u1'),
                  'offsets': np.cumsum(rng.integers(0, 4, 20000, dtype='<u8')), 'field': rng.standard_normal(9000)}
        expected = self.store('none.sqlite')
        expected.put('1' * 64, arrays)
        for name, value in (('disabled.sqlite', policy({f'{STORE}/kinds': disabled('palette')})),
                            ('parallel.sqlite', policy(workers=2))):
            with self.subTest(name=name):
                store = self.store(name, value)
                store.put('1' * 64, arrays)
                self.assertEqual(self.rows(store), self.rows(expected))
                self.assertEqual(store.codec_statistics()['workspace']['reserved_bytes'], 0)
        labels = {row[2].split(':', 1)[0] for row in self.rows(expected)}
        self.assertIn('blosc2-zstd-byte', labels)

    def test_parallel_preparation_reuses_an_existing_blosc2_chunk(self):
        # rev2 (refuter p_parallel_dedupe): the enabled class's preparation slots sit on the
        # stage ledger while the consumer authenticates an existing Blosc2 row. That check
        # runs in its own read scope, funded by its own reservation, so it is admitted.
        offsets = np.cumsum(np.random.default_rng(5).integers(0, 64, 40000)).astype('<u8')
        store = self.store('pdedupe.sqlite', policy({f'{STORE}/b': enabled('delta-v1')}, workers=2))
        store.put('1' * 64, {'a': offsets})
        before = self.rows(store)
        self.assertTrue(all(row[2].startswith('blosc2-zstd-byte:') for row in before))
        store.put('2' * 64, {'b': offsets})
        self.assertEqual(self.rows(store), before)
        np.testing.assert_array_equal(store.get('2' * 64)['b'], offsets)
        self.assertEqual(store.codec_statistics()['workspace']['reserved_bytes'], 0)

    def test_a_read_during_a_put_books_on_its_own_codec_ledger(self):
        # rev2 (refuter p_concurrency): a get() while a put on the same instance holds the
        # whole store ledger for its Blosc2 encode was refused. Each read scope reserves its
        # own codec allowance on the store budget and books its decodes against that.
        rng = np.random.default_rng(9)
        arrays = {'kinds': rng.integers(0, 4, 65536, dtype='u1'), 'field': rng.standard_normal(4096)}
        store = self.store('read.sqlite')
        store.put('1' * 64, arrays)
        started, release, errors = threading.Event(), threading.Event(), []
        real = blosc2.compress2

        def held(*args, **kwargs):
            started.set()
            release.wait(20)
            return real(*args, **kwargs)

        def write():
            try:
                store.put('2' * 64, {'offsets': np.arange(8192, dtype='<u8') * 3})
            except BaseException as exc:  # noqa: BLE001 - asserted below
                errors.append(exc)
        with mock.patch.object(blosc2, 'compress2', side_effect=held):
            writer = threading.Thread(target=write)
            writer.start()
            try:
                self.assertTrue(started.wait(20))
                self.assertEqual(store.codec_statistics()['workspace']['reserved_bytes'],
                                 self.limits.codec_workspace_bytes)
                got = store.get('1' * 64)
            finally:
                release.set()
                writer.join(30)
        self.assertEqual(errors, [])
        for name, array in arrays.items():
            np.testing.assert_array_equal(got[name], array)
        self.assertEqual(store.codec_statistics()['workspace']['reserved_bytes'], 0)

    def test_array_store_keys_are_qualified_by_the_store_schema(self):
        offsets = np.arange(8192, dtype='<u8')
        with self.assertRaisesRegex(ValueError, 'record_schema>/<column'):
            self.store('bare.sqlite', policy({'offsets': enabled('delta-v1')}))
        store = self.store('qualified.sqlite', policy({f'{STORE}/offsets': enabled('delta-v1')}))
        store.put('2' * 64, {'offsets': offsets, 'other': offsets + 1})
        labels = [row[0] for row in store._db.execute('SELECT codec FROM chunks')]
        self.assertEqual(len(labels), 2)
        self.assertEqual(sum(label == 'delta-v1' for label in labels), 1, labels)


class PalettePrecheckTests(unittest.TestCase):
    def test_precheck_is_exactly_more_than_sixteen_one_byte_values(self):
        rng = np.random.default_rng(3)
        for n in range(1, 257):
            values = rng.permutation(256)[:n].astype('u1')
            array = values[rng.integers(0, n, 4096)]
            array[:n] = values
            with self.subTest(n=n):
                self.assertEqual(codec._palette_cannot_win(array.tobytes(), np.dtype('u1')), n > 16)
                self.assertEqual(codec._palette_cannot_win(array.view('i1').tobytes(), np.dtype('i1')), n > 16)
        wide = np.arange(4096, dtype='<u2')
        self.assertFalse(codec._palette_cannot_win(wide.tobytes(), wide.dtype))
        self.assertFalse(codec._palette_cannot_win(bytes(range(256)) * 4, np.dtype('?')))

    def test_skipped_palette_never_sorts_and_keeps_bytes(self):
        array = np.random.default_rng(5).integers(0, 17, 65536, dtype='u1')
        array[:17] = np.arange(17)
        raw = array.tobytes()
        expected = legacy(OLD.Compression(), raw, array.dtype)
        store = receiver(STORAGE.Compression())
        with mock.patch.object(np, 'unique', side_effect=AssertionError('palette scan ran')):
            self.assertEqual(STORAGE.ArrayStore._encode(store, raw, array.dtype), expected)
            self.assertEqual(codec.encode_candidate(store, raw, array.dtype, enabled('palette')),
                             codec._categorical(raw, array.dtype))
        self.assertEqual(store._stats['encodes'], 1)

    def test_candidate_palette_and_delta_equal_the_full_scan(self):
        store = receiver(STORAGE.Compression(codec='raw'))
        real = codec._palette_cannot_win
        for index, array in enumerate(chunks()):
            raw, dt = array.tobytes(), array.dtype
            for rule in ('palette', 'delta-v1'):
                with self.subTest(chunk=index, rule=rule):
                    fast = codec.encode_candidate(store, raw, dt, enabled(rule))
                    with mock.patch.object(codec, '_palette_cannot_win', return_value=False):
                        full = codec.encode_candidate(store, raw, dt, enabled(rule))
                    self.assertEqual(fast, full)
        self.assertIs(codec._palette_cannot_win, real)


class PolicyKeyTests(unittest.TestCase):
    def test_bare_or_malformed_keys_refuse_and_qualified_keys_normalise(self):
        for key in ('node.kind', '/node.kind', f'{LEDGER}/', 'a b/c', 'a/b\n', f' {LEDGER}/node.kind'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'record_schema>/<column|array name'):
                codec.normalise_policy(policy({key: disabled()}))
        frozen = codec.normalise_policy(policy({f'{LEDGER}/node.kind': enabled('palette'),
                                                f'{PARTITION}/node.kind': disabled()}))
        self.assertTrue(frozen.for_array(f'{LEDGER}/node.kind').enabled)
        self.assertFalse(frozen.for_array(f'{PARTITION}/node.kind').enabled)
        self.assertFalse(frozen.for_array('node.kind').enabled)
        self.assertEqual(codec.normalise_policy(frozen), frozen)

    def test_ledger_rule_does_not_reach_a_partition_column_of_the_same_name(self):
        kinds = np.repeat(np.arange(9, dtype='u1'), 4000)
        store = receiver(STORAGE.Compression(), policy({f'{LEDGER}/node.kind': enabled('palette')}))
        hot = STORAGE.ArrayStore._encode(store, kinds.tobytes(), kinds.dtype, array_name=f'{PARTITION}/node.kind')
        cold = STORAGE.ArrayStore._encode(store, kinds.tobytes(), kinds.dtype, array_name=f'{LEDGER}/node.kind')
        self.assertEqual(hot, legacy(OLD.Compression(), kinds.tobytes(), kinds.dtype))
        self.assertEqual(cold, codec._categorical(kinds.tobytes(), kinds.dtype))

    def test_segment_source_passes_record_schema_qualified_names(self):
        source = (HERE / 'segment_store.py').read_text(encoding='utf-8')
        transformed = integration.segment_source(source)
        # identity.record_schema is publish()'s record_schema (required equal) and is in
        # scope inside _publish_arrays, where the storage generation moved the chunk loop.
        self.assertIn("array_name=identity.record_schema + '/' + info.name", transformed)
        self.assertNotIn('array_name=info.name)', transformed)
        compile(transformed, '<wp10-segment-candidate>', 'exec')

    def test_shipped_policies_normalise(self):
        shipped = codec.read_policy(HERE / 'codec_policy.json')
        self.assertEqual(shipped.arrays, ())
        proposed = pathlib.Path(os.environ.get('WP10_PROPOSED_POLICY', ''))
        if proposed.is_file():
            frozen = codec.read_policy(proposed)
            self.assertTrue(all(key.startswith(('atlas.private.heat-ledger.logical.v1/',
                                                'atlas.private.heat-fields.v1/')) for key, _ in frozen.arrays))
            self.assertFalse(any(rule.enabled for _, rule in frozen.arrays))


if __name__ == '__main__':
    unittest.main()
