"""Bounded stage-3C evidence; three declared seeds, no best-case seed selection.

Run with one native-library thread. Areas calibrate the candidate; the Cocos
outline and AF/AN velocities are NOT used by generation. This writes no data
unless the caller supplies an output directory. It is not a geological pass.
"""
from pathlib import Path
import argparse
import json
import math
import platform
import sys
import time
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    from atlas_tectonics import (SphericalFrame,PlanetPartitionSettings,generate_planetary_partition,
        PlateLayoutSettings,generate_plate_layout,layout_metrics,evaluate_plate_kinematics,plate_outline_cycles)
    from atlas_tectonics.plate_reference import (plate_reference_record,reference_area_fractions,
        reference_motion_sample,COCOS_COORDINATES,lonlat_directions,spherical_ring_metrics,outline_reference_record)
    from atlas_tectonics.resources import WorkBudget
    targets=reference_area_fractions(12);sphere=SphericalFrame(6371000.,'comparison-not-Earth-reconstruction')
    rows=[];maps=[]
    for seed in (41,42,43):
        for method in ('voronoi-fixture','connected-reference-candidate'):
            b=WorkBudget(256*1024**2);start=time.perf_counter()
            try:
                world=(generate_planetary_partition(sphere,PlanetPartitionSettings(12,seed),budget=b)
                    if method=='voronoi-fixture' else generate_plate_layout(sphere,PlateLayoutSettings(12,seed,512),budget=b))
            except ValueError as exc:
                rows.append({'seed':seed,'method':method,'accepted':False,'error':str(exc)})
                continue
            seconds=time.perf_counter()-start
            m=layout_metrics(world,budget=b)
            ranked=np.array(m['ranked_area_fractions']);l1=float(np.abs(ranked-targets).sum())
            outlines=[]
            for plate in world.plate_ids:
                try:
                    rings=plate_outline_cycles(world,plate,budget=b)
                    outlines.append({'plate_id':plate,'rings':[spherical_ring_metrics(r,budget=b) for r in rings]})
                except ValueError as exc:
                    outlines.append({'plate_id':plate,'not_measured':str(exc)})
            poles={plate:(np.array([i+1.,-2.,3.])*1e-16) for i,plate in enumerate(world.plate_ids)}
            motion=evaluate_plate_kinematics(world,poles,budget=b)
            rows.append({'seed':seed,'method':method,'accepted':True,'atlas_id':world.atlas_id,
                'generation_seconds':seconds,'peak_accounted_bytes':b.peak_reserved_bytes,
                'area_rank_l1':l1,'metrics':m,'outlines':outlines,
                'kinematic_case':'synthetic prescribed Euler vectors, NOT inferred physical motions',
                'maximum_rigid_plate_area_residual_sr_s':max(abs(v) for v in motion['own_area_rate_sr_s'].values()),
                'geological_validation':False})
            if seed==41:maps.append((method,world))
    refmotion=reference_motion_sample();cocos=spherical_ring_metrics(lonlat_directions(COCOS_COORDINATES))
    result={'schema':'atlas.plate-layout-comparison.v1','scope':'calibration and held-out limited references; no geological acceptance',
        'runtime':{'python':platform.python_version(),'numpy':np.__version__,'platform':platform.system()},
        'seeds':[41,42,43],'plate_count':12,'candidate_support_cells':512,
        'reference':plate_reference_record(),'outline_reference':outline_reference_record(),
        'cocos_metrics':cocos,'sampled_motion_columns':['calculated_opening','calculated_right_lateral','published_opening','published_right_lateral'],
        'sampled_motion_unit':'mm per Julian year','sampled_motion_rows':refmotion.tolist(),
        'motion_max_abs_difference_mm_a':float(abs(refmotion[:,:2]-refmotion[:,2:]).max()),
        'results':rows,
        'unresolved':['not all 52 full plate outlines compared','no validated boundary-type/shape generative law',
            'support discretisation remains a generating prior','no force-derived or evolving global plate motion',
            'small-plate resolution can cause explicit refusal','Windows not tested']}
    (a.output/'plate-layout-comparisons.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    # Optional Matplotlib diagnostics show the ACTUAL model arcs, never an artistic
    # image of intended output. Plotting is not a dependency of the core package.
    try:
        import matplotlib;matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
        for method,world in maps:
            pieces=[]
            for edge in world.interplate_edges:
                v,w=world.vertex_directions[world.edge_vertices[edge]]
                theta=math.atan2(np.linalg.norm(np.cross(v,w)),v@w)
                t=np.linspace(0,1,max(2,int(math.ceil(theta/.01))))
                q=(np.sin((1-t)*theta)[:,None]*v+np.sin(t*theta)[:,None]*w)/math.sin(theta)
                ll=np.rad2deg(np.column_stack((np.arctan2(q[:,1],q[:,0]),np.arcsin(np.clip(q[:,2],-1,1)))))
                cuts=np.flatnonzero(abs(np.diff(ll[:,0]))>180)+1
                pieces.extend(part for part in np.split(ll,cuts) if len(part)>1)
            fig,ax=plt.subplots(figsize=(11,5.5));ax.add_collection(LineCollection(pieces,linewidths=.8))
            ax.set(xlim=(-180,180),ylim=(-90,90),xlabel='Longitude (degrees)',ylabel='Latitude (degrees)',
                   title=f'{method}: 12 plates, seed 41\nActual great-circle boundaries; no geological acceptance')
            ax.grid(True,alpha=.25);fig.tight_layout();fig.savefig(a.output/(method+'.png'),dpi=150);plt.close(fig)
        fig,ax=plt.subplots(figsize=(8,5))
        ax.semilogy(np.arange(1,13),targets,marker='o',label='PB2002 largest 12, renormalised (calibration target)')
        for row in rows:
            if row['seed']==41 and row['accepted']:
                ax.semilogy(np.arange(1,13),row['metrics']['ranked_area_fractions'],marker='.',label=row['method'])
        ax.set(xlabel='Area rank',ylabel='Fraction of planetary surface',title='Area fit is calibration, not shape validation')
        ax.legend(fontsize=8);fig.tight_layout();fig.savefig(a.output/'area-spectrum.png',dpi=150);plt.close(fig)
    except ImportError:
        (a.output/'plotting-unavailable.txt').write_text('Optional Matplotlib not present; numerical evidence still written.\n')
    print(json.dumps({'rows':len(rows),'accepted_candidates':sum(r['accepted'] and r['method'].endswith('candidate') for r in rows),
                      'motion_max_abs_difference_mm_a':result['motion_max_abs_difference_mm_a']}))


if __name__=='__main__':main()
