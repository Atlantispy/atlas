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

from atlas_tectonics import TectonicsError
from atlas_tectonics.integration import reuse
from atlas_tectonics.codecs.storage import ArrayStore, Compression, StoreLimits


def key(label):
    return hashlib.sha256(label.encode()).hexdigest()


def state(mode=None):
    return types.SimpleNamespace(mode=mode, handles=None, captures={}, lock=threading.RLock())


LIMITS = StoreLimits(1024, 1 << 20, 4 << 20)
RAW = Compression('raw', palette=False)


class PackagedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = Path(self.tmp.name)/'bundle'
        self.tectonics = self.bundle/'resources'/'atlas'/'tectonics'
        self.source = self.tectonics/'src'/'atlas_tectonics'/'_identity.py'
        self.entry = self.tectonics/'tools'/'run/new_world.py'
        self.python = self.bundle/'resources'/'python'/'python.exe'
        self.marker = self.tectonics/'.desktop-runtime.json'
        for path in (self.source, self.entry, self.python, self.bundle/'Atlas.exe'):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(reuse._atlas_identity, '__file__', str(self.source)))
        self.stack.enter_context(mock.patch.object(sys, 'executable', str(self.python)))
        self.stack.enter_context(mock.patch.object(sys, 'argv', [str(self.entry)]))
        self.stack.enter_context(mock.patch.object(reuse, '_release_state', state()))

    def mark(self, **extra):
        self.marker.write_text(json.dumps(dict(schema='atlas.desktop-runtime.v1', identity_mode='release', **extra)))

    def test_environment_cannot_enable_release_and_checkout_marker_refuses(self):
        with mock.patch.dict(os.environ, {'ATLAS_IDENTITY_MODE': 'release'}):
            self.assertEqual(reuse.execution_mode(), 'strict')
        self.mark()
        with mock.patch.object(reuse._atlas_identity, '__file__',
                               str(Path(self.tmp.name)/'checkout'/'src'/'atlas_tectonics'/'_identity.py')):
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
            entry.touch()
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
        with ThreadPoolExecutor(8) as pool:
            contexts = list(pool.map(reuse.ExecutionContext, ['reference', 'scipy'] * 8))
        self.assertEqual(len({context.identity for context in contexts}), 2)
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
    def test_refusal_at_the_publication_boundary_rolls_back_the_snapshot(self):
        self.policy.mode = 'release'
        with ArrayStore(self.root/'late.db', LIMITS, RAW) as store:
            def refuse():
                raise TectonicsError('publication refused')
            with self.assertRaisesRegex(TectonicsError, 'publication refused'):
                store.put(key('late'), {'a': np.arange(16.)}, publication_check=refuse)
            self.assertFalse(store.contains(key('late')))
            self.assertEqual(store._db.execute('SELECT count(*) FROM chunks').fetchone()[0], 0)


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
