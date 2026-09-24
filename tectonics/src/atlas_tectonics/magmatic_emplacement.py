"""W08 prescribed emplacement of an already transferred, finite magma payload.

This kernel owns placement, not extraction, melting, transport rates or mechanics.
The receiver density defines volume; an outgoing host account pays for intrusions
into occupied space. Isobaric enthalpy is advected inventory, never new heat.
Inputs/results are immutable detached snapshots; their retained bytes belong to
the caller's allowance, as for W04 ColumnLoadState. Temporary work is admitted
against a shared WorkBudget no larger than 128 MiB; this is not an RSS limit.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from atlas_tectonics._validation import TectonicsError, input_shape, read_array, scalar, text
from atlas_tectonics.resources import WorkBudget, select_budget

_METHOD = 'atlas.w08-magmatic-emplacement.v1'
_MAX_BYTES = 128 * 1024 * 1024
_DEFAULT_BUDGET = WorkBudget(_MAX_BYTES)
_MAX_CELLS = 2_097_152
_MAX_COMPONENTS = 256
_EPS = np.finfo(np.float64).eps


def _budget(value):
    result = _DEFAULT_BUDGET if value is None else select_budget(value)
    if result.max_bytes > _MAX_BYTES:
        raise TectonicsError('magmatic emplacement work budget must not exceed 128 MiB')
    return result


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('magmatic emplacement cancelled')


def _text(value, name):
    text(value, name)
    if len(value) > 4096:
        raise TectonicsError(name + ' exceeds bounded text size')
    return value


def _ids(values, name, maximum):
    if type(values) is not tuple or not 0 < len(values) <= maximum:
        raise TectonicsError(name + ' requires a bounded nonempty tuple')
    for value in values:
        _text(value, name)
    if len(set(values)) != len(values):
        raise TectonicsError(name + ' must be unique')


def _text_allowance(values):
    # JSON escaping, temporary Unicode serialization, bytes and hash input.
    return 64*sum(len(value) for value in values)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _identity(record, *buffers):
    h = hashlib.sha256(_json(record))
    for b in buffers:
        h.update(b)
    return h.hexdigest()


def _sum(values):
    try:
        return scalar(math.fsum(values), 'extensive sum')
    except OverflowError as exc:
        raise TectonicsError('extensive sum outside finite binary64 range') from exc


def _quotient(numerator, denominator, name):
    with np.errstate(over='raise', invalid='raise', divide='raise', under='ignore'):
        result = numerator / denominator
    if not np.isfinite(result).all() or np.any((numerator != 0) & (result == 0)):
        raise TectonicsError(name + ' outside nonzero finite binary64 range')
    return result


def _allocate(total, weights):
    """Conservative binary64 partition; do not renormalise user-supplied weights."""
    out = total * weights
    if np.any((weights != 0) & (total != 0) & (out == 0)):
        raise TectonicsError('nonzero deposited account underflows binary64')
    anchor = int(np.argmax(weights))
    # Largest bin safely absorbs the small rounding remainder. No physical
    # correction or weight normalisation is hidden in this representation step.
    out[anchor] = total - _sum(out[j] for j in range(len(out)) if j != anchor)
    residual = total - _sum(out)
    if residual:
        out[anchor] += residual
    if _sum(out) != total:
        raise TectonicsError('cannot represent exact deposited extensive sum')
    if total >= 0 and np.any(out < 0):
        raise TectonicsError('negative deposited mass from numerical partition')
    return out


@dataclass(frozen=True, slots=True, init=False)
class MagmaticPayload:
    """Finite upstream debit; enthalpy may be signed relative to its source datum.

    enthalpy_source identifies the full shared thermodynamic closure, including
    its reference datum; source_id identifies this stock/result independently.
    The placement kernel does not invent a temperature or phase split.
    transfer_id names the unique upstream transfer, not a reusable material type.
    """
    component_ids: tuple[str, ...]
    source_id: str
    enthalpy_source: str
    transfer_id: str
    payload_id: str
    mass_kg: float
    enthalpy_j: float
    source_density_kg_m3: float
    source_volume_m3: float
    _components: bytes

    def __init__(self, component_ids, component_mass_kg, enthalpy_j,
                 source_density_kg_m3, *, source_id, transfer_id, enthalpy_source,
                 budget=None, cancel=None):
        _cancel(cancel)
        _ids(component_ids, 'component IDs', _MAX_COMPONENTS)
        _text(source_id, 'payload source'); _text(transfer_id, 'transfer ID')
        _text(enthalpy_source, 'payload enthalpy source')
        k = len(component_ids)
        if input_shape(component_mass_kg) != (k,):
            raise TectonicsError('payload needs one finite mass per component')
        with _budget(budget).reserve(128*k+_text_allowance(component_ids+
                (source_id,transfer_id,enthalpy_source))+32768,
                                     category='magma-payload'):
            c = read_array(component_mass_kg, 'payload component mass', nonnegative=True)
            if c.shape != (k,):
                raise TectonicsError('payload shape changed during capture')
            mass = _sum(c)
            e = scalar(enthalpy_j, 'signed isobaric enthalpy')
            rho = scalar(source_density_kg_m3, 'source density', positive=True)
            if mass == 0 and e != 0:
                raise TectonicsError('empty material cannot carry enthalpy')
            volume = scalar(mass/rho, 'source volume', nonnegative=True)
            if mass and not volume:
                raise TectonicsError('source volume underflows')
            b = c.tobytes()
            record = dict(method=_METHOD, components=component_ids, source=source_id,
                          transfer=transfer_id, enthalpy_j=e, enthalpy_source=enthalpy_source,
                          source_density_kg_m3=rho)
            _cancel(cancel)
            for name, value in dict(component_ids=component_ids, source_id=source_id,
                    transfer_id=transfer_id, enthalpy_source=enthalpy_source,
                    payload_id=_identity(record, b), mass_kg=mass,
                    enthalpy_j=e, source_density_kg_m3=rho, source_volume_m3=volume,
                    _components=b).items():
                object.__setattr__(self, name, value)

    @property
    def component_mass_kg(self):
        return np.frombuffer(self._components, dtype=np.float64)


@dataclass(frozen=True, slots=True, init=False)
class EmplacementTarget:
    """Source-defined cell footprints, receiver densities and unit-sum mass weights."""
    column_ids: tuple[str, ...]
    geometry_source: str
    frame_id: str
    datum_id: str
    epoch_id: str
    target_id: str
    _values: bytes

    def __init__(self, column_ids, area_m2, receiving_density_kg_m3, mass_weights,
                 *, geometry_source, frame_id, datum_id, epoch_id, budget=None, cancel=None):
        _cancel(cancel)
        if type(column_ids) is not tuple or not 0 < len(column_ids) <= _MAX_CELLS:
            raise TectonicsError('bounded nonempty tuple of column IDs required')
        # Validate text before sizing; the potentially large uniqueness set is
        # allocated only after admission below.
        for column_id in column_ids:
            _text(column_id, 'column ID')
        record = dict(method=_METHOD, columns=column_ids, geometry_source=geometry_source,
                      frame_id=frame_id, datum_id=datum_id, epoch_id=epoch_id)
        for name in ('geometry_source', 'frame_id', 'datum_id', 'epoch_id'):
            _text(record[name], name)
        n = len(column_ids)
        if any(input_shape(x) != (n,) for x in (area_m2, receiving_density_kg_m3, mass_weights)):
            raise TectonicsError('area, receiving density and weights need one value per column')
        with _budget(budget).reserve(256*n+_text_allowance(column_ids)+
                _text_allowance((geometry_source,frame_id,datum_id,epoch_id))+32768,
                                     category='magma-target'):
            _ids(column_ids, 'column IDs', _MAX_CELLS)
            a = read_array(area_m2, 'receiving area')
            r = read_array(receiving_density_kg_m3, 'receiving density')
            w = read_array(mass_weights, 'spatial mass weights', nonnegative=True)
            if any(x.shape != (n,) for x in (a,r,w)) or np.any(a <= 0) or np.any(r <= 0):
                raise TectonicsError('positive area/density and unchanged shapes required')
            if _sum(w) != 1.0:
                raise TectonicsError('supplied nonnegative mass weights must sum to one')
            b = np.column_stack((a,r,w)).tobytes()
            _cancel(cancel)
            for name,value in dict(column_ids=column_ids, geometry_source=geometry_source,
                    frame_id=frame_id, datum_id=datum_id, epoch_id=epoch_id,
                    target_id=_identity(record,b), _values=b).items():
                object.__setattr__(self,name,value)

    @property
    def area_m2(self):
        return np.frombuffer(self._values,dtype=np.float64).reshape(-1,3)[:,0]

    @property
    def receiving_density_kg_m3(self):
        return np.frombuffer(self._values,dtype=np.float64).reshape(-1,3)[:,1]

    @property
    def mass_weights(self):
        return np.frombuffer(self._values,dtype=np.float64).reshape(-1,3)[:,2]


@dataclass(frozen=True, slots=True, init=False)
class HostStock:
    """Finite homogeneous stock per receiving cell, bound to the exact target.

    Components use the same catalogue as the incoming payload. enthalpy_source
    binds the full shared thermodynamic closure, independently of stock source_id.
    Host density is its inventory density.
    """
    component_ids: tuple[str, ...]
    source_id: str
    enthalpy_source: str
    target_id: str
    stock_id: str
    cells: int
    _components: bytes
    _fields: bytes

    def __init__(self, component_ids, component_mass_kg, enthalpy_j, density_kg_m3,
                 *, source_id, target, enthalpy_source, budget=None, cancel=None):
        _cancel(cancel)
        _ids(component_ids, 'host component IDs', _MAX_COMPONENTS)
        _text(source_id, 'host source')
        _text(enthalpy_source, 'host enthalpy source')
        if type(target) is not EmplacementTarget:
            raise TectonicsError('host requires its explicit EmplacementTarget')
        n, k = len(target.column_ids), len(component_ids)
        if (input_shape(component_mass_kg) != (n,k) or input_shape(enthalpy_j) != (n,)
                or input_shape(density_kg_m3) != (n,)):
            raise TectonicsError('host components/enthalpy/density require exact cell coverage')
        with _budget(budget).reserve(128*n*k+256*n+
                _text_allowance(component_ids+(source_id,enthalpy_source))+32768,
                category='magma-host'):
            c = read_array(component_mass_kg, 'host components', nonnegative=True)
            e = read_array(enthalpy_j, 'host signed enthalpy')
            r = read_array(density_kg_m3, 'host density')
            if c.shape != (n,k) or e.shape != (n,) or r.shape != (n,) or np.any(r <= 0):
                raise TectonicsError('positive host density and unchanged shapes required')
            m = np.array([_sum(row) for row in c])
            if np.any((m == 0) & (e != 0)):
                raise TectonicsError('empty host material cannot carry enthalpy')
            try:
                v = _quotient(m,r,'host volume')
            except FloatingPointError as exc:
                raise TectonicsError('host volume outside numerical range') from exc
            cb, fb = c.tobytes(), np.column_stack((m,e,r,v)).tobytes()
            record = dict(method=_METHOD, components=component_ids, source_id=source_id,
                          target_id=target.target_id, enthalpy_source=enthalpy_source)
            _cancel(cancel)
            for name,value in dict(component_ids=component_ids, source_id=source_id,
                    target_id=target.target_id, enthalpy_source=enthalpy_source,
                    stock_id=_identity(record,cb,fb), cells=n,
                    _components=cb, _fields=fb).items():
                object.__setattr__(self,name,value)

    @property
    def component_mass_kg(self):
        return np.frombuffer(self._components,dtype=np.float64).reshape(self.cells,-1)

    @property
    def fields(self):
        """Columns mass kg, signed enthalpy J, density kg/m3, volume m3."""
        return np.frombuffer(self._fields,dtype=np.float64).reshape(self.cells,4)


@dataclass(frozen=True, slots=True, init=False)
class EmplacementResult:
    """One source-bound booking for W03/W04/W07, not three additive effects.

    incoming/outgoing_host/remaining_host fields: mass kg, advected enthalpy J,
    volume m3. geometry fields: dz m, added basal volume m3, added surface volume
    m3, net occupied volume m3, net inventory load kg/m2. No temperature anomaly,
    latent heat release or flexural response is inferred. The receiving reference
    must debit outgoing host before adding incoming volume; outgoing material is
    independently owned by the named destination. Host stock input is borrowed.
    """
    result_id: str
    payload: MagmaticPayload
    target: EmplacementTarget
    host: HostStock | None
    mode: str
    source_id: str
    host_destination_id: str | None
    _metadata: bytes
    _incoming: bytes
    _outgoing: bytes
    _remaining: bytes
    _geometry: bytes
    _in_components: bytes
    _out_components: bytes
    _remaining_components: bytes

    def descriptor(self):
        return json.loads(self._metadata)

    @property
    def incoming(self):
        return np.frombuffer(self._incoming,dtype=np.float64).reshape(-1,3)

    @property
    def outgoing_host(self):
        return np.frombuffer(self._outgoing,dtype=np.float64).reshape(-1,3)

    @property
    def remaining_host(self):
        return np.frombuffer(self._remaining,dtype=np.float64).reshape(-1,3)

    @property
    def geometry(self):
        return np.frombuffer(self._geometry,dtype=np.float64).reshape(-1,5)

    def _component_view(self, b):
        return np.frombuffer(b,dtype=np.float64).reshape(len(self.target.column_ids),-1)

    @property
    def incoming_component_mass_kg(self):
        return self._component_view(self._in_components)

    @property
    def outgoing_host_component_mass_kg(self):
        return self._component_view(self._out_components)

    @property
    def remaining_host_component_mass_kg(self):
        return self._component_view(self._remaining_components)


def emplace_magma(payload, target, *, mode, source_id, host=None,
                  host_destination_id=None, budget=None, cancel=None):
    """Place once; caller retains snapshots and deduplicates via accounting_entries.

    Displacement/replacement remove exactly receiver volume from finite host and
    publish its components/enthalpy to an explicit destination. Underplating adds
    basal volume; extrusion adds surface volume. None predicts accommodation.
    """
    _cancel(cancel)
    if type(payload) is not MagmaticPayload or type(target) is not EmplacementTarget:
        raise TectonicsError('typed finite payload and receiving target required')
    _text(source_id, 'emplacement source')
    if mode not in ('extrusive','underplating','host-displacement','replacement'):
        raise TectonicsError('explicit supported emplacement/accommodation mode required')
    remove_host = mode in ('host-displacement','replacement')
    if remove_host:
        if type(host) is not HostStock:
            raise TectonicsError('displacement/replacement requires finite host stock')
        _text(host_destination_id, 'outgoing host destination')
        if (host.target_id != target.target_id or host.component_ids != payload.component_ids):
            raise TectonicsError('host target/component catalogue differs from emplacement')
        if host.enthalpy_source != payload.enthalpy_source:
            raise TectonicsError('host and payload enthalpy source conventions differ')
        if host_destination_id in target.column_ids or host_destination_id == host.source_id:
            raise TectonicsError('outgoing host needs a distinct accounted destination')
    elif host is not None or host_destination_id is not None:
        raise TectonicsError('host output only belongs to displacement/replacement')
    n, k = len(target.column_ids), len(payload.component_ids)
    with _budget(budget).reserve(256*n*k+2048*n+_text_allowance(payload.component_ids+
            (source_id,payload.source_id,payload.transfer_id,payload.enthalpy_source,
             host_destination_id or ''))+65536,
            category='magma-emplacement'):
        try:
            with np.errstate(over='raise',invalid='raise',divide='raise',under='ignore'):
                w = target.mass_weights
                mass, enthalpy = _allocate(payload.mass_kg,w), _allocate(payload.enthalpy_j,w)
                components = np.empty((n,k))
                for j in range(k):
                    _cancel(cancel)
                    components[:,j] = _allocate(payload.component_mass_kg[j],w)
                volume = _quotient(mass,target.receiving_density_kg_m3,'receiving volume')
                dz = _quotient(volume,target.area_m2,'receiving thickness')
                incoming = np.column_stack((mass,enthalpy,volume))
                outgoing, remaining = np.zeros((n,3)), np.zeros((n,3))
                out_c, rem_c = np.zeros((n,k)), np.zeros((n,k))
                if remove_host:
                    hm, he, hr, hv = host.fields.T
                    if np.any(volume > hv):
                        raise TectonicsError('insufficient finite host volume for accommodation')
                    fraction = np.zeros(n)
                    occupied = hv > 0
                    fraction[occupied] = _quotient(volume[occupied],hv[occupied],'host removal fraction')
                    # Use the stored finite mass to make exact exhaustion exact;
                    # this equals V*rho at the represented stock density.
                    outgoing[:,0] = hm*fraction
                    outgoing[:,1] = he*fraction
                    outgoing[:,2] = volume
                    out_c = host.component_mass_kg*fraction[:,None]
                    if (np.any((host.component_mass_kg != 0) & (fraction[:,None] != 0) & (out_c == 0))
                            or np.any((he != 0) & (fraction != 0) & (outgoing[:,1] == 0))):
                        raise TectonicsError('nonzero outgoing host account underflows')
                    rem_c = host.component_mass_kg-out_c
                    remaining = np.column_stack((hm-outgoing[:,0],he-outgoing[:,1],hv-volume))
                    if np.any(remaining[:,(0,2)] < 0) or np.any(rem_c < 0):
                        raise TectonicsError('host removal would overdraw finite stock')
                net_mass = mass-outgoing[:,0]
                load = _quotient(net_mass,target.area_m2,'net inventory sheet')
                zeros = np.zeros(n)
                geometry = np.column_stack((dz, volume if mode=='underplating' else zeros,
                    volume if mode=='extrusive' else zeros, volume-outgoing[:,2],load))
        except (FloatingPointError,OverflowError) as exc:
            raise TectonicsError('emplacement arithmetic outside numerical range') from exc
        arrays = (incoming,outgoing,remaining,geometry,components,out_c,rem_c)
        if not all(np.isfinite(a).all() for a in arrays):
            raise TectonicsError('nonfinite emplacement fields')
        for i in range(n):
            _cancel(cancel)
            # Separate exact global component accounts and scalar mass partitions
            # can differ by rounding in a cell; enforce frozen extensive gate.
            actual = _sum(components[i]); expected = incoming[i,0]
            if abs(actual-expected) > 128*_EPS*max(abs(actual),abs(expected)):
                raise TectonicsError('incoming cell component mass closure failed')
            if host is not None:
                for a,b,c in zip(host.component_mass_kg[i],out_c[i],rem_c[i]):
                    if abs(_sum((b,c))-a) > 128*_EPS*(abs(a)+abs(b)+abs(c)):
                        raise TectonicsError('host component account closure failed')
                if abs(_sum(out_c[i])-outgoing[i,0]) > 128*_EPS*max(host.fields[i,0],outgoing[i,0]):
                    raise TectonicsError('outgoing host density/component mass mismatch')
        record = dict(method=_METHOD, payload_id=payload.payload_id, transfer_id=payload.transfer_id,
            target_id=target.target_id, source_id=source_id, mode=mode,
            enthalpy_source=payload.enthalpy_source,
            host_stock_id=None if host is None else host.stock_id,
            host_destination_id=host_destination_id, component_ids=payload.component_ids,
            source_volume_m3=payload.source_volume_m3, receiving_volume_m3=_sum(volume),
            incoming_mass_kg=_sum(mass), incoming_enthalpy_j=_sum(enthalpy),
            outgoing_host_mass_kg=_sum(outgoing[:,0]), outgoing_host_enthalpy_j=_sum(outgoing[:,1]),
            source_debit_owner=payload.source_id, receiving_inventory_owner='this-emplacement',
            structural_load_owner='net-inventory-mass-only',
            thermal_owner='advected-isobaric-enthalpy-inventory-only',
            heat_source_j=0.0, thermal_anomaly='not-inferred',
            geometry_owner='supplied-accommodation-mode; no displacement-solution',
            inventory_columns=('mass_kg','advected_enthalpy_j','volume_m3'),
            geometry_columns=('deposited_thickness_m','added_basal_volume_m3','added_surface_volume_m3',
                              'net_occupied_volume_m3','net_inventory_kg_m2'),
            reference='single transfer delta; never add upstream terminal stock again')
        metadata = _json(record)
        buffers = tuple(a.tobytes() for a in arrays)
        result = object.__new__(EmplacementResult)
        attrs = dict(result_id=_identity(record,*buffers),payload=payload,target=target,host=host,
                     mode=mode,source_id=source_id,host_destination_id=host_destination_id,
                     _metadata=metadata)
        attrs.update(zip(('_incoming','_outgoing','_remaining','_geometry','_in_components',
                          '_out_components','_remaining_components'),buffers))
        _cancel(cancel)
        for name,value in attrs.items():
            object.__setattr__(result,name,value)
        return result


def accounting_entries(results, *, budget=None, cancel=None):
    """Return detached single-owner ledger entries, refusing replay/double spending.

    Consumers book each entry once in their persistent ledger; the same entry ID
    owns its material volume, net load and advected enthalpy views. Upstream
    terminal sink stocks are alternate views of this incoming material, not an
    additional receiver inventory. Reusing the same host snapshot twice is
    refused: a continuation must supply the returned remaining stock instead.
    """
    if type(results) is not tuple or len(results) > 256:
        raise TectonicsError('bounded tuple of emplacement results required')
    if any(type(result) is not EmplacementResult for result in results):
        raise TectonicsError('typed emplacement result required')
    _cancel(cancel)
    with _budget(budget).reserve(16*sum(len(r._metadata) for r in results)+8192,
                                 category='magma-ledger-view'):
        return _accounting_entries(results,cancel)


def _accounting_entries(results,cancel):
    transfers, hosts, entries = set(),set(),[]
    for result in results:
        _cancel(cancel)
        key = result.payload.transfer_id
        if key in transfers:
            raise TectonicsError('same magma transfer would be booked twice')
        transfers.add(key)
        if result.host is not None:
            if result.host.stock_id in hosts:
                raise TectonicsError('same finite host stock would be spent twice')
            hosts.add(result.host.stock_id)
        item = result.descriptor()
        item['entry_id'] = result.result_id
        entries.append(item)
    return tuple(entries)
