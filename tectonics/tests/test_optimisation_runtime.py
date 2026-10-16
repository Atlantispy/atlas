"""Bounded integrity checks for release policy, immutable verification and retained-store accounting.

Private test-only state selects release behaviour; production has no environment switch.
All files, package layouts and databases written here are disposable fixtures.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics import ThermalParameters, TectonicsError, reuse, thermal
from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits


def key(label):
    return hashlib.sha256(label.encode()).hexdigest()


def state(mode=None):
    return types.SimpleNamespace(mode=mode, captures={}, lock=threading.RLock())


LIMITS = StoreLimits(1024, 1 << 20, 4 << 20)
RAW = Compression('raw', palette=False)


class PackagedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = Path(self.tmp.name)/'bundle'
        self.tectonics = self.bundle/'resources'/'atlas'/'tectonics'
        self.source = self.tectonics/'src'/'atlas_tectonics'/'reuse.py'
        self.entry = self.tectonics/'tools'/'new_world.py'
        self.python = self.bundle/'resources'/'python'/'python.exe'
        self.marker = self.tectonics/'.desktop-runtime.json'
        for path in (self.source, self.entry, self.python, self.bundle/'Atlas.exe'):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(reuse, '__file__', str(self.source)))
        self.stack.enter_context(mock.patch.object(sys, 'executable', str(self.python)))
        self.stack.enter_context(mock.patch.object(sys, 'argv', [str(self.entry)]))
        self.stack.enter_context(mock.patch.object(reuse, '_release_state', state()))

    def mark(self, **extra):
        self.marker.write_text(json.dumps(dict(schema='atlas.desktop-runtime.v1', identity_mode='release', **extra)))

    def test_environment_cannot_enable_release_and_checkout_marker_refuses(self):
        with mock.patch.dict(os.environ, {'ATLAS_IDENTITY_MODE': 'release'}):
            self.assertEqual(reuse.execution_mode(), 'strict')
        self.mark()
        with mock.patch.object(reuse, '__file__', str(Path(self.tmp.name)/'checkout'/'src'/'atlas_tectonics'/'reuse.py')):
            checkout_marker = Path(self.tmp.name)/'checkout'/'.desktop-runtime.json'
            checkout_marker.parent.mkdir(parents=True)
            checkout_marker.write_bytes(self.marker.read_bytes())
            with self.assertRaisesRegex(TectonicsError, 'restricted'):
                reuse._packaged_mode()
        # The policy is fixed for the process; adding a marker later cannot switch an existing strict run.
        self.assertEqual(reuse.execution_mode(), 'strict')

    def test_only_a_complete_plain_packaged_command_layout_is_admitted(self):
        self.mark()
        self.assertEqual(reuse._packaged_mode(), 'release')
        self.assertEqual(reuse.execution_mode(), 'release')
        with self.assertRaisesRegex(TectonicsError, 'strict'):
            reuse.require_strict_execution()
        for entry in (self.tectonics/'verify.py', self.tectonics/'tools'/'check_evidence.py'):
            with self.subTest(entry=entry.name), mock.patch.object(sys, 'argv', [str(entry)]):
                with self.assertRaisesRegex(TectonicsError, 'restricted'):
                    reuse._packaged_mode()
        with mock.patch.object(sys, 'executable', str(self.bundle/'python.exe')):
            with self.assertRaisesRegex(TectonicsError, 'restricted'):
                reuse._packaged_mode()
        with mock.patch.object(Path, 'is_symlink', lambda path: path == self.marker):
            with self.assertRaisesRegex(TectonicsError, 'linked'):
                reuse._packaged_mode()
        self.mark(extra=True)
        with self.assertRaisesRegex(TectonicsError, 'invalid'):
            reuse._packaged_mode()
        self.mark()
        (self.bundle/'Atlas.exe').unlink()
        with self.assertRaisesRegex(TectonicsError, 'incomplete'):
            reuse._packaged_mode()


class ReleaseExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.policy = state('strict')
        self.stack.enter_context(mock.patch.object(reuse, '_release_state', self.policy))

    def test_identity_is_mode_independent_and_producer_policy_survives_reopen(self):
        strict = reuse.ExecutionContext()
        strict_id = strict.identity
        strict.close()
        self.policy.mode = 'release'
        release = reuse.ExecutionContext()
        self.assertEqual(release.identity, strict_id)
        self.assertEqual(release.provenance, {'execution_identity': strict_id, 'execution_mode': 'release'})
        array = np.arange(16, dtype=np.float64)
        with ArrayStore(self.root/'state.db', LIMITS, RAW) as store:
            store.put(key('release'), {'a': array}, {'identity': release.identity})
            self.assertEqual(store.execution_mode(key('release')), 'release')
        self.policy.mode = 'strict'
        with ArrayStore(self.root/'state.db', LIMITS, RAW) as store:
            self.assertEqual(store.execution_mode(key('release')), 'release')
            self.assertEqual(store.get(key('release'))['a'].tobytes(), array.tobytes())
            # Identical scientific invocation/data stay shareable; first producer's policy remains immutable.
            store.put(key('release'), {'a': array}, {'identity': strict_id})
            self.assertEqual(store.execution_mode(key('release')), 'release')
            store.put(key('strict'), {'a': array}, {'identity': strict_id})
            self.assertEqual(store.execution_mode(key('strict')), 'strict')

    def test_one_capture_per_backend_is_thread_safe_and_close_is_per_context(self):
        self.policy.mode = 'release'
        original = reuse.ExecutionContext._capture
        calls = []

        def counted(context, backend):
            calls.append(backend)
            return original(context, backend)

        with mock.patch.object(reuse.ExecutionContext, '_capture', counted):
            with ThreadPoolExecutor(8) as pool:
                contexts = list(pool.map(reuse.ExecutionContext, ['reference', 'scipy'] * 8))
            self.assertEqual(sorted(calls), ['reference', 'scipy'])
            first, other = contexts[0], contexts[2]
            first.close()
            with self.assertRaisesRegex(TectonicsError, 'closed'):
                first.verify()
            other.verify_boundary()
            later = reuse.ExecutionContext('reference')
            later.verify_boundary()
            self.assertFalse(later._closed)
            for context in contexts[1:]:
                context.close()
            later.close()

    def test_save_reopen_and_cache_boundaries_refuse_real_source_drift_and_loaded_code_changes(self):
        self.policy.mode = 'release'
        source = self.root/'fixture-source'/'reuse.py'
        source.parent.mkdir()
        source.write_bytes(b'fixture = 1\n')
        with mock.patch.object(reuse, '__file__', str(source)):
            context = reuse.ExecutionContext('reference')
            with ArrayStore(self.root/'boundary.db', LIMITS, RAW) as store:
                parameters = ThermalParameters('synthetic', 'release boundary', 300., 1300., 1.)
                kwargs = dict(store=store, context=context, backend='reference',
                              cache_policy=reuse.CachePolicy(mode='always'))
                reuse.cached_temperature(np.arange(16.), 1., parameters, **kwargs)
                actions = {
                    'save': lambda: store.put(key('new'), {'a': np.arange(16.)}),
                    'reopen': lambda: ArrayStore(store.path, LIMITS, RAW),
                    'read': lambda: store.get(key('new')),
                    'backup': lambda: store.backup_to(self.root/'refused-backup.db'),
                    'cache': lambda: reuse.cached_temperature(np.arange(16.), 1., parameters, **kwargs),
                }
                before = source.stat()
                source.write_bytes(b'fixture = 2\n')
                os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
                try:
                    context.verify()  # release's per-call check is deliberately cheap
                    for name, action in actions.items():
                        with self.subTest(change='source', boundary=name), self.assertRaisesRegex(TectonicsError, 'source changed'):
                            action()
                finally:
                    source.write_bytes(b'fixture = 1\n')
                with mock.patch.object(thermal, 'half_space_temperature', lambda *a, **kw: np.zeros(16)):
                    for name, action in actions.items():
                        with self.subTest(change='loaded code', boundary=name), self.assertRaisesRegex(TectonicsError, 'loaded implementation'):
                            action()
                context.verify_boundary()

    def test_a_change_at_the_publication_boundary_rolls_back_the_snapshot(self):
        self.policy.mode = 'release'
        with ArrayStore(self.root/'late.db', LIMITS, RAW) as store:
            original = thermal.half_space_temperature
            try:
                def change():
                    thermal.half_space_temperature = lambda *a, **kw: None
                with self.assertRaisesRegex(TectonicsError, 'loaded implementation'):
                    store.put(key('late'), {'a': np.arange(16.)}, publication_check=change)
            finally:
                thermal.half_space_temperature = original
            self.assertFalse(store.contains(key('late')))
            self.assertEqual(store._db.execute('SELECT count(*) FROM chunks').fetchone()[0], 0)


class ImmutableVerificationTests(unittest.TestCase):
    def setUp(self):
        self.module = types.ModuleType('atlas_tectonics._optimisation_fixture')
        exec('def f(value=[1], *, options={"x": 1}):\n    return value[0] + options["x"]\n', self.module.__dict__)
        self.module.IMMUTABLE = ('a', frozenset({1, 2}), (None, True, 0.5, b'bytes'))
        self.module.MUTABLE = [1]
        self.module.NESTED = ([1],)
        self.module.DTYPE = np.dtype('f8', metadata={'nested': [1]})
        self.patch = mock.patch.dict(sys.modules, {self.module.__name__: self.module})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.modules = ('_optimisation_fixture', 'reuse')
        _, tokens, self.constants = reuse._callable_inventory(modules=self.modules)
        self.expected = {token[0]: token for token in tokens}
        self.cache = {}
        self.verify(self.cache)

    def verify(self, cache):
        reuse._verify_callable_inventory('reference', self.expected, self.constants, self.modules, cache)

    def test_only_deeply_immutable_objects_are_cached(self):
        prefix = self.module.__name__ + '.'
        self.assertIs(self.cache[prefix+'IMMUTABLE'][0], self.module.IMMUTABLE)
        for name in ('MUTABLE', 'NESTED', 'DTYPE'):
            self.assertNotIn(prefix+name, self.cache)
        class TupleSubclass(tuple):
            pass
        for value in ([], {}, set(), ([],), TupleSubclass((1,)), np.int64(1), self.module.DTYPE):
            self.assertFalse(reuse._deeply_immutable(value))
        self.verify(self.cache)

    def test_cache_and_uncached_oracle_both_refuse_mutable_default_code_and_membership_changes(self):
        scenarios = {
            'mutable': lambda: self.module.MUTABLE.append(2),
            'nested': lambda: self.module.NESTED[0].append(2),
            'dtype metadata': lambda: self.module.DTYPE.metadata['nested'].append(2),
            'default': lambda: self.module.f.__defaults__[0].append(2),
            'kwdefault': lambda: self.module.f.__kwdefaults__['options'].update(x=2),
            'code': lambda: setattr(self.module.f, '__code__', (lambda value=[1], *, options={'x': 1}: 7).__code__),
            'rebind': lambda: setattr(self.module, 'IMMUTABLE', ('different',)),
            'added constant': lambda: setattr(self.module, 'NEW', 2),
            'deleted constant': lambda: delattr(self.module, 'IMMUTABLE'),
        }
        # Restore the fixture after each mutation; no mutation is left in a production module.
        for name, mutate in scenarios.items():
            with self.subTest(name=name):
                saved = self.module.__dict__.copy()
                code, defaults, kwdefaults = self.module.f.__code__, self.module.f.__defaults__, self.module.f.__kwdefaults__
                try:
                    mutate()
                    for cache in (None, self.cache):
                        with self.assertRaises(TectonicsError):
                            self.verify(cache)
                finally:
                    self.module.__dict__.clear()
                    self.module.__dict__.update(saved)
                    self.module.MUTABLE[:] = [1]
                    self.module.NESTED[0][:] = [1]
                    self.module.DTYPE.metadata['nested'][:] = [1]
                    defaults[0][:] = [1]
                    kwdefaults['options']['x'] = 1
                    self.module.f.__code__, self.module.f.__defaults__, self.module.f.__kwdefaults__ = code, defaults, kwdefaults
                self.verify(self.cache)

    def test_refused_poisoning_does_not_promote_fresh_cache_entries(self):
        before = dict(self.cache)
        normal = reuse._constant
        with mock.patch.object(reuse, '_deeply_immutable', lambda value: True), \
                mock.patch.object(reuse, '_constant', lambda value: normal(value)):
            with self.assertRaises(TectonicsError):
                self.verify(self.cache)
        self.assertEqual(self.cache, before)
        self.module.MUTABLE.append(2)
        with self.assertRaises(TectonicsError):
            self.verify(self.cache)


class RetainedAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(reuse, '_release_state', state('strict'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = Path(self.tmp.name)/'retained.db'
        self.store = ArrayStore(self.path, LIMITS, RAW)
        self.addCleanup(self.store.close)
        self.sql = []
        self.store._db.set_trace_callback(self.sql.append)

    def full_total(self):
        chunks = self.store._db.execute('SELECT COALESCE(sum(length(payload)+length(descriptor)+128),0) FROM chunks').fetchone()[0]
        snapshots = self.store._db.execute('SELECT COALESCE(sum(length(body)+128),0) FROM snapshots').fetchone()[0]
        return chunks + snapshots

    def scans(self):
        return sum('SELECT COALESCE(sum(' in statement for statement in self.sql)

    def publish(self, label, offset=0):
        self.sql.clear()
        self.store.put(key(label), {'a': np.arange(64.) + offset})
        scans = self.scans()
        if self.store._retained is not None:
            self.assertEqual(self.store._retained[1], self.full_total())
        return scans

    def test_incremental_total_matches_scan_and_other_connection_invalidates_it(self):
        self.assertEqual(self.publish('one'), 2)
        self.assertEqual(self.publish('two', 1), 0)
        self.assertEqual(self.publish('two', 1), 0)  # duplicate publication adds no bytes
        with ArrayStore(self.path, LIMITS, RAW) as other:
            other.put(key('external'), {'b': np.arange(64.) + 2})
        self.assertEqual(self.publish('three', 3), 2)
        self.assertEqual(self.publish('four', 4), 0)

    def test_trigger_writes_force_scan_and_disable_the_retained_shortcut(self):
        self.publish('one')
        self.store._db.execute("CREATE TRIGGER extra_snapshot AFTER INSERT ON snapshots BEGIN "
                               "INSERT INTO snapshots SELECT '%s', body, digest FROM snapshots WHERE id=NEW.id; END" % key('trigger'))
        self.assertEqual(self.publish('two', 1), 2)
        self.assertIsNone(self.store._retained)
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 3)
        self.store._db.execute('DROP TRIGGER extra_snapshot')
        self.assertEqual(self.publish('three', 2), 2)
        self.assertIsNotNone(self.store._retained)

    def test_refused_publication_and_direct_rollback_do_not_reuse_a_stale_total(self):
        self.publish('one')
        before = self.full_total()
        def refuse():
            raise RuntimeError('fixture refuses publication')
        with self.assertRaisesRegex(RuntimeError, 'fixture refuses'):
            self.store.put(key('refused'), {'a': np.arange(64.) + 1}, publication_check=refuse)
        self.assertEqual(self.full_total(), before)
        self.assertIsNone(self.store._retained)
        self.assertFalse(self.store.contains(key('refused')))
        self.assertEqual(self.publish('two', 2), 2)
        self.store._db.execute('BEGIN IMMEDIATE')
        self.store._db.execute("INSERT INTO snapshots SELECT ?, body, digest FROM snapshots LIMIT 1", (key('rolled-back'),))
        self.store._db.execute('ROLLBACK')
        self.assertEqual(self.publish('three', 3), 2)


if __name__ == '__main__':
    unittest.main()
