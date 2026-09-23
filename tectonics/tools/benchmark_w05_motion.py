#!/usr/bin/env python3
"""Bounded W05 motion evidence; three alternating timing repeats, no terrain run.

Two matched-accuracy comparisons: cell integrals versus independent quadrature;
complete prepared output sequence with native versus Python inventory reductions.
The separate MUSCL diagnostic is NOT an accuracy-matched speedup baseline.
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

for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS'):
    os.environ.setdefault(key, '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
import numpy as np
import scipy
from atlas_tectonics import (ColumnGrid1D, ListricGeometry, MaterialCohort,
    PreparedListricExtension, hangingwall_cell_means)
from w05_reference import hanging_wall_means, boundary_exchanges


def timed_pair(first, second, repeats=3):
    samples = [[], []]
    for repeat in range(repeats):
        for index in ([0, 1] if repeat % 2 == 0 else [1, 0]):
            start = time.perf_counter()
            (first, second)[index]()
            samples[index].append(time.perf_counter()-start)
    before, after = map(statistics.median, samples)
    return dict(baseline_seconds=samples[0], optimised_seconds=samples[1],
                median_baseline_seconds=before, median_optimised_seconds=after,
                saved_seconds=before-after, saved_percent=100*(before-after)/before,
                speedup=before/after)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    case_path = ROOT/'cases/w05_motion.json'
    case = json.loads(case_path.read_text(encoding='utf-8'))
    geometry = ListricGeometry(case['crust_thickness_m'], case['detachment_depth_m'],
        case['surface_dip_rad'], case['trace_m'], case['case_id'])
    ref_geometry = dict(depth_m=geometry.detachment_depth_m,
                        decay_length_m=geometry.decay_length_m, trace_m=geometry.trace_m)
    u = case['velocity_m_per_year']/case['seconds_per_year']
    end = case['duration_years']*case['seconds_per_year']
    a = u*end
    common = dict(velocity_m_s=u, density_kg_m3=case['density_kg_m3'], width_m=case['width_m'],
        cohorts=(MaterialCohort('a', 'crust', 'synthetic-A', None),
                 MaterialCohort('b', 'crust', 'synthetic-B', -2*end)),
        fractions=(.25, .75), time_s=0., epoch_id=case['case_id'],
        datum_id='initial-flat-surface', source_id=case['case_id'])

    def grid(dx, domain=None):
        left, right = case['domain_m'] if domain is None else domain
        return ColumnGrid1D(np.linspace(left, right, round((right-left)/dx)+1), frame_id=case['case_id'])

    def crop(g):
        centres = (g.edges_m[1:]+g.edges_m[:-1])/2
        return (centres >= case['crop_m'][0]) & (centres <= case['crop_m'][1])

    accuracy = []
    final_surface = None
    for dx in case['grid_spacing_m']:
        g = grid(dx)
        expected = hanging_wall_means(g.edges_m, a, **ref_geometry)
        with PreparedListricExtension(g, geometry, **common) as plan:
            state = plan.advance(plan.initial, time_s=end)
            fields = plan.geometry_fields(state)
            mask = crop(g)
            error = np.abs(fields[:, 0]-expected)
            maximum = float(np.max(error[mask]))
            relative = float(np.sum(error[mask]*g.widths_m[mask]) /
                             np.sum(np.abs(expected[mask])*g.widths_m[mask]))
            if maximum > case['quadrature_comparison_atol_m'] or relative > case['finest_h_relative_l1']:
                raise ValueError('independent cell-mean gate failed')
            exchanges = boundary_exchanges(*case['domain_m'], a, **ref_geometry)
            np.testing.assert_allclose(state.exchange_m2,
                np.array(common['fractions'])[:, None]*np.array(exchanges), rtol=2e-13, atol=1e-8)
            accounts = state.material.transition_record['cumulative_cohort_accounts']
            accuracy.append(dict(dx_m=dx, cells=g.cells, maximum_crop_h_error_m=maximum,
                relative_crop_h_l1=relative, exchange_m2=state.exchange_m2.tolist(),
                max_cohort_balance_residual_m2=max(abs(row[4]) for row in accounts)))
            if dx == case['grid_spacing_m'][-1]:
                final_surface = fields[mask, 3]

    # Exact route has no numerical time step. These controls additionally prove
    # that requesting more snapshots cannot accumulate or duplicate movement.
    g = grid(case['grid_spacing_m'][1])
    partition_outputs = []
    with PreparedListricExtension(g, geometry, **common) as plan:
        direct = plan.advance(plan.initial, time_s=end)
        for count in (64, 128):
            state = plan.initial
            for index in range(count):
                state = plan.advance(state, time_s=end*(index+1)/count)
            np.testing.assert_array_equal(state.material.thickness_m, direct.material.thickness_m)
            np.testing.assert_array_equal(state.exchange_m2, direct.exchange_m2)
            partition_outputs.append(count)

    g = grid(case['grid_spacing_m'][-1], case['enlarged_domain_m'])
    with PreparedListricExtension(g, geometry, **common) as plan:
        state = plan.advance(plan.initial, time_s=end)
        difference = float(np.max(np.abs(plan.geometry_fields(state)[crop(g), 3]-final_surface)))
        if difference > case['domain_surface_difference_m']:
            raise ValueError('domain extension changed crop motion')

    g = grid(case['grid_spacing_m'][-1])
    reference = hanging_wall_means(g.edges_m, a, **ref_geometry)
    kernel_error = float(np.max(np.abs(hangingwall_cell_means(g, geometry, a)-reference)))
    kernel = timed_pair(lambda: hanging_wall_means(g.edges_m, a, **ref_geometry),
                        lambda: hangingwall_cell_means(g, geometry, a))

    preparation = {}
    plans = []
    try:
        for backend in ('reference', 'numba'):
            start = time.perf_counter()
            plans.append(PreparedListricExtension(g, geometry, backend=backend, **common))
            preparation[backend] = time.perf_counter()-start

        def sequence(plan):
            state = plan.initial
            for displacement in case['output_displacements_m'][1:]:
                state = plan.advance(state, time_s=displacement/u)
                fields = plan.geometry_fields(state)
            return state, fields

        before, after = sequence(plans[0]), sequence(plans[1])  # warm up, excluded
        np.testing.assert_allclose(before[1], after[1], rtol=0, atol=case['quadrature_comparison_atol_m'])
        np.testing.assert_array_equal(before[0].exchange_m2, after[0].exchange_m2)
        workflow = timed_pair(lambda: sequence(plans[0]), lambda: sequence(plans[1]))
        identities = [p.execution_id for p in plans]
    finally:
        for plan in plans:
            plan.close()

    # Recorded failure, not concealed or included in a matched-quality claim.
    with PreparedListricExtension(g, geometry, transport='muscl', **common) as plan:
        start = time.perf_counter()
        muscl = plan.advance(plan.initial, time_s=end, steps=128)
        muscl_seconds = time.perf_counter()-start
        error = float(np.max(np.abs(muscl.material.total_thickness()[crop(g)]-reference[crop(g)])))
    paths = [case_path, Path(__file__), ROOT/'tests/w05_reference.py',
             ROOT/'src/atlas_tectonics/extension.py', ROOT/'src/atlas_tectonics/reuse.py']
    record = dict(status='PASS_W05_STEP_2_MOTION', case_id=case['case_id'],
        python=sys.version.split()[0], numpy=np.__version__, scipy=scipy.__version__,
        platform=platform.platform(), threads=1, accuracy=accuracy,
        partition_counts=partition_outputs, partition_thickness_and_export='EXACT',
        domain_crop_surface_difference_m=difference, maximum_kernel_error_m=kernel_error,
        cell_integral_comparison=kernel, three_output_workflow_comparison=workflow,
        preparation_seconds=preparation, execution_identities=identities,
        muscl_diagnostic=dict(cells=g.cells, steps=128, seconds=muscl_seconds,
            maximum_crop_h_error_m=error, accepted=error <= case['finest_h_max_error_m'],
            note='Not a speedup baseline: MUSCL smooths the moving edge beyond the frozen 10 m gate.'),
        scope='3200-cell prescribed constant-speed listric family, 2 constant-fraction cohorts. Cell-integral baseline is independent adaptive quadrature; workflow baseline is the SAME exact method with Python reference inventory/total reductions versus native reductions. Three alternating repeats, prepared contexts, no disk cache, no workers. Workflow includes provenance, budgets, histories, exports and geometry fields at 3 output times. No support, full terrain, empirical or old-release timing claim.',
        source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    payload = json.dumps(record, indent=2, allow_nan=False)
    print(payload, flush=True)
    if args.output:
        args.output.write_text(payload+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
