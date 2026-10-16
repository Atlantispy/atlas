"""W4: per-query strict check cost on the COMPOSED source inventory (Q1/W2-K probe, re-pointed).

R/probes/probe_checkpoint_overhead.py (pinned, unchanged) only accepts candidate
directories under endpoint-checkpoints and proves them equal to I runtime-src plus
the seam. This wrapper reuses its unchanged child timing body, interval-1 query
census and before/after comparison by loading the module and, inside the fresh
composed child only, re-pointing the three globals its child uses for import roots:
E and I -> composed-r1 (root composed-r1/runtime-src; roots composed-r1/helpers and
/ram) and H -> H/source/tectonics/tests. That is exactly the composed layout, in
order, with no I helper or H root. The parent proves the inventory is the composed
manifest's, applies the probe's own projection formulas, compares with the W2-K
output (read only) and writes a NEW file.

Because the machine is shared, the W2-K candidate (candidate-w2k, verified by the
probe's own verify_candidate) is re-timed as a same-session CONTROL arm with the
probe child left exactly as W2-K ran it; arms alternate control, composed, control,
composed ... in separate fresh processes, and pooled samples per arm are compared.
After its timings each child also records a callable/constant inventory census per
package module (diagnostic attribution only; not part of the timed samples).
No sqlite is opened; the census of queries streams the r9/r4 JSON artifacts as Q1 did.

    python -B w4r_probe_overhead.py --output <new.json> [--rounds 2]
"""
import sys
sys.dont_write_bytecode = True

from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

import w4r_common as W


PROBE = W.R/'probes'/'probe_checkpoint_overhead.py'
PROBE_SHA256 = 'c18fada692d399bef7d6b2c3626ccd989d84d82e3c6ab55c1b59e09e33e572ea'
BASELINE = W.R/'probes'/'checkpoint-overhead-w2k.json'
BASELINE_SHA256 = '1f7e8ac89445bcff16d4c8655f90ae0c25b27e5e3bb4c2d84822fdff515cce1f'
Q1 = W.R/'probes'/'checkpoint-overhead.json'
Q1_SHA256 = 'c74a79203fd63b189078812278d721a0724c60f00333450aaa878686cb58167a'
CONTROL = W.E/'candidate-w2k'
CONTROL_MANIFEST = W.E/'candidate-manifest-w2k.json'
PROBE_CHILD_MINIMUM = 2 << 30     # the probe's own gate: 1 GiB floor + 1 GiB child headroom
AUDIT, CENSUS = 'W4_IMPORT_AUDIT ', 'W4_INVENTORY_CENSUS '
SAMPLES = ('capture_runtime', 'check', 'source_bytes', 'verify_boundary', 'query_baseline', 'query_miss', 'query_hit')
CENSUS_REPEATS = 5


def load_probe():
    W.require(W.file_sha(PROBE) == PROBE_SHA256, 'probe bytes differ from the pinned W2-K probe')
    spec = importlib.util.spec_from_file_location('probe_checkpoint_overhead', PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def census(backend='scipy'):
    """Per package module: tokens, registered-constant bytes and the cost of re-deriving them."""
    from atlas_tectonics import reuse
    modules = reuse._identity_modules(backend)
    rows = []
    for name in modules:
        begun = time.perf_counter_ns()
        for _ in range(CENSUS_REPEATS):
            _, tokens, constants = reuse._callable_inventory(backend, (name,))
        rows.append(dict(module=name, seconds=(time.perf_counter_ns()-begun)/1e9/CENSUS_REPEATS,
                         tokens=len(tokens), constant_bytes=len(constants)))
    total = sum(r['seconds'] for r in rows)
    rows.sort(key=lambda r: -r['seconds'])
    return dict(backend=backend, modules=len(rows), tokens=sum(r['tokens'] for r in rows),
                constant_bytes=sum(r['constant_bytes'] for r in rows), seconds_sum=total,
                per_module={r['module']: [r['seconds'], r['tokens'], r['constant_bytes']] for r in rows},
                top=rows[:15])


def child(arm, scratch, root):
    probe = load_probe()
    if arm == 'composed':
        W.require(Path(root) == W.NATIVE, 'the composed runtime-src is the only measured root')
        probe.E, probe.I, probe.H = W.RC, W.RC, W.H_TESTS      # sys.path: runtime-src, helpers, ram, H tests
    else:
        W.require(arm == 'control' and Path(root) == CONTROL, 'control arm is candidate-w2k exactly as W2-K ran it')
    probe.child(Path(scratch), Path(root))
    print(CENSUS+json.dumps(census(), sort_keys=True), flush=True)
    if arm == 'composed':
        audit = W.import_audit(sys.modules, harness_files=(PROBE,))
        print(AUDIT+json.dumps(audit, sort_keys=True), flush=True)
        return 3 if audit['violations'] else 0
    return 0


def composed_inventory():
    manifest = W.manifest()
    package = W.NATIVE/'atlas_tectonics'
    actual = W.native_hashes(package)
    W.require(actual == manifest['source_hashes'], 'composed runtime-src differs from the manifest')
    W.require(actual['atlas_tectonics/integration_endpoint_checkpoints.py'] == W.COMPANION_SHA256
              == W.file_sha(W.E/'integration_endpoint_checkpoints.py'), 'companion differs from the W2-K pin')
    w2k = W.native_hashes(CONTROL/'atlas_tectonics')
    size = lambda folder: sum(p.stat().st_size for p in folder.rglob('*.py'))
    return dict(root=str(W.NATIVE), files=len(actual), bytes=size(package),
                native_source_digest=sha256(W.canonical(actual)).hexdigest(),
                manifest_sha256=W.MANIFEST_SHA256, companion_sha256=W.COMPANION_SHA256,
                w2k_candidate_files=len(w2k), w2k_candidate_bytes=size(CONTROL/'atlas_tectonics'),
                differs_from_w2k_candidate=sorted(k for k in actual if w2k.get(k) != actual[k]))


def merge(runs):
    """Pool each backend's timed samples over the rounds of one arm (counts must agree)."""
    merged = dict(backends={})
    for run in runs:
        for backend, row in run['backends'].items():
            into = merged['backends'].setdefault(backend, {name: [] for name in SAMPLES})
            for name in SAMPLES:
                into[name] += row[name]
            for key in ('checks_per_miss', 'checks_per_hit'):
                W.require(into.setdefault(key, row[key]) == row[key], 'check counts differ between rounds')
    return merged


def project(probe, timings, counted):
    """The probe's own formulas (probe.main), unchanged, plus measured-count decision fields."""
    queries = counted['completed_component_volume_queries']
    threshold = probe.THRESHOLD_FRACTION*probe.GEOMETRY_PHASE_S
    summary, projection = {}, {}
    for backend, row in timings['backends'].items():
        stats = {name: probe._summary(row[name]) for name in SAMPLES}
        check = stats['check']['median']
        miss_e2e = stats['query_miss']['median']-stats['query_baseline']['median']
        summary[backend] = stats
        projection[backend] = dict(
            median_check_seconds=check, median_capture_runtime_seconds=stats['capture_runtime']['median'],
            median_source_bytes_seconds=stats['source_bytes']['median'],
            median_verify_boundary_seconds=stats['verify_boundary']['median'],
            checks_per_miss_measured=row['checks_per_miss'], checks_per_hit_measured=row['checks_per_hit'],
            plan_miss_overhead_seconds=3*check*queries,
            measured_count_miss_overhead_seconds=row['checks_per_miss']*check*queries,
            hit_check_overhead_seconds=row['checks_per_hit']*check*queries,
            per_miss_check_seconds=3*check, per_hit_check_seconds=row['checks_per_hit']*check,
            measured_per_miss_check_seconds=row['checks_per_miss']*check,
            end_to_end_miss_overhead_seconds_per_query=miss_e2e,
            end_to_end_miss_overhead_seconds=miss_e2e*queries,
            end_to_end_hit_seconds_per_query=stats['query_hit']['median'],
            end_to_end_all_hit_seconds=stats['query_hit']['median']*queries,
            fraction_of_3h_geometry=3*check*queries/probe.GEOMETRY_PHASE_S,
            fraction_of_interval1_geometry=3*check*queries/counted['interval1_geometry_phase_seconds'],
            ratio_to_interval1_endpoint_phase=3*check*queries/counted['named_records']['endpoint_volumes_phase_seconds'])
    decided = projection['scipy']
    scale = counted['interval2_directed_query_upper_bound']/counted['named_records']['directed_query_upper_bound']
    measured = decided['measured_count_miss_overhead_seconds']
    decision = dict(backend='scipy', threshold_seconds=threshold, queries=queries,
        measured_count_miss_overhead_seconds=measured, measured_count_fraction_of_threshold=measured/threshold,
        measured_count_exceeds=measured > threshold,
        measured_count_break_even_queries=threshold/decided['measured_per_miss_check_seconds'],
        plan_rule_miss_overhead_seconds=decided['plan_miss_overhead_seconds'],
        end_to_end_miss_overhead_seconds=decided['end_to_end_miss_overhead_seconds'],
        end_to_end_exceeds=decided['end_to_end_miss_overhead_seconds'] > threshold,
        all_hit_check_exceeds=decided['hit_check_overhead_seconds'] > threshold,
        interval2_proxy=dict(scale=scale, measured_count_miss_overhead_seconds=measured*scale,
            end_to_end_miss_overhead_seconds=decided['end_to_end_miss_overhead_seconds']*scale,
            exceeds_threshold=measured*scale > threshold,
            note='UNMEASURED proxy: ratio of directed_query_upper_bound (r4 interval 2 / r9 interval 1)'),
        note=('measured_count_* use the measured strict checks per miss (W2-K: 1); plan_rule_* keep the Q1 '
              '3 x check rule only for comparison with earlier outputs'))
    return summary, projection, decided, decision, scale


def run_arm(arm, probe):
    ram = W.ram_gate(minimum=PROBE_CHILD_MINIMUM)
    root = W.NATIVE if arm == 'composed' else CONTROL
    env = dict(os.environ, PYTHONHASHSEED='0', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
               PYTHONDONTWRITEBYTECODE='1', TMP=str(W.SCRATCH), TEMP=str(W.SCRATCH))
    with tempfile.TemporaryDirectory(prefix='pq-', dir=W.SCRATCH) as scratch:
        command = [sys.executable, '-B', str(Path(__file__).resolve()), '--child', arm, scratch, str(root)]
        launched = time.perf_counter()
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800, env=env,
                                   check=False, stdin=subprocess.DEVNULL)
        wall = time.perf_counter()-launched
    out = completed.stdout.splitlines()
    rows = {mark: [line[len(mark):] for line in out if line.startswith(mark)] for mark in (probe.MARK, CENSUS, AUDIT)}
    W.require(completed.returncode == 0 and len(rows[probe.MARK]) == 1 and len(rows[CENSUS]) == 1
              and len(rows[AUDIT]) == (arm == 'composed'),
              arm+' probe child failed: '+str(completed.returncode)+' '+completed.stderr[-4000:])
    timings = json.loads(rows[probe.MARK][0])
    W.require(Path(timings['candidate_module']).resolve().parent == (root/'atlas_tectonics').resolve(),
              arm+' child did not load its named package')
    return dict(arm=arm, timings=timings, census=json.loads(rows[CENSUS][0]),
                audit=json.loads(rows[AUDIT][0]) if rows[AUDIT] else None, ram_gate=ram,
                child=dict(command=command[1:], returncode=completed.returncode, wall_seconds=wall,
                           stderr_tail=completed.stderr[-2000:]))


def headline(record):
    row = record['projection']['scipy']
    return dict(package=record['package'], companion_sha256=record['sources']['companion_sha256'],
                files=record['sources']['candidate_files'], bytes=record['sources']['candidate_bytes'],
                median_check_seconds=row['median_check_seconds'],
                median_source_bytes_seconds=record['summary']['scipy']['source_bytes']['median'],
                checks_per_miss=row['checks_per_miss_measured'], checks_per_hit=row['checks_per_hit_measured'],
                end_to_end_miss_overhead_seconds_per_query=row['end_to_end_miss_overhead_seconds_per_query'],
                end_to_end_hit_seconds_per_query=row['end_to_end_hit_seconds_per_query'])


def census_difference(composed, control):
    """Modules whose inventory cost/size differs most between the arms (pooled over rounds by median)."""
    def pooled(rows):
        out = {}
        for row in rows:
            for module, (seconds, tokens, constant_bytes) in row['per_module'].items():
                entry = out.setdefault(module, [[], tokens, constant_bytes])
                entry[0].append(seconds)
        return {m: [statistics.median(s), t, c] for m, (s, t, c) in out.items()}
    a, b = pooled(composed), pooled(control)
    rows = [dict(module=m, composed_seconds=a.get(m, [0, 0, 0])[0], control_seconds=b.get(m, [0, 0, 0])[0],
                 composed_tokens=a.get(m, [0, 0, 0])[1], control_tokens=b.get(m, [0, 0, 0])[1],
                 composed_constant_bytes=a.get(m, [0, 0, 0])[2], control_constant_bytes=b.get(m, [0, 0, 0])[2])
            for m in sorted(set(a) | set(b))]
    for row in rows:
        row['delta_seconds'] = row['composed_seconds']-row['control_seconds']
    rows.sort(key=lambda r: -r['delta_seconds'])
    total = lambda side, key: sum(r[side+'_'+key] for r in rows)
    return dict(composed=dict(seconds=total('composed', 'seconds'), tokens=total('composed', 'tokens'),
                              constant_bytes=total('composed', 'constant_bytes'), modules=len(a)),
                control=dict(seconds=total('control', 'seconds'), tokens=total('control', 'tokens'),
                             constant_bytes=total('control', 'constant_bytes'), modules=len(b)),
                largest_increase=rows[:12])


def main(argv):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--label', default='w4-composed')
    parser.add_argument('--rounds', type=int, default=2)
    options = parser.parse_args(argv)
    output = Path(options.output).resolve()
    W.require(not output.exists(), 'output exists; refusing to overwrite '+str(output))
    W.require(1 <= options.rounds <= 4, 'rounds must be 1 to 4')
    W.require(W.file_sha(BASELINE) == BASELINE_SHA256 and W.file_sha(Q1) == Q1_SHA256, 'earlier probe outputs changed')
    begun = time.perf_counter()
    created = datetime.now(timezone.utc).isoformat()
    before = W.verify_composed()
    probe = load_probe()
    inventory = composed_inventory()
    control_sources = probe.verify_candidate(CONTROL/'atlas_tectonics', CONTROL_MANIFEST)
    counted = probe.count_queries()
    W.SCRATCH.mkdir(parents=True, exist_ok=True)
    runs = []
    for _ in range(options.rounds):
        for arm in ('control', 'composed'):
            runs.append(run_arm(arm, probe))
    arms = {arm: [r for r in runs if r['arm'] == arm] for arm in ('control', 'composed')}
    results = {}
    for arm, rows in arms.items():
        summary, projection, decided, decision, scale = project(probe, merge([r['timings'] for r in rows]), counted)
        results[arm] = dict(summary=summary, projection=projection, decided=decided, decision=decision)
    decided, decision = results['composed']['decided'], results['composed']['decision']
    control = results['control']['decided']
    per_round = [dict(arm=r['arm'], median_check_seconds=statistics.median(r['timings']['backends']['scipy']['check']),
                      median_source_bytes_seconds=statistics.median(r['timings']['backends']['scipy']['source_bytes']),
                      median_query_baseline_seconds=statistics.median(r['timings']['backends']['scipy']['query_baseline']),
                      available_ram_start=r['timings'].get('available_ram_start'), child_wall_seconds=r['child']['wall_seconds'])
                 for r in runs]
    ratio = lambda key: decided[key]/control[key]
    same_session = dict(
        composed=dict(median_check_seconds=decided['median_check_seconds'],
                      median_source_bytes_seconds=decided['median_source_bytes_seconds'],
                      inventory_part_seconds=decided['median_verify_boundary_seconds']-decided['median_source_bytes_seconds'],
                      median_query_baseline_seconds=results['composed']['summary']['scipy']['query_baseline']['median']),
        control=dict(median_check_seconds=control['median_check_seconds'],
                     median_source_bytes_seconds=control['median_source_bytes_seconds'],
                     inventory_part_seconds=control['median_verify_boundary_seconds']-control['median_source_bytes_seconds'],
                     median_query_baseline_seconds=results['control']['summary']['scipy']['query_baseline']['median']),
        ratio_check=ratio('median_check_seconds'), ratio_source_bytes=ratio('median_source_bytes_seconds'),
        ratio_verify_boundary=ratio('median_verify_boundary_seconds'),
        control_vs_w2k_record_check=control['median_check_seconds']/json.loads(BASELINE.read_bytes())['projection']['scipy']['median_check_seconds'],
        per_round=per_round)
    comparison = probe._comparison(BASELINE, decided, counted['completed_component_volume_queries'],
                                   decision['interval2_proxy']['scale'])
    composed_audits = [r['audit'] for r in arms['composed']]
    violations = [v for audit in composed_audits for v in audit['violations']]
    after = W.verify_composed()
    W.require(before['tree_digest'] == after['tree_digest'], 'composed tree changed during the probe')
    w2k, q1 = json.loads(BASELINE.read_bytes()), json.loads(Q1.read_bytes())
    record = dict(schema='private.q1-checkpoint-overhead.v1', package=options.label, created_utc=created,
        status='MEASURED', probe_sha256=PROBE_SHA256, wrapper_sha256=W.file_sha(Path(__file__)),
        common_sha256=W.file_sha(W.HERE/'w4r_common.py'),
        method=dict(process=('fresh children, alternating control (candidate-w2k, probe child unchanged: sys.path '
                             'candidate-w2k, I/helpers, I/ram, H) and composed (probe globals E, I -> composed-r1, '
                             'H -> H/source/tectonics/tests: sys.path composed runtime-src, helpers, ram, H tests); '
                             'PYTHONHASHSEED=0, OMP/OPENBLAS threads 1, PYTHONDONTWRITEBYTECODE=1; the probe child '
                             'asserts no profile/trace hook'),
                    rounds=options.rounds, timed='as the probe: %d calls each after 1 warm-up per child; samples '
                    'pooled per arm; ExecutionContext imports all package modules' % probe.CALLS,
                    census='after timing, per module: reuse._callable_inventory(scipy, (module,)) x %d (diagnostic)'
                           % CENSUS_REPEATS,
                    projection='probe formulas; decision on the MEASURED checks per miss x median _check x queries'),
        sources=inventory, control_sources=control_sources, queries=counted,
        runs=[dict(arm=r['arm'], child=r['child'], ram_gate=r['ram_gate'], raw=r['timings'],
                   census=dict((k, v) for k, v in r['census'].items() if k != 'per_module'))
              for r in runs],
        summary=results['composed']['summary'], projection=results['composed']['projection'], decision=decision,
        control=dict(summary=results['control']['summary'], projection=results['control']['projection'],
                     decision=results['control']['decision']),
        same_session=same_session,
        inventory_census=census_difference([r['census'] for r in arms['composed']], [r['census'] for r in arms['control']]),
        comparison=comparison, import_audit=dict(composed_runs=len(composed_audits), violations=violations,
            counts=[a['counts'] for a in composed_audits]),
        headline=dict(q1=headline(q1), w2k=headline(w2k), composed=dict(package=options.label,
            files=inventory['files'], bytes=inventory['bytes'], median_check_seconds=decided['median_check_seconds'],
            median_source_bytes_seconds=decided['median_source_bytes_seconds'],
            checks_per_miss=decided['checks_per_miss_measured'], checks_per_hit=decided['checks_per_hit_measured'],
            end_to_end_miss_overhead_seconds_per_query=decided['end_to_end_miss_overhead_seconds_per_query'],
            end_to_end_hit_seconds_per_query=decided['end_to_end_hit_seconds_per_query'])),
        composed_before=before, composed_after=after, probe_seconds=time.perf_counter()-begun,
        caveats=['Shared machine: arms alternate in fresh processes and samples are pooled; the control arm, '
                 'not the earlier W2-K record, is the like-for-like reference.',
                 'Tiny-fixture queries measure checkpoint mechanics, not production geometry per query.',
                 'Interval-2 figures use the UNMEASURED directed_query_upper_bound proxy.',
                 'Serial-addition assumption: checks may overlap worker waits in automatic parallel mode.',
                 'The inventory census re-derives tokens/constants per module; it approximates, not times, verify.'])
    digest = W.write_exclusive(output, record)
    print('W4_PROBE '+json.dumps(dict(files=inventory['files'], bytes=inventory['bytes'],
        composed_check_s=decided['median_check_seconds'], control_check_s=control['median_check_seconds'],
        ratio_check=same_session['ratio_check'], ratio_source_bytes=same_session['ratio_source_bytes'],
        composed_inventory_part_s=same_session['composed']['inventory_part_seconds'],
        control_inventory_part_s=same_session['control']['inventory_part_seconds'],
        checks_per_miss=decided['checks_per_miss_measured'], checks_per_hit=decided['checks_per_hit_measured'],
        measured_interval1_s=decision['measured_count_miss_overhead_seconds'],
        interval2_proxy_s=decision['interval2_proxy']['measured_count_miss_overhead_seconds'],
        threshold_s=decision['threshold_seconds'], violations=len(violations),
        output=str(output), sha256=digest)), flush=True)
    return 0 if not violations else 1


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--child':
        raise SystemExit(child(sys.argv[2], sys.argv[3], sys.argv[4]))
    raise SystemExit(main(sys.argv[1:]))
