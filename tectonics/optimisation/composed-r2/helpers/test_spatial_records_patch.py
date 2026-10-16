"""Synthetic WP5 persistence controls; no historical database or IV2 run."""
from copy import deepcopy
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parents[1]/'runtime-integration-r1/runtime-src')]

from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore
from compact_contracts import ContractError, SegmentRef
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from record_tables import RecordCodec, canonical
from segment_store import SegmentView
import spatial_records_patch as P


PRODUCER = {'execution_identity': 'b'*64, 'role': 'synthetic WP5 component fixture'}


def fixture_records(count=120):
    """IV2-shaped fan-out and repeated exact scalars, not real IV2 capacity."""
    face = {'face_id': 'f'*64, 'rate': ['0x'+'f'*1024, '0x1'], 'cells': ['a'*64, 'b'*64]}
    cells = [{'cell_id': sha256(str(i).encode()).hexdigest(), 'plate_id': 0,
              'volume': ['0x7', '0x2']} for i in range(count)]
    graph = dict(schema='synthetic.graph', parent_state_id='c'*64, cells=cells,
        internal_faces=[face]*count, outer_faces=[face]*count, collar_faces=[face]*count,
        support_ids=['d'*64]*count)
    graph_id = sha256(canonical(graph)).hexdigest()
    state = {k: '1'*64 for k in P.STATE_NAMES}
    state.update(schema='synthetic.state', intervals=2, time_s=2., cells=cells)
    body = {k: '2'*64 for k in P.EXCHANGE_NAMES}
    body.update(schema='synthetic.exchange', spatial_graph_id=graph_id,
        finite_proposal={'graph': graph}, no_source_replay=True)
    transport = dict(schema='synthetic.transport', result_id='e'*64, faces=[face]*count)
    heat = dict(result_id='9'*64, checkpoint={'metadata_sha256': '8'*64, 'metadata_bytes': 616_000_000})
    return dict(state=state, mesh={'schema': 'synthetic.mesh', 'cells': []},
                exchange=body, graph=graph, transport=transport, heat=heat)


def successor_fixture(candidate, budget, count=120):
    rows = fixture_records(count)
    refs = P.publish_records(candidate, rows, budget=budget, source_producer=PRODUCER)
    full = dict(rows['exchange'], spatial_graph=rows['graph'], transport=rows['transport'], joined_heat=rows['heat'])
    a, b = P.headers(rows['state'], full, refs)
    row = dict(kind='successor', sequence=2, exterior_state=a, exterior_advance=b)
    numeric = {'spatial:inventory': np.zeros((count, 7), dtype='<f8'),
               'spatial:heat': np.zeros(count, dtype='<f8')}
    return row, numeric, refs, rows


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wp5-records-')
        self.root = Path(self.temp.name)
        self.budget = WorkBudget(2 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='wp5-records-fixture')
        self.stores = IntervalStoreSet.create_migration(str(self.root/'catalog.json'),
            workflow_id='1'*64, scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)

    def tearDown(self):
        self.candidate.close()
        self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temp.cleanup()

    def test_successor_exact_identities_shared_graph_metadata_only_and_targets(self):
        at = perf_counter()
        row, numeric, refs, legacy = successor_fixture(self.candidate, self.budget)
        elapsed = perf_counter()-at
        for kind, value in legacy.items():
            raw = canonical(value)
            self.assertEqual((refs[kind]['bytes'], refs[kind]['sha256']), (len(raw), sha256(raw).hexdigest()))
        references = {canonical(ref['compact']['segment']) for ref in refs.values()}
        self.assertEqual(len(references), 1)
        numeric_bytes = sum(a.nbytes for a in numeric.values())
        limits = self.candidate.limits
        self.assertLessEqual(numeric_bytes, limits.max_array_bytes*.02)
        # Complete head manifest includes actual numeric descriptors and their
        # chunk inventories, not only the human-readable metadata dictionary.
        with ArrayStore(self.root/'numeric-head.sqlite', limits, budget=self.budget) as head:
            head.put('7'*64, numeric, row, budget=self.budget)
            with head._read_scope(budget=self.budget):
                manifest_bytes = len(canonical(head._manifest('7'*64)))
        self.assertLessEqual(manifest_bytes, limits.max_manifest_bytes*.25)
        with patch.object(SegmentView, 'read', side_effect=AssertionError('publication loaded payload')), \
                patch.object(SegmentView, 'iter', side_effect=AssertionError('publication streamed payload')):
            P.verify_publication_references(self.candidate, row, budget=self.budget, source_producer=PRODUCER)
            with self.assertRaisesRegex(ContractError, 'producer differs'):
                P.verify_publication_references(self.candidate, row, budget=self.budget,
                                                source_producer=dict(PRODUCER, role='changed'))
        seal_at = perf_counter()
        reference = SegmentRef.from_wire(refs['state']['compact']['segment'])
        self.stores.promote(self.candidate.seal(reference), expected_catalog_digest=self.stores.catalog_digest)
        seal_seconds = perf_counter()-seal_at
        stats = self.candidate.local_statistics()
        retained = self.scope.stats()
        physical_bytes = sum(path.stat().st_size for path in self.root.rglob('*')
                             if path.is_file() and not path.name.startswith('numeric-head.sqlite'))
        print(json.dumps(dict(check='wp5-synthetic-successor', pack_seconds=elapsed,
            seal_and_promote_seconds=seal_seconds,
            numeric_head_bytes=numeric_bytes, complete_manifest_bytes=manifest_bytes,
            record_logical_bytes=sum(ref['bytes'] for ref in refs.values()),
            retained_bytes=retained.retained_bytes, peak_retained_bytes=retained.peak_retained_bytes,
            sealed_interval_and_catalog_physical_bytes=physical_bytes,
            numeric_head_physical_bytes=(self.root/'numeric-head.sqlite').stat().st_size,
            process_ram='not measured', store_statistics=stats,
            matched_legacy_time_ram_disk='not measured')), flush=True)

    def test_sealed_reopen_exact_children_and_shared_graph(self):
        _, _, refs, legacy = successor_fixture(self.candidate, self.budget, count=3)
        reference = SegmentRef.from_wire(refs['state']['compact']['segment'])
        self.stores.promote(self.candidate.seal(reference), expected_catalog_digest=self.stores.catalog_digest)
        with P.open_records(self.stores, refs, budget=self.budget) as opened:
            proposal = opened['exchange'].field('finite_proposal')
            nested = proposal.field('graph')
            self.assertEqual(nested.index, opened['graph'].index)
            self.assertIs(nested._view, opened['graph']._view)
            nested.close(); proposal.close()
            for kind, record in opened.items():
                parts = []
                with record.iter_json() as stream:
                    for block in stream:
                        with block:
                            parts.append(block.value)
                raw = b''.join(parts)
                self.assertEqual(raw, canonical(legacy[kind]))

    def test_reference_mutations_and_publication_callback_refuse_without_payload(self):
        row, _, refs, _ = successor_fixture(self.candidate, self.budget, count=3)
        for mutate in (lambda x: x['state'].__setitem__('sha256', 'a'*64),
                       lambda x: x['state'].__setitem__('bytes', True),
                       lambda x: x['state']['compact'].__setitem__('field', 'graph'),
                       lambda x: x['state']['compact'].__setitem__('schema', 'unknown'),
                       lambda x: x['state']['compact']['segment'].__setitem__('merkle_root', 'a'*64)):
            bad = deepcopy(refs); mutate(bad)
            with self.assertRaises((ContractError, ValueError)):
                P.verify_records(self.candidate, bad, budget=self.budget)
        called = []
        check = P.publication_check(lambda: called.append('legacy'), self.candidate, row, budget=self.budget)
        check()
        self.assertEqual(called, ['legacy'])
        row['exterior_advance']['record_blobs'].pop('heat')
        with self.assertRaisesRegex(ContractError, 'complete spatial'):
            check()

    def test_republication_is_exact_and_adds_no_chunks(self):
        values = fixture_records(3)
        first = P.publish_records(self.candidate, values, budget=self.budget, source_producer=PRODUCER)
        before = self.candidate.local_statistics()
        second = P.publish_records(self.candidate, values, budget=self.budget, source_producer=PRODUCER)
        after = self.candidate.local_statistics()
        self.assertEqual(first, second)
        self.assertEqual(before, after)

    def test_logical_child_proof_is_not_replaced_by_authenticated_index(self):
        refs = P.publish_records(self.candidate, {'state': {'cells': [1, 2]}},
                                 budget=self.budget, source_producer=PRODUCER)
        bad = deepcopy(refs)
        bad['state']['sha256'] = 'a'*64
        original = P._bundle_metadata
        def forged_index(segment, selected, source_producer=None):
            metadata = original(segment, refs)
            metadata['records']['state']['sha256'] = 'a'*64
            return metadata
        with patch.object(P, '_bundle_metadata', side_effect=forged_index):
            with self.assertRaisesRegex(ContractError, 'logical identity differs'):
                with P.open_records(self.candidate, bad, budget=self.budget):
                    self.fail('forged child accepted')

    def test_certification_restore_keeps_numeric_arrays_and_native_check(self):
        records = dict(solution={'solution_id': 'a'*64}, proposal={}, iteration={},
                       force={'schema': 'synthetic.force'}, bindings={})
        ref = P.publish_records(self.candidate, {'certification': records}, budget=self.budget,
                                source_producer=PRODUCER)['certification']
        header = {'record_blob': ref, 'solution_id': 'a'*64}
        arrays = {'certification-force:omega': np.arange(3, dtype='<f8')}
        received = []
        cls = SimpleNamespace(_certification_header=lambda value, bound: dict(header, record_blob=bound),
            _check_certification_records=lambda *args: received.append(args))
        with patch('atlas_tectonics.regional_execution.RegionalMechanicalSnapshot',
                   side_effect=lambda definition, fields: (definition, fields)):
            P.restore_certification(cls, header, arrays, self.budget, store=self.candidate,
                                    graph={}, interval={}, expected={}, source_audit={})
        self.assertEqual(received[0][0], records)
        self.assertIs(received[0][1][1]['omega'], arrays['certification-force:omega'])
        bad = dict(arrays, extra=np.zeros(1))
        with self.assertRaisesRegex(ContractError, 'complete compact certification'):
            P.restore_certification(cls, header, bad, self.budget, store=self.candidate,
                                    graph={}, interval={}, expected={}, source_audit={})
        received.clear()

    def test_differential_roundtrip_preserves_header_and_actual_network_arrays(self):
        values = {name: 'a'*64 for name in P.DIFFERENTIAL_NAMES}
        values.update(start_time_s=['0x0', '0x1'], end_time_s=['0x1', '0x1'])
        record = {'interval': values, 'endpoint_network': {'network_id': 'c'*64}}
        ref = P.publish_records(self.candidate, {'differential': record}, budget=self.budget,
                                source_producer=PRODUCER)['differential']
        header = dict(values, record_blob=ref)
        raw = canonical(record)
        self.assertEqual((ref['bytes'], ref['sha256']), (len(raw), sha256(raw).hexdigest()))
        fields = {'positions': np.arange(6, dtype='<f8').reshape(2, 3)}
        network = SimpleNamespace(arrays=lambda: fields)
        retained = SimpleNamespace(interval_id=values['interval_id'])
        with patch('atlas_tectonics.integration_sphere.restore_network', return_value=network) as restore_network, \
                patch('atlas_tectonics.integration_differential_geometry.DifferentialInterval.restore',
                      return_value=retained) as restore_interval:
            got = P.restore_differential(header, {'differential-network:positions': fields['positions']},
                                          self.budget, store=self.candidate)
        self.assertIs(got, retained)
        self.assertIs(restore_network.call_args.args[1]['positions'], fields['positions'])
        self.assertEqual(restore_interval.call_args.args[0], values)

    def test_spatial_state_cells_stay_views_and_exchange_reassembles_without_decode(self):
        import mesh_tables as M
        from record_views import RecordRef, LogicalExchange
        values = fixture_records(2)
        # WP3 separately tests mesh storage/validation; this fixture isolates the
        # WP5 state/exchange boundary with an explicitly stubbed mesh adapter.
        mesh = object.__new__(M.CompactMesh)
        saved = dict(values['state'], thermal_mesh=mesh)
        exchange = dict(values['exchange'], spatial_graph=values['graph'],
                        transport=values['transport'], joined_heat=values['heat'])
        mesh_ref = {'schema': 'atlas.compact-mesh-store.v3', 'geometry_id': '5'*64}
        with patch('spatial_workflow_patch.persist_mesh', return_value=mesh_ref):
            with P.records(None, saved, exchange, self.budget, store=self.candidate,
                           source_producer=PRODUCER) as (state_header, exchange_header, arrays):
                self.assertEqual(arrays, {})
        ref = SegmentRef.from_wire(state_header['record_blobs']['state']['compact']['segment'])
        mesh_ref['segment'] = ref.to_wire()
        self.stores.promote(self.candidate.seal(ref), expected_catalog_digest=self.stores.catalog_digest)
        with patch('spatial_workflow_patch.verify_reference'), \
                patch('compact_store.CompactMeshStoreV3.open', return_value=mesh):
            with P.restore_records(None, state_header, exchange_header, {}, self.budget,
                                   store=self.stores) as (state, restored):
                self.assertIsInstance(state['cells'], RecordRef)
                self.assertIsInstance(restored, LogicalExchange)
                self.assertIs(state['thermal_mesh'], mesh)
                self.assertEqual(restored.identity().sha256, sha256(canonical(exchange)).hexdigest())
                adopted_cells = state['cells'].borrow()
        with adopted_cells.at(1) as row, row.field('cell_id') as field, field.scalar(max_owned_bytes=16384) as cell_id:
            self.assertEqual(cell_id.value, values['state']['cells'][1]['cell_id'])
        adopted_cells.close()
        del state, restored

    def test_bounded_export_and_cancellation_refuse(self):
        refs = P.publish_records(self.candidate, {'state': {'cells': ['x'*1024]*20}},
                                 budget=self.budget, source_producer=PRODUCER)
        with patch.object(P, 'EXPORT_LOGICAL_BYTES', 1024):
            with self.assertRaisesRegex(ContractError, 'logical export bound'):
                with P.export_record(self.candidate, refs['state'], 'state', budget=self.budget):
                    self.fail('oversized export accepted')
        with self.assertRaisesRegex(ContractError, 'cancelled'):
            P.publish_records(self.candidate, {'state': {}}, budget=self.budget,
                              source_producer=PRODUCER, cancel=lambda: True)


class TransformTests(unittest.TestCase):
    def test_real_workflow_source_transform_and_legacy_routes(self):
        import workflow_transfer as W
        import spatial_workflow_patch as Y
        source = (HERE.parents[1]/'runtime-integration-r1/runtime-src/atlas_tectonics/integration_regional_workflow.py').read_text(encoding='utf8')
        prior = Y.transform(W.nonzero_cursor_source(source))
        transformed = P.transform(prior)
        compile(transformed, '<wp5-workflow>', 'exec')
        for legacy in ("raw = _json(records)\n            name = 'certification-record:final'",
                       "raw = _json(record)\n            ref = dict(array='differential-record:geometry'",
                       "raw = values.tobytes()", "name = 'spatial-record:'+kind"):
            self.assertIn(legacy, transformed)
        with self.assertRaisesRegex(ContractError, 'unapplied'):
            P.transform(transformed)
        with self.assertRaisesRegex(ContractError, 'missing or ambiguous'):
            P.transform(prior.replace('import json\n', 'import json\nimport json\n'))
        self.assertIn('_COMPACT_RECORDS.publication_check(check, self._store, row', transformed)
        # Step 8: the certification booking width accepts a live compact graph.
        self.assertNotIn('len(solution.graph._json)', transformed)
        self.assertIn('_COMPACT_RECORDS.holder_bytes(solution.graph)', transformed)

    def test_holder_bytes_matches_native_width_and_compact_canonical_bytes(self):
        from types import SimpleNamespace
        raw = b'{"a":[1,2,3],"b":"x"}'
        self.assertEqual(P.holder_bytes(SimpleNamespace(_json=raw)), len(raw))
        budget = WorkBudget(1 << 28)
        scope = create_retained_scope(budget, process_epoch='step8-holder-bytes')
        packed = RecordCodec().pack_record({'a': [1, 2, 3], 'b': 'x'}, record_schema='atlas.test.v1',
                                           scope=scope, check=lambda: None)
        self.assertEqual(P.holder_bytes(SimpleNamespace(_json=packed)), len(raw))
        packed.close()
        scope.close()


if __name__ == '__main__':
    unittest.main()
