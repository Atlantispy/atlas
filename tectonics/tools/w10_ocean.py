"""Bounded observational challenge; no fitting, downloads or file writes.

The baseline is the frozen synthetic W06 case, not an Earth calibration.
Published quartiles describe dispersion, not calibrated confidence intervals.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from atlas_tectonics.parameters import ThermalParameters, PlateCoolingParameters, identity
from atlas_tectonics.plate_cooling import finite_plate_temperature
from atlas_tectonics.resources import WorkBudget

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / 'cases/w10_ocean_heatflow_r1.json'
SCREEN = dict(age_min_ma=40., age_max_ma=165., expected_bins=50,
              dispersion_divisor=1.349, maximum_rms_scaled_residual=1.,
              depth_steps_m=[10., 5., 2.5], maximum_finest_flux_change_w_m2=1e-8,
              sensitivity_factors=[.8, 1.2], work_budget_bytes=16*1024*1024)
COLUMNS = ['age_ma', 'count', 'mean_w_m2', 'median_w_m2',
           'lower_quartile_w_m2', 'upper_quartile_w_m2', 'bin_width_ma']


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_case(case):
    """Refuse incomplete bins, altered screen, malformed units or quartiles."""
    if (case.get('schema') != 'atlas.w10-ocean-heatflow.v1'
            or case.get('screen') != SCREEN or case.get('columns') != COLUMNS):
        raise ValueError('W10 schema, units or predeclared screen changed')
    rows = case.get('observations')
    if (not isinstance(rows, list) or len(rows) != 50
            or any(not isinstance(row, list) or len(row) != 7 for row in rows)
            or any(type(v) not in (int, float) for row in rows for v in row)):
        raise ValueError('exactly 50 complete numeric observation rows required')
    data = np.asarray(rows, dtype=float)
    if (not np.all(np.isfinite(data)) or np.any(data <= 0)
            or not np.array_equal(data[:, 0], 41.25+2.5*np.arange(50))
            or not np.all(data[:, 6] == 2.5)
            or not np.all(data[:, 1] == np.floor(data[:, 1]))
            or np.any(data[:, 4] > data[:, 3])
            or np.any(data[:, 3] > data[:, 5])
            or np.any(data[:, 4] >= data[:, 5])):
        raise ValueError('invalid observation ages, counts, widths or quartiles')
    return data


def load_case(path=CASE_PATH):
    payload = Path(path).read_bytes()
    case = json.loads(payload)
    validate_case(case)
    return case, _sha(payload)


def baseline_parameters(case):
    """Check original bytes and constants before forming the thermal parameters."""
    binding = case['model']
    records = {}
    for name in ('case', 'spreading'):
        expected_path = 'cases/w06_cooling.json' if name == 'case' else 'cases/w06_spreading.json'
        if binding[name+'_path'] != expected_path:
            raise ValueError('W10 must retain the original W06 source paths')
        payload = (ROOT / expected_path).read_bytes()
        if _sha(payload) != binding[name+'_sha256']:
            raise ValueError('frozen W06 source bytes changed; do not repin')
        records[name] = json.loads(payload)
    source = records['case']
    constants = binding['constants']
    expected_keys = {'surface_temperature_k', 'base_temperature_k',
                     'plate_thickness_m', 'diffusivity_m2_s', 'conductivity_w_m_k'}
    if (set(constants) != expected_keys or source['case_id'] != binding['case_id']
            or any(source[k] != v for k, v in constants.items())
            or records['spreading']['seconds_per_year'] != binding['seconds_per_year']):
        raise ValueError('frozen W06 constants or clock changed; no calibration allowed')
    thermal = ThermalParameters(source['case_id'], 'Unfitted frozen synthetic W06 case',
        source['surface_temperature_k'], source['base_temperature_k'], source['diffusivity_m2_s'])
    return PlateCoolingParameters(thermal, source['plate_thickness_m'], source['conductivity_w_m_k'])


def surface_flux(age_ma, parameters, seconds_per_year, step_m, budget):
    """Positive outward surface heat flux from a second-order depth derivative."""
    ages = np.asarray(age_ma, dtype=float)
    if (ages.ndim != 1 or not 1 <= ages.size <= 150 or not np.all(np.isfinite(ages))
            or np.any(ages <= 0) or not np.isfinite(step_m) or step_m <= 0
            or 2*step_m > parameters.thickness_m
            or not np.isfinite(seconds_per_year) or seconds_per_year <= 0):
        raise ValueError('finite positive ages, clock and resolved surface stencil required')
    temperatures = finite_plate_temperature(np.array([0., step_m, 2*step_m]),
        (ages*1e6*seconds_per_year)[:, None], parameters, budget=budget)
    differences = temperatures[:, 1:]-temperatures[:, :1]
    flux = parameters.conductivity_w_m_k*(4*differences[:, 0]-differences[:, 1])/(2*step_m)
    if not np.all(np.isfinite(flux)) or np.any(flux <= 0):
        raise ValueError('surface flux is non-finite or non-positive')
    return flux


def comparison(data, prediction):
    prediction = np.asarray(prediction, dtype=float)
    if prediction.shape != (len(data),) or not np.all(np.isfinite(prediction)):
        raise ValueError('one finite heat-flow prediction per observation required')
    residual = prediction-data[:, 3]
    sigma = (data[:, 5]-data[:, 4])/SCREEN['dispersion_divisor']
    scaled = residual/sigma
    rms = float(np.sqrt(np.mean(scaled**2)))
    inside = (prediction >= data[:, 4]) & (prediction <= data[:, 5])
    return dict(rms_scaled_residual=rms,
        rms_residual_w_m2=float(np.sqrt(np.mean(residual**2))),
        mean_signed_residual_w_m2=float(np.mean(residual)),
        max_absolute_residual_w_m2=float(np.max(abs(residual))),
        quartile_coverage_count=int(np.count_nonzero(inside)),
        quartile_coverage_fraction=float(np.mean(inside)),
        dispersion_verdict=('CONSISTENT_WITH_OBSERVED_DISPERSION' if rms <= 1.
                            else 'NOT_CONSISTENT_WITH_OBSERVED_DISPERSION'))


def _evaluate(ages, parameters, seconds_per_year, budget):
    values = [surface_flux(ages, parameters, seconds_per_year, step, budget)
              for step in SCREEN['depth_steps_m']]
    deltas = [float(np.max(abs(b-a))) for a, b in zip(values, values[1:])]
    return values[-1], dict(depth_steps_m=SCREEN['depth_steps_m'],
        max_successive_change_w_m2=deltas,
        passed=deltas[-1] < SCREEN['maximum_finest_flux_change_w_m2'])


def run_challenge():
    """Return complete JSON-compatible evidence without selecting a better fit."""
    started = time.perf_counter()
    case, case_sha = load_case()
    data = validate_case(case)
    parameters = baseline_parameters(case)
    baseline_id = identity(parameters)
    seconds_per_year = case['model']['seconds_per_year']
    budget = WorkBudget(SCREEN['work_budget_bytes'])
    predictions, refinement = _evaluate(data[:, 0], parameters, seconds_per_year, budget)
    baseline = comparison(data, predictions)
    sensitivity = []
    for variable in ('conductivity_w_m_k', 'diffusivity_m2_s', 'thickness_m', 'temperature_contrast_k'):
        for factor in SCREEN['sensitivity_factors']:
            if variable == 'diffusivity_m2_s':
                variant = replace(parameters, thermal=replace(parameters.thermal,
                    diffusivity_m2_s=parameters.thermal.diffusivity_m2_s*factor))
            elif variable == 'temperature_contrast_k':
                th = parameters.thermal
                variant = replace(parameters, thermal=replace(th,
                    mantle_temperature_k=th.surface_temperature_k+
                    (th.mantle_temperature_k-th.surface_temperature_k)*factor))
            else:
                variant = replace(parameters, **{variable: getattr(parameters, variable)*factor})
            values, check = _evaluate(data[:, 0], variant, seconds_per_year, budget)
            sensitivity.append(dict(variable=variable, factor=factor,
                parameter_id=identity(variant), numerical_refinement=check,
                metrics=comparison(data, values), predicted_flux_w_m2=values.tolist()))
    edge_results = []
    for sign in (-1, 1):
        values, check = _evaluate(data[:, 0]+sign*data[:, 6]/2, parameters, seconds_per_year, budget)
        edge_results.append(dict(edge='younger' if sign == -1 else 'older',
            numerical_refinement=check, metrics=comparison(data, values),
            max_change_from_bin_centres_w_m2=float(np.max(abs(values-predictions))),
            predicted_flux_w_m2=values.tolist()))
    rows = []
    for row, prediction in zip(data, predictions):
        record = dict(zip(COLUMNS, row.tolist()))
        record['count'] = int(record['count'])
        sigma = (row[5]-row[4])/SCREEN['dispersion_divisor']
        record.update(predicted_flux_w_m2=float(prediction),
            residual_w_m2=float(prediction-row[3]), dispersion_scale_w_m2=float(sigma),
            scaled_residual=float((prediction-row[3])/sigma),
            within_quartiles=bool(row[4] <= prediction <= row[5]))
        rows.append(record)
    numeric_pass = refinement['passed'] and all(
        x['numerical_refinement']['passed'] for x in sensitivity+edge_results)
    if identity(parameters) != baseline_id:
        raise RuntimeError('baseline parameters mutated')
    result = dict(schema='atlas.w10-ocean-evidence.v1', case_id=case['case_id'],
        status=baseline['dispersion_verdict'] if numeric_pass else 'NUMERICAL_REFINEMENT_UNRESOLVED',
        scope='Unfitted W06 synthetic constant-property model versus global oceanic heat-flow dispersion, 40-165 Ma.',
        calibration_performed=False, calibrated_confidence=False, whole_tectonics_acceptance=False,
        selected_sensitivity_model=None, case_sha256=case_sha,
        source=case['source'], model_input=case['model'], parameter_id=baseline_id,
        screen=case['screen'], baseline=baseline, numerical_refinement=refinement,
        all_numerical_checks_passed=bool(numeric_pass), observations=rows,
        sensitivity=dict(meaning='One parameter at a time at fixed factors; not a posterior or a model selection.',
            conductivity_diffusivity_note='Changing either conductivity or diffusivity changes k/kappa volumetric heat capacity consistently with the production parameter contract.',
            cases=sensitivity),
        age_bin_edges=dict(meaning='Sensitivity to bin location, not age uncertainty or a confidence interval.',
            cases=edge_results),
        production_source_sha256={name: _sha((ROOT/'src/atlas_tectonics'/name).read_bytes())
            for name in ('plate_cooling.py', 'parameters.py', 'resources.py', '_validation.py',
                         'thermal.py', 'stokes_execution.py')},
        tool_sha256=_sha(Path(__file__).read_bytes()),
        resources=dict(accounted_kernel_budget=budget.statistics(),
            scope='Kernel admission and peak reserved bytes only; not total memory or process RSS.'),
        elapsed_s=time.perf_counter()-started)
    json.dumps(result, allow_nan=False)
    return result


if __name__ == '__main__':
    print(json.dumps(run_challenge(), indent=2, allow_nan=False))
