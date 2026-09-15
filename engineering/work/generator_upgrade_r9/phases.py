"""Finite same-cohort seasonal accounting from an explicit stock allocation."""
from dataclasses import replace
from fractions import Fraction as F
from . import spatial as s, upstream as u


def run(bundle,recipe,environment,abundance,make_inputs):
    chains={}
    specs=recipe['cohort_chains']
    if type(specs) is not list or len(specs)>64: raise ValueError('bounded explicit cohort chains required')
    for chain in specs:
        u.exact_fields(chain,('chain_id','organism_id','allocation_scenario_id','seasons','evidence','source_status'),'finite cohort chain')
        for key in ('chain_id','organism_id','allocation_scenario_id','evidence'): u.text(chain[key])
        s._source(chain['evidence'],chain['source_status'])
        if chain['chain_id'] in chains: raise ValueError('duplicate cohort chain')
        seasons=chain['seasons']
        if type(seasons) is not list or not 2<=len(seasons)<=25 or any(a==b for a,b in zip(seasons,seasons[1:])): raise ValueError('explicit finite distinct adjacent phases required')
        taxon=recipe['organisms'].get(chain['organism_id'])
        if taxon is None or any(v not in taxon['seasons'] for v in seasons): raise ValueError('unknown cohort organism/season')
        allocation=abundance['alternative_scenarios'].get(chain['allocation_scenario_id'])
        if allocation is None or allocation['mode']!='PRESCRIBED_STOCK' or allocation['organism_id']!=chain['organism_id'] or allocation['season_id']!=seasons[0]: raise ValueError('matching initial prescribed-stock allocation required')
        scenarios={}
        for physical_id,allocated in allocation['physical_scenarios'].items():
            initial=allocated['model']; ctx=initial['context']; endpoints={}
            for bound,label in ((0,'lower_habitat'),(1,'upper_habitat')):
                if not initial['cells'] or initial['total_expected_entities'] is None:
                    endpoints[label]={'status':'UNKNOWN','phases':[],'reason':'initial stock/footprint unresolved'}; continue
                current={k:F(v['committed_expected_entities']['exact']) for k,v in initial['cells'].items()}
                unplaced=F(initial['unplaced_expected_entities']['exact']); total=F(initial['total_expected_entities']['exact'])
                initial_counts=dict(current); phases=[]; failure=None
                for index,(departure,arrival) in enumerate(zip(seasons,seasons[1:])):
                    if taxon['seasons'][departure] is None or taxon['seasons'][arrival] is None:
                        failure='phase biological requirements unknown'; break
                    cs,es,origins,rule,prescribed,h=make_inputs(bundle,recipe,environment,physical_id,chain['organism_id'],departure,bound)
                    ds,de,do,dr,dt,dh=make_inputs(bundle,recipe,environment,physical_id,chain['organism_id'],arrival,bound)
                    if rule.movement_mode!='SEASONAL_MOVEMENT': failure='mobile cohort applicability unresolved or not applicable'; break
                    # The chain explicitly chooses STOCK as its abundance mode.
                    # Habitat/accessibility/movement remain actual; the independent
                    # seasonal logistic/density scenario is not part of this mode.
                    rule=replace(rule,logit_intercept=None,logit_slope=None,conditional_occupied_fraction=None,density_per_occupied_m2=None)
                    dr=replace(dr,logit_intercept=None,logit_slope=None,conditional_occupied_fraction=None,density_per_occupied_m2=None)
                    movement=taxon['seasons'][departure]['movement']
                    if movement['destination_season_id']!=arrival: raise ValueError('cohort transition differs from declared seasonal movement')
                    stock=s.ExplicitStock(chain['organism_id'],ctx['counting_unit'],chain['chain_id'],ctx['spatial_scope_id'],
                        environment['parent_result_sha256'],departure,tuple(current.items()),chain['evidence'],chain['source_status'])
                    requests=tuple(s.MovementRequest(**{**r,'expected_individuals':None if r['expected_individuals'] is None else F(r['expected_individuals'])}) for r in movement['requests'])
                    result=s.route_movements(cs,es,origins,rule,requests,season_id=departure,
                        receiving_capacity={k:None if v is None else F(v) for k,v in movement['receiving_capacity'].items()},
                        evidence=movement['evidence'],source_status=movement['source_status'],destination_cells=ds,destination_edges=de,
                        destination_origins=do,destination_rule=dr,destination_season_id=arrival,declared_departure_stock=stock)
                    phases.append({'index':index,'departure':departure,'arrival':arrival,'result':result})
                    if result['cells'] is None or any(v['final_expected_individuals'] is None for v in result['cells'].values()):
                        failure='phase constraints unresolved; no new stock/placement inferred'; break
                    current={k:F(v['final_expected_individuals']['exact']) for k,v in result['cells'].items()}
                    if sum(current.values(),F())+unplaced!=total: raise ArithmeticError('same-cohort seasonal conservation failure')
                    if result['status'] in ('UNKNOWN','CONFLICT'): failure='arrival persistence or movement unresolved/conflicting; last committed ledger retained, no mortality inferred'; break
                endpoints[label]={'status':'UNKNOWN' if failure else 'INCOMPLETE_UNPLACED' if unplaced else 'MODELLED_CONSERVED_COHORT',
                    'initial_counts':{k:s.quantity(v) for k,v in initial_counts.items()},'final_committed_counts':{k:s.quantity(v) for k,v in current.items()},
                    'unplaced_expected_entities':s.quantity(unplaced),'total_expected_entities':s.quantity(total),
                    'conservation_residual_expected_entities':s.quantity(sum(current.values(),F())+unplaced-total),
                    'completed_phase_count':len(phases) if failure is None else sum(p['result']['status']=='MODELLED_FEASIBLE_ALLOCATION' for p in phases),
                    'phases':phases,'reason':failure}
            scenarios[physical_id]=endpoints
        chains[chain['chain_id']]={'organism_id':chain['organism_id'],'allocation_scenario_id':chain['allocation_scenario_id'],
            'scenarios':scenarios,'source_status':chain['source_status'],'evidence':chain['evidence'],
            'meaning':'same allocated stock across finite phases; resident and unplaced stock retained; no birth/death, immigration or sum of seasonal populations'}
    return chains
