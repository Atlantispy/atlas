"""Bounded exact-field and preparation-reuse measurement for 3D mechanics.

SPDX-License-Identifier: AGPL-3.0-only
Not a planetary run or a calibrated geological simulation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

import numpy as np
import scipy

from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES


def bindings():
    names = ['tools/check_regional3d.py', 'docs/REGIONAL_MECHANICS_3D.md',
             'tests/test_regional_elements3d.py', 'tests/test_regional_execution3d.py',
             'tests/test_regional_multigrid3d.py', 'tests/test_regional_solver_selection3d.py']
    names += [str(p.relative_to(ROOT)).replace('\\', '/')
              for p in sorted((ROOT/'src'/'atlas_tectonics').glob('*.py'))]
    return {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}


def cross_shear(xyz):
    x,y,z = np.moveaxis(xyz,-1,0)
    return np.stack((y*z,z*x,x*y),axis=-1)


def controls(method='gmres'):
    start = perf_counter()
    cells = (4,4,4)
    nodes = np.indices((9,9,9)).reshape(3,-1).T/8
    indices = np.indices(cells).reshape(3,-1).T
    g,_ = np.polynomial.legendre.leggauss(3)
    q = (indices[:,None,:]+(g[np.indices((3,3,3)).reshape(3,-1).T][None,:,:]+1)/2)/4
    eta = 1+q[...,0]
    force = np.stack((np.ones(q.shape[:2]),2-2*q[...,2],-3-2*q[...,1]),axis=-1)
    velocity = cross_shear(nodes)
    traction = {side:0. for side in SIDES}
    def prepare():
        return PreparedRegionalStokes3D(cells,(1.,1.,1.),eta,
            {side:('velocity',)*3 for side in SIDES},
            scales=RegionalMechanicsScales(1.,1.),reference_viscosity_pa_s=1.,
            frame_id='analytical-Cartesian',vertical_datum='box-bottom-z-zero',
            material_source='eta=1+x analytic field',physical_mean_pressure_pa=0.,method=method)
    def solve(plan,parent):
        return plan.solve(force,velocity,traction,parent_state_id=parent,
            epoch_id='same-time',time_s=0.,force_source='continuous-manufactured-force',
            boundary_source='analytical-trace')
    samples = {'rebuild_and_solve':[], 'prepared_new_request':[], 'exact_result_cache':[]}
    checks = {}
    with prepare() as warm:
        reference = solve(warm,'warmup')
        checks['exact_velocity'] = bool(np.max(np.abs(reference.array('velocity_m_s')-velocity)) < 2e-9)
        pq = warm.coordinates('pressure')@np.array([1.,2.,-3.])
        checks['exact_pressure'] = bool(np.max(np.abs(reference.array('physical_pressure_pa')-pq)) < 3e-8)
        checks['bitwise_output_parity'] = True
        checks['same_immutable_snapshot'] = True
        for i in range(3):
            # Alternating order reduces a simple one-direction warmup bias.
            order = ('cold','warm') if i%2 == 0 else ('warm','cold')
            for mode in order:
                begin = perf_counter()
                if mode == 'cold':
                    with prepare() as cold:
                        result = solve(cold,'request-'+str(i))
                    name = 'rebuild_and_solve'
                else:
                    result = solve(warm,'request-'+str(i))
                    warm_result = result
                    name = 'prepared_new_request'
                samples[name].append(perf_counter()-begin)
                checks['bitwise_output_parity'] &= all(
                    np.array_equal(reference.array(k),result.array(k)) for k in reference.array_names)
            begin = perf_counter()
            cached = solve(warm,'request-'+str(i))
            samples['exact_result_cache'].append(perf_counter()-begin)
            checks['same_immutable_snapshot'] &= cached is warm_result
            if perf_counter()-start > 30.:
                raise RuntimeError('bounded 30-second control deadline exceeded')
        stats = warm.statistics()
        checks['one_factor_prepared_path'] = stats['factorizations'] == 1
        checks['three_result_hits'] = stats['result_hits'] == 3
        descriptor = reference.descriptor()
    med = {k:statistics.median(v) for k,v in samples.items()}
    baseline = med['rebuild_and_solve']
    savings = {k:{'saved_seconds':baseline-v,'saved_percent':100*(1-v/baseline)}
               for k,v in med.items() if k != 'rebuild_and_solve'}
    return dict(passed=all(checks.values()),checks=checks,
        numerical={k:descriptor[k] for k in ('linear_relative_residual','work_relative_residual',
            'weak_divergence_max','quadrature_divergence_l2','krylov_iterations')},
        benchmark=dict(cells=list(cells),samples_seconds=samples,median_seconds=med,savings=savings,
            scope='same-time 4x4x4 exact 3D heterogeneous fixture, imported runtime, not world speedup',
            method=method,
            prepared_statistics=stats), execution_identity=descriptor['plan']['execution'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--method',choices=('gmres','multigrid','auto'),default='gmres',
                        help='assembled reference (default), the matrix-free multigrid method, '
                             'or the automatic selection between them')
    args = parser.parse_args()
    with args.output.open('x',encoding='utf-8',newline='\n') as out:
        begin = perf_counter()
        report = dict(schema='atlas.regional3d-controls.v1',status='INCOMPLETE',
            scientific_acceptance=False,whole_planet_acceptance=False,
            runtime=dict(python=platform.python_version(),system=platform.system(),
                         numpy=np.__version__,scipy=scipy.__version__))
        try:
            report['source_sha256'] = bindings()
            report.update(controls(args.method))
            report['source_unchanged'] = report['source_sha256'] == bindings()
            report['status'] = 'PASS_BOUNDED_CONTROLS_ONLY' if report['passed'] and report['source_unchanged'] else 'FAIL'
        except Exception as exc:
            report.update(status='FAIL',error_type=type(exc).__name__,error=str(exc))
        report['elapsed_seconds'] = perf_counter()-begin
        json.dump(report,out,indent=2,allow_nan=False)
        out.write('\n')
    print(json.dumps({k:report[k] for k in ('status','elapsed_seconds')}))
    return 0 if report['status'] == 'PASS_BOUNDED_CONTROLS_ONLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
