#!/usr/bin/env python3
"""Bounded W06.3 matched-output and protected full-run measurements.

Three alternating medians compare scalar adaptive depth/age integration with
the production assembled output on exactly 256 fixed cells at 20 Myr. Full
4000-cell, four-output preparation and repeated-state validation are separate.
No persistent cache, RSS bound or whole-generator performance claim is made.
"""
import argparse
import hashlib
import json
import math
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
import scipy

from atlas_tectonics.resources import WorkBudget
from test_w06_spreading_cooling import (CASE, COOLING, YEAR, cooling_fixture,
                                        field_errors, reference_motion)
from w06_cooling_reference import CoolingReference


def _measure(function):
    samples = []
    for _ in range(COOLING['benchmark_repeats']):
        start = time.perf_counter()
        function()
        samples.append(time.perf_counter()-start)
    return dict(seconds=samples, median_seconds=statistics.median(samples))


def _measure_pair(reference, production):
    samples = [[], []]
    for repeat in range(COOLING['benchmark_repeats']):
        for index in ((0, 1) if repeat % 2 == 0 else (1, 0)):
            start = time.perf_counter()
            (reference, production)[index]()
            samples[index].append(time.perf_counter()-start)
    scalar, vector = map(statistics.median, samples)
    return dict(reference_seconds=samples[0], production_seconds=samples[1],
        reference_median_seconds=scalar, production_median_seconds=vector,
        saved_seconds=scalar-vector, saved_percent=100.*(scalar-vector)/scalar,
        speedup=scalar/vector)


def _hashes(paths):
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _check_fields(actual, expected, energy):
    error = field_errors(actual, expected)
    contrast = COOLING['compensation_density_kg_m3']-COOLING['water_density_kg_m3']
    gates = dict(temperature_k=COOLING['mean_temperature_error_k'],
        sheet_kg_m2=contrast*COOLING['support_error_m'], subsidence_m=COOLING['support_error_m'],
        depth_m=COOLING['support_error_m'], heat_j_m2=energy*COOLING['heat_relative_error'])
    if any(error[key] > limit for key, limit in gates.items()):
        raise ArithmeticError('independent matched-field accuracy gate failed')
    return error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    design = ROOT/COOLING['frozen_design']['path']
    if (COOLING['frozen_design'] != CASE['frozen_design']
            or hashlib.sha256(design.read_bytes()).hexdigest() != COOLING['frozen_design']['sha256']):
        raise ValueError('frozen Step-1 design changed; do not automatically repin')
    # Hash the complete numerical package as well as the exact benchmark,
    # fixture, independent reference and frozen inputs before/after measurement.
    paths = [design, Path(__file__), ROOT/'cases/w06_cooling.json', ROOT/'cases/w06_spreading.json',
             ROOT/'tests/test_w06_spreading_cooling.py', ROOT/'tests/w06_cooling_reference.py',
             ROOT/'tests/w06_spreading_reference.py', *sorted((ROOT/'src/atlas_tectonics').glob('*.py'))]
    sources = _hashes(paths)
    owner = WorkBudget(CASE['work_budget_bytes'])
    elapsed = CASE['duration_years']*YEAR
    matched_cells = COOLING['benchmark_matched_cells']
    matched_edges = np.linspace(*CASE['crop_m'], matched_cells+1)
    full_edges = np.linspace(*CASE['domain_m'], 4001)
    # Explicit caller allowance for simultaneous outputs, scalar exact-key
    # caches, reference/difference arrays and immutable prepared states. This is
    # conservative admission, not a measured resident-memory guarantee.
    caller_allowance = 16*1024**2
    with owner.reserve(caller_allowance, category='w06-cooling-benchmark-caller'):
        with cooling_fixture(edges=matched_edges, budget=owner) as plan:
            motion = reference_motion(plan.spreading.motion)
            execution_id = plan.spreading.execution_id

            def scalar_output():
                # Fresh cache per run: only exact repeated intervals/ages
                # INSIDE this output are reused. No timed prior result lookup.
                reference = CoolingReference(COOLING, CASE['phases'])
                fields = reference.fields(matched_edges, elapsed, **motion)
                fields['heat_accounts_j'], fields['water_accounts_m3'] = reference.accounts(
                    matched_edges[[0, -1]], elapsed, width_m=CASE['width_m'], **motion)
                fields['maximum_reported_dimensionless_quad_error'] = reference.max_quad_error
                return fields

            def production_output():
                return plan.advance(plan.initial, time_s=CASE['time_s']+elapsed)

            expected, actual = scalar_output(), production_output()
            reference = CoolingReference(COOLING, CASE['phases'])
            accuracy = dict(cell_means=_check_fields(actual.cell_values, expected['cell_values'], reference.energy),
                            centres=_check_fields(actual.centre_values, expected['centre_values'], reference.energy))
            np.testing.assert_array_equal(actual.centre_valid, expected['centre_valid'])
            np.testing.assert_allclose(actual.ocean_fraction, expected['ocean_fraction'], rtol=0., atol=1.e-12)
            heat, water = expected['heat_accounts_j'], expected['water_accounts_m3']
            scale = max(heat[0], math.fsum(abs(v) for v in heat[[2, 4, 6, 7]]), 1.)
            heat_error = float(np.max(np.abs(actual.heat_accounts_j[:9]-heat[:9]))/scale)
            water_error = float(np.max(np.abs(actual.water_accounts_m3[:5]-water[:5])))
            created_area = heat[0]/reference.energy
            if (heat_error > COOLING['heat_relative_error']
                    or abs(heat[-1]) > COOLING['reference_heat_relative_error']
                    or abs(actual.heat_accounts_j[-1]) > COOLING['heat_relative_error']
                    or water_error > created_area*COOLING['support_error_m']):
                raise ArithmeticError('independent moving-domain heat/water gate failed')
            accuracy.update(heat_account_normalised_error=heat_error,
                production_heat_normalised_residual=float(actual.heat_accounts_j[-1]),
                reference_heat_normalised_residual=float(heat[-1]), water_account_error_m3=water_error,
                reference_maximum_reported_dimensionless_quad_error=expected['maximum_reported_dimensionless_quad_error'])
            tighter = CoolingReference(COOLING, CASE['phases'], tolerance=5.e-14)
            audit = field_errors(reference.mean(0., elapsed)[None, :], tighter.mean(0., elapsed)[None, :])
            if (audit['temperature_k'] > COOLING['reference_temperature_error_k']
                    or audit['subsidence_m'] > COOLING['reference_support_error_m']
                    or audit['heat_j_m2']/reference.energy > COOLING['reference_heat_relative_error']):
                raise ArithmeticError('tightened independent quadrature control failed')
            accuracy['tightened_reference_control'] = audit
            matched = _measure_pair(scalar_output, production_output)
            matched_accounts = actual.heat_accounts_j.tolist(), actual.water_accounts_m3.tolist()

        def full_sequence():
            # Includes grid, materials, source-validating context, both plans,
            # all four source-validated outputs and closure; no shared context.
            with cooling_fixture(edges=full_edges, budget=owner) as prepared:
                state, outputs = prepared.initial, []
                for years in CASE['output_years']:
                    state = prepared.advance(state, time_s=CASE['time_s']+years*YEAR)
                    outputs.append(state)
                return tuple(outputs)

        outputs = full_sequence()  # Untimed correctness warm-up.
        full = _measure(full_sequence)
        final = outputs[-1]
        heat, water = reference.accounts(CASE['domain_m'], elapsed, width_m=CASE['width_m'], **motion)
        np.testing.assert_allclose(final.heat_accounts_j[:9], heat[:9], rtol=0.,
                                   atol=heat[0]*COOLING['heat_relative_error'])
        np.testing.assert_allclose(final.water_accounts_m3[:5], water[:5], rtol=0.,
                                   atol=800000.*COOLING['support_error_m'])
        with cooling_fixture(edges=full_edges, budget=owner) as prepared:
            state = prepared.advance(prepared.initial, time_s=CASE['time_s']+elapsed)

            def repeat_state():
                result = prepared.advance(state, time_s=state.time_s)
                if result is not state:
                    raise ArithmeticError('same-time validated result lost immutable object identity')

            repeated = _measure(repeat_state)
        final_heat, final_water = final.heat_accounts_j.tolist(), final.water_accounts_m3.tolist()
    if _hashes(paths) != sources:
        raise ValueError('source changed during measurement; no result accepted')
    statistics_budget = owner.statistics()
    if statistics_budget['reserved_bytes']:
        raise ArithmeticError('measurement leaked a reservation')
    record = dict(schema='atlas.w06-cooling-measurement.v1', status='PASS_W06_STEP_3_BOUNDED_MEASUREMENT',
        case_id=COOLING['case_id'], repeats=COOLING['benchmark_repeats'],
        python=sys.version.split()[0], numpy=np.__version__, scipy=scipy.__version__, platform=platform.platform(),
        thread_environment={key: os.environ.get(key) for key in THREAD_VARIABLES},
        matched_scope=dict(cells=matched_cells, bounds_m=CASE['crop_m'], elapsed_years=CASE['duration_years'],
            fields=['phase temperatures', 'sheet anomaly', 'subsidence', 'water depth', 'top/base outward cumulative heat'],
            projections=['occupied cell means', 'valid centre samples', 'ocean fraction', 'centre mask'],
            accounts=['birth/basal/surface/resident/export heat', 'draw/resident/export water'],
            note='Identical field/account subset. Production additionally computes mass history, export records and validates identities; scalar reference performs independent adaptive age AND depth integration. Both regenerate an output; neither reads a prior cached result.'),
        accuracy=accuracy, matched_single_output_comparison=matched,
        protected_full_scope=dict(cells=4000, bounds_m=CASE['domain_m'], output_years=CASE['output_years']),
        setup_inclusive_full_four_output_sequence=full, same_state_source_validated_request=repeated,
        matched_heat_accounts_j=matched_accounts[0], matched_water_accounts_m3=matched_accounts[1],
        final_full_heat_accounts_j=final_heat, final_full_water_accounts_m3=final_water,
        budget=statistics_budget, caller_allowance_bytes=caller_allowance, execution_identity=execution_id,
        source_sha256=sources,
        scope='WORKING NON-CANON. Constant prescribed planar ocean birth, two hot finite solid phases, conductive plate cooling and single-owner column support. Heat/water exports freeze at boundary exit. 128 MiB accounted work envelope, not RSS. The matched comparison is only 256 fixed cells at one output; do not extrapolate its speedup to the separately measured full 4000-cell sequence. No persistent-cache, piecewise history, restart, inherited continent, empirical or whole-generator acceptance claim.')
    payload = json.dumps(record, indent=2, allow_nan=False)+'\n'
    args.output.write_text(payload, encoding='utf-8')
    print(json.dumps(dict(status=record['status'], output=str(args.output),
        matched=matched, full=full, repeated=repeated, accuracy=accuracy,
        peak_accounted_bytes=statistics_budget['peak_reserved_bytes']), indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
