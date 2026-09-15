"""Prescribed fixed-snapshot finite geology; no tectonic dynamics prediction."""
from collections.abc import Mapping
from dataclasses import replace
from fractions import Fraction as F
import math

from work.generator_upgrade_r14 import provenance

SCHEMA = 'diadem.prescribed-geological-columns.r16'
STATUSES = {'WORKING NON-CANON', 'SYNTHETIC TEST'}
MAX_BITS, MAX_CELLS, MAX_EVENTS, MAX_LAYERS = 8192, 32, 256, 2048
COMMON = {'event_id', 'cell_id', 'kind', 'evidence', 'source_status'}
PAYLOAD = {'translate_base': {'displacement_m'}, 'emplace': {'layer'},
           'strip_to_elevation': {'surface_m'}}
LAYER = {'material_id', 'grain_density_kg_m3', 'porosity', 'phase', 'thickness_m', 'evidence'}


def _text(value, label):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(label+': bounded nonblank text required')
    return value


def _q(value, label, *, positive=False, nonnegative=False):
    if type(value) not in (int, float, F, str) or (type(value) is float and not math.isfinite(value)):
        raise ValueError(label+': explicit finite exact quantity required')
    if type(value) is str and (len(value) > 5000 or value != value.strip()):
        raise ValueError(label+': bounded exact number string required')
    try:
        result = F(value)
    except (ValueError, ZeroDivisionError, OverflowError) as error:
        raise ValueError(label+': invalid exact quantity') from error
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > MAX_BITS:
        raise ValueError(label+': 8192-bit exact arithmetic budget exceeded')
    if (positive and result <= 0) or (nonnegative and result < 0):
        raise ValueError(label+': outside admitted positive/nonnegative range')
    return result


def _sum(values, label):
    result = F()
    for value in values:
        result = _q(result+value, label)
    return result


def _surface(column):
    volume = _sum((_q(layer.bulk_volume_m3, 'layer bulk volume', positive=True)
                   for layer in column.layers), 'column bulk volume')
    return _q(column.basal_elevation_m+volume/column.area_m2, 'absolute column surface')


def _inventory(layers):
    result = {}
    for layer in layers:
        row = result.setdefault(layer.material_id, [F(), F()])
        row[0] = _q(row[0]+layer.mass_kg, 'material mass')
        row[1] = _q(row[1]+layer.mass_kg/layer.grain_density_kg_m3, 'material solid volume')
    return result


def _accounts(before, imported, exported, after):
    inventories = [_inventory(items) for items in (before, imported, exported, after)]
    rows = []
    for mid in sorted(set().union(*(set(inv) for inv in inventories))):
        values = [inv.get(mid, [F(), F()]) for inv in inventories]
        row = {'material_id': mid}
        for index, unit in enumerate(('mass_kg', 'solid_volume_m3')):
            for label, value in zip(('initial', 'external_import', 'export', 'final'), values):
                row[label+'_'+unit] = str(value[index])
            residual = _q(values[0][index]+values[1][index]-values[2][index]-values[3][index], 'material account residual')
            if residual:
                raise ArithmeticError('exact material/solid-volume account failed')
            row['residual_'+unit] = str(residual)
        rows.append(row)
    return rows


def build_columns(initial, events):
    """Return (new native-column mapping, plain receipt); never advances time.

    Events are applied in list order. Empty columns are explicitly exhausted
    finite basal supports, not unknown/infinite rock or implicit soil profiles.
    """
    _, tt = provenance.backend()
    provenance.verify_backend()
    if not isinstance(initial, Mapping) or not 1 <= len(initial) <= MAX_CELLS:
        raise ValueError('one to32 explicit native columns required')
    if type(events) is not list or len(events) > MAX_EVENTS:
        raise ValueError('bounded ordered event list required')
    columns, densities = dict(initial), {}

    def check_layer(layer):
        if type(layer) is not tt.Layer:
            raise ValueError('compatible native material Layer required')
        _text(layer.material_id, 'material identity'); _text(layer.evidence, 'material evidence')
        _q(layer.mass_kg, 'layer mass', positive=True)
        density = _q(layer.grain_density_kg_m3, 'grain density', positive=True)
        phi = _q(layer.porosity, 'porosity', nonnegative=True)
        if phi >= 1 or layer.phase not in {'bedrock', 'immobile_regolith', 'mobile_sediment', 'organic'}:
            raise ValueError('unsupported porosity/material phase')
        if densities.setdefault(layer.material_id, density) != density:
            raise ValueError('same material identity has conflicting grain density')
        _q(layer.bulk_volume_m3, 'layer bulk volume', positive=True)

    input_layers = 0
    for key, column in columns.items():
        _text(key, 'cell identity')
        if type(column) is not tt.Column or type(column.source_status) is not str or column.source_status not in STATUSES:
            raise ValueError('compatible native column with resolved working/synthetic status required')
        _q(column.area_m2, 'column area', positive=True); _q(column.basal_elevation_m, 'finite base elevation')
        if type(column.layers) is not tuple:
            raise ValueError('immutable bottom-to-top layer tuple required')
        input_layers += len(column.layers)
        if input_layers > MAX_LAYERS:
            raise ValueError('2048 total input/emplacement layers exceeded')
        for layer in column.layers:
            check_layer(layer)
        _surface(column)

    event_ids, records, imported_all, exported_all = set(), [], [], []
    for event in events:
        if type(event) is not dict or type(event.get('kind')) is not str or event['kind'] not in PAYLOAD:
            raise ValueError('explicit supported event kind required')
        kind = event['kind']
        if set(event) != COMMON | PAYLOAD[kind]:
            raise ValueError('event fields differ from prescribed schema')
        eid = _text(event['event_id'], 'event identity'); _text(event['evidence'], 'event evidence')
        key = _text(event['cell_id'], 'event cell identity')
        if eid in event_ids or key not in columns:
            raise ValueError('duplicate event identity or unknown target cell')
        event_ids.add(eid); before = columns[key]
        if type(event['source_status']) is not str or event['source_status'] not in STATUSES or event['source_status'] != before.source_status:
            raise ValueError('event/column source status unresolved or mismatched')
        old_surface = _surface(before); imported, exported = (), ()
        if kind == 'translate_base':
            shift = _q(event['displacement_m'], 'prescribed vertical displacement')
            after = replace(before, basal_elevation_m=_q(before.basal_elevation_m+shift, 'translated base'))
        elif kind == 'emplace':
            item = event['layer']
            if type(item) is not dict or set(item) != LAYER:
                raise ValueError('explicit emplacement layer fields required')
            for name in ('material_id', 'phase', 'evidence'):
                _text(item[name], 'emplacement '+name)
            thickness = _q(item['thickness_m'], 'emplaced thickness', positive=True)
            density = _q(item['grain_density_kg_m3'], 'emplaced density', positive=True)
            phi = _q(item['porosity'], 'emplaced porosity', nonnegative=True)
            if phi >= 1:
                raise ValueError('emplaced porosity must be below one')
            mass = _q(thickness*before.area_m2*density*(1-phi), 'external emplacement mass', positive=True)
            layer = tt.Layer(item['material_id'], mass, density, phi, item['phase'], item['evidence'])
            check_layer(layer); input_layers += 1
            if input_layers > MAX_LAYERS:
                raise ValueError('2048 total input/emplacement layers exceeded')
            after, imported = before.deposit(layer), (layer,)
        else:
            target = _q(event['surface_m'], 'requested exposure elevation')
            if target < before.basal_elevation_m or target > old_surface:
                raise ValueError('exposure target below finite base or above existing surface')
            depth, requested = _q(old_surface-target, 'requested stripping depth'), F()
            for layer in reversed(before.layers):
                if not depth:
                    break
                height = _q(layer.bulk_volume_m3/before.area_m2, 'finite layer thickness', positive=True)
                used = min(depth, height)
                amount = layer.mass_kg if used == height else _q(used*before.area_m2*layer.grain_density_kg_m3*(1-layer.porosity), 'partial stripping mass', positive=True)
                requested = _q(requested+amount, 'total stripping mass')
                depth = _q(depth-used, 'remaining stripping depth', nonnegative=True)
            if depth:
                raise ValueError('exposure target has no finite material construction')
            after, removal = before.strip_mass(requested)
            if removal['unmet_mass_kg'] or removal['mass_residual_kg'] or _surface(after) != target:
                raise ArithmeticError('exact finite exposure target/account failed')
            exported = removal['removed_layers']
        new_surface = _surface(after)
        ledger = _accounts(before.layers, imported, exported, after.layers)
        records.append({'event': dict(event), 'old_base_elevation_m': str(before.basal_elevation_m),
            'new_base_elevation_m': str(after.basal_elevation_m), 'old_surface_m': str(old_surface),
            'new_surface_m': str(new_surface), 'surface_change_m': str(_q(new_surface-old_surface, 'surface change')),
            'exhausted': not after.layers, 'exposed_material': after.exposed.material_id if after.exposed else None,
            'material_accounts': ledger})
        imported_all.extend(imported); exported_all.extend(exported); columns[key] = after
    # The receipt is plain JSON, including event inputs that arrived as Fractions.
    def plain(value):
        if type(value) in (int, float, F):
            return str(_q(value, 'recorded exact quantity'))
        if type(value) is dict:
            return {key: plain(item) for key, item in value.items()}
        if type(value) is list:
            return [plain(item) for item in value]
        return value
    receipt = {'schema': SCHEMA, 'scope': 'PRESCRIBED_FIXED_SNAPSHOT; NO_TIME_OR_TECTONIC_DYNAMICS',
        'events': [plain(record) for record in records], 'event_order': [event['event_id'] for event in events],
        'material_accounts': _accounts([l for c in initial.values() for l in c.layers], imported_all,
                                       exported_all, [l for c in columns.values() for l in c.layers]),
        'limits': {'numeric_bits': MAX_BITS, 'cells': MAX_CELLS, 'events': MAX_EVENTS, 'total_layers': MAX_LAYERS},
        'columns': {key: {'initial_base_m': str(initial[key].basal_elevation_m),
            'final_base_m': str(column.basal_elevation_m), 'initial_surface_m': str(_surface(initial[key])),
            'final_surface_m': str(_surface(column)), 'exhausted': not column.layers,
            'exposed_material': column.exposed.material_id if column.exposed else None} for key, column in columns.items()},
        'exhausted_cells': sorted(key for key, column in columns.items() if not column.layers),
        'source_statuses': {key: column.source_status for key, column in columns.items()},
        'excluded': ['horizontal motion', 'lithification', 'isostasy', 'inferred material laws', 'time evolution']}
    provenance.verify_backend()
    return columns, receipt
