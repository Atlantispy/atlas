"""W08 conservative regional observations of current, singly owned stocks.

This diagnostic places extensive inventories on supplied moving parcels. It does
not transfer material, solve support or add a second thermal/source contribution.
Definitions and results are immutable snapshots; the enclosing workflow owns
their retained allowances after each admitted construction returns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
from shapely.strtree import STRtree

from ._validation import TectonicsError, input_shape, read_array, scalar
from .geometry import PlanarGeometry, DEFAULT_GEOMETRY_LIMITS, _validate_shape
from .magmatic_emplacement import (_allocate, _budget, _cancel, _identity,
    _ids, _json, _quotient, _sum, _text, _text_allowance)
from .planar_projection import _disjoint


_METHOD = 'atlas.w08-region.v1'
_EPS = np.finfo(np.float64).eps
_MODES = {'existing-column': ('crust', 'mantle', 'accretion'),
          'extrusive': ('extrusion',), 'underplating': ('intrusion',)}


def _footprints(polygons, *, count=None, frame_id=None):
    if (type(polygons) is not tuple or not 1 <= len(polygons) <= 4096 or
            (count is not None and len(polygons) != count) or
            any(type(g) is not PlanarGeometry or g.kind != 'Polygon' or
                g.is_empty or g.area_m2 <= 0 for g in polygons)):
        raise TectonicsError('one to 4096 positive-area planar parcel polygons required')
    frame = polygons[0].frame_id if frame_id is None else frame_id
    if any(g.frame_id != frame for g in polygons):
        raise TectonicsError('regional parcel frame mismatch')
    if sum(g.vertex_count for g in polygons) > DEFAULT_GEOMETRY_LIMITS.max_vertices:
        raise TectonicsError('regional polygon vertex budget exceeded')
    return polygons


def _geometry_bytes(polygons):
    return (512*sum(g.vertex_count for g in polygons) + 4096*len(polygons)
            + sum(g.retained_bytes for g in polygons))


def _validate_footprints(polygons, budget, cancel):
    for g in polygons:
        _cancel(cancel)
        _validate_shape(g._geom, DEFAULT_GEOMETRY_LIMITS, allow_empty=False)
    shapes = tuple(g._geom for g in polygons)
    _disjoint(shapes, STRtree(shapes), budget, cancel, 'regional parcel')


@dataclass(frozen=True, slots=True, init=False)
class W08Region:
    """A prescribed conservative placement, independent of physical ownership.

    Node IDs are a sorted subset of the unified inventory. Existing rock uses
    ``existing-column``; terminal magma requires ``extrusive`` or ``underplating``.
    Host replacement/displacement belongs to the explicit Step 5 owner and is
    deliberately unsupported here. Density is fixed for this source-bound region.
    """
    polygons: tuple[PlanarGeometry, ...]
    parcel_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    placement_modes: tuple[str, ...]
    source_id: str
    epoch_id: str
    datum_id: str
    frame_id: str
    gravity_m_s2: float
    region_id: str
    _density: bytes = field(repr=False)
    _weights: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    def __init__(self, polygons, parcel_ids, node_ids, density_kg_m3,
                 mass_weights, placement_modes, *, source_id, epoch_id,
                 datum_id, gravity_m_s2, budget=None):
        _footprints(polygons)
        _ids(parcel_ids, 'parcel IDs', 4096)
        _ids(node_ids, 'regional owner node IDs', 64)
        n, p = len(node_ids), len(polygons)
        if len(parcel_ids) != p or node_ids != tuple(sorted(node_ids)):
            raise TectonicsError('parcel IDs must match geometry and owner IDs must be sorted')
        if (type(placement_modes) is not tuple or len(placement_modes) != n or
                any(type(mode) is not str or mode not in _MODES for mode in placement_modes)):
            raise TectonicsError('explicit existing-column/extrusive/underplating mode per owner required')
        for name, value in (('source', source_id), ('epoch', epoch_id), ('datum', datum_id)):
            _text(value, name)
        g = scalar(gravity_m_s2, 'regional gravity', positive=True)
        if input_shape(density_kg_m3) != (n,) or input_shape(mass_weights) != (n,p):
            raise TectonicsError('one density per node and one mass weight per node/parcel required')
        resource = _budget(budget)
        # Includes detached arrays, JSON parameters, geometry/index and hash work.
        size = 192*n*p + 256*n + _geometry_bytes(polygons) + 65536
        size += _text_allowance(parcel_ids+node_ids+(source_id,epoch_id,datum_id))
        with resource.reserve(size, category='w08-region-definition'):
            _validate_footprints(polygons, resource, None)
            rho = read_array(density_kg_m3, 'regional receiving density')
            weights = read_array(mass_weights, 'regional mass weights', nonnegative=True)
            if rho.shape != (n,) or weights.shape != (n,p) or np.any(rho <= 0):
                raise TectonicsError('positive densities and unchanged regional shapes required')
            if any(_sum(row) != 1.0 for row in weights):
                raise TectonicsError('each supplied regional mass-weight row must sum to one')
            density, weight_bytes = rho.tobytes(), weights.tobytes()
            record = dict(method=_METHOD, source_id=source_id, epoch_id=epoch_id,
                datum_id=datum_id, frame_id=polygons[0].frame_id, parcel_ids=parcel_ids,
                node_ids=node_ids, placement_modes=placement_modes, gravity_m_s2=g,
                reference_geometry_ids=tuple(x.geometry_id for x in polygons),
                density_kg_m3=rho.tolist(), mass_weights=weights.tolist(),
                inventory_owner='unified-current-node-stocks',
                structural_owner='diagnostic-mass-per-area-reference-difference',
                thermal_owner='advected-isobaric-enthalpy-only', heat_source_j=0.)
            values = dict(polygons=polygons, parcel_ids=parcel_ids, node_ids=node_ids,
                placement_modes=placement_modes, source_id=source_id, epoch_id=epoch_id,
                datum_id=datum_id, frame_id=polygons[0].frame_id, gravity_m_s2=g,
                region_id=_identity(record,density,weight_bytes), _density=density,
                _weights=weight_bytes, _record=_json(record))
            for name, value in values.items():
                object.__setattr__(self,name,value)

    @property
    def density_kg_m3(self):
        return np.frombuffer(self._density, np.float64)

    @property
    def mass_weights(self):
        return np.frombuffer(self._weights, np.float64).reshape(len(self.node_ids),len(self.parcel_ids))

    @property
    def reference_wkb(self):
        return tuple(g.wkb for g in self.polygons)

    @property
    def nbytes(self):
        return _geometry_bytes(self.polygons)+len(self._density)+len(self._weights)+len(self._record)

    def descriptor(self):
        import json
        return json.loads(self._record)

    def regional_view(self, inventory, polygons, *, reference_inventory,
                      reference_polygons=None, budget=None, cancel=None):
        return regional_view(self, inventory, polygons,
            reference_inventory=reference_inventory, reference_polygons=reference_polygons,
            budget=budget, cancel=cancel)


@dataclass(frozen=True, slots=True)
class W08RegionalView:
    """Immutable full stocks plus reference-relative load and deposition views."""
    region_id: str
    view_id: str
    node_ids: tuple[str, ...]
    parcel_ids: tuple[str, ...]
    component_ids: tuple[str, ...]
    time_s: float
    _stocks: bytes = field(repr=False)
    _components: bytes = field(repr=False)
    _changes: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    def _stock(self, i):
        return np.frombuffer(self._stocks,np.float64).reshape(4,len(self.node_ids),len(self.parcel_ids))[i]

    @property
    def mass_kg(self): return self._stock(0)
    @property
    def enthalpy_j(self): return self._stock(1)
    @property
    def volume_m3(self): return self._stock(2)
    @property
    def thickness_m(self): return self._stock(3)
    @property
    def component_mass_kg(self):
        return np.frombuffer(self._components,np.float64).reshape(
            len(self.node_ids),len(self.parcel_ids),len(self.component_ids))
    @property
    def load_change_pa(self):
        return np.frombuffer(self._changes,np.float64).reshape(3,len(self.parcel_ids))[0]
    @property
    def surface_addition_m(self):
        return np.frombuffer(self._changes,np.float64).reshape(3,len(self.parcel_ids))[1]
    @property
    def basal_addition_m(self):
        return np.frombuffer(self._changes,np.float64).reshape(3,len(self.parcel_ids))[2]
    @property
    def nbytes(self):
        return sum(map(len,(self._stocks,self._components,self._changes,self._record)))

    def descriptor(self):
        import json
        return json.loads(self._record)


def _check_inventories(region, inventory, reference):
    # The unified inventory validates its complete, immutable extensive account;
    # comparing its definition prevents a different donor/enthalpy convention
    # from masquerading as the initial reference of the current trajectory.
    from .w08_inventory import W08Inventory
    if type(inventory) is not W08Inventory or type(reference) is not W08Inventory:
        raise TectonicsError('typed current and reference W08 inventories required')
    for name in ('component_ids','node_ids','node_kinds','origin_ids','enthalpy_source'):
        if getattr(inventory,name) != getattr(reference,name):
            raise TectonicsError('regional reference inventory '+name+' mismatch')
    if not np.array_equal(inventory.formation_time_s,reference.formation_time_s):
        raise TectonicsError('regional reference formation source mismatch')
    if reference.time_s > inventory.time_s:
        raise TectonicsError('regional reference cannot be later than current inventory')
    lookup = {name:i for i,name in enumerate(inventory.node_ids)}
    if any(name not in lookup for name in region.node_ids):
        raise TectonicsError('regional node is absent from unified inventory')
    indices = tuple(lookup[name] for name in region.node_ids)
    for i,mode in zip(indices,region.placement_modes):
        if inventory.node_kinds[i] not in _MODES[mode]:
            raise TectonicsError('regional placement mode does not match physical node kind')
    return indices


def regional_view(region, inventory, polygons, *, reference_inventory,
                  reference_polygons=None, budget=None, cancel=None):
    """Project current owner stocks; never book a new material or heat transfer.

    Load is g*(current mass/current area - reference mass/reference area).
    Extrusive/basal additions use only current-minus-reference mass at the fixed
    receiving density and current area. Existing column thickening is in the
    full thickness field and is not counted again as new emplacement.
    """
    _cancel(cancel)
    if type(region) is not W08Region:
        raise TectonicsError('typed W08 regional placement required')
    n,p = len(region.node_ids),len(region.parcel_ids)
    _footprints(polygons,count=p,frame_id=region.frame_id)
    reference = region.polygons if reference_polygons is None else reference_polygons
    _footprints(reference,count=p,frame_id=region.frame_id)
    indices = _check_inventories(region,inventory,reference_inventory)
    k = len(inventory.component_ids)
    resource = _budget(budget)
    # Returned bytes coexist with work arrays and JSON/hash scratch. No N*P*K
    # array, native geometry index or retained-result buffer precedes admission.
    size = 32*n*p*k + 160*n*p + 256*p + region.nbytes + 65536
    size += _geometry_bytes(polygons)+_geometry_bytes(reference)
    size += _text_allowance(inventory.component_ids+inventory.node_ids+
        (inventory.inventory_id,reference_inventory.inventory_id,region.source_id))
    with resource.reserve(size,category='w08-region-view'):
        if polygons != region.polygons:
            _validate_footprints(polygons,resource,cancel)
        if reference != region.polygons and reference != polygons:
            _validate_footprints(reference,resource,cancel)
        area = np.array([g.area_m2 for g in polygons])
        ref_area = np.array([g.area_m2 for g in reference])
        stocks = np.empty((4,n,p)); components = np.empty((n,p,k))
        base_mass = np.empty((n,p)); changes = np.zeros((3,p))
        mass,heat,volume,thickness = stocks
        weights,rho = region.mass_weights,region.density_kg_m3
        try:
            with np.errstate(over='raise',invalid='raise',divide='raise',under='ignore'):
                for row,i in enumerate(indices):
                    _cancel(cancel)
                    mass[row] = _allocate(inventory.mass_kg[i],weights[row])
                    base_mass[row] = _allocate(reference_inventory.mass_kg[i],weights[row])
                    heat[row] = _allocate(inventory.enthalpy_j[i],weights[row])
                    for c in range(k):
                        components[row,:,c] = _allocate(inventory.component_mass_kg[i,c],weights[row])
                    for parcel in range(p):
                        total = _sum(components[row,parcel])
                        if abs(total-mass[row,parcel]) > 128*_EPS*max(total,mass[row,parcel]):
                            raise TectonicsError('regional component mass closure failed')
                    volume[row] = _quotient(mass[row],rho[row],'regional volume')
                    thickness[row] = _quotient(volume[row],area,'regional thickness')
                    mode = region.placement_modes[row]
                    if mode != 'existing-column':
                        delta = _quotient(mass[row]-base_mass[row],rho[row],'emplacement volume change')
                        changes[1 if mode == 'extrusive' else 2] += _quotient(
                            delta,area,'emplacement thickness change')
                current = np.array([_sum(mass[:,j]) for j in range(p)])
                initial = np.array([_sum(base_mass[:,j]) for j in range(p)])
                changes[0] = (_quotient(current,area,'current mass per area')-
                    _quotient(initial,ref_area,'reference mass per area'))*region.gravity_m_s2
        except (FloatingPointError,OverflowError) as exc:
            raise TectonicsError('regional diagnostic arithmetic outside numerical range') from exc
        if not all(np.isfinite(a).all() for a in (stocks,components,changes)):
            raise TectonicsError('nonfinite regional diagnostic result')
        record = dict(method=_METHOD, region_id=region.region_id, source_id=region.source_id,
            epoch_id=region.epoch_id, datum_id=region.datum_id, frame_id=region.frame_id,
            node_ids=region.node_ids, parcel_ids=region.parcel_ids,
            component_ids=inventory.component_ids, placement_modes=region.placement_modes,
            current_inventory_id=inventory.inventory_id,
            reference_inventory_id=reference_inventory.inventory_id,
            inventory_source_id=inventory.source_id,
            reference_inventory_source_id=reference_inventory.source_id,
            enthalpy_source=inventory.enthalpy_source,
            origin_ids=tuple(inventory.origin_ids[i] for i in indices),
            time_s=inventory.time_s, reference_time_s=reference_inventory.time_s,
            geometry_ids=tuple(g.geometry_id for g in polygons),
            reference_geometry_ids=tuple(g.geometry_id for g in reference),
            gravity_m_s2=region.gravity_m_s2,
            mass_owner='unified-current-node-stocks', heat_source_j=0.,
            thermal_owner='advected-isobaric-enthalpy-only',
            structural_owner='diagnostic-only-no-support-solution',
            additions='mass-delta-only-at-fixed-receiving-density-and-current-area')
        buffers = stocks.tobytes(),components.tobytes(),changes.tobytes()
        _cancel(cancel)
        return W08RegionalView(region.region_id,_identity(record,*buffers),region.node_ids,
            region.parcel_ids,inventory.component_ids,inventory.time_s,*buffers,_json(record))
