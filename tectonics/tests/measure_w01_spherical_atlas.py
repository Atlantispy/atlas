"""Bounded stage-3B native-cap versus exhaustive ownership comparison.

One synthetic authored cube partition, no global physical simulation. Both paths
use identical spherical predicates, include query publication, and compare all
reported owners. Tree preparation is separate. No performance threshold in tests.
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.dont_write_bytecode=True
import numpy as np
from atlas_tectonics import build_spherical_atlas
from test_w01_spherical_atlas import cube_tiles, SPHERE


def main():
    start=time.perf_counter();atlas=build_spherical_atlas(SPHERE,*cube_tiles(6));build_s=time.perf_counter()-start
    q=np.random.default_rng(981721).normal(size=(2048,3))
    names=atlas.plate_ids
    def exhaustive():
        rows=[]
        for patch,region in zip(atlas.patches,atlas.regions):
            for i in np.flatnonzero(region.geometry.classify(q)>=0):
                rows.append((int(i),names.index(patch.plate_id)))
        return np.unique(np.asarray(rows,dtype='i8'),axis=0)
    start=time.perf_counter();index=atlas.index();index_s=time.perf_counter()-start
    try:
        reference=exhaustive();first=index.query(q)
        if not np.array_equal(reference,first.pairs):raise AssertionError('membership mismatch')
        durations={'exhaustive':[],'indexed':[]}
        for repetition in range(5):
            for label in (('exhaustive','indexed') if repetition%2==0 else ('indexed','exhaustive')):
                start=time.perf_counter();out=exhaustive() if label=='exhaustive' else index.query(q).pairs
                durations[label].append(time.perf_counter()-start)
                if not np.array_equal(reference,out):raise AssertionError('membership mismatch')
        record={'scope':'static spherical geometry only; warm paired queries, not planet generation',
                'runtime':{'python':platform.python_version(),'numpy':np.__version__,'platform':platform.system()},
                'patches':len(atlas.patches),'points':len(q),'build_seconds':build_s,'index_setup_seconds':index_s,
                'candidate_pairs':first.candidate_pairs,'exhaustive_pairs':first.exhaustive_pairs,
                'all_owner_matches_equal':True,'retained_atlas_bytes_estimate':atlas.retained_bytes_estimate,
                'query_seconds':{name:{'median':statistics.median(times),'samples':times} for name,times in durations.items()},
                'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (ROOT/'src/atlas_tectonics/spherical_atlas.py',Path(__file__))}}
        print(json.dumps(record,indent=2,allow_nan=False))
    finally:index.close()


if __name__=='__main__':main()
