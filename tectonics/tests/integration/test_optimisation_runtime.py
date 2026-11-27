"""Bounded integrity checks for retained-store accounting.

All files, package layouts and databases written here are disposable fixtures.
"""
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from atlas_tectonics.codecs.storage import ArrayStore, Compression, StoreLimits


def key(label):
    return hashlib.sha256(label.encode()).hexdigest()


LIMITS = StoreLimits(1024, 1 << 20, 4 << 20)
RAW = Compression('raw', palette=False)


class RetainedAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
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
