"""Step 8 capacity overlaps: the five that the first capacity summary omitted.

capacity-summary.json (15 October) listed overlaps that the four-block capacity
workload did not hold "even if later blocks fit". This harness runs that
workload unchanged (measure_live_capacity: same census, guardian, guards,
start-gate setting and source closure) and, at its full-overlap point -- every
graph, mesh, record-family and heat block retained and the numeric blocks
committed, before the root publication and the seal -- adds each omitted
overlap, measures it at its own peak and keeps what it produced until the seal:

  successor  8,064 genuinely distinct successor supports, issued one at a time
             through the compact partition producer (SupportBatch: one
             incremental builder), beside the 2,016-support parent. Replica 0
             is the authentic IV1 support; replicas 1-3 scale every exact
             rational numerator by a replica factor and rename the component
             cell IDs, so no replica shares content with another (a capacity
             input, not geometry).
  solver     the authentic IV1 transport solve, replayed from the saved finite
             proposal in the authentic exchange record through the Step 8 live
             transport (compact proposal; graph read through bounded access;
             actual PreparedSpatialTransport matrix, GMRES and exact rational
             workspaces). Exact only if its result ID equals the authentic
             transport record's.
  state      the authentic IV1 state issued by the composed state issue: cells
             streamed through the Step 8 cell sink, numeric projection arrays
             built from the packed cells and frozen into the immutable
             snapshot, its logical identity streamed over the compact mesh.
             Exact only if its state ID equals the stored state_id.
  carried    the next interval's carried parent cells over that state's
             compact cells, exactly as the live owner's _carried_start_cells
             holds them (every row decoded, one dict, until the frame ends);
             a refusal is recorded as the finding, not raised.
  restore    the four saved heat ledgers reopened through the heat store's
             restore route (one mutable field buffer beside its immutable copy
             and the completed fields), all held.
  producers  the certification and geometry records issued again (compact
             pack, as the compact route issues them) inside the same ExitStack
             that holds every owner above, as the workflow's does.

Each overlap records its elapsed time; process RSS, private bytes and OS peak,
tracked reservation and its peak, retained-scope bytes and output disk before
and after; the maxima a 50 ms sampler saw while it ran; the peak of every
record builder it ran; and its outputs' identities. What an overlap does not
represent is stated in its row.

--standalone runs only the named overlaps on a minimal context (the same
budget, scope, read-only original and candidate store; state builds one
authentic mesh block first, restore saves one heat ledger first), to validate
them before the long combined run. NOT a real IV2 run in either mode.
"""
import argparse
import json
import math
import sys
import threading
import time
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from types import ModuleType, SimpleNamespace

HERE = Path(__file__).resolve().parent
R = HERE.parent
I = R.parent/'runtime-integration-r1/runtime-src'
sys.path[:0] = [str(HERE), str(R), str(I)]
import measure_live_capacity as CAP

NAMES = ('successor', 'successor2', 'solver', 'state', 'carried', 'restore', 'producers')
# Interval two's continuation inputs (the authentic IV1 partition it prepares
# from), saved by the 13 Oct interval-two attempt; read-only.
CAPTURE = (R.parents[2]/'heat-repair-20261007'/'heat-original-continued-20261013-r4.artifacts'/
           'continuation-trace-inputs-02.json.gz')
CAPTURE_SHA256 = 'e761ff8c0a030299d8bc1f666d050418cdfa8c68e670f0a26487e8551f252add'
# Standalone-only forecast probe (not an overlap): one IV2-shaped graph record
# (four distinct-content replicas of every large authentic collection) packed
# in the unchanged 256 MiB builder, for its distance to that guard.
PROBES = ('graph4',)
# Replica factors for exact rational numerators; replica 0 is the authentic
# content itself. Odd primes near 1e6 keep magnitudes far below the 1 MiB
# integer bound while making every nonzero numerator distinct.
REPLICA_FACTORS = (1, 1000003, 1000033, 1000037)
# Every overlap module, bound into the run's source closure with the base set.
SOURCES = ('measure_live_capacity_overlaps.py', 'live_spatial_patch.py', 'live_transport_result.py',
           'live_finite_patch.py', 'spatial_indexed_patch.py', 'spatial_validation_patch.py',
           'live_composite.py', 'exchange_record_patch.py')
SAMPLE_SECONDS = 0.05
PROPOSAL_SCHEMA = 'atlas.finite-spatial-stock-proposal.v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


# Builder high-water marks. Each record builder has its own 256 MiB child
# WorkBudget that ends with the pack, so a successful pack leaves no trace of
# how close it came to that guard. This test-only probe keeps each child
# budget object (counters only, not the builder's tables) and labels it with
# the record schema being packed. It changes no output, booking or limit.
_BUILDERS, _LABEL = [], threading.local()


def install_builder_probe():
    import record_tables as T
    if getattr(T._Builder.__init__, 'step8_builder_probe', False):
        return
    original_init, original_pack = T._Builder.__init__, T.RecordCodec.pack_record

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        _BUILDERS.append({'label': getattr(_LABEL, 'value', None), 'budget': self.work_budget})

    def pack_record(self, value, *, record_schema, **kwargs):
        previous = getattr(_LABEL, 'value', None)
        _LABEL.value = previous or record_schema
        try:
            return original_pack(self, value, record_schema=record_schema, **kwargs)
        finally:
            _LABEL.value = previous

    init.step8_builder_probe = True
    T._Builder.__init__, T.RecordCodec.pack_record = init, pack_record


class labelled:
    """Label builders made outside pack_record (RecordBuilder, PartitionV2Builder)."""
    def __init__(self, label):
        self.label = label

    def __enter__(self):
        self.previous, _LABEL.value = getattr(_LABEL, 'value', None), self.label

    def __exit__(self, *exc):
        _LABEL.value = self.previous
        return False


def builder_summary(start=0):
    rows = []
    for at, row in enumerate(_BUILDERS[start:], start):
        stats = row['budget'].statistics()
        rows.append({'index': at, 'label': row['label'], 'peak_bytes': stats['peak_reserved_bytes'],
                     'limit_bytes': stats['max_bytes'], 'refusals': stats['refusals']})
    return rows


class Sampler:
    """Maxima of process RSS/private and tracked reservation while one overlap runs."""
    def __init__(self, budget):
        import psutil
        self.process, self.budget = psutil.Process(), budget
        self.maxima = {'rss_bytes': 0, 'private_bytes': 0, 'reserved_bytes': 0}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _sample(self):
        info = self.process.memory_info()
        values = {'rss_bytes': info.rss, 'private_bytes': getattr(info, 'private', info.vms),
                  'reserved_bytes': self.budget.reserved_bytes}
        for key, value in values.items():
            self.maxima[key] = max(self.maxima[key], value)

    def _run(self):
        while not self._stop.wait(SAMPLE_SECONDS):
            self._sample()

    def __enter__(self):
        self._sample()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        self._sample()
        return False


def _snapshot(ctx):
    return {'seconds': round(time.monotonic()-ctx.started, 3), 'process': CAP.process_sample(),
            'tracked': ctx.budget.statistics(), 'scope': CAP.scope_sample(ctx.scope),
            'output_disk_bytes': CAP.disk_bytes(ctx.output)}


def _measured(ctx, name, function):
    """Run one overlap with before/after samples, sampled maxima and builder peaks."""
    row = {'name': name, 'before': _snapshot(ctx), 'source_decodes': []}
    ctx.results.append(row)
    ctx.phase('overlap-'+name+'-start')
    first = len(_BUILDERS)
    with Sampler(ctx.budget) as sampler:
        refs = function(ctx, row)
    after = _snapshot(ctx)
    row.update(after=after, sampled_maxima=sampler.maxima, builders=builder_summary(first),
               elapsed_seconds=round(after['seconds']-row['before']['seconds'], 3))
    ctx.phase('overlap-'+name+'-held')
    return refs


def _rename(text, replica):
    """Replica-specific 64-hex identifier; every other string is kept."""
    if replica and len(text) == 64 and all(c in '0123456789abcdef' for c in text):
        return sha256(f'capacity replica {replica}:{text}'.encode()).hexdigest()
    return text


def _is_rational(value):
    return len(value) == 2 and all(type(x) is str and x.startswith(('0x', '-0x')) for x in value)


def _replicate(value, factor, replica):
    """Distinct-content replica: 64-hex IDs renamed, exact rational numerators scaled."""
    if type(value) is dict:
        return {_rename(k, replica): _replicate(v, factor, replica) for k, v in value.items()}
    if type(value) is list:
        if _is_rational(value):
            return [hex(int(value[0], 16)*factor), value[1]]
        return [_replicate(item, factor, replica) for item in value]
    if type(value) is str:
        return _rename(value, replica)
    return value


def graph4(ctx, row):
    """IV2-shaped graph: every authentic collection of 100+ entries times four, one record."""
    import mesh_tables as M
    from record_tables import RecordCodec
    expected = ctx.census['records']['spatial-record:graph']
    ctx.phase('probe-graph4-source-decode')
    raw_owner = M._Allocation(ctx.budget, 65536+2*expected['filebytes'])
    raw = CAP.GRAPH.read_bytes()
    require(sha256(raw).hexdigest() == expected['sha256'], 'graph spool changed')
    charge = M._decode_charge(raw)
    owners = [M._Allocation(ctx.budget, charge)]
    graph = json.loads(raw)
    del raw, raw_owner
    large = sorted(k for k, v in graph.items() if type(v) in (list, dict) and len(v) >= 100)
    ctx.phase('probe-graph4-replicate')
    for replica in range(1, len(REPLICA_FACTORS)):
        # Each replica is booked as a full decoded-size copy of the graph.
        owners.append(M._Allocation(ctx.budget, charge))
        for key in large:
            ctx.check()
            copy = _replicate(graph[key], REPLICA_FACTORS[replica], replica)
            if type(graph[key]) is list:
                graph[key].extend(copy)
            else:
                require(not set(copy) & set(graph[key]), 'replica keys collide')
                graph[key].update(copy)
            del copy
    ctx.phase('probe-graph4-pack')
    started = time.monotonic()
    compact = RecordCodec().pack_record(graph, record_schema=graph['schema'], scope=ctx.scope, check=ctx.check)
    seconds = time.monotonic()-started
    identity = compact.identity()
    row.update(replicated_fields=large, logical_bytes=identity.canonical_bytes, pack_seconds=round(seconds, 3),
               packed_column_bytes=sum(a.nbytes for a in compact._owner.value[1].values()),
               scope_note='capacity probe only: IDs renamed and rationals scaled per replica')
    del graph, owners
    compact.close()
    return {}


PROBE_FUNCTIONS = {'graph4': graph4}


def _scaled(value, factor, replica):
    """Distinct-content replica of one support (capacity input, not geometry)."""
    if type(value) is dict:
        out = {}
        for key, item in value.items():
            if key in ('logical_cell_id', 'parent_cell_id') and type(item) is str:
                out[key] = sha256(f'capacity successor replica {replica}:{item}'.encode()).hexdigest()
            else:
                out[key] = _scaled(item, factor, replica)
        return out
    if type(value) is list:
        if _is_rational(value):
            return [hex(int(value[0], 16)*factor), value[1]]
        return [_scaled(item, factor, replica) for item in value]
    return value


def _issue_partition(ctx, row, name, header, supports, shape):
    """Issue every replica of every support through the compact producer, then publish.

    header is the decoded parent body (its supports and partition_id are not
    reused); shape(support) gives the replica-0 support before distinct-content
    scaling. Returns the published reference wire.
    """
    import live_partition_patch as L
    import partition_native_patch as PN
    from partition_store import publish_partition_v2
    with labelled(name+'-partition-'+str(len(REPLICA_FACTORS)*len(supports))):
        batch = L.SupportBatch(ctx.scope, check=ctx.check)
    ids = []
    ctx.phase('overlap-'+name+'-issue')
    for replica, factor in enumerate(REPLICA_FACTORS):
        for support in supports:
            ctx.check()
            value = shape(support)
            value = value if replica == 0 else _scaled(value, factor, replica)
            owned = L.owned_support(value, ctx.budget)
            issued = batch.issue(owned.value)
            batch.append(issued)
            ids.append(issued.support_id)
            del owned, issued, value
        ctx.phase(f'overlap-{name}-replica-{replica}-issued')
    require(len(set(ids)) == len(ids) == len(REPLICA_FACTORS)*len(supports),
            'successor supports are not all distinct')
    body = {k: v for k, v in header.items() if k not in ('supports', 'partition_id')}
    body['support_ids'] = ids
    # The body is booked as its own owned copy before the decoded source ends.
    body_owner = L.owned_support(body, ctx.budget)
    del body, ids
    ctx.phase('overlap-'+name+'-finish')
    native = PN._native()
    partition = batch.finish(body_owner.value, native._record_hash(body_owner.value))
    batch.close()
    del body_owner
    ctx.owners.callback(partition.close)
    ctx.phase('overlap-'+name+'-publish')
    ref = publish_partition_v2(ctx.candidate, partition,
        producer=sha256(f'capacity {name} partition {partition.support_count}'.encode()).hexdigest(), check=ctx.check)
    row.update(support_count=partition.support_count, partition_id=partition.partition_id,
               identity=partition.record.identity().to_wire(), reference=ref.to_wire())
    return ref.to_wire()


def successor(ctx, row):
    from measure_live_mesh_capacity import _read_record
    ctx.phase('overlap-successor-source-decode')
    held = _read_record(ctx.source, ctx.census['records']['partition-record:partition'], budget=ctx.budget,
                        check=ctx.check, evidence=row['source_decodes'])
    descriptor = held.value
    supports = descriptor['supports']
    ref = _issue_partition(ctx, row, 'successor', descriptor, supports, lambda support: support)
    del descriptor, supports, held
    row['scope_note'] = 'synthetic distinct-content replicas of authentic IV1 supports; not a scientific partition'
    return {'successor_partition': ref}


def _carried_one_interval(support):
    """The support one interval deeper, exactly as prepare_interval_partition carries
    a constraint into the next chart: a snapshot-rotated record holding the value,
    the parent interval's duration and the plate's angular velocity (both already
    stored in the support in the exact rational encoding the code writes)."""
    offset, omega = support['duration_s'], support['material_angular_velocity_rad_s']
    return {**support, 'constraints': {
        name: {'kind': 'snapshot-rotated', 'constraint': value, 'snapshot_offset_s': offset,
               'angular_velocity_rad_s': omega}
        for name, value in support['constraints'].items()}}


def successor2(ctx, row):
    """IV2-shaped successor from the saved interval-two continuation capture.

    The capture holds the authentic IV1 partition that interval two's
    preparation reads (SHA-256 checked). Every stored constraint of every
    support is carried one interval deeper (depth 2 for all, against about half
    at interval two as measured, so a conservative shape), and four distinct
    replicas give the measured 3.8-5x growth in supports.
    """
    import gzip

    import mesh_tables as M
    ctx.phase('overlap-successor2-capture-decode')
    packed = CAPTURE.read_bytes()
    require(sha256(packed).hexdigest() == CAPTURE_SHA256, 'interval-two continuation capture changed')
    size = int.from_bytes(packed[-4:], 'little')  # gzip ISIZE: the exact size below 4 GiB
    raw_owner = M._Allocation(ctx.budget, 65536+2*size)
    raw = gzip.decompress(packed)
    require(len(raw) == size, 'capture size differs from its gzip trailer')
    charge = M._decode_charge(raw)
    decoded_owner = M._Allocation(ctx.budget, charge)
    capture = json.loads(raw)
    del raw, raw_owner, packed
    row['source_decodes'].append({'capture': str(CAPTURE), 'sha256': CAPTURE_SHA256, 'bytes': size,
                                  'decoded_charge_bytes': charge})
    supports = capture['supports']
    ref = _issue_partition(ctx, row, 'successor2', capture['partition'], supports, _carried_one_interval)
    del capture, supports, decoded_owner
    row['scope_note'] = ('authentic IV1 supports from the interval-two capture, every constraint carried one '
                         'interval deeper, four distinct-content replicas; a capacity input, not geometry')
    return {'successor2_partition': ref}


def _live_transport(ctx):
    import live_spatial_patch as L
    source = (I/'atlas_tectonics/integration_spatial_transport.py').read_text(encoding='utf8')
    transformed = L.transport_source(source)
    name = '_step8_capacity_live_transport'
    fullname = 'atlas_tectonics.'+name
    path = ctx.output/(name+'.py')
    path.write_text(transformed, encoding='utf8', newline='\n')
    module = ModuleType(fullname)
    module.__package__, module.__file__ = 'atlas_tectonics', str(path)
    sys.modules[fullname] = module
    exec(compile(transformed, str(path), 'exec'), module.__dict__)  # noqa: S102 - the composed transport bytes
    return module, sha256(transformed.encode('utf8')).hexdigest()


def solver(ctx, row):
    import live_finite_patch as LIVE_FINITE
    import live_spatial_patch as L
    from atlas_tectonics.integration_mimetic_heat import _q
    from measure_live_mesh_capacity import _read_record
    from record_tables import RecordCodec
    ctx.phase('overlap-solver-transport-decode')
    held = _read_record(ctx.source, ctx.census['records']['spatial-record:transport'], budget=ctx.budget,
                        check=ctx.check, evidence=row['source_decodes'])
    t = held.value
    expected = {'result_id': t['result_id'], 'geometry_id': t['geometry_id'], 'state_id': t['state_id'],
                'source_stage_id': t['source_stage_id'], 'nonnegative_fields': tuple(t['nonnegative_fields']),
                'krylov_iterations': t['krylov_iterations']}
    errors = {name: _q(value['allowed']) for name, value in t['field_errors'].items()}
    inputs = t['exact_input_stocks']
    del t, held
    ctx.phase('overlap-solver-exchange-decode')
    held = _read_record(ctx.source, ctx.census['records']['spatial-record:exchange'], budget=ctx.budget,
                        check=ctx.check, evidence=row['source_decodes'])
    proposal = held.value['finite_proposal']
    ctx.shared['exchange_state_id'] = held.value['state_id']
    require(proposal['stocks'] == inputs, 'saved finite proposal stocks differ from the transport inputs')
    digest = sha256()
    for part in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(proposal['graph']):
        digest.update(part.encode('utf8'))
    require(digest.hexdigest() == expected['geometry_id'], 'saved transport graph differs from the authentic geometry ID')
    del inputs
    ctx.phase('overlap-solver-proposal-pack')
    # Packed under the schema the live finite proposal issue uses
    # (live_finite_patch.issue); with no live graph record to borrow from,
    # the whole proposal is packed, the larger of its two routes.
    compact = RecordCodec().pack_record(proposal, record_schema=PROPOSAL_SCHEMA, scope=ctx.scope, check=ctx.check)
    ctx.owners.callback(compact.close)
    del proposal, held
    ctx.phase('overlap-solver-proposal-held-source-released')
    module, transport_sha = _live_transport(ctx)
    ctx.phase('overlap-solver-advance')
    started = time.monotonic()
    # The live owner's own inputs: FiniteStockProposal._transport_inputs is
    # LIVE_FINITE.transport_inputs (bounded graph view and funded exact stocks).
    issued = SimpleNamespace(_encoded=compact, _owner=SimpleNamespace(_budget=ctx.budget))
    with L.construction(ctx.scope, budget=ctx.budget):
        view, stocks = LIVE_FINITE.transport_inputs(issued, _q)
        try:
            with module.PreparedSpatialTransport(view, budget=ctx.budget) as operator:
                result = operator.advance(stocks, state_id=expected['state_id'],
                    source_stage_id=expected['source_stage_id'], max_projection_errors=errors,
                    nonnegative_fields=expected['nonnegative_fields'])
            cells, fields = len(next(iter(stocks.values()))), len(stocks)
        finally:
            view.stack.close()
            del view, stocks
    advance_seconds = time.monotonic()-started
    # The live transform issues the native result over a compact snapshot.
    snapshot = result._snapshot
    require(type(snapshot).__name__ == 'CompactTransportSnapshot', 'live transport did not issue a compact snapshot')
    ctx.owners.callback(snapshot._fields_owner.close)
    ctx.owners.callback(snapshot._record.close)
    require(result.result_id == expected['result_id'], 'replayed authentic IV1 transport differs from its record')
    ref = CAP.publish_record(ctx.candidate, snapshot._record, ctx.scope,
                             sha256(b'capacity replayed transport').hexdigest(), ctx.token)
    row.update(result_id=result.result_id, exact_result_id=True, geometry_id=expected['geometry_id'],
               cells=cells, fields=fields, advance_seconds=round(advance_seconds, 3),
               authentic_krylov_iterations=expected['krylov_iterations'], live_transport_sha256=transport_sha,
               proposal_identity=compact.identity().to_wire(), reference=ref.to_wire(),
               scope_note='live transport over the compact proposal; owner bookkeeping around it is in the W4 run')
    return {'replayed_transport': ref.to_wire()}


def state(ctx, row):
    import live_spatial_patch as L
    import spatial_indexed_patch as INDEXED
    from measure_live_mesh_capacity import _read_record
    require(ctx.meshes, 'a retained compact authentic mesh is required for the state issue')
    ctx.phase('overlap-state-source-decode')
    held = _read_record(ctx.source, ctx.census['records']['spatial-record:state'], budget=ctx.budget,
                        check=ctx.check, evidence=row['source_decodes'])
    record = held.value
    expected = record['state_id']
    require('exchange_state_id' not in ctx.shared or ctx.shared['exchange_state_id'] == expected,
            'stored state and authentic exchange name different state IDs')
    names = tuple(sorted(record['cells'][0]['exact']))
    ctx.phase('overlap-state-cell-sink')
    with labelled('state-cells'):
        sink = L.CellSink(ctx.scope, check=ctx.check)
    for cell in record['cells']:
        sink.append(cell)
    cells = sink.finish()
    ctx.owners.callback(sink._record.close)
    # The stored state is the logical body without its mesh, plus its own ID.
    body = {key: value for key, value in record.items() if key not in ('cells', 'state_id')}
    body.update(cells=cells, thermal_mesh=ctx.meshes[0])
    del record, held, cell
    owner = SimpleNamespace(_budget=ctx.budget, _names=names, _record_scope=ctx.scope)
    ctx.phase('overlap-state-issue')
    issued = INDEXED.issue(owner, body)
    ctx.keep.append(issued)
    state_id = issued._snapshot.result_id
    require(state_id == expected, 'composed state issue differs from the authentic state ID')
    row.update(state_id=state_id, exact_state_id=True, cells=cells.size, fields=len(names)+1,
               cells_identity=sink._record.identity().to_wire(),
               scope_note='cell rows come from the decoded authentic record; the live finish appends them one at a time')
    ctx.shared['state_cells'] = cells
    return {}


def _carried_live(ctx, row, cells, V):
    """D1-B (16 Oct 2026): the composed owner's carried start over the same cells.

    An index, rows exported when read: the identity start exactly as the
    transformed _carried_start_cells builds it (one field-level lineage read
    per parent, positions recorded), then close_graph's first read pass. The
    retained peak over that pass is sampled per row.
    """
    base = ctx.scope.stats().retained_bytes
    started = time.monotonic()
    previous = V.start_rows(cells)
    carried = V.carried_rows(previous)
    for key in previous:
        old = V.lineage_row(previous, key)
        _lineage = old['source_key']    # the identity check's one field read
        V.carry(carried, key, key, old)
    old = _lineage = None
    index = ctx.scope.stats().retained_bytes-base
    start_seconds = time.monotonic()-started
    peak, started = index, time.monotonic()
    for value in carried.values():   # the same per-row export as close_graph's items() pass
        peak = max(peak, ctx.scope.stats().retained_bytes-base)
        _volume = value['volume_m3']    # close_graph's starts read
    value = _volume = None
    row['live'] = {'rows': len(carried), 'index_retained_bytes': index, 'peak_retained_delta_bytes': peak,
                   'carried_start_seconds': start_seconds, 'read_pass_seconds': time.monotonic()-started}
    del previous, carried
    row['live']['retained_after_release_bytes'] = ctx.scope.stats().retained_bytes


def carried(ctx, row):
    """The next interval's carried parent cells over this state's compact cells.

    Two passes over the same issued cells. 'live' is the composed owner's D1-B
    carried start (_carried_live). The fields at the top level are the pre-D1-B
    expression, kept as the before measurement: every parent row decoded once
    and held in one dict until the owner's frame ends. A refusal there is
    recorded as the finding (rows held, retained bytes) and its frames are
    released, so the rest of the run continues on a consistent scope.
    """
    import traceback

    import spatial_validation_patch as V
    require('state_cells' in ctx.shared, 'run state first: carried rows come from the issued compact state')
    cells = ctx.shared['state_cells']
    ctx.phase('overlap-carried-live')
    _carried_live(ctx, row, cells, V)
    base = ctx.scope.stats().retained_bytes
    previous, held = {}, 0
    ctx.phase('overlap-carried-rows')
    try:
        for value in V.rows(cells):
            previous[value['cell_id']] = value
            held += 1
        del value
        full = ctx.scope.stats().retained_bytes
        row.update(rows=held, refused=False, retained_delta_bytes=full-base,
                   charge_per_row_bytes=(full-base)//max(held, 1))
    except Exception as error:  # noqa: BLE001 - the refusal is the measurement
        chain = CAP.exception_chain(error)
        row.update(rows=held, refused=True, refusal={'type': type(error).__name__, 'message': str(error),
                   'first_raised': {'type': type(chain[-1]).__name__, 'message': str(chain[-1])}},
                   retained_delta_bytes=ctx.scope.stats().retained_bytes-base)
        for item in chain:
            traceback.clear_frames(item.__traceback__)
            item.__traceback__ = None
        chain = item = None
    row['retained_limit_bytes'] = ctx.scope.retained_budget.max_bytes
    previous.clear()
    row['retained_after_release_bytes'] = ctx.scope.stats().retained_bytes
    row['scope_note'] = 'one parent state of the authentic IV1 size; an IV2 parent has about four times the rows'
    return {}


def restore(ctx, row):
    import private_heat_snapshot_store_r4 as HEAT_STORE
    receipts = ctx.heat_receipts()
    require(receipts, 'saved heat ledgers are required for the restore overlap')
    opened = []
    for at, (result_id, receipt) in enumerate(receipts):
        ctx.phase(f'overlap-restore-heat-{at}')
        handle = HEAT_STORE.open(ctx.candidate, receipt, expected_result_id=result_id,
                                 bindings=receipt['metadata']['bindings'], scope=ctx.scope)
        ctx.owners.callback(handle.close)
        ctx.owners.callback(handle.value.close)
        opened.append({'result_id': handle.value.result_id, 'fields': len(handle.value._fields),
                       'field_bytes': sum(8*math.prod(shape) for _, shape, _ in handle.value._fields)})
    row.update(restored=opened)
    return {}


def producers(ctx, row):
    from measure_live_mesh_capacity import _read_record
    from record_tables import RecordCodec
    refs = {}
    for name in ('certification-record:final', 'differential-record:geometry'):
        binding = ctx.census['records'][name]
        ctx.phase('overlap-producers-'+name.split(':')[0]+'-decode')
        held = _read_record(ctx.source, binding, budget=ctx.budget, check=ctx.check, evidence=row['source_decodes'])
        ctx.phase('overlap-producers-'+name.split(':')[0]+'-issue')
        packed = RecordCodec().pack_record(held.value, record_schema=held.value.get('schema', name),
                                           scope=ctx.scope, check=ctx.check)
        ctx.owners.callback(packed.close)
        identity = packed.identity()
        require(identity.sha256 == binding['sha256'] and identity.canonical_bytes == binding['filebytes'],
                'authentic producer record identity changed')
        del held
        refs[name] = CAP.publish_record(ctx.candidate, packed, ctx.scope,
                                        sha256(('capacity producer '+name).encode()).hexdigest(), ctx.token).to_wire()
    row.update(records=refs, scope_note="issuance (compact pack and publish) at full overlap; the producers' "
               'own scientific computation is part of the owner advance measured in the W4 run')
    return {'producers': refs}


FUNCTIONS = {'successor': successor, 'successor2': successor2, 'solver': solver, 'state': state, 'carried': carried,
             'restore': restore, 'producers': producers}


def run_overlaps(ctx, names):
    ctx.results, ctx.shared, ctx.keep = [], {}, []
    ctx.owners.callback(ctx.keep.clear)
    # Shared values include live record references (the issued state cells);
    # they end with the run's owners, before the scope's own close check.
    ctx.owners.callback(ctx.shared.clear)
    refs = {}
    for name in names:
        refs.update(_measured(ctx, name, FUNCTIONS.get(name) or PROBE_FUNCTIONS[name]) or {})
    return refs


def overlap_hook(names):
    """Called by measure_live_capacity.workload at its full-overlap point."""
    def hook(base):
        base.record['builders_before_overlaps'] = builder_summary()
        heat = [row for row in base.record.get('other_families', []) if row['name'] == 'heat:metadata_utf8']
        fields = dict(vars(base))
        fields['meshes'] = list(getattr(base.meshes, 'meshes', None) or [])
        fields['heat_receipts'] = lambda: [(b['result_id'], b['receipt']) for row in heat for b in row['blocks']]
        ctx = SimpleNamespace(**fields)
        base.record['overlaps'] = {'names': list(names), 'rows': None}
        try:
            refs = run_overlaps(ctx, names)
        finally:
            base.record['overlaps']['rows'] = getattr(ctx, 'results', None)
            base.record['builders'] = builder_summary()
            base.record['candidate_statistics_at_overlap'] = ctx.candidate.local_statistics()
        return refs
    return hook


def _save_one_heat(ctx):
    """One authentic heat ledger saved to the candidate (standalone restore input)."""
    import private_heat_snapshot_store_r4 as HEAT_STORE
    from heat_ledger_tables import CompactHeatSnapshot
    from measure_live_mesh_capacity import _read_record
    binding = ctx.census['records']['heat:metadata_utf8']
    held = _read_record(ctx.source, binding, budget=ctx.budget, check=ctx.check, evidence=[])
    metadata = ctx.source.metadata(binding['snapshot'])
    arrays = CAP.PaidArrays(ctx.budget, ctx.census['heat']['native_fields'], 1)
    ctx.owners.callback(arrays.close)
    hashes = CAP.fill_numeric(ctx.source, binding['snapshot'], arrays.blocks[0], ctx.check)
    named = CAP.native_heat_fields(ctx.census, arrays.blocks[0], hashes)
    snapshot = CompactHeatSnapshot.from_components(held.value, named, scope=ctx.scope,
        check=ctx.check, expected_result_id=metadata['result_id'])
    ctx.owners.callback(snapshot.close)
    receipt = HEAT_STORE.save(ctx.candidate, snapshot, bindings=dict(metadata['bindings'],
        capacity_block=sha256(b'standalone').hexdigest()), scope=ctx.scope, cancel=ctx.token)
    del held, named
    arrays.close()
    return [(snapshot.result_id, receipt)]


def standalone_workload(output):
    """Only the named overlaps, on the same guarded scope, original and store."""
    import gc
    import traceback
    output = Path(output).resolve()
    plan = json.loads((output/'prepare.json').read_text(encoding='utf8'))
    names = tuple(plan['overlaps']['names'])
    require(plan['sources'] == CAP.source_bindings(plan.get('extra_sources', ())),
            'capacity source closure changed after launch')
    value = CAP.read_census()
    sys.path.insert(0, str(output/'guard'))
    import historical_admission as H
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import Compression, StoreLimits
    from content_cache import create_retained_scope
    from interval_store_set import IntervalStoreSet
    from private_heat_continuation_guard_r3 import ContinuationGuard
    record = {'schema': 'atlas.step8.capacity-overlaps-standalone.v1', 'status': 'RUNNING',
              'scientific_status': 'NOT_A_REAL_IV2_RUN', 'sources': plan['sources'], 'guards': CAP.GUARDS,
              'start_gate': plan.get('start_gate'), 'record_spill_directory': plan.get('record_spill_directory'),
              'workload_timeout_seconds': plan.get('workload_timeout_seconds'),
              'live_producer': plan.get('live_producer'),
              'overlaps': {'names': list(names), 'rows': None}, 'checkpoints': []}
    result_path = output/'capacity.json'

    def save():
        CAP.write_json(result_path, record)
    save()
    budget = WorkBudget(CAP.GUARDS['logical_budget_bytes'])
    guard = ContinuationGuard(result_path, record, save)
    guard.budget = budget
    started, owners, failed = time.monotonic(), ExitStack(), False
    scope = None
    bound = plan.get('workload_timeout_seconds', CAP.MAX_SECONDS)

    def check():
        guard.check()
        if time.monotonic()-started > bound:
            raise TimeoutError(f'bounded capacity workload exceeded {bound} seconds')

    def phase(name):
        check()
        row = {'name': name, 'seconds': time.monotonic()-started, 'process': CAP.process_sample(),
               'tracked': budget.statistics(), 'scope': CAP.scope_sample(scope),
               'output_disk_bytes': CAP.disk_bytes(output)}
        record['checkpoints'].append(row)
        guard.phase(name)
        print(json.dumps({'phase': name, 'seconds': round(row['seconds'], 3),
                          'rss_bytes': row['process']['rss_bytes']}), flush=True)

    gc_was_enabled = gc.isenabled()
    gc.disable()
    ctx = None
    try:
        scope = create_retained_scope(budget, process_epoch='step8-capacity-overlaps-standalone',
                                      live_producer_bytes=(plan.get('live_producer') or {}).get('bytes'))
        owners.callback(scope.close)
        endpoint = value['census']['endpoint']
        source = owners.enter_context(H.open_original_readonly(limits=StoreLimits(**endpoint['store_limits']),
            compression=Compression(**endpoint['store_compression']), budget=budget))
        stores = IntervalStoreSet.create_migration(output/'catalog.json',
            workflow_id=sha256(b'step8 capacity overlaps standalone').hexdigest(), scope=scope)
        owners.callback(stores.close)
        candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        owners.callback(candidate.close)
        ctx = SimpleNamespace(scope=scope, budget=budget, candidate=candidate, source=source,
            census=value['census'], owners=owners, check=check, phase=phase, token=CAP.CheckToken(check),
            output=output, started=started, record=record, meshes=[], heat_receipts=list)
        if 'state' in names:
            from measure_live_mesh_capacity import retain_mesh_blocks
            meshes = retain_mesh_blocks(scope, candidate, source, value['census'], count=1, check=check,
                                        checkpoint=phase)
            owners.callback(meshes.close)
            ctx.meshes = list(meshes.meshes)
        if 'restore' in names:
            phase('standalone-heat-ledger-save')
            saved = _save_one_heat(ctx)
            ctx.heat_receipts = lambda: saved
        run_overlaps(ctx, names)
        record['overlaps']['rows'] = ctx.results
        record['candidate_statistics'] = candidate.local_statistics()
        record['status'] = 'OVERLAPS_COMPLETE'
        phase('overlaps-complete')
        owners.close()
        phase('all-owned-objects-released')
        require(budget.reserved_bytes == 0, 'overlap resources retained after explicit cleanup')
    except BaseException as error:  # noqa: BLE001 - every failure is recorded, then the run reports non-zero
        failed = True
        record['status'] = 'REFUSED_OR_FAILED'
        if ctx is not None and getattr(ctx, 'results', None) is not None:
            record['overlaps']['rows'] = ctx.results
        chain = CAP.exception_chain(error)
        record['failure'] = {'type': type(error).__name__, 'message': str(error),
                             'first_raised': {'type': type(chain[-1]).__name__, 'message': str(chain[-1])},
                             'traceback': ''.join(traceback.format_exception(error)),
                             'process': CAP.process_sample(), 'tracked': budget.statistics(),
                             'scope': CAP.scope_sample(scope),
                             'record_builders': CAP.failed_builder_evidence(error)}
        # The held exceptions were recorded while their frames stayed paid; drop
        # the frames of the whole chain (earlier tracebacks can hold borrows).
        for item in chain:
            traceback.clear_frames(item.__traceback__)
            item.__traceback__ = None
        chain = item = None
        try:
            owners.close()
        except BaseException as cleanup_error:  # noqa: BLE001 - recorded; the first failure stays primary
            record['cleanup_failure'] = repr(cleanup_error)
    finally:
        record['builders'] = builder_summary()
        record['elapsed_seconds'] = time.monotonic()-started
        record['final_process'] = CAP.process_sample()
        record['final_tracked'] = budget.statistics()
        record['output_disk_bytes'] = CAP.disk_bytes(output)
        try:
            guard.close()
        finally:
            if gc_was_enabled:
                gc.enable()
            save()
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch', type=Path)
    group.add_argument('--workload', type=Path)
    parser.add_argument('--overlaps', default=','.join(NAMES))
    parser.add_argument('--standalone', action='store_true')
    parser.add_argument('--start-gate-bytes', type=int, required=False)
    parser.add_argument('--start-gate-basis', default=None)
    parser.add_argument('--max-seconds', type=int, default=None)
    parser.add_argument('--max-seconds-basis', default=None)
    parser.add_argument('--scale', type=int, default=CAP.SCALE)
    parser.add_argument('--live-producer-bytes', type=int, default=None)
    args = parser.parse_args()
    if args.workload:
        plan = json.loads((args.workload/'prepare.json').read_text(encoding='utf8'))
        names = tuple(plan['overlaps']['names'])
        install_builder_probe()
        if plan['overlaps']['standalone']:
            return standalone_workload(args.workload)
        return CAP.workload(args.workload, overlaps=overlap_hook(names))
    names = tuple(name for name in args.overlaps.split(',') if name)
    allowed = NAMES+PROBES if args.standalone else NAMES
    require(names and all(name in allowed for name in names) and len(set(names)) == len(names),
            'overlap names must come from '+', '.join(allowed)+' (probes only with --standalone)')
    require('carried' not in names or 'state' in names and names.index('state') < names.index('carried'),
            'the carried overlap needs the state overlap first (issued compact cells)')
    return CAP.launch(args.launch, smoke=False, start_gate=args.start_gate_bytes, basis=args.start_gate_basis,
                      script=Path(__file__).resolve(), extra_sources=SOURCES,
                      plan_extra={'overlaps': {'names': list(names), 'standalone': args.standalone}},
                      max_seconds=args.max_seconds, max_seconds_basis=args.max_seconds_basis,
                      scale=args.scale, live_producer_bytes=args.live_producer_bytes)


if __name__ == '__main__':
    raise SystemExit(main())
