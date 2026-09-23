#!/usr/bin/env python3
"""Bounded same-equation timing, not a historical or whole-generator speed claim."""
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time

for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS'):
    os.environ.setdefault(key, '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import numpy as np
import scipy
from atlas_tectonics import ThermalParameters, PlateCoolingParameters, finite_plate_temperature


def main():
    p = PlateCoolingParameters(ThermalParameters('benchmark', 'synthetic dimensionless SI fixture', 0., 1., 1.), 1., 1.)
    x = np.linspace(0, 1, 256)[None, :]
    ages = np.geomspace(.005, 10., 1024)[:, None]
    edges = np.linspace(0, 1, 257)
    top = edges[:-1][None, :]; bottom = edges[1:][None, :]
    def textbook(cells=False):
        positions = .5*(top+bottom) if cells else x
        result = np.broadcast_to(positions, (len(ages), positions.shape[1])).copy()
        for n in range(1, 101):
            term = 2/(n*math.pi)*np.sin(n*math.pi*positions)*np.exp(-n*n*math.pi**2*ages)
            if cells:
                term *= np.sinc(n*.5*(bottom-top))
            result += term
        if not cells:
            result[:, 0] = 0.; result[:, -1] = 1.
        return result
    def candidate(cells=False):
        return finite_plate_temperature(top if cells else x, ages, p, cell_bottom_m=bottom if cells else None)
    # Warm imports/allocators; three bounded paired repetitions, no timing gate.
    results = {}
    for cells in (False, True):
        expected = textbook(cells); actual = candidate(cells)
        error = float(np.max(abs(actual-expected)))
        if error > 3e-14:
            raise ValueError('same-equation comparison failed')
        timings = {'textbook_100_mode_vectorised': [], 'dual_series_batched': []}
        for _ in range(3):
            for key, run in (('textbook_100_mode_vectorised', textbook), ('dual_series_batched', candidate)):
                start = time.perf_counter(); run(cells); timings[key].append(time.perf_counter()-start)
        before = statistics.median(timings['textbook_100_mode_vectorised'])
        after = statistics.median(timings['dual_series_batched'])
        results['cell_means' if cells else 'points'] = dict(max_normalised_temperature_difference=error,
            timings_seconds=timings, median_reference_seconds=before, median_candidate_seconds=after,
            saved_seconds=before-after, saved_percent=100*(before-after)/before, speedup=before/after)
    print(json.dumps(dict(status='PASS_SAME_EQUATION', python=sys.version.split()[0], platform=platform.platform(),
        numpy=np.__version__, scipy=scipy.__version__, samples=int(actual.size), input_shape=list(actual.shape),
        repetitions=3, results=results,
        scope='Synthetic 1D constant-property plate; not ASPECT/GWB runtime or whole-generator speedup. Neither implementation is timestep marching.',
        source_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (ROOT/'src/atlas_tectonics/plate_cooling.py', ROOT/'src/atlas_tectonics/parameters.py', Path(__file__))}), indent=2))


if __name__ == '__main__':
    main()
