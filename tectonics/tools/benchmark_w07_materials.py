#!/usr/bin/env python3
"""Bounded W07 material-plan reuse timing; exclusive NEW evidence report.

SPDX-License-Identifier: AGPL-3.0-only
Frozen 32x32 layered shear, interface 0.37, contrast 1000 and physical pressure
datum 10 Pa. Three complete outputs include setup, input sampling, public source
verification, solves, output checks/hashing and close. No warm-up run, solver
fallback, tolerance relaxation, geological evolution or held R4.4 campaign.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'), str(ROOT/'tools')]

from check_w07_mechanics import Recorder, SourceChanged, _jsonable, _snapshot_hash

BUDGET_BYTES = 128*1024**2
CALLER_BYTES = 16*1024**2
GRID = 32
INTERFACE = .37
CONTRAST = 1000.
FRAME = 'w07-synthetic-layered-x-right-z-up'
SAMPLING = 'exact vertical shear dual-support series compliance; normal point values'
FROZEN_DESIGN_SHA256 = '1748c9e2bd43f71ad0ce65fb9d68343d3f1379570f1b2b74882b85fa2c644378'
MODES = ('fresh_changing_coefficients', 'prepared_changing_coefficients',
         'fresh_identical_requests', 'verified_identical_requests')
GATES = dict(momentum_residual=1e-9, divergence_residual=1e-10,
             normalised_work_residual=1e-9, linear_residual=1e-12,
             pressure_gauge_residual=1e-12, boundary_velocity_residual=1e-12,
             corner_trace_residual=1e-12, rigid_constraint_residual=1e-10)


def _sources():
    paths = [*sorted((ROOT/'src/atlas_tectonics').rglob('*.py')),
             Path(__file__), ROOT/'tools/check_w07_mechanics.py',
             ROOT/'tests/w07_interface_reference.py', ROOT/'cases/w07_mechanics.json',
             ROOT/'docs/W07_REGIONAL_MECHANICS.md']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


class MaterialRecorder(Recorder):
    def verify(self):
        if _sources() != self.sources:
            raise SourceChanged('source/case/script bytes changed; material timing is not valid')


def _material_source(factor):
    return 'synthetic-layered-viscosity-factor-'+repr(factor)


def _accuracy(snapshot, factor):
    """Continuum layered velocity, physical datum, stress and work, not A*u."""
    import numpy as np
    from w07_interface_reference import layered_velocity
    u, w = snapshot.array('u_m_s'), snapshot.array('w_m_s')
    exact = np.broadcast_to(layered_velocity((np.arange(GRID)+.5)[:, None]/GRID,
                                             INTERFACE), u.shape)
    weights_u, weights_w = np.ones_like(u), np.ones_like(w)
    weights_u[:, [0, -1]] = .5
    weights_w[[0, -1]] = .5
    numerator = float(np.sum(weights_u*(u-exact)**2)+np.sum(weights_w*w*w))
    denominator = float(np.sum(weights_u*exact**2))
    velocity_error = (numerator/denominator)**.5
    tau = factor/(INTERFACE+(1-INTERFACE)/CONTRAST)
    shear_error = float(np.max(np.abs(snapshot.array('deviatoric_stress_xz_pa')-tau)))/tau
    pressure_error = float(np.max(np.abs(snapshot.array('physical_pressure_pa')-10.)))/10.
    description = snapshot.descriptor()
    work_error = abs(description['dimensional_diagnostics']['dissipation_w_per_m']-tau)/tau
    diagnostics = description['diagnostics']
    if diagnostics.get('gates_passed') is not True:
        raise AssertionError('public returned fields failed frozen mechanical gates')
    for name, limit in GATES.items():
        value = diagnostics.get(name)
        if value is None or not np.isfinite(value) or abs(value) > limit:
            raise AssertionError(f'frozen {name} gate failed: {value!r} > {limit}')
    if max(velocity_error, shear_error, work_error) > .01 or pressure_error > 1e-9:
        raise AssertionError('layered continuum velocity/shear/work or physical datum not resolved')
    return dict(velocity_relative_l2=velocity_error, shear_max_relative=shear_error,
                integrated_shear_work_relative=work_error, pressure_scaled_max=pressure_error,
                expected_shear_pa=tau, gates={name: diagnostics[name] for name in GATES})


def _sequence(owner, mode):
    import numpy as np
    from atlas_tectonics.regional_execution import PreparedRegionalStokes2D, RegionalMechanicsScales
    from w07_interface_reference import layered_sites, layered_velocity
    factors = (1., 1.25, 1.5) if mode.endswith('changing_coefficients') else (1., 1., 1.)
    retained = mode.startswith(('prepared', 'verified'))
    times = dict(preparation=[], material_sampling=[], boundary_sampling=[], coefficient_refill=[],
                 complete_request=[], output_validation=[], close=[])
    snapshots, accuracy, hashes, ids, stats = [], [], [], [], []
    plan = previous = None
    started = time.perf_counter()
    try:
        for index, factor in enumerate(factors):
            begin = time.perf_counter()
            ec, ev = layered_sites(GRID, GRID, INTERFACE, lower=factor, upper=CONTRAST*factor)
            times['material_sampling'].append(time.perf_counter()-begin)
            if plan is None:
                begin = time.perf_counter()
                types = {side: {'u': 'velocity', 'w': 'velocity'}
                         for side in ('left', 'right', 'bottom', 'top')}
                plan = PreparedRegionalStokes2D(GRID, GRID, 1., 1., 1., types,
                    scales=RegionalMechanicsScales(1., 1.), frame_id=FRAME,
                    vertical_datum='synthetic z=0', material_source=_material_source(factor),
                    physical_mean_pressure_pa=10., method='gmres', budget=owner,
                    viscosity_center_pa_s=ec, viscosity_vertex_pa_s=ev, material_sampling=SAMPLING)
                times['preparation'].append(time.perf_counter()-begin)
            elif mode == 'prepared_changing_coefficients':
                begin = time.perf_counter()
                plan.update_viscosity(ec, ev, material_source=_material_source(factor), material_sampling=SAMPLING)
                times['coefficient_refill'].append(time.perf_counter()-begin)
            begin = time.perf_counter()
            boundary = {side: {component: (layered_velocity(plan.coordinates((side, component))[1],
                          INTERFACE) if component == 'u' else 0.) for component in ('u', 'w')}
                        for side in ('left', 'right', 'bottom', 'top')}
            fu, fw = np.zeros((GRID, GRID+1)), np.zeros((GRID+1, GRID))
            times['boundary_sampling'].append(time.perf_counter()-begin)
            begin = time.perf_counter()
            result = plan.solve(fu, fw, boundary, frame_id=FRAME, epoch_id='synthetic-steady',
                time_s=0., force_source='explicit zero body force',
                boundary_source='exact layered velocity; no normal traction; independent P=10 datum')
            times['complete_request'].append(time.perf_counter()-begin)
            if mode == 'verified_identical_requests' and previous is not None and result is not previous:
                raise AssertionError('identical request did not return the verified latest snapshot')
            begin = time.perf_counter()
            accuracy.append(_accuracy(result, factor))
            hashes.append(_snapshot_hash(result)); ids.append(result.result_id)
            snapshots.append(result); stats.append(plan.statistics())
            times['output_validation'].append(time.perf_counter()-begin)
            previous = result
            if not retained:
                begin = time.perf_counter(); plan.close(); plan = None
                times['close'].append(time.perf_counter()-begin)
    finally:
        if plan is not None:
            begin = time.perf_counter(); plan.close()
            times['close'].append(time.perf_counter()-begin)
    elapsed = time.perf_counter()-started
    if mode == 'prepared_changing_coefficients' and stats[-1].get('coefficient_refills') != 2:
        raise AssertionError('changing material sequence did not refill twice')
    if mode == 'verified_identical_requests' and stats[-1]['latest_result_hits'] != 2:
        raise AssertionError('identical sequence did not reuse twice')
    if owner.reserved_bytes != CALLER_BYTES:
        raise AssertionError('public plan left a retained budget reservation after close')
    return (dict(end_to_end_seconds=elapsed, stage_seconds=times, coefficients=factors,
                 output_sha256=hashes, result_ids=ids, accuracy=accuracy, plan_statistics=stats), snapshots)


def _compare(left, right, *, exact):
    import numpy as np
    if len(left) != 3 or len(right) != 3:
        raise AssertionError('three matched outputs required')
    maximum = 0.
    field_count = 0
    for a, b in zip(left, right):
        if a.array_names != b.array_names:
            raise AssertionError('compared output field sets differ')
        for name in a.array_names:
            av, bv = a.array(name), b.array(name)
            if av.shape != bv.shape:
                raise AssertionError('compared field support differs: '+name)
            error = float(np.max(np.abs(av-bv)))/max(1., float(np.max(np.abs(av))))
            maximum = max(maximum, error); field_count += 1
            if exact:
                if av.tobytes() != bv.tobytes():
                    raise AssertionError('identical-request output bytes differ: '+name)
            elif error > 2e-10:
                raise AssertionError(f'cold/refill field mismatch {name}: scaled maximum {error}')
    return dict(fields_compared=field_count, maximum_scaled_field_difference=maximum,
                exact_bytes_required=exact, cold_refill_scaled_roundoff_limit=2e-10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=ROOT/'evidence/w07-material-timing.json')
    args = parser.parse_args()
    report = dict(schema='atlas.w07-material-reuse-timing.v1', source_status='WORKING NON-CANON',
        status='INCOMPLETE', checks=[], command=sys.argv,
        case=dict(nx=GRID,nz=GRID,width_m=1.,height_m=1.,interface=INTERFACE,
                  viscosity_contrast=CONTRAST,physical_mean_pressure_pa=10.,all_boundaries='velocity'),
        runtime=dict(python=sys.version,platform=platform.platform()),
        resource_policy=dict(work_budget_bytes=BUDGET_BYTES,caller_allowance_bytes=CALLER_BYTES,
                             numerical_threads=1,OS_RSS_cap=False,automatic_fallback=False),
        scope='Three complete public material-mechanics outputs; preparation, coefficient sampling/refill, '
              'boundary sampling, source verification in public calls, solves, output checks/hashing and close '
              'included. Imports/startup excluded. First sample includes native first-use overhead; no warmup. '
              'Finite steady synthetic B06 snapshots; no thermal/surface evolution, R4.4, empirical or whole-generator claim.')
    # Reserve the NEW path before execution. Failure evidence is written here;
    # an existing historical report is never replaced or modified.
    with args.report.open('x', encoding='utf-8') as output:
        try:
            sources = _sources(); report['source_sha256'] = sources
            design = json.loads((ROOT/'cases/w07_mechanics.json').read_text(encoding='utf-8'))
            if (sources['docs/W07_REGIONAL_MECHANICS.md'] != FROZEN_DESIGN_SHA256 or
                    design['frozen_design']['sha256'] != FROZEN_DESIGN_SHA256):
                raise SourceChanged('frozen W07 design differs; no automatic repin')
            import numpy as np
            import scipy
            from atlas_tectonics.resources import WorkBudget
            from atlas_tectonics.stokes_execution import _native_lease
            from threadpoolctl import threadpool_info
            report['runtime'].update(numpy=np.__version__, scipy=scipy.__version__)
            recorder = MaterialRecorder(report, sources)
            owner = WorkBudget(BUDGET_BYTES)
            samples = {mode: [] for mode in MODES}
            orders = []
            try:
                with _native_lease(), owner.reserve(CALLER_BYTES, category='w07-material-timing-caller'):
                    pools = [{k: p.get(k) for k in ('internal_api','prefix','num_threads')} for p in threadpool_info()]
                    report['runtime']['native_threadpools'] = pools
                    if any(p['num_threads'] != 1 for p in pools):
                        raise RuntimeError('managed native lease did not establish one numerical thread')
                    for repeat in range(3):
                        rotation = MODES[repeat:]+MODES[:repeat]
                        orders.append(rotation)
                        actual = {}
                        for mode in rotation:
                            def execute(mode=mode):
                                row, snapshots = _sequence(owner, mode)
                                actual[mode] = snapshots
                                retained = sum(s.nbytes for group in actual.values() for s in group)
                                if retained > CALLER_BYTES:
                                    raise AssertionError('retained snapshot bytes exceed caller allowance')
                                row['retained_snapshot_bytes_this_rotation'] = retained
                                return row
                            value = recorder.call(f'timing/{repeat+1}/{mode}', execute)
                            if value is not None:
                                samples[mode].append(value)
                        for baseline, candidate in ((MODES[0],MODES[1]),(MODES[2],MODES[3])):
                            if baseline in actual and candidate in actual:
                                recorder.call(f'parity/{repeat+1}/{candidate}',
                                    lambda b=baseline,c=candidate: _compare(actual[b], actual[c], exact=c==MODES[3]))
                            else:
                                recorder.gate(f'parity/{repeat+1}/{candidate}', False,
                                              dict(reason='one or more compared sequences failed'))
                    recorder.verify()
            finally:
                report['budget'] = owner.statistics()
            if report['budget']['reserved_bytes']:
                recorder.gate('resource-cleanup', False, report['budget'])
            summary = dict(rotating_order=orders, raw=samples)
            for baseline, candidate in ((MODES[0],MODES[1]),(MODES[2],MODES[3])):
                valid = len(samples[baseline]) == len(samples[candidate]) == 3 and all(
                    row['status'] == 'PASS' for row in report['checks'] if
                    row['name'].startswith('parity/') and row['name'].endswith(candidate))
                if not valid:
                    summary[candidate] = dict(status='NO_SAVING_CLAIM', reason='missing matched accepted outputs')
                    continue
                left = [r['end_to_end_seconds'] for r in samples[baseline]]
                right = [r['end_to_end_seconds'] for r in samples[candidate]]
                before, after = statistics.median(left), statistics.median(right)
                summary[candidate] = dict(status='MATCHED_ACCEPTED_OUTPUTS', baseline_seconds=left,
                    candidate_seconds=right, baseline_median_seconds=before, candidate_median_seconds=after,
                    saved_seconds=before-after, saved_percent=100*(before-after)/before,
                    baseline_first_minus_median_seconds=left[0]-before,
                    candidate_first_minus_median_seconds=right[0]-after)
            report['workflow_timing'] = summary
            report['failures'] = [r['name'] for r in report['checks'] if r['status'] != 'PASS']
            report['status'] = 'PASS_W07_MATERIAL_TIMING' if not report['failures'] else 'FAIL_W07_MATERIAL_TIMING'
        except BaseException as exc:
            report['status'] = 'FAIL_W07_MATERIAL_TIMING'
            report['fatal_error'] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc(limit=8))
        json.dump(_jsonable(report), output, indent=2, allow_nan=False)
        output.write('\n'); output.flush()
    print(json.dumps(dict(status=report['status'], checks=len(report['checks']),
                          failures=report.get('failures', []), fatal=report.get('fatal_error'),
                          report=str(args.report))))
    return 0 if report['status'].startswith('PASS') else 1


if __name__ == '__main__':
    raise SystemExit(main())
