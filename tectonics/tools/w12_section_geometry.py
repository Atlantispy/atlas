"""Exact column geometry from an already authenticated W12 reader result.

SPDX-License-Identifier: AGPL-3.0-only
The caller must obtain ``result`` through the native read-only reader. Structural
checks here are not authentication of arbitrary JSON. No native imports, stored
state changes, simulation, interpolation or inference of absolute elevation.

Physical mapping: compaction_columns.compaction_geometry stacks the native
CompactionState.parcels top-to-bottom, with bulk = grain + grain * void_ratio.
W03 binds area to strip width times cell width. Material cohorts are disjoint
phase inventories, not ordered geological layers (w03_workflow._inventory).
"""
from copy import deepcopy
import math


SCHEMA = 'atlas.w12-section-geometry.v1'
FIELDS = {'void_ratio': '1', 'porosity': '1',
          'bulk_thickness_m': 'm', 'grain_volume_m3': 'm3'}
_CURVES = ('downward_displacement_from_reference',
           'sediment_surface_change_up', 'reservoir_surface_change_up')


class SectionError(ValueError):
    """Unsupported reader structure, selection or unrepresentable geometry."""

    code = 'INVALID_SECTION'


def _require(condition, message):
    if not condition:
        raise SectionError(message)


def _mapping(value, name):
    _require(type(value) is dict, name + ' must be an object.')
    return value


def _text(value, name):
    _require(type(value) is str and bool(value.strip()), name + ' must be text.')
    return value


def _number(value, name, *, positive=False, nonnegative=False):
    _require(type(value) in (int, float), name + ' must be a finite number.')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    _require(finite, name + ' must be finite.')
    _require(not positive or value > 0, name + ' must be positive.')
    _require(not nonnegative or value >= 0, name + ' must be nonnegative.')
    return value


def _list(value, count, name):
    _require(type(value) is list and len(value) == count,
             name + ' has an unsupported shape.')
    return value


def _field(fields, name, shape, units=None, *, known=False, boolean=False):
    entry = _mapping(fields.get(name), name)
    spec = _mapping(entry.get('spec'), name + ' specification')
    recorded_shape = spec.get('shape')
    _require(type(recorded_shape) is list and all(type(n) is int for n in recorded_shape) and
             recorded_shape == shape and
             spec.get('dtype') == ('|b1' if boolean else '<f8'),
             name + ' has an unsupported shape or type.')
    if units is not None:
        _require(spec.get('units') == units, name + ' units differ.')
    if known:
        _require(spec.get('known') == 'all values known',
                 name + ' needs fully known native values.')
    values = _list(entry.get('values'), shape[0], name)
    rows = values if len(shape) == 2 else [values]
    for row in rows:
        _list(row, shape[-1], name)
        for value in row:
            if boolean:
                _require(type(value) is bool, name + ' needs a boolean mask.')
            else:
                _number(value, name)
    return values, spec


def build_section(result, *, field='void_ratio', cell_start=0, cell_stop=None):
    """Return physical parcel intervals below the current sediment surface.

    Accept only the inner, authenticated reader result, not its response envelope.
    ``cell_start:cell_stop`` selects contiguous original cells (stop exclusive).
    All native cells are preserved within the current <=64-cell reader envelope.
    Grain volume is m3 per parcel/cell, not volume per unit strip width. W04
    reference changes remain separate signed curves and never shift this datum.
    """
    _mapping(result, 'Result')
    _require(result.get('producer') == 'atlas-tectonics-column-assembly-v1' and
             result.get('route') == 'w04-support.v1' and
             result.get('source_status') == 'WORKING NON-CANON',
             'Only supported W12 column reader results can supply a section.')
    _require(type(field) is str and field in FIELDS, 'Unsupported section field.')
    provenance = _mapping(result.get('provenance'), 'Provenance')
    verified = _mapping(provenance.get('verified'), 'Reader verification')
    _require(all(verified.get(key) is True for key in
                 ('product', 'native_state', 'completed_output', 'source_runtime')),
             'An authenticated completed native reader result is required.')
    support = _mapping(result.get('support'), 'Support')
    _require(support.get('kind') == 'planar-strip', 'Only planar strip support is supported.')
    ids = support.get('cell_ids')
    _require(type(ids) is list and 0 < len(ids) <= 64, 'Native cell count is outside this reader envelope.')
    for value in ids:
        _text(value, 'Native cell ID')
    _require(len(set(ids)) == len(ids), 'Native cell IDs must be unique and ordered.')
    count = len(ids)
    stop = count if cell_stop is None else cell_stop
    _require(type(cell_start) is int and type(stop) is int and 0 <= cell_start < stop <= count,
             'Select a nonempty native cell interval within the saved support.')
    edges = _list(support.get('cell_edges_m'), count + 1, 'Cell edges')
    centres = _list(support.get('cell_centres_m'), count, 'Cell centres')
    width = _number(support.get('width_m'), 'Strip width', positive=True)
    for edge in edges:
        _number(edge, 'Cell edge')
    widths, areas = [], []
    for i, centre in enumerate(centres):
        _number(centre, 'Cell centre')
        dx = _number(edges[i+1] - edges[i], 'Cell width', positive=True)
        _require(edges[i] < centre < edges[i+1], 'Cell centres must lie inside their ordered edges.')
        widths.append(dx)
        areas.append(_number(width * dx, 'Cell area', positive=True))
    context = _mapping(result.get('context'), 'Context')
    frame = _text(support.get('frame_id'), 'Frame ID')
    datum = _text(support.get('depth_reference_id'), 'Source depth reference')
    native = _mapping(provenance.get('native_state_descriptor'), 'Native column descriptor')
    binding = _mapping(native.get('binding'), 'Native column binding')
    native_width = _number(native.get('reference_width_m'), 'Native strip width', positive=True)
    _require(native.get('schema') == 'atlas.w03-columns.v1' and native_width == width and
             context.get('spatial_frame_id') == frame and
             context.get('vertical_reference') == datum and binding.get('depth_reference_id') == datum,
             'The section support differs from its native column binding.')
    parcels = support.get('compaction_rows')
    _require(type(parcels) is list and 0 < len(parcels) <= 8192,
             'Native ordered compaction parcels are required.')
    parcel_ids = []
    for parcel in parcels:
        _mapping(parcel, 'Compaction parcel')
        parcel_ids.append(_text(parcel.get('parcel_id'), 'Parcel ID'))
        _text(parcel.get('source_id'), 'Parcel source')
        _mapping(parcel.get('parameters'), 'Parcel parameters')
        parts = parcel.get('components')
        _require(type(parts) in (list, tuple) and 0 < len(parts) <= 256,
                 'Each native parcel needs its grain components.')
    _require(len(set(parcel_ids)) == len(parcels), 'Native parcel IDs must be unique.')
    fields = _mapping(result.get('fields'), 'Fields')
    shape = [len(parcels), count]
    grain, _ = _field(fields, 'grain_volume_m3', shape, 'm3', known=True)
    void, _ = _field(fields, 'void_ratio', shape, '1', known=True)
    # Validate all source cells even when only a spatial slice is requested.
    tops, bottoms, selected_values = [], [], []
    accumulated = [0.] * count
    for solid_row, void_row in zip(grain, void):
        top, bottom, values = [], [], []
        for i, (solid, ratio) in enumerate(zip(solid_row, void_row)):
            _number(solid, 'Grain volume', positive=True)
            _number(ratio, 'Void ratio', nonnegative=True)
            pore = _number(solid * ratio, 'Pore volume', nonnegative=True)
            _require(not ratio or pore > 0, 'Pore volume underflows numerical range.')
            bulk = _number(solid + pore, 'Bulk volume', positive=True)
            height = _number(bulk / areas[i], 'Parcel thickness', positive=True)
            depth = _number(accumulated[i] + height, 'Parcel bottom depth', positive=True)
            _require(depth > accumulated[i], 'Parcel depth interval is unrepresentable.')
            top.append(accumulated[i]); bottom.append(depth)
            values.append({'void_ratio': ratio, 'porosity': ratio / (1 + ratio),
                           'bulk_thickness_m': height, 'grain_volume_m3': solid}[field])
            accumulated[i] = depth
        tops.append(top[cell_start:stop]); bottoms.append(bottom[cell_start:stop])
        selected_values.append(values[cell_start:stop])

    packed, packed_spec = _field(fields, 'support.values', [count, 8], ['Pa'] * 5 + ['m'] * 3)
    water_known, _ = _field(fields, 'support.reservoir_surface_known', [count], boolean=True)
    columns = _list(packed_spec.get('columns'), 8, 'W04 column specifications')
    w04 = _mapping(_mapping(provenance.get('native_descriptor'), 'Native support descriptor').get('native'),
                   'Native W04 support')
    _require(w04.get('schema') == 'atlas.w04-support-result.v1' and
             w04.get('depth_reference_id') == datum and w04.get('total_reference_result') is True and
             w04.get('feedback_applied') is False, 'Unsupported W04 reference or feedback semantics.')
    reference_time = _number(w04.get('reference_time_s'), 'W04 reference time')
    signed_curves = {}
    for index, name in enumerate(_CURVES, 5):
        spec = _mapping(columns[index], 'W04 curve specification')
        _require(spec.get('name') == name and spec.get('units') == 'm', 'Unsupported W04 curve column order.')
        if index == 7:
            _require(type(spec.get('known')) is dict and
                     spec['known'].get('mask_field') == 'support.reservoir_surface_known',
                     'Water surface change needs its native known mask.')
        signed_curves[name] = dict(spec=deepcopy(spec), unit='m', positive='down' if index == 5 else 'up',
            reference='change from native reference, not absolute elevation', reference_time_s=reference_time,
            values=[row[index] for row in packed[cell_start:stop]],
            known=water_known[cell_start:stop] if index == 7 else [True] * (stop-cell_start))
    return dict(schema=SCHEMA, status=result['source_status'],
        support=dict(kind='planar-strip', frame_id=frame, source_depth_reference_id=datum, width_m=width,
            cell_ids=ids[cell_start:stop], cell_edges_m=edges[cell_start:stop+1],
            cell_centres_m=centres[cell_start:stop], cell_widths_m=widths[cell_start:stop]),
        selection=dict(cell_start=cell_start, cell_stop=stop, source_cell_count=count,
            semantics='zero-based start-inclusive stop-exclusive; native cells; no interpolation or decimation'),
        vertical=dict(quantity='depth below current sediment surface', unit='m', positive='down',
            datum='current sediment surface', absolute_elevation_available=False),
        parcel_order='native compaction_rows top-to-bottom; not material cohort order',
        parcels=deepcopy(parcels), top_depth_m=tops, bottom_depth_m=bottoms,
        field=dict(name=field, unit=FIELDS[field], values=selected_values,
            known=[[True] * (stop-cell_start) for _ in parcels]),
        column_bulk_thickness_m=accumulated[cell_start:stop], signed_curves=signed_curves,
        geometry_formula='bulk_thickness_m = (grain_volume_m3 + grain_volume_m3 * void_ratio) / (strip_width_m * cell_width_m)',
        limitations=['Depth is relative to each current sediment surface; no absolute terrain elevation is supplied.',
            'Parcel components may be mixtures; material cohort inventories are not stacked layers.',
            'W04 curves are separate total changes from their reference; unknown water values retain packed placeholders.'])
