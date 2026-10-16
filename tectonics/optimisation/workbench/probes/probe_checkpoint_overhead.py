"""Q1: per-query endpoint-checkpoint verification overhead (Wave 0 probe).

No source edits. The parent proves the endpoint-checkpoint candidate is exactly
I runtime-src plus the reviewed seam/companion, counts interval-1 endpoint
component-volume queries from r9 JSON artifacts (never the sqlite), then times
the strict checks in ONE fresh PYTHONHASHSEED=0 child with no profile or trace
hook. Projection is the plan's 3 x check x queries; a measured result never
changes a guard, quota or the checkpoint module.

W2-K options: --candidate/--manifest name a candidate directory and manifest
under endpoint-checkpoints (default: the Q1 ones); --output names a NEW file
(an existing output, including Q1's checkpoint-overhead.json, is refused, never
overwritten); --baseline adds a before/after comparison against an earlier
output, read only; --label sets the record's package name.
"""
import sys
sys.dont_write_bytecode = True  # never leave bytecode beside frozen sources

from datetime import datetime, timezone
from fractions import Fraction as Q
import gc
import gzip
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
from time import perf_counter, perf_counter_ns


HERE = Path(__file__).resolve().parent
R = HERE.parent
O = R.parent
T = O.parents[2]
H = O.parents[1] / 'heat-repair-20261007'
E = R / 'endpoint-checkpoints'
I = O / 'runtime-integration-r1'
ORIGINAL = I / 'runtime-src' / 'atlas_tectonics'
CANDIDATE = E / 'candidate-src' / 'atlas_tectonics'
ARTIFACTS = H / 'heat-original-connected-20261013-r9.artifacts'
PARALLEL = ARTIFACTS / 'differential-parallel-01.json'
PROPOSAL = ARTIFACTS / 'differential-proposal-01.json'
BOUNDS = ARTIFACTS / 'preadvance-bounds.json.gz'
MESH = ARTIFACTS / 'preadvance-mesh.json.gz'
RUN_RECORD = H / 'heat-original-connected-20261013-r9.json'
LATER_PROPOSAL = H / 'heat-original-continued-20261013-r4.artifacts' / 'differential-proposal-02.json'
OUTPUT = HERE / 'checkpoint-overhead.json'
SCRATCH = T / '_t' / 'q1'
SEAM = ('integration_component_volume_batch.py', 'integration_differential_geometry.py',
        'integration_endpoint_checkpoints.py')
CALLS = 20
GEOMETRY_PHASE_S = 3*3600
THRESHOLD_FRACTION = 0.10
CHILD_HEADROOM_BYTES = 1 << 30   # child imports numpy/scipy; keep the 1 GiB machine floor intact
MARK = 'Q1-RESULT '
KEYS = ('a'*64, 'b'*64)


class ProbeRefused(RuntimeError):
    """An input differs from the stated measurement scope; nothing is projected."""


def require(condition, message):
    if not condition:
        raise ProbeRefused(message)


def _file_sha(path):
    digest = sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _digests(root):
    return {'/'.join(p.relative_to(root).parts): sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*.py'))}


def verify_candidate(candidate_package=CANDIDATE, manifest_path=E/'candidate-manifest.json'):
    # The tests import candidate-src; prove it IS I runtime-src + the seam, by
    # re-deriving the seam from the frozen bytes rather than trusting the manifest.
    original, candidate = _digests(ORIGINAL), _digests(candidate_package)
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    spec = importlib.util.spec_from_file_location('q1_patch_endpoint_seam', E/'patch_endpoint_seam.py')
    seam = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seam)
    derived = {name: text.encode('utf8') for name, text in seam.candidate_sources(ORIGINAL).items()}
    require(tuple(sorted(derived)) == tuple(sorted(SEAM)), 'endpoint seam output set differs')
    require(manifest['original_sources'] == original, 'I runtime-src differs from the candidate manifest')
    require(set(candidate) == set(original) | set(derived), 'candidate membership is not I runtime-src plus seam')
    for name, digest in candidate.items():
        expected = sha256(derived[name]).hexdigest() if name in derived else original[name]
        require(digest == expected, 'candidate source differs from I runtime-src plus seam: '+name)
    require(manifest['changed_sources'] == {name: candidate[name] for name in derived},
            'candidate manifest changed_sources differ')
    companion = _file_sha(E/'integration_endpoint_checkpoints.py')
    require(candidate['integration_endpoint_checkpoints.py'] == companion, 'companion differs from candidate copy')
    return dict(original_files=len(original), candidate_files=len(candidate),
        original_inventory_sha256=sha256(json.dumps(original, sort_keys=True).encode()).hexdigest(),
        candidate_inventory_sha256=sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest(),
        candidate_bytes=sum(p.stat().st_size for p in candidate_package.rglob('*.py')),
        seam_sha256={name: candidate[name] for name in SEAM}, companion_sha256=companion,
        patch_endpoint_seam_sha256=_file_sha(E/'patch_endpoint_seam.py'),
        candidate=str(candidate_package), manifest=str(manifest_path),
        manifest_sha256=_file_sha(manifest_path))


def _cells(path, block=1 << 20):
    """Stream the leading canonical cells array; later fields are never decoded."""
    decoder, prefix = json.JSONDecoder(), '{"cells":['
    with gzip.open(path, 'rt', encoding='utf8', newline='') as source:
        buffer = source.read(block)
        require(buffer.startswith(prefix), 'ALE bounds record must begin with its cells array')
        at, item, first = len(prefix), True, True
        while True:
            if at >= len(buffer):
                more = source.read(block)
                require(more, 'ALE bounds cells array is truncated')
                buffer, at = more, 0
            char = buffer[at]
            if not item:
                if char == ']':
                    return
                require(char == ',', 'non-canonical separator in ALE bounds cells')
                at, item = at+1, True
                continue
            if char == ']' and first:
                return
            require(char == '{', 'ALE bounds cell is not an object')
            try:
                cell, end = decoder.raw_decode(buffer, at)
            except json.JSONDecodeError:
                more = source.read(block)
                require(more, 'ALE bounds cells array is truncated or malformed')
                buffer, at = buffer[at:]+more, 0
                continue
            yield cell
            at, item, first = end, False, False


def count_queries():
    parallel = json.loads(PARALLEL.read_text(encoding='utf8'))
    proposal = json.loads(PROPOSAL.read_text(encoding='utf8'))
    require(parallel['schema'] == 'atlas.interface-parallel-decision.v1' and parallel['sequence'] == 1,
            'differential-parallel-01 is not the first interface decision')
    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)
    # Neither named record carries an endpoint-query count; record that search.
    query_keys = sorted({k for record in (parallel, proposal) for k in keys(record) if 'quer' in k.lower()})
    counts = dict(exterior=0, exterior_with_parent=0, exterior_births=0, kinds={})
    seen = set()
    for cell in _cells(BOUNDS):
        require(cell['cell_id'] not in seen, 'duplicate ALE bounds cell')
        seen.add(cell['cell_id'])
        kind = str(cell.get('kind'))
        counts['kinds'][kind] = counts['kinds'].get(kind, 0)+1
        if kind == 'exterior':
            require({'start_volume_bounds_m3', 'end_volume_bounds_m3', 'parent_cell_id'} <= cell.keys(),
                    'exterior cell lacks endpoint bounds')
            counts['exterior'] += 1
            counts['exterior_births' if cell['parent_cell_id'] is None else 'exterior_with_parent'] += 1
    with gzip.open(MESH, 'rt', encoding='utf8', newline='') as source:
        head = source.read(1 << 16)
    marker = '"booked_cell_rule":'
    require(head.count(marker) == 1, 'mesh booked_cell_rule not found once in its head')
    rule, _ = json.JSONDecoder().raw_decode(head, head.index(marker)+len(marker))
    mesh_components = rule['booked_components']+rule['components_without_booked_material']
    run = json.loads(RUN_RECORD.read_text(encoding='utf8'))
    phases = run['phases']
    names = [phase['name'] for phase in phases]
    require(names.count('actual-differential-geometry') == 1, 'r9 geometry phase is not unique')
    at = names.index('actual-differential-geometry')
    later = json.loads(LATER_PROPOSAL.read_text(encoding='utf8'))
    # ALE endpoint loop: every exterior component measures 'end'; only a carried
    # parent also measures 'start' (births are exactly zero, no query).
    queries = counts['exterior']+counts['exterior_with_parent']
    observations = parallel['observations']
    return dict(
        completed_component_volume_queries=queries,
        derivation='exterior cells (one end query each) + exterior cells with a parent (one start query each), '
                   'streamed from the interval-1 ALE bounds record; only the exterior component loop calls '
                   'component_volume_bounds, other cell kinds issue none; every retained endpoint row is met '
                   '(an unmet row raises), so each is a completed, writable entry',
        cell_counts=counts, unique_cell_ids=len(seen),
        mesh_cross_check=dict(booked_components=rule['booked_components'],
            components_without_booked_material=rule['components_without_booked_material'],
            total_components=mesh_components, matches_exterior=mesh_components == counts['exterior'],
            closed_graph_id=rule['closed_graph_id']),
        named_records=dict(
            query_count_keys_found=query_keys,
            endpoint_volumes_phase_seconds=observations['phases']['endpoint-volumes'],
            phases_seconds=observations['phases'],
            wall_contacts=observations['walls']['count'],
            interface_integrator=observations['interfaces']['integrator']['count'],
            interface_shortcut=observations['interfaces']['shortcut']['count'],
            route=parallel['route'], reason=parallel['reason'],
            instrumentation_gate=[g for g in parallel['gates'] if g['gate'] == 'instrumentation'],
            directed_query_upper_bound=proposal['directed_query_upper_bound'],
            proposal_stage=proposal['stage'], proposal_attempt=proposal['proposal']['attempt'],
            proposal_interval_id=proposal['proposal']['interval_id'],
            note='neither named record contains a per-query endpoint count; directed_query_upper_bound is '
                 'a directed-face query bound, not endpoint component-volume queries'),
        interval1_geometry_phase_seconds=phases[at+1]['seconds']-phases[at]['seconds'],
        interval1_geometry_phase=dict(start=phases[at], next=phases[at+1], status=run['status']),
        interval2_directed_query_upper_bound=later['directed_query_upper_bound'],
        files={str(path): _file_sha(path) for path in
               (PARALLEL, PROPOSAL, BOUNDS, MESH, RUN_RECORD, LATER_PROPOSAL)})


def _seconds(function, calls):
    out = []
    for _ in range(calls):
        begun = perf_counter_ns()
        function()
        out.append((perf_counter_ns()-begun)/1e9)
    return out


def child(scratch, root=E/'candidate-src'):
    """Fresh-process timings. Only the tests' own import route is used."""
    started = perf_counter()
    require(sys.getprofile() is None and sys.gettrace() is None, 'a profile/trace hook is installed')
    require(root.parent == E, 'candidate root must be a directory under endpoint-checkpoints')
    sys.path[:0] = [str(root), str(I/'helpers'), str(I/'ram'), str(H)]
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import reuse
    from atlas_tectonics.integration_component_volume_batch import ComponentVolumeQueries
    from atlas_tectonics.integration_endpoint_checkpoints import EndpointCheckpoints
    from atlas_tectonics.integration_parallel_binding import capture_runtime, canonical
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext
    imported = perf_counter()-started
    require(Path(G.__file__).resolve().parent == (root/'atlas_tectonics').resolve(),
            'atlas_tectonics did not load from the named candidate')
    require(reuse.execution_mode() == 'strict', 'strict execution mode required')
    try:
        import psutil
        process = psutil.Process()
    except ImportError:
        psutil = process = None

    def fixture(budget, index):
        # The endpoint-checkpoint test fixture; only the plane offset varies so
        # each index issues distinct support bytes (a distinct key, a real miss).
        box = V.CartesianCell((Q(-1, 10), 9, Q(-1, 10)), (Q(1, 10), Q(46, 5), Q(1, 10)), budget=budget)
        layer = V.RadialLayer(10, 0, 3, budget=budget)
        value = dict(voxel=box.record(), radial_layer=layer.record(),
            duration_s=G._qtext(Q(1)), start_time_s=G._qtext(Q(0)), end_time_s=G._qtext(Q(1)),
            constraints={'cut': dict(kind='fixed-plane', normal=G._store_vec((1, 0, 0)),
                                    offset=G._qtext(Q(index, 2000)))},
            components=[dict(logical_cell_id=key, parent_cell_id=key, constraints=[['cut', sign]], partition_path=[])
                        for key, sign in zip(KEYS, (1, -1), strict=True)])
        return G._issue(G.DifferentialSupport, value, budget)

    def measure(support, budget, store=None):
        with ComponentVolumeQueries(support, budget=budget) as queries:
            return queries.measure(KEYS[0], endpoint='end', max_width_m3=Q(1), max_leaves=1,
                                   positive_witness=True, _checkpoint=store)

    def counted(store):
        calls, original = [0], store._check
        def check():
            calls[0] += 1
            return original()
        store._check = check
        return calls

    result = dict(imported_seconds=imported, backends={}, python=sys.version, executable=sys.executable,
                  pid=os.getpid(), flags=dict(dont_write_bytecode=sys.dont_write_bytecode,
                  hash_randomization=sys.flags.hash_randomization), env={k: os.environ.get(k) for k in
                  ('PYTHONHASHSEED', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')},
                  candidate_module=str(Path(G.__file__).resolve()),
                  available_ram_start=None if psutil is None else psutil.virtual_memory().available)
    contexts = []
    try:
        # 'scipy' is the backend run_prepared_restart uses; 'reference' is the tests'.
        for backend in ('scipy', 'reference'):
            begun = perf_counter()
            context = ExecutionContext(backend)
            contexts.append(context)
            row = dict(context_capture_seconds=perf_counter()-begun,
                       runtime_canonical_bytes=len(canonical(capture_runtime(context))))
            row['capture_runtime_warmup'] = _seconds(lambda context=context: capture_runtime(context), 1)
            row['capture_runtime'] = _seconds(lambda context=context: capture_runtime(context), CALLS)
            row['source_bytes'] = _seconds(reuse._source_bytes, CALLS)
            row['verify_boundary'] = _seconds(context.verify_boundary, CALLS)
            budget = WorkBudget(64 << 20, max_predicate_work_units=1000000)
            directory = Path(tempfile.mkdtemp(prefix=backend[:3]+'-', dir=scratch))
            begun = perf_counter()
            with EndpointCheckpoints(directory, context=context, budget=budget) as store:
                row['store_enter_seconds'] = perf_counter()-begun
                row['check_warmup'] = _seconds(store._check, 1)
                row['check'] = _seconds(store._check, CALLS)
            # End-to-end tiny real queries: baseline (no store), misses, then hits.
            supports = [fixture(budget, index) for index in range(CALLS)]
            baseline, misses, hits, digests = [], [], [], []
            for support in supports:
                begun = perf_counter_ns()
                raw = measure(support, budget)._json
                baseline.append((perf_counter_ns()-begun)/1e9)
                digests.append(sha256(raw).hexdigest())
            with EndpointCheckpoints(directory, context=context, budget=budget) as store:
                for support, digest in zip(supports, digests, strict=True):
                    begun = perf_counter_ns()
                    raw = measure(support, budget, store)._json
                    misses.append((perf_counter_ns()-begun)/1e9)
                    require(sha256(raw).hexdigest() == digest, 'miss bytes differ from baseline')
                require((store.misses, store.written, store.hits, store.incomplete) == (CALLS, CALLS, 0, 0),
                        'tiny misses did not all complete and publish')
                store_bytes = store._used
            with EndpointCheckpoints(directory, context=context, budget=budget) as store:
                for support, digest in zip(supports, digests, strict=True):
                    begun = perf_counter_ns()
                    raw = measure(support, budget, store)._json
                    hits.append((perf_counter_ns()-begun)/1e9)
                    require(sha256(raw).hexdigest() == digest, 'hit bytes differ from baseline')
                require((store.hits, store.written) == (CALLS, 0), 'tiny reopen did not hit every entry')
            # Separate untimed pass: actual _check calls per miss and per hit.
            counting = Path(tempfile.mkdtemp(prefix=backend[:3]+'-n-', dir=scratch))
            support = fixture(budget, 40)
            with EndpointCheckpoints(counting, context=context, budget=budget) as store:
                calls = counted(store)
                measure(support, budget, store)
                require(store.written == 1, 'counting miss did not publish')
                per_miss = calls[0]
            with EndpointCheckpoints(counting, context=context, budget=budget) as store:
                calls = counted(store)
                measure(support, budget, store)
                require(store.hits == 1, 'counting reopen did not hit')
                per_hit = calls[0]
            supports = support = store = None
            gc.collect()
            require(budget.reserved_bytes == 0 and budget.statistics()['predicate_work']['reserved_units'] == 0,
                    'probe budget retained a reservation')
            row.update(query_baseline=baseline, query_miss=misses, query_hit=hits, result_sha256=digests,
                       checks_per_miss=per_miss, checks_per_hit=per_hit, miss_entry_bytes=store_bytes/CALLS,
                       final_reserved_bytes=budget.reserved_bytes,
                       peak_logical_bytes=budget.statistics()['peak_reserved_bytes'])
            result['backends'][backend] = row
    finally:
        for context in contexts:
            context.close()
    if process is not None:
        info = process.memory_info()
        result.update(rss_end=info.rss, peak_working_set=getattr(info, 'peak_wset', None),
                      available_ram_end=psutil.virtual_memory().available)
    result['child_seconds'] = perf_counter()-started
    print(MARK+json.dumps(result), flush=True)


def _summary(values):
    return dict(median=statistics.median(values), minimum=min(values), maximum=max(values), count=len(values))


def _options(argv):
    import argparse
    parser = argparse.ArgumentParser(description='endpoint-checkpoint verification overhead probe')
    parser.add_argument('--output', type=Path, default=OUTPUT, help='new result file; never overwritten')
    parser.add_argument('--candidate', default='candidate-src', help='candidate directory name under '+str(E))
    parser.add_argument('--manifest', default='candidate-manifest.json', help='its manifest name under '+str(E))
    parser.add_argument('--baseline', type=Path, default=None, help='earlier probe output to compare (read only)')
    parser.add_argument('--label', default='q1', help='package name recorded in the output')
    options = parser.parse_args(argv)
    for name in (options.candidate, options.manifest):
        require(Path(name).name == name and name not in ('', '.', '..'), 'candidate/manifest must be plain names')
    options.output = Path(os.path.abspath(options.output))
    require(not options.output.exists(), 'output exists; refusing to overwrite '+str(options.output))
    require(options.baseline is None or options.baseline.is_file(), 'baseline output not found')
    return options


def _comparison(baseline, decided, queries, scale):
    """Before (earlier output) and after (this run); also both counts at THIS run's check cost."""
    text = baseline.read_bytes()
    base = json.loads(text)
    require(base.get('schema') == 'private.q1-checkpoint-overhead.v1', 'baseline is not a probe output')
    prior = base['projection'][base['decision']['backend']]
    def side(row):
        check = row['median_check_seconds']
        return dict(median_check_seconds=check, checks_per_miss=row['checks_per_miss_measured'],
            checks_per_hit=row['checks_per_hit_measured'],
            miss_check_seconds_per_query=row['checks_per_miss_measured']*check,
            hit_check_seconds_per_query=row['checks_per_hit_measured']*check,
            end_to_end_miss_overhead_seconds_per_query=row['end_to_end_miss_overhead_seconds_per_query'],
            end_to_end_hit_seconds_per_query=row['end_to_end_hit_seconds_per_query'])
    before, after = side(prior), side(decided)
    check = after['median_check_seconds']   # removes run-to-run machine noise from the count change
    same = dict(before_miss_check_seconds_per_query=before['checks_per_miss']*check,
                after_miss_check_seconds_per_query=after['checks_per_miss']*check,
                before_hit_check_seconds_per_query=before['checks_per_hit']*check,
                after_hit_check_seconds_per_query=after['checks_per_hit']*check)
    saved_miss = same['before_miss_check_seconds_per_query']-same['after_miss_check_seconds_per_query']
    return dict(baseline=str(baseline), baseline_sha256=sha256(text).hexdigest(),
        baseline_package=base.get('package'), baseline_companion_sha256=base['sources']['companion_sha256'],
        backend=base['decision']['backend'], before=before, after=after, same_run_check_cost=same,
        queries=queries,
        projected_miss_check_seconds=dict(before=before['miss_check_seconds_per_query']*queries,
            after=after['miss_check_seconds_per_query']*queries,
            before_at_this_run_check=same['before_miss_check_seconds_per_query']*queries,
            after_at_this_run_check=same['after_miss_check_seconds_per_query']*queries,
            saved_at_this_run_check=saved_miss*queries),
        interval2_proxy=dict(scale=scale, before_at_this_run_check=same['before_miss_check_seconds_per_query']*queries*scale,
            after_at_this_run_check=same['after_miss_check_seconds_per_query']*queries*scale,
            note='UNMEASURED proxy (directed_query_upper_bound ratio), as in the decision block'))


def main(argv=()):
    options = _options(list(argv))
    output = options.output
    root = E/options.candidate
    begun = perf_counter()
    created = datetime.now(timezone.utc).isoformat()
    sources = verify_candidate(root/'atlas_tectonics', E/options.manifest)
    counted = count_queries()
    try:
        import psutil
        available = psutil.virtual_memory().available
    except ImportError:
        available = None
    require(available is None or available >= (1 << 30)+CHILD_HEADROOM_BYTES,
            'insufficient free memory for the probe child above the 1 GiB floor')
    SCRATCH.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONHASHSEED='0', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
               TMP=str(SCRATCH), TEMP=str(SCRATCH))
    with tempfile.TemporaryDirectory(prefix='run-', dir=SCRATCH) as scratch:
        command = [sys.executable, '-B', str(Path(__file__).resolve()), '--child', scratch, str(root)]
        launched = perf_counter()
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800, env=env, check=False)
        child_wall = perf_counter()-launched
    lines = [line for line in completed.stdout.splitlines() if line.startswith(MARK)]
    require(completed.returncode == 0 and len(lines) == 1,
            'probe child failed: '+str(completed.returncode)+' '+completed.stderr[-4000:])
    timings = json.loads(lines[0][len(MARK):])
    queries = counted['completed_component_volume_queries']
    threshold = THRESHOLD_FRACTION*GEOMETRY_PHASE_S
    summary, projection = {}, {}
    for backend, row in timings['backends'].items():
        stats = {name: _summary(row[name]) for name in
                 ('capture_runtime', 'check', 'source_bytes', 'verify_boundary',
                  'query_baseline', 'query_miss', 'query_hit')}
        check = stats['check']['median']
        miss_e2e = stats['query_miss']['median']-stats['query_baseline']['median']
        summary[backend] = stats
        projection[backend] = dict(
            median_check_seconds=check, median_capture_runtime_seconds=stats['capture_runtime']['median'],
            checks_per_miss_measured=row['checks_per_miss'], checks_per_hit_measured=row['checks_per_hit'],
            plan_miss_overhead_seconds=3*check*queries,
            measured_count_miss_overhead_seconds=row['checks_per_miss']*check*queries,
            hit_check_overhead_seconds=row['checks_per_hit']*check*queries,
            per_miss_check_seconds=3*check, per_hit_check_seconds=row['checks_per_hit']*check,
            end_to_end_miss_overhead_seconds_per_query=miss_e2e,
            end_to_end_miss_overhead_seconds=miss_e2e*queries,
            end_to_end_hit_seconds_per_query=stats['query_hit']['median'],
            end_to_end_all_hit_seconds=stats['query_hit']['median']*queries,
            fraction_of_3h_geometry=3*check*queries/GEOMETRY_PHASE_S,
            fraction_of_interval1_geometry=3*check*queries/counted['interval1_geometry_phase_seconds'],
            ratio_to_interval1_endpoint_phase=3*check*queries/counted['named_records']['endpoint_volumes_phase_seconds'])
    decided = projection['scipy']
    # The plan's formula decides; the other two are reported beside it, since
    # end-to-end also includes write/fsync costs that W2-K would not remove.
    exceeds = decided['plan_miss_overhead_seconds'] > threshold
    scale = counted['interval2_directed_query_upper_bound']/counted['named_records']['directed_query_upper_bound']
    record = dict(
        schema='private.q1-checkpoint-overhead.v1', package=options.label, created_utc=created,
        status='MEASURED', probe_sha256=_file_sha(Path(__file__)),
        options=dict(output=str(output), candidate=options.candidate, manifest=options.manifest,
                     baseline=None if options.baseline is None else str(options.baseline), label=options.label),
        method=dict(
            process='one fresh child: '+' '.join(command[:2])+' <probe> --child <scratch> <candidate>; '
                    'PYTHONHASHSEED=0, OMP/OPENBLAS threads 1 (the r9 binding values); no profile/trace hook (asserted)',
            imports=f'endpoint-checkpoint tests route: sys.path = {options.candidate}, I/helpers, I/ram, H; candidate '
                    'proven equal to I runtime-src plus patch_endpoint_seam.candidate_sources(I runtime-src)',
            timed=f'{CALLS} calls each after 1 recorded warm-up: capture_runtime(context), active '
                  'EndpointCheckpoints._check(), reuse._source_bytes(), context.verify_boundary(); then '
                  f'{CALLS} distinct tiny real endpoint queries: baseline without store, miss (write+fsync), '
                  'reopened hit; bytes compared; separate untimed pass counts _check calls per miss/hit',
            backends='scipy (run_prepared_restart.py ExecutionContext) decides; reference (tests) for comparison',
            projection='plan: 3 x median _check x interval-1 completed queries (misses); hits: measured checks '
                       'per hit x median _check x queries; also end-to-end (median miss - median baseline) x '
                       f'queries. Threshold {THRESHOLD_FRACTION:.0%} of a {GEOMETRY_PHASE_S} s geometry phase',
            clock='time.perf_counter_ns', statistic='median'),
        sources=sources, queries=counted, child=dict(command=command, returncode=completed.returncode,
            wall_seconds=child_wall, stderr_tail=completed.stderr[-4000:]),
        raw=timings, summary=summary, projection=projection,
        decision=dict(backend='scipy', threshold_seconds=threshold, queries=queries,
            plan_miss_overhead_seconds=decided['plan_miss_overhead_seconds'],
            exceeds_threshold=exceeds, w2k_scheduled=exceeds,
            fraction_of_threshold=decided['plan_miss_overhead_seconds']/threshold,
            break_even_queries=threshold/decided['per_miss_check_seconds'],
            note=('decided by the plan rule on interval-1 counts only; any interval-2 endpoint-query growth past '
                  'break_even_queries, or a larger composed source inventory, crosses the threshold'),
            measured_count_exceeds=decided['measured_count_miss_overhead_seconds'] > threshold,
            # The plan rule above assumes the Q1 3 checks per miss; this is the measured count.
            measured_count_miss_overhead_seconds=decided['measured_count_miss_overhead_seconds'],
            measured_count_fraction_of_threshold=decided['measured_count_miss_overhead_seconds']/threshold,
            end_to_end_exceeds=decided['end_to_end_miss_overhead_seconds'] > threshold,
            all_hit_check_exceeds=decided['hit_check_overhead_seconds'] > threshold,
            interval2_proxy=dict(scale=scale, plan_miss_overhead_seconds=decided['plan_miss_overhead_seconds']*scale,
                note='UNMEASURED proxy: ratio of directed_query_upper_bound (r4 interval 2 / r9 interval 1); '
                     'endpoint query counts for interval 2 are unknown')),
        caveats=[
            'Tiny-fixture query costs measure checkpoint mechanics, not production geometry cost per query.',
            ('The check walks all package sources and the loaded callable inventory; the composed runtime '
             '(R/composed-r1) may hold a different file count, so re-measure there if it differs materially.'),
            'Shared machine with parallel workers: timings include ambient contention; medians are reported.',
            ('The real parent may overlap checks with worker waits in automatic mode; the projection assumes '
             'the checks add serially to the parent critical path.'),
            ('Interval-1 count comes from the result record (unique exterior cells); the named parallel/proposal '
             'records hold no endpoint-query count.')],
        probe_seconds=perf_counter()-begun)
    if options.baseline is not None:
        record['comparison'] = _comparison(options.baseline, decided, queries, scale)
    partial = output.with_name(output.name+'.partial')
    with open(partial, 'x', encoding='utf8', newline='\n') as target:
        target.write(json.dumps(record, indent=2)+'\n')
    require(not output.exists(), 'output appeared during the probe; refusing to overwrite '+str(output))
    os.replace(partial, output)
    print(json.dumps(dict(queries=queries, median_check_s=decided['median_check_seconds'],
        checks_per_miss=decided['checks_per_miss_measured'], checks_per_hit=decided['checks_per_hit_measured'],
        measured_count_miss_overhead_s=decided['measured_count_miss_overhead_seconds'],
        plan_miss_overhead_s=decided['plan_miss_overhead_seconds'], threshold_s=threshold,
        w2k_scheduled=exceeds, output=str(output)), indent=2))


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--child':
        child(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        main(sys.argv[1:])
