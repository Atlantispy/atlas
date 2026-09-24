"""Finite shared W08 stocks and conservative single-segment transition adapters.

The event workflow serialises spending. These functions branch only from the
supplied inventory; neither terminal magma nor retirement destinations are a
second physical copy available to a derived load/heat projection. Node origin
and formation labels are source-owned bookkeeping, never inferred new births.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import weakref

import numpy as np

from ._validation import TectonicsError, frozen, input_shape, read_array, scalar
from .constitutive import _cancel
from .magmatic_transfer import MagmaticInventory, PreparedMagmaticTransfer
from .materials import MaterialCohort, _json, _name
from .resources import DEFAULT_BUDGET, WorkBudget, select_budget
from .subduction_materials import (
    DESTINATIONS, PreparedSubductionRetirement, SubductionInventory)


CAP = 128*1024**2
ROUND = 128*np.finfo(float).eps
KINDS = ('crust', 'mantle', 'source-solid', 'source-melt', 'reservoir',
         'intrusion', 'extrusion', 'export', 'accretion', 'deep-storage')
_DEFAULT_BUDGET = WorkBudget(CAP, parent=DEFAULT_BUDGET)
_RETIREMENT_KEYS = frozenset((
    'epoch_id', 'density_kg_m3', 'thickness_m', 'material_velocity_m_s',
    'boundary_velocity_m_s', 'outward_normal', 'strike_direction',
    'section_width_m', 'frame_id', 'section_policy', 'destination_fractions',
    'flux_source', 'partition_source'))


def _owner(budget):
    return WorkBudget(CAP, parent=_DEFAULT_BUDGET if budget is None else select_budget(budget))


def _sum(values):
    try:
        value = math.fsum(float(x) for x in values)
    except (ValueError, OverflowError) as exc:
        raise TectonicsError('W08 extensive account exceeds finite arithmetic') from exc
    if not math.isfinite(value):
        raise TectonicsError('nonfinite W08 extensive account')
    return value


def _names(values, label):
    if type(values) is not tuple or not 1 <= len(values) <= 64:
        raise TectonicsError('one to 64 explicit '+label+' required')
    for value in values:
        _name(value, label)
    if values != tuple(sorted(set(values))):
        raise TectonicsError(label+' must be unique and lexically sorted')
    return values


def _identity(record, *arrays):
    digest = hashlib.sha256(_json(record))
    for array in arrays:
        digest.update(_json((array.shape, array.dtype.str)))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _keep(array, owner):
    # Each small retained payload owns its lease. Borrowing an earlier state's
    # bytes would pin this state's reservation until that earlier state dies.
    checked = frozen(array)
    value = np.frombuffer(checked.tobytes(), dtype=np.float64).reshape(checked.shape)
    lease = owner.reserve(value.nbytes+256, category='w08-inventory-retained')
    lease.__enter__()
    root = value
    while isinstance(root.base, np.ndarray):
        root = root.base
    weakref.finalize(root, lease.__exit__, None, None, None)
    return value


@dataclass(frozen=True, init=False)
class W08Inventory:
    """Immutable complete component/enthalpy stocks and explicit node metadata.

    Arrays have immutable byte backing and private public descriptors. The
    detached JSON descriptor plus the two extensive arrays reconstructs the
    inventory; formation times are finite seconds in the workflow's epoch.
    Origins describe declared rows, including receiving stores. Transfer receipts
    retain donor lineage; a receiving store's label is not a new formation event.
    """
    node_ids: tuple
    node_kinds: tuple
    component_ids: tuple
    origin_ids: tuple
    source_id: str
    enthalpy_source: str
    time_s: float
    inventory_id: str
    _components: np.ndarray = field(repr=False, compare=False)
    _enthalpy: np.ndarray = field(repr=False, compare=False)
    _formation: np.ndarray = field(repr=False, compare=False)
    _mass: np.ndarray = field(repr=False, compare=False)
    _record: bytes = field(repr=False, compare=False)

    def __init__(self, node_ids, node_kinds, component_ids, component_mass_kg,
                 enthalpy_j, *, source_id, enthalpy_source, time_s=0.,
                 formation_time_s, origin_ids, budget=None, cancel=None):
        _cancel(cancel)
        nodes = _names(node_ids, 'node IDs')
        components = _names(component_ids, 'component IDs')
        count, kinds = len(nodes), node_kinds
        if (type(kinds) is not tuple or len(kinds) != count
                or any(kind not in KINDS for kind in kinds)):
            raise TectonicsError('one explicit supported kind per W08 node required')
        if type(origin_ids) is not tuple or len(origin_ids) != count:
            raise TectonicsError('one explicit source-owned origin per W08 node required')
        for origin in origin_ids:
            _name(origin, 'origin')
        _name(source_id, 'inventory source')
        _name(enthalpy_source, 'enthalpy convention')
        now = scalar(time_s, 'inventory time')
        if (input_shape(component_mass_kg) != (count, len(components))
                or input_shape(enthalpy_j) != (count,)
                or input_shape(formation_time_s) != (count,)):
            raise TectonicsError('component(N,K), enthalpy(N), formation-time(N) shapes required')
        owner = _owner(budget)
        with owner.reserve(96*count*(len(components)+4)+8192,
                           category='w08-inventory-input'):
            c = read_array(component_mass_kg, 'component mass', nonnegative=True)
            e = read_array(enthalpy_j, 'signed enthalpy')
            formation = read_array(formation_time_s, 'source formation times')
            if c.shape != (count, len(components)) or e.shape != (count,) or formation.shape != (count,):
                raise TectonicsError('W08 input shape changed during capture')
            if np.any(formation > now):
                raise TectonicsError('source formation time cannot lie after inventory time')
            mass = np.array([_sum(row) for row in c])
            if np.any((mass == 0) & (e != 0)):
                raise TectonicsError('empty stock cannot contain enthalpy or implicit throughflow')
            record = dict(schema='atlas.w08-inventory.v1', node_ids=nodes,
                node_kinds=kinds, component_ids=components, origin_ids=origin_ids,
                formation_time_s=formation.tolist(), source_id=source_id,
                enthalpy_source=enthalpy_source, time_s=now)
            encoded = _json(record)
            if len(encoded) > 131072:
                raise TectonicsError('W08 inventory metadata exceeds bounded descriptor')
            values = dict(node_ids=nodes, node_kinds=kinds, component_ids=components,
                origin_ids=origin_ids, source_id=source_id, enthalpy_source=enthalpy_source,
                time_s=now, inventory_id=_identity(record, c, e), _record=encoded,
                _components=_keep(c, owner), _enthalpy=_keep(e, owner),
                _formation=_keep(formation, owner), _mass=_keep(mass, owner))
            lease = owner.reserve(len(encoded)+1024, category='w08-inventory-metadata')
            lease.__enter__()
            weakref.finalize(self, lease.__exit__, None, None, None)
            for key, value in values.items():
                object.__setattr__(self, key, value)
        _cancel(cancel)

    @property
    def component_mass_kg(self): return self._components.view()
    @property
    def enthalpy_j(self): return self._enthalpy.view()
    @property
    def formation_time_s(self): return self._formation.view()
    @property
    def mass_kg(self): return self._mass.view()
    @property
    def nbytes(self):
        return sum(a.nbytes for a in (self._components, self._enthalpy,
                                      self._formation, self._mass))+len(self._record)

    def descriptor(self):
        return json.loads(self._record)

    def retime(self, time_s, *, source_id=None, budget=None, cancel=None):
        """Cessation/chronology only: preserve every stock and formation label."""
        now = scalar(time_s, 'inventory time')
        if now < self.time_s:
            raise TectonicsError('W08 inventory time cannot run backwards')
        return self._replace(self._components, self._enthalpy, now,
            self.source_id if source_id is None else source_id, budget, cancel)

    def _replace(self, c, e, time_s, source_id, budget, cancel):
        return W08Inventory(self.node_ids, self.node_kinds, self.component_ids, c, e,
            source_id=source_id, enthalpy_source=self.enthalpy_source, time_s=time_s,
            formation_time_s=self._formation, origin_ids=self.origin_ids,
            budget=budget, cancel=cancel)


def _selection(inventory, selected):
    if type(inventory) is not W08Inventory:
        raise TectonicsError('explicit W08Inventory required')
    _names(selected, 'selected node IDs')
    if any(node not in inventory.node_ids for node in selected):
        raise TectonicsError('selected node is absent from the shared W08 inventory')
    return [inventory.node_ids.index(node) for node in selected]


def _closure(initial, components, enthalpy, heat, moved_c, moved_e):
    """Compensated component and signed-enthalpy accounts, same 128-eps gate."""
    residuals = []
    for old, new, external, transfers in [
            *((initial._components[:, k], components[:, k], (), moved_c[..., k].flat)
              for k in range(len(initial.component_ids))),
            (initial._enthalpy, enthalpy, heat, moved_e.flat)]:
        old, new, external, transfers = map(tuple, (old, new, external, transfers))
        residual = _sum((*new, *(-x for x in old), *(-x for x in external)))
        scale = _sum(abs(x) for group in (old, new, external, transfers) for x in group)
        if abs(residual) > ROUND*scale:
            raise TectonicsError('global W08 component/enthalpy account does not close')
        residuals.append(residual)
    return dict(component_residual_kg=residuals[:-1], enthalpy_residual_j=residuals[-1])


def advance_magmatic(inventory, selected_node_ids, rates_kg_s, duration_s, *,
                     source_id, heat_w=None, thermodynamics=None, context=None,
                     budget=None, cancel=None):
    """Map a finite magma segment into exact shared rows, retaining all others."""
    _cancel(cancel)
    indices = _selection(inventory, selected_node_ids)
    owner = _owner(budget)
    with owner.reserve(256*len(inventory.node_ids)*(len(inventory.component_ids)+4)+65536,
                       category='w08-magmatic-adapter'):
        local = MagmaticInventory(selected_node_ids, tuple(inventory.node_kinds[i] for i in indices),
            inventory.component_ids, inventory._components[indices], inventory._enthalpy[indices],
            source_id=inventory.inventory_id, enthalpy_source=inventory.enthalpy_source,
            time_s=inventory.time_s, budget=owner, cancel=cancel)
        with PreparedMagmaticTransfer(local, rates_kg_s, source_id=source_id, heat_w=heat_w,
                thermodynamics=thermodynamics, context=context, budget=owner, cancel=cancel) as plan:
            result = plan.evaluate(duration_s, cancel=cancel)
            c, e = inventory._components.copy(), inventory._enthalpy.copy()
            c[indices], e[indices] = result.remaining.component_mass_kg, result.remaining.enthalpy_j
            moved_c, moved_e, heat = (result.transferred_component_mass_kg,
                result.transferred_enthalpy_j, result.external_heat_j)
            account = _closure(inventory, c, e, heat, moved_c, moved_e)
            updated = inventory._replace(c, e, result.remaining.time_s, plan.plan_id, owner, cancel)
            record = dict(operation='atlas.w08-inventory-magmatic.v1', source_id=source_id,
                initial_inventory_id=inventory.inventory_id, inventory_id=updated.inventory_id,
                selected_node_ids=selected_node_ids, duration_s=result.duration_s,
                plan_id=plan.plan_id, result_id=result.result_id, edge_ids=result.edge_ids,
                transferred_mass_kg=result.transferred_mass_kg.tolist(),
                transferred_component_mass_kg=moved_c.tolist(), transferred_enthalpy_j=moved_e.tolist(),
                external_heat_j=heat.tolist(), external_heat_total_j=_sum(heat),
                exhaustion_duration_s=plan.exhaustion_duration_s,
                exhausted_node_ids=result.descriptor()['exhausted_nodes'], account=account,
                kernel=result.descriptor(),
                ownership='shared inventory owns terminal stocks; edge transfers are receipts only')
            _cancel(cancel)
            return updated, json.loads(_json(record))


def advance_retirement(inventory, selected_node_ids, destination_ids, duration_s, *,
                       source_id, parameters, budget=None, cancel=None):
    """Debit finite crust/mantle cohorts and credit all three declared stores.

    ``parameters`` contains epoch_id and all explicit physical parameters of
    PreparedSubductionRetirement except destinations/source/budget/cancel. The
    caller's outer ExecutionContext verifies source/runtime identity.
    """
    _cancel(cancel)
    indices = _selection(inventory, selected_node_ids)
    if any(inventory.node_kinds[i] not in ('crust', 'mantle') for i in indices):
        raise TectonicsError('retirement sources must be explicitly crust or mantle')
    if (type(destination_ids) is not tuple or len(destination_ids) != 3
            or any(type(node) is not str for node in destination_ids)
            or len(set(destination_ids)) != 3
            or any(node not in inventory.node_ids for node in destination_ids)):
        raise TectonicsError('three distinct existing retirement destinations required')
    destinations = [inventory.node_ids.index(node) for node in destination_ids]
    if tuple(inventory.node_kinds[i] for i in destinations) != DESTINATIONS:
        raise TectonicsError('destination order must be accretion, deep-storage, export')
    if type(parameters) is not dict or parameters.keys() != _RETIREMENT_KEYS:
        raise TectonicsError('complete explicit retirement parameters including epoch_id required')
    supplied = dict(parameters)
    epoch = supplied.pop('epoch_id')
    _name(epoch, 'retirement epoch')
    owner = _owner(budget)
    with owner.reserve(512*len(inventory.node_ids)*(len(inventory.component_ids)+4)+65536,
                       category='w08-retirement-adapter'):
        cohorts = tuple(MaterialCohort(inventory.node_ids[i], inventory.node_kinds[i],
            inventory.origin_ids[i], inventory._formation[i]) for i in indices)
        local = SubductionInventory(cohorts, tuple(inventory.node_kinds[i] for i in indices),
            inventory._mass[indices], inventory.component_ids, inventory._components[indices],
            inventory._enthalpy[indices], time_s=inventory.time_s, epoch_id=epoch,
            source_id=inventory.inventory_id, enthalpy_source=inventory.enthalpy_source,
            budget=owner, cancel=cancel)
        with PreparedSubductionRetirement(local, destination_kinds=DESTINATIONS,
                destination_ids=destination_ids, source_id=source_id, **supplied,
                budget=owner, cancel=cancel) as plan:
            result = plan.evaluate(duration_s, cancel=cancel)
            c, e = inventory._components.copy(), inventory._enthalpy.copy()
            c[indices], e[indices] = result.remaining.component_mass_kg, result.remaining.enthalpy_j
            moved_c, moved_e = result.destination_component_mass_kg, result.destination_enthalpy_j
            for target, row in zip(destinations, range(3)):
                for k in range(len(inventory.component_ids)):
                    c[target, k] = _sum((c[target, k], *moved_c[row, :, k]))
                e[target] = _sum((e[target], *moved_e[row]))
            account = _closure(inventory, c, e, (), moved_c, moved_e)
            updated = inventory._replace(c, e, result.remaining.time_s, plan.plan_id, owner, cancel)
            record = dict(operation='atlas.w08-inventory-retirement.v1', source_id=source_id,
                initial_inventory_id=inventory.inventory_id, inventory_id=updated.inventory_id,
                selected_node_ids=selected_node_ids, destination_ids=destination_ids,
                destination_kinds=DESTINATIONS, duration_s=result.duration_s,
                plan_id=plan.plan_id, result_id=result.result_id,
                retired_component_mass_kg=result.retired_component_mass_kg.tolist(),
                retired_enthalpy_j=result.retired_enthalpy_j.tolist(),
                transferred_mass_kg=result.destination_mass_kg.tolist(),
                transferred_component_mass_kg=moved_c.tolist(), transferred_enthalpy_j=moved_e.tolist(),
                external_heat_j=[], external_heat_total_j=0.,
                exhaustion_duration_s=plan.exhaustion_duration_s,
                exhausted_node_ids=result.descriptor()['exhausted_cohort_ids'], account=account,
                source_cohorts=local.descriptor()['cohorts'], kernel=result.descriptor(),
                ownership='all retirement destinations are physical shared inventory rows')
            _cancel(cancel)
            return updated, json.loads(_json(record))
