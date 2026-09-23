#!/usr/bin/env python3
"""Matched exact cell-load summation: direct linear convolution versus shared FFT.

Both return w and three derivatives on every face/centre. This compares candidate
algorithms for the new finite-region kernel, not a previously shipped workflow.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS'):
    os.environ.setdefault(key,'1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src')]
import numpy as np
from atlas_tectonics import FlexureParameters, RegionalGrid1D, FlexureBoundary1D, FiniteRegionFlexure
from atlas_tectonics._validation import read_array, frozen
from atlas_tectonics.finite_flexure import _integrated_kernel
from atlas_tectonics.resources import select_budget


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    n, repeats, calls = 2048, 3, 12
    grid = RegionalGrid1D(n, 400000.)
    params = FlexureParameters('benchmark-uniform', 'synthetic timing fixture, not Earth calibration',
                               7e10,10000.,.25,3300.,10.)
    boundary = FlexureBoundary1D('continuous','continuous','explicit continuing uniform plate')
    start = time.perf_counter()
    plan = FiniteRegionFlexure(grid,params,boundary)
    fft_setup_s = time.perf_counter()-start
    start = time.perf_counter()
    # Give the direct baseline the same reusable cell-integrated Green kernel;
    # neither method recomputes integrals once per source load or per snapshot.
    kernel = _integrated_kernel(np.arange(-2*n,2*n+1)*(grid.spacing_m/2),grid.spacing_m,plan.alpha_m)
    kernel /= params.restoring_pa_per_m
    direct_setup_s = time.perf_counter()-start
    rng = np.random.default_rng(9341)
    load = np.r_[rng.uniform(-10000.,10000.,n),0.,0.]
    def direct():
        with select_budget(None).reserve(plan.work_bytes((n+2,))):
            captured = read_array(load,'regional load',ndim=1)
            sparse = np.zeros(2*n+1); sparse[1::2] = captured[:-2]
            result = np.column_stack([np.convolve(sparse,kernel[:,d])[2*n:4*n+1] for d in range(4)])
            for d in range(1,4):
                for _ in range(d): result[:,d] /= plan.alpha_m
            return frozen(result)
    def fft():
        return plan.solve(load)
    expected, actual = direct(), fft()
    scale = np.max(np.abs(expected),axis=0)
    error = np.max(np.abs(expected-actual),axis=0)
    if np.any(error > 5e-13*scale):
        raise ValueError('linear FFT exceeds the predeclared direct-sum comparison tolerance')
    times = {'direct_cell_superposition':[], 'prepared_linear_fft':[]}
    for repeat in range(repeats):
        order = [('direct_cell_superposition',direct),('prepared_linear_fft',fft)]
        if repeat%2: order.reverse()
        for name, run in order:
            start = time.perf_counter()
            for _ in range(calls): result = run()
            elapsed = time.perf_counter()-start
            if np.any(np.max(np.abs(result-expected),axis=0) > 5e-13*scale):
                raise ValueError('timed response exceeds the unchanged direct-sum comparison tolerance')
            times[name].append(elapsed)
    before, after = [statistics.median(times[k]) for k in times]
    paths = [ROOT/'src/atlas_tectonics/finite_flexure.py',Path(__file__)]
    record = dict(status='PASS_MATCHED_CELL_LOADS_AND_ALL_DERIVATIVES',cells=n,length_m=grid.length_m,
        calls_per_repeat=calls,repetitions=repeats,python=sys.version.split()[0],numpy=np.__version__,
        platform=platform.platform(),timings_seconds=times,
        median_direct_seconds=before,median_fft_seconds=after,saved_seconds=before-after,
        saved_percent=100*(before-after)/before,speedup=before/after,
        per_solve_direct_seconds=before/calls,per_solve_fft_seconds=after/calls,
        direct_setup_seconds=direct_setup_s,fft_setup_seconds=fft_setup_s,
        prepared_fft_storage_bytes=plan.setup_bytes,maximum_absolute_error=error.tolist(),
        comparison_tolerance='max abs error per derivative <= 5e-13 * that derivative max abs direct response',
        scope='New uniform finite-region kernel only; identical cell pressures and face/centre w,w1,w2,w3. Precomputed integrated kernel for both. Explicit zero far-field changes. Input validation, memory admission and immutable output included. No cache hits/workers, no W03 evolution/source checks or full terrain. Not an old-release or whole-generator speed claim.',
        source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    payload = json.dumps(record,indent=2);print(payload)
    if args.output: args.output.write_text(payload+'\n',encoding='utf-8')


if __name__ == '__main__': main()
