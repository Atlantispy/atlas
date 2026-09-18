#!/usr/bin/env python3
"""Build and verify the declared R2 static example offline, not a simulation.

No reference acquisition, dependency installation, checkpoint migration, Git/PC
write or implicit persistent output. --save-store explicitly publishes a new
self-contained local ArrayStore. Geometries/temperatures/history below are authored
case inputs, not measured mantle laws or a tectonic equilibrium claim.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'))


def build_example(*,budget=None,cancel=None):
    """Reuse the existing source catalogue; do not type mineral constants per cell."""
    from atlas_tectonics import (earth_material_library, GeologySource, MaterialCohort, CohortDescription,
        LayerComponent, GeologicalLayer, ColumnDescription, ThermalInitialProfile, GeologicalProvince,
        SurfaceSelector, FeaturePrecedence, FeatureGeometry, GeologicalDomain, GeologicalCase,
        PlanarGeometry, PrecursorState, InputOrigin, CoolingHistory)
    from atlas_tectonics.timebase import JULIAN_MEGAYEAR
    path=ROOT/'cases'/'precursor_r2.json'
    if path.is_symlink(): raise ValueError('linked case definitions are refused')
    raw=path.read_bytes();spec=json.loads(raw);x=spec['example']
    if spec['schema']!='atlas.precursor-r2-case.v1': raise ValueError('unsupported example case')
    case_hash=hashlib.sha256(raw).hexdigest()
    origin=GeologySource('example','authored',x['meaning'],content_sha256=case_hash)
    def rect(a,b):
        return PlanarGeometry.polygon([(a,0.),(b,0.),(b,x['height_m']),(a,x['height_m'])],frame_id=x['frame_id'],budget=budget)
    domain=GeologicalDomain(rect(0.,x['width_m']),'example')
    lib=earth_material_library()
    definitions,sources=lib.definitions(tuple(x[k] for k in ('continental_profile','oceanic_profile','mantle_profile')),
                                       reference_temperature_k=x['reference_property_temperature_k'])
    cohorts=tuple(CohortDescription(MaterialCohort(k,x[k+'_profile'],x['identity']+'/'+k,
        x['formation_time_megayears'][k]*JULIAN_MEGAYEAR.seconds_per_unit),'example') for k in ('continental','oceanic','mantle'))
    def layer(name,role,thickness,cohort):
        return GeologicalLayer(name,role,thickness,(LayerComponent(cohort,1.),),x['additional_explicit_porosity'],'example')
    columns=[]
    for name in ('continental','oceanic'):
        crust=x[name+'_crust_m'];total=x['lithosphere_thickness_m']
        columns.append(ColumnDescription(name,name,(layer(name+'-crust','crust',crust,name),
            layer(name+'-mantle','lithospheric_mantle',total-crust,'mantle')),total,'authored-geotherm','example'))
    thermal=ThermalInitialProfile('authored-geotherm','example','tabulated',depths_m=(0.,x['lithosphere_thickness_m']),
        temperatures_k=(x['surface_temperature_k'],x['base_temperature_k']))
    c=GeologicalCase(x['identity'],domain,time_s=0.,epoch_id=x['epoch_id'],depth_reference_id=x['depth_reference_id'],source_id='example',
        sources=(origin,*sources),materials=definitions,cohorts=cohorts,thermal_profiles=(thermal,),columns=tuple(columns),
        provinces=(GeologicalProvince('continent','continental',SurfaceSelector('domain'),'example'),
                   GeologicalProvince('ocean','oceanic',SurfaceSelector('geometry',('ocean-outline',)),'example')),
        geometries=(FeatureGeometry('ocean-outline',rect(0.,x['ocean_width_m']),'example'),),
        precedence=FeaturePrecedence(('ocean','continent')),budget=budget,cancel=cancel)
    inputs=(InputOrigin('example','authored',case_hash),*(InputOrigin(s.source_id,'observed',s.content_sha256) for s in sources))
    return PrecursorState(c,origins=inputs,cooling_history=(CoolingHistory('authored-geotherm','example',
        x['cooling_time_megayears']*JULIAN_MEGAYEAR.seconds_per_unit),),library=lib,budget=budget,cancel=cancel)


def main(argv=None):
    from atlas_tectonics import PreparedPrecursor, InitialSamplingCell, save_precursor_state,save_initial_samples
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore,StoreLimits
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save-store',type=Path,help='explicitly create a new local store; existing destinations are refused')
    args=parser.parse_args(argv)
    # Apply the established source/bytecode verification policy before importing
    # scientific fixtures. No clean-up is performed on an existing workspace.
    sys.path.insert(0,str(ROOT))
    from verify import source_inventory
    before=source_inventory(ROOT)
    budget=WorkBudget(128<<20);state=build_example(budget=budget)
    c=state.case;request=dict(frame_id=c.topology.frame_id,epoch_id=c.epoch_id,depth_reference_id=c.depth_reference_id)
    with PreparedPrecursor(state,budget=budget) as plan:
        cells=plan.sample_cells((InitialSamplingCell('whole-example',c.topology.domain,0.,c.columns[0].lithosphere_thickness_m),),**request)
    stored=False
    if args.save_store is not None:
        # ArrayStore rejects linked/unsafe filesystem paths. Exclusive reservation
        # prevents overwriting an existing database, even across racing creators.
        import os
        fd=os.open(args.save_store,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with ArrayStore(args.save_store,StoreLimits(4096,16<<20,64<<20),budget=budget) as store:
            # One complete result snapshot already includes the state/library.
            save_initial_samples(cells,store,budget=budget)
        stored=True
    after=source_inventory(ROOT)
    if after!=before: raise ValueError('source changed during example construction')
    print(json.dumps({'schema':'atlas.precursor-r2-example-result.v1','status':'PASS_STATIC_EXAMPLE_ONLY',
        'state_id':state.state_id,'sample_id':cells.sample_id,'case_definition_id':c.definition_id,
        'material_library_id':state.library.library_id,'source_sha256':before,
        'cell_volume_m3':cells.array('cell_volume_m3').tolist(),
        'volume_by_cohort_m3':{name:float(cells.array('phase_volume_m3')[cells.array('phase_cohort_code')==i].sum())
                              for i,name in enumerate(cells.descriptor()['cohort_ids'])},
        'mean_initial_temperature_k':cells.temperature().tolist(),
        'true_solid_volume_known':bool(cells.array('solid_volume_known').all()),
        'unresolved_initial_state':state.unresolved_initial_state,'store_written':stored,
        'work_budget':budget.statistics(),'physical_validation':False,'rheology_or_evolution_run':False},indent=2,allow_nan=False))
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except (OSError,ValueError,ImportError) as exc:
        print(json.dumps({'status':'BLOCKED_PRECURSOR_EXAMPLE','error':str(exc)}),file=sys.stderr)
        raise SystemExit(2)
