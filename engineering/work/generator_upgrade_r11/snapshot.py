"""One deterministic typed snapshot graph; executable ports, not a catalogue.

Source/recipe/support changes invalidate descendants. Checkpoints are semantically
replayed before continuation; this correctness implementation is not a new cache
or performance programme. Producers remain responsible for physical validation.
"""
from copy import deepcopy
import hashlib
import json
import math
import re

CATEGORIES = ('plate_tectonics', 'geology', 'topography_topology', 'hydrology',
    'political_borders', 'settlements', 'populations', 'biomes', 'climate',
    'precipitation', 'plant_animal_ranges', 'soils_ground_conditions',
    'erosion_sediment_transport', 'seas_coastal_processes', 'resources_land_suitability',
    'land_use_agriculture', 'infrastructure_connectivity', 'natural_hazards')
KNOWN = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'}
STATUSES = KNOWN | {'UNKNOWN', 'CONFLICT', 'INCOMPLETE', 'Locked', 'Soft-locked',
    'Provisional', 'Review-only', 'Superseded'}
MAX_STAGES = 128
MAX_BYTES = 8*1024*1024
FRAME_FIELDS = ('world_id', 'snapshot_id', 'calendar_id', 'spatial_frame_id',
    'vertical_reference', 'scenario_id')


def text(value):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError('explicit bounded identity/evidence required')
    return value


def digest(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('exact lowercase SHA256 required')
    return value


def plain(value, depth=0):
    if depth > 48:
        raise ValueError('snapshot nesting bound exceeded')
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise ValueError('string JSON keys required')
        for item in value.values():
            plain(item, depth+1)
    elif type(value) is list:
        for item in value:
            plain(item, depth+1)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError('finite JSON values required')
    elif type(value) not in (str, int, bool, type(None)):
        raise ValueError('plain JSON values required')
    return value


def encoded(value):
    raw = json.dumps(plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('snapshot byte bound exceeded')
    return raw


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def exact(value, fields, what):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError('exact '+what+' fields required')
    return value


def context(value):
    exact(value, FRAME_FIELDS, 'snapshot identity')
    for item in value.values():
        text(item)
    return value


def port(value):
    exact(value, ('quantity', 'unit', 'support_id', 'temporal_support'), 'quantity port')
    for item in value.values():
        text(item)
    return value


def product(value, expected_context, expected_ports):
    exact(value, ('context', 'ports', 'values', 'status', 'source_status', 'evidence', 'unresolved'), 'product')
    if context(value['context']) != expected_context or value['ports'] != expected_ports:
        raise ValueError('product world/season/frame/quantity/support mismatch')
    if type(value['values']) is not dict or set(value['values']) != set(expected_ports):
        raise ValueError('complete output quantity inventory required')
    for item in expected_ports.values():
        port(item)
    if value['status'] not in ('MODELLED', 'SUPPLIED_CONSTRAINT', 'UNKNOWN') or value['source_status'] not in STATUSES:
        raise ValueError('explicit supported product status required')
    text(value['evidence'])
    if type(value['unresolved']) is not list or any(type(x) is not str or not x for x in value['unresolved']):
        raise ValueError('explicit unresolved input inventory required')
    if value['status'] == 'UNKNOWN':
        if not value['unresolved'] or any(v is not None for v in value['values'].values()):
            raise ValueError('unknown product must abstain with named gaps')
    elif value['source_status'] not in KNOWN or value['unresolved'] or any(v is None for v in value['values'].values()):
        raise ValueError('known product cannot hide unknown fields or source status')
    encoded(value)
    return value


def emission(ctx, ports, values, *, evidence, source_status='SYNTHETIC TEST', status='MODELLED', unresolved=()):
    return product({'context': deepcopy(ctx), 'ports': deepcopy(ports), 'values': deepcopy(values),
        'status': status, 'source_status': source_status, 'evidence': evidence,
        'unresolved': list(unresolved)}, ctx, ports)


def parse(recipe, registry):
    exact(recipe, ('schema', 'context', 'stages', 'required_categories', 'evidence'), 'snapshot recipe')
    if recipe['schema'] != 'diadem.snapshot-graph-recipe.r11':
        raise ValueError('R11 graph recipe required')
    context(recipe['context']); text(recipe['evidence'])
    required = recipe['required_categories']
    if (type(required) is not list or len(set(required)) != len(required)
            or any(k not in CATEGORIES for k in required) or not required):
        raise ValueError('explicit unique category target required')
    stages = recipe['stages']
    if type(stages) is not list or not 1 <= len(stages) <= MAX_STAGES:
        raise ValueError('bounded nonempty stage graph required')
    nodes = {}
    for stage in stages:
        exact(stage, ('stage_id', 'category', 'producer_id', 'producer_sha256', 'inputs',
            'dependencies', 'outputs', 'missing_inputs', 'mode', 'acceptance'), 'stage')
        ident = text(stage['stage_id'])
        if ident in nodes or stage['category'] not in CATEGORIES:
            raise ValueError('unique stage identity and known category required')
        if stage['mode'] not in ('GENERATED', 'SUPPLIED_CONSTRAINT'):
            raise ValueError('generation versus supplied constraint must be explicit')
        if (type(stage['inputs']) is not dict or type(stage['dependencies']) is not dict
                or type(stage['outputs']) is not dict or not stage['outputs']
                or type(stage['missing_inputs']) is not list):
            raise ValueError('explicit stage fields required')
        for gap in stage['missing_inputs']:
            text(gap)
        for name, out in stage['outputs'].items():
            text(name); port(out)
        for name, dep in stage['dependencies'].items():
            text(name)
            exact(dep, ('stage_id', 'output', 'port'), 'dependency')
            text(dep['stage_id']); text(dep['output']); port(dep['port'])
        exact(stage['acceptance'], ('status', 'evidence'), 'acceptance')
        if stage['acceptance']['status'] not in ('PENDING', 'BOUNDED_REFERENCE_VERIFIED', 'DOMAIN_ACCEPTED'):
            raise ValueError('explicit independent acceptance state required')
        text(stage['acceptance']['evidence'])
        name = text(stage['producer_id']); expected = digest(stage['producer_sha256'])
        if name not in registry:
            raise ValueError('no implemented registered producer: '+name)
        registered = registry[name]
        exact(registered, ('sha256', 'run', 'verify'), 'producer registration')
        if digest(registered['sha256']) != expected or not callable(registered['run']) or not callable(registered['verify']):
            raise ValueError('actual registered execution differs')
        registered['verify']()
        nodes[ident] = stage
    for stage in stages:
        for dep in stage['dependencies'].values():
            source = nodes.get(dep['stage_id'])
            if source is None or source['outputs'].get(dep['output']) != dep['port']:
                raise ValueError('declared dependency quantity/support differs or absent')
    order = []
    remaining = set(nodes)
    while remaining:
        ready = sorted(k for k in remaining if all(d['stage_id'] in order for d in nodes[k]['dependencies'].values()))
        if not ready:
            raise ValueError('cyclic snapshot graph; fixed-point solver must be an explicit producer')
        order.extend(ready); remaining.difference_update(ready)
    encoded(recipe)
    return nodes, order


def run(recipe, registry, *, stop_after=None, resume=None):
    recipe = deepcopy(recipe)
    nodes, order = parse(recipe, registry)
    until = len(order) if stop_after is None else stop_after
    if type(until) is not int or not 0 <= until <= len(order):
        raise ValueError('bounded complete-stage cursor required')
    recipe_sha = sha(recipe)
    def simulate(count):
        rows = {}
        for ident in order[:count]:
            stage = nodes[ident]
            missing = list(stage['missing_inputs']); values = {}; bindings = {}
            for name, dep in sorted(stage['dependencies'].items()):
                source = rows[dep['stage_id']]
                bindings[name] = source['product_sha256']
                if source['product']['status'] == 'UNKNOWN':
                    missing.append('dependency '+dep['stage_id']+': '+', '.join(source['product']['unresolved']))
                else:
                    values[name] = deepcopy(source['product']['values'][dep['output']])
            invocation = sha({'context': recipe['context'], 'stage': stage, 'dependency_products': bindings})
            registered = registry[stage['producer_id']]
            registered['verify']()
            if missing:
                result = emission(recipe['context'], stage['outputs'], {k: None for k in stage['outputs']},
                    evidence='Required input closure failed; no affected producer execution', source_status='UNKNOWN',
                    status='UNKNOWN', unresolved=missing)
                executed = False
            else:
                result = registered['run'](deepcopy(recipe['context']), deepcopy(stage['inputs']), values)
                product(result, recipe['context'], stage['outputs'])
                if ((stage['mode'] == 'SUPPLIED_CONSTRAINT' and result['status'] not in ('SUPPLIED_CONSTRAINT', 'UNKNOWN'))
                        or (stage['mode'] == 'GENERATED' and result['status'] == 'SUPPLIED_CONSTRAINT')):
                    raise ValueError('a supplied constraint cannot be counted as regeneration')
                executed = True
            registered['verify']()
            # A producer may retain/reuse its returned dictionary. Detach the
            # accepted product before any later producer can mutate that alias;
            # otherwise the stored product can cease to match its own hash.
            result = deepcopy(result)
            rows[ident] = {'invocation_sha256': invocation, 'product_sha256': sha(result),
                'producer_executed': executed, 'product': result}
        return {'completed_stages': count, 'rows': rows}
    if resume is not None:
        exact(resume, ('schema', 'recipe_sha256', 'state_sha256', 'state'), 'snapshot checkpoint')
        if resume['schema'] != 'diadem.snapshot-graph-checkpoint.r11' or resume['recipe_sha256'] != recipe_sha or resume['state_sha256'] != sha(resume['state']):
            raise ValueError('checkpoint binding differs')
        count = resume['state'].get('completed_stages')
        if type(count) is not int or not 0 <= count <= until or resume['state'] != simulate(count):
            raise ValueError('checkpoint semantic replay differs')
    state = simulate(until)
    closure = {}
    for category in CATEGORIES:
        required_stages = [k for k in order if nodes[k]['category'] == category]
        complete = bool(required_stages) and all(k in state['rows'] and state['rows'][k]['product']['status'] != 'UNKNOWN' for k in required_stages)
        accepted = complete and all(nodes[k]['acceptance']['status'] == 'DOMAIN_ACCEPTED' for k in required_stages)
        closure[category] = {'stage_ids': required_stages, 'required': category in recipe['required_categories'],
            'execution_complete': complete, 'domain_acceptance_declared': accepted,
            'generated_stage_ids': [k for k in required_stages if nodes[k]['mode'] == 'GENERATED'],
            'supplied_constraint_stage_ids': [k for k in required_stages if nodes[k]['mode'] == 'SUPPLIED_CONSTRAINT']}
    target_complete = all(closure[k]['execution_complete'] for k in recipe['required_categories'])
    return {'schema': 'diadem.snapshot-graph-result.r11', 'recipe_sha256': recipe_sha, 'state': state,
        'category_closure': closure, 'status': 'STOPPED' if until < len(order) else 'EXECUTED' if target_complete else 'INCOMPLETE',
        'whole_generator_implemented_claim': False, 'production_authorised': False, 'canon_changed': False,
        'acceptance_declarations_are_not_verified_authority': True}


def checkpoint(result):
    if result.get('schema') != 'diadem.snapshot-graph-result.r11':
        raise ValueError('R11 snapshot result required')
    return {'schema': 'diadem.snapshot-graph-checkpoint.r11', 'recipe_sha256': digest(result['recipe_sha256']),
        'state_sha256': sha(result['state']), 'state': deepcopy(result['state'])}


def invalidated(previous, current, registry):
    """Explain changed descendants; do not reuse old bytes or start a cache."""
    old, _ = parse(previous, registry); new, order = parse(current, registry)
    changed = set(old) ^ set(new)
    if previous['context'] != current['context']:
        changed.update(new)
    for ident in order:
        if old.get(ident) != new[ident] or any(dep['stage_id'] in changed for dep in new[ident]['dependencies'].values()):
            changed.add(ident)
    return sorted(changed)
