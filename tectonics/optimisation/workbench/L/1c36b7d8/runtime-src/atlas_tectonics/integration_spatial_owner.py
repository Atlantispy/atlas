"""Retained spatial exterior stocks, coupled to actual native donor fields.

Initial source stocks are partitioned ONCE over certified physical cells. Later
steps consume the carried fields, never source temperatures or patch averages.
The heat mesh is a numerical operator geometry; it cannot set material volume.
Atomic storage/publication belongs to CollarWorkflow, not this proposal owner.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
import weakref
import live_spatial_patch as LIVE_SPATIAL
import exchange_record_patch as _EXCHANGE_RECORD

import numpy as np

from ._validation import TectonicsError
from .integration_collar_geometry import FullCellFunding, _partition
from .integration_exterior_mesh import ExteriorMesh
from .integration_mimetic_heat import EXTREMUM, MimeticGeometry, PreparedMimeticHeat3D, _enc, _q
from .integration_regional_inventory import ComponentRegistry, _width, _project
from .integration_spatial_ale import SpatialALEBounds, SpatialALEGraph, close_spatial_ale
from .integration_spatial_transport import PreparedSpatialTransport, SpatialTransportResult
from .integration_spatial_reservoir import PreparedFiniteStocks
from .regional_collar3d import PreparedRegionalCollar3D, RegionalCollarSourceFlowStage
from .regional_execution import RegionalMechanicalSnapshot
from .resources import WorkBudget
from .integration_dual_measures import B_NAME, policy_record, check_state_cells, transport_audit

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _json(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(record):
    return hashlib.sha256(_json(record)).hexdigest()


def _retain(obj, size, budget):
    lease = budget.reserve(size, category='spatial-owner-retained')
    lease.__enter__()
    weakref.finalize(obj, lease.__exit__, None, None, None)


def _carried_start_cells(state, geometry):
    """Exact identity transfer into new geometric labels, without remapping.

    The issued differential partition proves the old accepted chart is one
    same-support child at the next start. The owner additionally requires a
    complete one-to-one field transfer and unchanged material lineage. Nothing
    here splits, averages, advects or reconstructs a physical field.
    """
    previous = {row['cell_id']: row for row in _SV.rows(state['cells'])}
    if geometry.get('physical_geometry_family') != 'differential-plate-component-partition-v1':
        return previous
    from spatial_indexed_patch import mesh_header, is_compact
    _parent_mesh = state['thermal_mesh']
    _parent_header = mesh_header(_parent_mesh, _parent_mesh.budget if is_compact(_parent_mesh) else None)
    if geometry.get('parent_partition_id') != _parent_header.value.get('partition_id'):
        raise TectonicsError('carried fields do not belong to the actual parent partition')
    mapping = geometry.get('identity_start_cells')
    if type(mapping) is not list:
        raise TectonicsError('differential continuation needs issued exact start-field identities')
    # A closed graph keeps cells with exactly zero start and end volume and no
    # stream in ``inactive_zero_measure_cells``. They are still actual
    # geometry of the certificate: an identity child there is not omitted.
    actual = {row['cell_id']: row for row in (*geometry['cells'], *geometry.get('inactive_zero_measure_cells', ()))
              if row['kind'] == 'exterior'}
    parents, children, carried = set(), set(), {}
    for item in mapping:
        if type(item) is not dict or set(item) != {'parent_cell_id', 'cell_id'}:
            raise TectonicsError('complete parent-child start identity required')
        parent, child = item['parent_cell_id'], item['cell_id']
        if parent in parents or child in children or child not in actual:
            raise TectonicsError('differential start identity duplicates or omits actual geometry')
        parents.add(parent); children.add(child)
        row = actual[child]
        old = previous.get(parent)
        if old is None:
            bounds = row.get('start_volume_bounds_m3')
            if bounds is None or any(_q(v) for v in bounds):
                raise TectonicsError('absent old material cannot become a positive start child')
            continue
        if row['source_key'] != old['source_key']:
            raise TectonicsError('same-support start identity changed material lineage')
        carried[child] = _SV.copy_row(old, cell_id=child)
    if set(previous)-parents:
        raise TectonicsError('differential continuation omitted carried positive material')
    return carried


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class SpatialExteriorState:
    _snapshot: RegionalMechanicalSnapshot = field(repr=False)
    _budget: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('spatial exterior states are issued by their owner')

    @property
    def state_id(self):
        return self._snapshot.result_id

    @property
    def time_s(self):
        from spatial_indexed_patch import IndexedSpatialSnapshot
        if type(self._snapshot) is IndexedSpatialSnapshot:
            return self._snapshot.time_s
        return self._snapshot.descriptor()['time_s']

    def record(self):
        return dict(state_id=self.state_id, **self._snapshot.descriptor())

    def compact_record(self, *, mesh_reference):
        """Owned explicit compact persistence envelope; no legacy expansion."""
        from spatial_indexed_patch import compact_record
        return compact_record(self, mesh_reference=mesh_reference)

    def indexed_record(self):
        """Owned logical state with a sealed indexed mesh, not JSON wire."""
        from spatial_indexed_patch import indexed_record
        return indexed_record(self)

    def arrays(self):
        return {k: self._snapshot.array(k) for k in self._snapshot.array_names}


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class SpatialOwnerTransport:
    parent: SpatialExteriorState
    source: RegionalCollarSourceFlowStage
    graph: SpatialALEGraph
    result: SpatialTransportResult
    finite_proposal: object = field(repr=False, compare=False)
    measure_audit: bytes | None = field(repr=False, compare=False)
    _owner: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('spatial owner transport is issued from actual carried stocks')

    @property
    def result_id(self):
        return _hash(dict(parent=self.parent.state_id, source=self.source.result_id,
                          graph=self.graph.geometry_id, transport=self.result.result_id))


@dataclass(frozen=True)
class SpatialExteriorAdvance:
    state: SpatialExteriorState
    _record: object = field(repr=False)
    _transport: SpatialTransportResult = field(repr=False)
    _heat: object = field(repr=False)

    _result_id: str | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        _EXCHANGE_RECORD.initialise(self)

    @property
    def result_id(self):
        return _EXCHANGE_RECORD.result_id(self, _hash)

    def record(self):
        return _EXCHANGE_RECORD.record(self, _hash)

    def header(self, *, fields=_EXCHANGE_RECORD.HEADER_FIELDS):
        return _EXCHANGE_RECORD.header(self, fields=fields)

    def close(self):
        _EXCHANGE_RECORD.close(self)

    def audit_arrays(self):
        """The actual accepted numerical results, without re-solving or reseeding."""
        return {**{'spatial-transport:'+k: v for k, v in self._transport.arrays().items()},
                **{'joined-heat:'+k: self._heat.array(k) for k in self._heat.array_names}}


# Joined heat discretisations an owner may declare. The label is recorded in the
# owner definition (and so in its identity); the second entry selects the plan.
HEAT_METHODS = {
    'private-uniform-k-composed': ('PRIVATE uniform-k composed physical-face heat; original transported caloric stocks', 'PRIVATE'),
    'hybrid-mimetic': ('hybrid-mimetic backward Euler; actual current capacities', 'refuse'),
    EXTREMUM: ('cell-centred extremum-preserving backward Euler; actual current capacities', EXTREMUM),
}


class PreparedSpatialOwner:
    """Explicit first-order spatial advection and one joined finite-cell heat solve.

    This route is selected at construction and recorded in the workflow identity.
    It never replaces the ordinary prepared donor-cell or MUSCL method silently.
    All numerical projection allowances are caller supplied in field units.
    """
    def __init__(self, funding, collar, initial_bounds, initial_mesh, *,
                 method, max_projection_errors, budget, finite_stocks=None, measure_policy=None,
                 heat_method='hybrid-mimetic'):
        from .integration_differential_geometry import DifferentialInitialBounds
        self._closed, self._guard = False, None
        if heat_method not in HEAT_METHODS:
            raise TectonicsError('explicit supported joined heat method selection required')
        self._heat_label = HEAT_METHODS[heat_method][0]
        self._finite, self._owns_finite = None, False
        self._initial_geometry = None
        self._measure_policy = None if measure_policy is None else policy_record(measure_policy)
        static = type(initial_bounds) is DifferentialInitialBounds
        if self._measure_policy is not None and not static:
            raise TectonicsError('dual material admission requires prospective static initial geometry')
        if (type(funding) is not FullCellFunding or type(collar) is not PreparedRegionalCollar3D or
                type(initial_bounds) not in (SpatialALEBounds, DifferentialInitialBounds) or type(initial_mesh) is not ExteriorMesh or
                type(budget) is not WorkBudget or any(obj is not budget for obj in
                    (funding._resource, collar._budget, initial_bounds._resource, initial_mesh._resource))):
            raise TectonicsError('actual funding/collar/initial geometry with one shared budget required')
        if method != 'implicit-upwind':
            raise TectonicsError('explicit supported spatial method selection required')
        f, b, mesh = funding.descriptor(), initial_bounds.record(), initial_mesh.record()
        support_id = b['support_id'] if static else b['start_support_id']
        time = b['time_s'] if static else b['start_time_s']
        prior = b['trajectory_id'] if static else b['prior_trajectory_id']
        history = b['trajectory']['segments'] if static else b['trajectory']['segments'][:-1]
        if static:
            if (b.get('scope') != 'initial-current' or history or b['source'] != f['source'] or
                    mesh.get('initial_bounds_id') != initial_bounds.bounds_id or
                    mesh.get('partition_id') != b['partition_id'] or
                    mesh.get('current_geometry_id') != b['current_geometry_id']):
                raise TectonicsError('fresh static material needs its actual complete initial partition, not a future flow')
            self._initial_geometry = dict(family='differential-plate-component-partition-v1',
                initial_bounds_id=initial_bounds.bounds_id, partition_id=b['partition_id'],
                current_geometry_id=b['current_geometry_id'])
        if (b['funding_id'] != funding.funding_id or mesh['funding_id'] != funding.funding_id or
                b['collar_plan_id'] != collar.plan_id or mesh['grid_id'] != b['grid_id'] or
                mesh['support_id'] != support_id or _q(mesh['time_s']) != Q(f['time_s']) or
                _q(time) != Q(f['time_s'])):
            raise TectonicsError('fresh spatial source/support/grid/epoch mismatch')
        self._funding, self._collar, self._budget = funding, collar, budget
        self._configure_fields(f, finite_stocks)
        if type(max_projection_errors) is not dict or set(max_projection_errors) != set(self._names):
            raise TectonicsError('every spatial extensive field needs an explicit absolute numerical allowance')
        self._errors = {k: Q(v) for k, v in max_projection_errors.items()}
        if any(v < 0 for v in self._errors.values()):
            raise TectonicsError('negative spatial numerical allowance')
        self._guard = budget.reserve(65536+3*_width(f)+3*_width(b), category='spatial-owner-plan')
        self._guard.__enter__()
        try:
            self._definition = self._make_definition(f, b['grid_id'], initial_mesh.geometry_id, method)
            self.owner_id = _hash(self._definition)
            exterior = [r for r in b['cells'] if r['kind'] == 'exterior']
            if self._measure_policy is not None:
                width = sum((_q(r['volume_bounds_m3'][1])-_q(r['volume_bounds_m3'][0]) for r in exterior), Q(0))
                if width > _q(self._measure_policy['max_initial_width_m3']):
                    raise TectonicsError('complete initial geometry exceeds declared width allowance')
            mesh_ids = {r['logical_cell_id'] for r in mesh['cells'] if r['kind'] == 'exterior'}
            allocated = {}
            for remainder in funding.exterior_remainder():
                key = (remainder['patch_id'], remainder['sublayer'])
                rows = sorted((r for r in exterior if tuple(r['source_key']) == key), key=lambda r: r['cell_id'])
                stock = remainder['stocks']; total = _q(stock['volume_m3'])
                if not rows or total <= 0:
                    raise TectonicsError('complete positive actual source remainder required')
                # Complete source coverage was established by the actual grid
                # producer. This selects within each enclosure, never fills a
                # geometric gap or changes the original finite source total.
                key_bounds = 'volume_bounds_m3' if static else 'start_volume_bounds_m3'
                if self._measure_policy is None:
                    volumes = _partition([tuple(map(_q, r[key_bounds])) for r in rows], total)
                else:
                    from .integration_dual_geometry import initial_allocation
                    admitted = initial_allocation({r['cell_id']: tuple(map(_q, r[key_bounds])) for r in rows}, total,
                        relative_limits={r['cell_id']: _q(self._measure_policy['initial_relative_error']) for r in rows},
                        max_total_width=_q(self._measure_policy['max_initial_width_m3']), budget=budget)
                    volumes = tuple(admitted['booked'][r['cell_id']] for r in rows)
                for row, volume in zip(rows, volumes):
                    if volume == 0:
                        if row['cell_id'] in mesh_ids:
                            raise TectonicsError('positive thermal cell has no admitted material; refine geometry')
                        continue
                    if row['cell_id'] not in mesh_ids:
                        raise TectonicsError('funded physical cell has no thermal representation')
                    fields = dict.fromkeys(self._names, Q(0))
                    fields['component_mass_kg:'+str(self._keys.index(key))] = _q(stock['mass_kg'])*volume/total
                    fields['enthalpy_j'] = _q(stock['enthalpy_j'])*volume/total
                    fields['tracer:source_kappa'] = _q(stock['source_kappa_mass_kg'])*volume/total
                    if self._measure_policy is not None:
                        fields[B_NAME] = volume
                    allocated[row['cell_id']] = dict(cell_id=row['cell_id'], source_key=row['source_key'],
                        volume_m3=_enc(volume), exact={k: _enc(v) for k, v in fields.items()})
                    if static:
                        allocated[row['cell_id']]['geometry_volume_error_m3'] = [
                            _enc(_q(value)-volume) for value in row[key_bounds]]
            if set(allocated) != mesh_ids:
                raise TectonicsError('initial physical/thermal positive-cell coverage differs')
            initial = dict(schema='atlas.spatial-exterior-state.v1', owner_id=self.owner_id,
                funding_id=funding.funding_id, time_s=f['time_s'], intervals=0, parent_state_id=None,
                collar_state_id=None, support_id=support_id, trajectory_id=prior,
                trajectory={'segments': history}, grid_id=b['grid_id'],
                thermal_mesh_id=initial_mesh.geometry_id, thermal_mesh=mesh,
                cells=[allocated[k] for k in sorted(allocated)],
                projection_accounts={k: _enc(0) for k in self._names})
            if self._finite is not None:
                initial['finite_stock_state'] = self._finite.initial().record()
            if self._measure_policy is not None:
                initial['measure_policy'] = self._measure_policy
                arrays = funding.arrays()
                native_b = np.sum(arrays['component_mass_kg'], axis=0)/collar._native._material.density_kg_m3
                initial['native_material_quadrature_m3'] = [_enc(Q(float(v))) for v in native_b.flat]
                self._check_measures(initial)
            self._initial = self._issue(initial)
            # The decoded funding/bounds tables above are construction scratch,
            # not retained owner state. Funding, mesh and issued inventories have
            # their own leases; do not keep charging abandoned scratch on every
            # future transport/heat interval.
            retained = budget.reserve(8192+3*_width(self._definition)+_width(self._errors)+_width(self._names),
                                      category='spatial-owner-definition')
            retained.__enter__()
            self._guard.__exit__(None, None, None)
            self._guard = retained
        except BaseException:
            self.close(); raise

    def _configure_fields(self, funding, finite_stocks):
        self._keys = tuple(map(tuple, funding['component_keys']))
        self._registry = None
        if 'component_registry' in funding:
            self._registry = ComponentRegistry.from_record(funding['component_registry'], budget=self._budget)
            if self._registry.source_keys != self._keys:
                raise TectonicsError('registry initial component prefix differs from actual source geometry')
            self._registry.validate_native(self._collar._native)
        self._component_count = len(self._registry.rows) if self._registry is not None else len(self._keys)
        self._names = tuple('component_mass_kg:'+str(i) for i in range(self._component_count))
        self._names += ('enthalpy_j',)+tuple(sorted(k for k in self._funding.arrays() if k.startswith('tracer:')))
        if self._measure_policy is not None:
            self._names += (B_NAME,)
        self._nonnegative = tuple(k for k in self._names if k != 'enthalpy_j')
        if finite_stocks is not None:
            if (type(finite_stocks) is not PreparedFiniteStocks or finite_stocks._budget is not self._budget or
                    self._registry is None):
                raise TectonicsError('finite supplies require the actual shared-budget component registry')
            definition = finite_stocks.definition()
            if (definition['registry_id'] != self._registry.registry_id or
                    definition['field_names'] != list(self._names) or
                    definition['nonnegative_fields'] != list(self._nonnegative)):
                raise TectonicsError('finite stock field/component registry differs from the physical owner')
            from .integration_basal_inventory import validate_basal_rows
            from .integration_regional_inventory import validate_birth_stocks
            stocks = definition['initial_stocks']
            validate_basal_rows(self._funding, stocks)
            validate_birth_stocks(self._registry,
                [r for r in stocks if r['lineage'].get('kind') != 'finite-basal-reservoir'],
                native=self._collar._native, funding=self._funding, budget=self._budget)
        elif funding.get('basal_inventory'):
            raise TectonicsError('carved basal material requires its actual finite inventory owner')
        self._finite = finite_stocks

    def _make_definition(self, funding, grid_id, initial_mesh_id, method):
        definition = dict(schema='atlas.spatial-exterior-owner.v1', funding_id=self._funding.funding_id,
            collar_plan_id=self._collar.plan_id, source=funding['source'], grid_id=grid_id,
            initial_mesh_id=initial_mesh_id, component_keys=funding['component_keys'],
            native_initial_state_id=funding['native_initial_state_id'], epoch_s=funding['time_s'],
            method=method, heat_method=self._heat_label,
            projection_allowances={k: _enc(v) for k, v in self._errors.items()},
            conductivity_w_m_k=self._collar._native._material.conductivity_w_m_k,
            heat_capacity_j_kg_k=self._collar._native._material.heat_capacity_j_kg_k,
            source_fields='initialise once; retain every spatial field thereafter',
            scope='finite funded common-rigid exterior and actual regional grid, not arbitrary global plate evolution')
        if self._registry is not None:
            definition['component_registry'] = self._registry.record()
        if self._finite is not None:
            definition['finite_stocks'] = self._finite.definition()
        if self._initial_geometry is not None:
            definition['initial_geometry'] = self._initial_geometry
            definition['scope'] = 'finite funded differential exterior and complete regional grid; explicit supported motion family'
        if self._measure_policy is not None:
            definition['measure_policy'] = self._measure_policy
        return definition

    @classmethod
    def from_migrated_checkpoint(cls, **arguments):
        """Explicit evolved admission, never ordinary root restore or funding."""
        from spatial_transfer import admit_migrated_spatial_owner
        if cls is not PreparedSpatialOwner:
            raise TectonicsError('exact prepared spatial owner required')
        return admit_migrated_spatial_owner(**arguments)

    @classmethod
    def from_saved(cls, funding, collar, definition, initial_record, initial_arrays, *, budget):
        """Rebuild a prepared owner from its bound root, without any flow replay.

        The workflow verifies its immutable root/blob identities. This method
        independently checks the live source/material plan, the saved initial
        source allocation and the actual field arrays. It does not recalculate
        an accepted trajectory, material flux, heat solve or native source.
        """
        if (cls is not PreparedSpatialOwner or type(funding) is not FullCellFunding or
                type(collar) is not PreparedRegionalCollar3D or type(budget) is not WorkBudget or
                funding._resource is not budget or collar._budget is not budget or
                type(definition) is not dict or type(initial_record) is not dict):
            raise TectonicsError('saved owner requires actual funding/collar and one shared budget')
        self = object.__new__(cls)
        self._closed, self._guard, self._initial = False, None, None
        self._finite, self._owns_finite = None, False
        self._initial_geometry = None
        self._measure_policy = (None if 'measure_policy' not in definition else
                                policy_record(definition['measure_policy']))
        # The saved definition names its heat discretisation; an unknown one is
        # refused, never mapped to a default.
        self._heat_label = definition.get('heat_method')
        if self._heat_label not in {label for label, _ in HEAT_METHODS.values()}:
            self._closed = True
            raise TectonicsError('saved owner names an unknown joined heat method')
        self._funding, self._collar, self._budget = funding, collar, budget
        try:
            with budget.reserve(65536+3*_width(definition)+2*_width(initial_record),
                                category='spatial-owner-restore'):
                f = funding.descriptor()
                from spatial_indexed_patch import mesh_header
                _initial_mesh_header = mesh_header(initial_record['thermal_mesh'], budget)
                if 'finite_stocks' in definition:
                    fd = definition['finite_stocks']
                    self._finite = PreparedFiniteStocks(fd['registry_id'], fd['initial_stocks'],
                        field_names=fd['field_names'], nonnegative_fields=fd['nonnegative_fields'], budget=budget)
                    self._owns_finite = True
                    if self._finite.definition() != fd:
                        raise TectonicsError('saved finite funding definition differs')
                self._configure_fields(f, self._finite)
                errors = definition.get('projection_allowances', {})
                if definition.get('method') != 'implicit-upwind' or set(errors) != set(self._names):
                    raise TectonicsError('saved spatial numerical method/allowances differ')
                self._errors = {k: _q(v) for k, v in errors.items()}
                if any(v < 0 for v in self._errors.values()):
                    raise TectonicsError('negative saved spatial numerical allowance')
                if 'initial_geometry' in definition:
                    initial = definition['initial_geometry']
                    if (type(initial) is not dict or set(initial) !=
                            {'family', 'initial_bounds_id', 'partition_id', 'current_geometry_id'} or
                            initial['family'] != 'differential-plate-component-partition-v1' or
                            any(_initial_mesh_header.value.get(k) != initial[k] for k in
                                ('initial_bounds_id', 'partition_id', 'current_geometry_id'))):
                        raise TectonicsError('saved initial differential partition authority differs')
                    self._initial_geometry = json.loads(_json(initial))
                self._definition = self._make_definition(f, definition['grid_id'],
                                                         definition['initial_mesh_id'], definition['method'])
                self.owner_id = _hash(self._definition)
                if definition != dict(owner_id=self.owner_id, **self._definition):
                    raise TectonicsError('saved owner differs from the actual material/source/plan')
                if (initial_record.get('intervals') != 0 or initial_record.get('time_s') != f['time_s'] or
                        initial_record.get('parent_state_id') is not None or initial_record.get('collar_state_id') is not None or
                        initial_record.get('trajectory') != {'segments': []} or
                        initial_record.get('thermal_mesh_id') != definition['initial_mesh_id'] or
                        any(_q(v) for v in initial_record.get('projection_accounts', {}).values())):
                    raise TectonicsError('saved spatial root is not the original unadvanced material')
                mesh = _initial_mesh_header.value
                if mesh.get('funding_id') != funding.funding_id or mesh.get('grid_id') != definition['grid_id']:
                    raise TectonicsError('saved initial thermal support differs from its funding/grid')
                remainders = {(r['patch_id'], r['sublayer']): r['stocks'] for r in funding.exterior_remainder()}
                volumes = dict.fromkeys(remainders, Q(0))
                for row in _SV.rows(initial_record['cells']):
                    key = tuple(row['source_key'])
                    if key not in remainders:
                        raise TectonicsError('saved initial cell has no source material')
                    stock, volume = remainders[key], _q(row['volume_m3'])
                    total = _q(stock['volume_m3'])
                    if volume <= 0 or total <= 0:
                        raise TectonicsError('saved initial source allocation is not positive')
                    expected = dict.fromkeys(self._names, Q(0))
                    expected['component_mass_kg:'+str(self._keys.index(key))] = _q(stock['mass_kg'])*volume/total
                    expected['enthalpy_j'] = _q(stock['enthalpy_j'])*volume/total
                    expected['tracer:source_kappa'] = _q(stock['source_kappa_mass_kg'])*volume/total
                    if self._measure_policy is not None:
                        expected[B_NAME] = volume
                    if {k: _q(v) for k, v in row['exact'].items()} != expected:
                        raise TectonicsError('saved initial material was changed or reseeded')
                    volumes[key] += volume
                if any(volumes[k] != _q(s['volume_m3']) for k, s in remainders.items()):
                    raise TectonicsError('saved initial source volume is incomplete')
                if self._measure_policy is not None:
                    funded = funding.arrays()['component_mass_kg']
                    native_b = np.sum(funded, axis=0)/collar._native._material.density_kg_m3
                    if initial_record.get('native_material_quadrature_m3') != [_enc(Q(float(v))) for v in native_b.flat]:
                        raise TectonicsError('saved initial native quadrature differs from its actual funding')
                    width = Q(0)
                    relative = _q(self._measure_policy['initial_relative_error'])
                    for row in _SV.rows(initial_record['cells']):
                        b = _q(row['exact'][B_NAME])
                        low, high = (_q(row['volume_m3'])+_q(e) for e in row['geometry_volume_error_m3'])
                        if low <= 0 or low > high or max(abs(b/low-1), abs(b/high-1)) > relative:
                            raise TectonicsError('saved initial quadrature lacks its local accuracy certificate')
                        width += high-low
                    if width > _q(self._measure_policy['max_initial_width_m3']):
                        raise TectonicsError('saved initial geometry exceeds declared width allowance')
                guard = budget.reserve(8192+3*_width(self._definition)+_width(self._errors)+_width(self._names),
                                       category='spatial-owner-definition')
                guard.__enter__()
                self._guard = guard
                self._initial = self.restore(initial_record, initial_arrays)
            return self
        except BaseException:
            self.close(); raise

    def _verify(self):
        if self._closed or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
            raise TectonicsError('closed or changed spatial exterior owner')
        self._collar._verify()

    def descriptor(self):
        self._verify(); return dict(owner_id=self.owner_id, **json.loads(_json(self._definition)))

    @property
    def initial_state(self):
        self._verify()
        if self._initial is None:
            raise TectonicsError('migrated owner has no reseeded initial state; use its transferred endpoint')
        return self._initial

    def _issue(self, record):
        from spatial_indexed_patch import is_compact, issue
        if is_compact(record.get('thermal_mesh')):
            return issue(self, record)
        # Geometry is encoded once as provenance, not multiplied into field
        # workspaces. Exact field stocks and binary reporting arrays are bound.
        with self._budget.reserve(65536+3*_width(record)+32*len(record['cells'])*(len(self._names)+1),
                                  category='spatial-state-encoding'):
            fields = {k: np.asarray([_project(_q(r['exact'][k])) for r in record['cells']]) for k in self._names}
            fields['volume_m3'] = np.asarray([_project(_q(r['volume_m3'])) for r in record['cells']])
            snapshot = RegionalMechanicalSnapshot(record, fields)
            result = object.__new__(SpatialExteriorState)
            object.__setattr__(result, '_snapshot', snapshot); object.__setattr__(result, '_budget', self._budget)
            _retain(result, 8192+snapshot.nbytes, self._budget)
        return result

    def _bound(self, state):
        self._verify()
        if type(state) is not SpatialExteriorState or state._budget is not self._budget:
            raise TectonicsError('issued current spatial state on the actual shared budget required')
        from spatial_indexed_patch import logical_record
        r = logical_record(state)
        if r['owner_id'] != self.owner_id or r['funding_id'] != self._funding.funding_id or r['grid_id'] != self._definition['grid_id']:
            raise TectonicsError('spatial state source/owner/grid differs')
        return r

    def validate_parent(self, state, collar_state, *, _migrated_record=None):
        if _migrated_record is None:
            r = self._bound(state)
            time_s = state.time_s
        else:
            from spatial_transfer import bound_migrated_record
            r = bound_migrated_record(self, state, _migrated_record)
            time_s = r['time_s']
        self._collar._fields(collar_state)
        if time_s != collar_state.native_state.descriptor()['time_s']:
            raise TectonicsError('spatial exterior and native clocks differ')
        if (r['intervals'] == 0 and collar_state.native_state.result_id != self._definition['native_initial_state_id'] or
                r['intervals'] != 0 and r['collar_state_id'] != collar_state.result_id):
            raise TectonicsError('spatial material state has a different native parent')
        if self._measure_policy is not None:
            if B_NAME not in collar_state.fields.array_names:
                raise TectonicsError('dual spatial owner requires explicitly admitted native quadrature')
            actual = [_enc(Q(float(v))) for v in collar_state.fields.array(B_NAME).flat]
            if actual != r.get('native_material_quadrature_m3'):
                raise TectonicsError('native quadrature differs from carried spatial state')

    def close_graph(self, state, source, bounds):
        """Close actual interval geometry using carried volumes, not a reseed."""
        if type(source) is not RegionalCollarSourceFlowStage or source._owner is not self._collar:
            raise TectonicsError('actual pre-advection native source/flow stage required')
        self.validate_parent(state, source.parent)
        if type(bounds) is not SpatialALEBounds or bounds._resource is not self._budget:
            raise TectonicsError('issued space-time source geometry required')
        with LIVE_SPATIAL.record_access(bounds, scope=getattr(self, '_record_scope', None)) as b:
            r = self._bound(state)
            if (b['source_flow_stage_id'] != source.result_id or b['grid_id'] != r['grid_id'] or
                    b['funding_id'] != self._funding.funding_id or b['start_support_id'] != r['support_id'] or
                    b['prior_trajectory_id'] != r['trajectory_id'] or _q(b['start_time_s']) != Q(state.time_s)):
                raise TectonicsError('carried spatial geometry or source-flow binding is stale')
            carried = _carried_start_cells(r, b)
            starts = {key: _q(row['volume_m3']) for key, row in carried.items()}
            for row in b['cells']:
                if row['kind'] == 'collar':
                    lo, hi = map(_q, row['start_volume_bounds_m3'])
                    if lo != hi:
                        raise TectonicsError('native full-cell physical volume is not exact')
                    starts[row['cell_id']] = lo
            family = b.get('physical_geometry_family')
            if family == 'differential-plate-component-partition-v1':
                if self._finite is None:
                    raise TectonicsError('differential supply/export closure requires its actual finite stock owner')
                from .integration_differential_geometry import close_differential_ale
                retained = self._finite.restore(r['finite_stock_state'])
                errors = {key: tuple(map(_q, row['geometry_volume_error_m3']))
                          for key, row in carried.items()}
                errors.update({row['cell_id']: (Q(0), Q(0)) for row in b['cells'] if row['kind'] == 'collar'})
                dual = {}
                if self._measure_policy is not None:
                    booked = {}
                    for row in b['cells']:
                        key = row['cell_id']
                        if row['kind'] == 'algebraic-port':
                            continue
                        starts.setdefault(key, Q(0))
                        booked[key] = (_q(r['native_material_quadrature_m3'][row['index']])
                            if row['kind'] == 'collar' else
                            _q(carried[key]['exact'][B_NAME]) if key in carried else Q(0))
                    dual['material_quadrature_m3'] = booked
                return close_differential_ale(bounds, starts, retained,
                    geometry_volume_errors=errors, budget=self._budget, **dual)
            if family is not None:
                raise TectonicsError('unrecognised physical geometry cannot use common-rigid closure')
            return close_spatial_ale(bounds, starts, budget=self._budget)

    def transport(self, state, source, graph, *, finite_exchanges=None, cancel=None):
        """One joint solve from actual native donor fields and spatial history."""
        if type(source) is not RegionalCollarSourceFlowStage or source._owner is not self._collar:
            raise TectonicsError('actual current native donor source required')
        self.validate_parent(state, source.parent)
        if type(graph) is not SpatialALEGraph or graph._resource is not self._budget:
            raise TectonicsError('issued conservative physical space-time graph required')
        with LIVE_SPATIAL.record_access(graph, scope=getattr(self, '_record_scope', None)) as g:
            r = self._bound(state)
            if (g['source_flow_stage_id'] != source.result_id or g['flow_id'] != source.flow.flow_id or
                    g['parent_state_id'] != source.parent_state_id or g['funding_id'] != self._funding.funding_id or
                    g['grid_id'] != r['grid_id'] or g['start_support_id'] != r['support_id'] or
                    g['prior_trajectory_id'] != r['trajectory_id'] or
                    _q(g['start_time_s']) != Q(state.time_s)):
                raise TectonicsError('spatial transport graph belongs to another real source/state interval')
            previous = _carried_start_cells(r, g)
            if self._measure_policy is not None:
                for row in g.get('inactive_zero_measure_cells', []):
                    before = previous.get(row['cell_id'])
                    if before is not None and (_q(before['volume_m3']) or any(map(_q, before['exact'].values()))):
                        raise TectonicsError('inactive geometry cannot hide carried material or rebase')
            donor = {k: source.inventory.array(k) for k in source.inventory.array_names}
            stocks = {k: [] for k in self._names}
            for row in g['cells']:
                start = _q(row['start_volume_m3'])
                if row['kind'] == 'collar':
                    at = row['index']
                    values = {('component_mass_kg:'+str(i)): Q(float(donor['component_mass_kg'][i].flat[at]))
                              for i in range(self._component_count)}
                    values.update({k: Q(float(donor[k].flat[at])) for k in self._names if not k.startswith('component_mass_kg:')})
                else:
                    before = previous.get(row['cell_id'])
                    if before is None:
                        if start != 0:
                            raise TectonicsError('new spatial cell has unfunded positive start volume')
                        values = dict.fromkeys(self._names, Q(0))
                    else:
                        reference = _q(before['volume_m3'])
                        if self._measure_policy is not None and 'carried_start_geometry_volume_m3' in row:
                            if _q(row['carried_start_geometry_volume_m3']) != reference:
                                raise TectonicsError('geometric rebase has another carried reference')
                        elif start != reference:
                            raise TectonicsError('graph changed a carried physical volume')
                        values = {k: _q(v) for k, v in before['exact'].items()}
                for k in stocks:
                    stocks[k].append(values[k])
            if self._measure_policy is not None and g.get('physical_geometry_family') == 'differential-plate-component-partition-v1':
                bound_b = {row['cell_id']: value for row, value in zip(g['cells'], stocks[B_NAME])}
                bound_b.update({row['cell_id']: Q(0) for row in g.get('inactive_zero_measure_cells', [])})
                if g.get('material_quadrature_m3') != {k: _enc(v) for k, v in bound_b.items()}:
                    raise TectonicsError('geometric closure was prepared with different carried material')
            finite_proposal = None
            transport_graph = g
            if self._finite is not None:
                if type(finite_exchanges) is not list:
                    raise TectonicsError('explicit finite exchange list required, including an empty list')
                if finite_exchanges != g.get('finite_exchanges', []):
                    raise TectonicsError('finite exchanges differ from the issued physical geometry')
                retained = self._finite.restore(r['finite_stock_state'])
                if self._measure_policy is not None and g.get('finite_state_id') != retained.state_id:
                    raise TectonicsError('geometric closure belongs to another finite inventory state')
                finite_proposal = self._finite.prepare(retained, g, stocks, finite_exchanges,
                    source_stage_id=source.result_id, transport_parent_id=state.state_id)
                transport_graph, stocks = finite_proposal._transport_inputs()
            elif finite_exchanges is not None:
                raise TectonicsError('unfunded finite exchange declaration')
            with PreparedSpatialTransport(transport_graph, budget=self._budget) as operator:
                result = operator.advance(stocks, state_id=state.state_id, source_stage_id=source.result_id,
                    max_projection_errors=self._errors, nonnegative_fields=self._nonnegative, cancel=cancel)
            measure_audit = None
            if self._measure_policy is not None:
                prior = {}
                inventory = {} if self._finite is None else {
                    'finite-stock:'+v['stock_id']: v for v in r['finite_stock_state']['stocks']}
                for row in transport_graph['cells']:
                    key = row['cell_id']
                    prior[key] = (_q(inventory[key]['volume_m3']) if key in inventory else
                        _q(previous[key]['volume_m3']) if key in previous else
                        _q(row['start_volume_m3']) if row['kind'] == 'collar' else Q(0))
                measure_audit = _json(transport_audit(transport_graph, result.record(), prior, self._measure_policy,
                                                    budget=self._budget))
            step = object.__new__(SpatialOwnerTransport)
            for k, v in dict(parent=state, source=source, graph=graph, result=result,
                             finite_proposal=finite_proposal, measure_audit=measure_audit, _owner=self).items():
                object.__setattr__(step, k, v)
            _retain(step, 4096+(0 if measure_audit is None else len(measure_audit)), self._budget)
            return step

    def _validate_heat_plan(self, definition, heat_record, mesh):
        """Bind the actual solver identity to this owner's declared operator.

        Older exchanges lacking this evidence cannot establish which solver
        produced their arrays. Refuse them rather than infer a default or replay
        geometry/heat while restoring an accepted state.
        """
        with _SV.access(definition, heat_record) as (definition, heat_record):
            if self._heat_label == 'PRIVATE uniform-k composed physical-face heat; original transported caloric stocks':
                import private_heat_joined_consumer_r6 as J
                return J.validate_plan(self, definition, heat_record, mesh)
            try:
                bound = _SV.is_record(definition) and _SV.identity(definition, _hash) == heat_record.get('plan_id')
            except (TypeError, ValueError):
                bound = False
            if not bound:
                raise TectonicsError('joined heat result lacks its bound solver plan')
            selection = next(option for label, option in HEAT_METHODS.values() if label == self._heat_label)
            conductivity = definition.get('conductivity_w_m_k')
            if (definition.get('schema') != 'atlas.mimetic-heat-plan.v1' or
                    definition.get('positivity_method') != selection or
                    definition.get('geometry_id') != heat_record.get('geometry_id') or
                    definition.get('cells') != len(mesh['cells']) or definition.get('faces') != len(mesh['faces']) or
                    type(conductivity) is not list or len(conductivity) != len(mesh['cells']) or
                    any(value != self._definition['conductivity_w_m_k'] for value in conductivity)):
                raise TectonicsError('joined heat plan differs from the owner method, conductivity or endpoint')

    def heat(self, step, mesh, *, boundary=None, cancel=None, execution=None,
             absolute_residual_target=None, checkpoint_store=None):
        """One heat solve from current spatial material, with no extra source."""
        if self._heat_label == 'PRIVATE uniform-k composed physical-face heat; original transported caloric stocks':
            import private_heat_joined_consumer_r6 as J
            return J.forward(self, step, mesh, boundary=boundary,
                absolute_residual_target=absolute_residual_target, execution=execution,
                store=checkpoint_store, cancel=cancel)
        if type(step) is not SpatialOwnerTransport or step._owner is not self:
            raise TectonicsError('actual carried spatial transport stage required')
        if type(mesh) is not ExteriorMesh or mesh._resource is not self._budget:
            raise TectonicsError('issued source-bound physical thermal geometry required')
        with LIVE_SPATIAL.input_stack() as _live_inputs, LIVE_SPATIAL.record_access(step.graph, scope=getattr(self, '_record_scope', None)) as g:
            t = _live_inputs.enter_context(LIVE_SPATIAL.transport_access(step.result, scope=getattr(self, '_record_scope', None)))
            m = LIVE_SPATIAL.mesh_input(mesh)
            if (m['funding_id'] != self._funding.funding_id or m['support_id'] != g['end_support_id'] or
                    m['grid_id'] != g['grid_id'] or m['trajectory_id'] != g['trajectory_id'] or
                    m['time_s'] != g['end_time_s']):
                raise TectonicsError('thermal geometry is not this transported endpoint')
            # A mesh whose cells were named by an exact closure belongs to that
            # one closed graph, which must be the graph transported here.
            if 'booked_cell_rule' in m and (type(m['booked_cell_rule']) is not dict or
                    m['booked_cell_rule'].get('closed_graph_id') != step.graph.geometry_id):
                raise TectonicsError('thermal cells were booked by another closed graph than the transported one')
            columns = {key: i for i, key in enumerate(t['cell_ids'])}
            positive = {row['cell_id'] for row in g['cells'] if _q(row['end_volume_m3']) > 0}
            if {row['logical_cell_id'] for row in m['cells']} != positive:
                raise TectonicsError('physical endpoint cells and thermal mesh differ; no material may be omitted')
            if not set(m.get('required_thermal_boundary_faces', ())).issubset({} if boundary is None else boundary):
                raise TectonicsError('open native and reservoir-cut thermal faces require explicitly declared conditions')
            cp = self._collar._native._material.heat_capacity_j_kg_k
            E, C = [], []
            for row in m['cells']:
                at = columns[row['logical_cell_id']]
                E.append(_project(_q(t['exact_stocks']['enthalpy_j'][at])))
                mass = np.asarray([_project(_q(t['exact_stocks']['component_mass_kg:'+str(i)][at]))
                                   for i in range(self._component_count)])
                # Matches the existing native endpoint operation order exactly.
                C.append(float(np.sum(mass)*cp))
            geometry = LIVE_SPATIAL.thermal_geometry(mesh, m, self._budget, MimeticGeometry)
            selection = next(option for label, option in HEAT_METHODS.values() if label == self._heat_label)
            with PreparedMimeticHeat3D(geometry, self._definition['conductivity_w_m_k'], budget=self._budget,
                                       positivity_method=selection) as plan:
                return plan.advance(E, C, step.source.duration_s, state_id=step.result.result_id,
                                    source_w=0., boundary=boundary, cancel=cancel)

    def finish(self, step, mesh, heat, collar_advance, *, cancel=None):
        """Bind both actual endpoints; this still does not publish either one."""
        if self._heat_label == 'PRIVATE uniform-k composed physical-face heat; original transported caloric stocks':
            import private_heat_joined_consumer_r6 as J
            return J.finish(self, step, mesh, heat, collar_advance, cancel=cancel)
        from .integration_mimetic_heat import MimeticHeatResult
        from .regional_collar3d import RegionalCollarAdvance
        if (type(step) is not SpatialOwnerTransport or step._owner is not self or
                type(mesh) is not ExteriorMesh or type(heat) is not MimeticHeatResult or
                type(collar_advance) is not RegionalCollarAdvance or
                collar_advance.transport_stage is None or collar_advance.heat_stage is None or
                collar_advance.transport_stage.spatial_result is not step.result or
                collar_advance.transport_stage.spatial_graph is not step.graph or
                collar_advance.heat_stage.joined_result is not heat or
                collar_advance.heat_stage.joined_mesh is not mesh):
            raise TectonicsError('actual joint transport/heat/native endpoint chain required')
        self.validate_parent(step.parent, step.source.parent)
        with LIVE_SPATIAL.input_stack() as _live_inputs, LIVE_SPATIAL.record_access(step.graph, scope=getattr(self, '_record_scope', None)) as graph:
            old = self._bound(step.parent)
            transported = _live_inputs.enter_context(LIVE_SPATIAL.transport_access(step.result, scope=getattr(self, '_record_scope', None)))
            metric, heat_meta = LIVE_SPATIAL.mesh_input(mesh), heat.descriptor()
            if (heat_meta['state_id'] != step.result.result_id or heat_meta['geometry_id'] != mesh.geometry_id or
                    mesh._resource is not self._budget or heat._budget is not self._budget):
                raise TectonicsError('spatial heat is not this actual advected inventory and endpoint mesh')
            heat_plan = heat.plan_descriptor()
            self._validate_heat_plan(heat_plan, heat_meta, metric)
            thermal = {row['logical_cell_id']: i for i, row in enumerate(metric['cells'])}
            cells, projection = LIVE_SPATIAL.cell_sink(self, cancel), {k: _q(v) for k, v in old['projection_accounts'].items()}
            physical_count = len(graph['cells'])
            for name in self._names:
                # Finite inventory nodes carry their OWN residual accounts; include
                # only physical rows here so the combined workflow counts each once.
                projection[name] += sum(map(_q, transported['exact_projection_accounts'][name][:physical_count]), Q(0))
            if LIVE_SPATIAL.EARLY_RELEASE:
                # Every projection column was read once, above.
                LIVE_SPATIAL.release_columns(transported, 'exact_projection_accounts')
            exact = transported['exact_stocks']
            native = collar_advance.state.fields
            for at, row in enumerate(graph['cells']):
                volume = _q(row['end_volume_m3'])
                fields = {k: _q(exact[k][at]) for k in self._names}
                if volume == 0:
                    if any(fields.values()):
                        raise TectonicsError('vanished cell retained physical fields')
                    continue
                hi = thermal[row['cell_id']]
                # The binary HMM solve consumes projected transported energy. Its
                # actual local energy equation supplies the signed residual below;
                # no correction is added to the solved temperature or material.
                projection['enthalpy_j'] += fields['enthalpy_j']-Q(float(heat.array('input_enthalpy_j')[hi]))
                projection['enthalpy_j'] -= _q(heat_meta['exact_cell_storage_residual_j'][hi])
                fields['enthalpy_j'] = Q(float(heat.array('enthalpy_j')[hi]))
                if row['kind'] == 'collar':
                    ni = row['index']
                    for name in self._names:
                        actual = (native.array('component_mass_kg')[int(name.rsplit(':', 1)[1])].flat[ni]
                                  if name.startswith('component_mass_kg:') else native.array(name).flat[ni])
                        if name == 'enthalpy_j':
                            if Q(float(actual)) != fields[name]:
                                raise TectonicsError('native endpoint changed the actual joined heat result')
                        else:
                            projection[name] += fields[name]-Q(float(actual))
                else:
                    cells.append(dict(cell_id=row['cell_id'], source_key=row['source_key'],
                        volume_m3=_enc(volume), exact={k: _enc(v) for k, v in fields.items()}))
                    if graph.get('physical_geometry_family') == 'differential-plate-component-partition-v1':
                        cells[-1]['geometry_volume_error_m3'] = row['geometry_volume_error_m3']
            if LIVE_SPATIAL.EARLY_RELEASE:
                # Stock columns and the thermal lookup end with the cell loop.
                exact = thermal = None
                LIVE_SPATIAL.release_columns(transported, 'exact_stocks')
            end = float(_q(graph['end_time_s']))
            if Q(end) != _q(graph['end_time_s']) or end != collar_advance.state.native_state.descriptor()['time_s']:
                raise TectonicsError('shared spatial/native endpoint clock cannot be represented exactly')
            LIVE_SPATIAL.sort_cells(cells)
            record = dict(schema='atlas.spatial-exterior-state.v1', owner_id=self.owner_id,
                funding_id=self._funding.funding_id, time_s=end, intervals=old['intervals']+1,
                parent_state_id=step.parent.state_id, collar_state_id=collar_advance.state.result_id,
                support_id=graph['end_support_id'], trajectory_id=graph['trajectory_id'],
                trajectory=graph['trajectory'], grid_id=graph['grid_id'], thermal_mesh_id=mesh.geometry_id,
                thermal_mesh=LIVE_SPATIAL.mesh_value(mesh, metric), cells=LIVE_SPATIAL.state_cells(cells),
                projection_accounts={k: _enc(v) for k, v in projection.items()})
            if self._finite is not None:
                record['finite_stock_state'] = self._finite.finish(step.finite_proposal, step.result).record()
            if self._measure_policy is not None:
                record['measure_policy'] = self._measure_policy
                record['native_material_quadrature_m3'] = [_enc(Q(float(v))) for v in native.array(B_NAME).flat]
                self._check_measures(record)
            state = self._issue(record)
            del record, cells, old, metric, thermal, native, exact
            exchange = dict(schema='atlas.spatial-exterior-advance.v1', owner_id=self.owner_id,
                parent_state_id=step.parent.state_id, collar_state_id=collar_advance.state.result_id,
                source_flow_stage_id=step.source.result_id, source_audit_id=step.source.source_stage.source_audit.result_id,
                spatial_graph_id=step.graph.geometry_id, spatial_graph=LIVE_SPATIAL.reference(graph),
                global_transport_id=step.result.result_id, transport=LIVE_SPATIAL.reference(transported),
                joined_heat_id=heat.result_id, joined_heat=heat_meta, joined_heat_plan=heat_plan,
                heat_boundary_account='outward boundary energy remains an actual external heat transfer',
                physical_geometry='true volumes; thermal surrogate errors remain separately declared')
            if step.finite_proposal is not None:
                exchange['finite_proposal'] = step.finite_proposal.record()
            if step.measure_audit is not None:
                exchange['dual_measure_audit'] = json.loads(step.measure_audit)
            if LIVE_SPATIAL.active_scope(self._budget) is not None:
                result = _EXCHANGE_RECORD.build_advance(SpatialExteriorAdvance, state, exchange,
                    step.result, heat, scope=_EXCHANGE_RECORD.required_scope(self), check=lambda: LIVE_SPATIAL.check_cancel(cancel))
            else:
                with self._budget.reserve(65536+3*_width(exchange), category='spatial-exchange-encoding'):
                    result = SpatialExteriorAdvance(state, _json(exchange), step.result, heat)
                    _retain(result, 8192+len(result._record), self._budget)
            del exchange, graph, transported
            return result

    def _check_measures(self, record):
        """The saved physical, native and finite inventories share one limit."""
        if record.get('measure_policy') != self._measure_policy:
            raise TectonicsError('saved dual-measure policy differs from its owner')
        native = record.get('native_material_quadrature_m3')
        boxes = self._collar.cell_geometries()
        if type(native) is not list or len(native) != len(boxes):
            raise TectonicsError('complete carried native material quadrature required')
        cells = _SV.appendable_rows(record['cells'])
        for i, box in enumerate(boxes):
            if _q(native[i]) <= 0:
                raise TectonicsError('empty native constitutive cells are unsupported')
            cells.append(dict(cell_id='native-measure:'+str(i), volume_m3=_enc(box.volume_m3),
                              exact={B_NAME: native[i]}))
        for row in record.get('finite_stock_state', {}).get('stocks', []):
            cells.append(dict(cell_id='finite-stock:'+row['stock_id'],
                              volume_m3=row['volume_m3'], exact=row['exact']))
        check_state_cells(cells, self._measure_policy)

    def restore_compact(self, envelope, arrays, *, compact_mesh, expected_mesh_reference):
        from spatial_indexed_patch import restore_compact
        return restore_compact(self, envelope, arrays, compact_mesh=compact_mesh,
                               expected_mesh_reference=expected_mesh_reference)

    def restore(self, record, arrays, *, _validate_only=False):
        """Restore immutable saved fields, never recompute their heat or motion."""
        self._verify()
        if not _SV.is_state_record(record) or record.get('schema') != 'atlas.spatial-exterior-state.v1':
            raise TectonicsError('saved spatial state schema mismatch')
        body = {k: v for k, v in record.items() if k != 'state_id'}
        if self._finite is not None:
            saved_finite = self._finite.restore(body.get('finite_stock_state'))
            if saved_finite.record()['intervals'] != body.get('intervals'):
                raise TectonicsError('saved finite and physical interval counts differ')
        elif 'finite_stock_state' in body:
            raise TectonicsError('saved finite stock has no declared owner')
        if self._measure_policy is not None:
            self._check_measures(body)
        elif 'measure_policy' in body or 'native_material_quadrature_m3' in body:
            raise TectonicsError('dual-measure state requires its explicitly declared owner')
        if (body.get('owner_id') != self.owner_id or body.get('funding_id') != self._funding.funding_id or
                body.get('grid_id') != self._definition['grid_id'] or
                set(body.get('projection_accounts', {})) != set(self._names)):
            raise TectonicsError('saved spatial source/owner/field schema changed')
        from spatial_indexed_patch import mesh_header, mesh_identity, exterior_ids
        _mesh_header_owner = mesh_header(body['thermal_mesh'], self._budget)
        mesh = _mesh_header_owner.value
        if _validate_only:
            from spatial_transfer import _stream_hash as mesh_hash
        else:
            mesh_hash = _hash
        if (mesh_identity(body['thermal_mesh'], mesh_hash) != body['thermal_mesh_id'] or mesh['support_id'] != body['support_id'] or
                mesh['trajectory_id'] != body['trajectory_id'] or _q(mesh['time_s']) != Q(body['time_s'])):
            raise TectonicsError('saved spatial geometry/time/trajectory identity differs')
        seen = set()
        for row in _SV.rows(body['cells']):
            if row['cell_id'] in seen or _q(row['volume_m3']) <= 0 or set(row['exact']) != set(self._names):
                raise TectonicsError('saved spatial positive-cell layout differs')
            seen.add(row['cell_id'])
            if any(_q(row['exact'][name]) < 0 for name in self._nonnegative):
                raise TectonicsError('saved spatial material contains negative fields')
            if mesh.get('physical_geometry_family') == 'differential-plate-component-partition-v1':
                error = row.get('geometry_volume_error_m3')
                if type(error) is not list or len(error) != 2:
                    raise TectonicsError('saved differential volume needs its carried signed geometric enclosure')
                low, high = map(_q, error)
                if low > high or _q(row['volume_m3'])+high <= 0:
                    raise TectonicsError('saved signed geometric volume enclosure is invalid')
        if seen != set(exterior_ids(body['thermal_mesh'], self._budget)):
            raise TectonicsError('saved physical and thermal exterior cells differ')
        if _validate_only:
            from spatial_indexed_patch import validate_projected_payload
            return validate_projected_payload(self, body, arrays, record.get('state_id'))
        result = self._issue(body)
        expected = result.arrays()
        if (result.state_id != record.get('state_id') or set(arrays) != set(expected) or
                any(not np.array_equal(arrays[k], a) for k, a in expected.items())):
            raise TectonicsError('saved exact inventories and projected arrays disagree')
        return result

    def validate_exchange(self, state, exchange, *, audit_arrays=None,
                          composed_checkpoint=None, collar_state=None, cancel=None):
        """Verify the saved chain's actual bindings without repeating a solve."""
        with _SV.access(exchange) as exchange:
            r = self._bound(state)
            composed = _SV.is_record(exchange) and exchange.get('schema') == 'atlas.private.spatial-composed-advance.r1'
            if (not _SV.is_record(exchange) or not composed and exchange.get('schema') != 'atlas.spatial-exterior-advance.v1' or
                    exchange.get('state_id') != state.state_id or exchange.get('owner_id') != self.owner_id or
                    exchange.get('parent_state_id') != r['parent_state_id'] or
                    exchange.get('collar_state_id') != r['collar_state_id'] or
                    _SV.identity(exchange['spatial_graph'], _hash) != exchange['spatial_graph_id'] or
                    exchange['transport']['result_id'] != exchange['global_transport_id'] or
                    exchange['joined_heat']['state_id'] != exchange['global_transport_id'] or
                    exchange['joined_heat']['geometry_id'] != r['thermal_mesh_id']):
                raise TectonicsError('saved spatial exchange is not the actual published state chain')
            self._validate_heat_plan(exchange.get('joined_heat_plan'), exchange['joined_heat'], r['thermal_mesh'])
            body = _SV.exchange_identity(exchange, state.state_id, _hash)
            if body != exchange.get('result_id'):
                raise TectonicsError('saved spatial exchange identity differs')
            if type(audit_arrays) is not dict:
                raise TectonicsError('actual spatial transport and heat arrays are required on restore')
            transport = {k.removeprefix('spatial-transport:'): v for k, v in audit_arrays.items()
                         if k.startswith('spatial-transport:')}
            heat = {k.removeprefix('joined-heat:'): v for k, v in audit_arrays.items()
                    if k.startswith('joined-heat:')}
            if len(transport)+len(heat) != len(audit_arrays) or not transport or not heat:
                raise TectonicsError('saved spatial audit fields differ')
            with self._budget.reserve(65536+3*_SV.native_width(exchange, _width)+3*sum(v.nbytes for v in audit_arrays.values()),
                                      category='spatial-audit-restore'):
                tr = RegionalMechanicalSnapshot({k: v for k, v in exchange['transport'].items() if k != 'result_id'}, transport)
                if composed:
                    import private_heat_joined_consumer_r6 as J
                    heat_id = J.validate_saved_exchange(self, state, exchange, audit_arrays,
                        composed_checkpoint, collar_state=collar_state, cancel=cancel)
                else:
                    hr = RegionalMechanicalSnapshot(exchange['joined_heat'], heat)
                    heat_id = hr.result_id
                if tr.result_id != exchange['global_transport_id'] or heat_id != exchange['joined_heat_id']:
                    raise TectonicsError('saved actual spatial transport or heat arrays changed')
                if self._finite is not None:
                    finite = exchange.get('finite_proposal')
                    if not _SV.is_record(finite) or finite.get('transport_parent_id') != r['parent_state_id']:
                        raise TectonicsError('saved finite proposal belongs to a different physical parent')
                    self._finite.validate_saved(r['finite_stock_state'], finite, exchange['transport'])
                elif 'finite_proposal' in exchange:
                    raise TectonicsError('saved finite proposal has no actual stock owner')
                if self._measure_policy is not None:
                    audit = exchange.get('dual_measure_audit')
                    if type(audit) is not dict:
                        raise TectonicsError('saved dual transport audit is missing')
                    graph = (exchange['finite_proposal']['graph'] if self._finite is not None
                             else exchange['spatial_graph'])
                    actual = transport_audit(graph, exchange['transport'],
                        {k: _q(v) for k, v in audit['prior_geometry_m3'].items()}, self._measure_policy,
                        budget=self._budget)
                    if actual != audit:
                        raise TectonicsError('saved dual transport audit differs from its actual solve')
                    positions = {k: i for i, k in enumerate(exchange['transport']['cell_ids'])}
                    transported_b = exchange['transport']['exact_stocks'][B_NAME]
                    for cell in _SV.rows(r['cells']):
                        if cell['exact'][B_NAME] != transported_b[positions[cell['cell_id']]]:
                            raise TectonicsError('saved exterior quadrature changed after transport')
                    for cell in exchange['spatial_graph']['cells']:
                        if cell['kind'] == 'collar':
                            b = _enc(Q(_project(_q(transported_b[positions[cell['cell_id']]]))))
                            if r['native_material_quadrature_m3'][cell['index']] != b:
                                raise TectonicsError('saved native quadrature changed after transport')
                elif 'dual_measure_audit' in exchange:
                    raise TectonicsError('legacy exchange cannot contain a dual-measure audit')

    def close(self):
        if not self._closed:
            self._closed = True
            self._initial = None
            if self._owns_finite and self._finite is not None:
                self._finite.close()
            self._registry = None
            if self._guard is not None:
                self._guard.__exit__(None, None, None); self._guard = None

    def __enter__(self):
        self._verify(); return self

    def __exit__(self, *_):
        self.close()
import spatial_validation_patch as _SV  # compact validation r1
