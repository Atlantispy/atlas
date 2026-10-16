"""Step 6 composition and metadata-only successor boundary."""
from copy import deepcopy
from pathlib import Path
import gc
import unittest

import test_spatial_records_patch  # establishes the existing component import roots
import test_run_prepared_restart as runner_tests
import workflow_transfer as W
import run_prepared_restart as R
import spatial_workflow_patch as Y
import partition_workflow_transform as P
import spatial_records_patch as S
import spatial_validation_patch as V

HERE = Path(__file__).resolve().parent


class IntegrationTests(unittest.TestCase):
    def test_successor_eleven_checks_accept_compact_record_headers_without_payload(self):
        # Reuse the existing runner fixture and add the new compact descriptors.
        # This fake has metadata only: any payload read would fail immediately.
        fixture = runner_tests.SuccessorCheckTests()
        fixture.setUp()
        try:
            descriptor = dict(bytes=9, sha256='a'*64, compact={
                'schema': S.REFERENCE_SCHEMA, 'field': 'state',
                'segment': {'binding': 'metadata-only structural check'}})
            fixture.head['exterior_state'] = dict(
                state_id='b'*64, record_blobs={'state': descriptor})
            fixture.head['exterior_advance'] = dict(
                result_id='c'*64, record_blobs={
                    kind: dict(deepcopy(descriptor), compact=dict(descriptor['compact'], field=kind))
                    for kind in ('exchange', 'graph', 'transport', 'heat')})
            after, store = fixture.run_checks()
            self.assertEqual(len(R.SUCCESSOR_CHECKS), 11)
            self.assertEqual(after['head'], fixture.head['key'])
            self.assertEqual(store.reads, [fixture.head['key'], fixture.root['key'],
                fixture.root['key'], W.workflow_key('successor', fixture.head['key'])])
        finally:
            fixture.tearDown()

    def test_transform_layers_compose_once(self):
        source = (HERE.parents[1]/'runtime-integration-r1/runtime-src/atlas_tectonics/integration_regional_workflow.py').read_text(encoding='utf8')
        initial = Y.transform(W.nonzero_cursor_source(source))
        first = P.transform(initial)
        for prior in (first, P.transform_v2(first)):
            records = S.transform(prior)
            final = V.workflow_source(records)
            compile(final, '<step6-composed-workflow>', 'exec')
            self.assertIn('_COMPACT_RECORDS.publication_check', final)
            self.assertIn('with _SV.access(exchange)', final)
            with self.assertRaises(ValueError):
                V.workflow_source(final)

    def test_store_dispatch_uses_compact_route_and_preserves_legacy_signature(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        called = []
        @contextmanager
        def compact(*args, **kwargs):
            called.append((args, kwargs))
            yield ('headers', 'exchange', {})
        store = SimpleNamespace(scope=object())
        with patch.object(S, 'records', compact):
            with Y.records('cls', 'state', 'exchange', 'budget', store=store,
                           source_producer={'id': 'test'}) as result:
                self.assertEqual(result, ('headers', 'exchange', {}))
        with patch.object(S, 'restore_records', compact):
            with Y.restore_records('cls', 'state', 'exchange', {}, 'budget', store=store) as result:
                self.assertEqual(result, ('headers', 'exchange', {}))
        self.assertEqual(len(called), 2)
        gc.collect()


if __name__ == '__main__':
    unittest.main()
