"""Explicit bounded R4 recipes; no physical or production authority."""
from copy import deepcopy
from r3_bindings import bound_module,capture

_previous=bound_module('capture_fixtures',{'capture':capture})


def split_recipe(which=1):
    bed=[0.,1.9999,1.] if which==1 else [0.,1.9999,1.,1.99995,.5]
    water,solid=(2.9991,.001) if which==1 else (4.49865,.0015)
    depths=[2.-z for z in bed];volume=water+solid
    base=deepcopy(_previous.suite()[0]);n=len(bed)
    base.update(schema='diadem.terrain.capture.recipe.r4',scenario_id='single_drying_split' if which==1 else 'nested_drying_splits')
    base['state']=capture.CaptureState([1,n],[1.]*n,bed,[0.]*n,
        [water*d/volume for d in depths],[solid*d/volume for d in depths]).as_dict()
    base['forcing'].update(steps=1,dt_years=.8,outlets=[],connectivity=4,
        liquid_input_m3_year=[0.]*n,suspended_input_m3_year=[0.]*n,bed_input_solid_m3_year=[0.]*n,
        settling_m_year=1.,source_label='SYNTHETIC closed-pool split with one-class suspended mineral surrogate')
    base['limits']['checkpoint_steps']=1
    return base


def suite():
    # Exact-sill compound throughflow from old R3 is separately retained as a
    # rejected R4 closure test, not disguised as a successful repeated recipe.
    recipes=[deepcopy(r) for r in _previous.suite() if r['scenario_id']!='simultaneous_sill_phase_spill']
    for row in recipes:row['schema']='diadem.terrain.capture.recipe.r4'
    recipes.extend([split_recipe(1),split_recipe(2)])
    equal=deepcopy(split_recipe(1));equal['scenario_id']='no_zero_head_remixing'
    # Exactly full in binary64 arithmetic as well as decimal notation. The
    # former decimal pair1.8+.2 lies slightly ABOVE2 as exact binary operands;
    # it is retained separately as an unrepresentable-head rejection fixture.
    equal['state']=capture.CaptureState([1,3],[1.]*3,[0.,2.,0.],[0.]*3,[1.75,0.,1.875],[.25,0.,.125]).as_dict()
    equal['forcing'].update(steps=2,dt_years=.1,settling_m_year=0.)
    recipes.append(equal)
    rejoin=deepcopy(equal);rejoin['scenario_id']='positive_head_rejoining'
    rejoin['forcing'].update(steps=1,dt_years=.1,liquid_input_m3_year=[1.,0.,0.])
    recipes.append(rejoin)
    return recipes


def unrepresentable_head_recipe():
    recipe=deepcopy(suite()[-2]);recipe['scenario_id']='unrepresentable_positive_saddle_head_REJECTION'
    recipe['state']=capture.CaptureState([1,3],[1.]*3,[0.,2.,0.],[0.]*3,[1.8,0.,1.98],[.2,0.,.02]).as_dict()
    return recipe
