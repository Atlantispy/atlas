"""Conservative exposed-mobile-layer hillside transaction.

The float face law requests BULK volume. Actual donor density/porosity converts
each top-down layer portion to mass. All faces share that layer proportionally
before any debit. A declared dyadic mass quantum bounds representation; every
unmoved residual remains in its original layer, including sub-quantum layers.
Full exhaustion is exact. Receipts preserve source fractions and constituents.
No weathering, rock movement, sorting, pore water or heat is inferred here.
"""
from dataclasses import dataclass, replace
from fractions import Fraction as F
import math

from work.geology_r1 import accounts, composite, consumer, native as g1

MAX_CELLS = 256
MAX_LAYERS = 8192
MAX_FACES = 2048
MAX_BITS = 8192


def q(value, name, *, positive=False):
    if type(value) not in (int, float, F):
        raise ValueError(name + ': explicit exact/finite quantity required')
    if type(value) is float and not math.isfinite(value):
        raise ValueError(name + ': nonfinite quantity')
    result = F(value)
    if result < 0 or (positive and result == 0):
        raise ValueError(name + ': physical range violated')
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > MAX_BITS:
        raise ValueError(name + ': unchanged native rational bound exceeded')
    return result


@dataclass(frozen=True)
class AllocationControls:
    mass_quantum_kg: F
    max_total_bulk_error_m3: F
    deposition_order: str
    evidence: str

    def __post_init__(self):
        quantum = q(self.mass_quantum_kg, 'mass quantum', positive=True)
        if quantum.numerator != 1 or quantum.denominator & (quantum.denominator - 1):
            raise ValueError('declared inverse-power-of-two mass quantum required')
        object.__setattr__(self, 'mass_quantum_kg', quantum)
        object.__setattr__(self, 'max_total_bulk_error_m3', q(
            self.max_total_bulk_error_m3, 'total bulk allocation error budget'))
        if self.deposition_order != 'SOURCE_CELL_LAYER_FACE_ASCENDING':
            raise ValueError('explicit supported bottom-to-top deposition order required')
        if type(self.evidence) is not str or not self.evidence.strip():
            raise ValueError('declared numerical controls need evidence')


@dataclass(frozen=True)
class TransferResult:
    state: object
    receipt: dict
    # Each after-layer maps to exact fractions of previous native source layers.
    layer_sources: dict


def native():
    return g1.ground_gate.backend()[1]


def exposed_mobile(column):
    """Actual contiguous mobile layers, surface first; never through a cap."""
    result = []
    for index in range(len(column.layers) - 1, -1, -1):
        layer = column.layers[index]
        if layer.phase != 'mobile_sediment':
            break
        result.append((index, layer))
    return tuple(result)


def hillside_view(state, cell_ids, grid, palette, deposited_porosity):
    tt = native()
    if type(state) is not tt.LandscapeState or not 0 < len(state.columns) <= MAX_CELLS:
        raise ValueError('bounded native state required')
    if (type(cell_ids) not in (tuple, list) or len(cell_ids) != grid.size
            or len(set(cell_ids)) != len(cell_ids) or set(cell_ids) != set(state.column_map)):
        raise ValueError('one declared row-major support per native column required')
    consumer._state_palette(state, palette)
    columns = state.column_map
    if any(c.area_m2 != F(grid.dx_m) * F(grid.dy_m) for c in columns.values()):
        raise ValueError('native support area and actual hillside grid differ')
    if sum(len(c.layers) for c in columns.values()) > MAX_LAYERS:
        raise ValueError('native connection finite layer bound exceeded')
    mobile = {l.material_id for c in columns.values() for l in c.layers
              if l.phase == 'mobile_sediment'}
    if (type(deposited_porosity) is not dict or not mobile <= set(deposited_porosity)
            or not set(deposited_porosity) <= set(palette)):
        raise ValueError('explicit receiving packing for every current mobile material required')
    packing = {mid: q(p, 'receiving porosity') for mid, p in deposited_porosity.items()}
    if not set(packing) <= set(palette) or any(p >= 1 for p in packing.values()):
        raise ValueError('receiving porosity must be less than one')
    expansion = F(1)
    for column in columns.values():
        for _, layer in exposed_mobile(column):
            ratio = (1 - layer.porosity) / (1 - packing[layer.material_id])
            expansion = max(expansion, ratio, 1 / ratio)
    z, stock = [], []
    errors = []
    for key in cell_ids:
        column = columns[key]
        bulk = sum((l.bulk_volume_m3 for _, l in exposed_mobile(column)), F())
        a, b = float(column.surface_m), float(bulk)
        if not math.isfinite(a) or not math.isfinite(b) or (bulk and b == 0):
            raise ValueError('actual hillside geometry/positive stock unrepresentable')
        z.append(a); stock.append(b)
        errors.append({'cell_id': key, 'height_error_m': str(F(a) - column.surface_m),
                       'stock_error_m3': str(F(b) - bulk)})
    # Enclose rather than round down the worst packing CFL multiplier.
    represented = float(expansion)
    if F(represented) < expansion:
        represented = math.nextafter(represented, math.inf)
    if not math.isfinite(represented):
        raise ValueError('packing expansion cannot be represented')
    return {'surface_m': z, 'available_bulk_m3': stock,
            'receiving_expansion_max': represented, 'representation': errors}


def _allocate(mass, weights, quantum):
    """Largest-remainder dyadic allocation, exact total and stable ID ties.

An exact sub-quantum remainder of an exhausted layer goes to the greatest
remaining deficit; this preserves stock, not an artificial extra source.
"""
    ideals = {key: mass * weight for key, weight in weights.items()}
    ticks = {key: value // quantum for key, value in ideals.items()}
    ranks = sorted(weights, key=lambda key: (-(ideals[key] - ticks[key] * quantum), key))
    whole = mass // quantum
    extra = int(whole - sum(ticks.values()))
    if not 0 <= extra <= len(ranks):
        raise ArithmeticError('proportional tick allocation failed')
    for key in ranks[:extra]:
        ticks[key] += 1
    result = {key: count * quantum for key, count in ticks.items()}
    residual = mass - sum(result.values(), F())
    if residual:
        key = min(weights, key=lambda key: (-(ideals[key] - result[key]), key))
        result[key] += residual
    if sum(result.values(), F()) != mass or any(v < 0 for v in result.values()):
        raise ArithmeticError('exact face mass allocation did not close')
    return result


def apply(state, cell_ids, faces, palette, deposited_porosity, controls, *,
          operation_id, start_year, duration_years, evidence):
    """One atomic exact transaction; does not advance the native clock.

Face requests are the finite outputs of the selected successor law. Source
indices refer to the immutable PRE-transaction state. Each arrival gets its
own layer; no lineage is merged to save space. The coupled driver commits
operation IDs/elapsed time only after accepting its entire trial.
"""
    tt = native()
    if type(state) is not tt.LandscapeState or not 0 < len(state.columns) <= MAX_CELLS:
        raise ValueError('bounded native state required')
    if type(controls) is not AllocationControls:
        raise ValueError('predeclared allocation controls required')
    for label, value in (('operation ID', operation_id), ('process evidence', evidence)):
        if type(value) is not str or not value.strip() or len(value) > 1024:
            raise ValueError('bounded explicit ' + label + ' required')
    start = q(start_year, 'start year')
    duration = q(duration_years, 'duration years', positive=True)
    if start != state.elapsed_years:
        raise ValueError('hillside transaction clock differs from native state')
    columns = state.column_map
    if (len(cell_ids) != len(columns) or len(set(cell_ids)) != len(cell_ids)
            or set(cell_ids) != set(columns)):
        raise ValueError('complete unique row-major native support required')
    if type(faces) not in (tuple, list) or len(faces) > MAX_FACES:
        raise ValueError('bounded face request list required')
    consumer._state_palette(state, palette)
    prepared = composite._prepare_palette(palette)
    if type(deposited_porosity) is not dict:
        raise ValueError('explicit receiving packing required')
    packing = {mid: q(p, 'receiving porosity') for mid, p in deposited_porosity.items()}
    if any(p >= 1 for p in packing.values()):
        raise ValueError('receiving porosity must be less than one')
    grouped, seen = {}, set()
    for face in faces:
        identity = face['id']
        if type(identity) is not str or not identity or len(identity) > 1024 or identity in seen:
            raise ValueError('unique bounded face identity required')
        seen.add(identity)
        donor, receiver = face['donor'], face['receiver']
        if (type(donor) is not int or not 0 <= donor < len(cell_ids)
                or (receiver is not None and (type(receiver) is not int
                    or not 0 <= receiver < len(cell_ids) or donor == receiver))):
            raise ValueError('invalid face endpoints')
        if receiver is None and not face.get('boundary_id'):
            raise ValueError('outward transfer requires a declared boundary port')
        volume = q(face['requested_bulk_m3'], 'requested face bulk volume')
        if volume:
            grouped.setdefault(cell_ids[donor], []).append((identity, face, volume))
    remaining = {key: list(c.layers) for key, c in columns.items()}
    incoming = {key: [] for key in columns}
    origins = {key: [[{'source_cell': key, 'source_layer_index': i,
                      'fraction_of_source_mass': F(1)}] for i in range(len(c.layers))]
               for key, c in columns.items()}
    events, source_rows = [], []
    error = F()
    exported = {}
    for donor in sorted(grouped):
        requests = sorted(grouped[donor], key=lambda row: row[0])
        demand = sum((v for _, _, v in requests), F())
        mobile = exposed_mobile(columns[donor])
        available = sum((l.bulk_volume_m3 for _, l in mobile), F())
        target = min(demand, available)
        weights = {identity: v / demand for identity, _, v in requests}
        left = target
        applied_bulk = F()
        for index, layer in mobile:
            if not left:
                break
            if layer.material_id not in packing:
                raise ValueError('missing explicit receiving porosity for transported material')
            density = layer.grain_density_kg_m3
            bulk_density = density * (1 - layer.porosity)
            reference_bulk = min(left, layer.bulk_volume_m3)
            reference_mass = reference_bulk * bulk_density
            full = reference_mass == layer.mass_kg
            mass = layer.mass_kg if full else (
                reference_mass // controls.mass_quantum_kg) * controls.mass_quantum_kg
            portions = _allocate(mass, weights, controls.mass_quantum_kg)
            # The sum of face discrepancies includes both total conversion and
            # proportional-allocation errors in original donor bulk units.
            layer_error = sum((abs(portions[k] - reference_mass * w) / bulk_density
                               for k, w in weights.items()), F())
            error = q(error + layer_error, 'cumulative allocation error')
            if error > controls.max_total_bulk_error_m3:
                raise ValueError('predeclared total bulk allocation error budget exceeded')
            if mass:
                residual = layer.mass_kg - mass
                if residual:
                    remaining[donor][index] = replace(layer, mass_kg=residual)
                    origins[donor][index][0]['fraction_of_source_mass'] = residual / layer.mass_kg
                else:
                    remaining[donor][index] = None
                    origins[donor][index] = None
            for identity, face, requested in requests:
                moved = portions[identity]
                if not moved:
                    continue
                receiver = None if face['receiver'] is None else cell_ids[face['receiver']]
                fraction = q(moved / layer.mass_kg, 'source mass fraction', positive=True)
                event = {'face_id': identity, 'source_cell': donor, 'receiver_cell': receiver,
                         'source_layer_index': index, 'source_initial_mass_kg': layer.mass_kg,
                         'material_id': layer.material_id, 'phase': layer.phase,
                         'source_evidence': layer.evidence, 'mass_kg': moved,
                         'solid_m3': moved / density, 'donor_bulk_m3': moved / bulk_density,
                         'grain_density_kg_m3': density, 'source_porosity': layer.porosity,
                         'deposited_porosity': packing[layer.material_id] if receiver is not None else None,
                         'fraction_of_source_mass': fraction,
                         'constituents': composite._project_mass(layer.material_id, moved, prepared),
                         'boundary_id': face.get('boundary_id'), 'operation_id': operation_id,
                         'start_year': start, 'duration_years': duration, 'evidence': evidence}
                events.append(event)
                if receiver is None:
                    row = exported.setdefault(layer.material_id, [F(), F()])
                    row[0] += moved; row[1] += moved / density
                else:
                    deposit = replace(layer, mass_kg=moved, porosity=packing[layer.material_id])
                    incoming[receiver].append(((donor, index, identity), deposit, event))
            applied_bulk += mass / bulk_density
            left -= reference_bulk
            if not full:
                break  # Never draw below any positive remainder or immobile cap.
        source_rows.append({'source_cell': donor, 'requested_bulk_m3': demand,
                            'available_bulk_m3': available, 'supply_scale': target / demand,
                            'limited_target_bulk_m3': target, 'applied_bulk_m3': applied_bulk})
    result_columns, layer_sources = [], {}
    for key in sorted(columns):
        kept = [(layer, origin) for layer, origin in zip(remaining[key], origins[key]) if layer is not None]
        for _, layer, event in sorted(incoming[key], key=lambda row: row[0]):
            event['receiver_layer_index'] = len(kept)
            kept.append((layer, [{'source_cell': event['source_cell'],
                                 'source_layer_index': event['source_layer_index'],
                                 'fraction_of_source_mass': event['fraction_of_source_mass']}]))
        layer_sources[key] = [origin for _, origin in kept]
        result_columns.append((key, replace(columns[key], layers=tuple(l for l, _ in kept))))
    if sum(len(c.layers) for _, c in result_columns) > MAX_LAYERS:
        raise ValueError('native connection layer bound exceeded; no history merging')
    after = tt.LandscapeState(tuple(result_columns), state.elapsed_years, state.applied_deposition_ids)
    source_closure = {(key, i): F() for key, c in columns.items() for i in range(len(c.layers))}
    for rows in layer_sources.values():
        for sources in rows:
            for origin in sources:
                source_closure[origin['source_cell'], origin['source_layer_index']] += q(
                    origin['fraction_of_source_mass'], 'retained exact lineage fraction')
    for event in events:
        if event['receiver_cell'] is None:
            source_closure[event['source_cell'], event['source_layer_index']] += event['fraction_of_source_mass']
    if any(value != 1 for value in source_closure.values()):
        raise ArithmeticError('per-source-layer exact retained/transferred/exported closure failed')
    consumer._state_palette(after, palette)
    before_stock, after_stock = tt._inventory(columns), tt._inventory(after.column_map)
    balances = []
    for mid in sorted(set(before_stock) | set(after_stock) | set(exported)):
        initial = before_stock.get(mid, (F(), F()))
        final = after_stock.get(mid, (F(), F()))
        out = exported.get(mid, (F(), F()))
        if any(initial[i] != final[i] + out[i] for i in (0, 1)):
            raise ArithmeticError('exact material/solid hillside balance failed')
        balances.append({'material_id': mid, 'initial_mass_kg': initial[0], 'initial_solid_m3': initial[1],
                         'exported_mass_kg': out[0], 'exported_solid_m3': out[1],
                         'final_mass_kg': final[0], 'final_solid_m3': final[1]})
    projected = accounts.project_balances(balances, palette, accounts.TERRAIN_STAGES)
    receipt = {'schema': 'diadem.native-hillside-material-transfer.r1',
               'source_status': 'WORKING NON-CANON', 'operation_id': operation_id,
               'start_year': start, 'duration_years': duration, 'native_clock_advanced': False,
               'sources': source_rows, 'transfers': events, 'global_material_balance': balances,
               'constituent_balances': projected, 'mass_quantum_kg': controls.mass_quantum_kg,
               'exact_source_layer_closure': True,
               'total_bulk_allocation_error_m3': error,
               'max_total_bulk_error_m3': controls.max_total_bulk_error_m3,
               'deposition_order': controls.deposition_order, 'controls_evidence': controls.evidence,
               'scope': 'DRY_EXPOSED_MOBILE_ONLY_NO_PHASE_CHANGE_NO_SORTING',
               'representation_scope': 'RELATIVE_TO_REPRESENTED_FACE_REQUESTS_NOT_TOTAL_PDE_ERROR'}
    return TransferResult(after, receipt, layer_sources)
