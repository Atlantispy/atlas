"""Serial, bounded native dev41 candidate comparison; not a campaign.

SPDX-License-Identifier: AGPL-3.0-only
Source roots are isolated, explicitly changed implementations. Raw fields start
NEW runs, never rebound checkpoints. Output directories must not already exist.
"""
import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

THREADS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
           'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS',
           'NUMBA_NUM_THREADS')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_record(root):
    paths = list((root/'src/atlas_tectonics').glob('*.py'))
    paths += [root/'tools/run_convection_r4_4.py', root/'pyproject.toml']
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(paths)}


def write(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write('\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--cells', type=int, default=128)
    parser.add_argument('--case', choices=('tosi-1', 'tosi-2'), default='tosi-2')
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    root = args.source.resolve()/'tectonics'
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    before = source_record(root)
    record = dict(label=args.label, source=before, source_root=str(root),
                  benchmark_sha256=digest(Path(__file__).read_bytes()), command=sys.argv,
                  status='IN_PROGRESS / WORKING NON-CANON', completed=False,
                  timing_scope='NEW state, plan, two advances, one final diagnostic, close; excludes JIT, input and evidence I/O',
                  sampling='one final snapshot, not production cadence or full campaign')
    for key in THREADS:
        os.environ[key] = '1'
    sys.path.insert(0, str(root/'src'))
    import numpy as np
    import scipy
    import numba
    from numba.core.registry import CPUDispatcher
    from threadpoolctl import threadpool_info, threadpool_limits
    import atlas_tectonics as at
    from atlas_tectonics.resources import WorkBudget
    spec = importlib.util.spec_from_file_location('candidate_runner', root/'tools/run_convection_r4_4.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    numba.set_num_threads(1)
    policies = dict(policy=at.ThermochemicalPolicy(max_steps=2),
        nonlinear_policy=at.NonlinearStokesPolicy(max_picard_iterations=400,
            linear_rtol=1e-12, momentum_tolerance=1e-9, viscosity_rtol=1e-8,
            ilu_fill_factor=17, velocity_preconditioner='gmg'),
        nonlinear_start='previous-stage1', anderson_policy=at.AndersonPolicy(),
        adaptive_inner_policy=at.AdaptiveInnerPolicy(),
        preconditioner_reuse_policy=at.PreconditionerReusePolicy(max_uses=4))
    record['policies'] = {k: asdict(v) if k != 'nonlinear_start' else v for k, v in policies.items()}
    record['dt_s'] = 1e-7
    budget = WorkBudget(1024 << 20)
    arrays = {}

    def signatures():
        return {mn+'.'+name: sorted(map(str, v.signatures))
                for mn, m in list(sys.modules.items()) if mn.startswith('atlas_tectonics.') and m
                for name, v in vars(m).items() if isinstance(v, CPUDispatcher)}

    def run(n, temperature, composition, measured):
        cancel = runner.Cancellation(240.)
        clock = time.perf_counter()
        p = at.TosiCase(args.case).problem(n)
        s = at.ThermochemicalState(p, temperature, composition, time_s=0.,
                source='NEW bounded solver review fields', budget=budget)
        q = at.PreparedThermochemical2D(p, budget=budget, cancel=cancel, **policies)
        info = dict(preparation_s=time.perf_counter()-clock, step_s=[])
        steps = []
        try:
            for i in range(2):
                started = time.perf_counter()
                r = q.advance(s, 1e-7, source='bounded review physical step', cancel=cancel)
                info['step_s'].append(time.perf_counter()-started)
                steps.append(r)
                s = r.state
            started = time.perf_counter()
            flow = q.mechanical_snapshot(s, source='bounded review endpoint', cancel=cancel)
            info['snapshot_s'] = time.perf_counter()-started
        finally:
            started = time.perf_counter()
            q.close()
            info['close_s'] = time.perf_counter()-started
        info['total_s'] = time.perf_counter()-clock
        info['physical_s'] = info['preparation_s']+sum(info['step_s'])+info['close_s']
        assert budget.reserved_bytes == 0
        if not measured:
            return info
        record['timing'] = info
        info['steps'] = [x.state.descriptor() for x in steps]
        info['flow'] = flow.descriptor()
        for i, step in enumerate(steps):
            for key in step.array_names:
                arrays[f'step{i}.transport.{key}'] = step.array(key)
            for key in step.state.array_names:
                arrays[f'step{i}.state.{key}'] = step.state.array(key)
        for key in flow.array_names:
            if not key.startswith('initial_guess_'):
                arrays['snapshot.'+key] = flow.array(key)
        # Keep the unchanged publication gates explicit in local review evidence.
        d = info['flow']['diagnostics']
        policy = policies['nonlinear_policy']
        for key, bound in (('momentum_linf', policy.momentum_tolerance),
                ('divergence_linf', policy.divergence_tolerance),
                ('pressure_gauge_relative', policy.gauge_tolerance),
                ('gauge_multiplier_abs', policy.gauge_tolerance),
                ('work_balance_relative', policy.work_balance_tolerance)):
            assert 0 <= d[key] <= bound, (key, d[key], bound)
        adaptive = info['flow'].get('adaptive_inner')
        if adaptive and adaptive['active']:
            cert = adaptive['final_certification']
            assert cert['returned_residual_l2'] <= cert['target_l2']
        return info

    try:
        with threadpool_limits(limits=1):
            record['environment'] = dict(python=sys.version, platform=platform.platform(),
                processor=platform.processor(), numpy=np.__version__, scipy=scipy.__version__,
                numba=numba.__version__, threads=threadpool_info())
            assert all(x['num_threads'] == 1 for x in threadpool_info())
            record['warmup'] = run(8, at.tosi_initial_temperature(8), np.zeros((8,8)), False)
            sig = signatures()
            if args.fixture:
                raw = args.fixture.read_bytes()
                record['input_kind'] = 'NEW caller-supplied raw fields; document origin separately; not a checkpoint'
                record['input_file_sha256'] = digest(raw)
                with np.load(args.fixture, allow_pickle=False) as data:
                    temperature, composition = data['temperature_k'], data['composition']
            else:
                record['input_kind'] = 'analytic initial, not developed'
                temperature = at.tosi_initial_temperature(args.cells)
                composition = np.zeros_like(temperature)
            assert temperature.shape == composition.shape == (args.cells, args.cells)
            record['input_hashes'] = {k: digest(a.tobytes()) for k,a in
                [('temperature', temperature), ('composition', composition)]}
            record['timing'] = run(args.cells, temperature, composition, True)
            record['jit_signatures_unchanged'] = sig == signatures()
            assert record['jit_signatures_unchanged'], 'JIT compilation entered timing'
            record['completed'] = True
    except BaseException as exc:
        record['error'] = type(exc).__name__+': '+str(exc)
        record['traceback'] = traceback.format_exc()
        raise
    finally:
        record['budget_after_close'] = budget.statistics()
        record['source_unchanged'] = before == source_record(root)
        if arrays:
            np.savez_compressed(out/'arrays.npz', **arrays)
            record['arrays_sha256'] = digest((out/'arrays.npz').read_bytes())
        write(out/'result.json', record)
        print(json.dumps({k:record.get(k) for k in ('label','completed','error','source_unchanged')} |
            {'timing': {k:v for k,v in record.get('timing',{}).items() if k not in ('steps','flow')}}), flush=True)
        assert record['source_unchanged'], 'Source changed during benchmark'


if __name__ == '__main__':
    main()
