"""Declared numerical experiments; no physical inputs or accuracy gates retuned.

The matched driver runs captured real pipeline Water inputs, not a replacement
column. Its wall times are observed diagnostic costs, not a statistical benchmark.
Only a completed pair permits a time-saving percentage. Failed runs have no state.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import platform
import sys
import time

from . import binding, provenance

TASK = Path(__file__).resolve().parents[2]
STRICT_ACCURACY = dict(theta_atol=1e-8, head_atol_m=1e-8,
    flux_integral_atol_m=1e-10, relative_tolerance=1e-6,
    nonlinear_mass_atol_m=1e-12, total_mass_atol_m=1e-10)
DATA = {
    'single_receipt': ('outputs/generator-upgrade-r5/diagnosis-upstream-02/RECEIPT.json',
        '2d1946f7c0976c29608adfdb6fc7321782173d43a4ac35d7a3bdd3c8ee53969d'),
    'single': ('outputs/generator-upgrade-r5/diagnosis-upstream-02/original.json',
        'b70f3ab84fa3f03a90d8575dac7e6bb1af2bf0dc42613fbabe510517e9c6eacf'),
    'multi': ('outputs/generator-upgrade-r6/early-multilayer-01/fixture-005.json',
        '90bcfe7677e62f2a50ca0ad32005d89c4e8e13b1f369f10cfbd7b2e4237c2a86'),
    'multi_receipt': ('outputs/generator-upgrade-r6/early-multilayer-01/RECEIPT.json',
        '8fed4c7193ece4d53a95901fb2ad51a0c6a6bbb176233e0bb23366b6f791181f'),
    'oracle_receipt': ('outputs/generator-upgrade-r6/multilayer-oracle-01/RECEIPT.json',
        '304e890f477f18bab03dd59b5fd6a8ec57c3312755d44a94ad59eaeac1dcd0b8'),
    'gross_oracle_receipt': ('outputs/generator-upgrade-r6/multilayer-gross-oracle-01/RECEIPT.json',
        '3cca621590c1592b2ccbb3ba4b62af60ee0d0114aa73bc06051835b4f2ea47a0'),
    'warm': ('outputs/generator-upgrade-r6/later-failure-cap30-01/fixture-025.json',
        '23c79171630a15563e1f65416aab5a10b5055bcc75ac500baa529504d856c211'),
    'warm_oracle_receipt': ('outputs/generator-upgrade-r6/warm-multilayer-oracle-01/RECEIPT.json',
        '625becada3b7b4ba3451e44acbf64fe09fba17163d1284aab8ab53a59cb8ad21'),
}


def _read(name):
    path, digest = DATA[name]
    return json.loads(provenance.checked(TASK/path, digest))


def test_data_bindings():
    """Verify frozen external evidence and return exact absolute path -> SHA pins."""
    pins = {}
    for name, (relative, expected) in DATA.items():
        provenance.checked(TASK/relative, expected)
        pins[str(TASK/relative)] = expected
    oracle = _read('oracle_receipt')
    if oracle['source_sha256'] != provenance.R5_SOURCE_SHA256:
        raise ValueError('oracle must describe exact retained R5 spatial science')
    first = _read('single_receipt')
    early = _read('multi_receipt')
    gross = _read('gross_oracle_receipt')
    warm = _read('warm_oracle_receipt')
    if early['source_sha256'] != provenance.R5_SOURCE_SHA256 or first['source_sha256'] != provenance.R4_SOURCE_SHA256:
        raise ValueError('captured predecessor source identity differs')
    if gross['source_identity'] != oracle['source_identity'] or gross['fixture'] != oracle['fixture']:
        raise ValueError('gross and signed oracle scientific inputs differ')
    if warm['source_identity'] != oracle['source_identity']:
        raise ValueError('warm oracle spatial science differs')
    records = [*oracle['files'].values(), oracle['diagnostic_source'], oracle['fixture'],
               early['diagnostic_source'],
               *({'path':p,'sha256':s} for p,s in first['diagnostic_sources'].items()),
               *gross['files'].values(), *({'path':p,'sha256':s} for p,s in gross['diagnostic_sources'].items()),
               *warm['files'].values(), warm['fixture'],
               *({'path':p,'sha256':s} for p,s in warm['diagnostic_sources'].items())]
    for row in records:
        path = provenance.plain_path(row['path'])
        if not path.is_relative_to(TASK):
            raise ValueError('test evidence outside this exact task refused')
        provenance.checked(path, row['sha256'])
        if str(path) in pins and pins[str(path)] != row['sha256']:
            raise ValueError('conflicting external test evidence')
        pins[str(path)] = row['sha256']
    return pins


def verification_recipes(bundle):
    """Nested retained R4 recipes, not source-wrapped Bundle.run arguments.

    Default is exactly the retained recipe (implicit BACKWARD_EULER default).
    Strict members use SDIRK2 and explicitly supported resolution/work controls.
    All physical coefficients and both sets of coupled accuracy gates are intact.
    """
    recipes = {'default': bundle.reference.recipe()}
    for cap in (120, 60, 30):
        recipe = deepcopy(recipes['default'])
        physical = recipe['physical_recipe']
        physical['coupling_controls'].update(initial_dt_seconds=cap,
            max_dt_seconds=cap, min_dt_seconds=1)
        physical['water_controls'].update(**STRICT_ACCURACY,
            min_dt_s=1e-14, max_steps=10000, integration_method='SDIRK2')
        recipes['strict-cap-'+str(cap)] = recipe
    return recipes


def load_fixture(name):
    """Exact captured physics and state, independent of successor class identities."""
    test_data_bindings()
    if name == 'fixture005':
        return deepcopy(_read('multi'))
    if name == 'fixture025':
        return deepcopy(_read('warm'))
    if name != 'standalone30':
        raise ValueError('expected standalone30, fixture005 or fixture025')
    report = _read('single')
    first = report['first_actual_water_arguments']
    if first['forcing']['duration_seconds'] != 30 or report['duration_seconds'] != '30':
        raise ValueError('first actual standalone 30-second input required')
    return dict(schema='diadem.r6.actual-water-call-fixture.r1',
        capture='Exact original first lower-column Water invocation; initial elapsed time zero',
        column=first['column'], state={'head_m': first['old'], 'elapsed_seconds': 0.0},
        controls=first['controls'], forcing=first['forcing'], boundary=first['boundary'],
        water_density_kg_m3=report['recipe']['physical_recipe']['water_density_kg_m3'],
        gravity_m_s2=report['recipe']['physical_recipe']['gravity_m_s2'])


def fixture_arguments(bundle, name, *, method=None, minimum_dt=1e-14):
    """Bind the same immutable captured layers/forcing to the selected solver types."""
    if type(minimum_dt) not in (int,float) or not 0 < minimum_dt <= 1e-8:
        raise ValueError('explicit positive bounded diagnostic minimum step required')
    record = load_fixture(name)
    sw = bundle.solver
    column = dict(record['column'])
    column['layers'] = tuple(sw.HydraulicLayer(**v) for v in column['layers'])
    column = sw.Column(**column)
    original = record['state']
    state = sw.initial_state(column, tuple(original['head_m']), elapsed_seconds=original['elapsed_seconds'])
    if 'column_sha256' in original and state.column_sha256 != original['column_sha256']:
        raise ValueError('captured hydraulic geometry changed')
    forcing = dict(record['forcing'])
    if forcing['uptake'] is not None:
        uptake = dict(forcing['uptake']); uptake['weights'] = tuple(uptake['weights'])
        forcing['uptake'] = sw.Uptake(**uptake)
    controls = dict(record['controls'])
    controls.update(**STRICT_ACCURACY, min_dt_s=minimum_dt, max_steps=10000)
    if 'integration_method' in sw.Controls.__dataclass_fields__:
        controls['integration_method'] = 'SDIRK2' if method is None else method
    elif method not in (None,'BACKWARD_EULER'):
        raise ValueError('preserved R5 supports only BACKWARD_EULER')
    args = dict(column=column, state=state, forcing=sw.Forcing(**forcing),
        boundary=sw.Boundary(**record['boundary']), controls=sw.Controls(**controls),
        water_density_kg_m3=record['water_density_kg_m3'], gravity_m_s2=record['gravity_m_s2'])
    return args


def _plain(value):
    if is_dataclass(value): return _plain(asdict(value))
    if isinstance(value, dict): return {k:_plain(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [_plain(v) for v in value]
    return value


def compare_captured_to_oracle(result, controls, *, fixture_name='fixture005'):
    """Global endpoint/flux check at strict input allowances, not just local errors.

    Frozen Radau solves independently integrate time but share the spatial
    constitutive/face/uptake equations. Agreement is not spatial or field validation.
    """
    if fixture_name not in ('fixture005','fixture025'):
        raise ValueError('independent oracle requires one of the exact captured fixtures')
    pins = test_data_bindings()
    receipt = _read('oracle_receipt' if fixture_name == 'fixture005' else 'warm_oracle_receipt')
    oracles = [json.loads(provenance.checked(v['path'], v['sha256']))
               for v in receipt['files'].values()]
    if len(oracles) != 2 or any(r['status'] != 'SUCCESS' for r in oracles):
        raise ValueError('paired completed independent oracle required')
    oracle = min(oracles, key=lambda v:v['rtol'])
    gross_receipt = _read('gross_oracle_receipt' if fixture_name == 'fixture005' else 'warm_oracle_receipt')
    gross_oracles = [json.loads(provenance.checked(v['path'],v['sha256'])) for v in gross_receipt['files'].values()]
    if len(gross_oracles) != 2 or any(r['status'] != 'SUCCESS' for r in gross_oracles):
        raise ValueError('paired completed gross-transfer oracle required')
    gross = min(gross_oracles,key=lambda v:v['rtol'])
    if result.get('status') != 'MODELLED' or result.get('state') is None or result.get('ledger') is None:
        return {'status':'NOT_COMPARABLE', 'reason':'no completed candidate state', 'test_data_bindings':pins}
    state = _plain(result['state']); ledger = result['ledger']
    fixture = _read('multi' if fixture_name == 'fixture005' else 'warm')
    if (result['column_sha256'] != fixture['state']['column_sha256']
            or state['column_sha256'] != fixture['state']['column_sha256']
            or state['elapsed_seconds'] != fixture['state']['elapsed_seconds']+fixture['forcing']['duration_seconds']
            or [r['layer_id'] for r in result['layers']] != [r['layer_id'] for r in fixture['column']['layers']]):
        raise ValueError('oracle requires exact captured geometry, layer support and elapsed interval')
    candidates = {
        'head_m': (state['head_m'], oracle['final_head_m'], controls.head_atol_m),
        'face_integrals_m': ([a-b for a,b in zip(ledger['face_downward_m'], ledger['face_upward_m'])],
                             oracle['face_integrals_m'], controls.flux_integral_atol_m),
        'uptake_integrals_m': ([r['et_m'] for r in result['layers']], oracle['uptake_integrals_m'], controls.flux_integral_atol_m)}
    for key in ('face_downward_m','face_upward_m'):
        candidates[key] = (ledger[key],gross[key],controls.flux_integral_atol_m)
    rows = {}
    for key,(actual,reference,atol) in candidates.items():
        if len(actual) != len(reference): raise ValueError('oracle physical support mismatch')
        differences = [abs(a-b) for a,b in zip(actual,reference)]
        ratios = [d/(atol+controls.relative_tolerance*max(abs(a),abs(b)))
                  for d,a,b in zip(differences,actual,reference)]
        rows[key] = {'maximum_absolute_difference':max(differences), 'maximum_error_ratio':max(ratios)}
    mass = max(abs(ledger['water_residual_m']), *(abs(r['water_residual_m']) for r in result['layers']))
    # Finite JSON serialisation is also a fail-closed arithmetic check.
    comparison = {'status':'PASS' if max(v['maximum_error_ratio'] for v in rows.values()) <= 1
        and mass <= controls.total_mass_atol_m else 'FAIL', 'components':rows,
        'maximum_cell_or_column_water_residual_m':mass,
        'paired_oracle_head_difference_m':receipt.get('between_oracle_max_head_difference_m',
            receipt.get('between_oracle_maximum_differences',{}).get('final_head_m')),
        'paired_gross_oracle_differences':gross_receipt['between_oracle_maximum_differences'],
        'test_data_bindings':pins,
        'limits':'Wholly unsaturated exact captured temporal oracle; no full trajectory, spatial convergence or production claim.'}
    json.dumps(comparison, allow_nan=False)
    return comparison


def compare_fixture005_to_oracle(result, controls):
    return compare_captured_to_oracle(result, controls, fixture_name='fixture005')


def run_fixture(bundle, name, *, method=None, minimum_dt=1e-14):
    args = fixture_arguments(bundle, name, method=method, minimum_dt=minimum_dt)
    before = _plain(args)
    started = time.perf_counter()
    result = bundle.solver.advance(**args)
    elapsed = time.perf_counter()-started
    if _plain(args) != before: raise AssertionError('antecedent fixture mutated')
    bundle.verify()
    if result['status'] != 'MODELLED' and (result.get('state') is not None or result.get('ledger') is not None):
        raise AssertionError('failed diagnostic must not expose accepted partial state')
    record = {'fixture':name, 'source_sha256':bundle.source_sha256, 'inputs':before,
        'result':_plain(result), 'elapsed_wall_seconds':elapsed, 'input_unchanged':True,
        'timing_scope':'One actual standalone solver call, excluding binding/input verification; observed diagnostic cost, not a statistical benchmark.'}
    if name in ('fixture005','fixture025'):
        record['oracle_comparison'] = compare_captured_to_oracle(result,args['controls'],fixture_name=name)
    json.dumps(record, allow_nan=False)
    return record


def matched_timing(old, new):
    """No percentage comparing a failure or physically different numerical case."""
    a, b = deepcopy(old['inputs']), deepcopy(new['inputs'])
    a['controls'].pop('integration_method',None); b['controls'].pop('integration_method',None)
    if a != b or old['fixture'] != new['fixture']: raise ValueError('matched identical physical inputs and accuracy controls required')
    if old['result']['status'] != 'MODELLED' or new['result']['status'] != 'MODELLED':
        return {'status':'NOT_COMPARABLE', 'reason':'both exact intervals must complete; failure runtime is not a speedup'}
    baseline, candidate = old['elapsed_wall_seconds'], new['elapsed_wall_seconds']
    if baseline <= 0 or candidate <= 0: raise ValueError('positive measured wall times required')
    return {'status':'COMPLETED_MATCHED_DIAGNOSTIC', 'seconds_saved':baseline-candidate,
        'percent_time_saved':100*(baseline-candidate)/baseline,
        'limits':'One observed paired call; method is the explicit experimental change, not a statistical speed claim.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', choices=('standalone30','fixture005','fixture025','all'), default='fixture005')
    parser.add_argument('--solver', choices=('r5','r6','both'), default='r6')
    parser.add_argument('--minimum-dt', type=float, default=1e-14,
                        help='explicit shared floor; no fallback or tolerance changes')
    parser.add_argument('--output', required=True, help='new directory immediately under outputs/generator-upgrade-r6')
    options = parser.parse_args(argv)
    destination = provenance.plain_path(Path(options.output).absolute())
    if destination.parent != TASK/'outputs/generator-upgrade-r6': raise ValueError('bounded R6 output directory required')
    destination.mkdir(parents=True,exist_ok=False)
    names = ('standalone30','fixture005') if options.fixture == 'all' else (options.fixture,)
    solvers = ('r5','r6') if options.solver == 'both' else (options.solver,)
    records, bundles = {}, {}
    for version in solvers:
        if version == 'r5':
            from work.generator_upgrade_r5 import binding as previous
            bundles[version] = previous.load()
        else: bundles[version] = binding.load()
    files, comparisons = {}, {}
    def write(name,value):
        raw = (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
        path = destination/name
        with path.open('xb') as stream: stream.write(raw)
        return {'path':str(path),'sha256':provenance.sha(raw),'size_bytes':len(raw)}
    for name in names:
        records[name] = {}
        for version,bundle in bundles.items():
            row = run_fixture(bundle,name,method='BACKWARD_EULER' if version=='r5' else 'SDIRK2',minimum_dt=options.minimum_dt)
            records[name][version] = row
            files[name+'-'+version] = write(name+'-'+version+'.json',row)
            print(json.dumps({'fixture':name,'solver':version,'status':row['result']['status'],
                              'seconds':row['elapsed_wall_seconds'],'oracle':row.get('oracle_comparison',{}).get('status')},allow_nan=False),flush=True)
        if options.solver == 'both': comparisons[name] = matched_timing(records[name]['r5'],records[name]['r6'])
    for bundle in bundles.values(): bundle.verify()
    receipt = {'schema':'diadem.r6.matched-captured-fixtures.r1','files':files,'matched_timings':comparisons,
        'source_identities':{k:v.identity for k,v in bundles.items()},'test_data_bindings':test_data_bindings(),
        'runtime':{'python':sys.version,'executable':sys.executable,'platform':platform.platform()},
        'scope':'Captured standalone Water only; no full coupled success claimed; no source/canon/production changes.'}
    print(json.dumps({'receipt':write('RECEIPT.json',receipt),'matched_timings':comparisons},allow_nan=False),flush=True)


if __name__ == '__main__': main()
