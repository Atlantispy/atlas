"""Step 8 publication by reference: exact bytes, no re-import, fail-closed readers."""
import gc
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parents[1]/'runtime-integration-r1/runtime-src')]

import live_composite as LC
import record_tables as T
import spatial_record_recipes as RECIPES
import spatial_records_patch as P
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError, SegmentRef
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from record_views import LogicalExchange, _ObjectRecordRef
from segment_store import SegmentView

PRODUCER = {'execution_identity': 'c'*64, 'role': 'synthetic Step 8 recipe fixture'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def stream(value):
    output = []
    with value.iter_json() as blocks:
        for block in blocks:
            with block:
                output.append(block.value)
    return b''.join(output)


def big_rows(count):
    """Distinct exact content, so the borrowed rows exceed the lowered bound."""
    return {sha256(str(i).encode()).hexdigest(): {'volume': ['0x'+format(i+1, 'x')*40, '0x3'],
            'label': 'réceipt '+str(i), 'faces': [i, i+1, 'f'*64]} for i in range(count)}


class RecipeFixture:
    """Live holders as the composed producers leave them: graph composite over
    bounds, proposal composite over the graph, transport overlay, exchange
    composite over all three, and state metadata borrowing a cells record."""

    def __init__(self, scope, rows=1500):
        def pack(value, schema):
            return T.RecordCodec().pack_record(value, record_schema=schema, scope=scope, check=lambda: None)
        self.native = {}
        receipts = big_rows(rows)
        intervals = [{'face': i, 'bounds': ['0x1', '0x2']} for i in range(50)]
        bounds_value = {'schema': 'bounds', 'physical_measure_receipts': receipts,
                        'face_intervals': intervals, 'cells': [{'cell_id': 'b'*64, 'start': ['0x1', '0x1']}]}
        self.bounds = pack(bounds_value, 'atlas.spatial-working-record.v1')
        graph_cells = [{'cell_id': 'g'*64, 'end': ['0x5', '0x7']}]
        with self.bounds.root() as broot:
            receipts_ref, transfers = broot.field('physical_measure_receipts'), broot.field('face_intervals')
            graph_value = {'physical_measure_receipts': receipts_ref, 'schema': 'graph',
                           'original_face_intervals': transfers, 'cells': graph_cells, 'bounds_id': 'a'*64}
            self.graph = LC.compose_record(graph_value, record_schema='atlas.spatial-working-record.v1',
                                           scope=scope, check=lambda: None)
            receipts_ref.close()
            transfers.close()
        self.native['graph'] = {'schema': 'graph', 'physical_measure_receipts': receipts,
                                'original_face_intervals': intervals, 'cells': graph_cells, 'bounds_id': 'a'*64}
        with self.graph.root() as groot:
            borrowed = {k: groot.field(k) for k in ('physical_measure_receipts', 'original_face_intervals')}
            proposal = {'schema': 'proposal', 'stocks': {'v': ['0x1', '0x2']},
                        'graph': {**borrowed, 'cells': [{'cell_id': 'p'*64}], 'finite_inventory': {'o': 1}}}
            self.proposal = LC.compose_record(proposal, record_schema='atlas.finite-spatial-stock-proposal.v1',
                                              scope=scope, check=lambda: None)
            for ref in borrowed.values():
                ref.close()
        native_proposal = {'schema': 'proposal', 'stocks': {'v': ['0x1', '0x2']},
                           'graph': {'physical_measure_receipts': receipts, 'original_face_intervals': intervals,
                                     'cells': [{'cell_id': 'p'*64}], 'finite_inventory': {'o': 1}}}
        transport_value = {'schema': 'transport', 'cell_ids': ['t'*64]*3, 'exact': big_rows(600)}
        self.transport = pack(transport_value, 'atlas.spatial-implicit-transport.v1')
        header = pack({'result_id': 'e'*64}, 'atlas.transport-result-header.v1')
        cells_value = [{'cell_id': 's'*64, 'volume': ['0x1', '0x2']}]*5+[{'big': big_rows(400)}]
        self.cells = pack(cells_value, 'atlas.spatial-state-cells.v1')
        # As live_finite_patch.record and live_transport_result.result_record do,
        # the overlay bases are temporary handles that retire by reference count.
        transport_view = _ObjectRecordRef(self.transport.root(), overlay=header.root())
        proposal_view = _ObjectRecordRef(self.proposal.root(), overlay=pack(
            {'proposal_id': '9'*64}, 'atlas.finite-proposal-header.v1').root())
        with self.graph.root() as graph_ref:
            exchange = {'schema': 'exchange', 'owner_id': 'o'*64, 'spatial_graph': graph_ref,
                        'transport': transport_view, 'finite_proposal': proposal_view,
                        'joined_heat': {'result_id': 'h'*64}, 'joined_heat_plan': {'k': [1.5, 2.5]}}
            self.exchange = LC.compose_record(exchange, record_schema='atlas.spatial-exchange-body.v1',
                                              scope=scope, check=lambda: None)
        # The exchange composite holds its own detached borrows.
        transport_view.close()
        proposal_view.close()
        self.native['transport'] = {**transport_value, 'result_id': 'e'*64}
        self.native['exchange_full'] = {'schema': 'exchange', 'owner_id': 'o'*64,
            'spatial_graph': self.native['graph'], 'transport': self.native['transport'],
            'finite_proposal': {**native_proposal, 'proposal_id': '9'*64},
            'joined_heat': {'result_id': 'h'*64}, 'joined_heat_plan': {'k': [1.5, 2.5]}}
        self.state_meta = {'schema': 'state', 'state_id': '1'*64, 'time_s': 2.0, 'intervals': 2}
        self.native['state'] = {**self.state_meta, 'cells': cells_value}

    def rows(self):
        """Publication rows exactly as spatial_records_patch.records builds them."""
        full = LogicalExchange.from_body(self.exchange, state_id='1'*64, result_id='2'*64)
        body = full.without(('spatial_graph', 'transport', 'joined_heat'))
        graph, transport, heat = (full.field(k) for k in ('spatial_graph', 'transport', 'joined_heat'))
        cells = self.cells.root()
        rows = {'state': {**self.state_meta, 'cells': cells}, 'exchange': body,
                'graph': graph, 'transport': transport, 'heat': heat}
        native_exchange = {k: v for k, v in self.native['exchange_full'].items()
                           if k not in ('spatial_graph', 'transport', 'joined_heat')}
        native = {'state': self.native['state'], 'graph': self.native['graph'],
                  'transport': self.native['transport'], 'heat': {'result_id': 'h'*64},
                  'exchange': {**native_exchange, 'state_id': '1'*64, 'result_id': '2'*64}}
        # Derived views borrow from the full overlay: close them first.
        return rows, native, [cells, heat, transport, graph, body, full]


class RecipePublicationTests(unittest.TestCase):
    # The fixture is kilobytes, not IV1 megabytes; lower only the policy bound
    # that selects reference publication. Store limits stay the real ones, and
    # test_real_threshold_selects_v1_for_small_rows keeps the real bound.
    SMALL = 64 << 10

    def setUp(self):
        threshold = patch.object(RECIPES, 'SMALL_IMPORT_BYTES', self.SMALL)
        threshold.start()
        self.addCleanup(threshold.stop)
        self.temp = tempfile.TemporaryDirectory(prefix='step8-recipes-')
        self.root = Path(self.temp.name)
        self.budget = WorkBudget(2 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='step8-recipe-fixture')
        self.stores = IntervalStoreSet.create_migration(str(self.root/'catalog.json'),
            workflow_id='4'*64, scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='5'*64, runtime_identity='6'*64)
        self.fixture = RecipeFixture(self.scope)

    def tearDown(self):
        self.fixture = None
        self.candidate.close()
        self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temp.cleanup()

    def publish(self):
        rows, native, handles = self.fixture.rows()
        refs = P.publish_records(self.candidate, rows, budget=self.budget, source_producer=PRODUCER)
        for handle in handles:
            handle.close()
        return refs, native

    def seal(self, refs):
        # Reopen is a sealed-interval operation (the reader's page cache binds
        # sealed file identities); unsealed candidates are write-side only.
        self.stores.promote(self.candidate.seal(P.primary_segment(refs)),
                            expected_catalog_digest=self.stores.catalog_digest)

    def test_exact_identities_and_v2_only_for_large_borrowed_rows(self):
        refs, native = self.publish()
        for kind, value in native.items():
            raw = canonical(value)
            self.assertEqual((refs[kind]['bytes'], refs[kind]['sha256']),
                             (len(raw), sha256(raw).hexdigest()), kind)
        for kind in ('graph', 'exchange', 'transport', 'state'):
            self.assertTrue(RECIPES.is_v2(refs[kind]), kind)
        self.assertFalse(RECIPES.is_v2(refs['heat']))
        for value in refs.values():
            self.assertLessEqual(len(canonical(value)), RECIPES.MAX_DESCRIPTOR_BYTES)

    def test_borrowed_records_are_published_once_not_reimported(self):
        imported = []
        real = T.RecordCodec.pack_record
        def spy(codec, value, **kwargs):
            if kwargs.get('record_schema') == P.BUNDLE_SCHEMA:
                # Measured at call time: the borrows are released afterwards.
                imported.append(RECIPES.borrowed_bytes(value))
            return real(codec, value, **kwargs)
        with patch.object(T.RecordCodec, 'pack_record', spy):
            refs, _ = self.publish()
        self.assertEqual(len(imported), 1)
        # The bundle holds no large borrowed record: only natives and small refs.
        self.assertLessEqual(imported[0], self.SMALL*8)
        segments = {canonical(item) for ref in refs.values() if RECIPES.is_v2(ref)
                    for item in ref['compact']['segments']}
        schemas = {SegmentRef.from_wire(json.loads(raw)).identity.record_schema for raw in segments}
        # bounds (receipts), graph skeleton, transport body, state cells and the bundle.
        for schema in ('atlas.spatial-working-record.v1', 'atlas.spatial-implicit-transport.v1',
                       'atlas.spatial-state-cells.v1', P.BUNDLE_SCHEMA):
            self.assertIn(schema, schemas)
        # The bounds receipts back both the graph and the proposal: one segment.
        bounds_sha = self.fixture.bounds.identity().sha256
        bounds = [raw for raw in segments
                  if SegmentRef.from_wire(json.loads(raw)).identity.sha256 == bounds_sha]
        self.assertEqual(len(bounds), 1)

    def test_reopen_exact_children_and_shared_backing(self):
        refs, native = self.publish()
        self.seal(refs)
        with P.open_records(self.stores, refs, budget=self.budget, source_producer=PRODUCER) as opened:
            for kind, value in native.items():
                self.assertEqual(stream(opened[kind]), canonical(value), kind)
            with opened['graph'].field('physical_measure_receipts') as a, \
                    opened['exchange'].field('finite_proposal') as proposal, \
                    proposal.field('graph') as graph, graph.field('physical_measure_receipts') as b:
                self.assertIs(a._view, b._view)
                self.assertEqual(a.index, b.index)
            for value in opened.values():
                value.close()

    def test_republication_is_idempotent_and_adds_no_chunks(self):
        first, _ = self.publish()
        before = self.candidate.local_statistics()
        second, _ = self.publish()
        self.assertEqual(first, second)
        self.assertEqual(before, self.candidate.local_statistics())

    def test_verify_is_metadata_only_and_mutations_refuse(self):
        refs, _ = self.publish()
        with patch.object(SegmentView, 'read', side_effect=AssertionError('payload read')), \
                patch.object(SegmentView, 'iter', side_effect=AssertionError('payload streamed')):
            P.verify_records(self.candidate, refs, budget=self.budget, source_producer=PRODUCER)
            with self.assertRaisesRegex(ContractError, 'producer differs'):
                P.verify_records(self.candidate, refs, budget=self.budget,
                                 source_producer={**PRODUCER, 'role': 'changed'})
        self.seal(refs)
        mutations = (
            lambda x: x['graph'].__setitem__('sha256', 'a'*64),
            lambda x: x['graph']['compact'].__setitem__('schema', 'atlas.spatial-record-ref.v3'),
            lambda x: x['graph']['compact']['segments'][0].__setitem__('merkle_root', 'a'*64),
            lambda x: x['graph']['compact']['segments'][0]['root_key'].__setitem__('snapshot_key', 'b'*64),
            lambda x: x['graph']['compact']['segments'].append(x['graph']['compact']['segments'][0]),
            lambda x: x['exchange']['compact']['recipe'].__setitem__('keys', ['z']),
            lambda x: x['graph']['compact'].__setitem__('extra', 1),
        )
        for mutate in mutations:
            bad = deepcopy(refs)
            mutate(bad)
            with self.assertRaises((ContractError, ValueError, KeyError)), \
                    P.open_records(self.stores, bad, budget=self.budget):
                self.fail('mutated descriptor accepted')
            gc.collect()

    def test_wrong_node_or_reordered_segments_refuse_by_identity(self):
        refs, _ = self.publish()
        self.seal(refs)
        graph = refs['graph']['compact']
        bad = deepcopy(refs)
        def bump(recipe):
            if set(recipe) == {'node'}:
                recipe['node'][1] = max(0, recipe['node'][1]-1)
                return True
            return bump(recipe['base'])
        bump(bad['graph']['compact']['recipe'])
        with self.assertRaisesRegex(ContractError, 'logical identity differs|object base required|'
                                    'reference outside|names a key'), \
                P.open_records(self.stores, bad, budget=self.budget):
            self.fail('wrong node accepted')
        gc.collect()
        if len(graph['segments']) > 1:
            bad = deepcopy(refs)
            bad['graph']['compact']['segments'].reverse()
            with self.assertRaises(ContractError), P.open_records(self.stores, bad, budget=self.budget):
                self.fail('reordered segments accepted')
            gc.collect()

    def test_old_reader_refuses_new_descriptor_and_direct_segment(self):
        refs, _ = self.publish()
        with self.assertRaisesRegex(ContractError, 'schema/binding|binding differs'):
            P._descriptor(refs['graph'], 'graph')
        direct = next(SegmentRef.from_wire(item) for item in refs['graph']['compact']['segments']
                      if SegmentRef.from_wire(item).identity.record_schema != P.BUNDLE_SCHEMA)
        # A v1 descriptor naming the direct segment is refused as a foreign bundle schema.
        forged = {'bytes': refs['graph']['bytes'], 'sha256': refs['graph']['sha256'],
                  'compact': {'schema': P.REFERENCE_SCHEMA, 'segment': direct.to_wire(), 'field': 'graph'}}
        with self.assertRaisesRegex(ContractError, 'foreign record bundle schema'):
            P.verify_records(self.candidate, {'graph': forged}, budget=self.budget)

    def test_cancellation_releases_funding_and_retry_is_exact(self):
        rows, _, handles = self.fixture.rows()
        calls = []
        class Token:
            def is_set(self):
                calls.append(1)
                return len(calls) > 25
        with self.assertRaisesRegex(ContractError, 'cancelled'):
            P.publish_records(self.candidate, rows, budget=self.budget, source_producer=PRODUCER,
                              cancel=Token())
        gc.collect()
        for handle in handles:
            handle.close()
        # A cancelled publication returns no descriptor; any segment roots it
        # completed are whole, and a retry reuses them exactly.
        refs, native = self.publish()
        for kind, value in native.items():
            raw = canonical(value)
            self.assertEqual((refs[kind]['bytes'], refs[kind]['sha256']), (len(raw), sha256(raw).hexdigest()))

    def test_puts_stay_within_store_targets(self):
        refs, _ = self.publish()
        limits = self.candidate.limits
        for ref in refs.values():
            segments = ref['compact']['segments'] if RECIPES.is_v2(ref) else [ref['compact']['segment']]
            for item in segments:
                segment = SegmentRef.from_wire(item)
                self.assertLessEqual(segment.logical_bytes, limits.max_array_bytes//4)
                self.assertLessEqual(-(-segment.logical_bytes//65536), 2048)

    def test_native_rows_keep_v1_bundle_format(self):
        rows = {'state': {'cells': [1, 2]}, 'heat': {'result_id': 'h'*64}}
        refs = P.publish_records(self.candidate, rows, budget=self.budget, source_producer=PRODUCER)
        for kind in rows:
            self.assertEqual(set(refs[kind]['compact']), {'schema', 'segment', 'field'})
            self.assertEqual(refs[kind]['compact']['schema'], P.REFERENCE_SCHEMA)

    def test_real_threshold_selects_v1_for_small_rows(self):
        with patch.object(RECIPES, 'SMALL_IMPORT_BYTES', 4 << 20):
            refs, native = self.publish()
        # Every borrowed row in this small fixture is below the real 4 MiB
        # bound, so the unchanged v1 bundle carries it, exactly.
        for kind, value in native.items():
            self.assertFalse(RECIPES.is_v2(refs[kind]), kind)
            raw = canonical(value)
            self.assertEqual((refs[kind]['bytes'], refs[kind]['sha256']), (len(raw), sha256(raw).hexdigest()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
