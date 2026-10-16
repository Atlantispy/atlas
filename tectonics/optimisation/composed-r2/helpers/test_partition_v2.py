"""WP4 domain/segment fixtures; no historical database, migration or solve."""
from concurrent.futures import CancelledError
from copy import deepcopy
import gc
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
RUNTIME = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(HERE.parent))

from compact_contracts import ContractError
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
import partition_tables as P
import partition_store as S
import partition_workflow_patch as W
from record_tables import RecordCodec
from record_views import CompactRecord
from segment_store import SegmentBackend
from test_partition_tables import tiny_partition, D, WorkBudget


def stream_bytes(value):
    result = []
    with value.iter_json() as stream:
        for part in stream:
            with part:
                result.append(part.value)
    return b''.join(result)


class PartitionV2Tests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='wp4-partition-v2')
        self.scope_baseline = self.budget.reserved_bytes
        self.body, self.rows = tiny_partition(self.budget)

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def packed(self, body=None, rows=None, **kwargs):
        body = self.body if body is None else body
        return P.pack_partition_v2(body, iter(self.rows if rows is None else rows),
            expected_partition_id=D._record_hash(body), scope=self.scope, **kwargs)

    def test_fresh_exact_descriptor_body_supports_and_historical_header(self):
        view = self.packed()
        expected = dict(self.body, partition_id=D._record_hash(self.body), supports=self.rows)
        self.assertEqual(stream_bytes(view), D._encoded(expected))
        self.assertEqual(view.identity().sha256, sha256(D._encoded(expected)).hexdigest())
        body = view.root()
        self.assertEqual(stream_bytes(body), D._encoded(self.body))
        self.assertEqual(body.identity().sha256, view.partition_id)
        body.close()
        for i, row in enumerate(self.rows):
            ref = view.support_by_id(view.support_id(i))
            self.assertEqual(stream_bytes(ref), D._encoded(row)); ref.close()
        metadata, arrays = P.pack_partition(self.body, self.rows,
            expected_partition_id=D._record_hash(self.body), budget=self.budget)
        old = P.CompactPartition(metadata, arrays, expected_partition_id=view.partition_id, budget=self.budget)
        refs = {'partition': {'array': 'partition-record:partition',
                             'bytes': len(D._encoded(expected)), 'sha256': view.identity().sha256}}
        self.assertEqual(W.compact_header(view, refs), W.compact_header(old, refs))
        del old, arrays, metadata
        view.close()

    def test_streamed_rows_exact_count_and_order_and_unknown_science_refuse(self):
        for rows in (self.rows[::-1], self.rows[:-1], self.rows+[self.rows[0]]):
            with self.assertRaises((ContractError, P.PartitionTablesRefused)):
                self.packed(rows=rows)
        for target in ('support', 'component', 'constraint'):
            rows, body = deepcopy(self.rows), deepcopy(self.body)
            selected = {'support': rows[0], 'component': rows[0]['components'][0],
                        'constraint': rows[0]['constraints']['plane']}[target]
            selected['unknown-science'] = 1
            body['support_ids'] = [D._record_hash(row) for row in rows]
            with self.assertRaisesRegex(ContractError, 'scientific field'):
                self.packed(body, rows)
        rows, body = deepcopy(self.rows), deepcopy(self.body)
        rows[0]['constraints']['plane']['offset'] = ['0xzz', '0x1']
        body['support_ids'] = [D._record_hash(row) for row in rows]
        with self.assertRaisesRegex(ContractError, 'rational string'):
            self.packed(body, rows)

    def test_owned_refs_and_streams_block_close_and_bounded_export(self):
        view = self.packed()
        support = view.support(0)
        self.assertFalse(hasattr(support, '__getitem__'))
        with self.assertRaises(RuntimeError):
            view.close()
        with self.assertRaisesRegex(ContractError, 'export bound'):
            support.export(max_logical_bytes=1, max_owned_bytes=1 << 20)
        support.close()
        stream = view.iter_json(max_chunk_bytes=23)
        first = next(stream)
        stream.close()
        self.assertLessEqual(len(first.value), 23)
        self.assertGreater(first.charged_bytes, 0)
        first.close()
        with self.assertRaises(AttributeError):
            view._partition_id = '0'*64
        view.close()

    def test_benefit_gated_options_refuse_explicitly(self):
        for option in ({'parent_pool': object()}, {'locality_permutation': []}, {'support_cache': True}):
            with self.assertRaisesRegex(ContractError, 'disabled pending measured benefit gate'):
                self.packed(**option)

    def test_cancellation_keeps_failure_owned_until_traceback_release(self):
        called = 0
        def check():
            nonlocal called
            called += 1
            if called == 200:
                raise CancelledError('partition v2 cancellation')
        held = None
        try:
            self.packed(check=check)
        except CancelledError as error:
            held = error
        self.assertIsNotNone(held)
        self.assertGreater(self.budget.reserved_bytes, self.scope_baseline)
        held = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.scope_baseline)

    def test_segment_publish_retry_reopen_and_foreign_scope(self):
        with tempfile.TemporaryDirectory(prefix='wp4-', dir=TASK/'_t') as directory:
            stores = IntervalStoreSet.create_migration(str(Path(directory)/'catalog.json'),
                workflow_id='a'*64, scope=self.scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            view = self.packed()
            ref = S.publish_partition_v2(candidate, view, producer='d'*64)
            before = candidate.local_statistics()
            with patch.object(CompactRecord, 'array_sources', side_effect=AssertionError('retry encoded')):
                self.assertEqual(S.publish_partition_v2(candidate, view, producer='d'*64), ref)
            self.assertEqual(candidate.local_statistics(), before)
            view.close()
            stores.promote(candidate.seal(ref), expected_catalog_digest=None)
            reopened = S.open_partition_v2(stores, ref, scope=self.scope)
            self.assertEqual(stream_bytes(reopened), D._encoded(dict(self.body,
                partition_id=D._record_hash(self.body), supports=self.rows)))
            reopened.close()
            foreign = create_retained_scope(WorkBudget(1 << 30), process_epoch='foreign-wp4')
            with self.assertRaisesRegex(S.CompactPartitionStoreRefused, 'same-scope'):
                S.open_partition_v2(stores, ref, scope=foreign)
            foreign.close()
            candidate.close(); stores.close()

    def test_reference_only_successor_fresh_process(self):
        with tempfile.TemporaryDirectory(prefix='wp4-cold-', dir=TASK/'_t') as directory:
            catalog = str(Path(directory)/'catalog.json')
            stores = IntervalStoreSet.create_migration(catalog, workflow_id='a'*64, scope=self.scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            view = self.packed()
            partition = S.publish_partition_v2(candidate, view, producer='d'*64)
            expected = view.identity().to_wire()
            view.close()
            stores.promote(candidate.seal(partition), expected_catalog_digest=None)
            candidate = stores.begin_interval(stores.head, producer_identity='b'*64, runtime_identity='c'*64)
            head_value = {'schema': 'test.workflow-head.v1', 'compact_partition': partition.to_wire()}
            head = RecordCodec().pack_record(head_value, record_schema='test.workflow-head.v1',
                                             scope=self.scope, check=lambda: None)
            with head.metadata_bytes() as metadata:
                ref = SegmentBackend().publish(candidate, record_schema='test.workflow-head.v1',
                    identity=head.identity(), metadata=metadata.value, arrays=head.array_sources,
                    producer='d'*64, representation_profile='test.reference-only.v1', scope=self.scope)
            head.close()
            # A reference-only successor binds the allowed ancestor explicitly.
            with candidate.resolve_manifest(partition.root_key):
                pass
            stores.promote(candidate.seal(ref), expected_catalog_digest=stores.catalog_digest)
            stores.close(); gc.collect()
            script = '''
import gc,json,sys
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from compact_contracts import SegmentRef
from interval_store_set import IntervalStoreSet
from segment_store import SegmentBackend
from record_views import CompactRecord
from partition_store import open_partition_v2
b=WorkBudget(1<<30); s=create_retained_scope(b,process_epoch='wp4-fresh-reader')
stores=IntervalStoreSet.open_catalog(sys.argv[1],scope=s)
print('catalog opened',file=sys.stderr,flush=True)
head=CompactRecord.from_segment(SegmentBackend().open(stores,stores.head.head,scope=s))
print('head opened',file=sys.stderr,flush=True)
with head.export(max_logical_bytes=4096,max_owned_bytes=1<<20) as owned:
    ref=SegmentRef.from_wire(owned.value['compact_partition'])
head.close()
v=open_partition_v2(stores,ref,scope=s)
print('partition opened',file=sys.stderr,flush=True)
print(json.dumps({'identity':v.identity().to_wire(),'supports':v.support_count,'parent_interval':ref.root_key.interval}))
v.close(); stores.close(); gc.collect(); s.close()
assert b.reserved_bytes==0,b.reserved_bytes
'''
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                       PYTHONPATH=os.pathsep.join((str(HERE), str(HERE.parent), str(RUNTIME))))
            result = subprocess.run([sys.executable, '-B', '-c', script, catalog], env=env,
                                    capture_output=True, text=True, check=False, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data, {'identity': expected, 'supports': len(self.rows), 'parent_interval': 0})


if __name__ == '__main__':
    unittest.main()
