"""Read-only Step 8 probe: record_tables._Builder booking versus real memory.

Measures, on authenticated slices of the first authentic graph (record-004),
what the exact JSON -> compact DAG builder books on its mandatory 256 MiB child
WorkBudget and what Python memory it really retains, plus finish() arrays and
the mesh_tables._decode_charge admission versus real json.loads memory.

Writes only result*.json beside this file. No source file is modified.
Timings are taken only while tracemalloc is NOT running. Phase D (whole graph)
raises record_tables.MAX_BUILD_BYTES in this process only, so the builder can
run to completion and its would-be booking can be observed; that is a probe
device, never a proposed limit, and is labelled as such in the result.
"""
from __future__ import annotations

import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'

import argparse
from bisect import bisect_right
from collections import Counter
import gc
from hashlib import sha256
import json
import linecache
from pathlib import Path
import platform
import sys
import time
import tracemalloc
import weakref

import psutil

HERE = Path(__file__).resolve().parent
R = HERE.parents[3]
C = R/'compact-geometry-r1'
RUNTIME = R.parent/'runtime-integration-r1'/'runtime-src'
CENSUS = R/'probes/structure-census-r3/structure-census.json'
CENSUS_SHA256 = '02f0a05a7f05855d7ef578b879666489e8b2711405da2031204df372b5e379ae'
GRAPH = R/'probes/structure-census-r2/structure-scratch/record-004.json'
REC = 'physical_measure_receipts'
GIB = 1 << 30
MIN_AVAILABLE = 6*GIB
TARGETS = (1_000_000, 2_000_000, 4_000_000, 8_000_000, 15_000_000)
RUNTIME_LIMIT = 24*60          # seconds; optional phases are skipped past their gates
PROBE_UNCAPPED_BYTES = 8 << 30  # phase D only, in-process, labelled
sys.path[:0] = [str(C), str(R), str(RUNTIME)]

SOURCES = {'record_tables.py': C/'record_tables.py', 'mesh_tables.py': C/'mesh_tables.py',
           'content_cache.py': C/'content_cache.py', 'record_views.py': C/'record_views.py',
           'compact_contracts.py': C/'compact_contracts.py',
           'atlas_tectonics/resources.py': RUNTIME/'atlas_tectonics'/'resources.py'}
# arena.hold call sites in record_tables.py (verified against the source text at start).
HOLD_SITES = {('token', 148): 'tokens', ('integer', 165): 'integers', ('_add', 267): 'floats',
              ('_add', 275): 'ids', ('_add', 308): 'shapes', ('_add', 364): 'pairs',
              ('_add', 381): 'nodes', ('finish', 391): 'finish'}
SITE_TEXT = {120: 'self.arena.hold(8192)', 148: 'self.arena.hold(1024+32*len(value))',
             165: 'self.arena.hold(1024+(0 if dyadic else 4*count))', 267: 'self.arena.hold(256)',
             268: 'self.float_index[raw]', 275: 'self.arena.hold(256)', 276: 'self.id_index[value]',
             308: 'self.arena.hold(512+64*len(keys))', 364: 'self.arena.hold(256)',
             365: 'self.pair_index[children]', 381: 'self.arena.hold(768+64*len(children))',
             391: 'self.arena.hold(65536+160*n+32*e+sum(map(len, self.tokens)))'}
KIND_NAMES = ('NULL', 'BOOL', 'INTEGER', 'FLOAT', 'TEXT', 'IDENT', 'HEX', 'ARRAY', 'OBJECT', 'RATIONAL')
PROC = psutil.Process()
STARTED = time.monotonic()


def log(*parts):
    print(f'[{time.monotonic()-STARTED:7.1f}s]', *parts, flush=True)


def elapsed():
    return time.monotonic()-STARTED


def file_sha(path):
    digest = sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def mem():
    m = PROC.memory_info()
    return dict(rss=m.rss, private=getattr(m, 'private', None), peak_wset=getattr(m, 'peak_wset', None))


def mem_delta(a, b):
    return {k: b[k]-a[k] for k in ('rss', 'private') if a[k] is not None and b[k] is not None}


def available():
    return psutil.virtual_memory().available


def check():
    return None


# ---------------------------------------------------------------- decode side

def deep_json(value):
    """Unique-object sys.getsizeof sum of a decoded JSON tree (shared keys once)."""
    seen, total, by_type = set(), 0, {}
    stack = [value]
    getsizeof = sys.getsizeof
    while stack:
        o = stack.pop()
        i = id(o)
        if i in seen:
            continue
        seen.add(i)
        s = getsizeof(o)
        total += s
        entry = by_type.setdefault(type(o).__name__, [0, 0])
        entry[0] += 1
        entry[1] += s
        if type(o) is dict:
            stack.extend(o)
            stack.extend(o.values())
        elif type(o) is list:
            stack.extend(o)
    return dict(bytes=total, objects=len(seen),
                by_type={k: dict(count=v[0], bytes=v[1]) for k, v in sorted(by_type.items())})


def decode_untraced(raw):
    """RSS/private delta of json.loads(raw); value kept alive across the second sample."""
    gc.collect()
    gc.disable()
    a = mem()
    t0 = time.perf_counter()
    value = json.loads(raw)
    t1 = time.perf_counter()
    b = mem()
    gc.enable()
    return value, dict(seconds=t1-t0, before=a, after=b, delta=mem_delta(a, b))


def decode_traced(raw):
    gc.collect()
    gc.disable()
    tracemalloc.start()
    c0, _ = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    value = json.loads(raw)
    c1, p1 = tracemalloc.get_traced_memory()
    own = tracemalloc.get_tracemalloc_memory()
    del value
    c2, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.enable()
    return dict(retained_bytes=c1-c0, peak_bytes=p1-c0, residual_after_free=c2-c0,
                tracemalloc_own_memory=own)


# --------------------------------------------------------------- builder side

def verify_hold_sites(RT):
    path = RT.__file__
    linecache.checkcache(path)
    bad = {line: linecache.getline(path, line).strip() for line, text in SITE_TEXT.items()
           if text not in linecache.getline(path, line)}
    if bad:
        raise SystemExit('record_tables.py hold sites moved; refusing to attribute: '+repr(bad))


class Instrument:
    """Per-instance wrappers (no source edit): arena.hold by call site, scratch live/peak."""

    def __init__(self, builder, RT):
        arena = builder.arena
        self.arena_ref, builder_ref = weakref.ref(arena), weakref.ref(builder)
        self.chunk = RT.CHUNK
        self.chunks = len(arena.owners)
        self.arena_booked = RT.CHUNK*len(arena.owners)   # __init__ hold(8192) opened one chunk
        self.requested, self.holds = {'initial': 8192}, {'initial': 1}
        self.scratch_live = self.scratch_peak = self.scratch_calls = self.scratch_requested = 0
        self.scratch_max_single = 0
        self.total_peak = self.arena_booked
        self.refused = None
        hold_impl, scratch_impl = RT._Arena.hold, RT._Builder.scratch
        sites = HOLD_SITES
        state = self

        def hold(size):
            frame = sys._getframe(1)
            site = sites.get((frame.f_code.co_name, frame.f_lineno),
                             f'{frame.f_code.co_name}:{frame.f_lineno}')
            del frame
            target = state.arena_ref()
            chunk = max(state.chunk, size+1024) if size > target.free else 0
            try:
                hold_impl(target, size)
            except BaseException as exc:
                state.refused = dict(site=site, requested=size, new_chunk=chunk,
                                     arena_booked=state.arena_booked, scratch_live=state.scratch_live,
                                     exception=type(exc).__name__)
                raise
            state.arena_booked += chunk
            state.chunks += bool(chunk)
            state.requested[site] = state.requested.get(site, 0)+size
            state.holds[site] = state.holds.get(site, 0)+1
            booked = state.arena_booked+state.scratch_live
            if booked > state.total_peak:
                state.total_peak = booked

        def scratch(size):
            try:
                held = scratch_impl(builder_ref(), size)
            except BaseException as exc:
                state.refused = dict(site='scratch', requested=size, arena_booked=state.arena_booked,
                                     scratch_live=state.scratch_live, exception=type(exc).__name__)
                raise
            state.scratch_live += size
            state.scratch_calls += 1
            state.scratch_requested += size
            if size > state.scratch_max_single:
                state.scratch_max_single = size
            if state.scratch_live > state.scratch_peak:
                state.scratch_peak = state.scratch_live
            booked = state.arena_booked+state.scratch_live
            if booked > state.total_peak:
                state.total_peak = booked
            weakref.finalize(held, state._release, size)
            return held

        arena.hold = hold
        builder.scratch = scratch

    def _release(self, size):
        self.scratch_live -= size

    def report(self):
        arena = self.arena_ref()
        requested_total = sum(self.requested.values())
        return dict(arena_requested_by_site=dict(self.requested), arena_holds_by_site=dict(self.holds),
                    arena_requested_total=requested_total, arena_chunks=self.chunks,
                    arena_booked=self.arena_booked, arena_chunk_overhead=1024*self.chunks,
                    arena_unused_free=None if arena is None else arena.free,
                    arena_identity_ok=None if arena is None else
                        self.arena_booked == requested_total+1024*self.chunks+arena.free,
                    scratch_peak_live=self.scratch_peak, scratch_calls=self.scratch_calls,
                    scratch_requested_cumulative=self.scratch_requested,
                    scratch_max_single=self.scratch_max_single, scratch_live_now=self.scratch_live,
                    reconstructed_total_peak=self.total_peak, refused=self.refused)


def formula_booking(b):
    """Arena booking recomputed from table contents and the record_tables formulas."""
    integers = 0
    for v in b.integer_index:
        m = abs(v)
        count = (m.bit_length()+7)//8
        dyadic = m > 0 and m & (m-1) == 0 and count > 8
        integers += 1024+(0 if dyadic else 4*count)
    out = dict(initial=8192,
               tokens=sum(1024+32*len(k) for k in b.token_index),
               integers=integers, floats=256*len(b.floats), ids=256*len(b.ids),
               pairs=256*len(b.pairs), shapes=sum(512+64*len(s) for s in b.shapes),
               nodes=sum(768+64*len(r[3]) for r in b.nodes))
    out['total'] = sum(out.values())
    return out


def counts(b):
    kinds = Counter(r[0] for r in b.nodes)
    return dict(nodes=len(b.nodes), edges=sum(len(r[3]) for r in b.nodes),
                node_kinds={KIND_NAMES[k]: v for k, v in sorted(kinds.items())},
                tokens=len(b.tokens), token_encoded_bytes=sum(map(len, b.tokens)),
                token_input_chars=sum(len(k) for k in b.token_index),
                integers=len(b.integers), integer_magnitude_bytes=sum(len(r[3]) for r in b.integers),
                floats=len(b.floats), ids=len(b.ids), pairs=len(b.pairs), shapes=len(b.shapes),
                shape_keys=sum(map(len, b.shapes)), emitted_logical_bytes=b.length,
                max_scalar_charge=b._max_scalar_charge)


def table_sizes(b):
    """Deep sys.getsizeof per table, each object counted once (first-visit attribution).

    'preexisting' = allocated before tracemalloc started (input-owned strings and
    ints, or static singletons); 'new' = allocated by the builder.
    """
    seen = set()
    getsizeof, origin = sys.getsizeof, tracemalloc.get_object_traceback

    def rec():
        return dict(new_bytes=0, new_objects=0, preexisting_bytes=0, preexisting_objects=0)

    def visit(o, r):
        i = id(o)
        if i in seen:
            return
        seen.add(i)
        s = getsizeof(o)
        if origin(o) is None:
            r['preexisting_bytes'] += s
            r['preexisting_objects'] += 1
        else:
            r['new_bytes'] += s
            r['new_objects'] += 1
        if type(o) is tuple:
            for e in o:
                visit(e, r)

    result = {}

    def list_table(name, container):
        seen.add(id(container))
        r = rec()
        for o in container:
            visit(o, r)
        result[name] = dict(container_bytes=getsizeof(container), elements=r,
                            new_total=getsizeof(container)+r['new_bytes'])

    def dict_table(name, container):
        seen.add(id(container))
        rk, rv = rec(), rec()
        for k, v in container.items():
            visit(k, rk)
            visit(v, rv)
        result[name] = dict(container_bytes=getsizeof(container), keys=rk, values=rv,
                            new_total=getsizeof(container)+rk['new_bytes']+rv['new_bytes'])

    list_table('tokens', b.tokens)
    dict_table('token_index', b.token_index)
    list_table('nodes', b.nodes)
    dict_table('index', b.index)
    list_table('integers', b.integers)
    dict_table('integer_index', b.integer_index)
    list_table('floats', b.floats)
    dict_table('float_index', b.float_index)
    list_table('ids', b.ids)
    dict_table('id_index', b.id_index)
    list_table('shapes', b.shapes)
    dict_table('shape_index', b.shape_index)
    list_table('pairs', b.pairs)
    dict_table('pair_index', b.pair_index)
    # Arena leases: Scratch, its contextmanager lease and generator (approximate; no __dict__ materialised).
    seen.add(id(b.arena.owners))
    r = rec()
    for s in b.arena.owners:
        visit(s, r)
        lease = getattr(s, '_lease', None)
        if lease is not None:
            visit(lease, r)
            gen = getattr(lease, 'gen', None)
            if gen is not None:
                visit(gen, r)
    result['arena_owners_approx'] = dict(container_bytes=getsizeof(b.arena.owners), elements=r,
                                         new_total=getsizeof(b.arena.owners)+r['new_bytes'])
    result['total_new'] = sum(v['new_total'] for v in result.values())
    result['token_index_keys_shared_input_bytes'] = result['token_index']['keys']['preexisting_bytes']
    result['token_index_keys_new_bytes'] = result['token_index']['keys']['new_bytes']
    return result


def group(tables):
    """Category groups: list + its index dict."""
    pick = lambda *names: sum(tables[n]['new_total'] for n in names)
    return dict(tokens=pick('tokens', 'token_index'), nodes=pick('nodes', 'index'),
                integers=pick('integers', 'integer_index'), floats=pick('floats', 'float_index'),
                ids=pick('ids', 'id_index'), shapes=pick('shapes', 'shape_index'),
                pairs=pick('pairs', 'pair_index'), arena_owners=tables['arena_owners_approx']['new_total'])


def run_untraced(value, raw_sha, raw_len, scope, schema, RT, errors, *, do_finish=True):
    gc.collect()
    gc.disable()
    rb0 = scope.run_budget.reserved_bytes
    m0 = mem()
    out = {}
    t0 = time.perf_counter()
    b = RT._Builder(scope, check)
    root = None
    try:
        root = b.add(value)
    except errors as exc:
        out['refusal'] = dict(type=type(exc).__name__, message=str(exc), emitted_logical_bytes=b.length,
                              budget_at_refusal=b.work_budget.statistics())
    t1 = time.perf_counter()
    m1 = mem()
    out['add_seconds'] = t1-t0
    out['mem_after_add'] = m1
    out['mem_delta_after_add'] = mem_delta(m0, m1)
    out['budget_after_add'] = b.work_budget.statistics()
    out['counts'] = counts(b)
    if root is not None:
        out['exact'] = dict(sha256_match=b.digest.hexdigest() == raw_sha, length_match=b.length == raw_len)
        if do_finish:
            t2 = time.perf_counter()
            metadata, arrays = b.finish(root, schema)
            t3 = time.perf_counter()
            m2 = mem()
            out['finish'] = dict(seconds=t3-t2, array_nbytes=sum(a.nbytes for a in arrays.values()),
                                 metadata_bytes=len(metadata), mem_delta_vs_after_add=mem_delta(m1, m2),
                                 budget_after_finish=b.work_budget.statistics())
            del metadata, arrays
    del b, root
    gc.collect()
    m3 = mem()
    gc.enable()
    out['released'] = dict(run_budget_reserved_before=rb0, run_budget_reserved_after=scope.run_budget.reserved_bytes,
                           mem_delta_after_release=mem_delta(m0, m3))
    return out


def run_traced(value, raw_sha, raw_len, scope, schema, RT, errors, *, do_finish=True):
    gc.collect()
    gc.disable()
    rb0 = scope.run_budget.reserved_bytes
    tracemalloc.start()
    base, _ = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    b = RT._Builder(scope, check)
    inst = Instrument(b, RT)
    out = {}
    root = None
    try:
        root = b.add(value)
    except errors as exc:
        out['refusal'] = dict(type=type(exc).__name__, message=str(exc), emitted_logical_bytes=b.length,
                              budget_at_refusal=b.work_budget.statistics(), refused_request=inst.refused)
    cur, peak = tracemalloc.get_traced_memory()
    gc.collect()
    cur_gc, _ = tracemalloc.get_traced_memory()
    out['tracemalloc_add'] = dict(retained=cur-base, retained_after_gc=cur_gc-base, peak=peak-base,
                                  temporary_encoding_work=peak-cur,
                                  tracemalloc_own_memory=tracemalloc.get_tracemalloc_memory())
    out['budget'] = b.work_budget.statistics()
    out['instrument'] = inst.report()
    out['formula'] = formula_booking(b)
    out['counts'] = counts(b)
    if root is not None:
        out['exact'] = dict(sha256_match=b.digest.hexdigest() == raw_sha, length_match=b.length == raw_len)
    snap = tracemalloc.take_snapshot()
    stats = snap.statistics('lineno')
    out['retained_by_allocation_site'] = [
        dict(site=f'{Path(s.traceback[0].filename).name}:{s.traceback[0].lineno}', bytes=s.size, blocks=s.count)
        for s in stats[:30]]
    del snap, stats
    tables = table_sizes(b)
    out['deep_tables'] = tables
    out['deep_groups'] = group(tables)
    out['unattributed_retained'] = out['tracemalloc_add']['retained_after_gc']-tables['total_new']
    if root is not None and do_finish:
        gc.collect()
        tracemalloc.reset_peak()
        f0, _ = tracemalloc.get_traced_memory()
        booked0 = b.work_budget.reserved_bytes
        metadata, arrays = b.finish(root, schema)
        f1, fp = tracemalloc.get_traced_memory()
        bytearray_capacity = {}
        for name in ('token.bytes', 'int.bytes'):
            owner = arrays[name].base
            while owner is not None and not isinstance(owner, (bytes, bytearray)) and hasattr(owner, 'obj'):
                owner = owner.obj
            bytearray_capacity[name] = dict(nbytes=int(arrays[name].nbytes),
                                            owner_type=type(owner).__name__,
                                            owner_sizeof=sys.getsizeof(owner) if owner is not None else None)
        out['finish'] = dict(
            arrays=len(arrays), array_nbytes=sum(int(a.nbytes) for a in arrays.values()),
            per_array={k: dict(dtype=a.dtype.str, shape=list(a.shape), nbytes=int(a.nbytes))
                       for k, a in arrays.items()},
            metadata_bytes=len(metadata), tracemalloc_retained=f1-f0, tracemalloc_peak_above_start=fp-f0,
            transient_above_end=fp-f1, booked_before=booked0, booked_after=b.work_budget.reserved_bytes,
            finish_hold_requested=inst.requested.get('finish', 0), budget_peak=b.work_budget.peak_reserved_bytes,
            bytearray_capacity=bytearray_capacity)
        del metadata, arrays
    del b, inst, root
    gc.collect()
    end, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.enable()
    out['released'] = dict(run_budget_reserved_before=rb0, run_budget_reserved_after=scope.run_budget.reserved_bytes,
                           traced_residual_after_release=end-base)
    return out


# ------------------------------------------------------------------- slices

def plan_slices(graph):
    receipts = graph[REC]
    keys = sorted(receipts)
    base = {k: v for k, v in graph.items() if k != REC and (v is None or type(v) in (str, int, float, bool))}
    rest = {k: v for k, v in graph.items() if k != REC}
    row = [len(canonical(k))+1+len(canonical(receipts[k])) for k in keys]
    cumulative, total = [], 0
    for size in row:
        total += size
        cumulative.append(total)
    base_bytes = len(canonical(base))
    wrapper = 1+len(canonical(REC))+1+2   # comma, key, colon, braces

    def predicted(n):
        return base_bytes+wrapper+(cumulative[n-1]+n-1 if n else 0)

    chosen = []
    for target in TARGETS:
        lo, hi = 1, len(keys)
        while lo < hi:
            mid = (lo+hi+1)//2
            if predicted(mid) <= target:
                lo = mid
            else:
                hi = mid-1
        chosen.append((target, lo))
    # Canonical prefix bytes before the receipts value in the whole graph.
    prefix = 1
    for k in sorted(graph):
        if k == REC:
            prefix += len(canonical(k))+1
            break
        prefix += len(canonical(k))+1+len(canonical(graph[k]))+1
    key_lengths = Counter(len(k) for k in keys)
    info = dict(receipt_rows=len(keys), receipt_row_canonical_bytes_total=total,
                receipt_row_bytes_mean=total/len(keys), receipt_key_length_histogram=dict(key_lengths),
                receipt_keys_all_64_hex=all(len(k) == 64 and all(c in '0123456789abcdef' for c in k) for k in keys),
                scalar_base_fields=sorted(base), scalar_base_canonical_bytes=base_bytes,
                non_receipt_fields=len(rest), canonical_prefix_bytes_before_receipts_value=prefix,
                chosen=[dict(target=t, rows=n, predicted_bytes=predicted(n)) for t, n in chosen])
    return keys, base, rest, chosen, info


def make_slice(base, receipts, keys, n):
    value = dict(base)
    value[REC] = {k: receipts[k] for k in keys[:n]}
    return value


# --------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true', help='one small slice only; result-quick.json')
    args = parser.parse_args()
    result_path = HERE/('result-quick.json' if args.quick else 'result.json')
    result = dict(schema='atlas.step8.builder-probe.v1', status='RUNNING', quick=args.quick,
                  python=sys.version, platform=platform.platform(),
                  openblas_num_threads=os.environ.get('OPENBLAS_NUM_THREADS'),
                  labels=dict(measured='tracemalloc / sys.getsizeof / psutil / WorkBudget statistics on this host',
                              extrapolated='linear fits from measured slices; marked in projection',
                              probe_uncapped='phase D raises record_tables.MAX_BUILD_BYTES in-process only'),
                  notes=['gc disabled during decode and builder phases (as measure_live_capacity.workload)',
                         'no timing is taken while tracemalloc runs',
                         'RSS/private deltas are allocator-level and noisy; tracemalloc is the primary measure'])

    def save():
        tmp = result_path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(result, indent=1, sort_keys=True, default=str)+'\n', encoding='utf8')
        os.replace(tmp, result_path)

    result['sources_before'] = {name: file_sha(path) for name, path in SOURCES.items()}
    census_raw = CENSUS.read_bytes()
    if sha256(census_raw).hexdigest() != CENSUS_SHA256:
        raise SystemExit('census sha256 differs')
    expected = json.loads(census_raw)['census']['records']['spatial-record:graph']
    del census_raw
    import mesh_tables as M
    import record_tables as RT
    from atlas_tectonics.resources import MemoryLimitError, WorkBudget
    from compact_contracts import ContractError
    from content_cache import create_retained_scope
    import numpy
    result['versions'] = dict(numpy=numpy.__version__, psutil=psutil.__version__)
    verify_hold_sites(RT)
    errors = (MemoryLimitError, ContractError)
    result['builder_constants'] = dict(MAX_BUILD_BYTES=RT.MAX_BUILD_BYTES, CHUNK=RT.CHUNK,
                                       MAX_ROW_WORK_BYTES=RT.MAX_ROW_WORK_BYTES, MAX_ITEMS=RT.MAX_ITEMS)

    av = available()
    result['available_at_start'] = av
    if av < MIN_AVAILABLE:
        result['status'] = 'STOPPED_LOW_MEMORY'
        save()
        raise SystemExit('available memory below 6 GiB before loading the graph')
    raw = GRAPH.read_bytes()
    raw_sha = sha256(raw).hexdigest()
    result['input'] = dict(path=str(GRAPH), bytes=len(raw), sha256=raw_sha,
                           census_sha256=expected['sha256'], census_filebytes=expected['filebytes'],
                           authenticated=raw_sha == expected['sha256'] and len(raw) == expected['filebytes'])
    if not result['input']['authenticated']:
        result['status'] = 'STOPPED_INPUT_MISMATCH'
        save()
        raise SystemExit('graph bytes differ from census')
    log('input authenticated', len(raw))

    decode = result['decode'] = {}
    if not args.quick:
        t0 = time.perf_counter()
        charge = M._decode_charge(raw)
        decode['full_charge'] = dict(charge_bytes=charge, seconds=time.perf_counter()-t0,
                                     raw_charge_bytes_in_workload=65536+2*len(raw))
        log('decode charge', charge)
    graph, full_rss = decode_untraced(raw)
    decode['full_untraced'] = full_rss
    log('full decode rss delta', full_rss['delta'])
    if len(graph[REC]) != 48391:
        raise SystemExit('receipt inventory differs')
    schema = graph['schema']

    keys, base, rest, chosen, slice_info = plan_slices(graph)
    result['slice_plan'] = slice_info
    log('slices', slice_info['chosen'], 'prefix', slice_info['canonical_prefix_bytes_before_receipts_value'])
    receipts = graph[REC]
    if args.quick:
        chosen = [chosen[0]]
    slices = []
    for target, n in chosen:
        slices.append(dict(name=f'A{target//1_000_000}MB', family='A: scalar top-level fields + first N receipts (sorted keys)',
                           rows=n, target=target))
    if not args.quick:
        slices.append(dict(name='B-nonreceipt', family='B: all 58 non-receipt top-level fields, no receipts', rows=0,
                           target=None))
    result['slices'] = slices
    save()

    def slice_value(s):
        if s['name'] == 'B-nonreceipt':
            return rest
        if s['family'].startswith('L'):
            value = dict(rest)
            value[REC] = {k: receipts[k] for k in keys[:s['rows']]}
            return value
        return make_slice(base, receipts, keys, s['rows'])

    # Untraced per-slice decode (before heap churn of the traced full copy).
    for s in slices:
        raw_slice = canonical(slice_value(s))
        s['canonical_bytes'] = len(raw_slice)
        s['sha256'] = sha256(raw_slice).hexdigest()
        s['decode_charge'] = M._decode_charge(raw_slice)
        decoded, rss = decode_untraced(raw_slice)
        s['decode_untraced'] = rss
        s['decode_deep_sizeof'] = deep_json(decoded)
        del decoded, raw_slice
        gc.collect()
        log('slice decode untraced', s['name'], s['canonical_bytes'], rss['delta'])
    save()

    if not args.quick:
        decode['full_deep_sizeof'] = deep_json(graph)
        gc.collect()
        log('full deep sizeof', decode['full_deep_sizeof']['bytes'])
        av = available()
        if av < MIN_AVAILABLE:
            decode['full_traced'] = dict(skipped=f'available {av} < 6 GiB')
        else:
            decode['full_traced'] = decode_traced(raw)
            log('full decode traced', decode['full_traced']['retained_bytes'])
        full = decode['full_traced'].get('retained_bytes')
        decode['full_ratios'] = dict(
            charge_over_tracemalloc=None if not full else decode['full_charge']['charge_bytes']/full,
            charge_over_rss_delta=decode['full_charge']['charge_bytes']/max(1, full_rss['delta']['rss']),
            charge_over_private_delta=decode['full_charge']['charge_bytes']/max(1, full_rss['delta'].get('private') or 1),
            charge_over_deep_sizeof=decode['full_charge']['charge_bytes']/decode['full_deep_sizeof']['bytes'])
        for s in slices:
            raw_slice = canonical(slice_value(s))
            s['decode_traced'] = decode_traced(raw_slice)
            s['decode_charge_over_tracemalloc'] = s['decode_charge']/s['decode_traced']['retained_bytes']
            del raw_slice
        save()

    budget = WorkBudget(16 << 30)
    scope = create_retained_scope(budget, process_epoch='step8-builder-probe')
    result['scope'] = dict(run_budget_max=budget.max_bytes, run_budget_reserved_initial=budget.reserved_bytes)

    def measure(s, *, do_finish=True):
        value = slice_value(s)
        raw_slice = canonical(value)
        raw_sha_s, raw_len = sha256(raw_slice).hexdigest(), len(raw_slice)
        del raw_slice
        s['untraced'] = run_untraced(value, raw_sha_s, raw_len, scope, schema, RT, errors, do_finish=do_finish)
        log('builder untraced', s['name'], 'refused' if 'refusal' in s['untraced'] else 'ok',
            round(s['untraced']['add_seconds'], 2), s['untraced']['budget_after_add']['peak_reserved_bytes'])
        s['traced'] = run_traced(value, raw_sha_s, raw_len, scope, schema, RT, errors, do_finish=do_finish)
        log('builder traced', s['name'], s['traced']['tracemalloc_add']['retained_after_gc'],
            s['traced']['budget']['peak_reserved_bytes'])
        save()

    for s in slices:
        measure(s)
    save()

    # Literal slices (non-receipt fields + first N receipts), only if B fits under the cap.
    if not args.quick:
        b_ok = 'refusal' not in slices[-1]['untraced']
        literal = []
        if b_ok and elapsed() < 11*60:
            for target, n in chosen[:3:2]:
                s = dict(name=f'L+A{target//1_000_000}MB-rows', family='L: all non-receipt fields + first N receipts',
                         rows=n, target=None)
                raw_slice = canonical(slice_value(s))
                s['canonical_bytes'] = len(raw_slice)
                del raw_slice
                measure(s)
                literal.append(s)
                if 'refusal' in s['untraced']:
                    break
        result['literal_slices'] = literal if literal else dict(
            skipped='B refused under the real cap' if not b_ok else 'runtime gate')
        save()

    # Phase D: whole authentic graph, cap raised in-process only (probe device).
    if not args.quick:
        whole = result['whole_graph_uncapped'] = dict(
            label='PROBE ONLY: record_tables.MAX_BUILD_BYTES raised in-process to observe would-be booking; '
                  'not a shipped or proposed limit', probe_cap=PROBE_UNCAPPED_BYTES)
        if elapsed() > 15*60 or available() < MIN_AVAILABLE:
            whole['skipped'] = f'gate: elapsed {elapsed():.0f}s, available {available()}'
        else:
            original_cap = RT.MAX_BUILD_BYTES
            RT.MAX_BUILD_BYTES = PROBE_UNCAPPED_BYTES
            try:
                whole['untraced'] = run_untraced(graph, raw_sha, len(raw), scope, schema, RT, errors)
                log('whole untraced', whole['untraced']['add_seconds'],
                    whole['untraced']['budget_after_add']['peak_reserved_bytes'])
                save()
                estimate = 4*(whole['untraced']['add_seconds']+whole['untraced'].get('finish', {}).get('seconds', 0))
                if elapsed()+estimate+90 > RUNTIME_LIMIT or available() < MIN_AVAILABLE:
                    whole['traced'] = dict(skipped=f'gate: elapsed {elapsed():.0f}s, 4x untraced estimate {estimate:.0f}s')
                else:
                    whole['traced'] = run_traced(graph, raw_sha, len(raw), scope, schema, RT, errors)
                    log('whole traced', whole['traced']['tracemalloc_add']['retained_after_gc'])
            finally:
                RT.MAX_BUILD_BYTES = original_cap
            whole['cap_restored'] = RT.MAX_BUILD_BYTES == original_cap
        save()

    scope.close()
    result['sources_after'] = {name: file_sha(path) for name, path in SOURCES.items()}
    result['sources_unchanged'] = result['sources_after'] == result['sources_before']
    result['input_sha256'] = raw_sha
    result['process_peak_wset'] = mem()['peak_wset']
    result['elapsed_seconds_total'] = elapsed()
    result['status'] = 'COMPLETE'
    save()
    log('done', result_path)


if __name__ == '__main__':
    main()
