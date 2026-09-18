"""Bounded stage-3 evidence, not a world forecast or a timing-based test gate.

One rational rectangular partition measures preparation separately from repeated
native-batch diagnostics. Comparison uses the existing individual boundary-motion
function and the SAME verified side ownership. No remote calls or persistent data.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import numpy as np
import shapely
from atlas_tectonics import (PlanarGeometry, BoundaryRegion, build_boundary_network,
                            boundary_motion)


def rectangle(x0,y0,x1,y1):
    return PlanarGeometry.polygon([[x0,y0],[x1,y0],[x1,y1],[x0,y1]],frame_id='synthetic-plane')


def main():
    nx,ny=12,8
    regions=tuple(BoundaryRegion(f'{i:02}:{j:02}',f'{i:02}:{j:02}',rectangle(i,j,i+1,j+1))
                  for i in range(nx) for j in range(ny))
    d=rectangle(0,0,nx,ny)
    start=time.perf_counter();network=build_boundary_network(d,regions);build_s=time.perf_counter()-start
    edges=network.interplate_edges;frames=network.frames(edges)
    velocities={r.plate_id:np.array([float(i%7),float(i%5)]) for i,r in enumerate(regions)}
    def batch():return network.motion(velocities,[1.,-2.]).values_m_s[:,:2]
    def individual():
        results=[]
        for row,i in enumerate(edges):
            e=network.edge(i)
            result=boundary_motion(velocities[e.left_plate_id],velocities[e.right_plate_id],frames.tangent[row],[1.,-2.])
            results.append((result.opening_m_s,result.tangential_m_s))
        return np.array(results)
    actual=batch();expected=individual()
    np.testing.assert_allclose(actual,expected,rtol=1e-12,atol=1e-12)
    times={'batch':[],'individual':[]}
    for repeat in range(5):
        for name,fn in ((('batch',batch),('individual',individual)) if repeat%2==0 else (('individual',individual),('batch',batch))):
            start=time.perf_counter();fn();times[name].append(time.perf_counter()-start)
    tracemalloc.start();value=batch();_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    report={
      'scope':'bounded static-geometry/diagnostic comparison; no world or physics acceptance',
      'runtime':{'python':platform.python_version(),'numpy':np.__version__,'shapely':shapely.__version__,
                 'geos':shapely.geos_version_string,'platform':platform.system(),
                 'native_thread_environment':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
      'workload':{'regions':len(regions),'selected_interplate_edges':len(edges),'nx':nx,'ny':ny},
      'build_seconds_single_observation':build_s,
      'construction':network.statistics,
      'retained_network_estimate_bytes':network.retained_bytes_estimate,
      'tracked_batch_peak_bytes':peak,
      'tracked_memory_scope':'tracemalloc allocations only; excludes some native allocations, pre-existing geometry and callers',
      'timings':{k:{'samples_s':v,'median_s':statistics.median(v)} for k,v in times.items()},
      'max_abs_difference_m_s':float(np.max(np.abs(actual-expected))),
      'bit_equal_compared_diagnostics':actual.tobytes()==expected.tobytes(),
      'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in [ROOT/'src/atlas_tectonics/boundaries.py',Path(__file__)]}
    }
    print(json.dumps(report,indent=2,allow_nan=False))

if __name__=='__main__':main()
