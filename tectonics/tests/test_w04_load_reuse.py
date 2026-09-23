"""Focused load-cache integration: same scientific result, source-aware identity."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from numpy.testing import assert_array_equal
from atlas_tectonics import LoadSupport, LoadPhase, ColumnLoadState, column_load_change
from atlas_tectonics.reuse import cached_column_load_change, CachePolicy, ReuseController
from atlas_tectonics.storage import ArrayStore, StoreLimits


class LoadReuseTests(unittest.TestCase):
    def test_auto_bypass_and_persistent_hit_invalidation(self):
        support = LoadSupport(('a',), [5.], [2.], geometry_source='synthetic', frame_id='frame', datum_id='datum')
        phases = (LoadPhase('rock', 'rock', 8., 'synthetic'),)
        reference = ColumnLoadState(support, phases, [[3.]], [2.], source_id='before', epoch_id='t0')
        def current(source='after', volume=4.):
            return ColumnLoadState(support, phases, [[volume]], [2.], source_id=source, epoch_id='t1')
        state = current()
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'cache.db', StoreLimits(1024,1<<20,4<<20,4096)) as store:
                control = ReuseController()
                with patch('atlas_tectonics.reuse._invocation_record', side_effect=AssertionError('cheap cache overhead')):
                    result = cached_column_load_change(reference,state,2.,store=store,controller=control)
                assert_array_equal(result,column_load_change(reference,state,2.))
                self.assertEqual(store.statistics()['snapshots'],0)
                always = dict(store=store,controller=control,cache_policy=CachePolicy(mode='always'))
                a = cached_column_load_change(reference,state,2.,**always)
                b = cached_column_load_change(reference,state,2.,batch_columns=1,**always)
                assert_array_equal(a,b)
                self.assertEqual(control.statistics()['hits'],1)
                cached_column_load_change(reference,current('different-source'),2.,**always)
                cached_column_load_change(reference,current(volume=5.),2.,**always)
                cached_column_load_change(reference,state,3.,**always)
                self.assertEqual(control.statistics()['writes'],4)


if __name__ == '__main__':
    unittest.main()
