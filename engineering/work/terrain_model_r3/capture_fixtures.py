"""Preregistered small scenarios; no inferred Diadem coefficients or history."""
import math


def recipe(name,bed,area,shape,water,sediment,outlets,*,settling=0.,steps=1,dt=1.,win=None,sin=None,bin=None):
    n=len(bed)
    return {"schema":"diadem.terrain.capture.recipe.r3","purpose":"SYNTHETIC_ENGINEERING_ONLY",
        "scenario_id":name,"state":{"shape":shape,"cell_area_m2":area,"bedrock_m":bed,"bed_solid_m3":[0.]*n,
            "liquid_m3":water,"suspended_solid_m3":sediment},
        "forcing":{"steps":steps,"dt_years":dt,"outlets":outlets,"connectivity":4,
            "liquid_input_m3_year":win or [0.]*n,"suspended_input_m3_year":sin or [0.]*n,
            "bed_input_solid_m3_year":bin or [0.]*n,"settling_m_year":settling,
            "source_label":"SYNTHETIC prescribed one-class suspended surrogate and explicit carrier; no shoreline erosion"},
        "limits":{"max_product_bytes":16777216,"wall_seconds":120,"checkpoint_steps":10},
        "constraints":[],"physical_acceptance":False,"production_authorised":False}


def suite():
    closed=recipe("closed_column_settling",[0.],[10.],[1,1],[100.],[.1],[],settling=1.,dt=(100.*math.log(2)+.05)/10.)
    overflow=recipe("mixed_phase_overflow",[5.,0.,5.],[10.]*3,[1,3],[0.,99.9,0.],[0.,.1,0.],[0,2])
    tracer=recipe("flowing_pool_tracer",[10.,0.,10.],[10.]*3,[1,3],[0.,100.,0.],[0.]*3,[0,2],
        steps=100,dt=.01,win=[0.,9.99,0.],sin=[0.,.01,0.])
    moving=recipe("bed_only_displacement",[5.,0.,5.],[10.]*3,[1,3],[0.,50.,0.],[0.]*3,[0,2],bin=[0.,1.,0.])
    nested=recipe("unequal_concentrations_nested_pools",[6.,0.,2.,0.,4.,1.,6.],[1.]*7,[1,7],
        [0.,3.,0.,1.,0.,2.,0.],[0.,.03,0.,.002,0.,.01,0.],[0,6],settling=.2,steps=4,dt=.1,
        win=[0.,4.,0.,0.,0.,0.,0.],sin=[0.,.04,0.,0.,0.,0.,0.])
    simultaneous=recipe("simultaneous_sill_phase_spill",[2.,0.,2.,0.,2.],[1.]*5,[1,5],
        [0.,2.97,0.,1.98,0.],[0.,.03,0.,.02,0.],[0,4])
    return [closed,overflow,tracer,moving,nested,simultaneous]
