"""Tiny explicit engineering hypothesis, not Diadem production or calibration."""
from fractions import Fraction as F
from . import food_accounting as food, multicommodity as transport
from .bindings import SnowPacket, consume_snow_liquid
from .integration import food_delivery_snapshot
from work.generator_upgrade_r1.agroclimate import RootZone, DayForcing, crop_season
from work.generator_upgrade_r1.land_food import LandParcel, WaterPool, option_from_crop_season, allocate_land_food

E='SYNTHETIC TEST: dimensional/conservation oracle, not proposed Diadem parameters'
S='SYNTHETIC TEST'


def inputs(*,capacity=4,loss=F(1,10),town_energy=10000):
    """Two actual crop/food stocks, one shared road, source protection first."""
    snow=SnowPacket('snow-output','single-snow-producer','day-1','two-fields','climate-test',
                    F(1,10),F(1,10),F(1,10),F(1,10),E)
    liquid=consume_snow_liquid(snow,total_precipitation_m3=F(1,5),rain_m3=F(1,10),
        expected_producer_id=snow.producer_id,period_id=snow.period_id,domain_id=snow.domain_id,climate_id=snow.climate_id)
    # Actual water-volume to uniform forcing conversion over 10 m². No routing,
    # snow temperature process or runoff-generation claim is made by this adapter.
    liquid_mm=F(liquid['liquid_input_m3'])*1000/10
    root=RootZone(.3,.1,1,.5,E,S)
    season=crop_season(root,[DayForcing(float(liquid_mm),0,50,0,50)]+[DayForcing(0,0,50,0,50)]*3,
        initial_depletion_mm=0,potential_yield_kg_m2=1,yield_response_factor=1,
        minimum_valid_et_ratio=.5,evidence=E,source_status=S)
    crops=(('grain','field-g',1000),('beans','field-b',2000))
    options=[option_from_crop_season(season_result=season,option_id=c+'-cycle',parcel_id=p,crop_id=c,
        edible_fraction=1,loss_fraction=0,edible_energy_kcal_kg=k,irrigation_efficiency=.5,
        evidence=E,source_status=S,one_crop_season_per_year=True) for c,p,k in crops]
    allocation=allocate_land_food([LandParcel('field-g',(0,0,5,1),'pool',E,S),LandParcel('field-b',(5,0,10,1),'pool',E,S)],
        options,[WaterPool('pool',4,E,S)],frame_id='synthetic-metre-grid',
        annual_energy_kcal_per_person=3000,fixed_population=0)
    if allocation['status']!='OPTIMAL':raise ArithmeticError('reference land allocation failed')
    period=food.Period('annual-reference',1,365,E,S)
    bundle=food.FoodBundle('mixed',tuple(food.FoodComponent(c,F(1,2),k,E) for c,p,k in crops),F(3000,365),E,S)
    obligations=(food.Obligation('farm-eating','farm','mixed','recurring_consumption','per_year','kcal',2000,('eating-claim',),E,S),
                 food.Obligation('farm-reserve','farm','mixed','one_off_reserve','one_off','kcal',1000,('reserve-claim',),E,S),
                 food.Obligation('town-eating','town','mixed','recurring_consumption','per_year','kcal',town_energy,('town-claim',),E,S))
    bindings=tuple(food.HarvestBinding(c+'-cycle',p,c,'farm',c+'-stock',c+'-source',E,E,E,k) for c,p,k in crops)
    policies=(food.LocalPolicy('farm',('recurring_consumption','one_off_reserve'),('farm-eating','farm-reserve'),True,E),
              food.LocalPolicy('town',('recurring_consumption',),('town-eating',),True,E))
    rules=tuple(transport.CommodityRule(c,True,loss,(transport.CapacityUse('shared-road',1,E),),E) for c,p,k in crops)
    kwargs=dict(period=period,day_duration_seconds=86400,day_duration_evidence=E,
        source_id='actual-r1-food-budget',inventory_stocks=(),obligations=obligations,bundles=(bundle,),
        policies=policies,prior_debits=(food.StockDebit('old-paid','grain-stock',F(1,2),'old_commitment',('old-paid-claim',),E),),
        source_ledger_complete=True,nodes=(transport.Node('farm','land',E),transport.Node('town','land',E)),
        commodities=tuple(transport.Commodity(c,'available_edible_kg','kg',E) for c,p,k in crops),
        links=(transport.Link('road','farm','town','TRAVEL',3600,True,rules,period.period_id,E),),
        capacity_groups=(transport.CapacityGroup('shared-road',capacity,period.period_id,E),),
        objective=transport.Objective(transport.OBJECTIVE,'explicit-energy-weighted-example',E),
        demand_weights={(o.obligation_id,c):k for o in obligations for c,p,k in crops},network_complete=True,evidence=E)
    return {'snow_liquid':liquid,'crop_liquid_mm':liquid_mm,'crop_season':season,'land_allocation':allocation},bindings,kwargs


def food_reference(**changes):
    upstream,bindings,kwargs=inputs(**changes)
    result=food_delivery_snapshot(upstream['land_allocation']['food_budget'],bindings,**kwargs)
    return food.exact_json({'upstream':upstream,'delivery':result})
