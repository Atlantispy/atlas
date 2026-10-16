"""A2: WP6 streamed validation at census shape (H2, M1, M3, H3, M18).

Census IV1 (structure-census-r3, spatial-record:transport): 889 cells, 44 field
names, five rational groups (203,060 unique pairs, about 407k strings, about
6.36 MB canonical); dual_measure_audit prior/rebase maps of 889 entries each;
finite_proposal/stocks 44 x 889 pairs. Every value is unique (no shared lists).

The unchanged native validators run on the legacy dictionary and, through the
exact r2 source transforms, on compact inputs: a single packed record root, a
LogicalExchange over it, a sealed segment-store reopen, LogicalExchange
from_body and from_records compositions. Valid, finite-owner and composed
exchanges and targeted mutations must reach the legacy decision and message.

Fixture packing only: the Step 4 builder still books its fixed 256 MiB
allowance against about 18x the real token size (review H1, owned by the
builder repair), so single-record fixtures lift record_tables.MAX_BUILD_BYTES
in-process while packing and restore it before any validation. No validation
cap is changed. Scale 3.8x and 5x use from_records compositions of per-vector
records, which the builder packs within its unchanged allowance.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from fractions import Fraction
import gc
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import ast
from types import MethodType, SimpleNamespace
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_spatial_validation_patch as TV  # noqa: E402  (runtime path, fixture, exact bodies)
from test_spatial_validation_patch import O, F, D, W, digest, outcome  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot  # noqa: E402
from content_cache import create_retained_scope  # noqa: E402
import record_tables as T  # noqa: E402
from record_views import CompactRecord, LogicalExchange  # noqa: E402
import spatial_validation_patch as V  # noqa: E402

TMP = HERE.parents[4]/'_t'
SCALE = float(os.environ.get('A2_SCALE', '1'))
B = D.B_NAME
NAMES = ([B, 'enthalpy_j'] + ['component_mass_kg:%d' % i for i in range(38)] +
         ['tracer:accumulated_strain_ii', 'tracer:damage', 'tracer:radial_plastic_kappa', 'tracer:source_kappa'])
# Census IV1 group -> (pairs per field name at 1x, numerator hex digits, denominator hex digits)
GROUPS = {'exact_input_stocks': (889, 11, 1), 'exact_stocks': (889, 17, 9),
          'exact_projection_accounts': (889, 12, 1), 'binary_stock_projection_accounts': (889, 16, 9),
          'exact_face_transfers': (1059, 12, 7)}
COMPOSED = 'atlas.private.spatial-composed-advance.r1'
FINITE = 17


class Seq:
    def __init__(self):
        self.n = 0

    def pair(self, digits, den_digits):
        """Unique canonical rational pair: odd numerator, power-of-two denominator."""
        self.n += 1
        bits = 4*digits
        num = (1 << (bits-1)) | ((self.n*2654435761+12345) % (1 << (bits-1))) | 1
        den = 1 << (4*den_digits-1) if den_digits > 1 else 1
        return [hex(num), hex(den)]


def census_exchange(scale, budget, *, finite=False, composed=False):
    """Legacy dictionaries for one census-shaped IV1 (or scaled) exchange."""
    seq = Seq()
    owner, state, exchange, arrays, saved = TV.fixture(budget)
    cells = int(round(889*scale))
    cell_ids = ['finite-stock:%d' % i if i < FINITE else format(i*7919+1, '064x') for i in range(cells)]
    volumes = [seq.pair(11, 1) for _ in range(cells)]
    graph = dict(exchange['spatial_graph'], cells=[dict(cell_id=c, kind='exterior', index=i,
        start_volume_m3=v, end_volume_m3=v) for i, (c, v) in enumerate(zip(cell_ids, volumes, strict=True))])
    transport = dict(geometry_id=digest(graph), state_id='p'*64, source_stage_id='q'*64, cell_ids=cell_ids,
                     nonnegative_fields=[B])
    for group, (count, digits, den) in GROUPS.items():
        count = cells if count == 889 else int(round(count*scale))
        transport[group] = {name: [seq.pair(digits, den) for _ in range(count)] for name in NAMES}
    transport['exact_input_stocks'][B] = deepcopy(volumes)
    transport['exact_stocks'][B] = deepcopy(volumes)
    transport['exact_projection_accounts'][B] = [['0x0', '0x1'] for _ in range(cells)]
    transport['field_errors'] = {name: dict(max_abs=seq.pair(8, 1), count=cells) for name in NAMES}
    policy = owner._measure_policy
    prior = {c: O._q(v) for c, v in zip(cell_ids, volumes, strict=True)}
    ta = {'stock': np.arange(1., 3.)}
    transport['result_id'] = RegionalMechanicalSnapshot(transport, ta).result_id
    audit = D.transport_audit(graph, transport, prior, policy, budget=budget)
    exchange.update(spatial_graph=graph, spatial_graph_id=digest(graph), transport=transport,
                    global_transport_id=transport['result_id'], dual_measure_audit=audit)
    exchange['joined_heat']['state_id'] = transport['result_id']
    exchange['joined_heat_id'] = RegionalMechanicalSnapshot(exchange['joined_heat'], {'energy': np.array([3., 4.])}).result_id
    arrays = {'spatial-transport:stock': ta['stock'], 'joined-heat:energy': np.array([3., 4.])}
    saved['cells'] = [dict(cell_id=cell_ids[FINITE], exact={B: volumes[FINITE]})]
    fake = None
    if finite:
        fake = SimpleNamespace(owner_id='f'*64, _budget=budget, _verify=lambda: None, _positive=(B,),
                               _names=tuple(NAMES), restore=lambda value: None, _check_fields=lambda value: None)
        parent = dict(state_id='f'*64, intervals=0,
            stocks=[dict(stock_id=str(k), volume_m3=volumes[k], exact={n: seq.pair(9, 1) for n in NAMES})
                    for k in range(FINITE)],
            projection_accounts={str(k): {n: ['0x0', '0x1'] for n in NAMES} for k in range(FINITE)})
        proposal = dict(owner_id=fake.owner_id, graph=graph, parent=parent, transport_parent_id='p'*64,
                        source_stage_id='q'*64, stocks=deepcopy(transport['exact_input_stocks']))
        proposal['proposal_id'] = digest(proposal)
        expected = F.PreparedFiniteStocks._finished_record(fake, proposal, transport)
        saved['finite_stock_state'] = dict(state_id=digest(expected), **expected)
        exchange['finite_proposal'] = proposal
    if composed:
        exchange['schema'] = COMPOSED
    seal(exchange, state)
    return owner, state, exchange, arrays, saved, fake


def seal(exchange, state):
    exchange.pop('result_id', None)
    exchange.pop('state_id', None)
    exchange['result_id'] = digest(dict(state_id=state.state_id, exchange=exchange))
    exchange['state_id'] = state.state_id


class Routes:
    """Legacy and exact-transformed validators plus their synthetic boundaries."""
    def __init__(self):
        originals = {name: Path(module.__file__).read_text(encoding='utf-8') for name, module in
                     [('owner', O), ('reservoir', F), ('measures', D)]}
        self.measures = TV.body_functions(V.measures_source(originals['measures']), vars(D),
            ['_dual_audit_capacity', '_transport_audit', 'transport_audit'])
        self.owner = TV.body_functions(V.owner_source(originals['owner']),
            dict(vars(O), transport_audit=self.measures.transport_audit), ['_validate_heat_plan', 'validate_exchange'])
        self.finite = TV.body_functions(V.reservoir_source(originals['reservoir']), vars(F),
                                        ['_finished_record', 'validate_saved'])
        source = (TV.HISTORICAL/'private_heat_joined_consumer_r6.py').read_text(encoding='utf-8')
        namespace = dict(_verify=lambda: None, sha256=sha256, _json=O._json,
                         validate_saved=lambda reference, checkpoint, *, expected_result_id, arrays, budget, cancel:
                         expected_result_id)
        self.joined = {False: TV.body_functions(source, namespace, ['validate_saved_exchange']),
                       True: TV.body_functions(V.joined_source(source), namespace, ['validate_saved_exchange'])}

    def run(self, compact, owner, state, exchange, arrays, fake):
        owner._validate_heat_plan = MethodType(
            self.owner._validate_heat_plan if compact else O.PreparedSpatialOwner._validate_heat_plan, owner)
        if fake is not None:
            body = self.finite if compact else F.PreparedFiniteStocks
            fake._finished_record = MethodType(body._finished_record, fake)
            fake.validate_saved = MethodType(body.validate_saved, fake)
        owner._finite = fake
        sys.modules['private_heat_joined_consumer_r6'] = SimpleNamespace(
            validate_saved_exchange=self.joined[compact].validate_saved_exchange)
        checkpoint = SimpleNamespace(value=SimpleNamespace(_call=SimpleNamespace(_origin_objects=(owner,))))
        validate = self.owner.validate_exchange if compact else O.PreparedSpatialOwner.validate_exchange
        try:
            return outcome(lambda: validate(owner, state, exchange, audit_arrays=arrays,
                                            composed_checkpoint=checkpoint))
        finally:
            sys.modules.pop('private_heat_joined_consumer_r6', None)


@contextmanager
def lifted_builder():
    """Fixture packing only (review H1 is the builder repair's item)."""
    saved = T.MAX_BUILD_BYTES
    T.MAX_BUILD_BYTES = 4 << 30
    try:
        yield
    finally:
        T.MAX_BUILD_BYTES = saved


class Pieces:
    """Per-vector records composed with LogicalExchange.from_records (same scope)."""
    SPLIT = {(): ('transport', 'dual_measure_audit', 'spatial_graph', 'finite_proposal'),
             ('transport',): tuple(GROUPS), ('finite_proposal',): ('stocks', 'graph')}

    def __init__(self, scope):
        self.scope, self.cache, self.held = scope, {}, []

    def leaf(self, value):
        key = sha256(T.canonical(value)).hexdigest()
        if key not in self.cache:
            record = T.RecordCodec().pack_record(value, record_schema='a2.piece.v1', scope=self.scope,
                                                 check=lambda: None)
            self.cache[key] = (record, record.root())
        return self.cache[key][1]

    def compose(self, value, path=()):
        if type(value) is not dict:
            return self.leaf(value)
        split = self.SPLIT.get(path, ())
        if path[-1:] in (('stocks',),) or (len(path) == 2 and path[0] == 'transport'):
            split = tuple(value)  # every field vector is its own record
        children = {k: self.compose(v, path+(k,)) for k, v in value.items() if k in split}
        if not children:
            return self.leaf(value)
        base = self.leaf({k: v for k, v in value.items() if k not in children})
        ref = LogicalExchange.from_records(base, **children)
        self.held.append(ref)
        return ref

    def close(self):
        gc.collect()
        for ref in reversed(self.held):
            ref.close()
        for record, root in self.cache.values():
            root.close()
            record.close()
        self.held, self.cache = [], {}


class _Forced:
    """Re-run Codex's twelve-mutation suites with every container streamed."""
    keyed = 0

    def setUp(self):
        self._saved = (V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES, V.KEYED_OBJECT_KEYS)
        V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES, V.KEYED_OBJECT_KEYS = -1, -1, self.keyed

    def tearDown(self):
        V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES, V.KEYED_OBJECT_KEYS = self._saved

    # r1 whole-export semantics, or graph-only routes, are covered by the base module.
    test_source_anchors_compile_and_refuse_drift_or_double_application = None
    test_row_memory_is_bounded_at_three_point_eight_scale_no_graph_export = None
    test_failed_traceback_and_retained_row_keep_their_decodes_paid = None
    test_oversized_small_field_and_transport_refuse_before_decode = None


class ForcedStreamEntryRoutes(_Forced, TV.SpatialValidationTests):
    keyed = 0


class ForcedStreamKeyedRoutes(_Forced, TV.SpatialValidationTests):
    keyed = 1 << 20


class CensusShapedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = Routes()

    def compare(self, label, legacy_input, compact_inputs, budget):
        owner, state, exchange, arrays, saved, fake = legacy_input
        expected = self.routes.run(False, owner, state, exchange, arrays, fake)
        for kind, value in compact_inputs:
            got = self.routes.run(True, owner, state, value, arrays, fake)
            self.assertEqual(got, expected, (label, kind))
            got = None
            gc.collect()
        print('A2 parity', label, expected[0], expected[1] if len(expected) > 1 else '', flush=True)
        return expected

    def single_record(self, kind, *, finite, scale=None):
        """One packed census record: its root, a LogicalExchange, or a sealed segment-store reopen."""
        from interval_store_set import IntervalStoreSet
        from segment_store import SegmentBackend
        scale = SCALE if scale is None else scale
        budget = WorkBudget(8 << 30)
        scope = create_retained_scope(budget, process_epoch='a2-census-single')
        legacy = census_exchange(scale, budget, finite=finite)
        exchange = legacy[2]
        self.assertGreater(len(T.canonical(exchange['transport'])), 6_000_000*scale)
        with lifted_builder():
            record = T.RecordCodec().pack_record(exchange, record_schema='a2.exchange.v1', scope=scope,
                                                 check=lambda: None)
        TMP.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='a2-census-', dir=str(TMP)) as directory:
            held_open = []
            if kind == 'sealed-store':
                stores = IntervalStoreSet.create_migration(str(Path(directory)/'catalog.json'), workflow_id='1'*64, scope=scope)
                candidate = stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)
                with record.metadata_bytes() as held:
                    reference = SegmentBackend().publish(candidate, record_schema='a2.exchange.v1',
                        identity=record.identity(), metadata=held.value, arrays=record.array_sources,
                        producer='2'*64, representation_profile=T.SCHEMA, scope=scope)
                segment = SegmentBackend().open(candidate, reference, scope=scope)
                sealed = CompactRecord.from_segment(segment)
                ref = sealed.root()
                held_open = [sealed, segment, candidate, stores]
            elif kind == 'LogicalExchange':
                root = record.root()
                ref = LogicalExchange(record, root.index)
                root.close()
            else:
                ref = record.root()
            label = 'iv1-%s-%s-valid' % (kind, 'finite' if finite else 'plain')
            self.assertEqual(self.compare(label, legacy, [(kind, ref)], budget), ('accepted', None))
            ref.close()
            gc.collect()
            for item in held_open:
                item.close()
        record.close()
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_iv1_single_record_root_finite(self):
        self.single_record('root', finite=True)

    def test_iv1_single_record_logical_exchange_plain(self):
        self.single_record('LogicalExchange', finite=False)

    def test_sealed_store_reopen_streamed_parity(self):
        """Sealed segment-store reopen of Codex's WP6 fixture with every container streamed.

        At census width the segment reopen itself (segment_store/record_views,
        before any validation) did not finish within 240 s, even at 0.1x;
        that is recorded in the receipt. The twelve mutations run here.
        """
        from interval_store_set import IntervalStoreSet
        from segment_store import SegmentBackend
        saved = (V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES, V.KEYED_OBJECT_KEYS)
        V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES, V.KEYED_OBJECT_KEYS = -1, -1, 0
        budget = WorkBudget(256 << 20)
        scope = create_retained_scope(budget, process_epoch='a2-sealed')
        owner, state, initial, arrays, _ = TV.fixture(budget)
        routes = Routes()
        TMP.mkdir(exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix='a2-sealed-', dir=str(TMP)) as directory:
                stores = IntervalStoreSet.create_migration(str(Path(directory)/'catalog.json'), workflow_id='1'*64, scope=scope)
                candidate = stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)
                for name, exchange in TV.variants(initial):
                    record = T.RecordCodec().pack_record(exchange, record_schema='a2.sealed.v1', scope=scope,
                                                         check=lambda: None)
                    with record.metadata_bytes() as held:
                        reference = SegmentBackend().publish(candidate, record_schema='a2.sealed.v1',
                            identity=record.identity(), metadata=held.value, arrays=record.array_sources,
                            producer='2'*64, representation_profile=T.SCHEMA, scope=scope)
                    segment = SegmentBackend().open(candidate, reference, scope=scope)
                    sealed = CompactRecord.from_segment(segment)
                    ref = sealed.root()
                    case = (owner, state, exchange, arrays, None, None)
                    expected = routes.run(False, *case[:4], None)
                    self.assertEqual(routes.run(True, owner, state, ref, arrays, None), expected, name)
                    if name == 'valid':
                        self.assertEqual(expected, ('accepted', None))
                    ref.close(); gc.collect()
                    sealed.close(); segment.close(); record.close()
                gc.collect()
                candidate.close(); stores.close()
        finally:
            V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES, V.KEYED_OBJECT_KEYS = saved
            gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def composed_case(self, scale, *, finite, composed, mutations, valid=True):
        budget = WorkBudget(8 << 30)
        scope = create_retained_scope(budget, process_epoch='a2-census-composed')
        pieces = Pieces(scope)
        legacy = census_exchange(scale, budget, finite=finite, composed=composed)
        owner, state, exchange, arrays, saved, fake = legacy
        case = value = None
        try:
            for name, mutate in (('valid', None),)*valid+tuple(mutations):
                value = exchange
                if mutate is not None:
                    value = deepcopy(exchange)
                    mutate(value)
                    seal(value, state)
                case = (owner, state, value, arrays, saved, fake)
                body = pieces.compose({k: v for k, v in value.items() if k not in ('state_id', 'result_id')})
                full = pieces.compose(value)
                overlay = LogicalExchange.from_body(body, state_id=value['state_id'], result_id=value['result_id'])
                pieces.held.append(overlay)
                label = 'x%s-%s%s-%s' % (scale, 'finite' if finite else 'plain', '-composed' if composed else '', name)
                result = self.compare(label, case, [('from_records', full), ('from_body', overlay)], budget)
                if name == 'valid':
                    self.assertEqual(result, ('accepted', None), label)
                else:
                    self.assertEqual(result[0], 'refused', label)
        finally:
            legacy = case = value = None
            pieces.close()
            gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    MUTATIONS = (
        ('transport-stock', lambda e: e['transport']['exact_stocks'][B].__setitem__(5, ['0x3', '0x1'])),
        ('transport-face-vector', lambda e: e['transport']['exact_face_transfers'][NAMES[7]].__setitem__(3, ['0x5', '0x1'])),
        ('dual-prior', lambda e: e['dual_measure_audit']['prior_geometry_m3'].__setitem__(
            sorted(e['dual_measure_audit']['prior_geometry_m3'])[40], ['0x7', '0x1'])),
        ('dual-rebase', lambda e: e['dual_measure_audit']['geometric_rebase_m3'].__setitem__(
            sorted(e['dual_measure_audit']['geometric_rebase_m3'])[41], ['0x1', '0x1'])),
        ('result-id', lambda e: e.update(transport=dict(e['transport'], result_id='f'*64))),
    )

    def test_iv1_composed_plain_valid(self):
        self.composed_case(SCALE, finite=False, composed=False, mutations=())

    def test_iv1_composed_plain_transport_mutations(self):
        self.composed_case(SCALE, finite=False, composed=False, mutations=self.MUTATIONS[:2], valid=False)

    def test_iv1_composed_plain_audit_mutations(self):
        self.composed_case(SCALE, finite=False, composed=False, mutations=self.MUTATIONS[2:4], valid=False)

    def test_iv1_composed_plain_result_id_mutation(self):
        self.composed_case(SCALE, finite=False, composed=False, mutations=self.MUTATIONS[4:], valid=False)

    def test_iv1_composed_finite_valid(self):
        self.composed_case(SCALE, finite=True, composed=False, mutations=())

    def test_iv1_composed_finite_stock_mutation(self):
        def stocks(e):
            e['finite_proposal']['stocks'][NAMES[3]][2] = ['0x9', '0x1']
            proposal = e['finite_proposal']
            proposal.pop('proposal_id')
            proposal['proposal_id'] = digest(proposal)
        self.composed_case(SCALE, finite=True, composed=False, mutations=(('finite-stocks', stocks),), valid=False)

    def test_iv1_composed_schema_exchange(self):
        self.composed_case(SCALE, finite=False, composed=True, mutations=(self.MUTATIONS[0],))

    def test_scaled_audit_and_stocks_x1_record(self):
        self.scaled_audit_and_stocks(1.0, 'record')

    def test_scaled_audit_and_stocks_x1_composed(self):
        self.scaled_audit_and_stocks(1.0, 'composed')

    def test_scaled_audit_and_stocks_x3_8_record(self):
        self.scaled_audit_and_stocks(3.8, 'record')

    def test_scaled_audit_and_stocks_x3_8_composed(self):
        self.scaled_audit_and_stocks(3.8, 'composed')

    def test_scaled_audit_and_stocks_x5_record(self):
        self.scaled_audit_and_stocks(5.0, 'record')

    def test_scaled_audit_and_stocks_x5_composed(self):
        self.scaled_audit_and_stocks(5.0, 'composed')

    def scaled_audit_and_stocks(self, scale, only):
        """M3/H2 at 1x, 3.8x and 5x: the audit and stocks compare and stream within caps."""
        for scale in (scale,):
            budget = WorkBudget(8 << 30)
            scope = create_retained_scope(budget, process_epoch='a2-scaled')
            pieces = Pieces(scope)
            seq = Seq()
            cells = int(round(889*scale))
            keys = [format(i*7919+1, '064x') for i in range(cells)]
            audit = dict(schema='atlas.dual-measure-transport-audit.v1', geometry_id='g'*64, transport_id='t'*64,
                prior_geometry_m3={k: seq.pair(11, 1) for k in keys},
                geometric_rebase_m3={k: seq.pair(11, 1) for k in keys},
                prior_l1_m3=seq.pair(14, 1), rebase_l1_m3=seq.pair(14, 1), input_l1_m3=seq.pair(14, 1),
                end_l1_m3=seq.pair(14, 1), numerical_l1_m3=seq.pair(14, 1), convention='G and B')
            stocks = {n: [seq.pair(11, 1) for _ in range(cells)] for n in NAMES}
            try:
                for kind in (only,):
                    if kind == 'record':
                        with lifted_builder():
                            ref = pieces.leaf(dict(dual_measure_audit=audit, stocks=stocks))
                    else:
                        ref = pieces.compose(dict(dual_measure_audit=audit, stocks=stocks), ('finite_proposal',))
                    gc.collect()
                    base = budget._peak = budget.reserved_bytes  # peak of the streamed reads only
                    for keyed in (V.KEYED_OBJECT_KEYS,):
                        V.KEYED_OBJECT_KEYS, saved = keyed, V.KEYED_OBJECT_KEYS
                        try:
                            with V.access(ref) as view:
                                lazy = view['dual_measure_audit']
                                self.assertIsInstance(lazy, V._Lazy)
                                self.assertFalse(lazy != audit)
                                prior = {k: O._q(v) for k, v in lazy['prior_geometry_m3'].items()}
                                self.assertEqual(prior, {k: O._q(v) for k, v in audit['prior_geometry_m3'].items()})
                                changed = deepcopy(audit)
                                changed['geometric_rebase_m3'][keys[-1]] = ['0x1', '0x1']
                                self.assertTrue(lazy != changed)
                                held = view['stocks']
                                self.assertFalse(held != stocks)
                                self.assertTrue(held == stocks)
                                other = dict(stocks, **{NAMES[0]: stocks[NAMES[0]][:-1]+[['0x1', '0x1']]})
                                self.assertTrue(held != other)
                                self.assertEqual(len(held[NAMES[5]]), cells)
                                self.assertEqual(held[NAMES[5]][cells-1], stocks[NAMES[5]][-1])
                                del lazy, held, prior
                        finally:
                            V.KEYED_OBJECT_KEYS = saved
                    print('A2 scaled', scale, kind, 'audit bytes', len(T.canonical(audit)),
                          'stocks bytes', len(T.canonical(stocks)), 'read peak reserved',
                          budget.peak_reserved_bytes-base, flush=True)
            finally:
                pieces.close()
                gc.collect(); scope.close()
            self.assertEqual(budget.reserved_bytes, 0)


class RefreshDispatchTests(unittest.TestCase):
    """H3: _refresh's composed-schema dispatch on every compact exchange form."""
    def test_dispatch_equals_legacy_for_all_input_types(self):
        source = V.workflow_source(Path(W.__file__).read_text(encoding='utf-8'))
        nodes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.If) and
                 'spatial-composed-advance' in ast.get_source_segment(source, n.test)]
        self.assertEqual(len(nodes), 1)
        test = compile(ast.Expression(nodes[0].test), '<refresh-dispatch>', 'eval')
        original = compile("exchange.get('schema') == 'atlas.private.spatial-composed-advance.r1'", '<legacy>', 'eval')
        budget = WorkBudget(128 << 20)
        owner, state, initial, arrays, saved = TV.fixture(budget)
        for schema in (COMPOSED, 'atlas.spatial-exterior-advance.v1'):
            exchange = dict(initial, schema=schema)
            expected = eval(original, dict(exchange=exchange))
            self.assertEqual(expected, schema == COMPOSED)
            for kind in ('legacy', 'root', 'LogicalExchange', 'from_body', 'from_records'):
                with ExitStack() as stack:
                    if kind == 'legacy':
                        value = exchange
                    elif kind == 'from_records':
                        own = WorkBudget(128 << 20)
                        scope = create_retained_scope(own, process_epoch='a2-dispatch')
                        pieces = Pieces(scope)
                        stack.callback(lambda: (pieces.close(), gc.collect(), scope.close()))
                        value = pieces.compose(exchange)
                    else:
                        mode = {'root': False, 'LogicalExchange': True, 'from_body': 'overlay'}[kind]
                        value = stack.enter_context(TV.compact(exchange, budget, exchange=mode))
                    self.assertEqual(eval(test, dict(exchange=value, _SV=V)), expected, (schema, kind))
                    if kind != 'legacy':
                        # The unfixed expression is always False for compact forms.
                        self.assertFalse(eval(original, dict(exchange=value)), kind)
                    value = None
            gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


class StreamExactnessTests(unittest.TestCase):
    """Streamed entries, equality and snapshot identity equal native decoding."""
    def adversarial(self):
        values = ['', 'x', '"]},[{:', '\\', 'é', '\U0001f600', '\ud800', 0, -1, 2**200, -0.0, 0.0, 1.0, 1,
                  5e-324, 1.7976931348623157e308, 1e16, True, False, None, [], {}, [[]], {'a': {}}, ['0x1', '0x2']]
        obj = {}
        for i in range(3000):  # wider than one 64 KiB stream chunk
            key = ('k%05d' % i)+('é' if i % 7 == 0 else '')+('"' if i % 11 == 0 else '')
            obj[key] = values[i % len(values)] if i % 5 else ['x'*(i % 97), {'n': i, 'q': '}]'}]
        return obj

    def test_entries_equality_and_snapshot_identity_match_native(self):
        budget = WorkBudget(256 << 20)
        scope = create_retained_scope(budget, process_epoch='a2-exactness')
        pieces = Pieces(scope)
        obj = self.adversarial()
        transport = dict(cell_ids=['c%d' % i for i in range(700)], blob=obj, nonnegative_fields=[B],
                         exact_stocks={n: [['0x%x' % (i+1), '0x1'] for i in range(700)] for n in NAMES[:5]},
                         result_id='r'*64)
        arrays = {'stock': np.array([1., -0.0, 5e-324])}
        expected = RegionalMechanicalSnapshot({k: v for k, v in transport.items() if k != 'result_id'}, arrays).result_id
        saved = (V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES, V.KEYED_OBJECT_KEYS)
        try:
            for keyed in (0, 1 << 20):
                V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES, V.KEYED_OBJECT_KEYS = -1, -1, keyed
                for kind in ('record', 'composed'):
                    ref = (pieces.leaf(dict(transport=transport)) if kind == 'record'
                           else pieces.compose(dict(transport=transport)))
                    with V.access(ref) as view:
                        lazy = view['transport']
                        self.assertEqual(V.snapshot(lazy, arrays, RegionalMechanicalSnapshot).result_id, expected)
                        blob = lazy['blob']
                        self.assertEqual(list(blob.keys()), list(obj))
                        got = list(blob.items())
                        self.assertEqual(len(got), len(obj))
                        for (k, v), (k2, v2) in zip(got, obj.items(), strict=True):
                            self.assertEqual(k, k2)
                            self.assertTrue(V._equal(v, v2), k)
                        del got
                        self.assertTrue(lazy == transport)
                        self.assertFalse(lazy != transport)
                        changed = deepcopy(transport)
                        changed['blob'][list(obj)[1234]] = 'other'
                        self.assertTrue(lazy != changed)
                        self.assertEqual(len(lazy['exact_stocks'][NAMES[1]]), 700)
                        self.assertEqual(lazy['exact_stocks'][NAMES[1]][-1], ['0x2bc', '0x1'])
                        with self.assertRaises(IndexError):
                            lazy['exact_stocks'][NAMES[1]][700]
                        del lazy, blob
        finally:
            V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES, V.KEYED_OBJECT_KEYS = saved
            pieces.close()
            gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_held_refusal_keeps_streamed_exports_funded(self):
        budget = WorkBudget(128 << 20)
        scope = create_retained_scope(budget, process_epoch='a2-held')
        record = T.RecordCodec().pack_record({'transport': {'value': 'x'*256, 'v': [['0x1', '0x1']]*9}},
                                             record_schema='a2.held', scope=scope, check=lambda: None)
        ref = record.root()
        baseline = budget.reserved_bytes
        saved = (V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES)
        V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES = -1, -1
        error = None
        try:
            def fail():
                with V.access(ref) as value:
                    lazy = value['transport']
                    self.assertIsInstance(lazy, V._Lazy)
                    self.assertEqual(lazy['value'], 'x'*256)
                    raise ValueError('held validation refusal')
            try:
                fail()
            except ValueError as exc:
                error = exc
            gc.collect()
            self.assertGreater(budget.reserved_bytes, baseline)
            with self.assertRaises(RuntimeError):
                ref.close()
            error.__traceback__ = None
            error = None
            gc.collect()
            self.assertEqual(budget.reserved_bytes, baseline)
        finally:
            V.LAZY_MIN_BYTES, V.VECTOR_MIN_BYTES = saved
        ref.close(); record.close(); gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


class EstimateTests(unittest.TestCase):
    def test_entry_decode_estimate_covers_real_and_is_close_on_census_entries(self):
        import tracemalloc
        seq = Seq()
        cases = {
            'census-prior-entry': T.canonical({format(7, '064x'): seq.pair(11, 1)})[1:-1],
            'census-vector-entry': T.canonical({'enthalpy_j': [seq.pair(17, 9) for _ in range(889)]})[1:-1],
            'empty-lists': T.canonical({'k': [[]]*4000})[1:-1],
            'empty-objects': T.canonical({'k': [{}]*4000})[1:-1],
            'small-ints': T.canonical({'k': list(range(300, 6300))})[1:-1],
            'floats': T.canonical({'k': [1.5]*4000})[1:-1],
            'unicode': T.canonical({'k': ['\u00e9\U0001f600']*3000})[1:-1],
            'nested': T.canonical({'k': [[{'a': [1, {'b': 'x'}]}]]*1500})[1:-1],
        }
        for label, raw in cases.items():
            text = raw.decode('ascii')
            key_end = V._STRING.match(text, 0).end()
            gc.collect()
            tracemalloc.start()
            decoded = (json.loads(text[:key_end]), json.loads(text[key_end+1:]))
            real = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            del decoded
            booked = V._decoded_estimate(raw)
            self.assertLessEqual(real, booked, label)
            if label.startswith('census'):
                self.assertLessEqual(booked, 1.3*real+4096, label)
            print('A2 entry estimate', label, 'real', real, 'booked', booked, flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
