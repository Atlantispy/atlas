#!/usr/bin/env python3
"""Matched W05 output timing: calculate, save, reopen and resume one frozen case.

WORKING NON-CANON. This is execution evidence, not scientific acceptance.
No live source-bound functions are replaced to obtain timing measurements.
"""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

THREAD_KEYS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
               'NUMBA_NUM_THREADS')
for key in THREAD_KEYS:
    os.environ.setdefault(key, '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import numpy as np
from atlas_tectonics import (ColumnGrid1D, ListricGeometry, MaterialCohort,
    PreparedListricExtension, ExtensionSupportPolicy, FlexureParameters)
from atlas_tectonics.extension_workflow import PreparedExtensionWorkflow
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression


REPEATS = 3
BUDGET_BYTES = 128 << 20
# Covers the three retained comparison outputs and transient verification copies;
# the workflow itself retains no complete sequence of material/support arrays.
COMPARISON_BYTES = 8 << 20
LIMITS = StoreLimits(65536, 4 << 20, 32 << 20, decoded_cache_bytes=0)
COMPRESSION = Compression(codec='zstd', level=1)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configuration():
    case_path = ROOT/'cases/w05_support.json'
    support = json.loads(case_path.read_text(encoding='utf-8'))
    motion_path = ROOT/'cases'/support['motion_case']
    if sha256(motion_path) != support['motion_case_sha256']:
        raise ValueError('motion case source changed; no automatic repin')
    case = json.loads(motion_path.read_text(encoding='utf-8'))
    spacing = 125.
    if spacing not in case['grid_spacing_m']:
        raise ValueError('frozen 125 m case is unavailable')
    left, right = case['domain_m']
    grid = ColumnGrid1D(np.linspace(left, right, round((right-left)/spacing)+1),
                        frame_id=case['case_id'])
    displacements = tuple(case['output_displacements_m'][1:])
    if grid.cells != 3200 or displacements != (250., 500., 1000.):
        raise ValueError('benchmark requires the frozen 3200-cell three-output case')
    geometry = ListricGeometry(case['crust_thickness_m'], case['detachment_depth_m'],
                              case['surface_dip_rad'], case['trace_m'], case['case_id'])
    elastic = FlexureParameters(case['case_id'], 'step-1 frozen synthetic case',
        support['young_modulus_pa'], support['elastic_thickness_m'],
        support['poisson_ratio'], support['mantle_density_kg_m3'], support['gravity_m_s2'])
    policy = ExtensionSupportPolicy(elastic, support['max_abs_displacement_m'],
        support['max_abs_slope'], support['max_bending_strain'],
        support['max_omitted_displacement_m'], case['case_id'])
    velocity = case['velocity_m_per_year']/case['seconds_per_year']
    common = dict(velocity_m_s=velocity, density_kg_m3=case['density_kg_m3'],
        width_m=case['width_m'], cohorts=(MaterialCohort('a', 'crust', 'synthetic-A', None),
        MaterialCohort('b', 'crust', 'synthetic-B', None)), fractions=(.25, .75),
        time_s=0., epoch_id=case['case_id'], datum_id='initial-flat-surface',
        source_id=case['case_id'], backend='reference')
    return grid, geometry, policy, common, tuple(x/velocity for x in displacements)


def snapshot(state, support):
    """All persisted state/result bytes plus their public identities and metadata."""
    arrays = (state.material.thickness_m, state.material.grid.edges_m,
              state.exchange_m2, support.cell_means, support.face_centre_response)
    if any(a.flags.writeable for a in arrays):
        raise ValueError('workflow output exposes mutable array bytes')
    return dict(plan_id=state.plan_id, state_id=state.state_id,
        material_id=state.material.state_id, result_id=support.result_id,
        intervals=state.intervals, max_courant=state.max_courant,
        material_descriptor=state.material.descriptor(),
        material_bytes=state.material._payload,
        transition_bytes=state.material._transition_payload,
        grid_bytes=state.material.grid._edges, exchange_bytes=state._exchange,
        support_metadata=support._metadata, support_fields=support._fields,
        support_points=support._points)


def check(actual, expected):
    if actual != expected:
        changed = [name for name in expected if actual.get(name) != expected[name]]
        raise ValueError('matched output differs: '+', '.join(changed))


def output_record(value):
    return {name: (dict(bytes=len(item), sha256=hashlib.sha256(item).hexdigest())
                   if isinstance(item, bytes) else item)
            for name, item in value.items()}


def expected_outputs(config, budget):
    """Untimed oracle captures each output without retaining history in the API."""
    grid, geometry, policy, common, times = config
    outputs = []
    with PreparedListricExtension(grid, geometry, **common, budget=budget) as motion:
        with PreparedExtensionWorkflow(motion, policy, times, budget=budget) as workflow:
            for index in range(len(times)):
                checkpoint = workflow.run(through=index)
                outputs.append(snapshot(checkpoint.state, checkpoint.support))
            keys = [workflow.checkpoint_id(index) for index in range(len(times))]
            return outputs, keys, motion.execution_id


def calculate(config, budget, expected, checkpoint_ids):
    """Fresh no-store workflow, using the same single run call as durable paths."""
    grid, geometry, policy, common, times = config
    start = time.perf_counter()
    with PreparedListricExtension(grid, geometry, **common, budget=budget) as motion:
        motion_ready = time.perf_counter()
        execution_id = motion.execution_id
        with PreparedExtensionWorkflow(motion, policy, times, budget=budget) as workflow:
            workflow_ready = time.perf_counter()
            final = workflow.run()
            finished = time.perf_counter()
    elapsed = time.perf_counter()-start
    if final.output_index != len(times)-1 or final.checkpoint_id != checkpoint_ids[-1]:
        raise ValueError('uncached workflow returned the wrong final checkpoint')
    check(snapshot(final.state, final.support), expected[-1])
    return dict(total_seconds=elapsed, motion_setup_seconds=motion_ready-start,
        workflow_setup_seconds=workflow_ready-motion_ready,
        workflow_run_seconds=finished-workflow_ready,
        close_seconds=elapsed-(finished-start), execution_id=execution_id)


def durable(config, path, budget, expected, *, through=None):
    """One fresh store connection, motion and workflow, closed within total time."""
    grid, geometry, policy, common, times = config
    last = len(times)-1 if through is None else through
    start = time.perf_counter()
    with ExitStack() as stack:
        store = stack.enter_context(ArrayStore(path, LIMITS, COMPRESSION, budget=budget))
        store_ready = time.perf_counter()
        motion = stack.enter_context(PreparedListricExtension(
            grid, geometry, **common, budget=budget))
        motion_ready = time.perf_counter()
        workflow = stack.enter_context(PreparedExtensionWorkflow(
            motion, policy, times, store=store, budget=budget))
        workflow_ready = time.perf_counter()
        final = workflow.run(through=through)
        finished = time.perf_counter()
        execution_id = motion.execution_id
        store_operations = dict(store._stats)
    closed = time.perf_counter()
    # Reopen only for exact post-timing verification and store statistics.
    with ArrayStore(path, LIMITS, COMPRESSION, budget=budget) as store:
        stats = store.statistics()
        with PreparedListricExtension(grid, geometry, **common, budget=budget) as motion:
            with PreparedExtensionWorkflow(motion, policy, times,
                                            store=store, budget=budget) as workflow:
                checkpoint_ids = []
                for index in range(last+1):
                    loaded = workflow.load(index)
                    if loaded is None or loaded.output_index != index:
                        raise ValueError('requested checkpoint missing or mislabelled')
                    if loaded.checkpoint_id != workflow.checkpoint_id(index):
                        raise ValueError('checkpoint key is not deterministic')
                    check(snapshot(loaded.state, loaded.support), expected[index])
                    checkpoint_ids.append(loaded.checkpoint_id)
                if last+1 < len(times) and workflow.load(last+1) is not None:
                    raise ValueError('partial seed unexpectedly produced a later output')
    if final.output_index != last or final.checkpoint_id != checkpoint_ids[last]:
        raise ValueError('workflow returned the wrong final checkpoint')
    check(snapshot(final.state, final.support), expected[last])
    return dict(total_seconds=closed-start, store_open_seconds=store_ready-start,
        motion_setup_seconds=motion_ready-store_ready,
        workflow_setup_seconds=workflow_ready-motion_ready,
        workflow_run_seconds=finished-workflow_ready, close_seconds=closed-finished,
        execution_id=execution_id, checkpoint_ids=checkpoint_ids, store=stats,
        store_operations=store_operations)


def comparison(baseline, candidate):
    before = statistics.median(row['total_seconds'] for row in baseline)
    after = statistics.median(row['total_seconds'] for row in candidate)
    return dict(baseline_median_seconds=before, candidate_median_seconds=after,
                saved_seconds=before-after, saved_percent=100*(before-after)/before,
                speedup=before/after)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    config = configuration()
    paths = [ROOT/'cases/w05_support.json', ROOT/'cases/w05_motion.json', Path(__file__),
             ROOT/'tools/benchmark_w05_support.py']
    paths += sorted((ROOT/'src/atlas_tectonics').glob('*.py'))
    sources = {p.relative_to(ROOT).as_posix(): sha256(p) for p in paths}
    timings = {name: [] for name in ('uncached', 'cold_durable', 'warm_reopen',
                                   'partial_seed', 'partial_resume')}
    budget = WorkBudget(BUDGET_BYTES)
    # Only this newly created temporary directory is removed on completion.
    with tempfile.TemporaryDirectory(prefix='atlas-w05-workflow-') as temporary:
        with budget.reserve(COMPARISON_BYTES, category='benchmark-comparison-outputs'):
            oracle_start = time.perf_counter()
            expected, checkpoint_ids, execution_id = expected_outputs(config, budget)
            oracle_seconds = time.perf_counter()-oracle_start
            for repeat in range(REPEATS):
                # Alternate calculation/cold-save order; warm and resume have dependencies.
                order = ('uncached', 'durable') if repeat % 2 == 0 else ('durable', 'uncached')
                for mode in order:
                    if mode == 'uncached':
                        timings['uncached'].append(calculate(
                            config, budget, expected, checkpoint_ids))
                    else:
                        full_path = Path(temporary)/f'full-{repeat}.sqlite'
                        cold = durable(config, full_path, budget, expected)
                        warm = durable(config, full_path, budget, expected)
                        partial_path = Path(temporary)/f'partial-{repeat}.sqlite'
                        seed = durable(config, partial_path, budget, expected, through=0)
                        resume = durable(config, partial_path, budget, expected)
                        for row in (cold, warm, resume):
                            if row['checkpoint_ids'] != checkpoint_ids or row['store']['snapshots'] != 3:
                                raise ValueError('matched durable schedule or snapshot count differs')
                        if seed['checkpoint_ids'] != checkpoint_ids[:1] or seed['store']['snapshots'] != 1:
                            raise ValueError('partial seed is not exactly the first output')
                        for name, row in (('cold_durable', cold), ('warm_reopen', warm),
                                          ('partial_seed', seed), ('partial_resume', resume)):
                            timings[name].append(row)
                if any(row['execution_id'] != execution_id for rows in timings.values() for row in rows):
                    raise ValueError('execution source/runtime changed between measurements')
    if budget.reserved_bytes:
        raise ValueError('benchmark left budget reservations open')
    if sources != {p.relative_to(ROOT).as_posix(): sha256(p) for p in paths}:
        raise ValueError('benchmark sources changed during execution')
    combined = [dict(total_seconds=a['total_seconds']+b['total_seconds'])
                for a, b in zip(timings['partial_seed'], timings['partial_resume'])]
    record = dict(status='PASS_W05_STEP_4_MATCHED_WORKFLOW',
        source_status='WORKING NON-CANON SYNTHETIC', repetitions=REPEATS,
        platform=platform.platform(), machine=platform.machine(), python=sys.version,
        executable_sha256=sha256(Path(sys.executable)), numpy=np.__version__,
        scipy=version('scipy'), blosc2=version('blosc2'),
        thread_environment={key: os.environ[key] for key in THREAD_KEYS},
        cells=config[0].cells, spacing_m=125., output_displacements_m=[250., 500., 1000.],
        output_times_s=config[4], backend='reference', execution_id=execution_id,
        budget_bytes=BUDGET_BYTES, comparison_retention_allowance_bytes=COMPARISON_BYTES,
        untimed_comparison_oracle_seconds=oracle_seconds,
        work_budget=budget.statistics(), store_limits=asdict(LIMITS), compression=asdict(COMPRESSION),
        timings=timings,
        median_seconds={name: statistics.median(row['total_seconds'] for row in rows)
                        for name, rows in timings.items()},
        comparisons={name+'_vs_uncached': comparison(timings['uncached'], timings[name])
                     for name in ('cold_durable', 'warm_reopen', 'partial_resume')},
        partial_seed_plus_resume_vs_uncached=comparison(timings['uncached'], combined),
        checkpoint_ids=checkpoint_ids, matched_outputs=[output_record(item) for item in expected],
        scope='One frozen 3200-cell case, two cohorts, three consecutive requested outputs. '
              'Each measured run includes fresh motion/support or workflow preparation and closure; '
              'durable runs include store open/close. Warm means reopening a completed durable run '
              'with a fresh connection, not clearing operating-system caches. Partial resume starts '
              'from the saved first output: seed cost is excluded from resume and separately reported, '
              'including the paired seed-plus-resume total. Configuration, post-timing exact verification '
              'and source hashing are excluded. No source monkeypatching or timing subtraction is used. '
              'workflow_run_seconds combines verified read, calculation and storage; storage internal '
              'preparation/writer timers are separately recorded without replacing live functions. '
              'No full terrain '
              'run, scientific sweep, combined W05 acceptance or whole-generator speedup is claimed.',
        source_sha256=sources)
    payload = json.dumps(record, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(payload+'\n', encoding='utf-8')
        print(json.dumps({key: record[key] for key in ('status', 'median_seconds',
            'comparisons', 'partial_seed_plus_resume_vs_uncached')}, indent=2), flush=True)
    else:
        print(payload, flush=True)


if __name__ == '__main__':
    main()
