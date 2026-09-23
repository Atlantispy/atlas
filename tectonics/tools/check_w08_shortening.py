#!/usr/bin/env python3
"""Bounded W08 shortening reference and matched prepared-workflow timings.

No plots, long simulation or benchmark tolerance updates. Imports/interpreter
startup are excluded; timing includes input preparation, source verification,
motion, conservative projection, support, result hashing and owner closing.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
import numpy as np
import scipy
from threadpoolctl import threadpool_limits
from atlas_tectonics.materials import MaterialCohort, MaterialState
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.parameters import FlexureParameters
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.shortening import PreparedShortening, ShorteningInterval
from atlas_tectonics.shortening_support import PreparedShorteningSupport, ShorteningSupportPolicy
from w05_support_reference import piecewise_constant_response


ELASTIC = FlexureParameters('W08-physical-control', 'synthetic-elastic-properties',
                            7e10, 1e4, .25, 3300., 9.81)
POLICY = ShorteningSupportPolicy(ELASTIC, 3300., 1e4, .1, .1, 'bounded-control-validity')
FROZEN_SHA = '3a5b025a9e313e89a4e2eb6d8050a9e34b156d15d1d8c652bc13b66cd4eb51de'


def sources():
    files = [*sorted((ROOT/'src/atlas_tectonics').rglob('*.py')),
             ROOT/'cases/w08_regimes.json', ROOT/'docs/W08_REGIMES.md',
             ROOT/'tests/w05_support_reference.py', Path(__file__)]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def fixture(stack, n):
    budget = WorkBudget(128*1024**2)
    initial = MaterialState(ColumnGrid1D(np.linspace(0., 1e5, 65), frame_id='W08-control', budget=budget),
        (MaterialCohort('a', 'upper-crust', 'synthetic-upper', -1.),
         MaterialCohort('b', 'lower-crust', 'synthetic-lower', -1.)),
        np.array([np.full(64, 1e4), np.full(64, 2e4)]), time_s=0., epoch_id='synthetic-seconds', budget=budget)
    motion = stack.enter_context(PreparedShortening(initial,
        (ShorteningInterval(1., float(np.log(.98)), 0., 0., 'synthetic-finite-history'),),
        density_kg_m3=[2700., 2850.], width_m=1000., datum_id='fixed-initial-base',
        source_id='W08-bounded-physical-control', budget=budget))
    target = ColumnGrid1D(np.linspace(-5e4, 1.5e5, n+1), frame_id='W08-control', budget=budget)
    support = stack.enter_context(PreparedShorteningSupport(motion, target, POLICY,
        support_height_m=np.full(n, 1e5), replacement_density_kg_m3=np.zeros(n),
        geometry_source='complete-finite-footprint', budget=budget))
    return motion, support, budget


def signature(state, result):
    return dict(state=state.state_id, support=result.result_id,
        fields=hashlib.sha256(result._fields+result._points+result._phase_loads).hexdigest())


def run_frames(n, prepared):
    values = []; peak = 0
    if prepared:
        with ExitStack() as stack:
            motion, support, budget = fixture(stack, n)
            for t in (.25, .5, 1.):
                state = motion.evaluate(t)
                values.append(signature(state, support.solve(state)))
            peak = budget.peak_reserved_bytes
        assert budget.reserved_bytes == 0
    else:
        for t in (.25, .5, 1.):
            with ExitStack() as stack:
                motion, support, budget = fixture(stack, n)
                state = motion.evaluate(t)
                values.append(signature(state, support.solve(state)))
                peak = max(peak, budget.peak_reserved_bytes)
            assert budget.reserved_bytes == 0
    return values, peak


def reference_check():
    # Independent continuum load from the original and shortened rectangular
    # material bodies, NOT the already cell-averaged production load arrays.
    x = np.linspace(-5e4, 1.5e5, 17)
    q0 = 2800.*9.81*30000.
    truth = np.array([piecewise_constant_response(float(point), [0., 98000., 100000.],
        [q0*(1/.98-1), -q0], rigidity_n_m=ELASTIC.rigidity_n_m,
        restoring_pa_per_m=ELASTIC.restoring_pa_per_m)[0][0] for point in x])
    rows = []
    for n in (64, 128, 256):
        with ExitStack() as stack:
            motion, support, budget = fixture(stack, n)
            result = support.solve(motion.evaluate(1.))
            indices = np.rint((x+5e4)/(2e5/(2*n))).astype(int)
            error = result.face_centre_response[indices, 0]-truth
            rows.append(dict(cells=n, max_abs_error_m=float(np.max(np.abs(error))),
                             rms_error_m=float(np.sqrt(np.mean(error**2)))))
    # Fixed engineering targets before the first run: <1 m absolute error at
    # 256 cells and decreasing RMS over these three meshes. No geological fit.
    assert rows[-1]['max_abs_error_m'] < 1.
    assert rows[2]['rms_error_m'] < rows[1]['rms_error_m'] < rows[0]['rms_error_m']
    return dict(status='PASS', fixed_target_max_error_m=1., coordinates_m=x.tolist(),
                exact_load_boundaries_m=[0., 98000., 100000.], refinements=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): raise FileExistsError('new evidence file required')
    before = sources()
    assert before['docs/W08_REGIMES.md'] == FROZEN_SHA
    started = time.perf_counter()
    with threadpool_limits(limits=1):
        reference = reference_check()
        rows = {'fresh_each_output': [], 'prepared_three_outputs': []}
        signatures = None; peaks = {}
        for repeat in range(3):
            order = (False, True) if repeat % 2 == 0 else (True, False)
            for prepared in order:
                key = 'prepared_three_outputs' if prepared else 'fresh_each_output'
                start = time.perf_counter()
                outputs, peak = run_frames(256, prepared)
                rows[key].append(time.perf_counter()-start)
                peaks[key] = max(peaks.get(key, 0), peak)
                if signatures is None: signatures = outputs
                assert outputs == signatures, 'timed physical outputs/identities differ'
    medians = {key: statistics.median(value) for key, value in rows.items()}
    saved = medians['fresh_each_output']-medians['prepared_three_outputs']
    assert sources() == before, 'source/case/script changed during measurement'
    report = dict(schema='atlas.w08-shortening-check.v1', source_status='WORKING NON-CANON',
        status='PASS', reference=reference, source_sha256=before,
        runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                     platform=platform.system(), native_threads=1),
        timing=dict(scope='three complete 64-parcel to 256-cell shortening/load/support outputs',
                    repeats_s=rows, medians_s=medians, seconds_saved=saved,
                    percent_saved=100.*saved/medians['fresh_each_output'],
                    matched_output_identities=True, peak_accounted_bytes=peaks,
                    excludes='interpreter startup/imports, not setup or verification'),
        scope='selected prescribed dry shortening; not full W08 or whole-generator acceptance',
        elapsed_s=time.perf_counter()-started)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({key: report[key] for key in ('status', 'reference', 'timing', 'elapsed_s')}))


if __name__ == '__main__': main()
