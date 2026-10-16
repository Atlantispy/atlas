"""Run guarded owner arms one at a time (never concurrently), stop on failure.

Usage: python -B run_guarded_arms.py SUFFIX ARM [ARM ...]
ARM is new (Step 8 defaults) | old (every Step 8 switch off) | newv2 (64 KiB
publication bound) | nocomposite | norelease (one captured switch off).
Each arm writes R/probes/step8/owner-guarded-<arm>-<SUFFIX>-<n>; the driver
records exit codes and launch-time free memory in arms-<SUFFIX>.json here.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
STEP8 = R/'probes/step8'
HARNESS = C/'measure_live_owner_guarded.py'
ARMS = {'old': ['--route', 'old'], 'new': [],
        'newv2': ['--set', 'spatial_record_recipes.SMALL_IMPORT_BYTES=65536'],
        'nocomposite': ['--set', 'live_composite.ENABLED=0'],
        'norelease': ['--set', 'live_spatial_patch.EARLY_RELEASE=0'],
        'nostream': ['--set', 'live_spatial_patch.STREAM_CELLS=0'],
        'nomesh': ['--set', 'live_mesh_patch.EARLY_RELEASE=0']}


def main():
    suffix, arms = sys.argv[1], sys.argv[2:]
    if not arms or any(arm not in ARMS for arm in arms):
        raise SystemExit('arms must be one of '+', '.join(ARMS))
    rows, seen = [], {}
    for arm in arms:
        seen[arm] = seen.get(arm, 0)+1
        output = STEP8/('owner-guarded-'+arm+'-'+suffix+'-'+str(seen[arm]))
        row = {'arm': arm, 'output': str(output), 'available_bytes': psutil.virtual_memory().available,
               'started': time.strftime('%Y-%m-%d %H:%M:%S')}
        began = time.perf_counter()
        child = subprocess.run([sys.executable, '-B', str(HARNESS), '--launch', str(output), *ARMS[arm]],
                               check=False, timeout=2400)
        row.update(exit=child.returncode, wall_seconds=round(time.perf_counter()-began, 3))
        rows.append(row)
        (HERE/('arms-'+suffix+'.json')).write_text(json.dumps(rows, indent=1), encoding='utf8')
        print(json.dumps(row), flush=True)
        if child.returncode != 0:
            raise SystemExit('arm failed: '+arm)


if __name__ == '__main__':
    main()
