"""Focused stage-2 index/metric comparison; not a world-performance benchmark.

Run with PYTHONPATH=tectonics/src and native thread limits set before Python starts.
Both point-query paths include validated captures and return identical all-hit rows.
Index setup is measured separately. No speed threshold is used by unit tests.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import time
import tracemalloc

import numpy as np
from atlas_tectonics import (PlanarGeometry,GeometryFeature,GeometryIndex,GeometryLimits,
    SphericalFrame,SphericalChart,SphericalGeometry,geometry_runtime)


def timer(fn):
    t=time.perf_counter();result=fn();return time.perf_counter()-t,result


def main():
    features=[]
    for i in range(200):
        x=(i%20)*3.;y=(i//20)*3.
        g=PlanarGeometry.polygon([[x,y],[x+1,y],[x+1,y+1],[x,y+1]],frame_id='synthetic-map')
        features.append(GeometryFeature(f'f{i:03d}',g))
    centres=np.array([[(i%20)*3+.5,(i//20)*3+.5] for i in range(200)])
    points=np.tile(centres,(10,1))
    def exhaustive():
        rows=[]
        for j,f in enumerate(features):
            ids=np.flatnonzero(f.geometry.classify(points)>=0)
            rows.extend((int(i),j) for i in ids)
        return np.asarray(sorted(rows),dtype=np.int64)
    setup,index=timer(lambda:GeometryIndex(features))
    try:
        expected=exhaustive();assert index.query(points).pairs.tobytes()==expected.tobytes()
        samples={'exhaustive':[],'indexed':[]}
        for rep in range(5):
            operations=[('exhaustive',exhaustive),('indexed',lambda:index.query(points).pairs)]
            if rep%2:operations.reverse()
            for label,fn in operations:
                elapsed,out=timer(fn);assert out.tobytes()==expected.tobytes();samples[label].append(elapsed)
        tracemalloc.start();hits=index.query(points);_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        index_result={'features':len(features),'queries':len(points),'setup_s':setup,
            'median_s':{k:statistics.median(v) for k,v in samples.items()},'samples_s':samples,
            'candidate_pairs':hits.candidate_pairs,'exhaustive_pairs':hits.exhaustive_pairs,
            'output_pairs':len(hits.pairs),'exact_same_hits':True,'tracked_query_peak_bytes':peak,
            'memory_scope':'tracemalloc excludes some native GEOS/index/runtime allocations'}
    finally:index.close()
    sphere=SphericalFrame(2.,'synthetic-sphere');chart=SphericalChart(sphere,(1.,0.,0.))
    arc=SphericalGeometry.polyline([[math.sqrt(.5),-math.sqrt(.5),0],[math.sqrt(.5),math.sqrt(.5),0]],chart=chart)
    angles=np.linspace(0,math.pi/3,2048)
    query=np.column_stack((np.cos(angles),np.zeros(len(angles)),np.sin(angles)))
    first,result=timer(lambda:arc.distance_to(query));expected=2*angles
    np.testing.assert_allclose(result,expected,rtol=1e-12,atol=2e-12)
    metric_times=[timer(lambda:arc.distance_to(query))[0] for _ in range(5)]
    sources={str(p.relative_to(Path(__file__).resolve().parents[1])):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((Path(__file__).resolve().parents[1]/'src').rglob('*.py'))}
    record={'scope':'synthetic stage-2 geometry; no performance thresholds or planetary forecast',
        'runtime':dict(python=platform.python_version(),numpy=np.__version__,platform=platform.system(),**geometry_runtime()),
        'planar_index':index_result,'spherical_distance':{'queries':len(query),'first_use_s':first,
            'warm_median_s':statistics.median(metric_times),'max_abs_error_m':float(np.max(np.abs(result-expected)))},
        'source_sha256':sources}
    print(json.dumps(record,indent=2,allow_nan=False))


if __name__=='__main__':main()
