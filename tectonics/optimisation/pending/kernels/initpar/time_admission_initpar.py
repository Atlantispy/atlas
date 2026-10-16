"""Item 19 proof harness (T/ck/initpar): route (1)'s admission, serial or with the parallel initial pass.

A copy of the Runner chat's R/probes/step9/claude-20261016/time_admission_parts.py (sha256 62972c14...,
copied 16 Oct) with one addition: --workers=N (N >= 1) opens integration_initial_parallel.InitialParallel
(workers=N, batch_jobs=--batch [16], outstanding=--outstanding [3N]) around spatial.initial_metrics, as
the driver would; --workers=0 (default) runs the unchanged serial admission. The pass report (batches,
adoptions, serial members, session stats and seconds, child peaks) goes to report.json under
'initial_parallel'. Everything else is the original harness and its checks.

Original docstring follows.
Read-only: where route (1)'s 'initial-physical-and-thermal-metrics' phase spends its time.

Usage: python -B time_admission_parts.py [--metrics-only] [--seed-store=STORE@SHA256] [--expect=REPORT]
                                         [--expect-store=SHA256] [--expect-run=RUN_JSON]
                                         OUTDIR NATIVE_ROOT IMPORT_ROOT [IMPORT_ROOT ...]
  e.g. OUTDIR=R/L/adm1  NATIVE_ROOT=R/composed-r2/src  IMPORT_ROOTS=R/composed-r2/helpers H/source/tectonics/tests
  --metrics-only stops after initial_metrics (the geometry chat's scope), for bisecting
  native trees and helper sets that differ in the later parts' modules.
  --seed-store (item 7's exactness arm) copies a closed, pinned measurement store into OUTDIR
  before the admission, with private_heat_original_coverage_r1.copy_verified_cache's discipline:
  refuse if its SHA-256 differs or a -wal/-journal file exists, create exclusively, re-check both
  digests. Every query is then a cache hit. A hit re-checks each stored field's consistency with
  the request; it does not certify the geometry again. bounds_id and geometry_id are the SHA-256
  of the issued records' canonical bytes, so equal IDs mean byte-equal records.
  --expect compares this run's workflow ID, preparation IDs, identities and final store digest
  with an earlier report (the fresh-store arm), over the UNION of both reports' keys.
  --expect-store requires this run's final store SHA-256 to equal the given pin.
  --expect-run requires agreement with a producer's recorded run.json (run A): its workflow_id and
  its published root's preparation_ids. The spatial owner ID among them is the hash of a
  definition holding initial_bounds_id and initial_mesh_id; this run checks that its own owner
  definition holds its own bounds_id and geometry_id, so agreement binds both to run A's.

FAIL CLOSED (coordinator, 16 Oct 13:10): every requested comparison is a check, a field missing on
either side is a failure, the store must be closed (no sidecars) and, when seeded, byte-unchanged.
The report (with 'checks' and 'passed') is always written; the exit status is non-zero unless
every check is True.

The driver's phase of that name (fresh_interval_driver._admission and create_root) runs, in
order: initial_metrics, initial_spatial_owner (entered), and, back in create_root before the
'create-fresh-root' phase, Workflow._exterior_inputs + Workflow._identity. The geometry chat's
285-407 s figures time initial_metrics alone. This repeats the driver's calls with its literals
(FIXTURE, MEASUREMENT_CACHE, MEASUREMENT_CODEC, INITIAL_PARTITION, INITIAL_METRICS,
CREATED_TRACERS; the modules of run_fresh_interval.composition) and times each part apart, CPU
and wall, with the machine's other busy CPUs per part (psutil.cpu_times minus this process).
The preparation IDs come from the driver's own preparation_ids(). A NEW measurement store lives
in OUTDIR; nothing else is written. Requires PYTHONHASHSEED=0.
"""
import json
import sys
import time
from contextlib import nullcontext
from fractions import Fraction as Q
from pathlib import Path

import psutil

FIXTURE = {'pressure_space': 'q1-p0', 'material_quadrature': True}
MEASUREMENT_CACHE = {'chunk_bytes': 65536, 'max_array_bytes': 1 << 20, 'max_store_bytes': 128 << 20}
MEASUREMENT_CODEC = 'raw'
INITIAL_PARTITION = {'max_components': 4096}
INITIAL_METRICS = {'physical_volume_error_m3': Q(32000), 'thermal_volume_error_m3': Q(32000),
                   'max_leaves': 2**30, 'max_witness_refinements': 32}
CREATED_TRACERS = ('tracer:accumulated_strain_ii',)
SIDECARS = ('-wal', '-journal', '-shm')


def _busy(times):
    values = times._asdict()
    return sum(values.values())-values['idle']


class Parts:
    def __init__(self):
        self.rows, self.me = {}, psutil.Process()

    def start(self):
        self.cpu, self.wall = time.process_time(), time.perf_counter()
        self.system = _busy(psutil.cpu_times())

    def stop(self, name):
        cpu, wall = time.process_time()-self.cpu, time.perf_counter()-self.wall
        other = _busy(psutil.cpu_times())-self.system-cpu
        self.rows[name] = dict(cpu_s=round(cpu, 2), wall_s=round(wall, 2),
                               other_busy_cpus=round(other/wall, 2) if wall > 0 else None)
        print(name, self.rows[name], flush=True)


def _digest(path):
    from hashlib import file_digest
    with Path(path).open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def _sidecars(store):
    return sorted(store.name+s for s in SIDECARS if Path(str(store)+s).exists())


def _seed(source, pin, target):
    if _digest(source) != pin or _sidecars(Path(source)):
        raise SystemExit('seed store changed or is not closed')
    with Path(source).open('rb') as reader, Path(target).open('xb') as writer:
        for block in iter(lambda: reader.read(1 << 20), b''):
            writer.write(block)
    if _digest(target) != pin or _digest(source) != pin:
        raise SystemExit('seeded store differs from its pin')


def _option(argv, name):
    return next((item.split('=', 1)[1] for item in argv if item.startswith(name+'=')), None)


def _same(a, b):
    """A check, not a comparison: a field missing on either side fails."""
    return a is not None and b is not None and a == b


def _canonical(value):
    return None if value is None else json.dumps(value, sort_keys=True)


def evaluate(report, owner_binds, *, expect_store=None, other=None, run_a=None):
    """Every requested comparison as a check: True only when both sides are present and equal."""
    identity, workflow_id = report['identity'], report['workflow_id']
    preparation, store_sha256 = report['preparation_ids'], report['measurement_store_sha256']
    seeded = report['seeded_store']
    checks = {'store:closed_no_sidecars': report['store_sidecars'] == []}
    if seeded is not None:
        checks['store:unchanged_from_seed'] = report['store_unchanged_from_seed'] is True
        checks['seed:source_unchanged'] = _same(report.get('seed_source_sha256_after'), seeded['sha256'])
    if expect_store is not None:
        checks['store:sha256_equals_pin'] = _same(store_sha256, expect_store)
    if other is not None:
        mine = dict(identity, workflow_id=workflow_id, measurement_store_sha256=store_sha256,
                    preparation_ids=_canonical(preparation))
        theirs = dict(other.get('identity') or {}, workflow_id=other.get('workflow_id'),
                      measurement_store_sha256=other.get('measurement_store_sha256'),
                      preparation_ids=_canonical(other.get('preparation_ids')))
        for name in sorted(set(mine) | set(theirs)):
            checks[f'expect:{name}'] = _same(mine.get(name), theirs.get(name))
        checks['expect:report_passed'] = other.get('passed') is True
    if run_a is not None:
        root = run_a.get('published_root') or {}
        checks['run_a:workflow_id'] = _same(workflow_id, run_a.get('workflow_id'))
        checks['run_a:published_root_workflow_id'] = _same(workflow_id, (root.get('inspect') or {}).get('workflow_id'))
        checks['run_a:preparation_ids'] = _same(_canonical(preparation), _canonical(root.get('preparation_ids')))
        checks['run_a:spatial_owner'] = _same(identity.get('owner.owner_id'),
                                              (root.get('preparation_ids') or {}).get('spatial_owner'))
        for name in ('owner_definition_holds_bounds_id', 'owner_definition_holds_mesh_geometry_id'):
            checks[f'run_a:{name}'] = owner_binds.get(name) is True
    return checks


def main():
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    argv = sys.argv[1:]
    metrics_only = '--metrics-only' in argv
    seed, expect = _option(argv, '--seed-store'), _option(argv, '--expect')
    expect_store, expect_run = _option(argv, '--expect-store'), _option(argv, '--expect-run')
    workers, batch = int(_option(argv, '--workers') or 0), int(_option(argv, '--batch') or 16)
    outstanding = None if _option(argv, '--outstanding') is None else int(_option(argv, '--outstanding'))
    argv = [item for item in argv if not item.startswith(
        ('--metrics-only', '--seed-store=', '--expect=', '--expect-store=', '--expect-run=',
         '--workers=', '--batch=', '--outstanding='))]
    if any(item.startswith('--') for item in argv):
        raise SystemExit(f'unknown option: {[item for item in argv if item.startswith("--")]}')
    out, native, roots = Path(argv[0]), Path(argv[1]).resolve(), [Path(p).resolve() for p in argv[2:]]
    # Read every expectation before any work, so a missing or unreadable one refuses at once.
    other = json.loads(Path(expect).read_text(encoding='utf8')) if expect is not None else None
    run_a = json.loads(Path(expect_run).read_text(encoding='utf8')) if expect_run is not None else None
    out.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(native), *map(str, roots)]
    parts = Parts()
    seeded = None
    if seed is not None:
        source, pin = seed.rsplit('@', 1)
        parts.start()
        _seed(source, pin, out/'initial-measurements.sqlite')
        parts.stop('seed_copy')
        seeded = dict(source=str(Path(source).resolve()), sha256=pin, copied=True,
                      native_hit_verification_unchanged=True)
    parts.start()
    import atlas_tectonics
    if not Path(atlas_tectonics.__file__).resolve().is_relative_to(native):
        raise SystemExit('atlas_tectonics did not load from the native root')
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    import fresh_interval_driver as DRIVER
    import i04_differential_fixture as F
    import private_heat_original_spatial_r1 as spatial
    import probe_heat_original_connected_r9 as D
    parts.stop('imports')
    loaded = {name: str(Path(module.__file__).resolve()) for name, module in
              (('fixture', F), ('spatial', spatial), ('probe_r9', D), ('driver', DRIVER))}
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    owner_binds, preparation = {}, None
    parts.start()
    with ExecutionContext('reference') as reference, ExecutionContext('scipy') as heat, \
            ArrayStore(out/'initial-measurements.sqlite', StoreLimits(**MEASUREMENT_CACHE),
                       Compression(codec=MEASUREMENT_CODEC), budget=budget) as cache, \
            F.radial_differential_fixture(budget=budget, **FIXTURE) as case:
        parts.stop('contexts_store_fixture')
        parts.start()
        current, partition = spatial.initial_partition(case, **INITIAL_PARTITION)
        parts.stop('initial_partition')
        parts.start()
        if workers:
            from atlas_tectonics.integration_initial_parallel import InitialParallel
            initial_pass = InitialParallel(workers=workers, budget=budget, context=reference,
                                           batch_jobs=batch, outstanding=outstanding)
        else:
            initial_pass = nullcontext()
        with initial_pass:
            bounds, mesh = spatial.initial_metrics(case, partition, **INITIAL_METRICS, measure_policy=D.POLICY,
                                                   measurement_store=cache, measurement_context=reference)
        parts.stop('initial_metrics')
        # Required fields first: a missing one raises here (non-zero exit) instead of being dropped.
        identity = {'bounds.bounds_id': str(bounds.bounds_id), 'mesh.geometry_id': str(mesh.geometry_id)}
        for name, value in (('bounds', bounds), ('mesh', mesh), ('partition', partition), ('current', current)):
            for attr in ('bounds_id', 'geometry_id', 'partition_id'):
                if hasattr(value, attr):
                    identity[f'{name}.{attr}'] = str(getattr(value, attr))
        for name, context in (('reference', reference), ('heat', heat)):
            identity[f'{name}.provenance'] = json.dumps(context.provenance, sort_keys=True)
        budget_after_metrics = {k: v for k, v in budget.statistics().items() if k != 'category_peaks'}
        workflow_id = None
        if not metrics_only:
            from atlas_tectonics.integration_regional_workflow import CollarWorkflow as Workflow
            import private_heat_joined_consumer_r6 as J
            parts.start()
            with spatial.initial_spatial_owner(case, partition, bounds, mesh, created_tracers=CREATED_TRACERS,
                                               measure_policy=D.POLICY, heat_method=J.METHOD) as owner:
                parts.stop('initial_spatial_owner')
                identity['owner.owner_id'] = str(owner.owner_id)
                preparation = DRIVER.preparation_ids(case, owner)
                definition = getattr(owner, '_definition', None) or {}
                owner_binds = {
                    'owner_definition_holds_bounds_id': _same(
                        (definition.get('initial_geometry') or {}).get('initial_bounds_id'), bounds.bounds_id),
                    'owner_definition_holds_mesh_geometry_id': _same(
                        definition.get('initial_mesh_id'), mesh.geometry_id)}
                collar, funding = case['collar'], case['funding']
                parts.start()
                inputs = Workflow._exterior_inputs(owner, collar, funding, budget)
                parts.stop('workflow_exterior_inputs')
                parts.start()
                workflow_id = Workflow._identity(collar, funding, inputs)
                parts.stop('workflow_identity')
                del inputs
                parts.start()
            parts.stop('owner_exit')
        parts.start()
        reference.verify_boundary()
        heat.verify_boundary()
        parts.stop('verify_boundary_both')
        parts.start()
    parts.stop('contexts_exit')
    memory = psutil.Process().memory_info()
    store = out/'initial-measurements.sqlite'
    store_sha256 = _digest(store)
    report = dict(native_root=str(native), import_roots=list(map(str, roots)), metrics_only=metrics_only,
                  seeded_store=seeded, measurement_store_sha256=store_sha256,
                  store_unchanged_from_seed=None if seeded is None else store_sha256 == seeded['sha256'],
                  store_sidecars=_sidecars(store),
                  loaded=loaded, parts=parts.rows,
                  phase_equivalent_wall_s=round(sum(parts.rows[name]['wall_s'] for name in (
                      'initial_metrics', 'initial_spatial_owner', 'workflow_exterior_inputs', 'workflow_identity')
                      if name in parts.rows), 2),
                  workflow_id=workflow_id, preparation_ids=preparation, identity=identity,
                  budget_after_metrics=budget_after_metrics,
                  bounds_type=type(bounds).__name__,
                  mesh_type=type(mesh).__name__,
                  peak_working_set_mib=round(memory.peak_wset/2**20),
                  measurement_store_bytes=store.stat().st_size,
                  initial_parallel=initial_pass.report if workers else None)
    report['seed_source_sha256_after'] = None if seeded is None else _digest(seeded['source'])
    checks = evaluate(report, owner_binds, expect_store=expect_store, other=other, run_a=run_a)
    failed = sorted(name for name, ok in checks.items() if ok is not True)
    report.update(expected=None if other is None else str(Path(expect).resolve()),
                  expected_run=None if run_a is None else str(Path(expect_run).resolve()),
                  checks=checks, failed=failed, passed=not failed)
    (out/'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf8')
    print(json.dumps({'phase_equivalent_wall_s': report['phase_equivalent_wall_s'], 'workflow_id': workflow_id,
                      'passed': not failed, 'checks': len(checks), 'failed': failed}), flush=True)
    if failed:
        raise SystemExit(f'FAILED {len(failed)} of {len(checks)} checks: {", ".join(failed)}')


if __name__ == '__main__':
    main()
