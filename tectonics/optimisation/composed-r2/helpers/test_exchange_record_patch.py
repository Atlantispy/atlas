"""WP5 packaging controls: pinned native holder, no solve or real migration."""
import ast
from collections.abc import Mapping
from concurrent.futures import CancelledError
from copy import deepcopy
from dataclasses import dataclass, field
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
R = HERE.parent
I = R.parent/'runtime-integration-r1'/'runtime-src'
H = HERE.parents[3]/'heat-repair-20261007'
sys.path.insert(0, str(I))
sys.path.insert(0, str(R))

from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope
import exchange_record_patch as E
import record_tables as T
from record_views import CompactRecord, LogicalExchange


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def native_holder(source):
    """Execute the actual native class AST unchanged, including audit_arrays."""
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                and n.name == 'SpatialExteriorAdvance')
    env = dict(dataclass=dataclass, field=field, SpatialExteriorState=object,
        SpatialTransportResult=object, json=json,
        _hash=lambda value: sha256(canonical(value)).hexdigest(), _EXCHANGE_RECORD=E)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<native-holder>', 'exec'), env)
    return env['SpatialExteriorAdvance']


def fixture(rows=8, token=100):
    cells = [dict(cell_id=sha256(str(i).encode()).hexdigest(), label='\u00a3'+str(i),
                  exact=['-0x12', '0x15'], detail='t'*token, volume=1.25)
             for i in range(rows)]
    face = dict(from_cell=cells[0]['cell_id'], to_cell=cells[-1]['cell_id'], flux=['0x2', '0x3'])
    graph = dict(cells=cells, physical_faces=[face], faces=[face], transport_faces=[face])
    value = {name: sha256(name.encode()).hexdigest() for name in E.HEADER_FIELDS
             if name not in ('state_id', 'result_id')}
    value.update(schema='atlas.private.spatial-composed-advance.r1', spatial_graph=graph,
        spatial_graph_id=sha256(canonical(graph)).hexdigest(),
        finite_proposal=dict(graph=deepcopy(graph), inventory=cells),
        transport=dict(result_id='a'*64, rows=cells), joined_heat=dict(result_id='b'*64),
        joined_heat_plan=dict(schema='small-plan', rule='same'),
        dual_measure_audit=dict(result='exact'))
    return value


def stream(value):
    output = []
    with value.iter_json() as blocks:
        for block in blocks:
            with block:
                output.append(block.value)
    return b''.join(output)


class ExchangeRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner_source = (I/'atlas_tectonics'/'integration_spatial_owner.py').read_text(encoding='utf8')
        cls.original_holder = native_holder(cls.owner_source)
        cls.changed_source = E.holder_source(cls.owner_source)
        cls.holder = native_holder(cls.changed_source)

    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='wp5-exchange-test')
        self.state = SimpleNamespace(state_id='f'*64, _budget=self.budget)
        self.transport_array, self.heat_array = object(), object()
        self.transport = SimpleNamespace(arrays=lambda: {'amount': self.transport_array})
        self.heat = SimpleNamespace(array=lambda key: self.heat_array, array_names=('energy',))

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def build(self, value=None, check=lambda: None):
        return E.build_advance(self.holder, self.state, fixture() if value is None else value,
            self.transport, self.heat, scope=self.scope, check=check)

    def test_pinned_source_and_composition_order(self):
        import private_heat_indexed_runtime as indexed
        import spatial_indexed_patch as spatial
        import spatial_transfer
        raw = (H/'private_heat_joined_consumer_r6.py').read_text(encoding='utf8')
        self.assertEqual(sha256(raw.encode()).hexdigest(), E.JOINED_SHA)
        joined = indexed.joined_source(raw, expected_sha256=E.JOINED_SHA)
        self.assertEqual(sha256(joined.encode()).hexdigest(), E.INDEXED_JOINED_SHA)
        for source in (raw, joined):
            changed = E.producer_source(source)
            compile(changed, '<producer>', 'exec')
            # Only the imported helper and three packaging statements differ.
            self.assertEqual(changed.replace(
                'import exchange_record_patch as EXCHANGE_RECORD\n', '').replace(
                E._PRODUCER_NEW, E._PRODUCER_OLD), source)
            with self.assertRaises(ValueError):
                E.producer_source(changed)
        transformed = spatial.transform(spatial_transfer.spatial_owner_source(self.owner_source))
        self.assertEqual(sha256(transformed.encode()).hexdigest(), E.INDEXED_OWNER_SHA)
        compile(E.holder_source(transformed), '<indexed-holder>', 'exec')
        for source in (self.owner_source+'\n', self.changed_source):
            with self.assertRaises(ValueError):
                E.holder_source(source)
        with self.assertRaises(ValueError):
            E.producer_source(raw+'\n')

    def test_exact_native_identity_public_record_and_actual_handles(self):
        value = fixture()
        legacy = self.original_holder(self.state, canonical(value), self.transport, self.heat)
        compact = self.build(value)
        self.assertIs(compact.state, self.state)
        self.assertIs(compact._transport, self.transport)
        self.assertIs(compact._heat, self.heat)
        self.assertEqual(compact.audit_arrays(), legacy.audit_arrays())
        self.assertIs(compact.audit_arrays()['spatial-transport:amount'], self.transport_array)
        self.assertIs(compact.audit_arrays()['joined-heat:energy'], self.heat_array)
        self.assertEqual(compact.result_id, legacy.result_id)
        record = compact.record()
        self.assertIsInstance(record, LogicalExchange)
        self.assertNotIsInstance(record, Mapping)
        self.assertEqual(stream(record), canonical(legacy.record()))
        record.close()
        compact.close()

    def test_graph_finite_graph_and_face_rows_are_hash_consed(self):
        compact = self.build()
        body = compact._record.root()
        graph = body.field('spatial_graph')
        finite = body.field('finite_proposal')
        finite_graph = finite.field('graph')
        self.assertEqual(graph.index, finite_graph.index)
        faces, physical, transport = (graph.field(n) for n in ('faces', 'physical_faces', 'transport_faces'))
        self.assertEqual(faces.index, physical.index)
        self.assertEqual(faces.index, transport.index)
        for reference in (faces, physical, transport, finite_graph, finite, graph, body):
            reference.close()
        compact.close()

    def test_no_eager_body_json_export_and_result_hash_is_cached(self):
        real_dumps = json.dumps
        value = fixture()
        def reject_containers(value, *args, **kwargs):
            # Bounded codec metadata is allowed; a producer or exchange is not.
            if isinstance(value, dict) and value.get('schema') != T.SCHEMA:
                raise AssertionError('eager domain JSON')
            if isinstance(value, list):
                raise AssertionError('eager list JSON')
            return real_dumps(value, *args, **kwargs)
        with patch.object(json, 'dumps', side_effect=reject_containers):
            compact = self.build(value)
        with patch.object(LogicalExchange, 'composite_identity', side_effect=AssertionError('rehash')):
            with patch.object(CompactRecord, '_export', side_effect=AssertionError('eager export')):
                first = compact.result_id
                self.assertEqual(first, compact.result_id)
                logical = compact.record()
                logical.close()
        compact.close()

    def test_header_is_owned_bounded_and_rejects_body_fields(self):
        compact = self.build()
        before = self.scope.stats().retained_bytes
        with compact.header(fields=('result_id', 'spatial_graph_id')) as held:
            self.assertEqual(held.value, dict(result_id=compact.result_id,
                spatial_graph_id=fixture()['spatial_graph_id']))
            self.assertGreater(self.scope.stats().retained_bytes, before)
        self.assertEqual(self.scope.stats().retained_bytes, before)
        with self.assertRaises(ContractError):
            compact.header(fields=('spatial_graph',))
        compact.close()

    def test_explicit_scope_missing_closed_foreign_and_state_refusal(self):
        owner = SimpleNamespace(_budget=self.budget)
        with self.assertRaises(ContractError):
            E.required_scope(owner)
        owner._record_scope = self.scope
        self.assertIs(E.required_scope(owner), self.scope)
        other_budget = WorkBudget(1 << 20)
        owner._budget = other_budget
        with self.assertRaises(ContractError):
            E.required_scope(owner)
        foreign_state = SimpleNamespace(state_id='f'*64, _budget=other_budget)
        with self.assertRaises(ContractError):
            E.build_advance(self.holder, foreign_state, fixture(), self.transport, self.heat,
                            scope=self.scope, check=lambda: None)
        closed = create_retained_scope(other_budget, process_epoch='closed-scope')
        closed.close()
        owner._record_scope = closed
        with self.assertRaises(ContractError):
            E.required_scope(owner)
        self.assertEqual(other_budget.reserved_bytes, 0)

    def test_header_bound_and_scalar_contract_refuse_before_export(self):
        value = fixture()
        value['heat_projection_rule'] = 'x'*(1 << 20)
        compact = self.build(value)
        with self.assertRaises(ContractError):
            compact.header(fields=('heat_projection_rule',))
        gc.collect()
        compact.close()
        value['heat_projection_rule'] = {'large_child': [1, 2, 3]}
        compact = self.build(value)
        with patch.object(CompactRecord, '_export', side_effect=AssertionError('exported container')):
            with self.assertRaises(ContractError):
                compact.header(fields=('heat_projection_rule',))
        gc.collect()
        compact.close()

    def test_close_refuses_live_public_borrow_and_children_keep_backing(self):
        compact = self.build()
        record = compact.record()
        with self.assertRaises(RuntimeError):
            compact.close()
        self.assertEqual(record.kind, 'object')
        record.close()
        compact.close()
        with self.assertRaises(RuntimeError):
            _ = compact.result_id

    def test_cancel_before_first_admission(self):
        initial = self.budget.reserved_bytes
        def cancelled():
            raise CancelledError('before producer')
        with self.assertRaises(CancelledError):
            self.build(check=cancelled)
        self.assertEqual(self.budget.reserved_bytes, initial)

    def test_cancel_during_pack_keeps_traceback_funding_until_release(self):
        initial = self.budget.reserved_bytes
        calls, caught = 0, []
        def cancelled():
            nonlocal calls
            calls += 1
            if calls == 6:
                raise CancelledError('within producer')
        try:
            self.build(check=cancelled)
        except CancelledError as error:
            caught.append(error)
        self.assertEqual(len(caught), 1)
        self.assertGreater(self.budget.reserved_bytes, initial)
        caught.clear()
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, initial)

    def test_failed_native_constructor_keeps_compact_funding_until_release(self):
        initial, caught = self.budget.reserved_bytes, []
        def fail(state, packed, transport, heat):
            self.assertIsInstance(packed, CompactRecord)
            raise RuntimeError('native holder failure')
        try:
            E.build_advance(fail, self.state, fixture(), self.transport, self.heat,
                            scope=self.scope, check=lambda: None)
        except RuntimeError as error:
            caught.append(error)
        self.assertEqual(len(caught), 1)
        self.assertGreater(self.budget.reserved_bytes, initial)
        caught.clear()
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, initial)

    def test_cancel_after_native_holder_keeps_result_funded_until_release(self):
        initial, caught = self.budget.reserved_bytes, []
        made = False
        def constructor(*args):
            nonlocal made
            result = self.holder(*args)
            made = True
            return result
        def check():
            if made:
                raise CancelledError('after native holder')
        try:
            E.build_advance(constructor, self.state, fixture(), self.transport, self.heat,
                            scope=self.scope, check=check)
        except CancelledError as error:
            caught.append(error)
        self.assertEqual(len(caught), 1)
        self.assertGreater(self.budget.reserved_bytes, initial)
        caught.clear()
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, initial)

    def test_legacy_bytes_holder_compatibility(self):
        value = canonical(fixture())
        legacy = self.original_holder(self.state, value, self.transport, self.heat)
        changed = self.holder(self.state, value, self.transport, self.heat)
        self.assertEqual(changed.result_id, legacy.result_id)
        self.assertEqual(changed.record(), legacy.record())


def measure_packaging(mode):
    """One bounded child sample per mode; shared input, imports and resource cap.

    RSS/private are sampled physical process values, not logical reservations.
    No persistence happens at this producer seam, so there is no disk baseline.
    """
    import psutil
    import weakref
    from atlas_tectonics.integration_regional_inventory import _width
    value = fixture(rows=384, token=2048)
    raw_identity = sha256(canonical(value)).hexdigest()
    logical_bytes = len(canonical(value))
    source = (I/'atlas_tectonics'/'integration_spatial_owner.py').read_text(encoding='utf8')
    holder_type = native_holder(E.holder_source(source) if mode == 'compact' else source)
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='wp5-packaging-measurement')
    state = SimpleNamespace(state_id='f'*64, _budget=budget)
    process = psutil.Process()
    stop = threading.Event()
    before = process.memory_info()
    peaks = dict(rss=before.rss, private=getattr(before, 'private', before.rss))
    def sample():
        while not stop.wait(0.005):
            memory = process.memory_info()
            peaks['rss'] = max(peaks['rss'], memory.rss)
            peaks['private'] = max(peaks['private'], getattr(memory, 'private', memory.rss))
    sampler = threading.Thread(target=sample)
    sampler.start()
    start = time.perf_counter()
    if mode == 'compact':
        holder = E.build_advance(holder_type, state, value, None, None,
                                 scope=scope, check=lambda: None)
    elif mode == 'legacy':
        with budget.reserve(65536+3*_width(value), category='spatial-exchange-encoding'):
            holder = holder_type(state, canonical(value), None, None)
            lease = budget.reserve(8192+len(holder._record), category='spatial-owner-retained')
            lease.__enter__()
            weakref.finalize(holder, lease.__exit__, None, None, None)
    else:
        raise ValueError('expected legacy or compact mode')
    result_identity = holder.result_id
    elapsed = time.perf_counter()-start
    after = process.memory_info()
    stop.set()
    sampler.join()
    peaks['rss'] = max(peaks['rss'], after.rss)
    peaks['private'] = max(peaks['private'], getattr(after, 'private', after.rss))
    result = dict(mode=mode, rows=384, repeated_token_bytes=2048,
        body_sha256=raw_identity, logical_body_bytes=logical_bytes,
        result_id=result_identity, elapsed_seconds=elapsed,
        rss_before=before.rss, rss_after=after.rss, sampled_peak_rss=peaks['rss'],
        private_before=getattr(before, 'private', None),
        private_after=getattr(after, 'private', None), sampled_peak_private=peaks['private'],
        logical_retained_bytes=budget.reserved_bytes,
        logical_peak_bytes=budget.statistics()['peak_reserved_bytes'],
        disk='No producer persistence; no physical-store baseline measured',
        sampling_interval_seconds=0.005,
        scope='One fresh-process synthetic packaging sample; no solver or real IV2 claim')
    if mode == 'compact':
        holder.close()
    del holder
    gc.collect()
    scope.close()
    result['released_bytes'] = budget.reserved_bytes
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--measure':
        measure_packaging(sys.argv[2])
    else:
        unittest.main()
