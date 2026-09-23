#!/usr/bin/env python3
"""Same-model thermal support: sampled cell means versus analytic integration."""
import hashlib
import json
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
from atlas_tectonics import (ThermalParameters, PlateCoolingParameters, BoussinesqMaterial,
    ThermalSupportParameters, finite_plate_temperature, thermal_column_response, plate_thermal_response)


def main():
    material = BoussinesqMaterial('benchmark', 'synthetic not calibrated', 3300., 1000., 3.3,
                                 3e-5, 1300., 0., 0., (300., 1300.), .05)
    plate = PlateCoolingParameters(ThermalParameters('benchmark', 'synthetic', 300., 1300., 1e-6), 1e5, 3.3)
    support = ThermalSupportParameters('benchmark-baseline', 'synthetic local compensation',
        'plate-top', 'column-isostasy', 3300., 1000., 10., .1)
    age = np.geomspace(.005, 10., 2048)*1e16
    reference_age = .002*1e16
    edges = np.linspace(0., 1e5, 257)
    # Reuse unchanged reference samples fairly in the sampled-grid control.
    reference = finite_plate_temperature(edges[:-1], reference_age, plate, cell_bottom_m=edges[1:])
    def sampled():
        temperature = finite_plate_temperature(edges[:-1], age[:, None], plate, cell_bottom_m=edges[1:])
        return thermal_column_response(temperature, reference, edges, material, support)
    def integrated():
        return plate_thermal_response(age, reference_age, plate, material, support)
    expected = sampled(); actual = integrated()
    absolute = np.max(abs(expected-actual), axis=0)
    if not np.allclose(expected, actual, rtol=2e-12, atol=1e-8):
        raise ValueError('sampled/integrated model comparison failed')
    timings = {'sampled_256_cells': [], 'whole_column_integral': []}
    for repetition in range(3):
        pair = [('sampled_256_cells', sampled), ('whole_column_integral', integrated)]
        if repetition % 2: pair.reverse()
        for name, run in pair:
            start = time.perf_counter(); run(); timings[name].append(time.perf_counter()-start)
    before = statistics.median(timings['sampled_256_cells'])
    after = statistics.median(timings['whole_column_integral'])
    sources = (ROOT/'src/atlas_tectonics/thermal_support.py', ROOT/'src/atlas_tectonics/plate_integrals.py',
               ROOT/'src/atlas_tectonics/plate_cooling.py', ROOT/'src/atlas_tectonics/constitutive.py',
               ROOT/'src/atlas_tectonics/parameters.py', Path(__file__))
    print(json.dumps(dict(status='PASS_SAME_MODEL', platform=platform.platform(), python=sys.version.split()[0],
        numpy=np.__version__, scipy=scipy.__version__, columns=len(age), reference_cells=256,
        repetitions=3, output_fields=['buoyancy_sheet_kg_m2', 'downward_load_pa', 'downward_displacement_m'],
        max_absolute_difference=absolute.tolist(), timings_seconds=timings,
        median_reference_seconds=before, median_integral_seconds=after, saved_seconds=before-after,
        saved_percent=100*(before-after)/before, speedup=before/after,
        scope='Same constant-property model. Cached reference grid in baseline; no disk cache or JIT warmup in timings. Not whole-generator or external-software timing.',
        source_sha256={path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}), indent=2))


if __name__ == '__main__':
    main()
