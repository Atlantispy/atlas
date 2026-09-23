#!/usr/bin/env python3
"""Three setup-inclusive medians for W06 compute, publication and verified recovery.

One frozen 4000-cell constant ocean and changing-history ocean, plus the existing
two-layer inherited margin. No scalar/kernel rerun or whole-generator claim.
Each mode starts a fresh source context, physical plan and workflow. Recovery
also reopens SQLite; a filesystem cold-cache flush is neither requested nor used.
"""
import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import statistics
import sys
from tempfile import TemporaryDirectory
import time

THREAD_VARIABLES = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS')
for key in THREAD_VARIABLES:
    os.environ.setdefault(key, '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]

import numpy as np

from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.w06_workflow import PreparedW06Workflow
from w06_workflow_case import (ROUTES, CASE, COOLING, HISTORY, CALLER_ALLOWANCE,
    LIMITS, COMPRESSION, verify_frozen_design, route_fixture, open_store, checkpoint_signature)


def source_hashes():
    paths = [Path(__file__), ROOT/'docs/W06_SPREADING.md',
        *(ROOT/'cases'/name for name in ('w06_spreading.json', 'w06_cooling.json', 'w06_history.json')),
        *(ROOT/'tests'/name for name in ('w06_workflow_case.py', 'test_w06_workflow.py',
            'test_w06_spreading_cooling.py', 'test_w06_history_cooling.py', 'test_w06_margin_cooling.py',
            'precursor_fixtures.py', 'w06_cooling_reference.py', 'w06_history_reference.py')),
        *sorted((ROOT/'src/atlas_tectonics').glob('*.py'))]
    return {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def run_once(route, owner, *, path=None, through=None):
    """Timer covers preparation, run, inventory query and deterministic closure."""
    start = time.perf_counter()
    with route_fixture(route, budget=owner, cells=4000) as (prepared, policy, schedule):
        execution = prepared.execution_id if route == 'margin' else prepared.spreading.execution_id
        if path is None:
            with PreparedW06Workflow(prepared, schedule, margin_policy=policy) as workflow:
                output = workflow.run(through=through)
            storage = None
        else:
            with open_store(path, owner) as store:
                with PreparedW06Workflow(prepared, schedule, margin_policy=policy, store=store) as workflow:
                    output = workflow.run(through=through)
                    storage = store.statistics()
    duration = time.perf_counter()-start
    if owner.reserved_bytes != CALLER_ALLOWANCE:
        raise ArithmeticError('workflow measurement leaked a reservation')
    # Complete byte/state comparison and JSON hashing are outside timed work.
    return output, duration, execution, storage


def sample_summary(seconds):
    return dict(raw_seconds=seconds, median_seconds=statistics.median(seconds))


def percentage(baseline, measured):
    return 100.*(1.-measured/baseline)


def measure_route(route, directory):
    owner = WorkBudget(CASE['work_budget_bytes'])
    modes = ('no_store', 'cold_compute_publish', 'reopened_verified_warm', 'partial_continuation')
    timings = {name: [] for name in modes}
    final_storage, execution_ids = {}, set()
    with owner.reserve(CALLER_ALLOWANCE, category='w06-workflow-benchmark-caller'):
        expected, _, execution, _ = run_once(route, owner)
        expected_signature = checkpoint_signature(expected)
        execution_ids.add(execution)
        warm_path = directory/'complete.db'
        complete, _, _, _ = run_once(route, owner, path=warm_path)
        if checkpoint_signature(complete) != expected_signature:
            raise ArithmeticError('initial cold publication differs from no-store result')
        prefix_path = directory/'through-output-2.db'
        prefix, _, _, _ = run_once(route, owner, path=prefix_path, through=2)
        if prefix.output_index != 2:
            raise ArithmeticError('partial seed has wrong accepted endpoint')
        for repeat in range(3):
            # Backup seeding is explicit untimed pre-existing input preparation.
            # Each partial timing advances once from output 2, never from a
            # completed database left by a previous timing repetition.
            partial_path = directory/('partial-'+str(repeat)+'.db')
            with open_store(prefix_path, owner) as seed:
                seed.backup_to(partial_path)
            paths = dict(no_store=None,
                cold_compute_publish=directory/('cold-'+str(repeat)+'.db'),
                reopened_verified_warm=warm_path, partial_continuation=partial_path)
            order = modes[repeat:]+modes[:repeat]
            for mode in order:
                output, seconds, execution, storage = run_once(route, owner, path=paths[mode])
                if checkpoint_signature(output) != expected_signature:
                    raise ArithmeticError(route+' '+mode+' changed typed fields, accounts or provenance')
                if storage is not None and storage['snapshots'] != 4:
                    raise ArithmeticError('requested output history is incomplete')
                timings[mode].append(seconds)
                execution_ids.add(execution)
                if storage is not None:
                    # Do not embed duplicate budget records for every mode.
                    final_storage[mode] = {key: storage[key] for key in
                        ('snapshots', 'unique_chunks', 'encoded_payload_bytes', 'database_bytes',
                         'decoded_cache_bytes', 'operations', 'resource_allowances')}
        medians = {key: statistics.median(values) for key, values in timings.items()}
    budget = owner.statistics()
    if budget['reserved_bytes'] != 0:
        raise ArithmeticError('workflow measurement did not release all admission')
    if len(execution_ids) != 1:
        raise ValueError('execution identity changed between compared modes')
    return dict(route=route, cells=None if route == 'margin' else 4000,
        inherited_layers=2 if route == 'margin' else None,
        schedule_s=([1e12, 2e12, 1.01e14, 1.001e15] if route == 'margin'
                    else [years*CASE['seconds_per_year'] for years in CASE['output_years']]),
        samples={key: sample_summary(values) for key, values in timings.items()},
        percentages=dict(
            cold_publication_overhead_vs_no_store=100.*(medians['cold_compute_publish']/medians['no_store']-1.),
            warm_reduction_vs_cold_compute_publish=percentage(medians['cold_compute_publish'], medians['reopened_verified_warm']),
            warm_reduction_vs_no_store=percentage(medians['no_store'], medians['reopened_verified_warm']),
            partial_elapsed_reduction_vs_full_cold=percentage(medians['cold_compute_publish'], medians['partial_continuation'])),
        partial_comparison_warning='Partial starts with outputs 0-2 already accepted; this is a shorter workload, not an algorithmic speedup.',
        exact_typed_checkpoint_parity=True, final_signature=expected_signature,
        execution_identity=next(iter(execution_ids)), storage=final_storage, budget=budget)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if any(os.environ.get(key) != '1' for key in THREAD_VARIABLES):
        raise ValueError('all numerical thread counts must be one for this comparison')
    verify_frozen_design()
    before = source_hashes()
    routes = []
    with TemporaryDirectory(prefix='atlas-w06-workflow-') as temp:
        for route in ROUTES:
            directory = Path(temp)/route
            directory.mkdir()
            routes.append(measure_route(route, directory))
    if source_hashes() != before:
        raise ValueError('source changed during measurement; no result accepted')
    libraries = dict(numpy=np.__version__)
    for name in ('scipy', 'numba', 'zstandard'):
        try:
            libraries[name] = version(name)
        except PackageNotFoundError:
            libraries[name] = 'not installed'
    record = dict(schema='atlas.w06-workflow-measurement.v1',
        status='PASS_W06_STEP_5_BOUNDED_WORKFLOW_MEASUREMENT', repeats=3,
        frozen_design=CASE['frozen_design'], source_status='WORKING NON-CANON',
        python=sys.version.split()[0], platform=platform.platform(), libraries=libraries,
        thread_environment={key: os.environ[key] for key in THREAD_VARIABLES},
        scopes=dict(
            all_modes='Fresh source context, physical preparation and workflow; run to final requested output, inventory query and closure included. Byte-parity comparison is untimed. No process launch or filesystem-cache flush.',
            no_store='All four requested outputs computed sequentially, only final result retained, no storage.',
            cold_compute_publish='All four outputs computed and atomically published in a new SQLite store.',
            reopened_verified_warm='Reopen a complete store, verify full schedule/source bindings and decode final output without repeating completed thermal evolution. This is reopened warm I/O, not OS-cold I/O.',
            partial_continuation='Reopen an independently seeded copy containing outputs 0-2, restore output 2 and compute/publish output 3. Prefix computation and backup copying are excluded.',
            physical_domains='Constant ocean, history ocean and inherited margin are independent scenarios; their reservoirs are not spatially merged.'),
        routes=routes, codec=asdict(COMPRESSION), store_limits=asdict(LIMITS),
        caller_allowance_bytes=CALLER_ALLOWANCE, source_sha256=before,
        limits='128 MiB accounted admission, not RSS; 256 accepted-request ceiling unchanged. Exact recovery parity is measured here; independent science checks belong to the focused acceptance tests and retained Steps 3/4 evidence. No empirical, whole-terrain or production-ready claim.')
    args.output.write_text(json.dumps(record, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(status=record['status'], output=str(args.output), routes=[dict(
        route=row['route'], samples=row['samples'], percentages=row['percentages'],
        exact_typed_checkpoint_parity=row['exact_typed_checkpoint_parity'],
        peak_accounted_bytes=row['budget']['peak_reserved_bytes']) for row in routes]),
        indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
