"""WP12 bounded, synthetic sealed-store sidecar contract tests.

These are small real IntervalStoreSet fixtures, not historical WP0b evidence.
No test changes the default adoption state or invokes a long-running probe.
"""
from concurrent.futures import CancelledError
import gc
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(RUNTIME), str(HERE.parent)]
SCRATCH = (Path('C:/Users/LOCAL_USER/Documents/Codex/2026-10-15') /
           'c-Users-LOCAL_USER-documents-codex-2026-2/work/wp12-tests')

from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError, LogicalIdentity, RETAINED_BYTES
from content_cache import ChargeSpec, create_retained_scope
from interval_store_set import IntervalStoreSet
from raw_sidecar_store import RawSidecarStore, assess_adoption
import raw_sidecar_store as RS
import segment_store as S


class RawSidecarStoreTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='sidecar-', dir=SCRATCH)
        self.root = Path(self.temp.name)
        self.assertTrue(self.root.resolve().is_relative_to(SCRATCH.resolve()))
        self.budget = WorkBudget(512 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='wp12-fixture')
        self.stores = IntervalStoreSet.create_migration(
            self.root / 'catalog.json', workflow_id='a' * 64, scope=self.scope)
        self.candidate = self.stores.begin_interval(
            None, producer_identity='b' * 64, runtime_identity='c' * 64)
        self.backend = S.SegmentBackend()
        self.arrays = {
            'ints': np.arange(18000, dtype='<i4').reshape(3, 6000),
            'empty': np.empty((0, 3), dtype='<u2'),
            'floats': np.array([[0.0, -0.0, 1e100],
                                [-1e100, 5e-324, 1.25]], dtype='<f8'),
            'little': (np.arange(18000, dtype='<i4') * 7 + 11),
        }
        sources, owners = [], []
        try:
            for name, value in sorted(self.arrays.items()):
                raw = value.tobytes(order='C')
                owner = self.scope.reserve(ChargeSpec('fixture-input', len(raw))).commit(raw)
                owners.append(owner)
                sources.append(S.BytesArraySource(
                    S.ArrayInfo(name, value.dtype.str, value.shape, value.nbytes), owner))
            identity = LogicalIdentity('fixture.raw-sidecar.v1', sha256(b'wp12').hexdigest(), 1)
            self.ref = self.backend.publish(
                self.candidate, record_schema=identity.record_schema, identity=identity,
                metadata=b'{}', arrays=lambda: iter(sources), producer='b' * 64,
                representation_profile='fixture.raw-sidecar.columns.v1', scope=self.scope)
        finally:
            for source in sources:
                source.close()
            for owner in owners:
                owner.close()
        sealed = self.candidate.seal(self.ref)
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
        self.view = self.backend.open(self.stores, self.ref, scope=self.scope)
        self.views = [self.view]
        self.other_candidates = []
        self.caches = []
        self.cache_dir = self.root / 'raw-cache'

    def tearDown(self):
        for cache in reversed(self.caches):
            cache.close()
        gc.collect()
        for view in reversed(self.views):
            view.close()
        for candidate in self.other_candidates:
            candidate.close()
        self.candidate.close()
        self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        # The immutable source/sidecar files can be read-only on Windows.
        for path in self.root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.temp.cleanup()

    def cache(self, *, names=('ints', 'empty', 'floats', 'little'), enabled=True,
              experimental=True, cache_dir=None, view=None):
        result = RawSidecarStore(view or self.view, cache_dir or self.cache_dir,
                                 array_names=names, enabled=enabled,
                                 experimental=experimental)
        self.caches.append(result)
        return result

    def built(self, **kwargs):
        result = self.cache(**kwargs)
        self.assertIsInstance(result.build(), dict)
        return result

    def assert_exact(self, borrowed, name, start, stop):
        expected = self.arrays[name].reshape(-1)[start:stop]
        self.assertIsInstance(borrowed.value, np.ndarray)
        self.assertEqual(borrowed.value.shape, (stop - start,))
        self.assertEqual(borrowed.value.dtype.str, expected.dtype.str)
        self.assertEqual(borrowed.value.tobytes(), expected.tobytes())
        self.assertFalse(borrowed.value.flags.writeable)

    def change_bytes(self, path, data):
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        path.write_bytes(data)
        os.chmod(path, stat.S_IREAD)

    def test_exact_flat_slices_preserve_endian_float_bits_and_empty_arrays(self):
        cache = self.built()
        cases = [('ints', 0, 18000), ('ints', 16380, 16391), ('little', 3, 19),
                 ('floats', 0, 6), ('empty', 0, 0), ('ints', 18000, 18000)]
        for name, start, stop in cases:
            with self.subTest(name=name, start=start, stop=stop):
                allowance = (stop - start) * self.arrays[name].dtype.itemsize
                with cache.read(name, start, stop, max_owned_bytes=allowance) as borrowed:
                    self.assert_exact(borrowed, name, start, stop)
                    with self.assertRaises(ValueError):
                        borrowed.value.flags.writeable = True
                    if stop > start:
                        with self.assertRaises(ValueError):
                            borrowed.value[0] = 99

    def test_build_writes_only_selected_content_addressed_arrays_and_reuses_them(self):
        cache = self.built(names=('ints', 'empty'))
        paths = [cache.sidecar_path(name) for name in ('ints', 'empty')]
        self.assertEqual(set(self.cache_dir.iterdir()), set(paths))
        identities = {}
        for name, path in zip(('ints', 'empty'), paths, strict=True):
            self.assertRegex(path.name, r'^raw-[0-9a-f]{64}\.bin$')
            self.assertEqual(path.read_bytes(), self.arrays[name].tobytes())
            identities[path] = (path.stat().st_ino, path.stat().st_mtime_ns)
        cache.build()
        self.assertEqual(identities, {path: (path.stat().st_ino, path.stat().st_mtime_ns)
                                      for path in paths})
        self.assertIsInstance(json.loads(json.dumps(cache.stats())), dict)

    def test_explicit_disabled_never_builds_or_maps_and_uses_ordinary_read(self):
        cache = RawSidecarStore(self.view, self.cache_dir, array_names=('ints',), enabled=False)
        self.caches.append(cache)
        with patch.object(self.view, 'read', wraps=self.view.read) as ordinary:
            with cache.read('ints', 8, 12, max_owned_bytes=16) as borrowed:
                self.assert_exact(borrowed, 'ints', 8, 12)
            ordinary.assert_called_once_with('ints', 8, 12, max_owned_bytes=16)
        with self.assertRaises(ContractError):
            cache.build()
        self.assertEqual(cache.stats()['activation_status'], 'DISABLED')
        self.assertFalse(cache.stats()['enabled'])
        self.assertFalse(cache.stats()['representative_wp0b_gate_passed'])
        self.assertIsNone(cache.stats()['activation_decision_id'])
        self.assertFalse(self.cache_dir.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows mapping/locking contract')
    def test_default_activation_records_user_authority_and_maps_without_claiming_wp0b_gate(self):
        cache = RawSidecarStore(self.view, self.cache_dir, array_names=('ints',))
        self.caches.append(cache)
        self.assertFalse(self.cache_dir.exists())
        cache.build()
        with cache.read('ints', 8, 12, max_owned_bytes=16) as borrowed:
            self.assert_exact(borrowed, 'ints', 8, 12)
            self.assertTrue(borrowed.mapped)
        state = cache.stats()
        self.assertTrue(state['enabled'])
        self.assertFalse(state['experimental'])
        self.assertEqual(state['activation_status'], 'ENABLED_USER_AUTHORISED')
        self.assertEqual(state['activation_decision_id'], 'wp12-user-activate-20261015')
        self.assertFalse(state['representative_wp0b_gate_passed'])
        self.assertEqual(state['mapped_reads'], 1)

    def test_explicit_partial_or_synthetic_adoption_evidence_still_refuses(self):
        for evidence in ({}, {'schema': 'atlas.raw-sidecar-adoption.v1'},
                         adoption_fixture(source_kind='synthetic')):
            with self.subTest(evidence=evidence), self.assertRaises(ContractError):
                RawSidecarStore(self.view, self.cache_dir, array_names=('ints',),
                                adoption_evidence=evidence)
        self.assertFalse(self.cache_dir.exists())

    def test_candidate_views_cannot_enable_sidecars(self):
        candidate = self.stores.begin_interval(
            self.stores.head, producer_identity='b' * 64, runtime_identity='c' * 64)
        self.other_candidates.append(candidate)
        view = self.backend.open(candidate, self.ref, scope=self.scope)
        self.views.append(view)
        with self.assertRaises(ContractError):
            self.cache(view=view)
        self.assertFalse(self.cache_dir.exists())

    def test_absent_cache_falls_back_without_implicit_build(self):
        cache = RawSidecarStore(self.view, self.cache_dir, array_names=('ints',))
        self.caches.append(cache)
        with patch.object(self.view, 'read', wraps=self.view.read) as ordinary:
            with cache.read('ints', 0, 5, max_owned_bytes=20) as borrowed:
                self.assert_exact(borrowed, 'ints', 0, 5)
            self.assertEqual(ordinary.call_count, 1)
        self.assertFalse(self.cache_dir.exists())

    def test_deleted_sidecar_falls_back_and_explicit_build_repairs_missing_file(self):
        cache = self.built(names=('ints',))
        path = cache.sidecar_path('ints')
        cache.close()
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        path.unlink()
        cache = self.cache(names=('ints',))
        with patch.object(self.view, 'read', wraps=self.view.read) as ordinary:
            with cache.read('ints', 6, 11, max_owned_bytes=20) as borrowed:
                self.assert_exact(borrowed, 'ints', 6, 11)
            self.assertEqual(ordinary.call_count, 1)
        self.assertFalse(path.exists())
        cache.build()
        self.assertEqual(path.read_bytes(), self.arrays['ints'].tobytes())

    @unittest.skipUnless(os.name == 'nt', 'Windows mapping/locking contract')
    def test_verified_repeated_mapped_reads_do_not_decode_source_payload_again(self):
        cache = self.built(names=('ints',))
        with patch.object(self.stores, 'resolve_chunk',
                          side_effect=AssertionError('verified sidecar decoded source again')), \
             patch.object(self.view, 'read', side_effect=AssertionError('mapped path fell back')):
            for start in (5, 16380, 17990):
                with cache.read('ints', start, start + 5, max_owned_bytes=20) as borrowed:
                    self.assert_exact(borrowed, 'ints', start, start + 5)

    @unittest.skipUnless(os.name == 'nt', 'Windows mapping/locking contract')
    def test_escaped_numpy_and_memoryview_aliases_keep_shared_charge_after_close(self):
        cache = self.built(names=('ints',))
        baseline = self.scope.stats().retained_bytes
        borrowed = cache.read('ints', 16380, 16391, max_owned_bytes=44)
        raw = borrowed.value
        asarray = np.asarray(raw)
        sliced = asarray[2:8]
        memory = memoryview(sliced)
        live = self.scope.stats().retained_bytes
        mapped = cache.stats()['live_mapped_bytes']
        self.assertGreater(live, baseline)
        self.assertGreater(mapped, 0)
        self.assertEqual(cache.stats()['live_mappings'], 1)
        self.assertGreaterEqual(live - baseline, mapped)
        self.assertLessEqual(live, RETAINED_BYTES)
        borrowed.close()
        cache.close()
        self.assertEqual(memory.tobytes(), self.arrays['ints'].reshape(-1)[16382:16388].tobytes())
        del borrowed, raw, asarray, sliced
        gc.collect()
        pinned = self.scope.stats().retained_bytes
        self.assertEqual(cache.stats()['live_mapped_bytes'], mapped)
        self.assertGreater(pinned, 0)
        self.assertLessEqual(pinned, live)
        memory.release()
        del memory
        gc.collect()
        self.assertLess(self.scope.stats().retained_bytes, pinned)
        self.assertEqual(cache.stats()['live_mapped_bytes'], 0)
        self.assertEqual(cache.stats()['live_mappings'], 0)

    @unittest.skipUnless(os.name == 'nt', 'Windows mapping/locking contract')
    def test_direct_exported_mapping_close_refuses_until_numpy_alias_is_released(self):
        cache = self.built(names=('ints',))
        borrowed = cache.read('ints', 10, 18, max_owned_bytes=32)
        alias = np.asarray(borrowed.value)
        mapping = alias.base.obj
        self.assertIsInstance(mapping, RS._PaidMapping)
        borrowed.close()
        cache.close()
        before = self.scope.stats().retained_bytes
        mapped = cache.stats()['live_mapped_bytes']
        self.assertGreater(mapped, 0)
        with self.assertRaises(BufferError):
            mapping.close()
        self.assertEqual(self.scope.stats().retained_bytes, before)
        self.assertEqual(cache.stats()['live_mapped_bytes'], mapped)
        self.assertEqual(alias.tobytes(), self.arrays['ints'].reshape(-1)[10:18].tobytes())
        del alias
        gc.collect()
        mapping.close()
        self.assertEqual(cache.stats()['live_mapped_bytes'], 0)
        self.assertLess(self.scope.stats().retained_bytes, before)

    def test_fallback_numpy_memoryview_and_base_reexports_keep_byte_owner_alive(self):
        cache = self.cache(names=('ints',))
        before = self.scope.stats().purpose_bytes.get('retained:segment-read', 0)
        borrowed = cache.read('ints', 10, 18, max_owned_bytes=32)
        array = np.asarray(borrowed.value)
        exporter = array.base
        reexport = (np.frombuffer(exporter, dtype=array.dtype)
                    if isinstance(exporter, memoryview) else np.asarray(exporter))
        sliced = reexport[2:6]
        memory = memoryview(sliced)
        ordinary_export = np.frombuffer(array, dtype=array.dtype)
        funded = self.scope.stats().purpose_bytes.get('retained:segment-read', 0)
        self.assertGreater(funded, before)
        borrowed.close()
        cache.close()
        del borrowed, array, exporter, reexport, sliced, ordinary_export
        gc.collect()
        self.assertEqual(memory.tobytes(), self.arrays['ints'].reshape(-1)[12:16].tobytes())
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:segment-read', 0), funded)
        memory.release()
        del memory
        gc.collect()
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:segment-read', 0), before)

    @unittest.skipUnless(os.name == 'nt', 'Windows mapping/locking contract')
    def test_windows_borrow_locks_write_delete_and_replacement_until_last_alias_dies(self):
        cache = self.built(names=('ints',))
        path = cache.sidecar_path('ints')
        borrowed = cache.read('ints', 10, 16, max_owned_bytes=24)
        alias = np.asarray(borrowed.value)[1:]
        expected = alias.tobytes()
        borrowed.close()
        cache.close()
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        replacement = self.root / 'replacement.bin'
        replacement.write_bytes(b'x' * self.arrays['ints'].nbytes)
        with self.assertRaises(OSError):
            with path.open('r+b'):
                pass
        with self.assertRaises(OSError):
            path.unlink()
        with self.assertRaises(OSError):
            os.replace(replacement, path)
        self.assertEqual(alias.tobytes(), expected)
        del alias, borrowed
        gc.collect()
        os.replace(replacement, path)
        self.assertEqual(path.read_bytes(), b'x' * self.arrays['ints'].nbytes)

    @unittest.skipUnless(os.name == 'nt', 'Windows mapping/locking contract')
    def test_optional_mapping_admission_decline_falls_back_with_no_map_charge_leak(self):
        cache = self.built(names=('ints',))
        reserve = self.scope.reserve
        declined = []
        def admission(spec, *, required=True, cancel=None):
            if not required:
                declined.append(spec)
                return None
            return reserve(spec, required=required, cancel=cancel)
        with patch.object(self.scope, 'reserve', side_effect=admission), \
             patch.object(self.view, 'read', wraps=self.view.read) as ordinary:
            with cache.read('ints', 8, 12, max_owned_bytes=16) as borrowed:
                self.assert_exact(borrowed, 'ints', 8, 12)
            self.assertEqual(ordinary.call_count, 1)
        self.assertTrue(declined, 'mapping must request optional shared-scope admission')
        self.assertEqual(self.scope.stats().pending_bytes, 0)
        self.assertLessEqual(self.scope.stats().retained_bytes, RETAINED_BYTES)

    @unittest.skipUnless(os.name == 'nt', 'Windows mapping/locking contract')
    def test_bounded_windows_are_charged_before_mapping_and_released_without_page_cache(self):
        cache = self.built(names=('ints',))
        original = RS._PaidMapping
        admissions = []
        def observed(*args, **kwargs):
            admissions.append(self.scope.stats().pending_bytes)
            self.assertGreater(admissions[-1], 0, 'mapping started before shared-scope admission')
            return original(*args, **kwargs)
        with patch.object(RS, '_PaidMapping', side_effect=observed):
            first = cache.read('ints', 100, 102, max_owned_bytes=8)
            second = cache.read('ints', 400, 402, max_owned_bytes=8)
        self.assertEqual(len(admissions), 2)
        self.assertEqual(cache.stats()['live_mappings'], 2)
        self.assertLess(cache.stats()['live_mapped_bytes'], self.arrays['ints'].nbytes)
        first.close()
        gc.collect()
        self.assertEqual(cache.stats()['live_mappings'], 1)
        second.close()
        gc.collect()
        self.assertEqual(cache.stats()['live_mappings'], 0)
        self.assertEqual(cache.stats()['live_mapped_bytes'], 0)

    def test_changed_source_store_is_checked_before_serving_a_sidecar(self):
        cache = self.built(names=('ints',))
        changed = Path(str(self.root / self.stores.head.filename) + '-wal')
        changed.write_bytes(b'changed-source-fixture')
        try:
            with self.assertRaises(ContractError), \
                 patch.object(self.view, 'read', side_effect=AssertionError('freshness became a miss')):
                cache.read('ints', 0, 2, max_owned_bytes=8)
        finally:
            changed.unlink()

    def test_cancellation_refuses_build_and_mapped_read_without_pending_charges(self):
        event = threading.Event()
        self.view.cancel = event
        cache = self.cache(names=('ints',))
        event.set()
        with self.assertRaises((CancelledError, InterruptedError)):
            cache.build()
        event.clear()
        cache.build()
        event.set()
        with self.assertRaises((CancelledError, InterruptedError)):
            cache.read('ints', 0, 2, max_owned_bytes=8)
        event.clear()
        self.assertEqual(self.scope.stats().pending_bytes, 0)

    def test_invalid_bounds_allowances_and_unknown_name_refuse_before_mapping(self):
        cache = self.built(names=('ints',))
        cases = [(-1, 1, 8), (True, 1, 4), (0, False, 4), (4, 3, 4),
                 (0, 18001, 72004), (0, 2, 7), (0, 1, True), (0.0, 1, 4)]
        for start, stop, allowance in cases:
            with self.subTest(start=start, stop=stop, allowance=allowance):
                with self.assertRaises(ContractError):
                    cache.read('ints', start, stop, max_owned_bytes=allowance)
        with self.assertRaises((KeyError, ContractError)):
            cache.read('absent', 0, 1, max_owned_bytes=4)
        self.assertEqual(self.scope.stats().pending_bytes, 0)

    def test_tampered_sidecar_refuses_instead_of_falling_back_or_rebuilding(self):
        cache = self.built(names=('ints',))
        path = cache.sidecar_path('ints')
        cache.close()
        damaged = bytearray(path.read_bytes())
        damaged[65537] ^= 0x80
        self.change_bytes(path, damaged)
        with patch.object(self.view, 'read', side_effect=AssertionError('tampering became a miss')):
            with self.assertRaises(ContractError):
                self.cache(names=('ints',))
        self.assertEqual(path.read_bytes(), damaged)

    def test_truncated_sidecar_refuses(self):
        cache = self.built(names=('ints',))
        path = cache.sidecar_path('ints')
        cache.close()
        self.change_bytes(path, path.read_bytes()[:-1])
        with self.assertRaises(ContractError):
            self.cache(names=('ints',))

    def test_same_length_wrong_array_at_bound_filename_refuses(self):
        cache = self.built(names=('ints', 'little'))
        target, other = cache.sidecar_path('ints'), cache.sidecar_path('little')
        self.assertNotEqual(target.name, other.name)
        cache.close()
        self.change_bytes(target, other.read_bytes())
        with self.assertRaises(ContractError):
            self.cache(names=('ints',))

    def test_hardlinked_sidecar_refuses_when_host_allows_fixture(self):
        cache = self.built(names=('ints',))
        target = cache.sidecar_path('ints')
        cache.close()
        try:
            os.link(target, self.root / 'linked-payload.bin')
        except OSError as exc:
            self.skipTest('host refused hardlink fixture: ' + str(exc))
        with self.assertRaises(ContractError):
            self.cache(names=('ints',))

    def test_reparse_sidecar_refuses_when_host_allows_fixture(self):
        cache = self.built(names=('ints',))
        target = cache.sidecar_path('ints')
        cache.close()
        moved = self.root / 'outside-payload.bin'
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
        target.rename(moved)
        try:
            target.symlink_to(moved)
        except OSError as exc:
            moved.rename(target)
            self.skipTest('host refused symlink fixture: ' + str(exc))
        with self.assertRaises(ContractError):
            self.cache(names=('ints',))

    def test_closed_cache_refuses_new_reads(self):
        cache = self.built(names=('ints',))
        cache.close()
        cache.close()
        with self.assertRaises((ContractError, RuntimeError)):
            cache.read('ints', 0, 1, max_owned_bytes=4)

    def test_adoption_evidence_must_bind_selected_input_and_candidate_source(self):
        cache = self.cache(names=('ints',))
        evidence = adoption_fixture(
            input_binding_sha256=cache.input_binding_sha256,
            candidate_source_sha256=sha256(Path(RS.__file__).read_bytes()).hexdigest())
        cache.close()
        for changed in ('input_binding_sha256', 'candidate_source_sha256', 'array_names'):
            altered = dict(evidence)
            altered[changed] = ['little'] if changed == 'array_names' else 'd' * 64
            with self.subTest(binding=changed), self.assertRaises(ContractError):
                RawSidecarStore(self.view, self.cache_dir, array_names=('ints',),
                                enabled=True, adoption_evidence=altered)
        self.assertFalse(self.cache_dir.exists())


def adoption_fixture(**overrides):
    """Fabricated validation-only evidence; never activates an actual consumer."""
    value = dict(schema='atlas.raw-sidecar-adoption.v1', source_kind='real',
                 report_sha256='1' * 64, input_binding_sha256='2' * 64,
                 candidate_source_sha256='3' * 64, matched_configuration=True,
                 includes_creation_and_verification=True, exact_identity=True,
                 array_names=['ints'], baseline_run_seconds=100,
                 candidate_run_seconds=95, baseline_hot_read_seconds=10,
                 candidate_hot_read_seconds=5)
    value.update(overrides)
    return value


class RawSidecarAdoptionTests(unittest.TestCase):
    def test_absent_and_synthetic_evidence_are_incomplete_and_never_enable(self):
        for evidence in (None, {}, adoption_fixture(source_kind='synthetic')):
            with self.subTest(evidence=evidence):
                result = assess_adoption(evidence)
                self.assertEqual(result['status'], 'INCOMPLETE')
                self.assertFalse(result['enabled'])
                self.assertFalse(result['policy_written'])

    def test_exact_five_percent_boundary_requires_both_hot_and_net_run_saving(self):
        result = assess_adoption(adoption_fixture())
        self.assertEqual(result['status'], 'READY_FOR_OWNER_REVIEW')
        self.assertFalse(result['enabled'])
        self.assertFalse(result['policy_written'])
        for changes in ({'candidate_run_seconds': 95.000000001},
                        {'candidate_hot_read_seconds': 5.000000001},
                        {'baseline_hot_read_seconds': 4, 'candidate_hot_read_seconds': 0},
                        {'candidate_run_seconds': 99, 'candidate_hot_read_seconds': 0}):
            with self.subTest(changes=changes):
                result = assess_adoption(adoption_fixture(**changes))
                self.assertEqual(result['status'], 'TESTED_DISABLED')
                self.assertTrue(result['failed_gates'])
                self.assertFalse(result['enabled'])

    def test_missing_creation_verification_configuration_or_identity_is_incomplete(self):
        for flag in ('includes_creation_and_verification', 'matched_configuration', 'exact_identity'):
            for bad in (False, None, 1):
                with self.subTest(flag=flag, bad=bad):
                    result = assess_adoption(adoption_fixture(**{flag: bad}))
                    self.assertEqual(result['status'], 'INCOMPLETE')

    def test_malformed_timing_and_impossible_hot_subset_cannot_pass(self):
        for bad in (True, float('nan'), float('inf'), -1, '95'):
            with self.subTest(bad=bad):
                self.assertEqual(assess_adoption(adoption_fixture(
                    candidate_run_seconds=bad))['status'], 'INCOMPLETE')
        for changes in ({'baseline_run_seconds': 0}, {'array_names': ['ints', 'ints']},
                        {'array_names': []}, {'report_sha256': 'not-a-digest'}):
            with self.subTest(changes=changes):
                self.assertEqual(assess_adoption(adoption_fixture(**changes))['status'], 'INCOMPLETE')
        self.assertEqual(assess_adoption(adoption_fixture(
            baseline_hot_read_seconds=101))['status'], 'TESTED_DISABLED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
