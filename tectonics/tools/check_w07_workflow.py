#!/usr/bin/env python3
"""Source-pinned W07 assembly acceptance and matched final-state recovery timing.

SPDX-License-Identifier: AGPL-3.0-only
New reports only. Fixed cases, unchanged 128 MiB/256-step/one-thread ceilings.
Imports and interpreter startup are excluded; source preparation, solving,
validation, output hashing, store access and closing are included in timings.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'), str(ROOT/'tools')]
from check_w07_mechanics import Recorder, SourceChanged, _jsonable, FROZEN_DESIGN_SHA256


def sources():
    paths = [*sorted((ROOT/'src/atlas_tectonics').rglob('*.py')),
             *sorted((ROOT/'tests').glob('test_w01*.py')),
             ROOT/'tests/test_precursor_scaling.py', ROOT/'tests/test_w07_geology.py',
             ROOT/'tests/test_w07_workflow.py', ROOT/'tools/check_w07_mechanics.py',
             ROOT/'docs/W07_REGIONAL_MECHANICS.md', ROOT/'cases/w07_mechanics.json',
             Path(__file__)]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


class WorkflowRecorder(Recorder):
    def verify(self):
        if sources() != self.sources:
            raise SourceChanged('source/case/script changed during acceptance; no repinning')


def complete_identity(output):
    from test_w07_workflow import output_signature
    result = output_signature(output)
    result['arrays'] = {
        role: {name: dict(shape=snapshot.array(name).shape,
            sha256=hashlib.sha256(snapshot.array(name).tobytes()).hexdigest())
            for name in snapshot.array_names}
        for role, snapshot in (('state', output.state), ('mechanics', output.mechanics))}
    return result


def thermal_reference(nz, steps):
    """Closed Neumann heat equation: exact cosine-series cell means, not a grid oracle.

    W01 supplies T(z,0)=500-200z, rho*cp=2000, k=3, Q=2 on H=1.
    Odd coefficients are 800/(n*pi)^2; uniform heating is Q*t/(rho*cp).
    tau=k*t/(rho*cp)=.02. The fixed (grid,steps) refinement keeps dt/dz^2
    constant, testing the assembled space/time discretisation together.
    """
    import numpy as np
    from atlas_tectonics.resources import WorkBudget
    from test_w07_workflow import make_workflow_fixture
    duration = .02/(3./2000.)
    owner = WorkBudget(128*1024**2)
    with owner.reserve(4*1024**2, category='acceptance-caller-allowance'):
        with make_workflow_fixture('thermal', nx=4, nz=nz, thermal=True,
                heat_production=2., density_law='boussinesq-linear-reference',
                output_times_s=(0., duration), interval_steps=(0, steps), budget=owner) as plan:
            output = plan.run()
            z = np.linspace(0., 1., nz+1)
            n = np.arange(1, 128, 2, dtype=float)[:, None]
            cell_cos = (np.sin(n*np.pi*z[1:])-np.sin(n*np.pi*z[:-1]))/(n*np.pi/nz)
            exact = 400.+2.*duration/2000.+np.sum(
                800./(n*np.pi)**2*np.exp(-.02*(n*np.pi)**2)*cell_cos, axis=0)
            actual = output.state.array('temperature_k')
            error = float(np.sqrt(np.mean((actual-exact[:, None])**2))/100.)
            heat = output.descriptor()['heat']
            max_velocity = max(float(np.max(np.abs(output.mechanics.array(k))))
                               for k in ('u_m_s', 'w_m_s'))
            assert error < .01, ('temperature relative RMS', error)
            assert max_velocity < 1e-10, ('hydrostatic velocity', max_velocity)
            assert float(output.state.array('reference_mass_kg').sum()) == 4.
            assert abs(heat['source_energy_j']-4.*duration) < 1e-9
            assert heat['balance_relative'] <= 1e-9
            result = dict(grid=[4, nz], accepted_steps=steps, duration_s=duration,
                relative_rms_error_100k=error, max_velocity_m_s=max_velocity,
                heat=heat, output_id=output.output_id, statistics=plan.statistics())
    assert owner.reserved_bytes == 0, owner.statistics()
    result['released_budget'] = owner.statistics()
    return result


def recovery_timing():
    from atlas_tectonics.resources import WorkBudget
    from test_w07_workflow import make_workflow_fixture, open_store
    from threadpoolctl import threadpool_info
    rows = []
    identity = None
    warm_path = None
    with TemporaryDirectory(prefix='w07-acceptance-') as tmp:
        for repeat, order in enumerate((('fresh', 'save', 'restore'),
                ('save', 'restore', 'fresh'), ('restore', 'fresh', 'save'))):
            for mode in order:
                owner = WorkBudget(128*1024**2)
                path = Path(tmp)/('save-%d.db' % repeat) if mode == 'save' else warm_path
                started = time.perf_counter()
                with owner.reserve(4*1024**2, category='acceptance-caller-allowance'):
                    with (nullcontext(None) if mode == 'fresh' else open_store(path, owner)) as store:
                        with make_workflow_fixture('surface', nx=16, nz=8,
                                surface_amplitude_m=1e-4, output_times_s=(0., .01, .02),
                                interval_steps=(0, 32, 32), store=store, budget=owner) as plan:
                            output = plan.run()
                            signature = complete_identity(output)
                            stats = plan.statistics()
                            storage = None if store is None else store.statistics()
                            dedup = (None if store is None else
                                     store.metadata(output.checkpoint_id)['payload']['resources'])
                elapsed = time.perf_counter()-started
                assert owner.reserved_bytes == 0, owner.statistics()
                if identity is None:
                    identity = signature
                assert signature == identity, 'requested final state differs between execution modes'
                expected = (0, 1) if mode == 'restore' else (3, 0)
                assert (stats['computed_outputs'], stats['restored_outputs']) == expected, stats
                assert all(p['num_threads'] == 1 for p in threadpool_info())
                rows.append(dict(mode=mode, repeat=repeat, seconds=elapsed, statistics=stats,
                    storage=storage, dedup=dedup, released_budget=owner.statistics()))
                if mode == 'save':
                    warm_path = path
    medians = {mode: statistics.median(r['seconds'] for r in rows if r['mode'] == mode)
               for mode in ('fresh', 'save', 'restore')}
    return dict(workload='same final state from W01/W02 source preparation and three-output W07 surface schedule',
        grid=[16, 8], surface_amplitude_m=1e-4, wave_number=.5*3.141592653589793,
        accepted_steps=64, policy='raw lossless storage; no codec comparison', samples=rows,
        exact_signature=identity, medians_seconds=medians,
        restore_saving_seconds=medians['fresh']-medians['restore'],
        restore_saving_percent=100.*(1.-medians['restore']/medians['fresh']),
        first_save_overhead_seconds=medians['save']-medians['fresh'],
        first_save_overhead_percent=100.*(medians['save']/medians['fresh']-1.))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--mode', choices=('acceptance', 'timing', 'all'), default='all')
    args = parser.parse_args()
    # Claim a NEW path before importing scientific dependencies or executing work.
    with args.report.open('x', encoding='utf-8') as handle:
        report = dict(schema='atlas.w07.workflow.acceptance.v1', source_status='WORKING NON-CANON',
            mode=args.mode, checks=[], limits=dict(accounted_bytes=128*1024**2,
                caller_allowance_bytes=4*1024**2, accepted_steps=256, native_threads=1,
                os_rss_measured=False), sources=sources())
        recorder = WorkflowRecorder(report, report['sources'])
        started = time.perf_counter()
        try:
            import numpy as np
            import scipy
            from atlas_tectonics.stokes_execution import _native_lease
            from threadpoolctl import threadpool_info
            report['environment'] = dict(platform=platform.platform(), python=sys.version,
                numpy=np.__version__, scipy=scipy.__version__)
            assert report['sources']['docs/W07_REGIONAL_MECHANICS.md'] == FROZEN_DESIGN_SHA256
            assert report['sources']['cases/w07_mechanics.json'] == '07954c94de0099bea8a7d188907a715ddcac2265e4d4a51ce7488505d89c32b9'
            with _native_lease():
                report['native_pools'] = threadpool_info()
                assert all(p['num_threads'] == 1 for p in report['native_pools'])
                if args.mode != 'timing':
                    rows = [recorder.call('assembled/closed-heat/%d' % nz,
                            lambda n=nz, s=steps: thermal_reference(n, s))
                            for nz, steps in ((16, 16), (32, 64), (64, 256))]
                    errors = [r['relative_rms_error_100k'] for r in rows if r is not None]
                    ratios = [a/b for a, b in zip(errors, errors[1:])]
                    recorder.gate('assembled/closed-heat/space-time-refinement',
                        len(errors) == 3 and all(r > 2.5 for r in ratios), dict(errors=errors, ratios=ratios))
                if args.mode != 'acceptance':
                    recorder.call('matched-final-state/recovery', recovery_timing)
            recorder.verify()
        except Exception as exc:
            report['fatal'] = dict(type=type(exc).__name__, message=str(exc))
        finally:
            report['elapsed_seconds'] = time.perf_counter()-started
            report['status'] = ('PASS' if report['checks'] and 'fatal' not in report and
                all(c['status'] == 'PASS' for c in report['checks']) else 'FAIL')
            json.dump(_jsonable(report), handle, indent=2, allow_nan=False)
            handle.write('\n')
        print(json.dumps(dict(status=report['status'], report=str(args.report),
            checks=[dict(name=c['name'], status=c['status'], error=c.get('error')) for c in report['checks']],
            fatal=report.get('fatal'), elapsed_seconds=report['elapsed_seconds'])))
        return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
