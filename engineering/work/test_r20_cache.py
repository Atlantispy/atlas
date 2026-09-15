"""One actual-Store stage-cache regression; no politics model or old Store matrix."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from work.generator_upgrade_r20.cache import StageCache, CacheWriteSkipped


class StageCacheTests(unittest.TestCase):
    def test_reuse_copy_binding_invalidation_and_explicit_skip(self):
        binding = {'sources': {'fixture': 'synthetic source revision 1'},
                   'data': {'identity': 'synthetic bounded inputs'},
                   'owner': {'source_status': 'SYNTHETIC TEST'},
                   'frame': 'SYNTHETIC_LOCAL_METRES', 'config': {'rule': 1}}
        original_binding = deepcopy(binding)
        invocation = {'supports': ['synthetic-A'], 'seed': 7}
        expected = {'source_status': 'SYNTHETIC TEST', 'rows': [{'id': 'synthetic-A', 'value': '1/3'}],
                    'original_producer_seconds': .125}
        calls = {'producer': 0, 'validator': 0}

        def producer():
            calls['producer'] += 1
            return deepcopy(expected)

        def validator(value):
            calls['validator'] += 1
            self.assertEqual(value, expected)
            # A validator must not be able to change the value returned/saved.
            value['rows'][0]['value'] = 'validator-only mutation'

        def forbidden():
            self.fail('A verified hit must not execute the producer')

        # A short, dedicated root exercises the actual unchanged authenticated
        # Store. Its established security/internal matrix is not repeated here.
        with tempfile.TemporaryDirectory(prefix='r20-') as temporary:
            root = Path(temporary)
            cache = StageCache('input_stage', binding, root/'values')
            binding['config']['rule'] = 99  # Constructor binding is independent.
            cold, hit = cache.reuse(invocation, producer, validator)
            self.assertFalse(hit)
            self.assertEqual(cold, expected)
            cold['rows'][0]['value'] = 'caller-only mutation'
            warm, hit = cache.reuse(invocation, forbidden, validator)
            self.assertTrue(hit)
            self.assertEqual(warm, expected)
            self.assertEqual(calls, {'producer': 1, 'validator': 2})
            warm['rows'].append({'id': 'caller-only extra'})
            reopened = StageCache('input_stage', original_binding, root/'values')
            self.assertEqual(reopened.namespace, cache.namespace)
            restored, hit = reopened.reuse(invocation, forbidden, validator)
            self.assertTrue(hit)
            self.assertEqual(restored, expected)

            # Distinct invocation, stage and dependency closure each invalidate.
            changed_invocation = dict(invocation, seed=8)
            self.assertFalse(cache.reuse(changed_invocation, producer, validator)[1])
            other_stage = StageCache('next_stage', original_binding, root/'values')
            self.assertNotEqual(other_stage.namespace, cache.namespace)
            self.assertFalse(other_stage.reuse(invocation, producer, validator)[1])
            changed_binding = deepcopy(original_binding)
            changed_binding['data']['identity'] = 'synthetic bounded inputs revision 2'
            revised = StageCache('input_stage', changed_binding, root/'values')
            self.assertNotEqual(revised.namespace, cache.namespace)
            self.assertFalse(revised.reuse(invocation, producer, validator)[1])
            self.assertEqual(calls['producer'], 4)
            self.assertTrue(cache.reuse(invocation, forbidden, validator)[1])
            with self.assertRaisesRegex(ValueError, 'validator rejected'):
                cache.reuse(invocation, forbidden, lambda value: False)

            # Restrict this separate real Store to its existing key+lock bytes.
            # This only decreases a test budget, never changes production limits.
            full = StageCache('limited_stage', original_binding, root/'full')
            full._store.max_bytes = 33
            with self.assertWarnsRegex(CacheWriteSkipped, 'not saved.*store full'):
                value, hit = full.reuse(invocation, producer, validator)
            self.assertFalse(hit)
            self.assertEqual(value, expected)
            self.assertEqual(full.stats['writes'], 0)
            self.assertEqual(full.stats['skipped_full'], 1)
            self.assertEqual(len(full.warnings), 1)
            warnings_copy = full.warnings
            warnings_copy.clear()
            self.assertEqual(len(full.warnings), 1)
            before = calls['producer']
            with self.assertWarns(CacheWriteSkipped):
                self.assertFalse(full.reuse(invocation, producer, validator)[1])
            self.assertEqual(calls['producer'], before+1)
            self.assertTrue(cache.reuse(invocation, forbidden, validator)[1])


if __name__ == '__main__':
    unittest.main()
