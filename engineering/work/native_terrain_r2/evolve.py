"""Bounded mass/origin successor of the unchanged connected physical case.

Integer-quantum approximation is explicit, conserved and budgeted. This does
not claim equivalence to the predecessor's ever-growing exact trajectory.
"""
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction as F

from work.geology_r1 import consumer
from work.native_terrain_r1 import evolve as old, hillslope, materials as m
from work.native_terrain_r1.domain import channel_layer_sources
from . import channel, numerics as n, provenance as p

SCHEMA = 'diadem.connected-native-terrain.r2'
MAX_HISTORY = old.MAX_HISTORY
UniformRunoff, Acceptance = old.UniformRunoff, old.Acceptance


def _seal(body, binding):
    body = p.plain(body)
    return {'schema': SCHEMA, 'binding': deepcopy(binding), 'body': body,
            'body_sha256': p.sha(body), 'source_status': 'WORKING NON-CANON',
            'physical_acceptance_granted': False, 'production_selected': False}


def _native(body):
    return m.native().LandscapeState.from_dict(body['state'])


def validate(envelope):
    from .migration import read_predecessor_control
    if (type(envelope) is not dict or envelope.get('schema') != SCHEMA
            or p.sha(envelope.get('body')) != envelope.get('body_sha256')):
        raise ValueError('numerical successor envelope differs')
    p.verify(envelope['binding'])
    body, policy = envelope['body'], p.policy()
    if body['numeric_policy'] != policy:
        raise ValueError('numerical policy differs; no widening or repin')
    state = _native(body)
    consumer._state_palette(state, body['palette'])
    old._lineage_check(body, state)
    if len(body['origins']) > policy['maximum_origins']:
        raise ValueError('bounded original-origin inventory exceeded')
    for descriptor in body['origins'].values():
        n.units(F(descriptor['mass_kg']))
    for _, column in state.columns:
        for layer in column.layers:
            n.units(layer.mass_kg)
    for rows in body['lineage'].values():
        for row in rows:
            for value in row.values():
                n.units(F(value))
    for value in body['exported_origin_mass_kg'].values():
        n.units(F(value))
    parent = body['parent']
    if parent['kind'] != 'VERIFIED_R1_NUMERICAL_MIGRATION':
        raise ValueError('verified preserved predecessor reference required')
    predecessor = read_predecessor_control(parent['predecessor'])
    prior, migration = predecessor['body'], parent['migration']
    if predecessor['schema'] != old.SCHEMA:
        raise ValueError('unsupported predecessor scientific envelope')
    base = body['continuation_base']
    old_time = F(*prior['state']['elapsed_years'])
    if (migration['predecessor'] != parent['predecessor']
            or migration['successor_initial_state_sha256'] != body['initial_state_sha256']
            or F(migration['initial_elapsed_years']) != old_time
            or F(body['initial_elapsed_years']) != old_time
            or base['surface_water_exported_m3'] != migration['prior_surface_water_exported_m3']
            or base['surface_water_exported_m3'] != prior['surface_water_exported_m3']
            or base['cumulative_allocation_error_m3'] != migration['prior_cumulative_allocation_error_m3']
            or base['cumulative_allocation_error_m3'] != prior['cumulative_allocation_error_m3']
            or base['numeric_l1_units'] != migration['numeric_l1_units']
            or F(migration['mass_quantum_kg']) != n.Q
            or F(migration['mass_l1_error_bound_kg']) != n.mass(base['numeric_l1_units'])
            or F(migration['minimum_mass_per_bulk_m3']) != F(body['minimum_mass_per_bulk_m3'])
            or F(migration['migration_bulk_l1_cap_m3']) != F(policy['migration_bulk_l1_allocation_bound_m3'])
            or F(migration['bulk_l1_error_bound_m3']) != n.mass(base['numeric_l1_units']) / F(body['minimum_mass_per_bulk_m3'])):
        raise ValueError('continuation baseline differs from verified migration and predecessor')
    for key, digest_key in (('origins', 'original_origin_inventory_sha256'), ('palette', 'palette_sha256'),
                            ('clock', 'clock_sha256'), ('source', 'source_sha256')):
        if body[key] != prior[key] or p.sha(body[key]) != migration[digest_key]:
            raise ValueError('original inventory/case binding differs after migration: ' + key)
    previous_count = parent['predecessor']['history_count']
    prefix_ids = migration['prefix_operation_ids']
    history = body['history']
    if (type(previous_count) is not int or previous_count < 0
            or type(prefix_ids) is not list or len(prefix_ids) != previous_count
            or any(type(value) is not str or not value for value in prefix_ids)
            or len(set(prefix_ids)) != previous_count
            or previous_count + len(history) > MAX_HISTORY
            or set(prefix_ids) & {row['operation_id'] for row in history}
            or len({row['operation_id'] for row in history}) != len(history)):
        raise ValueError('bounded nonreplayed complete accepted history required')
    time, parent_hash = F(body['initial_elapsed_years']), body['initial_state_sha256']
    water = F(base['surface_water_exported_m3'])
    allocation_error = F(base['cumulative_allocation_error_m3'])
    error_units = base['numeric_l1_units']
    n.mass(error_units)
    for row in history:
        if F(row['start_year']) != time or row['parent_state_sha256'] != parent_hash:
            raise ValueError('accepted successor state/time chain differs')
        duration = m.q(F(row['duration_years']), 'accepted duration', positive=True)
        time += duration
        parent_hash = row['state_sha256']
        if (len(row['substeps']) != 2 or sum((F(s['hillslope']['duration_years'])
                for s in row['substeps']), F()) != duration):
            raise ValueError('accepted split duration differs')
        for substep in row['substeps']:
            water += m.q(F(substep['surface_runoff_m3']), 'accepted runoff')
            allocation_error += m.q(F(substep['hillslope']['total_bulk_allocation_error_m3']), 'hillside allocation')
            added = substep['numeric_compaction']['total_l1_units']
            n.mass(added)
            error_units += added
            if F(substep['surface_water_exported_m3']) != water:
                raise ValueError('accepted cumulative water differs')
        if row['diagnostics']['cumulative_numeric_l1_units'] != error_units:
            raise ValueError('accepted numeric approximation history differs')
    if (time != state.elapsed_years or parent_hash != p.sha(body['state'])
            or water != F(body['surface_water_exported_m3'])
            or allocation_error != F(body['cumulative_allocation_error_m3'])
            or error_units != body['numeric_l1_units']):
        raise ValueError('continuing state/time/water/error totals differ')
    conversion = m.q(F(body['minimum_mass_per_bulk_m3']), 'minimum mass per bulk', positive=True)
    if n.mass(error_units) / conversion > F(policy['new_cumulative_bulk_l1_allocation_bound_m3']):
        raise ValueError('predeclared cumulative numerical approximation bound exceeded')
    if n.mass(base['numeric_l1_units']) / conversion > F(policy['migration_bulk_l1_allocation_bound_m3']):
        raise ValueError('predeclared migration approximation bound exceeded')
    return body


def _compose(lineage, mapping, transfers, exports):
    """Preserve both original-origin margins and applied destination masses."""
    result = {key: [{} for _ in rows] for key, rows in mapping.items()}
    next_exports = deepcopy(exports)
    destinations, identities = defaultdict(lambda: defaultdict(F)), {}
    for key, rows in mapping.items():
        for index, sources in enumerate(rows):
            target = p.encoded(['layer', key, index]).decode('utf-8')
            identities[target] = (key, index)
            for source in sources:
                identity = source['source_cell'], source['source_layer_index']
                destinations[identity][target] += F(source['fraction_of_source_mass'])
    export_target = p.encoded(['export']).decode('utf-8')
    for source in transfers:
        identity = source['source_cell'], source['source_layer_index']
        destinations[identity][export_target] += F(source['fraction_of_source_mass'])
    expected = {(key, index) for key, rows in lineage.items() for index in range(len(rows))}
    if set(destinations) != expected:
        raise ValueError('every source layer requires its explicit complete destination account')
    error_units = 0
    for (key, index), targets in sorted(destinations.items()):
        source = lineage[key][index]
        rows = {origin: n.units(F(amount)) for origin, amount in source.items()}
        total = n.mass(sum(rows.values()))
        if sum(targets.values(), F()) != 1 or any(value < 0 for value in targets.values()):
            raise ValueError('source fractions must exactly close and remain nonnegative')
        columns = {target: n.units(total * fraction) for target, fraction in targets.items()}
        matrix, bound = n.transportation_matrix(rows, columns)
        error_units += bound
        for origin, allocated in matrix.items():
            for target, count in allocated.items():
                if not count:
                    continue
                if target == export_target:
                    next_exports[origin] = n.mass(n.units(F(next_exports.get(origin, '0'))) + count)
                else:
                    cell, layer_index = identities[target]
                    row = result[cell][layer_index]
                    row[origin] = n.mass(n.units(row.get(origin, F())) + count)
    exports.clear()
    exports.update(next_exports)
    return result, error_units


class Executor(old.Executor):
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
        lineage, hillside_origin_error = _compose(lineage, moved.layer_sources,
            [row for row in moved.receipt['transfers'] if row['receiver_cell'] is None], exports)
        runoff = self.runoff.volumes(moved.state, duration)
        trial = channel.trial(self.domain, moved.state, runoff, duration, self.erosion_laws,
            self.sediment_laws, self.channel_controls, evidence_id=self.evidence)
        mapping = channel_layer_sources(moved.state, trial)
        export_rows = [{'source_cell': row['source_cell'], 'source_layer_index': row['source_layer_index'],
            'fraction_of_source_mass': row['mass_kg'] / moved.state.column_map[row['source_cell']].layers[row['source_layer_index']].mass_kg}
            for row in trial.exports]
        lineage, channel_origin_error = _compose(lineage, mapping, export_rows, exports)
        after_route = self.domain.route(trial.state, self.runoff.volumes(trial.state, duration), duration)
        if trial.state.elapsed_years != state.elapsed_years + duration:
            raise ArithmeticError('calendar must advance exactly once')
        topology = {'before_hillslope': initial_route['receivers'],
            'before_channel': {row['cell_id']: row['receiver_id'] for row in trial.receipt['water_routing']},
            'after_channel': after_route['receivers']}
        actual_water_export = sum(trial.receipt['water_exports_m3'].values(), F())
        if actual_water_export != sum(runoff.values(), F()):
            raise ArithmeticError('native channel water differs from exact once-used runoff')
        channel_error = trial.receipt['numeric_compaction']['total_l1_units']
        receipt = {'hillslope': moved.receipt, 'hillslope_cfl': faces['explicit_cfl'],
            'face_requests': faces['faces'], 'diffusivity_m2_year': self.diffusivity,
            'critical_gradient': self.critical, 'deposited_porosity': self.packing,
            'geometry_representation': view['representation'], 'channel': trial.receipt,
            'hillslope_duration_representation_error_years': F(float(duration)) - duration,
            'topology': topology, 'surface_runoff_m3': sum(runoff.values(), F()),
            'runoff_evidence': self.runoff.evidence, 'disabled_processes': self.disabled,
            'surface_water_exported_m3': water_before + actual_water_export,
            'numeric_compaction': {'hillside_origin_l1_units': hillside_origin_error,
                'channel_origin_l1_units': channel_origin_error, 'channel_transfer_l1_units': channel_error,
                'total_l1_units': hillside_origin_error + channel_origin_error + channel_error,
                'mass_quantum_kg': n.Q,
                'scope': 'Additional represented-proposal allocation L1 bound; not global trajectory error'}}
        return trial.state, lineage, exports, receipt

    def advance(self, envelope, duration_years, acceptance, *, operation_id):
        from .migration import minimum_mass_per_bulk
        body = validate(envelope)
        if type(acceptance) is not Acceptance:
            raise ValueError('unchanged predeclared coupled acceptance required')
        if minimum_mass_per_bulk(self, body['palette']) != F(body['minimum_mass_per_bulk_m3']):
            raise ValueError('numerical error conversion differs from physical packing')
        if F(self.allocation.mass_quantum_kg) / n.Q != int(F(self.allocation.mass_quantum_kg) / n.Q):
            raise ValueError('hillside applied quantum is incompatible with successor units')
        by_law = {(law.material_id, law.phase): law for law in self.erosion_laws}
        reference = F(body['source']['reference_runoff_m_year'])
        for mid, descriptor in body['palette'].items():
            law = by_law.get((mid, descriptor['phase']))
            if (law is None or law.k_per_year.require('erosion_coefficient_at_reference_runoff', '1/year') != F(descriptor['k_per_year'])
                    or law.reference_runoff_m_year.require('reference_runoff', 'm/year') != reference):
                raise ValueError('original-phase physical law/reference differs')
        if (type(operation_id) is not str or not operation_id or
                operation_id in body['parent']['migration']['prefix_operation_ids'] or
                any(row['operation_id'] == operation_id for row in body['history'])):
            raise ValueError('unique accepted operation ID required')
        requested = m.q(duration_years, 'requested duration', positive=True)
        duration, initial = requested, _native(body)
        water_before, rejected = F(body['surface_water_exported_m3']), []
        for refinement in range(acceptance.max_halvings + 1):
            args = (initial, body['palette'], body['lineage'], body['exported_origin_mass_kg'])
            try:
                full = self._substep(*args, duration, operation_id + '/full', water_before)
                first = self._substep(*args, duration / 2, operation_id + '/a', water_before)
                second = self._substep(first[0], body['palette'], first[1], first[2], duration / 2,
                    operation_id + '/b', first[3]['surface_water_exported_m3'])
            except (m.native().TerrainStepTooLarge, hillslope.HillslopeStepTooLarge) as error:
                rejected.append({'duration_years': str(duration), 'reason': str(error), 'kind': type(error).__name__})
                duration /= 2
                continue
            surface, bulk = self._difference(full[0], second[0])
            topology_equal = full[3]['topology']['after_channel'] == second[3]['topology']['after_channel']
            topology_changed = any(not (row[3]['topology']['before_hillslope'] == row[3]['topology']['before_channel']
                == row[3]['topology']['after_channel']) for row in (full, first, second))
            allocation_error = sum((row[3]['hillslope']['total_bulk_allocation_error_m3'] for row in (first, second)), F())
            cumulative_error = F(body['cumulative_allocation_error_m3']) + allocation_error
            added_units = sum(row[3]['numeric_compaction']['total_l1_units'] for row in (first, second))
            total_units = body['numeric_l1_units'] + added_units
            new_bulk_bound = n.mass(total_units) / F(body['minimum_mass_per_bulk_m3'])
            if new_bulk_bound > F(body['numeric_policy']['new_cumulative_bulk_l1_allocation_bound_m3']):
                raise ValueError('predeclared cumulative numerical approximation budget exhausted')
            diagnostics = {'duration_years': duration, 'surface_error_m': surface,
                'material_bulk_l1_error_m3': bulk, 'allocation_error_m3': allocation_error,
                'topology_equal': topology_equal, 'within_operator_topology_change': topology_changed,
                'cumulative_allocation_error_m3': cumulative_error,
                'numeric_l1_units': added_units, 'cumulative_numeric_l1_units': total_units,
                'cumulative_additional_bulk_l1_bound_m3': new_bulk_bound}
            if (surface <= acceptance.max_surface_error_m and bulk <= acceptance.max_material_bulk_l1_error_m3
                    and cumulative_error <= acceptance.max_allocation_error_m3 and topology_equal and not topology_changed):
                state, lineage, exports, _ = second
                following = deepcopy(body)
                following.update(state=state.as_dict(), lineage=p.plain(lineage), exported_origin_mass_kg=p.plain(exports),
                    numeric_l1_units=total_units, surface_water_exported_m3=str(second[3]['surface_water_exported_m3']),
                    cumulative_allocation_error_m3=str(cumulative_error))
                if self.receiver is not None:
                    solid = sum((F(amount) / F(body['palette'][body['origins'][origin]['material_id']]['grain_density_kg_m3'])
                        for origin, amount in exports.items()), F())
                    following['receiver'] = p.plain(self.receiver.account(F(following['surface_water_exported_m3']), solid))
                following['history'].append({'operation_id': operation_id, 'start_year': initial.elapsed_years,
                    'requested_duration_years': requested, 'duration_years': duration,
                    'parent_state_sha256': p.sha(body['state']), 'state_sha256': p.sha(state.as_dict()),
                    'accepted_method': 'TWO_HALF_STEPS_FULL_TRIAL_DISCARDED', 'rejected_trials': rejected,
                    'acceptance': vars(acceptance), 'diagnostics': diagnostics,
                    'substeps': [first[3], second[3]], 'scenario_evidence': self.evidence})
                old._lineage_check(following, state)
                if len(following['history']) + following['parent']['predecessor']['history_count'] > MAX_HISTORY:
                    raise ValueError('whole accepted history bound exceeded; no silent truncation')
                p.verify(envelope['binding'])
                return _seal(following, envelope['binding'])
            rejected.append(p.plain(diagnostics))
            if not topology_equal or topology_changed:
                raise ValueError('routing topology event requires explicit handling; not a numerical residual')
            duration /= 2
        raise ValueError('coupled refinement budget exhausted; input unchanged')


def from_executor(executor):
    """Reuse the actual frozen case configuration, not reconstructed defaults."""
    if type(executor) is not old.Executor:
        raise ValueError('exact predecessor executor configuration required')
    return Executor(executor.domain, executor.diffusivity, executor.critical, executor.packing,
        executor.allocation, executor.runoff, executor.erosion_laws, executor.sediment_laws,
        executor.channel_controls, external_hillside_faces=executor.external_faces,
        receiver=executor.receiver, evidence=executor.evidence, disabled_processes=executor.disabled)
