#!/usr/bin/env python3
"""Bounded W06.4 history measurement, not a persistent-cache benchmark.

Three alternating medians compare the same field/account subset on 256 fixed
cells at 20 Myr. Separately, 4000 cells/four outputs compare fresh preparation
for each output against one reused preparation, including setup in both paths.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys

THREAD_VARIABLES = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS')
for key in THREAD_VARIABLES:
    os.environ.setdefault(key, '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'), str(ROOT/'tools')]

import numpy as np
import scipy

from atlas_tectonics.resources import WorkBudget
from benchmark_w06_cooling import _check_fields, _hashes, _measure, _measure_pair
from test_w06_history_cooling import HISTORY, BIRTH, COOLING, YEAR, history_fixture, reference_history
from w06_cooling_reference import CoolingReference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    design = ROOT/HISTORY['frozen_design']['path']
    if (HISTORY['frozen_design'] != COOLING['frozen_design']
            or hashlib.sha256(design.read_bytes()).hexdigest() != HISTORY['frozen_design']['sha256']):
        raise ValueError('frozen history design changed; never automatically repin')
    paths = [design, Path(__file__), ROOT/'tools/benchmark_w06_cooling.py',
             *(ROOT/'cases'/name for name in ('w06_history.json', 'w06_spreading.json', 'w06_cooling.json')),
             *(ROOT/'tests'/name for name in ('w06_history_reference.py', 'w06_cooling_reference.py',
                 'w06_spreading_reference.py', 'test_w06_history_cooling.py', 'test_w06_spreading_cooling.py')),
             *sorted((ROOT/'src/atlas_tectonics').glob('*.py'))]
    sources = _hashes(paths)
    owner = WorkBudget(HISTORY['work_budget_bytes'])
    elapsed = HISTORY['duration_years']*YEAR
    matched_edges = np.linspace(*HISTORY['crop_m'], 257)
    full_edges = np.linspace(*HISTORY['domain_m'], 4001)
    caller_allowance = 24*1024**2
    with owner.reserve(caller_allowance, category='w06-history-benchmark-caller'):
        with history_fixture(edges=matched_edges, budget=owner) as plan:
            execution_id = plan.spreading.execution_id

            def scalar_output():
                reference = reference_history(bounds=HISTORY['crop_m'])
                thermal = CoolingReference(COOLING, BIRTH['phases'])
                fields = reference.thermal_fields(matched_edges, elapsed, thermal)
                fields['heat_accounts_j'], fields['water_accounts_m3'] = reference.thermal_accounts(elapsed, thermal, width_m=BIRTH['width_m'])
                return fields

            def production_output():
                return plan.advance(plan.initial, time_s=elapsed)

            expected, actual = scalar_output(), production_output()
            thermal = CoolingReference(COOLING, BIRTH['phases'])
            accuracy = dict(cell_means=_check_fields(actual.cell_values, expected['cell_values'], thermal.energy),
                            centres=_check_fields(actual.centre_values, expected['centre_values'], thermal.energy))
            np.testing.assert_array_equal(actual.centre_valid, expected['centre_valid'])
            np.testing.assert_allclose(actual.ocean_fraction, expected['ocean_fraction'], rtol=0., atol=1.e-12)
            age_error = float(np.max(np.abs(actual.motion.centre_age_s-expected['centre_age_s'])))
            if age_error > HISTORY['age_error_s']:
                raise ArithmeticError('independent history age gate failed')
            heat, water = expected['heat_accounts_j'], expected['water_accounts_m3']
            scale = max(heat[0], math.fsum(abs(v) for v in heat[[2, 4, 6, 7]]), 1.)
            heat_error = float(np.max(np.abs(actual.heat_accounts_j[:9]-heat[:9]))/scale)
            water_error = float(np.max(np.abs(actual.water_accounts_m3[:5]-water[:5])))
            if (heat_error > COOLING['heat_relative_error']
                    or abs(heat[-1]) > COOLING['reference_heat_relative_error']
                    or abs(actual.heat_accounts_j[-1]) > COOLING['heat_relative_error']
                    or water_error > heat[0]/thermal.energy*COOLING['support_error_m']):
                raise ArithmeticError('independent history heat/water account gate failed')
            accuracy.update(centre_age_error_s=age_error, heat_account_normalised_error=heat_error,
                production_heat_normalised_residual=float(actual.heat_accounts_j[-1]),
                reference_heat_normalised_residual=float(heat[-1]), water_account_error_m3=water_error)
            matched = _measure_pair(scalar_output, production_output)

        def fresh_each_output():
            outputs = []
            for years in HISTORY['output_years']:
                with history_fixture(edges=full_edges, budget=owner) as plan:
                    outputs.append(plan.advance(plan.initial, time_s=years*YEAR))
            return tuple(outputs)

        def reused_sequence():
            outputs = []
            with history_fixture(edges=full_edges, budget=owner) as plan:
                state = plan.initial
                for years in HISTORY['output_years']:
                    state = plan.advance(state, time_s=years*YEAR)
                    outputs.append(state)
            return tuple(outputs)

        fresh, reused = fresh_each_output(), reused_sequence()
        for first, second in zip(fresh, reused):
            for name in ('cell_values', 'centre_values', 'heat_accounts_j', 'water_accounts_m3'):
                np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
            np.testing.assert_array_equal(first.motion.centre_age_s, second.motion.centre_age_s)
        full_heat, full_water = reference_history().thermal_accounts(elapsed, thermal, width_m=BIRTH['width_m'])
        np.testing.assert_allclose(reused[-1].heat_accounts_j[:9], full_heat[:9], rtol=0.,
                                   atol=full_heat[0]*COOLING['heat_relative_error'])
        np.testing.assert_allclose(reused[-1].water_accounts_m3[:5], full_water[:5], rtol=0.,
                                   atol=900000.*COOLING['support_error_m'])
        preparation = _measure_pair(fresh_each_output, reused_sequence)
        # Name these paths explicitly: the scalar reference above and the
        # fresh-preparation baseline below are different measurement scopes.
        preparation['fresh_each_output_seconds'] = preparation.pop('reference_seconds')
        preparation['reused_sequence_seconds'] = preparation.pop('production_seconds')
        preparation['fresh_each_output_median_seconds'] = preparation.pop('reference_median_seconds')
        preparation['reused_sequence_median_seconds'] = preparation.pop('production_median_seconds')
        with history_fixture(edges=full_edges, budget=owner) as plan:
            state = plan.advance(plan.initial, time_s=elapsed)

            def repeated_state():
                if plan.advance(state, time_s=state.time_s) is not state:
                    raise ArithmeticError('same-state request did not preserve object identity')

            repeat = _measure(repeated_state)
        final_heat, final_water = reused[-1].heat_accounts_j.tolist(), reused[-1].water_accounts_m3.tolist()
    if _hashes(paths) != sources:
        raise ValueError('source changed during measurement; no result accepted')
    budget = owner.statistics()
    if budget['reserved_bytes']:
        raise ArithmeticError('history measurement leaked a reservation')
    record = dict(schema='atlas.w06-history-measurement.v1', status='PASS_W06_STEP_4_BOUNDED_MEASUREMENT',
        case_id=HISTORY['case_id'], scenario='motion_switch', repeats=3,
        python=sys.version.split()[0], numpy=np.__version__, scipy=scipy.__version__, platform=platform.platform(),
        thread_environment={key: os.environ.get(key) for key in THREAD_VARIABLES}, accuracy=accuracy,
        matched_scope=dict(cells=256, bounds_m=HISTORY['crop_m'], elapsed_years=HISTORY['duration_years'],
            subset='Occupied phase means, sheet anomaly, subsidence/depth, cumulative top/base heat; centres and masks; heat/water source/resident/first-exit accounts. Production also builds mass/event/ownership records and checks source identity. Fresh scalar reference each repetition; no prior output lookup.'),
        matched_single_output_comparison=matched,
        full_scope=dict(cells=4000, bounds_m=HISTORY['domain_m'], output_years=HISTORY['output_years'],
            baseline='New grid, parameters, source context and both plans for EACH of four direct outputs.',
            reused='New grid, parameters, source context and both plans ONCE, then four sequential outputs.'),
        setup_inclusive_preparation_reuse=preparation, same_state_source_validated_request=repeat,
        final_full_heat_accounts_j=final_heat, final_full_water_accounts_m3=final_water,
        budget=budget, caller_allowance_bytes=caller_allowance, execution_identity=execution_id, source_sha256=sources,
        scope='WORKING NON-CANON. Frozen two-interval motion switch, exact affine birth/first-exit histories and unchanged W06.3 thermal model. 128 MiB accounted admission, not RSS. The 256-cell scalar comparison and 4000-cell setup-reuse comparison are distinct; do not add their savings or extrapolate to whole-generator performance. No persistent-cache/restart, arbitrary ridge-jump, reentry, deformation or empirical acceptance claim.')
    payload = json.dumps(record, indent=2, allow_nan=False)+'\n'
    args.output.write_text(payload, encoding='utf-8')
    print(json.dumps(dict(status=record['status'], output=str(args.output), matched=matched,
        prepared_reuse=preparation, repeated=repeat, accuracy=accuracy,
        peak_accounted_bytes=budget['peak_reserved_bytes']), indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
