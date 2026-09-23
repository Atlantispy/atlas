#!/usr/bin/env python3
"""One bounded W06 Step-2 measurement, with matched scalar/vector geometry.

The four outputs are 0/5/10/20 Myr on 4000 cells. Three alternating medians
compare the same width/youngest/oldest fields. Full prepared setup/sequence and
same-state validation timings are separate; neither is a persistent-cache claim.
The frozen design and all measured source bytes must remain unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

THREAD_VARIABLES = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS')
for key in THREAD_VARIABLES:
    os.environ.setdefault(key, '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]

import numpy as np

from atlas_tectonics import (ColumnGrid1D, PreparedRidgeSpreading, RidgeMotion,
                             SpreadingPhase, ridge_cell_geometry)
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from w06_spreading_reference import reference_accounts, reference_geometry


def _measure_pair(reference, production):
    samples = [[], []]
    for repeat in range(3):
        for index in ((0, 1) if repeat % 2 == 0 else (1, 0)):
            start = time.perf_counter()
            (reference, production)[index]()
            samples[index].append(time.perf_counter()-start)
    baseline, actual = map(statistics.median, samples)
    return dict(reference_seconds=samples[0], production_seconds=samples[1],
                reference_median_seconds=baseline, production_median_seconds=actual,
                saved_seconds=baseline-actual, saved_percent=100.*(baseline-actual)/baseline,
                speedup=baseline/actual)


def _measure(function):
    samples = []
    for _ in range(3):
        start = time.perf_counter()
        function()
        samples.append(time.perf_counter()-start)
    return dict(seconds=samples, median_seconds=statistics.median(samples))


def _hashes(paths):
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    case_path = ROOT/'cases/w06_spreading.json'
    case = json.loads(case_path.read_text(encoding='utf-8'))
    design_path = ROOT/case['frozen_design']['path']
    if hashlib.sha256(design_path.read_bytes()).hexdigest() != case['frozen_design']['sha256']:
        raise ValueError('frozen Step-1 design changed; review is required, never automatically repin')
    paths = [case_path, design_path, Path(__file__), ROOT/'tests/w06_spreading_reference.py',
             *(ROOT/'src/atlas_tectonics'/name for name in (
                 '__init__.py', 'spreading.py', 'mesh.py', 'materials.py', 'regional.py',
                 'reuse.py', 'resources.py', '_validation.py'))]
    sources = _hashes(paths)
    owner = WorkBudget(case['work_budget_bytes'])
    left, right = case['domain_m']
    edges = np.linspace(left, right, 4001)
    grid = ColumnGrid1D(edges, frame_id=case['frame_id'], budget=owner)
    motion_args = dict(case['motion'])
    for side in ('left', 'right', 'ridge'):
        motion_args[side+'_velocity_m_s'] = motion_args.pop(side+'_velocity_m_per_year')/case['seconds_per_year']
    motion = RidgeMotion(**motion_args)
    phases = tuple(SpreadingPhase(**row) for row in case['phases'])
    times = tuple(years*case['seconds_per_year'] for years in case['output_years'])
    reference_args = {key: motion_args[key] for key in (
        'ridge_position_m', 'left_velocity_m_s', 'right_velocity_m_s', 'ridge_velocity_m_s')}
    common = dict(time_s=case['time_s'], epoch_id=case['epoch_id'], width_m=case['width_m'],
                  source_id=case['case_id'], budget=owner)

    def reference_sequence():
        return tuple(reference_geometry(edges, elapsed, **reference_args) for elapsed in times)

    def kernel_sequence():
        return tuple(ridge_cell_geometry(grid, motion, elapsed, budget=owner) for elapsed in times)

    # Explicit allowance for caller-retained arrays and the scalar reference's
    # arrays; plan work uses the same parent. This is byte admission, not RSS.
    # Eight complete geometry sequences leave generous room for simultaneous
    # references, timed returns, masks/differences and the last immutable state.
    geometry_bytes = 2*grid.cells*3*8
    caller_allowance = 8*len(times)*geometry_bytes + 16*grid.nbytes + 65536
    accuracy = []
    with owner.reserve(caller_allowance, category='w06-benchmark-caller'):
        expected = reference_sequence()
        actual = kernel_sequence()
        for elapsed, independent, production in zip(times, expected, actual):
            np.testing.assert_array_equal(production[..., 0] > 0., independent[..., 0] > 0.)
            width_error = float(np.max(np.abs(production[..., 0]-independent[..., 0])))
            age_error = float(np.max(np.abs(production[..., 1:]-independent[..., 1:])))
            if width_error > case['position_error_m'] or age_error > case['age_error_s']:
                raise ArithmeticError('matched-field independent geometry gate failed')
            accuracy.append(dict(elapsed_years=elapsed/case['seconds_per_year'],
                occupied_side_cells=int(np.sum(production[..., 0] > 0.)),
                maximum_width_error_m=width_error, maximum_age_error_s=age_error))
        kernel = _measure_pair(reference_sequence, kernel_sequence)

        def prepared_sequence():
            with PreparedRidgeSpreading(grid, motion, phases, **common) as plan:
                state = plan.initial
                for elapsed in times:
                    state = plan.advance(state, time_s=case['time_s']+elapsed)
                    plan.phase_thickness(state, budget=owner)
                return state

        # One correctness warm-up is excluded; each measured call constructs
        # and closes its own plan AND default source-validating context.
        final = prepared_sequence()
        np.testing.assert_array_equal(final.cell_geometry, actual[-1])
        accounts = reference_accounts(edges, times[-1], case['phases'],
                                       width_m=case['width_m'], **reference_args)
        epsilon = case['material_roundoff_eps_multiplier']*np.finfo(float).eps
        for index, phase in enumerate(phases):
            scale = max(abs(float(x)) for x in accounts[index, (0, 2, 3, 4)])
            np.testing.assert_allclose(final.accounts_kg[index, (0, 2, 3, 4)],
                accounts[index, (0, 2, 3, 4)], rtol=0., atol=epsilon*scale)
            if abs(float(final.accounts_kg[index, 5])) > epsilon*scale:
                raise ArithmeticError('material residual exceeds unchanged W02 roundoff policy')
            if abs(float(np.sum(final.accounts_kg[index, :2]))-phase.stock_kg) > epsilon*phase.stock_kg:
                raise ArithmeticError('finite source ledger does not close')
        prepared = _measure(prepared_sequence)
        with PreparedRidgeSpreading(grid, motion, phases, **common) as plan:
            state = plan.advance(plan.initial, time_s=case['time_s']+times[-1])

            def repeat_request():
                result = plan.advance(state, time_s=state.time_s)
                if result is not state:
                    raise ArithmeticError('same-time request did not retain the identical state')

            repeated = _measure(repeat_request)
        with ExecutionContext('reference') as context:
            execution_identity = context.identity
        final_accounts = final.accounts_kg.tolist()
    if _hashes(paths) != sources:
        raise ValueError('source changed during measurement; no result is accepted')
    budget_statistics = owner.statistics()
    if budget_statistics['reserved_bytes'] != 0:
        raise ArithmeticError('measurement left a work reservation retained')
    record = dict(schema='atlas.w06-spreading-measurement.v1',
        status='PASS_W06_STEP_2_BOUNDED_MEASUREMENT', case_id=case['case_id'],
        cells=grid.cells, outputs_years=case['output_years'], repeats=3,
        python=sys.version.split()[0], numpy=np.__version__, platform=platform.platform(),
        thread_environment={key: os.environ.get(key) for key in THREAD_VARIABLES},
        accuracy=accuracy, final_phase_accounts_kg=final_accounts,
        matched_four_output_geometry_comparison=kernel,
        setup_inclusive_prepared_sequence=prepared,
        same_state_request_validation=repeated,
        budget=budget_statistics, caller_allowance_bytes=caller_allowance,
        execution_identity=execution_identity, source_sha256=sources,
        scope='WORKING NON-CANON. Constant prescribed planar birth only, 4000 cells, two finite phases, four outputs. Matched scalar/vector fields are occupied width and youngest/oldest age; scalar reference independently integrates birth-time preimages. Prepared sequence includes new plan/context setup, four source-validated output requests, thickness projections and closure. Repeated output returns the identical immutable state after source validation; it is not a persistent-cache saving. No cooling, support, varying histories, workflow restart, empirical or whole-generator acceptance. Budget is accounted bytes, not measured process RSS.')
    payload = json.dumps(record, indent=2, allow_nan=False)+'\n'
    args.output.write_text(payload, encoding='utf-8')
    print(payload, end='', flush=True)


if __name__ == '__main__':
    main()
