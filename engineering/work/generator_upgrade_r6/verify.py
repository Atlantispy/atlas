"""Focused exact-source corrected R6 checks, retained Water regression and strict restart proof.

Only the sealed R4 verifier's source-loader/audit/test-result utilities are reused.
This is not a rerun or recount of its whole historical verification programme.
"""
from __future__ import annotations

import argparse
from fractions import Fraction as F
import importlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import types
import unittest

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
OUTPUT_ROOT = TASK / 'outputs/generator-upgrade-r6'
SUITES = ('test_binding','test_hydraulic_jacobian','test_soil_integration','test_experiments')
EXPECTED_NEW_COUNT = 102
NEW_INVENTORY_SHA256 = 'cbb5f141aa4c1bba2961a95387acdb5476a1c138b78883b2baa06fd1dbff2ef2'
EXPECTED_RETAINED_COUNT = 29
RETAINED_INVENTORY_SHA256 = '02267a810378ea40d47872de8fb982b8c48c20f0b83afb80a7269134efe0bc9a'
ENTRY_SOURCE_SHA256 = None
R4_SEAL_SHA256 = 'f7382693a5284ebf111dc8a0622e5811440ccc7e2b546047943462b849926996'
WORKER_TIMEOUT_SECONDS = 600
RETAINED_PREFIX = 'retained-regression:work.generator_upgrade_r3.test_soil_water'
REFINEMENT_FLOORS = {'sediment_export_kg':1e-6,'terrain_change_m':1e-10,'water_export_m3':1e-8,
    'swe_m':1e-18,'precipitation_m3':1e-10,'temperature_c':1e-12,'head_integral_m2':1e-9}
REFINEMENT_BAND = (1.4,3.0)  # Preserved R4 predeclared diagnostic band, not retuned.


def sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def inventory_digest(ids):
    return sha(json.dumps(ids, separators=(',', ':'), ensure_ascii=True).encode())


def utility():
    """Fresh exact sealed bytes; no canonical predecessor module is modified."""
    seal = TASK / 'outputs/generator-upgrade-r4/connected-reference-01/VERIFICATION.json'
    raw = seal.read_bytes()
    if sha(raw) != R4_SEAL_SHA256:
        raise ValueError('retained verifier seal changed')
    record = json.loads(raw)
    path = TASK / 'work/generator_upgrade_r4/verify.py'
    raw = path.read_bytes()
    digest = record['source_snapshot'][str(path)]
    if sha(raw) != digest:
        raise ValueError('retained verifier utility source changed')
    module = types.ModuleType('_r6_sealed_verification_utilities')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module, path, digest


def install():
    if ENTRY_SOURCE_SHA256 is None or any(k.startswith('work.') for k in sys.modules):
        raise ValueError('fresh source-compiled standalone verifier required')
    helper, path, digest = utility()
    capture = helper.ExecutionCapture()
    # These are the exact two bootstrapped executions preceding the audit hook.
    for key, value in ((str(HERE/'verify.py'), ENTRY_SOURCE_SHA256), (str(path), digest)):
        capture.compiled[key] = value
        capture.executed[key] = value
        helper.READS[key] = value
    sys.addaudithook(capture.observe)
    sys.meta_path.insert(0, helper.SourceFinder())
    return helper, capture


def source_map(identity, helper):
    result = helper.source_map(identity['retained_source_identity']['retained_source_identity'])
    for mapping in (identity['retained_source_identity']['r5_sources'],identity['r6_sources']):
        for path, digest in mapping.items():
            key = helper.canonical(path)
            if key in result and result[key] != digest:
                raise ValueError('conflicting exact source binding')
            result[key] = digest
    return result


def required_sources():
    return (tuple(HERE/(name+'.py') for name in (*SUITES, 'binding', 'verify', 'provenance', 'soil_water', 'hydraulic_jacobian', 'experiments'))
        + tuple(TASK/('work/generator_upgrade_r4/'+name+'.py') for name in ('verify','pipeline','reference','climate','hydromet'))
        + tuple(TASK/('work/generator_upgrade_r3/'+name+'.py') for name in ('pipeline','test_soil_water','test_coupled_refinement','soil_inputs','terrain_transport')))


def validate_executed(executed, identity, helper, *, required=(), check_current=False):
    if type(executed) is not dict or not executed:
        raise ValueError('actual executed source evidence required')
    expected = source_map(identity, helper)
    seen = set()
    for path, digest in executed.items():
        key = helper.canonical(path)
        if key in seen or expected.get(key) != digest:
            raise ValueError('executed bytes differ from exact source capture')
        seen.add(key)
        if check_current and sha(Path(key).read_bytes()) != digest:
            raise ValueError('executed source changed after execution')
    if any(helper.canonical(path) not in seen for path in required):
        raise ValueError('required source was not actually executed')


def stable(bundle, helper, capture):
    bundle.verify()
    if bundle.identity['r6_sources'].get(str(HERE/'verify.py')) != ENTRY_SOURCE_SHA256:
        raise ValueError('entrypoint capture differs from bound source')
    validate_executed(capture.executed, bundle.identity, helper, check_current=True)
    if capture.derived_executed:
        raise ValueError('this bounded successor does not authorise derived source execution')
    for path, digest in helper.READS.items():
        if capture.executed.get(path) != digest:
            raise ValueError('fresh loader and actual execution records differ')


def discover(bundle, helper):
    if {p.name for p in HERE.glob('test_*.py')} != {name+'.py' for name in SUITES}:
        raise ValueError('test file inventory differs; no undisclosed suite')
    loader = unittest.TestLoader()
    new = loader.loadTestsFromNames(['work.generator_upgrade_r6.'+name for name in SUITES])
    retained_module = bundle.retained_soil_tests()
    retained = loader.loadTestsFromModule(retained_module)
    if loader.errors:
        raise ValueError('test import/discovery failed: '+repr(loader.errors))
    new_ids = [test.id() for test in helper.flatten(new)]
    old_prefix = retained_module.__name__
    def normalise(value):
        if not value.startswith(old_prefix+'.'):
            raise ValueError('retained test identity does not belong to exact private module')
        return RETAINED_PREFIX+value[len(old_prefix):]
    retained_ids = [normalise(test.id()) for test in helper.flatten(retained)]
    for ids in (new_ids, retained_ids):
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('nonempty unique test identities required')
    return new, new_ids, retained, retained_ids, normalise


def require_inventory(ids, *, retained=False):
    count, digest = ((EXPECTED_RETAINED_COUNT, RETAINED_INVENTORY_SHA256) if retained
                     else (EXPECTED_NEW_COUNT, NEW_INVENTORY_SHA256))
    if type(count) is not int or count <= 0 or type(digest) is not str:
        raise ValueError('reviewed inventory is PENDING; no final seal authorised')
    if (type(ids) is not list or any(type(v) is not str for v in ids) or len(ids) != count
            or len(set(ids)) != count or inventory_digest(ids) != digest):
        raise ValueError('exact reviewed test inventory differs')
    return digest


def validate_tests(record, *, retained=False):
    count = EXPECTED_RETAINED_COUNT if retained else EXPECTED_NEW_COUNT
    keys = ('tests','failures','errors','skips','expected_failures','unexpected_successes')
    if any(type(record.get(key)) is not int for key in keys):
        raise ValueError('integer test counts required; bool is not a count')
    digest = require_inventory(record['test_ids'], retained=retained)
    if record.get('status') != 'PASS' or record['tests'] != count or any(record[k] for k in keys[1:]):
        raise ValueError('complete unskipped actual suite did not pass')
    if (record['inventory_sha256'] != digest or
            not record['test_ids'] == record['started'] == record['stopped'] == record['passed']):
        raise ValueError('discovery/start/stop/pass identities disagree')


def run_suite(suite, ids, helper, normalise=lambda value: value):
    stream = io.StringIO()
    start = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helper.Result).run(suite)
    duration = time.perf_counter()-start
    return {'status': 'PASS' if result.wasSuccessful() else 'FAIL', 'tests': result.testsRun,
        'test_ids': ids, 'inventory_sha256': inventory_digest(ids),
        'started': list(map(normalise,result.started)), 'stopped': list(map(normalise,result.stopped)),
        'passed': list(map(normalise,result.passed)), 'failures':len(result.failures), 'errors':len(result.errors),
        'skips':len(result.skipped), 'expected_failures':len(result.expectedFailures),
        'unexpected_successes':len(result.unexpectedSuccesses), 'test_duration_seconds':duration,
        'test_log': stream.getvalue()}


def semantic(value):
    """Remove only the declared observational timer; retain all physics/gates."""
    if type(value) is dict:
        return {key:semantic(child) for key, child in value.items() if key != 'elapsed_wall_seconds'}
    if type(value) is list:
        return [semantic(child) for child in value]
    return value


def test_data_bindings():
    module = importlib.import_module('work.generator_upgrade_r6.experiments')
    return module.test_data_bindings()


def collect_oracle(bundle):
    module = importlib.import_module('work.generator_upgrade_r6.test_experiments')
    experiments = importlib.import_module('work.generator_upgrade_r6.experiments')
    cls = module.ExperimentTests
    cases = {}
    for name,args,result in (('fixture005',cls.args,cls.result),('fixture025',cls.warm_args,cls.warm_result)):
        comparison = experiments.compare_captured_to_oracle(result,args['controls'],fixture_name=name)
        if comparison['status']!='PASS': raise ValueError('actual cached strict candidate failed independent oracle')
        cases[name] = {'inputs':experiments._plain(args),'actual_result':experiments._plain(result),'comparison':comparison}
    return {'source_sha256':bundle.source_sha256,'cases':cases,
        'meaning':'actual successful-suite product, not rerun; independent time integrator with shared spatial laws',
        'external_test_data':test_data_bindings()}


def validate_oracle(record,bundle):
    experiments = importlib.import_module('work.generator_upgrade_r6.experiments')
    if (record.get('source_sha256')!=bundle.source_sha256 or set(record.get('cases',{}))!={'fixture005','fixture025'}
            or record.get('external_test_data')!=test_data_bindings()):
        raise ValueError('both exact source-bound independent-oracle cases required')
    for name,case in record['cases'].items():
        controls = bundle.solver.Controls(**case['inputs']['controls'])
        comparison = experiments.compare_captured_to_oracle(case['actual_result'],controls,fixture_name=name)
        if comparison['status']!='PASS' or comparison!=case['comparison']:
            raise ValueError('actual saved independent-oracle candidate/comparison differs')


def verification_recipes(bundle):
    module = importlib.import_module('work.generator_upgrade_r6.experiments')
    recipes = module.verification_recipes(bundle)
    names = {'default','strict-cap-120','strict-cap-60','strict-cap-30'}
    if type(recipes) is not dict or set(recipes) != names:
        raise ValueError('exact declared default and three strict-cap recipes required')
    for name, recipe in recipes.items():
        bundle.pipeline.parse(recipe,bundle.source_sha256)
        if name != 'default':
            cap = int(name.rsplit('-',1)[1])
            if recipe['physical_recipe']['coupling_controls']['max_dt_seconds'] != cap:
                raise ValueError('strict recipe outer cap differs from its declared identity')
            strict = {'theta_atol':1e-8,'head_atol_m':1e-8,'flux_integral_atol_m':1e-10,
                'relative_tolerance':1e-6,'nonlinear_mass_atol_m':1e-12,'total_mass_atol_m':1e-10,
                'min_dt_s':1e-14,'max_steps':10000,'integration_method':'SDIRK2'}
            if any(recipe['physical_recipe']['water_controls'][key] != value for key,value in strict.items()):
                raise ValueError('strict correction verification cannot relax the declared accuracy or work controls')
    return recipes


def selected_reference(bundle,recipe):
    p = bundle.pipeline
    model = p.parse(recipe,bundle.source_sha256)
    scenario = model.scenarios[0]  # One explicitly named coequal member, not preferred.
    state = p.initial(model,scenario)
    for event in recipe['events']:
        state = p.advance_event(model,state,event,scenario)
    result = {'schema':'diadem.strict-refinement-member.r6','status':'BOUNDED_SELECTED_MEMBER_REFERENCE',
        'source_sha256':bundle.source_sha256,'recipe_sha256':sha(bundle.storage.encoded(recipe)),
        'scenario_id':scenario.scenario_id,'scenario_index':0,'scope':'ONE_EXPLICIT_COEQUAL_MEMBER_NOT_ALL_THREE',
        'state':p.serialise({scenario.scenario_id:state},len(recipe['events'])),
        'soil_products':bundle.r3.soil_products(model.physical,state['physical']),
        'final_terrain_climate':bundle.r3.plain(p.atmosphere(model,state['physical'],recipe['events'][-1])),
        'production_installed':False,'canon_changed':False}
    bundle.verify()
    return result


def collect_cases(bundle,root):
    recipes = verification_recipes(bundle)
    result = {}
    for name in ('default','strict-cap-120'):
        result[name] = {'scope':'ALL_THREE_COEQUAL_MEMBERS_FULL_STOP_RESTART',
            'artifacts':artifact_reference(bundle,root/name,recipes[name])}
    for name in ('strict-cap-60','strict-cap-30'):
        path = root/(name+'.json')
        started = time.perf_counter()
        value = {'recipe':recipes[name],'result':selected_reference(bundle,recipes[name])}
        elapsed = time.perf_counter()-started
        bundle.storage.write_json(path,value)
        result[name] = {'scope':'ONE_EXPLICIT_COEQUAL_MEMBER_NOT_ALL_THREE',
            'path':str(path),'sha256':sha(path.read_bytes()),'elapsed_wall_seconds':elapsed}
    return result


def validate_cases(cases,bundle):
    if type(cases) is not dict or set(cases) != {'default','strict-cap-120','strict-cap-60','strict-cap-30'}:
        raise ValueError('all declared strict-cap and default cases required')
    actual = {}
    for name in ('default','strict-cap-120'):
        if cases[name].get('scope') != 'ALL_THREE_COEQUAL_MEMBERS_FULL_STOP_RESTART':
            raise ValueError('three-member full/restart scope missing')
        actual[name] = validate_artifacts(cases[name]['artifacts'],bundle)
    scenario = bundle.pipeline.hm.snow_scenarios()[0].scenario_id
    for name in ('strict-cap-60','strict-cap-30'):
        proof = cases[name]
        value = bundle.storage.read_json(proof['path'])
        result = value['result']
        if (sha(Path(proof['path']).read_bytes()) != proof['sha256']
                or proof.get('scope') != 'ONE_EXPLICIT_COEQUAL_MEMBER_NOT_ALL_THREE'
                or result.get('schema') != 'diadem.strict-refinement-member.r6'
                or result.get('source_sha256') != bundle.source_sha256
                or result.get('recipe_sha256') != sha(bundle.storage.encoded(value['recipe']))
                or result.get('scenario_id') != scenario or result.get('scenario_index') != 0
                or set(result['state']['members']) != {scenario}
                or result['state']['completed_events'] != len(value['recipe']['events'])
                or result.get('production_installed') is not False or result.get('canon_changed') is not False):
            raise ValueError('actual completed selected-member strict reference required')
        actual[name] = value
    return actual


def validate_joint_member(bundle,recipe,member,final):
    physical = member['physical']; history = physical['history']; joint = member['joint_history']
    total = sum((F(event['duration_seconds']) for event in recipe['events']),F())
    if not history or len(history)!=len(joint) or F(physical['elapsed'])!=total or physical['completed_events']!=len(recipe['events']):
        raise ValueError('complete matched physical/snow history and time required')
    clock = F(); maximum_physical = 0.; maximum_joint = 0.
    event_index = 0; event_end = F(recipe['events'][0]['duration_seconds']); durations = set()
    snow = {key:F(value) for key,value in recipe['initial_swe_m'].items()}
    for row,air in zip(history,joint):
        duration = F(row['duration_seconds'])
        if duration<=0 or F(row['start_seconds'])!=clock or F(air['start_seconds'])!=clock or F(air['duration_seconds'])!=duration:
            raise ValueError('physical/snow interval continuity failed')
        if clock==event_end:
            event_index += 1
            if event_index>=len(recipe['events']): raise ValueError('history exceeds declared events')
            event_end += F(recipe['events'][event_index]['duration_seconds'])
        event = recipe['events'][event_index]
        if (clock+duration>event_end or air['interval_id']!=event['interval_id'] or air['month']!=event['month']
                or duration>F(recipe['physical_recipe']['coupling_controls']['max_dt_seconds'])/2):
            raise ValueError('actual accepted interval does not match declared event/cap support')
        durations.add(duration)
        clock += duration
        residual = (F(row['initial_water_m3'])+F(row['liquid_input_m3'])+F(row['bottom_in_m3'])
            -F(row['actual_et_m3'])-F(row['bottom_out_m3'])-F(row['runoff_export_m3'])
            -F(row['sediment_porewater_export_m3'])-F(row['final_water_m3']))
        if residual!=F(row['numerical_water_residual_m3']) or abs(float(residual))>recipe['physical_recipe']['coupling_controls']['budget_atol_m3']:
            raise ValueError('actual physical water ledger failed')
        maximum_physical = max(maximum_physical,abs(float(residual)))
        residual = (F(air['initial_total_water_m3'])+F(air['precipitation_m3'])+F(row['bottom_in_m3'])
            -F(row['actual_et_m3'])-F(row['bottom_out_m3'])-F(row['runoff_export_m3'])
            -F(row['sediment_porewater_export_m3'])-F(air['final_total_water_m3'])-F(air['atmosphere_surface_transfer_roundoff_m3']))
        if residual!=F(air['joint_residual_m3']) or abs(float(residual))>recipe['coupling_controls']['joint_budget_atol_m3']:
            raise ValueError('actual atmosphere/snow/physical water ledger failed')
        maximum_joint = max(maximum_joint,abs(float(residual)))
        terrain = row['terrain']
        water = {key:F(value) for key,value in terrain['local_runoff_m3'].items()}; exports = {}
        for route in terrain['water_routing']:
            amount = F(route['through_volume_m3'])
            if amount!=water[route['cell_id']]: raise ValueError('actual routed water accumulation failed')
            if route['receiver_id'] is None: exports[route['connector_id']] = amount
            else: water[route['receiver_id']] += amount
        if exports!={key:F(value) for key,value in terrain['water_exports_m3'].items()} or F(terrain['water_residual_m3'])!=0:
            raise ValueError('actual external routed water ledger failed')
        for transfer in terrain['sediment_transfers']:
            if F(transfer['incoming_kg'])!=F(transfer['deposited_kg'])+F(transfer['outgoing_kg']):
                raise ValueError('actual sediment transfer mass failed')
        for balance in terrain['material_balances']:
            if (F(balance['initial_mass_kg'])-F(balance['exported_mass_kg'])-F(balance['final_mass_kg'])!=0
                    or F(balance['mass_residual_kg'])!=0 or F(balance['solid_residual_m3'])!=0):
                raise ValueError('actual retained material balance failed')
        receipt = air['atmospheric_moisture_ledger']
        if F(receipt['water_mass_residual_kg_s'])!=0: raise ValueError('actual atmosphere moisture ledger failed')
        for cell in receipt['cells']:
            if cell['elevation_m']!=float(F(terrain['initial_surfaces_m'][cell['cell_id']])):
                raise ValueError('generated climate did not use accepted antecedent terrain')
        for key,product in air['cells'].items():
            ledger = {name:F(value) for name,value in product['snow_ledger'].items()}
            if (ledger['initial_swe_m']!=snow[key] or ledger['snow_residual_m']!=0 or ledger['total_water_residual_m']!=0
                    or ledger['initial_swe_m']+ledger['snowfall_m']-ledger['melt_m']!=ledger['final_swe_m']
                    or ledger['rain_m']+ledger['snowfall_m']!=ledger['precipitation_m']
                    or ledger['rain_m']+ledger['melt_m']!=ledger['liquid_to_soil_m']
                    or not 0<=ledger['melt_m']<=ledger['potential_melt_m']):
                raise ValueError('actual persistent snow continuity/water ledger failed')
            snow[key] = ledger['final_swe_m']
    if clock!=total: raise ValueError('accepted physical intervals do not span the declared event time')
    for key,record in member['snow'].items():
        if F(record['swe_m'])!=snow[key] or F(record['elapsed_seconds'])!=total:
            raise ValueError('final snow state differs from complete history')
    for cell in final['receipt']['cells']:
        column = bundle.r3.landscape.Column.from_dict(physical['profiles'][cell['cell_id']]['column'])
        if cell['elevation_m']!=float(column.surface_m): raise ValueError('final climate terrain identity is stale')
    for water in physical['water'].values():
        if water['status']!='MODELLED' or water['numerics']['maximum_error_ratio']>1:
            raise ValueError('actual final soil-water accuracy gate failed')
        if abs(water['ledger']['water_residual_m'])>recipe['physical_recipe']['water_controls']['total_mass_atol_m']:
            raise ValueError('actual final soil-water mass gate failed')
        for layer in water['layers']:
            expected = recipe['physical_recipe']['water_density_kg_m3']*recipe['physical_recipe']['gravity_m_s2']*layer['head_m']
            if layer['signed_pore_pressure_pa']!=expected: raise ValueError('signed pressure is not the actual solved head')
    return {'accepted_intervals':len(history),'duration_seconds':str(total),
        'actual_accepted_durations_seconds':[str(value) for value in sorted(durations)],
        'maximum_physical_residual_m3':maximum_physical,'maximum_joint_residual_m3':maximum_joint,
        'material_and_routing_conservation':'EXACT_REPRESENTED_LEDGER_PASS','snow_continuity':'PASS',
        'antecedent_and_final_terrain_climate_binding':'PASS','actual_signed_pressure':'PASS'}


def refinement_report(cases,bundle):
    # Execute only the exact retained comparison helper, not its test suite.
    from work.generator_upgrade_r3.test_coupled_refinement import physical_head_distance
    actual = validate_cases(cases,bundle)
    scenario = bundle.pipeline.hm.snow_scenarios()[0].scenario_id
    values = []; physical = []; ledgers = []; recipes = []
    for cap in (120,60,30):
        name = 'strict-cap-'+str(cap)
        if cap==120:
            recipe = bundle.storage.read_json(Path(cases[name]['artifacts']['path'])/'recipe.json')['retained_recipe']
            result = actual[name]
            member = result['state']['members'][scenario]
            final = result['retained_result']['members'][scenario]['final_terrain_climate_diagnostic']
        else:
            recipe = actual[name]['recipe']; result = actual[name]['result']
            member = result['state']['members'][scenario]; final = result['final_terrain_climate']
        recipes.append(recipe)
        ledgers.append(validate_joint_member(bundle,recipe,member,final))
        state = member['physical']; history = state['history']; physical.append({'state':state})
        columns = {key:bundle.r3.landscape.Column.from_dict(value['column']) for key,value in state['profiles'].items()}
        initial = {key:bundle.r3.landscape.Column.from_dict(value['profile']['column']) for key,value in recipe['physical_recipe']['cells'].items()}
        values.append({'sediment_export_kg':float(sum((F(row['exported_mass_kg']) for step in history for row in step['terrain']['material_balances']),F())),
            'terrain_change_m':float(sum((abs(column.surface_m-initial[key].surface_m) for key,column in columns.items()),F())),
            'water_export_m3':float(sum((F(step[key]) for step in history for key in ('bottom_out_m3','runoff_export_m3','sediment_porewater_export_m3')),F())),
            'swe_m':float(sum((F(row['swe_m']) for row in member['snow'].values()),F())),
            'precipitation_m3':float(sum((F(row['precipitation_m3']) for row in member['joint_history']),F())),
            'temperature_c':sum(row['temperature_c'] for row in final['cells'].values())})
    normalised = bundle.storage.decoded(bundle.storage.encoded(recipes))
    for recipe in normalised:
        for key in ('initial_dt_seconds','max_dt_seconds'): del recipe['physical_recipe']['coupling_controls'][key]
    if normalised[0]!=normalised[1] or normalised[1]!=normalised[2]:
        raise ValueError('strict refinement changed more than outer time-step caps')
    differences = {key:[abs(values[i][key]-values[i+1][key]) for i in (0,1)] for key in values[0]}
    heads = [physical_head_distance(physical[i],physical[i+1]) for i in (0,1)]
    differences['head_integral_m2'] = [value[0] for value in heads]
    classified = {}
    for key,(a,b) in differences.items():
        classified[key] = ('UNRESOLVED_AT_PREDECLARED_FLOOR' if min(a,b)<=REFINEMENT_FLOORS[key]
            else 'DECREASING_WITHIN_FIRST_ORDER_BAND' if REFINEMENT_BAND[0]<=a/b<=REFINEMENT_BAND[1]
            else 'DECREASING_OUTSIDE_FIRST_ORDER_BAND' if b<a else 'NOT_DECREASING')
    return {'caps_seconds':[120,60,30],'scenario_id':scenario,'measures':values,'differences':differences,
        'ratios':{key:(a/b if b else None) for key,(a,b) in differences.items()},
        'observed_orders':{key:(math.log2(a/b) if a>0 and b>0 else None) for key,(a,b) in differences.items()},
        'head_nonoverlap_m':[value[1] for value in heads],'predeclared_floors':REFINEMENT_FLOORS,
        'predeclared_ratio_band':list(REFINEMENT_BAND),'classifications':classified,'ledger_checks':ledgers,
        'all_fields_first_order_claimed':False,
        'pressure_support':'actual retained R3 L1 piecewise-constant pressure-head comparison on common absolute elevations; uncovered thickness separate',
        'interpretation':'strict-inner runs on one explicitly selected coequal member; unchanged prior floors/band; unresolved or faster convergence is not relabelled first order'}


def artifact_reference(bundle, root, retained_recipe):
    root.mkdir(exist_ok=False)
    s = bundle.storage
    recipe = bundle.wrap_recipe(retained_recipe, evidence='SYNTHETIC declared R4 reference with isolated corrected R6 solver; no implicit control relaxation')
    s.write_json(root/'recipe.json',recipe)
    recipe = s.read_json(root/'recipe.json')
    timings = {}; started = time.perf_counter()
    full = bundle.run(recipe)
    timings['full'] = {'elapsed_wall_seconds':time.perf_counter()-started}
    started = time.perf_counter()
    stopped = bundle.run(recipe,stop_after=1)
    timings['stop'] = {'elapsed_wall_seconds':time.perf_counter()-started}
    stop_cp = bundle.checkpoint(stopped)
    s.write_json(root/'stop-result.json',stopped)
    s.write_json(root/'stop-checkpoint.json',stop_cp)
    restored = s.read_json(root/'stop-checkpoint.json')
    started = time.perf_counter()
    restarted = bundle.run(recipe,resume=restored)
    timings['restart'] = {'elapsed_wall_seconds':time.perf_counter()-started}
    for stage,result in (('full',full),('restart',restarted)):
        s.write_json(root/(stage+'-result.json'),result)
        s.write_json(root/(stage+'-checkpoint.json'),bundle.checkpoint(result))
    names = ('recipe.json','stop-result.json','stop-checkpoint.json','full-result.json',
             'full-checkpoint.json','restart-result.json','restart-checkpoint.json')
    proof = {'path':str(root), 'files':{name:sha((root/name).read_bytes()) for name in names},
             'reference_sha256':sha(s.encoded(full)), 'entrypoint':'binding.Bundle.run and checkpoint; no new CLI claimed',
             'timings':timings,'timing_scope':'individual completed run calls including their source/replay checks, not a generator-wide benchmark'}
    proof['all_member_ledger_checks'] = {name:validate_joint_member(bundle,retained_recipe,member,
        full['retained_result']['members'][name]['final_terrain_climate_diagnostic'])
        for name,member in full['state']['members'].items()}
    validate_artifacts(proof,bundle)
    return proof


def validate_artifacts(proof,bundle):
    root = bundle.storage.plain_path(proof['path'])
    names = {'recipe.json','stop-result.json','stop-checkpoint.json','full-result.json',
             'full-checkpoint.json','restart-result.json','restart-checkpoint.json'}
    if set(proof['files']) != names or {p.name for p in root.iterdir()} != names:
        raise ValueError('exact public wrapper artifact inventory differs')
    values = {}
    for name,digest in proof['files'].items():
        values[name] = bundle.storage.read_json(root/name)
        if sha((root/name).read_bytes()) != digest:
            raise ValueError('wrapper artifact changed after readback')
    full, restarted = values['full-result.json'], values['restart-result.json']
    if full != restarted or values['full-checkpoint.json'] != values['restart-checkpoint.json']:
        raise ValueError('actual full/restart state or checkpoint parity failed')
    if (full['source_sha256'] != bundle.source_sha256 or full['schema'] != 'diadem.strict-soil-water-result.r6'
            or full['production_installed'] is not False or full['canon_changed'] is not False
            or proof['reference_sha256'] != sha(bundle.storage.encoded(full))
            or full['state']['completed_events'] != len(values['recipe.json']['retained_recipe']['events'])
            or values['stop-result.json']['state']['completed_events'] != 1):
        raise ValueError('actual completed source-bound R6 reference required')
    scenarios = {row.scenario_id for row in bundle.pipeline.hm.snow_scenarios()}
    inner = full['retained_result']
    if (set(full['state']['members']) != scenarios or set(inner['members']) != scenarios
            or inner['state'] != full['state'] or inner['source_sha256'] != bundle.source_sha256
            or inner['snow_family'] != 'THREE_COEQUAL_SENSITIVITIES_NO_PREFERRED_MEMBER'):
        raise ValueError('complete actual three-coequal-member result required')
    checks = {scenario:validate_joint_member(bundle,values['recipe.json']['retained_recipe'],full['state']['members'][scenario],
            inner['members'][scenario]['final_terrain_climate_diagnostic']) for scenario in scenarios}
    if proof.get('all_member_ledger_checks')!=checks: raise ValueError('actual all-member physical checks differ')
    if set(proof.get('timings',{}))!={'full','stop','restart'}:
        raise ValueError('individual completed run timings required')
    for timing in proof['timings'].values():
        value = timing.get('elapsed_wall_seconds')
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:
            raise ValueError('finite completed run timing required')
    for stage in ('stop','full','restart'):
        result, cp = values[stage+'-result.json'], values[stage+'-checkpoint.json']
        if (cp != bundle.checkpoint(result) or cp['recipe_sha256'] != sha(bundle.storage.encoded(values['recipe.json']))):
            raise ValueError('saved recipe/result/checkpoint identity differs')
    return full


def worker(path,parent_path,mode):
    start = time.perf_counter()
    helper,capture = install()
    from work.generator_upgrade_r6 import binding
    bundle = binding.load()
    parent = bundle.storage.read_json(parent_path)
    if (sys.flags.optimize != mode or parent['source_identity'] != bundle.identity
            or parent['source_sha256'] != bundle.source_sha256):
        raise ValueError('worker actual mode/source differs from parent')
    if test_data_bindings()!=parent['external_test_data']:
        raise ValueError('worker external diagnostic test data differs from parent')
    new,ids,old,old_ids,normalise = discover(bundle,helper)
    require_inventory(ids); require_inventory(old_ids,retained=True)
    new_record = run_suite(new,ids,helper)
    old_record = run_suite(old,old_ids,helper,normalise)
    record = {'status':'FAIL','optimisation_flag':sys.flags.optimize,'source_identity':bundle.identity,
        'source_sha256':bundle.source_sha256,'new_tests':new_record,'retained_regression':old_record,
        'retained_regression_binding':'exact preserved R3 test bytes, explicit private R6 solver dependency; separately counted rerun'}
    try:
        validate_tests(new_record); validate_tests(old_record,retained=True)
    except ValueError:
        bundle.storage.write_json(path,record)
        capture.active = False
        return 1
    oracle_path = path.parent/(path.stem+'-oracle.json')
    oracle = collect_oracle(bundle)
    bundle.storage.write_json(oracle_path,oracle)
    record['oracle'] = {'path':str(oracle_path),'sha256':sha(oracle_path.read_bytes())}
    record['external_test_data'] = test_data_bindings()
    cases_root = path.parent/(path.stem+'-cases')
    cases_root.mkdir(exist_ok=False)
    record['cases'] = collect_cases(bundle,cases_root)
    validate_cases(record['cases'],bundle)
    record['refinement_report'] = refinement_report(record['cases'],bundle)
    record['refinement_sha256'] = sha(encoded(record['refinement_report']))
    stable(bundle,helper,capture)
    if record['external_test_data']!=parent['external_test_data']:
        raise ValueError('external diagnostic test data changed during worker')
    validate_executed(capture.executed,bundle.identity,helper,required=required_sources())
    record.update(status='PASS',executed_source_hashes=dict(capture.executed),
        private_dependency_executions=dict(bundle.graph.executed),
        test_duration_seconds=new_record['test_duration_seconds']+old_record['test_duration_seconds'],
        worker_duration_seconds=time.perf_counter()-start,
        duration_meaning='actual suite timing separate from source checks, new solver tests, all declared strict cases, default/strict full-stop-restart and readback; no speedup benchmark')
    bundle.storage.write_json(path,record)
    capture.active = False
    print(json.dumps({'status':record['status'],'new_tests':len(ids),'retained_regression':len(old_ids),'actual_mode':mode}),flush=True)
    return 0


def validate_workers(records,bundle,helper):
    if type(records) is not list or len(records) != 2:
        raise ValueError('exactly two worker receipts required')
    actual = []; oracles = []
    for record,mode in zip(records,(0,2)):
        if type(record.get('optimisation_flag')) is not int or record['optimisation_flag'] != mode:
            raise ValueError('actual normal/-OO modes required; inherited flags are not evidence')
        validate_tests(record['new_tests']); validate_tests(record['retained_regression'],retained=True)
        if record.get('status') != 'PASS' or record['source_identity'] != bundle.identity or record['source_sha256'] != bundle.source_sha256:
            raise ValueError('worker source/status differs from parent')
        validate_executed(record['executed_source_hashes'],bundle.identity,helper,required=required_sources(),check_current=True)
        for key in ('test_duration_seconds','worker_duration_seconds'):
            value = record.get(key)
            if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
                raise ValueError('finite nonnegative timing required')
        if record['worker_duration_seconds'] < record['test_duration_seconds']:
            raise ValueError('complete worker shorter than tests')
        actual.append(validate_cases(record['cases'],bundle))
        if record['external_test_data']!=test_data_bindings():
            raise ValueError('worker external diagnostic data changed')
        oracle = bundle.storage.read_json(record['oracle']['path'])
        if (sha(Path(record['oracle']['path']).read_bytes())!=record['oracle']['sha256']
                or oracle['source_sha256']!=bundle.source_sha256
                or oracle['external_test_data']!=record['external_test_data']):
            raise ValueError('saved actual independent-oracle evidence differs')
        validate_oracle(oracle,bundle)
        oracles.append(oracle)
        refined = refinement_report(record['cases'],bundle)
        if record.get('refinement_report')!=refined or record.get('refinement_sha256')!=sha(encoded(refined)):
            raise ValueError('actual strict refinement/ledger evidence differs')
    for key in ('executed_source_hashes','private_dependency_executions'):
        if records[0][key] != records[1][key]:
            raise ValueError('actual mode execution-source disagreement')
    if actual[0] != actual[1]:
        raise ValueError('normal/-OO actual case or restart disagreement')
    if records[0]['refinement_report']!=records[1]['refinement_report']:
        raise ValueError('normal/-OO strict refinement disagreement')
    if oracles[0]!=oracles[1]: raise ValueError('normal/-OO independent-oracle disagreement')


def final(run_id):
    if type(run_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}',run_id):
        raise ValueError('bounded new run ID required')
    helper,capture = install()
    from work.generator_upgrade_r6 import binding
    bundle = binding.load()
    _,ids,_,old_ids,_ = discover(bundle,helper)
    require_inventory(ids); require_inventory(old_ids,retained=True)
    parent_data = test_data_bindings()
    stable(bundle,helper,capture)
    root = bundle.storage.plain_path(OUTPUT_ROOT/run_id)
    root.mkdir(parents=True,exist_ok=False)
    bundle.storage.write_json(root/'PARENT_SOURCE.json',{'source_identity':bundle.identity,'source_sha256':bundle.source_sha256,
        'parent_optimisation_flag':sys.flags.optimize,'external_test_data':parent_data})
    records = []
    for label,mode,flags in (('n',0,[]),('o',2,['-OO'])):
        path = root/(label+'-worker.json')
        command = [sys.executable,'-B',*flags,str(HERE/'verify.py'),'--worker',str(path),
            '--parent-source',str(root/'PARENT_SOURCE.json'),'--mode',str(mode)]
        print('Executing source-bound mode '+str(mode),flush=True)
        try:
            result = subprocess.run(command,cwd=TASK,env=helper.child_environment(),capture_output=True,text=True,timeout=WORKER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            bundle.storage.write_json(root/(label+'-process.json'),{'status':'TIMEOUT','timeout_seconds':WORKER_TIMEOUT_SECONDS})
            raise RuntimeError('bounded verification worker timed out; no PASS seal') from error
        bundle.storage.write_json(root/(label+'-process.json'),{'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode:
            raise RuntimeError('verification worker failed; diagnostics preserved at '+str(root))
        records.append(bundle.storage.read_json(path))
    validate_workers(records,bundle,helper)
    stable(bundle,helper,capture)
    receipt = {'schema':'diadem.strict-soil-water-verification.r6','status':'BOUNDED_STRICT_SOLVER_SUCCESSOR_VERIFIED',
        'source_identity':bundle.identity,'source_sha256':bundle.source_sha256,'source_snapshot':bundle.identity['r6_sources'],
        'new_distinct_checks':len(ids),'new_test_ids':ids,'new_inventory_sha256':NEW_INVENTORY_SHA256,
        'retained_regression_checks':len(old_ids),'retained_test_ids':old_ids,'retained_inventory_sha256':RETAINED_INVENTORY_SHA256,
        'retained_regression_is_new_tests':False,'actual_interpreter_modes':[0,2], 'parent_optimisation_flag':sys.flags.optimize,
        'runs_per_check':2,'failures':0,'errors':0,'skips':0,
        'workers':[{'path':str(root/(label+'-worker.json')),'sha256':sha((root/(label+'-worker.json')).read_bytes()),
            'test_duration_seconds':row['test_duration_seconds'],'worker_duration_seconds':row['worker_duration_seconds'],
            'cases':row['cases'],'oracle':row['oracle']} for label,row in zip(('n','o'),records)],
        'executed_source_hashes':records[0]['executed_source_hashes'],'private_dependency_executions':records[0]['private_dependency_executions'],
        'case_sha256':sha(encoded(validate_cases(records[0]['cases'],bundle))),
        'refinement_report':records[0]['refinement_report'],'refinement_sha256':records[0]['refinement_sha256'],
        'external_test_data':records[0]['external_test_data'],
        'external_test_data_role':'frozen captured fixtures and independent temporal/gross-flux diagnostic evidence; not substituted physical inputs for connected cases',
        'production_installed':False,'canon_changed':False,'world_generated':False,'generation_speedup_percent':None,
        'strict_cases_completed':[120,60,30],
        'scope':'corrected R6 soil-water numerics in isolated exact preserved climate/hydromet/terrain/soil pipeline; default and cap120 all three coequal members full/restart; cap60/30 one explicitly selected coequal member; no universal accuracy or production claim'}
    bundle.storage.write_json(root/'VERIFICATION.json',receipt)
    if bundle.storage.read_json(root/'VERIFICATION.json') != receipt:
        raise IOError('final receipt readback mismatch')
    capture.active = False
    print(json.dumps({'status':receipt['status'],'new_checks':len(ids),'retained_regression':len(old_ids)}),flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--inventory',action='store_true')
    action.add_argument('--run-id')
    action.add_argument('--worker',type=Path)
    parser.add_argument('--parent-source',type=Path)
    parser.add_argument('--mode',type=int,choices=(0,2))
    args = parser.parse_args()
    if args.inventory:
        helper,capture = install()
        from work.generator_upgrade_r6 import binding
        bundle = binding.load()
        _,ids,_,old_ids,_ = discover(bundle,helper)
        stable(bundle,helper,capture)
        capture.active = False
        print(json.dumps({'status':'DISCOVERY_ONLY_NOT_VERIFICATION','new_count':len(ids),'new_sha256':inventory_digest(ids),
            'retained_count':len(old_ids),'retained_sha256':inventory_digest(old_ids),'new_ids':ids,'retained_ids':old_ids}),flush=True)
        return 0
    if args.worker:
        if args.parent_source is None or args.mode is None:
            parser.error('worker requires parent-source and actual mode')
        return worker(args.worker,args.parent_source,args.mode)
    return final(args.run_id)


def bootstrap():
    path = Path(__file__).resolve()
    raw = path.read_bytes()
    namespace = {'__name__':'__verified_r6_entry__','__file__':str(path)}
    exec(compile(raw,str(path),'exec',dont_inherit=True),namespace)
    namespace['ENTRY_SOURCE_SHA256'] = sha(raw)
    return namespace['main']()


if __name__ == '__main__':
    raise SystemExit(bootstrap())
