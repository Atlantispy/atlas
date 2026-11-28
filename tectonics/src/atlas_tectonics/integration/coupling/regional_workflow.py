"""Atomic retained-region workflow with a frozen, explicitly dormant source.

This is a regional branch, not a global plate clock or a return to rigid columns.
Native ArrayStore transactions own publication, compression and deduplication.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
from contextlib import contextmanager, ExitStack
from fractions import Fraction
import hashlib
import json
from atlas_tectonics._private.codecs import compact_restart_patch as _RESTART
from atlas_tectonics._private.integration.geometry import spatial_records_patch as _COMPACT_RECORDS
from atlas_tectonics._private.integration.geometry import spatial_workflow_patch as _COMPACT_SPATIAL
from atlas_tectonics._private.integration.geometry import partition_workflow_patch as _COMPACT_PARTITION
from atlas_tectonics._private.integration.geometry import publish_mesh_patch as _PUBLISH_MESH
from types import SimpleNamespace

from atlas_tectonics.integration import bridges as B
from atlas_tectonics.integration import material as M
from atlas_tectonics.integration.geometry import sphere as S
from atlas_tectonics.integration.coupling.regional_evolution import PreparedRegionalOwner, CellAllocation, RegionalVolumeMap, RegionalOwnerRefused
from atlas_tectonics.codecs.storage import ArrayStore, StoreConflict
from atlas_tectonics._validation import without_effort as _without
from typing import TYPE_CHECKING, Any, cast
if TYPE_CHECKING:
    from atlas_tectonics.integration.coupling.exterior_state import ExteriorFVState, PreparedExteriorOwner
    from atlas_tectonics.integration.geometry.differential_geometry import DifferentialPartition


SCHEMA = 'atlas.regional-owner-workflow.v1'
MAX_INTERVALS = 256                 # retained owner/native bounded-run envelope


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _key(kind, identity):
    return _hash(dict(schema=SCHEMA, kind=kind, identity=identity))


def retained_inventory_accounts(collar_state, exterior_state, *, budget):
    """Exact current retained inventories with numerical accounts kept separate.

    This counts the active paired domain, not dormant/unselected source rock or
    the whole planet. It reads issued fields; no source is resampled or solved.
    Finite admission projections remain constant lineage accounts, counted once
    even after the physical stock has been exhausted or exported.
    """
    from atlas_tectonics.integration.coupling.regional_inventory import _q, _encoded
    with budget.reserve(65536+4*exterior_state._snapshot.nbytes+3*collar_state.fields.nbytes,
                        category='retained-inventory-accounts'):
        record = _COMPACT_SPATIAL.logical_record(exterior_state)
        fields = collar_state.fields
        native = {'component_mass_kg:'+str(i): sum((Fraction(float(v)) for v in a.flat), Fraction(0))
                  for i, a in enumerate(fields.array('component_mass_kg'))}
        native.update({name: sum((Fraction(float(v)) for v in fields.array(name).flat), Fraction(0))
                       for name in fields.array_names if name != 'component_mass_kg'})
        sections = {kind: dict.fromkeys(native, Fraction(0)) for kind in
                    ('exterior', 'finite', 'spatial_projection', 'finite_projection', 'admission_projection')}
        sections['native'] = native

        def add(kind, values):
            for name, value in values.items():
                sections[kind][name] += _q(value)

        for cell in record['cells']:
            add('exterior', cell['exact'])
        add('spatial_projection', record['projection_accounts'])
        finite = record.get('finite_stock_state')
        if finite is not None:
            for row in finite['stocks']:
                add('finite', row['exact'])
                add('finite_projection', finite['projection_accounts'][row['stock_id']])
                if 'admission_projection' in row['lineage']:
                    admission = row['lineage']['admission_projection']
                    if 'material_quadrature_m3' in native:
                        # B is declared exactly from the original booked stock
                        # at fresh admission, so it has no extra physical-source
                        # debit or projection. Do not change the older lineage.
                        admission = dict(admission)
                        admission.setdefault('material_quadrature_m3', ['0', '1'])
                    add('admission_projection', admission)
        accounted = {name: sum((section[name] for section in sections.values()), Fraction(0)) for name in native}
        result = dict(schema='atlas.retained-inventory-accounts.v1', collar_state_id=collar_state.result_id,
            exterior_state_id=exterior_state.state_id, finite_state_id=None if finite is None else finite['state_id'],
            time_s=record['time_s'], scope='active retained domain and separate numerical accounts, not whole-planet stock',
            sections={kind: {name: _encoded(v) for name, v in values.items()} for kind, values in sections.items()},
            accounted={name: _encoded(v) for name, v in accounted.items()})
        if 'material_quadrature_m3' in native:
            result['material_quadrature_convention'] = 'conserved bookkeeping measure B, not geometric volume G or new mass'
        return dict(account_id=_hash(result), **result)


class RegionalWorkflow:
    """One current owner state, with immutable single-successor publication.

    The source sphere and moving state are stored once. They remain frozen at
    extraction time, not counted as active regional inventory and not advanced
    by this route. The native region is the only evolving state in this branch.
    Continuing global motion or handing a sheared field back to rigid columns
    requires another supported coupling, not an implicit projection here.

    A caller supplies its rebuilt native plan on open; its complete identity,
    including runtime, method and physical declarations, must reproduce. Store
    and native-plan lifetimes belong to the caller. This class owns only an
    owner it rebuilds on open. No accepted physics is rerun to inspect a history.
    """

    def __init__(self, *args, **kwargs):
        raise TypeError('RegionalWorkflow is issued by create() or open()')

    @classmethod
    def _issued(cls, store, owner, sphere, moving, root, budget, owns_owner):
        self = object.__new__(cls)
        self._store, self._owner, self._budget = store, owner, budget
        self._sphere, self._moving, self._root = sphere, moving, _json(root)
        self._owns_owner, self._closed = owns_owner, False
        self._head, self._state, self._token = root, owner.initial_state, None
        self._heat_sources = None
        return self

    @classmethod
    def create(cls, store, owner, *, sphere, moving, budget):
        owner.require_dormant_source(sphere, moving)
        definition = owner.descriptor()
        identity = _key('history', owner.owner_id)
        root = dict(schema=SCHEMA, workflow_id=identity, key=_key('root', identity),
            kind='root', sequence=0, owner=definition, source_sphere=sphere.descriptor(),
            source_moving=moving.descriptor(), regional=owner.initial_state.descriptor(),
            mechanical_heat_receipts=True,
            ownership='source frozen; selected columns dormant; only regional state evolves')
        arrays = dict(sphere.arrays())
        arrays.update(moving.arrays())
        arrays.update(owner.initial_state.arrays())
        store.put(root['key'], arrays, root, budget=budget)
        self = cls._issued(store, owner, sphere, moving, root, budget, False)
        self._refresh()
        return self

    @classmethod
    def open(cls, store, workflow_id, native_plan, *, budget):
        key = _key('root', workflow_id)
        root, arrays = store.metadata(key), store.get(key, budget=budget)
        owner = None
        try:
            sphere = S.restore_sphere(root['source_sphere'], arrays, budget=budget)
            moving = M.restore_moving(root['source_moving'], arrays, sphere, budget=budget)
            definition = root['owner']
            physical = definition.get('volume_map')
            volume_map = (None if physical is None else
                          RegionalVolumeMap.restore(physical, sphere, moving, budget=budget))
            allocations = (tuple(CellAllocation(row[0], row[1], Fraction(int(row[2][0]), int(row[2][1])))
                                 for row in definition['transfer']['allocations']) if volume_map is None else None)
            reservoirs = None
            if definition.get('boundary_inventory') is not None:
                from atlas_tectonics.integration.coupling.regional_inventory import HaloReservoir
                reservoirs = tuple(HaloReservoir.from_record(row, budget=budget)
                                   for row in definition['boundary_inventory']['reservoirs'])
            inventory_args = ({} if reservoirs is None else
                              {'boundary_reservoirs': reservoirs})
            if 'component_registry' in definition:
                from atlas_tectonics.integration.coupling.regional_inventory import ComponentRegistry
                inventory_args['component_registry'] = ComponentRegistry.from_record(
                    definition['component_registry'], budget=budget)
            if 'basal_side' in definition:
                inventory_args['basal_side'] = definition['basal_side']
            if definition.get('material_quadrature'):
                inventory_args['material_quadrature'] = True
            owner = PreparedRegionalOwner(native_plan, sphere, moving,
                B.Footprint(**definition['extract']['footprint']), allocations,
                plate_ids=tuple(definition['layout']['plate_ids']), creep_match=definition['creep_match'],
                map_source=definition['transfer']['source'], budget=budget, volume_map=volume_map,
                **inventory_args)
            held = {k: v for k, v in arrays.items() if k.startswith('regional.')}
            owner.restore(root['regional'], held, sphere=sphere, moving=moving)
            self = cls._issued(store, owner, sphere, moving, root, budget, True)
            self._refresh()
            return self
        except BaseException:
            if owner is not None:
                owner.close()
            raise

    def _verify(self):
        self._owner.require_dormant_source(self._sphere, self._moving)

    def _refresh(self):
        self._verify()
        token = self._store.change_token()
        if token == self._token:
            return
        root = json.loads(self._root)
        if self._store.metadata(root['key']) != root:
            raise RegionalOwnerRefused('regional workflow root changed')
        previous = root
        for sequence in range(1, MAX_INTERVALS+2):
            key = _key('successor', previous['key'])
            current = self._store.metadata(key)
            if current is None:
                break
            if sequence > MAX_INTERVALS:
                raise RegionalOwnerRefused('regional workflow exceeds its interval envelope')
            state, _ = current['regional'], previous['regional']
            previous = current
        # Only the current arrays are needed. Older records are linked by digest;
        # their payloads remain content-addressed in the existing store.
        arrays = cast(dict, _COMPACT_SPATIAL.workflow_arrays(self._store, previous['key'], budget=self._budget))
        if previous['kind'] == 'root':
            arrays = {k: v for k, v in arrays.items() if k.startswith('regional.')}
        state = self._owner.restore(previous['regional'], arrays, sphere=self._sphere, moving=self._moving)
        heat_sources = None
        if previous['kind'] == 'successor' and 'mechanical_heat' in previous:
            from atlas_tectonics.integration.heat.mechanical_heat import restore_heat_sources
            heat_sources = restore_heat_sources(previous['mechanical_heat'], owner=self._owner,
                state=state, expected_receipt_id=previous['mechanical_heat_id'], budget=self._budget)
        if token != self._store.change_token():
            raise StoreConflict('regional workflow changed during inspection; reopen at its accepted head')
        self._head, self._state, self._token = previous, state, token
        self._heat_sources = heat_sources

    @property
    def workflow_id(self):
        return json.loads(self._root)['workflow_id']

    @property
    def state(self):
        self._refresh()
        return self._state

    @property
    def mechanical_heat(self):
        """Actual donor-owned source receipt of the accepted interval, or None at admission.

        Reading and reopening only check the carried exchange. They never rerun
        mechanics or deposit the interval's heat a second time.
        """
        self._refresh()
        return self._heat_sources

    def inspect(self):
        self._refresh()
        return dict(workflow_id=self.workflow_id, head=self._head['key'],
            intervals=self._head['sequence'], time_s=self._state.native_state.descriptor()['time_s'],
            source_time_s=self._moving.time_s, source_frozen=True,
            mechanical_heat_id=None if self._heat_sources is None else self._heat_sources.receipt_id,
            reservation=self._owner.reservation(), regional=self._state.descriptor())

    def advance(self, duration_s, **driving):
        self._refresh()
        parent, state = self._head, self._state
        from atlas_tectonics.integration.feedback import regional_interval
        feedback = regional_interval(self._owner, state, duration_s, sphere=self._sphere,
                                     moving=self._moving, budget=self._budget, **driving)
        advanced, heat_sources = feedback.advance, feedback.heat_sources
        self._owner._bound(advanced.state)
        key = _key('successor', parent['key'])
        row = dict(schema=SCHEMA, workflow_id=self.workflow_id, key=key, kind='successor',
            sequence=parent['sequence']+1, parent_key=parent['key'], parent_digest=_hash(parent),
            regional=advanced.state.descriptor(), mechanical_heat=heat_sources.descriptor(),
            mechanical_heat_id=heat_sources.receipt_id)

        def check():
            store = self._store
            if store.metadata(parent['key']) != parent or store.metadata(json.loads(self._root)['key']) != json.loads(self._root):
                raise StoreConflict('regional workflow parent/source changed before publication')

        # Immutable key is the head compare-and-swap. Failure or cancellation
        # leaves the old accepted state; no source inventory is booked again.
        cancel = driving.get('cancel')
        if cancel is not None and not hasattr(cancel, 'is_set'):
            cancel = SimpleNamespace(is_set=cancel)
        self._store.put(key, advanced.state.arrays(), row, publication_check=check,
                        cancel=cancel, budget=self._budget)
        self._head, self._state, self._token = row, advanced.state, None
        self._heat_sources = heat_sources
        return advanced

    def close(self):
        if not self._closed and self._owns_owner:
            self._owner.close()
        self._closed = True

    def __enter__(self):
        self._verify()
        return self

    def __exit__(self, *_):
        self.close()


@dataclass(frozen=True)
class CoupledCollarAdvance:
    """Both actual sides of an atomically published material exchange."""
    collar: object
    exterior: object

    @property
    def state(self):
        return self.collar.state


class CollarWorkflow:
    """Single-store publication of a physically funded full-cell collar.

    This bounded route carries the entire resolved/collar state at one time.
    With an issued exterior owner, one transaction publishes both sides of the
    actual space-time exchange. Without one the outer material boundary remains
    closed. Neither route resamples an archived temperature or invents refill.
    A moving selected exterior is not a whole-planet force/topology acceptance.
    """
    _schema = 'atlas.funded-collar-workflow.v2'

    def __init__(self, *args, **kwargs):
        raise TypeError('CollarWorkflow is issued by create() or open()')

    @classmethod
    def _key(cls, kind, identity):
        return _hash(dict(schema=cls._schema, kind=kind, identity=identity))

    @classmethod
    def _issued(cls, store, collar, owner, funding, root, budget, exterior_owner=None):
        self = object.__new__(cls)
        self._store, self._collar, self._owner = store, collar, owner
        self._funding, self._root, self._budget = funding, _json(root), budget
        self._head, self._state, self._token, self._closed = None, None, None, False
        self._exterior_owner, self._exterior_state = exterior_owner, None
        self._owns_exterior_owner = False
        self._source_audit = None
        self._differential_interval = None
        self._differential_partition = None
        self._initial_current_geometry = None
        self._physical_geometry_family = root.get('geometry_family')
        return self

    @classmethod
    def _exterior_inputs(cls, exterior_owner, collar, funding, budget):
        if exterior_owner is None:
            return None
        record = exterior_owner.descriptor()
        return record

    @classmethod
    def _identity(cls, collar, funding, exterior_definition):
        parts = dict(collar=collar.plan_id, funding=funding.funding_id)
        if exterior_definition is not None:
            parts['exterior_owner'] = exterior_definition['owner_id']
        return cls._key('history', parts)

    @staticmethod
    def _payload(state, exterior, source_audit=None, spatial_audit=None):
        arrays = dict(state.arrays())
        if exterior is not None:
            arrays.update({'exterior-fv:'+k: v for k, v in exterior.arrays().items()})
        if source_audit is not None:
            arrays.update({'source-audit:'+k: source_audit.array(k) for k in source_audit.array_names})
        if spatial_audit is not None:
            arrays.update({'spatial-audit:'+k: v for k, v in spatial_audit.items()})
        return arrays

    def _is_spatial(self):
        from atlas_tectonics.integration.coupling.spatial_owner import PreparedSpatialOwner
        return type(self._exterior_owner) is PreparedSpatialOwner

    @staticmethod
    def _geometry_family(exterior_owner):
        from atlas_tectonics.integration.coupling.spatial_owner import PreparedSpatialOwner
        if type(exterior_owner) is PreparedSpatialOwner:
            return _COMPACT_SPATIAL.X.mesh_header(_COMPACT_SPATIAL.logical_record(exterior_owner.initial_state)['thermal_mesh'], exterior_owner._budget).value.get('physical_geometry_family')
        return None

    def _is_differential(self):
        return self._physical_geometry_family == 'differential-plate-component-partition-v1'

    @staticmethod
    def _certification_required(differential, solution):
        from atlas_tectonics.integration.geometry.differential_coupling import DifferentialIntervalSolution
        if differential:
            if type(solution) is not DifferentialIntervalSolution:
                raise RegionalOwnerRefused('differential publication requires the actual issued final trace/work and GCL solution')
        elif solution is not None:
            raise RegionalOwnerRefused('ordinary rigid-wall route cannot adopt differential certification')

    @staticmethod
    def _certification_header(records, ref):
        s, i = records['solution'], records['iteration']
        keys = ('solution_id', 'parent_state_id', 'spatial_state_id', 'finite_state_id',
                'source_flow_stage_id', 'source_audit_id', 'force_exchange_id', 'native_measure_id',
                'interval_id', 'partition_id', 'trace_audit_id', 'bounds_id', 'graph_id')
        return dict({k: s[k] for k in keys}, **records['bindings'],
                    parent_partition_id=i['parent_partition_id'], current_geometry_id=i['current_geometry_id'],
                    record_blob=ref)

    def _saved_certification_expected(self, parent, successor):
        """Compact chain checks also cover accepted intervals before the head."""
        current_id = (parent['differential_partition']['current_geometry_id'] if parent['kind'] == 'root' else
                      parent['differential_certification']['endpoint_current_geometry_id'])
        return dict(owner_id=self._exterior_owner.owner_id, funding_id=self._funding.funding_id,
            collar_plan_id=self._collar.plan_id, parent_state_id=parent['state']['result_id'],
            spatial_state_id=parent['exterior_state']['state_id'],
            parent_partition_id=parent['differential_partition']['partition_id'], current_geometry_id=current_id,
            interval_id=successor['differential_geometry']['interval_id'],
            partition_id=successor['differential_partition']['partition_id'],
            source_flow_stage_id=successor['exterior_advance']['source_flow_stage_id'],
            source_audit_id=successor['advance']['source_audit_id'],
            graph_id=successor['exterior_advance']['spatial_graph_id'])

    @staticmethod
    def _check_certification_records(records, force, graph, interval, expected, source_audit):
        """Validate retained accepted evidence, never issue new physics from JSON."""
        with _SV.access(graph) as graph:
            from . import regional_driving as D
            from atlas_tectonics.integration.geometry.wall_measures import _decode
            try:
                if set(records) != {'solution', 'proposal', 'iteration', 'force', 'bindings'}:
                    raise RegionalOwnerRefused('saved differential certification record set differs')
                s, p, i = (records[k] for k in ('solution', 'proposal', 'iteration'))
                from atlas_tectonics.integration.geometry.differential_coupling import PROPOSAL_EFFORT
                for record, key, schema in ((s, 'solution_id', 'atlas.differential-interval-solution.v1'),
                        (p, 'proposal_id', 'atlas.differential-force-proposal.v1'),
                        (i, 'iteration_id', 'atlas.differential-iteration.v1')):
                    if record['schema'] != schema or _hash(_without({k: v for k, v in record.items() if k != key},
                            PROPOSAL_EFFORT if key == 'proposal_id' else ())) != record[key]:
                        raise RegionalOwnerRefused('saved differential certification identity changed')
                audit, f = s['trace_audit'], force.descriptor()
                if (_hash(audit) != s['trace_audit_id'] or audit['schema'] != 'atlas.differential-final-trace-audit.v1' or
                        p['proposal_id'] != s['proposal_id'] or p['iteration_id'] != s['iteration_id'] or
                        i['iteration_id'] != s['iteration_id'] or s['published'] is not False or
                        p['published'] is not False or p['accepted_heat_state_advanced'] is not False or
                        _SV.content_identity(graph, _hash) != s['graph_id'] or graph['bounds_id'] != s['bounds_id'] or
                        force.result_id != s['force_exchange_id'] or records['force'] != f):
                    raise RegionalOwnerRefused('saved differential certification links changed')
                for key in ('parent_state_id', 'spatial_state_id', 'source_flow_stage_id', 'source_audit_id',
                            'force_exchange_id', 'native_measure_id', 'interval_id', 'partition_id'):
                    if p[key] != s[key]:
                        raise RegionalOwnerRefused('saved differential proposal differs from final certification')
                for key in ('parent_state_id', 'spatial_state_id', 'finite_state_id'):
                    if i[key] != s[key]:
                        raise RegionalOwnerRefused('saved differential iteration has another accepted parent')
                header = CollarWorkflow._certification_header(records, None)
                if any(header.get(k) != value for k, value in expected.items()):
                    raise RegionalOwnerRefused('differential certification has another owner, parent or accepted geometry')
                for key in ('parent_state_id', 'source_flow_stage_id', 'native_measure_id', 'interval_id', 'partition_id'):
                    if graph[key] != s[key] or audit[key] != s[key]:
                        raise RegionalOwnerRefused('final trace and material graph do not certify the same actual source')
                if (graph['finite_state_id'] != s['finite_state_id'] or
                        audit['force_exchange_id'] != force.result_id or
                        audit['native_result_id'] != source_audit['initial_mechanics_id'] or
                        f['native_result_id'] != audit['native_result_id'] or
                        f['parent_state_id'] != i['native_state_id'] or
                        i['native_state_id'] != source_audit['parent_state_id'] or
                        f['schema'] != D.SCHEMA+'.result' or
                        f['time_s'] != source_audit['start_time_s'] or
                        Fraction(f['time_s']) != _decode(interval['start_time_s']) or
                        audit['start_time_s'] != interval['start_time_s'] or audit['end_time_s'] != interval['end_time_s'] or
                        audit['velocity_replaced'] is not False or audit['source_heat_reapplied'] is not False or
                        f['algebra_relative_residual'] != audit['force_algebra_relative_residual'] or
                        f['virtual_work_relative_residual'] != audit['force_virtual_work_relative_residual'] or
                        f['algebra_relative_residual'] > D.ALGEBRA or f['virtual_work_relative_residual'] > D.WORK):
                    raise RegionalOwnerRefused('saved final trace/work audit differs from actual force/source arrays')
                account = audit['trace_account']
                low, high = map(_decode, account['l2_error_squared_bounds'])
                work = _decode(account['work_error_squared_upper'])
                limit, work_limit = map(_decode, (audit['max_l2_error_squared'], audit['max_work_error']))
                if min(low, high, work, limit, work_limit) < 0 or low > high or high > limit or work > work_limit**2:
                    raise RegionalOwnerRefused('saved trace/work certificate exceeds its declared acceptance bounds')
                plates, omega = f['driving']['plate_ids'], force.array('omega_rad_s')
                actual = interval['plate_angular_velocity_rad_s']
                if (omega.shape != (len(plates), 3) or set(plates) != set(actual) or
                        audit['angular_velocity_rad_s'] != actual or
                        any(tuple(Fraction(float(q)) for q in row) != tuple(map(_decode, actual[plate]))
                            for plate, row in zip(plates, omega))):
                    raise RegionalOwnerRefused('saved interval is not the actual solved force-rate field')
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                if isinstance(exc, RegionalOwnerRefused):
                    raise
                raise RegionalOwnerRefused('malformed differential certification provenance') from exc

    def _validate_differential_solution(self, solution, source, interval, partition, bounds):
        self._certification_required(True, solution)
        p = solution.proposal
        iteration = p._owner
        if (iteration._collar is not self._collar or iteration._funding is not self._funding or
                iteration._spatial_owner is not self._exterior_owner or
                iteration._state.result_id != self._state.result_id or
                iteration._spatial_state.state_id != self._exterior_state.state_id or
                iteration._parent_partition.partition_id != cast('DifferentialPartition', self._differential_partition).partition_id or
                iteration._current.geometry_id != self.current_geometry.geometry_id):
            raise RegionalOwnerRefused('certification belongs to another actual workflow owner or current parent')
        solution.validate_source(source, interval, partition, bounds, spatial_state_id=self._exterior_state.state_id)
        expected = dict(owner_id=self._exterior_owner.owner_id, funding_id=self._funding.funding_id,
            collar_plan_id=self._collar.plan_id, parent_state_id=self._state.result_id,
            spatial_state_id=self._exterior_state.state_id, parent_partition_id=cast('DifferentialPartition', self._differential_partition).partition_id,
            current_geometry_id=iteration._current.geometry_id,
            interval_id=interval.interval_id, partition_id=partition.partition_id,
            source_flow_stage_id=source.result_id, source_audit_id=source.source_stage.source_audit.result_id)
        from atlas_tectonics.integration.coupling.regional_inventory import _width
        width = (_COMPACT_RECORDS.holder_bytes(solution)+_COMPACT_RECORDS.holder_bytes(p)+_COMPACT_RECORDS.holder_bytes(solution.graph))+p.force_exchange.nbytes+_width(iteration._definition)
        with self._budget.reserve(65536+10*width, category='differential-certification-validation'):
            records = self._certification_records(solution)
            self._check_certification_records(records, p.force_exchange, solution.graph.record(), interval.record(),
                                               expected, source.source_stage.source_audit.descriptor())
        return solution.graph

    @staticmethod
    def _certification_records(solution):
        from atlas_tectonics.integration.geometry.differential_geometry import current_geometry_from_interval
        p, owner = solution.proposal, solution.proposal._owner
        return dict(solution=solution.record(), proposal=p.record(), iteration=owner.descriptor(),
            force=p.force_exchange.descriptor(), bindings=dict(owner_id=owner._spatial_owner.owner_id,
                funding_id=owner._funding.funding_id, collar_plan_id=owner._collar.plan_id,
                endpoint_current_geometry_id=current_geometry_from_interval(p.interval, budget=solution._resource).geometry_id))

    @classmethod
    @contextmanager
    def _certification_payload(cls, solution, budget, *, store=None, source_producer=None, cancel=None):
        if getattr(store, 'scope', None) is not None:
            with _COMPACT_RECORDS.certification_payload(cls, solution, budget, store=store,
                    source_producer=source_producer, cancel=cancel) as result:
                yield result
            return
        import numpy as np
        from atlas_tectonics.integration.coupling.regional_inventory import _width
        cls._certification_required(True, solution)
        force = solution.proposal.force_exchange
        width = len(solution._json)+len(solution.proposal._json)+_width(solution.proposal._owner._definition)+force.nbytes
        with budget.reserve(65536+10*width, category='differential-certification-encode'):
            records = cls._certification_records(solution)
            raw = _json(records)
            name = 'certification-record:final'
            ref = dict(array=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            arrays = {'certification-force:'+k: force.array(k) for k in force.array_names}
            arrays[name] = np.frombuffer(raw, dtype=np.uint8)
            yield cls._certification_header(records, ref), arrays

    @classmethod
    def _restore_certification(cls, header, arrays, budget, *, graph, interval, expected, source_audit, store=None, source_producer=None):
        if 'compact' in header.get('record_blob', {}):
            return _COMPACT_RECORDS.restore_certification(cls, header, arrays, budget, store=store,
                graph=graph, interval=interval, expected=expected, source_audit=source_audit, source_producer=source_producer)
        from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
        values = arrays.get('certification-record:final')
        with ExitStack() as scratch:
            scratch.enter_context(budget.reserve(65536+4*values.nbytes, category='differential-certification-read'))
            raw = values.tobytes()
            slots = 1+sum(raw.count(token) for token in (b'{', b'[', b':', b','))
            scratch.enter_context(budget.reserve(65536+6*len(raw)+128*slots, category='differential-certification-decode'))
            try:
                records = json.loads(raw)
            except (UnicodeDecodeError, ValueError) as exc:
                raise RegionalOwnerRefused('saved differential certification is not canonical data') from exc
            fields = {k.removeprefix('certification-force:'): v for k, v in arrays.items() if k.startswith('certification-force:')}
            scratch.enter_context(budget.reserve(65536+3*sum(a.nbytes for a in fields.values())+2*len(raw),
                                                 category='differential-certification-force'))
            force = RegionalMechanicalSnapshot(records['force'], fields)
            cls._check_certification_records(records, force, graph, interval, expected, source_audit)

    @staticmethod
    def _partition_header(record, refs):
        keys = ('partition_id', 'scope', 'funding_id', 'collar_plan_id', 'grid_id',
                'start_time_s', 'end_time_s', 'current_geometry_id', 'interval_id', 'parent_partition_id')
        return dict({k: record[k] for k in keys if k in record}, record_blobs=refs)

    @classmethod
    @contextmanager
    def _partition_payload(cls, partition, geometry, funding, collar, budget, *, store=None,
                           source_producer=None, cancel=None):
        """One immutable partition/support bundle; no per-cell certificate copies."""
        if store is not None:
            with _COMPACT_PARTITION.payload(cls, partition, geometry, funding, collar, budget, store=store,
                    source_producer=source_producer, cancel=cancel) as result:
                yield result
            return
        import numpy as np
        row = partition.record()
        initial = row['scope'] == 'initial-current'
        width = len(partition._json)+sum(len(s._json) for s in partition.supports)
        if initial:
            width += len(geometry._json)
        with budget.reserve(65536+8*width, category='differential-partition-encode'):
            records = dict(partition=partition.descriptor())
            if initial:
                records['current'] = geometry.descriptor()
            arrays, refs = {}, {}
            for kind, record in records.items():
                name, raw = 'partition-record:'+kind, _json(record)
                arrays[name] = np.frombuffer(raw, dtype=np.uint8)
                refs[kind] = dict(array=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            yield cls._partition_header(records['partition'], refs), arrays

    @classmethod
    def _restore_partition(cls, header, arrays, funding, collar, budget, *, interval=None, store=None, opened=None):
        if type(header) is dict and 'compact_partition' in header:
            return _COMPACT_PARTITION.restore(cls, header, arrays, funding, collar, budget,
                                              interval=interval, store=store, opened=opened)
        from atlas_tectonics.integration.geometry.differential_geometry import DifferentialPartition, CurrentGeometry
        refs = header.get('record_blobs', {})
        kinds = {'partition', 'current'} if interval is None else {'partition'}
        with ExitStack() as scratch:
            records = {}
            for kind in sorted(kinds):
                _, values = refs[kind], arrays['partition-record:'+kind]
                # Raw and canonical-comparison buffers die before the typed
                # issuer runs. The decoded object graph remains charged until
                # its last use; it is not released just to admit nested work.
                with budget.reserve(65536+4*values.nbytes, category='differential-partition-read'):
                    raw = values.tobytes()
                    slots = 1+sum(raw.count(token) for token in (b'{', b'[', b':', b','))
                    scratch.enter_context(budget.reserve(65536+4*len(raw)+128*slots,
                                                         category='differential-partition-decode'))
                    try:
                        record = json.loads(raw)
                    except (UnicodeDecodeError, ValueError) as exc:
                        raise RegionalOwnerRefused('saved differential partition is not valid JSON') from exc
                    del raw
                records[kind] = record
            geometry = interval if interval is not None else CurrentGeometry.restore(records['current'], budget=budget)
            partition = DifferentialPartition.restore(records['partition'], funding, collar, geometry, budget=budget)
            return partition, geometry

    @staticmethod
    @contextmanager
    def _differential_payload(interval, budget, *, store=None, source_producer=None, cancel=None):
        if getattr(store, 'scope', None) is not None:
            with _COMPACT_RECORDS.differential_payload(interval, budget, store=store,
                    source_producer=source_producer, cancel=cancel) as result:
                yield result
            return
        import numpy as np
        network = interval.endpoint_network
        with budget.reserve(65536+8*len(interval._json)+8*network.nbytes,
                            category='differential-workflow-encode'):
            record = dict(interval=interval.descriptor(), endpoint_network=network.descriptor())
            raw = _json(record)
            ref = dict(array='differential-record:geometry', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            body = record['interval']
            header = {k: body[k] for k in ('interval_id', 'parent_network_id', 'endpoint_network_id',
                                          'start_time_s', 'end_time_s', 'trajectory_id', 'prior_trajectory_id')}
            header['record_blob'] = ref
            arrays = {'differential-network:'+k: v for k, v in network.arrays().items()}
            arrays[ref['array']] = np.frombuffer(raw, dtype=np.uint8)
            yield header, arrays

    @staticmethod
    def _restore_differential(header, arrays, budget, *, store=None, source_producer=None):
        if 'compact' in header.get('record_blob', {}):
            return _COMPACT_RECORDS.restore_differential(header, arrays, budget, store=store, source_producer=source_producer)
        from atlas_tectonics.integration.geometry.differential_geometry import DifferentialInterval
        raw_array = arrays.get('differential-record:geometry')
        with ExitStack() as scratch:
            scratch.enter_context(budget.reserve(65536+2*raw_array.nbytes, category='differential-workflow-read'))
            raw = raw_array.tobytes()
            slots = 1+sum(raw.count(token) for token in (b'{', b'[', b':', b','))
            scratch.enter_context(budget.reserve(65536+6*len(raw)+128*slots, category='differential-workflow-decode'))
            try:
                record = json.loads(raw)
            except (UnicodeDecodeError, ValueError) as exc:
                raise RegionalOwnerRefused('saved differential geometry is not canonical data') from exc
            fields = {k.removeprefix('differential-network:'): v for k, v in arrays.items()
                      if k.startswith('differential-network:')}
            network = S.restore_network(record['endpoint_network'], fields, budget=budget)
            interval = DifferentialInterval.restore(record['interval'], network, budget=budget)
            return interval

    @staticmethod
    def _spatial_headers(state, exchange, refs):
        # The small lineage remains inspectable without loading old numerical
        # records. Large immutable records use the store's existing chunks.
        names = ('schema', 'state_id', 'owner_id', 'funding_id', 'time_s', 'intervals',
                 'parent_state_id', 'collar_state_id', 'support_id', 'trajectory_id',
                 'grid_id', 'thermal_mesh_id')
        state_header = {k: state[k] for k in names}
        state_header['record_blobs'] = {k: refs[k] for k in (('state',) if 'compact_mesh' in refs else ('state', 'mesh'))}
        if 'compact_mesh' in refs:
            state_header['compact_mesh'] = refs['compact_mesh']
        exchange_header = None
        if exchange is not None:
            names = ('schema', 'result_id', 'state_id', 'owner_id', 'parent_state_id',
                     'collar_state_id', 'source_flow_stage_id', 'source_audit_id',
                     'spatial_graph_id', 'global_transport_id', 'joined_heat_id')
            exchange_header = {k: exchange[k] for k in names}
            exchange_header['parent_collar_state_id'] = exchange['spatial_graph']['parent_state_id']
            exchange_header['record_blobs'] = {k: refs[k] for k in ('exchange', 'graph', 'transport', 'heat')}
        return state_header, exchange_header

    @classmethod
    @contextmanager
    def _spatial_records(cls, state, exchange, budget, *, store=None, source_producer=None, persist_mesh=True, cancel=None, aliases=False, support_source=None):
        if type(getattr(state, '_snapshot', None)) is _COMPACT_SPATIAL.X.IndexedSpatialSnapshot:
            with _COMPACT_SPATIAL.records(cls, state, exchange, budget, store=store,
                    source_producer=source_producer, persist=persist_mesh, cancel=cancel, aliases=aliases, support_source=support_source) as result:
                yield result
            return
        import numpy as np
        from atlas_tectonics.integration.coupling.regional_inventory import _width
        records = dict(state={k: v for k, v in state.items() if k != 'thermal_mesh'},
                       mesh=state['thermal_mesh'])
        if exchange is not None:
            records.update(exchange={k: v for k, v in exchange.items()
                                     if k not in ('spatial_graph', 'transport', 'joined_heat')},
                graph=exchange['spatial_graph'], transport=exchange['transport'], heat=exchange['joined_heat'])
        with budget.reserve(65536+2*sum(_width(r) for r in records.values()), category='spatial-record-encode'):
            arrays, refs = {}, {}
            for kind, record in records.items():
                raw = _json(record)
                name = 'spatial-record:'+kind
                arrays[name] = np.frombuffer(raw, dtype=np.uint8)
                refs[kind] = dict(array=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            a, b = cls._spatial_headers(state, exchange, refs)
            yield a, b, arrays

    @classmethod
    @contextmanager
    def _spatial_restore_records(cls, state_header, exchange_header, arrays, budget, *, store=None):
        if 'compact_mesh' in state_header:
            with _COMPACT_SPATIAL.restore_records(cls, state_header, exchange_header, arrays, budget, store=store) as result:
                yield result
            return
        refs = dict(state_header.get('record_blobs', {}))
        if exchange_header is not None:
            other = exchange_header.get('record_blobs', {})
            refs.update(other)
        kinds = {'state', 'mesh'} | (set() if exchange_header is None else {'exchange', 'graph', 'transport', 'heat'})
        with ExitStack() as stack:
            records = {}
            for kind in sorted(kinds):
                _, values = refs[kind], arrays['spatial-record:'+kind]
                stack.enter_context(budget.reserve(65536+2*values.nbytes, category='spatial-record-read'))
                raw = values.tobytes()
                # Conservative lexical object-width admission before parsing.
                # Counting punctuation within strings only overestimates this
                # bound; numeric tokens and container slots are charged too.
                slots = 1+sum(raw.count(token) for token in (b'{', b'[', b':', b','))
                stack.enter_context(budget.reserve(65536+6*len(raw)+128*slots,
                                                   category='spatial-record-decode'))
                try:
                    record = json.loads(raw)
                except (UnicodeDecodeError, ValueError) as exc:
                    raise RegionalOwnerRefused('saved spatial record is not valid JSON') from exc
                records[kind] = record
            state = dict(records['state'], thermal_mesh=records['mesh'])
            exchange = None if exchange_header is None else dict(records['exchange'],
                spatial_graph=records['graph'], transport=records['transport'], joined_heat=records['heat'])
            yield state, exchange

    @classmethod
    def _inputs(cls, store, collar, owner, funding, budget):
        row = funding.descriptor()
        basal = owner.descriptor().get('basal_side')
        if basal is not None:
            inventory = row.get('basal_inventory')
            if (collar.mechanics_scope != 'complete-grid' or type(inventory) is not dict or
                    not inventory.get('reservoirs') or
                    any(r.get('side') != basal for r in inventory['reservoirs'])):
                raise RegionalOwnerRefused('natural-base workflow requires its actual carved basal finite support')
        return row

    @classmethod
    def create(cls, store, collar, owner, funding, *, budget, exterior_owner=None,
               differential_partition=None, current_geometry=None):
        definition = cls._inputs(store, collar, owner, funding, budget)
        exterior_definition = cls._exterior_inputs(exterior_owner, collar, funding, budget)
        arrays = funding.arrays()
        state = collar.initial_state(owner.initial_state.native_state,
            component_mass_kg=arrays['component_mass_kg'], enthalpy_j=arrays['enthalpy_j'],
            material_tracers={k.removeprefix('tracer:'): v for k, v in arrays.items() if k.startswith('tracer:')},
            source_id=funding.funding_id)
        exterior = None if exterior_owner is None else exterior_owner.initial_state
        if exterior_owner is not None:
            exterior_owner.validate_parent(exterior, state)
        identity = cls._identity(collar, funding, exterior_definition)
        root: dict[str, Any] = dict(schema=cls._schema, workflow_id=identity, key=cls._key('root', identity),
            kind='root', sequence=0, collar_plan=collar.descriptor(), funding=definition,
            funding_id=funding.funding_id, state=state.record(), native_state_id=state.native_state.result_id,
            exterior_remainder=funding.exterior_remainder(),
            outer_material_boundary='closed; no resampling, refill or global advancement',
            source_status='WORKING NON-CANON')
        if exterior_definition is not None:
            root.update(exterior_owner=exterior_definition, exterior_state=_COMPACT_SPATIAL.state_record(exterior),
                outer_material_boundary='paired space-time flux; carried finite exterior inventories')
        family = cls._geometry_family(exterior_owner)
        if family is not None:
            root['geometry_family'] = family
        differential = family == 'differential-plate-component-partition-v1'
        from atlas_tectonics.integration.coupling.spatial_owner import PreparedSpatialOwner
        if type(exterior_owner) is PreparedSpatialOwner:
            with ExitStack() as scratch:
                partition_arrays = {}
                if differential:
                    from atlas_tectonics.integration.geometry.differential_geometry import DifferentialPartition, CurrentGeometry
                    initial = exterior_definition['initial_geometry']
                    if (type(differential_partition) is not DifferentialPartition or
                            type(current_geometry) is not CurrentGeometry or
                            differential_partition.partition_id != initial['partition_id'] or
                            current_geometry.geometry_id != initial['current_geometry_id'] or
                            differential_partition.record()['scope'] != 'initial-current'):
                        raise RegionalOwnerRefused('actual initial partition differs from admitted material geometry')
                    part_header, partition_arrays = scratch.enter_context(cls._partition_payload(
                        differential_partition, current_geometry, funding, collar, budget))
                    root['differential_partition'] = part_header
                header, _, blobs = scratch.enter_context(cls._spatial_records(_COMPACT_SPATIAL.state_record(exterior), None, budget, store=store, source_producer=_COMPACT_SPATIAL.producer(collar)))
                root['exterior_state'] = header
                store.put(root['key'], dict(cls._payload(state, exterior), **blobs, **partition_arrays), root, budget=budget)
        else:
            store.put(root['key'], cls._payload(state, exterior), root, budget=budget)
        self = cls._issued(store, collar, owner, funding, root, budget, exterior_owner)
        self._refresh()
        return self

    @classmethod
    def open(cls, store, workflow_id, collar, owner, funding, *, budget, exterior_owner=None):
        """Use rebuilt plans/funding identities; never replay an accepted interval."""
        definition = cls._inputs(store, collar, owner, funding, budget)
        root = store.metadata(cls._key('root', workflow_id))
        owns_exterior = False
        try:
            from atlas_tectonics.integration.coupling.spatial_owner import PreparedSpatialOwner
            saved_owner = root.get('exterior_owner')
            if (exterior_owner is None and type(saved_owner) is dict and
                    saved_owner.get('schema') == 'atlas.spatial-exterior-owner.v1'):
                # Reconstruct the admitted operator from its saved immutable
                # definition and initial actual fields. No initial flow solve,
                # ALE integration, source seeding or accepted heat is repeated.
                payload = _COMPACT_PARTITION.workflow_arrays(store, root['key'], budget=budget)
                if payload is None:
                    raise RegionalOwnerRefused('saved spatial admission arrays are missing')
                blobs = {k: v for k, v in payload.items() if k.startswith('spatial-record:')}
                fields = {k.removeprefix('exterior-fv:'): v for k, v in payload.items() if k.startswith('exterior-fv:')}
                with cls._spatial_restore_records(root['exterior_state'], None, blobs, budget, store=store) as (saved, _):
                    exterior_owner = PreparedSpatialOwner.from_saved(funding, collar, saved_owner, saved, fields,
                                                                     budget=budget)
                owns_exterior = True
                del payload, blobs, fields
            exterior_definition = cls._exterior_inputs(exterior_owner, collar, funding, budget)
            identity = cls._identity(collar, funding, exterior_definition)
            descriptor = collar.descriptor()
            if (workflow_id != identity or root.get('workflow_id') != identity or
                    root.get('key') != cls._key('root', identity) or root.get('funding') != definition or
                    root.get('funding_id') != funding.funding_id or root.get('collar_plan') != descriptor or
                    root.get('exterior_remainder') != funding.exterior_remainder() or
                    root.get('exterior_owner') != exterior_definition or
                    root.get('geometry_family') != cls._geometry_family(exterior_owner) or
                    root.get('outer_material_boundary') != (
                        'closed; no resampling, refill or global advancement' if exterior_owner is None else
                        'paired space-time flux; carried finite exterior inventories')):
                raise RegionalOwnerRefused('funded collar history or actual physical admission differs')
            from atlas_tectonics._private.codecs.compact_contracts import proving
            # Decision 578: in both modes, today's refusal of an indexed initial state on a store with a scope.
            if (type(exterior_owner) is PreparedSpatialOwner and getattr(store, 'scope', None) is not None and
                    type(getattr(exterior_owner.initial_state, '_snapshot', None)) is _COMPACT_SPATIAL.X.IndexedSpatialSnapshot):
                from atlas_tectonics._private.codecs.compact_contracts import ContractError
                raise ContractError('segmented spatial successors cannot contain mesh aliases')
            # Decision 542 (section 3): re-encoding the owner this open just restored is a round trip.
            if exterior_owner is not None and (proving() or not owns_exterior):
                if type(exterior_owner) is PreparedSpatialOwner:
                    with cls._spatial_records(_COMPACT_SPATIAL.state_record(exterior_owner.initial_state), None, budget, store=store, source_producer=_COMPACT_SPATIAL.producer(collar), persist_mesh=False, aliases=True) as (initial_header, _, _blobs):
                        if root.get('exterior_state') != initial_header:
                            raise RegionalOwnerRefused('spatial admission differs from its single actual funding')
                elif root.get('exterior_state') != cast('ExteriorFVState', cast('PreparedExteriorOwner', exterior_owner).initial_state).record():
                    raise RegionalOwnerRefused('exterior admission differs from its single actual funding')
            if proving():    # proof mode: the initial collar state rebuilt and compared
                initial = collar.initial_state_from_funding(funding, owner)
                if root.get('state') != initial.record() or root.get('native_state_id') != initial.native_state.result_id:
                    raise RegionalOwnerRefused('collar root differs from the actual one-time physical admission')
            self = cls._issued(store, collar, owner, funding, root, budget, exterior_owner)
            self._owns_exterior_owner = owns_exterior
            self._refresh()
            return self
        except BaseException:
            if owns_exterior:
                exterior_owner.close()
            raise

    @classmethod
    def open_migrated(cls, store, workflow_id, base, *, budget):
        from atlas_tectonics._private.integration.workflow_transfer import open_migrated_root
        return open_migrated_root(cls, store, workflow_id, base, budget=budget)

    def _verify(self):
        if getattr(self, '_migration', None) is not None:
            from atlas_tectonics._private.integration.workflow_transfer import verify_migrated_workflow
            verify_migrated_workflow(self)
            return
        if self._exterior_owner is None:
            self._collar._verify()
        self._owner._verify()
        if self._exterior_owner is not None:
            self._exterior_owner._verify()      # verifies the collar itself

    def _refresh(self):
        self._verify()
        token = self._store.change_token()
        if token == self._token:
            return
        root = json.loads(self._root)
        if self._store.metadata(root['key']) != root:
            raise RegionalOwnerRefused('funded collar root changed')
        # Nonzero roots require their own typed transfer restore. This exact
        # boundary does not treat an evidence-only descriptor as admission.
        base_sequence = root.get('sequence')
        if type(base_sequence) is not int or not 0 <= base_sequence <= MAX_INTERVALS:
            raise RegionalOwnerRefused('invalid absolute workflow base sequence')
        if root.get('kind') == 'migrated-root':
            from atlas_tectonics._private.integration.workflow_transfer import verify_migrated_workflow
            verify_migrated_workflow(self)
            if root.get('migration') != self._migration.record() or base_sequence != self._migration.record()['sequence']:
                raise RegionalOwnerRefused('migration root is not its actual admitted base')
        elif root.get('kind') != 'root' or base_sequence != 0:
            raise RegionalOwnerRefused('ordinary root must retain sequence zero')
        previous, accepted_parent = root, None
        for sequence in range(base_sequence+1, MAX_INTERVALS+2):
            key = self._key('successor', previous['key'])
            current = self._store.metadata(key)
            if current is None:
                break
            if sequence > MAX_INTERVALS:
                raise RegionalOwnerRefused('funded collar interval envelope exceeded')
            fields, parent = current['state']['fields'], previous['state']['fields']
            if self._exterior_owner is not None:
                _, _ = current['exterior_state'], previous['exterior_state']
            if self._is_differential():
                geometry = current['differential_geometry']
                partition = current['differential_partition']
                prior_network = (root['funding']['source']['network_id'] if previous['kind'] == 'root' else
                                 previous['differential_geometry']['endpoint_network_id'])
                from atlas_tectonics.integration.geometry.wall_measures import _decode
                if (geometry['parent_network_id'] != prior_network or
                        _decode(geometry['start_time_s']) != Fraction(parent['time_s']) or
                        _decode(geometry['end_time_s']) != Fraction(fields['time_s']) or
                        geometry['prior_trajectory_id'] != previous['exterior_state']['trajectory_id'] or
                        geometry['trajectory_id'] != current['exterior_state']['trajectory_id']):
                    raise RegionalOwnerRefused('saved differential geometry does not continue the actual accepted network/clock')
                self._saved_certification_expected(previous, current)
            accepted_parent, previous = previous, current
        if previous['kind'] == 'migrated-root':
            from atlas_tectonics._private.integration.workflow_transfer import restore_migrated_root
            restore_migrated_root(self, previous, token)
            return
        arrays = cast(dict, _COMPACT_PARTITION.workflow_arrays(self._store, previous['key'], budget=self._budget))
        prefix = 'exterior-fv:'
        exterior_arrays = {k[len(prefix):]: v for k, v in arrays.items() if k.startswith(prefix)}
        audit_prefix = 'source-audit:'
        audit_arrays = {k[len(audit_prefix):]: v for k, v in arrays.items() if k.startswith(audit_prefix)}
        spatial_prefix = 'spatial-audit:'
        spatial_arrays = {k[len(spatial_prefix):]: v for k, v in arrays.items() if k.startswith(spatial_prefix)}
        record_prefix = 'spatial-record:'
        record_arrays = {k: v for k, v in arrays.items() if k.startswith(record_prefix)}
        geometry_prefixes = ('differential-network:', 'differential-record:')
        geometry_arrays = {k: v for k, v in arrays.items() if k.startswith(geometry_prefixes)}
        partition_prefix = 'partition-record:'
        partition_arrays = {k: v for k, v in arrays.items() if k.startswith(partition_prefix)}
        certification_prefixes = ('certification-record:', 'certification-force:')
        certification_arrays = {k: v for k, v in arrays.items() if k.startswith(certification_prefixes)}
        collar_arrays = {k: v for k, v in arrays.items() if not k.startswith((prefix, audit_prefix, spatial_prefix, record_prefix, partition_prefix)+geometry_prefixes+certification_prefixes)}
        state = self._collar.restore(previous['state'], collar_arrays)
        source_audit = None
        if previous['kind'] == 'successor':
            from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
            source_audit = RegionalMechanicalSnapshot(previous['source_audit'], audit_arrays)
        elif audit_arrays:
            raise RegionalOwnerRefused('initial collar cannot contain an unexecuted heat-source audit')
        exterior_state, differential_interval, partition, current_geometry = None, None, None, None
        opened_partition = None
        if self._exterior_owner is not None:
            if self._is_spatial():
                with self._spatial_restore_records(previous['exterior_state'], previous.get('exterior_advance'),
                                                  record_arrays, self._budget, store=self._store) as (saved, exchange):
                    exterior_state = self._exterior_owner.restore(saved, exterior_arrays)
                    from atlas_tectonics._private.codecs.compact_contracts import proving
                    if proving():    # proof mode only
                        self._exterior_owner.validate_parent(exterior_state, state)
                    if exchange is not None:
                        if _SV.field_equals(exchange, 'schema', 'atlas.private.spatial-composed-advance.r1'):
                            from atlas_tectonics.integration.heat import private_heat_cold as COLD
                            with COLD.restore_checkpoint(self, parent=accepted_parent, head=previous,
                                    spatial_state=exterior_state, collar_state=state, source_audit=source_audit,
                                    exchange=exchange, audit_arrays=spatial_arrays) as checkpoint:
                                self._exterior_owner.validate_exchange(exterior_state, exchange,
                                    audit_arrays=spatial_arrays, composed_checkpoint=checkpoint,
                                    collar_state=state)
                        else:
                            self._exterior_owner.validate_exchange(exterior_state, exchange,
                                                                  audit_arrays=spatial_arrays)
                        if self._is_differential():
                            differential_interval = self._restore_differential(previous['differential_geometry'],
                                                                               geometry_arrays, self._budget, store=self._store,
                                source_producer=_COMPACT_SPATIAL.producer(self._collar))
                            interval = differential_interval.record()
                            with _SV.access(exchange) as _validation_exchange:
                                graph = _validation_exchange['spatial_graph']
                                ((graph.get('partition_id'), graph.get('parent_partition_id'),
                                    _hash(graph.get('support_ids')), _COMPACT_SPATIAL.mesh_partition(saved['thermal_mesh'], self._budget))
                                    if proving() else None)    # proof mode: read only by the comparison below
                                # C-1: open B reuses the partition this open already holds (its descriptor decides)
                                opened_partition = _COMPACT_PARTITION.held_partition(saved['thermal_mesh'])
                                from atlas_tectonics.integration.geometry.differential_geometry import current_geometry_from_interval
                                expected = self._saved_certification_expected(accepted_parent, previous)
                                expected['endpoint_current_geometry_id'] = current_geometry_from_interval(
                                    differential_interval, budget=self._budget).geometry_id
                                self._restore_certification(previous['differential_certification'], certification_arrays,
                                    self._budget, graph=graph, interval=interval, expected=expected,
                                    source_audit=source_audit.descriptor(), store=self._store,
                                    source_producer=_COMPACT_SPATIAL.producer(self._collar))
            else:
                exterior_state = self._exterior_owner.restore(previous['exterior_state'], exterior_arrays)
                self._exterior_owner.validate_parent(exterior_state, state)
                if previous['kind'] == 'successor':
                    self._exterior_owner.validate_exchange(exterior_state, previous['exterior_advance'])
        elif exterior_arrays:
            raise RegionalOwnerRefused('unowned exterior arrays in a closed collar checkpoint')
        if self._is_differential():
            partition, current_geometry = self._restore_partition(previous['differential_partition'], partition_arrays,
                self._funding, self._collar, self._budget, interval=differential_interval, store=self._store,
                opened=opened_partition)
            if previous['kind'] == 'root':
                self._exterior_owner.descriptor()['initial_geometry']
            else:
                from atlas_tectonics._private.codecs.compact_contracts import proving
        elif partition_arrays:
            raise RegionalOwnerRefused('unowned differential partition in collar checkpoint')
        if previous['kind'] == 'root':
            self._funding.arrays()
        if token != self._store.change_token():
            raise StoreConflict('funded collar changed during inspection; reopen at accepted head')
        self._head, self._state, self._token = previous, state, token
        self._exterior_state = exterior_state
        self._differential_interval = differential_interval
        self._differential_partition = partition
        self._initial_current_geometry = current_geometry if differential_interval is None else None
        self._source_audit = source_audit

    @property
    def workflow_id(self):
        return json.loads(self._root)['workflow_id']

    @property
    def state(self):
        self._refresh(); return self._state

    @property
    def exterior_state(self):
        self._refresh(); return self._exterior_state

    @property
    def source_audit(self):
        self._refresh(); return self._source_audit

    @property
    def differential_interval(self):
        """Last accepted actual network/trajectory; None at initial admission."""
        self._refresh(); return self._differential_interval

    @property
    def differential_partition(self):
        """Actual accepted component supports; never reseeded on reopening."""
        self._refresh(); return self._differential_partition

    @property
    def current_geometry(self):
        self._refresh()
        if self._differential_interval is None:
            return self._initial_current_geometry
        from atlas_tectonics.integration.geometry.differential_geometry import current_geometry_from_interval
        return current_geometry_from_interval(self._differential_interval, budget=self._budget)

    @property
    def spatial_audit_arrays(self):
        """Read-only saved numerical evidence, not a replayed operator result."""
        self._refresh()
        if not self._is_spatial() or self._head['kind'] != 'successor':
            return None
        from types import MappingProxyType
        arrays = self._store.get(self._head['key'], budget=self._budget)
        return MappingProxyType({k.removeprefix('spatial-audit:'): v for k, v in arrays.items()
                                 if k.startswith('spatial-audit:')})

    def retained_inventory_accounts(self):
        """Inspect this accepted head without a physics replay or source refill."""
        self._refresh()
        return retained_inventory_accounts(self._state, self._exterior_state, budget=self._budget)

    def inspect(self):
        self._refresh()
        return dict(workflow_id=self.workflow_id, head=self._head['key'], intervals=self._head['sequence'],
            time_s=self._state.fields.descriptor()['time_s'], funding_id=self._funding.funding_id,
            state_id=self._state.result_id, global_background_advanced=False,
            exterior_state_id=None if self._exterior_state is None else self._exterior_state.state_id,
            exterior_time_s=None if self._exterior_state is None else self._exterior_state.time_s,
            source_audit_id=None if self._source_audit is None else self._source_audit.result_id,
            scope=('one physically funded native/collar clock; closed outer material interface'
                   if self._exterior_owner is None else
                   'one native/collar and moving funded-exterior clock; no whole-planet acceptance claim'))

    def advance(self, duration_s, *, wall_measures=None, **driving):
        self._refresh()
        parent, state = self._head, self._state
        if parent['sequence'] >= MAX_INTERVALS:
            raise RegionalOwnerRefused('funded collar interval envelope exceeded')
        if 'boundary_stocks' in driving:
            raise RegionalOwnerRefused('outer material stock requires an issued exterior transfer owner')
        fields = state.fields
        tracers = tuple(k.removeprefix('tracer:') for k in fields.array_names if k.startswith('tracer:'))
        if self._exterior_owner is None:
            stocks = self._collar._transport.empty_boundary_stocks(
                fields.array('component_mass_kg').shape[0], tracer_names=tracers)
            offer = None
        else:
            self._exterior_owner.validate_parent(self._exterior_state, state)
            offer = self._exterior_owner.prepare(self._exterior_state, wall_measures)
            self._exterior_owner.validate_driving(offer, driving.get('rigid_motion'), duration_s)
            stocks = offer.boundary_stocks
        result = self._collar.advance(state, duration_s, boundary_stocks=stocks,
                                      wall_measures=wall_measures, **driving)
        exterior_advance = (None if offer is None else
            self._exterior_owner.advance(self._exterior_state, offer, result))
        return self._publish(parent, result, exterior_advance, cancel=driving.get('cancel'))

    def _spatial_wall(self, wall_measures, duration_s):
        from atlas_tectonics.integration.geometry.wall_measures import _decode
        from atlas_tectonics._validation import scalar
        self._exterior_owner.validate_parent(self._exterior_state, self._state)
        wall, exterior = wall_measures.descriptor(), _COMPACT_SPATIAL.logical_record(self._exterior_state)
        dt = scalar(duration_s, 'spatial duration', positive=True)
        start, end = (_decode(wall[k]) for k in ('start_time_s', 'end_time_s'))
        if (wall['funding_id'] != self._funding.funding_id or wall['collar_plan_id'] != self._collar.plan_id or
                wall['parent_state_id'] != self._exterior_state.state_id or
                start != Fraction(self._exterior_state.time_s) or end-start != Fraction(dt) or
                end != Fraction(self._exterior_state.time_s+dt) or
                wall['start_support_id'] != exterior['support_id'] or
                wall['prior_trajectory_id'] != exterior['trajectory_id']):
            raise RegionalOwnerRefused('spatial wall source, parent, exact clock or carried trajectory differs')
        if self._head['sequence'] >= MAX_INTERVALS:
            raise RegionalOwnerRefused('funded collar interval envelope exceeded')
        return dt

    def _spatial_current(self, current_geometry, duration_s):
        from atlas_tectonics.integration.geometry import differential_geometry as D
        from atlas_tectonics.integration.geometry.wall_measures import _decode
        from atlas_tectonics._validation import scalar
        self._exterior_owner.validate_parent(self._exterior_state, self._state)
        dt = scalar(duration_s, 'spatial duration', positive=True)
        current = current_geometry.record()
        expected_network = (self._funding.descriptor()['source']['network_id'] if self._differential_interval is None
                            else self._differential_interval.endpoint_network.network_id)
        if (current['network_id'] != expected_network or
                _decode(current['time_s']) != Fraction(self._exterior_state.time_s)):
            raise RegionalOwnerRefused('current force geometry differs from the accepted network or clock')
        if self._differential_interval is not None:
            D.current_geometry_from_interval(self._differential_interval, budget=self._budget)
        elif current_geometry.geometry_id != self._initial_current_geometry.geometry_id:
            raise RegionalOwnerRefused('current force geometry differs from the saved static source partition')
        if self._head['sequence'] >= MAX_INTERVALS:
            raise RegionalOwnerRefused('funded collar interval envelope exceeded')
        return dt

    def _spatial_differential(self, interval, duration_s):
        from atlas_tectonics.integration.geometry.wall_measures import _decode
        from atlas_tectonics._validation import scalar
        self._exterior_owner.validate_parent(self._exterior_state, self._state)
        dt = scalar(duration_s, 'spatial duration', positive=True)
        record, _ = interval.record(), _COMPACT_SPATIAL.logical_record(self._exterior_state)
        start, end = (_decode(record[k]) for k in ('start_time_s', 'end_time_s'))
        if self._head['sequence'] >= MAX_INTERVALS:
            raise RegionalOwnerRefused('funded collar interval envelope exceeded')
        return dt

    def source_flow_stage(self, duration_s, *, wall_measures=None, current_geometry=None, **driving):
        """Solve donor sources/flow only, so actual space-time geometry can bind it.

        This publishes nothing. The caller must issue physical ALE bounds and
        an endpoint thermal mesh, then call advance_spatial on this same head.
        """
        self._refresh()
        if current_geometry is not None:
            dt = self._spatial_current(current_geometry, duration_s)
        else:
            dt = self._spatial_wall(wall_measures, duration_s)
        return self._collar.source_flow_stage(self._state, dt, wall_measures=wall_measures, **driving)

    def advance_spatial(self, source_flow_stage, bounds, mesh, *, wall_measures=None, differential_interval=None,
                        differential_partition=None, differential_solution=None,
                        heat_boundary=None, finite_exchanges=None, cancel=None,
                        heat_execution=None, absolute_heat_residual_target=None):
        """One actual joint advection/heat/endpoint and one atomic publication.

        No callback or raw record can substitute for the issued source stage,
        physical geometry, conservative transport or current-capacity heat.
        The explicit first-order method is bound by the owner before step one.
        """
        from atlas_tectonics.regional.execution3d import _cancel
        self._certification_required(self._is_differential(), differential_solution)
        self._refresh(); _cancel(cancel)
        private_heat = (self._is_spatial() and self._exterior_owner._heat_label ==
            'PRIVATE uniform-k composed physical-face heat; original transported caloric stocks')
        if private_heat:
            from atlas_tectonics._private.integration.heat import joined_consumer as JOINED
            JOINED.I._target_text(absolute_heat_residual_target, cancel)
            JOINED.I._target_provenance(absolute_heat_residual_target)
        elif heat_execution is not None or absolute_heat_residual_target is not None:
            raise RegionalOwnerRefused('private heat arguments cannot change another declared method')
        # The explicit original target is persisted in joined_heat_plan and its
        # tagged declaration/hash is bound by the separately committed heat CAS.
        # Live result/call ownership remains held through endpoint/publication.
        self._collar._check_source_flow_stage(source_flow_stage)
        parent, _ = self._head, self._state
        if differential_interval is not None:
            self._spatial_differential(differential_interval, source_flow_stage.duration_s)
        else:
            self._spatial_wall(wall_measures, source_flow_stage.duration_s)
        # Reject known wrong endpoints before either joint operator runs.
        _thermal_header = _COMPACT_SPATIAL.X.mesh_header(mesh, self._budget)
        geometry, thermal = bounds.record(), _thermal_header.value
        if differential_interval is None:
            wall = wall_measures.descriptor()
            if (source_flow_stage.flow.descriptor().get('wall_measure_id') != wall['measure_id'] or
                    geometry['wall_measure_id'] != wall['measure_id'] or
                    thermal['wall_measure_id'] != wall['measure_id']):
                raise RegionalOwnerRefused('spatial solve and thermal mesh have another actual wall measure')
        else:
            wall = differential_interval.record()
            part = cast('DifferentialPartition', differential_partition).record()
            if (part.get('parent_partition_id') != cast('DifferentialPartition', self._differential_partition).partition_id or
                    part.get('interval_id') != differential_interval.interval_id or
                    part['funding_id'] != self._funding.funding_id or
                    part['collar_plan_id'] != self._collar.plan_id or
                    part['source'] != self._funding.descriptor()['source'] or
                    part['start_time_s'] != wall['start_time_s'] or part['end_time_s'] != wall['end_time_s'] or
                    part['grid_id'] != _COMPACT_PARTITION.field(self._differential_partition, 'grid_id').value or
                    geometry.get('partition_id') != cast('DifferentialPartition', differential_partition).partition_id or
                    thermal.get('partition_id') != cast('DifferentialPartition', differential_partition).partition_id or
                    geometry.get('parent_partition_id') != cast('DifferentialPartition', self._differential_partition).partition_id or
                    source_flow_stage.flow.descriptor().get('mechanics_scope') != 'complete-grid' or
                    geometry.get('interval_id') != differential_interval.interval_id or
                    thermal.get('interval_id') != differential_interval.interval_id or
                    thermal.get('ale_bounds_id') != bounds.bounds_id or
                    thermal.get('support_ids') != geometry.get('support_ids') or
                    geometry['trajectory'] != wall['trajectory']):
                raise RegionalOwnerRefused('spatial solve/thermal support differs from the actual differential interval')
        if (geometry['source_flow_stage_id'] != source_flow_stage.result_id or
                geometry['flow_id'] != source_flow_stage.flow.flow_id or
                thermal['funding_id'] != self._funding.funding_id or
                thermal['source'] != geometry['source'] or thermal['grid_id'] != geometry['grid_id'] or
                thermal['support_id'] != wall['end_support_id'] or
                thermal['trajectory_id'] != wall['trajectory_id'] or thermal['time_s'] != wall['end_time_s']):
            raise RegionalOwnerRefused('spatial thermal mesh is not the actual source/flow endpoint')
        # These complete decoded records are validation scratch, not state for
        # either operator. Keep the issued handles, but do not carry redundant
        # mesh/geometry/partition copies through transport and heat preparation.
        del geometry, thermal, wall
        if differential_interval is not None:
            del part
        graph = (self._exterior_owner.close_graph(self._exterior_state, source_flow_stage, bounds)
                 if differential_interval is None else self._validate_differential_solution(
                     differential_solution, source_flow_stage, differential_interval, differential_partition, bounds))
        _cancel(cancel)
        step = self._exterior_owner.transport(self._exterior_state, source_flow_stage, graph,
                                               finite_exchanges=finite_exchanges, cancel=cancel)
        transport = self._collar.transport_from_spatial(source_flow_stage, step.result, graph,
            method=self._exterior_owner.descriptor()['method'],
            finite_proposal=step.finite_proposal, cancel=cancel)
        if private_heat:
            # R3: where this workflow's own heat checkpoint save starts (None: today's path).
            _r3_mark = self._r3_write_mark()
            heat = self._exterior_owner.heat(step, mesh, boundary=heat_boundary, cancel=cancel,
                execution=heat_execution, absolute_residual_target=absolute_heat_residual_target,
                checkpoint_store=self._store)
            self._r3_after_heat_checkpoint(_r3_mark)
        else:
            heat = self._exterior_owner.heat(step, mesh, boundary=heat_boundary, cancel=cancel)
        adopted_heat = self._collar.heat_from_spatial(transport, heat, mesh, cancel=cancel)
        result = self._collar.endpoint_from_transport(transport, adopted_heat, cancel=cancel)
        if private_heat:
            exterior = self._exterior_owner.finish(step, mesh, heat, result, cancel=cancel)
        else:
            exterior = self._exterior_owner.finish(step, mesh, heat, result)
        return self._publish(parent, result, exterior, differential_interval=differential_interval,
                             differential_partition=differential_partition,
                             differential_solution=differential_solution, cancel=cancel)

    def _r3_write_mark(self):
        """R3 (WP-owned): where this workflow's own next store write starts, or None.

        Only a compact restart facade with a writing interval candidate, and only while
        this workflow's token is current; anything else keeps today's behaviour."""
        import sqlite3
        import sys
        try:
            from atlas_tectonics._private.codecs.interval_store_set import UnlistedCandidate
            facade = sys.modules.get('atlas_tectonics._private.codecs.compact_restart_store')
            candidate = getattr(self._store, 'candidate', None)
            if (self._token is None or facade is None or not facade.is_compact_restart_store(self._store) or
                    type(candidate) is not UnlistedCandidate):
                return None
            token = self._store.change_token()
            if token != self._token:
                return None
            return {'token': token, 'candidate': candidate}
        except (KeyError, ValueError, TypeError, AttributeError, sqlite3.Error):
            return None

    def _r3_heat_checkpoint_reason(self, mark):
        """R3: why the token after this workflow's own heat checkpoint save cannot be kept, or None.
        Compares tokens only: the save is not read back."""
        candidate, before = mark['candidate'], mark['token']
        after = self._store.change_token()
        if self._token != before or self._store.candidate is not candidate:
            return 'workflow token or candidate changed during the heat step', after
        if after[:2] != before[:2] or after[2][0] != before[2][0]:
            return 'catalog or interval changed during the heat step', after
        return None, after

    def _r3_after_heat_checkpoint(self, mark):
        """R3 (WP-owned): keep the token across this workflow's OWN heat checkpoint save.

        Adopted only when _r3_heat_checkpoint_reason finds nothing; otherwise nothing is
        set and the next _refresh() runs in full, exactly as today."""
        import sqlite3
        reason = 'workflow not current on a compact candidate before the save'
        if mark is not None:
            try:
                reason, after = self._r3_heat_checkpoint_reason(mark)
            except (KeyError, ValueError, TypeError, AttributeError, sqlite3.Error) as error:
                reason = 'check refused: ' + type(error).__name__
            if reason is None:
                self._token = after
        self._r3_heat_checkpoint = {'token_kept': reason is None, 'reason': reason}

    def _publish(self, parent, result, exterior_advance, *, differential_interval=None,
                 differential_partition=None, differential_solution=None, cancel=None):
        """One immutable successor for every supported paired operator route."""
        self._certification_required(self._is_differential(), differential_solution)
        self._verify()
        if differential_solution is not None:
            source = differential_solution.proposal.source_flow_stage
            self._validate_differential_solution(differential_solution, source, differential_interval,
                                                differential_partition, differential_solution.bounds)
        duration_s = result.source_stage.source_audit.descriptor()['duration_s']
        row = dict(schema=self._schema, workflow_id=self.workflow_id,
            key=self._key('successor', parent['key']), kind='successor', sequence=parent['sequence']+1,
            parent_key=parent['key'], parent_digest=_hash(parent), funding_id=self._funding.funding_id,
            native_state_id=result.state.native_state.result_id,
            source_audit=result.source_stage.source_audit.descriptor(),
            state=result.state.record(), advance=dict(duration_s=float(duration_s),
                source_audit_id=result.source_stage.source_audit.result_id,
                flow_id=result.flow.result_id, transport_id=result.transport.result_id, heat_id=result.heat.result_id))
        if exterior_advance is not None:
            row.update(exterior_state=_COMPACT_SPATIAL.state_record(exterior_advance.state),
                       exterior_advance=_COMPACT_RECORDS.advance_header(exterior_advance))

        _r2_tokens = []

        def check():
            self._verify()
            root = json.loads(self._root)
            if self._store.metadata(parent['key']) != parent or self._store.metadata(root['key']) != root:
                raise StoreConflict('funded collar parent/admission changed before publication')
            # R2: the change token this writer produced, read inside its own transaction.
            _r2_tokens.append(self._store.change_token())

        if cancel is not None and not hasattr(cancel, 'is_set'):
            cancel = SimpleNamespace(is_set=cancel)
        exterior_state = None if exterior_advance is None else exterior_advance.state
        spatial_audit = exterior_advance.audit_arrays() if self._is_spatial() else None
        payload = self._payload(result.state, exterior_state, result.source_stage.source_audit, spatial_audit)
        if self._is_spatial():
            with ExitStack() as scratch:
                support_source = None
                if differential_interval is not None:
                    header, certification_arrays = scratch.enter_context(self._certification_payload(
                        differential_solution, self._budget, store=self._store,
                        source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))
                    row['differential_certification'] = header
                    payload.update(certification_arrays)
                    header, geometry_arrays = scratch.enter_context(self._differential_payload(differential_interval, self._budget, store=self._store,
                        source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))
                    row['differential_geometry'] = header
                    payload.update(geometry_arrays)
                    # (b') the selected route issues native proposals: convert once here (payload would
                    # convert inside), so the published view's support source can serve the mesh.
                    publication_partition = _PUBLISH_MESH.compact_partition(differential_partition,
                        differential_interval, self._funding, self._collar, self._budget, self._store)
                    header, partition_arrays = scratch.enter_context(self._partition_payload(
                        publication_partition, differential_interval, self._funding, self._collar, self._budget,
                        store=self._store, source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))
                    row['differential_partition'] = header
                    payload.update(partition_arrays)
                    # (b') D1: the mesh built at JC 408 is compact and unpublished; persist_mesh
                    # publishes it below, after this partition, from that partition's support source.
                    support_source = _PUBLISH_MESH.published_support_source(publication_partition,
                        self._store, scratch, source_producer=_COMPACT_SPATIAL.producer(self._collar))
                saved, exchange, blobs = scratch.enter_context(self._spatial_records(
                    row['exterior_state'], scratch.enter_context(_COMPACT_RECORDS.advance_record(exterior_advance)),
                    self._budget, store=self._store, source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel,
                    support_source=support_source))
                row.update(exterior_state=saved, exterior_advance=exchange)
                self._store.put(row['key'], dict(payload, **blobs), row, publication_check=
                                _COMPACT_RECORDS.publication_check(check, self._store, row, budget=self._budget, cancel=cancel,
                                source_producer=_COMPACT_SPATIAL.producer(self._collar)),
                                cancel=cancel, budget=self._budget)
        else:
            self._store.put(row['key'], payload, row, publication_check=check, cancel=cancel, budget=self._budget)
        # R2: adopt only the in-transaction token, and only when no write intervened
        # after commit; the adopted head is the persisted metadata. Otherwise None.
        _r2_after = self._store.change_token()
        _r2_head = None
        if len(_r2_tokens) == 1 and _r2_tokens[0] == _r2_after:
            _r2_head = self._store.metadata(row['key'])
            if (_r2_head is None or _hash(_r2_head) != _hash(row) or
                    self._store.change_token() != _r2_after):
                _r2_head = None
        self._published_identity = dict(key=row['key'], sha256=_hash(row),
                                        token_adopted=_r2_head is not None)
        if _r2_head is None:
            self._head, self._state, self._token = row, result.state, None
        else:
            self._head, self._state, self._token = _r2_head, result.state, _r2_tokens[0]
            # Mirror the full _refresh post-state for a successor head.
            self._initial_current_geometry = None
        self._exterior_state = exterior_state
        self._source_audit = result.source_stage.source_audit
        self._differential_interval = differential_interval
        self._differential_partition = differential_partition
        _RESTART.postpublication(self, parent, row, cancel=cancel)
        return result if exterior_advance is None else CoupledCollarAdvance(result, exterior_advance)

    def close(self):
        if not self._closed and self._owns_exterior_owner:
            self._exterior_owner.close()
        self._closed = True             # caller owns plans and immutable funding

    def __enter__(self):
        self._verify(); return self

    def __exit__(self, *_):
        self.close()
from atlas_tectonics._private.integration.geometry import spatial_validation_patch as _SV  # compact validation r1
