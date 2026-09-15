"""Executable source-bound category graph; missing parents remain explicit gates.

Scientific producers run INSIDE the graph. Reused projections are declared as
supplied parent products, not newly regenerated science. Packed artifacts are
individually bounded; the graph contains only content references.
"""
from copy import deepcopy
from fractions import Fraction
from . import snapshot as s

SCHEMA = 'diadem.executable-category-workflow.r11'
E = 'WORKING NON-CANON bounded reference graph; execution and domain acceptance are distinct.'


def retained_organic_density(r8_recipe):
    """Preflight the ACTUAL R8 -> R7 soil recipe, before any graph producer.

    R8 names this input soil_recipe, unlike R9/R10's parent_recipe. The
    original scalar is retained exactly; this is not a new packing hypothesis.
    """
    soil = r8_recipe.get('soil_recipe')
    if not isinstance(soil, dict) or not isinstance(soil.get('organic'), dict):
        raise ValueError('actual R8 soil_recipe organic packing input required')
    value = soil['organic'].get('grain_density_kg_m3')
    if type(value) not in (int, float, str):
        raise ValueError('explicit positive retained organic grain density required')
    try:
        positive = Fraction(value) > 0
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError('finite positive retained organic grain density required') from exc
    if not positive:
        raise ValueError('positive retained organic grain density required')
    return value


class Artifacts:
    def __init__(self, codec):
        self.codec = codec
        self.records = {}

    def put(self, value, role):
        record = self.codec.pack(value)
        key = record['sha256']
        if key in self.records and self.records[key] != record:
            raise ValueError('content-address collision')
        self.records[key] = record
        return {'artifact_id': key, 'sha256': key, 'schema': value.get('schema', 'explicit-object'),
                'byte_length': record['byte_length'], 'role': role}

    def get(self, ref):
        s.exact(ref, ('artifact_id','sha256','schema','byte_length','role'), 'artifact reference')
        s.text(ref['role'])
        if ref['artifact_id'] != s.digest(ref['sha256']) or ref['artifact_id'] not in self.records:
            raise ValueError('unbound scientific artifact')
        record = self.records[ref['artifact_id']]
        if record['sha256'] != ref['sha256'] or record['byte_length'] != ref['byte_length']:
            raise ValueError('artifact identity/size differs')
        value = self.codec.unpack(record)
        if value.get('schema', 'explicit-object') != ref['schema']:
            raise ValueError('artifact scientific schema differs')
        return value


def assemble(bundle, recipe, *, supplied_parent=None):
    """Build metadata/registrations only; no scientific run happens here.

    Supplied R10 is an explicit test/replay seam, never silently labelled fresh
    generation. R8/R9 are still actually executed and checked against its lineage.
    """
    p = bundle.module('pipeline'); p.parse(bundle, recipe)
    recipe = deepcopy(recipe)
    r10 = bundle.parent; r9 = r10.parent; r8 = r9.parent
    r10_recipe = recipe['parent_recipe']; r9_recipe = r10_recipe['parent_recipe']; r8_recipe = r9_recipe['parent_recipe']
    organic_density = retained_organic_density(r8_recipe)
    codec = r10.graph.load('work.generator_upgrade_r10.payloads')
    artifacts = Artifacts(codec)
    input_ref = artifacts.put(recipe, 'explicit R11 input recipe, not scientific output')
    geo = bundle.module('owner_inputs').geography(bundle)
    if (geo.get('contract',{}).get('schema') != 'diadem.geo.r11-input-contract.v1'
            or not isinstance(geo.get('source_bindings'),dict)):
        raise ValueError('actual source-bound GEO contract required')
    geo_ref = artifacts.put(geo, 'exact GEO delivered field/status/owner contract, not accepted world geometry')
    supplied_ref = None if supplied_parent is None else artifacts.put(deepcopy(supplied_parent), 'explicit supplied R10 result; not regeneration')
    hm = r8.parent.parent.pipeline.hm
    groups = sorted(scenario.scenario_id+'/'+key for scenario in hm.snow_scenarios() for key in r10_recipe['hydraulic_hypotheses'])
    calendar = r8_recipe['seasonal']['calendar']['calendar_id']
    context = {'world_id': 'DIADEM_BOUNDED_REFERENCE', 'snapshot_id': s.sha(recipe), 'calendar_id': calendar,
        'spatial_frame_id': 'EXACT_PARENT_CELL_SUPPORT/'+s.sha({'cells': sorted(r8_recipe['cell_context']), 'edges': r8_recipe['edges']}),
        'vertical_reference': 'EXACT_RETAINED_PARENT_DATUM; NO NEW GEOGRAPHICAL DATUM',
        'scenario_id': 'COEQUAL_BRANCHES_NOT_ADDITIVE'}
    registry = {}; stages = []; stage_ports = {}; diagnostics = {}

    def add(ident, category, producer, *, dependencies=(), mode='GENERATED', gaps=(), scope=''):
        port = {'quantity': scope or 'source-bound scientific artifact', 'unit': 'typed record',
                'support_id': ident, 'temporal_support': calendar}
        stage_ports[ident] = port
        producer_id = 'r11.workflow.'+ident
        def run(ctx, inputs, incoming):
            if inputs != {'recipe_ref': input_ref, 'scope': scope, 'supplied_ref': supplied_ref if ident == 'parent-r10' else None}:
                raise ValueError('registered producer input binding differs')
            live_recipe = artifacts.get(inputs['recipe_ref'])
            if s.sha(live_recipe) != context['snapshot_id']:
                raise ValueError('scientific recipe changed')
            values = {key: artifacts.get(ref) for key,ref in incoming.items()}
            out, reason = producer(live_recipe, values, incoming)
            if reason is not None:
                if out is not None:
                    diagnostics[ident] = artifacts.put(out, 'failed/conditional producer diagnostic, not a known output')
                return s.emission(ctx, {'product':port}, {'product':None}, evidence=E,
                    status='UNKNOWN', source_status='UNKNOWN', unresolved=[reason])
            ref = artifacts.put(out, scope)
            return s.emission(ctx, {'product':port}, {'product':ref}, evidence=E,
                status='MODELLED' if mode == 'GENERATED' else 'SUPPLIED_CONSTRAINT', source_status='WORKING NON-CANON')
        registry[producer_id] = {'sha256': bundle.source_sha256, 'run':run, 'verify':bundle.graph.verify}
        stages.append({'stage_id':ident, 'category':category, 'producer_id':producer_id, 'producer_sha256':bundle.source_sha256,
            'inputs':{'recipe_ref':input_ref,'scope':scope,'supplied_ref':supplied_ref if ident=='parent-r10' else None},
            'dependencies':{name:{'stage_id':parent,'output':'product','port':stage_ports[parent]} for name,parent in dependencies},
            'outputs':{'product':port}, 'missing_inputs':list(gaps), 'mode':mode,
            'acceptance':{'status':'PENDING','evidence':'Actual execution proof and domain adoption are separate; no automatic approval'}})

    def physical(_, values, refs):
        out = r8.run(r8_recipe)
        if out.get('schema') != 'diadem.biomes-vegetation-result.r8':
            raise ValueError('actual R8 scientific schema differs')
        if out.get('source_sha256') != r8.source_sha256 or out.get('recipe_sha256') != s.sha(r8_recipe):
            raise ValueError('actual R8 source/recipe differs')
        return out, None
    add('physical-r8', 'biomes', physical, scope='Actual R8 formed-soil/seasonal/PFT/biome producer on explicit bounded inputs')

    def world_frames(_,values,refs):
        return bundle.module('world_inputs').declared_frames(geo),None
    add('world-owner-frames','topography_topology',world_frames,mode='SUPPLIED_CONSTRAINT',
        scope='Actual owner-declared native frames and retained branch, UNKNOWN datum fields preserved; no maps loaded, no political ancestry invented or accepted world inferred')

    def biology(_, values, refs):
        out = r9.run(r9_recipe)
        if out.get('parent_result_sha256') != s.sha(values['physical']):
            raise ValueError('R9 actual R8 dependency differs')
        return out, None
    add('biology-r9', 'plant_animal_ranges', biology, dependencies=(('physical','physical-r8'),),
        scope='Actual R9 execution artifact with conditional biological branches; NOT complete ordinary-organism ranges')

    def owner_biology(_, values, refs):
        package=bundle.module('owner_inputs').species(bundle)
        return bundle.module('biology').build_overlay(package),None
    add('biology-owner-overlay','plant_animal_ranges',owner_biology,mode='SUPPLIED_CONSTRAINT',
        scope='Actual delivered biological facts and scoped decisions compiled into preserved-status field records, NOT invented numerical species coefficients')

    def parent(_, values, refs):
        out = r10.run(r10_recipe) if supplied_ref is None else artifacts.get(supplied_ref)
        if (out.get('parent_result_sha256') != s.sha(values['biology'])
                or out.get('physical_parent_result_sha256') != s.sha(values['physical'])):
            raise ValueError('R10 actual R9/R8 dependency artifacts differ')
        actual_groups = p.parent_units(bundle, recipe, out)
        if sorted(actual_groups) != groups:
            raise ValueError('actual complete coequal scenario inventory differs')
        return out, None
    add('parent-r10', 'climate', parent, dependencies=(('physical','physical-r8'),('biology','biology-r9')),
        mode='GENERATED' if supplied_ref is None else 'SUPPLIED_CONSTRAINT',
        scope='Actual R10 seasonal chain execution' if supplied_ref is None else 'Explicit supplied R10 seasonal artifact, checked against fresh R8/R9')

    def project(ident, category, source, locator, scope):
        def producer(_, values, refs):
            selected = values['source']
            for name in locator:
                if not isinstance(selected,dict) or name not in selected:
                    return None, 'actual parent projection missing: '+'.'.join(locator)
                selected = selected[name]
            if selected is None:
                return None, 'actual parent projection unavailable: '+'.'.join(locator)
            return {'schema':'diadem.bound-parent-projection.r11','parent_ref':refs['source'],
                'locator':locator,'selected_value_sha256':s.sha(selected), 'scope':scope,
                'origin':'SUPPLIED_DERIVED_PARENT_PRODUCT_NOT_NEW_SCIENTIFIC_REGENERATION'}, None
        add(ident, category, producer, dependencies=(('source',source),), mode='SUPPLIED_CONSTRAINT',scope=scope)

    project('precipitation-parent', 'precipitation', 'parent-r10', ['climate'],
        'Actual R10 monthly precipitation/snow/air projection, inherited fixed circulation forcing')
    project('formed-soil-parent', 'soils_ground_conditions', 'physical-r8', ['soil_result','state'],
        'Actual formed finite profiles, operational horizons and fertility; source retained, not another formation run')
    project('topography-parent', 'topography_topology', 'physical-r8', ['soil_result','state'],
        'Current bounded column base elevations and formed geometry; not a regional topography/plate reconstruction')
    project('erosion-parent', 'erosion_sediment_transport', 'physical-r8', ['soil_result','parent_result'],
        'PRE_FORMATION R6 erosion/sediment reference; explicitly not a current R11 geometry rebind')

    water_ids = {}; eco_ids = {}; human_ids = {}; soil_ids = {}
    for group_id in groups:
        suffix = group_id.replace('/','--')
        def water_producer(_, values, refs, group_id=group_id):
            parent = values['parent']; group = p.parent_units(bundle,recipe,parent)[group_id]
            snow = next(iter(group.values()))['snow_id']
            spec, joins = p.water_inputs(bundle,recipe,group,parent['climate']['members'][snow])
            module = bundle.module('water')
            out = module.run(spec['network'],spec['initial'],spec['events'],controls=spec['controls'],
                source_binding_sha256=bundle.source_sha256,scenario_id=group_id)
            wrapped = {'schema':'diadem.workflow-water-stage.r11','scenario_id':group_id,'model':out,'source_joins':joins}
            return wrapped, None if out['status']=='MODELLED' else 'actual water producer '+out['status']
        water_id='water--'+suffix; water_ids[group_id]=water_id
        add(water_id,'hydrology',water_producer,dependencies=(('parent','parent-r10'),),
            scope='Actual finite water routing, temperature/phase/storage and terminal withdrawals: '+group_id)

        def eco_producer(_, values, refs, group_id=group_id):
            parent=values['parent']; group=p.parent_units(bundle,recipe,parent)[group_id]
            for cell,unit in group.items():
                layer=unit.get('carbon',{}).get('layers',{}).get(cell+'-mineral',{})
                if layer.get('diagnostic',{}).get('status')!='MODELLED_SEASONAL_CARBON_DIAGNOSTIC':
                    return None,'actual initial carbon/environment input missing: '+cell
            products, joins=p.ecosystem_products(bundle,recipe,group_id,group)
            out={'schema':'diadem.workflow-ecosystem-stage.r11','scenario_id':group_id,'models':products,'source_joins':joins}
            failed=[cell+':'+row['status'] for cell,row in products.items() if row['status']!='MODELLED_SEASONAL_ECOSYSTEM']
            return out,None if not failed else 'actual ecosystem producer unresolved: '+', '.join(failed)
        eco_id='ecosystem--'+suffix; eco_ids[group_id]=eco_id
        add(eco_id,'soils_ground_conditions',eco_producer,dependencies=(('parent','parent-r10'),),
            scope='Actual living carbon/finite nutrient/harvest operator with supplied biological laws: '+group_id)

        soil_ids[group_id]={}
        for cell in sorted(r8_recipe['cell_context']):
            def soil_producer(_,values,refs,group_id=group_id,cell=cell):
                group=p.parent_units(bundle,recipe,values['parent'])[group_id]; unit=group[cell]
                formed=values['physical']['soil_result']['state']['members'][unit['snow_id']][cell]
                sw=bundle.parent.parent.parent.parent.parent.solver
                solver=bundle.parent.graph.load('work.generator_upgrade_r10.richards_numerics').Adapter(sw)
                out=bundle.module('soil_feedback').reference_continuation(solver,unit,formed,values['ecosystem']['models'][cell],
                    organic_grain_density_kg_m3=organic_density,source_binding_sha256=bundle.source_sha256,
                    evidence='SYNTHETIC TEST: exact retained organic density/current joint packing; explicit unfrozen zero-input one-second continuation, not forecast',
                    duration_seconds=1,geometry_atol_m=1e-9)
                return out,None if out['status']=='MODELLED_STRUCTURE_AND_WATER_CONTINUATION' else 'actual soil/water continuation '+out['status']
            soil_id='soil-feedback--'+suffix+'--'+cell; soil_ids[group_id][cell]=soil_id
            add(soil_id,'soils_ground_conditions',soil_producer,
                dependencies=(('parent','parent-r10'),('physical','physical-r8'),('ecosystem',eco_id)),
                scope='Actual one-to-one organic structure/water remap and new solver-produced pressure on an explicit short unfrozen continuation: '+group_id+'/'+cell)

        def human_producer(_, values, refs, group_id=group_id):
            parent=values['parent']; group=p.parent_units(bundle,recipe,parent)[group_id]
            spec=p.human_inputs(bundle,recipe,parent,group_id,group,values['water']['model'],values['ecosystem']['models'])
            out=bundle.module('human').run_year(bundle.transport,**spec)
            return {'schema':'diadem.workflow-human-stage.r11','scenario_id':group_id,'model':out,'inputs':spec}, None if out['status']=='COMPLETE' else 'actual human stock chain '+out['status']
        human_id='human--'+suffix; human_ids[group_id]=human_id
        add(human_id,'infrastructure_connectivity',human_producer,
            dependencies=(('parent','parent-r10'),('water',water_id),('ecosystem',eco_id)),
            scope='Actual conserved food/water service and shared weather-dependent transport: '+group_id)
        project('hazards--'+suffix,'natural_hazards',human_id,['model','events'],
            'Computed held-wind/SWE exposure and service restrictions, NOT probabilities: '+group_id)
        project('settlements--'+suffix,'settlements',human_id,['model','fixed_settlements'],
            'Explicit fixed synthetic settlement supports, not generated adopted sites: '+group_id)
        project('populations--'+suffix,'populations',human_id,['model','fixed_settlements'],
            'Explicit fixed synthetic people and border labels; no demographic history: '+group_id)
        project('food-resources--'+suffix,'resources_land_suitability',human_id,['model','events'],
            'Computed edible dry stock/service accounts, not mineral reserves or generic ecological fertility: '+group_id)

    missing = {
        'plate_tectonics':'No actual regional plate configuration/kinematics input bound by this reference; uplift/columns are not plates',
        'geology':'No actual regional geological-unit/structure parent bound; supplied local materials do not constitute a geological map',
        'political_borders':'No source-bound political boundary geometry/access-rights parent; synthetic site border labels are not polygons',
        'seas_coastal_processes':'No sea/coast boundary, bathymetry, waves/tides or coastal-process input; inland reservoirs are not marine simulation',
        'land_use_agriculture':'No actual cultivated land/use allocation and explicit daily crop/irrigation parent selected; edible biomass conversion is not crop modelling',
        'erosion_sediment_transport':'Post-formation/seasonal changing-geometry sediment/water rebind absent; inherited pre-formation sediment record is historical only',
        'plant_animal_ranges':'Ordinary-organism numerical R9 branches remain conditionally unresolved; executing R9 is not complete calibrated occurrence/abundance'}
    missing['populations']='Working human total 15,964,359 and component row statuses are supplied by GEO; compatible physical settlement/population mapping is not bound by this synthetic reference'
    for category,reason in missing.items():
        add('required-parent--'+category,category,lambda *_:(None,'missing physical parent'),
            mode='SUPPLIED_CONSTRAINT',gaps=(reason,),scope='Required whole-category parent/closure gate; no placeholder generation')
    owner_categories = {
        'accepted_world_snapshot_and_complete_frame':('topography_topology',),
        'structural_model_scope_and_unsupported_kinematics':('plate_tectonics','geology'),
        'named_water_receivers_storage_routing_exchange':('hydrology','seas_coastal_processes'),
        'compatible_climate_soil_and_thermal_inputs':('climate','precipitation','biomes','soils_ground_conditions'),
        'realised_productive_parcels_and_supply':('resources_land_suitability','land_use_agriculture'),
        'occupied_operational_site_extents':('settlements',),
        'physical_network_and_capacities':('infrastructure_connectivity',),
        'seelenwacht_secondary_route':('infrastructure_connectivity',),
        'compatible_political_parent_and_policy':('political_borders',)}
    owner_unresolved=geo.get('effective_unresolved',geo['contract']['unresolved'])
    for row in owner_unresolved:
        s.exact(row,('field','status','owner'),'GEO unresolved field')
        for value in row.values(): s.text(value)
        if row['field'] not in owner_categories:
            raise ValueError('new owner field needs explicit category mapping, not silent omission')
        for category in owner_categories[row['field']]:
            reason='GEO field '+row['field']+'; original status='+row['status']+'; exact owner='+row['owner']
            add('owner-gap--'+category+'--'+row['field'],category,lambda *_:(None,'unresolved owner field'),
                mode='SUPPLIED_CONSTRAINT',gaps=(reason,),scope='World-acceptance field only; existing conditional reference branches remain executable')
    graph_recipe={'schema':'diadem.snapshot-graph-recipe.r11','context':context,'stages':stages,
                  'required_categories':list(s.CATEGORIES),'evidence':E}
    return {'recipe':graph_recipe,'registry':registry,'artifacts':artifacts,'diagnostics':diagnostics,
            'geo_ref':geo_ref,'owner_field_statuses':deepcopy(owner_unresolved),
            'stage_ids':{'parent':'parent-r10','physical':'physical-r8','biology':'biology-r9',
                         'water':water_ids,'ecosystem':eco_ids,'human':human_ids,'soil_feedback':soil_ids},'input_ref':input_ref}


def run(bundle, recipe, *, stop_after=None, resume=None, supplied_parent=None):
    """Run complete graph stages, not the legacy pipeline's scenario cursor.

    Each packed_artifacts entry is a separate <=8MiB immutable scientific unit.
    Persist the graph/checkpoint and those records separately. Do not flatten the
    decompressed artifact store into one giant JSON or treat it as a new cache.
    """
    bundle.verify()
    built=assemble(bundle,recipe,supplied_parent=supplied_parent)
    graph=s.run(built['recipe'],built['registry'],stop_after=stop_after,resume=resume)
    def ref(stage):
        row=graph['state']['rows'].get(stage)
        return None if row is None or row['product']['status']=='UNKNOWN' else row['product']['values']['product']
    scenarios={}
    for group,hid in built['stage_ids']['human'].items():
        scenarios[group]={'water':ref(built['stage_ids']['water'][group]),
            'ecosystem':ref(built['stage_ids']['ecosystem'][group]),'human':ref(hid),
            'soil_feedback':{cell:ref(stage) for cell,stage in built['stage_ids']['soil_feedback'][group].items()}}
    # Each artifact and each envelope is validated independently without raising
    # the retained bound. References ensure data are not duplicated per category.
    for record in built['artifacts'].records.values():
        built['artifacts'].codec.unpack(record)
    checkpoint=s.checkpoint(graph); s.encoded(graph); s.encoded(checkpoint)
    bundle.verify()
    return {'schema':SCHEMA,'source_sha256':bundle.source_sha256,'recipe_sha256':s.sha(recipe),
        'status':graph['status'],'graph_artifact':graph,'graph_checkpoint':checkpoint,
        'graph_recipe':built['recipe'],'packed_artifacts':built['artifacts'].records,
        'parent_ref':ref(built['stage_ids']['parent']),'physical_parent_ref':ref(built['stage_ids']['physical']),
        'biology_parent_ref':ref(built['stage_ids']['biology']),'scenario_product_refs':scenarios,
        'biological_owner_overlay_ref':ref('biology-owner-overlay'),
        'declared_world_frames_ref':ref('world-owner-frames'),
        'owner_input_contract_ref':built['geo_ref'],'owner_field_statuses':built['owner_field_statuses'],
        'diagnostic_artifact_refs':built['diagnostics'],'whole_generator_complete':False,
        'scope':'Actual bounded graph execution with explicit missing whole-category parents; no new canon, production or optimisation',
        'cursor_semantics':'COMPLETE_GRAPH_STAGES; legacy run_from_parent scenario cursor unchanged',
        'storage_contract':'Separate bounded graph/checkpoint/recipe and one bounded packed record per artifact ID'}


def resolve(bundle, workflow_result, ref):
    """Strictly resolve one returned scientific artifact, not a live file/cache."""
    if workflow_result.get('schema')!=SCHEMA or workflow_result.get('source_sha256')!=bundle.source_sha256:
        raise ValueError('workflow result/source binding differs')
    store=Artifacts(bundle.parent.graph.load('work.generator_upgrade_r10.payloads'))
    store.records=workflow_result['packed_artifacts']
    return store.get(ref)


def materialise_consequences(bundle,recipe,workflow_result):
    """Reconstruct grouped consequence records from completed graph artifacts.

    No model or parent run is invoked. This is a view of checked content, not a
    substitute for the independent final scientific validators or graph replay.
    """
    p=bundle.module('pipeline'); p.parse(bundle,recipe)
    if workflow_result.get('recipe_sha256')!=s.sha(recipe):
        raise ValueError('workflow materialisation recipe differs')
    graph=workflow_result['graph_artifact']
    if (graph['recipe_sha256']!=s.sha(workflow_result['graph_recipe'])
            or workflow_result['graph_checkpoint']!=s.checkpoint(graph)):
        raise ValueError('workflow graph/checkpoint identity differs')
    def selected(stage,ref):
        row=graph['state']['rows'].get(stage)
        expected=None if row is None else row['product']['values']['product']
        if ref!=expected:
            raise ValueError('materialisation reference differs from executed stage')
        if row is not None and row['product_sha256']!=s.sha(row['product']):
            raise ValueError('executed stage product checksum differs')
        return None if ref is None else resolve(bundle,workflow_result,ref)
    parent=selected('parent-r10',workflow_result['parent_ref'])
    if parent is None:
        raise ValueError('completed actual/supplied parent stage required for consequence materialisation')
    groups=p.parent_units(bundle,recipe,parent); codec=bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    if set(groups)!=set(workflow_result['scenario_product_refs']):
        raise ValueError('materialisation scenario inventory differs')
    outputs={}
    for group_id,group in sorted(groups.items()):
        refs=workflow_result['scenario_product_refs'][group_id]; suffix=group_id.replace('/','--')
        water=selected('water--'+suffix,refs['water']); ecosystem=selected('ecosystem--'+suffix,refs['ecosystem'])
        human=selected('human--'+suffix,refs['human'])
        soil={cell:selected('soil-feedback--'+suffix+'--'+cell,ref) for cell,ref in refs['soil_feedback'].items()}
        if set(soil)!=set(group):
            raise ValueError('materialisation soil-feedback support inventory differs')
        complete=water is not None and ecosystem is not None and human is not None
        row={'scenario_id':group_id,'parent_unit_sha256':{c:s.sha(u) for c,u in sorted(group.items())},
            'water':{'status':'UNKNOWN','reason':'graph water predecessor unresolved'} if water is None else water['model'],
            'ecosystems':{} if ecosystem is None else ecosystem['models'],
            'human':{'status':'UNKNOWN','reason':'graph stock predecessor unresolved'} if human is None else human['model'],
            'human_inputs':None if human is None else human['inputs'],
            'water_joins':[] if water is None else water['source_joins'],
            'ecosystem_joins':{} if ecosystem is None else ecosystem['source_joins'],
            'status':'MODELLED' if complete else 'INCOMPLETE','actual_biology_calibrated':False,
            'physical_soil_geometry_feedback':'MODELLED_BOUNDED_UNFROZEN_CONTINUATION' if all(v is not None for v in soil.values()) else 'INCOMPLETE',
            'soil_feedback':deepcopy(refs['soil_feedback']),'soil_feedback_retained_as_refs':True,'fixed_snapshot_not_history':True}
        outputs[group_id]=codec.pack(row)
    geo=resolve(bundle,workflow_result,workflow_result['owner_input_contract_ref'])
    biology=selected('biology-owner-overlay',workflow_result['biological_owner_overlay_ref'])
    complete=all(codec.unpack(row)['status']=='MODELLED' for row in outputs.values())
    return {'schema':'diadem.seasonal-consequences-result.r11','source_sha256':bundle.source_sha256,'source_status':'WORKING NON-CANON',
        'recipe_sha256':s.sha(recipe),'parent_result_sha256':s.sha(parent),
        'state':{'completed_scenarios':len(outputs),
            'parent_result_sha256':s.sha(parent),'results':outputs},
        'status':'COMPLETE_BOUNDED_CONSEQUENCES' if complete else 'INCOMPLETE',
        'parent_retained_separately':True,'hypotheses_are_coequal_not_additive':True,
        'biological_owner_inputs':None if biology is None else codec.pack(biology),
        'biological_input_status':'OWNER_FACTS_AND_SCOPED_DECISIONS_INTEGRATED; NO_NEW_SELECTED_NUMERICAL_COEFFICIENTS' if biology is not None else 'UNKNOWN',
        'geo_input_contract':{'sha256':s.sha(geo),'source_bindings':geo['source_bindings'],
            'unresolved':geo.get('effective_unresolved',geo['contract']['unresolved']),
            'original_unresolved':geo['contract']['unresolved'],
            'effective_unresolved':geo.get('effective_unresolved',geo['contract']['unresolved']),
            'requested_owner_returns_complete':geo.get('requested_owner_returns_complete',False),
            'world_input_completeness':geo['contract']['world_input_completeness']},
        'remaining_physical_feedback':['general frozen unsaturated soil hydraulics','general deformation, changed saturated packing and full-history recoupling'],
        'whole_generator_complete':False,'production_installed':False,'canon_changed':False,'optimisation_performed':False,
        'limits':recipe['scope'],'materialised_without_scientific_reruns':True,
        'graph_status':workflow_result['status'],'graph_recipe_sha256':graph['recipe_sha256']}


def graph_stop_after_first_human(bundle,recipe,*,supplied_parent=None):
    """Metadata-only complete-stage cursor, including one actual human producer."""
    built=assemble(bundle,recipe,supplied_parent=supplied_parent)
    _,order=s.parse(built['recipe'],built['registry'])
    human=set(built['stage_ids']['human'].values())
    return next(i+1 for i,stage in enumerate(order) if stage in human)
