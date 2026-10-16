"""Additive evolved spatial/funding transfer; no new funding or acceptance.

This consumes externally authenticated original funding and endpoint records.
It binds them to an adopted native transfer, preserves the original funding
snapshot/ID, and creates a new actual spatial owner. Historical exchange,
partition and acceptance validation belong to the workflow, not this seam.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as Q
import inspect
import hashlib
import json

import numpy as np

import native_transfer as N


_OWNER_MARKER = '    @classmethod\n    def from_saved(cls, funding, collar, definition, initial_record, initial_arrays, *, budget):\n'
_OWNER_ENTRY = '''    @classmethod
    def from_migrated_checkpoint(cls, **arguments):
        """Explicit evolved admission, never ordinary root restore or funding."""
        from spatial_transfer import admit_migrated_spatial_owner
        if cls is not PreparedSpatialOwner:
            raise TectonicsError('exact prepared spatial owner required')
        return admit_migrated_spatial_owner(**arguments)

'''
_INITIAL_OLD = '''    @property
    def initial_state(self):
        self._verify(); return self._initial
'''
_INITIAL_NEW = '''    @property
    def initial_state(self):
        self._verify()
        if self._initial is None:
            raise TectonicsError('migrated owner has no reseeded initial state; use its transferred endpoint')
        return self._initial
'''


def spatial_owner_source(source):
    """Exact minimal additive API patch; never modifies a live source file."""
    if (type(source) is not str or source.count(_OWNER_MARKER) != 1 or
            source.count(_INITIAL_OLD) != 1 or 'def from_migrated_checkpoint(' in source):
        raise N.TransferRefused('spatial owner differs from reviewed additive patch base')
    source = source.replace(_OWNER_MARKER, _OWNER_ENTRY+_OWNER_MARKER, 1).replace(_INITIAL_OLD, _INITIAL_NEW, 1)
    changes = (
        ('    def restore(self, record, arrays):',
         '    def restore(self, record, arrays, *, _validate_only=False):'),
        ("        if (_hash(mesh) != body['thermal_mesh_id'] or mesh['support_id'] != body['support_id'] or",
         "        if _validate_only:\n            from spatial_transfer import _stream_hash as mesh_hash\n"
         "        else:\n            mesh_hash = _hash\n"
         "        if (mesh_hash(mesh) != body['thermal_mesh_id'] or mesh['support_id'] != body['support_id'] or"),
        ('        result = self._issue(body)\n        expected = result.arrays()',
         '        if _validate_only:\n            from spatial_transfer import validate_projected_payload\n'
         "            return validate_projected_payload(self, body, arrays, record.get('state_id'))\n"
         '        result = self._issue(body)\n        expected = result.arrays()'),
        ('    def validate_parent(self, state, collar_state):\n'
         '        r = self._bound(state); self._collar._fields(collar_state)\n'
         "        if state.time_s != collar_state.native_state.descriptor()['time_s']:",
         '    def validate_parent(self, state, collar_state, *, _migrated_record=None):\n'
         '        if _migrated_record is None:\n'
         '            r = self._bound(state)\n            time_s = state.time_s\n'
         '        else:\n'
         '            from spatial_transfer import bound_migrated_record\n'
         '            r = bound_migrated_record(self, state, _migrated_record)\n'
         "            time_s = r['time_s']\n"
         '        self._collar._fields(collar_state)\n'
         "        if time_s != collar_state.native_state.descriptor()['time_s']:"),
    )
    for old, new in changes:
        if source.count(old) != 1:
            raise N.TransferRefused('spatial validation seam missing or ambiguous: '+old[:70])
        source = source.replace(old, new, 1)
    return source


_FUNDING = frozenset(('schema', 'funding_id', 'source', 'owner_id', 'collar_plan_id',
    'volume_map_id', 'native_initial_state_id', 'time_s', 'cells', 'component_keys',
    'cell_geometries', 'cell_accounts', 'source_accounts', 'exterior_remainder',
    'integration_request', 'allocation', 'projection', 'inherited_geometry_scope', 'authority'))
_FUNDING_OPTIONAL = ('component_registry', 'initial_source_plate_ids', 'basal_inventory', 'excluded_static_cells')
_OWNER = frozenset(('schema', 'owner_id', 'funding_id', 'collar_plan_id', 'source', 'grid_id',
    'initial_mesh_id', 'component_keys', 'native_initial_state_id', 'epoch_s', 'method',
    'heat_method', 'projection_allowances', 'conductivity_w_m_k', 'heat_capacity_j_kg_k',
    'source_fields', 'scope'))
_OWNER_OPTIONAL = ('component_registry', 'finite_stocks', 'initial_geometry', 'measure_policy')
_STATE = frozenset(('schema', 'state_id', 'owner_id', 'funding_id', 'time_s', 'intervals',
    'parent_state_id', 'collar_state_id', 'support_id', 'trajectory_id', 'trajectory',
    'grid_id', 'thermal_mesh_id', 'thermal_mesh', 'cells', 'projection_accounts'))
_STATE_OPTIONAL = ('finite_stock_state', 'measure_policy', 'native_material_quadrature_m3')
_STOCKS = ('volume_m3', 'mass_kg', 'enthalpy_j', 'source_kappa_mass_kg')
_STATE_HEADER = ('schema', 'state_id', 'owner_id', 'funding_id', 'time_s', 'intervals',
    'parent_state_id', 'collar_state_id', 'support_id', 'trajectory_id', 'grid_id', 'thermal_mesh_id')
TRANSFER_SCHEMA = 'atlas.evolved-spatial-funding-transfer.v2'


def _indexed(value):
    """Recognise only the exact loaded codec at the three logical hash seams."""
    import sys
    module = sys.modules.get('mesh_tables')
    if module is None:
        return False
    candidates = [value]
    if type(value) is dict:
        candidates.append(value.get('thermal_mesh'))
        if type(value.get('metadata')) is dict:
            candidates.append(value['metadata'].get('thermal_mesh'))
    return any(type(v) is module.CompactMesh for v in candidates)


def _stream_stats(value):
    """Exact ordinary canonical SHA/length and largest codec chunk; no full JSON."""
    digest, size, largest = hashlib.sha256(), 0, 0
    if _indexed(value):
        from spatial_indexed_patch import iter_logical_json
        for raw in iter_logical_json(value):
            digest.update(raw)
            size += len(raw)
            largest = max(largest, len(raw))
        return dict(sha256=digest.hexdigest(), nbytes=size), largest
    for text in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(value):
        raw = text.encode()
        digest.update(raw)
        size += len(raw)
        largest = max(largest, len(raw))
    return dict(sha256=digest.hexdigest(), nbytes=size), largest


def _stream_hash(value):
    return _stream_stats(value)[0]['sha256']


def _codec_work_bytes(value):
    """Peak streaming encoder stack/chunk, not a multiple of the whole mesh.

    Sorted dict item lists persist along the active recursion path. Escaping
    one Unicode string can produce six ASCII bytes per character, with both
    the encoded string and UTF-8 chunk live. Caller owns the source objects.
    """
    if _indexed(value) and type(value) is not dict:
        # The sealed codec separately funds each yielded row/support/header.
        return 65536
    if type(value) is dict:
        return 512+160*len(value)+max((_codec_work_bytes(k)+_codec_work_bytes(v)
                                      for k, v in value.items()), default=0)
    if type(value) in (tuple, list):
        return 512+max(map(_codec_work_bytes, value), default=0)
    if type(value) is str:
        return 512+12*len(value)
    if type(value) is int:
        return 256+value.bit_length()
    return 256


def _snapshot_id(body, bindings):
    return _stream_hash(dict(metadata=body, arrays={k: dict(shape=v['shape'], sha256=v['sha256'])
                                                   for k, v in bindings.items()}))


def snapshot_metadata_matches(snapshot, binding):
    """Match the complete immutable metadata, without materialising its mesh."""
    if type(snapshot).__module__ == 'spatial_indexed_patch':
        from spatial_indexed_patch import snapshot_metadata_matches as indexed_matches
        return indexed_matches(snapshot, binding)
    return (type(binding) is dict and set(binding) == {'sha256', 'nbytes'}
            and len(snapshot._metadata) == binding['nbytes']
            and hashlib.sha256(snapshot._metadata).hexdigest() == binding['sha256'])


def validate_projected_payload(owner, body, arrays, state_id):
    """Tail of actual restore: all preceding physical gates already ran.

    Use its exact projection, one field at a time, then the ordinary snapshot
    identity equation. No new state, mesh decode, or acceptance is produced.
    """
    from atlas_tectonics.integration_spatial_owner import _project, _q as decode
    from atlas_tectonics._validation import TectonicsError
    expected_names = set(owner._names) | {'volume_m3'}
    if set(arrays) != expected_names:
        raise TectonicsError('saved exact inventories and projected arrays disagree')
    bindings = _bindings(arrays)
    for name in sorted(expected_names):
        expected = np.fromiter((_project(decode(row['volume_m3'] if name == 'volume_m3'
            else row['exact'][name])) for row in body['cells']), dtype=np.float64, count=len(body['cells']))
        if not np.array_equal(arrays[name], expected):
            raise TectonicsError('saved exact inventories and projected arrays disagree')
    if _snapshot_id(body, bindings) != state_id:
        raise TectonicsError('saved exact inventories and projected arrays disagree')
    return dict(state_id=state_id, metadata=_stream_stats(body)[0], arrays=bindings)


def bound_migrated_record(owner, state, record):
    """Actual _bound gates plus exact complete-payload binding, no second decode."""
    from atlas_tectonics.integration_spatial_owner import SpatialExteriorState
    from atlas_tectonics._validation import TectonicsError
    owner._verify()
    if type(state) is not SpatialExteriorState or state._budget is not owner._budget:
        raise TectonicsError('issued current spatial state on the actual shared budget required')
    if (type(record) is not dict or record.get('state_id') != state.state_id
            or not snapshot_metadata_matches(state._snapshot,
                _stream_stats({k: v for k, v in record.items() if k != 'state_id'})[0])):
        raise TectonicsError('migrated spatial record differs from complete immutable state')
    if (record['owner_id'] != owner.owner_id or record['funding_id'] != owner._funding.funding_id
            or record['grid_id'] != owner._definition['grid_id']):
        raise TectonicsError('spatial state source/owner/grid differs')
    return record


def validate_current_parent(owner, state, spatial_state):
    """One accounted decode for actual parent validation, never two mesh trees."""
    import geometry_transfer as G
    from atlas_tectonics.regional_collar3d import RegionalCollarState
    from atlas_tectonics.integration_spatial_owner import SpatialExteriorState
    if type(state) is not RegionalCollarState or type(spatial_state) is not SpatialExteriorState:
        raise N.TransferRefused('actual current native/spatial state pair required')
    scratch = N._Allocation(owner._budget, 65536+G._fields_scratch_bytes(owner._collar, state)
        +G._json_decode_bytes(spatial_state._snapshot._metadata)
        +384*int(np.prod(owner._collar.cells)), category='spatial-transfer-parent-scratch')
    if type(spatial_state._snapshot).__module__ == 'spatial_indexed_patch':
        record_owner = spatial_state.indexed_record()
        record = record_owner.value
    else:
        record = spatial_state.record()
    owner.validate_parent(spatial_state, state, _migrated_record=record)
    assert scratch.size > 0


def _retained_snapshot(body, arrays, identity, metadata, allocation, budget):
    """Transfer-only immutable snapshot admission; identical ordinary wire bytes.

    Avoid the ordinary constructor's second complete identity serialisation.
    BytesIO has at most one output-sized growth buffer; getvalue plus the
    retained immutable copy and one array copy are explicitly temporary.
    """
    if _indexed(body):
        from spatial_indexed_patch import retained_snapshot
        return retained_snapshot(body, arrays, identity, metadata, allocation, budget)
    from io import BytesIO
    from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
    largest_array = max((a.nbytes for a in arrays.values()), default=0)
    scratch = N._Allocation(budget, 65536+3*metadata['nbytes']+largest_array,
                            category='spatial-transfer-codec-scratch')
    buffer = BytesIO()
    for text in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(body):
        buffer.write(text.encode())
    encoded = N._RecordBytes(buffer.getvalue(), allocation)
    buffer.close()
    fields = tuple((name, tuple(array.shape), N._RecordBytes(array.tobytes(order='C'), allocation))
                   for name, array in sorted(arrays.items()))
    snapshot = object.__new__(RegionalMechanicalSnapshot)
    for name, value in (('_metadata', encoded), ('_fields', fields), ('result_id', identity)):
        object.__setattr__(snapshot, name, value)
    if not snapshot_metadata_matches(snapshot, metadata) or _snapshot_id(body, _bindings(arrays)) != identity:
        raise N.TransferRefused('transferred snapshot changed during retained admission')
    assert scratch.size > 0
    return snapshot


def _q(value):
    from atlas_tectonics.integration_mimetic_heat import _q as decode, _enc
    result = decode(value)
    if _enc(result) != value:
        raise N.TransferRefused('noncanonical exact stock')
    return result


def _bindings(arrays):
    if type(arrays) is not dict or not arrays or len(arrays) > 330:
        raise N.TransferRefused('complete bounded spatial field dictionary required')
    import hashlib
    result = {}
    for name, array in arrays.items():
        if (type(name) is not str or not name or len(name) > 256 or type(array) is not np.ndarray
                or array.dtype != np.dtype(np.float64) or not array.dtype.isnative
                or not array.flags.c_contiguous):
            raise N.TransferRefused('exact native binary64 C-order spatial/funding payload required')
        result[name] = dict(dtype=array.dtype.str, shape=list(array.shape), nbytes=array.nbytes,
                           sha256=hashlib.sha256(memoryview(array).cast('B')).hexdigest())
    return result


def _record_identity(record, arrays, identity_key):
    body = {k: v for k, v in record.items() if k != identity_key}
    bindings = _bindings(arrays)
    if _snapshot_id(body, bindings) != N._digest(record[identity_key], identity_key):
        raise N.TransferRefused('historical '+identity_key+' payload identity differs')
    return body, bindings


def _funding_equations(record, arrays, collar, compatibility):
    """Recheck saved allocations/account equations, without re-funding geometry.

    Original source/containment certificates remain external authenticated
    evidence. These checks do NOT replace their independent acceptance.
    """
    N._keys(record, _FUNDING, _FUNDING_OPTIONAL, label='original funding')
    if record['schema'] != 'atlas.full-cell-collar-funding.v1':
        raise N.TransferRefused('unknown original funding schema')
    N._keys(record['source'], ('sphere_state_id', 'network_id', 'material_id', 'moving_id'), label='funding source')
    N._keys(record['integration_request'], ('max_cell_volume_width_m3', 'max_field_errors', 'max_leaves'),
            label='original funding request')
    N._keys(record['integration_request']['max_field_errors'], _STOCKS[1:], label='funding field error limits')
    old_collar = compatibility['plan_id_correspondence']['collar']['historical']
    if (record['collar_plan_id'] != old_collar or record['cells'] != list(collar.cells) or
            record['volume_map_id'] != collar.descriptor()['volume_map_id'] or
            record.get('component_registry') != collar.descriptor().get('component_registry')):
        raise N.TransferRefused('original funding geometry/collar lineage differs')
    cells = collar.cell_geometries()
    if record['cell_geometries'] != [cell.record() for cell in cells]:
        raise N.TransferRefused('original funded physical cell identities changed')
    keys = tuple(map(tuple, record['component_keys']))
    if keys != tuple(sorted(set(keys))) or len(record['cell_accounts']) != len(cells):
        raise N.TransferRefused('original funding component/cell coverage differs')
    if not N._REQUIRED_ARRAYS <= set(arrays) or set(arrays)-N._REQUIRED_ARRAYS:
        raise N.TransferRefused('original funding requires its exact six-field snapshot')
    ncomponents = len(collar._native._composition)
    for name, array in arrays.items():
        expected = (ncomponents, *collar.cells) if name == 'component_mass_kg' else collar.cells
        if array.shape != expected or not np.isfinite(array).all() or np.any(array < 0):
            raise N.TransferRefused('original funding field shape/positivity differs')
    for name in ('tracer:damage', 'tracer:accumulated_strain_ii', 'tracer:radial_plastic_kappa'):
        if np.any(arrays[name] != 0):
            raise N.TransferRefused('original fresh funding contains evolved incremental history')
    volumes = dict.fromkeys(keys, Q(0))
    projections = dict.fromkeys(_STOCKS[1:], Q(0))
    for box, row in zip(cells, record['cell_accounts'], strict=True):
        N._keys(row, ('cell_id', 'component_volumes_m3', 'component_bounds_m3',
            'component_max_deviation_m3', 'field_error_bounds', 'exact_minus_projected'), label='funded cell')
        if row['cell_id'] != box.cell_id or any(len(row[k]) != len(keys) for k in
                ('component_volumes_m3', 'component_bounds_m3', 'component_max_deviation_m3')):
            raise N.TransferRefused('funded component cell correspondence differs')
        values = tuple(map(_q, row['component_volumes_m3']))
        if sum(values, Q(0)) != box.volume_m3:
            raise N.TransferRefused('original component volumes do not fill their physical cell')
        for key, value, bounds, error in zip(keys, values, row['component_bounds_m3'],
                                            row['component_max_deviation_m3'], strict=True):
            if type(bounds) is not list or len(bounds) != 2:
                raise N.TransferRefused('complete original component enclosure required')
            low, high = map(_q, bounds)
            if not 0 <= low <= value <= high or _q(error) != max(value-low, high-value):
                raise N.TransferRefused('original component volume/enclosure equation differs')
            volumes[key] += value
        if set(row['field_error_bounds']) != set(projections) or set(row['exact_minus_projected']) != set(projections):
            raise N.TransferRefused('complete original field projections required')
        for name in projections:
            if not 0 <= _q(row['field_error_bounds'][name]) <= _q(record['integration_request']['max_field_errors'][name]):
                raise N.TransferRefused('original funding field error exceeds its bound')
            projections[name] += _q(row['exact_minus_projected'][name])
    sources, remainders = {}, {}
    for rows, target in ((record['source_accounts'], sources), (record['exterior_remainder'], remainders)):
        for row in rows:
            expected = (('patch_id', 'sublayer', 'source', 'debit', 'component_volume_max_deviation_m3',
                         'component_mass_projection') if target is sources else
                        ('patch_id', 'sublayer', 'radial_layer', 'geometry', 'geometry_volume_enclosure_m3', 'stocks'))
            N._keys(row, expected, label='original funding source account')
            key = row['patch_id'], row['sublayer']
            if key in target:
                raise N.TransferRefused('duplicate original funding source')
            target[key] = row
    if set(sources) != set(remainders) or not set(keys) <= set(sources):
        raise N.TransferRefused('original funding source/remainder coverage differs')
    basal = {key: dict.fromkeys(_STOCKS, Q(0)) for key in sources}
    if 'basal_inventory' in record:
        saved = record['basal_inventory']
        N._keys(saved, ('schema', 'base_funding_id', 'side', 'reservoirs', 'stocks', 'exact_debits',
                       'disjointness', 'pressure_work'), ('compartment_kind',), label='original basal funding')
        if saved.get('schema') != 'atlas.finite-basal-funding.v1' or 'excluded_static_cells' not in record:
            raise N.TransferRefused('complete original basal funding required')
        for row in saved['exact_debits']:
            key = tuple(row['source_key'])
            if key not in basal or set(row['exact']) != set(_STOCKS):
                raise N.TransferRefused('basal funding source/field coverage differs')
            for name in _STOCKS:
                amount = _q(row['exact'][name])
                if amount < 0:
                    raise N.TransferRefused('negative original basal debit')
                basal[key][name] += amount
    elif 'excluded_static_cells' in record:
        raise N.TransferRefused('unbound original finite exclusions')
    totals = dict.fromkeys(_STOCKS, Q(0))
    for key, row in sources.items():
        if set(row['source']) != set(_STOCKS) or set(row['debit']) != set(_STOCKS) or set(remainders[key]['stocks']) != set(_STOCKS):
            raise N.TransferRefused('complete original funding stock accounts required')
        for name in _STOCKS:
            source, debit, remainder = (_q(row['source'][name]), _q(row['debit'][name]), _q(remainders[key]['stocks'][name]))
            if min(source, debit, remainder) < 0 or source != debit+basal[key][name]+remainder:
                raise N.TransferRefused('original funding source = debit + basal + remainder failed')
            totals[name] += debit
        if _q(row['debit']['volume_m3']) != volumes.get(key, Q(0)):
            raise N.TransferRefused('original per-source cell volume debit differs')
        component = keys.index(key) if key in keys else None
        represented = Q(0) if component is None else sum((Q(float(v)) for v in arrays['component_mass_kg'][component].flat), Q(0))
        if _q(row['debit']['mass_kg']) != represented+_q(row['component_mass_projection']):
            raise N.TransferRefused('original component mass projection equation differs')
    represented = dict(mass_kg=sum((Q(float(v)) for v in arrays['component_mass_kg'].flat), Q(0)),
        enthalpy_j=sum((Q(float(v)) for v in arrays['enthalpy_j'].flat), Q(0)),
        source_kappa_mass_kg=sum((Q(float(v)) for v in arrays['tracer:source_kappa'].flat), Q(0)))
    if any(totals[k] != represented[k]+projections[k] for k in represented):
        raise N.TransferRefused('original full-cell exact/binary projection equation differs')


@dataclass(frozen=True)
class OwnedMigratedSpatial:
    owner: object
    state: object
    funding: object
    native_transfer: N.OwnedMigratedNativeCollar
    _record: bytes

    def record(self):
        return json.loads(self._record)

    @property
    def transfer_id(self):
        import hashlib
        return hashlib.sha256(self._record).hexdigest()

    @property
    def retained_bytes(self):
        return self._record._allocation.size


class SpatialTransferLease:
    def __init__(self, value):
        self._value, self._active, self._closed = value, False, False

    def __enter__(self):
        if self._active or self._closed:
            raise N.TransferRefused('spatial transfer lease is single-use')
        self._active = True
        return self

    def __exit__(self, *details):
        if self._value is not None:
            self._value.owner.close()
        self._value, self._active, self._closed = None, False, True

    def adopt(self):
        if not self._active or self._value is None:
            raise N.TransferRefused('spatial transfer must be adopted once within its lease')
        result, self._value = self._value, None
        return result

    @property
    def state(self):
        if not self._active or self._value is None:
            raise N.TransferRefused('spatial state is borrowed only inside its lease')
        return self._value.state


def admit_migrated_spatial_owner(*, collar, native_transfer, funding_record, funding_arrays,
        historical_owner_definition, historical_spatial_record, spatial_arrays, funding_binding, origin):
    """Import the evolved endpoint, with unchanged original funding and history.

    Funding-binding ledger hashes/counts are external authenticated operands,
    not independently authenticated by this local module. Neither this result
    nor its retained native transfer grants workflow advancement permission.
    """
    from atlas_tectonics.integration_collar_geometry import FullCellFunding
    from atlas_tectonics.integration_spatial_owner import PreparedSpatialOwner, SpatialExteriorState, HEAT_METHODS
    from atlas_tectonics.integration_spatial_reservoir import PreparedFiniteStocks
    from atlas_tectonics.integration_dual_measures import policy_record
    from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
    if type(native_transfer) is not N.OwnedMigratedNativeCollar:
        raise N.TransferRefused('adopted actual native/collar transfer required')
    if 'retained_owner' not in inspect.signature(RegionalMechanicalSnapshot).parameters:
        raise N.TransferRefused('retained snapshot support required')
    N._prepared_plans(collar._native, collar)
    N._keys(funding_record, _FUNDING, _FUNDING_OPTIONAL, label='funding record')
    N._keys(historical_owner_definition, _OWNER, _OWNER_OPTIONAL, label='historical spatial owner')
    N._keys(historical_spatial_record, _STATE, _STATE_OPTIONAL, label='historical spatial state')
    N._keys(funding_binding, ('funding_id', 'debit_count', 'ledger_sha256'), label='original funding ledger binding')
    N._digest(funding_binding['ledger_sha256'], 'original funding ledger')
    if (funding_binding['funding_id'] != funding_record['funding_id'] or
            type(funding_binding['debit_count']) is not int or funding_binding['debit_count'] != 1):
        raise N.TransferRefused('one already-booked original funding debit is required')
    if type(funding_arrays) is not dict or type(spatial_arrays) is not dict:
        raise N.TransferRefused('complete funding/spatial arrays required')
    byte_count = sum(a.nbytes for arrays in (funding_arrays, spatial_arrays) for a in arrays.values()
                     if type(a) is np.ndarray)
    import geometry_transfer as G
    # Inputs are borrowed caller-owned parsed records. This phase adds one
    # native provenance decode, current definitions, funding equation rows,
    # two cell-ID sets, one projected field and the streaming codec stack.
    # In particular, it does NOT decode or copy the supplied 190 MB mesh.
    codec = max(_codec_work_bytes(v) for v in
        (funding_record, historical_spatial_record, historical_owner_definition))
    _scratch = N._Allocation(collar._budget, 131072+G._json_decode_bytes(native_transfer._record)
        +G._plan_graph_scratch_bytes(collar)+G._fields_scratch_bytes(collar, native_transfer.state)
        +3*N._width(historical_owner_definition)+N._width(funding_record)
        +N._width(historical_spatial_record.get('finite_stock_state'))
        +384*len(historical_spatial_record['cells'])+2*max((a.nbytes for a in funding_arrays.values()), default=0)
        +1024*(len(funding_arrays)+len(spatial_arrays))+codec,
                            category='spatial-transfer-scratch')
    native_record = native_transfer.record()
    if origin != native_record['input']['origin']:
        raise N.TransferRefused('spatial/native authenticated endpoint origin differs')
    comparison = N.compare_scientific_contract(native_record['input']['historical_plan_graph'],
                                              N.current_plan_graph(collar._native, collar))
    if comparison != native_record['input']['compatibility']:
        raise N.TransferRefused('native transfer was issued under another current runtime')
    if native_transfer.state.record() != native_record['current_collar']:
        raise N.TransferRefused('native transferred endpoint differs from its record')
    original, spatial = historical_owner_definition, historical_spatial_record
    if (original['schema'] != 'atlas.spatial-exterior-owner.v1' or
            spatial['schema'] != 'atlas.spatial-exterior-state.v1' or
            N._hash({k: v for k, v in original.items() if k != 'owner_id'}) != original['owner_id'] or
            spatial['owner_id'] != original['owner_id'] or original['funding_id'] != funding_record['funding_id'] or
            spatial['funding_id'] != funding_record['funding_id'] or
            original['collar_plan_id'] != comparison['plan_id_correspondence']['collar']['historical'] or
            spatial['collar_state_id'] != native_record['input']['historical_collar']['result_id'] or
            spatial['time_s'] != native_record['current_native']['time_s'] or
            type(spatial['intervals']) is not int or spatial['intervals'] < 1):
        raise N.TransferRefused('complete evolved native/spatial/funding correspondence differs')
    funding_body, funding_fields = _record_identity(funding_record, funding_arrays, 'funding_id')
    spatial_body, spatial_fields = _record_identity(spatial, spatial_arrays, 'state_id')
    _funding_equations(funding_record, funding_arrays, collar, comparison)
    expected_definition = dict(original, collar_plan_id=collar.plan_id)
    expected_definition['owner_id'] = N._hash({k: v for k, v in expected_definition.items() if k != 'owner_id'})
    new_body = dict(spatial_body, owner_id=expected_definition['owner_id'],
                    collar_state_id=native_transfer.state.result_id, parent_state_id=spatial['state_id'])
    new_state_id = _snapshot_id(new_body, spatial_fields)
    new_record = dict(state_id=new_state_id, **new_body)
    funding_metadata, _ = _stream_stats(funding_body)
    historical_metadata, _ = _stream_stats(spatial_body)
    current_metadata, _ = _stream_stats(new_body)
    transfer_record = dict(schema=TRANSFER_SCHEMA, origin=origin,
        native_transfer_id=native_transfer.transfer_id, scientific_contract_id=comparison['scientific_contract_id'],
        historical_owner_definition=original, current_owner_definition=expected_definition,
        historical_spatial_header={k: spatial[k] for k in _STATE_HEADER},
        current_spatial_header={k: new_record[k] for k in _STATE_HEADER},
        historical_spatial_metadata=historical_metadata, current_spatial_metadata=current_metadata,
        original_funding_header={k: funding_record[k] for k in
            ('schema', 'funding_id', 'collar_plan_id', 'source', 'volume_map_id', 'native_initial_state_id', 'time_s')},
        original_funding_metadata=funding_metadata, original_funding_arrays=funding_fields,
        changed_spatial_fields=['state_id', 'owner_id', 'collar_state_id', 'parent_state_id'],
        spatial_arrays=spatial_fields, funding_binding=funding_binding,
        funding_debits_applied=0, elapsed_time_s=0, scientific_acceptance=False, continuation_authorised=False,
        historical_exchange_validation='external authenticated endpoint evidence; not rewritten as current',
        differential_partition_binding='separate explicit runtime-compatible reader still required')
    encoded = N._json(transfer_record)
    # Persistent bytes/definition accounting, separate from copy/validator scratch.
    current_retained_bytes = current_metadata['nbytes']
    if _indexed(new_body):
        from spatial_indexed_patch import retained_metadata_nbytes
        current_retained_bytes = retained_metadata_nbytes(new_body)
    payload = byte_count+funding_metadata['nbytes']+current_retained_bytes+len(encoded)
    allocation = N._Allocation(collar._budget, payload+32768+4*N._width(expected_definition)+
        1024*(len(funding_arrays)+len(spatial_arrays)), category='spatial-transfer-retained')
    funding = object.__new__(FullCellFunding)
    object.__setattr__(funding, '_snapshot', _retained_snapshot(funding_body, funding_arrays,
        funding_record['funding_id'], funding_metadata, allocation, collar._budget))
    object.__setattr__(funding, '_resource', collar._budget)
    if funding.funding_id != funding_record['funding_id'] or not snapshot_metadata_matches(funding._snapshot, funding_metadata):
        raise N.TransferRefused('original funding identity changed during import')
    # This is a NEW constructor, never a mutation of a historical owner or its
    # definition. _make_definition derives its actual new collar-bound identity.
    owner = object.__new__(PreparedSpatialOwner)
    owner._closed, owner._guard, owner._initial = False, None, None
    owner._finite, owner._owns_finite = None, False
    owner._initial_geometry = None
    owner._measure_policy = None if 'measure_policy' not in original else policy_record(original['measure_policy'])
    owner._heat_label = original['heat_method']
    owner._funding, owner._collar, owner._budget = funding, collar, collar._budget
    owner._migration_retained_owner = allocation
    try:
        if owner._heat_label not in {label for label, _ in HEAT_METHODS.values()}:
            raise N.TransferRefused('unknown historical heat method')
        if 'finite_stocks' in original:
            fd = original['finite_stocks']
            owner._finite = PreparedFiniteStocks(fd['registry_id'], fd['initial_stocks'],
                field_names=fd['field_names'], nonnegative_fields=fd['nonnegative_fields'], budget=collar._budget)
            owner._owns_finite = True
            if owner._finite.definition() != fd:
                raise N.TransferRefused('original finite stock definition changed')
        owner._configure_fields(funding_record, owner._finite)
        if original['method'] != 'implicit-upwind' or set(original['projection_allowances']) != set(owner._names):
            raise N.TransferRefused('original spatial method/complete field allowances differ')
        owner._errors = {k: _q(v) for k, v in original['projection_allowances'].items()}
        if any(v < 0 for v in owner._errors.values()):
            raise N.TransferRefused('negative original spatial field allowance')
        if 'initial_geometry' in original:
            initial = original['initial_geometry']
            N._keys(initial, ('family', 'initial_bounds_id', 'partition_id', 'current_geometry_id'), label='original initial geometry')
            if initial['family'] != 'differential-plate-component-partition-v1':
                raise N.TransferRefused('unknown original geometry family')
            owner._initial_geometry = json.loads(N._json(initial))
        owner._definition = owner._make_definition(funding_record, original['grid_id'], original['initial_mesh_id'], original['method'])
        owner.owner_id = N._hash(owner._definition)
        if owner.descriptor() != expected_definition:
            raise N.TransferRefused('non-runtime spatial owner scientific contract changed')
        state = object.__new__(SpatialExteriorState)
        object.__setattr__(state, '_snapshot', _retained_snapshot(new_body, spatial_arrays,
            new_state_id, current_metadata, allocation, collar._budget))
        object.__setattr__(state, '_budget', collar._budget)
        # Existing exact/float, cell coverage, finite-history, measure, time,
        # support, mesh and field gates run, without any source reconstruction.
        validated = owner.restore(new_record, state.arrays(), _validate_only=True)
        if validated != dict(state_id=new_state_id, metadata=current_metadata, arrays=spatial_fields):
            raise N.TransferRefused('actual spatial restore changed the transferred endpoint')
        owner.validate_parent(state, native_transfer.state, _migrated_record=new_record)
        if (_bindings(state.arrays()) != spatial_fields or _bindings(funding.arrays()) != funding_fields):
            raise N.TransferRefused('original funding/spatial bytes changed during transfer')
        del validated
        return SpatialTransferLease(OwnedMigratedSpatial(owner, state, funding, native_transfer,
                                                         N._RecordBytes(encoded, allocation)))
    except BaseException:
        owner.close()
        raise
