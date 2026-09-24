"""Bounded later-workflow profiling using retained public fixtures."""
import cProfile
import hashlib
import importlib
import json
import os
from pathlib import Path
import pstats
import sys
import time

for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS'):
    os.environ[key] = '1'
REPO = Path(os.environ.get('W11_REPO', str(Path(__file__).resolve().parents[2])))
sys.path[:0] = [str(REPO/'tectonics'/p) for p in ('src', 'tests', 'tools')]
if os.environ.get('W11_SOURCE'):
    sys.path.insert(0, os.environ['W11_SOURCE'])
from atlas_tectonics.resources import WorkBudget


def array_record(value):
    return dict(shape=value.shape, dtype=value.dtype.str, sha256=hashlib.sha256(value.tobytes()).hexdigest())


def run(route, scientific=False):
    budget = WorkBudget(128 << 20)
    if route == 'w05':
        m = importlib.import_module('benchmark_w05_workflow')
        with budget.reserve(m.COMPARISON_BYTES, category='w11-profile-output'):
            result, keys, execution = m.expected_outputs(m.configuration(), budget)
            signature = [m.output_record(x) for x in result]
            if scientific:
                signature = []
                for item in result:
                    md = item['material_descriptor']
                    support = json.loads(item['support_metadata'])
                    # Exact scientific bytes, accounts and physical metadata;
                    # source-derived identities are retained in the full record
                    # but are not labelled equal across source revisions.
                    signature.append(dict(fields={k:m.output_record({k:item[k]})[k] for k in
                        ('material_bytes','grid_bytes','exchange_bytes','support_fields','support_points','intervals','max_courant')},
                        material={k:md[k] for k in ('schema','grid','cohorts','time_s','epoch_id','dtype','layout','quantity')},
                        accounts=md['transition']['cumulative_cohort_accounts'],
                        support={k:v for k,v in support.items() if k not in
                            ('plan','initial','current','load_reference','load_current','execution')}))
    elif route.startswith('w06-'):
        m = importlib.import_module('benchmark_w06_workflow')
        with budget.reserve(m.CALLER_ALLOWANCE, category='w11-profile-output'):
            result, _, _, _ = m.run_once(route.removeprefix('w06-'), budget)
            signature = m.checkpoint_signature(result)
            if scientific:
                from w06_workflow_case import scientific_arrays, _record
                from dataclasses import fields
                state = result.state
                signature=dict(output_index=result.output_index, arrays=[array_record(a) for a in scientific_arrays(state)])
                if route=='w06-margin':
                    signature['support']={f.name:_record(getattr(state,f.name)) for f in fields(state)
                        if f.name not in ('thermal','support_id','thermal_owner')}
                    signature['thermal']={f.name:_record(getattr(state.thermal,f.name)) for f in fields(state.thermal)
                        if f.name not in ('source_state','source_state_id','plan_id','state_id','execution_id')}
                else:
                    signature.update(time_s=state.time_s,exports=_record(state.exports))
    elif route.startswith('w07-'):
        m = importlib.import_module('test_w07_workflow')
        mode = route.removeprefix('w07-')
        with m.make_workflow_fixture(mode, budget=budget, thermal=mode == 'thermal') as plan:
            result = plan.run()
            signature = m.output_signature(result)
            for obj in (result.state, result.mechanics):
                signature[obj.result_id] = {n: hashlib.sha256(obj.array(n).tobytes()).hexdigest() for n in obj.array_names}
    elif route == 'w08-joined':
        m = importlib.import_module('test_w08_workflow')
        with m.make_workflow_fixture(budget=budget) as plan:
            result = plan.run()
            signature = m.signature(result)
            if scientific:
                signature=dict(interval_index=result.interval_index,time_s=result.inventory.time_s,
                    inventory={k:array_record(getattr(result.inventory,k)) for k in
                        ('component_mass_kg','enthalpy_j','formation_time_s')},
                    labels={k:getattr(result.inventory,k) for k in
                        ('node_ids','node_kinds','component_ids','origin_ids','enthalpy_source')},
                    regional={k:array_record(getattr(result.regional,k)) for k in
                        ('mass_kg','enthalpy_j','volume_m3','thickness_m','component_mass_kg','load_change_pa','surface_addition_m','basal_addition_m')},
                    deformation=array_record(result.deformation_gradient),
                    polygons=[p.wkb.hex() for p in result.polygons],reference_polygons=[p.wkb.hex() for p in result.reference_polygons])
        del result, plan
    elif route == 'underthrust':
        m = importlib.import_module('check_underthrust')
        with m.prepare(m.make_fixture(), budget) as plan:
            signature=[]
            for t in m.OUTPUT_TIMES_S:
                state=plan.evaluate(t)
                signature.append(dict(time_s=state.time_s,arrays={k:array_record(getattr(state,k)) for k in m.ARRAY_FIELDS},
                    polygons=[p.wkb.hex() for p in state.polygons],
                    metadata={k:v for k,v in state.descriptor().items() if k not in ('plan_id','execution_id')})
                    if scientific else m.complete_signature(state,budget))
    elif route in ('evolving-regional', 'evolving-flexure'):
        m = importlib.import_module('check_evolving_inputs')
        create, solve, _ = getattr(m, route.replace('evolving-', '') + '_fixture')()
        with create(budget) as plan:
            signature=[]
            for i in range(3):
                result=solve(plan,i)
                arrays=({n:array_record(result.array(n)) for n in result.array_names} if hasattr(result,'array_names')
                    else {n:array_record(getattr(result,n)) for n in ('values','absolute_values','reservoir_surface_known')})
                signature.append(arrays if scientific else m.signature(result))
    else:
        raise ValueError(route)
    if budget.reserved_bytes:
        raise RuntimeError('unreleased reservation')
    return signature, budget.statistics()


def main():
    route, output = sys.argv[1:]
    package = Path(os.environ.get('W11_SOURCE', str(REPO/'tectonics/src')))/'atlas_tectonics'
    source = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}
    profile = cProfile.Profile()
    started = time.perf_counter()
    profile.enable()
    signature, budget = run(route)
    profile.disable()
    elapsed = time.perf_counter() - started
    if source != {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}:
        raise RuntimeError('source changed during measurement')
    stats = pstats.Stats(profile)
    rows = []
    for (path, line, name), (cc, nc, tt, ct, callers) in stats.stats.items():
        if 'atlas_tectonics' in path or 'pathlib' in path:
            rows.append(dict(file=Path(path).name, line=line, name=name, calls=nc, self_seconds=tt, cumulative_seconds=ct))
    rows.sort(key=lambda row: row['cumulative_seconds'], reverse=True)
    record = dict(route=route, elapsed_s=elapsed, budget=budget, signature=signature, top=rows[:60], source_sha256=source)
    Path(output).write_text(json.dumps(record, indent=2, default=str)+'\n', encoding='utf-8')
    print(json.dumps(dict(route=route, elapsed_s=elapsed, peak=budget['peak_reserved_bytes'], top=rows[:10]), indent=2))


if __name__ == '__main__':
    main()
