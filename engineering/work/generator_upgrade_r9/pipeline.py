"""R8 physical evidence to explicit species spatial snapshot hypotheses."""
from fractions import Fraction as F
from copy import deepcopy
import hashlib
from . import binding, upstream, spatial, sources, owner_inputs, stock, phases

FIELDS=('schema','source_status','source_sha256','evidence','parent_recipe','seasons',
        'organisms','placement_seed','actual_occurrence_overlays','abundance_scenarios','cohort_chains','limits')


def quantity(value):
    if value is None: return None
    if type(value) not in (str,int,float,F) or type(value) is str and (not value or len(value)>256):
        raise ValueError('explicit bounded rational quantity required, not boolean')
    return F(value)


def parse(bundle,recipe):
    recipe=bundle.storage.decoded(bundle.storage.encoded(recipe)); upstream.exact_fields(recipe,FIELDS,'R9 recipe')
    if recipe['schema']!=binding.RECIPE_SCHEMA or recipe['source_sha256']!=bundle.source_sha256 or recipe['source_status']!='WORKING NON-CANON':
        raise ValueError('this exact source-bound R9 recipe required')
    for key in ('evidence','placement_seed','limits'): upstream.text(recipe[key])
    upstream.validate_seasons(recipe['seasons']); season_ids={s['season_id'] for s in recipe['seasons']}
    taxa=recipe['organisms']
    if type(taxa) is not dict or not 1<=len(taxa)<=256: raise ValueError('bounded explicit organism roster required')
    roster={r['hs']:r for r in sources.retained_roster()['organisms']}
    biological=owner_inputs.biological_roster()
    seen_hs=set()
    for ident,taxon in taxa.items():
        upstream.text(ident)
        upstream.exact_fields(taxon,('name','kind','retained_hs','applicability','evidence','source_status','seasons'),'organism')
        upstream.text(taxon['name']); upstream.text(taxon['evidence'])
        if taxon['source_status'] not in spatial.KNOWN|spatial.UNKNOWN or taxon['kind'] not in ('PLANT','ANIMAL','OTHER','UNKNOWN'):
            raise ValueError('explicit organism status/kind required')
        hs=taxon['retained_hs']
        if hs is not None:
            if type(hs) is not int or hs not in roster or taxon['name']!=roster[hs]['species']: raise ValueError('retained organism identity differs')
            if hs in seen_hs: raise ValueError('duplicate retained organism identity')
            seen_hs.add(hs)
            expected='NONSPATIAL_EVENT' if hs==14 else 'ABSENT_WILD' if hs==19 else 'SPATIAL'
            if taxon['applicability']!=expected: raise ValueError('retained organism exceptional semantics differ')
        elif ident not in biological and taxon['source_status']!='SYNTHETIC TEST':
            raise ValueError('new biological roster entries need a bound source, not anonymous working defaults')
        if ident in biological:
            actual=biological[ident]
            if (taxon['name'],taxon['kind'],hs)!=(actual['name'],actual['kind'],actual['retained_hs']): raise ValueError('owner-bound biological identity differs')
        elif hs is not None:
            raise ValueError('retained taxon requires its stable owner identity')
        if taxon['applicability'] not in ('SPATIAL','NONSPATIAL_EVENT','ABSENT_WILD'): raise ValueError('explicit product applicability required')
        if type(taxon['seasons']) is not dict or set(taxon['seasons'])!=season_ids: raise ValueError('every requested season requires a product or explicit unknown')
        for sid,season in taxon['seasons'].items():
            if season is None: continue
            upstream.exact_fields(season,('requirements','habitat_operator','allowed_domains','rule','cells','origins','edges','prescribed_total','movement'),'organism season')
            if type(season['allowed_domains']) is not list or not season['allowed_domains'] or len(set(season['allowed_domains']))!=len(season['allowed_domains']) or not set(season['allowed_domains'])<={'LAND','SEA','CONFIRMED_OPEN_WATER'}:
                raise ValueError('explicit independent allowed habitat domains required')
            if season['rule']['species_id']!=ident: raise ValueError('spatial rule organism identity mismatch')
            if hs==4 and season['rule']['movement_mode']!='NONMOVING': raise ValueError('HS4 rooted adult movement must remain not applicable; dispersal is separate')
    if type(recipe['actual_occurrence_overlays']) is not list or len(recipe['actual_occurrence_overlays'])>1000: raise ValueError('bounded separate occurrence overlays required')
    seen=set()
    for overlay in recipe['actual_occurrence_overlays']:
        upstream.exact_fields(overlay,('overlay_id','organism_id','cell_id','evidence','source_status'),'separate occurrence evidence')
        for key in ('overlay_id','organism_id','cell_id','evidence'): upstream.text(overlay[key])
        if overlay['overlay_id'] in seen or overlay['organism_id'] not in taxa or overlay['source_status'] not in spatial.KNOWN|spatial.UNKNOWN: raise ValueError('invalid separate occurrence overlay')
        seen.add(overlay['overlay_id'])
    if type(recipe['abundance_scenarios']) is not list or len(recipe['abundance_scenarios'])>128: raise ValueError('bounded explicit abundance scenarios required')
    seen=set()
    for scenario in recipe['abundance_scenarios']:
        upstream.exact_fields(scenario,('scenario_id','organism_id','physical_scenario_id','season_id','mode','model'),'abundance scenario')
        for key in ('scenario_id','organism_id','physical_scenario_id','season_id'): upstream.text(scenario[key])
        if scenario['scenario_id'] in seen or scenario['organism_id'] not in taxa or scenario['season_id'] not in season_ids or scenario['mode'] not in ('DECLARED_DENSITY','PRESCRIBED_STOCK'):
            raise ValueError('explicit unique abundance scenario identity required')
        seen.add(scenario['scenario_id'])
        context=scenario['model']['context']
        if context['species_id']!=scenario['organism_id'] or context['snapshot_id']!=upstream.digest(recipe['parent_recipe']): raise ValueError('abundance physical recipe/organism binding differs')
        if taxa[scenario['organism_id']]['source_status']!='SYNTHETIC TEST':
            if context['source_status']!='WORKING NON-CANON': raise ValueError('new numerical biological scenarios remain working hypotheses')
            population=biological[scenario['organism_id']]['population_reference']
            if population is not None and context['counting_unit']!=population['counted_entity']: raise ValueError('biological counting unit differs from owner contract')
            if scenario['mode']=='PRESCRIBED_STOCK':
                if population is None:
                    if scenario['model']['total_expected_entities'] is not None: raise ValueError('plant stock remains UNKNOWN without its owner input')
                elif (scenario['model']['total_expected_entities'],context['spatial_scope_id'],context['time_basis'])!=(population['working_total'],population['scope'],population['temporal_basis']):
                    raise ValueError('prescribed stock must retain owner total, census scope and temporal meaning')
            if taxa[scenario['organism_id']]['applicability']!='SPATIAL': raise ValueError('exceptional organism cannot receive ordinary spatial abundance generation')
    return recipe


def rule_model(spec):
    converted=dict(spec)
    for key in ('conditional_occupied_fraction','density_per_occupied_m2','travel_budget'):
        converted[key]=quantity(converted[key])
    return spatial.SpeciesRule(**converted)


def inputs(bundle,recipe,environment,scenario_id,organism_id,season_id,bound):
    taxon=recipe['organisms'][organism_id]; spec=taxon['seasons'][season_id]
    source=environment['scenarios'][scenario_id]['seasons'][season_id]['cells']
    rule=rule_model(spec['rule']); cells=[]; habitat={}
    if type(spec['cells']) is not dict or set(spec['cells'])!=set(source): raise ValueError('complete species physical-cell context required')
    for ident,physical in sorted(source.items()):
        extra=upstream.exact_fields(spec['cells'][ident],('habitat_fraction','traversable','evidence','source_status'),'occupied-habitat context')
        if physical['domain']['kind'] not in spec['allowed_domains'] and physical['domain']['kind']!='UNKNOWN' and physical['domain']['source_status'] not in ('UNKNOWN','INCOMPLETE','CONFLICT'):
            h={'status':'EXCLUDED_DOMAIN','support':0.,'interval':[0.,0.],'factors':[],'reason':'explicit species/domain exclusion'}
            fraction=F(); traversable=False
        else:
            h=upstream.habitat(physical,spec['requirements'],spec['habitat_operator'])
            fraction=quantity(extra['habitat_fraction']); traversable=extra['traversable']
        habitat[ident]=h
        support=None if h['interval'] is None else h['interval'][bound]
        cells.append(spatial.Cell(ident,F(physical['area_m2']),support,fraction,traversable,
            extra['evidence']+'; actual physical projection '+upstream.digest(physical),extra['source_status']))
    # Every model edge must bind a declared actual parent adjacency and its length.
    parent_edges=recipe['parent_recipe']['edges']; adjacency={frozenset((e['a'],e['b'])):e for e in parent_edges}
    if type(spec['edges']) is not list or len(spec['edges'])>4096: raise ValueError('bounded directed species graph required')
    edges=[]
    for edge in spec['edges']:
        upstream.exact_fields(edge,('edge_id','source','target','cost_per_m','enabled','capacity_expected_individuals','evidence','source_status'),'species edge')
        key=frozenset((edge['source'],edge['target']))
        if key not in adjacency: raise ValueError('species corridor not on declared physical adjacency')
        cost=None if edge['cost_per_m'] is None else quantity(edge['cost_per_m'])*F(adjacency[key]['length_m'])
        edges.append(spatial.Edge(edge['edge_id'],edge['source'],edge['target'],cost,edge['enabled'],quantity(edge['capacity_expected_individuals']),
            edge['evidence']+'; physical adjacency '+upstream.digest(adjacency[key]),edge['source_status']))
    origins=None if spec['origins'] is None else tuple(spatial.Origin(**v) for v in spec['origins'])
    if spec['prescribed_total'] is not None:
        upstream.exact_fields(spec['prescribed_total'],('expected_individuals','evidence','source_status'),'prescribed total')
    total=None if spec['prescribed_total'] is None else spatial.PrescribedTotal(quantity(spec['prescribed_total']['expected_individuals']),spec['prescribed_total']['evidence'],spec['prescribed_total']['source_status'])
    return tuple(cells),tuple(edges),origins,rule,total,habitat


def placements(recipe,organism_id,season_id,lower,upper):
    """One explicit seeded occupancy hypothesis, never labelled observation.

    Common random numbers across physical/numerical scenarios preserve their
    sensitivity comparison. Season ID is included: no unrequested persistence
    or migration history is inferred from these independent snapshot draws.
    """
    result={}
    for ident,a in lower['cells'].items():
        b=upper['cells'][ident]
        binding={'seed':recipe['placement_seed'],'organism':organism_id,'season':season_id,'cell':ident}
        raw=hashlib.sha256(upstream.digest(binding).encode()).digest()
        u=F(int.from_bytes(raw[:8],'big')>>11,2**53)
        probs=[a['occupancy_probability'],b['occupancy_probability']]
        bounds=None if any(p is None for p in probs) else [min(probs),max(probs)]
        present=None if bounds is None or F(bounds[0])<=u<F(bounds[1]) else u<F(bounds[0])
        areas=[r['expected_occupied_area_m2'] for r in (a,b)]; counts=[r['expected_individuals'] for r in (a,b)]
        def interval(values):
            return None if any(v is None for v in values) else [str(min(F(v['exact']) for v in values)),str(max(F(v['exact']) for v in values))]
        result[ident]={'modelled_presence':present,'status':'UNKNOWN' if present is None else 'MODELLED_SNAPSHOT_DRAW',
            'occupancy_probability_interval':bounds,'expected_occupied_area_m2_interval':interval(areas),
            'expected_individuals_interval':interval(counts),'draw_uniform_exact':str(u),'draw_binding_sha256':upstream.digest(binding),
            'observed_presence':None,'meaning':'explicit conditional modelled occupancy draw at source-cell support; not observed occurrence, a realised census, or a temporal movement solution'}
    return result


def evaluate_unit(bundle,recipe,environment,scenario_id,organism_id,season_id):
    taxon=recipe['organisms'][organism_id]
    if taxon['applicability']!='SPATIAL':
        absent=taxon['applicability']=='ABSENT_WILD'
        return {'status':'NOT_APPLICABLE','organism_id':organism_id,'season_id':season_id,
            'applicability':taxon['applicability'],'reason':taxon['evidence'],
            'wild_expected_individuals':'0' if absent else None,'cells':None,'movement':None,
            'source_status':taxon['source_status']}
    spec=taxon['seasons'][season_id]
    if spec is None:
        return {'status':'INCOMPLETE_BIOLOGICAL_RULES','organism_id':organism_id,'season_id':season_id,
            'cells':None,'movement':None,'missing':['species-specific physical requirements','occupancy/accessibility law','occupied-habitat fraction','density and movement rules'],
            'reason':taxon['evidence'],'source_status':'UNKNOWN'}
    ranges=[]; movements=[]; habitat=None
    for bound in (0,1):
        cs,es,origins,rule,total,habitat=inputs(bundle,recipe,environment,scenario_id,organism_id,season_id,bound)
        ranges.append(spatial.evaluate_range(cs,es,origins,rule,season_id=season_id,prescribed_total=total))
        move=upstream.exact_fields(spec['movement'],('destination_season_id','requests','receiving_capacity','evidence','source_status'),'seasonal movement scenario')
        target=move['destination_season_id']
        if target not in taxon['seasons']: raise ValueError('explicit arrival season required')
        if taxon['seasons'][target] is None:
            movements.append({'status':'UNKNOWN','reason':'arrival biological rules unresolved','destination_season_id':target})
            continue
        ds,de,do,dr,dt,dh=inputs(bundle,recipe,environment,scenario_id,organism_id,target,bound)
        requests=tuple(spatial.MovementRequest(**{**r,'expected_individuals':quantity(r['expected_individuals'])}) for r in move['requests'])
        movements.append(spatial.route_movements(cs,es,origins,rule,requests,season_id=season_id,
            receiving_capacity={k:quantity(v) for k,v in move['receiving_capacity'].items()},evidence=move['evidence'],source_status=move['source_status'],
            prescribed_total=total,
            destination_cells=ds,destination_edges=de,destination_origins=do,destination_rule=dr,destination_season_id=target,destination_prescribed_total=dt))
    mapped=placements(recipe,organism_id,season_id,*ranges)
    for ident,h in habitat.items():
        threshold=spec['rule']['suitability_minimum']
        if h['interval'] is not None and threshold is not None and h['interval'][0]<threshold<=h['interval'][1]:
            mapped[ident].update(status='UNKNOWN',modelled_presence=None,occupancy_probability_interval=None,
                expected_occupied_area_m2_interval=None,expected_individuals_interval=None,
                reason='habitat numerical interval straddles necessary-condition threshold; endpoint cases do not certify an envelope')
    status='MODELLED' if all(r['status']=='MODELLED' for r in ranges) and all(v['status']!='UNKNOWN' for v in mapped.values()) and all(m['status'] in ('MODELLED_FEASIBLE_ALLOCATION','NOT_APPLICABLE') for m in movements) else 'UNKNOWN_OR_CONFLICT'
    return {'status':status,'organism_id':organism_id,'season_id':season_id,'habitat':habitat,
            'range_endpoint_cases':{'lower_habitat':ranges[0],'upper_habitat':ranges[1]},'cells':mapped,
            'movement_endpoint_cases':{'lower_habitat':movements[0],'upper_habitat':movements[1]},
            'movement_interpretation':'conditional allocation cases, not proven flow envelopes or global multi-OD optimum',
            'source_status':'WORKING NON-CANON','biological_rule_sha256':upstream.digest(taxon)}


def coverage(recipe,results,completed,total):
    statuses={ident:[] for ident in recipe['organisms']}
    for scenario in results.values():
        for ident,seasons in scenario.items():
            statuses[ident].extend(r['status'] for r in seasons.values())
    expected_per_organism=total//len(statuses)
    return {'requested_organism_count':len(statuses),'completed_units':completed,'expected_units':total,
            'all_units_executed':completed==total,
            'organisms':{k:{'source_status':recipe['organisms'][k]['source_status'],'retained_hs':recipe['organisms'][k]['retained_hs'],
                'unit_statuses':sorted(set(v)),'required_products_complete':len(v)==expected_per_organism and all(x in ('MODELLED','NOT_APPLICABLE') for x in v)} for k,v in statuses.items()},
            'all_required_products_complete':completed==total and all(v and all(x in ('MODELLED','NOT_APPLICABLE') for x in v) for v in statuses.values()),
            'no_complete_universal_plant_animal_roster_claim':True}


def overlap_products(recipe,environment,results):
    products={}
    for scenario_id,scenario in environment['scenarios'].items():
        products[scenario_id]={}
        for season_id,physical in scenario['seasons'].items():
            groups={}
            for group in ('RETAINED','SYNTHETIC_TEST'):
                eligible=[k for k,v in recipe['organisms'].items() if v['applicability']=='SPATIAL' and
                    (v['source_status']!='SYNTHETIC TEST')==(group=='RETAINED')]
                cells={}
                for cell_id,cell in physical['cells'].items():
                    known=present=0
                    for ident in eligible:
                        row=results.get(scenario_id,{}).get(ident,{}).get(season_id)
                        value=None if row is None or row.get('cells') is None else row['cells'][cell_id]['modelled_presence']
                        if value is not None: known+=1; present+=int(value)
                    cells[cell_id]={'represented_cell_area_m2':cell['area_m2'],'eligible_taxa':len(eligible),
                        'evaluated_presence_taxa':known,'unknown_or_unexecuted_taxa':len(eligible)-known,
                        'modelled_present_taxa':present,'modelled_absent_taxa':known-present,
                        'observed_richness':None}
                groups[group]={'eligible_organism_ids':eligible,'cells':cells,
                    'meaning':'conditional modelled cell-presence overlap; unknown is not absence; test organisms never enter retained-organism counts'}
            products[scenario_id][season_id]=groups
    return products


def abundance_products(recipe,environment,results):
    """Explicit alternative abundance models; never added to occupancy outputs."""
    models={}
    for spec in recipe['abundance_scenarios']:
        selected=list(environment['scenarios']) if spec['physical_scenario_id']=='ALL_COEQUAL' else [spec['physical_scenario_id']]
        outputs={}
        for sid in selected:
            if sid not in environment['scenarios']: raise ValueError('unknown abundance physical scenario')
            physical=environment['scenarios'][sid]['seasons'][spec['season_id']]['cells']
            model=deepcopy(spec['model']); cells=model['cells']; admissibility={}
            if cells is not None:
                if len({c['cell_id'] for c in cells})!=len(cells) or {c['cell_id'] for c in cells}!=set(physical): raise ValueError('complete actual abundance footprint required')
                for cell in cells:
                    area=F(physical[cell['cell_id']]['area_m2'])
                    unit=results.get(sid,{}).get(spec['organism_id'],{}).get(spec['season_id'])
                    support=None
                    if unit is not None and 'range_endpoint_cases' in unit:
                        cases=[v['cells'][cell['cell_id']] for v in unit['range_endpoint_cases'].values()]
                        states=[(r['habitat_status'],r['accessibility']['status']) for r in cases]
                        support=True if all(h=='PASS' and a=='ACCESSIBLE' for h,a in states) else False if all(h=='FAIL' or a=='INACCESSIBLE' for h,a in states) else None
                    declared=cell['eligible']
                    cell['eligible']=False if declared is False or support is False else True if declared is True and support is True else None
                    admissibility[cell['cell_id']]={'declared':declared,'actual_required_support_and_accessibility':support,'effective':cell['eligible'],
                        'reason':'declared abundance geography cannot overrule missing or failing actual species habitat/accessibility'}
                    if spec['mode']=='DECLARED_DENSITY':
                        measure=cell['measure']; unit=measure['unit']
                        if unit not in ('m2','km2'): raise ValueError('R8 supplies area only; length/volume need separately evidenced physical support')
                        if measure['value'] is not None and quantity(measure['value'])*(1000000 if unit=='km2' else 1)!=area: raise ValueError('abundance measure differs from actual parent cell area')
                    else:
                        measure=cell['occupied_measure']
                        if measure is not None:
                            if measure['unit'] not in ('m2','km2'): raise ValueError('R8 stock adapter cannot invent length/volume')
                            if measure['value'] is not None and quantity(measure['value'])*(1000000 if measure['unit']=='km2' else 1)>area: raise ValueError('occupied measure exceeds actual cell area')
            value=stock.declared_density(model) if spec['mode']=='DECLARED_DENSITY' else stock.allocate_stock(model)
            outputs[sid]={'model':value,'parent_result_sha256':environment['parent_result_sha256'],
                'admissibility':admissibility,'declared_model_sha256':upstream.digest(spec['model']),
                'actual_cell_bindings':{k:{'area_m2':v['area_m2'],'parent_cell_sha256':v['parent_cell_sha256']} for k,v in physical.items()}}
        models[spec['scenario_id']]={'organism_id':spec['organism_id'],'season_id':spec['season_id'],'mode':spec['mode'],'physical_scenarios':outputs,
            'interpretation':'explicit alternative joint scenario, not additional organisms or measured carrying capacity'}
    unplaced={}
    for ident,row in owner_inputs.biological_roster().items():
        population=row['population_reference']; total=None if population is None else population['working_total']
        context={'species_id':ident,'counting_unit':'UNKNOWN' if population is None else population['counted_entity'],
            'life_stage':'UNKNOWN' if population is None else population['counted_entity'],
            'spatial_scope_id':'UNKNOWN' if population is None else population['scope'],
            'time_basis':'UNKNOWN' if population is None else population['temporal_basis'],
            'snapshot_id':upstream.digest(recipe['parent_recipe']),'joint_scenario_id':'OWNER_STOCK_UNPLACED',
            'supplier':'Bound R9 Ecology/Population owners','evidence':row['evidence'],'source_status':'WORKING NON-CANON'}
        value=stock.allocate_stock({'schema':'diadem.prescribed-stock-input.r9','context':context,'total_expected_entities':total,'cells':None})
        unplaced[ident]={'allocation':value,'source_population_reference':population,
            'reason':'no source-bound admissible footprint/weights for this census scope; working stock does not force new terrain habitat',
            'not_wild_generation':row['retained_hs'] in (14,19)}
    return {'alternative_scenarios':models,'owner_stock_register':unplaced,
        'scenarios_and_seasons_are_not_additive':True,'observed_density_supplied':False,
        'whole_diadem_population_derived':False}


def run(bundle,recipe,*,stop_after=None,resume=None):
    recipe=parse(bundle,recipe); parent=bundle.parent.run(recipe['parent_recipe'])
    environment=upstream.project(bundle,parent,recipe['seasons']); parent_sha=upstream.digest(parent); env_sha=upstream.digest(environment)
    for overlay in recipe['actual_occurrence_overlays']:
        if overlay['cell_id'] not in next(iter(environment['scenarios'].values()))['seasons'][recipe['seasons'][0]['season_id']]['cells']: raise ValueError('occurrence overlay cell outside physical support')
    ordered=sorted((scenario,organism,season['season_id']) for scenario in environment['scenarios'] for organism in recipe['organisms'] for season in recipe['seasons'])
    until=len(ordered) if stop_after is None else stop_after
    if type(until) is not int or not 0<=until<=len(ordered): raise ValueError('bounded whole species-season cursor required')
    def simulate(count):
        results={}
        for scenario,organism,season in ordered[:count]:
            results.setdefault(scenario,{}).setdefault(organism,{})[season]=evaluate_unit(bundle,recipe,environment,scenario,organism,season)
        return {'completed_units':count,'parent_result_sha256':parent_sha,'environment_sha256':env_sha,'results':results}
    recipe_sha=upstream.digest(recipe)
    if resume is not None:
        upstream.exact_fields(resume,('schema','recipe_sha256','source_sha256','state_sha256','state'),'R9 checkpoint')
        saved=resume['state']; upstream.exact_fields(saved,('completed_units','parent_result_sha256','environment_sha256','results'),'R9 saved state')
        if resume['schema']!=binding.CHECKPOINT_SCHEMA or resume['source_sha256']!=bundle.source_sha256 or resume['recipe_sha256']!=recipe_sha or resume['state_sha256']!=upstream.digest(saved): raise ValueError('checkpoint binding differs')
        cursor=saved['completed_units']
        if type(cursor) is not int or not 0<=cursor<=until or saved!=simulate(cursor): raise ValueError('checkpoint state differs from actual upstream/spatial replay')
    state=simulate(until)
    abundance=abundance_products(recipe,environment,state['results'])
    result={'schema':binding.RESULT_SCHEMA,'source_status':'WORKING NON-CANON','source_sha256':bundle.source_sha256,
        'recipe_sha256':recipe_sha,'parent_result_sha256':parent_sha,'environment':environment,'state':state,
        'roster_coverage':coverage(recipe,state['results'],until,len(ordered)),
        'biological_owner_contracts':owner_inputs.biological_roster(),
        'abundance_models':abundance,
        'seasonal_cohort_chains':phases.run(bundle,recipe,environment,abundance,inputs),
        'overlap_products':overlap_products(recipe,environment,state['results']),
        'actual_occurrence_overlays':recipe['actual_occurrence_overlays'],'observations_used_as_forcing':False,
        'production_installed':False,'canon_changed':False,'optimisation_performed':False,'limits':recipe['limits']}
    return bundle.storage.decoded(bundle.storage.encoded(result))
