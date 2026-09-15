"""Bounded control-sensitivity experiment on the actual connected R4 recipe.

No physical coefficient, layer, forcing or accuracy tolerance is adjusted.
Minimum step/work limits are explicit experiment dimensions, never fallbacks.
"""
from fractions import Fraction as F
import json
from pathlib import Path
import sys
import time

from . import binding


def strict_recipe(bundle, *, minimum_dt=1e-4, max_steps=1000):
    recipe = bundle.reference.recipe()
    recipe['physical_recipe']['coupling_controls'].update(
        initial_dt_seconds=120, max_dt_seconds=120, min_dt_seconds=1)
    recipe['physical_recipe']['water_controls'].update(
        theta_atol=1e-8, head_atol_m=1e-8, flux_integral_atol_m=1e-10,
        relative_tolerance=1e-6, nonlinear_mass_atol_m=1e-12,
        total_mass_atol_m=1e-10, min_dt_s=minimum_dt, max_steps=max_steps)
    return recipe


def trial_report(bundle, recipe, *, seconds=30):
    p = bundle.pipeline
    model = p.parse(recipe, bundle.source_sha256)
    scenario = model.scenarios[0]
    initial = p.initial(model, scenario)
    before = p.serialise({'selected': initial}, 0)
    calls = []
    def profile(frame, event, value):
        if event == 'return' and frame.f_code is bundle.solver.advance.__code__:
            col = frame.f_locals['column']
            row = {'column_id': col.column_id, 'thicknesses_m': [l.thickness_m for l in col.layers],
                   'status': value['status'], 'reason': value.get('reason'),
                   'diagnostics': value.get('diagnostics'), 'numerics': value.get('numerics'),
                   'water_residual_m': None if value['ledger'] is None else value['ledger']['water_residual_m']}
            calls.append(row)
    previous = sys.getprofile()
    started = time.perf_counter()
    failure = None
    following = None
    try:
        sys.setprofile(profile)
        following = p.trial(model, initial, recipe['events'][0], scenario, F(seconds))
    except p.r3.CoupledStepFailure as exc:
        failure = str(exc)
    finally:
        sys.setprofile(previous)
    elapsed = time.perf_counter()-started
    if p.serialise({'selected': initial}, 0) != before:
        raise AssertionError('isolated trial changed its antecedent state')
    result = {'status': 'MODELLED' if following is not None else 'NUMERICAL_FAILURE',
              'failure': failure, 'trial_seconds': seconds, 'scenario_id': scenario.scenario_id,
              'source_sha256': bundle.source_sha256, 'recipe': recipe,
              'input_state_unchanged': True, 'solver_calls': calls,
              'elapsed_wall_seconds': elapsed,
              'timing_interpretation': 'diagnostic cost, not a matched performance improvement'}
    if following is not None:
        result['following_state'] = p.serialise({'selected': following}, 0)
    return result


def run(output):
    bundle = binding.load()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cases = [('original_limits', 1e-4, 1000), ('finer_minimum_only', 1e-8, 1000),
             ('finer_minimum_and_larger_budget', 1e-8, 10000)]
    results = {}
    for name, minimum, budget in cases:
        report = trial_report(bundle, strict_recipe(bundle, minimum_dt=minimum, max_steps=budget))
        raw = json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode('utf-8')+b'\n'
        with (output/(name+'.json')).open('xb') as handle:
            handle.write(raw)
        results[name] = {key: report[key] for key in ('status','failure','elapsed_wall_seconds')}
        print(name, json.dumps(results[name]), flush=True)
    return results


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: python -m work.generator_upgrade_r5.experiments NEW_OUTPUT_DIRECTORY')
    run(sys.argv[1])
