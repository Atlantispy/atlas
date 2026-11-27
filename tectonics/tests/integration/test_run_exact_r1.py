"""Run-exact speed plan r2, R-1: a recipe row's descriptor identity comes from the original's stream.

The rebuilt-record comparison at publish (C05430) is removed; the read path still rebuilds and proves it.
Synthetic inputs only.
SPDX-License-Identifier: AGPL-3.0-only
"""
import gc
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from atlas_tectonics.integration.resources import WorkBudget
from atlas_tectonics._private.codecs.content_cache import create_retained_scope
from atlas_tectonics._private.codecs.interval_store_set import IntervalStoreSet
from atlas_tectonics._private.codecs.record_tables import RecordCodec, canonical
from atlas_tectonics._private.integration.geometry import spatial_record_recipes as RECIPES
from atlas_tectonics._private.integration.geometry import spatial_records_patch as SR
from atlas_tectonics._private.integration import width_gate as WG

PRODUCER = {'execution_identity': 'b'*64, 'role': 'synthetic run-exact R-1 fixture'}


class RecipeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='run-exact-r1-')
        self.budget = WorkBudget(2 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='run-exact-r1')
        self.stores = IntervalStoreSet.create_migration(str(Path(self.temp.name)/'catalog.json'),
            workflow_id='1'*64, scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)
        self.packed = RecordCodec().pack_record({'schema': 'x', 'blob': ['x'*1024]*5000},
            record_schema='atlas.spatial-working-record.v1', scope=self.scope, check=lambda: None)
        self.ref = self.packed.root()

    def tearDown(self):
        self.ref.close()
        self.packed.close()
        self.candidate.close()
        self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temp.cleanup()

    def _fed(self, value):
        seen = []
        got = RECIPES.value_identity(value, scope=self.scope, check=lambda: None, feed=seen.append)
        raw = b''.join(bytes(b) for b in seen)
        self.assertEqual(got, {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()})
        return got, raw

    def test_recipe_descriptor_is_proved_by_the_rebuilt_record(self):
        rows = {'state': {'schema': 's', 'big': self.ref}}
        refs = SR.publish_records(self.candidate, rows, budget=self.budget, source_producer=PRODUCER)
        self.assertTrue(RECIPES.is_v2(refs['state']), 'fixture must take the recipe path')
        want, _ = self._fed(rows['state'])
        self.assertEqual({k: refs['state'][k] for k in ('bytes', 'sha256')}, want)
        # prove=True rebuilds from the published segments and requires the descriptor identity.
        # The publish scan now reads the original's stream; it must give the rebuilt record's scan result.
        original, rebuilt = WG.OptionalScan(), WG.OptionalScan()
        RECIPES.value_identity(rows['state'], scope=self.scope, check=lambda: None, feed=original.feed)
        with SR.open_records(self.candidate, refs, budget=self.budget, source_producer=PRODUCER) as children:
            got = RECIPES.stream_identity(children['state'], lambda: None, feed=rebuilt.feed)
            del children
        self.assertEqual(got, want)
        self.assertIsNotNone(original.result())
        self.assertEqual(original.result(), rebuilt.result())

    def test_feed_sees_each_branch_bytes_once(self):
        plain = {'schema': 's', 'n': [1, 2, 3]}
        self.assertEqual(self._fed(plain)[1], canonical(plain))
        self._fed(self.ref)
        self._fed({'schema': 's', 'big': self.ref})


if __name__ == '__main__':
    unittest.main()
