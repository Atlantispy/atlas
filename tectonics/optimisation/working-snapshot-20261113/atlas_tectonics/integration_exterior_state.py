"""Carried first-order exterior FV inventories and paired collar exchanges.

The geometry owner issues wall measures; this module never samples source
temperature after admission. Exact extensive records are authoritative. Float
arrays are reporting/native projections and their differences remain numerical
accounts, not added rock or heat. Publication belongs to the common clock.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
import weakref

import numpy as np

from ._validation import TectonicsError
from .integration_collar_geometry import FullCellFunding
from .integration_regional_inventory import _width, _project
from .regional_collar3d import (PreparedRegionalCollar3D, RegionalCollarAdvance,
    RegionalCollarTransportStage, RigidCollarMotion)
from .regional_execution import RegionalMechanicalSnapshot
from .regional_execution3d import SIDES, _hash, _json
from .resources import WorkBudget

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class ExteriorRefused(TectonicsError):
    """Unfunded, stale, incompatible or unlocated exterior exchange."""


def _enc(value):
    value = Q(value)
    return [hex(value.numerator), hex(value.denominator)]


def _q(pair):
    if type(pair) is not list or len(pair) != 2 or any(type(v) is not str for v in pair):
        raise ExteriorRefused('canonical exact rational pair required')
    try:
        value = Q(int(pair[0], 16), int(pair[1], 16))
    except (ValueError, ZeroDivisionError) as exc:
        raise ExteriorRefused('invalid exact exterior inventory') from exc
    if _enc(value) != pair:
        raise ExteriorRefused('noncanonical exact exterior inventory')
    return value


def _retain(obj, size, budget):
    lease = budget.reserve(size, category='exterior-fv-retained')
    lease.__enter__()
    try:
        weakref.finalize(obj, lease.__exit__, None, None, None)
    except BaseException:
        lease.__exit__(None, None, None)
        raise


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ExteriorFVState:
    _snapshot: RegionalMechanicalSnapshot = field(repr=False)
    _budget: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('ExteriorFVState is issued by PreparedExteriorOwner')

    @property
    def state_id(self):
        return self._snapshot.result_id

    @property
    def result_id(self):
        return self.state_id

    @property
    def time_s(self):
        return self._snapshot.descriptor()['time_s']

    def record(self):
        return dict(state_id=self.state_id, **self._snapshot.descriptor())

    def arrays(self):
        return {k: self._snapshot.array(k) for k in self._snapshot.array_names}


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ExteriorOffer:
    _metadata: bytes = field(repr=False)
    boundary_stocks: object
    _budget: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('ExteriorOffer is issued by PreparedExteriorOwner.prepare')

    @property
    def offer_id(self):
        return hashlib.sha256(self._metadata).hexdigest()

    @property
    def duration_s(self):
        return json.loads(self._metadata)['duration_s']

    def record(self):
        return dict(offer_id=self.offer_id, **json.loads(self._metadata))


@dataclass(frozen=True)
class ExteriorAdvance:
    state: ExteriorFVState
    _metadata: bytes = field(repr=False)

    @property
    def result_id(self):
        return _hash(dict(state_id=self.state.state_id, exchange=json.loads(self._metadata)))

    def record(self):
        return dict(result_id=self.result_id, state_id=self.state.state_id, **json.loads(self._metadata))


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ExteriorTransportStage:
    """Unpublished exact advective stocks, before a bound thermal endpoint."""
    _snapshot: RegionalMechanicalSnapshot = field(repr=False)
    _exchange: bytes = field(repr=False)
    _native_stage: RegionalCollarTransportStage = field(repr=False)
    _budget: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('exterior transport stages are issued by the owner')

    @property
    def result_id(self):
        return _hash(dict(stocks_id=self._snapshot.result_id, exchange=json.loads(self._exchange),
                          collar_transport_stage_id=self._native_stage.result_id))

    def record(self):
        return dict(schema='atlas.exterior-fv-transport-stage.v1', result_id=self.result_id,
            transported_state=self._snapshot.descriptor(), exchange=json.loads(self._exchange),
            collar_transport_stage_id=self._native_stage.result_id,
            scope='unpublished advected stocks; no completed collar or thermal endpoint')

    def arrays(self):
        return {k: self._snapshot.array(k) for k in self._snapshot.array_names}


class PreparedExteriorOwner:
    """Actual source-cell inventory; coarse moving control volumes are explicit.

    The first mesh has one cell per funded source patch/sublayer CSG remainder.
    Its source key, radial support, exclusion union and lineage are retained.
    This is a first-order well-mixed spatial discretisation, not an assertion of
    unresolved mixing accuracy. A geometry-issued spatial refinement is required
    before these coarse cells can be represented as finer material support.
    """
    def __setattr__(self, name, value):
        if not name.startswith('_') and hasattr(self, name):
            raise ExteriorRefused('prepared exterior definition is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, funding, collar, *, budget):
        if (type(funding) is not FullCellFunding or type(collar) is not PreparedRegionalCollar3D or
                type(budget) is not WorkBudget or funding._resource is not budget or collar._budget is not budget):
            raise ExteriorRefused('issued physical funding, actual collar and shared budget required')
        definition = funding.descriptor()
        if definition['collar_plan_id'] != collar.plan_id:
            raise ExteriorRefused('exterior funding belongs to another collar')
        self._collar, self._funding, self._budget = collar, funding, budget
        self._closed = False
        self._guard = budget.reserve(65536+4*_width(definition), category='exterior-fv-plan')
        self._guard.__enter__()
        try:
            self._native_keys = tuple(tuple(k) for k in definition['component_keys'])
            self._keys = tuple(sorted((r['patch_id'], r['sublayer']) for r in funding.exterior_remainder()))
            if len(set(self._keys)) != len(self._keys) or not set(self._native_keys) <= set(self._keys):
                raise ExteriorRefused('unique complete source remainder components required')
            self._tracers = tuple(sorted(k[7:] for k in funding.arrays() if k.startswith('tracer:')))
            self._fields = ('volume_m3', 'component_mass_kg', 'enthalpy_j')+tuple('tracer:'+k for k in self._tracers)
            self._definition = dict(schema='atlas.exterior-fv-owner.v1', funding_id=funding.funding_id,
                collar_plan_id=collar.plan_id, source=definition['source'],
                native_initial_state_id=definition['native_initial_state_id'],
                component_keys=[list(k) for k in self._keys], native_component_keys=[list(k) for k in self._native_keys],
                tracer_names=list(self._tracers), epoch_s=definition['time_s'],
                discretisation='first-order well-mixed moving source patch/layer CSG cells; no source-field resampling',
                geometry='rotated source cone/shell minus fixed complete collar exclusion union',
                refinement='explicit source-cell lineage; no automatic spatial refinement or subcell accuracy claim')
            self.owner_id = _hash(self._definition)
            cells = []
            for row in funding.exterior_remainder():
                key = row['patch_id'], row['sublayer']
                stock = row['stocks']
                values = {name: Q(0) for name in self._fields if name != 'component_mass_kg'}
                values['volume_m3'] = _q(stock['volume_m3'])
                values['enthalpy_j'] = _q(stock['enthalpy_j'])
                values['tracer:source_kappa'] = _q(stock['source_kappa_mass_kg'])
                mass = [Q(0)]*len(self._keys); mass[self._keys.index(key)] = _q(stock['mass_kg'])
                cell_id = _hash(dict(funding_id=funding.funding_id, source_key=key,
                    radial_layer=row['radial_layer'], exclusions=definition['cell_geometries']))
                cells.append(dict(cell_id=cell_id, source_key=list(key), parent_cell_id=None,
                    support=dict(radial_layer=row['radial_layer'], patch_id=row['patch_id'],
                        funding_id=funding.funding_id, exclusions='funding.cell_geometries',
                        geometry_volume_enclosure_m3=row['geometry_volume_enclosure_m3']),
                    exact={k: [_enc(v) for v in mass] if k == 'component_mass_kg' else _enc(values[k])
                           for k in self._fields}))
            cells.sort(key=lambda r: tuple(r['source_key']))
            self._cell_definition = {tuple(r['source_key']): {k: v for k, v in r.items() if k != 'exact'} for r in cells}
            self._initial_state = self._issue(dict(schema='atlas.exterior-fv-state.v1', owner_id=self.owner_id,
                funding_id=funding.funding_id, time_s=definition['time_s'], intervals=0,
                parent_state_id=None, collar_state_id=None, support_id=None, trajectory=None,
                trajectory_id=_hash([]),
                cells=cells, geometry_projection_intervals_m3=[
                    [_enc(self._values(row)['volume_m3']-_q(row['support']['geometry_volume_enclosure_m3'][1])),
                     _enc(self._values(row)['volume_m3']-_q(row['support']['geometry_volume_enclosure_m3'][0]))]
                    for row in cells],
                projection_accounts={k: _enc(0) for k in self._account_names()}))
        except BaseException:
            self._guard.__exit__(None, None, None); self._guard = None
            raise

    def _verify(self):
        if self._closed or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
            raise ExteriorRefused('closed or changed exterior owner source')
        self._collar._verify()

    def descriptor(self):
        self._verify()
        return dict(owner_id=self.owner_id, **json.loads(_json(self._definition)))

    @property
    def initial_state(self):
        self._verify()
        return self._initial_state

    def _account_names(self):
        return ('volume_m3', 'enthalpy_j')+tuple('component_mass_kg:'+str(i) for i in range(len(self._keys)))+tuple('tracer:'+k for k in self._tracers)

    def _values(self, row):
        exact = row['exact']
        if type(exact) is not dict or set(exact) != set(self._fields):
            raise ExteriorRefused('exterior carried field schema changed')
        if type(exact['component_mass_kg']) is not list or len(exact['component_mass_kg']) != len(self._keys):
            raise ExteriorRefused('exterior component vector changed')
        values = {k: tuple(_q(q) for q in v) if k == 'component_mass_kg' else _q(v) for k, v in exact.items()}
        if any(q < 0 for k, v in values.items() for q in (v if k == 'component_mass_kg' else (v,))):
            raise ExteriorRefused('negative exterior inventory')
        if values['volume_m3'] == 0 and any(q != 0 for k, v in values.items() if k != 'volume_m3'
                for q in (v if k == 'component_mass_kg' else (v,))):
            raise ExteriorRefused('empty exterior cell contains material or heat')
        return values

    def _arrays(self, record):
        rows = [self._values(row) for row in record['cells']]
        return {name: np.asarray([[_project(v) for v in row[name]] for row in rows], dtype=float).T
                if name == 'component_mass_kg' else np.asarray([_project(row[name]) for row in rows])
                for name in self._fields}

    def _issue(self, record):
        with self._budget.reserve(65536+16*_width(record), category='exterior-fv-state-encoding'):
            snapshot = RegionalMechanicalSnapshot(record, self._arrays(record))
            result = object.__new__(ExteriorFVState)
            object.__setattr__(result, '_snapshot', snapshot)
            object.__setattr__(result, '_budget', self._budget)
            _retain(result, 8192+2*snapshot.nbytes+4*_width(record), self._budget)
            return result

    def _bound(self, state):
        self._verify()
        if type(state) is not ExteriorFVState or state._budget is not self._budget:
            raise ExteriorRefused('issued shared-budget exterior state required')
        record = state.record()
        if (record.get('schema') != 'atlas.exterior-fv-state.v1' or
                record['owner_id'] != self.owner_id or record['funding_id'] != self._funding.funding_id):
            raise ExteriorRefused('exterior state belongs to another source/owner')
        if tuple(tuple(row['source_key']) for row in record['cells']) != self._keys:
            raise ExteriorRefused('exterior geometric cells changed without issued refinement')
        if set(record['projection_accounts']) != set(self._account_names()):
            raise ExteriorRefused('exterior numerical account layout changed')
        for pair in record['projection_accounts'].values():
            _q(pair)
        if len(record['geometry_projection_intervals_m3']) != len(self._keys):
            raise ExteriorRefused('exterior geometric projection account layout changed')
        for pair in record['geometry_projection_intervals_m3']:
            if type(pair) is not list or len(pair) != 2 or _q(pair[0]) > _q(pair[1]):
                raise ExteriorRefused('invalid exterior geometric projection interval')
        for row in record['cells']:
            expected = self._cell_definition[tuple(row['source_key'])]
            if any(row.get(k) != v for k, v in expected.items()):
                raise ExteriorRefused('exterior source support/cell identity changed without refinement')
            self._values(row)
        return record

    def validate_parent(self, state, collar_state):
        record = self._bound(state)
        self._collar._fields(collar_state)
        if state.time_s != collar_state.native_state.descriptor()['time_s']:
            raise ExteriorRefused('exterior and collar clocks differ')
        if record['intervals'] == 0:
            if collar_state.native_state.result_id != self._definition['native_initial_state_id']:
                raise ExteriorRefused('fresh exterior has another actual native parent')
        elif record['collar_state_id'] != collar_state.result_id:
            raise ExteriorRefused('carried exterior and collar parents differ')

    def _vector(self, row):
        values = self._values(row)
        return (values['volume_m3'], *values['component_mass_kg'], values['enthalpy_j'],
                *(values['tracer:'+k] for k in self._tracers))

    def _exact(self, values):
        n = len(self._keys)
        return dict(volume_m3=_enc(values[0]), component_mass_kg=list(map(_enc, values[1:1+n])),
            enthalpy_j=_enc(values[1+n]), **{'tracer:'+k: _enc(q) for k, q in zip(self._tracers, values[2+n:])})

    @staticmethod
    def _side(value):
        if value not in ('x-', 'x+', 'y-', 'y+', 'z-', 'z+'):
            raise ExteriorRefused('actual signed Cartesian wall side required')
        return value[0]+('0' if value[1] == '-' else '1')

    def prepare(self, state, wall_measures):
        """Issue interval-only inlet parcels from the CURRENT carried fields."""
        from .integration_wall_measures import WallMeasures
        parent = self._bound(state)
        if type(wall_measures) is not WallMeasures or wall_measures._resource is not self._budget:
            raise ExteriorRefused('issued shared-budget geometric wall measures required')
        wall = wall_measures.descriptor()
        with self._budget.reserve(131072+32*(_width(parent)+_width(wall)), category='exterior-fv-offer'):
            if (wall['funding_id'] != self._funding.funding_id or wall['collar_plan_id'] != self._collar.plan_id or
                    wall['parent_state_id'] != state.state_id or _q(wall['start_time_s']) != Q(state.time_s)):
                raise ExteriorRefused('wall measure source, grid, parent or clock changed')
            if (wall['prior_trajectory_id'] != parent['trajectory_id'] or
                    parent['trajectory'] is not None and parent['support_id'] != wall['start_support_id']):
                raise ExteriorRefused('carried absolute trajectory or current support changed')
            segments = wall['trajectory']['segments']
            prefix = [] if parent['trajectory'] is None else parent['trajectory']['segments']
            if segments[:-1] != prefix or wall['trajectory_id'] != _hash(segments):
                raise ExteriorRefused('accepted rigid trajectory prefix changed')
            duration = _q(wall['end_time_s'])-_q(wall['start_time_s'])
            dt = _project(duration)
            if duration <= 0 or Q(dt) != duration or state.time_s+dt != float(_q(wall['end_time_s'])):
                raise ExteriorRefused('wall interval is not exactly representable by the native duration/clock')
            omega_q = tuple(_q(v) for v in segments[-1]['angular_velocity_rad_s'])
            omega = tuple(_project(v) for v in omega_q)
            if tuple(map(Q, omega)) != omega_q:
                raise ExteriorRefused('exact angular velocity cannot be silently changed for native sampling')
            motion = RigidCollarMotion(omega, 'wall-measure:'+wall['measure_id'])
            transport = self._collar._transport
            normals = transport._sample_faces(self._collar.rigid_velocity(motion).reshape(
                *(2*n+1 for n in self._collar.cells), 3))
            exact_rates = self._collar.wall_streams(wall_measures, motion, dt)
            expected, streams = {}, {}
            for axis, label in enumerate('xyz'):
                for end in (0, 1):
                    side = label+str(end); at = 0 if end == 0 else -1
                    expected[side] = _hash(np.take(normals[axis], at, axis=axis).tolist())
                    streams[side] = tuple(rate*dt for rate in exact_rates[side])
            faces = {(self._side(r['side']), tuple(r['face_index'])): r for r in wall['faces']}
            expected_faces = {(side, at) for side in SIDES for at in np.ndindex(streams[side][0].shape)}
            if set(faces) != expected_faces or len(faces) != len(wall['faces']):
                raise ExteriorRefused('each full-grid outer face must be measured once')
            cells = {tuple(r['source_key']): r for r in parent['cells']}
            count = len(self._keys)+2+len(self._tracers)
            debits = {key: [Q(0)]*count for key in self._keys}
            inlet_error = {key: [Q(0)]*count for key in self._keys}
            incoming = {face: [Q(0)]*count for face in faces}
            outgoing = {face: Q(0) for face in faces}
            geometric_credit = {key: Q(0) for key in self._keys}
            for row in wall['rows']:
                face = self._side(row['side']), tuple(row['face_index'])
                key = tuple(row['exterior_cell_key'])
                if face not in faces or key not in cells:
                    raise ExteriorRefused('wall exchange has an unlocated donor or receiver')
                vin, vout = _q(row['inward_volume_m3']), _q(row['outward_volume_m3'])
                if vin < 0 or vout < 0:
                    raise ExteriorRefused('wall stream volumes must be nonnegative')
                old = self._vector(cells[key])
                if vin and old[0] == 0:
                    raise ExteriorRefused('empty exterior donor cannot supply an inlet')
                parcel = tuple(q*vin/old[0] for q in old) if vin else (Q(0),)*count
                deviation = _q(row['inward_max_deviation_m3'])
                if deviation and old[0] == 0:
                    raise ExteriorRefused('uncertain positive inlet support reaches an empty exterior cell')
                error = tuple(q*deviation/old[0] for q in old) if deviation else (Q(0),)*count
                debits[key] = [a+b for a, b in zip(debits[key], parcel)]
                inlet_error[key] = [a+b for a, b in zip(inlet_error[key], error)]
                incoming[face] = [a+b for a, b in zip(incoming[face], parcel)]
                outgoing[face] += vout
                geometric_credit[key] += vout
            for key, debit in debits.items():
                if any(a > b for a, b in zip(debit, self._vector(cells[key]))):
                    raise ExteriorRefused('aggregate interval inlet demand exhausts its actual finite donor')
            n = len(self._native_keys)
            indices = [self._keys.index(k) for k in self._native_keys]
            stocks = {}
            for side in SIDES:
                shape = streams[side][0].shape
                mass, heat = np.zeros((n, *shape)), np.zeros(shape)
                tracers = {k: np.zeros(shape) for k in self._tracers}
                for at in np.ndindex(shape):
                    face = side, at; vector = incoming[face]
                    geometric = faces[face]
                    if vector[0] != _q(geometric['inward_exact_volume_m3']) or outgoing[face] != _q(geometric['outward_exact_volume_m3']):
                        raise ExteriorRefused('located row volumes do not partition the complete signed wall flux')
                    for sign, exact in enumerate((vector[0], outgoing[face])):
                        if bool(exact) != bool(streams[side][sign][at]):
                            raise ExteriorRefused('physical/native stream projection erases or invents a nonzero crossing')
                    if any(vector[1+i] != 0 for i in range(len(self._keys)) if i not in indices):
                        raise ExteriorRefused('inflow contains a component not represented in the actual native law')
                    mass[(slice(None), *at)] = [_project(vector[1+i]) for i in indices]
                    heat[at] = _project(vector[1+len(self._keys)])
                    for j, key in enumerate(self._tracers):
                        tracers[key][at] = _project(vector[2+len(self._keys)+j])
                stocks[side] = transport.boundary_stock(side, streams[side][0], mass, heat, tracers)
            endpoints = {tuple(r['exterior_cell_key']): r for r in wall['exterior_cells']}
            if set(endpoints) != set(self._keys):
                raise ExteriorRefused('every carried exterior cell needs an endpoint geometry/GCL proof')
            geometry_projection = []
            for i, key in enumerate(self._keys):
                row = endpoints[key]
                chosen = _q(row['chosen_volume_change_m3'])
                a, b = map(_q, row['chosen_change_admissible_bounds_m3'])
                if not a <= chosen <= b or chosen != geometric_credit[key]-debits[key][0]:
                    raise ExteriorRefused('chosen exterior volume change is outside its derived geometric bound')
                if parent['intervals'] and row['start_support_id'] != parent['cell_support_ids'][self._keys.index(key)]:
                    raise ExteriorRefused('an exterior geometric cell lost its previous endpoint support')
                error = _q(row['chosen_volume_change_error_m3'])
                lo, hi = map(_q, parent['geometry_projection_intervals_m3'][i])
                lo, hi = lo-error, hi+error
                a, b = map(_q, row['end_volume_bounds_m3'])
                actual = self._vector(cells[key])[0]+chosen
                if actual < 0 or not a+lo <= actual <= b+hi:
                    raise ExteriorRefused('proposed volume violates endpoint geometry or propagated projection bounds')
                geometry_projection.append([_enc(lo), _enc(hi)])
            record = dict(schema='atlas.exterior-fv-offer.v1', owner_id=self.owner_id,
                parent_state_id=state.state_id, duration_s=dt, wall=wall,
                donor_debits=[dict(source_key=list(k), exact=self._exact(debits[k])) for k in self._keys],
                conditional_donor_field_error=[dict(source_key=list(k), exact=self._exact(inlet_error[k])) for k in self._keys],
                outer_normal_ids=expected,
                native_outward_volume_m3={s: list(map(_enc, map(Q, streams[s][1].flat))) for s in SIDES},
                boundary_stock_ids={s: stocks[s].result_id for s in SIDES},
                geometry_projection_intervals_m3=geometry_projection,
                method='current carried first-order FV donor fields; native transport method unchanged')
            encoded = _json(record)
            issued = object.__new__(ExteriorOffer)
            object.__setattr__(issued, '_metadata', encoded)
            object.__setattr__(issued, 'boundary_stocks', MappingProxyType(stocks))
            object.__setattr__(issued, '_budget', self._budget)
            _retain(issued, 8192+4*len(encoded)+sum(a.array(k).nbytes for a in stocks.values() for k in a.array_names), self._budget)
            return issued

    def validate_driving(self, offer, rigid_motion, duration_s):
        """Cheap known-input refusal before any native mechanical solve."""
        self._verify()
        if type(offer) is not ExteriorOffer or type(rigid_motion) is not RigidCollarMotion:
            raise ExteriorRefused('issued exterior offer and typed rigid motion required')
        record = offer.record()
        if record['owner_id'] != self.owner_id or duration_s != offer.duration_s:
            raise ExteriorRefused('requested drive/interval differs from the issued exterior offer')
        omega = record['wall']['trajectory']['segments'][-1]['angular_velocity_rad_s']
        if tuple(map(Q, rigid_motion.angular_velocity_rad_s)) != tuple(_q(q) for q in omega):
            raise ExteriorRefused('requested rigid velocity differs from measured physical motion')

    def advance_transport(self, parent, offer, collar_transport):
        """Pair actual advection before heat; no successor collar is invented."""
        old = self._bound(parent)
        if (type(offer) is not ExteriorOffer or offer._budget is not self._budget or
                type(collar_transport) is not RegionalCollarTransportStage):
            raise ExteriorRefused('issued offer and actual collar transport stage required')
        self._collar._check_transport_stage(collar_transport)
        if collar_transport.spatial_result is not None:
            raise ExteriorRefused('joint spatial transport needs its retained spatial owner, not coarse patch-cell pairing')
        record = offer.record(); wall = record['wall']; native = collar_transport
        with self._budget.reserve(131072+32*(_width(old)+_width(record)), category='exterior-fv-advance'):
            if record['owner_id'] != self.owner_id or record['parent_state_id'] != parent.state_id:
                raise ExteriorRefused('exterior offer has another parent')
            start = native.source_stage.inventory.descriptor()
            if (start['start_time_s'] != parent.time_s or start['duration_s'] != offer.duration_s or
                    native.parent.native_state.descriptor()['time_s']+native.duration_s != float(_q(wall['end_time_s']))):
                raise ExteriorRefused('actual collar and exterior interval differ')
            if old['intervals'] == 0:
                if start['parent_state_id'] != self._definition['native_initial_state_id']:
                    raise ExteriorRefused('actual first native parent differs from funded source')
            elif native.parent_state_id != old['collar_state_id']:
                raise ExteriorRefused('actual collar advance does not continue the paired exterior parent')
            report = native.transport.descriptor()
            if native.flow.descriptor().get('wall_measure_id') != wall['measure_id']:
                raise ExteriorRefused('native transport did not use this exact physical outer stream quadrature')
            if report['input_boundary_stock_ids'] != record['boundary_stock_ids']:
                raise ExteriorRefused('native transport did not consume this issued finite offer')
            n = len(self._keys); size = n+2+len(self._tracers)
            credits = {k: [Q(0)]*size for k in self._keys}
            credit_error = {k: [Q(0)]*size for k in self._keys}
            debits = {tuple(r['source_key']): self._vector(r) for r in record['donor_debits']}
            delta = [Q(0)]*size
            for side in SIDES:
                axis, end = 'xyz'.index(side[0]), 0 if side[1] == '0' else -1
                actual = np.take(native.flow.array('normal_'+side[0]+'_m_s'), end, axis=axis)
                if _hash(actual.tolist()) != record['outer_normal_ids'][side]:
                    raise ExteriorRefused('actual outer normals changed from the issued physical field')
                left, output = native.transport.boundary_stocks[side], native.transport.exports[side]
                if any(np.any(left.array(k) != 0) for k in self._fields):
                    raise ExteriorRefused('interval-only inlet parcel was not consumed exactly')
                expected_volume = np.asarray([float(_q(q)) for q in record['native_outward_volume_m3'][side]]).reshape(output.array('volume_m3').shape)
                if not np.array_equal(output.array('volume_m3'), expected_volume):
                    raise ExteriorRefused('actual export stream volume differs from issued wall sampling')
                for at in np.ndindex(expected_volume.shape):
                    parcel = [Q(float(output.array('volume_m3')[at]))]+[Q(0)]*n+[Q(float(output.array('enthalpy_j')[at]))]
                    for i, key in enumerate(self._native_keys):
                        parcel[1+self._keys.index(key)] = Q(float(output.array('component_mass_kg')[(i, *at)]))
                    parcel.extend(Q(float(output.array('tracer:'+k)[at])) for k in self._tracers)
                    receivers = [r for r in wall['rows'] if self._side(r['side']) == side and tuple(r['face_index']) == at and
                                 (_q(r['outward_volume_m3']) > 0 or _q(r['outward_max_deviation_m3']) > 0)]
                    total = sum((_q(r['outward_volume_m3']) for r in receivers), Q(0))
                    if parcel[0] and not total:
                        raise ExteriorRefused('actual export has no geometric receiver')
                    for row in receivers:
                        if not total:
                            continue  # independently exact zero whole-face stream
                        key = tuple(row['exterior_cell_key']); volume = _q(row['outward_volume_m3'])
                        credit = [volume]+[q*volume/total for q in parcel[1:]]
                        credits[key] = [a+b for a, b in zip(credits[key], credit)]
                        deviation = _q(row['outward_max_deviation_m3'])
                        error = [deviation]+[q*deviation/total for q in parcel[1:]]
                        credit_error[key] = [a+b for a, b in zip(credit_error[key], error)]
                    delta = [a+b for a, b in zip(delta, parcel)]
                    incoming = [Q(float(offer.boundary_stocks[side].array('volume_m3')[at]))]+[Q(0)]*n+[Q(float(offer.boundary_stocks[side].array('enthalpy_j')[at]))]
                    for i, key in enumerate(self._native_keys):
                        incoming[1+self._keys.index(key)] = Q(float(offer.boundary_stocks[side].array('component_mass_kg')[(i, *at)]))
                    incoming.extend(Q(float(offer.boundary_stocks[side].array('tracer:'+k)[at])) for k in self._tracers)
                    delta = [a-b for a, b in zip(delta, incoming)]
            cells = []
            for row in old['cells']:
                key = tuple(row['source_key']); before = self._vector(row)
                after = [a-b+c for a, b, c in zip(before, debits[key], credits[key])]
                if any(v < 0 for v in after):
                    raise ExteriorRefused('paired exterior update created a negative inventory')
                cells.append(dict(row, exact=self._exact(after)))
                delta = [a+b-c for a, b, c in zip(delta, debits[key], credits[key])]
            labels = ('volume_m3',)+tuple('component_mass_kg:'+str(i) for i in range(n))+('enthalpy_j',)+tuple('tracer:'+k for k in self._tracers)
            projection = {k: _enc(_q(old['projection_accounts'][k])+q) for k, q in zip(labels, delta)}
            endpoint = {tuple(r['exterior_cell_key']): r for r in wall['exterior_cells']}
            geometric = []
            for i, key in enumerate(self._keys):
                row = endpoint[key]
                chosen = _q(row['chosen_volume_change_m3'])
                if credits[key][0]-debits[key][0] != chosen:
                    raise ExteriorRefused('paired exterior volume differs from issued chosen GCL change')
                error = _q(row['chosen_volume_change_error_m3'])
                lo, hi = map(_q, old['geometry_projection_intervals_m3'][i])
                lo, hi = lo-error, hi+error
                a, b = map(_q, row['end_volume_bounds_m3'])
                actual = self._values(cells[i])['volume_m3']
                if not a+lo <= actual <= b+hi:
                    raise ExteriorRefused('carried volume lies outside endpoint geometry and propagated projection bounds')
                geometric.append([_enc(lo), _enc(hi)])
            metadata = dict(old); metadata.pop('state_id')
            metadata.update(time_s=float(_q(wall['end_time_s'])), intervals=old['intervals']+1,
                parent_state_id=parent.state_id, collar_state_id=None,
                support_id=wall['end_support_id'], trajectory=wall['trajectory'], cells=cells,
                trajectory_id=wall['trajectory_id'],
                cell_support_ids=[endpoint[k]['end_support_id'] for k in self._keys],
                geometry_accounts=wall['exterior_cells'], wall_measure_id=wall['measure_id'],
                geometry_projection_intervals_m3=geometric, projection_accounts=projection)
            exchange = dict(schema='atlas.exterior-fv-exchange.v1', owner_id=self.owner_id,
                parent_state_id=parent.state_id, offer_id=offer.offer_id, wall_measure_id=wall['measure_id'],
                collar_state_id=None, transport_id=native.transport.result_id,
                wall_measures=wall,
                donor_debits=record['donor_debits'],
                receiver_credits=[dict(source_key=list(k), exact=self._exact(credits[k])) for k in self._keys],
                conditional_donor_field_error=record['conditional_donor_field_error'],
                conditional_receiver_field_error=[dict(source_key=list(k), exact=self._exact(credit_error[k])) for k in self._keys],
                field_error_scope='wall-integration uncertainty conditional on current first-order FV fields, not cumulative physical solution error',
                projection_delta={k: _enc(q) for k, q in zip(labels, delta)},
                ownership='same native signed flux, actual located exterior receiver; no unlocated export bucket',
                discretisation='first-order well-mixed exterior donor/receiver fields; native transport method unchanged')
            snapshot = RegionalMechanicalSnapshot(metadata, self._arrays(metadata))
            result = object.__new__(ExteriorTransportStage)
            for key, value in dict(_snapshot=snapshot, _exchange=_json(exchange),
                                   _native_stage=native, _budget=self._budget).items():
                object.__setattr__(result, key, value)
            _retain(result, 8192+2*snapshot.nbytes+4*len(result._exchange), self._budget)
            return result

    def finish(self, transported, collar_advance):
        """Bind the completed collar; this coarse route adds no exterior heat."""
        self._verify()
        if (type(transported) is not ExteriorTransportStage or transported._budget is not self._budget or
                type(collar_advance) is not RegionalCollarAdvance or
                collar_advance._transport_stage is not transported._native_stage):
            raise ExteriorRefused('actual paired transport and its completed collar endpoint required')
        metadata = transported._snapshot.descriptor()
        exchange = json.loads(transported._exchange)
        with self._budget.reserve(65536+32*(_width(metadata)+_width(exchange)), category='exterior-fv-finish'):
            self._collar._fields(collar_advance.state)
            completed = collar_advance.state.fields.descriptor()
            if (metadata['owner_id'] != self.owner_id or metadata['collar_state_id'] is not None or
                    collar_advance.state.native_state.descriptor()['time_s'] != metadata['time_s'] or
                    collar_advance.transport.result_id != exchange['transport_id'] or
                    completed['parent_id'] != transported._native_stage.parent_state_id or
                    completed['transport_id'] != exchange['transport_id'] or
                    completed['heat_id'] != collar_advance.heat.result_id):
                raise ExteriorRefused('paired transport owner, interval or actual result differs')
            metadata['collar_state_id'] = exchange['collar_state_id'] = collar_advance.state.result_id
            state = self._issue(metadata); self._bound(state)
            result = ExteriorAdvance(state, _json(exchange))
            _retain(result, 8192+4*len(result._metadata), self._budget)
            return result

    def advance(self, parent, offer, collar_advance):
        """Compatibility path: pair transport then bind the completed endpoint."""
        if type(collar_advance) is not RegionalCollarAdvance:
            raise ExteriorRefused('actual collar advance required')
        transported = self.advance_transport(parent, offer, collar_advance._transport_stage)
        return self.finish(transported, collar_advance)

    def restore(self, record, arrays):
        self._verify()
        with self._budget.reserve(65536+32*_width(record), category='exterior-fv-restore'):
            if type(record) is not dict or record.get('schema') != 'atlas.exterior-fv-state.v1':
                raise ExteriorRefused('typed exact exterior checkpoint required')
            data = dict(record); expected = data.pop('state_id', None)
            try:
                state = self._issue(data)
                self._bound(state)
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ExteriorRefused('malformed exact exterior checkpoint') from exc
            actual = state.arrays()
            if (state.state_id != expected or type(arrays) is not dict or set(arrays) != set(actual) or
                    any(np.asarray(arrays[k]).dtype != np.dtype('float64') or
                        not np.array_equal(arrays[k], a) for k, a in actual.items())):
                raise ExteriorRefused('exterior exact records or reporting projections changed')
            return state

    def validate_exchange(self, state, exchange_record):
        """Verify saved issued evidence without replaying accepted quadrature."""
        from .integration_wall_measures import WallMeasures
        current = self._bound(state)
        with self._budget.reserve(65536+16*_width(exchange_record), category='exterior-fv-exchange-inspection'):
            if type(exchange_record) is not dict:
                raise ExteriorRefused('saved paired exterior exchange required')
            record = dict(exchange_record)
            result_id, state_id = record.pop('result_id', None), record.pop('state_id', None)
            if (state_id != state.state_id or record.get('owner_id') != self.owner_id or
                    record.get('parent_state_id') != current['parent_state_id'] or
                    record.get('collar_state_id') != current['collar_state_id'] or
                    result_id != _hash(dict(state_id=state_id, exchange=record))):
                raise ExteriorRefused('saved exterior exchange identity or parent changed')
            wall = WallMeasures.restore(record['wall_measures'], budget=self._budget).descriptor()
            if (wall['measure_id'] != record['wall_measure_id'] or wall['measure_id'] != current['wall_measure_id'] or
                    wall['end_support_id'] != current['support_id'] or
                    wall['trajectory_id'] != current['trajectory_id'] or
                    wall['trajectory'] != current['trajectory'] or
                    wall['exterior_cells'] != current['geometry_accounts'] or
                    _q(wall['end_time_s']) != Q(state.time_s)):
                raise ExteriorRefused('saved exterior geometry, trajectory or clock evidence changed')

    def close(self):
        if not self._closed:
            self._closed = True
            self._initial_state = None
            if self._guard is not None:
                self._guard.__exit__(None, None, None); self._guard = None

    def __enter__(self):
        self._verify(); return self

    def __exit__(self, *_):
        self.close()
