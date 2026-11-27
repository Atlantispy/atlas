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

from atlas_tectonics._validation import TectonicsError, read_array, scalar
from atlas_tectonics.thermal.magmatic_transfer import MagmaticInventory, PreparedMagmaticTransfer
from atlas_tectonics.materials.materials import MaterialCohort, _json, _name
from atlas_tectonics.integration.resources import DEFAULT_BUDGET, WorkBudget, select_budget
from atlas_tectonics.integration.resources import check_event_or_callable
from atlas_tectonics.subduction.materials import (
    DESTINATIONS, PreparedSubductionRetirement, SubductionInventory)


CAP = 128*1024**2
ROUND = 128*np.finfo(float).eps
KINDS = ('crust', 'mantle', 'source-solid', 'source-melt', 'reservoir',
         'intrusion', 'extrusion', 'export', 'accretion', 'deep-storage')
_DEFAULT_BUDGET = WorkBudget(CAP, parent=DEFAULT_BUDGET)


def _owner(budget):
    return WorkBudget(CAP, parent=_DEFAULT_BUDGET if budget is None else select_budget(budget))


def _sum(values):
    try:
        value = math.fsum(float(x) for x in values)
    except (ValueError, OverflowError) as exc:
        raise TectonicsError('W08 extensive account exceeds finite arithmetic') from exc
    return value


def _names(values, label):
    if type(values) is not tuple or not 1 <= len(values) <= 64:
        raise TectonicsError('one to 64 explicit '+label+' required')
    for value in values:
        _name(value, label)
    return values


def _identity(encoded, *arrays):
    digest = hashlib.sha256(encoded)
    for array in arrays:
        digest.update(_json((array.shape, array.dtype.str)))
        digest.update(memoryview(array).cast('B'))
    return digest.hexdigest()


def _keep(array, owner):
    # Each small retained payload owns its lease. Borrowing an earlier state's
    # bytes would pin this state's reservation until that earlier state dies.
    value = np.frombuffer(array.tobytes(order='C'), dtype=np.float64).reshape(array.shape)
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
        self._initialise(node_ids, node_kinds, component_ids, component_mass_kg,
                         enthalpy_j, source_id, enthalpy_source, time_s,
                         formation_time_s, origin_ids, budget, cancel, None)

    def _initialise(self, node_ids, node_kinds, component_ids, component_mass_kg,
                    enthalpy_j, source_id, enthalpy_source, time_s,
                    formation_time_s, origin_ids, budget, cancel, known_mass):
        check_event_or_callable(cancel, 'constitutive work cancelled')
        nodes = _names(node_ids, 'node IDs')
        components = _names(component_ids, 'component IDs')
        count, kinds = len(nodes), node_kinds
        for origin in origin_ids:
            _name(origin, 'origin')
        _name(source_id, 'inventory source')
        _name(enthalpy_source, 'enthalpy convention')
        now = scalar(time_s, 'inventory time')
        owner = _owner(budget)
        with owner.reserve(96*count*(len(components)+4)+8192,
                           category='w08-inventory-input'):
            if known_mass is None:
                c = read_array(component_mass_kg, 'component mass', nonnegative=True)
                e = read_array(enthalpy_j, 'signed enthalpy')
                formation = read_array(formation_time_s, 'source formation times')
                mass = np.array([_sum(row) for row in c])
                if np.any((mass == 0) & (e != 0)):
                    raise TectonicsError('empty stock cannot contain enthalpy or implicit throughflow')
            else:
                # retime carries issued immutable stocks forward and obtains independent retained leases.
                c, e, formation, mass = component_mass_kg, enthalpy_j, formation_time_s, known_mass
            record = dict(schema='atlas.w08-inventory.v1', node_ids=nodes,
                node_kinds=kinds, component_ids=components, origin_ids=origin_ids,
                formation_time_s=formation.tolist(), source_id=source_id,
                enthalpy_source=enthalpy_source, time_s=now)
            encoded = _json(record)
            values = dict(node_ids=nodes, node_kinds=kinds, component_ids=components,
                origin_ids=origin_ids, source_id=source_id, enthalpy_source=enthalpy_source,
                time_s=now, inventory_id=_identity(encoded, c, e), _record=encoded,
                _components=_keep(c, owner), _enthalpy=_keep(e, owner),
                _formation=_keep(formation, owner), _mass=_keep(mass, owner))
            lease = owner.reserve(len(encoded)+1024, category='w08-inventory-metadata')
            lease.__enter__()
            weakref.finalize(self, lease.__exit__, None, None, None)
            for key, value in values.items():
                object.__setattr__(self, key, value)
        check_event_or_callable(cancel, 'constitutive work cancelled')

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
        result = object.__new__(W08Inventory)
        result._initialise(self.node_ids, self.node_kinds, self.component_ids,
            self._components, self._enthalpy, self.source_id if source_id is None else source_id,
            self.enthalpy_source, now, self._formation, self.origin_ids, budget, cancel, self._mass)
        return result

    def _replace(self, c, e, time_s, source_id, budget, cancel):
        return W08Inventory(self.node_ids, self.node_kinds, self.component_ids, c, e,
            source_id=source_id, enthalpy_source=self.enthalpy_source, time_s=time_s,
            formation_time_s=self._formation, origin_ids=self.origin_ids,
            budget=budget, cancel=cancel)


def _selection(inventory, selected):
    _names(selected, 'selected node IDs')
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
        residuals.append(residual)
    return dict(component_residual_kg=residuals[:-1], enthalpy_residual_j=residuals[-1])


def advance_magmatic(inventory, selected_node_ids, rates_kg_s, duration_s, *,
                     source_id, heat_w=None, thermodynamics=None, context=None,
                     end_time_s=None, budget=None, cancel=None):
    """Map a finite magma segment into exact shared rows, retaining all others."""
    check_event_or_callable(cancel, 'constitutive work cancelled')
    indices = _selection(inventory, selected_node_ids)
    owner = _owner(budget)
    with owner.reserve(256*len(inventory.node_ids)*(len(inventory.component_ids)+4)+65536,
                       category='w08-magmatic-adapter'):
        mass = inventory._mass[indices]
        local = object.__new__(MagmaticInventory)
        local._initialise(selected_node_ids, tuple(inventory.node_kinds[i] for i in indices),
            inventory.component_ids, inventory._components[indices], inventory._enthalpy[indices],
            inventory.inventory_id, inventory.enthalpy_source, inventory.time_s, owner, cancel, mass)
        plan = object.__new__(PreparedMagmaticTransfer)
        plan._initialise(local, rates_kg_s, source_id, heat_w, thermodynamics, context, owner, cancel, mass)
        with plan:
            result = plan.evaluate(duration_s, end_time_s=end_time_s, cancel=cancel)
            c, e = inventory._components.copy(), inventory._enthalpy.copy()
            c[indices], e[indices] = result.remaining.component_mass_kg, result.remaining.enthalpy_j
            moved_c, moved_e, heat = (result.transferred_component_mass_kg,
                result.transferred_enthalpy_j, result.external_heat_j)
            account = _closure(inventory, c, e, heat, moved_c, moved_e)
            updated = inventory._replace(c, e, result.remaining.time_s, plan.plan_id, owner, cancel)
            kernel = result.descriptor()
            record = dict(operation='atlas.w08-inventory-magmatic.v1', source_id=source_id,
                initial_inventory_id=inventory.inventory_id, inventory_id=updated.inventory_id,
                selected_node_ids=selected_node_ids, duration_s=result.duration_s,
                plan_id=plan.plan_id, result_id=result.result_id, edge_ids=result.edge_ids,
                transferred_mass_kg=result.transferred_mass_kg.tolist(),
                transferred_component_mass_kg=moved_c.tolist(), transferred_enthalpy_j=moved_e.tolist(),
                external_heat_j=heat.tolist(), external_heat_total_j=_sum(heat),
                exhaustion_duration_s=plan.exhaustion_duration_s,
                exhausted_node_ids=kernel['exhausted_nodes'], account=account,
                kernel=kernel,
                ownership='shared inventory owns terminal stocks; edge transfers are receipts only')
            check_event_or_callable(cancel, 'constitutive work cancelled')
            return updated, json.loads(_json(record))


def advance_retirement(inventory, selected_node_ids, destination_ids, duration_s, *,
                       source_id, parameters, end_time_s=None, budget=None, cancel=None):
    """Debit finite crust/mantle cohorts and credit all three declared stores.

    ``parameters`` contains epoch_id and all explicit physical parameters of
    PreparedSubductionRetirement except destinations/source/budget/cancel. The
    caller's outer ExecutionContext verifies source/runtime identity.
    """
    check_event_or_callable(cancel, 'constitutive work cancelled')
    indices = _selection(inventory, selected_node_ids)
    destinations = [inventory.node_ids.index(node) for node in destination_ids]
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
            result = plan.evaluate(duration_s, end_time_s=end_time_s, cancel=cancel)
            c, e = inventory._components.copy(), inventory._enthalpy.copy()
            c[indices], e[indices] = result.remaining.component_mass_kg, result.remaining.enthalpy_j
            moved_c, moved_e = result.destination_component_mass_kg, result.destination_enthalpy_j
            for target, row in zip(destinations, range(3)):
                for k in range(len(inventory.component_ids)):
                    c[target, k] = _sum((c[target, k], *moved_c[row, :, k]))
                e[target] = _sum((e[target], *moved_e[row]))
            account = _closure(inventory, c, e, (), moved_c, moved_e)
            updated = inventory._replace(c, e, result.remaining.time_s, plan.plan_id, owner, cancel)
            kernel = result.descriptor()
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
                exhausted_node_ids=kernel['exhausted_cohort_ids'], account=account,
                source_cohorts=local.descriptor()['cohorts'], kernel=kernel,
                ownership='all retirement destinations are physical shared inventory rows')
            check_event_or_callable(cancel, 'constitutive work cancelled')
            return updated, json.loads(_json(record))
