"""Synthetic retained-lifetime/accounting tests; no runtime or database advance."""
import gc
import hashlib
import threading
import unittest
import weakref

from atlas_tectonics.integration_parallel_owner import RevocableOwner
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from compact_contracts import ContractError, RETAINED_BYTES
from content_cache import (CARRIER_BYTES, ChargeSpec, ContentCache, OwnedStream, OWNER_BYTES,
                           VerifiedCacheKey, create_retained_scope, page_key,
                           get_content_cache, support_key, verified_hash_key, view_seal_key)


def owner(scope, value=b'value', *, capacity=None, purpose='test'):
    if capacity is None:
        capacity = len(value) if isinstance(value, (bytes, bytearray)) else 128
    with scope.reserve(ChargeSpec(purpose, capacity)) as reservation:
        return reservation.commit(value)


def key(scope, value=b'value', category='pages'):
    return VerifiedCacheKey(category, scope.process_epoch, hashlib.sha256(value).digest())


def verify(binding, value):
    return hashlib.sha256(value).digest() == binding.authenticated_key_bytes


class ScopeFixture:
    def make_scope(self, maximum=RETAINED_BYTES * 2, epoch='test-process'):
        run = WorkBudget(maximum)
        scope = create_retained_scope(run, process_epoch=epoch)
        self.addCleanup(gc.collect)
        return run, scope


class OwnershipTests(ScopeFixture, unittest.TestCase):
    def test_single_exact_child_no_scope_or_revoker_replacement(self):
        run, scope = self.make_scope()
        self.assertIs(create_retained_scope(run, process_epoch='test-process'), scope)
        self.assertEqual(scope.retained_budget.max_bytes, RETAINED_BYTES)
        self.assertIs(scope.retained_budget._parent, run)
        self.assertIs(scope.run_budget, run)
        self.assertIsNone(run._scope)
        self.assertIsNone(scope.retained_budget._scope)
        self.assertIsNone(scope.retained_budget._revoker)
        with self.assertRaises(ValueError):
            create_retained_scope(run, process_epoch='foreign-process')
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_charge_spec_capacity_and_pending_transfer(self):
        run, scope = self.make_scope()
        before = scope.stats().retained_bytes
        spec = ChargeSpec('capacity', 200, owner_bytes=8192, index_bytes=500)
        reservation = scope.reserve(spec)
        self.assertEqual(scope.stats().pending_bytes, 8892)
        value = reservation.commit(bytearray(100))
        self.assertEqual(scope.stats().pending_bytes, 0)
        self.assertEqual(run.reserved_bytes, before + 8892)
        reservation.close()
        self.assertEqual(run.reserved_bytes, before + 8892)
        value.close()
        self.assertEqual(run.reserved_bytes, before)
        scope.close()
        with self.assertRaises(ValueError):
            ChargeSpec('too-small-owner', 1, owner_bytes=0)

    def test_aggregate_refusal_precedes_allocation(self):
        run, scope = self.make_scope()
        first = scope.reserve(ChargeSpec('one', 150 * 1024 * 1024))
        allocated = []
        with self.assertRaises(MemoryLimitError):
            with scope.reserve(ChargeSpec('two', 120 * 1024 * 1024)):
                allocated.append(bytearray(1))
        self.assertEqual(allocated, [])
        self.assertEqual(scope.stats().required_refusals, 1)
        self.assertEqual(scope.stats().pending_bytes, 150 * 1024 * 1024 + OWNER_BYTES)
        first.close()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_paid_child_shares_backing_parent_close_refuses(self):
        run, scope = self.make_scope()
        value = owner(scope, b'abc')
        before = run.reserved_bytes
        child = value.retain()
        self.assertIs(value.allocation_id, child.allocation_id)
        self.assertIs(value.value, child.value)
        # A retained child share books its ownership carrier at CARRIER_BYTES (Plan 18 carrier booking).
        self.assertEqual(run.reserved_bytes, before + CARRIER_BYTES)
        self.assertEqual(value.borrow_count, 1)
        with self.assertRaises(RuntimeError):
            value.assert_unborrowed()
        with self.assertRaises(RuntimeError):
            value.close()
        self.assertEqual(child.value, b'abc')
        child.close()
        child.close()
        value.close()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_dependency_pin_lasts_through_shared_carriers(self):
        run, scope = self.make_scope()
        handle = owner(scope, b'handle')
        with scope.reserve(ChargeSpec('read', 3)) as reservation:
            read = reservation.commit(b'abc', dependencies=(handle,))
        child = read.retain()
        with self.assertRaises(RuntimeError):
            handle.close()
        child.close()
        read.close()
        handle.assert_unborrowed()
        handle.close()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_foreign_dependency_refused_without_adoption(self):
        run, scope = self.make_scope()
        other_run, other = self.make_scope(epoch='foreign')
        foreign = owner(other)
        reservation = scope.reserve(ChargeSpec('target', 5))
        with self.assertRaises(ValueError):
            reservation.commit(b'value', dependencies=(foreign,))
        reservation.close()
        self.assertEqual(foreign.value, b'value')
        foreign.close()
        other.close()
        scope.close()
        self.assertEqual((run.reserved_bytes, other_run.reserved_bytes), (0, 0))

    def test_owned_exception_and_independent_traceback_keep_charge(self):
        run, scope = self.make_scope()
        before = run.reserved_bytes

        def fail():
            with owner(scope, bytearray(8192)) as retained:
                raw = retained.value
                self.assertEqual(len(raw), 8192)
                raise ValueError('held producer failure')

        try:
            fail()
        except ValueError as error:
            traceback = error.__traceback__
        gc.collect()
        self.assertGreaterEqual(run.reserved_bytes, before + 8192 + OWNER_BYTES)
        with self.assertRaises(RuntimeError):
            scope.close()
        del traceback
        gc.collect()
        self.assertEqual(run.reserved_bytes, before)
        scope.close()

    def test_pending_exception_frame_keeps_precommit_allocation_paid(self):
        run, scope = self.make_scope()
        before = run.reserved_bytes

        def fail():
            with scope.reserve(ChargeSpec('uncommitted', 4096)) as reservation:
                allocated = bytearray(4096)
                self.assertIsNotNone(reservation)
                self.assertEqual(len(allocated), 4096)
                raise ValueError('allocation failed before commit')

        try:
            fail()
        except ValueError as error:
            traceback = error.__traceback__
        gc.collect()
        self.assertEqual(scope.stats().pending_bytes, 4096 + OWNER_BYTES)
        del traceback
        gc.collect()
        self.assertEqual(run.reserved_bytes, before)
        scope.close()

    def test_yielded_blocks_survive_advance_and_stream_close(self):
        run, scope = self.make_scope()

        def produce():
            yield owner(scope, b'one')
            yield owner(scope, b'two')

        stream = OwnedStream(produce(), scope=scope)
        first = next(stream)
        second = next(stream)
        stream.close()
        self.assertEqual(first.value, b'one')
        self.assertEqual(second.value, b'two')
        self.assertGreaterEqual(run.reserved_bytes, 2 * (OWNER_BYTES + 3))
        first.close()
        second.close()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_failed_generator_traceback_remains_funded(self):
        run, scope = self.make_scope()
        before = run.reserved_bytes

        def produce():
            retained = owner(scope, bytearray(6000))
            raw = retained.value
            yield owner(scope, b'yield')
            self.assertEqual(len(raw), 6000)
            raise ValueError('generator failure')

        stream = OwnedStream(produce(), scope=scope)
        first = next(stream)
        try:
            next(stream)
        except ValueError as error:
            traceback = error.__traceback__
        stream.close()
        first.close()
        del stream
        gc.collect()
        self.assertGreaterEqual(run.reserved_bytes, before + 6000 + OWNER_BYTES)
        del traceback
        gc.collect()
        self.assertEqual(run.reserved_bytes, before)
        scope.close()

    def test_optional_declines_do_not_revoke_or_count_required_refusal(self):
        run, scope = self.make_scope(32_000)
        worker = run.reserve(20_000, category='optional-worker')
        worker.__enter__()
        stopped = []

        def stop():
            stopped.append(True)
            worker.__exit__(None, None, None)

        with RevocableOwner((run,), stop) as revoker:
            self.assertIsNone(scope.reserve(ChargeSpec('optional', 15_000), required=False))
            self.assertEqual(stopped, [])
            self.assertIs(run._revoker, revoker)
            self.assertIsNone(scope.retained_budget._revoker)
            self.assertEqual(scope.stats().required_refusals, 0)
            self.assertEqual(scope.stats().optional_declines, 1)
            required = scope.reserve(ChargeSpec('required', 15_000))
            self.assertEqual(stopped, [True])
            self.assertIs(run._revoker, revoker)
            required.close()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_cancellation_after_admission_releases_only_unused_reservation(self):
        from concurrent.futures import CancelledError
        run, scope = self.make_scope()
        before = run.reserved_bytes

        class CancelAfterAdmission:
            calls = 0

            def is_set(self):
                self.calls += 1
                return self.calls == 2

        with self.assertRaises(CancelledError):
            scope.reserve(ChargeSpec('cancelled-reservation', 100), cancel=CancelAfterAdmission())
        self.assertEqual(run.reserved_bytes, before)
        self.assertEqual(scope.stats().pending_bytes, 0)
        scope.close()

    def test_pending_admission_refuses_scope_close_in_callback(self):
        run, scope = self.make_scope()
        attempts = []

        class Check:
            def is_set(self):
                try:
                    scope.close()
                except RuntimeError:
                    attempts.append('refused')
                return False

        reservation = scope.reserve(ChargeSpec('in-flight', 100), cancel=Check())
        self.assertEqual(attempts, ['refused', 'refused'])
        reservation.close()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_factory_never_holds_registry_lock_during_existing_revoker(self):
        run = WorkBudget(10_000)
        worker = run.reserve(8000, category='worker')
        worker.__enter__()
        callbacks = []

        def stop():
            with self.assertRaises(RuntimeError):
                create_retained_scope(run, process_epoch='process')
            callbacks.append('outside-lock')
            worker.__exit__(None, None, None)

        with RevocableOwner((run,), stop):
            scope = create_retained_scope(run, process_epoch='process')
            self.assertEqual(callbacks, ['outside-lock'])
            scope.close()
        self.assertEqual(run.reserved_bytes, 0)


class CacheTests(ScopeFixture, unittest.TestCase):
    def test_shared_accessor_same_budget_configuration_and_scope_lifetime(self):
        run, scope = self.make_scope()
        cache = get_content_cache(scope, 'pages', enabled=True, verifier=verify)
        value = owner(scope, b'cached')
        binding = key(scope, b'cached')
        cache.offer_verified(binding, value)
        value.close()
        reference = weakref.ref(cache)
        before = run.reserved_bytes
        del cache
        gc.collect()
        self.assertIsNotNone(reference())
        shared = get_content_cache(scope, 'pages', enabled=True, verifier=verify)
        self.assertIs(shared, reference())
        self.assertEqual(run.reserved_bytes, before)
        self.assertEqual(shared.max_bytes, 64 * 1024 * 1024)
        got = shared.get(binding)
        self.assertEqual(got.value, b'cached')
        got.close()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_shared_accessor_adopts_compatible_cache_and_refuses_config_change(self):
        _, scope = self.make_scope()
        direct = ContentCache(scope, 'pages', verifier=verify)
        self.assertIs(get_content_cache(scope, 'pages', enabled=True, verifier=verify), direct)
        for settings in (dict(enabled=False, verifier=verify),
                         dict(enabled=True, verifier=lambda binding, raw: verify(binding, raw)),
                         dict(enabled=True, verifier=verify, max_entries=1),
                         dict(enabled=True, verifier=verify, max_bytes=63 * 1024 * 1024)):
            with self.assertRaises(ValueError):
                get_content_cache(scope, 'pages', **settings)
        scope.close()

    def test_shared_cache_disabled_parity_and_scope_close_with_held_borrow(self):
        outputs = []
        for enabled in (False, True):
            run, scope = self.make_scope()
            cache = get_content_cache(scope, 'pages', enabled=enabled, verifier=verify)
            value = owner(scope, b'exact-page')
            binding = key(scope, value.value)
            inserted = cache.offer_verified(binding, value)
            got = cache.get(binding)
            outputs.append(value.value if got is None else got.value)
            self.assertEqual(inserted, enabled)
            value.close()
            if got is not None:
                with self.assertRaises(RuntimeError):
                    scope.close()
                self.assertEqual(got.value, b'exact-page')
                got.close()
            scope.close()
            self.assertEqual(run.reserved_bytes, 0)
        self.assertEqual(outputs[0], outputs[1])

    def test_failed_shared_creation_releases_slot_for_valid_retry(self):
        run, scope = self.make_scope(20_000)
        blocker = scope.reserve(ChargeSpec('hold', 7000))
        with self.assertRaises(MemoryLimitError):
            get_content_cache(scope, 'pages', enabled=True, verifier=verify)
        blocker.close()
        cache = get_content_cache(scope, 'pages', enabled=True, verifier=verify)
        self.assertIs(cache.scope, scope)
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_cache_quota_is_not_mandatory_read_limit(self):
        run, scope = self.make_scope()
        cache = ContentCache(scope, 'pages', verifier=verify)
        value = owner(scope, b'large-range', capacity=128 * 1024 * 1024)
        self.assertFalse(cache.offer_verified(key(scope, b'large-range'), value))
        self.assertEqual(value.value, b'large-range')
        self.assertGreater(run.reserved_bytes, 128 * 1024 * 1024)
        value.close()
        cache.close()
        scope.close()

    def test_cache_does_not_double_charge_shared_backing_and_counters_exact(self):
        run, scope = self.make_scope()
        cache = ContentCache(scope, 'pages', verifier=verify)
        value = owner(scope, b'abc', capacity=100_000)
        before = run.reserved_bytes
        self.assertTrue(cache.offer_verified(key(scope, b'abc'), value))
        self.assertLess(run.reserved_bytes - before, OWNER_BYTES + 1024)
        self.assertGreater(scope.stats().pinned_bytes, 100_000)
        self.assertEqual(scope.evict_unpinned(requested_bytes=100_000), 0)
        value.close()
        self.assertGreater(scope.stats().evictable_bytes, 100_000)
        got = cache.get(key(scope, b'abc'))
        self.assertEqual(got.value, b'abc')
        self.assertEqual(scope.evict_unpinned(requested_bytes=100_000), 0)
        self.assertIsNone(cache.get(key(scope, b'different')))
        got.close()
        reclaimed = scope.evict_unpinned(requested_bytes=1)
        self.assertGreater(reclaimed, 100_000)
        stats = scope.stats()
        self.assertEqual((stats.hits['pages'], stats.misses['pages'], stats.insertions['pages'],
                          stats.evictions['pages'], stats.entries['pages']), (1, 1, 1, 1, 0))
        self.assertEqual(stats.reclaimed_bytes['pages'], reclaimed)
        self.assertEqual(stats.retained_bytes, stats.pending_bytes + stats.pinned_bytes +
                         stats.evictable_bytes + stats.non_cache_owned_bytes)
        cache.close()
        scope.close()

    def test_pressure_evicts_then_mandatory_admission_succeeds(self):
        run, scope = self.make_scope(45_000)
        cache = ContentCache(scope, 'pages', verifier=verify)
        value = owner(scope, b'abc', capacity=15_000)
        cache.offer_verified(key(scope, b'abc'), value)
        value.close()
        before = scope.stats().evictions['pages']
        reservation = scope.reserve(ChargeSpec('read', 28_000))
        self.assertEqual(scope.stats().evictions['pages'], before + 1)
        self.assertEqual(scope.stats().required_refusals, 0)
        reservation.close()
        cache.close()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_lru_eviction_and_pin_lifetime_after_cache_close(self):
        run, scope = self.make_scope()
        cache = ContentCache(scope, 'pages', verifier=verify, max_entries=2)
        for payload in (b'a', b'b'):
            value = owner(scope, payload)
            cache.offer_verified(key(scope, payload), value)
            value.close()
        borrowed = cache.get(key(scope, b'a'))
        value = owner(scope, b'c')
        cache.offer_verified(key(scope, b'c'), value)
        value.close()
        self.assertIsNone(cache.get(key(scope, b'b')))
        cache.close()
        self.assertEqual(borrowed.value, b'a')
        with self.assertRaises(RuntimeError):
            scope.close()
        borrowed.close()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_foreign_owner_epoch_and_category_refuse(self):
        _, scope = self.make_scope()
        _, other = self.make_scope(epoch='other')
        cache = ContentCache(scope, 'pages', verifier=verify)
        foreign = owner(other)
        with self.assertRaises(ValueError):
            cache.offer_verified(key(scope), foreign)
        with self.assertRaises(ValueError):
            cache.get(key(other))
        with self.assertRaises(ValueError):
            cache.get(key(scope, category='facts'))
        with self.assertRaises(ValueError):
            ContentCache(scope, 'pages', verifier=verify)
        foreign.close()
        cache.close()
        other.close()
        scope.close()

    def test_verification_before_insert_and_after_mutation(self):
        _, scope = self.make_scope()
        cache = ContentCache(scope, 'pages', verifier=verify)
        value = owner(scope, bytearray(b'abc'))
        with self.assertRaises(ContractError):
            cache.offer_verified(key(scope, b'bad'), value)
        self.assertEqual(scope.stats().insertions['pages'], 0)
        cache.offer_verified(key(scope, b'abc'), value)
        value.value[0] = 0
        with self.assertRaises(ContractError):
            cache.get(key(scope, b'abc'))
        value.close()
        cache.close()
        scope.close()

    def test_cancellation_checked_before_hit_and_callbacks_outside_lock(self):
        _, scope = self.make_scope()
        cancel = threading.Event()
        cache = ContentCache(scope, 'pages', verifier=verify)
        value = owner(scope)
        cache.offer_verified(key(scope), value)
        value.close()
        cancel.set()
        from concurrent.futures import CancelledError
        with self.assertRaises(CancelledError):
            cache.get(key(scope), cancel=cancel)
        self.assertEqual(scope.stats().hits['pages'], 0)
        checks = []

        class Check:
            def is_set(self):
                checks.append(not cache._lock._is_owned())
                return False

        got = cache.get(key(scope), cancel=Check())
        got.close()
        self.assertTrue(all(checks))
        cache.close()
        scope.close()

    def test_held_hit_verifier_traceback_keeps_cached_backing_paid(self):
        run, scope = self.make_scope()
        fail = [False]

        def verifier(binding, raw):
            if fail[0]:
                raise ValueError('verification retained raw bytes')
            return verify(binding, raw)

        cache = ContentCache(scope, 'pages', verifier=verifier)
        value = owner(scope, b'x' * 5000)
        binding = key(scope, value.value)
        cache.offer_verified(binding, value)
        value.close()
        fail[0] = True
        try:
            cache.get(binding)
        except ValueError as error:
            traceback = error.__traceback__
        cache.close()
        self.assertGreaterEqual(scope.stats().pinned_bytes, 5000 + OWNER_BYTES)
        with self.assertRaises(RuntimeError):
            scope.close()
        del traceback
        gc.collect()
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_optional_pressure_retries_and_quota_category_stats_are_real(self):
        run, scope = self.make_scope(50_000)
        cache = ContentCache(scope, 'pages', verifier=verify)
        value = owner(scope, b'abc', capacity=15_000)
        cache.offer_verified(key(scope, b'abc'), value)
        value.close()
        before = scope.stats()
        self.assertGreater(before.category_bytes['pages'], 15_000 + OWNER_BYTES)
        self.assertEqual(before.category_bytes['facts'], 0)
        reservation = scope.reserve(ChargeSpec('optional-read', 30_000), required=False)
        self.assertIsNotNone(reservation)
        after = scope.stats()
        self.assertEqual(after.evictions['pages'], 1)
        self.assertEqual(after.required_refusals, 0)
        self.assertEqual(after.category_bytes['pages'], cache._control.charged_bytes)
        self.assertEqual(after.category_peak_bytes['pages'], before.category_bytes['pages'])
        self.assertIn('retained:optional-read', after.purpose_bytes)
        self.assertEqual(after.live_bytes + after.pending_bytes, after.retained_bytes)
        reservation.close()
        cache.close()
        self.assertEqual(scope.stats().category_bytes['pages'], 0)
        scope.close()
        self.assertEqual(run.reserved_bytes, 0)

    def test_cache_on_off_exact_parity(self):
        results = []
        for enabled in (False, True):
            _, scope = self.make_scope()
            cache = ContentCache(scope, 'pages', enabled=enabled, verifier=verify)
            values = []
            for payload in (b'a\x00', b'b\xff', b'a\x00'):
                got = cache.get(key(scope, payload))
                if got is None:
                    got = owner(scope, payload)
                    cache.offer_verified(key(scope, payload), got)
                values.append(got.value)
                got.close()
            results.append(values)
            cache.close()
            scope.close()
        self.assertEqual(results[0], results[1])

    def test_key_domain_and_every_page_trust_field(self):
        fields = dict(process_epoch='epoch', file_identity=b'file',
                      chunk_id=b'chunk', descriptor_digest=b'descriptor')
        base = page_key(**fields)
        for field in fields:
            changed = dict(fields)
            changed[field] += 'x' if field == 'process_epoch' else b'x'
            self.assertNotEqual(base, page_key(**changed))
        self.assertNotEqual(base, verified_hash_key(**fields))
        self.assertNotEqual(support_key(process_epoch='e', support_identity=b'a', decoder_schema=b'b'),
                            support_key(process_epoch='e', support_identity=b'a', decoder_schema=b'c'))
        common = dict(process_epoch='e', logical_schema=b'schema',
                      canonical_profile=b'profile', logical_identity=b'id')
        self.assertNotEqual(view_seal_key(ordered_bindings=(b'a', b'b'), **common),
                            view_seal_key(ordered_bindings=(b'b', b'a'), **common))


if __name__ == '__main__':
    unittest.main()
