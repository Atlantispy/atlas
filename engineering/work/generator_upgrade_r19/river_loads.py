"""Exact receiving-water imports from an actual R18 terrain-step receipt.

This is an internal-account extractor, NOT execution authentication. The caller
must authenticate the producing R18 run, its forcing and native source binding.
Here the supplied lineage is required and retained, selected water routing and
represented sediment transfers are reconciled, and grain densities/compositions
are revalidated. Neither unselected connector choice nor the constitutive
settling/erosion calculation is rerun. A frozen-topology trial does not become
an adaptively accepted coupled step by passing these checks.

Imports contain surface-runoff water and grain-solid volume, never sediment
bulk volume or unspecified carried pore water. Projection is congruent and
well mixed; there is no selective sorting, dissolution or receiving-water law.
"""
from copy import deepcopy
from fractions import Fraction as F

from work.generator_upgrade_r16 import columns
from work.generator_upgrade_r18 import accounts, composite
from . import provenance as p


SCHEMA = 'diadem.receiving-water-river-imports.r19'
SCOPE = 'CONGRUENT_WELL_MIXED_COMPOSITE_TRANSFERS_NO_COMPONENT_SORTING'
LINEAGE = ('input_recipe_sha256', 'forcing_sha256',
           'r18_input_scientific_sha256', 'r18_regional_input_sha256',
           'r18_execution_sha256')
MAX_CELLS, MAX_LAYERS = 32, 2048
ROUTE = {'cell_id', 'connector_id', 'receiver_id', 'length_m',
         'outlet_elevation_m', 'initial_drop_m', 'slope',
         'through_volume_m3', 'discharge_m3_year', 'evidence'}
TRANSFER = {'cell_id', 'receiver_id', 'connector_id', 'source_cell',
            'source_layer_index', 'material_id', 'incoming_kg', 'deposited_kg',
            'outgoing_kg', 'transport_fraction',
            'exact_theoretical_transport_fraction',
            'transport_fraction_representation_error', 'constitutive_precision'}
BALANCE = {'material_id', 'initial_mass_kg', 'final_mass_kg', 'exported_mass_kg',
           'mass_residual_kg', 'initial_solid_m3', 'final_solid_m3',
           'exported_solid_m3', 'solid_residual_m3'}
LAYER = {'material_id', 'mass_kg', 'grain_density_kg_m3', 'porosity', 'phase', 'evidence'}


def _exact(row, keys, label):
    if type(row) is not dict or set(row) != keys:
        raise ValueError(label+': exact native fields required')


def _rows(value, limit, label):
    if type(value) is not list or len(value) > limit:
        raise ValueError(label+': bounded native list required')
    return value


def _text(value, label):
    columns._text(value, label)
    if value in {'UNKNOWN', 'INCOMPLETE', 'CONFLICT'}:
        raise ValueError(label+': unresolved identity')
    return value


def _q(value, label='native quantity', *, signed=False, positive=False):
    if type(value) is list:
        if (len(value) != 2 or any(type(v) is not int for v in value)
                or value[1] <= 0 or any(abs(v).bit_length() > 8192 for v in value)):
            raise ValueError(label+': bounded numerator/positive denominator required')
        value = F(*value)
    return columns._q(value, label, nonnegative=not signed, positive=positive)


def _sum(values):
    return columns._sum(values, 'bounded river-account sum')


def _sha(value):
    if (type(value) is not str or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('explicit lowercase SHA256 lineage required')
    return value


def _hashes(value):
    if type(value) is not dict or not 1 <= len(value) <= 64:
        raise ValueError('bounded native executed-source mapping required')
    for key, digest in value.items():
        _text(key, 'native source name')
        _sha(digest)
    return value


def _add(inventory, identity, mass, solid):
    previous = inventory.get(identity, (F(), F()))
    inventory[identity] = (_q(previous[0]+mass), _q(previous[1]+solid))


def _plain_stocks(inventory):
    return {key: {'mass_kg': str(values[0]), 'solid_volume_m3': str(values[1])}
            for key, values in sorted(inventory.items())}


def _layer(row, densities):
    _exact(row, LAYER, 'native material layer')
    mid = _text(row['material_id'], 'native material identity')
    if mid not in densities or _q(row['grain_density_kg_m3'], positive=True) != densities[mid]:
        raise ValueError('native grain density differs from composition-bound material')
    if _q(row['porosity']) >= 1 or row['phase'] not in composite.PHASES:
        raise ValueError('invalid native layer porosity/phase')
    _text(row['evidence'], 'native layer evidence')
    mass = _q(row['mass_kg'], positive=True)
    return mid, mass, _q(mass/densities[mid])


def _state(state, cells, surfaces, densities, end):
    _exact(state, {'schema', 'elapsed_years', 'columns', 'applied_deposition_ids',
                   'foundation_sources'}, 'native final state')
    if state['schema'] != 'diadem.layered-landscape-state.r1' or _q(state['elapsed_years']) != end:
        raise ValueError('native final-state schema/clock differs')
    _hashes(state['foundation_sources'])
    history = _rows(state['applied_deposition_ids'], 16384, 'deposition history')
    for identity in history:
        _text(identity, 'deposition history identity')
    if len(set(history)) != len(history):
        raise ValueError('duplicate deposition history')
    inventory, seen, count = {}, set(), 0
    for row in _rows(state['columns'], MAX_CELLS, 'native final columns'):
        _exact(row, {'column_id', 'column'}, 'native final column row')
        cell = _text(row['column_id'], 'column identity')
        if cell not in cells or cell in seen:
            raise ValueError('final column inventory differs from routing')
        seen.add(cell)
        column = row['column']
        _exact(column, {'schema', 'area_m2', 'basal_elevation_m', 'source_status', 'layers'}, 'material column')
        if (column['schema'] != 'diadem.material-column.r1'
                or column['source_status'] not in columns.STATUSES):
            raise ValueError('invalid final column schema/status')
        area, base = _q(column['area_m2'], positive=True), _q(column['basal_elevation_m'], signed=True)
        bulk = []
        for layer in _rows(column['layers'], MAX_LAYERS, 'native layers'):
            count += 1
            if count > MAX_LAYERS:
                raise ValueError('native total layer budget exceeded')
            mid, mass, solid = _layer(layer, densities)
            _add(inventory, mid, mass, solid)
            bulk.append(_q(solid/_q(1-_q(layer['porosity']), positive=True)))
        if _q(base+_q(_sum(bulk)/area), signed=True) != surfaces[cell]:
            raise ValueError('final material geometry differs from native surface receipt')
    if seen != cells:
        raise ValueError('final column inventory is incomplete')
    return inventory


def _water(receipt, outlet_receivers, duration):
    local = receipt['local_runoff_m3']
    if type(local) is not dict or not 1 <= len(local) <= MAX_CELLS:
        raise ValueError('1..32 local runoff cells required')
    local = {_text(k, 'runoff cell'): _q(v) for k, v in local.items()}
    cells = set(local)
    surfaces = []
    for name in ('initial_surfaces_m', 'final_surfaces_m'):
        values = receipt[name]
        if type(values) is not dict or set(values) != cells:
            raise ValueError('surface inventory differs from runoff cells')
        surfaces.append({k: _q(v, signed=True) for k, v in values.items()})
    initial, final = surfaces
    exports = receipt['water_exports_m3']
    if type(exports) is not dict or len(exports) > MAX_CELLS:
        raise ValueError('bounded external water exports required')
    exports = {_text(k, 'external outlet'): _q(v) for k, v in exports.items()}
    if type(outlet_receivers) is not dict or set(outlet_receivers) != set(exports):
        raise ValueError('exactly one receiver mapping per external outlet; no missing/extra outlet')
    for receiver in outlet_receivers.values():
        _text(receiver, 'receiving-water cell')
    routes, connectors = {}, set()
    for row in _rows(receipt['water_routing'], MAX_CELLS, 'selected water routes'):
        _exact(row, ROUTE, 'selected water route')
        cell, connector, target = row['cell_id'], row['connector_id'], row['receiver_id']
        _text(cell, 'route cell'); _text(connector, 'route connector')
        if cell not in cells or cell in routes or connector in connectors:
            raise ValueError('unknown/duplicate selected route')
        if target is not None and (type(target) is not str or target not in cells or target == cell):
            raise ValueError('unknown/self internal route receiver')
        _text(row['evidence'], 'connector evidence')
        if target is not None and row['outlet_elevation_m'] is not None:
            raise ValueError('internal route cannot carry an external outlet height')
        level = _q(row['outlet_elevation_m'], signed=True) if target is None else initial[target]
        drop = _q(initial[cell]-level, positive=True)
        if (_q(row['initial_drop_m'], positive=True) != drop
                or _q(row['slope'], positive=True) != _q(drop/_q(row['length_m'], positive=True))):
            raise ValueError('selected route geometry differs from supplied surfaces')
        routes[cell] = row
        connectors.add(connector)
    order = sorted(cells, key=lambda k: (-initial[k], k))
    through, actual_exports = dict(local), {}
    for cell in order:
        row = routes.get(cell)
        if row is None:
            if through[cell]:
                raise ValueError('positive runoff lacks an open selected route')
            continue
        if (_q(row['through_volume_m3']) != through[cell]
                or _q(row['discharge_m3_year']) != _q(through[cell]/duration)):
            raise ValueError('selected through-water/discharge account differs')
        target = row['receiver_id']
        if target is None:
            actual_exports[row['connector_id']] = through[cell]
        else:
            through[target] = _q(through[target]+through[cell])
    if (actual_exports != exports or _sum(local.values()) != _sum(exports.values())
            or _q(receipt['water_residual_m3'], signed=True) != 0):
        raise ValueError('native external water account does not close')
    return cells, initial, final, routes, exports


def _origins(erosion, cells, densities, start, end):
    if type(erosion) is not dict or erosion.get('schema') != 'diadem.layered-landscape-represented-transfer.r14':
        raise ValueError('actual R14 erosion receipt required')
    if (_q(erosion['start_year']) != start or _q(erosion['end_year']) != end
            or erosion['depositions'] != [] or erosion['persistent_arithmetic_bits'] != 8192):
        raise ValueError('native erosion interval/deposition/arithmetic contract differs')
    _hashes(erosion['foundation_executed_sources'])
    _text(erosion['retained_landscape_source'], 'retained landscape source')
    _sha(erosion['retained_landscape_sha256'])
    # These paired native records are emitted in the same removal order. R14's
    # numerical record supplies the original bottom-to-top layer index, which
    # the older native eroded-parcel encoding alone does not contain.
    parcels = _rows(erosion['eroded_parcels'], MAX_LAYERS, 'eroded parcels')
    records = _rows(erosion['numerical_representation'], MAX_LAYERS, 'R14 represented transfers')
    if len(parcels) != len(records):
        raise ValueError('erosion parcel/represented-transfer inventories differ')
    origins, inventory = {}, {}
    for parcel, record in zip(parcels, records):
        _exact(parcel, {'column_id', 'start_year', 'end_year', 'source_layer'}, 'eroded parcel')
        if type(record) is not dict:
            raise ValueError('native represented-transfer record required')
        cell, index = parcel['column_id'], record['source_layer_index']
        if (type(cell) is not str or cell not in cells or type(index) is not int
                or not 0 <= index < MAX_LAYERS or record['column_id'] != cell):
            raise ValueError('invalid original source cell/layer provenance')
        mid, mass, solid = _layer(parcel['source_layer'], densities)
        begin, finish = _q(parcel['start_year']), _q(parcel['end_year'])
        if (not start <= begin < finish <= end or record['material_id'] != mid
                or _q(record['applied_mass_kg']) != mass
                or _q(record['start_year']) != begin or _q(record['end_year']) != finish):
            raise ValueError('native eroded parcel differs from represented transfer')
        identity = (cell, index)
        if identity in origins:
            raise ValueError('duplicate unsegmented source-layer origin')
        origins[identity] = {'material_id': mid, 'mass': mass, 'parcel': parcel}
        _add(inventory, mid, mass, solid)
    return origins, inventory


def _sediment(receipt, routes, origins, densities):
    rows, used, exports, deposited, by_cell = {}, set(), [], {}, {}
    for row in _rows(receipt['sediment_transfers'], MAX_CELLS*MAX_LAYERS, 'sediment transfers'):
        _exact(row, TRANSFER, 'native sediment transfer')
        cell, source, index = row['cell_id'], row['source_cell'], row['source_layer_index']
        if type(cell) is not str or type(source) is not str or type(index) is not int:
            raise ValueError('explicit sediment route/source-layer identity required')
        origin, route = origins.get((source, index)), routes.get(cell)
        if (origin is None or route is None or row['material_id'] != origin['material_id']
                or row['receiver_id'] != route['receiver_id'] or row['connector_id'] != route['connector_id']):
            raise ValueError('sediment origin/selected-route identity differs')
        identity = (cell, source, index)
        if identity in rows:
            raise ValueError('duplicate per-route sediment-origin transfer')
        incoming, deposited_mass, outgoing = (_q(row[name], positive=name != 'deposited_kg')
            for name in ('incoming_kg', 'deposited_kg', 'outgoing_kg'))
        factor = _q(row['transport_fraction'], positive=True)
        theory = _q(row['exact_theoretical_transport_fraction'], positive=True)
        error = _q(row['transport_fraction_representation_error'], signed=True)
        if (factor > 1 or theory > 1 or _q(factor-theory, signed=True) != error
                or _q(incoming*factor) != outgoing or _q(deposited_mass+outgoing) != incoming
                or row['constitutive_precision'] != 'binary64 factor; exact represented mass split'):
            raise ValueError('represented sediment split/fraction account differs')
        rows[identity] = row
        mid = origin['material_id']
        _add(deposited, mid, deposited_mass, _q(deposited_mass/densities[mid]))
        by_cell[cell] = _q(by_cell.get(cell, F())+_q(outgoing/densities[mid]))
    for (source, index), origin in sorted(origins.items()):
        cell, incoming, local_deposited = source, origin['mass'], F()
        for _ in range(MAX_CELLS):
            identity = (cell, source, index)
            if identity not in rows or identity in used:
                raise ValueError('missing/cyclic sediment-origin route')
            used.add(identity)
            row = rows[identity]
            if _q(row['incoming_kg']) != incoming:
                raise ValueError('sediment hand-off mass differs between consecutive cells')
            local_deposited = _q(local_deposited+_q(row['deposited_kg']))
            incoming = _q(row['outgoing_kg'])
            if row['receiver_id'] is None:
                if _q(local_deposited+incoming) != origin['mass']:
                    raise ValueError('source-layer deposition/export account does not close')
                exports.append({'outlet_connector': row['connector_id'],
                    'outlet_source_cell': cell, 'source_cell': source, 'source_layer_index': index,
                    'material_id': origin['material_id'], 'mass_kg': str(incoming),
                    'solid_volume_m3': str(_q(incoming/densities[origin['material_id']])),
                    'fraction_of_eroded_mass': str(_q(incoming/origin['mass'])),
                    'source_erosion_parcel': deepcopy(origin['parcel']),
                    'external_transfer': deepcopy(row)})
                break
            cell = row['receiver_id']
        else:
            raise ValueError('sediment route exceeds native cell budget')
    if used != set(rows):
        raise ValueError('unreachable or duplicated sediment transfer')
    maximum = F()
    for cell, solid in by_cell.items():
        water = _q(routes[cell]['through_volume_m3'], positive=True)
        maximum = max(maximum, _q(solid/water))
    if _q(receipt['maximum_solid_liquid_flux_ratio']) != maximum:
        raise ValueError('reported solid/liquid flux ratio differs from represented exports')
    return exports, deposited


def _extract(result, outlet_receivers):
    """Return per-receiver exact stocks, export provenance and input lineage.

``outlet_receivers`` is an exact mapping of ALL selected external connector IDs
to nonblank receiving-cell IDs, including zero-water outlets. Several outlets
may share one receiver. The caller validates that receiving cells physically
exist and authenticates the producing result. Inputs are never modified.

Bounds mirror the native trial: 32 cells, 2048 layers/origins, 65536 transfer
rows, 8192-bit exact quantities; palette descriptors retain their 64-component
bound. Missing native keys, unresolved status and inconsistent accounts fail
closed. Lineage hashes are identifiers, not proof of execution.
"""
    if type(result) is not dict:
        raise ValueError('actual plain R18 terrain result required')
    lineage = {name: _sha(result[name]) for name in LINEAGE}
    if (result['source_status'] not in columns.STATUSES or result['constituent_scope'] != SCOPE
            or result['adapter_scope'] != 'R16_INTERFACE_WITH_EXACT_COMPOSITE_K_TO_UNCHANGED_R14_TRIAL'
            or result['whole_diadem_year_verified'] is not False):
        raise ValueError('R18 terrain scope/source status differs')
    _text(result['native_receipt_status_scope'], 'native status scope')
    receipt = result['receipt']
    if (type(receipt) is not dict or receipt.get('schema') != 'diadem.runoff-layered-sediment-trial.r14'
            or receipt['status'] != 'CONSERVATIVE_FROZEN_TOPOLOGY_TRIAL_NOT_COUPLED_ACCEPTANCE'
            or receipt['source_status'] != 'WORKING NON-CANON' or receipt['production_authorised'] is not False):
        raise ValueError('actual conservative R14 frozen-topology trial receipt required')
    _text(receipt['evidence_id'], 'native trial evidence')
    duration, start, end = _q(receipt['duration_years'], positive=True), _q(receipt['start_year']), _q(receipt['end_year'])
    if _q(start+duration) != end:
        raise ValueError('native terrain interval does not close')
    palette = result['palette']
    if type(palette) is not dict or not 1 <= len(palette) <= MAX_LAYERS:
        raise ValueError('bounded composition-bound palette required')
    densities = {mid: _q(composite._validated(mid, palette)['grain_density_kg_m3'], positive=True)
                 for mid in palette}
    cells, initial, final, routes, water = _water(receipt, outlet_receivers, duration)
    final_inventory = _state(result['state'], cells, final, densities, end)
    erosion = receipt['actual_R14_erosion_receipt']
    origins, eroded_inventory = _origins(erosion, cells, densities, start, end)
    if result['state']['foundation_sources'] != erosion['foundation_executed_sources']:
        raise ValueError('native final state and erosion source identities differ')
    # Preserve forcing/native records as lineage, without claiming to reexecute
    # the constitutive model or to authenticate a supplied source digest.
    forcings = _rows(erosion['forcings'], MAX_CELLS, 'native forcing receipts')
    if (any(type(row) is not dict or type(row.get('column_id')) is not str for row in forcings)
            or len(forcings) != len(cells) or {row['column_id'] for row in forcings} != cells):
        raise ValueError('one native forcing receipt per routed cell required')
    for forcing in forcings:
        _exact(forcing, {'column_id', 'discharge', 'slope', 'represented_rates_m_year'}, 'native forcing')
        route = routes.get(forcing['column_id'])
        for key, name, unit, source in (('discharge', 'discharge', 'm3/year', 'discharge_m3_year'),
                                         ('slope', 'hydraulic_slope', '1', 'slope')):
            prop = forcing[key]
            _exact(prop, {'name', 'value', 'unit', 'evidence', 'status'}, 'native forcing property')
            expected = _q(route[source]) if route is not None else F()
            # The native trial explicitly bridges its exact routed quantities
            # to binary64 forcing before erosion. Check that represented bridge,
            # not equality to an unrepresentable rational hydraulic input.
            if (prop['name'] != name or prop['unit'] != unit or prop['status'] != 'WORKING NON-CANON'
                    or _q(prop['value']) != _q(float(expected))):
                raise ValueError('native represented forcing differs from routed water/geometry')
            _text(prop['evidence'], 'native forcing evidence')
        rate_keys = set()
        for row in _rows(forcing['represented_rates_m_year'], MAX_LAYERS*4, 'native represented rates'):
            _exact(row, {'material_id', 'phase', 'rate'}, 'native represented rate')
            key = (_text(row['material_id'], 'rate material'), row['phase'])
            if row['phase'] not in composite.PHASES or key in rate_keys:
                raise ValueError('invalid/duplicate represented rate identity')
            rate_keys.add(key)
            _q(row['rate'])
    law_keys = set()
    for law in _rows(erosion['laws'], 16384, 'native material laws'):
        _exact(law, {'material_id', 'phase', 'k_per_year', 'reference_runoff_m_year'}, 'native material law')
        key = (_text(law['material_id'], 'erosion-law material'), law['phase'])
        if law['phase'] not in composite.PHASES or key in law_keys:
            raise ValueError('invalid/duplicate native erosion law')
        law_keys.add(key)
        for field, name, unit in (('k_per_year', 'erosion_coefficient_at_reference_runoff', '1/year'),
                                  ('reference_runoff_m_year', 'reference_runoff', 'm/year')):
            prop = law[field]
            _exact(prop, {'name', 'value', 'unit', 'evidence', 'status'}, 'native erosion property')
            if prop['name'] != name or prop['unit'] != unit or prop['status'] != result['source_status']:
                raise ValueError('native erosion property identity/status differs')
            _text(prop['evidence'], 'native erosion evidence')
            _q(prop['value'], positive=field == 'reference_runoff_m_year')
    export_parcels, deposited = _sediment(receipt, routes, origins, densities)
    exports = {}
    for parcel in export_parcels:
        _add(exports, parcel['material_id'], _q(parcel['mass_kg']), _q(parcel['solid_volume_m3']))
    balances = _rows(receipt['material_balances'], MAX_LAYERS, 'native material balances')
    by_material = {}
    for row in balances:
        _exact(row, BALANCE, 'native material balance')
        mid = _text(row['material_id'], 'account material')
        if mid not in densities or mid in by_material:
            raise ValueError('unknown/duplicate material balance')
        values = {name: _q(row[name], signed='residual' in name) for name in BALANCE-{'material_id'}}
        if values['initial_mass_kg'] <= 0:
            raise ValueError('native material account requires a positive initial stock')
        for stage in ('initial', 'final', 'exported'):
            if _q(values[stage+'_mass_kg']/densities[mid]) != values[stage+'_solid_m3']:
                raise ValueError('material mass/solid account has stale density')
        if (values['mass_residual_kg'] or values['solid_residual_m3']
                or _q(values['final_mass_kg']+values['exported_mass_kg']) != values['initial_mass_kg']
                or _q(values['final_solid_m3']+values['exported_solid_m3']) != values['initial_solid_m3']
                or (values['final_mass_kg'], values['final_solid_m3']) != final_inventory.get(mid, (F(), F()))
                or (values['exported_mass_kg'], values['exported_solid_m3']) != exports.get(mid, (F(), F()))):
            raise ValueError('native material final/export account does not close')
        by_material[mid] = values
    if (set(final_inventory) | set(exports) | set(eroded_inventory)) - set(by_material):
        raise ValueError('material balance omits a physical stock/transfer')
    erosion_seen = set()
    for row in _rows(erosion['global_material_balance'], MAX_LAYERS, 'native erosion balances'):
        mid = row['material_id']
        if mid not in by_material or mid in erosion_seen:
            raise ValueError('native erosion material inventory differs')
        erosion_seen.add(mid)
        for suffix, terrain_suffix, index in (('mass_kg', 'mass_kg', 0), ('solid_volume_m3', 'solid_m3', 1)):
            initial_stock, added, removed, remaining = (_q(row[name+'_'+suffix])
                for name in ('initial', 'deposited', 'eroded', 'final'))
            if (added or _q(row['residual_'+suffix], signed=True)
                    or _q(removed+remaining) != initial_stock
                    or initial_stock != by_material[mid]['initial_'+terrain_suffix]
                    or removed != eroded_inventory.get(mid, (F(), F()))[index]
                    or _q(remaining+deposited.get(mid, (F(), F()))[index]) != by_material[mid]['final_'+terrain_suffix]):
                raise ValueError('native erosion/transport material hand-off does not close')
    if erosion_seen != set(by_material):
        raise ValueError('missing native erosion material account')
    projected = accounts.project_balances(balances, palette, accounts.TERRAIN_STAGES)
    if projected != result['constituent_balances']:
        raise ValueError('supplied constituent balances differ from exact native projection')
    receivers = {}
    for outlet, volume in sorted(water.items()):
        target = outlet_receivers[outlet]
        receiver = receivers.setdefault(target, {'water_m3': F(), 'materials': {}, 'constituents': {}, 'outlets': [], 'parcels': []})
        receiver['water_m3'] = _q(receiver['water_m3']+volume)
        route = next(row for row in routes.values() if row['connector_id'] == outlet)
        receiver['outlets'].append({'connector_id': outlet, 'water_m3': str(volume), 'native_route': deepcopy(route)})
    for parcel in export_parcels:
        receiver = receivers[outlet_receivers[parcel['outlet_connector']]]
        mid, mass, solid = parcel['material_id'], _q(parcel['mass_kg']), _q(parcel['solid_volume_m3'])
        _add(receiver['materials'], mid, mass, solid)
        receiver['parcels'].append(parcel)
    for receiver in receivers.values():
        for mid, (mass, _) in sorted(receiver['materials'].items()):
            for unit, stock in composite.project_mass(mid, mass, palette).items():
                _add(receiver['constituents'], unit, _q(stock['mass_kg']), _q(stock['solid_volume_m3']))
        receiver['water_m3'] = str(receiver['water_m3'])
        receiver['materials'] = _plain_stocks(receiver['materials'])
        receiver['constituents'] = _plain_stocks(receiver['constituents'])
    lineage.update(terrain_result_sha256=p.sha(result), native_receipt_sha256=p.sha(receipt),
        native_erosion_receipt_sha256=p.sha(erosion),
        native_forcing_receipts=deepcopy(forcings), native_erosion_laws=deepcopy(erosion['laws']),
        native_foundation_sources=deepcopy(erosion['foundation_executed_sources']),
        retained_landscape_source=erosion['retained_landscape_source'],
        retained_landscape_sha256=erosion['retained_landscape_sha256'])
    return {'schema': SCHEMA, 'source_status': result['source_status'],
        'receivers': dict(sorted(receivers.items())), 'palette': deepcopy(palette),
        'lineage': lineage, 'constituent_balances': deepcopy(projected),
        'start_year': str(start), 'end_year': str(end), 'duration_years': str(duration),
        'total_water_m3': str(_sum(water.values())), 'total_material_exports': _plain_stocks(exports),
        'checks': ['selected-route geometry and exact water continuity',
                   'represented sediment splits and complete source-layer paths',
                   'native eroded parcels and represented-transfer provenance',
                   'final material geometry, fixed grain density and exact material/solid accounts',
                   'composition identity and recomputed constituent balances'],
        'execution_authenticated': False, 'native_trial_status': receipt['status'],
        'constituent_scope': SCOPE, 'pore_water_scope': receipt['pore_water'],
        'scope': 'EXTRACTION_ONLY_SURFACE_WATER_AND_GRAIN_SOLIDS; CALLER_AUTHENTICATES_EXECUTION_AND_RECEIVERS'}


def extract(result, outlet_receivers):
    """Extract exact receiver stocks; see module scope and ``_extract`` contract.

Malformed or inconsistent inputs raise ValueError. This function does not run
terrain physics, inspect source files or authenticate the producing execution.
"""
    try:
        return _extract(result, outlet_receivers)
    except (KeyError, TypeError, OverflowError, ZeroDivisionError) as error:
        raise ValueError('malformed or overbounded native river-load receipt: '+str(error)) from error
