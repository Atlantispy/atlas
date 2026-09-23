"""Bounded W08 full-vector reference and matched-output timing; no plots/runs."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import numpy as np
import scipy
from threadpoolctl import threadpool_limits
from atlas_tectonics.geometry import PlanarGeometry
from atlas_tectonics.materials import MaterialCohort
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.deformation_network import NodalMotionInterval, PreparedDeformationNetwork
from atlas_tectonics.transform import AffineMotionInterval, PreparedAffineMotion, PreparedPlanarMaterials


def hashes():
    paths = sorted((ROOT/'src'/'atlas_tectonics').glob('*.py'))
    paths += [ROOT/'cases'/'w08_transform.json',ROOT/'cases'/'w08_regimes.json',
              ROOT/'docs'/'W08_REGIMES.md',Path(__file__).resolve()]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def network_inputs(n, length=100000.):
    x,y=np.meshgrid(np.linspace(0,length,n+1),np.linspace(0,length,n+1))
    vertices=np.column_stack((x.ravel(),y.ravel())); triangles=[]
    for j in range(n):
        for i in range(n):
            a=j*(n+1)+i; b=a+1; c=a+n+1; d=c+1
            triangles.extend(((a,b,d),(a,d,c)))
    triangles=np.array(triangles,dtype=np.int64)
    px,py=(vertices*np.pi/length).T
    velocity=np.column_stack((.2*vertices[:,1]+.08*length*np.sin(px)*np.sin(py),
                             -.04*vertices[:,0]+.06*length*np.sin(2*px)*np.sin(py)))
    return vertices, triangles, velocity


def reference_check(case):
    rows=[]
    cohorts=(MaterialCohort('a','upper','initial',-10),MaterialCohort('b','lower','initial',None))
    for n in case['distributed_bend_challenge']['spatial_subdivisions_per_axis']:
        vertices,triangles,velocity=network_inputs(n); m=len(triangles)
        budget=WorkBudget(128*1024**2)
        with PreparedDeformationNetwork(vertices,triangles,(NodalMotionInterval(1.,velocity,'smooth-prescribed-bend'),),
            time_s=0,frame_id='synthetic-plane',source_id='challenge-1',triangle_ids=tuple('t'+str(i) for i in range(m)),budget=budget) as motion:
            with PreparedPlanarMaterials(motion,cohorts,np.tile([[10000.],[20000.]],(1,m)),density_kg_m3=[2700.,2850.],
                epoch_id='synthetic-seconds',datum_id='reference-column',source_id='challenge-material',
                specific_enthalpy_j_kg=np.tile([[100.],[-50.]],(1,m)),enthalpy_source='relative-heat') as material:
                result=material.evaluate(1.)
                px,py=(vertices[triangles].mean(axis=1)*np.pi/100000.).T
                ux=.08*np.pi*np.cos(px)*np.sin(py)
                uy=.2+.08*np.pi*np.sin(px)*np.cos(py)
                vx=-.04+.12*np.pi*np.cos(2*px)*np.sin(py)
                vy=.06*np.pi*np.sin(2*px)*np.cos(py)
                exact=(1+ux)*(1+vy)-uy*vx
                error=result.motion.jacobian-exact
                actual_volume=result.thickness_m*np.array([g.area_m2 for g in result.motion.polygons])
                np.testing.assert_allclose(actual_volume,result.volume_m3,rtol=128*np.finfo(float).eps,atol=0)
                if not (result.thickness_m.sum(axis=0).min()<30000<result.thickness_m.sum(axis=0).max()):
                    raise AssertionError('distributed bend must include both thickening and thinning')
                rows.append(dict(subdivisions=n,triangles=m,jacobian_rms_error=float(np.sqrt(np.mean(error**2))),
                    jacobian_max_error=float(np.max(np.abs(error))),jacobian_min=float(result.motion.jacobian.min()),
                    thickness_min_m=float(result.thickness_m.sum(axis=0).min()),
                    thickness_max_m=float(result.thickness_m.sum(axis=0).max()),
                    volume_m3=[math.fsum(row) for row in result.volume_m3],
                    mass_kg=[math.fsum(row) for row in result.mass_kg],
                    enthalpy_j=[math.fsum(row) for row in result.enthalpy_j],
                    peak_accounted_bytes=budget.peak_reserved_bytes))
        del result
    if not all(b['jacobian_rms_error']<a['jacobian_rms_error'] for a,b in zip(rows,rows[1:])):
        raise AssertionError('reference RMS must decrease at every refinement')
    if rows[-1]['jacobian_rms_error']>=case['distributed_bend_challenge']['jacobian_rms_absolute_error_max_finest']:
        raise AssertionError('frozen finest-grid Jacobian accuracy gate failed')
    return dict(status='PASS',refinements=rows)


def rectangle(x,y,dx,dy):
    return PlanarGeometry.polygon([[x,y],[x+dx,y],[x+dx,y+dy],[x,y+dy]],frame_id='timing-plane')


def timing_fixture():
    sources=tuple(rectangle(i*1000.,j*1000.,1000.,1000.) for j in range(8) for i in range(8))
    targets=tuple(rectangle(-2000.+i*1000.,-2000.+j*1000.,1000.,1000.) for j in range(12) for i in range(14))
    return sources,targets


def sequence(sources,targets,mode,times):
    budget=WorkBudget(128*1024**2); output=[]
    def make():
        motion=PreparedAffineMotion(sources,(AffineMotionInterval(1.,[[.02,.15],[-.04,-.03]],[20.,-10.],[0.,0.],'timing-motion'),),
            parcel_ids=tuple('p'+str(i) for i in range(len(sources))),time_s=0,source_id='timing-case',budget=budget)
        material=PreparedPlanarMaterials(motion,(MaterialCohort('a','upper','initial',0),MaterialCohort('b','lower','initial',0)),
            np.tile([[10000.],[20000.]],(1,len(sources))),density_kg_m3=[2700.,2850.],epoch_id='seconds',
            datum_id='reference',source_id='timing-material',specific_enthalpy_j_kg=np.tile([[100.],[-50.]],(1,len(sources))),enthalpy_source='relative')
        return motion,material
    kwargs=dict(target_ids=tuple('r'+str(i) for i in range(len(targets))),exterior_id='outside',source_id='timing-view')
    start=time.perf_counter()
    if mode=='fresh':
        for t in times:
            motion,material=make()
            try: output.append(material.project(t,targets,**kwargs).projection_id)
            finally: material.close(); motion.close()
    else:
        motion,material=make()
        try:
            for t in times: output.append(material.project(t,targets,**kwargs).projection_id)
        finally: material.close(); motion.close()
    return time.perf_counter()-start,output,budget.peak_reserved_bytes


def timings():
    sources,targets=timing_fixture(); results={}
    for label,times in (('three_changing_outputs',(.25,.5,1.)),('three_identical_outputs',(1.,1.,1.))):
        measured={'fresh':[],'prepared':[]}; peaks={}
        for repeat in range(3):
            identities={}
            for mode in (('fresh','prepared') if repeat%2==0 else ('prepared','fresh')):
                elapsed,identities[mode],peak=sequence(sources,targets,mode,times)
                measured[mode].append(elapsed); peaks[mode]=max(peaks.get(mode,0),peak)
            if identities['fresh']!=identities['prepared']: raise AssertionError('matched timing output identities differ')
        medians={k:statistics.median(v) for k,v in measured.items()}
        saved=medians['fresh']-medians['prepared']
        results[label]=dict(repeats_s=measured,medians_s=medians,seconds_saved=saved,
            percent_saved=100*saved/medians['fresh'],matched_output_identities=True,peak_accounted_bytes=peaks)
    return dict(scope='64 material polygons, 168 fixed target polygons, two cohorts',results=results,
                excludes='interpreter startup/imports, not setup/source verification/materialisation/close')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True); args=parser.parse_args()
    if args.output.exists(): raise SystemExit('new evidence path required')
    case=json.loads((ROOT/'cases/w08_transform.json').read_text())
    before=hashes()
    if before['docs/W08_REGIMES.md']!=case['parent_design_sha256']: raise AssertionError('frozen parent design changed')
    start=time.perf_counter()
    with threadpool_limits(limits=1):
        reference=reference_check(case); timing=timings()
    if hashes()!=before: raise AssertionError('source changed during assessment')
    record=dict(schema='atlas.w08-transform-check.v1',source_status='WORKING NON-CANON',status='PASS',
        source_sha256=before,reference=reference,timing=timing,
        runtime=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,platform=platform.system(),native_threads=1),
        elapsed_s=time.perf_counter()-start)
    with args.output.open('x',encoding='utf-8') as stream: json.dump(record,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(status='PASS',reference=reference,timing=timing,elapsed_s=record['elapsed_s']),indent=2))


if __name__=='__main__': main()
