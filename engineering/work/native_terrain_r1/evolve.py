"""One continuing native state: hillslope, refreshed routing, native incision.

Bounded dry-material/supplied-surface-runoff reference only. Rock production,
weathering, failure, pore water, enthalpy and evolving climate are not inferred.
Every accepted interval uses two half steps; the rejected full trial is never
committed. Original material origins remain exact through both operators.
"""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction as F

from work.geology_r1 import consumer
from . import hillslope, materials as m, provenance as p
from .domain import Domain, channel_layer_sources

SCHEMA = 'diadem.connected-native-terrain.r1'
MAX_HISTORY = 256


def _seal(body, binding):
    body = p.plain(body)
    return {'schema': SCHEMA, 'binding': deepcopy(binding), 'body': body,
            'body_sha256': p.sha(body), 'source_status': 'WORKING NON-CANON',
            'physical_acceptance_granted': False, 'production_selected': False}


def _native(body):
    return m.native().LandscapeState.from_dict(body['state'])


def _lineage_check(body, state):
    initial = body['origins']
    if not set(body['exported_origin_mass_kg']) <= set(initial):
        raise ValueError('unknown exported material origin')
    totals = {key: m.q(F(body['exported_origin_mass_kg'].get(key, '0')), 'exported origin mass') for key in initial}
    if set(body['lineage']) != set(state.column_map):
        raise ValueError('continuing lineage support differs')
    for key, column in state.columns:
        rows = body['lineage'][key]
        if len(rows) != len(column.layers):
            raise ValueError('continuing lineage layer count differs')
        for layer, row in zip(column.layers, rows):
            total = F()
            for origin, value in row.items():
                mass = m.q(F(value), 'continuing origin mass', positive=True)
                if origin not in initial or initial[origin]['material_id'] != layer.material_id:
                    raise ValueError('continuing material origin differs')
                total += mass; totals[origin] += mass
            if total != layer.mass_kg:
                raise ArithmeticError('exact output layer lineage mass differs')
    if any(totals[key] != F(row['mass_kg']) for key, row in initial.items()):
        raise ArithmeticError('exact continuing origin retained/exported mass failed')


def validate(envelope):
    if (type(envelope) is not dict or envelope.get('schema') != SCHEMA
            or p.sha(envelope.get('body')) != envelope.get('body_sha256')):
        raise ValueError('native continuing-state envelope differs')
    p.verify(envelope['binding'])
    body = envelope['body']
    state = _native(body)
    consumer._state_palette(state, body['palette'])
    _lineage_check(body, state)
    history = body['history']
    if len(history) > MAX_HISTORY or len({r['operation_id'] for r in history}) != len(history):
        raise ValueError('bounded nonreplayed accepted history required')
    time = F(body['initial_elapsed_years'])
    parent = body['initial_state_sha256']
    water = allocation_error = F()
    for row in history:
        if F(row['start_year']) != time or row['parent_state_sha256'] != parent:
            raise ValueError('accepted history time/state chain differs')
        duration = m.q(F(row['duration_years']), 'accepted duration', positive=True)
        time += duration; parent = row['state_sha256']
        if len(row['substeps']) != 2 or sum((F(s['hillslope']['duration_years']) for s in row['substeps']), F()) != duration:
            raise ValueError('accepted split duration differs')
        for substep in row['substeps']:
            water += m.q(F(substep['surface_runoff_m3']), 'accepted surface runoff')
            allocation_error += m.q(F(substep['hillslope']['total_bulk_allocation_error_m3']), 'accepted allocation error')
            if F(substep['surface_water_exported_m3']) != water:
                raise ValueError('accepted cumulative water trajectory differs')
    if time != state.elapsed_years or parent != p.sha(body['state']):
        raise ValueError('accepted native state/time differs from history')
    if water != F(body['surface_water_exported_m3']) or allocation_error != F(body['cumulative_allocation_error_m3']):
        raise ValueError('continuing water/allocation total differs from accepted history')
    return body


def _initialise(state, palette, clock, source, parent):
    if type(state) is not m.native().LandscapeState:
        raise ValueError('actual shared native state required')
    consumer._state_palette(state, palette)
    if (type(clock) is not dict or not clock.get('calendar_id')
            or not clock.get('evidence') or not clock.get('seconds_per_year')):
        raise ValueError('explicit calendar and physical year binding required')
    m.q(F(clock['seconds_per_year']), 'seconds per model year', positive=True)
    lineage, origins = {}, {}
    state_hash = p.sha(state.as_dict())
    for key, column in state.columns:
        lineage[key] = []
        for index, layer in enumerate(column.layers):
            origin = p.sha([state_hash, key, index])
            origins[origin] = {'source_cell': key, 'source_layer_index': index,
                               'material_id': layer.material_id, 'phase': layer.phase,
                               'evidence': layer.evidence, 'mass_kg': str(layer.mass_kg)}
            lineage[key].append({origin: str(layer.mass_kg)})
    body = {'state': state.as_dict(), 'initial_state_sha256': state_hash,
            'initial_elapsed_years': str(state.elapsed_years), 'palette': deepcopy(palette),
            'clock': deepcopy(clock), 'source': deepcopy(source), 'parent': deepcopy(parent),
            'origins': origins, 'lineage': lineage, 'exported_origin_mass_kg': {},
            'surface_water_exported_m3': '0', 'receiver': None,
            'cumulative_allocation_error_m3': '0', 'history': []}
    return _seal(body, p.identity())


def from_synthetic(state, palette, clock, *, evidence, reference_runoff_m_year):
    if not evidence or any(c.source_status != 'SYNTHETIC TEST' for _, c in state.columns):
        raise ValueError('explicit synthetic native case and evidence required')
    reference = m.q(reference_runoff_m_year, 'explicit coefficient reference runoff', positive=True)
    return _initialise(state, palette, clock,
                       {'kind': 'EXPLICIT_SYNTHETIC_CASE_NOT_R18_FINE_SCALE_EVIDENCE',
                        'evidence': evidence, 'reference_runoff_m_year': str(reference)}, None)


def from_topography(envelope):
    """Verified one-way import; preserve the full old envelope as ancestry.

This does not replace any selected producer or upsample its geological support.
The executor later requires the imported native areas to match its process grid.
"""
    from work.topography_r1 import terrain
    body = terrain.verify(envelope)
    return _initialise(m.native().LandscapeState.from_dict(body['current_state']),
                       body['palette'], body['clock'],
                       {'kind': 'VERIFIED_TOPOGRAPHY_R1_CONTINUING_PARENT',
                        'evidence': envelope['body_sha256'],
                        'reference_runoff_m_year': body['seed']['scientific']['regional_input']['reference_runoff_m_year']}, envelope)


def _compose(lineage, mapping, transfers, exports):
    result = {}
    for key, rows in mapping.items():
        result[key] = []
        for sources in rows:
            row = {}
            for source in sources:
                for origin, mass in lineage[source['source_cell']][source['source_layer_index']].items():
                    value = F(mass) * source['fraction_of_source_mass']
                    if value:
                        row[origin] = m.q(row.get(origin, F()) + value, 'remapped origin mass')
            result[key].append(row)
    for source in transfers:
        for origin, mass in lineage[source['source_cell']][source['source_layer_index']].items():
            exports[origin] = m.q(F(exports.get(origin, 0)) + F(mass) * source['fraction_of_source_mass'],
                                  'cumulative exported origin mass')
    return result


@dataclass(frozen=True)
class UniformRunoff:
    """Explicit effective surface runoff, not guessed rainfall/infiltration."""
    metres_per_year: F
    evidence: str
    def __post_init__(self):
        object.__setattr__(self, 'metres_per_year', m.q(self.metres_per_year, 'effective runoff'))
        if type(self.evidence) is not str or not self.evidence.strip():
            raise ValueError('prescribed uniform runoff needs physical/scenario evidence')
    def volumes(self, state, duration):
        return {key: self.metres_per_year * duration * c.area_m2 for key, c in state.columns}


@dataclass(frozen=True)
class Acceptance:
    max_surface_error_m: F
    max_material_bulk_l1_error_m3: F
    max_allocation_error_m3: F
    max_halvings: int
    evidence: str
    def __post_init__(self):
        for name in ('max_surface_error_m', 'max_material_bulk_l1_error_m3', 'max_allocation_error_m3'):
            object.__setattr__(self, name, m.q(getattr(self, name), name))
        if type(self.max_halvings) is not int or not 0 <= self.max_halvings <= 12:
            raise ValueError('bounded explicit trial-halving limit required')
        if not self.evidence:
            raise ValueError('predeclared time-refinement acceptance evidence required')


class Executor:
    def __init__(self, domain, diffusivity_m2_year, critical_gradient, deposited_porosity,
                 allocation, runoff, erosion_laws, sediment_laws, channel_controls,
                 *, external_hillside_faces=(), receiver=None, evidence, disabled_processes):
        if type(domain) is not Domain or type(runoff) is not UniformRunoff:
            raise ValueError('bound whole domain and explicit supported runoff law required')
        required = {'weathering', 'uplift', 'rock_failure', 'pore_water', 'enthalpy', 'seasonal_forcing'}
        if set(disabled_processes) != required or not evidence:
            raise ValueError('explicit dry-case exclusions and scenario evidence required')
        self.domain = domain
        self.diffusivity = deepcopy(diffusivity_m2_year)
        self.critical = deepcopy(critical_gradient)
        self.packing = deepcopy(deposited_porosity)
        self.allocation, self.runoff = allocation, runoff
        self.erosion_laws, self.sediment_laws = tuple(erosion_laws), tuple(sediment_laws)
        self.channel_controls = channel_controls
        self.external_faces = deepcopy(tuple(external_hillside_faces))
        self.evidence = evidence
        self.disabled = tuple(sorted(disabled_processes))
        self.receiver = receiver
        if receiver is not None:
            from .receiver import FiniteReceiver
            if type(receiver) is not FiniteReceiver:
                raise ValueError('explicit supported finite receiver required')
            if any(c.receiver_id is None and c.outlet_elevation_m != receiver.outlet_control_m
                   for c in domain.connectors):
                raise ValueError('native outlet control differs from declared finite receiver')

    def _substep(self, state, palette, lineage, exports, duration, operation, water_before=F()):
        initial_route = self.domain.route(state, self.runoff.volumes(state, duration), duration)
        view = m.hillside_view(state, self.domain.cell_ids, self.domain.grid, palette, self.packing)
        faces = hillslope.face_requests(self.domain.grid, view['surface_m'], view['available_bulk_m3'],
                    self.diffusivity, float(duration), self.critical,
                    receiving_expansion_max=view['receiving_expansion_max'], external_faces=self.external_faces)
        moved = m.apply(state, self.domain.cell_ids, faces['faces'], palette, self.packing,
                        self.allocation, operation_id=operation, start_year=state.elapsed_years,
                        duration_years=duration, evidence=self.evidence)
        exports = deepcopy(exports)
        lineage = _compose(lineage, moved.layer_sources,
                           [r for r in moved.receipt['transfers'] if r['receiver_cell'] is None], exports)
        runoff = self.runoff.volumes(moved.state, duration)
        channel = self.domain.trial(moved.state, runoff, duration, self.erosion_laws,
                                    self.sediment_laws, self.channel_controls, evidence_id=self.evidence)
        mapping = channel_layer_sources(moved.state, channel)
        export_rows = [{'source_cell': row['source_cell'], 'source_layer_index': row['source_layer_index'],
                        'fraction_of_source_mass': row['mass_kg'] / moved.state.column_map[row['source_cell']].layers[row['source_layer_index']].mass_kg}
                       for row in channel.exports]
        lineage = _compose(lineage, mapping, export_rows, exports)
        after_route = self.domain.route(channel.state, self.runoff.volumes(channel.state, duration), duration)
        if channel.state.elapsed_years != state.elapsed_years + duration:
            raise ArithmeticError('coupled operators did not advance the calendar exactly once')
        topology = {'before_hillslope': initial_route['receivers'],
                    'before_channel': {row['cell_id']: row['receiver_id'] for row in channel.receipt['water_routing']},
                    'after_channel': after_route['receivers']}
        actual_water_export = sum(channel.receipt['water_exports_m3'].values(), F())
        if actual_water_export != sum(runoff.values(), F()):
            raise ArithmeticError('native channel did not export the exact supplied surface runoff')
        receipt = {'hillslope': moved.receipt, 'hillslope_cfl': faces['explicit_cfl'],
                   'face_requests': faces['faces'], 'diffusivity_m2_year': self.diffusivity,
                   'critical_gradient': self.critical, 'deposited_porosity': self.packing,
                   'geometry_representation': view['representation'], 'channel': channel.receipt,
                   'hillslope_duration_representation_error_years': F(float(duration)) - duration,
                   'topology': topology, 'surface_runoff_m3': sum(runoff.values(), F()),
                   'runoff_evidence': self.runoff.evidence, 'disabled_processes': self.disabled}
        water_after = water_before + actual_water_export
        receipt['surface_water_exported_m3'] = water_after
        return channel.state, lineage, exports, receipt

    @staticmethod
    def _difference(full, half):
        a, b = full.column_map, half.column_map
        surface = max(abs(a[key].surface_m - b[key].surface_m) for key in a)
        def bulk(column):
            result = {}
            for layer in column.layers:
                identity = (layer.material_id, layer.phase)
                result[identity] = result.get(identity, F()) + layer.bulk_volume_m3
            return result
        error = F()
        for key in a:
            av, bv = bulk(a[key]), bulk(b[key])
            error += sum((abs(av.get(mid, F()) - bv.get(mid, F())) for mid in set(av) | set(bv)), F())
        return surface, error

    def advance(self, envelope, duration_years, acceptance, *, operation_id):
        body = validate(envelope)
        if type(acceptance) is not Acceptance:
            raise ValueError('predeclared coupled acceptance required')
        by_law = {(law.material_id, law.phase): law for law in self.erosion_laws}
        reference = F(body['source']['reference_runoff_m_year'])
        for mid, descriptor in body['palette'].items():
            law = by_law.get((mid, descriptor['phase']))
            if (law is None or law.k_per_year.require('erosion_coefficient_at_reference_runoff', '1/year') != F(descriptor['k_per_year'])
                    or law.reference_runoff_m_year.require('reference_runoff', 'm/year') != reference):
                raise ValueError('original-phase erosion law differs from bound palette/reference runoff')
        if (type(operation_id) is not str or not operation_id or
                any(row['operation_id'] == operation_id for row in body['history'])):
            raise ValueError('unique accepted operation ID required; no replay')
        requested = m.q(duration_years, 'requested duration', positive=True)
        duration = requested
        initial = _native(body)
        water_before = F(body['surface_water_exported_m3'])
        rejected = []
        for refinement in range(acceptance.max_halvings + 1):
            args = (initial, body['palette'], body['lineage'], body['exported_origin_mass_kg'])
            try:
                full = self._substep(*args, duration, operation_id + '/full', water_before)
                first = self._substep(*args, duration / 2, operation_id + '/a', water_before)
                second = self._substep(first[0], body['palette'], first[1], first[2], duration / 2, operation_id + '/b',
                                       first[3]['surface_water_exported_m3'])
            except (m.native().TerrainStepTooLarge, hillslope.HillslopeStepTooLarge) as error:
                rejected.append({'duration_years': str(duration), 'reason': str(error), 'kind': type(error).__name__})
                duration /= 2
                continue
            surface, bulk = self._difference(full[0], second[0])
            topology_equal = (full[3]['topology']['after_channel'] == second[3]['topology']['after_channel'])
            topology_changed = any(not (row[3]['topology']['before_hillslope'] == row[3]['topology']['before_channel']
                                       == row[3]['topology']['after_channel'])
                                   for row in (full, first, second))
            allocation_error = sum((row[3]['hillslope']['total_bulk_allocation_error_m3'] for row in (first, second)), F())
            cumulative_error = F(body['cumulative_allocation_error_m3']) + allocation_error
            diagnostics = {'duration_years': duration, 'surface_error_m': surface,
                           'material_bulk_l1_error_m3': bulk, 'allocation_error_m3': allocation_error,
                           'topology_equal': topology_equal, 'within_operator_topology_change': topology_changed,
                           'cumulative_allocation_error_m3': cumulative_error}
            if (surface <= acceptance.max_surface_error_m and bulk <= acceptance.max_material_bulk_l1_error_m3
                    and cumulative_error <= acceptance.max_allocation_error_m3 and topology_equal and not topology_changed):
                state, lineage, exports, _ = second
                following = deepcopy(body)
                following.update(state=state.as_dict(), lineage=p.plain(lineage), exported_origin_mass_kg=p.plain(exports))
                following['surface_water_exported_m3'] = str(second[3]['surface_water_exported_m3'])
                following['cumulative_allocation_error_m3'] = str(cumulative_error)
                if self.receiver is not None:
                    solid = sum((F(mass) / F(body['palette'][body['origins'][origin]['material_id']]['grain_density_kg_m3'])
                                 for origin, mass in exports.items()), F())
                    following['receiver'] = p.plain(self.receiver.account(F(following['surface_water_exported_m3']), solid))
                following['history'].append({'operation_id': operation_id, 'start_year': initial.elapsed_years,
                    'requested_duration_years': requested, 'duration_years': duration,
                    'parent_state_sha256': p.sha(body['state']), 'state_sha256': p.sha(state.as_dict()),
                    'accepted_method': 'TWO_HALF_STEPS_FULL_TRIAL_DISCARDED', 'rejected_trials': rejected,
                    'acceptance': vars(acceptance), 'diagnostics': diagnostics,
                    'substeps': [first[3], second[3]], 'scenario_evidence': self.evidence})
                _lineage_check(following, state)
                if len(following['history']) > MAX_HISTORY:
                    raise ValueError('bounded accepted history exceeded; no silent truncation')
                p.verify(envelope['binding'])
                return _seal(following, envelope['binding'])
            rejected.append(p.plain(diagnostics))
            if not topology_equal or topology_changed:
                raise ValueError('routing topology event requires explicit handling; not a numerical residual')
            duration /= 2
        raise ValueError('coupled refinement budget exhausted; original state remains unmodified')
