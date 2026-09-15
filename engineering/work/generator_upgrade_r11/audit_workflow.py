"""Independent saved-workflow verifier: metadata reconstruction, never model runs.

This proves graph/artifact/source joins and delegates saved material accounts to
the independent auditors. It does not semantically replay scientific producers,
adopt a world or claim that rehashing arbitrary scientific output is sufficient.
"""
from dataclasses import replace
from fractions import Fraction as F
from . import snapshot as s


def require(condition, message):
    if not condition:
        raise ValueError(message)


def result(bundle, recipe, workflow_product, supplied_parent=None, complete=True):
    """Audit a complete bounded workflow or an exact accepted stage prefix.

    assemble/parse reconstruct only expected metadata. Biological owner overlays
    and declared frame records are rebuilt from verified source facts; no R8/R9/
    R10, water, ecosystem, human or soil solver producer is called here.
    """
    require(type(complete) is bool, 'explicit complete/prefix audit mode required')
    bundle.verify()
    workflow = bundle.module('workflow')
    built = workflow.assemble(bundle, recipe, supplied_parent=supplied_parent)
    nodes, order = s.parse(built['recipe'], built['registry'])
    expected_fields = ('schema', 'source_sha256', 'recipe_sha256', 'status', 'graph_artifact',
        'graph_checkpoint', 'graph_recipe', 'packed_artifacts', 'parent_ref', 'physical_parent_ref',
        'biology_parent_ref', 'scenario_product_refs', 'biological_owner_overlay_ref', 'declared_world_frames_ref',
        'owner_input_contract_ref', 'owner_field_statuses', 'diagnostic_artifact_refs', 'whole_generator_complete',
        'scope', 'cursor_semantics', 'storage_contract')
    out = s.exact(workflow_product, expected_fields, 'workflow result')
    require(out['schema'] == workflow.SCHEMA and out['source_sha256'] == bundle.source_sha256
        and out['recipe_sha256'] == s.sha(recipe), 'workflow recipe/source/schema binding differs')
    require(out['graph_recipe'] == built['recipe'], 'workflow stage/inputs/port/source recipe differs from actual registrations')
    require(out['whole_generator_complete'] is False, 'bounded workflow is not a completed world generator')
    require(out['cursor_semantics'] == 'COMPLETE_GRAPH_STAGES; legacy run_from_parent scenario cursor unchanged', 'workflow cursor meaning differs')
    require(out['scope'] == 'Actual bounded graph execution with explicit missing whole-category parents; no new canon, production or optimisation',
        'workflow applicability scope differs')
    require(out['storage_contract'] == 'Separate bounded graph/checkpoint/recipe and one bounded packed record per artifact ID',
        'bounded artifact storage contract differs')
    graph = s.exact(out['graph_artifact'], ('schema', 'recipe_sha256', 'state', 'category_closure', 'status',
        'whole_generator_implemented_claim', 'production_authorised', 'canon_changed', 'acceptance_declarations_are_not_verified_authority'), 'saved graph')
    require(graph['schema'] == 'diadem.snapshot-graph-result.r11' and graph['recipe_sha256'] == s.sha(built['recipe']), 'graph identity differs')
    for key in ('whole_generator_implemented_claim', 'production_authorised', 'canon_changed'):
        require(graph[key] is False, 'graph falsely claims world/canon/production authority')
    require(graph['acceptance_declarations_are_not_verified_authority'] is True, 'acceptance status qualification lost')
    state = s.exact(graph['state'], ('completed_stages', 'rows'), 'graph prefix state')
    count = state['completed_stages']
    require(type(count) is int and 0 <= count <= len(order), 'invalid graph prefix cursor')
    require(not complete or count == len(order), 'complete audit requires all graph stages')
    require(type(state['rows']) is dict and set(state['rows']) == set(order[:count]), 'graph prefix omits/reorders required stage membership')
    require(out['graph_checkpoint'] == s.checkpoint(graph), 'graph checkpoint/state binding differs')
    s.encoded(graph); s.encoded(out['graph_checkpoint'])
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    store = workflow.Artifacts(codec)
    require(type(out['packed_artifacts']) is dict, 'packed scientific artifact store required')
    store.records = out['packed_artifacts']
    for key, record in store.records.items():
        require(s.digest(key) == record['sha256'], 'artifact key and payload digest differ')
        codec.unpack(record)  # Enforces original per-artifact codec/byte bound.
    for key, record in built['artifacts'].records.items():
        require(store.records.get(key) == record, 'assembled explicit recipe/source/supplied-parent artifact differs')
    reachable = set(built['artifacts'].records)

    def resolve(ref, expected_role=None):
        value = store.get(ref)
        if expected_role is not None:
            require(ref['role'] == expected_role, 'scientific artifact role differs')
        reachable.add(ref['artifact_id'])
        return value

    def stage_ref(ident):
        row = state['rows'].get(ident)
        return None if row is None else row['product']['values']['product']

    def stage_value(ident):
        ref = stage_ref(ident)
        return None if ref is None else resolve(ref, nodes[ident]['inputs']['scope'])

    # Independent reconstruction of each invocation/dependency port and skipped
    # output. No registered callable is invoked; hashes alone are not the oracle.
    unknown_executed = set()
    for ident in order[:count]:
        stage = nodes[ident]
        row = s.exact(state['rows'][ident], ('invocation_sha256', 'product_sha256', 'producer_executed', 'product'), 'executed stage row')
        product = s.product(row['product'], built['recipe']['context'], stage['outputs'])
        require(type(row['producer_executed']) is bool, 'producer execution flag must be Boolean')
        bindings, missing = {}, list(stage['missing_inputs'])
        for name, dep in sorted(stage['dependencies'].items()):
            parent = state['rows'][dep['stage_id']]
            bindings[name] = parent['product_sha256']
            if parent['product']['status'] == 'UNKNOWN':
                missing.append('dependency '+dep['stage_id']+': '+', '.join(parent['product']['unresolved']))
        require(row['invocation_sha256'] == s.sha({'context': built['recipe']['context'], 'stage':stage,
            'dependency_products':bindings}), 'stage invocation/dependency digest differs')
        require(row['product_sha256'] == s.sha(product), 'stage emission digest differs')
        if missing:
            expected = s.emission(built['recipe']['context'], stage['outputs'], {k:None for k in stage['outputs']},
                evidence='Required input closure failed; no affected producer execution', source_status='UNKNOWN',
                status='UNKNOWN', unresolved=missing)
            require(product == expected and row['producer_executed'] is False, 'missing input did not produce exact non-executed UNKNOWN gate')
        else:
            require(row['producer_executed'] is True, 'available registered stage falsely marked not executed')
            require(product['evidence'] == workflow.E, 'registered product evidence differs')
            if product['status'] == 'UNKNOWN':
                require(product['source_status'] == 'UNKNOWN', 'failed producer source status differs')
                unknown_executed.add(ident)
            else:
                expected_status = 'MODELLED' if stage['mode'] == 'GENERATED' else 'SUPPLIED_CONSTRAINT'
                require(product['status'] == expected_status and product['source_status'] == 'WORKING NON-CANON',
                    'supplied/generated/source-status classification differs')
                resolve(product['values']['product'], stage['inputs']['scope'])

    closure = {}
    for category in s.CATEGORIES:
        ids = [k for k in order if nodes[k]['category'] == category]
        done = bool(ids) and all(k in state['rows'] and state['rows'][k]['product']['status'] != 'UNKNOWN' for k in ids)
        accepted = done and all(nodes[k]['acceptance']['status'] == 'DOMAIN_ACCEPTED' for k in ids)
        closure[category] = {'stage_ids':ids, 'required':category in built['recipe']['required_categories'],
            'execution_complete':done, 'domain_acceptance_declared':accepted,
            'generated_stage_ids':[k for k in ids if nodes[k]['mode'] == 'GENERATED'],
            'supplied_constraint_stage_ids':[k for k in ids if nodes[k]['mode'] == 'SUPPLIED_CONSTRAINT']}
    require(graph['category_closure'] == closure, 'category closure inflated or omitted')
    target_complete = all(closure[k]['execution_complete'] for k in built['recipe']['required_categories'])
    status = 'STOPPED' if count < len(order) else ('EXECUTED' if target_complete else 'INCOMPLETE')
    require(out['status'] == graph['status'] == status, 'graph/workflow completion status differs')
    require(not complete or status == 'INCOMPLETE', 'this bounded reference cannot imply a complete accepted world')
    diagnostics = out['diagnostic_artifact_refs']
    require(type(diagnostics) is dict and set(diagnostics) <= unknown_executed, 'diagnostic attached to nonfailed/unexecuted stage')
    for ident, ref in diagnostics.items():
        resolve(ref, 'failed/conditional producer diagnostic, not a known output')
    require(set(store.records) == reachable, 'unreferenced/missing scientific artifact in workflow store')

    # External named references must select exactly their executed stage, not an
    # interchangeable object with a recomputed checksum.
    for field, ident in (('physical_parent_ref','physical-r8'), ('biology_parent_ref','biology-r9'),
            ('parent_ref','parent-r10'), ('biological_owner_overlay_ref','biology-owner-overlay'),
            ('declared_world_frames_ref','world-owner-frames')):
        require(out[field] == stage_ref(ident), 'workflow named stage reference differs: '+field)
    require(out['owner_input_contract_ref'] == built['geo_ref'], 'owner contract reference differs')
    geo = resolve(out['owner_input_contract_ref'])
    expected_geo = bundle.module('owner_inputs').geography(bundle)
    require(geo == expected_geo and out['owner_field_statuses'] == built['owner_field_statuses'], 'original/effective GEO field/status/source binding differs')
    owner_overlay = stage_value('biology-owner-overlay')
    if owner_overlay is not None:
        expected_bio = bundle.module('biology').build_overlay(bundle.module('owner_inputs').species(bundle))
        require(owner_overlay == expected_bio, 'actual delivered biology overlay differs')
    frame_product = stage_value('world-owner-frames')
    if frame_product is not None:
        require(frame_product == bundle.module('world_inputs').declared_frames(expected_geo), 'actual declared native world frame differs')

    physical, biological, parent = (stage_value(k) for k in ('physical-r8','biology-r9','parent-r10'))
    r10 = bundle.parent; r9 = r10.parent; r8 = r9.parent
    rr10 = recipe['parent_recipe']; rr9 = rr10['parent_recipe']; rr8 = rr9['parent_recipe']
    for value, bound, rr, schema in ((physical,r8,rr8,'diadem.biomes-vegetation-result.r8'),
            (biological,r9,rr9,'diadem.species-spatial-result.r9'), (parent,r10,rr10,'diadem.seasonal-world-result.r10')):
        if value is not None:
            require(value['schema'] == schema and value['source_sha256'] == bound.source_sha256
                and value['recipe_sha256'] == s.sha(rr), 'actual R8/R9/R10 source/recipe/schema differs')
            require(value['source_status'] == 'WORKING NON-CANON' and all(value[k] is False
                for k in ('production_installed','canon_changed','optimisation_performed')),
                'actual parent applicability/authority status differs')
    if biological is not None:
        require(physical is not None and biological['parent_result_sha256'] == s.sha(physical), 'actual R9-to-R8 digest join differs')
    if parent is not None:
        require(biological is not None and physical is not None
            and parent['parent_result_sha256'] == s.sha(biological)
            and parent['physical_parent_result_sha256'] == s.sha(physical), 'actual R10-to-R9/R8 digest join differs')
        if supplied_parent is not None:
            require(parent == supplied_parent, 'supplied parent was silently replaced or relabelled')

    # Rebuild source projections, including exact locator, value hash and origin
    # classification, independently of their registered producer functions.
    projections = {'precipitation-parent':('parent-r10',['climate']),
        'formed-soil-parent':('physical-r8',['soil_result','state']),
        'topography-parent':('physical-r8',['soil_result','state']),
        'erosion-parent':('physical-r8',['soil_result','parent_result'])}
    for group, hid in built['stage_ids']['human'].items():
        suffix = group.replace('/','--')
        for label, locator in (('hazards',['model','events']),('settlements',['model','fixed_settlements']),
                ('populations',['model','fixed_settlements']),('food-resources',['model','events'])):
            projections[label+'--'+suffix] = hid, locator
    for ident, (source, locator) in projections.items():
        projected = stage_value(ident)
        if projected is None:
            continue
        actual = stage_value(source)
        require(actual is not None, 'projection lacks actual source product')
        for name in locator:
            require(type(actual) is dict and name in actual, 'projection locator absent in actual source')
            actual = actual[name]
        expected = {'schema':'diadem.bound-parent-projection.r11', 'parent_ref':stage_ref(source),
            'locator':locator,'selected_value_sha256':s.sha(actual), 'scope':nodes[ident]['inputs']['scope'],
            'origin':'SUPPLIED_DERIVED_PARENT_PRODUCT_NOT_NEW_SCIENTIFIC_REGENERATION'}
        require(projected == expected, 'supplied parent projection content/meaning differs')

    refs = out['scenario_product_refs']
    require(type(refs) is dict and set(refs) == set(built['stage_ids']['human']), 'scenario reference inventory differs')
    for group, row in refs.items():
        s.exact(row, ('water','ecosystem','human','soil_feedback'), 'scenario reference group')
        for kind in ('water','ecosystem','human'):
            require(row[kind] == stage_ref(built['stage_ids'][kind][group]), 'scenario component reference differs')
        require(type(row['soil_feedback']) is dict and set(row['soil_feedback']) == set(built['stage_ids']['soil_feedback'][group]),
            'soil continuation reference inventory differs')
        for cell, ref in row['soil_feedback'].items():
            require(ref == stage_ref(built['stage_ids']['soil_feedback'][group][cell]), 'soil support stage reference differs')
        if complete:
            require(all(row[k] is not None for k in ('water','ecosystem','human'))
                and all(r is not None for r in row['soil_feedback'].values()), 'complete bounded scenario/soil branch required')
    if complete:
        require(parent is not None and owner_overlay is not None and frame_product is not None, 'complete source-derived parent/owner stages required')

    # Saved material budgets and physical support joins. Input builders below are
    # pure; no advance/solve/run_year method is used by the independent auditors.
    group_checks, soil_checks, partial_checks = {}, {}, {}
    if parent is not None:
        pipeline = bundle.module('pipeline')
        groups = pipeline.parent_units(bundle, recipe, parent)
        require(set(groups) == set(refs), 'actual parent scenario set differs from graph')
        audit = bundle.module('audit')
        view = workflow.materialise_consequences(bundle, recipe, out)
        require(view['materialised_without_scientific_reruns'] is True, 'consequence view provenance differs')
        for group, units in sorted(groups.items()):
            row = refs[group]
            decoded = codec.unpack(view['state']['results'][group])
            for kind, schema in (('water','diadem.workflow-water-stage.r11'),
                    ('ecosystem','diadem.workflow-ecosystem-stage.r11'),('human','diadem.workflow-human-stage.r11')):
                if row[kind] is not None:
                    value = resolve(row[kind])
                    require(value['schema'] == schema and value['scenario_id'] == group, 'scientific wrapper group/schema differs')
            for kind in ('water','human'):
                if row[kind] is not None:
                    component = decoded[kind]
                    require(component['source_binding_sha256'] == bundle.source_sha256 and component['scenario_id'] == group
                        and (kind != 'human' or component['source_status'] == 'WORKING NON-CANON'), 'saved component source/scenario/status differs')
            if row['water'] is not None:
                require(decoded['water']['production_ready'] is False and decoded['water']['canon_adopted'] is False,
                    'water result falsely claims production/canon authority')
                water_spec, water_joins = pipeline.water_inputs(bundle, recipe, units, parent['climate']['members'][group.split('/')[0]])
                require(decoded['water_joins'] == water_joins and all(decoded['water']['inputs'][key] == water_spec[key]
                    for key in ('events','network','initial','controls')), 'actual water parent/input joins differ')
            if row['ecosystem'] is not None:
                require(set(decoded['ecosystems']) == set(units), 'ecosystem support set differs')
                ecosystem = bundle.module('ecosystem')
                expected_joins = {}
                for cell, unit in sorted(units.items()):
                    eco = decoded['ecosystems'][cell]
                    require(eco['source_binding_sha256'] == bundle.source_sha256 and eco['scenario_id'] == group+'/'+cell
                        and eco['source_status'] == 'WORKING NON-CANON', 'ecosystem source/scenario/status differs')
                    spec = ecosystem.reference_spec(bundle.organic, bundle.fertility, unit)
                    expected_joins[cell] = spec.pop('reference_join')
                    multiplier = F(recipe['parameters']['plant_absorbed_light_multiplier'])
                    spec['events'] = tuple(replace(e, absorbed_par_j_m2=e.absorbed_par_j_m2*multiplier) for e in spec['events'])
                    spec['initial_state'] = ecosystem.state_to_record(bundle.organic, spec['initial_state'])
                    spec.update(source_binding_sha256=bundle.source_sha256, scenario_id=group+'/'+cell,
                        evidence=pipeline.E, source_status='SYNTHETIC TEST')
                    require(eco['inputs'] == ecosystem.plain(spec), 'actual native ecosystem stock/driver/law/source input differs')
                require(decoded['ecosystem_joins'] == expected_joins, 'actual ecosystem source joins differ')
            if all(row[k] is not None for k in ('water','ecosystem','human')):
                group_checks[group] = audit.group(bundle, recipe, parent, group, units, decoded)
            else:
                saved = {}
                if row['water'] is not None:
                    saved['water'] = audit.water(decoded['water'])
                if row['ecosystem'] is not None:
                    require(set(decoded['ecosystems']) == set(units), 'partial ecosystem support set differs')
                    saved['ecosystems'] = {c:audit.ecosystem(e) for c,e in decoded['ecosystems'].items()}
                partial_checks[group] = saved
            soil_checks[group] = {}
            for cell, ref in sorted(row['soil_feedback'].items()):
                if ref is not None:
                    require(row['ecosystem'] is not None and physical is not None, 'soil continuation lacks actual parent/ecosystem')
                    unit = units[cell]
                    formed = physical['soil_result']['state']['members'][unit['snow_id']][cell]
                    soil_checks[group][cell] = bundle.module('audit_soil').continuation(bundle, unit, formed,
                        decoded['ecosystems'][cell], resolve(ref))
    bundle.verify()
    return {'schema':'diadem.independent-workflow-audit.r11', 'status':'PASS',
        'source_sha256':bundle.source_sha256, 'recipe_sha256':s.sha(recipe), 'graph_recipe_sha256':s.sha(built['recipe']),
        'audit_mode':'COMPLETE_BOUNDED_GRAPH' if complete else 'EXACT_SAVED_STAGE_PREFIX',
        'completed_stages':count, 'registered_stages':len(order), 'artifact_count':len(store.records),
        'executed_stages':sum(row['producer_executed'] for row in state['rows'].values()),
        'unknown_stage_count':sum(row['product']['status']=='UNKNOWN' for row in state['rows'].values()),
        'graph_status':status, 'scenario_count':len(refs), 'complete_scenario_count':len(group_checks),
        'soil_continuation_count':sum(len(v) for v in soil_checks.values()), 'group_checks':group_checks,
        'partial_checks':partial_checks, 'soil_checks':soil_checks, 'source_owner_overlays_checked':
            {'biology':owner_overlay is not None,'declared_world_frames':frame_product is not None,'geography':True},
        'scientific_producer_reruns':0, 'world_generator_complete':False,
        'limits':'Saved graph/dependency/account verification only; no production, canon adoption or scientific model replay.'}
