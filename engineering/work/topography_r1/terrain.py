"""Optimised evolving terrain over Physical's selected, unchanged R18 seed.

The seed's construction envelope stays byte-exact. Only a private native
consumer view substitutes the independently checked current state. Every child
retains its actual forcing, exact elapsed interval, material accounts and seed
lineage; it is not an R18 construction or an accepted whole-world terrain map.
"""
from copy import deepcopy
from fractions import Fraction as F
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace

from work.generator_upgrade_r18 import working
from work.generator_upgrade_r22 import terrain as previous
from work.geology_r1 import consumer as geology_consumer, accounts
from work.generator_upgrade_r28.preflight import clone
from work.generator_runtime_r12.store import Store
from . import provenance as p, kernels

consumer = SimpleNamespace(**dict(vars(geology_consumer),
    terrain=SimpleNamespace(trial=kernels.trial)))
consumer.terrain_step = clone(geology_consumer.terrain_step, terrain=consumer.terrain)

SCHEMA = 'diadem.evolving-terrain-state.topography-r1'
VIEW_SCHEMA = 'diadem.current-terrain-view.topography-r1'
DECISION = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-5/02_Working_Files/Physical_Inputs_R22/REPLACEMENT_TERRAIN_PARENT_DECISION_R1.json')
DECISION_SHA = '8eda6513bd1c33df45ff33b6468c1e89d2cb2ccf80aea6a0531e9774323e01e6'


def _decision():
    decision = json.loads(p.checked(DECISION, DECISION_SHA))
    if (decision['decision'] != 'SELECT_R18_DEFAULT_FINITE_GEOLOGY_AND_INITIAL_SURFACE_AS_WORKING_INTEGRATION_SEED'
            or decision['selected_parent']['alternative'] != 'DEFAULT'
            or decision['source_bindings']['selected_r18_input']['sha256'] != working.INPUT_SHA):
        raise ValueError('explicit current selected R18 DEFAULT seed decision required')
    return decision


def _native(value):
    _, native = consumer.regional.p.backend()
    return native.LandscapeState.from_dict(value)


def _geometry(state):
    result = {}
    for key, column in state.columns:
        lower = column.basal_elevation_m; layers = []
        for layer in column.layers:
            upper = lower+layer.bulk_volume_m3/column.area_m2
            layers.append({'material_id': layer.material_id, 'phase': layer.phase,
                'bottom_m': str(lower), 'top_m': str(upper), 'mass_kg': str(layer.mass_kg),
                'grain_density_kg_m3': str(layer.grain_density_kg_m3),
                'porosity': str(layer.porosity), 'evidence': layer.evidence})
            lower = upper
        result[key] = {'bottom_to_top': layers, 'surface_m': str(column.surface_m),
            'exposed_material': None if column.exposed is None else column.exposed.material_id,
            'finite_stock_exhausted': not layers, 'basal_elevation_m': str(column.basal_elevation_m)}
    return result


def _stocks(state):
    stocks = {}
    for _, column in state.columns:
        for layer in column.layers:
            mass, solid = stocks.get(layer.material_id, (F(), F()))
            stocks[layer.material_id] = (mass+layer.mass_kg, solid+layer.mass_kg/layer.grain_density_kg_m3)
    return stocks


def _balance(before, after, result, palette):
    consumer._state_palette(after, palette)
    if result['palette'] != palette:
        raise ValueError('terrain continuation changed its composition-bound palette')
    rows = result['receipt']['material_balances']; initial, final = _stocks(before), _stocks(after)
    if len({r['material_id'] for r in rows}) != len(rows) or {r['material_id'] for r in rows} != set(initial) | set(final):
        raise ValueError('terrain material balance inventory differs from native states')
    for row in rows:
        mid = row['material_id']
        for index, suffix in enumerate(('mass_kg', 'solid_m3')):
            a = accounts.quantity(row['initial_'+suffix]); b = accounts.quantity(row['final_'+suffix])
            exported = accounts.quantity(row['exported_'+suffix])
            if a != initial.get(mid, (F(), F()))[index] or b != final.get(mid, (F(), F()))[index] or a != b+exported:
                raise ValueError('native terrain material/solid stocks and exports do not close')
    expected = accounts.project_balances(rows, palette, accounts.TERRAIN_STAGES)
    if result['constituent_balances'] != expected:
        raise ValueError('terrain constituent account differs from actual native states')


def _binding():
    return {'topography_r1': p.identity(),
        'physical_decision': {'path': str(DECISION), 'sha256': DECISION_SHA}}


def _seal(body, binding, *, cache_hit=False, cache_key=None):
    if len(p.encoded(body)) > consumer.regional.p.parent.parent.shared.LIMIT:
        raise ValueError('bounded terrain continuation envelope exceeded')
    return {'schema': SCHEMA, 'binding': deepcopy(binding), 'body': deepcopy(body),
        'body_sha256': p.sha(body), 'execution': {'cache_hit': cache_hit, 'cache_key': cache_key,
            'cache_namespace': p.sha(binding), 'whole_diadem_year_verified': False,
            'physical_acceptance_granted': False, 'canon_changed': False}}


def from_seed(snapshot, clock):
    """Open the selected source-driven seed, without inventing an evolution dose."""
    decision = _decision(); science = consumer.verify(snapshot)
    selected = decision['selected_parent']; details = science['regional_input']
    if (details.get('alternative') != 'DEFAULT' or details.get('owner_input') != {'path': str(working.INPUT), 'sha256': working.INPUT_SHA}
            or science['context'] != {k: selected['context'][k] for k in science['context']}
            or science['source_status'] != 'WORKING NON-CANON'):
        raise ValueError('supplied snapshot is not the selected R18 DEFAULT working seed')
    consumer.regional.contract.exact(clock, {'calendar_id', 'seconds_per_year', 'origin', 'evidence', 'source_status'}, 'terrain integration clock')
    for field in ('calendar_id', 'evidence'):
        consumer.regional.contract.text(clock[field])
    if clock['origin'] != 'CONSTRUCTOR_RELATIVE_NO_WORLD_DATE' or clock['source_status'] != science['source_status']:
        raise ValueError('explicit compatible constructor-relative clock/status required; no world-date inference')
    consumer.columns._q(clock['seconds_per_year'], 'explicit seconds per numerical year', positive=True)
    state = _native(science['state'])
    if state.elapsed_years != 0:
        raise ValueError('R18 construction origin must be zero; supply evolved state through R22')
    geometry = _geometry(state)
    for key, point in science['supports'].items():
        if {k: geometry[key][k] for k in science['stratigraphy'][key]} != science['stratigraphy'][key]:
            raise ValueError('seed construction geometry differs from actual initial state')
        x, y = (consumer.columns._q(v, 'selected support coordinate') for v in point['xy_m'])
        frame = selected['frame']; origin = frame['first_centre_m']; step = frame['step_m']
        c, r = (x-origin[0])/step[0], (y-origin[1])/step[1]
        scope = selected['selection']
        if (r.denominator != 1 or c.denominator != 1 or not scope['row_start'] <= r < scope['row_stop']
                or not scope['column_start'] <= c < scope['column_stop'] or F(point['area_m2']) != F(frame['native_area_m2'])):
            raise ValueError('seed support is outside selected native public geometry')
    body = {'seed': deepcopy(snapshot), 'seed_scientific_sha256': snapshot['execution']['scientific_sha256'],
        'selection': {'decision_id': decision['id'], 'decision_sha256': DECISION_SHA,
            'parent_id': selected['parent_id'], 'alternative': 'DEFAULT', 'seed_role': selected['role']},
        'clock': deepcopy(clock), 'current_state': deepcopy(science['state']), 'current_geometry': geometry,
        'palette': deepcopy(details['palette']), 'elapsed_years': '0', 'elapsed_seconds': '0', 'history': []}
    envelope = _seal(body, _binding()); verify(envelope)
    return envelope


def _validate(envelope):
    """Read back lineage, native geometry and exact material accounts; no rerun."""
    consumer.regional.contract.exact(envelope, {'schema', 'binding', 'body', 'body_sha256', 'execution'}, 'R22 terrain envelope')
    if envelope['schema'] != SCHEMA or envelope['body_sha256'] != p.sha(envelope['body']):
        raise ValueError('terrain envelope schema/body binding differs')
    binding = envelope['binding']
    consumer.regional.contract.exact(binding, {'topography_r1', 'physical_decision'}, 'Topography R1 binding')
    p.verify(binding['topography_r1'])
    if binding['physical_decision'] != {'path': str(DECISION), 'sha256': DECISION_SHA}:
        raise ValueError('terrain selected-decision source binding differs')
    decision = _decision(); body = envelope['body']; seed = body['seed']; science = consumer.verify(seed)
    if body['seed_scientific_sha256'] != seed['execution']['scientific_sha256'] or body['selection']['decision_sha256'] != DECISION_SHA:
        raise ValueError('terrain seed/selected decision lineage differs')
    if science['regional_input'].get('alternative') != 'DEFAULT' or science['regional_input'].get('owner_input', {}).get('sha256') != working.INPUT_SHA:
        raise ValueError('terrain continuation has an unselected seed')
    if body['palette'] != science['regional_input']['palette']:
        raise ValueError('terrain current palette differs from selected finite geological seed')
    clock = body['clock']; year = consumer.columns._q(clock['seconds_per_year'], 'clock seconds per year', positive=True)
    if clock['origin'] != 'CONSTRUCTOR_RELATIVE_NO_WORLD_DATE' or clock['source_status'] != science['source_status']:
        raise ValueError('terrain clock origin/status changed')
    state = _native(science['state']); elapsed = F()
    if state.elapsed_years != 0 or not 0 <= len(body['history']) <= 8192:
        raise ValueError('bounded constructor-relative evolving terrain history required')
    for i, row in enumerate(body['history']):
        receipt = {k: v for k, v in row.items() if k != 'row_sha256'}
        forcing = row['forcing']; duration = consumer.columns._q(forcing['duration_years'], 'forward terrain interval', positive=True)
        if (row['row_sha256'] != p.sha(receipt) or row['index'] != i or row['initial_state_sha256'] != p.sha(state.as_dict())
                or row['forcing_sha256'] != p.sha(forcing) or F(row['start_years']) != elapsed
                or F(row['duration_years']) != duration or F(row['duration_seconds']) != duration*year):
            raise ValueError('terrain forcing/state/clock chain differs')
        after = _native(row['native_result']['state'])
        if after.elapsed_years != elapsed+duration or row['final_state_sha256'] != p.sha(after.as_dict()):
            raise ValueError('native terrain state clock advanced other than once')
        _balance(state, after, row['native_result'], body['palette'])
        state = after; elapsed += duration
    if (body['current_state'] != state.as_dict() or body['current_geometry'] != _geometry(state)
            or F(body['elapsed_years']) != elapsed or F(body['elapsed_seconds']) != elapsed*year):
        raise ValueError('current terrain geometry/state/clock differs from its actual history')
    if set(state.column_map) != set(science['supports']):
        raise ValueError('evolving terrain support inventory differs from seed')
    for key, column in state.columns:
        if column.area_m2 != F(science['supports'][key]['area_m2']):
            raise ValueError('evolving terrain changed support area')
    consumer._state_palette(state, body['palette'])
    if envelope['execution']['cache_namespace'] != p.sha(binding):
        raise ValueError('terrain cache namespace differs from source binding')
    return body, state


def verify(envelope):
    return _validate(envelope)[0]


def _fresh_sources(envelope):
    """Retain live source/owner-byte guards without reinterpreting private history."""
    p.verify(envelope['binding']['topography_r1'])
    _decision()
    science = envelope['body']['seed']['scientific']
    consumer.regional._owner_source(science['owner_source'])
    consumer.regional._owner_source(science['regional_input']['source_package'])
    if 'owner_input' in science['regional_input']:
        consumer.regional._owner_source(science['regional_input']['owner_input'])


def import_r22(envelope):
    """Explicit authenticated migration; selected seed and full history stay exact."""
    previous.verify(envelope)
    imported = _seal(envelope['body'], _binding())
    verify(imported)
    return imported


def cache_namespace(envelope):
    verify(envelope)
    return p.sha(envelope['binding'])


def original_erosion_laws(envelope):
    """Physical's exact original-phase K; mobile and settling laws stay supplied."""
    body = verify(envelope); science = body['seed']['scientific']
    reference = science['regional_input']['reference_runoff_m_year']
    def prop(name, value, unit, evidence):
        return {'name': name, 'value': value, 'unit': unit, 'evidence': evidence, 'status': science['source_status']}
    return [{'material_id': mid, 'phase': descriptor['phase'],
        'k_per_year': prop('erosion_coefficient_at_reference_runoff', descriptor['k_per_year'], '1/year', descriptor['evidence']),
        'reference_runoff_m_year': prop('reference_runoff', reference, 'm/year', descriptor['evidence'])}
        for mid, descriptor in sorted(body['palette'].items())]


def _advance(envelope, forcing, *, store=None, cache_root=None,
             _reuse_parent=True, _optimised_kernel=True):
    if type(_reuse_parent) is not bool or type(_optimised_kernel) is not bool:
        raise ValueError('internal comparison switches must be explicit booleans')
    body, before = _validate(envelope)
    parent_sha = p.sha(envelope)
    if not _reuse_parent:
        before = _native(body['current_state'])
    if cache_root is not None:
        if store is not None:
            raise ValueError('supply a terrain Store or cache root, not both')
        store = Store(Path(cache_root), p.sha(envelope['binding']))
    def unchanged_parent():
        if p.sha(envelope) != parent_sha:
            raise ValueError('authenticated terrain parent mutated during advance')

    duration = consumer.columns._q(forcing['duration_years'], 'terrain duration', positive=True)
    key = p.sha({'schema': SCHEMA, 'binding': p.sha(envelope['binding']),
        'parent': envelope['body_sha256'], 'forcing': p.sha(forcing)})
    if store is not None and (type(store) is not Store or store.namespace != p.sha(envelope['binding'])):
        raise ValueError('exact evolving-terrain source-bound Store required')
    result = None if store is None else store.get(key)
    cache_hit = result is not None
    if result is None:
        seed = body['seed']; science = deepcopy(seed['scientific'])
        science['state'] = deepcopy(body['current_state'])
        science['regional_input']['palette'] = deepcopy(body['palette'])
        # This is deliberately not emitted as an R18 snapshot. Native consumer
        # mathematics receives only the independently validated current view.
        private = {'scientific': science, 'execution': deepcopy(seed['execution'])}
        private_sha = p.sha(private)
        def checked_view(snapshot):
            if snapshot is not private or p.sha(snapshot) != private_sha:
                raise ValueError('private native current-state view mutated')
            unchanged_parent()
            if _reuse_parent:
                _fresh_sources(envelope)
            else:
                verify(envelope)
            return science
        def lineage(snapshot):
            return {**consumer._lineage(seed), 'r22_parent_state_sha256': p.sha(body['current_state']),
                'r22_parent_envelope_sha256': envelope['body_sha256']}
        source = consumer.terrain_step if _optimised_kernel else geology_consumer.terrain_step
        namespace = dict(source.__globals__, verify=checked_view, _lineage=lineage)
        method = FunctionType(source.__code__, namespace, source.__name__,
            source.__defaults__, source.__closure__)
        result = method(private, deepcopy(forcing))
    if (result.get('forcing_sha256') != p.sha(forcing) or result.get('r22_parent_state_sha256') != p.sha(body['current_state'])
            or result.get('r22_parent_envelope_sha256') != envelope['body_sha256']):
        raise ValueError('cached/native terrain result has a different actual parent or forcing')
    unchanged_parent()
    after = _native(result['state'])
    if after.elapsed_years != before.elapsed_years+duration:
        raise ValueError('terrain native continuation did not advance current clock exactly once')
    _balance(before, after, result, body['palette'])
    row = {'index': len(body['history']), 'initial_state_sha256': p.sha(before.as_dict()),
        'final_state_sha256': p.sha(after.as_dict()), 'start_years': str(before.elapsed_years),
        'duration_years': str(duration), 'duration_seconds': str(duration*F(body['clock']['seconds_per_year'])),
        'forcing_sha256': p.sha(forcing), 'forcing': deepcopy(forcing), 'native_result': deepcopy(result)}
    row['row_sha256'] = p.sha(row)
    following = deepcopy(body)
    following.update(current_state=after.as_dict(), current_geometry=_geometry(after),
        elapsed_years=str(after.elapsed_years), elapsed_seconds=str(after.elapsed_years*F(body['clock']['seconds_per_year'])))
    following['history'].append(row)
    child = _seal(following, envelope['binding'], cache_hit=cache_hit, cache_key=key)
    verify(child)
    unchanged_parent()
    if store is not None and not cache_hit:
        store.put(key, result)
    return child


def advance(envelope, forcing, *, store=None, cache_root=None):
    return _advance(envelope, forcing, store=store, cache_root=cache_root)


def view(envelope):
    body = verify(envelope); seed_science = body['seed']['scientific']
    context = deepcopy(seed_science['context'])
    context['snapshot_id'] = 'TOPOGRAPHY_R1_TERRAIN_CHILD_'+envelope['body_sha256'] if body['history'] else context['snapshot_id']
    context['scenario_id'] = _decision()['selected_parent']['integration_scenario_id']
    context['calendar_id'] = body['clock']['calendar_id']
    supports = {key: {**deepcopy(point), 'basal_elevation_m': geometry['basal_elevation_m'],
        'surface_m': geometry['surface_m'], 'exposed_material': geometry['exposed_material'],
        'finite_stock_exhausted': geometry['finite_stock_exhausted']}
        for key, point in seed_science['supports'].items() for geometry in [body['current_geometry'][key]]}
    return {'schema': VIEW_SCHEMA, 'context': context, 'seed_context': deepcopy(seed_science['context']),
        'supports': supports, 'state_sha256': p.sha(body['current_state']),
        'seed_scientific_sha256': body['seed_scientific_sha256'], 'envelope_sha256': envelope['body_sha256'],
        'elapsed_years': body['elapsed_years'], 'elapsed_seconds': body['elapsed_seconds'],
        'clock': deepcopy(body['clock']), 'source_status': seed_science['source_status'],
        'role': 'EVOLVED_WORKING_TERRAIN_CHILD' if body['history'] else 'SELECTED_WORKING_INITIAL_TERRAIN_SEED',
        'physical_acceptance_granted': False, 'whole_diadem_year_verified': False,
        'sea_vertical_registration': 'NOT_ASSERTED', 'world_date': None}
